SELECT 
    fiscal_year, 
    award_type,
	award_notice_date,
    COUNT(*) as grant_count,
    SUM(award_amount) as total_dollars
FROM main.nih_awards_national
WHERE award_type IN ('1','5','2')
	AND agency_code = 'NIH'
	AND fiscal_year IN (2024, 2026)
GROUP BY fiscal_year, award_type, award_notice_date 
ORDER BY fiscal_year desc, award_type, award_notice_date;