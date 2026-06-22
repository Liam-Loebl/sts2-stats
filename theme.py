"""Visual theme for the Slay the Spire 2 stats dashboard.

Two things live here:

1. ``CSS`` — a single CSS string injected once at the top of ``app.py``
   via ``st.markdown(CSS, unsafe_allow_html=True)``. It loads Inter,
   hides Streamlit chrome, tightens page padding, and gives sidebar /
   sections their dark-neutral look. No brown. No serif.

2. ``register_altair_theme()`` — registers a custom Altair theme named
   ``'sts2'`` and enables it. Call once on app startup. Pass
   ``theme=None`` to ``st.altair_chart`` so Streamlit doesn't clobber
   it.

The palette is the single source of truth — every other file that
needs a hex value should import from ``PALETTE``.
"""
from __future__ import annotations

import altair as alt


# ---------------------------------------------------------------------------
# Palette — the single source of truth. No brown anywhere.
# ---------------------------------------------------------------------------

PALETTE = {
    "background":     "#0B0D10",
    "surface":        "#13161B",
    "border":         "#1F242C",
    "text_primary":   "#E6E8EB",
    "text_secondary": "#8A929E",
    "accent":         "#7C5CFF",
    "accent_muted":   "#7C5CFF26",
    "positive":       "#3FB950",
    "negative":       "#F85149",
}

# Character colors — positional, pairs with the CHARACTERS list in app.py
# (IRONCLAD, SILENT, NECROBINDER, REGENT, DEFECT) via domain=char_order on
# the Altair color scale. Order matches the in-game UI (Defect last).
#
# Hexes extracted (Nov 2026) from the StS2 energy-orb PNGs hosted on
# slaythespire.wiki.gg — the official wiki's canonical class-color icon
# (the orb that marks each card's character). Two independent agents
# pixel-bucketed the orb art; values below are the saturation-weighted
# rim/identity color for each character. Mega Crit does not publish
# official hex values; these are the closest-to-source numbers available.
CHARACTER_RANGE = [
    "#c8232f",  # Ironclad    — deep crimson (darker + more saturated than the orb's
                #                 lighter rim, which read as salmon on the dashboard)
    "#1ed75e",  # Silent      — vivid saturated green (matches user swatch)
    "#c93ea8",  # Necrobinder — saturated purple-magenta (hue pulled toward purple,
                #                 saturation up — the dusty rose reading was too muted)
    "#fa921e",  # Regent      — amber / yellow-orange (hue shifted yellower from the
                #                 orb's red-orange rim)
    "#4d9be0",  # Defect      — clean medium blue, brightened (NOT cyan; the orb has
                #                 zero green channel, only lightened for visibility)
]

FONT_FAMILY = "Inter, 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif"


# ---------------------------------------------------------------------------
# CSS — chrome hiding, Inter, padding, sidebar surface
# ---------------------------------------------------------------------------

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"], .stApp, .stMarkdown, .stText,
section[data-testid="stSidebar"] {{
    font-family: {FONT_FAMILY};
    font-feature-settings: 'tnum' 1, 'cv11' 1;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}}

/* Hide Streamlit chrome */
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ display: none; }}

/* Tighten page padding, cap width */
.block-container {{
    padding: 1.5rem 2rem 3rem 2rem;
    max-width: 1280px;
}}

/* Sidebar surface */
section[data-testid="stSidebar"] {{
    background: {PALETTE['background']};
    border-right: 1px solid {PALETTE['border']};
}}
section[data-testid="stSidebar"] .block-container {{
    padding-top: 2rem;
}}
section[data-testid="stSidebar"] hr {{
    border: 0;
    border-top: 1px solid {PALETTE['border']};
    margin: 1rem 0;
}}
section[data-testid="stSidebar"] label {{
    color: {PALETTE['text_secondary']} !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    letter-spacing: 0.02em;
}}

/* Headings — kill the giant default st.title */
h1, .stMarkdown h1 {{
    font-size: 22px !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
    color: {PALETTE['text_primary']};
    margin: 0 0 0.25rem 0;
}}
h2, .stMarkdown h2 {{
    font-size: 14px !important;
    font-weight: 600 !important;
    color: {PALETTE['text_primary']};
}}
h3, .stMarkdown h3 {{
    font-size: 13px !important;
    font-weight: 600 !important;
    color: {PALETTE['text_primary']};
}}

/* Section eyebrow (small uppercase tracked label between rows) */
.eyebrow {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: {PALETTE['text_secondary']};
    margin: 2rem 0 0.75rem 0;
}}

/* Metric card — hand-rolled, replaces st.metric */
.metric-card {{
    background: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 16px;
    padding: 20px;
    height: 100%;
}}
.metric-card.is-hero {{
    padding: 28px;
    /* Match height of the right-column 2-stack (two cards + 0.5rem gap).
       Without this Streamlit's columns top-align and the hero column
       hangs shorter than its neighbor. */
    min-height: calc(2 * 116px + 0.5rem);
    display: flex;
    flex-direction: column;
    justify-content: center;
}}
.metric-card.is-selected {{
    border-color: {PALETTE['accent']};
}}
.metric-label {{
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: {PALETTE['text_secondary']};
    margin: 0 0 10px 0;
}}
.metric-value {{
    font-size: 32px;
    font-weight: 600;
    line-height: 1.1;
    color: {PALETTE['text_primary']};
    font-variant-numeric: tabular-nums;
    margin: 0;
}}
.metric-value.is-hero {{
    font-size: 48px;
}}
.metric-value.is-accent {{
    color: {PALETTE['accent']};
}}
.metric-delta {{
    font-size: 12px;
    font-weight: 500;
    color: {PALETTE['text_secondary']};
    margin-top: 8px;
    font-variant-numeric: tabular-nums;
}}
.metric-delta.is-positive {{ color: {PALETTE['positive']}; }}
.metric-delta.is-negative {{ color: {PALETTE['negative']}; }}

/* Sub-rows inside character tiles */
.tile-subrow {{
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: {PALETTE['text_secondary']};
    font-variant-numeric: tabular-nums;
    margin-top: 4px;
}}
.tile-subrow .v {{ color: {PALETTE['text_primary']}; font-weight: 500; }}

/* Page header strip — title left, last-sync right */
.page-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 1.5rem;
    padding-bottom: 0;
}}
.page-header .last-sync {{
    color: {PALETTE['text_secondary']};
    font-size: 12px;
    font-variant-numeric: tabular-nums;
}}

/* Chart headers (sit above each chart, columns provide the grouping —
   no bordered wrapper, since Streamlit can't reliably wrap a chart in
   a markdown-emitted div). */
.chart-title {{
    font-size: 13px;
    font-weight: 600;
    color: {PALETTE['text_primary']};
    margin: 0.25rem 0 4px 0;
}}
.chart-sub {{
    font-size: 11px;
    color: {PALETTE['text_secondary']};
    margin: 0 0 12px 0;
}}

/* Footer */
.app-footer {{
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid {PALETTE['border']};
    color: {PALETTE['text_secondary']};
    font-size: 12px;
}}

/* Empty-state pill */
.empty-state {{
    background: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 12px;
    padding: 16px 20px;
    color: {PALETTE['text_secondary']};
    font-size: 13px;
}}

/* Streamlit widget polish: remove the "running" spinner halo color */
.stSpinner > div > div {{
    border-top-color: {PALETTE['accent']} !important;
}}

/* Button polish — keep accent for primary actions only */
.stButton > button {{
    background: {PALETTE['surface']};
    color: {PALETTE['text_primary']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
}}
.stButton > button:hover {{
    border-color: {PALETTE['accent']};
    color: {PALETTE['text_primary']};
}}
</style>
"""


# ---------------------------------------------------------------------------
# Altair theme
# ---------------------------------------------------------------------------

def _sts2_altair_theme() -> dict:
    """Custom Altair theme matching the palette."""
    p = PALETTE
    return {
        "config": {
            "background": p["background"],
            "view": {"stroke": None, "fill": p["surface"], "continuousWidth": 400, "continuousHeight": 280},
            "font": "Inter",
            "title": {
                "color": p["text_primary"],
                "font": "Inter",
                "fontSize": 13,
                "fontWeight": 600,
                "anchor": "start",
                "offset": 12,
            },
            "axis": {
                "domain": False,
                "ticks": False,
                "grid": False,
                "labelColor": p["text_secondary"],
                "labelFont": "Inter",
                "labelFontSize": 11,
                "labelFontWeight": 500,
                "titleColor": p["text_secondary"],
                "titleFont": "Inter",
                "titleFontSize": 11,
                "titleFontWeight": 500,
                "titlePadding": 12,
                "labelPadding": 6,
            },
            "axisY": {
                "grid": True,
                "gridColor": p["border"],
                "gridDash": [2, 4],
                "gridOpacity": 0.6,
                "domain": False,
                "ticks": False,
                "labelColor": p["text_secondary"],
                "titleColor": p["text_secondary"],
            },
            "axisX": {
                "grid": False,
                "domain": False,
                "ticks": False,
                "labelColor": p["text_secondary"],
                "titleColor": p["text_secondary"],
            },
            "legend": {
                "orient": "top",
                "direction": "horizontal",
                "symbolType": "square",
                "symbolSize": 80,
                "labelColor": p["text_primary"],
                "labelFont": "Inter",
                "labelFontSize": 12,
                "titleColor": p["text_secondary"],
                "titleFont": "Inter",
                "titleFontSize": 11,
                "titleFontWeight": 500,
                "padding": 0,
                "offset": 8,
            },
            "range": {
                "category": CHARACTER_RANGE,
            },
            "line": {
                "color": p["accent"],
                "strokeWidth": 2,
            },
            "bar": {
                "color": p["accent"],
                "stroke": None,
            },
            "point": {
                "color": p["accent"],
                "filled": True,
                "size": 40,
            },
            "rule": {"color": p["border"]},
        }
    }


def register_altair_theme() -> None:
    """Register and enable the 'sts2' Altair theme. Idempotent across reruns.

    Altair 5.5+ deprecated `alt.themes.register/enable` in favor of
    `alt.theme.register(...)`. Try the new API first, fall back to the old
    so this works on either generation.
    """
    try:
        # Altair 5.5+ — register() is a decorator-factory that takes
        # (name, *, enable=False) and returns a decorator.
        alt.theme.register("sts2", enable=True)(_sts2_altair_theme)
    except AttributeError:
        # Altair < 5.5 — old API, two function calls.
        alt.themes.register("sts2", _sts2_altair_theme)
        alt.themes.enable("sts2")
