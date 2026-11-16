# Where a question is about: the user's position, a named place, a place outside PJ or anywhere.

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from ..shared.config import policy
from ..shared.text import contains_phrase, normalize_query_text
from .coverage import OutsidePlace, outside_place
from .cypher_generation import load_vocabulary
from .proximity import explicit_radius_meters, extract_explicit_location

LocationKind = Literal["near_user", "named", "outside", "anywhere"]
POSITION_MODES = ("radius_search", "nearest_search", "walking_proxy", "distance_measurement")
USER_POSITION_TERMS = {"near me", "around me", "close to me", "current location", "around here"}
DISTANCE = (r"(?:\d+(?:\.\d+)?\s*(?:km|kilomet(?:er|re)s?|m|met(?:er|re)s?)|(?:walking|driving)\s+distance|"
            r"(?:a\s+)?(?:short\s+)?(?:\d+|five|ten|fifteen)[- ]?min(?:ute)?s?\s+(?:walk|drive))")
# "within 2km of X", "1km from X" and "closest mamak to X" all mean "near X".
NEAR_PHRASES = (
    (re.compile(rf"\b(?:within\s+)?{DISTANCE}\s+(?:of|from|away\s+from)\s+", re.IGNORECASE), "near "),
    (re.compile(r"\b((?:closest|nearest)\s+(?:[\w'-]+\s+){0,3}?)to\s+", re.IGNORECASE), r"\1near "),
)


@dataclass(frozen=True)
class Location:
    kind: LocationKind = "anywhere"
    name: str | None = None
    outside: OutsidePlace | None = None
    text: str = ""


def resolve_location(question: str) -> Location:
    text = question
    for pattern, replacement in NEAR_PHRASES:
        text = pattern.sub(replacement, text)
    outside = outside_place(text)
    if outside:
        return Location("outside", outside.name, outside, text)

    normalized = normalize_query_text(text)
    modes = policy("proximity")["modes"]
    terms = {term for mode in POSITION_MODES for term in modes.get(mode, {}).get("terms", [])}
    near_user = contains_phrase(normalized, USER_POSITION_TERMS)
    named = extract_explicit_location(text)
    if named and contains_phrase(normalize_query_text(named), terms | USER_POSITION_TERMS):
        named = None
    if named and not near_user:
        return Location("named", named, text=text)
    if near_user or (contains_phrase(normalized, terms) and not _about_nearby_places(normalized)) \
            or explicit_radius_meters(normalized) is not None:
        return Location("near_user", named, text=text)
    return Location(text=text)


# "offices nearby" or "near a university" is about NearbyPlace kinds (categories.json), not the user's position.
@lru_cache(maxsize=1)
def _nearby_kinds() -> re.Pattern:
    kinds = "|".join(re.escape(kind) for kind in load_vocabulary()["columns"]["nearby_place.kind"]["values"])
    return re.compile(rf"\b(?:{kinds})(?:e?s)?\s+(?:nearby|around|close by)\b"
                      rf"|\b(?:near|around|close to)\s+(?:a|an|the|any)?\s*(?:\w+\s+)?(?:{kinds})", re.IGNORECASE)


def _about_nearby_places(normalized: str) -> bool:
    return bool(_nearby_kinds().search(normalized.replace("universities", "university")))
