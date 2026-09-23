"""One unattended cycle — the implementation the CLI, the scheduler and the panel all call.

usage: cycle.py <workflow> [profile] [--allow-unrecorded] [--retain-days N] [--retain-keep M]

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

sys.path.insert(0, "/work/p281")

PY = "/opt/venv/bin/python"
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
        retain_days=None, retain_keep=None, by="cli"):
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
        argv = [PY, "/work/p281/run_workflow.py", "start", ui, workflow, profile]
        if allow_unrecorded:
            argv.append("--allow-unrecorded")
        t0 = time.time()
        p = subprocess.run(argv, capture_output=True, text=True, cwd="/work")
        seconds = round(time.time() - t0)
        if p.returncode == 3:                     # the stack cannot run this now, and said why
            try:
                why = json.loads(p.stdout.strip().splitlines()[-1])
            except Exception:
                why = {"error": (p.stderr or p.stdout)[-200:]}
            return record({"workflow": workflow, "by": by, "ui": ui, "refused": why})

        out = subprocess.run([PY, "/work/p281/soak_outcome.py", ui],
                             capture_output=True, text=True, cwd="/work").stdout
        try:
            outcome = json.loads(out.strip().splitlines()[-1])
        except Exception:
            outcome = {"state": "unknown"}
        row = record({"workflow": workflow, "by": by, "ui": ui, "seconds": seconds,
                      "outcome": outcome})

        if retain_days or retain_keep:
            args = [PY, "/work/p281/cleanup.py", "--apply", "--json"]
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
    bare = [x for i, x in enumerate(argv)
            if not x.startswith("--") and (i == 0 or argv[i - 1] not in OPTS)]
    return {"workflow": bare[0] if bare else "trading-b",
            "profile": bare[1] if len(bare) > 1 else "research-default",
            "allow_unrecorded": "--allow-unrecorded" in argv,
            "retain_days": opt("--retain-days"), "retain_keep": opt("--retain-keep"),
            "by": opt("--by") or "cli"}


if __name__ == "__main__":
    row = run(**parse_args(sys.argv[1:]))
    print(json.dumps(row, ensure_ascii=False))
    # exit codes are for a scheduler: 0 = a cycle ran or one was already running, 3 = refused
    raise SystemExit(3 if "refused" in row else 0)
