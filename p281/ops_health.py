"""How has this stack been doing — the thing to read after a week of unattended cycles.

usage: ops_health.py [--json] [--last N]        (inside the agent container)

It reads what unattended operation already leaves behind and says nothing it cannot read:

  evidence/ops/cycles.jsonl     one line per cycle from scripts/cycle.sh — and per skip and per
                                refusal, which are the two things a scheduler hides best
  evidence/checks/last.json     when the stack was last checked and what failed
  evidence/soak/*/summary.json  what a measured soak found growing, if one was run
  p281/capabilities.py          what the stack can do *now*

What it deliberately does not do: decide that anything is wrong. It reports the counts, the spread
of durations, the growth, and the capabilities; whether that is acceptable for this operation is
the operator's judgement (CONTRACT.md).
"""
import glob, json, os, statistics, sys, time, urllib.error, urllib.request

sys.path.insert(0, "/work/p281")
import capabilities
import settings

OPS = "/work/evidence/ops/cycles.jsonl"


def cycles(last=50):
    rows = []
    if os.path.isfile(OPS):
        for line in open(OPS, encoding="utf-8"):
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows[-last:]


def summarise(rows):
    ran = [r for r in rows if "outcome" in r]
    skipped = [r for r in rows if r.get("skipped")]
    refused = [r for r in rows if "refused" in r]
    secs = [r["seconds"] for r in ran if isinstance(r.get("seconds"), (int, float))]
    ended = {}
    for r in ran:
        ended[(r["outcome"] or {}).get("ended_at") or "unknown"] = \
            ended.get((r["outcome"] or {}).get("ended_at") or "unknown", 0) + 1
    unrecorded = sum(1 for r in ran if not (r["outcome"] or {}).get("mlflow"))
    # the reason a cycle stopped where it did — the same hold every night is the thing to see
    reasons = {}
    for r in ran:
        why = ((r["outcome"] or {}).get("reason") or "").strip()
        if why and (r["outcome"] or {}).get("ended_at") != "done_cycle":
            reasons[why[:120]] = reasons.get(why[:120], 0) + 1
    errs = [(r.get("ui"), (r["outcome"] or {}).get("record_error"))
            for r in ran if (r["outcome"] or {}).get("record_error")]
    return {
        "cycles_recorded": len(ran),
        "skipped_busy": len(skipped),
        "refused": len(refused),
        "refused_why": [list((r.get("refused") or {}).get("why", {})) for r in refused][-3:],
        "ended": ended,
        "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:5]),
        "seconds": {"min": min(secs), "median": round(statistics.median(secs), 1),
                    "max": max(secs)} if secs else None,
        "not_in_mlflow": unrecorded,
        "record_errors": errs[-3:],
        "first_at": ran[0]["at"] if ran else None,
        "last_at": ran[-1]["at"] if ran else None,
    }


def stuck_lock(d="/work/evidence/ops/.cycle.lock.d"):
    """A lock left by a killed cycle skips every cycle after it — silently, unless it is shown."""
    if not os.path.isdir(d):
        return None
    try:
        since = open(f"{d}/started", encoding="utf-8").read().strip()
        age = round(time.time() - float(open(f"{d}/started_epoch", encoding="utf-8").read().strip()))
    except Exception:
        since, age = "unknown", None
    return {"since": since, "age_s": age, "path": d,
            "clear_with": "rmdir, after checking that no cycle is running"}


def checks():
    p = "/work/evidence/checks/last.json"
    if not os.path.isfile(p):
        return {"at": None, "ok": None, "note": "no check has been recorded"}
    d = json.load(open(p, encoding="utf-8"))
    age = None
    try:
        age = round(time.time() - time.mktime(time.strptime(d["at"], "%Y-%m-%dT%H:%M:%SZ"))
                    + time.timezone)
    except Exception:
        pass
    return {"at": d.get("at"), "age_s": age, "ok": d.get("ok"),
            "composition": d.get("composition"), "failed": d.get("failed")}


def soaks():
    out = []
    for f in sorted(glob.glob("/work/evidence/soak/*/summary.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except ValueError:
            continue
        out.append({"soak": os.path.basename(os.path.dirname(f)), "cycles": d.get("cycles"),
                    "memory_total_mib": d.get("memory_mib_total"),
                    "counts_growth": d.get("counts_growth"),
                    "seconds": d.get("seconds", {}).get("per_cycle")})
    return out[-3:]


def _agents():
    """Every managed agent this account has, asked of Preloop."""
    import urllib.request as _u
    tok = json.load(open(glob.glob(os.path.expanduser(
        "~/.preloop/agents/*/permission_hook.json"))[0], encoding="utf-8"))["token"]
    api = settings.runtime()["preloop"]["api_url"]
    r = _u.Request(api + "/api/v1/agents", headers={"Authorization": "Bearer " + tok})
    with _u.urlopen(r, timeout=20) as x:
        d = json.loads(x.read())
    return d if isinstance(d, list) else (d.get("items") or [])


def fix_for(e):
    """What to do about this particular provider, not advice in general.

    A fresh install hits one of these on the first day and the two need different hands: a login
    that expired is the operator's own provider login, and an account nobody has observed is the
    *quota observer's* login — a separate lineage, in its own container, with no path through the
    panel (OPERATIONS §29).
    """
    why = str(e.get("why") or "")
    who = e.get("provider") or "the provider"
    if "nothing has observed this account" in why:
        return (f"the quota observer has no {who} login: "
                f"`docker exec -it $STACK-quota {who} login`, with the SAME account the routing "
                f"login uses — a different one answers account_mismatch, which is the point of it")
    return (f"sign in again for {who} (the panel's 계정 tab, or the provider's own login "
            f"under /route)")


def unknowable(profile="research-default"):
    """Run the router the way a run's first step does, and report what it could not determine.

    The same three parts in the same order — this profile's routing policy, a fresh collection of
    observations, the router's own evaluation — so what this reports is what a run would meet.
    """
    import subprocess, tempfile
    prof = settings.profile(profile)
    if not prof:
        return [{"provider": "(all)", "why": f"unknown: no generated profile {profile!r}"}]
    with tempfile.TemporaryDirectory() as d:
        pol = prof["routing"]
        with open(f"{d}/policy.json", "w") as f:
            json.dump(pol, f)
        os.makedirs(f"{d}/obs", exist_ok=True)
        env = {**os.environ, "P281_MODEL_ROUTES": json.dumps(pol.get("model_route") or {}),
               "P281_LOGINS": json.dumps(pol.get("login") or {})}
        subprocess.run([sys.executable, "/work/p281/collect_obs.py", f"{d}/obs"],
                       capture_output=True, env=env, timeout=180)
        r = subprocess.run([sys.executable, "/work/p281/router.py", f"{d}/policy.json", f"{d}/obs"],
                           capture_output=True, text=True, timeout=60)
    try:
        ev = json.loads(r.stdout)["evaluated"]
    except Exception:
        return [{"provider": "(all)", "why": "unknown: the router did not answer"}]
    return [e for e in ev if str(e.get("why") or "").startswith("unknown:")]


def risks():
    """Standing facts an operator should not have to rediscover. Probed, not assumed.

    The one that matters here: in Preloop OSS 0.15.0 an API key resolves to its *user* and the
    endpoints are guarded by that user's role, so every credential of the account carries
    `decide_approvals` and no setting inside Preloop takes it away (this build exposes no way to
    add a second user to an account). What answers the request instead is the **route**: the agent
    reaches Preloop only through the guard, which refuses a decision whatever credential is
    presented (docker/apiguard.conf, OPERATIONS.md §20).

    This probe runs wherever it is run from, which is the point — it reports what *this* position
    can do. From the agent a 403 is the guard; a 404 means the decision was allowed and only the
    request id was wrong, so the guard is not in the path.
    """
    out = []
    # A provider whose state cannot be determined: a login file that exists with a dead token
    # behind it, an observation that cannot be read. Being at a limit or stale is ordinary and is
    # not a risk; not being able to tell is, because every run that needs that provider will hold
    # and the bring-up will still report the login as present (measured: an expired Claude OAuth
    # token held three runs of a suite while `claude /route login` said true).
    for e in unknowable():
        out.append({"risk": f"the stack cannot tell what {e['provider']} can do",
                    "detail": e.get("why"),
                    "why_it_matters": "a run that needs this provider will hold, and the login "
                                      "check will still say the login is there",
                    "what_would_fix_it": fix_for(e)})
    # Identities that accumulate. Onboarding an agent creates a managed agent in Preloop and a
    # credential for it; doing it again — a reinstall, a repaired install — creates another and
    # leaves the first, each with a live credential. Nothing breaks, and a credential nobody knows
    # about is not something to discover later (OPERATIONS §35). Reported, not deleted: removing an
    # identity that something may still present is an operator's decision.
    try:
        rows = _agents()
        seen = {}
        for a in rows:
            name = str(a.get("display_name") or "")
            if name.startswith("Role: "):
                continue                     # a role principal is declared, and one of each
            seen.setdefault(name, []).append(a)
        extra = {n: len(v) for n, v in seen.items() if len(v) > 1}
        if extra:
            out.append({"risk": "more than one identity per agent in Preloop",
                        "detail": ", ".join(f"{n}: {c}" for n, c in sorted(extra.items())),
                        "why_it_matters": "each carries a live credential, and only the newest is "
                                          "the one this stack presents",
                        "what_would_fix_it": "read them with `principals.py list` and the Preloop "
                                             "console, and delete the ones nothing uses"})
    except Exception:
        pass

    try:
        tok = json.load(open(glob.glob(os.path.expanduser(
            "~/.preloop/agents/*/permission_hook.json"))[0], encoding="utf-8"))["token"]
        api = settings.runtime()["preloop"]["api_url"]
        req = urllib.request.Request(
            f"{api}/api/v1/approval-requests/00000000-0000-0000-0000-000000000000/approve",
            data=json.dumps({"approved": True}).encode(), method="POST",
            headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
            code = 200
        except urllib.error.HTTPError as e:
            code = e.code
        if code != 403:
            out.append({"risk": "from here, an approval can be decided",
                        "detail": f"the approvals endpoint answered {code} (403 would be a refusal)",
                        "why_it_matters": "an approval is the one decision reserved for a person; "
                                          "run from the agent this means the party being governed "
                                          "can answer its own request",
                        "what_would_fix_it": "the guard must hold the name the agent resolves for "
                                             "Preloop (scripts/up.sh brings up apiguard; "
                                             "docker/apiguard.conf holds the refusals)"})
    except Exception as e:
        out.append({"risk": "could not check whether an approval can be decided from here",
                    "detail": f"{type(e).__name__}: {e}"})
    return out


def report(last=50):
    return {"cycles": summarise(cycles(last)), "lock": stuck_lock(), "last_check": checks(),
            "risks": risks(),
            "capabilities": {k: v["available"] for k, v in capabilities.probe().items()},
            "soaks": soaks()}


if __name__ == "__main__":
    n = int(sys.argv[sys.argv.index("--last") + 1]) if "--last" in sys.argv else 50
    r = report(n)
    if "--json" in sys.argv:
        print(json.dumps(r, ensure_ascii=False))
        raise SystemExit(0)
    c = r["cycles"]
    print(f"cycles      {c['cycles_recorded']} recorded, {c['skipped_busy']} skipped as busy, "
          f"{c['refused']} refused")
    if c["seconds"]:
        print(f"seconds     min {c['seconds']['min']}  median {c['seconds']['median']}  "
              f"max {c['seconds']['max']}")
    print(f"ended       {c['ended'] or '-'}")
    for why, n in (c.get("reasons") or {}).items():
        print(f"   {n}x  {why}")
    print(f"not in MLflow  {c['not_in_mlflow']}")
    for ui, err in c["record_errors"]:
        print(f"   {ui}: {err}")
    if r["lock"]:
        print(f"lock        held since {r['lock']['since']} ({r['lock']['age_s']}s) — "
              f"every cycle is skipped while it is there")
    k = r["last_check"]
    print(f"last check  {k['at']} ({k.get('age_s')}s ago) ok={k['ok']} "
          f"composition={k.get('composition')}")
    for item in r.get("risks") or []:
        print(f"risk        {item['risk']}")
        print(f"            {item.get('detail','')}")
        if item.get("what_would_fix_it"):
            print(f"            fix: {item['what_would_fix_it']}")
    print("capabilities " + ", ".join(f"{n}={'yes' if v else 'NO'}"
                                      for n, v in r["capabilities"].items()))
    for s in r["soaks"]:
        print(f"soak {s['soak']}  {s['cycles']} cycles  memory {s['memory_total_mib']} MiB  "
              f"growth {s['counts_growth']}")
