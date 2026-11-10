import re
from typing import Any

TIER_WORDS = {"budget": "budget", "mid": "mid-range", "upscale": "upscale", "luxury": "luxury"}


TECHNICAL_WORDS = re.compile(
    r"\b(?:graph|vocabular\w*|schema|cypher|node|field|column)s?\b|\b[A-Z]\w+\.\w+\b|\$\w+"
    r"|\b[a-z]+_[a-z_]+\b",
    re.IGNORECASE)
SEARCH_MECHANICS = re.compile(
    r"\b(?:pattern|fuzzy|amenity_type|section(?: code)?|area names?|as the area|starting with|"
    r"radius you|filters?|quer(?:y|ied)|database|dataset|operational|status|results?|returned|required|"
    r"search(?:ed|ing)?|no area filter|whole city|treated|(?:options|info|information) (?:I|we) have|"
    r"I (?:picked|chose|selected|pulled|included|highlighted|focused on))\b", re.IGNORECASE)


SEARCH_OPENING = re.compile(
    r"^(?:Assuming|I took|I treated|I assumed|I interpreted|I matched|I searched|I limited|I used|I returned|"
    r"I(?:'m| am) (?:treating|assuming)|Based on|Using)\b[^,;:.—–]*(?:[,;:—–]|\.(?:\s|$))\s*"
    r"(?:(?:and|so|but)\s+)?", re.IGNORECASE)


def clean_opening(text: str, fallback: str | None = None) -> str:
    match = SEARCH_OPENING.match(text)
    if match:
        rest = text[match.end():].lstrip()
        text = rest[:1].upper() + rest[1:] if rest else text
    if fallback is not None and (SEARCH_MECHANICS.search(text) or TECHNICAL_WORDS.search(text)):
        return fallback
    return text


def _and(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else items[0] if items else ""


def _earlier_chat(conversation_context: str) -> str:
    if conversation_context and conversation_context != "No previous conversation.":
        return f"Earlier in this chat (for context only):\n{conversation_context[-1500:]}\n\n"
    return ""


def _text_of(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def area_label(area: Any) -> Any:
    match = re.fullmatch(r"(.+?)\s*\((.+)\)", area) if isinstance(area, str) else None
    return f"{match[1]} ({match[2].split(',')[0].strip()})" if match else area


def _without_technical(text: str, fallback: str) -> str:
    kept = [sentence for sentence in re.split(r"(?<=[.!?])\s+", text) if not TECHNICAL_WORDS.search(sentence)]
    return " ".join(kept).strip() or fallback


def _sentence(text: str) -> str:
    text = _without_markers(" ".join(text.split()).replace("**", ""))
    return text if text.endswith((".", "!", "?")) else text + "."


def _without_markers(answer: str) -> str:
    cleaned = re.sub(r"\s*\[R\d+\]", "", answer)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned).strip()
    return re.sub(r";\s+([a-z])", lambda match: ". " + match[1].upper(), cleaned)
