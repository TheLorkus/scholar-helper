from __future__ import annotations

import os
from typing import Iterable, Optional

from dotenv import load_dotenv
from supabase import Client, create_client

from scholar_helper.models import AggregatedTotals, SeasonWindow, TournamentResult

SEASON_TABLE = "season_rewards"
TOURNAMENT_TABLE = "tournament_logs"

_client: Optional[Client] = None

load_dotenv()


def get_supabase_client() -> Optional[Client]:
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        return None

    try:
        _client = create_client(url, key)
        return _client
    except Exception:
        # Fail softly if the client cannot be created (e.g., incompatible deps in the runtime).
        return None


def upsert_season_totals(
    season: SeasonWindow, username: str, totals: AggregatedTotals, table: str = SEASON_TABLE
) -> None:
    client = get_supabase_client()
    if client is None:
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
    }
    client.table(table).upsert(payload).execute()


def upsert_tournament_logs(
    tournaments: Iterable[TournamentResult], username: str, table: str = TOURNAMENT_TABLE
) -> None:
    client = get_supabase_client()
    if client is None:
        return

    rows = []
    for t in tournaments:
        rows.append(
            {
                "username": username,
                "tournament_id": t.id,
                "name": t.name,
                "start_date": t.start_date.isoformat() if t.start_date else None,
                "entry_fee_token": t.entry_fee.token if t.entry_fee else None,
                "entry_fee_amount": t.entry_fee.amount if t.entry_fee else None,
                "rewards": [r.__dict__ for r in t.rewards],
                "raw": t.raw,
            }
        )
    if rows:
        client.table(table).upsert(rows).execute()
