"""#281 router controls: inject faults into normalized observations, check the decision.

usage: router_controls.py <live-obs-dir>
Starts from the live observations, applies one mutation per case, runs router.py on the result
and compares with the expected decision. No model, no network — deterministic.
"""
import copy, json, os, subprocess, sys, tempfile
from datetime import datetime, timedelta, timezone

live = sys.argv[1]
base = {p[:-5]: json.load(open(os.path.join(live, p))) for p in os.listdir(live) if p.endswith(".json")}
now = datetime.now(timezone.utc)
iso = lambda dt: dt.isoformat()


def fresh(o, age_s=60):
    o["observed_at"] = iso(now - timedelta(seconds=age_s)); return o


def case(name, mutate, expect_decision, expect_provider=""):
    obs = copy.deepcopy(base)
    mutate(obs)
    with tempfile.TemporaryDirectory() as d:
        for k, v in obs.items():
            if v is not None:
                json.dump(v, open(os.path.join(d, f"{k}.json"), "w"))
        r = json.loads(subprocess.run(
            [sys.executable, os.path.join(os.path.dirname(__file__), "router.py"),
             os.path.join(os.path.dirname(__file__), "routing-policy.json"), d],
            capture_output=True, text=True, env={**os.environ, "ROUTER_NOW": iso(now)}).stdout)
    ok = r["decision"] == expect_decision and r["provider"] == expect_provider
    why = {e["provider"]: e["why"] for e in r["evaluated"]}
    return {"case": name, "expect": f"{expect_decision} {expect_provider}".strip(),
            "got": f"{r['decision']} {r['provider']}".strip(), "ok": ok, "why": why}


def set_(path, value):
    def f(obs):
        o = obs
        for k in path[:-1]:
            o = o[k]
        o[path[-1]] = value
    return f


def seq(*fs):
    def f(obs):
        for g in fs:
            g(obs)
    return f


cases = [
    case("live observations as collected", lambda o: None, "ROUTE", "codex"),
    case("claude made fresh (60 s) → preferred provider wins",
         lambda o: fresh(o["claude"]), "ROUTE", "claude"),
    case("claude fresh but session 85% → falls back to codex",
         seq(lambda o: fresh(o["claude"]), set_(["claude", "windows", "session", "used_percent"], 85.0)),
         "ROUTE", "codex"),
    case("codex ACCOUNT MISMATCH (observer logged into another account)",
         set_(["codex", "observed_account"], "email:0000000000000000"), "HOLD"),
    case("codex account mismatch while claude is fresh → claude, never the mismatched one",
         seq(lambda o: fresh(o["claude"]), set_(["codex", "observed_account"], "email:0000000000000000")),
         "ROUTE", "claude"),
    case("codex executing account unknown (no auth in the execution layer)",
         set_(["codex", "executing_account"], None), "HOLD"),
    case("codex STALE (observed 2 h ago, numbers look fine)",
         lambda o: fresh(o["codex"], 7200), "HOLD"),
    case("codex observed_at in the future (clock skew / forged)",
         lambda o: fresh(o["codex"], -3600), "HOLD"),
    case("codex required weekly window missing",
         lambda o: o["codex"]["windows"].pop("weekly", None), "HOLD"),
    case("codex weekly 95% (exhausted)",
         set_(["codex", "windows", "weekly", "used_percent"], 95), "HOLD"),
    case("codex observation file absent (observer down)",
         set_(["codex"], None), "HOLD"),
    case("both fresh, both exhausted",
         seq(lambda o: fresh(o["claude"]), set_(["claude", "windows", "weekly", "used_percent"], 99.0),
             set_(["codex", "windows", "weekly", "used_percent"], 99)), "HOLD"),
]

for c in cases:
    print(json.dumps(c))
print(json.dumps({"passed": sum(c["ok"] for c in cases), "total": len(cases)}))
