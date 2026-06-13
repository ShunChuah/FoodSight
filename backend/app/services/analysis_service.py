from typing import Any


def analyze_kg_rows(
    query_understanding: dict | None,
    rows: list[dict[str, Any]],
) -> str | None:
    if not query_understanding or not rows:
        return None

    if query_understanding.get("scope") != "fnb_analyst":
        return None

    analysis = query_understanding.get("analysis") or {}
    mode = analysis.get("mode") if isinstance(analysis, dict) else None
    if mode == "pricing_analysis":
        return _analyze_pricing(rows)
    if mode == "area_opportunity":
        return _analyze_area_opportunity(rows)
    if mode == "competitor_density":
        return _analyze_competitor_density(rows)
    if mode == "market_gap":
        return _analyze_market_gap(rows)
    if mode == "customer_segment_analysis":
        return _analyze_customer_segments(rows)
    if mode == "location_risk_analysis":
        return _analyze_location_risk(rows)
    if mode == "menu_gap_analysis":
        return _analyze_menu_gap(rows)
    return None


def _analyze_pricing(rows: list[dict[str, Any]]) -> str | None:
    best = _first_row_with(rows, "avg_price")
    if not best:
        return None

    avg_price = _number(best.get("avg_price"))
    min_price = _number(best.get("min_price"))
    max_price = _number(best.get("max_price"))
    sample_count = _number(best.get("sample_count"))
    category = _text(
        best.get("item_category")
        or best.get("category")
        or best.get("dish_category")
        or best.get("item")
    ) or "matching dessert items"
    if avg_price is None:
        return None

    lower = avg_price * 0.9
    upper = avg_price * 1.1
    evidence = [f"- Average observed price for {category}: {_money(avg_price)}"]
    if min_price is not None and max_price is not None:
        evidence.append(
            f"- Observed price range: {_money(min_price)} to {_money(max_price)}"
        )
    if sample_count is not None:
        evidence.append(f"- Sample size: {int(sample_count)} menu items")

    return "\n".join(
        [
            "Analyst pricing summary:",
            f"Recommended starting range: {_money(lower)} to {_money(upper)}.",
            "Why:",
            *evidence,
            "Use the lower end for an entry/budget position and the upper end "
            "for a more premium dessert position.",
        ]
    )


def _analyze_area_opportunity(rows: list[dict[str, Any]]) -> str | None:
    ranked = _rank_area_rows(rows)
    if not ranked:
        return None

    top = ranked[0]
    area = _area_name(top)
    return "\n".join(
        [
            "Analyst area-opportunity summary:",
            f"Best candidate area: {area}.",
            _area_reason(top),
            "Ranking is based only on available graph signals: restaurant "
            "counts, matching competitors, saturation ratio, ratings, reviews, "
            "population density, and cluster density.",
        ]
    )


def _analyze_competitor_density(rows: list[dict[str, Any]]) -> str | None:
    ranked = _rank_by_saturation(rows)
    if not ranked:
        return None

    top = ranked[0]
    return "\n".join(
        [
            "Analyst competitor-density summary:",
            f"Highest competitive pressure: {_area_name(top)}.",
            _area_reason(top),
        ]
    )


def _analyze_market_gap(rows: list[dict[str, Any]]) -> str | None:
    ranked = _rank_area_rows(rows)
    if not ranked:
        return None

    top = ranked[0]
    return "\n".join(
        [
            "Analyst market-gap summary:",
            f"Most promising gap: {_area_name(top)}.",
            _area_reason(top),
            "A stronger gap means fewer matching competitors relative to the "
            "available demand or density signals in the graph.",
        ]
    )


def _analyze_customer_segments(rows: list[dict[str, Any]]) -> str | None:
    ranked = sorted(
        rows,
        key=lambda row: (
            _number(row.get("restaurant_count")) or 0,
            _number(row.get("avg_review_count")) or 0,
            _number(row.get("avg_rating")) or 0,
        ),
        reverse=True,
    )
    if not ranked:
        return None

    top = ranked[0]
    segment = _text(
        top.get("segment")
        or top.get("target_segment")
        or top.get("dining_experience")
        or top.get("business_style")
        or top.get("ambiance")
    ) or "the strongest observed segment"
    count = _number(top.get("restaurant_count"))
    rating = _number(top.get("avg_rating"))
    reviews = _number(top.get("avg_review_count"))

    evidence = []
    if count is not None:
        evidence.append(f"{int(count)} restaurants")
    if rating is not None:
        evidence.append(f"{rating:.2f} average rating")
    if reviews is not None:
        evidence.append(f"{reviews:.0f} average reviews")

    return "\n".join(
        [
            "Analyst customer-segment summary:",
            f"Strongest observed segment: {segment}.",
            "Evidence: " + ", ".join(evidence) + "." if evidence else
            "Evidence: available BusinessProfile signals ranked this segment highest.",
        ]
    )


def _analyze_location_risk(rows: list[dict[str, Any]]) -> str | None:
    ranked = _rank_location_risk(rows)
    if not ranked:
        return None

    top = ranked[0]
    return "\n".join(
        [
            "Analyst location-risk summary:",
            f"Highest risk area: {_area_name(top)}.",
            _area_reason(top),
            "Risk is based only on available graph signals such as saturation, "
            "competitor count, restaurant density, rating, and review activity.",
        ]
    )


def _analyze_menu_gap(rows: list[dict[str, Any]]) -> str | None:
    ranked = _rank_menu_gap(rows)
    if not ranked:
        return None

    top = ranked[0]
    category = _text(
        top.get("item_category")
        or top.get("category")
        or top.get("menu_category")
        or top.get("dish")
        or top.get("dish_name")
    ) or "the top-ranked menu category"
    dish_count = _number(top.get("dish_count"))
    restaurant_count = _number(top.get("restaurant_count"))
    avg_price = _number(top.get("avg_price"))

    evidence = []
    if dish_count is not None:
        evidence.append(f"{int(dish_count)} matching dishes")
    if restaurant_count is not None:
        evidence.append(f"{int(restaurant_count)} restaurants offering it")
    if avg_price is not None:
        evidence.append(f"{_money(avg_price)} average price")

    return "\n".join(
        [
            "Analyst menu-gap summary:",
            f"Most promising menu gap: {category}.",
            "Evidence: " + ", ".join(evidence) + "." if evidence else
            "Evidence: available dish/menu signals ranked this category highest.",
        ]
    )


def _rank_area_rows(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        saturation = _number(row.get("saturation_ratio"))
        competitors = _number(row.get("matching_competitors"))
        total = _number(row.get("total_restaurants"))
        if saturation is None and competitors is not None and total:
            saturation = competitors / total

        demand = _average_available(
            _number(row.get("area_population_density")),
            _number(row.get("population_density")),
            _number(row.get("avg_density_score")),
            _number(row.get("avg_cluster_density")),
            _number(row.get("avg_area_rating")),
            _number(row.get("avg_area_reviews")),
            _number(row.get("avg_area_review_count")),
        )
        opportunity = _number(row.get("opportunity"))
        if opportunity is None:
            opportunity = (1 - (saturation or 0)) + (demand or 0)
        row["_analysis_score"] = opportunity
        scored.append(row)
    return sorted(
        scored,
        key=lambda item: item.get("_analysis_score") or 0,
        reverse=True,
    )


def _rank_by_saturation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        saturation = _number(row.get("saturation_ratio"))
        competitors = _number(row.get("matching_competitors"))
        total = _number(row.get("total_restaurants"))
        if saturation is None and competitors is not None and total:
            saturation = competitors / total
        row["_analysis_score"] = saturation or 0
        scored.append(row)
    return sorted(
        scored,
        key=lambda item: item.get("_analysis_score") or 0,
        reverse=True,
    )


def _rank_location_risk(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        saturation = _number(row.get("saturation_ratio"))
        competitors = _number(row.get("matching_competitors"))
        total = _number(row.get("total_restaurants"))
        if saturation is None and competitors is not None and total:
            saturation = competitors / total
        density = _number(row.get("avg_density_score") or row.get("avg_cluster_density"))
        reviews = _number(row.get("avg_area_review_count") or row.get("avg_area_reviews"))
        row["_analysis_score"] = (
            (saturation or 0)
            + ((competitors or 0) / 100)
            + ((density or 0) / 100)
            + ((reviews or 0) / 1000)
        )
        scored.append(row)
    return sorted(
        scored,
        key=lambda item: item.get("_analysis_score") or 0,
        reverse=True,
    )


def _rank_menu_gap(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        dish_count = _number(row.get("dish_count"))
        restaurant_count = _number(row.get("restaurant_count"))
        rating = _number(row.get("avg_rating"))
        reviews = _number(row.get("avg_review_count"))
        row["_analysis_score"] = (
            (1 / (1 + (restaurant_count or 0)))
            + ((rating or 0) / 10)
            + ((reviews or 0) / 1000)
            + (1 / (1 + (dish_count or 0)))
        )
        scored.append(row)
    return sorted(
        scored,
        key=lambda item: item.get("_analysis_score") or 0,
        reverse=True,
    )


def _area_reason(row: dict[str, Any]) -> str:
    total = _number(row.get("total_restaurants"))
    competitors = _number(row.get("matching_competitors"))
    saturation = _number(row.get("saturation_ratio"))
    rating = _number(row.get("avg_area_rating"))
    reviews = _number(row.get("avg_area_reviews") or row.get("avg_area_review_count"))
    density = _number(row.get("avg_density_score") or row.get("avg_cluster_density"))

    parts = []
    if total is not None:
        parts.append(f"{int(total)} total restaurants")
    if competitors is not None:
        parts.append(f"{int(competitors)} matching competitors")
    if saturation is not None:
        parts.append(f"{saturation:.2f} saturation ratio")
    if rating is not None:
        parts.append(f"{rating:.2f} average rating")
    if reviews is not None:
        parts.append(f"{reviews:.0f} average reviews")
    if density is not None:
        parts.append(f"{density:.2f} density score")
    return "Evidence: " + ", ".join(parts) + "." if parts else "Evidence: available graph metrics ranked this area highest."


def _first_row_with(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    return next((row for row in rows if _number(row.get(key)) is not None), None)


def _area_name(row: dict[str, Any]) -> str:
    return _text(row.get("candidate_area") or row.get("area") or row.get("name")) or "the top-ranked area"


def _average_available(*values: float | None) -> float | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _money(value: float) -> str:
    return f"RM {value:.2f}"
