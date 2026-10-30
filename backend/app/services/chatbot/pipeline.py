# One chat turn: rule-based screen -> Cypher generation (LLM 1) -> answer (LLM 2).

import os
from dataclasses import dataclass, field
from functools import partial
from time import perf_counter
from typing import Callable

from ...contracts import GuardrailDecision
from ..insight_generation.graph_answer import generate_answer, query_graph
from ..insight_generation.graph_evidence import build_graph_evidence
from ..query_generation.proximity import location_requirement
from ..query_generation.scope import classify_query_scope
from ..shared.diagnostics import kg_debug, log_timing
from ..shared.messages import response

NO_LOCATION = "No location context provided."
NO_CONVERSATION = "No previous conversation."
LLM_ERROR_ANSWER = response("errors.answer")
LOCATION_REQUEST_ANSWER = response("location.permission", venue="restaurants")
OUT_OF_SCOPE_ANSWER = response("errors.out_of_scope")

DEFAULT_RESPONSE_BUDGET_SECONDS = 13.5
MIN_RESPONSE_BUDGET_SECONDS = 6.0
MAX_RESPONSE_BUDGET_SECONDS = 90.0


def get_response_budget_seconds() -> float:
    try:
        budget = float(os.getenv("RESPONSE_BUDGET_SECONDS", str(DEFAULT_RESPONSE_BUDGET_SECONDS)))
    except ValueError:
        budget = DEFAULT_RESPONSE_BUDGET_SECONDS
    return max(MIN_RESPONSE_BUDGET_SECONDS, min(budget, MAX_RESPONSE_BUDGET_SECONDS))


@dataclass
class AssistantTurn:
    answer: str
    map_data: dict | None = None
    build_graph: Callable[[], dict | None] | None = None
    quick_replies: list[str] = field(default_factory=list)
    chat_title: str | None = None


def generate_assistant_response(
    messages: list[dict[str, str]],
    location_context: str = NO_LOCATION,
    location_permission_denied: bool = False,
    preflight_decision: GuardrailDecision | None = None,
    deadline: float | None = None,
    title_needed: bool | None = None,
) -> AssistantTurn:
    started_at = perf_counter()
    deadline = deadline or started_at + get_response_budget_seconds()
    user_query = messages[-1]["content"] if messages else ""
    conversation_context = format_conversation_context(messages[:-1])

    decision = preflight_decision or assess_query_guardrails(user_query, conversation_context)
    if decision.status != "ready":
        return AssistantTurn(decision.message or response("errors.unknown"))
    if decision.location_required and location_context == NO_LOCATION and not location_permission_denied:
        return AssistantTurn(LOCATION_REQUEST_ANSWER)

    if title_needed is None:
        title_needed = len(messages) <= 1
    # Never ask the user two questions in a row (this also covers the location request).
    previous_reply = messages[-2] if len(messages) >= 2 and messages[-2]["role"] == "assistant" else None
    may_clarify = not (previous_reply and previous_reply["content"].rstrip().endswith("?"))
    replies: dict = {}
    retrieval_started_at = perf_counter()
    result = query_graph(user_query, conversation_context, location_context, deadline=deadline,
                         replies=replies, want_title=title_needed, may_clarify=may_clarify)
    log_timing("chat.retrieval", retrieval_started_at, status=result.status, total_started_at=started_at)
    answer = generate_answer(user_query, result, conversation_context=conversation_context, deadline=deadline)
    log_timing("chat.pipeline.total", started_at, status=answer.status, used_llm=answer.used_llm)
    kg_debug("Final answer", answer.text)
    has_rows = result.status == "success" and bool(result.records)
    return AssistantTurn(
        answer=answer.text or LLM_ERROR_ANSWER,
        map_data=result.map_result.to_dict() if has_rows else None,
        build_graph=partial(build_graph_evidence, result.records) if has_rows else None,
        quick_replies=replies.get("quick_replies", []),
        chat_title=replies.get("chat_title"),
    )


def assess_query_guardrails(user_query: str, conversation_context: str = NO_CONVERSATION) -> GuardrailDecision:
    screen = classify_query_scope(user_query, conversation_context)
    if screen.status == "out_of_scope":
        return GuardrailDecision(status="out_of_scope", message=OUT_OF_SCOPE_ANSWER)
    if screen.status == "unsupported":
        return GuardrailDecision(status="unsupported", scope=screen.scope, message=screen.reason)
    location_required, detected_location = location_requirement(user_query)
    return GuardrailDecision(status="ready", scope=screen.scope, location_required=location_required,
                             detected_location=detected_location)


def format_conversation_context(messages: list[dict[str, str]]) -> str:
    turns = []
    for message in messages[-8:]:
        role = "Assistant" if message["role"] == "assistant" else "User"
        content = " ".join(message["content"].strip().split())
        turns.append(f"{role}: {content[:1200]}")
    return "\n".join(turns) if turns else NO_CONVERSATION
