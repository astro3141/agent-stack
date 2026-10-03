# Recorded runs of the adapter

Four runs of `stack/run-agent.mjs`, taken on the instance on 2026-10-03 after update day 2
(`911dc67`: claude 2.1.287 / claude-agent-acp 0.85.1, codex 0.160.0 / codex-acp 2.1.1,
grok 1.0.46, acpx 0.19.4) and posted on issue #27. One per provider, plus grok's denied case:

| dir | run | outcome |
|---|---|---|
| `claude-auto` | auto, `write_file` through Preloop | COMPLETED; `permissions.jsonl` (`preloop_mcp_rules`, `allow_once`) |
| `codex-auto` | auto, `write_file` through Preloop | COMPLETED |
| `grok-allow` | §50 pair, principal `novel-reviewer`, brokered into `closed` | COMPLETED, produced |
| `grok-deny` | §50 pair, same principal, a path the rules refuse | DENIED, `mcp_rule_denials: 1` |

Each directory holds the run's `request.json`, `events.jsonl`, `result.json` and, where the run
wrote them, `permissions.jsonl` and `execution.json`. acpx's own session store is left out.
Masked: every UUID is `00000000-0000-0000-0000-0000000000NN`, the same mapping across all files
so references still match; no tokens, credentials, emails or host paths. Run ids, token counts
and model names are as recorded. `INDEX.txt` carries each file's size and sha256 prefix, and
`review_controls.py` checks them.

What they are for: `stack/adapter/replay.mjs` feeds `events.jsonl` and the recorded inputs through
the adapter's model-free halves (`stack/adapter/*.mjs`) and compares with `result.json` — the
measurement that lets `run-agent.mjs` be cut without a model call (#27, OPERATIONS §74).
