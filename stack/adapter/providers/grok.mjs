// Grok Build in xAI's own ACP mode: one provider's half of the adapter (#27). Read from `ctx`,
// the one call's context (login, egress); nothing is kept between calls.

export default function grok(ctx) {
  return {
    agent: "grok-build",
    // xAI's own ACP mode. --no-leader: a fresh backend per run; the shared "leader" process
    // would let runs (and potentially logins) share one agent backend.
    argv: process.env.GROK_TAP ? ["sh", "/work/stack/grok-tap.sh"] : ["grok", "agent", "--no-leader", "stdio"],
    preloopSource: "grok_build",
    // Direct only: there is no Preloop gateway route for Grok. The routing layer's own login
    // (GROK_HOME=/route/grok) and the allowlist proxy.
    env() { return {}; },
    // HOME is separate too: Grok imports Claude Code's user settings from $HOME (~/.claude,
    // ~/.claude.json) for compatibility. Measured: it ran the Preloop PreToolUse hook that
    // onboarding installed for Claude on every Grok tool call — each became a human approval
    // request labelled `claude_code`, and each stalled the run for the hook's 300 s timeout.
    directEnv() { return { GROK_HOME: ctx.loginDir("grok"), HOME: `${ctx.loginDir("grok")}/home`, ...ctx.egress }; },
    directOnly: true,
    // Grok has a Preloop principal of its own; its credential sits in the `preloop` MCP entry of
    // /route/grok/config.toml (docs/record/OPERATIONS.md), which is also why `mcp_principal` cannot apply
    // here: Grok reads the credential from that file, not from what the adapter passes.
    mcpAuthFromFile: true,
    // Without a principal this is still true: the server it uses is the one in its config file.
    // With one, the adapter hands it a server over ACP instead (§49), and this is not reached.
    mcpAuth() { throw new Error("grok reads its Preloop credential from its own config file"); },
    disableNative() { return {}; },
    // Grok did not connect an MCP server handed over ACP (no connection attempt in its log;
    // its tool search waited ~5 min per call for a server "still connecting"). The same server
    // registered in its own config (/route/grok/config.toml, `grok mcp add preloop …`) is healthy.
    mcpViaConfig: true,
    // A call to a tool of the Preloop MCP server (registered as "preloop" in Grok's own config):
    // decided by Preloop's rules at the MCP proxy, so not sent to human approval as well.
    // Normally unreachable: the login's config.toml carries `[permission] allow =
    // ["MCPTool(preloop__*)"]` and denies Bash/Edit/Write/WebFetch/WebSearch, so Grok neither
    // asks about Preloop MCP calls nor runs native write/shell tools. Kept as a fallback.
    // That table is written by stack/grok_posture.py (on login, and on every bring-up) and
    // checked by `up.sh --check` — it was hand-written once, and a second install ran without
    // it: the Cold Reader wrote with native Write, waited for a person, and ended DENIED (§64).
    governedDownstream(raw) {
      const tc = raw.toolCall ?? {};
      return tc._meta?.["x.ai/tool"]?.name === "use_tool" && tc.rawInput?.variant === "UseTool"
        && typeof tc.rawInput?.tool_name === "string" && tc.rawInput.tool_name.startsWith("preloop__");
    },
  };
}
