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
| State persistence | state recovered after a restart | **partial** — the run's workspace and every artifact survive, and `resume` exists; but Conductor writes a checkpoint only when a run *fails* (measured: 2 of 51 runs have one), so a run that was stopped is started again, not resumed | state shown; `resume` is a command |
| Artifact persistence | reference and version kept | yes — artifacts live in the run's workspace, and the things that must not drift carry a hash: the frozen draft (`draft_meta.json`), the cycle's packet (`packet_sha256`), each fan-out member's output (receipt `sha256`) | partly (run detail, report) |
| **Tool enforcement** | allow/deny **per step** | **covered.** A role names the principal it runs as (`story=codex:novel-reviewer`), the name reaches the call, and Preloop enforces that principal's rights — including on the argument: the novel workflow's reviewers may write `review_*` and are denied the draft ("Access denied: Scoped rule 2"), measured both directly and in a run where five calls carried two principals across three vendors | the account policy's state is shown; `p281/principals.py list` / `check` answer per principal |
| Secrets | kept out of the model's context | yes — credentials live in volumes (`/route`, Preloop's own), never in a prompt or an argument, and the adapter neither stores nor logs a token (`mcp_principal` takes it from the environment and records only the name) | — |
| Isolation | sandbox / container / worktree | yes — one container per concern, the agent single-homed on an internal network, egress through an allowlist proxy. **Per-run directories are not access isolation** (the file server serves all of `/ws`), and that is recorded rather than implied | capabilities line |
| Timeout | runaway execution stopped | yes — per step in the workflow, per call in the adapter (`timeout_ms`) | — |
| **Cancellation** | a run can be stopped | **yes, as of this review** — `run_workflow.py stop`, `POST /api/runs/<id>/stop`, and a **중지** button on a running row. Conductor does the stopping (graceful cancel → signal → force) | **yes** |
| Retry | runtime failure re-executed | **partial** — one bounded retry for a provider's own "login is refreshing" (reported as `attempts`), and a fan-out member that fails is isolated. There is no general retry policy, and a chained member stops at its first failed step by design | attempts and failures shown |
| Idempotency | side effects not repeated | **not addressed.** One cycle at a time is enforced by a lock, and run ids are unique, but a repeated run repeats its writes; nothing marks a step as safe to re-execute | — |
| Approval | a human gate before risky work | yes — Preloop's approval channel, with the **decision in the panel** | yes |
| Audit | tool / model / execution trace | yes — the adapter's evidence per call, Preloop's own records, MLflow runs, and Conductor's OTel spans in MLflow | linked |

## §13–15 The separations the guide insists on

| what | here |
|---|---|
| Runtime outcome ≠ semantic outcome | kept apart everywhere: a call's `status` (COMPLETED/FAILED) and the workflow's judgement (`gate.decision` PASS / REPAIR / BLOCK / CYCLE / HOLD) are separate fields in the record, and the graph routes on the judgement |
| Runtime retry ≠ workflow loop | kept apart: `attempts` counts a retried *execution*; the novel workflow's repair loop is a semantic transition with a bound (`max_repairs`) and a deterministic triage that owns the edge |
| Runtime evidence ≠ semantic evidence | partly: runtime evidence is complete (per-call events, permissions, result). Semantic evidence is recorded as the decision, its reason and the artifact's hash — but there is **no index from an acceptance criterion to the runtime evidence that supports it** (the guide's `criterion → execution_id/tool_call_id`) |
| Workflow semantics stay out of the platform | held: Preloop decides tool rights, never what a result means; `CONTRACT.md` is this stack's own version of the same rule |

## §16–18 Evaluation and the production gate

**Not covered.** There is no evaluation layer: no dataset of happy / edge / failure / adversarial
cases, no outcome, step or trajectory graders, and no grader validation. What exists instead is:

- **controls** (`p281/trial_controls.py`, 162) that pin the *machinery* against synthetic inputs —
  they answer "does the stack do what it says", not "is the workflow's judgement any good";
- **capability trials** (`TRIAL-A`, `TRIAL-B`) — a handful of runs each, which the guide explicitly
  says is not production readiness;
- **a soak** (§11 of OPERATIONS) — stability over repetition, not quality.

So by the guide's own checklist this stack is at *pilot*, not at a production gate, for any
workflow that runs on it.

## What this review changed

0. **Tool rights per step** — the gap the review named first is closed: a role runs as its own
   principal, and a reviewer can no longer rewrite what it judges ([#2](https://github.com/astro3141/agent-stack/issues/2), measured in OPERATIONS §10).
1. **Cancellation was missing and is now here** — including in the panel, because stopping a run
   that is going is the same kind of decision as answering an approval.
2. **A stopped run leaves no checkpoint**, so it is restarted rather than resumed. Measured, and
   written down rather than assumed from the presence of `conductor resume`.

## What it did not change (open, with issues)

| gap | why it matters | issue |
|---|---|---|
| evaluation layer | without outcome/step/trajectory evaluation over a dataset, "it worked" is a handful of runs | [#3](https://github.com/astro3141/agent-stack/issues/3) |
| idempotency of side effects | a re-run repeats its writes; nothing marks a step safe to repeat | [#4](https://github.com/astro3141/agent-stack/issues/4) |
| semantic evidence index | evidence exists but is not linked to the criterion it supports | [#5](https://github.com/astro3141/agent-stack/issues/5) |
