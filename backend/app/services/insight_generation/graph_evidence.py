# Knowledge Graph Evidence: the Neo4j subgraph an answer was built from, drawn as stored.

from typing import Any

from ..shared.neo4j import execute_cypher
from .graph_answer import _plain, _today

MAX_RESTAURANTS = 10
MAX_NODES = 80

RESTAURANT_SUBGRAPH = """
UNWIND range(0, size($ids) - 1) AS position
MATCH (r:Restaurant) WHERE r.restaurant_id = $ids[position]
CALL {
  WITH r
  RETURN r AS a, null AS rel, null AS b
  UNION
  WITH r
  MATCH (r)-[rel:LOCATED_IN|LOCATED_AT|PRICED_AT|HAS_PRICE_RANGE|HAS_RATING|HAS_PROFILE|HAS_HOURS|SERVES|HAS_FACILITY]->(b)
  RETURN r AS a, rel, b
  UNION
  WITH r
  MATCH (r)-[:LOCATED_IN]->(a:Location)-[rel:IN_AREA|LOCATED_IN]->(b:Area)
  RETURN a, rel, b
  UNION
  WITH r
  MATCH (r)-[:LOCATED_IN]->(:Location)-[:IN_AREA]->(a:Area)-[rel:IN_CITY|PART_OF]->(b:City)
  RETURN a, rel, b
  UNION
  WITH r
  MATCH (r)-[rel:COMPETES_WITH]-(other:Restaurant) WHERE other.restaurant_id IN $anchors
  RETURN startNode(rel) AS a, rel, endNode(rel) AS b
}
RETURN elementId(a) AS source_id, labels(a)[0] AS source_label, properties(a) AS source_properties,
       type(rel) AS type,
       elementId(b) AS target_id, labels(b)[0] AS target_label, properties(b) AS target_properties
ORDER BY position, type, target_label, target_id
""".strip()

AREA_SUBGRAPH = """
UNWIND range(0, size($areas) - 1) AS position
MATCH (a:Area) WHERE a.name = $areas[position]
OPTIONAL MATCH (a)-[rel:IN_CITY|PART_OF]->(b:City)
RETURN elementId(a) AS source_id, labels(a)[0] AS source_label, properties(a) AS source_properties,
       type(rel) AS type,
       elementId(b) AS target_id, labels(b)[0] AS target_label, properties(b) AS target_properties
ORDER BY position
""".strip()

CAPTION_PROPERTIES = {
    "Rating": "rating_score",
    "PriceRange": "tier",
    "Location": "postcode",
    "BusinessProfile": "service_style",
}


class GraphEvidenceError(RuntimeError):
    pass


def build_graph_evidence(records: list[dict[str, Any]]) -> dict | None:
    rows = [row for row in records[:MAX_RESTAURANTS] if isinstance(row, dict)]
    ids = list(dict.fromkeys(row["restaurant_id"] for row in rows if row.get("restaurant_id") is not None))
    if ids:
        anchors = list(dict.fromkeys(row["anchor_id"] for row in rows
                                     if row.get("competitor_of") and row.get("anchor_id") is not None))
        result = execute_cypher(RESTAURANT_SUBGRAPH, {"ids": ids, "anchors": anchors})
    else:
        areas = list(dict.fromkeys(str(row["area_name"]) for row in rows if row.get("area_name")))
        if not areas:
            return None
        result = execute_cypher(AREA_SUBGRAPH, {"areas": areas})
    if result.status == "skipped_disabled":
        return None
    if result.status != "success":
        raise GraphEvidenceError(f"Neo4j {result.status}: {result.detail or result.message}")

    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str, str], dict] = {}

    def add(node_id: str | None, label: str | None, properties: dict | None) -> bool:
        if not node_id:
            return False
        if node_id not in nodes:
            if len(nodes) >= MAX_NODES:
                return False
            properties = _plain(properties or {})
            nodes[node_id] = {"id": node_id, "label": label, "name": _caption(label, properties),
                              "properties": properties}
        return True

    for row in result.records:
        source = add(row["source_id"], row["source_label"], row["source_properties"])
        target = add(row["target_id"], row["target_label"], row["target_properties"])
        if source and target and row["type"]:
            key = (row["source_id"], row["target_id"], row["type"])
            edges.setdefault(key, {"source": row["source_id"], "target": row["target_id"], "type": row["type"]})
    if not nodes:
        return None
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def _caption(label: str | None, properties: dict) -> str:
    field = "name" if properties.get("name") not in (None, "") else (
        _today() if label == "OperatingHours" else CAPTION_PROPERTIES.get(label))
    value = properties.get(field) if field else None
    return str(value) if value not in (None, "") else str(label or "Node")
