"""Update history for the admin review page: each extraction's change report
(data/reports/changes_<source>_<date_time>.json, written by the change check), each
source's scheduling decisions (data/state/schedule.json) and the dropped duplicates
(data/reports/google_duplicates.json). Everything is kept, so everything is shown."""

import re
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app import config
from app.admin import files

REPORTS = "reports"
DUPLICATES = "reports/google_duplicates.json"
REPORT_NAME = re.compile(r"^changes_(osm|google)_\d{4}-\d{2}-\d{2}_\d{4}\.json$")
# The scheduler's rule (THRESHOLD in src/s1_scrapers/update_schedule.py; change both
# together): a change share at or above it means extract more often. Shown on the chart.
CHANGE_THRESHOLD = 0.03
# For a first report, whose files carry only their record count
FILE_LABELS = {
    "osm_raw.csv": "restaurants",
    "osm_nearby_raw.csv": "nearby places",
    "osm_places_raw.csv": "named places",
    "osm_areas_raw.csv": "sections",
    "osm_city_raw.csv": "city",
    "google_raw.csv": "Google places",
}


def _report_names():
    folder = config.PIPELINE_DATA_DIR / REPORTS
    if not folder.is_dir():
        return []
    return sorted(p.name for p in folder.iterdir() if REPORT_NAME.match(p.name))


def _file_summaries(report):
    out = []
    for name, entry in (report.get("files") or {}).items():
        entry = entry or {}
        out.append({"file": name, "what": entry.get("what") or FILE_LABELS.get(name, name),
                    "records": entry.get("records"), "records_before": entry.get("records_before"),
                    "counts": entry.get("counts")})
    return out


def _decision(entry):
    if not entry:
        return None
    return {key: entry.get(key) for key in ("interval_before", "interval_after", "decided_by", "reason")}


def history():
    """Per source: the current schedule, and every extraction newest first, each with
    its report's figures and the scheduling decision made from it (matched by
    extracted_at). A decision with no report (the runner's, when the change check
    failed) is listed too; a Google OSM-day report has no decision (only a refresh moves
    Google's date)."""
    schedule = files.read_data(files.SCHEDULE, {}) or {}
    reports = {"osm": {}, "google": {}}
    for name in _report_names():
        report = files.read_data(f"{REPORTS}/{name}", {}) or {}
        source = report.get("source") or REPORT_NAME.match(name).group(1)
        if source in reports and report.get("extracted_at"):
            reports[source][report["extracted_at"]] = (name, report)

    sources = {}
    for source in ("osm", "google"):
        entry = schedule.get(source) or {}
        decisions = {item.get("extracted_at"): item for item in entry.get("history") or [] if item.get("extracted_at")}
        extractions = []
        for when in sorted(set(reports[source]) | set(decisions), reverse=True):
            name, report = reports[source].get(when, (None, None))
            decision = decisions.get(when)
            item = {"extracted_at": when, "report": name, "decision": _decision(decision)}
            if report:
                item.update({
                    "baseline": bool(report.get("baseline")),
                    "kind": report.get("kind"),
                    "compared_with": report.get("compared_with"),
                    "days_since": report.get("days_since"),
                    "changes": report.get("changes"),
                    "records": report.get("records"),
                    "change_share": report.get("change_share"),
                    "copy": report.get("copy"),
                    "reviews": report.get("reviews"),
                    "files": _file_summaries(report),
                })
            else:
                # Figures from the decision itself, when it has them
                item.update({"baseline": False, "kind": None, "days_since": decision.get("days_since"),
                             "changes": decision.get("changes"), "records": decision.get("records"),
                             "change_share": decision.get("change_share"), "files": []})
            extractions.append(item)
        sources[source] = {
            "schedule": {key: entry.get(key) for key in
                         ("interval_days", "last_extraction", "next_due", "decided_by", "reason")} if entry else None,
            "extractions": extractions,
        }

    duplicates_path = config.PIPELINE_DATA_DIR / DUPLICATES
    duplicates = files.read_data(DUPLICATES, {}) or {}
    written = (datetime.fromtimestamp(duplicates_path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
               if duplicates_path.exists() else None)
    return {
        "change_threshold": CHANGE_THRESHOLD,
        "sources": sources,
        "duplicates": {"file_written": written, "dropped": duplicates.get("dropped") or []},
    }


def report_detail(name, osm_types):
    """One report's records: per file the new, removed and changed ones, each with an
    OpenStreetMap link when its type is known. osm_types(ids) gives {osm_id: osm_type}
    for restaurants (from the database)."""
    if not REPORT_NAME.match(name):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "REPORT_NOT_FOUND")
    report = files.read_data(f"{REPORTS}/{name}", None)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "REPORT_NOT_FOUND")
    restaurant_files = ("osm_raw.csv", "google_raw.csv")
    ids = {str(item.get("key")) for file, entry in (report.get("files") or {}).items() if file in restaurant_files
           for group in ("new", "removed", "changed") for item in (entry or {}).get(group) or []}
    types = osm_types(sorted(ids)) if ids else {}

    def link(file, key):
        key = str(key)
        if file == "osm_nearby_raw.csv" and "/" in key:
            return f"https://www.openstreetmap.org/{key}"
        if file in ("osm_areas_raw.csv", "osm_city_raw.csv"):
            return f"https://www.openstreetmap.org/relation/{key}"
        if file in restaurant_files and types.get(key):
            return f"https://www.openstreetmap.org/{types[key]}/{key}"
        return None

    out = []
    for file, entry in (report.get("files") or {}).items():
        entry = entry or {}
        out.append({
            "file": file,
            "what": entry.get("what") or FILE_LABELS.get(file, file),
            "counts": entry.get("counts"),
            **{group: [{**item, "map": link(file, item.get("key"))} for item in entry.get(group) or []]
               for group in ("new", "removed", "changed")},
        })
    return {"name": name, "source": report.get("source"), "extracted_at": report.get("extracted_at"), "files": out}
