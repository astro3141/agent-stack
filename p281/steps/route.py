"""Conductor script step: collect normalized quota observations and choose a provider.

Emits the router decision flat for Conductor; the full evaluation is kept in the evidence dir.
"""
import json, os, subprocess, sys

run = os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")
d = f"/work/evidence/p281/route-{run}"
os.makedirs(d, exist_ok=True)
here = "/work/p281"
subprocess.run([sys.executable, f"{here}/collect_obs.py", f"{d}/obs"], check=True, capture_output=True)
r = json.loads(subprocess.run([sys.executable, f"{here}/router.py", os.environ.get("ROUTING_POLICY", f"{here}/routing-policy.json"), f"{d}/obs"],
                              check=True, capture_output=True, text=True).stdout)
json.dump(r, open(f"{d}/decision.json", "w"), indent=1)
print(json.dumps({"decision": r["decision"], "provider": r["provider"], "reason": r["reason"],
                  "evaluated": json.dumps(r["evaluated"]), "evidence_dir": d}))
