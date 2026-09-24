# Runbook

**The operator's document.** It opens with what the job actually is — the five things this stack
cannot do for itself — and the rest is what to do when something is wrong, starting from what you
can see. Every entry is something that actually happened here; the measurement behind it is in
OPERATIONS.md under the section named.

Read [docs/concepts.md](concepts.md) once, to know why the pieces are arranged this way.
[docs/commands.md](commands.md) is the reference you keep open beside this one.

For the state the composition started from, see [RUNBOOK.md](../RUNBOOK.md) — that file is history,
this one is operation.

---

## The job

Most of this stack looks after itself: it refuses a run it cannot govern, it records what it did,
and it says what it cannot tell. Five things it cannot do, and those are the operator's.

| the duty | how you know it is due | where |
|---|---|---|
| **Sign in to the providers** | `every provider's state is knowable` is not `0`, or runs hold with `no eligible provider`. Tokens expire on their own schedule, so this is not a calendar item | panel, 계정 |
| **Decide the approvals** | a run is waiting; the 승인 대기 card is not empty. Nothing else can decide them, by design | panel |
| **Decide whether a run should keep going** | a run is going that should not be, or a stopped one is worth continuing | panel, 중지 / 재개 |
| **Keep a backup, and its key** | before any update or rollback, and on whatever cadence the data deserves. The Preloop database is the only copy of the account, its policies, the principals and the approval history | `scripts/backup.sh` |
| **Say what the stack may become** | an update, a rollback, a change of composition, a new principal or policy — none of it happens on its own | `scripts/release.sh`, `config/` |

Two of those are accountability rather than action: **who holds the backup key**, and **who is
allowed to answer an approval**. Both are a person's, and neither is enforced by the stack — the
approval boundary here is a route, not a right (concepts.md).

Everything else an operator does to this stack is a command or a file. If you find yourself wanting
a button for it, that is the signal to write it down in `config/`, not in a screen.

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

## A fresh install: logged in, and one provider still unusable

**Look:** the accounts view shows all three providers 연결됨, and one of them is refused:

```
codex   불일치   unknown: nothing has observed this account yet (executing='email:4d34…')
                 — the quota observer has no login for it
```

**What it means.** There are **two** login lineages here, deliberately: the **routing** logins under
`/route` that actually execute, and the **quota observer's** own login in its own container, which
reads the provider's remaining quota. The router uses a provider only when the account that was
observed is the account that will execute — so an observer with no login leaves that provider with
no usable observation, however well the routing login works.

Claude and Grok usually survive this because their observation comes from the same credential that
executes. Codex is read through the observer, so it is the one that shows.

**Do:**

```bash
docker exec -it "$STACK-quota" codex login      # the SAME account the routing login uses
scripts/up.sh --check
```

A *different* account there answers `account_mismatch`, which is exactly what that check is for:
reading one account's remaining quota and spending another's is the mistake it exists to prevent.

**Not a fix:** running a workflow. The other path to a valid observation is a session the routing
login itself leaves behind, and that needs a call the router will not admit while the provider has
no observation — so it never happens by itself.

**Still missing, and known:** the observer's login has no path through the panel, while the routing
logins do. It is the one human step of a fresh install that only exists as a command.

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

## The tools are listed but every call fails

**Look:** a run's steps fail with nothing written, and the evidence shows

```
preloop__write_file … → Error: MCP server <some id> not found
```

while `mcp_list.py claude` still prints twenty tools.

**What it means.** That tool server was replaced and has a new id; Preloop resolves a tool to its
server from a cache in its api process, and the cache still holds the old one. Listing keeps
working, calling does not. Applying the policy and rescanning do **not** clear it.

**Do:**

```bash
docker exec cadp278-agent python3 /work/p281/mcp_list.py claude --probe   # PROBE OK / PROBE FAIL
docker restart preloop-oss-api-1                                          # what actually clears it
```

`scripts/up.sh` probes on every bring-up and does this by itself, in that order — apply, scan, and
only if a call still fails, restart Preloop's api (OPERATIONS §28).

## The runtime sees only Preloop's own tools

**Look:** `up.sh --check` → `fsmcp tools exposed via Preloop` fails, and:

```bash
docker exec cadp278-agent python3 /work/p281/mcp_list.py claude
# → only ask_user, get_approval_status, permission_prompt, request_approval …
```

**What it means.** Preloop does not expose a tool server's tools until it has **scanned** it. A scan
that ran before that server was listening registers the server with nothing on it, and `cfg.py
apply` then records the policy as applied — so no later bring-up puts it right. Seen on a fresh
install on another machine, where the account had the policy and the runtime had four tools.

Note what this is *not*: it is not about principals. `mcp_list.py claude` uses the **runtime's own**
MCP credential from `~/.claude.json`; there is no principal called `claude` on any of these
instances, and the check passes on the ones where the scan landed.

**Do:**

```bash
docker exec cadp278-admin /opt/venv/bin/python /work/p281/cfg.py rescan
# {"ok": true, "policy": "policy/b-fsmcp.yaml", "scanned": ["…-toolsvc", "…-fsmcp"]}
```

`scripts/up.sh` now does this by itself: when the runtime cannot see the tools it **applies the
policy again and then scans**, in that order, because a rescan cannot create a server that the
account does not have. If you are doing it by hand and `rescan` says `not_registered`, that is the
case — apply first:

```bash
docker exec cadp278-admin /opt/venv/bin/python /work/p281/cfg.py apply    # --force ignores our record
docker exec cadp278-admin /opt/venv/bin/python /work/p281/cfg.py rescan
```

`apply` no longer trusts its own record: it skips only when the account still has every server the
policy declares. On another machine the record said the work was done while the account had none.

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
