"""
FoodSight — Extraction scheduler (UC9)

Run by run_1_extraction.py right after the change check (detect_changes.py):
it reads the change report of the extraction that just ran and sets that
source's next extraction date. OSM and Google each have their own schedule.

  first extraction (the report is a baseline: nothing to compare with)
      → the default interval (DEFAULT_DAYS: OSM 7, Google 14), no AI
        (UC9's exception flow: no change summary yet)
  every later extraction
      → the AI (the same Gemma model as stage 4) reads the last few
        extractions and the rule: a change share of THRESHOLD (3%) or more
        means extract MORE often (fewer days), under it LESS often (more
        days), between MIN_DAYS and MAX_DAYS. It answers
        {"interval_days": ..., "reason": ...}.
  Google data fetched on an OSM day (only new or changed restaurants)
      → Google's schedule does not move; only a refresh counts.

The code checks the AI's answer: a number outside 1-60 is limited to it; an
answer that goes the wrong way (longer when the share is 3% or more, shorter
when it is under) is not used, and neither is a failed call (an error, no
GEMINI_API_KEY, the daily quota used up): the interval then stays as it was.
The same number of days is allowed (the interval stays).

When a source was extracted but its date did not move (the change check or
this scheduler failed, so there is no report to decide with), the daily
runner (run_update.py) calls move_without_report(): the interval is kept and
the next date moves on from that extraction, so the source is not extracted
again every night (a full paid refresh each time for Google).

Kept in data/state/schedule.json: per source the interval, the last
extraction, the next due date, who decided (default, ai, kept, runner) and
why, and the history of every decision. Each decision is also added to its change
report (data/reports/changes_<source>_<date_time>.json, under "schedule").
"""

import json
import os
from datetime import datetime, timedelta

from src.cache_saving import save_json

STATE_FILE = os.path.join("data", "state", "schedule.json")
REPORTS_DIR = os.path.join("data", "reports")
DEFAULT_DAYS = {"osm": 7, "google": 14}
MIN_DAYS, MAX_DAYS = 1, 60
THRESHOLD = 0.03      # change share at or above which a source is extracted more often
HISTORY_SHOWN = 5     # earlier extractions shown to the AI
NAMES = {"osm": "OpenStreetMap (OSM)", "google": "Google Places"}


def load_schedule(path=None):
    path = path or STATE_FILE
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _report_path(source, report):
    stamp = datetime.fromisoformat(report["extracted_at"]).strftime("%Y-%m-%d_%H%M")
    return os.path.join(REPORTS_DIR, f"changes_{source}_{stamp}.json")


def _file_counts(report):
    """{"restaurants": "9 new, 30 changed, 1 removed", ...} for the files that changed."""
    out = {}
    for info in (report.get("files") or {}).values():
        c = info.get("counts") or {}
        if c.get("new") or c.get("changed") or c.get("removed"):
            out[info.get("what")] = f"{c['new']} new, {c['changed']} changed, {c['removed']} removed"
    return out


def build_prompt(source, report, entry):
    """The prompt for the AI: the rule, the current interval, and the last
    extractions with their change shares."""
    current = entry["interval_days"]
    lines = [
        f"You set how often FoodSight extracts {NAMES[source]} data for the restaurants of "
        "Petaling Jaya, Malaysia. Extracting costs API calls and time; waiting too long leaves "
        "the data out of date.",
        f"Rule: if the latest change share is {THRESHOLD:.0%} or more, extract MORE often "
        f"(fewer days than now); if it is under {THRESHOLD:.0%}, extract LESS often (more days "
        f"than now). The answer must be a whole number of days from {MIN_DAYS} to {MAX_DAYS}.",
        "The change share is (new + changed + removed records) divided by all records of the "
        "extraction. Ratings, review counts and reviews never count as changes.",
        f"Current interval: {current} days.",
        "",
        "Extractions, oldest first:",
    ]
    history = entry.get("history", [])[-HISTORY_SHOWN:]
    for item in history:
        lines.append(_history_line(item))
    lines.append(_history_line({
        "extracted_at": report["extracted_at"], "days_since": report.get("days_since"),
        "change_share": report.get("change_share"), "changes": report.get("changes"),
        "records": report.get("records"), "files": _file_counts(report),
    }) + "   <- the latest")
    lines += [
        "",
        "ANSWER",
        "Respond in JSON only, no markdown, in this shape:",
        '{"interval_days": <whole number>, "reason": "<one sentence>"}',
    ]
    return "\n".join(lines)


def _history_line(item):
    when = datetime.fromisoformat(item["extracted_at"]).strftime("%Y-%m-%d")
    if item.get("decided_by") == "runner":
        return (f"- {when}: no change figures (the change check or the scheduler failed); "
                f"interval kept at {item['interval_after']} days")
    if item.get("change_share") is None:
        return f"- {when}: first extraction (nothing to compare with)"
    files = "; ".join(f"{what} {counts}" for what, counts in (item.get("files") or {}).items())
    line = (f"- {when}: {item.get('days_since')} days after the previous one; "
            f"{item.get('changes')} of {item.get('records')} records changed "
            f"({item['change_share']:.1%})")
    if item.get("interval_after"):
        line += f"; interval then set to {item['interval_after']} days"
    return line + (f" — {files}" if files else "")


def ask_ai(prompt):
    """The AI's answer {"interval_days", "reason"}, through stage 4's AI call
    (the same model, retries and speed limit). Raises when there is no usable
    answer."""
    from src.s4_profilers.profile_data import GEMINI_API_KEY, UnusableAnswer, call_ai

    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not found in .env")

    def check(answer):
        try:
            int(round(float(answer["interval_days"])))
        except (KeyError, TypeError, ValueError):
            raise UnusableAnswer("no whole number of days in interval_days") from None

    answer, _tries = call_ai(prompt, check)
    return answer


def decide(source, report, entry):
    """(interval_days, decided_by, reason) for an extraction after the first."""
    current = entry["interval_days"]
    share = report.get("change_share") or 0.0
    more_often = share >= THRESHOLD
    try:
        answer = ask_ai(build_prompt(source, report, entry))
    except BaseException as exc:  # noqa: BLE001 - any failure keeps the interval
        if isinstance(exc, KeyboardInterrupt):
            raise
        return current, "kept", f"no AI answer ({type(exc).__name__}: {str(exc)[:150]}): interval kept"
    days = int(round(float(answer["interval_days"])))
    reason = str(answer.get("reason") or "").strip() or "no reason given"
    if (more_often and days > current) or (not more_often and days < current):
        return current, "kept", (f"the AI answered {days} days, the wrong way for a {share:.1%} change "
                                 f"share ({f'{THRESHOLD:.0%} or more: fewer days' if more_often else f'under {THRESHOLD:.0%}: more days'}); "
                                 f"interval kept. Its reason: {reason}")
    limited = min(max(days, MIN_DAYS), MAX_DAYS)
    if limited != days:
        reason += f" (the AI answered {days} days, limited to {limited})"
    return limited, "ai", reason


def update_schedule(source, report, state_file=None):
    """Set the source's next extraction date from this extraction's change
    report (see the text at the top). Returns the source's schedule entry, or
    None when the report does not move the schedule."""
    state_file = state_file or STATE_FILE
    schedule = load_schedule(state_file)
    entry = schedule.get(source)
    title = "OSM" if source == "osm" else "Google"

    if source == "google" and not report.get("baseline") and not str(report.get("kind", "")).startswith("refresh"):
        print(f"\nSchedule: {title}'s next date stays "
              f"{(entry or {}).get('next_due', 'unset')} (only a full refresh moves it)")
        return None
    if entry and entry.get("last_extraction") == report["extracted_at"]:
        print(f"\nSchedule: this {title} extraction was scheduled already; next {entry['next_due']}")
        return entry

    before = entry["interval_days"] if entry else None
    if report.get("baseline") or not entry:
        days, decided_by = DEFAULT_DAYS[source], "default"
        reason = f"first extraction: the default {days} days, no AI"
        entry = {"history": (entry or {}).get("history", [])}
    else:
        days, decided_by, reason = decide(source, report, entry)

    when = datetime.fromisoformat(report["extracted_at"])
    entry.update(
        interval_days=days,
        last_extraction=report["extracted_at"],
        next_due=(when.date() + timedelta(days=days)).isoformat(),
        decided_by=decided_by,
        reason=reason,
    )
    entry["history"].append({
        "extracted_at": report["extracted_at"],
        "days_since": report.get("days_since"),
        "change_share": report.get("change_share"),
        "changes": report.get("changes"),
        "records": report.get("records"),
        "files": _file_counts(report),
        "interval_before": before,
        "interval_after": days,
        "decided_by": decided_by,
        "reason": reason,
    })
    schedule[source] = entry
    save_json(state_file, schedule)

    path = _report_path(source, report)
    if os.path.exists(path):
        report["schedule"] = {k: entry[k] for k in ("interval_days", "next_due", "decided_by", "reason")}
        save_json(path, report)

    change = "" if before in (None, days) else f" (was {before})"
    print(f"\nSchedule ({title}): every {days} days{change}, next {entry['next_due']} — {decided_by}: {reason}")
    return entry


def move_without_report(source, extracted_at, state_file=None):
    """The daily runner's fallback (see the text at the top): the source was
    extracted at `extracted_at` (ISO time), but the change check or the
    scheduler failed, so its date did not move. Keeps the current interval
    (the default for a source with no schedule yet) and sets the next date
    from this extraction. Returns the source's schedule entry."""
    state_file = state_file or STATE_FILE
    schedule = load_schedule(state_file)
    entry = schedule.get(source) or {"history": []}
    before = entry.get("interval_days")
    days = before or DEFAULT_DAYS[source]
    reason = ("the change check or the scheduler failed after this extraction (see the day's log), "
              "so there were no change figures to decide with: the daily runner kept the interval")
    when = datetime.fromisoformat(extracted_at)
    entry.update(
        interval_days=days,
        last_extraction=extracted_at,
        next_due=(when.date() + timedelta(days=days)).isoformat(),
        decided_by="runner",
        reason=reason,
    )
    entry.setdefault("history", []).append({
        "extracted_at": extracted_at,
        "days_since": None,
        "change_share": None,
        "changes": None,
        "records": None,
        "files": {},
        "interval_before": before,
        "interval_after": days,
        "decided_by": "runner",
        "reason": reason,
    })
    schedule[source] = entry
    save_json(state_file, schedule)
    return entry


def status_lines(state_file=None):
    """One line per source, for a quick look at the schedule."""
    schedule = load_schedule(state_file)
    lines = []
    for source in ("osm", "google"):
        entry = schedule.get(source)
        title = "OSM" if source == "osm" else "Google"
        if not entry:
            lines.append(f"{title:7} no extraction yet")
            continue
        last = entry["history"][-1]
        if last.get("decided_by") == "runner":
            share = "change check failed"
        elif last.get("change_share") is None:
            share = "first extraction"
        else:
            share = f"{last['change_share']:.1%} changed"
        lines.append(f"{title:7} last {entry['last_extraction'][:10]} ({share})   next {entry['next_due']}   "
                     f"every {entry['interval_days']} days ({entry['decided_by']}: {entry['reason']})")
    return lines


if __name__ == "__main__":
    print("\n".join(status_lines()))
