"""Controls for the #284 review boundaries: partial apply, observation source choice, restart after
the end event, workspace_root spelling. Real functions, in-memory/temporary inputs — no Preloop,
no provider, no model call.

usage (agent container): /opt/venv/bin/python /work/stack/review_controls.py
"""
import base64, contextlib, hashlib, importlib, io, json, os, re, shutil, subprocess, sys, tempfile, time
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

    # declared, not assumed (issue #15): grok with native tools is refused, the reuse window is the
    # profile's and must sit under max_age_s, and it reaches the generated routing policy
    import yaml as _y
    prof = _y.safe_load((root / "config" / "profiles" / "research-default.yaml").read_text())
    envy = _y.safe_load((root / "config" / "environment.yaml").read_text())
    e1 = cfg.validate_profile({**prof, "tools": {**prof["tools"], "native_tools": True}}, "research-default", envy)[0]
    check("profile: grok with native_tools: true is refused, saying the posture is per login",
          any("grok" in e and "per login" in e for e in e1), e1)
    e2 = cfg.validate_profile({**prof, "quota": {**prof["quota"], "reuse_s": prof["quota"]["max_age_s"]}}, "research-default", envy)[0]
    check("profile: reuse_s at or above max_age_s is refused", any("reuse_s" in e for e in e2), e2)
    check("profile: reuse_s is validated as a number", any("reuse_s" in e for e in
          cfg.validate_profile({**prof, "quota": {**prof["quota"], "reuse_s": "soon"}}, "research-default", envy)[0]))
    gen = json.loads((root / "config" / "generated" / "profiles" / "research-default.json").read_text())
    check("profile: reuse_s reaches the generated routing policy", gen["routing"].get("reuse_s") == prof["quota"].get("reuse_s", 120), gen["routing"])

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


# ---------------------------------------------------------------- 2d. state that outlives a run
def state_controls():
    """One root, one directory per package, declared in the manifest, reported never deleted
    (docs/packages.md, "State that outlives a run")."""
    root = Path(tempfile.mkdtemp(prefix="agentstack-state-"))
    (root / "config" / "generated").mkdir(parents=True)
    rt = json.loads(json.dumps(__import__("settings").DEFAULT_RUNTIME))
    rt["paths"]["state_root"] = str(root / "state")
    (root / "config" / "generated" / "runtime.json").write_text(json.dumps(rt))
    (root / "state" / "hello-lane").mkdir(parents=True)           # installed, declares no state
    (root / "state" / "hello-lane" / "x").write_bytes(b"x" * 2048)
    (root / "state" / "zz-nobody").mkdir()                         # no such package
    env = {**os.environ, "AGENTSTACK_ROOT": str(root)}
    r = subprocess.run([sys.executable, str(HERE / "packages.py"), "state", "--json"], env=env,
                       capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout or "{}").get("packages") or {}
    check("state: an installed package's undeclared directory is reported as such",
          got.get("hello-lane", {}).get("state") == "UNDECLARED" and got["hello-lane"]["kb"] == 2, got)
    check("state: a directory with no package is a question, not a deletion",
          got.get("zz-nobody", {}).get("state") == "NO PACKAGE" and (root / "state" / "zz-nobody").exists(), got)
    import importlib
    check("state: requires.state is a key something reads", "state" in importlib.import_module("packages").KNOWN_REQUIRES)
    # a scheduled cycle carries the workflow's inputs through (PACKAGE-MATRIX §4, #13)
    cy = importlib.import_module("cycle")
    a = cy.parse_args(["trading-b", "research-default", "day=2026-10-02", "--by", "scheduler", "--retain-days", "3"])
    check("cycle: key=value words are the workflow's inputs, not a profile",
          a["inputs"] == {"day": "2026-10-02"} and a["profile"] == "research-default" and a["by"] == "scheduler", a)
    check("cycle: a bare profile still parses without inputs", cy.parse_args(["x"])["inputs"] == {})
    check("cycle: the inputs reach the run's argv",
          'argv += [f"{k}={v}" for k, v in sorted((inputs or {}).items())]' in (HERE / "cycle.py").read_text())
    # state kept with the work, elsewhere: declared as a string, reported as a place, never a directory
    pkgs = root / "packages"; (pkgs / "remote-one").mkdir(parents=True)
    (pkgs / "remote-one" / "manifest.yaml").write_text("name: remote-one\nversion: 0.0.1\nentry: w.yaml\nrequires:\n  state: \"github issue comments\"\n")
    (pkgs / "remote-one" / "w.yaml").write_text("name: remote-one\nagents: []\n")
    (root / "config" / "packages.yaml").write_text("packages:\n  - remote-one\n")
    env2 = {**env, "AGENTSTACK_PACKAGES": str(pkgs), "AGENTSTACK_PACKAGES_YAML": str(root / "config" / "packages.yaml")}
    r = subprocess.run([sys.executable, str(HERE / "packages.py"), "state", "--json"], env=env2,
                       capture_output=True, text=True, timeout=60)
    got = json.loads(r.stdout or "{}").get("packages") or {}
    check("state: a package that keeps state with the work is reported as a place, not a directory",
          got.get("remote-one", {}).get("state") == "remote" and "github issue comments" in got["remote-one"]["why"]
          and "not in this stack's backup" in got["remote-one"]["why"], got)
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- 2e. binding
def bind_controls():
    """The hash is the stack's; which bytes, and what a mismatch means, are the package's (#12)."""
    import hashlib
    sys.path.insert(0, str(HERE / "steps"))
    st = importlib.import_module("step")
    root = Path(tempfile.mkdtemp(prefix="agentstack-bind-"))
    (root / "a.txt").write_bytes(b"one draft\n")
    check("bind: a file's binding is its sha256", st.bind_file(root / "a.txt") == hashlib.sha256(b"one draft\n").hexdigest())
    check("bind: a text's binding is its UTF-8 sha256", st.bind_text("한 줄") == hashlib.sha256("한 줄".encode()).hexdigest())
    sha = st.bind_file(root / "a.txt")
    check("bind: a receipt made for these bytes is bound", st.bound({"context": sha, "members": {}}, sha))
    check("bind: a receipt for other bytes is not", not st.bound({"context": "0" * 64}, sha))
    check("bind: a receipt with no binding is not, and neither is an empty expectation",
          not st.bound({"members": {}}, sha) and not st.bound({"context": ""}, ""))
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- 2f. fan-out: a member's failure is its own
def fanout_controls():
    """Review 2026-10-02: a member whose process could not start left its row without an end and
    the step reading the rows died for every member; a retry replaced the first attempt's result,
    so its call and its evidence directory left the receipt."""
    sys.path.insert(0, str(HERE / "steps"))
    fo = importlib.import_module("fanout")
    rows, _ = fo.run_all([{"key": "ok", "argv": ["true"]},
                          {"key": "gone", "argv": ["/nonexistent/agentstack-no-such-exe"]}])
    by = {r["key"]: r for r in rows}
    check("fanout: a member that cannot start is a row with an end, a code and the reason",
          by["gone"].get("start_failed") and by["gone"]["returncode"] == 127 and "ended_at" in by["gone"]
          and "FileNotFoundError" in by["gone"]["stderr"], by["gone"])
    check("fanout: … and the member beside it is unaffected",
          by["ok"]["returncode"] == 0 and "ended_at" in by["ok"], by["ok"])
    rows, _ = fo.run_all([{"key": "e", "argv": ["sh", "-c", "echo $AGENTSTACK_ATTEMPT"], "env": {"AGENTSTACK_ATTEMPT": "2"}}])
    check("fanout: a job's env reaches its process", rows[0]["stdout"].strip() == "2", rows[0])

    # a retry, end to end through tasks.py: a fake chain fails on attempt 1 and produces on 2
    root = Path(tempfile.mkdtemp(prefix="agentstack-retry-"))
    (root / "config" / "generated").mkdir(parents=True)
    rt = json.loads(json.dumps(__import__("settings").DEFAULT_RUNTIME))
    rt["paths"]["workspace_root"] = str(root / "ws")
    (root / "config" / "generated" / "runtime.json").write_text(json.dumps(rt))
    chain = root / "chain.py"
    chain.write_text("""import json, os, sys
m = json.load(open(sys.argv[1]))
ws = os.environ["WSDIR"]; a = os.environ.get("AGENTSTACK_ATTEMPT", "1")
ok = a == "2"
if ok:
    open(f"{ws}/out.txt", "w").write("second time")
print(json.dumps({"status": "COMPLETED" if ok else "FAILED", "produced": ok, "model_calls": 1,
                  "run_id": f"r-{m['label']}" + ("-a2" if a == "2" else ""), "attempt_seen": a}))
""")
    (root / "ws" / "r1").mkdir(parents=True)
    plan = root / "plan.json"
    plan.write_text(json.dumps({"members": [{"label": "m", "retries": 1,
                                             "steps": [{"kind": "script", "argv": ["true"], "expected": "out.txt"}]}]}))
    env = {**os.environ, "AGENTSTACK_ROOT": str(root), "CONDUCTOR_SELF_RUN_ID": "r1", "POC_PY": sys.executable,
           "AGENTSTACK_CHAIN_ENTRY": str(chain), "WSDIR": str(root / "ws" / "r1")}
    r = subprocess.run([sys.executable, str(HERE / "steps" / "tasks.py"), str(root / "receipt.json"), "ctx", "p",
                        "--plan", str(plan)], env=env, capture_output=True, text=True, timeout=60)
    try:
        last = json.loads(r.stdout.strip().splitlines()[-1])
        rec = json.loads((root / "receipt.json").read_text())["members"]["m"]
    except Exception as e:                                       # noqa: BLE001
        last, rec = {"error": f"{e}: {r.stderr[-300:]}"}, {}
    check("tasks: a retried member produces, and the receipt counts both attempts",
          rec.get("produced") and rec.get("attempts") == 2 and rec.get("attempt_outcomes") == ["failed", "produced"], rec or last)
    check("tasks: every attempt's own result stays in the receipt, the retry named apart",
          [a.get("run_id") for a in rec.get("attempt_results") or []] == ["r-m", "r-m-a2"]
          and rec.get("result", {}).get("attempt_seen") == "2", rec.get("attempt_results"))
    check("tasks: the step reports the calls that were made, not the members that exist",
          last.get("model_calls") == 2 and last.get("produced") == 1, last)
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- 3. restart after the end event
def run_controls():
    """The run's state is read by `view` and restored by `read`, by name (runstate.recover)."""
    sys.path.insert(0, str(HERE))
    rw = importlib.import_module("run_workflow")
    rs = importlib.import_module("runstate")
    rs.RUNS = Path(tempfile.mkdtemp(prefix="agentstack-runs-"))
    dead = subprocess.Popen(["true"]); dead.wait()

    def make(ui, events, pid):
        d = rs.RUNS / ui / "tmp" / "conductor"; d.mkdir(parents=True)
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
        meta = make(ui, [start, ev], dead.pid)
        v = rw.view(dict(meta))
        untouched = json.loads(rw.meta_path(ui).read_text())
        check(f"run: end event + launcher gone → the view shows finished ({dec})", v["state"] == "finished" and v["ended"]
              and (v["output"] or {}).get("decision") == dec and not v["error"], v)
        check(f"run: … and a view writes nothing ({dec})", untouched["state"] == "running"
              and "recovered_from_event_log" not in untouched, untouched)
        v = rw.read(ui)
        saved = json.loads(rw.meta_path(ui).read_text())
        check(f"run: read() restores the state and persists it ({dec})", v["state"] == "finished"
              and saved["state"] == "finished" and saved.get("recovered_from_event_log")
              and saved.get("ended_at") == 2.0 and v.get("recovered_from_event_log"), saved)
    v = rw.read("rc-live-0000cccc") if make("rc-live-0000cccc", [start, done], os.getpid()) else None
    check("run: end event, launcher alive → shown finished, meta left to the launcher",
          v["state"] == "finished" and json.loads(rw.meta_path("rc-live-0000cccc").read_text())["state"] == "running", v)
    make("rc-intr-0000dddd", [start], dead.pid)
    check("run: no end event + launcher gone → interrupted, and said why",
          rw.read("rc-intr-0000dddd")["state"] == "interrupted" and "launcher is gone" in rw.read("rc-intr-0000dddd")["error"]
          and json.loads(rw.meta_path("rc-intr-0000dddd").read_text())["state"] == "interrupted")
    make("rc-runn-0000eeee", [start], os.getpid())
    check("run: no end event, launcher alive → running", rw.read("rc-runn-0000eeee")["state"] == "running")
    check("run: a run that is not there is None, not a traceback", rw.read("rc-none-0000ffff") is None)
    shutil.rmtree(rs.RUNS)


# ---------------------------------------------------------------- 4. the event log is read by what a step said
def event_controls():
    """A routing step and a recording step are recognised by their output, not their name
    (review 2026-10-02: the screen read `route` and `record*`, so a name was an API)."""
    sys.path.insert(0, str(HERE))
    ev = importlib.import_module("runevents")
    root = Path(tempfile.mkdtemp(prefix="agentstack-events-"))
    log = root / "conductor-p281-x-20260923-000000-deadbeef.events.jsonl"

    def sc(name, out):
        return {"type": "script_completed", "timestamp": 1.5, "data": {"agent_name": name, "stdout": json.dumps(out)}}
    routing = {"decision": "ROUTE", "provider": "claude", "reason": "within limits", "evaluated": "[]",
               "model_route": "direct", "profile": "p"}
    recorded = {"mlflow_run_id": "abc", "experiment_id": "7", "record_error": ""}
    events = [{"type": "agent_started", "timestamp": 1.0, "data": {"agent_name": "choose_provider"}},
              sc("choose_provider", routing),
              sc("route", {"status": "OK", "decision": "PASS"}),      # a step *named* route that is not the router
              sc("persist_result", recorded),
              {"type": "workflow_completed", "timestamp": 2.0, "data": {"output": {"decision": "PASS"}}}]
    log.write_text("".join(json.dumps(e) + "\n" for e in events))
    r = ev.read(log)
    check("events: the router's answer is read under any step name",
          (r["route"] or {}).get("provider") == "claude" and r["route"]["decision"] == "ROUTE", r["route"])
    check("events: a step named route that did not route is not read as the router",
          (r["route"] or {}).get("decision") != "PASS", r["route"])
    check("events: the recorder's answer is read under any step name",
          (r["mlflow"] or {}).get("run_id") == "abc" and r["mlflow"]["experiment_id"] == "7", r["mlflow"])
    check("events: the run id comes from the log's own name", r["conductor_run"] == "deadbeef", r["conductor_run"])
    check("events: the end, the output and the steps", r["ended"] and r["completed_ok"]
          and (r["output"] or {}).get("decision") == "PASS" and [s["step"] for s in r["steps"]] == ["choose_provider"], r)
    check("events: no log is an empty reading, not an error", ev.read(None) == ev.empty())
    check("events: ended() sees the end past the byte it was given", ev.ended(log) and not ev.ended(log, log.stat().st_size))
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- 5. the execution record
def execution_controls():
    """One shape for a call's result, owned in one place, and the document lists the same keys."""
    sys.path.insert(0, str(HERE))
    ex = importlib.import_module("execution")
    rec = ex.record(status="COMPLETED", provider="claude", run_id="r-m-claude")
    check("execution: a record carries every field, defaults filled, and its contract version",
          set(ex.FIELDS) <= set(rec) and rec["attempts"] == 1 and rec["measurements"] == {} and rec["contract"] == ex.CONTRACT, rec)
    check("execution: what a step adds beyond the shape is kept",
          ex.record(provider="x", run_id="y", dispatched={"role": "r"})["dispatched"] == {"role": "r"})
    check("execution: a call is a run id and a provider; a refusal that never ran is not one",
          ex.is_execution(rec) and not ex.is_execution(ex.record(status="DENIED", provider="claude")))
    check("execution: problems are named", ex.problems({"status": "FAILED", "attempts": "2"}) ==
          ["run_id missing", "provider missing", "attempts is not int"], ex.problems({"status": "FAILED", "attempts": "2"}))
    doc = (WORK / "docs" / "packages.md").read_text()
    block = doc.split("## The output of a model step")[1].split("```yaml")[1].split("```")[0]
    keys = set(re.findall(r"^\s{6}([a-z_]+):", block, re.M)) - {"type", "properties"}
    check("execution: docs/packages.md lists exactly the shape's keys", keys == set(ex.FIELDS), sorted(keys ^ set(ex.FIELDS)))
    root = Path(tempfile.mkdtemp(prefix="agentstack-exec-"))
    ex.write(root / "e1", rec)
    check("execution: the platform's copy round-trips from the evidence directory", ex.read(root / "e1") == rec)
    check("execution: no copy is None, not an error", ex.read(root / "nothing") is None)
    # a fan-out member: two attempts of a call, and a chain of two model steps + a script
    member = {"result": {"run_id": "r-m-claude-a2", "provider": "claude", "status": "COMPLETED"},
              "attempt_results": [{"run_id": "r-m-claude", "provider": "claude", "status": "FAILED"},
                                  {"run_id": "r-m-claude-a2", "provider": "claude", "status": "COMPLETED"}]}
    got = ex.of_member("m", member)
    check("execution: every attempt of a member is an execution of its own",
          [g["run_id"] for g in got] == ["r-m-claude", "r-m-claude-a2"] and all(g["member"] == "m" for g in got), got)
    chain = {"result": {"status": "COMPLETED", "steps": [
        {"kind": "script", "step": "m-1"},
        {"kind": "model", "step": "m-2", "run_id": "r-m-2", "provider": "codex"},
        {"kind": "model", "step": "m-3", "run_id": "r-m-3", "provider": "claude"}]}}
    got = ex.of_member("m", chain)
    check("execution: a chain is its model steps, each one tagged",
          [(g["run_id"], g["member"]) for g in got] == [("r-m-2", "m:m-2"), ("r-m-3", "m:m-3")], got)
    check("execution: a member that never named a call is no execution", ex.of_member("m", {"result": {"status": "FAILED"}}) == [])
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- 6. one door to the router, one door to a call
def door_controls():
    """Six callers asked the router in three moves each; now they ask admission.py. Three
    places chose between agent_task.py and the broker; now agent_task.py chooses, once."""
    sys.path.insert(0, str(HERE))
    srcs = {n: (WORK / n).read_text() for n in ("stack/steps/route.py", "stack/steps/admit_models.py", "stack/capabilities.py",
                                                "stack/ops_health.py", "ops/server.py", "scripts/verify.sh")}
    check("door: nobody but admission.py runs the collector and the router themselves",
          [n for n, s in srcs.items() if "/collect_obs.py" in s or "/router.py" in s] == [],
          [n for n, s in srcs.items() if "/collect_obs.py" in s or "/router.py" in s])
    check("door: … and every one of them asks admission", all("admission" in s for s in srcs.values()))
    ad = importlib.import_module("admission")
    try:
        ad.evaluate("zz-no-such-profile")
        missing = False
    except LookupError:
        missing = True
    check("door: a profile that does not exist is a LookupError, never a default", missing)
    pol = {"candidates": ["grok"], "login": {"grok": "grok"}, "model_route": {"grok": "direct"},
           "thresholds": {}, "max_age_s": 600, "reuse_s": 0}
    root = Path(tempfile.mkdtemp(prefix="agentstack-door-"))
    # a settings root of its own, with no login under it: the collector (a subprocess) reads the
    # logins root from the generated runtime, so what it finds is nothing — and says so
    (root / "config" / "generated").mkdir(parents=True); (root / "route").mkdir(); (root / "obs").mkdir()
    rt = json.loads(json.dumps(__import__("settings").DEFAULT_RUNTIME))
    rt["paths"].update({"logins_root": str(root / "route"), "observations": str(root / "obs")})
    (root / "config" / "generated" / "runtime.json").write_text(json.dumps(rt))
    env = dict(os.environ)
    os.environ["AGENTSTACK_ROOT"] = str(root)
    try:
        d = ad.evaluate(policy=pol, evidence_dir=str(root / "ev"))
    except Exception as e:                                       # noqa: BLE001
        d = {"error": f"{type(e).__name__}: {e}"}
    finally:
        os.environ.clear(); os.environ.update(env)
    check("door: the three moves end to end — policy written, observed, judged, decision kept",
          d.get("decision") in ("ROUTE", "HOLD") and (root / "ev" / "policy.json").exists()
          and (root / "ev" / "decision.json").exists() and d.get("policy") == pol, d)
    check("door: what could not be read is reported as unknown, not decided",
          all(e["provider"] == "grok" for e in ad.unknown(d)) and ad.eligible(d) == [] if d.get("decision") == "HOLD" else True, d)
    for n in ("stack/steps/tasks.py", "stack/steps/task_chain.py"):
        check(f"door: {n.split('/')[-1]} starts agent_task.py and never chooses the broker",
              "broker_dispatch" not in (WORK / n).read_text() and "agent_task.py" in (WORK / n).read_text())
    at = (WORK / "stack/steps/agent_task.py").read_text()
    check("door: agent_task.py is where a declared egress profile goes to the broker",
          "broker_dispatch.py" in at and "role_egress.profile_of(principal)" in at)
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- 7. a second instance beside the first
def instance_controls():
    """What the second cold start found (OPERATIONS §69): images named for the instance,
    docker/.env in step with instance.env, networks counted before the build."""
    comp = (WORK / "docker" / "compose.poc.yaml").read_text()
    imgs = re.findall(r"^\s+image: (\S+)", comp, re.M)
    ours = [i for i in imgs if "agentstack" in i]
    check("instance: every image of this stack is named for the instance",
          ours and all(i.startswith("${STACK:-agentstack}/") for i in ours), ours)
    check("instance: the candidate image a release builds is too",
          'CAND_IMAGE="$STACK/governed-runtime:cand-' in (WORK / "scripts" / "release.sh").read_text())
    root = Path(tempfile.mkdtemp(prefix="agentstack-inst-"))
    (root / "config").mkdir(); (root / "docker").mkdir()
    (root / "config" / "instance.env").write_text("# the second one\nSTACK=agst2\nHUB_PORT=8880\nPRELOOP_PROJECT=preloop-two\n")
    (root / "docker" / ".env").write_text("POC_HOST_DIR=/home/you/agent-stack-two\nSTACK=agentstack\n")
    subprocess.run(["bash", str(WORK / "scripts" / "instance_env.sh"), str(root)], check=True, timeout=30)
    got = dict(l.split("=", 1) for l in (root / "docker" / ".env").read_text().splitlines() if "=" in l)
    check("instance: docker/.env takes every key instance.env names, and keeps the rest",
          got == {"POC_HOST_DIR": "/home/you/agent-stack-two", "STACK": "agst2", "HUB_PORT": "8880", "PRELOOP_PROJECT": "preloop-two"}, got)
    subprocess.run(["bash", str(WORK / "scripts" / "instance_env.sh"), str(root)], check=True, timeout=30)
    check("instance: … and a second run changes nothing",
          (root / "docker" / ".env").read_text().count("STACK=") == 1 and dict(l.split("=", 1) for l in (root / "docker" / ".env").read_text().splitlines() if "=" in l) == got)
    (root / "config" / "instance.env").unlink()
    subprocess.run(["bash", str(WORK / "scripts" / "instance_env.sh"), str(root)], check=True, timeout=30)
    check("instance: no instance.env, nothing written", dict(l.split("=", 1) for l in (root / "docker" / ".env").read_text().splitlines() if "=" in l) == got)
    up = (WORK / "scripts" / "up.sh").read_text(); rs = (WORK / "scripts" / "restore.sh").read_text()
    check("instance: up.sh and restore.sh write it through the one script",
          'scripts/instance_env.sh" "$HERE"' in up and 'scripts/instance_env.sh" "$WORKSPACEU"' in rs)
    ins = (WORK / "scripts" / "install.sh").read_text()
    check("instance: the host check counts network headroom before a build can run out",
          "network headroom" in ins and "NEED_NETS=15" in ins and "default-address-pools" in ins)
    check("instance: 15 is what the composition actually has, plus Preloop's one",
          len(re.findall(r"^  [a-z][a-z-]*:\s*$", comp.split("\nnetworks:\n", 1)[1].split("\n\n")[0], re.M)) + 1 == 15,
          comp.split("\nnetworks:\n", 1)[1].split("\n\n")[0][:200])
    shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- 8. the panel starts nothing
def panel_controls():
    """#24, decided 2026-10-02: starting a run is a command. The panel lists workflows, what each
    takes and the command; it offers no start. Stopping a run that is going stays a person's."""
    hub = (WORK / "hub" / "index.html").read_text()
    srv = (WORK / "ops" / "server.py").read_text()
    check("panel: no start and no precheck on the page",
          'id="start"' not in hub and 'id="precheck"' not in hub and 'api("/api/runs", {' not in hub)
    check("panel: the page shows the command instead, and says it does not start",
          'id="wf-command"' in hub and "scripts/cycle.sh ${name}" in hub and "이 화면은 시작하지 않습니다" in hub)
    check("panel: the ops API has no start endpoint", 'run_workflow.py", "start"' not in srv
          and "POST /api/runs  body" not in srv)
    check("panel: stopping a run that is going is still the panel's", "/stop" in srv and "data-stop" in hub)
    check("panel: resume went with start — no button, no endpoint, the command shown instead",
          "data-resume" not in hub and '/resume", p)' not in srv and "run_workflow.py resume" in hub)
    check("panel: the contract says so in its own words",
          "shows the command" in (WORK / "CONTRACT.md").read_text())


policy_controls()
codex_controls()
kept_controls()
grok_posture_controls()
state_controls()
bind_controls()
fanout_controls()
run_controls()
event_controls()
execution_controls()
door_controls()
instance_controls()
panel_controls()
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
