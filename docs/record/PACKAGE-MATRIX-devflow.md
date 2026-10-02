## Capability × package column — `devflow` (/home/user/agent-stack-devflow @ 91300e8)

| ID | devflow | evidence |
|---|---|---|
| C1 Admission | USES(stack/steps/route.py, admit_models.py) | devflow.yaml:108,228 route.py; :132 admit_models.py for named-model rounds; HOLD routed to adjudicate as "no model review this run", not a refusal (manifest.yaml:24-27 deliberately omits `admission` from requires) |
| C2 Role binding | OWN(devflow.yaml, steps/review_plan.py) | roles.py never called; principal picked by Jinja (devflow.yaml:155, literal names at :276,:294,:325); review_plan.py:186-188 builds provider/login/route itself and assumes login name == provider name |
| C3 Execution | USES(stack/steps/broker_dispatch.py, tasks.py→task_chain.py) | 3 direct broker_dispatch.py steps (devflow.yaml:273,291,322); reviews via tasks.py --plan (:170). Package had to choose the "door" itself: devflow.yaml:27-31 says agent_task.py named directly runs outside the role's profile |
| C4 Tool rights | USES(principals.yaml; mcp_principal via argv) | 4 principals with write_file/edit_file rules + egress_profile; principal passed as 8th argv (devflow.yaml:276) and in plan members (review_plan.py:188) |
| C5 Concurrency | USES(stack/steps/tasks.py) | plan with per-member `retries`/`retry_when` (review_plan.py:191-192); receipt context = frame id; adjudicate.py:292-310 verifies receipt context, `produced`, sha256 |
| C6 Recording | BOTH — partial | devflow.yaml:400-401 passes only `receipts` (review fan-out), `check`, `evidence_file`, `measurements`; no `executions` for prepare/implement/research agents → a pass that only implements is recorded NO_EXECUTION |
| C7 Operation | N-A | no reference to cycle.sh/soak.sh/cleanup; drive.py is its own "cycle" (X5) |
| C8 Composition | USES(manifest requires.capabilities) | `[tool_rights, egress]`; `requires.principals` (manifest.yaml:28) is read by nothing in stack/packages.py |
| P1 Workspace addressing | OWN(lib/stackenv.py) — kept | stackenv.load() wraps `import settings` fail-closed; `RUN = os.environ.get("CONDUCTOR_SELF_RUN_ID","manual")` in 10/10 steps |
| P2 Last-line JSON | OWN(every step) — kept | hand-rolled in 10/10; private `emit()` in 3 steps; crash→JSON tail in 9/10 (not proceed.py) |
| P3 REPEATABLE / guards | OWN — kept, remote-only | 11/11 declare; guards ask the remote only (publish.py:219-242; integrate.py:388-417, :444; deliver.py:195-199); no workspace marker anywhere |
| P4 Evidence `items` | OWN(steps/publish.py:257-268) — kept | passed as `evidence_file` (devflow.yaml:401) |
| P5 Refuse-not-degrade | OWN(lib/stackenv.py, ghauth.py, dfcore.py) — kept | AuthError hint names 연결/package.env; RemoteError → TOOL_FAILURE never a verdict |
| P6 Hand-in by name / fixtures | USES(/work/handoff) + OWN(fixtures/) | evaluate.py:32-64 `DEVFLOW_HANDOFF` + SAFE name regex |
| P7 Own credentials | USES(manifest login:, requires.env, requires.egress) + OWN(lib/ghauth.py) | github_login.py device flow writes token.json 0600; egress hosts declared, opened by operator (allow.local) |
| P8 Principals in package | USES(principals.yaml) | 4 principals, applied by scripts/up.sh |
| X1 Step boilerplate | OWN(steps/*) | same 6-line header in 8/10; stack offers no step helper |
| X2 Tree snapshot/diff/hash | OWN(lib/wstree.py, deliver.py:57-68, refs.py:187-206) | sha1 tree_map + diff A/M/D; commit-tree cache `<ws_root>/.devflow-cache/<repo>/<sha>`; stack has no tree-hash helper |
| X3 External-effect guard mechanics | OWN(lib/remote.py, deliver/integrate/publish) | GET-only 3-attempt transient retry; error taxonomy Transient/Unavailable/Conflict; lost-answer discovery; FixtureRemote `lose_response`/`down`; `op_key` written (integrate.py:167) but never read back |
| X4 Token lifecycle | OWN(lib/ghauth.py) | refresh 600 s early, flock-serialised, atomic write; beyond the stack's login flow which only runs argv and watches `done_when` |
| X5 Sub-run orchestration | OWN(steps/drive.py) — stack MISSING | shells `/work/stack/run_workflow.py start/show`; child ids `<parent[:24]>-p<n>`; ignores stack's `--suite/--case` grouping; summary to `$TMPDIR` |
| X6 Controls harness | OWN(controls.py `step()`, Sim) | runs steps as subprocesses with CONDUCTOR_SELF_RUN_ID; own fixture builder; nothing in stack runs packages/*/controls.py |
| X7 Prompt templating / freezing | OWN(evaluate.py write_materials/write_prompt, work.py fill, prompts/*.md) | `{PLACEHOLDER}` str.replace (29 placeholders); frozen materials with `not_shown` size limit; frame/basis digests (dfcore.frame_of); package self-digest `workflow_identity()` — stack's packages.lock knows the commit but offers no API |
| X8 Waiting on external time/state | OWN(drive.py settle) | polls GitHub check_runs until the set is stable; stack has no wait/poll primitive |
| X9 Cross-run package state | OWN(GitHub state comment; dfcore render_state/read_state) | machine copy in an HTML comment; per-run `devflow/state.json`; off-run `.devflow-cache` and token.json; stack records are write-only — MISSING on stack side |
| X10a Last-line-JSON subprocess protocol | OWN(dfcore.run_hook, controls.step, deliver.regenerate) | three private re-implementations of "run argv, read last stdout line as JSON" |
| X10b Platform-layout knowledge | OWN(lib/refs.py:271-310) | reads `docker/egress/profiles/<p>.allow` and principals.yaml directly to tell the model its hosts |
| X10c Fixture remote w/ fault injection | OWN(lib/remote.py FixtureRemote, 296 lines) | generic JSON test double for any remote |

### (a) Stack scripts by absolute path; version requirement
devflow.yaml names stack scripts in **8 agent entries → 5 distinct files**: route.py, admit_models.py, tasks.py, broker_dispatch.py (×3), record.py. drive.py → `/work/stack/run_workflow.py`; controls.py:1351 → admit_models.py. **No stack-version requirement anywhere**: the only version floors are prose in RUNBOOK.md:135-136 (`stack ≥ 24ab1fb`, `stack ≥ 2985815`).

### (b) Boilerplate duplication across the 10 steps
P1 header near-verbatim in **8/10**; RUN-id read and stackenv.load in 10/10. P2 `print(json.dumps(...))` 10/10; the crash-to-JSON tail verbatim in **9/10**; three steps define a private `emit()`.

### (c) Non-devflow-specific lib content
~900 of ~1,840 lib lines: `remote.py` GitHubRemote (311 lines) and FixtureRemote (296); `ghauth.py` (123) + `steps/github_login.py` (103); `stackenv.py` (25); `wstree.py` (26); `refs.cached_tree/copy_tree/as_text` (~45); `dfcore.run_hook` + `sha256/canon` (~35); `drive.settle/one_pass` (~45). A second package talking to GitHub would copy remote.py, ghauth.py and github_login.py wholesale.

### Findings
- **Implementer/researcher model calls never reach the record**: only review `receipts` are recorded; a pass that prepares+implements records NO_EXECUTION with 0 children.
- **The execution door leaks into the workflow**: three steps name `broker_dispatch.py` directly because a direct `agent_task.py` step runs outside the role's profile (devflow.yaml:27-31) — a role fact the package must know and encode.
- **Role binding re-implemented**: roles.py unused; principal chosen by Jinja and review_plan.py guesses `login = provider name`.
- **~half of lib is generic HTTP/GitHub/auth/tree code**; the stack provides no HTTP-remote, token-refresh, tree-hash, or fixture-fault capability.
- **Sub-run orchestration is a shell-out**: drive.py does not use `--suite/--case`, so one devflow-auto's passes are unlinked in the record; its summary lands in `$TMPDIR`.
- **Package-owned state outside any run**: `.devflow-cache` has no cleanup owner; durable task state lives on GitHub because the stack has no cross-run package state.
- **Push guard cannot recognise its own lost-answer effect**: deliver.py:195-199 treats a moved branch as "someone else moved it"; `op_key` written but never read back.
- **No version contract between the two repos**: 5 stack scripts + run_workflow.py bound by absolute path, two commit floors only in RUNBOOK prose.
