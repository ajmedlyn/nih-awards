CREATE OR REPLACE TABLE investigators AS
WITH cte AS(
	SELECT 
		ai.profile_id,
		ai.Full_Name,
		ai.Last_Name,
		ai.First_Name,
		ai.ApplicationID,
		ROW_NUMBER() OVER (
			PARTITION BY ai.profile_id
			ORDER BY 
				af.award_notice_date DESC NULLS LAST,
				ai.ApplicationID DESC
				) AS name_rank
		FROM nih_awards.main.award_fact af 
		INNER JOIN nih_awards.main.Award_Investigators ai 
			ON ai.ApplicationID = af.ApplicationID 
			)
SELECT 
	profile_id,
	Full_Name,
	Last_Name,
	First_Name,
	ApplicationID
FROM cte
WHERE name_rank = 1;