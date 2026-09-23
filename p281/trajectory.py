"""What a run actually did — assembled from what the stack already records.

usage:
  trajectory.py <ui-id> [--json]        one run
  trajectory.py --suite <name> [--json] every run labelled with that suite

This is the ground an evaluation stands on, and deliberately not the evaluation. Whether a
reviewer's verdict was right, or a lane was a good strategy, is what the work *means*, and meaning
belongs to the workflow (CONTRACT.md). What the platform can answer without knowing the domain is
the **trajectory**: which steps ran, how many model calls were made and as whom, what the tool
rules refused, how often something was retried, whether a loop stayed inside its bound, what it
cost, and what the judgement rested on.

Every number here is read from a record that already existed — Conductor's event log, the fan-out
receipts, each call's own result, the run's own output, the evidence index — so this file adds no
new source of truth. Where a fact cannot be read it is reported as `null`, never guessed.

The four **assertions** are true or false rather than opinions, which is what makes them worth
pinning: the loop stayed inside its bound; every model call carried a principal where the workflow
assigns them; the run reached a terminal step; the run was recorded. They say nothing about whether
the result was any good.
"""
import glob, json, os, re, sys

sys.path.insert(0, "/work/p281")
import settings

RUNS = "/work/evidence/ui-runs"
EVID = "/work/evidence/p281"


def _load(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def _view(ui):
    """The run as run_workflow.py sees it — the same reader the panel uses."""
    import subprocess
    out = subprocess.run(["/opt/venv/bin/python", "/work/p281/run_workflow.py", "show", ui],
                         capture_output=True, text=True, cwd="/work").stdout
    try:
        return json.loads(out)
    except Exception:
        return {}


def calls_of(view):
    """Every routed call this run made, with who made it and what it cost."""
    run = view.get("conductor_run")
    rows = []
    if not run:
        return rows
    for d in sorted(glob.glob(f"{EVID}/{run}-*")):
        res = _load(os.path.join(d, "result.json"))
        if not isinstance(res, dict):
            continue
        q = ((res.get("turn") or {}).get("_meta") or {}).get("quota") or {}
        rows.append({
            "call": os.path.basename(d),
            "provider": res.get("provider"),
            "principal": res.get("mcp_principal") or "",
            "status": res.get("status"),
            # a permission request that Preloop's *rules* decided is not a person being asked;
            # only the ones routed to the approval channel are (agent_task.py counts them the
            # same way, and this must not overstate what a human was involved in)
            "permission_requests": len(res.get("permissions") or []),
            "approvals_requested": sum(1 for x in (res.get("permissions") or [])
                                       if x.get("routed") == "preloop_approval"),
            "decided_by_rules": sum(1 for x in (res.get("permissions") or [])
                                    if x.get("routed") == "preloop_mcp_rules"),
            "rule_denials": len(res.get("mcp_denials") or []),
            "tokens": (q.get("token_count") or {}).get("totalTokens"),
            "wall_ms": res.get("wall_ms"),
        })
    return rows


def loop_of(view):
    """Rounds against the bound, when the workflow expresses one. Both are the run's own fields."""
    out, inp = view.get("output") or {}, view.get("inputs") or {}
    rounds = out.get("repairs")
    bound = inp.get("max_repairs")
    try:
        rounds, bound = int(rounds), int(bound)
    except (TypeError, ValueError):
        return None
    return {"rounds": rounds, "bound": bound, "within": rounds <= bound}


def evidence_of(view):
    """The judgement's own index (#5), if the run wrote one."""
    prefix = view.get("workspace_prefix")
    idx = _load(f"{prefix}/evidence_index.json") if prefix else None
    if not isinstance(idx, dict):
        return None
    items = idx.get("items") or []
    return {"decision": idx.get("decision"), "items": len(items),
            "by": sorted({str(i.get("by")) for i in items if i.get("by")}),
            "linked_to_a_call": sum(1 for i in items if i.get("execution_id"))}


def of_run(ui):
    view = _view(ui)
    if not view or view.get("error"):
        return {"ui": ui, "error": (view or {}).get("error", "no such run")}
    calls = calls_of(view)
    steps = [s["step"] for s in view.get("steps") or []]
    loop = loop_of(view)
    principals = sorted({c["principal"] for c in calls if c["principal"]})
    declared = bool(principals)          # the workflow assigns them, so every call should carry one
    t = {
        "ui": ui, "workflow": view.get("workflow"), "profile": view.get("profile"),
        "suite": view.get("suite") or "",
        "state": view.get("state"), "ended_at": view.get("terminated_at"),
        "decision": (view.get("output") or {}).get("decision"),
        "steps": steps,
        "model_calls": len(calls),
        "by_provider": {p: sum(1 for c in calls if c["provider"] == p)
                        for p in sorted({c["provider"] for c in calls if c["provider"]})},
        "by_principal": {p: sum(1 for c in calls if c["principal"] == p) for p in principals},
        "permission_requests": sum(c["permission_requests"] for c in calls),
        "approvals_requested": sum(c["approvals_requested"] for c in calls),
        "decided_by_rules": sum(c["decided_by_rules"] for c in calls),
        "rule_denials": sum(c["rule_denials"] for c in calls),
        "retries": sum(max(0, (c.get("attempts") or 1) - 1) for c in calls),
        "tokens": sum(c["tokens"] or 0 for c in calls) or None,
        "wall_ms": sum(c["wall_ms"] or 0 for c in calls) or None,
        "loop": loop,
        "capabilities_at_start": view.get("capabilities"),
        "evidence": evidence_of(view),
        "calls": calls,
    }
    t["assertions"] = {
        # each one is a fact about the run, not a judgement of its result
        "loop_within_bound": (loop or {}).get("within"),
        "every_call_had_a_principal":
            (all(c["principal"] for c in calls) if declared and calls else None),
        "reached_a_terminal_step": bool(view.get("terminated_at")),
        "recorded": bool((view.get("mlflow") or {}).get("run_id")),
    }
    return t


def of_suite(name):
    out = []
    for meta in sorted(glob.glob(f"{RUNS}/*/meta.json")):
        m = _load(meta, {})
        if (m or {}).get("suite") == name:
            out.append(of_run(m["ui_id"]))
    return out


def _print(t):
    if "error" in t:
        print(f"{t['ui']}: {t['error']}")
        return
    a = t["assertions"]
    print(f"{t['ui']}  {t['workflow']}  {t.get('decision') or t.get('ended_at') or t['state']}"
          + (f"  suite={t['suite']}" if t["suite"] else ""))
    print(f"  steps            {' → '.join(t['steps'])}")
    print(f"  model calls      {t['model_calls']}  {t['by_provider']}"
          + (f"  principals {t['by_principal']}" if t["by_principal"] else ""))
    print(f"  permission asks  {t['permission_requests']}"
          f"  (decided by rules {t['decided_by_rules']}, asked a person {t['approvals_requested']},"
          f" refused {t['rule_denials']})   retried {t['retries']}")
    if t["loop"]:
        print(f"  loop             {t['loop']['rounds']} of {t['loop']['bound']} allowed")
    if t["evidence"]:
        e = t["evidence"]
        print(f"  evidence         {e['items']} items, {e['linked_to_a_call']} tied to a call, "
              f"from {', '.join(e['by']) or '—'}")
    print(f"  cost             {t['tokens'] or '—'} tokens, {round((t['wall_ms'] or 0)/1000)}s in calls")
    print("  assertions       " + ", ".join(
        f"{k}={'—' if v is None else ('yes' if v else 'NO')}" for k, v in a.items()))


if __name__ == "__main__":
    args = sys.argv[1:]
    as_json = "--json" in args
    if "--suite" in args:
        rows = of_suite(args[args.index("--suite") + 1])
        if as_json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            for r in rows:
                _print(r)
                print()
            print(f"{len(rows)} run(s) in this suite")
        sys.exit(0)
    ui = next((a for a in args if not a.startswith("--")), None)
    if not ui:
        print(__doc__.strip().splitlines()[2]); sys.exit(2)
    t = of_run(ui)
    print(json.dumps(t, ensure_ascii=False)) if as_json else _print(t)
