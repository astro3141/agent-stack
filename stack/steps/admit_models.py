"""Conductor script step: is every model this round needs usable right now?

usage: admit_models.py <profile> <provider,provider,…>

The router answers a one-of question — *which* provider should this step take — and it answers it
about the candidates the profile names. A round that needs two model families to both complete has
no way to ask that with `route.py`: a profile listing one provider reports on one provider, and a
workflow routing on it learns nothing about the other. Measured on the case that found this: a
review round needing claude **and** codex checked its limits through a claude-only profile, held the
whole round on claude's 87%, and never asked about codex at all (OPERATIONS §61).

So this asks the other question, with the same machinery: the profile's routing policy with its
candidate list replaced by the providers named here, evaluated by `router.py` against fresh
observations. Every provider gets a verdict and a reason.

What it does NOT do is decide. It reports:

    {"all_eligible": false, "eligible": ["codex"], "missing": ["claude"],
     "reason": "claude: exhausted: session 91% >= 80%", "evaluated": "[…]"}

Whether a round holds, runs short, or runs anyway is the workflow's — a platform that decided here
would be deciding what a round *is* (CONTRACT.md). A missing provider is named with the router's own
words, so a held round can say why in the sentence a person reads.

What a repeat of this step does (OPERATIONS.md §17): "yes" — it re-observes and answers again.
"""
REPEATABLE = "yes"
import json
import os
import subprocess
import sys

sys.path.insert(0, "/work/stack")
import settings

HERE = "/work/stack"
run = os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")
prof_name = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "research-default"
wanted = [p.strip() for p in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if p.strip()]

d = f"/work/evidence/p281/admit-{run}"
os.makedirs(d, exist_ok=True)


def out(**kw):
    print(json.dumps(kw, ensure_ascii=False))
    raise SystemExit(0)


prof = settings.profile(prof_name)
if prof is None:
    out(all_eligible=False, eligible=[], missing=wanted, evaluated="[]",
        reason=f"unknown profile {prof_name!r} (run cfg.py generate)", evidence_dir=d)
if not wanted:
    out(all_eligible=False, eligible=[], missing=[], evaluated="[]",
        reason="no providers named: admit_models.py <profile> <provider,provider,…>",
        evidence_dir=d)

pol = dict(prof["routing"])
# the profile's own thresholds, windows and logins — only *who* is asked about changes. A provider
# the profile has no route or login for is asked about as the profile would have to run it.
pol["candidates"] = wanted
policy_path = f"{d}/policy.json"
json.dump(pol, open(policy_path, "w"), indent=1)

routes = pol.get("model_route") or {}
subprocess.run([sys.executable, f"{HERE}/collect_obs.py", f"{d}/obs"], check=False,
               capture_output=True,
               env={**os.environ, "AGENTSTACK_MODEL_ROUTES": json.dumps(routes),
                    "AGENTSTACK_LOGINS": json.dumps(pol.get("login") or {})})
r = subprocess.run([sys.executable, f"{HERE}/router.py", policy_path, f"{d}/obs"],
                   capture_output=True, text=True)
try:
    decision = json.loads(r.stdout)
except ValueError:
    out(all_eligible=False, eligible=[], missing=wanted, evaluated="[]",
        reason=f"the router did not answer ({(r.stderr or r.stdout)[-160:]})", evidence_dir=d)

ev = decision.get("evaluated") or []
verdict = {e["provider"]: e for e in ev if isinstance(e, dict) and e.get("provider")}
eligible = [p for p in wanted if (verdict.get(p) or {}).get("eligible")]
missing = [p for p in wanted if p not in eligible]
why = "; ".join(f"{p}: {(verdict.get(p) or {}).get('why', 'not evaluated')}" for p in missing)
json.dump({"wanted": wanted, "decision": decision}, open(f"{d}/admission.json", "w"), indent=1)
out(all_eligible=not missing, eligible=eligible, missing=missing,
    reason=why or "every named provider is within limits",
    evaluated=json.dumps(ev, ensure_ascii=False), profile=prof_name, evidence_dir=d)
