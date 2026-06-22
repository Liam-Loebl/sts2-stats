"""Slay the Spire 2 Stats — Phase 2: Overview Dashboard.

Streamlit entrypoint. Run with:

    streamlit run app.py

Sidebar filters drive every panel: solo/co-op, standard/all, abandoned,
ascension floor, character. Charts and topline metrics all flow through
sts2_stats.queries so the SQL lives in one place.
"""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from sts2_stats import queries
from sts2_stats.db import connect
from sts2_stats.importer import import_all
from sts2_stats.paths import find_history_dirs


# ---------------------------------------------------------------------------
# Config
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


# ---------------------------------------------------------------------------
# Import-on-first-load
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
        # DB is fresh enough; record the file's mtime as our "last import"
        st.session_state["last_import_at"] = datetime.fromtimestamp(DB_PATH.stat().st_mtime)
        st.session_state["last_import_summary"] = None


# ---------------------------------------------------------------------------
# Sidebar — filters
# ---------------------------------------------------------------------------

st.sidebar.markdown("## Filters")

mode_label = st.sidebar.radio(
    "Mode",
    ["Solo", "Co-op", "Both"],
    index=0,
    help="Solo = is_multiplayer = 0; Co-op = is_multiplayer = 1.",
)
mode_map = {"Solo": "solo", "Co-op": "coop", "Both": "both"}

game_mode_label = st.sidebar.radio(
    "Game mode",
    ["Standard", "All"],
    index=0,
)
game_mode_map = {"Standard": "standard", "All": "all"}

include_abandoned = st.sidebar.checkbox("Include abandoned runs", value=False)

ascension_min = st.sidebar.slider("Minimum ascension", 0, 20, 0)

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

st.sidebar.divider()

if st.sidebar.button("Refresh data", use_container_width=True):
    with st.spinner("Re-importing..."):
        _do_import()
    st.rerun()

# Bottom-of-sidebar status caption (last import + total runs in DB)
with connect(DB_PATH) as _info_conn:
    _total_runs_in_db = _info_conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

_last_import = st.session_state.get("last_import_at")
_last_import_str = _last_import.strftime("%Y-%m-%d %H:%M:%S") if _last_import else "unknown"
st.sidebar.caption(
    f"Last import: {_last_import_str}  \n"
    f"{_total_runs_in_db} runs in DB"
)


# ---------------------------------------------------------------------------
# Main — header
# ---------------------------------------------------------------------------

st.title("Slay the Spire 2 Stats")
st.caption(
    "Personal run-data dashboard. Phase 2 covers topline metrics, per-character "
    "results, rolling win rate, and damage taken per act. Filters in the sidebar "
    "apply to every panel below."
)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

conn = connect(DB_PATH)

topline = queries.topline_stats(conn, filters)
per_char = queries.per_character_stats(conn, filters)
wr_over_time = queries.win_rate_over_time(conn, filters, window=20)
dmg_per_act = queries.damage_per_act(conn, filters)


# ---------------------------------------------------------------------------
# Topline metrics row
# ---------------------------------------------------------------------------

c1, c2, c3, c4 = st.columns(4)

total_runs = topline.get("total_runs", 0)
win_rate = topline.get("win_rate", 0.0) or 0.0
best_streak = topline.get("best_streak", 0)
most_played_asc = topline.get("most_played_ascension")

c1.metric("Total runs", f"{total_runs}")
c2.metric(
    "Win rate",
    f"{win_rate:.1%}" if total_runs else "—",
    help=f"{topline.get('wins', 0)}W / {topline.get('losses', 0)}L",
)
c3.metric("Best streak", f"{best_streak}")
c4.metric(
    "Most-played ascension",
    f"A{most_played_asc}" if most_played_asc is not None else "—",
)

st.divider()


# ---------------------------------------------------------------------------
# Empty-state guard
# ---------------------------------------------------------------------------

if total_runs == 0:
    st.info("No runs match these filters.")
    st.caption(
        "Phase 2: Overview Dashboard. Phase 3 adds card rankings + WAR + Elo."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Per-character tiles
# ---------------------------------------------------------------------------

st.subheader("By character")

# Index per_char results by character name so we can render all 5 tiles in
# a fixed order (even characters with 0 runs after filtering).
per_char_by_name = {row["character"]: row for row in per_char}

char_cols = st.columns(len(CHARACTERS))
for col, char in zip(char_cols, CHARACTERS):
    short = char.replace("CHARACTER.", "")
    row = per_char_by_name.get(char)
    if row and row["runs"] > 0:
        col.metric(
            short,
            f"{row['win_rate']:.1%}",
            help=(
                f"{row['runs']} runs, {row['wins']} wins, "
                f"avg floors {row['avg_floors_reached']:.1f}"
            ),
        )
        col.caption(f"n={row['runs']}")
    else:
        col.metric(short, "—", help="No runs match these filters.")
        col.caption("n=0")

st.divider()


# ---------------------------------------------------------------------------
# Rolling win rate
# ---------------------------------------------------------------------------

st.subheader("Rolling 20-run win rate")

if not wr_over_time:
    st.caption("Need at least 20 runs after filters to draw the rolling win rate.")
else:
    wr_df = pd.DataFrame(wr_over_time)
    wr_df = wr_df.set_index("run_index")[["win_rate"]]
    st.line_chart(wr_df, height=300)

st.divider()


# ---------------------------------------------------------------------------
# Damage per act, by character
# ---------------------------------------------------------------------------

st.subheader("Average damage taken per act, by character")

if not dmg_per_act:
    st.caption("No damage data for the current filters.")
else:
    dmg_df = pd.DataFrame(dmg_per_act)
    # Strip the "CHARACTER." prefix for cleaner axis labels.
    dmg_df["character_short"] = dmg_df["character"].str.replace(
        "CHARACTER.", "", regex=False
    )
    # Pivot to character x act, with one column per act ("Act 1", "Act 2", ...).
    pivot = dmg_df.pivot_table(
        index="character_short",
        columns="act",
        values="avg_damage",
        aggfunc="mean",
    )
    pivot.columns = [f"Act {int(c)}" for c in pivot.columns]
    pivot.index.name = "Character"
    # Preserve canonical character order where possible.
    order = [c.replace("CHARACTER.", "") for c in CHARACTERS]
    pivot = pivot.reindex([c for c in order if c in pivot.index])
    st.bar_chart(pivot, height=350)


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.divider()
st.caption("Phase 2: Overview Dashboard. Phase 3 adds card rankings + WAR + Elo.")

conn.close()
