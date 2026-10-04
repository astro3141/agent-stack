// Codex over ACP (codex-acp): one provider's half of the adapter (#27). Read from `ctx`, the one
// call's context (login, principal, egress, the MCP url); nothing is kept between calls.
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";

export default function codex(ctx) {
  return {
    agent: "codex",
    preloopSource: "codex_cli",
    // Gateway route comes from ~/.codex/config.toml (Preloop onboarding), which codex-acp
    // reads — unlike acpx's Claude profile. The default ACP mode "agent" hands approvals to
    // Codex's own Guardian reviewer model; "read-only" hands them to the ACP client.
    env() { return { INITIAL_AGENT_MODE: "read-only" }; },
    // Option B: the routing layer owns the provider connection. Its own login lineage lives in
    // /route/codex (not the Preloop-custodied one in ~/.codex); traffic leaves only through the
    // allowlist proxy. The Preloop gateway is not on this path.
    directEnv() {
      return { CODEX_HOME: ctx.loginDir("codex"), ...ctx.egress };
    },
    // Rollouts record no account. The adapter therefore writes a ledger entry per run binding
    // Codex's session id to the login it ran as, so the quota collector can refuse a rollout
    // written under another login (A→B re-login in the same CODEX_HOME).
    accountFingerprint(direct) {
      const home = direct ? ctx.loginDir("codex") : join(homedir(), ".codex");
      const tok = JSON.parse(readFileSync(join(home, "auth.json"), "utf8")).tokens?.id_token ?? "";
      const claims = JSON.parse(Buffer.from((tok.split(".")[1] ?? "").replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8") || "{}");
      return claims.email ? "email:" + createHash("sha256").update(claims.email.toLowerCase()).digest("hex").slice(0, 16) : null;
    },
    sessionLedger: `${ctx.loginsRoot}/codex-session-ledger.jsonl`,
    mcpAuth() {
      return ctx.withPrincipal(() => {
        const t = readFileSync(join(homedir(), ".codex/config.toml"), "utf8");
        const m = t.match(/\[mcp_servers\.preloop\.http_headers\][^[]*?Authorization\s*=\s*'([^']+)'/);
        if (!m) throw new Error("no Preloop MCP bearer in ~/.codex/config.toml");
        return m[1];
      });
    },
    // Shell removed by feature flags. apply_patch has no off switch in this Codex; it stays
    // and, in read-only mode, every use escalates to Preloop approval.
    disableNative() {
      // default_tools_approval_mode=approve on the Preloop MCP server: those calls are decided
      // by Preloop rules downstream. Without it Codex asks the client, and its request names
      // neither the server nor the tool (`_meta.is_mcp_tool_approval` only).
      // The server is defined here in full (url, bearer) rather than relying on the entry
      // Preloop onboarding wrote into ~/.codex/config.toml: with CODEX_HOME=/route/codex that
      // file is not read, and a bare `default_tools_approval_mode` then attaches to nothing
      // (measured: the MCP call went back to human approval). Env only — never written to disk.
      return { CODEX_CONFIG: JSON.stringify({
        features: { shell_tool: false, unified_exec: false },
        mcp_servers: { preloop: {
          url: ctx.mcpUrl,
          http_headers: { Authorization: this.mcpAuth() },
          default_tools_approval_mode: "approve",
        } },
      }) };
    },
    // A query (§89): shell off, web search off (`web_search = "disabled"`, the top-level key of
    // Codex's config; the `features.web_search*` toggles are its deprecated spellings), and no MCP
    // server defined — on the direct route CODEX_HOME=/route/codex carries none of its own.
    // apply_patch has no off switch (above): a use of it is a tool_call event, and TOOLS_USED.
    queryEnv() {
      return { CODEX_CONFIG: JSON.stringify({
        features: { shell_tool: false, unified_exec: false },
        web_search: "disabled",
      }) };
    },
    // Codex gets the Preloop MCP server from CODEX_CONFIG above; attaching it over ACP as well
    // would define it twice.
    mcpViaConfig: true,
  };
}
