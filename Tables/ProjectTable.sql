CREATE OR REPLACE TABLE projects AS
SELECT
    row_number() OVER (
        ORDER BY core_project_num
    ) AS Project_ID,
    core_project_num,
    First_Fiscal_Year,
    Last_Fiscal_Year,
    ProjectStart,
    ProjectEnd
FROM (
    SELECT
        nan.core_project_num,
        MIN(nan.fiscal_year) AS First_Fiscal_Year,
        MAX(nan.fiscal_year) AS Last_Fiscal_Year,
        MIN(TRY_CAST(nan.project_start_date AS DATE)) AS ProjectStart,
        MAX(TRY_CAST(nan.project_end_date AS DATE)) AS ProjectEnd
    FROM nih_awards.main.nih_awards_national nan
    WHERE nan.subproject_id IS NULL
      AND nan.core_project_num IS NOT NULL
    GROUP BY nan.core_project_num
) project_base;