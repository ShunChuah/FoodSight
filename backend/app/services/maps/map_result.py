from typing import Any

from ...contracts import MapBounds, MapFeature, MapOverlay, MapPoint, MapResult
from ..shared.config import policy
from ..shared.messages import response

MAP_PROPERTY_FIELDS = (
    "address", "area", "venue_type", "average_rating", "review_count", "cuisines", "price_tier",
    "average_price", "currency", "phone", "website", "hours_today", "facilities", "distance_m",
    "restaurant_type", "weekly_hours", "summary", "halal_status",
)


def build_map_result(records: list[dict[str, Any]], overlays: list[MapOverlay] | tuple = (),
                     overlay_failed: bool = False) -> MapResult:
    if not records and not overlays:
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
    if not features and not overlays:
        return MapResult(status="unavailable", message=response("maps.missing_coordinates"))
    notes = [response("maps.partial_coordinates")] if missing_coordinates else []
    if overlay_failed:
        notes.append(response("maps.overlays_unavailable"))
    points = [(feature.longitude, feature.latitude) for feature in features] or         [point for overlay in overlays for point in _positions(overlay.geometry.get("coordinates"))]
    longitudes, latitudes = [point[0] for point in points], [point[1] for point in points]
    return MapResult(
        status="ready",
        features=tuple(features),
        overlays=tuple(overlays),
        message=" ".join(notes) or None,
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


def _positions(coordinates: Any) -> list[tuple[float, float]]:
    if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2 and all(
            isinstance(value, (int, float)) for value in coordinates[:2]):
        return [(float(coordinates[0]), float(coordinates[1]))]
    if isinstance(coordinates, (list, tuple)):
        return [point for item in coordinates for point in _positions(item)]
    return []
