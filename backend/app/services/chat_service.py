import re

from .knowledge_graph_service import answer_with_knowledge_graph, format_kg_response
from .llm_service import classify_fnb_query


LLM_ERROR_ANSWER = (
    "I could not generate the Cypher query because the LLM service is unavailable. "
    "Please check the backend logs and LLM configuration."
)
LOCATION_REQUEST_ANSWER = (
    "I need a location to answer that recommendation. Please tell me the specific "
    "area or enable location permission before retrying."
)
SAMPLE_MAP_IMAGE_URL = "https://docs.maptiler.com/leaflet/examples/nextjs/map.png"

FNB_KEYWORDS = {
    "breakfast", "brunch", "cafe", "cafes", "coffee", "cuisine", "dinner",
    "dining", "drink", "drinks", "eat", "food", "lunch", "meal", "menu",
    "price", "pricing", "restaurant", "restaurants", "supper",
}
FNB_FOLLOW_UP_KEYWORDS = {
    "ambiance", "budget", "cheap", "cheaper", "cheapest", "facilities",
    "facility", "luxury", "premium",
}
FOLLOW_UP_PHRASES = (
    "and that one", "compare them", "how about", "what about",
    "which is better", "which one", "which ones",
)
CURRENT_LOCATION_KEYWORDS = (
    "near me", "nearby", "around me", "around here", "close to me",
    "closest", "nearest", "walking distance", "current location",
)
LOCATION_QUERY_KEYWORDS = {
    "find", "recommend", "show me", "suggest", "where can i",
    "where should i",
}
LOCATION_TARGET_KEYWORDS = {
    "breakfast", "brunch", "cafe", "cafes", "coffee shop", "dinner", "eat",
    "food", "lunch", "meal", "place to eat", "places to eat", "restaurant",
    "restaurants", "supper",
}
INFORMATIONAL_PREFIXES = (
    "define ", "explain ", "how does ", "how do ", "tell me about ",
    "what does ", "what is ", "what are the differences", "why ",
)


def generate_assistant_response(
    messages: list[dict[str, str]],
    location_context: str = "No location context provided.",
    location_permission_denied: bool = False,
) -> tuple[str, str | None]:
    user_query = messages[-1]["content"] if messages else ""
    conversation_context = format_conversation_context(messages[:-1])
    is_fnb, scope_reason = assess_fnb_query(user_query, conversation_context)

    if not is_fnb:
        return (
            f"I cannot answer this question because {scope_reason}. "
            "FoodSight only supports Food & Beverage questions about restaurants, "
            "cafes, cuisines, dining areas, reviews, pricing, and F&B market insights.",
            None,
        )
    if location_permission_denied:
        return LOCATION_REQUEST_ANSWER, None

    result = answer_with_knowledge_graph(
        user_query,
        conversation_context,
        location_context,
    )
    answer = format_kg_response(result)
    print("\nKnowledge graph response:\n", answer, "\n", flush=True)
    return answer or LLM_ERROR_ANSWER, SAMPLE_MAP_IMAGE_URL


def assess_fnb_query(
    user_query: str,
    conversation_context: str = "No previous conversation.",
) -> tuple[bool, str | None]:
    if LOCATION_REQUEST_ANSWER in conversation_context:
        return True, None
    if _contains_terms(user_query, FNB_KEYWORDS):
        return True, None

    normalized = " ".join(user_query.lower().strip().split())
    has_fnb_history = _contains_terms(conversation_context, FNB_KEYWORDS)
    if has_fnb_history and (
        any(phrase in normalized for phrase in FOLLOW_UP_PHRASES)
        or _contains_terms(normalized, FNB_FOLLOW_UP_KEYWORDS)
        or extract_explicit_location(user_query)
    ):
        return True, None
    return classify_fnb_query(user_query, conversation_context)


def has_deterministic_fnb_signal(user_query: str) -> bool:
    return _contains_terms(user_query, FNB_KEYWORDS)


def assess_location_requirement(
    user_query: str,
    conversation_context: str = "No previous conversation.",
) -> tuple[bool, str | None]:
    if LOCATION_REQUEST_ANSWER in conversation_context:
        clean_location = " ".join(user_query.strip().split())
        return False, clean_location[:160] if clean_location else None

    normalized = " ".join(user_query.lower().strip().split())
    if _has_current_location(normalized):
        return True, None

    explicit_location = extract_explicit_location(user_query)
    if explicit_location:
        return False, explicit_location
    if re.search(r"(?<!\w)within(?!\w)", normalized):
        return True, None
    if normalized.startswith(INFORMATIONAL_PREFIXES):
        return False, None
    if _has_current_location(conversation_context.lower()):
        return True, None

    has_location_intent = _contains_phrase(normalized, LOCATION_QUERY_KEYWORDS)
    has_location_target = _contains_phrase(normalized, LOCATION_TARGET_KEYWORDS)
    return has_location_intent and has_location_target, None


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
    return any(
        re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text)
        for keyword in CURRENT_LOCATION_KEYWORDS
    )


def _contains_phrase(text: str, phrases: set[str]) -> bool:
    return any(
        re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text)
        for phrase in phrases
    )


def _contains_terms(text: str, terms: set[str]) -> bool:
    return bool(set(re.findall(r"[a-z]+", text.lower())) & terms)
