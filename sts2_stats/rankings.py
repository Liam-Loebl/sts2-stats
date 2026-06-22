"""Phase 3 card-rankings engine: pick%, win%-when-picked, WAR, and Elo per card.

The statistical methodology is locked in SPEC and implemented here verbatim:

  WAR  (§5.3) — outcome metric, survivorship-corrected.
      For each pick of card C on floor F in a run of character X:
        contribution to W = 1 if that run won else 0
        contribution to E = baseline(X, F) = P(win | character X reached floor F)
      WAR_raw(C)    = (W - E) / N            with N = number of picks of C
      WAR_shrunk(C) = (W - E) / (N + k)      k = WAR_SHRINKAGE_K phantom
                                             replacement-level (lift = 0) picks.
      The floor-conditional baseline strips out survivorship bias: a card only
      offered on floor 45 is judged against runs that already reached floor 45,
      not against all runs. Per-act WAR restricts the W/E/N sums to picks whose
      floor falls in that act.

  Elo  (§5.4) — preference metric, multi-way pairwise, summed, zero-sum.
      Each reward is a mini-tournament. The chosen option (a card, or SKIP when
      nothing was taken on a skippable reward) plays one match against every
      other option and the rating deltas are summed:
        a pick beats all N-1 alternatives + SKIP  -> a large up-move
        a pass loses one match to the taken card  -> a small down-move
      All pairwise `expected` scores use the ratings as they stood *before* the
      reward, then every delta is applied at once, so the result is independent
      of option order within a single reward. Ratings are per-character pools;
      SKIP is a rated entity per character (the "replacement line": cards above
      it are worth taking, below it usually a pass). Processed oldest->newest so
      an Elo-over-time trend is available later.

  Scope (§5.4a) — only source_type in {monster, elite, boss, ancient}. SKIP is a
      real option only on the skippable combat rewards (monster/elite/boss);
      `ancient` is a forced pick with no skip. Reward groups with more than one
      picked option (a real but rare game mechanic) are excluded from Elo only;
      they still contribute to WAR.

Pure stdlib. The caller passes an open connection and the standard `filters`
dict (see queries.apply_filters); this module never opens or closes the DB.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any

from . import reworks
from .names import pretty_card_name, pretty_character_name
from .queries import apply_filters

# --- scope (SPEC §5.4a) ----------------------------------------------------
IN_SCOPE_SOURCES = ("monster", "elite", "boss", "ancient")
# Skip is a real option only on skippable combat rewards. `ancient` is a forced
# pick (boon-style), so it never feeds a SKIP match.
ELO_SKIPPABLE_SOURCES = frozenset({"monster", "elite", "boss"})

# --- tunable constants (documented so they can be dialed deliberately) -----
WAR_SHRINKAGE_K = 10.0   # phantom replacement-level picks; pulls low-N WAR toward 0
WINRATE_PRIOR_M = 10.0   # beta-binomial prior strength for win%-when-picked
ELO_K = 24.0             # Elo step size per pairwise match
ELO_INITIAL = 1500.0     # starting rating for every card and for SKIP
ELO_SHRINKAGE_K = 10.0   # phantom 'no-preference' matches; shrinks elo_vs_skip toward the
                         # skip line at low match counts, mirroring WAR/win% shrinkage
ELO_MAX_REWARD_CARDS = 5  # a node offering more DISTINCT cards than this is the save
                          # flattening several card offers at one node (un-splittable);
                          # excluded from Elo, still counted in WAR/pick%
SKIP_KEY = "__SKIP__"    # sentinel entity id for the per-character skip rating


# ---------------------------------------------------------------------------
# Run set + floor baselines
# ---------------------------------------------------------------------------

def _filtered_runs(conn: sqlite3.Connection, filters: dict) -> dict[int, dict]:
    """Map run_id -> {character, win, floors_reached, start_time} for filtered runs."""
    where, params = apply_filters(filters)
    sql = (
        "SELECT r.run_id, r.character, r.win, r.floors_reached, r.start_time, r.build_id "
        f"FROM runs r {where}"
    )
    runs: dict[int, dict] = {}
    for run_id, character, win, floors_reached, start_time, build_id in conn.execute(sql, params):
        runs[int(run_id)] = {
            "character": character,
            "win": int(win or 0),
            "floors_reached": int(floors_reached or 0),
            "start_time": int(start_time or 0),
            "build_id": build_id,
        }
    return runs


def _floor_baselines(runs: dict[int, dict]) -> dict[str, dict]:
    """Per character, reverse-cumulative win rate by floor reached.

    baseline[char] = {"reached": [..], "won": [..], "max_f": int} where, for
    floor F (1-based), reached[F] = # runs of that character with
    floors_reached >= F and won[F] = # of those that won. The win rate is
    won[F] / reached[F]. (Counts are tiny — ~25 runs, ~49 floors — so the
    naive fill is instant and obviously correct.)
    """
    by_char: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for r in runs.values():
        by_char[r["character"]].append((r["floors_reached"], r["win"]))

    baselines: dict[str, dict] = {}
    for char, lst in by_char.items():
        max_f = max((fr for fr, _ in lst), default=0)
        reached = [0] * (max_f + 2)
        won = [0] * (max_f + 2)
        for floors_reached, win in lst:
            for F in range(1, floors_reached + 1):
                reached[F] += 1
                won[F] += win
        baselines[char] = {"reached": reached, "won": won, "max_f": max_f}
    return baselines


def _baseline_rate(baselines: dict, char: str, floor: int) -> float | None:
    """P(win | character reached `floor`), or None if no support."""
    b = baselines.get(char)
    if not b:
        return None
    F = max(1, min(floor, b["max_f"]))
    denom = b["reached"][F]
    if denom == 0:
        return None
    return b["won"][F] / denom


# ---------------------------------------------------------------------------
# Elo over the in-scope reward groups
# ---------------------------------------------------------------------------

def _expected(r_a: float, r_b: float) -> float:
    """Standard Elo expectation that A beats B."""
    return 1.0 / (1.0 + 10.0 ** ((r_b - r_a) / 400.0))


def _skip_key(act_no: int) -> str:
    """Per-act Skip entity id, e.g. '__SKIP__:1'. Skip is rated separately per
    act, since the value of skipping shifts from act 1 (lots worth taking) to
    act 3 (deck built, skipping more often correct)."""
    return f"{SKIP_KEY}:{act_no}"


def _run_elo(groups: list[dict], runs: dict[int, dict]) -> tuple[dict, dict]:
    """Chronological per-character Elo.

    `groups` is a list of dicts: {run_id, source, act_index, mpi, options}
    where options is a list of (card_id, was_picked). Returns:
      ratings[char][entity]  -> final rating (entity = card_id or a per-act skip
                                key from _skip_key(act_no))
      counts[char][entity]   -> number of reward groups the entity played in
    Skip is rated per act (one entity per act), so the caller reads each act's
    skip rating from ratings[char][_skip_key(act_no)].
    """
    ratings: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(lambda: ELO_INITIAL))
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    # Oldest -> newest by (run start_time, act, map point within act).
    def _order(g: dict) -> tuple:
        st = runs.get(g["run_id"], {}).get("start_time", 0)
        return (st, g["act_index"], g["mpi"])

    for g in sorted(groups, key=_order):
        run = runs.get(g["run_id"])
        if run is None:
            continue
        char = run["character"]
        act_no = g["act_index"] + 1  # Skip is rated per act (see _skip_key)
        # Collapse duplicate option rows: the same card_id can appear more than
        # once in one reward group (several reward screens share a map point under
        # reward_event_id = run:act:map_point_index, or a restock repeats a card).
        # Elo is a single mini-tournament over the DISTINCT options, so each card
        # must play the winner exactly once and be counted once — otherwise
        # duplicates inflate the winner's gain, the loser's drop, and elo_n, and a
        # picked card that reappears as an option self-matches. (WAR deliberately
        # counts every picked row; this dedup is Elo-local.)
        picked_flags: dict[str, int] = {}
        for cid, p in g["options"]:
            picked_flags[cid] = picked_flags.get(cid, 0) | (1 if p else 0)
        cards = list(picked_flags)
        n_picked = sum(picked_flags.values())  # number of DISTINCT picked cards

        # Multi-pick rewards are excluded from Elo (§5.4a); they stay in WAR.
        if n_picked > 1:
            continue

        # Oversized nodes (more distinct cards than a single reward can offer) are
        # the save flattening several card offers at one node into one list. They
        # can't be split into screens, and treating them as one tournament would
        # over-credit the pick, so they're excluded from Elo (still in WAR/pick%).
        if len(cards) > ELO_MAX_REWARD_CARDS:
            continue

        skippable = g["source"] in ELO_SKIPPABLE_SOURCES

        if n_picked == 1:
            winner = next(cid for cid, f in picked_flags.items() if f)
            losers = [cid for cid in cards if cid != winner]
            if skippable:
                losers.append(_skip_key(act_no))
        else:  # n_picked == 0
            if not skippable:
                # Forced-pick reward with nothing taken = run ended mid-reward;
                # no meaningful preference signal. Skip it.
                continue
            winner = _skip_key(act_no)
            losers = list(cards)

        if not losers:
            continue

        pool = ratings[char]
        r_w = pool[winner]
        deltas: dict[str, float] = defaultdict(float)
        for loser in losers:
            r_l = pool[loser]
            exp_w = _expected(r_w, r_l)          # pre-update ratings for every pairing
            deltas[winner] += ELO_K * (1.0 - exp_w)
            deltas[loser] += ELO_K * (0.0 - (1.0 - exp_w))
        for entity, d in deltas.items():
            pool[entity] += d

        # Group participation counts (for the N shown next to Elo).
        counts[char][winner] += 1
        for loser in losers:
            counts[char][loser] += 1

    return ratings, counts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_rankings(
    conn: sqlite3.Connection,
    filters: dict,
    act: int | None = None,
) -> dict:
    """Compute the full card-rankings table for the given filters.

    Rows are keyed by (card_id, character) — cards are character-specific, and
    keying by character keeps per-character Elo pools and baselines honest even
    for any neutral/colorless cards that appear under more than one character.

    `act` (1-based) restricts pick%/win%/WAR/Elo to rewards offered in that act;
    `act=None` uses all acts and additionally fills `war_by_act` with the per-act
    WAR splits. Returns {"rows": [...], "meta": {...}}.
    """
    runs = _filtered_runs(conn, filters)
    baselines = _floor_baselines(runs)
    p0 = (sum(r["win"] for r in runs.values()) / len(runs)) if runs else 0.0

    # In-scope card events for the filtered runs (optionally act-restricted).
    where, params = apply_filters(filters)
    qmarks = ",".join("?" * len(IN_SCOPE_SOURCES))
    clause = (where + " AND " if where else "WHERE ") + f"ce.source_type IN ({qmarks})"
    qparams = list(params) + list(IN_SCOPE_SOURCES)
    if act is not None:
        clause += " AND ce.act_index = ?"
        qparams.append(act - 1)
    sql = (
        "SELECT ce.run_id, ce.reward_event_id, ce.card_id, ce.source_type, "
        "       ce.floor, ce.act_index, ce.was_picked, ce.map_point_index "
        "FROM card_events ce JOIN runs r ON r.run_id = ce.run_id "
        f"{clause}"
    )
    events = conn.execute(sql, qparams).fetchall()

    # Per-(card, character) accumulators.
    offers: dict[tuple, int] = defaultdict(int)
    picks: dict[tuple, int] = defaultdict(int)
    war_W: dict[tuple, float] = defaultdict(float)
    war_E: dict[tuple, float] = defaultdict(float)
    war_N: dict[tuple, int] = defaultdict(int)
    war_act: dict[tuple, dict[int, list]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0, 0]))  # act -> [W,E,N]
    picked_runs: dict[tuple, set] = defaultdict(set)
    offers_act: dict[tuple, dict[int, int]] = defaultdict(lambda: defaultdict(int))  # (card,char) -> act -> offers
    acts_seen: set[int] = set()

    groups: dict[str, dict] = {}
    invalid_groups: set[str] = set()  # reward whose picked card was reworked-out -> stale

    for run_id, reward_id, card_id, source, floor, act_index, was_picked, mpi in events:
        run = runs.get(int(run_id))
        if run is None:
            continue
        char = run["character"]
        act_no = int(act_index) + 1
        # Card-rework valid-from filter: drop a reworked card's pre-rework events so
        # only its current form counts. If the *picked* option is reworked-out, the
        # whole reward is stale (drop from Elo/skip, don't turn it into a skip).
        if reworks.event_excluded(card_id, run["build_id"]):
            if was_picked:
                invalid_groups.add(reward_id)
            continue
        key = (card_id, char)
        offers[key] += 1
        offers_act[key][act_no] += 1
        acts_seen.add(act_no)

        g = groups.get(reward_id)
        if g is None:
            g = groups[reward_id] = {
                "run_id": int(run_id),
                "source": source,
                "act_index": int(act_index),
                "mpi": int(mpi),
                "floor": int(floor),
                "options": [],
            }
        g["options"].append((card_id, int(was_picked)))

        if was_picked:
            picks[key] += 1
            picked_runs[key].add(int(run_id))
            base = _baseline_rate(baselines, char, int(floor))
            war_W[key] += run["win"]
            if base is not None:
                war_E[key] += base
                war_N[key] += 1
                cell = war_act[key][act_no]
                cell[0] += run["win"]
                cell[1] += base
                cell[2] += 1

    valid_groups = [g for rid, g in groups.items() if rid not in invalid_groups]
    ratings, elo_counts = _run_elo(valid_groups, runs)

    def _skip_rating(ch: str, act_no: int) -> float:
        return ratings.get(ch, {}).get(_skip_key(act_no), ELO_INITIAL)

    def _skip_count(ch: str, act_no: int) -> int:
        return elo_counts.get(ch, {}).get(_skip_key(act_no), 0)

    # Win%-when-picked shrinks toward the pooled grand mean of THAT conditional
    # quantity, not the per-run win rate p0. Winning runs survive longer and so
    # generate more pick rows, so the average card is picked in a winning-skewed
    # subset of runs; shrinking toward p0 would bias every low-N card's win% low.
    total_wins_picked = sum(
        sum(runs[rid]["win"] for rid in prs) for prs in picked_runs.values()
    )
    total_runs_picked = sum(len(prs) for prs in picked_runs.values())
    p_winpicked = (total_wins_picked / total_runs_picked) if total_runs_picked else p0

    rows: list[dict] = []
    for key in offers:
        card_id, char = key
        n_off = offers[key]
        n_pick = picks.get(key, 0)
        n_war = war_N.get(key, 0)

        if n_war > 0:
            diff = war_W[key] - war_E[key]
            war_raw = diff / n_war
            war_shrunk = diff / (n_war + WAR_SHRINKAGE_K)
        else:
            war_raw = war_shrunk = None

        war_by_act: dict[int, dict] = {}
        for act_no, (w, e, n) in sorted(war_act[key].items()):
            if n > 0:
                war_by_act[act_no] = {
                    "war_raw": (w - e) / n,
                    "war_shrunk": (w - e) / (n + WAR_SHRINKAGE_K),
                    "n": n,
                }

        prs = picked_runs.get(key, set())
        runs_picked = len(prs)
        wins_picked = sum(runs[rid]["win"] for rid in prs)
        if runs_picked > 0:
            winrate_raw = wins_picked / runs_picked
            winrate_shrunk = (
                (wins_picked + p_winpicked * WINRATE_PRIOR_M) / (runs_picked + WINRATE_PRIOR_M)
            )
        else:
            winrate_raw = winrate_shrunk = None

        elo_n = elo_counts.get(char, {}).get(card_id, 0)
        if elo_n > 0:
            elo_val = ratings.get(char, {}).get(card_id, ELO_INITIAL)
            # Skip is rated per act; compare the card to the offer-weighted average
            # of the per-act skip lines for the act(s) it's actually offered in.
            oa = offers_act.get(key, {})
            den = sum(oa.values())
            weighted_skip = (
                sum(_skip_rating(char, a) * n for a, n in oa.items()) / den
                if den else ELO_INITIAL
            )
            vs_skip_raw = elo_val - weighted_skip
            # Shrink the preference toward the skip line (0) at low match count,
            # mirroring WAR/win% shrinkage so a 1-match card can't headline.
            vs_skip = vs_skip_raw * (elo_n / (elo_n + ELO_SHRINKAGE_K))
        else:
            # Never competed in an Elo match (its only in-scope rewards were
            # multi-pick groups or forced picks): no revealed preference at all,
            # so report no value rather than the prior's drift from the skip line.
            elo_val = None
            vs_skip_raw = None
            vs_skip = None

        rows.append({
            "card_id": card_id,
            "card": pretty_card_name(card_id),
            "character": char,
            "character_name": pretty_character_name(char),
            "offers": n_off,
            "picks": n_pick,
            "pick_rate": (n_pick / n_off) if n_off else 0.0,
            "runs_picked": runs_picked,
            "wins_picked": wins_picked,
            "winrate_raw": winrate_raw,
            "winrate_shrunk": winrate_shrunk,
            "war_raw": war_raw,
            "war": war_shrunk,           # the displayed WAR (shrunk)
            "war_n": n_war,
            "war_by_act": war_by_act,
            "elo": elo_val,              # raw rating, or None if it never competed
            "elo_vs_skip": vs_skip,      # shrunk preference vs the skip line, None if never competed
            "elo_vs_skip_raw": vs_skip_raw,
            "elo_n": elo_n,
        })

    # Explicit None check (not `r["war"] or -9`): a genuine WAR of exactly 0.0 is
    # falsy and must sort on its real value, above negatives — only no-data (None)
    # WAR falls to the bottom of its offers tier.
    rows.sort(key=lambda r: (-r["offers"], 9.0 if r["war"] is None else -r["war"], r["card"]))

    # Skip-as-a-choice stats per (character, act): treat skipping a skippable
    # reward like picking "Skip", so Skip gets the same offers / pick% / win% / WAR
    # columns as cards. Skippable = monster/elite/boss (ancient is a forced pick).
    skip_off: dict[tuple, int] = defaultdict(int)
    skip_pick: dict[tuple, int] = defaultdict(int)
    skip_W: dict[tuple, float] = defaultdict(float)
    skip_E: dict[tuple, float] = defaultdict(float)
    skip_N: dict[tuple, int] = defaultdict(int)
    skip_runs: dict[tuple, set] = defaultdict(set)
    for g in valid_groups:
        if g["source"] not in ELO_SKIPPABLE_SOURCES:
            continue
        run = runs.get(g["run_id"])
        if run is None:
            continue
        sk = (run["character"], g["act_index"] + 1)
        skip_off[sk] += 1
        if not any(p for _, p in g["options"]):  # nothing taken -> I skipped
            skip_pick[sk] += 1
            skip_W[sk] += run["win"]
            base = _baseline_rate(baselines, run["character"], g["floor"])
            if base is not None:
                skip_E[sk] += base
                skip_N[sk] += 1
            skip_runs[sk].add(g["run_id"])

    # Skip rows: one per (character, act) with skippable rewards, fully populated
    # like a card (Skip is the "is it worth taking?" baseline, so elo_vs_skip = 0).
    skip_rows: list[dict] = []
    for char in sorted({r["character"] for r in rows}):
        for act_no in sorted(acts_seen):
            sk = (char, act_no)
            n_off = skip_off.get(sk, 0)
            if n_off <= 0:
                continue
            n_pick = skip_pick.get(sk, 0)
            n_war = skip_N.get(sk, 0)
            if n_war > 0:
                diff = skip_W[sk] - skip_E[sk]
                s_war_raw, s_war = diff / n_war, diff / (n_war + WAR_SHRINKAGE_K)
            else:
                s_war_raw = s_war = None
            prs = skip_runs.get(sk, set())
            rp = len(prs)
            wp = sum(runs[r]["win"] for r in prs)
            if rp > 0:
                s_wr_raw = wp / rp
                s_wr = (wp + p_winpicked * WINRATE_PRIOR_M) / (rp + WINRATE_PRIOR_M)
            else:
                s_wr_raw = s_wr = None
            sn = _skip_count(char, act_no)
            skip_rows.append({
                "card_id": _skip_key(act_no), "card": f"Skip · Act {act_no}",
                "character": char, "character_name": pretty_character_name(char),
                "offers": n_off, "picks": n_pick,
                "pick_rate": (n_pick / n_off) if n_off else 0.0,
                "runs_picked": rp, "wins_picked": wp,
                "winrate_raw": s_wr_raw, "winrate_shrunk": s_wr,
                "war_raw": s_war_raw, "war": s_war, "war_n": n_war, "war_by_act": {},
                "elo": _skip_rating(char, act_no) if sn > 0 else None,
                "elo_vs_skip": 0.0, "elo_vs_skip_raw": 0.0, "elo_n": sn,
                "is_skip": True, "act": act_no,
            })

    skip_elo_meta = {
        char: {a: _skip_rating(char, a) for a in sorted(acts_seen) if _skip_count(char, a) > 0}
        for char in sorted({r["character"] for r in rows})
    }

    meta = {
        "n_runs": len(runs),
        "p0": p0,
        "p_winpicked": p_winpicked,
        "skip_elo": skip_elo_meta,
        "war_shrinkage_k": WAR_SHRINKAGE_K,
        "winrate_prior_m": WINRATE_PRIOR_M,
        "elo_k": ELO_K,
        "elo_shrinkage_k": ELO_SHRINKAGE_K,
        "elo_initial": ELO_INITIAL,
        "in_scope_sources": list(IN_SCOPE_SOURCES),
        "act": act,
        "n_cards": len(rows),
        "n_events": len(events),
    }
    return {"rows": rows, "skip_rows": skip_rows, "meta": meta}
