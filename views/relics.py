"""Relics page — every relic I've obtained, ranked by WAR.

Relics are auto-taken, so (unlike the card board) there's no Elo or pick rate —
just outcome: WAR (win-rate points above my floor-conditional baseline) plus how
often I obtained it and my win rate when I did. Themed HTML table (Styler) so it
follows the light/dark toggle, with green->red WAR coloring and a sample floor.
Engine: sts2_stats/relics.py.
"""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st

import dashboard_common as dc
from sts2_stats import relics

palette = st.session_state["palette"]
filters = st.session_state["filters"]
mode = st.session_state["mode"]

dc.page_header("Relics")


# ---------------------------------------------------------------------------
# Controls
# ---------------------------------------------------------------------------

char_labels = ["Overall"] + [c.replace("CHARACTER.", "") for c in dc.CHARACTERS]
char_choice = st.radio(
    "Character", char_labels, index=0, horizontal=True, key="_relic_char"
)
relic_character = None if char_choice == "Overall" else f"CHARACTER.{char_choice}"
relic_filters = {**filters, "character": relic_character}

c1, c2 = st.columns([2, 3], gap="medium")
with c1:
    sort_choice = st.selectbox(
        "Sort by", ["WAR", "Obtained", "Win %"], index=0, key="_relic_sort"
    )
with c2:
    min_obt = st.slider(
        "Minimum times obtained", 1, 30, 5, key="_relic_minobt",
        help="Hide relics with too little data to read. N is shown on every row.",
    )

conn = dc.connect_db()
try:
    res = relics.compute_relic_rankings(conn, relic_filters)
finally:
    conn.close()

rows = res["rows"]
meta = res["meta"]

if meta["n_runs"] == 0 or not rows:
    st.markdown(
        '<div class="empty-state" style="margin-top:1rem;">'
        "No relic data for these filters yet.</div>",
        unsafe_allow_html=True,
    )
    st.stop()


# ---------------------------------------------------------------------------
# Table styling (themed; follows light/dark like the card board)
# ---------------------------------------------------------------------------

st.markdown(
    """
<style>
.cr-caption { font-size: 12px; color: var(--c-text2); margin: -0.45rem 0 0.7rem 0;
  font-variant-numeric: tabular-nums; }
.relic-table { max-height: 600px; overflow: auto; border: 1px solid var(--c-border);
  border-radius: 12px; box-shadow: var(--c-shadow); margin-top: 2px; }
.relic-table table { width: 100%; border-collapse: collapse;
  font-variant-numeric: tabular-nums; }
.relic-table thead th { position: sticky; top: 0; background: var(--c-surface);
  color: var(--c-text2); text-align: right; font-weight: 600; font-size: 12px;
  padding: 10px 14px; border-bottom: 1px solid var(--c-border); box-shadow: 0 1px 0 var(--c-border); }
.relic-table thead th:first-child { text-align: left; }
.relic-table tbody td { padding: 9px 14px; text-align: right; color: var(--c-text);
  border-bottom: 1px solid var(--c-border); font-size: 13px; }
.relic-table tbody td:first-child { text-align: left; font-weight: 500; }
.relic-table tbody tr:hover td { background-color: var(--c-hover); }
.relic-table::-webkit-scrollbar { width: 10px; height: 10px; }
.relic-table::-webkit-scrollbar-thumb { background: var(--c-border); border-radius: 6px; }
</style>
""".replace("var(--c-border)", palette["border"])
   .replace("var(--c-text2)", palette["text_secondary"])
   .replace("var(--c-text)", palette["text_primary"])
   .replace("var(--c-surface)", palette["surface"])
   .replace("var(--c-hover)", palette["accent_muted"])
   .replace("var(--c-shadow)", palette["shadow"]),
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Filter / search / sort -> table
# ---------------------------------------------------------------------------

shown = [r for r in rows if r["obtained"] >= min_obt]
search = st.text_input(
    "Search relics", "", placeholder="Search relics by name…",
    key="_relic_search", label_visibility="collapsed",
).strip().lower()
display = [r for r in shown if not search or search in r["relic"].lower()]

_sort_key = {"WAR": "war", "Obtained": "obtained", "Win %": "winrate_shrunk"}[sort_choice]
display = sorted(
    display, key=lambda r: (r[_sort_key] if r[_sort_key] is not None else -math.inf),
    reverse=True,
)

dc.eyebrow("All relics")
_caption = f"{len(display)} shown · obtained {min_obt}+ times · WAR in win-rate points"
if search:
    _caption += f" · matching “{search}”"
st.markdown(f'<div class="cr-caption">{_caption}</div>', unsafe_allow_html=True)

if not display:
    st.markdown(
        '<div class="empty-state">No relics clear the current filters.</div>',
        unsafe_allow_html=True,
    )
    st.stop()


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


_POS = _hex_to_rgb(palette["positive"])
_NEG = _hex_to_rgb(palette["negative"])


def _war_bg(pct) -> str:
    """Green->red wash by WAR magnitude (pct is WAR in win-rate points)."""
    if pct is None or (isinstance(pct, float) and math.isnan(pct)):
        return ""
    frac = max(-1.0, min(1.0, pct / 8.0))
    r, g, b = _POS if frac >= 0 else _NEG
    return f"background-color: rgba({r},{g},{b},{min(0.45, abs(frac) * 0.45):.3f});"


df = pd.DataFrame([
    {
        "Relic": r["relic"],
        "Obtained": r["obtained"],
        "Win %": r["winrate_shrunk"] * 100 if r["winrate_shrunk"] is not None else float("nan"),
        "WAR": r["war"] * 100 if r["war"] is not None else float("nan"),
    }
    for r in display
])

styler = (
    df.style
    .hide(axis="index")
    .format({"Obtained": "{:.0f}", "Win %": "{:.1f}%", "WAR": "{:+.1f}"}, na_rep="—")
    .map(_war_bg, subset=["WAR"])
)
st.markdown(f'<div class="relic-table">{styler.to_html()}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Methodology
# ---------------------------------------------------------------------------

with st.expander("How these numbers are computed"):
    st.markdown(
        f"""
**Relics are outcome-only.** Unlike cards, relics are auto-acquired — there's no
pick-vs-skip choice — so there's no Elo or pick rate, just *did getting it help*.

**WAR — Wins Above Replacement.** For each run that obtained a relic (at the floor
it dropped), I compare the run's result to my own win rate among runs of that
character that *reached that same floor*. Pinning the baseline to the floor strips
out survivorship (a late-dropping relic shouldn't get credit for the run already
surviving). Shown in win-rate points, shrunk toward 0 by
{meta['war_shrinkage_k']:.0f} phantom obtains so tiny samples don't show fake
extremes. **+2.0** means +2 percentage points of win rate when I get it.

**Win %** is my win rate in runs that obtained the relic (shrunk toward the
average). **Obtained** is how many runs got it (its N).

Starting relics sit near **0** by design — every run of a character has them, so
there's nothing to compare against. Sample sizes are small ({meta['n_runs']} runs),
so N is shown and relics below the *Minimum times obtained* bar are hidden.
""")

st.markdown(
    '<div class="app-footer">Personal Slay the Spire 2 run analytics · '
    f'{meta["n_runs"]} runs after filters</div>',
    unsafe_allow_html=True,
)
