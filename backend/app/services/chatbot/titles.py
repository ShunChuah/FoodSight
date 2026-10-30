import re

GENERIC_TITLES = {"New Chat", "F&B Assistance", "F&B Business Analysis"}


def create_temporary_chat_title(message: str) -> str:
    clean_message = " ".join(message.strip().split())
    if not clean_message:
        return "New Chat"
    return f"{clean_message[:35]}..." if len(clean_message) > 35 else clean_message


def generated_title(value: object, message: str) -> str | None:
    if not isinstance(value, str):
        return None
    title = " ".join(value.strip().split()).strip(" .?!:;,-")
    if not title or _normalized_text(title) == _normalized_text(message) or title in GENERIC_TITLES:
        return None
    return " ".join(title.split()[:8])[:80] or None


def _normalized_text(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))
