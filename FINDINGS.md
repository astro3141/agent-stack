# #278 PoC — findings so far (2026-09-20, rebuilt environment)

Status: L0 wiring partially proven. Two blockers are user-action items (see end).

## Publishing map (for the #278 comment / receipt)

Each finding is written to stand alone so it can be posted as-is. Mapping to the issue:

| Finding | Issue section | Carries |
|---|---|---|
| F1 | §4.3, §11 | `conductor_to_mlflow: CONFIG_ONLY`; falsifies the "collector may be needed" note |
| F2 | §5, N8 | `N8: CONFIRMED` (static rejection, exact upstream message) |
| F3 | §4.1, §4.2 | config shapes accepted as written (static only) |
| F4 | §4.4, §6, N3, N4 | `conductor_to_gate`; Gate is stateless and cannot infer PASS |
| F5 | §4.4 | Conductor v0.1.37 schema deviations from the issue's snippets |
| F6, F9 | §7, N7 | isolation architecture; why containerization is not a THIN_ADAPTER |
| F7 | §11 | baseline versions; Flow present but unused |
| F8, F12 | §4.1, N6-adjacent | subscription credential custody: failure, then controlled non-reproduction |
| F10 | environment | host-local TLS interception; NOT generalizable, footnote only |
| F11 | §4.1 | model pin is a precondition; corrects an earlier wrong diagnosis |
| F13, F13a | §4.1, §6, EVIDENCE_VISIBILITY | routing proven, attribution lossy — supports the "no observability as source of truth" rule |

Corrections made in place rather than deleted: F8 (narrowed), F11 (replaced), F13 (rate-limit
claim withdrawn). Each says so explicitly, because a receipt that hides its own wrong turns is
worth less than one that shows them.

---

## F1 — §4.3 Conductor -> MLflow composes CONFIG-ONLY, no collector needed

Proven live. Environment variables only:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:5000
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_EXPORTER_OTLP_HEADERS=x-mlflow-experiment-id=1
OTEL_SERVICE_NAME=cadp-commodity-composition-poc
```

- MLflow logged `POST /v1/traces 200 OK`; traces are queryable via
  `/api/3.0/mlflow/traces/search`.
- **The issue's §4.3 note that the `x-mlflow-experiment-id` header "may require an
  OTel Collector" is falsified for this version pair.** Conductor's exporter honors the
  standard `OTEL_EXPORTER_OTLP_HEADERS` variable and the traces land in the named
  experiment (id 1), not the default one. No collector is in the path.
- Correction to the issue's env contract: Conductor enables tracing from
  `OTEL_EXPORTER_OTLP_ENDPOINT` (base URL), per `docs/telemetry.md`. The
  signal-specific `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` named in §4.3 is not the
  documented switch; the base-URL form is what was tested and works
  (SDK appends `/v1/traces`).
- Span hierarchy ingested: `invoke_workflow <workflow-name>` -> `invoke_agent <step>`,
  parent/child preserved. Enough to locate steps (§11 "MLflow shows the workflow/step
  hierarchy"), measured on a model-free run; model/tool span depth still unmeasured.
- Native correlation identifier confirmed: every trace carries tag
  `conductor.run_id` (= Conductor's run id) and `service.name`. That is a **native**
  join key for §6, requiring no shim.
- Failure visibility: a run that failed on a bad script path was ingested with
  `state: ERROR`, so observability sees failures without extra wiring.

## F2 — N8 (direct `type: mcp` over HTTP) CONFIRMED incompatible, config-only

`conductor validate` rejects the composition statically with the exact upstream message:

```
Agent 'direct_call': type: mcp supports stdio servers only (got 'http');
http/sse support is not implemented yet
```

This is the expected baseline finding from §5/N8, and it is a *static* rejection, so
no runtime probing is needed to establish it. Recorded, not hidden, not forked.

## F3 — §4.1/§4.2 config shapes are schema-valid as written in the issue

`conductor validate` accepts, unchanged:

- §4.1's `runtime.provider: {name: openai, base_url: ..., api_key: ${PRELOOP_API_KEY}}`
- README's alternative structured form `{name: copilot, type: openai, wire_api: completions, base_url: ...}`
- §4.2's `runtime.mcp_servers.preloop: {type: http, url: .../mcp/v1, headers: {Authorization: Bearer ...}}`

Static acceptance only — **not** proof of live traffic through Preloop. Blocked on B1.

## F4 — Gate is a stateless script step and cannot infer PASS

`gate/gate.py` is a pure stdin->stdout function (no network, no state, no model).
Unit-level negative controls already reproduce:

| Input | Decision |
|---|---|
| complete evidence, tests green, review PASS, governance APPROVED | `PASS` |
| tests exit_code=1, failed=2 | `RETRY` (N4: never PASS) |
| `artifact.sha256` removed | `BLOCK` + `missing: [artifact.sha256]` (N3) |
| empty/garbage stdin | `BLOCK` (N3) |
| governance status UNKNOWN (no Preloop reachable) | `BLOCK` |

Retry is **not** owned by the Gate: `decision == 'RETRY'` is a Conductor route back to
`implement`, bounded by `workflow.limits.max_iterations`. Conductor stays the sole
routing/retry authority (§2).

## F5 — Conductor v0.1.37 schema deviations from the issue's snippets

- `workflow.context_mode` is documented in `docs/workflow-syntax.md` but **rejected** by
  the v0.1.37 schema (`extra_forbidden`). Docs are ahead of the released tag.
- `{{ workflow.dir }}` resolves to the directory of the YAML file, not the project root.
- Script `command`/`working_dir` need Windows-absolute paths or `${VAR:-default}`
  loader substitution.

## Blockers (user action)

**B1 — Preloop control plane not provisioned.** Upstream supports two install surfaces:
Preloop Cloud, or self-host via Docker Compose / Helm. This host has no Docker and no
WSL distro. Without a control plane, §4.1, §4.2, N1, N2, N6 and N7 cannot be executed,
and the governance probe correctly reports `UNKNOWN` (which the Gate turns into BLOCK).

**B2 — Claude Code OAuth session expired on this host.** The agent steps
(`research`/`implement`/`review`) fail with
`Failed to authenticate: OAuth session expired and could not be refreshed`.
Needs `claude` re-login, or an `ANTHROPIC_API_KEY` for the raw `claude` provider.
The deterministic half of the slice (script/set/gate/terminate steps) is unaffected.

## F6 — Governed-agent config isolation (decided 2026-09-20)

The Preloop `--approvals` onboarding installs a Claude Code PreToolUse hook, which would
otherwise govern the operator's everyday Claude Code sessions on this host.

Measured against upstream source, **`CLAUDE_CONFIG_DIR` does not isolate this**: Preloop's
CLI resolves Claude settings from `os.UserHomeDir()/.claude/settings.json`
(`cli/internal/cmd/claude_permission_policy.go:53-58`) and its sidecar config from
`~/.claude/preloop-control.json` (`cli/internal/cmd/claude.go:101`). Neither reads
`CLAUDE_CONFIG_DIR`. Relocating the agent's config dir would pollute the real `~/.claude`
while the governed agent reads a different tier — the hook would not fire at all.

Chosen isolation, using Conductor's own documented mechanism:

```yaml
workflow:
  runtime:
    provider:
      name: claude-agent-sdk
      setting_sources: [project]     # `user` tier deliberately NOT loaded
agents:
  - name: implement
    working_dir: D:/Work/poc-278/fixture
```

`docs/workflow-syntax.md`: "`project` reads `<working_dir>/.claude/settings.json`, whose
`hooks` run shell commands on tool events." So the Preloop hook lives only in
`fixture/.claude/settings.json` and governs only agents whose cwd is the fixture.
`~/.claude` is untouched. Model-gateway env vars are injected per `conductor run` process,
never exported globally.

This also resolves the `setting_sources` trap raised in the issue's design-correction
comment: enabling `[user]` would have loaded the operator tier's *other* hooks too.

Operational note (not an adapter): `preloop agents onboard` writes user scope by default.
If its CLI exposes no scope flag, the generated hook block is relocated by hand into
`fixture/.claude/settings.json` and the user file reverted. Config relocation only — no
upstream fork, no second policy engine.

Caveat recorded: the hook must NOT be placed at `poc-278/.claude/settings.json` — that is
the operator's own session cwd, which would route the operator's tool calls through
Preloop approvals.

## B2 — RESOLVED

Claude Code OAuth re-authenticated on this host; `claude -p` returns normally. Agent steps
are unblocked.

## F7 — Preloop OSS stack provisioned (B1 resolved for wiring)

Preloop OSS **0.15.0** self-hosted via the upstream `install/oss` script on Docker Desktop
4.91.0 (engine 29.8.0, compose v5.5.1). All eight containers running:
`api` (8000), `gateway` (8001), `console` (3000), `postgres`, `nats`, `scheduler`,
`worker`, `flow-worker`. CLI: `preloop` 0.15.0 (commit c91b326).

Endpoint probes (unauthenticated, from the host):

| Endpoint | Result | Meaning |
|---|---|---|
| `http://localhost:3000/` | 200 | console up |
| `http://localhost:8001/openai/v1/models` | **401** | §4.1 Model Gateway route exists, auth required |
| `http://localhost:3000/mcp/v1` | **401** | §4.2 MCP Safety Layer route exists, auth required |

`flow-worker` runs as part of the stock compose file. Preloop Flow remains **unused** by
this PoC (§7 non-goal); its presence in the stack is not Flow-dependency.

Confirmed for F6's operational note: **`preloop agents onboard` exposes no settings-scope
flag** (`--all --approvals --dry-run --force --live-validate --model --no-reuse --tags
--yes` only). The hook relocation into `fixture/.claude/settings.json` is therefore
required, and `--dry-run` will be used first to capture exactly what it would write.

Two steps remain operator-only (not performed by the agent): first-user creation via the
installer's bootstrap link, and `preloop login`.

## F8 — Observed: Preloop onboarding took custody of the rotating subscription credential

Discovered by causing it (2026-09-20). `preloop agents discover` **auto-onboarded** Claude
Code: in a non-TTY shell its confirmation prompts (`Onboard ...? (Y/n)`, `Route native tool
calls through Preloop approvals? (Y/n)`) take the default answer, so a read-only-sounding
discovery command performed a mutating onboarding of the user tier.

Effect, in Preloop's own words on offboard:

> Restored subscription login: live token written back to `~/.claude/.credentials.json`
> (subscription tokens rotate, and the Preloop account held the active copy while onboarded).

Because Anthropic subscription tokens **rotate**, the Preloop account holding the active
copy logged the operator's Claude Desktop / Claude Code out repeatedly — re-login produced a
new token, which the gateway's copy then superseded again.

Scope of the claim (deliberately narrow — the internal mechanism is NOT established):

> A rotating Claude subscription credential must not be shared across independently operated
> governed and interactive runtimes unless credential-custody/rotation semantics are
> explicitly proven safe. In the observed Preloop onboarding path, custody of the active
> subscription credential moved into the gateway and interfered with the host Claude
> Code/Desktop authentication state.

What is established: onboarding moved custody (upstream says so on offboard), the host
logged out repeatedly while onboarded, and offboarding restored normal operation
immediately. What is **not** established: which specific refresh revoked which token.
Confirming that needs gateway-side and Anthropic-side auth logs that this PoC does not have.
This is therefore an observed interaction, not a proven revocation mechanism, and it is not
evidence that *all* subscription-identity sharing is impossible in principle.
- The design-correction comment on #278 recorded that the gateway supports Max OAuth as a
  byte-faithful proxy. That remains true, but the **custody** consequence was not captured:
  it is exclusive, not shared.
- Implication for the PoC: the governed agent must use either a separate Anthropic **API key**
  (upstream's own recommended fallback, printed during onboarding) or a separate account.
  This is a finding for the receipt's EVIDENCE_VISIBILITY / BYPASS_PATHS discussion, not a
  workaround to hide.

Recovery performed: `preloop agents offboard "Claude Code" -y --remove-model yes
--remove-mcp-servers yes` (restores config and writes the live token back), quarantined
`~/.claude/preloop-control.json` and `~/.claude/settings.preloop-backup.json` into
`evidence/incident-20260920/`, removed the pre-approved gateway key from
`~/.claude.json` `customApiKeyResponses.approved`, and stopped the `gateway` container.

Process rule added: **never run `preloop agents discover` in a non-TTY shell.** Use
`preloop agents onboard <agent> --dry-run` explicitly, and read the plan before applying.

## F9 — Governed runtime is a container, isolated on an internal Docker network

Architecture adopted 2026-09-20 after the F8 incident, replacing the project-scope
settings trick of F6 (F6's analysis stands but is no longer the isolation mechanism).

```
Windows host                         Docker
  Claude Desktop / Claude Code         agentstack-governed  (internal: true — NO egress)
  ~/.claude  ← never onboarded           ├─ agent      : Conductor + Claude Code + fixture
                                         ├─ mlflow     : traces (port published inbound only)
                                         └─ preloop api / console / gateway (attached out of band)
                                                    │
                                       gateway is the ONLY dual-homed member → Anthropic
```

Rationale and honest scoping:

- **Conductor and Claude Code share one container** for reproducibility and simpler
  instrument wiring — *not* because a container boundary would break tracing. W3C
  `traceparent` propagation crosses process and container boundaries; Conductor's own
  telemetry doc documents exactly that for its Copilot provider. What a split would risk
  is losing provider-native in-process instrumentation, which is a different and smaller
  claim than the one made earlier in this session.
- **No Anthropic credential in the image.** Credentials are minted inside the container
  and live in the `agentstack-agent-home` volume. The host's `~/.claude` is never mounted.
  This is the specific thing that went wrong in F8 (Preloop read the *host's* credential
  file); a container-minted login is a separate token lineage.
- **Two-phase credential handling.** `claude auth login` needs egress to claude.ai, which
  the governed network forbids by design. So the agent is attached to a throwaway bridge
  network (`agentstack-provision`) for the login step only, then disconnected. Provisioning
  path and governed runtime path are deliberately distinct, and the receipt records both.
- **N7 evidence upgrade.** Because the agent's only network is `internal: true`, a direct
  `api.anthropic.com` call is refused at the network layer rather than merely absent from
  configuration. The claim becomes: *the governed workload's network has no external
  egress, and the only dual-homed model path is the Preloop gateway.* Port publishing on
  the MLflow service is inbound DNAT and grants no egress, so it does not weaken this.
- **Containerization is not a THIN_ADAPTER.** It owns no workflow state, no policy, no
  evidence, and translates nothing. It is deployment packaging, so it does not by itself
  move the disposition off `COMPOSES_CONFIG_ONLY`.

Open item to measure, not assume: whether a published port works on an `internal: true`
network in this Docker version. If it does not, MLflow gets dual-homed on an inbound-only
bridge and that fact is recorded rather than hidden.

## Operating rules added after F8

```
Host:
  preloop agents onboard      FORBIDDEN
  preloop agents discover     FORBIDDEN (auto-onboards on default answers in a non-TTY shell)
  touching ~/.claude          FORBIDDEN

Container:
  all of the above permitted
```

Verified against the installed CLI (0.15.0), the read-only discovery paths are
`preloop agents discover --json` ("read-only, no prompts") and
`preloop agents discover --no-onboard-prompt`. Only these are used from now on, and
`PRELOOP_CONFIRM` is checked before any Preloop command.

## F10 — Host-environment fact: AV terminates TLS to claude.ai

Discovered while building the governed image (`curl` exit 60 inside the container).
Measured from a throwaway container on this host:

| Host | Certificate issuer seen from a container |
|---|---|
| `claude.ai` | **`O = AO Kaspersky Lab, CN = Kaspersky Anti-Virus Personal Root Certificate`** |
| `preloop.ai` | `Let's Encrypt` |
| `github.com` | `Sectigo` |
| `pypi.org` | `GlobalSign` |

Kaspersky performs selective TLS interception: the Anthropic host is intercepted, the
others are not. Its root is trusted by the Windows store but not inside containers, which
is why the image build failed until the root was added explicitly
(`docker/ca/kaspersky-root.crt`, thumbprint `C3CD0FA95531B1C530D3D484C859B128AC0B25D7`).

Why this belongs in a governance PoC receipt rather than a build log:

- A local endpoint-security product is a **pre-existing man-in-the-middle on the model
  path**. Any claim of the form "model traffic is governed by, and visible only to,
  Preloop" is false on this host for traffic that leaves it — the AV sees it first.
- This does not affect the governed agent container, whose network has no egress at all.
  It is a property of whatever egresses to Anthropic, i.e. the **gateway** container.
- Whether Kaspersky intercepts the gateway container's egress (WSL2-originated traffic)
  as well as Windows-process traffic is **not yet measured**. It is recorded as an open
  question for the N7 bypass inventory, not assumed either way.
- Adding the root to the image is a trust decision, stated here explicitly: the PoC image
  trusts a locally installed interception CA in order to install Claude Code at all.

## F11 — Model pin is a precondition for credential resolution (NOT a platform gap)

**This finding replaces an earlier, wrong conclusion.** The first diagnosis recorded here
claimed Preloop could not extract Claude Code's OAuth credential on Linux, because the
container failed where the Windows host succeeded. That was a correlation, not the cause.
Reading the upstream source settled it.

### Root cause

`parseClaudeManagedGatewayUpstream` (`cli/internal/cmd/agents_openclaw.go:2237`) resolves the
model *first* and returns early when it cannot:

```go
modelRef = env ANTHROPIC_MODEL  ->  settings.json "model"  ->  resolveClaudeRecentModelRef()
if modelRef == "" { return nil, nil }          // bails here
apiKey, _ := resolveClaudeAuthToken(document)  // credential resolution is the NEXT line
```

With a nil upstream, `applySelectedModelToUpstream`
(`cli/internal/cmd/agents_model_picker.go:312`) constructs a stub carrying only
`ManagedModelAlias`, and `CanRouteThroughGateway()` (`agents_openclaw.go:428`) requires
`ProviderName`, `ModelIdentifier` **and** a credential, so it returns false — producing the
"Could not resolve credentials…" note. That is why passing `--model` did not help: the flag
injects an alias *after* the resolver has already given up, and carries no provider or
credential with it.

- **Host succeeded** because it had session history: "Detected Claude Code's recent upstream
  model as claude-opus-5."
- **Container failed** because its `settings.json` was `{}` and it had never run a session,
  so all three model sources were empty.

### Verification

Setting `"model": "sonnet"` in the container's `~/.claude/settings.json` and re-running the
same dry-run, with nothing else changed:

```
Note: Resolved Claude Code model selector "sonnet" to current Anthropic model anthropic/claude-sonnet-4-5.
Note: Resolved Claude Code OAuth credentials from /home/agent/.claude/.credentials.json.
Note: Model traffic will route through Preloop using anthropic/claude-sonnet-4-5.
```

It resolved the **container's own** credential file, not the host's. Plan A is not blocked.

Ruled out as causes by measurement, not assumption: token format (both `sk-ant-oat01-`,
len 108), credential file schema (identical), `HOME`/uid/permissions (correct), missing
`~/.claude.json` (present), stale account models (registry emptied), and platform
(`resolveClaudeCredentialFileToken` at `agents_openclaw.go:3089` reads
`$HOME/.claude/.credentials.json` on every OS; only the macOS keychain path is
platform-gated).

### What this means for #278

A fresh governed runtime needs an **explicit model pin in its own config** before onboarding
can wire gateway routing. This is a real integration precondition worth recording: a
container image built to be credential-free and history-free hits it by construction,
while a developer laptop never does. It is configuration, not an adapter.

### Incident residue cleaned before the test

The host onboarding had left three model entries in the Preloop account
(`Claude Code anthropic/claude-fable-5-1`, `…/claude-sonnet-5`, `…/claude-haiku-4-5-20251001`),
all `credential_type: oauth_anthropic_claude_code` — i.e. still holding credentials derived
from the **host** login, despite the offboard. The first container dry-run proposed reusing
one of them ("reusing the credential already stored in your Preloop account"), which would
have re-created F8 through the back door. They were deleted
(`DELETE /api/v1/ai-models/{id}` -> 204 x3, registry now empty) before any onboarding was
applied. Offboarding an agent does **not** by itself remove model entries that carry its
captured credential — worth recording as a governance-lifecycle observation.

## F12 — Plan A preflight PASSED: container-minted credential does not disturb the host

The question F8 could not answer — whether Preloop taking custody of a *container-minted*
subscription token would perturb the operator's separate host session — was tested directly.

Protocol: baseline the host credential, onboard only inside the container, force repeated
gateway round-trips, re-measure the host.

| Measurement | Baseline (before container onboarding) | After onboarding + 4 gateway round-trips |
|---|---|---|
| Host `~/.claude/.credentials.json` sha256 (first 16) | `3cf7189cc872dd22` | `3cf7189cc872dd22` (unchanged) |
| Host credential mtime | `17:26:18` | `17:26:18` (unchanged) |
| Host `claude auth status` → `loggedIn` | `true` | `true` |
| Host live model call | — | `HOST_OK` |
| Host `~/.claude/settings.json` | 4 keys, no Preloop entries | identical |
| Container credential sha256 (first 16) | — | `ef30dfd483ba7c2a` (distinct lineage) |

Container-side results: onboarding's own live validation returned
`round-trip OK, model=anthropic/claude-sonnet-4-5, latency=2.9s`, and three further
`claude -p` calls each returned `GW_OK`. Because the container has **no egress**, those
calls can only have traversed the Preloop gateway.

Conclusion, stated at the width the evidence supports: **the failure mode in F8 was custody
of the host's credential file, not sharing one account across runtimes.** A separately minted
login in an isolated HOME, onboarded only inside the container, left the host session intact
across repeated gateway traffic. This does not prove the two lineages can never interact —
a longer soak or a refresh-token rotation on the host side was not exercised — but the
specific interference F8 exhibited did not reproduce.

Container configuration written by onboarding (host equivalent stayed clean):

```
env.ANTHROPIC_BASE_URL   = http://console/anthropic
env.ANTHROPIC_API_KEY    = agt_… (Preloop gateway key, not an Anthropic key)
env.ANTHROPIC_MODEL      = sonnet
hooks.PreToolUse         = preloop agents permission-hook --source claude_code
```

§4.1's requirement that "no direct provider credential is required inside the governed agent
path" is satisfied literally here: the only credential in the agent's environment is a
Preloop gateway key.

## F13 — §4.1 routing PROVEN; §4.1 attribution only PARTIAL

### Routing: proven, two independent ways

Conductor ran inside the governed container and returned `GATEWAY_ROUNDTRIP_OK`
(4,026 tokens). Two independent confirmations that the traffic went through Preloop:

1. **Structural.** The agent container's only network is `internal: true` with no default
   route, so no other path to a model exists (see `evidence/n7-network-isolation.txt`).
2. **Observed.** Both hops logged the requests:

```
console  172.19.0.3 -> "POST /anthropic/v1/messages?beta=true" 200   claude-cli/2.1.277 … agent-sdk/0.2.157
gateway  172.18.0.9 -> "POST /anthropic/v1/messages?beta=true" 200
```

The agent's environment contains no Anthropic credential — only the Preloop gateway key.

### Attribution: incomplete, and that is a finding, not a footnote

§4.1's acceptance criterion asks that the request "appears in Preloop gateway/session/cost
attribution". Measured against `/api/v1/account/gateway-usage`:

| Traffic | Gateway access log | Usage row |
|---|---|---|
| Onboarding live validation (09:04) | yes | **yes** (`status 200`, `src=claude_code`) |
| Synthetic `curl` probes, 4 of them | yes | **yes** (counted in summary) |
| Claude Code / Conductor runs (09:06–09:09, ~9 POSTs, all 200) | yes | **no rows at all** |

A controlled before/after around one Conductor run: `total_requests` 3 → 3, tokens 156 → 156,
while the run itself reported 4,026 tokens.

Ruled out by experiment:

- **Streaming.** `stream:false` and `stream:true` probes each produced a row.
- **The `?beta=true` query Claude Code uses.** A probe with it produced a row.
- **Credential.** The probes used the same `agt_…` gateway key from the agent's own config.
- **Status code.** A later controlled run settled this: one `claude -p` call logged both a
  `429` and a `200` at the gateway, and the usage summary stayed at
  `total=6 success=2 failed=4` across it. Neither outcome was recorded.

**The discriminator is the client, not the request.** Requests issued by `curl` and by the
Preloop CLI's own live validation are recorded; requests issued by the agent runtime
(`claude-cli/2.1.277 … agent-sdk/0.2.157`) are not, whatever their outcome. For a governance
receipt this is the worst arrangement available: the traffic that is missing from attribution
is precisely the governed workload's own traffic.

The two surfaces also disagree — `gateway-usage/summary` counted 6 requests (successes plus
failures) where `gateway-usage/search` listed 2 (successes only) — so "appears in attribution"
additionally depends on which surface is asked. The underlying cause of the agent-client gap
is not established here.

Consequence for the receipt: **governance of the model path is real (the traffic cannot avoid
the gateway), but cost/usage attribution cannot be relied on as evidence for gating.** This
directly supports the issue's §6 rule that the Gate must consume structured Conductor outputs
rather than observability queries — here, the observability surface is demonstrably lossy.

### Two side observations

- **TLS interception is intermittent, not constant.** Exactly one
  `CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain` appears in the
  gateway log for the whole session (09:04:20), and the gateway's retry then succeeded. Every
  later upstream call verified normally. This revises F10's open question: Kaspersky did
  intercept the gateway container's egress at least once, and stopped doing so afterwards
  (the operator added an exception around that time). One observation, not a pattern.
- **There is no account-level rate limit.** An earlier note here claimed subscription
  throttling was active because synthetic probes returned `429 rate_limit_error`. That was
  wrong, and the reviewer's objection was the right one: the container and the operator's
  own session share one account, so an account-wide limit would have stopped both. Retested
  directly — a real `claude -p` call through the gateway returned `LIMIT_CHECK_OK`, with the
  gateway logging one `429` followed by a `200`. The 429s are transient upstream responses
  that the real client retries through; the synthetic probes simply did not retry. Model-heavy
  testing is **not** blocked.

### F13a — the attribution gap is an implementation gap, not a configuration switch

The reviewer's hypothesis was that an option might simply be off. Traced end to end; it is not.

**Database ground truth** (queried directly in Postgres, bypassing both usage APIs):

```sql
select endpoint, status_code, action_type, count(*) from api_usage
where endpoint like '%/anthropic/%' group by 1,2,3;

 /anthropic/v1/messages | 429 | model_gateway |  8
 /anthropic/v1/messages | 200 | model_gateway |  2
 /anthropic/v1/messages | 502 | model_gateway |  1
```

11 rows, against **38** `POST /anthropic/v1/messages` requests in the gateway's own access
log. The rows are not written; they are not merely hidden by an API filter. The newest
`200` row is 09:04:23 — the onboarding validation — and every agent-issued success after it
recorded nothing.

**Code path** (`preloop/services/`):

- `anthropic_gateway.py:110` — a streaming request returns
  `GatewayStreamingResponse(..., on_complete=service.flush_deferred_stream_record)`.
- `openai_gateway.py:5862` — on a successful passthrough stream the record is **stashed**
  via `_defer_stream_record(...)`, unconditionally, with `status_code=200`.
- `gateway_streaming.py:114` — `stream_response` runs the callback in a `finally`, shielded,
  and on failure logs `"Deferred gateway stream recording failed after body flush"`.

So there is no feature flag in this path: the code intends to record, and it reports its own
failures. **Zero** occurrences of that warning appear in the gateway log, yet the rows are
absent — so the deferred flush is not erroring, it is not producing a row. Why the last step
does not land is not established here; settling it would need instrumentation inside the
gateway process, which is out of scope for this PoC.

Also ruled out along the way:

- **nginx.** Pointing the agent straight at `http://gateway:8000/anthropic`, bypassing the
  console proxy entirely, recorded nothing either (`11 2 9` before and after).
- **`MODEL_GATEWAY_*` settings.** The ones that exist govern content capture, indexing,
  preview size and retries — none gate `ApiUsage` writes.

What this means for #278 is unchanged and is the point worth carrying into the receipt: the
model path is genuinely governed, and its usage/cost attribution is not trustworthy as
gating evidence on this version.

## F14 — §4.2 PROVEN and N1 CONFIRMED; governance decisions are log-only

### Setup

A disposable MCP tool service (`agentstack-toolsvc`, FastMCP streamable-HTTP) exposing
`write_marker` — a tool whose effect is externally observable as a file — and a read-only
`list_markers`. It sits on `agentstack-toolnet` (`internal: true`); **the agent container is not
a member**, so the only route from agent to tool is through Preloop:

```
agent (agentstack-governed) --/mcp/v1--> preloop api --> toolsvc (agentstack-toolnet)
agent -> toolsvc directly: http=000, curl_exit=6   (cannot resolve)
```

Registered with `POST /api/v1/mcp-servers`; Preloop discovered both tools.

### §4.2 allow path — PROVEN

A Conductor workflow (`workflows/probes/p42-mcp-governed.yaml`, the §4.2 config shape from
the issue) ran in the container and the agent called the tool through Preloop. The
**underlying effect actually happened**: `allow-path.txt` appeared on the host bind mount,
and `list_markers` returned it. Preloop logged
`Tool write_marker executed successfully on external server`.

One wiring correction worth recording: `setting_sources: [user]` loads the settings tier but
does **not** hand Claude Code's MCP servers to the SDK. The first attempt failed with
*"'write_marker' and 'list_markers' are not available in the current toolset"*. Declaring
`runtime.mcp_servers` in the workflow — exactly the shape §4.2 specifies — is what attaches
them. So §4.2 is config-only, but the config has to be in the workflow, not inherited.

### N1 deny — CONFIRMED

`policy/n1-deny.yaml` denies `write_marker` (condition `true` → `deny`). Re-running the same
workflow:

```
Policy evaluation for 'write_marker': found 1 access rules
Rule matched: N1 control — deny every write_marker call -> action=deny
Policy evaluation for 'write_marker': action=deny, reason=N1 control — deny every write_marker call
```

| Check | Result |
|---|---|
| marker files on the host bind mount | **0** |
| marker files inside the tool container | **0** |
| allowed `list_markers` in the same run | reached the external server normally |

The deny prevented the **underlying effect**, not merely the agent's report of it — which is
exactly what N1 asks. The allowed tool in the same run still worked, so this is policy
discrimination, not an outage.

### The governance-observability catch

The decision is real but **only exists in the API container's process log**. Checked directly
in Postgres after the denied call:

- `audit_log` — no row for the tool decision (only `model_gateway_request` rows)
- `runtime_session_activity` — only `model_gateway_call` rows, none for MCP tools
- `/api/v1/audit-logs`, `/api/v1/tool-calls` — 404 (not present in this version)

This matters for §6. The issue expects `Preloop approval/policy fact = governance
observation`, and the Gate's `governance` input was designed to be a *query* against the
control plane (`gate/governance_probe.py`). On this version there is nothing queryable to
read: a deny is enforced but not exposed as a retrievable governance record. Together with
F13/F13a (model usage attribution missing for agent traffic), the pattern is consistent —
**Preloop enforces reliably and reports partially**. A Gate that consumed Preloop's APIs as
evidence would see neither the denied tool call nor most of the model calls.

## F15 — MLflow cannot distinguish a denied tool call from an executed one

Asked directly: does the governance decision that F14 found missing from Preloop's queryable
surfaces at least show up in MLflow? It does not.

Comparing the `write_marker` tool span from the allow run and the deny run, both ingested
from the governed container:

| Span attribute | ALLOW run (`b050b42f`) | DENY run (`65afc0ee`) |
|---|---|---|
| `gen_ai.tool.name` | `mcp__preloop__write_marker` | `mcp__preloop__write_marker` |
| `gen_ai.operation.name` | `execute_tool` | `execute_tool` |
| `mlflow.spanType` | `TOOL` | `TOOL` |
| span `status` | `STATUS_CODE_UNSET` | `STATUS_CODE_UNSET` |
| `events` | `[]` | `[]` |

The span sets are otherwise identical too — both runs produce `invoke_workflow`,
`invoke_agent`, `execute_tool mcp__preloop__write_marker`,
`execute_tool mcp__preloop__list_markers`, `execute_tool StructuredOutput`. Nothing in the
trace says the call was refused, and nothing says the file was never written.

A third run with the issue's §4.3 content-capture switch enabled
(`OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_ONLY`) changed nothing: same
attributes, still no events, no tool arguments, no tool result. So this is not a matter of
turning capture on — §4.3's content-capture measurement, for tool spans on this provider,
comes back **negative**.

### Why this is one of the more load-bearing findings

The issue states the rule up front:

> MLflow MUST NOT become the workflow source of truth. … A critical Gate must not depend on
> "query MLflow and see whether something probably happened."

This is the direct evidence for it. Had the Gate been allowed to derive `governance` from
observability, it would read an executed tool call and a denied one as the same event, and a
run where the effect was blocked would be indistinguishable from one where it happened. The
prohibition is not stylistic; on this stack the observability surface genuinely cannot carry
that distinction.

Taken with F13/F13a and F14, the evidence picture on this stack is consistent:

| Surface | Model calls | Tool policy decisions |
|---|---|---|
| Actually enforced | yes | yes (N1 confirmed) |
| Preloop queryable API | partial (agent traffic missing) | no |
| Preloop process logs | yes | yes |
| MLflow traces | yes (spans present) | present but indistinguishable |

Enforcement is trustworthy; **retrievable evidence is not**. The Gate must therefore take
governance facts from the execution path itself — a structured Conductor step output — not
from either observability backend. `gate/governance_probe.py` as originally written (an HTTP
query against the control plane) is refuted by this and needs redesign.

## F16 — The deny IS in Conductor's own event stream; only the OTel export drops it

F15 established that neither Preloop's queryable APIs nor MLflow can tell an allowed tool
call from a denied one. That invited the conclusion that the information does not exist
outside process logs, and therefore that new instrumentation (an MCP-boundary telemetry
wrapper) would be needed. **That conclusion is wrong.** Conductor already has it.

From the run event logs, same tool, two runs:

```json
ALLOW  {"type":"agent_tool_complete","data":{"tool_name":"mcp__preloop__write_marker",
        "result":"{\"result\":\"wrote /markers/allow-path.txt\"}"}}

DENY   {"type":"agent_tool_complete","data":{"tool_name":"mcp__preloop__write_marker",
        "result":"[{'type': 'text', 'text': 'Access denied: N1 control — deny every write_marker call'}]"}}
```

The denial is verbatim, including the matched rule's description. Conductor also records the
arguments (`agent_tool_start` → `{"name": "deny-path"}`).

So the gap is narrower and more precise than "the stack cannot see denies":

| Layer | Has the allow/deny distinction? |
|---|---|
| Preloop enforcement | yes (and it is the authority) |
| Preloop process log | yes |
| Preloop queryable API | no |
| **Conductor event stream** | **yes, verbatim** |
| Conductor OTel spans → any backend | **no** — dropped at export |
| MLflow | no (receives spans that never carried it) |

This matches Conductor's documented behavior: argument values and result payloads are
deliberately excluded from MCP step event payloads on the span path (a secrets-redaction
decision), and the §4.3 content-capture switch does not re-enable them for tool spans (F15).

### Consequence for the Gate — no adapter required

§6 says the Gate must consume observed structured outputs from the execution path, not
observability queries. That is directly satisfiable: the governance fact is already in
Conductor's own event log, which is Conductor's own artifact.

Measured, because it decides whether this is usable in-run rather than post-hoc: the event
log is written **incrementally**, not flushed at the end. Line counts sampled while a run was
still active: `4 → 4 → 4 → 12 → 12 → 18 → 22 → 31`. A later `type: script` step in the same
workflow can therefore read it and emit a deterministic governance evidence object while the
workflow is still running.

This keeps the disposition at `COMPOSES_CONFIG_ONLY` for the governance-evidence path: no new
component, no second lifecycle, no policy semantics re-implemented outside Preloop.
`gate/governance_probe.py` gets rewritten from "HTTP query against the control plane" to
"read Conductor's own event stream", which is a change of source, not a new runtime.

### What a telemetry wrapper would and would not buy

A wrapper at the MCP boundary that stamped `policy.decision=deny` / `tool.executed=false`
onto spans would make Phoenix, Langfuse or MLflow able to *display* the distinction. It would
not improve the Gate, which does not need it. It carries two costs worth stating before
anyone builds one:

1. It derives a governance verdict by parsing a tool-result string (`"Access denied: …"`).
   §3 assigns policy semantics to Preloop; a component that interprets them elsewhere is
   duplicating that ownership, which is the `COMPOSES_WITH_SEMANTIC_DUPLICATION` warning
   shape, not a transport shim.
2. It is a custom component in a PoC whose headline question is whether config-only wiring
   suffices. Building it for observability convenience would move the receipt off
   `COMPOSES_CONFIG_ONLY` for a benefit that the Gate does not require.

If it is built anyway, the honest framing is: telemetry enrichment for debugging, explicitly
not an evidence path, and recorded as a thin adapter with no authority.

## F17 — Vertical slice runs green, and N1/N3/N4/N5 all confirmed live

All four components participate in one Conductor graph
(`workflows/slice.yaml`), running inside the governed container.

### Baseline PASS run (`run_id 4a0c82d4`, 100s, 54,201 tokens)

```json
{"decision":"PASS","reason":"required evidence satisfied",
 "tests_exit_code":0,"governance_status":"APPROVED","governed_calls":1}
```

Observable outcomes, not claims:

- the agent edited the fixture (`text = text.strip("-")`) and pytest went 2 failed → **4/4 passing**
- the governed MCP call produced its real effect: `slice-cadp-278-vertical-slice.txt` appeared
- MLflow received the full hierarchy §8 asks for:

```
invoke_workflow cadp-278-vertical-slice
  invoke_agent research    → Read, Bash, Read, StructuredOutput
  invoke_agent implement   → Read, Edit, mcp__preloop__write_marker, StructuredOutput
  invoke_agent test
  invoke_agent review      → Read, Read, StructuredOutput
  invoke_agent governance / collect_evidence / gate / gate_pass
```

### Negative controls

| Control | Setup | Result | Gate reason |
|---|---|---|---|
| **N1** deny | `policy/n1-deny.yaml` applied; tests passing, evidence complete | `BLOCK`, `governance_status=DENIED`, **0 marker files** | `governance denied the governed action` |
| **N3** missing evidence | `artifact.sha256` removed from `collect_evidence`; tests passing, governance APPROVED | `BLOCK` | `required evidence missing or wrong-typed: artifact.sha256` |
| **N4** failed test | implement told not to fix the code; governance APPROVED | `RETRY` (never PASS) | `tests did not pass` |
| **N5** MLflow down | `agentstack-mlflow` stopped mid-PoC | `PASS` — **identical to the baseline** | `required evidence satisfied` |

Each control isolates one variable. N1 and N3 both BLOCK while tests are green, and N4
withholds PASS while governance is fine, so the Gate's reason is attributable in every case
rather than incidental.

N5 in detail, because §6 asks specifically that observability loss be visible without
changing correctness. Conductor reported the loss loudly:

```
Failed to export span batch due to timeout, max retries or shutdown.
Transient error ... Failed to resolve 'mlflow' ... retrying in 1.00s
OpenTelemetry export for run abf32e78 did not finish within 5.0s; continuing
teardown, some spans may be lost
```

and still returned `PASS` with the same evidence. Observability is best-effort here in the
way the issue requires: loud when it fails, powerless over the verdict.

### What this settles about the Gate

The Gate is a `type: script` step, a pure stdin→stdout function. It made four different
decisions across these runs purely from the evidence object handed to it, never querying
MLflow or Preloop. RETRY is a Conductor route, not Gate state. `§11`'s Gate criteria —
stateless, structured evidence, no inferred PASS, MLflow not a source of truth — are met by
demonstration rather than by construction.

## F18 — N6 CONFIRMED: no silent bypass, tested with a direct path deliberately available

N6 asks that a governed action not silently fall back to the direct provider when Preloop is
unavailable. Run in two parts, because the obvious version of this test proves almost nothing.

### N6a — governed posture (egress 0), gateway stopped

| Probe | Result |
|---|---|
| `POST console/anthropic/v1/messages` | `502` |
| `https://api.anthropic.com/v1/messages` | `curl_exit=6` (unresolvable) |
| Slice run | **failed closed** — `ProviderError: API Error: 502 Bad Gateway … check your inference gateway (console)` |

The workflow produced no Gate decision at all, so there was no PASS to bypass into. But with
no egress this outcome is structural, not behavioural: the client *could not* bypass. That is
a weak proof, so it was followed by the real one.

### N6b — bypass deliberately made possible

The agent was attached to the throwaway `agentstack-provision` network **while the gateway
stayed down**, so a direct path existed:

| Precondition | State |
|---|---|
| `api.anthropic.com` reachable from the agent | yes — `http=405`, resolves to `160.79.104.10` |
| Preloop gateway | down — `502` |
| Anthropic OAuth credential inside the container | **still present** (`~/.claude/.credentials.json`) |

Every ingredient for a silent fallback was in place. Sampling the agent's outbound sockets
every 4s for the duration of a model call:

```
t=1..10 (x4s):  172.19.0.5:80        <- console (the Preloop path), every sample
                (never 160.79.104.10)
```

The only destination for the entire call was the configured gateway. Claude Code retried the
governed endpoint and never attempted the direct provider, despite holding a credential that
would have worked there.

**N6: CONFIRMED.** Not merely "bypass was impossible" but "bypass was possible and did not
happen".

### Operational note

The failure mode differs by caller. Inside Conductor the outage surfaced promptly as a
`ProviderError` naming the gateway. A bare `claude -p` instead **hung** and was killed at
150s (`exit 124`) with no output — it keeps retrying rather than failing fast. For a workflow
that is the better of the two behaviours, but an operator watching a raw CLI sees a stall,
not an error.

## F19 — N7: native tools are NOT governed; the provider bypasses the permission system

N7 asks for the inventory of action paths that do not traverse Preloop, and forbids claiming
"all agent actions governed" until it is closed. It is now closed, and the answer is no.

| Action path | Traverses Preloop? | Mechanism |
|---|---|---|
| Model inference | **yes** | `ANTHROPIC_BASE_URL` → gateway (F13, F18) |
| MCP tools declared in `runtime.mcp_servers` | **yes** | Preloop `/mcp/v1`; deny blocks the real effect (F14) |
| Undeclared MCP servers | cannot attach | provider forces `strict_mcp_config=True` |
| Native `Read` / `Write` / `Edit` / `Bash` / … | **NO** | `permission_mode="bypassPermissions"` |

### Measured

A run exercising a file read, two shell commands, a file write and one MCP tool produced:

```
Conductor tool events : Read, Bash, Bash, mcp__preloop__list_markers, StructuredOutput
PreToolUse hook log   : 0 invocations
```

The hook was temporarily wrapped in a pass-through logger to observe it, then restored. A
bare `claude -p` in the same container also fired it zero times.

### Mechanism, from upstream source

`conductor/providers/claude_agent_sdk.py:1697`:

```python
# Omitted -> default claude_code preset (filesystem/bash/web).
return _DEFAULT_TOOL_PRESET, "bypassPermissions"
```

and at the SDK call site, two lines above `strict_mcp_config=True`:

```python
# ... permission_mode bypasses approval for whatever they expose.
```

So the hook is not failing — the permission system it hangs off is switched off by the
provider whenever an agent omits `tools:`, which is the documented way to get the built-in
tools at all.

### The trade this provider forces

```
omit `tools:`   -> full claude_code preset, permission system bypassed
`tools: []`     -> no bypass, and no built-in tools either (cannot read or edit the repo)
```

There is no setting that keeps the built-in tools *and* submits them to the hook; a
narrowing per-server `tools:` filter is separately refused on this provider. Preloop's
documented headless alternative (`claude -p --permission-prompt-tool
mcp__preloop__permission_prompt`) is not reachable from Conductor, which drives the SDK
rather than the CLI flag surface — and when tried directly in this container it failed with
*"MCP tool … not found. Available MCP tools: none"*.

### Consequence for the receipt

This is the single largest qualification on the whole composition. In this topology an agent
can read and write any file its working directory exposes and run arbitrary shell commands
with **no Preloop mediation at all**, while still being unable to reach the network. What
bounds those actions here is the container and its empty egress — not the governance layer.

It also sharpens the design-correction comment's capability matrix. That comment scored
Claude Code as `native-tool hook: ✅ PreToolUse` and placed it at tier T3/T4 as the cheapest
path to strong assurance. That scoring holds for Claude Code **as a CLI**; it does not hold
for Claude Code **driven by Conductor's `claude-agent-sdk` provider**, which is the topology
the PoC actually needs. The axis that matters is not "does the agent support a hook" but
"does the runtime that drives it leave the permission system on".

## F20 — N2 CONFIRMED: the approval path resumes the same run, with no second orchestrator

`policy/n2-approval.yaml` set `write_marker` to `require_approval` against the default
approval workflow (300s timeout, 1 approval, human).

### Sequence, observed

| Time | State |
|---|---|
| t≈0 | slice launched; Conductor reaches `implement` |
| t≈110s | the agent's `write_marker` call blocks; a pending approval appears in Preloop |
| t≈110–170s | **Conductor is still inside the `implement` step of the same run** — no checkpoint, no resume, no second process |
| t≈170s | approval granted |
| t≈180s | tool executes, marker file appears |
| t≈250s | `implement → test → review → governance → gate → gate_pass` |
| final | `{"decision":"PASS","governance_status":"APPROVED","governed_calls":1}` |

**N2's actual question — "approved call resumes/completes without a second workflow owner" —
answers cleanly: yes.** Conductor never handed off ownership. The approval blocked inside a
tool call; the workflow neither checkpointed nor restarted, and Preloop Flow took no part.
The approval mechanism is expressed entirely in Preloop policy plus one unchanged Conductor
workflow, so it stays inside `COMPOSES_CONFIG_ONLY`.

### Approval identity and Gate correlation — the part the issue asks to record

The approval record is rich on the governance side and empty on the correlation side:

```
id                     85173139-7824-416e-aa6d-3bb73975742a
tool_name              write_marker
tool_args              {'name': 'slice-cadp-278-vertical-slice'}
status                 approved      decided_by_human   True
requested_at/resolved_at/expires_at   present
rule_context           {'source':'tool_access_rule','decision':'require_approval','rule_id':…}
risk_level             danger        was_bypassed       False
execution_id           null          ← no link to the Conductor run
```

There is no `run_id`, no trace id, and `execution_id` is null. **The approval cannot be joined
to the Conductor run through any native identifier.** The only thing tying them together in
this PoC is the tool argument, which the workflow happened to template from the workflow name
(`slice-cadp-278-vertical-slice`) — a coincidence of prompt design, not a correlation
mechanism. §6 asked which cross-system joins are native and which need custom metadata: this
one is **neither native nor currently carried**, and would need a deliberate convention
(e.g. stamping `CONDUCTOR_SELF_RUN_ID` into every governed tool argument) to become joinable.

The Gate is unaffected, because F16 already moved governance evidence to Conductor's own
event stream, which records the approved call's result in-run. But any *audit* that wants to
answer "which run was this approval for" cannot do so from Preloop's record alone.

### Two operational defects found while running this

1. **`preloop approvals approve <id>` is broken in 0.15.0.** It posts an empty body and the
   API rejects it:
   `422 {"loc":["body","approved"],"msg":"Field required"}`. Approval had to be issued
   directly: `POST /api/v1/approval-requests/{id}/approve {"approved": true}`. The CLI also
   prints a truncated id (`85173139-782`) that its own API then rejects as an invalid UUID.
2. **An earlier `request_approval` expired unnoticed.** During the baseline slice the agent
   voluntarily called Preloop's built-in `request_approval` tool; that request sat pending
   and reached `status: expired` with `decided_by_human: False`. The workflow had already
   completed as PASS, because that voluntary call was not the governed path. Worth noting
   that a model *asking* for approval and a policy *requiring* it are different mechanisms,
   and only the second one blocks.

## F21 — WP §5.1 re-measured: two artifacts, different durability; the non-enrollment basis needs restating

The CADP workflow-plane TD (WP §5.1, measured 2026-09-07 on run `24919dde`) says:

> Conductor's run receipts are local-file grade: an `events.jsonl` under `TMPDIR`, keyed by an
> 8-hex `run_id`; the run record is **deleted on normal completion**; a checkpoint is written
> only on failure by default.

Re-measured on **v0.1.37**. The description conflates two artifacts that in this version have
different contents and different lifetimes.

### The two artifacts

| | `TMPDIR/conductor/*.events.jsonl` | `~/.conductor/runs/terminal/<run_id>.json` |
|---|---|---|
| contents | every step, tool call, arguments and result, verbatim | `status`, workflow `output`, started/ended, tokens, cost, `error_type`, pointer to the event log |
| written | incrementally during the run | at terminal state |
| after normal completion | **present** | **present** |
| after the container is recreated | **all 19 lost** | **all 19 survived** |

A controlled run confirmed the creation side: one successful run took the counts from
18 → 19 for both artifacts, and the PID file under `~/.conductor/runs/` (which exists only
while a run is live) was cleared.

The durable record for run `4a0c82d4` is a real structured receipt of the workflow's result:

```json
{"run_id":"4a0c82d4","workflow_name":"slice","status":"success",
 "output":{"decision":"PASS","governance_status":"APPROVED","governed_calls":1},
 "total_tokens":54201,"total_cost_usd":0.1456,
 "event_log_path":"/tmp/conductor/conductor-…-4a0c82d4.events.jsonl"}
```

The checkpoint half of WP §5.1 holds, with a refinement: one checkpoint exists across this
whole PoC, from the single genuine `ProviderError`. Runs ending at an explicit
`type: terminate` with `status: failed` wrote none — Conductor documents that explicit
terminations skip the on-failure checkpoint. "Only on failure" is right; "every failure" is not.

### Effect on WP §5.2's refusal

§5.2 refuses to enrol a Conductor principal in the run profile, on three grounds:

| Ground stated in §5.2 | Status on v0.1.37 |
|---|---|
| "a TMPDIR file deleted on success" | **does not reproduce** — the event log is not deleted |
| "after a normal completion there is no receipt at all" | **does not reproduce** — the terminal record persists, with status and output |
| "there is no target-authoritative `WORK_START` outcome" | **holds** |

**The refusal stands. Its stated basis does not.** Two of three grounds are stale, and the one
that survives is the only one that was ever constitutional rather than incidental: both
artifacts are Conductor reporting on *itself*. Durability does not convert a self-report into
a target-authoritative receipt, which is the whole point K7 grading exists to enforce.

This matters practically. As written, §5.2 invites a future reader who re-measures to conclude
the refusal is obsolete — the two falsifiable grounds are exactly the ones they would check
first. Restated on the surviving ground alone, the refusal becomes robust to version drift:

> No orchestrator-authored run record, however durable or structured, can grade a run scope by
> K7, because K7 requires a receipt returned by the target of the effect, and an orchestrator
> is not that target.

### §5.3's revisit condition, re-scored

| Required property | v0.1.37 |
|---|---|
| durable across normal completion | **satisfied** (terminal record) |
| readable by the Reconciler after restart | **satisfied** (`$HOME`, survived container recreation) |
| correlatable to a Platform-sealed `WORK_START` effect_id by a target-returned binding | **not satisfied** |

Two of three now hold. The remaining gap is categorical, not incremental — it cannot be closed
by any improvement to Conductor's own record-keeping.

### A weakness this exposes in the PoC's own design

`gate/governance_probe.py` reads the **event log** — the ephemeral artifact. That is sound
in-run, because the probe executes as a step of the same run while the file is live, and the
Gate's decision is made from it at that moment. But it means the PoC's governance evidence is
**not durably auditable after the fact** unless the log is deliberately preserved. It was, by
hand, into `evidence/conductor-events/` (19 files) before the container was recreated — and
recreating the container proved the point by destroying the originals.

The durable terminal record carries the Gate's decision but not the per-tool detail the
governance fact is derived from. So for this stack: **the decision is durable, the evidence
behind it is not.** A deployment that needs after-the-fact audit has to copy the event log out
as part of the run, which is one line of workflow configuration, not an adapter — but it is a
thing that must be deliberately done, and the receipt now says so.

## F22 — N7 CORRECTED: `bypassPermissions` was NOT the cause; Preloop's own onboarding disabled the hook

F19 asserted that Conductor's `permission_mode="bypassPermissions"` was why the Preloop
PreToolUse hook never ran. **That causal claim was wrong.** It was challenged on review, and
the challenge is right on both the documentation and the measurement.

### Why the original claim was wrong

The Agent SDK documents the evaluation order explicitly, and hooks come first:

> **Hooks** — Run hooks first. A hook can deny the call outright or pass it on.
> … `bypassPermissions`: "Hooks still execute and can block operations if needed."
> "Deny rules, explicit `ask` rules, and hooks are evaluated **before the mode check** and can
> still block a tool."

F19's own data already contained the counter-evidence and it was not used: a **bare `claude -p`
run**, with no Conductor and no provider-set permission mode, also produced 0 hook invocations.
A cause specific to Conductor's provider cannot explain that.

### What the cause actually is — isolated by experiment

The observation harness was validated first (the container can append to the log; the wrapper
is present and executable), so "0 invocations" was a real measurement, not an instrumentation
artifact. Then one variable was changed:

| Run | Configuration | Hook invocations |
|---|---|---|
| A | exactly as Preloop's onboarding wrote it (`env.CLAUDE_CODE_SIMPLE = "1"`) | **0** |
| B | identical, with **only** `CLAUDE_CODE_SIMPLE` removed | **1**, with full payload |
| C | same removal, run through **Conductor** | **6**, payload shows `permission_mode: bypassPermissions` |

`CLAUDE_CODE_SIMPLE=1` is the environment form of Claude Code's `--bare` mode, documented as
"Minimal mode: **skip hooks**, LSP, plugin sync…". **Preloop's `agents onboard --approvals`
installed a PreToolUse hook and, in the same settings file, set the variable that skips hooks.**

Run C also settles the mechanism question directly: the hook fires under Conductor *while the
payload reports `permission_mode: bypassPermissions`*, exactly as the SDK documents.

### What is still true, restated at the width the evidence supports

Native file and shell tools were **not governed in the measured configuration**. Two
independent, measured contributors:

1. **Hooks were skipped entirely** by `CLAUDE_CODE_SIMPLE=1`, written by Preloop's own onboarding.
2. **With hooks running, the hook allowed the call itself.** Invoked directly with a `Bash`
   event it returns:

   ```json
   {"hookSpecificOutput":{"permissionDecision":"allow",
    "permissionDecisionReason":"Allowed by the agent's own configuration."}}
   ```

   and **zero** `/api/v1/agents/permission-check` requests reached the control plane across the
   entire session. A policy entry `{name: Bash, source: builtin, action: deny}` did not block
   the call, and Preloop logged no policy evaluation for it — only `Created tool config: Bash`
   when the policy was applied.

What remains unestablished, and should not be asserted:

- whether the hook would escalate to Preloop under a non-bypass permission mode
- whether `source: builtin` is the correct policy shape for native-tool rules at all
- whether any Conductor-expressible configuration yields governed native tools

The last one is constrained by a fact that **does** survive from F19: this provider offers only
two tool configurations — omit `tools:` (full preset, `bypassPermissions`) or `tools: []` (no
bypass, no tools). A non-empty explicit tool list is rejected. So a "tools present, mode not
bypass" configuration is not expressible here regardless of what the hook would do with it.

### State left behind

`CLAUDE_CODE_SIMPLE` has been left **removed** from the container's settings — a deliberate
deviation from what onboarding wrote, because leaving it would silently disable the governance
hook. The hook command itself was restored to the unwrapped Preloop binary.

## F23 — Gate evidence binding: three gaps found, all three closed inside Gate rules

Raised on review: N3 and N4 only show that *missing* or *failing* inputs are refused. They do
not show that the Gate refuses evidence belonging to a **different attempt, a different target,
or a different run**. Probed directly, model-free where possible.

### What was found

| Probe | Question | Result before hardening |
|---|---|---|
| **G1** | is `artifact.sha256` bound to the artifact at decision time? | **NO.** A script mutated the file between the test step and the Gate; the Gate returned `PASS` binding digest `4e2c26e6…` while the file on disk was `fb1e9ea9…` |
| **G2** | is governance evidence scoped to the attempt? | **NO.** The probe aggregates every governed call in the run |
| **G3** | does an approval from an earlier attempt satisfy a later one? | **YES, it did.** Attempt 1 approved + attempt 2 performing no governed action at all → `APPROVED` |
| **G4** | does an approval naming a *different target* count? | **YES, it did.** The probe never read `agent_tool_start` arguments |
| **G5** | can evidence from another run leak in? | **No.** A wrong `run_id` yields `UNKNOWN`, fail-closed — this part was already sound |

G1 is the sharpest: `artifact.sha256` was a *record of a past measurement*, not a binding to the
artifact being gated. Anything that wrote the file after the test step — including the `review`
agent, which holds `Edit` — would have gone unnoticed.

G3's direction matters. Aggregating across a run is conservative for *denials* (one denial
poisons the run), but it is permissive for *approvals*: an attempt that performed no governed
action at all inherits the previous attempt's approval.

### The fix, and it stays inside "Gate rules/scripts"

Two additions, no new component, no new lifecycle:

1. **`gate/verify_artifact.py`** — re-measures the artifact immediately before the Gate and
   emits `artifact_matches_tested`. The Gate stays a pure function; the I/O is a separate step.
   `gate.py` now requires `artifact.matches_tested` to be `true` and otherwise returns
   `BLOCK — artifact changed between measurement and decision`.
2. **A binding token for governance.** `governance_probe.py` now takes the tested digest as an
   argument, pairs each `agent_tool_complete` with its `agent_tool_start` arguments, and counts
   only calls that name that digest. `gate.py` requires `governance.bound_to_target`.
   The workflow was restructured so the governed action happens **after** measurement: a new
   `attest` step calls `write_marker` with the tested digest as its name, so the approval is
   evidence about *that artifact in that attempt* rather than about the run in general.

### Verification after hardening

| Probe | Result |
|---|---|
| G1 re-run | `BLOCK — artifact changed between measurement and decision`, with both digests in the output (`fb1e9ea9…` tested vs `5d559cf6…` at decision) |
| G3 re-run | `UNKNOWN` — "1 governed call(s) executed but none named the gated target" |
| G4 re-run | `UNKNOWN` — same |
| control (token genuinely present) | `APPROVED` — "1 governed call(s) executed naming the gated target" |
| **full slice, live** | `PASS` with `governance_bound: true`, `artifact_verified: true`; the marker file is named `4e2c26e6…`, which equals the sha256 of the file on disk |

The end-to-end check is the last row: the governed attestation names the artifact that is
actually on disk at decision time, so the three evidence items (test result, artifact identity,
governance approval) now refer to the same object.

### Residual, stated rather than closed

- **Attempt identity is still implicit.** Binding is by artifact digest, so a retry that produces
  an identical artifact is indistinguishable from the previous attempt. For this fixture that is
  harmless; for a workload where the same artifact can be re-attested it is not, and a real
  attempt counter would be needed.
- **The review verdict is unbound.** `review.verdict` still carries no reference to the artifact
  it reviewed. The same G1-class gap applies to it and was not closed here.
- **Only one file is verified.** `verify_artifact.py` hashes the single fixture module. A real
  target needs a tree digest or an explicit manifest.
- **The token is carried in a tool argument**, which means the agent could in principle attest
  an artifact it did not produce. It cannot forge the *digest* (that comes from the test step's
  own output), but nothing stops it calling `write_marker` with that name without having done
  the work. The attestation proves a governed call happened naming this artifact, not that the
  agent behaved.

### Method note

An earlier attempt to reset the fixture between probes used `git checkout -- .` in a repository
that had been `git init`-ed but never committed, so it silently did nothing and one probe ran
against a tampered file. A baseline commit now exists so resets actually reset.

## F24 — Evidence is recoverable after restart, once preserved deliberately; not all of it is re-derivable

F21 left the PoC with a real weakness: the decision was durable (Conductor's terminal record)
while the evidence behind it was not (the event log lived in TMPDIR and did not survive a
container recreation). Closed and tested.

### The preservation step

`gate/preserve_evidence.py` runs after the Gate and before the terminal steps. It writes the
evidence object and copies the run's event log into `evidence/runs/<run_id>/` on the durable
mount. One workflow step; it owns no state, makes no decision, and changes nothing about the
run — so it stays inside the same "Gate rules/scripts" allowance as the rest.

A live PASS run produced:

```
evidence/runs/630e045b/evidence.json                                      250 bytes
evidence/runs/630e045b/conductor-…-630e045b.events.jsonl               53,541 bytes
```

### The restart experiment

The agent container was recreated, which empties `/tmp` — verified: `0` event logs remained.
Then the decision was re-derived from preserved material alone:

| Check | Result |
|---|---|
| **A.** governance fact re-derived from the preserved event log | `APPROVED`, `bound=True`, `governed=1 denied=0` — identical to the live run |
| **B.** Gate re-run on the preserved evidence object | `PASS — required evidence satisfied` — identical |
| **C.** Conductor's own durable terminal record, written independently | `status=success, decision=PASS, governance=APPROVED` |
| **D.** artifact identity re-checked against the file on the durable mount | `re-verifies: True` |

Three independent records agree, and the artifact still hashes to the digest the decision was
made against.

### The part worth being precise about

B is weaker than it looks. Re-running a pure function over a stored evidence object proves the
record is intact and the function deterministic — it does **not** re-establish the facts. Sorted
by what the preserved material can actually support:

| Evidence item | After restart |
|---|---|
| `governance.status` | **re-derived** from raw events — the strongest item |
| `artifact.sha256` | **re-verifiable** — the artifact is on a durable mount and still matches (D) |
| `artifact.matches_tested` | stored conclusion, but re-checkable via D |
| `tests.exit_code` / `failed` | **stored conclusion** — pytest is not re-run from the record |
| `review.verdict` | **stored conclusion** — a model output, not reproducible even in principle |

So the honest claim is: **the decision is reproducible and its governance fact is re-derivable;
the test result and the review verdict are attestations that have to be trusted or re-run.**
Re-running the tests would require the artifact plus the test suite at that revision, which the
bind mount happens to provide here but which a real deployment would have to pin deliberately
(the test suite is not preserved with the run, only the artifact digest is).

### Residual

- The **test suite** is not preserved alongside the artifact, so `tests.*` cannot be re-derived
  from the record even though the artifact can be re-hashed.
- Preservation is wired on the **PASS path only**. A BLOCK path currently preserves nothing,
  which is backwards for audit — the failures are the interesting ones. That is a two-line
  workflow change, not yet made.
- The preserved copy lives next to the workspace it describes; nothing makes it tamper-evident.
  This is evidence recovery, not evidence integrity, and the receipt should not conflate them.

## F25 — Budget and spend control cannot be relied on here, for three independent reasons

The receipt said model traffic is governed, and it is — routing was proven twice over (F13,
N6). It also implied that the gateway's budget and spend-cap capability is the thing CADP's
EP §B2.3 prerequisite is pointed at. That implication was untested. Tested now, and it does
not hold on this deployment.

### 1. The running build has no budget API at all

`POST /api/v1/budget/policies` and `GET /api/v1/budget/policies` both return `404`, through the
console proxy and against the `api` container directly. The router exists in upstream `main`
(`backend/preloop/api/endpoints/budget.py`, registered in `app.py` at `/api/v1`), but the
running **0.15.0** image does not expose it:

```
budget paths in the running build: NONE     (174 paths total)
```

So budget policies could not be created, let alone enforced. This is version drift between the
source and the released OSS image, not a permission problem.

### 2. Subscription-routed traffic records $0 spend by design

The account's own usage summary, after an entire PoC of model calls:

```json
{"total_requests": 11, "token_usage": {"total_tokens": 156}, "estimated_cost": 0.0,
 "budget": {"monthly_limit_usd": null, "current_spend_usd": 0.0,
            "soft_limit_exceeded": false, "hard_limit_exceeded": false}}
```

`estimated_cost` is `0.0` because the gateway documents exactly this: "Requests routed over
subscription OAuth credentials (Claude Code Max, ChatGPT/Codex) record $0 spend with the
API-equivalent value kept in metadata." A USD hard limit therefore cannot trip on
subscription-routed traffic **even if the budget API were present**. Budgets in this topology
would govern API-key traffic only.

### 3. The counting-unit question resolves the wrong way

The receipt reported "38 gateway requests against 11 usage rows" and left the counting unit
open. It is not a unit mismatch. Measured on a single controlled call:

```
usage rows before: 11
one `claude -p` call through the gateway -> "UNIT_TEST"   (succeeded)
usage rows after:  11
rows in Postgres for the anthropic endpoint in the last 5 minutes: 0
```

And the full composition of every `/anthropic/` usage row ever written in this deployment:

| status | rows | what they were |
|---|---|---|
| `200` | **2** | the onboarding live validation, and one host-side call — neither issued by the agent runtime |
| `429` | 8 | my synthetic `curl` probes |
| `502` | 1 | the single upstream TLS failure |

**Not one successful agent-issued model call produced a usage row.** The 11 rows are entirely
validation, probes and failures. So the earlier framing — "attribution is partial" — was too
generous: for the traffic that matters it is absent, and what is recorded is mostly traffic the
PoC generated while testing the recorder.

### What this means together

Three independent failures, any one of which is sufficient:

| | |
|---|---|
| no budget API in the running build | budgets cannot be configured |
| subscription traffic records $0 | a USD budget could not trip on it if they could |
| agent successes produce no rows | the spend figure a budget would read is not being written |

**Gateway traversal was proven; spend control was not, and on this build could not be.** The
receipt's `EVIDENCE_VISIBILITY / approval-policy: WEAK` entry understates this: it treats the
gap as reporting fidelity, when for budgets it is a missing capability plus a design choice
plus a defect stacked on each other.

This also sharpens the F13a/COMPARISON claim about CADP EP §B2.3. Preloop governs provider
*invocation* — that part is real and proven. It does not follow that it governs provider
*spend*: on this build the three mechanisms that would make spend governable are respectively
absent, inert for subscription credentials, and unfed.
