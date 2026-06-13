import re
from dataclasses import dataclass

from .knowledge_graph_service import answer_with_knowledge_graph, format_kg_response
from .query_understanding_service import extract_query_understanding


LLM_ERROR_ANSWER = (
    "I could not generate the Cypher query because the LLM service is unavailable. "
    "Please check the backend logs and LLM configuration."
)
LOCATION_REQUEST_ANSWER = (
    "I need a location to answer that recommendation. Browser location is not "
    "available, so please tell me the specific area to search."
)

# Fast F&B scope signals. Ambiguous messages still fall through to query understanding.
FNB_ENTITY_TERMS = {
    "bakery", "beverage", "beverages", "boba", "breakfast", "brunch",
    "cafe", "cafes", "coffee", "cuisine", "dessert", "desserts", "dinner",
    "dining", "drink", "drinks", "eat", "food", "lunch", "meal", "menu",
    "restaurant", "restaurants", "supper", "dish", "dishes",
}

OPENING_INTENT_PHRASES = {
    "open a", "open new", "opening a", "where is suitable",
    "where should i open",
}

ANALYST_INTENT_PHRASES = OPENING_INTENT_PHRASES | {
    "business opportunity", "competitor", "competitors", "competition",
    "market", "market gap", "market saturation", "restaurant density",
    "saturation", "suitable area", "target segment", "underserved",
}

# Short follow-ups can inherit the previous F&B scope.
FOLLOW_UP_SIGNALS = {
    "ambiance", "budget", "cheap", "cheaper", "cheapest", "facilities",
    "facility", "luxury", "premium", "price", "pricing", "rating", "ratings",
    "review", "reviews", "compare them", "how about", "what about",
    "which is better", "which one", "which ones",
}

CURRENT_LOCATION_PHRASES = {
    "near me", "nearby", "around me", "around here", "close to me",
    "closest", "nearest", "walking distance", "current location",
}

# Customer search/recommendation language usually needs a location.
LOCATION_SEARCH_PHRASES = {
    "craving", "find", "recommend", "show me", "suggest", "want to drink",
    "want to eat", "where can i", "where should i",
}

# Clarify contradictory price filters before Cypher generation.
PRICE_INTENT_TERMS = {
    "affordable": {"affordable", "budget", "cheap", "inexpensive"},
    "premium": {"expensive", "luxury", "premium", "high end"},
}

# Stop requests for data absent from the current graph.
UNSUPPORTED_DATA_TERMS = {
    "revenue": "revenue",
    "profit": "profit",
    "sales forecast": "sales forecasts",
    "monthly sales": "monthly sales",
    "operating cost": "operating costs",
    "rental cost": "rental costs",
}


@dataclass(frozen=True)
class GuardrailDecision:
    status: str
    scope: str | None = None
    message: str | None = None
    location_required: bool = False
    detected_location: str | None = None
    query_understanding: dict | None = None


def generate_assistant_response(
    messages: list[dict[str, str]],
    location_context: str = "No location context provided.",
    location_permission_denied: bool = False,
    preflight_decision: GuardrailDecision | None = None,
) -> tuple[str, str | None]:
    user_query = messages[-1]["content"] if messages else ""
    conversation_context = format_conversation_context(messages[:-1])

    if preflight_decision and preflight_decision.status in {
        "clarification_required",
        "unsupported",
        "out_of_scope",
    }:
        return (
            preflight_decision.message
            or _default_guardrail_message(preflight_decision.status),
            None,
        )

    decision = preflight_decision
    scope = decision.scope if decision else None
    if not decision or decision.status != "ready" or not scope:
        decision = assess_query_guardrails(user_query, conversation_context)
        if decision.status != "ready":
            return decision.message or _default_guardrail_message(decision.status), None
        scope = decision.scope

    if not scope:
        return (
            "I could not confirm the request as an F&B customer or analyst question. "
            "Please clarify what Food & Beverage decision you want help with.",
            None,
        )
    query_understanding = (
        decision.query_understanding
        if decision and decision.query_understanding
        else extract_query_understanding(user_query, conversation_context, scope)
    )
    if (
        query_understanding.get("intent") == "unsupported"
        or query_understanding.get("scope") not in {"fnb_customer", "fnb_analyst"}
    ):
        return (
            "I cannot answer this question because it is outside Food & Beverage. "
            "FoodSight supports F&B customer and F&B business-analysis questions.",
            None,
        )
    if query_understanding.get("needs_clarification"):
        return (
            query_understanding.get("clarification_question")
            or "Could you clarify what kind of Food & Beverage result you want?",
            None,
        )

    if location_permission_denied:
        return LOCATION_REQUEST_ANSWER, None

    _apply_location_context_to_understanding(
        query_understanding,
        location_context,
    )
    understanding_location = query_understanding.get("location") or {}
    understanding_needs_location = bool(
        isinstance(understanding_location, dict)
        and understanding_location.get("requires_browser_location")
    )
    guardrail_needs_location = bool(decision and decision.location_required)
    if (
        (guardrail_needs_location or understanding_needs_location)
        and location_context == "No location context provided."
    ):
        return LOCATION_REQUEST_ANSWER, None

    result = answer_with_knowledge_graph(
        user_query,
        conversation_context,
        location_context,
        scope,
        query_understanding,
    )
    answer = format_kg_response(result)
    print("\nKnowledge graph response:\n", answer, "\n", flush=True)
    return answer or LLM_ERROR_ANSWER, None


def _apply_location_context_to_understanding(
    query_understanding: dict,
    location_context: str,
) -> None:
    if location_context == "No location context provided.":
        return

    location = query_understanding.setdefault("location", {})
    if not isinstance(location, dict):
        location = {}
        query_understanding["location"] = location

    area_match = re.search(
        r"^User location area:\s*(.+)$",
        location_context,
        flags=re.IGNORECASE,
    )
    if area_match:
        location["type"] = "named_area"
        location["value"] = area_match.group(1).strip()[:160] or None
        location["requires_browser_location"] = False
        return

    if location_context.startswith("User browser coordinates:"):
        location["type"] = "browser_coordinates"
        location["value"] = None
        location["requires_browser_location"] = False


def assess_query_guardrails(
    user_query: str,
    conversation_context: str = "No previous conversation.",
) -> GuardrailDecision:
    scope, scope_message = assess_fnb_scope(user_query, conversation_context)
    query_understanding = None
    if scope == "needs_understanding":
        query_understanding = extract_query_understanding(
            user_query,
            conversation_context,
        )
        scope = query_understanding.get("scope")
        if query_understanding.get("needs_clarification"):
            return GuardrailDecision(
                status="clarification_required",
                scope=scope if scope in {"fnb_customer", "fnb_analyst"} else None,
                message=(
                    query_understanding.get("clarification_question")
                    or "Could you clarify what kind of Food & Beverage result you want?"
                ),
                query_understanding=query_understanding,
            )
        if query_understanding.get("intent") == "unsupported":
            scope = "not_fnb"
            scope_message = "it is outside Food & Beverage"
        elif scope not in {"fnb_customer", "fnb_analyst"}:
            scope = "uncertain"
            scope_message = (
                "Could you clarify how this question relates to an F&B customer "
                "or business decision?"
            )

    if scope == "not_fnb":
        reason = _format_scope_reason(
            scope_message or "This request is outside Food & Beverage."
        )
        return GuardrailDecision(
            status="out_of_scope",
            message=(
                f"I cannot answer this question because {reason}. FoodSight "
                "supports F&B customer and F&B business-analysis questions."
            ),
            query_understanding=query_understanding,
        )
    if scope == "uncertain":
        return GuardrailDecision(
            status="clarification_required",
            message=scope_message,
            query_understanding=query_understanding,
        )

    clarification = assess_clarification_requirement(
        user_query,
        conversation_context,
        scope,
    )
    if clarification:
        return GuardrailDecision(
            status="clarification_required",
            scope=scope,
            message=clarification,
            query_understanding=query_understanding,
        )

    unsupported = assess_capability_support(user_query)
    if unsupported:
        return GuardrailDecision(
            status="unsupported",
            scope=scope,
            message=unsupported,
            query_understanding=query_understanding,
        )

    location_required, detected_location = assess_location_requirement(
        user_query,
        conversation_context,
        scope,
    )
    if query_understanding and location_required:
        location = query_understanding.setdefault("location", {})
        if isinstance(location, dict):
            location["type"] = None
            location["value"] = None
            location["requires_browser_location"] = True
    return GuardrailDecision(
        status="ready",
        scope=scope,
        location_required=location_required,
        detected_location=detected_location,
        query_understanding=query_understanding,
    )


def assess_fnb_scope(
    user_query: str,
    conversation_context: str = "No previous conversation.",
) -> tuple[str, str | None]:
    has_fnb_entity = _contains_phrase(user_query.lower(), FNB_ENTITY_TERMS)
    if has_fnb_entity and _contains_phrase(
        user_query.lower(),
        ANALYST_INTENT_PHRASES,
    ):
        return "fnb_analyst", None
    if has_fnb_entity:
        return "fnb_customer", None

    normalized = " ".join(user_query.lower().strip().split())
    has_fnb_history = _contains_phrase(
        conversation_context.lower(),
        FNB_ENTITY_TERMS,
    )
    if has_fnb_history and (
        _contains_phrase(normalized, FOLLOW_UP_SIGNALS)
        or extract_explicit_location(user_query)
        or _conversation_awaits_location(conversation_context)
    ):
        inherited_scope = (
            "fnb_analyst"
            if _contains_phrase(
                conversation_context.lower(),
                ANALYST_INTENT_PHRASES,
            )
            else "fnb_customer"
        )
        return inherited_scope, None
    return "needs_understanding", None


def assess_clarification_requirement(
    user_query: str,
    conversation_context: str,
    scope: str,
) -> str | None:
    normalized = " ".join(user_query.lower().strip().split())
    has_affordable_intent = _contains_phrase(
        normalized,
        PRICE_INTENT_TERMS["affordable"],
    )
    has_premium_intent = _contains_phrase(
        normalized,
        PRICE_INTENT_TERMS["premium"],
    )
    if has_affordable_intent and has_premium_intent:
        return "Should I prioritize affordable options or premium options?"

    if (
        any(phrase in normalized for phrase in ("which one", "which is better"))
        and conversation_context == "No previous conversation."
    ):
        return "Which restaurants, cafes, or areas would you like me to compare?"

    if normalized in {"recommend food", "suggest food", "recommend a place"}:
        return (
            "What cuisine, venue type, price range, or area do you prefer?"
        )

    return None


def assess_capability_support(user_query: str) -> str | None:
    normalized = " ".join(user_query.lower().strip().split())
    unsupported_fields = [
        label
        for phrase, label in UNSUPPORTED_DATA_TERMS.items()
        if phrase in normalized
    ]
    if not unsupported_fields:
        return None
    fields = ", ".join(sorted(set(unsupported_fields)))
    return (
        f"FoodSight cannot answer this yet because the current knowledge graph "
        f"does not contain {fields} data."
    )


def assess_location_requirement(
    user_query: str,
    conversation_context: str = "No previous conversation.",
    scope: str = "fnb_customer",
) -> tuple[bool, str | None]:
    normalized = " ".join(user_query.lower().strip().split())
    if _has_current_location(normalized):
        return True, None

    if _conversation_awaits_location(conversation_context):
        clean_location = " ".join(user_query.strip().split())
        return False, clean_location[:160] if clean_location else None

    explicit_location = extract_explicit_location(user_query)
    if explicit_location:
        return False, explicit_location
    if re.search(r"(?<!\w)within(?!\w)", normalized):
        return True, None
    if _has_current_location(conversation_context.lower()):
        return True, None

    has_location_intent = _contains_phrase(normalized, LOCATION_SEARCH_PHRASES)
    if scope == "fnb_analyst":
        return False, None
    if has_location_intent:
        return True, None
    return False, None


def format_conversation_context(messages: list[dict[str, str]]) -> str:
    turns = []
    for message in messages[-8:]:
        role = "Assistant" if message["role"] == "assistant" else "User"
        content = " ".join(message["content"].strip().split())
        turns.append(f"{role}: {content[:1200]}")
    return "\n".join(turns) if turns else "No previous conversation."


def extract_explicit_location(user_query: str) -> str | None:
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
    location = match.group(1).strip()
    return (
        None
        if location.lower() in {"here", "me", "my location", "current location"}
        else location
    )


def _has_current_location(text: str) -> bool:
    return _contains_phrase(text, CURRENT_LOCATION_PHRASES)


def _contains_phrase(text: str, phrases: set[str]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text)
        for phrase in phrases
    )


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


def _default_guardrail_message(status: str) -> str:
    messages = {
        "clarification_required": "Could you clarify what you would like to find?",
        "unsupported": (
            "FoodSight does not currently have the graph data needed to answer "
            "that question."
        ),
        "out_of_scope": (
            "FoodSight supports F&B customer and F&B business-analysis questions."
        ),
    }
    return messages.get(status, "I could not process this request.")


def _format_scope_reason(reason: str) -> str:
    cleaned = " ".join(reason.strip().split()).rstrip(" .!?")
    if not cleaned:
        return "it is outside Food & Beverage"

    cleaned = re.sub(
        r"^(?:the|this) (?:question|request|query) is\b",
        "it is",
        cleaned,
        flags=re.IGNORECASE,
    )
    if cleaned.lower().startswith("it is"):
        return f"it is{cleaned[5:]}"
    return cleaned[:1].lower() + cleaned[1:]
