"""#281 router: choose a provider from normalized quota observations. No vendor code.

usage: router.py <policy.json> <observations-dir>
prints one JSON decision: {"decision": "ROUTE"|"HOLD", "provider": ..., "reason": ..., "evaluated": [...]}

Observation files (<obs-dir>/<provider>.json), written by collect_obs.py or by a test:
  {"provider": str, "source": str, "observed_at": ISO-8601 UTC,
   "observed_account": str|null,          # whose quota this is, as the source reports it
   "executing_account": str|null,          # the account the execution layer would run as
   "identity_basis": "email"|"structural", # how the two were obtained
   "windows": {"session": {"used_percent": float, "resets_at": ISO|null},
               "weekly":  {"used_percent": float, "resets_at": ISO|null}}}

Rules, in order, per candidate (policy "candidates" order is preference order):
  1. no observation                      -> ineligible (unknown)
  2. observed_account != executing_account -> ineligible (account_mismatch) — never "close enough"
  3. observation older than max_age_s     -> ineligible (stale) — a stale number is not a number;
     except a reading that aged because the login's access token expired (live_failed_kind
     login_expired): the collector renews that token with the refresh token before reading
     (§109), and a call renews it too, so the last good reading is used until the credential's
     own refresh_token_expires_at (carried on the observation; without it, refreshable_age_s,
     default 14 days), and the verdict says so (§108). Past that it is unknown: a person signs in
  4. a window in require_windows missing   -> ineligible (unknown); other missing windows are
     recorded as "not reported", never assumed empty. require_windows is a list (every
     candidate) or a mapping provider -> list: a vendor that reports no usage figure at all
     (measured: Grok's CLI proxy, OPERATIONS §64) is admitted only where the profile says so,
     and the decision then says it was admitted without one
  5. any reported window used_percent >= its limit -> ineligible (exhausted)
  6. otherwise eligible
First eligible candidate wins. None eligible -> HOLD: the run does not start (fail closed).
"""
import json, math, os, sys
from datetime import datetime, timezone

# How old a kept reading may be and still be used behind an expired access token when the
# observation does not say when the refresh token ends (§108; since §109 the collector carries
# the credential's own refreshTokenExpiresAt and this is the fallback): the vendor's refresh
# token has been observed to live about two weeks (#44). A profile may set quota.refreshable_age_s.
REFRESHABLE_AGE_S = 14 * 86400


def valid_percent(u):
    """A usable utilisation is a real, finite number in [0, 100]. bool is excluded explicitly
    (it is an int in Python). Anything else is not a number the router may act on."""
    return (isinstance(u, (int, float)) and not isinstance(u, bool) and math.isfinite(u)
            and 0 <= u <= 100)


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def evaluate(cand, obs, policy, now):
    r = {"provider": cand}
    if obs is None:
        return {**r, "eligible": False, "why": "unknown: no observation"}
    r.update(source=obs.get("source"), observed_at=obs.get("observed_at"),
             identity_basis=obs.get("identity_basis"))
    oa, ea = obs.get("observed_account"), obs.get("executing_account")
    # Absent is not mismatched. Two accounts that differ is a refusal an operator should act on;
    # nobody having observed this account yet is a state the stack cannot determine, and saying
    # "account_mismatch: observed=None" for it sent one reader looking for a second account that
    # never existed. The two are separated so the bring-up's "every provider's state is knowable"
    # catches the second (measured on a fresh install: the observer had no login yet).
    if not oa:
        # Every provider is read with the login that executes (OPERATIONS §29); the observer is
        # codex's optional second source. So an account nobody has read is a provider with no
        # readable login here — the panel's job — and the message used to send people to the
        # observer instead (the second install's checks, §64).
        return {**r, "eligible": False,
                "why": "unknown: nothing has read this provider's login yet "
                       f"(executing={ea!r}) — sign in on the panel; the quota observer is not it"}
    if not ea:
        return {**r, "eligible": False,
                "why": f"unknown: no executing account for this provider (observed={oa!r})"}
    if oa != ea:
        return {**r, "eligible": False,
                "why": f"account_mismatch: observed={oa!r} executing={ea!r}"}
    try:
        age = (now - parse_ts(obs["observed_at"])).total_seconds()
    except Exception:
        # The source usually knows why it has nothing, and says so. Passing that on is the
        # difference between "unparseable observed_at" — which sends a reader into the plumbing —
        # and "the provider's login expired", which sends them to the panel (OPERATIONS §33).
        detail = str(obs.get("error") or "").strip()
        return {**r, "eligible": False,
                "why": f"unknown: {detail[:160]}" if detail else "unknown: no timestamp on the observation"}
    r["age_s"] = round(age)
    # The door's note: after this reading was taken, the vendor refused a call for the account's
    # sake (an organisation that disabled access, a dead login, a key it does not accept). The
    # reading may still say "within limits"; the next call will not run, and the remedy is the
    # call's own sentence, not the observer's "run `claude login`" (#44, trading's measurement).
    # Unknown, with those words, until a completed call takes the note back.
    note = obs.get("execution_refusal")
    if isinstance(note, dict) and note.get("failure"):
        return {**r, "eligible": False, "login_refused": True,
                "why": f"unknown: the last call was refused for the account's sake — "
                       f"\"{str(note['failure'])[:160]}\" — follow that sentence; a quota reading "
                       f"{round(age)}s old says nothing about it"}
    if age < -60:
        return {**r, "eligible": False, "why": f"unknown: observed_at is {-round(age)}s in the future"}
    if age > policy["max_age_s"]:
        # A reading too old because the login behind it expired is not the ordinary "stale" (a
        # collection that has not run for a while): nothing here will take a new one until a
        # person signs in. Said as `unknown:`, so the bring-up's "every provider's state is
        # knowable" and the panel's standing risk name it, with the remedy (#44). Measured
        # three times in two days before this: every run that needed claude held on "stale".
        if obs.get("live_failed_kind") == "login_expired":
            # §108 (#44, trading's and novel-v2's measurement): the access token lives 8 h and any
            # call through the CLI refreshes it, so the token being expired says nothing about
            # whether a call would run — until the refresh token itself has lapsed, which the
            # vendor does not publish and nothing here can read. So the last good reading stands
            # (its quota numbers are the last known, not the current) up to refreshable_age_s,
            # and the first call is the measurement: it refreshes, or it meets the vendor's
            # refusal, which the door leaves beside the login (§88) and the next route holds on.
            # Said as `unknown:` only past that bound: a login idle that long needs a person.
            # Before §108 this said "nothing here refreshes it; sign in" — false, measured.
            # §109: the credential says when its refresh token ends, and the collector carries it;
            # past that, no refresh is possible and a person signs in. Without it, the observed life.
            rexp = obs.get("refresh_token_expires_at")
            try:
                rexp_s = (parse_ts(rexp) - now).total_seconds() if rexp else None
            except Exception:
                rexp_s = None
            if rexp_s is not None and rexp_s <= 0:
                return {**r, "eligible": False, "login_expired": True,
                        "why": f"unknown: the login's refresh token expired at {rexp} — nothing can renew it; "
                               f"sign in on the panel"}
            bound = policy.get("refreshable_age_s", REFRESHABLE_AGE_S)
            if rexp_s is None and age > bound:
                return {**r, "eligible": False, "login_expired": True,
                        "why": f"unknown: the login's token expired and its last good reading is {round(age)}s old "
                               f"(> {bound}s, the refresh token's observed life) — a login idle that long needs "
                               f"a person; sign in on the panel"}
            r["login_expired"], r["refreshable"] = True, True
        else:
            return {**r, "eligible": False, "why": f"stale: {round(age)}s old > {policy['max_age_s']}s"}
    elif obs.get("live_failed_kind") == "login_expired":
        # still young enough to use, and the login behind it is already dead: said beside the
        # verdict, so the panel can show it before the reading ages out
        r["login_expired"] = True
    wins = obs.get("windows") or {}
    if not isinstance(wins, dict):
        return {**r, "eligible": False, "why": "unknown: windows malformed"}
    req = policy.get("require_windows") or []
    if isinstance(req, dict):
        req = req.get(cand) or []
    for w in req:
        if (wins.get(w) or {}).get("used_percent") is None:
            return {**r, "eligible": False, "why": f"unknown: required {w} window not reported"}
    for w, limit in policy["max_used_percent"].items():
        u = (wins.get(w) or {}).get("used_percent")
        if u is None:
            r[f"{w}_used"] = "not reported"   # optional window: recorded, not assumed
            continue
        if not valid_percent(u):
            return {**r, "eligible": False, "why": f"unknown: {w} used_percent invalid ({u!r})"}
        r[f"{w}_used"] = u
        if u >= limit:
            return {**r, "eligible": False, "why": f"exhausted: {w} {u}% >= {limit}%"}
    if not any((wins.get(w) or {}).get("used_percent") is not None for w in policy["max_used_percent"]):
        # nothing to be within: the profile required no window of this provider, and it reported
        # none. Eligible, and the record says on what basis — identity and freshness only.
        return {**r, "eligible": True, "why": "within limits (no usage window reported; none required of this provider)"}
    if r.get("refreshable"):
        lr = obs.get("login_refresh") or {}
        return {**r, "eligible": True,
                "why": f"within limits as last read {round(age)}s ago — the login's access token expired since; "
                       f"the collector's refresh came back `{lr.get('outcome') or 'not tried'}`"
                       f"{(' (' + str(lr.get('error'))[:80] + ')') if lr.get('error') else ''}, and a call renews it too "
                       f"(§108, §109); a refusal either meets is left for the next route"}
    return {**r, "eligible": True, "why": "within limits"}


def main():
    policy = json.load(open(sys.argv[1]))
    d = sys.argv[2]
    now = parse_ts(os.environ["ROUTER_NOW"]) if os.environ.get("ROUTER_NOW") else datetime.now(timezone.utc)
    evaluated = []
    for cand in policy["candidates"]:
        p = os.path.join(d, f"{cand}.json")
        try:
            # reading and parsing are inside the per-candidate guard too: one corrupt file makes
            # that candidate unknown, it does not stop the choice among the others
            obs = json.load(open(p)) if os.path.exists(p) else None
            evaluated.append(evaluate(cand, obs, policy, now))
        except Exception as e:   # one malformed observation must not stop the whole choice
            evaluated.append({"provider": cand, "eligible": False,
                              "why": f"unknown: observation unreadable ({type(e).__name__})"})
    chosen = next((e for e in evaluated if e["eligible"]), None)
    print(json.dumps({
        "decision": "ROUTE" if chosen else "HOLD",
        "provider": chosen["provider"] if chosen else "",
        "reason": (f"{chosen['provider']}: {chosen['why']}" if chosen
                   else "no eligible provider: " + "; ".join(f"{e['provider']}={e['why']}" for e in evaluated)),
        "evaluated": evaluated,
        "now": now.isoformat(),
    }))


if __name__ == "__main__":
    main()
