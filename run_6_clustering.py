"""
Entry-point runner for the FoodSight food cluster stage.
Runs after run_5_validation.py has produced data/5_validated/pj_validated.json,
and before run_7_loading.py.

Stage 1: Find food clusters (DBSCAN)  -> data/6_clustered/pj_clustered.json
           - Groups open restaurants that are packed close together
           - Each cluster gets its centre, size, outline and density
           - Each restaurant gets its cluster, or none

Usage:
  python run_6_clustering.py                              # 200 m, 5 restaurants
  python run_6_clustering.py --dry-run                    # print the clusters, save nothing
  python run_6_clustering.py --eps 300 --min-samples 10   # try other settings

Requires: pip install scikit-learn
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    from src.s6_clustering.cluster_restaurants import EPS_M, MIN_SAMPLES

    parser = argparse.ArgumentParser(description="FoodSight food clusters (DBSCAN).")
    parser.add_argument("--eps", type=float, default=EPS_M, metavar="METRES",
                        help=f"How close counts as near (default {EPS_M}).")
    parser.add_argument("--min-samples", type=int, default=MIN_SAMPLES, metavar="N",
                        help=f"Restaurants within --eps, itself included, that make a "
                             f"busy spot (default {MIN_SAMPLES}).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the clusters without saving them.")
    args = parser.parse_args()
    if args.eps <= 0:
        parser.error("--eps must be more than 0")
    if args.min_samples < 1:
        parser.error("--min-samples must be at least 1")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting FoodSight clustering pipeline...")
    logger.info("[1/1] Finding food clusters with DBSCAN...")

    try:
        from src.s6_clustering.cluster_restaurants import main as run_cluster

        run_cluster(eps_m=args.eps, min_samples=args.min_samples, dry_run=args.dry_run)

    except FileNotFoundError as exc:
        logger.error("[1/1] Clustering failed: %s", exc)
        logger.error("      Run run_5_validation.py first.")
        sys.exit(1)
    except Exception as exc:
        logger.error("[1/1] Clustering failed: %s", exc)
        sys.exit(1)

    logger.info("Clustering pipeline complete.")


if __name__ == "__main__":
    from src.run_log import start_log
    start_log()
    main()
