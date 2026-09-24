"""The package's own step: write the text it was given into this run's workspace.

Deterministic, no network, no model. What a repeat does (OPERATIONS.md §17): "yes" — the same
text gives the same file and the same hash, so running it again changes nothing.
"""
REPEATABLE = "yes"
import hashlib, json, os, sys

RUN = os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")
WS = f"{os.environ.get('P281_WORKSPACE_ROOT', '/ws')}/{RUN}"

text = (sys.argv[1] if len(sys.argv) > 1 else "hello from a package")
os.makedirs(WS, exist_ok=True)
path = f"{WS}/hello.txt"
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write(text + "\n")
print(json.dumps({"path": path, "chars": str(len(text)),
                  "sha256": hashlib.sha256(text.encode()).hexdigest()}))
