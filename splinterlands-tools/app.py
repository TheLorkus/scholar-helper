from __future__ import annotations

import streamlit as st

from core.config import setup_page
from core.home import render_home


setup_page("Splinterlands Tools Hub")


def main() -> None:
    """Entry point for the multipage Streamlit hub."""
    try:
        # Route to the ordered Home page so the sidebar keeps the multipage order.
        st.switch_page("pages/01_Home.py")
        return
    except Exception:
        # Fallback for environments without switch_page support.
        render_home()


if __name__ == "__main__":
    main()
