-- geo_lat/geo_lon break ties so IDs are stable across rebuilds
-- (6 name/state/DUNS groups have multiple locations, all with null DUNS)
-- THis builds an org table using DUNS and NAME and State from the main table.


CREATE OR REPLACE TABLE organizations AS
SELECT
    ROW_NUMBER() OVER (
        ORDER BY org_name, org_state, org_duns, geo_lat, geo_lon -- the pratical change is a tie breaker that only impacts a few records
    ) AS organization_id,
    org_name,
    org_duns,
    org_state,
    geo_lat,
    geo_lon
FROM (
    SELECT DISTINCT
        org_name,
        org_duns,
        org_state,
        geo_lat,
        geo_lon
    FROM nih_awards_national
    WHERE NOT (
        org_name IS NULL
        AND org_duns IS NULL
    )
) orgs;