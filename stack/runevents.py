"""Reading a run's Conductor event log: what the steps did, and how the run ended.

One reader, used by the panel's view, the list, the tail and the trajectory. It knows Conductor's
event types and nothing about any workflow. What it extracts for the screen:

  * the steps as they started, and the one running now;
  * the **routing** step's answer and the **recording** step's answer — recognised by what the
    step *said*, not by what the workflow called it. A step whose output carries `decision` and
    `evaluated` is the router speaking (stack/steps/route.py); one whose output carries
    `mlflow_run_id` is the recorder (stack/steps/record.py), whatever its name. Until this, the
    screen read a step named `route` and steps whose names started with `record`, so a workflow
    that called its recording step `persist_result` ran correctly and showed no record — a name
    the workflow chose was quietly an API (review 2026-10-02, OPERATIONS §68);
  * where and why the run terminated, its output, whether it ended, and whether the *last* thing
    the log recorded was the workflow completing (a stop and a later resume share one log, so only
    the last end describes the run).
"""
import json
from pathlib import Path


def conductor_run_of(path):
    """Conductor's run id, from the log's own name: conductor-<workflow>-<ts>-<run id>.events.jsonl"""
    return Path(path).name.rsplit("-", 1)[-1].split(".")[0]


def output_of(data):
    """A script step's output: the JSON its last stdout line carried, or None."""
    raw = data.get("stdout") or ""
    for cand in (raw, (raw.strip().splitlines() or [""])[-1]):
        try:
            d = json.loads(cand)
            return d if isinstance(d, dict) else None
        except ValueError:
            continue
    return None


def is_routing(out):
    """The router's answer, whatever the step is called (route.py: decision + evaluated)."""
    return isinstance(out, dict) and "decision" in out and "evaluated" in out and "provider" in out


def is_record(out):
    """The recorder's answer, whatever the step is called (record.py: mlflow_run_id)."""
    return isinstance(out, dict) and "mlflow_run_id" in out


def empty():
    return {"steps": [], "current_step": None, "route": None, "terminated_at": None,
            "termination_reason": None, "output": None, "conductor_run": None, "error": None,
            "mlflow": None, "ended": False, "ended_event_at": None, "completed_ok": False,
            "segment": 0}


def _new_segment(out):
    """A run that starts again in the same log — a resume after a stop or a failure — is read from
    here: what the earlier segment ended with (its end, its error, its output, where it terminated)
    is no longer this run's state. Measured before this: a resumed run whose process was alive read
    as `finished` with the old failure (review 3, OPERATIONS §79). The steps already taken stay."""
    out.update({"ended": False, "ended_event_at": None, "completed_ok": False, "error": None,
                "output": None, "terminated_at": None, "termination_reason": None,
                "segment": out.get("segment", 0) + 1})


def read(path):
    """The reading of one event log; `empty()` when there is no log yet."""
    out = empty()
    if not path:
        return out
    out["conductor_run"] = conductor_run_of(path)
    try:
        lines = Path(path).open().read().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        t, d = e.get("type"), e.get("data") or {}
        if t == "workflow_started" or (t == "agent_started" and out["ended"]):
            _new_segment(out)
        if t == "workflow_started":
            continue
        if t == "agent_started":
            out["current_step"] = d.get("agent_name")
            out["steps"].append({"step": d.get("agent_name"), "at": e.get("timestamp")})
        elif t == "script_completed":
            r = output_of(d)
            if is_routing(r):
                out["route"] = {k: r.get(k) for k in ("decision", "provider", "reason", "model_route", "profile")}
            elif is_record(r):
                out["mlflow"] = {"run_id": r.get("mlflow_run_id"), "experiment_id": r.get("experiment_id"),
                                 "error": r.get("record_error")}
        elif t == "agent_completed" and d.get("agent_type") == "terminate":
            out["terminated_at"] = d.get("agent_name")
            out["termination_reason"] = d.get("termination_reason")
        elif t == "workflow_completed":
            out["output"] = d.get("output"); out["ended"] = True; out["ended_event_at"] = e.get("timestamp")
            # A resumed run continues in the same event log, so the stop that interrupted it is
            # still in there. The run ended after it: the failure was superseded.
            out["error"] = None
            out["completed_ok"] = True
        elif t in ("workflow_failed", "agent_failed", "script_failed"):
            # an explicit failed terminate (HOLD, BLOCK, DENIED …) carries the workflow output
            if isinstance(d.get("output"), dict):
                out["output"] = d["output"]
            if t == "workflow_failed":
                out["ended"] = True; out["ended_event_at"] = e.get("timestamp")
                out["completed_ok"] = False
                # a failed terminate reports where and why only here
                out["terminated_at"] = out["terminated_at"] or d.get("terminated_by") or d.get("agent_name")
                out["termination_reason"] = out["termination_reason"] or d.get("termination_reason")
            if not d.get("is_explicit"):
                out["error"] = json.dumps(d)[:500]
    return out


def ended(path, from_byte=0):
    """Whether the log records the workflow ending — past `from_byte`, either way. Cheap: a scan
    for the two event names, used by the launcher's wait loop."""
    if not path:
        return False
    try:
        with Path(path).open() as f:
            f.seek(from_byte)
            for line in f:
                if '"workflow_completed"' in line or '"workflow_failed"' in line:
                    return True
    except OSError:
        pass
    return False
