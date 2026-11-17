CREATE OR REPLACE TABLE project_titles_main_projects AS
SELECT DISTINCT
	nan.project_title,
	p.Project_ID,
	p.core_project_num,
	COUNT(*) AS TitleCount
FROM nih_awards_national nan
INNER JOIN projects p 
	ON nan.core_project_num = p.core_project_num
WHERE nan.project_title IS NOT NULL
	AND nan.subproject_id IS NULL
GROUP BY p.Project_ID, nan.project_title, p.core_project_num;