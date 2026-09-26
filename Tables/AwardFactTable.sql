-- the purpose of this table is to create an Award Fact from the main NAN table 
-- I created a separate table for organizations
CREATE OR REPLACE TABLE award_fact AS 
SELECT 
   	aw.appl_id AS ApplicationID,
    o.organization_id AS ORG_ID,
    aw.subproject_id AS SubProject_ID,
    aw.core_project_num AS Core_Project_Number,
    p.Project_ID AS Project_ID,
    aw.project_num,
    aw.indirect_cost_amt AS Indirects,
    aw.direct_cost_amt AS Directs,
    aw.award_amount AS TotalCosts,
    aw.project_title,
    aw.fiscal_year AS Federal_Fiscal_Year,
    aw.agency_ic_admin_code AS IC_Code,
    aw.org_type_code,
    aw.org_type_name,
    aw.dept_type,
    aw.agency_code,
    aw.award_type,
	TRY_CAST(aw.award_notice_date AS DATE) AS award_notice_date,
	TRY_CAST(aw.budget_start AS DATE) AS Budget_Start_Date,
	TRY_CAST(aw.budget_end AS DATE) AS Budget_End_Date,
	TRY_CAST(aw.project_start_date AS DATE) AS Project_Start_Date,
	TRY_CAST(Aw.project_end_date AS DATE) AS Project_End_Date,
    aw.activity_code,
    aw.appl_type_code,
    aw.support_year,
    aw.suffix_code
FROM nih_awards.main.nih_awards_national aw	
LEFT JOIN nih_awards.main.organizations o 
    ON aw.org_name IS NOT DISTINCT FROM o.org_name
    AND aw.geo_lat IS NOT DISTINCT FROM o.geo_lat 
    AND aw.geo_lon IS NOT DISTINCT FROM o.geo_lon 
    AND aw.org_duns IS NOT DISTINCT FROM o.org_duns 
    AND aw.org_state IS NOT DISTINCT FROM o.org_state
LEFT JOIN nih_awards.main.projects p
	ON aw.core_project_num = p.core_project_num;