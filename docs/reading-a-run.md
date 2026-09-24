# Reading a run

Everything a run leaves behind, and the command that reads it. Reverse-engineering this map took
another operator half a debugging session, so it is written down here rather than implied by the
paths.

## Start with the two that answer most questions

```bash
docker exec agentstack-agent /opt/venv/bin/python /work/stack/trajectory.py <id>
docker exec agentstack-agent /opt/venv/bin/python /work/stack/run_workflow.py show <id>
```

`trajectory.py` assembles what the run did from every record below — steps, calls by provider and
principal, permission asks split into *decided by a rule* and *asked a person*, retries, loop rounds
against the bound, cost, and four assertions that are true or false. `show` is the same run as the
panel reads it, as JSON.

While it is going:

```bash
run_workflow.py start <id> <workflow> <profile> --detach   # returns the id
run_workflow.py tail <id> --follow                          # the steps as they happen
run_workflow.py stop <id>     # graceful: it keeps a checkpoint
run_workflow.py resume <id>   # re-enters the step that did not finish
```

## Where each thing lands

| what | where | read it with |
|---|---|---|
| the run as the stack sees it (state, inputs, suite, case, capabilities at start) | `evidence/ui-runs/<id>/meta.json` | `run_workflow.py show <id>` |
| every step and its transitions | `evidence/ui-runs/<id>/tmp/conductor/*.events.jsonl` | `run_workflow.py tail <id>` |
| a checkpoint to continue from | `evidence/ui-runs/<id>/tmp/conductor/checkpoints/*.json` | `run_workflow.py resume <id>` |
| the launcher's own output | `evidence/ui-runs/<id>/run.log` | `tail` |
| **what the steps produced** (lane files, drafts, reports) | `/ws/<conductor run id>/` | `show <id>` gives the id as `workspace_prefix` |
| **one model call**: request, result, permission asks and their answers, the vendor's own events | `evidence/p281/<conductor run>-<step>-<provider>/` | `result.json` first; `events.jsonl` when it is not enough |
| what the judgement rested on | `<workspace>/evidence_index.json` | `trajectory.py <id>` summarises it |
| the record, and one child run per call | MLflow, `http://127.0.0.1:5000` | the panel's run detail links it |
| who answered an approval, and with which credential | `evidence/ops/controls.jsonl` | `grep` |
| what the stack could do when the run started | `meta.json` → `capabilities` | `show <id>` |

A record's `status` says what the run did, not whether it was right: `COMPLETED` or `PARTIAL` when
models ran, `NO_EXECUTION` when the run reached its decision without calling one (a check, a lint
gate, a scanner — `gate.decision` is still the decision it reached), and `HOLD` when the router
started nothing and there was nothing to judge.

The **conductor run id** is the short hex in the workspace and evidence paths (`/ws/af95bad4`,
`evidence/p281/af95bad4-E1-grok/`). `show` prints it as `conductor_run`, and the panel shows it on
the run's row.

## A set of runs

```bash
run_workflow.py start <id> <wf> <profile> --suite <name> --case <case>
suite.py run <suite> <workflow> <profile> <cases.jsonl> [--concurrency N]
suite.py read <suite>
```

`suite.py read` gives each run's trajectory and then the set's execution facts: how many reached a
terminal step, how many were recorded, the loops against their bounds, the cost, how often a rule
decided a permission request and how often a person was asked. How the runs *ended* is tallied and
labelled as the workflow's own word — not a grade. Whether a judgement was right needs a grader, and
that is the workflow's, not this stack's.

## When a step failed

1. `trajectory.py <id>` — which step, how many calls, what was refused.
2. `result.json` in that step's evidence directory — `status`, and **`failure`**, the reason the
   step gives for its own failure.
3. `events.jsonl` in the same directory — the vendor's own events, including every tool call and
   what Preloop answered.
4. The workflow's own report, if it writes one (`port_report.json`, `evidence_index.json`) in the
   workspace.

A run that held before it started is a routing decision, not a failure: `show <id>` carries
`route`, and the reason names the provider and why — see the runbook's *Runs hold* entry.
