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
description: one line, shown in the panel's 새 실행 tab
workflows:                    # or `entry: workflow.yaml` for a single one
  my-lane: workflow.yaml
requires:
  capabilities: [tool_rights, egress, record, admission]   # the runner refuses a run without them
runbook: RUNBOOK.md           # your operating document — the panel links it under the workflow
```

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

**1. Address the workspace through `settings`, never by guessing.**

```python
import settings
RUN = os.environ.get("CONDUCTOR_SELF_RUN_ID", "manual")
WS  = f"{settings.runtime()['paths']['workspace_root']}/{RUN}"
```

The run's workspace is `<workspace_root>/<conductor run id>`, and every other reader — the
recorder, the evidence index, the panel — resolves it the same way. A step that invents its own
path writes where nothing will look for it.

**2. The last line of stdout is JSON, and it is the step's output.**

Conductor reads it and the workflow's `output:` block names its fields. Anything else you print is
for a human; the last line is the contract. A step that cannot do its work prints JSON saying so
rather than raising.

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
