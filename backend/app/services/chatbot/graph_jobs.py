"""Knowledge Graph Evidence is built after the answer has been sent, so the answer never waits for it.

The chat route saves the answer with a pending ChatMessageGraphJob, then calls start_graph_job(): a worker
thread builds the graph and saves it. The thread does not belong to the request, so the graph is finished
even when the browser has moved on; the browser asks GET /chats/{chat}/messages/{message}/graph until then.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Callable

from sqlalchemy.orm import Session

from ...database import SessionLocal
from ...model import ChatMessage, ChatMessageGraph, ChatMessageGraphJob
from ..shared.diagnostics import log_timing

# A job still pending after this long was lost (the server restarted while building it), so it counts as failed.
GRAPH_JOB_TIMEOUT = timedelta(minutes=2)

_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="graph-evidence")


def start_graph_job(message_id: int, build: Callable[[], dict | None]) -> None:
    _workers.submit(run_graph_job, message_id, build)


def run_graph_job(
    message_id: int,
    build: Callable[[], dict | None],
    session_factory: Callable[[], AbstractContextManager[Session]] = SessionLocal,
) -> str:
    """Build the graph and save it. Returns "ready", "empty" (nothing to draw), "failed" or "gone" (chat deleted)."""
    started_at = perf_counter()
    try:
        graph = build()
        outcome = "ready" if graph else "empty"
    except Exception as exc:  # a broken graph must never take the worker down
        print(f"Knowledge Graph Evidence failed for message {message_id}: {exc}", flush=True)
        graph, outcome = None, "failed"
    try:
        with session_factory() as db:
            job = db.get(ChatMessageGraphJob, message_id)
            if job is None:
                outcome = "gone"
            elif outcome == "ready":
                db.delete(job)
                db.add(ChatMessageGraph(message_id=message_id, data=graph))
            elif outcome == "empty":
                db.delete(job)
            else:
                job.status = "failed"
            db.commit()
    except Exception as exc:
        print(f"Knowledge Graph Evidence could not be saved for message {message_id}: {exc}", flush=True)
        outcome = "failed"
    log_timing("chat.graph_evidence", started_at, status=outcome, message_id=message_id)
    return outcome


def graph_status(message: ChatMessage, now: datetime | None = None) -> str | None:
    """"ready", "pending" or "failed"; None for an answer without graph evidence."""
    if message.graph_snapshot:
        return "ready"
    job = message.graph_job
    if job is None:
        return None
    created_at = job.created_at if job.created_at.tzinfo else job.created_at.replace(tzinfo=timezone.utc)
    if job.status == "pending" and (now or datetime.now(timezone.utc)) - created_at > GRAPH_JOB_TIMEOUT:
        return "failed"
    return job.status
