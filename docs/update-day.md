# Update day

Once a month, by a person, in about half a day. The stack is nine external things held together
(README), and each of them moves on its own schedule: the provider CLIs change what a measured
posture relies on, Preloop's installer changes what a cold start gets, the images this pulls
change underneath a commit that did not. Nothing here updates itself, by design (runbook, "The
job"): the stack must not rewrite what it is judged by, and an update is exactly that.

Three layers, and only the first is automatic:

| layer | cadence | what it does | who decides |
|---|---|---|---|
| **report** | weekly, automatic | `scripts/drift.sh` says what is pinned and what each registry has now; `cold-start-linux` runs the same cold start a second machine runs (`.github/workflows/`) | nobody — it changes nothing |
| **update day** | monthly, a person | this page | the operator |
| **fix** | when something is wrong | the runbook | the operator |

## Before

```bash
scripts/up.sh --check                       # the stack is healthy before it is changed
scripts/backup.sh                           # the Preloop database, logins, MLflow — not part of a release
scripts/release.sh record --tag pre-$(date +%Y%m)   # what runs now, kept: images, toolchain, configuration
scripts/drift.sh                            # what moved since last time
```

A `newer` line is a question, not an instruction. Three kinds of answer:

- **a provider CLI** (claude-code, codex, grok, the two acp adapters, acpx) — the read-only posture
  of a reviewer rests on how that CLI reads its settings (`run-agent.mjs`, `disableNative()`), and
  a new version is unmeasured until a run shows the native tools are still off. Update one at a
  time, and run the N7 check after each.
- **an image or a server** (mlflow, server-filesystem, supergateway, docker-cli) — a new
  `server-filesystem` means re-reading its tool list into `policy/b-fsmcp.yaml`, which names every
  tool and denies the rest.
- **Preloop** (preloop-oss, preloop-cli) — a new version is a new subject: the guard checks in
  `scripts/up.sh --check` and the controls that measure Preloop's behaviour were written against
  0.15.0. OPERATIONS §8 says a schema migration is not covered by rollback; read Preloop's notes
  before, not after.

## The update, on a branch

1. Change the pins in the files `drift.sh` names, one component per commit, with the measurement
   that justifies it in the commit message.
2. Push the branch. `cold-start-linux` builds the stack on a host that has none of it; the job's
   own rule is that only the provider logins may fail. Wait for it.
3. On the instance:

```bash
scripts/release.sh update --to <rev>        # records what runs now, moves the workspace, rebuilds, checks
scripts/verify.sh --level full              # the checks, the three control suites, package locks,
                                            # controls and floors, then hello-lane, auto and novel-a
```

4. `verify.sh --level full` makes the cheap runs (`hello-lane`, `auto`, `novel-a`). For a provider
   CLI change, add the N7 native-tool check on the vendor that changed (OPERATIONS §7) by hand:
   what you are looking for is the thing a control cannot see — a CLI that now writes through its
   own tool instead of Preloop's, a session file that moved, a login that stopped refreshing.
5. Merge when the controls and the runs are clean. Record the measurements in OPERATIONS.md under a
   new section, as every other change here is recorded: what was updated, from what to what, and
   what was run to say it still holds.

## If it does not hold

```bash
scripts/release.sh list
scripts/release.sh rollback --to pre-<yyyymm>   # workspace revision, images, toolchain, configuration
scripts/up.sh --check
```

Data survives both directions. What rollback does not undo is a Preloop schema migration; that is
what the backup from "Before" is for (`scripts/restore.sh` brings it up beside the live instance,
never over it).

## What is deliberately not here

- **No automatic update.** The stack reports drift; a person decides. A workflow could run the
  report and the controls, and devflow could carry the branch through review, but choosing to
  update and running `release.sh` stay with the operator — the governed party must not change
  what governs it (OPERATIONS §20–§21, issue #7).
- **No "latest".** Every component is pinned, and `drift.sh` reads the pins from the files that
  hold them so it cannot disagree with the build.
- **No shorter cadence.** The weekly report is cheap and changes nothing; a monthly update is as
  often as the measurements can be repeated with care. Something that breaks between update days
  is a fix, and the runbook's business.
