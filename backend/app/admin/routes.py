"""The admin review page (/api/v1/admin/...): what the pipeline needs a person for, and the
admin's decisions, written into the decision files in src/reference/ for the next run.

- Google matches: data/review/google_match_review.json -> google_match_overrides.json
- Removed restaurants: data/review/removed_from_osm.json -> removed_restaurant_decisions.json
- Nearby places: public.nearby_place -> nearby_exclusions.json
- Read only: the update history (history.py: change reports, schedule decisions, dropped
  duplicates) and the logs (logs.py: data/logs, split into runs and stages)

A decision takes effect in the next nightly update (run_update.py, case 2). Until then the
item stays in its review file marked with the decision, and the decision can be undone.
Once the update has applied it, the item leaves the review file and the page no longer
offers an undo. Only admins (auth.users.is_superuser). Changes use PUT and DELETE, never GET
(the SameSite cookie rule)."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.admin import files
from app.admin import history as update_history
from app.admin import logs as pipeline_logs
from app.auth.backend import current_admin
from app.auth.models import User
from app.database import get_db

router = APIRouter(prefix="/admin", tags=["admin"],
                   dependencies=[Depends(current_admin), Depends(files.require_files)])

NOTE_MAX = 300
LOCK_STALE_HOURS = 21   # as in run_update.py: a lock this old was left by a crash
# Pins farther apart than this are offered the choice of Google's pin: the distance within
# which a same or brand name is matched automatically (MAX_DISTANCE_BY_STRENGTH in
# src/s1_scrapers/extract_google.py; change both together). A partly alike name has no
# limit of its own, so it uses this one.
AUTO_MATCH_M = 50
OSM_ID = r"^\d{1,20}$"
OsmType = Literal["node", "way", "relation"]


class GoogleDecision(BaseModel):
    same: bool   # true: the Google place in the review file is this restaurant; false: it is not
    note: str = Field("", max_length=NOTE_MAX)
    pin: Literal["osm", "google"] = "osm"   # the pin saved in the database (same place only)


class SharedDecision(BaseModel):
    # The restaurant that is the Google place; null: none of them (each goes on OSM-only)
    osm_id: str | None = Field(None, pattern=r"^\d{1,20}$")
    note: str = Field("", max_length=NOTE_MAX)
    pin: Literal["osm", "google"] = "osm"   # for the chosen restaurant, when it is offered


class RemovedDecision(BaseModel):
    decision: Literal["closed", "delete", "keep"]
    note: str = Field("", max_length=NOTE_MAX)


class Exclusion(BaseModel):
    reason: str = Field(min_length=1, max_length=NOTE_MAX)


def _note(note: str) -> dict:
    note = note.strip()
    return {"note": note} if note else {}


def _items(relative: str) -> list:
    return (files.read_data(relative, {}) or {}).get("items") or []


def _find(items: list, osm_id: str, missing="REVIEW_ITEM_NOT_FOUND", code=status.HTTP_404_NOT_FOUND) -> dict:
    for item in items:
        if str(item.get("osm_id")) == osm_id:
            return item
    raise HTTPException(code, missing)


def _ids(name):
    return bindparam(name, expanding=True)


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


def _nearby_keys(db: Session) -> set:
    return {f"{r.osm_type}/{r.osm_id}" for r in db.execute(text("SELECT osm_type, osm_id FROM nearby_place"))}


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    schedule = files.read_data(files.SCHEDULE, {}) or {}
    run_state = files.read_data(files.RUN_STATE, {}) or {}
    lock = files.read_data(files.RUN_LOCK, None)
    todo = files.read_data(files.GRAPH_TODO, {}) or {}
    invalid = files.read_data(files.VALIDATION_INVALID, {}) or {}
    graph_invalid = files.read_data(files.GRAPH_INVALID, {}) or {}
    ai_failed = _items(files.AI_FAILED)

    running_since = None
    if lock and lock.get("started"):
        started = datetime.fromisoformat(lock["started"])
        if (datetime.now(timezone.utc) - started).total_seconds() < LOCK_STALE_HOURS * 3600:
            running_since = lock["started"]

    google = (files.read_data(files.GOOGLE_REVIEW, {}) or {})
    google_items = google.get("items") or []
    overrides = files.entries(files.OVERRIDES)
    google_decided = sum(1 for i in google_items if str(i.get("osm_id")) in overrides)
    removed = files.read_data(files.REMOVED_REVIEW, {}) or {}
    removed_items = removed.get("items") or []
    decisions = files.entries(files.REMOVED_DECISIONS)
    removed_decided = sum(1 for i in removed_items if str(i.get("osm_id")) in decisions)
    exclusions = files.entries(files.EXCLUSIONS)
    counted = _nearby_keys(db)

    return {
        "schedule": {source: {key: entry.get(key) for key in
                              ("next_due", "interval_days", "last_extraction", "decided_by", "reason")}
                     for source, entry in schedule.items()},
        "last_run": run_state.get("last_run"),
        "unfinished": run_state.get("unfinished"),
        "running_since": running_since,
        "graph_waiting": {"changes": sum(len(v or {}) for v in (todo.get("changes") or {}).values()),
                          "rebuild_clusters": bool(todo.get("rebuild_clusters"))},
        "ai_failed": {"restaurants": sum(1 for i in ai_failed if i.get("kind") == "profile"),
                      "reviews": sum(1 for i in ai_failed if i.get("kind") == "sentiment")},
        "address_failed": len(_items(files.ADDRESS_FAILED)),
        "validation_invalid": {
            "restaurants": len(invalid.get("invalid_restaurants") or []),
            "areas": len(invalid.get("invalid_areas") or []),
            "nearby_places": len(invalid.get("invalid_nearby_places") or []),
            "checked_at": invalid.get("validated_at") or invalid.get("quarantined_at"),
        },
        "graph_invalid": {
            "nodes": len(graph_invalid.get("invalid_nodes") or []),
            "relationships": len(graph_invalid.get("invalid_relationships") or []),
            "checked_at": graph_invalid.get("validated_at"),
        },
        "google_matches": {"waiting_decision": len(google_items) - google_decided,
                           "waiting_update": google_decided, "file_written": google.get("created_at")},
        "removed_restaurants": {"waiting_decision": len(removed_items) - removed_decided,
                                "waiting_update": removed_decided, "file_written": removed.get("created_at")},
        "nearby_exclusions": {"total": len(exclusions),
                              "waiting_update": sum(1 for key in exclusions if key in counted)},
    }


# ---------------------------------------------------------------------------
# Google matches
# ---------------------------------------------------------------------------


def _google_decision(entry, place_id):
    """The saved override with what it means: same (this Google place), not_same (no
    Google match), or other_place (a different place ID, written by hand)."""
    if entry is None:
        return None
    given = (entry or {}).get("place_id")
    kind = "not_same" if given is None else ("same" if given == place_id else "other_place")
    return {**entry, "kind": kind}


def _other_names(items: list, db: Session) -> dict:
    """osm_id -> name for every restaurant an item names in other_osm_ids: from the review
    file, or for one no longer in OpenStreetMap (replaces_removed) from the database."""
    names = {str(i.get("osm_id")): i.get("osm_name") for i in items}
    missing = sorted({str(o) for i in items for o in i.get("other_osm_ids") or []} - names.keys())
    if missing:
        rows = db.execute(text("SELECT osm_id, name FROM restaurant WHERE osm_id IN :ids").bindparams(_ids("ids")),
                          {"ids": missing})
        names.update({r.osm_id: r.name for r in rows})
    return names


def _far_apart(item: dict) -> bool:
    """True when the pins are farther apart than a same name would be matched
    automatically: every too_far item, and any other beyond AUTO_MATCH_M (a partly
    alike name has no limit of its own). The page then shows "Pins too far apart"."""
    limit = item.get("limit_m") if item.get("limit_m") is not None else AUTO_MATCH_M
    return (item.get("distance_m") or 0) > limit


def _pin_choice(item: dict) -> bool:
    """True when the admin may save Google's pin instead of OSM's: both pins exist and
    they are far apart."""
    location = ((item.get("google") or {}).get("details") or {}).get("location") or {}
    osm = item.get("osm") or {}
    if location.get("latitude") is None or not osm.get("latitude"):
        return False
    return _far_apart(item)


def _google_summary(item: dict, overrides: dict, names: dict) -> dict:
    osm_id = str(item.get("osm_id"))
    place_id = (item.get("google") or {}).get("place_id")
    return {
        "far_apart": _far_apart(item),
        "pin_choice": _pin_choice(item),
        "osm_id": osm_id,
        "reason": item.get("reason"),
        "reason_text": item.get("reason_text"),
        "osm_name": item.get("osm_name"),
        "google_name": item.get("google_name"),
        "name_strength": item.get("name_strength"),
        "distance_m": item.get("distance_m"),
        "limit_m": item.get("limit_m"),
        "place_id": place_id,
        "others": [{"osm_id": str(o), "osm_name": names.get(str(o))} for o in item.get("other_osm_ids") or []],
        "decision": _google_decision(overrides.get(osm_id), place_id),
    }


@router.get("/google-matches")
def google_matches(db: Session = Depends(get_db)):
    doc = files.read_data(files.GOOGLE_REVIEW, {}) or {}
    items = doc.get("items") or []
    names = _other_names(items, db)
    overrides = files.entries(files.OVERRIDES)
    return {
        "file_written": doc.get("created_at"),
        "reasons": doc.get("reasons") or {},
        "items": [_google_summary(item, overrides, names) for item in items],
    }


@router.get("/google-matches/{osm_id}")
def google_match(osm_id: str = Path(pattern=OSM_ID), db: Session = Depends(get_db)):
    items = _items(files.GOOGLE_REVIEW)
    item = _find(items, osm_id)
    summary = _google_summary(item, files.entries(files.OVERRIDES), _other_names([item], db))
    return {**summary, "osm": item.get("osm") or {}, "google": item.get("google") or {}}


@router.put("/google-matches/{osm_id}")
def decide_google_match(body: GoogleDecision, osm_id: str = Path(pattern=OSM_ID),
                        user: User = Depends(current_admin)):
    item = _find(_items(files.GOOGLE_REVIEW), osm_id)
    shown = (item.get("google") or {}).get("place_id")
    # The place ID is copied from the review file: the admin never types one
    place_id = shown if body.same else None
    if body.same and not shown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "REVIEW_ITEM_HAS_NO_GOOGLE_PLACE")
    # Google's pin only with Google's place, and only where the page offers the choice
    google_pin = body.pin == "google"
    if google_pin and not (body.same and _pin_choice(item)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PIN_CHOICE_NOT_ALLOWED")

    def change(overrides):
        if place_id:
            # One Google place belongs to one restaurant (UNIQUE restaurant.google_place_id)
            taken = next((k for k, v in overrides.items()
                          if k != osm_id and (v or {}).get("place_id") == place_id), None)
            if taken:
                raise HTTPException(status.HTTP_409_CONFLICT, {"code": "GOOGLE_PLACE_ALREADY_GIVEN", "osm_id": taken})
        # No "pin" means OSM's pin, the pipeline's own rule
        overrides[osm_id] = {"place_id": place_id, **({"pin": "google"} if google_pin else {}),
                             **_note(body.note), **files.stamp(user)}
        return overrides[osm_id]

    return {"decision": _google_decision(files.change_entries(files.OVERRIDES, change), shown)}


PLACE_ID = r"^[A-Za-z0-9_-]{1,255}$"


def _shared_members(place_id: str, missing="REVIEW_ITEM_NOT_FOUND", code=status.HTTP_404_NOT_FOUND) -> list:
    """The review items of one shared Google place: the OSM restaurants that all matched it."""
    members = [i for i in _items(files.GOOGLE_REVIEW)
               if i.get("reason") == "shared_google_place" and (i.get("google") or {}).get("place_id") == place_id]
    if not members:
        raise HTTPException(code, missing)
    return members


@router.put("/google-matches/shared/{place_id}")
def decide_shared(body: SharedDecision, place_id: str = Path(pattern=PLACE_ID), user: User = Depends(current_admin)):
    """Decide a whole shared Google place in one write: the chosen restaurant gets the place,
    every other one null (OpenStreetMap data only); no osm_id gives every one null."""
    members = _shared_members(place_id)
    ids = [str(m.get("osm_id")) for m in members]
    chosen = next((m for m in members if str(m.get("osm_id")) == body.osm_id), None)
    if body.osm_id is not None and chosen is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "NOT_IN_THIS_GROUP")
    google_pin = body.pin == "google"
    if google_pin and not (chosen and _pin_choice(chosen)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PIN_CHOICE_NOT_ALLOWED")

    def change(overrides):
        if chosen:
            taken = next((k for k, v in overrides.items() if k not in ids and (v or {}).get("place_id") == place_id), None)
            if taken:
                raise HTTPException(status.HTTP_409_CONFLICT, {"code": "GOOGLE_PLACE_ALREADY_GIVEN", "osm_id": taken})
        stamp, note = files.stamp(user), _note(body.note)
        for osm_id in ids:
            given = place_id if osm_id == body.osm_id else None
            overrides[osm_id] = {"place_id": given, **({"pin": "google"} if given and google_pin else {}), **note, **stamp}
        return {osm_id: overrides[osm_id] for osm_id in ids}

    saved = files.change_entries(files.OVERRIDES, change)
    return {"decisions": {osm_id: _google_decision(entry, place_id) for osm_id, entry in saved.items()}}


@router.delete("/google-matches/shared/{place_id}")
def undo_shared(place_id: str = Path(pattern=PLACE_ID)):
    ids = [str(m.get("osm_id")) for m in
           _shared_members(place_id, "DECISION_ALREADY_APPLIED", status.HTTP_409_CONFLICT)]
    files.change_entries(files.OVERRIDES, lambda overrides: [overrides.pop(osm_id, None) for osm_id in ids])
    return {"decisions": {osm_id: None for osm_id in ids}}


@router.delete("/google-matches/{osm_id}")
def undo_google_match(osm_id: str = Path(pattern=OSM_ID)):
    # Still in the review file = not applied yet; once applied, it is no longer there
    _find(_items(files.GOOGLE_REVIEW), osm_id, "DECISION_ALREADY_APPLIED", status.HTTP_409_CONFLICT)
    files.change_entries(files.OVERRIDES, lambda overrides: overrides.pop(osm_id, None))
    return {"decision": None}


# ---------------------------------------------------------------------------
# Restaurants gone from OpenStreetMap
# ---------------------------------------------------------------------------


@router.get("/removed-restaurants")
def removed_restaurants(db: Session = Depends(get_db)):
    doc = files.read_data(files.REMOVED_REVIEW, {}) or {}
    items = doc.get("items") or []
    decisions = files.entries(files.REMOVED_DECISIONS)
    ids = [i["restaurant_id"] for i in items if i.get("restaurant_id")]
    pins = {}
    if ids:
        rows = db.execute(text("SELECT r.restaurant_id, l.latitude, l.longitude FROM restaurant r "
                               "JOIN location l ON l.location_id = r.location_id "
                               "WHERE r.restaurant_id IN :ids").bindparams(_ids("ids")), {"ids": ids})
        pins = {r.restaurant_id: (r.latitude, r.longitude) for r in rows}
    # The pin comes from the restaurant's location in the database; an item with no database
    # row (a test item from tools/fake_removed_restaurant.py) may carry its own
    def pin(item):
        return pins.get(item.get("restaurant_id")) or (item.get("latitude"), item.get("longitude"))

    return {
        "file_written": doc.get("created_at"),
        "items": [{**item, "osm_id": str(item.get("osm_id")),
                   "latitude": pin(item)[0], "longitude": pin(item)[1],
                   "decision": decisions.get(str(item.get("osm_id")))}
                  for item in items],
    }


@router.put("/removed-restaurants/{osm_id}")
def decide_removed(body: RemovedDecision, osm_id: str = Path(pattern=OSM_ID), user: User = Depends(current_admin)):
    _find(_items(files.REMOVED_REVIEW), osm_id)

    def change(decisions):
        decisions[osm_id] = {"decision": body.decision, **_note(body.note), **files.stamp(user)}
        return decisions[osm_id]

    return {"decision": files.change_entries(files.REMOVED_DECISIONS, change)}


@router.delete("/removed-restaurants/{osm_id}")
def undo_removed(osm_id: str = Path(pattern=OSM_ID)):
    _find(_items(files.REMOVED_REVIEW), osm_id, "DECISION_ALREADY_APPLIED", status.HTTP_409_CONFLICT)
    files.change_entries(files.REMOVED_DECISIONS, lambda decisions: decisions.pop(osm_id, None))
    return {"decision": None}


# ---------------------------------------------------------------------------
# Nearby places and the hand-checked exclusions
# ---------------------------------------------------------------------------

# How many restaurants count each place: through restaurant_nearby_place for the counted
# kinds; a station is no link but each restaurant's nearest_station (by name).
RESTAURANTS_COUNTING = """
    CASE WHEN p.kind = 'station'
         THEN (SELECT count(*) FROM nearby_context c WHERE c.nearest_station = p.name)
         ELSE (SELECT count(*) FROM restaurant_nearby_place l WHERE l.nearby_place_id = p.nearby_place_id)
    END"""

PLACES_SQL = text(rf"""
    SELECT p.osm_type, p.osm_id, p.kind, p.name, p.station_type, p.latitude, p.longitude,
           {RESTAURANTS_COUNTING} AS restaurants,
           count(*) OVER () AS total
    FROM nearby_place p
    WHERE (:kind = '' OR p.kind = :kind)
      AND (:pattern = '' OR p.name ILIKE :pattern ESCAPE '\')
    ORDER BY restaurants DESC, p.name, p.osm_id
    LIMIT :limit OFFSET :offset""")


def _radius(kind: str):
    """radius_m of a counted kind, from categories.json (None for a station)."""
    columns = (files.read_reference(files.CATEGORIES, {}) or {}).get("columns") or {}
    values = (columns.get("nearby_place.kind") or {}).get("values") or {}
    return (values.get(kind) or {}).get("radius_m")


def _like(words: str) -> str:
    words = words.strip()
    if not words:
        return ""
    return "%" + words.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@router.get("/nearby-places")
def nearby_places(kind: str = Query("", max_length=20), q: str = Query("", max_length=100),
                  limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db)):
    rows = db.execute(PLACES_SQL, {"kind": kind, "pattern": _like(q), "limit": limit, "offset": offset}).all()
    kinds = db.execute(text("SELECT kind, count(*) AS places FROM nearby_place GROUP BY kind ORDER BY kind")).all()
    exclusions = files.entries(files.EXCLUSIONS)
    return {
        "total": rows[0].total if rows else 0,
        "kinds": [{"kind": r.kind, "places": r.places} for r in kinds],
        "items": [{"osm_type": r.osm_type, "osm_id": str(r.osm_id), "kind": r.kind, "name": r.name,
                   "station_type": r.station_type, "latitude": r.latitude, "longitude": r.longitude,
                   "restaurants": r.restaurants, "exclusion": exclusions.get(f"{r.osm_type}/{r.osm_id}")}
                  for r in rows],
    }


@router.get("/nearby-places/{osm_type}/{osm_id}")
def nearby_place(osm_type: OsmType, osm_id: int, db: Session = Depends(get_db)):
    place = db.execute(text("SELECT nearby_place_id, osm_type, osm_id, kind, name, station_type, latitude, "
                            "longitude, osm_fetched_at FROM nearby_place WHERE osm_type = :t AND osm_id = :i"),
                       {"t": osm_type, "i": osm_id}).first()
    if not place:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NEARBY_PLACE_NOT_FOUND")
    if place.kind == "station":
        sql = ("SELECT r.restaurant_id, r.name, c.station_distance_m AS distance_m, l.latitude, l.longitude "
               "FROM nearby_context c JOIN restaurant r ON r.restaurant_id = c.restaurant_id "
               "JOIN location l ON l.location_id = r.location_id "
               "WHERE c.nearest_station = :name ORDER BY c.station_distance_m, r.name")
        restaurants = db.execute(text(sql), {"name": place.name}).all()
    else:
        sql = ("SELECT r.restaurant_id, r.name, n.distance_m, l.latitude, l.longitude "
               "FROM restaurant_nearby_place n JOIN restaurant r ON r.restaurant_id = n.restaurant_id "
               "JOIN location l ON l.location_id = r.location_id "
               "WHERE n.nearby_place_id = :id ORDER BY n.distance_m, r.name")
        restaurants = db.execute(text(sql), {"id": place.nearby_place_id}).all()
    return {
        "osm_type": place.osm_type, "osm_id": str(place.osm_id), "kind": place.kind, "name": place.name,
        "station_type": place.station_type, "latitude": place.latitude, "longitude": place.longitude,
        "osm_fetched_at": place.osm_fetched_at, "radius_m": _radius(place.kind),
        "map": f"https://www.openstreetmap.org/{place.osm_type}/{place.osm_id}",
        "restaurants": [{"restaurant_id": r.restaurant_id, "name": r.name, "distance_m": r.distance_m,
                         "latitude": r.latitude, "longitude": r.longitude} for r in restaurants],
        "exclusion": files.entries(files.EXCLUSIONS).get(f"{place.osm_type}/{place.osm_id}"),
    }


@router.get("/nearby-exclusions")
def nearby_exclusions(db: Session = Depends(get_db)):
    counted = _nearby_keys(db)
    items = []
    for key, entry in files.entries(files.EXCLUSIONS).items():
        osm_type, _, osm_id = key.partition("/")
        # Still in nearby_place: excluded in the file, still counted until the next update
        items.append({"key": key, "osm_type": osm_type, "osm_id": osm_id, **(entry or {}),
                      "waiting_update": key in counted,
                      "map": f"https://www.openstreetmap.org/{key}"})
    return {"items": items}


@router.put("/nearby-exclusions/{osm_type}/{osm_id}")
def exclude_place(body: Exclusion, osm_type: OsmType, osm_id: int,
                  user: User = Depends(current_admin), db: Session = Depends(get_db)):
    key = f"{osm_type}/{osm_id}"
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "EXCLUSION_REASON_EMPTY")
    place = db.execute(text("SELECT kind, name FROM nearby_place WHERE osm_type = :t AND osm_id = :i"),
                       {"t": osm_type, "i": osm_id}).first()

    def change(exclusions):
        # kind and name come from the database (or stay as they were): the admin types only the reason
        known = exclusions.get(key) or {}
        if not place and not known:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "NEARBY_PLACE_NOT_FOUND")
        exclusions[key] = {"kind": place.kind if place else known.get("kind"),
                           "name": place.name if place else known.get("name"),
                           "reason": reason, **files.stamp(user)}
        return exclusions[key]

    return {"exclusion": files.change_entries(files.EXCLUSIONS, change)}


@router.delete("/nearby-exclusions/{osm_type}/{osm_id}")
def remove_exclusion(osm_type: OsmType, osm_id: int):
    key = f"{osm_type}/{osm_id}"
    files.change_entries(files.EXCLUSIONS, lambda exclusions: exclusions.pop(key, None))
    return {"exclusion": None}


# ---------------------------------------------------------------------------
# Update history and logs (read only)
# ---------------------------------------------------------------------------


@router.get("/history")
def history():
    return update_history.history()


@router.get("/history/reports/{name}")
def history_report(name: str, db: Session = Depends(get_db)):
    def osm_types(ids):
        rows = db.execute(text("SELECT osm_id, osm_type FROM restaurant WHERE osm_id IN :ids").bindparams(_ids("ids")),
                          {"ids": ids})
        return {r.osm_id: r.osm_type for r in rows}

    return update_history.report_detail(name, osm_types)


@router.get("/logs")
def log_days():
    return {"days": pipeline_logs.days()}


@router.get("/logs/{day}")
def log_day(day: str):
    return pipeline_logs.day(day)


@router.get("/logs/{day}/text")
def log_text(day: str, start: int = Query(1, ge=1), end: int = Query(ge=1)):
    return pipeline_logs.text(day, start, end)
