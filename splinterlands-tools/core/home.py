from __future__ import annotations

import streamlit as st


def render_home() -> None:
    st.title("Splinterlands Tools Hub")
    st.caption("Pick a tool to jump in, or open a page from the sidebar.")

    st.markdown("### Featured tools")
    st.page_link("app.py", label="Home (current)", icon="🏠")
    st.page_link("pages/10_Brawl_Dashboard.py", label="Brawl Dashboard", icon="🛡️")
    st.page_link("pages/20_Scholar_Helper.py", label="Scholar Helper", icon="🎓")

    st.markdown("### Coming soon")
    st.page_link("pages/30_SPS_Analytics.py", label="SPS Analytics", icon="📈")

    st.info("Use the sidebar to switch between pages at any time.")
