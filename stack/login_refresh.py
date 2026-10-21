"""Trade an expired Claude access token for a new one with the login's own refresh token (§109).

Two tokens live in `<login>/.credentials.json` (`claudeAiOauth`): the access token, which every
API call carries and which lives 8 hours (`expiresAt`), and the refresh token, which obtains the
next access token and lives weeks (`refreshTokenExpiresAt`); both are written there by the CLI,
and the CLI itself renews the first with the second in the middle of a model call. Until §109 the
stack never did — decision 2 (DECISIONS-2026-10-04): the stack does not sign a person in — and so
a login nobody had called for 8 hours held every run that needed it, until a call happened to
run (trading, #44: a weekday's runs survived on a neighbouring workflow's call). Decision 2 is
narrowed, not reversed: **the stack still makes no login** (a person's, on the panel), **but it
does what the CLI does between calls** — one POST to the vendor's token endpoint with the refresh
token, client id and scopes the file already holds, and the answer written back the way the CLI
writes it. Measured on Claude Code 2.1.287 (its strings): the endpoint, the body, the fields it
stores, and its rule for writing — only when the refresh token on disk is still the one it read
(a sibling may have refreshed meanwhile; its write wins and this one is dropped).

No model call, no login flow, nothing invented: a request the file already has every input for.
What the vendor refuses (`invalid_grant`: a dead refresh token, a revoked login) is left beside
the login as the door's own refusal note (§88), so the router says a person is needed, with the
vendor's words. A transport failure writes nothing and leaves no note: the reading is tried as
before, and the next collection tries again.
"""
import json, os, time, urllib.error, urllib.request

TOKEN_URL = "https://platform.claude.com/v1/oauth/token"     # Claude Code 2.1.287, TOKEN_URL
# The CLI sends client_id and scope on every refresh: the credential's own when it has them, its
# constants when it does not (an older credential carries neither). §109 sent them only when the
# file had them, and the vendor answered the first live expiry with HTTP 400 "Invalid request
# format" (#44, 2026-10-21, §110). Both read from the 2.1.287 binary.
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
DEFAULT_SCOPES = ["user:profile", "user:inference", "user:sessions:claude_code", "user:mcp_servers",
                  "user:file_upload", "user:plugins"]       # qZe() with PLUGINS_SCOPE_REGISTERED, in its order
TIMEOUT_S = 30
# a token this close to its end is renewed now rather than at its end: a reading and the call it
# admits are minutes apart, and an access token that expires between them is the hold this exists for
EARLY_S = 300


def read(path):
    """The credential file's `claudeAiOauth` block, or None when there is no file or no block."""
    try:
        d = json.load(open(path, encoding="utf-8"))
        c = d.get("claudeAiOauth")
        return c if isinstance(c, dict) else None
    except Exception:
        return None


def _epoch_s(v):
    """A stored timestamp in seconds: the CLI writes milliseconds."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v / 1000.0 if v > 1e11 else v


def state(cred, now=None):
    """What the tokens are, now: `fresh` (the access token has time left), `expired` (and the
    refresh token has time left, or says nothing about its end), `refresh_expired`,
    `no_refresh_token`, `no_credential`."""
    now = time.time() if now is None else now
    if not cred:
        return "no_credential"
    if not cred.get("refreshToken"):
        return "no_refresh_token"
    exp = _epoch_s(cred.get("expiresAt"))
    if exp is not None and exp - EARLY_S > now:
        return "fresh"
    rexp = _epoch_s(cred.get("refreshTokenExpiresAt"))
    if rexp is not None and rexp <= now:
        return "refresh_expired"
    return "expired"


class Refused(Exception):
    """The vendor refused the refresh for the account's sake (`invalid_grant`: a revoked or dead
    refresh token, an account it will not serve): the sentence is the remedy. Any other 4xx is a
    request the stack built wrongly, and that is a failure of this code, not of the login."""


def exchange(cred, egress=None, post=None):
    """One POST to the token endpoint. Returns the vendor's answer (access_token, expires_in,
    refresh_token?, refresh_token_expires_in?, scope?). Raises Refused on the vendor's 4xx with
    its words, any other exception on transport."""
    body = {"grant_type": "refresh_token", "refresh_token": cred["refreshToken"],
            "client_id": cred.get("clientId") or CLIENT_ID,
            "scope": " ".join(cred["scopes"] if cred.get("scopes") else DEFAULT_SCOPES)}
    if post is not None:
        return post(body)
    handlers = [urllib.request.ProxyHandler({k.lower().replace("_proxy", ""): v for k, v in (egress or {}).items()
                                             if k.lower() in ("https_proxy", "http_proxy") and v})]
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(TOKEN_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "agent-stack/login_refresh"})
    try:
        with opener.open(req, timeout=TIMEOUT_S) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")[:400]
        raise classify(e.code, text)


def classify(code, text):
    """What a non-2xx answer is: `invalid_grant` is the vendor refusing the login (Refused, the
    §88 note); every other answer is this request's or the vendor's failure (RuntimeError, no
    note, tried again next time). The words are kept either way. Two shapes are read: OAuth's
    {error, error_description} and the API's {type: error, error: {type, message}}."""
    try:
        j = json.loads(text)
    except ValueError:
        j = {}
    e = j.get("error")
    if isinstance(e, dict):
        err, desc = str(e.get("type") or ""), str(e.get("message") or "")
    else:
        err, desc = str(e or ""), str(j.get("error_description") or "")
    words = f"{err}: {desc}".strip(": ") or text[:200]
    if err == "invalid_grant":
        return Refused(f"the login's refresh token was refused by the vendor (invalid_grant: {desc or 'no reason given'})")
    return RuntimeError(f"the token refresh request failed (HTTP {code}, {words[:200]})")


def save_cas(path, expected_refresh_token, answer, now=None):
    """Write the answer into the file the way the CLI does, only if the refresh token on disk is
    still `expected_refresh_token`: a sibling that refreshed first wins, and its write is kept.
    Returns True when written."""
    now = time.time() if now is None else now
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return False
    c = d.get("claudeAiOauth")
    if not isinstance(c, dict) or c.get("refreshToken") != expected_refresh_token:
        return False
    new = dict(c)
    new["accessToken"] = answer["access_token"]
    if answer.get("refresh_token"):
        new["refreshToken"] = answer["refresh_token"]
    new["expiresAt"] = int((now + float(answer["expires_in"])) * 1000)
    if answer.get("refresh_token_expires_in") is not None:
        new["refreshTokenExpiresAt"] = int((now + float(answer["refresh_token_expires_in"])) * 1000)
    if answer.get("scope"):
        new["scopes"] = str(answer["scope"]).split()
    d["claudeAiOauth"] = new
    tmp = path + ".refresh.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f)
    try:
        os.chmod(tmp, os.stat(path).st_mode & 0o777)
    except OSError:
        pass
    os.replace(tmp, path)
    return True


def summary_path(logins_root, provider, login):
    return os.path.join(logins_root, ".quota", f"{provider}-{login}.refresh.json")


def refresh(path, logins_root=None, provider="claude", login="claude", egress=None, post=None, now=None):
    """The whole step, never raising: read, decide, exchange, write, note. Returns the summary
    it also leaves beside the quota reading: {at, outcome, expires_at?, refresh_expires_at?, error?}.

    outcome: fresh | refreshed | adopted (a sibling wrote first) | refused (the vendor's words,
    the §88 note left) | failed (transport; nothing written, no note) | refresh_expired |
    no_refresh_token | no_credential
    """
    now = time.time() if now is None else now
    cred = read(path)
    st = state(cred, now)
    out = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), "outcome": st}
    if cred:
        for k, f in (("expiresAt", "expires_at"), ("refreshTokenExpiresAt", "refresh_expires_at")):
            s = _epoch_s(cred.get(k))
            if s is not None:
                out[f] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s))
    if st == "expired":
        try:
            ans = exchange(cred, egress=egress, post=post)
            if not ans.get("access_token") or ans.get("expires_in") is None:
                raise RuntimeError(f"the vendor's answer has no access_token/expires_in: {str(ans)[:200]}")
            if save_cas(path, cred["refreshToken"], ans, now):
                out["outcome"] = "refreshed"
            else:
                out["outcome"] = "adopted"
            c2 = read(path) or {}
            for k, f in (("expiresAt", "expires_at"), ("refreshTokenExpiresAt", "refresh_expires_at")):
                s = _epoch_s(c2.get(k))
                if s is not None:
                    out[f] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(s))
        except Refused as e:
            out["outcome"], out["error"] = "refused", str(e)[:300]
            if logins_root:
                try:
                    import execution
                    note = f"{e} — sign in on the panel"
                    assert execution.login_refusal(note)      # the words must be the note's own kind (§110)
                    execution.note_refusal(logins_root, provider, login,
                                           {"status": "FAILED", "failure": note, "run_id": "login_refresh"})
                except Exception:
                    pass
        except Exception as e:
            out["outcome"], out["error"] = "failed", f"{type(e).__name__}: {e}"[:300]
    elif st == "refresh_expired":
        out["error"] = f"the refresh token expired at {out.get('refresh_expires_at')}: a person signs in again on the panel"
    if logins_root:
        try:
            p = summary_path(logins_root, provider, login)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            json.dump(out, open(p + ".tmp", "w"))
            os.replace(p + ".tmp", p)
        except Exception:
            pass
    return out


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", "/route/claude"), ".credentials.json")
    print(json.dumps(refresh(p, egress={k: v for k, v in os.environ.items() if k.lower().endswith("_proxy")})))
