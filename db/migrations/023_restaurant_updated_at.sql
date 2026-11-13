-- 023: restaurant.updated_at changes only when the restaurant's own data changes.
--
-- Before: the trigger trg_restaurant_updated_at ran update_updated_at(), which
-- sets updated_at to now() on EVERY update. Every load renumbers the food
-- clusters (replace_clusters() in load_data.py sets cluster_id on every
-- restaurant), so every restaurant got the time of the last load, whether it
-- changed or not. The graph copies updated_at only for the restaurants on the
-- stage 8 to-do list, so the other nodes drifted away from PostgreSQL, and the
-- graph update counted restaurants as updated when only that time differed.
--
-- After: a separate function for restaurants sets now() only when a column
-- other than cluster_id and updated_at itself changed (name, phone, website,
-- business_status, the Google IDs, osm_id ...); otherwise it keeps the old
-- time. An UPDATE that writes the same values also keeps it. A restaurant's
-- linked rows (hours, price, profile, rating, nearby counts, cuisines) do not
-- touch it; they have their own times (generated_at, scraped_at, osm_fetched_at).
--
-- chat_session keeps the shared update_updated_at().
--
-- The times already in the table (the last load, 2026-11-12 03:00, for almost
-- every restaurant) stay as they are: the real times are not known.

BEGIN;

CREATE FUNCTION public.restaurant_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF (to_jsonb(NEW) - 'updated_at' - 'cluster_id')
       IS DISTINCT FROM (to_jsonb(OLD) - 'updated_at' - 'cluster_id') THEN
        NEW.updated_at := now();
    ELSE
        NEW.updated_at := OLD.updated_at;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER trg_restaurant_updated_at ON public.restaurant;

CREATE TRIGGER trg_restaurant_updated_at
    BEFORE UPDATE ON public.restaurant
    FOR EACH ROW EXECUTE FUNCTION public.restaurant_updated_at();

COMMIT;
