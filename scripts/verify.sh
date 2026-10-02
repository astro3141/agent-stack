#!/usr/bin/env bash
# Verify this tree — as much as the machine it runs on allows.
#
#   scripts/verify.sh                       pick the level this machine can do (static or stack)
#   scripts/verify.sh --level static        no Docker: syntax, graphs, policy, the step helper,
#                                           package declarations, in-tree package controls, drift
#   scripts/verify.sh --level stack         a running stack, no provider logins: up.sh --check,
#                                           the three control suites, package locks and controls,
#                                           package floors, one hello-lane run, ops_health
#   scripts/verify.sh --level full          logins present: everything above, then one routed run
#                                           (auto) and one role-split run (novel-a), both recorded
#
# Three levels, cumulative, because three kinds of machine run this tree: a checkout with no
# Docker (a cloud session, a laptop without the stack), a stack with nobody signed in (the
# GitHub runner — .github/workflows/cold-start-linux.yml runs `stack`), and an operator's instance
# with provider logins (the only place a model call can be measured). Each level says at the top
# what it cannot see, so a green run is never read as more than it is.
#
# Exit 0 when every check at the chosen level passed; 1 otherwise. Changes nothing but
# evidence/ and the run it starts at `full`.
set -uo pipefail
# Git Bash rewrites an argument that looks like a POSIX path into a Windows one before docker sees
# it, so `docker exec … /opt/venv/bin/python` arrived as "C:/Program Files/Git/opt/venv/bin/python"
# (measured on a Windows host, 2026-10-02; up.sh already carries this line). The host python there
# is a native Windows one: it reads no MSYS path and ends its lines with CRLF, so what this script
# hands it is converted with cygpath, and what it prints is read without the CR.
export MSYS_NO_PATHCONV=1
HERE="$(cd "$(dirname "$0")/.." && pwd)"
hp() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else printf '%s' "$1"; fi; }   # a path as the host python reads it
PSEP=":"; command -v cygpath >/dev/null 2>&1 && PSEP=";"                                            # PYTHONPATH's separator there
nocr() { tr -d '\r'; }
cd "$HERE"
LEVEL=""
while [ $# -gt 0 ]; do
  case "$1" in
    --level) LEVEL="$2"; shift 2;;
    --level=*) LEVEL="${1#--level=}"; shift;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
STACK="${STACK:-agentstack}"
[ -f "$HERE/config/instance.env" ] && . "$HERE/config/instance.env"
# The host python: the first candidate that actually runs a script from stdin. On a Windows host
# `python3` can be the Microsoft Store's app-execution alias — a stub that prints "Python", exits
# 49 and runs nothing (measured 2026-10-02: every static check failed with that one word as its
# reason) — and the interpreter there is `python`, or `py -3`. UTF-8 for whatever it prints: a
# cp949 console could not encode the em dash in a control's name, and the control died on it.
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
pick_py() {
  local c
  for c in ${PY:-} python3 python "py -3"; do
    if [ "$(printf 'print(7)' | $c - 2>/dev/null | tr -d '\r')" = 7 ]; then printf '%s' "$c"; return 0; fi
  done
  return 1
}
PY="$(pick_py)" || { echo "no working python on this host (tried python3, python, py -3); set PY=<interpreter>" >&2; exit 2; }
FAILS=0; CHECKS=0
ok()   { CHECKS=$((CHECKS+1)); printf '  ok    %s\n' "$1"; }
bad()  { CHECKS=$((CHECKS+1)); FAILS=$((FAILS+1)); printf '  FAIL  %s\n' "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$2"; }
note() { printf '  note  %s\n' "$1"; }
sect() { printf '\n== %s\n' "$1"; }
in_agent() { docker exec "$STACK-agent" /opt/venv/bin/python "$@"; }

stack_up() { docker info >/dev/null 2>&1 && docker inspect -f '{{.State.Running}}' "$STACK-agent" 2>/dev/null | grep -q true; }

if [ -z "$LEVEL" ]; then
  if stack_up; then LEVEL=stack; else LEVEL=static; fi
  echo "level: $LEVEL (chosen for this machine; --level overrides)"
else
  echo "level: $LEVEL"
fi
case "$LEVEL" in static|stack|full) ;; *) echo "level is static | stack | full" >&2; exit 2;; esac

# ============================================================================ static
sect "static — what a checkout can say about itself"
echo "  cannot see: whether any of it runs. That is the stack level."

# a throwaway runtime, so the step helper and the in-tree controls resolve a workspace that is ours
TMP="$(mktemp -d)"; CROOT=""
cleanup() { rm -rf "$TMP"; [ -n "$CROOT" ] && docker exec "$STACK-agent" rm -rf "$CROOT" >/dev/null 2>&1; true; }
trap cleanup EXIT
mkdir -p "$TMP/config/generated" "$TMP/ws"
printf '{"preloop":{"api_url":"x","mcp_url":"x"},"mlflow":{"url":"x"},"egress":{"proxy":"http://127.0.0.1:1","no_proxy":[]},"paths":{"workspace_root":"%s/ws","evidence_root":"%s/ev","observations":"%s/obs","logins_root":"%s/route"}}' \
  "$TMP" "$TMP" "$TMP" "$TMP" > "$TMP/config/generated/runtime.json"
export AGENTSTACK_ROOT="$(hp "$TMP")" PYTHONPATH="$(hp "$HERE/stack")$PSEP$(hp "$HERE/stack/steps")${PYTHONPATH:+$PSEP$PYTHONPATH}"

# parsed, not byte-compiled: compileall writes __pycache__, which the containers own (uid 1000) on a
# bind mount, and a host user who cannot write there read "Error compiling" for a file that was fine
out="$($PY - <<'PYAST' | nocr
import ast, glob, sys
bad = []
for f in sorted(set(glob.glob("stack/**/*.py", recursive=True) + glob.glob("packages/*/steps/*.py")
                    + glob.glob("packages/*/controls.py") + glob.glob("ops/*.py") + glob.glob("hub/*.py"))):
    if "/vendor/" in f or "/harness/" in f or "__pycache__" in f:
        continue
    try:
        ast.parse(open(f, encoding="utf-8").read(), filename=f)
    except SyntaxError as e:
        bad.append(f"{f}:{e.lineno}: {e.msg}")
print(len(bad)); print("\n".join(bad))
PYAST
)"
if [ "$(echo "$out" | head -1)" = 0 ]; then ok "every Python file parses"; else bad "a Python file does not parse" "$(echo "$out" | tail -n +2 | head -3 | tr '\n' ';')"; fi

out="$($PY - <<'PY' | nocr
import glob, sys, yaml
bad = []
files = glob.glob("packages/*/*.yaml") + glob.glob("policy/*.yaml") + glob.glob("config/*.yaml") \
      + glob.glob("config/profiles/*.yaml") + ["docker/compose.poc.yaml"] + glob.glob(".github/workflows/*.yml")
for f in files:
    try:
        d = yaml.safe_load(open(f, encoding="utf-8"))
    except Exception as e:
        bad.append(f"{f}: {type(e).__name__}"); continue
    if isinstance(d, dict) and "workflow" in d and "agents" in d:
        names = {a["name"] for a in d["agents"]}
        for a in d["agents"]:
            for r in a.get("routes") or []:
                if r.get("to") not in names:
                    bad.append(f"{f}: {a['name']} routes to {r.get('to')!r}, which is not an agent")
        if d["workflow"].get("entry_point") not in names:
            bad.append(f"{f}: entry_point {d['workflow'].get('entry_point')!r} is not an agent")
print(len(files)); print("\n".join(bad))
PY
)"
n="$(echo "$out" | head -1)"; errs="$(echo "$out" | tail -n +2)"
if [ -z "$errs" ]; then ok "$n YAML files parse, and every workflow route resolves"; else bad "a YAML file or a workflow graph is broken" "$errs"; fi

missing="$(for f in stack/steps/*.py packages/*/steps/*.py; do case "$f" in */vendor/*|*/step.py|*/__init__.py) continue;; esac; grep -q '^REPEATABLE' "$f" || echo "$f"; done)"
if [ -z "$missing" ]; then ok "every step declares what a repeat of it does (REPEATABLE)"; else bad "steps without REPEATABLE" "$(echo $missing)"; fi

out="$($PY - <<'PY' | nocr
import yaml
d = yaml.safe_load(open("policy/b-fsmcp.yaml", encoding="utf-8"))
tools = {t["name"] for t in d["tools"]}
fs = {"read_file","read_text_file","read_media_file","read_multiple_files","write_file","edit_file",
      "create_directory","list_directory","list_directory_with_sizes","directory_tree","move_file",
      "search_files","get_file_info","list_allowed_directories"}
# `allow` is the only value Preloop 0.15.0/0.16.0 accept (policy header, OPERATIONS §63): anything
# else fails `policy apply` on the instance, so a change here is caught before a bring-up.
print("allow" if d["defaults"]["unknown_tools"] == "allow" else "UNSUPPORTED", sorted(fs - tools))
PY
)"
case "$out" in "allow []") ok "policy/b-fsmcp.yaml names every filesystem tool, with the one default Preloop accepts";; *) bad "policy/b-fsmcp.yaml misses a tool, or sets a default Preloop refuses" "$out";; esac

out="$(AGENTSTACK_PACKAGES="$HERE/packages" AGENTSTACK_PACKAGES_YAML="$HERE/config/packages.yaml" AGENTSTACK_PACKAGES_LOCAL="$HERE/config/packages.local.yaml" AGENTSTACK_ROOT="$(hp "$HERE")" $PY stack/packages.py 2>&1 | nocr)"
if echo "$out" | grep -q "UNUSABLE\|REFUSED"; then bad "a declared package is unusable or needs a newer stack" "$(echo "$out" | grep 'UNUSABLE\|REFUSED')"; else ok "every declared package is usable: $(echo "$out" | grep -cvE '^\s' ) packages"; fi
echo "$out" | grep "note:" | sed 's/^/        /' || true

# The step tests and the in-tree packages' controls run with the stack's own interpreter when the
# stack is up — in the agent container, where the paths and the settings are the runtime's — and
# with the host python only on a checkout that has no stack. A native Windows python wrote the
# hello-lane file under a mixed path and ran novel's controls to a different answer than the
# runtime gives (measured 2026-10-02, with the runtime's own answer taken in the same session);
# the runtime's answer is the one that counts.
if stack_up; then
  CROOT="/tmp/verify-$$"
  docker exec "$STACK-agent" sh -c "mkdir -p $CROOT/config/generated $CROOT/ws && printf '%s' '{\"preloop\":{\"api_url\":\"x\",\"mcp_url\":\"x\"},\"mlflow\":{\"url\":\"x\"},\"egress\":{\"proxy\":\"http://127.0.0.1:1\",\"no_proxy\":[]},\"paths\":{\"workspace_root\":\"$CROOT/ws\",\"evidence_root\":\"$CROOT/ev\",\"observations\":\"$CROOT/obs\",\"logins_root\":\"$CROOT/route\"}}' > $CROOT/config/generated/runtime.json"
  runpy()  { local id="$1" f="$2"; shift 2; docker exec -e AGENTSTACK_ROOT="$CROOT" -e CONDUCTOR_SELF_RUN_ID="$id" "$STACK-agent" /opt/venv/bin/python "/work/$f" "$@"; }
  runpyc() { docker exec -e AGENTSTACK_ROOT="$CROOT" "$STACK-agent" /opt/venv/bin/python -c "$@"; }
  note "step tests and package controls run in the agent container, with the stack's interpreter"
else
  runpy()  { local id="$1"; shift; CONDUCTOR_SELF_RUN_ID="$id" $PY "$@"; }
  runpyc() { $PY -c "$@"; }
  note "step tests and package controls run with the host python ($PY); the stack level uses the runtime's"
fi
r="$(runpy verify-static packages/hello-lane/steps/write.py verify 2>&1 | tail -1 | nocr)"
if runpyc 'import json, os, sys; sys.exit(0 if os.path.isfile(json.loads(sys.argv[1])["path"]) else 1)' "$r" 2>/dev/null; then
  ok "a step addresses the workspace through the helper (hello-lane)"
else bad "hello-lane's step did not write where the helper points" "$r"; fi
r="$(runpy verify-static packages/research-r/steps/r_stage.py bogus 2>&1 | tail -1 | nocr)"
case "$r" in *'"ok": false'*) ok "a step refuses in its output rather than crashing (research-r)";; *) bad "research-r's step did not refuse as JSON" "$r";; esac
r="$(runpyc 'import step; step.main(lambda: 1/0, decision="")' 2>&1 | tail -1 | nocr)"
case "$r" in *TOOL_FAILURE*) ok "the helper turns a crash into the declared output";; *) bad "step.main did not report a crash" "$r";; esac

for c in packages/*/controls.py; do
  [ -f "$c" ] || continue
  name="$(basename "$(dirname "$c")")"
  if grep -qE "^  $name:" config/packages.yaml && grep -A3 -E "^  $name:" config/packages.yaml | grep -q "from: local"; then
    if runpy verify-ctl "$c" 2>&1 | nocr > "$TMP/ctl-$name.log"; then ok "$name: $(tail -1 "$TMP/ctl-$name.log")"; else bad "$name: controls failed" "$(grep -E 'FAIL|Error' "$TMP/ctl-$name.log" | head -5 | tr '\n' ';')"; fi
  else
    note "$name: controls.py present; a fetched package's controls run at the stack level"
  fi
done

# the lists compose mounts, generated on a tree shaped like a fresh clone: no allow.local, no
# provisioned profile — the case the operator's own instance never exercises
FRESH="$TMP/fresh"; mkdir -p "$FRESH"
if git archive HEAD 2>/dev/null | tar -x -C "$FRESH" && cp scripts/egress_gen.sh "$FRESH/scripts/" \
   && (cd "$FRESH" && bash scripts/egress_gen.sh >/dev/null 2>&1) \
   && [ -f "$FRESH/config/generated/egress/allow" ] && [ -f "$FRESH/config/generated/egress/profiles/closed.allow" ]; then
  ok "egress lists generate on a fresh clone (no allow.local, no provisioned profile)"
else
  bad "egress_gen.sh does not produce the lists compose mounts on a fresh clone"
fi

if [ -x scripts/drift.sh ]; then
  newer="$(bash scripts/drift.sh 2>/dev/null | awk 'NR>1 && $4=="newer"{print $1}' | tr '\n' ' ')"
  [ -n "$newer" ] && note "drift (report only): newer upstream — $newer" || note "drift: nothing newer, or no registry answered"
fi

if [ "$LEVEL" = static ]; then
  echo; echo "static: $((CHECKS-FAILS))/$CHECKS passed"; [ $FAILS = 0 ] && exit 0 || exit 1
fi

# ============================================================================ stack
sect "stack — a running instance, nobody signed in"
echo "  cannot see: a model call. Only the provider logins and quota are allowed to fail here."
if ! stack_up; then bad "no running stack: '$STACK-agent' is not up (scripts/up.sh)"; echo; echo "stack: $((CHECKS-FAILS))/$CHECKS passed"; exit 1; fi

CHECKLOG="$TMP/up-check.log"
bash scripts/up.sh --check > "$CHECKLOG" 2>&1 || true
ALLOWED="claude /route login|codex /route login|grok /route login|observer codex login|every provider's state is knowable|observation fresh \(< 10 min\)|the router can choose a provider"
failed="$(grep -E '^  FAIL' "$CHECKLOG" | sed -E 's/^  FAIL  //; s/\s{2,}.*$//')"
unexpected="$(echo "$failed" | grep -vE "^($ALLOWED)$" | grep -v '^$' || true)"
logins_missing="$(echo "$failed" | grep -E "/route login" || true)"
if [ -z "$unexpected" ]; then ok "up.sh --check: nothing failed but logins/quota ($(echo "$failed" | grep -c . ) such lines)"; else bad "up.sh --check failed outside logins/quota" "$(echo "$unexpected" | tr '\n' ';')"; fi
grep -q 'runtime may not decide approvals' "$CHECKLOG" && ! grep -qE 'FAIL\s+runtime may not' "$CHECKLOG" && ok "the runtime cannot decide approvals or rewrite its rights" || bad "the approval boundary check did not pass"

for suite in trial_controls review_controls; do
  if in_agent "/work/stack/$suite.py" > "$TMP/$suite.log" 2>&1; then ok "$suite: $(grep -E 'controls passed|passed' "$TMP/$suite.log" | tail -1)"
  else bad "$suite reported failures" "$(grep -E '^\s*FAIL' "$TMP/$suite.log" | head -5 | tr '\n' ';')"; tail -6 "$TMP/$suite.log" | sed 's/^/        | /'; fi
  grep -E '^\s*skip' "$TMP/$suite.log" | sed 's/^/        /' | head -5 || true
done
# the router controls mutate the live observations (<observations>/<provider>.json), which exist
# only once the quota observer has seen a signed-in provider: without one they are skipped, named
OBS="$(in_agent -c 'import settings; print(settings.runtime()["paths"]["observations"])' 2>/dev/null || echo /obs)"
# (the observer leaves a raw file there even with nobody signed in; what the controls mutate is the
# normalized file of every provider, so those three are the condition)
if docker exec "$STACK-agent" sh -c "test -f $OBS/claude.json && test -f $OBS/codex.json && test -f $OBS/grok.json"; then
  if in_agent /work/stack/router_controls.py "$OBS" > "$TMP/router_controls.log" 2>&1; then ok "router_controls: $(tail -1 "$TMP/router_controls.log")"
  else bad "router_controls reported failures" "$(grep -c '"ok": false' "$TMP/router_controls.log") case(s)"; tail -6 "$TMP/router_controls.log" | sed 's/^/        | /'; fi
else
  note "router_controls: not every provider has a normalized observation in $OBS (nobody signed in) — skipped; the full level runs it"
fi

if bash scripts/packages.sh verify > "$TMP/pkg.log" 2>&1; then ok "packages.sh verify: locks and package controls"; else bad "packages.sh verify failed" "$(grep -E 'DRIFT|CHANGED|MISSING|FAILED' "$TMP/pkg.log" | head -5 | tr '\n' ';')"; fi
grep -E '^\s*none' "$TMP/pkg.log" | sed 's/^/        /' || true

floors="$(in_agent /work/stack/packages.py stack 2>&1)"
if echo "$floors" | grep -q "too_old"; then bad "a package needs a newer stack" "$(echo "$floors" | grep too_old)"; else ok "no package floor is violated"; fi

RID="verify-$(date +%s | tail -c 7)"
if in_agent /work/stack/run_workflow.py start "$RID" hello-lane research-default text=verify > "$TMP/hello.log" 2>&1 \
   && in_agent /work/stack/run_workflow.py show "$RID" 2>/dev/null | tail -1 | grep -q '"completed_ok": true'; then
  ok "hello-lane ran to completion ($RID) — a package step through Conductor, no model"
else bad "hello-lane did not complete ($RID)" "$(tail -3 "$TMP/hello.log" | tr '\n' ';')"; fi

in_agent /work/stack/ops_health.py > "$TMP/health.log" 2>&1 && ok "ops_health answers" || bad "ops_health failed" "$(tail -2 "$TMP/health.log" | tr '\n' ';')"

if [ "$LEVEL" = stack ]; then
  echo; echo "stack: $((CHECKS-FAILS))/$CHECKS passed"
  [ -n "$logins_missing" ] && echo "not signed in: $(echo "$logins_missing" | sed 's/ \/route login//' | tr '\n' ' ')— the full level needs a person to sign in on the panel"
  [ $FAILS = 0 ] && exit 0 || exit 1
fi

# ============================================================================ full
sect "full — provider logins present: a model call, routed, governed and recorded"
echo "  cannot see: whether the model's work was any good (COVERAGE.md §16–18), and the N7"
echo "  native-tool check per provider after a CLI update (docs/update-day.md) — still by hand."
if [ -n "$logins_missing" ]; then
  bad "not every provider is signed in" "$(echo "$logins_missing" | tr '\n' ';') — sign in on the panel, then run again"
  echo; echo "full: $((CHECKS-FAILS))/$CHECKS passed"; exit 1
fi

run_and_show() {  # id workflow [inputs...] — prints the show line; 0 when completed_ok
  local id="$1" wf="$2"; shift 2
  in_agent /work/stack/run_workflow.py start "$id" "$wf" research-default "$@" > "$TMP/$id.log" 2>&1
  in_agent /work/stack/run_workflow.py show "$id" 2>/dev/null | tail -1 | tee "$TMP/$id.show" | grep -q '"completed_ok": true'
}
RID="verify-auto-$(date +%s | tail -c 6)"
if run_and_show "$RID" auto file_name=verify.txt content=V1; then
  dec="$($PY -c "import json,sys; print((json.load(open('$TMP/$RID.show')).get('output') or {}).get('decision',''))" 2>/dev/null)"
  [ "$dec" = PASS ] && ok "auto: one routed call, file written through Preloop, judged PASS ($RID)" \
                    || bad "auto completed but the judgement is '$dec' ($RID)" "$(tail -1 "$TMP/$RID.show" | head -c 300)"
else bad "auto did not complete ($RID)" "$(tail -2 "$TMP/$RID.log" | tr '\n' ';')"; fi

RID="verify-novel-$(date +%s | tail -c 6)"
if run_and_show "$RID" novel-a max_repairs=1; then
  dec="$($PY -c "import json,sys; print((json.load(open('$TMP/$RID.show')).get('output') or {}).get('decision',''))" 2>/dev/null)"
  ok "novel-a: roles on separate principals, fan-out reviews, recorded — decision $dec ($RID)"
else bad "novel-a did not complete ($RID)" "$(tail -2 "$TMP/$RID.log" | tr '\n' ';')"; fi

echo; echo "full: $((CHECKS-FAILS))/$CHECKS passed"
[ $FAILS = 0 ] && exit 0 || exit 1
