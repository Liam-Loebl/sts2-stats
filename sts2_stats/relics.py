"""Relic rankings — per-relic WAR (outcome only; no Elo, no pick%).

Relics are auto-acquired: there's no pick-vs-skip choice the way card rewards
have, so there's no revealed preference (Elo) signal and no pick rate. What we
*can* measure is outcome — when I obtain a relic (at the floor it drops), do I
win more than my own baseline for runs that reached that floor? That's WAR,
reusing the exact floor-conditional, survivorship-corrected baseline from the
card engine (rankings.py). One row per relic; the page's character control flows
through `apply_filters`, and the per-event char-conditional baseline keeps things
honest even when aggregating across characters in the Overall view.

Starting relics (floor_added_to_deck == 1, held by every run of a character)
land near WAR 0 by construction — their baseline is that character's whole
population — which is correct: a relic everyone always has carries no signal.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

from . import rankings
from .names import pretty_relic_name
from .queries import apply_filters

WAR_SHRINKAGE_K = rankings.WAR_SHRINKAGE_K   # phantom replacement-level obtains
WINRATE_PRIOR_M = rankings.WINRATE_PRIOR_M   # beta prior strength for win%


def compute_relic_rankings(conn: sqlite3.Connection, filters: dict) -> dict:
    """Per-relic obtain count, win%-when-obtained (shrunk), and WAR (shrunk)."""
    runs = rankings._filtered_runs(conn, filters)
    baselines = rankings._floor_baselines(runs)
    p0 = (sum(r["win"] for r in runs.values()) / len(runs)) if runs else 0.0

    where, params = apply_filters(filters)
    sql = (
        "SELECT re.run_id, re.relic_id, re.floor "
        f"FROM relic_events re JOIN runs r ON r.run_id = re.run_id {where}"
    )
    events = conn.execute(sql, params).fetchall()

    W: dict = defaultdict(float)   # sum of wins over runs that obtained the relic
    E: dict = defaultdict(float)   # sum of floor-conditional baselines (expected)
    N: dict = defaultdict(int)     # runs that obtained it (a relic is unique per run)
    wins: dict = defaultdict(int)
    for run_id, relic_id, floor in events:
        run = runs.get(int(run_id))
        if run is None:
            continue
        N[relic_id] += 1
        W[relic_id] += run["win"]
        wins[relic_id] += run["win"]
        base = rankings._baseline_rate(baselines, run["character"], int(floor))
        if base is not None:
            E[relic_id] += base

    # win%-when-obtained shrinks toward the grand mean of that quantity (the
    # no-effect level), falling back to p0 if there are no obtains at all.
    total_obtain = sum(N.values())
    p_anchor = (sum(wins.values()) / total_obtain) if total_obtain else p0

    rows: list[dict] = []
    for relic_id, n in N.items():
        diff = W[relic_id] - E[relic_id]
        w = wins[relic_id]
        rows.append({
            "relic_id": relic_id,
            "relic": pretty_relic_name(relic_id),
            "obtained": n,
            "wins": w,
            "winrate_raw": w / n,
            "winrate_shrunk": (w + p_anchor * WINRATE_PRIOR_M) / (n + WINRATE_PRIOR_M),
            "war_raw": diff / n,
            "war": diff / (n + WAR_SHRINKAGE_K),   # displayed (shrunk)
            "war_n": n,
        })

    rows.sort(key=lambda r: (-r["war"], -r["obtained"], r["relic"]))
    meta = {
        "n_runs": len(runs),
        "p0": p0,
        "p_anchor": p_anchor,
        "war_shrinkage_k": WAR_SHRINKAGE_K,
        "winrate_prior_m": WINRATE_PRIOR_M,
        "n_relics": len(rows),
        "n_events": len(events),
    }
    return {"rows": rows, "meta": meta}
