"""
FoodSight — Record hashes

One rule for what "changed" means. A record's hash is the SHA-256 of its
values, with fetch times, the rating and the review count left out: those
change on their own and never count as a change. The same values always give
the same 64-character hash; one changed character gives a different one.

  OSM restaurant  its row in data/1_raw/osm_raw.csv
  Google place    its row in data/1_raw/google_raw.csv plus its facilities
                  (google_facilities_raw.csv), sorted so their order never matters
Reviews are never hashed: Google sends a different set of 5 from time to time.

Used by stage 4 (profile_data.py): a saved AI answer is reused only while the
hashes of the records it was made from stay the same.
"""

import csv
import hashlib
import json
import os
from collections import defaultdict

RAW_DIR = os.path.join("data", "1_raw")

# Columns that never count as a change
LEFT_OUT = {"extracted_at", "source", "google_fetched_at", "osm_fetched_at",
            "rating_score", "total_reviews"}
# Comma lists whose order Google may change without anything changing
SORTED_LISTS = {"google_types"}


def record_hash(row):
    """The hash of one record (a dict of its values), leaving out LEFT_OUT."""
    values = {}
    for column, value in row.items():
        if column is None or column in LEFT_OUT:
            continue
        value = "" if value is None else str(value).strip()
        if column in SORTED_LISTS:
            value = ",".join(sorted(item.strip() for item in value.split(",") if item.strip()))
        values[column] = value
    text = json.dumps(values, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def google_places(raw_dir=RAW_DIR):
    """{osm_id: the Google place's row in google_raw.csv, with its facilities
    from google_facilities_raw.csv as one sorted "facilities" value}: one
    Google record, as hashed here and compared by the change check."""
    facilities = defaultdict(list)
    for row in _rows(os.path.join(raw_dir, "google_facilities_raw.csv")):
        facilities[row["osm_id"]].append(f"{row.get('facility_category', '')}:{row.get('facility_name', '')}")
    return {
        row["osm_id"]: {**row, "facilities": ",".join(sorted(facilities[row["osm_id"]]))}
        for row in _rows(os.path.join(raw_dir, "google_raw.csv"))
    }


def restaurant_hashes(raw_dir=RAW_DIR):
    """{osm_id: {"osm": hash, "google": hash, or None without a Google match}}
    for every restaurant in osm_raw.csv."""
    osm_path = os.path.join(raw_dir, "osm_raw.csv")
    if not os.path.exists(osm_path):
        raise FileNotFoundError(f"{osm_path} not found. Run run_1_extraction.py first.")
    google = {osm_id: record_hash(row) for osm_id, row in google_places(raw_dir).items()}
    return {
        row["osm_id"]: {"osm": record_hash(row), "google": google.get(row["osm_id"])}
        for row in _rows(osm_path)
    }
