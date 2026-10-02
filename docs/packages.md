# Writing a workflow package

A package is a directory under `packages/` that this stack can run without being edited
([concepts.md](concepts.md), OPERATIONS §27, §30). `packages/hello-lane` shows the shape; this page
is the **contract** its steps have to keep — the things that were previously discoverable only by
reading the platform's source, and that cost another operator a broken baseline and a record that
read as empty.

## Where it lives

A package either lives in this repository (`from: local` in `config/packages.yaml` — the example and
the capability trials) or in **its own repository**, fetched and pinned:

```yaml
packages:
  my-lane:
    from: https://github.com/<owner>/my-lane-package.git
    ref: main
```

```bash
scripts/packages.sh install my-lane   # clones it, writes config/packages.lock, excludes it here
scripts/packages.sh verify            # is what is on disk still the commit the lock names
scripts/up.sh                         # applies what it declares
```

**Declaring it is what installs it.** The loader offers what `config/packages.yaml` names, not what
is on disk: a directory copied under `packages/` without a declaration is listed with that as its
reason, is not offered as a workflow, and its `principals.yaml` is not applied. Removing the entry
removes the package from the running stack at the next read — which is what "installing a package
is a decision to trust it" has to mean if it means anything.

**Its own repository is the recommendation; `from: local` is the exception.** A platform repository
should say which workflows it runs, not carry them — and it is the repository that can be published,
which a package inside it inherits. Write the package in its own repository from the start if any
of these is true:

* it carries **domain content** — a strategy, a client's rules, a project's policy;
* it **names something real** — a repository, a branch, a person, an account;
* it **snapshots another repository's files**, even as a fixture;
* it would be wrong to publish alongside the platform.

`from: local` is for what the platform repository can publish about itself: the example here, and
the capability trials that exist to show the stack runs a shape.

Measured twice, and the second time is the argument. The trading package lived here for 36 files
before it moved out. The devflow package landed here complete — and carried a private repository's
name, its branch layout and a snapshot of its policy, in Korean, quoting an internal document. No
control caught either one; a publication audit did, which is a bad place to find out. Splitting
afterwards is not free: the content stays in this repository's history, and getting it out means
rewriting every commit.

**Instance registration is not package content either.** A file that says *which* project a package
runs against — `config/<package>/projects/<name>.yaml`, naming a repository and a branch — is this
instance's configuration, like `config/instance.env`. `config/*/projects/` is git-ignored here for
that reason: the package's own repository holds the rules, this one holds neither.

The fetch happens on the host, so no git credential is ever inside the governed runtime. Nothing
has to be excluded afterwards: `packages/*` is git-ignored and the packages this repository carries
are the named exceptions, so what you install is yours and stays out of its history (OPERATIONS
§42).

That repository ignores what the runtime writes — `__pycache__/` and `*.pyc` at least. `verify`
compares the working tree against the pinned commit, so a compiled step that is tracked makes every
run report the package as edited.

## The layout

```
packages/<name>/
  manifest.yaml      name, version, what it needs of the stack, and the workflows it carries
  workflow.yaml      the graph (or several files, named in the manifest)
  steps/             its own steps
  prompts/ fixtures/ cases/
  principals.yaml    the identities its steps run as, and what each may do
  controls.py        (optional) its own controls
  README.md
```

`manifest.yaml`:

```yaml
name: my-lane                 # must equal the directory name
version: 0.1.0
description: one line, shown in the panel's 워크플로 tab
workflows:                    # or `entry: workflow.yaml` for a single one
  my-lane: workflow.yaml
requires:
  capabilities: [tool_rights, egress, record, admission]   # the runner refuses a run without them
  python: [pydantic]          # modules you import that the image must already carry
runbook: RUNBOOK.md           # your operating document — the panel links it under the workflow
```

**Bring your own code; declare only what you cannot.** A pure-Python dependency belongs *in* the
package — it arrives as a directory, and a step can put it on `sys.path` itself. Declare
`requires.python` only for what cannot travel that way (a C extension, a wheel), and note what the
stack will and will not do with it: no container here can reach PyPI (OPERATIONS §62), so nothing is
installed for you. What you get is an answer and a refusal — `packages.py python` says whether each
module is importable, and a run whose package lacks one is refused at the start, naming the module,
instead of dying on an ImportError inside a step. Adding it is a line in the image and a rebuild, by
the operator.

A package may carry **several workflows** when they share steps — that is why the three trading
workflows are one package.

A workflow **name** belongs to whichever package declares it, and to only one: a name two installed
packages declare is carried by neither, and `packages.py` and any refused run name both packages so
you can rename one. Check yours against what is already installed:

```bash
docker exec agentstack-agent /opt/venv/bin/python /work/stack/run_workflow.py workflows
```

## Which container runs what

Every step runs in the **agent**, with `/work` mounted and `PYTHONPATH=/work/stack:/work/stack/steps`,
so `import settings` works from wherever the step lives. See [containers.md](containers.md) for the
rest — in particular, anything that writes to Preloop belongs on the admin side, and a package's
steps never need to.

## The contract a step keeps

**1. Address the workspace through the stack's step helper, never by guessing.**

```python
import step                  # stack/steps/step.py — on the PYTHONPATH the stack sets for every step
RUN = step.run_id()          # Conductor's id for this run
WS  = step.workspace()       # <workspace_root>/<run id>, from the stack's settings; not created
```

The run's workspace is `<workspace_root>/<conductor run id>`, and every other reader — the
recorder, the evidence index, the panel — resolves it the same way. A step that invents its own
path writes where nothing will look for it. Six packages had copied these lines before the helper
existed, and one copy addressed the workspace through an environment variable nothing sets
(docs/record/PACKAGE-MATRIX.md, X1): a copied contract drifts in the copy nobody reads.
`import step` fails outside the stack, and that is the right answer — a step that carried on with
a guessed root would run, on a fixture, exactly like one that did not. A step that needs to run by
hand on a host puts `/work/stack/steps` on `sys.path` first, as the in-tree packages do.

**2. The last line of stdout is JSON, and it is the step's output.**

```python
step.out(decision="PASS", reason="...")              # prints the line; the fields are the output
step.main(lambda: work(), decision="", reason="")    # runs the step; an exception becomes that line
```

Conductor reads it and the workflow's `output:` block names its fields. Anything else you print is
for a human; the last line is the contract. A step that cannot do its work prints JSON saying so
rather than raising — `step.refuse(reason, **fields)` does exactly that and exits 0 — and a step
that crashes should still answer: `step.main(fn, **shape)` turns an exception into the same line,
with every declared key present (Conductor refuses a line that lacks one), `status: TOOL_FAILURE`
and the reason. A machinery failure is then something the graph routes on, not a traceback the
operator finds in a log.

**3. Say what a repeat of this step does.** Every step declares it, and a control fails if one does
not:

```python
REPEATABLE = "yes"       # same inputs, same result — running it again changes nothing
REPEATABLE = "guarded"   # it recognises the repeat and does not redo the work
REPEATABLE = "no"        # it does the work again (a model call, for instance)
```

A step with an effect **outside this stack** — opening a pull request, sending something, moving
money — declares `guarded` and guards itself. Nothing in the platform deduplicates an external
effect for you, and nothing can: what counts as the same effect is the workflow's to know. Two
places to keep the answer, and they are not equivalent:

* **the run's workspace** survives a resume. A resumed run keeps its conductor run id, so
  `/ws/<run>` is the same directory the interrupted attempt wrote to (measured: one workspace id
  across both halves of a resumed run's event log). A marker file there is enough to stop a step
  from doing the same thing twice *within one run*.
* **the remote** is the only answer for a *different* run — a re-run under a new id, a retry from
  another machine, a person who ran it again. There the workspace is new and says nothing.

So: a marker for the resume, and a question to the remote for everything else. A step that only
writes the marker will open the pull request twice the day someone re-runs the cycle.

**4. Evidence files use `items`.** `stack/steps/record.py` counts and stores exactly that key; a file
with `rows` is stored and counted as **zero**, so the record reads as "nothing kept":

```json
{"items": [{"claim": "...", "kind": "...", "execution_id": "...", "by": "..."}], "decision": "PASS"}
```

**5. Refuse, do not degrade.** If what the step needs is absent, say so in the output and let the
workflow's graph decide. A step that carries on with less produces a result nobody can read back.

**6. Data comes in by name, not by path.** Run inputs are letters, digits, dot, underscore, hyphen
and space (arguments reach Conductor as an argv list and are never shell-interpreted), so a path
cannot be an input. Put the file in the **hand-in directory** — `/work/handoff/` — and pass its
name:

```bash
cp acyc-2026-04-10.json <repo>/handoff/
run_workflow.py start r1 trading-port research-default mode=live packet_from=acyc-2026-04-10.json
```

The step resolves the name inside that directory and refuses anything that escapes it. Fixtures
that travel with the package live in `fixtures/` instead; the hand-in directory is for data that
arrives from outside a run.

## The output of a model step

`stack/steps/agent_task.py` answers with one shape — the **execution record**, owned by
`stack/execution.py` — and every workflow that routes on it declares some of it in its `output:`
block; three packages had each copied their own subset, one of them twice
(docs/record/PACKAGE-MATRIX.md, X10b). The same record is what a fan-out keeps in its receipt
(every attempt of every member), what a chain keeps for each of its model steps, what the
recorder turns into an MLflow run, and what `trajectory.py` sums; a copy is written beside the
adapter's raw result as `<evidence_dir>/execution.json`, so the evidence directory carries the
platform's record of the call whether or not any step passed it on. A record carries
`contract: 1`, the version of this shape. This is the whole set (a control compares this list
with `execution.FIELDS`); declare what you route on and copy the lines, do not retype them:

```yaml
    output:
      status: {type: string}                 # COMPLETED | FAILED | DENIED | TIMED_OUT | ...
      provider: {type: string}
      principal: {type: string}              # the Preloop principal the call presented
      model_route: {type: string}
      run_id: {type: string}                 # <run>-<label>-<provider>: this call's evidence directory
      workspace: {type: string}
      produced_path: {type: string}          # the artifact the step was told to expect
      produced: {type: boolean}              # it is there, and this call wrote it
      produced_stale: {type: boolean}        # it is there, untouched by this call (left by an earlier one)
      model_session_reported: {type: string}
      model_adapter_reported: {type: string}
      model_served: {type: string}           # "unknown" unless something on the path reported it
      approvals_requested: {type: number}
      mcp_rule_denials: {type: number}
      retryable_elsewhere: {type: boolean}
      evidence_dir: {type: string}
      profile: {type: string}
      attempts: {type: number}               # 2 when the one bounded login-refresh retry ran
      failure: {type: string}                # why, when status is not COMPLETED
      ledger_error: {type: string}
      measurements:                          # a number the adapter did not report is left out, never 0
        type: object
        properties:
          total_tokens: {type: number, required: false}
          wall_ms: {type: number, required: false}
```

A YAML anchor (`output: &agent_out` on the first model step, `output: *agent_out` on the rest)
keeps one copy per workflow; `packages/research-r/research-r.yaml` shows it.

**Where a call runs is not the workflow's to choose.** A role that declares an egress profile is
handed to the broker by `agent_task.py` itself (§54); a fan-out and a chain start the same step
and never choose a door, and neither does a workflow that calls it directly.

**What the screen reads, it reads from what a step said, not from the step's name.** The panel
shows a run's routing decision and its MLflow record. It recognises the routing step by its
output (`decision` + `evaluated` + `provider`, which is what `stack/steps/route.py` answers) and
the recording step by its output (`mlflow_run_id`, what `stack/steps/record.py` answers) —
name them `route` and `record_pass` or `choose_provider` and `persist_result`; the screen is the
same. Until this the screen read a step *named* `route` and steps whose names began with
`record` (OPERATIONS §68).

## What it needs of the stack

`requires:` in the manifest is read, key by key, by `stack/packages.py`; the runner refuses a run
whose package needs what the stack has not got. These are the keys something reads:

| key | what it declares | who reads it |
|---|---|---|
| `capabilities` | the stack capabilities a run needs (`tool_rights`, `egress`, `record`, `admission`) | `run_workflow.py start` refuses without them |
| `env` | environment variables, by name and purpose — never a value | `packages.py needs`, the panel |
| `egress` | hosts the package's scripts reach | `packages.py egress` (an audit, not a control) |
| `python` | modules the image must carry | `packages.py python`, `run_workflow.py start` |
| `stack` | the oldest stack revision the package runs on: `stack: {min: <commit>}` | `packages.py stack`, `run_workflow.py start` |
| `state` | `state: true` — the package keeps state outside any run, under its own directory (below); `state: "<where>"` — it keeps state with the work, elsewhere, and this says where | `packages.py state` |

A package calls the stack's steps by absolute path and argv order, so one written against a newer
stack fails on an older one in whatever way the missing feature fails — a brokered step refused as
`invalid expected`, a long call killed at fifteen minutes (both measured, in the devflow runbook).
`requires.stack.min` names the floor; the runner refuses a run on a checkout that verifiably does
not contain that commit, and `packages.py stack` reports a floor it cannot verify (a shallow clone,
no git) without refusing anything, because that says nothing about the stack's age.

**A key outside that table is a comment.** Two packages carried one for weeks — `principals`,
`host_paths` — each believing the stack checked something it never looked at. `packages.py` now
prints `note: requires.<key> is read by nothing in this stack` under the package, so the belief
does not survive the first `list`.

## Binding a result to its input

A reviewer judges one draft; a lane trades on one packet; a verdict is about one tree. When the
thing judged can change between the step that froze it and the step that reads the judgement, the
judgement must say which bytes it was about, and the reader must refuse one about other bytes.
Four packages did this, each in its own words (docs/record/PACKAGE-MATRIX.md, X2). The mechanism
is the stack's now; the choice stays the package's.

```python
import step
sha = step.bind_file(frozen_path)          # or step.bind_text(text): the name the result is bound to
# … the fan-out carries the workflow's `context` back in every receipt, unchanged (CONTRACT) …
if not step.bound(receipt, sha):           # a receipt for other bytes, or with no binding: not this round's
    ...
```

- **The package decides what the input is** — a frozen file, a packet built from several, a
  tree — and what a mismatch means (novel repairs; trading refuses; devflow reports).
- **The stack carries the binding unchanged** (`context` in the receipt, `sha256` of every
  produced file) and gives the three functions; it never decides that two hashes are "close".
- novel is the measured instance: `packages/novel/controls.py` drives its triage through every
  way a receipt can fail to be this round's (an older draft's, no receipt, a file changed after
  the reviews step), and those controls run unchanged on the helper.

## State that outlives a run

Most of what a package writes belongs to a run — the workspace, the evidence, the record — and
goes with it (`cleanup.py`). Some does not: a ledger of what was already decided, a cache of a
remote's answers, the last cycle's hand-over. Four packages kept such state in four places (a
GitHub comment, `.devflow-cache`, `handoff/` used as a database, a `/research` mount), each with
its own idea of who cleans it, because the stack named nowhere (docs/record/PACKAGE-MATRIX.md,
X9). It names one place now:

```
<state_root>/<package>/        state_root is in config/environment.yaml (default /work/state)
```

- **The package owns it.** What is in there, its shape, and when it is pruned are the package's;
  a step reaches it through the stack's settings (`step.runtime()["paths"]["state_root"]`), never
  by a path of its own.
- **It is declared.** `requires: {state: true}` in the manifest. `packages.py state` lists every
  directory under the root with who declared it; one nobody declared is reported as a question,
  not deleted — the stack removes runs, not a package's memory.
- **It is not a hand-in.** Input still arrives through `handoff/` by name; state is what the
  package writes for its own next run.
- **It is not in git, and it is in the backup.** `state/` is ignored by git and copied by
  `scripts/backup.sh` (restored by `scripts/restore.sh`), because it is the one thing a package
  writes that neither a run nor the repository can give back — trading's segment ledger, say.
  A package that needs a fixture ships it in `fixtures/`.
- **Hand-in is not state, and a refreshed credential is neither.** Three kinds, measured on
  trading (issue #14): what a cycle *reads and must not change* (its pins — frozen by hash at
  registration, verified every cycle) stays a hand-in under `handoff/`; what the *next* cycle
  needs (ledger, pending executions, re-entry decision table, durable attempts, receipts, lane
  accumulations) is state, here; a provider login the CLI rewrites on refresh is neither — it
  lives with the logins and is regenerated by signing in, not restored.

That is the whole contract: a path, a declaration, a report. No helper, because a path and a
rule are all four packages were missing.

**Two kinds of state, and the root is the place for one of them.** Asked (issue #14), the two
packages that keep the most state answered differently, and both are right:

| | lives | because | declared as |
|---|---|---|---|
| trading's segment ledger | `<state_root>/trading/` | the next cycle on *this* instance needs it; nobody else reads it | `state: true` |
| devflow's task state | the task's GitHub issue (a sentence for people; counters and done-keys for the machine) | a person must read "who does what, and it resumes when" **where the work is**, and the budgets, rounds and the list of commits devflow pushed must outlive this machine, a reinstall, a wiped workspace | `state: "github issue comments"` |

State that lives with the work is the package's, end to end: the stack has no place for it and
should not pretend to. What the stack does is **know where it is** — `packages.py state` reports
it, and the backup says it is not covered. One rule travels with it, because the stack's own
guarantee does: *a reading nobody authenticated is not a reading.* A package that reads its
state back from a place others can write (an issue comment, a wiki page) verifies who wrote it
before trusting a counter or a done-key — devflow found, in its own controls, that a forged
marker comment reset its budgets (issue #14), which is a fail-open of exactly the kind the
platform refuses in itself.

## Child runs, and waiting on the world

Measured (issue #13, `stack/cases/child-run.yaml`, cold-start-linux run 26): a parent that starts
hello-lane with a `type: workflow` step, then waits. **The child's step saw the parent's run id**
— `5ed2fd86` on both sides — so a Conductor sub-workflow is *the same run* with a nested graph:
one `CONDUCTOR_SELF_RUN_ID`, one workspace under it, one evidence namespace (`route-<run>`,
`admit-<run>`), one record. That settles what each is for:

- **`type: workflow`** composes graphs. Use it to reuse a workflow's steps inside yours; the
  child writes into your workspace and its model calls land in your record. Do not use it for a
  run that needs a workspace, a record or an evidence directory of its own — a second `route`
  step in the child would write over the parent's.
- **`type: wait`** pauses (`duration: 1s`, measured `waited_seconds` 1.001); polling is `wait`
  plus a route that loops back. No Python.
- **A run of its own** is started through the stack's door, `run_workflow.py start`, as devflow's
  `drive.py` does — which was right, not a workaround. What the stack still owes there is the
  link: a child started from a step should carry its parent's `--suite`/`--case` so the record
  reads them together (issue #13, remaining).

## Asking for a retry

A fan-out member may ask to be run again when it does not produce:

```json
{"label": "E", "retries": 2, "retry_when": ["failed", "denied"], "steps": [ … ]}
```

No retry by default; `["failed"]` when retries are asked for and `retry_when` is not given — a
denial is an answer (a tool rule, or a person), and retrying an answer is something the workflow
says out loud. Every attempt is in the receipt as `attempts` and `attempt_outcomes`.

## Credentials of its own

A package that talks to something other than a model provider needs two things, and both are the
operator's to give — a capability the runtime does not need is one it does not get (OPERATIONS §36):

```
docker/package.env          KEY=value, git-ignored, read into the agent's environment
docker/egress/allow.local   one regex per line, git-ignored: the hosts this package may reach
                            (docker/egress/allow is the tracked provider baseline — platform
                            content, never a package's; the two merge at bring-up, §60)
```

Declare the hosts in your manifest as well — `requires: {egress: [api.example.com]}`. That is an
audit, not a control: the allowlist is **one file for one proxy shared by every container on the
governed network**, so a host opened for you is reachable by every other package, and `packages.py
egress` exists to say which open host nobody asks for any more. Per-role or per-package enforcement
would need its own container and its own proxy (OPERATIONS §45).

**Declare them in the manifest**, so the operator is told before a run instead of by your step's
error several minutes in:

```yaml
requires:
  env:
    - name: MY_LANE_TOKEN
      purpose: read the issues it reviews          # shown in the panel
      file: docker/package.env                     # where the operator puts it
```

```bash
docker exec cadp278-agent /opt/venv/bin/python /work/stack/packages.py needs
my-lane   MY_LANE_TOKEN   MISSING  docker/package.env — read the issues it reviews
```

The panel shows the same line under the workflow you select, as `있음` / `없음`. **Presence only.**
The value is never read, returned, logged, or typed into that screen: a panel that accepted a
credential would be a control-plane surface holding a secret, which is the one thing this stack
takes care not to build. Declaring it does not make it a precondition either — the stack reports,
and your step refuses at the point of use, because only it knows whether *this* run needs the
credential at all (trading declares KIS's keys; `trading-b` never touches them).

### When the credential has a login flow

A value the operator holds — an app key, a personal token — goes in the file above. A credential you
get by **authorising** something does not have to: declare the flow and the panel drives it exactly
the way it drives a provider's login (OPERATIONS §44).

```yaml
login:
  purpose: one line, shown on the screen
  argv: [gh, auth, login, --hostname, github.com, --web]   # a program and its arguments
  home_env: [GH_CONFIG_DIR]      # pointed at this login's own directory
  done_when: {file: hosts.yml}   # connected when this is there
```

The platform runs that argv under a pseudo-terminal in the agent, through the allowlist proxy, reads
the URL and the device code off its output, hands back the one-time code the operator pastes —
through a FIFO, never to disk, never logged — and calls it connected when your file appears.
**Nothing here ever opens that file**: whatever the flow mints is written by the thing that ran it,
and read back only by your steps, through `home_env`.

Two limits worth knowing. The program has to exist in the governed runtime image, so this is for a
CLI the stack already carries or a step of your own (`packages/hello-lane/steps/login.py` is a worked
example, and the reason the mechanism is measured rather than described). And `argv` is a list of
plain arguments — a shell line is refused, not escaped.

The stack does not hold them for you and does not ask for them: a composition without the file
simply cannot run what needs it. Your step reads `os.environ`, and when the value is not there it
**refuses with a hint that names the file** rather than failing halfway
(`packages/trading/steps/live_packet.py` is the worked example). Nothing else is opened: the proxy
refuses every host that is not in `allow`, including the one your step forgot to declare.

## Identities

If a step should run as its own principal, name it in the workflow
(`story=codex:my-reviewer`) and declare it in the package's `principals.yaml`, in the same shape as
`config/principals.yaml`. `scripts/up.sh` creates it and mints its credential.

A role that must reach its own domains declares a **profile**, beside its tool rules:

```yaml
principals:
  my-reviewer:
    egress_profile: closed        # runs in that profile's container, on that profile's network
```

The profile's proxy carries the host list; the broker maps the role and holds its credential; your
step's argv does not change (OPERATIONS §53–§55). The older `egress: [hosts]` key is retired — it
belonged to the uid-based design, and every `principals.py apply` names roles still on it.

**Installing a package is a decision to trust it**: that is what gives its principals rights. Read a
package before installing it, as you would a dependency.

## Controls

A package's rules are pinned by the package: `packages/<name>/controls.py`, run in the agent
container by `scripts/packages.sh verify` (or `controls [name]` alone), exit 1 on a failure. It
drives the package's real steps with fake inputs and no model call — `packages/novel/controls.py`
is the shape: a `load()` that points the step at a temporary workspace, a `check(name, got, want)`,
one function per risk, a summary line.

The platform's suite (`stack/trial_controls.py`) pins the platform and never imports a package to
pin that package's rules. Until 2026-10 it did — novel's triage, evidence index and round semantics
lived there, and the suite loaded trading's step as a fixture for the fan-out, so the platform's
checks failed on a machine that had not installed a private package (docs/record/PACKAGE-MATRIX.md,
X6). The rule now: a package this repository carries may serve as a fixture for a platform
capability; one it does not carry is skipped when absent, never imported; a package's own
judgements are its own controls. A package with no `controls.py` is listed by `verify` as having
nothing that pins its rules — which is the truth, and the reason to write one.

## Before you call it done

```bash
docker exec agentstack-agent /opt/venv/bin/python /work/stack/packages.py          # is it usable
docker exec agentstack-agent /opt/venv/bin/python /work/stack/run_workflow.py workflows --detail
scripts/up.sh                                                                  # principals applied
docker exec agentstack-agent /opt/venv/bin/python /work/stack/run_workflow.py \
  start <id> <workflow> research-default --detach
docker exec agentstack-agent /opt/venv/bin/python /work/stack/run_workflow.py tail <id> --follow
```

Then read it back the way everyone else will: [reading-a-run.md](reading-a-run.md).

And check the things that six packages got wrong between them (docs/record/PACKAGE-MATRIX.md):

- every step starts with `import step` and ends with `step.out(...)` — no copied workspace line,
  no `print(json.dumps(...))` of its own;
- every step declares `REPEATABLE`, including the ones a workflow calls only sometimes — the
  stack's controls scan every `packages/*/steps/*.py` and fail on one that does not;
- a model call goes through `agent_task.py`, never to the adapter directly: the direct call loses
  the produced/stale stamp, the login-refresh retry and the principal. Where the call runs is the
  role's business — a principal with an `egress_profile` is handed to the broker by that step, and
  the workflow never chooses a door;
- the package carries `controls.py`, and `scripts/packages.sh verify` runs it clean;
- **every** model call reaches the record: the primary one as `execute`, the rest in `executions`
  (a workflow that calls a reviewer and records only the author shows one call for a two-call run);
- `evidence_file` is passed when the run judged anything, with `items`;
- a manifest that requires `tool_rights` names a principal on every call that writes;
- every environment variable a step reads is in `requires.env`, so the operator is told before a
  run and not by a step several minutes in;
- data comes in by name through `handoff/` or travels in `fixtures/`; no absolute host path in a step;
- `requires.stack.min` names the oldest stack the package was run on.
