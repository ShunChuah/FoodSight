"""
Cleans data/1_raw/reviews_raw.csv → data/2_cleaned/reviews_cleaned.csv.

Step 1 — Remove incomplete rows: drop any row where text or author_name
          is empty or blank.

Step 2 — Validate individual_rating: drop rows where individual_rating
          is not a number between 1 and 5 (inclusive).

Step 3 — Remove duplicate reviews: a review whose google_review_id (Google's
          own ID for it) was already seen is dropped. A review without an ID
          counts as a duplicate only of the same restaurant + author + text,
          so the same words written about two different restaurants are both
          kept.

Step 4 — Normalize language codes: standardise all variants of English
          (e.g. 'en-US', 'en-GB', 'en-AU') to 'en'.
"""

import csv
import os
import sys
from pathlib import Path

INPUT_CSV  = os.path.join("data", "1_raw",     "reviews_raw.csv")
OUTPUT_CSV = os.path.join("data", "2_cleaned", "reviews_cleaned.csv")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_rating(value):
    """Return True if value is a number between 1 and 5 inclusive."""
    try:
        r = float(value)
        return 1 <= r <= 5
    except (TypeError, ValueError):
        return False


def _normalize_language(lang):
    """Normalise English language variants (en-US, en-GB, etc.) to 'en'."""
    if lang.lower().startswith("en"):
        return "en"
    return lang


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

    # Step 1 — remove rows with empty text or author_name
    rows = [
        r for r in rows
        if r.get("text", "").strip() and r.get("author_name", "").strip()
    ]
    incomplete_removed = total_before - len(rows)

    # Step 2 — validate individual_rating is between 1 and 5
    rows = [r for r in rows if _valid_rating(r.get("individual_rating", ""))]
    invalid_rating_removed = (total_before - incomplete_removed) - len(rows)

    # Step 3 — remove duplicate reviews by Google's review ID
    seen = set()
    deduped = []
    for row in rows:
        review_id = row.get("google_review_id", "").strip()
        key = review_id or (
            row.get("osm_id", "").strip(),
            row.get("author_name", "").strip(),
            row.get("text", "").strip(),
        )
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    duplicates_removed = len(rows) - len(deduped)
    rows = deduped

    # Step 4 — normalize language codes (en-US, en-GB → en)
    lang_normalized = 0
    for row in rows:
        original = row.get("language", "")
        normalized = _normalize_language(original)
        if normalized != original:
            row["language"] = normalized
            lang_normalized += 1

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    print(f"  Input  : {INPUT_CSV}")
    print(f"  Before : {total_before} rows")
    print(f"    Incomplete rows removed (no text/author) : {incomplete_removed}")
    print(f"    Invalid rating rows removed              : {invalid_rating_removed}")
    print(f"    Duplicate reviews removed (same ID)      : {duplicates_removed}")
    print(f"    Language codes normalized                : {lang_normalized}")
    print(f"  After  : {len(rows)} reviews -> {OUTPUT_CSV}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    os.chdir(project_root)
    main()