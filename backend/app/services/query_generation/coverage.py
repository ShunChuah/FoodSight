# City coverage: questions about places outside Petaling Jaya get a reply before any LLM call.

import re
from dataclasses import dataclass
from functools import lru_cache

from ..shared.config import policy
from ..shared.messages import response
from .scope import about_food

MAX_SUGGESTIONS = 3
MAX_SUGGESTION_LENGTH = 80
LOCATION_WORDS = r"(?:in|at|near|around|nearby|close to)"
PLACE_WORDS = r"(?:\s+(?:area|city|centre|center|town|side))*"
TRAILING_WORDS = r"(?:\s+(?:today|tonight|tomorrow|now|please|lah|instead|too|also|then|right\s+now))*"
PLACE_END = (r"(?=\s*(?:[?!.,;]|$)|\s+(?:for|with|under|below|above|that|serving|open|by|ranked|sorted|ordered|"
             r"compared|versus|vs|than|and|or|but|which|who|to|on|this|next|near|within)\b)")


@dataclass(frozen=True)
class OutsidePlace:
    name: str
    nearby_areas: tuple[str, ...]
    span: tuple[int, int] | None = None


@dataclass(frozen=True)
class CoverageReply:
    message: str
    suggestions: tuple[str, ...]


def _key(name: str) -> str:
    return re.sub(r"\s+", "", name).casefold()


@lru_cache(maxsize=1)
def _places() -> dict[str, tuple[str, tuple[str, ...]]]:
    return {_key(name): (name, tuple(region.get("nearby_areas", [])))
            for region in policy("coverage")["outside_places"] for name in region["places"]}


@lru_cache(maxsize=2)
def _place_pattern(anywhere: bool) -> re.Pattern:
    names = "|".join(r"\s*".join(re.escape(word) for word in name.split())
                     for name, _ in sorted(_places().values(), key=lambda item: len(item[0]), reverse=True))
    if anywhere:
        return re.compile(rf"(?<!\w)(?P<place>{names})(?P<words>{PLACE_WORDS})(?!\w)", re.IGNORECASE)
    return re.compile(rf"(?<!\w){LOCATION_WORDS}\s+(?:the\s+)?(?P<place>{names})(?P<words>{PLACE_WORDS})"
                      rf"{TRAILING_WORDS}{PLACE_END}", re.IGNORECASE)


def outside_place(text: str, *, anywhere: bool = False) -> OutsidePlace | None:
    match = _place_pattern(anywhere).search(text or "")
    if not match:
        return None
    name, nearby = _places()[_key(match.group("place"))]
    return OutsidePlace(name, nearby, (match.start("place"), match.end("words")))


def named_outside_place(name: str) -> OutsidePlace | None:
    found = _places().get(_key(re.sub(r"^the\s+", "", name.strip(), flags=re.IGNORECASE)))
    return OutsidePlace(*found) if found else None


def outside_coverage(question: str, conversation_context: str = "", *, anywhere: bool = False) -> CoverageReply | None:
    place = outside_place(question) or (outside_place(question, anywhere=True) if anywhere else None)
    return coverage_reply(question, place, conversation_context) if place else None


def coverage_reply(question: str, place: OutsidePlace, conversation_context: str = "") -> CoverageReply:
    settings = policy("coverage")
    areas = (place.nearby_areas or tuple(settings["popular_areas"]))[:MAX_SUGGESTIONS]
    message = response("coverage.outside_nearby" if place.nearby_areas else "coverage.outside_far",
                       city=settings["city"], place=place.name, areas=_join(areas))
    user_turns = " ".join(re.findall(r"^User:\s*(.+)$", conversation_context or "", flags=re.MULTILINE))
    food = about_food(question) or about_food(user_turns)
    return CoverageReply(message, tuple(dict.fromkeys(_suggestion(question, place, area, food) for area in areas)))


def _suggestion(question: str, place: OutsidePlace, area: str, food: bool) -> str:
    if food and place.span:
        start, end = place.span
        rewritten = " ".join(f"{question[:start]}{area}{question[end:]}".split())
        if len(rewritten) <= MAX_SUGGESTION_LENGTH:
            return rewritten[:1].upper() + rewritten[1:]
    return f"Places to eat in {area}"


def _join(names: tuple[str, ...]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
