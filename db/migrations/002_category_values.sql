-- Bring two CHECK rules in line with src/categories.json:
-- review.sentiment gains 'mixed', and the top price tier 'fine-dining' becomes 'luxury'.
BEGIN;

ALTER TABLE public.review DROP CONSTRAINT chk_sentiment;
ALTER TABLE public.review
    ADD CONSTRAINT chk_sentiment
    CHECK (sentiment IS NULL OR sentiment IN ('positive', 'mixed', 'neutral', 'negative'));

ALTER TABLE public.price_range DROP CONSTRAINT chk_tier;
UPDATE public.price_range SET tier = 'luxury' WHERE tier = 'fine-dining';
ALTER TABLE public.price_range
    ADD CONSTRAINT chk_tier
    CHECK (tier IN ('budget', 'mid', 'upscale', 'luxury'));

COMMIT;
