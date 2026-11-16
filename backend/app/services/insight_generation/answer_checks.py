import re
from functools import lru_cache
from typing import Any

from ..query_generation.cypher_generation import load_vocabulary
from ..shared.diagnostics import kg_debug, note_turn
from .presentation import comparison_evidence

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
CLOCK = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\b", re.IGNORECASE)
NOT_CHECKED = {"record_id", "fields"}


def _numbers(text: str) -> list[float]:
    found = []
    for match in NUMBER.findall(CLOCK.sub(" ", text)):
        try:
            found.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return found


# A figure is supported when the prompt holds it, allowing rounding ("about 1,500" for 1,503, "RM36" for RM36.80),
# but not for small decimals such as ratings (4.9 is not 4.8). Small whole numbers ("three places", "PJU 5") pass.
def _supported(sentence: str, known: list[float]) -> bool:
    return all((value.is_integer() and value <= 12)
               or any(abs(value - figure) <= (max(1.0, 0.02 * figure) if figure >= 10 else 0.05) for figure in known)
               for value in _numbers(sentence))


# The answer model explains the figures; a sentence with a figure it was not given is dropped, not shown.
def _checked_payload(payload: Any, known: list[float], streaming: bool = False) -> Any:
    if isinstance(payload, dict):
        return {name: value if name in NOT_CHECKED else _checked_payload(value, known, streaming)
                for name, value in payload.items()}
    if isinstance(payload, list):
        return [_checked_payload(item, known, streaming) for item in payload]
    if not isinstance(payload, str):
        return payload
    sentences = re.split(r"(?<=[.!?])\s+", payload)
    unfinished = sentences.pop() if streaming and sentences and not sentences[-1].rstrip().endswith((".", "!", "?")) \
        else None
    kept = [sentence for sentence in sentences if _supported(sentence, known)]
    if len(kept) < len(sentences) and not streaming:
        dropped = [sentence for sentence in sentences if sentence not in kept]
        kg_debug("Dropped sentences with figures not in the evidence", dropped)
        note_turn(unsupported_figures=dropped)
    return " ".join(kept + ([unfinished] if unfinished else [])).strip()


SUPERLATIVES = {
    "average_price": r"cheapest|lowest (?:average )?price|least expensive|most affordable",
    "average_rating": r"highest[- ]rated|highest rating|best[- ]rated|top[- ]rated|best rating",
    "distance_m": r"closest|nearest(?!\s+(?:station|mrt|lrt|bus))|shortest distance",
    "review_count": r"most[- ]reviewed|most reviews|widest praise",
}
# Words in the cuisine lists that are too common to treat as a named dish.
GENERIC_TERMS = {"local", "bar", "pub", "tea", "juice", "beverages", "bread", "cake", "cakes", "dessert", "pastry",
                 "international", "diner", "southern", "coconut", "chocolate", "fries", "deli", "burger", "sandwich",
                 "continental", "arab", "arabic", "chinese", "taiwanese", "cantonese"}


# Dish and style keywords from the cuisine vocabulary ("Omakase", "Nasi Lemak"), longest first.
@lru_cache(maxsize=1)
def _dish_terms() -> tuple[str, ...]:
    values = load_vocabulary()["columns"]["cuisine.name"]["values"]
    names = [value.lower() for value in values]
    terms = {label.lower() for value, detail in values.items() for label in detail.get("includes", [])
             if label.lower() != str(detail.get("origin_country", "")).lower()
             and not any(label.lower() in name or name in label.lower() for name in names)}
    return tuple(sorted(terms - GENERIC_TERMS, key=len, reverse=True))


def asked_dish(question: str, parameters: dict[str, Any]) -> str | None:
    named = parameters.get("dish")
    if isinstance(named, str) and named.strip():
        return named.strip().lower()
    return next((term for term in _dish_terms() if re.search(rf"\b{re.escape(term)}\b", question, re.IGNORECASE)),
                None)


# Menus are not recorded, so a dish is confirmed only by the place's own name, type or summary.
def serves_dish(row: dict[str, Any], dish: str) -> bool:
    text = " ".join(str(row.get(key) or "") for key in ("restaurant_name", "brand", "restaurant_type", "summary"))
    return bool(re.search(rf"\b{re.escape(dish)}\b", text, re.IGNORECASE))


def dish_note(rows: list[dict[str, Any]], dish: str) -> str | None:
    confirmed = [row["restaurant_name"] for row in rows if serves_dish(row, dish) and row.get("restaurant_name")]
    if not confirmed:
        return (f"I couldn't confirm which places serve {dish}, as my data doesn't include menus, "
                "so these are the closest matches.")
    if len(confirmed) < len(rows):
        return f"Only {_names(confirmed)} clearly offer{'s' if len(confirmed) == 1 else ''} {dish}, " \
               "and the others are close matches."
    return None


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


# Removes claims the evidence cannot back: a dish at a place not shown to serve it, and "cheapest" or
# "highest rated" when the places are tied or the figure is missing.
def supported_claims(payload: Any, rows: list[dict[str, Any]], dish: str | None = None) -> Any:
    if not isinstance(payload, dict):
        return payload
    supported = {item["metric"] for item in comparison_evidence(rows) if len(item["names"]) < len(rows)}
    unsupported = [pattern for metric, pattern in SUPERLATIVES.items() if metric not in supported] if len(rows) > 1 \
        else []
    names = [str(row["restaurant_name"]) for row in rows if row.get("restaurant_name")]
    nobody = dish is not None and not any(serves_dish(row, dish) for row in rows)
    checked = {}
    for key, value in payload.items():
        if key == "restaurants" and isinstance(value, list):
            checked[key] = [_checked_place(item, rows, dish, unsupported, names) for item in value]
        elif isinstance(value, str):
            checked[key] = _claims(value, dish if nobody else None, unsupported, names)
        else:
            checked[key] = value
    return checked


def _checked_place(item: Any, rows: list[dict[str, Any]], dish: str | None, unsupported: list[str],
                   names: list[str]) -> Any:
    if not isinstance(item, dict):
        return item
    match = re.fullmatch(r"R(\d+)", str(item.get("record_id", "")))
    row = rows[int(match[1]) - 1] if match and 0 < int(match[1]) <= len(rows) else {}
    unconfirmed = dish if dish and not serves_dish(row, dish) else None
    return {key: _claims(value, unconfirmed, unsupported, names) if isinstance(value, str) and key != "record_id"
            else value for key, value in item.items()}


def _claims(text: str, dish: str | None, unsupported: list[str], names: list[str]) -> str:
    if unsupported:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        pattern = re.compile(rf"\b(?:{'|'.join(unsupported)})\b", re.IGNORECASE)
        kept = [sentence for sentence in sentences if not pattern.search(sentence)]
        if len(kept) < len(sentences):
            note_turn(unsupported_comparisons=[sentence for sentence in sentences if sentence not in kept])
        text = " ".join(kept)
    if dish:
        text = _without_dish(text, dish, names)
    return text.strip()


def _without_dish(text: str, dish: str, names: list[str]) -> str:
    masked = {f"\x00{index}\x00": name for index, name in enumerate(names) if re.search(re.escape(dish), name, re.I)}
    for token, name in masked.items():
        text = text.replace(name, token)
    text = re.sub(rf"(?:,?\s+(?:like|such as|including|especially))?\s*\b{re.escape(dish)}(?:[- ](?:style|inspired))?",
                  "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b([Aa])n?\s+(?=[aeiouAEIOU])", r"\1n ", text)
    text = re.sub(r"\b([Aa])n\s+(?=[^aeiouAEIOU\W])", r"\1 ", text)
    text = re.sub(r"\s{2,}", " ", re.sub(r"\s+([,.;])", r"\1", text))
    for token, name in masked.items():
        text = text.replace(token, name)
    return text
