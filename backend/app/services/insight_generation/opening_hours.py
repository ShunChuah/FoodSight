import re
from datetime import datetime
from typing import Any

from ..shared.config import app_timezone
from .presentation import time_label

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def now_local() -> datetime:
    return datetime.now(app_timezone())


def weekday_today() -> str:
    return WEEKDAYS[now_local().weekday()]


OPEN_NOW_WORDS = re.compile(r"\b(?:open (?:right )?now|currently open|still open|open at the moment)\b", re.IGNORECASE)
LATE_WORDS = re.compile(r"\b(?:supper|late[- ]night|late at night|open(?:s|ing)? (?:till |until )?late)\b",
                        re.IGNORECASE)
LATE_HOUR, NIGHT_ENDS_HOUR = 23, 5
CLOCK_TIME = re.compile(r"\b(?:after|past|at|by|around)\s+(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)\b", re.IGNORECASE)


def time_asked(question: str, now: datetime) -> datetime | None:
    clock = CLOCK_TIME.search(question or "")
    if clock:
        hour = int(clock.group(1)) % 12 + (12 if clock.group(3).lower() == "pm" else 0)
        return now.replace(hour=hour, minute=int(clock.group(2) or 0), second=0, microsecond=0)
    if OPEN_NOW_WORDS.search(question or ""):
        return now
    if LATE_WORDS.search(question or ""):
        # During the night itself, supper means open right now.
        if now.hour >= LATE_HOUR or now.hour < NIGHT_ENDS_HOUR:
            return now
        return now.replace(hour=LATE_HOUR, minute=0, second=0, microsecond=0)
    return None


# A range past midnight ("18:00-02:00") counts until it ends, also from yesterday's hours.
def open_now(hours_today: Any, now: datetime, hours_yesterday: Any = None) -> bool | None:
    if hours_today == "open 24 hours":
        return True
    minute = now.hour * 60 + now.minute
    if any(end <= start and minute < end for start, end in _ranges(hours_yesterday)):
        return True
    if not isinstance(hours_today, str):
        return None
    if hours_today.strip().lower() == "closed":
        return False
    ranges = _ranges(hours_today)
    if not ranges:
        return None
    return any(start <= minute < (end if end > start else 24 * 60) for start, end in ranges)


def opens_next(weekly_hours: dict[str, Any] | None, now: datetime) -> str | None:
    hours = weekly_hours or {}
    minute = now.hour * 60 + now.minute
    later = [start for start, _ in _ranges(hours.get(WEEKDAYS[now.weekday()])) if start > minute]
    if later:
        return f"{_clock(min(later))} today"
    tomorrow = [start for start, _ in _ranges(hours.get(WEEKDAYS[(now.weekday() + 1) % 7]))]
    return f"{_clock(min(tomorrow))} tomorrow" if tomorrow else None


def _ranges(hours: Any) -> list[tuple[int, int]]:
    if not isinstance(hours, str):
        return []
    return [(int(sh) * 60 + int(sm), int(eh) * 60 + int(em))
            for sh, sm, eh, em in re.findall(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})", hours)]


def _clock(minute: int) -> str:
    return time_label(minute // 60, minute % 60)


def _yesterday(weekly_hours: dict[str, Any] | None, moment: datetime) -> Any:
    return (weekly_hours or {}).get(WEEKDAYS[(moment.weekday() - 1) % 7])
