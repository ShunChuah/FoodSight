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
    # Tags that work against the request.
    conflicts: tuple[str, ...] = ()

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
    entries = [*settings["categories"].values(), *settings["preferences"].values(),
               *(entry["conflicts"] for entry in settings["preferences"].values() if "conflicts" in entry)]
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


# A mood request ranks a wider pool, so a well-fitting lower-rated place is still a candidate.
def candidate_pool(intent: "Intent | None" = None) -> int:
    settings = _policy()
    mood = intent is not None and bool(intent.ambiance or intent.segments or intent.facilities)
    return settings["mood_candidate_pool"] if mood else settings["candidate_pool"]


# The query model's intent; policy terms are only a fallback when a reply has none.
def recommendation_intent(question: str, named: dict | None = None, cypher: str = "") -> Intent:
    settings, named = _policy(), named if isinstance(named, dict) else {}
    from_model = bool(named)
    chosen = set() if from_model else {name for name, entry in settings["categories"].items()
                                       if _pattern(entry["terms"]).search(question)}
    entry = settings["categories"].get(named.get("category"))
    if entry and any(f"'{value}'" in cypher for value in [*entry["types"], *entry["venues"]]):
        chosen.add(named["category"])
    wished = set() if from_model else {name for name, entry in settings["preferences"].items()
                                       if _pattern(entry["terms"]).search(question)}
    wished |= {name for name in named.get("preferences") or [] if name in settings["preferences"]}

    types, venues, related, segments, facilities, conflicts = [], [], [], [], [], []
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
        conflicts += [*entry.get("conflicts", {}).get("ambiance", []), *entry.get("conflicts", {}).get("segments", [])]
        if entry.get("opens_by"):
            opens_by = min(filter(None, [opens_by, _minutes(entry["opens_by"])]))
    if from_model:
        ranking = named.get("ranking") if named.get("ranking") in RANKINGS else "relevance"
        budget = named.get("budget") is True
    else:
        ranking = next((kind for kind, terms in settings["ranking_terms"].items()
                        if _pattern(terms).search(question)), "relevance")
        budget = bool(_pattern(settings["budget_terms"]).search(question))
    return Intent(
        category=next((name for name in settings["categories"] if name in chosen), None),
        types=tuple(dict.fromkeys(types)), venues=tuple(dict.fromkeys(venues)),
        related=tuple(value for value in dict.fromkeys(related) if value not in types),
        ambiance=tuple(ambiance.items()), segments=tuple(dict.fromkeys(segments)),
        facilities=tuple(dict.fromkeys(facilities)), opens_by=opens_by,
        budget=budget, ranking=ranking,
        # A tag the request itself asks for never counts against it.
        conflicts=tuple(value for value in dict.fromkeys(conflicts)
                        if value not in dict(ambiance) and value not in segments))


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


TAG_SHARES = {
    "ambiance": "MATCH (r:Restaurant {counted_as_open: true})-[:HAS_PROFILE]->(bp:BusinessProfile) "
                "UNWIND coalesce(bp.ambiance, []) AS tag RETURN tag, count(DISTINCT r) AS places",
    "segments": "MATCH (r:Restaurant {counted_as_open: true})-[:HAS_PROFILE]->(bp:BusinessProfile) "
                "UNWIND coalesce(bp.target_segment, []) AS tag RETURN tag, count(DISTINCT r) AS places",
    "facilities": "MATCH (r:Restaurant {counted_as_open: true})-[:HAS_FACILITY]->(f:Facility) "
                  "RETURN f.name AS tag, count(DISTINCT r) AS places",
}
OPEN_PLACES = "MATCH (r:Restaurant {counted_as_open: true}) RETURN count(r) AS places"
_shares: dict[str, dict[str, float]] = {}


# Share of open places holding each tag, read once from the graph.
def _tag_shares() -> dict[str, dict[str, float]]:
    if not _shares:
        total = execute_cypher(OPEN_PLACES, {}, purpose="open places")
        places = total.records[0].get("places") if total.status == "success" and total.records else None
        if not places:
            return {}
        found = {}
        for group, query in TAG_SHARES.items():
            result = execute_cypher(query, {}, purpose=f"{group} shares")
            if result.status != "success":
                return {}
            found[group] = {row["tag"]: row["places"] / places for row in result.records if row.get("tag")}
        _shares.update(found)
    return _shares


# Rarer tags say more: one held by specific_share of places or fewer counts fully.
def specificity(group: str, tag: str) -> float:
    share = _tag_shares().get(group, {}).get(tag)
    if not share:
        return 1.0
    settings = _policy()
    rarity = _clip(math.log(1 / share) / math.log(1 / settings["specific_share"]))
    # A requested tag never counts below specificity_floor, however common.
    floor = settings["specificity_floor"]
    return floor + (1 - floor) * rarity


def _combined(strengths: list[float]) -> float:
    # Matched tags add up towards 1: 0.6 and 0.5 make 0.8.
    return 1 - math.prod(1 - _clip(value) for value in strengths)


# Score (0-100), request fit (0-1) and reasons; a missing attribute scores 0.
def _score(row: dict[str, Any], intent: Intent, kind: str) -> tuple[float, float | None, list[str]]:
    settings = _policy()
    weights = settings["weights"]
    # A name-guessed profile counts for nothing; Google facilities always count fully.
    profiled = not row.get("profile_is_a_guess")
    trust = settings["evidence"].get(row.get("evidence_level") or "high", 1.0) if profiled else 0.0
    parts: list[tuple[float, float]] = []
    fit_parts: list[tuple[float, float]] = []
    reasons: list[str] = []
    if intent.types:
        parts.append((weights["category"], {"exact": 1.0, "related": 0.5}.get(kind, 0.0)))
        if kind == "exact" and row.get("restaurant_type"):
            reasons.append(f"a {_words(row['restaurant_type'])}")
    tags = {"ambiance": _list(row.get("ambiance")), "segments": _list(row.get("good_for"))}
    against = _combined([specificity(group, value) * trust for group in tags for value in tags[group]
                         if value in intent.conflicts])
    keep = 1 - settings["conflict_penalty"] * against
    if intent.ambiance:
        wanted = dict(intent.ambiance)
        found = [value for value in tags["ambiance"] if value in wanted] if profiled else []
        value = _combined([wanted[tag] * specificity("ambiance", tag) * trust for tag in found]) * keep
        parts.append((weights["ambiance"], value))
        fit_parts.append((weights["ambiance"], value))
        if found:
            reasons.append(f"{' and '.join(_words(value) for value in found)} atmosphere (AI-inferred profile)")
    if intent.segments or intent.facilities or intent.opens_by:
        segments = [value for value in tags["segments"] if value in intent.segments] if profiled else []
        # Facility names keep their spaces ("Kids Menu"); only profile tags use underscores.
        listed = row.get("facilities") if isinstance(row.get("facilities"), list) else []
        facilities = [value for value in listed if value in intent.facilities]
        opens = opens_at(row.get("hours_today"))
        if intent.opens_by:
            # A meal tag on a place that opens too late for it counts for little.
            early = opens is not None and opens <= intent.opens_by
            suits = 1.0 if early and facilities else 0.8 if early else 0.3 if facilities else 0.0
            if early:
                reasons.append("open all day today" if opens == 0
                               else f"opens at {time_label(opens // 60, opens % 60)} today")
        else:
            suits = _combined([*(specificity("segments", tag) * trust for tag in segments),
                               *(specificity("facilities", tag) for tag in facilities)]) * keep
        parts.append((weights["suitability"], suits))
        fit_parts.append((weights["suitability"], suits))
        if facilities:
            reasons.append("Google lists " + " and ".join(facilities))
        if segments:
            reasons.append(f"suits {' and '.join(_words(value) for value in segments)} (AI-inferred profile)")
    distance = row.get("distance_m")
    if isinstance(distance, (int, float)) and not isinstance(distance, bool):
        radius = policy("proximity")["default_radius_meters"]
        parts.append((weights["distance"], _clip(1 - distance / radius)))
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
    score = 100 * sum(weight * value for weight, value in parts) / total if total else 0.0
    fit_total = sum(weight for weight, _ in fit_parts)
    fit = sum(weight * value for weight, value in fit_parts) / fit_total if fit_total else None
    return score, fit, reasons


PRICE_BANDS = ("budget", "mid", "upscale", "luxury")


# 0 budget, 1 mid, 2 upscale, 3 luxury; unpriced places come last.
def price_band(row: dict[str, Any]) -> int:
    if row.get("price_tier") in PRICE_BANDS:
        return PRICE_BANDS.index(row["price_tier"])
    price = row.get("average_price")
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        return 0 if price < 20 else 1 if price < 60 else 2 if price < 150 else 3
    return len(PRICE_BANDS)


# Fit groups come first, so a popular weak match never outranks a strong one.
def fit_tier(fit: float | None) -> int:
    if fit is None:
        return 0
    tiers = _policy()["fit_tiers"]
    return 2 if fit >= tiers["strong"] else 1 if fit >= tiers["some"] else 0


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
        score, fit, reasons = _score(row, intent, kind)
        alternative = None
        if kind != "exact":
            found = _words(row["restaurant_type"]) if row.get("restaurant_type") else "a different kind of place"
            alternative = f"{found}, not a {_words(intent.category or 'match')}"
        # Cheapest band first (for a budget request), then fit group, then score or the explicit ranking.
        band = price_band(row) if intent.budget else 0
        order = (band, -fit_tier(fit), _explicit_key(row, intent.ranking) if intent.explicit else -score)
        # fit_tier stays so "open now first" never crosses fit groups.
        scored.append((kind, order, index, {**row, "why_it_matches": reasons, "alternative": alternative,
                                            "fit_tier": fit_tier(fit)}))
    scored.sort(key=lambda item: item[1:3])
    exact = _one_per_brand([row for kind, _, _, row in scored if kind == "exact"])
    related = _one_per_brand([row for kind, _, _, row in scored if kind == "related"])
    other = _one_per_brand([row for kind, _, _, row in scored if kind == "other"])
    if not exact:
        return related + other
    return exact + related[:_policy()["max_alternatives"]]
