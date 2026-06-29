"""Relics page — a per-relic detail view (not a table).

Relics are auto-taken, so there's no Skip, Elo, or pick rate — just outcome.
Pick a relic and see its art, the headline numbers (Obtained, Win % when
obtained, WAR, and its rank), and where it sits in the WAR ranking of every
relic you've gotten. WAR reuses the card engine's floor-conditional,
survivorship-corrected baseline (sts2_stats/relics.py).
"""
from __future__ import annotations

import html
import math

import altair as alt
import pandas as pd
import requests
import streamlit as st

import dashboard_common as dc
from sts2_stats import relics


@st.cache_data(show_spinner=False, ttl=3600)
def _relic_image_url(relic_id: str) -> str | None:
    """untapped.gg relic-art URL, or None if it doesn't resolve. Slug = relic_id
    minus the RELIC. prefix, lowercased, underscores kept (RELIC.WAR_PAINT ->
    war_paint). Cached HEAD check so a missing one never shows a broken icon."""
    slug = (relic_id[6:] if relic_id.startswith("RELIC.") else relic_id).lower()
    url = f"https://sts2json.untapped.gg/art/relics/{slug}.png"
    try:
        r = requests.head(url, timeout=4, allow_redirects=True)
        return url if r.status_code == 200 else None
    except requests.RequestException:
        return None


palette = st.session_state["palette"]
filters = st.session_state["filters"]
mode = st.session_state["mode"]

dc.page_header("Relics")


# ---------------------------------------------------------------------------
# Controls + data
# ---------------------------------------------------------------------------

char_labels = ["Overall"] + [c.replace("CHARACTER.", "") for c in dc.CHARACTERS]
char_choice = st.radio("Character", char_labels, index=0, horizontal=True, key="_relic_char")
relic_character = None if char_choice == "Overall" else f"CHARACTER.{char_choice}"
relic_filters = {**filters, "character": relic_character}

min_obt = st.slider(
    "Minimum times obtained", 1, 30, 5, key="_relic_minobt",
    help="Only rank relics with at least this many obtains (small samples are noise).",
)

conn = dc.connect_db()
try:
    res = relics.compute_relic_rankings(conn, relic_filters)
finally:
    conn.close()

rows = res["rows"]
meta = res["meta"]

qualifying = sorted(
    [r for r in rows if r["obtained"] >= min_obt],
    key=lambda r: (r["war"] if r["war"] is not None else -math.inf),
    reverse=True,
)

if meta["n_runs"] == 0 or not qualifying:
    st.markdown(
        '<div class="empty-state" style="margin-top:1rem;">'
        "No relics clear the current filters yet (try lowering the minimum).</div>",
        unsafe_allow_html=True,
    )
    st.stop()


# ---------------------------------------------------------------------------
# Relic picker
# ---------------------------------------------------------------------------

keys = [r["relic_id"] for r in qualifying]
by_id = {r["relic_id"]: r for r in qualifying}
rank_of = {r["relic_id"]: i + 1 for i, r in enumerate(qualifying)}

if st.session_state.get("_relic_pick") not in keys:
    st.session_state["_relic_pick"] = keys[0]
chosen = st.selectbox(
    "Relic", keys, format_func=lambda k: by_id[k]["relic"], key="_relic_pick",
)
row = by_id[chosen]
rank = rank_of[chosen]


# ---------------------------------------------------------------------------
# Hero: art + headline tiles
# ---------------------------------------------------------------------------

def _pct(v) -> str:
    return f"{v * 100:.1f}%" if v is not None else "—"


def _war(v) -> str:
    return f"{v * 100:+.1f}" if v is not None else "—"  # win-rate points


_art_col, _info_col = st.columns([1, 3], gap="large")
with _art_col:
    _img = _relic_image_url(row["relic_id"])
    if _img:
        st.image(_img, width=200)
    else:
        st.markdown(
            f'<div style="border:2px dashed {palette["border"]};border-radius:14px;'
            f"min-height:200px;display:flex;align-items:center;justify-content:center;"
            f'color:{palette["text_secondary"]};font-size:13px;">no relic art</div>',
            unsafe_allow_html=True,
        )
with _info_col:
    st.markdown(
        f'<div class="chart-title" style="font-size:28px;border-left:5px solid {palette["accent"]};'
        f'padding-left:0.7rem;margin-bottom:0.15rem;">{html.escape(row["relic"])}</div>'
        f'<div class="chart-sub" style="margin-bottom:0.8rem;">obtained {row["obtained"]}× · '
        f'won {row["wins"]} of those runs</div>',
        unsafe_allow_html=True,
    )
    dc.sample_warning(row["obtained"], floor=10, noun="obtains", palette=palette)
    m = st.columns(4, gap="small")
    with m[0]:
        dc.metric_card("Obtained", str(row["obtained"]), secondary=True)
    with m[1]:
        dc.metric_card("Win % when obtained", _pct(row["winrate_shrunk"]), secondary=True)
    with m[2]:
        dc.metric_card("WAR", _war(row["war"]), secondary=True, accent=True)
    with m[3]:
        dc.metric_card("Rank", f"#{rank} of {len(qualifying)}", secondary=True)


# ---------------------------------------------------------------------------
# Where it ranks — WAR across every qualifying relic
# ---------------------------------------------------------------------------

dc.eyebrow("WAR ranking — where this relic sits")

sdf = pd.DataFrame([
    {
        "relic": r["relic"],
        "WAR": r["war"] * 100,
        "rank": i + 1,
        "is_this": r["relic_id"] == chosen,
    }
    for i, r in enumerate(qualifying)
])
zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
    color=palette["text_secondary"], opacity=0.35).encode(x="x:Q")
others = (
    alt.Chart(sdf[~sdf["is_this"]])
    .mark_circle(size=55, opacity=0.4, color=palette["text_secondary"])
    .encode(
        x=alt.X("WAR:Q", axis=alt.Axis(title="WAR (win-rate points)")),
        y=alt.Y("rank:Q", axis=alt.Axis(title="Rank (1 = best)"),
                scale=alt.Scale(reverse=True)),
        tooltip=["relic", alt.Tooltip("WAR:Q", format="+.1f"), alt.Tooltip("rank:Q")],
    )
)
this = (
    alt.Chart(sdf[sdf["is_this"]])
    .mark_point(size=240, filled=True, color=palette["accent"],
                stroke=palette["text_primary"], strokeWidth=1.5)
    .encode(
        x="WAR:Q", y="rank:Q",
        tooltip=["relic", alt.Tooltip("WAR:Q", format="+.1f"), alt.Tooltip("rank:Q")],
    )
)
st.altair_chart((zero + others + this).properties(height=340), width="stretch", theme=None)
st.markdown(
    f'<div class="chart-sub">Each dot is a relic ({len(qualifying)} obtained '
    f'{min_obt}+ times); this one is highlighted. Further right = it wins more '
    "above my floor baseline when I get it.</div>",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Methodology
# ---------------------------------------------------------------------------

with st.expander("How these numbers are computed"):
    st.markdown(
        f"""
**Relics are outcome-only.** They're auto-acquired — no pick-vs-skip choice — so
there's no Elo, no pick rate, and no Skip line. Just *did getting it help*.

**WAR — Wins Above Replacement.** For each run that obtained the relic (at the
floor it dropped), I compare the run's result to my win rate among runs of that
character that *reached that same floor*. Pinning the baseline to the floor strips
out survivorship. Shown in win-rate points, shrunk toward 0 by
{meta['war_shrinkage_k']:.0f} phantom obtains so tiny samples don't show fake
extremes. **+2.0** = +2 percentage points of win rate when I get it.

**Win %** is my win rate in runs that obtained the relic (shrunk toward the
average). **Obtained** is how many runs got it (its N). **Rank** is its place in
the WAR order of every relic obtained {min_obt}+ times.

Starting relics sit near **0** by design — every run of a character has them, so
there's nothing to compare against.
""")

st.markdown(
    '<div class="app-footer">Personal Slay the Spire 2 run analytics · '
    f'{meta["n_runs"]} runs after filters</div>',
    unsafe_allow_html=True,
)
