// What the adapter sends Preloop about a permission request, and how Preloop's answer (or its
// absence) becomes the request's outcome — the pure half of askPreloop (#27). The HTTP call,
// the signal and the log stay in run-agent.mjs.

// Native tools a profile may let run without asking: read-only, and bounded by the egress allowlist.
export const NATIVE_ALLOWABLE = ["WebSearch", "WebFetch"];

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
