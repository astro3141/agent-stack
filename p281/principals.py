"""Role principals: the identities a workflow's steps run as, and the rights each one carries.

usage:
  principals.py list                         what exists, and what each may do
  principals.py create <name>                a principal and its credential (prints the env line)
  principals.py rules <name> <spec.json>     replace that principal's tool rules
  principals.py check <name>                 what its credential can and cannot do, measured

Why this exists at all: tool rights in Preloop are per **subject** — a credential, or the managed
agent behind it — never per step. A step gets its own rights by running as its own principal, and
`steps/roles.py` is where a workflow says which role uses which (`story=codex:novel-reviewer`).
The vendor and the principal are chosen separately, so three vendors can share one reviewer's
rights, which is what the novel workflow does.

**This never writes a credential anywhere.** `create` prints the line to put in
`docker/principals.env` (git-ignored, read by the agent container as environment); the adapter
takes it from the environment and records only the principal's name. A credential that is not in
that file simply is not available, and a step that asks for it fails closed.
"""
import glob, hashlib, json, os, sys, urllib.error, urllib.request

sys.path.insert(0, "/work/p281")
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
    for name, aid in sorted(principals().items()):
        cfg = (api("GET", f"/api/v1/agents/{aid}/governance") or {}).get("config") or {}
        rules = cfg.get("tool_rules") or {}
        off = [t for t, v in (cfg.get("tool_enabled_overrides") or {}).items() if v is False]
        has = os.environ.get(env_name(name)) is not None
        print(f"{name:<18} {aid}  credential in the environment: {'yes' if has else 'NO'}")
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
    code = {"list": lambda: cmd_list(),
            "create": lambda: cmd_create(a[1]),
            "rules": lambda: cmd_rules(a[1], a[2]),
            "check": lambda: cmd_check(a[1])}[a[0]]()
    sys.exit(code or 0)
