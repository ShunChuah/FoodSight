"""
FoodSight — Run logs

Saves everything a pipeline run shows in the terminal (prints, log lines,
warnings and error tracebacks) into one file per day:
data/logs/YYYY-MM-DD.log. Every run that day, a stage run by hand or the
daily update, is added to the same file between a header line (the time and
the command) and a footer line (the time it ended and how long it took).
The terminal shows everything as before.

Each run_*.py starts it with two lines:

    from src.run_log import start_log
    start_log()

Old log files are never deleted automatically.
"""

import atexit
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"

_started = False


class _Tee:
    """A text stream that writes to the terminal stream it replaces and to
    the day's log file. If the log file cannot be written (a full disk),
    logging stops and the run goes on."""

    def __init__(self, stream, log_file):
        self._stream = stream
        self._log = log_file

    def write(self, text):
        if self._log is not None:
            try:
                self._log.write(text)
            except (OSError, ValueError):
                self._log = None
        if self._stream is not None:
            self._stream.write(text)
        return len(text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        if self._log is not None:
            try:
                self._log.flush()
            except (OSError, ValueError):
                self._log = None
        if self._stream is not None:
            self._stream.flush()

    def stop_logging(self):
        self._log = None

    def __getattr__(self, name):
        # encoding, isatty(), fileno() ...: answered by the terminal stream
        # (or by the log file when there is no terminal, as under pythonw)
        return getattr(self._stream if self._stream is not None else self._log, name)


def _duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} min {seconds} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min"


def safe_output():
    """Output sent to a file or pipe (python run_update.py > out.txt) uses
    Windows' cp1252, which cannot write characters such as → or Chinese
    names. Show those as ? there instead of stopping the run. Used by
    start_log(), and on its own by output that is not logged
    (run_update.py --status)."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def start_log():
    """Copy this run's terminal output into today's log file (see above).
    Calling it again in the same run does nothing."""
    global _started
    if _started:
        return
    _started = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    start = datetime.now()
    # Line-buffered, so each line reaches the file at once, even before a crash
    log_file = open(LOG_DIR / f"{start:%Y-%m-%d}.log", "a", encoding="utf-8", buffering=1)
    command = " ".join([Path(sys.argv[0]).name] + sys.argv[1:])
    log_file.write(f"\n===== {start:%H:%M:%S}  {command} =====\n")

    # A file or pipe shows characters such as → as ?; the log file is UTF-8
    # and keeps them
    safe_output()

    out, err = _Tee(sys.stdout, log_file), _Tee(sys.stderr, log_file)
    sys.stdout, sys.stderr = out, err

    def write_footer():
        try:
            out.flush()
            err.flush()
            end = datetime.now()
            log_file.write(f"===== {end:%H:%M:%S}  end of {command} "
                           f"({_duration((end - start).total_seconds())}) =====\n")
            log_file.close()
        except (OSError, ValueError):
            pass
        # Anything printed after this (other exit handlers) goes to the terminal only
        out.stop_logging()
        err.stop_logging()

    atexit.register(write_footer)
