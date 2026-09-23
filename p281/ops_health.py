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


def risks():
    """Standing facts an operator should not have to rediscover. Probed, not assumed.

    The one that matters here: in Preloop OSS 0.15.0 an API key resolves to its *user* and the
    endpoints are guarded by that user's role, so the credential the runtime holds — which has to
    be a managed-agent credential for the permission hook to work at all — carries whatever the
    creating user may do. If that user is the account owner, the governed party can answer its own
    approval requests. Asking the API is the only honest way to know: a 403 means refused, a 404
    means it was allowed and only the request id was wrong.
    """
    out = []
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
            out.append({"risk": "the runtime's own credential can decide approvals",
                        "detail": f"the approvals endpoint answered {code} to it (403 would be a refusal)",
                        "why_it_matters": "an approval is the one decision reserved for a person, "
                                          "and the party being governed holds a credential that can make it",
                        "what_would_fix_it": "issue the runtime's managed-agent credential under a "
                                             "Preloop user whose role lacks decide_approvals "
                                             "(viewer, analyst and tracker_manager do)"})
    except Exception as e:
        out.append({"risk": "could not check whether the runtime credential can approve",
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
