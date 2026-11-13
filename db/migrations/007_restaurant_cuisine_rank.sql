-- Restaurant cuisine: rank each of a restaurant's cuisines, 1 = the most
-- important, up to 3 (the limit in src/categories.json). Existing rows get 1.
BEGIN;

ALTER TABLE public.restaurant_cuisine
    ADD COLUMN rank smallint NOT NULL DEFAULT 1,
    ADD CONSTRAINT chk_restaurant_cuisine_rank CHECK (rank BETWEEN 1 AND 3);

COMMIT;
