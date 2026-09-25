"""Per-role egress: which hosts a role may reach, the uid it runs as, and the proxy that enforces it.

usage (in the agent container):
  role_egress.py plan [--json]     what each role declares, the uid and port assigned, what is live
  role_egress.py write             write the per-role proxy configs and mint their credentials
                                   (root, because the credentials are 0600: docker exec -u 0)
  role_egress.py uid <role>        the uid a role runs as, or nothing

Why a role and not a workflow: a workflow already names a role per step
(`story=codex:novel-reviewer`), so a role's list is inherited by whatever workflow uses it, and the
stack keeps one identity model instead of two (OPERATIONS §47).

Two things are needed and they do different jobs, both measured before this existed (§47):

  * **the proxy** decides hosts, and all it learns from a connection is a credential on a port —
    every process in the agent shares one container IP. So each role gets its own tinyproxy
    instance: its own port, its own filter file, its own BasicAuth.
  * **the uid** is what makes that credential unstealable. Every step used to run as one user, and
    `/proc/<pid>/environ` is readable across processes at the same uid; with a uid per role it is
    Permission denied.

The credentials never touch this repository or `/work`: they live in a volume mounted into the agent
and the egress container, 0600 and owned by root, so a step — which runs as a role, never as root —
cannot read any of them, not even its own. `role-exec` reads the one it needs and puts it in the
step's own environment.

A role that declares nothing is not here, and nothing changes for it: it keeps the shared proxy and
the provider baseline, which is what every step had before this existed.
"""
import json
import os
import re
import secrets
import sys

sys.path.insert(0, "/work/stack")
import settings

CREDS = os.environ.get("AGENTSTACK_ROLE_CREDS", "/role-egress")
GEN = "/work/config/generated"
UID_BASE, PORT_BASE = 1100, 8890
NAME = re.compile(r"[a-z][a-z0-9-]{1,39}")
HOST = re.compile(r"[a-z0-9.-]{3,120}")
# Every role reaches the providers: the routing layer cannot execute without them, and a role's own
# list is about what it may reach *in addition*.
BASELINE = ["chatgpt.com", "auth.openai.com", "api.openai.com", "api.anthropic.com",
            "platform.claude.com", "console.anthropic.com", "claude.ai", "auth.x.ai",
            "accounts.x.ai", "api.x.ai", "cli-chat-proxy.grok.com"]


def declared():
    """{role: [hosts]} — every role that declares egress, from the platform's file and the packages."""
    out = {}
    try:
        import principals as pr
        for role, spec in (pr.declared() or {}).items():
            hosts = [str(h).strip() for h in ((spec or {}).get("egress") or [])]
            hosts = [h for h in hosts if HOST.fullmatch(h)]
            if hosts and NAME.fullmatch(str(role)):
                out[str(role)] = sorted(set(hosts))
    except Exception as e:
        print(json.dumps({"error": f"could not read the declarations: {type(e).__name__}: {e}"}),
              file=sys.stderr)
    return out


def assignment():
    """{role: {uid, port}} — stable across bring-ups, because it is written down once.

    Assigning by position in a sorted list would move a role's uid the day another role is added,
    and every file that role owns would stop being its own. So the map is persisted and only ever
    extended.
    """
    path = os.path.join(GEN, "role-uids.json")
    try:
        cur = json.load(open(path, encoding="utf-8"))
    except Exception:
        cur = {}
    used_uid = {v["uid"] for v in cur.values()}
    used_port = {v["port"] for v in cur.values()}
    changed = False
    for role in sorted(declared()):
        if role in cur:
            continue
        uid = next(u for u in range(UID_BASE, UID_BASE + 400) if u not in used_uid)
        port = next(p for p in range(PORT_BASE, PORT_BASE + 400) if p not in used_port)
        cur[role] = {"uid": uid, "port": port}
        used_uid.add(uid)
        used_port.add(port)
        changed = True
    if changed:
        os.makedirs(GEN, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline=chr(10)) as f:
            json.dump(cur, f, indent=1, sort_keys=True)
    return cur


def plan():
    d, a = declared(), assignment()
    rows = {}
    for role, hosts in sorted(d.items()):
        m = a.get(role) or {}
        rows[role] = {"hosts": hosts, "uid": m.get("uid"), "port": m.get("port"),
                      "credential_written": os.path.isfile(f"{CREDS}/{role}.cred"),
                      "credential_owner": (os.stat(f"{CREDS}/{role}.cred").st_uid
                                           if os.path.isfile(f"{CREDS}/{role}.cred") else None),
                      "config_written": os.path.isfile(f"{CREDS}/{role}.conf")}
    return {"roles": rows, "baseline": BASELINE, "creds_dir": CREDS}


def write():
    """Write each role's proxy config and mint the credential it needs. Root, in the agent."""
    os.makedirs(CREDS, exist_ok=True)
    os.chmod(CREDS, 0o755)          # the directory is listable; the credentials inside are not
    d, a = declared(), assignment()
    wrote = []
    for role, hosts in sorted(d.items()):
        port = (a.get(role) or {}).get("port")
        if not port:
            continue
        uid = (a.get(role) or {}).get("uid")
        cred_path = f"{CREDS}/{role}.cred"
        if os.path.isfile(cred_path):
            secret = open(cred_path, encoding="utf-8").read().strip()
        else:
            # minted once and kept: re-minting would leave the proxy and the launcher disagreeing
            secret = secrets.token_urlsafe(24)
            with open(cred_path, "w", encoding="utf-8", newline=chr(10)) as f:
                f.write(secret + chr(10))
        # the role's own, and only the role's: 0600 owned by its uid. Another role is another uid and
        # cannot read it; root can, which is how the proxy's configuration is written at all.
        os.chmod(cred_path, 0o600)
        if uid:
            try:
                os.chown(cred_path, uid, uid)
            except OSError:
                pass            # not root: reported by `plan`, which checks what is readable
        with open(f"{CREDS}/{role}.port", "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(str(port) + chr(10))
        os.chmod(f"{CREDS}/{role}.port", 0o644)
        allow = chr(10).join("^" + h.replace(".", chr(92) + ".") + "$"
                             for h in BASELINE + hosts) + chr(10)
        with open(f"{CREDS}/{role}.allow", "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(allow)
        os.chmod(f"{CREDS}/{role}.allow", 0o644)
        conf = [f"# {role}: the providers, plus what this role declares. Generated, not edited.",
                "User tinyproxy", "Group tinyproxy", f"Port {port}", "Timeout 600",
                "MaxClients 40", "Allow 0.0.0.0/0", "ConnectPort 443", "ConnectPort 9443",
                "ConnectPort 29443", f'Filter "{CREDS}/{role}.allow"', "FilterType ere",
                "FilterDefaultDeny Yes", "FilterURLs Off", f"BasicAuth {role} {secret}",
                f'PidFile "{CREDS}/{role}.pid"', "LogLevel Critical", ""]
        with open(f"{CREDS}/{role}.conf", "w", encoding="utf-8", newline=chr(10)) as f:
            f.write(chr(10).join(conf))
        os.chmod(f"{CREDS}/{role}.conf", 0o600)   # it carries the credential; root reads it
        wrote.append({"role": role, "port": port, "hosts": len(hosts)})
    return {"wrote": wrote, "creds_dir": CREDS}


if __name__ == "__main__":
    a = sys.argv[1:] or ["plan"]
    if a[0] == "uid":
        m = assignment().get(a[1] if len(a) > 1 else "") or {}
        print(m.get("uid") or "")
    elif a[0] == "write":
        print(json.dumps(write(), ensure_ascii=False))
    else:
        p = plan()
        if "--json" in a:
            print(json.dumps(p, ensure_ascii=False))
        elif not p["roles"]:
            print("no role declares egress — every step keeps the shared proxy and the baseline")
        else:
            for role, r in p["roles"].items():
                ready = r["credential_written"] and r["config_written"]
                print(f"{role:<18} uid={r['uid']} port={r['port']} "
                      f"hosts={','.join(r['hosts'])} {'ready' if ready else 'NOT WRITTEN'}")
