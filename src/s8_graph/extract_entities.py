"""
FoodSight — Graph Entity Extractor (UC18)
Turns the structured F&B data in PostgreSQL into graph entity nodes.

The domain ontology (src/s8_graph/ontology.json) decides which tables become
which node labels and which columns become node properties:

  city -> City            area -> Area              location -> Location
  cluster -> Cluster      restaurant -> Restaurant  cuisine -> Cuisine
  facility -> Facility    price_range -> PriceRange
  business_profile -> BusinessProfile               rating -> Rating
  operating_hours -> OperatingHours                 review -> Review
  nearby_context -> NearbyContext                   nearby_place -> NearbyPlace

Step 1 — Load the ontology.
Step 2 — For each node label, read its table from PostgreSQL.
Step 3 — Turn the ontology's "list_properties" from comma text into lists:
          "families, students" -> ["families", "students"], in the same order.
Step 4 — Work out the ontology's "derived" values (DERIVED below):
          Restaurant.counted_as_open.
Step 5 — Deduplicate nodes by their key (one Cuisine node per cuisine,
          however many restaurants serve it).

The point values ("points", such as pin) are made in build_graph.py, because
they are a Neo4j type.

NOT COPIED INTO THE GRAPH: foreign key columns (they become relationships in
extract_relationships.py). boundary_geojson IS copied, as text, onto Area,
Cluster and City, so the map can be drawn from the graph alone. Neo4j cannot
calculate with it, and it must never be sent to an LLM (an outline is a long
list of coordinates).

Nodes missing a required property are logged and excluded by
validate_graph.py, which checks every node against the ontology.
"""

import json
import logging
import os
from decimal import Decimal

from psycopg2 import sql

from src.categories import get_column

logger = logging.getLogger(__name__)

ONTOLOGY_PATH = os.path.join("src", "s8_graph", "ontology.json")

# The business_status values of restaurants that may still be trading
# (OPERATIONAL and UNKNOWN). Food clusters and COMPETES_WITH use the same list.
OPEN_STATUSES = set(get_column("restaurant.business_status")["counted_as_open"])


def load_ontology(path=ONTOLOGY_PATH):
    if not os.path.exists(path):
        raise FileNotFoundError("Ontology file not found.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _to_graph_value(value):
    """Neo4j cannot store Decimal (e.g. rating_score), so convert it to float."""
    return float(value) if isinstance(value, Decimal) else value


def _split_list(value):
    """'families, office_workers' -> ['families', 'office_workers']. Empty -> None."""
    if value is None:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


def _counted_as_open(node):
    """True when the restaurant may still be trading."""
    return node["business_status"] in OPEN_STATUSES


# Name in the ontology's "derived" -> function(node) -> value.
DERIVED = {
    "counted_as_open": _counted_as_open,
}


def _make_node(columns, row, spec):
    """One node: its columns, lists split, derived values worked out."""
    node = dict(zip(columns, map(_to_graph_value, row)))
    for prop in spec.get("list_properties", []):
        node[prop] = _split_list(node[prop])
    for prop in spec.get("derived", {}):
        node[prop] = DERIVED[prop](node)
    return node


def extract_entities(conn, ontology):
    """Return {label: [node, ...]} where each node is a dict of its properties."""
    nodes = {}
    with conn.cursor() as cur:
        for label, spec in ontology["nodes"].items():
            unknown = set(spec.get("derived", {})) - DERIVED.keys()
            if unknown:
                raise ValueError(
                    f"{label}: no code for derived value(s) {sorted(unknown)}; "
                    "add them to DERIVED in extract_entities.py"
                )
            columns = [spec["key"]] + spec["properties"]
            cur.execute(
                sql.SQL("SELECT {} FROM public.{}").format(
                    sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.Identifier(spec["table"]),
                )
            )
            # Keyed by the node key, so a repeated key keeps one node only.
            unique = {row[0]: _make_node(columns, row, spec) for row in cur.fetchall()}
            nodes[label] = list(unique.values())
            logger.info("  %-16s %5d nodes", label, len(nodes[label]))
    return nodes
