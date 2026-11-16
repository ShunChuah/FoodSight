import json
import logging
import re
from typing import Any

from ...contracts import MapOverlay, QueryPlan
from ..shared.neo4j import execute_cypher

logger = logging.getLogger(__name__)

MAX_AREAS = 10
AREA_BOUNDARIES = "MATCH (a:Area) WHERE a.boundary_geojson IS NOT NULL RETURN a.name AS name, a.boundary_geojson AS boundary"
PLACE_POINTS = """
MATCH (r:Restaurant)-[:LOCATED_IN]->(l:Location)
WHERE r.restaurant_id IN $ids AND l.latitude IS NOT NULL AND l.longitude IS NOT NULL
RETURN l.latitude AS latitude, l.longitude AS longitude
""".strip()
ANCHOR_POINT = """
MATCH (t:Restaurant {restaurant_id: $id})-[:LOCATED_IN]->(l:Location)
RETURN t.name AS name, l.latitude AS latitude, l.longitude AS longitude
LIMIT 1
""".strip()
STUDY_FIGURES = ("restaurants", "competitors", "competitor_share", "area_price")
RADIUS_PARAMETERS = ("radius_m", "default_radius_m")

_boundaries: dict[str, dict] | None = None


class OverlayError(Exception):
    pass


# Area outlines never change between graph builds of a running app, so they are read once.
def _area_boundaries(timeout_seconds: float | None) -> dict[str, dict]:
    global _boundaries
    if _boundaries is None:
        found = _query(AREA_BOUNDARIES, {}, timeout_seconds)
        _boundaries = {row["name"]: json.loads(row["boundary"]) for row in found if row.get("name")}
    return _boundaries


def _query(cypher: str, parameters: dict[str, Any], timeout_seconds: float | None) -> list[dict[str, Any]]:
    result = execute_cypher(cypher, parameters, timeout_seconds=timeout_seconds, purpose="map overlays")
    if result.status != "success":
        raise OverlayError(result.message or "map overlay query failed")
    return result.records


def _label(area: str) -> str:
    match = re.fullmatch(r"(.+?)\s*\((.+)\)", area)
    return f"{match[1]} ({match[2].split(',')[0].strip()})" if match else area


def _area(name: str, boundaries: dict[str, dict], properties: dict[str, Any]) -> MapOverlay | None:
    geometry = boundaries.get(name)
    if not geometry or geometry.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    return MapOverlay(f"area:{name}", "area", _label(name), geometry, properties)


def _figures(row: dict[str, Any], skip: set[str]) -> dict[str, Any]:
    return {key: value for key, value in row.items()
            if key not in skip and isinstance(value, (int, float)) and not isinstance(value, bool)}


def _point(latitude: Any, longitude: Any) -> dict[str, Any] | None:
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return {"type": "Point", "coordinates": [round(float(longitude), 6), round(float(latitude), 6)]}


def study_overlays(areas: list[dict[str, Any]], competitor_ids: list[Any],
                   timeout_seconds: float | None = None) -> list[MapOverlay]:
    boundaries = _area_boundaries(timeout_seconds)
    overlays = []
    for rank, area in enumerate(areas, start=1):
        properties = {"role": area.get("role"), "rank": rank,
                      **{key: area[key] for key in STUDY_FIGURES if area.get(key) is not None}}
        if area.get("show_score") and area.get("score") is not None:
            properties["score"] = area["score"]
        overlay = _area(area["area_name"], boundaries, properties)
        if overlay:
            overlays.append(overlay)
    if competitor_ids:
        points = [[round(row["longitude"], 5), round(row["latitude"], 5)]
                  for row in _query(PLACE_POINTS, {"ids": competitor_ids}, timeout_seconds)]
        if points:
            overlays.append(MapOverlay("density:competitors", "density", "Competitor density",
                                       {"type": "MultiPoint", "coordinates": points}, {"places": len(points)}))
    return overlays


def answer_overlays(plan: QueryPlan, rows: list[dict[str, Any]], *, area_filter: bool,
                    timeout_seconds: float | None = None) -> list[MapOverlay]:
    overlays = []
    compared = [row for row in rows if isinstance(row.get("area_name"), str)]
    searched = list(dict.fromkeys(row["area"] for row in rows if isinstance(row.get("area"), str))) \
        if area_filter else []
    if compared or searched:
        boundaries = _area_boundaries(timeout_seconds)
        found = [_area(row["area_name"], boundaries, {"rank": rank, **_figures(row, {"latitude", "longitude"})})
                 for rank, row in enumerate(compared[:MAX_AREAS], start=1)]
        found += [_area(name, boundaries, {}) for name in searched[:MAX_AREAS]]
        overlays += [overlay for overlay in found if overlay]
    centre = _search_centre(plan, rows, timeout_seconds)
    if centre:
        overlays.append(centre)
    return overlays


def _search_centre(plan: QueryPlan, rows: list[dict[str, Any]], timeout_seconds: float | None) -> MapOverlay | None:
    radius = next((plan.parameters[name] for name in RADIUS_PARAMETERS
                   if isinstance(plan.parameters.get(name), (int, float))), None)
    properties = {"radius_m": radius} if radius else {}
    point = _point(plan.parameters.get("latitude"), plan.parameters.get("longitude"))
    if point:
        return MapOverlay("radius:user", "radius", "Your location", point, properties)
    anchors = list(dict.fromkeys(row["anchor_id"] for row in rows if row.get("anchor_id") is not None))
    if len(anchors) != 1:
        return None
    found = _query(ANCHOR_POINT, {"id": anchors[0]}, timeout_seconds)
    point = _point(found[0].get("latitude"), found[0].get("longitude")) if found else None
    return MapOverlay("radius:anchor", "radius", found[0].get("name") or "Search centre", point, properties) \
        if point else None


# An overlay that cannot be built never costs the answer its markers: the map shows them alone and says so.
def safely(build, *args, **kwargs) -> tuple[list[MapOverlay], bool]:
    try:
        return build(*args, **kwargs), False
    except Exception:  # noqa: BLE001
        logger.warning("Map overlays could not be built", exc_info=True)
        return [], True
