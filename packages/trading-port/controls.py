"""Port controls — drive the port's real functions with fixture inputs, no model call.

Same idea as trial_controls.py: pin the contracts that make the port faithful, using the
committed pilot fixture. Needs no provider login and no network — safe to run in the current
environment (owner 2026-09-24: the workflow itself must NOT run here; these checks may).

  python3 p281/port_controls.py
"""

import json
import os
import subprocess
import sys
import tempfile

# The package is its own root now: its steps and fixtures travel with it, and the platform is
# addressed where the platform is (OPERATIONS §27). Before the move these were all under p281/.
PKG = os.path.dirname(os.path.abspath(__file__))
ROOT = "/work"
STEPS = os.path.join(PKG, "steps")
PLATFORM_STEPS = os.path.join(ROOT, "p281", "steps")
FIX = os.path.join(PKG, "fixtures")
PILOT = os.path.join(FIX, "harness-arch-packet-pilot.json")
PY = sys.executable
n_ok = n_fail = 0


def ck(name, cond, detail=""):
    global n_ok, n_fail
    if cond:
        n_ok += 1
        print(f"  ok    {name}")
    else:
        n_fail += 1
        print(f"  FAIL  {name}  {detail}")


def main():
    # every step resolves its workspace via settings (workspace_root/RUN)
    # — the container has /ws; on the host we point P281_ROOT at a temp
    # tree with a runtime.json whose workspace_root is writable, so these
    # run exactly as in the container. PYTHONPATH lets `import settings`
    # and trade_stage resolve.
    proot = tempfile.mkdtemp(prefix="port-root-")
    wsroot = tempfile.mkdtemp(prefix="port-ws-")
    gen = os.path.join(proot, "config", "generated")
    os.makedirs(gen, exist_ok=True)
    rt = {"preloop": {}, "mlflow": {}, "egress": {"proxy": "", "no_proxy": []},
          "paths": {"workspace_root": wsroot, "evidence_root": proot,
                    "observations": proot, "logins_root": proot}}
    json.dump(rt, open(os.path.join(gen, "runtime.json"), "w"))
    run_id = "ctl"
    ws = os.path.join(wsroot, run_id)
    os.makedirs(ws, exist_ok=True)
    ppath = os.pathsep.join([STEPS, os.path.join(ROOT, "p281"),
                             os.environ.get("PYTHONPATH", "")])
    env = dict(os.environ, P281_ROOT=proot, CONDUCTOR_SELF_RUN_ID=run_id,
               PYTHONPATH=ppath)

    # 1. bridge produces a stack packet from the pilot harness packet
    r = subprocess.run([PY, f"{STEPS}/packet_bridge.py", "pilot", "--from", PILOT],
                       capture_output=True, text=True, env=env)
    try:
        b = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        b = {}
    ck("bridge OK on pilot", b.get("status") == "OK", r.stdout + r.stderr)
    pkt = json.load(open(f"{ws}/packet.json")) if os.path.exists(f"{ws}/packet.json") else {}

    # 2. PIT preserved + provenance carried, held-back NOT in the lanes' packet
    ck("harness hash carried", bool(b.get("harness_packet_hash")))
    ck("provenance in packet", bool(pkt.get("source", {}).get("harness_packet_hash")))
    ck("held-back not in lanes' packet",
       "next_session" not in pkt and "held_back_returns" not in pkt)
    ck("held-back placed separately (pilot)",
       os.path.exists(f"{ws}/held_back_returns.json"))

    # 3. constraints mirror the frozen constitution (gross .50 / name .05 / min .01)
    c = pkt.get("constraints", {})
    ck("constitution constraints", c.get("max_gross") == 0.50
       and c.get("max_weight_per_symbol") == 0.05 and c.get("min_weight") == 0.01,
       str(c))

    # 4. live refuses a missing hand-in (no silent fetch)
    r2 = subprocess.run([PY, f"{STEPS}/packet_bridge.py", "live"],
                        capture_output=True, text=True, env=env)
    try:
        b2 = json.loads(r2.stdout.strip().splitlines()[-1])
    except Exception:
        b2 = {}
    ck("live refuses no hand-in", b2.get("status") == "ERROR", r2.stdout)

    # 5. baseline B is deterministic and within bounds, 0 model calls
    # trade_stage.py is the built-in trading workflow's step, not this package's: the dependency
    # the manifest names, addressed where it actually lives
    subprocess.run([PY, f"{PLATFORM_STEPS}/trade_stage.py", "baseline", "B"],
                   capture_output=True, text=True, env=env)
    lb = json.load(open(f"{ws}/lane_B.json")) if os.path.exists(f"{ws}/lane_B.json") else {}
    gross = sum(t["weight"] for t in lb.get("targets", []))
    ck("baseline 0 model calls", lb.get("model_calls") == 0)
    ck("baseline within gross", 0 < gross <= c.get("max_gross", 0.5), f"gross={gross}")
    ck("baseline names in universe",
       all(any(u["symbol"] == t["symbol"] for u in pkt["universe"])
           for t in lb.get("targets", [])))

    # 6. plan builder emits the arch shapes (E/G 1 step, F 3, H 3 incl 1 script)
    r3 = subprocess.run([PY, f"{STEPS}/arch_port.py", "plan",
                         "E:grok:l:r", "G:claude:l:r", "F:codex:l:r", "H:claude:l:r"],
                        capture_output=True, text=True, env=env)
    try:
        p = json.loads(r3.stdout.strip().splitlines()[-1])
    except Exception:
        p = {}
    ck("plan 4 members", p.get("members") == 4, r3.stdout + r3.stderr)
    # E1 + G1 + F3 + H2(forecast,decide) = 7 model; H has 1 script (score)
    ck("plan model+script steps", p.get("model_steps") == 7 and p.get("script_steps") == 1,
       f"model={p.get('model_steps')} script={p.get('script_steps')}")

    # 7. evaluate validates identically + scores from the held-back file; grounding enforced
    json.dump({"lane": "E", "model_calls": 1, "refs": [],
               "targets": [{"symbol": pkt["universe"][0]["symbol"], "weight": 0.04}]},
              open(f"{ws}/lane_E.json", "w"))
    json.dump({"lane": "G", "model_calls": 1, "refs": [],
               "targets": [{"symbol": "NOTINUNIVERSE", "weight": 0.04}]},
              open(f"{ws}/lane_G.json", "w"))
    r4 = subprocess.run([PY, f"{STEPS}/arch_port.py", "evaluate"],
                        capture_output=True, text=True, env=env)
    try:
        e = json.loads(r4.stdout.strip().splitlines()[-1])
    except Exception:
        e = {}
    rep = json.load(open(f"{ws}/port_report.json")) if os.path.exists(f"{ws}/port_report.json") else {}
    rows = {x["lane"]: x for x in rep.get("rows", [])}
    ck("evaluate valid lane E", rows.get("E", {}).get("status") == "VALID", str(rows.get("E")))
    ck("evaluate rejects off-universe G", rows.get("G", {}).get("status") == "INVALID")
    ck("evaluate flags MISSING F/H",
       rows.get("F", {}).get("status") == "MISSING" and rows.get("H", {}).get("status") == "MISSING")
    ck("evaluate scored in pilot", e.get("scored", "").startswith("yes"))

    # 8. vendored valuation is the harness's pure math, importable, deterministic
    sys.path.insert(0, STEPS)
    try:
        from vendor.valuation import dcf_value_per_share, VALUATION_VERSION
        v1 = dcf_value_per_share(100.0, 0.05, 5, 0.10, 0.02, -50.0, 10.0)
        v2 = dcf_value_per_share(100.0, 0.05, 5, 0.10, 0.02, -50.0, 10.0)
        ck("vendored valuation deterministic", v1 == v2 and VALUATION_VERSION == "lh-valuation-v0.1")
    except Exception as ex:
        ck("vendored valuation deterministic", False, repr(ex))

    print(f"\n{n_ok}/{n_ok + n_fail} controls passed")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
