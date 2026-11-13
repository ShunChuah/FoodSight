"""
Entry-point runner for the FoodSight knowledge graph pipeline.
Runs after run_7_loading.py has stored the validated data in PostgreSQL.

Stage 1: Extract graph entities       (UC18)  PostgreSQL tables -> nodes
Stage 2: Extract graph relationships  (UC19)  foreign keys      -> relationships
                                              rules             -> NEAREST_STATION,
                                                                   SPANS, COMPETES_WITH
Stage 3: Validate against ontology    (UC22)  -> data/review/graph_invalid.json
Stage 4: Update the knowledge graph   (UC21)  only the rows on the stage 8 to-do list
                                              (data/state/graph_todo.json, written by
                                              run_7_loading.py): added, updated or
                                              removed in Neo4j, clusters rebuilt;
                                              then the list is emptied
     or: Build the knowledge graph    (UC20)  with --fresh: empty Neo4j and copy all

The node types, relationship types and required properties are defined in
src/s8_graph/ontology.json.

Usage:
  python run_8_graph.py            # update the graph with what the last loads changed
  python run_8_graph.py --fresh    # empty the graph, then build it again from all of
                                   # PostgreSQL: the first build, or a graph that is
                                   # out of date (it also empties the to-do list)

Requires in .env:
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
  NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
Neo4j must be running (start the instance in Neo4j Desktop first).
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="FoodSight knowledge graph (PostgreSQL -> Neo4j).")
    parser.add_argument("--fresh", action="store_true",
                        help="Empty the graph (every node, relationship, constraint and index) "
                             "and build it again from all of PostgreSQL. The graph is emptied "
                             "only after extraction and validation have succeeded.")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    # On a re-run Neo4j reports "constraint already exists" once per constraint.
    logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)
    logger = logging.getLogger(__name__)
    logger.info("Starting FoodSight knowledge graph pipeline...")

    try:
        from src.s8_graph.build_graph import build_graph
        from src.s8_graph.extract_entities import extract_entities, load_ontology
        from src.s8_graph.extract_relationships import extract_relationships
        from src.s8_graph.update_graph import empty_todo, read_todo, todo_is_empty, update_graph
        from src.s8_graph.validate_graph import validate_graph
        from src.s7_loader.load_data import TODO_FILE, get_connection

        todo = read_todo()
        if not args.fresh and todo_is_empty(todo):
            logger.info("Nothing to update: the stage 8 to-do list (%s) is empty.", TODO_FILE)
            logger.info("To copy everything again (the first build, or a graph that is out of "
                        "date): python run_8_graph.py --fresh")
            return

        ontology = load_ontology()

        conn = get_connection()
        try:
            logger.info("[1/4] Extracting graph entities from PostgreSQL...")
            nodes = extract_entities(conn, ontology)

            logger.info("[2/4] Extracting graph relationships...")
            relationships = extract_relationships(conn, ontology)
        finally:
            conn.close()

        # Every key in PostgreSQL, before validation: a listed row that is not
        # here was deleted; one that is here but fails validation is invalid
        in_postgres = {label: {node[ontology["nodes"][label]["key"]] for node in items}
                       for label, items in nodes.items()}

        logger.info("[3/4] Validating nodes and relationships against the ontology...")
        nodes, relationships = validate_graph(ontology, nodes, relationships)

        if args.fresh:
            logger.info("[4/4] Building the knowledge graph in Neo4j (emptying it first)...")
            build_graph(ontology, nodes, relationships, fresh=True)
            empty_todo(todo)  # the graph now matches PostgreSQL
        else:
            logger.info("[4/4] Updating the knowledge graph with the to-do list (UC21)...")
            update_graph(ontology, nodes, relationships, todo, in_postgres)
            empty_todo(todo)
            logger.info("  The to-do list is empty again (%s).", TODO_FILE)

    except FileNotFoundError as exc:
        logger.error("Knowledge graph pipeline failed: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.error("Knowledge graph pipeline failed: %s", exc)
        if args.fresh:
            logger.error("The graph may be half built: fix the problem and run "
                         "python run_8_graph.py --fresh again.")
        else:
            logger.error("Nothing was changed in the graph, and the to-do list was kept: "
                         "fix the problem and run it again.")
        sys.exit(1)

    logger.info("Knowledge graph pipeline complete.")


if __name__ == "__main__":
    from src.run_log import start_log
    start_log()
    main()
