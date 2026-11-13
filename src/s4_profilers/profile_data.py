"""
profile_data.py — The AI stage (stage 4). ONE AI call per restaurant settles
where OpenStreetMap and Google disagree AND profiles the restaurant.

Reads data/3_merged/pj_merged.json (stage 3 merges by rules only and leaves
the fields where the sources disagree in each restaurant's "conflicts").

The prompt has three parts: the lists from src/reference/categories.json (the same in
every call), the restaurant's facts, and the fields where the sources
disagree (only when they do). The AI answers in JSON:

  1. merge           — for each disagreeing field (name, phone, website,
                       full_address, postcode, street): which source to keep,
                       with a reason. The value is copied from that source,
                       never typed by the AI. For every field but the name the
                       AI may trust neither ("none"): the field stays empty and
                       merge_log keeps both values and the AI's reason. A
                       postcode or street that neither source had is then read
                       from the chosen address.
  2. cuisines        — 1 to 3 names picked ONLY from cuisine.name in
                       src/reference/categories.json and ranked (1 = most important);
                       origin_country and category come from that file. Names
                       outside the list are dropped; none left → "Other"
  3. price_range     — {tier, avg_meal_price}, see price_range_for():
                       avg_meal_price: the middle of Google's price band when
                       there is one (but the AI's estimate, kept inside the
                       band, when the middle and Google's price level give
                       different tiers); otherwise the AI's estimate, kept
                       inside the tier of Google's price level when there is one
                       tier: not asked from the AI; set from avg_meal_price
                       using the price bands in src/reference/categories.json
  4. business_profile — target_segment, service_style, restaurant_type,
                       business_style, ambiance (each picked ONLY from its list
                       in src/reference/categories.json; a value not listed is dropped and
                       the column may stay empty; target_segment and ambiance
                       hold up to 3 and 2 values as "families, students"),
                       halal_status, generated_at: when the AI answered (UTC),
                       evidence_level: how much the AI had to work with, set by
                       evidence_level() below, never by the AI
The AI is shown: the names (both when they differ), amenity type, brand, OSM
cuisine and halal tags, Google's types, Maps label and description, Google's
price band or level, the address, area, what is nearby, opening hours,
Google's facilities, the rating, and up to MAX_REVIEW_TEXTS review texts
(each cut at MAX_REVIEW_CHARS characters), in this order: the reviews of
Google's latest fetch in Google's order (Google sorts them by relevance), then
older ones from the review cache, newest first; texts shorter than
SHORT_REVIEW_CHARS ("nice") go last.

ASKED AGAIN ONLY WHEN SOMETHING CHANGED: each cached answer keeps the hashes
of the restaurant's OSM and Google records it was made from (record_hashes,
see src/record_hash.py: fetch times, the rating and the review count are left
out). An answer is reused while it was given to this PROMPT_VERSION, for the
same disagreeing values, and the hashes are the same; otherwise the
restaurant is asked again. A new rating, new reviews or a change around the
restaurant (nearby places, its section) never asks again.

REVIEWS AND THEIR SENTIMENT: data/cache/review_cache.json keeps every review
ever collected, by google_review_id, with its Google place and its sentiment.
Each run adds the reviews of Google's latest fetch; nothing is removed. After
the profiles, each review with text and no sentiment yet is sent in batches of
SENTIMENT_BATCH (one word back per review: positive, mixed, neutral or
negative; an unknown word is neutral). A review with no text gets none. Each
restaurant in the output carries all its reviews from the cache, so a review
Google stops showing is still loaded once it has its sentiment.

A failed call is tried again: a server error, a timeout or a lost connection
up to MAX_TRIES (4) times, waiting 15, 30 and 60 s between tries; an answer
the code cannot use up to UNUSABLE_TRIES (3) times, 5 s apart; rate limits
are waited out. If it still fails:
  - a profile call: the restaurant is listed in AI_FAILED_FILE and left out
    of the output, so it is not validated or loaded until a later run gets an
    answer. No rule decides in the AI's place.
  - a sentiment batch: its reviews are listed in AI_FAILED_FILE and left out
    of the output (no review is saved without its sentiment); their
    restaurant goes on. The next run asks for them again.

Output: data/4_profiled/pj_final.json — only restaurants with an answer;
        run_5_validation.py checks it before anything is loaded
Review: data/review/ai_failed.json (rewritten on every run)
Caches: data/cache/profile_cache.json (keyed by osm_id) and
        data/cache/review_cache.json (keyed by google_review_id)

Usage:
  python profile_data.py              # full run
  python profile_data.py --no-llm     # cached answers only; the rest are left out

Requires: pip install google-genai python-dotenv
.env must contain: GEMINI_API_KEY=your_key_here
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Lets `src` be imported when this file is run directly, not through run_4_profiling.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.cache_saving import save_due, save_json
from src.categories import allowed_values, get_column, value_definitions
from src.record_hash import restaurant_hashes
from src.s3_mergers.merge_data import (
    DAY_FIELDS, LOCATION_FIELDS, _log_entry, fields_waiting_for_address,
    read_parts_from_address, write_review_file,
)

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

INPUT_FILE       = os.path.join("data", "3_merged",   "pj_merged.json")
OUTPUT_FILE      = os.path.join("data", "4_profiled", "pj_final.json")
CACHE_FILE       = os.path.join("data", "cache",      "profile_cache.json")
# Every review ever collected, with its sentiment (see the text at the top)
REVIEW_CACHE_FILE = os.path.join("data", "cache",     "review_cache.json")
# Review file, rewritten on every run (an empty list when there is nothing):
# restaurants with no usable answer and reviews with no sentiment, left out
# of OUTPUT_FILE
AI_FAILED_FILE   = os.path.join("data", "review", "ai_failed.json")

GEMINI_MODEL     = "gemma-4-26b-a4b-it"  # a Gemma model, reached with the Gemini API key
RATE_LIMIT_WAITS = [30, 60, 120]  # seconds to wait after a rate limit; these do not count as tries
# A server error (500, 503), a timeout or a lost connection: the AI service
# is having trouble, which can last minutes, so wait longer before each new try
SERVER_ERROR_WAITS = [15, 30, 60]  # seconds before try 2, 3 and 4
MAX_TRIES        = len(SERVER_ERROR_WAITS) + 1  # 4 tries in all for such failures
# An answer the code cannot use (not JSON, a field left undecided): waiting
# does not help, so ask again soon, up to 3 tries
UNUSABLE_TRIES   = 3
RETRY_WAIT       = 5              # seconds before asking again after an unusable answer
CALL_TIMEOUT_S   = 180            # a call that takes longer is a failed try
# How much the model thinks before it answers: None = its default (about 2,000
# thinking tokens, about 50 s a call) or "MINIMAL" (almost none, about 6 s a
# call). This model accepts no other level.
THINKING_LEVEL   = None
# The free tier allows 16,000 input tokens a minute for this model, and each
# prompt is about 6,000, so calls are spaced to stay under this many:
TOKENS_PER_MINUTE = 15_000
CHARS_PER_TOKEN   = 3.6           # about right for these prompts (22,000 characters ≈ 6,000 tokens)

# Up to 10 review texts in a profile prompt: even a prompt full of Chinese
# reviews then stays under the free tier's 16,000 input tokens a minute
MAX_REVIEW_TEXTS   = 10
MAX_REVIEW_CHARS   = 500
SHORT_REVIEW_CHARS = 20   # a shorter text ("nice", "Messy") goes last
SENTIMENT_BATCH    = 20   # reviews per sentiment call

HALAL      = allowed_values("business_profile.halal_status")
SENTIMENTS = allowed_values("review.sentiment")

VALID_HALAL      = set(HALAL)
VALID_SENTIMENTS = set(SENTIMENTS)

# The address fields share one rule in the prompt
ADDRESS_FIELDS = set(LOCATION_FIELDS)
# Fields the AI may leave empty by trusting neither source ("none"): every
# disagreeing field except the name, which every restaurant needs
NONE_ALLOWED = ADDRESS_FIELDS | {"phone", "website"}

# The cuisine list: {name: {definition, category, origin_country, includes}}
CUISINES         = get_column("cuisine.name")["values"]
CUISINE_BY_LOWER = {name.lower(): name for name in CUISINES}
MAX_CUISINES     = get_column("cuisine.name")["max"]
FALLBACK_CUISINE = "Other"  # when the AI gives no cuisine from the list

# The business_profile columns the AI picks from lists in src/reference/categories.json:
# {column: (allowed values, pick "one" or "many", most values)}. A value that is
# not listed is dropped; with nothing left the column stays empty.
PROFILE_LISTS = {
    column: (
        list(get_column(f"business_profile.{column}")["values"]),
        get_column(f"business_profile.{column}")["pick"],
        get_column(f"business_profile.{column}").get("max", 1),
    )
    for column in ("restaurant_type", "service_style", "business_style", "target_segment", "ambiance")
}

# Raise when the prompt changes what it asks for: cached answers to an older
# prompt are then asked again. 2 = cuisines picked from the list and ranked;
# 3 = Google's price band or level shown, estimate kept inside the level;
# 4 = what is nearby (offices, schools, stations, ...) shown for target_segment;
# 5 = the evidence level saved with each answer; 6 = restaurant_type,
# service_style, business_style, target_segment and ambiance picked from the
# lists, and Google's description shown; 7 = the estimate must fall inside
# Google's price band (used when a wide band and the level disagree);
# 8 = one call also settles where OSM and Google disagree (merging has no AI
# any more); facilities, opening hours, the address and both names shown;
# reviews cut at 500 characters; a flat JSON answer. Still 8 (decided
# 2026-11-09): "none" for phone and website was added later without raising
# it, since an "osm" or "google" answer is still valid under the new rule; the
# 960 answers cached before then could not choose "none" for those two.
# Still 8 (decided 2026-11-10): the prompt now shows up to 10 reviews (Google's
# latest first, then older ones) and no longer asks for review sentiments (a
# separate batch call does); every cached answer had already seen all the
# reviews its restaurant had (at most 5), so none is asked again.
PROMPT_VERSION = 8

# A Google-matched restaurant whose AI read at least this many review texts
# has evidence_level high (business_profile.evidence_level in categories.json).
HIGH_EVIDENCE_REVIEWS = 3

# Counted nearby kinds as (kind, radius in metres, nearby_context column),
# from nearby_place.kind in src/reference/categories.json, for the prompt's "Nearby" line.
NEARBY_COUNTED = [
    (kind, detail["radius_m"], detail["column"])
    for kind, detail in get_column("nearby_place.kind")["values"].items()
    if "radius_m" in detail
]

# Each price tier with the lowest price (MYR) that belongs to it, highest first.
TIER_FLOORS = sorted(
    ((detail["min_price"], tier)
     for tier, detail in get_column("price_range.tier")["values"].items()),
    reverse=True,
)


# Each tier's range in RM: (lowest price, lowest price of the next tier),
# None for the top tier. Mid is (20, 60): RM20 to RM59.
_FLOORS = sorted((detail["min_price"], tier)
                 for tier, detail in get_column("price_range.tier")["values"].items())
TIER_RANGES = {tier: (floor, _FLOORS[i + 1][0] if i + 1 < len(_FLOORS) else None)
               for i, (floor, tier) in enumerate(_FLOORS)}

# Google priceLevel (e.g. PRICE_LEVEL_MODERATE) → tier, from google_level in
# src/reference/categories.json: a starting match, to be checked against real bands.
LEVEL_TIER = {level: tier
              for tier, detail in get_column("price_range.tier")["values"].items()
              for level in detail.get("google_level", [])}

# How the prompt writes each day
DAY_SHORT = dict(zip(DAY_FIELDS, ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]))

# The rule the AI follows for each disagreeing field (one rule for the
# three address fields)
MERGE_RULES = {
    "name": "name: the name the shop is known by. Prefer the one without an added "
            "branch, mall or place name, without a label such as (Non-Halal), and "
            "without a second copy of the name in another language or script. If the "
            "two names spell the shop differently, follow the reviews and Google's description.",
    "phone": "phone: prefer a landline (+603-...) over a mobile (+601...-...); "
             "otherwise the number that looks complete. If neither number can be "
             'trusted, choose "none".',
    "website": "website: prefer the shop's own website over a social media page "
               "(Facebook, Instagram) or a delivery or booking page. If neither link "
               'can be trusted, choose "none".',
    "address": "full_address, postcode and street: prefer neither source. Choose the most "
               "complete and specific value (unit or lot number, street, postcode), and keep "
               "the postcode and street consistent with the address you choose. If neither "
               'value can be trusted, choose "none".',
}


def evidence_level(restaurant, n_review_texts):
    """How much the AI had to work with: high = matched on Google and at
    least HIGH_EVIDENCE_REVIEWS review texts; medium = matched on Google,
    fewer reviews; low = no Google match (only OpenStreetMap's name and tags)."""
    if not restaurant.get("google_place_id"):
        return "low"
    return "high" if n_review_texts >= HIGH_EVIDENCE_REVIEWS else "medium"


def tier_for_price(price):
    """Return the price tier that a meal price falls in, or None without a price."""
    if price is None:
        return None
    for floor, tier in TIER_FLOORS:
        if price >= floor:
            return tier
    return None


def band_middle(low, high):
    """The middle of Google's price band (RM20-40 → 30); its start when the
    top is open (RM100+); None without a band."""
    if low is not None and high is not None:
        return (low + high) / 2
    return low if low is not None else high


def keep_inside(price, tier):
    """Move a price into a tier's range: up to its lowest price, or down to
    just under the next tier (RM59 for mid)."""
    lowest, next_floor = TIER_RANGES[tier]
    if price < lowest:
        return lowest
    if next_floor is not None and price >= next_floor:
        return next_floor - 1
    return price


def keep_in_band(price, low, high):
    """Move a price into Google's band: up to its start, or down to its end.
    An open band (RM100+) has no end."""
    if low is not None and price < low:
        return low
    if high is not None and price > high:
        return high
    return price


def price_range_for(restaurant, llm_price):
    """Return {tier, avg_meal_price} for a restaurant.

    Google's price band → its middle. But when the middle and Google's price
    level give different tiers (a wide band, such as RM20-120 for a
    "Moderate" KFC), the AI's estimate decides, kept inside the band; without
    an estimate the middle is used. No band → the AI's estimate (None if
    there is none), kept inside the tier of Google's price level when Google
    gives one. The tier follows from the price, or from the level when there
    is no price, so the two always agree.
    """
    low, high = restaurant.get("google_price_low"), restaurant.get("google_price_high")
    middle = band_middle(low, high)
    level_tier = LEVEL_TIER.get(restaurant.get("google_price_level") or "")
    if middle is not None and middle > 0:
        price = middle
        if level_tier and tier_for_price(middle) != level_tier and llm_price is not None:
            price = keep_in_band(llm_price, low, high)
    else:
        price = llm_price
        if price is not None and level_tier:
            price = keep_inside(price, level_tier)
    tier = tier_for_price(price) if price is not None else level_tier
    return {"tier": tier, "avg_meal_price": price}


# ---------------------------------------------------------------------------
# AI client
# ---------------------------------------------------------------------------

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        _client = genai.Client(api_key=GEMINI_API_KEY,
                               http_options=types.HttpOptions(timeout=CALL_TIMEOUT_S * 1000))
    return _client


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def display_name(restaurant):
    """The restaurant's name for messages, also while the AI still has to choose it."""
    choice = (restaurant.get("conflicts") or {}).get("name") or {}
    return (restaurant.get("name") or choice.get("osm_value")
            or choice.get("google_value") or "(unnamed)")


def reviews_by_place(review_cache):
    """{google_place_id: [google_review_id, ...]}, to find a place's reviews fast."""
    index = {}
    for review_id, saved in review_cache.items():
        if saved.get("google_place_id"):
            index.setdefault(saved["google_place_id"], []).append(review_id)
    return index


def restaurant_reviews(restaurant, review_cache, by_place=None):
    """All the restaurant's reviews: those of Google's latest fetch in
    Google's order (it sorts them by relevance), then older ones from the
    review cache for the same Google place, newest first. Each is a dict of
    the review's fields, with its sentiment from the cache. by_place is
    reviews_by_place(review_cache), when already made."""
    latest = [r for r in restaurant.get("reviews") or [] if r.get("google_review_id")]
    seen = {r["google_review_id"] for r in latest}
    place = restaurant.get("google_place_id")
    if by_place is None:
        candidates = [rid for rid, saved in review_cache.items() if place and saved.get("google_place_id") == place]
    else:
        candidates = by_place.get(place, []) if place else []
    older = sorted(
        (dict(review_cache[rid], google_review_id=rid) for rid in candidates if rid not in seen),
        key=lambda r: r.get("published_at") or "", reverse=True,
    )
    reviews = []
    for review in latest + older:
        saved = review_cache.get(review["google_review_id"]) or {}
        reviews.append({
            "google_review_id":  review["google_review_id"],
            "author_name":       review.get("author_name"),
            "text":              review.get("text"),
            "individual_rating": review.get("individual_rating"),
            "published_at":      review.get("published_at"),
            "sentiment":         saved.get("sentiment"),
        })
    return reviews


def prompt_review_texts(reviews):
    """The review texts for the prompt: up to MAX_REVIEW_TEXTS, in the order
    of restaurant_reviews(), with the very short ones (under
    SHORT_REVIEW_CHARS) moved to the end."""
    texts = [(r.get("text") or "").strip() for r in reviews]
    texts = [t for t in texts if t]
    return ([t for t in texts if len(t) >= SHORT_REVIEW_CHARS]
            + [t for t in texts if len(t) < SHORT_REVIEW_CHARS])[:MAX_REVIEW_TEXTS]


def profile_list_lines(column, hint=None):
    """The prompt guideline for a listed business_profile column: its meaning,
    how many to pick, an optional hint, its rules, and every value with its
    definition, all from src/reference/categories.json."""
    detail = get_column(f"business_profile.{column}")
    _, pick, most = PROFILE_LISTS[column]
    how = "exactly one value" if pick == "one" else f"1 to {most} values, the most important first"
    return [
        f"- {column}: {detail['meaning']} Pick {how}, ONLY from this list, written exactly as listed.",
        *([f"  {hint}"] if hint else []),
        *[f"  {rule}" for rule in detail.get("rules", [])],
        *[f"  - {value}: {text}" for value, text in value_definitions(f"business_profile.{column}").items()],
    ]


def nearby_line(context):
    """The prompt line about what is around the restaurant, or None, e.g.
    "Nearby (OpenStreetMap, may be incomplete): within 500 m: school 1,
    mall 0, hotel 1, office 5; within 1000 m: university 2, hospital 0;
    nearest train station: KJ24 SS 15 (LRT), 420 m"."""
    if not context:
        return None
    by_radius = {}
    for kind, radius, column in NEARBY_COUNTED:
        by_radius.setdefault(radius, []).append(f"{kind.replace('_', ' ')} {context.get(column) or 0}")
    parts = [f"within {radius} m: {', '.join(items)}" for radius, items in sorted(by_radius.items())]
    if context.get("nearest_station"):
        kind = f" ({context['station_type']})" if context.get("station_type") else ""
        parts.append(f"nearest train station: {context['nearest_station']}{kind}, "
                     f"{context.get('station_distance_m')} m")
    return "Nearby (OpenStreetMap, may be incomplete): " + "; ".join(parts)


def _day_ranges(days):
    """Day indices 0-6 written as ranges: [0, 2, 3, 4, 5, 6] → "Mon, Wed-Sun"."""
    names = [DAY_SHORT[d] for d in DAY_FIELDS]
    runs, start = [], days[0]
    for prev, day in zip(days, days[1:] + [None]):
        if day is None or day != prev + 1:
            runs.append(names[start] if start == prev else f"{names[start]}-{names[prev]}")
            start = day
    return ", ".join(runs)


def hours_line(hours):
    """The prompt line with the opening hours, days with the same hours
    together, e.g. "Opening hours: Mon, Wed-Sun 07:00-21:30; Tue closed"; None
    when no day is known."""
    hours = hours or {}
    if not any(hours.get(day) for day in DAY_FIELDS):
        return None
    if hours.get("is_24_7"):
        return "Opening hours: open 24 hours, every day"
    groups = {}
    for i, day in enumerate(DAY_FIELDS):
        value = hours.get(day) or "unknown"
        groups.setdefault("closed" if value == "Closed" else value, []).append(i)
    return "Opening hours: " + "; ".join(f"{_day_ranges(days)} {value}" for value, days in groups.items())


def restaurant_lines(restaurant, review_texts):
    """Part 2 of the prompt: the restaurant's facts, only the lines that have data."""
    conflicts = restaurant.get("conflicts") or {}
    lines = []
    if "name" in conflicts:
        lines.append(f"Name (OpenStreetMap): {conflicts['name']['osm_value']}")
        lines.append(f"Name (Google): {conflicts['name']['google_value']}")
    else:
        lines.append(f"Name: {display_name(restaurant)}")
    lines.append(f"Amenity type: {restaurant.get('amenity_type') or 'restaurant'}")

    def add(label, value):
        value = (value or "").strip()
        if value:
            lines.append(f"{label}: {value}")

    add("Brand", restaurant.get("brand"))
    add("Cuisine tags (OpenStreetMap)", restaurant.get("cuisine_raw"))
    add("Halal tag (OpenStreetMap)", restaurant.get("halal_tag"))
    # Google's place types (e.g. chinese_restaurant): a hint, never stored
    primary_type = (restaurant.get("google_primary_type") or "").strip()
    google_types = [t for t in (restaurant.get("google_types") or "").split(",")
                    if t and t not in ("establishment", "point_of_interest", primary_type)]
    if primary_type or google_types:
        main = f"{primary_type} (main); " if primary_type else ""
        lines.append(f"Google types: {main}{', '.join(google_types)}")
    add("Google Maps label", restaurant.get("google_maps_type_label"))
    add("Google's description", restaurant.get("editorial_summary"))

    low, high = restaurant.get("google_price_low"), restaurant.get("google_price_high")
    level = restaurant.get("google_price_level") or ""
    if low is not None and high is not None:
        lines.append(f"Google price band: RM{low:g}-{high:g} per person")
    elif low is not None:
        lines.append(f"Google price band: RM{low:g}+ per person")
    elif high is not None:
        lines.append(f"Google price band: up to RM{high:g} per person")
    elif level in LEVEL_TIER:
        meaning = value_definitions("price_range.tier")[LEVEL_TIER[level]]
        lines.append(f"Google price level: {level} (here: {meaning})")

    # The address, unless the AI still has to choose it (it is in Part 3 then)
    if "full_address" not in conflicts and restaurant.get("full_address"):
        guessed = ((restaurant.get("merge_log") or {}).get("full_address") or {}).get("resolution")
        note = " (Nominatim's guess from the pin)" if guessed == "nominatim_guess" else ""
        lines.append(f"Address{note}: {restaurant['full_address']}")
    add("Area", restaurant.get("area_name"))
    nearby = nearby_line(restaurant.get("nearby_context"))
    if nearby:
        lines.append(nearby)
    hours = hours_line(restaurant.get("operating_hours"))
    if hours:
        lines.append(hours)
    facilities = [f["name"] for f in restaurant.get("facilities") or [] if f.get("name")]
    if facilities:
        lines.append("Google facilities (a facility not listed is unknown, not missing): "
                     + ", ".join(facilities))
    rating = restaurant.get("rating") or {}
    if rating.get("rating_score") is not None:
        lines.append(f"Rating: {rating['rating_score']} ({rating.get('total_reviews')} reviews)")

    if review_texts:
        lines.append(f"Review texts (Google's most relevant first, then older ones; up to "
                     f"{MAX_REVIEW_TEXTS}, each cut at {MAX_REVIEW_CHARS} characters):")
        for i, text in enumerate(review_texts, 1):
            cut = text[:MAX_REVIEW_CHARS] + "..." if len(text) > MAX_REVIEW_CHARS else text
            lines.append(f'{i}. "{cut}"')
    return lines


def conflict_lines(conflicts):
    """Part 3 of the prompt: the fields where the sources disagree, and the
    rule for each. Empty when they agree on everything."""
    if not conflicts:
        return []
    lines = [
        "PART 3 – WHERE THE SOURCES DISAGREE",
        'OpenStreetMap (source "osm") and Google (source "google") give different values for '
        "these fields. For each field, choose the source to keep. Its value is copied exactly, "
        "so you never write the value yourself.",
    ]
    for field, values in conflicts.items():
        lines.append(f'- {field}: osm "{values["osm_value"]}" | google "{values["google_value"]}"')
    lines.append("Rules:")
    rules = {"address" if field in ADDRESS_FIELDS else field for field in conflicts}
    lines += [f"- {MERGE_RULES[key]}" for key in ("name", "phone", "website", "address") if key in rules]
    return lines


def list_lines():
    """Part 1 of the prompt: every list the AI picks from, with its rules and
    hints (the same in every call)."""
    halal = get_column("business_profile.halal_status")
    return [
        "PART 1 – THE LISTS (pick values ONLY from these lists, each written exactly as listed)",
        f"- cuisines: pick the most suitable cuisines for this restaurant, at least 1 and at most "
        f"{MAX_CUISINES}. If you pick more than one, rank them: the most important first.",
        "  Use the cuisine tags, Google types, Google Maps label, both names (where two are given), "
        "brand and reviews.",
        "  Cuisine tags may contain semicolons (e.g. 'chinese;seafood') — treat each as separate.",
        *[f"  {rule}" for rule in get_column("cuisine.name").get("rules", [])],
        "  The list (name: definition; also called):",
        *[f"  - {name}: {detail['definition']}"
          + (f" Also called: {', '.join(detail['includes'])}." if detail.get("includes") else "")
          for name, detail in CUISINES.items()],
        "- avg_meal_price: what one person usually pays for a meal here. Use Malaysian market context",
        "  and any prices mentioned in the reviews. If a Google price band is given, your estimate",
        "  must fall inside that band; if only a Google price level is given, inside its range.",
        "  Price tiers:",
        "  " + " ".join(f"{tier}: {text}" for tier, text in value_definitions("price_range.tier").items()),
        *profile_list_lines("restaurant_type",
                            "Google types, the Google Maps label and Google's description, where given, "
                            "are hints (e.g. coffee_shop, fast_food_restaurant, Malaysian restaurant). "
                            "Opening hours are hints too, never proof: open 24 hours or late at night "
                            "fits a mamak; open only from morning to mid-afternoon fits a kopitiam or "
                            "hawker stall."),
        *profile_list_lines("service_style",
                            "Focus on how the customer orders and gets the food, not the atmosphere. "
                            "The Google facilities Dine-in, Takeout, Delivery and Curbside Pickup are "
                            "hints: Takeout or Delivery without Dine-in suggests takeaway_only or "
                            "delivery_only."),
        *profile_list_lines("business_style",
                            "Focus on who runs it: the brand and how many outlets it has, not the cuisine or vibe."),
        *profile_list_lines("target_segment",
                            "The Nearby line, where given, hints who is around: offices suggest office_workers, "
                            "universities and schools students and families, hotels tourists, malls mall_shoppers, "
                            "a close train station commuters. It comes from OpenStreetMap and may be incomplete, "
                            "so the restaurant's own details and reviews come first. A mall or office tower in "
                            "the address suggests mall_shoppers or office_workers. In the Google facilities, "
                            "Good for Children and Kids Menu suggest families, and Good for Groups large_groups; "
                            "opening late at night suggests late_night_crowd."),
        *profile_list_lines("ambiance",
                            "Live Music or Live Sports in the Google facilities suggests lively."),
        f"- halal_status: {halal['meaning']} Pick exactly one:",
        *[f"  - {value}: {text}" for value, text in value_definitions("business_profile.halal_status").items()],
        "  Use the halal tag first. Other signs: Halal or Non-Halal in a name or in Google's "
        "description; pork, lard or pork dishes (char siew, siu yuk, bak kut teh) in the reviews; "
        "a Malay or mamak shop. Beer, Wine or Cocktails in the Google facilities show that alcohol "
        "is served; alcohol is a main part of the business only for a bar or pub.",
    ]


def answer_lines(conflicts):
    """The JSON shape the AI must answer in."""
    lines = ["ANSWER", "Respond in JSON only, no markdown, no backticks, in this shape:", "{"]
    if conflicts:
        lines.append('  "merge": {')
        for i, field in enumerate(conflicts):
            sources = '"osm", "google" or "none"' if field in NONE_ALLOWED else '"osm" or "google"'
            comma = "," if i < len(conflicts) - 1 else ""
            lines.append(f'    "{field}": {{"source": {sources}, "reason": "brief reason"}}{comma}')
        lines.append("  },")
    lines += [
        '  "cuisines": ["most important cuisine", "second (optional)", "third (optional)"],',
        '  "avg_meal_price": <positive number — estimated MYR per person>,',
        *[f'  "{column}": ' + (f'"one value from the {column} list",' if pick == "one" else
                              f'["1 to {most} values from the {column} list, most important first"],')
          for column, (_, pick, most) in PROFILE_LISTS.items()],
        f'  "halal_status": "{" OR ".join(HALAL)}"',
        "}",
    ]
    return lines


def build_prompt(restaurant, review_cache, by_place=None):
    """Build the prompt. Returns (prompt, n_review_texts, facts): facts is
    the restaurant's own part (Parts 2 and 3), kept in AI_FAILED_FILE when
    the call fails."""
    review_texts = prompt_review_texts(restaurant_reviews(restaurant, review_cache, by_place))
    n = len(review_texts)
    conflicts = restaurant.get("conflicts") or {}

    jobs = "Describe the restaurant with values from the lists in Part 1."
    if conflicts:
        jobs = ("You have two jobs: describe the restaurant with values from the lists in Part 1, "
                "and, for each field in Part 3, choose which source to keep.")
    facts = ["PART 2 – THE RESTAURANT", *restaurant_lines(restaurant, review_texts)]
    if conflicts:
        facts += ["", *conflict_lines(conflicts)]
    lines = [
        "You are checking and describing one food business in Petaling Jaya, Malaysia.",
        "Use the facts given here and general knowledge of Malaysian food; do not invent facts.",
        jobs,
        "",
        *list_lines(),
        "",
        *facts,
        "",
        *answer_lines(conflicts),
    ]
    return "\n".join(lines), n, facts


# ---------------------------------------------------------------------------
# AI call with retries
# ---------------------------------------------------------------------------

class UnusableAnswer(ValueError):
    """An AI answer the code cannot use."""


class DailyQuotaReached(Exception):
    """The AI's daily free quota is used up: the run stops, and the same command
    continues from the cache once the quota resets."""


class AICallFailed(Exception):
    """The AI gave no usable answer; tries says how often it was asked."""

    def __init__(self, exc, tries):
        super().__init__(f"{type(exc).__name__}: {exc}")
        self.tries = tries


def parse_json(text):
    """Strip markdown fences and isolate the JSON object, then parse."""
    if not text or not text.strip():
        raise UnusableAnswer("the answer is empty")
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1:
        t = t[start:end + 1]
    return json.loads(t)


def check_usable(answer, conflicts):
    """Raise UnusableAnswer unless the answer is a JSON object that chooses a
    source for every disagreeing field ("none" for any field but the name).
    Nothing else is checked here: values that are not on a list are dropped
    when the answer is applied, and run_5_validation.py checks the result."""
    if not isinstance(answer, dict):
        raise UnusableAnswer("the answer is not a JSON object")
    merge = answer.get("merge") if conflicts else {}
    if conflicts and not isinstance(merge, dict):
        raise UnusableAnswer("the answer has no merge part")
    for field in conflicts:
        decision = merge.get(field)
        source = str(decision.get("source") or "").strip().lower() if isinstance(decision, dict) else ""
        allowed = ("osm", "google", "none") if field in NONE_ALLOWED else ("osm", "google")
        if source not in allowed:
            raise UnusableAnswer(f"{field} was not decided (source {source or 'missing'!r})")


_sent = []  # (time, estimated input tokens) of the calls of the last minute


def wait_for_token_room(tokens):
    """Sleep until sending `tokens` more input tokens keeps the last 60 seconds
    under TOKENS_PER_MINUTE, then count them as sent."""
    while True:
        now = time.monotonic()
        _sent[:] = [(at, n) for at, n in _sent if now - at < 60]
        if not _sent or sum(n for _, n in _sent) + tokens <= TOKENS_PER_MINUTE:
            _sent.append((now, tokens))
            return
        time.sleep(60 - (now - _sent[0][0]) + 0.5)


def call_ai(prompt, check):
    """Ask the AI and return (answer, tries). `check(answer)` raises
    UnusableAnswer for an answer the code cannot use (check_usable() for a
    profile, check_sentiments() for a sentiment batch).

    A rate limit (429) is waited out (RATE_LIMIT_WAITS; not counted as a try).
    A server error, a timeout or a lost connection is tried again after
    SERVER_ERROR_WAITS (15, 30, 60 s), up to MAX_TRIES (4) tries in all; an
    unusable answer is asked again after RETRY_WAIT (5 s), up to
    UNUSABLE_TRIES (3) tries. Any other error (such as a bad request) fails
    at once. Raises AICallFailed when there is no usable
    answer, and DailyQuotaReached when the day's free quota is used up. Calls
    are spaced by wait_for_token_room()."""
    from google.genai import types
    client = _get_client()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        **({"thinking_config": types.ThinkingConfig(thinking_level=THINKING_LEVEL)}
           if THINKING_LEVEL else {}),
    )
    tokens = int(len(prompt) / CHARS_PER_TOKEN)
    rate_waits = list(RATE_LIMIT_WAITS)
    tries = 0
    while True:
        tries += 1
        wait_for_token_room(tokens)
        try:
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=config)
            answer = parse_json(resp.text)
            check(answer)
            return answer, tries
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            code = getattr(exc, "code", None)
            code = code if isinstance(code, int) else None
            if code == 429 or "RESOURCE_EXHAUSTED" in str(exc):
                if "PerDay" in str(exc):
                    raise DailyQuotaReached(str(exc)[:300]) from exc
                if not rate_waits:
                    raise AICallFailed(exc, tries) from exc
                wait = rate_waits.pop(0)
                print(f"    Rate limit hit, waiting {wait}s before asking again...")
                time.sleep(wait)
                tries -= 1
                continue
            # Not JSON (json.loads) or not usable (check): a ValueError
            unusable = isinstance(exc, ValueError)
            if (code is not None and code < 500) or tries >= (UNUSABLE_TRIES if unusable else MAX_TRIES):
                raise AICallFailed(exc, tries) from exc
            wait = RETRY_WAIT if unusable else SERVER_ERROR_WAITS[min(tries, len(SERVER_ERROR_WAITS)) - 1]
            print(f"    Try {tries} failed ({type(exc).__name__}: {str(exc)[:120]}), "
                  f"trying again in {wait}s...")
            time.sleep(wait)


# ---------------------------------------------------------------------------
# Review sentiment, in batches
# ---------------------------------------------------------------------------

def sentiment_prompt(texts):
    """One prompt that asks the sentiment of several reviews at once."""
    lines = [
        "You are reading customer reviews of food businesses in Petaling Jaya, Malaysia.",
        "For each review below, give its overall sentiment, one of:",
        *[f"- {value}: {text}" for value, text in value_definitions("review.sentiment").items()],
        *[f"  {rule}" for rule in get_column("review.sentiment").get("rules", [])],
        "",
        f"Reviews (each cut at {MAX_REVIEW_CHARS} characters):",
    ]
    for i, text in enumerate(texts, 1):
        cut = text[:MAX_REVIEW_CHARS] + "..." if len(text) > MAX_REVIEW_CHARS else text
        lines.append(f'{i}. "{cut}"')
    lines += [
        "",
        "ANSWER",
        "Respond in JSON only, no markdown, no backticks, in this shape:",
        f'{{"sentiments": [<exactly {len(texts)} items, one of {"/".join(SENTIMENTS)}, '
        f'in the same order as the {len(texts)} reviews>]}}',
    ]
    return "\n".join(lines)


def check_sentiments(answer, n):
    """Raise UnusableAnswer unless the answer has exactly n sentiments."""
    items = answer.get("sentiments") if isinstance(answer, dict) else None
    if not isinstance(items, list) or len(items) != n:
        got = len(items) if isinstance(items, list) else "no list"
        raise UnusableAnswer(f"expected {n} sentiments, got {got}")


def score_reviews(review_ids, review_cache, no_llm):
    """Give each review in review_ids (with text, no sentiment yet) its
    sentiment, SENTIMENT_BATCH per call, saved in review_cache. An unknown
    word is neutral. Returns ({review_id: error} for the reviews still
    without one, number of calls). Raises DailyQuotaReached."""
    failed, calls = {}, 0
    if no_llm:
        return {review_id: ("not asked (--no-llm)", 0) for review_id in review_ids}, 0
    for start in range(0, len(review_ids), SENTIMENT_BATCH):
        batch = review_ids[start:start + SENTIMENT_BATCH]
        texts = [review_cache[r]["text"].strip() for r in batch]
        try:
            answer, tries = call_ai(sentiment_prompt(texts), lambda a: check_sentiments(a, len(batch)))
        except AICallFailed as exc:
            failed.update({r: (str(exc), exc.tries) for r in batch})
            print(f"    Sentiment batch {start // SENTIMENT_BATCH + 1}: FAILED after {exc.tries} tries "
                  f"({exc}); its {len(batch)} reviews are left out")
            continue
        calls += 1
        for review_id, word in zip(batch, answer["sentiments"]):
            word = str(word).strip().lower()
            review_cache[review_id]["sentiment"] = word if word in VALID_SENTIMENTS else "neutral"
        save_json(REVIEW_CACHE_FILE, review_cache)
        print(f"    Sentiment batch {start // SENTIMENT_BATCH + 1}: {len(batch)} reviews scored"
              + (f" (after {tries} tries)" if tries > 1 else ""))
    return failed, calls


# ---------------------------------------------------------------------------
# Apply the answer to the restaurant record
# ---------------------------------------------------------------------------

def _safe_str(v):
    s = str(v).strip() if v is not None else ""
    return s if s else None


def _value_key(text):
    """Compare list values ignoring capitals, spaces and hyphens: "Office Workers" = office_workers."""
    return re.sub(r"[\s\-]+", "_", str(text).strip().lower())


def pick_values(raw, column):
    """The AI's answer for a listed business_profile column, keeping only
    listed values (matched by _value_key) without repeats: one value for a
    pick-one column; otherwise at most its max, in the AI's order (most
    important first), joined by ", " ("families, students"). None when no
    listed value is left, so the column stays empty."""
    allowed, pick, most = PROFILE_LISTS[column]
    by_key = {_value_key(value): value for value in allowed}
    items = raw if isinstance(raw, list) else str(raw).split(",") if raw is not None else []
    picked = []
    for item in items:
        value = by_key.get(_value_key(item))
        if value and value not in picked:
            picked.append(value)
    if not picked:
        return None
    return picked[0] if pick == "one" else ", ".join(picked[:most])


def pick_cuisines(raw):
    """Turn the AI's cuisines into [{name, rank, origin_country, category}]:
    only names from the list (matched ignoring capitals), no repeats, at most
    MAX_CUISINES, ranked 1, 2, 3 in the AI's order. If none is left, the
    restaurant gets FALLBACK_CUISINE. Country and category come from the list."""
    if isinstance(raw, str):
        raw = [raw]  # one name given as plain text
    names = []
    for item in raw if isinstance(raw, list) else []:
        text = _safe_str(item.get("name") if isinstance(item, dict) else item)
        name = CUISINE_BY_LOWER.get(text.lower()) if text else None
        if name and name not in names:
            names.append(name)
    names = names[:MAX_CUISINES] or [FALLBACK_CUISINE]
    return [
        {
            "name":           name,
            "rank":           rank,
            "origin_country": CUISINES[name]["origin_country"],
            "category":       CUISINES[name]["category"],
        }
        for rank, name in enumerate(names, start=1)
    ]


def apply_merge(restaurant, merge):
    """Copy each disagreeing field's value from the source the AI chose and
    record it in merge_log; then read a postcode or street that neither
    source had from the chosen address. A field the AI trusted neither source
    for ("none") stays empty; its merge_log entry keeps both values and the
    AI's reason. Removes the restaurant's "conflicts". Returns how many
    fields were left empty."""
    conflicts = restaurant.pop("conflicts", None) or {}
    merge_log = restaurant.setdefault("merge_log", {})
    left_empty = 0
    for field, values in conflicts.items():
        decision = merge[field]
        source = str(decision["source"]).strip().lower()
        reason = _safe_str(decision.get("reason")) or "AI choice"
        osm_v, google_v = values["osm_value"], values["google_value"]
        value = {"osm": osm_v, "google": google_v}.get(source)
        restaurant[field] = value
        merge_log[field] = _log_entry(osm_v, google_v, value, source, "ai", reason)
        left_empty += source == "none"
    read_parts_from_address(restaurant, merge_log, fields_waiting_for_address(merge_log))
    return left_empty


def apply_profile(restaurant, answer):
    """Write the profile from the AI's answer into the restaurant, in place."""

    # 1. cuisines — checked against the list, ranked in the AI's order
    restaurant["cuisines"] = pick_cuisines(answer.get("cuisines"))

    # 2. price_range — Google's band first, the AI's estimate otherwise
    try:
        llm_price = float(answer.get("avg_meal_price"))
        llm_price = llm_price if llm_price > 0 else None
    except (TypeError, ValueError):
        llm_price = None
    restaurant["price_range"] = price_range_for(restaurant, llm_price)

    # 3. business_profile — only values from the lists in categories.json
    raw_halal = (_safe_str(answer.get("halal_status")) or "").lower()
    restaurant["business_profile"] = {
        "target_segment":  pick_values(answer.get("target_segment"), "target_segment"),
        "restaurant_type": pick_values(answer.get("restaurant_type"), "restaurant_type"),
        "service_style":   pick_values(answer.get("service_style"), "service_style"),
        "business_style":  pick_values(answer.get("business_style"), "business_style"),
        "ambiance":        pick_values(answer.get("ambiance"), "ambiance"),
        "halal_status":    raw_halal if raw_halal in VALID_HALAL else "unknown",
        # When the AI gave this answer (UTC), kept with the answer in the cache
        "generated_at":    answer.get("generated_at"),
        # What the AI had to work with for this answer, kept with it too
        "evidence_level":  answer.get("evidence_level"),
    }
    # The reviews and their sentiments are set by main() from the review
    # cache (score_reviews()), not from this answer. An answer cached before
    # 2026-11-10 still has "review_sentiments" by position: no longer read.


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


def cached_answer(cache, osm_id, conflicts, hashes):
    """The cached answer for a restaurant, or None: it is reused only when it
    was given to this PROMPT_VERSION, for the same disagreeing values, and
    made from records with the same hashes (the restaurant's OSM and Google
    records have not changed)."""
    entry = cache.get(osm_id)
    if (isinstance(entry, dict) and entry.get("prompt_version") == PROMPT_VERSION
            and (entry.get("asked") or {}) == conflicts
            and entry.get("record_hashes") == hashes):
        return entry
    return None


def stamp_old_answers(cache, all_hashes):
    """Once, on the first run of this version: the cached answers saved
    before record hashes were kept (all 960 on 2026-11-10) were made from the
    current raw files, so they get those files' hashes instead of being asked
    again. Returns how many were stamped."""
    stamped = 0
    for osm_id, entry in cache.items():
        if isinstance(entry, dict) and "record_hashes" not in entry and osm_id in all_hashes:
            entry["record_hashes"] = all_hashes[osm_id]
            stamped += 1
    return stamped


def load_review_cache():
    """The review cache. On the first run of this version (no file yet) it is
    filled from the previous output, pj_final.json, whose reviews already have
    their sentiments, so nothing is asked for them."""
    if os.path.exists(REVIEW_CACHE_FILE):
        with open(REVIEW_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f), False
    review_cache = {}
    if os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            previous = json.load(f)
        seen_at = (previous.get("metadata") or {}).get("profiled_at")
        for restaurant in previous.get("restaurants", []):
            for review in restaurant.get("reviews") or []:
                if review.get("google_review_id"):
                    review_cache[review["google_review_id"]] = _review_entry(restaurant, review, seen_at)
    return review_cache, True


def _review_entry(restaurant, review, seen_at):
    return {
        "google_place_id":   restaurant.get("google_place_id"),
        "osm_id":            restaurant.get("osm_id"),
        "author_name":       review.get("author_name"),
        "text":              review.get("text"),
        "individual_rating": review.get("individual_rating"),
        "published_at":      review.get("published_at"),
        "sentiment":         review.get("sentiment"),
        "first_seen":        seen_at,
    }


def add_fetched_reviews(restaurant, review_cache, seen_at):
    """Add the reviews of Google's latest fetch that the cache does not have
    yet. Returns how many were new."""
    new = 0
    for review in restaurant.get("reviews") or []:
        review_id = review.get("google_review_id")
        if review_id and review_id not in review_cache:
            review_cache[review_id] = _review_entry(restaurant, {**review, "sentiment": None}, seen_at)
            new += 1
    return new


def needs_sentiment(saved):
    """A review that has text but no sentiment yet."""
    return bool((saved.get("text") or "").strip()) and not saved.get("sentiment")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="FoodSight AI stage: settle disagreements and profile.")
    parser.add_argument(
        "--no-llm", action="store_true",
        help="Ask the AI nothing: use cached answers only; the other restaurants are left out.",
    )
    args = parser.parse_args()

    if not args.no_llm and not GEMINI_API_KEY:
        sys.exit("ERROR: GEMINI_API_KEY not found in .env. "
                 "Add it, or run with --no-llm.")

    if not os.path.exists(INPUT_FILE):
        sys.exit(f"ERROR: {INPUT_FILE} not found. Run run_3_merging.py first.")

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        merged = json.load(f)

    restaurants = merged.get("restaurants", [])

    total = len(restaurants)
    cache = load_cache()
    all_hashes = restaurant_hashes()  # {osm_id: {"osm": ..., "google": ...}} of the raw files
    review_cache, first_run = load_review_cache()
    if first_run:
        stamped = stamp_old_answers(cache, all_hashes)
        print("First run with record hashes and the review cache:")
        print(f"  {stamped} cached AI answers got the hashes of the current raw files (not asked again)")
        print(f"  {len(review_cache)} reviews with their sentiments copied from {OUTPUT_FILE} "
              f"into {REVIEW_CACHE_FILE}")
    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new_reviews = sum(add_fetched_reviews(r, review_cache, run_at) for r in restaurants)
    by_place = reviews_by_place(review_cache)

    stats = {"called": 0, "cached": 0, "failed": 0, "skipped": 0, "retried": 0,
             "fields_decided": 0, "fields_left_empty": 0, "new_reviews": new_reviews,
             "sentiment_calls": 0, "reviews_scored": 0, "reviews_left_out": 0}
    answered = []   # restaurants with an answer -> OUTPUT_FILE
    ai_failed = []  # -> AI_FAILED_FILE

    def stop_for_quota(what):
        save_cache(cache)
        save_json(REVIEW_CACHE_FILE, review_cache)
        print(f"\nThe AI's daily free quota is used up ({what}). The answers so far are saved in "
              f"{CACHE_FILE} and {REVIEW_CACHE_FILE}.")
        print("Run the same command again once the quota resets (the next day): nothing already "
              "answered is asked again. No output file was written.")
        sys.exit(2)

    # The caches are saved every SAVE_EVERY restaurants and when the run stops
    # early (Ctrl+C or an error), so a rerun asks only what is missing.
    try:
        for idx, restaurant in enumerate(restaurants, start=1):
            if save_due(idx - 1):
                save_cache(cache)

            osm_id = str(restaurant.get("osm_id", ""))
            name = display_name(restaurant)
            conflicts = restaurant.get("conflicts") or {}
            hashes = all_hashes.get(osm_id)
            prompt, n_texts, facts = build_prompt(restaurant, review_cache, by_place)

            answer = cached_answer(cache, osm_id, conflicts, hashes)
            if answer is not None:
                stats["cached"] += 1
                print(f"  [{idx}/{total}] {name[:30]:32} -> CACHE")
            elif args.no_llm:
                stats["skipped"] += 1
                ai_failed.append({"kind": "profile", "osm_id": osm_id, "name": name,
                                  "error": "not asked (--no-llm)", "tries": 0, "facts": facts})
                print(f"  [{idx}/{total}] {name[:30]:32} -> SKIPPED (--no-llm), left out")
                continue
            else:
                try:
                    answer, tries = call_ai(prompt, lambda a: check_usable(a, conflicts))
                except DailyQuotaReached:
                    stop_for_quota(f"after {stats['called']} new profile answers this run")
                except AICallFailed as exc:
                    stats["failed"] += 1
                    ai_failed.append({
                        "kind": "profile", "osm_id": osm_id, "name": name, "error": str(exc),
                        "tries": exc.tries,
                        "failed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "facts": facts,
                    })
                    print(f"  [{idx}/{total}] {name[:30]:32} -> FAILED after {exc.tries} "
                          f"tries ({exc}), left out")
                    continue
                answer["prompt_version"] = PROMPT_VERSION
                answer["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                answer["evidence_level"] = evidence_level(restaurant, n_texts)
                # The values each merge choice was for: a later run asks again
                # when either value has changed
                answer["asked"] = conflicts
                # The records the answer was made from: a later run asks again
                # when the restaurant's OSM or Google record has changed
                answer["record_hashes"] = hashes
                cache[osm_id] = answer
                stats["called"] += 1
                stats["retried"] += tries > 1
                print(f"  [{idx}/{total}] {name[:30]:32} -> AI answered"
                      + (f" (after {tries} tries)" if tries > 1 else "")
                      + (f"; chose {', '.join(conflicts)}" if conflicts else ""))

            stats["fields_left_empty"] += apply_merge(restaurant, answer.get("merge") or {})
            apply_profile(restaurant, answer)
            stats["fields_decided"] += len(conflicts)
            answered.append(restaurant)

        # Sentiment for the reviews of these restaurants that have none yet
        pending = []
        for restaurant in answered:
            for review in restaurant_reviews(restaurant, review_cache, by_place):
                review_id = review["google_review_id"]
                if needs_sentiment(review_cache.get(review_id, {})) and review_id not in pending:
                    pending.append(review_id)
        failed_reviews = {}
        if pending:
            print(f"\nSentiment for {len(pending)} reviews, {SENTIMENT_BATCH} per call...")
            try:
                failed_reviews, stats["sentiment_calls"] = score_reviews(pending, review_cache, args.no_llm)
            except DailyQuotaReached:
                stop_for_quota("while scoring review sentiments")
            stats["reviews_scored"] = len(pending) - len(failed_reviews)

        # Each restaurant carries all its reviews; one still without a
        # sentiment is left out and listed, and asked again next run
        failed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for restaurant in answered:
            kept = []
            for review in restaurant_reviews(restaurant, review_cache, by_place):
                review_id = review["google_review_id"]
                if needs_sentiment(review_cache.get(review_id, {})):
                    error, tries = failed_reviews.get(review_id, ("no sentiment yet", 0))
                    ai_failed.append({
                        "kind": "sentiment", "osm_id": restaurant.get("osm_id"),
                        "name": display_name(restaurant), "google_review_id": review_id,
                        "error": error, "tries": tries, "failed_at": failed_at,
                        "text": (review.get("text") or "")[:200],
                    })
                    stats["reviews_left_out"] += 1
                    continue
                kept.append(review)
            restaurant["reviews"] = kept
    except BaseException:
        print(f"\nStopped early: saving the AI answers so far to {CACHE_FILE} and {REVIEW_CACHE_FILE}.")
        print("Run the same command again; nothing already answered is asked again.")
        save_cache(cache)
        save_json(REVIEW_CACHE_FILE, review_cache)
        raise

    save_cache(cache)
    save_json(REVIEW_CACHE_FILE, review_cache)

    # Build output — preserve city / areas / nearby places / metadata; only
    # the restaurants with an answer, so run_5_validation.py checks them next
    output = {
        "city":          merged.get("city"),
        "areas":         merged.get("areas", []),
        "nearby_places": merged.get("nearby_places", []),
        "restaurants":   answered,
        "metadata": {
            **merged.get("metadata", {}),
            "profiled_at":           datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "restaurants_profiled":  len(answered),
            "ai_calls_made":         stats["called"],
            "ai_calls_cached":       stats["cached"],
            "ai_calls_retried":      stats["retried"],
            "ai_failed_left_out":    stats["failed"],
            "ai_not_asked_left_out": stats["skipped"],
            "conflict_fields_decided": stats["fields_decided"],
            "fields_left_empty_by_ai": stats["fields_left_empty"],
            "reviews_new_this_run":  stats["new_reviews"],
            "sentiment_calls_made":  stats["sentiment_calls"],
            "reviews_scored":        stats["reviews_scored"],
            "reviews_left_out":      stats["reviews_left_out"],
        },
    }

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    write_review_file(
        AI_FAILED_FILE,
        'Two kinds of items. kind "profile": a restaurant with no usable AI answer, left out of '
        "pj_final.json, so it is not validated or loaded yet (the item has the error, the tries "
        'and the restaurant\'s part of the prompt, facts). kind "sentiment": a review whose '
        "sentiment could not be worked out, left out of pj_final.json so no review is saved "
        "without one; its restaurant goes on. Run python run_4_profiling.py again: only these "
        "are asked (everything else comes from the caches), then run_5_validation.py, "
        "run_6_clustering.py and run_7_loading.py.",
        ai_failed,
    )

    print()
    print("=" * 60)
    print("PROFILING COMPLETE")
    print(f"  Total restaurants : {total}")
    print(f"  Profiled          : {len(answered)} -> {OUTPUT_FILE}")
    print(f"  AI calls made     : {stats['called']} ({stats['retried']} needed more than one try)")
    print(f"  From cache        : {stats['cached']}")
    print(f"  Disagreements     : {stats['fields_decided']} fields chosen by the AI")
    print(f"  AI failed         : {stats['failed']:>4} -> {AI_FAILED_FILE} (left out; run again)")
    if stats["skipped"]:
        print(f"  Not asked         : {stats['skipped']:>4} (--no-llm; left out, listed in {AI_FAILED_FILE})")
    print(f"  Left empty by AI  : {stats['fields_left_empty']:>4} fields (it trusted neither source; "
          "reason in merge_log)")
    print(f"  Reviews           : {stats['new_reviews']} new this run; {stats['reviews_scored']} scored in "
          f"{stats['sentiment_calls']} sentiment calls; {stats['reviews_left_out']} left out "
          f"(no sentiment yet, listed in {AI_FAILED_FILE})")
    print(f"  Caches            : {CACHE_FILE}, {REVIEW_CACHE_FILE} ({len(review_cache)} reviews)")
    print("=" * 60)


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[2])
    main()
