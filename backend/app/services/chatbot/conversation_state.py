# What a chat is about, kept between turns for follow-ups ("only halal ones", "the second one").
# Filters come from the ontology's vocabulary bindings, so new categories.json columns need no code change.

import re
from typing import Any

from ...contracts import QueryPlan
from ..insight_generation.graph_query import filters_on_area, named_places
from ..query_generation.cypher_generation import allowed_values, load_vocabulary, vocabulary_bindings

STATE_VERSION = 1
MAX_SHOWN = 5
LITERAL = r"'((?:[^'\\]|\\.)*)'"
VALUE = rf"(?:{LITERAL}|\[([^\]]*)\]|\$(\w+))"


def search_state(plan: QueryPlan, rows: list[dict[str, Any]], place: str | None = None) -> dict:
    places = [{"restaurant_id": row["restaurant_id"], "name": row["restaurant_name"], "area": row.get("area")}
              for row in rows if row.get("restaurant_id") is not None and row.get("restaurant_name")]
    state = {
        "version": STATE_VERSION,
        "business": plan.business,
        "filters": query_filters(plan.cypher, plan.parameters),
        "area": _area(plan, rows) or place,
        "places_named": [" ".join(words) for words in named_places(plan.parameters)],
        "shown": places[:MAX_SHOWN],
        "areas_shown": [row["area_name"] for row in rows if row.get("area_name") and not places][:MAX_SHOWN],
    }
    return {key: value for key, value in state.items() if value not in (None, [], {})}


def query_filters(cypher: str, parameters: dict[str, Any]) -> dict[str, list[str]]:
    filters: dict[str, list[str]] = {}
    for (label, prop), column in vocabulary_bindings().items():
        allowed, routine = allowed_values(column), _not_a_choice(column)
        for value in _values(cypher, parameters, label, prop):
            if value in allowed and value not in routine and value not in filters.get(column, []):
                filters.setdefault(column, []).append(value)
    return filters


def state_prompt(state: dict | None) -> str:
    if not state or state.get("version") != STATE_VERSION:
        return ""
    lines = ["What this chat is about so far (keep it for follow-ups unless the user changes it):",
             f"- Asked as: {'a business owner or analyst' if state.get('business') else 'a diner'}"]
    for column, values in (state.get("filters") or {}).items():
        lines.append(f"- {column}: {', '.join(values)}")
    if state.get("area"):
        lines.append(f"- Area: {state['area']}")
    if state.get("places_named"):
        lines.append(f"- Places named: {', '.join(state['places_named'])}")
    if state.get("shown"):
        lines.append("- Places shown last, in order: " + "; ".join(
            f"{index}. {place['name']} (restaurant_id {place['restaurant_id']})"
            for index, place in enumerate(state["shown"], 1)))
        lines.append("  For 'it', 'that one' or 'the second one', set details true and return only that place: "
                     "MATCH (r:Restaurant {restaurant_id: <its id>}) RETURN r.restaurant_id AS restaurant_id. "
                     "The app adds its details itself.")
    if state.get("areas_shown"):
        lines.append("- Areas shown last, in order: " + "; ".join(
            f"{index}. {area}" for index, area in enumerate(state["areas_shown"], 1)))
    return "\n".join(lines)


def _values(cypher: str, parameters: dict[str, Any], label: str, prop: str) -> list[str]:
    found = []
    for node in re.finditer(rf"\(\s*(\w*)\s*:\s*{label}\b\s*(\{{[^}}]*\}})?", cypher):
        variable, inline = node.group(1), node.group(2) or ""
        found += [_read(match, parameters) for match in re.finditer(rf"\b{prop}\s*:\s*{VALUE}", inline)]
        if variable:
            found += [_read(match, parameters) for match in
                      re.finditer(rf"\b{variable}\.{prop}\s*(?:=|\bIN\b)\s*{VALUE}", cypher, flags=re.IGNORECASE)]
            found += [_read(match, parameters) for match in
                      re.finditer(rf"{VALUE}\s+IN\s+{variable}\.{prop}\b", cypher, flags=re.IGNORECASE)]
    return [str(value) for group in found for value in group]


def _read(match: re.Match, parameters: dict[str, Any]) -> list:
    literal, listed, parameter = match.groups()
    if literal is not None:
        return [literal]
    if listed is not None:
        return re.findall(LITERAL, listed)
    value = parameters.get(parameter)
    return value if isinstance(value, list) else [value] if isinstance(value, str) else []


# Statuses counted as open (categories.json) are the routine "still trading" filter, not the user's choice.
def _not_a_choice(column: str) -> set[str]:
    return set(load_vocabulary()["columns"][column].get("counted_as_open", []))


def _area(plan: QueryPlan, rows: list[dict[str, Any]]) -> str | None:
    if not filters_on_area(plan.cypher):
        return None
    areas = {row.get("area") for row in rows if row.get("area")}
    return areas.pop() if len(areas) == 1 else None
