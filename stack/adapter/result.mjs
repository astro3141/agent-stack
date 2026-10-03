// The adapter's result — the model-free half of run-agent.mjs (#27).
//
// What a turn's events fold into (text, usage, the MCP denials Preloop's proxy answered as
// ordinary results), how the normalized status is decided, and the one result shape the adapter
// prints and writes. Nothing here starts a process or reads a credential, which is why it can
// be replayed against a recorded run: stack/adapter/replay.mjs feeds the fixtures under
// stack/fixtures/run-agent/ through these functions and compares with the result.json each run
// wrote on the instance.

// Preloop's MCP proxy returns a rule denial as an ordinary result (isError: false) whose text
// starts "Access denied:". Matching that text is the only signal available; it is fragile and
// would break silently if Preloop reworded it — which is what the replay is for.
export const DENIAL_RE = /Access denied:/;

export function mcpDenialOf(ev) {
  if (ev.type !== "tool_call") return null;
  if (!DENIAL_RE.test(JSON.stringify(ev.rawOutput ?? ev.content ?? ev.text ?? ""))) return null;
  return { title: ev.title ?? null, toolCallId: ev.toolCallId ?? null,
    text: JSON.stringify(ev.rawOutput ?? ev.content ?? ev.text).match(/Access denied:[^"\\]*/)?.[0] ?? null };
}

// One event at a time, into the three accumulators the run keeps (the live loop also appends the
// raw event to events.jsonl between calls).
export function take(acc, ev) {
  if (ev.type === "text_delta" && ev.stream !== "thought") acc.text.push(ev.text);
  if (ev.type === "status" && ev.tag === "usage_update") acc.usage.push(ev);
  const d = mcpDenialOf(ev);
  if (d) acc.mcpDenials.push(d);
  return acc;
}
export const accumulator = () => ({ text: [], usage: [], mcpDenials: [] });
export function fold(events) {
  return events.reduce(take, accumulator());
}

// Normalized status. TIMED_OUT = the run deadline passed while an approval was still open;
// the run deadline must exceed the approval window or every unanswered approval ends here.
// A denial is never a generic failure: it must not be retried on another provider, because
// that would turn "not approved" into "try someone else".
export function normalizeStatus({ permissions = [], mcpDenials = [], failure = null, result = null }) {
  const denials = permissions.filter((p) => p.outcome !== "allow_once");
  return denials.some((d) => d.denial === "run_ended_awaiting_approval") ? "TIMED_OUT"
    : denials.some((d) => d.denial === "control_unavailable") ? "CONTROL_UNAVAILABLE"
    : denials.length || mcpDenials.length ? "DENIED"
    : failure || result?.status === "failed" ? "FAILED"
    : result?.status === "cancelled" ? "CANCELLED"
    : "COMPLETED";
}

// What of a permission event goes into the result: never `raw` (local evidence only) or the
// full Preloop answer, only its request id.
export const permissionView = ({ acp_kind, title, outcome, denial, preloop, error, routed }) =>
  ({ acp_kind, title, outcome, denial, request_id: preloop?.request_id ?? null, error, routed: routed ?? "preloop_approval" });

export function buildResult({ req, norm, hook, principal, status, permissions, mcpDenials, mcpOnly, direct,
                              result, failure, text, wallMs, evDir, ledgerError }) {
  return {
    run_id: req.run_id,
    status: norm,
    // which onboarded agent's credential was presented, and whether it was the matching one
    hook: hook ? { principal: hook.hook.runtime_principal ?? null, source: hook.hook.source ?? null, matched: hook.matched } : null,
    retryable_elsewhere: norm === "FAILED" && (result?.error?.retryable ?? false),
    provider: req.provider,
    mcp_principal: principal ?? "",
    model: {
      requested: req.model ?? null,
      session_reported: status?.models?.currentModelId ?? status?.model ?? null,
      served: "unknown",   // nothing on this path reports the served model; do not infer it
    },
    permissions: permissions.map(permissionView),
    mcp_denials: mcpDenials,
    native_tools: !mcpOnly,
    model_route: direct ? "direct" : "preloop_gateway",
    turn: result ?? null,
    failure: failure ?? null,
    text,
    wall_ms: wallMs,
    evidence_dir: evDir,
    ledger_error: ledgerError,
  };
}

export const exitCodeFor = (norm) => (norm === "COMPLETED" ? 0 : norm === "DENIED" ? 3 : 1);
