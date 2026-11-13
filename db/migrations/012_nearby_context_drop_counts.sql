-- Nearby context: remove the three counts added by 011 (apartments_500m,
-- bus_stops_500m, mosques_500m). They did not help: almost every restaurant
-- has bus stops, apartment counts are buildings rather than homes, and most
-- "mosques" were surau. The table was empty when this was written, so no data
-- is lost.
BEGIN;

ALTER TABLE public.nearby_context
    DROP COLUMN apartments_500m,
    DROP COLUMN bus_stops_500m,
    DROP COLUMN mosques_500m;

COMMIT;
