-- The allowed values of every list in src/categories.json are checked by the
-- validator only (validate_data.py and foodsight_schema.json, "values_from"),
-- so a list can change in that file alone, with no migration. This drops the
-- eight database copies of those lists.
--
-- Kept, because they copy no list: the number rules (counts and distances
-- >= 0, ratings 1 to 5, cuisine rank 1 to 3, dish price > 0), the OSM
-- element types (node, way, relation), and "a station has a type, nothing
-- else does".
BEGIN;

ALTER TABLE public.restaurant       DROP CONSTRAINT chk_business_status;
ALTER TABLE public.price_range      DROP CONSTRAINT chk_tier;
ALTER TABLE public.business_profile DROP CONSTRAINT business_profile_halal_status_check,
                                    DROP CONSTRAINT chk_evidence_level;
ALTER TABLE public.review           DROP CONSTRAINT chk_sentiment;
ALTER TABLE public.nearby_context   DROP CONSTRAINT chk_station_type;
ALTER TABLE public.nearby_place     DROP CONSTRAINT chk_nearby_place_kind,
                                    DROP CONSTRAINT chk_nearby_place_station_type;

COMMIT;
