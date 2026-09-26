WITH cte AS(
	SELECT
	nan.contact_pi_name,
	SUM(nan.award_amount) AS total_award_amount
	FROM nih_awards.main.nih_awards_national nan
	WHERE nan.contact_pi_name IS NOT NULL
	GROUP BY nan.contact_pi_name
),
ranked AS (
	SELECT 
	contact_pi_name,
	total_award_amount,
		ROW_NUMBER() OVER (
		ORDER BY total_award_amount DESC
		) as rn 
		FROM cte
	)
SELECT *
FROM ranked 
WHERE rn <= 10;
