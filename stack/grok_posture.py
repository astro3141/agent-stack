"""Grok's native tools are off by a block in its own config file. This writes it, and checks it.

usage (agent container):
  grok_posture.py ensure [<GROK_HOME> ...]     write the block where it is missing; say what was done
  grok_posture.py check  [<GROK_HOME> ...]     one JSON line per login: ok, or what is missing
  grok_posture.py check --brief                "yes" when every grok login carries it, else "no"

Without arguments the logins are the ones the profiles name for grok (config/profiles, `login`),
`grok` when none does.

Why this file exists. Claude's native write/shell are removed by a project settings file the
adapter writes into the run's workspace; Codex's by feature flags in its environment. Grok's are
removed by a `[permission]` table in its own config — and that table was written **by hand**, on
the first install, measured (FINDINGS-281, "Grok native tools removed", 2026-09-22), and then
assumed. The second install (OPERATIONS §64) had a Grok login and no such table: the Cold Reader
produced its review, wrote it with the native `Write` tool instead of Preloop's `write_file`, the
adapter held that for a person, nobody was there, and the lane ended `DENIED` (`approval_expired`)
after the approval window. An arm64 pilot had met the same wall earlier (§31: a Grok lane asking
to run a shell command). Twice is a pattern: a posture that lives in a file nobody provisions is
a posture that holds on one machine.

What is written is exactly what was measured:

    [permission]
    deny  = ["Bash", "Edit", "Write", "WebFetch", "WebSearch"]
    allow = ["MCPTool(preloop__*)"]
    [ui]
    remember_tool_approvals = false

Deny rules win over every other rule and mode in Grok's documented evaluation order, so with
this there is no native write path left that a human approval could open — the same posture the
matrix records for Claude (project deny) and, short of `apply_patch`, for Codex.

`ensure` keeps what the file already has: the `preloop` MCP server entry, other tables, an
existing `[ui]` table, extra deny or allow entries (merged, never dropped). The previous file is
kept beside it as `config.toml.bak`, and the result is parsed back before it is accepted; a file
this cannot parse is left exactly as it was and reported.
"""
import json
import os
import re
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DENY = ["Bash", "Edit", "Write", "WebFetch", "WebSearch"]
ALLOW = ["MCPTool(preloop__*)"]


def grok_homes():
    """Every login directory the profiles run grok on, under the stack's logins root."""
    import settings
    rt = settings.runtime()
    root = rt["paths"]["logins_root"]
    names = []
    for n in settings.profile_names():
        p = settings.profile(n) or {}
        login = ((p.get("routing") or {}).get("login") or {}).get("grok")
        if login and login not in names:
            names.append(login)
    return [os.path.join(root, n) for n in (names or ["grok"])]


def read(home):
    path = os.path.join(home, "config.toml")
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    try:
        doc = tomllib.loads(text) if text else {}
    except tomllib.TOMLDecodeError as e:
        return text, None, f"config.toml does not parse: {e}"
    return text, doc, None


def missing(doc):
    """What the block lacks, in the words a person would look for; empty when it is all there."""
    perm = doc.get("permission") or {}
    deny, allow = perm.get("deny") or [], perm.get("allow") or []
    out = []
    lacking = [t for t in DENY if t not in deny]
    if lacking:
        out.append("deny lacks " + ", ".join(lacking))
    if not any(a in allow for a in ALLOW):
        out.append("allow lacks MCPTool(preloop__*)")
    if (doc.get("ui") or {}).get("remember_tool_approvals") is not False:
        out.append("ui.remember_tool_approvals is not false")
    return out


def check(home):
    if not os.path.isfile(os.path.join(home, "auth.json")):
        return {"home": home, "state": "no login"}
    text, doc, err = read(home)
    if err:
        return {"home": home, "state": "error", "error": err}
    lacks = missing(doc)
    return {"home": home, "state": "ok" if not lacks else "missing", **({"missing": lacks} if lacks else {})}


_HEADER = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def rewrite(text, doc):
    """The file with the block in it: tables kept, [permission] replaced by the merged one,
    remember_tool_approvals set under an existing [ui] or a new one. Text in, text out."""
    perm = doc.get("permission") or {}
    deny = list(DENY) + [t for t in (perm.get("deny") or []) if t not in DENY]
    allow = list(ALLOW) + [a for a in (perm.get("allow") or []) if a not in ALLOW]
    lines, out, table = text.splitlines(), [], None
    ui_seen = False
    for line in lines:
        m = _HEADER.match(line)
        if m:
            table = m.group(1).strip()
            if table == "permission":
                continue                       # the whole table is rewritten below
            out.append(line)
            if table == "ui":
                ui_seen = True
                out.append("remember_tool_approvals = false")
            continue
        if table == "permission":
            continue
        if table == "ui" and re.match(r"^\s*remember_tool_approvals\s*=", line):
            continue
        out.append(line)
    if out and out[-1].strip():
        out.append("")
    out += ["[permission]",
            "deny = " + json.dumps(deny),
            "allow = " + json.dumps(allow)]
    if not ui_seen:
        out += ["[ui]", "remember_tool_approvals = false"]
    return "\n".join(out) + "\n"


def ensure(home):
    c = check(home)
    if c["state"] in ("no login", "ok", "error"):
        return c
    text, doc, _ = read(home)
    new = rewrite(text, doc)
    try:
        after = tomllib.loads(new)
    except tomllib.TOMLDecodeError as e:
        return {"home": home, "state": "error", "error": f"the rewritten file does not parse: {e}", "left": "unchanged"}
    still = missing(after)
    if still:
        return {"home": home, "state": "error", "error": "the rewrite did not produce the block: " + "; ".join(still), "left": "unchanged"}
    path = os.path.join(home, "config.toml")
    if text:
        open(path + ".bak", "w", encoding="utf-8").write(text)
    tmp = path + ".tmp"
    open(tmp, "w", encoding="utf-8").write(new)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return {"home": home, "state": "written", "was_missing": c["missing"], **({"kept": "config.toml.bak"} if text else {})}


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "check"
    brief = "--brief" in args
    homes = [a for a in args[1:] if not a.startswith("--")] or grok_homes()
    fn = ensure if cmd == "ensure" else check
    results = [fn(h) for h in homes]
    if brief:
        logged_in = [r for r in results if r["state"] != "no login"]
        print("yes" if logged_in and all(r["state"] == "ok" for r in logged_in) else "no")
        sys.exit(0)
    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    sys.exit(1 if any(r["state"] == "error" for r in results) else 0)
