"""Role principals: the identities a workflow's steps run as, and the rights each one carries.

usage:
  principals.py apply [--dry-run]            make Preloop match config/principals.yaml
  principals.py list                         what exists, and what each may do
  principals.py create <name>                a principal and its credential (prints the env line)
  principals.py rules <name> <spec.json>     replace that principal's tool rules
  principals.py check <name>                 what its credential can and cannot do, measured

Why this exists at all: tool rights in Preloop are per **subject** — a credential, or the managed
agent behind it — never per step. A step gets its own rights by running as its own principal, and
`steps/roles.py` is where a workflow says which role uses which (`story=codex:novel-reviewer`).
The vendor and the principal are chosen separately, so three vendors can share one reviewer's
rights, which is what the novel workflow does.

`apply` is what a bring-up runs: the identities and their rights are declared in
`config/principals.yaml`, so a fresh machine gets the same governance as this one instead of
whatever somebody set by hand. It creates what is missing, replaces rules that differ, and leaves
what already agrees — and it mints a credential only for a principal that has none.

**A credential is never printed to a log or committed.** `create` prints the line to put in
`docker/principals.env` (git-ignored, read by the agent container as environment); the adapter
takes it from the environment and records only the principal's name. A credential that is not in
that file simply is not available, and a step that asks for it fails closed.
"""
import glob, hashlib, json, os, sys, urllib.error, urllib.request

sys.path.insert(0, "/work/stack")
import settings

API = settings.runtime()["preloop"]["api_url"]
MCP = settings.runtime()["preloop"]["mcp_url"]
PREFIX = "Role: "


def token():
    return json.load(open(glob.glob(os.path.expanduser(
        "~/.preloop/agents/*/permission_hook.json"))[0], encoding="utf-8"))["token"]


def api(method, path, body=None):
    d = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(API + path, data=d, method=method,
                               headers={"Authorization": "Bearer " + token(),
                                        "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as x:
            t = x.read().decode()
            return json.loads(t) if t.strip() else {"ok": x.status}
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read()[:300].decode("utf8", "replace")}


def principals():
    rows = api("GET", "/api/v1/agents")
    rows = rows if isinstance(rows, list) else rows.get("items") or []
    return {r["display_name"][len(PREFIX):]: r["id"] for r in rows
            if str(r.get("display_name", "")).startswith(PREFIX)}


def env_name(name):
    return "PRELOOP_MCP_" + name.upper().replace("-", "_")


def cmd_list():
    want = declared()
    for name, aid in sorted(principals().items()):
        cfg = (api("GET", f"/api/v1/agents/{aid}/governance") or {}).get("config") or {}
        rules = cfg.get("tool_rules") or {}
        off = [t for t, v in (cfg.get("tool_enabled_overrides") or {}).items() if v is False]
        has = os.environ.get(env_name(name)) is not None
        mark = "" if name in want else "   UNDECLARED — no package or config asks for this one"
        print(f"{name:<18} {aid}  credential in the environment: {'yes' if has else 'NO'}{mark}")
        for tool, rs in rules.items():
            for r in rs:
                print(f"    {tool}: {r.get('action')} when "
                      f"{r.get('condition_expression') or '(anything else)'}")
        if off:
            print(f"    disabled: {', '.join(off)}")


def cmd_create(name):
    # Preloop composes the credential's name as "Managed Agent Credential: <display> / <name>"
    # into a varchar(100); a long display name fails with a 500, so the display name is kept short.
    a = api("POST", "/api/v1/agents", {"display_name": PREFIX + name, "agent_kind": "claude_code"})
    if "id" not in a:
        print(json.dumps(a)); return 1
    c = api("POST", f"/api/v1/agents/{a['id']}/credentials",
            {"name": f"{name}-mcp"[:40], "scopes": ["mcp:read", "mcp:write"]})
    if "token" not in c:
        print(json.dumps(c)); return 1
    print(f"# {name}: {a['id']}  (sha12 {hashlib.sha256(c['token'].encode()).hexdigest()[:12]})")
    print(f"# put this line in docker/principals.env, then: scripts/up.sh")
    print(f"{env_name(name)}={c['token']}")
    return 0


ENV_FILE = "/work/docker/principals.env"


def credentials_of(aid):
    r = api("GET", f"/api/v1/agents/{aid}/credentials")
    rows = r if isinstance(r, list) else ((r or {}).get("items") or (r or {}).get("credentials") or [])
    return [c for c in rows if isinstance(c, dict)]


def has_credential(aid, name):
    """Live in Preloop *and* named in the env file — either missing and the pair is unusable."""
    live = any(c.get("status") not in ("revoked", "expired") for c in credentials_of(aid))
    try:
        in_file = any(l.startswith(env_name(name) + "=") for l in open(ENV_FILE, encoding="utf-8"))
    except OSError:
        in_file = False
    return live and in_file


def credential_name(aid, name):
    """A name Preloop will accept: it refuses a duplicate, including a revoked one's."""
    taken = {c.get("name") for c in credentials_of(aid)}
    base = f"{name}-mcp"[:36]
    if base not in taken:
        return base
    return next(f"{base}-{n}" for n in range(2, 99) if f"{base}-{n}" not in taken)


def declared():
    """What this stack declares, plus what each installed package brings with it.

    A package that names a principal in its steps also declares what that principal may do, in its
    own principals.yaml — so installing a workflow is enough for its identities to exist with
    rights of their own (stack/packages.py, OPERATIONS §27). The stack's own declarations win a
    name clash, and a clash between two packages is reported rather than resolved silently.
    """
    import yaml
    path = "/work/config/principals.yaml"
    own = {}
    if os.path.exists(path):
        own = (yaml.safe_load(open(path, encoding="utf-8")) or {}).get("principals") or {}
    try:
        sys.path.insert(0, "/work/stack")
        import packages
        from_packages, conflicts = packages.principals()
    except Exception:
        from_packages, conflicts = {}, []
    merged = {who: spec["spec"] for who, spec in from_packages.items() if who not in own}
    merged.update(own)
    if conflicts:
        print(json.dumps({"warning": "packages disagree about a principal", "conflicts": conflicts},
                         ensure_ascii=False), file=sys.stderr)
    return merged


def cmd_apply(dry_run=False):
    """Make Preloop match the declaration. Idempotent: a second run changes nothing."""
    want = declared()
    if not want:
        print(json.dumps({"ok": True, "declared": 0, "note": "no config/principals.yaml"})); return 0
    have = principals()
    changes, env_lines = [], []
    for name, spec in sorted(want.items()):
        rules = spec.get("tool_rules") or {}
        aid = have.get(name)
        if not aid:
            if dry_run:
                changes.append({"principal": name, "would": "create"}); continue
            a = api("POST", "/api/v1/agents", {"display_name": PREFIX + name,
                                               "agent_kind": "claude_code"})
            if "id" not in a:
                print(json.dumps({"ok": False, "principal": name, "stage": "create", "detail": a}))
                return 1
            aid = a["id"]
            changes.append({"principal": name, "did": "created"})
        cfg = api("GET", f"/api/v1/agents/{aid}/governance")
        cfg = (cfg or {}).get("config") or {}
        if (cfg.get("tool_rules") or {}) != rules:
            if dry_run:
                changes.append({"principal": name, "would": "set rules"})
            else:
                cfg["tool_rules"] = rules
                r = api("PUT", f"/api/v1/agents/{aid}/governance", cfg)
                if "error" in (r or {}):
                    print(json.dumps({"ok": False, "principal": name, "stage": "rules", "detail": r}))
                    return 1
                changes.append({"principal": name, "did": "rules set"})
        # A credential only when there is none: this is the one part that is a secret, and
        # re-minting would leave the old one live while the env file pointed at the new one.
        # Whether one exists is asked of Preloop and of the env file — never of this process's
        # own environment, which differs by container (the file is mounted in the agent, and
        # `apply` runs on the admin side).
        if not dry_run and not has_credential(aid, name):
            c = api("POST", f"/api/v1/agents/{aid}/credentials",
                    {"name": credential_name(aid, name), "scopes": ["mcp:read", "mcp:write"]})
            if "token" not in c:
                print(json.dumps({"ok": False, "principal": name, "stage": "credential",
                                  "detail": c})); return 1
            env_lines.append(f"{env_name(name)}={c['token']}")
            changes.append({"principal": name, "did": "credential minted",
                            "sha12": hashlib.sha256(c["token"].encode()).hexdigest()[:12]})
    out_file = ""
    if env_lines:
        # Written here, inside this container, and not into the tree: the repository is a bind
        # mount owned by the host user, and a container writing into it fails on Linux with
        # "Permission denied" (measured on a runner). scripts/up.sh appends this to
        # docker/principals.env as the host user, and removes it.
        out_file = "/tmp/principals-new.env"
        with open(out_file, "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(chr(10).join(env_lines) + chr(10))
        try:
            os.chmod(out_file, 0o600)
        except OSError:
            # losing a credential Preloop has already issued over a failed chmod is the worse
            # outcome; the file's protection is the host's once it is moved
            pass
    # An identity outlives the declaration that asked for it. `apply` creates and updates; it has
    # never removed, and a package that stops being declared leaves its principals behind with
    # their rights and their credentials still live — measured the day devflow moved out of this
    # repository: the package was gone from config/packages.yaml and `Role: devflow-reviewer` was
    # still there, still able to write. Reported, never deleted: deleting an identity is the
    # operator's to do, and a report that names one is what makes it their decision instead of
    # nobody's (OPERATIONS §35, §40).
    orphans = sorted(set(have) - set(want))
    print(json.dumps({"ok": True, "declared": len(want), "changes": changes,
                      "undeclared": orphans,
                      "undeclared_note": ("these identities exist in Preloop and no declaration "
                                          "names them — a package that was removed leaves them "
                                          "behind; `principals.py list` shows what each may still "
                                          "do, and removing one is yours to do"
                                          if orphans else ""),
                      "restart_needed": bool(env_lines), "credentials_at": out_file,
                      "note": ("new credentials are waiting in the admin container — scripts/up.sh "
                               "puts them in docker/principals.env") if env_lines else ""},
                     ensure_ascii=False))
    return 0


def cmd_rules(name, spec_path):
    aid = principals().get(name)
    if not aid:
        print(json.dumps({"error": f"no principal named {name}"})); return 1
    cfg = api("GET", f"/api/v1/agents/{aid}/governance")["config"]
    cfg["tool_rules"] = json.load(open(spec_path, encoding="utf-8"))
    r = api("PUT", f"/api/v1/agents/{aid}/governance", cfg)
    print(json.dumps((r.get("config") or {}).get("tool_rules"), ensure_ascii=False))
    return 0


def cmd_check(name):
    """What this principal's credential can actually do — asked, not assumed."""
    tok = os.environ.get(env_name(name))
    if not tok:
        print(json.dumps({"error": f"{env_name(name)} is not in the environment"})); return 1
    def call(tool, args):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": tool, "arguments": args}}
        r = urllib.request.Request(MCP, data=json.dumps(body).encode(), method="POST",
                                   headers={"Authorization": "Bearer " + tok,
                                            "Content-Type": "application/json",
                                            "Accept": "application/json, text/event-stream"})
        try:
            with urllib.request.urlopen(r, timeout=60) as x:
                raw = x.read().decode("utf8", "replace")
        except urllib.error.HTTPError as e:
            return f"HTTP {e.code}"
        for line in raw.splitlines():
            if line.startswith("data:"):
                raw = line[5:].strip(); break
        d = json.loads(raw)
        c = (d.get("result") or {}).get("content") or d.get("error")
        return json.dumps(c, ensure_ascii=False)[:120]
    probe = f"principal-check/{name}"
    print(f"{name}: write review_probe.json -> {call('write_file', {'path': probe + '/review_probe.json', 'content': '{}'})}")
    print(f"{name}: write draft.md         -> {call('write_file', {'path': probe + '/draft.md', 'content': 'x'})}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:] or ["list"]
    code = {"apply": lambda: cmd_apply("--dry-run" in a),
            "list": lambda: cmd_list(),
            "create": lambda: cmd_create(a[1]),
            "rules": lambda: cmd_rules(a[1], a[2]),
            "check": lambda: cmd_check(a[1])}[a[0]]()
    sys.exit(code or 0)
