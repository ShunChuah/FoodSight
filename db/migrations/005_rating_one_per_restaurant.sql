-- Allow one rating per restaurant, like price_range, business_profile and operating_hours.
-- Without it the loader's ON CONFLICT DO NOTHING never fires, so a second load adds a second rating.
BEGIN;

ALTER TABLE public.rating ADD CONSTRAINT rating_restaurant_id_key UNIQUE (restaurant_id);

-- The UNIQUE constraint creates its own index on restaurant_id, so this one is redundant.
DROP INDEX public.idx_rating_restaurant;

COMMIT;
