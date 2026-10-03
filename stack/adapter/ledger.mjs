// The codex session ledger line: binds a vendor session to the login it ran as, so the quota
// collector can refuse a rollout written under another login (#27, the pure half).
export function ledgerLine({ sessionId, runId, accountAtStart, accountAtEnd, at = new Date().toISOString() }) {
  return { session_id: sessionId, run_id: runId, at,
    // a login that changed during the run binds the session to no account
    account: accountAtStart && accountAtStart === accountAtEnd ? accountAtStart : null,
    account_at_start: accountAtStart, account_at_end: accountAtEnd };
}
