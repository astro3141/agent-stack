"""Read the generated settings (config/generated/, produced by cfg.py). Shared by the step scripts.

Falls back to the built-in defaults when nothing has been generated yet, so an unconfigured
checkout still runs the way it did before the settings model existed.
"""
import json, os, sys
from pathlib import Path

ROOT = Path(os.environ.get("AGENTSTACK_ROOT", "/work"))
GEN = ROOT / "config" / "generated"
# Where this code is, and the interpreter running it: a module that starts another module of the
# stack names it from here, never as a path written out (review 3, "변경 용이성", OPERATIONS §80).
STACK = Path(__file__).resolve().parent
PYTHON = sys.executable

# The providers the execution layer supports, and the routes each one takes. One module per
# provider under stack/adapter/providers/ is the other half; a control holds the two equal. Read
# here by cfg.py (validation), login_helper.py (targets) and the ops API (through the directory).
PROVIDERS = {
    "claude": {"direct", "preloop_gateway"},
    "codex": {"direct", "preloop_gateway"},
    "grok": {"direct"},
}

DEFAULT_RUNTIME = {
    "preloop": {"api_url": "http://api:8000", "mcp_url": "http://console/mcp/v1"},
    "mlflow": {"url": "http://mlflow:5000"},
    "egress": {"proxy": "http://egress:8888", "no_proxy": ["console", "api", "gateway", "mlflow", "localhost", "127.0.0.1"]},
    "broker": {"url": "http://broker:8791", "mcp_url": "http://broker:8791/mcp/v1"},
    "paths": {"workspace_root": "/ws", "evidence_root": "/work/evidence/p281", "observations": "/obs", "logins_root": "/route",
              "state_root": "/work/state"},
}


def runtime():
    try:
        return json.loads((GEN / "runtime.json").read_text())
    except Exception:
        return DEFAULT_RUNTIME


def url(section, key):
    """One address, from the generated settings or the default here — the only place an in-network
    address is written. `settings.url("preloop", "api_url")`, `("broker", "url")`, …"""
    v = (runtime().get(section) or {}).get(key)
    return v or DEFAULT_RUNTIME[section][key]


def profile(name):
    """The generated profile, or None if it does not exist (callers must fail, not guess)."""
    p = GEN / "profiles" / f"{name}.json"
    return json.loads(p.read_text()) if p.is_file() else None


def profile_names():
    """Every generated profile's name — so a refusal can say what there is instead."""
    d = GEN / "profiles"
    return [f.stem for f in d.glob("*.json")] if d.is_dir() else []


def egress_env(rt=None):
    rt = rt or runtime()
    e = rt["egress"]; np = ",".join(e.get("no_proxy") or [])
    return {"HTTPS_PROXY": e["proxy"], "https_proxy": e["proxy"], "HTTP_PROXY": e["proxy"],
            "http_proxy": e["proxy"], "NO_PROXY": np, "no_proxy": np}
