from __future__ import annotations

import os
import logging
from typing import Dict, Iterable, Optional

from dotenv import load_dotenv
import requests
try:
    import streamlit as st
except Exception:  # Streamlit not available in pure CLI runs (e.g., tests)
    st = None

from scholar_helper.models import AggregatedTotals, SeasonWindow, TournamentResult

SEASON_TABLE = "season_rewards"
TOURNAMENT_TABLE = "tournament_logs"

logger = logging.getLogger(__name__)

_last_error: Optional[str] = None

load_dotenv()


def _get_supabase_credentials() -> Optional[tuple[str, str]]:
    """Return (url, key) using env first, then Streamlit secrets."""
    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )
    if (not url or not key) and st is not None:
        secrets = st.secrets
        url = url or secrets.get("SUPABASE_URL")
        key = (
            key
            or secrets.get("SUPABASE_SERVICE_ROLE_KEY")
            or secrets.get("SUPABASE_SERVICE_KEY")
            or secrets.get("SUPABASE_ANON_KEY")
        )
    if not url or not key:
        return None
    return url, key


def get_supabase_client() -> Optional[tuple[str, str]]:
    """
    Backwards-compatible helper used by the app code to check whether Supabase is configured.

    We return credentials instead of a Supabase client to avoid dependency conflicts on Streamlit
    Cloud. The upsert helpers below use the REST API directly via requests.
    """
    global _last_error
    creds = _get_supabase_credentials()
    if not creds:
        _last_error = "Missing SUPABASE_URL or key"
        return None
    _last_error = None
    return creds


def get_last_supabase_error() -> Optional[str]:
    return _last_error


def _postgrest_upsert(url: str, key: str, table: str, rows) -> None:
    global _last_error
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    resp = requests.post(f"{url}/rest/v1/{table}", json=rows, headers=headers, timeout=15)
    if resp.status_code >= 300:
        _last_error = f"Supabase upsert failed: {resp.status_code} {resp.text}"


def _build_auth_headers(key: str, content_type: str | None = None) -> Dict[str, str]:
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def upsert_season_totals(
    season: SeasonWindow,
    username: str,
    totals: AggregatedTotals,
    scholar_pct: float,
    payout_currency: str,
    table: str = SEASON_TABLE,
) -> None:
    creds = get_supabase_client()
    if creds is None:
        return

    payload = {
        "season_id": season.id,
        "season_start": season.starts.isoformat(),
        "season_end": season.ends.isoformat(),
        "username": username,
        "ranked_tokens": totals.ranked.token_amounts,
        "brawl_tokens": totals.brawl.token_amounts,
        "tournament_tokens": totals.tournament.token_amounts,
        "entry_fees_tokens": totals.entry_fees.token_amounts,
        "ranked_usd": totals.ranked.usd,
        "brawl_usd": totals.brawl.usd,
        "tournament_usd": totals.tournament.usd,
        "entry_fees_usd": totals.entry_fees.usd,
        "overall_usd": totals.overall.usd,
        "scholar_pct": scholar_pct,
        "payout_currency": payout_currency,
    }
    url, key = creds
    _postgrest_upsert(url, key, table, payload)


def upsert_tournament_logs(
    tournaments: Iterable[TournamentResult], username: str, table: str = TOURNAMENT_TABLE
) -> None:
    creds = get_supabase_client()
    if creds is None:
        return

    rows = []
    for t in tournaments:
        rows.append(
            {
                "username": username,
                "tournament_id": t.id,
                "name": t.name,
                "start_date": t.start_date.isoformat() if t.start_date else None,
                "finish": t.finish,
                "entry_fee_token": t.entry_fee.token if t.entry_fee else None,
                "entry_fee_amount": t.entry_fee.amount if t.entry_fee else None,
                "rewards": [r.__dict__ for r in t.rewards],
                "raw": t.raw,
            }
        )
    if rows:
        url, key = creds
        _postgrest_upsert(url, key, table, rows)


def fetch_season_history(username: str) -> list[Dict[str, object]]:
    creds = get_supabase_client()
    if creds is None:
        return []

    url, key = creds
    endpoint = (
        f"{url}/rest/v1/{SEASON_TABLE}?username=eq.{username}&order=season_id.desc"
    )
    logger.debug("Fetching season history: %s headers=apikey", endpoint)
    headers = _build_auth_headers(key)
    resp = requests.get(endpoint, headers=headers, timeout=15)
    if resp.status_code >= 300:
        global _last_error
        _last_error = (
            f"Supabase fetch failed: {resp.status_code} {resp.text[:2048]}"
        )
        logger.error("Supabase fetch failed: %s %s", resp.status_code, resp.text)
        return []
    data = resp.json() or []
    logger.debug("Fetched %d history rows for %s", len(data), username)
    if not isinstance(data, list):
        return []
    return data


def update_season_currency(username: str, season_id: int, currency: str) -> bool:
    creds = get_supabase_client()
    if creds is None:
        return False

    url, key = creds
    headers = _build_auth_headers(key, content_type="application/json")
    resp = requests.patch(
        f"{url}/rest/v1/{SEASON_TABLE}?username=eq.{username}&season_id=eq.{season_id}",
        json={"payout_currency": currency},
        headers=headers,
        timeout=15,
    )
    if resp.status_code >= 300:
        global _last_error
        _last_error = f"Supabase update failed: {resp.status_code} {resp.text}"
        return False
    return True
