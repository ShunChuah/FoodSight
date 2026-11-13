# In-process caches with expiry, emptied on restart. <NAME>_CACHE_TTL_SECONDS=0 in .env switches one off.

import hashlib
import json
import os
from collections import OrderedDict
from threading import Lock
from time import monotonic, perf_counter
from typing import Any

from .diagnostics import log_timing

MAX_ENTRIES = 512


class TTLCache:
    def __init__(self, name: str, default_ttl_seconds: float, max_entries: int = MAX_ENTRIES):
        self.name = name
        self.default_ttl_seconds = default_ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = Lock()

    @property
    def ttl_seconds(self) -> float:
        try:
            return max(0.0, float(os.getenv(f"{self.name.upper()}_CACHE_TTL_SECONDS", self.default_ttl_seconds)))
        except ValueError:
            return self.default_ttl_seconds

    def get(self, *key_parts: Any) -> Any | None:
        if not self.ttl_seconds:
            return None
        started_at = perf_counter()
        key = _key(key_parts)
        with self._lock:
            entry = self._entries.get(key)
            if entry and entry[0] > monotonic():
                self._entries.move_to_end(key)
                log_timing(f"cache.{self.name}", started_at, status="hit")
                return entry[1]
            self._entries.pop(key, None)
        return None

    def set(self, value: Any, *key_parts: Any) -> None:
        ttl = self.ttl_seconds
        if not ttl:
            return
        with self._lock:
            self._entries[_key(key_parts)] = (monotonic() + ttl, value)
            self._entries.move_to_end(_key(key_parts))
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def _key(parts: tuple) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# Callers store a model reply only after it passed validation.
QUERY_REPLIES = TTLCache("llm_query", 1800)
ANSWER_REPLIES = TTLCache("llm_answer", 600)
# Short while the graph data is still changing.
GRAPH_ROWS = TTLCache("neo4j", 300)


def clear_all() -> None:
    for cache in (QUERY_REPLIES, ANSWER_REPLIES, GRAPH_ROWS):
        cache.clear()
