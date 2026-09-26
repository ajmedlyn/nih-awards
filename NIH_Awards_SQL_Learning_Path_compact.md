# NIH Awards SQL Learning Path: Compact Travel Version

Purpose: finish the normalized NIH awards database while keeping SQL skills warm.

Use this as a flight packet. The full reference stays in:

```text
NIH_Awards_SQL_Learning_Path.md
```

---

## 1. Current State

Main DB:

```text
nih_awards.duckdb        18 GB
nih_awards_slim.duckdb   33 MB
```

Core tables:

| Table | Rows | Grain / role |
|---|---:|---|
| `nih_awards_national` | 1,936,045 | Raw award rows |
| `award_fact` | 1,936,045 | Current fact, one row per `ApplicationID` |
| `organizations` | 18,420 | Org dimension candidate |
| `projects` | 407,356 | Project dimension candidate, one row per `core_project_num` |
| `investigators` | 211,289 | PI dimension candidate, one row per `profile_id` |
| `Award_Investigators` | 2,180,014 | Award-to-PI bridge |
| `nih_institutes` | 87 | IC/admin institute dimension |
| `project_titles_main_projects` | 478,440 | Project title history/variants |

Key findings to fix or preserve:

| Finding | Current result | Action |
|---|---:|---|
| `award_fact` row count equals raw | 1,936,045 | Preserve |
| Duplicate `ApplicationID` in `award_fact` | 0 | Preserve |
| Null `ORG_ID` in `award_fact` | 560 | Decide null vs unknown org |
| Raw `core_project_num` missing from `projects` | 21 | Rebuild `dim_project` |
| Raw rows missing `core_project_num` | 11 | Document exception |
| Duplicate `(ApplicationID, profile_id)` in PI bridge | 432 | Dedupe bridge |
| Awards with no investigator bridge rows | 2,942 | Document or fix |
| Awards with zero contact PI in bridge | 2 | Investigate |
| Investigator rows likely affected by `NULLS FIRST` | 28,720 | Rebuild with `NULLS LAST` |
| Invalid non-null date strings | 0 | Convert to real `DATE` |

---

## 2. Target Model

Keep the model boring and clear.

| Target table | Grain | Key |
|---|---|---|
| `fact_award` | One row per award/application | `application_id` |
| `dim_organization` | One row per stable org identity | `organization_id` |
| `dim_project` | One row per `core_project_num` | `project_id` |
| `dim_institute` | One row per IC/admin code | `agency_ic_admin_code` |
| `dim_investigator` | One row per NIH PI profile | `profile_id` |
| `bridge_award_investigator` | One row per award plus PI | `application_id`, `profile_id` |
| `bridge_project_title` | One row per project plus observed title | `project_id`, title key |

Fact table should hold:

```text
keys + dates + measures + award identity fields
```

Good fact columns:

```text
application_id
organization_id
project_id
agency_ic_admin_code
federal_fiscal_year
project_num
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

Attributes that should usually live outside the fact:

```text
org_name
agency_ic_admin_name
project_title
pi_names
pis_json
abstract_text
terms
spending_categories_json
```

---

## 3. Finish-The-Project Checklist

### Phase 1: Freeze Definitions

- [ ] Write the grain of every target table.
- [ ] Pick naming convention: prefer snake case for new tables.
- [ ] Decide: replace old tables or create new `dim_*`, `fact_*`, `bridge_*`.
- [ ] Add a short data dictionary.
- [ ] Add a simple ERD.

Main design choice:

```text
Recommended: build new normalized tables, then create compatibility views for the app if needed.
```

### Phase 2: Rebuild Dimensions

- [ ] `dim_institute`: distinct IC/admin code, abbrev, name.
- [ ] `dim_project`: rebuild from all raw rows; include the 21 missing `core_project_num` values.
- [ ] `dim_organization`: decide whether identity includes city, country, UEI, DUNS, state, lat/lon.
- [ ] `dim_investigator`: one row per `profile_id`.
- [ ] Use typed `DATE` columns where possible.

Investigator rule:

```text
profile_id defines identity.
latest non-null award_notice_date picks display name.
highest ApplicationID breaks ties.
null dates go last.
```

Current script issue:

```text
Tables/Investigators.sql uses NULLS FIRST.
Rebuild with NULLS LAST.
```

### Phase 3: Rebuild Bridges

- [ ] `bridge_award_investigator` from `pis_json`.
- [ ] Cast `is_contact_pi` to `BOOLEAN`.
- [ ] Dedupe `(application_id, profile_id)`.
- [ ] Investigate 432 duplicate award/profile rows.
- [ ] Investigate 2 awards with zero contact PI.
- [ ] Document 2,942 awards with no investigator rows.
- [ ] `bridge_project_title` for project title variants.

### Phase 4: Rebuild Fact

- [ ] Keep one row per `application_id`.
- [ ] Add `project_id`.
- [ ] Add `organization_id`.
- [ ] Add `agency_ic_admin_code`.
- [ ] Convert dates with `TRY_CAST(... AS DATE)`.
- [ ] Keep measures: direct, indirect, total/award amount.
- [ ] Leave raw JSON and text-heavy fields out of the fact.

### Phase 5: Validate

Minimum validation:

- [ ] `fact_award` count equals `nih_awards_national`.
- [ ] `fact_award.application_id` is unique.
- [ ] No unexpected org/project/institute orphans.
- [ ] Bridge rows resolve to awards and investigators.
- [ ] Bridge has unique `(application_id, profile_id)`.
- [ ] Date conversions have zero invalid non-null values.
- [ ] Contact PI exceptions are known.

---

## 4. SQL Toolbelt: What To Reach For

| Question shape | SQL tool |
|---|---|
| Is this one row per X? | `COUNT(*)` vs `COUNT(DISTINCT X)` |
| What is duplicated? | `GROUP BY key HAVING COUNT(*) > 1` |
| What is missing? | Anti-join: `LEFT JOIN ... WHERE right.key IS NULL` |
| Did this join multiply rows? | Count joined rows vs distinct left keys |
| Top N overall? | `GROUP BY`, `ORDER BY`, `LIMIT` |
| Top N within each group? | `ROW_NUMBER()` / `RANK()` with `PARTITION BY` |
| Latest row per entity? | `ROW_NUMBER() OVER (PARTITION BY entity ORDER BY date DESC)` |
| Year-over-year change? | Aggregate first, then `LAG()` |
| Percent of total? | `SUM(...) OVER (PARTITION BY ...)` |
| Text dates? | `TRY_CAST(text_col AS DATE)` |
| JSON list to rows? | `json_each()` |
| Nullable natural-key join? | `IS NOT DISTINCT FROM` |

Core habit:

```text
Name the row grain before joining more tables.
```

---

## 5. Essential Query Patterns

### Grain Check

Use when you need to prove a table is one row per key.

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(DISTINCT ApplicationID) AS distinct_application_ids,
    COUNT(*) - COUNT(DISTINCT ApplicationID) AS duplicate_rows
FROM award_fact;
```

### Duplicate Finder

Use when uniqueness breaks.

```sql
SELECT
    ApplicationID,
    profile_id,
    COUNT(*) AS rows
FROM Award_Investigators
GROUP BY ApplicationID, profile_id
HAVING COUNT(*) > 1
ORDER BY rows DESC, ApplicationID;
```

### Anti-Join

Use when looking for missing parent records.

```sql
SELECT COUNT(*) AS org_orphans
FROM award_fact af
LEFT JOIN organizations o
    ON af.ORG_ID = o.organization_id
WHERE af.ORG_ID IS NOT NULL
  AND o.organization_id IS NULL;
```

Raw projects missing from project dimension:

```sql
SELECT DISTINCT nan.core_project_num
FROM nih_awards_national nan
LEFT JOIN projects p
    ON nan.core_project_num = p.core_project_num
WHERE nan.core_project_num IS NOT NULL
  AND p.core_project_num IS NULL;
```

### Join Multiplication Check

Use before summing after a join.

```sql
WITH joined AS (
    SELECT af.ApplicationID
    FROM award_fact af
    JOIN Award_Investigators ai
        ON af.ApplicationID = ai.ApplicationID
)
SELECT
    COUNT(*) AS joined_rows,
    COUNT(DISTINCT ApplicationID) AS distinct_awards,
    COUNT(*) - COUNT(DISTINCT ApplicationID) AS extra_rows
FROM joined;
```

Interpretation:

```text
Extra rows are expected for award-to-PI joins.
Do not sum award dollars after that join unless you mean PI participation dollars.
```

### One Row Per Entity

Use to choose a canonical investigator display name.

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
        ) AS rn
    FROM Award_Investigators ai
    JOIN award_fact af
        ON ai.ApplicationID = af.ApplicationID
)
SELECT *
FROM ranked
WHERE rn = 1;
```

### Percent Of Annual Funding

```sql
WITH annual_ic AS (
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
FROM annual_ic;
```

### Year-Over-Year Change

```sql
WITH annual AS (
    SELECT
        Federal_Fiscal_Year,
        IC_Code,
        SUM(TotalCosts) AS total_costs
    FROM award_fact
    GROUP BY Federal_Fiscal_Year, IC_Code
)
SELECT
    *,
    total_costs - LAG(total_costs) OVER (
        PARTITION BY IC_Code
        ORDER BY Federal_Fiscal_Year
    ) AS yoy_change
FROM annual;
```

### Date Overlap

Use for active awards in a fiscal year.

```sql
WHERE TRY_CAST(project_start_date AS DATE) <= DATE '2024-09-30'
  AND TRY_CAST(project_end_date AS DATE) >= DATE '2023-10-01'
```

Pattern:

```text
start <= period_end AND end >= period_start
```

### JSON To Bridge

```sql
SELECT
    nan.appl_id AS ApplicationID,
    pi.key AS pi_position,
    json_extract_string(pi.value, '$.profile_id') AS profile_id,
    json_extract_string(pi.value, '$.first_name') AS first_name,
    json_extract_string(pi.value, '$.last_name') AS last_name,
    json_extract_string(pi.value, '$.is_contact_pi')::BOOLEAN AS is_contact_pi
FROM nih_awards_national nan,
     json_each(nan.pis_json) AS pi;
```

---

## 6. Focused Practice Sets

### Set A: Orientation

Reach for:

```text
duckdb_tables()
DESCRIBE
COUNT(*)
COUNT(DISTINCT key)
```

Do:

1. List tables and row estimates.
2. Prove `award_fact` grain.
3. Prove `projects` grain.
4. Test whether `Award_Investigators` is unique by `(ApplicationID, profile_id)`.
5. Count awards by fiscal year.

### Set B: Referential Integrity

Reach for:

```text
anti-joins
```

Do:

1. `award_fact.ORG_ID` -> `organizations.organization_id`.
2. `award_fact.IC_Code` -> `nih_institutes.agency_ic_admin_code`.
3. `Award_Investigators.ApplicationID` -> `award_fact.ApplicationID`.
4. `Award_Investigators.profile_id` -> `investigators.profile_id`.
5. Raw `core_project_num` -> `projects.core_project_num`.

### Set C: Safe Aggregation

Reach for:

```text
group only after row grain is correct
```

Do:

1. Total award amount by fiscal year.
2. Total award amount by IC and fiscal year.
3. Top 20 organizations by total award amount.
4. Top 20 contact PIs by total award amount.
5. Percent of annual funding by IC.

Before summing after joins, ask:

```text
Did this join multiply my awards?
```

### Set D: Windows

Reach for:

```text
ROW_NUMBER, RANK, LAG, SUM OVER
```

Do:

1. Top 10 ICs within each fiscal year.
2. Year-over-year change by IC.
3. Three-year moving average by IC.
4. One display name per investigator.
5. One deduped bridge row per `(ApplicationID, profile_id)`.

### Set E: Rebuild Work

Reach for:

```text
CREATE OR REPLACE TABLE AS + validation immediately after
```

Do:

1. Draft `dim_project`.
2. Draft `dim_institute`.
3. Draft deduped `bridge_award_investigator`.
4. Draft `dim_investigator` with `NULLS LAST`.
5. Draft `fact_award` with `project_id`, `organization_id`, typed dates, and measures.

---

## 7. Flight Sessions

### Session 1: ERD And Grain, 45 Minutes

- Draw target tables.
- Write one sentence of grain per table.
- Mark keys, measures, and attributes.
- Circle fields that should leave the fact table.

Deliverable:

```text
One clean ERD and table-grain list.
```

### Session 2: Validation SQL, 60 Minutes

- Write tests for the current findings.
- Turn every exception into a count query.
- Use `pass` / `fail` status where possible.

Deliverable:

```text
First draft of validate_normalized_model.sql.
```

### Session 3: Bridge And Investigator Fix, 60 Minutes

- Explode `pis_json`.
- Dedupe `(ApplicationID, profile_id)`.
- Rebuild investigator display name with `NULLS LAST`.
- Validate uniqueness and orphan counts.

Deliverable:

```text
Bridge and investigator rebuild SQL.
```

### Session 4: Fact Rebuild, 60 Minutes

- Add `project_id`, `organization_id`, and IC code.
- Convert dates.
- Keep measures.
- Validate row count and key uniqueness.

Deliverable:

```text
First draft of fact_award rebuild SQL.
```

---

## 8. Definition Of Done

The project is finished enough when:

- [ ] Each normalized table has a written grain.
- [ ] Each primary key candidate has a uniqueness test.
- [ ] Each foreign key has an orphan test.
- [ ] `fact_award` has one row per `application_id`.
- [ ] `fact_award` includes `organization_id`, `project_id`, and `agency_ic_admin_code`.
- [ ] Dates needed for analysis are real `DATE` columns.
- [ ] `bridge_award_investigator` is unique by `(application_id, profile_id)`.
- [ ] `dim_investigator` is unique by `profile_id`.
- [ ] Known exceptions are documented.
- [ ] App queries work through migrated SQL or compatibility views.
- [ ] Validation SQL can be rerun after refreshes.

Final mental loop:

```text
1. What grain do I want?
2. Which table naturally has that grain?
3. What measures do I need?
4. What attributes do I need?
5. Did my join change the row count?
6. Can I validate the result?
```

