"""#281: build normalized quota observations for the router, one file per provider.

usage: collect_obs.py <out-dir>
Runs in the governed agent container. Vendor-specific by design — this is the collector, the
place where each source's shape is translated; router.py sees only the common format.

  codex  : CodexBar in the observer container (own login, egress) → /obs/codex.raw.json
           observed account = CodexBar's identity.accountEmail (fingerprinted)
           executing account = the id_token email in this container's ~/.codex/auth.json,
           whose credential Preloop custodies for execution (fingerprinted)       → basis "email"
  claude : Preloop gateway's stored upstream headers (anthropic-ratelimit-unified-*)
           observed account = the Preloop-custodied Anthropic OAuth credential
           executing account = the same credential, when Claude's route is the Preloop gateway
           No email is available on either side                                   → basis "structural"
"""
import base64, glob, hashlib, json, os, sys, urllib.request
from datetime import datetime, timezone

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
fp = lambda s: "email:" + hashlib.sha256(s.lower().encode()).hexdigest()[:16] if s else None


def write(provider, rec):
    json.dump(rec, open(os.path.join(out, f"{provider}.json"), "w"), indent=1)


def iso_from_epoch(v):
    try:
        return datetime.fromtimestamp(int(v), timezone.utc).isoformat()
    except Exception:
        return None


# ---- codex ------------------------------------------------------------------------------
def codex_executing_account():
    a = json.load(open(os.path.expanduser("~/.codex/auth.json")))
    part = ((a.get("tokens") or {}).get("id_token") or "..").split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return fp(claims.get("email", ""))


try:
    raw = json.load(open("/obs/codex.raw.json"))
    item = next((x for x in (raw.get("payload") or []) if x.get("provider") == "codex"), None)
    u = (item or {}).get("usage") or {}
    win = lambda w: None if not u.get(w) else {"used_percent": u[w].get("usedPercent"),
                                                "resets_at": u[w].get("resetsAt"),
                                                "window_minutes": u[w].get("windowMinutes")}
    windows = {k: v for k, v in {"session": win("primary"), "weekly": win("secondary")}.items() if v}
    write("codex", {
        "provider": "codex", "source": f"codexbar:{(item or {}).get('source')}",
        # the provider-side timestamp, not when the file was written
        "observed_at": u.get("updatedAt") or raw.get("collected_at"),
        "observed_account": fp((u.get("identity") or {}).get("accountEmail") or u.get("accountEmail") or ""),
        "executing_account": codex_executing_account(),
        "identity_basis": "email",
        "windows": windows,
    } if item else {"provider": "codex", "source": "codexbar", "observed_at": raw.get("collected_at"),
                    "observed_account": None, "executing_account": codex_executing_account(),
                    "identity_basis": "email", "windows": {}, "error": f"codexbar exit {raw.get('exit')}"})
except FileNotFoundError:
    pass  # no observation → router treats codex as unknown


# ---- claude -----------------------------------------------------------------------------
try:
    tok = [l.split(":", 1)[1].strip() for l in open(os.path.expanduser("~/.preloop/config.yaml"))
           if l.startswith("access_token:")][0]
    d = json.load(urllib.request.urlopen(urllib.request.Request(
        "http://api:8000/api/v1/account/gateway-usage/rate-limits",
        headers={"Authorization": "Bearer " + tok}), timeout=20))
    snaps = [s for s in d.get("latest_snapshots", []) if s.get("provider_name") == "anthropic"
             and ((s.get("rate_limit") or {}).get("headers") or {}).get("anthropic-ratelimit-unified-5h-utilization")]
    s = max(snaps, key=lambda s: s["observed_at"]) if snaps else None
    base = (json.load(open(os.path.expanduser("~/.claude/settings.json"))).get("env") or {}).get("ANTHROPIC_BASE_URL", "")
    executing = "preloop-custody:anthropic-oauth" if base.startswith("http://console") else None
    if s:
        h = s["rate_limit"]["headers"]
        pct = lambda k: round(float(h[k]) * 100, 1) if h.get(k) is not None else None
        write("claude", {
            "provider": "claude", "source": f"preloop-gateway:{s['model_alias']}",
            # Preloop stores naive UTC timestamps
            "observed_at": s["observed_at"] + ("" if s["observed_at"].endswith("Z") or "+" in s["observed_at"] else "+00:00"),
            "observed_account": f"preloop-custody:anthropic-{s.get('upstream_credential_type')}",
            "executing_account": executing,
            "identity_basis": "structural",
            "windows": {
                "session": {"used_percent": pct("anthropic-ratelimit-unified-5h-utilization"),
                            "resets_at": iso_from_epoch(h.get("anthropic-ratelimit-unified-5h-reset"))},
                "weekly": {"used_percent": pct("anthropic-ratelimit-unified-7d-utilization"),
                           "resets_at": iso_from_epoch(h.get("anthropic-ratelimit-unified-7d-reset"))},
            },
        })
except Exception as e:
    write("claude", {"provider": "claude", "source": "preloop-gateway", "observed_at": None,
                     "observed_account": None, "executing_account": None,
                     "identity_basis": "structural", "windows": {}, "error": str(e)[:200]})

print(json.dumps({"out": out, "files": sorted(os.listdir(out))}))
