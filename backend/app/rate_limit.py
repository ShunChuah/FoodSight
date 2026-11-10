# Per-user limits on chat messages, which each cost several LLM calls. Counts live in this process's memory, so
# with several API workers or replicas each keeps its own; move them to a shared store such as Redis then.

import math
import threading
import time
from collections import deque
from typing import Callable

from fastapi import Depends, HTTPException, status

from . import config
from .auth.backend import current_user
from .auth.models import User
from .services.shared.messages import response as user_response


class RateLimiter:
    def __init__(self, limits: tuple[tuple[int, float], ...], clock: Callable[[], float] = time.monotonic):
        self.limits = tuple((count, seconds) for count, seconds in limits if count > 0)
        self.window = max((seconds for _, seconds in self.limits), default=0)
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    # Counts the request and returns 0, or returns the whole seconds to wait without counting it.
    def hit(self, key: str) -> int:
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            wait = 0.0
            for count, seconds in self.limits:
                recent = [moment for moment in hits if moment > now - seconds]
                if len(recent) >= count:
                    # A slot frees up when the oldest request that still counts leaves the window.
                    wait = max(wait, recent[-count] + seconds - now)
            if wait > 0:
                return max(1, math.ceil(wait))
            hits.append(now)
            return 0


chat_limiter = RateLimiter(((config.CHAT_LIMIT_PER_MINUTE, 60), (config.CHAT_LIMIT_PER_DAY, 24 * 60 * 60)))


def wait_text(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} second{'' if seconds == 1 else 's'}"
    if seconds < 60 * 60:
        minutes = math.ceil(seconds / 60)
        return f"{minutes} minute{'' if minutes == 1 else 's'}"
    hours = math.ceil(seconds / 3600)
    return f"{hours} hour{'' if hours == 1 else 's'}"


def limit_chat(user: User = Depends(current_user)) -> None:
    wait = chat_limiter.hit(f"user:{user.id}")
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=user_response("interface.rate_limited", wait=wait_text(wait)),
            headers={"Retry-After": str(wait)},
        )
