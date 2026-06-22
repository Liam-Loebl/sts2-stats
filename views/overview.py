"""Overview page — topline win rate, character tiles, win-rate trend, damage per act.

Content moved verbatim from the Phase 2 single-page app; only the shared
chrome (theme, sidebar filters, render helpers) was lifted into
`dashboard_common`. Reads the active filters/palette from session_state
(populated by app.py before nav.run()).
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

import dashboard_common as dc
from sts2_stats import queries
from theme import CHARACTER_RANGE

palette = st.session_state["palette"]
filters = st.session_state["filters"]

dc.page_header("Overview")

# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

conn = dc.connect_db()
try:
    topline = queries.topline_stats(conn, filters)
    per_char = queries.per_character_stats(conn, filters)
    wr_over_time = queries.win_rate_over_time(conn, filters, window=20)
    dmg_per_act = queries.damage_per_act(conn, filters)
finally:
    conn.close()

total_runs = topline.get("total_runs", 0)
win_rate = topline.get("win_rate", 0.0) or 0.0
best_streak = topline.get("best_streak", 0)
wins = topline.get("wins", 0)
losses = topline.get("losses", 0)


# ---------------------------------------------------------------------------
# Summary — hero win rate + 2 supporting tiles
# ---------------------------------------------------------------------------

dc.eyebrow("Summary")

hero_col, side_col = st.columns([3, 2], gap="small")
with hero_col:
    dc.metric_card(
        "Win rate",
        f"{win_rate:.1%}" if total_runs else "—",
        delta=(f"{wins}W / {losses}L" if total_runs else None),
        hero=True,
        accent=True,
    )
with side_col:
    s1, s2 = st.columns(2, gap="small")
    with s1:
        dc.metric_card("Total runs", f"{total_runs}", secondary=True)
    with s2:
        dc.metric_card("Best streak", f"{best_streak}", secondary=True)


# ---------------------------------------------------------------------------
# Empty-state guard
# ---------------------------------------------------------------------------

if total_runs == 0:
    st.markdown(
        '<div class="empty-state" style="margin-top:1.5rem;">'
        "No runs match these filters."
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="app-footer">'
        f"Personal Slay the Spire 2 run analytics · {total_runs} runs"
        "</div>",
        unsafe_allow_html=True,
    )
    st.stop()


# ---------------------------------------------------------------------------
# Characters — 5-tile row
# ---------------------------------------------------------------------------

dc.eyebrow("Characters")

per_char_by_name = {row["character"]: row for row in per_char}

char_cols = st.columns(len(dc.CHARACTERS), gap="small")
for col, char, color in zip(char_cols, dc.CHARACTERS, CHARACTER_RANGE):
    short = char.replace("CHARACTER.", "")
    row = per_char_by_name.get(char)
    is_selected = filters.get("character") == char
    with col:
        dc.character_tile(short, row, selected=is_selected, color=color)


# ---------------------------------------------------------------------------
# Trends — rolling win rate (left) + damage per act (right)
# ---------------------------------------------------------------------------

dc.eyebrow("Trends")

left_col, right_col = st.columns([3, 2], gap="small")

with left_col:
    st.markdown(
        '<div class="chart-title">Rolling win rate</div>'
        '<div class="chart-sub">20-run window, chronological</div>',
        unsafe_allow_html=True,
    )
    if not wr_over_time:
        st.markdown(
            '<div class="empty-state">Need at least 20 runs after filters '
            "to draw a rolling window.</div>",
            unsafe_allow_html=True,
        )
    else:
        wr_df = pd.DataFrame(wr_over_time)
        line = (
            alt.Chart(wr_df)
            .mark_line(strokeWidth=2, color=palette["accent"], interpolate="monotone")
            .encode(
                x=alt.X("run_index:Q", axis=alt.Axis(title="Run #", labelFlush=False)),
                y=alt.Y(
                    "win_rate:Q",
                    axis=alt.Axis(title="Win rate", format=".0%"),
                    scale=alt.Scale(domain=[0, 1], nice=False),
                ),
                tooltip=[
                    alt.Tooltip("run_index:Q", title="Run #"),
                    alt.Tooltip("win_rate:Q", title="Win rate", format=".1%"),
                ],
            )
        )
        baseline = (
            alt.Chart(pd.DataFrame({"y": [0.5]}))
            .mark_rule(strokeDash=[4, 4], color=palette["text_secondary"], opacity=0.45)
            .encode(y="y:Q")
        )
        st.altair_chart((baseline + line).properties(height=280), width="stretch", theme=None)

with right_col:
    st.markdown(
        '<div class="chart-title">Damage taken per act</div>'
        '<div class="chart-sub">Average, by character</div>',
        unsafe_allow_html=True,
    )
    if not dmg_per_act:
        st.markdown(
            '<div class="empty-state">No damage data for the current '
            "filters.</div>",
            unsafe_allow_html=True,
        )
    else:
        dmg_df = pd.DataFrame(dmg_per_act)
        dmg_df["character_short"] = dmg_df["character"].str.replace(
            "CHARACTER.", "", regex=False
        )
        dmg_df["act_label"] = "Act " + dmg_df["act"].astype(int).astype(str)

        char_order = [c.replace("CHARACTER.", "") for c in dc.CHARACTERS]
        present_order = [c for c in char_order if c in set(dmg_df["character_short"])]

        bars = (
            alt.Chart(dmg_df)
            .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
            .encode(
                x=alt.X(
                    "act_label:N",
                    axis=alt.Axis(title=None, labelAngle=0),
                    sort=sorted(dmg_df["act_label"].unique()),
                ),
                xOffset=alt.XOffset("character_short:N", sort=present_order),
                y=alt.Y("avg_damage:Q", axis=alt.Axis(title="Avg damage taken", format=",.0f")),
                color=alt.Color(
                    "character_short:N",
                    sort=present_order,
                    scale=alt.Scale(domain=char_order, range=CHARACTER_RANGE),
                    legend=None,  # the character tiles above are the shared color key
                ),
                tooltip=[
                    alt.Tooltip("character_short:N", title="Character"),
                    alt.Tooltip("act_label:N", title="Act"),
                    alt.Tooltip("avg_damage:Q", title="Avg damage", format=",.1f"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(bars, width="stretch", theme=None)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown(
    '<div class="app-footer">'
    f"Personal Slay the Spire 2 run analytics · {total_runs} runs"
    "</div>",
    unsafe_allow_html=True,
)
