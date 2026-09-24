"""What this stack can do right now — probed, not declared.

usage: capabilities.py [--json] [--profile <name>] [--missing [--allow-unrecorded]]
       (in the agent container)

A composition may leave a service out (scripts/up.sh --composition), and a service that is
supposed to be there can also be down. Both come to the same question for a run that is about to
start: *which capabilities does the stack have at this moment*. So this asks the services
themselves rather than reading a name someone wrote down — a declared composition can be stale,
a probe cannot.

Each capability answers with what a caller needs to decide: whether it is there, and what depends
on it. What to do about a missing one is not decided here (CONTRACT.md): `run_workflow.py` refuses
to start a run without the capabilities a run cannot be honest without, and takes an explicit
opt-in for recording, which a run can do without as long as someone says so.
"""
import json, os, sys, urllib.error, urllib.request

sys.path.insert(0, "/work/stack")
import settings

RT = settings.runtime()


def http(url, timeout=5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


DEFAULT_PROFILE = "research-default"


def probe(profile=DEFAULT_PROFILE):
    """What the stack can do now. `profile` is the profile the caller is about to run under:
    admission is a question about a routing policy, and there is more than one."""
    mcp = RT["preloop"]["mcp_url"]
    caps = {}

    # Tool rights. 401 without a credential is the MCP proxy answering: it is up and it is
    # refusing, which is exactly what it must do.
    code = http(mcp)
    caps["tool_rights"] = {
        "available": code == 401,
        "detail": f"Preloop MCP answered {code or 'nothing'}",
        "without_it": "no governed file tools, and no decision on a native tool call",
        "required": True}

    api = http(RT["preloop"]["api_url"] + "/api/v1/openapi.json")
    caps["approvals"] = {
        "available": api == 200,
        "detail": f"Preloop api answered {api or 'nothing'}",
        "without_it": "a permission request cannot be answered, so every one of them is a denial",
        "required": True}

    # Egress. The proxy must be reachable *and* still refuse what is not a provider.
    prov = http("http://egress:8888", timeout=5)
    caps["egress"] = {
        "available": prov != 0,
        "detail": f"allowlist proxy answered {prov or 'nothing'}",
        "without_it": "no route to any provider; nothing can run",
        "required": True}

    ml = http(RT["mlflow"]["url"] + "/health")
    caps["record"] = {
        "available": ml == 200,
        "detail": f"MLflow answered {ml or 'nothing'}",
        "without_it": "runs still execute, but nothing about them is recorded or comparable",
        "required": False}

    # The screen is deliberately not probed here: it is reached from the host, not from inside
    # this network, and no run needs it. scripts/up.sh reports it from where it is reachable.

    # Admission is whether the router can choose a provider — asked of the router, not of one
    # source's file. It used to read the observer's own /obs/codex.raw.json, which stopped being
    # the model when codex became readable with the login that executes (§29): the router said
    # ROUTE while this said admission=no, and a screen that contradicts the run is worse than a
    # screen that says nothing.
    #
    # Asked of *this run's* profile. It used to ask for "research-default" whatever the run had
    # selected, so a run started on another profile was admitted or refused on a routing policy it
    # was not going to use — cost-first names the same three providers in a different order, and a
    # profile with different thresholds would have been judged on thresholds nobody asked for.
    try:
        import subprocess, tempfile
        prof = settings.profile(profile)
        if prof is None:
            raise FileNotFoundError(f"no profile named {profile!r}")
        pol = prof.get("routing") or {}
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(f"{tmp}/obs", exist_ok=True)
            json.dump(pol, open(f"{tmp}/policy.json", "w"))
            env = {**os.environ, "AGENTSTACK_MODEL_ROUTES": json.dumps(pol.get("model_route") or {}),
                   "AGENTSTACK_LOGINS": json.dumps(pol.get("login") or {})}
            subprocess.run([sys.executable, "/work/stack/collect_obs.py", f"{tmp}/obs"],
                           capture_output=True, env=env, timeout=180)
            out = subprocess.run([sys.executable, "/work/stack/router.py",
                                  f"{tmp}/policy.json", f"{tmp}/obs"],
                                 capture_output=True, text=True, timeout=60).stdout
        d = json.loads(out)
        usable = [e["provider"] for e in d.get("evaluated") or [] if e.get("eligible")]
        fresh = bool(usable)
        detail = (f"under {profile}, the router would take {usable[0]}" if fresh
                  else f"under {profile}, no eligible provider: " + "; ".join(
                      f"{e['provider']}={e.get('why')}" for e in (d.get("evaluated") or []))[:160])
    except Exception as e:
        fresh, detail = False, f"could not ask the router for {profile} ({type(e).__name__}: {e})"
    caps["admission"] = {
        "available": fresh, "detail": detail,
        "without_it": "the router sees no quota, calls every provider unknown, and holds the run",
        "required": False}
    return caps


def missing(caps=None, need_record=True, profile=DEFAULT_PROFILE):
    """The capabilities a run cannot start without, given whether it insists on being recorded."""
    caps = caps or probe(profile)
    out = [k for k, c in caps.items() if c["required"] and not c["available"]]
    if need_record and not caps["record"]["available"]:
        out.append("record")
    return out


if __name__ == "__main__":
    prof = DEFAULT_PROFILE
    if "--profile" in sys.argv and sys.argv.index("--profile") + 1 < len(sys.argv):
        prof = sys.argv[sys.argv.index("--profile") + 1]
    caps = probe(prof)
    if "--missing" in sys.argv:
        # one answer for every caller that has to decide whether a run may start
        gone = missing(caps, need_record="--allow-unrecorded" not in sys.argv)
        print(json.dumps({"missing": gone,
                          "why": {k: caps[k]["without_it"] for k in gone},
                          "detail": {k: caps[k]["detail"] for k in gone}}, ensure_ascii=False))
        sys.exit(0)
    if "--json" in sys.argv:
        print(json.dumps(caps, ensure_ascii=False))
    else:
        for k, c in caps.items():
            mark = "yes" if c["available"] else ("MISSING" if c["required"] else "no")
            print(f"  {k:<12} {mark:<8} {c['detail']}")
            if not c["available"]:
                print(f"               → {c['without_it']}")
    sys.exit(1 if missing(caps, need_record=False) else 0)
