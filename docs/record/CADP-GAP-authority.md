# Authority Plane gap analysis — CADP v0.5 AP TD vs. agent-stack

Sources read: `TECHNICAL_DESIGN_cadp_v0_5_authority_plane.md` (Part A, B1–B6, §C, Appendix); Spec v0.5 §2, §3 (K1–K7), §4.3–4.4, §9.1; TD v0.4 §§2–6, 9, 12, 13 (re-homed by Part A); agent-stack `CONTRACT.md`, `docs/concepts.md`, `docs/containers.md`, `docs/record/COVERAGE.md`, `docs/record/OPERATIONS.md` §10, §13, §16–§21, §26, §28, §38–§39, §43–§44, §56–§57, and `stack/{run-agent.mjs, router.py, broker.py, approver.py, approvals.py, principals.py, capabilities.py, cfg.py, mcp_call.py, packages.py, trajectory.py, role_egress.py, steps/record.py, steps/broker_dispatch.py, steps/admit_models.py}`, `policy/*.yaml`, `config/principals.yaml`, `docker/apiguard.conf`, `docker/egress/allow`.

Verdict legend: COVERED / PARTIAL / MISSING / N-A. "Substitute" names what agent-stack has in that place, if anything.

## A1. Spec v0.5 §2 — constitutional invariants

| ID | Requirement (one line) | Anchor | Verdict | Evidence / substitute |
|---|---|---|---|---|
| S2.1 | Producer output is never effect authority; chain is request → policy evaluates → PEP admits → narrow capability performs → authoritative source reconciles; Human identity never bypasses the PEP | Spec v0.5 §2.1 | PARTIAL | Preloop evaluates tool rules per call and its MCP proxy performs the tool call (`run-agent.mjs`; `policy/b-fsmcp.yaml`); no reconciliation stage exists (OPERATIONS §38). Human decision = Preloop approval answered with the runtime's *own* credential (`stack/approvals.py::_token`, OPERATIONS §13). |
| S2.2 | `policy ALLOW ≠ effect authority`; PEP freshly verifies exact decision/effect binding and releases/uses a bounded capability | Spec v0.5 §2.2 | MISSING | Preloop `permission-check` returns `allow`/`deny` and the vendor CLI itself then performs the native tool (`run-agent.mjs::askPreloop`); for MCP tools the decision and the call are one request. No decision record bound by digest to an effect; no bounded capability. |
| S2.3 | No standing credential able to create a governed effect in any worker/model/reviewer payload; no credential KIND exempt | Spec v0.5 §2.3 | MISSING | Packages' effect credentials are injected into the **agent** container environment: `DEVFLOW_GITHUB_TOKEN` via `docker/package.env` (OPERATIONS §43; `stack/packages.py`). Provider logins live in the agent (`/route`). The runtime's hook credential carries `decide_approvals`; only a nginx route refuses it (`docker/apiguard.conf`; OPERATIONS §20 "a route restriction, not a rights restriction"). Substitute: broker holds *Preloop* principal credentials out of step reach (`stack/broker.py`, OPERATIONS §48, §54). |
| S2.4 | Exact binding by immutable identity + digest of policy, work revision, effect target/operation/material, evidence, decision, backend identity | Spec v0.5 §2.4 | PARTIAL | Artifact hashes exist (receipt `sha256`, `draft_meta.json`, `packet_sha256`, `evidence_index.json`; `cfg.py` records policy source sha256). But a permission decision binds only `tool_name` + `tool_input` text, never a policy revision/digest or material digest. |
| S2.5 | Fail closed on missing/stale/UNKNOWN facts; **unclassified operation defaults to effecting** | Spec v0.5 §2.5; §9.1 | PARTIAL | Fail-closed is real on the routing side (`router.py` rules 1–5; permission-path failure ⇒ denial; missing capability ⇒ run refused). Classification is fail-**open**: every policy sets `defaults: unknown_tools: allow` (`policy/*.yaml`), and principal rules default to allow absent an explicit deny. |
| S2.6 | Sealed append-only history is authority; no mutable desired-state store; "latest" lookups at dispatch forbidden | Spec v0.5 §2.6; TD v0.4 §6.6 | PARTIAL | Evidence dirs and MLflow runs are append-only in practice. Authority facts are mutable: Preloop holds ONE policy per account replaced in place (`cfg.py`), approval bypasses and tool rights are live switches (OPERATIONS §16). |
| S2.7 | No silent substitution: changed policy/material/evidence/decision ⇒ new evaluation; decisions never silently reused | Spec v0.5 §2.7 | MISSING | Preloop **approval bypasses** ("stop asking, for a while", OPERATIONS §16) are standing cross-effect reuse; agent-stack only *displays* them (`stack/elsewhere.py`). |
| S2.8 | Reconciliation is epistemic; reconciler never dispatches; blind retry forbidden | Spec v0.5 §2.8; §4.4 | MISSING | No reconciler; no UNKNOWN outcome class. §38: a resumed run re-creating the same PR is left to the workflow ("asks the remote whether the effect already happened"). |
| S2.9 | Genesis out-of-band by root; policy content never mutated in place; activation only via governed effect / signed break-glass | Spec v0.5 §2.9 | MISSING | `preloop policy apply` from the admin container overwrites the account policy (OPERATIONS §21); `scripts/up.sh` claims a fresh Preloop by bootstrap token (§22). No revision identity, no signature, no activation record. |

## A2. Spec v0.5 §3 — K1–K7

| ID | Requirement | Anchor | Verdict | Evidence / substitute |
|---|---|---|---|---|
| K1 | Immutable `PolicyRefV1` {policy_id, revision, content_digest, issuer_ref}; mutable alias never admits | Spec v0.5 §3 K1 | MISSING | Substitute: `cfg.py status` tracks `source_sha256`/`applied_sha256` of the YAML — an ops record, not an identity bound to any decision. |
| K2 | `EvidenceEnvelopeV1` with subject bindings, `availability PRESENT/UNKNOWN`, provenance {source_relation, integrity} | Spec v0.5 §3 K2 | PARTIAL | `permissions.jsonl`, `result.json`, receipts, `evidence_index.json` carry hashes and principal names; "requested ≠ observed" discipline applied. But envelopes are worker-written files in the agent's own evidence dir, no schema, no `availability`, no ingress stamping, no provenance class. |
| K3 | `EffectRequestV1`: Platform-allocated `effect_id` before any external call; one `effect_id` ⇔ one `request_digest` | Spec v0.5 §3 K3 | MISSING | No effect identity exists; ids are Conductor run ids and per-call `run_id`. §38: "what stops a resumed run from repeating an external side effect … Nothing in the platform does, and nothing should." |
| K4 | `AdmissionInputV1`: complete canonical binding of everything the evaluator sees; PEP never back-fills | Spec v0.5 §3 K4 | MISSING | Preloop evaluates CEL over `{"args": args}` plus the subject chain; `evidence_index.json` is assembled by the workflow's own judging step — caller-selected. |
| K5 | `PolicyDecisionV1` bound to exact input digest; evaluator integrity verified; errors never ALLOW | Spec v0.5 §3 K5 | PARTIAL | Preloop's answer `{decision, timed_out, request_id}` logged per call; approval expiry is a policy outcome; error ⇒ `control_unavailable` ⇒ denial. No policy_ref, no input digest, no evaluator integrity ref. |
| K6 | `EffectAdmissionV1` durably recorded **before** any external call; commit-time recheck; single-dispatch bounded capability; atomic `(effect_id, dispatch_ordinal)` | Spec v0.5 §3 K6 | MISSING | No pre-effect record. Native tools: the vendor CLI performs the effect after the hook allow. MCP tools: Preloop proxy performs the call in-process. Broker job token (`TOKEN_TTL_S = 3600`) is a per-job bearer for one *role's rights*, not a single-dispatch capability. |
| K7 | `EffectOutcomeV1` append-only; `COMMITTED` requires target-authoritative receipt; timeouts/404s are `UNKNOWN` | Spec v0.5 §3 K7 | MISSING | Outcome is the worker's normalized `status` (COMPLETED/FAILED/DENIED/TIMED_OUT) — self-report; `produced`/`produced_stale` is a local stat. No target-authoritative receipt. |

## A3. Spec v0.5 §4.3 admission protocol / §9.1 kernel conformance

| ID | Requirement | Anchor | Verdict | Evidence / substitute |
|---|---|---|---|---|
| P4.3 | Eight-step positive path; steps 5–7 never skipped by workflow success / PASS / APPROVE / ALLOW | Spec v0.5 §4.3 | MISSING | Workflow routes on `gate.decision` PASS/REPAIR/BLOCK and steps act directly; nothing between a workflow verdict and the next step's effect except Preloop's per-tool-call rule. |
| P4.3h | Human/delegated decisions as envelopes with exact scope, attributable identity, no reuse, no self-approval | Spec v0.5 §4.3 | PARTIAL | Preloop approval shows tool/file/cwd/run; answer's credential fingerprint logged; reviewer ≠ author enforced by per-role principals. But approver identity is the runtime's own credential (§13), scope is a Preloop request id, bypasses permit reuse. |
| P4.3r | Review/verification evidence must bind the immutable candidate; reviewers never hold bypass credentials | Spec v0.5 §4.3 | PARTIAL | Reviews reference the reviewed file's sha256 and the frozen draft hash (§18); reviewer principals denied the draft (§10). Reviewer roles run in the same agent where package credentials are present (§43). |
| P9.1 | Kernel-conformance controls (wrong target/revision/material/stale evidence/decision reuse do not admit; no capability release without admission record; replay ⇒ no duplicate; etc.) | Spec v0.5 §9.1 | MISSING | No admission record, no effect identity, so none expressible. Substitute: 515–524 machinery controls (`trial_controls.py`, `review_controls.py`, `router_controls.py`; N1/N2/N7 policies) measure tool-rule enforcement, not effect binding. |

## A4. Part A re-homed TD v0.4 content

| ID | Requirement | Anchor | Verdict | Evidence / substitute |
|---|---|---|---|---|
| A2.1 | Canonicalization `cadp-jcs-1` / `raw-bytes-1`; digest object `{algorithm, canonicalization, value}` | TD v0.4 §2.1 | MISSING | Bare hex sha256; no canonical JSON, no scheme object. |
| A2.2 | Identities allocated by Ingress (`cadp-v04:<kind>:<uuidv7>`); requester never chooses `effect_id` | TD v0.4 §2.2 | MISSING | Ids are Conductor/caller strings. |
| A2.3 | Content-addressed material/claims (`cas://sha256/`), verify on write and read | TD v0.4 §2.3 | MISSING | Workspace files under `/ws`; no CAS. |
| A2.4 | No replaceable fields; runtime DB INSERT/SELECT only | TD v0.4 §2.4 | PARTIAL | MLflow/evidence append; `record.py` dedupes by `idempotency_key`. Preloop policy/rights/bypasses mutated in place. |
| A2.5 | Write validation and verify-on-read for admission | TD v0.4 §2.5 | MISSING | `trajectory.py` reports `null` when unreadable; no digest verification. |
| A2.6 | `KERNEL_INCIDENT` envelopes; kernel-enforced scope hold | TD v0.4 §2.6 | MISSING | `evidence/ops/controls.jsonl` is an ops log. |
| A3.1–3.4 | Constitutional store contract and admission transaction | TD v0.4 §3 | MISSING | No constitutional store. Conductor state + MLflow + evidence files. |
| A4.1 | Credential owner = PEP process only; isolation by mechanism | TD v0.4 §4.1 | PARTIAL | Mechanism-based isolation exists for *Preloop* credentials and egress (broker uid separation, apiguard, per-profile allowlists). But the agent owns provider logins and package effect tokens (§43), and the allowlist can be widened per instance (`allow.local`). |
| A4.2 | Proof of actual target identity by read-only probe (`PEP_TARGET_IDENTITY`) | TD v0.4 §4.2 | MISSING | Analogue only for quota: `router.py` refuses `observed_account != executing_account`. |
| A4.3 | Bounded capability, exactly one dispatch, dispatch window | TD v0.4 §4.3 | MISSING | Broker job token authorises *any number* of MCP calls as that role for the job's lifetime. |
| A4.4 | Commit-time recheck items 1–17 (+#18, +run-membership) | TD v0.4 §4.4; AP B4(5), B5 | MISSING | — |
| A4.5 | Restart reconciliation; no dispatch journal | TD v0.4 §4.5 | PARTIAL | Conductor checkpoint + `resume` (§23) — workflow replay, which Spec §4.4 says never substitutes for authority. |
| A4.6 | Dispatch precondition classes; pre-K6 refusal not an effect | TD v0.4 §4.6 | MISSING | — |
| A5.1–5.3 | `EvaluatorPort` bundle; evaluator integrity proof; decision sealing with TTL and closed constraint vocabulary | TD v0.4 §5.1–5.3 | MISSING / PARTIAL | Preloop evaluator input is `{"args": args}` + subject chain; version pin only. Approval `expires_at` ⇒ `approval_expired` is a policy outcome; `client_decision` deliberately omitted. Loop bounds (`max_repairs`) are workflow-owned. |
| A5.4 | Kernel-consumed config: closed schema, no defaults, exact-match registries | TD v0.4 §5.4; AP B3(5) | PARTIAL | `cfg.py` refuses `native_allow` outside `{WebSearch, WebFetch}`; but `unknown_tools: allow`, no closed vocabulary; config lives in Preloop's mutable account. |
| A6.1–6.6 | `TargetAdapterV1` port, native idempotency key, outcome truth table, reference adapters, reconciler, CAS completeness | TD v0.4 §6 | MISSING | Tool servers are plain MCP servers. Substitute: each *step* declares `REPEATABLE = yes/guarded/no` (§17) — workflow-side, unproven. devflow performs GitHub effects from inside the agent with its own token. |
| A9.1 | Evidence ingress stamps `producer_ref` from authenticated identity; `source_relation` checked against registry | TD v0.4 §9.1 | PARTIAL | Principal *name* recorded per call, token never; evidence files written by the worker into its own `evidence_dir` — self-stamped. |
| A9.2 | `CREDENTIAL_REACH_ATTESTATION` negative probe from worker identity | TD v0.4 §9.2 | PARTIAL | `scripts/up.sh` / `ops_health.py` probe the guard *from the governed position* on every bring-up (§20). Not an envelope, not consumed by admission, does not probe governed effect targets. |
| A9.3 | Human decision `cadp.human-decision.v1`: authenticated principal, effect sealed first, scope mandatory, no reuse | TD v0.4 §9.3 | PARTIAL | Preloop approval = human gate per tool call with facts shown. Principal is the runtime credential (§13); no effect to bind to; bypasses enable reuse (§16). |
| A9.4 | Genesis; `POLICY_ACTIVATE` effect; Ed25519 root signatures; `BREAK_GLASS` | TD v0.4 §9.4 | MISSING | `cfg.py apply` / `preloop policy apply` from admin (§21); bootstrap claim (§22). |
| A9.5 | Retention/archival as a root operation with signed evidence | TD v0.4 §9.5 | PARTIAL | `stack/cleanup.py` previews before destruction and protects pending approvals (§9). |
| A12 | Twelve-call Kernel API; reach matrix by `process_class`; "enforced by the Kernel Service, not by network position" | TD v0.4 §12 | MISSING | Substitute: apiguard route matrix, per-role Preloop principals, broker `/dispatch` reachable by anything on the governed network (§56: "Spend, not escalation"). Reach is network position. |
| A13 | Conformance plan C1–C42, P1–P7, two-claim report | TD v0.4 §13 | PARTIAL | A large measured control set exists (515–524, §56–57; N1/N2/N7) with a guard-bite spirit. No control corresponds to any C-series item. |

## A5. Part B — new v0.5 contracts

| ID | Requirement | Anchor | Verdict | Evidence / substitute |
|---|---|---|---|---|
| B1(1)–(5) | Requester-scoped `allocate_effect_id`; `allocation_key = sha256(jcs({requester_ref, tuple, contract_digest}))`; `cadp.allocation-key.{external,run-origin}.v1` | AP B1 | MISSING | No allocation call. Substitute: `record.py` `idempotency_key` (record-only). |
| B2(1)–(11) | `effect_allocation` row shape; schema descriptor registry; cross-activation immutability; first-seal checks before any K3 row; one transaction; refusal shape | AP B2 | MISSING | — |
| B3(1) | Activation refuses duplicate registry rows | AP B3(1) | PARTIAL | Analogue: a principal declared by two packages is reported as a conflict (stack's own wins); not an activation refusal. |
| B3(2)–(5) | Unknown-key refusal; closed entry key sets; `kernel_subject_namespaces`; `cadp.kernel-config.v2` | AP B3 | MISSING | `cfg.py` refuses only non-allowed `native_allow` tools; principals YAML keys not closed. |
| B4(1)–(5) | `subject_complete_assembly`: assembly queries the complete sealed set, caller can add never subtract; fail closed; recheck #18 | AP B4 | MISSING | `evidence_index.json` produced by the workflow's judging step — the caller decides what the record sees (§18; CONTRACT.md). |
| B5(1)–(10) | Run capability minted at witnessed initial dispatch; enrolled requesters; `run_membership` row; delivered exactly once; ORIGIN-OR-REFUSED | AP B5 | MISSING | Substitute: broker mints an opaque per-job token for a *role*; OPERATIONS §56 states a per-run token was measured and deliberately **not built** (ptrace_scope 0). Token re-presented on every MCP call. |
| B6(1)–(5) | Wire framing: `allocation_tuple` body field; `x-cadp-run-capability` header; `METHOD_REACH` unchanged | AP B6 | MISSING / N-A | — |

## A6. Section C — falsification controls

| ID | Control | Anchor | Verdict |
|---|---|---|---|
| C-A1 | Duplicate-registry-row rejection at activation | AP §C A1 | MISSING (conflict reported, not refused) |
| C-A2 | Unknown-entry-key rejection | AP §C A2 | MISSING |
| C-A3 | Assembly-completeness refusal | AP §C A3 | MISSING |
| C-A4 | Run-capability borrowing / witnessed minting / K7-gated usability | AP §C A4 | MISSING |
| C-A5 | Run-origin identity & contract immutability | AP §C A5 | MISSING |
| C-B2 legs | Binding mismatch pre-K3; typed tuple values; descriptor immutability; purpose mismatch; cross-principal re-seal; namespace checks | AP §C | MISSING (nearest analogue: `router_controls.py` typed-value discipline on observations) |

## C. Summary

1. **What agent-stack is, in v0.5 vocabulary:** a **Workflow Plane** (Conductor graphs, checkpoint/resume, fan-out receipts, `REPEATABLE` step declarations) plus an **Execution Plane** (routing layer over provider quotas, per-role Preloop principals, broker-held credentials, per-profile egress), with Preloop acting as a **per-tool-call permission gate** and MLflow as a run record. It implements **no Authority Plane kernel**: no K1–K7 record exists, and OPERATIONS §38 states as design that the platform does not deduplicate or govern external effects — the inverse of the AP TD's "the moment it changes the external world, it is CADP's business".
2. **Gap 1 — no effect identity, admission or outcome (K3/K6/K7, TD §3.4, §4.3–4.6, B1/B2):** tool calls are decided and performed in one request; native-tool effects are performed by the vendor CLI after a hook allow; nothing durable precedes an external call and nothing target-authoritative follows it.
3. **Gap 2 — credential reach (Spec §2.3, TD §4.1, §9.2):** governed-effect credentials (`DEVFLOW_GITHUB_TOKEN`, provider logins) sit in the agent container; the runtime's own credential can decide approvals and is held back only by an nginx route (OPERATIONS §13, §20).
4. **Gap 3 — no immutable policy identity bound to decisions (K1/K4/K5, TD §5, §9.4, B3):** Preloop's single mutable account policy is replaced in place; decisions carry no policy digest, no input digest; `unknown_tools: allow` is fail-open on classification (Spec §2.5).
5. **Gap 4 — silent reuse and no reconciliation (Spec §2.7–2.8, §4.4):** approval bypasses are standing cross-effect reuse that agent-stack only displays; no UNKNOWN discipline, no reconciler.
6. **Gap 5 — run membership / caller authentication (B5/B6, TD §12):** the broker's `/dispatch` is callable by anything on the governed network and a per-run token was explicitly not built (§56); reach is network position, which TD §12 rejects.
