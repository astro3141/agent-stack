"""Conductor script step: assign a provider to each role of a role-split workflow.

usage: roles.py <profile> <admission-evidence-dir> <role>=<provider>[:<principal>] [...]

The evidence directory is the one `route.py` wrote (decision.json) or the one `admit_models.py`
wrote (admission.json): a round that admits several providers by name binds its roles against
that admission, and a provider the profile does not list is bound when that admission says it
is eligible (#51).

The router (steps/route.py) answers "may anything run, and on which provider" from quota, and its
answer names one provider. A role-split workflow needs more than that: each role is bound to a
*named* provider by design (the novel-shaped trial binds Author, Reviewer and Cold Reader to
different vendors), so every provider a role will actually run on has to be admissible on its own.

Two things are therefore checked per role, and a role that fails either is reported rather than
guessed or substituted:

  * the profile carries that provider at all (it names its login and model route), and
  * the router found that provider **eligible** in this run's own evaluation — read from the
    decision the router just wrote, never inferred from the fact that some other provider had
    room. Measured before this check existed: with Codex and Claude both over their limit and
    only Grok eligible, the Codex and Claude roles were still returned as ok.

No evaluation to read is not "fine": it is reported as unavailable, the same way the router holds
a run when it cannot see a quota.

A role may also name the **principal** it runs as (`story=codex:novel-reviewer`). That is what
makes tool rights per *step* rather than per run: the principal carries the rights (Preloop governs
per subject), the vendor carries the model, and they are chosen separately. The principal is a
name here and nothing else — its credential reaches the adapter from the environment, never from
a workflow or an argument.
"""

# What a repeat of this step does (OPERATIONS.md §17): "yes" — the same result;
# "guarded" — it recognises the repeat; "no" — it does the work again.
REPEATABLE = "yes"   # a function of the profile and this run's router decision
import json, os, sys

sys.path.insert(0, "/work/stack")
import settings

prof_name = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else "research-default"
evidence_dir = sys.argv[2] if len(sys.argv) > 2 else ""
specs = sys.argv[3:]
if evidence_dir and "=" in evidence_dir:        # called without the evidence dir
    specs, evidence_dir = [evidence_dir, *specs], ""

PROF = settings.profile(prof_name) or {}
routing = PROF.get("routing") or {}
candidates = routing.get("candidates") or []
logins = routing.get("login") or {}
routes = routing.get("model_route") or {}


def eligibility():
    """provider -> (eligible, why) from this run's admission; None when there is none to read.

    Two steps write one: `route.py` (decision.json — the one-of question) and `admit_models.py`
    (admission.json — every provider a round names, each with a verdict, #51). Either is this
    run's own evaluation; a role is bound against it, never against the fact that some other
    provider had room."""
    for fn, pick in (("decision.json", lambda d: d),
                     ("admission.json", lambda d: d.get("decision") or {})):
        p = os.path.join(evidence_dir, fn) if evidence_dir else ""
        if not p or not os.path.isfile(p):
            continue
        try:
            d = pick(json.load(open(p, encoding="utf-8")))
        except (ValueError, AttributeError):
            continue
        ev = d.get("evaluated")
        if isinstance(ev, list):
            return {e.get("provider"): (bool(e.get("eligible")), e.get("why") or "")
                    for e in ev if isinstance(e, dict)}
    return None


elig = eligibility()
out = {"profile": prof_name}
missing, ineligible = [], []
def verdict(provider):
    """Why this provider cannot be bound, or "" when it can."""
    # A provider the profile does not list may still be bound when this run's admission asked
    # about it by name and admitted it (admit_models.py, #51): the profile's thresholds judged
    # it, and its login and route are the profile's when it has them, the provider's own name
    # and the direct route otherwise. A provider nobody asked about is still "not in the profile".
    if provider not in candidates and not (elig and provider in elig):
        return "not in the profile"          # say so; never substitute another vendor
    if elig is None:
        return "no router evaluation to read"
    if provider not in elig:
        return "the router did not evaluate it"
    if not elig[provider][0]:
        return elig[provider][1]
    return ""


for arg in specs:
    role, _, rest = arg.partition("=")
    spec, _, principal = rest.partition(":")
    # `author=claude|codex`: the workflow's own order of vendors for a role, walked here the way
    # the router walks the profile's candidates — the first that this run's admission admitted
    # wins, and the order is the workflow's (#44: a role pinned to one vendor held every run
    # while that vendor's login was dead; a workflow that would rather run on another names it).
    alternatives = [p.strip() for p in spec.split("|") if p.strip()]
    whys = {p: verdict(p) for p in alternatives}
    provider = next((p for p in alternatives if not whys[p]), None)
    if provider is None:
        out[f"{role}_provider"] = out[f"{role}_login"] = out[f"{role}_route"] = ""
        out[f"{role}_principal"] = ""
        # one line per role: every alternative and why; "missing" only when none is in reach
        bucket = missing if all(w == "not in the profile" for w in whys.values()) else ineligible
        bucket.append(", ".join(f"{role}:{p} ({w})" for p, w in whys.items()))
        continue
    out[f"{role}_provider"] = provider
    out[f"{role}_login"] = logins.get(provider, provider)
    out[f"{role}_route"] = routes.get(provider, "preloop_gateway" if provider in candidates else "direct")
    out[f"{role}_principal"] = principal
out["missing"] = ",".join(missing)
out["ineligible"] = ",".join(ineligible)
out["ok"] = "yes" if not missing and not ineligible else "no"
print(json.dumps(out, ensure_ascii=False))
