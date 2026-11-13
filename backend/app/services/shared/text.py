import re


def normalize_query_text(value: str) -> str:
    return " ".join(value.lower().strip().split())


def contains_phrase(text: str, phrases: set[str]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) for phrase in phrases)
