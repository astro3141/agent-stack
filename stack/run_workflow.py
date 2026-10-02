"""Start and read workflow runs for the ops API — runs inside the agent container.

usage:
  run_workflow.py start <ui-id> <workflow> <profile> [key=value ...] [--allow-unrecorded]
                        [--detach]         start it and return the id, rather than waiting
  run_workflow.py tail  <ui-id> [--follow] the steps as they happen, from the run's own event log
                        [--suite <name>]   label this run so a set can be read together
                        [--case <id>]      which case of that set this run is for
  run_workflow.py resume <ui-id>                                      continue an interrupted run
  run_workflow.py stop   <ui-id>                                      stop a run that is going
  run_workflow.py show  <ui-id>                                       JSON view of one run
  run_workflow.py list                                                JSON list, newest first
  run_workflow.py workflows                                           what may be started, and from where

Only workflows in WORKFLOWS may be started; arguments reach Conductor as an argv list, never
through a shell.

A run is refused when the stack cannot do what a run needs (stack/capabilities.py): without
Preloop no tool is governed and no permission request can be answered, and without the egress
proxy there is no route to a provider. Recording is the one capability a run can do without —
a composition may leave MLflow out — but only when the caller says so with `--allow-unrecorded`,
so an unrecorded run is a decision someone made and not something noticed afterwards.

Binding a UI run to *its* Conductor run is exact, not inferred: each run gets its own directory
and its own TMPDIR, and Conductor writes its event log under the temp directory
(<tmp>/conductor/conductor-<workflow>-<ts>-<run id>.events.jsonl). That directory therefore
holds this run's event log and nothing else. The view is read from that log — no second copy
of the run's progress is kept.

The event log decides whether a run ended. If it records the end (completed or failed) but the
launcher died before writing that down, the run is restored as `finished` with the logged outcome.
A run whose launcher is gone without an end in the log is marked `interrupted`. Nothing is resumed.
Reading the log is stack/runevents.py; the run's state and its restoration, stack/runstate.py;
this file starts, stops, resumes and answers.
"""
import json, os, re, subprocess, sys, time

sys.path.insert(0, "/work/stack")
import settings
import capabilities
import runstate
import runevents

# The workflows this stack was built with, and then whatever is installed as a package. A package
# is a directory under packages/ (stack/packages.py); installing one must not mean editing this
# file, or a workflow could never be given to anyone (CONTRACT.md, OPERATIONS §27).
# Nothing is built in any more: every workflow this stack runs is a package under packages/,
# including the five it was built with (OPERATIONS §30). The name is kept so that a stack which
# has to carry one again has the place to put it, and so that a package cannot silently take over
# a name the platform itself answers to.
# Workflows this stack carries itself: fixtures that measure the stack with no model and no
# package — a package may not take one of these names (known()).
BUILT_IN = {"child-run": "stack/cases/child-run.yaml"}   # #13: a sub-workflow and a wait, measured


def known():
    """Built-ins first: a package may not take a name this stack already answers to."""
    try:
        import packages
        return {**packages.workflows(), **BUILT_IN}
    except Exception:
        return dict(BUILT_IN)


def contested():
    """Workflow names more than one installed package declares. Nobody may start them, and a
    refusal says which packages are fighting over the name rather than "invalid workflow"."""
    try:
        import packages
        return {c["workflow"]: c["declared_by"]
                for c in packages.workflows(with_conflicts=True)[1]}
    except Exception:
        return {}


def described():
    """Each workflow with what it says about itself: its description and the inputs it declares.

    Read from the workflow file, so the screen offers what exists rather than a list someone kept
    up to date by hand — which is how the panel came to offer two of seven (OPERATIONS §30).
    `profile` is left out: the panel chooses that once, for any workflow.
    """
    import yaml
    try:
        import packages
        needs = packages.needs_env()
        logins = {p["name"]: packages.login_of(p["name"])
                  for p in packages.installed().values() if p["usable"]}
        owner = {w: p["name"] for p in packages.installed().values() if p["usable"]
                 for w in (p.get("entries") or {})}
        runbooks = {p["name"]: p.get("runbook") or "" for p in packages.installed().values()
                    if p["usable"]}
    except Exception:
        needs, owner = {}, {}
    def caps_of(name):
        try:
            import packages
            return packages.requires_of(name)[0]
        except Exception:
            return []
    out = {}
    for name, rel in sorted(known().items()):
        row = {"path": rel, "description": "", "inputs": [],
               # what the package this workflow belongs to needs in the environment, and whether it
               # is there. Names and presence only — the panel shows it and never offers entry.
               "needs_env": needs.get(owner.get(name), []),
               # the official login this workflow's package declares, if it has one (§44)
               "login": (logins.get(owner.get(name)) or None),
               # the package's own operating document (§58): the panel links it, the stack only
               # says where it is
               "runbook": runbooks.get(owner.get(name), ""),
               "package": owner.get(name, ""),
               # what its package says it needs of the stack — the panel's start gate reads it
               "capabilities": caps_of(name)}
        try:
            d = yaml.safe_load(open(f"/work/{rel}", encoding="utf-8")) or {}
            w = d.get("workflow") or {}
            row["description"] = str(w.get("description") or "")
            for key, spec in (w.get("input") or {}).items():
                if key == "profile":
                    continue
                spec = spec or {}
                row["inputs"].append({"name": key, "default": str(spec.get("default") or ""),
                                      "description": str(spec.get("description") or ""),
                                      "required": bool(spec.get("required"))})
        except Exception as e:
            row["error"] = f"{type(e).__name__}: {e}"
        out[name] = row
    return out


WORKFLOWS = known()
SAFE = re.compile(r"[A-Za-z0-9._\- ]{0,200}")


# The run's state (meta, launcher, checkpoints) and its event log have readers of their own:
# stack/runstate.py and stack/runevents.py. These names are kept here for the callers that
# imported them from this file (cleanup.py, the controls); the implementation is theirs.
run_dir, meta_path = runstate.run_dir, runstate.meta_path
events_for, checkpoints_for = runstate.events_for, runstate.checkpoints_for
instance_id, launcher_alive = runstate.instance_id, runstate.launcher_alive


def run_ended(ui, from_byte=0):
    """Whether this run's event log records the workflow ending — past `from_byte`, either way."""
    return runevents.ended(events_for(ui), from_byte)


def cmd_start(ui, workflow, profile, pairs, allow_unrecorded=False, suite="", case=""):
    if workflow not in WORKFLOWS:
        fight = contested().get(workflow)
        print(json.dumps({"error": f"no workflow named {workflow!r}",
                          "why": (f"{' and '.join(fight)} both declare it, so neither carries it; "
                                  "rename one in its manifest" if fight else None),
                          "workflows": sorted(WORKFLOWS)}, ensure_ascii=False))
        return 2
    if not re.fullmatch(r"[a-z0-9-]{1,40}", profile) or not re.fullmatch(r"[a-z0-9-]{6,40}", ui):
        print(json.dumps({"error": "invalid profile or id",
                          "rule": "a profile is [a-z0-9-] up to 40, a run id [a-z0-9-] of 6 to 40"}))
        return 2
    # A profile that is not there is refused here rather than deep inside a step: every step that
    # reads it calls settings.profile(), which returns None on purpose so callers fail instead of
    # guessing, and the first of them to fail does so several minutes into a run.
    if settings.profile(profile) is None:
        print(json.dumps({"error": f"no profile named {profile!r}",
                          "profiles": sorted(settings.profile_names())}))
        return 2
    # Admission is asked of the profile this run selected, not of a default one.
    caps = capabilities.probe(profile)
    gone = capabilities.missing(caps, need_record=not allow_unrecorded, profile=profile)
    # and what this workflow's own package says it needs — declared in its manifest, refused here
    try:
        import packages
        needs, pkg_name = packages.requires_of(workflow)
    except Exception:
        needs, pkg_name = [], ""
    for c in needs:
        if c not in caps:
            gone.append(c)
            caps[c] = {"available": False, "without_it": f"{pkg_name} declares it; this stack has "
                                                         "no probe for a capability by that name",
                       "detail": "unknown capability"}
        elif not caps[c]["available"] and c not in gone:
            gone.append(c)
    # A module the package says it imports, checked here (§62): the alternative is an ImportError
    # in a step, minutes in, naming a module and nothing about which package wanted it or why the
    # image has not got it. No container in this stack can reach PyPI — the fix is always a line in
    # the image, at build, by the operator.
    try:
        import packages as _pk
        lacking = [(pkg, e["module"]) for pkg, rows in _pk.needs_python().items()
                   for e in rows if not e["present"]
                   if pkg == (_pk.requires_of(workflow)[1] or pkg_name)]
    except Exception:
        lacking = []
    if lacking:
        print(json.dumps({
            "error": "this workflow's package needs a module the runtime has not got: "
                     + ", ".join(m for _, m in lacking),
            "why": {m: f"{pkg} declares it in requires.python" for pkg, m in lacking},
            "hint": "no container here can reach PyPI (OPERATIONS §62): add it to "
                    "docker/agent.Dockerfile's venv install and re-run scripts/up.sh --build. "
                    "A pure-Python dependency belongs in the package instead."}, ensure_ascii=False))
        return 3
    # The stack revision the package says it needs at least (requires.stack.min). Only a floor this
    # checkout verifiably does not contain refuses; "unverifiable" is reported by `packages.py
    # stack` and refuses nothing, because it says nothing about the stack's age.
    try:
        floor = _pk.stack_of(pkg_name).get(pkg_name) if pkg_name else None
    except Exception:
        floor = None
    if floor and floor.get("state") == "too_old":
        print(json.dumps({
            "error": f"this workflow's package needs a newer stack: {pkg_name} declares "
                     f"requires.stack.min {floor['min']}, and this checkout does not contain it",
            "hint": "scripts/release.sh update --to <a revision at or past it>, or pin an older "
                    "package in config/packages.yaml"}, ensure_ascii=False))
        return 3
    if gone:
        print(json.dumps({"error": "the stack cannot run this now: " + ", ".join(gone),
                          "why": {k: caps[k]["without_it"] for k in gone},
                          "detail": {k: caps[k]["detail"] for k in gone},
                          "hint": ("add --allow-unrecorded to run without recording"
                                   if gone == ["record"] else "")}))
        return 3
    inputs = {}
    for kv in pairs:
        k, _, v = kv.partition("=")
        # A refusal that does not name the rule sends the reader into the source: a path in
        # `packet_from` was refused as "invalid input" and finding out that `/` is not allowed
        # meant opening this file (reported from the second machine, OPERATIONS §33).
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,29}", k):
            print(json.dumps({"error": f"invalid input name {k!r}",
                              "rule": "an input name is [a-z][a-z0-9_] of up to 30"})); return 2
        if not SAFE.fullmatch(v):
            bad = sorted({c for c in v if not SAFE.fullmatch(c)})
            print(json.dumps({"error": f"invalid value for input {k!r}",
                              "rule": "a value is letters, digits, dot, underscore, hyphen or "
                                      "space, up to 200 — arguments reach Conductor as an argv "
                                      "list and are never shell-interpreted",
                              "refused_characters": bad,
                              "hint": ("a path cannot be passed as an input; put the file in the "
                                       "hand-in directory and pass its name (docs/packages.md)"
                                       if "/" in v else "")}, ensure_ascii=False)); return 2
        inputs[k] = v
    d = run_dir(ui)
    tmp = d / "tmp"
    # A run id is used once: its directory holds that run's event log, checkpoints and meta, and a
    # second run under the same id would read as one run with two of everything. Refused as an
    # answer, not as a traceback — the caller is a panel or a script, and both read JSON.
    try:
        (tmp / "conductor").mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(json.dumps({"error": f"the run id {ui!r} has been used already",
                          "hint": "ids are used once; `resume` continues that run"}))
        return 2
    meta = {"ui_id": ui, "workflow": workflow, "profile": profile, "inputs": inputs,
            # labels only: they group runs and name the case a run was started for, and change
            # nothing about what runs. What a case *means* is the dataset's, and this carries it
            # without reading it (stack/suite.py, OPERATIONS §24).
            "suite": suite, "case": case,
            "started_at": time.time(), "state": "running",
            # what the stack could do when this run started, so a run read later is read in
            # the light of the stack it actually ran on
            "capabilities": {k: c["available"] for k, c in caps.items()},
            "unrecorded": bool(allow_unrecorded and not caps["record"]["available"]),
            "launcher_pid": os.getpid(), "instance": instance_id()}
    meta_path(ui).write_text(json.dumps(meta))
    # `--web` is not for anyone to look at: the dashboard binds the container's loopback and is
    # not published (OPERATIONS §14). It is here because `conductor stop` escalates *starting from
    # a graceful cancel via the dashboard*, and that is the path that lets a run write a
    # checkpoint. Without it a stopped run leaves nothing to resume from. Port 0 = auto-selected,
    # so concurrent runs do not collide.
    argv = ["conductor", "--silent", "run", WORKFLOWS[workflow], "--no-interactive",
            "--web", "--web-port", "0", "-i", f"profile={profile}"]
    for k, v in inputs.items():
        argv += ["-i", f"{k}={v}"]
    env = {**os.environ, "TMPDIR": str(tmp), "CONDUCTOR_EVENT_DIR": str(tmp / "conductor")}
    with open(d / "run.log", "wb") as log:
        rc = run_conductor(ui, argv, env, log)
    meta.update({"state": "finished", "exit": rc, "ended_at": time.time()})
    meta_path(ui).write_text(json.dumps(meta))
    return 0


def run_conductor(ui, argv, env, log):
    """Run Conductor and come back when the *workflow* has ended.

    `--web` keeps serving the dashboard after the workflow finishes, so waiting for the process to
    exit means waiting forever: measured, five launchers still sleeping half an hour after their
    runs had ended, and a suite whose third case never started because the pool never freed a
    worker. The event log is the record of the run (it is what `view` reads), so the end of the
    workflow is read from there and the process is then asked to go, gently first.
    """
    # A resume writes into the log the stopped attempt already filled, and that log ends with the
    # stop. Only what this process appends counts, so the end is looked for past what is there now.
    p = events_for(ui)
    from_byte = p.stat().st_size if p else 0
    proc = subprocess.Popen(argv, cwd="/work", stdout=log, stderr=subprocess.STDOUT, env=env,
                            start_new_session=True)
    ended_at = None
    while True:
        rc = proc.poll()
        if rc is not None:
            return rc                      # it left on its own: nothing to tidy
        if ended_at is None and run_ended(ui, from_byte):
            ended_at = time.time()         # the workflow is over; the dashboard is not
        elif ended_at and time.time() - ended_at > 5:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=20)
            # our own tidy-up, not the run's outcome: that is in the event log, which every
            # reader here uses. Reporting -15 as the exit would call a finished run a failure.
            return 0
        time.sleep(2)


def cmd_tail(ui, follow=False):
    """The run's steps as they happen, read from its own event log.

    A start that holds the terminal until the run ends is fine for a script and wrong for a person:
    the first pilot on another machine was cut by a two-minute client timeout while the run itself
    carried on (OPERATIONS §33). `--detach` returns the id; this is how you then watch it.
    """
    if not meta_path(ui).exists():
        print(json.dumps({"error": "no such run"})); return 1
    seen, idle = 0, 0
    while True:
        p = events_for(ui)
        lines = p.open().read().splitlines() if p else []
        for line in lines[seen:]:
            try:
                e = json.loads(line)
            except Exception:
                continue
            t, d = e.get("type"), e.get("data") or {}
            # Conductor stamps events with epoch seconds, not an ISO string
            try:
                at = time.strftime("%H:%M:%S", time.localtime(float(e.get("timestamp"))))
            except (TypeError, ValueError):
                at = "--:--:--"
            if t == "agent_started":
                print(f"{at}  → {d.get('agent_name')}", flush=True)
            elif t == "agent_completed" and d.get("agent_type") == "terminate":
                print(f"{at}  ■ {d.get('agent_name')}: {d.get('termination_reason') or ''}", flush=True)
            elif t in ("workflow_completed", "workflow_failed"):
                print(f"{at}  {'done' if t == 'workflow_completed' else 'ended'}", flush=True)
                if not follow:
                    return 0
                return 0
        seen = len(lines)
        if not follow:
            return 0
        meta = json.loads(meta_path(ui).read_text())
        if meta.get("state") != "running" and not launcher_alive(meta):
            idle += 1
            if idle > 2:          # the launcher is gone and the log has stopped growing
                return 0
        time.sleep(2)


def cmd_resume(ui):
    """Continue an interrupted run from Conductor's own checkpoint.

    Conductor writes checkpoints under $TMPDIR/conductor/checkpoints, and every run here already
    has a TMPDIR of its own — so a run's checkpoints are exactly its own. Resuming re-enters the
    step that did not finish; inside a fan-out step, steps/fanout.py then re-runs only the members
    that did not finish. Conductor's unit is the step, this stack's unit is the member, and the two
    together are what makes an interrupted cycle continue instead of starting over.
    """
    if not re.fullmatch(r"[a-z0-9-]{6,40}", ui) or not meta_path(ui).exists():
        print(json.dumps({"error": "no such run"})); return 1
    meta = json.loads(meta_path(ui).read_text())
    if meta.get("state") == "running" and launcher_alive(meta):
        print(json.dumps({"error": "this run is still going"})); return 1
    d = run_dir(ui)
    tmp = d / "tmp"
    cps = checkpoints_for(ui)
    if not cps:
        print(json.dumps({"error": "no checkpoint for this run — nothing to resume from"})); return 1
    meta.update({"state": "running", "resumed_at": time.time(), "resumed_from": cps[-1].name,
                 "launcher_pid": os.getpid(), "instance": instance_id()})
    meta_path(ui).write_text(json.dumps(meta))
    argv = ["conductor", "--silent", "resume", "--from", str(cps[-1]), "--no-interactive"]
    env = {**os.environ, "TMPDIR": str(tmp), "CONDUCTOR_EVENT_DIR": str(tmp / "conductor")}
    with open(d / "run.log", "ab") as log:
        rc = run_conductor(ui, argv, env, log)
    meta.update({"state": "finished", "exit": rc, "ended_at": time.time()})
    meta_path(ui).write_text(json.dumps(meta))
    return 0


def cmd_stop(ui):
    """Stop a run that is going. A person's decision, so it is offered in the panel too.

    Conductor owns the stopping: `conductor stop --run-id` escalates until the process is confirmed
    gone (a graceful cancel, then a signal, then force) and refuses to target the run it is itself
    running inside. This only finds the run id — from the event log this run owns — and records
    that a stop was asked for.

    What a stop does **not** leave, measured: a checkpoint. Across 51 runs here only two have one,
    and both are runs that *failed*; a stopped run's directory has none, so it is started again
    rather than resumed. The run itself is then read as `interrupted`, which is what it is.
    """
    meta = json.loads(meta_path(ui).read_text()) if meta_path(ui).exists() else None
    if not meta:
        print(json.dumps({"error": "no such run"})); return 2
    p = events_for(ui)
    rid = runevents.conductor_run_of(p) if p else None
    if not rid:
        print(json.dumps({"error": "this run has no Conductor event log yet"})); return 3
    # --yes: the confirmation is the panel's (a person pressed a button); there is no terminal here
    r = subprocess.run(["conductor", "stop", "--run-id", rid, "--yes"], capture_output=True, text=True,
                       cwd="/work", env={**os.environ, "TMPDIR": str(run_dir(ui) / "tmp")})
    meta["stop_requested_at"] = time.time()
    meta["stop_result"] = (r.stdout or r.stderr)[-300:]
    meta_path(ui).write_text(json.dumps(meta))
    print(json.dumps({"ui_id": ui, "conductor_run": rid, "rc": r.returncode,
                      "output": (r.stdout or r.stderr)[-300:]}))
    return 0


def view(meta):
    """The run as the screen shows it: its meta, what its event log says, and the state the two
    imply. A reading — this writes nothing. The restored state is `read()`'s, by name."""
    ui = meta["ui_id"]
    reading = runevents.read(events_for(ui))
    out = {**meta, **reading, "workspace_prefix": None}
    if reading["conductor_run"]:
        # every model step of this run works under <workspace_root>/<conductor run id>… — known
        # from the start, so a pending approval can be tied to the run while the step still waits
        out["workspace_prefix"] = f"{settings.runtime()['paths']['workspace_root']}/{reading['conductor_run']}"
    out["state"] = runstate.state_of(meta, reading)
    if out["state"] == "interrupted":
        # said on every reading, not only the one that noticed: the screen refreshes
        out["error"] = out["error"] or ("the run's launcher is gone (container restart or process "
                                        "killed) and Conductor recorded no end; it was not resumed")
    if meta.get("state") == "finished" and not out["output"] and not out["error"] and not out["ended"]:
        log = run_dir(ui) / "run.log"
        out["error"] = log.read_text(errors="replace")[-600:] if log.exists() else "no output"
    return out


def read(ui):
    """The run, with its state restored first: a run whose launcher died after the log recorded
    the end is written down as finished, one whose launcher is gone without an end as
    interrupted (runstate.recover). This is what `show` and `list` answer with; a caller that
    must not write asks `view()`."""
    meta = runstate.load(ui)
    if meta is None:
        return None
    meta = runstate.recover(meta, runevents.read(events_for(ui)))
    return view(meta)


def cmd_show(ui):
    v = read(ui) if re.fullmatch(r"[a-z0-9-]{6,40}", ui) else None
    if v is None:
        print(json.dumps({"error": "no such run"})); return 1
    print(json.dumps(v))
    return 0


def cmd_list():
    rows = []
    metas = sorted(runstate.RUNS.glob("*/meta.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]
    for m in metas:
        v = read(m.parent.name)
        if v is None:
            continue
        rows.append({k: v.get(k) for k in ("ui_id", "workflow", "profile", "state", "started_at", "current_step",
                                            "terminated_at", "route", "suite", "case")}
                    | {"decision": (v.get("output") or {}).get("decision"),
                       # a run that stopped before it ended, and has something to continue from
                       # A stop *is* an end in Conductor's log (it fails the run), so "not ended"
                       # is the wrong test: what matters is whether the last thing recorded was
                       # the workflow completing, and whether there is a checkpoint to go on from.
                       "resumable": bool(v.get("state") != "running" and not v.get("completed_ok")
                                         and checkpoints_for(v["ui_id"]))})
    print(json.dumps(rows))
    return 0


if __name__ == "__main__":
    a = sys.argv[1]
    argv = sys.argv[5:]
    def labelled(name):
        i = argv.index(name) if name in argv else -1
        return argv[i + 1] if 0 <= i < len(argv) - 1 else ""
    suite, case = labelled("--suite"), labelled("--case")
    # everything that is neither a flag nor a flag's value is an input pair
    rest = [x for i, x in enumerate(argv)
            if x not in ("--allow-unrecorded", "--suite", "--case")
            and (i == 0 or argv[i - 1] not in ("--suite", "--case"))]
    def start_or_detach():
        # A start holds the terminal until the run ends, which is right for a script and wrong for
        # a person: a two-minute client timeout cut the first pilot on another machine while the
        # run carried on (OPERATIONS §33). `--detach` re-runs this same command in the background
        # and answers with the id, which `tail` and `show` then take.
        if "--detach" not in argv:
            return cmd_start(sys.argv[2], sys.argv[3], sys.argv[4], rest,
                             "--allow-unrecorded" in argv, suite, case)
        ui = sys.argv[2]
        if meta_path(ui).exists():
            print(json.dumps({"error": f"the run id {ui!r} has been used already"})); return 2
        child = [a for a in sys.argv if a != "--detach"]
        subprocess.Popen([sys.executable] + child[0:1] + child[1:], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):                      # answer once the run exists, not before
            if meta_path(ui).exists():
                break
            time.sleep(1)
        print(json.dumps({"ui": ui, "detached": True,
                          "watch": f"run_workflow.py tail {ui} --follow",
                          "started": meta_path(ui).exists()}))
        return 0

    sys.exit({"start": start_or_detach,
              "tail": lambda: cmd_tail(sys.argv[2], "--follow" in sys.argv),
              "resume": lambda: cmd_resume(sys.argv[2]),
              "stop": lambda: cmd_stop(sys.argv[2]),
              "show": lambda: cmd_show(sys.argv[2]), "list": cmd_list,
              # the one answer both this and the panel use, so neither keeps its own list
              "workflows": lambda: (print(json.dumps(
                  {**(described() if "--detail" in sys.argv else known()),
                   **({"_contested": contested()} if contested() else {})},
                  ensure_ascii=False)), 0)[1]}[a]())
