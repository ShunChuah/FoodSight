-- Missing UNIQUE, NOT NULL, delete and number rules found in the schema
-- audit of 2026-10-31.
--
-- BEFORE RUNNING: empty the old restaurant data (the June load). It breaks
-- four of these rules:
--   restaurant_cuisine  226 restaurants have two cuisines with the same rank
--   review              all 3,395 reviews have no google_review_id
--   rating              199 ratings have no score
--   business_profile    all 919 profiles have no evidence_level
-- It all runs in one transaction: if one rule fails, nothing is changed.
--
-- A UNIQUE on two columns checks the PAIR, not each column on its own:
--   UNIQUE (city_id, name)         a city can still have many areas; only two
--                                  areas with the same name in one city are refused.
--   UNIQUE (oauth_name, account_id) many rows can still be 'google'; only the
--                                  same Google account linked twice is refused.
BEGIN;

-- 1. UNIQUE: stop duplicates
ALTER TABLE public.city               ADD CONSTRAINT uq_city_name UNIQUE (name);
ALTER TABLE public.area               ADD CONSTRAINT uq_area_city_name UNIQUE (city_id, name);
-- each restaurant has its own location row
ALTER TABLE public.restaurant         ADD CONSTRAINT uq_restaurant_location UNIQUE (location_id);
-- one cuisine per rank (1 = most important)
ALTER TABLE public.restaurant_cuisine ADD CONSTRAINT uq_restaurant_cuisine_rank UNIQUE (restaurant_id, rank);
-- one Google account links to one user
ALTER TABLE auth.oauth_account        ADD CONSTRAINT uq_oauth_account_provider UNIQUE (oauth_name, account_id);
-- the UNIQUE above makes its own index on the same two columns
DROP INDEX auth.idx_oauth_account_lookup;

-- 2. NOT NULL: never empty
-- UNIQUE lets many empty values in, so these keys must also be NOT NULL to
-- stop duplicates (the loader finds restaurants by osm_id, reviews by google_review_id)
ALTER TABLE public.restaurant       ALTER COLUMN osm_id SET NOT NULL;
ALTER TABLE public.review           ALTER COLUMN google_review_id SET NOT NULL;
-- the loader writes no rating row for a restaurant without a Google rating
ALTER TABLE public.rating           ALTER COLUMN rating_score SET NOT NULL,
                                    ALTER COLUMN total_reviews SET NOT NULL;
-- set by profile_data.py for every profile
ALTER TABLE public.business_profile ALTER COLUMN evidence_level SET NOT NULL;
-- every cuisine in categories.json has a category (origin_country stays optional: Fusion has none)
ALTER TABLE public.cuisine          ALTER COLUMN category SET NOT NULL;

-- 3. Delete rule: deleting a cluster (when DBSCAN runs again) empties
-- restaurant.cluster_id instead of being blocked
ALTER TABLE public.restaurant
    DROP CONSTRAINT restaurant_cluster_id_fkey,
    ADD  CONSTRAINT restaurant_cluster_id_fkey
         FOREIGN KEY (cluster_id) REFERENCES public.cluster (cluster_id) ON DELETE SET NULL;

-- 4. Number rule, like dish.price
ALTER TABLE public.price_range
    ADD CONSTRAINT chk_avg_meal_price CHECK (avg_meal_price IS NULL OR avg_meal_price > 0);

-- 5. Redundant indexes: the UNIQUE constraints restaurant_osm_id_key and
-- users_email_key already index these columns
DROP INDEX public.idx_restaurant_osm;
DROP INDEX auth.idx_users_email;

COMMIT;
