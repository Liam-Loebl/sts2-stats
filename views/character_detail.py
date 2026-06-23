"""Character detail page — one character's win rate, rolling trend, damage curve,
and best/worst cards.

Reads the active sidebar filters from session_state. The character is chosen with
the selectbox here, or arrives from the Overview's "Detail →" button via a
one-shot st.session_state["detail_character"]. Pure presentation over existing
queries (topline_stats / per_character_stats / win_rate_over_time / damage_per_act)
and the rankings engine — no new engine work.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import dashboard_common as dc
from sts2_stats import queries, rankings
from sts2_stats.names import pretty_character_name
from theme import CHARACTER_RANGE

palette = st.session_state["palette"]
filters = st.session_state["filters"]
mode = st.session_state["mode"]

# Character -> identity color (positional with dc.CHARACTERS / CHARACTER_RANGE).
_CHAR_COLOR = {c: CHARACTER_RANGE[i] for i, c in enumerate(dc.CHARACTERS)}

dc.page_header("Character Detail")


# ---------------------------------------------------------------------------
# Character picker (one-shot hand-off from the Overview "Detail →" button)
# ---------------------------------------------------------------------------

keys = list(dc.CHARACTERS)

# One-shot hand-off from the Overview "Detail →" button.
pre = st.session_state.pop("detail_character", None)
if pre in keys:
    st.session_state["_detail_char"] = pre
if st.session_state.get("_detail_char") not in keys:
    st.session_state["_detail_char"] = keys[0]

# Character picker: five buttons (one per character) instead of a dropdown. Each
# carries its identity color as a top stripe; the active character is filled.
_btn_stripes = "\n".join(
    f'.st-key-charbtn_{c.replace("CHARACTER.", "")} button {{ border-top: 3px solid {_CHAR_COLOR[c]}; }}'
    for c in keys
)
st.markdown(
    "<style>"
    '[class*="st-key-charbtn_"] button { padding: 0.8rem 0.4rem; font-weight: 600; border-radius: 10px; }'
    + _btn_stripes
    + "</style>",
    unsafe_allow_html=True,
)
dc.eyebrow("Character")
_btn_cols = st.columns(len(keys), gap="small")
for _col, _c in zip(_btn_cols, keys):
    with _col:
        if st.button(
            pretty_character_name(_c),
            key=f"charbtn_{_c.replace('CHARACTER.', '')}",
            width="stretch",
            type="primary" if _c == st.session_state["_detail_char"] else "secondary",
        ):
            st.session_state["_detail_char"] = _c
            st.rerun()

char = st.session_state["_detail_char"]
color = _CHAR_COLOR.get(char, palette["accent"])
char_filters = {**filters, "character": char}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

conn = dc.connect_db()
try:
    top = queries.topline_stats(conn, char_filters)
    per_rows = queries.per_character_stats(conn, char_filters)
    wr_series = queries.win_rate_over_time(conn, char_filters, window=10)
    dmg = queries.damage_per_act(conn, char_filters)
    board = rankings.compute_rankings(conn, char_filters)
finally:
    conn.close()

per = next((r for r in per_rows if r["character"] == char), None)
total = top["total_runs"]

st.markdown(
    f'<div class="chart-title" style="font-size:21px;border-left:4px solid {color};'
    f'padding-left:0.55rem;margin-bottom:0.6rem;">{pretty_character_name(char)}</div>',
    unsafe_allow_html=True,
)

if total == 0:
    st.markdown(
        '<div class="empty-state">No runs for this character under the current filters.</div>',
        unsafe_allow_html=True,
    )
    st.stop()


# ---------------------------------------------------------------------------
# Headline metrics
# ---------------------------------------------------------------------------

dc.sample_warning(total, floor=10, noun="runs", palette=palette)

avg_floors = per["avg_floors_reached"] if per else 0.0
top_asc = top["most_played_ascension"]

m = st.columns(5, gap="small")
with m[0]:
    dc.metric_card("Win rate", f"{top['win_rate']:.1%}",
                   delta=f"{top['wins']}W / {top['losses']}L", secondary=True, accent=True)
with m[1]:
    dc.metric_card("Runs", str(total), secondary=True)
with m[2]:
    dc.metric_card("Best streak", str(top["best_streak"]), secondary=True)
with m[3]:
    dc.metric_card("Avg floors", f"{avg_floors:.0f}", secondary=True)
with m[4]:
    dc.metric_card("Top ascension", str(top_asc) if top_asc is not None else "—", secondary=True)


# ---------------------------------------------------------------------------
# Trends — rolling win rate + damage per act
# ---------------------------------------------------------------------------

dc.eyebrow("Trends")
left, right = st.columns([3, 2], gap="small")

with left:
    st.markdown(
        '<div class="chart-title">Rolling win rate</div>'
        '<div class="chart-sub">10-run window, chronological</div>',
        unsafe_allow_html=True,
    )
    if not wr_series:
        st.markdown(
            '<div class="empty-state">Need at least 10 runs on this character to draw '
            "a rolling window.</div>",
            unsafe_allow_html=True,
        )
    else:
        wr_df = pd.DataFrame(wr_series)
        line = (
            alt.Chart(wr_df)
            .mark_line(strokeWidth=2, color=color, interpolate="monotone")
            .encode(
                x=alt.X("run_index:Q", axis=alt.Axis(title="Run #", labelFlush=False)),
                y=alt.Y("win_rate:Q", axis=alt.Axis(title="Win rate", format=".0%"),
                        scale=alt.Scale(domain=[0, 1], nice=False)),
                tooltip=[alt.Tooltip("run_index:Q", title="Run #"),
                         alt.Tooltip("win_rate:Q", title="Win rate", format=".1%")],
            )
        )
        baseline = (
            alt.Chart(pd.DataFrame({"y": [0.5]}))
            .mark_rule(strokeDash=[4, 4], color=palette["text_secondary"], opacity=0.45)
            .encode(y="y:Q")
        )
        st.altair_chart((baseline + line).properties(height=280), width="stretch", theme=None)

with right:
    st.markdown(
        '<div class="chart-title">Damage taken per act</div>'
        '<div class="chart-sub">average</div>',
        unsafe_allow_html=True,
    )
    if not dmg:
        st.markdown('<div class="empty-state">No damage data for these filters.</div>',
                    unsafe_allow_html=True)
    else:
        dmg_df = pd.DataFrame(dmg)
        dmg_df["act_label"] = "Act " + dmg_df["act"].astype(int).astype(str)
        bars = (
            alt.Chart(dmg_df)
            .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2, color=color)
            .encode(
                x=alt.X("act_label:N", axis=alt.Axis(title=None, labelAngle=0),
                        sort=sorted(dmg_df["act_label"].unique())),
                y=alt.Y("avg_damage:Q", axis=alt.Axis(title="Avg damage taken", format=",.0f")),
                tooltip=[alt.Tooltip("act_label:N", title="Act"),
                         alt.Tooltip("avg_damage:Q", title="Avg damage", format=",.1f"),
                         alt.Tooltip("n_runs:Q", title="Runs")],
            )
            .properties(height=280)
        )
        st.altair_chart(bars, width="stretch", theme=None)


# ---------------------------------------------------------------------------
# Best / worst cards (by WAR) for this character
# ---------------------------------------------------------------------------

dc.eyebrow("Best & worst cards")

MIN_OFF = 5
ranked = [r for r in board["rows"] if r["offers"] >= MIN_OFF and r["war"] is not None]
if len(ranked) < 2:
    st.markdown(
        f'<div class="empty-state">Not enough {pretty_character_name(char)} cards clear the '
        f"{MIN_OFF}-offer bar yet to rank.</div>",
        unsafe_allow_html=True,
    )
else:
    ranked.sort(key=lambda r: r["war"], reverse=True)
    best = ranked[:8]
    worst = ranked[-8:]

    def _hbar(card_rows, title, sub, order):
        st.markdown(f'<div class="chart-title">{title}</div>'
                    f'<div class="chart-sub">{sub}</div>', unsafe_allow_html=True)
        df = pd.DataFrame([
            {"card": r["card"], "WAR": r["war"] * 100, "offers": r["offers"]}
            for r in card_rows
        ])
        ch = (
            alt.Chart(df)
            .mark_bar(cornerRadiusTopRight=2, cornerRadiusBottomRight=2)
            .encode(
                x=alt.X("WAR:Q", axis=alt.Axis(title="WAR (win-rate points)")),
                y=alt.Y("card:N", sort=alt.SortField("WAR", order=order), axis=alt.Axis(title=None)),
                color=alt.condition(alt.datum.WAR >= 0,
                                    alt.value(palette["positive"]), alt.value(palette["negative"])),
                tooltip=["card", alt.Tooltip("WAR:Q", format="+.1f"),
                         alt.Tooltip("offers:Q", title="Offers")],
            )
            .properties(height=max(120, 30 * len(df)))
        )
        st.altair_chart(ch, width="stretch", theme=None)

    bcol, wcol = st.columns(2, gap="medium")
    with bcol:
        _hbar(best, "Best by WAR", f"top {len(best)} · offered {MIN_OFF}+ times", "descending")
    with wcol:
        _hbar(worst[::-1], "Worst by WAR", f"bottom {len(worst)} · offered {MIN_OFF}+ times", "ascending")

st.markdown(
    '<div class="app-footer">Personal Slay the Spire 2 run analytics · '
    f'{total} {pretty_character_name(char)} runs after filters</div>',
    unsafe_allow_html=True,
)
