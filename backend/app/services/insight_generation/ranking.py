# Ranks discovery results by what the question is after (policy "recommendation" in query_assumptions.json).

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from ..query_generation.cypher_generation import load_vocabulary
from ..shared.config import policy
from ..shared.neo4j import execute_cypher
from .presentation import money_label, time_label

FULL_RATING, LOW_RATING = 5.0, 3.5
MANY_REVIEWS = 2000
BUDGET_PRICE, DEAR_PRICE = 10, 40
RANKINGS = ("relevance", "popularity", "rating", "price", "distance")
NO_CATEGORY = "none"
FALLBACK_PRIOR = 4.2
PJ_RATING = "MATCH (:Restaurant {counted_as_open: true})-[:HAS_RATING]->(rt:Rating) RETURN avg(rt.rating_score) AS mean"


@dataclass(frozen=True)
class Intent:
    category: str | None = None
    types: tuple[str, ...] = ()
    venues: tuple[str, ...] = ()
    related: tuple[str, ...] = ()
    ambiance: tuple[tuple[str, float], ...] = ()
    segments: tuple[str, ...] = ()
    facilities: tuple[str, ...] = ()
    opens_by: int | None = None
    budget: bool = False
    ranking: str = "relevance"

    @property
    def explicit(self) -> bool:
        return self.ranking != "relevance"

    @property
    def active(self) -> bool:
        return bool(self.types or self.ambiance or self.segments or self.facilities or self.opens_by
                    or self.budget or self.explicit)


def _pattern(terms: list[str]) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(re.escape(term) for term in terms) + r")\b", re.IGNORECASE)


# Checked against categories.json once, so a renamed value fails at start-up instead of never matching.
@lru_cache(maxsize=1)
def _policy() -> dict:
    settings = policy("recommendation")
    columns = load_vocabulary()["columns"]
    known = {name: set(columns[column]["values"]) for name, column in (
        ("types", "business_profile.restaurant_type"), ("venues", "restaurant.amenity_type"),
        ("ambiance", "business_profile.ambiance"), ("segments", "business_profile.target_segment"),
        ("facilities", "facility.name"))}
    entries = [*settings["categories"].values(), *settings["preferences"].values()]
    for entry in entries:
        for key, values in entry.items():
            unknown = set(values) - known[key] if key in known else set()
            if key == "related":
                unknown = set(values) - known["types"]
            if unknown:
                raise ValueError(f"recommendation policy names unknown {key} values: {sorted(unknown)}")
    if set(settings.get("ranking_terms", {})) - set(RANKINGS):
        raise ValueError("recommendation ranking_terms may only name " + ", ".join(RANKINGS[1:]))
    return settings


def categories() -> list[str]:
    return list(_policy()["categories"])


def preferences() -> dict[str, list[str]]:
    return {name: entry["terms"] for name, entry in _policy()["preferences"].items()}


def candidate_pool() -> int:
    return _policy()["candidate_pool"]


# The query model's intent plus what the policy terms find in the question, so either one can catch a miss.
# Its category counts only when its own Cypher filters on that kind of place, so a guess cannot demote the rest.
# The ranking comes from the words alone: "most popular" is literal, and the model over-reads "best" as rating.
def recommendation_intent(question: str, named: dict | None = None, cypher: str = "") -> Intent:
    settings, named = _policy(), named if isinstance(named, dict) else {}
    chosen = {name for name, entry in settings["categories"].items() if _pattern(entry["terms"]).search(question)}
    entry = settings["categories"].get(named.get("category"))
    if entry and any(f"'{value}'" in cypher for value in [*entry["types"], *entry["venues"]]):
        chosen.add(named["category"])
    wished = {name for name, entry in settings["preferences"].items() if _pattern(entry["terms"]).search(question)}
    wished |= {name for name in named.get("preferences") or [] if name in settings["preferences"]}

    types, venues, related, segments, facilities = [], [], [], [], []
    ambiance: dict[str, float] = {}
    opens_by = None
    for name in [name for name in settings["categories"] if name in chosen]:
        entry = settings["categories"][name]
        types += entry["types"]
        venues += entry["venues"]
        related += entry["related"]
    for name in [name for name in settings["preferences"] if name in wished]:
        entry = settings["preferences"][name]
        for value, weight in entry["ambiance"].items():
            ambiance[value] = max(weight, ambiance.get(value, 0))
        segments += entry["segments"]
        facilities += entry["facilities"]
        if entry.get("opens_by"):
            opens_by = min(filter(None, [opens_by, _minutes(entry["opens_by"])]))
    ranking = next((kind for kind, terms in settings["ranking_terms"].items() if _pattern(terms).search(question)),
                   "relevance")
    return Intent(
        category=next((name for name in settings["categories"] if name in chosen), None),
        types=tuple(dict.fromkeys(types)), venues=tuple(dict.fromkeys(venues)),
        related=tuple(value for value in dict.fromkeys(related) if value not in types),
        ambiance=tuple(ambiance.items()), segments=tuple(dict.fromkeys(segments)),
        facilities=tuple(dict.fromkeys(facilities)), opens_by=opens_by,
        budget=named.get("budget") is True or bool(_pattern(settings["budget_terms"]).search(question)),
        ranking=ranking)


REQUIRED = re.compile(r"\b(?:only|must|need|needs|has to|have to)\b", re.IGNORECASE)


# Mood and customer filters the query model wrote anyway become true, so the ranking, not the filter, decides.
def without_soft_filters(cypher: str, intent: Intent, question: str) -> str:
    values = [*dict(intent.ambiance), *intent.segments]
    if not values or REQUIRED.search(question):
        return cypher
    choice = "|".join(re.escape(value) for value in values)
    cypher = re.sub(rf"'(?:{choice})'\s+IN\s+(?:coalesce\(\s*)?\w+\.(?:ambiance|target_segment)(?:\s*,\s*\[\s*\]\s*\))?",
                    "true", cypher)
    return re.sub(r"\w+\.(?:ambiance|target_segment)\s+IS\s+NOT\s+NULL", "true", cypher)


def _minutes(clock: str) -> int:
    hour, minute = clock.split(":")
    return int(hour) * 60 + int(minute)


# First opening time in today's hours ("07:00-15:00, 18:00-22:00" opens at 7:00); 0 when open all day.
def opens_at(hours: Any) -> int | None:
    if hours == "open 24 hours":
        return 0
    found = re.search(r"(\d{1,2}):(\d{2})\s*[-–]", hours) if isinstance(hours, str) else None
    return int(found[1]) * 60 + int(found[2]) if found else None


def _clip(value: float) -> float:
    return max(0.0, min(1.0, value))


def _words(value: str) -> str:
    return value.replace("_", " ")


def _list(value: Any) -> list:
    items = value if isinstance(value, list) else value.split(",") if isinstance(value, str) else []
    return [str(item).strip().replace(" ", "_") for item in items if str(item).strip()]


_prior: list[float] = []


# PJ's average rating, read once; a failed read falls back without being kept.
def _prior_rating() -> float:
    if not _prior:
        result = execute_cypher(PJ_RATING, {}, purpose="PJ average rating")
        mean = result.records[0].get("mean") if result.status == "success" and result.records else None
        if not isinstance(mean, (int, float)):
            return FALLBACK_PRIOR
        _prior.append(float(mean))
    return _prior[0]


# Bayesian average: few reviews pull the rating towards PJ's average, so 5.0 from 2 reviews is not "the best".
def bayesian_rating(row: dict[str, Any]) -> float | None:
    rating, reviews = row.get("average_rating"), row.get("review_count")
    if not isinstance(rating, (int, float)):
        return None
    reviews = reviews if isinstance(reviews, int) else 0
    prior = _policy()["prior_reviews"]
    return (reviews * rating + prior * _prior_rating()) / (reviews + prior)


def _kind(row: dict[str, Any], intent: Intent) -> str:
    kind = row.get("restaurant_type")
    if kind in intent.types or (kind is None and row.get("venue_type") in intent.venues):
        return "exact"
    return "related" if kind in intent.related else "other"


# Score from 0 to 100 plus the facts behind it. A missing attribute scores 0, never an average.
def _score(row: dict[str, Any], intent: Intent, kind: str) -> tuple[float, list[str]]:
    weights = _policy()["weights"]
    # A profile guessed from the name alone is not evidence of atmosphere or customers.
    profiled = not row.get("profile_is_a_guess")
    parts: list[tuple[float, float]] = []
    reasons: list[str] = []
    if intent.types:
        parts.append((weights["category"], {"exact": 1.0, "related": 0.5}.get(kind, 0.0)))
        if kind == "exact" and row.get("restaurant_type"):
            reasons.append(f"a {_words(row['restaurant_type'])}")
    if intent.ambiance:
        wanted = dict(intent.ambiance)
        found = [value for value in _list(row.get("ambiance")) if value in wanted] if profiled else []
        parts.append((weights["ambiance"], max((wanted[value] for value in found), default=0.0)))
        if found:
            reasons.append(f"{' and '.join(_words(value) for value in found)} atmosphere (AI-inferred profile)")
    if intent.segments or intent.facilities or intent.opens_by:
        segments = [value for value in _list(row.get("good_for")) if value in intent.segments] if profiled else []
        facilities = [value for value in _list(row.get("facilities")) if value in intent.facilities]
        opens = opens_at(row.get("hours_today"))
        if intent.opens_by:
            # A meal tag on a place that opens too late for it counts for little.
            early = opens is not None and opens <= intent.opens_by
            suits = 1.0 if early and facilities else 0.8 if early else 0.3 if facilities else 0.0
            if early:
                reasons.append("open all day today" if opens == 0
                               else f"opens at {time_label(opens // 60, opens % 60)} today")
        else:
            suits = 1.0 if facilities else 0.7 if segments else 0.0
        parts.append((weights["suitability"], suits))
        if facilities:
            reasons.append("Google lists " + " and ".join(facilities))
        if segments:
            reasons.append(f"suits {' and '.join(_words(value) for value in segments)} (AI-inferred profile)")
    rated = bayesian_rating(row)
    reviews = row.get("review_count") if isinstance(row.get("review_count"), int) else 0
    parts.append((weights["rating"], _clip((rated - LOW_RATING) / (FULL_RATING - LOW_RATING)) if rated else 0.0))
    parts.append((weights["reviews"], _clip(math.log10(1 + reviews) / math.log10(1 + MANY_REVIEWS))))
    if intent.budget:
        price = row.get("average_price")
        cheap = _clip((DEAR_PRICE - price) / (DEAR_PRICE - BUDGET_PRICE)) if isinstance(price, (int, float)) else 0.0
        parts.append((weights["price"], cheap))
        if isinstance(price, (int, float)) and cheap > 0:
            reasons.append(f"around {money_label(price, 'MYR')} per person (estimated)")
    total = sum(weight for weight, _ in parts)
    return (100 * sum(weight * value for weight, value in parts) / total if total else 0.0), reasons


# The order for an explicit ranking; distance keeps the query's own order (it holds the distances).
def _explicit_key(row: dict[str, Any], ranking: str) -> float:
    if ranking == "popularity":
        return -(row.get("review_count") or 0)
    if ranking == "rating":
        rated = bayesian_rating(row)
        return -rated if rated is not None else math.inf
    if ranking == "price":
        price = row.get("average_price")
        return price if isinstance(price, (int, float)) else math.inf
    return 0.0


# One branch per brand: chains otherwise fill the list with the same place.
def _one_per_brand(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, kept = set(), []
    for row in rows:
        brand = str(row.get("brand") or str(row.get("restaurant_name") or "").split(" - ")[0]).strip().casefold()
        if brand and brand in seen:
            continue
        seen.add(brand)
        kept.append(row)
    return kept


# Best matches first, then up to max_alternatives related places, each labelled; unrelated kinds are dropped
# unless nothing else is left. An explicit ranking (most popular, cheapest) orders by its metric instead of the score.
def rank_for_intent(rows: list[dict[str, Any]], intent: Intent) -> list[dict[str, Any]]:
    scored = []
    for index, row in enumerate(rows):
        kind = _kind(row, intent) if intent.types else "exact"
        score, reasons = _score(row, intent, kind)
        alternative = None
        if kind != "exact":
            found = _words(row["restaurant_type"]) if row.get("restaurant_type") else "a different kind of place"
            alternative = f"{found}, not a {_words(intent.category or 'match')}"
        order = _explicit_key(row, intent.ranking) if intent.explicit else -score
        scored.append((kind, order, index, {**row, "why_it_matches": reasons, "alternative": alternative}))
    scored.sort(key=lambda item: item[1:3])
    exact = _one_per_brand([row for kind, _, _, row in scored if kind == "exact"])
    related = _one_per_brand([row for kind, _, _, row in scored if kind == "related"])
    other = _one_per_brand([row for kind, _, _, row in scored if kind == "other"])
    if not exact:
        return related + other
    return exact + related[:_policy()["max_alternatives"]]
