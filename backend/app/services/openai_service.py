import os
import json
import urllib.error
import urllib.request


MOCK_ANSWER = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim "
    "veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea "
    "commodo consequat. Duis aute irure dolor in reprehenderit in voluptate "
    "velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint "
    "occaecat cupidatat non proident, sunt in culpa qui officia deserunt "
    "mollit anim id est laborum."
)

MOCK_MAP_IMAGE = "https://leafletjs.com/examples/quick-start/thumbnail.png"

CHAT_SYSTEM_PROMPT = """
You are FoodSight, an AI-first location intelligence chatbot for F&B discovery.
Answer user questions with practical, location-aware recommendations. Keep the
answer concise, explain your reasoning briefly, and mention location context when
it is available. If exact live business data is unavailable, say what extra data
would improve the recommendation.

Response format:
- For questions that need multiple recommendations, reasons, comparisons, or
  steps, answer as a short explanation followed by a numbered list.
- Use this numbered list format:
  1. Point name
     - One concise paragraph explaining the point.
  2. Point name
     - One concise paragraph explaining the point.
  3. Point name
     - One concise paragraph explaining the point.
- Put a blank line between numbered items.
- Do not use markdown bold markers like ** around point names.
- For simple questions, answer with one short normal paragraph instead.
- Avoid long markdown sections unless the user explicitly asks for detailed
  analysis.
""".strip()

TITLE_SYSTEM_PROMPT = """
Create a short chat title from the user's first query.
Rules:
- 3 to 7 words.
- No quotation marks.
- No trailing punctuation.
- Preserve important place names.
""".strip()


def _get_ai_provider() -> str:
    return os.getenv("AI_PROVIDER", "gemini").strip().lower()


def _get_openai_client():
    # Missing key or SDK keeps development/demo mode on the mock response.
    if not os.getenv("OPENAI_API_KEY"):
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    return OpenAI()


def _get_openai_model() -> str:
    # Allows model changes from .env without editing code.
    return os.getenv("OPENAI_MODEL", "gpt-5.2")


def _get_gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _call_gemini(prompt: str) -> str | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None

    model = _get_gemini_model()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ]
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None

    candidates = data.get("candidates") or []
    if not candidates:
        return None

    parts = candidates[0].get("content", {}).get("parts") or []
    text_parts = [part.get("text", "") for part in parts if part.get("text")]
    text = "\n".join(text_parts).strip()
    return text or None


def _format_chat_prompt(messages: list[dict[str, str]]) -> str:
    turns = []
    for message in messages:
        role = "Assistant" if message["role"] == "assistant" else "User"
        turns.append(f"{role}: {message['content']}")

    return f"{CHAT_SYSTEM_PROMPT}\n\nConversation:\n" + "\n".join(turns)


def generate_chat_title(first_query: str) -> str:
    # Uses the first query to create a short title for the sidebar.
    if _get_ai_provider() == "gemini":
        title = _call_gemini(f"{TITLE_SYSTEM_PROMPT}\n\nUser query: {first_query}")
        return title[:160] if title else _fallback_title(first_query)

    client = _get_openai_client()
    if not client:
        return _fallback_title(first_query)

    try:
        response = client.responses.create(
            model=_get_openai_model(),
            instructions=TITLE_SYSTEM_PROMPT,
            input=first_query,
        )
    except Exception:
        return _fallback_title(first_query)

    title = response.output_text.strip()
    return title[:160] if title else _fallback_title(first_query)


def generate_assistant_response(messages: list[dict[str, str]]) -> tuple[str, str | None]:
    # Sends the current chat context to the configured AI provider.
    if _get_ai_provider() == "gemini":
        answer = _call_gemini(_format_chat_prompt(messages))
        print("\nGemini raw response:\n", answer, "\n", flush=True)
        return answer or MOCK_ANSWER, MOCK_MAP_IMAGE

    client = _get_openai_client()
    if not client:
        return MOCK_ANSWER, MOCK_MAP_IMAGE

    try:
        response = client.responses.create(
            model=_get_openai_model(),
            instructions=CHAT_SYSTEM_PROMPT,
            input=messages,
        )
    except Exception:
        return MOCK_ANSWER, MOCK_MAP_IMAGE

    answer = response.output_text.strip()
    print("\nOpenAI raw response:\n", answer, "\n", flush=True)
    return answer or MOCK_ANSWER, MOCK_MAP_IMAGE


def _fallback_title(message: str) -> str:
    # Local title generator used when OpenAI is unavailable.
    clean_message = " ".join(message.strip().split())
    return f"{clean_message[:35]}..." if len(clean_message) > 35 else clean_message
