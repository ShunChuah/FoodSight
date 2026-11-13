-- Nearby places: the exact OSM places behind the counts in nearby_context.
--   nearby_place             one row per place (office, school, university,
--                            hospital, mall, hotel, train station), stored once;
--                            every place, also those near no restaurant
--   restaurant_nearby_place  one row per restaurant and counted place within
--                            its kind's radius, with the distance. Only counted
--                            kinds: the nearest station stays in nearby_context.
--                            For each kind, a restaurant's number of rows equals
--                            its count in nearby_context.
-- distance_m is the straight-line distance in metres between the restaurant's
-- pin and the place's pin (a node's point, or the middle of an outline's box).
-- The kinds are nearby.kind and the station types nearby_context.station_type
-- in src/categories.json; the CHECKs below copy them.
BEGIN;

CREATE TABLE public.nearby_place (
    nearby_place_id  serial PRIMARY KEY,
    osm_type         varchar(10)  NOT NULL
                     CHECK (osm_type IN ('node', 'way', 'relation')),
    osm_id           bigint       NOT NULL,
    kind             varchar(20)  NOT NULL
                     CONSTRAINT chk_nearby_place_kind
                     CHECK (kind IN ('school', 'university', 'hospital', 'mall',
                                     'hotel', 'station', 'office')),
    name             varchar(200) NOT NULL,
    station_type     varchar(20)
                     CONSTRAINT chk_nearby_place_station_type
                     CHECK (station_type IN ('LRT', 'MRT', 'KTM', 'Monorail', 'Other')),
    latitude         double precision NOT NULL,
    longitude        double precision NOT NULL,
    osm_fetched_at   timestamptz  NOT NULL,
    CONSTRAINT uq_nearby_place_osm UNIQUE (osm_type, osm_id),
    -- a station always has a type; nothing else has one
    CONSTRAINT chk_nearby_place_station_has_type
        CHECK ((kind = 'station') = (station_type IS NOT NULL))
);

CREATE TABLE public.restaurant_nearby_place (
    restaurant_id    integer NOT NULL
                     REFERENCES public.restaurant (restaurant_id) ON DELETE CASCADE,
    nearby_place_id  integer NOT NULL
                     REFERENCES public.nearby_place (nearby_place_id) ON DELETE CASCADE,
    distance_m       integer NOT NULL CHECK (distance_m >= 0),
    PRIMARY KEY (restaurant_id, nearby_place_id)
);

-- "Which restaurants are near this place?" (the primary key already covers
-- "which places are near this restaurant?")
CREATE INDEX idx_restaurant_nearby_place_place
    ON public.restaurant_nearby_place (nearby_place_id);

COMMIT;
