# Runbook

What to do, starting from what you can see. Every entry here is something that actually happened on
this stack; the measurement behind it is in OPERATIONS.md under the section named.

For the state the composition started from, see [RUNBOOK.md](../RUNBOOK.md) — that file is history,
this one is operation.

---

## Every session

```bash
scripts/up.sh --check                                    # about twenty questions, and the capabilities
docker exec cadp278-agent /opt/venv/bin/python /work/p281/ops_health.py
```

`up.sh --check` changes nothing. Read it in three parts: **isolation** (the agent has no route out
except the allowlist proxy), **services and the boundary** (Preloop answers, and the runtime may
read but not decide), **logins and quota** (the only part that needs a person).

`ops_health.py` adds what a single check cannot see: recent cycles, a stuck lock, standing risks,
and whether recent runs were recorded.

The panel (`http://127.0.0.1:8780`) shows the same state and is the only place with buttons, and
only for decisions a person must make.

## Starting and stopping

```bash
scripts/up.sh                  # safe to repeat; it converges (idempotent), it does not reset
scripts/down.sh                # stops the runs first, so each keeps a checkpoint
scripts/down.sh --now          # do not wait for runs; the step in flight is lost
scripts/down.sh --volumes      # also deletes logins, the Preloop database and the agent home
```

`down.sh` without `--now` asks the run list what is in flight and stops each one the way a person
would, which is what leaves a checkpoint behind (OPERATIONS §23). `--volumes` prints exactly which
volumes it will remove and refuses anything named differently — but it removes the provider logins,
so a person has to sign in again afterwards.

---

## Runs hold: "no eligible provider"

**Look:** `up.sh --check` → `every provider's state is knowable` is not `0`, or the panel's
dashboard shows a standing risk.

```
FAIL  every provider's state is knowable   expected 0, got 1
      claude: unknown: unparseable observed_at
```

**What it means.** The router could not determine that provider's state. Being **at a limit** or
having a **stale** observation is ordinary and does not fail the check; *not being able to tell*
does, because every run needing that provider will hold while the login file still looks present.

**Most often:** the OAuth token behind the login expired. Confirm:

```bash
docker exec cadp278-agent sh -c 'CLAUDE_CONFIG_DIR=/route/claude HTTPS_PROXY=http://egress:8888 \
  codexbar usage --provider claude --source oauth --json'
# → "Claude OAuth token expired. … Run `claude login`, then retry."
```

**Do:** sign in again from the panel's 계정 tab. That is a person's job — the stack will not do it
and cannot. Then `up.sh --check` should show `0` again (OPERATIONS §24).

## A run is going and will not end

**Look:** `run_workflow.py show <id>` says `running`, and the step has not changed for a long time.

```bash
docker exec cadp278-agent sh -c 'ps -eo pid,etime,args | grep "[r]un_workflow\|[c]onductor-cli"'
```

**Do:** stop it the way a person would, so it keeps a checkpoint, then continue it when you want:

```bash
docker exec cadp278-agent /opt/venv/bin/python /work/p281/run_workflow.py stop <id>
docker exec cadp278-agent /opt/venv/bin/python /work/p281/run_workflow.py resume <id>
```

or use **중지** / **재개** in the panel. Resume re-enters the step that did not finish; the steps
before it are not run again (measured: a stopped `novel-a` finished in 4 model calls where a full
run makes 5 — OPERATIONS §23).

**If launchers outlive their runs** — a run shows finished but the process is still there — that is
the shape of a defect this stack has had twice. The current design waits on the *event log*, not on
the process, and tidies the dashboard after. If you see it again, capture `ps` output before
killing anything.

## A stopped run cannot be continued

**Look:** `run_workflow.py list` shows `resumable: false` for a run that did not finish.

A checkpoint exists only when the run was cancelled **gracefully**. A run killed with its container
(`down.sh --now`, a crash, a machine restart) leaves none: start it again instead. This is why
`down.sh` stops runs first.

## The panel does not do what the code says

**Cause, measured:** the image was not rebuilt. `ops/server.py` and `hub/index.html` live in
images; editing the file changes nothing until the image is built.

```bash
scripts/up.sh          # builds what this tree owns, every time
```

If you brought containers up with `docker compose` by hand, you skipped that.

## A guard rule was edited and is not enforced

**Cause:** `docker/apiguard.conf` is a bind-mounted file, and compose does not restart a container
because a file under it changed. `up.sh` reloads it on every bring-up; by hand:

```bash
docker exec cadp278-apiguard nginx -t && docker exec cadp278-apiguard nginx -s reload
```

Verify from the position the rule constrains — inside the agent, not from the host:

```bash
docker exec cadp278-agent sh -c 'curl -s -o /dev/null -w %{http_code} -X POST \
  -H "Content-Type: application/json" -d "{\"approved\":true}" \
  http://api:8000/api/v1/approval-requests/00000000-0000-0000-0000-000000000000/approve'
# 403 = the guard is in the path.  404 = it is not.
```

## Something is waiting for an approval

**Look:** the panel's 승인 대기 card, or:

```bash
docker exec cadp278-ops python3 /work/p281/approvals.py
```

**Do:** decide it in the panel. The agent may *read* what is waiting and cannot decide it — that is
the point (OPERATIONS §20). Every decision made through the panel records the fingerprint of the
credential that made it in `evidence/ops/controls.jsonl`.

## Preloop does not answer

**Look:** `up.sh` stops with `Preloop did not come up; nothing below would be governed`, or the
`Preloop api` check fails.

```bash
docker compose --project-directory ~/.preloop-oss -p preloop-oss \
  -f ~/.preloop-oss/docker-compose.yaml -f ~/.preloop-oss/docker-compose.auth.yaml ps
docker logs preloop-oss-api-1 --tail 50
```

A first boot runs migrations and takes minutes; `up.sh` waits up to 180 seconds for the API to
answer. If the database is the problem, the Preloop volume is in the backup —
`preloop-oss_postgres-data` holds the account, its policies, the principals and the approval
history, and nothing else does.

## A fresh machine, or a restore without the Preloop database

`up.sh` claims an unclaimed instance by itself: it counts rows in Preloop's own `user` table, and
on zero it registers the first user with the bootstrap token, issues the runtime's credential and
installs the permission hook (OPERATIONS §22). The console account it created is in
`docker/preloop-owner.env`.

**It claims; it does not restore.** Approval history, principals and custodied credentials come
back only from a backup.

## Disk keeps growing

```bash
scripts/host-state.sh          # containers, images, volumes, disk
scripts/cleanup.sh             # removes what is safe, and names what it left alone
```

A soak is the way to tell growth from a leak: `scripts/soak.sh <cycles> <workflow>` samples memory,
disk and run outcomes before and after every cycle and writes `evidence/soak/<id>/summary.json`. It
cleans nothing, deliberately — growth measured with a cleaner running is not growth.

## A cycle says it is busy and nothing is running

A killed run can leave the cycle lock behind. `ops_health.py` reports it (`lock`), and the panel
shows it. Clear it only after confirming no run is in flight.

## Permission denied writing `config/generated` or `evidence` (Linux)

The containers run as uid 1000 and this tree is owned by whoever cloned it. `up.sh` opens exactly
the two trees the containers write to; if you ran something by hand as another user, repeat the
bring-up. No credential lives in either tree — those are in `docker/*.env`, which the host writes
at 0600 (OPERATIONS §25).

---

## Backup, restore, update, rollback

```bash
scripts/backup.sh                          # stops the writers, dumps, restarts, encrypts
scripts/restore.sh --archive <file> …      # brings the backup up as a SEPARATE instance
scripts/release.sh record                  # keep what is running now
scripts/release.sh update --to <rev>       # record, move, rebuild, check
scripts/release.sh rollback --to <tag>     # put a kept release back
```

Two things worth knowing before you need them:

- **A restore is verified beside the live instance**, never over it: another name, other ports, its
  own Preloop project. The restored database is checked against the backup's row counts, and a
  mismatch stops the restore rather than starting something that looks fine.
- **A release is not an image tag.** The toolchain lives in a volume that masks the image's copy, so
  a release is *code revision + image ids + configuration + the toolchain itself*. Data is not part
  of it; that is what backup covers.

Losing the backup key means losing the backup. Keep the key and the archive in different places.

---

## Things not to do

- **Do not run `preloop agents onboard` or `discover` on the host.** They rewrite the host's own
  agent configuration. The stack onboards inside its own container, against its own home.
- **Do not mount the host's `~/.claude` into a container.** The isolation this stack is built on is
  that the governed runtime has its own logins and its own home.
- **Do not put a token, cookie or API key into a log, an issue or a commit.** Credentials are piped
  or written by the host at 0600; a fingerprint (`sha12`) is what goes in a record.
- **Do not decide an approval from the agent**, and do not work around the guard to do it. If the
  decision has to happen, it happens in the panel, as a person.
- **Do not add a button for something an operator could type.** The screen is for decisions a person
  must make; everything else is a command or a file, so the truth has one home.
