import os
import json
import re
from dataclasses import dataclass
from pathlib import Path


SCHEMA_TERM_ALIASES = {
    "Restaurant": {
        "restaurant", "restaurants", "cafe", "cafes", "coffee shop",
        "place", "places", "spot", "spots", "venue", "venues",
        "restaurant type", "venue type", "rating", "ratings", "rated",
        "high rating", "high ratings", "best", "good", "review", "reviews",
        "review count",
    },
    "Location": {
        "location", "locations", "address", "postcode", "coordinate",
        "coordinates", "latitude", "longitude", "near me", "nearby",
        "nearest", "closest", "walking distance",
    },
    "Area": {
        "area", "areas", "neighborhood", "neighbourhood", "district",
        "zone", "near", "around",
    },
    "City": {"city", "state", "country"},
    "Cuisine": {
        "cuisine", "cuisines", "food type", "origin", "italian", "chinese",
        "japanese", "korean", "thai", "indian", "malay", "malaysian",
        "mexican", "french", "western", "mediterranean", "vegetarian",
        "vegan", "halal",
    },
    "Dish": {
        "dish", "dishes", "food", "meal", "breakfast", "brunch", "lunch",
        "dinner", "supper", "signature dish",
    },
    "MenuCategory": {"menu", "menu category", "category"},
    "PriceRange": {
        "price", "prices", "pricing", "budget", "cheap", "cheapest",
        "affordable", "expensive", "luxury", "premium", "cost",
    },
    "BusinessProfile": {
        "ambiance", "atmosphere", "business style", "dining experience",
        "target segment", "casual", "fine dining",
    },
    "Cluster": {
        "cluster", "density", "competition area", "restaurant count",
    },
    "Promotion": {
        "promotion", "promotions", "discount", "discounts", "deal", "deals",
        "offer", "offers",
    },
    "Event": {"event", "events", "recurring"},
    "Facility": {
        "facility", "facilities", "amenity", "amenities", "parking",
        "wifi", "wheelchair", "outdoor seating",
    },
}

IGNORED_CONTEXT_VALUES = {
    "no previous conversation.",
    "no location context provided.",
}

SELF_RELATIONSHIP_TERMS = {
    "NEAR_TO": {"similar restaurant", "near another restaurant"},
    "COMPETES_WITH": {
        "competitor", "competitors", "competing restaurant",
        "competing restaurants", "competition",
    },
}


@dataclass(frozen=True)
class SchemaRelationship:
    source: str
    type: str
    target: str


@dataclass
class GraphSchema:
    nodes: dict[str, set[str]]
    relationships: list[SchemaRelationship]


def get_schema_path() -> Path:
    configured_path = os.getenv(
        "NEO4J_SCHEMA_PATH",
        "app/knowledge_graph/schema.txt",
    ).strip()
    schema_path = Path(configured_path)
    if not schema_path.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        schema_path = backend_root / schema_path
    return schema_path


def get_query_assumptions_path() -> Path:
    configured_path = os.getenv(
        "QUERY_ASSUMPTIONS_PATH",
        "app/knowledge_graph/query_assumptions.json",
    ).strip()
    assumptions_path = Path(configured_path)
    if not assumptions_path.is_absolute():
        backend_root = Path(__file__).resolve().parents[2]
        assumptions_path = backend_root / assumptions_path
    return assumptions_path


def load_graph_schema() -> GraphSchema:
    schema_path = get_schema_path()
    try:
        raw_schema = schema_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(
            f"Could not read Neo4j schema file at {schema_path}: {exc}"
        ) from exc

    if not raw_schema:
        raise RuntimeError(f"Neo4j schema file is empty: {schema_path}")

    nodes = {}
    for label, properties_text in re.findall(
        r"^-\s*([A-Za-z_]\w*)\s*\(([^)]*)\)",
        raw_schema,
        flags=re.MULTILINE,
    ):
        nodes[label] = {
            property_name.strip()
            for property_name in properties_text.split(",")
            if property_name.strip()
        }

    relationships = [
        SchemaRelationship(source, relationship, target)
        for source, relationship, target in re.findall(
            (
                r"^-\s*\(\s*([A-Za-z_]\w*)\s*\)"
                r"\s*-\s*\[:([A-Za-z_]\w*)\]\s*->"
                r"\s*\(\s*([A-Za-z_]\w*)\s*\)"
            ),
            raw_schema,
            flags=re.MULTILINE,
        )
    ]

    if not nodes or not relationships:
        raise RuntimeError(
            f"Neo4j schema file has an unsupported format: {schema_path}"
        )

    return GraphSchema(nodes=nodes, relationships=relationships)


def load_query_assumptions() -> dict:
    assumptions_path = get_query_assumptions_path()
    try:
        return json.loads(assumptions_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not read query assumptions file at {assumptions_path}: {exc}"
        ) from exc


def format_schema(schema: GraphSchema) -> str:
    node_lines = [
        f"- {label}({', '.join(sorted(properties))})"
        for label, properties in sorted(schema.nodes.items())
    ]
    relationship_lines = [
        f"- ({relationship.source})-[:{relationship.type}]->({relationship.target})"
        for relationship in schema.relationships
    ]
    return "\n".join(
        [
            "Node labels:",
            *node_lines,
            "",
            "Relationships:",
            *relationship_lines,
        ]
    )


def format_assumptions(assumptions: list[dict]) -> str:
    if not assumptions:
        return "No query assumptions matched."
    return "\n".join(
        f"- {item['name']}: {item['instruction']}"
        for item in assumptions
        if item.get("name") and item.get("instruction")
    )


def retrieve_relevant_schema(
    schema: GraphSchema,
    user_query: str,
    conversation_context: str = "",
    location_context: str = "",
) -> GraphSchema:
    search_text = " ".join(
        part.strip().lower()
        for part in (user_query, conversation_context, location_context)
        if part.strip() and part.strip().lower() not in IGNORED_CONTEXT_VALUES
    )
    selected_labels = {"Restaurant"} if "Restaurant" in schema.nodes else set()

    for label, properties in schema.nodes.items():
        aliases = SCHEMA_TERM_ALIASES.get(label, set())
        property_terms = {
            property_name.lower().replace("_", " ")
            for property_name in properties
            if property_name not in {"id", "name", "type", "category"}
        }
        if any(_contains_term(search_text, alias) for alias in aliases):
            selected_labels.add(label)
        elif any(_contains_term(search_text, term) for term in property_terms):
            selected_labels.add(label)

    if not selected_labels:
        return schema

    connected_labels = set(selected_labels)
    required_edges = set()
    for label in tuple(selected_labels):
        path = _shortest_schema_path(schema, "Restaurant", label)
        if path:
            connected_labels.update(path)
            required_edges.update(
                frozenset((source, target))
                for source, target in zip(path, path[1:])
            )

    relationships = [
        relationship
        for relationship in schema.relationships
        if (
            relationship.source in connected_labels
            and relationship.target in connected_labels
            and (
                frozenset((relationship.source, relationship.target))
                in required_edges
                or (
                    relationship.source == relationship.target
                    and any(
                        _contains_term(search_text, term)
                        for term in SELF_RELATIONSHIP_TERMS.get(
                            relationship.type,
                            set(),
                        )
                    )
                )
            )
        )
    ]
    nodes = {
        label: properties
        for label, properties in schema.nodes.items()
        if label in connected_labels
    }
    return GraphSchema(nodes=nodes, relationships=relationships)


def retrieve_relevant_assumptions(
    assumptions: dict,
    user_query: str,
    conversation_context: str = "",
    location_context: str = "",
) -> list[dict]:
    search_text = " ".join(
        part.strip().lower()
        for part in (user_query, conversation_context, location_context)
        if part.strip() and part.strip().lower() not in IGNORED_CONTEXT_VALUES
    )
    matched_assumptions = []
    seen_names = set()
    for group_items in assumptions.values():
        if not isinstance(group_items, list):
            continue
        for item in group_items:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            triggers = item.get("triggers") or []
            instruction = item.get("instruction")
            if (
                not name
                or not instruction
                or name in seen_names
                or not any(_contains_term(search_text, trigger) for trigger in triggers)
            ):
                continue
            matched_assumptions.append(
                {"name": name, "instruction": instruction}
            )
            seen_names.add(name)
    return matched_assumptions


def _contains_term(text: str, term: str) -> bool:
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])",
            text,
        )
    )


def _shortest_schema_path(
    schema: GraphSchema,
    start: str,
    target: str,
) -> list[str]:
    if start == target:
        return [start]
    if start not in schema.nodes or target not in schema.nodes:
        return []

    adjacency = {label: [] for label in schema.nodes}
    for relationship in schema.relationships:
        source_neighbors = adjacency.setdefault(relationship.source, [])
        target_neighbors = adjacency.setdefault(relationship.target, [])
        if relationship.target not in source_neighbors:
            source_neighbors.append(relationship.target)
        if relationship.source not in target_neighbors:
            target_neighbors.append(relationship.source)

    queue = [(start, [start])]
    visited = {start}
    while queue:
        current, path = queue.pop(0)
        for neighbor in adjacency.get(current, []):
            if neighbor in visited:
                continue
            next_path = [*path, neighbor]
            if neighbor == target:
                return next_path
            visited.add(neighbor)
            queue.append((neighbor, next_path))
    return []
