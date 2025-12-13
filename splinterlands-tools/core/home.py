from __future__ import annotations

import os
import streamlit as st


def render_home() -> None:
    st.title("Splinterlands Tools Hub")
    st.caption("Pick a tool to jump in, or open a page from the sidebar.")

    st.markdown("### Featured tools")
    st.page_link("pages/10_Brawl_Dashboard.py", label="Brawl Dashboard", icon="🛡️")
    st.page_link("pages/20_Rewards_Tracker.py", label="Rewards Tracker", icon="🎓")
    series_page = (
        "pages/30_Tournament_Series.py"
        if os.path.exists("pages/30_Tournament_Series.py")
        else ("pages/30_Series_Hub.py" if os.path.exists("pages/30_Series_Hub.py") else None)
    )
    if series_page:
        st.page_link(series_page, label="Tournament Series", icon="🏆")

    st.markdown("### Coming soon")
    st.page_link("pages/40_SPS_Analytics.py", label="SPS Analytics", icon="📈")

    st.info("Use the sidebar to switch between pages at any time.")
