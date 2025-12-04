from __future__ import annotations

from typing import List

import streamlit as st
from dotenv import load_dotenv

from scholar_helper.models import AggregatedTotals, RewardEntry, SeasonWindow, TournamentResult
from scholar_helper.services.aggregation import aggregate_totals
from scholar_helper.services.api import (
    fetch_current_season,
    fetch_prices,
    fetch_tournaments,
    fetch_unclaimed_balance_history,
)
from scholar_helper.services.storage import (
    get_last_supabase_error,
    get_supabase_client,
    upsert_season_totals,
    upsert_tournament_logs,
)

st.set_page_config(page_title="Scholar Rewards Tracker", layout="wide")
load_dotenv()


@st.cache_data(ttl=300, show_spinner=False)
def cached_season() -> SeasonWindow:
    return fetch_current_season()


@st.cache_data(ttl=300, show_spinner=False)
def cached_prices():
    return fetch_prices()


@st.cache_data(ttl=300, show_spinner=False)
def cached_rewards(username: str) -> List[RewardEntry]:
    return fetch_unclaimed_balance_history(username)


@st.cache_data(ttl=300, show_spinner=False)
def cached_tournaments(username: str) -> List[TournamentResult]:
    return fetch_tournaments(username)


def clear_caches():
    cached_season.clear()  # type: ignore[attr-defined]
    cached_prices.clear()  # type: ignore[attr-defined]
    cached_rewards.clear()  # type: ignore[attr-defined]
    cached_tournaments.clear()  # type: ignore[attr-defined]


def parse_usernames(raw: str) -> List[str]:
    return [name.strip() for name in raw.split(",") if name.strip()]


def _format_price(value) -> str:
    """Render price safely even if cached values are non-numeric."""
    try:
        return f"${float(value):.6f}"
    except Exception:
        return str(value)


def _format_token_amounts_dict(token_amounts, prices) -> str:
    if not token_amounts:
        return "-"
    parts = []
    for token, amount in token_amounts.items():
        usd = (prices.get(token) or 0) * amount
        parts.append(f"{amount:g} {token} (${usd:,.2f})")
    return "; ".join(parts)


def _render_user_summary(username: str, totals: AggregatedTotals, scholar_pct: float) -> None:
    st.markdown(f"**{username}**")
    cols = st.columns(4)
    cols[0].metric("Overall", f"${totals.overall.usd:,.2f}")
    cols[1].metric("Ranked", f"${totals.ranked.usd:,.2f}")
    cols[2].metric("Brawl", f"${totals.brawl.usd:,.2f}")
    cols[3].metric("Tournament", f"${totals.tournament.usd:,.2f}")
    owner_share = totals.overall.usd * (1 - scholar_pct / 100)
    scholar_share = totals.overall.usd * (scholar_pct / 100)
    st.caption(f"Owner: ${owner_share:,.2f} | Scholar: ${scholar_share:,.2f}")


def main():
    st.title("Scholar Rewards Tracker")
    st.caption("Splinterlands rewards, tournaments, and brawls with USD conversion.")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        usernames_raw = st.text_input("Usernames (comma separated)", value="lorkus,vorkus")
    with col2:
        scholar_pct = st.number_input("Scholar share (%)", min_value=0, max_value=100, value=50, step=5)
    with col3:
        refresh_clicked = st.button("Refresh now")

    if refresh_clicked:
        clear_caches()
        st.rerun()

    try:
        season = cached_season()
        prices = cached_prices()
    except Exception as exc:
        st.error(f"Failed to load base data: {exc}")
        return

    st.caption(f"SPS price: {_format_price(prices.get('sps'))} | DEC: {_format_price(prices.get('dec'))}")

    usernames = parse_usernames(usernames_raw)
    st.write(f"Season {season.id}: {season.starts.date()} \u2192 {season.ends.date()}")

    per_user_totals: List[tuple[str, AggregatedTotals]] = []
    reward_rows: List[RewardEntry] = []
    tournament_rows: List[TournamentResult] = []

    for username in usernames:
        with st.spinner(f"Fetching data for {username}..."):
            try:
                user_rewards = cached_rewards(username)
                user_tournaments = cached_tournaments(username)
            except Exception as exc:
                st.warning(f"Failed to fetch data for {username}: {exc}")
                continue

            reward_rows.extend(user_rewards)
            tournament_rows.extend(user_tournaments)

            try:
                totals = aggregate_totals(season, user_rewards, user_tournaments, prices)
                per_user_totals.append((username, totals))
            except Exception as exc:
                st.warning(f"Failed to aggregate data for {username}: {exc}")

    if not reward_rows and not tournament_rows:
        st.info("No data found yet. Try adding usernames.")
        return

    totals: AggregatedTotals = aggregate_totals(season, reward_rows, tournament_rows, prices)

    if per_user_totals:
        st.markdown("### Per-user totals")
        for i in range(0, len(per_user_totals), 2):
            cols = st.columns(2)
            for col, entry in zip(cols, per_user_totals[i : i + 2]):
                with col:
                    _render_user_summary(entry[0], entry[1], scholar_pct)
        table_rows = [
            {
                "User": username,
                "Overall (USD)": totals.overall.usd,
                "Ranked (USD)": totals.ranked.usd,
                "Brawl (USD)": totals.brawl.usd,
                "Tournament (USD)": totals.tournament.usd,
                "Scholar share (USD)": totals.overall.usd * (scholar_pct / 100),
                "Scholar share (SPS)": totals.overall.token_amounts.get("SPS", 0) * (scholar_pct / 100),
            }
            for username, totals in per_user_totals
        ]
        st.dataframe(
            table_rows,
            width="stretch",
            hide_index=True,
            column_config={
                "Overall (USD)": st.column_config.NumberColumn(format="%.2f"),
                "Ranked (USD)": st.column_config.NumberColumn(format="%.2f"),
                "Brawl (USD)": st.column_config.NumberColumn(format="%.2f"),
                "Tournament (USD)": st.column_config.NumberColumn(format="%.2f"),
                "Scholar share (USD)": st.column_config.NumberColumn(format="%.2f"),
                "Scholar share (SPS)": st.column_config.NumberColumn(format="%.2f"),
            },
        )

    st.markdown("### Rewards by source (all users, season)")
    source_rows = [
        {"Source": "Ranked", "USD (est)": totals.ranked.usd, "Tokens": _format_token_amounts_dict(totals.ranked.token_amounts, prices)},
        {"Source": "Brawl", "USD (est)": totals.brawl.usd, "Tokens": _format_token_amounts_dict(totals.brawl.token_amounts, prices)},
        {"Source": "Tournament", "USD (est)": totals.tournament.usd, "Tokens": _format_token_amounts_dict(totals.tournament.token_amounts, prices)},
        {"Source": "Entry fees (tracking)", "USD (est)": totals.entry_fees.usd, "Tokens": _format_token_amounts_dict(totals.entry_fees.token_amounts, prices)},
    ]
    st.dataframe(
        source_rows,
        width="stretch",
        hide_index=True,
        column_config={
            "USD (est)": st.column_config.NumberColumn(format="%.2f"),
        },
    )

    supabase_ready = get_supabase_client() is not None
    supabase_error = get_last_supabase_error()
    st.markdown("---")
    st.markdown("### Persistence")
    if supabase_ready:
        if st.button("Sync season snapshot to Supabase"):
            try:
                usernames_label = ",".join(usernames) if usernames else "unspecified"
                upsert_season_totals(season, usernames_label, totals)
                upsert_tournament_logs(tournament_rows, usernames_label)
                st.success("Synced to Supabase.")
            except Exception as exc:
                st.error(f"Failed to sync to Supabase: {exc}")
    else:
        msg = (
            "Set SUPABASE_URL and SUPABASE_SERVICE_KEY (or ANON KEY) in your environment or "
            ".streamlit/secrets.toml to enable persistence."
        )
        if supabase_error:
            msg += f" (Init error: {supabase_error})"
        st.info(msg)


if __name__ == "__main__":
    main()
