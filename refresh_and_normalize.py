"""
NIH awards — refresh, then rebuild the normalized tables
--------------------------------------------------------
Step 1 (fetch):     runs nih_awards_national_incremental_2026_fetch.py, which
                    stages pages in a local file and merges them into the
                    database in one transaction at the end.
                    If it fails, or its completeness check finds missing
                    awards, stop here: the normalized tables keep their
                    last good version.
Step 2 (normalize): runs the Tables/ SQL in build order, all in one
                    transaction, then checks that award_fact matches the
                    source row count and that no table has duplicate keys.
                    If a script or a check fails, every table rolls back.
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
import os
import subprocess
import sys
import duckdb
from db_config import DB_PATH, require_existing_db   # set NIH_AWARDS_DB to use another file

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

# Each table's key (its grain). A rebuild that produces duplicates is rolled back.
TABLE_KEYS = {
    "organizations":                "organization_id",
    "projects":                     "core_project_num",
    "award_fact":                   "ApplicationID",
    "Award_Investigators":          "ApplicationID, profile_id",
    "investigators":                "profile_id",
    "award_ic_funding":             "ApplicationID, IC_Code",
    "award_spending_categories":    "ApplicationID, Spending_Category_ID",
    "spending_categories":          "Spending_Category_ID",
    "project_titles_main_projects": "Project_ID, project_title",
    "award_text":                   "ApplicationID",
}

DATE_COLUMNS = ["award_notice_date", "budget_start", "budget_end",
                "project_start_date", "project_end_date"]


def log(message: str):
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def run_fetch(with_text: bool, db_path: str) -> bool:
    command = [sys.executable, str(FETCH_SCRIPT)]
    if with_text:
        command.append("--include-text")
    log("STEP 1: fetch")
    # The fetch picks its database from NIH_AWARDS_DB, so pass --db through.
    result = subprocess.run(command, cwd=PROJECT_DIR, env={**os.environ, "NIH_AWARDS_DB": db_path})
    if result.returncode == 2:   # EXIT_MISSING_AWARDS in the fetch script
        log("Fetch finished, but its completeness check found MISSING AWARDS. Normalized tables not rebuilt.")
        log("Run again to retry the fetch, or use --skip-fetch to rebuild from what was saved.")
        return False
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
            con.execute((TABLES_DIR / filename).read_text(encoding="utf-8"))
        except Exception as e:
            con.execute("ROLLBACK")
            log(f"Normalize FAILED on {filename}: {e}")
            log("Rolled back. All normalized tables keep their previous version.")
            return False
    problems = integrity_problems(con, build)
    if problems:
        con.execute("ROLLBACK")
        for problem in problems:
            log(f"Integrity check FAILED: {problem}")
        log("Rolled back. All normalized tables keep their previous version.")
        return False
    con.execute("COMMIT")
    log("Normalize finished (row count and key checks passed).")
    return True


def integrity_problems(con, build: list) -> list:
    """Check the freshly built tables before they are committed.
    Returns a list of problems; an empty list means all checks passed."""
    problems = []
    source, facts = con.execute(
        "SELECT (SELECT COUNT(*) FROM nih_awards_national), (SELECT COUNT(*) FROM award_fact)"
    ).fetchone()
    if source != facts:
        problems.append(f"award_fact has {facts:,} rows but nih_awards_national has {source:,}")
    for _, table in build:
        key = TABLE_KEYS.get(table)
        if key is None:
            continue
        duplicates = con.execute(
            f'SELECT COUNT(*) FROM (SELECT 1 FROM "{table}" GROUP BY {key} HAVING COUNT(*) > 1)'
        ).fetchone()[0]
        if duplicates:
            problems.append(f"{table} has {duplicates:,} duplicated keys ({key})")
    return problems


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
    check_award_text(con, rebuilt=any(table == "award_text" for _, table in build))


def check_award_text(con, rebuilt: bool):
    """Warn when award_text exists but this run did not rebuild it and it has fallen behind."""
    exists = con.execute(
        "SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = 'award_text'"
    ).fetchone()[0]
    if rebuilt or not exists:
        return
    behind = con.execute("""
        SELECT COUNT(*) FROM nih_awards_national nan
        WHERE (nan.abstract_text IS NOT NULL OR nan.phr_text IS NOT NULL)
          AND NOT EXISTS (SELECT 1 FROM award_text t WHERE t.ApplicationID = nan.appl_id)
    """).fetchone()[0]
    flag = "" if behind == 0 else "   <-- WARNING: award_text not rebuilt; rerun with --with-text"
    log(f"  {'award_text (not rebuilt)':<30} {behind:>12,} awards with text missing{flag}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Rebuild the normalized tables without fetching from NIH.")
    parser.add_argument("--with-text", action="store_true",
                        help="Fetch abstracts/PHR text and build award_text (local/work copy only).")
    parser.add_argument("--db", default=str(DB_PATH), help=argparse.SUPPRESS)  # for testing on a copy
    args = parser.parse_args()
    # Full path, so the fetch (which runs from the project folder) uses the same file.
    args.db = str(Path(args.db).resolve())

    log(f"Database: {args.db}")
    require_existing_db(args.db)
    if not args.skip_fetch and not run_fetch(args.with_text, args.db):
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
