SELECT
    fiscal_year,
    agency_ic_admin_abbrev AS ic,
    strftime(award_notice_date::TIMESTAMP, '%Y-%m') AS month,
    COUNT(*) AS n_awards,
    SUM(award_amount) AS monthly_funding,
    SUM(SUM(award_amount)) OVER (
        PARTITION BY fiscal_year, agency_ic_admin_abbrev
        ORDER BY strftime(award_notice_date::TIMESTAMP, '%Y-%m')
    ) AS running_total
FROM nih_awards_national
WHERE award_notice_date IS NOT NULL
    AND agency_code = 'NIH'
    AND fiscal_year BETWEEN 2020 AND 2026
GROUP BY fiscal_year, agency_ic_admin_abbrev, month
ORDER BY fiscal_year, agency_ic_admin_abbrev, month;