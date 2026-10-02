"""What every step starts with — and what every package had been copying.

Six packages were read against docs/packages.md (docs/record/PACKAGE-MATRIX.md): all six carry
the same first lines — read the run id, find the workspace, print one line of JSON at the end —
and one of them had it wrong, addressing the workspace through an environment variable nothing
in the stack sets. That is what a copied contract does: it drifts, and it drifts in the copy
nobody reads. The three answers live here now, and a step starts with `import step`.

    import step
    RUN = step.run_id()
    WS  = step.workspace()                 # <workspace_root>/<conductor run id>
    ...
    step.out(decision="PASS", reason="...")   # the last line of stdout, the step's output

`workspace()` asks the stack's settings (stack/settings.py) and nothing else. Outside the stack
`settings` is not importable and the import fails — which is the right answer. A step that fell
back to a guessed root used to "work" on a fixture while writing where nothing would look for it
(agent-stack-devflow, lib/stackenv.py, records the one time that nearly reached GitHub). With the
stack's settings present but nothing generated yet, settings' own documented default applies.

`main(fn, **shape)` runs a step and turns an exception into its answer: the same one line of
JSON, carrying every key the workflow's `output:` declares (Conductor refuses a line that lacks
one) with `status: TOOL_FAILURE` and the reason. A machinery failure is then a result the graph
can route on, never a traceback the operator finds minutes later in a log.

This file is importable because the stack sets PYTHONPATH to /work/stack:/work/stack/steps for
every step (docker/compose.poc.yaml). A package that wants to run its steps outside that
environment — a host-side control, say — puts /work/stack/steps on sys.path itself, as the
in-tree packages do, and the fail-closed property above still holds through `settings`.

Not a step: it declares no REPEATABLE, and the control that scans steps for one skips it by name.
"""
import json
import os
import sys

# `settings` lives one directory up. When this file was found by path rather than PYTHONPATH,
# that directory may not be importable yet; make it so, from where this file actually is.
_STACK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _STACK not in sys.path:
    sys.path.insert(0, _STACK)


def run_id():
    """Conductor's id for this run — the key of the workspace, the record and the evidence."""
    return os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")


def runtime():
    """The stack's generated runtime settings. Raises when they are not there to be read."""
    import settings
    return settings.runtime()


def workspace(run=None):
    """<workspace_root>/<run id>. Not created: the step that writes there creates it."""
    return os.path.join(runtime()["paths"]["workspace_root"], run or run_id())


def evidence_dir(name=None):
    """<evidence_root>/<name>, the directory a model call's evidence goes in; `name` defaults to
    the run id, and a step that makes several calls names each one (<run>-<label>-<provider>)."""
    return os.path.join(runtime()["paths"]["evidence_root"], name or run_id())


def out(**fields):
    """The step's output: one line of JSON on stdout, the last one. Returns the dict."""
    sys.stdout.write(json.dumps(fields, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return fields


def refuse(reason, **fields):
    """Say what is missing and stop, exit 0: the graph decides what a refusal means here.
    `fields` are the keys the workflow's output declares, with the values a refusal carries."""
    fields.setdefault("status", "REFUSED")
    out(reason=str(reason)[:300], **fields)
    sys.exit(0)


def main(fn, **shape):
    """Run `fn()`; an exception becomes the step's answer in the declared shape, exit 0.

    `shape` is every key the workflow's `output:` declares, with the value it holds when the
    step did not get to compute one. A SystemExit (a refusal) passes through unchanged.
    """
    try:
        return fn()
    except SystemExit:
        raise
    except Exception as e:                   # noqa: BLE001 — the point is to report, not to hide
        answer = dict(shape)
        answer["status"] = "TOOL_FAILURE"
        answer["reason"] = f"{type(e).__name__}: {e}"[:300]
        out(**answer)
        return 0


# ---- binding a result to the input it was made from --------------------------------------
# Four packages hashed their inputs and bound results to the hash, each in its own words
# (docs/record/PACKAGE-MATRIX.md, X2): novel's receipt `context` is the frozen draft's sha256 and
# its triage refuses a review made for another draft; trading builds its packet twice and
# compares; devflow hashes a tree. The mechanism is the same and lives here. What to bind —
# which bytes are "the input", and whether a mismatch blocks or repairs — stays the workflow's.

def bind_file(path, chunk=1 << 16):
    """sha256 of a file's bytes, hex — the name a result is bound to."""
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def bind_text(text):
    """sha256 of a string's UTF-8 bytes, hex."""
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bound(receipt, expected, key="context"):
    """Whether a receipt (a dict with the `context` the fan-out carried back unchanged) was made
    for `expected`. False for a missing key, an empty expectation, or a different one — a receipt
    for another input is not this round's, and a receipt with no binding is not one either."""
    return bool(expected) and isinstance(receipt, dict) and receipt.get(key) == expected
