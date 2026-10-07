// The provider modules as functions of one call's context (#27): what each vendor is given
// comes from the context it was made with, and two calls made in one process do not see each
// other's login or principal. No model, no network, no vendor login; host node or the agent's.
//
//   node stack/adapter/providers_check.mjs          one line per check, exit 1 on a failure
import { readFileSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import claude from "./providers/claude.mjs";
import codex from "./providers/codex.mjs";
import grok from "./providers/grok.mjs";
import { CLAUDE_BUILTIN_TOOLS } from "./permissions.mjs";

const here = dirname(fileURLToPath(import.meta.url));
let bad = 0, n = 0;
const check = (name, ok, got) => {
  n++;
  if (!ok) bad++;
  console.log(`${ok ? "ok  " : "FAIL"}  ${name}${ok ? "" : `  (got ${JSON.stringify(got)})`}`);
};

// the shape run-agent.mjs builds (callContext), with stand-ins for what it reads from the instance
const ctx = ({ login = null, principal = null } = {}) => ({
  login, principal, loginsRoot: "/route",
  loginDir: (p) => `/route/${login ?? p}`,
  withPrincipal: (own) => (principal ? `Bearer job-for-${principal}` : own()),
  egress: { HTTPS_PROXY: "http://egress:8888", NO_PROXY: "console,api" },
  mcpUrl: "http://console/mcp/v1",
});

const A = { login: "claude-work", principal: "novel-author" };
const B = { login: null, principal: null };
const a = { claude: claude(ctx(A)), codex: codex(ctx({ login: "codex-two", principal: "novel-reviewer" })), grok: grok(ctx({ login: "grok-two" })) };
const b = { claude: claude(ctx(B)), codex: codex(ctx(B)), grok: grok(ctx(B)) };

for (const [name, p] of Object.entries(b)) {
  check(`${name}: has what run-agent.mjs calls (agent, preloopSource, env, directEnv, mcpAuth, disableNative)`,
    typeof p.agent === "string" && typeof p.preloopSource === "string" && ["env", "directEnv", "mcpAuth", "disableNative"].every((k) => typeof p[k] === "function"),
    Object.keys(p));
}
check("the Preloop sources are the ones the hooks carry",
  [b.claude.preloopSource, b.codex.preloopSource, b.grok.preloopSource].join() === "claude_code,codex_cli,grok_build",
  [b.claude.preloopSource, b.codex.preloopSource, b.grok.preloopSource]);

// the login travels with the call
check("claude: the login named by the call is the config dir", a.claude.directEnv().CLAUDE_CONFIG_DIR === "/route/claude-work", a.claude.directEnv().CLAUDE_CONFIG_DIR);
check("claude: no login named → the provider's own", b.claude.directEnv().CLAUDE_CONFIG_DIR === "/route/claude", b.claude.directEnv().CLAUDE_CONFIG_DIR);
check("codex: CODEX_HOME follows the call", a.codex.directEnv().CODEX_HOME === "/route/codex-two" && b.codex.directEnv().CODEX_HOME === "/route/codex",
  [a.codex.directEnv().CODEX_HOME, b.codex.directEnv().CODEX_HOME]);
check("grok: GROK_HOME and its separate HOME follow the call",
  a.grok.directEnv().GROK_HOME === "/route/grok-two" && a.grok.directEnv().HOME === "/route/grok-two/home" && b.grok.directEnv().GROK_HOME === "/route/grok",
  [a.grok.directEnv(), b.grok.directEnv().GROK_HOME]);
check("every direct route carries the egress proxy", ["claude", "codex", "grok"].every((k) => b[k].directEnv().HTTPS_PROXY === "http://egress:8888"));

// the principal travels with the call, and only with it
const cfgA = JSON.parse(a.codex.disableNative().CODEX_CONFIG);
check("codex: a named principal's credential is the one written into CODEX_CONFIG",
  cfgA.mcp_servers.preloop.http_headers.Authorization === "Bearer job-for-novel-reviewer" && cfgA.mcp_servers.preloop.url === "http://console/mcp/v1",
  cfgA.mcp_servers.preloop);
check("codex: shell stays off, MCP calls are decided downstream",
  cfgA.features.shell_tool === false && cfgA.features.unified_exec === false && cfgA.mcp_servers.preloop.default_tools_approval_mode === "approve", cfgA.features);
check("codex: the session ledger sits under the logins root", b.codex.sessionLedger === "/route/codex-session-ledger.jsonl", b.codex.sessionLedger);
check("claude: a named principal's credential, without reading the login's file", a.claude.mcpAuth() === "Bearer job-for-novel-author", a.claude.mcpAuth());
let threw = "";
try { b.grok.mcpAuth(); } catch (e) { threw = String(e.message); }
check("grok: its own credential is in its config file, never passed", /own config file/.test(threw), threw);

// a call made after another does not change what the first was given
const before = JSON.stringify([a.claude.directEnv(), a.codex.directEnv(), a.grok.directEnv(), a.claude.mcpAuth()]);
claude(ctx({ login: "someone-else", principal: "other-role" })); codex(ctx({ login: "x" })); grok(ctx({ login: "y" }));
check("two calls in one process: the second does not reach the first", before === JSON.stringify([a.claude.directEnv(), a.codex.directEnv(), a.grok.directEnv(), a.claude.mcpAuth()]));

// native tools: what each vendor is told to switch off
const cwd = mkdtempSync(join(tmpdir(), "providers-check-"));
try {
  b.claude.disableNative(cwd, ["WebFetch", "Bash"]);
  const s = JSON.parse(readFileSync(join(cwd, ".claude/settings.json"), "utf8")).permissions;
  check("claude: native write/shell denied in the workspace's settings; only allowable read tools let through",
    ["Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"].every((t) => s.deny.includes(t)) && JSON.stringify(s.allow) === '["WebFetch"]', s);
} finally { rmSync(cwd, { recursive: true, force: true }); }

// which Preloop MCP calls are decided by Preloop's rules rather than sent to a person
check("claude: the server the adapter attached is decided downstream; another is not",
  b.claude.governedDownstream({ toolCall: { _meta: { claudeCode: { mcpServer: { name: "preloop", source: "dynamic" } } } } }) === true
  && b.claude.governedDownstream({ toolCall: { _meta: { claudeCode: { mcpServer: { name: "preloop", source: "user" } } } } }) === false);
check("grok: use_tool on a preloop__ tool is decided downstream; a native tool is not",
  b.grok.governedDownstream({ toolCall: { _meta: { "x.ai/tool": { name: "use_tool" } }, rawInput: { variant: "UseTool", tool_name: "preloop__write_file" } } }) === true
  && b.grok.governedDownstream({ toolCall: { _meta: { "x.ai/tool": { name: "write" } }, rawInput: {} } }) === false);

// a closed call (§89, §102): every provider has its own way of asking for no tools, and none brings an MCP server
const qdir = mkdtempSync(join(tmpdir(), "agentstack-closed-"));
check("closed: every provider answers closedEnv", ["claude", "codex", "grok"].every((k) => typeof b[k].closedEnv === "function"));
b.claude.closedEnv(qdir);
const qdeny = JSON.parse(readFileSync(join(qdir, ".claude/settings.json"), "utf8")).permissions;
check("claude: a closed call denies every built-in tool the stack knows by name — the read-only ones, the web ones, the report class (ReportFindings, #93) — and the Preloop server, and allows none",
  CLAUDE_BUILTIN_TOOLS.every((t) => qdeny.deny.includes(t)) && qdeny.deny.includes("mcp__preloop")
  && ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "ReportFindings", "SendUserFile", "Workflow"].every((t) => qdeny.deny.includes(t))
  && !("allow" in qdeny), qdeny);
const odir = mkdtempSync(join(tmpdir(), "agentstack-open-"));
b.claude.disableNative(odir, ["WebSearch"]);
const odeny = JSON.parse(readFileSync(join(odir, ".claude/settings.json"), "utf8")).permissions;
check("claude: an open call refuses what writes, executes, reports, schedules or steers (ReportFindings, SendUserFile, Workflow, Bash, Write among them), keeps what reads and the deferred-tool loader, and allows only the profile's web tools",
  ["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "ReportFindings", "SendUserFile", "Workflow", "ScheduleWakeup", "SendMessage", "CronCreate"].every((t) => odeny.deny.includes(t))
  && ["Read", "Glob", "Grep", "WebSearch", "WebFetch", "ToolSearch", "AskUserQuestion"].every((t) => !odeny.deny.includes(t))
  && JSON.stringify(odeny.allow) === JSON.stringify(["WebSearch"]), odeny);
rmSync(odir, { recursive: true, force: true });
const qcfg = JSON.parse(b.codex.closedEnv().CODEX_CONFIG);
check("codex: a closed call turns shell and web search off and defines no MCP server",
  qcfg.features.shell_tool === false && qcfg.features.unified_exec === false && qcfg.web_search === "disabled" && !("mcp_servers" in qcfg), qcfg);
check("grok: a closed call adds nothing — its posture is the login's", Object.keys(b.grok.closedEnv()).length === 0);
rmSync(qdir, { recursive: true, force: true });

// and the entry point keeps no per-call state of its own
const ra = readFileSync(join(here, "..", "run-agent.mjs"), "utf8");
check("run-agent.mjs: no module-level `let` — login, principal and hook are the call's",
  !/^let /m.test(ra) && !/\b(LOGIN|PRINCIPAL|HOOK_FOR)\b/.test(ra), (ra.match(/^let .*/gm) ?? []));
check("run-agent.mjs: names no provider's internals, only the three modules",
  ["CLAUDE_CONFIG_DIR", "CODEX_HOME", "GROK_HOME", "codex_cli", "grok_build"].every((x) => !ra.includes(x))
  && ["providers/claude.mjs", "providers/codex.mjs", "providers/grok.mjs"].every((x) => ra.includes(x)));

console.log(`${n - bad}/${n} provider checks passed`);
process.exitCode = bad ? 1 : 0;
