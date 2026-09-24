# Against the workflow design procedure — what this stack covers, and what it does not

The method this work is measured against is *AI Workflow Design Procedure — Preloop 유무 비교*
(v0.3, Notion). Its point: a workflow is not a prompt, it is
**brief → process research → graph → state/artifacts → step contracts → execution layer →
evaluation**, and with Preloop the execution layer thins into an *Execution Binding* rather than
disappearing.

This file answers two questions for each thing the guide requires: **is it covered here**, and
**is it in the panel**. Nothing below is claimed from reading the code — each line is either
something this stack has been measured doing, or is marked as not covered.

## §12.1 Runtime concerns

| concern | the guide's minimum | here | in the panel |
|---|---|---|---|
| Run identity | workflow run / step execution ID | yes — a UI run id, Conductor's own run id, a per-call `run_id` (`<run>-<label>-<provider>`), and an MLflow run per call under a parent per run | yes: run history, run detail, MLflow link |
| State persistence | state recovered after a restart | **covered for a stopped run.** Runs carry a loopback-only dashboard, which is the rung `conductor stop` starts from, so a stop now writes a checkpoint and `resume` re-enters the step that was interrupted — measured: a stopped `novel-a` finished PASS in 4 model calls where a full run makes 5 (OPERATIONS §23). A run whose *container* died mid-step still has only what the last checkpoint holds | state shown, and **재개** beside **중지** |
| Artifact persistence | reference and version kept | yes — artifacts live in the run's workspace, and the things that must not drift carry a hash: the frozen draft (`draft_meta.json`), the cycle's packet (`packet_sha256`), each fan-out member's output (receipt `sha256`) | partly (run detail, report) |
| **Tool enforcement** | allow/deny **per step** | **covered.** A role names the principal it runs as (`story=codex:novel-reviewer`), the name reaches the call, and Preloop enforces that principal's rights — including on the argument: the novel workflow's reviewers may write `review_*` and are denied the draft ("Access denied: Scoped rule 2"), measured both directly and in a run where five calls carried two principals across three vendors — and the party being judged cannot rewrite them (§21) | the account policy's state is shown; `p281/principals.py list` / `check` answer per principal |
| Secrets | kept out of the model's context | yes — credentials live in volumes (`/route`, Preloop's own), never in a prompt or an argument, and the adapter neither stores nor logs a token (`mcp_principal` takes it from the environment and records only the name) | — |
| Isolation | sandbox / container / worktree | yes — one container per concern, the agent single-homed on an internal network, egress through an allowlist proxy. **Per-run directories are not access isolation** (the file server serves all of `/ws`), and that is recorded rather than implied | capabilities line |
| Timeout | runaway execution stopped | yes — per step in the workflow, per call in the adapter (`timeout_ms`) | — |
| **Cancellation** | a run can be stopped | **yes, as of this review** — `run_workflow.py stop`, `POST /api/runs/<id>/stop`, and a **중지** button on a running row. Conductor does the stopping (graceful cancel → signal → force) | **yes** |
| Retry | runtime failure re-executed | **partial** — one bounded retry for a provider's own "login is refreshing" (reported as `attempts`), and a fan-out member that fails is isolated. There is no general retry policy, and a chained member stops at its first failed step by design | attempts and failures shown |
| Idempotency | side effects not repeated | **covered where it changes a decision.** Every step declares what a repeat does (`REPEATABLE`), and the three that were wrong about it are guarded: freezing the same draft is one round, a repeated triage spends no repair round, and one run and judgement write one record (`idempotency_key`). Artifact writes are still plain writes, in the run's own workspace (OPERATIONS §17) | — |
| Approval | a human gate before risky work | yes — Preloop's approval channel, with the **decision in the panel**, and the runtime **refused** it: the governed network reaches Preloop only through a guard that refuses writes to the control plane by default (deciding an approval, standing bypasses, tool rights, credentials, the account's policy) and passes every read. A route restriction, not a rights one — this build of Preloop cannot express the latter (OPERATIONS §13, §20, §21) | yes |
| Audit | tool / model / execution trace | yes — the adapter's evidence per call, Preloop's own records, MLflow runs, and Conductor's OTel spans in MLflow | linked |

## §13–15 The separations the guide insists on

| what | here |
|---|---|
| Runtime outcome ≠ semantic outcome | kept apart everywhere: a call's `status` (COMPLETED/FAILED) and the workflow's judgement (`gate.decision` PASS / REPAIR / BLOCK / CYCLE / HOLD) are separate fields in the record, and the graph routes on the judgement |
| Runtime retry ≠ workflow loop | kept apart: `attempts` counts a retried *execution*; the novel workflow's repair loop is a semantic transition with a bound (`max_repairs`) and a deterministic triage that owns the edge |
| Runtime evidence ≠ semantic evidence | **joined.** The judging step writes `evidence_index.json`: each claim with its kind and severity, the criterion it answers, the call that produced it (`execution_id`, evidence directory, principal), the review or proposal it came from with that file's sha256, and the artifact it is about with its hash. The recorder stores the index on the MLflow run and tags the count, so a record is readable without its workspace (OPERATIONS §18). What is still missing is a criterion *catalogue* — the criterion is the reviewer and the kind of finding, not an entry in an acceptance-criteria document, because the workflows here do not have one yet |
| Workflow semantics stay out of the platform | held: Preloop decides tool rights, never what a result means; `CONTRACT.md` is this stack's own version of the same rule |

## §16–18 Evaluation and the production gate

**The execution half is covered; the meaning half is not ours.** Whether a verdict was right or a
lane was a good strategy is what the work means, and meaning belongs to the workflow — it needs
labelled cases from whoever knows the domain. What the platform can answer without knowing the
domain, it now does: `p281/trajectory.py` assembles what a run did from the records that already
existed, with four assertions that are true or false (the loop stayed inside its bound, every call
carried its principal, the run reached a terminal step, the run was recorded), and
`p281/suite.py` turns a file of cases into one run per case and reads the set back as execution
fact — how many reached a terminal step, what they cost, how often a person was asked, how the runs
ended (the workflow's word, not a grade). The `case` each run carries is what a grader joins on
(OPERATIONS §19, §24).

Still not covered, and not ours to cover: the **content** of a dataset and its labels, outcome and
step graders, grader validation. What exists beside the trajectory is:

- **controls** (`p281/trial_controls.py`, 162) that pin the *machinery* against synthetic inputs —
  they answer "does the stack do what it says", not "is the workflow's judgement any good";
- **capability trials** (`TRIAL-A`, `TRIAL-B`) — a handful of runs each, which the guide explicitly
  says is not production readiness;
- **a soak** (§11 of OPERATIONS) — stability over repetition, not quality.

So by the guide's own checklist this stack is at *pilot*, not at a production gate, for any
workflow that runs on it — and closing that gap is the workflow owner's work, on the ground this
stack now provides.

## What this review changed

0. **The stack claims its own Preloop** — a fresh instance is registered, the runtime's credential
   issued and this stack's policy applied by `scripts/up.sh`, with the one call that would silently
   create a second tenant guarded by a row count
   ([#6](https://github.com/astro3141/agent-stack/issues/6), OPERATIONS §22).
0. **The runtime cannot change what it is judged by** — not its own approval, not its tool rights,
   not the account's policy, not a credential. The boundary is drawn on the network the agent lives
   on and checked from that position on every bring-up
   ([#1](https://github.com/astro3141/agent-stack/issues/1),
   [#7](https://github.com/astro3141/agent-stack/issues/7), OPERATIONS §20–21).
0. **The trajectory of a run**, assembled and assertable — the part of evaluation that needs no
   domain knowledge ([#3](https://github.com/astro3141/agent-stack/issues/3), OPERATIONS §19).
0. **Evidence joined to its claim** — a judgement now names the call that made it and the artifact
   it was about, and the index travels with the record
   ([#5](https://github.com/astro3141/agent-stack/issues/5), OPERATIONS §18).
0. **Idempotency where it matters** — three steps changed a judgement when repeated (a round, a
   repair bound, a record); all three are guarded and every step now declares what a repeat does
   ([#4](https://github.com/astro3141/agent-stack/issues/4), OPERATIONS §17).
0. **Tool rights per step** — the gap the review named first is closed: a role runs as its own
   principal, and a reviewer can no longer rewrite what it judges ([#2](https://github.com/astro3141/agent-stack/issues/2), measured in OPERATIONS §10).
1. **Cancellation was missing and is now here** — including in the panel, because stopping a run
   that is going is the same kind of decision as answering an approval.
2. **A stopped run now leaves a checkpoint and can be continued** — the missing piece was the
   graceful-cancel rung of `conductor stop`, which needs a dashboard to exist at all (OPERATIONS
   §23). Along the way: a resumed run used to read as the failure it was stopped at, and nothing
   in this tree built its own images, so panel changes silently did not run.

## What it did not change (open, with issues)

| gap | why it matters | issue |
|---|---|---|
| graders and datasets | the trajectory of a run is now recorded (§16–18), but whether a judgement was *right* still needs labelled cases from whoever knows the domain — the workflow's work, not the platform's | — |
