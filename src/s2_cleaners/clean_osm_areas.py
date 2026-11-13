"""
Builds data/2_cleaned/osm_areas_cleaned.csv: one row per official section of PJ.

Inputs (written by extract_osm.py):
  data/1_raw/osm_areas_raw.csv    the sections (SS 2, Seksyen 14, PJU 6, ...)
  data/1_raw/osm_places_raw.csv   the familiar named places (Bandar Utama, ...)

Step 1 — Keep sections that have a name and a boundary.

Step 2 — Keep named places that have a name and a geometry and are not just
          a section's own name again (a dot called "SS 2" or "SS2").

Step 3 — Add the named places inside each section to its name:
            PJU 6 (Bandar Utama, Damansara Residensi)
          A dot counts if it lies in the section. A shape counts if at least
          half of it lies in the section, or if it covers at least a fifth of
          the section, so a large place such as Kelana Jaya is listed under
          every section it covers. Names are in alphabetical order; any that
          would push the name past 250 characters are left off.
          Named places inside no section (outside PJ) are reported and dropped.
"""

import csv
import json
import os
import re
import sys
from pathlib import Path

from shapely.geometry import shape

SECTIONS_CSV = os.path.join("data", "1_raw", "osm_areas_raw.csv")
PLACES_CSV = os.path.join("data", "1_raw", "osm_places_raw.csv")
OUTPUT_CSV = os.path.join("data", "2_cleaned", "osm_areas_cleaned.csv")

NAME_MAX = 250  # public.area.name is varchar(250) (db/migrations/003)
MIN_SHARE_OF_PLACE = 0.5  # at least half of the place lies in the section
MIN_SHARE_OF_SECTION = 0.2  # or the place covers at least a fifth of the section


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


def _geometry(row):
    """Return the row's boundary_geojson as a valid shapely geometry, or None."""
    raw = row.get("boundary_geojson", "").strip()
    if not raw:
        return None
    try:
        geom = shape(json.loads(raw))
    except Exception:
        return None
    if not geom.is_valid:
        geom = geom.buffer(0)  # repair self-intersections
    return None if geom.is_empty else geom


def _key(name):
    """Compare names ignoring case and spaces: "SS2" matches "SS 2"."""
    return re.sub(r"\s+", "", name).lower()


def _places_in(section_geom, places):
    """Return the sorted names of the named places that lie in a section."""
    names = set()
    for name, geom in places:
        if geom.geom_type == "Point":
            inside = section_geom.contains(geom)
        else:
            overlap = section_geom.intersection(geom).area
            inside = (
                overlap >= MIN_SHARE_OF_PLACE * geom.area
                or overlap >= MIN_SHARE_OF_SECTION * section_geom.area
            )
        if inside:
            names.add(name)
    return sorted(names)


def _section_name(section, place_names):
    """Return ("PJU 6 (Bandar Utama, ...)", number of place names left off
    to stay within NAME_MAX)."""
    kept = list(place_names)
    while kept:
        name = f"{section} ({', '.join(kept)})"
        if len(name) <= NAME_MAX:
            return name, len(place_names) - len(kept)
        kept.pop()
    return section, len(place_names)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    fieldnames, section_rows = _read_csv(SECTIONS_CSV)
    _, place_rows = _read_csv(PLACES_CSV)

    # Step 1 — sections with a name and a boundary
    sections = []
    for row in section_rows:
        geom = _geometry(row)
        if (
            row.get("name", "").strip()
            and geom is not None
            and geom.geom_type in ("Polygon", "MultiPolygon")
        ):
            sections.append((row, geom))
    if not sections:
        sys.exit(f"ERROR: no usable sections in {SECTIONS_CSV}. Run extraction again.")
    section_keys = {_key(row["name"]) for row, _ in sections}

    # Step 2 — named places with a name and a geometry, other than section names
    places = []
    for row in place_rows:
        name = row.get("name", "").strip()
        geom = _geometry(row)
        if (
            name
            and geom is not None
            and geom.geom_type in ("Point", "Polygon", "MultiPolygon")
            and _key(name) not in section_keys
        ):
            places.append((name, geom))

    # Step 3 — add the named places inside each section to its name
    kept = []
    used = set()
    with_places = 0
    names_left_off = 0
    for row, geom in sections:
        names = _places_in(geom, places)
        used.update(names)
        with_places += bool(names)
        name, left_off = _section_name(row["name"].strip(), names)
        names_left_off += left_off
        kept.append({**row, "name": name})
    outside = sorted({name for name, _ in places} - used)

    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)

    # Summary
    print(f"  Input  : {SECTIONS_CSV}, {PLACES_CSV}")
    print(f"  Sections                          : {len(sections)} of {len(section_rows)}")
    print(f"    with named places in their name : {with_places}")
    print(f"    place names left off (too long) : {names_left_off}")
    print(f"  Named places                      : {len(places)} of {len(place_rows)}")
    print(f"    inside no section (dropped)     : {len(outside)} {outside if outside else ''}")
    print(f"  After  : {len(kept)} areas -> {OUTPUT_CSV}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    os.chdir(project_root)
    main()
