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
  - Tone scan on README.md and SPEC.md against an extensible inventory of
    AI-prose tells, tuned for a plain-confident voice:
      1. em-dash overuse (3+ in a paragraph)
      2. negative-parallelism ('not just X' / 'not only X')
      3. promotional vocab (robust, leverage, delve, seamlessly, ...)
      4. meta-commentary openers (it's worth noting, notably,, importantly,, ...)
      5. inflated symbolism (stands as a testament, at the heart of, ...)
      6. conjunctive sentence-starters (Moreover,, Furthermore,, ...)
      7. rule-of-three cadence (3+ ', and' lists per paragraph)
      8. hedge-verb density (might/could/perhaps 3+ per paragraph)
      9. soft filler (actually, really, basically, literally, just)
      10. sentence-starting And/But/So/Well
      11. -ly adverb pile-ups (5+ per paragraph)
      12. bolding density (3+ **bold** spans per section)
      13. long paragraphs (6+ sentences)
      14. passive voice (was/is/are + past-participle)
      15. corporate jargon (going forward, deep dive, synergy, ...)
      16. AI flourishes (paints a picture, in essence, crucially,, ...)
      17. cliché openers ('in today's fast-paced world', 'long story short')
      18. 'whilst' (prefer 'while')
      19. italic-for-emphasis density (3+ *italic* spans per section)
    Hits are emitted as soft NOTEs (the run still passes) plus a per-category
    summary line, so it's easy to spot which pattern is dominating. The word
    and phrase lists live at the top of the relevant section in this file —
    edit them freely to tune.

Use after every import (or after a game patch ships a new save-schema version)
to confirm nothing has silently drifted. Exits 0 if all checks pass, 1 if any fail.
"""
from __future__ import annotations

import json
import re
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


def _strip_markdown_code(text: str) -> str:
    """Drop fenced code blocks and inline `code` so the tone scan doesn't
    false-positive on identifiers like 'leverage' or 'robust' that happen to
    appear inside code or commands."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`\n]+`", "", text)
    return text


# Word/phrase inventories for the tone scan. Lifted from the patterns the
# README audit (and the anthropic-skills:humanizer skill) flagged as common
# AI-prose tells. Tweak freely — edit this list and re-run verify.py.
_PROMO_VOCAB = [
    "robust", "leverage", "delve", "elegantly", "seamlessly",
    "comprehensive", "powerful", "meticulous", "foster", "illuminate",
    "holistic", "multifaceted", "nuanced", "groundbreaking",
    "cutting-edge", "state-of-the-art", "underscores",
]
_META_COMMENTARY = [
    "it's worth noting", "it is worth noting", "it's important to note",
    "it's important to remember", "notably,", "interestingly,",
    "importantly,", "of note,",
]
_INFLATED_PHRASES = [
    "stands as a testament", "speaks volumes", "at the heart of",
    "at the intersection of", "captures the essence", "paints a picture",
    "epitomizes", "embodies the spirit",
]
_CONJ_STARTERS = (
    "Moreover,", "Furthermore,", "Additionally,",
    "Consequently,", "Thus,", "Hence,",
)

# User-selected pattern inventories. Tuned for "Plain confident" voice:
# direct first-person, no flourish, short sentences. Edit freely — these are
# the knobs to tune the scan.
_HEDGE_VERBS = ("might", "could", "perhaps", "possibly", "may")
_SOFT_FILLER = ("actually", "really", "basically", "literally", "just")
_SENTENCE_START_CONJ = ("And", "But", "So", "Well")
_NON_ADVERB_LY = {  # -ly words that aren't adverbs — excluded from the count
    "only", "family", "supply", "rally", "ally", "lily", "italy",
    "lonely", "ugly", "holy", "early", "july", "rely", "imply",
    "apply", "reply", "comply", "multiply", "assembly", "anomaly",
    "fly", "ply", "ugly", "homely", "friendly", "lovely",
}
_CORPORATE_JARGON = (
    "going forward", "at the end of the day", "synergy", "deliverable",
    "circle back", "touch base", "deep dive", "wheelhouse",
    "low-hanging fruit", "move the needle",
)
_AI_FLOURISHES = (
    "paints a picture", "speaks volumes", "in essence", "crucially,",
    "fundamentally,", "ultimately,",
)
_CLICHE_OPENERS = (
    "in today's fast-paced world", "long story short",
    "to make a long story short", "without further ado",
)


def _scan_tone(text: str) -> list[str]:
    """Return human-readable hit descriptions for one document's prose."""
    text = _strip_markdown_code(text)
    low = text.lower()
    hits: list[str] = []

    # 1. Em-dash overuse: any paragraph with 3+ em-dashes.
    for para in text.split("\n\n"):
        n = para.count("—")
        if n >= 3:
            hits.append(f"em-dash overuse — {n} em-dashes in one paragraph")

    # 2. Negative-parallelism: 'not just X' / 'not only X' phrasing.
    for m in re.finditer(r"(?i)\bnot (just|only)\b[^.\n]{0,80}", text):
        snippet = m.group(0).strip().replace("\n", " ")
        hits.append(f"negative-parallelism — '{snippet[:70]}'")

    # 3. Promotional / AI vocab.
    for word in _PROMO_VOCAB:
        for m in re.finditer(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE):
            ctx = text[max(0, m.start() - 25): m.end() + 25].replace("\n", " ")
            hits.append(f"promo vocab '{m.group(0)}' — '...{ctx.strip()}...'")

    # 4. Meta-commentary openers.
    for phrase in _META_COMMENTARY:
        idx = low.find(phrase)
        if idx >= 0:
            ctx = text[max(0, idx - 10): idx + len(phrase) + 50].replace("\n", " ")
            hits.append(f"meta-commentary '{phrase}' — '...{ctx.strip()}...'")

    # 5. Inflated symbolism / vague-evocative phrases.
    for phrase in _INFLATED_PHRASES:
        idx = low.find(phrase)
        if idx >= 0:
            ctx = text[max(0, idx - 20): idx + len(phrase) + 40].replace("\n", " ")
            hits.append(f"inflated phrase '{phrase}' — '...{ctx.strip()}...'")

    # 6. Conjunctive sentence-starters at the start of a line.
    for line in text.split("\n"):
        first = line.lstrip()
        for word in _CONJ_STARTERS:
            if first.startswith(word):
                hits.append(f"conjunctive starter '{word.rstrip(',')}' — '{first[:70]}'")
                break

    # 7. Rule-of-three heuristic: paragraphs with 3+ ', and ' constructions.
    for para in text.split("\n\n"):
        n = len(re.findall(r",\s+and\s+", para))
        if n >= 3:
            hits.append(f"rule-of-three cadence — {n} ', and' lists in one paragraph")

    # 8. Hedging density: 3+ hedge verbs in one paragraph.
    for para in text.split("\n\n"):
        n = sum(
            len(re.findall(rf"\b{re.escape(w)}\b", para, flags=re.IGNORECASE))
            for w in _HEDGE_VERBS
        )
        if n >= 3:
            hits.append(
                f"hedge density — {n} hedge words (might/could/perhaps/...) in one paragraph"
            )

    # 9. Soft filler — each occurrence is a hit.
    for word in _SOFT_FILLER:
        for m in re.finditer(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE):
            ctx = text[max(0, m.start() - 25): m.end() + 25].replace("\n", " ")
            hits.append(f"soft filler '{m.group(0)}' — '...{ctx.strip()}...'")

    # 10. Sentence-starting And / But / So / Well.
    for m in re.finditer(r"(?:^|[.!?]\s+)(And|But|So|Well)\b", text):
        idx = m.start(1)
        ctx = text[max(0, idx - 20): idx + 60].replace("\n", " ")
        hits.append(f"sentence-starting '{m.group(1)}' — '...{ctx.strip()}...'")

    # 11. -ly adverb density: 5+ -ly adverbs in one paragraph.
    for para in text.split("\n\n"):
        matches = re.findall(r"\b\w{3,}ly\b", para)
        matches = [w for w in matches if w.lower() not in _NON_ADVERB_LY]
        if len(matches) >= 5:
            hits.append(f"-ly adverb density — {len(matches)} -ly words in one paragraph")

    # 12. Bolding density: 3+ **bold** spans within one Markdown section.
    sections = re.split(r"(?m)^#+\s.*$", text)
    for sec in sections:
        n = len(re.findall(r"\*\*[^*\n]+\*\*", sec))
        if n >= 3:
            hits.append(f"bolding density — {n} **bold** spans in one section")

    # 13. Long paragraphs: 6+ sentences (skip code/list/heading paragraphs).
    for para in text.split("\n\n"):
        first = para.strip().lstrip("> ")
        if not first or first.startswith(("#", "-", "*", "|", "```")):
            continue
        if re.match(r"^\d+\.\s", first):
            continue
        sentences = [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", first) if len(s) > 3]
        if len(sentences) >= 6:
            hits.append(f"long paragraph — {len(sentences)} sentences")

    # 14. Passive voice (heuristic): be-verb + past-participle.
    for m in re.finditer(
        r"\b(was|were|is|are|am|been|being|be)\s+(\w+ed|\w+en)\b",
        text, flags=re.IGNORECASE,
    ):
        snippet = m.group(0)
        ctx = text[max(0, m.start() - 15): m.end() + 25].replace("\n", " ")
        hits.append(f"passive voice '{snippet}' — '...{ctx.strip()}...'")

    # 15. Corporate jargon.
    for phrase in _CORPORATE_JARGON:
        idx = low.find(phrase)
        if idx >= 0:
            ctx = text[max(0, idx - 20): idx + len(phrase) + 30].replace("\n", " ")
            hits.append(f"corporate jargon '{phrase}' — '...{ctx.strip()}...'")

    # 16. AI flourishes (in addition to the inflated_phrases list above).
    for phrase in _AI_FLOURISHES:
        idx = low.find(phrase)
        if idx >= 0:
            ctx = text[max(0, idx - 20): idx + len(phrase) + 40].replace("\n", " ")
            hits.append(f"AI flourish '{phrase}' — '...{ctx.strip()}...'")

    # 17. Cliché openers.
    for phrase in _CLICHE_OPENERS:
        idx = low.find(phrase)
        if idx >= 0:
            ctx = text[max(0, idx - 10): idx + len(phrase) + 30].replace("\n", " ")
            hits.append(f"cliché opener '{phrase}' — '...{ctx.strip()}...'")

    # 18. 'whilst' — prefer 'while'.
    for m in re.finditer(r"\bwhilst\b", text, flags=re.IGNORECASE):
        ctx = text[max(0, m.start() - 25): m.end() + 25].replace("\n", " ")
        hits.append(f"'whilst' (prefer 'while') — '...{ctx.strip()}...'")

    # 19. Italic-for-emphasis density: 3+ *italic* or _italic_ spans per section.
    # Strip bold first so we don't double-count **...** as italic.
    sections = re.split(r"(?m)^#+\s.*$", text)
    for sec in sections:
        sec_no_bold = re.sub(r"\*\*[^*\n]+\*\*", "", sec)
        sec_no_bold = re.sub(r"__[^_\n]+__", "", sec_no_bold)
        n_star = len(re.findall(r"(?<![\*\w])\*([^\*\n]+?)\*(?![\*\w])", sec_no_bold))
        n_under = len(re.findall(r"(?<![\w_])_([^_\n]+?)_(?![\w_])", sec_no_bold))
        n = n_star + n_under
        if n >= 3:
            hits.append(f"italic density — {n} *italic* spans in one section")

    return hits


def _category_of(hit: str) -> str:
    """Pull the leading category label out of a hit string for the summary."""
    em = hit.find(" — ")
    q = hit.find(" '")
    if em < 0 and q < 0:
        return hit
    if em < 0:
        return hit[:q]
    if q < 0:
        return hit[:em]
    return hit[: min(em, q)]


def check_tone(r: Reporter, files: list[Path], cap: int = 50) -> None:
    r.header("Tone scan: AI-prose tells in markdown docs (soft warnings)")
    all_hits: list[str] = []
    scanned = 0
    for f in files:
        if not f.exists():
            r.note(f"{f.name}: file not found — skipping")
            continue
        scanned += 1
        for hit in _scan_tone(f.read_text(encoding="utf-8")):
            all_hits.append(f"{f.name}: {hit}")

    for hit in all_hits[:cap]:
        r.note(hit)
    if len(all_hits) > cap:
        r.note(f"... and {len(all_hits) - cap} more (capped at {cap})")

    if all_hits:
        from collections import Counter
        cats = Counter(_category_of(h.split(": ", 1)[1] if ": " in h else h) for h in all_hits)
        summary = ", ".join(f"{c}={n}" for c, n in cats.most_common())
        r.note(f"by category: {summary}")
        r.ok(f"tone scan complete — {len(all_hits)} note(s) above for review")
    else:
        r.ok(f"no AI-tone tells found in {scanned} file(s)")


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
    check_tone(r, [DB_PATH.parent / "README.md", DB_PATH.parent / "SPEC.md"])

    return r.summary()


if __name__ == "__main__":
    raise SystemExit(main())
