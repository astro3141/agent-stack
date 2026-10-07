"""What a closed call's model says it can see, against the stack's deny list (§104, #93).

usage (in the agent container, a claude login present):  tools_seen.py   → one JSON line

The only enumeration of the built-in tools this path has is the model's own report: the SDK's
init message lists them but the ACP adapter does not surface it, and acpx forwards no option
that would. So a closed call on claude is asked to name every tool it can call, in a declared
shape, and the names are compared with CLAUDE_BUILTIN_TOOLS (stack/adapter/permissions.mjs). A
name outside the list is a tool the list does not refuse — it is reported, the list grows, and
`verify.sh --level full` fails until it does. The model's report can be incomplete; it cannot be
wrong about a name it gives.
"""
import json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def known():
    src = open(os.path.join(HERE, "adapter", "permissions.mjs"), encoding="utf-8").read()
    body = src[src.index("CLAUDE_BUILTIN_TOOLS = ["):]
    body = body[:body.index("];")]
    return set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', body))


def main():
    run_id = os.environ.get("CONDUCTOR_SELF_RUN_ID") or "verify-tools-seen"
    env = {**os.environ, "CONDUCTOR_SELF_RUN_ID": run_id}
    argv = [sys.executable, os.path.join(HERE, "steps", "agent_task.py"), "claude", "direct", "tools-seen",
            os.path.join(HERE, "checks", "tools_seen.md"), "tools-seen.json", "closed", "claude", "",
            "--output-schema", os.path.join(HERE, "checks", "tools_seen.schema.json")]
    p = subprocess.run(argv, capture_output=True, text=True, env=env)
    try:
        rec = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception:
        print(json.dumps({"status": "NO_RECORD", "why": (p.stderr or p.stdout)[-300:]}))
        return 1
    out = {"status": rec.get("status"), "run_id": rec.get("run_id"), "tool_calls": rec.get("tool_calls")}
    if rec.get("status") != "COMPLETED":
        out["why"] = rec.get("failure", "")
        print(json.dumps(out, ensure_ascii=False))
        return 1
    seen = [str(t) for t in ((rec.get("answer") or {}).get("tools") or [])]
    names = [t for t in seen if NAME.match(t)]
    k = known()
    out.update({"seen": seen, "outside": sorted(set(n for n in names if n not in k)),
                "mcp": sorted(t for t in seen if t.startswith("mcp__"))})
    print(json.dumps(out, ensure_ascii=False))
    return 0 if not out["outside"] else 1


if __name__ == "__main__":
    sys.exit(main())
