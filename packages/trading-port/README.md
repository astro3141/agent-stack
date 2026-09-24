<!-- Ported to a package on 2026-09-24. What moved, and what did not:

  p281/workflows/trading-port.yaml   ->  packages/trading-port/workflow.yaml
  p281/steps/{arch_port,packet_bridge}.py -> packages/trading-port/steps/
  p281/steps/vendor/                 ->  packages/trading-port/steps/vendor/
  p281/prompts/port-*.md             ->  packages/trading-port/prompts/
  p281/fixtures/trading/*.json       ->  packages/trading-port/fixtures/
  p281/port_controls.py              ->  packages/trading-port/controls.py

Every path inside those files was rewritten to the package root, and the package's own controls
pass from there (17/17). What did NOT move: route.py, roles.py, tasks.py and record.py are platform
capabilities and stay in p281/ — and **trade_stage.py stays too, which is the one thing that keeps
this package from being self-contained.** It belongs to the built-in trading-b workflow, and this
package reuses its `validate` so every lane is checked the same way. Until it is either vendored
here or promoted to a capability, installing this package on a machine also requires that built-in
workflow to be present. The manifest names it (`requires.platform_steps`).

Installing: copy this directory into `packages/` on a machine that has the stack, run
`scripts/up.sh`, then `run_workflow.py start <id> trading-port <profile>`. Nothing in the platform
is edited (OPERATIONS §27). -->

# Porting the paper-trading harness's arch cycle onto this stack (2026-09-24)

Not a shape trial (that is `TRIAL-B-trading.md`). This is the **port**: the harness's own arch
cycle — B(deterministic replica) + E + G + F(desk) + H(forecast→score→decide) — deciding together
from **one bridged harness packet**, validated by the harness's own contracts, with the
deterministic financial math kept out of the prompts.

**Not run in the current environment (owner 2026-09-24).** The workflow is authored and
statically verified; **pilot and live are exercised later** (post-reset). What runs here is only
`p281/port_controls.py` — no model call, no network.

## What "port" changes over the shape trial

| | shape trial (B2) | this port |
|---|---|---|
| packet | invented fixture, one shape per lane | the harness's **real ResearchPacket**, bridged (`packet_bridge.py`); one packet, several lanes |
| lane contracts | generic shape prompts | the harness's own: grounding (refs ⊆ packet source_id), universe membership, the frozen constitution's gross 50% / name 5% / min-trade 1% |
| deterministic math | — | a **script step** (`vendor/valuation.py`, pinned to harness sha), never a prompt (§12) |
| scoring | fixture next-session | pilot: a held-back file; **live: the harness's own ledger is authoritative** — this stack produces the validated *decisions* |

## The three seams

1. **The packet bridge** (`p281/steps/packet_bridge.py`). The harness builds a PIT ResearchPacket
   from KIS/DART with its own gated builders. This stack's egress reaches model providers only, so
   market data is out of scope *inside* the runtime by construction (TRIAL-B). The bridge is the
   seam, in two modes:
   - **pilot** — a committed harness-shaped packet (`fixtures/trading/harness-arch-packet-pilot.json`,
     generated from the harness's own fixture builder, invented numbers, reproducible), plus a
     companion held-back returns file kept OUT of the lanes' packet.
   - **live** — the harness freezes a real packet outside the runtime and hands the path in
     (`-i mode=live -i packet_from=…`). The bridge never fetches; it maps and preserves the PIT
     facts (`available_at`, `receipt_id`, `original_or_correction`) and carries the harness's own
     `external_packet_hash`, so a cycle's input is attributable to the exact harness packet it came
     from. A live hand-in with no hash is refused, not silently trusted.

2. **The deterministic core as a script step.** `vendor/valuation.py` is the harness's
   `trader/arch/valuation.py` copied **verbatim** (pure functions, no I/O), with a provenance
   header pinning the source sha256 (`1a80c78d…`). It runs as a script step so the AI never
   authors valuation/scoring — the port's H lane already puts scoring in a script between two model
   calls, and any implied/scenario comparison uses this module, not a prompt. **Maintenance:**
   re-vendor and re-pin on any harness change to that file. This is the same "one execution core,
   not three copies" tension recorded for the harness itself — vendoring with a pinned sha is the
   interim, a shared module is the real fix (a next-segment prerequisite).

3. **Identical validation.** `arch_port.py evaluate` reuses `trade_stage.validate` unchanged:
   grounding, universe, per-symbol weight bounds and gross exposure — one function for every lane,
   including the deterministic B. A lane that was planned and produced nothing is `MISSING`, not
   silently dropped (the defect the shape trial found, kept fixed here).

## What is faithful, and what is approximated

- **Faithful:** the packet's PIT fields and provenance; the constitution's bounds; grounding;
  lane isolation; the deterministic-math-is-not-the-lane's rule; the held-back scoring split.
- **Approximated / deferred, on purpose:**
  - The **live lane prompts** should be the harness's frozen prompts verbatim (pinned in
    `ArchConfig.PromptPins`), adapted only for stack I/O. The committed `prompts/port-*.md` are
    compact faithful stand-ins for a cheap reproducible **pilot**; swapping in the frozen prompts
    is the live step and is a documented follow-on, not done here.
  - **Scoring/ledger** stay in the harness for live. The stack's `evaluate` is pilot-grade
    diagnostic only.
  - **Lane I is not in this cycle.** It uses a per-symbol long-horizon packet and its own thesis
    lifecycle/ledger — a separate bridge and workflow, its 3-call pipeline already shown to run in
    the shape trial. Follow-on.
  - **A~D epoch-2** (frictionless A, MI-modified C, RC-reviewed D) is a different segment's
    workflow; not ported here.

## Files

| | |
|---|---|
| `p281/workflows/trading-port.yaml` | the port workflow (route→roles→**bridge**→B→plan→lanes→evaluate→record), `mode=pilot|live` |
| `p281/steps/packet_bridge.py` | harness ResearchPacket → stack packet, pilot/live, PIT + provenance preserved |
| `p281/steps/arch_port.py` | the arch lane plan (E/G/F/H) and the port evaluate (identical validation + held-back scoring) |
| `p281/steps/vendor/valuation.py` | the harness valuation core, vendored verbatim, sha-pinned |
| `p281/prompts/port-*.md` | pilot lane prompts carrying the harness contracts (7 files) |
| `p281/fixtures/trading/harness-arch-packet-pilot.json` | a real-shaped harness packet (pilot) |
| `p281/fixtures/trading/harness-arch-heldback-pilot.json` | held-back returns, kept out of the lanes' packet |
| `p281/port_controls.py` | 17 controls, no model call — the only thing run here |

## How it will be exercised (later, not here)

```bash
# pilot — reproducible, no market data, no provider needed for the bridge/B/evaluate;
#         the four model lanes need provider logins (panel 계정 tab)
conductor run p281/workflows/trading-port.yaml -i mode=pilot -i profile=research-default

# live — the harness freezes today's ResearchPacket outside this runtime, hands the path in
conductor run p281/workflows/trading-port.yaml -i mode=live \
  -i packet_from=/work/handoff/acyc-YYYY-MM-DD.json
```

Provider logins for this stack must NOT use the harness's a.t (riskcritic-only) account — the
2026-09-13 account-separation rule stands.

## Verified here

`python3 p281/port_controls.py` → 17/17, no model call: bridge on pilot, PIT/provenance carried,
held-back kept out of the lanes' packet, live refuses a missing hand-in, constitution constraints,
deterministic B within bounds, the arch plan's shapes (7 model + 1 script steps), identical
validation (valid E / off-universe rejected / MISSING flagged), pilot scoring, and the vendored
valuation being the harness's deterministic math. End-to-end (the model lanes) is pilot's job,
later.
