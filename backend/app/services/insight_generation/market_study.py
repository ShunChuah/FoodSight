# Where to open an F&B outlet (policy "market_study" in query_assumptions.json). One aggregate query gives every
# area's market and the concept's direct competitors there; the app computes each figure and ranks the areas, and
# the answer model only explains them.

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Any

from ..query_generation.cypher_generation import load_vocabulary
from ..shared.config import policy
from ..shared.neo4j import execute_cypher

# All of PJ in one pass: each area's restaurants, reviews and prices, and the direct competitors among them.
AREA_MARKET = """
MATCH (r:Restaurant {counted_as_open: true})-[:LOCATED_IN]->(l:Location)-[:IN_AREA]->(a:Area)
OPTIONAL MATCH (r)-[:HAS_RATING]->(rt:Rating)
OPTIONAL MATCH (r)-[:PRICED_AT]->(p:PriceRange)
OPTIONAL MATCH (r)-[:HAS_PROFILE]->(bp:BusinessProfile)
WITH a, r, l, rt, p, bp, r.restaurant_id IN $competitor_ids AS rival
RETURN a.name AS area_name,
       count(DISTINCT r) AS restaurants,
       sum(coalesce(rt.total_reviews, 0)) AS reviews,
       count(rt.rating_score) AS rated,
       avg(p.avg_meal_price) AS area_price,
       count(p.avg_meal_price) AS priced,
       collect(p.tier) AS tiers,
       collect(bp.restaurant_type) AS kinds,
       collect(bp.target_segment) AS segments,
       collect(CASE WHEN rival THEN {restaurant_id: r.restaurant_id, restaurant_name: r.name,
                                     average_rating: rt.rating_score, review_count: rt.total_reviews,
                                     average_price: p.avg_meal_price, price_tier: p.tier,
                                     latitude: l.latitude, longitude: l.longitude, kind: bp.restaurant_type,
                                     sentiments: COLLECT { MATCH (r)-[:HAS_REVIEW]->(v:Review) RETURN v.sentiment }}
               END) AS rivals
""".strip()
NEARBY = """
UNWIND $areas AS area_name
MATCH (r:Restaurant {counted_as_open: true})-[:LOCATED_IN]->(:Location)-[:IN_AREA]->(:Area {name: area_name})
MATCH (r)-[:NEAR]->(np:NearbyPlace)
WITH area_name, np.kind AS kind, count(DISTINCT np) AS places
RETURN area_name, collect([kind, places]) AS nearby
""".strip()

DIMENSIONS = ("market", "competition", "generators", "price", "differentiation", "confidence", "competitor_strength")
OBJECTIVES = ("balanced", "exposure", "low_competition", "strongest_market")
PRICE_POSITIONS = ("none", "budget", "mid", "premium")
RESTAURANT = re.compile(r"\brestaurants?\b", re.IGNORECASE)
CUSTOMERS = re.compile(r"\b(?:students?|universit\w*|offices?|office workers|famil\w*|kids|tourists?|travellers?|"
                       r"shoppers?|mall|commuters?|patients|hospital)\b", re.IGNORECASE)
TARGET_PRICE = re.compile(r"\bRM\s?(\d+(?:\.\d+)?)", re.IGNORECASE)
# Competitor ratings run from about 3.5 to 4.8 in PJ: lower leaves more room to stand out.
TOP_RATING, LOW_RATING = 4.8, 3.5


# Checked once against categories.json, so a renamed nearby kind fails at start-up.
@lru_cache(maxsize=1)
def settings() -> dict:
    values = policy("market_study")
    kinds = set(load_vocabulary()["columns"]["nearby_place.kind"]["values"])
    named = set(values["weights"]) | {key for weights in values["objectives"].values() for key in weights}
    if named - set(DIMENSIONS):
        raise ValueError(f"market_study names unknown dimensions: {sorted(named - set(DIMENSIONS))}")
    if set(values["objectives"]) - set(OBJECTIVES):
        raise ValueError("market_study objectives may only be " + ", ".join(OBJECTIVES[1:]))
    unknown = (set(values["nearby"]) | {kind for group in values["preference_nearby"].values() for kind in group}) - kinds
    if unknown:
        raise ValueError(f"market_study names unknown nearby kinds: {sorted(unknown)}")
    return values


def objectives() -> list[str]:
    return list(OBJECTIVES)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _scaled(values: list[float | None]) -> list[float | None]:
    known = [value for value in values if value is not None]
    if not known:
        return [None] * len(values)
    low, high = min(known), max(known)
    return [None if value is None else 0.5 if high == low else (value - low) / (high - low) for value in values]


def _log(value: float | None) -> float | None:
    return math.log1p(value) if value is not None else None


def _common(values: list[Any], limit: int) -> list[str]:
    counts = Counter(value for value in values if isinstance(value, str) and value)
    return [value for value, _ in counts.most_common(limit)]


def _tier_price(rivals: list[dict[str, Any]], tiers: tuple[str, ...]) -> float | None:
    prices = [place["average_price"] for place in rivals
              if place.get("price_tier") in tiers and _number(place.get("average_price")) is not None]
    return round(_mean(prices), 1) if prices else None


def _rival(place: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in place.items() if key not in ("sentiments", "kind")}


# One area's figures, each from the population it describes: area-wide figures from all its restaurants,
# competitor figures only from its direct competitors.
def _area(row: dict[str, Any], nearby: dict[str, int] | None) -> dict[str, Any]:
    rivals = [place for place in row.get("rivals") or [] if place]
    restaurants = row.get("restaurants") or 0
    rated = [place for place in rivals if _number(place.get("average_rating")) is not None]
    prices = [place["average_price"] for place in rivals if _number(place.get("average_price")) is not None]
    reviewed = [place for place in rivals if isinstance(place.get("review_count"), int)]
    competitor_reviews = sum(place["review_count"] for place in reviewed)
    sentiments = Counter(value for place in rivals for value in place.get("sentiments") or [] if value)
    sampled = sum(sentiments.values())
    minimum = settings()["rated_minimum_reviews"]
    established = [place for place in rated if (place.get("review_count") or 0) >= minimum]
    segments = [value for values in row.get("segments") or [] for value in values or []]
    area_price = _number(row.get("area_price"))
    return {
        "area_name": row["area_name"],
        "restaurants": restaurants,
        "reviews": row.get("reviews") or 0,
        "reviews_per_restaurant": round((row.get("reviews") or 0) / restaurants) if restaurants else None,
        "rated_share": (row.get("rated") or 0) / restaurants if restaurants else 0.0,
        "priced_share": (row.get("priced") or 0) / restaurants if restaurants else 0.0,
        "area_price": round(area_price, 1) if area_price is not None else None,
        "area_tier": next(iter(_common(row.get("tiers") or [], 1)), None),
        "restaurant_mix": _common(row.get("kinds") or [], 3),
        "customers": [value.replace("_", " ") for value in _common(segments, 3)],
        "competitors": len(rivals),
        "competitor_share": round(100 * len(rivals) / restaurants, 1) if restaurants else None,
        # Only competitors with a review count: one without Google data is unknown, not zero reviews.
        "competitor_reviews": competitor_reviews if reviewed else None,
        "competitor_reviews_avg": round(competitor_reviews / len(reviewed)) if reviewed else None,
        "competitor_rating": round(_mean([place["average_rating"] for place in rated]), 1) if rated else None,
        "rated_competitors": len(rated),
        "competitor_price": round(_mean(prices), 1) if prices else None,
        "competitor_price_low": min(prices) if prices else None,
        "competitor_price_high": max(prices) if prices else None,
        "competitor_tiers": dict(Counter(place["price_tier"] for place in rivals if place.get("price_tier"))),
        "premium_competitor_price": _tier_price(rivals, ("upscale", "luxury")),
        "budget_competitor_price": _tier_price(rivals, ("budget",)),
        "main_competitors": [_rival(place) for place in
                             sorted(rivals, key=lambda place: -(place.get("review_count") or 0))[:3]],
        "top_rated": _rival(max(established, key=lambda place: (place["average_rating"], place["review_count"])))
        if established else None,
        "lowest_rated": _rival(min(established, key=lambda place: (place["average_rating"], -place["review_count"])))
        if len(established) >= 2 else None,
        "negative_share": round(100 * sentiments["negative"] / sampled)
        if sampled >= settings()["sentiment_minimum_reviews"] else None,
        "sentiment_sample": sampled or None,
        "nearby_places": nearby or None,
        "market_study": True,
    }


def _benchmark(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rivals = [place for row in rows for place in row.get("rivals") or [] if place]
    restaurants = sum(row.get("restaurants") or 0 for row in rows)
    rated = [place["average_rating"] for place in rivals if _number(place.get("average_rating")) is not None]
    prices = [place["average_price"] for place in rivals if _number(place.get("average_price")) is not None]
    priced = sum(row.get("priced") or 0 for row in rows)
    area_price = (sum((row.get("area_price") or 0) * (row.get("priced") or 0) for row in rows) / priced
                  if priced else None)
    reviewed = [place["review_count"] for place in rivals if isinstance(place.get("review_count"), int)]
    competitor_reviews = sum(reviewed)
    return {
        "restaurants": restaurants,
        "competitors": len(rivals),
        "competitor_share": round(100 * len(rivals) / restaurants, 1) if restaurants else None,
        "competitor_rating": round(_mean(rated), 1) if rated else None,
        "competitor_reviews": competitor_reviews if reviewed else None,
        "competitor_reviews_avg": round(competitor_reviews / len(reviewed)) if reviewed else None,
        "competitor_price": round(_mean(prices), 1) if prices else None,
        "area_price": round(area_price, 1) if area_price is not None else None,
    }


def _weights(objective: str, price_position: str, target_price: float | None) -> dict[str, float]:
    values = settings()
    weights = {name: 0.0 for name in DIMENSIONS}
    weights.update(values["weights"])
    weights.update(values["objectives"].get(objective, {}))
    if price_position in ("none", "mid") and target_price is None:
        weights["price"] = 0.0  # no price aim: nothing to judge prices against
    return weights


# Each dimension from 0 to 1 per area, normalised across the compared areas; None where an area has no data.
def _dimensions(areas: list[dict[str, Any]], price_position: str, target_price: float | None,
                boosted: set[str], objective: str = "balanced") -> list[dict[str, float | None]]:
    values = settings()
    reviews = _scaled([_log(area["reviews"]) for area in areas])
    size = _scaled([float(area["restaurants"]) for area in areas])
    engagement = _scaled([_number(area["reviews_per_restaurant"]) for area in areas])
    market = [None if reviews[i] is None else 0.5 * reviews[i] + 0.3 * (size[i] or 0) + 0.2 * (engagement[i] or 0)
              for i in range(len(areas))]
    share = _scaled([_number(area["competitor_share"]) for area in areas])
    nearby = _scaled([_log(sum(values["nearby"][kind]["weight"] * (2 if kind in boosted else 1) * count
                                for kind, count in area["nearby_places"].items() if kind in values["nearby"]))
                      if area["nearby_places"] else None for area in areas])
    area_price = _scaled([_number(area["area_price"]) for area in areas])
    strength = _scaled([_log(float(area["competitor_reviews"] or 0)) for area in areas])
    count = _scaled([float(area["competitors"]) for area in areas])
    dimensions = []
    for i, area in enumerate(areas):
        competition = None
        if share[i] is not None:
            # Low competition counts for more in a bigger market, unless low competition is what the user asked
            # for; none at all is a possible gap, not proof of demand.
            low = objective == "low_competition"
            competition = (1 - share[i]) * (1 if low else 0.6 + 0.4 * (market[i] or 0))
            if area["competitors"] == 0:
                competition = min(competition, values["no_competitor_cap_low_competition" if low
                                                      else "no_competitor_cap"])
        price = None
        reference = _number(area["competitor_price"]) or _number(area["area_price"])
        if target_price and reference is not None:
            price = max(0.0, 1 - abs(reference - target_price) / target_price)
        elif price_position == "premium":
            price = area_price[i]
        elif price_position == "budget" and area_price[i] is not None:
            price = 1 - area_price[i]
        differentiation = None
        if area["competitor_rating"] is not None:
            room = max(0.0, min(1.0, (TOP_RATING - area["competitor_rating"]) / (TOP_RATING - LOW_RATING)))
            negative = area["negative_share"]
            differentiation = 0.7 * room + 0.3 * negative / 100 if negative is not None else room
        dimensions.append({
            "market": market[i],
            "competition": competition,
            "generators": nearby[i],
            "price": price,
            "differentiation": differentiation,
            "confidence": 0.5 * area["rated_share"] + 0.3 * area["priced_share"] + 0.2 * bool(area["nearby_places"]),
            "competitor_strength": None if strength[i] is None else 0.6 * strength[i] + 0.4 * (count[i] or 0),
        })
    return dimensions


def _score(dimensions: dict[str, float | None], weights: dict[str, float]) -> float:
    parts = [(weights[name], value) for name, value in dimensions.items() if value is not None and weights[name] > 0]
    total = sum(weight for weight, _ in parts)
    return round(100 * sum(weight * value for weight, value in parts) / total, 1) if total else 0.0


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# Areas the user named ("SS2", "Damansara Utama"), matched on the section code or a place in its brackets.
def named_areas(names: list[str], area_names: list[str]) -> list[str]:
    found = []
    for name in names or []:
        wanted = _compact(str(name))
        for area in area_names:
            code, _, places = area.partition(" (")
            if wanted and (wanted == _compact(code)
                           or any(wanted == _compact(place) for place in places.rstrip(")").split(","))):
                found.append(area)
                break
    return list(dict.fromkeys(found))


def _roles(order: list[dict[str, Any]], objective: str, named: bool,
           price_position: str = "none") -> list[tuple[dict[str, Any], str]]:
    limit = settings()["max_areas"]
    if named:
        if len(order) == 1:
            return [(order[0], "Area Assessment")]
        return [(area, "Best Fit" if index == 0 else "Alternative") for index, area in enumerate(order[:limit])]
    if objective == "strongest_market":
        labels = ("Strongest Existing Market", "Second-Strongest Market", "Third-Strongest Market")
        return list(zip(order[:limit], labels))
    first, rest = order[0], list(order[1:])
    picks = [(first, "Best Overall Opportunity")]
    lower = next((area for area in rest if area["competitor_share"] is not None and first["competitor_share"] is not None
                  and area["competitor_share"] < first["competitor_share"]), None)
    # When the first already has the least competition, the trade-off is a bigger market with more rivals.
    bigger = None if lower else next((area for area in rest if area["dimensions"].get("market", 0)
                                      > first["dimensions"].get("market", 0)), None)
    if (lower or bigger) and len(picks) < limit:
        picks.append((lower, "Lower-Competition Alternative") if lower else (bigger, "Larger-Market Alternative"))
        rest.remove(lower or bigger)
    # A different price positioning: among the areas that still score well, the one whose spending differs most.
    if len(picks) < limit and first["area_price"] is not None:
        candidates = [area for area in rest if area["area_price"] is not None
                      and area["score"] >= settings()["alternative_min_score_share"] * first["score"]
                      and (price_position != "budget" or area["area_price"] < first["area_price"])
                      and (price_position != "premium" or area["area_price"] > first["area_price"])]
        other = max(candidates, key=lambda area: abs(area["area_price"] - first["area_price"]), default=None)
        if other and abs(other["area_price"] - first["area_price"]) >= 2:
            higher = other["area_price"] > first["area_price"]
            picks.append((other, "Premium Positioning Alternative" if higher else "Budget Positioning Alternative"))
            rest.remove(other)
    picks += [(area, "Alternative") for area in rest[:limit - len(picks)]]
    return picks


# The compared areas, best first, each with its role, figures, dimension scores and the PJ benchmark;
# the competitors to put on the map. None when the graph could not be read.
def study(competitor_ids: list[Any], intent: dict[str, Any], question: str,
          timeout_seconds: float | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    values = settings()
    market = execute_cypher(AREA_MARKET, {"competitor_ids": competitor_ids}, timeout_seconds=timeout_seconds,
                            purpose="area market")
    if market.status != "success":
        return None
    rows = market.records
    # A Korean restaurant does not compete with a drinks shop that sells Korean drinks.
    if RESTAURANT.search(question or "") and intent.get("category") in (None, "none"):
        excluded = set(values["not_restaurant_competitors"])
        rows = [{**row, "rivals": [place for place in row.get("rivals") or []
                                   if place and place.get("kind") not in excluded]} for row in rows]
    named = named_areas(intent.get("areas") or [], [row["area_name"] for row in rows])
    eligible = [row for row in rows if row["area_name"] in named] if named else \
        [row for row in rows if (row.get("restaurants") or 0) >= values["min_restaurants"]]
    if not eligible:
        return [], []
    nearby = execute_cypher(NEARBY, {"areas": [row["area_name"] for row in eligible]}, timeout_seconds=timeout_seconds,
                            purpose="nearby places")
    around = ({row["area_name"]: dict(row.get("nearby") or []) for row in nearby.records}
              if nearby.status == "success" else {})
    areas = [_area(row, around.get(row["area_name"])) for row in eligible]

    objective = intent.get("objective") if intent.get("objective") in OBJECTIVES else "balanced"
    price_position = intent.get("price_position") if intent.get("price_position") in PRICE_POSITIONS else "none"
    target = TARGET_PRICE.search(question or "")
    target_price = float(target[1]) if target else None
    boosted = {kind for name in intent.get("preferences") or [] for kind in values["preference_nearby"].get(name, [])}
    weights = _weights(objective, price_position, target_price)
    for area, dimensions in zip(areas, _dimensions(areas, price_position, target_price, boosted, objective)):
        area["dimensions"] = {name: round(value, 3) for name, value in dimensions.items() if value is not None}
        area["score"] = _score(dimensions, weights)
    order = sorted(areas, key=lambda area: (-area["score"], area["area_name"]))
    chosen = _roles(order, objective, bool(named), price_position)
    pj = _benchmark(rows)
    # A score is only worth showing when it compares enough areas on enough data.
    show = len(eligible) >= 3 and all(area["dimensions"]["confidence"] >= values["show_score_min_confidence"]
                                      for area, _ in chosen)
    focus = bool(boosted) or bool(CUSTOMERS.search(question or ""))
    picked = [{**area, "role": role, "show_score": show, "pj": pj, "objective": objective,
               "price_position": price_position, "target_price": target_price, "customer_focus": focus}
              for area, role in chosen]
    return picked, [place for area in picked for place in area["main_competitors"]]
