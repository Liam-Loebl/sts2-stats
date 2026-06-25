"""Card Rankings board — pick%, win%, WAR, and Elo-vs-Skip per card.

The statistical engine lives in sts2_stats/rankings.py (methodology locked
in SPEC §5.3/§5.4/§5.4a). This page is presentation only: the filter/sort
controls, a card search, and the sortable table with green->red WAR coloring,
per-character identity tint, and honest small-sample handling.
"""
from __future__ import annotations

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
mode = st.session_state["mode"]

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
# Table styling
# ---------------------------------------------------------------------------

st.markdown(
    """
<style>
.cr-caption { font-size: 12px; color: var(--cr-text2); margin: -0.45rem 0 0.7rem 0;
  font-variant-numeric: tabular-nums; }
.cr-table { max-height: 600px; overflow: auto; border: 1px solid var(--cr-border);
  border-radius: 12px; margin-top: 2px; box-shadow: var(--cr-shadow); }
.cr-table table { width: 100%; margin: 0; }
.cr-table tbody tr:hover td { background-color: var(--cr-hover); }
.cr-table::-webkit-scrollbar { width: 10px; height: 10px; }
.cr-table::-webkit-scrollbar-thumb { background: var(--cr-border); border-radius: 6px; }
</style>
""".replace("var(--cr-border)", palette["border"])
   .replace("var(--cr-text2)", palette["text_secondary"])
   .replace("var(--cr-hover)", palette["accent_muted"])
   .replace("var(--cr-shadow)", palette["shadow"]),
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# The board table
# ---------------------------------------------------------------------------

search = st.text_input(
    "Search cards", "", placeholder="Search cards by name…",
    key="_cr_search", label_visibility="collapsed",
).strip().lower()
display = [r for r in shown if not search or search in r["card"].lower()]
_n_disp = sum(1 for r in display if not r.get("is_skip"))
dc.eyebrow("All cards")
_caption = f"{_n_disp} shown · offered {min_offers}+ times · Skip line per act"
if search:
    _caption += f" · matching “{search}”"
st.markdown(f'<div class="cr-caption">{_caption}</div>', unsafe_allow_html=True)

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


shown_sorted = sorted(display, key=lambda r: _sortval(r, _sort_key[0]), reverse=not _sort_key[1])

# One search box (above) filters the table. When a search is active, offer a single
# shortcut to open the top-ranked match's detail page — so there's no second
# search control, but the board -> card-detail jump is kept.
if search:
    _top = next((r for r in shown_sorted if not r.get("is_skip")), None)
    if _top is not None and st.button(
        f"Open detail · {_top['card']} · {_top['character_name']} →", key="_cr_open_top"
    ):
        st.session_state["detail_card"] = (_top["card_id"], _top["character"])
        st.switch_page("views/card_detail.py")


def _num_or_nan(v):
    return v if v is not None else float("nan")


table = []
for r in shown_sorted:
    table.append({
        "Card": r["card"],
        "Char": r["character_name"],
        "Offers": _num_or_nan(r["offers"]),
        "Pick %": r["pick_rate"],
        "Win %": _num_or_nan(r["winrate_shrunk"]),
        "WAR": _num_or_nan(r["war"]),
        "Elo": round(r["elo"]) if r["elo"] is not None else float("nan"),
        "vs Skip": round(r["elo_vs_skip"]) if r["elo_vs_skip"] is not None else float("nan"),
    })

df = pd.DataFrame(table)


def _war_bg(v: float) -> str:
    """Diverging good/bad background from the palette (so it matches the metric
    deltas in both modes), centered at 0, clamped at ±0.15."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    m = max(-1.0, min(1.0, v / 0.15))
    alpha = 0.10 + 0.30 * abs(m)
    r, g, b = _hex_to_rgb(palette["positive"] if m >= 0 else palette["negative"])
    return f"background-color: rgba({r}, {g}, {b}, {alpha:.3f})"


def _pct(v) -> str:
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.0%}"


def _war_fmt(v) -> str:
    # Displayed in win-rate points (x100): a WAR of 0.022 reads as +2.2.
    return "—" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:+.1f}"


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


def _char_row_bg(row, alpha: float) -> list:
    """Tint the Card/Char cells with the character identity color. Skip rows are
    the baseline, not a card: italicize their label and don't tint them."""
    styles = ["" for _ in row]
    if str(row["Card"]).startswith("Skip"):
        styles[row.index.get_loc("Card")] = (
            f"font-style: italic; color: {palette['text_secondary']};"
        )
        return styles
    rgb = _CHAR_RGB.get(row["Char"]) if "Char" in row.index else None
    if rgb:
        bg = f"background-color: rgba({rgb[0]}, {rgb[1]}, {rgb[2]}, {alpha})"
        for col in ("Card", "Char"):
            if col in row.index:
                styles[row.index.get_loc(col)] = bg
    return styles


# Character tint: stronger in light mode (over white), a touch lighter in dark
# mode so it reads as the character's color, like the Overview damage-chart bars.
_char_alpha = 0.55 if mode == "light" else 0.45
styler = (
    df.style
    .apply(lambda row: _char_row_bg(row, _char_alpha), axis=1)
    .map(_war_bg, subset=["WAR"])
    .format({
        "Pick %": _pct,
        "Win %": _pct,
        "WAR": _war_fmt,
        "Offers": _int_or_dash,
        "Elo": _int_or_dash,
        "vs Skip": _signed_or_dash,
    })
)

# Render as themed HTML rather than st.dataframe: the dataframe grid follows the
# static config.toml theme (dark) and can't be re-themed per the light/dark
# toggle, so we render the Styler to HTML and color it from the active palette.
# Sorting is via the "Sort by" control above; column meanings are in the expander.
_num_cols = ["Offers", "Pick %", "Win %", "WAR", "Elo", "vs Skip"]
_left_th = "thead th.col0, thead th.col1"
styler = (
    styler
    .hide(axis="index")
    .set_properties(subset=_num_cols, **{"text-align": "right"})
    .set_table_styles([
        {"selector": "", "props": [
            ("width", "100%"), ("border-collapse", "collapse"), ("font-size", "13px"),
            ("background-color", palette["surface"]), ("color", palette["text_primary"]),
        ]},
        {"selector": "thead th", "props": [
            ("position", "sticky"), ("top", "0"), ("z-index", "1"),
            ("background-color", palette["surface"]), ("color", palette["text_secondary"]),
            ("font-weight", "600"), ("font-size", "11px"), ("text-transform", "uppercase"),
            ("letter-spacing", "0.04em"), ("text-align", "right"), ("white-space", "nowrap"),
            ("padding", "11px 12px"), ("border-bottom", f"1px solid {palette['border']}"),
            ("box-shadow", "0 3px 6px rgba(0,0,0,0.12)"),
        ]},
        {"selector": _left_th, "props": [("text-align", "left")]},
        {"selector": "tbody td", "props": [
            ("padding", "8px 12px"), ("white-space", "nowrap"),
            ("font-variant-numeric", "tabular-nums"),
            ("border-bottom", f"1px solid {palette['border']}"),
        ]},
        {"selector": "tbody td.col0", "props": [("font-weight", "600")]},
    ])
)
st.markdown(f'<div class="cr-table">{styler.to_html()}</div>', unsafe_allow_html=True)


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
replacement-level picks so tiny samples don't show fake extremes. It's shown in
win-rate points, so **+2.2** means +2.2 percentage points of win rate per pick
(not 0.022).

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

**Card versions.** When a card is reworked in a patch, its pre-rework rewards are
dropped (a hand-maintained valid-from list, `card_reworks.json`), so each card's
numbers reflect only its current form. The sidebar **Minimum patch** control can
further restrict the whole board to runs from a chosen game version onward.

**The gap is the point.** High *vs Skip* + negative *WAR* = a card I overrate;
positive *WAR* + negative *vs Skip* = one I underrate. Sort by WAR and scan the
*vs Skip* column — the cards where the two disagree are the ones worth a look.

Sample sizes are still small ({meta['n_runs']} runs), so **N is shown on every
card** and the cards below the *Minimum times offered* bar are hidden rather than
shown at face value.
""")
