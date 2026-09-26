"""
NIH RePORTER Award Data Fetcher
--------------------------------
Pulls all NIH awards for University of Colorado Denver / Anschutz Medical Campus
for federal fiscal years 2023, 2024, and 2025, then loads into a DuckDB database.

Usage:
  pip install requests duckdb
  python nih_awards_fetch.py
"""
from datetime import datetime
import argparse
import json
import time
import requests
import duckdb
from award_text import TEXT_API_FIELDS, upsert_records

# ── Config ────────────────────────────────────────────────────────────────────

API_URL      = "https://api.reporter.nih.gov/v2/projects/search"
DB_PATH      = "ucd_awards.duckdb"
FISCAL_YEARS = list(range(2001, datetime.now().year + 1))
PAGE_SIZE    = 500
INCLUDE_TEXT_FIELDS = False  # opt in with --include-text

# ── Helpers ───────────────────────────────────────────────────────────────────

def search_page(org_names: list, fiscal_years: list, offset: int) -> dict:
    payload = {
        "criteria": {
            "org_names":   org_names,
            "fiscal_years": fiscal_years,
        },
        "offset": offset,
        "limit":  PAGE_SIZE,
        "sort_field": "fiscal_year",
        "sort_order": "desc",
    }
    if not INCLUDE_TEXT_FIELDS:
        payload["exclude_fields"] = list(TEXT_API_FIELDS)
    resp = requests.post(API_URL, json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()


def flatten_record(r: dict) -> dict:
    flat = {}

    # Direct scalars
    for k in [
        "appl_id", "subproject_id", "fiscal_year", "project_num",
        "project_serial_num", "activity_code", "award_type", "award_amount",
        "award_notice_date", "budget_start", "budget_end",
        "project_start_date", "project_end_date",
        "cfda_code", "funding_mechanism", "direct_cost_amt", "indirect_cost_amt",
        "cong_dist", "arra_funded", "is_active", "is_new",
        "project_title", "project_detail_url", "abstract_text", "phr_text",
        "terms", "pref_terms", "spending_categories_desc", "agency_code",
        "covid_response", "contact_pi_name", "core_project_num", "date_added",
        "opportunity_number", "mechanism_code_dc",
    ]:
        flat[k] = r.get(k)

    # Organization (nested dict)
    org = r.get("organization") or {}
    flat["org_name"]    = org.get("org_name")
    flat["org_city"]    = org.get("city")
    flat["org_state"]   = org.get("org_state")
    flat["org_country"] = org.get("country")
    flat["org_duns"]    = org.get("org_duns")
    flat["org_uei"]     = org.get("uei")
    flat["dept_type"]   = org.get("dept_type")

    # Organization type
    ot = r.get("organization_type") or {}
    flat["org_type_name"] = ot.get("name")
    flat["org_type_code"] = ot.get("code")

    # Geo coordinates
    geo = r.get("geo_lat_lon") or {}
    flat["geo_lat"] = geo.get("lat")
    flat["geo_lon"] = geo.get("lon")

    # Agency IC admin
    aic = r.get("agency_ic_admin") or {}
    flat["agency_ic_admin_code"]   = aic.get("code")
    flat["agency_ic_admin_abbrev"] = aic.get("abbreviation")
    flat["agency_ic_admin_name"]   = aic.get("name")
    flat["agency_ic_fundings_json"] = json.dumps(r.get("agency_ic_fundings") or [])

    # Principal investigators
    pis = r.get("principal_investigators") or []
    flat["pi_names"]       = " | ".join(p.get("full_name", "") for p in pis)
    flat["pi_profile_ids"] = " | ".join(str(p.get("profile_id", "")) for p in pis)
    flat["pis_json"]       = json.dumps(pis)

    # Program officers
    pos = r.get("program_officers") or []
    flat["program_officers"] = " | ".join(
        f"{p.get('last_name','')}, {p.get('first_name','')}" for p in pos
    )

    # Study section
    fss = r.get("full_study_section") or {}
    flat["study_section_code"] = fss.get("srg_code")
    flat["study_section_name"] = fss.get("name")

    # Project num split
    pns = r.get("project_num_split") or {}
    flat["activity_code_split"] = pns.get("activity_code")
    flat["ic_code"]             = pns.get("ic_code")
    flat["serial_num"]          = pns.get("serial_num")
    flat["support_year"]        = pns.get("support_year")
    flat["suffix_code"]         = pns.get("suffix_code")
    flat["appl_type_code"]      = pns.get("appl_type_code")

    flat["spending_categories_json"] = json.dumps(r.get("spending_categories") or {})

    return flat


# ── DuckDB ────────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE IF NOT EXISTS ucd_awards (
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


def load_to_duckdb(records: list, db_path: str):
    con = duckdb.connect(db_path)
    con.execute(DDL)

    if not records:
        print("No records to load.")
        con.close()
        return

    upsert_records(con, "ucd_awards", records, flatten_record, INCLUDE_TEXT_FIELDS)

    count = con.execute("SELECT COUNT(*) FROM ucd_awards").fetchone()[0]
    con.close()
    print(f"\nLoaded. Total rows in ucd_awards: {count:,}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global INCLUDE_TEXT_FIELDS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-text", action="store_true", default=INCLUDE_TEXT_FIELDS,
                        help="Download abstracts, public-health text, terms and preferred terms.")
    INCLUDE_TEXT_FIELDS = parser.parse_args().include_text
    print("=" * 60)
    print("NIH RePORTER Award Fetcher — UCD / Anschutz")
    print(f"Fiscal years: {FISCAL_YEARS[0]}–{FISCAL_YEARS[-1]}")
    print("=" * 60)

    org_names = [
        "UNIVERSITY OF COLORADO DENVER",
        "UNIVERSITY OF COLORADO ANSCHUTZ MEDICAL CAMPUS",
    ]

    all_records = []

    for year in FISCAL_YEARS:
        print(f"\nFetching fiscal year {year}...")
        offset = 0
        year_records = []

        while True:
            print(f"  Fetching offset {offset}...", end=" ", flush=True)
            data    = search_page(org_names, [year], offset)
            total   = data.get("meta", {}).get("total", 0)
            results = data.get("results", [])

            if offset == 0:
                print(f"Total records: {total:,}")

            if not results:
                break

            year_records.extend(results)
            print(f"  Got {len(results)} (cumulative: {len(year_records):,})")

            offset += PAGE_SIZE
            if offset >= total or offset >= 14999:
                break
            time.sleep(0.5)

        print(f"  Year {year}: {len(year_records):,} records")
        all_records.extend(year_records)

    if not all_records:
        print("No records returned.")
        return

    print(f"\nLoading {len(all_records):,} records into {DB_PATH} ...")
    load_to_duckdb(all_records, DB_PATH)
    print(f"\nDone! Open '{DB_PATH}' in DBeaver.")


if __name__ == "__main__":
    main()
