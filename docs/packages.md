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
  trading:
    from: https://github.com/astro3141/agent-stack-trading.git
    ref: main
```

```bash
scripts/packages.sh install trading   # clones it, writes config/packages.lock, git-ignores it here
scripts/packages.sh verify            # is what is on disk still the commit the lock names
scripts/up.sh                         # applies what it declares
```

Domain content belongs in its own repository: a platform repository should say which workflows it
runs, not carry them. The fetch happens on the host, so no git credential is ever inside the
governed runtime.

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
```

A package may carry **several workflows** when they share steps — that is why the three trading
workflows are one package.

A workflow **name** belongs to whichever package declares it, and to only one: a name two installed
packages declare is carried by neither, and `packages.py` and any refused run name both packages so
you can rename one. Check yours against what is already installed:

```bash
docker exec cadp278-agent /opt/venv/bin/python /work/p281/run_workflow.py workflows
```

## Which container runs what

Every step runs in the **agent**, with `/work` mounted and `PYTHONPATH=/work/p281:/work/p281/steps`,
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

**4. Evidence files use `items`.** `p281/steps/record.py` counts and stores exactly that key; a file
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
docker/egress/allow         one regex per line: the hosts this package may reach
```

The stack does not hold them for you and does not ask for them: a composition without the file
simply cannot run what needs it. Your step reads `os.environ`, and when the value is not there it
**refuses with a hint that names the file** rather than failing halfway
(`packages/trading/steps/live_packet.py` is the worked example). Nothing else is opened: the proxy
refuses every host that is not in `allow`, including the one your step forgot to declare.

## Identities

If a step should run as its own principal, name it in the workflow
(`story=codex:my-reviewer`) and declare it in the package's `principals.yaml`, in the same shape as
`config/principals.yaml`. `scripts/up.sh` creates it and mints its credential.

**Installing a package is a decision to trust it**: that is what gives its principals rights. Read a
package before installing it, as you would a dependency.

## Before you call it done

```bash
docker exec cadp278-agent /opt/venv/bin/python /work/p281/packages.py          # is it usable
docker exec cadp278-agent /opt/venv/bin/python /work/p281/run_workflow.py workflows --detail
scripts/up.sh                                                                  # principals applied
docker exec cadp278-agent /opt/venv/bin/python /work/p281/run_workflow.py \
  start <id> <workflow> research-default --detach
docker exec cadp278-agent /opt/venv/bin/python /work/p281/run_workflow.py tail <id> --follow
```

Then read it back the way everyone else will: [reading-a-run.md](reading-a-run.md).
