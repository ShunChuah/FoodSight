"""
submissions.py — Restaurants registered by their business (stage 3).

A user registers a restaurant on the Register Business form, an admin checks
it (the backend, public.business_submission), and the next pipeline run adds
it. This module reads every approved and live submission from PostgreSQL and
turns each into a restaurant record for pj_merged.json, next to the ones from
OpenStreetMap and Google:

  - source "submitted", submission_id; no osm_id, osm_type or Google fields
  - the business's own values: name, brand, phone, website, status, the
    description (restaurant.editorial_summary), the opening hours and the
    facilities. They are already in the pipeline's formats: the backend
    writes them that way.
  - full_address: the address with the postcode and the city added (unless
    the address already has the postcode); street read from it
  - amenity_type follows from the restaurant type (AMENITY_FOR_TYPE)
  - the section, the nearby counts and the nearest station come from the pin,
    by the same code as for every other restaurant (assign_area,
    nearby_context in merge_data.py)
  - submitted_profile: the cuisines, price, halal status and profile values
    the business chose. Stage 4 copies them into the profile and asks the AI
    nothing (evidence_level "submitted").

Live submissions are read on every run too, not only new ones: the clusters,
and the nearby counts around a changed place, are worked out again for every
restaurant in the file, so a restaurant left out would lose its cluster.
"""

from src.categories import allowed_values, get_column

# The statuses the pipeline reads (business_submission.status in categories.json)
APPROVED, LIVE = "approved", "live"
_STATUSES = allowed_values("business_submission.status")
assert APPROVED in _STATUSES and LIVE in _STATUSES, "business_submission.status lost approved or live"

# restaurant.amenity_type for each business_profile.restaurant_type: the
# OpenStreetMap kind of place a mapper would give it. A type not listed here
# is "restaurant". Checked against categories.json when this module loads, so
# a renamed value fails at once instead of silently becoming "restaurant".
AMENITY_FOR_TYPE = {
    "cafe": "cafe",
    "fast_food": "fast_food",
    "food_court": "food_court",
    "canteen": "canteen",
    "bakery": "bakery",
    "dessert_shop": "ice_cream",
    "drinks_shop": "beverage",
}
DEFAULT_AMENITY = "restaurant"
_types, _amenities = allowed_values("business_profile.restaurant_type"), allowed_values("restaurant.amenity_type")
assert all(t in _types for t in AMENITY_FOR_TYPE), "AMENITY_FOR_TYPE names a restaurant_type not in categories.json"
assert all(a in _amenities for a in [*AMENITY_FOR_TYPE.values(), DEFAULT_AMENITY]), \
    "AMENITY_FOR_TYPE names an amenity_type not in categories.json"

FACILITY_CATEGORY = {name: detail["category"] for name, detail in get_column("facility.name")["values"].items()}
DAY_FIELDS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
ALL_DAY = "00:00-24:00"

QUERY = """
    SELECT s.*, r.decided_at AS approved_at
    FROM public.business_submission s
    LEFT JOIN public.submission_round r
           ON r.submission_id = s.submission_id AND r.round_no = s.round_no
    WHERE s.status IN (%s, %s)
    ORDER BY s.submission_id
"""


def load_submissions():
    """The approved and live submissions as dicts, or None when the table does
    not exist yet (migration 028 not run). A database that cannot be reached
    stops the run: without the submissions the load would drop their
    restaurants from the food clusters."""
    from src.s7_loader.load_data import get_connection

    try:
        conn = get_connection()
    except Exception as exc:
        raise SystemExit(f"ERROR: could not read the business submissions from PostgreSQL ({exc}). "
                         "Start PostgreSQL and run run_3_merging.py again.") from exc
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.business_submission')")
            if cur.fetchone()[0] is None:
                return None
            cur.execute(QUERY, (APPROVED, LIVE))
            names = [d[0] for d in cur.description]
            return [dict(zip(names, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _text(value):
    text = (value or "").strip() if isinstance(value, str) else value
    return text or None


def _items(text):
    """A comma list as written by the backend ("Malay, Nyonya") -> ["Malay", "Nyonya"]."""
    return [part.strip() for part in (text or "").split(",") if part.strip()]


def full_address(address, postcode, city):
    """The address with the postcode and the city: "12, Jalan SS 2/24" ->
    "12, Jalan SS 2/24, 47300 Petaling Jaya, Selangor". An address that
    already has its postcode is kept as written."""
    address = (address or "").strip().rstrip(",")
    if postcode and postcode in address:
        return address
    place = ", ".join(p for p in ((city or {}).get("name"), (city or {}).get("state")) if p) or "Petaling Jaya"
    return f"{address}, {postcode} {place}" if postcode else f"{address}, {place}"


def submission_record(sub, polygons, nearby, city):
    """One approved or live submission as a pj_merged.json restaurant record."""
    from src.s3_mergers.merge_data import _street_in, assign_area, nearby_context

    lat, lon = float(sub["latitude"]), float(sub["longitude"])
    area_name, area_type = assign_area(lat, lon, polygons)
    context, counted = nearby_context(lat, lon, nearby)
    hours = {day: _text(sub.get(day)) for day in DAY_FIELDS}
    hours["is_24_7"] = all(hours[day] == ALL_DAY for day in DAY_FIELDS)
    address = full_address(sub.get("address"), _text(sub.get("postcode")), city)
    restaurant_type = _text(sub.get("restaurant_type"))
    approved_at = sub.get("approved_at")

    return {
        "source": "submitted",
        "submission_id": sub["submission_id"],
        "osm_id": None,
        "osm_type": None,
        "google_place_id": None,
        "google_maps_uri": None,
        "google_fetched_at": None,
        "editorial_summary": _text(sub.get("description")),
        "google_primary_type": None,
        "google_maps_type_label": None,
        "google_price_low": None,
        "google_price_high": None,
        "google_price_level": None,
        "google_types": None,
        "name": _text(sub.get("name")),
        "amenity_type": AMENITY_FOR_TYPE.get(restaurant_type, DEFAULT_AMENITY),
        "brand": _text(sub.get("brand")),
        "phone": _text(sub.get("phone")),
        "website": _text(sub.get("website")),
        "business_status": _text(sub.get("business_status")),
        "latitude": lat,
        "longitude": lon,
        "full_address": address,
        "postcode": _text(sub.get("postcode")),
        "street": _street_in(sub.get("address") or ""),
        "area_name": area_name,
        "area_type": area_type,
        "nearby_context": context,
        "nearby_places": counted,
        "operating_hours": hours,
        "cuisine_raw": None,
        "halal_tag": None,
        "rating": {"rating_score": None, "total_reviews": None},
        "facilities": [{"name": name, "category": FACILITY_CATEGORY[name]}
                       for name in _items(sub.get("facilities")) if name in FACILITY_CATEGORY],
        "merge_log": {},
        "conflicts": {},
        "reviews": [],
        # The business's choices; stage 4 copies them into the profile (no AI)
        "submitted_profile": {
            "cuisines": _items(sub.get("cuisines")),
            "avg_meal_price": float(sub["avg_meal_price"]),
            "halal_status": _text(sub.get("halal_status")),
            "restaurant_type": restaurant_type,
            "service_style": _text(sub.get("service_style")),
            "business_style": _text(sub.get("business_style")),
            "target_segment": _text(sub.get("target_segment")),
            "ambiance": _text(sub.get("ambiance")),
            "approved_at": approved_at.isoformat() if approved_at else None,
        },
    }, area_name is not None
