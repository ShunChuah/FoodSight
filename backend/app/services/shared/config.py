# Search policy from query_assumptions.json, read once per process: restart after editing it.

import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROXIMITY_MODES = {"radius_search", "nearest_search", "walking_proxy", "distance_measurement", "delivery_search"}


def get_query_assumptions_path() -> Path:
    path = Path(os.getenv("QUERY_ASSUMPTIONS_PATH", "app/knowledge_graph/query_assumptions.json"))
    return path if path.is_absolute() else Path(__file__).resolve().parents[3] / path


@lru_cache(maxsize=1)
def load_query_assumptions() -> dict:
    path = get_query_assumptions_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _validate(data)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(f"Invalid query assumptions at {path}: {exc}") from exc
    return data


def policy(section: str) -> dict:
    return load_query_assumptions()["policy"][section]


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate(data: dict) -> None:
    if data["version"] != 1:
        raise ValueError("unsupported version")
    settings = data["policy"]
    city = settings["coverage"]["city"]
    if not isinstance(city, str) or not city.strip():
        raise ValueError("coverage.city must name a supported city")

    alternatives = settings["alternatives"]
    if not isinstance(alternatives["enabled"], bool):
        raise ValueError("alternatives.enabled must be boolean")
    for key, maximum in (("maximum_attempts", 5), ("result_limit", 25)):
        if not _positive_int(alternatives[key]) or alternatives[key] > maximum:
            raise ValueError(f"alternatives.{key} must be between 1 and {maximum}")
    budget = alternatives["time_budget_seconds"]
    if isinstance(budget, bool) or not isinstance(budget, (float, int)) or not 0 < budget <= 4:
        raise ValueError("alternatives.time_budget_seconds must be in (0, 4]")

    limits = settings["results"]
    for key in ("default_limit", "discovery_limit", "maximum_limit"):
        if not _positive_int(limits[key]):
            raise ValueError(f"policy.results.{key} must be a positive integer")
    if not max(limits["default_limit"], limits["discovery_limit"]) <= limits["maximum_limit"] <= 25:
        raise ValueError("result defaults must fit maximum_limit (safety ceiling: 25)")

    proximity = settings["proximity"]
    radii = ("default_radius_meters", "delivery_radius_meters", "walking_radius_meters",
             "minimum_radius_meters", "maximum_radius_meters")
    for key in radii:
        if not _positive_int(proximity[key]):
            raise ValueError(f"policy.proximity.{key} must be a positive integer")
    low, high = proximity["minimum_radius_meters"], proximity["maximum_radius_meters"]
    for value in [proximity[key] for key in radii[:3]] + list(proximity["venue_radius_meters"].values()):
        if not low <= value <= high <= 50000:
            raise ValueError("radius defaults must fit configured bounds (safety ceiling: 50000m)")
    steps = alternatives["automatic_radius_steps_meters"]
    if not steps or any(not _positive_int(v) or not low <= v <= high for v in steps) or steps != sorted(set(steps)):
        raise ValueError("alternatives.automatic_radius_steps_meters must increase within proximity bounds")
    modes = proximity["modes"]
    if set(modes) != PROXIMITY_MODES:
        raise ValueError("proximity.modes must define all supported spatial operations")
    if any(not isinstance(mode.get("terms"), list) or not mode["terms"]
           or any(not isinstance(term, str) or not term.strip() for term in mode["terms"]) for mode in modes.values()):
        raise ValueError("proximity mode terms must be nonempty strings")
    if not 1 <= modes["nearest_search"]["default_limit"] <= limits["maximum_limit"]:
        raise ValueError("nearest_search.default_limit must fit result bounds")

    ranking = settings["ranking"]
    if ranking["default_direction"] not in {"asc", "desc"}:
        raise ValueError("unsupported default ranking direction")
    minimum = ranking.get("rated_minimum_reviews", 0)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
        raise ValueError("ranking.rated_minimum_reviews must be a whole number of reviews")

    currency = settings["price_matching"]["default_currency"]
    if currency is not None and (not isinstance(currency, str) or len(currency) != 3 or not currency.isascii()
                                 or not currency.isalpha() or not currency.isupper()):
        raise ValueError("price_matching.default_currency must be an uppercase currency code or null")
