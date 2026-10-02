"""One door to the router: this profile's policy, a collection of observations, the evaluation.

usage: admission.py <profile> [--candidates a,b,…] [--dir <evidence dir>]

Six places asked the router the same question in the same three moves — write the profile's
routing policy down, run `collect_obs.py` with that policy's routes, logins and reuse window in
the environment, run `router.py` on the result — and each had its own copy of the moves
(stack/steps/route.py, steps/admit_models.py, capabilities.py, ops_health.py, ops/server.py,
scripts/verify.sh). A copied flow drifts in the copy nobody reads: the reuse window was added to
five of them. The moves live here now, and a caller asks one question.

What this answers: the router's own decision (`decision`, `provider`, `reason`, `evaluated`, …),
plus `policy` (what it was judged against) and `evidence_dir` when the caller asked for the
evidence to be kept. What it does not do is decide anything about the answer — a HOLD is reported,
never turned into a refusal here (CONTRACT.md). A collector that fails is not fatal: the router
then says "unknown: no observation" for the providers it could not read, which is the true state,
and `collect_error` carries what the collector said.
"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import settings

PY = sys.executable


def policy_of(profile, candidates=None):
    """The routing policy a run on this profile is judged against. `candidates` narrows *who* is
    asked about (admit_models.py); thresholds, windows and logins stay the profile's."""
    prof = settings.profile(profile)
    if prof is None:
        raise LookupError(f"unknown profile {profile!r} (run cfg.py generate)")
    pol = dict(prof.get("routing") or {})
    if candidates:
        pol["candidates"] = list(candidates)
    return pol


def collect_env(pol):
    """What the collector reads from its environment: the policy's routes, logins and reuse window."""
    return {**os.environ, "AGENTSTACK_MODEL_ROUTES": json.dumps(pol.get("model_route") or {}),
            "AGENTSTACK_LOGINS": json.dumps(pol.get("login") or {}),
            "AGENTSTACK_OBS_REUSE_S": str(pol.get("reuse_s", 120))}


def collect(pol, obs_dir, timeout=180):
    """Observations into `obs_dir`, read with this policy's logins. Returns "" or what went wrong."""
    os.makedirs(obs_dir, exist_ok=True)
    try:
        p = subprocess.run([PY, f"{HERE}/collect_obs.py", obs_dir], capture_output=True, text=True,
                           env=collect_env(pol), timeout=timeout)
    except Exception as e:                                       # noqa: BLE001 — reported, not raised
        return f"{type(e).__name__}: {e}"[:200]
    return "" if p.returncode == 0 else (p.stderr or p.stdout)[-200:]


def route(policy_path, obs_dir, timeout=60):
    """The router's decision on these observations, or a RuntimeError naming why it did not answer."""
    p = subprocess.run([PY, f"{HERE}/router.py", policy_path, obs_dir],
                       capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(p.stdout)
    except ValueError:
        raise RuntimeError(f"the router did not answer ({(p.stderr or p.stdout)[-160:]})")


def evaluate(profile=None, policy=None, candidates=None, evidence_dir=None, collect_timeout=180):
    """Ask the router about this profile (or this raw `policy`), after collecting.

    With `evidence_dir`, the policy, the observations (`obs/`) and the decision are kept there —
    a routing step's evidence; without it, nothing is left behind. Raises LookupError for a
    profile that does not exist and RuntimeError when the router does not answer: the caller
    says what either means where it stands.
    """
    pol = dict(policy) if policy is not None else policy_of(profile, candidates)
    if policy is not None and candidates:
        pol["candidates"] = list(candidates)
    tmp = None if evidence_dir else tempfile.TemporaryDirectory(prefix="agentstack-admission-")
    d = evidence_dir or tmp.name
    try:
        os.makedirs(d, exist_ok=True)
        policy_path = f"{d}/policy.json"
        json.dump(pol, open(policy_path, "w"), indent=1)
        err = collect(pol, f"{d}/obs", collect_timeout)
        r = route(policy_path, f"{d}/obs")
        r = {**r, "policy": pol, "evidence_dir": d if evidence_dir else "",
             **({"collect_error": err} if err else {})}
        if evidence_dir:
            json.dump(r, open(f"{d}/decision.json", "w"), indent=1)
        return r
    finally:
        if tmp:
            tmp.cleanup()


def eligible(decision):
    """The providers the router would take, in its order."""
    return [e["provider"] for e in (decision.get("evaluated") or []) if e.get("eligible")]


def unknown(decision):
    """The providers whose state the stack could not read — the standing risk ops_health reports."""
    return [e for e in (decision.get("evaluated") or [])
            if str(e.get("why") or "").startswith("unknown:")]


if __name__ == "__main__":
    args = sys.argv[1:]
    def opt(name):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else ""
    name = next((a for a in args if not a.startswith("--") and args[args.index(a) - 1] not in ("--candidates", "--dir")), "")
    if not name:
        print(json.dumps({"error": "admission.py <profile> [--candidates a,b] [--dir <evidence dir>]"}))
        sys.exit(2)
    try:
        print(json.dumps(evaluate(name, candidates=[c for c in opt("--candidates").split(",") if c],
                                  evidence_dir=opt("--dir") or None), ensure_ascii=False))
    except (LookupError, RuntimeError) as e:
        print(json.dumps({"decision": "HOLD", "provider": "", "reason": str(e), "evaluated": [],
                          "error": str(e)}))
        sys.exit(1)
