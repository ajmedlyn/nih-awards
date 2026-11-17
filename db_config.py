"""Where the main DuckDB file lives.

Defaults to nih_awards.duckdb in the project folder. To use a different file on
a machine, set the NIH_AWARDS_DB environment variable to a file name (kept in the
project folder) or a full path, e.g. NIH_AWARDS_DB=big_dawg.duckdb.
"""
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH     = PROJECT_DIR / os.environ.get("NIH_AWARDS_DB", "nih_awards.duckdb")
