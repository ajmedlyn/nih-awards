"""
NIH awards — refresh, then rebuild the normalized tables
--------------------------------------------------------
Step 1 (fetch):     runs nih_awards_national_incremental_2026_fetch.py.
                    If it fails (nonzero exit), stop here: the normalized
                    tables keep their last good version.
Step 2 (normalize): runs the Tables/ SQL in build order, all in one
                    transaction. If any script fails, every table rolls back.
Step 3 (check):     prints row counts and counts source dates TRY_CAST lost
                    (expected 0; a warning, not a failure).

Usage:
    python refresh_and_normalize.py                 # fetch + normalize (cloud copy: no text)
    python refresh_and_normalize.py --with-text     # also fetch abstracts/PHR and build award_text (work copy)
    python refresh_and_normalize.py --skip-fetch    # normalize only

Exit code: 0 if everything succeeded, 1 if any step failed.
"""
from datetime import datetime
from pathlib import Path
import argparse
import subprocess
import sys
import duckdb
from db_config import DB_PATH   # set NIH_AWARDS_DB to use another file

PROJECT_DIR  = Path(__file__).resolve().parent
FETCH_SCRIPT = PROJECT_DIR / "nih_awards_national_incremental_2026_fetch.py"
TABLES_DIR   = PROJECT_DIR / "Tables"

# Build order: later tables use IDs created by earlier ones (see table documentation.md).
BUILD_ORDER = [
    ("org table.sql",                "organizations"),
    ("ProjectTable.sql",             "projects"),
    ("AwardFactTable.sql",           "award_fact"),                    # uses organizations, projects
    ("award_investigators tbl.sql",  "Award_Investigators"),
    ("Investigators.sql",            "investigators"),                 # uses award_fact, Award_Investigators
    ("IC_FundingTable.sql",          "award_ic_funding"),
    ("SpendingCategories.sql",       "award_spending_categories"),
    ("SpendingCategoryLookup.sql",   "spending_categories"),
    ("MainProjectTitles.sql",        "project_titles_main_projects"),  # uses projects
]

# Local/work copy only (--with-text); the cloud copy skips it for space.
TEXT_BUILD = [
    ("AwardText.sql",                "award_text"),
]

DATE_COLUMNS = ["award_notice_date", "budget_start", "budget_end",
                "project_start_date", "project_end_date"]


def log(message: str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def run_fetch(with_text: bool) -> bool:
    command = [sys.executable, str(FETCH_SCRIPT)]
    if with_text:
        command.append("--include-text")
    log("STEP 1: fetch")
    result = subprocess.run(command, cwd=PROJECT_DIR)
    if result.returncode != 0:
        log(f"Fetch FAILED (exit code {result.returncode}). Normalized tables not rebuilt.")
        return False
    log("Fetch finished.")
    return True


def run_normalize(con, build: list) -> bool:
    log("STEP 2: normalize")
    con.execute("BEGIN TRANSACTION")
    for filename, table in build:
        log(f"  building {table}  ({filename})")
        try:
            con.execute((TABLES_DIR / filename).read_text())
        except Exception as e:
            con.execute("ROLLBACK")
            log(f"Normalize FAILED on {filename}: {e}")
            log("Rolled back. All normalized tables keep their previous version.")
            return False
    con.execute("COMMIT")
    log("Normalize finished.")
    return True


def run_checks(con, build: list):
    log("STEP 3: check")
    for _, table in build:
        n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        log(f"  {table:<30} {n:>12,} rows")
    for column in DATE_COLUMNS:
        lost = con.execute(f"""
            SELECT COUNT(*) FROM nih_awards_national
            WHERE {column} IS NOT NULL AND TRY_CAST({column} AS DATE) IS NULL
        """).fetchone()[0]
        flag = "" if lost == 0 else "   <-- WARNING: dates lost to TRY_CAST"
        log(f"  {column:<30} {lost:>12,} lost dates{flag}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Rebuild the normalized tables without fetching from NIH.")
    parser.add_argument("--with-text", action="store_true",
                        help="Fetch abstracts/PHR text and build award_text (local/work copy only).")
    parser.add_argument("--db", default=str(DB_PATH), help=argparse.SUPPRESS)  # for testing on a copy
    args = parser.parse_args()

    log(f"Database: {args.db}")
    if not args.skip_fetch and not run_fetch(args.with_text):
        return 1

    build = BUILD_ORDER + (TEXT_BUILD if args.with_text else [])

    con = duckdb.connect(args.db)
    try:
        if not run_normalize(con, build):
            return 1
        run_checks(con, build)
    finally:
        con.close()
    log("DONE.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
