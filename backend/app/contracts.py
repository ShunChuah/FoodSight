"""Data passed between the chat route, the Cypher pipeline and the map."""
from dataclasses import dataclass, field
from typing import Any, Literal

from .services.shared.config import policy

RetrievalStatus = Literal[
    "success",
    "no_results",
    "preview",
    "clarification_required",
    "unsupported",
    "invalid_query",
    "execution_error",
]
MapStatus = Literal["ready", "empty", "unavailable"]
AnswerStatus = Literal[
    "success",
    "fallback",
    "no_results",
    "clarification_required",
    "unsupported",
]


@dataclass(frozen=True)
class GuardrailDecision:
    """The rule-based screen's verdict, made at preflight and reused at send."""

    status: str  # ready | unsupported | out_of_scope
    scope: str | None = None
    message: str | None = None
    location_required: bool = False
    detected_location: str | None = None


@dataclass(frozen=True)
class QueryPlan:
    """A validated Cypher query and its parameters."""

    cypher: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    # RESTAURANT_DETAILS_FIELD when the user asked about one particular restaurant.
    requested_fields: tuple[str, ...] = ()
    result_limit: int = policy("results")["default_limit"]


@dataclass(frozen=True)
class MapPoint:
    latitude: float
    longitude: float

    def to_dict(self) -> dict[str, float]:
        return {"latitude": self.latitude, "longitude": self.longitude}


@dataclass(frozen=True)
class MapBounds:
    south: float
    west: float
    north: float
    east: float

    def to_dict(self) -> dict[str, float]:
        return {"south": self.south, "west": self.west, "north": self.north, "east": self.east}


@dataclass(frozen=True)
class MapFeature:
    feature_id: str
    label: str
    latitude: float
    longitude: float
    properties: dict[str, Any] = field(default_factory=dict)

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "id": self.feature_id,
            "geometry": {"type": "Point", "coordinates": [self.longitude, self.latitude]},
            "properties": {"feature_type": "restaurant", "label": self.label, **self.properties},
        }


@dataclass(frozen=True)
class MapResult:
    """GeoJSON map snapshot saved with the answer."""

    status: MapStatus
    features: tuple[MapFeature, ...] = ()
    center: MapPoint | None = None
    bounds: MapBounds | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "version": 2,
            "map_mode": "restaurant_markers",
            "feature_collection": {
                "type": "FeatureCollection",
                "features": [feature.to_geojson() for feature in self.features],
            },
            "center": self.center.to_dict() if self.center else None,
            "bounds": self.bounds.to_dict() if self.bounds else None,
            "message": self.message,
        }


@dataclass
class RetrievalResult:
    """What the query step found; the answer step and the map read it."""

    status: RetrievalStatus
    query_plan: QueryPlan = field(default_factory=QueryPlan)
    records: list[dict[str, Any]] = field(default_factory=list)
    # The reply itself without rows (an explanation, a question, a decline), or a note shown above the answer.
    message: str | None = None
    map_result: MapResult = field(default_factory=lambda: MapResult(status="empty"))


@dataclass(frozen=True)
class AnswerResult:
    status: AnswerStatus
    text: str
    used_llm: bool = False
