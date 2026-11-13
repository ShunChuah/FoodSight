-- Review: store Google's ID for each review (the review's "name", such as
-- places/ChIJ.../reviews/...), unique, so loading the same review again is
-- skipped instead of adding a copy. Existing rows have no ID (NULL), which
-- the unique rule allows.
BEGIN;

ALTER TABLE public.review
    ADD COLUMN google_review_id varchar(255),
    ADD CONSTRAINT uq_review_google_review_id UNIQUE (google_review_id);

COMMIT;
