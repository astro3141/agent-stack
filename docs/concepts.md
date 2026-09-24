# How this stack is put together

Five things run here. Four of them were written by other people, and the work is what holds them
together under real constraints.

| | what it decides | ours? |
|---|---|---|
| **Preloop OSS** | what an agent may do: tool rights per principal, approvals | no |
| **Conductor** | the order of steps, and the state between them | no |
| **MLflow** | where a run's facts are kept and compared | no |
| **acpx** | the protocol the vendors' CLIs speak | no |
| **the routing layer** | which provider runs a call, with which credential, under which quota | **yes** |

## The one rule

**The platform provides capabilities; it does not decide behaviour** ([CONTRACT.md](../CONTRACT.md)).

A capability says *this is possible, with these guarantees*. Behaviour says *do this, now, and here
is what it means*. Two questions settle most arguments:

- Would a different domain — a novel, a trading cycle, a code review — need this **with the same
  meaning**? Then it is a capability, and it belongs to the platform.
- Does it encode *what a good result is*, or *what to do when a result is not good*? Then it is
  behaviour, and it belongs to the workflow, even when every workflow happens to want the same
  thing.

That line is why, for example, this stack records **what a run did** and refuses to compute whether
the run was *right*: the first needs no domain knowledge, the second is the whole of it.

## A run, end to end

```
run_workflow.py start <id> <workflow> <profile>
   │
   ├─ capabilities probed        a run is refused if the stack cannot do what it needs
   ├─ route        the router reads quota observations and says ROUTE or HOLD
   ├─ roles        each role is bound to a provider and a principal
   ├─ …steps…      model calls through the routing layer; tools through Preloop's MCP
   ├─ record       one MLflow run for the workflow, one child per call
   └─ done_*       a terminal step; its name is the run's outcome
```

Every model call leaves an evidence directory (`evidence/p281/<run>-<label>-<provider>/`) holding
the request, the result, the permission requests and their answers. Nothing in a report is computed
twice from memory: the readers all read those files.

## Identity: principals

Preloop's rights are **per subject** — a credential, or the managed agent behind it — never per
step. A step gets its own rights by running as its own principal, which a workflow names next to
the provider:

```yaml
roles: ["architect=codex:novel-author", "story=codex:novel-reviewer", …]
```

The principals themselves, and what each may do, are declared in
[`config/principals.yaml`](../config/principals.yaml) and applied to Preloop on every bring-up.
That is why a second machine is governed the same way: the reviewer that may write `review_*` and
may not touch the draft is a file, not something someone once did in a console.

## The boundary that is a route, not a right

An approval is the one decision reserved for a person. In Preloop OSS 0.15.0 every credential of an
account carries `decide_approvals`, and this build has no way to make one that does not (no member
management: `/users`, `/invitations`, `/teams` all answer 404).

So the boundary is drawn where this stack does have authority — the network. The agent is
single-homed on `governed`, and the names it resolves for Preloop belong to a guard
([`docker/apiguard.conf`](../docker/apiguard.conf)) that **refuses writes to the control plane by
default**:

| from the governed network | |
|---|---|
| any read | allowed |
| `POST …/agents/permission-check`, `POST /mcp/v1…` | allowed — the permission hook and MCP itself |
| deciding an approval, standing bypasses, tool rights, credentials, policy | refused, each with its own reason |

It is a route restriction, not a rights restriction, and OPERATIONS §20–21 says so in those words.

## What the panel is for, and what it is not

**Human decisions go on a screen; everything else is a command or a file.** The panel
(`http://127.0.0.1:8780`) has provider login, approval decisions, stopping and resuming a run, and
the state a person needs to make those calls. It has no button for anything an operator could type,
because a button for that is a second place for the truth to live.

## Records, and what an evaluation stands on

- **A run's record**: an MLflow run per workflow run, a child per model call, the evidence index of
  the judgement, and the artifacts' hashes.
- **A run's trajectory** (`p281/trajectory.py`): what a run did, assembled from records that
  already exist — steps, calls by provider and principal, permission asks split into *decided by a
  rule* and *asked a person*, retries, loop rounds against the bound, cost, and four assertions
  that are true or false.
- **A set of runs** (`p281/suite.py`): one run per case from a `cases.jsonl`, read back as
  execution fact.

There is no accuracy and no score anywhere in that. Whether a judgement was right needs labelled
cases from whoever knows the domain — the workflow's, not the platform's.

## A workflow is a package

A workflow is not an edit to this stack. It is a directory under `packages/`:

```
packages/<name>/
  manifest.yaml   name, version, entry, what it needs of the stack
  workflow.yaml   the graph; its steps by absolute path under the package root
  steps/ prompts/ fixtures/ cases/
  principals.yaml the identities its steps run as, and what each may do
```

**Installing a package is a decision to trust it.** `scripts/up.sh` applies its `principals.yaml` —
creating the identities it declares and minting their credentials — which is what makes a workflow
governed the same way on every machine. Read a package before installing it, as you would a
dependency.

Install one by putting it there and running `scripts/up.sh`: the runner and the panel both learn it
from the loader (`p281/packages.py`), and `principals.py apply` creates the identities it declares
with the rights it declares. Nothing in the platform is edited, which is the point — a workflow
that cannot be given to someone is not a workflow, it is a modification.

**Every** workflow is a package, including the ones this stack was written with: `packages/auto`,
`packages/research-r`, `packages/novel`, `packages/trading` (which carries three, because they
share a deterministic step), and `packages/hello-lane` as the smallest example. `p281/steps/` holds
only what any workflow may call — route, roles, agent_task, tasks, task_chain, fanout, record — and
that list is the platform's surface.

## Compositions

A composition is which parts are running: `full`, `no-record` (no MLflow), `runtime` (no panel).
`scripts/up.sh --composition <name>` prints what each one costs in capabilities, and a run is
**refused** when a capability it needs is missing — not degraded silently.

## Where to read further

| | |
|---|---|
| [CONTRACT.md](../CONTRACT.md) | the boundary, with the tests that settle arguments |
| [OPERATIONS.md](../OPERATIONS.md) | every operational fact, as a measurement — §10 tool rights, §17 repeats, §19 trajectory, §20–21 the guard, §22 claiming Preloop, §23 stop and resume, §25 a second machine |
| [COVERAGE.md](../COVERAGE.md) | this stack against the workflow design procedure: covered, partial, missing |
| [docs/install.md](install.md) | from a clone to a running stack |
| [docs/commands.md](commands.md) | every command, in one table |
| [docs/runbook.md](runbook.md) | what to do when something is wrong |
| [docs/containers.md](containers.md) | which container does what, and what it must not |
| [docs/reading-a-run.md](reading-a-run.md) | where everything a run leaves behind lands |
| [docs/packages.md](packages.md) | writing a workflow package: the contract its steps keep |
