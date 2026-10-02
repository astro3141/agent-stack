"""Where a run's state lives, and the one explicit way it is restored.

A UI run is a directory under RUNS: `meta.json` (what was started, by which launcher, and the
state the launcher last wrote), `tmp/conductor/` (this run's own event log and checkpoints —
its TMPDIR, so nothing else's), `run.log`. This module owns the paths, the reading and writing
of meta, and the question "is the launcher still here".

`recover()` is the one function that changes a run's state without being its launcher, and it is
called by name: a reader that wants the restored state asks for it (`run_workflow.read`), a
reader that only looks (`run_workflow.view`) gets a view and changes nothing. Until this split
the view did both, so understanding what the panel showed meant knowing when it also wrote
(review 2026-10-02, OPERATIONS §68).
"""
import glob, json, os, time
from pathlib import Path

RUNS = Path("/work/evidence/ui-runs")


def run_dir(ui):
    return RUNS / ui


def meta_path(ui):
    return run_dir(ui) / "meta.json"


def load(ui):
    """The run's meta, or None when there is no such run."""
    p = meta_path(ui)
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def save(meta):
    meta_path(meta["ui_id"]).write_text(json.dumps(meta))
    return meta


def instance_id():
    """Identifies this container instance: PID 1's start time changes on every (re)start."""
    try:
        return open("/proc/1/stat").read().split(")")[1].split()[19] + "@" + os.uname().nodename
    except Exception:
        return "unknown"


def launcher_alive(meta):
    """Whether the process that started this run is still here — on this instance, and running."""
    if meta.get("instance") != instance_id():
        return False
    try:
        os.kill(int(meta.get("launcher_pid", 0)), 0)
        return True
    except (ProcessLookupError, ValueError, PermissionError):
        return False


def events_for(ui):
    """Exactly this run's event log, or None. Its TMPDIR holds this run's log and nothing else."""
    files = glob.glob(str(run_dir(ui) / "tmp" / "conductor" / "*.events.jsonl"))
    return Path(files[0]) if len(files) == 1 else None


def checkpoints_for(ui):
    """This run's checkpoints, oldest first. Its own TMPDIR, so they cannot be another run's."""
    return sorted((run_dir(ui) / "tmp" / "conductor" / "checkpoints").glob("*.json"),
                  key=lambda p: p.stat().st_mtime)


def state_of(meta, reading):
    """What state the run is in, given its meta and what its event log says — read, not written.

    The event log decides whether a run ended. A run the launcher still calls `running` whose log
    records the end is `finished`; one whose launcher is gone without an end is `interrupted`.
    """
    if meta.get("state") == "running":
        if reading.get("ended"):
            return "finished"
        if not launcher_alive(meta):
            return "interrupted"
    return meta.get("state")


def recover(meta, reading):
    """Persist what the launcher could not: the state the log and the launcher's absence imply.

    Only once the launcher is gone — a live launcher's own write (with the exit code) must not be
    raced. Returns the meta, updated and saved when something was restored, unchanged otherwise.
    """
    if meta.get("state") != "running" or launcher_alive(meta):
        return meta
    if reading.get("ended"):
        meta.update({"state": "finished", "exit": None, "ended_at": reading.get("ended_event_at"),
                     "recovered_from_event_log": True})
    else:
        meta.update({"state": "interrupted", "interrupted_detected_at": time.time()})
    return save(meta)
