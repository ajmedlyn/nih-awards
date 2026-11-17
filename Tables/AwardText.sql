-- Award text: abstract and public health relevance (PHR) text, one row per application.
-- Local/work copy only: refresh_and_normalize.py builds this table only with --with-text,
-- so the cloud copy stays text-free.
-- Abstracts repeat across continuation years of a project; deduplicating is a later option.
-- terms and pref_terms are intentionally left out.
CREATE OR REPLACE TABLE award_text AS
SELECT
    nan.appl_id AS ApplicationID,
    nan.abstract_text,
    nan.phr_text
FROM nih_awards_national nan
WHERE nan.abstract_text IS NOT NULL
   OR nan.phr_text IS NOT NULL;
