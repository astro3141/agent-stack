"""Pending Preloop approval requests, and answering them — for the panel, in the agent container.

An approval is the one thing in this stack that *must* wait for a person: an agent asked to do
something its rules do not decide on its own, and the run stops until someone says yes or no. That
is why the decision is here rather than only in Preloop's console — the panel exists for what needs
a human, and this is the clearest case of it. The request's own facts (which tool, which file,
which run asked) are shown with it, and every answer is recorded on this side too, so an approval
given here is not only a row in Preloop's database.

  approvals.py                 prints a JSON list of the pending requests (the panel reads this)
  approvals.py --all           prints {"complete": true|false, "items": [...], "error": "…"}
  approvals.py decide <id> approve|decline [comment]   answers one request

The API answers one page at a time (`limit`, `skip`, default 50) and orders by request time, so
asking for the first page alone is not "the pending ones": fifty decided requests are enough to
hide one that is waiting. This asks for `status=pending` and keeps asking until a page comes back
short. Callers that delete things (p281/cleanup.py) must use --all and stop unless `complete`.
"""
import glob, hashlib, json, os, sys, urllib.error, urllib.request
from datetime import datetime, timezone
sys.path.insert(0, "/work/p281")
import settings

PAGE = 100
MAX_PAGES = 100          # a hard stop; beyond this the answer is reported as incomplete


def fetch_pending():
    tok = json.load(open(glob.glob(os.path.expanduser("~/.preloop/agents/*/permission_hook.json"))[0]))["token"]
    api = settings.runtime()["preloop"]["api_url"]
    now = datetime.now(timezone.utc)
    out, skip = [], 0
    for _ in range(MAX_PAGES):
        url = f"{api}/api/v1/approval-requests?status=pending&limit={PAGE}&skip={skip}"
        rows = json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers={"Authorization": "Bearer " + tok}), timeout=20))
        if not isinstance(rows, list):
            raise ValueError("unexpected answer from the approvals API")
        for r in rows:
            if r.get("status") != "pending":
                continue
            exp = r.get("expires_at")
            if exp and datetime.fromisoformat(exp).replace(tzinfo=timezone.utc) < now:
                continue      # Preloop leaves expired requests "pending"; do not show them as waiting
            args = r.get("tool_args") or {}
            out.append({"id": r["id"], "tool": r.get("tool_name"), "requested_at": r.get("requested_at"),
                        "expires_at": exp, "cwd": args.get("cwd"),
                        "target": args.get("file_path") or args.get("path") or args.get("command")
                                  or (args.get("_acp_locations") or [None])[0],
                        "source": args.get("_preloop_source")})
        if len(rows) < PAGE:
            return out, True          # a short page means the end
        skip += PAGE
    return out, False                 # ran out of pages: the answer is not complete


def decide(request_id, approve, comment=""):
    """Answer one request. Preloop owns the decision; this records that it was given here."""
    tok = json.load(open(glob.glob(os.path.expanduser("~/.preloop/agents/*/permission_hook.json"))[0]))["token"]
    api = settings.runtime()["preloop"]["api_url"]
    verb = "approve" if approve else "decline"
    body = json.dumps({"approved": bool(approve),
                       "comment": (comment or "")[:500]}).encode()
    req = urllib.request.Request(f"{api}/api/v1/approval-requests/{request_id}/{verb}",
                                 data=body, method="POST",
                                 headers={"Authorization": "Bearer " + tok,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            answer = json.loads(r.read() or b"{}")
        out = {"ok": True, "id": request_id, "decision": verb, "status": answer.get("status")}
    except urllib.error.HTTPError as e:
        out = {"ok": False, "id": request_id, "decision": verb,
               "error": f"HTTP {e.code}: {e.read()[:200].decode('utf8', 'replace')}"}
    except Exception as e:
        out = {"ok": False, "id": request_id, "decision": verb, "error": f"{type(e).__name__}: {e}"}
    # the operations record, on our side: which credential answered what, and whether it took.
    # The fingerprint matters because in Preloop OSS 0.15.0 the runtime's own credential is
    # authorised to decide approvals (measured; OPERATIONS.md §13) — so "who answered" is a
    # question that has to stay answerable afterwards.
    try:
        os.makedirs("/work/evidence/ops", exist_ok=True)
        with open("/work/evidence/ops/controls.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                "control": "approval",
                                "credential_sha12": hashlib.sha256(tok.encode()).hexdigest()[:12],
                                **out,
                                "comment": (comment or "")[:200]}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["decide"]:
        rid, verb = sys.argv[2], sys.argv[3]
        if verb not in ("approve", "decline"):
            print(json.dumps({"ok": False, "error": "decision must be approve or decline"}))
            sys.exit(2)
        print(json.dumps(decide(rid, verb == "approve",
                                sys.argv[4] if len(sys.argv) > 4 else ""), ensure_ascii=False))
        sys.exit(0)
    full = "--all" in sys.argv[1:]
    try:
        items, complete = fetch_pending()
    except Exception as e:
        if full:
            print(json.dumps({"complete": False, "items": [], "error": f"{type(e).__name__}: {e}"}))
            sys.exit(0)
        raise
    print(json.dumps({"complete": complete, "items": items} if full else items))
