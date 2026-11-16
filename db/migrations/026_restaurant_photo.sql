-- Restaurants: Google's first photos of each matched restaurant (up to 3, in Google's
-- order), the image itself stored here. Downloaded in stage 1
-- (src/s1_scrapers/extract_photos.py, kept as files in data/cache/photos/) and copied
-- here by stage 7 (load_data.py, sync_photos()). google_place_id is the Google place
-- the photo came from: when a restaurant's Google match changes, stage 7 deletes the
-- old place's photos. author_name and author_uri are the photographer, which Google
-- requires to be shown with the photo. The number of photos (3) and the width (800 px)
-- are set in extract_photos.py, not here, so changing them needs no migration.
-- Deleting a restaurant deletes its photos.
BEGIN;

CREATE TABLE public.restaurant_photo (
    restaurant_id   integer      NOT NULL REFERENCES public.restaurant(restaurant_id) ON DELETE CASCADE,
    position        smallint     NOT NULL,
    google_place_id varchar(255) NOT NULL,
    image           bytea        NOT NULL,
    content_type    varchar(20)  NOT NULL,
    width_px        integer,
    height_px       integer,
    author_name     varchar(255),
    author_uri      varchar(500),
    fetched_at      timestamptz  NOT NULL,
    PRIMARY KEY (restaurant_id, position)
);

COMMIT;
