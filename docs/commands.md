# Every command, in one place

Two rules for reading this list:

- **`scripts/*` run on the host.** They act on the instance this workspace belongs to — the one
  named in `config/instance.env` if there is one, otherwise the live one.
- **`p281/*.py` run inside a container**, and *which* container is part of the rule: anything that
  writes to Preloop runs in **admin**, because the guard refuses those writes from the agent's
  network (OPERATIONS §21).

```bash
docker exec cadp278-agent /opt/venv/bin/python /work/p281/<script>.py …    # reads, runs, MCP
docker exec cadp278-admin /opt/venv/bin/python /work/p281/<script>.py …    # writes to Preloop
```

## The stack

| | |
|---|---|
| `scripts/install.sh [--check] [--preloop-dir DIR] [--no-preloop]` | host check; install Preloop; bring up |
| `scripts/up.sh [--composition full\|no-record\|runtime] [--check] [--recreate]` | build, start, claim, apply policy and principals, check |
| `scripts/down.sh [--volumes] [--now]` | stop the runs first, then the containers. `--volumes` also deletes logins, the Preloop database and the agent home |
| `scripts/backup.sh [--out DIR] [--key FILE]` | one consistent, encrypted archive of everything that cannot be regenerated |
| `scripts/restore.sh …` | bring a backup up as a *separate* instance, and verify it against the live one |
| `scripts/release.sh record\|list\|update --to REV\|rollback --to TAG` | keep what is running, move to something else, go back |
| `scripts/cleanup.sh` | remove what is safe to remove, and say what it did not touch |
| `scripts/host-state.sh` | what the host looks like: containers, images, volumes, disk |
| `scripts/soak.sh <cycles> <workflow> [profile]` | run the same workflow many times and sample what grows |
| `scripts/cycle.sh <workflow>` | one unattended cycle, for a scheduler |

## Runs

| | |
|---|---|
| `run_workflow.py start <id> <workflow> <profile> [k=v …] [--suite N] [--case C] [--allow-unrecorded]` | start a run (agent) |
| `run_workflow.py stop <id>` | graceful cancel — it keeps a checkpoint |
| `run_workflow.py resume <id>` | re-enter the step that did not finish |
| `run_workflow.py show <id>` / `list` | one run, or the last fifty, as JSON |
| `trajectory.py <id> [--json]` / `--suite <name>` | what a run did, and the four assertions |
| `suite.py run <suite> <workflow> <profile> <cases.jsonl> [--concurrency N]` | one run per case |
| `suite.py read <suite> [--json]` | the set, with its execution facts |

## Governance

| | where |
|---|---|
| `principals.py apply [--dry-run]` | **admin** — make Preloop match `config/principals.yaml` |
| `principals.py list` | either — what exists and what each may do |
| `principals.py check <name>` | agent — what a principal's credential can actually do, asked not assumed |
| `principals.py create <name>` / `rules <name> <spec.json>` | **admin** — the manual forms of `apply` |
| `approvals.py` / `approvals.py decide <id> approve\|decline [comment]` | panel container; the agent may read but not decide |
| `cfg.py status` / `generate` | agent — reads the provider logins |
| `cfg.py apply` | **admin** — writes the policy to Preloop |
| `bootstrap_preloop.py --unclaimed …` | **admin** — claim a fresh instance (`up.sh` calls it) |

## State and health

| | |
|---|---|
| `ops_health.py [--last N] [--json]` | cycles, the lock, the last check, standing risks, capabilities, soaks |
| `capabilities.py` | what the running composition can do, probed |
| `elsewhere.py` | the switches elsewhere that would make this panel's claims untrue |
| `router.py <policy.json> <obs-dir>` | one routing decision, from observations only |
| `collect_obs.py <dir>` | collect the quota observations the router reads |
| `trial_controls.py` | every control, against synthetic inputs — the machinery, not the judgement |

## The panel

`http://127.0.0.1:8780` — provider login, approval decisions, starting a run, stopping and
resuming one, and the state needed to decide those. Its API (`127.0.0.1:8781`) has one route per
action, each mapping to one known command; adding a capability there is deliberate.

## Conventions worth knowing

- Every step declares what a repeat does (`REPEATABLE = "yes" | "guarded" | "no"`), OPERATIONS §17.
- A run is refused, not degraded, when a capability it needs is missing; `--allow-unrecorded` is
  the one explicit exception.
- A credential is never an argument or a log line: it is piped, or written by the host at 0600.
