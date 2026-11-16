"""
extract_photos.py — Google's first photos of every matched restaurant. Part of
stage 1: run_1_extraction.py runs it after the Google extraction (and its
change check), never as a stage of its own. Stage 7 copies the photos into
public.restaurant_photo (migration 026).

WHICH PLACES: every Google place in data/1_raw/google_raw.csv (every matched
restaurant, closed ones too). A place gets Google's first PHOTOS_PER_PLACE
photos (Google's order), each MAX_WIDTH_PX wide at most (a smaller original
stays as it is):
  - a place with no photos saved yet (a new restaurant, a changed Google
    match, or the first run): asked now;
  - a place with PHOTOS_PER_PLACE saved: never asked again;
  - a place with fewer (Google had fewer, or none): asked again only on a
    Google refresh (--refresh-google). If Google now has more, its first
    PHOTOS_PER_PLACE are downloaded again and replace the saved ones;
    otherwise nothing is downloaded.
Photos never accumulate (unlike reviews): a place holds at most
PHOTOS_PER_PLACE, and they are replaced only as above.

THE CALLS: Google's photo names come from Place Details (New) with the field
mask "photos" only (the Essentials IDs Only SKU: free, no limit). Each photo
is then one Place Photos (New) request (billed: 1,000 free a month, then
US$7 per 1,000) with skipHttpRedirect, which answers with a short-lived link
to the image; the image itself is then fetched from that link (not billed).
The key is sent in a header, never in a link, so it never appears in the log.
Photo names expire and Google does not allow keeping them, so they are used
at once and never saved.

NOT A CHANGE: photos are not in google_raw.csv, so they are never counted by
the change check (they do not move the Google schedule) and never make stage 4
ask the AI again.

SAVED: each place's photos as files in data/cache/photos/<place_id>/ (1.jpg,
2.jpg, ...), described in data/cache/photo_cache.json (keyed by place ID: when
it was last asked, how many photos Google had, and for each photo its file,
type, size, photographer and download time). Kept by Google place, so a
restaurant redrawn in OSM (a new osm_id for the same place) keeps its photos;
photos of a place no restaurant uses any more stay in the cache (cheap; the
place may come back). The files are kept so that rebuilding the database
reloads them without paying again.

A place whose download fails keeps its saved photos (or none) and is asked
again the next time stage 1 runs. A bad key stops the photos (every call would
fail); the Google extraction before it is not affected.
"""

import csv
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# Lets `src` be imported when this file is run directly, not through run_1_extraction.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.cache_saving import save_due, save_json

load_dotenv()

GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY")

PHOTOS_PER_PLACE = 3
MAX_WIDTH_PX = 800

GOOGLE_RAW_CSV = os.path.join("data", "1_raw", "google_raw.csv")
PHOTO_DIR = os.path.join("data", "cache", "photos")
PHOTO_CACHE_FILE = os.path.join("data", "cache", "photo_cache.json")

DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
MEDIA_URL = "https://places.googleapis.com/v1/{photo_name}/media"
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
BACKOFF_WAITS = [2, 4, 8, 16, 32]
RATE_LIMIT_SLEEP = 0.05


class PhotoError(RuntimeError):
    """A failed call, with its HTTP status code (None for a network error)."""

    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status


class KeyProblem(PhotoError):
    """A bad key or the API not enabled: every call would fail."""


def _now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(url, headers=None, params=None):
    """GET with retries for network errors, rate limits (429) and server
    errors (5xx). Other errors are raised at once; 401/403 as KeyProblem.
    Error messages never include the link (the key is in a header anyway)."""
    last = None
    for attempt, wait in enumerate(BACKOFF_WAITS, start=1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=60)
        except requests.RequestException as exc:
            last = PhotoError(None, type(exc).__name__)
        else:
            if resp.ok:
                return resp
            try:
                message = resp.json().get("error", {}).get("message", "")
            except ValueError:
                message = ""
            if resp.status_code in (401, 403):
                raise KeyProblem(resp.status_code, message or "not allowed")
            last = PhotoError(resp.status_code, message or resp.reason)
            if resp.status_code != 429 and resp.status_code < 500:
                raise last
        if attempt < len(BACKOFF_WAITS):
            time.sleep(wait)
    raise last


def photo_names(place_id):
    """Google's photos of a place, in Google's order: a list of its photo
    objects (name, widthPx, heightPx, authorAttributions). Free."""
    resp = _get(DETAILS_URL.format(place_id=place_id),
                headers={"X-Goog-Api-Key": GOOGLE_PLACES_API_KEY, "X-Goog-FieldMask": "photos"})
    time.sleep(RATE_LIMIT_SLEEP)
    return resp.json().get("photos") or []


def download(photo):
    """One photo: (image bytes, content type, width, height). One billed request."""
    resp = _get(MEDIA_URL.format(photo_name=photo["name"]),
                headers={"X-Goog-Api-Key": GOOGLE_PLACES_API_KEY},
                params={"maxWidthPx": MAX_WIDTH_PX, "skipHttpRedirect": "true"})
    link = resp.json().get("photoUri")
    if not link:
        raise PhotoError(None, "Google gave no link to the image")
    image = _get(link)
    content_type = (image.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if content_type not in IMAGE_TYPES:
        raise PhotoError(None, f"not an image ({content_type or 'no type'})")
    # Google scales a wider original down to MAX_WIDTH_PX; a narrower one stays as it is
    width, height = photo.get("widthPx"), photo.get("heightPx")
    if width and height and width > MAX_WIDTH_PX:
        width, height = MAX_WIDTH_PX, round(height * MAX_WIDTH_PX / width)
    time.sleep(RATE_LIMIT_SLEEP)
    return image.content, content_type, width, height


def save_place(place_id, photos, downloaded, google_count):
    """Replace a place's photo files with the new ones; return its cache entry."""
    folder = os.path.join(PHOTO_DIR, place_id)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)
    fetched_at = _now_utc()
    saved = []
    for position, (photo, (data, content_type, width, height)) in enumerate(zip(photos, downloaded), start=1):
        path = os.path.join(folder, f"{position}.{IMAGE_TYPES[content_type]}")
        with open(path, "wb") as f:
            f.write(data)
        author = (photo.get("authorAttributions") or [{}])[0]
        saved.append({
            "position": position,
            "file": path.replace(os.sep, "/"),
            "content_type": content_type,
            "width_px": width,
            "height_px": height,
            "author_name": author.get("displayName"),
            "author_uri": author.get("uri"),
            "fetched_at": fetched_at,
        })
    return {"checked_at": fetched_at, "google_count": google_count, "photos": saved}


def matched_places():
    """The Google place IDs in google_raw.csv, in file order, each once."""
    if not os.path.exists(GOOGLE_RAW_CSV):
        return []
    with open(GOOGLE_RAW_CSV, "r", encoding="utf-8", newline="") as f:
        return list(dict.fromkeys(row["google_place_id"] for row in csv.DictReader(f)
                                  if row.get("google_place_id")))


def load_photo_cache():
    if not os.path.exists(PHOTO_CACHE_FILE):
        return {}
    with open(PHOTO_CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def run(refresh=False):
    """Download the photos the places in google_raw.csv still need (see the top)."""
    if not GOOGLE_PLACES_API_KEY:
        raise EnvironmentError("GOOGLE_PLACES_API_KEY not found. Add it to your .env file.")
    places = matched_places()
    cache = load_photo_cache()
    print(f"\nPhotos: {len(places)} Google places; up to {PHOTOS_PER_PLACE} photos each, "
          f"{MAX_WIDTH_PX} px wide" + (" (refresh: places with fewer are asked again)" if refresh else ""))

    downloads = 0
    counts = {"downloaded": 0, "enough": 0, "waiting": 0, "nothing more": 0, "failed": 0}
    asked = 0
    try:
        for place_id in places:
            entry = cache.get(place_id)
            have = len(entry["photos"]) if entry else 0
            if have >= PHOTOS_PER_PLACE:
                counts["enough"] += 1
                continue
            if entry and not refresh:
                counts["waiting"] += 1  # fewer than PHOTOS_PER_PLACE: asked again on a Google refresh
                continue
            if save_due(asked):
                save_json(PHOTO_CACHE_FILE, cache)
            asked += 1
            try:
                names = photo_names(place_id)
                if len(names) <= have:
                    # Google has no photos (a new place), or no more than are saved:
                    # nothing to download; remembered, so asked again only on a refresh
                    if entry:
                        entry.update(checked_at=_now_utc(), google_count=len(names))
                    else:
                        cache[place_id] = {"checked_at": _now_utc(), "google_count": 0, "photos": []}
                    counts["nothing more"] += 1
                    continue
                chosen = names[:PHOTOS_PER_PLACE]
                downloaded = []
                for photo in chosen:
                    downloaded.append(download(photo))
                    downloads += 1
            except KeyProblem:
                raise
            except PhotoError as exc:
                counts["failed"] += 1
                print(f"  {place_id}: FAILED ({exc}); asked again next time")
                continue
            cache[place_id] = save_place(place_id, chosen, downloaded, len(names))
            counts["downloaded"] += 1
            if counts["downloaded"] % 50 == 0:
                print(f"  {counts['downloaded']} places done, {downloads} photos downloaded...", flush=True)
    except KeyProblem as exc:
        print(f"  WARNING: photos stopped: Google refused the key ({exc}). "
              "Check GOOGLE_PLACES_API_KEY and that Places API (New) is enabled.")
    finally:
        save_json(PHOTO_CACHE_FILE, cache)
        print(f"Photos: {downloads} downloaded (billed) for {counts['downloaded']} places; "
              f"{counts['enough']} already had {PHOTOS_PER_PLACE}; "
              f"{counts['waiting']} with fewer wait for the next Google refresh; "
              f"{counts['nothing more']} asked, Google had nothing more; {counts['failed']} failed "
              f"-> {PHOTO_CACHE_FILE}")
    return downloads


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download Google's photos of the matched restaurants.")
    parser.add_argument("--refresh", action="store_true",
                        help="Also ask again the places with fewer than the full number of photos.")
    run(refresh=parser.parse_args().refresh)
