from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, List

import streamlit as st
from dotenv import load_dotenv

from scholar_helper.models import AggregatedTotals, CategoryTotals, PriceQuotes, RewardEntry, SeasonWindow, TournamentResult
from scholar_helper.services.aggregation import aggregate_totals, filter_tournaments_for_season
from scholar_helper.services.api import (
    fetch_current_season,
    fetch_prices,
    fetch_tournaments,
    fetch_unclaimed_balance_history,
)
from scholar_helper.services.storage import (
    fetch_season_history,
    get_last_supabase_error,
    get_supabase_client,
    update_season_currency,
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


def _format_rewards_list(rewards: List[RewardEntry] | List[TournamentResult], prices) -> str:
    parts = []
    for reward in rewards:
        token = getattr(reward, "token", None) or getattr(reward, "token", None)
        amount = getattr(reward, "amount", None)
        if token is None or amount is None:
            continue
        usd = (prices.get(token) or 0) * amount
        parts.append(f"{amount:g} {token.upper()} (${usd:,.2f})")
    return "; ".join(parts) if parts else "-"


def _build_currency_options(per_user_totals: List[tuple[str, AggregatedTotals]]) -> List[str]:
    currencies = {"SPS", "USD", "ETH", "HIVE", "BTC", "DEC", "VOUCHER"}
    for _, totals in per_user_totals:
        tokens = totals.overall.token_amounts.keys()
        currencies.update(token.upper() for token in tokens if isinstance(token, str))
    base_order = ["SPS", "USD", "ETH", "HIVE", "BTC", "DEC", "VOUCHER"]
    extras = [token for token in sorted(currencies) if token not in base_order]
    ordered = [token for token in base_order if token in currencies]
    return ordered + extras


def _format_scholar_payout(
    currency: str,
    totals: AggregatedTotals,
    scholar_pct: float,
    prices: PriceQuotes,
    explicit_sps: float | None = None,
) -> str:
    currency_key = currency.upper()
    if explicit_sps is None:
        sps_amount = totals.overall.token_amounts.get("SPS", 0.0) * (scholar_pct / 100)
    else:
        sps_amount = explicit_sps
    sps_price = prices.get("SPS") or prices.get("sps") or 0
    usd_value = sps_amount * sps_price

    if currency_key == "USD":
        return f"${usd_value:,.2f}"
    if sps_amount == 0 or usd_value == 0:
        if currency_key == "SPS":
            return f"{sps_amount:,.2f} SPS (${usd_value:,.2f})"
        return f"0.00 {currency_key}"
    if currency_key == "SPS":
        return f"{sps_amount:,.2f} SPS (${usd_value:,.2f})"

    target_price = prices.get(currency_key) or prices.get(currency_key.lower())
    if not target_price:
        return f"-"
    converted = usd_value / target_price if target_price else 0.0
    return f"{converted:,.2f} {currency_key} (${usd_value:,.2f})"


def _safe_float(value: object | None, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (float, int)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _safe_int(value: object | None, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _try_parse_int(value: object | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _parse_token_amounts(payload: object | None) -> Dict[str, float]:
    if not payload:
        return {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception:
            return {}
    if not isinstance(payload, dict):
        return {}
    tokens: Dict[str, float] = {}
    for token, amount in payload.items():
        try:
            key = str(token).upper()
            tokens[key] = float(amount)
        except Exception:
            continue
    return tokens


def _category_totals_from_record(record: Dict[str, object], prefix: str) -> CategoryTotals:
    tokens = _parse_token_amounts(record.get(f"{prefix}_tokens"))
    usd_value = _safe_float(record.get(f"{prefix}_usd"))
    return CategoryTotals(token_amounts=tokens, usd=usd_value)


def _merge_token_amounts(*parts: Dict[str, float]) -> Dict[str, float]:
    merged: Dict[str, float] = defaultdict(float)
    for part in parts:
        for token, amount in part.items():
            merged[token.upper()] += amount
    return dict(merged)


def _aggregated_totals_from_record(record: Dict[str, object]) -> AggregatedTotals:
    ranked = _category_totals_from_record(record, "ranked")
    brawl = _category_totals_from_record(record, "brawl")
    tournament = _category_totals_from_record(record, "tournament")
    entry_fees = _category_totals_from_record(record, "entry_fees")
    overall_tokens = _merge_token_amounts(
        ranked.token_amounts,
        brawl.token_amounts,
        tournament.token_amounts,
        entry_fees.token_amounts,
    )
    overall_usd = _safe_float(record.get("overall_usd"))
    if not overall_usd:
        overall_usd = ranked.usd + brawl.usd + tournament.usd + entry_fees.usd
    overall = CategoryTotals(token_amounts=overall_tokens, usd=overall_usd)
    return AggregatedTotals(
        ranked=ranked,
        brawl=brawl,
        tournament=tournament,
        entry_fees=entry_fees,
        overall=overall,
    )


def _record_scholar_pct(record: Dict[str, object]) -> float:
    return _safe_float(record.get("scholar_pct"))


def _record_season_id(record: Dict[str, object]) -> int:
    return _safe_int(record.get("season_id"))


def _sum_rewards_sps(rewards) -> float:
    return sum(r.amount for r in rewards if getattr(r, "token", "").upper() == "SPS")


def _sum_rewards_usd(rewards, prices) -> float:
    total = 0.0
    for r in rewards:
        price = prices.get(r.token) or prices.get(r.token.lower()) or 0
        total += r.amount * price
    return total


def _get_finish_for_tournament(t: TournamentResult, username: str) -> str | int:
    if t.finish is not None:
        return t.finish
    detail = t.raw.get("detail") if isinstance(t.raw, dict) else None
    target = username.lower()
    # Try players list
    players = detail.get("players") if isinstance(detail, dict) else None
    if isinstance(players, list):
            for p in players:
                if not isinstance(p, dict):
                    continue
                if str(p.get("player", "")).lower() == target:
                    finish_value = _try_parse_int(p.get("finish"))
                    if finish_value is not None:
                        return finish_value
                    break
    # Try current_player block
    current_player = detail.get("current_player") if isinstance(detail, dict) else None
    if isinstance(current_player, dict) and str(current_player.get("player", "")).lower() == target:
        finish_value = _try_parse_int(current_player.get("finish"))
        if finish_value is not None:
            return finish_value
    return "-"


def _render_user_summary(username: str, totals: AggregatedTotals, scholar_pct: float) -> None:
    st.markdown(
        f"<div style='font-size:16px; font-weight:600; font-family:inherit;'>{username}</div>",
        unsafe_allow_html=True,
    )
    cols = st.columns(4)
    cols[0].metric("Overall", f"${totals.overall.usd:,.2f}")
    cols[1].metric("Ranked", f"${totals.ranked.usd:,.2f}")
    cols[2].metric("Brawl", f"${totals.brawl.usd:,.2f}")
    cols[3].metric("Tournament", f"${totals.tournament.usd:,.2f}")


def main():
    st.title("Scholar Rewards Tracker")
    st.caption("Splinterlands rewards, tournaments, and brawls with USD conversion.")

    try:
        season = cached_season()
        prices = cached_prices()
    except Exception as exc:
        st.error(f"Failed to load base data: {exc}")
        return

    price_tokens = ["USD", "SPS", "DEC", "ETH", "HIVE", "BTC", "VOUCHER"]
    price_rows = []
    for token in price_tokens:
        if token.upper() == "USD":
            display = "$1.00"
        else:
            price = prices.get(token.lower())
            display = _format_price(price) if price is not None else "-"
        price_rows.append({"Currency": token, "USD price": display})
    with st.sidebar:
        st.subheader("Prices")
        st.dataframe(
            price_rows,
            hide_index=True,
            column_config={
                "Currency": st.column_config.TextColumn(),
                "USD price": st.column_config.TextColumn(),
            },
        )
    st.write(f"Season {season.id}: {season.starts.date()} \u2192 {season.ends.date()}")

    tab_summary, tab_tournaments, tab_history = st.tabs(["Summary", "Tournaments", "Scholar history"])

    with tab_summary:
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

        usernames = parse_usernames(usernames_raw)

        per_user_totals: List[tuple[str, AggregatedTotals]] = []
        reward_rows: List[RewardEntry] = []
        tournament_rows: List[TournamentResult] = []
        user_tournaments_by_user: Dict[str, List[TournamentResult]] = {}
        currency_choices: Dict[int, str] = {}
        default_currency = "SPS"
        currency_options: List[str] = ["SPS"]

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
                user_tournaments_by_user[username] = user_tournaments

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

            currency_options = _build_currency_options(per_user_totals)
            st.markdown("#### Scholar payout currency per account")
            selector_columns_count = max(1, min(2, len(per_user_totals)))
            selector_columns = st.columns(selector_columns_count)
            default_currency_idx = currency_options.index("SPS") if "SPS" in currency_options else 0
            currency_choices: dict[int, str] = {}
            for idx, (username, _) in enumerate(per_user_totals):
                selection_column = selector_columns[idx % selector_columns_count]
                currency_choices[idx] = selection_column.selectbox(
                    f"{username} payout currency",
                    options=currency_options,
                    key=f"scholar_payout_currency_{idx}_{username}",
                    index=default_currency_idx,
                )

            st.markdown("#### Scholar + owner share table")
            default_currency = currency_options[default_currency_idx]
            table_rows = []
            for idx, (username, totals) in enumerate(per_user_totals):
                scholar_share_usd = totals.overall.usd * (scholar_pct / 100)
                owner_share_usd = totals.overall.usd - scholar_share_usd
                scholar_share_sps = totals.overall.token_amounts.get("SPS", 0) * (scholar_pct / 100)
                selected_currency = currency_choices.get(idx, default_currency)
                payout_display = _format_scholar_payout(selected_currency, totals, scholar_pct, prices)
                table_rows.append(
                    {
                        "User": username,
                        "Overall (USD)": totals.overall.usd,
                        "Ranked (USD)": totals.ranked.usd,
                        "Brawl (USD)": totals.brawl.usd,
                        "Tournament (USD)": totals.tournament.usd,
                        "Scholar share (USD)": scholar_share_usd,
                        "Owner share (USD)": owner_share_usd,
                        "Scholar share (SPS)": scholar_share_sps,
                        "Scholar payout": payout_display,
                    }
                )
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
                    "Owner share (USD)": st.column_config.NumberColumn(format="%.2f"),
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
            if st.button("Sync season snapshot to Supabase", key="sync_season_snapshot"):
                any_error = False
                for idx, (username, user_totals) in enumerate(per_user_totals):
                    currency = currency_choices.get(idx, default_currency)
                    user_tournaments = user_tournaments_by_user.get(username, [])
                    try:
                        upsert_season_totals(season, username, user_totals, scholar_pct, currency)
                        upsert_tournament_logs(user_tournaments, username)
                    except Exception as exc:
                        st.error(f"Failed to sync {username}: {exc}")
                        any_error = True
                        break
                if not any_error:
                    st.success("Synced to Supabase.")
        else:
            msg = (
                "Set SUPABASE_URL and SUPABASE_SERVICE_KEY (or ANON KEY) in your environment or "
                ".streamlit/secrets.toml to enable persistence."
            )
            if supabase_error:
                msg += f" (Init error: {supabase_error})"
            st.info(msg)

    with tab_tournaments:
        st.subheader("Current-season tournaments")
        tour_user = st.text_input("Username", value="lorkus", key="tournament_user")
        if st.button("Reload tournaments", key="reload_tournaments"):
            clear_caches()
            st.rerun()

        if not tour_user.strip():
            st.info("Enter a username to view tournaments.")
            return

        try:
            all_tournaments = cached_tournaments(tour_user.strip())
        except Exception as exc:
            st.error(f"Failed to fetch tournaments: {exc}")
            return

        season_tournaments = filter_tournaments_for_season(all_tournaments, season)
        if not season_tournaments:
            st.info("No tournaments found for this season.")
            return

        rows = []
        for t in season_tournaments:
            sps_amt = _sum_rewards_sps(t.rewards)
            usd_amt = _sum_rewards_usd(t.rewards, prices)
            rows.append(
                {
                    "Date": t.start_date.date() if t.start_date else None,
                    "Tournament": t.name,
                    "Finish": _get_finish_for_tournament(t, tour_user.strip()),
                    "Earnings (SPS)": sps_amt,
                    "Earnings (USD)": usd_amt,
                }
            )
        st.dataframe(
            rows,
            width="stretch",
            hide_index=True,
            column_config={
                "Date": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "Finish": st.column_config.TextColumn(),
                "Earnings (SPS)": st.column_config.NumberColumn(format="%.2f"),
                "Earnings (USD)": st.column_config.NumberColumn(format="%.2f"),
            },
        )

    with tab_history:
        st.subheader("Scholar history by season")
        history_username = st.text_input("Scholar username", value="", key="history_username")
        normalized_history_username = history_username.strip()
        feedback_key = (
            f"history_feedback_{normalized_history_username.lower()}" if normalized_history_username else None
        )
        if feedback_key:
            if feedback := st.session_state.pop(feedback_key, None):
                st.success(feedback)

        history_table_rows: List[Dict[str, object]] = []
        history_records_sorted: List[Dict[str, object]] = []
        history_currency_options: List[str] = []

        if not normalized_history_username:
            st.info("Enter a scholar username to view season-by-season history.")
        else:
            supabase_ready = get_supabase_client() is not None
            if not supabase_ready:
                msg = (
                    "Set SUPABASE_URL and a Supabase key in your environment or "
                    ".streamlit/secrets.toml to enable history."
                )
                if get_last_supabase_error():
                    msg += f" (Init error: {get_last_supabase_error()})"
                st.info(msg)
            else:
                history_records = fetch_season_history(normalized_history_username)
                fetch_error = get_last_supabase_error()
                if fetch_error and not history_records:
                    st.error(f"Failed to load history: {fetch_error}")
                elif not history_records:
                    st.info("No history records found for this scholar.")
                else:
                    history_records_sorted = sorted(history_records, key=_record_season_id, reverse=True)
                    totals_list = [_aggregated_totals_from_record(record) for record in history_records_sorted]
                    history_totals = [(normalized_history_username, totals) for totals in totals_list]
                    history_currency_options = _build_currency_options(history_totals)

                    for record, totals in zip(history_records_sorted, totals_list):
                        season_label = f"Season {_record_season_id(record)}"
                        season_start_str = record.get("season_start") or "-"
                        season_end_str = record.get("season_end") or "-"
                        scholar_pct = _record_scholar_pct(record)
                        scholar_share_usd = totals.overall.usd * (scholar_pct / 100)
                        owner_share_usd = totals.overall.usd - scholar_share_usd
                        payout_currency = str(record.get("payout_currency") or "SPS")
                        payout_override = None
                        if record.get("scholar_payout") is not None:
                            payout_override = _safe_float(record.get("scholar_payout"))
                        payout_display = _format_scholar_payout(
                            payout_currency, totals, scholar_pct, prices, explicit_sps=payout_override
                        )
                        history_table_rows.append(
                            {
                                "Season": season_label,
                                "Range": f"{season_start_str} → {season_end_str}",
                                "Scholar pct": f"{scholar_pct:.1f}%" if scholar_pct else "-",
                                "Ranked (USD)": totals.ranked.usd,
                                "Tournament (USD)": totals.tournament.usd,
                                "Brawl (USD)": totals.brawl.usd,
                                "Entry fees (USD)": totals.entry_fees.usd,
                                "Overall (USD)": totals.overall.usd,
                                "Scholar share (USD)": scholar_share_usd,
                                "Owner share (USD)": owner_share_usd,
                                "Scholar payout": payout_display,
                                "Currency": payout_currency,
                            }
                        )

        if history_table_rows:
            st.dataframe(
                history_table_rows,
                width="stretch",
                hide_index=True,
                column_config={
                    "Ranked (USD)": st.column_config.NumberColumn(format="%.2f"),
                    "Tournament (USD)": st.column_config.NumberColumn(format="%.2f"),
                    "Brawl (USD)": st.column_config.NumberColumn(format="%.2f"),
                    "Entry fees (USD)": st.column_config.NumberColumn(format="%.2f"),
                    "Overall (USD)": st.column_config.NumberColumn(format="%.2f"),
                    "Scholar share (USD)": st.column_config.NumberColumn(format="%.2f"),
                    "Owner share (USD)": st.column_config.NumberColumn(format="%.2f"),
                },
            )

            st.markdown("#### Update payout currency")
            for idx, record in enumerate(history_records_sorted[:2]):
                stored_currency = str(record.get("payout_currency") or "SPS")
                default_currency = stored_currency if stored_currency in history_currency_options else history_currency_options[0]
                selection_key = f"history_currency_{normalized_history_username.lower()}_{_record_season_id(record)}_{idx}"
                cols = st.columns([1.5, 1.5, 2, 1])
                cols[0].markdown(f"**Season {_record_season_id(record)}**")
                cols[1].markdown(f"{record.get('season_start') or '-'} → {record.get('season_end') or '-'}")
                selected_currency = cols[2].selectbox(
                    "Payout currency",
                    options=history_currency_options,
                    key=selection_key,
                    index=history_currency_options.index(default_currency),
                )
                if cols[3].button(
                    "Save currency",
                    key=f"history_save_{normalized_history_username.lower()}_{_record_season_id(record)}_{idx}",
                ):
                    if update_season_currency(normalized_history_username, _record_season_id(record), selected_currency):
                        if feedback_key:
                            st.session_state[feedback_key] = (
                                f"Scholar payout currency updated to {selected_currency} for season {_record_season_id(record)}."
                            )
                        st.experimental_rerun()  # type: ignore[attr-defined]
                    else:
                        st.error("Failed to update the payout currency; check your Supabase configuration.")


if __name__ == "__main__":
    main()
