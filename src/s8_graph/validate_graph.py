"""
FoodSight — Graph Schema Validator (UC22)
Checks the extracted nodes and relationships against the domain ontology
BEFORE anything is written to Neo4j.

Step 1 — Nodes: the label must exist in the ontology and every required
          property must have a value.

Step 2 — Relationships: the type must exist in the ontology, and both ends
          must be valid nodes of the labels the ontology allows for that type
          (e.g. SERVES must go from a Restaurant to a Cuisine).

Valid entries   -> returned to the caller for graph insertion
Invalid entries -> data/review/graph_invalid.json  (with error reasons)
"""

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

INVALID_PATH = os.path.join("data", "review", "graph_invalid.json")


def _is_empty(value):
    return value is None or (isinstance(value, str) and not value.strip())


def validate_nodes(ontology, nodes):
    """Return (valid nodes by label, list of invalid node reports)."""
    valid, invalid = {}, []
    for label, items in nodes.items():
        spec = ontology["nodes"].get(label)
        if spec is None:
            invalid.extend({"label": label, "key": None, "errors": [f"'{label}' is not a node type in the ontology"]} for _ in items)
            continue

        valid[label] = []
        for node in items:
            missing = [p for p in [spec["key"]] + spec["required"] if _is_empty(node.get(p))]
            if missing:
                invalid.append({
                    "label": label,
                    "key": node.get(spec["key"]),
                    "errors": [f"missing required property '{p}'" for p in missing],
                })
            else:
                valid[label].append(node)
    return valid, invalid


def validate_relationships(ontology, valid_nodes, relationships):
    """Return (valid relationships by type, list of invalid relationship reports)."""
    known_keys = {
        label: {node[ontology["nodes"][label]["key"]] for node in items}
        for label, items in valid_nodes.items()
    }

    valid, invalid = {}, []
    for rel_type, items in relationships.items():
        spec = ontology["relationships"].get(rel_type)
        if spec is None:
            invalid.extend(
                {"type": rel_type, **rel, "errors": [f"'{rel_type}' is not a relationship type in the ontology"]}
                for rel in items
            )
            continue

        sources = known_keys.get(spec["from"], set())
        targets = known_keys.get(spec["to"], set())
        valid[rel_type] = []
        for rel in items:
            errors = []
            if rel["from"] not in sources:
                errors.append(f"source is not a valid {spec['from']} node")
            if rel["to"] not in targets:
                errors.append(f"target is not a valid {spec['to']} node")
            if errors:
                invalid.append({"type": rel_type, **rel, "errors": errors})
            else:
                valid[rel_type].append(rel)
    return valid, invalid


def validate_graph(ontology, nodes, relationships):
    """Validate everything, write the invalid file, return only the valid entries."""
    valid_nodes, invalid_nodes = validate_nodes(ontology, nodes)
    valid_rels, invalid_rels = validate_relationships(ontology, valid_nodes, relationships)

    os.makedirs(os.path.dirname(INVALID_PATH), exist_ok=True)
    with open(INVALID_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "invalid_nodes":         invalid_nodes,
            "invalid_relationships": invalid_rels,
            "validated_at":          datetime.now().astimezone().isoformat(timespec="seconds"),
        }, f, ensure_ascii=False, indent=2)

    logger.info("  Nodes valid:            %d", sum(len(v) for v in valid_nodes.values()))
    logger.info("  Nodes invalid:          %d", len(invalid_nodes))
    logger.info("  Relationships valid:    %d", sum(len(v) for v in valid_rels.values()))
    logger.info("  Relationships invalid:  %d", len(invalid_rels))
    for item in (invalid_nodes + invalid_rels)[:5]:
        logger.warning("  Excluded %s: %s", item.get("label") or item.get("type"), "; ".join(item["errors"]))
    if invalid_nodes or invalid_rels:
        logger.warning("  Violation details: %s", INVALID_PATH)

    return valid_nodes, valid_rels
