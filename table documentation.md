NIH Awards normalized schema
Source: nih_awards_national (one row per NIH application, ~1.98M rows).
All tables are rebuilt from the source with CREATE OR REPLACE.


Build order:
Scripts live in Tables/. Run in this order, because later tables store IDs
created by earlier ones.
1. org table.sql                  -> organizations
2. ProjectTable.sql               -> projects
3. AwardFactTable.sql             -> award_fact (uses organization_id, Project_ID)
4. award_investigators tbl.sql    -> Award_Investigators
5. Investigators.sql              -> investigators (uses award_fact, Award_Investigators)
6. IC_FundingTable.sql            -> award_ic_funding
7. SpendingCategories.sql         -> award_spending_categories
8. SpendingCategoryLookup.sql     -> spending_categories (ID -> name lookup)
9. MainProjectTitles.sql          -> project_titles_main_projects (uses projects)
10. AwardText.sql                 -> award_text (local/work copy only, --with-text)

refresh_and_normalize.py runs these in this order in one transaction, after
the incremental fetch succeeds. Keep its BUILD_ORDER in sync with this list.

If organizations or projects is rebuilt, award_fact must be rebuilt after it.


Date handling:
Source dates are VARCHAR. Scripts use TRY_CAST so one malformed NIH record
cannot fail the rebuild. Check after each rebuild that no dates were lost:
count rows where the source date is not null but TRY_CAST(... AS DATE) is null.
Expected result: 0.


Organizations table grain:
One row per distinct org_name, org_duns, org_state, geo_lat, geo_lon.

Identity rule:
An organization is one location, not one legal entity. The same name and DUNS
can appear more than once when NIH geocoded it at different coordinates.

Stable IDs:
organization_id comes from ROW_NUMBER ordered by all five columns, so IDs are
the same on every rebuild of the same data. New organizations can shift IDs,
so do not store organization_id outside this database.

Excluded rows:
Records with both org_name and org_duns null are excluded. 562 award_fact
rows have no ORG_ID for this reason.


Projects table grain:
One row per core_project_num.

Subprojects:
Only non-subproject records (subproject_id is null) are used to build projects.
146 award_fact rows have no Project_ID: 11 have no core_project_num, and 135
are subprojects whose core project has no main (non-subproject) record.
Known gap, accepted for MVP.


Award fact table grain:
One row per ApplicationID. Joins to organizations and projects.

Subprojects and dollar totals:
A parent award's amount already includes its subprojects, and each subproject
also has its own row and amount. is_subproject (award_fact, award_ic_funding)
flags those rows; filter NOT is_subproject for dollar totals or they come out
about 10% high.
IC_Code is the administering institute only. Use award_ic_funding to split
dollars across co-funding institutes.


Award IC funding table grain:
One row per ApplicationID per funding institute (IC_Code).

Co-funding:
~40K awards are funded by more than one institute. Totals by institute should
use this table, not award_fact.IC_Code.

Known source issues:
For 92 awards, the sum of IC_TotalCost does not match award_fact.TotalCosts
because of NIH source data errors (e.g., amounts off by ~100x, or award totals
exactly $10M higher than the IC total). 45 awards have IC funding rows but a
null TotalCosts. Use award_fact.TotalCosts for award totals.


Award spending categories table grain:
One row per ApplicationID per Spending_Category_ID.
~1.14M awards have at least one category. Verified: no duplicates, no null IDs.

Category names:
The source stores category IDs in spending_categories_json and names in
spending_categories_desc. SpendingCategoryLookup.sql pairs them into
spending_categories (one row per Spending_Category_ID), keeping the name from
the most recent fiscal year.


Award investigators table grain:
One row per ApplicationID per profile_id.

Contact PI:
NIH sometimes lists the same person twice on one application, once as contact
PI and once not. bool_or collapses these to one row and keeps TRUE, since each
application has exactly one contact PI.


Investigators table grain:
One row per NIH PI profile_id.

Display-name rule:
An investigator may have multiple observed name variants across award records.
The investigator's display name is selected from the observation with the most
recent non-null award_notice_date.

Tie-breaking:
If multiple observations share the same latest award_notice_date, the observation
with the highest ApplicationID is selected to ensure deterministic results.

Null dates:
Observations with null award_notice_date are ranked after dated observations.
If an investigator has only null dates, the highest ApplicationID is selected.

Identity rule:
profile_id defines investigator identity. Different profile IDs are not merged,
even when names appear to refer to the same person.

History:
The award_investigators table retains the name reported on each application.
The investigators table stores only the selected display name.

Missing IDs:
PI JSON objects with null profile_id and blank names are excluded from
award_investigators and investigators.


Award text table grain:
One row per ApplicationID that has an abstract or public health relevance text.
Built only on the local/work copy (refresh_and_normalize.py --with-text); the
cloud copy skips it for space. terms and pref_terms are not included.
Abstracts repeat across continuation years of a project (about 1.54M main-project
applications share about 631K distinct abstracts). Deduplicating into an
abstracts table plus a mapping table is a later option if disk gets tight.
