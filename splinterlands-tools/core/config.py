from __future__ import annotations

import os

from dotenv import load_dotenv
import streamlit as st


_ENV_LOADED_FLAG = "_SL_TOOLS_ENV_LOADED"


def setup_page(title: str, layout: str = "wide") -> None:
    """Set common page config and load environment variables once."""
    if not os.environ.get(_ENV_LOADED_FLAG):
        load_dotenv()
        os.environ[_ENV_LOADED_FLAG] = "1"
    st.set_page_config(page_title=title, layout=layout)
    # Hide the implicit main page entry in the sidebar nav.
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNav"] li:first-child {display: none !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )
