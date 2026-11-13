# Spoken explanations for the Cinematic AI map tour, from OpenAI's text-to-speech (gpt-4o-mini-tts).
# Each line is made once and kept in the database, so replaying a tour costs nothing.

import hashlib
import json
import os
import socket
import urllib.error
import urllib.request

from .llm import SSL_CONTEXT

SPEECH_URL = "https://api.openai.com/v1/audio/speech"
DEFAULT_MODEL = "gpt-4o-mini-tts"
DEFAULT_VOICE = "coral"
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_NARRATION_CHARACTERS = 600
STYLE = """Context: This is one line from a continuous narrated map tour of food places in Petaling Jaya, Malaysia. Every line must sound like the same take by the same person.
Voice: A friendly local tour guide. Warm, clear and composed.
Tone: Steady and neutral-warm on every line. Do not act out the content. Words like lively, exciting, top pick, quiet or calm do not change the energy.
Pacing: The same moderate, even pace throughout, about 160 words per minute. Do not speed up or slow down between lines.
Pitch and energy: Keep the same pitch range and energy level from start to finish, with no dramatic emphasis.
Pauses: A short natural pause at commas and full stops only.
Pronunciation: Say RM as ringgit. Pronounce Malaysian place and restaurant names naturally."""


class SpeechError(Exception):
    pass


def _setting(name: str, default: str) -> str:
    return os.getenv(name, "").strip() or default


def speech_settings() -> dict:
    return {"model": _setting("NARRATION_MODEL", DEFAULT_MODEL), "voice": _setting("NARRATION_VOICE", DEFAULT_VOICE),
            "instructions": _setting("NARRATION_STYLE", STYLE)}


# The same words in the same voice and style always give the same audio, so this names its saved copy.
def narration_key(text: str, settings: dict | None = None) -> str:
    settings = settings or speech_settings()
    source = json.dumps([settings["model"], settings["voice"], settings["instructions"], text], ensure_ascii=False)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def synthesise(text: str, settings: dict | None = None) -> bytes:
    settings = settings or speech_settings()
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if not api_key:
        raise SpeechError("The speech service is not configured.")
    try:
        timeout = max(2.0, min(float(_setting("NARRATION_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))), 60.0))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_SECONDS
    payload = {**settings, "input": text, "response_format": "mp3"}
    request = urllib.request.Request(
        _setting("NARRATION_API_URL", SPEECH_URL), data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
            audio = response.read()
    except urllib.error.HTTPError as exc:
        print(f"Speech HTTP error {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}", flush=True)
        raise SpeechError(f"The speech service returned HTTP error {exc.code}.") from exc
    except (TimeoutError, socket.timeout, urllib.error.URLError, ConnectionError) as exc:
        print(f"Speech call failed: {exc}", flush=True)
        raise SpeechError("The speech service could not be reached.") from exc
    if not audio:
        raise SpeechError("The speech service returned no audio.")
    print(f"Speech made: {len(text)} characters, {len(audio):,} bytes, {settings['model']}/{settings['voice']}", flush=True)
    return audio
