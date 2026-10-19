"""Read-only Cypher execution on Neo4j."""
import atexit
import logging
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
from typing import Any

from .diagnostics import kg_debug, log_timing
from .messages import response

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CypherExecutionResult:
    records: list[dict[str, Any]]
    status: str
    message: str | None = None
    detail: str | None = None  # the database's own error text (never shown to users)


def execution_enabled() -> bool:
    return os.getenv("NEO4J_EXECUTE_QUERIES", "false").strip().lower() == "true"


def execute_cypher(
    cypher: str,
    parameters: dict[str, Any] | None = None,
    *,
    timeout_seconds: float | None = None,
) -> CypherExecutionResult:
    """Run one query in a read-only session. Never raises: a failure comes back as its status,
    with the database's error in `detail` so the Cypher model can correct the query."""
    started_at = perf_counter()
    if not execution_enabled():
        log_timing("neo4j.query", started_at, status="skipped_disabled", row_count=0)
        return CypherExecutionResult([], "skipped_disabled")

    uri = os.getenv("NEO4J_URI", "").strip()
    user = os.getenv("NEO4J_USER", "").strip()
    password = os.getenv("NEO4J_PASSWORD", "").strip()
    database = os.getenv("NEO4J_DATABASE", "neo4j").strip()
    if not uri or not user or not password:
        logger.warning("Neo4j connection settings are missing")
        kg_debug("Neo4j execution skipped", "Neo4j connection settings are missing")
        log_timing("neo4j.query", started_at, status="skipped_config", row_count=0)
        return CypherExecutionResult([], "skipped_config", response("errors.unavailable"))

    rows: list[dict[str, Any]] = []
    execution_status = "success"
    configured_timeout = _query_timeout()
    effective_timeout = min(configured_timeout, timeout_seconds) if timeout_seconds is not None else configured_timeout
    error_code = None
    if effective_timeout <= 0:
        log_timing("neo4j.query", started_at, status="skipped_deadline", row_count=0, timeout_s=0)
        return CypherExecutionResult([], "error", response("errors.retrieval"))
    try:
        from neo4j import READ_ACCESS, Query

        driver = _driver(uri, user, password)
        # Read-only session: the database itself rejects writes, in addition to the query checks.
        with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
            query = Query(cypher, timeout=effective_timeout)
            rows = [dict(record) for record in session.run(query, parameters or {})]
    except ImportError:
        logger.warning("Neo4j driver is unavailable")
        execution_status = "skipped_missing_driver"
        kg_debug("Neo4j execution skipped", "neo4j package is not installed")
        return CypherExecutionResult([], execution_status, response("errors.unavailable"))
    except Exception as exc:
        logger.warning("Neo4j execution failed: %s", exc)
        error_code = getattr(exc, "code", None) or type(exc).__name__
        execution_status = "timeout" if "TimedOut" in error_code or isinstance(exc, TimeoutError) else "error"
        kg_debug("Neo4j query execution failed", str(exc))
        return CypherExecutionResult([], execution_status, response("errors.retrieval"), str(exc)[:500])
    finally:
        log_timing(
            "neo4j.query",
            started_at,
            status=execution_status,
            row_count=len(rows),
            configured_timeout_s=configured_timeout,
            timeout_s=round(effective_timeout, 3),
            error_code=error_code,
        )
    return CypherExecutionResult(rows, execution_status)


# Queries that touch the restaurant data most questions use (areas, cuisines, ratings, prices, profiles, hours).
WARM_UP_QUERIES = (
    "MATCH (r:Restaurant)-[:LOCATED_IN]->(l:Location)-[:IN_AREA]->(a:Area) RETURN count(DISTINCT a) AS areas",
    "MATCH (r:Restaurant)-[:SERVES]->(c:Cuisine) RETURN count(c) AS cuisines",
    "MATCH (r:Restaurant)-[:HAS_RATING]->(rt:Rating) RETURN max(rt.total_reviews) AS reviews",
    "MATCH (r:Restaurant)-[:PRICED_AT]->(p:PriceRange) RETURN avg(p.avg_meal_price) AS price",
    "MATCH (r:Restaurant)-[:HAS_PROFILE]->(bp:BusinessProfile) RETURN count(bp.halal_status) AS profiles",
    "MATCH (r:Restaurant)-[:HAS_HOURS]->(h:OperatingHours) RETURN count(h) AS hours",
)


def warm_up() -> None:
    """Open the connection and load the graph into Neo4j's memory before the first question.

    The first query on a cold database can take several seconds, which would eat the first user's time budget.
    """
    for query in WARM_UP_QUERIES:
        execute_cypher(query)


def _query_timeout() -> float:
    configured = os.getenv("NEO4J_QUERY_TIMEOUT_SECONDS", "10").strip()
    try:
        timeout = float(configured)
    except ValueError:
        timeout = 10.0
    return max(0.5, min(timeout, 60.0)) if math.isfinite(timeout) else 10.0


@lru_cache(maxsize=4)
def _driver(uri: str, user: str, password: str):
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(uri, auth=(user, password), connection_timeout=5, connection_acquisition_timeout=10)
    atexit.register(driver.close)
    return driver
