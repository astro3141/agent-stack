"""Conductor script step: one model task through the routing/execution layer.

usage: agent_task.py <provider> <model_route> <label> <prompt-file|-> <expected-file>
       [<profile> [<login> [<principal>]]] [--output-schema <schema.json>] [--model <id>]

`--model <id>` asks the vendor for that model by name — the adapter already forwards `req.model`
as a session option (run-agent.mjs); without it the login's default answers, which a pinned
binding cannot accept after the fact (#62: a pin enforced only post-hoc is a refusal the call
already paid for). What actually answered is still read from the record's `model_usage` rows —
the ask and the check stay separate.
The prompt file may use {WS} for the run's shared workspace (/ws/<conductor run id>), which
every model step of the run shares, so a later step can read what an earlier one wrote.
Writes are only possible through the Preloop MCP server (native write/shell are removed);
Preloop's rules decide them. Emits the normalized result flat for Conductor.

Two things shape a call, and they are independent (§102; docs/packages.md "The shape of a call").
The **environment** is the profile's: `tools.allowed: []` in the profile asks the vendor for no
tools and one turn (the adapter's session options `allowedTools: []`, `maxTurns: 1`, no Preloop
MCP server, every permission request refused by the adapter without asking) — a *closed* call; a
tool call the vendor made anyway is TOOLS_USED. The **output contract** is this option's:
`--output-schema <schema.json>` has the answer — the expected file when this attempt wrote it,
else the model's text with one surrounding fence removed — read as JSON after the call and checked
against the schema here, the same for every vendor. Valid → COMPLETED, the answer in the expected
file and carried as `answer`; invalid → INVALID_OUTPUT with every break named, and no retry — a
failure the model made is not retried (CONTRACT.md). With a schema, `produced` means a valid
answer arrived. The prompt file may be `-` for stdin. Retried once, as any call is: a login
refresh; and, with a schema and no file written, a text that is not JSON at all (a cut stream,
not an answer). The query kind (§89) was these two bundled into one, with the stack deciding how
they are used; now the profile and the option each say their own thing, and the record says both.

Where it runs is the role's business, not the caller's: a principal that declares an egress
profile is handed to the broker (steps/broker_dispatch.py, same argv) and runs in that profile's
container; any other runs here. A workflow names this step and never has to choose a door.
"""

# What a repeat of this step does (OPERATIONS.md §17): "yes" — the same result;
# "guarded" — it recognises the repeat; "no" — it does the work again.
REPEATABLE = "no"   # a model call: it costs, and the answer is not the same twice
import hashlib, json, os, subprocess, sys, time
sys.path.insert(0, "/work/stack")
import execution
import query as queryk
import settings


def split_options(argv):
    """The door's options, parted from its positionals.

    `--output-schema <schema>` and `--model <id>` may stand anywhere after the positional arguments,
    so the positionals are read without them — and the options stay in argv, moved behind the
    positionals, because the two re-executions below (the broker, the role's uid) pass argv on as
    it is: deleted for the positional parse, they did not travel, and a confined role's call with
    a schema reached the dispatch step without it, with `-` for a prompt file (`prompt unreadable`,
    §91). Returns (positionals, options as given, schema file, model id, why) — `why` names an
    option that was given without its value.
    """
    pos, opts, vals, why = [], [], {"--output-schema": "", "--model": ""}, ""
    rest = list(argv)
    while rest:
        a = rest.pop(0)
        if a in vals:
            v = rest.pop(0) if rest else ""
            if not v:
                why = f"{a} needs {'the schema file' if a == '--output-schema' else 'the model id'}"
            vals[a] = v
            opts += [a, v]
        else:
            pos.append(a)
    return pos, opts, vals["--output-schema"], vals["--model"], why


POSITIONAL, PASSTHROUGH, schema_file, model_id, _why = split_options(sys.argv[1:])
if _why:
    print(json.dumps(execution.record(status="FAILED", produced=False, failure=_why)))
    raise SystemExit(0)
sys.argv[1:] = POSITIONAL + PASSTHROUGH          # the positionals first, the options behind them, nothing lost
provider, model_route, label, prompt_file, expected = POSITIONAL[:5]
prof_name = POSITIONAL[5] if len(POSITIONAL) > 5 and POSITIONAL[5] else "research-default"
login = POSITIONAL[6] if len(POSITIONAL) > 6 and POSITIONAL[6] else provider
# the principal whose tool rights this step runs with; empty means the adapter's own credential
principal = POSITIONAL[7] if len(POSITIONAL) > 7 and POSITIONAL[7] else ""
RT, PROF = settings.runtime(), settings.profile(prof_name)
# A profile is live only once `cfg.py generate` has written it (scripts/up.sh does). A yaml that
# exists without that ran as an empty profile here — no native_allow, so every web lookup waited
# for a person until the step timed out (novel-v2, #79). Refused, with what there is instead.
if PROF is None:
    print(json.dumps(execution.record(
        status="FAILED", provider=provider, principal=principal, profile=prof_name,
        produced=False, attempts=0,
        failure=f"profile {prof_name!r} has no generated file — a profile yaml is live only after "
                f"`cfg.py generate` (scripts/up.sh runs it); generated now: "
                f"{', '.join(settings.profile_names()) or 'none'}")))
    raise SystemExit(0)
# The environment is the profile's (§102): `tools.allowed` is the list the vendor's agent is handed
# as its tools (the adapter's session option); `[]` is a closed call — no tools, one turn, every
# permission request refused where it arrives — and the record says `closed`. No key: the agent's
# own tools, under the profile's native_tools/native_allow and Preloop's rules, as before.
ALLOWED = (PROF.get("tools") or {}).get("allowed")
closed = isinstance(ALLOWED, list) and len(ALLOWED) == 0
run = os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")
ws = f"{RT['paths']['workspace_root']}/{run}"
os.makedirs(ws, exist_ok=True)
# a retry (tasks.py) names itself: its evidence sits beside the first attempt's, not over it
attempt = os.environ.get("AGENTSTACK_ATTEMPT", "")
run_id = f"{run}-{label}-{provider}" + (f"-a{attempt}" if attempt and attempt != "1" else "")
# A workflow may call the same step again under the same label — novel's repair loop does, and
# a retry is only one of the ways — and a call made twice is two calls: the second one's evidence
# sits beside the first's (-r2, -r3 …), never over it. Measured before this: two calls of 100 and
# 200 tokens left one record of 200 (review 3, OPERATIONS §79). Decided here, after the door below
# has had its say, so the one process that makes the call is the one that names it.
def _own_evidence_dir(base):
    root = RT["paths"]["evidence_root"]
    rid, n = base, 2
    while os.path.isdir(f"{root}/{rid}") and os.listdir(f"{root}/{rid}"):
        rid, n = f"{base}-r{n}", n + 1
    return rid, f"{root}/{rid}"


def shared_with_roles(*paths):
    """Let a step that runs as its own role write where every step of this run writes.

    A role has its own uid (OPERATIONS §48), so the run's workspace and this call's evidence
    directory have to be writable by the group the roles share — the workspace is shared between the
    steps of a run by design, which is the point of `{WS}` in a prompt. setgid, so what a role
    creates stays in the group and the next step can read it.
    """
    import grp
    try:
        gid = grp.getgrnam("roles").gr_gid
    except KeyError:
        return
    for p in paths:
        try:
            os.chown(p, -1, gid)
            os.chmod(p, 0o2775)
        except OSError:
            pass          # not ours to change: the step still runs, and it is the same directory


# The door (§54). A role that declares an egress profile runs in that profile's container, through
# the broker — the fan-out (steps/tasks.py) and a chain (steps/task_chain.py) already swap the
# entrypoint for such a role, and a workflow that calls this step directly now gets the same swap
# here, so a package need not know there are two doors (docs/record/PACKAGE-MATRIX.md, "the door
# leaks into the workflow"). The argv is the same either way. Inside the profile's container the
# runner has already dispatched (it marks its environment with AGENTSTACK_EGRESS_PROFILE) and this
# step runs as itself. A role without a profile is untouched by this.
if principal and not os.environ.get("AGENTSTACK_EGRESS_PROFILE") and not os.environ.get("AGENTSTACK_ROLE"):
    try:
        import role_egress
        _profile = role_egress.profile_of(principal)
    except Exception:
        _profile = ""
    if _profile:
        os.execv(sys.executable, [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "broker_dispatch.py")] + sys.argv[1:])
run_id, evid = _own_evidence_dir(run_id)
os.makedirs(evid, exist_ok=True)

# Run as the role this step belongs to, when that role has one of its own. Everything after this
# point is that role: its uid, and its egress. A step whose role declares no hosts is not re-executed
# and nothing about it changes (§48).
if principal and not os.environ.get("AGENTSTACK_ROLE"):
    try:
        sys.path.insert(0, "/work/stack")
        import role_egress
        # what this role declares *now*. The uid map is kept across bring-ups on purpose — a role's
        # uid must not move — so it still holds roles that have since dropped their declaration, and
        # reading it as "is this role confined" refused every step of such a role (measured: a
        # reviewer whose declaration had been taken back out).
        role_uid = ((role_egress.assignment().get(principal) or {}).get("uid")
                    if principal in role_egress.declared() else None)
    except Exception:
        role_uid = None
    # A confined role needs a **login of its own**, and this is not a rule about one vendor
    # (OPERATIONS §50). Every one of these CLIs owns its credential file: codex sets its mode when
    # it starts (chmod on a file you do not own is EPERM), grok reads an auth.json it keeps at 0600,
    # and all of them rewrite it when the token refreshes — which resets whatever group access an
    # operator granted. Measured: grok's auth.json came back 0600 owned by the launcher after a
    # refresh, so a role sharing that login works until the next one and then stops. Sharing is the
    # trap; owning is the arrangement.
    if role_uid:
        login_dir = f"{RT['paths']['logins_root']}/{login}"
        try:
            owner = os.stat(login_dir).st_uid
        except OSError:
            owner = None
        if owner != role_uid:
            rec = execution.record(
                status="FAILED", provider=provider, principal=principal,
                run_id=run_id, workspace=ws, produced=False, produced_stale=False,
                evidence_dir=evid, profile=prof_name, attempts=0,
                failure=f"{principal} declares egress of its own, so this step runs as that "
                           f"role's uid — and the login {login!r} belongs to "
                           f"{'uid ' + str(owner) if owner is not None else 'nobody: it is not there'}. "
                           "These CLIs own their credential files: they set the mode, and they "
                           "rewrite it on every token refresh, so group access granted by hand "
                           "lasts until the next one. The way out is to declare `egress_profile:` "
                           "and drop `egress:` — the uid path is deprecated (§51–§55), nothing on "
                           "the panel makes a login a role owns, and a brokered role needs none; "
                           "the uid path survives only with a login made inside the container and "
                           "chowned to this role's uid by hand (§50, §95).")
            execution.write(evid, rec)
            print(json.dumps(rec))
            raise SystemExit(0)
    if role_uid and os.path.exists("/usr/local/bin/role-exec"):
        shared_with_roles(ws, evid)
        # -E keeps this step's environment: the run id, the workspace, the credential the adapter
        # presents. sudo resets it by default, and a step that lost CONDUCTOR_SELF_RUN_ID wrote to
        # the wrong workspace and could not authenticate at all (measured). What role-exec then
        # overrides is exactly the proxy — the one thing this role is supposed to have of its own.
        os.environ["AGENTSTACK_HOME"] = os.environ.get("HOME", "/home/agent")
        os.execvp("sudo", ["sudo", "-n", "-E", "-u", principal,
                           "/usr/local/bin/role-exec", principal,
                           "--", sys.executable, os.path.abspath(__file__)] + sys.argv[1:])
def _refused(why, **more):
    """A call that is not made: the record says why, with attempts 0, and the step ends."""
    rec = execution.record(status="FAILED", closed=closed, provider=provider, principal=principal,
                           run_id=run_id, workspace=ws, produced=False, produced_stale=False,
                           evidence_dir=evid, profile=prof_name, attempts=0, failure=why, **more)
    execution.write(evid, rec)
    print(json.dumps(rec))
    raise SystemExit(0)


# The prompt: a file, or `-` for stdin (a harness that never writes its prompt to disk, #62);
# {WS} where it appears is the run's shared workspace. What the model is told about the shape it
# must answer in is the prompt's business, and request.json carries the prompt the model saw.
_bytes = sys.stdin.buffer.read() if prompt_file == "-" else open(prompt_file, "rb").read()
prompt = _bytes.decode("utf-8", errors="surrogateescape").replace("{WS}", ws)

# The output schema is the step's to check, after the call; so it is read before, and a schema
# this validator would only half-read is refused now, at no cost — an answer called valid against
# a keyword nobody checked would be the worse outcome (stack/query.py).
schema, schema_sha = None, ""
if schema_file:
    try:
        sbytes = open(schema_file, "rb").read()
        schema = json.loads(sbytes.decode("utf-8"))
        schema_sha = hashlib.sha256(sbytes).hexdigest()
    except (OSError, ValueError) as e:
        _refused(f"the schema {schema_file!r} could not be read as JSON: {type(e).__name__}: {e}"[:300])
    if not isinstance(schema, dict) or schema.get("type") != "object":
        _refused("an output schema is an object with \"type\": \"object\" at its root — the shape the "
                 "three vendors' own schema modes require too; the answer travels as `answer`, a mapping",
                 schema_sha256=schema_sha)
    bad = queryk.unchecked(schema)
    if bad:
        _refused(f"the schema uses keywords this door does not check ({', '.join(bad)}); it checks "
                 f"{', '.join(sorted(queryk.CHECKED))} and reads nothing else — an answer called valid "
                 "against a half-read schema is not an answer (stack/query.py)", schema_sha256=schema_sha)

req = {"run_id": run_id, "provider": provider, "model_route": model_route or "preloop_gateway",
       "login": login, "profile": prof_name,
       **({"allowed_tools": list(ALLOWED)} if isinstance(ALLOWED, list) else {}),
       **({"mcp_principal": principal} if principal else {}),
       "cwd": ws, "timeout_ms": (PROF.get("execution") or {}).get("timeout_ms", 600000),
       "native_tools": (PROF.get("tools") or {}).get("native_tools", False), "evidence_dir": evid,
       "native_allow": list((PROF.get("tools") or {}).get("native_allow") or []),
       **({"schema_sha256": schema_sha} if schema_file else {}),
       **({"model": model_id} if model_id else {}),
       "prompt": prompt}
rp = os.path.join(evid, "request.json")
json.dump(req, open(rp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
# the adapter, by path: the controls stand a recorded one in its place (AGENTSTACK_ADAPTER) and
# measure this step's own reading of what it answered, with no vendor on the line
ADAPTER = os.environ.get("AGENTSTACK_ADAPTER") or str(settings.STACK / "run-agent.mjs")
def run_once():
    p = subprocess.run(["node", ADAPTER, rp], capture_output=True, text=True,
                       env={**os.environ, "NODE_NO_WARNINGS": "1"})
    try:
        return json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        return {"status": "FAILED", "failure": {"message": (p.stderr or p.stdout)[-400:]}}


# What "produced" is going to mean. The expected file existing is not enough: this step is run
# again — by its own retry below, and by a fan-out member that asked to be retried (§34) — in the
# *same* workspace, under the same name. A call that failed after an earlier attempt had written
# the file would otherwise report `produced: true`, and a chain would advance on an artifact that
# nothing in this attempt wrote. So what counts is that this attempt wrote it.
exp_path = os.path.join(ws, expected)


def stamp():
    try:
        st = os.stat(exp_path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


before = stamp()

r = run_once()
# One retry for a login the provider itself calls transient. Measured: two processes touching the
# same Claude login directory (the quota observer reading usage, and this step) collide on an
# OAuth refresh — "another Claude Code process is refreshing it". Retrying once is enough; it is
# counted here so a run never hides it.
attempts = 1
# `turn` can be present and null — a vendor result with no turn at all. Reading it as a mapping
# crashed the step with an AttributeError instead of reporting why the call failed (measured).
msg = json.dumps((r.get("turn") or {}).get("error") or r.get("failure") or {})
first = None


def tool_use(res):
    """What the turn reached for: (tool calls, web lookups) from the events the adapter kept,
    and a permission it asked for counts as a call even when no event named it."""
    calls, web = queryk.tool_counts(os.path.join(evid, "events.jsonl"))
    return max(calls, len(res.get("permissions") or [])), web


def not_json(res):
    """A completed call with an output schema whose answer has to come from the text — this
    attempt wrote no file — and the text is not JSON at all: a cut stream, read as a transport
    fault and retried once (DECISIONS-2026-10-04 §8) — unlike JSON that breaks the schema, which
    is the model's answer and is not retried."""
    if not schema_file or res.get("status") != "COMPLETED" or tool_use(res)[0]:
        return False
    if stamp() not in (None, before):     # the file was written: the answer is the file, whatever the text
        return False
    try:
        json.loads(queryk.extract(res.get("text") or ""))
        return False
    except ValueError:
        return True


if (r.get("status") != "COMPLETED" and "refresh" in msg.lower()) or not_json(r):
    # the first attempt is kept, not replaced: its adapter result beside the second's, and what it
    # cost in the measurements below (review 3: `attempts=2` alone lost the first result and time)
    first = r
    try:
        os.replace(os.path.join(evid, "result.json"), os.path.join(evid, "result.a1.json"))
    except OSError:
        pass
    try:
        os.replace(os.path.join(evid, "events.jsonl"), os.path.join(evid, "events.a1.jsonl"))
    except OSError:
        pass
    if "refresh" in msg.lower():
        time.sleep(20)
    r = run_once()
    attempts = 2


def _cost(res):
    qq = ((res.get("turn") or {}).get("_meta") or {}).get("quota") or {}
    return (qq.get("token_count") or {}).get("totalTokens"), res.get("wall_ms")


def _usage(res):
    """Per-model token counts, as the adapter reported them: [{model, token_count: {...}}]."""
    qq = ((res.get("turn") or {}).get("_meta") or {}).get("quota") or {}
    return [m for m in (qq.get("model_usage") or []) if isinstance(m, dict)]


q = ((r.get("turn") or {}).get("_meta") or {}).get("quota") or {}
_tok, _wall = _cost(r)
_usage_rows = _usage(r)
if first is not None:
    t1, w1 = _cost(first)
    _tok = (t1 or 0) + (_tok or 0) if (t1 is not None or _tok is not None) else None
    _wall = (w1 or 0) + (_wall or 0) if (w1 is not None or _wall is not None) else None
    _usage_rows = _usage(first) + _usage_rows
meas = {"total_tokens": _tok, "wall_ms": _wall, **({"model_usage": _usage_rows} if _usage_rows else {})}

# The door's own verdicts (§89, §102). A closed call that made a tool call anyway is TOOLS_USED,
# whatever else happened. With an output schema, a completed call's answer — the expected file
# when this attempt wrote it, else the text with one fence removed — is read as JSON and checked;
# what passes from the text is written to the expected file. "produced" then means a valid
# answer arrived, from either source.
status, answer, verdict = r.get("status", "FAILED"), {}, ""
tool_calls, server_tool_use = tool_use(r)
if closed and tool_calls:
    status, verdict = "TOOLS_USED", (f"the call made {tool_calls} tool call(s) — a closed call (the profile's "
                                     "tools.allowed is []) is one prompt with no tools; the vendor did not "
                                     "honour the ask, or the model reached for one (events.jsonl)")
elif schema_file and status == "COMPLETED":
    wrote = stamp() not in (None, before)
    value, probs = None, []
    if wrote:
        try:
            with open(exp_path, encoding="utf-8") as f:
                value = json.load(f)
        except (OSError, ValueError) as e:
            probs = [f"the expected file is not JSON: {e}"]
    else:
        try:
            value = json.loads(queryk.extract(r.get("text") or ""))
        except ValueError as e:
            probs = [f"the text is not JSON: {e}"]
    if not probs:
        probs = queryk.problems(value, schema)
    if probs:
        status, verdict = "INVALID_OUTPUT", "; ".join(probs)[:600]
        if not wrote:
            try:
                with open(os.path.join(evid, "answer.raw.txt"), "w", encoding="utf-8") as f:
                    f.write(r.get("text") or "")
            except OSError:
                pass
    else:
        answer = value
        if not wrote:
            os.makedirs(os.path.dirname(exp_path) or ws, exist_ok=True)
            with open(exp_path, "w", encoding="utf-8") as f:
                json.dump(answer, f, ensure_ascii=False, indent=1)
after = stamp()
# left over from an earlier attempt, untouched by this one: the reader is told, rather than the
# file being deleted — an artifact someone may want to look at is not this step's to destroy
stale = bool(after and after == before)
# One shape, owned in one place (stack/execution.py): what is printed here is what the receipt
# keeps, the recorder reads and the trajectory sums — and a copy goes beside the adapter's own
# result.json, so the evidence directory carries the platform's record of this call too.
rec = execution.record(**{
    "status": status,
    "closed": closed,
    "provider": provider,
    "principal": principal,
    "model_route": r.get("model_route") or model_route,
    "run_id": run_id,
    "workspace": ws,
    "produced_path": exp_path,
    "produced": bool(after) and not stale and not verdict,   # with a schema: a valid answer arrived
    "produced_stale": stale,
    "model_session_reported": (r.get("model") or {}).get("session_reported") or "",
    "model_adapter_reported": ",".join(m.get("model", "") for m in q.get("model_usage", [])),
    "model_served": (r.get("model") or {}).get("served") or "unknown",
    "approvals_requested": sum(1 for x in r.get("permissions", []) if x.get("routed") == "preloop_approval"),
    "mcp_rule_denials": len(r.get("mcp_denials", [])),
    "retryable_elsewhere": bool(r.get("retryable_elsewhere")),
    "evidence_dir": evid,
    "profile": prof_name,
    "attempts": attempts,
    **({"attempt_outcomes": [first.get("status", "FAILED"), r.get("status", "FAILED")]} if first is not None else {}),
    # Why it failed, in the line a reader of this step's output sees. Without it a step that died
    # in 0.4 seconds said only FAILED, and finding "ENOENT: ~/.codex/config.toml" meant replaying
    # the request by hand on another machine (reported from the second install).
    "failure": execution.failure_of(r) if not verdict else verdict,
    "ledger_error": r.get("ledger_error") or "",
    "turns": 1,
    "tool_calls": tool_calls,
    "server_tool_use": server_tool_use,
    "schema_sha256": schema_sha,
    "answer": answer,
    # missing measurements are omitted, never 0; model_usage is the adapter's list as it came
    "measurements": {k: v for k, v in meas.items()
                     if (isinstance(v, (int, float)) and not isinstance(v, bool)) or k == "model_usage"},
})
execution.write(evid, rec)
# The refusal of a login, left where the quota observer looks (#44, trading's measurement): a
# call the vendor turned away for the account's sake is written beside the login's kept reading,
# with its own words, and the next completed call takes it back.
execution.note_refusal(RT["paths"]["logins_root"], provider, login, rec)
print(json.dumps(rec))
