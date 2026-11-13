"""
Entry-point runner for the FoodSight AI stage (stage 4).
Runs after run_3_merging.py has produced data/3_merged/pj_merged.json.

One AI call per new or changed restaurant → data/4_profiled/pj_final.json
  - Chooses a source for each field where OSM and Google disagree
    (name, phone, website, address); the value is copied from that source.
    For every field but the name it may trust neither ("none"): the field
    stays empty, and merge_log keeps both values and the AI's reason
  - Adds cuisines, price_range and business_profile; the prompt shows up to
    10 reviews (Google's latest first, then older ones)
  - Cached in data/cache/profile_cache.json with the hashes of the OSM and
    Google records it was made from: an unchanged restaurant is not asked
    again (a new rating or new reviews alone never ask again)
  - Every review is kept in data/cache/review_cache.json; new reviews get
    their sentiment in batches of 20 per AI call
  - No usable answer after its tries (4 for a server error, waiting 15, 30
    and 60 s; 3 for an unusable answer) → listed in data/review/ai_failed.json and
    left out of pj_final.json: the restaurant (profile), or only the review
    (sentiment; its restaurant goes on). The next run asks them again
  - run_5_validation.py checks pj_final.json next, before anything is loaded

Usage:
  python run_4_profiling.py            # full run
  python run_4_profiling.py --no-llm   # cached answers only; the rest are left out

Requires GEMINI_API_KEY in .env (unless --no-llm is used).
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="FoodSight data profiling pipeline.")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Ask the AI nothing: cached answers only; the rest are left out.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting FoodSight profiling pipeline...")

    if args.no_llm:
        logger.info("[1/1] Profiling (no AI calls)...")
    else:
        logger.info("[1/1] Settling disagreements and profiling with the AI...")

    try:
        from src.s4_profilers.profile_data import main as run_profile

        # profile_data.main() reads sys.argv itself: pass on only --no-llm
        sys.argv = [sys.argv[0]] + (["--no-llm"] if args.no_llm else [])

        run_profile()

    except FileNotFoundError as exc:
        logger.error("[1/1] Profiling failed: %s", exc)
        logger.error("      Run run_3_merging.py first.")
        sys.exit(1)
    except Exception as exc:
        logger.error("[1/1] Profiling failed: %s", exc)
        sys.exit(1)

    logger.info("Profiling pipeline complete.")


if __name__ == "__main__":
    from src.run_log import start_log
    start_log()
    main()
