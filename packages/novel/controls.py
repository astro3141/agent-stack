"""novel's own controls — the workflow's judgements, driven through its real step with fake inputs.

usage (agent container):  /opt/venv/bin/python /work/packages/novel/controls.py

A package's controls live with the package and are run by `scripts/packages.sh verify`
(docs/packages.md, "Controls"). Until 2026-10 these lived inside the platform's own suite,
stack/trial_controls.py, which imported this package's step to pin this package's rules — so the
platform's suite depended on a workflow's internals, and the rule for where a package's checks go
was "wherever they were written" (docs/record/PACKAGE-MATRIX.md, X6).

What is pinned here is novel's, not the platform's:

  triage    a review counts only for the draft it was written for, and only when this round's
            reviews step reports it produced — an older verdict, an emptied file and a document
            that is not a review all block instead of passing
  evidence  the index a judgement writes names the call that made each finding, the principal it
            ran as, the review it came from and the artifact it is about
  repeat    freezing the same bytes is one round; a repeated triage spends no repair round
  wiring    novel-a.yaml binds the author and the reviewers to different principals, every role's
            call carries its principal, the reviews step is the platform's fan-out and is told
            what is required, and "what is required" is this workflow's word, not the platform's

No model call, no network. The platform's capabilities this workflow uses (the fan-out, the
recorder, role binding) are pinned by the platform's suite, with this package as a fixture.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

PKG = os.path.dirname(os.path.abspath(__file__))
STEP = os.path.join(PKG, "steps", "novel_stage.py")
GRAPH = os.path.join(PKG, "novel-a.yaml")
sys.path.insert(0, "/work/stack/steps")        # `step` for the module under test, when run by hand

PASS, FAIL = [], []


def check(name, got, want):
    (PASS if got == want else FAIL).append((name, got, want))
    print(f"  {'ok  ' if got == want else 'FAIL'}  {name:<58} {got!r}"
          + ("" if got == want else f"  (expected {want!r})"))


def load(name, ws):
    """The step module with its workspace pointed at a temporary directory."""
    os.environ["CONDUCTOR_SELF_RUN_ID"] = os.path.basename(ws)
    spec = importlib.util.spec_from_file_location(name, STEP)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    m.WS = ws
    return m


def last_line(fn, *args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args)
    return json.loads(buf.getvalue().strip().splitlines()[-1])


OK = {"reviewer": "x", "usable": True, "verdict": "PASS",
      "findings": [{"kind": "NONE", "severity": "MINOR", "what": "fine"}]}
BLOCKING = {"reviewer": "x", "usable": True, "verdict": "REPAIR",
            "findings": [{"kind": "FACT_ERROR", "severity": "BLOCKING", "what": "wrong"}]}


# ---------------------------------------------------------------- triage
def triage_case(label, *, receipt_draft="d02", produced=True, story=None, history=None,
                tamper=False, no_receipt=False):
    """Freeze d01, review it, repair, freeze d02 — then vary what this round produced."""
    root = tempfile.mkdtemp(prefix="novel-triage-")
    ws = os.path.join(root, "run")
    os.makedirs(ws)
    ns = load(f"novel_stage_{label}", ws)

    open(f"{ws}/draft.md", "w").write("first draft\n")
    last_line(ns.cmd_freeze)                              # d01
    for n in ("story", "history"):
        json.dump({**OK, "reviewer": n}, open(f"{ws}/review_{n}.json", "w"))
    open(f"{ws}/draft.md", "w").write("repaired draft\n")
    last_line(ns.cmd_freeze)                              # d02 — a new round
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
        json.dump({"context": ctx, "members": members}, open(f"{ws}/reviews_round.json", "w"))
    if tamper:
        json.dump({**OK, "findings": [{"kind": "NONE", "severity": "MINOR"}]},
                  open(f"{ws}/review_story.json", "w"))
    try:
        return last_line(ns.cmd_triage, "1")["decision"]
    finally:
        shutil.rmtree(root, ignore_errors=True)


def controls_triage():
    print("triage — a review counts only for this round's draft")
    check("this round reviewed d02 and found nothing", triage_case("a", story=OK, history=OK), "PASS")
    # the defect: d01's reviews were still on disk, so a failed reviewer passed on the old verdict
    check("a required reviewer failed this round", triage_case("b", produced=False), "BLOCK")
    check("required reviews are empty objects", triage_case("c", story={}, history={}), "BLOCK")
    check("a required review has no findings",
          triage_case("d", story={"verdict": "PASS", "findings": []}, history=OK), "BLOCK")
    check("a finding carries no severity",
          triage_case("e", story={"verdict": "PASS", "findings": [{"kind": "NONE"}]}, history=OK), "BLOCK")
    check("the receipt names an earlier draft",
          triage_case("f", receipt_draft="d01", story=OK, history=OK), "BLOCK")
    check("no receipt from this round at all",
          triage_case("g", no_receipt=True, story=OK, history=OK), "BLOCK")
    check("the file changed after the reviews step",
          triage_case("h", story=OK, history=OK, tamper=True), "BLOCK")
    check("a blocking finding still repairs", triage_case("i", story=BLOCKING, history=OK), "REPAIR")


# ---------------------------------------------------------------- evidence
def controls_evidence():
    print("evidence — a judgement says what it rests on")
    root = tempfile.mkdtemp(prefix="novel-evidence-")
    ws = os.path.join(root, "run")
    os.makedirs(ws)
    ns = load("novel_stage_ev", ws)
    open(f"{ws}/draft.md", "w").write("a draft to judge\n")
    last_line(ns.cmd_freeze)
    meta = json.load(open(f"{ws}/draft_meta.json", encoding="utf-8"))
    blocking = {"reviewer": "story", "usable": True, "verdict": "REPAIR",
                "findings": [{"kind": "CONTRACT_MISS", "severity": "BLOCKING",
                              "what": "the contracted change never happens"}]}
    members = {}
    for n, doc, prov, call in (("story", blocking, "codex", "run-story"),
                               ("history", OK, "claude", "run-history"),
                               ("cold", OK, "grok", "run-cold")):
        json.dump(doc, open(f"{ws}/review_{n}.json", "w"))
        members[n] = {"artifact": f"review_{n}.json", "provider": prov, "produced": True,
                      "status": "COMPLETED", "sha256": ns.sha_file(f"{ws}/review_{n}.json"),
                      "result": {"run_id": call, "provider": prov, "principal": "novel-reviewer",
                                 "evidence_dir": f"/work/evidence/p281/{call}"}}
    json.dump({"context": meta["draft_sha256"], "members": members},
              open(f"{ws}/reviews_round.json", "w"))
    res = last_line(ns.cmd_triage, "1")
    idx = json.load(open(f"{ws}/evidence_index.json", encoding="utf-8"))
    check("the index is written and reported",
          (os.path.isfile(f"{ws}/evidence_index.json"), res["evidence_items"]), (True, len(idx["items"])))
    check("it names the judgement it explains", idx["decision"], "REPAIR")
    blocking_item = [i for i in idx["items"] if i.get("severity") == "BLOCKING"][0]
    check("a finding points at the call that made it", blocking_item["execution_id"], "run-story")
    check("and at the principal that call ran as", blocking_item["principal"], "novel-reviewer")
    check("and at the review it came from", blocking_item["review"]["sha256"], members["story"]["sha256"])
    check("and at the artifact it is about",
          (blocking_item["about"]["draft_id"], blocking_item["about"]["sha256"]),
          (meta["draft_id"], meta["draft_sha256"]))
    check("a reviewer that found nothing is still in the index",
          [i["by"] for i in idx["items"]].count("cold"), 1)
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- repeating a step
def controls_repeat():
    print("repeat — freezing the same draft is one round; a repeated triage spends nothing")
    root = tempfile.mkdtemp(prefix="novel-repeat-")
    ws = os.path.join(root, "run")
    os.makedirs(ws)
    ns = load("novel_stage_rep", ws)
    open(f"{ws}/draft.md", "w").write("one and only draft\n")
    first = last_line(ns.cmd_freeze)
    again = last_line(ns.cmd_freeze)
    check("freezing the same draft twice is one round",
          (first["draft_id"], again["draft_id"], again.get("repeated")), ("d01", "d01", True))
    open(f"{ws}/draft.md", "w").write("a repaired draft\n")
    check("a different draft is a new round", last_line(ns.cmd_freeze)["draft_id"], "d02")

    meta = json.load(open(f"{ws}/draft_meta.json", encoding="utf-8"))
    members = {}
    for n, doc in (("story", BLOCKING), ("history", OK), ("cold", OK)):
        json.dump(doc, open(f"{ws}/review_{n}.json", "w"))
        members[n] = {"artifact": f"review_{n}.json", "status": "COMPLETED", "produced": True,
                      "sha256": ns.sha_file(f"{ws}/review_{n}.json")}
    json.dump({"context": meta["draft_sha256"], "members": members},
              open(f"{ws}/reviews_round.json", "w"))
    seen = []
    for _ in range(3):
        d = last_line(ns.cmd_triage, "2")
        seen.append((d["decision"], d["repairs_done"]))
    check("a repeated triage neither spends a round nor flips to BLOCK", seen, [("REPAIR", 0)] * 3)
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- the graph's wiring
def controls_wiring():
    print("wiring — the graph binds its roles, and keeps its own judgements")
    y = open(GRAPH, encoding="utf-8").read()
    block = y.split("- name: record_block", 1)[1].split("- name: record_hold", 1)[0]
    check("record_block sends an execute record", "'execute'" in block, True)
    check("record_block sends the triage reason", "triage.output.reason" in block, True)
    check("record_hold still sends none (a real HOLD)",
          "'execute'" in y.split("- name: record_hold", 1)[1].split("routes:", 1)[0], False)
    check("the author and the reviewers are different principals",
          ("author=claude:novel-author" in y and "story=codex:novel-reviewer" in y), True)
    for role in ("architect", "author", "story", "history", "cold"):
        check(f"{role}'s call carries its principal", f"{role}_principal" in y, True)
    check("the reviews step names the platform's capability", "steps/tasks.py" in y, True)
    check("the triage step is told what is required", '"story,history"' in y, True)
    check("'what is required' is this workflow's word",
          "required" in open(STEP, encoding="utf-8").read(), True)
    check("every step declares what a repeat does",
          "REPEATABLE" in open(STEP, encoding="utf-8").read(), True)


if __name__ == "__main__":
    controls_triage()
    controls_evidence()
    controls_repeat()
    controls_wiring()
    print(f"\nnovel controls: {len(PASS)} ok, {len(FAIL)} failed")
    for name, got, want in FAIL:
        print(f"  FAIL  {name}: got {got!r}, expected {want!r}")
    sys.exit(1 if FAIL else 0)
