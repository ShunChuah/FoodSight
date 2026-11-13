"""
FoodSight — Food Clusters (DBSCAN)
Finds the places in Petaling Jaya where open restaurants are packed close
together, such as the SS 2 food row or PJ Old Town.

Runs after run_5_validation.py and before run_7_loading.py:
  reads  data/5_validated/pj_validated.json
  writes data/6_clustered/pj_clustered.json (the same data, plus the clusters)

HOW DBSCAN WORKS (EPS_M = 200 m, MIN_SAMPLES = 5)
  1. Draw an EPS_M circle around each restaurant's pin and count the
     restaurants inside, the restaurant itself included.
  2. MIN_SAMPLES or more: a core restaurant (it sits in a busy spot).
  3. Core restaurants within EPS_M of each other are in the same cluster.
     This chains: A near B and B near C puts A, B and C in one cluster even
     when A and C are 400 m apart, so a cluster can follow a street.
  4. A restaurant within EPS_M of a core restaurant, but not core itself, is
     a border member: it joins that cluster but does not grow it. A border
     restaurant near two clusters joins the one found first, so in rare cases
     a cluster has fewer than MIN_SAMPLES members.
  5. Every other restaurant is noise: in no cluster (cluster_label null).
  Distances are straight-line metres on the earth (haversine), as in
  nearby_context.

WHICH RESTAURANTS
  Only restaurants that may still be trading (business_status OPERATIONAL or
  UNKNOWN: counted_as_open in src/reference/categories.json; UNKNOWN is a restaurant
  with no Google match) and will be loaded. A closed restaurant, and one
  without an AI profile (the loader leaves it out), gets cluster_label null.

WHAT EACH CLUSTER GETS (the top-level "clusters" list, biggest first)
  cluster_label     0, 1, 2, ...; the loader turns it into cluster_id 1, 2, 3, ...
  centroid_lat/lon  the average of the members' pins
  restaurant_count  the members, border members included
  boundary_geojson  a circle of radius EPS_M / 2 around each member's pin,
                    merged into one shape. Each member is within EPS_M of
                    another member, so the circles touch and the shape is one
                    piece (a Polygon).
  density_score     restaurant_count / the shape's area in km²
                    (restaurants per km²; higher = more tightly packed)

Each restaurant gets "cluster_label": its cluster's label, or null.

The settings and how many restaurants were clustered are saved under
"clustering" in the output file.
"""

import json
import math
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
from shapely.geometry import Point, mapping
from shapely.ops import transform, unary_union
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors

# Lets `src` be imported when this file is run directly, not through run_6_clustering.py.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.categories import get_column

EPS_M = 200        # how close counts as "near", in metres
MIN_SAMPLES = 5    # restaurants within EPS_M (itself included) that make a busy spot

INPUT_PATH = os.path.join("data", "5_validated", "pj_validated.json")
OUTPUT_PATH = os.path.join("data", "6_clustered", "pj_clustered.json")

EARTH_RADIUS_M = 6_371_000  # the same as every other distance in the pipeline

# A drawn circle is a many-sided shape that sits slightly inside the true
# circle. One extra metre keeps the circles of two members exactly EPS_M apart
# overlapping, so a cluster's shape never breaks into pieces.
CIRCLE_MARGIN_M = 1

# The business_status values of restaurants that may still be trading
# (OPERATIONAL and UNKNOWN), from src/reference/categories.json; only these are clustered.
OPEN_STATUSES = set(get_column("restaurant.business_status")["counted_as_open"])


def to_cluster(restaurant):
    """True for a restaurant that is clustered: it may still be trading
    (OPEN_STATUSES), and it is loaded (it has an AI profile)."""
    return (restaurant.get("business_status") in OPEN_STATUSES
            and bool(restaurant.get("business_profile")))


def run_dbscan(points, eps_m, min_samples):
    """points: [(lat, lon), ...]. Returns one label per point: 0, 1, 2, ... or -1 (noise)."""
    if not points:
        return []
    return DBSCAN(
        eps=eps_m / EARTH_RADIUS_M,  # haversine works in radians of the earth's circle
        min_samples=min_samples,
        metric="haversine",
        algorithm="ball_tree",
    ).fit_predict(np.radians(points))


def k_distance_check(points, eps_m, min_samples):
    """The usual check for choosing EPS_M: for each restaurant, the distance to
    its (MIN_SAMPLES - 1)th nearest other restaurant. Returns (share within
    eps_m, median metres, 75th percentile metres), or None if too few points."""
    k = min_samples - 1
    if k < 1 or len(points) <= k:
        return None
    finder = NearestNeighbors(n_neighbors=k, metric="haversine", algorithm="ball_tree")
    distances, _ = finder.fit(np.radians(points)).kneighbors()  # excludes the point itself
    kth = distances[:, k - 1] * EARTH_RADIUS_M
    return (float((kth <= eps_m).mean()),
            float(np.percentile(kth, 50)),
            float(np.percentile(kth, 75)))


def _flat_map(lat0):
    """Two functions: (lon, lat) in degrees -> (x, y) in metres on a flat map
    centred on latitude lat0, and back. Over a city the size of PJ (about
    15 km across) the shapes and areas are off by far less than 1%."""
    scale = math.cos(math.radians(lat0))

    def to_metres(lon, lat, z=None):
        return (np.radians(lon) * EARTH_RADIUS_M * scale, np.radians(lat) * EARTH_RADIUS_M)

    def to_degrees(x, y, z=None):
        return (np.degrees(np.asarray(x) / (EARTH_RADIUS_M * scale)),
                np.degrees(np.asarray(y) / EARTH_RADIUS_M))

    return to_metres, to_degrees


def _round(coords, digits=6):
    """Round nested GeoJSON coordinates (6 decimals is about 0.1 m)."""
    if isinstance(coords, (list, tuple)):
        return [_round(c, digits) for c in coords]
    return round(float(coords), digits)


def _geojson(geom):
    """A shapely geometry as a GeoJSON string, [longitude, latitude] order."""
    g = mapping(geom)
    return json.dumps({"type": g["type"], "coordinates": _round(g["coordinates"])})


def build_cluster(label, members, eps_m, to_metres, to_degrees):
    """One row of the "clusters" list from its member restaurants."""
    lats = [float(m["latitude"]) for m in members]
    lons = [float(m["longitude"]) for m in members]
    radius = eps_m / 2 + CIRCLE_MARGIN_M
    shape = unary_union([Point(to_metres(lon, lat)).buffer(radius) for lat, lon in zip(lats, lons)])
    area_km2 = shape.area / 1_000_000
    return {
        "cluster_label": label,
        "centroid_lat": round(sum(lats) / len(lats), 7),
        "centroid_lon": round(sum(lons) / len(lons), 7),
        "restaurant_count": len(members),
        "density_score": round(len(members) / area_km2, 1),
        "boundary_geojson": _geojson(transform(to_degrees, shape)),
    }


def _main_section(members):
    """For the printout only: the section with the most members, and how many others."""
    sections = Counter(m.get("area_name") or "(no section)" for m in members)
    name = sections.most_common(1)[0][0]
    return name + (f" (+{len(sections) - 1} more)" if len(sections) > 1 else "")


def main(eps_m=EPS_M, min_samples=MIN_SAMPLES, dry_run=False):
    print("=" * 60)
    print("FoodSight — Food Clusters (DBSCAN)")
    print("=" * 60)

    if not os.path.exists(INPUT_PATH):
        raise FileNotFoundError(f"{INPUT_PATH} not found.")
    with open(INPUT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    restaurants = data.get("restaurants", [])
    chosen = [r for r in restaurants if to_cluster(r)]
    points = [(float(r["latitude"]), float(r["longitude"])) for r in chosen]
    labels = run_dbscan(points, eps_m, min_samples)

    # Members of each cluster. A dict keeps the order DBSCAN found them in,
    # so clusters of the same size are always numbered the same way.
    groups = {}
    for restaurant, label in zip(chosen, labels):
        if label >= 0:
            groups.setdefault(int(label), []).append(restaurant)
    ordered = sorted(groups.values(), key=len, reverse=True)  # biggest first

    for restaurant in restaurants:
        restaurant["cluster_label"] = None

    clusters = []
    if points:
        lat0 = sum(p[0] for p in points) / len(points)
        to_metres, to_degrees = _flat_map(lat0)
        for label, members in enumerate(ordered):
            clusters.append(build_cluster(label, members, eps_m, to_metres, to_degrees))
            for member in members:
                member["cluster_label"] = label

    in_cluster = sum(len(m) for m in ordered)
    alone = len(chosen) - in_cluster

    # ── Summary ──────────────────────────────────────────────
    print(f"\nSettings      : {eps_m:g} m, {min_samples} restaurants")
    # Why the others were left out: not trading, or still waiting for the AI
    not_open = sum(1 for r in restaurants if r.get("business_status") not in OPEN_STATUSES)
    waiting = len(restaurants) - len(chosen) - not_open
    print(f"Restaurants   : {len(restaurants)} in total; {len(chosen)} open ones checked "
          f"({in_cluster} in a cluster); {not_open} closed or not open yet"
          + (f"; {waiting} waiting for AI profiling" if waiting else ""))
    check = k_distance_check(points, eps_m, min_samples)
    if check:
        share, median, p75 = check
        print(f"k-distance    : {share:.0%} of open restaurants have {min_samples - 1} others "
              f"within {eps_m:g} m")
        print(f"                (half have them within {median:.0f} m, "
              f"three quarters within {p75:.0f} m)")
    print(f"Clusters      : {len(clusters)}")
    if chosen:
        print(f"In a cluster  : {in_cluster} ({in_cluster / len(chosen):.0%})")
        print(f"In no cluster : {alone} ({alone / len(chosen):.0%})")

    if clusters:
        print(f"\n  {'#':>3}  {'restaurants':>11}  {'per km²':>7}  main section")
        for cluster, members in zip(clusters, ordered):
            print(f"  {cluster['cluster_label'] + 1:>3}  {cluster['restaurant_count']:>11}  "
                  f"{cluster['density_score']:>7.0f}  {_main_section(members)}")

    if dry_run:
        print("\nDry run: nothing saved.")
        print("=" * 60)
        return

    data["clusters"] = clusters
    data["clustering"] = {
        "eps_m": eps_m,
        "min_samples": min_samples,
        "restaurants_clustered": len(chosen),
        "in_a_cluster": in_cluster,
        "clustered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nSaved: {OUTPUT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    main()
