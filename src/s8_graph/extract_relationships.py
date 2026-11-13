"""
FoodSight — Graph Relationship Extractor (UC19)
Builds the relationships that link the graph entity nodes together.

Step 1 — Structural relationships, derived from foreign keys and junction
          tables in PostgreSQL (the ontology names the table and columns):

            (Restaurant)-[:LOCATED_IN]->(Location)-[:IN_AREA]->(Area)-[:IN_CITY]->(City)
            (Restaurant)-[:SERVES {rank}]->(Cuisine)
            (Restaurant)-[:HAS_FACILITY]->(Facility)
            (Restaurant)-[:HAS_HOURS]->(OperatingHours)
            (Restaurant)-[:PRICED_AT]->(PriceRange)
            (Restaurant)-[:HAS_PROFILE]->(BusinessProfile)
            (Restaurant)-[:HAS_RATING]->(Rating)
            (Restaurant)-[:HAS_NEARBY]->(NearbyContext)
            (Restaurant)-[:NEAR {distance_m}]->(NearbyPlace)
            (Restaurant)-[:HAS_REVIEW]->(Review)
            (Restaurant)-[:IN_CLUSTER]->(Cluster)

          A row whose foreign key is empty has no relationship and is skipped
          (e.g. a location that was not matched to any area). A relationship
          whose ontology entry lists "properties" also carries those columns
          of its table (SERVES carries rank, NEAR carries distance_m).

Step 2 — Relationships worked out by rule (RULES below), with no AI:

            (Restaurant)-[:NEAREST_STATION {distance_m}]->(NearbyPlace)
              the restaurant's nearest train station: the station name in
              nearby_context (worked out by merge_data.py) matched to the
              station node of that name. A restaurant whose station name
              matches no station node, or two, gets no link and a warning.

            (Cluster)-[:SPANS {restaurant_count}]->(Area)
              each section a food cluster reaches into, with how many of the
              cluster's restaurants are in it.

            (Restaurant)-[:COMPETES_WITH]->(Restaurant)
              both restaurants may still be trading (business_status
              OPERATIONAL or UNKNOWN: counted_as_open in src/reference/categories.json),
              are in the same food cluster
              (DBSCAN, run_6_clustering.py), share at least one cuisine and have
              the same price tier. A restaurant in no cluster has no
              competitors.

          A rule's SQL returns the start key, the end key, then the
          relationship's properties in the order the ontology lists them.
          Competition has no direction, so each pair is stored once, from the
          lower restaurant_id to the higher one.
"""

import logging
from collections import defaultdict

from psycopg2 import sql

from src.categories import get_column
from src.s8_graph.extract_entities import _to_graph_value

logger = logging.getLogger(__name__)

# An empty cluster_id never equals another (NULL = NULL is not true in SQL),
# so a restaurant in no cluster gets no pairs.
COMPETES_WITH_SQL = """
    SELECT DISTINCT a.restaurant_id, b.restaurant_id
    FROM public.restaurant a
    JOIN public.price_range pa         ON pa.restaurant_id = a.restaurant_id
    JOIN public.restaurant_cuisine ca  ON ca.restaurant_id = a.restaurant_id
    JOIN public.restaurant b           ON b.restaurant_id > a.restaurant_id
                                      AND b.cluster_id = a.cluster_id
    JOIN public.price_range pb         ON pb.restaurant_id = b.restaurant_id
                                      AND pb.tier = pa.tier
    JOIN public.restaurant_cuisine cb  ON cb.restaurant_id = b.restaurant_id
                                      AND cb.cuisine_id = ca.cuisine_id
    WHERE a.business_status = ANY(%(open)s)
      AND b.business_status = ANY(%(open)s)
"""

# Every restaurant with a nearest station, with the station node(s) of that
# name. A name with no station node gives one row with an empty
# nearby_place_id; a name shared by two stations gives two rows.
# _one_station_each() then keeps only the restaurants with exactly one.
NEAREST_STATION_SQL = """
    SELECT nc.restaurant_id, np.nearby_place_id, nc.station_distance_m
    FROM public.nearby_context nc
    LEFT JOIN public.nearby_place np ON np.kind = 'station'
                                    AND np.name = nc.nearest_station
    WHERE nc.nearest_station IS NOT NULL
"""

# One row per cluster and section it reaches into, with how many of the
# cluster's restaurants are in that section.
SPANS_SQL = """
    SELECT r.cluster_id, l.area_id, count(*)
    FROM public.restaurant r
    JOIN public.location l ON l.location_id = r.location_id
    WHERE r.cluster_id IS NOT NULL
      AND l.area_id IS NOT NULL
    GROUP BY r.cluster_id, l.area_id
"""

# Rule name in the ontology -> SQL that returns (from key, to key, properties...).
RULES = {
    "competes_with": COMPETES_WITH_SQL,
    "nearest_station": NEAREST_STATION_SQL,
    "spans": SPANS_SQL,
}

# The values a rule's SQL is given: the business_status values of restaurants
# that may still be trading (OPERATIONAL and UNKNOWN)
RULE_PARAMS = {
    "competes_with": {"open": get_column("restaurant.business_status")["counted_as_open"]},
}


def _one_station_each(rows):
    """Keep a restaurant's NEAREST_STATION link only when its station name
    matched exactly one station node. A name that matches none would give no
    link, and two stations with the same name would give a wrong second link,
    so those restaurants are left without one and reported."""
    matches = defaultdict(list)
    for row in rows:
        matches[row[0]].append(row)
    kept, problems = [], []
    for restaurant_id, found in matches.items():
        linked = [row for row in found if row[1] is not None]
        if len(linked) == 1:
            kept.append(linked[0])
        else:
            problems.append((restaurant_id, len(linked)))
    if problems:
        logger.warning(
            "  NEAREST_STATION: %d restaurants have no link, because their station name "
            "matches 0 or 2+ station nodes. First ones (restaurant_id, matches): %s",
            len(problems), problems[:5],
        )
    return kept


# Rule name -> check run on the rule's rows before they become relationships.
RULE_CHECKS = {
    "nearest_station": _one_station_each,
}


def _structural_query(spec):
    """SELECT the two key columns, then the relationship's properties, if any."""
    columns = [spec["from_column"], spec["to_column"]] + spec.get("properties", [])
    return sql.SQL("SELECT {cols} FROM public.{table} WHERE {src} IS NOT NULL AND {dst} IS NOT NULL").format(
        cols=sql.SQL(", ").join(map(sql.Identifier, columns)),
        src=sql.Identifier(spec["from_column"]),
        dst=sql.Identifier(spec["to_column"]),
        table=sql.Identifier(spec["table"]),
    )


def extract_relationships(conn, ontology):
    """Return {relationship type: [{"from": key, "to": key}, ...]}. A
    relationship with properties also has "props": {column: value}."""
    relationships = {}
    with conn.cursor() as cur:
        for rel_type, spec in ontology["relationships"].items():
            props = spec.get("properties", [])
            params = None
            if "rule" in spec:
                query, params = RULES[spec["rule"]], RULE_PARAMS.get(spec["rule"])
            else:
                query = _structural_query(spec)
            cur.execute(query, params)
            rows = cur.fetchall()
            check = RULE_CHECKS.get(spec.get("rule"))
            if check:
                rows = check(rows)
            relationships[rel_type] = [
                {"from": row[0], "to": row[1],
                 **({"props": dict(zip(props, map(_to_graph_value, row[2:])))} if props else {})}
                for row in rows
            ]
            logger.info("  %-16s %5d relationships", rel_type, len(relationships[rel_type]))
    return relationships
