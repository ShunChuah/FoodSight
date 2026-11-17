"""
FoodSight — Data Validator
Validates the final merged + profiled JSON against the JSON Schema
BEFORE inserting into PostgreSQL.

Valid records   -> data/5_validated/pj_validated.json  (safe to insert)
Invalid records -> data/review/validation_invalid.json   (with error reasons)

Nearby places are checked first; a restaurant's nearby_places must point to
valid ones, and for each kind their number must equal its nearby_context count
(check_nearby_links). A restaurant must have no field still waiting for the
AI to choose between OSM and Google (check_conflicts_decided).

The checks also cover the database rules a schema cannot express, so a load
never stops halfway: a rating score always comes with total_reviews
(check_rating), no two restaurants share an osm_id, a google_place_id or a
submission_id (check_unique_ids), an extracted restaurant has its
OpenStreetMap IDs and a submitted one its submission instead
(check_source_ids), a restaurant's cuisines repeat no name and no rank
(check_cuisines), and every "date-time" can be read and has a time zone
(DATE_CHECKER).

The schema holds no value lists of its own. A field marked
"values_from": "table.column" gets its allowed values from src/reference/categories.json
when the schema is loaded.

Install: pip install jsonschema
Run:     python validate_data.py
"""

import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

# Lets `src` be imported when this file is run directly, not through run_5_validation.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.categories import allowed_values, get_column

# business_profile columns holding several values from a list as plain text
# ("families, students"): {column: (allowed values, most values)}. The schema
# checks the single-value lists; these are checked by check_profile_lists().
MULTI_VALUE_COLUMNS = {
    column: (set(allowed_values(f"business_profile.{column}")),
             get_column(f"business_profile.{column}")["max"])
    for column in ("target_segment", "ambiance")
}

# Counted nearby kinds: {kind: (radius in metres, nearby_context column)}
NEARBY_COUNTED = {
    kind: (detail["radius_m"], detail["column"])
    for kind, detail in get_column("nearby_place.kind")["values"].items()
    if "radius_m" in detail
}

# Restaurant fields that are UNIQUE in the database (checked by check_unique_ids);
# submission_id is the loader's key for a submitted restaurant
UNIQUE_IDS = ("osm_id", "google_place_id", "submission_id")

# restaurant.source and business_profile.evidence_level of a restaurant
# registered by its business (checked by check_source_ids)
SUBMITTED = "submitted"
assert SUBMITTED in allowed_values("restaurant.source")
assert SUBMITTED in allowed_values("business_profile.evidence_level")

# "format": "date-time" in the schema is checked only when a validator is given
# a format checker. The library's own date-time check needs an extra package
# (rfc3339-validator) and is silently skipped without it, so this one is used:
# a date Python can read, with its time zone, so the database never has to
# guess the zone.
DATE_CHECKER = FormatChecker(formats=())


@DATE_CHECKER.checks("date-time", raises=ValueError)
def is_date_time(value) -> bool:
    if not isinstance(value, str):
        return True  # the "type" keyword checks the type
    if datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("no time zone")
    return True


SCHEMA_PATH     = "src/s5_validator/foodsight_schema.json"
INPUT_PATH     = "data/4_profiled/pj_final.json"
VALID_PATH     = "data/5_validated/pj_validated.json"
INVALID_PATH   = "data/review/validation_invalid.json"


def fill_category_values(node) -> None:
    """Turn every "values_from" marker in the schema into the list of allowed
    values from src/reference/categories.json. A field that may be null keeps null."""
    if isinstance(node, dict):
        column = node.pop("values_from", None)
        if column:
            values = allowed_values(column)
            types = node.get("type")
            if isinstance(types, list) and "null" in types:
                values.append(None)
            node["enum"] = values
        for child in node.values():
            fill_category_values(child)
    elif isinstance(node, list):
        for child in node:
            fill_category_values(child)


def load_schema(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    fill_category_values(schema)
    return schema


def validate_restaurant(validator_restaurant, restaurant: dict) -> list:
    """Validate ONE restaurant against the restaurant sub-schema.
    Returns a list of error messages (empty list = valid)."""
    errors = []
    for error in validator_restaurant.iter_errors(restaurant):
        path = " -> ".join(str(p) for p in error.path) or "(root)"
        errors.append(f"{path}: {error.message}")
    return errors


def check_profile_lists(restaurant: dict) -> list:
    """Each value of target_segment and ambiance must be listed in
    src/reference/categories.json, at most the column's max values, with no repeats.
    Returns error messages. (The database has no CHECK for these on purpose:
    the lists can change in categories.json alone.)"""
    bp = restaurant.get("business_profile") or {}
    errors = []
    for column, (allowed, most) in MULTI_VALUE_COLUMNS.items():
        text = bp.get(column)
        if text is None:
            continue
        values = [v.strip() for v in str(text).split(",")]
        where = f"business_profile -> {column}"
        unknown = [v for v in values if v not in allowed]
        if unknown:
            errors.append(f"{where}: not in the list: {', '.join(repr(v) for v in unknown)}")
        if len(values) > most:
            errors.append(f"{where}: {len(values)} values, at most {most}")
        if len(set(values)) != len(values):
            errors.append(f"{where}: a value is repeated")
    return errors


def check_conflicts_decided(restaurant: dict) -> list:
    """Every field where OSM and Google disagree must have been decided by the
    AI in run_4_profiling.py, which removes the restaurant's "conflicts".
    Returns error messages."""
    waiting = restaurant.get("conflicts") or {}
    if not waiting:
        return []
    return [f"conflicts: still waiting for the AI to choose a source: {', '.join(waiting)}"]


def check_rating(restaurant: dict) -> list:
    """The loader writes a rating row whenever there is a score, and the
    database needs total_reviews in it (NOT NULL). A rating with no score is
    fine: it is not loaded. Returns error messages."""
    rating = restaurant.get("rating") or {}
    if rating.get("rating_score") is not None and rating.get("total_reviews") is None:
        return ["rating: has a rating_score but no total_reviews (the database needs both)"]
    return []


def check_cuisines(restaurant: dict) -> list:
    """restaurant_cuisine has PRIMARY KEY (restaurant_id, cuisine_id) and
    UNIQUE (restaurant_id, rank), so a restaurant may not list the same cuisine
    twice or give two cuisines the same rank. Returns error messages."""
    cuisines = restaurant.get("cuisines") or []
    errors = []
    names = [c.get("name") for c in cuisines]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        errors.append(f"cuisines: a cuisine is listed twice: {', '.join(repr(n) for n in repeated)}")
    ranks = [c.get("rank") for c in cuisines]
    repeated = sorted({r for r in ranks if ranks.count(r) > 1}, key=str)
    if repeated:
        errors.append(f"cuisines: two cuisines have the same rank: {', '.join(str(r) for r in repeated)}")
    return errors


def check_source_ids(restaurant: dict) -> list:
    """The IDs that go with each source. An extracted restaurant has its
    OpenStreetMap object (osm_id and osm_type) and no submission; a submitted
    one has its submission_id and no OpenStreetMap or Google IDs (the database
    allows osm_id and osm_type empty only together). evidence_level
    "submitted" belongs to submitted restaurants only. Returns error messages."""
    errors = []
    submitted = restaurant.get("source") == SUBMITTED
    if submitted:
        if not restaurant.get("submission_id"):
            errors.append("submission_id: a submitted restaurant needs its business submission")
        for field in ("osm_id", "osm_type", "google_place_id"):
            if restaurant.get(field):
                errors.append(f"{field}: a submitted restaurant has none")
    else:
        for field in ("osm_id", "osm_type"):
            if not restaurant.get(field):
                errors.append(f"{field}: required for an extracted restaurant")
        if restaurant.get("submission_id"):
            errors.append("submission_id: only a submitted restaurant has one")
    evidence = (restaurant.get("business_profile") or {}).get("evidence_level")
    if evidence and (evidence == SUBMITTED) != submitted:
        errors.append(f"business_profile -> evidence_level: {evidence!r} does not fit source "
                      f"{restaurant.get('source')!r}")
    return errors


def restaurant_label(restaurant: dict) -> str:
    """How a restaurant is named in the invalid file: its osm_id, or its submission."""
    if restaurant.get("osm_id"):
        return restaurant["osm_id"]
    if restaurant.get("submission_id"):
        return f"submission {restaurant['submission_id']}"
    return "unknown"


def count_ids(restaurants: list) -> dict:
    """{field: Counter of its values} for each field in UNIQUE_IDS."""
    return {field: Counter(r.get(field) for r in restaurants if r.get(field))
            for field in UNIQUE_IDS}


def check_unique_ids(restaurant: dict, id_counts: dict) -> list:
    """osm_id and google_place_id are UNIQUE in the database, so two restaurants
    with the same one cannot both be loaded (a shared google_place_id stops the
    loader, a shared osm_id makes it skip the second). There is no way to tell
    which one is right, so all of them are rejected. Returns error messages."""
    errors = []
    for field, counts in id_counts.items():
        value = restaurant.get(field)
        if value and counts[value] > 1:
            errors.append(f"{field}: {value!r} is used by {counts[value]} restaurants "
                          "(UNIQUE in the database)")
    return errors


def check_nearby_links(restaurant: dict, known_places: dict) -> list:
    """The checks a schema cannot make on a restaurant's nearby_places (the
    exact places behind its nearby_context counts). Returns error messages.

    - each place must be in the valid top-level nearby_places, with the same kind
    - only counted kinds (not stations), and never beyond the kind's radius
    - for each kind, the number of places must equal the count in nearby_context
    """
    links = restaurant.get("nearby_places") or []
    context = restaurant.get("nearby_context")
    errors = []
    if not context:
        if links:
            errors.append("nearby_places: given, but there is no nearby_context")
        return errors
    for link in links:
        where = f"nearby_places -> {link.get('osm_type')}/{link.get('osm_id')}"
        kind = known_places.get((link.get("osm_type"), link.get("osm_id")))
        if kind is None:
            errors.append(f"{where}: not in the valid top-level nearby_places")
        elif kind != link.get("kind"):
            errors.append(f"{where}: kind {link.get('kind')!r}, but the place is a {kind!r}")
        if link.get("kind") not in NEARBY_COUNTED:
            errors.append(f"{where}: {link.get('kind')!r} is not a counted kind")
        elif link.get("distance_m", 0) > NEARBY_COUNTED[link["kind"]][0]:
            errors.append(f"{where}: {link['distance_m']} m is beyond the {link['kind']} radius")
    for kind, (_, column) in NEARBY_COUNTED.items():
        n = sum(1 for link in links if link.get("kind") == kind)
        if n != context.get(column):
            errors.append(f"nearby_places: {n} {kind} places, but nearby_context.{column} is {context.get(column)}")
    return errors


def main():
    print("=" * 60)
    print("FoodSight — Data Validation")
    print("=" * 60)

    # ── Load schema ──────────────────────────────────────────
    schema = load_schema(SCHEMA_PATH)

    # Build a validator for a SINGLE restaurant (the items sub-schema)
    restaurant_schema = schema["properties"]["restaurants"]["items"]
    restaurant_validator = Draft202012Validator(restaurant_schema, format_checker=DATE_CHECKER)

    # Build a validator for a SINGLE area
    area_schema = schema["properties"]["areas"]["items"]
    area_validator = Draft202012Validator(area_schema, format_checker=DATE_CHECKER)

    # Build a validator for a SINGLE nearby place
    place_validator = Draft202012Validator(schema["properties"]["nearby_places"]["items"],
                                           format_checker=DATE_CHECKER)

    # ── Load data ────────────────────────────────────────────
    if not os.path.exists(INPUT_PATH):
        # run_5_validation.py stops with exit code 1, so the daily update stops here
        raise FileNotFoundError(f"{INPUT_PATH} not found.")

    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    restaurants   = data.get("restaurants", [])
    areas         = data.get("areas", [])
    nearby_places = data.get("nearby_places", [])

    print(f"\nLoaded {len(restaurants)} restaurants, {len(areas)} areas, "
          f"{len(nearby_places)} nearby places")

    # ── Validate nearby places (before restaurants, which point to them) ──
    valid_places   = []
    invalid_places = []

    for p in nearby_places:
        errors = []
        for error in place_validator.iter_errors(p):
            path = " -> ".join(str(x) for x in error.path) or "(root)"
            errors.append(f"{path}: {error.message}")
        if (p.get("kind") == "station") != (p.get("station_type") is not None):
            errors.append("station_type: set for stations only, and every station has one")
        if errors:
            invalid_places.append({"osm": f"{p.get('osm_type')}/{p.get('osm_id')}",
                                   "name": p.get("name", "unknown"), "errors": errors})
        else:
            valid_places.append(p)
    known_places = {(p["osm_type"], p["osm_id"]): p["kind"] for p in valid_places}

    # ── Validate restaurants ─────────────────────────────────
    valid_restaurants   = []
    invalid_restaurants = []
    id_counts = count_ids(restaurants)

    for i, r in enumerate(restaurants):
        errors = (validate_restaurant(restaurant_validator, r)
                  + check_profile_lists(r)
                  + check_rating(r)
                  + check_cuisines(r)
                  + check_conflicts_decided(r)
                  + check_source_ids(r)
                  + check_unique_ids(r, id_counts)
                  + check_nearby_links(r, known_places))
        if errors:
            invalid_restaurants.append({
                "osm_id": restaurant_label(r),
                "name":   r.get("name", "unknown"),
                "errors": errors
            })
        else:
            valid_restaurants.append(r)

    # ── Validate areas ───────────────────────────────────────
    valid_areas   = []
    invalid_areas = []

    for a in areas:
        errors = []
        for error in area_validator.iter_errors(a):
            path = " -> ".join(str(p) for p in error.path) or "(root)"
            errors.append(f"{path}: {error.message}")
        if errors:
            invalid_areas.append({"name": a.get("name", "unknown"), "errors": errors})
        else:
            valid_areas.append(a)

    # ── Save valid data ──────────────────────────────────────
    os.makedirs(os.path.dirname(VALID_PATH), exist_ok=True)
    with open(VALID_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "city":          data.get("city"),
            "areas":         valid_areas,
            "nearby_places": valid_places,
            "restaurants":   valid_restaurants,
            "validated_at":  datetime.now().astimezone().isoformat(timespec="seconds")
        }, f, ensure_ascii=False, indent=2)

    # ── Save the invalid records ─────────────────────────────
    os.makedirs(os.path.dirname(INVALID_PATH), exist_ok=True)
    with open(INVALID_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "invalid_restaurants":   invalid_restaurants,
            "invalid_areas":         invalid_areas,
            "invalid_nearby_places": invalid_places,
            "validated_at":          datetime.now().astimezone().isoformat(timespec="seconds")
        }, f, ensure_ascii=False, indent=2)

    # ── Summary ──────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("VALIDATION COMPLETE")
    print(f"  Restaurants valid:    {len(valid_restaurants)}")
    print(f"  Restaurants invalid:  {len(invalid_restaurants)}")
    print(f"  Areas valid:          {len(valid_areas)}")
    print(f"  Areas invalid:        {len(invalid_areas)}")
    print(f"  Nearby places valid:  {len(valid_places)}")
    print(f"  Nearby places invalid:{len(invalid_places):>4}")
    print(f"  Valid output:    {VALID_PATH}")
    print(f"  Invalid output:  {INVALID_PATH}")
    print("=" * 60)

    # Show first few errors as examples
    if invalid_restaurants:
        print("\nSAMPLE VALIDATION ERRORS:")
        for item in invalid_restaurants[:5]:
            print(f"\n  {item['name']} (osm_id={item['osm_id']}):")
            for err in item["errors"][:3]:
                print(f"    - {err}")


if __name__ == "__main__":
    main()
