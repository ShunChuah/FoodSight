"""
FoodSight — Change check (UC10)

Right after an extraction, every record of the files just written is given a
hash (src/record_hash.py: fetch times, the rating and the review count are
left out, so they never count as a change) and compared with the last saved
copy of that source:

  new        in this extraction, not in the last copy
  changed    in both, with a different hash
  unchanged  in both, with the same hash
  removed    in the last copy, not in this extraction

  osm     osm_raw.csv (restaurants), osm_nearby_raw.csv (nearby places),
          osm_places_raw.csv (named places), osm_areas_raw.csv (sections),
          osm_city_raw.csv (the city)
  google  google_raw.csv, each place with its facilities (Google places).
          Reviews are not compared, since Google sends a different set of 5
          from time to time; their copy is kept and the new ones are counted.

change share = (new + changed + removed) ÷ the records of this extraction,
over all of the source's files. The extraction scheduler (UC9) uses it,
with days_since: the days since the last copy, except for a Google refresh,
whose days count from the last Google refresh (last_extraction in
data/state/schedule.json). A copy in between (an OSM day's Google lookups,
or a decision step's) still holds the answers that refresh fetched.

Output:
  data/reports/changes_<source>_<date_time>.json, after every extraction:
      the counts per file, the change share, and every new, removed and
      changed record; a changed record lists only its changed fields, old
      and new (an outline as "outline changed").
  data/archive/<source>/<date_time>/, a copy of the source's raw files with
      their hashes (hashes.json), saved only when something changed since
      the last copy. The first copy of a source is saved in any case: it is
      the baseline the next extraction is compared with.
<date_time> is when the extraction ran (the files' extracted_at), local time.
Nothing in data/archive/ is ever deleted.
"""

import json
import os
import shutil
from datetime import datetime, timezone

from src.cache_saving import save_json
from src.record_hash import LEFT_OUT, SORTED_LISTS, _rows, google_places, record_hash
from src.s1_scrapers.update_schedule import load_schedule

RAW_DIR = os.path.join("data", "1_raw")
ARCHIVE_DIR = os.path.join("data", "archive")
REPORTS_DIR = os.path.join("data", "reports")
HASHES_FILE = "hashes.json"
LONG_TEXT = 300  # a longer changed value (an outline) is not copied into the report

# For each source: the compared files (file, what one record is, key columns)
# and the files kept in its archive copy
SOURCES = {
    "osm": {
        "compare": [
            ("osm_raw.csv", "restaurants", ("osm_id",)),
            ("osm_nearby_raw.csv", "nearby places", ("osm_type", "osm_id")),
            ("osm_places_raw.csv", "named places", ("osm_id",)),
            ("osm_areas_raw.csv", "sections", ("osm_id",)),
            ("osm_city_raw.csv", "city", ("osm_id",)),
        ],
        "copy": ["osm_raw.csv", "osm_nearby_raw.csv", "osm_places_raw.csv",
                 "osm_areas_raw.csv", "osm_city_raw.csv"],
    },
    "google": {
        "compare": [("google_raw.csv", "Google places", ("osm_id",))],
        "copy": ["google_raw.csv", "google_facilities_raw.csv", "reviews_raw.csv"],
    },
}


def _key(row, columns):
    return "/".join(str(row.get(column) or "").strip() for column in columns)


def _records(folder, source):
    """{file: {key: row}} for the compared files of a source in a folder (the
    raw files, or an archive copy). A Google place row carries its facilities."""
    records = {}
    for file, _label, columns in SOURCES[source]["compare"]:
        rows = google_places(folder).values() if file == "google_raw.csv" else _rows(os.path.join(folder, file))
        records[file] = {_key(row, columns): row for row in rows}
    return records


def _extracted_at(folder, source):
    """When the extraction in a folder ran, from its main file's extracted_at,
    as local time (a time without a zone is UTC)."""
    rows = _rows(os.path.join(folder, SOURCES[source]["compare"][0][0]))
    text = (rows[0].get("extracted_at") or "").strip() if rows else ""
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now().astimezone()
    return (when if when.tzinfo else when.replace(tzinfo=timezone.utc)).astimezone()


def _copies(source, archive_dir):
    """The source's archive copies, oldest first."""
    folder = os.path.join(archive_dir, source)
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, name) for name in sorted(os.listdir(folder))
            if os.path.isfile(os.path.join(folder, name, HASHES_FILE))]


def _changed_fields(old, new):
    """{column: [old value, new value]} for the columns that changed (a long
    text such as an outline as "outline changed"), leaving out what never
    counts as a change, and a list whose order alone changed."""
    fields = {}
    for column in sorted(set(old) | set(new), key=str):
        if column is None or column in LEFT_OUT:
            continue
        a, b = str(old.get(column) or "").strip(), str(new.get(column) or "").strip()
        if column in SORTED_LISTS:
            a = ",".join(sorted(item.strip() for item in a.split(",") if item.strip()))
            b = ",".join(sorted(item.strip() for item in b.split(",") if item.strip()))
        if a == b:
            continue
        if column == "boundary_geojson":
            fields[column] = "outline changed"
        elif len(a) > LONG_TEXT or len(b) > LONG_TEXT:
            fields[column] = "long text changed"
        else:
            fields[column] = [a, b]
    return fields


def _save_copy(raw_dir, source, hashes, when, archive_dir):
    """Copy the source's raw files and their hashes into a dated folder."""
    stamp = when.strftime("%Y-%m-%d_%H%M")
    folder = os.path.join(archive_dir, source, stamp)
    n = 2
    while os.path.exists(folder):
        folder = os.path.join(archive_dir, source, f"{stamp}_{n}")
        n += 1
    os.makedirs(folder)
    for file in SOURCES[source]["copy"]:
        if os.path.exists(os.path.join(raw_dir, file)):
            shutil.copy2(os.path.join(raw_dir, file), os.path.join(folder, file))
    save_json(os.path.join(folder, HASHES_FILE), {
        "source": source,
        "extracted_at": when.isoformat(timespec="minutes"),
        "files": hashes,
    })
    return folder


def _days_counted_from(source, refresh, copy_when, when, schedule_file=None):
    """The time days_since counts from. For a Google refresh: the last Google
    refresh, its last_extraction in schedule.json (only a refresh moves it).
    The copy in between may be an OSM day's or a decision step's, which reuse
    the answers that refresh fetched, so counting from it would make the
    changes look far faster than they are (16 Nov 2026: 3.9 days instead of
    13.8). Otherwise, or with no earlier refresh in the schedule: the last copy."""
    if source != "google" or not refresh:
        return copy_when
    last = (load_schedule(schedule_file).get("google") or {}).get("last_extraction")
    try:
        last_when = datetime.fromisoformat(last) if last else None
    except ValueError:
        return copy_when
    if last_when is None:
        return copy_when
    last_when = last_when if last_when.tzinfo else last_when.astimezone()
    return last_when if last_when < when else copy_when


def check_changes(source, refresh=False, raw_dir=RAW_DIR, archive_dir=ARCHIVE_DIR, reports_dir=REPORTS_DIR,
                  schedule_file=None):
    """Compare the source's raw files with its last archive copy, write the
    change report, save a copy when something changed (always the first
    time), print the summary, and return the report. schedule_file (default
    data/state/schedule.json) gives a Google refresh its last refresh."""
    when = _extracted_at(raw_dir, source)
    path = os.path.join(reports_dir, f"changes_{source}_{when.strftime('%Y-%m-%d_%H%M')}.json")
    copies = _copies(source, archive_dir)
    if copies and os.path.exists(path):
        with open(os.path.join(copies[-1], HASHES_FILE), "r", encoding="utf-8") as f:
            last_when = json.load(f)["extracted_at"]
        if last_when == when.isoformat(timespec="minutes"):
            # This extraction was checked already, and its copy is the last one:
            # checking it again would compare it with itself and lose its report
            print(f"\n{source}: this extraction was checked already; its report: {path}")
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    records = _records(raw_dir, source)
    hashes = {file: {key: record_hash(row) for key, row in rows.items()} for file, rows in records.items()}
    labels = {file: label for file, label, _ in SOURCES[source]["compare"]}
    report = {
        "how_to_read": (
            "What changed in this extraction since the last saved copy. Per file: the counts, "
            "then every new and removed record (key and name) and every changed record with "
            "only its changed fields as [old, new]. Fetch times, the rating and the review "
            "count never count as a change; an outline is shown as 'outline changed' (both "
            "outlines are in the archive copies). change_share = (new + changed + removed) / "
            "the records of this extraction. days_since counts from days_counted_from: for a "
            "Google refresh the last Google refresh, otherwise the last saved copy (compared_with)."
        ),
        "source": source,
        "extracted_at": when.isoformat(timespec="minutes"),
    }
    if source == "google":
        report["kind"] = ("refresh: every saved match was fetched again" if refresh else
                          "OSM day: only new or changed restaurants were asked")
    title = "OSM" if source == "osm" else "Google"

    if not copies:
        folder = _save_copy(raw_dir, source, hashes, when, archive_dir)
        report.update(baseline=True, compared_with=None, change_share=None, copy=folder,
                      files={file: {"records": len(rows)} for file, rows in records.items()})
        print(f"\n{title}: first saved copy (the baseline); nothing to compare with yet")
        print("  " + ", ".join(f"{labels[f]} {len(rows):,}" for f, rows in records.items()))
        print(f"  copy: {folder}")
    else:
        previous = copies[-1]
        with open(os.path.join(previous, HASHES_FILE), "r", encoding="utf-8") as f:
            saved = json.load(f)
        before_hashes = saved["files"]
        before_records = _records(previous, source)
        before_when = datetime.fromisoformat(saved["extracted_at"])
        files, total_changes, total_records = {}, 0, 0
        for file, now in hashes.items():
            before = before_hashes.get(file, {})
            new = sorted(now.keys() - before.keys())
            removed = sorted(before.keys() - now.keys())
            changed = sorted(k for k in now.keys() & before.keys() if now[k] != before[k])
            files[file] = {
                "what": labels[file],
                "records": len(now),
                "records_before": len(before),
                "counts": {"new": len(new), "changed": len(changed), "removed": len(removed),
                           "unchanged": len(now) - len(new) - len(changed)},
                "new": [{"key": k, "name": records[file][k].get("name")} for k in new],
                "removed": [{"key": k, "name": (before_records[file].get(k) or {}).get("name")} for k in removed],
                "changed": [{"key": k, "name": records[file][k].get("name"),
                             "fields": _changed_fields(before_records[file].get(k) or {}, records[file][k])}
                            for k in changed],
            }
            total_changes += len(new) + len(changed) + len(removed)
            total_records += len(now)
        share = total_changes / total_records if total_records else 0.0
        counted_from = _days_counted_from(source, refresh, before_when, when, schedule_file)
        days = max((when - counted_from).total_seconds() / 86400, 0)
        folder = _save_copy(raw_dir, source, hashes, when, archive_dir) if total_changes else None
        report.update(baseline=False, compared_with=saved["extracted_at"], days_since=round(days, 1),
                      days_counted_from=counted_from.isoformat(timespec="minutes"),
                      changes=total_changes, records=total_records, change_share=round(share, 4),
                      copy=folder, files=files)
        if counted_from == before_when:
            since = f"({days:.1f} days)"
        else:
            since = (f"(the last copy); {days:.1f} days since the last Google refresh "
                     f"({counted_from.strftime('%Y-%m-%d %H:%M')})")
        print(f"\n{title} changes since {before_when.strftime('%Y-%m-%d %H:%M')} {since}"
              + (f" — {report['kind']}" if source == "google" else ""))
        for file, info in files.items():
            c = info["counts"]
            what = f"{info['records_before']:,} → {info['records']:,}"
            detail = ("unchanged" if not (c["new"] or c["changed"] or c["removed"]) else
                      f"{c['new']} new, {c['changed']} changed, {c['removed']} removed, {c['unchanged']:,} unchanged")
            print(f"  {info['what']:15} {what:>15}   {detail}")
        print(f"  change share    {total_changes:,} ÷ {total_records:,} = {share:.1%}")
        print(f"  copy: {folder}" if folder else "  copy: none saved (nothing changed since the last copy)")

    if source == "google":
        # Reviews: not compared, only the new ones counted (by review ID)
        seen = set()
        for copy in copies:
            seen |= {r.get("google_review_id") for r in _rows(os.path.join(copy, "reviews_raw.csv"))}
        now_reviews = {r.get("google_review_id") for r in _rows(os.path.join(raw_dir, "reviews_raw.csv"))}
        report["reviews"] = {"in_this_extraction": len(now_reviews),
                             "never_seen_before": len(now_reviews - seen) if copies else None}
        if copies:
            print(f"  reviews         {len(now_reviews - seen):,} never seen before (not counted as changes)")

    save_json(path, report)
    print(f"  report: {path}")
    return report


def last_seen_in_osm(osm_ids, archive_dir=ARCHIVE_DIR):
    """{osm_id: when (local "YYYY-MM-DD HH:MM") the newest OSM copy that
    still had the restaurant was extracted}, for the given osm_ids."""
    wanted, found = set(osm_ids), {}
    for copy in reversed(_copies("osm", archive_dir)):
        if not wanted:
            break
        with open(os.path.join(copy, HASHES_FILE), "r", encoding="utf-8") as f:
            saved = json.load(f)
        keys = saved["files"].get("osm_raw.csv", {})
        for osm_id in [i for i in wanted if i in keys]:
            found[osm_id] = datetime.fromisoformat(saved["extracted_at"]).strftime("%Y-%m-%d %H:%M")
            wanted.discard(osm_id)
    return found
