"""
Entry-point runner for the FoodSight data preprocessing (cleaning) pipeline.
Runs after run_1_extraction.py has produced raw CSVs in data/1_raw/.

Reads from data/1_raw/, writes cleaned versions to data/2_cleaned/.

Stage 1: osm_raw.csv              → osm_cleaned.csv           (cleaner: clean_osm)
Stage 2: osm_areas_raw.csv
         + osm_places_raw.csv     → osm_areas_cleaned.csv     (cleaner: clean_osm_areas)
Stage 3: osm_nearby_raw.csv       → osm_nearby_cleaned.csv    (cleaner: clean_osm_nearby)
Stage 4: osm_city_raw.csv         → osm_city_cleaned.csv      (cleaner: none — passthrough)
Stage 5: google_raw.csv           → google_cleaned.csv        (cleaner: clean_google)
Stage 6: google_facilities_raw.csv→ google_facilities_cleaned.csv (cleaner: clean_google_facilities)
Stage 7: reviews_raw.csv          → reviews_cleaned.csv       (cleaner: clean_reviews)

Usage:
  python run_2_preprocessing.py              # run all stages
"""

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

RAW_DIR = os.path.join("data", "1_raw")
CLEANED_DIR = os.path.join("data", "2_cleaned")

# Passthrough files: (raw filename, cleaned filename)
# Real cleaner logic will replace these copies when implemented.
PASSTHROUGH_FILES = [
    ("osm_raw.csv", "osm_cleaned.csv"),
    ("osm_city_raw.csv", "osm_city_cleaned.csv"),
    ("google_raw.csv", "google_cleaned.csv"),
    ("google_facilities_raw.csv", "google_facilities_cleaned.csv"),
    ("reviews_raw.csv", "reviews_cleaned.csv"),
]


def _copy_to_cleaned(
    raw_name, cleaned_name, logger, stage_label, note="no cleaner yet"
):
    src = os.path.join(RAW_DIR, raw_name)
    dst = os.path.join(CLEANED_DIR, cleaned_name)
    if not os.path.exists(src):
        logger.error("%s Skipped: %s not found.", stage_label, src)
        return
    shutil.copy2(src, dst)
    logger.info("%s Copied %s -> %s (%s)", stage_label, raw_name, cleaned_name, note)


def main():
    parser = argparse.ArgumentParser(
        description="FoodSight data preprocessing pipeline."
    )
    parser.add_argument(
        "--skip-areas",
        action="store_true",
        help="Skip Stage 2 (OSM area cleaning).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting FoodSight preprocessing pipeline...")

    os.makedirs(CLEANED_DIR, exist_ok=True)

    # ------------------------------------------------------------------
    # Stage 1: OSM restaurants — real cleaner (clean_osm.py)
    # ------------------------------------------------------------------
    logger.info("[1/7] Cleaning OSM restaurants...")
    try:
        from src.s2_cleaners.clean_osm import main as run_clean_osm

        run_clean_osm()
    except FileNotFoundError as exc:
        logger.error("[1/7] Cleaning failed: %s", exc)
        logger.error("      Run run_1_extraction.py first.")
        sys.exit(1)
    except Exception as exc:
        logger.error("[1/7] Cleaning failed: %s", exc)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Stage 2: OSM areas — real cleaner (clean_areas.py)
    # ------------------------------------------------------------------
    if args.skip_areas:
        logger.info("[2/7] OSM area cleaning skipped (--skip-areas).")
    else:
        logger.info("[2/7] Cleaning OSM areas...")
        try:
            from src.s2_cleaners.clean_osm_areas import main as run_clean_osm_areas

            run_clean_osm_areas()
        except FileNotFoundError as exc:
            logger.error("[2/7] Cleaning failed: %s", exc)
            logger.error("      Run run_1_extraction.py first.")
            sys.exit(1)
        except Exception as exc:
            logger.error("[2/7] Cleaning failed: %s", exc)
            sys.exit(1)

    # ------------------------------------------------------------------
    # Stage 3: OSM nearby places — real cleaner (clean_osm_nearby.py)
    # ------------------------------------------------------------------
    logger.info("[3/7] Cleaning OSM nearby places...")
    try:
        from src.s2_cleaners.clean_osm_nearby import main as run_clean_osm_nearby

        run_clean_osm_nearby()
    except Exception as exc:
        logger.error("[3/7] Cleaning failed: %s", exc)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Stage 4: OSM city — passthrough (no cleaner needed)
    # ------------------------------------------------------------------
    _copy_to_cleaned(
        "osm_city_raw.csv", "osm_city_cleaned.csv", logger, "[4/7]", note="passthrough"
    )

    # ------------------------------------------------------------------
    # Stage 4: Google restaurants — real cleaner (clean_google.py)
    # ------------------------------------------------------------------
    logger.info("[5/7] Cleaning Google data...")
    try:
        from src.s2_cleaners.clean_google import main as run_clean_google

        run_clean_google()
    except FileNotFoundError as exc:
        logger.error("[5/7] Cleaning failed: %s", exc)
        logger.error("      Run run_1_extraction.py first.")
        sys.exit(1)
    except Exception as exc:
        logger.error("[5/7] Cleaning failed: %s", exc)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Stage 5: Google facilities — real cleaner (clean_google_facilities.py)
    # ------------------------------------------------------------------
    logger.info("[6/7] Cleaning Google facilities...")
    try:
        from src.s2_cleaners.clean_google_facilities import main as run_clean_google_facilities

        run_clean_google_facilities()
    except FileNotFoundError as exc:
        logger.error("[6/7] Cleaning failed: %s", exc)
        logger.error("      Run run_1_extraction.py first.")
        sys.exit(1)
    except Exception as exc:
        logger.error("[6/7] Cleaning failed: %s", exc)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Stage 6: Reviews — real cleaner (clean_reviews.py)
    # ------------------------------------------------------------------
    logger.info("[7/7] Cleaning reviews...")
    try:
        from src.s2_cleaners.clean_reviews import main as run_clean_reviews

        run_clean_reviews()
    except FileNotFoundError as exc:
        logger.error("[7/7] Cleaning failed: %s", exc)
        logger.error("      Run run_1_extraction.py first.")
        sys.exit(1)
    except Exception as exc:
        logger.error("[7/7] Cleaning failed: %s", exc)
        sys.exit(1)

    logger.info("Preprocessing pipeline complete. Cleaned files in: %s", CLEANED_DIR)


if __name__ == "__main__":
    from src.run_log import start_log
    start_log()
    main()
