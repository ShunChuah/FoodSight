import re
from typing import Any

from ..shared.config import policy
from .graph_reads import DETAIL_COLUMNS
from .presentation import comparison_evidence, distance_label, hours_label, money_label
from .ranking import opens_at

TIME_WORDS = re.compile(r"\b(?:open\w*|clos\w*|hours?|now|today|tonight|tomorrow|late|early|morning|night|"
                        r"breakfast|brunch|lunch|dinner|supper|\d{1,2}\s*(?:am|pm))\b", re.IGNORECASE)
NOON = 12 * 60


# Today's hours are left out of a list unless the question is about time, or the place only opens at noon or later.
def _restaurant_evidence(rows: list[dict[str, Any]], card: bool = False, hours: bool = True) -> list[dict[str, Any]]:
    comparisons = comparison_evidence(rows)
    evidence = []
    for row in rows:
        opens = opens_at(row.get("hours_today"))
        timed = hours or (opens is not None and opens >= NOON)
        item = {
            **{key: value for key, value in row.items() if key not in DETAIL_COLUMNS and key != "distance_m"},
            "restaurant_name": row.get("restaurant_name"),
            "area": row.get("area"),
            "distance_display": distance_label(row.get("distance_m")),
            "average_rating": row.get("average_rating"),
            "review_count": row.get("review_count"),
            "few_reviews": True if isinstance(row.get("average_rating"), (int, float))
            and (row.get("review_count") or 0) < policy("ranking")["rated_minimum_reviews"] else None,
            "price_display": (f"around {money_label(row['average_price'], 'MYR')} on average"
                              if isinstance(row.get("average_price"), (int, float)) else None),
            "price_tier": row.get("price_tier"),
            "cuisines": row.get("cuisines"),
            "venue_type": row.get("venue_type"),
            "restaurant_type": row.get("restaurant_type"),
            "halal_status": _halal_evidence(row),
            "good_for": row.get("good_for"),
            "ambiance": row.get("ambiance"),
            "service_style": row.get("service_style") if row.get("service_style") != "unknown" else None,
            "facilities": row.get("facilities"),
            "google_summary": row.get("summary"),
            "nearest_station": row.get("nearest_station") if card else None,
            "profile_is_a_guess": row.get("profile_is_a_guess"),
            "hours_today": hours_label(row.get("hours_today")) if timed else None,
            "open_now": row.get("open_now") if timed else None,
            "opens_at": row.get("opens_at") if timed else None,
            "comparison_facts": [item["description"] for item in comparisons if row.get("restaurant_name") in item["names"]],
        }
        if card:
            item.update(phone=row.get("phone"), address=row.get("address"), website=row.get("website"),
                        weekly_hours={day: hours_label(hours) for day, hours in (row.get("weekly_hours") or {}).items()}
                        or None)
        evidence.append({key: value for key, value in item.items() if value not in (None, "", [])})
    return evidence


# A halal status guessed from the name alone carries its caveat, so the answer never states it as fact.
def _halal_evidence(row: dict[str, Any]) -> str | None:
    status = row.get("halal_status")
    if not status or status == "unknown":
        return None
    return f"{status} (guessed from the name only, not confirmed)" if row.get("profile_is_a_guess") else status


def _group_evidence(row: dict[str, Any]) -> dict[str, Any]:
    evidence = {key: value for key, value in row.items() if value not in (None, "", [])}
    shares = [key for key, value in evidence.items() if key.endswith("share_pct") and isinstance(value, (int, float))]
    pj = next((key for key in shares if key.startswith("pj_")), None)
    area = next((key for key in shares if not key.startswith("pj_")), None)
    if pj and area:
        difference = evidence[area] - evidence[pj]
        evidence["compared_with_pj"] = ("about the same as PJ overall" if abs(difference) < 1
                                        else "more crowded than PJ overall" if difference > 0
                                        else "less crowded than PJ overall")
    return evidence


def _business_evidence(row: dict[str, Any]) -> dict[str, Any]:
    evidence = _restaurant_evidence([row])[0]
    return {key: value for key, value in evidence.items() if key not in ("hours_today", "open_now", "opens_at")}
