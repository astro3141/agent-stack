"""The package's own step: write the text it was given into this run's workspace.

Deterministic, no network, no model. What a repeat does (OPERATIONS.md §17): "yes" — the same
text gives the same file and the same hash, so running it again changes nothing.
"""
REPEATABLE = "yes"
import hashlib, os, sys

sys.path.insert(0, "/work/stack/steps")   # the stack's PYTHONPATH has it; this is for running by hand
import step                               # docs/packages.md, contract 1 and 2

WS = step.workspace()                     # <workspace_root>/<conductor run id>, from the stack's settings

text = (sys.argv[1] if len(sys.argv) > 1 else "hello from a package")
os.makedirs(WS, exist_ok=True)
path = f"{WS}/hello.txt"
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write(text + "\n")
step.out(path=path, chars=str(len(text)), sha256=hashlib.sha256(text.encode()).hexdigest())
