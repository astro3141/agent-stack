"""One unattended cycle — the implementation the CLI, the scheduler and the panel all call.

usage: cycle.py <workflow> [profile] [key=value ...] [--allow-unrecorded] [--retain-days N] [--retain-keep M]

`scripts/cycle.sh` is a thin wrapper around this, and the ops API calls it too. There is one
implementation because the rules are the interesting part and two copies of them would drift:

  * **one at a time.** The lock is a directory next to the operations record, so every entry point
    sees the same one. A cycle that arrives while another is running is *skipped*, not queued —
    two would share logins and workspaces. The lock is never broken here: a cycle that cannot tell
    whether the other is alive may not decide that it is dead. It records how long it has been
    held instead, and `ops_health.py` shows it.
  * **it refuses rather than pretends.** `run_workflow.py` checks the capabilities and exits 3
    when one a run needs is missing; that refusal is recorded with its reason.
  * **one line per cycle** in evidence/ops/cycles.jsonl — and per skip, and per refusal, which are
    the two things an unattended schedule hides best.
  * **retention only when asked**, and then it is the same cleanup as by hand (whole runs, live
    runs and pending approvals protected).
"""
import json, os, subprocess, sys, time

sys.path.insert(0, "/work/stack")

PY = sys.executable
STACK = os.path.dirname(os.path.abspath(__file__))
OPS_DIR = "/work/evidence/ops"
RECORD = f"{OPS_DIR}/cycles.jsonl"
LOCK = f"{OPS_DIR}/.cycle.lock.d"


def record(row):
    os.makedirs(OPS_DIR, exist_ok=True)
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **row}
    with open(RECORD, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def lock_held():
    """What the lock says about itself, or None when it is free."""
    if not os.path.isdir(LOCK):
        return None
    try:
        since = open(f"{LOCK}/started", encoding="utf-8").read().strip()
        age = round(time.time() - float(open(f"{LOCK}/started_epoch", encoding="utf-8").read()))
    except Exception:
        since, age = "unknown", None
    return {"since": since, "age_s": age}


def run(workflow, profile="research-default", allow_unrecorded=False,
        retain_days=None, retain_keep=None, by="cli", inputs=None):
    os.makedirs(OPS_DIR, exist_ok=True)
    try:
        os.mkdir(LOCK)
    except FileExistsError:
        held = lock_held() or {}
        return record({"workflow": workflow, "by": by, "skipped": "busy",
                       "lock_since": held.get("since"), "lock_age_s": held.get("age_s")})
    try:
        open(f"{LOCK}/started", "w").write(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        open(f"{LOCK}/started_epoch", "w").write(str(time.time()))
        open(f"{LOCK}/pid", "w").write(str(os.getpid()))

        ui = "cyc-" + time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        argv = [PY, os.path.join(STACK, "run_workflow.py"), "start", ui, workflow, profile]
        # the workflow's inputs, as the panel and the CLI pass them; the runner validates them.
        # Until this line a scheduled cycle could pass none, and trading read `day=` inside a
        # step instead (PACKAGE-MATRIX §4).
        argv += [f"{k}={v}" for k, v in sorted((inputs or {}).items())]
        if allow_unrecorded:
            argv.append("--allow-unrecorded")
        t0 = time.time()
        p = subprocess.run(argv, capture_output=True, text=True, cwd="/work")
        seconds = round(time.time() - t0)
        # 3: the stack cannot run this now (a capability missing), and said why. 2: the start was
        # invalid — no such workflow, a bad profile, a bad input, a reused id — and the runner said
        # which. Both are refusals. Until §86 only 3 was: an rc-2 start fell through to the
        # outcome reader, which found no run and wrote `{"state": null}` as a cycle that ran,
        # exit 0 — a scheduler that misnamed its workflow saw success forever.
        if p.returncode in (2, 3):
            try:
                why = json.loads(p.stdout.strip().splitlines()[-1])
            except Exception:
                why = {"error": (p.stderr or p.stdout)[-200:]}
            return record({"workflow": workflow, "by": by, "ui": ui, "refused": why,
                           "rc": p.returncode})
        if p.returncode != 0:                     # the runner itself failed; say so, not "ran"
            return record({"workflow": workflow, "by": by, "ui": ui, "seconds": seconds,
                           "failed": {"rc": p.returncode,
                                      "error": (p.stderr or p.stdout)[-300:]}})

        out = subprocess.run([PY, os.path.join(STACK, "soak_outcome.py"), ui],
                             capture_output=True, text=True, cwd="/work").stdout
        try:
            outcome = json.loads(out.strip().splitlines()[-1])
        except Exception:
            outcome = {"state": "unknown"}
        row = record({"workflow": workflow, "by": by, "ui": ui, "seconds": seconds,
                      "outcome": outcome})

        if retain_days or retain_keep:
            args = [PY, os.path.join(STACK, "cleanup.py"), "--apply", "--json"]
            if retain_days:
                args += ["--days", str(retain_days)]
            if retain_keep:
                args += ["--keep", str(retain_keep)]
            r = subprocess.run(args, capture_output=True, text=True, cwd="/work")
            try:
                removed = json.loads(r.stdout.strip().splitlines()[-1])
            except Exception:
                removed = {"error": (r.stderr or r.stdout)[-200:]}
            record({"by": by, "retention": removed})
            row["retention"] = removed
        return row
    finally:
        for f in ("started", "started_epoch", "pid"):
            try:
                os.remove(f"{LOCK}/{f}")
            except OSError:
                pass
        try:
            os.rmdir(LOCK)
        except OSError:
            pass


OPTS = ("--retain-days", "--retain-keep", "--by")


def parse_args(argv):
    """What a caller asked for. Positionals are what is left once every option *and its value* is
    taken out: reading the first bare word as the profile made `--by scheduler` start a run with
    the profile "scheduler", which the router then held on — and the workflow's hold message
    assumed a step that never ran."""
    def opt(name):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None
    words = [x for i, x in enumerate(argv)
             if not x.startswith("--") and (i == 0 or argv[i - 1] not in OPTS)]
    inputs = dict(w.split("=", 1) for w in words if "=" in w)      # key=value → a workflow input
    bare = [w for w in words if "=" not in w]
    # No default workflow: the one this had (trading-b) left with its package, and a scheduler
    # that names nothing is asking for nothing (§86).
    return {"workflow": bare[0] if bare else None,
            "profile": bare[1] if len(bare) > 1 else "research-default",
            "allow_unrecorded": "--allow-unrecorded" in argv,
            "retain_days": opt("--retain-days"), "retain_keep": opt("--retain-keep"),
            "by": opt("--by") or "cli", "inputs": inputs}


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    if not args["workflow"]:
        print(json.dumps({"error": "no workflow named",
                          "usage": __doc__.strip().splitlines()[2].strip()}))
        raise SystemExit(2)
    row = run(**args)
    print(json.dumps(row, ensure_ascii=False))
    # exit codes are for a scheduler: 0 = a cycle ran or one was already running, 3 = refused,
    # 1 = the runner itself failed (nothing to read back)
    raise SystemExit(3 if "refused" in row else 1 if "failed" in row else 0)
