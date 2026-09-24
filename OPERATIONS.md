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
| `cadp` | no longer part of what runs here: it keeps issue #281, the history up to #292, and `poc/278-composition/` |

**This tree is the repository** (`astro3141/agent-stack`, private), and that is a change: the
measurements used to be made here and mirrored into `cadp` under `poc/281-routing/`. Two trees
produced exactly one class of bug, and review found it rather than we did: `novel_reviews.py`
was published calling `fanout.run_all(..., ledger=…)` against a `run_all(jobs)`
published without that parameter, so the copy that ran was the other one and "measured on the
running stack" described code no reader could execute. A mirror check was written, then widened
twice as it kept finding what it did not compare (fixtures and policy; deletions; the root
documents). None of that is needed now: there is one tree, and it is the one that runs.

What the move did **not** carry: the composition's own history, which stays in `cadp` under
`poc/278-composition/`. This history starts at `9cce003`, the snapshot taken when that work ended.

One difference from the published copy survived the move and is worth keeping in mind:

| file | this tree (running) | the copy in `cadp` history |
|---|---|---|
| `docker/agent.Dockerfile` | unpinned installs; copies one host CA file | Claude 2.1.278, Conductor `87f7788e`, Preloop CLI 0.15.0 pinned; `ca/` directory, certificates unversioned |

So **the running agent image was built from the unpinned Dockerfile**, and the versions in it are
whatever the installers returned on 2026-09-22 (§3). The pinned Dockerfile in the repository has
never been built here. The compose defaults are the repository's relative ones on both sides;
what differs is this host's `docker/.env`, which is where a host's own paths belong.

### What the platform provides, and what a workflow decides

`CONTRACT.md` draws that line: the platform provides capabilities with guarantees, the workflow
decides behaviour. It carries the audit of where this PoC had crossed it — the fan-out each
workflow had re-implemented (now `p281/steps/tasks.py`), the "required review" judgement that sat
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

**What a composition changes for a run.** `p281/capabilities.py` probes the services themselves
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
| cadp278-agent | cadp278/governed-runtime:local | `3e8bd6e7acaf` | unless-stopped |
| cadp278-quota | cadp278/governed-runtime:local | `3e8bd6e7acaf` | unless-stopped |
| cadp278-mlflow | cadp278/mlflow:3.16.1 | `57a342f2b725` | unless-stopped |
| cadp278-toolsvc | cadp278/toolsvc:local | `38b87dca3845` | unless-stopped |
| cadp278-fsmcp | cadp278/fsmcp:local | `f57433a16a90` | unless-stopped |
| cadp278-egress | cadp278/egress:local | `c458342cf3e7` | unless-stopped |
| cadp278-ops | cadp278/ops:local | `9e0c9a20f6f6` | unless-stopped |
| cadp278-hub | cadp278/hub:local | `5242dbd198af` | unless-stopped |
| preloop-oss api / worker / flow-worker / scheduler / gateway | ghcr.io/preloop/preloop:0.15.0 | `82728945c4b6` | unless-stopped |
| preloop-oss console | ghcr.io/preloop/console:0.15.0 | `d53da2640ace` | unless-stopped |
| preloop-oss postgres | pgvector/pgvector:pg16 | `ccc6e83d6e35` | unless-stopped |
| preloop-oss nats | nats:alpine | `ac8f88a6494b` | unless-stopped |

The `:local` tags are mutable: a rebuild replaces them and the previous image keeps no tag. There
is no release history to go back to.

## 3. Tool versions — and where they live

Read inside `cadp278-agent`:

| tool | path | version in use | same path inside the image |
|---|---|---|---|
| claude | `/home/agent/.local/bin/claude` | 2.1.278 | 2.1.278 |
| conductor | `/home/agent/.local/bin/conductor` | v0.1.37 | v0.1.37 |
| preloop CLI | `/home/agent/.local/bin/preloop` | 0.15.0 (`c91b326`) | 0.15.0 |
| codex | `/opt/npm-global/bin/codex` | codex-cli 0.155.1 | 0.155.1 |
| grok | `/opt/npm-global/bin/grok` | 1.0.40 | 1.0.40 |
| node / python | image | v22.14.0 / 3.13.15 | — |
| acpx, claude-agent-acp, codex-acp | `/opt/npm-global` | 0.18.0, 0.79.0, 1.12.0 | same |

**`/home/agent` is a volume (`cadp278-agent-home`), and it masks the image's copy of that
directory.** Claude, Conductor and the Preloop CLI are installed there. Today the two copies agree,
but nothing keeps them in step: after a rebuild the container still runs the volume's binaries, and
after `claude update` inside the container the image's copy is stale. Consequences:

- **Replacing the image does not roll back those three tools.**
- A release must therefore be recorded as *code revision + image ids + configuration + the tool
  versions read from the running container* (this table), not as an image tag alone.

## 4. Where state lives, and what it costs to lose

| data | location | size | class | why |
|---|---|---|---|---|
| provider logins (Claude, Codex, Grok) + Codex session ledger | volume `cadp278-route-creds` → `/route` | 66 MB | **restore required** | only the operator can recreate them, interactively, per provider |
| Preloop agent enrolment, CLI config, the agent's own `~/.codex`, `~/.claude` | volume `cadp278-agent-home` → `/home/agent` | 771 MB | **restore required** | enrolment token and client id; re-enrolling is a manual Preloop operation |
| observer's Codex login (+ caches) | volume `cadp278-quota-home` → `/home/agent` (quota) | 1.3 GB | **restore required** (login part) | operator login; the caches inside are disposable |
| Preloop account, policies, MCP servers, approval history, custodied credentials | volume `preloop-oss_postgres-data` | 22 MB | **restore required** | registration closes after the first user; re-creating it is a manual bootstrap |
| Preloop secrets/config | `~/.preloop-oss/.env` (21 lines) | 1 KB | **restore required** | the database is bound to these keys; without it a restored DB is not usable |
| research data | bind `D:\Work\research-280` → `/research` | 49 MB | **restore required** | the actual subject of the #280 work |
| MLflow database and artifacts | bind `evidence/mlflow` → `/mlflow` | 12 MB | **restore required** | the record of every run; SQLite file and artifacts must be kept together |
| run evidence: `evidence/ui-runs`, `evidence/p281`, `evidence/runs`, `evidence/conductor-events` | workspace | 3 MB | **restore required** | a run's UI record, its Conductor event log and its artifacts are one unit — they are kept or dropped together |
| settings sources: `config/environment.yaml`, `config/profiles/*`, `policy/*` | workspace (versioned) | small | **restore required** if edited locally | the repository holds them, but operator edits live here first |
| apply state `config/generated/state.json` | workspace (git-ignored) | small | **special** | derived in form, but it records which policy this tool made active on the account. It pairs with the Preloop database: restore both from the same snapshot, or reset it and apply again. Never restore it against a different Preloop database |
| generated settings `config/generated/*.json` | workspace | small | regenerate | `cfg.py generate` |
| quota observations | volume `cadp278-quota-obs` → `/obs` | 12 KB | regenerate | the observer rewrites them within minutes |
| per-run workspaces | volume `cadp278-ws` → `/ws` | 700 KB | regenerate / discard | scratch for a run; keep only while the run is open |
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
   (`RUNBOOK.md`, #278 §2.1–2.6 plus the #281 bring-up and the operator logins).

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
(`STACK`, default `cadp278r`), its own volumes, its own Preloop project and its own ports (hub
8790, ops 8791, MLflow 5010, Preloop 8010/8011/3010). Both copies hold the *same* credentials, so
they must not run at once: the script refuses to start while the live instance is up, and prints
how to stop it.

**Result of the first real exercise** (backup `20260922-234312`, 1.1 GB, 14 members):

| criterion | result |
|---|---|
| archive readable and unchanged | 14/14 members match their SHA-256 |
| restored into a fresh clone (`poc/281-ops`), new volumes, new ports | instance `cadp278r` came up; live volumes and workspace untouched |
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
   (`cadp278-toolsvc`, `cadp278-fsmcp`), so in the restored copy the model could not reach them and
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
| 1 | the teardown command printed after a restore carried no instance name, so in a new shell it resolved to the live project | the restore writes `config/instance.env` (instance name, Preloop project, paths, ports) and `docker/.env`; `up.sh` and the new `down.sh` in that workspace read it | in the restored workspace, `up.sh --check` used ports 8791/8790 and `down.sh --volumes` removed only `cadp278r-*` and `preloop-restore_*`; the six live volumes were untouched |
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
`cadp278r` on its own ports → 16/16 checks → Preloop counts match → run history and MLflow
experiments present → `auto` workflow **PASS** → `down.sh --volumes` removed only the restored
instance → the live instance came back with 16/16 checks.

### Second review — four failure paths closed (2026-09-23)

| # | was | is now | checked |
|---|---|---|---|
| 1 | the restore compared its Preloop directory with the live one for equality only, and split the live mount list on spaces, so a parent directory of the live install (later `rm -rf`'d) and a path with spaces slipped through | every directory the restore writes to or deletes — its workspace and its Preloop install — is compared **both ways** against every directory the live instance uses, on normalised paths, read line by line. Docker's internal mount form (`/run/desktop/mnt/host/d/…`) is normalised first; unnormalised it matched nothing and the check passed silently | refused: workspace equal to, inside, or containing the live workspace; workspace equal to the live research directory; Preloop directory equal to, above, or inside a live directory; the restore's own two directories overlapping each other; and the same with spaces in the path. A separate target still passes |
| 2 | `down.sh --volumes` selected by name prefix, so with `STACK=cadp278r` a volume named `cadp278r-second-…` was selected too | the five volumes of the instance and its Preloop data volume are named exactly | with `cadp278r-second-route-creds` and `cadp278r-second-agent-home` present, only `cadp278r-route-creds` was removed; the lookalikes survived |
| 3 | `up.sh` defaulted `POC_HOST_DIR`/`RESEARCH_HOST_DIR` to its own directory and exported them, and a shell variable wins over `docker/.env` — so the live agent had ended up mounting the wrong research directory | no path is defaulted in `up.sh`/`down.sh`; one is exported only when the environment or a restored workspace's `instance.env` set it. Compose then reads `docker/.env`, and falls back to the relative defaults | after the fix the live agent mounts `D:/Work/research-280` again (it had been mounting `…/poc-278/evidence/research`), and the restored copy mounts its own |
| 4 | the row counts were read before the writers were stopped and the dump taken after, so an approval arriving in between made a good dump look wrong | the counts are read after the stop and immediately before `pg_dump`, from the same quiesced state | a fresh backup and restore: "80 tables, key counts match" |

Third exercise, end to end (archive `20260923-011845`): fresh clone → `cadp278r` on its own ports →
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
| 3 | the revision and configuration were read from wherever the script sat, the images from the running containers — they could describe different checkouts | every command first checks that this workspace is the one the agent mounts as `/work` (Docker's internal mount form normalised) | running `record` from the repository checkout: "this script is in … but cadp278-agent runs D:/Work/poc-278" |
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

These are covered by `p281/cleanup_controls.py` (13 checks), which runs against temporary
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

`p281/cleanup_controls.py` now covers 17 cases.

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

The credentials are the operator's: `p281/principals.py create <name>` prints the line for
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
  `p281/ops_health.py` shows it; clearing it stays an operator's decision, because this script may
  not declare another cycle dead.
- **it refuses rather than pretends.** The capabilities are checked before the run starts
  (§ compositions): a cycle that cannot be governed does not run, and the refusal is recorded with
  the reason.
- **it leaves a record.** One line per cycle in `evidence/ops/cycles.jsonl` — when, which run, how
  long, how it ended **and why**, and what the stack could do at the time. Skips and refusals are
  lines too, which is what a scheduler otherwise hides.
- **retention only when asked.** With `--retain-days` / `--retain-keep` it runs the same cleanup as
  by hand (§9: whole runs, live runs and pending approvals protected) and records what went.

`p281/ops_health.py` reads all of that back: how many cycles ran, were skipped or were refused, the
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
(`POST /api/approvals/<id>` → `p281/approvals.py decide`). An approval is a run stopped waiting for
a person; sending that person to a second console to answer it is where an unattended schedule
loses a night. Preloop still owns the decision — this records on our side too
(`evidence/ops/controls.jsonl`) that it was answered here, with what comment, and whether Preloop
took it. Policy editing and run comparison stay linked, not rebuilt: the panel offers no route for
starting a cycle, deleting runs or changing the composition, and a control fails if one appears.

**One implementation behind a cycle.** `p281/cycle.py` holds the rules (the lock, the refusal, the
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
the agent**: `cadp278-replay`, on the ops network, with the workspace mounted **read-only**, no
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
| **mode** | **approval bypass** (stop asking, for a while); which **policy version** is applied; **tool on/off per principal** (`tool_enabled_overrides`); an MCP server's `default_tools_approval_mode` (decide by rules vs ask a human); `registration_enabled`; the hook's `safe_read_auto_allow` | set by us from files (`cfg.py`, the MCP server entries) except the first two. **Bypasses and the applied policy are read and shown** (`p281/elsewhere.py`, `cfg.py status` → `replaced`); changing them stays in the console |
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
truth. So `p281/elsewhere.py` reads what another console could have changed underneath us, and the
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

`p281/trajectory.py <run>` assembles one answer from those places — Conductor's event log, the
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
`HTTP 404: Approval request not found` — it reached Preloop, and was not refused. `p281/approvals.py`
now takes both its address (`P281_PRELOOP_API`) and its credential (`PRELOOP_OPERATOR_TOKEN`, else
the hook credential under `P281_CREDENTIAL_HOME`) from where it runs, and `ops/server.py` runs it
locally instead of `docker exec`-ing into the agent. With neither credential it fails closed.

`scripts/up.sh` checks both directions on every bring-up, from the position the rule constrains:

```
ok    runtime may read approvals                   200
ok    runtime may not decide approvals             403
```

**What this is not.** It is a route restriction, not a rights restriction. The runtime's credential
still carries the permission, and anyone holding it from another network position can still decide.
`p281/ops_health.py` says so in the way it now reports: the probe describes *the position it was run
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

**Where they run now.** `cadp278-admin` — the same image as the agent (it carries the Preloop CLI
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
silently. So `p281/bootstrap_preloop.py` refuses to run unless the caller asserts `--unclaimed`, and
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

`p281/suite.py`:

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
`p281/ops_health.py`, so it appears in the panel where a person will see it — and signing in again
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

**The governance, which was the real gap.** `p281/workflows/novel-a.yaml` names the identities its
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
2. **`preloop.cadp.yaml` no longer publishes anything.** It did, and with the base file also
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
that instance did not declare. `p281/mcp_list.py claude` takes the **runtime's own** MCP credential
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
   {"ok": true, "scanned": ["cadp278-toolsvc", "cadp278-fsmcp"], "not_registered": []}
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

Until now a workflow was three things at once: a file under `p281/workflows/`, steps and prompts
scattered through `p281/`, and **its name written into a list inside `run_workflow.py` and a second
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

`p281/packages.py` answers three questions and no others — what is installed, where is its entry
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
`port/trading-harness`, in the old shape: its workflow under `p281/workflows/`, its steps beside the
platform's in `p281/steps/`, its prompts and fixtures in `p281/prompts/` and `p281/fixtures/`. It is
now `packages/trading-port/`, and the branch stays as the record of the port itself.

```
p281/workflows/trading-port.yaml          → packages/trading-port/workflow.yaml
p281/steps/{arch_port,packet_bridge}.py   → packages/trading-port/steps/
p281/steps/vendor/                        → packages/trading-port/steps/vendor/
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
   workflow is installed rather than copied into `p281/`. The agent now carries
   `PYTHONPATH=/work/p281:/work/p281/steps`: *the step library is importable from wherever a step
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
the ones this stack was written with, and they sat in `p281/` where a package's contents may not
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

`BUILT_IN` is now empty, and `p281/steps/` holds only what every workflow may call: `route.py`,
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

1. The controls scanned `p281/steps/` for *"every step says what a repeat of it does"*. Moved into
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
experiment: [containers.md](../docs/containers.md) — which container may do what, and that a 403 in
the agent is the boundary rather than an obstacle; [reading-a-run.md](../docs/reading-a-run.md) —
where a run's state, events, outputs, per-call evidence and record each land, with the command that
reads each; [packages.md](../docs/packages.md) — the contract a package's steps keep, which was
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
