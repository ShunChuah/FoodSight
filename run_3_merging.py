"""
Entry-point runner for the FoodSight data merging pipeline (stage 3).
Runs after run_1_extraction.py and run_2_preprocessing.py.

Merge OSM + Google data by rules only → data/3_merged/pj_merged.json
  - Joins OSM (primary) with Google matches by osm_id
  - Uses a value both sources agree on, or the one source that has it.
    Where they disagree, both values are kept in "conflicts" for the AI in
    run_4_profiling.py, which chooses a source in the same call that
    profiles the restaurant. No AI is used here.
  - Asks Nominatim for an address only when neither source has one
    (failures: data/review/address_lookup_failed.json)
  - Assigns each restaurant to the area (official section) that contains it
  - Attaches nearby places, reviews and facilities

Usage:
  python run_3_merging.py
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="FoodSight data merging pipeline.")
    parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting FoodSight merging pipeline...")
    logger.info("[1/1] Merging by rules (no AI)...")

    try:
        from src.s3_mergers.merge_data import main as run_merge

        # merge_data.main() reads sys.argv itself: give it no options
        sys.argv = [sys.argv[0]]
        run_merge()

    except FileNotFoundError as exc:
        logger.error("[1/1] Merging failed: %s", exc)
        logger.error("      Run run_1_extraction.py and run_2_preprocessing.py first.")
        sys.exit(1)
    except Exception as exc:
        logger.error("[1/1] Merging failed: %s", exc)
        sys.exit(1)

    logger.info("Merging pipeline complete.")


if __name__ == "__main__":
    from src.run_log import start_log
    start_log()
    main()
