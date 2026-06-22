"""Card Rankings board — pick%, win%, WAR, and Elo per card.

The statistical engine lives in sts2_stats/rankings.py (methodology locked
in SPEC §5.3/§5.4/§5.4a). This page is presentation only: controls, the
WAR-vs-Elo "overrated / underrated" insight, and the sortable table with
green->red WAR coloring and honest small-sample handling.
"""
from __future__ import annotations

import html
import math

import pandas as pd
import streamlit as st

import dashboard_common as dc
from sts2_stats import rankings
from sts2_stats.names import pretty_character_name
from sts2_stats.queries import apply_filters
from theme import CHARACTER_RANGE

palette = st.session_state["palette"]
filters = st.session_state["filters"]

dc.page_header("Card Rankings")


# ---------------------------------------------------------------------------
# Available acts (derived from data — never hardcode "3 acts")
# ---------------------------------------------------------------------------

def _available_acts(conn, f: dict) -> list[int]:
    where, params = apply_filters(f)
    clause = (where + " AND " if where else "WHERE ") + (
        "ce.source_type IN ('monster','elite','boss','ancient')"
    )
    sql = (
        "SELECT DISTINCT ce.act_index FROM card_events ce "
        "JOIN runs r ON r.run_id = ce.run_id " + clause
    )
    return sorted(int(a) + 1 for (a,) in conn.execute(sql, params).fetchall())


conn = dc.connect_db()
try:
    # --- character filter: Overall + per character (the board's own control) ---
    char_labels = ["Overall"] + [c.replace("CHARACTER.", "") for c in dc.CHARACTERS]
    _sidebar_char = filters.get("character")
    _default_char = "Overall" if not _sidebar_char else _sidebar_char.replace("CHARACTER.", "")
    char_choice = st.radio(
        "Character",
        char_labels,
        index=char_labels.index(_default_char) if _default_char in char_labels else 0,
        horizontal=True,
        key="_cr_char",
    )
    board_character = None if char_choice == "Overall" else f"CHARACTER.{char_choice}"
    board_filters = {**filters, "character": board_character}

    acts = _available_acts(conn, board_filters)

    # --- act / sort / sample-size controls ---
    c1, c2, c3 = st.columns([2, 2, 3], gap="medium")
    with c1:
        act_labels = ["Overall"] + [f"Act {a}" for a in acts]
        act_choice = st.radio(
            "Act", act_labels, index=0, horizontal=True, key="_cr_act"
        )
        act = None if act_choice == "Overall" else int(act_choice.split()[1])
    with c2:
        sort_choice = st.selectbox(
            "Sort by",
            ["WAR", "Elo vs Skip", "Pick %", "Win %", "Offers"],
            index=0, key="_cr_sort",
        )
    with c3:
        min_offers = st.slider(
            "Minimum times offered", 1, 40, 10, key="_cr_minoffers",
            help="Hide cards with too little data to read. Sample size (N) is "
                 "shown for every card that clears the bar.",
        )

    res = rankings.compute_rankings(conn, board_filters, act=act)
finally:
    conn.close()

rows = res["rows"]
skip_rows = res.get("skip_rows", [])
meta = res["meta"]


# ---------------------------------------------------------------------------
# Empty / no-data guards
# ---------------------------------------------------------------------------

if meta["n_runs"] == 0 or not rows:
    st.markdown(
        '<div class="empty-state" style="margin-top:1rem;">'
        "No in-scope card rewards for these filters yet."
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()

cards_shown = [r for r in rows if r["offers"] >= min_offers]
shown = cards_shown + skip_rows  # Skip rows are exempt from the offers gate


# ---------------------------------------------------------------------------
# WAR-vs-Elo insight — the headline (SPEC §5.5)
# ---------------------------------------------------------------------------

def _insight_panel(title: str, subtitle: str, picks: list[dict], kind: str) -> str:
    if not picks:
        body = (
            '<div class="cr-insight-empty">Not enough picked-and-offered cards '
            "yet — come back after more runs.</div>"
        )
    else:
        items = []
        for r in picks:
            war = r["war"]
            vs = r["elo_vs_skip"]
            war_s = f"{war:+.3f}" if war is not None else "—"
            items.append(
                f'<div class="cr-insight-row">'
                f'<span class="cr-insight-card">{html.escape(r["card"])}</span>'
                f'<span class="cr-insight-meta">{html.escape(r["character_name"])} · '
                f'pick {r["pick_rate"]:.0%} · WAR {war_s} · vs Skip {vs:+.0f}</span>'
                f"</div>"
            )
        body = "".join(items)
    accent = palette["negative"] if kind == "over" else palette["positive"]
    return (
        f'<div class="cr-insight" style="--cr-accent: {accent};">'
        f'<div class="cr-insight-title">{html.escape(title)}</div>'
        f'<div class="cr-insight-sub">{html.escape(subtitle)}</div>'
        f"{body}</div>"
    )


# Eligible = enough preference signal (offered a lot) AND enough outcome signal
# (picked enough that WAR isn't a coin flip).
elig = [
    r for r in rows
    if r["offers"] >= 15 and r["picks"] >= 5
    and r["war"] is not None and r["elo_vs_skip"] is not None
]
overrated = sorted([r for r in elig if r["war"] < 0], key=lambda r: -r["elo_vs_skip"])[:3]
underrated = sorted([r for r in elig if r["elo_vs_skip"] < 0], key=lambda r: -r["war"])[:3]

st.markdown(
    """
<style>
.cr-insight { background: var(--cr-surface); border: 1px solid var(--cr-border);
  border-left: 3px solid var(--cr-accent); border-radius: 12px; padding: 16px 18px; height: 100%; }
.cr-insight-title { font-size: 13px; font-weight: 600; color: var(--cr-text); }
.cr-insight-sub { font-size: 11px; color: var(--cr-text2); margin: 2px 0 12px 0; }
.cr-insight-row { display: flex; flex-direction: column; margin-bottom: 9px; }
.cr-insight-card { font-size: 13px; font-weight: 600; color: var(--cr-text); }
.cr-insight-meta { font-size: 11px; color: var(--cr-text2); font-variant-numeric: tabular-nums; }
.cr-insight-empty { font-size: 12px; color: var(--cr-text2); }
</style>
""".replace("var(--cr-surface)", palette["surface"])
   .replace("var(--cr-border)", palette["border"])
   .replace("var(--cr-text2)", palette["text_secondary"])
   .replace("var(--cr-text)", palette["text_primary"]),
    unsafe_allow_html=True,
)

dc.eyebrow("Where my picks and my results disagree")
i1, i2 = st.columns(2, gap="small")
with i1:
    st.markdown(
        _insight_panel(
            "Overrated by me",
            "I take these over Skip, but they don't win (high preference, negative WAR)",
            overrated, "over",
        ),
        unsafe_allow_html=True,
    )
with i2:
    st.markdown(
        _insight_panel(
            "Underrated by me",
            "Win when I take them, but I usually pass (positive WAR, below my Skip line)",
            underrated, "under",
        ),
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# The board table
# ---------------------------------------------------------------------------

dc.eyebrow(f"All cards ({len(cards_shown)} shown · offered ≥ {min_offers}×) + a Skip line per act")

_sort_key = {
    "WAR": ("war", False),
    "Elo vs Skip": ("elo_vs_skip", False),
    "Pick %": ("pick_rate", False),
    "Win %": ("winrate_shrunk", False),
    "Offers": ("offers", False),
}[sort_choice]


def _sortval(r, key):
    v = r[key]
    return v if v is not None else -math.inf


shown_sorted = sorted(shown, key=lambda r: _sortval(r, _sort_key[0]), reverse=not _sort_key[1])

def _num_or_nan(v):
    return v if v is not None else float("nan")


table = []
for r in shown_sorted:
    table.append({
        "Card": r["card"],
        "Char": r["character_name"],
        "Offers": _num_or_nan(r["offers"]),
        "Picks": _num_or_nan(r["picks"]),
        "Pick %": r["pick_rate"],
        "Win %": _num_or_nan(r["winrate_shrunk"]),
        "WAR": _num_or_nan(r["war"]),
        "Elo": round(r["elo"]) if r["elo"] is not None else float("nan"),
        "vs Skip": round(r["elo_vs_skip"]) if r["elo_vs_skip"] is not None else float("nan"),
        "Elo N": r["elo_n"],
    })

df = pd.DataFrame(table)


def _war_bg(v: float) -> str:
    """Diverging green(+)/red(-) background, centered at 0, clamped at ±0.15."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    m = max(-1.0, min(1.0, v / 0.15))
    alpha = 0.10 + 0.32 * abs(m)
    rgb = "63,185,80" if m >= 0 else "248,81,73"
    return f"background-color: rgba({rgb},{alpha:.3f})"


def _pct(v) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.0%}"


def _war_fmt(v) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:+.3f}"


def _int_or_dash(v) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.0f}"


def _signed_or_dash(v) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:+.0f}"


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# Pretty character name -> rgb, so the Card / Char cells can carry each
# character's identity color (the same hexes as the Overview character tiles).
_CHAR_RGB = {
    pretty_character_name(cid): _hex_to_rgb(col)
    for cid, col in zip(dc.CHARACTERS, CHARACTER_RANGE)
}


def _char_row_bg(row) -> list:
    """Tint the Card and Char cells with the row's character identity color."""
    rgb = _CHAR_RGB.get(row["Char"])
    styles = ["" for _ in row]
    if rgb:
        bg = f"background-color: rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, 0.22)"
        for col in ("Card", "Char"):
            styles[row.index.get_loc(col)] = bg
    return styles


styler = (
    df.style
    .apply(_char_row_bg, axis=1)
    .map(_war_bg, subset=["WAR"])
    .format({
        "Pick %": _pct,
        "Win %": _pct,
        "WAR": _war_fmt,
        "Offers": _int_or_dash,
        "Picks": _int_or_dash,
        "Elo": _int_or_dash,
        "vs Skip": _signed_or_dash,
        "Elo N": "{:.0f}",
    })
)

st.dataframe(
    styler,
    width="stretch",
    hide_index=True,
    height=560,
    column_config={
        "Card": st.column_config.TextColumn("Card", width="medium"),
        "Char": st.column_config.TextColumn("Char", width="small"),
        "Offers": st.column_config.TextColumn("Offers", help="Times this card was offered (sample size)."),
        "Picks": st.column_config.TextColumn("Picks", help="Times I took it."),
        "Pick %": st.column_config.TextColumn("Pick %", help="Picks ÷ Offers."),
        "Win %": st.column_config.TextColumn(
            "Win %", help="Win rate of runs where I took it, shrunk toward my overall "
                          "win rate so a 2-for-2 card doesn't read as 100%."),
        "WAR": st.column_config.TextColumn(
            "WAR", help="Wins Above Replacement: how much more I win when I take this card "
                        "vs. the average run that reached the same floor as that character. "
                        "Shrunk toward 0 for low samples. Green = wins more, red = wins less."),
        "Elo": st.column_config.TextColumn(
            "Elo", help="Preference rating from treating every reward as a mini-tournament. "
                        "Per-character pool, everyone starts at 1500. Shown only for cards that competed."),
        "vs Skip": st.column_config.TextColumn(
            "vs Skip", help="Elo minus this character's act-weighted Skip line (Skip is rated per act) — "
                            "the 'is it worth taking' number, shrunk toward the skip line for low match "
                            "counts. Positive = above my skip line. Shown only for cards that competed."),
        "Elo N": st.column_config.NumberColumn(
            "Elo N", help="Reward tournaments this card actually competed in (the Elo sample size)."),
    },
)


# ---------------------------------------------------------------------------
# Methodology + scope caption
# ---------------------------------------------------------------------------

with st.expander("How these numbers are computed"):
    st.markdown(
        f"""
**Scope.** Card rewards from monsters, elites, bosses, and Ancient choices
({meta['n_events']:,} card options across {meta['n_runs']} runs after filters).
Shop and event (`unknown`) rewards are excluded by default — shops record the
whole inventory across restocks, which would poison the preference math.

**WAR — Wins Above Replacement (does it *win*?).**
For every time I pick a card on a given floor, I compare the run's result to my
own win rate among runs of that character that *reached that same floor*. Pinning
the baseline to the floor strips out survivorship bias (a card only offered late
shouldn't get credit for the run already surviving that long). WAR is the average
of those per-pick lifts, shrunk toward 0 by {meta['war_shrinkage_k']:.0f} phantom
replacement-level picks so tiny samples don't show fake extremes.

**Elo — preference (do I *take* it?).**
Each reward is a mini-tournament: the card I pick beats every alternative,
including **Skip**, and the rating moves are summed (beating three options is a
stronger signal than beating one). Pools are per-character; Skip is a rated
entity **rated separately per act** (the value of skipping shifts from act 1 to
act 3), so the board shows a **Skip** line for each act, and a card's **vs Skip**
value (vs the act-weighted skip line) says whether I treat it as worth taking.
Step size K = {meta['elo_k']:.0f}. *vs Skip* is shrunk toward the skip line for
cards with few matches and shown only for cards that competed, so a single lucky
pick can't headline.

**The gap is the point.** High *vs Skip* + negative *WAR* = a card I overrate;
positive *WAR* + negative *vs Skip* = one I underrate. Both lists are at the top
of this page.

Sample sizes are still small ({meta['n_runs']} runs), so **N is shown on every
card** and the cards below the *Minimum times offered* bar are hidden rather than
shown at face value.
""")
