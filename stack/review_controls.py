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
elif [ "$(cat {root}/mode)" = expired ]; then
  printf '[{{"provider":"claude","source":"oauth","error":{{"message":"Claude OAuth token expired. CodexBar CLI does not launch Claude to refresh credentials. Run `claude login`, then retry."}}}}]'
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
    # #44: the login's token expired. The kept reading stands in, and *why* it will not be
    # refreshed travels with it — so the router can say "sign in" instead of "stale".
    e = collect("expired", 0)
    check("#44: an expired login is named as the kind of failure beside the kept reading",
          e["source"] == "cache:codexbar:oauth" and e.get("live_failed_kind") == "login_expired", e)
    check("#44: a 429 is a different kind", c.get("live_failed_kind") == "rate_limited", c.get("live_failed_kind"))
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    pol = {"candidates": ["claude"], "max_age_s": 1800, "require_windows": {"claude": ["weekly"]},
           "max_used_percent": {"session": 80, "weekly": 90}}
    def route(age, kind):
        d2 = Path(tempfile.mkdtemp(prefix="agentstack-r44-"))
        json.dump(pol, open(d2 / "p.json", "w"))
        o = {**e, "observed_at": (now - timedelta(seconds=age)).isoformat()}
        if kind is None:
            o.pop("live_failed_kind", None); o.pop("live_failed", None)
        else:
            o["live_failed_kind"] = kind
        json.dump(o, open(d2 / "claude.json", "w"))
        r = json.loads(subprocess.run([sys.executable, str(HERE / "router.py"), str(d2 / "p.json"), str(d2)],
                                      capture_output=True, text=True, env={**os.environ, "ROUTER_NOW": now.isoformat()}).stdout)
        shutil.rmtree(d2, ignore_errors=True)
        return r["evaluated"][0]
    young = route(60, "login_expired")
    check("#44: a kept reading still young enough is used, and the dead login is said beside the verdict",
          young["eligible"] is True and young.get("login_expired") is True, young)
    old = route(27152, "login_expired")
    check("#44: aged out behind an expired login it is unknown — a person's job — with the remedy",
          old["eligible"] is False and old["why"].startswith("unknown: the login's token expired") and "sign in on the panel" in old["why"], old["why"])
    check("#44: aged out for any other reason it is still stale, the ordinary word",
          route(27152, None)["why"].startswith("stale:") and route(27152, "rate_limited")["why"].startswith("stale:"))
    import importlib.util as il
    spec = il.spec_from_file_location("oh_fb", str(HERE / "ops_health.py"))
    oh = il.module_from_spec(spec); spec.loader.exec_module(oh)
    check("#44: the standing risk's remedy names the expired token and why the login check still says true",
          "token expired" in oh.fix_for({"provider": "claude", "why": old["why"]}) and "login check" in oh.fix_for({"provider": "claude", "why": old["why"]}))
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
    # the temporary root holds the state only; the packages and their declaration are this tree's
    env = {**os.environ, "AGENTSTACK_ROOT": str(root), "AGENTSTACK_PACKAGES": str(WORK / "packages"),
           "AGENTSTACK_PACKAGES_YAML": str(WORK / "config" / "packages.yaml"),
           "AGENTSTACK_PACKAGES_LOCAL": str(WORK / "config" / "packages.local.yaml")}
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
    # behaviour, not text (§82): cycle.run on a temporary ops directory, with the runner it starts
    # replaced by one that only records the argv it was given
    cy = importlib.import_module("cycle")
    with tempfile.TemporaryDirectory() as ops:
        cy.OPS_DIR, cy.LOCK, cy.RECORD = ops, f"{ops}/.cycle.lock.d", f"{ops}/cycles.jsonl"
        seen = []
        class _P:  # what subprocess.run returns
            returncode = 0; stdout = '{"state": "ok"}'; stderr = ""
        real_run = cy.subprocess.run
        cy.subprocess.run = lambda argv, **kw: (seen.append(list(argv)), _P)[1]
        try:
            row = cy.run("hello-lane", "research-default", by="control", inputs={"text": "a b", "day": "2026-10-03"})
        finally:
            cy.subprocess.run = real_run
        started = next((a for a in seen if "run_workflow.py" in " ".join(a)), [])
        check("cycle: the inputs reach the run's argv, each as key=value, a space kept",
              started[-2:] == ["day=2026-10-03", "text=a b"] and started[2:5] == ["start", row.get("ui"), "hello-lane"], started)
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
          'id="wf-command"' in hub and 'const tmpl = wf.command || "";' in hub and "이 화면은 시작하지 않습니다" in hub)
    check("panel: the ops API has no start endpoint", 'run_workflow.py", "start"' not in srv
          and "POST /api/runs  body" not in srv)
    check("panel: stopping a run that is going is still the panel's", "/stop" in srv and "data-stop" in hub)
    check("panel: configuration is applied by command — no button, no endpoint, the state still shown",
          "cfg-apply" not in hub and "/api/config/apply" not in srv and "/api/config/generate" not in srv
          and "/api/config/status" in srv and "cfg.py apply" in hub)
    check("panel: resume went with start — no button, no endpoint, the command shown instead",
          "data-resume" not in hub and '/resume", p)' not in srv and "run_workflow.py resume" in hub)
    check("panel: the contract says so in its own words",
          "shows the command" in (WORK / "CONTRACT.md").read_text())


# ---------------------------------------------------------------- 9. the next five (#13 #22 #23 #25 #26)
def next_controls():
    """Execution facts collected by the platform; a child run linked to its parent; the
    documented examples executed; the contract version carried; the own-runtime contract."""
    sys.path.insert(0, str(HERE))
    rw = importlib.import_module("run_workflow"); rs = importlib.import_module("runstate")
    # #13: a run started from inside another run knows its parent and inherits the labels
    rs.RUNS = Path(tempfile.mkdtemp(prefix="agentstack-child-"))
    d = rs.RUNS / "parent-0000aaaa" / "tmp" / "conductor"; d.mkdir(parents=True)
    (d / "conductor-p281-x-20260923-000000-cafe1234.events.jsonl").write_text("")
    rw.meta_path("parent-0000aaaa").write_text(json.dumps({"ui_id": "parent-0000aaaa", "suite": "s9", "case": "c3", "state": "running"}))
    check("child: a run a step starts carries the parent's Conductor id and inherits suite/case",
          rw.child_context(env={"CONDUCTOR_SELF_RUN_ID": "cafe1234"}) == ("cafe1234", "s9", "c3"))
    check("child: labels the caller gave are kept", rw.child_context("mine", "", env={"CONDUCTOR_SELF_RUN_ID": "cafe1234"}) == ("cafe1234", "mine", ""))
    check("child: a run started by a person has no parent", rw.child_context(env={}) == ("", "", ""))
    check("child: the parent travels to the child's Conductor and into its record",
          '"AGENTSTACK_PARENT_RUN": parent' in (HERE / "run_workflow.py").read_text()
          and '"parent.run_id": parent' in (HERE / "steps" / "record.py").read_text())
    shutil.rmtree(rs.RUNS, ignore_errors=True)
    # #22: the recorder reads what the evidence holds, listed or not
    root = Path(tempfile.mkdtemp(prefix="agentstack-evid-"))
    (root / "config" / "generated").mkdir(parents=True)
    rt = json.loads(json.dumps(__import__("settings").DEFAULT_RUNTIME))
    rt["paths"]["evidence_root"] = str(root / "evidence")
    (root / "config" / "generated" / "runtime.json").write_text(json.dumps(rt))
    ex = importlib.import_module("execution")
    for name, rec in (("r7-a-claude", {"run_id": "r7-a-claude", "provider": "claude", "status": "FAILED"}),
                      ("r7-a-claude-a2", {"run_id": "r7-a-claude-a2", "provider": "claude", "status": "COMPLETED"}),
                      ("r7-x", {"status": "FAILED"})):                     # not an execution: no provider
        ex.write(root / "evidence" / name, ex.record(**rec))
    (root / "evidence" / "r8-other-codex").mkdir(); ex.write(root / "evidence" / "r8-other-codex", ex.record(run_id="r8-other-codex", provider="codex"))
    code = ("import json, sys; sys.path.insert(0, '/work/stack'); sys.path.insert(0, '/work/stack/steps'); import record; "
            "ex, errs = record.executions_of(json.loads(sys.argv[1])); print(json.dumps([e['run_id'] for e in ex]))")
    env = {**os.environ, "AGENTSTACK_ROOT": str(root), "CONDUCTOR_SELF_RUN_ID": "r7"}
    r = subprocess.run([sys.executable, "-c", code, "{}"], env=env, capture_output=True, text=True, timeout=60)
    check("evidence: a run that listed nothing is recorded with every call its evidence holds, and no other run's",
          r.stdout.strip() == '["r7-a-claude", "r7-a-claude-a2"]', r.stdout + r.stderr[-300:])
    r = subprocess.run([sys.executable, "-c", code, json.dumps({"execute": {"run_id": "r7-a-claude-a2", "provider": "claude", "status": "COMPLETED"}})],
                       env=env, capture_output=True, text=True, timeout=60)
    check("evidence: what the step listed and what the evidence holds join on run_id, nothing twice",
          sorted(json.loads(r.stdout or "[]")) == ["r7-a-claude", "r7-a-claude-a2"], r.stdout + r.stderr[-300:])
    r = subprocess.run([sys.executable, "-c", code, "{}"], env={**env, "CONDUCTOR_SELF_RUN_ID": "manual"}, capture_output=True, text=True, timeout=60)
    check("evidence: no Conductor run, nothing read", r.stdout.strip() == "[]", r.stdout + r.stderr[-300:])
    shutil.rmtree(root, ignore_errors=True)
    # #23: the documented examples run; a duplicate key is caught
    de = importlib.import_module("doc_examples")
    rows = de.check(str(WORK / "docs" / "packages.md"))
    check("examples: every example in docs/packages.md passes", rows and all(not v.startswith("FAIL") for _, _, v in rows), [v for _, _, v in rows if v.startswith("FAIL")])
    check("examples: the manifest example is read as a package by the stack's reader", any("a usable package" in v for _, _, v in rows))
    bad = Path(tempfile.mkdtemp(prefix="agentstack-doc-")) / "d.md"
    bad.write_text("```yaml\nname: x\nentry: w.yaml\nrequires:\n  capabilities: [egress]\nrequires:\n  python: [a]\n```\n")
    v = de.check(str(bad))[0][2]
    check("examples: a duplicate key is a failure, not the last value", v.startswith("FAIL duplicate key 'requires'"), v)
    shutil.rmtree(bad.parent, ignore_errors=True)
    check("examples: the static level runs them", "doc_examples.py" in (WORK / "scripts" / "verify.sh").read_text())
    check("contract: the receipt and a chain carry the version",
          '"contract": execution.CONTRACT' in (HERE / "steps" / "tasks.py").read_text()
          and '"contract": execution.CONTRACT' in (HERE / "steps" / "task_chain.py").read_text())
    # #25: the own-runtime contract names the doors
    c = (WORK / "CONTRACT.md").read_text()
    check("own runtime: the contract says every model call goes through agent_task.py and names what such a package may not do",
          "## A package that brings its own runtime" in c and "Every model call goes through" in c and "may not do" in c)


# ---------------------------------------------------------------- 10. the adapter, replayed (#27)
def adapter_controls():
    """run-agent.mjs's model-free halves (stack/adapter/*.mjs) reproduce what the adapter wrote
    on the instance for four recorded runs; the step's failure line reads the denial."""
    fx = WORK / "stack" / "fixtures" / "run-agent"
    import hashlib
    idx = (fx / "INDEX.txt").read_text()
    bad = [m.group(1) for m in re.finditer(r"(\S+)\s+(\d+) B\s+sha256:([0-9a-f]+)", idx)
           if not hashlib.sha256((fx / m.group(1)).read_bytes()).hexdigest().startswith(m.group(3))]
    check("adapter: the fixtures are the ones the instance recorded (index hashes hold)", bad == [], bad)
    r = subprocess.run(["node", str(WORK / "stack" / "adapter" / "replay.mjs")], capture_output=True, text=True, timeout=120)
    check("adapter: four recorded runs replay through result.mjs — text, usage, denials, status, the whole result",
          r.returncode == 0 and "4/4 recorded runs replayed" in r.stdout, (r.stdout + r.stderr)[-600:])
    r = subprocess.run(["node", str(WORK / "stack" / "adapter" / "providers_check.mjs")], capture_output=True, text=True, timeout=120)
    check("adapter: each provider module is a function of one call's context — login, principal, egress travel with it",
          r.returncode == 0 and "provider checks passed" in r.stdout, (r.stdout + r.stderr)[-600:])
    ra = (WORK / "stack" / "run-agent.mjs").read_text()
    check("adapter: run-agent.mjs uses the modules and keeps no copy of the folded logic",
          all(x in ra for x in ("from \"/work/stack/adapter/result.mjs\"", "take(acc, ev)", "normalizeStatus(", "buildResult(", "permissionBody(", "ledgerLine("))
          and "Access denied:" not in ra.split("import { ledgerLine }")[1])
    ex = importlib.import_module("execution")
    deny = json.loads((fx / "grok-deny" / "result.json").read_text())
    ok = json.loads((fx / "claude-auto" / "result.json").read_text())
    check("adapter: a DENIED by an MCP rule says which rule, not \"{}\"",
          ex.failure_of(deny) == "Access denied: Scoped rule 2", ex.failure_of(deny))
    check("adapter: a completed call has no failure line", ex.failure_of(ok) == "")
    check("adapter: a permission refused by a person is named",
          ex.failure_of({"status": "DENIED", "permissions": [{"outcome": "reject_once", "denial": "denied", "title": "Write"}]}) == "permission denied: Write")
    check("adapter: the adapter's own failure wins",
          ex.failure_of({"status": "FAILED", "failure": {"message": "ENOENT: config.toml"}}) == "ENOENT: config.toml")


# ---------------------------------------------------------------- 11. the image is the toolchain (#34, §76)
def update_controls():
    """Every tool is installed under /opt in the image and nothing under $HOME; release.sh carries
    no toolchain and no flag; the docs say so; drift.sh says why a line has no answer (§75)."""
    df = (WORK / "docker" / "agent.Dockerfile").read_text()
    rel = (WORK / "scripts" / "release.sh").read_text()
    check("image: claude, uv/Conductor and the Preloop CLI install under /opt, each proven present at build",
          all(x in df for x in ("HOME=/opt/claude bash -c", "test -x /opt/claude/.local/bin/claude",
                                "--prefix=/opt/uv uv", "UV_TOOL_DIR=/opt/uv/tools UV_TOOL_BIN_DIR=/opt/uv/bin",
                                "test -x /opt/uv/bin/conductor", "INSTALL_DIR=/opt/preloop/bin", "test -x /opt/preloop/bin/preloop")))
    check("image: nothing is installed under /home/agent, and /home/agent/.local/bin is not on PATH",
          "/home/agent/.local" not in df.replace("Nothing of them is under /home/agent", "") and "PATH=/opt/claude/.local/bin:/opt/uv/bin:/opt/preloop/bin:" in df)
    check("image: the Preloop installer runs as the agent (it writes the agent's home), the rest as root, and the build proves /home/agent is all the agent's",
          df.index("chown agent:agent /opt/preloop/bin\nUSER agent\n") < df.index("sh /tmp/preloop-cli.sh")
          < df.index("chown -R root:root /opt/preloop") < df.index('RUN test -z "$(find /home/agent ! -user agent)"')
          and "RUN HOME=/root pip install" in df and "RUN HOME=/root UV_TOOL_DIR" in df)
    check("image: claude's self-update is off — the pin is the version", "DISABLE_AUTOUPDATER=1" in df)
    check("image: the three are world-readable for the role users a step runs as",
          all(f"chmod -R a+rX {d}" in df for d in ("/opt/claude", "/opt/uv", "/opt/preloop")))
    comp = (WORK / "docker" / "compose.poc.yaml").read_text()
    check("image: the replay service runs Conductor's venv where the image puts it",
          'entrypoint: ["/opt/uv/tools/conductor-cli/bin/python"]' in comp and "/home/agent/.local" not in comp)
    check("release: a record carries no toolchain archive, an update stages and swaps nothing and has no flag — a release is revision + images + configuration",
          all(x not in rel for x in ("tar czf /out/toolchain.tar.gz", "verify_staged", "swap_staged", "keep_or_restore_toolchain",
                                     "REPLACE_TOOLCHAIN=1", "VOLUME_TOOLS", "refusing an update whose toolchain"))
          and "format=3" in rel and 'say "will change $t"' in rel)
    check("release: a record from before #34 still rolls back — its archive is restored into the volume, verified first (§79)",
          'if [ -f "$SRC/toolchain.tar.gz" ]; then' in rel and "OLD_TOOLCHAIN=1" in rel)
    ud = (WORK / "docs" / "update-day.md").read_text()
    check("docs: update-day.md has no flag and says the rebuild changes every tool",
          "--replace-toolchain]" not in ud and "There is\nno flag" in ud.replace("There is no flag", "There is\nno flag")
          and "Every tool is the image's" in ud)
    check("docs: the runbook's release line matches release.sh",
          "**A release is** *code revision + image ids + configuration*" in (WORK / "docs" / "runbook.md").read_text())
    up = (WORK / "scripts" / "up.sh").read_text()
    check("instance: up.sh --check names an unused pre-#34 toolchain copy in the volume, with the command, and does not remove it",
          "pre-#34 toolchain copy" in up and "alpine rm -rf /vol/.local" in up
          and up.index("test -d /home/agent/.local/share/claude") < up.index('echo "        docker run --rm'))
    # #37: the Preloop CLI lists an agent only once its config file exists; a fresh home has none
    bp = importlib.import_module("bootstrap_preloop")
    import tempfile
    with tempfile.TemporaryDirectory() as home:
        made = [bp.seed_for(k, home) for k in ("claude-code", "codex", "grok")]
        cx = Path(home) / ".codex" / "config.toml"; cl = Path(home) / ".claude" / "settings.json"
        check("onboarding: the bootstrap seeds the file each vendor's CLI must have before Preloop sees it — codex's empty, claude's {}",
              cx.is_file() and cx.read_text() == "" and cl.is_file() and json.loads(cl.read_text()) == {} and made[2] is None, made)
        cx.write_text("model_provider = 'preloop'\n")
        bp.seed_for("codex", home)
        check("onboarding: a file that exists is left alone", cx.read_text() == "model_provider = 'preloop'\n")
    # behaviour, not text (§82): onboard() with the Preloop CLI replaced by one that notes, at the
    # moment it is asked, whether each vendor's file is already there
    with tempfile.TemporaryDirectory() as home:
        present_when_asked = {}
        class _R: returncode = 0; stdout = ""; stderr = ""
        def fake_run(argv, **kw):
            if argv[:3] == ["preloop", "agents", "onboard"]:
                kind = argv[3]
                rel = bp.SEED.get(kind, ("",))[0]
                present_when_asked[kind] = bool(rel) and os.path.exists(os.path.join(home, rel))
            return _R
        real_run, real_home = bp.subprocess.run, os.environ.get("HOME")
        bp.subprocess.run = fake_run; os.environ["HOME"] = home
        try:
            problem = bp.onboard("http://preloop.test", "key", ["claude-code", "codex"])
        finally:
            bp.subprocess.run = real_run
            if real_home is not None: os.environ["HOME"] = real_home
        check("onboarding: the seed happens for every kind the claim onboards, before the CLI is asked",
              problem is None and present_when_asked == {"claude-code": True, "codex": True}, (problem, present_when_asked))
    dr = (WORK / "scripts" / "drift.sh").read_text()
    check("drift: four states, and an unanswered line carries the registry's reason",
          all(w in dr for w in ('state="same"', 'state="newer"', 'state="unasked"', 'state="unanswered"', "UNANSWERED+=", '"reason":"%s"')))
    check("drift: verify.sh prints the summary line, not only 'nothing newer'",
          'note "drift: $(tail -1 <<<"$drift")"' in (WORK / "scripts" / "verify.sh").read_text())
    # --offline: this runs inside the governed runtime at the stack level, which has no egress, and
    # eleven asks that each wait for a timeout are what made cold-start run 52 fail (§75)
    r = subprocess.run(["bash", str(WORK / "scripts" / "drift.sh"), "--offline"], capture_output=True, text=True, timeout=60)
    out = [l for l in r.stdout.splitlines() if l.strip()]
    states = [l.split()[3] for l in out[1:-1]]
    check("drift: the shape, without a registry — 14 lines, 11 unanswered as 'not asked', 3 unasked, and the last line counts them",
          r.returncode == 0 and len(states) == 14 and states.count("unanswered") == 11 and states.count("unasked") == 3
          and out[-1].startswith("11 of 14 lines unanswered") and "not asked (--offline)" in out[-1],
          (r.returncode, states, out[-1:], r.stderr[-300:]))


# ---------------------------------------------------------------- 12. review 3: the contract across repeat, resume, rollback (§79)
def review3_controls():
    """The six findings of the third review, each reproduced without a model where it can be."""
    import tempfile, types
    # (2) a call made twice is two calls: the second's evidence sits beside the first's
    at = (HERE / "steps" / "agent_task.py").read_text()
    src = at[at.index("def _own_evidence_dir(base):"):at.index("    return rid, f\"{root}/{rid}\"") + len("    return rid, f\"{root}/{rid}\"")]
    with tempfile.TemporaryDirectory() as root:
        ns = {"os": os, "RT": {"paths": {"evidence_root": root}}}
        exec(src, ns)
        own = ns["_own_evidence_dir"]
        first = own("run-repair-claude")
        check("calls: the first call of a label takes the plain name", first[0] == "run-repair-claude", first)
        os.makedirs(first[1]); Path(first[1], "execution.json").write_text("{}")
        second = own("run-repair-claude")
        os.makedirs(second[1]); Path(second[1], "result.json").write_text("{}")
        third = own("run-repair-claude")
        check("calls: the same label again is -r2, then -r3 — never the same directory",
              (second[0], third[0]) == ("run-repair-claude-r2", "run-repair-claude-r3"), (second[0], third[0]))
        os.makedirs(f"{root}/run-x-codex")            # an empty directory is this call's own, not a repeat
        check("calls: an empty directory left by a door that re-executed is not read as a repeat",
              own("run-x-codex")[0] == "run-x-codex")
        retry = own("run-repair-claude-a2")
        check("calls: a retry's own name (-a2) is kept and repeats under it (-a2-r2)",
              retry[0] == "run-repair-claude-a2" and (os.makedirs(retry[1]), Path(retry[1], "x").write_text(""), own("run-repair-claude-a2")[0])[2] == "run-repair-claude-a2-r2")
    check("calls: the name is decided after the door, by the process that makes the call",
          at.index("\"broker_dispatch.py\")] + sys.argv[1:])") < at.index("run_id, evid = _own_evidence_dir(run_id)") < at.index("os.makedirs(evid, exist_ok=True)"))
    check("calls: the retry number travels through the broker to the runner's environment",
          '"attempt": os.environ.get("AGENTSTACK_ATTEMPT", "")' in (HERE / "steps" / "broker_dispatch.py").read_text()
          and '"attempt": str(req.get("attempt") or "")' in (HERE / "broker.py").read_text()
          and '"AGENTSTACK_ATTEMPT": str(job["attempt"])' in (HERE / "profile_runner.py").read_text())
    check("calls: the adapter's own refresh retry keeps the first attempt — its result file, its cost, both outcomes",
          'os.path.join(evid, "result.a1.json")' in at and "t1, w1 = _cost(first)" in at and '"attempt_outcomes": [first.get("status"' in at)
    check("calls: the trajectory still counts a retry that was also repeated",
          r'-a\d+(?:-r\d+)?$' in (HERE / "trajectory.py").read_text())

    # (3) one execution named twice is one record, the evidence whole and the passed fields on it
    rec_src = (HERE / "steps" / "record.py").read_text()
    with tempfile.TemporaryDirectory() as root:
        rt = {"paths": {"evidence_root": root, "workspace_root": root, "logins_root": root}}
        gen = Path(root) / "config" / "generated"; gen.mkdir(parents=True)
        (gen / "runtime.json").write_text(json.dumps(rt))
        ex = importlib.import_module("execution")
        d = Path(root) / "r1-E1-claude"; d.mkdir()
        ex.write(str(d), ex.record(run_id="r1-E1-claude", provider="claude", status="COMPLETED", produced=True,
                                   evidence_dir=str(d), measurements={"total_tokens": 300, "wall_ms": 10}, model_served="m"))
        env = {**os.environ, "AGENTSTACK_ROOT": root, "CONDUCTOR_SELF_RUN_ID": "r1"}
        code = ("import json,sys; sys.path.insert(0,'/work/stack'); sys.path.insert(0,'/work/stack/steps'); import record as R; "
                "ex,err=R.executions_of({'execute': {'run_id':'r1-E1-claude','provider':'claude','status':'COMPLETED'}}, 'r1'); "
                "print(json.dumps([ex, err]))").replace("/work/stack", str(HERE))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
        try:
            exs, errs = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            exs, errs = [], [r.stderr[-300:]]
        check("record: a partial `execute` and the evidence directory are one record with the evidence's measurements",
              len(exs) == 1 and exs[0].get("measurements", {}).get("total_tokens") == 300 and exs[0].get("model_served") == "m"
              and "model_session_reported" in exs[0], (exs, errs))

    # (4) a resumed run is a new segment of the same log; the parent travels with a resume
    rv = importlib.import_module("runevents")
    with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
        for e in [{"type": "agent_started", "data": {"agent_name": "a"}, "timestamp": "t1"},
                  {"type": "workflow_failed", "data": {"output": {"x": 1}}, "timestamp": "t2"},
                  {"type": "agent_started", "data": {"agent_name": "b"}, "timestamp": "t3"}]:
            f.write(json.dumps(e) + "\n")
        path = f.name
    v = rv.read(path)
    check("resume: a step that starts after a failure is read as a run that is going again — not ended, no stale output",
          v["ended"] is False and v["completed_ok"] is False and v["output"] is None and v["current_step"] == "b" and v["segment"] == 1 and len(v["steps"]) == 2,
          {k: v[k] for k in ("ended", "output", "current_step", "segment")})
    with open(path, "a") as f:
        f.write(json.dumps({"type": "workflow_completed", "data": {"output": {"y": 2}}, "timestamp": "t4"}) + "\n")
    v = rv.read(path)
    check("resume: the segment's own end is the run's end", v["ended"] and v["completed_ok"] and v["output"] == {"y": 2})
    os.unlink(path)
    check("resume: the saved parent is in a resumed run's environment",
          '"AGENTSTACK_PARENT_RUN": str(meta.get("parent") or "")' in (HERE / "run_workflow.py").read_text())

    # (5) an observation directory holds this collection's files and no other's
    ad = importlib.import_module("admission")
    with tempfile.TemporaryDirectory() as root:
        obs = Path(root) / "obs"; obs.mkdir(); (obs / "claude.json").write_text('{"stale": true}')
        err = ad.collect({"model_route": {}, "login": {}, "reuse_s": 0}, str(obs), timeout=0.001)
        check("admission: a collection that failed leaves no earlier file for the router to read",
              bool(err) and not list(obs.glob("*.json")), (err, [p.name for p in obs.glob("*")]))

    # (1) a rollback to a release from before #34 restores its toolchain archive into the volume
    rel = (WORK / "scripts" / "release.sh").read_text()
    check("rollback: a pre-#34 archive is unpacked and verified (claude, conductor, preloop) before anything moves",
          "tar xzf /in/toolchain.tar.gz -C /vol/.local.new" in rel and "for t in claude conductor preloop; do" in rel
          and rel.index("for t in claude conductor preloop; do") < rel.index('docker stop "$AGENT" >/dev/null 2>&1 || true\n  if [ "$OLD_TOOLCHAIN" = 1 ]'))
    check("rollback: the swap into /home/agent/.local happens only after everything verified, keeps what was there, and clears it after the checks pass",
          "mv /vol/.local.new /vol/.local" in rel and ".local.old" in rel
          and rel.index('[ "$OLD_TOOLCHAIN" = 0 ] || docker run --rm -v "$STACK-agent-home:/vol" alpine rm -rf /vol/.local.old')
              > rel.index("reapply_policy || exit 1\n  [ \"$OLD_TOOLCHAIN\""))
    # behaviour (§84): the archive check itself, the same text the alpine container runs, on an
    # unpacked archive shaped like pre-202610's — bin/claude an absolute symlink into
    # /home/agent/.local (dangling here), bin/preloop a relative one, bin/conductor a file
    import re as _re84, subprocess as _sp84, tempfile as _tf84, os as _os84
    _fn = _re84.search(r"TOOLCHAIN_USABLE='(.*?)'\n", rel, _re84.S).group(1)
    def _usable(remove=None):
        with _tf84.TemporaryDirectory() as d:
            for sub in ("bin", "share/claude/versions", "share/preloop/bin"):
                _os84.makedirs(f"{d}/{sub}")
            open(f"{d}/share/claude/versions/2.1.278", "w").write("#!/bin/sh\n")
            open(f"{d}/share/preloop/bin/preloop", "w").write("#!/bin/sh\n")
            open(f"{d}/bin/conductor", "w").write("#!/bin/sh\n")
            _os84.symlink("/home/agent/.local/share/claude/versions/2.1.278", f"{d}/bin/claude")
            _os84.symlink("../share/preloop/bin/preloop", f"{d}/bin/preloop")
            if remove:
                _os84.unlink(f"{d}/{remove}")
            r = _sp84.run(["sh", "-c", _fn + f"\ntoolchain_usable {d}"], capture_output=True, text=True)
            return r.returncode, r.stderr.strip()
    _ok = _usable()
    _no_claude = _usable("share/claude/versions/2.1.278")
    _no_preloop = _usable("share/preloop/bin/preloop")
    check("rollback: an archive whose bin/claude is an absolute symlink into /home/agent/.local verifies where it is unpacked",
          _ok == (0, ""), _ok)
    check("rollback: and a link whose target is really missing is still refused, naming the tool",
          _no_claude[0] == 1 and "no claude" in _no_claude[1] and _no_preloop[0] == 1 and "no preloop" in _no_preloop[1],
          (_no_claude, _no_preloop))
    check("rollback: nothing says the archive is left alone any more", "not used; the kept images carry the toolchain" not in rel)

    # (6) the command a person copies runs as printed; the first-use path in the docs runs
    hub = (WORK / "hub" / "index.html").read_text()
    check("hub: the command is the API's quoted string, the profile shell-quoted here, a placeholder named",
          "function shq(v)" in hub and 'tmpl.replace("{profile}", prof ? shq(prof)' in hub and "값으로 바꿔 넣습니다" in hub and '${i.default || "<" + i.name + ">"}' not in hub)
    check("hub: the package login line does not depend on the needs list, and an empty login object is no login",
          "const lg = wf.login && wf.login.package ? wf.login : null;" in hub and 'if (lg && $("#pkg-login"))' in hub)
    check("hub: the consoles' addresses come from the ops API — no fixed MLflow port in the run detail",
          "http://127.0.0.1:5000/#/experiments" not in hub and "await ensureLinks();" in hub and 'data-link="preloop"' in hub)
    check("hub: a failed read of the approvals leaves the table and its drafts in place",
          "if (!Array.isArray(a)) {" in hub and hub.index("if (!Array.isArray(a)) {") < hub.index("const typed = {}; let focused = null;"))
    inst = (WORK / "docs" / "install.md").read_text()
    m = re.search(r"run_workflow\.py start (\S+) ", inst)
    check("docs: the install example declares the package before running it, and its run id is one run_workflow.py accepts",
          "packages.local.yaml" in inst and "scripts/packages.sh install" in inst and bool(m) and re.fullmatch(r"[a-z0-9-]{6,40}", m.group(1) or "") is not None,
          m.group(1) if m else None)


# ---------------------------------------------------------------- 13. one fact, one place (§80)
def ease_controls():
    """Providers, in-network addresses and the stack's own paths are each written once; the rest
    reads them. Measured as absence: the literal does not appear a second time."""
    st = importlib.import_module("settings")
    mods = sorted(p.stem for p in (HERE / "adapter" / "providers").glob("*.mjs"))
    check("providers: settings.PROVIDERS is the module list under stack/adapter/providers/", sorted(st.PROVIDERS) == mods, (sorted(st.PROVIDERS), mods))
    cfg = importlib.import_module("cfg")
    check("providers: cfg.py validates against the same table", cfg.KNOWN_PROVIDERS is st.PROVIDERS)
    pyfiles = [p for p in list(HERE.rglob("*.py")) + list((WORK / "ops").glob("*.py")) if not p.name.endswith("_controls.py") and p.name != "settings.py" and "fixtures" not in p.parts]
    lit = re.compile(r'[\(\[\{]\s*"claude",\s*"codex",\s*"grok"\s*[\)\]\}]')
    bad = [str(p.relative_to(WORK)) for p in pyfiles if lit.search(p.read_text())]
    check("providers: no second list of the three in the Python", bad == [], bad)
    srv = (WORK / "ops" / "server.py").read_text()
    check("providers: the ops API reads the provider modules that exist, not a set of its own", "def providers():" in srv and 'PROVIDERS = {"claude"' not in srv)
    hosts = re.compile(r'http://(console|api:8000|broker:8791|egress:8888|mlflow:5000)\b')
    files = [p for p in list(HERE.rglob("*.py")) + list(HERE.glob("*.mjs")) + list((HERE / "adapter" / "providers").glob("*.mjs")) + list(HERE.glob("*.sh")) + [WORK / "scripts" / "up.sh"]
             if p.name != "settings.py" and not p.name.endswith("_controls.py") and "fixtures" not in p.parts]
    bad = sorted({f"{p.relative_to(WORK)}:{i}" for p in files for i, l in enumerate(p.read_text().splitlines(), 1)
                  if hosts.search(l) and not l.lstrip().startswith("#") and not l.lstrip().startswith("//")})
    check("addresses: no in-network address is written outside settings.py (code lines of stack/, the adapter, up.sh)", bad == [], bad)
    check("addresses: the adapter reads the generated settings or says to generate them — no fallback copy",
          "run `cfg.py generate`" in (HERE / "run-agent.mjs").read_text() and 'need(RT.preloop?.api_url' in (HERE / "run-agent.mjs").read_text())
    check("addresses: up.sh probes the addresses the settings name, read once from the agent",
          "read -r RT_API RT_MCP RT_MLFLOW RT_PROXY" in (WORK / "scripts" / "up.sh").read_text())
    check("addresses: settings.url falls back to the one default table",
          st.url("broker", "url") == st.DEFAULT_RUNTIME["broker"]["url"] and st.url("preloop", "api_url").startswith("http://"))
    # ops/server.py runs in another container and names the agent's interpreter to exec into it —
    # that is not its own interpreter, and it is named there once
    interp = [str(p.relative_to(WORK)) for p in pyfiles if "/opt/venv/bin/python" in p.read_text() and p.name != "server.py"]
    check("paths: no Python module of the stack writes its own interpreter's path — sys.executable, or the package's POC_PY", interp == [], interp)
    check("paths: the ops API names the agent's interpreter once", srv.count("/opt/venv/bin/python") == 1)
    stackp = [f"{p.relative_to(WORK)}" for p in HERE.rglob("*.py") if not p.name.endswith("_controls.py") and "fixtures" not in p.parts
              and re.search(r'"/work/stack/[A-Za-z_]+(?:/[A-Za-z_]+)*\.(?:py|mjs)"', p.read_text())]
    check("paths: no module names another module of the stack by an absolute path — __file__ and settings.STACK", stackp == [], stackp)
    counts = {f: (WORK / "scripts" / f).read_text().count("/opt/venv/bin/python") for f in ("up.sh", "down.sh", "packages.sh", "verify.sh")}
    check("paths: each script names the agent's interpreter once (PY_IN_AGENT)", all(v == 1 for v in counts.values()), counts)
    check("paths: the ops API names the stack's mount once", srv.count('"/work/stack') == 1 and 'STACK = "/work/stack"' in srv, srv.count('"/work/stack'))


# ---------------------------------------------------------------- 14. the first-use path (§81)
def firstuse_controls():
    """The command a person copies is built once (run_workflow.py), parses as a shell would, and
    the panel shows that string; the stack level runs it (verify.sh)."""
    import shlex
    # described() on this checkout, the way verify.sh's static level points packages.py at it
    env = {**os.environ, "AGENTSTACK_ROOT": str(WORK), "AGENTSTACK_PACKAGES": str(WORK / "packages"),
           "AGENTSTACK_PACKAGES_YAML": str(WORK / "config" / "packages.yaml"),
           "AGENTSTACK_PACKAGES_LOCAL": str(WORK / "config" / "packages.local.yaml")}
    r = subprocess.run([sys.executable, "-c", "import sys, json; sys.path.insert(0, sys.argv[1]); import run_workflow; print(json.dumps(run_workflow.described()))", str(HERE)],
                       capture_output=True, text=True, env=env, timeout=120)
    try:
        rows = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        rows = {}
    cmds = {k: v.get("command", "") for k, v in rows.items()}
    check("first use: every workflow the stack offers has a command, and each parses as a shell would",
          bool(cmds) and all(c.startswith("scripts/cycle.sh ") and "{profile}" in c and shlex.split(c.replace("{profile}", "p")) for c in cmds.values()), cmds)
    hl = cmds.get("hello-lane", "")
    toks = shlex.split(hl.replace("{profile}", "research-default"))
    check("first use: hello-lane's command carries its default with the space intact after shell parsing",
          toks[:3] == ["scripts/cycle.sh", "hello-lane", "research-default"] and any(t.startswith("text=") and " " in t for t in toks), toks)
    req = [c for c in cmds.values() if "'<" in c]
    check("first use: a required input with no default is a quoted, named placeholder — never bare angle brackets",
          all("<" not in c.replace("'<", "").replace(">'", "") for c in cmds.values()), req)
    hub = (WORK / "hub" / "index.html").read_text()
    check("first use: the panel shows the API's command and only puts the profile in",
          "const tmpl = wf.command || \"\";" in hub and 'tmpl.replace("{profile}"' in hub and "slot(i.name)" not in hub)
    vs = (WORK / "scripts" / "verify.sh").read_text()
    check("first use: the stack level runs that string from the checkout and requires the cycle to complete",
          'FU_CMD="$(in_agent /work/stack/run_workflow.py workflows --detail' in vs and 'bash -c "$FU_CMD"' in vs and '"completed_ok": true' in vs.split("FU_UI=")[1])


# ---------------------------------------------------------------- 15. what the controls pin (§82)
# ---------------------------------------------------------------- 21. the package feedback round (#51–#55)
def feedback_controls():
    """What the devflow author's findings asked of the stack (issues #51–#55), as behaviour."""
    import importlib.util as il
    spec = il.spec_from_file_location("step_fb", str(HERE / "steps" / "step.py"))
    st = il.module_from_spec(spec); spec.loader.exec_module(st)
    # #52: the crash's key is the step's to name; the shape decides every other key
    rc, out = quiet(lambda: st.main(lambda: 1 / 0, "error", decision="", reason=""))
    row = json.loads(out.strip().splitlines()[-1])
    check("#52: step.main puts the crash under the key the step names",
          (row["status"], row["error"].startswith("ZeroDivisionError"), row["reason"]), ("TOOL_FAILURE", True, ""))
    rc, out = quiet(lambda: st.main(lambda: 1 / 0, decision=""))
    check("#52: and under `reason` when it names none", "reason" in json.loads(out.strip().splitlines()[-1]))
    # #53: requires.state in every form
    spec = il.spec_from_file_location("pk_fb", str(HERE / "packages.py"))
    pk = il.module_from_spec(spec); spec.loader.exec_module(pk)
    check("#53: state: true is here", pk.state_declared(True), (True, ""))
    check("#53: state: \"<where>\" is with the work", pk.state_declared("github issue comments"), (False, "github issue comments"))
    check("#53: {here, with_the_work} is both", pk.state_declared({"here": True, "with_the_work": "github issue comments"}),
          (True, "github issue comments"))
    check("#53: [true, \"<where>\"] is both", pk.state_declared([True, "gh"]), (True, "gh"))
    check("#53: nothing declared is neither", (pk.state_declared(None), pk.state_declared(False)), ((False, ""), (False, "")))
    # #54 / #55: the roots, filled in from the defaults, and the controls' scratch root
    import settings as se
    importlib.reload(se)
    rt = se.runtime()
    check("#55: handoff_root and config_root are roots like the others",
          all(k in rt["paths"] for k in ("handoff_root", "config_root", "state_root", "workspace_root")), sorted(rt["paths"]))
    check("the broker's address is answered even by a runtime.json that predates it", bool(rt.get("broker", {}).get("url")))
    old = os.environ.get(se.CONTROLS_ROOT)
    os.environ[se.CONTROLS_ROOT] = "/tmp/fb-scratch"
    try:
        p = se.runtime()["paths"]
        check("#54: under the controls' root the three roots a step writes to move there, the rest stay",
              (p["workspace_root"], p["evidence_root"], p["state_root"], p["logins_root"] == rt["paths"]["logins_root"]),
              ("/tmp/fb-scratch/workspace", "/tmp/fb-scratch/evidence", "/tmp/fb-scratch/state", True))
    finally:
        if old is None:
            os.environ.pop(se.CONTROLS_ROOT, None)
        else:
            os.environ[se.CONTROLS_ROOT] = old
    # (that scripts/packages.sh sets the root for a package's controls is measured by the cold
    # start: `packages.sh verify` runs novel's controls through it, in the container)
    # #55: a hand-in is a name, never a path
    check("#55: a hand-in name resolves under handoff_root",
          st.handoff("acyc-2026-04-10.json") == os.path.join(os.path.realpath(rt["paths"]["handoff_root"]), "acyc-2026-04-10.json"))
    for bad in ("../x", "/etc/passwd", ".", ""):
        try:
            st.handoff(bad); ok_ = False
        except ValueError:
            ok_ = True
        check(f"#55: a hand-in that escapes is refused ({bad!r})", ok_)
    # #55: the hosts of an egress profile are an answer, read from what the proxy reads
    root = Path(tempfile.mkdtemp(prefix="agentstack-fb-"))
    (root / "config" / "generated" / "egress" / "profiles").mkdir(parents=True)
    (root / "config" / "generated" / "egress" / "profiles" / "probe.allow").write_text("# generated\n^example\\.com$\n\n^api\\.anthropic\\.com$\n")
    old_root = se.GEN
    se.GEN = root / "config" / "generated"
    try:
        check("#55: step.egress_hosts(profile) answers the profile's patterns, comments and blanks dropped",
              st.egress_hosts("probe") == ["^example\\.com$", "^api\\.anthropic\\.com$"], st.egress_hosts("probe"))
        check("#55: and nothing for a profile the instance has not provisioned", st.egress_hosts("nope") == [], st.egress_hosts("nope"))
    finally:
        se.GEN = old_root
    shutil.rmtree(root, ignore_errors=True)


def pinkind_controls():
    """pin_kinds.py counts the controls that pin a source file's text rather than a behaviour; the
    count may fall and may not rise. Raise the bound only with a sentence in OPERATIONS."""
    r = subprocess.run([sys.executable, str(HERE / "pin_kinds.py"), str(HERE / "review_controls.py"), str(HERE / "trial_controls.py")],
                       capture_output=True, text=True, timeout=60)
    try:
        kinds = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        kinds = {}
    rc = kinds.get(str(HERE / "review_controls.py"), {}); tc = kinds.get(str(HERE / "trial_controls.py"), {})
    check("pins: review_controls' source-text pins do not grow (≤ 51 at §82)", 0 < rc.get("source-text", 999) <= 51, rc)
    check("pins: trial_controls' source-text pins do not grow (≤ 167 at §83)", 0 < tc.get("source-text", 999) <= 167, tc)
    check("pins: behaviour checks are the majority of review_controls", rc.get("behaviour", 0) > rc.get("source-text", 0) + rc.get("absence", 0), rc)


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
next_controls()
adapter_controls()
update_controls()
review3_controls()
ease_controls()
firstuse_controls()
feedback_controls()
pinkind_controls()
failed = [n for n, ok in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
