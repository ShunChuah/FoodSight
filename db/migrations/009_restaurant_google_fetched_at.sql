-- Restaurant: when its Google data (hours, phone, status, rating, ...) was
-- fetched from Google. Empty for a restaurant with no Google match.
BEGIN;

ALTER TABLE public.restaurant ADD COLUMN google_fetched_at timestamptz;

COMMIT;
