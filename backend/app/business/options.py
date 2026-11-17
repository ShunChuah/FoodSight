"""The lists the Register Business form picks from, read from the backend's copy of
src/reference/categories.json (app/knowledge_graph/categories.json, kept identical to the
pipeline's), so the form, the backend and the pipeline's validator always use the same values.
A value added to categories.json appears in the form after a backend restart."""

import json
from functools import lru_cache
from pathlib import Path

CATEGORIES_PATH = Path(__file__).resolve().parents[1] / "knowledge_graph" / "categories.json"

# The statuses a business can register with (restaurant.business_status), in the form's words.
REGISTRABLE_STATUSES = {"OPERATIONAL": "Open now", "FUTURE_OPENING": "Opening soon"}
# "unknown" means the AI could not tell; the business always can, so it is not offered.
NOT_OFFERED = {"unknown"}
PROFILE_COLUMNS = ("restaurant_type", "business_style", "service_style", "target_segment", "ambiance")


@lru_cache(maxsize=None)
def columns() -> dict:
    with open(CATEGORIES_PATH, encoding="utf-8") as f:
        data = json.load(f)["columns"]
    missing = [s for s in REGISTRABLE_STATUSES if s not in data["restaurant.business_status"]["values"]]
    if missing:
        raise RuntimeError(f"restaurant.business_status in {CATEGORIES_PATH} lost {', '.join(missing)}")
    return data


def _definition(detail) -> str:
    return detail["definition"] if isinstance(detail, dict) else detail


def label(value: str) -> str:
    """A list value as the form shows it: hawker_stall -> "Hawker stall"."""
    words = value.replace("_", " ")
    return words[:1].upper() + words[1:]


def choices(column: str) -> list[dict]:
    """[{value, label, definition}] of a list, without the values not offered."""
    return [{"value": value, "label": label(value), "definition": _definition(detail)}
            for value, detail in columns()[column]["values"].items() if value not in NOT_OFFERED]


def allowed(column: str) -> set[str]:
    return {choice["value"] for choice in choices(column)}


def most(column: str) -> int:
    """How many values a pick-many list allows (its max)."""
    return columns()[column].get("max", 1)


def facility_categories() -> dict[str, str]:
    """{facility name: its category} (facility.name)."""
    return {name: detail["category"] for name, detail in columns()["facility.name"]["values"].items()}


def facility_groups() -> list[dict]:
    """The facilities grouped by category, in the file's order: [{key, title, items}]."""
    names = facility_categories()
    return [
        {"key": key, "title": label(key),
         "items": [{"value": name, "label": name} for name, category in names.items() if category == key]}
        for key in columns()["facility.category"]["values"]
    ]


def cuisines() -> list[dict]:
    return [{"value": name, "label": name, "definition": _definition(detail), "category": detail.get("category")}
            for name, detail in columns()["cuisine.name"]["values"].items()]


def form_options(city: str) -> dict:
    """Everything the form needs: the lists, their limits and the city."""
    statuses = columns()["restaurant.business_status"]["values"]
    return {
        "restaurantTypes": choices("business_profile.restaurant_type"),
        "businessStyles": choices("business_profile.business_style"),
        "serviceStyles": choices("business_profile.service_style"),
        "targetSegments": choices("business_profile.target_segment"),
        "ambiances": choices("business_profile.ambiance"),
        "businessStatuses": [{"value": value, "label": text, "definition": _definition(statuses[value])}
                             for value, text in REGISTRABLE_STATUSES.items()],
        "cuisines": cuisines(),
        "facilityGroups": facility_groups(),
        "limits": {
            "cuisines": most("cuisine.name"),
            "targetSegments": most("business_profile.target_segment"),
            "ambiance": most("business_profile.ambiance"),
        },
        "city": city,
    }
