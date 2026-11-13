-- Restaurant: store the Google place it was matched to (the join key between
-- OSM and Google, one restaurant per Google place) and its Google Maps link,
-- and allow Google's FUTURE_OPENING status (listed on Google, not open yet).
BEGIN;

ALTER TABLE public.restaurant
    ADD COLUMN google_place_id varchar(255),
    ADD COLUMN google_maps_uri varchar(500),
    ADD CONSTRAINT uq_restaurant_google_place_id UNIQUE (google_place_id);

ALTER TABLE public.restaurant DROP CONSTRAINT chk_business_status;
ALTER TABLE public.restaurant
    ADD CONSTRAINT chk_business_status
    CHECK (business_status IN ('OPERATIONAL', 'CLOSED_TEMPORARILY', 'PERMANENTLY_CLOSED', 'FUTURE_OPENING'));

COMMIT;
