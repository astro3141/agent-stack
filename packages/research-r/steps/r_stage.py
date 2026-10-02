"""Conductor script step: move files between #280's run directory and the agents' workspace.

The agents can write only through the Preloop MCP server, which serves /ws. #280's
deterministic steps read and write /research/artifacts/runs/<run id>. This step bridges the
two, deterministically, and never edits content.

  r_stage.py in      reference fixture              → /ws/<run>/
  r_stage.py review  candidate + both verifications → /ws/<run>/   (for the reviewer)
  r_stage.py back    /ws/<run>/review.json          → run directory (input-verify re-hashes it)
"""

# What a repeat of this step does (OPERATIONS.md §17): "yes" — the same result;
# "guarded" — it recognises the repeat; "no" — it does the work again.
REPEATABLE = "yes"   # prepares the research run's workspace from fixtures
import hashlib, shutil, sys
from pathlib import Path
sys.path.insert(0, "/work/stack/steps")   # the stack's PYTHONPATH has it; this is for running by hand
import step                               # docs/packages.md, contract 1 and 2

run = step.run_id()
ws = Path(step.workspace()); ws.mkdir(parents=True, exist_ok=True)
rd = Path("/research/artifacts/runs") / run
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()


def refuse(reason):
    # What is missing, said in the output (contract 5) — not a traceback from shutil. Before this,
    # `in` and `review` on a host without the /research mount died with FileNotFoundError and no
    # JSON line, which Conductor reads as the step crashing rather than as the run refusing.
    step.out(ok=False, moved=[], reason=reason, hashes={}); sys.exit(0)


mode = sys.argv[1] if len(sys.argv) > 1 else ""
moved = []
if mode == "in":
    src = Path("/research/artifacts/reference-fixture.json")
    if not src.is_file():
        refuse(f"{src} is not there: this trial needs the /research mount (docker/compose.poc.yaml)")
    shutil.copyfile(src, ws / src.name); moved.append(src.name)
elif mode == "review":
    names = ("candidate.json", "verification.primary.json", "verification.independent.json")
    missing = [n for n in names if not (rd / n).is_file()]
    if missing:
        refuse(f"the research run directory {rd} lacks {', '.join(missing)}")
    for n in names:
        shutil.copyfile(rd / n, ws / n); moved.append(n)
elif mode == "back":
    src = ws / "review.json"
    if not src.is_file():
        refuse("reviewer produced no review.json")
    rd.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, rd / "review.json"); moved.append("review.json")
else:
    refuse(f"unknown mode {mode!r}: in | review | back")
step.out(ok=True, moved=moved, reason="", hashes={n: sha(ws / n) for n in moved})
