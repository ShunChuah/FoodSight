import json
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Callable

from ...contracts import AnswerResult
from ..query_generation.cypher_generation import load_vocabulary
from ..shared.diagnostics import kg_debug
from ..shared.llm import LLMServiceError
from .answer_checks import _checked_payload, _numbers
from .answer_evidence import _business_evidence, _group_evidence
from .answer_model import _model_answer
from .answer_prompts import ANALYSIS_FORMAT, ANALYST_INSTRUCTIONS, AREAS_FORMAT
from .answer_text import TIER_WORDS, _earlier_chat, _sentence, _text_of, _without_markers, area_label, clean_opening
from .graph_query import COMPETITOR_WORDS
from .graph_reads import DETAIL_COLUMNS
from .presentation import distance_label, money_label
from .study_answer import _study_evidence, render_area_analysis

FIGURE_TITLES = {"groups": "Key figures", "restaurants": "How they compare",
                 "reviews": "Review sentiment"}
# Section names per kind of analysis; None leaves a section out.
SECTION_TITLES = {
    "groups": {"findings": None, "implication": "What this means", "recommendation": "Business implication"},
    "restaurants": {"findings": "Market observations", "implication": "What this means",
                    "recommendation": "My recommendation"},
    "reviews": {"findings": "What customers mention", "implication": "What this means",
                "recommendation": "Business implications"},
}
ANALYSIS_OPENINGS = {"areas": "Here are the areas I'd shortlist, best first.",
                     "groups": "Here's what the available records show.",
                     "restaurants": "Here's how these places compare.",
                     "reviews": "Here's what the available reviews show."}
LIMITATIONS = {
    "areas": "Restaurant counts show existing supply, not customer demand or profitability, and rent, parking and "
             "foot traffic aren't in my data.",
    "groups": "These figures show existing supply in the available records, not customer demand or profitability.",
    "restaurants": "Ratings and prices are benchmarks from the available records, not sales or market share.",
    "reviews": "These reviews are the available sample, not every customer's experience.",
}
HIDDEN_COLUMNS = {"restaurant_id", "anchor_id", "competitor_ids", "position", "latitude", "longitude",
                  "main_competitors", "compared_with_pj", "currency", "weekly_hours", "hours"}
COLUMN_NAMES = {"area_name": "Area", "all_restaurants": "Restaurants", "avg_rating": "Average rating",
                "average_rating": "Average rating", "avg_meal_price": "Average meal price",
                "average_price": "Average meal price", "average_meal_price": "Average meal price",
                "share_pct": "Share", "pj_share_pct": "PJ share", "review_count": "Reviews",
                "total_reviews": "Reviews", "price_tier": "Price tier"}


def _hidden(key: str) -> bool:
    return key in HIDDEN_COLUMNS or key == "id" or key.endswith(("_id", "_ids"))


NOT_A_COUNT = re.compile(r"pct|share|rating|price|spend|avg|average|per_|ratio|rate|stars", re.IGNORECASE)


# The model writes the briefing; the code writes the figures, so every number is exact.
def _analysis(user_query: str, rows: list[dict[str, Any]], note: str | None, conversation_context: str,
              deadline: float | None, kind: str, on_answer: Callable[[str], None] | None = None) -> AnswerResult:
    fallback = render_area_analysis(rows) if kind == "areas" else render_analysis(rows, kind, question=user_query)
    if note:
        fallback = f"{note}\n\n{fallback}"
    areas = kind == "areas"
    if areas:
        evidence = _study_evidence(rows)
    else:
        evidence = [{re.sub(r"\bpj\b", "PJ", key.replace("_pct", " %").replace("_", " ")): _plain_value(value)
                     for key, value in (_business_evidence(row) if row.get("restaurant_name")
                                        else _group_evidence(row)).items() if not _hidden(key)}
                    for row in rows]
    sample = _review_sample(rows) if kind == "reviews" else ""
    prompt = _earlier_chat(conversation_context) + f"User question: {user_query}\n\n{sample}Evidence:\n" + "\n".join(
        (f"[A{index}] " if areas else "- ") + json.dumps(item, ensure_ascii=False, default=str)
        for index, item in enumerate(evidence, 1))
    known = _numbers(prompt)
    try:
        if areas:
            render = lambda payload: render_area_analysis(  # noqa: E731
                rows, _checked_payload(payload, known) or {"answer": ""})
            partial = lambda payload: render_area_analysis(  # noqa: E731
                rows, _checked_payload(payload, known, streaming=True) or {"answer": ""}, partial=True)
            output_format = AREAS_FORMAT
        else:
            render = lambda payload: render_analysis(  # noqa: E731
                rows, kind, _checked_payload(payload, known) or {"answer": ""}, user_query)
            partial = lambda payload: render_analysis(  # noqa: E731
                rows, kind, _checked_payload(payload, known, streaming=True) or {"answer": ""}, user_query)
            output_format = ANALYSIS_FORMAT
        answer = _model_answer(prompt, ANALYST_INSTRUCTIONS + "\n\n" + output_format, deadline, render, partial,
                               note, on_answer)
        if answer is None:
            return AnswerResult(status="fallback", text=fallback)
    except (LLMServiceError, ValueError, TypeError) as exc:
        kg_debug("Answer used the written-out fallback", {"reason": str(exc)})
        return AnswerResult(status="fallback", text=fallback)
    answer = _without_markers(answer)
    return AnswerResult(status="success", text=f"{note}\n\n{answer}" if note else answer, used_llm=True)


def render_analysis(rows: list[dict[str, Any]], kind: str, payload: dict | None = None, question: str = "") -> str:
    if payload is not None and not _text_of(payload.get("answer")):
        raise ValueError("invalid_response_json")
    payload = payload or {}
    answer = _text_of(payload.get("answer"))
    if answer and kind == "reviews":
        answer = _sampled(answer, rows)
    lines = [clean_opening(answer) if answer else ANALYSIS_OPENINGS[kind]]
    figures = _figures(rows, kind)
    if figures:
        table = figures[0].startswith("|")
        lines += ["", f"**{_figure_title(rows, kind, question)}**", *([""] if table else []),
                  *(figures if table else [f"- {line}" for line in figures])]
    titles = SECTION_TITLES[kind]
    findings = [_finding(item) for item in payload.get("findings") or []
                if re.search(r"[A-Za-z]", _text_of(item))]
    if findings and titles["findings"]:
        lines += ["", f"**{titles['findings']}**", *findings]
    for key in ("implication", "recommendation"):
        if _text_of(payload.get(key)):
            lines += ["", f"**{titles[key]}**", _sentence(_text_of(payload[key]))]
    lines += ["", _sentence(_text_of(payload.get("limitation")) or LIMITATIONS[kind])]
    return "\n".join(lines)


def _finding(text: str) -> str:
    text = _sentence(re.sub(r"\s*\((?:mentions? in )?\d+ (?:mentions?|rows?)\)", "", _text_of(text)))
    label = re.match(r"([^:]{2,40}):\s+(.+)", text)
    return f"- **{label.group(1)}:** {label.group(2)}" if label else f"- {text}"


def _figure_title(rows: list[dict[str, Any]], kind: str, question: str = "") -> str:
    if kind == "restaurants" and (COMPETITOR_WORDS.search(question)
                                  or any("anchor_id" in row or "competitor_of" in row for row in rows)):
        return "Main competitors"
    return FIGURE_TITLES[kind]


def _figures(rows: list[dict[str, Any]], kind: str) -> list[str]:
    if kind == "reviews":
        return _sentiment_figures(rows)
    if kind == "restaurants":
        return [_restaurant_figure(row) for row in rows]
    table = _group_table(rows)
    if table:
        return table
    columns = [key for key in rows[0] if not _hidden(key) and not isinstance(rows[0].get(key), dict)]
    label = columns[0] if columns and isinstance(rows[0].get(columns[0]), str) else None
    if len(rows) == 1:
        return [f"{_column_name(key)}: {_cell(key, rows[0][key])}" for key in columns
                if rows[0].get(key) not in (None, "", [])]
    figures = []
    for row in rows:
        values = ", ".join(_figure(key, row[key]) for key in columns
                           if key != label and row.get(key) not in (None, "", []))
        name = _cell(label, row[label]) if label and row.get(label) else ""
        figures.append(f"**{name[:1].upper() + name[1:]}:** {values}" if name else values)
    return [figure for figure in figures if figure]


def _restaurant_figure(row: dict[str, Any]) -> str:
    facts = []
    if isinstance(row.get("average_rating"), (int, float)):
        reviews = f" from {row['review_count']:,} reviews" if isinstance(row.get("review_count"), int) else ""
        facts.append(f"rated {row['average_rating']:.1f}{reviews}")
    if isinstance(row.get("average_price"), (int, float)):
        facts.append(f"around {money_label(row['average_price'], 'MYR')} per person")
    if TIER_WORDS.get(row.get("price_tier")):
        facts.append(TIER_WORDS[row["price_tier"]])
    if distance_label(row.get("distance_m")):
        facts.append(f"about {distance_label(row['distance_m'])} away")
    facts += [_figure(key, value) for key, value in row.items()
              if key not in DETAIL_COLUMNS and not _hidden(key) and key != "distance_m"
              and isinstance(value, (int, float)) and not isinstance(value, bool)]
    name = row["restaurant_name"]
    area = (f" — {area_label(row['area'])}" if row.get("area") and str(row["area"]).lower() not in name.lower()
            else "")
    text = ", ".join(facts)
    return f"**{name}**{area}." + (f" {text[:1].upper() + text[1:]}." if facts else "")


def _sampled(answer: str, rows: list[dict[str, Any]]) -> str:
    if answer.lower().startswith(("in the", "across the", "among the")):
        return answer
    sentiments = {str(row.get("sentiment") or "").lower() for row in rows} - {""}
    kind = f" {next(iter(sentiments))}" if len(sentiments) == 1 else ""
    text = re.sub(r"\b(?:most often|mostly|usually|generally|most commonly)\s+(?=complain|mention|praise|say|like)",
                  "", answer, flags=re.IGNORECASE)
    text = re.sub(r"^(?:most\s+)?(?:customers|people|diners)\b", "reviewers", text, flags=re.IGNORECASE)
    return f"In the {len(rows)} available{kind} reviews, {text[:1].lower() + text[1:]}"


def _review_sample(rows: list[dict[str, Any]]) -> str:
    sentiments = Counter(str(row.get("sentiment") or "unknown").lower() for row in rows)
    mix = "all " + next(iter(sentiments)) if len(sentiments) == 1 else ", ".join(
        f"{count} {name}" for name, count in sentiments.most_common())
    return f"Review sample: {len(rows)} reviews, {mix}.\n\n"


def _sentiment_figures(rows: list[dict[str, Any]]) -> list[str]:
    sentiments = [value for row in rows
                  for value in (row["sentiment"] if isinstance(row.get("sentiment"), list) else [row.get("sentiment")])
                  if isinstance(value, str) and value]
    counts = Counter(value.lower() for value in sentiments)
    order = ["positive", "mixed", "neutral", "negative"]
    # A query for complaints returns only negative reviews: a one-row "100%" table would mislead.
    if len(counts) < 2:
        return []
    return ["| Sentiment | Reviews |", "|---|---:|"] + [
        f"| {value.capitalize()} | {counts[value]} ({100 * counts[value] / len(sentiments):.0f}%) |"
        for value in sorted(counts, key=lambda value: order.index(value) if value in order else len(order))]


# Counts, shares and averages as a table: one column per area or group (and PJ overall when the rows carry PJ
# figures) for a few rows, one row per group for more. None when the rows are not a group comparison.
def _group_table(rows: list[dict[str, Any]]) -> list[str] | None:
    columns = [key for key in rows[0] if not _hidden(key) and not isinstance(rows[0].get(key), (dict, list))]
    label = columns[0] if columns and isinstance(rows[0].get(columns[0]), str) else None
    metrics = [key for key in columns if key != label]
    if not label or not metrics:
        return None
    rows = [row for row in rows if row.get(label) not in (None, "")] or rows
    names = [(lambda name: name[:1].upper() + name[1:])(
        area_label(row[label]) if label == "area_name" else _cell(label, row[label])) if row.get(label) else ""
             for row in rows]
    if len(rows) > 4:
        table = ["| " + _column_name(label) + " | " + " | ".join(_column_name(key) for key in metrics) + " |",
                 "|---|" + "---:|" * len(metrics)]
        return table + ["| " + name + " | " + " | ".join(_cell(key, row.get(key)) if row.get(key) is not None
                                                     else "–" for key in metrics) + " |"
                        for name, row in zip(names, rows)]
    pj = {key[3:]: key for key in metrics if key.startswith("pj_")}
    shown = [key for key in metrics if not key.startswith("pj_")] + [key for key in pj.values() if key[3:] not in metrics]
    header = names + (["PJ overall"] if pj else [])
    table = ["| Metric | " + " | ".join(header) + " |", "|---|" + "---:|" * len(header)]
    for key in shown:
        own = key.startswith("pj_")
        cells = ["–" if own or rows[i].get(key) is None else _cell(key, rows[i][key]) for i in range(len(rows))]
        if pj:
            source = key if own else pj.get(key)
            cells.append(_cell(source, rows[0][source]) if source and rows[0].get(source) is not None else "–")
        table.append(f"| {_column_name(key[3:] if own else key)} | " + " | ".join(cells) + " |")
    return table


def _column_name(key: str) -> str:
    if key in COLUMN_NAMES:
        return COLUMN_NAMES[key]
    words = re.sub(r"_pct$", "", key).replace("avg_", "average_").replace("_", " ")
    words = re.sub(r"\bpj\b", "PJ", words)
    return words[:1].upper() + words[1:]


def _figure(key: str, value: Any) -> str:
    name = _column_name(key)
    first = name.split(" ")[0]
    if not (first.isupper() or first.lower() in _proper_words()):
        name = name[:1].lower() + name[1:]
    if isinstance(value, int) and not isinstance(value, bool) and not NOT_A_COUNT.search(key):
        return f"{value:,} {name}"
    return f"{name} {_cell(key, value)}"


def _cell(key: str, value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(_cell(key, item) for item in value if item not in (None, ""))
    if isinstance(value, (int, float)):
        if "pct" in key or "share" in key:
            return f"{value:g}%"
        if "price" in key or "spend" in key:
            return money_label(value, "MYR") or str(value)
        if "rating" in key or key == "stars":
            return f"{value:.1f}" if round(value, 1) == value else f"{value:.2f}"
        return f"{int(value):,}" if float(value).is_integer() else f"{value:,.1f}"
    if key in ("price_tier", "tier"):
        return TIER_WORDS.get(str(value), str(value))
    return str(_plain_value(value))


def _plain_value(value: Any) -> Any:
    if isinstance(value, str) and value in load_vocabulary()["columns"]["restaurant.business_status"]["values"]:
        return value.replace("_", " ").capitalize()
    return value


@lru_cache(maxsize=1)
def _proper_words() -> frozenset[str]:
    columns = load_vocabulary()["columns"]
    return frozenset(value.split(" ")[0].lower() for column in ("cuisine.name", "cuisine.category")
                     for value in columns[column]["values"])
