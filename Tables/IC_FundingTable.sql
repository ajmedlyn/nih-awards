-- table purpose: create a table of IC funding by institute and fiscal year

CREATE OR REPLACE TABLE award_ic_funding AS
SELECT 
	nan.appl_id AS ApplicationID,
	json_extract_string(ic.value, '$.code') AS IC_Code,
	json_extract_string(ic.value, '$.name') AS Institute,
	CAST(json_extract_string(ic.value, '$.fy') AS INTEGER) AS Fiscal_Year,
	CAST(json_extract_string(ic.value, '$.total_cost') AS DOUBLE) AS IC_TotalCost,
	CAST(json_extract_string(ic.value, '$.direct_cost_ic') AS DOUBLE) AS IC_DirectCost,
	CAST(json_extract_string(ic.value, '$.indirect_cost_ic') AS DOUBLE) AS IC_InDirectCost
FROM nih_awards.main.nih_awards_national nan, 
	json_each(nan.agency_ic_fundings_json) AS IC
