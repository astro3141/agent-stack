# Every command, in one place

Two rules for reading this list:

- **`scripts/*` run on the host.** They act on the instance this workspace belongs to — the one
  named in `config/instance.env` if there is one, otherwise the live one.
- **`stack/*.py` run inside a container**, and *which* container is part of the rule: anything that
  writes to Preloop runs in **admin**, because the guard refuses those writes from the agent's
  network (OPERATIONS §21).

```bash
docker exec agentstack-agent /opt/venv/bin/python /work/stack/<script>.py …    # reads, runs, MCP
docker exec agentstack-admin /opt/venv/bin/python /work/stack/<script>.py …    # writes to Preloop
```

## The stack

| | |
|---|---|
| `scripts/install.sh [--check] [--preloop-dir DIR] [--no-preloop]` | host check; install Preloop; bring up |
| `scripts/up.sh [--composition full\|no-record\|runtime] [--observer] [--check] [--recreate]` | build, start, claim, apply policy and principals, check; `--observer` adds codex's optional second quota source |
| `scripts/down.sh [--volumes] [--now]` | stop the runs first, then the containers. `--volumes` also deletes logins, the Preloop database and the agent home |
| `scripts/backup.sh [--out DIR] [--key FILE] [--no-stop] [--allow-missing]` | one consistent, encrypted archive of everything that cannot be regenerated — Preloop's database, the login volumes, MLflow, evidence, `config/`, `policy/`, `state/`, Preloop's install directory and `docker/*.env` |
| `scripts/restore.sh --archive FILE --workspace DIR [--stack NAME] [--key FILE] [--clone-from REPO --rev REV] [--into-existing]` | bring a backup up as a *separate* instance, and verify it against the live one |
| `scripts/restore.sh --archive FILE --verify-only [--key FILE]` | unpack the archive and check every member against its manifest; writes nothing |
| `scripts/release.sh record [--tag NAME]\|list\|update --to REV\|rollback --to TAG` | keep what is running, move to something else, go back |
| `scripts/verify.sh [--level static\|stack\|full]` | verify this tree as far as this machine allows: a checkout, a running stack with nobody signed in, or an instance with logins — the level picks itself unless named |
| `scripts/drift.sh [--json] [--offline]` | what is pinned and what each registry has now; reports, changes nothing ([update-day.md](update-day.md)) |
| `scripts/packages.sh list\|install\|verify\|controls [name]` | the workflow packages: what is declared, fetch what is not local, check it is still the pinned commit, run its own controls |
| `scripts/cleanup.sh [--days N] [--keep N] [--apply] [--include-orphans] [--json]` | **a preview by default**: what would go, as whole runs, and what is protected. `--apply` removes it |
| `scripts/credentials.sh [list\|fill\|set NAME]` | put a credential a package declares where it says it lives, from a terminal prompt — never through the panel |
| `scripts/host-state.sh` | what the host looks like: containers, images, volumes, disk |
| `scripts/soak.sh <cycles> <workflow> [profile]` | run the same workflow many times and sample what grows |
| `scripts/cycle.sh <workflow> [profile] [k=v …] [--allow-unrecorded] [--retain-days N] [--retain-keep M]` | one unattended cycle, for a scheduler; exit 0 ran or busy, 3 refused, 1 the runner failed |

## Runs

| | |
|---|---|
| `run_workflow.py start <id> <workflow> <profile> [k=v …] [--suite N] [--case C] [--detach] [--allow-unrecorded]` | start a run (agent); `--detach` returns the id instead of waiting |
| `run_workflow.py tail <id> [--follow]` | the steps as they happen, from the run's own event log |
| `run_workflow.py stop <id>` | graceful cancel — it keeps a checkpoint |
| `run_workflow.py resume <id>` | re-enter the step that did not finish |
| `run_workflow.py show <id>` / `list` | one run, or the last fifty, as JSON |
| `trajectory.py <id> [--json]` / `--suite <name>` | what a run did, and the four assertions |
| `suite.py run <suite> <workflow> <profile> <cases.jsonl> [--concurrency N]` | one run per case |
| `suite.py read <suite> [--json]` | the set, with its execution facts |
| `packages.py list [--json]` / `show <name>` | the installed workflow packages, and why an unusable one is unusable |
| `packages.py python\|needs\|egress\|stack\|state\|logins [<name>] [--json]` | what each package needs of the image, the environment, the allowlist, the stack revision; where it keeps state; the login it declares |
| `run_workflow.py workflows [--detail]` | what may be started — built-ins and packages, the one answer the panel uses too |

## Governance

| | where |
|---|---|
| `principals.py apply [--dry-run]` | **admin** — make Preloop match `config/principals.yaml` |
| `principals.py list` | either — what exists and what each may do |
| `principals.py check <name>` | agent — what a principal's credential can actually do, asked not assumed |
| `principals.py create <name>` / `rules <name> <spec.json>` | **admin** — the manual forms of `apply` |
| `approvals.py` / `approvals.py decide <id> approve\|decline [comment]` | panel container; the agent may read but not decide |
| `cfg.py status` / `generate` / `validate` | agent — reads the provider logins; `generate` is what every run reads (`config/generated/`), and `up.sh` runs it |
| `cfg.py apply [--force]` | **admin** — writes the policy to Preloop; `--force` ignores the stack's own record of having done so |
| `cfg.py rescan` | **admin** — scan the policy's MCP servers again, when their tools are not exposed |
| `bootstrap_preloop.py --unclaimed …` | **admin** — claim a fresh instance (`up.sh` calls it) |

## State and health

| | |
|---|---|
| `ops_health.py [--last N] [--json]` | cycles, the lock, the last check, standing risks, capabilities, soaks |
| `capabilities.py [--profile <name>] [--json] [--missing] [--allow-unrecorded]` | what the running composition can do, probed — admission is asked of that profile |
| `elsewhere.py` | the switches elsewhere that would make this panel's claims untrue: standing approval bypasses, the MCP servers the account has |
| `admission.py <profile> [--candidates a,b] [--dir DIR]` | **the one door to the router**: the profile's policy, a fresh collection, one decision. What `route.py`, `admit_models.py`, `capabilities.py` and the checks all call |
| `router.py <policy.json> <obs-dir>` / `collect_obs.py <dir>` | the two halves `admission.py` runs; alone, the collector needs the routes and logins `admission.py` sets in its environment (`AGENTSTACK_MODEL_ROUTES`, `AGENTSTACK_LOGINS`) |
| `grok_posture.py ensure\|check [<GROK_HOME>…]` | the `[permission]` table that turns Grok's native tools off, in its own config — written on login and on every bring-up, checked by `up.sh --check` |
| `trial_controls.py` | every control, against synthetic inputs — the machinery, not the judgement |

## The panel

`http://127.0.0.1:8780` — provider login, approval decisions, stopping a run, and the state
needed to decide those. It starts nothing and resumes nothing (#24): the 워크플로 tab shows the
command to copy. Its API (`127.0.0.1:8781`) has one route per action, each mapping to one known
command; adding a capability there is deliberate.

## Where things are

[containers.md](containers.md) — which container may do what, and why a 403 in the agent is the
boundary rather than a problem. [reading-a-run.md](reading-a-run.md) — where a run's state, events,
outputs, evidence and record each land.

## Conventions worth knowing

- Every step declares what a repeat does (`REPEATABLE = "yes" | "guarded" | "no"`), OPERATIONS §17.
- A run is refused, not degraded, when a capability it needs is missing; `--allow-unrecorded` is
  the one explicit exception.
- A credential is never an argument or a log line: it is piped, or written by the host at 0600.
