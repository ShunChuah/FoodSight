import json
import re
from time import perf_counter
from typing import Any

from .llm_service import LLMServiceError, call_llm
from .schema_service import (
    format_assumptions,
    load_query_assumptions,
    retrieve_relevant_assumptions,
)

# User goals:
ALLOWED_INTENTS = (
    "restaurant_recommendation",
    "restaurant_search",
    "restaurant_comparison",
    "area_analysis",
    "competitor_analysis",
    "market_gap_analysis",
    "general_fnb_question",
    "unsupported",
)
ALLOWED_SCOPES = ("fnb_customer", "fnb_analyst")
# Query Strategy:
ALLOWED_ANALYSIS_MODES = (
    "restaurant_lookup",  # to look up for restaurants
    "area_opportunity",  # to rank or analyze areas for opening a business
    "competitor_density",  # to analyze competitor density/saturation
    "market_gap",  # to identify underserved cuisine or business opportunity
    "pricing_analysis",  # to analyze menu or restaurant pricing
    "customer_segment_analysis",  # to analyze target customer segments
    "location_risk_analysis",  # to analyze area/location risk signals
    "menu_gap_analysis",  # to analyze underserved menu or dish opportunities
)
COMPACT_INTENT_FILTERS = {
    "Restaurant": {
        "name": [],
        "venue_type": None,
        "average_rating": None,
        "review_count": None,
    },
    "Location": {
        "address": None,
        "postcode": None,
    },
    "Area": {
        "name": None,
        "type": None,
    },
    "City": {
        "name": None,
    },
    "Cuisine": {
        "name": [],
        "category": [],
    },
    "Dish": {
        "name": [],
        "price": None,
        "category": [],
        "is_signature": None,
    },
    "MenuCategory": {
        "name": [],
        "description": [],
    },
    "PriceRange": {
        "tier": None,
        "avg_price": None,
    },
    "BusinessProfile": {
        "target_segment": None,
        "dining_experience": None,
        "business_style": None,
        "ambiance": None,
    },
    "Cluster": {
        "restaurant_count": None,
        "density_score": None,
    },
    "Promotion": {
        "title": None,
        "discount_type": None,
        "is_active": None,
    },
    "Facility": {
        "name": [],
        "type": None,
        "is_available": None,
    },
}
QUERY_UNDERSTANDING_JSON_SHAPE = {
    "intent": "...",
    "scope": "...",
    "needs_clarification": False,
    "clarification_question": None,
    "analysis": {
        "mode": None,
    },
    "filters": COMPACT_INTENT_FILTERS,
    "location": {
        "type": None,
        "value": None,
        "requires_browser_location": False,
    },
    "sort": {
        "label": None,
        "property": None,
        "direction": None,
    },
    "limit": None,
}


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value))


QUERY_UNDERSTANDING_PROMPT = f"""
Convert the user's message into FoodSight query-understanding JSON.
Return valid JSON only. Do not generate Cypher.

Allowed intents:
{chr(10).join(f"- {intent}" for intent in ALLOWED_INTENTS)}

Allowed scopes:
{chr(10).join(f"- {scope}" for scope in ALLOWED_SCOPES)}

Rules:
- Non-F&B: intent "unsupported", scope null, empty filters.
- F&B: infer intent, scope, useful schema fields, location, sort, and limit.
  Limit is 3 unless the user explicitly asks for a number.
- Use only labels/properties in the JSON shape; no helper fields.
- Map meaning to the closest queryable field:
  food need/craving/flavor/health goal -> Dish or Cuisine;
  dining style/audience/ambiance -> BusinessProfile;
  venue/rating -> Restaurant; price -> PriceRange; 
  facilities -> Facility;
  market/location opportunity -> Area, City, Cluster, Restaurant.
- Infer concrete queryable values. Do not copy vague words as the only
  Dish/Cuisine value.
- For fnb_analyst analysis.mode:
  where-to-open/location -> area_opportunity;
  competitor/saturation -> competitor_density;
  gap/underserved -> market_gap;
  menu/item/price setting -> pricing_analysis;
  customer/segment/audience -> customer_segment_analysis;
  risk/location risk/too competitive -> location_risk_analysis;
  menu/dish/product gap -> menu_gap_analysis;
  existing restaurant lookup -> restaurant_lookup.
- area_opportunity with no named location means rank all candidate areas.
- Customer recommendation/search with no named place needs browser location.
- Use query assumptions only for defaults and configurable mappings.
- Use conversation only to resolve follow-ups.
- Clarify only when no safe F&B query can be formed.
- Use null for unknown scalar fields and [] for empty lists.

JSON shape:
{json.dumps(QUERY_UNDERSTANDING_JSON_SHAPE, indent=2)}
""".strip()

DEFAULT_UNDERSTANDING = {
    **_json_clone(QUERY_UNDERSTANDING_JSON_SHAPE),
    "intent": "restaurant_search",
    "scope": "fnb_customer",
    "limit": 3,
}


def extract_query_understanding(
    user_query: str,
    conversation_context: str = "No previous conversation.",
    scope: str | None = None,
) -> dict[str, Any]:
    assumption_context = _relevant_assumption_context(
        user_query,
        conversation_context,
    )
    prompt = (
        f"Known scope from guardrail: {scope or 'unknown'}\n\n"
        f"Relevant query assumptions:\n{assumption_context}\n\n"
        f"Conversation:\n{conversation_context}\n\n"
        f"User query:\n{user_query}"
    )

    try:
        started_at = perf_counter()
        print(
            "[TIMING] Query understanding started. " "elapsed=0.00s total=0.00s",
            flush=True,
        )
        raw = call_llm(prompt, QUERY_UNDERSTANDING_PROMPT)
        parsed = _parse_json_object(raw or "")
    except LLMServiceError:
        parsed = None
    finally:
        if "started_at" in locals():
            elapsed = perf_counter() - started_at
            print(
                f"[TIMING] Query understanding generated JSON. "
                f"elapsed={elapsed:.2f}s total={elapsed:.2f}s",
                flush=True,
            )

    understanding_source = (
        parsed
        if isinstance(parsed, dict)
        else _fallback_understanding(user_query, scope)
    )
    understanding = _normalize_understanding(understanding_source, user_query, scope)
    if understanding.get("intent") == "unsupported":
        return understanding
    return _merge_deterministic_signals(
        understanding,
        user_query,
        scope,
        conversation_context,
    )


def format_query_understanding(understanding: dict[str, Any] | None) -> str:
    if not understanding:
        return "No structured query understanding provided."
    return json.dumps(understanding, ensure_ascii=False, indent=2)


def _relevant_assumption_context(
    user_query: str,
    conversation_context: str,
) -> str:
    try:
        relevant_assumptions = retrieve_relevant_assumptions(
            load_query_assumptions(),
            user_query,
            conversation_context,
        )
    except RuntimeError:
        return "No query assumptions matched."
    return format_assumptions(relevant_assumptions)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*([\s\S]*?)```",
        cleaned,
        flags=re.IGNORECASE,
    )
    if fenced:
        cleaned = fenced.group(1).strip()

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_filters(value: dict[str, Any]) -> dict[str, Any]:
    filters = _json_clone(DEFAULT_UNDERSTANDING["filters"])

    for label, allowed_properties in filters.items():
        supplied_properties = value.get(label)
        if not isinstance(supplied_properties, dict):
            continue
        for property_name, default_value in allowed_properties.items():
            if property_name not in supplied_properties:
                continue
            filters[label][property_name] = _normalize_filter_value(
                supplied_properties[property_name],
                default_value,
            )
    return filters


def _normalize_filter_value(value: object, default_value: object) -> object:
    if isinstance(default_value, dict):
        normalized = _json_clone(default_value)
        supplied = value if isinstance(value, dict) else {}
        for key, nested_default in default_value.items():
            if isinstance(supplied, dict) and key in supplied:
                normalized[key] = _normalize_filter_value(
                    supplied[key],
                    nested_default,
                )
        return normalized

    if isinstance(default_value, list):
        values = value if isinstance(value, list) else [value]
        return [_clean_term(item) for item in values if _clean_term(item)]

    if isinstance(default_value, bool):
        return value if isinstance(value, bool) else None

    if isinstance(default_value, (int, float)):
        return float(value) if isinstance(value, (int, float)) else None

    if default_value is None:
        if isinstance(value, str):
            return _clean_term(value)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return float(value)
        return None

    return None


def _normalize_understanding(
    value: dict[str, Any],
    user_query: str,
    scope: str | None,
) -> dict[str, Any]:
    understanding = _json_clone(DEFAULT_UNDERSTANDING)
    understanding.update({key: value.get(key) for key in understanding if key in value})

    filters = value.get("filters")
    if isinstance(filters, dict):
        understanding["filters"] = _normalize_filters(filters)

    analysis = value.get("analysis")
    if isinstance(analysis, dict):
        understanding["analysis"].update(
            {
                key: analysis.get(key)
                for key in understanding["analysis"]
                if key in analysis
            }
        )

    location = value.get("location")
    if isinstance(location, dict):
        understanding["location"].update(
            {
                key: location.get(key)
                for key in understanding["location"]
                if key in location
            }
        )

    sort = value.get("sort")
    if isinstance(sort, dict):
        understanding["sort"].update(
            {key: sort.get(key) for key in understanding["sort"] if key in sort}
        )

    if understanding["intent"] not in ALLOWED_INTENTS:
        understanding["intent"] = _fallback_intent(user_query, scope)
    if scope in ALLOWED_SCOPES:
        understanding["scope"] = scope
    elif understanding["intent"] == "unsupported":
        understanding["scope"] = None
    elif understanding["scope"] not in ALLOWED_SCOPES:
        understanding["scope"] = "fnb_customer"

    understanding["needs_clarification"] = bool(
        understanding.get("needs_clarification")
    )
    if understanding["analysis"].get("mode") not in ALLOWED_ANALYSIS_MODES:
        understanding["analysis"]["mode"] = _fallback_analysis_mode(
            user_query,
            understanding["scope"],
            understanding["intent"],
        )
    if not isinstance(understanding.get("clarification_question"), str):
        understanding["clarification_question"] = None
    else:
        understanding["clarification_question"] = (
            " ".join(understanding["clarification_question"].strip().split())[:500]
            or None
        )

    if not isinstance(understanding["location"].get("type"), str):
        understanding["location"]["type"] = None
    if not isinstance(understanding["location"].get("value"), str):
        understanding["location"]["value"] = None
    understanding["location"]["requires_browser_location"] = bool(
        understanding["location"].get("requires_browser_location")
    )

    if not isinstance(understanding["sort"].get("label"), str):
        understanding["sort"]["label"] = None
    if not isinstance(understanding["sort"].get("property"), str):
        understanding["sort"]["property"] = None
    if understanding["sort"].get("direction") not in {"asc", "desc"}:
        understanding["sort"]["direction"] = None

    requested_limit = _extract_requested_limit(user_query)
    understanding["limit"] = requested_limit if requested_limit is not None else 3
    return understanding


def _merge_deterministic_signals(
    understanding: dict[str, Any],
    user_query: str,
    scope: str | None,
    conversation_context: str = "No previous conversation.",
) -> dict[str, Any]:
    normalized = " ".join(user_query.lower().strip().split())
    effective_scope = scope if scope in ALLOWED_SCOPES else understanding.get("scope")

    if _contains_any(
        normalized,
        {"near me", "nearby", "around me", "around here", "closest", "nearest"},
    ):
        understanding["location"]["type"] = None
        understanding["location"]["value"] = None
        understanding["location"]["requires_browser_location"] = True
    elif _conversation_awaits_location(conversation_context):
        location = " ".join(user_query.strip().split())
        if location:
            understanding["needs_clarification"] = False
            understanding["clarification_question"] = None
            understanding["intent"] = _fallback_intent(user_query, effective_scope)
            understanding["location"]["type"] = "named_area"
            understanding["location"]["value"] = location[:160]
            understanding["location"]["requires_browser_location"] = False

    explicit_location = _extract_explicit_location(user_query)
    if explicit_location:
        understanding["location"]["type"] = "named_area"
        understanding["location"]["value"] = explicit_location
        understanding["location"]["requires_browser_location"] = False

    if effective_scope == "fnb_analyst":
        understanding["scope"] = "fnb_analyst"
        if understanding["intent"] in {
            "restaurant_recommendation",
            "restaurant_search",
        }:
            understanding["intent"] = _fallback_intent(user_query, effective_scope)
        if understanding["analysis"].get("mode") == "restaurant_lookup":
            understanding["analysis"]["mode"] = _fallback_analysis_mode(
                user_query,
                "fnb_analyst",
                understanding["intent"],
            )

    return understanding


def _fallback_understanding(user_query: str, scope: str | None) -> dict[str, Any]:
    normalized = " ".join(user_query.lower().strip().split())
    understanding = _json_clone(DEFAULT_UNDERSTANDING)
    has_fnb_signal = _has_fallback_fnb_signal(normalized)

    if scope not in ALLOWED_SCOPES and not has_fnb_signal:
        understanding["intent"] = "unsupported"
        understanding["scope"] = None
        return understanding

    understanding["intent"] = _fallback_intent(user_query, scope)
    if scope in ALLOWED_SCOPES:
        understanding["scope"] = scope

    # Minimal non-LLM fallback. Semantic food understanding belongs to the LLM.
    if _contains_any(
        normalized,
        {"near me", "nearby", "around me", "around here", "closest", "nearest"},
    ):
        understanding["location"]["requires_browser_location"] = True
    elif scope == "fnb_customer" and _contains_any(
        normalized,
        {
            "craving",
            "find",
            "recommend",
            "show me",
            "suggest",
            "want to drink",
            "want to eat",
            "where should i eat",
        },
    ):
        understanding["location"]["requires_browser_location"] = True

    return understanding


def _has_fallback_fnb_signal(normalized: str) -> bool:
    return _contains_any(
        normalized,
        {
            "beverage",
            "boba",
            "breakfast",
            "brunch",
            "cafe",
            "coffee",
            "craving",
            "cuisine",
            "dinner",
            "dining",
            "drink",
            "eat",
            "food",
            "hungry",
            "lunch",
            "meal",
            "menu",
            "restaurant",
            "supper",
            "want to drink",
            "want to eat",
            "what should i eat",
            "what to eat",
        },
    )


def _fallback_intent(user_query: str, scope: str | None) -> str:
    normalized = user_query.lower()
    if scope == "fnb_analyst":
        if any(
            term in normalized for term in ("price", "pricing", "charge", "set for")
        ):
            return "competitor_analysis"
        if any(
            term in normalized
            for term in ("customer", "segment", "audience", "target market")
        ):
            return "area_analysis"
        if any(term in normalized for term in ("risk", "risky", "too competitive")):
            return "area_analysis"
        if any(term in normalized for term in ("menu", "dish", "product")):
            return "market_gap_analysis"
        if any(term in normalized for term in ("competitor", "competition")):
            return "competitor_analysis"
        if any(term in normalized for term in ("gap", "underserved")):
            return "market_gap_analysis"
        return "area_analysis"
    if any(term in normalized for term in ("recommend", "suggest", "best")):
        return "restaurant_recommendation"
    if any(term in normalized for term in ("compare", "which one", "which is better")):
        return "restaurant_comparison"
    return "restaurant_search"


def _fallback_analysis_mode(
    user_query: str,
    scope: str | None,
    intent: str | None,
) -> str | None:
    if scope != "fnb_analyst":
        return "restaurant_lookup"

    normalized = user_query.lower()
    if any(term in normalized for term in ("price", "pricing", "charge", "set for")):
        return "pricing_analysis"
    if any(
        term in normalized
        for term in ("customer", "segment", "audience", "target market")
    ):
        return "customer_segment_analysis"
    if any(term in normalized for term in ("risk", "risky", "too competitive")):
        return "location_risk_analysis"
    if any(term in normalized for term in ("menu", "dish", "product")):
        return "menu_gap_analysis"
    if any(term in normalized for term in ("competitor", "competition", "saturation")):
        return "competitor_density"
    if any(term in normalized for term in ("gap", "underserved")):
        return "market_gap"
    if intent in {"area_analysis", "market_gap_analysis"}:
        return "area_opportunity"
    return "restaurant_lookup"


def _extract_explicit_location(user_query: str) -> str | None:
    match = re.search(
        (
            r"\b(?:near|in|at|around|within|close to)\s+"
            r"([a-z0-9][a-z0-9 .,'-]{1,80}?)"
            r"(?=\s+(?:for|with|under|below|above|that|serving|open)\b|[?!.]|$)"
        ),
        user_query,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    location = " ".join(match.group(1).strip().split())
    return (
        None
        if location.lower() in {"here", "me", "my location", "current location"}
        else location
    )


def _extract_requested_limit(user_query: str) -> int | None:
    match = re.search(
        (
            r"\b(?:top|show|give|find|return|list|suggest|recommend)?\s*"
            r"(\d{1,2})\s+"
            r"(?:options?|results?|places?|restaurants?|cafes?|areas?|"
            r"recommendations?|items?|dishes?)\b"
        ),
        user_query,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    return max(1, min(int(match.group(1)), 25))


def _contains_any(text: str, terms: set[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) for term in terms)


def _conversation_awaits_location(conversation_context: str) -> bool:
    assistant_lines = [
        line.lower()
        for line in conversation_context.splitlines()
        if line.startswith("Assistant:")
    ]
    if not assistant_lines:
        return False
    last_assistant = assistant_lines[-1]
    return (
        "which area" in last_assistant
        or "which city or area" in last_assistant
        or "specific area" in last_assistant
        or "location would you like" in last_assistant
    )


def _clean_term(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.lower().strip().split())
    return cleaned[:80] if cleaned else None
