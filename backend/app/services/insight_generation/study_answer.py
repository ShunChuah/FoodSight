import re
from typing import Any, Callable

from .answer_text import TIER_WORDS, _and, _sentence, _text_of, area_label, clean_opening
from .market_study import settings as market_settings
from .presentation import money_label

STUDY_NOTE = ("*Note: restaurant counts and Google reviews show existing market activity, not customer numbers or "
              "profitability, and prices are estimated averages.*")
MIX_WORDS = {"casual_restaurant": "casual restaurants", "fast_food": "fast-food outlets", "bar_pub": "bars and pubs",
             "fine_dining": "fine-dining restaurants", "bakery": "bakeries", "hawker_stall": "hawker stalls"}
# Compared in code, because the model compares numbers unreliably.
STUDY_MEASURES = (("restaurants", max, "largest restaurant market"), ("reviews", max, "most Google reviews"),
                  ("competitor_share", min, "lowest competitor share"), ("competitors", min, "fewest direct competitors"),
                  ("competitors", max, "most direct competitors"),
                  ("competitor_rating", min, "weakest-rated competitors"),
                  ("competitor_rating", max, "strongest-rated competitors"),
                  ("competitor_reviews_avg", max, "busiest competitors"),
                  ("area_price", max, "highest average spending"), ("area_price", min, "lowest average spending"))


def _money(value: Any) -> str | None:
    return money_label(value, "MYR") if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _study_highlights(rows: list[dict[str, Any]]) -> list[list[str]]:
    highlights: list[list[str]] = [[] for _ in rows]
    for key, pick, label in STUDY_MEASURES:
        values = [(row[key], index) for index, row in enumerate(rows) if isinstance(row.get(key), (int, float))]
        if len(values) < 2 or len({value for value, _ in values}) == 1:
            continue
        best = pick(value for value, _ in values)
        highlights[next(index for value, index in values if value == best)].append(label)
    return highlights


def _mix(kinds: list[str]) -> str | None:
    words = [MIX_WORDS.get(kind, kind.replace("_", " ") + "s") for kind in kinds if kind and kind != "other"]
    return _and(words) or None


NEARBY_SHOWN = 3


def _nearby_customers(places: dict[str, int] | None) -> str | None:
    nearby = market_settings()["nearby"]
    kinds = sorted((kind for kind, count in (places or {}).items() if count and kind in nearby),
                   key=lambda kind: -places[kind])[:NEARBY_SHOWN]
    return _and([f"{places[kind]} {PLURALS.get(kind, kind + 's') if places[kind] > 1 else kind} "
                 f"({nearby[kind]['customers']})" for kind in kinds]) or None


def _against_pj(share: float | None, pj: float | None) -> str | None:
    if share is None or pj is None:
        return None
    return "about the same as PJ overall" if abs(share - pj) < 1 else (
        "lower than PJ overall" if share < pj else "higher than PJ overall")


# Price from the concept's competitors only. Fallback order: same positioning, the area's, then all of PJ.
def _benchmark_price(row: dict[str, Any]) -> float | None:
    if row["target_price"]:
        return row["target_price"]
    if row["price_position"] == "premium":
        return row["premium_competitor_price"] or row["competitor_price_high"] or row["pj"].get("competitor_price")
    if row["price_position"] == "budget":
        return row["budget_competitor_price"] or row["competitor_price_low"] or row["pj"].get("competitor_price")
    return row["competitor_price"] or row["pj"].get("competitor_price")


def _competitor_text(place: dict[str, Any]) -> str:
    facts = [f"{place['average_rating']:.1f}" if isinstance(place.get("average_rating"), (int, float)) else None,
             f"{place['review_count']:,} reviews" if isinstance(place.get("review_count"), int) else None,
             f"around {_money(place.get('average_price'))}" if _money(place.get("average_price")) else None]
    facts = [fact for fact in facts if fact]
    return place.get("restaurant_name", "") + (f" ({', '.join(facts)})" if facts else "")


def _study_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence = []
    for row, highlights in zip(rows, _study_highlights(rows)):
        pj = row["pj"]
        prices = (f"{_money(row['competitor_price_low'])} to {_money(row['competitor_price_high'])}, around "
                  f"{_money(row['competitor_price'])} on average" if row["competitor_price"] is not None else None)
        item = {
            "area": area_label(row["area_name"]), "role": row["role"],
            "opportunity score out of 100": row["score"] if row["show_score"] else None,
            "user's objective": row["objective"], "user's price position": row["price_position"],
            "user's target price": _money(row["target_price"]),
            "restaurants": row["restaurants"], "Google reviews": row["reviews"],
            "reviews per restaurant": row["reviews_per_restaurant"], "restaurant mix": _mix(row["restaurant_mix"]),
            "likely customers (AI-inferred)": _and(row["customers"]) or None,
            "nearby places and who they could bring": _nearby_customers(row["nearby_places"]),
            "direct competitors": row["competitors"], "competitor share %": row["competitor_share"],
            "PJ competitor share %": pj["competitor_share"],
            "competition compared with PJ": _against_pj(row["competitor_share"], pj["competitor_share"]),
            "average competitor rating": row["competitor_rating"],
            "competitor reviews in total": row["competitor_reviews"],
            "average reviews per competitor": row["competitor_reviews_avg"],
            "competitor prices (estimates)": prices,
            "area average price (estimate)": _money(row["area_price"]),
            "price benchmark for a new outlet": _money(_benchmark_price(row)),
            "premium competitors' average price": _money(row["premium_competitor_price"]),
            "budget competitors' average price": _money(row["budget_competitor_price"]),
            "competitor price tiers": {TIER_WORDS.get(tier, tier): count
                                       for tier, count in row["competitor_tiers"].items()} or None,
            "main competitors": [_competitor_text(place) for place in row["main_competitors"]] or None,
            "highest-rated competitor": _competitor_text(row["top_rated"]) if row["top_rated"] else None,
            "lowest-rated competitor": _competitor_text(row["lowest_rated"]) if row["lowest_rated"] else None,
            "negative share of sampled competitor reviews %": row["negative_share"],
            "sampled competitor reviews": row["sentiment_sample"] if row["negative_share"] is not None else None,
            "stands out for": highlights or None,
        }
        evidence.append({key: value for key, value in item.items() if value not in (None, "", [], {})})
    return evidence


# Every figure is written here, never by the model.
def render_area_analysis(rows: list[dict[str, Any]], payload: dict | None = None, partial: bool = False) -> str:
    if payload is not None and not _text_of(payload.get("answer")):
        raise ValueError("invalid_response_json")
    payload = payload or {}
    notes: dict[int, dict] = {}
    for item in payload.get("areas") or []:
        match = re.fullmatch(r"A(\d+)", str(item.get("record_id", ""))) if isinstance(item, dict) else None
        if match and 1 <= int(match[1]) <= len(rows):
            notes[int(match[1])] = item
    payload = _measured(payload)
    answer = _text_of(payload.get("answer"))
    # Keep the briefing's standard opening; clean_opening would strip it.
    if not answer.lower().startswith("based on the available market data"):
        answer = clean_opening(answer)
    lines = []
    lines.append(_bold_area(_sentence(answer), rows[0]) if answer else _study_summary(rows))
    shown = rows[:max(notes, default=0)] if partial else rows
    if shown:
        lines += ["", "**Recommended locations**"]
    for index, row in enumerate(shown, 1):
        note = notes.get(index, {})
        lines += ["", f"**{index}. {area_label(row['area_name'])} — {row['role']}**"]
        if _text_of(note.get("summary")):
            lines.append(_sentence(_text_of(note["summary"])))
        lines += [f"- **{name}:** {value}." for name, value in _study_bullets(row)]
        if _text_of(note.get("closing")):
            lines += ["", _sentence(_text_of(note["closing"]))]
    done = not partial or "recommendation" in payload
    if done:
        lines += ["", "**Overall comparison**", "", *_study_table(rows)]
    if done and _text_of(payload.get("recommendation")):
        lines += ["", "**My recommendation**", _sentence(_text_of(payload["recommendation"]))]
    elif done and not payload:
        lines += ["", STUDY_NEXT_STEP]
    if done:
        lines += ["", STUDY_NOTE]
    return "\n".join(lines)


EXPOSURE_CLAIMS = (
    (re.compile(r"\bmaximi[sz]e (?:its |your |the )?(?:exposure|visibility)\b", re.IGNORECASE),
     "reach a larger existing market"),
    (re.compile(r"\bmaximum (?:existing )?(?:market )?(?:exposure|visibility)\b", re.IGNORECASE),
     "a larger existing market"),
    (re.compile(r"\bhigh[- ]exposure\b", re.IGNORECASE), "larger-market"),
    (re.compile(r"\b(?:choice|pick|option) for exposure\b", re.IGNORECASE), "choice for a larger existing market"),
)


# Tones down overclaiming wording, e.g. "maximum exposure" -> "a larger existing market".
def _measured(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {key: value if key == "record_id" else _measured(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_measured(item) for item in payload]
    if isinstance(payload, str):
        for pattern, plain in EXPOSURE_CLAIMS:
            payload = pattern.sub(plain, payload)
    return payload


STUDY_NEXT_STEP = ("**Next step:** check rents, pedestrian traffic, visibility and competitor locations at specific "
                   "sites before deciding.")


# Without the answer model: what the figures themselves show, worked out here.
def _study_summary(rows: list[dict[str, Any]]) -> str:
    name = lambda row: area_label(row["area_name"])  # noqa: E731
    if len(rows) == 1:
        return f"Here is how {name(rows[0])} compares with Petaling Jaya overall, based on the available figures."
    largest = max(rows, key=lambda row: row["restaurants"])
    shares = [row for row in rows if row["competitor_share"] is not None]
    lowest = min(shares, key=lambda row: row["competitor_share"]) if shares else None
    text = f"Based on the available figures, {name(largest)} has the largest restaurant market among the areas compared"
    if lowest and lowest is not largest:
        text += f", while {name(lowest)} has the lowest share of direct competitors"
    return text + "."


def _bold_area(answer: str, row: dict[str, Any]) -> str:
    if "**" in answer:
        return answer
    name = str(row.get("area_name") or "")
    for candidate in dict.fromkeys(filter(None, [area_label(name), name.split(" (")[0], _area_place(name)])):
        found = re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", answer)
        if found:
            return answer[:found.start()] + f"**{found[0]}**" + answer[found.end():]
    return answer


def _area_place(name: str) -> str | None:
    match = re.fullmatch(r"(.+?)\s*\((.+)\)", name)
    return match[2].split(",")[0].strip() if match else None


# Which facts lead depends on what the user is after; at most STUDY_FACTS of them, the main competitors last.
STUDY_FACTS = 5
FACT_ORDER = {
    "balanced": ("market", "competition", "competitor_price", "rating"),
    "exposure": ("market", "competition", "competitor_price", "rating"),
    "low_competition": ("competition", "market", "competitor_price", "rating"),
    "price": ("area_price", "competitor_prices", "competition", "market"),
    "strongest_market": ("competition", "competitor_reviews", "rating", "market"),
}


def _study_bullets(row: dict[str, Any]) -> list[tuple[str, str]]:
    pj, competitors = row["pj"], row["competitors"]
    facts: dict[str, tuple[str, str] | None] = {
        "market": ("Market size", f"{row['restaurants']} restaurants and {row['reviews']:,} Google reviews"),
        "competition": ("Competition", (
            f"{competitors} direct competitor{'s' if competitors != 1 else ''}, {row['competitor_share']:g}% of local "
            "restaurants" + (f" (PJ: {pj['competitor_share']:g}%)" if pj.get("competitor_share") is not None else "")
        ) if competitors else "No matching direct competitors are currently recorded in this area"),
        "competitor_price": ("Average competitor price", f"{_money(row['competitor_price'])} per person (estimated)")
        if row["competitor_price"] is not None else
        ("Average area price", f"{_money(row['area_price'])} per person (estimated)")
        if row["area_price"] is not None else None,
        "area_price": ("Average area price", f"{_money(row['area_price'])} per person (estimated)")
        if row["area_price"] is not None else None,
        "competitor_prices": ("Competitor prices", (
            f"{_money(row['competitor_price_low'])} to {_money(row['competitor_price_high'])}, around "
            f"{_money(row['competitor_price'])} on average (estimated)"
            if row["competitor_price_low"] != row["competitor_price_high"]
            else f"around {_money(row['competitor_price'])} (estimated)")) if row["competitor_price"] is not None else None,
        "rating": ("Average rating", f"{row['competitor_rating']:.1f} among {row['rated_competitors']} competitor"
                   f"{'s' if row['rated_competitors'] != 1 else ''} with rating data")
        if row["competitor_rating"] is not None else None,
        "competitor_reviews": ("Competitor reviews", f"{row['competitor_reviews']:,} in total")
        if row["competitor_reviews"] is not None else None,
        "nearby": ("Nearby", _nearby_customers(row["nearby_places"]))
        if row.get("customer_focus") and row["nearby_places"] else None,
    }
    goal = "price" if row["price_position"] in ("premium", "budget") or row["target_price"] else row["objective"]
    order = ("nearby", *FACT_ORDER.get(goal, FACT_ORDER["balanced"])) if row.get("customer_focus") \
        else FACT_ORDER.get(goal, FACT_ORDER["balanced"])
    shown = [facts[key] for key in order if facts.get(key)][:STUDY_FACTS - 1]
    rivals = [place["restaurant_name"] for place in row["main_competitors"]]
    if rivals:
        shown.append(("Main competitors" if len(rivals) > 1 else "Main competitor", _and(rivals)))
    return shown


def _study_table(rows: list[dict[str, Any]]) -> list[str]:
    def cell(value: Any, text: Callable[[Any], str]) -> str:
        return text(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else "N/A"

    measures = [
        ("Restaurants", lambda row: cell(row.get("restaurants"), lambda value: f"{value:,}")),
        ("Direct competitors", lambda row: cell(row.get("competitors"), lambda value: f"{value:,}")),
        ("Competitor share", lambda row: cell(row.get("competitor_share"), lambda value: f"{value:g}%")),
        ("Total Google reviews", lambda row: cell(row.get("reviews"), lambda value: f"{value:,}")),
        ("Average area price", lambda row: cell(row.get("area_price"), _money)),
    ]
    names = [_area_place(row["area_name"]) or row["area_name"] for row in rows]
    table = ["| Criteria | " + " | ".join(names) + " |", "|---|" + "---:|" * len(rows)]
    return table + ["| " + name + " | " + " | ".join(value(row) for row in rows) + " |" for name, value in measures
                    if any(value(row) != "N/A" for row in rows)]


PLURALS = {"university": "universities"}
