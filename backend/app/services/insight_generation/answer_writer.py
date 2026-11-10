import json
import re
from time import perf_counter
from typing import Any, Callable

from ...contracts import AnswerResult, RetrievalResult
from ..query_generation.cypher_generation import RESTAURANT_DETAILS_FIELD
from ..shared.diagnostics import kg_debug, log_timing, note_turn
from ..shared.llm import LLMServiceError
from ..shared.messages import response
from .analysis_answer import _analysis
from .answer_checks import _checked_payload, _numbers
from .answer_evidence import TIME_WORDS, _restaurant_evidence
from .answer_model import _model_answer
from .answer_prompts import ANSWER_INSTRUCTIONS, CARD_FORMAT, COMPARE_FORMAT, LIST_FORMAT
from .answer_text import _earlier_chat, _without_markers
from .graph_query import few_area_matches, named_places
from .opening_hours import weekday_today
from .restaurant_answer import _brand_branches, _render_model_answer, _restaurant_fallback


def generate_answer(
    user_query: str,
    retrieval: RetrievalResult,
    *,
    conversation_context: str = "No previous conversation.",
    deadline: float | None = None,
    on_answer: Callable[[str], None] | None = None,
) -> AnswerResult:
    # on_answer gets the full answer so far, not a delta.
    started_at = perf_counter()
    result = _answer(user_query, retrieval, conversation_context, deadline, on_answer)
    log_timing("answer.generation", started_at, status=result.status, used_llm=result.used_llm)
    return result


ANALYSIS_LAYOUTS = ("areas", "reviews", "restaurants", "groups")


def answer_layout(retrieval: RetrievalResult) -> str:
    rows, plan = retrieval.records, retrieval.query_plan
    restaurants = bool(rows) and all(row.get("restaurant_name") for row in rows)
    card = restaurants and len(rows) == 1 and RESTAURANT_DETAILS_FIELD in plan.requested_fields
    shortlist = bool(rows) and not restaurants and all("main_competitors" in row for row in rows)
    reviews = any("review" in row for row in rows)
    # Market figures and reviews across places always get an analysis; places only when a business asked.
    if (plan.business or shortlist or not restaurants or (reviews and not card)) and (not card or reviews):
        return "areas" if shortlist else "reviews" if reviews else "restaurants" if restaurants else "groups"
    if card:
        return "card"
    return "compare" if len(rows) >= 2 and len(named_places(plan.parameters)) >= 2 else "list"


# Only the places the model has started describing.
def _described_rows(payload: dict | None, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    numbers = [int(match.group(1)) for item in (payload or {}).get("restaurants") or []
               if isinstance(item, dict) and ("description" in item or "best_for" in item)
               and (match := re.fullmatch(r"R(\d+)", str(item.get("record_id", ""))))]
    return rows[:max(numbers, default=0)]


def _answer(user_query: str, retrieval: RetrievalResult, conversation_context: str,
            deadline: float | None, on_answer: Callable[[str], None] | None = None) -> AnswerResult:
    if retrieval.status == "no_results":
        return AnswerResult(status="no_results", text=retrieval.message or response("errors.no_results"))
    if retrieval.status == "clarification_required":
        return AnswerResult(status="clarification_required", text=retrieval.message or response("errors.clarify"))
    if retrieval.status == "success" and not retrieval.records and retrieval.message:
        return AnswerResult(status="success", text=retrieval.message, used_llm=True)
    if retrieval.status != "success":
        status = "unsupported" if retrieval.status == "unsupported" else "fallback"
        return AnswerResult(status=status, text=retrieval.message or response("errors.retrieval"))

    note = retrieval.message
    rows = retrieval.records
    layout = answer_layout(retrieval)
    note_turn(layout=layout)
    if layout in ANALYSIS_LAYOUTS:
        return _analysis(user_query, rows, note, conversation_context, deadline, layout, on_answer)
    card = layout == "card"
    if layout == "compare":
        rows = _brand_branches(rows, named_places(retrieval.query_plan.parameters))
    evidence = _restaurant_evidence(rows, card, hours=card or bool(TIME_WORDS.search(user_query)))
    fallback = _restaurant_fallback(rows, card, user_query, compare=layout == "compare")
    if note:
        fallback = f"{note}\n\n{fallback}"

    context = _earlier_chat(conversation_context)
    if card:
        context += f"Today is {weekday_today().capitalize()}.\n\n"
    compare = layout == "compare"
    if few_area_matches(retrieval.query_plan, rows):
        context += (f"Only {len(rows)} place{'s' if len(rows) > 1 else ''} in the area the user asked about "
                    "match. In the conclusion, say so in a few words and offer to look across Petaling Jaya.\n\n")
    prompt = context + f"User question: {user_query}\n\nEvidence:\n" + "\n".join(
        f"[R{index}] {json.dumps(item, ensure_ascii=False, default=str)}" for index, item in enumerate(evidence, 1))
    output_format = CARD_FORMAT if card else COMPARE_FORMAT if compare else LIST_FORMAT
    known = _numbers(prompt)
    try:
        answer = _model_answer(
            prompt, ANSWER_INSTRUCTIONS + "\n\n" + output_format, deadline,
            lambda payload: _render_model_answer(_checked_payload(payload, known), rows, card, user_query, compare),
            lambda payload: _render_model_answer(_checked_payload(payload, known, streaming=True),
                                                 rows if card else _described_rows(payload, rows), card,
                                                 user_query, compare),
            note, on_answer)
        if answer is None:
            return AnswerResult(status="fallback", text=fallback)
        if not answer:
            raise ValueError("invalid_response_json")
    except (LLMServiceError, ValueError, TypeError) as exc:
        kg_debug("Answer used the written-out fallback", {"reason": str(exc)})
        return AnswerResult(status="fallback", text=fallback)
    answer = _without_markers(answer)
    return AnswerResult(status="success", text=f"{note}\n\n{answer}" if note else answer, used_llm=True)
