# #281 findings — common agent execution and quota-based routing

Working log. Measured facts only; each entry states what is and is not established.

---

## Phase 0 — environment fixed

- **RUNBOOK rewritten.** The previous version predated the Preloop install and prescribed the
  F6 project-scope onboarding rule that F9 superseded. Followed as written it would have
  re-created the F8 incident path. See `RUNBOOK.md`.
- **Revisions are now recordable.** Neither workspace was under version control. Baseline
  snapshot: `poc-278 @ 2027dcb`, `research-280 @ ecccc6e`, fixture `@ e41c407`. Secret-bearing
  incident files and the MLflow store are git-ignored. `core.autocrlf` is **off**: with it on, a
  fresh checkout rewrites line endings and changes `sha256(gate.py)`, breaking every manifest
  that pins it.
- **Baseline smoke on the existing path passed** (2026-09-21): isolation intact (no default
  route, egress `000`, MCP `401`), Conductor → Preloop gateway returned `GATEWAY_ROUNDTRIP_OK`,
  gateway logged the POSTs.

### Runtime additions (image rebuilt)

Everything under `/opt`, never `$HOME` (#280: `$HOME` is a volume that pins what is under it).

| Component | Version |
|---|---|
| node | 22.14.0 |
| acpx | 0.18.0 |
| @agentclientprotocol/claude-agent-acp | 0.79.0 |
| @agentclientprotocol/codex-acp | 1.12.0 |
| @openai/codex | 0.155.1 |
| CodexBar CLI | 0.63.0, static musl build (glibc build does not run here, see below) |

Two provisioning traps:

1. The node tarball step failed on `tar -xJ`: `python:3.13-slim-bookworm` has no `xz-utils`.
   Switched to the `.tar.gz` distribution.
2. **CodexBar's glibc build needs `GLIBC_2.38`; Debian bookworm ships 2.36.** It fails at load:
   `version 'GLIBC_2.38' not found`. Switched to the static musl build; it runs (`CodexBar 0.63.0`).
   Image after the switch: `72d6e4cb395e`. Isolation re-verified after recreate.

acpx's built-in profiles launch adapters with `npx -y <adapter>`. With no egress that can only
work if the adapter is already installed; it is, and the built-in profile did start.

---

## Phase 2 — acpx + Claude

### A. Built-in profile, nothing injected → fails closed

`acpx claude exec …` with no extra configuration:

```
Internal error: Failed to refresh OAuth token: another Claude Code process is refreshing it
or exited mid-refresh …
```

This is the settings-isolation behaviour the review cited, measured. acpx's built-in Claude
profile loads project and local settings but **not user settings**, and in this container the
gateway environment and the Preloop PreToolUse hook both live in the user tier. So the session
fell back to the ambient OAuth credential, tried to refresh it, and could not reach the provider
because the runtime has no egress.

- **Safe:** it failed closed; nothing bypassed the gateway.
- **Misleading:** the error blames a concurrent refresh; the real cause is no network.
- **Residue:** the failed refresh left `~/.claude/.oauth_refresh.lock`, which would make later
  OAuth-path runs report the same misleading message. Removed.
- **Credential untouched:** `sha256(.credentials.json)` = `ef30dfd483ba7c2a`, identical to the
  value recorded in F12. The existing Conductor path still worked immediately afterwards.

### B. Built-in profile, gateway env injected explicitly → works through the gateway

Chosen over `ACPX_CLAUDE_INCLUDE_USER_SETTINGS=1`, which would also pull in the rest of the
user tier (the thing F6 was trying to avoid) and would leave "which settings applied" implicit.
Exactly three variables, read from the container's own settings and passed as process env:

```
ANTHROPIC_BASE_URL=http://console/anthropic
ANTHROPIC_API_KEY=agt_…            (Preloop gateway key)
ANTHROPIC_MODEL=sonnet
```

Result: reply `B_OK`, exit 0. Gateway log for the same window: **6 × `200`**, 1 × `404`.

### The 404, and what model actually served

The adapter did **not** honour `ANTHROPIC_MODEL=sonnet`. It requested its own default,
`claude-sonnet-5`. The gateway attempted to auto-register that Claude-family model, hit a
`UniqueViolation` on `uq_managed_agent_ai_model_binding_slot`, and answered
`Requested model not found` (404); later requests in the same session returned 200.

acpx records `model_usage: [{"model": "claude-sonnet-5", totalTokens: 42438}]`. That is the
model the adapter **requested**. The gateway 404'd on exactly that name once, and does not log a
served-model identity for the 200s, so **the served model is not confirmed** — recorded as such,
per the issue's rule that an alias alone does not establish the served model.

Two Preloop 0.15.0 idempotency defects are visible in the same window (both `UniqueViolation`,
one on `uq_runtime_session_account_source`, one on the model-binding slot). Neither blocked the
run.

---

## Phase 3 — does acpx contain native writes? Yes, at the ACP layer

Fixture: an empty workspace; the task is to create `marker.txt`. Each case uses a **fresh named
session** (`sessions new --name p3-<case>`), because acpx's session key is
`(agentCommand, absoluteCwd, optional name)` and carries no account or policy.

| Case | Mode | Permission request recorded | Independent file check |
|---|---|---|---|
| Write tool | `--approve-all` | yes — `kind=edit`, `Write marker.txt`, content `P3` | **created** (control) |
| Write tool | default (`--approve-reads`) | yes — identical request | **absent** |
| Write tool | `--deny-all` | yes — identical request | **absent** |
| shell alternative | default | yes — `kind=execute`, `echo P3 > marker.txt` | **absent** |

Every "absent" case carries the exact request for that write in its transcript, and the approve
control proves the agent was capable of and attempted the same write. So these are refusals, not
runs where nothing was tried — the standard the issue sets for deny evidence.

This is the result #278 could not get. Under Conductor's `claude-agent-sdk` provider, native
Write/Bash ran unmediated in the measured configuration (F19/F22). acpx refuses them at the ACP
permission layer, including the shell route to the same effect.

**What this is not:** it is acpx's own permission policy, not Preloop's. The issue requires
Preloop to own the policy decision and forbids the adapter from becoming a second approval
engine. This establishes that the ACP layer is a place where native actions **can** be stopped;
routing that decision to Preloop (`onPermissionRequest` → Preloop → the pending request) is the
next, narrow piece of work. Also not yet shown: a real *approval* round trip through Preloop, and
the approval-timeout case.

`exit=5` on refusal: the refused request ends the turn and the process exits non-zero. Inside a
Conductor step that surfaces as a failed step — consistent with failing closed.

---

## CodexBar guard inside the governed runtime (first probe)

`codexbar guard --provider {claude,codex} --min-remaining 20 --window session --json`:

```
{"provider":"claude","exitCode":69,"remainingPercent":null,"unavailableReason":"fetch-failed","decision":"unknown"}
{"provider":"codex", "exitCode":69,"remainingPercent":null,"unavailableReason":"fetch-failed","decision":"unknown"}
```

- **Fails closed by default** with no egress: exit 69, no percentage invented.
- **The guard output names no account.** It can say "claude has N% left", never *whose*. The
  account-match requirement therefore cannot be met from `guard` alone; the router has to bind
  the observation to an account identity obtained separately and compare it with the executing
  account. `guard` removes the threshold glue, not the identity glue.
- Quota observation needs provider egress, which the governed runtime deliberately lacks, so
  CodexBar cannot live in the agent container; it needs an observer placement of its own.

## Change ledger (the #281 success measure)

Every change made to run a given vendor through the common layer, recorded as it happens.

| # | What | Why | Vendor-specific? |
|---|---|---|---|
| 1 | node + acpx + both ACP adapters + codex in the image | egress 0 forbids launch-time `npx` | no (shared) |
| 2 | inject 3 gateway env vars per run | acpx excludes user settings | **Claude-specific** (Anthropic env names) |
| 3 | fresh named session per run | session key lacks account/policy | no (shared) |
| 4 | `--approve-*` / `--deny-all` per run | permission policy is per invocation | no (shared) |

Codex not yet run — blocked on a container-side Codex login.
