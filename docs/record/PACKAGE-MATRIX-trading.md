## Capability × package matrix — `trading` (/home/user/agent-stack-trading @ 4f1ada8, v0.2.1, 6 workflows)

Scope: `harness/` (36,438 py lines) treated as domain content, not audited; only the package's calls into it are cited. Paths relative to the package root unless prefixed `stack/`.

| ID | trading | evidence |
|---|---|---|
| C1 Admission | **BOTH** | USES `stack/steps/route.py` in trading-b/shapes/port/official (official gates only new model calls: trading-official.yaml:112-129). trading-epoch.yaml / trading-lane-i.yaml have **no route step at all** — quota admission replaced by the harness's own attempt budgets (epoch_cycle.py:1-13). admit_models.py never used. |
| C2 Role binding | **USES(stack/steps/roles.py)** | trading-b.yaml:51-52 (`ai=codex:trading-lane`), shapes.yaml:55-56, port.yaml:66-67. N-A for official/epoch/lane-i: provider pinned in the pins file, `PROVIDER_HOLD` on mismatch (official_cycle.py:573-586). |
| C3 Execution | **BOTH** | b/shapes/port: model calls via `stack/steps/tasks.py` → agent_task. official/epoch/lane-i: the harness's `ClaudeCliArchPolicy` / `ClaudeCliRiskAdapter` spawn the claude CLI **inside the step** with `CLAUDE_CONFIG_DIR=/route/claude` (official_cycle.py:241-357; epoch_cycle.py:43-50,104-113; lane_i_cycle.py:75-79) — bypasses run-agent.mjs / normalized result; no `preloop|mcp|principal` string in those three files. |
| C4 Tool rights | **BOTH** | principals.yaml declares `trading-lane`; bound in trading-b.yaml:52 and hardcoded `"principal": "trading-lane"` in trade_stage.py:134 / arch_port.py:67. official/epoch/lane-i: direct CLI dispatch carries **no principal** (principals.yaml:22-23 says so). |
| C5 Concurrency | **BOTH** | USES `stack/steps/tasks.py` (+`--plan` → task_chain) in b/shapes/port (trading-port.yaml:142-143). official/epoch/lane-i run lanes sequentially inside `ArchRunner.run_cycle` and the package **builds its own receipt in tasks.py's `members` shape** from harness telemetry (official_cycle.py:359-541). |
| C6 Recording | **USES(stack/steps/record.py)** | all six YAMLs (26 call sites). b/shapes/port pass `evidence_file`+`receipts`; official passes own receipt + measurements; epoch/lane-i pass `check` only (trading-epoch.yaml:58,70) → record has no executions/evidence; ledger stays in sqlite. |
| C7 Operation | **BOTH** | USES `scripts/cycle.sh` from scripts/trading-live-slots.sh:21-25. OWN: launchd plist generation + `launchctl bootstrap` (scripts/bootstrap-live.sh:53-76), catch-up slot, PATH fix, logs into `$STACK_ROOT/evidence/ops/launchd-*.log`. soak/cleanup not referenced. |
| C8 Composition | **USES(manifest.yaml:28)** | `requires.capabilities: [tool_rights, egress, record, admission]`. No stack-version pin. README-port.md:16 still cites `requires.platform_steps`, which the manifest no longer has. |
| P1 Workspace via settings | **BOTH** | trade_stage.py:25-29, packet_bridge.py:32-35, arch_port.py:28-31 as the contract; official_cycle.py:90-105 `_ws_path` same formula but **silently falls back to `/tmp/official-ws`**; epoch/lane-i use no workspace (state in `/work/handoff/*.sqlite3`). |
| P2 Last-line JSON | **OWN (complies)** | every step; official_cycle.py:62-80 `SHAPES` fills every declared key and exits 0 on holds; harness stdout redirected to stderr (lane_i_cycle.py:108-111, epoch_cycle.py:131-134). |
| P3 REPEATABLE / guarded | **BOTH / partial** | 7 of 9 steps declare. **epoch_cycle.py and lane_i_cycle.py declare nothing** → `stack/trial_controls.py:796-804` fails "every step says what a repeat of it does". official's guard is real and remote-side: `ALREADY_DECIDED`/`EVIDENCE_PENDING` in the segment DB before any model call (harness_adapter.py:189-250). |
| P4 Evidence `items` | **BOTH** | trade_stage.py:276-277 and arch_port.py:148-152 write `items`. official/epoch/lane-i pass no `evidence_file` → `evidence_items` 0 by construction. |
| P5 Refuse-not-degrade | **OWN (complies)** | packet_bridge.py:112-116, live_packet.py:64-68, official_cycle.py:126-141, 588-595, epoch_cycle.py:60-63,75-79,87-97, lane_i_cycle.py:58-62,69-72,80-84. Exception: `_ws_path` /tmp fallback. |
| P6 Hand-in by name + fixtures | **BOTH** | packet_bridge.py:117-121 resolves `/work/handoff/<name>` but **accepts a `/` path unchanged** (escape refusal relies on `stack/run_workflow.py:121` SAFE charset, not the step). official/epoch/lane-i: `--db /work/handoff/{{segment_db}}`, `--pins /work/handoff/{{pins}}`. |
| P7 Own credentials | **OWN / partial** | manifest.yaml:35-41 declares `KIS_APP_KEY`, `KIS_APP_SECRET` in `docker/market.env`; **`DART_API_KEY` is required but undeclared** (epoch_cycle.py:75-79, lane_i_cycle.py:58-62, official_cycle.py:161-164) → `packages.py needs` cannot report it. Uses `market.env`, not the contract's `package.env`. |
| P8 Principals declared | **USES(principals.yaml)** | one principal `trading-lane`; no `egress_profile` because codex/grok CLIs refuse a foreign uid (principals.yaml:11-15). Not used by the three harness-dispatch workflows. |
| X1 Step boilerplate | **OWN ×4** | run-id/settings/WS/`out()` copied in trade_stage.py:22-34, packet_bridge.py:30-40, arch_port.py:26-37, official_cycle.py:74-105. |
| X2 Snapshot / hashing / receipts | **BOTH** | OWN: packet built twice & sha-compared (trade_stage.py:44-54), `_sha` canonical JSON (packet_bridge.py:43-46), input bundle hash + verified packet + envelope `<file>.meta.json` (harness_adapter.py:119-160, 469-478), receipt re-built from DB (official_cycle.py:359-541). |
| X3 External-effect guard | **OWN (+domain)** | orders/ledger idempotency is harness (`prepare_cycle` ALREADY_DECIDED; `execution_lock` flock; D3 "decide() never retries"). KIS: single attempt, 30 s timeout, no retry (live_packet.py:71-73,102). |
| X4 Credential/token lifecycle | **OWN** | KIS token issue/cache/refresh in `~/.kis-token.json` (live_packet.py:51-83) **and** a second cache in the harness (`harness/trader/data/kis.py:154-182`). Claude CLI token refresh reaches directly into the stack's login store `/route/claude` via `CLAUDE_CONFIG_DIR` (official_cycle.py:262-275, epoch_cycle.py:43-50) — undeclared dependency on `logins_root` layout. |
| X5 Sub-run orchestration | **OWN** | shell: slots.sh loops 3 workflows through cycle.sh; bootstrap-live.sh runs steps by `docker exec`. In-step: harness `run_cycle` spawns claude CLI children; failure_rehearsal.py:256-267 spawns a crash child. |
| X6 Controls location | **BOTH** | package controls.py (17 checks, port path only; stale `/work/p281` at :21,:55); three more suites as steps (`official_cycle.py rehearse`, `harness_adapter.py rehearsal`, `failure_rehearsal.py`). Stack's `stack/trial_controls.py:140,347,509,579` loads `/work/packages/trading/steps/trade_stage.py` — stack controls depend on this external package being installed. |
| X7 Prompt templating / freezing | **OWN** | 20 prompts passed by path to tasks.py. Official: pins file, `pin-material` measures prompt/schema sha + CLI version (official_cycle.py:725-760), freeze guard (300-357). Stack has no freeze/pin capability. |
| X8 External time / calendar / schedule | **OWN; MISSING on stack** | KRX calendar via harness `TradingCalendar` (fail-closed); KST "today" resolved in-step because `cycle.sh` cannot pass workflow inputs (official_cycle.py:1388-1396); launchd 18:40/21:10 Mon–Fri. Stack: lock+skip only, no scheduler, no calendar, no input pass-through. |
| X9 Cross-run state | **OWN; MISSING on stack** | segment sqlite DBs + pins kept in `/work/handoff/` — the inbound hand-in dir used as a persistent state store; token caches in `~`; `DISPATCH_HOME=/tmp/official-dispatch-home`. Stack defines only per-run workspace and inbound handoff; no package-state contract. |
| X10a Output-contract filling | **OWN** | `SHAPES` per command, every exit carries every declared key, exit 0 (official_cycle.py:57-80) — generic Conductor-validation workaround. |
| X10b Egress env to child processes | **BOTH** | `_apply_stack_egress` imports `stack/settings.egress_env()` and applies to `os.environ` before spawning (official_cycle.py:107-124); settings.py has the function, no documented step hook. |
| X10c Bundled-library bootstrap | **OWN (by contract)** | `harness_root()/ensure_harness()` sys.path discovery (harness_adapter.py:70-99), vendored `steps/vendor/valuation.py` sha-pinned, `requires.python: [pydantic, httpx]`. |
| X10d Stale platform address | **OWN (defect)** | `sys.path.insert(0, "/work/p281")` trade_stage.py:24; controls.py:21,55; YAML names `p281-trading-*`. Works only because PYTHONPATH already carries /work/stack. |
| X10e Host test scaffolding | **OWN** | controls.py:44-58 fabricates `config/generated/runtime.json` + `AGENTSTACK_ROOT` to run steps outside the container. |

### (a) Stack scripts called by absolute path; stack-version requirement
- **4 distinct stack scripts**: `route.py` (4 YAMLs), `roles.py` (3), `tasks.py` (3), `record.py` (6). **26 call sites**. YAMLs also hardcode `/work/packages/trading/…` and `/work/handoff/…`.
- **No stack-version requirement is declared.** `stack/packages.py` reads only capabilities/python/env/egress.

### (b) Scheduling in the package vs stack cycle.sh
`scripts/bootstrap-live.sh` writes and loads two macOS launchd plists (18:40, 21:10 weekdays) running `scripts/trading-live-slots.sh`, which calls the stack's `scripts/cycle.sh` for epoch → official → lane-i. What the stack does **not** provide and the package built: the trigger, a multi-workflow order, a catch-up slot, exchange-calendar no-op, per-day idempotency (delegated to the harness), and **passing workflow inputs through cycle.sh** (day resolved in-step).

### (c) Generic parts another HTTP-API-with-keys package would copy
1. Step boilerplate (RUN/WS/out).
2. `SHAPES` output-contract fill + exit-0-on-hold.
3. `_apply_stack_egress()` and the `egressprobe` check.
4. Proxy-aware `urllib` opener + bearer-token issue/cache/refresh, refuse-with-hint when the key is absent.
5. Hand-in name → `/work/handoff/<name>` resolution with escape refusal.
6. stdout→stderr redirect around a chatty library.
7. Receipt builder in tasks.py `members` shape for calls the stack did not make.
8. Bundled-library discovery and host-side control scaffolding.

### Findings
- Three of six workflows (official, epoch, lane-i) run model calls through the harness's claude CLI inside a script step: no `agent_task`/broker, no Preloop principal, no fan-out — the stack supplies only record (+ route for official), and the package re-creates the receipt format to feed `record.py`.
- `epoch_cycle.py` and `lane_i_cycle.py` declare no `REPEATABLE`; the stack's `trial_controls.py:796-804` would fail on them. Epoch/lane-i also skip quota admission entirely.
- `DART_API_KEY` is required by three steps but absent from `manifest.requires.env`. The package uses `docker/market.env`, not the contract's `package.env`.
- Two KIS token caches coexist in one container; Claude CLI credentials are refreshed by writing into the stack's `/route/claude` store directly.
- `/work/handoff/` has become the package's persistent state store — the stack has no package-state contract; `_ws_path` silently falls back to `/tmp` off-stack.
- Scheduling is wholly package-side (launchd + slots script); `cycle.sh` cannot pass workflow inputs.
- Stale addressing: `/work/p281` in trade_stage.py:24 and controls.py; README says "three workflows" while the manifest carries six; README-port cites a `requires.platform_steps` key that no longer exists.
- Stack-side coupling runs the other way too: `stack/trial_controls.py` imports `/work/packages/trading/steps/trade_stage.py`.
