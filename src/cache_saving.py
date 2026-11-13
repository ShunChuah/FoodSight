"""
Saving the pipeline's caches while a stage runs.

The stages that call Google, Gemini or Nominatim (extract_google.py,
merge_data.py, profile_data.py) keep every answer in a cache file in
data/cache/. Each saves its cache every SAVE_EVERY restaurants, and again when
the run stops early (Ctrl+C or an error). A stop halfway therefore loses at
most the last few answers, and a rerun asks only for what is not cached yet.
"""

import json
import os
import time

SAVE_EVERY = 25  # restaurants between two saves


def save_due(done):
    """True when `done` restaurants are finished and that is a multiple of SAVE_EVERY."""
    return done > 0 and done % SAVE_EVERY == 0


def save_json(path, data):
    """Write data to path as JSON. It is written to a temporary file first,
    which then replaces the old file, so a stop in the middle of writing never
    leaves half a file: the old cache stays whole until the new one is ready."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # On Windows another program (an antivirus scan, for example) can hold the
    # file for a moment, so the swap is tried a few times.
    for attempt in range(3):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(0.5)
