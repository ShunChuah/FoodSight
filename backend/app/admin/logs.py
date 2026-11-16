"""The pipeline's logs for the admin review page: data/logs/YYYY-MM-DD.log, one file per
day, written by src/run_log.py. Each run there starts with a header line
("===== 00:26:56  run_update.py =====") and ends with a footer line ("===== 00:49:56  end
of run_update.py (22 min 59 s) ====="). run_update.py starts each stage as its own
process, which writes its own header and footer inside the update's, so a day is a list of
runs, an update with its stages inside.

Problems are the WARNING, ERROR and CRITICAL log lines, the runner's own "WARNING: ..."
lines, and Python error traces. A problem repeated right after itself (three Neo4j
retries) is kept once with its count. A run with no footer was still running when the file
was read, or was cut off (a power cut, ended by hand)."""

import re
from pathlib import Path

from fastapi import HTTPException, status

from app import config

LOGS = "logs"
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAX_TEXT_LINES = 5000   # the most lines "Show the full text" sends at once
LINE_MAX = 2000         # characters of one line
TRACE_MAX = 80          # lines of one Python error trace

HEADER = re.compile(r"^===== (\d\d:\d\d:\d\d)  (.+) =====$")
FOOTER = re.compile(r"^end of (.+) \(([^()]*)\)$")
RECORD = re.compile(r"\d{4}-\d{2}-\d{2} (\d\d:\d\d:\d\d),\d{3} - (CRITICAL|ERROR|WARNING) - (.*)")
RUNNER_WARNING = re.compile(r"^WARNING: (.*)")
RUNNER_STARTED = re.compile(r"^FoodSight daily update \d{4}-\d{2}-\d{2}: (.*)")
RUNNER_RESULT = re.compile(r"^FoodSight daily update: (.*)")
UPDATE = "run_update.py"

_cache: dict[str, tuple] = {}


def _path(day: str) -> Path:
    if not DAY.match(day):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LOG_NOT_FOUND")
    path = config.PIPELINE_DATA_DIR / LOGS / f"{day}.log"
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "LOG_NOT_FOUND")
    return path


def _lines(path: Path) -> list:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def _new_run(command, started, line):
    script, _, args = command.partition(" ")
    return {"command": command, "script": script, "args": args, "started": started, "ended": None,
            "duration": None, "open": True, "first_line": line, "last_line": line,
            "did": None, "result": None, "problems": [], "stages": []}


def _add_problem(run, line_no, level, text):
    text = text[:LINE_MAX]
    problems = run["problems"]
    if problems and problems[-1]["text"] == text and problems[-1]["level"] == level:
        problems[-1]["count"] += 1
        return
    problems.append({"line": line_no, "level": level, "text": text, "count": 1})


def parse(path: Path) -> dict:
    """The day's runs, reused until the file changes."""
    stat = path.stat()
    stamp = (stat.st_mtime_ns, stat.st_size)
    hit = _cache.get(str(path))
    if hit and hit[0] == stamp:
        return hit[1]

    lines = _lines(path)
    runs, stack, loose = [], [], {"problems": []}
    trace = None   # the Python error trace being read: [run, first line number, lines]

    def end_trace():
        nonlocal trace
        if trace:
            run, first, text = trace
            _add_problem(run, first, "error", "\n".join(text[:TRACE_MAX]))
            trace = None

    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        if trace:
            if line.startswith((" ", "\t")):
                trace[2].append(line)
                continue
            if line and not HEADER.match(line):   # the exception itself ends the trace
                trace[2].append(line)
                end_trace()
                continue
            end_trace()

        header = HEADER.match(line)
        if header:
            time, command = header.groups()
            footer = FOOTER.match(command)
            if footer:
                ended, duration = footer.groups()[0], footer.group(2)
                for depth in range(len(stack) - 1, -1, -1):
                    if stack[depth]["command"] == ended:
                        while len(stack) > depth + 1:
                            stack.pop()["last_line"] = number - 1   # cut off inside this run
                        run = stack.pop()
                        run.update(ended=time, duration=duration, open=False, last_line=number)
                        break
                continue
            script = command.partition(" ")[0]
            # A stage opens inside an update that is between stages. A run or stage still
            # open means it was cut off: an update waits for its stage, so a power cut or
            # an ended task stopped both, and the new run starts on its own
            if stack and (stack[-1]["script"] != UPDATE or script == UPDATE):
                while stack:
                    stack.pop()["last_line"] = number - 1
            run = _new_run(command, time, number)
            (stack[-1]["stages"] if stack else runs).append(run)
            stack.append(run)
            continue

        run = stack[-1] if stack else None
        if run:
            run["last_line"] = number
        target = run or loose
        if line.startswith("Traceback (most recent call last):"):
            trace = [target, number, [line]]
            continue
        record = RECORD.search(line)
        if record:
            _add_problem(target, number, "error" if record.group(2) in ("ERROR", "CRITICAL") else "warning", record.group(3).strip())
            continue
        if run and run["script"] == UPDATE:
            started = RUNNER_STARTED.match(line)
            if started:
                run["did"] = started.group(1)
                continue
            result = RUNNER_RESULT.match(line)
            if result:
                run["result"] = result.group(1)
                continue
            warning = RUNNER_WARNING.match(line)
            # After its result line the runner repeats its warnings as a summary: kept once
            if warning and not run["result"]:
                _add_problem(run, number, "warning", warning.group(1))
    end_trace()

    def count(run, level):
        return (sum(p["count"] for p in run["problems"] if p["level"] == level)
                + sum(count(stage, level) for stage in run["stages"]))

    for run in runs:
        for item in [run, *run["stages"]]:
            item["warnings"], item["errors"] = count(item, "warning"), count(item, "error")
    day = {
        "day": path.stem,
        "size": stat.st_size,
        "lines": len(lines),
        "runs": runs,
        "loose_problems": loose["problems"],
        "warnings": sum(r["warnings"] for r in runs) + sum(p["count"] for p in loose["problems"] if p["level"] == "warning"),
        "errors": sum(r["errors"] for r in runs) + sum(p["count"] for p in loose["problems"] if p["level"] == "error"),
    }
    _cache[str(path)] = (stamp, day)
    return day


def days() -> list:
    """Every log day, newest first, with its size, number of runs and problems."""
    folder = config.PIPELINE_DATA_DIR / LOGS
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.log"), reverse=True):
        if not DAY.match(path.stem):
            continue
        day = parse(path)
        out.append({"day": day["day"], "size": day["size"], "runs": len(day["runs"]),
                    "warnings": day["warnings"], "errors": day["errors"]})
    return out


def day(name: str) -> dict:
    return parse(_path(name))


def text(name: str, start: int, end: int) -> dict:
    """Lines start to end (1-based, inclusive) of a day's log. When the range is longer
    than MAX_TEXT_LINES, its last lines are sent (where an error usually is), and
    skipped says how many were left out at the top."""
    lines = _lines(_path(name))
    start = max(1, start)
    end = min(len(lines), max(end, start))
    skipped = max(0, end - start + 1 - MAX_TEXT_LINES)
    first = start + skipped
    return {"start": first, "end": end, "skipped": skipped, "total": len(lines),
            "lines": [line[:LINE_MAX] for line in lines[first - 1:end]]}
