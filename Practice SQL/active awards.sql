SELECT
	nan.agency_ic_admin_name,
	SUM(nan.award_amount) AS TotalAward
FROM nih_awards.main.nih_awards_national nan
WHERE nan.agency_code = 'NIH'
	AND TRY_CAST(nan.project_start_date AS DATE) <= DATE '2024-09-30'
	AND TRY_CAST(nan.project_end_date AS DATE) >= DATE '2023-10-01'
GROUP BY agency_ic_admin_name 