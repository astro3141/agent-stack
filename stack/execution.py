"""The execution record: what one routed model call reports, in one shape, everywhere it travels.

A call's result goes a long way — `steps/agent_task.py` prints it, a fan-out (`steps/tasks.py`)
keeps it in a receipt, a chain (`steps/task_chain.py`) keeps it as one of its steps, the recorder
(`steps/record.py`) turns it into an MLflow run, and `trajectory.py` sums it up — and each of
those used to pick the fields it wanted by hand. That is how a retry lost its first attempt's
cost on the way (OPERATIONS §67): nothing on the path owned the shape. This does.

    import execution
    rec = execution.record(status="COMPLETED", provider="claude", run_id=..., ...)   # every field, defaults filled
    execution.write(evidence_dir, rec)       # <evidence_dir>/execution.json — the platform's copy
    execution.read(evidence_dir)             # it back, or None
    execution.is_execution(d)                # a dict that names a call (run_id + provider)
    execution.problems(d)                    # what a record is missing, [] when nothing
    execution.of_member(label, member)       # every execution a fan-out member made: each attempt,
                                             # and each model step of a chain

`FIELDS` is the whole shape, and docs/packages.md lists the same keys for a workflow's `output:`
block — the one place and the document say the same thing because the control compares them.
A record carries `contract`, the version of this shape, so a reader can tell an old one apart.
"""
import copy, json, os

CONTRACT = 2                             # 2: the query kind's keys (§89) — a 1 is a record from before them

# every key a model step answers with, and what it holds when the call did not get that far
FIELDS = {
    "status": "FAILED",                  # COMPLETED | FAILED | DENIED | TIMED_OUT | INVALID_OUTPUT | TOOLS_USED | …
    "kind": "task",                      # task: the prompt may use tools and writes an artifact;
                                         # query: one prompt, no tools, an answer in a declared shape (§89)
    "provider": "",
    "principal": "",                     # the Preloop principal the call presented
    "model_route": "",
    "run_id": "",                        # <run>-<label>-<provider>[-a<n>]: this call's evidence directory
    "workspace": "",
    "produced_path": "",                 # the artifact the step was told to expect
    "produced": False,                   # it is there, and this call wrote it
    "produced_stale": False,             # it is there, untouched by this call (left by an earlier one)
    "model_session_reported": "",
    "model_adapter_reported": "",
    "model_served": "unknown",           # "unknown" unless something on the path reported it
    "approvals_requested": 0,
    "mcp_rule_denials": 0,
    "retryable_elsewhere": False,
    "evidence_dir": "",
    "profile": "",
    "attempts": 1,                       # 2 when the one bounded login-refresh retry ran
    "failure": "",                       # why, when status is not COMPLETED
    "ledger_error": "",
    "turns": 1,                          # one prompt is one turn over ACP; a retry is another call
    "tool_calls": 0,                     # tool calls the turn made (events.jsonl); a query must say 0
    "server_tool_use": 0,                # of those, web lookups
    "schema_sha256": "",                 # a query: the declared schema, by content
    "answer": {},                        # a query: the validated answer; {} until there is one
    "measurements": {},                  # a number the adapter did not report is left out, never 0;
                                         # model_usage: per-model token counts, as the adapter reported them
}
REQUIRED = ("run_id", "provider", "status")

# A call the vendor refused before any work — the login, the account, the organisation — is a
# fact about the *login*, not about this run, and the quota observer cannot see it: it reads a
# token file and answers "expired, run `claude login`" while the call itself answers "your
# organization has disabled … use an API key" (trading's measurement on #44). The door leaves the
# sentence beside the login's kept reading, the collector carries it, the router says it, and a
# completed call removes it. Only sentences of that class are kept; a model's own failure is not.
REFUSAL_WORDS = ("organization has disabled", "not logged in", "token expired", "oauth",
                 "authenticate", "api key", "unauthorized", "invalid_api_key", "credentials not found",
                 "subscription", "403", "401")


def login_refusal(text):
    """True when a failure's words say the login or the account was refused, not the work."""
    t = str(text or "").lower()
    return any(w in t for w in REFUSAL_WORDS)


def refusal_path(logins_root, provider, login):
    """<logins_root>/.quota/<provider>-<login>.refused.json — beside the kept quota reading."""
    import os
    return os.path.join(logins_root, ".quota", f"{provider}-{login}.refused.json")


def note_refusal(logins_root, provider, login, rec):
    """Leave the door's note beside the login when this call was refused for the account's sake,
    and take it back when a call completed. Returns "left" | "cleared" | "" — never raises: the
    record is the deliverable, this is a note beside it."""
    import json as _j, os, time
    try:
        p = refusal_path(logins_root, provider, login)
        if rec.get("status") == "COMPLETED":
            if os.path.exists(p):
                os.remove(p)
                return "cleared"
            return ""
        if not login_refusal(rec.get("failure")):
            return ""
        os.makedirs(os.path.dirname(p), exist_ok=True)
        _j.dump({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "run_id": rec.get("run_id"),
                 "failure": str(rec.get("failure"))[:300]}, open(p + ".tmp", "w"))
        os.replace(p + ".tmp", p)
        return "left"
    except Exception:
        return ""
TYPES = {"produced": bool, "produced_stale": bool, "retryable_elsewhere": bool,
         "approvals_requested": int, "mcp_rule_denials": int, "attempts": int, "measurements": dict,
         "turns": int, "tool_calls": int, "server_tool_use": int, "answer": dict}


def record(**fields):
    """A whole record: every key of FIELDS, the given values over the defaults, the contract
    version. Keys outside FIELDS are kept — a brokered call adds `dispatched`, a chain step adds
    `step` and `kind` — so nothing a step says is dropped on the way."""
    out = copy.deepcopy(FIELDS)
    out.update({k: v for k, v in fields.items() if v is not None})
    out["contract"] = CONTRACT
    return out


def normalize(d):
    """The same, from a dict a step printed (or an older reader kept)."""
    return record(**(d if isinstance(d, dict) else {}))


def is_execution(d):
    """Whether this dict names a call that was made: a run id (its evidence) and a provider."""
    return isinstance(d, dict) and bool(d.get("run_id")) and bool(d.get("provider"))


def problems(d):
    """What is wrong with a record, as a list of sentences; [] when nothing is."""
    if not isinstance(d, dict):
        return ["not an object"]
    out = [f"{k} missing" for k in REQUIRED if not d.get(k)]
    for k, t in TYPES.items():
        if k in d and not isinstance(d[k], t) or (t is int and isinstance(d.get(k), bool)):
            out.append(f"{k} is not {t.__name__}")
    return out


def failure_of(r):
    """Why a call did not complete, in the one line a reader of the step's output sees.

    From the adapter's result: its own `failure.message`, else the vendor turn's error, else —
    for a DENIED — what refused it: the first MCP rule denial's text ("Access denied: …") or
    the first permission denial's kind. "" for a completed call. Measured on the recorded runs
    (stack/fixtures/run-agent): a DENIED used to read `"{}"` here, the JSON of nothing (#27).
    """
    if not isinstance(r, dict):
        return ""
    if r.get("status") == "COMPLETED":
        return ""
    msg = ((r.get("failure") or {}).get("message") if isinstance(r.get("failure"), dict) else r.get("failure")) \
        or ((r.get("turn") or {}).get("error") or {}).get("message")
    if msg:
        return str(msg)[:300]
    for d in r.get("mcp_denials") or []:
        if isinstance(d, dict) and d.get("text"):
            return str(d["text"])[:300]
    for p in r.get("permissions") or []:
        if isinstance(p, dict) and p.get("outcome") != "allow_once":
            return f"permission {p.get('denial') or 'refused'}: {p.get('title') or p.get('acp_kind') or 'tool'}"[:300]
    rest = (r.get("turn") or {}).get("error") or r.get("failure") or {}
    return (json.dumps(rest, ensure_ascii=False)[:300] if rest else "")


def write(evidence_dir, rec):
    """The platform's own copy of the record, beside the adapter's raw result.json."""
    if not evidence_dir:
        return
    try:
        os.makedirs(evidence_dir, exist_ok=True)
        with open(os.path.join(evidence_dir, "execution.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False, indent=1)
    except OSError:
        pass                                      # the step's stdout still carries it


def read(evidence_dir):
    try:
        with open(os.path.join(evidence_dir, "execution.json"), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def attempts_of(member):
    """Every attempt's result a fan-out member made, oldest first — the kept list, or the one."""
    rows = member.get("attempt_results") if isinstance(member, dict) else None
    if isinstance(rows, list) and rows:
        return [r for r in rows if isinstance(r, dict)]
    r = (member or {}).get("result") if isinstance(member, dict) else None
    return [r] if isinstance(r, dict) else []


def of_member(label, member):
    """Every execution a fan-out member made, each tagged with the member it belonged to: the
    model steps of a chain (one per step), or the call itself — for every attempt. Not an
    execution: a chain whose steps were all scripts, or an attempt that never named a call."""
    out = []
    for r in attempts_of(member):
        steps = [st for st in (r.get("steps") or [])
                 if isinstance(st, dict) and st.get("kind") == "model" and is_execution(st)]
        if steps:
            out.extend({**normalize(st), "member": f"{label}:{st.get('step', '')}"} for st in steps)
        elif is_execution(r):
            out.append({**normalize(r), "member": label})
    return out
