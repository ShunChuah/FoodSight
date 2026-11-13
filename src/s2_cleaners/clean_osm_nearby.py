"""
Builds data/2_cleaned/osm_nearby_cleaned.csv: the places that say who is around
a restaurant (offices, schools, universities, hospitals, malls, hotels and
train stations) in and around PJ.

Input (written by extract_osm.py):
  data/1_raw/osm_nearby_raw.csv   one row per place, with its kind (nearby_place.kind
                                in src/reference/categories.json)

Step 1 — Keep places with a pin, a kind listed in nearby_place.kind and a name. A
          place with no name is dropped: it could not be shown or told apart.
          A station whose type is not listed in nearby_context.station_type
          becomes Other.

Step 2 — Drop repeats of the same OSM element.

Step 3 — Drop the hand-checked places in src/reference/nearby_exclusions.json: places
          OSM tags wrongly (a clinic tagged as a hospital, a toll plaza tagged
          as a mall) or maps more than once (a mall and its wings). Entries no
          longer found in the extracted data are reported, so the list can be
          tidied.

Step 4 — Drop parts of a bigger place: rows whose part_of is filled (a
          school, university or hospital inside the outline of a bigger one of
          the same kind, such as a faculty inside its campus; extract_osm.py
          decides). They stay visible in the raw file, but are never counted.

Step 5 — Drop a place mapped twice in OSM (often once as a dot and once as a
          building, or as its grounds and its building): same kind and same
          name, ignoring case and spaces, within SAME_PLACE_M of each other.
          The first one is kept.

merge_data.py then counts these places around each restaurant.
"""

import csv
import json
import math
import os
import re
import sys
from pathlib import Path

# Lets `src` be imported when this file is run directly, not through run_2_preprocessing.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.categories import allowed_values

INPUT_CSV = os.path.join("data", "1_raw", "osm_nearby_raw.csv")
OUTPUT_CSV = os.path.join("data", "2_cleaned", "osm_nearby_cleaned.csv")
# Hand-written, kept in git: places never counted, by "osm_type/osm_id".
EXCLUSIONS_FILE = os.path.join("src", "reference", "nearby_exclusions.json")

SAME_PLACE_M = 150  # a dot and a building of one place are this close at most

KINDS = set(allowed_values("nearby_place.kind"))
STATION_TYPES = set(allowed_values("nearby_context.station_type"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_csv(path):
    """Return (fieldnames, rows) of a CSV file; stop if it is missing."""
    if not os.path.exists(path):
        sys.exit(f"ERROR: {path} not found. Run extraction first.")
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def _load_exclusions(path):
    """Return {"osm_type/osm_id": detail} from the exclusions file, or {} if
    it is missing."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get("exclusions", {})


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _key(name):
    """Compare names ignoring case and spaces."""
    return re.sub(r"\s+", "", name).lower()


def _distance_m(lat1, lon1, lat2, lon2):
    """Distance in metres between two points (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    fieldnames, rows = _read_csv(INPUT_CSV)
    total_before = len(rows)

    # Step 1 — a pin, a listed kind and a name
    kept = []
    no_name = 0
    for row in rows:
        lat, lon = _float(row.get("latitude")), _float(row.get("longitude"))
        if lat is None or lon is None or row.get("kind") not in KINDS:
            continue
        name = (row.get("name") or "").strip()
        if not name:
            no_name += 1
            continue
        if row["kind"] == "station" and row.get("station_type") not in STATION_TYPES:
            row["station_type"] = "Other"
        kept.append({**row, "name": name})
    no_pin_or_kind = total_before - len(kept) - no_name

    # Step 2 — the same OSM element twice
    seen = set()
    unique = []
    for row in kept:
        element = (row.get("osm_type"), row.get("osm_id"))
        if element not in seen:
            seen.add(element)
            unique.append(row)
    repeats = len(kept) - len(unique)

    # Step 3 — hand-checked places that are never counted
    exclusions = _load_exclusions(EXCLUSIONS_FILE)
    element_key = lambda row: f"{row.get('osm_type')}/{row.get('osm_id')}"
    allowed = [row for row in unique if element_key(row) not in exclusions]
    excluded = len(unique) - len(allowed)
    not_found = sorted(set(exclusions) - {element_key(row) for row in rows})

    # Step 4 — parts of a bigger place
    wholes = [row for row in allowed if not (row.get("part_of") or "").strip()]
    parts = len(allowed) - len(wholes)

    # Step 5 — one place mapped twice: same kind and name, close together
    places = []
    first_of = {}  # (kind, name key) -> pins already kept
    for row in wholes:
        lat, lon = float(row["latitude"]), float(row["longitude"])
        pins = first_of.setdefault((row["kind"], _key(row["name"])), [])
        if any(_distance_m(lat, lon, a, b) <= SAME_PLACE_M for a, b in pins):
            continue
        pins.append((lat, lon))
        places.append(row)
    mapped_twice = len(wholes) - len(places)

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(places)

    # Summary
    print(f"  Input  : {total_before} places from {INPUT_CSV}")
    print(f"    No pin or unknown kind removed   : {no_pin_or_kind}")
    print(f"    No name removed                  : {no_name}")
    print(f"    Same OSM element twice removed   : {repeats}")
    print(f"    Hand-checked exclusions removed  : {excluded} (from {EXCLUSIONS_FILE})")
    if not_found:
        print(f"      not in this data any more (can be removed from the file): {', '.join(not_found)}")
    print(f"    Parts of a bigger place removed  : {parts}")
    print(f"    Mapped twice (same name, {SAME_PLACE_M} m) : {mapped_twice}")
    by_kind = {kind: sum(1 for p in places if p["kind"] == kind) for kind in allowed_values("nearby_place.kind")}
    print("  After  : " + ", ".join(f"{n} {kind}" for kind, n in by_kind.items()) + f" -> {OUTPUT_CSV}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    os.chdir(project_root)
    main()
