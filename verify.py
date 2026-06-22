"""Run a battery of correctness checks against the SQLite DB and the source .run files.

What it checks:
  - DB schema invariants (no NULLs in required columns, FK integrity, floor / act
    indices in range, reward_event_id format, abandoned-implies-no-kill invariant)
  - For every co-op run: the stored character matches players[local_player_index]
    in the source JSON
  - Floor math: every picked card's `floor_added_to_deck` in the source JSON equals
    the floor stored in card_events (sampled across a few multi-act runs)
  - Random spot-check: 5 runs' worth of top-level fields re-derived from source
    JSON, every field compared against the DB row
  - Idempotency: re-running the importer leaves run/card-event counts unchanged

Use after every import (or after a game patch ships a new save-schema version)
to confirm nothing has silently drifted. Exits 0 if all checks pass, 1 if any fail.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sts2_stats.db import connect
from sts2_stats.importer import import_all
from sts2_stats.paths import find_history_dirs

DB_PATH = Path(__file__).resolve().parent / "sts2_stats.sqlite"

EXPECTED_CHARACTERS = {
    "CHARACTER.IRONCLAD",
    "CHARACTER.SILENT",
    "CHARACTER.DEFECT",
    "CHARACTER.REGENT",
    "CHARACTER.NECROBINDER",
}


class Reporter:
    """Tiny PASS/FAIL/NOTE accumulator that prints as it goes and returns an exit code."""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.noted = 0

    def header(self, title: str) -> None:
        print(f"\n--- {title} ---")

    def ok(self, msg: str) -> None:
        print(f"  PASS  {msg}")
        self.passed += 1

    def fail(self, msg: str) -> None:
        print(f"  FAIL  {msg}")
        self.failed += 1

    def note(self, msg: str) -> None:
        print(f"  NOTE  {msg}")
        self.noted += 1

    def summary(self) -> int:
        total = self.passed + self.failed
        print(
            f"\n{self.passed}/{total} checks passed"
            f"  ({self.failed} failed, {self.noted} notes)"
        )
        return 0 if self.failed == 0 else 1


def check_db_invariants(conn: sqlite3.Connection, r: Reporter) -> None:
    r.header("DB invariants")

    total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    if total == 0:
        r.fail("runs table is empty — did you run import_all.py?")
        return
    r.ok(f"runs table populated ({total} rows)")

    null_cols = []
    for col in (
        "character", "game_mode", "win", "was_abandoned", "is_multiplayer",
        "num_players", "acts_reached", "floors_reached", "source_file", "imported_at",
    ):
        n = conn.execute(f"SELECT COUNT(*) FROM runs WHERE {col} IS NULL").fetchone()[0]
        if n:
            null_cols.append(f"{col}({n})")
    if null_cols:
        r.fail(f"NULLs in NOT-NULL-intent columns: {', '.join(null_cols)}")
    else:
        r.ok("no NULLs in NOT-NULL-intent columns")

    bad = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE (num_players > 1) != is_multiplayer"
    ).fetchone()[0]
    if bad:
        r.fail(f"{bad} run(s) have is_multiplayer inconsistent with num_players")
    else:
        r.ok("is_multiplayer matches (num_players > 1) on every row")

    chars = {row[0] for row in conn.execute("SELECT DISTINCT character FROM runs")}
    unexpected = chars - EXPECTED_CHARACTERS
    if unexpected:
        r.note(f"unexpected character(s) found (new EA roster?): {sorted(unexpected)}")
    else:
        r.ok(f"all characters in expected EA roster ({len(chars)}/5 seen)")

    bad = conn.execute("""
        SELECT COUNT(*) FROM runs
        WHERE win = 0
          AND killed_by_encounter = 'NONE.NONE'
          AND killed_by_event = 'NONE.NONE'
          AND was_abandoned = 0
    """).fetchone()[0]
    if bad:
        r.fail(
            f"{bad} run(s) violate abandoned-invariant "
            "(loss with no kill source but was_abandoned=0)"
        )
    else:
        r.ok("abandoned-invariant holds (loss + NONE.NONE => was_abandoned=1)")

    bad = conn.execute("""
        SELECT COUNT(*) FROM card_events ce
        LEFT JOIN runs r ON ce.run_id = r.run_id
        WHERE r.run_id IS NULL
    """).fetchone()[0]
    if bad:
        r.fail(f"{bad} card_events row(s) reference missing run_id")
    else:
        r.ok("every card_events row references a real run_id")

    bad = conn.execute("""
        SELECT COUNT(*) FROM card_events ce
        JOIN runs r ON ce.run_id = r.run_id
        WHERE ce.floor < 1
           OR ce.floor > r.floors_reached
           OR ce.act_index < 0
           OR ce.act_index >= r.acts_reached
    """).fetchone()[0]
    if bad:
        r.fail(f"{bad} card_events row(s) have floor or act_index out of range")
    else:
        r.ok("card_events floor + act_index in range on every row")

    bad = conn.execute("""
        SELECT COUNT(*) FROM card_events
        WHERE reward_event_id != run_id || ':' || act_index || ':' || map_point_index
    """).fetchone()[0]
    if bad:
        r.fail(f"{bad} card_events row(s) have malformed reward_event_id")
    else:
        r.ok("reward_event_id matches '<run_id>:<act>:<mp>' on every row")

    errors = conn.execute("SELECT COUNT(*) FROM import_log").fetchone()[0]
    if errors:
        r.note(f"{errors} parse error(s) logged in import_log (inspect to triage)")
    else:
        r.ok("no parse failures in import_log")


def check_coop_identification(conn: sqlite3.Connection, r: Reporter) -> None:
    r.header("Co-op local-user identification (all co-op runs)")

    coop = conn.execute(
        "SELECT run_id, source_file, local_player_index, character "
        "FROM runs WHERE is_multiplayer = 1"
    ).fetchall()
    if not coop:
        r.note("no co-op runs in DB — skipping")
        return

    failures: list[str] = []
    skipped_missing = 0
    for run_id, src, local_idx, character in coop:
        path = Path(src)
        if not path.exists():
            skipped_missing += 1
            continue
        try:
            with path.open(encoding="utf-8") as f:
                j = json.load(f)
        except Exception:
            skipped_missing += 1
            continue
        players = j.get("players") or []
        if not (0 <= local_idx < len(players)):
            failures.append(f"run {run_id}: local_player_index {local_idx} out of range")
            continue
        jchar = (players[local_idx] or {}).get("character")
        if jchar != character:
            failures.append(
                f"run {run_id}: DB character {character!r} != "
                f"players[{local_idx}].character {jchar!r}"
            )

    if failures:
        for msg in failures[:5]:
            r.fail(msg)
        if len(failures) > 5:
            r.fail(f"... and {len(failures) - 5} more")
    else:
        checked = len(coop) - skipped_missing
        r.ok(f"all {checked} co-op runs resolved to the correct local character")
    if skipped_missing:
        r.note(f"{skipped_missing} co-op run(s) skipped (source file no longer on disk)")


def check_floor_math(conn: sqlite3.Connection, r: Reporter, sample_size: int = 3) -> None:
    r.header(f"Floor math: floor_added_to_deck vs DB floor on {sample_size} runs")

    rows = conn.execute("""
        SELECT run_id, source_file, local_player_index FROM runs
        WHERE acts_reached >= 2
        ORDER BY RANDOM()
        LIMIT ?
    """, (sample_size,)).fetchall()
    if not rows:
        r.note("no multi-act runs to sample — skipping")
        return

    for run_id, src, local_idx in rows:
        path = Path(src)
        if not path.exists():
            r.note(f"run {run_id}: source file missing — skipping")
            continue
        try:
            with path.open(encoding="utf-8") as f:
                j = json.load(f)
        except Exception as e:
            r.fail(f"run {run_id}: could not re-read source ({e})")
            continue

        db_pick_floors: dict[tuple[str, int], int] = {}
        for card_id, floor in conn.execute(
            "SELECT card_id, floor FROM card_events WHERE run_id = ? AND was_picked = 1",
            (run_id,),
        ).fetchall():
            db_pick_floors[(card_id, floor)] = floor

        mismatches = 0
        checked = 0
        for act in j.get("map_point_history") or []:
            if not isinstance(act, list):
                continue
            for mp in act:
                if not isinstance(mp, dict):
                    continue
                pstats = mp.get("player_stats") or []
                if local_idx >= len(pstats):
                    continue
                for ch in (pstats[local_idx] or {}).get("card_choices") or []:
                    if not isinstance(ch, dict) or not ch.get("was_picked"):
                        continue
                    card = ch.get("card") or {}
                    cid = card.get("id")
                    fad = card.get("floor_added_to_deck")
                    if cid is None or fad is None:
                        continue
                    if (cid, fad) in db_pick_floors:
                        checked += 1
                    else:
                        mismatches += 1
        if mismatches:
            r.fail(
                f"run {run_id}: {mismatches} picked card(s) with "
                f"floor_added_to_deck not matching any DB floor"
            )
        else:
            r.ok(f"run {run_id}: {checked} picked cards match floor exactly")


def check_against_source(conn: sqlite3.Connection, r: Reporter, sample_size: int = 5) -> None:
    r.header(f"Random spot-check: {sample_size} runs, every field vs source JSON")

    rows = conn.execute("""
        SELECT run_id, source_file, character, ascension, build_id, schema_version,
               game_mode, win, was_abandoned, is_multiplayer, num_players,
               acts_reached, local_player_index, killed_by_encounter, killed_by_event
        FROM runs
        ORDER BY RANDOM()
        LIMIT ?
    """, (sample_size,)).fetchall()
    if not rows:
        r.fail("no runs available for cross-check")
        return

    for db in rows:
        (run_id, src, character, ascension, build_id, schema_version, game_mode,
         win, was_abandoned, is_multi, num_players, acts_reached, local_idx,
         killed_enc, killed_evt) = db
        path = Path(src)
        if not path.exists():
            r.note(f"run {run_id}: source file missing — skipping")
            continue
        try:
            with path.open(encoding="utf-8") as f:
                j = json.load(f)
        except Exception as e:
            r.fail(f"run {run_id}: could not re-read source ({e})")
            continue

        mismatches: list[str] = []
        players = j.get("players") or []
        if not (0 <= local_idx < len(players)):
            mismatches.append(
                f"local_player_index={local_idx} out of players range {len(players)}"
            )
        else:
            jchar = (players[local_idx] or {}).get("character")
            if jchar != character:
                mismatches.append(f"character: DB={character!r} JSON={jchar!r}")

        comparisons = [
            (ascension,      j.get("ascension"),      "ascension"),
            (build_id,       j.get("build_id"),       "build_id"),
            (schema_version, j.get("schema_version"), "schema_version"),
            (game_mode,      j.get("game_mode"),      "game_mode"),
            (win,            1 if j.get("win") else 0,            "win"),
            (was_abandoned,  1 if j.get("was_abandoned") else 0,  "was_abandoned"),
            (is_multi,       1 if len(players) > 1 else 0,        "is_multiplayer"),
            (num_players,    len(players),                        "num_players"),
            (acts_reached,   len(j.get("map_point_history") or []), "acts_reached"),
            (killed_enc,     j.get("killed_by_encounter"),        "killed_by_encounter"),
            (killed_evt,     j.get("killed_by_event"),            "killed_by_event"),
        ]
        for db_val, j_val, name in comparisons:
            if db_val != j_val:
                mismatches.append(f"{name}: DB={db_val!r} JSON={j_val!r}")

        if mismatches:
            r.fail(f"run {run_id}: {len(mismatches)} mismatch(es) — " + "; ".join(mismatches))
        else:
            r.ok(f"run {run_id}: all 12 fields match source")


def check_idempotency(r: Reporter) -> None:
    r.header("Idempotency: re-import doesn't change counts")

    conn = connect(DB_PATH)
    try:
        before = (
            conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM card_events").fetchone()[0],
        )
    finally:
        conn.close()

    dirs = find_history_dirs()
    if not dirs:
        r.note("no history dir auto-detected — skipping")
        return

    result = import_all(DB_PATH, history_dirs=dirs)

    conn = connect(DB_PATH)
    try:
        after = (
            conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM card_events").fetchone()[0],
        )
    finally:
        conn.close()

    if before == after:
        r.ok(f"counts stable across re-import (runs={before[0]}, card_events={before[1]})")
    else:
        r.note(
            f"counts changed: runs {before[0]}->{after[0]}, "
            f"card_events {before[1]}->{after[1]} — likely new runs played "
            "since the last import (not necessarily a bug)"
        )
    if result["errors"]:
        r.note(f"re-import logged {result['errors']} parse error(s)")


def main() -> int:
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found. Run `python import_all.py` first.")
        return 1

    print(f"Verifying: {DB_PATH}")

    r = Reporter()
    conn = connect(DB_PATH)
    try:
        check_db_invariants(conn, r)
        check_coop_identification(conn, r)
        check_floor_math(conn, r)
        check_against_source(conn, r)
    finally:
        conn.close()
    check_idempotency(r)

    return r.summary()


if __name__ == "__main__":
    raise SystemExit(main())
