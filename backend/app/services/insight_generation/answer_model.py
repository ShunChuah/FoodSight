from time import perf_counter
from typing import Callable

from ..shared.cache import ANSWER_REPLIES
from ..shared.diagnostics import kg_debug, mark
from ..shared.llm import call_llm, parse_json_object, parse_partial_json, remaining_response_timeout
from .answer_text import _without_markers

STREAM_INTERVAL_SECONDS = 0.1


class _AnswerStream:
    def __init__(self, on_answer: Callable[[str], None], render: Callable[[dict | None], str], note: str | None):
        self.on_answer, self.render, self.note = on_answer, render, note
        self.last, self.sent_at = "", 0.0

    def __call__(self, raw: str) -> None:
        if perf_counter() - self.sent_at < STREAM_INTERVAL_SECONDS:
            return
        try:
            text = _without_markers(self.render(parse_partial_json(raw)))
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            return
        if text and text != self.last:
            if not self.last:
                mark("answer.streaming_started")
            self.last, self.sent_at = text, perf_counter()
            self.on_answer(f"{self.note}\n\n{text}" if self.note else text)


# LLM call 2: cached for the same evidence, else streamed and cached once it renders; None if out of time.
def _model_answer(prompt: str, instructions: str, deadline: float | None, render: Callable[[dict | None], str],
                  partial: Callable[[dict | None], str], note: str | None,
                  on_answer: Callable[[str], None] | None) -> str | None:
    raw = ANSWER_REPLIES.get(prompt, instructions)
    if raw is not None:
        return render(parse_json_object(raw))
    timeout = remaining_response_timeout(deadline)
    if timeout is None and deadline is not None:
        return None
    raw = call_llm(prompt, instructions, task="response", timeout_seconds=timeout,
                   on_text=_AnswerStream(on_answer, partial, note) if on_answer else None)
    if on_answer:
        mark("answer.streaming_done")
    kg_debug("Answer model output", raw)
    answer = render(parse_json_object(raw))
    ANSWER_REPLIES.set(raw, prompt, instructions)
    return answer
