-- Evidence level: how much the AI had to work with when it wrote a restaurant's
-- profile. Set by profile_data.py, never by the AI:
--   high    matched on Google, and the AI read 3 to 5 reviews
--   medium  matched on Google, but fewer than 3 reviews
--   low     no Google match: only OpenStreetMap's name and tags
-- The values are business_profile.evidence_level in src/categories.json (keep
-- the CHECK below in line with it). Empty for rows loaded before this column
-- existed.
BEGIN;

ALTER TABLE public.business_profile
    ADD COLUMN evidence_level varchar(10)
        CONSTRAINT chk_evidence_level
        CHECK (evidence_level IN ('high', 'medium', 'low'));

COMMIT;
