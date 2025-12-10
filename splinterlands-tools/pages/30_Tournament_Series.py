from __future__ import annotations

from datetime import datetime, date

import streamlit as st

from core.config import setup_page
from scholar_helper.services.storage import (
    fetch_tournament_events_supabase,
    fetch_tournament_results_supabase,
    fetch_tournament_ingest_organizers,
    fetch_series_configs,
    fetch_point_schemes,
    get_last_supabase_error,
)


setup_page("Tournament Series")


def _format_date(value: datetime | None) -> str:
    if not value:
        return "-"
    return value.strftime("%Y-%m-%d")


def _format_ruleset(allowed_cards: dict | None) -> str:
    if not isinstance(allowed_cards, dict):
        return "-"
    epoch = allowed_cards.get("epoch") or allowed_cards.get("type") or "Ruleset"
    ghost = allowed_cards.get("ghost")
    cards = allowed_cards.get("type") or "All"
    epoch_label = str(epoch).title()
    type_label = f"{epoch_label} {'Ghost' if ghost else 'Owned'}"
    cards_label = "All" if str(cards).lower() == "all" else str(cards).title()
    return f"Type: {type_label} - Cards: {cards_label}"


def _parse_date(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def _as_float(value):
    try:
        return float(value)
    except Exception:
        return None


def _render_scheme_rules(scheme: dict) -> list[dict]:
    rules = scheme.get("rules") or []
    rows = []
    mode = scheme.get("mode")
    base_points = scheme.get("base_points")
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        row: dict = {
            "Min": rule.get("min"),
            "Max": rule.get("max"),
        }
        if mode == "multiplier":
            row["Base"] = base_points
            row["Multiplier"] = rule.get("multiplier")
        else:
            row["Points"] = rule.get("points")
        rows.append(row)
    return rows


def render_page() -> None:
    st.title("Tournament Series")
    st.caption("Supabase-backed list of hosted tournaments with stored leaderboards.")

    organizers = fetch_tournament_ingest_organizers()
    selected_org = st.selectbox(
        "Organizer",
        options=organizers + ["(custom)"] if organizers else ["(custom)"],
        index=0,
    )
    custom_username = ""
    if selected_org == "(custom)":
        custom_username = st.text_input("Custom organizer username").strip()
    username = custom_username or (selected_org if selected_org != "(custom)" else "").strip()

    configs = fetch_series_configs(username) if username else []
    config_labels = ["(No saved config)"] + [cfg.get("name") or str(cfg.get("id")) for cfg in configs]
    selected_config_label = st.selectbox("Series config (optional)", options=config_labels, index=0)
    selected_config = None

    if not username:
        st.info("Enter an organizer username to view hosted tournaments.")
        return

    scheme_options = {
        "Balanced": "balanced",
        "Performance": "performance",
        "Participation": "participation",
    }

    col1, col2, col3 = st.columns(3)
    with col1:
        scheme_label = st.selectbox("Point scheme", options=list(scheme_options.keys()), index=0)
        scheme = scheme_options[scheme_label]
    with col2:
        since_date = st.date_input("Start date (optional)", value=None)
    with col3:
        until_date = st.date_input("End date (optional)", value=None)

    # Apply config overrides if selected.
    include_ids: list[str] = []
    exclude_ids: set[str] = set()
    if selected_config_label != "(No saved config)" and configs:
        selected_config = next(
            (c for c in configs if (c.get("name") or str(c.get("id"))) == selected_config_label),
            None,
        )
        if selected_config:
            scheme = selected_config.get("point_scheme") or scheme
            since_date = selected_config.get("include_after") or since_date
            until_date = selected_config.get("include_before") or until_date
            include_ids = selected_config.get("include_ids") or []
            exclude_ids = set(selected_config.get("exclude_ids") or [])

    limit = st.slider("Limit to last N events (0 = all after filters)", min_value=0, max_value=100, value=20)

    with st.spinner(f"Loading tournaments ingested for {username}..."):
        tournaments = fetch_tournament_events_supabase(
            username,
            since=_parse_date(since_date),
            until=_parse_date(until_date),
            limit=200,
        )
    if not tournaments:
        error = get_last_supabase_error()
        if error:
            st.error(f"Supabase query failed: {error}")
        else:
            st.info("No tournaments found for that organizer in Supabase. Ingest first, then refresh.")
        return

    if not tournaments:
        st.info("No tournaments found for that organizer.")
        return

    # Optional ruleset filter derived from available allowed_cards.
    ruleset_labels = sorted({(_format_ruleset(t.get("allowed_cards")) or "-") for t in tournaments})
    ruleset_labels = [label for label in ruleset_labels if label and label != "-"]
    ruleset_labels.insert(0, "All rulesets")
    selected_ruleset = st.selectbox("Ruleset filter (optional)", options=ruleset_labels, index=0)
    if selected_ruleset != "All rulesets":
        tournaments = [t for t in tournaments if _format_ruleset(t.get("allowed_cards")) == selected_ruleset]
        if not tournaments:
            st.info("No tournaments match that ruleset for the selected filters.")
            return

    # Filter by include/exclude ids from config.
    if include_ids:
        tournaments = [t for t in tournaments if t.get("tournament_id") in include_ids]
    if exclude_ids:
        tournaments = [t for t in tournaments if t.get("tournament_id") not in exclude_ids]

    # Trim to last N after filtering.
    if limit and len(tournaments) > limit:
        tournaments = tournaments[:limit]

    rows = []
    for t in tournaments:
        start_dt = _parse_date(t.get("start_date"))
        rows.append(
            {
                "Date": _format_date(start_dt),
                "Tournament": t.get("name") or t.get("tournament_id"),
                "Ruleset": _format_ruleset(t.get("allowed_cards")),
            }
        )

    st.dataframe(
        rows,
        hide_index=True,
        width="stretch",
        column_config={
            "Date": st.column_config.TextColumn(),
            "Tournament": st.column_config.TextColumn(),
            "Ruleset": st.column_config.TextColumn(),
            },
        )

    # Series leaderboard
    points_key = {
        "balanced": "points_balanced",
        "performance": "points_performance",
        "participation": "points_participation",
    }.get(scheme, "points_balanced")

    event_ids = [t.get("tournament_id") for t in tournaments if t.get("tournament_id")]

    with st.spinner("Computing series leaderboard..."):
        result_rows = fetch_tournament_results_supabase(
            tournament_ids=event_ids,
            organizer=username,
            since=_parse_date(since_date),
            until=_parse_date(until_date),
        )

    if result_rows:
        totals_map: dict[str, dict[str, object]] = {}
        for row in result_rows:
            player = str(row.get("player") or "").strip()
            if not player:
                continue
            pts = _as_float(row.get(points_key)) or 0
            finish = row.get("finish")
            agg = totals_map.setdefault(
                player,
                {"points": 0.0, "events": 0, "finishes": [], "podiums": 0},
            )
            agg["points"] += pts
            agg["events"] += 1
            if finish is not None:
                agg["finishes"].append(finish)
                if isinstance(finish, (int, float)) and 1 <= float(finish) <= 3:
                    agg["podiums"] += 1

        total_rows = []
        for player, agg in totals_map.items():
            finishes = [f for f in agg["finishes"] if f is not None]
            avg_finish = sum(finishes) / len(finishes) if finishes else None
            best_finish = min(finishes) if finishes else None
            total_rows.append(
                {
                    "Player": player,
                    "Points": agg["points"],
                    "Events": agg["events"],
                    "Avg Finish": avg_finish,
                    "Best": best_finish,
                    "Podiums": agg["podiums"],
                }
            )

        total_rows.sort(key=lambda r: r["Points"], reverse=True)
        ruleset_title = "Full"
        if selected_ruleset != "All rulesets":
            ruleset_title = selected_ruleset
            if ruleset_title.lower().startswith("type:"):
                ruleset_title = ruleset_title.replace("Type:", "").strip()
            ruleset_title = ruleset_title.split(" - ")[0].strip() or "Full"
        tournament_count = len(tournaments)
        tabs = st.tabs(["Leaderboard", "Point schemes"])
        with tabs[0]:
            st.subheader(
                f"{ruleset_title} Series Leaderboard hosted by {username} ({scheme_label} points) - aggregated over {tournament_count} tournaments"
            )
            st.dataframe(
                total_rows,
                hide_index=True,
                width="stretch",
                column_config={
                    "Player": st.column_config.TextColumn(),
                    "Points": st.column_config.NumberColumn(format="%.0f"),
                    "Events": st.column_config.NumberColumn(format="%d"),
                    "Avg Finish": st.column_config.NumberColumn(format="%.2f"),
                    "Best": st.column_config.NumberColumn(format="%d"),
                    "Podiums": st.column_config.NumberColumn(format="%d"),
                },
            )
        with tabs[1]:
            st.subheader("Point Schemes")
            schemes = fetch_point_schemes()
            if not schemes:
                st.info("No point schemes found in Supabase.")
            else:
                for scheme in schemes:
                    st.markdown(f"**{scheme.get('label') or scheme.get('slug')}** ({scheme.get('mode')})")
                    st.caption(
                        f"Base points: {scheme.get('base_points')}, DNP points: {scheme.get('dnp_points')}"
                    )
                    rows = _render_scheme_rules(scheme)
                    st.dataframe(
                        rows,
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "Min": st.column_config.NumberColumn(format="%d"),
                            "Max": st.column_config.NumberColumn(format="%d"),
                            "Base": st.column_config.NumberColumn(format="%.0f"),
                            "Multiplier": st.column_config.NumberColumn(format="%.2f"),
                            "Points": st.column_config.NumberColumn(format="%.0f"),
                        },
                    )
                    st.divider()
    else:
        st.info("No leaderboard rows found for the selected window.")

    labels = []
    for t in tournaments:
        start_dt = _parse_date(t.get("start_date"))
        labels.append(f"{_format_date(start_dt)} - {t.get('name') or t.get('tournament_id')}")
    if not labels:
        return

    selected_label = st.selectbox("View leaderboard", options=labels, index=0)

    selected_idx = labels.index(selected_label)
    selected = tournaments[selected_idx]
    tournament_id = selected.get("tournament_id") or selected.get("id")
    with st.spinner(f"Loading leaderboard for {selected.get('name') or tournament_id}..."):
        leaderboard = fetch_tournament_results_supabase(tournament_id)
    if leaderboard:
        st.dataframe(
            [
                {
                    "Finish": row.get("finish"),
                    "Player": row.get("player"),
                    "Points": _as_float(row.get(points_key)),
                    "Prizes": row.get("prize_text"),
                }
                for row in leaderboard
            ],
            hide_index=True,
            width="stretch",
            column_config={
                "Finish": st.column_config.NumberColumn(format="%d"),
                "Player": st.column_config.TextColumn(),
                "Points": st.column_config.NumberColumn(format="%.0f"),
                "Prizes": st.column_config.TextColumn(),
            },
        )
    else:
        st.info("No leaderboard entries found for that tournament.")


if __name__ == "__main__":
    render_page()
