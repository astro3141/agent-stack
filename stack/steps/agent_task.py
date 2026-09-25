"""Conductor script step: one model task through the routing/execution layer.

usage: agent_task.py <provider> <model_route> <label> <prompt-file> <expected-file>
       [<profile> [<login> [<principal>]]]
The prompt file may use {WS} for the run's shared workspace (/ws/<conductor run id>), which
every model step of the run shares, so a later step can read what an earlier one wrote.
Writes are only possible through the Preloop MCP server (native write/shell are removed);
Preloop's rules decide them. Emits the normalized result flat for Conductor.
"""

# What a repeat of this step does (OPERATIONS.md §17): "yes" — the same result;
# "guarded" — it recognises the repeat; "no" — it does the work again.
REPEATABLE = "no"   # a model call: it costs, and the answer is not the same twice
import json, os, subprocess, sys, time
sys.path.insert(0, "/work/stack")
import settings

provider, model_route, label, prompt_file, expected = sys.argv[1:6]
prof_name = sys.argv[6] if len(sys.argv) > 6 and sys.argv[6] else "research-default"
login = sys.argv[7] if len(sys.argv) > 7 and sys.argv[7] else provider
# the principal whose tool rights this step runs with; empty means the adapter's own credential
principal = sys.argv[8] if len(sys.argv) > 8 and sys.argv[8] else ""
RT, PROF = settings.runtime(), settings.profile(prof_name) or {}
run = os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")
ws = f"{RT['paths']['workspace_root']}/{run}"
os.makedirs(ws, exist_ok=True)
run_id = f"{run}-{label}-{provider}"
evid = f"{RT['paths']['evidence_root']}/{run_id}"
os.makedirs(evid, exist_ok=True)


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
            print(json.dumps({
                "status": "FAILED", "provider": provider, "principal": principal,
                "run_id": run_id, "workspace": ws, "produced": False, "produced_stale": False,
                "evidence_dir": evid, "profile": prof_name, "attempts": 0,
                "failure": f"{principal} declares egress of its own, so this step runs as that "
                           f"role's uid — and the login {login!r} belongs to "
                           f"{'uid ' + str(owner) if owner is not None else 'nobody: it is not there'}. "
                           "These CLIs own their credential files: they set the mode, and they "
                           "rewrite it on every token refresh, so group access granted by hand "
                           "lasts until the next one. Connect a login named for this role and run "
                           "the step on it, or drop the role's egress declaration (§50).",
                "measurements": {}}))
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
req = {"run_id": run_id, "provider": provider, "model_route": model_route or "preloop_gateway",
       "login": login, "profile": prof_name,
       **({"mcp_principal": principal} if principal else {}),
       "cwd": ws, "timeout_ms": (PROF.get("execution") or {}).get("timeout_ms", 600000),
       "native_tools": (PROF.get("tools") or {}).get("native_tools", False), "evidence_dir": evid,
       "native_allow": list((PROF.get("tools") or {}).get("native_allow") or []),
       "prompt": open(prompt_file, encoding="utf-8").read().replace("{WS}", ws)}
rp = os.path.join(evid, "request.json")
json.dump(req, open(rp, "w"), indent=1)
def run_once():
    p = subprocess.run(["node", "/work/stack/run-agent.mjs", rp], capture_output=True, text=True,
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
if r.get("status") != "COMPLETED" and "refresh" in msg.lower():
    time.sleep(20)
    r = run_once()
    attempts = 2
q = ((r.get("turn") or {}).get("_meta") or {}).get("quota") or {}
meas = {"total_tokens": (q.get("token_count") or {}).get("totalTokens"), "wall_ms": r.get("wall_ms")}
after = stamp()
# left over from an earlier attempt, untouched by this one: the reader is told, rather than the
# file being deleted — an artifact someone may want to look at is not this step's to destroy
stale = bool(after and after == before)
print(json.dumps({
    "status": r.get("status", "FAILED"),
    "provider": provider,
    "principal": principal,
    "model_route": r.get("model_route") or model_route,
    "run_id": run_id,
    "workspace": ws,
    "produced_path": exp_path,
    "produced": bool(after) and not stale,
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
    # Why it failed, in the line a reader of this step's output sees. Without it a step that died
    # in 0.4 seconds said only FAILED, and finding "ENOENT: ~/.codex/config.toml" meant replaying
    # the request by hand on another machine (reported from the second install).
    "failure": ((r.get("failure") or {}).get("message")
                or (r.get("turn", {}).get("error") or {}).get("message")
                or ("" if r.get("status") == "COMPLETED" else json.dumps(
                    r.get("turn", {}).get("error") or r.get("failure") or {},
                    ensure_ascii=False)[:300]))[:300],
    "ledger_error": r.get("ledger_error") or "",
    # missing measurements are omitted, never 0
    "measurements": {k: v for k, v in meas.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
}))
