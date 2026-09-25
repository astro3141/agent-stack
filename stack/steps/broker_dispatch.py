"""Run one model step through the broker — the same contract as agent_task.py, different door.

usage: broker_dispatch.py <provider> <model_route> <label> <prompt-file> <expected-file>
       [<profile> [<login> [<principal>]]]

The argv is agent_task.py's on purpose: the fan-out (steps/tasks.py) and a chain
(steps/task_chain.py) swap the entrypoint and change nothing else, so a receipt, a retry and the
recorder read a brokered member exactly like a local one.

Which members come here is a fact about the *role*: a principal that declares `egress_profile:`
(§53) runs where that declaration says, and the broker — not this step, not the workflow — maps the
role, mints the job token, and holds the credential (§54). This step reads the prompt, asks, and
reports the result as its last line. It carries no secret at any point: what travels is the prompt
and the role's name.

What a repeat of this step does (OPERATIONS §17): "no" — a model call, dispatched.
"""
REPEATABLE = "no"
import json
import os
import sys
import urllib.error
import urllib.request

BROKER = os.environ.get("AGENTSTACK_BROKER_URL", "http://cadp278-broker:8791")

provider, model_route, label, prompt_file, expected = sys.argv[1:6]
prof_name = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] else "research-default"
login = sys.argv[7] if len(sys.argv) > 7 and sys.argv[7] else provider
principal = sys.argv[8] if len(sys.argv) > 8 and sys.argv[8] else ""
run = os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")

try:
    prompt = open(prompt_file, encoding="utf-8").read()
except OSError as e:
    print(json.dumps({"status": "FAILED", "produced": False,
                      "failure": f"prompt unreadable: {type(e).__name__}"}))
    raise SystemExit(0)

# The execution profile owns the call's time limit, brokered or not: a local step reads
# timeout_ms from the same profile (agent_task.py), and a fixed 900 s here cut a call the
# profile allowed an hour for — the runner killed it mid-work with nothing produced
# (devflow's research step, measured at 25–33 minutes under long-task's 3600 s).
sys.path.insert(0, "/work/stack")
import settings  # noqa: E402
timeout_s = int(((settings.profile(prof_name) or {}).get("execution")
                 or {}).get("timeout_ms", 900000)) // 1000

req = {"role": principal, "provider": provider, "model_route": model_route or "direct",
       "label": label, "prompt": prompt, "expected": expected,
       "profile_name": prof_name, "login": login, "run_id": run,
       "timeout_s": timeout_s}
try:
    r = urllib.request.Request(BROKER + "/dispatch", data=json.dumps(req).encode(),
                               headers={"content-type": "application/json"})
    # the broker waits timeout_s + 30 on the runner; wait past that, so the timeout that speaks
    # is the runner's ("TIMED_OUT"), not a socket error here
    with urllib.request.urlopen(r, timeout=timeout_s + 60) as x:
        out = json.loads(x.read())
except urllib.error.HTTPError as e:
    try:
        why = json.loads(e.read()).get("error", "")
    except Exception:
        why = f"HTTP {e.code}"
    print(json.dumps({"status": "DENIED" if e.code == 403 else "FAILED", "produced": False,
                      "principal": principal, "provider": provider,
                      "failure": f"the broker refused this dispatch: {why}"},
                     ensure_ascii=False))
    raise SystemExit(0)
except Exception as e:
    print(json.dumps({"status": "FAILED", "produced": False, "principal": principal,
                      "provider": provider,
                      "failure": f"the broker did not answer: {type(e).__name__}"}))
    raise SystemExit(0)

res = out.get("result") or {"status": "FAILED",
                            "failure": out.get("error", "no result from the runner")}
# where it ran is part of the record: the receipt should say this member was brokered, and where
res["dispatched"] = out.get("dispatched") or {"role": principal}
print(json.dumps(res, ensure_ascii=False))
