# Rule-based screen before any LLM call: off-topic requests and food data the graph does not have.

import re
from dataclasses import dataclass
from functools import lru_cache

from ..shared.messages import response
from ..shared.text import contains_phrase, normalize_query_text
from .cypher_generation import load_vocabulary

FNB_ENTITY_TERMS = {
    "bakery", "beverage", "beverages", "boba", "breakfast", "brunch",
    "cafe", "cafes", "coffee", "craving", "cuisine", "dessert", "desserts",
    "dinner", "dining", "dish", "dishes", "drink", "drinks", "eat", "fastfood", "food",
    "hungry", "lunch", "meal", "menu", "restaurant", "restaurants", "supper",
    "want to drink", "want to eat", "what should i eat", "what to eat",
}

NON_FNB_TERMS = {
    "cryptocurrency", "flight", "football", "hotel", "movie", "movies",
    "politics", "president", "programming", "python", "stock market",
    "weather",
}

_NON_FNB_TOPICS = "|".join(re.escape(term) for term in sorted(NON_FNB_TERMS))
CLEAR_NON_FNB_REQUEST = re.compile(
    r"^(?:please\s+)?(?:(?:(?:tell|teach) me about|explain|discuss|"
    r"what is|what are|what's|who is|help me with)\s+)?(?:the\s+)?"
    rf"(?:{_NON_FNB_TOPICS})(?:\s+(?:today|now|please))?[.!?]*$"
)
WEATHER_REQUEST = re.compile(
    r"^(?:please\s+)?(?:(?:what(?:'s| is)|how(?:'s| is))\s+(?:the\s+)?weather"
    r"|(?:check|tell me about|show me|give me)\s+(?:the\s+)?weather|weather)"
    r"(?:[.!?]*$|\s+(?:today|tomorrow|now|forecast|like|in|at|near|around)\b)"
)

UNSUPPORTED_CAPABILITY_PATTERNS = (
    (r"\brecipes?\b", "recipes"),
    (r"\bhow\s+to\s+(?:cook|make|prepare)\b", "cooking instructions"),
    (r"\bingredients?\b", "ingredients"),
    (r"\b(?:calories?|nutrition|nutritional)\b", "nutrition information"),
    (r"\b(?:allergens?|allergies)\b", "allergen information"),
    (r"\brevenue\b", "revenue"),
    (r"\bprofit\b", "profit"),
    (r"\bsales forecast\b", "sales forecasts"),
    (r"\bmonthly sales\b", "monthly sales"),
    (r"\bopening cost\b", "opening costs"),
    (r"\boperating cost\b", "operating costs"),
    (r"\brental cost\b", "rental costs"),
    (r"\bstartup cost\b", "startup costs"),
    (r"\bbudget\s+to\s+open\b", "startup budget"),
    (r"\bcalculate\s+(?:the\s+)?budget\b", "startup budget"),
    (r"\bhow\s+much\s+(?:budget|money|capital)\b", "startup budget"),
    (r"\bstartup\s+budget\b", "startup budget"),
    (r"\bstarting\s+budget\b", "startup budget"),
    (r"\bhow\s+much\s+(?:can|could|does|do|will|would)\b.*\b(?:make|earn)\b", "revenue"),
    (r"\bfoot\s*traffic\b|\bfootfall\b|\bhow\s+busy\b", "foot traffic"),
)
NO_FOOD_WORD_NEEDED = {"foot traffic"}


@dataclass(frozen=True)
class ScopeDecision:
    status: str
    scope: str | None = None
    reason: str | None = None


def classify_query_scope(user_query: str, conversation_context: str = "No previous conversation.") -> ScopeDecision:
    normalized = normalize_query_text(user_query)
    if CLEAR_NON_FNB_REQUEST.fullmatch(normalized) or WEATHER_REQUEST.match(normalized):
        return ScopeDecision(status="out_of_scope")
    fnb_signal = has_fnb_signal(user_query)
    unsupported = _unsupported_capabilities(normalized)
    scope = _fnb_scope(normalized, conversation_context, fnb_signal)
    if unsupported and (fnb_signal or NO_FOOD_WORD_NEEDED.intersection(unsupported)):
        return ScopeDecision(status="unsupported", scope=scope,
                             reason=response("errors.unsupported_capability", capabilities=", ".join(unsupported)))
    # Missing keywords are not evidence that the request is unrelated: the model decides.
    return ScopeDecision(status="supported", scope=scope or "fnb")


def has_fnb_signal(text: str) -> bool:
    return contains_phrase(normalize_query_text(text), FNB_ENTITY_TERMS)


@lru_cache(maxsize=1)
def _food_terms() -> re.Pattern:
    terms = {"food", "eat", "eats", "drink", "drinks", "dish", "dishes", "meal", "meals", "dinner", "lunch", "breakfast"}
    for column in load_vocabulary()["columns"].values():
        for value, detail in column["values"].items():
            terms.add(value.replace("_", " "))
            terms.update(detail.get("includes", []) if isinstance(detail, dict) else [])
    pattern = "|".join(sorted((re.escape(term.casefold()) for term in terms if len(term) > 2), key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{pattern})(?!\w)")


def about_food(text: str) -> bool:
    return has_fnb_signal(text) or bool(_food_terms().search(text.casefold()))


def _fnb_scope(normalized: str, conversation_context: str, fnb_signal: bool) -> str | None:
    if not fnb_signal:
        normalized = normalize_query_text(" ".join(
            line.removeprefix("User:") for line in conversation_context.splitlines() if line.startswith("User:")))
        if not contains_phrase(normalized, FNB_ENTITY_TERMS):
            return None
    return "fnb"


def _unsupported_capabilities(normalized: str) -> list[str]:
    return sorted({label for pattern, label in UNSUPPORTED_CAPABILITY_PATTERNS if re.search(pattern, normalized)})
