"""The broker: the one process that holds the Preloop principal credentials and the dispatch right.

Runs in its own container under its own uid — one broker, not one per role — so nothing a step can
do reaches its memory or its files: uid 1000 cannot read another uid's 0600 file and cannot trace
another uid's process (measured, OPERATIONS §48). No vendor CLI ever runs as this uid, which is what
kept per-role uids poisonous in §48–§50: the poison was CLIs meeting foreign uids, and the broker
never runs one.

Two jobs (§53):

  POST /dispatch      run one model step as a role, in the egress profile that role is declared to
                      use. The role→profile map is read HERE, from the same declarations that carry
                      the role's tool rules — never from the caller. The argv is pinned by the
                      runner. What the caller chooses is which declared role runs; what it cannot
                      choose is where, or with what.

  POST /mcp/v1        the MCP forward. A dispatched step authenticates with an opaque per-job token;
                      this endpoint swaps it for the role's real Preloop credential and forwards to
                      the console. The credential exists in exactly one process: this one. A stolen
                      token is a claim on one role's rights for one job's lifetime — and §53 says
                      plainly that two roles sharing one profile can steal each other's tokens; map
                      roles that must not do that to different profiles.

Who may call /dispatch is the honest limit (§51): anything on the governed network, which includes
steps. The containment is what a forged dispatch can obtain — a governed model step, as a declared
role, under that role's rules, inside that role's profile — which is what a workflow could ask for
legitimately. Spend, not escalation. Tightening the caller side is the remaining slice.
"""
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, "/work/stack")

CONSOLE_MCP = os.environ.get("AGENTSTACK_CONSOLE_MCP", "http://console/mcp/v1")
SELF_MCP = os.environ.get("AGENTSTACK_BROKER_MCP", "http://broker:8791/mcp/v1")
RUNNER_PORT = int(os.environ.get("AGENTSTACK_RUNNER_PORT", "8790"))
NAME = re.compile(r"[a-z][a-z0-9-]{0,39}")

JOBS = {}          # token -> {"role", "born", "done"}
JOBS_LOCK = threading.Lock()
TOKEN_TTL_S = 3600


def provisioned():
    """The egress profiles this instance actually has — the operator's artifacts, read from disk.

    A profile is the stack's to own (§57): its allowlist file and its proxy/runner pair are created
    at bring-up, like the shared allowlist in §45. A package may *reference* one by name in a
    role's declaration; it cannot create or widen one by declaring harder. So the set of names that
    exist is read from what the operator provisioned, never from what anyone requested."""
    import glob
    return sorted(os.path.basename(f)[:-len(".allow")]
                  for f in glob.glob("/work/docker/egress/profiles/*.allow"))


def mapping():
    """{role: profile} — read from the declarations, at call time, never from a request."""
    import importlib
    import principals as pr
    importlib.reload(pr)
    out = {}
    for role, spec in (pr.declared() or {}).items():
        prof = str((spec or {}).get("egress_profile") or "")
        if prof and NAME.fullmatch(prof) and NAME.fullmatch(str(role)):
            out[str(role)] = prof
    return out


def credential(role):
    """The role's Preloop credential, from this process's environment and nowhere else."""
    v = os.environ.get("PRELOOP_MCP_" + role.upper().replace("-", "_"))
    if not v:
        return None
    return v if v.startswith("Bearer ") else "Bearer " + v


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj, headers=()):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path == "/health":
            with JOBS_LOCK:
                live = sum(1 for j in JOBS.values() if not j["done"])
            return self._send(200, {"ok": True, "map": mapping(),
                                    "profiles_provisioned": provisioned(), "jobs_live": live})
        return self._send(404, {"error": "unknown"})

    def do_POST(self):
        if self.path == "/dispatch":
            return self._dispatch()
        if self.path == "/mcp/v1":
            return self._forward()
        return self._send(404, {"error": "unknown"})

    def _dispatch(self):
        try:
            n = int(self.headers.get("content-length") or 0)
            req = json.loads(self.rfile.read(n))
        except Exception:
            return self._send(400, {"error": "a dispatch is one JSON object"})
        role = str(req.get("role") or "")
        m = mapping()
        if role not in m:
            return self._send(403, {"error": f"role {role!r} declares no egress_profile — "
                                             "the broker dispatches only mapped roles"})
        profile = m[role]
        if req.get("profile") and req["profile"] != profile:
            # the caller does not choose where a role runs; saying so beats ignoring it
            return self._send(403, {"error": f"role {role!r} is declared to run in "
                                             f"{profile!r}, not {req['profile']!r}"})
        have = provisioned()
        if profile not in have:
            # the ownership line, spoken where it is crossed: the package chose a name, and only
            # the operator makes names exist
            return self._send(501, {"error": f"role {role!r} is mapped to profile {profile!r}, "
                                             f"which this instance does not provision. Profiles "
                                             f"are the operator's: this instance has "
                                             f"{have or 'none'}. Add the profile (docker/egress/"
                                             "profiles/, compose) or remap the role (§57)."})
        if credential(role) is None:
            return self._send(503, {"error": f"the broker holds no credential for {role!r}"})
        token = secrets.token_urlsafe(24)
        with JOBS_LOCK:
            JOBS[token] = {"role": role, "born": time.time(), "done": False}
        job = {"role": role, "profile": profile, "profile_name":
               str(req.get("profile_name") or "research-default"),
               "provider": str(req.get("provider") or "claude"),
               "model_route": str(req.get("model_route") or "direct"),
               "login": str(req.get("login") or req.get("provider") or "claude"),
               "label": str(req.get("label") or "b1"),
               "prompt": str(req.get("prompt") or ""),
               "expected": str(req.get("expected") or "out.txt"),
               "run_id": str(req.get("run_id") or f"broker-{int(time.time())}"),
               "timeout_s": int(req.get("timeout_s") or 900),
               "job_token": token, "mcp_url": SELF_MCP}
        try:
            r = urllib.request.Request(f"http://runner-{profile}:{RUNNER_PORT}/run",
                                       data=json.dumps(job).encode(),
                                       headers={"content-type": "application/json"})
            with urllib.request.urlopen(r, timeout=job["timeout_s"] + 30) as x:
                out = json.loads(x.read())
        except Exception as e:
            out = {"error": f"the {profile!r} runner did not answer: {type(e).__name__}"}
        finally:
            with JOBS_LOCK:
                JOBS[token]["done"] = True   # a token lives exactly as long as its job
        return self._send(200, {"dispatched": {"role": role, "profile": profile,
                                               "run_id": job["run_id"]}, **out})

    def _forward(self):
        auth = (self.headers.get("Authorization") or "").replace("Bearer ", "", 1).strip()
        now = time.time()
        with JOBS_LOCK:
            job = JOBS.get(auth)
            if job and (job["done"] or now - job["born"] > TOKEN_TTL_S):
                job = None
        if not job:
            return self._send(401, {"error": "not a live job token"})
        cred = credential(job["role"])
        if cred is None:
            return self._send(503, {"error": "the broker lost the role's credential"})
        n = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(n)
        headers = {"content-type": self.headers.get("content-type", "application/json"),
                   "accept": self.headers.get("accept",
                                              "application/json, text/event-stream"),
                   "Authorization": cred}
        sid = self.headers.get("mcp-session-id")
        if sid:
            headers["mcp-session-id"] = sid
        try:
            r = urllib.request.Request(CONSOLE_MCP, data=body, headers=headers)
            with urllib.request.urlopen(r, timeout=900) as x:
                raw = x.read()
                ct = x.headers.get("content-type", "application/json")
                out_sid = x.headers.get("mcp-session-id")
                code = x.status
        except urllib.error.HTTPError as e:
            raw, ct, out_sid, code = e.read(), "application/json", None, e.code
        except Exception as e:
            return self._send(502, {"error": f"console unreachable: {type(e).__name__}"})
        self.send_response(code)
        self.send_header("content-type", ct)
        self.send_header("content-length", str(len(raw)))
        if out_sid:
            self.send_header("mcp-session-id", out_sid)
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    held = sorted(k[len("PRELOOP_MCP_"):] for k in os.environ if k.startswith("PRELOOP_MCP_"))
    print(f"broker: uid={os.getuid()} credentials held for {len(held)} roles; "
          f"map={mapping()}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8791), H).serve_forever()
