# Agent Stack

A governed execution stack for coding agents, and the record of measuring it.

Four things run here, and only one of them was written for this stack:

| | what it does | ours? |
|---|---|---|
| **Preloop OSS** | tool rights and approvals — the MCP proxy that decides what an agent may do, per principal | no |
| **Conductor** | the workflow engine that walks a graph of steps | no |
| **MLflow** | where a run's facts are recorded and compared | no |
| **acpx** | the agent-client protocol runtime the providers' CLIs speak | no |
| **the routing / execution layer** | one entry point that owns the provider connections (Claude, Codex, Grok), decides from quota whether anything may run, presents the right credential, and returns one normalized result whatever the vendor | **yes** |

Most of the work is not the routing layer itself: it is making those four hold together under real
constraints — network isolation, an egress allowlist, credentials that never leave their own
directory, and the operations that let the result survive a restart, an update or a bad week.

## Where things are

| | |
|---|---|
| `docker/` | the composition: compose file, one Dockerfile per service, the egress allowlist, how Preloop joins these networks |
| `p281/` | the routing layer (`run-agent.mjs`, `router.py`, `collect_obs.py`), the platform capabilities (`steps/tasks.py`, `steps/task_chain.py`, `steps/record.py`, `capabilities.py`), the workflows and their domain steps, and the controls |
| `scripts/` | operations: `up.sh` / `down.sh`, `backup.sh` / `restore.sh`, `release.sh`, `cleanup.sh`, `soak.sh`, `cycle.sh` |
| `policy/`, `gate/`, `config/` | the tool policies, the evidence gate, and the profiles everything is generated from |
| `evidence/` | what runs actually produced — checks, UI runs, soak samples, operations records |

## Start here

| | |
|---|---|
| **[docs/install.md](docs/install.md)** | from a clone to a running stack, what the host needs, and what only a person can do |
| **[docs/concepts.md](docs/concepts.md)** | how the five pieces fit, the one rule they are arranged around, and what a run leaves behind |
| **[docs/commands.md](docs/commands.md)** | every command, and which container it belongs in |
| **[docs/runbook.md](docs/runbook.md)** | what to do when something is wrong, with the symptom first |

## The documents that matter

- **[CONTRACT.md](CONTRACT.md)** — the line this codebase is organized around: *the platform
  provides capabilities; it does not decide behaviour.* Each capability with its guarantee, and
  what it leaves to the caller. Read this before adding anything.
- **[COVERAGE.md](COVERAGE.md)** — this stack measured against the workflow design procedure it is
  meant to serve: what it covers, what is only partial, and what is missing (with issues).
- **[OPERATIONS.md](OPERATIONS.md)** — what is actually running and what must survive it: backup
  and restore, update and rollback, cleanup, compositions, tool policy per principal, and long
  operation. Every section is a measurement, including the ones that went wrong.
- **[RUNBOOK.md](RUNBOOK.md)** — the composition stack as first measured (#278), kept as the state
  it started from. For operating the stack as it is now, use [docs/runbook.md](docs/runbook.md).
- `p281/TRIAL-A-novel.md`, `p281/TRIAL-B-trading.md` — whether workflows of a given shape actually
  run here, and what broke when they did.

## Installing it

```bash
scripts/install.sh --check           # what the host is missing, changing nothing
scripts/install.sh                   # install Preloop OSS if needed, then bring the stack up
```

**What the host needs**, and what the check asks for by name:

| | why |
|---|---|
| Docker, and a running daemon | everything here is containers |
| **Docker Compose 2.24 or newer** | the composition uses `env_file: required: false`; an older compose fails with a parse error that does not say which feature it did not know |
| bash, git, curl | the scripts, and Preloop's own installer |
| **x86_64** | `docker/agent.Dockerfile` installs a linux-x64 Node and an x86_64 CodexBar. Every image this stack pulls is multi-arch, so arm64 needs those two lines parameterized — it has not been done or tried |
| ~20GB free | images and volumes |

The installer runs **Preloop's own installer** (`https://preloop.ai/install/oss`) into
`~/.preloop-oss` when that directory is not there, and `--preloop-dir` puts it elsewhere. From then
on `scripts/up.sh` is enough: it builds this tree's images, **claims a fresh Preloop** (registers
the first user with the bootstrap token, issues the runtime's credential — OPERATIONS §22), applies
the account policy from `policy/` and the principals declared in `config/principals.yaml`, and
checks the result.

**What no script will do for you: sign in to a provider.** Claude, Codex and Grok accounts belong
to a person, on the vendor's own page. The panel's 계정 tab is where that happens
(`http://127.0.0.1:8780`), and until it does, runs hold with `no eligible provider` — which the
bring-up now says out loud rather than reporting a login file's existence as a login.

Choices worth making before installing, none of which the script decides for you:

- **Which composition.** The full stack, or `--composition no-record` (no MLflow) / `minimal` —
  `scripts/up.sh` prints what each one costs in capabilities.
- **Where Preloop lives.** `--preloop-dir`, if `~/.preloop-oss` is not where you want it.
- **The instance's name and ports.** `config/instance.env` (`STACK`, `OPS_PORT`, `HUB_PORT`,
  `PRELOOP_*_PORT`) — a second instance on the same machine needs its own.

## Running it

```bash
scripts/up.sh                        # everything, then check it
scripts/up.sh --composition no-record   # without MLflow, and be told what that costs
scripts/cycle.sh trading-b           # one unattended cycle, for a scheduler to call
docker exec cadp278-agent /opt/venv/bin/python /work/p281/ops_health.py
```

`scripts/up.sh --check` answers about twenty questions about isolation, services, logins and quota
observation, and prints which capabilities the running composition has.

## How this repository came to be

The measurements were made in a working tree that lived beside the `cadp` repository and was
mirrored into it under `poc/281-routing/`. Keeping two trees produced exactly one class of bug —
code that was published but could not run, because the copy that ran was the other one — so the
tree that runs is now the repository. Its history starts at `9cce003`, the snapshot taken when the
composition work (`cadp` issue #278) ended and the routing layer (#281) began; the composition's
own history stays in `cadp` under `poc/278-composition/`.

Nothing here is a product. It is a proof of concept with its measurements attached, including the
ones that corrected earlier claims.
