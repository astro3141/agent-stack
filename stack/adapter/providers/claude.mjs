// Claude Code over ACP (acpx's "claude" agent): one provider's half of the adapter (#27).
// Everything here is read from `ctx`, the one call's context that run-agent.mjs builds from the
// request: which login, which principal, which egress. Nothing is kept between calls.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { NATIVE_ALLOWABLE } from "../permissions.mjs";

export default function claude(ctx) {
  return {
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
    // Option B: the routing layer's own Claude login (CLAUDE_CONFIG_DIR=/route/claude, a lineage
    // separate from the one Preloop custodies) through the allowlist proxy. The gateway variables
    // from env() are NOT passed on this route (directReplacesEnv), so nothing points at Preloop's
    // gateway. CLAUDE_CONFIG_DIR also moves Claude's user tier (settings, .claude.json) away from
    // ~/.claude, where onboarding installed the Preloop hook and MCP entry.
    directEnv() { return { CLAUDE_CONFIG_DIR: ctx.loginDir("claude"), ...ctx.egress }; },
    directReplacesEnv: true,
    // This principal's Preloop MCP bearer (onboarding wrote it into ~/.claude.json).
    mcpAuth() {
      return ctx.withPrincipal(() =>
        JSON.parse(readFileSync(join(homedir(), ".claude.json"), "utf8")).mcpServers.preloop.headers.Authorization);
    },
    // Native write/shell removed through the workspace's project settings — acpx loads that
    // tier, and a deny rule cannot be lifted by another tier. The Preloop policy forbids MCP
    // writes under .claude/, so the agent cannot rewrite this file.
    // `allow` is the profile's tools.native_allow — read-only tools a profile lets run without
    // asking (WebSearch, WebFetch; cfg.py refuses anything else). Where they can reach is still the
    // egress allowlist's to decide. Without it every web lookup waits for a person, and an
    // unattended run's lookups expire (measured: devflow preparation, approval_expired).
    disableNative(cwd, allow = []) {
      mkdirSync(join(cwd, ".claude"), { recursive: true });
      const safe = allow.filter((t) => NATIVE_ALLOWABLE.includes(t));
      writeFileSync(join(cwd, ".claude/settings.json"), JSON.stringify(
        { permissions: { deny: ["Write", "Edit", "MultiEdit", "NotebookEdit", "Bash"],
                         ...(safe.length ? { allow: safe } : {}) } }) + "\n");
      return {};
    },
    // A query (§89): no tool at all. Every native tool Claude Code has, by name, and the Preloop MCP
    // server the user tier may carry (the gateway route's ~/.claude.json) are denied in the
    // workspace's project settings; the session is also asked for allowedTools [] and one turn.
    // A name Claude does not have is ignored, so the list may be longer than one version's tools.
    // Whether a denied tool is removed or only refused is the vendor's; a use shows as a
    // tool_call event either way, and the door then says TOOLS_USED.
    queryEnv(cwd) {
      mkdirSync(join(cwd, ".claude"), { recursive: true });
      writeFileSync(join(cwd, ".claude/settings.json"), JSON.stringify(
        { permissions: { deny: ["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "Read", "Glob", "Grep",
                                "LS", "WebSearch", "WebFetch", "Task", "Agent", "TodoWrite", "NotebookRead",
                                "ToolSearch", "Skill", "SlashCommand", "BashOutput", "KillShell",
                                "ExitPlanMode", "EnterPlanMode", "AskUserQuestion", "mcp__preloop"] } }) + "\n");
      return {};
    },
    // A call to the Preloop MCP server that the adapter itself attached. Its decision is made
    // by Preloop's rules at the MCP proxy, so it is not sent to human approval as well.
    // (Measured: an `allow: ["mcp__preloop"]` rule in project settings did not stop Claude
    // from asking for this ACP-attached, `source: "dynamic"` server.)
    governedDownstream(raw) {
      const s = raw.toolCall?._meta?.claudeCode?.mcpServer;
      return s?.name === "preloop" && s?.source === "dynamic";
    },
  };
}
