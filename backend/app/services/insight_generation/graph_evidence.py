"""Knowledge Graph Evidence for View Details (FR-58: graph visualisation).

Turns the rows behind an answer into nodes and relationships:

    Dough! Bakery & Cafe -SERVES-> Western
    Dough! Bakery & Cafe -LOCATED_IN-> Seksyen 17
    Hideaway Cafe        -SERVES-> Western        (the same Western node)

Only facts already in the retrieved rows are drawn, so the picture never shows
more than the answer used. Repeated values share one node; that is what makes
connections between results visible. Restaurant -> Area is drawn directly
(the graph stores Restaurant -> Location -> Area; the Location step adds nothing
for the user).
"""
from typing import Any

from ..shared.config import policy
from .presentation import distance_label, money_label, price_tier_label

MAX_RESTAURANTS = 10
MAX_NODES = 60


class _Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str, str], dict] = {}

    def node(self, label: str, key: object, name: str, properties: dict | None = None) -> str | None:
        """Add (or reuse) a node; the same label + key is always the same node."""
        node_id = f"{label}:{str(key).strip().casefold()}"
        if node_id not in self.nodes:
            if len(self.nodes) >= MAX_NODES:
                return None  # keep the picture readable
            self.nodes[node_id] = {"id": node_id, "label": label, "name": name,
                                   "properties": {k: v for k, v in (properties or {}).items() if v not in (None, "", [])}}
        return node_id

    def edge(self, source: str | None, target: str | None, relationship: str) -> None:
        if source and target:
            self.edges.setdefault((source, target, relationship), {"source": source, "target": target, "type": relationship})

    def to_dict(self) -> dict | None:
        if not self.nodes:
            return None
        return {"nodes": list(self.nodes.values()), "edges": list(self.edges.values())}


def build_graph_evidence(records: list[dict[str, Any]]) -> dict | None:
    """Return {"nodes": [...], "edges": [...]} for the answer's rows, or None when there is nothing to draw."""
    graph = _Graph()
    for row in records[:MAX_RESTAURANTS]:
        if not isinstance(row, dict):
            continue
        if row.get("restaurant_name"):
            _add_restaurant(graph, row)
        elif row.get("area_name"):
            _add_area(graph, row)
    return graph.to_dict()


def _add_restaurant(graph: _Graph, row: dict) -> None:
    name = str(row["restaurant_name"])
    currency = row.get("currency") or "MYR"
    halal = {"halal": "Listed as halal", "non-halal": "Listed as non-halal"}.get(row.get("halal_status"))
    restaurant = graph.node("Restaurant", row.get("restaurant_id") or name, name, {
        "Rating": f"{row['average_rating']:g} out of 5" if isinstance(row.get("average_rating"), (int, float)) else None,
        "Reviews": f"{int(row['review_count']):,}" if isinstance(row.get("review_count"), (int, float)) else None,
        "Average price": money_label(row.get("average_price"), currency),
        "Distance": distance_label(row.get("distance_m")),
        "Halal": halal,
    })
    if restaurant is None:
        return
    for cuisine in row.get("cuisines") or []:
        graph.edge(restaurant, graph.node("Cuisine", cuisine, str(cuisine)), "SERVES")
    if row.get("area"):
        graph.edge(restaurant, graph.node("Area", row["area"], str(row["area"])), "LOCATED_IN")
    tier = row.get("price_tier")
    if tier:
        label = price_tier_label(tier)
        graph.edge(restaurant, graph.node("PriceRange", tier, label[:1].upper() + label[1:]), "HAS_PRICE_RANGE")


def _add_area(graph: _Graph, row: dict) -> None:
    """An area row from an analysis question, with the numbers the query computed for it."""
    area = str(row["area_name"])
    node = graph.node("Area", area, area, {
        key.replace("_", " ").capitalize(): _number_text(value)
        for key, value in row.items() if key != "area_name" and _number_text(value) is not None
    })
    city = policy("coverage")["city"]
    graph.edge(node, graph.node("City", city, city), "PART_OF")


def _number_text(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.1f}"
