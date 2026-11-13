-- Add the road a restaurant is on, such as Jalan SS 2/24, as its own column.
-- Empty when no source gives a street.
BEGIN;

ALTER TABLE public.location ADD COLUMN street varchar(200);

COMMIT;
