# Live processing stages for the streamed answer, and stopping a turn the user cancelled. The reporter lives in a
# context variable, so the pipeline reports stages without passing a callback through every function.

import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable

UNDERSTOOD, SEARCHING, COMPARING, WRITING = "understood", "searching", "comparing", "writing"


class TurnCancelled(Exception):
    """The user stopped the answer; nothing is saved."""


_progress: ContextVar[dict | None] = ContextVar("progress", default=None)


@contextmanager
def tracking(on_stage: Callable[[str, list[str]], None] | None, cancel: threading.Event | None = None,
             place: str | None = None):
    token = _progress.set({"on_stage": on_stage, "cancel": cancel, "place": place})
    try:
        yield
    finally:
        _progress.reset(token)


def place() -> str | None:
    progress = _progress.get()
    return progress["place"] if progress else None


def set_place(name: str | None) -> None:
    progress = _progress.get()
    if progress is not None:
        progress["place"] = name


# Stops at the next stage once the user has cancelled, before more model or database work is paid for.
def check_cancelled() -> None:
    progress = _progress.get()
    if progress and progress["cancel"] is not None and progress["cancel"].is_set():
        raise TurnCancelled()


def report_stage(stage: str, detail: list[str] | None = None) -> None:
    check_cancelled()
    progress = _progress.get()
    if progress and progress["on_stage"]:
        try:
            progress["on_stage"](stage, detail or [])
        except Exception as exc:  # A display problem never stops the answer.
            print(f"Stage report failed: {exc}", flush=True)


def summary_words(values: list[Any]) -> list[str]:
    return [str(value) for value in dict.fromkeys(value for value in values if value)][:4]
