"""
Enriches OSM restaurant data with Google Places information, using
Places API (New) (https://places.googleapis.com/v1).

For each restaurant in data/1_raw/osm_raw.csv, finds its Google place with one
Text Search (New) for the restaurant name, around the OSM pin. Only places
within SEARCH_RADIUS_M (100 m) are kept: Google treats the search circle as a
preference, so places farther away can come back and are dropped here.

A candidate is a MATCH (see match_problem) when:
  - its Google types do not show it is clearly something other than a food
    business (a road, an address, a petrol station, a gym, ...); a place
    Google gives no category is kept, and the name decides;
  - its name is "same" or "brand" (see name_strength);
  - its pin is within the limit for that strength
    (MAX_DISTANCE_BY_STRENGTH: same 50 m, brand 50 m).
Of the candidates that pass, the most alike name wins, then the nearest pin,
so the closest outlet of a chain is chosen.

REVIEW (see review_reason): when nothing matches, the best food place within
100 m whose name is alike but not matched is shown to a person:
  - too_far            — "same" or "brand" name, but the pins are more than 50 m apart;
  - name_partly_alike  — "close" name (half the words shared): never matched
                         automatically.
Its Place Details are fetched once and cached (marked "review"), so the next
run neither searches nor fetches it again. The restaurant is HELD FOR REVIEW:
clean_osm.py leaves it out of the rest of the pipeline until a person decides
in src/reference/google_match_overrides.json (osm_id → the right place ID, or null for
no match); every run obeys that file before any rule. Nothing alike within
100 m → NOT FOUND, and the restaurant goes on with OSM data only. A NOT
FOUND is cached too (marked "not_found", with the name and pin searched): a
run without --refresh-google does not search it again unless its OSM name or
pin has changed, so an OSM day pays only for new or changed restaurants; a
refresh searches every one of them again.

Duplicates (find_duplicates): when two or more OSM restaurants end up on the
same Google place, copies with the same name (the same shop mapped twice in
OSM) are dropped except the one nearest Google's pin, listed in
data/reports/google_duplicates.json; different names are all held for review
(shared_google_place).

Output files:
  - data/1_raw/google_raw.csv            — one row per matched restaurant
                                         (rating, phone, website, business_status,
                                          opening hours, price level, Google types,
                                          address, postcode, street)
  - data/1_raw/reviews_raw.csv           — up to 5 customer reviews per restaurant
  - data/1_raw/google_facilities_raw.csv — one row per confirmed boolean facility
                                         (dine-in, takeout, delivery, etc.)
  - data/review/google_match_review.json — the one review file: every held
                                         restaurant with its reason and all its
                                         OSM and Google data
  - data/reports/google_duplicates.json    — copies dropped as the same shop (a log)

The CSV column names are the pipeline's own and did not change when the
extractor moved to Places API (New); only the Google field names did.

Every Place Details answer is cached in data/cache/google_cache.json keyed by
osm_id, marked "matched", "review" or "override", so re-runs skip
already-processed restaurants; a search that found nothing is kept there as
"not_found" (no Place Details, see above). It is saved every 25 restaurants and when the run stops early
(Ctrl+C or an error), so a stop halfway loses at most the last few answers. A cached answer is checked again with the current rules, and one
that no longer fits is searched again. Each entry keeps fetched_at, the exact
time Google sent it (UTC), which becomes restaurant.google_fetched_at and
rating.scraped_at. An entry saved by the older Places API is refreshed once:
its place ID is reused (IDs are the same in both APIs), so only Place Details
is called again, not the search. HTTP errors use exponential backoff.

REFRESH (run(refresh=True), python run_1_extraction.py --skip-osm
--refresh-google): a saved match (and a hand-checked one in the override
file) is not reused as it is: its Place Details are fetched again by the
saved place ID, so hours, status, price, facilities, rating and reviews are
fresh. A fetch that fails keeps the saved answer (a Google problem never
wipes a restaurant's data); a bad key still stops the run. A place ID Google
no longer knows is searched again by name, like a new restaurant. A fresh
answer that no longer fits the rules is searched again, as above. Restaurants
held for review are not refreshed. Without refresh (an OSM day), saved
matches are reused and only new or changed restaurants cost a call.

REPLACES_REMOVED (a review reason): when a search matches a Google place
that, in the cache, belongs to a restaurant no longer in osm_raw.csv, the
new restaurant is held instead of matched: it is probably the same shop
redrawn in OSM with a new ID (a point turned into a building), or a new shop
in its unit. It stays held, with no new search, until a person decides in
the override file. Approved with that place_id, the loader moves the old
restaurant's database row to the new osm_id, with its reviews.
"""

import argparse
import csv
import json
import math
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import requests
from dotenv import load_dotenv

# Lets `src` be imported when this file is run directly, not through run_1_extraction.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.cache_saving import save_due, save_json
from src.categories import get_column

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

load_dotenv()

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")
if not GOOGLE_PLACES_API_KEY:
    raise EnvironmentError("GOOGLE_PLACES_API_KEY not found. Add it to your .env file.")

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"

INPUT_CSV = os.path.join("data", "1_raw", "osm_raw.csv")
GOOGLE_RAW_CSV = os.path.join("data", "1_raw", "google_raw.csv")
REVIEWS_RAW_CSV = os.path.join("data", "1_raw", "reviews_raw.csv")
FACILITIES_RAW_CSV = os.path.join("data", "1_raw", "google_facilities_raw.csv")
CACHE_FILE = os.path.join("data", "cache", "google_cache.json")
# The one review file: restaurants held for a person to check, with the reason
# and all their OSM and Google data (rewritten each run, so never write
# decisions in it)
MATCH_REVIEW_JSON = os.path.join("data", "review", "google_match_review.json")
# OSM restaurants dropped as the same shop mapped twice (rewritten each run)
DUPLICATES_JSON = os.path.join("data", "reports", "google_duplicates.json")
# Hand-checked decisions, obeyed before any matching rule. Kept in
# src/reference/ (not data/) because it is written by a person, not
# generated, and must be kept.
OVERRIDES_FILE = os.path.join("src", "reference", "google_match_overrides.json")

# Cache entries saved from Places API (New) carry this marker; older entries
# (from the previous Places API) are refreshed once.
CACHE_API = "places_new"

# Text Search (New) only needs enough to pick the right place.
SEARCH_FIELDS = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.location",
        "places.types",
    ]
)

# Google place types that mean a food or drink business. Any type ending in
# "_restaurant" (e.g. chinese_restaurant) counts too.
FOOD_TYPES = {
    "food", "restaurant", "cafe", "bakery", "bar", "pub", "wine_bar",
    "meal_takeaway", "meal_delivery", "coffee_shop", "tea_house", "food_court",
    "cafeteria", "dessert_shop", "ice_cream_shop", "juice_shop", "donut_shop",
    "sandwich_shop", "bagel_shop", "chocolate_shop", "confectionery",
    "candy_store", "deli", "diner", "steak_house", "bar_and_grill", "acai_shop",
}
# Types almost every place has. A place with only these has no category in
# Google, so the name decides.
GENERIC_TYPES = {"establishment", "point_of_interest"}

# The facilities, from src/reference/categories.json: {name: {definition, category,
# google}}, where google is the Place Details field that is true when the
# restaurant has it (a dot reads a field inside an object, such as
# parkingOptions.freeParkingLot). Only a true answer becomes a facility row.
_FACILITIES = get_column("facility.name")["values"]

# Place Details (New) field mask. Each call is billed at the price of the most
# expensive field listed, so only fields the pipeline uses are asked for.
DETAILS_FIELDS = ",".join(
    [
        "id",
        "displayName",
        "nationalPhoneNumber",
        "internationalPhoneNumber",
        "websiteUri",
        "businessStatus",
        "rating",
        "userRatingCount",
        "regularOpeningHours",
        "priceLevel",
        "priceRange",
        "types",
        "primaryType",
        "googleMapsTypeLabel",
        "editorialSummary",
        "reviews",
        "location",
        "formattedAddress",
        "addressComponents",
        "googleMapsUri",
    ]
    # Facility fields: the object a dotted field sits in is asked for whole
    + sorted({detail["google"].split(".")[0] for detail in _FACILITIES.values()})
)

RATE_LIMIT_SLEEP = 0.1

# The name strengths (see name_strength) that are matched automatically, and
# how far apart the OSM and Google pins may then be, in metres. A strength
# without an entry is never matched automatically (a person can still accept
# it in OVERRIDES_FILE).
MAX_DISTANCE_BY_STRENGTH = {"same": 50, "brand": 50}
# (The admin review page offers Google's pin beyond 50 m: AUTO_MATCH_M in
# backend/app/admin/routes.py; change both together.)
STRENGTH_ORDER = ["same", "brand", "close", "weak"]  # best first
# Name strengths alike enough to show a person when they are not matched
REVIEW_STRENGTHS = ("same", "brand", "close")
# Text Search looks around the OSM pin within this radius, and places farther
# away are dropped (Google only treats the circle as a preference). So it is
# also the farthest a place can be and still go to the review file.
SEARCH_RADIUS_M = 100

# Why a restaurant is held for review (the `reason` of each review item)
REVIEW_REASONS = {
    "too_far": "Same or brand name, but the pins are too far apart "
               "(matched automatically only within 50 m).",
    "name_partly_alike": "The names are only partly alike (at least half the words "
                         "shared); such names are never matched automatically.",
    "shared_google_place": "Two or more OSM restaurants with different names matched "
                           "the same Google place; Google can only be one of them.",
    "replaces_removed": "A new OSM restaurant matched a Google place that belonged to a "
                        "restaurant no longer in OpenStreetMap: probably the same shop redrawn "
                        "with a new ID, or a new shop in its unit. Same shop: give the new osm_id "
                        "this place_id, and its database row moves to the new ID with its reviews.",
}

# Words removed from both names before they are compared, wherever they are.
_FILLER_WORDS = {
    "the", "and", "restoran", "restaurant", "cafe", "café", "kafe",
    "cafeteria", "kedai", "makanan", "makan", "warung", "warong", "bistro",
    "mamak", "kopitiam",
}

# Google day index: 0=Sunday, 1=Monday … 6=Saturday
GOOGLE_DAY_MAP = {
    0: "sunday",
    1: "monday",
    2: "tuesday",
    3: "wednesday",
    4: "thursday",
    5: "friday",
    6: "saturday",
}

GOOGLE_RAW_COLUMNS = [
    "osm_id",
    "google_place_id",
    "name",
    "phone",
    "website",
    "business_status",
    "rating_score",
    "total_reviews",
    "price_level",
    "price_low",
    "price_high",
    "formatted_address",
    "postcode",
    "street",
    "latitude",
    "longitude",
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
    "is_24_7",
    "hours_raw",
    "google_types",
    "google_primary_type",
    "google_maps_type_label",
    "editorial_summary",
    "google_maps_uri",
    "google_fetched_at",
    "source",
    "extracted_at",
]

REVIEWS_COLUMNS = [
    "osm_id",
    "google_place_id",
    "google_review_id",
    "author_name",
    "text",
    "individual_rating",
    "published_at",
    "language",
    "source",
    "extracted_at",
]

FACILITIES_COLUMNS = [
    "osm_id",
    "google_place_id",
    "facility_name",
    "facility_category",
    "source",
    "extracted_at",
]

BACKOFF_WAITS = [2, 4, 8, 16, 32]


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------


class PlacesAPIError(RuntimeError):
    """An error answer from Places API (New), with its HTTP status code."""

    def __init__(self, status, message):
        super().__init__(f"Places API error {status}: {message}")
        self.status = status


def _request(method, url, field_mask, body=None):
    """Call Places API (New) and return the JSON answer.

    Network errors, rate limits (429) and server errors (5xx) are retried with
    exponential backoff. Other API errors (bad key, API not enabled, invalid
    request) are raised immediately as PlacesAPIError.
    """
    headers = {
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": field_mask,
    }
    last_exc = None
    for attempt, wait in enumerate(BACKOFF_WAITS, start=1):
        try:
            resp = requests.request(method, url, headers=headers, json=body, timeout=30)
        except requests.RequestException as exc:
            last_exc = exc
        else:
            if resp.ok:
                return resp.json()
            try:
                message = resp.json().get("error", {}).get("message", resp.text)
            except ValueError:
                message = resp.text
            last_exc = PlacesAPIError(resp.status_code, message)
            if resp.status_code != 429 and resp.status_code < 500:
                raise last_exc  # API-level errors — no point retrying
        if attempt < len(BACKOFF_WAITS):
            print(f"  Attempt {attempt} failed ({last_exc}), retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"All {len(BACKOFF_WAITS)} attempts failed. Last: {last_exc}")


# ---------------------------------------------------------------------------
# Distance helper
# ---------------------------------------------------------------------------


def haversine_m(lat1, lon1, lat2, lon2):
    """Return distance in metres between two WGS-84 points."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------


def _name_words(name):
    """Lower-case words of a name without filler words (Restoran, Cafe, The,
    ...). A name made only of filler words keeps them all."""
    words = re.findall(r"\w+", name.lower())
    return [w for w in words if w not in _FILLER_WORDS] or words


def _alike(a, b, ratio):
    """True if two strings are equal or at least `ratio` alike (0 to 1)."""
    return a == b or SequenceMatcher(None, a, b).ratio() >= ratio


def name_strength(osm_name, google_name):
    """How alike two names are, after filler words are removed and small
    spelling differences allowed (words at least 80% alike count as shared:
    Noodle/Noodles, Barakah/Barokah).

      same   — the whole names are at least 85% alike ("Seven Cups" / "Sevencups")
      brand  — every word of the shorter name is in the longer
               ("KFC" / "KFC Lotus Ara Damansara")
      close  — at least half the words of either name are shared
               ("Medan Selera Jati" / "Selera Jati Food Court");
               never matched automatically, only sent for review
      weak   — one shared word, or the letters at least 50% alike
               (never a match, never reviewed)
      None   — nothing in common
    """
    wa, wb = _name_words(osm_name), _name_words(google_name)
    ca, cb = "".join(wa), "".join(wb)
    if not ca or not cb:
        return None
    if _alike(ca, cb, 0.85):
        return "same"
    short, long_ = (wa, wb) if len(ca) <= len(cb) else (wb, wa)
    hits = sum(1 for w in short if any(_alike(w, v, 0.8) for v in long_))
    if hits == len(short) or "".join(short) in "".join(long_):
        return "brand"
    if hits / len(long_) >= 0.5 or hits / len(short) >= 0.5:
        return "close"
    if hits or SequenceMatcher(None, ca, cb).ratio() >= 0.5:
        return "weak"
    return None


def _not_food(types):
    """Return the type that shows a Google place is clearly not a food
    business (a road, an address, an area, a petrol station, a gym, ...),
    or None if it may be one.

    A place with any food type passes. A place with only the generic types
    has no category in Google, so it passes too and the name decides.
    """
    if any(t in FOOD_TYPES or t.endswith("_restaurant") for t in types):
        return None
    return next((t for t in types if t not in GENERIC_TYPES), None)


def _distance_to(osm_lat, osm_lon, place):
    """Metres from the OSM pin to a Google place's pin."""
    return haversine_m(float(osm_lat), float(osm_lon), place["lat"], place["lon"])


def match_problem(osm_name, osm_lat, osm_lon, place):
    """Why a Google place {name, lat, lon, types} is not an automatic match
    for this OSM restaurant, or None if it is: it must not be clearly
    something other than a food business, its name must be "same" or
    "brand", and its pin must be within the limit for that strength."""
    bad_type = _not_food(place["types"])
    if bad_type:
        return f"not a food business: {bad_type}"
    strength = name_strength(osm_name, place["name"])
    if strength is None:
        return "names have nothing in common"
    if strength not in MAX_DISTANCE_BY_STRENGTH:
        return f"only a '{strength}' name likeness, never matched automatically"
    if place["lat"] is None or place["lon"] is None:
        return "Google gave no location"
    distance = _distance_to(osm_lat, osm_lon, place)
    limit = MAX_DISTANCE_BY_STRENGTH[strength]
    if distance > limit:
        return f"'{strength}' name but {distance:.0f} m away (limit {limit} m)"
    return None


def _rank(osm_name, osm_lat, osm_lon, place):
    """Sort key for candidates: the most alike name first, then the nearest
    pin, so the closest outlet of a chain wins."""
    return (
        STRENGTH_ORDER.index(name_strength(osm_name, place["name"])),
        _distance_to(osm_lat, osm_lon, place),
    )


def best_match(osm_name, osm_lat, osm_lon, candidates):
    """Return the best candidate that passes match_problem(), or None."""
    passing = [c for c in candidates if match_problem(osm_name, osm_lat, osm_lon, c) is None]
    return min(passing, key=lambda c: _rank(osm_name, osm_lat, osm_lon, c), default=None)


def review_reason(osm_name, osm_lat, osm_lon, place):
    """(reason, reason_text) when a Google place that is not a match is still
    worth a person's look, or None. It must be a food place within
    SEARCH_RADIUS_M whose name is "same" or "brand" but too far apart to be
    matched automatically (too_far), or "close" (name_partly_alike). A place that
    passes match_problem() is a match, not a review, and gives None."""
    if _not_food(place["types"]) or place["lat"] is None or place["lon"] is None:
        return None
    strength = name_strength(osm_name, place["name"])
    if strength not in REVIEW_STRENGTHS:
        return None
    distance = _distance_to(osm_lat, osm_lon, place)
    if distance > SEARCH_RADIUS_M:
        return None
    if strength == "close":
        return "name_partly_alike", (
            f"Names only partly alike (at least half the words shared), pins "
            f"{distance:.0f} m apart. Such names are never matched automatically."
        )
    limit = MAX_DISTANCE_BY_STRENGTH[strength]
    if distance > limit:
        return "too_far", (
            f"{strength.capitalize()} name, but the pins are {distance:.0f} m apart "
            f"(matched automatically only within {limit} m)."
        )
    return None


def best_for_review(osm_name, osm_lat, osm_lon, candidates):
    """The most promising candidate for the review file (see
    review_reason()), or None."""
    worth = [c for c in candidates if review_reason(osm_name, osm_lat, osm_lon, c)]
    return min(worth, key=lambda c: _rank(osm_name, osm_lat, osm_lon, c), default=None)


# ---------------------------------------------------------------------------
# Text Search (New)
# ---------------------------------------------------------------------------


def text_search(lat, lon, query):
    """Return candidates {place_id, name, lat, lon, types} from Text Search
    (New) around the OSM point. Google treats the SEARCH_RADIUS_M circle
    only as a preference and can return places outside it; those, and
    places without a location, are dropped here."""
    body = {
        "textQuery": query,
        "locationBias": {
            "circle": {
                "center": {"latitude": float(lat), "longitude": float(lon)},
                "radius": float(SEARCH_RADIUS_M),
            }
        },
    }
    data = _request("POST", SEARCH_URL, SEARCH_FIELDS, body)
    time.sleep(RATE_LIMIT_SLEEP)
    places = [
        {
            "place_id": p.get("id", ""),
            "name": p.get("displayName", {}).get("text", ""),
            "lat": p.get("location", {}).get("latitude"),
            "lon": p.get("location", {}).get("longitude"),
            "types": p.get("types", []),
        }
        for p in data.get("places", [])
    ]
    return [
        p for p in places
        if p["lat"] is not None and p["lon"] is not None
        and _distance_to(lat, lon, p) <= SEARCH_RADIUS_M
    ]


def _place_from_details(details):
    """The same fields as a text_search() candidate, from Place Details (New)."""
    location = details.get("location", {})
    return {
        "place_id": details.get("id", ""),
        "name": details.get("displayName", {}).get("text", ""),
        "lat": location.get("latitude"),
        "lon": location.get("longitude"),
        "types": details.get("types", []),
        "address": details.get("formattedAddress", ""),
        "map": details.get("googleMapsUri", ""),
    }


# ---------------------------------------------------------------------------
# Place Details (New)
# ---------------------------------------------------------------------------


def place_details(place_id):
    """Fetch Place Details (New) with the fields in DETAILS_FIELDS."""
    data = _request("GET", DETAILS_URL.format(place_id=place_id), DETAILS_FIELDS)
    time.sleep(RATE_LIMIT_SLEEP)
    return data


def _field(details, path):
    """Read a field by dotted path, e.g. 'accessibilityOptions.wheelchairAccessibleEntrance'."""
    value = details
    for key in path.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _ringgit(money):
    """A Money object such as {"currencyCode": "MYR", "units": "20"} as a
    number string ("20"); "" when it is missing or not in ringgit."""
    if not isinstance(money, dict) or money.get("currencyCode") != "MYR":
        return ""
    amount = int(money.get("units", 0) or 0) + int(money.get("nanos", 0) or 0) / 1e9
    return f"{amount:g}"


def _text(value):
    """The text of a localized field such as {"text": "Malaysian restaurant",
    "languageCode": "en"}; a plain string is returned as it is."""
    if isinstance(value, dict):
        return value.get("text", "")
    return value or ""


def _address_part(details, part_type):
    """Return the text of the first addressComponents entry of a type,
    e.g. 'route' (the street) or 'postal_code'."""
    for part in details.get("addressComponents", []):
        if part_type in part.get("types", []):
            return part.get("longText", "")
    return ""


def _iso_utc(timestamp):
    """'2024-05-01T10:00:00.123456789Z' → '2024-05-01T10:00:00+00:00', the
    format the rest of the pipeline uses; '' if it cannot be read."""
    m = re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", timestamp or "")
    return f"{m.group(0)}+00:00" if m else ""


# ---------------------------------------------------------------------------
# Hours parsing
# ---------------------------------------------------------------------------


def _fmt_time(point):
    """Convert {'hour': 9, 'minute': 0} → '09:00'."""
    return f"{point.get('hour', 0):02d}:{point.get('minute', 0):02d}"


def parse_hours(details):
    """
    Parse regularOpeningHours from Place Details (New) into per-day columns.
    Returns (day_dict, is_24_7, hours_raw).

    Each day is its opening times ("11:00-15:00, 18:00-22:00"), "Closed" when
    Google gives a weekly schedule with no opening that day, or "" when
    Google has no hours at all. Google's "always open" form (one opening on
    Sunday at 00:00 with no close) and a whole-day opening (00:00 to the next
    00:00) are written "00:00-24:00". is_24_7 is true only when all 7 days are
    "00:00-24:00".
    """
    day_dict = {
        col: ""
        for col in [
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        ]
    }
    is_24_7 = False
    hours_raw = ""

    oh = details.get("regularOpeningHours", {})
    if not oh:
        return day_dict, is_24_7, hours_raw

    # Build hours_raw from weekdayDescriptions
    weekday_text = oh.get("weekdayDescriptions", [])
    if weekday_text:
        hours_raw = "; ".join(weekday_text)

    periods = oh.get("periods", [])

    # Detect 24/7: single period, opens Sunday 00:00, no close key
    if (
        len(periods) == 1
        and periods[0].get("open", {}).get("day") == 0
        and _fmt_time(periods[0].get("open", {})) == "00:00"
        and "close" not in periods[0]
    ):
        for col in day_dict:
            day_dict[col] = "00:00-24:00"
        return day_dict, True, hours_raw

    for period in periods:
        open_info = period.get("open", {})
        close_info = period.get("close", {})
        open_day = open_info.get("day")

        if open_day is None:
            continue

        col = GOOGLE_DAY_MAP.get(open_day)
        if not col:
            continue

        if close_info:
            slot = f"{_fmt_time(open_info)}-{_fmt_time(close_info)}"
            if slot == "00:00-00:00":
                slot = "00:00-24:00"  # open the whole day
        else:
            slot = _fmt_time(open_info)

        # Append if day already has a slot (split-hour days)
        if day_dict[col] and slot:
            day_dict[col] = f"{day_dict[col]}, {slot}"
        else:
            day_dict[col] = slot

    if periods:
        for col in day_dict:
            day_dict[col] = day_dict[col] or "Closed"
    is_24_7 = all(v == "00:00-24:00" for v in day_dict.values())
    return day_dict, is_24_7, hours_raw


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _now_utc():
    """The current time in UTC with its time zone, e.g. 2026-10-21T08:30:00+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_google_row(osm_id, details, extracted_at, fetched_at=""):
    """Build a single dict for google_raw.csv. fetched_at is when Google sent
    these details (kept in the cache, so a cached answer keeps its own time)."""
    day_dict, is_24_7, hours_raw = parse_hours(details)

    phone = details.get("nationalPhoneNumber") or details.get(
        "internationalPhoneNumber", ""
    )
    google_types = ",".join(details.get("types", []))
    location = details.get("location", {})
    lat = str(location["latitude"]) if location.get("latitude") is not None else ""
    lon = str(location["longitude"]) if location.get("longitude") is not None else ""
    rating = details.get("rating")
    total_reviews = details.get("userRatingCount")

    return {
        "osm_id": osm_id,
        "google_place_id": details.get("id", ""),
        "name": details.get("displayName", {}).get("text", ""),
        "phone": phone,
        "website": details.get("websiteUri", ""),
        "business_status": details.get("businessStatus", ""),
        "rating_score": str(rating) if rating is not None else "",
        "total_reviews": str(total_reviews) if total_reviews is not None else "",
        # Google's own level name, e.g. PRICE_LEVEL_MODERATE (matched to a tier
        # in src/reference/categories.json), and its price band per person in ringgit
        "price_level": details.get("priceLevel", ""),
        "price_low": _ringgit(details.get("priceRange", {}).get("startPrice")),
        "price_high": _ringgit(details.get("priceRange", {}).get("endPrice")),
        "formatted_address": details.get("formattedAddress", ""),
        "postcode": _address_part(details, "postal_code"),
        "street": _address_part(details, "route"),
        "latitude": lat,
        "longitude": lon,
        "monday": day_dict["monday"],
        "tuesday": day_dict["tuesday"],
        "wednesday": day_dict["wednesday"],
        "thursday": day_dict["thursday"],
        "friday": day_dict["friday"],
        "saturday": day_dict["saturday"],
        "sunday": day_dict["sunday"],
        "is_24_7": str(is_24_7),
        "hours_raw": hours_raw,
        "google_types": google_types,
        "google_primary_type": details.get("primaryType", ""),
        "google_maps_type_label": _text(details.get("googleMapsTypeLabel")),
        # Google's short description; many places have none. Text only, no language code.
        "editorial_summary": _text(details.get("editorialSummary")).strip(),
        "google_maps_uri": details.get("googleMapsUri", ""),
        "google_fetched_at": fetched_at,
        "source": "google",
        "extracted_at": extracted_at,
    }


def build_review_rows(osm_id, details, extracted_at):
    """Return list of review row dicts for reviews_raw.csv."""
    rows = []
    place_id = details.get("id", "")
    for review in details.get("reviews", []):
        text = review.get("text", {})
        rating = review.get("rating")
        rows.append(
            {
                "osm_id": osm_id,
                "google_place_id": place_id,
                # Google's ID for the review, e.g. places/ChIJ.../reviews/...
                "google_review_id": review.get("name", ""),
                "author_name": review.get("authorAttribution", {}).get("displayName", ""),
                "text": text.get("text", ""),
                "individual_rating": str(rating) if rating is not None else "",
                "published_at": _iso_utc(review.get("publishTime", "")),
                "language": text.get("languageCode", ""),
                "source": "google",
                "extracted_at": extracted_at,
            }
        )
    return rows


def build_facility_rows(osm_id, details, extracted_at):
    """Return one row per facility in src/reference/categories.json whose Google field
    is true in details. False or no answer gives no row."""
    place_id = details.get("id", "")
    rows = []
    for facility_name, detail in _FACILITIES.items():
        if _field(details, detail["google"]) is True:
            rows.append(
                {
                    "osm_id": osm_id,
                    "google_place_id": place_id,
                    "facility_name": facility_name,
                    "facility_category": detail["category"],
                    "source": "google",
                    "extracted_at": extracted_at,
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(cache):
    save_json(CACHE_FILE, cache)


# ---------------------------------------------------------------------------
# Input reader
# ---------------------------------------------------------------------------


def read_osm_rows(limit=None):
    if not os.path.exists(INPUT_CSV):
        sys.exit(
            f"ERROR: Input file not found: {INPUT_CSV}\n" "Run extract_osm.py first."
        )
    rows = []
    with open(INPUT_CSV, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit is not None and i >= limit:
                break
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Matching one restaurant: overrides, cache, search, review
# ---------------------------------------------------------------------------


def load_overrides():
    """Hand-checked matches from OVERRIDES_FILE: {osm_id: {"place_id": ...}},
    where place_id null means the restaurant has no Google match."""
    if not os.path.exists(OVERRIDES_FILE):
        return {}
    with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("overrides", {})


def _osm_map(osm):
    """The OpenStreetMap page of an OSM restaurant."""
    return f"https://www.openstreetmap.org/{osm.get('osm_type') or 'node'}/{osm.get('osm_id', '')}"


def review_item(osm, details, fetched_at, reason, reason_text, other_osm_ids=None):
    """One entry of MATCH_REVIEW_JSON: why the restaurant is held, and
    everything known about both sides (the whole OSM row and the whole Place
    Details answer), each with its map link."""
    place = _place_from_details(details)
    name = osm.get("name", "")
    strength = name_strength(name, place["name"])
    distance = None
    if place["lat"] is not None and place["lon"] is not None:
        distance = round(_distance_to(osm["latitude"], osm["longitude"], place))
    item = {
        "osm_id": osm.get("osm_id", ""),
        "reason": reason,
        "reason_text": reason_text,
        "osm_name": name,
        "google_name": place["name"],
        "name_strength": strength,
        "distance_m": distance,
        "limit_m": MAX_DISTANCE_BY_STRENGTH.get(strength),
        "osm": {**osm, "map": _osm_map(osm)},
        "google": {
            "place_id": place["place_id"],
            "map": place["map"],
            "fetched_at": fetched_at,
            "details": details,
        },
    }
    if other_osm_ids:
        item["other_osm_ids"] = other_osm_ids
    return item


def _cache_put(cache, osm_id, details, fetched_at, match, held_reason=None):
    """Save one Place Details answer. `match` says what it is used for:
    "matched" (the restaurant's Google data), "review" (held for a person)
    or "override" (fetched for a hand-checked decision). held_reason is kept
    for a hold that must last until a person decides (replaces_removed)."""
    cache[osm_id] = {
        "place_id": details.get("id", ""),
        "api": CACHE_API,
        "match": match,
        "fetched_at": fetched_at,
        "details": details,
        **({"held_reason": held_reason} if held_reason else {}),
    }


def _searched_with(name, lat, lon):
    """What a search was made with, saved in a "not_found" cache entry: a
    later run searches again only when one of these has changed."""
    return {"name": name, "lat": lat, "lon": lon}


def _stops_the_run(exc):
    """A bad or invalid key, Places API (New) not enabled, or a field name
    Google does not know: every call would fail, so the run stops."""
    message = str(exc).lower()
    return exc.status in (401, 403) or (exc.status == 400 and ("field" in message or "api key" in message))


def refresh_details(entry):
    """Fresh Place Details for a saved answer, by its place ID. Returns
    (details, fetched_at, status): the fresh answer ("REFRESHED"); the saved
    one when the call fails ("KEPT SAVED (...)"), so a Google problem never
    wipes a restaurant's data; or (None, None, "PLACE ID GONE") when Google no
    longer knows the place ID. A key problem is raised (it stops the run)."""
    try:
        return place_details(entry["place_id"]), _now_utc(), "REFRESHED"
    except PlacesAPIError as exc:
        if _stops_the_run(exc):
            raise
        if exc.status == 404 or (exc.status == 400 and "place" in str(exc).lower()):
            return None, None, "PLACE ID GONE"
        return entry["details"], entry.get("fetched_at", ""), f"KEPT SAVED (refresh failed: {exc})"
    except Exception as exc:  # network or server errors, after the retries in _request()
        return entry["details"], entry.get("fetched_at", ""), f"KEPT SAVED (refresh failed: {exc})"


def gone_places(cache, current_osm_ids):
    """{place_id: osm_id} for the cached matches whose restaurant is no longer
    in OSM (not in osm_raw.csv): a new restaurant that finds one of these
    places is held as replaces_removed."""
    return {
        entry["place_id"]: osm_id
        for osm_id, entry in cache.items()
        if osm_id not in current_osm_ids and entry.get("match") in ("matched", "override")
        and entry.get("place_id")
    }


def replaces_removed_item(osm, details, fetched_at, old_osm_id):
    """The review item of a restaurant held as replaces_removed."""
    return review_item(
        osm, details, fetched_at, "replaces_removed",
        f"This Google place belonged to OSM restaurant {old_osm_id}, which is no longer in "
        "OpenStreetMap. If it is the same shop (redrawn with a new ID), give this osm_id the "
        "place_id: its database row then moves to the new ID, with its reviews. If it is a "
        "different shop, give it null.",
        [old_osm_id],
    )


def use_override(osm_id, place_id, cache, refresh=False):
    """Apply a hand-checked decision. Returns (details or None, status).
    Details already cached for the same place (a match or a review entry)
    are reused, so approving a reviewed place costs no Google call; with
    refresh they are fetched again."""
    if not place_id:
        return None, "OVERRIDE: no Google match"
    entry = cache.get(osm_id)
    if entry and entry.get("api") == CACHE_API and entry.get("place_id") == place_id:
        if not refresh:
            return entry["details"], "OVERRIDE"
        details, fetched_at, status = refresh_details(entry)
        if details is None:
            print(f"  → WARNING: Google no longer knows the place ID {place_id} given to {osm_id} "
                  f"in {OVERRIDES_FILE}: the saved data is kept; check the override")
            return entry["details"], "OVERRIDE (place ID gone: check the override)"
        if status == "REFRESHED":
            _cache_put(cache, osm_id, details, fetched_at, "override")
        return details, f"OVERRIDE {status}"
    _cache_put(cache, osm_id, place_details(place_id), _now_utc(), "override")
    return cache[osm_id]["details"], "OVERRIDE"


def match_restaurant(osm, cache, review, prefix, refresh=False, gone=None):
    """Find the Google place for one OSM restaurant. Returns (details or
    None, status).

    A cached answer is first checked again with the current rules, which
    needs no Google call: a match that still passes is used; a restaurant
    already held for review that is still a review case stays held. With
    refresh, a saved match is fetched again first (refresh_details()). Anything
    else is searched again: one Text Search for the name. The best candidate
    that passes match_problem() is the match, unless its place belonged to a
    restaurant no longer in OSM (`gone`, see gone_places()): then the
    restaurant is held as replaces_removed. Otherwise the best candidate worth
    a person's look (review_reason()) gets its Place Details cached as
    "review", is added to `review`, and the restaurant is held back until a
    person decides. Nothing alike within SEARCH_RADIUS_M: NOT FOUND, saved
    as a "not_found" entry with the name and pin searched; without refresh it
    is not searched again until one of those changes."""
    osm_id, name = osm.get("osm_id", ""), osm.get("name", "").strip()
    lat, lon = osm.get("latitude", "").strip(), osm.get("longitude", "").strip()
    gone = gone or {}

    known = {}  # place_id -> (details, fetched_at) already in hand, never fetched twice
    rejected = None  # the cached place, when it no longer fits the rules
    entry = cache.get(osm_id)
    if entry and entry.get("held_reason") == "replaces_removed" and entry.get("match") == "review":
        old_osm_id = gone.get(entry.get("place_id"))
        if old_osm_id:
            # Waiting for a person: no new search, no new fetch
            review.append(replaces_removed_item(osm, entry["details"], entry.get("fetched_at", ""), old_osm_id))
            return None, "HELD FOR REVIEW (cached)"
        # The old restaurant is back in OSM: the usual rules decide again
        del cache[osm_id]
        entry = None
    if entry and entry.get("match") == "not_found":
        # Searched before and nothing found: searched again only on a refresh
        # day, or when the OSM name or pin has changed since
        if not refresh and entry.get("searched_with") == _searched_with(name, lat, lon):
            return None, "NOT FOUND (cached)"
        del cache[osm_id]
        entry = None
    if entry:
        if entry.get("api") != CACHE_API:
            # Saved by the older Places API: same place ID, new details
            details, fetched_at, status = place_details(entry.get("place_id", "")), _now_utc(), "REFRESHED"
        elif refresh and entry.get("match") == "matched":
            details, fetched_at, status = refresh_details(entry)
            if details is None:
                print(f"{prefix} → Google no longer knows place ID {entry.get('place_id')}, searching again")
                del cache[osm_id]
                entry = None
        else:
            details, fetched_at, status = entry["details"], entry.get("fetched_at", ""), "CACHE"
    if entry:
        place = _place_from_details(details)
        known[place["place_id"]] = (details, fetched_at)
        problem = match_problem(name, lat, lon, place)
        if problem is None:
            if status == "REFRESHED" or entry.get("match") == "review":
                _cache_put(cache, osm_id, details, fetched_at, "matched")
            return details, status
        reason = review_reason(name, lat, lon, place)
        if reason and entry.get("match") == "review":
            # Searched before and still waiting for a person: no new search
            review.append(review_item(osm, details, fetched_at, *reason))
            return None, "HELD FOR REVIEW (cached)"
        print(f"{prefix} → cached answer no longer fits the rules ({problem}), searching again")
        del cache[osm_id]
        rejected = place

    candidates = text_search(lat, lon, name)
    match = best_match(name, lat, lon, candidates)
    if match:
        details, fetched_at = known.get(match["place_id"]) or (place_details(match["place_id"]), _now_utc())
        old_osm_id = gone.get(match["place_id"])
        if old_osm_id and old_osm_id != osm_id:
            _cache_put(cache, osm_id, details, fetched_at, "review", held_reason="replaces_removed")
            review.append(replaces_removed_item(osm, details, fetched_at, old_osm_id))
            return None, "HELD FOR REVIEW"
        _cache_put(cache, osm_id, details, fetched_at, "matched")
        return details, "MATCHED"

    # The cached place counts too: Google may not return it any more
    pick = best_for_review(name, lat, lon, candidates + ([rejected] if rejected else []))
    if pick:
        details, fetched_at = known.get(pick["place_id"]) or (place_details(pick["place_id"]), _now_utc())
        _cache_put(cache, osm_id, details, fetched_at, "review")
        review.append(review_item(osm, details, fetched_at, *review_reason(name, lat, lon, pick)))
        return None, "HELD FOR REVIEW"
    cache[osm_id] = {"match": "not_found", "searched_at": _now_utc(),
                     "searched_with": _searched_with(name, lat, lon)}
    return None, "NOT FOUND"


def find_duplicates(osm_by_id, matched, cache):
    """Find Google places matched by two or more OSM restaurants.

    Same name (the same shop mapped twice in OSM): the restaurant whose OSM
    pin is nearest Google's pin is kept and the others are dropped. Different
    names: all of them are held for review (shared_google_place), since
    Google can only be one of them. `matched` is {osm_id: Place Details}.
    Returns (dropped, held): DUPLICATES_JSON entries and MATCH_REVIEW_JSON
    items.
    """
    by_place = {}
    for osm_id, details in matched.items():
        by_place.setdefault(details.get("id", ""), []).append(osm_id)

    dropped, held = [], []
    for place_id, osm_ids in by_place.items():
        if len(osm_ids) < 2:
            continue
        place = _place_from_details(matched[osm_ids[0]])
        osms = [osm_by_id[i] for i in osm_ids]

        def to_google(osm):
            if place["lat"] is None or place["lon"] is None:
                return 0
            return haversine_m(float(osm["latitude"]), float(osm["longitude"]), place["lat"], place["lon"])

        if all(name_strength(osms[0]["name"], o["name"]) == "same" for o in osms[1:]):
            keep = min(osms, key=to_google)
            for osm in osms:
                if osm is keep:
                    continue
                dropped.append(
                    {
                        "osm_id": osm["osm_id"],
                        "osm_name": osm["name"],
                        "osm_map": _osm_map(osm),
                        "kept_osm_id": keep["osm_id"],
                        "kept_osm_name": keep["name"],
                        "google_place_id": place_id,
                        "google_name": place["name"],
                        "google_map": place["map"],
                        "distance_to_google_m": round(to_google(osm)),
                        "kept_distance_to_google_m": round(to_google(keep)),
                        "reason": "same name and same Google place as the kept restaurant "
                                  "(the same shop mapped twice in OSM); the one nearer "
                                  "Google's pin is kept",
                    }
                )
        else:
            for osm in osms:
                others = [o for o in osms if o is not osm]
                named = ", ".join(f"'{o['name']}' ({o['osm_id']})" for o in others)
                held.append(
                    review_item(
                        osm,
                        matched[osm["osm_id"]],
                        cache.get(osm["osm_id"], {}).get("fetched_at", ""),
                        "shared_google_place",
                        f"Matched the same Google place as {named}. Google can only be one of them.",
                        [o["osm_id"] for o in others],
                    )
                )
    return dropped, held


def write_match_review(items):
    """Write MATCH_REVIEW_JSON, the one review file: the held restaurants,
    sorted by reason, then name strength, then distance. Returns
    {reason: count}."""
    path = MATCH_REVIEW_JSON
    reasons = list(REVIEW_REASONS)
    rank = {s: i for i, s in enumerate(STRENGTH_ORDER)}
    items.sort(key=lambda r: (
        reasons.index(r["reason"]),
        rank.get(r["name_strength"], len(rank)),
        r["distance_m"] or 0,
    ))
    counts = {reason: n for reason in reasons if (n := sum(1 for r in items if r["reason"] == reason))}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "how_to_use": (
                    "These restaurants are held back: preprocessing leaves them out until "
                    "you decide. For each item, read reason_text and compare the two sides "
                    "(osm and google, each with its map link). Then add its osm_id to "
                    f"{OVERRIDES_FILE} with google.place_id if it is the same place, or null "
                    "if it is not (the restaurant then goes on with OSM data only). Then run: "
                    "python run_1_extraction.py --skip-osm, and preprocessing again. Do not write "
                    "decisions in this file: it is rewritten on every run."
                ),
                "reasons": REVIEW_REASONS,
                "created_at": _now_utc(),
                "counts": counts,
                "items": items,
            },
            f, ensure_ascii=False, indent=2,
        )
    return counts


# ---------------------------------------------------------------------------
# Main extraction loop
# ---------------------------------------------------------------------------


def run(refresh=False):
    """Find and fetch the Google data of every OSM restaurant. With refresh,
    saved matches are fetched again (see REFRESH at the top)."""
    extracted_at = _now_utc()  # with its time zone, like OSM's: 2026-11-16T16:00:05+00:00
    if refresh:
        print("REFRESH — fetching fresh Place Details for every saved match "
              "(a failed fetch keeps the saved data).\n")

    osm_rows = read_osm_rows()
    total = len(osm_rows)
    cache = load_cache()
    overrides = load_overrides()
    # Places of cached restaurants no longer in OSM
    gone = gone_places(cache, {o.get("osm_id", "") for o in osm_rows})

    google_rows = []
    review_rows = []
    facility_rows = []
    match_review = []  # -> MATCH_REVIEW_JSON
    matched = {}  # osm_id -> Place Details, for find_duplicates()

    counts = Counter()

    # The cache is saved every SAVE_EVERY restaurants and when the run stops
    # early (Ctrl+C or an error), so a rerun pays only for what is missing.
    try:
        for idx, osm in enumerate(osm_rows, start=1):
            if save_due(idx - 1):
                save_cache(cache)

            osm_id = osm.get("osm_id", "")
            name = osm.get("name", "").strip()
            lat = osm.get("latitude", "").strip()
            lon = osm.get("longitude", "").strip()

            prefix = f"[{idx}/{total}] {name or '(unnamed)'}"

            # Skip rows without name or coordinates
            if not name or not lat or not lon:
                print(f"{prefix} → SKIP (missing name or coords)")
                continue

            try:
                if osm_id in overrides:
                    details, status = use_override(osm_id, overrides[osm_id].get("place_id"), cache, refresh)
                else:
                    details, status = match_restaurant(osm, cache, match_review, prefix, refresh, gone)
            except PlacesAPIError as exc:
                if _stops_the_run(exc):
                    # Bad or invalid key (Google answers 400 "API key not valid"),
                    # Places API (New) not enabled, or a field name Google does
                    # not know (in DETAILS_FIELDS or categories.json): every call
                    # would fail. Stop before any output file is rewritten; the
                    # cache is saved below.
                    raise
                details, status = None, f"ERROR ({exc})"
            except Exception as exc:
                details, status = None, f"ERROR ({exc})"

            counts[status.split(" (")[0]] += 1
            if details is None:
                print(f"{prefix} → {status}")
                continue
            print(f"{prefix} → {status} ({details.get('id', '')[:20]}…)")
            matched[osm_id] = details

            fetched_at = cache.get(osm_id, {}).get("fetched_at", "")
            google_rows.append(build_google_row(osm_id, details, extracted_at, fetched_at))
            review_rows.extend(build_review_rows(osm_id, details, extracted_at))
            facility_rows.extend(build_facility_rows(osm_id, details, extracted_at))
    except BaseException:
        print(f"\nStopped early: saving the Google answers so far to {CACHE_FILE}.")
        print("Run the same command again; cached restaurants are not asked again.")
        save_cache(cache)
        raise

    # One Google place matched by two or more OSM restaurants: drop the extra
    # copies of the same shop, hold the rest for review. Neither goes on.
    dropped, held = find_duplicates({o.get("osm_id", ""): o for o in osm_rows}, matched, cache)
    match_review.extend(held)
    removed = {d["osm_id"] for d in dropped} | {h["osm_id"] for h in held}
    google_rows = [r for r in google_rows if r["osm_id"] not in removed]
    review_rows = [r for r in review_rows if r["osm_id"] not in removed]
    facility_rows = [r for r in facility_rows if r["osm_id"] not in removed]
    total_reviews = len(review_rows)

    # Write outputs
    os.makedirs(os.path.dirname(GOOGLE_RAW_CSV), exist_ok=True)

    with open(GOOGLE_RAW_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=GOOGLE_RAW_COLUMNS)
        writer.writeheader()
        writer.writerows(google_rows)

    with open(REVIEWS_RAW_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=REVIEWS_COLUMNS)
        writer.writeheader()
        writer.writerows(review_rows)

    with open(FACILITIES_RAW_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FACILITIES_COLUMNS)
        writer.writeheader()
        writer.writerows(facility_rows)

    review_counts = write_match_review(match_review)

    os.makedirs(os.path.dirname(DUPLICATES_JSON), exist_ok=True)
    with open(DUPLICATES_JSON, "w", encoding="utf-8") as f:
        json.dump(
            {
                "how_to_read": (
                    "OSM restaurants dropped as the same shop mapped twice: same name and same "
                    "Google place as the kept one, which is nearer Google's pin. Preprocessing "
                    f"leaves them out. To keep one anyway, give it its own entry in {OVERRIDES_FILE} "
                    "(its own Google place_id, or null to keep it with OSM data only)."
                ),
                "dropped": dropped,
            },
            f, ensure_ascii=False, indent=2,
        )

    save_cache(cache)

    # Summary
    print(f"\n{'='*60}")
    print("Extraction complete. Summary:")
    print(f"  Total processed  : {total}")
    for status, n in sorted(counts.items()):
        print(f"  {status:<27}: {n}")
    print(f"  Total reviews    : {total_reviews}")
    print(f"\n  {GOOGLE_RAW_CSV:<45} {len(google_rows)} rows")
    print(f"  {REVIEWS_RAW_CSV:<45} {len(review_rows)} rows")
    print(f"  {FACILITIES_RAW_CSV:<45} {len(facility_rows)} rows")
    by_reason = ", ".join(f"{reason} {n}" for reason, n in review_counts.items()) or "none"
    print(f"  {MATCH_REVIEW_JSON:<45} {len(match_review)} restaurants held until you review them"
          f" ({by_reason})")
    print(f"  {DUPLICATES_JSON:<45} {len(dropped)} dropped as the same shop mapped twice in OSM")
    print(f"  {CACHE_FILE:<45} (cache)")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract Google Places data for OSM restaurants."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Fetch fresh Place Details for every saved match (a Google refresh).",
    )
    args = parser.parse_args()
    run(refresh=args.refresh)
