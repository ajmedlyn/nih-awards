-- Creates an award investigator table: one row per investigator per application (ties back to ApplicationID).
-- Lists all investigators from the pis_json column of nih_awards_national.
-- is_contact_pi is a boolean that marks the contact PI.
-- NIH sometimes lists the same person twice on one application (once as contact PI, once not).
-- bool_or collapses these to one row and keeps TRUE, since each application has exactly one contact PI.
-- PIs with no profile_id are excluded.
CREATE OR REPLACE TABLE Award_Investigators AS
SELECT
    nan.appl_id AS ApplicationID,
    json_extract_string(pi.value, '$.profile_id') AS profile_id,
	upper(json_extract_string(pi.value, '$.last_name')) AS Last_Name,
	upper(json_extract_string(pi.value, '$.first_name')) AS First_Name,
	COALESCE(upper(json_extract_string(pi.value, '$.last_name')), '') || ', ' ||
	COALESCE(upper(json_extract_string(pi.value, '$.first_name')), '') AS Full_Name, -- may revist later and build in middle initial
	bool_or(json_extract_string(pi.value, '$.is_contact_pi') = 'true') AS is_contact_pi 
FROM nih_awards.main.nih_awards_national nan,
     json_each(nan.pis_json) AS pi
WHERE json_extract_string(pi.value, '$.profile_id') IS NOT NULL -- maybe revisit and do a case statement later on but this is MVP
GROUP BY ALL;