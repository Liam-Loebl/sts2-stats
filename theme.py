"""Visual theme for the Slay the Spire 2 stats dashboard.

Public API after the light/dark refactor:

- ``PALETTES`` — dict keyed by mode (``"dark"`` / ``"light"``). Every
  other file that needs a hex value should read ``PALETTES[mode]`` for
  the active mode, where ``mode`` lives in ``st.session_state``.
- ``CHARACTER_RANGE`` — list of 5 hexes, positional with the
  ``CHARACTERS`` list in app.py. Same in both modes.
- ``get_css(palette, mode="dark")`` — returns the CSS block for the
  active palette. Inject once at the top of app.py via
  ``st.markdown(get_css(palette, mode), unsafe_allow_html=True)``.
- ``register_altair_theme(palette)`` — registers a custom Altair theme
  named ``'sts2'`` bound to the given palette and enables it. Call once
  on app startup AND every time the palette changes. Pass ``theme=None``
  to ``st.altair_chart`` so Streamlit doesn't clobber it.
- ``PALETTE`` — backwards-compat alias for ``PALETTES["dark"]``. Kept
  for any external scripts that imported it before the refactor; new
  code should read from ``PALETTES`` directly.
"""
from __future__ import annotations

import altair as alt


# ---------------------------------------------------------------------------
# Palette — the single source of truth. No brown anywhere.
# ---------------------------------------------------------------------------

PALETTES = {
    "dark": {
        "background":     "#0B0D10",
        "surface":        "#13161B",
        "border":         "#1F242C",
        "text_primary":   "#E6E8EB",
        "text_secondary": "#8A929E",
        "accent":         "#7C5CFF",  # purple, identical in both modes
        "accent_muted":   "#7C5CFF26",
        "positive":       "#3FB950",
        "negative":       "#F85149",
    },
    "light": {
        # Background is a soft warm off-white, not pure #FFFFFF — easier
        # on the eyes and lets the white surface cards visually lift.
        "background":     "#F2EFE8",
        "surface":        "#FFFFFF",  # cards "lift" above the cream bg
        "border":         "#E0DCD2",
        "text_primary":   "#1A1814",  # warm dark, strong contrast on cream
        "text_secondary": "#6B6663",
        "accent":         "#7C5CFF",  # same purple
        "accent_muted":   "#7C5CFF1F",
        "positive":       "#15803D",  # darker for contrast on light bg
        "negative":       "#B91C1C",
    },
}

# Backwards-compat alias — same value the module exported before the
# light-mode refactor. New code should call `get_css(palette)` and read
# from PALETTES[mode] directly.
PALETTE = PALETTES["dark"]

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
    "#e02b32",  # Ironclad    — deep crimson, brightened (R 212 -> 224); still a true
                #                 red, just a notch livelier on the dark background
    "#1eca58",  # Silent      — vivid green, dropped one notch from #1ed75e
                #                 (G 215 -> 202) so it doesn't glow over the rest of the palette
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

def get_css(palette: dict, mode: str = "dark") -> str:
    """Render the full CSS block for the given palette + mode.

    The `mode` argument lets the function emit different rules where a
    palette swap alone isn't enough — currently used to render the
    character-tile name eyebrow in the character's color on dark
    backgrounds (where the saturated hex passes contrast on the surface)
    but in palette['text_primary'] on light, where the same hex would
    fail WCAG small-text contrast against the white card surface.
    """
    char_label_color = "var(--char-color)" if mode == "dark" else palette["text_primary"]
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"], .stApp, .stMarkdown, .stText,
section[data-testid="stSidebar"] {{
    font-family: {FONT_FAMILY};
    font-feature-settings: 'tnum' 1, 'cv11' 1;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}}

/* Critical: override Streamlit's base="dark" page background + default
   text color from .streamlit/config.toml. Without these rules the dark
   base bleeds through in light mode. !important is needed because
   Streamlit's own rules have decent specificity. */
html, body, .stApp, .main {{
    background-color: {palette['background']} !important;
    color: {palette['text_primary']} !important;
}}
.stApp [data-testid="stAppViewContainer"],
.stApp [data-testid="stMain"] {{
    background-color: {palette['background']} !important;
}}
/* Streamlit uses CSS custom properties for its internal widget styling.
   Re-bind them to the active palette so radios / sliders / selectboxes
   pick up the right tones in light mode. */
:root, .stApp {{
    --background-color: {palette['background']};
    --secondary-background-color: {palette['surface']};
    --text-color: {palette['text_primary']};
    --primary-color: {palette['accent']};
}}
/* Catch-all body / markdown / widget text so nothing reverts to
   Streamlit's hardcoded white in light mode. Children with explicit
   color (metric-value, metric-label, chart-title, etc.) win by
   specificity. */
.stApp .stMarkdown,
.stApp .stMarkdown p,
.stApp p,
.stApp .stRadio > label,
.stApp .stCheckbox > label,
.stApp .stSelectbox > label,
.stApp .stSlider > label {{
    color: {palette['text_primary']};
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
    background: {palette['background']};
    border-right: 1px solid {palette['border']};
}}
section[data-testid="stSidebar"] .block-container {{
    padding-top: 2rem;
}}
section[data-testid="stSidebar"] hr {{
    border: 0;
    border-top: 1px solid {palette['border']};
    margin: 1rem 0;
}}
section[data-testid="stSidebar"] label {{
    color: {palette['text_secondary']} !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    letter-spacing: 0.02em;
}}

/* Headings — kill the giant default st.title (!important on color to
   beat Streamlit's base="dark" default which otherwise forces white) */
h1, .stMarkdown h1 {{
    font-size: 22px !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
    color: {palette['text_primary']} !important;
    margin: 0 0 0.25rem 0;
}}
h2, .stMarkdown h2 {{
    font-size: 14px !important;
    font-weight: 600 !important;
    color: {palette['text_primary']} !important;
}}
h3, .stMarkdown h3 {{
    font-size: 13px !important;
    font-weight: 600 !important;
    color: {palette['text_primary']} !important;
}}

/* Section eyebrow (small uppercase tracked label between rows) */
.eyebrow {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: {palette['text_secondary']};
    margin: 2rem 0 0.75rem 0;
}}

/* Metric card — hand-rolled, replaces st.metric */
.metric-card {{
    background: {palette['surface']};
    border: 1px solid {palette['border']};
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
    border-color: {palette['accent']};
}}

/* Character tile — top stripe in the character's color (passed via the
   --char-color CSS variable on the tile div). Name eyebrow also picks
   up the color so the tile reads as "this character" at a glance. */
.metric-card.character-tile {{
    border-top: 3px solid var(--char-color);
    padding-top: 17px;  /* compensate for the stripe height */
}}
.metric-card.character-tile .metric-label {{
    /* Dark mode: name in the character's color (saturated, high contrast
       on the dark surface). Light mode: text_primary, since the same
       saturated hex would fail small-text contrast on white. The colored
       top stripe still carries the identity in light mode. */
    color: {char_label_color};
}}
.metric-label {{
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: {palette['text_secondary']};
    margin: 0 0 10px 0;
}}
.metric-value {{
    font-size: 32px;
    font-weight: 600;
    line-height: 1.1;
    color: {palette['text_primary']};
    font-variant-numeric: tabular-nums;
    margin: 0;
}}
.metric-value.is-hero {{
    font-size: 48px;
}}
.metric-value.is-accent {{
    color: {palette['accent']};
}}
.metric-delta {{
    font-size: 12px;
    font-weight: 500;
    color: {palette['text_secondary']};
    margin-top: 8px;
    font-variant-numeric: tabular-nums;
}}
.metric-delta.is-positive {{ color: {palette['positive']}; }}
.metric-delta.is-negative {{ color: {palette['negative']}; }}

/* Sub-rows inside character tiles */
.tile-subrow {{
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: {palette['text_secondary']};
    font-variant-numeric: tabular-nums;
    margin-top: 4px;
}}
.tile-subrow .v {{ color: {palette['text_primary']}; font-weight: 500; }}

/* Page header strip — title left, last-sync right */
.page-header {{
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 1.5rem;
    padding-bottom: 0;
}}
.page-header .last-sync {{
    color: {palette['text_secondary']};
    font-size: 12px;
    font-variant-numeric: tabular-nums;
}}

/* Chart headers (sit above each chart, columns provide the grouping —
   no bordered wrapper, since Streamlit can't reliably wrap a chart in
   a markdown-emitted div). */
.chart-title {{
    font-size: 13px;
    font-weight: 600;
    color: {palette['text_primary']};
    margin: 0.25rem 0 4px 0;
}}
.chart-sub {{
    font-size: 11px;
    color: {palette['text_secondary']};
    margin: 0 0 12px 0;
}}

/* Footer */
.app-footer {{
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid {palette['border']};
    color: {palette['text_secondary']};
    font-size: 12px;
}}

/* Empty-state pill */
.empty-state {{
    background: {palette['surface']};
    border: 1px solid {palette['border']};
    border-radius: 12px;
    padding: 16px 20px;
    color: {palette['text_secondary']};
    font-size: 13px;
}}

/* Streamlit widget polish: remove the "running" spinner halo color */
.stSpinner > div > div {{
    border-top-color: {palette['accent']} !important;
}}

/* Button polish — keep accent for primary actions only */
.stButton > button {{
    background: {palette['surface']};
    color: {palette['text_primary']};
    border: 1px solid {palette['border']};
    border-radius: 8px;
    font-size: 13px;
    font-weight: 500;
}}
.stButton > button:hover {{
    border-color: {palette['accent']};
    color: {palette['text_primary']};
}}
</style>
"""


# ---------------------------------------------------------------------------
# Altair theme
# ---------------------------------------------------------------------------

def _altair_config(p: dict) -> dict:
    """Build the Altair theme config dict for the given palette."""
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


def register_altair_theme(palette: dict | None = None) -> None:
    """Register and enable the 'sts2' Altair theme for the given palette.

    The theme is registered as a closure over the palette so re-calling
    this function with a different palette (e.g. after a light/dark
    toggle) re-binds the chart colors. Idempotent across reruns.

    Altair 5.5+ deprecated `alt.themes.register/enable` in favor of
    `alt.theme.register(...)`. Try the new API first, fall back to the
    old so this works on either generation.
    """
    if palette is None:
        palette = PALETTES["dark"]

    def theme_fn() -> dict:
        return _altair_config(palette)

    try:
        # Altair 5.5+ — register() is a decorator-factory that takes
        # (name, *, enable=False) and returns a decorator.
        alt.theme.register("sts2", enable=True)(theme_fn)
    except AttributeError:
        # Altair < 5.5 — old API, two function calls.
        alt.themes.register("sts2", theme_fn)
        alt.themes.enable("sts2")
