"""Conductor script step: record what a run did in MLflow (REST, no client library).

Reads one JSON payload on stdin:

    {"execute":    <execution record>,          # the run's primary execution, if it has one
     "executions": [<execution record>, ...],   # more executions the workflow ran directly
     "receipts":   ["<path>", ...],             # fan-out receipts (steps/tasks.py): their members
     "check":      {"decision", "reason", "file_sha256"},
     "measurements": {...},                     # the run's own numbers, whatever they mean here
     "evidence_file": "<path>",                 # the run's semantic index, kept with the record
     "route":      <router output>}

What it records depends only on how many executions the run actually made:

  * **none, and no decision in `check`** — the router started nothing. That decision is a result
    too, so it is recorded (status HOLD, gate.decision NOT_RUN).
  * **none, with a decision in `check`** — the run judged without calling a model (a
    documentation check, a lint gate, a scanner). Recorded as status NO_EXECUTION with that
    decision, its reason and its evidence: a workflow does not have to call a model to have a
    result, and one that does not used to be written down as "nothing was judged".
  * **one** — one MLflow run, as before.
  * **more than one** — a parent run carrying the run's judgement, and a **child run per
    execution** (`mlflow.parentRunId`), each with its own provider, model, evidence and numbers.
    Until this existed, a multi-lane cycle had to flatten its lanes into a single record: the
    lanes' own tokens, durations and providers were in the evidence directory but could not be
    compared in MLflow, which is the whole point of running lanes.

Vendor-neutral: provider and model are recorded as data. Tagged with conductor.run_id, the same
attribute Conductor's own OTel traces carry (#278 F1), so the run and its trace join on it.

Recording is observation. Its failure is reported, never allowed to change the run's outcome: the
step always exits 0 and the workflow routes on the Gate decision as before (#278 N5). One child
that cannot be written does not lose the parent, and the failure is named in `record_error`.
"""

# What a repeat of this step does (OPERATIONS.md §17): "yes" — the same result;
# "guarded" — it recognises the repeat; "no" — it does the work again.
REPEATABLE = "guarded"   # the same run and judgement return the record already written (idempotency_key)
import json, os, sys, time, urllib.request

sys.path.insert(0, "/work/stack")
import settings


def mlflow_url():
    # MLFLOW_URL still overrides (the observation-failure tests point it at a dead host)
    return os.environ.get("MLFLOW_URL") or settings.runtime()["mlflow"]["url"]


def call(path, body=None, method="POST"):
    r = urllib.request.Request(mlflow_url() + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(r, timeout=20))


def put_artifact(exp_id, rid, path, name="result.json"):
    urllib.request.urlopen(urllib.request.Request(
        f"{mlflow_url()}/api/2.0/mlflow-artifacts/artifacts/{exp_id}/{rid}/artifacts/{name}",
        data=open(path, "rb").read(), method="PUT"), timeout=20)


def attach_evidence(payload, exp_id, rid):
    """Keep the run's semantic index with its record: which judgement rests on which call.

    The workflow writes it (what a finding means is the workflow's, CONTRACT.md); this only stores
    it beside the run and counts it, so a record can be read later without the workspace.
    """
    path = payload.get("evidence_file")
    if not path or not os.path.exists(path):
        return 0
    try:
        items = (json.load(open(path, encoding="utf-8")) or {}).get("items") or []
        put_artifact(exp_id, rid, path, "evidence_index.json")
        log(rid, {"evidence_items": len(items)})
        return len(items)
    except Exception:
        return 0


def experiment_id(payload):
    rt = payload.get("route") or {}
    ex = payload.get("execute") or {}
    prof = settings.profile(rt.get("profile") or ex.get("profile") or "research-default") or {}
    name = (prof.get("record") or {}).get("mlflow_experiment", "p281-routing")
    try:
        return call(f"/api/2.0/mlflow/experiments/get-by-name?experiment_name={name}",
                    method="GET")["experiment"]["experiment_id"]
    except urllib.error.HTTPError:
        return call("/api/2.0/mlflow/experiments/create", {"name": name})["experiment_id"]


def executions_of(payload):
    """Every execution this run made: the primary one, any the workflow passes, and the members
    of every fan-out receipt. A receipt that cannot be read is reported, not guessed at."""
    found, errors = [], []
    ex = payload.get("execute")
    if isinstance(ex, dict) and ex.get("run_id"):
        found.append(dict(ex))
    for e in payload.get("executions") or []:
        if isinstance(e, dict) and e.get("run_id"):
            found.append(dict(e))
    for rp in payload.get("receipts") or []:
        if not rp:
            continue
        try:
            rec = json.load(open(rp, encoding="utf-8"))
        except Exception as e:
            errors.append(f"receipt {os.path.basename(str(rp))}: {type(e).__name__}")
            continue
        for label, m in sorted((rec.get("members") or {}).items()):
            r = (m or {}).get("result")
            if not isinstance(r, dict):
                errors.append(f"receipt member {label}: no execution record")
                continue
            steps = [st for st in (r.get("steps") or [])
                     if isinstance(st, dict) and st.get("run_id") and st.get("kind") == "model"]
            if steps:
                # a member that is a chain is several executions, and each gets its own run
                found.extend({**st, "member": f"{label}:{st.get('step', '')}"} for st in steps)
            elif r.get("run_id") and r.get("provider"):
                found.append({**r, "member": label})
            else:
                errors.append(f"receipt member {label}: no execution record")
    seen, unique = set(), []
    for e in found:                       # a receipt and an `execute` can name the same execution
        if e["run_id"] in seen:
            continue
        seen.add(e["run_id"])
        unique.append(e)
    return unique, errors


def numbers(d):
    return [(k, float(v)) for k, v in (d or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)]


def log(rid, tags, metrics=(), params=()):
    now = int(time.time() * 1000)
    call("/api/2.0/mlflow/runs/log-batch", {"run_id": rid,
         "params": [{"key": k, "value": str(v)} for k, v in params],
         "tags": [{"key": k, "value": str(v)[:5000]} for k, v in tags.items()],
         # a missing measurement is omitted, not recorded as 0
         "metrics": [{"key": k, "value": v, "timestamp": now, "step": 0} for k, v in metrics]})


def new_run(exp_id, name):
    return call("/api/2.0/mlflow/runs/create",
                {"experiment_id": exp_id, "start_time": int(time.time() * 1000),
                 "run_name": name})["run"]["info"]["run_id"]


def finish(rid):
    call("/api/2.0/mlflow/runs/update", {"run_id": rid, "status": "FINISHED",
         "end_time": int(time.time() * 1000)})


def execution_tags(ex, ck, rt, cid):
    """The facts about one execution — the same set a single-execution run has always carried."""
    return {"conductor.run_id": cid, "provider": ex["provider"],
            "model_route": ex.get("model_route", ""), "status": ex["status"],
            "gate.decision": ck["decision"], "gate.reason": ck["reason"],
            "model.session_reported": ex["model_session_reported"],
            "model.adapter_reported": ex["model_adapter_reported"],
            "model.served": ex["model_served"], "evidence_dir": ex["evidence_dir"],
            "file_sha256": ck["file_sha256"], "route.decision": rt.get("decision", "manual"),
            "route.reason": rt.get("reason", "provider given as input"),
            "route.evaluated": rt.get("evaluated", ""), "ledger_error": ex.get("ledger_error", ""),
            "profile": rt.get("profile") or ex.get("profile", "")}


def execution_metrics(ex):
    return numbers({**(ex.get("measurements") or {}),
                    "approvals_requested": ex.get("approvals_requested"),
                    "mcp_rule_denials": ex.get("mcp_rule_denials")})


def existing(exp_id, key):
    """The run already recorded under this key, if there is one. A record is an observation of a
    thing that happened once; recording it twice — a resumed run, a step re-executed — would put
    two of the same run in the comparison and quietly double every count taken from it."""
    if not key:
        return None
    try:
        r = call("/api/2.0/mlflow/runs/search",
                 {"experiment_ids": [exp_id], "max_results": 1,
                  "filter": f"tags.idempotency_key = '{key}'"})
    except Exception:
        return None                      # cannot tell: record, and let the duplicate be visible
    runs = r.get("runs") or []
    return runs[0]["info"]["run_id"] if runs else None


def record(payload):
    ck = payload.get("check") or {}
    rt = payload.get("route") or {}
    cid = os.environ.get("CONDUCTOR_SELF_RUN_ID", "")
    # what makes this record the same record: the run, and the judgement being recorded
    key = payload.get("idempotency_key") or (
        f"{cid}:{ck.get('decision', '')}" if cid else "")
    exps, errors = executions_of(payload)
    exp_id = experiment_id(payload)
    already = existing(exp_id, key)
    if already:
        return {"mlflow_run_id": already, "experiment_id": exp_id, "executions": len(exps),
                "children": 0, "repeated": True, "record_error": "; ".join(errors)}

    if not exps:
        # Nothing executed. Two different runs look like this, and writing them down the same way
        # loses the one that matters:
        #   * the router started nothing — HOLD, and there is no judgement to record;
        #   * the run reached a judgement without calling a model — a documentation check, a
        #     lint gate, a scanner. That is a finished run with a decision, and recording it as
        #     HOLD/NOT_RUN said "nothing was judged" about a run that judged.
        # The check's own decision is the record; `status` says only that no model ran.
        decided = str(ck.get("decision") or "")
        rid = new_run(exp_id, f"{cid}-" + ("check" if decided else "hold"))
        log(rid, {"conductor.run_id": cid, "idempotency_key": key,
                  "provider": "none",
                  "status": "NO_EXECUTION" if decided else "HOLD",
                  "gate.decision": decided or "NOT_RUN",
                  "gate.reason": ck.get("reason", ""),
                  "file_sha256": ck.get("file_sha256", ""),
                  "route.decision": rt.get("decision"),
                  "route.reason": rt.get("reason"), "route.evaluated": rt.get("evaluated"),
                  "profile": rt.get("profile", ""),
                  "evidence_dir": rt.get("evidence_dir")},
            numbers(payload.get("measurements") or {}))
        n = attach_evidence(payload, exp_id, rid) if decided else 0
        finish(rid)
        return {"mlflow_run_id": rid, "experiment_id": exp_id, "executions": 0, "children": 0,
                "evidence_items": n, "record_error": "; ".join(errors)}

    if len(exps) == 1:
        ex = exps[0]
        rid = new_run(exp_id, ex["run_id"])
        log(rid, {**execution_tags(ex, ck, rt, cid), "idempotency_key": key}, execution_metrics(ex),
            [("provider", ex["provider"]), ("native_tools", "false")])
        res = os.path.join(ex["evidence_dir"], "result.json")
        if os.path.exists(res):
            put_artifact(exp_id, rid, res)
        n = attach_evidence(payload, exp_id, rid)
        finish(rid)
        return {"mlflow_run_id": rid, "experiment_id": exp_id, "executions": 1, "children": 0,
                "evidence_items": n, "record_error": "; ".join(errors)}

    # Several executions: the parent carries the run's judgement, each child its own execution.
    done = [e for e in exps if e.get("status") == "COMPLETED"]
    rid = new_run(exp_id, f"{cid}-run")
    log(rid, {"conductor.run_id": cid, "idempotency_key": key,
              "status": "COMPLETED" if len(done) == len(exps) else "PARTIAL",
              "gate.decision": ck.get("decision", ""), "gate.reason": ck.get("reason", ""),
              "file_sha256": ck.get("file_sha256", ""),
              "providers": ",".join(sorted({e["provider"] for e in exps})),
              "members": ",".join(e.get("member", e["run_id"]) for e in exps),
              "route.decision": rt.get("decision", "manual"), "route.reason": rt.get("reason", ""),
              "route.evaluated": rt.get("evaluated", ""), "evidence_dir": rt.get("evidence_dir", ""),
              "profile": rt.get("profile") or exps[0].get("profile", "")},
        numbers({**(payload.get("measurements") or {}),
                 "executions": len(exps), "executions_completed": len(done)}))

    children = 0
    for ex in exps:
        try:
            crid = new_run(exp_id, ex["run_id"])
            tags = execution_tags(ex, ck, rt, cid)
            tags["mlflow.parentRunId"] = rid
            if ex.get("member"):
                tags["member"] = ex["member"]
            log(crid, tags, execution_metrics(ex),
                [("provider", ex["provider"]), ("native_tools", "false")])
            res = os.path.join(ex.get("evidence_dir", ""), "result.json")
            if ex.get("evidence_dir") and os.path.exists(res):
                put_artifact(exp_id, crid, res)
            finish(crid)
            children += 1
        except Exception as e:           # one child lost is not the run's record lost
            errors.append(f"{ex.get('member') or ex['run_id']}: {type(e).__name__}: {e}"[:200])
    n = attach_evidence(payload, exp_id, rid)
    finish(rid)
    return {"mlflow_run_id": rid, "experiment_id": exp_id, "executions": len(exps),
            "children": children, "evidence_items": n, "record_error": "; ".join(errors)[:300]}


def main():
    payload = json.load(sys.stdin)
    try:
        out = record(payload)
    except Exception as e:
        out = {"mlflow_run_id": "", "experiment_id": "", "executions": 0, "children": 0,
               "record_error": f"{type(e).__name__}: {e}"[:300]}
    print(json.dumps(out))


if __name__ == "__main__":
    main()
