import re
from typing import Any

from ..query_generation.cypher_generation import load_vocabulary
from .answer_text import _and, area_label
from .presentation import distance_label, hours_label, money_label


def _heading(row: dict[str, Any]) -> str:
    return f"**{row['restaurant_name']}**" + (f" – {area_label(row['area'])}" if row.get("area") else "")


CARD_SECTIONS = ("Restaurant highlights", "Opening hours", "Dining options", "Location and contact")
SERVICE_WORDS = {"Delivery": r"\bdeliver", "Takeout": r"\b(?:takeaway|take away|take-away|takeout|tapau)\b",
                 "Dine-in": r"\b(?:dine[- ]?in|eat in)\b", "Reservations": r"\b(?:book\w*|reserv\w*)\b",
                 "Curbside Pickup": r"\b(?:curbside|pick ?up)\b"}
# Malaysian usage on screen; the stored facility names stay as Google gives them.
FACILITY_WORDS = {"Takeout": "Takeaway"}
TIER_LABELS = {"budget": "Budget-friendly", "mid": "Mid-range", "upscale": "Upscale", "luxury": "Luxury"}
SECTION_LABELS = {"Services": "Dining options"}


# Facts outside these sections show only when the question asks for them.
def _profile_card(row: dict[str, Any], fields: tuple[str, ...] | None = None, question: str = "") -> str:
    facts = _card_facts(row)
    if fields is not None:
        asked: dict[str, list[str]] = {}
        named = [name for name, pattern in SERVICE_WORDS.items() if re.search(pattern, question, re.IGNORECASE)]
        if "Services" in fields and named:
            # The services the user named, each with what Google lists: absent is "Not listed", not "No".
            offered = _services(row)
            for name in named:
                shown = FACILITY_WORDS.get(name, name)
                asked[shown] = ["Available" if shown in offered else "Not listed"]
        for _, field, label, text in facts:
            if field == "Services" and field in fields:
                if not named:
                    for name in _services(row):
                        asked[name] = ["Available"]
            elif field in fields:
                asked.setdefault(label or SECTION_LABELS.get(field, field), []).append(text)
        if asked:
            return _heading(row) + "\n" + "\n".join(
                _bullet(label, texts[0] if len(texts) == 1 else _sentence_list(", ".join(
                    [texts[0], *(text.lower() for text in texts[1:])])))
                for label, texts in asked.items())
    lines = [_heading(row)]
    for section in CARD_SECTIONS:
        shown = [(label, text) for place, _, label, text in facts if place == section]
        if shown:
            lines += ["", f"**{section}**", *(_bullet(label, text) for label, text in shown)]
    return "\n".join(lines)


def _bullet(label: str | None, text: str) -> str:
    return f"- {label}: {text}" if label else f"- {text}"


# (section or None, field the question can ask for, label, text) for every fact the row has.
def _card_facts(row: dict[str, Any]) -> list[tuple[str | None, str, str | None, str]]:
    rating, reviews, price = row.get("average_rating"), row.get("review_count"), row.get("average_price")
    guessed = row.get("profile_is_a_guess")
    facts = [
        ("Restaurant highlights", "Rating", "Rating",
         f"{rating:.1f}/5" + (f" ({reviews:,} Google reviews)" if isinstance(reviews, int) else "")
         if isinstance(rating, (int, float)) else None),
        ("Restaurant highlights", "Price", "Estimated price",
         f"around {money_label(price, 'MYR')} per person" if isinstance(price, (int, float)) else None),
        ("Restaurant highlights", "Price", "Price category", TIER_LABELS.get(row.get("price_tier"))),
        ("Restaurant highlights", "Cuisine", "Cuisine", ", ".join(row["cuisines"]) if row.get("cuisines") else None),
        ("Restaurant highlights", "Halal", "Halal", None if guessed else
         {"halal": "Listed as halal", "non-halal": "Not halal"}.get(row.get("halal_status"))),
        ("Restaurant highlights", "Good for", "Suitable for", None if guessed else _sentence_list(row.get("good_for"))),
        ("Restaurant highlights", "Atmosphere", "Atmosphere",
         None if guessed else _sentence_list(row.get("ambiance"))),
        *_hours_facts(row),
        *[("Dining options" if label == "Services" else None, label, None if label == "Services" else label, text)
          for label, text in _facility_groups(row.get("facilities") or [])],
        ("Location and contact", "Address", "Address", clean_address(row.get("address"))),
        ("Location and contact", "Nearest station", "Nearest station", row.get("nearest_station")),
        ("Location and contact", "Distance", "Distance",
         f"about {distance_label(row['distance_m'])} away" if distance_label(row.get("distance_m")) else None),
        ("Location and contact", "Phone", "Phone", row.get("phone")),
        ("Location and contact", "Website", "Website", row.get("website")),
    ]
    return [fact for fact in facts if fact[3]]


def _hours_facts(row: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    hours, is_open, opens_at = row.get("hours_today"), row.get("open_now"), row.get("opens_at")
    if hours == "open 24 hours":
        return [("Opening hours", "Hours", "Today", "Open 24 hours")]
    today = ("Closed today" if isinstance(hours, str) and hours.strip().lower() == "closed"
             else hours_label(hours) if isinstance(hours, str) and hours.strip() else None)
    now = ("Open" if is_open else f"Closed, opens {opens_at}" if is_open is False and opens_at
           else "Closed" if is_open is False else None)
    return [fact for fact in (("Opening hours", "Hours", "Today", today),
                              ("Opening hours", "Hours", "Current status", now)) if fact[3]]


def _sentence_list(value: Any) -> str | None:
    items = [item.strip() for item in str(value or "").split(",") if item.strip()]
    return (_and(items)[:1].upper() + _and(items)[1:]) if items else None


def clean_address(address: Any) -> str | None:
    if not isinstance(address, str) or not address.strip():
        return None
    kept: list[str] = []
    for part in (piece.strip() for piece in address.split(",")):
        text = " ".join(word.capitalize() if word.isalpha() and word.isupper() and len(word) > 2 else word
                        for word in part.split())
        if not text or text.casefold() == "malaysia":
            continue
        if any(char.isalpha() for char in text) and any(text.casefold() in other.casefold() for other in kept):
            continue
        kept.append(text)
    return ", ".join(kept)


FACILITY_GROUPS = {"service": "Services", "meal_type": "Meals", "drinks": "Drinks", "menu": "Menu",
                   "dietary": "Dietary", "amenity": "Amenities", "suitability": "Suitable for",
                   "accessibility": "Accessibility", "parking": "Parking", "payment": "Payment"}


def _services(row: dict[str, Any]) -> list[str]:
    values = load_vocabulary()["columns"]["facility.name"]["values"]
    return [FACILITY_WORDS.get(name, name) for name in row.get("facilities") or []
            if isinstance(values.get(name), dict) and values[name].get("category") == "service"]


def _facility_groups(facilities: list[str], spread: str | None = None) -> list[tuple[str, str]]:
    values = load_vocabulary()["columns"]["facility.name"]["values"]
    grouped: dict[str, list[str]] = {label: [] for label in FACILITY_GROUPS.values()}
    for name in facilities:
        detail = values.get(name)
        category = detail.get("category") if isinstance(detail, dict) else None
        grouped[FACILITY_GROUPS.get(category, "Services")].append(FACILITY_WORDS.get(str(name), str(name)))
    return [pair for label, names in grouped.items() if names
            for pair in ([(label, name) for name in names] if label == spread
                         else [(label, _sentence_list(", ".join(name.lower() for name in names)))])]
