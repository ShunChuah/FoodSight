# Safety checks run on every generated Cypher query before execution (FR-53).

import re
from dataclasses import dataclass
from typing import Any

from ..shared.config import policy

READ_ONLY_CLAUSES = (
    "CALL", "CREATE", "DELETE", "DETACH", "DROP", "FOREACH", "LOAD CSV",
    "MERGE", "REMOVE", "SET", "UNION", "USE",
)


@dataclass(frozen=True)
class SchemaRelationship:
    source: str
    type: str
    target: str


@dataclass
class GraphSchema:
    nodes: dict[str, set[str]]
    relationships: list[SchemaRelationship]


def validate_cypher(
    cypher: str,
    schema: GraphSchema,
    parameters: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    if not cypher.strip():
        return False, "The generated query was empty."
    if not re.match(r"^\s*(OPTIONAL\s+)?MATCH\b", cypher, flags=re.IGNORECASE):
        return False, "The query must begin with MATCH or OPTIONAL MATCH."
    if not re.search(r"\bRETURN\b", cypher, flags=re.IGNORECASE):
        return False, "The query must contain a RETURN clause."
    if not _is_safe_read_query(cypher):
        return False, "The query contains a write or unsupported clause."
    if re.search(
        r"\b\w+\.(?:latitude|longitude)\s*=\s*-?\d+(?:\.\d+)?\b",
        cypher,
        flags=re.IGNORECASE,
    ):
        return (
            False,
            "Latitude and longitude must not be compared with exact equality. "
            "Use distance ranking or a radius filter.",
        )
    if ";" in cypher.rstrip(";"):
        return False, "Multiple Cypher statements are not allowed."
    limit_match = re.search(r"\bLIMIT\s+(\d+)\b", cypher, flags=re.IGNORECASE)
    is_count_query = bool(
        re.search(r"\bRETURN\s+COUNT\s*\(", cypher, flags=re.IGNORECASE)
    )
    if not limit_match and not is_count_query:
        return False, "The query must contain a LIMIT clause."
    maximum = policy("results")["maximum_limit"]
    if limit_match and int(limit_match.group(1)) > maximum:
        return False, f"The query result limit cannot exceed {maximum}."
    if len(cypher) > 9000 or len(re.findall(r"\bMATCH\b", cypher, re.IGNORECASE)) > 20:
        return False, "The query exceeds the allowed complexity."

    required_parameters = set(re.findall(r"\$([A-Za-z_]\w*)", cypher))
    supplied_parameters = set((parameters or {}).keys())
    missing_parameters = required_parameters - supplied_parameters
    if missing_parameters:
        return False, f"Missing parameters: {', '.join(sorted(missing_parameters))}."

    variable_labels = dict(
        re.findall(r"\(\s*([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)", cypher)
    )
    unknown_labels = set(variable_labels.values()) - set(schema.nodes)
    if unknown_labels:
        return False, f"Unknown node labels: {', '.join(sorted(unknown_labels))}."

    allowed_relationships = {item.type for item in schema.relationships}
    query_relationships = set(
        re.findall(r"\[\s*\w*\s*:\s*([A-Za-z_]\w*)", cypher)
    )
    unknown_relationships = query_relationships - allowed_relationships
    if unknown_relationships:
        return (
            False,
            f"Unknown relationship types: {', '.join(sorted(unknown_relationships))}.",
        )

    allowed_patterns = {
        (item.source, item.type, item.target) for item in schema.relationships
    }
    used_patterns = set(
        re.findall(
            (
                r"(?=\(\s*\w*\s*:\s*([A-Za-z_]\w*)[^)]*\)"
                r"\s*-\s*\[\s*\w*\s*:\s*([A-Za-z_]\w*)[^\]]*\]\s*->"
                r"\s*\(\s*\w*\s*:\s*([A-Za-z_]\w*)[^)]*\))"
            ),
            cypher,
        )
    )
    reverse_patterns = re.findall(
        (
            r"(?=\(\s*\w*\s*:\s*([A-Za-z_]\w*)[^)]*\)"
            r"\s*<-\s*\[\s*\w*\s*:\s*([A-Za-z_]\w*)[^\]]*\]\s*-"
            r"\s*\(\s*\w*\s*:\s*([A-Za-z_]\w*)[^)]*\))"
        ),
        cypher,
    )
    used_patterns.update(
        (source, relationship, target)
        for target, relationship, source in reverse_patterns
    )
    invalid_patterns = used_patterns - allowed_patterns
    if invalid_patterns:
        rendered = ", ".join(
            f"({source})-[:{relationship}]->({target})"
            for source, relationship, target in sorted(invalid_patterns)
        )
        return False, f"Invalid relationship patterns: {rendered}."

    unknown_properties = []
    property_accesses = re.findall(
        r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)",
        cypher,
    )
    property_accesses += re.findall(r"properties\((\w+)\)\['(\w+)'\]", cypher)
    for variable, property_name in property_accesses:
        label = variable_labels.get(variable)
        if label and property_name not in schema.nodes.get(label, set()):
            unknown_properties.append(f"{label}.{property_name}")
    if unknown_properties:
        return (
            False,
            "Unknown properties: "
            + ", ".join(sorted(set(unknown_properties)))
            + ".",
        )
    return True, None

def _is_safe_read_query(cypher: str) -> bool:
    normalized = re.sub(r"\s+", " ", cypher).upper()
    return (
        bool(normalized.startswith(("MATCH ", "OPTIONAL MATCH ")))
        and "CYPHER |" not in normalized
        and not any(
            re.search(rf"\b{re.escape(clause)}\b", normalized)
            for clause in READ_ONLY_CLAUSES
        )
    )
