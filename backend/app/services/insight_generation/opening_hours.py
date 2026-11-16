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


LATE_HOUR, NIGHT_ENDS_HOUR = 23, 5


# The moment a place must be open, from intent time ("now", "late" or "HH:MM").
def time_asked(intent: dict[str, Any] | None, now: datetime) -> datetime | None:
    time = str((intent or {}).get("time") or "")
    clock = re.fullmatch(r"(\d{1,2}):(\d{2})", time)
    if clock:
        return now.replace(hour=int(clock.group(1)), minute=int(clock.group(2)), second=0, microsecond=0)
    if time == "now":
        return now
    if time == "late":
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
