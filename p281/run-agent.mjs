// #281 routing/execution layer — one entry point for every provider.
//
//   node run-agent.mjs <request.json>          prints one normalized result JSON on stdout
//
// request.json: { run_id, provider, model?, cwd, prompt, timeout_ms?, evidence_dir? }
//
// Everything vendor-specific lives in PROVIDERS below. The caller (Conductor), Preloop and
// MLflow see the same request and result shape whichever provider runs.
//
// Permission: every ACP permission request goes to Preloop's native-tool permission check.
// The adapter decides nothing itself — it forwards with no client decision, so Preloop
// escalates to its approval channel, and maps the answer back. Any failure on that path
// (unreachable, bad response, exception) is a rejection. The acpx fallback policy is
// deny-all, so a handler that throws or returns undefined still cannot allow.

import { readFileSync, writeFileSync, mkdirSync, appendFileSync, globSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import http from "node:http";
import { createAcpRuntime, createRuntimeStore } from "/opt/npm-global/lib/node_modules/acpx/dist/runtime.js";
import { createAgentRegistry } from "/opt/npm-global/lib/node_modules/acpx/dist/agent-registry.js";

// Direct to the api, not through the console proxy: nginx cuts the held-open approval at 300 s
// with a 504 page, just before Preloop answers `timed_out` (~302 s), turning "approval expired"
// into "control unavailable".
// Own variable: the container already sets PRELOOP_URL=http://console for the Preloop CLI.
const PRELOOP_URL = process.env.PRELOOP_API_URL ?? "http://api:8000";

// ---- vendor-specific: the only place a provider is named -------------------------------
const PROVIDERS = {
  claude: {
    agent: "claude",
    preloopSource: "claude_code",
    // acpx does not load user settings, so the gateway route is passed explicitly. The
    // values are read from the container's own settings at run time and never persisted
    // (agentProcessEnv is child-only).
    env() {
      const s = JSON.parse(readFileSync(join(homedir(), ".claude/settings.json"), "utf8")).env ?? {};
      const keep = ["ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL"];
      return Object.fromEntries(keep.filter((k) => s[k]).map((k) => [k, s[k]]));
    },
  },
  codex: {
    agent: "codex",
    preloopSource: "codex_cli",
    env() { return {}; },   // filled in when Codex is logged in and its route is measured
  },
};
// -----------------------------------------------------------------------------------------

function preloopToken() {
  const [p] = globSync(join(homedir(), ".preloop/agents/*/permission_hook.json"));
  return JSON.parse(readFileSync(p, "utf8")).token;
}

function postJson(url, obj, signal) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(obj);
    const rq = http.request(url, {
      method: "POST", signal,
      headers: { Authorization: `Bearer ${preloopToken()}`, "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(data) },
    }, (res) => {
      let b = "";
      res.setEncoding("utf8").on("data", (c) => (b += c)).on("end", () => resolve({ status: res.statusCode, body: b }));
    });
    rq.on("error", reject);
    rq.end(data);
  });
}

async function askPreloop(req, { provider, runId, cwd, signal, log }) {
  const tc = req.raw.toolCall ?? {};
  const body = {
    tool_name: tc.title?.split(" ")[0] || tc.kind || "unknown",
    tool_input: { ...(tc.rawInput ?? {}), _acp_kind: tc.kind ?? req.inferredKind, _acp_title: tc.title },
    source: PROVIDERS[provider].preloopSource,
    session_id: runId,
    cwd,
    agent_reasoning: `run ${runId} via acpx/${provider}`,
    // client_decision deliberately omitted: the adapter holds no policy of its own.
  };
  const started = Date.now();
  let ans, err;
  try {
    // node:http, not fetch: undici's default headersTimeout is 300 s, which cuts the held-open
    // approval just before Preloop answers `timed_out` (~302 s). The run deadline (signal)
    // is the only bound here.
    const r = await postJson(`${PRELOOP_URL}/api/v1/agents/permission-check`, body, signal);
    if (r.status !== 200) throw new Error(`permission-check http ${r.status}`);
    ans = JSON.parse(r.body);
    if (ans.decision !== "allow" && ans.decision !== "deny") throw new Error(`unexpected decision ${ans.decision}`);
  } catch (e) { err = String(e?.message ?? e); }
  const ev = {
    at: new Date().toISOString(), ms: Date.now() - started,
    acp_kind: tc.kind ?? req.inferredKind ?? null, title: tc.title ?? null, input: tc.rawInput ?? null,
    preloop: ans ?? null, error: err ?? null,
    outcome: ans?.decision === "allow" ? "allow_once" : "reject_once",
    denial: ans?.decision === "allow" ? null
      : signal?.aborted ? "run_ended_awaiting_approval"
      : err ? "control_unavailable" : ans.timed_out ? "approval_expired" : "denied",
  };
  log(ev);
  return { outcome: ev.outcome };
}

async function main() {
  const req = JSON.parse(readFileSync(process.argv[2], "utf8"));
  const prof = PROVIDERS[req.provider];
  if (!prof) throw new Error(`unknown provider ${req.provider}`);
  const evDir = req.evidence_dir ?? `/tmp/p281/runs/${req.run_id}`;
  mkdirSync(evDir, { recursive: true });
  const permissions = [];
  const log = (ev) => { permissions.push(ev); appendFileSync(join(evDir, "permissions.jsonl"), JSON.stringify(ev) + "\n"); };

  const runtime = createAcpRuntime({
    cwd: req.cwd,
    agentProcessEnv: prof.env(),
    sessionStore: createRuntimeStore({ stateDir: join(evDir, "acpx-state") }),
    agentRegistry: createAgentRegistry(),
    permissionMode: "deny-all",                 // fallback if the handler throws / returns undefined
    nonInteractivePermissions: "deny",
    timeoutMs: req.timeout_ms ?? 600000,
  });

  const t0 = Date.now();
  const text = [], usage = [];
  let result, handle, failure;
  try {
    // A fresh session key per run: acpx keys sessions on (agent, cwd, name) with no account
    // or policy, so reuse across runs could carry one account's session into another's.
    handle = await runtime.ensureSession({
      sessionKey: `p281-${req.run_id}`, agent: prof.agent, mode: "oneshot", cwd: req.cwd,
      sessionOptions: req.model ? { model: req.model } : undefined,
    });
    const turn = runtime.startTurn({
      handle, text: req.prompt, mode: "prompt", requestId: `${req.run_id}-1`,
      onPermissionRequest: (r, { signal }) => askPreloop(r, { provider: req.provider, runId: req.run_id, cwd: req.cwd, signal, log }),
    });
    for await (const ev of turn.events) {
      if (ev.type === "text_delta" && ev.stream !== "thought") text.push(ev.text);
      if (ev.type === "status" && ev.tag === "usage_update") usage.push(ev);
      appendFileSync(join(evDir, "events.jsonl"), JSON.stringify(ev) + "\n");
    }
    result = await turn.result;
  } catch (e) {
    failure = { message: String(e?.message ?? e), code: e?.code };
  }
  let status = null;
  try { if (handle) status = await runtime.getStatus({ handle }); } catch { /* best effort */ }
  try { await runtime.shutdown(); } catch { /* best effort */ }

  // Normalized status. TIMED_OUT = the run deadline passed while an approval was still open;
  // the run deadline must exceed the approval window or every unanswered approval ends here.
  // A denial is never a generic failure: it must not be retried on
  // another provider, because that would turn "not approved" into "try someone else".
  const denials = permissions.filter((p) => p.outcome !== "allow_once");
  const norm =
    denials.some((d) => d.denial === "run_ended_awaiting_approval") ? "TIMED_OUT"
    : denials.some((d) => d.denial === "control_unavailable") ? "CONTROL_UNAVAILABLE"
    : denials.length ? "DENIED"
    : failure || result?.status === "failed" ? "FAILED"
    : result?.status === "cancelled" ? "CANCELLED"
    : "COMPLETED";

  const out = {
    run_id: req.run_id,
    status: norm,
    retryable_elsewhere: norm === "FAILED" && (result?.error?.retryable ?? false),
    provider: req.provider,
    model: {
      requested: req.model ?? null,
      session_reported: status?.models?.currentModelId ?? status?.model ?? null,
      served: "unknown",   // nothing on this path reports the served model; do not infer it
    },
    permissions: permissions.map(({ acp_kind, title, outcome, denial, preloop, error }) =>
      ({ acp_kind, title, outcome, denial, request_id: preloop?.request_id ?? null, error })),
    turn: result ?? null,
    failure: failure ?? null,
    text: text.join(""),
    wall_ms: Date.now() - t0,
    evidence_dir: evDir,
  };
  writeFileSync(join(evDir, "result.json"), JSON.stringify({ ...out, status_raw: status, usage_events: usage }, null, 1));
  process.stdout.write(JSON.stringify(out) + "\n");
  process.exitCode = norm === "COMPLETED" ? 0 : norm === "DENIED" ? 3 : 1;
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ status: "FAILED", failure: { message: String(e?.message ?? e) } }) + "\n");
  process.exitCode = 1;
});
