// #281 routing/execution layer — one entry point for every provider.
//
//   node run-agent.mjs <request.json>          prints one normalized result JSON on stdout
//
// request.json: { run_id, provider, model?, cwd, prompt, timeout_ms?, evidence_dir?,
//                 mcp_principal? }   mcp_principal: present this role's Preloop credential
//
// Everything vendor-specific lives in stack/adapter/providers/<name>.mjs. The caller (Conductor),
// Preloop and MLflow see the same request and result shape whichever provider runs.
//
// Permission: every ACP permission request goes to Preloop's native-tool permission check.
// The adapter decides nothing itself — it forwards with no client decision, so Preloop
// escalates to its approval channel, and maps the answer back. Any failure on that path
// (unreachable, bad response, exception) is a rejection. The acpx fallback policy is
// deny-all, so a handler that throws or returns undefined still cannot allow.

import { statSync, readFileSync, writeFileSync, mkdirSync, appendFileSync, globSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import http from "node:http";
import { createAcpRuntime, createRuntimeStore } from "/opt/npm-global/lib/node_modules/acpx/dist/runtime.js";
import { createAgentRegistry } from "/opt/npm-global/lib/node_modules/acpx/dist/agent-registry.js";
// The model-free halves live beside this file and are replayed against recorded runs
// (stack/adapter/replay.mjs, stack/fixtures/run-agent/, #27): what a turn's events fold into,
// how the status is decided, the one result shape; what a permission request says to Preloop and
// how the answer becomes an outcome; the codex ledger line.
import { accumulator, take, normalizeStatus, buildResult, exitCodeFor } from "/work/stack/adapter/result.mjs";
import { NATIVE_ALLOWABLE, permissionBody, permissionEvent, decidedLocally } from "/work/stack/adapter/permissions.mjs";
import { ledgerLine } from "/work/stack/adapter/ledger.mjs";
// One module per provider, each a function of the call's context: what a vendor needs (its
// login directory, its egress, its principal) is handed to it per call, never kept in this
// module between calls (#27).
import claude from "/work/stack/adapter/providers/claude.mjs";
import codex from "/work/stack/adapter/providers/codex.mjs";
import grok from "/work/stack/adapter/providers/grok.mjs";

// Direct to the api, not through the console proxy: nginx cuts the held-open approval at 300 s
// with a 504 page, just before Preloop answers `timed_out` (~302 s), turning "approval expired"
// into "control unavailable".
// Own variable: the container already sets PRELOOP_URL=http://console for the Preloop CLI.
// Addresses and paths come from the generated settings (config/generated/runtime.json, from
// config/environment.yaml via cfg.py); the literals are only the fallback for an unconfigured
// checkout.
const RT = (() => {
  try { return JSON.parse(readFileSync("/work/config/generated/runtime.json", "utf8")); } catch { return {}; }
})();
const PRELOOP_URL = process.env.PRELOOP_API_URL ?? RT.preloop?.api_url ?? "http://api:8000";
const PRELOOP_MCP_URL = process.env.AGENTSTACK_MCP_URL
  ?? RT.preloop?.mcp_url ?? `${process.env.PRELOOP_URL ?? "http://console"}/mcp/v1`;
const LOGINS = RT.paths?.logins_root ?? "/route";

// ---- per-role Preloop principal (opt-in) ------------------------------------------------
// A request may name a principal of its own (`mcp_principal`): the call then presents that
// principal's Preloop credential to the MCP endpoint instead of the adapter's, so two roles on
// the same provider can carry different tool rights (Preloop governs per subject — api_key_id,
// then managed_agent_id). The token is never stored here and never written to the evidence: the
// caller supplies it in PRELOOP_MCP_<NAME>. A named principal whose credential is missing is an
// error, never a silent fall back to the adapter's wider rights.
const principalEnv = (name) => `PRELOOP_MCP_${name.toUpperCase().replace(/[^A-Z0-9]/g, "_")}`;
function principalAuth(name) {
  // Brokered (§53): the step holds an opaque per-job token, not the credential. The broker's
  // MCP forward swaps it for the role's real one, which exists only in the broker's process.
  if (process.env.AGENTSTACK_JOB_TOKEN) return `Bearer ${process.env.AGENTSTACK_JOB_TOKEN}`;
  const v = process.env[principalEnv(name)];
  if (!v) throw new Error(`mcp_principal "${name}": ${principalEnv(name)} is not set`);
  return v.startsWith("Bearer ") ? v : `Bearer ${v}`;
}

// Option B egress: the routing layer's allowlist proxy. Preloop (tools, approvals), MLflow and
// in-network names stay direct.
//
// A step that runs as a role of its own (§48) arrives with that role's proxy already in its
// environment — role-exec put it there, with the role's credential. The vendor CLI must get *that*
// proxy, not the shared one: measured (devflow's researcher, 2026-09-25), with the shared proxy
// written over it here, every model call and every WebFetch of a confined role went out through the
// shared list — the role's own hosts were refused as "filtered domain" and the shared list's hosts
// were open to it. The confinement held for the adapter's own process and nothing it started.
const EGRESS = (() => {
  const roleProxy = process.env.AGENTSTACK_ROLE ? (process.env.HTTPS_PROXY || process.env.https_proxy) : null;
  const proxy = roleProxy || RT.egress?.proxy || "http://egress:8888";
  const npList = RT.egress?.no_proxy ?? ["console", "api", "gateway", "mlflow", "localhost", "127.0.0.1"];
  // a brokered step's MCP endpoint (§53) is in-network: never sent through the egress proxy,
  // whose list quite rightly has no idea what a "broker" is
  if (process.env.AGENTSTACK_MCP_URL) {
    try { npList.push(new URL(process.env.AGENTSTACK_MCP_URL).hostname); } catch {}
  }
  const np = npList.join(",");
  return { HTTPS_PROXY: proxy, HTTP_PROXY: proxy, https_proxy: proxy, http_proxy: proxy, NO_PROXY: np, no_proxy: np };
})();

// ---- vendor-specific: the only place a provider is named -------------------------------
const PROVIDERS = { claude, codex, grok };

// What one call is, as every provider module reads it. Built once in main() from the request;
// two calls in one process would get two of these, and nothing of one reaches the other.
//   login      the login directory under LOGINS the profile names (request `login`)
//   principal  the role whose Preloop credential this call presents (request `mcp_principal`)
function callContext({ login = null, principal = null } = {}) {
  return {
    login, principal,
    loginsRoot: LOGINS,
    loginDir: (provider) => `${LOGINS}/${login ?? provider}`,
    // Every profile's mcpAuth() goes through this, so the override reaches both the server the
    // adapter attaches over ACP and the one it writes into a vendor config in memory.
    withPrincipal: (own) => (principal ? principalAuth(principal) : own()),
    egress: EGRESS,
    mcpUrl: PRELOOP_MCP_URL,
  };
}

// The credential of the agent that is actually running, not whichever hook file sorts first.
// A fresh install now onboards more than one vendor (claude-code and codex), so the home holds
// more than one hook; each says which agent it is for (`source`, the same value the permission
// request carries). Presenting the wrong one still works today — both credentials belong to the
// same account and neither runtime agent carries tool rules — and it would attribute every
// permission request to the wrong agent, which is the kind of thing that is discovered later as
// rights nobody meant. The fallback is the first hook, and the choice is recorded in the run's
// evidence either way (OPERATIONS §32).
function preloopHook(source) {
  const files = globSync(join(homedir(), ".preloop/agents/*/permission_hook.json"));
  if (!files.length) throw new Error("no Preloop permission hook in this home");
  const want = source ?? null;
  // Newest first. A home outlives a Preloop database: reinstalling the control plane and claiming
  // it again onboards the agent afresh and leaves the previous identity's hook beside the new one,
  // with the same `source` and a credential of an account that no longer exists. Taking whichever
  // the directory listed first would present the dead one (OPERATIONS §35).
  const byNewest = files
    .map((f) => { try { return { f, at: statSync(f).mtimeMs }; } catch { return null; } })
    .filter(Boolean).sort((a, b) => b.at - a.at).map((x) => x.f);
  for (const f of byNewest) {
    try {
      const h = JSON.parse(readFileSync(f, "utf8"));
      if (want && h.source === want) return { hook: h, file: f, matched: true };
    } catch { /* a hook that cannot be read is not the one to use */ }
  }
  return { hook: JSON.parse(readFileSync(byNewest[0], "utf8")), file: byNewest[0], matched: false };
}

// `token`: the hook credential of the agent this call runs, chosen once in main().
function postJson(url, obj, signal, token) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(obj);
    const rq = http.request(url, {
      method: "POST", signal,
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json",
        "Content-Length": Buffer.byteLength(data) },
    }, (res) => {
      let b = "";
      res.setEncoding("utf8").on("data", (c) => (b += c)).on("end", () => resolve({ status: res.statusCode, body: b }));
    });
    rq.on("error", reject);
    rq.end(data);
  });
}

async function askPreloop(req, { provider, prof, token, runId, cwd, signal, log, mcpOnly, nativeAllow = [] }) {
  const tc = req.raw.toolCall ?? {};
  // A read-only web tool the profile lets run without asking (tools.native_allow). Where it can
  // reach is the egress allowlist's to decide; nothing that writes or executes is ever let through.
  const nativeName = tc._meta?.claudeCode?.toolName ?? tc.name;
  if (mcpOnly && nativeName && NATIVE_ALLOWABLE.includes(nativeName) && nativeAllow.includes(nativeName)) {
    log(decidedLocally(tc, req.raw, "profile_native_allow"));
    return { outcome: "allow_once" };
  }
  if (mcpOnly && prof.governedDownstream?.(req.raw)) {
    log(decidedLocally(tc, req.raw, "preloop_mcp_rules"));
    return { outcome: "allow_once" };
  }
  const body = permissionBody(tc, req.inferredKind, prof.preloopSource, runId, cwd);
  // (agent_reasoning names the adapter and the provider, as before)
  body.agent_reasoning = `run ${runId} via acpx/${provider}`;
  const started = Date.now();
  let ans, err;
  try {
    // node:http, not fetch: undici's default headersTimeout is 300 s, which cuts the held-open
    // approval just before Preloop answers `timed_out` (~302 s). The run deadline (signal)
    // is the only bound here.
    const r = await postJson(`${PRELOOP_URL}/api/v1/agents/permission-check`, body, signal, token);
    if (r.status !== 200) throw new Error(`permission-check http ${r.status}`);
    ans = JSON.parse(r.body);
    if (ans.decision !== "allow" && ans.decision !== "deny") throw new Error(`unexpected decision ${ans.decision}`);
  } catch (e) { err = String(e?.message ?? e); }
  const ev = permissionEvent({ tc, inferredKind: req.inferredKind, raw: req.raw, body, ans, err,
                               aborted: !!signal?.aborted, started });
  log(ev);
  return { outcome: ev.outcome };
}

async function main() {
  const req = JSON.parse(readFileSync(process.argv[2], "utf8"));
  const make = PROVIDERS[req.provider];
  if (!make) throw new Error(`unknown provider ${req.provider}`);
  // A role may present a principal of its own. A vendor that keeps its Preloop credential in its own
  // config file cannot have that file rewritten per call — but it can be *handed* a server over ACP
  // with the principal's credential, which is a different thing and was refused here for three
  // months on the strength of a measurement that had gone stale (OPERATIONS §49): grok 1.0.40
  // advertises `mcpCapabilities: {http: true}`, connects to a server handed to it, and completes the
  // Preloop handshake. So a principal is allowed, and the server travels with the call.
  const call = callContext({ login: req.login ?? null, principal: req.mcp_principal || null });
  const prof = make(call);
  // whose credential this run presents to Preloop, decided once, from the provider being run
  const hook = preloopHook(prof.preloopSource);
  const evDir = req.evidence_dir ?? `/tmp/agentstack/runs/${req.run_id}`;
  mkdirSync(evDir, { recursive: true });
  const permissions = [];
  const log = (ev) => { permissions.push(ev); appendFileSync(join(evDir, "permissions.jsonl"), JSON.stringify(ev) + "\n"); };

  // native_tools: false → option B. File work goes through Preloop's MCP endpoint, where
  // Preloop rules decide; the vendor's native write/shell tools are removed where the vendor
  // allows it, and whatever remains still escalates to Preloop approval.
  const mcpOnly = req.native_tools === false;
  if (call.principal && !mcpOnly) {
    throw new Error("mcp_principal requires native_tools=false: without it the run does not go through the Preloop MCP server");
  }
  const extraEnv = mcpOnly ? prof.disableNative(req.cwd, req.native_allow || []) : {};
  // model_route: "direct" → the routing layer's own login + allowlist proxy; otherwise the
  // Preloop model gateway (the #278 path). Refused if the provider has no direct profile.
  const direct = req.model_route === "direct" || !!prof.directOnly;
  if (direct && !prof.directEnv) throw new Error(`no direct route for ${req.provider}`);
  const routeEnv = direct ? prof.directEnv() : {};
  // Handed over ACP when the vendor takes it that way, and *also* when a principal is named and the
  // vendor would otherwise read its own file: that is the only way this call's rights differ from
  // the login's. The name is the same one its configuration uses, so a vendor that has both sees one
  // server under one name rather than two answering for the same thing.
  const handOver = mcpOnly && (!prof.mcpViaConfig || (call.principal && prof.mcpAuthFromFile));
  const mcpServers = handOver ? [{
    type: "http", name: "preloop", url: PRELOOP_MCP_URL,
    headers: [{ name: "Authorization", value: call.principal ? principalAuth(call.principal) : prof.mcpAuth() }],
  }] : undefined;

  const runtime = createAcpRuntime({
    cwd: req.cwd,
    mcpServers,
    agentProcessEnv: { ...(direct && prof.directReplacesEnv ? {} : prof.env()), ...extraEnv, ...routeEnv },
    sessionStore: createRuntimeStore({ stateDir: join(evDir, "acpx-state") }),
    agentRegistry: createAgentRegistry(prof.argv ? { overrides: { [prof.agent]: prof.argv } } : undefined),
    permissionMode: "deny-all",                 // fallback if the handler throws / returns undefined
    nonInteractivePermissions: "deny",
    timeoutMs: req.timeout_ms ?? 600000,
  });

  let accountAtStart = null;
  try { accountAtStart = prof.accountFingerprint?.(direct) ?? null; } catch { accountAtStart = null; }
  const t0 = Date.now();
  const acc = accumulator();                 // text, usage, mcpDenials — folded in result.mjs
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
      onPermissionRequest: (r, { signal }) => askPreloop(r, { provider: req.provider, prof, token: hook.hook.token, runId: req.run_id, cwd: req.cwd, signal, log, mcpOnly, nativeAllow: req.native_allow || [] }),
    });
    for await (const ev of turn.events) {
      take(acc, ev);
      appendFileSync(join(evDir, "events.jsonl"), JSON.stringify(ev) + "\n");
    }
    result = await turn.result;
  } catch (e) {
    failure = { message: String(e?.message ?? e), code: e?.code };
  }
  let status = null;
  try { if (handle) status = await runtime.getStatus({ handle }); } catch { /* best effort */ }
  try { await runtime.shutdown(); } catch { /* best effort */ }
  // The ledger only feeds quota attribution. Failing to write it must not overwrite the task's
  // own result: the session is then simply absent from the ledger, so the collector ignores its
  // rollout, and the error is reported next to the (unchanged) result.
  let ledgerError = null;
  if (prof.sessionLedger && status?.backendSessionId) {
    try {
      let accountAtEnd = null;
      try { accountAtEnd = prof.accountFingerprint(direct); } catch { accountAtEnd = null; }
      appendFileSync(process.env.AGENTSTACK_CODEX_LEDGER ?? prof.sessionLedger, JSON.stringify(ledgerLine({
        sessionId: status.backendSessionId, runId: req.run_id, accountAtStart, accountAtEnd })) + "\n");
    } catch (e) {
      ledgerError = String(e?.message ?? e);
    }
  }

  const norm = normalizeStatus({ permissions, mcpDenials: acc.mcpDenials, failure, result });
  const out = buildResult({ req, norm, hook, principal: call.principal, status, permissions,
                            mcpDenials: acc.mcpDenials, mcpOnly, direct, result, failure,
                            text: acc.text.join(""), wallMs: Date.now() - t0, evDir, ledgerError });
  writeFileSync(join(evDir, "result.json"), JSON.stringify({ ...out, status_raw: status, usage_events: acc.usage }, null, 1));
  process.stdout.write(JSON.stringify(out) + "\n");
  process.exitCode = exitCodeFor(norm);
}

main().catch((e) => {
  process.stdout.write(JSON.stringify({ status: "FAILED", failure: { message: String(e?.message ?? e) } }) + "\n");
  process.exitCode = 1;
});
