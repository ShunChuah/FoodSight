"""
FoodSight — Database Loader
Brings PostgreSQL up to date with data/6_clustered/pj_clustered.json.

Every row is compared with what the database already holds:
  - new        -> added
  - different  -> only that row is updated (the restaurant, its location, its
                  hours, price, profile, rating, nearby counts; its cuisines,
                  facilities and nearby links are changed one by one)
  - the same   -> left alone
Fetch times (google_fetched_at, rating.scraped_at, osm_fetched_at) never count
as a change on their own; they are written whenever their row is.

What is left alone or kept:
  - a restaurant in the database that is not in the file (gone from OSM, held
    for review, or no AI answer) is not touched. When a nearby place it was
    linked to is deleted, its counts are worked out again from the links left.
  - reviews are history: a review Google no longer shows is kept. New reviews
    are added (by google_review_id), and a review saved without a sentiment
    gets one when the file has it.
  - a section that is no longer in OSM is deleted only when no location still
    points to it.

Found by their own keys: restaurants by osm_id, sections by osm_id
(migration 021), nearby places by osm_type + osm_id, the city by name.

Re-mapped restaurant: a new osm_id whose Google place already belongs to a
restaurant in the database whose osm_id is no longer in the file. When
src/reference/google_match_overrides.json gives the new osm_id that place
(a person checked it is the same shop), the existing row moves to the new
osm_id, with its reviews and history. Otherwise the new restaurant is not
loaded, and the summary says how to approve it.

CLUSTERS are replaced on every load: the old ones are deleted, the new ones
are numbered from 1 again, and every restaurant in the file gets this run's
cluster_id.

The cuisine table is filled from src/reference/categories.json (cuisine.name:
every name with its fixed origin_country and category) at the start of each
load; a restaurant's cuisines are linked in restaurant_cuisine with their rank
(1 = most important). A cuisine name not in the file is skipped.

A restaurant without an AI profile (business_profile is None) is not loaded.
run_4_profiling.py already leaves out every restaurant with no usable AI
answer (data/review/ai_failed.json), so this is only a safety.

PHOTOS (sync_photos()): public.restaurant_photo is brought up to date with the
photos stage 1 downloaded (data/cache/photo_cache.json and data/cache/photos/,
keyed by Google place): added, replaced (another download time) or deleted,
for every restaurant in the database with a Google place. Without the table
(migration 026 not run) photos are skipped and the summary says so; the rest
of the load goes on. Photos are not in the graph.

STAGE 8 TO-DO LIST (data/state/graph_todo.json): every row this load added,
updated or deleted, with the value before and after, so run_8_graph.py updates
only those in Neo4j. A load adds to the list; run_8_graph.py empties it.

Everything happens in one transaction: an error changes nothing. With
dry_run=True (run_7_loading.py --dry-run) the changes are made, counted and
shown, then undone, and the to-do list is not written.

TEMPORARILY NULL FIELDS (remove when data available):
  - area.population_density        -> WorldPop not integrated
"""

import csv
import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import psycopg2
from dotenv import load_dotenv
from psycopg2 import sql

# Lets `src` be imported when this file is run directly, not through run_7_loading.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.cache_saving import save_json
from src.categories import get_column

load_dotenv()

INPUT_FILE = os.path.join("data", "6_clustered", "pj_clustered.json")
VALIDATED_FILE = os.path.join("data", "5_validated", "pj_validated.json")  # what clustering read
TODO_FILE = os.path.join("data", "state", "graph_todo.json")
OVERRIDES_FILE = os.path.join("src", "reference", "google_match_overrides.json")
# Restaurants gone from OSM: every restaurant in the latest OSM extraction,
# your decisions, and the review file of the undecided ones
OSM_RAW_FILE = os.path.join("data", "1_raw", "osm_raw.csv")
DECISIONS_FILE = os.path.join("src", "reference", "removed_restaurant_decisions.json")
REMOVED_FILE = os.path.join("data", "review", "removed_from_osm.json")
DECISIONS = ("closed", "delete", "keep")
CLOSED_STATUS = "PERMANENTLY_CLOSED"
EXAMPLES_SHOWN = 15  # changes listed by name in the summary
# Google's photos, downloaded in stage 1 (src/s1_scrapers/extract_photos.py)
PHOTO_CACHE_FILE = os.path.join("data", "cache", "photo_cache.json")
PHOTO_MIGRATION = "db/migrations/026_restaurant_photo.sql"

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# nearby_context count columns, from nearby_place.kind in categories.json
COUNT_COLUMNS = [v["column"] for v in get_column("nearby_place.kind")["values"].values()
                 if v.get("column")]

RESTAURANT_COMPARE = ["osm_type", "name", "amenity_type", "brand", "phone", "website",
                      "business_status", "google_place_id", "google_maps_uri", "editorial_summary"]
LOCATION_COMPARE = ["area_id", "latitude", "longitude", "full_address", "postcode", "street"]
# One row per restaurant: (columns that count as a change, fetch times written with the row)
ONE_ROW = {
    "operating_hours": ([*DAYS, "is_24_7"], []),
    "price_range": (["tier", "avg_meal_price"], []),
    "business_profile": (["target_segment", "restaurant_type", "service_style", "business_style",
                          "ambiance", "halal_status", "evidence_level", "generated_at"], []),
    "rating": (["rating_score", "total_reviews"], ["scraped_at"]),
    "nearby_context": ([*COUNT_COLUMNS, "nearest_station", "station_type", "station_distance_m"],
                       ["osm_fetched_at"]),
}

# ---------------------------------------------------------------------------
# Database connection
# ---------------------------------------------------------------------------


def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", 5432)),
        dbname=os.getenv("DB_NAME", "foodsight"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _str(v):
    """Return stripped string or None."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _float(v):
    """Return float or None."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    """Return int or None."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _time(v):
    """A timestamp as an aware datetime (UTC when it has no zone), or None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        t = v
    else:
        try:
            t = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _same(a, b):
    """True when a database value and a new value are the same: numbers within
    a millionth (coordinates, prices, a numeric rating), times as instants."""
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, datetime) or isinstance(b, datetime):
        return _time(a) == _time(b)
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def _plain(v):
    """A value as it is written in the to-do list: a long text (an outline)
    as its sha256, so the list stays small."""
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, str) and len(v) > 200:
        return "sha256:" + hashlib.sha256(v.encode("utf-8")).hexdigest()
    if isinstance(v, (list, tuple, set)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    return v


def _show(v):
    """A short form of a value for the summary."""
    if isinstance(v, str) and len(v) > 200:
        return "(outline)"
    text = repr(_plain(v))
    return text if len(text) <= 60 else text[:57] + "..."


def _diff(table, old, new, columns):
    """{"table.column": (before, now)} for the columns whose values differ."""
    return {f"{table}.{c}": (old.get(c), new[c]) for c in columns if not _same(old.get(c), new[c])}


def _rows(cur, query, params=None):
    cur.execute(query, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _insert(cur, table, values, returning=None):
    query = sql.SQL("INSERT INTO public.{} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, values)),
        sql.SQL(", ").join(sql.Placeholder() * len(values)),
    )
    if returning:
        query += sql.SQL(" RETURNING {}").format(sql.Identifier(returning))
    cur.execute(query, list(values.values()))
    return cur.fetchone()[0] if returning else None


def _update(cur, table, values, key_column, key):
    query = sql.SQL("UPDATE public.{} SET {} WHERE {} = %s").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in values),
        sql.Identifier(key_column),
    )
    cur.execute(query, [*values.values(), key])


class Changes:
    """What this load changed: counts for the summary, a few changes by name,
    and the entries of the stage 8 to-do list."""

    def __init__(self):
        self.counts = Counter()
        self.fields = Counter()  # restaurants' own fields that changed
        self.examples = []
        self.todo = defaultdict(dict)  # group -> {key: {"action", "changes"}}

    def note(self, group, key, action, changes=None):
        entry = self.todo[group].setdefault(str(key), {"action": action, "changes": {}})
        if action in ("added", "deleted"):
            entry["action"] = action
        for field, (before, now) in (changes or {}).items():
            entry["changes"][field] = [_plain(before), _plain(now)]

    def example(self, text):
        self.counts["examples"] += 1
        if len(self.examples) < EXAMPLES_SHOWN:
            self.examples.append(text)


# ---------------------------------------------------------------------------
# What the database holds now
# ---------------------------------------------------------------------------


def read_database(cur):
    """Every row the comparison needs, read once at the start."""
    db = SimpleNamespace()
    db.restaurants = {r["osm_id"]: r for r in _rows(cur, (
        "SELECT restaurant_id, location_id, osm_id, " + ", ".join(RESTAURANT_COMPARE)
        + ", google_fetched_at FROM public.restaurant"))}
    db.locations = {r["location_id"]: r for r in _rows(cur, (
        "SELECT location_id, " + ", ".join(LOCATION_COMPARE) + " FROM public.location"))}
    for table, (compare, times) in ONE_ROW.items():
        setattr(db, table, {r["restaurant_id"]: r for r in _rows(cur, sql.SQL(
            "SELECT restaurant_id, {} FROM public.{}").format(
                sql.SQL(", ").join(map(sql.Identifier, [*compare, *times])),
                sql.Identifier(table)))})
    db.cuisine_links = defaultdict(list)
    for r in _rows(cur, "SELECT restaurant_id, cuisine_id, rank FROM public.restaurant_cuisine"):
        db.cuisine_links[r["restaurant_id"]].append((r["cuisine_id"], r["rank"]))
    db.facility_links = defaultdict(set)
    for r in _rows(cur, "SELECT restaurant_id, facility_id FROM public.restaurant_facility"):
        db.facility_links[r["restaurant_id"]].add(r["facility_id"])
    db.nearby_links = defaultdict(dict)
    for r in _rows(cur, "SELECT restaurant_id, nearby_place_id, distance_m FROM public.restaurant_nearby_place"):
        db.nearby_links[r["restaurant_id"]][r["nearby_place_id"]] = r["distance_m"]
    db.reviews = {r["google_review_id"]: r for r in _rows(cur, (
        "SELECT review_id, restaurant_id, google_review_id, sentiment FROM public.review"))}
    db.facility_ids = {r["name"]: r["facility_id"] for r in _rows(cur, (
        "SELECT facility_id, name FROM public.facility"))}
    return db


# ---------------------------------------------------------------------------
# Step 1: city
# ---------------------------------------------------------------------------


def sync_city(cur, city, changes):
    """Add the city, or update its state, country and outline. PJ is the only
    city: if the table holds one city under another name, it is renamed."""
    new = {
        "name": _str(city.get("name")),
        "state": _str(city.get("state")),
        "country": _str(city.get("country")),
        "boundary_geojson": _str(city.get("boundary_geojson")),
    }
    rows = _rows(cur, "SELECT city_id, name, state, country, boundary_geojson FROM public.city")
    old = next((r for r in rows if r["name"] == new["name"]), rows[0] if len(rows) == 1 else None)
    if old is None:
        city_id = _insert(cur, "city", new, returning="city_id")
        changes.counts["city added"] += 1
        changes.note("city", city_id, "added")
        changes.example(f"city added: {new['name']}")
        return city_id
    found = _diff("city", old, new, list(new))
    if found:
        _update(cur, "city", new, "city_id", old["city_id"])
        changes.counts["city updated"] += 1
        changes.note("city", old["city_id"], "updated", found)
        changes.example(f"city {new['name']}: {', '.join(found)} changed")
    return old["city_id"]


# ---------------------------------------------------------------------------
# Step 2: sections (areas)
# ---------------------------------------------------------------------------


def sync_areas(cur, areas, city_id, changes):
    """Add new sections and update changed ones, found by osm_id (migration
    021), so a renamed section keeps its row. Returns ({name in the file:
    area_id}, the database rows of sections no longer in the file)."""
    existing = {r["osm_id"]: r for r in _rows(cur, (
        "SELECT area_id, osm_id, city_id, name, type, boundary_geojson FROM public.area"))}
    name_to_id, seen = {}, set()
    for area in areas:
        osm_id = int(area["osm_id"])
        new = {
            "city_id": city_id,
            "name": _str(area.get("name")),
            "type": _str(area.get("type")),
            "boundary_geojson": _str(area.get("boundary_geojson")),
        }
        old = existing.get(osm_id)
        if old is None:
            area_id = _insert(cur, "area", {**new, "osm_id": osm_id}, returning="area_id")
            changes.counts["area added"] += 1
            changes.note("areas", area_id, "added")
            changes.example(f"section added: {new['name']}")
        else:
            area_id = old["area_id"]
            found = _diff("area", old, new, list(new))
            if found:
                _update(cur, "area", new, "area_id", area_id)
                changes.counts["area updated"] += 1
                changes.note("areas", area_id, "updated", found)
                if "area.name" in found:
                    changes.example(f"section renamed: {_show(old['name'])} -> {_show(new['name'])}")
                else:
                    changes.example(f"section {new['name']}: {', '.join(found)} changed")
            else:
                changes.counts["area unchanged"] += 1
        name_to_id[new["name"]] = area_id
        seen.add(osm_id)
    gone = [r for osm_id, r in existing.items() if osm_id not in seen]
    return name_to_id, gone


def delete_gone_areas(cur, gone, changes):
    """Delete the sections no longer in OSM, once no location points to them
    (a restaurant not in the file can still be in one: then it is kept)."""
    for row in gone:
        cur.execute("SELECT count(*) FROM public.location WHERE area_id = %s", (row["area_id"],))
        used = cur.fetchone()[0]
        if used:
            changes.counts["area kept"] += 1
            changes.example(f"section {row['name']} is no longer in OSM, "
                            f"but {used} locations still point to it: kept")
            continue
        cur.execute("DELETE FROM public.area WHERE area_id = %s", (row["area_id"],))
        changes.counts["area deleted"] += 1
        changes.note("areas", row["area_id"], "deleted")
        changes.example(f"section deleted: {row['name']}")


# ---------------------------------------------------------------------------
# Step 2b: nearby places
# ---------------------------------------------------------------------------


def sync_nearby_places(cur, places, restaurants_in_file, changes):
    """Add new places and update changed ones (found by osm_type + osm_id);
    delete the places no longer in the file, which deletes their links too
    (ON DELETE CASCADE). Returns ({(osm_type, osm_id): nearby_place_id},
    {nearby_place_id: "osm_type/osm_id"}, restaurant_ids not in the file that
    lost a link)."""
    existing = {(r["osm_type"], r["osm_id"]): r for r in _rows(cur, (
        "SELECT nearby_place_id, osm_type, osm_id, kind, name, station_type, latitude, longitude "
        "FROM public.nearby_place"))}
    compare = ["kind", "name", "station_type", "latitude", "longitude"]
    place_ids, place_keys = {}, {}
    for place in places:
        key = (_str(place.get("osm_type")), _int(place.get("osm_id")))
        new = {
            "kind": _str(place.get("kind")),
            "name": _str(place.get("name")),
            "station_type": _str(place.get("station_type")),
            "latitude": _float(place.get("latitude")),
            "longitude": _float(place.get("longitude")),
            "osm_fetched_at": _str(place.get("osm_fetched_at")),
        }
        old = existing.get(key)
        if old is None:
            place_id = _insert(cur, "nearby_place",
                               {"osm_type": key[0], "osm_id": key[1], **new},
                               returning="nearby_place_id")
            changes.counts["place added"] += 1
            changes.note("nearby_places", place_id, "added")
            changes.example(f"nearby {new['kind']} added: {new['name']} ({key[0]}/{key[1]})")
        else:
            place_id = old["nearby_place_id"]
            found = _diff("nearby_place", old, new, compare)
            if found:
                _update(cur, "nearby_place", new, "nearby_place_id", place_id)
                changes.counts["place updated"] += 1
                changes.note("nearby_places", place_id, "updated", found)
                changes.example(f"nearby {new['kind']} {new['name']}: {', '.join(found)} changed")
            else:
                changes.counts["place unchanged"] += 1
        place_ids[key] = place_id
        place_keys[place_id] = f"{key[0]}/{key[1]}"

    lost_link = set()
    for key, old in existing.items():
        if key in place_ids:
            continue
        cur.execute("SELECT restaurant_id FROM public.restaurant_nearby_place WHERE nearby_place_id = %s",
                    (old["nearby_place_id"],))
        lost_link.update(rid for (rid,) in cur.fetchall() if rid not in restaurants_in_file)
        cur.execute("DELETE FROM public.nearby_place WHERE nearby_place_id = %s", (old["nearby_place_id"],))
        place_keys[old["nearby_place_id"]] = f"{key[0]}/{key[1]}"
        changes.counts["place deleted"] += 1
        changes.note("nearby_places", old["nearby_place_id"], "deleted")
        changes.example(f"nearby {old['kind']} deleted: {old['name']} ({key[0]}/{key[1]})")
    return place_ids, place_keys, lost_link


def recount_not_in_file(cur, restaurant_ids, changes):
    """A restaurant in the database but not in the file keeps its rows as
    they are. When a nearby place it was linked to is deleted, the link goes
    with it, so its counts are worked out again from the links that are left
    (a restaurant's number of links always equals its count)."""
    columns = {kind: v["column"] for kind, v in get_column("nearby_place.kind")["values"].items()
               if v.get("column")}
    for rid in sorted(restaurant_ids):
        cur.execute(
            """
            SELECT p.kind, count(*) FROM public.restaurant_nearby_place l
            JOIN public.nearby_place p USING (nearby_place_id)
            WHERE l.restaurant_id = %s GROUP BY p.kind
            """,
            (rid,),
        )
        found = dict(cur.fetchall())
        new = {column: found.get(kind, 0) for kind, column in columns.items()}
        old = _rows(cur, sql.SQL("SELECT {} FROM public.nearby_context WHERE restaurant_id = %s").format(
            sql.SQL(", ").join(map(sql.Identifier, new))), (rid,))
        if not old:
            continue
        differ = _diff("nearby_context", old[0], new, list(new))
        if differ:
            _update(cur, "nearby_context", new, "restaurant_id", rid)
            changes.counts["recounted"] += 1
            changes.note("restaurants", rid, "updated", differ)


# ---------------------------------------------------------------------------
# Step 4: clusters
# ---------------------------------------------------------------------------


def replace_clusters(cur, clusters):
    """Delete the old clusters and insert this run's, numbered from 1 again
    (cluster_label 0 -> cluster_id 1, the biggest). run_6_clustering.py works
    them out again every run, so an old cluster is never kept.
    Returns {cluster_label: cluster_id}."""
    cur.execute("UPDATE public.restaurant SET cluster_id = NULL WHERE cluster_id IS NOT NULL")
    cur.execute("DELETE FROM public.cluster")
    cur.execute("SELECT setval(pg_get_serial_sequence('public.cluster', 'cluster_id'), 1, false)")
    label_to_id = {}
    for cluster in sorted(clusters, key=lambda c: c["cluster_label"]):
        cur.execute(
            """
            INSERT INTO public.cluster
                (centroid_lat, centroid_lon, restaurant_count, density_score, boundary_geojson)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING cluster_id
            """,
            (
                _float(cluster.get("centroid_lat")),
                _float(cluster.get("centroid_lon")),
                _int(cluster.get("restaurant_count")),
                _float(cluster.get("density_score")),
                _str(cluster.get("boundary_geojson")),
            ),
        )
        label_to_id[cluster["cluster_label"]] = cur.fetchone()[0]
    return label_to_id


# ---------------------------------------------------------------------------
# Step 7: cuisine list
# ---------------------------------------------------------------------------


def sync_cuisines(cur, changes):
    """Write every cuisine in src/reference/categories.json into public.cuisine,
    with its origin_country and category (updated if the file changed), and
    return {name: cuisine_id}."""
    existing = {r["name"]: r for r in _rows(cur, (
        "SELECT cuisine_id, name, origin_country, category FROM public.cuisine"))}
    cuisine_ids = {}
    for name, detail in get_column("cuisine.name")["values"].items():
        new = {"origin_country": detail.get("origin_country"), "category": detail.get("category")}
        old = existing.get(name)
        if old is None:
            cuisine_id = _insert(cur, "cuisine", {"name": name, **new}, returning="cuisine_id")
            changes.counts["cuisine added"] += 1
            changes.note("cuisines", cuisine_id, "added")
        else:
            cuisine_id = old["cuisine_id"]
            found = _diff("cuisine", old, new, list(new))
            if found:
                _update(cur, "cuisine", new, "cuisine_id", cuisine_id)
                changes.counts["cuisine updated"] += 1
                changes.note("cuisines", cuisine_id, "updated", found)
        cuisine_ids[name] = cuisine_id
    return cuisine_ids


def delete_gone_cuisines(cur, cuisine_ids, changes):
    """Delete the cuisines no longer in src/reference/categories.json, once no
    restaurant is linked to them (a restaurant not in the file can still be:
    then the cuisine is kept). Runs after the restaurants, whose links to such
    a cuisine are dropped as they are compared."""
    gone = _rows(cur, "SELECT cuisine_id, name FROM public.cuisine WHERE NOT (cuisine_id = ANY(%s))",
                 (list(cuisine_ids.values()),))
    for row in gone:
        cur.execute("SELECT count(*) FROM public.restaurant_cuisine WHERE cuisine_id = %s", (row["cuisine_id"],))
        used = cur.fetchone()[0]
        if used:
            changes.counts["cuisine kept"] += 1
            changes.example(f"cuisine {row['name']} is no longer in categories.json, "
                            f"but {used} restaurants still have it: kept")
            continue
        cur.execute("DELETE FROM public.cuisine WHERE cuisine_id = %s", (row["cuisine_id"],))
        changes.counts["cuisine deleted"] += 1
        changes.note("cuisines", row["cuisine_id"], "deleted")
        changes.example(f"cuisine deleted (no longer in categories.json): {row['name']}")


# ---------------------------------------------------------------------------
# Steps 3, 5, 6, 8-15: one restaurant and its rows
# ---------------------------------------------------------------------------


def restaurant_values(r):
    return {**{c: _str(r.get(c)) for c in RESTAURANT_COMPARE},
            "google_fetched_at": _str(r.get("google_fetched_at"))}


def location_values(r, ctx):
    area = _str(r.get("area_name"))
    return {
        "area_id": ctx.area_name_to_id.get(area) if area else None,
        "latitude": _float(r.get("latitude")),
        "longitude": _float(r.get("longitude")),
        "full_address": _str(r.get("full_address")),
        "postcode": _str(r.get("postcode")),
        "street": _str(r.get("street")),
    }


def one_row_values(table, r, old):
    """The new values of one of the one-row-per-restaurant tables, or None
    when the restaurant has no such row."""
    if table == "operating_hours":
        hours = r.get("operating_hours") or {}
        return {**{day: _str(hours.get(day)) for day in DAYS},
                "is_24_7": bool(hours.get("is_24_7", False))}
    if table == "price_range":
        price = r.get("price_range") or {}
        tier = _str(price.get("tier"))
        return {"tier": tier, "avg_meal_price": _float(price.get("avg_meal_price"))} if tier else None
    if table == "business_profile":
        profile = r.get("business_profile")
        if not profile:
            return None
        # When the AI answered. An answer cached before answer times were kept
        # has none: the saved time stays, or the loading time for a new row.
        generated = (_str(profile.get("generated_at")) or (old or {}).get("generated_at")
                     or datetime.now(timezone.utc))
        return {
            **{c: _str(profile.get(c)) for c in ("target_segment", "restaurant_type", "service_style",
                                                 "business_style", "ambiance", "halal_status",
                                                 "evidence_level")},
            "generated_at": generated,
        }
    if table == "rating":
        # No rating score (no Google match, or Google has none): no rating row
        rating = r.get("rating") or {}
        score = _float(rating.get("rating_score"))
        if score is None:
            return None
        return {"rating_score": score, "total_reviews": _int(rating.get("total_reviews")),
                "scraped_at": _str(r.get("google_fetched_at")) or datetime.now(timezone.utc)}
    if table == "nearby_context":
        context = r.get("nearby_context")
        if not context:
            return None
        return {
            **{c: _int(context.get(c)) or 0 for c in COUNT_COLUMNS},
            "nearest_station": _str(context.get("nearest_station")),
            "station_type": _str(context.get("station_type")),
            "station_distance_m": _int(context.get("station_distance_m")),
            "osm_fetched_at": _str(context.get("osm_fetched_at")),
        }
    raise ValueError(table)


def sync_one_row(cur, table, rid, new, old):
    """Insert, update or delete a restaurant's row in a one-row table.
    Returns {"table.column": (before, now)}, or {"table": ...} when the whole
    row was added or deleted."""
    compare = ONE_ROW[table][0]
    if new is None:
        if old is None:
            return {}
        cur.execute(sql.SQL("DELETE FROM public.{} WHERE restaurant_id = %s").format(
            sql.Identifier(table)), (rid,))
        return {table: ("row", None)}
    if old is None:
        _insert(cur, table, {"restaurant_id": rid, **new})
        return {table: (None, "row")}
    found = _diff(table, old, new, compare)
    if found:
        _update(cur, table, new, "restaurant_id", rid)
    return found


def sync_cuisine_links(cur, rid, r, ctx, old):
    """Make the restaurant's cuisines (with their rank) what the file says."""
    new = []
    for position, cuisine in enumerate(r.get("cuisines") or [], start=1):
        cuisine_id = ctx.cuisine_ids.get(_str(cuisine.get("name")))
        if cuisine_id is not None:
            new.append((cuisine_id, cuisine.get("rank") or position))
    if sorted(new) == sorted(old):
        return {}
    cur.execute("DELETE FROM public.restaurant_cuisine WHERE restaurant_id = %s", (rid,))
    for cuisine_id, rank in new:
        _insert(cur, "restaurant_cuisine", {"restaurant_id": rid, "cuisine_id": cuisine_id, "rank": rank})

    def names(links):
        # a cuisine removed from categories.json can still be linked: shown by its id
        return [ctx.cuisine_names.get(c, f"cuisine {c}") for c, _ in sorted(links, key=lambda link: link[1])]

    return {"cuisines": (names(old), names(new))}


def _facility_id(cur, name, category, ctx, changes):
    """The facility's id; a facility name seen for the first time is added."""
    if name not in ctx.facility_ids:
        cur.execute(
            "INSERT INTO public.facility (name, category) VALUES (%s, %s) "
            "ON CONFLICT DO NOTHING RETURNING facility_id",
            (name, category),
        )
        row = cur.fetchone()
        if row:
            changes.note("facilities", row[0], "added")
            ctx.facility_ids[name] = row[0]
        else:
            cur.execute("SELECT facility_id FROM public.facility WHERE name = %s", (name,))
            ctx.facility_ids[name] = cur.fetchone()[0]
        ctx.facility_names[ctx.facility_ids[name]] = name
    return ctx.facility_ids[name]


def sync_facility_links(cur, rid, r, ctx, old, changes):
    """Make the restaurant's facilities what the file says."""
    new = set()
    for facility in r.get("facilities") or []:
        name, category = _str(facility.get("name")), _str(facility.get("category"))
        if name and category:
            new.add(_facility_id(cur, name, category, ctx, changes))
    if new == old:
        return {}
    for facility_id in old - new:
        cur.execute("DELETE FROM public.restaurant_facility WHERE restaurant_id = %s AND facility_id = %s",
                    (rid, facility_id))
    for facility_id in new - old:
        _insert(cur, "restaurant_facility", {"restaurant_id": rid, "facility_id": facility_id})
    return {"facilities": (sorted(ctx.facility_names[f] for f in old),
                           sorted(ctx.facility_names[f] for f in new))}


def sync_nearby_links(cur, rid, r, ctx, old):
    """Make the restaurant's links to nearby places (with their distance)
    what the file says. Returns (changes, added, removed, distance changed)."""
    new = {}
    for link in r.get("nearby_places") or []:
        key = (_str(link.get("osm_type")), _int(link.get("osm_id")))
        place_id = ctx.place_ids.get(key)
        if place_id is None:
            raise ValueError(f"nearby place {key[0]}/{key[1]} is not in nearby_places")
        new[place_id] = _int(link.get("distance_m"))
    if new == old:
        return {}, 0, 0, 0
    removed = old.keys() - new.keys()
    added = new.keys() - old.keys()
    moved = {p for p in new.keys() & old.keys() if new[p] != old[p]}
    for place_id in removed:
        # already gone when its place was deleted (ON DELETE CASCADE); then this deletes nothing
        cur.execute("DELETE FROM public.restaurant_nearby_place WHERE restaurant_id = %s AND nearby_place_id = %s",
                    (rid, place_id))
    for place_id in added:
        _insert(cur, "restaurant_nearby_place",
                {"restaurant_id": rid, "nearby_place_id": place_id, "distance_m": new[place_id]})
    for place_id in moved:
        cur.execute("UPDATE public.restaurant_nearby_place SET distance_m = %s "
                    "WHERE restaurant_id = %s AND nearby_place_id = %s", (new[place_id], rid, place_id))

    def named(links):
        return {ctx.place_keys[p]: d for p, d in sorted(links.items(), key=lambda item: ctx.place_keys[item[0]])}

    return {"nearby_links": (named(old), named(new))}, len(added), len(removed), len(moved)


def sync_reviews(cur, rid, r, known):
    """Add the reviews not in the database yet (by google_review_id), and give
    a sentiment to a saved review that has none when the file has one.
    Reviews are history: one missing from the file is kept. Returns (added,
    sentiments filled)."""
    added = filled = 0
    for review in r.get("reviews") or []:
        review_id = _str(review.get("google_review_id"))
        sentiment = _str(review.get("sentiment"))
        saved = known.get(review_id)
        if saved is None:
            cur.execute(
                """
                INSERT INTO public.review
                    (restaurant_id, google_review_id, author_name, text,
                     individual_rating, sentiment, published_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (rid, review_id, _str(review.get("author_name")), _str(review.get("text")),
                 _int(review.get("individual_rating")), sentiment, _str(review.get("published_at"))),
            )
            added += cur.rowcount  # 0 when another restaurant already has this review
            known[review_id] = {"restaurant_id": rid, "sentiment": sentiment}
        elif saved["sentiment"] is None and sentiment and saved["restaurant_id"] == rid:
            cur.execute("UPDATE public.review SET sentiment = %s WHERE google_review_id = %s",
                        (sentiment, review_id))
            saved["sentiment"] = sentiment
            filled += 1
    return added, filled


def add_restaurant(cur, r, ctx, db, changes):
    """A restaurant that is not in the database yet: all its rows are added."""
    location_id = _insert(cur, "location", location_values(r, ctx), returning="location_id")
    rid = _insert(cur, "restaurant", {
        "location_id": location_id,
        "osm_id": _str(r.get("osm_id")),
        **restaurant_values(r),
        "cluster_id": ctx.cluster_ids.get(r.get("cluster_label")),
    }, returning="restaurant_id")
    for table in ONE_ROW:
        sync_one_row(cur, table, rid, one_row_values(table, r, None), None)
    sync_cuisine_links(cur, rid, r, ctx, [])
    sync_facility_links(cur, rid, r, ctx, set(), changes)
    sync_nearby_links(cur, rid, r, ctx, {})
    added, _ = sync_reviews(cur, rid, r, db.reviews)
    changes.counts["restaurant new"] += 1
    changes.counts["reviews added"] += added
    changes.note("restaurants", rid, "added")
    changes.example(f"new restaurant: {_str(r.get('name'))} (osm {r.get('osm_id')})")


def update_restaurant(cur, r, ctx, db, changes):
    """A restaurant already in the database: only what differs is written."""
    old_row = db.restaurants[_str(r.get("osm_id"))]
    rid = old_row["restaurant_id"]
    found = {}

    new_row = restaurant_values(r)
    differ = _diff("restaurant", old_row, new_row, RESTAURANT_COMPARE)
    if differ:
        _update(cur, "restaurant", new_row, "restaurant_id", rid)
    found.update(differ)

    new_location = location_values(r, ctx)
    differ = _diff("location", db.locations.get(old_row["location_id"]) or {}, new_location,
                   LOCATION_COMPARE)
    if differ:
        _update(cur, "location", new_location, "location_id", old_row["location_id"])
    found.update(differ)

    for table in ONE_ROW:
        old = getattr(db, table).get(rid)
        found.update(sync_one_row(cur, table, rid, one_row_values(table, r, old), old))
    found.update(sync_cuisine_links(cur, rid, r, ctx, db.cuisine_links.get(rid, [])))
    found.update(sync_facility_links(cur, rid, r, ctx, db.facility_links.get(rid, set()), changes))
    links, links_added, links_removed, links_moved = sync_nearby_links(
        cur, rid, r, ctx, db.nearby_links.get(rid, {}))
    found.update(links)
    reviews_added, sentiments_filled = sync_reviews(cur, rid, r, db.reviews)

    cur.execute("UPDATE public.restaurant SET cluster_id = %s WHERE restaurant_id = %s",
                (ctx.cluster_ids.get(r.get("cluster_label")), rid))

    # The restaurant's own data, versus what changes around it or on Google
    own = {f: v for f, v in found.items()
           if not f.startswith(("rating", "nearby_context", "nearby_links")) and f != "location.area_id"}
    if own:
        changes.counts["restaurant changed"] += 1
        changes.fields.update(f.split(".")[0] if f.startswith(ONE_ROW_PREFIXES) else f for f in own)
        shown = "; ".join(f"{f} {_show(before)} -> {_show(now)}" for f, (before, now) in list(own.items())[:3])
        more = f" (+{len(own) - 3} more)" if len(own) > 3 else ""
        changes.example(f"{_str(r.get('name'))} (osm {r.get('osm_id')}): {shown}{more}")
    else:
        changes.counts["restaurant unchanged"] += 1
    if any(f.startswith("rating") for f in found):
        changes.counts["rating updated"] += 1
    if any(f.startswith("nearby_context") for f in found):
        changes.counts["nearby counts updated"] += 1
    if "location.area_id" in found:
        changes.counts["section changed"] += 1
    changes.counts["links added"] += links_added
    changes.counts["links removed"] += links_removed
    changes.counts["links moved"] += links_moved
    changes.counts["reviews added"] += reviews_added
    changes.counts["sentiments filled"] += sentiments_filled
    if reviews_added or sentiments_filled:
        found["reviews"] = (None, {"added": reviews_added, "sentiment_filled": sentiments_filled})
    if found:
        changes.note("restaurants", rid, "updated", found)


ONE_ROW_PREFIXES = tuple(f"{table}." for table in ONE_ROW)


# ---------------------------------------------------------------------------
# Re-mapped restaurants (a new osm_id on a known Google place)
# ---------------------------------------------------------------------------


def load_overrides():
    """{osm_id: place_id} from the hand-checked Google matches."""
    if not os.path.exists(OVERRIDES_FILE):
        return {}
    with open(OVERRIDES_FILE, "r", encoding="utf-8") as f:
        entries = json.load(f).get("overrides") or {}
    return {str(osm_id): (entry or {}).get("place_id") for osm_id, entry in entries.items()}


def take_over_moved_rows(cur, restaurants, db, changes):
    """A new osm_id whose Google place belongs to a restaurant in the database
    whose osm_id is not in the file (OSM redrew it with a new ID). With the
    match approved in the override file, the existing row moves to the new
    osm_id and is then updated like any other; without it, the new restaurant
    is not loaded. Returns the osm_ids not loaded, with the reason."""
    in_file = {_str(r.get("osm_id")) for r in restaurants}
    by_place = {row["google_place_id"]: row for row in db.restaurants.values() if row["google_place_id"]}
    overrides = None
    held = {}
    for r in restaurants:
        osm_id, place = _str(r.get("osm_id")), _str(r.get("google_place_id"))
        if osm_id in db.restaurants or not place or place not in by_place:
            continue
        old = by_place[place]
        if old["osm_id"] in in_file:
            continue  # that restaurant is in the file too; it is updated first and frees the place
        if overrides is None:
            overrides = load_overrides()
        if overrides.get(osm_id) != place:
            held[osm_id] = (f"{_str(r.get('name'))}: same Google place as {old['name']} "
                            f"(osm {old['osm_id']}), which is no longer in OSM")
            continue
        cur.execute("UPDATE public.restaurant SET osm_id = %s, osm_type = %s WHERE restaurant_id = %s",
                    (osm_id, _str(r.get("osm_type")), old["restaurant_id"]))
        changes.counts["moved to new osm_id"] += 1
        changes.note("restaurants", old["restaurant_id"], "updated",
                     {"restaurant.osm_id": (old["osm_id"], osm_id),
                      "restaurant.osm_type": (old["osm_type"], _str(r.get("osm_type")))})
        changes.example(f"{old['name']}: moved from osm {old['osm_id']} to osm {osm_id} (approved match)")
        del db.restaurants[old["osm_id"]]
        old.update(osm_id=osm_id, osm_type=_str(r.get("osm_type")))
        db.restaurants[osm_id] = old
    return held


# ---------------------------------------------------------------------------
# Restaurants gone from OSM, and your decisions about them
# ---------------------------------------------------------------------------


def osm_ids_in_osm():
    """Every restaurant osm_id in the latest OSM extraction (osm_raw.csv), or
    None when the file is missing (then nothing counts as gone)."""
    if not os.path.exists(OSM_RAW_FILE):
        return None
    with open(OSM_RAW_FILE, "r", encoding="utf-8", newline="") as f:
        return {row["osm_id"].strip() for row in csv.DictReader(f) if row.get("osm_id")}


def load_decisions():
    """{osm_id: {"decision", "note"}} from DECISIONS_FILE."""
    if not os.path.exists(DECISIONS_FILE):
        return {}
    with open(DECISIONS_FILE, "r", encoding="utf-8") as f:
        return {str(k): (v or {}) for k, v in (json.load(f).get("decisions") or {}).items()}


def apply_removed(cur, db, in_osm, decisions, changes):
    """Restaurants in the database whose osm_id is no longer in OSM: apply
    your decision (closed, delete or keep). Returns (the undecided ones, the
    decisions no longer needed: their restaurant is back in OSM or gone)."""
    undecided, deleted_now = [], set()
    for osm_id, row in list(db.restaurants.items()):
        if osm_id in in_osm:
            continue
        decision = str((decisions.get(osm_id) or {}).get("decision") or "").strip().lower()
        rid = row["restaurant_id"]
        if decision == "closed":
            if row["business_status"] != CLOSED_STATUS:
                cur.execute("UPDATE public.restaurant SET business_status = %s WHERE restaurant_id = %s",
                            (CLOSED_STATUS, rid))
                changes.note("restaurants", rid, "updated",
                             {"restaurant.business_status": (row["business_status"], CLOSED_STATUS)})
                changes.counts["removed closed"] += 1
                changes.example(f"{row['name']} (osm {osm_id}): gone from OSM, set to {CLOSED_STATUS} (your decision)")
                row["business_status"] = CLOSED_STATUS
        elif decision == "delete":
            # Its reviews, links and one-row tables go with it (ON DELETE CASCADE); then its location
            cur.execute("DELETE FROM public.restaurant WHERE restaurant_id = %s", (rid,))
            cur.execute("DELETE FROM public.location WHERE location_id = %s", (row["location_id"],))
            changes.note("restaurants", rid, "deleted")
            changes.counts["removed deleted"] += 1
            changes.example(f"{row['name']} (osm {osm_id}): gone from OSM, deleted (your decision)")
            del db.restaurants[osm_id]
            deleted_now.add(osm_id)
        elif decision == "keep":
            changes.counts["removed kept"] += 1
        else:
            if decision:
                print(f"  WARNING: decision {decision!r} for osm {osm_id} in {DECISIONS_FILE} is not one of "
                      f"{', '.join(DECISIONS)}: it stays on the list")
            undecided.append(row)
    # Deleted by this load: the decision did its job, and is reported from the next load on
    no_longer_needed = sorted(osm_id for osm_id in decisions
                              if osm_id in in_osm or (osm_id not in db.restaurants and osm_id not in deleted_now))
    return undecided, no_longer_needed


def write_removed_file(db, undecided):
    """Rewrite REMOVED_FILE, in the layout of the other review files."""
    from src.s1_scrapers.detect_changes import last_seen_in_osm
    seen = last_seen_in_osm([row["osm_id"] for row in undecided])
    items = []
    for row in sorted(undecided, key=lambda r: r["name"] or ""):
        location = db.locations.get(row["location_id"]) or {}
        items.append({
            "osm_id": row["osm_id"],
            "osm_type": row["osm_type"],
            "name": row["name"],
            "restaurant_id": row["restaurant_id"],
            "address": location.get("full_address"),
            "business_status": row["business_status"],
            "last_seen_in_osm": seen.get(row["osm_id"]),
            "osm_map": f"https://www.openstreetmap.org/{row['osm_type'] or 'node'}/{row['osm_id']}",
            "google_map": row["google_maps_uri"],
        })
    save_json(REMOVED_FILE, {
        "how_to_use": (
            "Restaurants in the database that are no longer in OpenStreetMap: closed and "
            "deleted by a mapper, or redrawn with a new ID. Nothing in the database changes "
            "for them until you decide. Check each one (Google Maps, a visit), then add its "
            f"osm_id to {DECISIONS_FILE} with \"closed\", \"delete\" or \"keep\". The next "
            "python run_7_loading.py applies it. Do not write decisions in this file: it is "
            "rewritten on every load. One that comes back in OSM leaves the list by itself."
        ),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "count": len(items),
        "items": items,
    })


# ---------------------------------------------------------------------------
# Stage 8 to-do list
# ---------------------------------------------------------------------------


def _merge_entry(before, after):
    """One row's entry when the list already has one from an earlier load:
    the first value before and the latest value now are kept."""
    if before is None or after["action"] == "deleted":
        return after
    if before["action"] == "added":
        return before  # stage 8 adds it whole anyway
    merged = dict(before.get("changes") or {})
    for field, (old, new) in (after.get("changes") or {}).items():
        first = merged[field][0] if field in merged else old
        if first == new:
            merged.pop(field, None)  # changed back
        else:
            merged[field] = [first, new]
    if not merged and after["action"] == "updated":
        return None
    return {"action": after["action"], "changes": merged}


def write_todo(changes):
    """Add this load's changes to data/state/graph_todo.json (run_8_graph.py
    reads it, updates those rows in Neo4j, and empties it). Written before the
    load is committed: if the commit then fails, stage 8 only checks rows that
    did not change, which does no harm."""
    todo = {}
    if os.path.exists(TODO_FILE):
        with open(TODO_FILE, "r", encoding="utf-8") as f:
            todo = json.load(f)
    groups = todo.get("changes") or {}
    for group, entries in changes.todo.items():
        target = groups.setdefault(group, {})
        for key, entry in entries.items():
            merged = _merge_entry(target.get(key), entry)
            if merged is None:
                target.pop(key, None)
            else:
                target[key] = merged
    save_json(TODO_FILE, {
        "how_to_read": (
            "Rows that changed in PostgreSQL since run_8_graph.py last updated the graph. "
            "run_7_loading.py adds to this file; run_8_graph.py updates these rows in Neo4j "
            "and then empties it. Groups: restaurants (everything that belongs to one "
            "restaurant, by restaurant_id), areas, city, nearby_places, cuisines, facilities "
            "(by their id). Each change is [value before, value now]; an outline is shown as "
            "its sha256. rebuild_clusters: the clusters were replaced (every load does)."
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rebuild_clusters": True,
        "changes": {group: entries for group, entries in groups.items() if entries},
    })


# ---------------------------------------------------------------------------
# Photos
# ---------------------------------------------------------------------------


def sync_photos(cur, changes):
    """Bring public.restaurant_photo up to date with the photos stage 1
    downloaded (PHOTO_CACHE_FILE, keyed by Google place). Every restaurant in
    the database with a Google place gets that place's photos: a new one is
    added, one with another download time is replaced, one no longer listed is
    deleted, and photos of a place the restaurant no longer has (its Google
    match changed or went) are deleted. A place stage 1 has not asked yet
    leaves the restaurant's photos as they are. Photos are not in the graph, so
    nothing goes on the stage 8 to-do list. Without the table (migration 026
    not run yet) nothing is done and the summary says so."""
    cur.execute("SELECT to_regclass('public.restaurant_photo')")
    if cur.fetchone()[0] is None:
        changes.counts["photos table missing"] = 1
        return
    cache = {}
    if os.path.exists(PHOTO_CACHE_FILE):
        with open(PHOTO_CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

    cur.execute("SELECT restaurant_id, google_place_id FROM restaurant WHERE google_place_id IS NOT NULL")
    place_of = dict(cur.fetchall())
    cur.execute("SELECT restaurant_id, position, google_place_id, fetched_at FROM restaurant_photo")
    have = {(rid, pos): (place_id, fetched_at) for rid, pos, place_id, fetched_at in cur.fetchall()}

    def delete(rid, pos):
        cur.execute("DELETE FROM restaurant_photo WHERE restaurant_id = %s AND position = %s", (rid, pos))
        changes.counts["photos deleted"] += 1

    # Photos of a place the restaurant no longer has
    for (rid, pos), (place_id, _) in list(have.items()):
        if place_of.get(rid) != place_id:
            delete(rid, pos)
            del have[(rid, pos)]

    for rid, place_id in place_of.items():
        entry = cache.get(place_id)
        if entry is None:
            continue  # not asked yet in stage 1
        wanted = {p["position"]: p for p in entry.get("photos") or []}
        for pos in [pos for (r, pos) in have if r == rid and pos not in wanted]:
            delete(rid, pos)
        for pos, photo in wanted.items():
            fetched_at = datetime.fromisoformat(photo["fetched_at"])
            current = have.get((rid, pos))
            if current and current[1] == fetched_at:
                changes.counts["photos unchanged"] += 1
                continue
            if not os.path.exists(photo["file"]):
                changes.counts["photo files missing"] += 1
                continue
            with open(photo["file"], "rb") as f:
                image = f.read()
            cur.execute(
                """INSERT INTO restaurant_photo (restaurant_id, position, google_place_id, image, content_type,
                                                 width_px, height_px, author_name, author_uri, fetched_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (restaurant_id, position) DO UPDATE SET
                       google_place_id = EXCLUDED.google_place_id, image = EXCLUDED.image,
                       content_type = EXCLUDED.content_type, width_px = EXCLUDED.width_px,
                       height_px = EXCLUDED.height_px, author_name = EXCLUDED.author_name,
                       author_uri = EXCLUDED.author_uri, fetched_at = EXCLUDED.fetched_at""",
                (rid, pos, place_id, psycopg2.Binary(image), photo["content_type"], photo.get("width_px"),
                 photo.get("height_px"), photo.get("author_name"), photo.get("author_uri"), fetched_at),
            )
            changes.counts["photos replaced" if current else "photos added"] += 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(input_file=INPUT_FILE, dry_run=False):
    print("=" * 60)
    print("FoodSight — Database Loader" + ("  (DRY RUN: nothing will be saved)" if dry_run else ""))
    print("=" * 60)

    if not os.path.exists(input_file):
        sys.exit(f"ERROR: {input_file} not found. Run run_6_clustering.py first.")
    # A validation run after the last clustering would be silently left out.
    if (input_file == INPUT_FILE and os.path.exists(VALIDATED_FILE)
            and os.path.getmtime(VALIDATED_FILE) > os.path.getmtime(input_file)):
        sys.exit(f"ERROR: {VALIDATED_FILE} is newer than {input_file}. "
                 "Run run_6_clustering.py first.")

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    city_data = data.get("city") or {}
    areas = data.get("areas", [])
    nearby_places = data.get("nearby_places", [])
    clusters = data.get("clusters", [])
    all_restaurants = data.get("restaurants", [])
    restaurants = [r for r in all_restaurants if r.get("business_profile")]
    waiting_for_ai = len(all_restaurants) - len(restaurants)

    print(f"\nLoaded  : {len(all_restaurants)} restaurants, {len(areas)} areas, "
          f"{len(nearby_places)} nearby places, {len(clusters)} clusters")

    changes = Changes()
    conn = get_connection()
    try:
        cur = conn.cursor()
        db = read_database(cur)
        print(f"Database: {len(db.restaurants)} restaurants before this load")

        ctx = SimpleNamespace()
        city_id = sync_city(cur, city_data, changes)
        ctx.area_name_to_id, gone_areas = sync_areas(cur, areas, city_id, changes)

        held = take_over_moved_rows(cur, restaurants, db, changes)
        restaurants = [r for r in restaurants if _str(r.get("osm_id")) not in held]

        # Restaurants gone from OSM: your decisions; the undecided ones are listed
        in_osm = osm_ids_in_osm()
        undecided, no_longer_needed = [], []
        if in_osm is not None:
            undecided, no_longer_needed = apply_removed(cur, db, in_osm, load_decisions(), changes)

        in_file = {_str(r.get("osm_id")) for r in restaurants}
        in_file_ids = {row["restaurant_id"] for osm_id, row in db.restaurants.items() if osm_id in in_file}

        ctx.place_ids, ctx.place_keys, lost_link = sync_nearby_places(cur, nearby_places, in_file_ids, changes)
        ctx.cluster_ids = replace_clusters(cur, clusters)
        ctx.cuisine_ids = sync_cuisines(cur, changes)
        ctx.cuisine_names = {cuisine_id: name for name, cuisine_id in ctx.cuisine_ids.items()}
        ctx.facility_ids = dict(db.facility_ids)
        ctx.facility_names = {facility_id: name for name, facility_id in ctx.facility_ids.items()}

        # Restaurants already in the database first (one may free a Google
        # place a new restaurant takes), then the new ones
        existing = [r for r in restaurants if _str(r.get("osm_id")) in db.restaurants]
        new = [r for r in restaurants if _str(r.get("osm_id")) not in db.restaurants]
        total = len(restaurants)
        for idx, r in enumerate(existing + new, start=1):
            try:
                if _str(r.get("osm_id")) in db.restaurants:
                    update_restaurant(cur, r, ctx, db, changes)
                else:
                    add_restaurant(cur, r, ctx, db, changes)
            except Exception:
                print(f"\nERROR at restaurant '{_str(r.get('name'))}' (osm_id={r.get('osm_id')})")
                raise
            if idx % 200 == 0 or idx == total:
                print(f"  Compared {idx}/{total} restaurants...")

        delete_gone_areas(cur, gone_areas, changes)
        delete_gone_cuisines(cur, ctx.cuisine_ids, changes)
        recount_not_in_file(cur, lost_link, changes)
        sync_photos(cur, changes)
        not_in_file = [row for osm_id, row in db.restaurants.items() if osm_id not in in_file]

        if dry_run:
            conn.rollback()
        else:
            write_todo(changes)
            conn.commit()
            if in_osm is not None:
                write_removed_file(db, undecided)
    except Exception as exc:
        conn.rollback()
        print(f"\nERROR: {exc}")
        print("Transaction rolled back: nothing was changed. Fix the error and run it again.")
        sys.exit(1)
    finally:
        conn.close()

    c = changes.counts
    print("\n" + "=" * 60)
    print("DRY RUN: these changes were made and then undone; nothing was saved"
          if dry_run else "LOAD COMPLETE")
    city_state = "added" if c["city added"] else "updated" if c["city updated"] else "unchanged"
    print(f"  city              : {city_state}")
    print(f"  sections          : {c['area added']} added, {c['area updated']} updated, "
          f"{c['area deleted']} deleted, {c['area unchanged']} unchanged"
          + (f", {c['area kept']} kept (still used)" if c["area kept"] else ""))
    print(f"  nearby places     : {c['place added']} added, {c['place updated']} updated, "
          f"{c['place deleted']} deleted, {c['place unchanged']:,} unchanged")
    print(f"  clusters          : {len(ctx.cluster_ids)} (old ones replaced)")
    print(f"  cuisines          : {len(ctx.cuisine_ids)} ({c['cuisine added']} added, "
          f"{c['cuisine updated']} updated"
          + (f", {c['cuisine deleted']} deleted" if c["cuisine deleted"] else "")
          + (f", {c['cuisine kept']} kept (still used)" if c["cuisine kept"] else "") + ")")
    print(f"  restaurants       : {c['restaurant new']} new, {c['restaurant changed']} changed, "
          f"{c['restaurant unchanged']} unchanged"
          + (f", {c['moved to new osm_id']} moved to a new osm_id" if c["moved to new osm_id"] else ""))
    if changes.fields:
        print("    changed         : " + ", ".join(f"{f} {n}" for f, n in changes.fields.most_common(8)))
    print(f"  ratings           : {c['rating updated']} updated")
    print(f"  reviews           : {c['reviews added']} added, {c['sentiments filled']} sentiments filled")
    print(f"  nearby counts     : {c['nearby counts updated']} restaurants updated; links "
          f"+{c['links added']} / -{c['links removed']}, {c['links moved']} distances changed")
    print(f"  sections changed  : {c['section changed']} restaurants")
    if c["photos table missing"]:
        print(f"  photos            : not loaded: the table restaurant_photo does not exist yet "
              f"(run {PHOTO_MIGRATION}, then run_7_loading.py again)")
    else:
        print(f"  photos            : {c['photos added']} added, {c['photos replaced']} replaced, "
              f"{c['photos deleted']} deleted, {c['photos unchanged']} unchanged"
              + (f"; {c['photo files missing']} files missing in data/cache/photos/"
                 if c["photo files missing"] else ""))
    if not_in_file:
        print(f"  not in this data  : {len(not_in_file)} restaurants in the database, left as they are"
              + (f" ({c['recounted']} recounted)" if c["recounted"] else ""))
    if in_osm is None:
        print(f"  gone from OSM     : not checked ({OSM_RAW_FILE} not found)")
    else:
        applied = c["removed closed"] + c["removed deleted"] + c["removed kept"]
        print(f"  gone from OSM     : {len(undecided)} waiting for your decision"
              + ("  (list not written: dry run)" if dry_run else f" -> {REMOVED_FILE}")
              + (f"; decided: {c['removed closed']} closed, {c['removed deleted']} deleted, "
                 f"{c['removed kept']} kept" if applied else ""))
        if no_longer_needed:
            print(f"  decisions no longer needed (back in OSM, or already deleted): "
                  f"{', '.join(no_longer_needed)}; you can remove them from {DECISIONS_FILE}")
    todo_counts = ", ".join(f"{len(v)} {k}" for k, v in changes.todo.items() if v) or "nothing"
    print(f"  stage 8 to-do     : {todo_counts}"
          + ("  (not written: dry run)" if dry_run else f"  -> {TODO_FILE}"))
    if held:
        print(f"\n  {len(held)} new restaurants NOT loaded:")
        for osm_id, reason in held.items():
            print(f"    osm {osm_id} {reason}")
        print("  If it is the same shop, add the new osm_id with that place_id to")
        print("  src/reference/google_match_overrides.json and run run_7_loading.py again:")
        print("  the existing row then moves to the new osm_id, with its reviews.")
    if changes.examples:
        print(f"\n  Changes ({min(len(changes.examples), c['examples'])} of {c['examples']}):")
        for line in changes.examples:
            print(f"    {line}")
    if waiting_for_ai:
        print(f"\n  {waiting_for_ai} restaurants NOT loaded: their AI profiling failed.")
        print("  Run run_4_profiling.py again (it asks only these), then run_5_validation.py,")
        print("  run_6_clustering.py and run_7_loading.py.")
    print("=" * 60)


if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parents[2])
    main(dry_run="--dry-run" in sys.argv)
