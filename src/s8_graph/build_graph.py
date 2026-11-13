"""
FoodSight — Knowledge Graph Builder (UC20)
Stores the validated nodes and relationships in the Neo4j graph database.

This is the full build, run by python run_8_graph.py --fresh: the first
build, or one that brings an out-of-date graph back in line. A normal run
updates only what changed (update_graph.py, UC21), using the connection,
schema and loading helpers below.

Step 1 — Connect to Neo4j over the Bolt protocol. If Neo4j cannot be
          reached, retry up to 3 times, then abort.

Step 2 — Only with --fresh (python run_8_graph.py --fresh): empty the graph.
          Every node and relationship is deleted, and every constraint and
          index is dropped, so nothing from an older build is left: a
          restaurant no longer in PostgreSQL, or an index on a property the
          ontology no longer has. Step 3 makes them again. This runs only
          after extraction and validation have succeeded, so a run that
          fails while reading PostgreSQL never leaves the graph empty.

Step 3 — Create one uniqueness constraint per node label (on its key), the
          indexes listed in the ontology (name, osm_id, ...), a point index
          for each point value (pin), and the full-text indexes
          (place_names: word search over the names of restaurants, sections
          and nearby places).

Step 4 — Insert nodes in batches using MERGE. Each point value in the
          ontology ("points") is made here from its two columns:
          pin = point({latitude, longitude}), so Neo4j can measure the metres
          between two pins with point.distance().

Step 5 — Insert relationships in batches using MERGE. Nodes always go in
          first, because a relationship needs both of its ends to exist.

MERGE means "create it if it is missing, otherwise update it", so this script
can be re-run without creating duplicates. MERGE never deletes, so only what
can become wrong between two loads is deleted and loaded again, marked
"rebuild" in the ontology:
  Cluster nodes   DBSCAN numbers the clusters again on every run, so an old
                  cluster must not stay. DETACH DELETE also removes their
                  IN_CLUSTER and SPANS relationships.
  COMPETES_WITH   follows the clusters, but links two restaurants, which are
                  never deleted, so it is deleted on its own.
With --fresh the graph is emptied first, so nothing old is left. Rows that
PostgreSQL deleted are removed by the normal run (update_graph.py), from the
stage 8 to-do list.

Requires: pip install neo4j
.env must contain: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
"""

import logging
import os
import time

from dotenv import load_dotenv
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable

load_dotenv()

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000
DELETE_BATCH_SIZE = 10000
MAX_RETRIES = 3
RETRY_WAIT_SECONDS = 5


def connect():
    """Open a Neo4j driver, retrying when the database is unreachable."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    driver = GraphDatabase.driver(
        uri,
        auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "")),
    )
    for attempt in range(MAX_RETRIES + 1):
        try:
            driver.verify_connectivity()
            return driver
        except ServiceUnavailable as exc:
            if attempt == MAX_RETRIES:
                driver.close()
                raise ConnectionError(
                    f"Could not connect to Neo4j at {uri} after {MAX_RETRIES} retries. "
                    "Start the instance in Neo4j Desktop and try again."
                ) from exc
            logger.error("  Neo4j connection failed: %s", str(exc).splitlines()[0])
            logger.info("  Retry %d/%d in %ds...", attempt + 1, MAX_RETRIES, RETRY_WAIT_SECONDS)
            time.sleep(RETRY_WAIT_SECONDS)


def _batches(rows):
    for i in range(0, len(rows), BATCH_SIZE):
        yield rows[i:i + BATCH_SIZE]


def empty_graph(session):
    """Delete every node and relationship, then drop every constraint and
    index, except Neo4j's own lookup indexes (they find nodes by label and
    relationships by type). Returns (nodes deleted, constraints dropped,
    indexes dropped)."""
    deleted = 0
    while True:
        batch = session.run(
            "MATCH (n) WITH n LIMIT $limit DETACH DELETE n RETURN count(*) AS c",
            limit=DELETE_BATCH_SIZE,
        ).single()["c"]
        deleted += batch
        if batch == 0:
            break
    # Constraints first: dropping one also drops the index it owns.
    constraints = [record["name"] for record in session.run("SHOW CONSTRAINTS YIELD name")]
    for name in constraints:
        session.run(f"DROP CONSTRAINT `{name}` IF EXISTS").consume()
    indexes = [
        record["name"]
        for record in session.run("SHOW INDEXES YIELD name, type")
        if record["type"] != "LOOKUP"
    ]
    for name in indexes:
        session.run(f"DROP INDEX `{name}` IF EXISTS").consume()
    return deleted, len(constraints), len(indexes)


def create_constraints_and_indexes(session, ontology):
    for label, spec in ontology["nodes"].items():
        session.run(
            f"CREATE CONSTRAINT {label.lower()}_{spec['key']} IF NOT EXISTS "
            f"FOR (n:`{label}`) REQUIRE n.`{spec['key']}` IS UNIQUE"
        ).consume()
        for prop in spec["indexes"]:
            session.run(
                f"CREATE INDEX {label.lower()}_{prop} IF NOT EXISTS FOR (n:`{label}`) ON (n.`{prop}`)"
            ).consume()
        for prop in spec.get("points", {}):
            session.run(
                f"CREATE POINT INDEX {label.lower()}_{prop} IF NOT EXISTS FOR (n:`{label}`) ON (n.`{prop}`)"
            ).consume()
    for name, spec in ontology.get("fulltext_indexes", {}).items():
        labels = "|".join(f"`{label}`" for label in spec["labels"])
        props = ", ".join(f"n.`{prop}`" for prop in spec["properties"])
        session.run(
            f"CREATE FULLTEXT INDEX {name} IF NOT EXISTS FOR (n:{labels}) ON EACH [{props}]"
        ).consume()


def _set_points(spec):
    """The SET clauses that make each point value of a node from its two
    columns, e.g. SET n.`pin` = point({latitude: row.`latitude`, longitude: row.`longitude`})."""
    return "".join(
        f" SET n.`{name}` = point({{latitude: row.`{lat}`, longitude: row.`{lon}`}})"
        for name, (lat, lon) in spec.get("points", {}).items()
    )


def load_nodes(session, ontology, nodes):
    """MERGE every node. Returns {label: (sent, created)}."""
    summary = {}
    for label, rows in nodes.items():
        spec = ontology["nodes"][label]
        key = spec["key"]
        if spec.get("rebuild"):
            session.run(f"MATCH (n:`{label}`) DETACH DELETE n").consume()
        created = 0
        for batch in _batches(rows):
            counters = session.run(
                f"UNWIND $rows AS row MERGE (n:`{label}` {{`{key}`: row.`{key}`}}) "
                f"SET n = row{_set_points(spec)}",
                rows=batch,
            ).consume().counters
            created += counters.nodes_created
        summary[label] = (len(rows), created)
    return summary


def load_relationships(session, ontology, relationships):
    """MERGE every relationship. Returns {type: (sent, created)}."""
    summary = {}
    for rel_type, rows in relationships.items():
        spec = ontology["relationships"][rel_type]
        from_key = ontology["nodes"][spec["from"]]["key"]
        to_key = ontology["nodes"][spec["to"]]["key"]

        if spec.get("rebuild"):
            session.run(f"MATCH ()-[r:`{rel_type}`]->() DELETE r").consume()

        # A relationship with properties (SERVES: rank, NEAR: distance_m,
        # NEAREST_STATION: distance_m, SPANS: restaurant_count) gets them set,
        # so a rerun updates them on the relationship MERGE found.
        merge = (
            f"MERGE (a)-[r:`{rel_type}`]->(b) SET r += row.props"
            if spec.get("properties")
            else f"MERGE (a)-[:`{rel_type}`]->(b)"
        )
        created = 0
        for batch in _batches(rows):
            counters = session.run(
                f"UNWIND $rows AS row "
                f"MATCH (a:`{spec['from']}` {{`{from_key}`: row.from}}) "
                f"MATCH (b:`{spec['to']}` {{`{to_key}`: row.to}}) "
                f"{merge}",
                rows=batch,
            ).consume().counters
            created += counters.relationships_created
        summary[rel_type] = (len(rows), created)
    return summary


def build_graph(ontology, nodes, relationships, fresh=False):
    logger.info("  Connecting to Neo4j...")
    driver = connect()
    try:
        with driver.session() as session:
            if fresh:
                deleted, constraints, indexes = empty_graph(session)
                logger.info(
                    "  Emptied the graph: %d nodes deleted, %d constraints and %d indexes dropped.",
                    deleted, constraints, indexes,
                )
            create_constraints_and_indexes(session, ontology)
            node_summary = load_nodes(session, ontology, nodes)
            rel_summary = load_relationships(session, ontology, relationships)
            total_nodes = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            total_rels = session.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
    finally:
        driver.close()

    logger.info("  %-16s %7s %9s", "NODE", "sent", "created")
    for label, (sent, created) in node_summary.items():
        logger.info("  %-16s %7d %9d", label, sent, created)
    logger.info("  %-16s %7s %9s", "RELATIONSHIP", "sent", "created")
    for rel_type, (sent, created) in rel_summary.items():
        logger.info("  %-16s %7d %9d", rel_type, sent, created)
    logger.info("  Graph now holds %d nodes and %d relationships.", total_nodes, total_rels)
