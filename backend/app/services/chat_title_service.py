from concurrent.futures import Future, ThreadPoolExecutor
from time import perf_counter
from typing import Callable

from .llm_service import generate_chat_title


title_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chat-title")
TITLE_ELIGIBLE_STATUSES = {"ready", "clarification_required"}


def create_temporary_chat_title(message: str) -> str:
    clean_message = " ".join(message.strip().split())
    if not clean_message:
        return "New Chat"
    return f"{clean_message[:35]}..." if len(clean_message) > 35 else clean_message


def generate_chat_title_safely(message: str) -> str | None:
    started_at = perf_counter()
    print(
        "[TIMING] Chat title generation started. elapsed=0.00s total=0.00s",
        flush=True,
    )
    try:
        title = generate_chat_title(message).strip()
    except Exception as exc:
        print(f"Chat title generation failed: {exc}", flush=True)
        return None
    finally:
        elapsed = perf_counter() - started_at
        print(
            f"[TIMING] Chat title generation produced a title. "
            f"elapsed={elapsed:.2f}s total={elapsed:.2f}s",
            flush=True,
        )
    return title[:160] if title else None


def start_chat_title_generation(
    message: str,
    decision_status: str,
) -> Future[str | None] | None:
    # Valid F&B requests still deserve a title when the assistant asks a
    # clarification question before Cypher generation.
    if decision_status not in TITLE_ELIGIBLE_STATUSES:
        return None
    return title_executor.submit(generate_chat_title_safely, message)


def persist_chat_title_when_ready(
    future: Future[str | None],
    save_title: Callable[[str], None],
) -> None:
    def handle_result(completed: Future[str | None]) -> None:
        try:
            generated_title = completed.result()
        except Exception as exc:
            print(f"Parallel chat title generation failed: {exc}", flush=True)
            return
        if not generated_title:
            return

        save_title(generated_title)

    future.add_done_callback(handle_result)
