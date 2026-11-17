-- Restaurant photos from business submissions: a submitted restaurant's storefront photo
-- (submission_document, kind storefront_photo) becomes its photo 1 in restaurant_photo, copied by
-- stage 7 (load_data.py, sync_photos()): turned upright, at most 800 px wide, and saved again as a
-- JPEG without the file's hidden data (the GPS position and camera a phone writes into it). The
-- original stays in submission_document for the admin. author_name is the business name.
--
-- A photo now comes from a Google place (google_place_id, stage 1's download) or from a business
-- submission (submission_id), exactly one of the two. Deleting the submission or the restaurant
-- deletes the photo.
BEGIN;

ALTER TABLE public.restaurant_photo ALTER COLUMN google_place_id DROP NOT NULL;
ALTER TABLE public.restaurant_photo
    ADD COLUMN submission_id integer REFERENCES public.business_submission(submission_id) ON DELETE CASCADE;
ALTER TABLE public.restaurant_photo
    ADD CONSTRAINT chk_restaurant_photo_one_source CHECK ((google_place_id IS NULL) <> (submission_id IS NULL));

COMMIT;
