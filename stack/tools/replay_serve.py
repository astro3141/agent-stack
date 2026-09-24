"""Serve Conductor's own run dashboard for a recorded run — outside the agent's isolation.

usage: replay_serve.py <port>      (runs in the `replay` container; the workspace is mounted ro)

Conductor draws a workflow run far better than we would, and it already knows how to do it from a
recorded event log: `ReplayDashboard` serves the same React frontend with a replay-mode API
(conductor/web/replay.py, MIT). Two things made it usable here:

  * its `host` is a parameter — the CLI leaves it on the container's loopback, which is why
    `conductor run --web` cannot be reached (OPERATIONS.md §14), but the class takes any address;
  * it needs nothing but the event log, and this stack keeps one per run already
    (evidence/ui-runs/<id>/tmp/conductor/*.events.jsonl).

So this runs in a container that is **not** the agent: on the ops network, with the workspace
mounted read-only, and no credentials of any kind. The agent stays single-homed on its internal
network, which is the reason the dashboard could not simply be published from there.

Which run is being shown is a one-line file the ops API writes (evidence/ops/replay.run). Watching
a file rather than opening a control port keeps this container without an inbound API of its own:
it serves a dashboard and reads a name, and that is all it can do.
"""
import asyncio, glob, os, sys
from pathlib import Path

from conductor.web.replay import ReplayDashboard

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8785
REQUEST = "/work/evidence/ops/replay.run"
RUNS = "/work/evidence/ui-runs"


def log_for(run_id):
    """The event log of one run, or the newest run's when none is named."""
    if run_id:
        if not run_id.replace("-", "").isalnum():        # a name, never a path
            return None
        hits = sorted(glob.glob(f"{RUNS}/{run_id}/tmp/conductor/*.events.jsonl"))
        return Path(hits[-1]) if hits else None
    hits = sorted(glob.glob(f"{RUNS}/*/tmp/conductor/*.events.jsonl"), key=os.path.getmtime)
    return Path(hits[-1]) if hits else None


def requested():
    try:
        return open(REQUEST, encoding="utf-8").read().strip() or None
    except OSError:
        return None


async def main():
    current, dash = None, None
    while True:
        want = requested()
        if want != current or dash is None:
            path = log_for(want)
            if path is None:
                print(f"no event log for {want!r}; keeping the current one", flush=True)
                current = want
                await asyncio.sleep(2)
                continue
            if dash is not None:
                await dash.stop()
                dash = None
                await asyncio.sleep(0.3)     # let the port go
            dash = ReplayDashboard(path, host="0.0.0.0", port=PORT)
            await dash.start()
            current = want
            print(f"showing {want or '(newest)'}: {path}", flush=True)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
