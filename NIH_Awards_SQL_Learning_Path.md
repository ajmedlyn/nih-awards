# NIH Awards Normalization and SQL Learning Path

Printable working guide for finishing the `nih_awards` normalized DuckDB model while keeping SQL skills sharp.

Prepared from the local DuckDB instance on 2026-06-18.

---

## 1. Current Database Snapshot

Main database:

```text
nih_awards.duckdb   18 GB
```

Flight-friendly database:

```text
nih_awards_slim.duckdb   33 MB
```

Connect:

```bash
duckdb nih_awards.duckdb
duckdb nih_awards_slim.duckdb
```

Useful shell commands:

```sql
.tables
DESCRIBE award_fact;
DESCRIBE nih_awards_national;
SELECT * FROM duckdb_tables() WHERE schema_name = 'main';
```

### Main Tables

| Table | Approx rows | Current purpose |
|---|---:|---|
| `nih_awards_national` | 1,936,045 | Raw flattened NIH award source table |
| `award_fact` | 1,936,045 | One row per award/application |
| `organizations` | 18,420 | Organization dimension candidate |
| `projects` | 407,356 | Project dimension candidate keyed by `core_project_num` |
| `investigators` | 211,289 | Investigator dimension candidate keyed by `profile_id` |
| `Award_Investigators` | 2,180,014 | Award-to-investigator bridge |
| `nih_institutes` | 87 | NIH institute/admin IC dimension candidate |
| `project_titles_main_projects` | 478,440 | Project-title history/variant bridge |
| `ucd_awards` | 19,416 | UC Davis award subset |
| `_fetch_progress` | 1,539 | Fetch bookkeeping |

### Current Quality Findings

These findings should become tests.

| Check | Current result | What it means |
|---|---:|---|
| Raw rows | 1,936,045 | Baseline source count |
| `award_fact` rows | 1,936,045 | Fact table currently preserves raw award grain |
| Duplicate `award_fact.ApplicationID` rows | 0 | Good primary-key candidate |
| Null `award_fact.ApplicationID` | 0 | Good |
| Null `award_fact.ORG_ID` | 560 | Decide whether to allow null or create an unknown org row |
| Organization IDs duplicated | 0 | Good surrogate key uniqueness |
| `award_fact` org orphans | 0 | Existing non-null org links resolve |
| `projects` duplicate `Project_ID` rows | 0 | Good |
| `projects` duplicate `core_project_num` rows | 0 | Good |
| Raw rows missing `core_project_num` | 11 | Need null-handling rule |
| Raw `core_project_num` values not in `projects` | 21 | Rebuild or refresh project dimension |
| `investigators` duplicate `profile_id` rows | 0 | Good |
| Investigators likely affected by `NULLS FIRST` display-name ranking | 28,720 | Current script conflicts with documentation; use `NULLS LAST` |
| Duplicate award/profile rows in `Award_Investigators` | 432 | Bridge table needs dedupe rule |
| Award-investigator profile orphans | 0 | Good |
| Award-investigator application orphans | 0 | Good |
| Award fact rows without investigators | 2,942 | Need rule: expected source gaps vs data issue |
| Awards in bridge with zero contact PI | 2 | Investigate |
| Date strings that fail `TRY_CAST(... AS DATE)` | 0 | Convert date text to typed `DATE` columns |
| `award_fact.IC_Code` values missing from `nih_institutes` | 0 | Good |

---

## 2. Target Normalized Model

Keep the model simple and explicit. The goal is not to normalize everything into dust. The goal is to make grain, identity, and joins obvious.

### Recommended Core Tables

| Target table | Grain | Key |
|---|---|---|
| `fact_award` | One row per NIH application/award record | `ApplicationID` |
| `dim_organization` | One row per stable org identity | `organization_id` |
| `dim_project` | One row per `core_project_num` | `Project_ID` |
| `dim_institute` | One row per IC/admin institute code | `agency_ic_admin_code` |
| `dim_investigator` | One row per NIH PI `profile_id` | `profile_id` |
| `bridge_award_investigator` | One row per application plus investigator | `ApplicationID`, `profile_id` |
| `bridge_project_title` | One row per project plus observed title | `Project_ID`, normalized title |

### Possible Later Tables

| Table | Why it might help |
|---|---|
| `dim_activity` | Activity codes such as R01, U01, K awards |
| `dim_award_type` | Award type descriptions and grouping |
| `dim_org_type` | Organization type code/name cleanup |
| `dim_study_section` | Review study section code/name |
| `bridge_award_spending_category` | If `spending_categories_json` becomes analytically important |
| `bridge_award_program_officer` | If program officers become a repeated entity |

### Fact Table Columns To Prefer

The fact should hold keys, measures, and event dates.

Good fact columns:

```text
ApplicationID
organization_id
Project_ID
agency_ic_admin_code
Federal_Fiscal_Year
activity_code
appl_type_code
support_year
suffix_code
award_notice_date
budget_start
budget_end
project_start_date
project_end_date
direct_cost_amt
indirect_cost_amt
award_amount
```

Columns that probably belong outside the fact:

```text
org_name
org_state
org_duns
agency_ic_admin_name
project_title
pi_names
pis_json
abstract_text
terms
spending_categories_json
```

---

## 3. Project Completion Roadmap

Use this as the master checklist.

### Phase 1: Freeze Definitions

- [ ] Write down the grain of every normalized table.
- [ ] Decide naming conventions: either snake case everywhere or keep existing mixed case. Prefer snake case for new work.
- [ ] Decide whether target tables replace current names or live beside them as `dim_*`, `fact_*`, and `bridge_*`.
- [ ] Create a `docs/data_dictionary.md` or expand `table documentation.md`.
- [ ] Add a short ERD to the docs.

Key decision:

```text
Do we preserve dashboard compatibility by keeping existing table names/views?
Recommended: create new normalized tables, then compatibility views if the Streamlit app expects old names.
```

### Phase 2: Rebuild Dimensions From Raw

- [ ] Rebuild `dim_institute` from distinct admin IC fields.
- [ ] Rebuild `dim_project` from all current raw rows, including the 21 missing `core_project_num` values found in the audit.
- [ ] Decide how to handle 11 raw rows with null `core_project_num`.
- [ ] Rebuild `dim_organization` and decide whether to include `org_city`, `org_country`, `org_uei`, `org_type_code`, and `org_type_name`.
- [ ] Rebuild `dim_investigator` using the documented display-name rule.
- [ ] Fix investigator display-name ordering so null `award_notice_date` values rank after real dates.
- [ ] Convert valid date strings into actual `DATE` columns.

Project dimension note:

The current `projects` table has 407,356 rows, but 21 non-null `core_project_num` values in raw data are not represented. That suggests the dimension was built before a later fetch or with a filter that now needs revisiting.

Investigator dimension note:

`table documentation.md` says null award dates should rank after dated observations. The current `Tables/Investigators.sql` uses `af.award_notice_date DESC NULLS FIRST`, which selects null-dated observations ahead of dated ones. The audit found 28,720 investigator profiles where the selected row is null-dated even though that profile also has a dated award. Use `DESC NULLS LAST` when rebuilding the investigator dimension.

### Phase 3: Rebuild Bridges

- [ ] Rebuild `bridge_award_investigator` from `pis_json`.
- [ ] Store `is_contact_pi` as `BOOLEAN`, not text.
- [ ] Deduplicate `(ApplicationID, profile_id)`.
- [ ] Investigate the current 432 duplicate application/profile rows.
- [ ] Investigate the 2 awards in the bridge with zero contact PI.
- [ ] Decide how to document 2,942 awards with no investigator rows.
- [ ] Rebuild `bridge_project_title` from `project_title`, `Project_ID`, and a normalized title key.

Useful dedupe shape:

```sql
CREATE OR REPLACE TABLE bridge_award_investigator AS
WITH exploded AS (
    SELECT
        nan.appl_id AS ApplicationID,
        json_extract_string(pi.value, '$.profile_id') AS profile_id,
        upper(json_extract_string(pi.value, '$.last_name')) AS last_name,
        upper(json_extract_string(pi.value, '$.first_name')) AS first_name,
        json_extract_string(pi.value, '$.is_contact_pi')::BOOLEAN AS is_contact_pi,
        row_number() OVER (
            PARTITION BY
                nan.appl_id,
                json_extract_string(pi.value, '$.profile_id')
            ORDER BY
                json_extract_string(pi.value, '$.is_contact_pi')::BOOLEAN DESC,
                pi.key
        ) AS rn
    FROM nih_awards_national nan,
         json_each(nan.pis_json) AS pi
    WHERE json_extract_string(pi.value, '$.profile_id') IS NOT NULL
)
SELECT
    ApplicationID,
    profile_id,
    last_name,
    first_name,
    concat_ws(', ', last_name, first_name) AS full_name,
    is_contact_pi
FROM exploded
WHERE rn = 1;
```

### Phase 4: Rebuild `fact_award`

- [ ] Include `Project_ID`, not just `project_num`.
- [ ] Include `organization_id`.
- [ ] Include `agency_ic_admin_code`.
- [ ] Keep additive measures: direct, indirect, total/award amount.
- [ ] Keep typed dates.
- [ ] Keep raw identifying strings only where they define award identity.
- [ ] Do not carry raw JSON into the fact unless there is a deliberate reason.

Fact rebuild shape:

```sql
CREATE OR REPLACE TABLE fact_award AS
SELECT
    nan.appl_id AS application_id,
    org.organization_id,
    proj.Project_ID AS project_id,
    nan.agency_ic_admin_code,
    nan.fiscal_year AS federal_fiscal_year,
    nan.project_num,
    nan.activity_code,
    nan.appl_type_code,
    nan.support_year,
    nan.suffix_code,
    TRY_CAST(nan.award_notice_date AS DATE) AS award_notice_date,
    TRY_CAST(nan.budget_start AS DATE) AS budget_start,
    TRY_CAST(nan.budget_end AS DATE) AS budget_end,
    TRY_CAST(nan.project_start_date AS DATE) AS project_start_date,
    TRY_CAST(nan.project_end_date AS DATE) AS project_end_date,
    nan.direct_cost_amt AS direct_cost_amt,
    nan.indirect_cost_amt AS indirect_cost_amt,
    nan.award_amount AS award_amount
FROM nih_awards_national nan
LEFT JOIN dim_organization org
    ON nan.org_name IS NOT DISTINCT FROM org.org_name
   AND nan.org_duns IS NOT DISTINCT FROM org.org_duns
   AND nan.org_state IS NOT DISTINCT FROM org.org_state
   AND nan.geo_lat IS NOT DISTINCT FROM org.geo_lat
   AND nan.geo_lon IS NOT DISTINCT FROM org.geo_lon
LEFT JOIN dim_project proj
    ON nan.core_project_num = proj.core_project_num;
```

### Phase 5: Add Tests

Create a repeatable validation SQL file such as:

```text
duckdb scripts/validate_normalized_model.sql
```

Minimum tests:

- [ ] Row count: `fact_award` equals `nih_awards_national`.
- [ ] Uniqueness: `fact_award.application_id` has no duplicates.
- [ ] No orphan organization keys except approved unknown/null cases.
- [ ] No orphan project keys except approved null `core_project_num` cases.
- [ ] No orphan institute keys.
- [ ] No orphan bridge award keys.
- [ ] No orphan bridge investigator keys.
- [ ] `dim_investigator.profile_id` is unique.
- [ ] `bridge_award_investigator` has unique `(application_id, profile_id)`.
- [ ] Date conversions have zero invalid non-null values.
- [ ] `is_contact_pi` is boolean and each award has either exactly one contact PI or a documented exception.

### Phase 6: Make It Usable

- [ ] Add compatibility views for current app queries if needed.
- [ ] Create an analytics view for common joins.
- [ ] Create a smaller training database or exported Parquet subset for flight/offline work.
- [ ] Document query examples for funding by institute, organization, PI, project, and fiscal year.
- [ ] Update the Streamlit app pages to use normalized tables or compatibility views.

---

## 4. SQL Practice Sets

Do these without looking at the answer hints first. Use the full DB when possible and the slim DB for quick drills.

### Practice Set A: Orientation

Goal: get fast at reading an unfamiliar database.

1. List every table and row estimate.
2. Show all columns in `award_fact`.
3. Show all columns in `nih_awards_national` that contain `date`.
4. Count raw awards by fiscal year.
5. Find the first and last fiscal year in the raw data.
6. Count distinct organizations by state.
7. Find the top 20 IC/admin institutes by total award amount.
8. Count how many awards have null `award_amount`.
9. Count awards by `activity_code`.
10. Find the most recent `award_notice_date`.

Starter:

```sql
SELECT table_name, estimated_size
FROM duckdb_tables()
WHERE schema_name = 'main'
ORDER BY table_name;
```

### Practice Set B: Grain And Keys

Goal: prove table grain with SQL, not vibes.

1. Prove `award_fact` is one row per `ApplicationID`.
2. Prove `organizations` is one row per `organization_id`.
3. Test whether `org_duns` alone is a stable organization key.
4. Test whether `(org_name, org_state)` is unique in `organizations`.
5. Prove `projects` is one row per `core_project_num`.
6. Find raw `core_project_num` values missing from `projects`.
7. Count awards with null `core_project_num`.
8. Find the most common `project_num` prefixes.
9. Find whether `project_num` is unique in `award_fact`.
10. Find awards whose `project_num` appears under multiple application IDs.

Pattern:

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(DISTINCT ApplicationID) AS distinct_ids,
    COUNT(*) - COUNT(DISTINCT ApplicationID) AS duplicate_rows
FROM award_fact;
```

### Practice Set C: Joins And Anti-Joins

Goal: build referential-integrity instincts.

1. Count `award_fact` rows with a matching organization.
2. Count `award_fact` rows with no organization.
3. Count non-null org IDs in `award_fact` that do not resolve to `organizations`.
4. Count IC codes in `award_fact` that do not resolve to `nih_institutes`.
5. Count investigator bridge rows with no matching `award_fact`.
6. Count investigator bridge rows with no matching `investigators`.
7. Find awards with no investigator bridge rows.
8. Find investigators with no award bridge rows.
9. Find projects with no fact rows, after joining through `core_project_num`.
10. Write one query that returns all orphan counts as rows in a test result table.

Anti-join pattern:

```sql
SELECT COUNT(*) AS orphan_rows
FROM child_table c
LEFT JOIN parent_table p
    ON c.parent_key = p.parent_key
WHERE c.parent_key IS NOT NULL
  AND p.parent_key IS NULL;
```

### Practice Set D: Aggregation

Goal: answer real funding questions.

1. Total award amount by fiscal year.
2. Total direct and indirect costs by fiscal year.
3. Top 25 organizations by total award amount.
4. Top 25 organizations by active award count.
5. Top 25 PIs by total award amount as contact PI.
6. Total funding by IC/admin institute and fiscal year.
7. Percent of total annual funding by institute.
8. Average award size by activity code.
9. Median award size by activity code.
10. Number of unique projects funded each fiscal year.

Percent-of-total pattern:

```sql
WITH by_ic AS (
    SELECT
        Federal_Fiscal_Year,
        IC_Code,
        SUM(TotalCosts) AS total_costs
    FROM award_fact
    GROUP BY Federal_Fiscal_Year, IC_Code
)
SELECT
    *,
    total_costs
        / SUM(total_costs) OVER (PARTITION BY Federal_Fiscal_Year)
        AS pct_of_year
FROM by_ic;
```

### Practice Set E: Window Functions

Goal: maintain ranking and time-series fluency.

1. Rank institutes by funding within each fiscal year.
2. Find each organization's highest-funded fiscal year.
3. Find each PI's first and most recent award year.
4. Calculate year-over-year funding change by institute.
5. Calculate a three-year moving average of total funding by institute.
6. Find projects whose funding increased three years in a row.
7. Pick one display name per investigator using the latest award notice date.
8. Find duplicate award/profile rows and keep only one.
9. Find the top 10 awards per organization.
10. Label each award as above or below its activity-code median.

Display-name pattern:

```sql
WITH ranked AS (
    SELECT
        ai.profile_id,
        ai.Full_Name,
        ai.Last_Name,
        ai.First_Name,
        ai.ApplicationID,
        ROW_NUMBER() OVER (
            PARTITION BY ai.profile_id
            ORDER BY
                TRY_CAST(af.award_notice_date AS DATE) DESC NULLS LAST,
                ai.ApplicationID DESC
        ) AS name_rank
    FROM Award_Investigators ai
    JOIN award_fact af
        ON ai.ApplicationID = af.ApplicationID
)
SELECT *
FROM ranked
WHERE name_rank = 1;
```

### Practice Set F: Dates

Goal: stop treating dates as strings.

1. Convert `award_notice_date` to `DATE`.
2. Count invalid non-null date strings.
3. Count awards by award-notice month.
4. Count awards active during federal fiscal year 2024.
5. Count awards active on a given date.
6. Calculate project duration in days.
7. Find awards where `budget_end` is before `budget_start`.
8. Find awards where `project_end_date` is before `project_start_date`.
9. Compare award notice timing across institutes.
10. Build a fiscal-year label from dates.

Active-in-period pattern:

```sql
WHERE TRY_CAST(project_start_date AS DATE) <= DATE '2024-09-30'
  AND TRY_CAST(project_end_date AS DATE) >= DATE '2023-10-01'
```

### Practice Set G: JSON And Bridges

Goal: get comfortable extracting repeated entities.

1. Explode `pis_json` with `json_each`.
2. Extract `profile_id`, `first_name`, `last_name`, and `is_contact_pi`.
3. Count the number of PIs per application.
4. Find applications with more than five PIs.
5. Count awards with exactly one contact PI.
6. Find awards with zero contact PI.
7. Find awards with more than one contact PI.
8. Build a deduplicated award-investigator bridge.
9. Compare bridge row count before and after dedupe.
10. Rebuild investigator display names from the bridge.

JSON pattern:

```sql
SELECT
    nan.appl_id,
    pi.key,
    json_extract_string(pi.value, '$.profile_id') AS profile_id,
    json_extract_string(pi.value, '$.first_name') AS first_name,
    json_extract_string(pi.value, '$.last_name') AS last_name,
    json_extract_string(pi.value, '$.is_contact_pi')::BOOLEAN AS is_contact_pi
FROM nih_awards_national nan,
     json_each(nan.pis_json) AS pi
LIMIT 25;
```

### Practice Set H: Normalization Builds

Goal: turn SQL exercises into project progress.

1. Create `dim_institute`.
2. Create `dim_project`.
3. Create `dim_organization`.
4. Create `bridge_award_investigator`.
5. Create `dim_investigator`.
6. Create `bridge_project_title`.
7. Create `fact_award`.
8. Add validation queries after each create.
9. Write an analytics view that joins fact to project, org, institute, and contact PI.
10. Compare results from the normalized view against the old raw table for three dashboard metrics.

Build habit:

```text
CREATE TABLE
then immediately run:
1. row count
2. distinct key count
3. null key count
4. orphan checks
5. sample rows
```

---

## 5. Mini Answer Key And Validation Queries

Use these after you attempt the exercises.

### Fact Grain

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(DISTINCT ApplicationID) AS distinct_application_ids,
    COUNT(*) - COUNT(DISTINCT ApplicationID) AS duplicate_rows
FROM award_fact;
```

Expected current result:

```text
rows: 1,936,045
distinct_application_ids: 1,936,045
duplicate_rows: 0
```

### Missing Project Dimension Rows

```sql
SELECT
    core_project_num,
    COUNT(*) AS raw_rows,
    MIN(fiscal_year) AS first_fy,
    MAX(fiscal_year) AS last_fy
FROM nih_awards_national
WHERE core_project_num IS NOT NULL
  AND core_project_num NOT IN (
      SELECT core_project_num FROM projects
  )
GROUP BY core_project_num
ORDER BY raw_rows DESC, core_project_num;
```

Expected current finding:

```text
21 core_project_num values are missing from projects.
```

### Duplicate Award-Investigator Bridge Rows

```sql
SELECT
    ApplicationID,
    profile_id,
    Full_Name,
    COUNT(*) AS duplicate_rows
FROM Award_Investigators
GROUP BY ApplicationID, profile_id, Full_Name
HAVING COUNT(*) > 1
ORDER BY duplicate_rows DESC, ApplicationID;
```

Expected current finding:

```text
432 duplicate application/profile rows.
```

### Investigator Display-Name Null Date Check

```sql
WITH profile_date_status AS (
    SELECT
        ai.profile_id,
        MAX(CASE WHEN af.award_notice_date IS NOT NULL THEN 1 ELSE 0 END)
            AS has_dated_award,
        MAX(
            CASE
                WHEN i.ApplicationID = ai.ApplicationID
                 AND af.award_notice_date IS NULL
                THEN 1
                ELSE 0
            END
        ) AS selected_null_dated_award
    FROM Award_Investigators ai
    JOIN award_fact af
        ON ai.ApplicationID = af.ApplicationID
    JOIN investigators i
        ON ai.profile_id = i.profile_id
    GROUP BY ai.profile_id
)
SELECT COUNT(*) AS likely_affected_by_nulls_first
FROM profile_date_status
WHERE selected_null_dated_award = 1
  AND has_dated_award = 1;
```

Expected current finding:

```text
28,720 investigator profiles are likely affected by NULLS FIRST.
```

### Awards Without Investigators

```sql
SELECT COUNT(*) AS award_fact_rows_without_investigators
FROM award_fact af
LEFT JOIN (
    SELECT DISTINCT ApplicationID
    FROM Award_Investigators
) ai USING (ApplicationID)
WHERE ai.ApplicationID IS NULL;
```

Expected current finding:

```text
2,942 awards have no investigator bridge rows.
```

### IC Referential Integrity

```sql
SELECT
    af.IC_Code,
    COUNT(*) AS rows
FROM award_fact af
LEFT JOIN nih_institutes ni
    ON af.IC_Code = ni.agency_ic_admin_code
WHERE af.IC_Code IS NOT NULL
  AND ni.agency_ic_admin_code IS NULL
GROUP BY af.IC_Code
ORDER BY rows DESC;
```

Expected current result:

```text
0 rows
```

### Date Validity

```sql
SELECT
    COUNT(*) FILTER (
        WHERE award_notice_date IS NOT NULL
          AND TRY_CAST(award_notice_date AS DATE) IS NULL
    ) AS invalid_award_notice_dates
FROM award_fact;
```

Expected current result:

```text
0 invalid non-null award_notice_date values.
```

---

## 6. General SQL Knowledge To Retain

### Always Start With Grain

Before writing joins, say this sentence:

```text
This table has one row per ____.
```

If you cannot fill in the blank, do not trust your query yet.

Examples:

```text
award_fact: one row per ApplicationID
organizations: one row per organization_id
investigators: one row per profile_id
Award_Investigators: should be one row per ApplicationID plus profile_id
```

### Know Your Join Type

| Join | Use it when |
|---|---|
| `INNER JOIN` | You only want rows that match on both sides |
| `LEFT JOIN` | You want to keep all rows from the left table |
| Anti-join | You want missing relationships |
| Semi-join | You want rows where a related row exists |

Anti-join:

```sql
SELECT c.*
FROM child c
LEFT JOIN parent p
    ON c.parent_id = p.parent_id
WHERE p.parent_id IS NULL;
```

Semi-join:

```sql
SELECT *
FROM parent p
WHERE EXISTS (
    SELECT 1
    FROM child c
    WHERE c.parent_id = p.parent_id
);
```

### Use `IS NOT DISTINCT FROM` For Nullable Natural Keys

Normal equality does not match nulls:

```sql
NULL = NULL
```

returns unknown, not true.

For nullable natural-key joins, use:

```sql
a.org_duns IS NOT DISTINCT FROM b.org_duns
```

You already use this correctly in the organization join.

### Prefer Typed Dates

Strings sort alphabetically. Dates sort chronologically.

Good:

```sql
TRY_CAST(award_notice_date AS DATE) AS award_notice_date
```

Then use:

```sql
date_trunc('month', award_notice_date)
```

### Distinguish Measures From Attributes

Measures can usually be summed:

```text
award_amount
direct_cost_amt
indirect_cost_amt
award_count
```

Attributes describe things:

```text
org_name
project_title
agency_ic_admin_name
activity_code
```

When a dimension attribute appears in a fact table, ask whether it is there for performance, compatibility, or because the model is not finished.

### Window Functions Are Post-Aggregation Tools

Common uses:

```text
ROW_NUMBER: choose one row
RANK / DENSE_RANK: rank within groups
LAG / LEAD: compare with prior/next row
SUM(...) OVER: calculate totals without collapsing rows
AVG(...) OVER: moving averages
```

Example:

```sql
SELECT
    fiscal_year,
    agency_ic_admin_name,
    total_award,
    total_award - LAG(total_award) OVER (
        PARTITION BY agency_ic_admin_name
        ORDER BY fiscal_year
    ) AS yoy_change
FROM annual_ic_funding;
```

### Normalize For Truth, Denormalize For Use

Normalized tables should make identity and relationships clean.

Analytics views can make common queries pleasant:

```sql
CREATE OR REPLACE VIEW vw_award_analytics AS
SELECT
    af.application_id,
    af.federal_fiscal_year,
    af.award_amount,
    org.org_name,
    org.org_state,
    proj.core_project_num,
    inst.agency_ic_admin_abbrev,
    inst.agency_ic_admin_name
FROM fact_award af
LEFT JOIN dim_organization org
    ON af.organization_id = org.organization_id
LEFT JOIN dim_project proj
    ON af.project_id = proj.project_id
LEFT JOIN dim_institute inst
    ON af.agency_ic_admin_code = inst.agency_ic_admin_code;
```

This keeps the model clean while making app/query work easier.

---

## 7. DuckDB Tips

### Inspect Before You Scan

```sql
SELECT *
FROM duckdb_tables()
WHERE schema_name = 'main';
```

```sql
DESCRIBE table_name;
```

### Use `LIMIT` While Exploring

```sql
SELECT *
FROM nih_awards_national
LIMIT 25;
```

### Use `TRY_CAST`

`CAST` fails on bad data. `TRY_CAST` returns null.

```sql
TRY_CAST(award_notice_date AS DATE)
```

### Use CTEs To Make Thought Visible

```sql
WITH base AS (...),
aggregated AS (...),
ranked AS (...)
SELECT *
FROM ranked
WHERE rn <= 10;
```

Each CTE should have a clear reason to exist.

### Save Repeatable Work

Put reusable SQL here:

```text
duckdb scripts/
Tables/
Practice SQL/
```

Recommended new files:

```text
duckdb scripts/build_normalized_model.sql
duckdb scripts/validate_normalized_model.sql
docs/data_dictionary.md
docs/erd.md
```

---

## 8. Flight Study Plan

### Session 1: Model Review, 45-60 Minutes

- Read sections 1-3.
- Write the target ERD on paper.
- For each target table, write the grain in one sentence.
- Mark columns that belong in fact vs dimensions.

Deliverable:

```text
One clean handwritten ERD and table-grain list.
```

### Session 2: SQL Warmup, 45-60 Minutes

- Do Practice Set A.
- Do Practice Set B, exercises 1-6.
- Check answers only after writing the queries.

Deliverable:

```text
10-15 working queries saved or written out.
```

### Session 3: Project Integrity, 60-90 Minutes

- Do Practice Set C.
- Write a first draft of `validate_normalized_model.sql`.
- Turn each current quality finding into a test query.

Deliverable:

```text
A validation checklist that can be run after every rebuild.
```

### Session 4: Bridge Tables, 60-90 Minutes

- Do Practice Set G.
- Write a deduped `bridge_award_investigator` query.
- Decide the handling rule for duplicate app/profile rows.
- Decide the handling rule for missing contact PI cases.

Deliverable:

```text
Bridge table SQL plus documented exception policy.
```

### Session 5: Rebuild Design, 60-90 Minutes

- Draft SQL for `dim_project`, `dim_organization`, and `fact_award`.
- Add `Project_ID`/`project_id` to the fact.
- Convert dates to `DATE`.
- Write validation queries beside each create statement.

Deliverable:

```text
First draft of build_normalized_model.sql.
```

### Session 6: Analytics Practice, 45-60 Minutes

- Do Practice Sets D and E.
- Pick three dashboard metrics and write normalized-table versions.
- Compare mentally against raw-table versions.

Deliverable:

```text
Three app-ready queries against the normalized model.
```

---

## 9. High-Value Habits

### Before Every Query

Ask:

```text
What is the row grain of my result?
Which table controls the row count?
Could this join multiply rows?
What nulls do I expect?
What result would surprise me?
```

### After Every Query

Check:

```sql
COUNT(*)
COUNT(DISTINCT key)
MIN(date_column), MAX(date_column)
SUM(amount)
```

Then sample:

```sql
SELECT *
FROM result
ORDER BY random()
LIMIT 10;
```

### When A Join Looks Wrong

Debug in this order:

1. Count left table.
2. Count right table.
3. Count distinct join keys on both sides.
4. Count null join keys.
5. Count duplicate join keys.
6. Run an anti-join in both directions.
7. Join a small filtered sample.

### When A Dimension Feels Messy

Ask:

```text
What is the business identity?
What is the source identity?
What is the display label?
Can labels change over time?
Do I need history or just current display?
```

For investigators, you already have a good rule:

```text
profile_id defines identity.
latest non-null award_notice_date picks display name.
ApplicationID breaks ties.
```

---

## 10. Final Project Definition Of Done

The normalized database is finished enough when:

- [ ] Every table has a documented grain.
- [ ] Every primary key candidate has a uniqueness test.
- [ ] Every foreign key relationship has an orphan test.
- [ ] `fact_award` has one row per `ApplicationID`.
- [ ] `fact_award` includes `organization_id`, `project_id`, and `agency_ic_admin_code`.
- [ ] Date columns needed for analysis are stored as `DATE`.
- [ ] `bridge_award_investigator` has one row per `(application_id, profile_id)`.
- [ ] `dim_investigator` has one row per `profile_id`.
- [ ] Missing/exception cases are documented.
- [ ] Current dashboard queries either work through compatibility views or have been migrated.
- [ ] Validation SQL can be rerun after refreshes.
- [ ] The slim/training DB can be regenerated.

If you can run the validation script after a data refresh and explain each exception without anxiety, the model is in good shape.
