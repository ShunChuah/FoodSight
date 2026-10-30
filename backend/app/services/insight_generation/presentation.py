import math
from typing import Any

COMPARISON_METRICS = {
    "average_price": ("lowest_average_price", min, "lowest average price"),
    "average_rating": ("highest_rating", max, "highest rating"),
    "distance_m": ("closest", min, "shortest distance"),
    "review_count": ("most_reviews", max, "most reviews"),
}
PRICE_TIER_LABELS = {"budget": "budget-friendly", "mid": "mid-range", "premium": "premium"}


def distance_label(value: Any) -> str | None:
    if not _number(value):
        return None
    if value < 25:
        return "less than 50 m"
    step = 50 if value < 500 else 100
    metres = math.floor(value / step + 0.5) * step if value < 1000 else value
    return f"{metres} m" if metres < 1000 else f"{metres / 1000:.1f} km"


def money_label(value: Any, currency: str | None) -> str | None:
    if not _number(value):
        return None
    prefix = "RM" if currency == "MYR" else f"{currency} " if currency else ""
    return prefix + (f"{value:.0f}" if value == int(value) else f"{value:.2f}")


def price_tier_label(value: Any) -> str | None:
    if not value:
        return None
    tier = str(value).strip().lower()
    return PRICE_TIER_LABELS.get(tier, tier.replace("_", " "))


def comparison_evidence(rows: list[dict]) -> list[dict]:
    result = []
    for field, (key, choose, label) in COMPARISON_METRICS.items():
        values = [row.get(field) for row in rows]
        if len(rows) < 2 or not all(_finite(value) for value in values):
            continue
        if field == "average_price" and (len({row.get("currency") for row in rows}) != 1 or not rows[0].get("currency")):
            continue
        best = choose(values)
        winners = [row["restaurant_name"] for row in rows if row[field] == best and row.get("restaurant_name")]
        result.append({"metric": field, "key": key, "description": label, "names": winners, "value": best,
                       "tied": len(winners) > 1})
    return result


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _number(value: Any) -> bool:
    return _finite(value) and value >= 0
