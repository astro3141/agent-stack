"""agentstack-ops — the only component with Docker control. A fixed set of actions over HTTP.

The UI (and anything else) calls this API; it never talks to Docker itself. Each route maps to
one predetermined `docker exec` into a known container, with arguments passed as an argv list
(no shell) and validated first. Adding a capability means adding a route here, deliberately.

Listens on 0.0.0.0:8781 inside its container; compose publishes it on 127.0.0.1 only. That limits
who can reach it, not what it can do: whoever reaches it controls these actions.

Routes
  GET  /api/health
  GET  /api/config/status                 POST /api/config/generate   POST /api/config/apply
  GET  /api/profiles                      GET /api/workflows   what may be started
  GET  /api/accounts?profile=<name>       per provider: login state, quota, account match, eligibility
  POST /api/accounts/<provider>/login     body {"login": optional}     start the official login
  GET  /api/accounts/<provider>/login?login=<name>
  POST /api/accounts/<provider>/code      body {"code": "...", "login": optional}
  POST /api/accounts/<provider>/cancel    body {"login": optional}
  GET  /api/runs                          POST /api/runs  body {"workflow","profile","inputs":{}}
  GET  /api/runs/<ui-id>                  POST /api/runs/<ui-id>/stop   POST /api/runs/<ui-id>/resume
  GET  /api/approvals                     pending approval requests (read-only)
"""
import json, os, re, secrets, subprocess, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

AGENT = os.environ.get("OPS_AGENT_CONTAINER", "agentstack-agent")
# The operator's own commands — the ones that change what the account enforces — run here, on the
# admin side, because the guard refuses those writes from the governed network (OPERATIONS §21).
ADMIN = os.environ.get("OPS_ADMIN_CONTAINER", "agentstack-admin")
PY = "/opt/venv/bin/python"
PROVIDERS = {"claude", "codex", "grok"}
NAME = re.compile(r"[a-z0-9-]{1,40}")


def dexec(args, stdin=None, detach=False, timeout=120, container=None):
    """docker exec into a known container. args is an argv list; nothing is shell-interpreted.

    The default is the agent. `container=ADMIN` is for the commands that change what Preloop
    enforces: they must not run on the governed side, where the guard refuses them.
    """
    cmd = ["docker", "exec"] + (["-d"] if detach else []) + (["-i"] if stdin is not None else []) + [container or AGENT] + args
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def jlocal(args, timeout=60):
    """Run one of this tree's scripts *here*, not in the agent.

    Approvals are the reason this exists. The agent's route to Preloop refuses a decision
    (docker/apiguard.conf), and it should: the party being governed must not answer its own
    request. This container is on the admin side and carries its own credential, so the decision
    is made where the person is (OPERATIONS.md §20).
    """
    r = subprocess.run(["python3"] + args, capture_output=True, text=True, timeout=timeout)
    for cand in (r.stdout.strip(), (r.stdout.strip().splitlines() or [""])[-1]):
        try:
            return json.loads(cand)
        except Exception:
            continue
    return {"error": (r.stderr or r.stdout or f"exit {r.returncode}").strip()[-400:]}


def jexec(args, **kw):
    rc, out, err = dexec(args, **kw)
    for cand in (out.strip(), (out.strip().splitlines() or [""])[-1]):   # whole output, else last line
        try:
            return json.loads(cand)
        except Exception:
            continue
    return {"error": (err or out or f"exit {rc}").strip()[-400:]}


def accounts(profile):
    prof = jexec(["cat", f"/work/config/generated/profiles/{profile}.json"])
    if "error" in prof or "routing" not in prof:
        return {"error": f"unknown profile {profile!r}"}
    routing = prof["routing"]
    # quota observations + the router's own evaluation, with this profile's policy
    obs_dir = f"/tmp/ops-obs-{secrets.token_hex(4)}"
    routes = json.dumps(routing["model_route"])
    logins = json.dumps(routing.get("login") or {})
    ev = jexec(["sh", "-c", 'P281_MODEL_ROUTES="$1" P281_LOGINS="$5" "$2" /work/p281/collect_obs.py "$3" >/dev/null 2>&1; '
                'printf %s "$4" > "$3/policy.json"; "$2" /work/p281/router.py "$3/policy.json" "$3"; rm -rf "$3"',
                "sh", routes, PY, obs_dir, json.dumps(routing), logins], timeout=180)
    evaluated = {e["provider"]: e for e in (ev.get("evaluated") or [])}
    rows = []
    for name in routing["candidates"]:
        login = routing["login"].get(name, name)
        st = jexec([PY, "/work/p281/login_helper.py", "status", name, login])
        e = evaluated.get(name, {})
        rows.append({
            "provider": name, "login": login, "route": routing["model_route"].get(name),
            "connection": st.get("state"), "plan": (st.get("account") or {}).get("plan"),
            "eligible": e.get("eligible"), "why": e.get("why"),
            "observed_at": e.get("observed_at"), "age_s": e.get("age_s"), "source": e.get("source"),
            "identity_basis": e.get("identity_basis"),
            "account_match": None if "why" not in e else not str(e.get("why", "")).startswith("account_mismatch"),
            "session_used": e.get("session_used"), "weekly_used": e.get("weekly_used"),
        })
    return {"profile": profile, "decision": ev.get("decision"), "chosen": ev.get("provider"),
            "reason": ev.get("reason"), "providers": rows}


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20000:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def log_message(self, fmt, *args):
        # never log request bodies (authorization codes); method and path only
        print(f"{self.command} {urlparse(self.path).path} -> {args[1] if len(args) > 1 else ''}", flush=True)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query); p = u.path
        if p == "/api/health":
            return self._send(200, {"ok": True, "agent": AGENT})
        if p == "/api/config/status":
            return self._send(200, jexec([PY, "/work/p281/cfg.py", "status"]))
        if p == "/api/workflows":
            # with what each one says about itself, so the screen offers what exists
            return self._send(200, jexec([PY, "/work/p281/run_workflow.py", "workflows", "--detail"]))
        if p == "/api/profiles":
            rc, out, _ = dexec(["sh", "-c", "ls /work/config/generated/profiles/"])
            names = [x[:-5] for x in out.split() if x.endswith(".json")]
            profs = [jexec(["cat", f"/work/config/generated/profiles/{n}.json"]) for n in names]
            return self._send(200, [{"name": x.get("name"), "description": x.get("description"),
                                     "candidates": (x.get("routing") or {}).get("candidates")} for x in profs])
        if p == "/api/accounts":
            prof = (q.get("profile") or ["research-default"])[0]
            if not NAME.fullmatch(prof):
                return self._send(400, {"error": "invalid profile"})
            return self._send(200, accounts(prof))
        m = re.fullmatch(r"/api/accounts/([a-z]+)/login", p)
        if m:
            prov, login = m.group(1), (q.get("login") or [m.group(1)])[0]
            if prov not in PROVIDERS or not NAME.fullmatch(login):
                return self._send(400, {"error": "invalid provider or login"})
            return self._send(200, jexec([PY, "/work/p281/login_helper.py", "status", prov, login]))
        if p == "/api/runs":
            return self._send(200, jexec([PY, "/work/p281/run_workflow.py", "list"]))
        if p == "/api/approvals":          # what is waiting for a person right now
            return self._send(200, jlocal(["/work/p281/approvals.py"]))
        if p == "/api/overview":
            # One read for the panel: what the stack can do now, how the unattended cycles have
            # been going, what the last check found, and where the other solutions' own consoles
            # are. Nothing here is recomputed — it is what the stack already records.
            health = jexec([PY, "/work/p281/ops_health.py", "--json", "--last", "50"])
            rc, out, _ = dexec(["cat", "/work/evidence/checks/last.json"])
            try:
                last = json.loads(out) if rc == 0 else {}
            except ValueError:
                last = {}
            elsewhere = jexec([PY, "/work/p281/elsewhere.py", "--json"])
            rc2, hs, _ = dexec(["cat", "/work/evidence/ops/host-state.json"])
            try:
                host_state = json.loads(hs) if rc2 == 0 else None
            except ValueError:
                host_state = None
            return self._send(200, {
                "health": health,
                "composition": last.get("composition"),
                # backups and releases live outside every container; this is what the host last
                # wrote down about them (scripts/host-state.sh), shown with its age
                "host_state": host_state,
                # what another console could have changed under us
                "elsewhere": elsewhere,
                # the consoles that own what this panel deliberately does not rebuild
                "links": {
                    "preloop": f"http://127.0.0.1:{os.environ.get('PRELOOP_CONSOLE_PORT', '3000')}",
                    "mlflow": f"http://127.0.0.1:{os.environ.get('MLFLOW_PORT', '5000')}",
                    # runs and traces land in different experiments: the records this stack writes
                    # (p281-routing) and Conductor's OTel spans (the OTEL_SERVICE_NAME the agent
                    # container sets, `agent-stack`; older spans carry the name it had before). The
                    # second one is a dashboard nothing here pointed at until it was reviewed.
                    "mlflow_traces": f"http://127.0.0.1:{os.environ.get('MLFLOW_PORT', '5000')}"
                                     f"/#/experiments/1?compareRunsMode=TRACES",
                }})
        if p == "/api/checks":             # what scripts/up.sh --check last found, and when
            rc, out, _ = dexec(["cat", "/work/evidence/checks/last.json"])
            if rc != 0:
                return self._send(200, {"at": None, "ok": None,
                                        "error": "the checks have not been run since this was added"})
            try:
                return self._send(200, json.loads(out))
            except ValueError:
                return self._send(200, {"at": None, "ok": None, "error": "unreadable check result"})
        m = re.fullmatch(r"/api/runs/([a-z0-9-]{6,40})", p)
        if m:
            return self._send(200, jexec([PY, "/work/p281/run_workflow.py", "show", m.group(1)]))
        return self._send(404, {"error": "no such route"})

    def do_POST(self):
        p = urlparse(self.path).path; b = self._body()
        if p in ("/api/config/generate", "/api/config/apply"):
            # The split follows the guard: generating writes files in this tree and reads the
            # provider logins, which only the agent has; applying writes to Preloop, which only
            # the admin side may do (OPERATIONS §21).
            what = p.rsplit("/", 1)[1]
            return self._send(200, jexec([PY, "/work/p281/cfg.py", what], timeout=300,
                                         container=ADMIN if what == "apply" else None))
        m = re.fullmatch(r"/api/accounts/([a-z]+)/(login|code|cancel)", p)
        if m:
            prov, act = m.groups()
            login = b.get("login") or prov
            if prov not in PROVIDERS or not isinstance(login, str) or not NAME.fullmatch(login):
                return self._send(400, {"error": "invalid provider or login"})
            if act == "login":
                return self._send(200, jexec([PY, "/work/p281/login_helper.py", "start", prov, login], timeout=60))
            if act == "cancel":
                return self._send(200, jexec([PY, "/work/p281/login_helper.py", "cancel", prov, login]))
            code = b.get("code")
            if not isinstance(code, str) or not code.strip() or len(code) > 2000:
                return self._send(400, {"error": "missing code"})
            return self._send(200, jexec([PY, "/work/p281/login_helper.py", "code", prov, login], stdin=code))
        if p == "/api/replay":
            # Not a control over the stack: it chooses which recorded run the read-only dashboard
            # shows. The name is written for the replay container to pick up; nothing is executed.
            ui = b.get("ui")
            if not isinstance(ui, str) or not re.fullmatch(r"[a-z0-9-]{6,40}", ui):
                return self._send(400, {"error": "invalid run id"})
            rc, out, err = dexec(["sh", "-c",
                                  f"test -d /work/evidence/ui-runs/{ui} && "
                                  f"printf %s {ui} > /work/evidence/ops/replay.run && echo ok"])
            if rc != 0 or "ok" not in out:
                return self._send(404, {"error": "no such run"})
            # the panel's own address — the dashboard is proxied by the hub, not published
            return self._send(200, {"ui": ui, "url": "/conductor",
                                    "note": "the dashboard switches within a couple of seconds"})
        m = re.fullmatch(r"/api/runs/([a-z0-9-]{6,40})/stop", p)
        if m:
            # Stopping a run that is going is a person's call — the same kind of decision as an
            # approval, and the only other one this panel makes. Conductor does the stopping.
            return self._send(200, jexec([PY, "/work/p281/run_workflow.py", "stop", m.group(1)]))
        m = re.fullmatch(r"/api/runs/([a-z0-9-]{6,40})/resume", p)
        if m:
            # The other half of stopping. Whether an interrupted run is worth continuing is the
            # same kind of judgement as stopping it was, so it is offered in the same place.
            # Detached, like a start: resuming re-enters the step that did not finish and runs on.
            rc, out, err = dexec([PY, "/work/p281/run_workflow.py", "resume", m.group(1)], detach=True)
            if rc != 0:
                return self._send(502, {"error": (err or out or "could not resume").strip()[-300:]})
            return self._send(200, {"ui": m.group(1), "resuming": True})
        m = re.fullmatch(r"/api/approvals/([0-9a-f-]{36})", p)
        if m:
            # Preloop owns the decision; this panel is where the person makes it, because an
            # approval is the one thing here that cannot proceed without one. Everything else an
            # operator does to this stack is a command, not a button (see the panel's own note).
            # It runs *here*, with this container's own credential: the agent may read what is
            # waiting but its route refuses the decision (OPERATIONS.md §20).
            d = b.get("decision")
            if d not in ("approve", "decline"):
                return self._send(400, {"error": "decision must be approve or decline"})
            comment = b.get("comment") or ""
            if not isinstance(comment, str) or len(comment) > 500:
                return self._send(400, {"error": "comment must be a string of at most 500 chars"})
            out = jlocal(["/work/p281/approvals.py", "decide", m.group(1), d, comment])
            return self._send(200 if out.get("ok") else 502, out)
        if p == "/api/runs":
            wf, prof, inputs = b.get("workflow"), b.get("profile") or "research-default", b.get("inputs") or {}
            # what may be started is the runner's answer, not a second list kept here: a package
            # installed under packages/ is startable from the panel the moment it is there
            allowed = jexec([PY, "/work/p281/run_workflow.py", "workflows"])
            if not isinstance(allowed, dict) or "error" in allowed:
                return self._send(502, {"error": "could not read which workflows may be started"})
            if wf not in allowed or not NAME.fullmatch(prof) or not isinstance(inputs, dict):
                return self._send(400, {"error": "invalid workflow, profile or inputs"})
            # The run is started detached, so what the stack cannot do has to be found out before
            # that: a refusal after detaching would look like a run that never reported anything.
            unrecorded = b.get("allow_unrecorded") is True
            gate = jexec([PY, "/work/p281/capabilities.py", "--missing"]
                         + (["--allow-unrecorded"] if unrecorded else []))
            if gate.get("missing"):
                return self._send(409, {"error": "the stack cannot run this now: "
                                                 + ", ".join(gate["missing"]), **gate})
            ui = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
            pairs = [f"{k}={v}" for k, v in inputs.items() if isinstance(v, (str, int))]
            rc, out, err = dexec([PY, "/work/p281/run_workflow.py", "start", ui, wf, prof] + pairs
                                 + (["--allow-unrecorded"] if unrecorded else []), detach=True)
            return self._send(202 if rc == 0 else 500, {"ui_id": ui} if rc == 0 else {"error": err[-300:]})
        return self._send(404, {"error": "no such route"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8781), H).serve_forever()
