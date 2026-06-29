"""Potion rankings — pickup%, win%, WAR, and a use rate per potion.

Unlike relics, potions are a genuine choice (you skip them) and they get
consumed, so we have more to measure than a relic:

  - **Pickup %** — of the times a potion was offered, how often I took it
    (`potion_choices` with was_picked). This is the pick-vs-skip signal.
  - **WAR** — on the picks, the same floor-conditional, survivorship-corrected
    baseline as cards: for each run that picked a potion at floor F,
    (win - baseline(character, F)), shrunk by k.
  - **Win %** — win rate of runs that picked the potion (shrunk).
  - **Use rate** — of the potions I acquired (picked + bought), how often I
    actually used one (`potion_used`). A "do I hoard potions?" signal; can read
    above 100% for potions also granted by relics/events (not counted as
    acquired), which is itself informative.

No Elo (kept out, like relics — potions aren't ranked against each other in a
way an Elo ladder captures cleanly). Engine is pure stdlib; reuses the card
engine's floor baseline (rankings.py).
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict

from . import rankings
from .names import pretty_potion_name
from .queries import apply_filters

WAR_SHRINKAGE_K = rankings.WAR_SHRINKAGE_K
WINRATE_PRIOR_M = rankings.WINRATE_PRIOR_M


def compute_potion_rankings(conn: sqlite3.Connection, filters: dict) -> dict:
    """Per-potion offered / picked / pickup% / win% / WAR / used / use-rate."""
    runs = rankings._filtered_runs(conn, filters)
    baselines = rankings._floor_baselines(runs)
    p0 = (sum(r["win"] for r in runs.values()) / len(runs)) if runs else 0.0

    where, params = apply_filters(filters)
    sql = (
        "SELECT pe.run_id, pe.potion_id, pe.floor, pe.event_type, pe.was_picked "
        f"FROM potion_events pe JOIN runs r ON r.run_id = pe.run_id {where}"
    )
    events = conn.execute(sql, params).fetchall()

    offered: dict = defaultdict(int)
    picked: dict = defaultdict(int)
    used: dict = defaultdict(int)
    bought: dict = defaultdict(int)
    W: dict = defaultdict(float)
    E: dict = defaultdict(float)
    war_n: dict = defaultdict(int)
    picked_runs: dict = defaultdict(set)

    for run_id, potion_id, floor, event_type, was_picked in events:
        run = runs.get(int(run_id))
        if run is None:
            continue
        if event_type == "offered":
            offered[potion_id] += 1
            if was_picked:
                picked[potion_id] += 1
                picked_runs[potion_id].add(int(run_id))
                W[potion_id] += run["win"]
                base = rankings._baseline_rate(baselines, run["character"], int(floor))
                if base is not None:
                    E[potion_id] += base
                    war_n[potion_id] += 1
        elif event_type == "used":
            used[potion_id] += 1
        elif event_type == "bought":
            bought[potion_id] += 1

    # win%-when-picked shrinks toward the grand mean of that quantity.
    total_picked_runs = sum(len(s) for s in picked_runs.values())
    total_picked_wins = sum(sum(runs[r]["win"] for r in s) for s in picked_runs.values())
    p_anchor = (total_picked_wins / total_picked_runs) if total_picked_runs else p0

    rows: list[dict] = []
    for pid in set(offered) | set(used) | set(bought):
        off = offered.get(pid, 0)
        pk = picked.get(pid, 0)
        n = war_n.get(pid, 0)
        war = (W[pid] - E[pid]) / (n + WAR_SHRINKAGE_K) if n else None
        prs = picked_runs.get(pid, set())
        rp = len(prs)
        wp = sum(runs[r]["win"] for r in prs)
        winrate = (wp + p_anchor * WINRATE_PRIOR_M) / (rp + WINRATE_PRIOR_M) if rp else None
        acquired = pk + bought.get(pid, 0)
        u = used.get(pid, 0)
        rows.append({
            "potion_id": pid,
            "potion": pretty_potion_name(pid),
            "offered": off,
            "picked": pk,
            "pickup_rate": (pk / off) if off else None,
            "runs_picked": rp,
            "wins_picked": wp,
            "winrate_shrunk": winrate,
            "war": war,
            "war_n": n,
            "used": u,
            "bought": bought.get(pid, 0),
            "use_rate": (u / acquired) if acquired else None,
        })

    rows.sort(key=lambda r: (r["war"] is None, -(r["war"] or 0.0), -r["offered"], r["potion"]))
    meta = {
        "n_runs": len(runs),
        "p0": p0,
        "p_anchor": p_anchor,
        "war_shrinkage_k": WAR_SHRINKAGE_K,
        "winrate_prior_m": WINRATE_PRIOR_M,
        "n_potions": len(rows),
        "n_events": len(events),
    }
    return {"rows": rows, "meta": meta}
