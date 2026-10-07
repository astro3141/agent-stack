// What the adapter sends Preloop about a permission request, and how Preloop's answer (or its
// absence) becomes the request's outcome — the pure half of askPreloop (#27). The HTTP call,
// the signal and the log stay in run-agent.mjs.

// Native tools a profile may let run without asking: read-only, and bounded by the egress allowlist.
export const NATIVE_ALLOWABLE = ["WebSearch", "WebFetch"];

// The built-in tools of Claude Code, by name — measured on the 2.1.x build (2026-10-07, §104,
// #93), the SDK's aliases included (a name this version does not have is ignored by the
// settings file). This is a deny list by name, and that is all the stack has on this path: the
// SDK's `tools` option (the surface itself) does not reach the agent through acpx 0.19.4, and
// `allowedTools` — what the stack sent until §104 — is the SDK's auto-allow list, not a
// restriction. So a closed call refuses every name here and runs one turn; a tool this list does
// not name is visible to the model, and its use is TOOLS_USED. A new Claude Code pin re-measures
// the list (docs/update-day.md); the full verify level asks a closed call what it can see.
export const CLAUDE_BUILTIN_TOOLS = [
  "Agent", "Artifact", "ArtifactComments", "ArtifactData", "AskUserQuestion", "Bash", "BashOutput",
  "Brief", "CronCreate", "CronDelete", "CronList", "DesignSync", "Edit", "EnterPlanMode",
  "EnterWorktree", "ExitPlanMode", "ExitWorktree", "Glob", "Grep", "KillBash", "KillShell", "LS",
  "ListAgents", "ListConnectors", "ListMcpResources", "ListMcpResourcesTool", "ListPeers",
  "ListPlugins", "ListSkills", "Monitor", "MultiEdit", "NotebookEdit", "NotebookRead",
  "PushNotification", "Read", "ReadMcpResource", "ReadMcpResourceDir", "ReadMcpResourceDirTool",
  "ReadMcpResourceTool", "ReadNotifications", "ReportFindings", "ScheduleWakeup",
  "SearchMcpRegistry", "SearchPlugins", "SearchSkills", "SendMessage", "SendUserFile",
  "SendUserMessage", "ShowOnboardingRolePicker", "Skill", "SlashCommand", "SuggestConnectors",
  "SuggestPluginInstall", "SuggestSkills", "Task", "TaskCreate", "TaskGet", "TaskList", "TaskStop",
  "TaskUpdate", "TodoWrite", "ToolSearch", "WebFetch", "WebSearch", "Workflow", "Write",
];
// An open call with native_tools: false keeps what reads (and the loader of deferred tools, and
// the question the ACP adapter renders as a form); everything that writes, executes, reports,
// schedules or steers is refused by name — a report-class tool reached for because a prompt's
// vocabulary matched it (ReportFindings, #93) is then refused instead of waiting on an approval.
export const CLAUDE_OPEN_KEEP = ["Read", "Glob", "Grep", "LS", "NotebookRead", "TodoWrite", "ToolSearch",
                                 "WebSearch", "WebFetch", "AskUserQuestion", "Agent", "Task", "Skill"];
export const CLAUDE_OPEN_DENY = CLAUDE_BUILTIN_TOOLS.filter((t) => !CLAUDE_OPEN_KEEP.includes(t));
export const CLAUDE_CLOSED_DENY = [...CLAUDE_BUILTIN_TOOLS, "mcp__preloop"];

export function permissionBody(tc, inferredKind, source, runId, cwd) {
  return {
    tool_name: tc.title?.split(" ")[0] || tc.kind || "unknown",
    // What the approver sees. Claude puts the target in rawInput; Codex sends rawInput null
    // and carries the edit as ACP diff content + locations. Forward both, so an approver is
    // never asked to approve "Edit files" with no file named.
    tool_input: {
      ...(tc.rawInput ?? {}),
      _acp_kind: tc.kind ?? inferredKind, _acp_title: tc.title,
      _acp_locations: (tc.locations ?? []).map((l) => l.path),
      _acp_diffs: (tc.content ?? []).filter((c) => c.type === "diff")
        .map((c) => ({ path: c.path, new_text: (c.newText ?? "").slice(0, 4000), is_new: c.oldText == null })),
    },
    source,
    session_id: runId,
    cwd,
    agent_reasoning: `run ${runId} via acpx/${source}`,
    // client_decision deliberately omitted: the adapter holds no policy of its own.
  };
}

// The event the run keeps for one request, given what Preloop answered (`ans`), what went wrong
// on the way (`err`), and whether the run's deadline had passed (`aborted`).
export function permissionEvent({ tc, inferredKind, raw, body, ans, err, aborted, started, now = Date.now() }) {
  return {
    at: new Date(now).toISOString(), ms: now - started,
    acp_kind: tc.kind ?? inferredKind ?? null, title: tc.title ?? null, input: body.tool_input,
    raw,   // local evidence only; never sent anywhere
    preloop: ans ?? null, error: err ?? null,
    outcome: ans?.decision === "allow" ? "allow_once" : "reject_once",
    denial: ans?.decision === "allow" ? null
      : aborted ? "run_ended_awaiting_approval"
      : err ? "control_unavailable" : ans?.timed_out ? "approval_expired" : "denied",
  };
}

// A request decided without asking anyone: a read-only tool the profile allows, or a call to
// the Preloop MCP server itself (its rules decide at the proxy).
export function decidedLocally(tc, raw, routed) {
  return { at: new Date().toISOString(), acp_kind: tc.kind ?? null, title: tc.title ?? null,
    raw, outcome: "allow_once", denial: null, preloop: null, error: null, routed };
}

// A request refused without asking anyone: a closed call (§89, §102) has no tools, so a tool the
// model reached for is not sent to Preloop as if it could be approved — it is refused here,
// logged, and the door reads it, with the tool_call event beside it, as TOOLS_USED.
export function refusedLocally(tc, raw, routed) {
  return { at: new Date().toISOString(), acp_kind: tc.kind ?? null, title: tc.title ?? null,
    raw, outcome: "reject_once", denial: "closed_no_tools", preloop: null, error: null, routed };
}
