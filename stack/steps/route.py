"""Conductor script step: collect normalized quota observations and choose a provider.

Emits the router decision flat for Conductor; the full evaluation is kept in the evidence dir.
The asking itself — policy, collection, router — is stack/admission.py, the one door every
caller of the router goes through.
"""

# What a repeat of this step does (OPERATIONS.md §17): "yes" — the same result;
# "guarded" — it recognises the repeat; "no" — it does the work again.
REPEATABLE = "yes"   # re-observes quota and decides again; writes its own evidence directory
import json, os, sys
sys.path.insert(0, "/work/stack")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import step
run = step.run_id()
d = step.evidence_dir(f"route-{run}")      # <evidence_root>/route-<run>, where every reader looks
os.makedirs(d, exist_ok=True)
import admission
# The profile's routing policy, generated from config/profiles/<name>.yaml. ROUTING_POLICY
# (a raw policy file) still overrides it — used by the fault-injection and limit tests.
prof_name = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "research-default"
raw = json.load(open(os.environ["ROUTING_POLICY"])) if os.environ.get("ROUTING_POLICY") else None
try:
    r = admission.evaluate(prof_name, policy=raw, evidence_dir=d)
except LookupError as e:                       # no such profile: a HOLD that says so, not a crash
    print(json.dumps({"decision": "HOLD", "provider": "", "reason": str(e),
                      "evaluated": "[]", "model_route": "", "login": "", "profile": prof_name, "evidence_dir": d}))
    sys.exit(0)
pol = r["policy"]
routes = pol.get("model_route", {})
print(json.dumps({"decision": r["decision"], "provider": r["provider"], "reason": r["reason"],
                  "model_route": routes.get(r["provider"], "preloop_gateway") if r["provider"] else "",
                  "login": (pol.get("login") or {}).get(r["provider"], r["provider"]) if r["provider"] else "",
                  "profile": prof_name,
                  "evaluated": json.dumps(r["evaluated"]), "evidence_dir": d}))
