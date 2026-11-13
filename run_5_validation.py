"""
Entry-point runner for the FoodSight data validation pipeline.
Runs after run_4_profiling.py has produced data/4_profiled/pj_final.json.

Stage 1: Validate profiled data  -> data/5_validated/pj_validated.json
                                    data/review/validation_invalid.json
           - Validates every restaurant and area against foodsight_schema.json
           - Mirrors all PostgreSQL CHECK constraints and NOT NULL rules
           - Valid records are safe to insert into PostgreSQL
           - Invalid records go to data/review/validation_invalid.json with
             per-field error messages

Usage:
  python run_5_validation.py

Requires: pip install jsonschema
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger(__name__)
    logger.info("Starting FoodSight validation pipeline...")
    logger.info("[1/1] Validating profiled data against JSON schema...")

    try:
        from src.s5_validator.validate_data import main as run_validate

        run_validate()

    except FileNotFoundError as exc:
        logger.error("[1/1] Validation failed: %s", exc)
        logger.error("      Run run_4_profiling.py first.")
        sys.exit(1)
    except Exception as exc:
        logger.error("[1/1] Validation failed: %s", exc)
        sys.exit(1)

    logger.info("Validation pipeline complete.")


if __name__ == "__main__":
    from src.run_log import start_log
    start_log()
    main()
