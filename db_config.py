"""Where the main DuckDB file lives.

Defaults to nih_awards.duckdb in the project folder. To use a different file on
a machine, set the NIH_AWARDS_DB environment variable to a file name (kept in the
project folder) or a full path, e.g. NIH_AWARDS_DB=big_dawg.duckdb.
"""
import os
from pathlib import Path

import duckdb

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH     = PROJECT_DIR / os.environ.get("NIH_AWARDS_DB", "nih_awards.duckdb")

# A full history is about 2.1M rows. Far fewer means the wrong file: a fresh
# folder from a ZIP download, or NIH_AWARDS_DB unset or mistyped.
MIN_ROWS = 1_000_000


def require_existing_db(path=DB_PATH, min_rows=MIN_ROWS):
    """Stop (exit code 1) rather than refresh a missing or near-empty database.

    Without this, DuckDB silently creates a new empty file and the refresh
    "succeeds" with two fiscal years of data. Only the full-history fetch
    (nih_awards_national_fetch.py) should ever create a database.
    """
    path = Path(path)
    if not path.is_file():
        raise SystemExit(
            f"Database not found: {path}\n"
            f"Check that you are in the project folder that holds it, and that NIH_AWARDS_DB "
            f"is set (currently {os.environ.get('NIH_AWARDS_DB', 'unset')!r}). "
            f"To build a new database from scratch, run nih_awards_national_fetch.py."
        )
    con = duckdb.connect(str(path), read_only=True)
    try:
        rows = con.execute("SELECT COUNT(*) FROM nih_awards_national").fetchone()[0]
    except duckdb.CatalogException:
        rows = 0
    finally:
        con.close()
    if rows < min_rows:
        raise SystemExit(
            f"{path} has only {rows:,} rows in nih_awards_national (expected at least {min_rows:,}). "
            f"This looks like the wrong database; not refreshing it."
        )
