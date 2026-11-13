-- Nearby context: what is around each restaurant, from OpenStreetMap. How many
-- offices, schools, malls and hotels lie within 500 m of its pin, how many
-- universities (and colleges) and hospitals within 1 km, and its nearest train
-- station. One row per restaurant, like rating and price_range. A count of 0
-- is a real answer. The kinds, their OSM labels and radii are nearby.kind in
-- src/categories.json; the station types are nearby_context.station_type
-- there (keep the CHECK below in line with it).
BEGIN;

CREATE TABLE public.nearby_context (
    nearby_context_id   serial PRIMARY KEY,
    restaurant_id       integer NOT NULL UNIQUE
                        REFERENCES public.restaurant (restaurant_id) ON DELETE CASCADE,
    offices_500m        integer NOT NULL DEFAULT 0 CHECK (offices_500m >= 0),
    schools_500m        integer NOT NULL DEFAULT 0 CHECK (schools_500m >= 0),
    universities_1km    integer NOT NULL DEFAULT 0 CHECK (universities_1km >= 0),
    hospitals_1km       integer NOT NULL DEFAULT 0 CHECK (hospitals_1km >= 0),
    malls_500m          integer NOT NULL DEFAULT 0 CHECK (malls_500m >= 0),
    hotels_500m         integer NOT NULL DEFAULT 0 CHECK (hotels_500m >= 0),
    nearest_station     varchar(200),
    station_type        varchar(20)
                        CONSTRAINT chk_station_type
                        CHECK (station_type IN ('LRT', 'MRT', 'KTM', 'Monorail', 'Other')),
    station_distance_m  integer CHECK (station_distance_m >= 0),
    osm_fetched_at      timestamptz NOT NULL
);

COMMIT;
