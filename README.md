# nih-awards

NIH award data from the [NIH RePORTER API](https://api.reporter.nih.gov), loaded into DuckDB and explored through a Streamlit dashboard and SQL.

## What's here

| Path | Purpose |
|---|---|
| `nih_awards_national_fetch.py` | Historical pull of every NIH award, FY2000–FY2026, batched by state and fiscal year |
| `refresh_and_normalize.py` | Runs the incremental fetch, then rebuilds the normalized tables (stops if the fetch fails) |
| `nih_awards_national_incremental_2026_fetch.py` | Incremental refresh of the prior and current fiscal years (upsert by `appl_id`) |
| `db_config.py` | Which DuckDB file the scripts use (`NIH_AWARDS_DB`) |
| `award_text.py` | Shared upsert logic and the abstract / terms text fields |
| `Tables/` | SQL that builds the normalized schema from `nih_awards_national` |
| `table documentation.md` | Build order and rules for the normalized tables |
| `Home.py`, `app.py`, `pages/` | Streamlit dashboard (Funding Cliff, Pipeline, Institutes, Universities) |
| `duckdb scripts/`, `Practice SQL/` | Ad hoc analysis queries and SQL practice |
| `tests/` | Tests for the text upsert logic |

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Database file name

Scripts use `nih_awards.duckdb` in the project folder by default. To use a different file on a machine, set the `NIH_AWARDS_DB` environment variable (see `db_config.py`):

```bash
export NIH_AWARDS_DB=big_dawg.duckdb      # macOS/Linux: add to ~/.zshrc to keep it
```

```bat
setx NIH_AWARDS_DB big_dawg.duckdb        :: Windows: applies to new terminals
```

The SQL in `Tables/` uses plain table names, so it works with any file name.

## Refreshing the data

```bash
python refresh_and_normalize.py
```

This runs the incremental fetch, then rebuilds the normalized tables in `Tables/` in one transaction, then prints row counts and a date check. If the fetch fails (NIH down for 15 tries in a row), it stops before rebuilding. If any SQL script fails, every normalized table rolls back to its previous version. Use `--skip-fetch` to rebuild the tables only.

On the local/work copy, add `--with-text`: the fetch also downloads abstracts and public-health text, and the chain builds `award_text`. The cloud copy runs without it, so it stays text-free.

To run only the fetch:

```bash
python nih_awards_national_incremental_2026_fetch.py
```

Add `--include-text` to also refresh abstracts, public-health text and terms.

- Rows are upserted on `appl_id`: existing awards are updated, new ones inserted, nothing is deleted.
- Each fiscal year is fetched in batches: one per US state/territory, one each for intramural (`IM`), interagency (`IAA`) and contract (`NSRDC`) awards, which have no state, and one for foreign awards. Any batch over the API's 15,000-record cap stops the run instead of being cut off.
- Each run ends with a completeness check comparing the table's row count per fiscal year with NIH's total.
- The fiscal year follows NIH's calendar (it starts October 1). The script re-pulls last fiscal year too, because NIH backfills fields such as spending categories after the year closes.
- NIH asks for no more than 1 request per second; the script waits 1.1 seconds between requests. For large pulls, NIH also asks that you run between 9 PM and 5 AM Eastern.
- DuckDB allows one writer. Close Streamlit and any open DuckDB sessions first.

The normalized table build order is in `table documentation.md`.

## Running the dashboard

```bash
streamlit run Home.py
```

The dashboard pages read `nih_awards_slim.duckdb`, not the main database, so a refresh doesn't update the dashboard until the slim file is rebuilt.

## Data notes

- FY2026 spending categories were empty after the fiscal year closed. NIH fills them in over the following months; roughly 89% of awards in a completed year have them.
- `award_amount` covers the whole budget period, and totals here are awards that came through RePORTER, not NIH's full appropriation (which also includes intramural research and other lines).
