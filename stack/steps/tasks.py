"""Platform capability: run several routed model tasks at the same time, and say what each produced.

usage: tasks.py <receipt-path> <context> <profile> <spec> [<spec> ...]
       tasks.py <receipt-path> <context> <profile> --plan <plan.json>

       spec = label:provider:login:route:prompt-file:expected-file[:principal]
       plan = {"members": [{"label", "steps": [...], "retries"?, "retry_when"?}, ...]}
              (a member may be a sequence, run in order by steps/task_chain.py; members still run
              at the same time)

What this guarantees, and nothing more:

  * the tasks are started together and each is timed on its own (steps/fanout.py);
  * one task's failure does not touch another — every member is reported, none aborts the step;
  * a **receipt** is written before this step reports: for each member, what it was, whether the
    artifact it was asked for exists, that artifact's sha256, how long it took, and the member's
    own execution record as the routed call returned it — which is what lets the recorder give
    every member an MLflow run of its own. The receipt carries the caller's `context` string
    unchanged — the platform never interprets it, and a caller that wants its results bound to
    something (a frozen draft, a packet hash) passes that.

A member may ask to be **run again** when it does not produce: `"retries": 1` and, if it wants,
`"retry_when": ["failed", "denied"]`. The default is no retry and, when retries are asked for,
`["failed"]` only — a *denial* is an answer, and retrying an answer needs to be said out loud.
Whether a lane deserves a second attempt is the workflow's decision; being able to make that
decision is this step's job, and until it existed a workflow had no way to say it at all.
Every attempt is counted in the receipt (`attempts`, `attempt_outcomes`), because a retry that
disappears from the record is a run that lies about what it cost.

What this deliberately does not know: which members matter, what a missing one means, or whether
the result is any good. Those are the workflow's, and it decides them from the receipt.

Why this exists as a capability at all: Conductor's `parallel` and `for_each` groups refuse script
steps (v0.1.37), and every routed model call here is a script step. Without this, each workflow
writes its own fan-out — which is exactly what the first two trials did, twice, with their domain
rules mixed into it.
"""

# What a repeat of this step does (OPERATIONS.md §17): "yes" — the same result;
# "guarded" — it recognises the repeat; "no" — it does the work again.
REPEATABLE = "no"   # it starts model calls
import hashlib, json, os, sys

sys.path.insert(0, "/work/stack")
sys.path.insert(0, "/work/stack/steps")
import settings
import fanout

PY = os.environ.get("POC_PY", "/opt/venv/bin/python")
RUN = os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")
WS = f"{settings.runtime()['paths']['workspace_root']}/{RUN}"


def sha_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


receipt_path, context, prof = sys.argv[1], sys.argv[2], sys.argv[3]
if not os.path.isabs(receipt_path):
    receipt_path = f"{WS}/{receipt_path}"

jobs = []
if sys.argv[4:5] == ["--plan"]:
    # A member may be a chain of steps. The plan is written by the workflow, which is the only
    # place that knows what a lane of its experiment is made of; this step only runs it.
    plan = json.load(open(sys.argv[5], encoding="utf-8"))
    mdir = f"{WS}/.members"
    os.makedirs(mdir, exist_ok=True)
    for m in plan["members"]:
        m.setdefault("profile", prof)
        mp = f"{mdir}/{m['label']}.json"
        json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        expected = (m["steps"][-1].get("expected") or "")
        jobs.append({"key": m["label"], "label": m["label"],
                     "retries": int(m.get("retries") or 0),
                     "retry_when": [str(x) for x in (m.get("retry_when") or ["failed"])],
                     "provider": ",".join(sorted({st.get("provider", "none")
                                                  for st in m["steps"] if st["kind"] == "model"})) or "none",
                     "expected": expected, "produces": f"{WS}/{expected}" if expected else "",
                     "steps_planned": len(m["steps"]),
                     "argv": [PY, "/work/stack/steps/task_chain.py", mp]})
else:
    # A member whose role declares an egress profile runs through the broker, in that profile's
    # container, on that profile's network (§54). Same argv contract either way, so the receipt,
    # the retry loop and the recorder cannot tell the doors apart — which is the point.
    import role_egress
    for spec in sys.argv[4:]:
        parts = spec.split(":")
        label, provider, login, route, prompt, expected = parts[:6]
        principal = parts[6] if len(parts) > 6 else ""
        entry = ("/work/stack/steps/broker_dispatch.py"
                 if principal and role_egress.profile_of(principal)
                 else "/work/stack/steps/agent_task.py")
        jobs.append({"key": label, "label": label, "provider": provider, "expected": expected,
                     "produces": f"{WS}/{expected}",
                     "argv": [PY, entry, provider, route, label,
                              prompt, expected, prof, login, principal]})

def outcome_of(res, produced):
    """What this attempt was, in the words a member's `retry_when` uses."""
    if produced:
        return "produced"
    # a member that is a chain reports its own FAILED; the step that failed says what it was
    status = str(res.get("failed_status") or res.get("status") or "FAILED").upper()
    return "denied" if status in ("DENIED", "CONTROL_UNAVAILABLE", "TIMED_OUT") else "failed"


def read_row(r):
    try:
        res = json.loads(r["stdout"].strip().splitlines()[-1])
    except Exception:
        res = {"status": "FAILED", "produced": False,
               "error": (r["stderr"] or r["stdout"])[-200:]}
    return res, bool(res.get("produced"))


rows, wall = fanout.run_all(jobs)

# A member that asked for retries and did not produce is run again — on its own, so one lane's
# second attempt never delays another's first. Attempts are kept, not replaced: the receipt says
# how many there were and what each one was.
by_label = {r["label"]: r for r in rows}
job_of = {j["label"]: j for j in jobs}
history = {label: [outcome_of(*read_row(r))] for label, r in by_label.items()}
while True:
    again = []
    for label, r in by_label.items():
        job = job_of.get(label, {})
        used = len(history[label]) - 1                       # retries used so far
        if used >= (job.get("retries") or 0):
            continue
        if history[label][-1] in (job.get("retry_when") or ["failed"]):
            again.append(job)
    if not again:
        break
    more, w2 = fanout.run_all(again)
    wall += w2
    for r in more:
        by_label[r["label"]] = r
        history[r["label"]].append(outcome_of(*read_row(r)))
rows = list(by_label.values())

members, failed = {}, []
for r in rows:
    res, produced = read_row(r)
    if not produced:
        failed.append(r["label"])
    members[r["label"]] = {
        "provider": r["provider"], "artifact": r["expected"],
        "status": res.get("status", "FAILED"), "produced": produced,
        "sha256": sha_file(r["produces"]) if produced else "",
        "started_at": r["started_at"], "ended_at": r["ended_at"],
        "seconds": round(r["ended_at"] - r["started_at"], 2),
        # attempts *of this member*, and what each one was — the routed call's own retry (a login
        # the provider called transient) stays in its result, where it was
        "attempts": len(history.get(r["label"]) or [1]),
        "attempt_outcomes": history.get(r["label"]) or [],
        "call_attempts": res.get("attempts", 1), "run_id": res.get("run_id", ""),
        "steps_run": res.get("steps_run", 1), "steps_planned": r.get("steps_planned", 1),
        "failed_step": res.get("failed_step", ""),
        "error": res.get("error", "")[:200] if not produced else "",
        # the routed call's own record, kept whole: the recorder reads it, this step does not
        "result": res}

os.makedirs(os.path.dirname(receipt_path), exist_ok=True)
json.dump({"context": context, "wall_s": wall, "members": members},
          open(receipt_path, "w"), ensure_ascii=False, indent=1)

busy = round(sum(m["seconds"] for m in members.values()), 2)
print(json.dumps({
    "status": "OK",
    "receipt": receipt_path,
    "tasks": len(members),
    "produced": sum(1 for m in members.values() if m["produced"]),
    "model_calls": sum((m["result"] or {}).get("model_calls", 1) for m in members.values()),
    "failed": ",".join(failed),
    "wall_s": wall,
    "busy_s": busy,
    "longest_s": max((m["seconds"] for m in members.values()), default=0),
    # busy ÷ wall: 1.0 would mean they might as well have run one after another
    "overlap": fanout.overlap(rows, wall),
    "detail": json.dumps(members, ensure_ascii=False),
}))
