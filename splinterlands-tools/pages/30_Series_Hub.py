from __future__ import annotations

import streamlit as st

from core.config import setup_page
from series import leaderboard, tournament


setup_page("Series Hub")


def render_page() -> None:
    st.title("Series Hub")
    st.caption("Quick links to Series tools.")

    view = st.session_state.get("__series_view", "leaderboard")
    view = st.radio(
        "Pick a view",
        options=["leaderboard", "tournament"],
        format_func=lambda v: "Series Leaderboard" if v == "leaderboard" else "Tournament Configurator (organizers)",
        horizontal=True,
        index=0 if view == "leaderboard" else 1,
        key="__series_view",
    )

    st.divider()

    if view == "leaderboard":
        st.header("Series Leaderboard", divider="gray")
        leaderboard.render_page(embed_mode=True)
    else:
        st.header("Tournament Configurator (organizers)", divider="gray")
        tournament.render_page(embed_mode=True)

        st.divider()
        st.subheader("Docs: Tournament Series")
        try:
            with open("Tournament_Series.md", "r", encoding="utf-8") as f:
                doc_text = f.read()
            st.markdown(doc_text)
        except Exception as exc:  # pragma: no cover - best-effort embed
            st.error(f"Failed to load Tournament_Series.md: {exc}")


if __name__ == "__main__":
    render_page()
