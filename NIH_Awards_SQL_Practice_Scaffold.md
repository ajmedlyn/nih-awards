# NIH Awards SQL Practice Scaffold

This guide is for learning what tool to reach for.

The goal is not to memorize finished queries. The goal is to build the reflex:

```text
Question shape -> SQL tool -> small proof query -> final query
```

Use this alongside:

```text
NIH_Awards_SQL_Learning_Path.md
```

---

## 1. The Core Reflex

Before writing SQL, classify the question.

| If the question asks... | Reach for... | Why |
|---|---|---|
| "How many rows?" | `COUNT(*)` | Establish table size |
| "How many unique things?" | `COUNT(DISTINCT key)` | Check identity or cardinality |
| "Is this one row per X?" | `COUNT(*)` vs `COUNT(DISTINCT X)` | Prove grain |
| "What is missing?" | `LEFT JOIN ... WHERE right.key IS NULL` | Anti-join finds gaps |
| "What is duplicated?" | `GROUP BY key HAVING COUNT(*) > 1` | Exposes broken uniqueness |
| "Top N by amount/count?" | `GROUP BY`, `SUM`, `COUNT`, `ORDER BY`, `LIMIT` | Standard ranking |
| "Top N within each group?" | `ROW_NUMBER()` or `RANK()` | Ranking inside partitions |
| "Latest row per person/project?" | `ROW_NUMBER() OVER (...)` | Pick one row deterministically |
| "Change over time?" | `LAG()` or `LEAD()` | Compare current row to prior row |
| "Percent of total?" | `SUM(...) OVER (...)` | Keep detail while adding denominator |
| "Running or moving total?" | Window frame | Time-series analysis |
| "String date problem?" | `TRY_CAST(... AS DATE)` | Convert safely |
| "Nested JSON list?" | `json_each()` | Explode repeated entities |
| "Nullable natural-key join?" | `IS NOT DISTINCT FROM` | Treat nulls as comparable |
| "Build a model table?" | `CREATE OR REPLACE TABLE AS` plus validation | Materialize repeatable logic |

Most NIH awards work is some combination of:

```text
grain -> keys -> joins -> dates -> aggregation -> validation
```

---

## 2. Your Main Tables

Think of the current model this way:

| Table | Mental model | Grain to remember |
|---|---|---|
| `nih_awards_national` | Raw source | One row per application/award row |
| `award_fact` | Current fact candidate | One row per `ApplicationID` |
| `organizations` | Org dimension candidate | One row per `organization_id` |
| `projects` | Project dimension candidate | One row per `core_project_num` |
| `investigators` | PI dimension candidate | One row per `profile_id` |
| `Award_Investigators` | Award-PI bridge | Should be one row per `ApplicationID`, `profile_id` |
| `nih_institutes` | Institute dimension | One row per `agency_ic_admin_code` |

When in doubt, ask:

```text
Which table should control the row count?
```

For award-level analysis, usually `award_fact` or `nih_awards_national` controls the row count.

For PI-level analysis, usually `investigators` controls the row count.

For award-to-PI analysis, the bridge controls the row count.

---

## 3. The SQL Toolbelt

### Tool 1: Grain Check

Use when:

```text
I need to know whether this table is really one row per key.
```

Template:

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(DISTINCT key_column) AS distinct_keys,
    COUNT(*) - COUNT(DISTINCT key_column) AS duplicate_rows
FROM table_name;
```

NIH version:

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(DISTINCT ApplicationID) AS distinct_application_ids,
    COUNT(*) - COUNT(DISTINCT ApplicationID) AS duplicate_rows
FROM award_fact;
```

How to think:

```text
If rows = distinct keys, the key uniquely identifies rows.
If rows > distinct keys, the table is more detailed than that key.
```

Practice:

1. Prove the grain of `award_fact`.
2. Prove the grain of `projects`.
3. Test whether `org_duns` alone is enough for `organizations`.
4. Test whether `Award_Investigators` is unique by `(ApplicationID, profile_id)`.

Hint:

```sql
COUNT(DISTINCT col1 || '|' || col2)
```

is a quick composite-key check. For production-quality work, prefer grouping by both columns.

---

### Tool 2: Duplicate Finder

Use when:

```text
I expected one row per key, but I need to find where that breaks.
```

Template:

```sql
SELECT
    key_column,
    COUNT(*) AS rows
FROM table_name
GROUP BY key_column
HAVING COUNT(*) > 1
ORDER BY rows DESC;
```

NIH version:

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

What this tells you:

```text
The bridge currently has repeated application/profile pairs.
That means joins from awards to investigators may multiply rows.
```

Next move:

Use `ROW_NUMBER()` to inspect or dedupe.

---

### Tool 3: Anti-Join

Use when:

```text
I need to find records in one table that do not have a match in another table.
```

Template:

```sql
SELECT COUNT(*) AS missing_rows
FROM child c
LEFT JOIN parent p
    ON c.parent_key = p.parent_key
WHERE c.parent_key IS NOT NULL
  AND p.parent_key IS NULL;
```

NIH version:

```sql
SELECT COUNT(*) AS award_fact_org_orphans
FROM award_fact af
LEFT JOIN organizations o
    ON af.ORG_ID = o.organization_id
WHERE af.ORG_ID IS NOT NULL
  AND o.organization_id IS NULL;
```

Use anti-joins for:

- Fact rows missing a dimension match.
- Dimension rows not used by facts.
- Raw keys missing from normalized tables.
- Bridge rows pointing to missing parent records.

Practice:

1. Find `award_fact` rows whose `IC_Code` does not exist in `nih_institutes`.
2. Find raw `core_project_num` values missing from `projects`.
3. Find `Award_Investigators` rows whose `profile_id` does not exist in `investigators`.
4. Find awards in `award_fact` with no investigator bridge rows.

Hint for raw projects:

```sql
SELECT DISTINCT nan.core_project_num
FROM nih_awards_national nan
LEFT JOIN projects p
    ON nan.core_project_num = p.core_project_num
WHERE nan.core_project_num IS NOT NULL
  AND p.core_project_num IS NULL;
```

---

### Tool 4: Join Multiplication Check

Use when:

```text
My totals got too large after a join.
```

The fear:

```text
One award joins to multiple rows, so award_amount gets counted multiple times.
```

Template:

```sql
WITH joined AS (
    SELECT
        left_table.primary_key
    FROM left_table
    JOIN right_table
        ON ...
)
SELECT
    COUNT(*) AS joined_rows,
    COUNT(DISTINCT primary_key) AS distinct_left_keys,
    COUNT(*) - COUNT(DISTINCT primary_key) AS extra_rows
FROM joined;
```

NIH version:

```sql
WITH joined AS (
    SELECT
        af.ApplicationID
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
extra_rows are not always bad.
For award-to-PI joins, extra rows are expected because one award can have multiple PIs.
But if you then SUM award_amount, you must decide whether to count each award once or allocate across PIs.
```

Question to ask:

```text
Am I doing award-level analysis or investigator-participation analysis?
```

---

### Tool 5: Grouped Aggregation

Use when:

```text
I need totals, counts, averages, or medians by category.
```

Template:

```sql
SELECT
    category,
    COUNT(*) AS row_count,
    SUM(amount) AS total_amount
FROM table_name
GROUP BY category
ORDER BY total_amount DESC;
```

NIH version:

```sql
SELECT
    Federal_Fiscal_Year,
    IC_Code,
    COUNT(*) AS award_count,
    SUM(TotalCosts) AS total_costs
FROM award_fact
GROUP BY Federal_Fiscal_Year, IC_Code
ORDER BY Federal_Fiscal_Year, total_costs DESC;
```

Reach for this when you hear:

```text
by fiscal year
by institute
by organization
by activity code
top funded
average award size
```

Practice:

1. Funding by fiscal year.
2. Funding by IC and fiscal year.
3. Award count by activity code.
4. Average award size by organization state.
5. Median award size by activity code.

Hint:

DuckDB supports:

```sql
median(TotalCosts)
```

---

### Tool 6: Ranking

Use when:

```text
I need top N overall or top N within each group.
```

Top N overall:

```sql
SELECT
    org_name,
    SUM(TotalCosts) AS total_costs
FROM award_fact af
JOIN organizations o
    ON af.ORG_ID = o.organization_id
GROUP BY org_name
ORDER BY total_costs DESC
LIMIT 10;
```

Top N within each fiscal year:

```sql
WITH by_ic AS (
    SELECT
        Federal_Fiscal_Year,
        IC_Code,
        SUM(TotalCosts) AS total_costs
    FROM award_fact
    GROUP BY Federal_Fiscal_Year, IC_Code
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY Federal_Fiscal_Year
            ORDER BY total_costs DESC
        ) AS rank_in_year
    FROM by_ic
)
SELECT *
FROM ranked
WHERE rank_in_year <= 10
ORDER BY Federal_Fiscal_Year, rank_in_year;
```

Tool choice:

| Need | Use |
|---|---|
| Exactly 10 rows per group | `ROW_NUMBER()` |
| Preserve ties | `RANK()` |
| Preserve ties without gaps | `DENSE_RANK()` |

---

### Tool 7: Pick One Row Per Entity

Use when:

```text
I have many observations but need one canonical record.
```

Examples:

- One display name per investigator.
- One latest title per project.
- One most recent award per project.
- One preferred organization record.

Template:

```sql
WITH ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY entity_key
            ORDER BY sort_column DESC
        ) AS rn
    FROM source_table
)
SELECT *
FROM ranked
WHERE rn = 1;
```

NIH investigator version:

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

Why `NULLS LAST` matters:

```text
The documented rule says real award dates should beat null dates.
If you use NULLS FIRST, a null-dated old record can become the display name.
```

DuckDB shortcut:

```sql
SELECT ...
FROM ...
QUALIFY ROW_NUMBER() OVER (...) = 1;
```

Use `QUALIFY` when you want to filter on a window function without adding another CTE.

---

### Tool 8: Time Comparison

Use when:

```text
I need growth, decline, first/last, or change over time.
```

Common tools:

| Need | Use |
|---|---|
| Previous year value | `LAG()` |
| Next year value | `LEAD()` |
| First year | `MIN(fiscal_year)` |
| Last year | `MAX(fiscal_year)` |
| Moving average | `AVG(...) OVER (...)` |
| Running total | `SUM(...) OVER (...)` |

NIH year-over-year funding:

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
FROM annual
ORDER BY IC_Code, Federal_Fiscal_Year;
```

Three-year moving average:

```sql
AVG(total_costs) OVER (
    PARTITION BY IC_Code
    ORDER BY Federal_Fiscal_Year
    ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
) AS three_year_avg
```

Think:

```text
GROUP BY creates one row per time period first.
Window functions compare those already-aggregated rows.
```

---

### Tool 9: Percent Of Total

Use when:

```text
I need share, mix, contribution, or percent of annual funding.
```

Template:

```sql
SELECT
    group_col,
    amount,
    amount / SUM(amount) OVER () AS pct_of_total
FROM grouped_data;
```

NIH version:

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
FROM annual_ic
ORDER BY Federal_Fiscal_Year, pct_of_year DESC;
```

Reach for:

```text
SUM(...) OVER (PARTITION BY ...)
```

when you need a denominator but do not want to collapse the rows.

---

### Tool 10: Date Safety

Use when:

```text
The source stores dates as strings.
```

First validate:

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(*) FILTER (
        WHERE award_notice_date IS NOT NULL
          AND TRY_CAST(award_notice_date AS DATE) IS NULL
    ) AS invalid_dates
FROM award_fact;
```

Then convert:

```sql
TRY_CAST(award_notice_date AS DATE) AS award_notice_date
```

Active-in-period question:

```text
Was this project active at any time during federal FY2024?
```

Reach for interval overlap:

```sql
WHERE TRY_CAST(project_start_date AS DATE) <= DATE '2024-09-30'
  AND TRY_CAST(project_end_date AS DATE) >= DATE '2023-10-01'
```

Pattern:

```text
start <= period_end AND end >= period_start
```

This is the standard overlap test.

---

### Tool 11: JSON Explosion

Use when:

```text
A column contains a list of repeated objects.
```

For NIH, `pis_json` contains multiple investigator objects per award.

Reach for:

```sql
json_each()
```

NIH pattern:

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

Thought process:

```text
Raw award row -> explode PI list -> one row per award plus PI -> bridge table
```

Validation after explosion:

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(DISTINCT ApplicationID || '|' || profile_id) AS distinct_award_pi_pairs
FROM exploded_pis;
```

---

### Tool 12: CTE Ladder

Use when:

```text
The query has more than one idea in it.
```

CTE structure:

```sql
WITH base AS (
    -- select the rows and columns you need
),
cleaned AS (
    -- cast dates, clean strings, filter bad rows
),
aggregated AS (
    -- group to the desired grain
),
ranked AS (
    -- window functions
)
SELECT *
FROM ranked;
```

Rule:

```text
Each CTE should change the row grain or make one idea clearer.
```

Bad sign:

```text
You cannot explain what a CTE does in one sentence.
```

---

## 4. Question Shapes And First Moves

### Shape A: "How many awards..."

First table:

```text
award_fact
```

First move:

```sql
SELECT COUNT(*)
FROM award_fact;
```

Then add filters.

Example:

```text
How many NIH awards were active in FY2024?
```

Tool:

```text
Date overlap filter
```

Skeleton:

```sql
SELECT COUNT(*)
FROM nih_awards_national
WHERE TRY_CAST(project_start_date AS DATE) <= DATE '2024-09-30'
  AND TRY_CAST(project_end_date AS DATE) >= DATE '2023-10-01';
```

---

### Shape B: "Which organizations..."

First table:

```text
award_fact joined to organizations
```

First move:

```sql
SELECT
    o.org_name,
    SUM(af.TotalCosts) AS total_costs
FROM award_fact af
JOIN organizations o
    ON af.ORG_ID = o.organization_id
GROUP BY o.org_name
ORDER BY total_costs DESC;
```

Warning:

```text
Do not join to Award_Investigators unless the question is PI-related.
That can multiply award rows.
```

---

### Shape C: "Which PIs..."

First table:

```text
Award_Investigators bridge
```

Then join:

```text
bridge -> investigators
bridge -> award_fact
```

Question to answer first:

```text
Do I want only contact PIs or all listed PIs?
```

Contact PI funding skeleton:

```sql
SELECT
    i.profile_id,
    i.Full_Name,
    SUM(af.TotalCosts) AS total_costs
FROM Award_Investigators ai
JOIN investigators i
    ON ai.profile_id = i.profile_id
JOIN award_fact af
    ON ai.ApplicationID = af.ApplicationID
WHERE ai.is_contact_pi = 'true'
GROUP BY i.profile_id, i.Full_Name
ORDER BY total_costs DESC;
```

Warning:

```text
If you include all PIs, the same award amount may appear once per PI.
That is fine for participation analysis, but not for unduplicated award totals.
```

---

### Shape D: "Which projects..."

First table:

```text
projects
```

But current `award_fact` does not yet include `Project_ID`, so for now join through raw `core_project_num` or rebuild the fact.

Temporary pattern:

```sql
SELECT
    p.Project_ID,
    p.core_project_num,
    SUM(nan.award_amount) AS total_award_amount
FROM nih_awards_national nan
JOIN projects p
    ON nan.core_project_num = p.core_project_num
GROUP BY p.Project_ID, p.core_project_num
ORDER BY total_award_amount DESC;
```

Better normalized future:

```text
fact_award.project_id -> dim_project.project_id
```

---

### Shape E: "What changed over time..."

First move:

```text
Aggregate to one row per time period and entity.
```

Then:

```text
Use LAG().
```

Skeleton:

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
    ) AS change_from_prior_year
FROM annual;
```

Common mistake:

```text
Trying to use LAG before grouping. Group first, compare second.
```

---

### Shape F: "Is the normalized model correct?"

Reach for validation query sets.

Minimum pattern:

```sql
SELECT 'fact row count' AS test_name,
       COUNT(*) AS observed_value
FROM fact_award

UNION ALL

SELECT 'raw row count',
       COUNT(*)
FROM nih_awards_national;
```

Better pattern:

```text
Each test should return:
test_name, observed_value, expected_value, status
```

Skeleton:

```sql
SELECT
    'fact row count equals raw row count' AS test_name,
    (SELECT COUNT(*) FROM fact_award) AS observed_value,
    (SELECT COUNT(*) FROM nih_awards_national) AS expected_value,
    CASE
        WHEN (SELECT COUNT(*) FROM fact_award)
           = (SELECT COUNT(*) FROM nih_awards_national)
        THEN 'pass'
        ELSE 'fail'
    END AS status;
```

---

## 5. Scaffolded Practice Path

### Level 1: Orientation

Skill:

```text
Know where you are before writing joins.
```

Practice question:

```text
What are the largest tables, and what are their likely grains?
```

Reach for:

```text
duckdb_tables()
DESCRIBE
COUNT(*)
COUNT(DISTINCT key)
```

Hints:

1. Start with table list and row counts.
2. Pick one candidate key per table.
3. Compare total rows to distinct key count.
4. Write the grain in English.

Skeleton:

```sql
SELECT table_name, estimated_size
FROM duckdb_tables()
WHERE schema_name = 'main'
ORDER BY estimated_size DESC;
```

---

### Level 2: Referential Integrity

Skill:

```text
Find missing parent rows.
```

Practice question:

```text
Does every non-null organization key in award_fact resolve to organizations?
```

Reach for:

```text
Anti-join
```

Hints:

1. `award_fact` is the child.
2. `organizations` is the parent.
3. Keep non-null child keys.
4. Missing parent means joined parent key is null.

Skeleton:

```sql
SELECT COUNT(*)
FROM award_fact af
LEFT JOIN organizations o
    ON af.ORG_ID = o.organization_id
WHERE af.ORG_ID IS NOT NULL
  AND o.organization_id IS NULL;
```

Repeat for:

- `award_fact.IC_Code` -> `nih_institutes.agency_ic_admin_code`
- `Award_Investigators.ApplicationID` -> `award_fact.ApplicationID`
- `Award_Investigators.profile_id` -> `investigators.profile_id`

---

### Level 3: Safe Aggregation

Skill:

```text
Aggregate at the right grain without accidental duplication.
```

Practice question:

```text
What are the top 20 organizations by total award amount?
```

Reach for:

```text
Join fact to one-row-per-org dimension, then GROUP BY.
```

Hints:

1. Start from `award_fact`, because the measure lives there.
2. Join `organizations` by `ORG_ID`.
3. Group by org identity and display label.
4. Sort by `SUM(TotalCosts)`.

Skeleton:

```sql
SELECT
    o.organization_id,
    o.org_name,
    SUM(af.TotalCosts) AS total_costs
FROM award_fact af
JOIN organizations o
    ON af.ORG_ID = o.organization_id
GROUP BY o.organization_id, o.org_name
ORDER BY total_costs DESC
LIMIT 20;
```

Check:

```text
Does joining organizations multiply award rows?
```

Use:

```sql
WITH joined AS (
    SELECT af.ApplicationID
    FROM award_fact af
    JOIN organizations o
        ON af.ORG_ID = o.organization_id
)
SELECT
    COUNT(*) AS joined_rows,
    COUNT(DISTINCT ApplicationID) AS distinct_awards
FROM joined;
```

---

### Level 4: Bridge Tables

Skill:

```text
Analyze many-to-many relationships without lying to yourself.
```

Practice question:

```text
Who are the top contact PIs by award amount?
```

Reach for:

```text
Bridge table + contact PI filter + fact join.
```

Hints:

1. Start with `Award_Investigators`.
2. Filter to `is_contact_pi = 'true'`.
3. Join to `award_fact` for dollars.
4. Join to `investigators` for display name.
5. Group by `profile_id`, not just name.

Skeleton:

```sql
SELECT
    i.profile_id,
    i.Full_Name,
    COUNT(DISTINCT af.ApplicationID) AS award_count,
    SUM(af.TotalCosts) AS total_costs
FROM Award_Investigators ai
JOIN investigators i
    ON ai.profile_id = i.profile_id
JOIN award_fact af
    ON ai.ApplicationID = af.ApplicationID
WHERE ai.is_contact_pi = 'true'
GROUP BY i.profile_id, i.Full_Name
ORDER BY total_costs DESC
LIMIT 20;
```

Debug question:

```text
What happens if you remove the contact PI filter?
```

Expected learning:

```text
The result changes from award ownership to award participation.
The same award can contribute to multiple PIs.
```

---

### Level 5: Canonical Rows

Skill:

```text
Pick one best row per entity using explicit business rules.
```

Practice question:

```text
How should dim_investigator choose one display name per profile_id?
```

Reach for:

```text
ROW_NUMBER() with PARTITION BY profile_id.
```

Hints:

1. Identity is `profile_id`.
2. Display name comes from observed award-investigator rows.
3. Latest non-null award notice date wins.
4. Highest `ApplicationID` breaks ties.
5. Null dates go last.

Skeleton:

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

Check:

```text
Does every profile_id appear once?
```

Reach for:

```sql
COUNT(*) vs COUNT(DISTINCT profile_id)
```

---

### Level 6: JSON To Bridge

Skill:

```text
Turn nested source data into relational rows.
```

Practice question:

```text
How do I rebuild Award_Investigators from pis_json?
```

Reach for:

```text
json_each + extract fields + dedupe.
```

Hints:

1. Start from `nih_awards_national`.
2. Cross join to `json_each(nan.pis_json)`.
3. Extract profile/name/contact fields.
4. Remove rows with null `profile_id`.
5. Dedupe `(ApplicationID, profile_id)`.

Skeleton:

```sql
WITH exploded AS (
    SELECT
        nan.appl_id AS ApplicationID,
        pi.key AS pi_position,
        json_extract_string(pi.value, '$.profile_id') AS profile_id,
        upper(json_extract_string(pi.value, '$.last_name')) AS last_name,
        upper(json_extract_string(pi.value, '$.first_name')) AS first_name,
        json_extract_string(pi.value, '$.is_contact_pi')::BOOLEAN AS is_contact_pi
    FROM nih_awards_national nan,
         json_each(nan.pis_json) AS pi
),
ranked AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY ApplicationID, profile_id
            ORDER BY is_contact_pi DESC, pi_position
        ) AS rn
    FROM exploded
    WHERE profile_id IS NOT NULL
)
SELECT *
FROM ranked
WHERE rn = 1;
```

Validation:

```sql
SELECT
    COUNT(*) AS rows,
    COUNT(DISTINCT ApplicationID || '|' || profile_id) AS distinct_pairs
FROM bridge_award_investigator;
```

---

## 6. Drill Cards

Use these like flashcards.

### Card 1

Question:

```text
Is this table one row per ApplicationID?
```

Reach for:

```text
COUNT(*) vs COUNT(DISTINCT ApplicationID)
```

---

### Card 2

Question:

```text
Which raw projects are missing from the project dimension?
```

Reach for:

```text
Anti-join from raw to dimension
```

---

### Card 3

Question:

```text
Why did total funding increase after joining investigators?
```

Reach for:

```text
Join multiplication check
```

Then ask:

```text
Award-level total or PI-participation total?
```

---

### Card 4

Question:

```text
How do I choose the latest record per investigator?
```

Reach for:

```text
ROW_NUMBER() OVER (PARTITION BY profile_id ORDER BY date DESC NULLS LAST)
```

---

### Card 5

Question:

```text
How do I calculate each institute's share of annual funding?
```

Reach for:

```text
SUM(total) OVER (PARTITION BY fiscal_year)
```

---

### Card 6

Question:

```text
How do I compare this year's funding to last year's?
```

Reach for:

```text
GROUP BY year first, then LAG()
```

---

### Card 7

Question:

```text
How do I safely use a source date stored as text?
```

Reach for:

```text
TRY_CAST(text_col AS DATE)
```

---

### Card 8

Question:

```text
How do I extract PIs from pis_json?
```

Reach for:

```text
json_each()
```

---

## 7. The Final Mental Model

When stuck, use this loop:

```text
1. Name the grain I want.
2. Pick the table that naturally has that grain.
3. Identify the measures I need.
4. Identify the attributes I need.
5. Join only the dimensions needed for those attributes.
6. Check whether the join changed the row count.
7. Aggregate only after the row grain is correct.
8. Validate with counts and anti-joins.
```

For this project, the most important sentence is:

```text
Do not join more tables until you know what row grain you currently have.
```

