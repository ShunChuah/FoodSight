import json
import os
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from .analysis_service import analyze_kg_rows
from .llm_service import (
    LLMServiceError,
    generate_graph_query_response,
)
from .query_understanding_service import format_query_understanding
from .schema_service import (
    GraphSchema,
    format_schema,
    load_graph_schema,
    retrieve_relevant_schema,
)


READ_ONLY_CLAUSES = (
    "CALL", "CREATE", "DELETE", "DETACH", "DROP", "FOREACH", "LOAD CSV",
    "MERGE", "REMOVE", "SET", "UNION", "USE",
)


def kg_debug(stage: str, value: Any = None) -> None:
    if os.getenv("KG_DEBUG", "false").strip().lower() != "true":
        return
    prefix = f"[KG DEBUG] {stage}"
    if value is None:
        print(prefix, flush=True)
        return
    rendered = (
        value
        if isinstance(value, str)
        else json.dumps(value, default=str, ensure_ascii=False, indent=2)
    )
    print(f"\n{prefix}\n{rendered}\n", flush=True)


@dataclass
class KnowledgeGraphResult:
    cypher: str
    message: str | None = None
    rows: list[dict[str, Any]] | None = None
    analysis: str | None = None


def answer_with_knowledge_graph(
    user_query: str,
    conversation_context: str = "No previous conversation.",
    location_context: str = "No location context provided.",
    scope: str = "fnb_customer",
    query_understanding: dict | None = None,
) -> KnowledgeGraphResult:
    kg_debug(
        "Knowledge graph request",
        {
            "user_query": user_query,
            "conversation_context": conversation_context,
            "location_context": location_context,
            "scope": scope,
            "query_understanding": query_understanding,
        },
    )
    schema = load_graph_schema()
    relevant_schema = retrieve_relevant_schema(
        schema,
        user_query,
        conversation_context,
        location_context,
        query_understanding,
    )
    schema_context = format_schema(relevant_schema)
    understanding_context = format_query_understanding(query_understanding)
    kg_debug(
        "Relevant graph schema selection",
        {
            "node_labels": sorted(relevant_schema.nodes),
            "relationship_types": sorted(
                {item.type for item in relevant_schema.relationships}
            ),
        },
    )
    kg_debug("Relevant graph schema", schema_context)
    kg_debug("Structured query understanding", understanding_context)

    cypher, message = _generate_cypher_or_clarification(
        schema_context,
        understanding_context,
        location_context,
    )
    if not cypher:
        return KnowledgeGraphResult(cypher="", message=message)

    valid, validation_error = validate_cypher(cypher, schema)
    kg_debug("Local Cypher validation", {"valid": valid, "error": validation_error})
    if not valid:
        return KnowledgeGraphResult(
            cypher="",
            message=(
                "I could not create a safe, schema-valid Cypher query. "
                f"Validation failed: {validation_error or 'unknown error'}"
            ),
        )

    rows = _execute_cypher_if_enabled(cypher)
    analysis = analyze_kg_rows(query_understanding, rows)
    return KnowledgeGraphResult(cypher=cypher, rows=rows, analysis=analysis)


def format_kg_response(result: KnowledgeGraphResult) -> str:
    parts = []
    if result.cypher:
        parts.extend(["Generated Cypher query:", "", result.cypher])
    if result.analysis:
        parts.extend(["", result.analysis])
    if result.rows:
        parts.extend(
            [
                "",
                "Query result rows:",
                json.dumps(result.rows[:5], default=str, ensure_ascii=False, indent=2),
            ]
        )
    if result.message:
        parts.extend(
            ["", f"Status: {result.message}"]
            if result.cypher
            else [result.message]
        )
    return "\n".join(parts).strip()


def validate_cypher(
    cypher: str,
    schema: GraphSchema | None = None,
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
    if limit_match and int(limit_match.group(1)) > 25:
        return False, "The query result limit cannot exceed 25."

    schema = schema or load_graph_schema()
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
    for variable, property_name in re.findall(
        r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)",
        cypher,
    ):
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


def _execute_cypher_if_enabled(cypher: str) -> list[dict[str, Any]]:
    if os.getenv("NEO4J_EXECUTE_QUERIES", "false").strip().lower() != "true":
        return []

    try:
        from neo4j import GraphDatabase
    except ImportError:
        kg_debug("Neo4j execution skipped", "neo4j package is not installed")
        return []

    uri = os.getenv("NEO4J_URI", "").strip()
    user = os.getenv("NEO4J_USER", "").strip()
    password = os.getenv("NEO4J_PASSWORD", "").strip()
    database = os.getenv("NEO4J_DATABASE", "neo4j").strip()
    if not uri or not user or not password:
        kg_debug("Neo4j execution skipped", "Neo4j connection settings are missing")
        return []

    started_at = perf_counter()
    print("[TIMING] Neo4j query execution started. elapsed=0.00s total=0.00s", flush=True)
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session(database=database) as session:
            rows = [dict(record) for record in session.run(cypher)]
    except Exception as exc:
        kg_debug("Neo4j query execution failed", str(exc))
        return []
    finally:
        driver.close()
        elapsed = perf_counter() - started_at
        print(
            f"[TIMING] Neo4j query execution returned rows. "
            f"elapsed={elapsed:.2f}s total={elapsed:.2f}s",
            flush=True,
        )
    return rows


def _generate_cypher_or_clarification(
    schema_context: str,
    understanding_context: str,
    location_context: str,
) -> tuple[str, str | None]:
    result_limit = _understanding_result_limit(understanding_context)
    try:
        started_at = perf_counter()
        print(
            "[TIMING] Cypher generation started. elapsed=0.00s total=0.00s",
            flush=True,
        )
        raw = generate_graph_query_response(
            schema_context,
            understanding_context,
            location_context,
        )
    except LLMServiceError as exc:
        kg_debug("Cypher generation LLM error", exc.user_message)
        return "", exc.user_message
    finally:
        if "started_at" in locals():
            elapsed = perf_counter() - started_at
            print(
                f"[TIMING] Cypher generation produced a query. "
                f"elapsed={elapsed:.2f}s total={elapsed:.2f}s",
                flush=True,
            )
    kg_debug("Raw generated Cypher LLM output", raw or "<empty>")
    cypher, clarification = _parse_generation_output(raw or "", result_limit)
    if cypher or clarification:
        return cypher, clarification

    return "", (
        "I could not generate a reliable Cypher query. Please rephrase your "
        "question with clearer F&B criteria."
    )


def _parse_generation_output(
    text: str,
    result_limit: int,
) -> tuple[str, str | None]:
    cleaned = text.strip()
    fenced = re.fullmatch(
        r"```(?:text|cypher)?\s*([\s\S]*?)```",
        cleaned,
        flags=re.IGNORECASE,
    )
    if fenced:
        cleaned = fenced.group(1).strip()

    clarification = re.match(
        r"^CLARIFY\s*\|\s*(.+)$",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if clarification:
        return "", " ".join(clarification.group(1).strip().split())[:500]

    cypher_blocks = re.split(
        r"(?im)^\s*CYPHER\s*\|\s*",
        cleaned,
    )
    if len(cypher_blocks) > 1:
        # Some models ignore the single-query instruction and return alternatives.
        # Keep only the first candidate; later candidates must never reach the UI.
        if cypher_blocks[0].strip():
            return "", None
        cleaned = cypher_blocks[1].strip()

    if re.match(r"^\s*(?:OPTIONAL\s+)?MATCH\b", cleaned, flags=re.IGNORECASE):
        return _clean_cypher(cleaned, result_limit), None
    return "", None


def _clean_cypher(text: str, result_limit: int | None = None) -> str:
    cleaned = text.strip()
    fenced = re.search(
        r"```(?:cypher)?\s*([\s\S]*?)```",
        cleaned,
        flags=re.IGNORECASE,
    )
    if fenced:
        cleaned = fenced.group(1).strip()
    cleaned = cleaned.rstrip(";").strip()
    if result_limit is None or re.search(
        r"\bRETURN\s+COUNT\s*\(",
        cleaned,
        flags=re.IGNORECASE,
    ):
        return cleaned

    safe_limit = max(1, min(result_limit, 25))
    if re.search(r"\bLIMIT\s+\d+\b", cleaned, flags=re.IGNORECASE):
        return re.sub(
            r"\bLIMIT\s+\d+\b",
            f"LIMIT {safe_limit}",
            cleaned,
            count=1,
            flags=re.IGNORECASE,
        )
    return f"{cleaned}\nLIMIT {safe_limit}"


def _understanding_result_limit(understanding_context: str) -> int:
    try:
        understanding = json.loads(understanding_context)
    except json.JSONDecodeError:
        return 3

    limit = understanding.get("limit") if isinstance(understanding, dict) else None
    return max(1, min(int(limit), 25)) if isinstance(limit, int) else 3


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
