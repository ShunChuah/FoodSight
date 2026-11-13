"""
Extracts raw F&B data from OpenStreetMap for Petaling Jaya via the Overpass API.

Runs three steps in sequence:
  1. extract_fnb()    — fetches all restaurant/cafe/etc nodes and ways within PJ,
                        parses opening hours into per-day columns
                        (parse_opening_hours()), takes the brand from the
                        brand tag only (never operator), and takes the
                        address, postcode and street from OSM addr:* tags only
                        (no Nominatim here: merge_data.py asks it later, only
                        for restaurants still without an address). One row per
                        restaurant, for data/1_raw/osm_raw.csv.
  2. extract_areas()  — fetches PJ's official sections (admin_level 10, such
                        as SS 2 or PJU 6) and the named places inside PJ
                        (suburbs, neighbourhoods, quarters), and converts each
                        element's geometry into a GeoJSON string with
                        osm2geojson (Point for nodes; Polygon for relations, or
                        MultiPolygon when an area has separate pieces). Rows for
                        data/1_raw/osm_areas_raw.csv (sections) and
                        data/1_raw/osm_places_raw.csv (named places).
  3. extract_city()   — fetches the full Petaling Jaya admin boundary relation,
                        converts it to GeoJSON with osm2geojson, and looks up
                        the state and country that contain it (Overpass is_in).
                        One row for data/1_raw/osm_city_raw.csv.
  4. extract_nearby() — fetches the places that say who is around a restaurant
                        (offices, schools, universities, hospitals, malls,
                        hotels and train stations: nearby_place.kind in
                        src/reference/categories.json) in the box around the city
                        widened by NEARBY_MARGIN_M. One row per place, for
                        data/1_raw/osm_nearby_raw.csv; merge_data.py counts them
                        around each restaurant. A school, university or
                        hospital inside the outline of a bigger one (a faculty
                        inside its campus) gets part_of and is never counted.

All HTTP calls use exponential backoff. main() writes the five files only
after every step has succeeded, so a failed query leaves the files of the last
successful run untouched instead of mixing new and old files.
"""

import copy
import csv
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import osm2geojson
import requests
from shapely.geometry import Point, mapping, shape

# Lets `src` be imported when this file is run directly, not through run_1_extraction.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.categories import get_column

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "FoodSight-FYP/1.0"
OUTPUT_DIR = "data/1_raw"
OSM_RAW_CSV = os.path.join(OUTPUT_DIR, "osm_raw.csv")
OSM_AREAS_CSV = os.path.join(OUTPUT_DIR, "osm_areas_raw.csv")
OSM_PLACES_CSV = os.path.join(OUTPUT_DIR, "osm_places_raw.csv")
OSM_CITY_CSV = os.path.join(OUTPUT_DIR, "osm_city_raw.csv")
OSM_NEARBY_CSV = os.path.join(OUTPUT_DIR, "osm_nearby_raw.csv")


def _load_osm_labels():
    """Return {OSM key: {OSM value: amenity type}} from src/reference/categories.json,
    where each amenity type lists the OSM labels ("key=value") that produce it,
    e.g. bakery <- shop=bakery, shop=pastry."""
    labels = {}
    for amenity_type, detail in get_column("restaurant.amenity_type")["values"].items():
        for label in detail["osm"]:
            key, value = label.split("=", 1)
            labels.setdefault(key, {})[value] = amenity_type
    return labels


OSM_LABELS = _load_osm_labels()

DAY_ORDER = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
DAY_TO_COL = {
    "Mo": "monday",
    "Tu": "tuesday",
    "We": "wednesday",
    "Th": "thursday",
    "Fr": "friday",
    "Sa": "saturday",
    "Su": "sunday",
}

OSM_RAW_COLUMNS = [
    "osm_id",
    "osm_type",
    "name",
    "amenity_type",
    "brand",
    "phone",
    "website",
    "latitude",
    "longitude",
    "full_address",
    "postcode",
    "street",
    "hours_raw",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "is_24_7",
    "cuisine_raw",
    "halal_tag",
    "source",
    "extracted_at",
]

AREAS_COLUMNS = ["osm_id", "name", "type", "boundary_geojson", "source", "extracted_at"]
CITY_COLUMNS = [
    "osm_id",
    "name",
    "state",
    "country",
    "boundary_geojson",
    "source",
    "extracted_at",
]
NEARBY_COLUMNS = [
    "osm_id",
    "osm_type",
    "kind",
    "name",
    "station_type",
    "part_of",
    "latitude",
    "longitude",
    "source",
    "extracted_at",
]

BACKOFF_WAITS = [2, 4, 8, 16, 32]


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _get(url, params=None, data=None):
    """GET (or POST if data provided) with exponential backoff."""
    headers = {"User-Agent": USER_AGENT}
    last_exc = None
    for attempt, wait in enumerate(BACKOFF_WAITS, start=1):
        try:
            if data is not None:
                resp = requests.post(url, data=data, headers=headers, timeout=180)
            else:
                resp = requests.get(url, params=params, headers=headers, timeout=180)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_exc = exc
            if attempt < len(BACKOFF_WAITS):
                print(f"  Attempt {attempt} failed ({exc}), retrying in {wait}s…")
                time.sleep(wait)
    raise RuntimeError(
        f"All {len(BACKOFF_WAITS)} attempts failed. Last error: {last_exc}"
    )


# ---------------------------------------------------------------------------
# Overpass query
# ---------------------------------------------------------------------------

def _build_overpass_query():
    """Ask OSM for every amenity and shop label listed in src/reference/categories.json.
    Cuisine labels get no line of their own: they only relabel places that
    one of the other labels already collects."""
    lines = []
    for key, values in OSM_LABELS.items():
        if key == "cuisine":
            continue
        pattern = "|".join(values)
        lines.append(f'  node(area.pj)["{key}"~"^({pattern})$"];')
        lines.append(f'  way(area.pj)["{key}"~"^({pattern})$"];')
    return "\n".join(
        [
            "[out:json][timeout:120];",
            'area["name"="Petaling Jaya"]["admin_level"="7"]->.pj;',
            "(",
            *lines,
            ");",
            "out center tags;",
        ]
    )


OVERPASS_QUERY = _build_overpass_query()


def fetch_fnb_elements():
    """Fetch F&B elements from Overpass and return deduplicated list."""
    print("  Sending Overpass query…")
    resp = _get(OVERPASS_URL, data={"data": OVERPASS_QUERY})
    elements = resp.json().get("elements", [])
    print(f"  Raw elements returned: {len(elements)}")

    seen_ids = set()
    deduped = []
    for el in elements:
        eid = el.get("id")
        if eid not in seen_ids:
            seen_ids.add(eid)
            deduped.append(el)

    print(f"  Elements after deduplication: {len(deduped)}")
    return deduped


# ---------------------------------------------------------------------------
# Tag mapping helpers
# ---------------------------------------------------------------------------


def _first(*values):
    """Return first non-empty string value."""
    for v in values:
        if v:
            return v.strip()
    return ""


def get_coords(el):
    """Return (lat, lon) for node or way element."""
    if el.get("type") == "node":
        return el.get("lat", ""), el.get("lon", "")
    center = el.get("center", {})
    return center.get("lat", ""), center.get("lon", "")


def resolve_amenity_type(tags):
    """Turn an element's OSM labels into one amenity type. A cuisine label wins
    (a cafe that sells bubble tea is a beverage shop), then amenity, then shop."""
    cuisine = tags.get("cuisine", "")
    for osm_value, amenity_type in OSM_LABELS.get("cuisine", {}).items():
        if osm_value in cuisine:
            return amenity_type
    # Amenity labels are listed first in categories.json, so they are checked first.
    for key, mapping in OSM_LABELS.items():
        if key != "cuisine" and tags.get(key) in mapping:
            return mapping[tags[key]]
    return "unknown"


# ---------------------------------------------------------------------------
# Hours parsing
# ---------------------------------------------------------------------------


# Public and school holidays: skipped, since the columns hold weekdays only.
HOLIDAYS = {"PH", "SH"}
# One opening, such as "11:00-15:00", "8:30-16:00" or "11:00 – 22:00".
_TIME_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})")
# Inside one rule, a day word right after a time (or after "off"/"closed")
# starts a new part: "Mo-Sa 11:00-04:00, Su 11:00-24:00" and
# "Mo-Fr 07:00-20:00 Sa-Su 10:00-20:00" are two parts each. A comma between
# two times is not a new part but a split shift: "Mo-Su 11:00-15:00, 17:30-22:00".
_NEW_PART = re.compile(
    r"(?:(?<=\d)|(?<=(?i:off))|(?<=(?i:closed)))\s*(?:,\s*|\s+)"
    r"(?=(?:Mo|Tu|We|Th|Fr|Sa|Su|PH|SH)\b)"
)


def _day_range_to_list(start, end):
    """Expand 'Mo-Fr' → ['Mo','Tu','We','Th','Fr']. A range that runs past
    Sunday wraps round: 'Su-Th' → ['Su','Mo','Tu','We','Th'] and 'We-Mo' is
    Wednesday to Monday."""
    si = DAY_ORDER.index(start)
    ei = DAY_ORDER.index(end)
    if si <= ei:
        return DAY_ORDER[si : ei + 1]
    return DAY_ORDER[si:] + DAY_ORDER[: ei + 1]


def parse_opening_hours(hours_raw):
    """
    Parse an OSM opening_hours string into a dict of day→hours and is_24_7.
    Returns: (day_dict, is_24_7)
    day_dict keys are DAY_TO_COL values. Each day is its opening times
    ("11:00-15:00, 18:00-22:00"), "Closed", or "" when unknown.

    How a string is read:
      - ";" separates rules, and a later rule replaces an earlier one for the
        days it names: "Mo-Sa 15:00-24:00; Sa 17:00-24:00" gives Saturday
        17:00-24:00.
      - Inside a rule, the parts (see _NEW_PART) add up:
        "Mo-Fr 08:00-12:00, We 14:00-18:00" gives Wednesday both times.
      - A day range may wrap past Sunday ("Su-Th", "Th-Tu").
      - One-digit hours get two digits (8:30 → 08:30). A trailing "open"
        is ignored ("00:00-24:00 open"). PH and SH are skipped.
      - "Closed" is a day marked off/closed, or a day the string does not
        mention (in OSM's rules an unlisted day is closed: Mo-Sa 06:30-15:00
        means Sunday is closed).
      - If any part cannot be read (an unknown word such as "sunrise", or a
        typo such as "18:300"), every day is "" (unknown), never "Closed".
      - "24/7" makes every day "00:00-24:00".
    is_24_7 is true only when all 7 days are "00:00-24:00".
    """
    unknown = {col: "" for col in DAY_TO_COL.values()}
    if not hours_raw:
        return unknown, False

    s = hours_raw.strip()
    if s == "24/7":
        return {col: "00:00-24:00" for col in unknown}, True

    day_dict = dict(unknown)
    for rule in (r.strip() for r in s.split(";") if r.strip()):
        rule_days = {}  # what this rule says about each day it names
        for part in _NEW_PART.split(rule):
            read = _read_part(part)
            if read is None:
                return dict(unknown), False
            days, value = read
            for day in days:
                if value == "Closed":
                    rule_days[day] = "Closed"
                else:
                    earlier = rule_days.get(day)
                    rule_days[day] = (earlier if isinstance(earlier, list) else []) + value
        for day, value in rule_days.items():
            day_dict[DAY_TO_COL[day]] = value if value == "Closed" else ", ".join(sorted(set(value)))

    if any(day_dict.values()):
        for col in day_dict:
            day_dict[col] = day_dict[col] or "Closed"
    is_24_7 = all(v == "00:00-24:00" for v in day_dict.values())
    return day_dict, is_24_7


def _read_part(part):
    """Read one part of a rule, such as 'Mo-Fr 08:00-12:00, 14:00-18:00',
    '11:00-22:00' (every day) or 'We off'. Returns (days, "Closed") or
    (days, [times]); None when the part cannot be read."""
    part = re.sub(r"\s+open$", "", part.strip(), flags=re.IGNORECASE)

    closed = re.fullmatch(r"(.*?)\s*\b(?:off|closed)", part, re.IGNORECASE)
    if closed:
        days = _parse_day_spec(closed.group(1)) if closed.group(1) else list(DAY_ORDER)
        return None if days is None else (days, "Closed")

    times = list(_TIME_RANGE.finditer(part))
    if not times:
        return None
    # Only times, and commas between them, may follow the first time.
    if _TIME_RANGE.sub("", part[times[0].start() :]).strip(" ,"):
        return None
    day_part = part[: times[0].start()].strip()
    days = _parse_day_spec(day_part) if day_part else list(DAY_ORDER)
    if days is None:
        return None
    return days, [
        f"{int(h1):02d}:{m1}-{int(h2):02d}:{m2}"
        for h1, m1, h2, m2 in (t.groups() for t in times)
    ]


def _parse_day_spec(day_part):
    """Parse 'Mo-Fr', 'Mo,We,Fr', 'Su-Th' or 'Mo' into a list of day
    abbreviations; PH and SH are skipped. None when a piece is not a day
    (such as 'Daily'), so the caller treats the string as unreadable."""
    days = []
    for segment in day_part.split(","):
        segment = segment.strip()
        if not segment:
            continue
        range_match = re.fullmatch(
            r"(Mo|Tu|We|Th|Fr|Sa|Su)-(Mo|Tu|We|Th|Fr|Sa|Su)", segment
        )
        if range_match:
            days.extend(_day_range_to_list(range_match.group(1), range_match.group(2)))
        elif segment in DAY_ORDER:
            days.append(segment)
        elif segment not in HOLIDAYS:
            return None
    return days


# ---------------------------------------------------------------------------
# Address resolution
# ---------------------------------------------------------------------------


def resolve_address(tags):
    """Return (full_address, postcode) from the element's own addr:* tags.

    When the tags give no address, full_address is empty. The merger asks
    Nominatim for a guess later, and only if Google has no address either.
    """
    postcode = tags.get("addr:postcode", "").strip()

    # Priority 1
    full = tags.get("addr:full", "").strip()
    if full:
        return full, postcode

    # Priority 2 — the addr:* parts joined. A city or postcode alone (e.g.
    # just "Petaling Jaya") does not count as an address.
    if tags.get("addr:housenumber") or tags.get("addr:street"):
        parts = [
            tags.get("addr:housenumber", ""),
            tags.get("addr:street", ""),
            tags.get("addr:city", ""),
            tags.get("addr:state", ""),
            tags.get("addr:postcode", ""),
        ]
        return ", ".join(p.strip() for p in parts if p.strip()), postcode

    return "", postcode


# ---------------------------------------------------------------------------
# Build row
# ---------------------------------------------------------------------------


def build_row(el, extracted_at):
    tags = el.get("tags", {})
    lat, lon = get_coords(el)

    name = _first(tags.get("name"), tags.get("name:en"), tags.get("brand"))
    # The brand tag only. OSM's operator tag says who runs the place (the
    # city council, a company), not a brand, so it is not used.
    brand = _first(tags.get("brand"))
    phone = _first(tags.get("phone"), tags.get("contact:phone"))
    website = _first(tags.get("website"), tags.get("contact:website"))
    cuisine_raw = tags.get("cuisine", "")
    halal_tag = tags.get("diet:halal", "")
    hours_raw = tags.get("opening_hours", "")

    amenity_type = resolve_amenity_type(tags)
    full_address, postcode = resolve_address(tags)
    day_dict, is_24_7 = parse_opening_hours(hours_raw)

    return {
        "osm_id": str(el.get("id", "")),
        "osm_type": el.get("type", ""),
        "name": name,
        "amenity_type": amenity_type,
        "brand": brand,
        "phone": phone,
        "website": website,
        "latitude": str(lat) if lat != "" else "",
        "longitude": str(lon) if lon != "" else "",
        "full_address": full_address,
        "postcode": postcode,
        "street": tags.get("addr:street", "").strip(),
        "hours_raw": hours_raw,
        "monday": day_dict["monday"],
        "tuesday": day_dict["tuesday"],
        "wednesday": day_dict["wednesday"],
        "thursday": day_dict["thursday"],
        "friday": day_dict["friday"],
        "saturday": day_dict["saturday"],
        "sunday": day_dict["sunday"],
        "is_24_7": str(is_24_7),
        "cuisine_raw": cuisine_raw,
        "halal_tag": halal_tag,
        "source": "osm",
        "extracted_at": extracted_at,
    }


# ---------------------------------------------------------------------------
# F&B extraction (step 1/3)
# ---------------------------------------------------------------------------


def extract_fnb(extracted_at):
    """Return one row per restaurant, for OSM_RAW_CSV."""
    elements = fetch_fnb_elements()
    rows = []
    total = len(elements)
    for i, el in enumerate(elements, start=1):
        if i % 100 == 0 or i == total:
            print(f"  Processing element {i}/{total}…")
        rows.append(build_row(el, extracted_at))
    return rows


# ---------------------------------------------------------------------------
# Area extraction (step 2/3)
# ---------------------------------------------------------------------------

# The areas are PJ's official numbered sections (SS 2, Seksyen 14, PJU 6, ...):
# the admin_level 10 boundaries listed as members of the PJ relation. They
# cover the whole city with no gaps or overlaps, so every restaurant falls
# inside exactly one.
SECTIONS_QUERY = """
[out:json][timeout:120];
relation["name"="Petaling Jaya"]["admin_level"="7"];
rel(r)["boundary"="administrative"]["admin_level"="10"];
out geom;
""".strip()

# The familiar named places (Bandar Utama, Taman Megah, ...). Many are only a
# dot, so they are not areas themselves: clean_osm_areas.py adds the names of
# those inside each section to that section's name.
PLACES_QUERY = """
[out:json][timeout:120];
area["name"="Petaling Jaya"]["admin_level"="7"]->.pj;
(
  node(area.pj)["place"~"^(suburb|neighbourhood|quarter)$"];
  relation(area.pj)["place"~"^(suburb|neighbourhood|quarter)$"];
);
out geom;
""".strip()


def _element_to_shape(el):
    """Build an OSM element's geometry with osm2geojson.

    NODE     → Point
    RELATION → Polygon, or MultiPolygon when the area has separate pieces.
               Member roles are followed, so a hole stays a hole.
    Returns a shapely geometry, or None if nothing could be built.
    A relation must come from an `out geom` query.
    """
    el = copy.deepcopy(el)  # osm2geojson marks the members it has used
    for member in el.get("members", []):
        # A way listed with no role is read as part of the outer edge.
        if member.get("type") == "way" and not member.get("role"):
            member["role"] = "outer"

    shapes = osm2geojson.json2shapes({"elements": [el]})
    if not shapes:
        return None
    geom = shapes[0]["shape"]
    # osm2geojson always returns a relation as a MultiPolygon; unwrap one piece.
    if geom.geom_type == "MultiPolygon" and len(geom.geoms) == 1:
        geom = geom.geoms[0]
    return geom


def _shape_to_geojson(geom):
    """Return a shapely geometry as a GeoJSON string ('' for None).
    GeoJSON coordinate order is always [longitude, latitude]."""
    return json.dumps(mapping(geom)) if geom is not None else ""


def _area_rows(query, extracted_at, area_type=None):
    """Run an Overpass query and return one row per element. The row's type
    is area_type when given, otherwise the element's place tag."""
    resp = _get(OVERPASS_URL, data={"data": query})
    elements = resp.json().get("elements", [])

    rows = []
    for el in elements:
        tags = el.get("tags", {})
        rows.append(
            {
                "osm_id": str(el.get("id", "")),
                "name": tags.get("name", ""),
                "type": area_type or tags.get("place", ""),
                "boundary_geojson": _shape_to_geojson(_element_to_shape(el)),
                "source": "osm",
                "extracted_at": extracted_at,
            }
        )
    return rows


def extract_areas(extracted_at):
    """Return (section rows for OSM_AREAS_CSV, named place rows for
    OSM_PLACES_CSV)."""
    print("  Sending section Overpass query…")
    # Every section is a numbered section of the city: "quarter" in categories.json.
    sections = _area_rows(SECTIONS_QUERY, extracted_at, area_type="quarter")
    print(f"  Sections: {len(sections)}")

    print("  Sending named place Overpass query…")
    places = _area_rows(PLACES_QUERY, extracted_at)
    print(f"  Named places: {len(places)}")

    return sections, places


# ---------------------------------------------------------------------------
# City extraction (step 3/3)
# ---------------------------------------------------------------------------

CITY_QUERY = """
[out:json][timeout:120];
relation["name"="Petaling Jaya"]["admin_level"="7"];
out geom;
""".strip()

# {lat} and {lon} are a point inside the city. The boundaries that contain
# that point are its parents: admin_level 4 is the state, 2 is the country.
PARENTS_QUERY = """
[out:json][timeout:60];
is_in({lat},{lon})->.parents;
area.parents["boundary"="administrative"]["admin_level"~"^(2|4)$"];
out tags;
""".strip()

def _lookup_state_country(geom):
    """Return (state, country): the names of the admin_level 4 and 2
    boundaries that contain a point inside the city boundary.

    Raises when the lookup still fails after the retries in _get(), or when
    OSM sends no state or no country, so no file is written. There is no
    default value: a guessed state or country would go into the database as
    if OSM had said it.
    """
    if geom is None:
        raise RuntimeError("no city boundary to look up the state and country from")
    point = geom.representative_point()  # always inside the boundary
    query = PARENTS_QUERY.format(lat=round(point.y, 7), lon=round(point.x, 7))
    resp = _get(OVERPASS_URL, data={"data": query})

    found = {}
    for el in resp.json().get("elements", []):
        tags = el.get("tags", {})
        found[tags.get("admin_level")] = tags.get("name", "")

    state, country = found.get("4"), found.get("2")
    missing = [what for what, value in (("state", state), ("country", country)) if not value]
    if missing:
        raise RuntimeError(f"OSM sent no {' and no '.join(missing)} for the city")
    return state, country


def extract_city(extracted_at):
    """Return the one city row for OSM_CITY_CSV. Raises when OSM sends no
    city boundary, or no state or country for it, so no file is written."""
    print("  Sending city Overpass query…")
    resp = _get(OVERPASS_URL, data={"data": CITY_QUERY})
    elements = resp.json().get("elements", [])
    print(f"  Raw city elements: {len(elements)}")

    relation = next((e for e in elements if e.get("type") == "relation"), None)
    if relation is None:
        raise RuntimeError("OSM sent no Petaling Jaya boundary relation")

    tags = relation.get("tags", {})
    geom = _element_to_shape(relation)
    geojson = _shape_to_geojson(geom)

    print("  Looking up state and country…")
    state, country = _lookup_state_country(geom)

    return [
        {
            "osm_id": str(relation.get("id", "")),
            "name": tags.get("name", "Petaling Jaya"),
            "state": state,
            "country": country,
            "boundary_geojson": geojson,
            "source": "osm",
            "extracted_at": extracted_at,
        }
    ]


# ---------------------------------------------------------------------------
# Nearby places (step 4/4)
# ---------------------------------------------------------------------------

# Places near restaurants (offices, schools, malls, stations, ...) are looked
# for in the box around PJ widened by this much on every side, so a place just
# across the city border still counts, and every restaurant has a station.
NEARBY_MARGIN_M = 3000


def _osm_label_list(column):
    """Return [(value, labels), ...] from a categories.json column whose values
    list OSM labels, in file order. Each label is a list of conditions
    [(OSM key, OSM value or "*"), ...] that must all hold: "a=b&c=d" is two."""
    return [
        (value, [[tuple(part.split("=", 1)) for part in label.split("&")]
                 for label in detail["osm"]])
        for value, detail in get_column(column)["values"].items()
    ]


NEARBY_KINDS = _osm_label_list("nearby_place.kind")
STATION_TYPES = _osm_label_list("nearby_context.station_type")
# Kinds whose parts OSM often maps as places of the same kind (a university's
# faculties, a school's hall): a place inside a bigger one is a part of it.
PARTS_INSIDE_KINDS = {
    kind for kind, detail in get_column("nearby_place.kind")["values"].items() if detail.get("parts_inside")
}


def _has_label(tags, labels):
    """True if the tags meet every condition of one of the labels; "*"
    matches any value."""
    return any(
        all(key in tags and value in ("*", tags[key]) for key, value in label)
        for label in labels
    )


def _first_match(tags, label_list):
    """The first value whose OSM labels the tags carry, or None."""
    return next((value for value, labels in label_list if _has_label(tags, labels)), None)


def _nearby_query(bounds):
    """Overpass query for every nearby kind inside bounds (west, south, east,
    north) widened by NEARBY_MARGIN_M."""
    west, south, east, north = bounds
    pad_lat = NEARBY_MARGIN_M / 111_320
    pad_lon = NEARBY_MARGIN_M / (111_320 * math.cos(math.radians((south + north) / 2)))
    bbox = f"{south - pad_lat:.6f},{west - pad_lon:.6f},{north + pad_lat:.6f},{east + pad_lon:.6f}"
    lines = []
    for _, labels in NEARBY_KINDS:
        for label in labels:
            filters = "".join(f'["{key}"]' if value == "*" else f'["{key}"="{value}"]' for key, value in label)
            lines.append(f"  nwr{filters};")
    # out geom: outlines too, so a faculty can be found inside its campus
    return "\n".join([f"[out:json][timeout:180][bbox:{bbox}];", "(", *lines, ");", "out geom;"])


def _element_pin(el):
    """(lat, lon) of an element: a node's own point, otherwise the middle of
    its bounding box (what Overpass calls its center). (None, None) if unknown."""
    if el.get("type") == "node":
        return el.get("lat"), el.get("lon")
    b = el.get("bounds")
    if not b:
        return None, None
    return (b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2


def _mark_parts(rows, elements):
    """Fill part_of for places of a PARTS_INSIDE_KINDS kind whose pin lies
    inside the outline of a bigger place of the same kind, with the smallest
    such place, e.g. "Fakulti Kejuruteraan (way 992791287)". rows[i] belongs
    to elements[i]. A place with a part_of is not counted later."""
    outlines = {}  # kind -> [(row index, shape)]
    for i, (row, el) in enumerate(zip(rows, elements)):
        if row["kind"] in PARTS_INSIDE_KINDS and el.get("type") in ("way", "relation"):
            geom = _element_to_shape(el)
            if geom is not None and geom.geom_type in ("Polygon", "MultiPolygon") and geom.area > 0:
                outlines.setdefault(row["kind"], []).append((i, geom))
    own_area = {i: geom.area for shapes in outlines.values() for i, geom in shapes}

    for i, row in enumerate(rows):
        if row["kind"] not in PARTS_INSIDE_KINDS:
            continue
        pin = Point(row["longitude"], row["latitude"])
        bigger = [
            (geom.area, j) for j, geom in outlines.get(row["kind"], [])
            if j != i and geom.area > own_area.get(i, 0) and geom.contains(pin)
        ]
        if bigger:
            j = min(bigger)[1]
            parent = rows[j]
            row["part_of"] = f"{parent['name'] or '(no name)'} ({parent['osm_type']} {parent['osm_id']})"


def extract_nearby(extracted_at, city_rows):
    """Return one row per nearby place (office, school, ..., station) in and
    around the city, for OSM_NEARBY_CSV. A station also gets its station_type;
    a part of a bigger place (a faculty of a university) gets part_of."""
    raw = city_rows[0].get("boundary_geojson", "") if city_rows else ""
    if not raw:
        raise RuntimeError("no city boundary to look for nearby places around")
    print("  Sending nearby place Overpass query…")
    resp = _get(OVERPASS_URL, data={"data": _nearby_query(shape(json.loads(raw)).bounds)})

    rows, elements = [], []
    for el in resp.json().get("elements", []):
        tags = el.get("tags", {})
        kind = _first_match(tags, NEARBY_KINDS)
        lat, lon = _element_pin(el)
        if kind is None or lat is None or lon is None:
            continue
        rows.append(
            {
                "osm_id": str(el.get("id", "")),
                "osm_type": el.get("type", ""),
                "kind": kind,
                "name": tags.get("name") or tags.get("name:en", ""),
                "station_type": (_first_match(tags, STATION_TYPES) or "Other") if kind == "station" else "",
                "part_of": "",
                "latitude": lat,
                "longitude": lon,
                "source": "osm",
                "extracted_at": extracted_at,
            }
        )
        elements.append(el)
    _mark_parts(rows, elements)

    counts = {kind: sum(1 for r in rows if r["kind"] == kind) for kind, _ in NEARBY_KINDS}
    print("  Nearby places: " + ", ".join(f"{n} {kind}" for kind, n in counts.items())
          + f" ({sum(1 for r in rows if r['part_of'])} are parts of a bigger place)")
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main():
    # UTC with its time zone, e.g. 2026-10-23T02:10:00+00:00
    extracted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"\n{'='*60}")
    print(f"FoodSight OSM Extractor  |  {extracted_at}")
    print(f"{'='*60}\n")

    # Every query runs before any file is written: if one fails, the run
    # stops here and the files of the last successful run stay as they were.
    print("[1/4] Extracting F&B restaurant data…")
    fnb_rows = extract_fnb(extracted_at)

    print("\n[2/4] Extracting sections and named places…")
    section_rows, place_rows = extract_areas(extracted_at)

    print("\n[3/4] Extracting city boundary data…")
    city_rows = extract_city(extracted_at)

    print("\n[4/4] Extracting nearby places (offices, schools, stations, ...)…")
    nearby_rows = extract_nearby(extracted_at, city_rows)

    outputs = [
        (OSM_RAW_CSV, OSM_RAW_COLUMNS, fnb_rows),
        (OSM_AREAS_CSV, AREAS_COLUMNS, section_rows),
        (OSM_PLACES_CSV, AREAS_COLUMNS, place_rows),
        (OSM_CITY_CSV, CITY_COLUMNS, city_rows),
        (OSM_NEARBY_CSV, NEARBY_COLUMNS, nearby_rows),
    ]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for path, columns, rows in outputs:
        _write_csv(path, columns, rows)

    print(f"\n{'='*60}")
    print("Extraction complete. All queries succeeded; files written:")
    for path, _, rows in outputs:
        print(f"  {path:<40} {len(rows)} rows")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
