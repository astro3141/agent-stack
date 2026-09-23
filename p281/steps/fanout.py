"""Start several subprocesses together, time each one honestly, and remember what finished.

Used by the capability trials (steps/novel_reviews.py, steps/trade_lanes.py), which need real
concurrency because Conductor's `parallel` / `for_each` groups refuse script steps (v0.1.37) and
every routed model call here is a script step.

Two jobs, and they are separate on purpose:

1. **Measurement.** Each child is waited on in its own thread and stamps its own end time. The
   first version collected the children with a sequential loop and stamped the end when the loop
   reached each one, so a slow child stretched the others — measured, a 100 s + 1 s + 1 s fan-out
   reported an overlap of 3.00 where the truth was 1.02.

2. **Per-member resume.** Conductor's unit is the step, so it can only resume the whole group.
   A ledger beside the run's workspace records each member's own state, so a step that runs again
   after an interruption re-executes only the members that did not finish. That is the part
   Conductor cannot do for routed calls, and it is done here rather than claimed.

What "finished" means is deliberately narrow:

  * a member is reused only when its **fingerprint** matches — the command it would run plus the
    content of the inputs it was given — so a changed prompt, packet or draft re-runs it;
  * and only when the artifact it produced is still there with the same sha256;
  * a member left `running` by an interruption is never assumed complete: it runs again. There is
    no partial resume inside a provider call, and this does not pretend otherwise.
"""
import hashlib, json, os, subprocess, tempfile, threading, time


def _sha_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def fingerprint(job):
    """What must be identical for a finished member to be reused."""
    h = hashlib.sha256()
    h.update("\x00".join(job["argv"]).encode("utf-8"))
    for p in job.get("inputs") or []:
        h.update(f"|{os.path.basename(p)}:{_sha_file(p)}".encode("utf-8"))
    return h.hexdigest()


def _load(ledger):
    if not ledger or not os.path.isfile(ledger):
        return {}
    try:
        return json.load(open(ledger, encoding="utf-8"))
    except ValueError:
        return {}


def _save(ledger, data, lock):
    if not ledger:
        return
    with lock:
        os.makedirs(os.path.dirname(ledger), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(ledger))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, ledger)          # a crash never leaves half a ledger


def run_all(jobs, ledger=None, force=False):
    """jobs: [{"key", "argv", "inputs": [paths], "produces": path, **extra}] → (rows, wall_s)

    Rows carry the job's extras plus started_at / ended_at (offsets from the first start),
    stdout, stderr, returncode, reused, attempts.
    """
    t0 = time.time()
    state = _load(ledger)
    lock = threading.Lock()
    rows, to_run = [], []

    for job in jobs:
        row = dict(job)
        fp = fingerprint(job)
        prev = state.get(job["key"]) or {}
        art = job.get("produces")
        reusable = (
            not force
            and prev.get("state") == "done"
            and prev.get("fingerprint") == fp
            and (not art or (os.path.exists(art) and _sha_file(art) == prev.get("artifact_sha256")))
        )
        row.update({"fingerprint": fp, "attempts": int(prev.get("attempts", 0))})
        if reusable:
            row.update({"reused": True, "started_at": 0.0, "ended_at": 0.0,
                        "stdout": prev.get("stdout", ""), "stderr": "", "returncode": 0,
                        "previous_seconds": prev.get("seconds", 0)})
            rows.append(row)
            continue
        if prev.get("state") == "running":
            # an interrupted member: nothing here can resume a provider call halfway
            row["interrupted_before"] = True
        row["reused"] = False
        rows.append(row)
        to_run.append(row)

    def work(row):
        row["started_at"] = round(time.time() - t0, 2)
        row["attempts"] += 1
        state[row["key"]] = {"state": "running", "fingerprint": row["fingerprint"],
                             "attempts": row["attempts"], "started_at": time.time(),
                             "pid": None}
        _save(ledger, state, lock)
        p = subprocess.Popen(row["argv"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        state[row["key"]]["pid"] = p.pid
        _save(ledger, state, lock)
        out, err = p.communicate()
        row["ended_at"] = round(time.time() - t0, 2)      # this child's own end, not the loop's
        row["stdout"], row["stderr"], row["returncode"] = out, err, p.returncode
        art = row.get("produces")
        ok = p.returncode == 0 and (not art or os.path.exists(art))
        state[row["key"]] = {"state": "done" if ok else "failed",
                             "fingerprint": row["fingerprint"], "attempts": row["attempts"],
                             "seconds": round(row["ended_at"] - row["started_at"], 2),
                             "artifact": art or "", "artifact_sha256": _sha_file(art) if art and ok else "",
                             "stdout": out[-4000:] if ok else "", "returncode": p.returncode,
                             "ended_at": time.time()}
        _save(ledger, state, lock)

    threads = [threading.Thread(target=work, args=(r,), daemon=True) for r in to_run]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return rows, round(time.time() - t0, 2)


def overlap(rows, wall):
    """How much the children really overlapped: busy time ÷ wall time, over the ones that ran.

    1.0 means they might as well have run one after another; N means N were busy throughout.
    Reused members are excluded — they were not running in this pass.
    """
    ran = [r for r in rows if not r.get("reused")]
    busy = sum(r["ended_at"] - r["started_at"] for r in ran)
    return round(busy / wall, 2) if wall and ran else 0.0
