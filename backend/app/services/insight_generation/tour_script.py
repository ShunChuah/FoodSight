# The Cinematic AI tour's words: one model call, made when Play is first pressed, ties each step of the map
# tour to the user's question and says why each place fits it. Only facts from the answer's map may be used,
# and a step that mentions a number not in its facts is dropped, so the app's own wording is used for it.

import json
import math
import re
from typing import Any

from ..shared.llm import LLMServiceError, call_llm, parse_json_object

MAX_STEPS = 20
MAX_FACILITIES = 15
MAX_ANSWER_CHARACTERS = 2500
LIMITS = {"title": 70, "caption": 170, "narration": 420}
STEP_ID = re.compile(r"^(areas|radius|places|finish|area:.{1,120}|place:restaurant:.{1,120})$")
SUMMARY_KINDS = {"closing", "places found", "areas compared"}
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
PLACE_FACTS = (
    "cuisines", "restaurant_type", "venue_type", "average_rating", "review_count", "average_price", "price_tier",
    "distance_m", "area", "summary", "ambiance", "good_for", "service_style", "halal_status", "hours_today", "facilities",
)

INSTRUCTIONS = """You write the script for a short guided map tour that explains a food and drink answer in Petaling Jaya, Malaysia.
The tour shows the steps one by one on a map, with a title and caption on screen and a narration read aloud.

Return JSON: {"steps": {"<step id>": {"title": "...", "caption": "...", "narration": "..."}}} with one entry for every step id given.

Rules:
- Tie every step to what the user asked. For each place, explain why it fits their request (for example quiet for studying, open late, halal, cheap, close by), using only that step's facts and the answer text.
- Use only the facts given, with figures exactly as written (times may be said in 12-hour form). Never invent ratings, prices, distances, hours, features or names. If a fact is not given, leave it out.
- Places are shown from the lowest rank up to number 1. Say that number 1 is the top pick.
- Each step has its own job. Never repeat a point an earlier step already made.
  - search circle: where the search was centred and how far it reached.
  - areas compared: which areas were compared and what they were compared on.
  - places found: how many places matched and what the group has in common or how it varies (for example the price spread or opening hours). This is the only step that says the order, from the last up to number 1. Do not restate the question.
  - place: what this place is, then why it fits the request.
  - closing: help the user choose, by which place suits which need. Do not retell each place.
- title: at most 60 characters. Only a place title starts with "#<rank> <name>", and an area with a rank "#<rank> <area>". Every other title is a short heading without "#", such as "Five quiet cafes matched".
- Write times in 12-hour form, such as 9 am or 2:45 pm, never 09:00 or 14:45.
- caption: shown on screen, one or two short sentences, at most 150 characters. RM and km are fine here.
- narration: read aloud, one to three sentences, at most 60 words. Write words that sound right when spoken: "15 ringgit", "3 kilometres", "400 metres", "number 2". No symbols, markdown, emoji or lists.
- Write complete, friendly sentences without semicolons. Do not start every step the same way.
- The narrations are read aloud one by one, so keep them even in tone and length: every place narration is two sentences of about 30 to 45 words, saying first what the place is and then why it fits the request. Plain, calm wording, with no exclamation marks and no hype words such as amazing, perfect or must-try.
- Keep the user's language if the question is not in English."""


def _feature_steps(map_data: dict) -> dict[str, dict]:
    # Matches the app's place ids (mapPlaces.js): only drawable points count, ranked in their map order.
    features = [feature for feature in ((map_data.get("feature_collection") or {}).get("features") or [])
                if _drawable(feature)]
    steps = {}
    for index, feature in enumerate(features):
        properties = feature.get("properties") or {}
        facts = {"rank": index + 1, "name": properties.get("label")}
        for key in PLACE_FACTS:
            value = properties.get(key)
            if value in (None, "", [], {}):
                continue
            facts[key] = value[:MAX_FACILITIES] if key == "facilities" and isinstance(value, list) else value
        steps[f"place:restaurant:{feature.get('id') if feature.get('id') is not None else index}"] = facts
    return steps


def _drawable(feature: Any) -> bool:
    geometry = feature.get("geometry") if isinstance(feature, dict) else None
    coordinates = (geometry or {}).get("coordinates")
    return (isinstance(geometry, dict) and geometry.get("type") == "Point" and isinstance(coordinates, list)
            and len(coordinates) >= 2 and all(isinstance(value, (int, float)) and math.isfinite(value) for value in coordinates[:2])
            and abs(coordinates[0]) <= 180 and abs(coordinates[1]) <= 90)


def tour_steps(map_data: dict | None, step_ids: list[str]) -> list[dict]:
    if not isinstance(map_data, dict):
        return []
    places = _feature_steps(map_data)
    overlays = {overlay.get("id"): overlay for overlay in map_data.get("overlays") or [] if isinstance(overlay, dict)}
    areas = [overlay for overlay in overlays.values() if overlay.get("kind") == "area"]
    radius = next((overlay for overlay in overlays.values() if overlay.get("kind") == "radius"), None)
    steps = []
    for step_id in dict.fromkeys(step_ids):
        if not isinstance(step_id, str) or not STEP_ID.match(step_id):
            continue
        if step_id in places:
            steps.append({"id": step_id, "kind": "place", "facts": places[step_id]})
        elif step_id.startswith("area:") and step_id[5:] in overlays:
            overlay = overlays[step_id[5:]]
            steps.append({"id": step_id, "kind": "area", "facts": {"name": overlay.get("label"), **(overlay.get("properties") or {})}})
        elif step_id == "radius" and radius:
            steps.append({"id": step_id, "kind": "search circle",
                          "facts": {"centre": radius.get("label"), **(radius.get("properties") or {})}})
        elif step_id == "areas" and areas:
            steps.append({"id": step_id, "kind": "areas compared", "facts": {"areas": [area.get("label") for area in areas]}})
        elif step_id == "places" and places:
            steps.append({"id": step_id, "kind": "places found", "facts": {"places": len(places),
                                                                           "shown": sum(step in places for step in step_ids)}})
        elif step_id == "finish":
            steps.append({"id": step_id, "kind": "closing", "facts": {}})
        if len(steps) >= MAX_STEPS:
            break
    return steps


def _numbers(value: Any) -> set[str]:
    found = set()
    for match in NUMBER.findall(json.dumps(value, ensure_ascii=False)):
        number = match.replace(",", "")
        found.add(number)
        try:
            amount = float(number)
        except ValueError:
            continue
        # The same figure said another way: 3000 m is 3 km, 15.0 is 15, 4.65 rounds to 4.7.
        for figure in (amount, amount / 1000, round(amount), round(amount, 1)):
            found.add(f"{figure:g}")
        if amount.is_integer() and 0 <= amount <= 24:
            found.add(str(int(amount) % 12 or 12))  # 22:00 may be said as 10 pm
    return found | {"5"}  # a rating "out of 5"


# A 24-hour time; one already followed by am or pm is left alone.
CLOCK = r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*[aApP]\.?[mM]\b)"
CLOCK_RANGE = re.compile(CLOCK + r"(?:\s*[-–]\s*" + CLOCK + ")?")


def _clock(hour: str, minute: str) -> str:
    hour_number = int(hour)
    return f"{hour_number % 12 or 12}{'' if minute == '00' else ':' + minute} {'am' if hour_number < 12 else 'pm'}"


# 24-hour times from the data become 12-hour ones: "09:00-14:45" reads "9 am–2:45 pm", or "9 am to 2:45 pm" aloud.
def twelve_hour(text: str, spoken: bool = False) -> str:
    def convert(match: re.Match) -> str:
        first = _clock(match.group(1), match.group(2))
        if match.group(3) is None:
            return first
        return first + (" to " if spoken else "–") + _clock(match.group(3), match.group(4))

    return CLOCK_RANGE.sub(convert, text)


def _tidy(text: str, limit: int, key: str = "caption") -> str:
    text = " ".join(text.replace("**", "").split())
    text = twelve_hour(text, spoken=key == "narration")
    if key == "title":
        text = re.sub(r"^#(?!\d)\S*\s*", "", text)  # "#closing tour complete" -> "tour complete"
        text = text[:1].upper() + text[1:]
    text = re.sub(r";\s*(\w)", lambda match: ". " + match.group(1).upper(), text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",")
    return cut + ("" if cut.endswith((".", "!", "?")) else "…")


def checked_script(reply: dict | None, steps: list[dict], context: str) -> dict[str, dict]:
    written = (reply or {}).get("steps")
    if not isinstance(written, dict):
        return {}
    shared = _numbers(context) | {str(number) for number in range(1, len(steps) + 1)}
    every_fact = _numbers([step["facts"] for step in steps])
    script, summaries = {}, {}
    for step in steps:
        entry = written.get(step["id"])
        if not isinstance(entry, dict):
            continue
        lines = {key: _tidy(entry[key], LIMITS[key], key) for key in LIMITS if isinstance(entry.get(key), str) and entry[key].strip()}
        if len(lines) < 3:
            continue
        # The overview and closing sum up the whole tour, so they may use any step's facts.
        allowed = shared | (every_fact if step["kind"] in SUMMARY_KINDS else _numbers(step["facts"]))
        stated = {number.replace(",", "") for line in lines.values() for number in NUMBER.findall(line)}
        if not stated <= allowed:
            print(f"Tour step {step['id']} dropped: numbers {sorted(stated - allowed)} are not in its facts", flush=True)
            continue
        repeated = next((earlier for earlier, words in summaries.items()
                         if step["kind"] in SUMMARY_KINDS and _overlap(_content_words(lines["narration"]), words) >= REPEAT_OVERLAP), None)
        if repeated:
            print(f"Tour step {step['id']} dropped: it repeats {repeated}", flush=True)
            continue
        if step["kind"] in SUMMARY_KINDS:
            summaries[step["id"]] = _content_words(lines["narration"])
        script[step["id"]] = lines
    return script


# The overview and closing each have their own job; one that mostly repeats the other is dropped,
# and the app's own wording plays for it instead.
REPEAT_OVERLAP = 0.35  # a real repeat scored 0.41; separate summary lines scored 0.21 or less
FILLER = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "from", "with", "that", "this", "these", "is", "are",
    "it", "its", "i", "you", "your", "will", "be", "as", "at", "by", "up", "each", "which", "why", "how", "what", "so",
    "here", "there", "they", "we", "my", "me", "can", "may", "go", "through", "show", "number",
}


def _stem(word: str) -> str:
    # Rough, so "cafes" meets "cafe" and "studying" meets "study".
    for ending in ("ing", "ies", "ed", "es", "s", "y"):
        if word.endswith(ending) and len(word) - len(ending) >= 3:
            return word[: -len(ending)]
    return word


def _content_words(text: str) -> set[str]:
    return {_stem(word) for word in re.findall(r"[a-z0-9']+", text.lower()) if word not in FILLER}


def _overlap(first: set[str], second: set[str]) -> float:
    return len(first & second) / min(len(first), len(second)) if first and second else 0.0


def write_tour_script(questions: list[str], answer: str, steps: list[dict], timeout_seconds: float = 25.0) -> dict[str, dict]:
    if not steps:
        return {}
    question = questions[-1] if questions else ""
    payload = {
        "question": question,
        "earlier_questions": questions[:-1],
        "answer_shown_to_the_user": answer[:MAX_ANSWER_CHARACTERS],
        "steps": steps,
    }
    try:
        reply = call_llm(json.dumps(payload, ensure_ascii=False, default=str), INSTRUCTIONS, task="response",
                         timeout_seconds=timeout_seconds)
    except LLMServiceError as exc:
        print(f"Tour script not written: {exc.user_message}", flush=True)
        return {}
    return checked_script(parse_json_object(reply), steps, " ".join([*questions, answer]))
