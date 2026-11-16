from typing import Any

from ...contracts import MapResult, QueryPlan
from .map_result import build_map_result
from .overlays import answer_overlays, safely, study_overlays


def answer_map(plan: QueryPlan, rows: list[dict[str, Any]], *, area_filter: bool,
               timeout_seconds: float | None = None) -> MapResult:
    overlays, failed = safely(answer_overlays, plan, rows, area_filter=area_filter, timeout_seconds=timeout_seconds)
    return build_map_result(rows, overlays, failed)


def study_map(areas: list[dict[str, Any]], competitor_ids: list[Any], places: list[dict[str, Any]],
              timeout_seconds: float | None = None) -> MapResult:
    overlays, failed = safely(study_overlays, areas, competitor_ids, timeout_seconds=timeout_seconds)
    return build_map_result(places, overlays, failed)
