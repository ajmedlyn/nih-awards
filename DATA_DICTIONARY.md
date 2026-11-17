# NIH Awards — Data Dictionary

Every object in the main DuckDB database (`nih_awards.duckdb`; `big_dawg.duckdb` on the work copy), with its grain, keys, how it is built, and what each column means.

- **Row counts and "Filled" percentages** were measured on 2026-11-16 from `nih_awards.duckdb`, after the leftover-batch fix and a full rebuild. "Filled" = share of rows where the column is not NULL. They will drift with each refresh.
- **Build order and design rules** (stable IDs, tie-breaking, known source issues) live in `table documentation.md`. This file describes *what the data means*; that one describes *how it is built*.
- **Source:** NIH RePORTER API v2 (`https://api.reporter.nih.gov/v2/projects/search`). RePORTER covers NIH **and** other HHS/VA agencies — see `agency_code`.

---

## Object map

| Object | Layer | Grain (one row per…) | Rows | Key | Built by |
|---|---|---|---|---|---|
| `nih_awards_national` | Source | application (`appl_id`) | 2,143,532 | `appl_id` | `nih_awards_national_fetch.py`, `nih_awards_national_incremental_2026_fetch.py` |
| `award_fact` | Normalized | application | 2,143,532 | `ApplicationID` | `Tables/AwardFactTable.sql` |
| `organizations` | Normalized | organization location | 20,417 | `organization_id` | `Tables/org table.sql` |
| `projects` | Normalized | core project | 445,875 | `Project_ID` | `Tables/ProjectTable.sql` |
| `Award_Investigators` | Normalized | application × investigator | 2,403,568 | (`ApplicationID`, `profile_id`) | `Tables/award_investigators tbl.sql` |
| `investigators` | Normalized | investigator | 229,689 | `profile_id` | `Tables/Investigators.sql` |
| `award_ic_funding` | Normalized | application × funding institute | 2,135,965 | (`ApplicationID`, `IC_Code`) | `Tables/IC_FundingTable.sql` |
| `award_spending_categories` | Normalized | application × spending category | 7,434,943 | (`ApplicationID`, `Spending_Category_ID`) | `Tables/SpendingCategories.sql` |
| `spending_categories` | Lookup | spending category | 352 | `Spending_Category_ID` | `Tables/SpendingCategoryLookup.sql` |
| `project_titles_main_projects` | Normalized | core project × title | 531,761 | (`Project_ID`, `project_title`) | `Tables/MainProjectTitles.sql` |
| `award_text` | Normalized (work copy only) | application with text | — | `ApplicationID` | `Tables/AwardText.sql` (`--with-text`) |
| `nih_institutes` | Lookup | administering IC code | 87 | `agency_ic_admin_code` | No build script in repo (created by hand) |
| `ucd_awards` | Legacy source | application (UCD/Anschutz only) | 19,416 | `appl_id` | `nih_awards_fetch.py` (writes `ucd_awards.duckdb`; copied in) |
| `_fetch_progress` | Internal | fetch batch | 1,707 | `batch_key` | Both national fetchers |

`award_text` exists only where `refresh_and_normalize.py --with-text` has run (the work copy); the personal and cloud copies don't have it.

### How the tables join

```
nih_awards_national.appl_id ─┬─ award_fact.ApplicationID
                             ├─ Award_Investigators.ApplicationID ── investigators.profile_id
                             ├─ award_ic_funding.ApplicationID
                             ├─ award_spending_categories.ApplicationID ── spending_categories.Spending_Category_ID
                             └─ award_text.ApplicationID

award_fact.ORG_ID       → organizations.organization_id
award_fact.Project_ID   → projects.Project_ID ── project_titles_main_projects.Project_ID
award_fact.IC_Code      → nih_institutes.agency_ic_admin_code
```

`organization_id` and `Project_ID` are rebuilt on every normalize run and can shift when new rows arrive. Join on them inside the database; don't store them elsewhere.

---

## Codes used across tables

**Agency (`agency_code`).** RePORTER is not NIH-only. Filter `agency_code = 'NIH'` for NIH questions.

| Code | Agency | Rows |
|---|---|---|
| NIH | National Institutes of Health | 2,017,697 |
| ALLCDC | Centers for Disease Control and Prevention | 54,658 |
| VA | Department of Veterans Affairs | 26,623 |
| SAMSHA | Substance Abuse and Mental Health Services Administration (NIH's spelling) | 22,267 |
| AHRQ | Agency for Healthcare Research and Quality | 11,802 |
| FDA | Food and Drug Administration | 10,129 |
| ACF | Administration for Children and Families | 316 |
| HRSA | Health Resources and Services Administration | 1 |
| NULL | — | 39 |

**Application / award type (`appl_type_code`, `award_type`).** The leading digit of `project_num`.

| Code | Meaning | Rows |
|---|---|---|
| 1 | New | 471,091 |
| 2 | Competing continuation (renewal) | 129,635 |
| 3 | Competing revision / supplement | 138,570 |
| 4C / 4N | Extension, competing / non-competing | 1,481 / 27,969 |
| 5 | Non-competing continuation (next year of an ongoing award) | 1,304,298 |
| 6 | Change of organization status (successor-in-interest) | 3,948 |
| 7 | Change of grantee or training institution | 34,885 |
| 8 | Change of institute/center, non-competing | 1,564 |
| 9 | Change of institute/center, competing | 1,595 |

**Funding mechanism (`mechanism_code_dc` → `funding_mechanism`).**

| Code | Mechanism | Rows | Has a US state? |
|---|---|---|---|
| RP | Research projects (non-SBIR/STTR) | 1,223,894 | Yes |
| RC | Research centers | 314,220 | Yes |
| OR | Other research-related | 221,604 | Yes |
| TR / TI | Training, individual / institutional | 89,846 / 57,740 | Yes |
| IM | Intramural research (NIH's own labs) | 78,589 | **No** — fetched by the `IM` batch |
| SB | SBIR/STTR small-business grants | 51,550 | Yes |
| NSRDC / SRDC | R&D contracts (non-SBIR / SBIR) | 27,127 / 1,535 | Mostly; leftovers fetched by the `NSRDC` batch |
| IAA | Interagency agreements | 2,804 | **No** — fetched by the `IAA` batch |
| CO | Construction grants | 892 | Yes |
| UK / OT / CP | Other | 58,513 / 11,333 / 1,088 | Yes |

---

## `nih_awards_national` — source table

One row per NIH application (`appl_id`) as returned by RePORTER. An *application* is one award action in one fiscal year: a five-year R01 normally appears as five rows sharing a `core_project_num`. Rows are upserted on `appl_id` and never deleted, so a few awards NIH has since withdrawn remain.

**Fetch coverage:** FY2000–FY2027. Each fiscal year is fetched by state, then by the no-state mechanisms (`IM`, `IAA`, `NSRDC`), then by foreign country. About 1,600 rows across all years are still missing versus NIH's totals; see Known gaps.

**Identifiers and project number**

| Column | Type | Filled | Description |
|---|---|---|---|
| `appl_id` | BIGINT | 100% | NIH application ID. Primary key. |
| `subproject_id` | VARCHAR | 17.9% | Component number within a multi-project award (centers, program projects). NULL for the parent award and for single-project awards. |
| `fiscal_year` | INTEGER | 100% | NIH fiscal year of the award (Oct 1 – Sep 30; FY2027 began 2026-10-01). |
| `project_num` | VARCHAR | 100% | Full project number, e.g. `5K08CA087901-03` = type `5` + activity `K08` + IC `CA` + serial `087901` + support year `03`. |
| `project_serial_num` | VARCHAR | **0%** | Always empty: the field isn't requested from the API. Use `serial_num`. |
| `core_project_num` | VARCHAR | 100% | Project number without type, year or suffix, e.g. `K08CA087901`. The same across every year of a project; the grain of `projects`. |
| `activity_code` | VARCHAR | 100% | Grant type, e.g. `R01`, `K08`, `P30`, `ZIA` (intramural). |
| `activity_code_split` | VARCHAR | 98.5% | Activity code parsed out of `project_num`. Normally equals `activity_code`. |
| `ic_code` | VARCHAR | 98.5% | Two-letter institute code parsed out of `project_num`, e.g. `CA` = NCI. |
| `serial_num` | VARCHAR | 98.5% | Serial-number part of `project_num`. |
| `support_year` | VARCHAR | 98.5% | Year of support, e.g. `03` = third year. Text, keeps leading zeros. |
| `suffix_code` | VARCHAR | 98.5% | Suffix such as `S1` (supplement) or `A1` (amended application); empty string when none. |
| `appl_type_code` | VARCHAR | 98.5% | Application type parsed out of `project_num`. See codes above. |
| `award_type` | VARCHAR | 98.7% | Application type as reported by RePORTER. Same codes. |
| `mechanism_code_dc` | VARCHAR | 99.9% | Funding mechanism code. See codes above. |
| `funding_mechanism` | VARCHAR | 99.9% | Funding mechanism name. |

**Money** (US dollars, for this application in this fiscal year)

| Column | Type | Filled | Description |
|---|---|---|---|
| `award_amount` | BIGINT | 96.8% | Total cost awarded (direct + indirect). Use for award totals. |
| `direct_cost_amt` | BIGINT | 92.0% | Direct costs. |
| `indirect_cost_amt` | BIGINT | 84.4% | Indirect (facilities and administrative) costs. |
| `agency_ic_fundings_json` | VARCHAR | 100% | JSON array, one entry per funding institute: `fy`, `code`, `name`, `total_cost`, `direct_cost_ic`, `indirect_cost_ic`. Normalized into `award_ic_funding`. Use that table for totals by institute. |

**Dates** (stored as text, e.g. `2013-08-09T00:00:00`; `award_fact` casts them to DATE)

| Column | Type | Filled | Description |
|---|---|---|---|
| `award_notice_date` | VARCHAR | 87.7% | Date of the Notice of Award. |
| `budget_start`, `budget_end` | VARCHAR | 93.9% | Budget period this year's money covers. |
| `project_start_date`, `project_end_date` | VARCHAR | 89.4%, 89.6% | Whole project period across all years. |
| `date_added` | VARCHAR | 100% | When the record was added to RePORTER. |

**Administering and funding agency**

| Column | Type | Filled | Description |
|---|---|---|---|
| `agency_code` | VARCHAR | 100% | Funding agency: `NIH`, `ALLCDC`, `VA`, … See codes above. |
| `agency_ic_admin_code` | VARCHAR | 100% | Administering institute/center code, e.g. `CA`. Joins to `nih_institutes`. |
| `agency_ic_admin_abbrev` | VARCHAR | 100% | Its abbreviation, e.g. `NCI`. |
| `agency_ic_admin_name` | VARCHAR | 100% | Its full name. |
| `cfda_code` | VARCHAR | 80.8% | Assistance Listing (CFDA) number, e.g. `93.397`. |
| `opportunity_number` | VARCHAR | 70.1% | Funding opportunity the application answered, e.g. `PAR-97-031`. |
| `arra_funded` | VARCHAR | 91.4% | `Y`/`N`: funded by the 2009 Recovery Act. |
| `covid_response` | VARCHAR | 0.2% | COVID-19 funding codes, e.g. `[Reg-CV]`. NULL for unrelated awards. |
| `is_active` | BOOLEAN | 100% | RePORTER's "active project" flag as of the last fetch of this row. |
| `is_new` | BOOLEAN | 100% | RePORTER's "new project" flag as of the last fetch of this row. |

**Organization**

| Column | Type | Filled | Description |
|---|---|---|---|
| `org_name` | VARCHAR | 99.8% | Recipient organization. For intramural awards, the NIH division. |
| `org_city` | VARCHAR | 8.5% | City. **Only filled for rows fetched after the 2026-11-16 fix.** |
| `org_state` | VARCHAR | 95.2% | US state/territory code. Foreign organizations carry their own region code (e.g. `ON` = Ontario); NULL for intramural and interagency awards. |
| `org_country` | VARCHAR | 12.4% | Country, e.g. `UNITED STATES`. Same caveat as `org_city`. |
| `org_duns` | VARCHAR | 95.1% | DUNS number(s), stored as list text: `[063690705]`. The stable organization ID for older years. |
| `org_uei` | VARCHAR | 8.1% | Unique Entity ID (replaced DUNS in 2022). Same caveat as `org_city`. |
| `dept_type` | VARCHAR | 60.3% | Department type, e.g. `PATHOLOGY`. |
| `org_type_name` | VARCHAR | 100% | Organization type, e.g. `SCHOOLS OF MEDICINE`. |
| `org_type_code` | VARCHAR | 95.0% | Code for `org_type_name`. |
| `geo_lat`, `geo_lon` | DOUBLE | 96.0% | Geocoded location. |
| `cong_dist` | VARCHAR | 94.9% | Congressional district, e.g. `AL-07`. |

**People and review**

| Column | Type | Filled | Description |
|---|---|---|---|
| `contact_pi_name` | VARCHAR | 99.7% | Contact principal investigator, `LAST, FIRST`. |
| `pi_names` | VARCHAR | 100% | All PI names, pipe-separated (` \| `). |
| `pi_profile_ids` | VARCHAR | 100% | All PI profile IDs, pipe-separated, in the same order. |
| `pis_json` | VARCHAR | 100% | JSON array of PIs with `profile_id`, names, `is_contact_pi`. Source of truth; normalized into `Award_Investigators`. |
| `program_officers` | VARCHAR | 100% | NIH program officer(s), `LAST, FIRST`. Empty string on 568,712 rows. |
| `study_section_code` | VARCHAR | 93.0% | Peer-review group code. |
| `study_section_name` | VARCHAR | 93.0% | Peer-review group name. |

**Text and topics**

| Column | Type | Filled | Description |
|---|---|---|---|
| `project_title` | VARCHAR | 100% | Title of this application. Can change between years of a project. |
| `abstract_text` | VARCHAR | 86.6% | Scientific abstract written by the applicants. Not fetched by default (`--include-text`). |
| `phr_text` | VARCHAR | 48.5% | Public health relevance statement: a short plain-language "why it matters". Not fetched by default. |
| `terms` | VARCHAR | 84.5% | Every thesaurus synonym of the award's concepts, `<like><this>`. Large and redundant; not used downstream. |
| `pref_terms` | VARCHAR | 84.4% | One preferred name per concept, semicolon-separated. |
| `spending_categories_desc` | VARCHAR | 58.6% | NIH spending (RCDC) category names, semicolon-separated. Names can carry `*` markers, which the lookup strips. NULL until NIH assigns categories, roughly the year after the fiscal year closes. |
| `spending_categories_json` | VARCHAR | 100% | JSON array of category IDs, e.g. `[132]`, in the same order as the names. `{}` when there are none (886,526 rows). Normalized into `award_spending_categories`. |
| `project_detail_url` | VARCHAR | 100% | Link to the award on RePORTER. |

---

## `award_fact`

One row per application; the main fact table. Every row of `nih_awards_national` appears once. Dates are cast from text to DATE with `TRY_CAST`; the refresh's check step confirms no dates were lost.

| Column | Type | Filled | Source / description |
|---|---|---|---|
| `ApplicationID` | BIGINT | 100% | `appl_id`. Primary key. |
| `ORG_ID` | BIGINT | 99.9% | → `organizations.organization_id`. NULL (2,655 rows) when the source has neither org name nor DUNS. |
| `SubProject_ID` | VARCHAR | 17.9% | `subproject_id`. |
| `Core_Project_Number` | VARCHAR | 100% | `core_project_num`. |
| `Project_ID` | BIGINT | 100% | → `projects.Project_ID`. NULL for 72 rows: no core project number, or a subproject whose parent has no main record. |
| `project_num` | VARCHAR | 100% | `project_num`. |
| `Indirects` | BIGINT | 84.4% | `indirect_cost_amt`. |
| `Directs` | BIGINT | 92.0% | `direct_cost_amt`. |
| `TotalCosts` | BIGINT | 96.8% | `award_amount`. Use this for award totals. |
| `project_title` | VARCHAR | 100% | `project_title`. |
| `Federal_Fiscal_Year` | INTEGER | 100% | `fiscal_year`. |
| `IC_Code` | VARCHAR | 100% | `agency_ic_admin_code`: the **administering** IC only. For dollars by institute use `award_ic_funding`. |
| `org_type_code`, `org_type_name`, `dept_type` | VARCHAR | 95.0%, 100%, 60.3% | As in the source. |
| `agency_code` | VARCHAR | 100% | As in the source. Filter `= 'NIH'` for NIH-only questions. |
| `award_type`, `appl_type_code` | VARCHAR | 98.7%, 98.5% | As in the source. See codes above. |
| `award_notice_date` | DATE | 87.7% | Cast from source. |
| `Budget_Start_Date`, `Budget_End_Date` | DATE | 93.9% | Cast from `budget_start`, `budget_end`. |
| `Project_Start_Date`, `Project_End_Date` | DATE | 89.4%, 89.6% | Cast from `project_start_date`, `project_end_date`. |
| `activity_code` | VARCHAR | 100% | As in the source. |
| `support_year`, `suffix_code` | VARCHAR | 98.5% | As in the source. |

## `organizations`

One row per distinct (`org_name`, `org_duns`, `org_state`, `geo_lat`, `geo_lon`): an organization **location**, not a legal entity. The same university can appear more than once if NIH geocoded it differently. Excludes rows with neither name nor DUNS.

| Column | Type | Filled | Description |
|---|---|---|---|
| `organization_id` | BIGINT | 100% | Surrogate key, stable for the same data but can shift when new organizations arrive. |
| `org_name` | VARCHAR | 98.7% | Organization name. A few are NIH placeholder text, e.g. `*(FY18 USE 10048472)`. |
| `org_duns` | VARCHAR | 74.7% | DUNS list text. |
| `org_state` | VARCHAR | 91.6% | State/region code. |
| `geo_lat`, `geo_lon` | DOUBLE | 96.7% | Location. |

## `projects`

One row per `core_project_num`, built from main (non-subproject) records only.

| Column | Type | Filled | Description |
|---|---|---|---|
| `Project_ID` | BIGINT | 100% | Surrogate key, ordered by `core_project_num`. |
| `core_project_num` | VARCHAR | 100% | Core project number. |
| `First_Fiscal_Year`, `Last_Fiscal_Year` | INTEGER | 100% | First and last fiscal year the project appears. |
| `ProjectStart`, `ProjectEnd` | DATE | 96.6%, 95.7% | Earliest project start and latest project end across its years. |

## `Award_Investigators`

One row per application per investigator, from `pis_json`. PIs without a `profile_id` are excluded.

| Column | Type | Filled | Description |
|---|---|---|---|
| `ApplicationID` | BIGINT | 100% | → `award_fact.ApplicationID`. |
| `profile_id` | VARCHAR | 100% | NIH PI profile ID. → `investigators.profile_id`. |
| `Last_Name`, `First_Name` | VARCHAR | 100% | Uppercased, as reported on this application. |
| `Full_Name` | VARCHAR | 100% | `LAST, FIRST`. |
| `is_contact_pi` | BOOLEAN | 100% | TRUE for the application's contact PI (exactly one per application). |

## `investigators`

One row per `profile_id`, with one display name: the name from the investigator's most recent award (ties → highest `ApplicationID`). Different profile IDs are never merged, even when names match.

| Column | Type | Filled | Description |
|---|---|---|---|
| `profile_id` | VARCHAR | 100% | Primary key. |
| `Full_Name`, `Last_Name`, `First_Name` | VARCHAR | 100% | Display name. |
| `ApplicationID` | BIGINT | 100% | The application the display name came from. |

## `award_ic_funding`

One row per application per funding institute, from `agency_ic_fundings_json`. About 40K awards are co-funded, so **totals by institute should come from this table**, not `award_fact.IC_Code`.

| Column | Type | Filled | Description |
|---|---|---|---|
| `ApplicationID` | BIGINT | 100% | → `award_fact.ApplicationID`. |
| `IC_Code` | VARCHAR | 100% | Funding institute code. |
| `Institute` | VARCHAR | 100% | Funding institute name. |
| `Fiscal_Year` | INTEGER | 100% | Fiscal year of this institute's funding. |
| `IC_TotalCost` | DOUBLE | 100% | This institute's share of total cost. |
| `IC_DirectCost`, `IC_InDirectCost` | DOUBLE | 95.1%, 87.1% | Its direct / indirect share. |

## `award_spending_categories`

One row per application per NIH spending (RCDC) category. Awards without categories have no rows. Before about FY2008, and for the most recent fiscal year until NIH assigns them, there are none.

| Column | Type | Filled | Description |
|---|---|---|---|
| `ApplicationID` | BIGINT | 100% | → `award_fact.ApplicationID`. |
| `Spending_Category_ID` | INTEGER | 100% | → `spending_categories.Spending_Category_ID`. |

## `spending_categories`

One row per spending-category ID, pairing IDs with names from the source. When a category was renamed, the most recent fiscal year's name wins.

| Column | Type | Filled | Description |
|---|---|---|---|
| `Spending_Category_ID` | INTEGER | 100% | Primary key. |
| `Spending_Category_Name` | VARCHAR | 100% | Category name, e.g. `Agent Orange & Dioxin`. |

## `project_titles_main_projects`

One row per core project per distinct title, from main (non-subproject) records. Shows how a project's title changed over its life.

| Column | Type | Filled | Description |
|---|---|---|---|
| `project_title` | VARCHAR | 100% | A title used by the project. |
| `Project_ID` | BIGINT | 100% | → `projects.Project_ID`. |
| `core_project_num` | VARCHAR | 100% | Core project number. |
| `TitleCount` | BIGINT | 100% | How many applications used this title. |

## `award_text` (work copy only)

One row per application that has an abstract or public health relevance text. Abstracts repeat across a project's continuation years (about 1.54M main-project applications share about 631K distinct abstracts).

| Column | Type | Description |
|---|---|---|
| `ApplicationID` | BIGINT | → `award_fact.ApplicationID`. |
| `abstract_text` | VARCHAR | Scientific abstract. |
| `phr_text` | VARCHAR | Public health relevance statement. |

## `nih_institutes`

Lookup of administering-institute codes to names, 87 rows covering NIH and the other agencies in RePORTER. **No build script in the repo**: it was created by hand and is not rebuilt by the refresh.

| Column | Type | Filled | Description |
|---|---|---|---|
| `agency_ic_admin_code` | VARCHAR | 100% | IC code, e.g. `EY`. |
| `agency_code` | VARCHAR | 95.4% | Agency, e.g. `NIH`, `ALLCDC`. |
| `agency_ic_admin_abbrev` | VARCHAR | 100% | Abbreviation, e.g. `NEI`. |
| `agency_ic_admin_name` | VARCHAR | 95.4% | Full name. |

## `ucd_awards` (legacy)

University of Colorado Denver / Anschutz awards only, 19,416 rows, from the earlier `nih_awards_fetch.py`. Same columns as `nih_awards_national`, with these differences: `project_serial_num` is filled (99.8%), and `org_city`, `org_country` and `org_uei` are empty (0%). Not refreshed by the current pipeline. The national table now contains the same awards.

## `_fetch_progress` (internal)

Bookkeeping for the fetchers' resume mode. One row per batch, keyed `<label>_<fiscal year>`: a state (`CA_2009`), a mechanism (`IM_2009`), `FOREIGN_2009`, or the retired `INTL_2009`.

| Column | Type | Description |
|---|---|---|
| `batch_key` | VARCHAR | Batch label and fiscal year. Primary key. |
| `total`, `fetched` | INTEGER | Records fetched for the batch. |
| `completed` | BOOLEAN | TRUE once the batch finished; resume mode skips these. |
| `updated_at` | TIMESTAMP | When the batch last ran. |

---

## Known gaps

| Gap | Effect | Status |
|---|---|---|
| ~1,600 awards still missing versus NIH's totals (FY2000: 356; FY2016–2022: 3–7 per year) | Totals slightly low | Small groups the batches don't cover yet; not investigated |
| `org_city`, `org_country`, `org_uei` empty on rows fetched before 2026-11-16 | Can't filter by city/country on older rows | Fixed for new fetches; old rows need a full re-pull |
| `project_serial_num` always empty | — | Field not requested; use `serial_num` |
| ~6% of rows are non-NIH agencies | Inflates "NIH" totals unless filtered | Filter `agency_code = 'NIH'` |
| 92 awards where `award_ic_funding` doesn't sum to `TotalCosts`; 45 with IC rows but NULL `TotalCosts` | Small institute/award mismatches | NIH source errors; documented in `table documentation.md` |
| FY2026 spending categories not yet published | Category questions empty for FY2026 | Fills in as NIH assigns them; the incremental re-pulls the prior year |
| Text missing for FY2000 and the 2026-11-16 leftover rows on the personal copy | `award_text` gaps for those rows | Backfill later if needed |
| Rows withdrawn by NIH are never deleted | FY2025–2026 have ~35–52 more rows than NIH reports | By design (upsert, no delete) |
| `nih_institutes` has no build script | Can't be recreated from the repo | Add a script |
