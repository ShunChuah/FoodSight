"""HTTP client for the LLM (OpenAI Responses/Chat Completions or Gemini-style APIs).

Two tasks use it: "query" (writing the Cypher, cypher_generation.py) and "response" (writing the answer,
graph_answer.py). Each task has its own model and timeout settings in .env.
"""
import json
import math
import os
import re
import socket
import urllib.error
import urllib.request
from time import perf_counter
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

LLMTask = Literal["query", "response"]
TASK_MODEL_ENV = {
    "query": "LLM_QUERY_MODEL",
    "response": "LLM_RESPONSE_MODEL",
}
TASK_TIMEOUT_ENV = {
    "query": "LLM_QUERY_TIMEOUT_SECONDS",
    "response": "LLM_RESPONSE_TIMEOUT_SECONDS",
}
TASK_DEFAULT_TIMEOUTS = {
    "query": 15.0,
    "response": 15.0,
}
MIN_RESPONSE_BUDGET_SECONDS = 1.25
RESPONSE_DEADLINE_MARGIN_SECONDS = 0.25


class LLMServiceError(Exception):
    def __init__(self, user_message: str, *, code: Literal["error", "timeout"] = "error"):
        super().__init__(user_message)
        self.user_message = user_message
        self.code = code


def remaining_response_timeout(deadline: float | None) -> float | None:
    """None means no deadline was supplied, or too little response time remains."""
    if deadline is None:
        return None
    remaining = deadline - perf_counter() - RESPONSE_DEADLINE_MARGIN_SECONDS
    return remaining if remaining >= MIN_RESPONSE_BUDGET_SECONDS else None


def parse_json_object(raw: str | None) -> dict | None:
    """Read an object from plain or Markdown-fenced model JSON."""
    if not isinstance(raw, str) or not raw:
        return None
    cleaned = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE)
    if fenced:
        cleaned = fenced[1]
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def parse_answer_json(raw: str | None, *, max_length: int) -> str | None:
    """Read bounded answer text from model JSON."""
    payload = parse_json_object(raw)
    answer = payload.get("answer") if payload else None
    if not isinstance(answer, str):
        return None
    answer = answer.strip()
    return answer if answer and len(answer) <= max_length else None


def call_llm(
    prompt: str,
    instructions: str | None = None,
    *,
    task: LLMTask = "query",
    timeout_seconds: float | None = None,
    response_schema: dict | None = None,
) -> str | None:
    """Send one request and return the model's text. Raises LLMServiceError on any failure.

    instructions: the fixed rules (cached by the provider); prompt: this request's data.
    response_schema: a JSON schema the reply must follow (structured outputs, query task only).
    """
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = _get_llm_model(task)
    url = _get_llm_url(model)
    if not api_key or not url or not model:
        print(
            f"LLM {task} call skipped: API key, URL, or model is missing.",
            flush=True,
        )
        raise LLMServiceError(
            "The LLM service is not configured. Please check the backend "
            "LLM configuration."
        )
    payload, headers = _build_llm_request(
        prompt, model, task=task, response_schema=response_schema, instructions=instructions,
    )
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    configured_timeout = _get_llm_timeout(task)
    request_timeout = (
        max(0.5, min(configured_timeout, timeout_seconds))
        if timeout_seconds is not None
        else configured_timeout
    )
    print(f"[LLM] task={task} model={model} timeout_seconds={request_timeout:g}", flush=True)
    try:
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(f"LLM HTTP error {exc.code}: {error_body[:500]}", flush=True)
        raise LLMServiceError(_http_error_message(exc.code, error_body)) from exc
    except (TimeoutError, socket.timeout) as exc:
        print(f"LLM call timed out: {exc}", flush=True)
        raise LLMServiceError(
            "The LLM service timed out. Please try again later.", code="timeout",
        ) from exc
    except urllib.error.URLError as exc:
        if _is_timeout_error(exc.reason):
            print(f"LLM call timed out: {exc}", flush=True)
            raise LLMServiceError(
                "The LLM service timed out. Please try again later.", code="timeout",
            ) from exc
        print(f"LLM URL error: {exc}", flush=True)
        raise LLMServiceError(
            "The LLM service could not be reached. Please try again later."
        ) from exc
    except ConnectionError as exc:
        print(f"LLM connection error: {exc}", flush=True)
        raise LLMServiceError(
            "The LLM service could not be reached. Please try again later."
        ) from exc
    except json.JSONDecodeError as exc:
        print(f"LLM response was not valid JSON: {exc}", flush=True)
        raise LLMServiceError(
            "The LLM service returned an invalid response. Please try again."
        ) from exc

    _log_token_usage(data, task, model)
    # A reply cut off by the output-token limit is unusable JSON, so treat it as a failure.
    if data.get("status") == "incomplete" or any(
        choice.get("finish_reason") == "length" for choice in data.get("choices") or []
    ):
        raise LLMServiceError(
            "The LLM response was incomplete. Please try again."
        )
    text = _extract_llm_text(data)
    if not text:
        print(f"LLM returned no text: {json.dumps(data)[:500]}", flush=True)
    return text


def _get_llm_model(task: LLMTask) -> str:
    task_model = os.getenv(TASK_MODEL_ENV[task], "").strip()
    return task_model or os.getenv("LLM_MODEL", "").strip()


def _get_llm_url(model: str) -> str | None:
    url = os.getenv("LLM_API_URL", "").strip()
    return url.replace("{model}", model) if url else None


def _get_llm_timeout(task: LLMTask) -> float:
    legacy_timeout = os.getenv("LLM_TIMEOUT_SECONDS", "").strip()
    configured = os.getenv(TASK_TIMEOUT_ENV[task], "").strip() or legacy_timeout
    try:
        timeout = float(configured) if configured else TASK_DEFAULT_TIMEOUTS[task]
    except ValueError:
        timeout = TASK_DEFAULT_TIMEOUTS[task]
    return max(1.0, min(timeout, 60.0))


def _get_llm_style() -> str:
    return os.getenv("LLM_API_STYLE", "content").strip().lower()


def query_uses_structured_outputs() -> bool:
    return _get_llm_style() in {"responses", "chat"} and os.getenv(
        "LLM_QUERY_STRUCTURED_OUTPUTS", "true",
    ).strip().lower() == "true"


def _build_llm_request(
    prompt: str,
    model: str,
    *,
    task: LLMTask = "query",
    response_schema: dict | None = None,
    instructions: str | None = None,
) -> tuple[dict, dict[str, str]]:
    """Fixed rules go in the system/instructions slot; the request data goes in the user turn."""
    api_key = os.getenv("LLM_API_KEY", "").strip()
    style = _get_llm_style()
    headers = {"Content-Type": "application/json"}
    # Answer generation always expects a JSON object, so ask the provider for one.
    response_json = task == "response" and os.getenv("LLM_RESPONSE_JSON_MODE", "true").strip().lower() == "true"

    # LLM_API_STYLE: "content" (Gemini), "responses" (OpenAI Responses API) or "chat" (Chat Completions).
    if style == "content":
        headers["x-goog-api-key"] = api_key
        payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if instructions:
            payload["systemInstruction"] = {"parts": [{"text": instructions}]}
        if response_json:
            payload["generationConfig"] = {"responseMimeType": "application/json"}
        return payload, headers
    headers["Authorization"] = f"Bearer {api_key}"
    if style == "responses":
        payload = {"model": model, "input": prompt}
        if instructions:
            payload["instructions"] = instructions
        if response_json:
            payload["text"] = {"format": {"type": "json_object"}}
    else:
        messages = [{"role": "system", "content": instructions}] if instructions else []
        payload = {"model": model, "messages": [*messages, {"role": "user", "content": prompt}]}
        if response_json:
            payload["response_format"] = {"type": "json_object"}
    if task == "query":
        _configure_query_request(payload, model, style, response_schema)
    else:
        _configure_reasoning(payload, model, style, os.getenv("LLM_RESPONSE_REASONING_EFFORT", "low"))
    _mention_json_in_input(payload, style)
    return payload, headers


def _supports_reasoning_effort(model: str) -> bool:
    """GPT-5 / GPT-5-mini / GPT-5-nano accept a reasoning effort (including "minimal")."""
    return bool(re.fullmatch(r"gpt-5(?:-(?:mini|nano))?(?:-\d{4}-\d{2}-\d{2})?", model))


def _configure_reasoning(payload: dict, model: str, style: str, effort: str) -> None:
    """How long the model may "think" before answering; lower is faster."""
    effort = effort.strip().lower()
    if effort not in {"minimal", "low", "medium", "high"} or not _supports_reasoning_effort(model):
        return
    if style == "responses":
        payload["reasoning"] = {"effort": effort}
    elif style == "chat":
        payload["reasoning_effort"] = effort


def _mention_json_in_input(payload: dict, style: str) -> None:
    """OpenAI's json_object mode rejects a request (HTTP 400) unless the *input*
    messages mention JSON; text in the separate instructions field doesn't count."""
    if style == "responses":
        uses_json_object = (payload.get("text") or {}).get("format", {}).get("type") == "json_object"
        if uses_json_object and "json" not in payload["input"].lower():
            payload["input"] += "\n\nRespond with a JSON object."
    elif style == "chat":
        user = payload["messages"][-1]
        if (payload.get("response_format") or {}).get("type") == "json_object" and "json" not in user["content"].lower():
            user["content"] += "\n\nRespond with a JSON object."


def _configure_query_request(payload: dict, model: str, style: str, response_schema: dict | None = None) -> None:
    """Settings for the Cypher request: output-token limit, structured JSON output, minimal reasoning for speed."""
    configured_limit = os.getenv("LLM_QUERY_MAX_OUTPUT_TOKENS", "1024").strip()
    try:
        token_limit = int(configured_limit)
    except ValueError:
        token_limit = 1024
    token_limit = max(256, min(token_limit, 4096))
    json_mode = os.getenv("LLM_QUERY_JSON_MODE", "true").strip().lower() == "true"
    structured = bool(response_schema) and query_uses_structured_outputs()
    effort = os.getenv("LLM_QUERY_REASONING_EFFORT", "minimal").strip().lower()
    supports_minimal = _supports_reasoning_effort(model)
    if effort not in {"minimal", "low", "medium", "high"} or not supports_minimal:
        effort = None

    if style == "responses":
        payload["max_output_tokens"] = token_limit
        if structured:
            payload["text"] = {"format": {
                "type": "json_schema", "name": "cypher_generation",
                "strict": True, "schema": response_schema,
            }}
        elif json_mode:
            payload["text"] = {"format": {"type": "json_object"}}
        if effort:
            payload["reasoning"] = {"effort": effort}
        if supports_minimal:
            payload.setdefault("text", {})["verbosity"] = "low"
    else:
        payload["max_completion_tokens"] = token_limit
        if structured:
            payload["response_format"] = {
                "type": "json_schema", "json_schema": {
                    "name": "cypher_generation", "strict": True, "schema": response_schema,
                },
            }
        elif json_mode:
            payload["response_format"] = {"type": "json_object"}
        if effort:
            payload["reasoning_effort"] = effort
        if supports_minimal:
            payload["verbosity"] = "low"


def _log_token_usage(data: dict, task: LLMTask, model: str) -> None:
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return
    details = usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}
    values = {
        "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
        "output_tokens": usage.get("output_tokens", usage.get("completion_tokens")),
        "reasoning_tokens": details.get("reasoning_tokens") if isinstance(details, dict) else None,
    }
    input_details = usage.get("input_tokens_details", usage.get("prompt_tokens_details"))
    if isinstance(input_details, dict):
        values["cached_input_tokens"] = input_details.get("cached_tokens")
    counts = {key: value for key, value in values.items() if isinstance(value, int)}
    if counts:
        print(
            "[LLM_USAGE] " + json.dumps({"task": task, "model": model, **counts}),
            flush=True,
        )


def _extract_llm_text(data: dict) -> str | None:
    style = _get_llm_style()
    if style == "content":
        candidates = data.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts") if candidates else []
        text = "\n".join(part.get("text", "") for part in parts or [])
        return text.strip() or None
    if style == "responses":
        if data.get("output_text"):
            return str(data["output_text"]).strip() or None
        text_parts = [
            content["text"]
            for output in data.get("output") or []
            for content in output.get("content") or []
            if content.get("text")
        ]
        return "\n".join(text_parts).strip() or None

    choices = data.get("choices") or []
    content = choices[0].get("message", {}).get("content") if choices else None
    return content.strip() if isinstance(content, str) and content.strip() else None


def _http_error_message(status_code: int, error_body: str) -> str:
    if status_code == 429:
        retry_match = re.search(
            r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)s",
            error_body,
            flags=re.IGNORECASE,
        )
        if retry_match:
            retry_seconds = max(1, math.ceil(float(retry_match.group(1))))
            return (
                "The LLM service rate limit has been reached. Please try again "
                f"in about {retry_seconds} seconds."
            )
        return (
            "The LLM service rate limit has been reached. Please try again shortly."
        )
    return (
        f"The LLM service returned HTTP error {status_code}. "
        "Please try again later."
    )


def _is_timeout_error(error: object) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    return "timed out" in str(error).lower()
