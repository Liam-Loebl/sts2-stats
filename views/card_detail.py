"""Card detail page — one card's full story: headline metrics, per-act splits,
Elo over time, and where it sits on the Elo-vs-WAR map.

Reads the active sidebar filters (mode / game_mode / ascension / patch) from
session_state, computes the full board once, and drills into a single
(card, character). The card is chosen with the selectbox here, or arrives
pre-selected from the Card Rankings board's "Detail →" button (a one-shot
hand-off via st.session_state["detail_card"]).
"""
from __future__ import annotations

import html

import altair as alt
import pandas as pd
import streamlit as st

import dashboard_common as dc
from sts2_stats import rankings
from theme import CHARACTER_RANGE

palette = st.session_state["palette"]
filters = st.session_state["filters"]
mode = st.session_state["mode"]

# Character -> identity color (positional with dc.CHARACTERS / CHARACTER_RANGE).
_CHAR_COLOR = {c: CHARACTER_RANGE[i] for i, c in enumerate(dc.CHARACTERS)}

dc.page_header("Card Detail")

# ---------------------------------------------------------------------------
# Data (whole board for the current filters; character intrinsic to each row)
# ---------------------------------------------------------------------------

conn = dc.connect_db()
try:
    res = rankings.compute_rankings(conn, {**filters, "character": None})
finally:
    conn.close()

rows = res["rows"]
meta = res["meta"]

if not rows:
    st.markdown(
        '<div class="empty-state" style="margin-top:1rem;">'
        "No in-scope card data for these filters yet.</div>",
        unsafe_allow_html=True,
    )
    st.stop()


# ---------------------------------------------------------------------------
# Card picker (each option carries the (card_id, character) identity)
# ---------------------------------------------------------------------------

options = sorted(rows, key=lambda r: (r["card"], r["character_name"]))
keys = [(r["card_id"], r["character"]) for r in options]
labels = {(r["card_id"], r["character"]): f"{r['card']} · {r['character_name']}" for r in options}

# One-shot hand-off from the board's "Detail →" button.
pre = st.session_state.pop("detail_card", None)
if pre in keys:
    st.session_state["_detail_card_select"] = pre
if st.session_state.get("_detail_card_select") not in keys:
    st.session_state["_detail_card_select"] = keys[0]

chosen = st.selectbox(
    "Card", keys, format_func=lambda k: labels[k], key="_detail_card_select",
)
row = next((r for r in rows if (r["card_id"], r["character"]) == chosen), None)
if row is None:
    st.markdown(
        '<div class="empty-state">That card has no data under the current filters.</div>',
        unsafe_allow_html=True,
    )
    st.stop()

char = row["character"]
color = _CHAR_COLOR.get(char, palette["accent"])


# ---------------------------------------------------------------------------
# Header + headline metrics
# ---------------------------------------------------------------------------

def _pct(v: float | None) -> str:
    return f"{v * 100:.1f}%" if v is not None else "—"


def _war(v: float | None) -> str:
    return f"{v * 100:+.1f}" if v is not None else "—"  # win-rate points


def _elo(v: float | None) -> str:
    return f"{v:.0f}" if v is not None else "—"


def _delta(v: float | None) -> str:
    return f"{v:+.0f}" if v is not None else "—"  # Elo-point delta


st.markdown(
    f'<div class="chart-title" style="font-size:21px;border-left:4px solid {color};'
    f'padding-left:0.55rem;margin-bottom:0.1rem;">{html.escape(row["card"])}</div>'
    f'<div class="chart-sub" style="margin-bottom:0.6rem;">{html.escape(row["character_name"])}'
    f' · offered {row["offers"]}× · picked {row["picks"]}×</div>',
    unsafe_allow_html=True,
)

dc.sample_warning(row["offers"], floor=10, noun="offers", palette=palette)

m = st.columns(6, gap="small")
with m[0]:
    dc.metric_card("Pick %", _pct(row["pick_rate"]), secondary=True)
with m[1]:
    dc.metric_card("Win % when picked", _pct(row["winrate_shrunk"]), secondary=True)
with m[2]:
    dc.metric_card("WAR", _war(row["war"]), secondary=True, accent=True)
with m[3]:
    dc.metric_card("Elo", _elo(row["elo"]), secondary=True)
with m[4]:
    dc.metric_card("vs Skip", _delta(row["elo_vs_skip"]), secondary=True)
with m[5]:
    dc.metric_card("Elo matches", str(row["elo_n"]), secondary=True)


# ---------------------------------------------------------------------------
# By act — pick rate + WAR per act
# ---------------------------------------------------------------------------

dc.eyebrow("By act")

by_act = row.get("by_act") or {}
if not by_act:
    st.markdown(
        '<div class="empty-state">No per-act data for this card under these filters.</div>',
        unsafe_allow_html=True,
    )
else:
    act_df = pd.DataFrame([
        {
            "act": f"Act {a}",
            "Pick %": d["pick_rate"] * 100,
            "WAR": (d["war"] * 100) if d["war"] is not None else None,
            "offers": d["offers"],
            "picks": d["picks"],
        }
        for a, d in sorted(by_act.items())
    ])
    left, right = st.columns(2, gap="small")
    with left:
        st.markdown('<div class="chart-title">Pick rate by act</div>', unsafe_allow_html=True)
        bars = (
            alt.Chart(act_df)
            .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2, color=color)
            .encode(
                x=alt.X("act:N", axis=alt.Axis(title=None, labelAngle=0)),
                y=alt.Y("Pick %:Q", axis=alt.Axis(title="Pick %", format=".0f"),
                        scale=alt.Scale(domain=[0, 100])),
                tooltip=[alt.Tooltip("act:N", title="Act"),
                         alt.Tooltip("Pick %:Q", format=".1f"),
                         alt.Tooltip("offers:Q", title="Offers"),
                         alt.Tooltip("picks:Q", title="Picks")],
            )
            .properties(height=240)
        )
        st.altair_chart(bars, width="stretch", theme=None)
    with right:
        st.markdown('<div class="chart-title">WAR by act</div>'
                    '<div class="chart-sub">win-rate points per pick</div>',
                    unsafe_allow_html=True)
        wardf = act_df.dropna(subset=["WAR"])
        if wardf.empty:
            st.markdown('<div class="empty-state">No picks with a baseline yet.</div>',
                        unsafe_allow_html=True)
        else:
            base = alt.Chart(wardf).encode(
                x=alt.X("act:N", axis=alt.Axis(title=None, labelAngle=0)),
            )
            warbars = base.mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
                y=alt.Y("WAR:Q", axis=alt.Axis(title="WAR")),
                color=alt.condition(alt.datum.WAR >= 0,
                                    alt.value(palette["positive"]), alt.value(palette["negative"])),
                tooltip=[alt.Tooltip("act:N", title="Act"),
                         alt.Tooltip("WAR:Q", format="+.1f"),
                         alt.Tooltip("picks:Q", title="Picks")],
            )
            zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
                color=palette["text_secondary"], opacity=0.5).encode(y="y:Q")
            st.altair_chart((zero + warbars).properties(height=240), width="stretch", theme=None)


# ---------------------------------------------------------------------------
# Elo over time
# ---------------------------------------------------------------------------

dc.eyebrow("Elo over time")

seq = meta.get("elo_history", {}).get(char, {}).get(row["card_id"], [])
if not seq:
    st.markdown(
        '<div class="empty-state">This card never competed in an Elo match under '
        "these filters (its only rewards were forced or multi-pick), so there's no "
        "trajectory to plot.</div>",
        unsafe_allow_html=True,
    )
else:
    init = meta.get("elo_initial", 1500.0)
    elo_df = pd.DataFrame(
        {"match": list(range(len(seq) + 1)), "Elo": [init] + list(seq)}
    )
    line = (
        alt.Chart(elo_df)
        .mark_line(point=True, strokeWidth=2, color=color, interpolate="monotone")
        .encode(
            x=alt.X("match:Q", axis=alt.Axis(title="Match # (chronological)", tickMinStep=1)),
            y=alt.Y("Elo:Q", axis=alt.Axis(title="Elo"), scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("match:Q", title="Match #"),
                     alt.Tooltip("Elo:Q", format=".0f")],
        )
    )
    start = (
        alt.Chart(pd.DataFrame({"y": [init]}))
        .mark_rule(strokeDash=[4, 4], color=palette["text_secondary"], opacity=0.5)
        .encode(y="y:Q")
    )
    st.altair_chart((start + line).properties(height=280), width="stretch", theme=None)
    st.markdown(
        f'<div class="chart-sub">Starts at the {init:.0f} baseline; each point is the rating '
        "after one card-reward match (a pick beating the field, or losing to a pick).</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Elo vs WAR — where this card sits among all cards
# ---------------------------------------------------------------------------

dc.eyebrow("Elo vs WAR — preference vs outcome")

MIN_OFF = 10
scatter_rows = [
    r for r in rows
    if r["offers"] >= MIN_OFF and r["war"] is not None and r["elo_vs_skip"] is not None
]
if len(scatter_rows) < 3:
    st.markdown(
        '<div class="empty-state">Not enough cards clear the sample bar to draw the map yet.</div>',
        unsafe_allow_html=True,
    )
else:
    sdf = pd.DataFrame([
        {
            "card": r["card"],
            "character": r["character_name"],
            "WAR": r["war"] * 100,
            "vs Skip": r["elo_vs_skip"],
            "is_this": (r["card_id"], r["character"]) == chosen,
        }
        for r in scatter_rows
    ])
    # Ensure the selected card is present even if it's below the sample bar.
    if not sdf["is_this"].any() and row["war"] is not None and row["elo_vs_skip"] is not None:
        sdf = pd.concat([sdf, pd.DataFrame([{
            "card": row["card"], "character": row["character_name"],
            "WAR": row["war"] * 100, "vs Skip": row["elo_vs_skip"], "is_this": True,
        }])], ignore_index=True)

    zero_x = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(
        color=palette["text_secondary"], opacity=0.35).encode(x="x:Q")
    zero_y = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
        color=palette["text_secondary"], opacity=0.35).encode(y="y:Q")
    others = (
        alt.Chart(sdf[~sdf["is_this"]])
        .mark_circle(size=55, opacity=0.35, color=palette["text_secondary"])
        .encode(
            x=alt.X("WAR:Q", axis=alt.Axis(title="WAR (win-rate points)")),
            y=alt.Y("vs Skip:Q", axis=alt.Axis(title="Elo vs Skip")),
            tooltip=["card", "character", alt.Tooltip("WAR:Q", format="+.1f"),
                     alt.Tooltip("vs Skip:Q", format="+.0f")],
        )
    )
    this = (
        alt.Chart(sdf[sdf["is_this"]])
        .mark_point(size=220, filled=True, color=color, stroke=palette["text_primary"], strokeWidth=1.5)
        .encode(
            x="WAR:Q", y="vs Skip:Q",
            tooltip=["card", "character", alt.Tooltip("WAR:Q", format="+.1f"),
                     alt.Tooltip("vs Skip:Q", format="+.0f")],
        )
    )
    st.altair_chart((zero_x + zero_y + others + this).properties(height=320),
                    width="stretch", theme=None)
    st.markdown(
        '<div class="chart-sub">Top-left = I take it over Skip but it doesn\'t win (overrated); '
        "bottom-right = it wins when I take it but I usually pass (underrated). This card is "
        "highlighted.</div>",
        unsafe_allow_html=True,
    )

st.markdown(
    '<div class="app-footer">Personal Slay the Spire 2 run analytics · '
    f'{meta["n_runs"]} runs after filters</div>',
    unsafe_allow_html=True,
)
