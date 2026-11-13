import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter, time
from typing import Any
from uuid import uuid4

_request_timing: ContextVar[dict | None] = ContextVar("request_timing", default=None)
_turn: ContextVar[dict | None] = ContextVar("turn", default=None)


def trace_request(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = _request_timing.set({
            "trace_id": uuid4().hex, "started_at": time(), "monotonic_start": perf_counter(),
        })
        try:
            return function(*args, **kwargs)
        finally:
            _request_timing.reset(token)
    return wrapped


def timing_token_fields() -> dict | None:
    context = _request_timing.get()
    return {key: context[key] for key in ("trace_id", "started_at")} if context else None


# The preflight token also carries how long the preflight took, so the send request's timeline can show it.
def preflight_timing_fields() -> dict | None:
    context = _request_timing.get()
    fields = timing_token_fields()
    return {**fields, "preflight_s": round(perf_counter() - context["monotonic_start"], 3)} if fields else None


# Continue the preflight request's timing in the send request (values come only from the signed token).
def restore_request_timing(fields: dict | None) -> None:
    context = _request_timing.get()
    if context is not None and fields:
        context.update(fields, monotonic_start=perf_counter() - max(0.0, time() - fields["started_at"]))


# Records one step of the current request for its timeline; nothing is printed until log_request_summary.
def log_timing(operation: str, started_at: float, *, status: str = "success", **fields: Any) -> None:
    context = _request_timing.get()
    if context is not None:
        context.setdefault("phases", []).append((operation, started_at, perf_counter(), status, fields))


def mark(event: str) -> None:
    context = _request_timing.get()
    if context is not None:
        now = perf_counter()
        context.setdefault("phases", []).append((event, now, None, "success", {}))


PHASE_LABELS = {
    "chat.send.guardrails": "Guardrail check",
    "cypher.generation": "Query model (LLM 1) writes the Cypher",
    "cypher.validation": "Cypher check",
    "neo4j.query": "Graph query",
    "answer.generation": "Answer model (LLM 2)",
    "answer.streaming_started": "> Answer starts streaming to the user",
    "answer.streaming_done": "> Answer finished streaming",
    "chat.send.persist": "Save chat",
}

def _phase_label(operation: str, status: str, fields: dict) -> str:
    if operation.startswith("cache."):
        return f"Cache hit: {operation.removeprefix('cache.').replace('_', ' ')}"
    label = PHASE_LABELS.get(operation, operation)
    if operation == "neo4j.query":
        label += f": {fields['purpose']}" if fields.get("purpose") else ""
        rows = fields.get("row_count")
        label += f" ({rows} row{'' if rows == 1 else 's'})" if rows is not None else ""
    if operation == "cypher.generation" and fields.get("retry"):
        label += " (retry)"
    if status not in ("success", "hit"):
        label += f" [{status}]"
    return label


SPEED_TARGET_SECONDS = 15.0


# One readable timeline per question, from the moment it was sent, printed once the answer is saved.
def log_request_summary(question: str = "") -> None:
    context = _request_timing.get()
    if not context:
        return
    start, now = context["monotonic_start"], perf_counter()
    phases = sorted(context.get("phases", []), key=lambda phase: phase[1])
    # The speed target, not a limit: a slower answer still finishes, and is flagged here.
    over = f" | OVER {SPEED_TARGET_SECONDS:g}s TARGET" if now - start > SPEED_TARGET_SECONDS else ""
    lines = [f'[TIMING] "{question[:80]}" | {now - start:.2f}s total{over} | trace {context["trace_id"][:8]}',
             f"{'at':>9} {'took':>7}  phase",
             f"{0:8.2f}s {'':>7}  Question sent"]
    if isinstance(context.get("preflight_s"), (int, float)):
        lines.append(f"{context['preflight_s']:8.2f}s {context['preflight_s']:6.2f}s  Preflight request")
    open_ends: list[float] = []
    for operation, started_at, completed_at, status, fields in phases:
        while open_ends and started_at >= open_ends[-1]:
            open_ends.pop()
        indent = "  " * len(open_ends)
        took = f"{completed_at - started_at:6.2f}s" if completed_at is not None else ""
        lines.append(f"{started_at - start:8.2f}s {took:>7}  {indent}{_phase_label(operation, status, fields)}")
        if completed_at is not None:
            open_ends.append(completed_at)
    lines.append(f"{now - start:8.2f}s {'':>7}  Done")
    print("\n".join(lines), flush=True)


# One [TURN] JSON line per chat turn with each step's decision; the timeline has the timing.
@contextmanager
def turn_record(**fields: Any):
    context = _request_timing.get()
    record = {"trace_id": context["trace_id"] if context else None, **fields}
    token = _turn.set(record)
    try:
        yield record
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"[:300]
        raise
    finally:
        _turn.reset(token)
        print("[TURN] " + json.dumps(record, default=str, ensure_ascii=False), flush=True)


def note_turn(**fields: Any) -> None:
    record = _turn.get()
    if record is not None:
        record.update(fields)


def kg_debug(stage: str, value: Any = None) -> None:
    if os.getenv("KG_DEBUG", "false").strip().lower() != "true":
        return
    prefix = f"[KG DEBUG] {stage}"
    if value is None:
        print(prefix, flush=True)
        return
    rendered = (
        value
        if isinstance(value, str)
        else json.dumps(value, default=str, ensure_ascii=False, indent=2)
    )
    print(f"\n{prefix}\n{rendered}\n", flush=True)
