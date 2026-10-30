import math
import re

from ..shared.config import policy
from ..shared.text import contains_phrase, normalize_query_text

USER_REFERENCE = re.compile(r"^(?:the\s+)?(?:me|here|my|your|user(?:['’]s)?|current|device|browser|gps)(?:\b|_)", re.I)


def is_user_reference(text: object) -> bool:
    cleaned = str(text or "").strip().strip("()[]\"“”‘’'.,;: ").strip()
    return bool(cleaned) and bool(USER_REFERENCE.match(cleaned))


GENERIC_PLACES = re.compile(
    r"^(?:the\s+|a\s+|any\s+)?(?:universit(?:y|ies)|colleges?|campus(?:es)?|schools?|offices?|office buildings?|malls?|"
    r"shopping (?:malls?|centres?|centers?)|stations?|lrt|mrt|hospitals?|residential areas?|housing areas?|tourist spots?)\b",
    re.I)


DISTANCE_PATTERN = r"(?<![\w.])(-?\d+(?:\.\d+)?)\s*(km|kilomet(?:er|re)s?|m|met(?:er|re)s?)\b"


def coordinates_from_context(context: str) -> dict[str, float] | None:
    match = re.fullmatch(
        r"User browser coordinates:\s*latitude\s+(-?\d+(?:\.\d+)?),\s*longitude\s+(-?\d+(?:\.\d+)?)\.?",
        context.strip(), re.I,
    )
    if not match:
        return None
    latitude, longitude = map(float, match.groups())
    if not (math.isfinite(latitude) and math.isfinite(longitude) and abs(latitude) <= 90 and abs(longitude) <= 180):
        return None
    return {"latitude": latitude, "longitude": longitude}


def explicit_radius_meters(query: str) -> int | None:
    numeric = re.search(DISTANCE_PATTERN, query, re.I)
    if numeric:
        return int(float(numeric[1]) * (1000 if numeric[2].lower().startswith("k") else 1))
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
             "eight": 8, "nine": 9, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
             "one hundred": 100, "hundred": 100}
    spelled = re.search(r"\b(" + "|".join(sorted(words, key=len, reverse=True)) + r")\s+(km|kilomet(?:er|re)s?|m|met(?:er|re)s?)\b", query, re.I)
    return words[spelled[1].lower()] * (1000 if spelled[2].lower().startswith("k") else 1) if spelled else None


def mode_for(query: str) -> str | None:
    text = query.lower()
    modes = policy("proximity")["modes"]
    for mode in ("distance_measurement", "nearest_search", "walking_proxy", "delivery_search", "radius_search"):
        if any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) for term in modes[mode]["terms"]):
            return mode
    if explicit_radius_meters(text) is not None or re.search(r"\b(?:near|around|close to)\s+\S", text):
        return "radius_search"
    return None


def default_radius(query: str) -> int | None:
    settings = policy("proximity")
    mode = mode_for(query)
    if mode == "distance_measurement":
        return None
    explicit = explicit_radius_meters(query)
    if explicit is not None:
        return explicit
    if mode == "nearest_search":
        return settings["maximum_radius_meters"]
    if mode == "walking_proxy":
        return settings["walking_radius_meters"]
    if mode == "delivery_search":
        return settings["delivery_radius_meters"]
    for venue, radius in settings["venue_radius_meters"].items():
        if re.search(rf"\b{re.escape(venue)}s?\b", query, re.I):
            return radius
    return settings["default_radius_meters"]


def extract_explicit_location(user_query: str) -> str | None:
    match = re.search(
        (
            r"\b(?:near|in|at|around|within|close to)\s+"
            r"([a-z0-9][a-z0-9 .,'-]{1,80}?)"
            r"(?=\s+(?:for|with|under|below|above|that|serving|open|"
            r"by|ranked|sorted|ordered|compared|versus|vs|than|and|or|but|which|who|"
            r"target|targets|serve|serves|offer|offers|have|has|are|is|do|does)\b|[?!.,]|$)"
        ),
        user_query,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    location = " ".join(match.group(1).strip().split())
    if GENERIC_PLACES.match(location):
        return None
    if explicit_radius_meters(location) is not None and re.match(
        r"^(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred)\b", location, re.I,
    ):
        return None
    return (
        None
        if is_user_reference(location) or re.match(r"^\d+(?:\.\d+)?\s*(?:km|m|kilometres?|kilometers?|metres?|meters?)\b", location, flags=re.IGNORECASE)
        else location
    )


POSITION_MODES = ("radius_search", "nearest_search", "walking_proxy", "distance_measurement")
USER_POSITION_TERMS = {"near me", "around me", "close to me", "current location", "around here"}


def location_requirement(user_query: str) -> tuple[bool, str | None]:
    normalized = normalize_query_text(user_query)
    modes = policy("proximity")["modes"]
    terms = {term for mode in POSITION_MODES for term in modes.get(mode, {}).get("terms", [])}
    proximity = contains_phrase(normalized, terms) or explicit_radius_meters(normalized) is not None
    named_place = extract_explicit_location(user_query)
    if named_place and contains_phrase(normalize_query_text(named_place), terms | USER_POSITION_TERMS):
        named_place = None
    if named_place and not contains_phrase(normalized, USER_POSITION_TERMS):
        return False, named_place
    return proximity, named_place
