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

sys.path.insert(0, "/work/p281")
sys.path.insert(0, "/work/p281/steps")
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
    root = tempfile.mkdtemp(prefix="p281-triage-")
    ws = os.path.join(root, "run")
    os.makedirs(ws)
    ns = load("/work/p281/steps/novel_stage.py", "novel_stage_ctl", ws)

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
    root = tempfile.mkdtemp(prefix="p281-lanes-")
    ws = os.path.join(root, "run")
    os.makedirs(ws)
    ts = load("/work/p281/steps/trade_stage.py", "trade_stage_ctl", ws)
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
    root = tempfile.mkdtemp(prefix="p281-roles-")
    ev = os.path.join(root, "route")
    os.makedirs(ev)

    def run(evaluated, args=("architect=codex", "author=claude", "cold=grok")):
        if evaluated is not None:
            json.dump({"decision": "ROUTE", "provider": "grok", "reason": "x",
                       "evaluated": evaluated}, open(f"{ev}/decision.json", "w"))
        elif os.path.isfile(f"{ev}/decision.json"):
            os.remove(f"{ev}/decision.json")
        p = subprocess.run(["/opt/venv/bin/python", "/work/p281/steps/roles.py",
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
    y = open("/work/p281/workflows/novel-a.yaml", encoding="utf-8").read()
    block = y.split("- name: record_block", 1)[1].split("- name: record_hold", 1)[0]
    check("record_block sends an execute record", "'execute'" in block, True)
    check("record_block sends the triage reason", "triage.output.reason" in block, True)
    check("record_hold still sends none (a real HOLD)",
          "'execute'" in y.split("- name: record_hold", 1)[1].split("routes:", 1)[0], False)

    src = open("/work/p281/run_workflow.py", encoding="utf-8").read()
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
    root = scratch or tempfile.mkdtemp(prefix="p281-scratch-")
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
    specs = ["story:claude:claude:direct:/work/p281/prompts/novel-review-story.md:review_story.json",
             "history:codex:codex:direct:/work/p281/prompts/novel-review-history.md:review_history.json",
             "cold:grok:grok:direct:/work/p281/prompts/novel-cold.md:review_cold.json"]

    for label, fail, want_triage in (("every reviewer produced", "", "PASS"),
                                     ("a required reviewer failed", "history", "BLOCK")):
        root = tempfile.mkdtemp(prefix="p281-step-")
        ws = real_ws()
        ns = load("/work/p281/steps/novel_stage.py", f"ns_{fail or 'all'}", ws)
        open(f"{ws}/draft.md", "w").write("a draft\n")
        ns.cmd_freeze()
        meta = json.load(open(f"{ws}/draft_meta.json"))

        res = run_step("/work/p281/steps/tasks.py", f"nr_{fail or 'all'}",
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
    root = tempfile.mkdtemp(prefix="p281-lanestep-")
    ws = real_ws()
    ts = load("/work/p281/steps/trade_stage.py", "ts_step", ws)
    _, packet, body, _ = ts.build_packet()
    open(f"{ws}/packet.json", "w", encoding="utf-8").write(body)
    syms = [s["symbol"] for s in packet["universe"]][:2]
    doc = json.dumps({"lane": "ai", "model_calls": 1, "refs": [],
                      "targets": [{"symbol": s, "weight": 0.2} for s in syms]})
    ts.cmd_baseline("base")                      # the workflow's own step, no model call
    specs = ["ai:codex:codex:direct:/work/p281/prompts/trade-lane.md:lane_ai.json",
             "ai2:claude:claude:direct:/work/p281/prompts/trade-lane2.md:lane_ai2.json"]
    res = run_step("/work/p281/steps/tasks.py", "tl_step",
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
    spec = importlib.util.spec_from_file_location("record_ctl", "/work/p281/steps/record.py")
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

    root = tempfile.mkdtemp(prefix="p281-rec-")
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

    # nothing ran at all
    sent.clear()
    out = rec.record({"check": check_, "route": route})
    check("a run the router held is still recorded",
          (out["executions"], tags_of(out["mlflow_run_id"]).get("status")), (0, "HOLD"))

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
    cap = open("/work/p281/steps/tasks.py", encoding="utf-8").read()
    body = "\n".join(l for l in cap.splitlines()
                     if not l.lstrip().startswith("#") and "Conductor" not in l)
    body = body.split('"""', 2)[-1].lower()          # code only, not the module's explanation
    found = sorted({w for w in DOMAIN_WORDS if w in body})
    check("no domain vocabulary in the capability's code", found, [])
    for name, path, want in (
            ("what is required", "/work/p281/steps/novel_stage.py", "required"),
            ("what a valid proposal is", "/work/p281/steps/trade_stage.py", "INVALID"),
            ("the deterministic baseline", "/work/p281/steps/trade_stage.py", "momentum20")):
        check(f"the workflow still owns: {name}", want in open(path, encoding="utf-8").read(), True)
    check("nothing imports the removed fan-out wrappers",
          any(os.path.exists(p) for p in ("/work/p281/steps/novel_reviews.py",
                                          "/work/p281/steps/trade_lanes.py")), False)
    y = open("/work/p281/workflows/novel-a.yaml", encoding="utf-8").read()
    check("the reviews step names the capability", "steps/tasks.py" in y, True)
    check("the triage step is told what is required", '"story,history"' in y, True)


# ---------------------------------------------------------------- members that are chains
def controls_chains():
    print("chains — a lane may be a sequence of steps, and stays one lane's business")
    root = tempfile.mkdtemp(prefix="p281-chain-")
    ws = real_ws()
    ts = load("/work/p281/steps/trade_stage.py", "ts_chain", ws)
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

    res = run_step("/work/p281/steps/tasks.py", "tasks_chain",
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
    res = run_step("/work/p281/steps/tasks.py", "tasks_chain_fail",
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
    spec = importlib.util.spec_from_file_location("record_chain", "/work/p281/steps/record.py")
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
    ts2 = load("/work/p281/steps/trade_stage.py", "ts_missing", ws)
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
    spec = importlib.util.spec_from_file_location("ops_health_ctl", "/work/p281/ops_health.py")
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
    d = tempfile.mkdtemp(prefix="p281-lock-")
    check("no lock is not a problem", oh.stuck_lock(os.path.join(d, "none")), None)
    open(os.path.join(d, "started"), "w").write("2026-09-23T04:00:00Z")
    open(os.path.join(d, "started_epoch"), "w").write(str(int(__import__("time").time()) - 3600))
    held = oh.stuck_lock(d)
    check("a held lock is reported with its age", (held["since"], held["age_s"] >= 3600),
          ("2026-09-23T04:00:00Z", True))
    shutil.rmtree(d, ignore_errors=True)

    # the rules live in p281/cycle.py — the shell script is only how a scheduler reaches them
    cyc = open("/work/p281/cycle.py", encoding="utf-8").read()
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
    spec = il.spec_from_file_location("traj_ctl", "/work/p281/trajectory.py")
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

    src = open("/work/p281/trajectory.py", encoding="utf-8").read()
    for word in ("accuracy", "grade", "grader", "score", "correct"):
        check(f"it does not grade ({word})", word in src.lower().split("assertions")[0], False)


# ---------------------------------------------------------------- evidence, joined to its claim
def controls_evidence():
    print("evidence — a judgement says what it rests on")
    import io, contextlib, importlib.util as il
    ws = real_ws()
    ns = load("/work/p281/steps/novel_stage.py", "ns_ev", ws)
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
    spec = il.spec_from_file_location("record_ev", "/work/p281/steps/record.py")
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
    root = tempfile.mkdtemp(prefix="p281-ev-")
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
    missing = [os.path.basename(f) for f in sorted(_glob.glob("/work/p281/steps/*.py"))
               if "REPEATABLE" not in open(f, encoding="utf-8").read()]
    check("every step says what a repeat of it does", missing, [])
    vals = {os.path.basename(f): re.search(r'REPEATABLE = "(\w+)"',
                                           open(f, encoding="utf-8").read()).group(1)
            for f in sorted(_glob.glob("/work/p281/steps/*.py"))}
    check("a model call is never claimed repeatable",
          [k for k in ("agent_task.py", "execute.py", "tasks.py", "task_chain.py")
           if vals.get(k) != "no"], [])

    ws = real_ws()
    ns = load("/work/p281/steps/novel_stage.py", "ns_rep", ws)
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
    spec = il.spec_from_file_location("record_rep", "/work/p281/steps/record.py")
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
    root = tempfile.mkdtemp(prefix="p281-princ-")
    ev = os.path.join(root, "route")
    os.makedirs(ev)
    json.dump({"decision": "ROUTE", "provider": "codex", "reason": "x",
               "evaluated": [{"provider": p, "eligible": True, "why": "within limits"}
                             for p in ("codex", "claude", "grok")]},
              open(f"{ev}/decision.json", "w"))
    out = json.loads(subprocess.run(
        ["/opt/venv/bin/python", "/work/p281/steps/roles.py", "research-default", ev,
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
    at = open("/work/p281/steps/agent_task.py", encoding="utf-8").read()
    check("the task passes it to the adapter", '"mcp_principal": principal' in at, True)
    check("and only when there is one", 'if principal else {}' in at, True)
    ad = open("/work/p281/run-agent.mjs", encoding="utf-8").read()
    check("the adapter fails closed without the credential",
          "is not set" in ad and "PRELOOP_MCP_" in ad, True)

    y = open("/work/p281/workflows/novel-a.yaml", encoding="utf-8").read()
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
    spec = importlib.util.spec_from_file_location("approvals_ctl", "/work/p281/approvals.py")
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
    spec2 = il.spec_from_file_location("elsewhere_ctl", "/work/p281/elsewhere.py")
    ew = il.module_from_spec(spec2)
    sys.modules["elsewhere_ctl"] = ew
    spec2.loader.exec_module(ew)
    st = ew.state()
    check("approval bypasses are read", "approval_bypasses" in st or "approval_bypasses_error" in st, True)
    check("the registered MCP servers are read", "mcp_servers" in st or "mcp_servers_error" in st, True)
    src = open("/work/p281/elsewhere.py", encoding="utf-8").read()
    check("and only read — nothing there is edited from here",
          any(m in src for m in ('method="POST"', 'method="PUT"', 'method="DELETE"')), False)

    page = open("/work/hub/index.html", encoding="utf-8").read()
    check("the page asks before it decides", "confirm(" in page, True)
    check("and says where the rest is done", "scripts/up.sh --check" in page, True)

    # one cycle implementation, and its arguments read the way a scheduler passes them
    spec = importlib.util.spec_from_file_location("cycle_ctl", "/work/p281/cycle.py")
    cy = importlib.util.module_from_spec(spec)
    sys.modules["cycle_ctl"] = cy
    spec.loader.exec_module(cy)
    check("the lock is a directory beside the record", cy.LOCK.endswith(".cycle.lock.d"), True)
    sh = open("/work/scripts/cycle.sh", encoding="utf-8").read()
    check("the shell entry point holds no rules of its own", "p281/cycle.py" in sh, True)
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
        y = open(f"/work/p281/workflows/{name}.yaml", encoding="utf-8").read()
        hold = [l for l in y.splitlines() if "HOLD:" in l]
        check(f"{name}: the hold message survives an early hold",
              all(("roles" not in l) or ("roles is defined" in l) for l in hold), True)


# ---------------------------------------------------------------- a reduced composition
def controls_composition():
    print("reduced — what a composition may drop, and what a run is refused for")
    sys.path.insert(0, "/work/p281")
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
    preloop = open("/work/docker/preloop.cadp.yaml", encoding="utf-8").read()
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
          "P281_PRELOOP_API: http://preloop-api:8000" in compose, True)
    ops_server = open("/work/ops/server.py", encoding="utf-8").read()
    check("the panel runs the decision itself, not in the agent",
          'jlocal(["/work/p281/approvals.py", "decide"' in ops_server, True)
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
    spec = il.spec_from_file_location("appr_ctl", "/work/p281/approvals.py")
    ap = il.module_from_spec(spec); sys.modules["appr_ctl"] = ap; spec.loader.exec_module(ap)
    old_env = dict(os.environ)
    try:
        os.environ["P281_PRELOOP_API"] = "http://preloop-api:8000"
        os.environ["PRELOOP_OPERATOR_TOKEN"] = "an-operators-own"
        check("the address comes from where it runs", ap._api(), "http://preloop-api:8000")
        check("an operator's own credential is used first", ap._token(), "an-operators-own")
        del os.environ["PRELOOP_OPERATOR_TOKEN"]
        os.environ["P281_CREDENTIAL_HOME"] = "/nowhere"
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
    ops = open("/work/p281/ops_health.py", encoding="utf-8").read()
    check("the probe reports the position it was run from, not a property of the credential",
          "This probe runs wherever it is run from, which is the point" in ops, True)


def controls_template():
    print("")
    print("what a second machine gets — the governance is declared, not remembered")
    import importlib.util as il, yaml
    spec = il.spec_from_file_location("prin_ctl", "/work/p281/principals.py")
    pr = il.module_from_spec(spec); sys.modules["prin_ctl"] = pr; spec.loader.exec_module(pr)
    src = open("/work/p281/principals.py", encoding="utf-8").read()
    up = open("/work/scripts/up.sh", encoding="utf-8").read()
    inst = open("/work/scripts/install.sh", encoding="utf-8").read()
    readme = open("/work/README.md", encoding="utf-8").read()
    decl = yaml.safe_load(open("/work/config/principals.yaml", encoding="utf-8"))["principals"]

    # Every principal any workflow names must be declared, or that workflow's steps run on a
    # second machine with no rights of their own — which is the gap this file closes.
    import glob as _glob, re as _re
    named = set()
    for f in _glob.glob("/work/p281/workflows/*.yaml"):
        named |= set(_re.findall(r'=[a-z0-9-]+:([a-z0-9-]+)', open(f, encoding="utf-8").read()))
    check("the principals the workflows name are declared", sorted(named - set(decl)), [])
    check("and the scan found the ones this stack uses",
          sorted(named & set(decl)), ["novel-author", "novel-reviewer"])
    check("and what each may do is in the file, not in someone's memory",
          bool((decl.get("novel-reviewer") or {}).get("tool_rules", {}).get("write_file")), True)
    check("a reviewer's last rule is the deny that makes the allow mean something",
          decl["novel-reviewer"]["tool_rules"]["write_file"][-1]["action"], "deny")
    check("applying it is part of every bring-up", "principals.py apply" in up, True)
    check("and it runs where a write to Preloop is allowed",
          '"$STACK-admin" /opt/venv/bin/python /work/p281/principals.py apply' in up, True)
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
    spec = il.spec_from_file_location("boot_ctl", "/work/p281/bootstrap_preloop.py")
    bp = il.module_from_spec(spec); sys.modules["boot_ctl"] = bp; spec.loader.exec_module(bp)
    src = open("/work/p281/bootstrap_preloop.py", encoding="utf-8").read()
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
          '"$STACK-agent" /opt/venv/bin/python /work/p281/cfg.py generate' in up
          and '"$STACK-admin" /opt/venv/bin/python /work/p281/cfg.py apply' in up, True)


def controls_resume():
    print("")
    print("stopping and continuing — a stop that leaves something to go on from")
    import importlib.util as il, json as _json, pathlib, tempfile
    spec = il.spec_from_file_location("rw_ctl", "/work/p281/run_workflow.py")
    rw = il.module_from_spec(spec); sys.modules["rw_ctl"] = rw; spec.loader.exec_module(rw)
    src = open("/work/p281/run_workflow.py", encoding="utf-8").read()
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


def controls_suite():
    print("")
    print("a set of cases — running it is ours, saying what it means is not")
    import importlib.util as il, tempfile, pathlib
    spec = il.spec_from_file_location("suite_ctl", "/work/p281/suite.py")
    su = il.module_from_spec(spec); sys.modules["suite_ctl"] = su; spec.loader.exec_module(su)
    src = open("/work/p281/suite.py", encoding="utf-8").read()

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
    oh = open("/work/p281/ops_health.py", encoding="utf-8").read()
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
