# Execution Plane gap analysis — CADP v0.5 EP TD vs agent-stack

Sources read: `TECHNICAL_DESIGN_cadp_v0_5_execution_plane.md` (EP TD, all), Spec v0.5 §2.3 / §6 / §4.5, TD v0.4 §§17–19 (via EP TD Part A), and agent-stack `README.md`, `CONTRACT.md`, `docs/concepts.md`, `docs/containers.md`, `docs/record/COVERAGE.md`, `docs/record/OPERATIONS.md` (§10, §29, §46, §48, §53–54), `docs/record/FINDINGS-281.md`, `stack/run-agent.mjs`, `router.py`, `collect_obs.py`, `codex_identity.py`, `role_egress.py`, `capabilities.py`, `broker.py`, `profile_runner.py`, `steps/{agent_task,tasks,roles,route,admit_models,record}.py`, `trajectory.py`, `config/environment.yaml`, `config/profiles/*.yaml`, `docker/compose.poc.yaml`, `docker/egress/*`, `docker/agent.Dockerfile`.

## A. Normative requirements of the Execution Plane (EP TD + Spec v0.5 §6, §2.3)

### Part A — re-homed mechanics (TD v0.4 §§17–19, owned here unchanged)

| ID | Requirement (one line) | Anchor |
|---|---|---|
| A1 | Three closed-union keyed registries per surface role (`WORKER_PROVIDERS`/`REVIEW_PROVIDERS`/`PLAN_PROVIDERS`); each profile carries an **argv template** (not a prefix), an **auth descriptor** (never a credential), and `identity_class_product`; resolvers never default; unknown provider fails closed with **no fs/process/docker/network side effect**. | EP TD §A.1 row §17.1; TD v0.4 §17.1 |
| A2 | `identity_class_product` must match the registry's product string for that surface's `producer_ref`; a product-side string never asserts a class. | EP TD §A.1 row §17.1; TD v0.4 §17.1 |
| A3 | Measurement-first capabilities: `model_scan`, `effort_scan`, `verdict_format`, measured read-only argv exist only after a live container probe; unmeasured ⇒ `UNKNOWN` / conservative verdict; never guessed. | EP TD §A.1 row §17.2; TD v0.4 §17.2 |
| A4 | Reviewer/planner read-only posture is the **measured argv** (tools allow-list; plan mode is defence-in-depth only, bypass-permission flags forbidden on read-only surfaces). | TD v0.4 §17.2 "Read-only posture", §17.1 |
| A5 | Auth injection: closed `oauth_env` / `auth_files` union resolved by the broker; **exactly one provider's auth enters a container**, read-only at its provider path; missing HOME/file, unexpected env var, unknown `kind` throw; no fallback to another provider's token; no reuse of worker auth for reviewer/planner or the reverse. | EP TD §A.1 row §17.3; TD v0.4 §17.3 |
| A6 | Entry independence guard `assertReviewIndependence(worker_product, review_provider)` runs before any surface compute; same-product reviewer refused. | EP TD §A.1 row §17.4; TD v0.4 §17.4(1) |
| A7 | Each surface authenticates as its **own** registered principal and submits under its own `producer_ref`; a provider without a token fails closed rather than borrowing another product's identity. | EP TD §A.1 row §17.5; TD v0.4 §17.5 |
| A8 | External-verification producer: repo-owned `.github/workflows/cadp-verify.yml`; broker does one check-runs read **host-side** via operator `gh`; `projectCheckRuns` fail-closed (queued/in-progress/absent/duplicate/malformed ⇒ `UNKNOWN`, never pass/fail); two independent opt-ins; `.github/` is a gate path. | EP TD §A.1 row §18.1/18.2/18.4; TD v0.4 §18 |
| A9 | Session-scan capture for **every** model surface: broker-owned per-run session dir; writable session bind that does **not** widen reach (`/ws` stays `:ro`, auth `:ro`, egress unchanged); session-file-first / stdout-fallback scan over the profile's `model_scan` / `effort_scan`; requested-effort ↔ measured `effort_argv` pairing; surface-role vocabulary `WORKER | REVIEWER | PLANNER`. | EP TD §A.1 row §19.1–19.4; TD v0.4 §19.3, §19.4 |
| A10 | Requested ≠ observed: requested is never consulted to fill observed; unmeasured field ⇒ `UNKNOWN`, never a guessed value; every `PRESENT` observed field carries a locator. | EP TD §A.1 row §19.1–19.4, §A.2(3); TD v0.4 §19.1; Spec v0.5 §4.5 |
| A11 | Execution evidence shape: `BACKEND_EXECUTION` (`cadp.backend.v1`) per surface run, producer `backend-scan:<provider>`, `source_relation SELF_REPORT`, with one `surface-role` subject binding. | EP TD §A.1 row §19.1–19.4, §A.3; TD v0.4 §19.2(a) |
| A12 | Container isolation (checkout-grounded): worker/reviewer on an `--internal` docker network whose **only** hole is the dual-homed allowlist CONNECT proxy to provider hosts; verifier `--network none`; host filesystem invisible except declared mounts; every surface under an **unambiguous container identity**, run through `runBoundedSurface` with a declared bound and confirmed termination. | EP TD §A.1 "Also owned here" |
| A13 | Cross-plane contracts (subject bindings, `produced_at` sourcing, locator enforcement, producer registration) are the Authority Plane's; this plane **supplies** locators and envelopes but enforces nothing. | EP TD §A.2(1)–(4) |

### Part B — new v0.5 contracts

| ID | Requirement (one line) | Anchor |
|---|---|---|
| B1.1 | `ExecutionRequestV1` (`cadp.execution-request.v1`) is constructed **by the broker after preparation and immediately before the surface starts**; common header exactly `{schema, surface_role, provider, executor_profile_digest, repo_id}`. | EP TD §B1(1) |
| B1.2 | `executor_profile_digest = jcsDigest(executor_profile_payload.v1)`: the resolved registry profile **verbatim** under a closed key set, typed `Digest`, descriptors only — **no credential in the preimage**. | EP TD §B1(1); §B1(6a) |
| B1.3 | Role-specific exact inputs: `base_revision` (WORKER/PLANNER) / `candidate_revision` (REVIEWER); `input_digests` in two layers over a closed `input_role` set `{work-item, intent, surface-prompt, workspace-revision}`; `surface-prompt` **required for every role**; each entry digests UTF-8 raw bytes under `{sha256, raw-bytes-1}`. | EP TD §B1(1) |
| B1.4 | Exact closed key sets per role; unknown key / unknown, duplicate or missing `input_role` ⇒ **MALFORMED ⇒ broker refusal: no digest, no attempt identity, no surface, nothing sealed**. | EP TD §B1(1e) |
| B1.5 | `execution_request_digest = jcsDigest(complete ExecutionRequestV1)` under `cadp-jcs-1`; changes whenever surface-visible bytes change. | EP TD §B1(1e) |
| B1.6 | No re-derivation in the caller layer: the revision field must equal the one the sealing composition pinned. | EP TD §B1(1) |
| B2.1 | `ExecutionResultV1` = `{schema, surface_role, provider, output_artifact_subject, output_artifact_digest, output_artifact_locator, observed{model,effort,provider,run_id,version}}`; **all three output fields required on success**; missing ⇒ MALFORMED, no envelope sealed. | EP TD §B1(2) |
| B2.2 | Per-role artifact bytes: WORKER = broker-generated `git bundle`; REVIEWER = captured verdict stdout; PLANNER = captured proposal stdout; digest computed by the **broker as observer over bytes it holds**. | EP TD §B1(2) |
| B2.3 | Output-artifact subject = `{authority_ref:"cadp-store:k04", namespace:"execution-output", object_id:"<execution_request_digest>/<broker-minted attempt identity>"}`; attempt identity = container id minted at surface start. | EP TD §B1(2a) |
| B2.4 | The artifact's own digest is never its name; identity is broker-assigned, never surface-asserted. | EP TD §B1(2b) |
| B2.5 | Retry semantics: two attempts of one logical request are **two distinct artifacts with distinct identities**, append-only; never "latest". | EP TD §B1(2c) |
| B2.6 | `output_artifact_locator` is a broker-side observation locator of the `broker-response#…` shape. | EP TD §B1(2) |
| B3.1 | Envelope binding: exactly one added `SubjectBinding` with `content_digest = output_artifact_digest`, copied **verbatim** by the sealer. | EP TD §B1(3) |
| B3.2 | Every `content_digest` under an approved scheme. | EP TD §B1(3) |
| B3.3 | Same digest rides as `claim.observed.output_artifact = {PRESENT, value, locator}`; `source_relation` stays `SELF_REPORT`. | EP TD §B1(3) |
| B4 | Capture mechanics for WORKER bundle and REVIEWER stdout digests are `[UNMEASURED — probe required]`. | EP TD §B1(4); Spec v0.5 §6 |
| B5 | Probe must measure (a) broker-side digest with no surface input, (b) stable re-digest, (c) observer chain + broker-side locator, (d) comparability to sealed `GIT_PUSH` material. | EP TD §B1(5) |
| B6a | `can_read_workspace` in the REVIEWER closed set; closed sets track the role's profile interface in totality. | EP TD §B1(6a) |
| B6b | Reviewer runs over two planes: `/ws` instruction plane **empty by contract**; `/candidate:ro` evidence plane is a **sanitized snapshot** of `candidate_revision` (tracked regular files only, no `.git`; symlink/gitlink ⇒ fail-closed refusal). | EP TD §B1(6b) |
| B7.1 | Provider-credential custody: exactly one provider's auth in an isolated container, read-only, host keychain and other providers unreachable, egress only to provider hosts; GitHub read credential stays **host-side**. | EP TD §B2(1); Spec v0.5 §6 |
| B7.2 | That status is a **deployment-policy fact** that dissolves on reclassification; a policy that classifies provider invocation (spend caps, data egress, model access) as governed pulls provider credentials inside the PEP boundary. | EP TD §B2(2); Spec v0.5 §2.3, §6 |
| B7.3 | Provider invocation is **not yet classified**; unclassified ⇒ effecting; a machine-readable active-policy classification datum is a named v0.5 prerequisite. | EP TD §B2(3)–(4) |
| B7.4 | Isolation is this plane's container construction and is **never delegated to any orchestrator**; an orchestrator working directory/settings are not a sandbox. | EP TD §B2(5); WP §6 |
| B8.1 | Optionality: removing the plane loses only the `backend-scan:*` producers; `backend_model_present` becomes unsatisfiable ⇒ `pr_create_ok` DENY. | EP TD §B3(1)–(2) |
| B8.2 | Equal citizen: no admission without the composition's evidence; an alternative executor needs a reference-policy delta. | EP TD §B3(3) |
| C1 | Conformance control legs: unified-subject, surface-input-drift, malformed-request, sealer-transport, malformed-result, identity/content placement, scheme, locator, self-report. | EP TD §C(1) |
| C2 | Custody control F2: worker sandbox imports **only** declared auth files; reviewer: session bind is the only extra writable bind, `/ws` `:ro`, host `HOME` never mounted. | EP TD §C(2) |
| C3 | Optionality control: plane removed ⇒ kernel conformance unchanged, `pr_create_ok` DENYs. | EP TD §C(3) |

### Spec v0.5 §2.3 / §6 (direct)

| ID | Requirement | Anchor |
|---|---|---|
| S1 | No standing credential capable of a governed effect may exist in a worker, model, reviewer, verifier, or workflow payload; prompt instructions, role labels, sandbox names, worker self-report are **not** isolation evidence. | Spec v0.5 §2.3 ¶1 |
| S2 | Any credential able to create a governed effect lives inside the enforcing boundary; no credential **kind** exempt. | Spec v0.5 §2.3 ¶2 |
| S3 | The Execution Plane is an **optional product service with a declarative contract**, not part of the authority boundary. | Spec v0.5 §6 ¶1 |
| S4 | The contract is **symmetric and output-bound**: `ExecutionRequest` carries executor profile, provider, exact input digests; `ExecutionResult` carries an exact `output_artifact_digest` bound as a subject. | Spec v0.5 §6 ¶2 |

## B. Gap verdicts against agent-stack

| ID | Verdict | Reason | Evidence |
|---|---|---|---|
| A1 | PARTIAL | `PROVIDERS` is a closed map (`claude`/`codex`/`grok`) and `main()` throws `unknown provider` before any side effect; but there is **one** registry, not three per surface role; no argv template per role, no auth descriptor union, no `identity_class_product`. `config/profiles/*.yaml` are **routing** profiles, not executor profiles. | `stack/run-agent.mjs` `PROVIDERS`, `main()`; `config/profiles/research-default.yaml` |
| A2 | MISSING | No `identity_class` / product string anywhere; provider name is the only identity. | grep `identity_class` → none |
| A3 | PARTIAL | Honest-UNKNOWN discipline is present (`served: "unknown"`), three levels kept apart (requested / session_reported / adapter_reported / served) — but **no measured capability fields exist at all**: no `model_scan`, `effort_scan`, `verdict_format`, no probe-gated registry entries. | `stack/run-agent.mjs`; FINDINGS-281 "Model identity, revisited" |
| A4 | PARTIAL | Read-only posture is by **settings file + Preloop MCP**, not measured argv: Claude native `Write/Edit/Bash` denied via a per-run `cwd/.claude/settings.json`; Codex via `CODEX_CONFIG` feature flags (`apply_patch` admitted to have no off switch); Grok via `/route/grok/config.toml`. No WORKER-vs-REVIEWER argv distinction. | `run-agent.mjs` `disableNative()` |
| A5 | MISSING | **All three providers' logins are mounted into one container** (`route-creds:/route`), plus the Preloop-custodied `~/.codex` / `~/.claude.json` in `agent-home`. Selection is by env var, i.e. convention, and `/route` is read-write. agent-stack's own words: "Provider credentials are not per-role … they live in one container." | `docker/compose.poc.yaml`; `run-agent.mjs` `directEnv()`; OPERATIONS §48, §46 |
| A6 | MISSING | No independence guard; `roles.py` binds `role=provider:principal` as the workflow declares. Independence is a workflow convention, never refused by the platform. | `stack/steps/roles.py` |
| A7 | PARTIAL | Preloop principals per role exist — but that is **tool-rights** identity, not an evidence-producer principal. The permission-hook selection **falls back to another vendor's hook** when none matches, which is the borrowed identity §17.5 forbids. | `run-agent.mjs` `preloopHook()`; `stack/broker.py` |
| A8 | MISSING | No external-verification producer, no check-runs read, no `cadp-verify.yml`. The only GitHub touch is a package login flow that runs `gh auth login` **inside the agent container** — the opposite of §18.2's host-side rule. | `stack/packages.py` `login_of()`; README `legacy/` |
| A9 | MISSING | No session-scan at all; no per-run session dir; no role vocabulary; no effort argv pairing. Codex rollouts are read only for rate limits (quota). | `stack/collect_obs.py` |
| A10 | PARTIAL | Requested vs observed is separated and never copied. But there is **no locator on any observed field**, and `session_reported` is an acpx client status, not a scanned backend fact. | `run-agent.mjs`; `stack/steps/record.py` `execution_tags()` |
| A11 | MISSING | No `BACKEND_EXECUTION` envelope, no K2 envelope. Facts land as MLflow tags and a workflow-written `evidence_index.json`. | `stack/steps/record.py`; OPERATIONS §18 |
| A12 | PARTIAL | Network half largely matches (agent single-homed on `governed` internal network; only route out is tinyproxy CONNECT with `FilterDefaultDeny`). Gaps: (i) allowlist is **not provider-only** (package hosts: KIS on 9443, DART); (ii) **no per-surface container** — one long-lived `agent` container runs every call as a subprocess, no container identity per attempt; (iii) the whole repo tree is bind-mounted rw at `/work`; (iv) lifetime bound is a per-call `timeout_ms`, no confirmed container termination; (v) no verifier surface. | `docker/compose.poc.yaml`; `docker/egress/*`; OPERATIONS §36, §60 |
| A13 | NOT-APPLICABLE | No Authority Plane / Kernel to supply to. | — |
| B1.1 | MISSING | The per-call `request.json` is the caller-to-adapter body; no broker-to-surface object, no schema literal, no `surface_role`, no `repo_id`. | `stack/steps/agent_task.py`; `run-agent.mjs` |
| B1.2 | MISSING | No executor profile object, no digest, no JCS canonicalization anywhere. | grep `canonical|jcs|digest` → none |
| B1.3 | MISSING | No `base_revision` / `candidate_revision` (no git materialization — workspace is a shared writable `/ws/<run>`); the final prompt is written to evidence but **never digested**. | `agent_task.py`; `environment.yaml` |
| B1.4 | MISSING | No request schema, so no malformed-request refusal. `profile_runner.py` validates field shapes (input hygiene), not a closed-key-set contract. | `stack/profile_runner.py` |
| B1.5 | MISSING | No request digest exists. | — |
| B1.6 | NOT-APPLICABLE | No sealing composition. | — |
| B2.1 | MISSING | `result.json` has no `output_artifact_subject/digest/locator`; a success result with no artifact is returned normally (`produced: false` reported, not refused). | `run-agent.mjs` `out`; `agent_task.py` |
| B2.2 | PARTIAL | A sha256 **is** computed over the expected artifact — but by `tasks.py` after the call, over a file in the **shared, writable, non-access-isolated `/ws`**, not by the adapter over bytes it holds. | `stack/steps/tasks.py` `sha_file`; COVERAGE "Per-run directories are not access isolation" |
| B2.3 | MISSING | `run_id = f"{run}-{label}-{provider}"` — deterministic, caller-composed, reused across attempts; no broker-minted per-attempt identity. | `agent_task.py` |
| B2.4 | MISSING | No subject/identity construction. | — |
| B2.5 | MISSING (contrary) | Retries are explicitly "run again — in the **same** workspace, under the **same** name"; a second attempt **overwrites** the first's artifact and identity. | `agent_task.py`; `tasks.py` retry loop; CONTRACT.md |
| B2.6 | MISSING | No locator concept; `evidence_dir` is a directory path. | `run-agent.mjs` |
| B3.1 | MISSING | No `SubjectBinding`, no envelope. | `record.py` |
| B3.2 | MISSING | Hashes are bare hex with implied sha256; no scheme discipline. | `tasks.py` |
| B3.3 | MISSING | No `observed.output_artifact`; no `source_relation`. | — |
| B4 | NOT-APPLICABLE | No capture mechanism to measure. (agent-stack's "nothing claimed from reading the code" matches the EP probe rule in spirit.) | COVERAGE.md preamble |
| B5 | MISSING | None of (a)–(d) measured; (c) is inverted — the only artifact digest is taken off a workspace the model and other roles can write. | OPERATIONS §10 |
| B6a | NOT-APPLICABLE | No profile closed set. | — |
| B6b | MISSING | No reviewer evidence plane; a reviewer-shaped role reads the same shared rw `/ws/<run>` the author wrote; nothing `:ro`; `disableNative()` writes `.claude/settings.json` into the cwd — the instruction-plane file the TD says a provider CLI auto-discovers. | `agent_task.py`; `run-agent.mjs`; compose `fsmcp` |
| B7.1 | MISSING | Three providers' credentials in one container (A5); egress not provider-only (A12); GitHub credential minted **inside** the agent (A8). The provider-host reach bound itself (tinyproxy allowlist) is measured and holds — that half is COVERED. | OPERATIONS §48, §53 |
| B7.2 | PARTIAL | agent-stack **does** classify provider invocation as governed — by quota/spend (router HOLD) — which under B2(2) is exactly the case that pulls provider credentials inside the enforcing boundary; yet those credentials sit in the execution container and (via `/proc/<pid>/environ`, same uid) are readable by any co-resident step. | `stack/router.py`; OPERATIONS §46 |
| B7.3 | OUT-OF-SCOPE-EXTRA / PARTIAL | agent-stack has a machine-readable admission datum for provider invocation (profile `quota.*`; router verdict with reason) — more than the reference deployment. It is spend admission, not a `NON_EFFECTING` classification. | `config/profiles/*.yaml`; `router.py` |
| B7.4 | PARTIAL | The enforced boundary is agent-stack's own network/container construction, not Conductor's working dir. But native-tool removal relies on the CLI's **settings tier** (`cwd/.claude/settings.json`) — the working-directory-as-trust-boundary that WP §6 / B2(5) says establishes nothing. | `docs/concepts.md`; `run-agent.mjs`; `docker/apiguard.conf` |
| B8.1 | NOT-APPLICABLE | No Kernel. Analogue: `capabilities.py` refuses a run that lacks a required capability. | `stack/capabilities.py` |
| B8.2 | NOT-APPLICABLE | No admission gate over execution evidence; `trajectory.py`'s four assertions do not include model identity or artifact binding. | `stack/trajectory.py` |
| C1 | MISSING | No control asserts request/result shape, subject identity, drift, malformed refusal, placement, scheme, locator, or self-report refusal. | `stack/*_controls.py` |
| C2 | MISSING | No custody control; agent-stack states the opposite as a recorded limit ("**No control pins this.**"). Host `HOME` not mounted — that sub-point holds. | OPERATIONS §46 |
| C3 | NOT-APPLICABLE | No kernel conformance suite. | — |
| S1 | MISSING | Package credentials (`market.env`, `package.env`) and role MCP tokens are loaded into the **same** agent container environment the model process runs in and are readable cross-process at uid 1000. | compose `agent` `env_file`; OPERATIONS §36, §46 |
| S2 | PARTIAL | Direction is right: the broker (uid 1050, own container, `/work:ro`) holds Preloop principal credentials and hands steps an opaque per-job token (§53–54). But provider, package and Preloop-hook credentials remain in the governed container. | `stack/broker.py`; OPERATIONS §54 |
| S3 | COVERED (in kind) | agent-stack is precisely an optional, declarative execution service: "the platform provides capabilities; it does not decide behaviour". | `CONTRACT.md`; `capabilities.py` |
| S4 | MISSING | No `ExecutionRequest` with profile/provider/input digests; no `ExecutionResult` with an output-artifact digest bound as a subject. | `run-agent.mjs`; `record.py` |

### OUT-OF-SCOPE-EXTRA (agent-stack has it; the EP TD does not ask for it)

| Feature | Where | Note vs TD |
|---|---|---|
| Quota-based admission (`ROUTE`/`HOLD`, per-window `used_percent`, staleness, candidate order) | `router.py`, `collect_obs.py`, `steps/route.py`, `steps/admit_models.py` | Closest TD analogue is B2(2)'s "spend caps" as a *classification trigger*. |
| Observed-vs-executing **account** identity match (email fingerprint, codex session ledger) | `collect_obs.py`, `codex_identity.py`, `run-agent.mjs` | Identity of the *paying account*, not the *serving model*. |
| Login lineage / login state (`/route/<login>`, panel sign-in) | README, OPERATIONS §29 | TD treats auth as operator-extracted tokens injected per run. |
| Per-role egress (uid + tinyproxy BasicAuth per role) and egress **profiles** (network-per-profile, broker dispatch, job tokens) | `role_egress.py`, `broker.py`, `profile_runner.py` | Finer than the TD's single allowlist; still not per-surface containers. |
| Preloop tool rights per principal + approval boundary as a route (`apiguard`) + human approval channel | `docker/apiguard.conf`, OPERATIONS §20–21 | Tool-call governance; TD's PEP governs *effects*. |
| MLflow recording, fan-out receipts, chained members, cancellation/resume, compositions | `steps/record.py`, `steps/tasks.py`, `run_workflow.py`, `capabilities.py` | Orchestration/record concerns the EP TD leaves to orchestrators. |
| Normalized denial semantics (`DENIED` never retried elsewhere; `CONTROL_UNAVAILABLE`, `TIMED_OUT`) | `run-agent.mjs` `norm` | Useful fail-closed discipline; no TD counterpart. |

## C. Summary

1. agent-stack's routing layer is an **adapter + admission + egress** service: `run-agent.mjs` normalizes one acpx call per vendor, `router.py` admits by quota, tinyproxy bounds provider reach, Preloop governs tool calls. It maps onto the EP TD's *surface broker* in role, but it brokers **prompts to a long-lived container**, not **digested requests to per-attempt isolated surfaces**.
2. It satisfies the TD's *posture* clauses in spirit (honest `UNKNOWN`, requested≠observed kept apart, fail-closed on unknown provider / missing capability, network as the boundary) and almost none of its *contract* clauses.
3. **Gap 1 — no symmetric execution contract (S4, B1.*, B2.*, B3.*):** no `ExecutionRequest`, no profile/prompt/revision digests, no broker-minted attempt identity, no `output_artifact_{subject,digest,locator}`, no envelope.
4. **Gap 2 — credential custody (A5, B7.1, S1/S2):** all three provider logins, package credentials and the Preloop hook live in the one governed container; OPERATIONS §46 records that no control pins reach.
5. **Gap 3 — no per-surface isolation or identity (A12, B2.3, B2.5):** one container, shared `/ws`, deterministic reusable `run_id`, retries overwrite in place.
6. **Gap 4 — no measured observation of the surface (A3, A9, A10):** `served:"unknown"` is hardcoded; no session scan, no locators, no role vocabulary, no independence guard.
7. **Gap 5 — no reviewer evidence-plane discipline and no external verifier (A8, B6b).**
8. Where agent-stack exceeds the TD (quota admission, account matching, per-role egress, job-token broker, approval route) it is in dimensions the TD leaves to deployment policy — and B2(2) implies that by governing spend it has already triggered the clause that should pull provider credentials behind the boundary.
