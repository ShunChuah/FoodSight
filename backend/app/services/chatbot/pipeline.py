# One chat turn: rule-based screen -> Cypher generation (LLM 1) -> answer (LLM 2).

import os
from dataclasses import dataclass, field
from functools import partial
from time import perf_counter
from typing import Callable

from ...contracts import GuardrailDecision
from ..insight_generation.graph_answer import generate_answer, query_graph
from ..insight_generation.graph_evidence import build_graph_evidence
from ..query_generation.coverage import coverage_reply
from ..query_generation.location import resolve_location
from ..query_generation.scope import classify_query_scope
from ..shared.diagnostics import kg_debug, note_turn, turn_record
from ..shared.messages import response
from .conversation_state import search_state, state_prompt

NO_LOCATION = "No location context provided."
NO_CONVERSATION = "No previous conversation."
LLM_ERROR_ANSWER = response("errors.answer")
LOCATION_REQUEST_ANSWER = response("location.permission", venue="restaurants")
OUT_OF_SCOPE_ANSWER = response("errors.out_of_scope")

# With the chat state, earlier answers only need their opening.
SHORT_ANSWER_CHARACTERS = 300
# Used when RESPONSE_BUDGET_SECONDS is not set.
DEFAULT_RESPONSE_BUDGET_SECONDS = 14.0
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
    # None keeps the previous state.
    state: dict | None = None
    log: dict = field(default_factory=dict, compare=False, repr=False)


def generate_assistant_response(
    messages: list[dict[str, str]],
    location_context: str = NO_LOCATION,
    location_permission_denied: bool = False,
    preflight_decision: GuardrailDecision | None = None,
    deadline: float | None = None,
    title_needed: bool | None = None,
    chat_state: dict | None = None,
    on_answer: Callable[[str], None] | None = None,
) -> AssistantTurn:
    user_query = messages[-1]["content"] if messages else ""
    with turn_record(question=user_query[:300]) as record:
        turn = _respond(user_query, messages, location_context, location_permission_denied, preflight_decision,
                        deadline, title_needed, chat_state, on_answer)
    turn.log = record
    return turn


def _respond(user_query, messages, location_context, location_permission_denied, preflight_decision, deadline,
             title_needed, chat_state, on_answer) -> AssistantTurn:
    started_at = perf_counter()
    deadline = deadline or started_at + get_response_budget_seconds()
    state_text = state_prompt(chat_state)
    conversation_context = format_conversation_context(
        messages[:-1], answer_characters=SHORT_ANSWER_CHARACTERS if state_text else None)

    decision = preflight_decision or assess_query_guardrails(user_query, conversation_context)
    note_turn(preflight=decision.status, scope=decision.scope, location=decision.location_kind,
              place=decision.detected_location, gps=location_context != NO_LOCATION, follow_up=len(messages) > 1)
    if decision.status != "ready":
        note_turn(outcome="blocked")
        return AssistantTurn(decision.message or response("errors.unknown"), quick_replies=list(decision.suggestions))
    if decision.location_required and location_context == NO_LOCATION and not location_permission_denied:
        note_turn(outcome="location_request")
        return AssistantTurn(LOCATION_REQUEST_ANSWER)

    if title_needed is None:
        title_needed = len(messages) <= 1
    # Never ask the user two questions in a row (this also covers the location request).
    previous_reply = messages[-2] if len(messages) >= 2 and messages[-2]["role"] == "assistant" else None
    may_clarify = not (previous_reply and previous_reply["content"].rstrip().endswith("?"))
    replies: dict = {}
    result = query_graph(user_query, conversation_context, location_context, deadline=deadline,
                         replies=replies, want_title=title_needed, may_clarify=may_clarify,
                         chat_state=state_text)
    answer = generate_answer(user_query, result, conversation_context=conversation_context, deadline=deadline,
                             on_answer=on_answer)
    note_turn(result=result.status, answer=answer.status, used_llm=answer.used_llm)
    kg_debug("Final answer", answer.text)
    has_rows = result.status == "success" and bool(result.records)
    place = decision.detected_location if decision.location_kind == "named" else None
    state = search_state(result.query_plan, result.records, place) if has_rows else None
    return AssistantTurn(
        answer=answer.text or LLM_ERROR_ANSWER,
        map_data=result.map_result.to_dict() if has_rows else None,
        build_graph=partial(build_graph_evidence, result.records) if has_rows else None,
        quick_replies=replies.get("quick_replies", []),
        chat_title=replies.get("chat_title"),
        state=state,
    )


def assess_query_guardrails(user_query: str, conversation_context: str = NO_CONVERSATION) -> GuardrailDecision:
    screen = classify_query_scope(user_query, conversation_context)
    if screen.status == "out_of_scope":
        return GuardrailDecision(status="out_of_scope", message=OUT_OF_SCOPE_ANSWER)
    if screen.status == "unsupported":
        return GuardrailDecision(status="unsupported", scope=screen.scope, message=screen.reason)
    location = resolve_location(user_query)
    if location.kind == "outside" and location.outside:
        coverage = coverage_reply(location.text, location.outside, conversation_context)
        return GuardrailDecision(status="outside_coverage", scope=screen.scope, message=coverage.message,
                                 location_kind=location.kind, detected_location=location.name,
                                 suggestions=coverage.suggestions)
    return GuardrailDecision(status="ready", scope=screen.scope, location_kind=location.kind,
                             detected_location=location.name)


def format_conversation_context(messages: list[dict[str, str]], answer_characters: int | None = None) -> str:
    turns = []
    for message in messages[-8:]:
        role = "Assistant" if message["role"] == "assistant" else "User"
        content = " ".join(message["content"].strip().split())
        limit = answer_characters if answer_characters and role == "Assistant" else 1200
        turns.append(f"{role}: {content[:limit]}")
    return "\n".join(turns) if turns else NO_CONVERSATION
