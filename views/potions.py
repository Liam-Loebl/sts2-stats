"""Potions page — a per-potion detail view.

Potions are a real choice (you skip them) and get used, so unlike relics they
have a pickup rate and a use rate. Pick a potion to see its art, pickup% / win% /
WAR / use rate / offered / used, and where it ranks among the potions you've been
offered. WAR reuses the card engine's floor baseline (sts2_stats/potions.py).
No Elo (same call as relics).
"""
from __future__ import annotations

import html
import math

import altair as alt
import pandas as pd
import requests
import streamlit as st

import dashboard_common as dc
from sts2_stats import potions


@st.cache_data(show_spinner=False, ttl=3600)
def _potion_image_url(potion_id: str) -> str | None:
    """untapped.gg potion-art URL, or None. Slug = potion_id minus the POTION.
    prefix, lowercased, underscores kept (POTION.SWIFT_POTION -> swift_potion).
    Cached HEAD check so a missing one never shows a broken icon."""
    slug = (potion_id[7:] if potion_id.startswith("POTION.") else potion_id).lower()
    url = f"https://sts2json.untapped.gg/art/potions/{slug}.png"
    try:
        r = requests.head(url, timeout=4, allow_redirects=True)
        return url if r.status_code == 200 else None
    except requests.RequestException:
        return None


palette = st.session_state["palette"]
filters = st.session_state["filters"]
mode = st.session_state["mode"]

dc.page_header("Potions")


# ---------------------------------------------------------------------------
# Controls + data
# ---------------------------------------------------------------------------

char_labels = ["Overall"] + [c.replace("CHARACTER.", "") for c in dc.CHARACTERS]
char_choice = st.radio("Character", char_labels, index=0, horizontal=True, key="_potion_char")
potion_character = None if char_choice == "Overall" else f"CHARACTER.{char_choice}"
potion_filters = {**filters, "character": potion_character}

min_off = st.slider(
    "Minimum times offered", 1, 30, 5, key="_potion_minoff",
    help="Only rank potions offered at least this many times (small samples are noise).",
)

conn = dc.connect_db()
try:
    res = potions.compute_potion_rankings(conn, potion_filters)
finally:
    conn.close()

rows = res["rows"]
meta = res["meta"]

qualifying = sorted(
    [r for r in rows if r["offered"] >= min_off],
    key=lambda r: (r["war"] if r["war"] is not None else -math.inf),
    reverse=True,
)

if meta["n_runs"] == 0 or not qualifying:
    st.markdown(
        '<div class="empty-state" style="margin-top:1rem;">'
        "No potions clear the current filters yet (try lowering the minimum).</div>",
        unsafe_allow_html=True,
    )
    st.stop()


# ---------------------------------------------------------------------------
# Potion picker
# ---------------------------------------------------------------------------

keys = [r["potion_id"] for r in qualifying]
by_id = {r["potion_id"]: r for r in qualifying}
rank_of = {r["potion_id"]: i + 1 for i, r in enumerate(qualifying)}

if st.session_state.get("_potion_pick") not in keys:
    st.session_state["_potion_pick"] = keys[0]
chosen = st.selectbox(
    "Potion", keys, format_func=lambda k: by_id[k]["potion"], key="_potion_pick",
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
    _img = _potion_image_url(row["potion_id"])
    if _img:
        st.image(_img, width=180)
    else:
        st.markdown(
            f'<div style="border:2px dashed {palette["border"]};border-radius:14px;'
            f"min-height:180px;display:flex;align-items:center;justify-content:center;"
            f'color:{palette["text_secondary"]};font-size:13px;">no potion art</div>',
            unsafe_allow_html=True,
        )
with _info_col:
    st.markdown(
        f'<div class="chart-title" style="font-size:28px;border-left:5px solid {palette["accent"]};'
        f'padding-left:0.7rem;margin-bottom:0.15rem;">{html.escape(row["potion"])}</div>'
        f'<div class="chart-sub" style="margin-bottom:0.8rem;">offered {row["offered"]}× · '
        f'picked {row["picked"]}× · #{rank} of {len(qualifying)} by WAR</div>',
        unsafe_allow_html=True,
    )
    dc.sample_warning(row["picked"], floor=10, noun="picks", palette=palette)
    r1 = st.columns(3, gap="small")
    with r1[0]:
        dc.metric_card("Pickup %", _pct(row["pickup_rate"]), secondary=True)
    with r1[1]:
        dc.metric_card("Win % when picked", _pct(row["winrate_shrunk"]), secondary=True)
    with r1[2]:
        dc.metric_card("WAR", _war(row["war"]), secondary=True, accent=True)
    r2 = st.columns(3, gap="small")
    with r2[0]:
        dc.metric_card("Use rate", _pct(row["use_rate"]), secondary=True)
    with r2[1]:
        dc.metric_card("Offered", str(row["offered"]), secondary=True)
    with r2[2]:
        dc.metric_card("Used", str(row["used"]), secondary=True)


# ---------------------------------------------------------------------------
# Where it ranks — WAR across every qualifying potion
# ---------------------------------------------------------------------------

dc.eyebrow("WAR ranking — where this potion sits")

sdf = pd.DataFrame([
    {
        "potion": r["potion"],
        "WAR": (r["war"] * 100) if r["war"] is not None else None,
        "rank": i + 1,
        "is_this": r["potion_id"] == chosen,
    }
    for i, r in enumerate(qualifying)
]).dropna(subset=["WAR"])

if len(sdf) >= 2:
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
        color=palette["text_secondary"], opacity=0.35).encode(x="x:Q")
    others = (
        alt.Chart(sdf[~sdf["is_this"]])
        .mark_circle(size=60, opacity=0.4, color=palette["text_secondary"])
        .encode(
            x=alt.X("WAR:Q", axis=alt.Axis(title="WAR (win-rate points)")),
            y=alt.Y("rank:Q", axis=alt.Axis(title="Rank (1 = best)"),
                    scale=alt.Scale(reverse=True)),
            tooltip=["potion", alt.Tooltip("WAR:Q", format="+.1f"), alt.Tooltip("rank:Q")],
        )
    )
    this = (
        alt.Chart(sdf[sdf["is_this"]])
        .mark_point(size=260, filled=True, color=palette["accent"],
                    stroke=palette["text_primary"], strokeWidth=1.5)
        .encode(
            x="WAR:Q", y="rank:Q",
            tooltip=["potion", alt.Tooltip("WAR:Q", format="+.1f"), alt.Tooltip("rank:Q")],
        )
    )
    st.altair_chart((zero + others + this).properties(height=320), width="stretch", theme=None)
    st.markdown(
        f'<div class="chart-sub">Each dot is a potion ({len(sdf)} offered {min_off}+ '
        "times); this one is highlighted. Further right = it wins more above my floor "
        "baseline when I take it.</div>",
        unsafe_allow_html=True,
    )
else:
    st.markdown(
        '<div class="empty-state">Not enough potions have a WAR yet to draw the ranking.</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Methodology
# ---------------------------------------------------------------------------

with st.expander("How these numbers are computed"):
    st.markdown(
        f"""
**Pickup %** — of the times this potion was offered, how often I took it (the
pick-vs-skip signal). **Win %** — win rate of runs that picked it (shrunk toward
the average). **WAR** — for each run that picked it (at the floor it was offered),
the result vs my win rate among runs of that character that *reached that floor*;
floor-pinned to strip survivorship, shrunk by {meta['war_shrinkage_k']:.0f} phantom
picks, shown in win-rate points. **Use rate** — of the potions I acquired (picked
or bought), how often I used one; it can read above 100% for potions also granted
by relics/events (not counted as acquired). **Rank** is the WAR order among
potions offered {min_off}+ times.

No Elo and no Skip line — kept out, same as relics. Sample sizes are small
({meta['n_runs']} runs), so N is shown and low-sample potions are flagged.
""")

st.markdown(
    '<div class="app-footer">Personal Slay the Spire 2 run analytics · '
    f'{meta["n_runs"]} runs after filters</div>',
    unsafe_allow_html=True,
)
