"""
Entry-point runner for raw data extraction.

Stage 1: OSM extraction via Overpass API  → data/1_raw/osm_raw.csv
                                             data/1_raw/osm_areas_raw.csv
                                             data/1_raw/osm_places_raw.csv
                                             data/1_raw/osm_city_raw.csv
                                             data/1_raw/osm_nearby_raw.csv
                                             (all five written only when every
                                             OSM request has succeeded)
Stage 2: Google Places enrichment         → data/1_raw/google_raw.csv
                                             data/1_raw/reviews_raw.csv
                                             data/1_raw/google_facilities_raw.csv
                                             data/reports/google_duplicates.json
                                             data/review/google_match_review.json
                                             data/cache/google_cache.json
After each: the change check (UC10)       → data/reports/changes_<source>_<date_time>.json
                                             data/archive/<source>/<date_time>/
                                             (a copy, only when something changed)
           then the scheduler (UC9)       → data/state/schedule.json: the source's
                                             next extraction date (Google's moves
                                             only after a --refresh-google)

Usage:
  python run_1_extraction.py                 # run both stages (an OSM day: saved
                                             # Google matches are reused, only new or
                                             # changed restaurants cost a Google call)
  python run_1_extraction.py --skip-osm      # Google only
  python run_1_extraction.py --skip-google   # OSM only
  python run_1_extraction.py --skip-osm --refresh-google
                                             # a Google day: fresh Place Details for
                                             # every saved match (about 650 calls; a
                                             # failed fetch keeps the saved data)
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.s1_scrapers.detect_changes import check_changes
from src.s1_scrapers.extract_osm import main as run_osm
from src.s1_scrapers.update_schedule import update_schedule


def main():
    parser = argparse.ArgumentParser(description="FoodSight raw data extraction pipeline.")
    parser.add_argument("--skip-osm", action="store_true",
                        help="Skip Stage 1 (OSM extraction).")
    parser.add_argument("--skip-google", action="store_true",
                        help="Skip Stage 2 (Google Places extraction).")
    parser.add_argument("--refresh-google", action="store_true",
                        help="Stage 2: fetch fresh Place Details for every saved match "
                             "(a Google refresh; a failed fetch keeps the saved data).")
    args = parser.parse_args()
    if args.refresh_google and args.skip_google:
        parser.error("--refresh-google cannot be used with --skip-google")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting FoodSight extraction pipeline...")

    def changes(source):
        """The change check (UC10), then the scheduler (UC9), after an
        extraction. A failure is reported but does not undo the extraction,
        whose files are fine."""
        try:
            report = check_changes(source, refresh=args.refresh_google if source == "google" else False)
        except Exception as exc:
            logger.error("Change check for %s failed: %s (the extracted files are fine; "
                         "the next extraction is compared with the last saved copy)", source, exc)
            return
        try:
            update_schedule(source, report)
        except Exception as exc:
            logger.error("Scheduler for %s failed: %s (the schedule stays as it was)", source, exc)

    # ------------------------------------------------------------------
    # Stage 1: OSM extraction
    # ------------------------------------------------------------------
    if args.skip_osm:
        logger.info("[1/2] OSM extraction skipped (--skip-osm).")
    else:
        logger.info("[1/2] Running OSM extraction...")
        try:
            run_osm()
        except Exception as exc:
            logger.error("[1/2] OSM extraction failed: %s", exc)
            sys.exit(1)
        changes("osm")

    # ------------------------------------------------------------------
    # Stage 2: Google Places enrichment
    # Imported here so a missing API key only aborts this stage.
    # ------------------------------------------------------------------
    if args.skip_google:
        logger.info("[2/2] Google Places extraction skipped (--skip-google).")
    else:
        mode_label = " (refresh: fresh Place Details for every saved match)" if args.refresh_google else ""
        logger.info("[2/2] Running Google Places extraction%s...", mode_label)
        try:
            from src.s1_scrapers.extract_google import run as run_google
            run_google(refresh=args.refresh_google)
        except EnvironmentError as exc:
            logger.error("[2/2] Google extraction skipped: %s", exc)
        except Exception as exc:
            logger.error("[2/2] Google extraction failed: %s", exc)
            sys.exit(1)
        else:
            changes("google")

    logger.info("Extraction pipeline complete.")


if __name__ == "__main__":
    from src.run_log import start_log
    start_log()
    main()
