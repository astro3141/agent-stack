"""List the tools Preloop's MCP endpoint exposes to a given agent principal (token from its own config)."""
import json, os, sys, tomllib, urllib.request
who = sys.argv[1]
if who == "claude":
    tok = json.load(open(os.path.expanduser("~/.claude.json")))["mcpServers"]["preloop"]["headers"]["Authorization"]
else:
    tok = tomllib.load(open(os.path.expanduser("~/.codex/config.toml"), "rb"))["mcp_servers"]["preloop"]["http_headers"]["Authorization"]
H = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "Authorization": tok}
def call(m, p, i, sid=None):
    h = dict(H)
    if sid: h["mcp-session-id"] = sid
    r = urllib.request.urlopen(urllib.request.Request("http://console/mcp/v1", data=json.dumps(
        {"jsonrpc": "2.0", "id": i, "method": m, "params": p}).encode(), headers=h), timeout=20)
    b = r.read().decode()
    return r.headers.get("mcp-session-id"), json.loads(b.split("data: ", 1)[1] if "data: " in b else b)
sid, _ = call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "p281", "version": "0"}}, 1)
_, d = call("tools/list", {}, 2, sid)
names = sorted(t["name"] for t in d["result"]["tools"])

# `--probe` calls one harmless tool instead of listing. Listing is not proof: a tool server that
# was deleted and recreated keeps its tools in the listing while every call answers "MCP server
# <old id> not found", because Preloop resolves tool -> server from a cache in its api process
# (measured; OPERATIONS §28). A read with no side effect is enough to tell the two apart.
if "--probe" in sys.argv:
    if "list_allowed_directories" not in names:
        print("PROBE FAIL: the file tools are not even listed"); raise SystemExit(1)
    _, r = call("tools/call", {"name": "list_allowed_directories", "arguments": {}}, 3, sid)
    text = json.dumps(r, ensure_ascii=False)
    if "not found" in text or "error" in (r or {}):
        print("PROBE FAIL: " + text[:200]); raise SystemExit(1)
    print("PROBE OK")
    raise SystemExit(0)

print(who, names)
