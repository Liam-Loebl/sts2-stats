"""Slay the Spire 2 Stats — Phase 2: Overview Dashboard.

Streamlit entrypoint. Run with:

    streamlit run app.py

The data layer is untouched from the Phase 2 build (same filters dict,
same five queries, same import-on-first-load cache). This file owns the
*look*: dark-neutral palette, Inter typography, hand-rolled metric
cards, Altair charts.
"""
from __future__ import annotations

import html
import time
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from sts2_stats import queries
from sts2_stats.db import connect
from sts2_stats.importer import import_all
from sts2_stats.paths import find_history_dirs  # noqa: F401  (kept for parity)
from theme import CSS, PALETTE, CHARACTER_RANGE, register_altair_theme


# ---------------------------------------------------------------------------
# Config (unchanged from Phase 2)
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent / "sts2_stats.sqlite"
IMPORT_STALE_SECONDS = 5 * 60  # re-import if DB older than 5 minutes

CHARACTERS = [
    "CHARACTER.IRONCLAD",
    "CHARACTER.SILENT",
    "CHARACTER.DEFECT",
    "CHARACTER.REGENT",
    "CHARACTER.NECROBINDER",
]

st.set_page_config(
    page_title="Slay the Spire 2 Stats",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inject styling + register Altair theme exactly once per session.
st.markdown(CSS, unsafe_allow_html=True)
register_altair_theme()


# ---------------------------------------------------------------------------
# Import-on-first-load (unchanged behavior)
# ---------------------------------------------------------------------------

def _db_is_stale() -> bool:
    if not DB_PATH.exists():
        return True
    age = time.time() - DB_PATH.stat().st_mtime
    return age > IMPORT_STALE_SECONDS


def _do_import() -> dict:
    """Run import_all() and remember when we did it."""
    summary = import_all(DB_PATH)
    st.session_state["last_import_at"] = datetime.now()
    st.session_state["last_import_summary"] = summary
    return summary


if "last_import_at" not in st.session_state:
    if _db_is_stale():
        with st.spinner("Importing run history..."):
            _do_import()
    else:
        st.session_state["last_import_at"] = datetime.fromtimestamp(DB_PATH.stat().st_mtime)
        st.session_state["last_import_summary"] = None


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------

def _eyebrow(text: str) -> None:
    st.markdown(f'<div class="eyebrow">{html.escape(text)}</div>', unsafe_allow_html=True)


def metric_card(
    label: str,
    value: str,
    delta: str | None = None,
    *,
    hero: bool = False,
    accent: bool = False,
    selected: bool = False,
) -> None:
    """Hand-rolled metric tile. Replaces st.metric.

    label   — small uppercase caption on top
    value   — the big number
    delta   — optional supporting line (e.g. "84W / 196L"); muted, but
              pass a leading '+' / '-' to colour as positive / negative
    hero    — true for the lead win-rate stat (48px instead of 32px)
    accent  — render the number in the accent color (lead stat)
    selected — 1px accent border (selected character)
    """
    classes = ["metric-card"]
    if hero:
        classes.append("is-hero")
    if selected:
        classes.append("is-selected")

    value_classes = ["metric-value"]
    if hero:
        value_classes.append("is-hero")
    if accent:
        value_classes.append("is-accent")

    delta_html = ""
    if delta:
        delta_class = "metric-delta"
        stripped = delta.strip()
        if stripped.startswith("+"):
            delta_class += " is-positive"
        elif stripped.startswith("-") and not stripped.startswith("--"):
            delta_class += " is-negative"
        delta_html = f'<div class="{delta_class}">{html.escape(delta)}</div>'

    st.markdown(
        f'<div class="{" ".join(classes)}">'
        f'<div class="metric-label">{html.escape(label)}</div>'
        f'<div class="{" ".join(value_classes)}">{html.escape(value)}</div>'
        f"{delta_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def character_tile(short_name: str, row: dict | None, *, selected: bool) -> None:
    """Per-character tile: name eyebrow, big win rate, two muted subrows."""
    classes = ["metric-card"]
    if selected:
        classes.append("is-selected")

    if row and row["runs"] > 0:
        win_rate = f"{row['win_rate']:.1%}"
        runs_row = (
            f'<div class="tile-subrow"><span>Runs</span>'
            f'<span class="v">{row["runs"]}</span></div>'
        )
        floors_row = (
            f'<div class="tile-subrow"><span>Avg floors</span>'
            f'<span class="v">{row["avg_floors_reached"]:.1f}</span></div>'
        )
    else:
        win_rate = "—"
        runs_row = (
            '<div class="tile-subrow"><span>Runs</span>'
            '<span class="v">0</span></div>'
        )
        floors_row = (
            '<div class="tile-subrow"><span>Avg floors</span>'
            '<span class="v">—</span></div>'
        )

    st.markdown(
        f'<div class="{" ".join(classes)}">'
        f'<div class="metric-label">{html.escape(short_name)}</div>'
        f'<div class="metric-value">{win_rate}</div>'
        f"{runs_row}{floors_row}"
        f"</div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Sidebar — filters (same shape as Phase 2)
# ---------------------------------------------------------------------------

st.sidebar.markdown(
    '<div class="eyebrow" style="margin: 0 0 0.75rem 0;">Filters</div>',
    unsafe_allow_html=True,
)

mode_label = st.sidebar.radio(
    "Mode",
    ["Solo", "Co-op", "Both"],
    index=0,
)
mode_map = {"Solo": "solo", "Co-op": "coop", "Both": "both"}

game_mode_label = st.sidebar.radio(
    "Game mode",
    ["Standard", "All"],
    index=0,
)
game_mode_map = {"Standard": "standard", "All": "all"}

st.sidebar.markdown("<hr>", unsafe_allow_html=True)

include_abandoned = st.sidebar.checkbox("Include abandoned runs", value=False)
ascension_min = st.sidebar.slider("Minimum ascension", 0, 20, 0)

st.sidebar.markdown("<hr>", unsafe_allow_html=True)

character_label = st.sidebar.selectbox(
    "Character",
    ["All", "IRONCLAD", "SILENT", "DEFECT", "REGENT", "NECROBINDER"],
    index=0,
)
character_value = None if character_label == "All" else f"CHARACTER.{character_label}"

filters: dict = {
    "mode": mode_map[mode_label],
    "game_mode": game_mode_map[game_mode_label],
    "include_abandoned": include_abandoned,
    "ascension_min": ascension_min,
    "character": character_value,
}

st.sidebar.markdown("<hr>", unsafe_allow_html=True)

if st.sidebar.button("Refresh data", use_container_width=True):
    with st.spinner("Re-importing..."):
        _do_import()
    st.rerun()

with connect(DB_PATH) as _info_conn:
    _total_runs_in_db = _info_conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

_last_import = st.session_state.get("last_import_at")
_last_import_str = _last_import.strftime("%Y-%m-%d %H:%M") if _last_import else "unknown"
st.sidebar.markdown(
    f'<div style="color:{PALETTE["text_secondary"]};font-size:11px;'
    f'line-height:1.5;margin-top:0.5rem;">'
    f'Last import<br><span style="color:{PALETTE["text_primary"]};font-variant-numeric:tabular-nums;">'
    f'{html.escape(_last_import_str)}</span><br>'
    f'<span style="font-variant-numeric:tabular-nums;">{_total_runs_in_db}</span> runs in DB'
    f'</div>',
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Page header strip
# ---------------------------------------------------------------------------

_now = datetime.now().strftime("%Y-%m-%d %H:%M")
st.markdown(
    f'<div class="page-header">'
    f'<h1>Spire Stats</h1>'
    f'<span class="last-sync">Last sync {html.escape(_last_import_str)}</span>'
    f"</div>",
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

conn = connect(DB_PATH)

topline = queries.topline_stats(conn, filters)
per_char = queries.per_character_stats(conn, filters)
wr_over_time = queries.win_rate_over_time(conn, filters, window=20)
dmg_per_act = queries.damage_per_act(conn, filters)

total_runs = topline.get("total_runs", 0)
win_rate = topline.get("win_rate", 0.0) or 0.0
best_streak = topline.get("best_streak", 0)
most_played_asc = topline.get("most_played_ascension")
wins = topline.get("wins", 0)
losses = topline.get("losses", 0)


# ---------------------------------------------------------------------------
# Topline — hero win rate + 3 supporting tiles
# ---------------------------------------------------------------------------

_eyebrow("Topline")

hero_col, side_col = st.columns([2, 3], gap="small")

with hero_col:
    metric_card(
        "Win rate",
        f"{win_rate:.1%}" if total_runs else "—",
        delta=(f"{wins}W / {losses}L" if total_runs else None),
        hero=True,
        accent=True,
    )

with side_col:
    s1, s2, s3 = st.columns(3, gap="small")
    with s1:
        metric_card("Total runs", f"{total_runs}")
    with s2:
        metric_card("Best streak", f"{best_streak}")
    with s3:
        metric_card(
            "Top ascension",
            f"A{most_played_asc}" if most_played_asc is not None else "—",
        )


# ---------------------------------------------------------------------------
# Empty-state guard (early exit, same behavior as Phase 2)
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
        "Phase 2 of 5 — card rankings (WAR, Elo) coming in Phase 3."
        "</div>",
        unsafe_allow_html=True,
    )
    conn.close()
    st.stop()


# ---------------------------------------------------------------------------
# Characters — 5-tile row
# ---------------------------------------------------------------------------

_eyebrow("Characters")

per_char_by_name = {row["character"]: row for row in per_char}

char_cols = st.columns(len(CHARACTERS), gap="small")
for col, char in zip(char_cols, CHARACTERS):
    short = char.replace("CHARACTER.", "")
    row = per_char_by_name.get(char)
    is_selected = character_value == char
    with col:
        character_tile(short, row, selected=is_selected)


# ---------------------------------------------------------------------------
# Trends — rolling win rate (left) + damage per act (right)
# ---------------------------------------------------------------------------

_eyebrow("Trends")

left_col, right_col = st.columns([3, 2], gap="small")

with left_col:
    st.markdown(
        '<div class="chart-card">'
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
            .mark_line(
                strokeWidth=2,
                color=PALETTE["accent"],
                interpolate="monotone",
            )
            .encode(
                x=alt.X(
                    "run_index:Q",
                    axis=alt.Axis(title="Run #", labelFlush=False),
                ),
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
            .properties(height=280)
        )
        st.altair_chart(line, use_container_width=True, theme=None)
    st.markdown("</div>", unsafe_allow_html=True)

with right_col:
    st.markdown(
        '<div class="chart-card">'
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

        # Preserve canonical character order in the legend / color scale.
        char_order = [c.replace("CHARACTER.", "") for c in CHARACTERS]
        present_order = [c for c in char_order if c in set(dmg_df["character_short"])]

        bars = (
            alt.Chart(dmg_df)
            .mark_bar(
                cornerRadiusTopLeft=2,
                cornerRadiusTopRight=2,
            )
            .encode(
                x=alt.X(
                    "act_label:N",
                    axis=alt.Axis(title=None, labelAngle=0),
                    sort=sorted(dmg_df["act_label"].unique()),
                ),
                xOffset=alt.XOffset(
                    "character_short:N", sort=present_order
                ),
                y=alt.Y(
                    "avg_damage:Q",
                    axis=alt.Axis(title="Avg damage taken", format=",.0f"),
                ),
                color=alt.Color(
                    "character_short:N",
                    sort=present_order,
                    scale=alt.Scale(
                        domain=char_order, range=CHARACTER_RANGE
                    ),
                    legend=alt.Legend(title=None),
                ),
                tooltip=[
                    alt.Tooltip("character_short:N", title="Character"),
                    alt.Tooltip("act_label:N", title="Act"),
                    alt.Tooltip("avg_damage:Q", title="Avg damage", format=",.1f"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(bars, use_container_width=True, theme=None)
    st.markdown("</div>", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown(
    '<div class="app-footer">'
    "Phase 2 of 5 — card rankings (WAR, Elo) coming in Phase 3."
    "</div>",
    unsafe_allow_html=True,
)

conn.close()
