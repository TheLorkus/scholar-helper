from __future__ import annotations

import streamlit as st

from core.config import setup_page


setup_page("Series Hub")


def render_page() -> None:
    st.title("Series Hub")
    st.caption("Quick links to Series tools.")

    st.page_link("pages/series/31_Series_Leaderboard.py", label="Series Leaderboard", icon="🎟️")
    st.page_link("pages/series/30_Tournament_Series.py", label="Tournament Configurator (organizers)", icon="📊")


if __name__ == "__main__":
    render_page()
