-- Restaurant: osm_type, the kind of OpenStreetMap object the restaurant is:
-- node (a point) or way (an outline, such as a building; its pin is the
-- outline's centre). On the 3 November data 919 restaurants are nodes and 41
-- are ways. OpenStreetMap numbers nodes, ways and relations separately, so
-- osm_id alone does not say which object it is; with osm_type a restaurant
-- opens at openstreetmap.org/{osm_type}/{osm_id}, like public.nearby_place.
--
-- The CHECK is the same as nearby_place.osm_type (migration 014):
-- OpenStreetMap's own three types, not a list in src/categories.json.
-- osm_id stays the restaurant's unique key (the caches and the override file
-- use it).
--
-- NOT NULL: run this on an EMPTY restaurant table (empty the pipeline tables
-- first, then reload from run_3_merging.py). On a filled table it stops with
-- "column "osm_type" of relation "restaurant" contains null values" and
-- changes nothing.
BEGIN;

ALTER TABLE public.restaurant
    ADD COLUMN osm_type varchar(10) NOT NULL CHECK (osm_type IN ('node', 'way', 'relation'));

COMMIT;
