"""
Test data for the admin review page's Removed restaurants tab, which is empty while no
restaurant in the database has disappeared from OpenStreetMap.

  python tools/fake_removed_restaurant.py add      # puts 2 made-up restaurants on the tab
  python tools/fake_removed_restaurant.py status   # shows what test data is there
  python tools/fake_removed_restaurant.py remove   # takes them out again, with their decisions

The made-up restaurants have IDs no OpenStreetMap object has (999000000001 and
999000000002) and are in no database table. The loader applies a decision only to a
restaurant that is in the database, and reports one for an unknown ID as "no longer
needed", so clicking Closed, Delete or Keep for them can never change a real restaurant.

What it writes:
  data/review/removed_from_osm.json                the tab's list (add and remove)
  src/reference/removed_restaurant_decisions.json  remove only: the test restaurants'
                                                   decisions (any other decision is left alone)

Run "remove" when you are done, before midnight. A test decision left in the decisions
file counts as a new decision, so the nightly update would run stages 7-8 once: harmless
(nothing changes, and that load rewrites the list without the test restaurants), but
needless. Every load (stage 7) rewrites the list, so after one, run "add" again to test more.
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
from src.cache_saving import save_json  # noqa: E402  (temporary file, then swapped in)

REMOVED_FILE = os.path.join("data", "review", "removed_from_osm.json")
DECISIONS_FILE = os.path.join("src", "reference", "removed_restaurant_decisions.json")
OSM_RAW = os.path.join("data", "1_raw", "osm_raw.csv")
LOCK_FILE = os.path.join("data", "state", "run.lock")

# In the layout stage 7 writes (write_removed_file() in load_data.py), plus a pin of their
# own: they have no database row to take one from. Both in Petaling Jaya.
TEST_ITEMS = [
    {
        "osm_id": "999000000001", "osm_type": "node", "name": "TEST - Fake Kopitiam", "restaurant_id": None,
        "address": "12, Jalan SS 2/24, 47300 Petaling Jaya", "business_status": "OPERATIONAL",
        "last_seen_in_osm": "2026-11-12T00:26+08:00",
        "osm_map": "https://www.openstreetmap.org/node/999000000001", "google_map": None,
        "latitude": 3.1180, "longitude": 101.6205,
    },
    {
        "osm_id": "999000000002", "osm_type": "way", "name": "TEST - Fake Nasi Kandar", "restaurant_id": None,
        "address": "Jalan 14/20, Seksyen 14, 46100 Petaling Jaya", "business_status": "TEMPORARILY_CLOSED",
        "last_seen_in_osm": "2026-11-02T04:21+08:00",
        "osm_map": "https://www.openstreetmap.org/way/999000000002", "google_map": None,
        "latitude": 3.1045, "longitude": 101.6380,
    },
]
TEST_IDS = {item["osm_id"] for item in TEST_ITEMS}


def _read(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_decisions(doc):
    """The decisions file in its hand-written layout: _readme first, one decision per line
    (as the admin review page writes it), swapped in from a temporary file."""
    parts = [f"  {json.dumps(k)}: " + json.dumps(v, indent=2, ensure_ascii=False).replace("\n", "\n  ")
             for k, v in doc.items() if k != "decisions"]
    items = doc.get("decisions") or {}
    if items:
        lines = ",\n".join(f"    {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in items.items())
        parts.append(f'  "decisions": {{\n{lines}\n  }}')
    else:
        parts.append('  "decisions": {}')
    tmp = DECISIONS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write("{\n" + ",\n".join(parts) + "\n}\n")
    os.replace(tmp, DECISIONS_FILE)


def _update_running():
    lock = _read(LOCK_FILE, None)
    if not lock:
        return None
    started = datetime.fromisoformat(lock["started"])
    hours = (datetime.now().astimezone() - started).total_seconds() / 3600
    return lock["started"] if hours < 21 else None


def add():
    real_ids = {row["osm_id"] for row in csv.DictReader(open(OSM_RAW, encoding="utf-8"))} if os.path.exists(OSM_RAW) else set()
    if TEST_IDS & real_ids:
        sys.exit(f"Stopped: {sorted(TEST_IDS & real_ids)} is a real OpenStreetMap restaurant now; nothing written.")
    doc = _read(REMOVED_FILE, None)
    if doc is None:
        sys.exit(f"Stopped: {REMOVED_FILE} does not exist yet (run python run_7_loading.py once); nothing written.")
    items = [item for item in doc.get("items") or [] if str(item.get("osm_id")) not in TEST_IDS]
    doc["items"] = items + TEST_ITEMS
    doc["count"] = len(doc["items"])
    save_json(REMOVED_FILE, doc)
    print(f"Added {len(TEST_ITEMS)} test restaurants to {REMOVED_FILE}:")
    for item in TEST_ITEMS:
        print(f"  {item['osm_id']}  {item['name']}")
    print("Open the admin review page, Removed restaurants, to try Closed, Delete, Keep and Undo.")
    print("When you are done: python tools/fake_removed_restaurant.py remove")
    running = _update_running()
    if running:
        print(f"Note: an update is running since {running}; its stage 7 rewrites the list, which takes "
              "the test restaurants out. Run add again after it ends.")


def remove():
    doc = _read(REMOVED_FILE, None)
    removed_items = 0
    if doc is not None:
        before = len(doc.get("items") or [])
        doc["items"] = [item for item in doc.get("items") or [] if str(item.get("osm_id")) not in TEST_IDS]
        doc["count"] = len(doc["items"])
        removed_items = before - len(doc["items"])
        if removed_items:
            save_json(REMOVED_FILE, doc)
    decisions = _read(DECISIONS_FILE, None)
    removed_decisions = 0
    if decisions is not None:
        entries = decisions.get("decisions") or {}
        removed_decisions = sum(1 for key in list(entries) if key in TEST_IDS and entries.pop(key, None) is not None)
        if removed_decisions:
            decisions["decisions"] = entries
            _write_decisions(decisions)
    print(f"Removed {removed_items} test restaurants from {REMOVED_FILE} "
          f"and {removed_decisions} test decisions from {DECISIONS_FILE}.")


def status():
    items = [item for item in (_read(REMOVED_FILE, {}) or {}).get("items") or [] if str(item.get("osm_id")) in TEST_IDS]
    decisions = {k: v for k, v in ((_read(DECISIONS_FILE, {}) or {}).get("decisions") or {}).items() if k in TEST_IDS}
    print(f"Test restaurants on the list: {len(items)}" + "".join(f"\n  {i['osm_id']}  {i['name']}" for i in items))
    print(f"Test decisions in the decisions file: {len(decisions)}"
          + "".join(f"\n  {k}  {v.get('decision')}" for k, v in decisions.items()))
    if decisions:
        print("Run remove before midnight, or the nightly update runs stages 7-8 once for them (harmless).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test restaurants for the Removed restaurants tab.")
    parser.add_argument("action", choices=["add", "status", "remove"])
    {"add": add, "status": status, "remove": remove}[parser.parse_args().action]()
