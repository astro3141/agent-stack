"""Arch-cycle port — the harness's own lanes on this stack, one frozen packet.

This is the PORT, not the shape trial (TRIAL-B2). The difference is three things:

  1. the packet is the harness's real ResearchPacket (via packet_bridge.py), not invented numbers;
  2. the lanes carry the harness's own contracts — grounding (refs ⊆ packet), universe membership,
     the frozen constitution's weight/gross bounds — checked identically by validate();
  3. the deterministic financial math is a SCRIPT step (vendored valuation), never a prompt (§12).

Lanes in this cycle share ONE packet: B (deterministic replica, 0 calls) + E (one call) +
G (one call, memory-shaped) + F (a desk: analyst → risk → PM) + H (forecast → deterministic
score → decide). Lane I is a SEPARATE-packet, own-ledger follow-on — its per-symbol long-horizon
packet and thesis lifecycle do not share this cycle's ResearchPacket (see PORT-trading.md).

  arch_port.py plan <lane:provider:login:route> ...   write the lane plan for this cycle
"""

import json
import os
import sys

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import settings  # same workspace contract as every other step

RUN = os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")
WS = f"{settings.runtime()['paths']['workspace_root']}/{RUN}"
P = "/work/packages/trading-port/prompts"
PY = os.environ.get("POC_PY", "/opt/venv/bin/python")


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False))


# each lane's steps — the harness shape, pointed at the PORT prompts and
# the vendored deterministic core (H's middle step)
SHAPES = {
    "E": [("model", f"{P}/port-e.md", "lane_E.json")],
    "G": [("model", f"{P}/port-g.md", "lane_G.json")],
    "F": [("model", f"{P}/port-f1-analyst.md", "f_analysis.json"),
          ("model", f"{P}/port-f2-risk.md", "f_risk.json"),
          ("model", f"{P}/port-f3-pm.md", "lane_F.json")],
    "H": [("model", f"{P}/port-h1-forecast.md", "h_forecast.json"),
          ("script", "score-forecast", "h_score.json"),
          ("model", f"{P}/port-h2-decide.md", "lane_H.json")],
}


def cmd_plan(specs):
    members = []
    for spec in specs:
        lane, provider, login, route = spec.split(":")
        steps = []
        for i, (kind, what, expected) in enumerate(SHAPES[lane], 1):
            if kind == "model":
                steps.append({"kind": "model", "name": f"{lane}{i}",
                              "provider": provider, "login": login,
                              "route": route, "prompt": what,
                              "expected": expected})
            else:
                steps.append({"kind": "script",
                              "name": f"{lane}{i}-{what}",
                              "expected": expected,
                              "argv": [PY, "/work/p281/steps/trade_stage.py",
                                       what]})
        members.append({"label": lane, "steps": steps})
    path = f"{WS}/lanes_plan.json"
    json.dump({"members": members}, open(path, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    out(status="OK", plan=path, members=len(members),
        model_steps=sum(1 for m in members for s in m["steps"]
                        if s["kind"] == "model"),
        script_steps=sum(1 for m in members for s in m["steps"]
                         if s["kind"] == "script"))


def cmd_evaluate():
    """Validate every lane IDENTICALLY against the bridged packet
    (grounding + universe + weight/gross bounds — trade_stage.validate),
    and score against a HELD-BACK returns file if one is present.

    Scoring here is DIAGNOSTIC/pilot-grade only: the authoritative
    return, cost and ledger stay in the harness (PORT-trading.md). Live
    cycles carry no held-back file, so this reports validation + the
    decisions, and the harness scores them in its own ledger."""
    _here = os.path.dirname(os.path.abspath(__file__))
    sys.path[:0] = [_here, os.path.dirname(_here)]  # steps/ and p281/
    from trade_stage import validate  # identical checks
    packet = json.load(open(f"{WS}/packet.json", encoding="utf-8"))
    held = None
    hp = f"{WS}/held_back_returns.json"
    if os.path.exists(hp):
        held = json.load(open(hp, encoding="utf-8"))  # {sym: ret, "BENCH": r}
    plan = json.load(open(f"{WS}/lanes_plan.json", encoding="utf-8"))
    planned = [m["label"] for m in plan["members"]] + ["B"]
    rows = []
    seen = set()
    for name in sorted(os.listdir(WS)):
        if not (name.startswith("lane_") and name.endswith(".json")):
            continue
        lane = name[5:-5]
        seen.add(lane)
        try:
            doc = json.load(open(f"{WS}/{name}", encoding="utf-8"))
            errs, gross = validate(lane, doc, packet)
            pos = len(doc.get("targets") or []) if isinstance(doc, dict) else 0
            if errs:
                rows.append({"lane": lane, "status": "INVALID",
                             "why": "; ".join(errs)[:200],
                             "gross": round(gross, 3), "positions": pos})
                continue
            row = {"lane": lane, "status": "VALID", "gross": round(gross, 3),
                   "positions": pos,
                   "model_calls": int(doc.get("model_calls", 0))}
            if held:
                ret = sum(float(t["weight"]) * held.get(t["symbol"], 0.0)
                          for t in doc["targets"])
                row["ret"] = round(ret, 5)
                row["excess"] = round(ret - held.get("BENCH", 0.0) * gross, 5)
            rows.append(row)
        except Exception as e:
            rows.append({"lane": lane, "status": "INVALID",
                         "why": f"{type(e).__name__}: {e}"[:200]})
    for lane in planned:
        if lane not in seen:
            rows.append({"lane": lane, "status": "MISSING",
                         "why": "planned but produced nothing"})
    report = f"{WS}/port_report.json"
    # "items" is the platform's evidence-index contract (steps/record.py
    # counts and stores exactly that key) — "rows" here would be stored
    # but counted as 0, which reads later as "nothing kept"
    json.dump({"items": rows, "scored": bool(held)},
              open(report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    valid = [r for r in rows if r["status"] == "VALID"]
    best = max(valid, key=lambda r: r.get("excess", r.get("ret", -1e9))) \
        if (valid and held) else None
    out(status="OK", lanes=len(rows), valid=len(valid),
        invalid=sum(1 for r in rows if r["status"] != "VALID"),
        scored="yes" if held else "no (harness scores live)",
        best_lane=best["lane"] if best else "",
        report=report)


if __name__ == "__main__":
    {"plan": lambda: cmd_plan(sys.argv[2:]),
     "evaluate": cmd_evaluate}[sys.argv[1]]()

