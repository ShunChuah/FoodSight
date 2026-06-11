import json
import os
import re
from dataclasses import dataclass
from typing import Any

from .llm_service import (
    LLMServiceError,
    generate_graph_insight,
    generate_graph_query_response,
    repair_cypher,
)
from .schema_service import (
    GraphSchema,
    format_assumptions,
    format_schema,
    load_graph_schema,
    load_query_assumptions,
    retrieve_relevant_assumptions,
    retrieve_relevant_schema,
)


READ_ONLY_CLAUSES = (
    "CREATE", "DELETE", "DETACH", "DROP", "LOAD CSV", "MERGE", "REMOVE", "SET",
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
    rows: list[dict[str, Any]]
    insight: str | None = None
    message: str | None = None
    execution_skipped: bool = False


def answer_with_knowledge_graph(
    user_query: str,
    conversation_context: str = "No previous conversation.",
    location_context: str = "No location context provided.",
) -> KnowledgeGraphResult:
    kg_debug(
        "Knowledge graph request",
        {
            "user_query": user_query,
            "conversation_context": conversation_context,
            "location_context": location_context,
        },
    )
    schema = load_graph_schema()
    relevant_schema = retrieve_relevant_schema(
        schema,
        user_query,
        conversation_context,
        location_context,
    )
    schema_context = format_schema(relevant_schema)
    relevant_assumptions = retrieve_relevant_assumptions(
        load_query_assumptions(),
        user_query,
        conversation_context,
        location_context,
    )
    assumption_context = format_assumptions(relevant_assumptions)
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
    kg_debug("Relevant query assumptions", assumption_context)

    cypher, message = _generate_cypher_or_clarification(
        user_query,
        schema_context,
        assumption_context,
        conversation_context,
        location_context,
    )
    if not cypher:
        return KnowledgeGraphResult(cypher="", rows=[], message=message)

    valid, validation_error = validate_cypher(cypher, schema)
    kg_debug("Local Cypher validation", {"valid": valid, "error": validation_error})
    if not valid:
        repaired, repair_error = _repair_and_clean(
            user_query,
            cypher,
            validation_error or "Invalid query",
            schema_context,
            assumption_context,
            conversation_context,
            location_context,
        )
        if repair_error:
            return KnowledgeGraphResult(cypher="", rows=[], message=repair_error)
        if repaired and validate_cypher(repaired, schema)[0]:
            cypher = repaired
        else:
            return KnowledgeGraphResult(
                cypher="",
                rows=[],
                message=(
                    "I could not create a safe and reliable Cypher query after "
                    "one repair attempt. Please rephrase the F&B request."
                ),
            )

    explain_error, execution_skipped = explain_cypher_query(cypher)
    kg_debug(
        "Neo4j EXPLAIN",
        {"skipped": execution_skipped, "error": explain_error},
    )
    if explain_error:
        repaired, repair_error = _repair_and_clean(
            user_query,
            cypher,
            explain_error,
            schema_context,
            assumption_context,
            conversation_context,
            location_context,
        )
        if repair_error:
            return KnowledgeGraphResult(cypher="", rows=[], message=repair_error)
        if repaired and validate_cypher(repaired, schema)[0]:
            retry_error, _ = explain_cypher_query(repaired)
            if not retry_error:
                cypher = repaired
                explain_error = None
        if explain_error:
            return KnowledgeGraphResult(
                cypher="",
                rows=[],
                message=(
                    "I could not produce a Neo4j-valid Cypher query after one "
                    "repair attempt. Please clarify or rephrase the F&B request."
                ),
            )

    if execution_skipped:
        return KnowledgeGraphResult(
            cypher=cypher,
            rows=[],
            message=(
                "Cypher was validated locally. Neo4j EXPLAIN and execution are "
                "currently disabled."
            ),
            execution_skipped=True,
        )

    rows, execution_error, _ = execute_cypher_query(cypher)
    if execution_error:
        repaired, repair_error = _repair_and_clean(
            user_query,
            cypher,
            execution_error,
            schema_context,
            assumption_context,
            conversation_context,
            location_context,
        )
        if repair_error:
            return KnowledgeGraphResult(cypher="", rows=[], message=repair_error)
        if repaired and validate_cypher(repaired, schema)[0]:
            explain_retry_error, _ = explain_cypher_query(repaired)
            if not explain_retry_error:
                retry_rows, retry_error, _ = execute_cypher_query(repaired)
                if not retry_error:
                    cypher, rows, execution_error = repaired, retry_rows, None
        if execution_error:
            return KnowledgeGraphResult(
                cypher="",
                rows=[],
                message=(
                    "I could not execute a reliable Cypher query after one repair "
                    "attempt. Please rephrase the F&B request."
                ),
            )

    if not rows:
        return KnowledgeGraphResult(
            cypher=cypher,
            rows=[],
            message=(
                "No matching graph results were found. Try broadening the location, "
                "cuisine, price, or rating criteria."
            ),
        )

    try:
        insight = generate_graph_insight(
            user_query,
            rows,
            conversation_context,
            location_context,
        ) or _format_rows(rows)
    except LLMServiceError as exc:
        kg_debug("LLM insight error; using deterministic formatting", exc.user_message)
        insight = _format_rows(rows)
    return KnowledgeGraphResult(cypher=cypher, rows=rows, insight=insight)


def format_kg_response(result: KnowledgeGraphResult) -> str:
    parts = []
    if result.cypher:
        parts.extend(["Generated Cypher query:", "", result.cypher])
    if result.insight:
        parts.extend(["", result.insight])
    if result.message and not result.execution_skipped:
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


def execute_cypher_query(
    cypher: str,
) -> tuple[list[dict[str, Any]], str | None, bool]:
    if not _neo4j_execution_enabled():
        return [], None, True
    connection, error = _neo4j_connection()
    if error:
        return [], error, False

    try:
        from neo4j import GraphDatabase
    except ImportError:
        return [], "Neo4j Python driver is not installed.", False

    uri, user, password, database = connection
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session(database=database) as session:
            rows = [dict(record) for record in session.run(cypher)]
    except Exception as exc:
        return [], str(exc), False
    finally:
        if driver:
            driver.close()
    return rows, None, False


def explain_cypher_query(cypher: str) -> tuple[str | None, bool]:
    if not _neo4j_execution_enabled():
        return None, True
    connection, error = _neo4j_connection()
    if error:
        return error, False

    try:
        from neo4j import GraphDatabase
    except ImportError:
        return "Neo4j Python driver is not installed.", False

    uri, user, password, database = connection
    driver = None
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session(database=database) as session:
            session.run(f"EXPLAIN {cypher}").consume()
    except Exception as exc:
        return str(exc), False
    finally:
        if driver:
            driver.close()
    return None, False


def _generate_cypher_or_clarification(
    user_query: str,
    schema_context: str,
    assumption_context: str,
    conversation_context: str,
    location_context: str,
) -> tuple[str, str | None]:
    result_limit = _requested_result_limit(user_query)
    try:
        raw = generate_graph_query_response(
            user_query,
            schema_context,
            assumption_context,
            conversation_context,
            location_context,
        )
    except LLMServiceError as exc:
        kg_debug("Cypher generation LLM error", exc.user_message)
        return "", exc.user_message
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

    cypher_prefix = re.match(
        r"^CYPHER\s*\|\s*([\s\S]+)$",
        cleaned,
        flags=re.IGNORECASE,
    )
    if cypher_prefix:
        cleaned = cypher_prefix.group(1).strip()
    if re.match(r"^\s*(?:OPTIONAL\s+)?MATCH\b", cleaned, flags=re.IGNORECASE):
        return _clean_cypher(cleaned, result_limit), None
    return "", None


def _repair_and_clean(
    user_query: str,
    cypher: str,
    error_message: str,
    schema_context: str,
    assumption_context: str,
    conversation_context: str,
    location_context: str,
) -> tuple[str | None, str | None]:
    try:
        repaired = repair_cypher(
            user_query,
            cypher,
            error_message,
            schema_context,
            assumption_context,
            conversation_context,
            location_context,
        )
    except LLMServiceError as exc:
        kg_debug("Cypher repair LLM error", exc.user_message)
        return None, exc.user_message
    kg_debug(
        "Raw repaired Cypher LLM output",
        {"error": error_message, "output": repaired or "<empty>"},
    )
    cleaned = (
        _clean_cypher(repaired, _requested_result_limit(user_query))
        if repaired
        else None
    )
    return cleaned, None


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


def _requested_result_limit(user_query: str) -> int:
    match = re.search(
        (
            r"\b(?:top|show|give|find|return|list|suggest|recommend)?\s*"
            r"(\d{1,2})\s+"
            r"(?:options?|results?|places?|restaurants?|cafes?|recommendations?)\b"
        ),
        user_query,
        flags=re.IGNORECASE,
    )
    return max(1, min(int(match.group(1)), 25)) if match else 3


def _is_safe_read_query(cypher: str) -> bool:
    normalized = re.sub(r"\s+", " ", cypher).upper()
    return bool(normalized.startswith(("MATCH ", "OPTIONAL MATCH "))) and not any(
        re.search(rf"\b{re.escape(clause)}\b", normalized)
        for clause in READ_ONLY_CLAUSES
    )


def _neo4j_execution_enabled() -> bool:
    return os.getenv("NEO4J_EXECUTE_QUERIES", "false").strip().lower() == "true"


def _neo4j_connection():
    uri = os.getenv("NEO4J_URI", "").strip()
    user = os.getenv("NEO4J_USER", "").strip()
    password = os.getenv("NEO4J_PASSWORD", "").strip()
    database = os.getenv("NEO4J_DATABASE", "").strip() or None
    if not all([uri, user, password]):
        return None, "Neo4j credentials are not configured."
    return (uri, user, password, database), None


def _format_rows(rows: list[dict[str, Any]]) -> str:
    lines = ["Knowledge graph results:"]
    for index, row in enumerate(rows[:10], start=1):
        values = ", ".join(f"{key}: {value}" for key, value in row.items())
        lines.append(f"{index}. {values}")
    return "\n".join(lines)
