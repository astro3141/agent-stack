"""Claim a fresh Preloop instance, so the stack can bring itself up.

usage:
  bootstrap_preloop.py --unclaimed [--api URL] [--username U] [--email E]
                       [--secrets-file PATH] [--agent-kinds claude-code,codex] [--no-onboard]
  (the bootstrap token is read from stdin)

Preloop is *ours* — a container this stack starts. Its first user is created against localhost
with the bootstrap token the install already holds, and nobody has to decide anything, so it is
the stack's work rather than the operator's (agent-stack issue #6). A provider login is the
opposite: a third party's account, on the vendor's page, tied to a person; that stays theirs.

**The caller must assert `--unclaimed`, and this refuses without it.** The reason is a sharp edge
in `POST /api/v1/auth/register`: while the instance has no users the bootstrap token gates it, but
once it has one, `REGISTRATION_ENABLED` (true by default) lets the same call through and it creates
a **second account** whose user is that account's owner — a second tenant, silently. `scripts/up.sh`
establishes the fact by counting rows in Preloop's own `user` table before calling this.

The password is generated here, never chosen and never printed: it goes to `--secrets-file` with
mode 0600, git-ignored, and this prints only that path. The operator needs it for the console, which
is the one place a person still signs in.

What a repeat does (OPERATIONS.md §17): REPEATABLE = "guarded" — a claimed instance is reported as
already claimed and nothing is written.
"""
REPEATABLE = "guarded"
import json, os, secrets, subprocess, sys, urllib.error, urllib.request

DEFAULT_API = os.environ.get("P281_PRELOOP_API") or "http://api:8000"


def call(api, path, body=None, token=None, method=None):
    d = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = "Bearer " + token
    req = urllib.request.Request(api + path, data=d, method=method or ("POST" if d else "GET"),
                                 headers=h)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            t = r.read().decode()
            return r.status, (json.loads(t) if t.strip() else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf8", "replace")
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"detail": body[:300]}


def write_secrets(path, username, email, password):
    """The password a person needs for the console, written where the caller said.

    The default is a path inside this container, not the repository: the tree is a bind mount
    owned by the host user, and a container writing into it fails on Linux with "Permission
    denied" (measured). `scripts/up.sh` takes the file from here and puts it beside the other
    operator secrets, as the host user, with the host's own permissions.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Preloop's own account, created by scripts/up.sh on a fresh instance.\n")
        f.write("# The console is the one place a person still signs in (OPERATIONS.md §22).\n")
        f.write(f"PRELOOP_OWNER_USERNAME={username}\n")
        f.write(f"PRELOOP_OWNER_EMAIL={email}\n")
        f.write(f"PRELOOP_OWNER_PASSWORD={password}\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass          # a bind mount from a Windows host refuses the mode; see principals.py


def claim(api, username, email, bootstrap_token, secrets_file):
    """Create the first user and return the API key the CLI will use."""
    password = secrets.token_urlsafe(24)
    # Written before the account exists, not after. The first version wrote it last, and on the
    # Linux runner the write failed *after* registration had succeeded: an account existed whose
    # password nobody would ever know. A file for an account that was never created is harmless
    # and is removed below; the other way round is not recoverable.
    write_secrets(secrets_file, username, email, password)
    code, r = call(api, "/api/v1/auth/register",
                   {"username": username, "email": email, "password": password,
                    "bootstrap_token": bootstrap_token})
    if code >= 400:
        try:
            os.unlink(secrets_file)
        except OSError:
            pass
    if code == 400 and "already" in json.dumps(r).lower():
        return None, {"ok": True, "already": True, "detail": "a user with that name or email exists"}
    if code >= 400:
        return None, {"ok": False, "stage": "register", "status": code, "detail": r.get("detail")}

    code, tok = call(api, "/api/v1/auth/token/json", {"username": username, "password": password})
    if code >= 400 or not tok.get("access_token"):
        return None, {"ok": False, "stage": "sign in", "status": code, "detail": tok.get("detail")}

    code, key = call(api, "/api/v1/auth/api-keys", {"name": "stack-bootstrap"},
                     token=tok["access_token"])
    api_key = key.get("key") or key.get("token") or key.get("api_key")
    if code >= 400 or not api_key:
        return None, {"ok": False, "stage": "credential", "status": code,
                      "detail": key.get("detail") or sorted(key)}

    return api_key, None


def onboard(api, api_key, agent_kinds):
    """Let the Preloop CLI create each agent's managed identity, credential and permission hook.

    The CLI reads `$HOME/.claude/settings.json` and fails outright if it is not there. The image
    ships none and the home is a volume, so on a fresh machine it is not there — measured, both
    ways round. An empty object is enough for onboarding to proceed; what goes in it afterwards is
    the agent's own configuration, not this step's business.

    **Every vendor this stack routes to, not only Claude.** On the second machine a fresh install
    onboarded claude-code and nothing else, so `~/.codex/config.toml` had no Preloop entry and
    every codex lane died in under a second — silently, because the step dropped the reason
    (OPERATIONS §31). Onboarding here also means it happens on the admin side, which is the only
    side allowed to create an agent at all: from the governed network the guard answers 403, and
    that is the boundary working, not a problem to route around.
    """
    cfg_dir = os.path.join(os.path.expanduser("~"), ".claude")
    cfg = os.path.join(cfg_dir, "settings.json")
    if not os.path.exists(cfg):
        os.makedirs(cfg_dir, exist_ok=True)
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({}, f)
    r = subprocess.run(["preloop", "auth", "login", "--token", api_key, "--url", api, "--force"],
                       capture_output=True, text=True, timeout=300)
    if r.returncode:
        # never echo the argv: it carries the credential
        return {"ok": False, "stage": "auth login", "detail": (r.stderr or r.stdout).strip()[-300:]}
    failed = {}
    for kind in agent_kinds:
        r = subprocess.run(["preloop", "agents", "onboard", kind, "--approvals", "--yes",
                            "--live-validate=false"], capture_output=True, text=True, timeout=300)
        if r.returncode:
            # one vendor's CLI missing must not stop the others: a composition may not have it
            failed[kind] = (r.stderr or r.stdout).strip()[-200:]
    if len(failed) == len(agent_kinds):
        return {"ok": False, "stage": "agents onboard", "detail": failed}
    return {"partial": failed} if failed else None


def main(argv):
    if "--unclaimed" not in argv:
        print(json.dumps({"ok": False, "error": "refusing to register without --unclaimed: on an "
                                                "instance that already has a user this would "
                                                "create a second account, not a second member"}))
        return 2
    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default
    api = opt("--api", DEFAULT_API).rstrip("/")
    username = opt("--username", os.environ.get("PRELOOP_OWNER_USERNAME", "owner"))
    # No real address is invented for the operator: this account exists so the stack can run, and
    # a person who wants mail from it can change it in the console. Preloop insists the value be
    # shaped like an address and rejects the reserved suffixes (`localhost`, `.local`, `.invalid`
    # were all refused; `.internal` is accepted), so the default is one that resolves nowhere.
    email = opt("--email", os.environ.get("PRELOOP_OWNER_EMAIL", "owner@agent-stack.internal"))
    # inside this container by default; the caller moves it (see write_secrets)
    secrets_file = opt("--secrets-file", "/tmp/preloop-owner.env")
    bootstrap_token = sys.stdin.read().strip()
    if not bootstrap_token:
        print(json.dumps({"ok": False, "error": "no bootstrap token on stdin — PRELOOP_BOOTSTRAP_TOKEN "
                                                "is set on Preloop's own api container"}))
        return 2

    api_key, problem = claim(api, username, email, bootstrap_token, secrets_file)
    if problem:
        print(json.dumps(problem, ensure_ascii=False))
        return 0 if problem.get("ok") else 1
    out = {"ok": True, "user": username, "secrets_file": secrets_file, "onboarded": False}
    if "--no-onboard" not in argv:
        kinds = [k for k in opt("--agent-kinds", "claude-code,codex").split(",") if k]
        problem = onboard(api, api_key, kinds)
        if problem and "partial" in problem:
            out["onboarded_partially"] = problem["partial"]
            problem = None
        if problem:
            problem["user_created"] = username
            problem["secrets_file"] = secrets_file
            print(json.dumps(problem, ensure_ascii=False))
            return 1
        out["onboarded"] = True
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
