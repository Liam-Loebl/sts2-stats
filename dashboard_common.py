"""Shared dashboard scaffolding for the multipage Streamlit app.

The app moved to Streamlit's `st.navigation` multipage pattern in Phase 3:
`app.py` is the router + shared chrome (theme, CSS, sidebar filters,
import-on-load), and each view under `views/` renders one page's content.
Everything both pages need lives here so neither the theme nor the filter
sidebar drifts between pages.

Public API:
  apply_theme()              -> (mode, palette); resolves theme, injects CSS, registers Altair
  import_on_load()           -> run the idempotent import once per session if the DB is stale
  render_sidebar(mode, palette) -> filters dict (theme toggle + filters + refresh + last-import)
  connect_db()               -> open sqlite connection to the local DB
  page_header(title)         -> the title + last-sync strip at the top of a view
  eyebrow / metric_card / character_tile -> shared render helpers
  CHARACTERS                 -> canonical roster order (positional with theme.CHARACTER_RANGE)
"""
from __future__ import annotations

import html
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from sts2_stats import reworks
from sts2_stats.db import connect
from sts2_stats.importer import import_all
from sts2_stats.paths import find_history_dirs, iter_run_files
from theme import PALETTES, get_css, register_altair_theme


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DB_PATH = Path(__file__).parent / "sts2_stats.sqlite"
IMPORT_STALE_SECONDS = 5 * 60  # re-import if DB older than 5 minutes

# Canonical roster order — positional with theme.CHARACTER_RANGE. Order matches
# the in-game character-select UI (Defect last).
CHARACTERS = [
    "CHARACTER.IRONCLAD",
    "CHARACTER.SILENT",
    "CHARACTER.NECROBINDER",
    "CHARACTER.REGENT",
    "CHARACTER.DEFECT",
]


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

def apply_theme() -> tuple[str, dict]:
    """Resolve the active theme, inject CSS, register the Altair theme.

    Defaults to dark (no flashbang on first load). Must be called on every
    page render (each page script runs top-to-bottom independently).
    """
    if "theme_mode" not in st.session_state:
        st.session_state["theme_mode"] = "dark"
    mode = st.session_state["theme_mode"]
    palette = PALETTES[mode]
    st.markdown(get_css(palette, mode=mode), unsafe_allow_html=True)
    register_altair_theme(palette)
    return mode, palette


# ---------------------------------------------------------------------------
# Import-on-first-load
# ---------------------------------------------------------------------------

def _db_is_stale() -> bool:
    if not DB_PATH.exists():
        return True
    return (time.time() - DB_PATH.stat().st_mtime) > IMPORT_STALE_SECONDS


def do_import() -> dict:
    """Run import_all() and remember when we did it."""
    summary = import_all(DB_PATH)
    st.session_state["last_import_at"] = datetime.now()
    st.session_state["last_import_summary"] = summary
    return summary


def import_on_load() -> None:
    """Import new runs once per session if the DB looks stale."""
    if "last_import_at" in st.session_state:
        return
    if _db_is_stale():
        with st.spinner("Importing run history..."):
            do_import()
    else:
        st.session_state["last_import_at"] = datetime.fromtimestamp(DB_PATH.stat().st_mtime)
        st.session_state["last_import_summary"] = None


def connect_db():
    return connect(DB_PATH)


def _last_import_str() -> str:
    last = st.session_state.get("last_import_at")
    return last.strftime("%Y-%m-%d %H:%M") if last else "unknown"


# ---------------------------------------------------------------------------
# Auto-update watcher (Phase 5) — Streamlit-native, no background threads
# ---------------------------------------------------------------------------

WATCH_INTERVAL = "10s"  # how often to poll the history folder for new runs


def _history_signature() -> tuple[int, int]:
    """Cheap fingerprint of the run-history folder(s): (#run files, newest mtime).

    Changes exactly when a run is written (a finished run drops a new
    <start_time>.run) or Steam Cloud syncs one down — and never opens a file."""
    count, newest = 0, 0
    for d in find_history_dirs():
        for p in iter_run_files(d):
            count += 1
            try:
                newest = max(newest, int(p.stat().st_mtime))
            except OSError:
                pass
    return (count, newest)


@st.fragment(run_every=WATCH_INTERVAL)
def _watch_tick() -> None:
    """Poll the folder on an interval; on a new run, re-import and rerun the whole
    app so every view refreshes. Only this fragment re-runs on the interval, so the
    poll is cheap — a real change is what triggers the import + full app rerun."""
    sig = _history_signature()
    if sig != st.session_state.get("_history_sig"):
        st.session_state["_history_sig"] = sig
        do_import()
        st.rerun()  # scope="app": refresh topline, charts, board — everything
    st.caption(f"Auto-refresh on · checking every {WATCH_INTERVAL}")


def _render_watcher() -> None:
    """Sidebar control + loop for the auto-update watcher."""
    enabled = st.sidebar.toggle(
        "Auto-refresh", value=True, key="_watch_enabled",
        help=f"Check for new runs every {WATCH_INTERVAL} and refresh automatically "
             "when one finishes.",
    )
    # Seed the baseline so the first tick doesn't reimport on a non-change.
    if "_history_sig" not in st.session_state:
        st.session_state["_history_sig"] = _history_signature()
    if enabled:
        with st.sidebar:
            _watch_tick()


# ---------------------------------------------------------------------------
# Sidebar (theme toggle + filters + refresh + last-import) — shared by all pages
# ---------------------------------------------------------------------------

def render_sidebar(mode: str, palette: dict) -> dict:
    """Render the shared sidebar and return the active `filters` dict.

    Widget keys are fixed so selections persist across page switches.
    """
    # Theme toggle
    st.sidebar.markdown(
        '<div class="eyebrow" style="margin: 0 0 0.75rem 0;">Theme</div>',
        unsafe_allow_html=True,
    )
    theme_choice = st.sidebar.radio(
        "Theme", ["Dark", "Light"],
        index=0 if mode == "dark" else 1,
        horizontal=True, label_visibility="collapsed", key="_theme_choice_radio",
    )
    new_mode = "dark" if theme_choice == "Dark" else "light"
    if new_mode != mode:
        st.session_state["theme_mode"] = new_mode
        st.rerun()

    st.sidebar.markdown("<hr>", unsafe_allow_html=True)
    st.sidebar.markdown(
        '<div class="eyebrow" style="margin: 0 0 0.75rem 0;">Filters</div>',
        unsafe_allow_html=True,
    )

    mode_label = st.sidebar.radio("Mode", ["Solo", "Co-op", "Both"], index=0, key="_mode_radio")
    mode_map = {"Solo": "solo", "Co-op": "coop", "Both": "both"}

    game_mode_label = st.sidebar.radio("Game mode", ["Standard", "All"], index=0, key="_gamemode_radio")
    game_mode_map = {"Standard": "standard", "All": "all"}

    st.sidebar.markdown("<hr>", unsafe_allow_html=True)

    include_abandoned = st.sidebar.checkbox("Include abandoned runs", value=False, key="_abandoned_cb")
    ascension_min = st.sidebar.slider("Minimum ascension", 0, 10, 0, key="_ascension_slider")

    # Patch window — restrict every stat to runs from a chosen game version
    # onward. A discrete select_slider over the versions actually present (not a
    # numeric slider: versions aren't evenly spaced and build_id sorts wrong
    # lexically). "All" = no filter. We pass the qualifying build_ids (not the
    # cutoff) because build_id can't be range-compared in SQL.
    pconn = connect_db()
    try:
        versions = sorted(
            (b for (b,) in pconn.execute(
                "SELECT DISTINCT build_id FROM runs WHERE build_id IS NOT NULL AND build_id != ''")),
            key=reworks.version_key,
        )
    finally:
        pconn.close()
    build_ids = None
    if versions:
        patch_choice = st.sidebar.select_slider(
            "Minimum patch",
            options=["All", *versions],
            value="All",
            key="_patch_min_slider",
            help="Only include runs from this game version onward.",
        )
        if patch_choice != "All":
            cutoff = reworks.version_key(patch_choice)
            build_ids = [b for b in versions if reworks.version_key(b) >= cutoff]

    filters = {
        "mode": mode_map[mode_label],
        "game_mode": game_mode_map[game_mode_label],
        "include_abandoned": include_abandoned,
        "ascension_min": ascension_min,
        # None = all patches; else the list of build_ids at/after the chosen patch.
        "build_ids": build_ids,
        # Character is chosen per-page: Card Rankings has its own Overall / per-
        # character control, and the Overview always shows all five characters.
        # (A second sidebar Character control silently diverged from the board's.)
        "character": None,
    }

    st.sidebar.markdown("<hr>", unsafe_allow_html=True)
    if st.sidebar.button("Refresh data", width="stretch", key="_refresh_btn"):
        with st.spinner("Re-importing..."):
            do_import()
        st.rerun()

    _render_watcher()

    # Last-import info
    info_conn = connect_db()
    try:
        total_runs_in_db = info_conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    finally:
        info_conn.close()

    st.sidebar.markdown(
        f'<div style="color:{palette["text_secondary"]};font-size:11px;'
        f'line-height:1.5;margin-top:0.5rem;">'
        f'Last import<br><span style="color:{palette["text_primary"]};font-variant-numeric:tabular-nums;">'
        f'{html.escape(_last_import_str())}</span><br>'
        f'<span style="font-variant-numeric:tabular-nums;">{total_runs_in_db}</span> runs in DB'
        f'</div>',
        unsafe_allow_html=True,
    )
    return filters


# ---------------------------------------------------------------------------
# Render helpers (shared across pages)
# ---------------------------------------------------------------------------

def page_header(title: str) -> None:
    st.markdown(
        f'<div class="page-header">'
        f'<h1>{html.escape(title)}</h1>'
        f'<span class="last-sync">Last sync {html.escape(_last_import_str())}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )


def eyebrow(text: str) -> None:
    st.markdown(f'<div class="eyebrow">{html.escape(text)}</div>', unsafe_allow_html=True)


def sample_warning(n: int | None, *, floor: int = 10, noun: str = "offers", palette: dict) -> bool:
    """Render a 'small sample' caution banner when `n` is below the offer floor.

    Keeps the detail pages honest: the Card Rankings board hides anything below the
    floor rather than showing it at face value, so a detail page must flag when its
    own numbers fall below that same bar. Returns True if a warning was shown.
    """
    if n is None or n >= floor:
        return False
    neg = palette["negative"]
    st.markdown(
        f'<div style="border-left:3px solid {neg};'
        f"background:color-mix(in srgb, {neg} 10%, transparent);"
        f'color:{palette["text_primary"]};padding:0.5rem 0.75rem;border-radius:8px;'
        f'margin:0.3rem 0 0.85rem;font-size:13px;line-height:1.45;">'
        f"<strong>Small sample.</strong> Only {n} {html.escape(noun)} — read these as noise, "
        f"not signal. The Card Rankings board hides anything below {floor} {html.escape(noun)} "
        f"for this reason; the numbers are shown here with N so you can judge for yourself.</div>",
        unsafe_allow_html=True,
    )
    return True


def metric_card(
    label: str,
    value: str,
    delta: str | None = None,
    *,
    accent: bool = False,
    selected: bool = False,
    secondary: bool = False,
) -> None:
    """Hand-rolled metric tile. Replaces st.metric."""
    classes = ["metric-card"]
    if selected:
        classes.append("is-selected")

    value_classes = ["metric-value"]
    if secondary:
        value_classes.append("is-secondary")
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


def character_tile(short_name: str, row: dict | None, *, selected: bool, color: str) -> None:
    """Per-character tile: colored top stripe + faint identity wash, big win
    rate, a win-rate bar (so the row reads as a comparison strip), one meta line."""
    classes = ["metric-card", "character-tile"]
    if selected:
        classes.append("is-selected")

    if row and row["runs"] > 0:
        pct = max(0.0, min(100.0, row["win_rate"] * 100))
        win_rate = f"{row['win_rate']:.1%}"
        bar = (
            '<div class="tile-bar"><div class="tile-bar-fill" '
            f'style="width: {pct:.0f}%;"></div></div>'
        )
        meta = (
            f'<div class="tile-meta">{row["wins"]}W / {row["runs"]} runs '
            f'· {row["avg_floors_reached"]:.0f} avg floors</div>'
        )
    else:
        win_rate = "—"
        bar = '<div class="tile-bar"></div>'
        meta = '<div class="tile-meta">No runs</div>'

    st.markdown(
        f'<div class="{" ".join(classes)}" style="--char-color: {html.escape(color)};">'
        f'<div class="metric-label">{html.escape(short_name)}</div>'
        f'<div class="metric-value">{win_rate}</div>'
        f"{bar}{meta}"
        f"</div>",
        unsafe_allow_html=True,
    )
