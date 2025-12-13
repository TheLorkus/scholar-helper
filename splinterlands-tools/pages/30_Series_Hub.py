from __future__ import annotations

import streamlit as st

from core.config import setup_page


setup_page("Series Hub")


def render_page() -> None:
    st.title("Series Hub")
    st.caption("Quick links to Series tools.")

    st.page_link("pages/30_Tournament_Series.py", label="Tournament Series (full)", icon="📊")
    st.page_link("pages/31_Series_Leaderboard.py", label="Series Leaderboard (config)", icon="🎟️")


if __name__ == "__main__":
    render_page()
