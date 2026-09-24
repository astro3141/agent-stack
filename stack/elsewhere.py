"""What can change this stack from someone else's console — read, so it is not a surprise.

usage: elsewhere.py [--json]        (in the agent container; the panel reads it through ops)

The panel deliberately does not rebuild Preloop's or MLflow's screens. The cost of that choice is
that things can change there and this stack would not say so. These are the ones that would change
what an agent may do or whether a person is asked at all, so they are read and shown here:

  * **approval bypasses** — Preloop can be told to stop asking for a while. A bypass does not block
    a run; it removes the block, which is exactly the kind of change that is invisible from the
    outcome. Any bypass at all is worth seeing.
  * **the MCP servers registered to the account** — the tools an agent can reach are whatever is
    registered, and that list is editable in the console.
  * **the policy actually applied to the account** — this stack generates and applies its own
    (stack/cfg.py); a policy applied elsewhere replaces it, which `cfg.py status` already reports.

It reads and reports. Changing any of them stays in the console that owns them: this is not a
second place to edit Preloop.
"""
import glob, json, os, sys, urllib.error, urllib.request

sys.path.insert(0, "/work/stack")
import settings

API = settings.runtime()["preloop"]["api_url"]


def token():
    return json.load(open(glob.glob(os.path.expanduser(
        "~/.preloop/agents/*/permission_hook.json"))[0], encoding="utf-8"))["token"]


def get(path):
    r = urllib.request.Request(API + path, headers={"Authorization": "Bearer " + token()})
    with urllib.request.urlopen(r, timeout=15) as x:
        return json.loads(x.read() or b"null")


def state():
    out = {}
    try:
        rows = get("/api/v1/approval-bypasses") or []
        rows = rows if isinstance(rows, list) else rows.get("items") or []
        out["approval_bypasses"] = [
            {"id": r.get("id"), "scope": r.get("scope") or r.get("tool_name") or r.get("agent_id"),
             "created_at": r.get("created_at"), "expires_at": r.get("expires_at"),
             "reason": (r.get("reason") or "")[:120]} for r in rows]
    except Exception as e:
        out["approval_bypasses_error"] = f"{type(e).__name__}: {e}"
    try:
        rows = get("/api/v1/mcp-servers") or []
        rows = rows if isinstance(rows, list) else rows.get("items") or rows.get("servers") or []
        out["mcp_servers"] = [{"name": r.get("name"), "url": r.get("url") or r.get("command")}
                              for r in rows]
    except Exception as e:
        out["mcp_servers_error"] = f"{type(e).__name__}: {e}"
    return out


if __name__ == "__main__":
    s = state()
    if "--json" in sys.argv:
        print(json.dumps(s, ensure_ascii=False))
    else:
        b = s.get("approval_bypasses")
        print(f"approval bypasses  {len(b) if b is not None else s.get('approval_bypasses_error')}")
        for x in b or []:
            print(f"   {x['scope']} · until {x['expires_at']} · {x['reason']}")
        for m in s.get("mcp_servers") or []:
            print(f"mcp server         {m['name']}  {m['url']}")
