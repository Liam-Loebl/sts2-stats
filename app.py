"""Slay the Spire 2 Stats — multipage Streamlit app.

Run with:

    streamlit run app.py

This file is the router + shared chrome only. Page content lives in
`views/overview.py` and `views/card_rankings.py`. Shared theme, sidebar
filters, render helpers, and the import-on-load all live in
`dashboard_common`, so neither the look nor the filter state drifts
between pages.
"""
from __future__ import annotations

import streamlit as st

import dashboard_common as dc

st.set_page_config(
    page_title="Slay the Spire 2 Stats",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Theme + CSS + Altair must be (re)applied on every page render.
mode, palette = dc.apply_theme()

# Navigation lives at the top of the sidebar; the shared filters render below it.
nav = st.navigation([
    st.Page("views/overview.py", title="Overview", default=True),
    st.Page("views/card_rankings.py", title="Card Rankings"),
    st.Page("views/card_detail.py", title="Card Detail"),
])

dc.import_on_load()
filters = dc.render_sidebar(mode, palette)

# Stash shared context so the selected view reads it without re-deriving.
st.session_state["filters"] = filters
st.session_state["palette"] = palette
st.session_state["mode"] = mode

nav.run()
