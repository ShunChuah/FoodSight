# Every read here is limited to the request's remaining time budget.

import re
from dataclasses import replace
from datetime import date, datetime, time
from time import perf_counter
from typing import Any

from . import opening_hours
from ...contracts import QueryPlan
from ..query_generation.coverage import coverage_reply, named_outside_place, outside_coverage
from ..query_generation.cypher_generation import check_cypher, relaxed_parameters, translate_cuisines
from ..shared.config import policy
from ..shared.diagnostics import kg_debug
from ..shared.messages import response
from ..shared.neo4j import CypherExecutionResult, execute_cypher
from .opening_hours import WEEKDAYS, weekday_today, _yesterday, open_now, opens_next
from .presentation import distance_label

# Details for the restaurant_ids a generated query returns (generated queries return ids only).
RESTAURANT_DETAILS = """
UNWIND range(0, size($ids) - 1) AS position
MATCH (r:Restaurant) WHERE r.restaurant_id = $ids[position]
OPTIONAL MATCH (r)-[:LOCATED_IN]->(l:Location)
OPTIONAL MATCH (l)-[:IN_AREA]->(a:Area)
OPTIONAL MATCH (r)-[:HAS_RATING]->(rt:Rating)
OPTIONAL MATCH (r)-[:PRICED_AT]->(p:PriceRange)
OPTIONAL MATCH (r)-[:HAS_PROFILE]->(bp:BusinessProfile)
OPTIONAL MATCH (r)-[:HAS_HOURS]->(h:OperatingHours)
OPTIONAL MATCH (r)-[ns:NEAREST_STATION]->(st:NearbyPlace)
RETURN position, r.restaurant_id AS restaurant_id, r.name AS restaurant_name, r.amenity_type AS venue_type,
       r.brand AS brand,
       r.business_status AS business_status, r.phone AS phone, r.website AS website,
       l.latitude AS latitude, l.longitude AS longitude, l.full_address AS address, a.name AS area,
       rt.rating_score AS average_rating, rt.total_reviews AS review_count,
       p.avg_meal_price AS average_price, p.tier AS price_tier,
       bp.halal_status AS halal_status, bp.restaurant_type AS restaurant_type, bp.target_segment AS good_for,
       bp.ambiance AS ambiance, bp.service_style AS service_style, bp.evidence_level AS evidence_level,
       r.editorial_summary AS summary, st.name AS station, st.station_type AS station_type,
       ns.distance_m AS station_distance_m,
       h {.monday, .tuesday, .wednesday, .thursday, .friday, .saturday, .sunday, .is_24_7} AS hours,
       COLLECT { MATCH (r)-[:SERVES]->(c:Cuisine) RETURN c.name } AS cuisines,
       COLLECT { MATCH (r)-[:HAS_FACILITY]->(f:Facility) RETURN f.name } AS facilities
ORDER BY position
""".strip()

DETAIL_COLUMNS = {
    "position", "restaurant_id", "restaurant_name", "venue_type", "brand", "business_status", "latitude", "longitude", "area",
    "average_rating", "review_count", "average_price", "price_tier", "halal_status", "restaurant_type", "good_for",
    "ambiance", "service_style", "hours", "cuisines", "facilities", "hours_today", "currency", "anchor_id",
    "phone", "website", "address", "open_now", "opens_at", "weekly_hours", "summary", "nearest_station",
    "profile_is_a_guess",
}


def _relax(plan: QueryPlan, deadline: float | None) -> tuple[QueryPlan, CypherExecutionResult, int | None] | None:
    settings = policy("alternatives")
    stop = perf_counter() + settings["time_budget_seconds"]
    if deadline is not None:
        stop = min(stop, deadline - ANSWER_SECONDS)
    for parameters, radius in relaxed_parameters(plan.parameters):
        if perf_counter() >= stop:
            break
        looser = replace(plan, parameters=parameters, result_limit=min(plan.result_limit, settings["result_limit"]))
        execution = execute_cypher(*translate_cuisines(looser.cypher, parameters),
                                   timeout_seconds=max(0.5, stop - perf_counter()))
        kg_debug("Cypher relaxed", {"parameters": parameters, "rows": len(execution.records)})
        if execution.status == "success" and execution.records:
            return looser, execution, radius
    return None


ANCHOR_PLACES = """
UNWIND $ids AS id
MATCH (r:Restaurant) WHERE r.restaurant_id = id
OPTIONAL MATCH (r)-[:LOCATED_IN]->(:Location)-[:IN_AREA]->(a:Area)
OPTIONAL MATCH (r)-[:HAS_RATING]->(rt:Rating)
RETURN r.name AS name, a.name AS area
ORDER BY coalesce(rt.total_reviews, 0) DESC
""".strip()
AREA_BY_PATTERN = "MATCH (a:Area) WHERE a.name =~ $value RETURN count(a) AS areas"
AREA_BY_TEXT = "MATCH (a:Area) WHERE toLower(a.name) CONTAINS toLower($value) RETURN count(a) AS areas"
BUSY_AREAS = """
MATCH (r:Restaurant {counted_as_open: true})-[:LOCATED_IN]->(:Location)-[:IN_AREA]->(a:Area)
RETURN a.name AS area, count(r) AS restaurants
ORDER BY restaurants DESC
LIMIT 4
""".strip()


DISH_PLACES = """
MATCH (r:Restaurant {counted_as_open: true})
OPTIONAL MATCH (r)-[:LOCATED_IN]->(l:Location)
OPTIONAL MATCH (l)-[:IN_AREA]->(a:Area)
OPTIONAL MATCH (r)-[:HAS_PROFILE]->(bp:BusinessProfile)
OPTIONAL MATCH (r)-[:PRICED_AT]->(p:PriceRange)
OPTIONAL MATCH (r)-[:HAS_RATING]->(rt:Rating)
WITH r, a, bp, p, rt,
     toLower(r.name) CONTAINS $dish OR toLower(coalesce(r.editorial_summary, '')) CONTAINS $dish AS named,
     CASE WHEN $radius IS NULL OR l IS NULL THEN null
          ELSE point.distance(point({latitude: l.latitude, longitude: l.longitude}),
                              point({latitude: $latitude, longitude: $longitude})) END AS distance_m
WHERE ($area IS NULL OR a.name =~ $area)
  AND ($radius IS NULL OR distance_m <= $radius)
  AND (named OR ($cuisine IS NOT NULL AND EXISTS { MATCH (r)-[:SERVES]->(:Cuisine {name: $cuisine}) }
                 AND NOT coalesce(bp.restaurant_type, '') IN $not_meals))
WITH DISTINCT r, named, p, rt, distance_m
RETURN r.restaurant_id AS restaurant_id, round(distance_m) AS distance_m
ORDER BY named DESC, CASE WHEN $budget THEN coalesce(p.avg_meal_price, 1000) ELSE 0 END,
         coalesce(rt.rating_score, 0) DESC, coalesce(rt.total_reviews, 0) DESC
LIMIT $limit
""".strip()
NOT_MEALS = ["bakery", "cafe", "dessert_shop", "drinks_shop", "bar_pub"]


# Places with the dish in their name or summary first, then sit-down places of its cuisine; price only orders them.
def _dish_places(dish: str, cuisine: str | None, area: str | None, budget: bool, limit: int,
                 deadline: float | None, near: tuple[float, float, float] | None = None) -> list[dict[str, Any]]:
    latitude, longitude, radius = near or (None, None, None)
    found = execute_cypher(DISH_PLACES, {"dish": dish.lower(), "cuisine": cuisine, "area": area, "budget": budget,
                                         "limit": limit, "not_meals": NOT_MEALS, "latitude": latitude,
                                         "longitude": longitude, "radius": radius},
                           timeout_seconds=_query_time(deadline), purpose="dish places")
    return found.records if found.status == "success" else []


def _anchor_question(rows: list[dict[str, Any]], deadline: float | None) -> tuple[str, list[str]] | None:
    anchors = list(dict.fromkeys(row["anchor_id"] for row in rows if row.get("anchor_id") is not None))
    if len(anchors) < 2:
        return None
    places = execute_cypher(ANCHOR_PLACES, {"ids": anchors}, timeout_seconds=_query_time(deadline),
                            purpose="named places").records
    if len(places) < 2:
        return None
    names = [place["name"] for place in places]
    options = [
        f"{place['name']} in {place['area']}" if names.count(place["name"]) > 1 and place.get("area") else place["name"]
        for place in places
    ]
    return "I found a few places with that name. Which one do you mean?", list(dict.fromkeys(options))[:4]


def _unknown_area_question(plan: QueryPlan, deadline: float | None, question: str = "",
                           conversation_context: str = "") -> tuple[str, list[str]] | None:
    area_variables = set(re.findall(r"\(\s*([A-Za-z_]\w*)\s*:\s*Area\b", plan.cypher))
    for variable in area_variables:
        v = re.escape(variable)
        pattern = re.search(rf"\b{v}\.name\s*=~\s*\$(\w+)", plan.cypher)
        text = re.search(rf"toLower\(\s*{v}\.name\s*\)\s*(?:CONTAINS|=|STARTS\s+WITH)\s*toLower\(\s*\$(\w+)\s*\)"
                         rf"|\b{v}\.name\s*(?:=|CONTAINS)\s*\$(\w+)", plan.cypher, flags=re.IGNORECASE)
        if pattern:
            check, value, label = AREA_BY_PATTERN, plan.parameters.get(pattern.group(1)), None
        elif text:
            value = plan.parameters.get(text.group(1) or text.group(2))
            check, label = AREA_BY_TEXT, value
        else:
            continue
        if not isinstance(value, str):
            continue
        outside = named_outside_place(label) if label else None
        if outside:
            coverage = (outside_coverage(question, conversation_context, anywhere=True)
                        or coverage_reply(question, outside, conversation_context))
            return coverage.message, list(coverage.suggestions)
        found = execute_cypher(check, {"value": value}, timeout_seconds=_query_time(deadline))
        if found.status != "success" or (found.records and found.records[0].get("areas")):
            continue
        busy = execute_cypher(BUSY_AREAS, {}, timeout_seconds=_query_time(deadline), purpose="busy areas").records
        place = f"an area called “{label}”" if label else "that area"
        return (f"I couldn't find {place} in Petaling Jaya, which is the area I cover. Which area should I look in?",
                [row["area"] for row in busy if row.get("area")])
    return None


def _run(plan: QueryPlan, deadline: float | None, more_candidates: bool = False,
         pool: int | None = None) -> CypherExecutionResult:
    # Re-checked so a retried query never runs unchecked.
    if check_cypher(plan.cypher, plan.parameters):
        return CypherExecutionResult([], "invalid", response("errors.validation"))
    cypher = plan.cypher
    if more_candidates:
        maximum = pool or policy("results")["maximum_limit"]
        cypher = re.sub(r"\bLIMIT\s+\d+\b", f"LIMIT {maximum}", cypher, flags=re.IGNORECASE)
    return execute_cypher(*translate_cuisines(cypher, plan.parameters), timeout_seconds=_query_time(deadline),
                          purpose="search")


ANSWER_SECONDS = 3.0


def _query_time(deadline: float | None) -> float | None:
    return max(0.5, deadline - perf_counter() - ANSWER_SECONDS) if deadline is not None else None


def _with_restaurant_details(rows: list[dict[str, Any]], deadline: float | None) -> list[dict[str, Any]]:
    groups: dict[Any, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("restaurant_id") is not None:
            groups.setdefault(row["restaurant_id"], []).append(row)
    if not groups:
        return []
    first = {}
    for restaurant_id, group in groups.items():
        row = dict(group[0])
        for key in row:
            values = [item.get(key) for item in group]
            if len(group) > 1 and key not in DETAIL_COLUMNS and any(value != values[0] for value in values):
                row[key] = values
        first[restaurant_id] = row
    details = execute_cypher(RESTAURANT_DETAILS, {"ids": list(first)}, timeout_seconds=_query_time(deadline),
                             purpose="restaurant details")
    if details.status != "success":
        kg_debug("Restaurant details unavailable", details.message)
        return rows
    found = {row["restaurant_id"]: {key: _plain(value) for key, value in row.items()} for row in details.records}
    today = weekday_today()
    merged = []
    for restaurant_id, row in first.items():
        detail = found.get(restaurant_id)
        if not detail:
            continue
        hours = detail.pop("hours", None) or {}
        detail.pop("position", None)
        for key in ("good_for", "ambiance", "service_style"):
            detail[key] = _readable(detail.get(key))
        detail["profile_is_a_guess"] = detail.pop("evidence_level", None) == "low" or None
        station, kind, metres = (detail.pop(key, None) for key in ("station", "station_type", "station_distance_m"))
        detail["nearest_station"] = (f"{station}" + (f" ({kind})" if kind and kind != "Other" else "")
                                     + (f", {distance_label(metres)}" if distance_label(metres) else "")
                                     if station else None)
        detail["hours_today"] = "open 24 hours" if hours.get("is_24_7") else hours.get(today)
        detail["weekly_hours"] = {day: hours[day] for day in WEEKDAYS if hours.get(day)} \
            if not hours.get("is_24_7") else None
        now = opening_hours.now_local()
        detail["open_now"] = open_now(detail["hours_today"], now, _yesterday(detail["weekly_hours"], now))
        detail["opens_at"] = opens_next(detail["weekly_hours"], now) if detail["open_now"] is False else None
        detail["currency"] = "MYR"
        merged.append({**{k: v for k, v in row.items() if k not in DETAIL_COLUMNS}, **detail})
    return merged


def _readable(value: Any) -> Any:
    if isinstance(value, list):
        return ", ".join(str(item).replace("_", " ") for item in value) or None
    return value.replace("_", " ") if isinstance(value, str) else value


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if hasattr(value, "iso_format"):
        return value.iso_format()
    if hasattr(value, "items") and hasattr(value, "labels"):
        return {key: _plain(item) for key, item in value.items()}
    if hasattr(value, "x") and hasattr(value, "y"):
        return {"longitude": value.x, "latitude": value.y}
    return str(value)
