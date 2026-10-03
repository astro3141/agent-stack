// Replay the recorded runs under stack/fixtures/run-agent/ through the adapter's model-free
// halves and compare with what the adapter wrote on the instance (#27). No model, no network.
//
//   node stack/adapter/replay.mjs [fixtures dir]        one line per fixture, exit 1 on a mismatch
//
// What is compared, per run: the fold of events.jsonl (text, usage count, MCP denials) against
// result.json; the normalized status from the recorded permissions, denials, failure and turn
// against result.status; and the whole result shape rebuilt from the recorded inputs against
// result.json minus its two raw members (status_raw, usage_events).
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { fold, normalizeStatus, buildResult } from "./result.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = process.argv[2] ?? join(here, "..", "fixtures", "run-agent");
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);
let bad = 0, n = 0;
for (const d of readdirSync(root).filter((x) => existsSync(join(root, x, "result.json"))).sort()) {
  n++;
  const req = JSON.parse(readFileSync(join(root, d, "request.json"), "utf8"));
  const want = JSON.parse(readFileSync(join(root, d, "result.json"), "utf8"));
  const events = readFileSync(join(root, d, "events.jsonl"), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  const acc = fold(events);
  const text = acc.text.join("");
  const problems = [];
  if (text !== want.text) problems.push("text differs");
  if (acc.usage.length !== (want.usage_events ?? []).length) problems.push(`usage ${acc.usage.length} vs ${(want.usage_events ?? []).length}`);
  if (!eq(acc.mcpDenials, want.mcp_denials)) problems.push(`mcp_denials ${JSON.stringify(acc.mcpDenials)} vs ${JSON.stringify(want.mcp_denials)}`);
  // the recorded permissions carry the fields the status is decided on (outcome, denial)
  const perms = (want.permissions ?? []).map((p) => ({ ...p, preloop: p.request_id ? { request_id: p.request_id } : null }));
  const norm = normalizeStatus({ permissions: perms, mcpDenials: acc.mcpDenials, failure: want.failure, result: want.turn });
  if (norm !== want.status) problems.push(`status ${norm} vs ${want.status}`);
  const hook = want.hook ? { hook: { runtime_principal: want.hook.principal, source: want.hook.source }, matched: want.hook.matched } : null;
  const direct = want.model_route === "direct";
  const out = buildResult({ req, norm, hook, principal: req.mcp_principal || null, status: want.status_raw,
    permissions: perms, mcpDenials: acc.mcpDenials, mcpOnly: req.native_tools === false, direct,
    result: want.turn, failure: want.failure, text, wallMs: want.wall_ms, evDir: want.evidence_dir,
    ledgerError: want.ledger_error });
  const { status_raw, usage_events, ...recorded } = want;
  for (const k of new Set([...Object.keys(out), ...Object.keys(recorded)])) {
    if (!eq(out[k], recorded[k])) problems.push(`${k}: ${JSON.stringify(out[k])?.slice(0, 80)} vs ${JSON.stringify(recorded[k])?.slice(0, 80)}`);
  }
  bad += problems.length ? 1 : 0;
  console.log(`  ${problems.length ? "FAIL" : "ok  "}  ${d.padEnd(12)} ${want.provider.padEnd(7)} ${want.status.padEnd(10)} events ${String(events.length).padStart(3)}  denials ${acc.mcpDenials.length}` + (problems.length ? `\n        ${problems.join("\n        ")}` : ""));
}
console.log(`${n - bad}/${n} recorded runs replayed`);
process.exit(bad ? 1 : 0);
