"""
merge_data.py — Combine OSM + Google extracted data into one dataset, by rules
only (stage 3). No AI is used here.

  - Joins OSM (primary) with Google matches by osm_id, and keeps OSM's
    osm_type (node or way) with it
  - name, phone, website, full_address, postcode and street: a value both
    sources agree on (or that only one has) is used. When both have different
    values, the field is left empty and both values go to the restaurant's
    "conflicts"; the AI in profile_data.py (stage 4) chooses a source, in the
    same call that profiles the restaurant, and the value is copied from it.
  - Opening hours: the whole week from Google if it has hours, else from
    OSM. is_24_7 is true only when all 7 days are 00:00-24:00.
  - Location: OSM's pin (Google's only when OSM has none). (Whether the
    Google place is the same restaurant at all is decided earlier, by the
    match rules in extract_google.py.) When neither source has an address,
    Nominatim is asked to guess one from the pin (only then, and cached in
    NOMINATIM_CACHE_FILE); failed lookups are listed in LOOKUP_FAILED_FILE.
    A missing postcode or street is read from the final address (in stage 4
    when the address itself waits for the AI).
  - business_status: Google's; UNKNOWN for a restaurant with no Google match
  - Assigns each restaurant to the area (official section) that contains it
  - Nearby context: counts the offices, schools, universities, hospitals,
    malls and hotels within each kind's radius of the restaurant's pin, and
    finds the nearest train station (osm_nearby_cleaned.csv; plain distance
    math). Each restaurant's nearby_places lists the exact places counted,
    with their distance; the top-level nearby_places lists every place once
  - Attaches reviews and facilities. Every choice and its reason goes to
    merge_log.
  - Adds the restaurants registered by their business and approved by an
    admin (submissions.py, read from PostgreSQL): source "submitted", with
    the business's own values, the section and nearby counts from their pin.
    Every other record has source "extracted".
  - Writes data/3_merged/pj_merged.json

Usage:
  python merge_data.py

Requires: pip install requests shapely
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from shapely.geometry import Point, shape

# Lets `src` be imported when this file is run directly, not through run_3_merging.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.cache_saving import save_due, save_json
from src.categories import get_column

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OSM_CSV        = os.path.join("data", "2_cleaned", "osm_cleaned.csv")
GOOGLE_CSV     = os.path.join("data", "2_cleaned", "google_cleaned.csv")
REVIEWS_CSV    = os.path.join("data", "2_cleaned", "reviews_cleaned.csv")
AREAS_CSV      = os.path.join("data", "2_cleaned", "osm_areas_cleaned.csv")
CITY_CSV       = os.path.join("data", "2_cleaned", "osm_city_cleaned.csv")
FACILITIES_CSV = os.path.join("data", "2_cleaned", "google_facilities_cleaned.csv")
NEARBY_CSV     = os.path.join("data", "2_cleaned", "osm_nearby_cleaned.csv")

# Nearby places (nearby_place.kind in src/reference/categories.json) counted around each
# restaurant's pin: {kind: (radius in metres, nearby_context column)}. Stations
# are not counted; the nearest one is kept instead.
NEARBY_COUNTED = {
    kind: (detail["radius_m"], detail["column"])
    for kind, detail in get_column("nearby_place.kind")["values"].items()
    if "radius_m" in detail
}

# Hand-checked Google matches (written by hand or by the admin review page). The merger
# reads only "pin": "google", the restaurant whose Google pin a person chose over OSM's.
OVERRIDES_FILE = os.path.join("src", "reference", "google_match_overrides.json")

OUTPUT_FILE = os.path.join("data", "3_merged", "pj_merged.json")
# Review file, rewritten on every run: the restaurants with no address from
# either source whose Nominatim lookup failed. A later run asks Nominatim again
# for these only (its other answers are cached).
LOOKUP_FAILED_FILE = os.path.join("data", "review", "address_lookup_failed.json")

# Nominatim (OpenStreetMap's address lookup) guesses an address from a pin.
# It is asked only for restaurants with no address from OSM tags or Google.
# Answers are cached by pin, so a later run does not ask again; failed
# lookups are not cached. Usage policy: at most one request per second.
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_CACHE_FILE = os.path.join("data", "cache", "nominatim_cache.json")
NOMINATIM_SLEEP = 1.1
NOMINATIM_RETRY_WAITS = [2, 5]
USER_AGENT = "FoodSight-FYP/1.0"

DAY_FIELDS = ["monday", "tuesday", "wednesday", "thursday", "friday",
              "saturday", "sunday"]

# Fields present in BOTH CSVs. Different values go to the AI in stage 4,
# which picks a source.
CONFLICT_FIELDS = ["name", "phone", "website"]

# Address fields: OSM column -> Google column. Compared like CONFLICT_FIELDS,
# but the AI may also reject both values (the field then stays empty).
LOCATION_FIELDS = {
    "full_address": "formatted_address",
    "postcode": "postcode",
    "street": "street",
}

# A comma-separated address part that starts with one of these is a street.
_ROAD = re.compile(
    r"(?:Jalan|Jln|Lorong|Lrg|Persiaran|Lebuhraya|Lebuh|Lingkaran|Lintasan|Laluan|Road)\b",
    re.IGNORECASE,
)

# merge_log resolution of a postcode or street that neither source had, while
# the address it is read from waits for the AI (stage 4 reads it then)
WAITING_FOR_ADDRESS = "waiting_for_address"


# ---------------------------------------------------------------------------
# Small value helpers
# ---------------------------------------------------------------------------

def _s(v):
    """Normalise to a stripped string."""
    return (v or "").strip()


def nz(v):
    """Empty string → None, else stripped value."""
    v = _s(v)
    return v if v else None


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def to_bool(v):
    return _s(v).lower() in ("true", "1", "yes")


def _same_key(field, value):
    """Text used to decide whether two address values are the same:
    postcodes by their digits; streets and addresses ignoring capitals,
    spaces, punctuation, and Jln versus Jalan."""
    v = value.lower()
    if field == "postcode":
        return re.sub(r"\D", "", v)
    v = re.sub(r"\bjln\b", "jalan", v)
    return re.sub(r"[\W_]+", "", v)


def _postcode_in(address):
    """The postcode written in an address: its last 5-digit number, or None."""
    found = re.findall(r"(?<!\d)\d{5}(?!\d)", address)
    return found[-1] if found else None


def _street_in(address):
    """The street written in an address: the first comma-separated part that
    starts with a road word (Jalan, Jln, Lorong, Persiaran, ...), or None."""
    for part in address.split(","):
        part = part.strip()
        if _ROAD.match(part):
            return part
    return None


def _log_entry(osm_v, google_v, chosen, source, resolution, reason):
    """One merge_log record: both values, the choice, and why."""
    return {
        "osm_value": osm_v,
        "google_value": google_v,
        "chosen_value": chosen,
        "chosen_source": source,
        "resolution": resolution,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# CSV loaders
# ---------------------------------------------------------------------------

def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_inputs():
    osm_rows = read_csv(OSM_CSV)
    if not osm_rows:
        sys.exit(f"ERROR: {OSM_CSV} not found or empty. Run preprocessing first.")

    google_by_id = {r["osm_id"]: r for r in read_csv(GOOGLE_CSV) if r.get("osm_id")}

    reviews_by_id = {}
    for r in read_csv(REVIEWS_CSV):
        reviews_by_id.setdefault(r.get("osm_id", ""), []).append(r)

    area_rows = read_csv(AREAS_CSV)

    city_rows = read_csv(CITY_CSV)
    city = None
    if city_rows:
        row = city_rows[0]
        city = {
            "name":             _s(row.get("name")),
            "state":            _s(row.get("state")),
            "country":          _s(row.get("country")),
            "boundary_geojson": _s(row.get("boundary_geojson")),
        }

    facilities_by_id = {}
    for r in read_csv(FACILITIES_CSV):
        oid = r.get("osm_id", "")
        facilities_by_id.setdefault(oid, []).append({
            "name":     _s(r.get("facility_name")),
            "category": _s(r.get("facility_category")),
        })

    return osm_rows, google_by_id, reviews_by_id, area_rows, city, facilities_by_id


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def load_cache(path=None):
    """Load a cache file (NOMINATIM_CACHE_FILE unless another path is given)."""
    path = path or NOMINATIM_CACHE_FILE
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache, path=None):
    """Save a cache file (NOMINATIM_CACHE_FILE unless another path is given)."""
    save_json(path or NOMINATIM_CACHE_FILE, cache)


# ---------------------------------------------------------------------------
# Area index (shapely)
# ---------------------------------------------------------------------------

def build_area_index(area_rows):
    """Return the area shapes for area assignment, as a list of
    (name, type, shapely_geometry)."""
    polygons = []
    for row in area_rows:
        raw = _s(row.get("boundary_geojson"))
        name = _s(row.get("name"))
        atype = _s(row.get("type"))
        if not raw or not name:
            continue
        try:
            geojson = json.loads(raw)
        except json.JSONDecodeError:
            continue

        gtype = geojson.get("type")
        if gtype in ("Polygon", "MultiPolygon"):
            try:
                geom = shape(geojson)
                if not geom.is_valid:
                    geom = geom.buffer(0)  # repair self-intersections
                if not geom.is_empty:
                    polygons.append((name, atype, geom))
            except Exception:
                continue
    return polygons


def assign_area(lat, lon, polygons):
    """Return (area_name, area_type) of the area that contains the point,
    or (None, None). The areas cover the whole city without overlapping,
    so a restaurant inside the city is inside exactly one."""
    if lat is None or lon is None:
        return None, None

    pt = Point(lon, lat)  # GeoJSON order: x=lon, y=lat

    for name, atype, geom in polygons:
        try:
            if geom.contains(pt):
                return name, atype
        except Exception:
            continue
    return None, None


# ---------------------------------------------------------------------------
# Nearby context
# ---------------------------------------------------------------------------

def load_nearby():
    """Return the nearby places from NEARBY_CSV as dicts {osm_type, osm_id,
    kind, name, station_type, lat, lon, fetched_at}, or None when the file is
    missing (then no restaurant gets a nearby context)."""
    if not os.path.exists(NEARBY_CSV):
        return None
    places = []
    for row in read_csv(NEARBY_CSV):
        lat, lon = to_float(row.get("latitude")), to_float(row.get("longitude"))
        # A part of a bigger place (a faculty of a university) is never
        # counted; clean_osm_nearby.py already drops these rows.
        if lat is None or lon is None or _s(row.get("part_of")):
            continue
        places.append({
            "osm_type": _s(row.get("osm_type")),
            "osm_id": to_int(row.get("osm_id")),
            "kind": _s(row.get("kind")),
            "name": nz(row.get("name")),
            "station_type": nz(row.get("station_type")),
            "lat": lat,
            "lon": lon,
            "fetched_at": nz(row.get("extracted_at")),
        })
    return places


def _distance_m(lat1, lon1, lat2, lon2):
    """Distance in metres between two points (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def nearby_context(lat, lon, places):
    """What is around a pin. Returns (context, counted):

      context — for each counted kind, how many places lie within its radius
                (0 is a real answer), and the nearest train station with its
                distance and type; osm_fetched_at is when OSM sent the places
      counted — the exact places behind those counts, one dict {osm_type,
                osm_id, kind, distance_m} each, by kind and then nearest first

    Both come from the same loop, so for each kind the number of counted
    places always equals its count. Stations are not in counted. (None, [])
    when there is no pin or no nearby places."""
    if lat is None or lon is None or not places:
        return None, []
    context = {column: 0 for _, column in NEARBY_COUNTED.values()}
    counted = []
    nearest, nearest_m = None, None
    for place in places:
        if place["kind"] == "station":
            d = _distance_m(lat, lon, place["lat"], place["lon"])
            if nearest_m is None or d < nearest_m:
                nearest, nearest_m = place, d
        elif place["kind"] in NEARBY_COUNTED:
            radius, column = NEARBY_COUNTED[place["kind"]]
            # 1 degree of latitude is about 111 km: skip far places cheaply
            if abs(place["lat"] - lat) * 111_320 > radius:
                continue
            d = _distance_m(lat, lon, place["lat"], place["lon"])
            if d <= radius:
                context[column] += 1
                counted.append({"osm_type": place["osm_type"], "osm_id": place["osm_id"],
                                "kind": place["kind"], "distance_m": round(d)})
    context["nearest_station"] = nearest["name"] if nearest else None
    context["station_type"] = nearest["station_type"] if nearest else None
    context["station_distance_m"] = round(nearest_m) if nearest else None
    context["osm_fetched_at"] = places[0]["fetched_at"]
    kind_order = list(NEARBY_COUNTED)
    counted.sort(key=lambda c: (kind_order.index(c["kind"]), c["distance_m"]))
    return context, counted


def nearby_place_list(places):
    """Every nearby place (stations too) for pj_merged.json's top-level
    nearby_places, which the loader writes to public.nearby_place."""
    return [
        {
            "osm_type": p["osm_type"],
            "osm_id": p["osm_id"],
            "kind": p["kind"],
            "name": p["name"],
            "station_type": p["station_type"] if p["kind"] == "station" else None,
            "latitude": p["lat"],
            "longitude": p["lon"],
            "osm_fetched_at": p["fetched_at"],
        }
        for p in places or []
    ]


# ---------------------------------------------------------------------------
# Field classification (Rules 1–4)
# ---------------------------------------------------------------------------

def classify(osm_val, google_val, key=str.lower):
    """
    Return (kind, chosen_value, chosen_source) where kind is one of:
      both_empty | single_osm | single_google | identical | conflict
    Two values are identical when key() gives the same text for both.
    For 'conflict', chosen_value/source are None (needs resolution).
    """
    o = _s(osm_val)
    g = _s(google_val)
    if not o and not g:
        return "both_empty", None, None
    if o and not g:
        return "single_osm", o, "osm"
    if g and not o:
        return "single_google", g, "google"
    if key(o) == key(g):
        return "identical", o, "both"
    return "conflict", None, None


# ---------------------------------------------------------------------------
# Rule-based decisions
# ---------------------------------------------------------------------------

def resolve_hours(osm, google, resolved, merge_log):
    """The whole week comes from one source, no AI: Google's if Google
    has any hours, otherwise OSM's, otherwise every day unknown (None).
    A day is its opening times, "Closed", or None. is_24_7 is true only when
    all 7 days are "00:00-24:00", whatever the source."""
    def has_hours(row):
        return any(_s(row.get(day)) for day in DAY_FIELDS)

    if has_hours(google):
        week, source, reason = google, "google", "Google has hours, so its whole week is used"
    elif has_hours(osm):
        week, source, reason = osm, "osm", "Google has no hours, so OSM's whole week is used"
    else:
        week, source, reason = {}, "none", "Neither source has hours"

    for day in DAY_FIELDS:
        value = _s(week.get(day)) or None
        resolved[day] = value
        merge_log[day] = _log_entry(_s(osm.get(day)), _s(google.get(day)), value, source, "rule", reason)

    is_24_7 = all(resolved[day] == "00:00-24:00" for day in DAY_FIELDS)
    resolved["is_24_7"] = "true" if is_24_7 else "false"
    merge_log["is_24_7"] = _log_entry(
        _s(osm.get("is_24_7")), _s(google.get("is_24_7")), is_24_7, source, "rule",
        "True only when all 7 days are 00:00-24:00",
    )


def load_pin_choices(path=OVERRIDES_FILE):
    """{osm_id: "google"} for the restaurants whose override asks for Google's pin
    ("pin": "google", chosen on the admin review page for a Google match whose pins
    are far apart). Every other restaurant keeps the pin rule in resolve_coordinates()."""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        overrides = json.load(f).get("overrides") or {}
    return {str(osm_id): "google" for osm_id, entry in overrides.items()
            if (entry or {}).get("pin") == "google" and (entry or {}).get("place_id")}


def resolve_coordinates(osm, google, resolved, merge_log, pin_choice=None):
    """OSM's pin is used; Google's only when OSM has none, or when a person chose
    Google's pin (pin_choice "google", from the override file). No AI.
    Latitude and longitude always come from the same source."""
    osm_pin = (_s(osm.get("latitude")), _s(osm.get("longitude")))
    google_pin = (_s(google.get("latitude")), _s(google.get("longitude")))
    if pin_choice == "google" and all(google_pin):
        pin, source, reason = google_pin, "google", "Google's pin, chosen by a person (google_match_overrides.json)"
        for field, osm_v, google_v, value in zip(("latitude", "longitude"), osm_pin, google_pin, pin):
            resolved[field] = value
            merge_log[field] = _log_entry(osm_v, google_v, value, source, "override", reason)
        return
    if all(osm_pin):
        pin, source, reason = osm_pin, "osm", "OSM's pin is used whenever it has one"
    elif all(google_pin):
        pin, source, reason = google_pin, "google", "OSM had no pin, so Google's is used"
    else:
        pin, source, reason = (None, None), "none", "Neither source had a pin"

    for field, osm_v, google_v, value in zip(
        ("latitude", "longitude"), osm_pin, google_pin, pin
    ):
        resolved[field] = value
        merge_log[field] = _log_entry(osm_v, google_v, value, source, "rule", reason)


def compare_location(osm, google, resolved, merge_log, conflicts):
    """Compare full_address, postcode and street between OSM and Google.

    Same value -> used. Only one source has it -> used. Both differ -> left
    empty and added to conflicts for the AI in stage 4. Returns the fields
    neither source had.
    """
    missing = set()
    for field, google_column in LOCATION_FIELDS.items():
        osm_v = _s(osm.get(field))
        google_v = _s(google.get(google_column))
        kind, chosen, source = classify(
            osm_v, google_v, key=lambda v, f=field: _same_key(f, v)
        )
        if kind == "both_empty":
            missing.add(field)
        elif kind in ("single_osm", "single_google"):
            resolved[field] = chosen
            merge_log[field] = _log_entry(
                osm_v, google_v, chosen, source, "single_source",
                f"Only {source.upper()} had a value",
            )
        elif kind == "identical":
            resolved[field] = chosen
            merge_log[field] = _log_entry(
                osm_v, google_v, chosen, "both", "both_identical", "Both sources agree"
            )
        else:
            resolved[field] = None
            conflicts[field] = {"osm_value": osm_v, "google_value": google_v}
    return missing


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def write_review_file(path, how_to_use, items):
    """Write a review file in data/review/, in the same layout as
    google_match_review.json: how_to_use, created_at, count, items. Rewritten
    on every run, with an empty list when there is nothing to review."""
    write_json(path, {
        "how_to_use": how_to_use,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "count": len(items),
        "items": items,
    })


def nominatim_guess(lat, lon, nominatim_cache, stats):
    """Nominatim's address guess for a pin, as (guess, error): guess is a
    string ('' when Nominatim has none), or None when the lookup failed, and
    then error says why. Answers are cached by pin; failures are not."""
    key = f"{float(lat):.6f},{float(lon):.6f}"
    if key in nominatim_cache:
        stats["nominatim_cached"] += 1
        return nominatim_cache[key], None

    last_exc = None
    for wait in [NOMINATIM_SLEEP] + NOMINATIM_RETRY_WAITS:
        time.sleep(wait)  # also keeps to at most one request per second
        try:
            resp = requests.get(
                NOMINATIM_URL,
                params={"lat": lat, "lon": lon, "format": "json"},
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            resp.raise_for_status()
            guess = _s(resp.json().get("display_name"))
            nominatim_cache[key] = guess
            stats["nominatim_made"] += 1
            return guess, None
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
    print(f"    Nominatim lookup failed for ({lat}, {lon}): {last_exc}")
    return None, f"{type(last_exc).__name__}: {last_exc}"


def fill_missing_address(resolved, merge_log, nominatim_cache, stats):
    """Fill the address that neither OSM nor Google had with Nominatim's
    guess for the pin. Returns the error text when the lookup failed, else None."""
    lat, lon = resolved.get("latitude"), resolved.get("longitude")
    guess, error = nominatim_guess(lat, lon, nominatim_cache, stats) if lat and lon else ("", None)
    resolved["full_address"] = guess or None
    if guess:
        merge_log["full_address"] = _log_entry(
            "", "", guess, "nominatim", "nominatim_guess",
            "Neither OSM tags nor Google gave an address, so Nominatim's "
            "guess from the pin is used",
        )
    elif guess is None:
        merge_log["full_address"] = _log_entry(
            "", "", None, "none", "unresolved",
            "No address from OSM tags or Google, and the Nominatim lookup "
            "failed; the next run tries again",
        )
    else:
        merge_log["full_address"] = _log_entry(
            "", "", None, "none", "not_found",
            "No address from OSM, Google or Nominatim",
        )
    return error


def read_parts_from_address(values, merge_log, fields):
    """Fill the postcode and street in `fields` (ones neither OSM nor Google
    had) by reading them from the final address, values["full_address"].
    Also used by profile_data.py, once the AI has chosen the address."""
    address = values.get("full_address") or ""
    for field, read in (("postcode", _postcode_in), ("street", _street_in)):
        if field not in fields:
            continue
        value = read(address) if address else None
        values[field] = value
        if value:
            merge_log[field] = _log_entry(
                "", "", value, "address", "from_address",
                "Neither OSM nor Google had one, so it was read from the address",
            )
        else:
            merge_log[field] = _log_entry(
                "", "", None, "none", "not_found",
                "Neither OSM nor Google had one, and the address has none",
            )


def fields_waiting_for_address(merge_log):
    """The postcode and street that stage 3 left to be read from the address
    the AI chooses (see WAITING_FOR_ADDRESS)."""
    return {field for field in ("postcode", "street")
            if (merge_log.get(field) or {}).get("resolution") == WAITING_FOR_ADDRESS}


def resolve_restaurant(osm, google, nominatim_cache, stats, pin_choice=None):
    """Decide every field the rules can decide. Returns (resolved, merge_log,
    conflicts, lookup_error):

      resolved     — field -> chosen value (None when empty, or when the AI
                     still has to choose)
      merge_log    — field -> how it was decided and why (see _log_entry)
      conflicts    — field -> {osm_value, google_value}: both sources have a
                     value and they differ; the AI in stage 4 chooses a source
      lookup_error — why the Nominatim lookup failed, or None
    """
    merge_log, resolved, conflicts = {}, {}, {}

    for field in CONFLICT_FIELDS:
        osm_v = _s(osm.get(field))
        google_v = _s(google.get(field))
        kind, chosen, source = classify(osm_v, google_v)
        resolved[field] = chosen
        if kind == "both_empty":
            continue  # not recorded in merge_log (no decision)
        if kind == "conflict":
            conflicts[field] = {"osm_value": osm_v, "google_value": google_v}
        elif kind == "identical":
            merge_log[field] = _log_entry(
                osm_v, google_v, chosen, "both", "both_identical", "Both sources agree"
            )
        else:
            merge_log[field] = _log_entry(
                osm_v, google_v, chosen, source, "single_source",
                f"Only {source.upper()} had a value",
            )

    resolve_coordinates(osm, google, resolved, merge_log, pin_choice)
    resolve_hours(osm, google, resolved, merge_log)
    missing = compare_location(osm, google, resolved, merge_log, conflicts)

    lookup_error = None
    if "full_address" in missing:
        lookup_error = fill_missing_address(resolved, merge_log, nominatim_cache, stats)
    parts = missing & {"postcode", "street"}
    if "full_address" in conflicts:
        # The address waits for the AI, so these are read from it in stage 4
        for field in parts:
            resolved[field] = None
            merge_log[field] = _log_entry(
                "", "", None, "none", WAITING_FOR_ADDRESS,
                "Neither OSM nor Google had one; it is read from the address "
                "once the AI has chosen it",
            )
    else:
        read_parts_from_address(resolved, merge_log, parts)
    return resolved, merge_log, conflicts, lookup_error


# ---------------------------------------------------------------------------
# Build final restaurant record
# ---------------------------------------------------------------------------

def build_record(osm, google, resolved, merge_log, conflicts, reviews, facilities, polygons,
                 nearby=None):
    has_google = bool(google)

    lat = to_float(resolved.get("latitude"))
    lon = to_float(resolved.get("longitude"))
    area_name, area_type = assign_area(lat, lon, polygons)
    context, counted = nearby_context(lat, lon, nearby)

    operating_hours = {d: nz(resolved.get(d)) for d in DAY_FIELDS}
    operating_hours["is_24_7"] = to_bool(resolved.get("is_24_7"))

    clean_reviews = [
        {
            "google_review_id": nz(r.get("google_review_id")),
            "author_name": _s(r.get("author_name")),
            "text": _s(r.get("text")),
            "individual_rating": to_int(r.get("individual_rating")),
            "published_at": nz(r.get("published_at")),
        }
        for r in reviews
    ]

    record = {
        # extracted (OpenStreetMap + Google) or submitted (submissions.py)
        "source": "extracted",
        "osm_id": _s(osm.get("osm_id")),
        # node (a point) or way (an outline, such as a building; its pin is the
        # outline's centre). OSM numbers each kind separately, so osm_id needs
        # it to name one object: openstreetmap.org/{osm_type}/{osm_id}
        "osm_type": _s(osm.get("osm_type")),
        "google_place_id": nz(google.get("google_place_id")) if has_google else None,
        "google_maps_uri": nz(google.get("google_maps_uri")) if has_google else None,
        "google_fetched_at": nz(google.get("google_fetched_at")) if has_google else None,
        # Google's short description (restaurant.editorial_summary); also a profiler hint
        "editorial_summary": nz(google.get("editorial_summary")) if has_google else None,
        # Not stored in the database: input for the profiler (restaurant_type)
        "google_primary_type": nz(google.get("google_primary_type")) if has_google else None,
        "google_maps_type_label": nz(google.get("google_maps_type_label")) if has_google else None,
        # Not stored either: the profiler sets avg_meal_price and tier from them
        "google_price_low": to_float(google.get("price_low")) if has_google else None,
        "google_price_high": to_float(google.get("price_high")) if has_google else None,
        "google_price_level": nz(google.get("price_level")) if has_google else None,
        "google_types": nz(google.get("google_types")) if has_google else None,
        "name": nz(resolved.get("name")),
        "amenity_type": nz(osm.get("amenity_type")),
        "brand": nz(osm.get("brand")),
        "phone": nz(resolved.get("phone")),
        "website": nz(resolved.get("website")),
        # UNKNOWN without a Google match: OSM cannot tell whether it still trades
        "business_status": (nz(google.get("business_status")) or "UNKNOWN") if has_google else "UNKNOWN",
        "latitude": lat,
        "longitude": lon,
        "full_address": nz(resolved.get("full_address")),
        "postcode": nz(resolved.get("postcode")),
        "street": nz(resolved.get("street")),
        "area_name": area_name,
        "area_type": area_type,
        "nearby_context": context,
        # The exact places behind the counts (public.restaurant_nearby_place)
        "nearby_places": counted,
        "operating_hours": operating_hours,
        "cuisine_raw": nz(osm.get("cuisine_raw")),
        "halal_tag": nz(osm.get("halal_tag")),
        "rating": {
            "rating_score":  to_float(google.get("rating_score")) if has_google else None,
            "total_reviews": to_int(google.get("total_reviews")) if has_google else None,
        },
        "facilities": facilities,
        "merge_log": merge_log,
        # Fields where the sources disagree: {field: {osm_value, google_value}}.
        # The AI in stage 4 chooses a source; empty when there is nothing to choose.
        "conflicts": conflicts,
        "reviews": clean_reviews,
    }
    return record, (area_name is not None), len(clean_reviews)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Merge OSM + Google data (rules only).")
    parser.parse_args()

    osm_rows, google_by_id, reviews_by_id, area_rows, city, facilities_by_id = load_inputs()

    polygons = build_area_index(area_rows)
    nearby = load_nearby()
    if nearby is None:
        print(f"WARNING: {NEARBY_CSV} not found, so no restaurant gets a nearby context. "
              "Run run_1_extraction.py (with OSM) and run_2_preprocessing.py first.")
    nominatim_cache = load_cache(NOMINATIM_CACHE_FILE)
    pin_choices = load_pin_choices()

    total = len(osm_rows)
    stats = {
        "google_matched": 0,
        "osm_only": 0,
        "with_conflicts": 0,
        "conflict_fields": 0,
        "nominatim_made": 0,
        "nominatim_cached": 0,
        "with_area": 0,
        "with_nearby": 0,
        "nearby_links": 0,
        "reviews_attached": 0,
        "submitted": 0,
    }

    restaurants = []
    lookup_failed = []  # -> LOOKUP_FAILED_FILE

    # The Nominatim cache is saved every SAVE_EVERY restaurants and when the
    # run stops early (Ctrl+C or an error), so a rerun asks only what is missing.
    try:
        for idx, osm in enumerate(osm_rows, start=1):
            if save_due(idx - 1):
                save_cache(nominatim_cache, NOMINATIM_CACHE_FILE)

            osm_id = osm.get("osm_id", "")
            google = google_by_id.get(osm_id, {})
            reviews = reviews_by_id.get(osm_id, [])
            name = _s(osm.get("name")) or "(unnamed)"

            try:
                resolved, merge_log, conflicts, lookup_error = resolve_restaurant(
                    osm, google, nominatim_cache, stats, pin_choices.get(osm_id)
                )
                facilities = facilities_by_id.get(osm_id, [])
                record, has_area, n_reviews = build_record(
                    osm, google, resolved, merge_log, conflicts, reviews, facilities,
                    polygons, nearby
                )
                restaurants.append(record)
                stats["with_nearby"] += record["nearby_context"] is not None
                stats["nearby_links"] += len(record["nearby_places"])
                stats["with_conflicts"] += bool(conflicts)
                stats["conflict_fields"] += len(conflicts)

                if lookup_error:
                    lookup_failed.append({
                        "osm_id": osm_id,
                        "name": record["name"] or name,
                        "latitude": record["latitude"],
                        "longitude": record["longitude"],
                        "error": lookup_error,
                    })

                if google:
                    stats["google_matched"] += 1
                else:
                    stats["osm_only"] += 1
                if has_area:
                    stats["with_area"] += 1
                stats["reviews_attached"] += n_reviews

                # Progress line
                if not google:
                    status = "OSM only (no Google match)"
                elif not conflicts:
                    status = "Google matched, sources agree"
                else:
                    status = f"Google matched, for the AI: {', '.join(conflicts)}"
                print(f"  [{idx}/{total}] {name[:28]:30} -> {status}")

            except Exception as exc:
                print(f"  [{idx}/{total}] {name[:28]:30} -> ERROR ({exc}) - skipped")
                continue
    except BaseException:
        print(f"\nStopped early: saving the Nominatim answers so far to {NOMINATIM_CACHE_FILE}.")
        print("Run the same command again; cached answers are not asked again.")
        save_cache(nominatim_cache, NOMINATIM_CACHE_FILE)
        raise

    save_cache(nominatim_cache, NOMINATIM_CACHE_FILE)

    # Restaurants registered by their business and approved by an admin
    from src.s3_mergers.submissions import load_submissions, submission_record
    submissions = load_submissions()
    if submissions is None:
        print("  Business submissions: none (the table business_submission does not exist yet: "
              "run db/migrations/028_business_submission.sql)")
    for sub in submissions or []:
        record, has_area = submission_record(sub, polygons, nearby, city)
        restaurants.append(record)
        stats["submitted"] += 1
        stats["with_area"] += has_area
        stats["with_nearby"] += record["nearby_context"] is not None
        stats["nearby_links"] += len(record["nearby_places"])
        print(f"  [submitted] {record['name'][:28]:30} -> business submission {record['submission_id']}"
              + ("" if has_area else " (WARNING: its pin is in no section)"))

    # Build areas reference block
    areas_out = [
        {
            "osm_id": _s(a.get("osm_id")),
            "name": _s(a.get("name")),
            "type": _s(a.get("type")),
            "boundary_geojson": _s(a.get("boundary_geojson")),
        }
        for a in area_rows if _s(a.get("name"))
    ]

    output = {
        "city": city,
        "areas": areas_out,
        # Every nearby place, once (public.nearby_place); each restaurant's
        # nearby_places points to the ones it counted, by osm_type and osm_id
        "nearby_places": nearby_place_list(nearby),
        "restaurants": restaurants,
        "metadata": {
            "total_restaurants": len(restaurants),
            "google_matched": stats["google_matched"],
            "osm_only": stats["osm_only"],
            "submitted_restaurants": stats["submitted"],
            "restaurants_with_conflicts": stats["with_conflicts"],
            "conflict_fields": stats["conflict_fields"],
            "nominatim_calls_made": stats["nominatim_made"],
            "nominatim_calls_cached": stats["nominatim_cached"],
            "address_lookups_failed": len(lookup_failed),
            "areas_loaded": len(areas_out),
            "restaurants_with_area": stats["with_area"],
            "restaurants_without_area": len(restaurants) - stats["with_area"],
            "nearby_places_loaded": len(nearby or []),
            "restaurants_with_nearby_context": stats["with_nearby"],
            "nearby_place_links": stats["nearby_links"],
            "total_reviews_attached": stats["reviews_attached"],
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    }

    write_json(OUTPUT_FILE, output)
    write_review_file(
        LOOKUP_FAILED_FILE,
        "Restaurants with no address from OpenStreetMap or Google whose Nominatim "
        "lookup failed, so they have no address for now. Run python run_3_merging.py "
        "again: only these are looked up again (other answers come from the cache). "
        "Then run python run_4_profiling.py (its answers come from its cache).",
        lookup_failed,
    )

    # Final summary
    m = output["metadata"]
    print("\n" + "=" * 60)
    print("MERGE COMPLETE")
    print(f"  Total restaurants:        {m['total_restaurants']}")
    print(f"  Google matched:           {m['google_matched']}")
    print(f"  OSM only (no match):      {m['osm_only']}")
    print(f"  Submitted by a business:  {m['submitted_restaurants']} (approved or live business submissions)")
    print(f"  Sources disagree:         {m['restaurants_with_conflicts']} restaurants, "
          f"{m['conflict_fields']} fields (the AI chooses in run_4_profiling.py)")
    print(f"  Nominatim lookups made:   {m['nominatim_calls_made']} "
          f"(from cache: {m['nominatim_calls_cached']})")
    print(f"  Google pins chosen:       {len(pin_choices)} (by a person, in {OVERRIDES_FILE})")
    print(f"  Areas assigned:           {m['restaurants_with_area']}")
    print(f"  Nearby context:           {m['restaurants_with_nearby_context']} "
          f"(from {m['nearby_places_loaded']} nearby places; "
          f"{m['nearby_place_links']} restaurant-place links)")
    print(f"  Reviews attached:         {m['total_reviews_attached']}")
    print(f"  Output: {OUTPUT_FILE}")
    print(f"  Address lookups failed:   {m['address_lookups_failed']:>4} -> "
          f"{LOOKUP_FAILED_FILE} (run again to retry)")
    print("=" * 60)


if __name__ == "__main__":
    main()
