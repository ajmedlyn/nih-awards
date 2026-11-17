"""
NIH RePORTER — National Award Incremental Refresh, FY2026+
----------------------------------------------------------
Refreshes NIH award data from FY2026 forward into the national DuckDB table,
using the same batching, field selection, flattening, and upsert rules as
nih_awards_national_fetch.py.

Strategy: batch by state/territory to stay under the API's 14,999-record
offset cap. Also fetches a catch-all batch for non-US / no-state records.

Rate limit: NIH asks for no more than 1 request/second. We use 1.1s delay.
Recommended: run on weekends or weekdays 9 PM – 5 AM EST.

Usage:
    python nih_awards_national_incremental_2026_fetch.py

Options (edit constants below):
    --include-text       — opt in to abstracts, public-health text and terms
    DB_PATH              — path to your DuckDB file
    RESUME               — set True to skip FY2026+ batches already refreshed
"""
from datetime import datetime
import argparse
import json
import time
import requests
import duckdb
from award_text import TEXT_API_FIELDS, upsert_records

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH           = "nih_awards.duckdb"   # same file, separate table
TABLE_NAME        = "nih_awards_national"
_today            = datetime.now()
CURRENT_FY        = _today.year + (1 if _today.month >= 10 else 0)   # NIH FY starts Oct 1
START_FISCAL_YEAR = CURRENT_FY - 1   # re-pull last FY: NIH backfills fields like spending categories
FISCAL_YEARS      = list(range(START_FISCAL_YEAR, CURRENT_FY + 1))
PAGE_SIZE         = 500
REQUEST_DELAY     = 1.1                   # seconds between requests (NIH policy)
MAX_RETRIES       = 15                    # give up on a page after this many failed requests
INCLUDE_TEXT_FIELDS = False              # opt in with --include-text
RESUME            = False                 # False = refresh FY2026+ batches each run

API_URL = "https://api.reporter.nih.gov/v2/projects/search"

# All US states + DC + territories
US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY",
    "DC","PR","GU","VI","AS","MP",
]

BASE_FIELDS = [
    "ApplId","SubprojectId","FiscalYear","Organization","ProjectNum",
    "ProjectNumSplit","ProjectTitle","ActivityCode","AwardType","AwardAmount",
    "AwardNoticeDate","BudgetStart","BudgetEnd","ProjectStartDate","ProjectEndDate",
    "CfdaCode","FundingMechanism","DirectCostAmt","IndirectCostAmt",
    "AgencyIcAdmin","AgencyIcFundings","CongDist","PrincipalInvestigators",
    "ContactPiName","ProgramOfficers","ArraFunded","IsActive",
    "IsNew","ProjectDetailUrl","CoreProjectNum","DateAdded","OpportunityNumber",
    "MechanismCodeDc","FullStudySection","OrganizationType","GeoLatLon",
    "CovidResponse","AgencyCode","SpendingCategoriesDesc","SpendingCategories",
]

TEXT_FIELDS = list(TEXT_API_FIELDS)

INCLUDE_FIELDS = BASE_FIELDS + (TEXT_FIELDS if INCLUDE_TEXT_FIELDS else [])

# ── DDL ───────────────────────────────────────────────────────────────────────

DDL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    appl_id                  BIGINT PRIMARY KEY,
    subproject_id            VARCHAR,
    fiscal_year              INTEGER,
    project_num              VARCHAR,
    project_serial_num       VARCHAR,
    core_project_num         VARCHAR,
    activity_code            VARCHAR,
    activity_code_split      VARCHAR,
    ic_code                  VARCHAR,
    serial_num               VARCHAR,
    support_year             VARCHAR,
    suffix_code              VARCHAR,
    appl_type_code           VARCHAR,
    award_type               VARCHAR,
    mechanism_code_dc        VARCHAR,
    award_amount             BIGINT,
    direct_cost_amt          BIGINT,
    indirect_cost_amt        BIGINT,
    award_notice_date        VARCHAR,
    budget_start             VARCHAR,
    budget_end               VARCHAR,
    project_start_date       VARCHAR,
    project_end_date         VARCHAR,
    cfda_code                VARCHAR,
    funding_mechanism        VARCHAR,
    opportunity_number       VARCHAR,
    cong_dist                VARCHAR,
    arra_funded              VARCHAR,
    covid_response           VARCHAR,
    agency_code              VARCHAR,
    is_active                BOOLEAN,
    is_new                   BOOLEAN,
    agency_ic_admin_code     VARCHAR,
    agency_ic_admin_abbrev   VARCHAR,
    agency_ic_admin_name     VARCHAR,
    agency_ic_fundings_json  VARCHAR,
    org_name                 VARCHAR,
    org_city                 VARCHAR,
    org_state                VARCHAR,
    org_country              VARCHAR,
    org_duns                 VARCHAR,
    org_uei                  VARCHAR,
    dept_type                VARCHAR,
    org_type_name            VARCHAR,
    org_type_code            VARCHAR,
    geo_lat                  DOUBLE,
    geo_lon                  DOUBLE,
    contact_pi_name          VARCHAR,
    pi_names                 VARCHAR,
    pi_profile_ids           VARCHAR,
    pis_json                 VARCHAR,
    program_officers         VARCHAR,
    study_section_code       VARCHAR,
    study_section_name       VARCHAR,
    project_title            VARCHAR,
    abstract_text            VARCHAR,
    phr_text                 VARCHAR,
    terms                    VARCHAR,
    pref_terms               VARCHAR,
    spending_categories_desc VARCHAR,
    spending_categories_json VARCHAR,
    project_detail_url       VARCHAR,
    date_added               VARCHAR
);
"""

PROGRESS_DDL = """
CREATE TABLE IF NOT EXISTS _fetch_progress (
    batch_key   VARCHAR PRIMARY KEY,
    total       INTEGER,
    fetched     INTEGER,
    completed   BOOLEAN,
    updated_at  TIMESTAMP DEFAULT current_timestamp
);
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def flatten_record(r: dict) -> dict:
    flat = {}

    for k in [
        "appl_id","subproject_id","fiscal_year","project_num",
        "project_serial_num","activity_code","award_type","award_amount",
        "award_notice_date","budget_start","budget_end",
        "project_start_date","project_end_date",
        "cfda_code","funding_mechanism","direct_cost_amt","indirect_cost_amt",
        "cong_dist","arra_funded","is_active","is_new",
        "project_title","project_detail_url","abstract_text","phr_text",
        "terms","pref_terms","spending_categories_desc","agency_code",
        "covid_response","contact_pi_name","core_project_num","date_added",
        "opportunity_number","mechanism_code_dc",
    ]:
        flat[k] = r.get(k)

    org = r.get("organization") or {}
    flat["org_name"]    = org.get("org_name")
    flat["org_city"]    = org.get("city")
    flat["org_state"]   = org.get("org_state")
    flat["org_country"] = org.get("country")
    flat["org_duns"]    = org.get("org_duns")
    flat["org_uei"]     = org.get("uei")
    flat["dept_type"]   = org.get("dept_type")

    ot = r.get("organization_type") or {}
    flat["org_type_name"] = ot.get("name")
    flat["org_type_code"] = ot.get("code")

    geo = r.get("geo_lat_lon") or {}
    flat["geo_lat"] = geo.get("lat")
    flat["geo_lon"] = geo.get("lon")

    aic = r.get("agency_ic_admin") or {}
    flat["agency_ic_admin_code"]    = aic.get("code")
    flat["agency_ic_admin_abbrev"]  = aic.get("abbreviation")
    flat["agency_ic_admin_name"]    = aic.get("name")
    flat["agency_ic_fundings_json"] = json.dumps(r.get("agency_ic_fundings") or [])

    pis = r.get("principal_investigators") or []
    flat["pi_names"]       = " | ".join(p.get("full_name","") for p in pis)
    flat["pi_profile_ids"] = " | ".join(str(p.get("profile_id","")) for p in pis)
    flat["pis_json"]       = json.dumps(pis)

    pos = r.get("program_officers") or []
    flat["program_officers"] = " | ".join(
        f"{p.get('last_name','')}, {p.get('first_name','')}" for p in pos
    )

    fss = r.get("full_study_section") or {}
    flat["study_section_code"] = fss.get("srg_code")
    flat["study_section_name"] = fss.get("name")

    pns = r.get("project_num_split") or {}
    flat["activity_code_split"] = pns.get("activity_code")
    flat["ic_code"]             = pns.get("ic_code")
    flat["serial_num"]          = pns.get("serial_num")
    flat["support_year"]        = pns.get("support_year")
    flat["suffix_code"]         = pns.get("suffix_code")
    flat["appl_type_code"]           = pns.get("appl_type_code")
    flat["spending_categories_json"] = json.dumps(r.get("spending_categories") or {})

    return flat


def insert_records(con, records: list[dict]):
    upsert_records(con, TABLE_NAME, records, flatten_record, INCLUDE_TEXT_FIELDS)


def batch_key(state_or_tag: str, fy: int) -> str:
    return f"{state_or_tag}_{fy}"


def already_done(con, key: str) -> bool:
    row = con.execute(
        "SELECT completed FROM _fetch_progress WHERE batch_key = ?", [key]
    ).fetchone()
    return bool(row and row[0])


def mark_progress(con, key: str, total: int, fetched: int, completed: bool):
    con.execute("""
        INSERT OR REPLACE INTO _fetch_progress (batch_key, total, fetched, completed, updated_at)
        VALUES (?, ?, ?, ?, current_timestamp)
    """, [key, total, fetched, completed])


def clear_refresh_progress(con):
    """Let incremental runs refresh FY2026+ batches even if a prior run completed."""
    if RESUME:
        return

    keys = [batch_key(state, fy) for fy in FISCAL_YEARS for state in US_STATES]
    keys += [batch_key("INTL", fy) for fy in FISCAL_YEARS]
    con.executemany("DELETE FROM _fetch_progress WHERE batch_key = ?", [(key,) for key in keys])


# ── Fetch one batch (state + FY) ──────────────────────────────────────────────

def fetch_batch(con, state_or_none: str | None, fy: int, label: str):
    key = batch_key(label, fy)

    if RESUME and already_done(con, key):
        print(f"  [{label} FY{fy}] already complete — skipping")
        return

    criteria: dict = {"fiscal_years": [fy]}
    if state_or_none:
        criteria["org_states"] = [state_or_none]
    else:
        # Catch-all: non-US awards (no state filter, exclude US states)
        # NIH doesn't have a "not in" filter, so we use org_countries workaround
        # — just query with no state filter and deduplicate via PRIMARY KEY
        pass

    offset      = 0
    total_seen  = 0
    page_count  = 0
    failures    = 0

    while True:
        payload = {
            "criteria":       criteria,
            "include_fields": INCLUDE_FIELDS,
            "offset":         offset,
            "limit":          PAGE_SIZE,
        }

        try:
            resp = requests.post(API_URL, json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            failures += 1
            if failures >= MAX_RETRIES:
                # Fail loudly: a nonzero exit stops refresh_and_normalize.py
                # before it rebuilds tables from a half-refreshed source.
                raise RuntimeError(
                    f"Giving up on [{label} FY{fy}] offset {offset} after {failures} tries"
                ) from e
            print(f"  ERROR on [{label} FY{fy}] offset {offset}: {e} — retry {failures}/{MAX_RETRIES} in 5s")
            time.sleep(5)
            continue
        failures = 0

        total     = data.get("meta", {}).get("total", 0)
        results   = data.get("results", [])
        page_count += 1

        if offset == 0 and total > 0:
            print(f"  [{label} FY{fy}] total: {total:,}", end="", flush=True)

        if not results:
            break

        insert_records(con, results)
        total_seen += len(results)

        print(f"  +{len(results)}", end="", flush=True)

        offset += PAGE_SIZE
        if offset >= total or offset >= 14999:
            break

        time.sleep(REQUEST_DELAY)

    print()  # newline after progress dots
    mark_progress(con, key, total_seen, total_seen, True)
    time.sleep(REQUEST_DELAY)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global INCLUDE_TEXT_FIELDS, INCLUDE_FIELDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-text", action="store_true", default=INCLUDE_TEXT_FIELDS,
                        help="Download abstracts, public-health text, terms and preferred terms.")
    args = parser.parse_args()
    INCLUDE_TEXT_FIELDS = args.include_text
    INCLUDE_FIELDS = BASE_FIELDS + (TEXT_FIELDS if INCLUDE_TEXT_FIELDS else [])
    print("=" * 65)
    print("NIH RePORTER — National Award Fetcher")
    print(f"Table: {TABLE_NAME}  |  DB: {DB_PATH}")
    print(f"Fiscal years: {FISCAL_YEARS}  |  Text fields: {INCLUDE_TEXT_FIELDS}")
    print(f"Incremental refresh from FY{START_FISCAL_YEAR}; resume mode: {RESUME}")
    print("=" * 65)

    con = duckdb.connect(DB_PATH)
    con.execute(DDL)
    con.execute(PROGRESS_DDL)
    clear_refresh_progress(con)

    total_batches = len(US_STATES) * len(FISCAL_YEARS) + len(FISCAL_YEARS)
    done_batches  = 0

    for fy in FISCAL_YEARS:
        # US states + territories
        for state in US_STATES:
            done_batches += 1
            pct = 100 * done_batches / total_batches
            print(f"\n[{done_batches}/{total_batches} | {pct:.0f}%] State={state} FY={fy}")
            fetch_batch(con, state, fy, state)

        # International / no-state catch-all
        # (will upsert — duplicates handled by PRIMARY KEY)
        done_batches += 1
        print(f"\n[{done_batches}/{total_batches}] International catch-all FY={fy}")
        fetch_batch(con, None, fy, "INTL")

    row_count = con.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
    fy_breakdown = con.execute(f"""
        SELECT fiscal_year, COUNT(*) as n, SUM(award_amount) as total_cost
        FROM {TABLE_NAME}
        GROUP BY fiscal_year ORDER BY fiscal_year
    """).fetchall()

    print("\n" + "=" * 65)
    print(f"DONE. Total rows in {TABLE_NAME}: {row_count:,}")
    for fy, n, tc in fy_breakdown:
        print(f"  FY{fy}: {n:,} awards  |  ${tc:,.0f} total cost")
    print(f"\nOpen {DB_PATH} in DBeaver.")
    con.close()


if __name__ == "__main__":
    main()
