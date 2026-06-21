"""SQLite schema + connection helpers + sanity-report queries.

Phase 1 tables:
  runs         — one row per imported .run file (local-user perspective for co-op)
  card_events  — one row per *option* per reward (group by reward_event_id to
                 reconstruct a single reward's full choice set; Skip = a reward
                 group with no was_picked=1)
  import_log   — quarantine log: one row per .run file that failed to parse

The DB is disposable. Always rebuildable from the source .run files via
import_all.py. Idempotent upsert is keyed on the run_id (= run's start_time).
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id              INTEGER PRIMARY KEY,           -- = start_time (unix)
    seed                TEXT,
    start_time          INTEGER NOT NULL,
    run_time            INTEGER,
    character           TEXT NOT NULL,                 -- local user's character
    ascension           INTEGER,
    build_id            TEXT,
    schema_version      INTEGER,
    game_mode           TEXT NOT NULL,                 -- "standard" | "custom" | ...
    win                 INTEGER NOT NULL,              -- 0/1
    was_abandoned       INTEGER NOT NULL,              -- 0/1
    is_multiplayer      INTEGER NOT NULL,              -- 0/1 (players length > 1)
    num_players         INTEGER NOT NULL,
    acts_reached        INTEGER NOT NULL,              -- = len(map_point_history)
    floors_reached      INTEGER NOT NULL,              -- = sum of per-act map_point counts
    killed_by_encounter TEXT,
    killed_by_event     TEXT,
    local_player_index  INTEGER NOT NULL,              -- index into players[] for local user
    source_file         TEXT NOT NULL,
    imported_at         TEXT NOT NULL                  -- ISO8601 UTC
);

CREATE INDEX IF NOT EXISTS idx_runs_character ON runs(character);
CREATE INDEX IF NOT EXISTS idx_runs_ascension ON runs(ascension);
CREATE INDEX IF NOT EXISTS idx_runs_mode      ON runs(game_mode);
CREATE INDEX IF NOT EXISTS idx_runs_multi     ON runs(is_multiplayer);
CREATE INDEX IF NOT EXISTS idx_runs_build     ON runs(build_id);

CREATE TABLE IF NOT EXISTS card_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           INTEGER NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    reward_event_id  TEXT NOT NULL,                    -- "<run_id>:<act_index>:<map_point_index>"
    act_index        INTEGER NOT NULL,                 -- 0-based
    map_point_index  INTEGER NOT NULL,                 -- 0-based within act
    floor            INTEGER NOT NULL,                 -- 1-based, cumulative across acts
    source_type      TEXT NOT NULL,                    -- map_point_type (monster/elite/boss/shop/ancient/unknown)
    card_id          TEXT NOT NULL,
    was_picked       INTEGER NOT NULL                  -- 0/1
);

CREATE INDEX IF NOT EXISTS idx_cev_run    ON card_events(run_id);
CREATE INDEX IF NOT EXISTS idx_cev_card   ON card_events(card_id);
CREATE INDEX IF NOT EXISTS idx_cev_floor  ON card_events(floor);
CREATE INDEX IF NOT EXISTS idx_cev_act    ON card_events(act_index);
CREATE INDEX IF NOT EXISTS idx_cev_reward ON card_events(reward_event_id);
CREATE INDEX IF NOT EXISTS idx_cev_picked ON card_events(was_picked);

CREATE TABLE IF NOT EXISTS import_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    error       TEXT NOT NULL,
    logged_at   TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open (and create-if-needed) the SQLite DB with sane defaults."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


def upsert_run(conn: sqlite3.Connection, run_row: dict, card_event_rows: list[dict]) -> None:
    """Insert-or-replace a run + its card events atomically.

    Idempotent: re-importing the same file leaves the DB identical (the
    ON DELETE CASCADE wipes prior card_events for the same run_id first).
    """
    cur = conn.cursor()
    cur.execute("DELETE FROM runs WHERE run_id = ?", (run_row["run_id"],))
    cur.execute(
        """
        INSERT INTO runs (
            run_id, seed, start_time, run_time, character, ascension, build_id,
            schema_version, game_mode, win, was_abandoned, is_multiplayer,
            num_players, acts_reached, floors_reached, killed_by_encounter,
            killed_by_event, local_player_index, source_file, imported_at
        ) VALUES (
            :run_id, :seed, :start_time, :run_time, :character, :ascension, :build_id,
            :schema_version, :game_mode, :win, :was_abandoned, :is_multiplayer,
            :num_players, :acts_reached, :floors_reached, :killed_by_encounter,
            :killed_by_event, :local_player_index, :source_file, :imported_at
        )
        """,
        run_row,
    )
    if card_event_rows:
        cur.executemany(
            """
            INSERT INTO card_events (
                run_id, reward_event_id, act_index, map_point_index, floor,
                source_type, card_id, was_picked
            ) VALUES (
                :run_id, :reward_event_id, :act_index, :map_point_index, :floor,
                :source_type, :card_id, :was_picked
            )
            """,
            card_event_rows,
        )


def log_import_error(conn: sqlite3.Connection, source_file: str, error: str, when: str) -> None:
    conn.execute(
        "INSERT INTO import_log (source_file, error, logged_at) VALUES (?, ?, ?)",
        (source_file, error, when),
    )


# ----- sanity report -----------------------------------------------------

def _scalar(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def sanity_report(conn: sqlite3.Connection) -> dict:
    """Return key topline counts so we can eyeball them against the recon."""
    out: dict = {}
    out["total_runs"]       = _scalar(conn, "SELECT COUNT(*) FROM runs")
    out["wins"]             = _scalar(conn, "SELECT COUNT(*) FROM runs WHERE win = 1")
    out["losses"]           = _scalar(conn, "SELECT COUNT(*) FROM runs WHERE win = 0")
    out["abandoned"]        = _scalar(conn, "SELECT COUNT(*) FROM runs WHERE was_abandoned = 1")
    out["multiplayer"]      = _scalar(conn, "SELECT COUNT(*) FROM runs WHERE is_multiplayer = 1")
    out["solo"]             = _scalar(conn, "SELECT COUNT(*) FROM runs WHERE is_multiplayer = 0")
    out["card_events"]      = _scalar(conn, "SELECT COUNT(*) FROM card_events")
    out["card_picks"]       = _scalar(conn, "SELECT COUNT(*) FROM card_events WHERE was_picked = 1")
    out["import_errors"]    = _scalar(conn, "SELECT COUNT(*) FROM import_log")

    # Topline solo-standard-non-abandoned win rate (recon expects ~53.8% = 49/91)
    filt = "is_multiplayer = 0 AND game_mode = 'standard' AND was_abandoned = 0"
    out["solo_std_total"]   = _scalar(conn, f"SELECT COUNT(*) FROM runs WHERE {filt}")
    out["solo_std_wins"]    = _scalar(conn, f"SELECT COUNT(*) FROM runs WHERE {filt} AND win = 1")
    out["solo_std_losses"]  = _scalar(conn, f"SELECT COUNT(*) FROM runs WHERE {filt} AND win = 0")
    if out["solo_std_total"]:
        out["solo_std_winrate"] = out["solo_std_wins"] / out["solo_std_total"]
    else:
        out["solo_std_winrate"] = None

    out["by_character"] = conn.execute(
        "SELECT character, COUNT(*) FROM runs GROUP BY character ORDER BY COUNT(*) DESC"
    ).fetchall()
    out["by_ascension"] = conn.execute(
        "SELECT ascension, COUNT(*) FROM runs GROUP BY ascension ORDER BY ascension"
    ).fetchall()
    out["by_game_mode"] = conn.execute(
        "SELECT game_mode, COUNT(*) FROM runs GROUP BY game_mode ORDER BY COUNT(*) DESC"
    ).fetchall()
    out["by_schema"] = conn.execute(
        "SELECT schema_version, COUNT(*) FROM runs GROUP BY schema_version ORDER BY schema_version"
    ).fetchall()
    out["by_build_top"] = conn.execute(
        "SELECT build_id, COUNT(*) FROM runs GROUP BY build_id ORDER BY COUNT(*) DESC LIMIT 15"
    ).fetchall()
    return out


def print_sanity_report(report: dict) -> None:
    print("===== SANITY REPORT =====")
    print(f"Total runs imported:       {report['total_runs']}")
    print(f"  Solo:                    {report['solo']}")
    print(f"  Co-op:                   {report['multiplayer']}")
    print(f"  Wins / Losses:           {report['wins']} / {report['losses']}")
    print(f"  Abandoned:               {report['abandoned']}")
    print(f"Card events stored:        {report['card_events']}  (picks: {report['card_picks']})")
    print(f"Import errors logged:      {report['import_errors']}")
    print()
    if report["solo_std_winrate"] is not None:
        print(f"Solo / standard / non-abandoned:")
        print(f"  {report['solo_std_wins']}W / {report['solo_std_losses']}L  "
              f"(n={report['solo_std_total']}, win rate = {report['solo_std_winrate']:.1%})")
        print(f"  RECON BASELINE expected:  49W / 42L (n=91, 53.8%)")
    print()
    print("By character:")
    for char, n in report["by_character"]:
        print(f"  {char:<25} {n}")
    print()
    print("By ascension:")
    for asc, n in report["by_ascension"]:
        print(f"  A{asc:<3} {n}")
    print()
    print("By game_mode:")
    for mode, n in report["by_game_mode"]:
        print(f"  {mode:<10} {n}")
    print()
    print("By schema_version:")
    for sv, n in report["by_schema"]:
        print(f"  v{sv} {n}")
    print()
    print("By build_id (top 15):")
    for build, n in report["by_build_top"]:
        print(f"  {build:<10} {n}")
