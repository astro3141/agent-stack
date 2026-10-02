"""Controls for the #284 review boundaries: partial apply, observation source choice, restart after
the end event, workspace_root spelling. Real functions, in-memory/temporary inputs — no Preloop,
no provider, no model call.

usage (agent container): /opt/venv/bin/python /work/stack/review_controls.py
"""
import base64, contextlib, hashlib, importlib, io, json, os, shutil, subprocess, sys, tempfile, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  — {detail}"))


def quiet(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = fn(*a)
    return rc, buf.getvalue()


# ---------------------------------------------------------------- 1. policy apply, partial failure
def policy_controls():
    root = Path(tempfile.mkdtemp(prefix="agentstack-cfg-"))
    shutil.copytree(WORK / "config", root / "config", ignore=shutil.ignore_patterns("generated"))
    shutil.copytree(WORK / "policy", root / "policy")
    (root / "policy" / "a.yaml").write_text((root / "policy" / "b-fsmcp.yaml").read_text() + "\n# A\n")
    os.environ["AGENTSTACK_ROOT"] = str(root)
    sys.path.insert(0, str(HERE))
    cfg = importlib.reload(importlib.import_module("cfg"))

    account = {"policy": None}                       # what the fake Preloop holds
    mode = {"apply": "ok", "scan": "ok"}
    calls = {"apply": 0}
    names = []
    for f in ("a.yaml", "b-fsmcp.yaml"):
        names += [s["name"] for s in cfg.load_yaml(root / "policy" / f).get("mcp_servers") or []]

    def fake_run(argv, **kw):
        calls["apply"] += 1
        if mode["apply"] == "timeout":
            account["policy"] = Path(argv[-1]).name  # a timeout may still have replaced it
            raise subprocess.TimeoutExpired(argv, 120)
        if mode["apply"] == "error":
            return subprocess.CompletedProcess(argv, 1, "", "rejected")
        account["policy"] = Path(argv[-1]).name
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    def fake_call(env, method, path, token):
        if method == "GET":
            return [{"name": n, "id": str(i)} for i, n in enumerate(names)]
        if mode["scan"] == "timeout":
            raise TimeoutError("scan timed out")
        return {}

    cfg.subprocess = type("FakeSubprocess", (), {"run": staticmethod(fake_run), "TimeoutExpired": subprocess.TimeoutExpired,
                                                  "CompletedProcess": subprocess.CompletedProcess})
    cfg.preloop_token = lambda: "t"
    cfg.preloop_call = fake_call

    def use(pol):
        for p in (root / "config" / "profiles").glob("*.yaml"):
            s = p.read_text()
            s = s.replace("policy/b-fsmcp.yaml", pol).replace("policy/a.yaml", pol)
            p.write_text(s)

    def apply():
        n = calls["apply"]
        _, out = quiet(cfg.cmd_apply)
        return json.loads(out)["results"], calls["apply"] - n

    def status(pol):
        _, out = quiet(cfg.cmd_status)
        return next(r for r in json.loads(out)["targets"] if r["target"] == f"preloop-policy:{pol}")

    use("policy/a.yaml"); r, n = apply()
    check("policy: A applies", account["policy"] == "a.yaml" and list(r.values()) == ["applied"], r)
    use("policy/b-fsmcp.yaml"); mode["scan"] = "timeout"; r, n = apply()
    s = status("policy/b-fsmcp.yaml")
    check("policy: B applied, scan failed → reported as such", list(r.values()) == ["policy applied, scan failed"], r)
    check("policy: after B's scan failure the account is recorded as B",
          s["active_on_account"] == "policy/b-fsmcp.yaml" and s["state"] == "apply_failed" and "scan stage" in s["error"], s)
    use("policy/a.yaml"); mode["scan"] = "ok"; r, n = apply()
    check("policy: A→B(scan failed)→A applies A again (review case)", n == 1 and account["policy"] == "a.yaml"
          and list(r.values()) == ["applied"] and status("policy/a.yaml")["state"] == "applied", (r, n, account))
    r, n = apply()
    check("policy: A again → already applied, no call", n == 0 and list(r.values()) == ["already applied"], (r, n))
    use("policy/b-fsmcp.yaml"); mode["scan"] = "timeout"; apply(); mode["scan"] = "ok"; r, n = apply()
    check("policy: B retried after its scan failed is not skipped", n == 1 and list(r.values()) == ["applied"]
          and status("policy/b-fsmcp.yaml")["state"] == "applied", (r, n))
    use("policy/a.yaml"); mode["apply"] = "timeout"; r, n = apply()
    s = status("policy/a.yaml")
    check("policy: apply timeout → account unknown, not B", list(r.values()) == ["apply failed"]
          and s["active_on_account"] == "unknown" and s["state"] == "apply_failed", (r, s))
    use("policy/b-fsmcp.yaml"); mode["apply"] = "ok"; r, n = apply()
    check("policy: after an unknown state B is applied, not skipped as 'already'", n == 1 and account["policy"] == "b-fsmcp.yaml"
          and list(r.values()) == ["applied"], (r, n, account))
    use("policy/a.yaml"); mode["apply"] = "error"; apply(); mode["apply"] = "ok"; use("policy/b-fsmcp.yaml"); r, n = apply()
    check("policy: failed apply of A, then B → B applied again (was the active one before)", n == 1
          and list(r.values()) == ["applied"], (r, n))
    # a legacy state record (before stages were tracked) is re-applied once, never trusted
    st = cfg.load_state(); st["preloop_active"].pop("scan", None); cfg.save_state(st); r, n = apply()
    check("policy: record without scan stage is not trusted", n == 1 and list(r.values()) == ["applied"], (r, n))

    for ws, ok in [("/ws", True), ("/ws/alt", True), ("/ws/", True), ("/data", False), ("/ws/../data", False),
                   ("/ws/./alt", False), ("/wsx", False), ("/ws/alt/..", False), ("ws/alt", False)]:
        env = {"paths": {"workspace_root": ws}}
        bad = any("workspace_root" in e and "must be" in e for e in cfg.validate_env(env))
        check(f"workspace_root {ws!r} {'accepted' if ok else 'rejected'}", bad != ok)
    shutil.rmtree(root)


# ---------------------------------------------------------------- 2. Codex observation source
def codex_controls():
    fp = lambda s: "email:" + hashlib.sha256(s.lower().encode()).hexdigest()[:16]
    b64 = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).decode().rstrip("=")

    def run(with_a_newer):
        root = Path(tempfile.mkdtemp(prefix="agentstack-obs-"))
        logins, obs, out = root / "route", root / "obs", root / "out"
        (root / "config" / "generated").mkdir(parents=True)
        rt = json.loads(json.dumps(__import__("settings").DEFAULT_RUNTIME))
        rt["paths"].update({"logins_root": str(logins), "observations": str(obs)})
        (root / "config" / "generated" / "runtime.json").write_text(json.dumps(rt))
        home = logins / "codex-b"; (home / "sessions" / "2026").mkdir(parents=True); obs.mkdir()
        (home / "auth.json").write_text(json.dumps({"tokens": {"id_token": "h." + b64({"email": "b@example.test"}) + ".s"}}))
        t0 = datetime.now(timezone.utc) - timedelta(minutes=2)
        sid = "0199aaaa-bbbb-cccc-dddd-000000000001"
        (logins / "codex-session-ledger.jsonl").write_text(json.dumps({"account": fp("b@example.test"), "session_id": sid}) + "\n")
        (home / "sessions" / "2026" / f"rollout-x-{sid}.jsonl").write_text(json.dumps({
            "timestamp": t0.isoformat().replace("+00:00", "Z"), "payload": {"rate_limits": {
                "primary": {"used_percent": 10, "window_minutes": 300, "resets_at": int(time.time()) + 3600},
                "secondary": {"used_percent": 20, "window_minutes": 10080, "resets_at": int(time.time()) + 86400}}}}) + "\n")
        if with_a_newer:
            (obs / "codex.raw.json").write_text(json.dumps({"collected_at": (t0 + timedelta(seconds=1)).isoformat(), "payload": [
                {"provider": "codex", "source": "oauth", "usage": {"updatedAt": (t0 + timedelta(seconds=1)).isoformat(),
                 "primary": {"usedPercent": 5, "windowMinutes": 300}, "secondary": {"usedPercent": 5, "windowMinutes": 10080},
                 "identity": {"accountEmail": "a@example.test"}}}]}))
        fake = root / "bin"; fake.mkdir()
        for tool in ("codexbar", "preloop"):
            (fake / tool).write_text("#!/bin/sh\nexit 1\n"); (fake / tool).chmod(0o755)
        env = {**os.environ, "AGENTSTACK_ROOT": str(root), "PATH": f"{fake}:{os.environ['PATH']}",
               "AGENTSTACK_MODEL_ROUTES": json.dumps({"codex": "direct"}), "AGENTSTACK_LOGINS": json.dumps({"codex": "codex-b"}),
               "AGENTSTACK_CODEX_LEDGER": str(logins / "codex-session-ledger.jsonl")}
        cp = subprocess.run([sys.executable, str(HERE / "collect_obs.py"), str(out)], env=env, capture_output=True, text=True, timeout=60)
        if not (out / "codex.json").exists():
            print(cp.stdout[-800:], cp.stderr[-1500:])
        rec = json.loads((out / "codex.json").read_text())
        pol = {"candidates": ["codex"], "model_route": {"codex": "direct"}, "login": {"codex": "codex-b"},
               "max_age_s": 1800, "require_windows": ["weekly"], "max_used_percent": {"session": 80, "weekly": 90}}
        (out / "policy.json").write_text(json.dumps(pol))
        dec = json.loads(subprocess.run([sys.executable, str(HERE / "router.py"), str(out / "policy.json"), str(out)],
                                        env=env, capture_output=True, text=True, timeout=60).stdout)
        shutil.rmtree(root)
        return rec, dec

    rec, dec = run(False)
    check("codex: B's bound rollout only → eligible", dec.get("decision") == "ROUTE" and dec.get("provider") == "codex", dec)
    rec, dec = run(True)
    check("codex: A's reading 1 s newer does not displace B's (review case)",
          rec["observed_account"] == rec["executing_account"] and rec["source"].startswith("rollout:"), rec)
    check("codex: … and B stays eligible", dec.get("decision") == "ROUTE" and dec.get("provider") == "codex", dec)
    check("codex: A's reading is kept as another source", any(s["source"].startswith("codexbar") for s in rec["other_sources"]), rec)


# ---------------------------------------------------------------- 2b. a reading kept beside the login
def kept_controls():
    """The second install's 429 (OPERATIONS §64): every asker took its own live reading of
    Claude's usage endpoint, the vendor rate-limited the endpoint, and a run held with the
    quota at 6 % / 43 %. The collector keeps the last good reading beside the login now."""
    root = Path(tempfile.mkdtemp(prefix="agentstack-kept-"))
    logins, out, fake = root / "route", root / "out", root / "bin"
    (root / "config" / "generated").mkdir(parents=True); (logins / "claude").mkdir(parents=True); fake.mkdir()
    rt = json.loads(json.dumps(__import__("settings").DEFAULT_RUNTIME))
    rt["paths"].update({"logins_root": str(logins), "observations": str(root / "obs")})
    (root / "config" / "generated" / "runtime.json").write_text(json.dumps(rt))
    (logins / "claude" / ".claude.json").write_text(json.dumps({"oauthAccount": {"organizationUuid": "org-1"}}))
    (fake / "codexbar").write_text(f"""#!/bin/sh
echo x >> {root}/calls
if [ "$(cat {root}/mode)" = ok ]; then
  printf '[{{"provider":"claude","source":"oauth","usage":{{"updatedAt":"%s","primary":{{"usedPercent":6,"windowMinutes":300}},"secondary":{{"usedPercent":43,"windowMinutes":10080}}}}}}]' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
else
  printf '[{{"provider":"claude","source":"oauth","error":{{"message":"Claude OAuth usage endpoint is rate limited by Anthropic right now"}}}}]'
fi
"""); (fake / "codexbar").chmod(0o755)
    (fake / "preloop").write_text("#!/bin/sh\nexit 1\n"); (fake / "preloop").chmod(0o755)
    calls = lambda: sum(1 for _ in open(root / "calls")) if (root / "calls").exists() else 0

    def collect(mode, reuse):
        (root / "mode").write_text(mode)
        env = {**os.environ, "AGENTSTACK_ROOT": str(root), "PATH": f"{fake}:{os.environ['PATH']}",
               "AGENTSTACK_OBS_REUSE_S": str(reuse), "AGENTSTACK_MODEL_ROUTES": json.dumps({"claude": "direct"}),
               "AGENTSTACK_LOGINS": json.dumps({"claude": "claude"})}
        subprocess.run([sys.executable, str(HERE / "collect_obs.py"), str(out)], env=env, capture_output=True, text=True, timeout=60)
        return json.loads((out / "claude.json").read_text())

    a = collect("429", 0)
    check("kept: no reading yet, vendor refuses → unknown, with the vendor's words",
          not a["windows"] and "rate limited" in (a.get("error") or ""), a)
    b = collect("ok", 0)
    check("kept: a good reading is taken live and kept", b["source"] == "codexbar:oauth"
          and b["windows"]["weekly"]["used_percent"] == 43 and (logins / ".quota" / "claude-claude.json").exists(), b)
    c = collect("429", 0)
    check("kept: vendor refuses after a good reading → the good one stands in, failure beside it",
          c["source"] == "cache:codexbar:oauth" and c["windows"]["weekly"]["used_percent"] == 43
          and "rate limited" in c.get("live_failed", ""), c)
    n = calls()
    d = collect("ok", 600)
    check("kept: within the reuse window the vendor is not asked again",
          d["source"] == "cache:codexbar:oauth" and "reused_after_s" in d and calls() == n, (d, calls(), n))
    check("kept: the reused reading keeps its own time, so the router judges its age as before",
          d["observed_at"] == b["observed_at"], (d["observed_at"], b["observed_at"]))
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- 2c. Grok's posture in its own config
def grok_posture_controls():
    """The table that turns Grok's native tools off lives in Grok's config file, which a login does
    not write. The second install ran a Grok lane without it (OPERATIONS §64). stack/grok_posture.py
    writes it, keeps what is there, and checks it."""
    import importlib
    gp = importlib.import_module("grok_posture")
    root = Path(tempfile.mkdtemp(prefix="agentstack-grok-"))
    a, b, c = root / "a", root / "b", root / "c"
    for d in (a, b, c):
        d.mkdir()
    check("grok posture: no login → nothing to write, said so", gp.ensure(str(a))["state"] == "no login")
    (b / "auth.json").write_text("{}")
    r1 = gp.ensure(str(b)); r2 = gp.ensure(str(b))
    import tomllib as _t
    doc = _t.loads((b / "config.toml").read_text())
    check("grok posture: a bare login gets the block, parseable", r1["state"] == "written"
          and set(gp.DENY) <= set(doc["permission"]["deny"]) and doc["permission"]["allow"] == gp.ALLOW
          and doc["ui"]["remember_tool_approvals"] is False, (r1, doc))
    check("grok posture: a second ensure changes nothing", r2["state"] == "ok" and not (b / "config.toml.bak").exists(), r2)
    (c / "auth.json").write_text("{}")
    (c / "config.toml").write_text('[mcp_servers.preloop]\nurl = "http://console/mcp/v1"\n[mcp_servers.preloop.http_headers]\n'
                                   'Authorization = "Bearer x"\n\n[ui]\ntheme = "dark"\nremember_tool_approvals = true\n\n'
                                   '[permission]\ndeny = ["Bash", "Custom"]\n')
    r3 = gp.ensure(str(c))
    doc = _t.loads((c / "config.toml").read_text())
    check("grok posture: an existing file keeps its MCP entry, its [ui] keys and its own deny entries",
          r3["state"] == "written" and doc["mcp_servers"]["preloop"]["url"] == "http://console/mcp/v1"
          and doc["ui"] == {"theme": "dark", "remember_tool_approvals": False}
          and "Custom" in doc["permission"]["deny"] and set(gp.DENY) <= set(doc["permission"]["deny"]), (r3, doc))
    check("grok posture: and the previous file is kept beside it", (c / "config.toml.bak").exists() and "Custom" in (c / "config.toml.bak").read_text())
    check("grok posture: check names what is missing", gp.check(str(c))["state"] == "ok"
          and "deny lacks" in " ".join(r3["was_missing"]), r3)
    (c / "config.toml").write_text("[permission\nbroken = \n")
    r4 = gp.ensure(str(c))
    check("grok posture: a file that does not parse is left alone and reported",
          r4["state"] == "error" and (c / "config.toml").read_text().startswith("[permission\n"), r4)
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- 3. restart after the end event
def run_controls():
    sys.path.insert(0, str(HERE))
    rw = importlib.import_module("run_workflow")
    rw.RUNS = Path(tempfile.mkdtemp(prefix="agentstack-runs-"))
    dead = subprocess.Popen(["true"]); dead.wait()

    def make(ui, events, pid):
        d = rw.RUNS / ui / "tmp" / "conductor"; d.mkdir(parents=True)
        (d / f"conductor-p281-x-20260923-000000-{ui[-8:]}.events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
        meta = {"ui_id": ui, "workflow": "auto", "profile": "p", "inputs": {}, "started_at": time.time(),
                "state": "running", "launcher_pid": pid, "instance": rw.instance_id()}
        rw.meta_path(ui).write_text(json.dumps(meta))
        return meta

    start = {"type": "agent_started", "timestamp": 1.0, "data": {"agent_name": "execute"}}
    done = {"type": "workflow_completed", "timestamp": 2.0, "data": {"output": {"decision": "PASS"}}}
    failed = {"type": "workflow_failed", "timestamp": 2.0, "data": {"output": {"decision": "DENIED"}, "is_explicit": True,
              "terminated_by": "denied", "termination_reason": "DENIED: policy"}}
    for ui, ev, dec in [("rc-pass-0000aaaa", done, "PASS"), ("rc-deny-0000bbbb", failed, "DENIED")]:
        v = rw.view(make(ui, [start, ev], dead.pid))
        saved = json.loads(rw.meta_path(ui).read_text())
        check(f"run: end event + launcher gone → finished ({dec})", v["state"] == "finished" and v["ended"]
              and (v["output"] or {}).get("decision") == dec and not v["error"], v)
        check(f"run: … and the restored state is persisted ({dec})", saved["state"] == "finished"
              and saved.get("recovered_from_event_log") and saved.get("ended_at") == 2.0, saved)
    v = rw.view(make("rc-live-0000cccc", [start, done], os.getpid()))
    check("run: end event, launcher alive → shown finished, meta left to the launcher",
          v["state"] == "finished" and json.loads(rw.meta_path("rc-live-0000cccc").read_text())["state"] == "running", v)
    v = rw.view(make("rc-intr-0000dddd", [start], dead.pid))
    check("run: no end event + launcher gone → interrupted", v["state"] == "interrupted", v)
    v = rw.view(make("rc-runn-0000eeee", [start], os.getpid()))
    check("run: no end event, launcher alive → running", v["state"] == "running", v)
    shutil.rmtree(rw.RUNS)


policy_controls()
codex_controls()
kept_controls()
grok_posture_controls()
run_controls()
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
