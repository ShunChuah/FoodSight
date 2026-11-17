"""
FoodSight — the daily update (run by Windows Task Scheduler every night at
midnight; it can also be run by hand).

Each run does the first of these that applies:
  1. An extraction is due (its next date in data/state/schedule.json is today
     or earlier, see the scheduler, UC9): stage 1 for it, then stages 2-8.
     This also finishes any earlier unfinished run and applies any new
     decision (case 2), since stages 2-8 always process all the data.
        OSM due        python run_1_extraction.py
        Google due     python run_1_extraction.py --skip-osm --refresh-google
        both due       python run_1_extraction.py --refresh-google
     A Google refresh with new Google match decisions waiting first runs the
     decision step (python run_1_extraction.py --skip-osm, see case 2). A
     restaurant held for review is not in google_raw.csv, so a restaurant
     released as "same place" is a new Google row. Taken in by the decision
     step (whose change report the scheduler ignores), it is not counted again
     by the refresh, which then counts only real Google changes; otherwise 30
     approvals would look like a 4.7% change and the scheduler would refresh
     more often (more paid calls) with nothing changed on Google.
  2. Nothing due, but a decision file in src/reference/ changed since the run
     that last applied it (written by the admin review page, or by hand):
     from the first stage that reads it to stage 8. Only what the pipeline
     reads counts (a place ID, an excluded place, a decision); a note, who
     decided or the layout do not.
        google_match_overrides.json        stage 1 for Google only
                                           (python run_1_extraction.py
                                           --skip-osm: saved Google answers,
                                           no paid Place Details calls, no date
                                           moves; only the photos of newly
                                           approved restaurants are paid),
                                           then 2-8
        nearby_exclusions.json             stages 2-8 (no AI)
        removed_restaurant_decisions.json  stages 7-8
     The fingerprint of each file as last applied is kept in decisions_applied
     in data/state/run_state.json.
     An admin approving a business submission (business_submission.status
     approved, in PostgreSQL) counts here too: stages 3-8. Stage 7 adds the
     restaurant and sets the submission live, so it is not run again for it.
  3. Nothing else, but the last run stopped halfway: the stages from the one
     that failed to stage 8.
  4. Nothing else, but stage 4 left restaurants or reviews without an AI
     answer (data/review/ai_failed.json is not empty: an AI server error, for
     example): stages 4-8. Stage 4 asks only those; every other answer comes
     from its cache. This is tried every night until they have an answer.
  5. Nothing else, but the graph to-do list is not empty (Neo4j was closed
     last time): stage 8 only.
  6. Nothing to do: one line in the day's log.
When several of cases 2 to 5 apply, all are done tonight: the run starts at
the earliest stage any of them needs (an unfinished stage 6 with AI failures
waiting starts at stage 4).

"Extracted" means stage 1 rewrote the source's raw file (osm_raw.csv or
google_raw.csv; each is written only when its extraction succeeded), whatever
happened after it. When something fails:
  - stage 1, nothing extracted: the source stays due and the next run tries
    again (a warning says so). New decisions, an unfinished run, AI failures
    or a waiting graph to-do list are still dealt with tonight (as in cases 2
    to 5).
  - the decision step (stage 1 --skip-osm) did not rewrite google_raw.csv:
    a warning, the Google match decisions stay waiting for the next run, and
    the run goes on.
  - stage 1, one source extracted and the other not (OSM worked, the Google
    refresh did not): stages 2-8 still run; a warning names the one not
    extracted.
  - stage 1, extracted but its date did not move (the change check or the
    scheduler failed after the extraction): stages 2-8 run, the interval is
    kept and the next date moves on from this extraction
    (update_schedule.move_without_report), with a warning. Without this the
    source would stay due and be extracted again every night, for Google a
    full paid refresh each time.
  - stage 4 finished, but some restaurants or reviews still have no AI
    answer: the run goes on (they are left out for now) with a warning, and
    the next run asks them again (case 1 or 4).
  - stages 2-7 (stage 4 out of AI quota, for example): the bookmark in
    data/state/run_state.json remembers the stage; the next run continues
    from it (case 3), unless an extraction is due (case 1 does it all). A
    decision counts as applied only once the stage that reads it succeeded.
  - stage 8 (Neo4j Desktop not started): never blocks anything. The graph
    to-do list keeps the changes, and case 5 retries on every run.

Each stage is its own process and writes into the day's log as usual
(data/logs/YYYY-MM-DD.log), so a night's whole run is in one file. Warnings
are printed there as "WARNING: ...", kept in last_run.warnings in
data/state/run_state.json and shown by --status. A lock file stops two
updates from running at once.

Catch-up after a shutdown: the midnight task runs only while someone is
signed in, so a laptop that is off at midnight misses that night (Windows
looks for the missed run at start-up, before anyone signs in). A second
task, "FoodSight catch-up", starts python run_update.py --catch-up 5 minutes
after the user signs in. It does nothing when an update has finished since
midnight (last_finished in data/state/run_state.json, written at the end of
every run, a night with nothing to do too), and otherwise does the night's
update as usual. A run cut off halfway never finished, so the catch-up
continues it; a run that stopped on the AI quota did finish, so it waits
for the next midnight instead of hitting the same quota again.

Usage:
  python run_update.py                          # the daily job
  python run_update.py --status                 # what is due, unfinished, waiting; changes nothing
  python run_update.py --force osm|google|both  # extract now even if not due
  python run_update.py --catch-up               # the daily job, only if none has finished since midnight
"""

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.cache_saving import save_json
from src.s1_scrapers import update_schedule

STATE_FILE = os.path.join("data", "state", "run_state.json")
LOCK_FILE = os.path.join("data", "state", "run.lock")
TODO_FILE = os.path.join("data", "state", "graph_todo.json")   # written by run_7_loading.py
AI_FAILED_FILE = os.path.join("data", "review", "ai_failed.json")   # written by run_4_profiling.py
LOCK_STALE_HOURS = 21   # longer than the task's 20-hour limit: a lock this old was left by a crash
# Each source's main raw file: stage 1 writes it only when that extraction succeeded
RAW_FILES = {"osm": os.path.join("data", "1_raw", "osm_raw.csv"),
             "google": os.path.join("data", "1_raw", "google_raw.csv")}
TITLES = {"osm": "OSM", "google": "Google"}
STAGES = {
    2: "run_2_preprocessing.py",
    3: "run_3_merging.py",
    4: "run_4_profiling.py",
    5: "run_5_validation.py",
    6: "run_6_clustering.py",
    7: "run_7_loading.py",
    8: "run_8_graph.py",
}
QUOTA_EXIT = 2   # run_4_profiling.py stops with this when the AI's daily quota is used up
# The decision files (written by the admin review page, or by hand) and the
# first stage that reads each one (case 2)
REFERENCE_DIR = os.path.join("src", "reference")
OVERRIDES = "google_match_overrides.json"   # extract_google.py, in stage 1
DECISION_FILES = {
    OVERRIDES: 1,
    "nearby_exclusions.json": 2,              # clean_osm_nearby.py
    "removed_restaurant_decisions.json": 7,   # load_data.py
}
# Business submissions an admin approved (business_submission.status, in
# PostgreSQL): stage 3 reads them (src/s3_mergers/submissions.py), stage 7 sets live
APPROVED = "approved"
SUBMISSIONS_STAGE = 3


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _written_at(path):
    """When the file was last written (seconds), or None when it does not exist."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def run_stage(script, args=()):
    """Run one stage as its own process (it logs into the day's file itself);
    return its exit code. Without a console (the hidden task) no window opens."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.__stdout__ is None else 0
    print(f"\n>>> {_now()}  python {script} {' '.join(args)}".rstrip(), flush=True)
    return subprocess.run([sys.executable, script, *args], cwd=ROOT, creationflags=flags).returncode


# ---------------------------------------------------------------------------
# What is due, unfinished or waiting
# ---------------------------------------------------------------------------


def due_sources(today, schedule):
    """The sources whose next extraction date is today or earlier (a source
    with no schedule yet is due)."""
    due = []
    for source in ("osm", "google"):
        entry = schedule.get(source)
        if not entry or date.fromisoformat(entry["next_due"]) <= today:
            due.append(source)
    return due


def graph_waiting():
    """True when the graph to-do list has changes stage 8 has not copied yet."""
    todo = _read(TODO_FILE, None)
    return bool(todo) and (bool(todo.get("rebuild_clusters")) or any((todo.get("changes") or {}).values()))


def ai_failed_waiting():
    """(restaurants, reviews) that stage 4 has no AI answer for yet, from
    data/review/ai_failed.json (rewritten by every stage 4 run)."""
    try:
        items = (_read(AI_FAILED_FILE, None) or {}).get("items") or []
    except (OSError, ValueError):
        return 0, 0
    restaurants = sum(1 for item in items if item.get("kind") == "profile")
    return restaurants, len(items) - restaurants


def submissions_waiting():
    """How many business submissions an admin approved that no load has added
    yet (business_submission.status approved; stage 7 sets live). 0 when the
    table does not exist (migration 028 not run) or PostgreSQL cannot be
    reached (then stage 7 could not load them anyway)."""
    try:
        from src.s7_loader.load_data import get_connection
        conn = get_connection()
    except Exception:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.business_submission')")
            if cur.fetchone()[0] is None:
                return 0
            cur.execute("SELECT count(*) FROM public.business_submission WHERE status = %s", (APPROVED,))
            return cur.fetchone()[0]
    except Exception:
        return 0
    finally:
        conn.close()


def _submissions_text(n):
    return f"{n} approved business submission{'' if n == 1 else 's'} to add"


def _ai_failed_text(restaurants, reviews):
    parts = [f"{n} {word}{'' if n == 1 else 's'}"
             for n, word in ((restaurants, "restaurant"), (reviews, "review")) if n]
    return " and ".join(parts)


def _stages_text(first):
    if first == 1:
        return "python run_1_extraction.py --skip-osm (the decision step), then stages 2-8"
    return "stage 8 only" if first == 8 else f"stages {first}-8"


def decision_fingerprint(name):
    """A hash of what the pipeline reads from a decision file: the place ID of
    each override and its pin choice (stage 3 reads "pin": "google"), the
    excluded places, each decision. A note, who decided, when, or the layout
    are left out, so editing a note never starts a run. An override without a
    pin choice hashes as before the pin choice existed.
    None when the file does not exist; "unreadable" when it is not valid JSON
    (it then counts as changed, and the stage that reads it reports the error)."""
    try:
        doc = _read(os.path.join(REFERENCE_DIR, name), None)
    except (OSError, ValueError):
        return "unreadable"
    if doc is None:
        return None
    if name == OVERRIDES:
        used = {str(k): ([(v or {}).get("place_id"), v["pin"]] if (v or {}).get("pin") else (v or {}).get("place_id"))
                for k, v in (doc.get("overrides") or {}).items()}
    elif name == "nearby_exclusions.json":
        used = sorted(doc.get("exclusions") or {})
    else:
        used = {str(k): str((v or {}).get("decision") or "").strip().lower()
                for k, v in (doc.get("decisions") or {}).items()}
    return hashlib.sha256(json.dumps(used, sort_keys=True).encode("utf-8")).hexdigest()


def decisions_waiting(state):
    """{file: first stage that reads it} for the decision files that changed
    since the run that last applied them."""
    applied = state.get("decisions_applied") or {}
    return {name: stage for name, stage in DECISION_FILES.items()
            if decision_fingerprint(name) != applied.get(name)}


def _mark_applied(state, name, fingerprint):
    state.setdefault("decisions_applied", {})[name] = fingerprint


def catch_up(state):
    """When no extraction runs: what is left to do, as {"case", "from_stage",
    "why"}, or None. Cases 2 to 5 (see the text at the top): new decisions, an
    unfinished run, restaurants or reviews with no AI answer, a waiting graph
    to-do list. Everything that applies is done tonight, so the run starts at
    the earliest stage any of them needs; "case" is the first that applies."""
    needs = []   # (case, first stage, why)
    waiting = decisions_waiting(state)
    if waiting:
        needs.append((2, min(waiting.values()), f"new decisions in {', '.join(waiting)}"))
    approved = submissions_waiting()
    if approved:
        needs.append((2, SUBMISSIONS_STAGE, _submissions_text(approved)))
    unfinished = state.get("unfinished")
    if unfinished:
        needs.append((3, unfinished["stage"],
                      f"the last run stopped at stage {unfinished['stage']} ({unfinished['error']})"))
    failed = ai_failed_waiting()
    if any(failed):
        needs.append((4, 4, f"{_ai_failed_text(*failed)} with no AI answer yet ({AI_FAILED_FILE})"))
    if graph_waiting():
        needs.append((5, 8, "the graph to-do list is not empty"))
    if not needs:
        return None
    first = min(stage for _, stage, _ in needs)
    why = "; ".join(text for _, _, text in needs)
    if len(needs) > 1:
        why += f"; so from stage {first}"
    return {"case": needs[0][0], "from_stage": first, "why": why}


def plan(today, force=None):
    """What this run will do: {"case", "sources", "from_stage", "why",
    "decision_step"}. decision_step: run python run_1_extraction.py --skip-osm
    before a Google refresh, as Google match decisions are waiting (case 1)."""
    schedule = update_schedule.load_schedule()
    state = _read(STATE_FILE, {})
    if force:
        sources = ["osm", "google"] if force == "both" else [force]
        todo = {"case": 1, "sources": sources, "from_stage": 1, "why": f"--force {force}"}
    elif due := due_sources(today, schedule):
        todo = {"case": 1, "sources": due, "from_stage": 1,
                "why": ", ".join(s.upper() if s == "osm" else "Google" for s in due) + " due"}
    elif later := catch_up(state):
        return {"sources": [], "decision_step": False, **later}
    else:
        nxt = ", ".join(f"{'OSM' if s == 'osm' else 'Google'} {e['next_due']}" for s, e in schedule.items())
        return {"case": 6, "sources": [], "from_stage": None, "why": f"nothing to do (next: {nxt})",
                "decision_step": False}
    todo["decision_step"] = "google" in todo["sources"] and OVERRIDES in decisions_waiting(state)
    if todo["decision_step"]:
        todo["why"] += "; new Google match decisions are taken in first, so the refresh counts only real changes"
    return todo


def extraction_args(sources):
    if sources == ["osm"]:
        return []
    if sources == ["google"]:
        return ["--skip-osm", "--refresh-google"]
    return ["--refresh-google"]


def decision_step(state, runner, warn):
    """Take in new Google match decisions: stage 1 for Google only, with no
    refresh (python run_1_extraction.py --skip-osm). Saved Google answers are
    reused, so it makes no paid Place Details calls (only the photos of newly
    approved restaurants, 3 billed requests each), and no schedule moves (only a full
    refresh moves Google's date). Returns True when google_raw.csv was
    rewritten, which marks the overrides as applied."""
    fingerprint = decision_fingerprint(OVERRIDES)
    before = _written_at(RAW_FILES["google"])
    code = runner("run_1_extraction.py", ["--skip-osm"])
    after = _written_at(RAW_FILES["google"])
    if after is not None and after != before:
        _mark_applied(state, OVERRIDES, fingerprint)
        save_json(STATE_FILE, state)
        print("\nDecision step: the Google match decisions are taken in")
        return True
    warn(f"The Google match decisions ({REFERENCE_DIR}{os.sep}{OVERRIDES}) could not be taken in "
         f"(stage 1 --skip-osm exit code {code}; see the error above): they stay waiting, and "
         "the next run tries again")
    return False


# ---------------------------------------------------------------------------
# The lock
# ---------------------------------------------------------------------------


def _alive(pid):
    """True when a process with this ID is still running (Windows; elsewhere assumed)."""
    if os.name != "nt":
        return True
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


def running_lock():
    """The lock of an update that is still running, or None."""
    lock = _read(LOCK_FILE, None)
    if not lock:
        return None
    age = (datetime.now().astimezone() - datetime.fromisoformat(lock["started"])).total_seconds() / 3600
    return lock if age < LOCK_STALE_HOURS and _alive(lock["pid"]) else None


def finished_today(state, now=None):
    """When the last update finished, if that was since midnight (local time),
    or None. Any run of this script counts, whatever it did; --catch-up runs
    only when this is None. last_finished is written by every run (a night
    with nothing to do too); before it existed only last_run had a time."""
    text = state.get("last_finished") or (state.get("last_run") or {}).get("finished")
    try:
        when = datetime.fromisoformat(text) if text else None
    except ValueError:
        return None
    if when is None:
        return None
    when = when if when.tzinfo else when.astimezone()
    now = now or datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return when if when >= midnight else None


# ---------------------------------------------------------------------------
# The daily job
# ---------------------------------------------------------------------------


def daily(today=None, force=None, runner=run_stage):
    """Do today's update (see the text at the top). Returns the result text."""
    today = today or date.today()
    todo = plan(today, force)
    state = _read(STATE_FILE, {})
    print(f"FoodSight daily update {today}: {todo['why']}")
    if todo["case"] == 6:
        # Nothing to do is a finished update too, so a sign-in later today
        # does not run it again (--catch-up)
        state["last_finished"] = _now()
        save_json(STATE_FILE, state)
        return todo["why"]

    started = _now()
    result = None
    warnings = []

    def warn(text):
        warnings.append(text)
        print(f"WARNING: {text}", flush=True)

    first = todo["from_stage"]
    if first == 1 and todo["sources"]:
        if todo["decision_step"]:
            decision_step(state, runner, warn)
        # Taken after the decision step, which rewrites google_raw.csv itself
        schedule_before = update_schedule.load_schedule()
        files_before = {s: _written_at(p) for s, p in RAW_FILES.items()}
        overrides_before = decision_fingerprint(OVERRIDES)
        code = runner("run_1_extraction.py", extraction_args(todo["sources"]))
        schedule_after = update_schedule.load_schedule()
        # Rewritten by this stage 1. On an OSM day google_raw.csv is rewritten
        # too (Google lookups for new restaurants), without Google being due
        written = {s: t for s, p in RAW_FILES.items()
                   if (t := _written_at(p)) is not None and t != files_before[s]}
        if "google" in written:   # its Google part ran, and obeyed the overrides
            _mark_applied(state, OVERRIDES, overrides_before)
        print(f"\nStage 1 (exit code {code}): "
              + (", ".join(TITLES[s] for s in written) + " extracted" if written else "nothing extracted"))
        for source in todo["sources"]:
            title = TITLES[source]
            if source not in written:
                warn(f"{title} was due but nothing was extracted (stage 1 exit code {code}; see the "
                     "error above): it stays due, and the next run tries again")
            elif ((schedule_after.get(source) or {}).get("last_extraction")
                  == (schedule_before.get(source) or {}).get("last_extraction")):
                extracted_at = datetime.fromtimestamp(written[source]).astimezone().isoformat(timespec="minutes")
                entry = update_schedule.move_without_report(source, extracted_at)
                warn(f"{title} was extracted, but its schedule did not move: the change check or the "
                     f"scheduler failed (see the error above), so this extraction has no change figures. "
                     f"The interval was kept ({entry['interval_days']} days): next {title} extraction "
                     f"{entry['next_due']}")
        later = None if written else catch_up(state)
        if written:
            first = 2
        elif later:
            first = later["from_stage"]
            print(f"Nothing extracted; {later['why']}: {_stages_text(first)} run now")
        else:
            result = "nothing extracted, and nothing else to do"

    if result is None and first == 1:
        # Case 2 (or a night whose extraction failed): new Google match
        # decisions need stage 1 for Google. Stages 2-8 run even when it fails:
        # they are cheap (everything cached) and may have other decisions to apply
        decision_step(state, runner, warn)
        first = 2

    if result is None:
        for stage in range(first, 9):
            # Written before the stage starts: a run cut off from outside (a power
            # cut, the task's 20-hour limit, End in Task Scheduler) is continued
            # from this stage by the next run
            state["unfinished"] = {"stage": stage, "since": _now(),
                                   "error": "cut off while it was running (a power cut, the 20-hour "
                                            "limit, or ended by hand)"}
            save_json(STATE_FILE, state)
            # The decision files this stage reads, as it reads them now: they count
            # as applied once it succeeds
            reads = {name: decision_fingerprint(name) for name, s in DECISION_FILES.items() if s == stage}
            code = runner(STAGES[stage], ())
            if code == 0:
                for name, fingerprint in reads.items():
                    _mark_applied(state, name, fingerprint)
                if stage == 4:
                    left = ai_failed_waiting()
                    if any(left):
                        warn(f"Stage 4 still has no AI answer for {_ai_failed_text(*left)} (see "
                             f"{AI_FAILED_FILE}): they are left out of the database for now, and "
                             "the next run asks them again")
                if stage == 7 and (left := submissions_waiting()):
                    warn(f"{_submissions_text(left)} were not loaded (the validator rejected them: see "
                         "data/review/validation_invalid.json); the next run tries again")
                continue
            if stage == 8:
                result = (f"stage 8 failed (exit code {code}): the graph is not updated yet, and the "
                          "to-do list keeps the changes; start the FoodSight instance in Neo4j Desktop, "
                          "and the next run updates it")
                state.pop("unfinished", None)   # stages 2-7 are done
                break
            error = "the AI's daily quota is used up" if (stage == 4 and code == QUOTA_EXIT) else f"exit code {code}"
            state["unfinished"] = {"stage": stage, "since": _now(), "error": error}
            result = f"stopped at stage {stage} ({error}); the next run continues from it"
            break
        else:
            state.pop("unfinished", None)
            result = "all stages done"

    finished = _now()
    state["last_run"] = {"started": started, "finished": finished, "did": todo["why"], "result": result}
    state["last_finished"] = finished
    if warnings:
        state["last_run"]["warnings"] = warnings
    save_json(STATE_FILE, state)
    print(f"\nFoodSight daily update: {result}")
    for text in warnings:
        print(f"WARNING: {text}")
    return result


def status(today=None):
    today = today or date.today()
    state = _read(STATE_FILE, {})
    todo = plan(today)
    print(f"FoodSight daily update: status on {today}\n")
    print("Schedule:")
    for line in update_schedule.status_lines():
        print(f"  {line}")
    if todo["case"] == 1:
        what = (("python run_1_extraction.py --skip-osm (the decision step), then " if todo["decision_step"] else "")
                + f"python run_1_extraction.py {' '.join(extraction_args(todo['sources']))}".rstrip()
                + ", then stages 2-8")
    elif todo["case"] == 6:
        what = "nothing"
    else:
        what = _stages_text(todo["from_stage"])
    print(f"\nThe next run would do: {what}  ({todo['why']})")
    waiting = decisions_waiting(state)
    print("New decisions waiting: " + (", ".join(f"{name} (from stage {stage})" for name, stage in waiting.items())
                                       if waiting else "none"))
    approved = submissions_waiting()
    print("Business submissions: " + (f"{_submissions_text(approved)} (from stage {SUBMISSIONS_STAGE})"
                                      if approved else "none approved and waiting"))
    unfinished = state.get("unfinished")
    print(f"Unfinished run: " + (f"stage {unfinished['stage']} since {unfinished['since']} ({unfinished['error']})"
                                 if unfinished else "none"))
    failed = ai_failed_waiting()
    print(f"No AI answer yet: " + (f"{_ai_failed_text(*failed)} ({AI_FAILED_FILE}; the next run asks them again)"
                                   if any(failed) else "none"))
    todo_file = _read(TODO_FILE, None)
    waiting = ", ".join(f"{len(v)} {k}" for k, v in ((todo_file or {}).get("changes") or {}).items() if v)
    print(f"Graph to-do list: {waiting or ('only the clusters' if graph_waiting() else 'empty')}")
    lock = running_lock()
    print(f"Running now: " + (f"yes, since {lock['started']} (process {lock['pid']})" if lock else "no"))
    done = finished_today(state)
    print("Catch-up at sign-in: " + (f"nothing to do (today's update finished at {done.strftime('%H:%M')})" if done
                                     else "would run the update (none has finished since midnight)"))
    last = state.get("last_run")
    print(f"Last run: " + (f"{last['started']} to {last['finished']}: {last['did']}; {last['result']}" if last else "none yet"))
    for text in (last or {}).get("warnings", []):
        print(f"  WARNING: {text}")


def main():
    parser = argparse.ArgumentParser(description="FoodSight daily update: extract what is due, then stages 2-8.")
    parser.add_argument("--status", action="store_true", help="Show what is due, unfinished and waiting; change nothing.")
    parser.add_argument("--force", choices=["osm", "google", "both"], help="Extract now even if not due.")
    parser.add_argument("--catch-up", action="store_true",
                        help="The daily job, only if no update has finished since midnight "
                             "(the sign-in task 'FoodSight catch-up', for a laptop that was off at midnight).")
    args = parser.parse_args()
    if args.catch_up and (args.status or args.force):
        parser.error("--catch-up cannot be used with --status or --force")
    if args.status:
        status()
        return

    if args.catch_up:
        done = finished_today(_read(STATE_FILE, {}))
        if done:
            # The same first line as an update, so the admin page's Logs tab shows it as one
            print(f"FoodSight daily update {date.today()}: catch-up after sign-in: today's update already "
                  f"finished at {done.strftime('%H:%M')}, so nothing to do")
            return
        print("Catch-up after sign-in: no update has finished since midnight (the laptop was probably off "
              "at midnight), so it runs now")

    lock = running_lock()
    if lock:
        print(f"Another update is running since {lock['started']} (process {lock['pid']}): not starting a second one.")
        return
    save_json(LOCK_FILE, {"pid": os.getpid(), "started": _now()})
    try:
        daily(force=args.force)
    finally:
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass


if __name__ == "__main__":
    os.chdir(ROOT)
    from src.run_log import safe_output, start_log
    if "--status" in sys.argv:
        safe_output()   # not logged, but safe to send to a file or pipe
    else:
        start_log()
    main()
