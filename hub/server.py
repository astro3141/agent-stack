"""cadp278-hub — the UI. Serves one page, forwards /api/* to the ops API, and puts Conductor's own
run dashboard on the same address. No Docker access, no credentials, no mounts.

Published on 127.0.0.1:8780, and that is the only address a person needs. Everything the page can
do goes through ops' fixed routes; the page reads state from the systems that own it (Conductor's
event log, Preloop, MLflow) via ops, and hands actions to them — it keeps no state of its own.

**Why Conductor's dashboard arrives through here.** It draws a run better than we would, and it can
draw one from an event log this stack already keeps, so it is used rather than re-implemented
(`conductor.web.replay`, MIT). It runs in its own small container because that container needs the
`conductor` package and a read-only mount of the workspace, and this one — the container a browser
talks to — is better off with neither. Its port is not published: the only way in is through this
proxy, which forwards exactly the paths its bundle asks for.

Those paths are absolute (`/assets/…`, `/api/state`), which is why they are matched here by name
rather than mounted under a prefix; none of them collide with this panel's own routes.
"""
import os, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPS = os.environ.get("HUB_OPS_URL", "http://cadp278-ops:8781")
REPLAY = os.environ.get("HUB_REPLAY_URL", "")          # empty: the dashboard is not in this composition
PAGE = open(os.path.join(os.path.dirname(__file__), "index.html"), "rb").read()

# What Conductor's bundle asks for at the root. /api/replay (ours, POST) and /api/replay/info
# (theirs) are different paths, so the split is exact rather than a prefix guess.
REPLAY_EXACT = {"/conductor", "/conductor/", "/favicon.svg", "/api/state", "/api/logs",
                "/api/replay/info"}
REPLAY_PREFIX = ("/assets/", "/api/files/")


def for_replay(path):
    p = path.split("?", 1)[0]
    return p in REPLAY_EXACT or p.startswith(REPLAY_PREFIX)


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"{self.command} {self.path.split('?')[0]} -> {args[1] if len(args) > 1 else ''}", flush=True)

    def _forward(self, base, path, method, ctype="application/json", host=None):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        headers = {"Content-Type": "application/json"}
        if host:
            # Conductor's dashboard refuses a Host header that is not loopback (web/auth.py) —
            # a DNS-rebinding guard aimed at a browser, not at a proxy on its own network. This
            # says what it wants to hear and changes nothing else; the connection still goes to
            # the replay container by name, over the ops network.
            headers["Host"] = host
        req = urllib.request.Request(base + path, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                code, data = r.status, r.read()
                ctype = r.headers.get("Content-Type", ctype)
        except urllib.error.HTTPError as e:
            code, data = e.code, e.read()
            ctype = e.headers.get("Content-Type", ctype) if e.headers else ctype
        except Exception as e:
            code, data = 502, ('{"error": "%s unreachable: %s"}' % (base, type(e).__name__)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _replay(self, method):
        if not REPLAY:
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("the run dashboard is not part of this composition\n".encode())
            return
        path = self.path
        if path.split("?", 1)[0] in ("/conductor", "/conductor/"):
            path = "/"                       # its bundle lives at the root of its own server
        self._forward(REPLAY, path, method, ctype="text/html; charset=utf-8",
                      host=f"127.0.0.1:{REPLAY.rsplit(':', 1)[-1]}")

    def do_GET(self):
        if for_replay(self.path):
            return self._replay("GET")
        if self.path.startswith("/api/"):
            return self._forward(OPS, self.path, "GET")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def do_POST(self):
        if for_replay(self.path):
            return self._replay("POST")
        if self.path.startswith("/api/"):
            return self._forward(OPS, self.path, "POST")
        self.send_response(404); self.end_headers()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8780), H).serve_forever()
