"""Run a workflow over a set of cases, and read the set back.

usage:
  suite.py run  <suite> <workflow> <profile> <cases.jsonl> [--concurrency N] [--allow-unrecorded]
  suite.py read <suite> [--json]

The boundary this sits on (CONTRACT.md): **what a case is, and whether an answer was right, is the
workflow's** — it needs labelled examples from whoever knows the domain, and a grader that says what
counts. **Starting a run for each case, keeping them apart, and reading back what each one did is
the platform's**, and until now this stack had only half of it: a run could be labelled with a
suite and its trajectory read (OPERATIONS §19), but nothing turned a file of cases into that set of
runs.

`cases.jsonl` is one JSON object per line. `case` is an id for the line; every other key is passed
to the workflow as an input, unread — a value this stack does not interpret is a value it cannot
distort. Lines this file cannot use are reported, not skipped silently.

What comes back is **execution fact**: how many runs reached a terminal step, how many were
recorded, what they cost, how often a rule decided a permission request and how often a person was
asked, whether the loops stayed inside their bounds. The decisions are counted too, and labelled as
what they are — the workflow's own word for how each run ended, not a grade. There is no accuracy
here and no score: joining these runs to the expected answers is the grader's work, and the `case`
each run carries is what it joins on.

What a repeat does (OPERATIONS.md §17): REPEATABLE = "guarded" — a case whose run already exists is
reported as already run, and is not started again.
"""
REPEATABLE = "guarded"
import json, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/work/stack")
import trajectory

PYTHON = os.environ.get("POC_PY", "/opt/venv/bin/python")
RUNS = "/work/evidence/ui-runs"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,19}")


def read_cases(path):
    """Every line as {case, inputs}, with the unusable ones named rather than dropped."""
    cases, bad = [], []
    for n, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            bad.append({"line": n, "why": f"not JSON: {e}"})
            continue
        if not isinstance(row, dict):
            bad.append({"line": n, "why": "not an object"})
            continue
        case = str(row.get("case") or f"c{n:03d}")
        if not NAME.fullmatch(case):
            bad.append({"line": n, "why": f"case id {case!r} is not [a-z0-9-] of 1 to 20"})
            continue
        cases.append({"case": case, "inputs": {k: str(v) for k, v in row.items() if k != "case"}})
    seen = {}
    for c in cases:
        seen.setdefault(c["case"], []).append(c)
    for case, rows in seen.items():
        if len(rows) > 1:
            bad.append({"case": case, "why": f"{len(rows)} lines share this case id"})
    return [c for c in cases if len(seen[c["case"]]) == 1], bad


def ui_for(suite, case):
    """One run id per (suite, case), so a repeat is recognised rather than duplicated."""
    return f"{suite}-{case}"[:40]


def start_one(suite, workflow, profile, case, extra):
    ui = ui_for(suite, case["case"])
    if os.path.isdir(f"{RUNS}/{ui}"):
        return {"case": case["case"], "ui": ui, "started": False, "why": "already run"}
    argv = [PYTHON, "/work/stack/run_workflow.py", "start", ui, workflow, profile]
    argv += [f"{k}={v}" for k, v in case["inputs"].items()]
    argv += ["--suite", suite, "--case", case["case"]] + extra
    r = subprocess.run(argv, capture_output=True, text=True)
    err = ""
    for line in (r.stdout or "").strip().splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("error"):
            err = d["error"]
    return {"case": case["case"], "ui": ui, "started": r.returncode == 0 and not err,
            "exit": r.returncode,
            "error": err or ((r.stderr or "").strip()[-200:] if r.returncode else "")}


def cmd_run(suite, workflow, profile, path, concurrency, extra):
    if not NAME.fullmatch(suite):
        print(json.dumps({"error": "a suite name is [a-z0-9-] of 1 to 20"}))
        return 2
    cases, bad = read_cases(path)
    if not cases:
        print(json.dumps({"error": "no usable case in " + path, "unusable": bad}))
        return 2
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        rows = list(pool.map(lambda c: start_one(suite, workflow, profile, c, extra), cases))
    ok = all(r["started"] or r.get("why") == "already run" for r in rows)
    print(json.dumps({"suite": suite, "workflow": workflow, "cases": len(cases),
                      "started": sum(1 for r in rows if r["started"]),
                      "already_run": sum(1 for r in rows if r.get("why") == "already run"),
                      "failed": [r for r in rows if not r["started"] and r.get("why") != "already run"],
                      "unusable": bad, "runs": rows}, ensure_ascii=False))
    return 0 if ok and not bad else 1


def summarise(rows):
    """Execution facts over the set. Nothing here says whether an answer was right."""
    ok = [t for t in rows if "error" not in t]

    def total(k):
        return sum(t.get(k) or 0 for t in ok)

    loops = [t["loop"] for t in ok if t.get("loop")]
    ended = {}
    for t in ok:
        d = t.get("decision") or t.get("state") or "—"
        ended[d] = ended.get(d, 0) + 1
    return {
        "runs": len(rows), "read": len(ok),
        "reached_a_terminal_step": sum(1 for t in ok if t["assertions"]["reached_a_terminal_step"]),
        "recorded": sum(1 for t in ok if t["assertions"]["recorded"]),
        "every_call_had_a_principal": sum(1 for t in ok
                                          if t["assertions"]["every_call_had_a_principal"] is True),
        "loops_within_bound": sum(1 for l in loops if l["within"]),
        "loops_measured": len(loops),
        "model_calls": total("model_calls"), "tokens": total("tokens"),
        "wall_s_in_calls": round(total("wall_ms") / 1000),
        "permission_requests": total("permission_requests"),
        "decided_by_rules": total("decided_by_rules"),
        "asked_a_person": total("approvals_requested"),
        "refused_by_a_rule": total("rule_denials"),
        "retries": total("retries"),
        # the workflow's own word for how each run ended — a tally, not a grade
        "ended_as": dict(sorted(ended.items())),
    }


def cmd_read(suite, as_json):
    rows = trajectory.of_suite(suite)
    if as_json:
        print(json.dumps({"suite": suite, "summary": summarise(rows), "runs": rows},
                         ensure_ascii=False))
        return 0
    for t in rows:
        trajectory._print(t)
        print()
    s = summarise(rows)
    print(f"suite {suite}: {s['read']} of {s['runs']} runs read")
    print(f"  reached a terminal step  {s['reached_a_terminal_step']}/{s['read']}"
          f"   recorded {s['recorded']}/{s['read']}"
          + (f"   loops within bound {s['loops_within_bound']}/{s['loops_measured']}"
             if s["loops_measured"] else ""))
    print(f"  permission asks          {s['permission_requests']}"
          f"  (rules {s['decided_by_rules']}, a person {s['asked_a_person']},"
          f" refused {s['refused_by_a_rule']})   retried {s['retries']}")
    print(f"  cost                     {s['model_calls']} calls, {s['tokens'] or '—'} tokens,"
          f" {s['wall_s_in_calls']}s in calls")
    print(f"  ended as                 {s['ended_as']}   (the workflow's word, not a grade)")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["run"] and len(a) >= 5:
        conc = int(a[a.index("--concurrency") + 1]) if "--concurrency" in a else 2
        extra = ["--allow-unrecorded"] if "--allow-unrecorded" in a else []
        sys.exit(cmd_run(a[1], a[2], a[3], a[4], conc, extra))
    if a[:1] == ["read"] and len(a) >= 2:
        sys.exit(cmd_read(a[1], "--json" in a))
    print(__doc__.strip().splitlines()[2].strip())
    sys.exit(2)
