"""
Cleans data/1_raw/google_facilities_raw.csv → data/2_cleaned/google_facilities_cleaned.csv.

Step 1 — Remove duplicate rows: when the same (osm_id, facility_name) pair
          appears more than once, keep only the first occurrence. Duplicates
          can arise if extraction is re-run and the CSV is appended.

Step 2 — Validate facility_category: drop any row whose facility_category is
          not one of the categories defined in src/reference/categories.json
          ("facility.category").
          An unexpected category means a bug crept into the extraction code.

Step 3 — Validate facility_name: drop any row whose facility_name is not one
          of the facility names defined in src/reference/categories.json
          ("facility.name").
          An unknown name means extraction wrote something outside the defined
          attribute map and the row cannot be trusted.
"""

import csv
import os
import sys
from pathlib import Path

# Lets `src` be imported when this file is run directly, not through run_2_preprocessing.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.categories import allowed_values

INPUT_CSV = os.path.join("data", "1_raw", "google_facilities_raw.csv")
OUTPUT_CSV = os.path.join("data", "2_cleaned", "google_facilities_cleaned.csv")

# Defined in src/reference/categories.json.
VALID_CATEGORIES = set(allowed_values("facility.category"))
VALID_FACILITY_NAMES = set(allowed_values("facility.name"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if not os.path.exists(INPUT_CSV):
        sys.exit(f"ERROR: {INPUT_CSV} not found. Run extraction first.")

    with open(INPUT_CSV, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    total_before = len(rows)

    # Step 1 — remove duplicate (osm_id, facility_name) pairs, keep first
    seen = set()
    deduped = []
    for row in rows:
        key = (row.get("osm_id", "").strip(), row.get("facility_name", "").strip())
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    duplicates_removed = total_before - len(deduped)
    rows = deduped

    # Step 2 — drop rows with invalid facility_category
    before_step2 = len(rows)
    rows = [
        r for r in rows if r.get("facility_category", "").strip() in VALID_CATEGORIES
    ]
    invalid_category_removed = before_step2 - len(rows)

    # Step 3 — drop rows with invalid facility_name
    before_step3 = len(rows)
    rows = [
        r for r in rows if r.get("facility_name", "").strip() in VALID_FACILITY_NAMES
    ]
    invalid_name_removed = before_step3 - len(rows)

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    print(f"  Input  : {INPUT_CSV}")
    print(f"  Before : {total_before} rows")
    print(f"    Duplicate (osm_id, facility_name) removed : {duplicates_removed}")
    print(f"    Invalid facility_category removed         : {invalid_category_removed}")
    print(f"    Invalid facility_name removed             : {invalid_name_removed}")
    print(f"  After  : {len(rows)} rows -> {OUTPUT_CSV}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    os.chdir(project_root)
    main()
