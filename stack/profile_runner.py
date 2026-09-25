"""The runner inside an egress-profile container: it executes exactly one thing, told by the broker.

Listens on the dispatch network only — its container is attached to that network and the broker is
the only other member that speaks to runners, so a step in the main agent has no route here
(OPERATIONS §53). And it does not trust its caller anyway: the argv is built *here*, from fields,
around one pinned entrypoint. A request is data; the only program a runner will ever start is
`agent_task.py`.

What a job carries and what it does not: role, provider, label, the prompt text, the expected file
— and an opaque job token the broker minted. **No credential.** The adapter presents the token to
the broker's MCP forward, and the broker swaps it for the real principal credential that never
leaves the broker's process (§53). A token stolen from this container's process list is a claim on
one role's rights for one job's lifetime, not a credential.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PY = "/opt/venv/bin/python"
STEP = "/work/stack/steps/agent_task.py"
PROFILE = os.environ.get("AGENTSTACK_EGRESS_PROFILE", "")
NAME = re.compile(r"[a-z][a-z0-9-]{0,39}")
SAFE = re.compile(r"[A-Za-z0-9._\- ]{1,200}")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ok": True, "profile": PROFILE})
        return self._send(404, {"error": "unknown"})

    def do_POST(self):
        if self.path != "/run":
            return self._send(404, {"error": "unknown"})
        try:
            n = int(self.headers.get("content-length") or 0)
            job = json.loads(self.rfile.read(n))
        except Exception:
            return self._send(400, {"error": "a job is one JSON object"})
        # the broker said which profile it meant; a job routed to the wrong runner is refused,
        # never quietly run under a different list
        if job.get("profile") != PROFILE:
            return self._send(409, {"error": f"this runner is profile {PROFILE!r}, "
                                             f"the job says {job.get('profile')!r}"})
        for k in ("role", "provider", "login"):
            if not NAME.fullmatch(str(job.get(k) or "")):
                return self._send(400, {"error": f"invalid {k}"})
        # a label is the workflow's word for its own lane (E1, story, m1-claude): the run id and
        # evidence path carry it, so it is a filename-safe token, not a role name
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", str(job.get("label") or "")):
            return self._send(400, {"error": "invalid label"})
        for k in ("run_id", "profile_name"):
            if not SAFE.fullmatch(str(job.get(k) or "")):
                return self._send(400, {"error": f"invalid {k}"})
        # `expected` is a path relative to the run's workspace, and a workflow may keep it in a
        # subdirectory (devflow writes devflow/research.json — refused here as "invalid expected"
        # until this allowed the separator). Relative, and never stepping out of the workspace.
        exp = str(job.get("expected") or "")
        if not re.fullmatch(r"[A-Za-z0-9._\- /]{1,200}", exp) or exp.startswith("/") or ".." in exp:
            return self._send(400, {"error": "invalid expected"})
        prompt = str(job.get("prompt") or "")
        if not prompt or len(prompt) > 200000:
            return self._send(400, {"error": "prompt text is required (and bounded)"})
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as f:
            f.write(prompt)
            pf = f.name
        env = {**os.environ,
               "CONDUCTOR_SELF_RUN_ID": str(job["run_id"]),
               # the adapter's brokered path (run-agent.mjs): MCP goes to the broker's forward,
               # authenticated by the opaque job token — the credential stays with the broker
               "AGENTSTACK_MCP_URL": str(job.get("mcp_url") or ""),
               "AGENTSTACK_JOB_TOKEN": str(job.get("job_token") or "")}
        argv = [PY, STEP, job["provider"], str(job.get("model_route") or "direct"),
                job["label"], pf, job["expected"], job["profile_name"], job["login"],
                job["role"]]
        try:
            r = subprocess.run(argv, capture_output=True, text=True,
                               timeout=int(job.get("timeout_s") or 900), env=env)
            last = (r.stdout.strip().splitlines() or ["{}"])[-1]
            try:
                out = json.loads(last)
            except ValueError:
                out = {"status": "FAILED", "error": (r.stderr or r.stdout)[-400:]}
            return self._send(200, {"result": out, "profile": PROFILE})
        except subprocess.TimeoutExpired:
            return self._send(200, {"result": {"status": "TIMED_OUT"}, "profile": PROFILE})
        finally:
            try:
                os.unlink(pf)
            except OSError:
                pass


if __name__ == "__main__":
    port = int(os.environ.get("AGENTSTACK_RUNNER_PORT", "8790"))
    print(f"profile runner: {PROFILE} on {port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
