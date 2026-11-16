"""The pipeline's files for the admin review page: reading the review, report and state
files in data/ (mounted read-only), and writing the admin's decisions into the decision
files in src/reference/, which the pipeline obeys on its next run.

A decision file is written the safe way: the new text goes to a temporary file in the same
folder first, which then replaces the old file in one step, so the pipeline never reads half
a file. One lock lets only one decision be written at a time."""

import json
import os
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, status

from app import config

# In data/
GOOGLE_REVIEW = "review/google_match_review.json"
REMOVED_REVIEW = "review/removed_from_osm.json"
AI_FAILED = "review/ai_failed.json"
ADDRESS_FAILED = "review/address_lookup_failed.json"
VALIDATION_INVALID = "review/validation_invalid.json"
GRAPH_INVALID = "review/graph_invalid.json"
SCHEDULE = "state/schedule.json"
RUN_STATE = "state/run_state.json"
RUN_LOCK = "state/run.lock"
GRAPH_TODO = "state/graph_todo.json"

# In src/reference/: each decision file and the key of its entries
OVERRIDES = ("google_match_overrides.json", "overrides")
EXCLUSIONS = ("nearby_exclusions.json", "exclusions")
REMOVED_DECISIONS = ("removed_restaurant_decisions.json", "decisions")
CATEGORIES = "categories.json"

_write_lock = threading.Lock()
_cache: dict[str, tuple] = {}


def require_files():
    """Router dependency: 503 when the backend cannot see the pipeline's folders (the
    container was started before the mounts in docker-compose.yml were added)."""
    if not config.PIPELINE_DATA_DIR.is_dir() or not config.PIPELINE_REFERENCE_DIR.is_dir():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ADMIN_FILES_NOT_MOUNTED")


def _read(path: Path, default):
    """The file's JSON, reused until the file changes; default when it does not exist.
    Callers must not change what they get back."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return default
    stamp = (stat.st_mtime_ns, stat.st_size)
    hit = _cache.get(str(path))
    if hit and hit[0] == stamp:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, {"code": "ADMIN_FILE_UNREADABLE", "file": path.name})
    _cache[str(path)] = (stamp, data)
    return data


def read_data(relative: str, default=None):
    return _read(config.PIPELINE_DATA_DIR / relative, default)


def read_reference(name: str, default=None):
    return _read(config.PIPELINE_REFERENCE_DIR / name, default)


def entries(decision_file) -> dict:
    """The entries of a decision file ({} when it has none)."""
    name, key = decision_file
    return (read_reference(name, {}) or {}).get(key) or {}


def stamp(user) -> dict:
    """Who decided and when, added to every entry the page writes. The username, not the
    email: git keeps these files."""
    return {"decided_by": user.username, "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def change_entries(decision_file, change):
    """Read the decision file, let change(entries) edit its entries in place, then write
    the file back the safe way. Returns what change returned. When change raises, the file
    is not written."""
    name, key = decision_file
    path = config.PIPELINE_REFERENCE_DIR / name
    with _write_lock:
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except FileNotFoundError:
            doc = {}
        except ValueError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, {"code": "ADMIN_FILE_UNREADABLE", "file": name})
        items = doc.get(key) or {}
        result = change(items)
        doc[key] = items
        _replace(path, _layout(doc, key))
        return result


def _layout(doc: dict, key: str) -> str:
    """The file's text in the layout of the hand-written files: the other keys (the
    _readme) first, then one entry per line, so a git diff shows one line per decision."""
    parts = [f"  {json.dumps(k)}: " + json.dumps(v, indent=2, ensure_ascii=False).replace("\n", "\n  ")
             for k, v in doc.items() if k != key]
    items = doc[key]
    if items:
        lines = ",\n".join(f"    {json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}"
                           for k, v in items.items())
        parts.append(f"  {json.dumps(key)}: {{\n{lines}\n  }}")
    else:
        parts.append(f"  {json.dumps(key)}: {{}}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def _replace(path: Path, text: str):
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        # Windows refuses the swap while another program has the file open for a moment
        # (the pipeline reading it), so try a few times
        for attempt in range(10):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.2)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
