import re
from typing import Any

from .answer_checks import CLOCK
from .answer_evidence import TIME_WORDS
from .answer_prompts import CARD_FIELDS
from .answer_text import _and, _sentence, _without_markers, _without_technical, area_label, clean_opening
from .presentation import distance_label, hours_label, money_label
from .restaurant_card import FACILITY_WORDS, SERVICE_WORDS, _profile_card, _services


def _render_model_answer(payload: dict | None, rows: list[dict[str, Any]], card: bool = False,
                         question: str = "", compare: bool = False) -> str:
    if not payload or not isinstance(payload.get("introduction"), str) or not payload["introduction"].strip():
        raise ValueError("invalid_response_json")
    descriptions = {}
    for item in payload.get("restaurants") or []:
        text = item.get("best_for" if compare else "description") if isinstance(item, dict) else None
        if isinstance(text, str):
            match = re.fullmatch(r"R(\d+)", str(item.get("record_id", "")))
            if match and 1 <= int(match.group(1)) <= len(rows):
                descriptions[int(match.group(1))] = text
    conclusion = payload.get("conclusion") if isinstance(payload.get("conclusion"), str) else ""
    if card:
        introduction = _direct_answer(clean_opening(payload["introduction"].strip()), question)
        introduction = _without_technical(introduction, f"Here's what I have on {rows[0]['restaurant_name']}.")
        introduction = _on_topic(introduction, rows[0], question) or _service_answer(rows[0], question) or \
            f"Here's what I have on {rows[0]['restaurant_name']}."
        conclusion = _on_topic(_without_sources(conclusion), rows[0], question)
        fields = _card_fields(payload.get("fields"), question)
        return render_restaurants(rows, introduction, descriptions, conclusion, card, fields, question=question)
    conclusion = _without_sources(conclusion)
    if compare:
        introduction = clean_opening(_without_sources(payload["introduction"].strip()))
        introduction = _without_technical(introduction, "Here's how they compare.")
        return render_restaurants(rows, introduction, descriptions, conclusion, compare=True)
    introduction = clean_opening(_without_sources(payload["introduction"].strip()),
                                 "Here are a few places you might like.")
    return render_restaurants(rows, introduction, descriptions, conclusion)


def render_restaurants(rows: list[dict[str, Any]], introduction: str, descriptions: dict[int, str],
                       conclusion: str = "", card: bool = False, fields: tuple[str, ...] | None = None,
                       compare: bool = False, question: str = "") -> str:
    if card:
        body = _profile_card(rows[0], fields, question)
        keep = conclusion and conclusion.strip() and not _repeats_card(conclusion, rows[0])
        conclusion = _sentence(conclusion) if keep else ""
        answered = YES_NO_QUESTION.match(question or "") and not introduction.startswith("Here's what I have on")
        if fields is not None and answered:
            parts = [_without_markers(introduction), _without_markers(conclusion or "")]
            return "\n\n".join(part for part in parts if part and part.strip())
        if fields is None:
            heading, _, sections = body.partition("\n")
            ending = _worth_visiting(conclusion) if conclusion else ""
            parts = [heading, _without_markers(introduction), sections.strip(), _without_markers(ending)]
            return "\n\n".join(part for part in parts if part and part.strip())
    elif compare:
        body = "\n\n".join(_compare_entry(row, descriptions.get(index)) for index, row in enumerate(rows, 1))
        conclusion = f"**My recommendation:** {_sentence(conclusion)}" if conclusion and conclusion.strip() else ""
    else:
        body = "\n".join(_list_entry(row, descriptions.get(index)) for index, row in enumerate(rows, 1))
    parts = [_without_markers(introduction), body, _without_markers(conclusion or "")]
    return "\n\n".join(part for part in parts if part and part.strip())


# "Mixue or Chagee?" keeps each brand's most-reviewed branch, in the order named.
# "Mixue SS2 or Mixue PJU 10" names branches, so every branch stays.
def _brand_branches(rows: list[dict[str, Any]], places: list[list[str]] | None = None) -> list[dict[str, Any]]:
    places = places or []
    leads = [words[0].casefold() for words in places if words]
    if len(leads) != len(set(leads)):
        return rows

    def brand(row: dict[str, Any]) -> str:
        label = f"{row.get('restaurant_name') or ''} {row.get('brand') or ''}".casefold()
        named = next((index for index, words in enumerate(places)
                      if all(word.casefold() in label for word in words)), None)
        return f"named:{named}" if named is not None else \
            str(row.get("restaurant_name") or "").split(" - ")[0].strip().casefold()

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(brand(row), []).append(row)
    picked = []
    for branches in groups.values():
        best = max(branches, key=lambda row: row.get("review_count") or 0)
        picked.append({**best, "most_reviewed_branch": True} if len(branches) > 1 else best)
    return picked


def _worth_visiting(text: str) -> str:
    text = re.sub(r"^worth visiting if:?\s*", "", text.strip(), flags=re.IGNORECASE)
    return f"**Worth visiting if:** {text[:1].upper() + text[1:]}"


def _compare_entry(row: dict[str, Any], best_for: str | None) -> str:
    area = area_label(row.get("area"))
    lines = [f"**{row['restaurant_name']}" + (f" — {area}" if area else "") + "**"
             + (" *(most-reviewed PJ branch)*" if row.get("most_reviewed_branch") else "")]
    if isinstance(row.get("average_rating"), (int, float)):
        reviews = f" ({row['review_count']:,} Google reviews)" if isinstance(row.get("review_count"), int) else ""
        lines.append(f"- Rating: {row['average_rating']:.1f}/5{reviews}")
    if isinstance(row.get("average_price"), (int, float)):
        lines.append(f"- Estimated price: around {money_label(row['average_price'], 'MYR')} per person")
    if distance_label(row.get("distance_m")):
        lines.append(f"- Distance: about {distance_label(row['distance_m'])} away")
    if best_for and best_for.strip():
        text = best_for.strip().rstrip(".")
        lines.append(f"- Best for: {text[:1].upper() + text[1:]}")
    return "\n".join(lines)


def _list_entry(row: dict[str, Any], description: str | None) -> str:
    area = area_label(row.get("area"))
    label = f"{row['restaurant_name']} — {area}" if area else row["restaurant_name"]
    label += " (alternative pick)." if row.get("alternative") else "."
    text = _sentence(description) if description and description.strip() else _fact_sentence(row)
    return f"- **{label}** {text}".rstrip()


def _fact_sentence(row: dict[str, Any]) -> str:
    facts = []
    if isinstance(row.get("average_rating"), (int, float)):
        reviews = f" from {row['review_count']:,} reviews" if isinstance(row.get("review_count"), int) else ""
        facts.append(f"rated {row['average_rating']:.1f}{reviews}")
    if isinstance(row.get("average_price"), (int, float)):
        facts.append(f"around {money_label(row['average_price'], 'MYR')} per person")
    if distance_label(row.get("distance_m")):
        facts.append(f"about {distance_label(row['distance_m'])} away")
    if not facts:
        return ""
    return "It's " + (", ".join(facts[:-1]) + " and " + facts[-1] if len(facts) > 1 else facts[0]) + "."


ASKED_FIELDS = (
    (r"\b(?:book|booking|reserv\w*|table)\b", ("Services", "Phone")),
    (r"\b(?:open|close[sd]?|hours?|time|today|tonight|now)\b", ("Hours",)),
    (r"\b(?:halal|pork|muslim)\b", ("Halal", "Cuisine")),
    (r"\b(?:phone|call|contact|number)\b", ("Phone",)),
    (r"\b(?:where|address|location|located|direction|get there)\b", ("Address", "Distance")),
    (r"\b(?:price|cost|expensive|cheap|budget|how much)\b", ("Price",)),
    (r"\b(?:rating|rated|reviews?|good|worth)\b", ("Rating", "About")),
    (r"\b(?:deliver\w*|takeaway|takeout|tapau|dine[- ]?in|drive)\b", ("Services",)),
    (r"\bpark\w*", ("Parking",)),
    (r"\b(?:card|cash|pay\w*|contactless|e-?wallet)\b", ("Payment",)),
    (r"\b(?:lrt|mrt|ktm|train|station|public transport)\b", ("Nearest station",)),
    (r"\b(?:website|menu|instagram|online)\b", ("Website",)),
    (r"\b(?:kids?|family|families|children|wheelchair|accessible)\b", ("Good for", "Accessibility")),
)


YES_NO_QUESTION = re.compile(r"^\W*(?:is|are|am|can|could|do|does|did|will|would|should|has|have|any|may)\b", re.IGNORECASE)
LEADING_YES_NO = re.compile(r"^(?:yes|no)\b\s*[,—–:-]?\s*", re.IGNORECASE)
SOURCE_PHRASES = re.compile(r"\s*\b(?:from|in|based on|according to) (?:the|my) (?:(?:available|provided) )?"
                            r"(?:evidence|data|details|information|info)"
                            r"(?: I have)?\b", re.IGNORECASE)


def _without_sources(text: str) -> str:
    text = SOURCE_PHRASES.sub("", text or "")
    return re.sub(r",\s*(?=[.;:!?,]|$)", "", text)


CONTACT_WORDS = re.compile(r"\b(?:phone|call|contact|number|whatsapp)\b", re.IGNORECASE)


# The card already shows hours and phone, so the prose mentions them only when the question asks.
def _on_topic(text: str, row: dict[str, Any], question: str) -> str:
    phone = re.sub(r"\D", "", str(row.get("phone") or ""))
    asked = _card_fields(None, question) or ()
    timed = bool(TIME_WORDS.search(question)) or "Hours" in asked
    contact = bool(CONTACT_WORDS.search(question)) or "Phone" in asked

    def off(sentence: str) -> bool:
        return ((not timed and bool(CLOCK.search(sentence)))
                or (not contact and (bool(CONTACT_WORDS.search(sentence))
                                     or (len(phone) >= 7 and phone[-7:] in re.sub(r"\D", "", sentence)))))

    return " ".join(sentence for sentence in re.split(r"(?<=[.!?])\s+", text or "") if not off(sentence)).strip()


def _service_answer(row: dict[str, Any], question: str) -> str | None:
    named = [name for name, pattern in SERVICE_WORDS.items() if re.search(pattern, question, re.IGNORECASE)]
    if not named:
        return None
    offered = _services(row)
    words = [FACILITY_WORDS.get(name, name) for name in named]
    listed = [word for word in words if word in offered]
    name = row["restaurant_name"]
    if len(listed) == len(words):
        return f"Yes, {name} lists {_and([word.lower() for word in words])}."
    if not listed:
        return f"{name} doesn't list {_and([word.lower() for word in words])}, so it's best to check with them."
    return f"{name} lists {_and([word.lower() for word in listed])}, but not the rest."


def _direct_answer(text: str, question: str) -> str:
    text = _without_sources(text)
    if not YES_NO_QUESTION.match(question or "") and LEADING_YES_NO.match(text):
        rest = LEADING_YES_NO.sub("", text, count=1)
        text = rest[:1].upper() + rest[1:] if rest else text
    return text


GENERAL_REQUEST = re.compile(r"\b(?:tell me (?:more )?about|more (?:about|info\w*|details?)|details?|info\w* (?:on|about)|"
                             r"what(?:'s| is) .+ like|describe|overview)\b", re.IGNORECASE)


def _card_fields(chosen: Any, question: str) -> tuple[str, ...] | None:
    if GENERAL_REQUEST.search(question):
        return None
    asked = tuple(dict.fromkeys(field for pattern, fields in ASKED_FIELDS
                                if re.search(pattern, question, re.IGNORECASE) for field in fields))
    if asked:
        return asked
    if isinstance(chosen, list):
        if any(str(item).strip().casefold() == "all" for item in chosen):
            return None
        valid = tuple(dict.fromkeys(item for item in chosen if item in CARD_FIELDS))
        if valid:
            return valid
    return None


def _repeats_card(tip: str, row: dict[str, Any]) -> bool:
    text = tip.casefold()
    hours = str(hours_label(row.get("hours_today")) or "").casefold()
    price = money_label(row["average_price"], "MYR") if isinstance(row.get("average_price"), (int, float)) else None
    repeated = [
        bool(hours) and any(part.strip() in text for part in re.split(r"[-–,]", hours) if part.strip()),
        bool(price) and price.casefold() in text,
        isinstance(row.get("average_rating"), (int, float)) and f"{row['average_rating']:g}" in text,
        sum(str(name).casefold() in text for name in row.get("facilities") or []) >= 2,
    ]
    return any(repeated)


def _restaurant_fallback(rows: list[dict[str, Any]], card: bool, question: str = "", compare: bool = False) -> str:
    introduction = (f"Here's what I have on {rows[0]['restaurant_name']}:" if card
                    else "Here's how they compare:" if compare else "Here are a few places you could try:")
    return render_restaurants(rows, introduction, {}, card=card, fields=_card_fields(None, question) if card else None,
                              compare=compare, question=question)
