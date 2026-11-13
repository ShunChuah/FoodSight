-- Nearby context: three more counts, all within 500 m of the restaurant's pin.
--   apartments_500m  apartment and condominium buildings (high-rise housing;
--                    buildings, not homes or people)
--   bus_stops_500m   bus stops
--   mosques_500m     mosques and surau (a hint of halal demand, not of
--                    whether the restaurant is halal)
-- Their OSM labels are in nearby.kind in src/categories.json. The table was
-- empty when this was written; a row already there would get 0 for all three.
BEGIN;

ALTER TABLE public.nearby_context
    ADD COLUMN apartments_500m integer NOT NULL DEFAULT 0 CHECK (apartments_500m >= 0),
    ADD COLUMN bus_stops_500m  integer NOT NULL DEFAULT 0 CHECK (bus_stops_500m >= 0),
    ADD COLUMN mosques_500m    integer NOT NULL DEFAULT 0 CHECK (mosques_500m >= 0);

COMMIT;
