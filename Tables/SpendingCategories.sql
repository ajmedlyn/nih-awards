CREATE OR REPLACE TABLE award_spending_categories AS
SELECT
    nan.appl_id AS ApplicationID,
    TRY_CAST(sc.value AS INTEGER) AS Spending_Category_ID
FROM nih_awards_national nan,
     json_each(nan.spending_categories_json) AS sc;