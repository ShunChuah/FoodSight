import re
from typing import Any

from ..shared.diagnostics import kg_debug, note_turn

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
CLOCK = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\b", re.IGNORECASE)
NOT_CHECKED = {"record_id", "fields"}


def _numbers(text: str) -> list[float]:
    found = []
    for match in NUMBER.findall(CLOCK.sub(" ", text)):
        try:
            found.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return found


# A figure is supported when the prompt holds it, allowing rounding ("about 1,500" for 1,503, "RM36" for RM36.80),
# but not for small decimals such as ratings (4.9 is not 4.8). Small whole numbers ("three places", "PJU 5") pass.
def _supported(sentence: str, known: list[float]) -> bool:
    return all((value.is_integer() and value <= 12)
               or any(abs(value - figure) <= (max(1.0, 0.02 * figure) if figure >= 10 else 0.05) for figure in known)
               for value in _numbers(sentence))


# The answer model explains the figures; a sentence with a figure it was not given is dropped, not shown.
def _checked_payload(payload: Any, known: list[float], streaming: bool = False) -> Any:
    if isinstance(payload, dict):
        return {name: value if name in NOT_CHECKED else _checked_payload(value, known, streaming)
                for name, value in payload.items()}
    if isinstance(payload, list):
        return [_checked_payload(item, known, streaming) for item in payload]
    if not isinstance(payload, str):
        return payload
    sentences = re.split(r"(?<=[.!?])\s+", payload)
    unfinished = sentences.pop() if streaming and sentences and not sentences[-1].rstrip().endswith((".", "!", "?")) \
        else None
    kept = [sentence for sentence in sentences if _supported(sentence, known)]
    if len(kept) < len(sentences) and not streaming:
        dropped = [sentence for sentence in sentences if sentence not in kept]
        kg_debug("Dropped sentences with figures not in the evidence", dropped)
        note_turn(unsupported_figures=dropped)
    return " ".join(kept + ([unfinished] if unfinished else [])).strip()
