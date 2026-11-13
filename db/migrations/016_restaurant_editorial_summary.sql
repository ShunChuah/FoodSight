-- Restaurant: Google's short description of the place (Places API (New)
-- editorialSummary), text only. Empty for a restaurant with no Google match,
-- and for one Google has no description for. The profiler also shows it to
-- the AI as a hint.
BEGIN;

ALTER TABLE public.restaurant ADD COLUMN editorial_summary varchar(1000);

COMMIT;
