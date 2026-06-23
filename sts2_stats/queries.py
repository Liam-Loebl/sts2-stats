"""Filtered analytics queries over the runs / card_events / room_events tables.

This module exposes the read-side API used by the dashboard / CLI:

  - apply_filters(filters)      -> (sql_where_fragment, params)
  - topline_stats(conn, f)      -> dict of headline counts + win rate + streak
  - per_character_stats(conn,f) -> per-character runs / wins / win_rate / avg floors
  - win_rate_over_time(conn,f)  -> rolling win-rate series across chronological runs
  - damage_per_act(conn, f)     -> avg damage taken per (character, act)

All functions accept the standard `filters` dict:

    {
      "mode": "solo" | "coop" | "both",   # default "solo"
      "game_mode": "standard" | "all",      # default "standard"
      "include_abandoned": bool,            # default False
      "ascension_min": int,                 # default 0
      "character": str | None,              # default None (all characters)
      "build_ids": list[str] | None,        # default None (all patches); else
                                            #   restrict to these build_ids
    }

Defensive: when no runs match the filters, callers get zeros / empty lists
rather than exceptions. Pure stdlib (sqlite3 only); the open connection is
passed in by the caller so this module never opens or closes the DB.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any


# ---------------------------------------------------------------------------
# Filter -> SQL WHERE fragment
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "mode": "solo",
    "game_mode": "standard",
    "include_abandoned": False,
    "ascension_min": 0,
    "character": None,
    "build_ids": None,
}


def _merged(filters: dict | None) -> dict:
    """Return a copy of `filters` with any missing keys filled from defaults."""
    out = dict(_DEFAULTS)
    if filters:
        out.update(filters)
    return out


def apply_filters(filters: dict) -> tuple[str, list]:
    """Build a SQL WHERE clause + ordered params list from the filter dict.

    Every condition targets the runs table aliased as `r`. Returns
    ``(sql_fragment, params)`` where ``sql_fragment`` is either an empty
    string (no filters active) or starts with the literal ``WHERE ``.
    """
    f = _merged(filters)
    clauses: list[str] = []
    params: list = []

    mode = f.get("mode", "solo")
    if mode == "solo":
        clauses.append("r.is_multiplayer = ?")
        params.append(0)
    elif mode == "coop":
        clauses.append("r.is_multiplayer = ?")
        params.append(1)
    # "both" -> no filter

    game_mode = f.get("game_mode", "standard")
    if game_mode == "standard":
        clauses.append("r.game_mode = ?")
        params.append("standard")
    # "all" -> no filter

    if not f.get("include_abandoned", False):
        clauses.append("r.was_abandoned = ?")
        params.append(0)

    asc_min = f.get("ascension_min", 0) or 0
    if asc_min > 0:
        clauses.append("r.ascension >= ?")
        params.append(asc_min)

    character = f.get("character")
    if character is not None:
        clauses.append("r.character = ?")
        params.append(character)

    # Patch window: restrict to a set of build_ids (computed sidebar-side from a
    # chosen "from version onward" cutoff, since build_id can't be range-compared
    # in SQL). None / empty -> no restriction.
    build_ids = f.get("build_ids")
    if build_ids:
        placeholders = ",".join("?" * len(build_ids))
        clauses.append(f"r.build_id IN ({placeholders})")
        params.extend(build_ids)

    if not clauses:
        return "", []
    return "WHERE " + " AND ".join(clauses), params


# ---------------------------------------------------------------------------
# Topline stats
# ---------------------------------------------------------------------------

def topline_stats(conn: sqlite3.Connection, filters: dict) -> dict:
    """Return overall counts + win rate + best streak + most-played ascension.

    Best streak is the longest run of consecutive wins when runs are
    ordered chronologically (start_time ASC). Most-played ascension is
    the mode of the `ascension` column among filtered runs.
    """
    where, params = apply_filters(filters)
    sql = (
        "SELECT r.win, r.ascension "
        "FROM runs r "
        f"{where} "
        "ORDER BY r.start_time ASC"
    )
    rows = conn.execute(sql, params).fetchall()

    total = len(rows)
    if total == 0:
        return {
            "total_runs": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "best_streak": 0,
            "most_played_ascension": None,
        }

    wins = sum(1 for w, _ in rows if w == 1)
    losses = total - wins

    # Longest consecutive-win streak (chronological).
    best_streak = 0
    cur_streak = 0
    for w, _ in rows:
        if w == 1:
            cur_streak += 1
            if cur_streak > best_streak:
                best_streak = cur_streak
        else:
            cur_streak = 0

    # Most-played ascension (ignore NULLs; ties broken by Counter's insertion order,
    # which under ORDER BY start_time ASC is "earliest-played" — fine as a tiebreak).
    asc_counts = Counter(a for _, a in rows if a is not None)
    most_played_ascension = asc_counts.most_common(1)[0][0] if asc_counts else None

    return {
        "total_runs": total,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / total,
        "best_streak": best_streak,
        "most_played_ascension": most_played_ascension,
    }


# ---------------------------------------------------------------------------
# Per-character stats
# ---------------------------------------------------------------------------

def per_character_stats(conn: sqlite3.Connection, filters: dict) -> list[dict]:
    """One row per character with at least one matching run, sorted by runs desc.

    Each row has: character, runs, wins, win_rate, avg_floors_reached.
    """
    where, params = apply_filters(filters)
    sql = (
        "SELECT r.character, "
        "       COUNT(*)                       AS runs, "
        "       SUM(CASE WHEN r.win = 1 THEN 1 ELSE 0 END) AS wins, "
        "       AVG(r.floors_reached)          AS avg_floors "
        "FROM runs r "
        f"{where} "
        "GROUP BY r.character "
        "ORDER BY runs DESC, r.character ASC"
    )
    out: list[dict] = []
    for character, runs, wins, avg_floors in conn.execute(sql, params).fetchall():
        runs = int(runs or 0)
        wins = int(wins or 0)
        win_rate = (wins / runs) if runs else 0.0
        out.append(
            {
                "character": character,
                "runs": runs,
                "wins": wins,
                "win_rate": win_rate,
                "avg_floors_reached": float(avg_floors) if avg_floors is not None else 0.0,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Rolling win rate over time
# ---------------------------------------------------------------------------

def win_rate_over_time(
    conn: sqlite3.Connection, filters: dict, window: int = 20
) -> list[dict]:
    """Rolling win rate over a window of consecutive (chronological) runs.

    Each output row is the win rate over the previous `window` runs
    ending at that run_index (1-based after filters). The first
    (window - 1) runs are skipped so every reported value uses a full
    window. Returns [] if fewer than `window` filtered runs exist or if
    `window` is not positive.
    """
    if window <= 0:
        return []

    where, params = apply_filters(filters)
    sql = (
        "SELECT r.win, r.start_time "
        "FROM runs r "
        f"{where} "
        "ORDER BY r.start_time ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    n = len(rows)
    if n < window:
        return []

    wins = [int(w) for w, _ in rows]
    times = [int(t) for _, t in rows]

    # Rolling sum across the window.
    rolling = sum(wins[:window])
    out: list[dict] = [
        {
            "run_index": window,
            "win_rate": rolling / window,
            "n": window,
            "start_time": times[window - 1],
        }
    ]
    for i in range(window, n):
        rolling += wins[i] - wins[i - window]
        out.append(
            {
                "run_index": i + 1,
                "win_rate": rolling / window,
                "n": window,
                "start_time": times[i],
            }
        )
    return out


# ---------------------------------------------------------------------------
# Damage per act (per character)
# ---------------------------------------------------------------------------

def damage_per_act(conn: sqlite3.Connection, filters: dict) -> list[dict]:
    """Average damage taken per act, broken down by character.

    For each filtered run we sum `room_events.damage_taken` per
    (run, act_index). Acts the run never reached contribute no rows
    (so n_runs is correctly only the runs that reached that act).
    We then average those per-run sums per (character, act).

    Acts are reported as 1-based (act_index 0 -> act 1).
    Sorted by character, then act ascending.
    """
    where, params = apply_filters(filters)
    # Inner subquery: per-run, per-act damage totals (only acts touched by the run).
    sql = (
        "SELECT r.character, "
        "       per_run.act_index, "
        "       AVG(per_run.dmg) AS avg_damage, "
        "       COUNT(*)         AS n_runs "
        "FROM ( "
        "    SELECT re.run_id, re.act_index, SUM(re.damage_taken) AS dmg "
        "    FROM room_events re "
        "    GROUP BY re.run_id, re.act_index "
        ") AS per_run "
        "JOIN runs r ON r.run_id = per_run.run_id "
        f"{where} "
        "GROUP BY r.character, per_run.act_index "
        "ORDER BY r.character ASC, per_run.act_index ASC"
    )
    out: list[dict] = []
    for character, act_index, avg_damage, n_runs in conn.execute(sql, params).fetchall():
        out.append(
            {
                "character": character,
                "act": int(act_index) + 1,
                "avg_damage": float(avg_damage) if avg_damage is not None else 0.0,
                "n_runs": int(n_runs or 0),
            }
        )
    return out
