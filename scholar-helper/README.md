# Scholar Rewards Tracker

Streamlit app to track Splinterlands account performance, split rewards with a scholar, and sync snapshots to Supabase.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Python version: see `runtime.txt` (3.11.14).

## Configuration

- Copy `.env.example` to `.env` and set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (or `SUPABASE_ANON_KEY`) to enable persistence.
- Default username: `lorkus` (edit in the UI).
- Upload historical JSON (`{"rewards": [...], "tournaments": [...]}`) to augment API data.

## Scheduled sync to Supabase

- CLI: `python -m scholar_helper.cli.sync_supabase --usernames lorkus,other_player`
- Runs the same fetch/aggregate logic and upserts to Supabase; needs `SUPABASE_URL` + key in env.
- To automate, point a cron/GitHub Action/runner at the CLI. Supabase Scheduled Functions can be used as a cron trigger; wrap this command in a containerized runner if you want it to live next to your Supabase project.

## Notes

- API fetches are cached for 5 minutes and can be manually refreshed.
- Entry fees are tracked but not subtracted from totals.
- Season boundaries come from the `/settings` endpoint (start = previous season end, end = current season end).
