"""Map snapshot saved with each answer: one marker per restaurant in the answer."""
from typing import Any

from ...contracts import MapBounds, MapFeature, MapPoint, MapResult
from ..shared.config import policy
from ..shared.messages import response

# Restaurant facts shown in the marker popup.
MAP_PROPERTY_FIELDS = (
    "address", "area", "venue_type", "average_rating", "review_count", "cuisines", "price_tier",
    "average_price", "currency", "phone", "website", "hours_today", "facilities", "distance_m",
)


def build_map_result(records: list[dict[str, Any]]) -> MapResult:
    """Markers for the restaurants in the answer; rows without coordinates (or area rows) are left out."""
    if not records:
        return MapResult(status="empty")
    features, seen, missing_coordinates = [], set(), False
    for record in records:
        latitude = _coordinate(record.get("latitude"), -90, 90)
        longitude = _coordinate(record.get("longitude"), -180, 180)
        label = _text(record.get("restaurant_name"))
        if latitude is None or longitude is None or not label:
            missing_coordinates = missing_coordinates or bool(label)
            continue
        feature_id = _text(str(record.get("restaurant_id") or "")) or f"{label}:{latitude}:{longitude}"
        if (feature_id, latitude, longitude) in seen:
            continue
        seen.add((feature_id, latitude, longitude))
        properties = {key: record[key] for key in MAP_PROPERTY_FIELDS if record.get(key) not in (None, "", [], {})}
        if not properties.get("currency") and "average_price" in properties:
            properties["currency"] = policy("price_matching")["default_currency"]
        features.append(MapFeature(feature_id=feature_id, label=label, latitude=latitude, longitude=longitude,
                                   properties=properties))
    if not features:
        return MapResult(status="unavailable", message=response("maps.missing_coordinates"))
    latitudes = [feature.latitude for feature in features]
    longitudes = [feature.longitude for feature in features]
    return MapResult(
        status="ready",
        features=tuple(features),
        message=response("maps.partial_coordinates") if missing_coordinates else None,
        center=MapPoint(latitude=sum(latitudes) / len(latitudes), longitude=sum(longitudes) / len(longitudes)),
        bounds=MapBounds(south=min(latitudes), west=min(longitudes), north=max(latitudes), east=max(longitudes)),
    )


def _coordinate(value: Any, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        coordinate = float(value)
    except (TypeError, ValueError):
        return None
    return coordinate if minimum <= coordinate <= maximum else None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
