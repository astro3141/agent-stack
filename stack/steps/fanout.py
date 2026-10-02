"""Start several subprocesses together and measure each one's own start and end.

Used by the capability trials (steps/novel_reviews.py, steps/trade_lanes.py), which need real
concurrency because Conductor's `parallel` / `for_each` groups refuse script steps (v0.1.37) and
every routed model call here is a script step.

Why this exists as its own module: the first version of both trials collected the children with a
sequential loop of `communicate()` and stamped the end time when the loop reached each child. With
a slow child first, every later child was recorded as ending when the slow one did — measured, a
100 s + 1 s + 1 s fan-out reported a concurrency of 3.00 where the true overlap was 1.02. A
measurement that flatters the thing being measured is worse than none, so the waiting is done in a
thread per child and each child stamps its own end.
"""

# What a repeat of this step does (OPERATIONS.md §17): "yes" — the same result;
# "guarded" — it recognises the repeat; "no" — it does the work again.
REPEATABLE = "no"   # it starts whatever it was given
import os, subprocess, threading, time


def run_all(jobs):
    """jobs: [{"key": str, "argv": [..], **extra}] → (rows, wall_s)

    Each row carries the job's extras plus: started_at, ended_at (offsets in seconds from the
    first start), stdout, stderr, returncode — every row, including one whose process could not
    be started (returncode 127, the reason in stderr, `start_failed`). A job may carry `env`,
    added to the child's environment.
    """
    t0 = time.time()
    rows = [dict(j) for j in jobs]
    threads = []

    def work(row):
        row["started_at"] = round(time.time() - t0, 2)
        env = {**os.environ, **(row.get("env") or {})} if row.get("env") else None
        try:
            p = subprocess.Popen(row["argv"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            out, err, rc = *p.communicate(), p.returncode
        except Exception as e:                           # noqa: BLE001 — an executable that is not
            # there, a path that cannot be run: this member failed to *start*. It used to leave
            # the row without an end, and the step reading the rows died on every member's behalf
            # (review 2026-10-02) — one member's failure touching the others, which is the one
            # thing this module promises not to let happen.
            out, err, rc = "", f"{type(e).__name__}: {e}", 127
            row["start_failed"] = True
        row["ended_at"] = round(time.time() - t0, 2)      # this child's own end, not the loop's
        row["stdout"], row["stderr"], row["returncode"] = out, err, rc

    for row in rows:
        t = threading.Thread(target=work, args=(row,), daemon=True)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    return rows, round(time.time() - t0, 2)


def overlap(rows, wall):
    """How much the children really overlapped: busy time ÷ wall time.

    1.0 means they might as well have run one after another; N means N were busy throughout.
    """
    busy = sum(r["ended_at"] - r["started_at"] for r in rows)
    return round(busy / wall, 2) if wall else 0.0
