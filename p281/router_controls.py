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
    # preference order: claude, codex, grok
    case("live observations as collected", lambda o: None, "ROUTE", "codex"),
    case("claude made fresh (60 s) → preferred provider wins",
         lambda o: fresh(o["claude"]), "ROUTE", "claude"),
    case("claude fresh but session 85% → next in order (codex)",
         seq(lambda o: fresh(o["claude"]), set_(["claude", "windows", "session", "used_percent"], 85.0)),
         "ROUTE", "codex"),
    case("codex ACCOUNT MISMATCH → never codex; falls to grok",
         set_(["codex", "observed_account"], "email:0000000000000000"), "ROUTE", "grok"),
    case("codex executing account unknown → grok",
         set_(["codex", "executing_account"], None), "ROUTE", "grok"),
    case("codex STALE (2 h, numbers fine) → grok",
         lambda o: fresh(o["codex"], 7200), "ROUTE", "grok"),
    case("codex observed_at 1 h in the future → grok",
         lambda o: fresh(o["codex"], -3600), "ROUTE", "grok"),
    case("codex required weekly window missing → grok",
         lambda o: o["codex"]["windows"].pop("weekly", None), "ROUTE", "grok"),
    case("codex weekly 95% (exhausted) → grok",
         set_(["codex", "windows", "weekly", "used_percent"], 95), "ROUTE", "grok"),
    case("codex observer down (no file) → grok",
         set_(["codex"], None), "ROUTE", "grok"),
    case("grok ACCOUNT MISMATCH and codex exhausted → HOLD",
         seq(set_(["grok", "observed_account"], "email:0000000000000000"),
             set_(["codex", "windows", "weekly", "used_percent"], 95)), "HOLD"),
    case("grok stale and codex stale → HOLD",
         seq(lambda o: fresh(o["grok"], 7200), lambda o: fresh(o["codex"], 7200)), "HOLD"),
    case("all three fresh, all exhausted → HOLD",
         seq(lambda o: fresh(o["claude"]), set_(["claude", "windows", "weekly", "used_percent"], 99.0),
             set_(["codex", "windows", "weekly", "used_percent"], 99),
             set_(["grok", "windows", "weekly", "used_percent"], 99)), "HOLD"),
    case("codex and grok exhausted, claude fresh → claude",
         seq(lambda o: fresh(o["claude"]), set_(["codex", "windows", "weekly", "used_percent"], 99),
             set_(["grok", "windows", "weekly", "used_percent"], 99)), "ROUTE", "claude"),
]

for c in cases:
    print(json.dumps(c))
print(json.dumps({"passed": sum(c["ok"] for c in cases), "total": len(cases)}))
