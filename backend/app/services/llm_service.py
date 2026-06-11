import json
import math
import os
import re
import socket
import urllib.error
import urllib.request
from typing import Any

from dotenv import load_dotenv

load_dotenv()


TITLE_SYSTEM_PROMPT = """
Create a short plain-text chat title from the user's first query.

Rules:
- Use 3 to 7 words only.
- Use letters, numbers, and spaces only.
- Do not use emojis, symbols, markdown, quotation marks, brackets, slashes, hyphens, or punctuation.
- Preserve important place names.
- Do not add explanations.
- Return only the title text.
""".strip()

FNB_SCOPE_PROMPT = """
Classify whether the user's question is related to Food & Beverage.
F&B includes restaurants, cafes, food, drinks, cuisines, dining, reviews,
pricing, restaurant locations, customer demand, competitors, and F&B market
or location intelligence.

Use the conversation history to understand short follow-up questions.

Return exactly one line:
- FNB
- NOT_FNB | A short reason

Do not answer the user's question.
""".strip()


class LLMServiceError(Exception):
    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


def call_llm(prompt: str, instructions: str | None = None) -> str | None:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    url = _get_llm_url()
    if not api_key or not url:
        print("LLM call skipped: LLM_API_KEY or LLM_API_URL is missing.", flush=True)
        raise LLMServiceError(
            "The LLM service is not configured. Please check the backend "
            "LLM configuration."
        )

    full_prompt = f"{instructions}\n\n{prompt}" if instructions else prompt
    payload, headers = _build_llm_request(full_prompt)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        print(f"LLM HTTP error {exc.code}: {error_body[:500]}", flush=True)
        raise LLMServiceError(_http_error_message(exc.code, error_body)) from exc
    except (TimeoutError, socket.timeout) as exc:
        print(f"LLM call timed out: {exc}", flush=True)
        raise LLMServiceError(
            "The LLM service timed out. Please try again later."
        ) from exc
    except urllib.error.URLError as exc:
        if _is_timeout_error(exc.reason):
            print(f"LLM call timed out: {exc}", flush=True)
            raise LLMServiceError(
                "The LLM service timed out. Please try again later."
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

    text = _extract_llm_text(data)
    if not text:
        print(f"LLM returned no text: {json.dumps(data)[:500]}", flush=True)
    return text


def generate_chat_title(first_query: str) -> str:
    try:
        title = call_llm(first_query, TITLE_SYSTEM_PROMPT)
    except LLMServiceError:
        title = None
    return title[:160] if title else _fallback_title(first_query)


def classify_fnb_query(
    user_query: str,
    conversation_context: str,
) -> tuple[bool, str | None]:
    try:
        classification = call_llm(
            (
                f"Conversation history:\n{conversation_context}\n\n"
                f"Current user question:\n{user_query}"
            ),
            FNB_SCOPE_PROMPT,
        )
    except LLMServiceError as exc:
        print(f"F&B scope classification unavailable: {exc.user_message}", flush=True)
        return False, "the question could not be confirmed as Food & Beverage related"
    if not classification:
        return False, "the LLM service could not classify the question"

    classification = classification.strip()
    if classification.upper() == "FNB":
        return True, None
    if classification.upper().startswith("NOT_FNB"):
        _, separator, reason = classification.partition("|")
        clean_reason = " ".join(reason.strip().split())[:240] if separator else ""
        return False, clean_reason or "it is outside Food & Beverage"
    return False, "the question could not be confirmed as Food & Beverage related"


def generate_graph_query_response(
    user_query: str,
    schema_context: str,
    assumption_context: str,
    conversation_context: str,
    location_context: str,
    retry_note: str | None = None,
) -> str | None:
    generated = call_llm(
        _build_cypher_prompt(
            user_query,
            schema_context,
            assumption_context,
            conversation_context,
            location_context,
            retry_note,
        )
    )
    return generated


def repair_cypher(
    user_query: str,
    cypher: str,
    error_message: str,
    schema_context: str,
    assumption_context: str,
    conversation_context: str,
    location_context: str,
) -> str | None:
    prompt = f"""
Repair this read-only Neo4j Cypher query.
Return exactly one corrected Cypher query and no explanation.
Use only the provided graph schema and never use write clauses.

Graph schema:
{schema_context}

Relevant query assumptions:
{assumption_context}

User question:
{user_query}

Conversation history:
{conversation_context}

Location context:
{location_context}

Invalid query:
{cypher}

Validation or Neo4j error:
{error_message}
""".strip()
    repaired = call_llm(prompt)
    return repaired


def generate_graph_insight(
    user_query: str,
    rows: list[dict[str, Any]],
    conversation_context: str,
    location_context: str,
) -> str | None:
    prompt = f"""
You are FoodSight, an AI-first location intelligence chatbot for F&B discovery.
Use the Neo4j graph query results to answer the user clearly and concisely.
Mention the graph evidence behind your recommendation.

User question:
{user_query}

Conversation history:
{conversation_context}

Location context:
{location_context}

Graph rows as JSON:
{json.dumps(rows, default=str, ensure_ascii=False)}
""".strip()
    return call_llm(prompt)


def _build_cypher_prompt(
    user_query: str,
    schema_context: str,
    assumption_context: str,
    conversation_context: str,
    location_context: str,
    retry_note: str | None = None,
) -> str:
    retry_instruction = (
        f"\nPrevious generation problem:\n{retry_note}\nGenerate a corrected response."
        if retry_note
        else ""
    )
    return f"""
You generate read-only Neo4j Cypher for FoodSight, an F&B knowledge graph.

Rules:
- First decide whether the request has enough clear and consistent information
  to generate a reliable Cypher query.
- If required information is missing, unclear, ambiguous, or conflicting,
  return CLARIFY immediately and do not generate Cypher.
- Treat opposite criteria as conflicts, including cheap/budget/affordable
  together with expensive/premium/luxury.
- Use only labels, relationships, and properties in the schema.
- Return exactly one line:
  CYPHER | <one read-only Cypher query>
  CLARIFY | <one short clarification question>
- Use MATCH, OPTIONAL MATCH, WHERE, WITH, RETURN, ORDER BY, and LIMIT only.
- Return 3 options by default, or the user's explicit requested number.
- Use conversation history to resolve follow-up references.
- Use the provided location context when the current question omits location.
- With coordinates, use Restaurant-[:LOCATED_AT]->Location.
- Do not invent graph fields or important filters.
- Use the relevant query assumptions when they apply, but only with fields
  present in the graph schema.
- Return CLARIFY for missing required information, unclear references, overly
  broad requests, conflicting criteria, or unsupported conditions.
- Do not clarify optional details when a documented default applies.

Clarification examples:
- "Find cheap expensive cafes":
  CLARIFY | Should I prioritize cheap cafes or expensive cafes?
- "Which one is better?" without identifiable choices:
  CLARIFY | Which restaurants or areas would you like me to compare?
- "Recommend food":
  CLARIFY | What cuisine, dish, price, or area do you prefer?
- "Suggest a place for dinner" without location context:
  CLARIFY | Which area or location would you like me to search?
- "Find the most viral restaurant" when popularity is unavailable:
  CLARIFY | Popularity is unavailable. Would you prefer rating, price, cuisine, or location?

Graph schema:
{schema_context}

Relevant query assumptions:
{assumption_context}

Conversation history:
{conversation_context}

Location context:
{location_context}

Current user question:
{user_query}
{retry_instruction}
""".strip()


def _get_llm_url() -> str | None:
    url = os.getenv("LLM_API_URL", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    return url.replace("{model}", model) if url else None


def _get_llm_style() -> str:
    return os.getenv("LLM_API_STYLE", "content").strip().lower()


def _build_llm_request(prompt: str) -> tuple[dict, dict[str, str]]:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL", "").strip()
    style = _get_llm_style()
    headers = {"Content-Type": "application/json"}

    if style == "content":
        headers["x-goog-api-key"] = api_key
        return {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}, headers
    if style == "responses":
        headers["Authorization"] = f"Bearer {api_key}"
        return {"model": model, "input": prompt}, headers

    headers["Authorization"] = f"Bearer {api_key}"
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }, headers


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


def _fallback_title(message: str) -> str:
    clean_message = " ".join(message.strip().split())
    return f"{clean_message[:35]}..." if len(clean_message) > 35 else clean_message
