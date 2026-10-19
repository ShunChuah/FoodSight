"""[TIMING] log lines and KG_DEBUG output.
"""
import json
import os
from contextvars import ContextVar
from functools import wraps
from time import perf_counter, time
from typing import Any
from uuid import uuid4

_request_timing: ContextVar[dict | None] = ContextVar("request_timing", default=None)


def trace_request(function):
    """Isolate timing for concurrent synchronous FastAPI request handlers."""
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


def restore_request_timing(fields: dict | None) -> None:
    """Continue the preflight request's timing in the send request (values come only from the signed token)."""
    context = _request_timing.get()
    if context is not None and fields:
        context.update(fields, monotonic_start=perf_counter() - max(0.0, time() - fields["started_at"]))


def log_request_timing(operation: str, *, status: str = "success") -> None:
    context = _request_timing.get()
    if context:
        log_timing(operation, context["monotonic_start"], status=status)


def log_timing(
    operation: str,
    started_at: float,
    *,
    status: str = "success",
    total_started_at: float | None = None,
    **fields: Any,
) -> None:
    """Log durations in seconds using a monotonic clock."""
    completed_at = perf_counter()
    parts = [
        "[TIMING]",
        f"operation={operation}",
        f"status={status}",
        f"elapsed_s={completed_at - started_at:.3f}",
    ]
    if total_started_at is not None:
        parts.append(f"total_s={completed_at - total_started_at:.3f}")
    context = _request_timing.get()
    if context:
        parts.extend((f"trace_id={context['trace_id']}",
                      f"request_elapsed_s={completed_at - context['monotonic_start']:.3f}"))
    parts.extend(
        f"{key}={_format_field(value)}"
        for key, value in fields.items()
        if value is not None
    )
    print(" ".join(parts), flush=True)


def _format_field(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    return str(value).replace(" ", "_")


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
