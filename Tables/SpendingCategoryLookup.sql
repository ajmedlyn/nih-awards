
-- This is a skinny for spending categories the data agent
-- The prupose is to track trends ID as spending categories across fiscal years
CREATE OR REPLACE TABLE spending_categories AS
WITH pairs AS (
    SELECT
        nan.fiscal_year,
        TRY_CAST(sc.value AS INTEGER) AS id,
        trim(replace(string_split(nan.spending_categories_desc, ';')[sc.key::INTEGER + 1], '*', '')) AS name
    FROM nih_awards_national nan,
         json_each(nan.spending_categories_json) AS sc
    WHERE nan.spending_categories_desc IS NOT NULL
)
SELECT
    id   AS Spending_Category_ID,
    name AS Spending_Category_Name
FROM pairs
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY id
    ORDER BY fiscal_year DESC, name
) = 1;