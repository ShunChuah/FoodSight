"""
Entry-point runner for the FoodSight database loading pipeline.
Runs after run_6_clustering.py has produced data/6_clustered/pj_clustered.json.

Stage 1: Bring PostgreSQL (public schema) up to date with the file
           - New rows are added, rows that differ are updated, rows that are
             the same are left alone (fetch times alone never count)
           - City, sections (by osm_id), nearby places: added, updated, and
             deleted when no longer in OSM
           - Each restaurant: its location, hours, price, profile, rating,
             nearby counts, cuisines, facilities and nearby links
           - Reviews: new ones added, old ones kept as history
           - Clusters replaced (old ones deleted, new ones numbered from 1)
           - Restaurants in the database but not in the file are left as they are
         Writes the stage 8 to-do list (data/state/graph_todo.json): every row
         that changed, for run_8_graph.py

Usage:
  python run_7_loading.py              # load
  python run_7_loading.py --dry-run    # show what would change, then undo it

Requires DB credentials in .env:
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="FoodSight database loader.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Make the changes, show them, then undo them: nothing is saved.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting FoodSight database loading pipeline...")
    logger.info("[1/1] %s PostgreSQL with the clustered data...",
                "Comparing (dry run)" if args.dry_run else "Updating")

    try:
        from src.s7_loader.load_data import main as run_load
        run_load(dry_run=args.dry_run)

    except FileNotFoundError as exc:
        logger.error("[1/1] Loading failed: %s", exc)
        logger.error("      Run run_6_clustering.py first.")
        sys.exit(1)
    except Exception as exc:
        logger.error("[1/1] Loading failed: %s", exc)
        sys.exit(1)

    logger.info("Database loading pipeline complete.")


if __name__ == "__main__":
    from src.run_log import start_log
    start_log()
    main()
