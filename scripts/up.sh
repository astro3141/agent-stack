#!/usr/bin/env bash
# Bring the whole stack up (or back after a restart / recreate) and check it.
#
#   scripts/up.sh            up + check
#   scripts/up.sh --check    check only
#   scripts/up.sh --recreate up with --force-recreate (the "survives recreation" test)
#   scripts/up.sh [...] --composition <full|no-record|runtime>
#
# A composition says which optional services are started. It is a memory decision with a
# consequence, so the consequence is printed rather than left to be discovered:
#
#   full       everything (the default)
#   no-record  without MLflow — runs execute, nothing about them is recorded or comparable
#   runtime    without MLflow and without the screen — runs start from the CLI only
#
# What is never optional: Preloop (tool rights and approvals), the egress allowlist proxy and
# the file tool server. Dropping any of those does not make the stack smaller, it makes it
# something else — one that cannot say what an agent was allowed to do. The quota observer is
# optional (--observer): every provider is read with the login that executes (OPERATIONS §29),
# and the observer is codex's second source, for an operator who signs it in.
#
# No manual step afterwards: Preloop joins the PoC networks through docker/preloop.agentstack.yaml,
# every PoC container restarts on its own, the observer's loop (when on) is its container process,
# and logins / Preloop's database / MLflow live in volumes or bind mounts.
PY_IN_AGENT=/opt/venv/bin/python   # the agent container's interpreter — named once here (OPERATIONS §80)
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
# A workspace that is a restored copy says so in config/instance.env (written by scripts/
# restore.sh): its instance name, Preloop project, paths and ports. Reading it here is what keeps
# a later `up.sh --check` or `down.sh` in that directory from acting on the live instance instead.
# Values already set in the environment win, so a deliberate override still works.
if [ -f "$HERE/config/instance.env" ]; then
  while IFS='=' read -r k v; do
    case "$k" in ''|'#'*) continue;; esac
    eval "[ -n \"\${$k:-}\" ]" || eval "$k=\$v"
  done < "$HERE/config/instance.env"
  # and compose run by hand in this directory must name the same instance: docker/.env (§69)
  bash "$HERE/scripts/instance_env.sh" "$HERE"
fi
PRELOOP_DIR="${PRELOOP_DIR:-$HOME/.preloop-oss}"
# docker on Windows needs native paths; path conversion is off below (MSYS_NO_PATHCONV)
command -v cygpath >/dev/null && { PRELOOP_DIR="$(cygpath -m "$PRELOOP_DIR")"; HERE="$(cygpath -m "$HERE")"; }
export MSYS_NO_PATHCONV=1
MODE="up"; COMPOSITION="${COMPOSITION:-full}"; BUILD="--build"
while [ $# -gt 0 ]; do
  case "$1" in
    --composition) COMPOSITION="${2:-full}"; shift 2;;
    --observer) OBSERVER=1; shift;;
    --check|--recreate|up) MODE="$1"; shift;;
    --no-build) BUILD="--no-build"; shift;;   # bring up the images that exist, build nothing (a rollback, §101)
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
case "$COMPOSITION" in
  full)      COMPOSE_PROFILES="record,ui";;
  no-record) COMPOSE_PROFILES="ui";;
  runtime)   COMPOSE_PROFILES="";;
  *) echo "unknown composition: $COMPOSITION (full | no-record | runtime)" >&2; exit 2;;
esac
# Egress profiles this instance provisioned (docker/egress/profiles/<name>.allow, §60) bring their
# proxy and runner up as the compose profile `egress-<name>`; closed and probe ship tracked and are
# always on. A profile with no list has no container, and a role mapped to it is refused by name.
for _f in "$HERE"/docker/egress/profiles/*.allow; do
  [ -f "$_f" ] || continue
  _n="$(basename "$_f" .allow)"
  case "$_n" in closed|probe) continue;; esac
  COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}egress-$_n"
done
# The quota observer — codex's optional second source with a login of its own (§29) — is a compose
# profile: on with --observer, and kept on once its volume exists (an operator who signed in there
# once keeps it). Without a login it only polled into exit 1 (second install, issue #16).
if [ "${OBSERVER:-0}" = 1 ] || docker volume inspect "${STACK:-agentstack}-quota-home" >/dev/null 2>&1; then
  COMPOSE_PROFILES="${COMPOSE_PROFILES:+$COMPOSE_PROFILES,}observer"
fi
export COMPOSE_PROFILES
# One instance per name: STACK selects container/volume/network names and the published ports.
# The defaults are the live instance; a restored copy runs under another name (scripts/restore.sh).
STACK="${STACK:-agentstack}"
OPS_PORT="${OPS_PORT:-8781}"; HUB_PORT="${HUB_PORT:-8780}"; MLFLOW_PORT="${MLFLOW_PORT:-5000}"
PRELOOP_PROJECT="${PRELOOP_PROJECT:-preloop-oss}"
PRELOOP_API_PORT="${PRELOOP_API_PORT:-8000}"; PRELOOP_GATEWAY_PORT="${PRELOOP_GATEWAY_PORT:-8001}"
PRELOOP_CONSOLE_PORT="${PRELOOP_CONSOLE_PORT:-3000}"
# Paths are NOT defaulted here. Compose reads docker/.env (this host's own paths) and falls back
# to the relative defaults in compose.poc.yaml; a shell variable would win over both, so one is
# exported only when something actually set it — the environment, or a restored workspace's
# config/instance.env. See docs.docker.com/compose/how-tos/environment-variables/.
export STACK OPS_PORT HUB_PORT MLFLOW_PORT
[ -n "${POC_HOST_DIR:-}" ] && export POC_HOST_DIR
[ -n "${RESEARCH_HOST_DIR:-}" ] && export RESEARCH_HOST_DIR
export PRELOOP_API_PORT PRELOOP_GATEWAY_PORT PRELOOP_CONSOLE_PORT
FORCE=""; [ "$MODE" = "--recreate" ] && FORCE="--force-recreate"

# The instance's own Python libraries go into the image at build (docker/python/python.local,
# OPERATIONS §101), and every line is pinned: a line without == would resolve differently at every
# build, and the release record could not say what the image carries. Prints `none` when there is
# no file, `pinned` when every line is, else the first line that is not.
python_local_report() {  # file
  [ -f "$1" ] || { echo none; return 0; }
  _n=0
  while IFS= read -r _line || [ -n "$_line" ]; do
    _n=$((_n+1))
    _t="$(printf '%s' "$_line" | sed 's/[[:space:]]*#.*$//; s/^[[:space:]]*//; s/[[:space:]]*$//')"
    [ -n "$_t" ] || continue
    case "$_t" in
      [A-Za-z0-9]*==?*) ;;   # a distribution name, == and a version (extras and --hash may follow)
      *) echo "line $_n is not pinned: $_line"; return 0;;
    esac
  done < "$1"
  echo pinned
}

# Apply this stack's policy, and when Preloop refuses it, say what it said. The result line alone
# ("apply failed") sent a reader to the admin container's state file; the cold-start runner failed
# three times before the reason was read from there (a value Preloop 0.15.0 does not accept, §63).
apply_policy() {   # <indent>
  docker exec "$STACK-admin" $PY_IN_AGENT /work/stack/cfg.py apply | grep -o '"preloop-policy[^,]*' | sed "s/^/$1/" || true
  docker exec "$STACK-admin" $PY_IN_AGENT /work/stack/cfg.py status 2>/dev/null \
    | docker exec -i "$STACK-admin" $PY_IN_AGENT -c 'import json,sys
for t in json.load(sys.stdin).get("targets", []):
    if t.get("error"): print("why:", t["target"], "—", t["error"])' | sed "s/^/$1/" || true
}

if [ "$MODE" != "--check" ]; then
  # The containers run as uid 1000; this tree is a bind mount owned by whoever cloned it. On a
  # Windows host that difference does not exist, and on Linux it stops the stack dead: measured on
  # a runner, `cfg.py generate` answered "Permission denied: /work/config/generated" and the
  # account ended up with no MCP servers, so no tool was served through Preloop. Only the two
  # trees the containers actually write to are opened up, and neither holds a secret — the
  # credentials live in docker/*.env, which the host writes and keeps at 0600.
  for d in config/generated evidence evidence/checks evidence/ops evidence/p281 evidence/ui-runs; do
    mkdir -p "$HERE/$d" 2>/dev/null || true
  done
  chmod -R a+rwX "$HERE/config/generated" "$HERE/evidence" 2>/dev/null || true

  echo "== PoC stack (composition: $COMPOSITION)"
  # `--build` because the images whose source is this tree (agent, ops, hub, fsmcp,
  # egress, mlflow) are built from it: without it an edit to ops/server.py or hub/index.html
  # simply does not reach the running stack, and nothing says so. Layers are cached, so an
  # unchanged tree costs a few seconds.
  # What the proxies read is generated: tracked baseline + this instance's own additions (§60).
  # Before the containers start, so a first bring-up on a fresh clone has the file to mount.
  bash "$HERE/scripts/egress_gen.sh" || exit 1
  _pl="$(python_local_report "$HERE/docker/python/python.local")"
  case "$_pl" in none|pinned) ;;
    *) echo "docker/python/python.local: $_pl" >&2
       echo "  every line is one distribution pinned with == (comments and blank lines aside); scripts/packages.py python prints the candidates" >&2
       exit 1;;
  esac
  if [ "$BUILD" = "--no-build" ]; then   # a rollback: the kept images, as they are (§101)
    (cd "$HERE/docker" && docker compose -f compose.poc.yaml up -d --no-build $FORCE) || exit 1
  else
    (cd "$HERE/docker" && docker compose -f compose.poc.yaml up -d --build $FORCE) || exit 1
  fi
  # `up` only starts; a service left out of this composition would keep running from the last one,
  # and freeing its memory is the reason for choosing a smaller composition in the first place.
  # Removing the container leaves its data alone: MLflow's database and artifacts are a bind mount.
  drop=""
  case ",$COMPOSE_PROFILES," in *,record,*) ;; *) drop="$drop mlflow";; esac
  case ",$COMPOSE_PROFILES," in *,ui,*) ;; *) drop="$drop ops hub replay";; esac
  case ",$COMPOSE_PROFILES," in *,observer,*) ;; *) drop="$drop quota";; esac
  if [ -n "$drop" ]; then
    echo "   not in this composition:$drop"
    (cd "$HERE/docker" && COMPOSE_PROFILES="record,ui,observer" docker compose -f compose.poc.yaml rm -sf $drop >/dev/null) || exit 1
  fi
  # The generated settings (config/generated/: runtime.json, profiles/<name>.json) are derived from
  # config/ and git-ignored, so a fresh clone has none — and they used to be generated only on the
  # branch that claims a new Preloop. A clone brought up against an already-claimed instance had
  # no profile, the router could not read research-default, and admission failed with
  # FileNotFoundError (measured on a Windows host, 2026-10-02). Generated here, every time, like
  # the egress lists above; the claim branch below generates again, harmlessly.
  docker exec "$STACK-agent" $PY_IN_AGENT /work/stack/cfg.py generate >/dev/null 2>&1 \
    || echo "  WARN  config/generated could not be written (cfg.py generate) — profiles may be missing" >&2
  # a server whose process is older than the code it serves is restarted (§103); a running
  # brokered call on it ends with the process — a bring-up is the operator's moment for that
  _stale="$(stale_servers | tr '\n' ' ')"
  if [ -n "${_stale% }" ]; then
    echo "== stack servers started before this code — restarting:${_stale:+ }${_stale% }"
    docker restart $_stale >/dev/null || exit 1
  fi
  echo "== Preloop (+ PoC network attachment)"
  docker compose --project-directory "$PRELOOP_DIR" -p "$PRELOOP_PROJECT" \
    -f "$PRELOOP_DIR/docker-compose.yaml" -f "$PRELOOP_DIR/docker-compose.auth.yaml" \
    -f "$HERE/docker/preloop.agentstack.yaml" up -d $FORCE || exit 1
  # Wait for Preloop's API to answer rather than for a number of seconds. On a machine that has
  # run it before, eight seconds was enough and the fixed sleep went unnoticed; on a fresh install
  # the first boot runs migrations, and the claim below met "Connection refused" (measured, on a
  # Linux runner). Asking is also faster when it is already up.
  printf '   waiting for Preloop to answer'
  ready=0
  for i in $(seq 1 90); do
    if docker exec "$STACK-admin" sh -c \
         'curl -fsS -o /dev/null --max-time 3 http://preloop-api:8000/api/v1/openapi.json' 2>/dev/null; then
      ready=1; break
    fi
    [ $((i % 5)) = 0 ] && printf '.'
    sleep 2
  done
  if [ "$ready" = 1 ]; then echo " ok"; else
    echo " no answer after 180s" >&2
    echo "  Preloop did not come up; nothing below would be governed" >&2
    exit 1
  fi

  # A fresh Preloop has no user, and without one nothing in this stack is governed. Claiming it is
  # this stack's work, not the operator's: it is our own container, the bootstrap token is already
  # in it, and nobody has to decide anything (OPERATIONS.md §22). The fact is established by
  # counting rows — `POST /auth/register` on a claimed instance would quietly create a *second
  # account*, so the bootstrap refuses to run without being told the instance is unclaimed.
  preloop_exec() {
    docker compose --project-directory "$PRELOOP_DIR" -p "$PRELOOP_PROJECT"       -f "$PRELOOP_DIR/docker-compose.yaml" -f "$PRELOOP_DIR/docker-compose.auth.yaml"       exec -T "$@" 2>/dev/null
  }
  users="$(preloop_exec postgres psql -U postgres -d preloop -Atc 'select count(*) from "user"' | tr -d '
')"
  if [ "$users" = "0" ]; then
    echo "== Preloop has no user yet — claiming it"
    preloop_exec api printenv PRELOOP_BOOTSTRAP_TOKEN       | docker exec -i "$STACK-admin" $PY_IN_AGENT /work/stack/bootstrap_preloop.py           --unclaimed --api http://preloop-api:8000       || { echo "  the instance could not be claimed — nothing below will be governed" >&2; exit 1; }
    # The container wrote the owner's password inside itself, because this tree is a bind mount
    # owned by the host user and a container cannot write into it on Linux. Moving it here means
    # the file ends up with the host's ownership and mode, and the password never passes through
    # a terminal or a log.
    if docker exec "$STACK-admin" test -f /tmp/preloop-owner.env 2>/dev/null; then
      docker exec "$STACK-admin" cat /tmp/preloop-owner.env >> "$HERE/docker/preloop-owner.env"
      chmod 600 "$HERE/docker/preloop-owner.env" 2>/dev/null || true
      docker exec "$STACK-admin" rm -f /tmp/preloop-owner.env
      echo "   the console account is in docker/preloop-owner.env"
    fi
    # A claimed instance still enforces nothing until this stack's policy is on it: the MCP
    # servers, the tools and the approval workflow all come from policy/. Generating reads the
    # provider logins (agent); applying writes to Preloop (admin) — OPERATIONS.md §21.
    echo "== applying this stack's policy to the new instance"
    docker exec "$STACK-agent" $PY_IN_AGENT /work/stack/cfg.py generate >/dev/null 2>&1 || true
    apply_policy "  "
  else
    # An instance claimed earlier gets this checkout's policy too, on every bring-up. It used to
    # be applied on the claim and when the tool probe failed (below), so a policy-only change — a
    # new deny, a re-read tool list — on an instance brought up with this script rode along
    # unapplied until something else broke: novel-v2 measured the first `..` write reaching the
    # filesystem on an instance updated to e929362, and the denial only after `cfg.py apply` by
    # hand (#78, OPERATIONS §97). `release.sh update` applied it; a plain bring-up did not. `cfg.py
    # apply` answers "already applied" when the account carries this content, so this costs one
    # question, and `--check` below says when the account enforces an older policy.
    echo "== policy"
    apply_policy "  "
  fi
fi

fail=0
FAILED=""
check() {  # name, expected, actual
  if [ "$2" = "$3" ]; then printf '  ok    %-44s %s\n' "$1" "$3"
  else printf '  FAIL  %-44s expected %s, got %s\n' "$1" "$2" "$3"; fail=1
       FAILED="$FAILED{\"check\":\"$1\",\"expected\":\"$2\",\"got\":\"$3\"},"; fi
}
in_agent() { docker exec "$STACK-agent" sh -c "$1" 2>/dev/null; }
in_agent_stdin() { docker exec -i "$STACK-agent" sh -c "$1" 2>/dev/null; }
# The stack's servers — the broker, the profile runners, the replay server — run /work/stack/*.py
# as long-lived processes; a bring-up that rebuilt no image leaves them on the code they started
# with (devflow, #91: half the path on §102, a brokered call COMPLETED with no schema). This names
# the ones whose process predates the newest stack file: the bring-up restarts them, --check says.
stale_servers() {
  docker ps --filter "name=^${STACK}-" --format '{{.Names}}' 2>/dev/null | while read -r c; do
    case "$(docker inspect -f '{{join .Config.Cmd " "}}' "$c" 2>/dev/null)" in
      *"/work/stack/"*) echo "$c $(docker inspect -f '{{.State.StartedAt}}' "$c" 2>/dev/null)";;
    esac
  done | in_agent_stdin "$PY_IN_AGENT /work/stack/stale_servers.py /work/stack"
}

# A fetched package is pinned: installing one gives its principals rights, so what is on disk has
# to be the commit the lock names. Reported here rather than enforced — a package edited on purpose
# during development is a normal state, and being told is the point (OPERATIONS §37).
if [ -f "$HERE/config/packages.lock" ]; then
  bash "$HERE/scripts/packages.sh" verify >/dev/null 2>&1     || echo "  WARN  a fetched package is not what config/packages.lock names — scripts/packages.sh list" >&2
fi

# The identities a workflow's steps run as, and the rights each carries, are declared in
# config/principals.yaml — not remembered from whoever created them by hand. Applying that on
# every bring-up is what keeps a second machine governed the same way as this one; it writes to
# Preloop, so it runs on the admin side (OPERATIONS.md §21, §25).
#
# Not under --check: a check changes nothing (the runbook's promise, and verify.sh's). Until §86
# this ran in every mode, and so did the guard reload and the per-role egress block below — a
# `--check` applied principals, could recreate the agent and restarted the egress proxy, the
# agent's only route to the providers, under whatever call was in flight.
if [ "$MODE" != "--check" ] && docker ps --format '{{.Names}}' | grep -qx "$STACK-admin"; then
  out="$(docker exec "$STACK-admin" $PY_IN_AGENT /work/stack/principals.py apply 2>&1 | tail -1)"
  case "$out" in
    *'"ok": true'*) echo "$out" | grep -q '"changes": \[\]' || echo "== principals: $out";;
    *) echo "  WARN  the declared principals could not be applied: $out" >&2;;
  esac
  # An identity outlives the declaration that asked for it: `apply` creates and updates, never
  # removes, so a package that stopped being declared leaves its principal behind with a live
  # credential. Reported here because a bring-up is where someone is looking (OPERATIONS §40).
  echo "$out" | grep -q '"undeclared": \[\]' || {
    left="$(echo "$out" | sed 's/.*"undeclared": \[//; s/\].*//')"
    [ -n "$left" ] && echo "  NOTE  identities no declaration asks for: $left"                            "— principals.py list shows what each may still do; removing one is yours"
  }
  # A credential just minted is a line in docker/principals.env, which the agent reads as
  # environment when it starts. Without this, a fresh machine has the principals and their rules
  # but the steps that run as them can present nothing until someone runs up.sh a second time —
  # measured on the cold start, where the first bring-up ended with the credentials unread.
  case "$out" in
    *'"restart_needed": true'*)
      # The same reason as the owner's password above: the container minted them and cannot write
      # into this tree, so the host puts them in place and the agent is restarted to read them.
      if docker exec "$STACK-admin" test -f /tmp/principals-new.env 2>/dev/null; then
        [ -f "$HERE/docker/principals.env" ] || \
          printf '# Credentials of the role principals. Written by scripts/up.sh, never versioned.\n' \
            > "$HERE/docker/principals.env"
        docker exec "$STACK-admin" cat /tmp/principals-new.env >> "$HERE/docker/principals.env"
        chmod 600 "$HERE/docker/principals.env" 2>/dev/null || true
        docker exec "$STACK-admin" rm -f /tmp/principals-new.env
      fi
      # Both readers of principals.env: the agent for unmapped roles, and the broker, which alone
      # holds the credentials of the roles that declare an egress profile (§54). Restarting only the
      # agent left the broker with none on a cold start — every brokered review refused with "the
      # broker holds no credential", measured on the first full verify of a fresh instance.
      echo "   new credentials — restarting the agent and the broker so they read them"
      (cd "$HERE/docker" && docker compose -f compose.poc.yaml up -d --force-recreate agent broker >/dev/null 2>&1) \
        || echo "  WARN  the agent or the broker did not restart; run scripts/up.sh again" >&2;;
  esac
fi

# Preloop exposes a tool server's tools only after it has scanned it, and a scan that ran before
# that server was listening leaves a server registered with nothing on it — which `cfg.py apply`
# then records as applied, so no later bring-up puts it right. Measured on a fresh install
# elsewhere: the runtime saw Preloop's own four tools and none of the file tools. The truth is what
# the runtime can see, so that is what is asked, and a scan is the way out.
if [ "$MODE" != "--check" ] && docker ps --format '{{.Names}}' | grep -qx "$STACK-agent"; then
  probe() { docker exec "$STACK-agent" sh -c 'python3 /work/stack/mcp_list.py claude --probe 2>/dev/null' | grep -q "PROBE OK"; }
  if ! probe; then
    echo "== the runtime cannot see the tool servers — applying the policy again, then scanning"
    # Apply first, and only then scan. A rescan alone fixes the case where the servers exist with
    # nothing on them; it cannot fix the one where the account has no servers at all, which is what
    # another machine hit — `GET /mcp-servers` answered `[]` while our record said the work was
    # done. `apply` now checks the account rather than the record, so it repairs both.
    apply_policy "   "
    docker exec "$STACK-admin" $PY_IN_AGENT /work/stack/cfg.py rescan | sed 's/^/   /' || true
    sleep 3
    # A server that was recreated has a new id, and Preloop's api keeps the old one in its own
    # cache: the listing stays right and every call fails. Restarting that one container is what
    # clears it (measured), and it is only done when a call has actually failed.
    if ! probe; then
      echo "   the tools are listed but a call does not reach them — restarting Preloop's api"
      docker restart "$PRELOOP_PROJECT-api-1" >/dev/null 2>&1 || true
      for _ in $(seq 1 30); do probe && break; sleep 3; done
    fi
  fi
fi

# The guard's rules are a bind-mounted file, and compose does not restart a container because a
# file under it changed — a rule edited without this reload is a rule that is not enforced.
if [ "$MODE" != "--check" ] && docker ps --format '{{.Names}}' | grep -qx "$STACK-apiguard"; then
  docker exec "$STACK-apiguard" nginx -t >/dev/null 2>&1 &&
    docker exec "$STACK-apiguard" nginx -s reload >/dev/null 2>&1 ||
    echo "  WARN  the guard did not accept its configuration — the rules in effect are the old ones" >&2
fi

# Grok's native tools are off by a table in its own config file — written by hand on the first
# install and by nothing since, until a second install ran a Grok lane without it (OPERATIONS
# §64). Written here on every bring-up for every grok login the profiles name; idempotent.
if [ "$MODE" != "--check" ] && docker ps --format '{{.Names}}' | grep -qx "$STACK-agent"; then
  in_agent "$PY_IN_AGENT"' /work/stack/grok_posture.py ensure 2>/dev/null' | grep -v '"no login"' | sed 's/^/   grok posture: /' || true
fi

echo "== the stack's servers"
_stale="$(stale_servers | tr '\n' ' ')"
check "the stack's servers run this checkout's code (broker, runners)" none "${_stale:+${_stale% }}${_stale:-none}"
echo "== the image's inputs"
# docker/python/python.local is built into the image (§101); a line that is not pinned fails the
# bring-up, and this says so on a --check too. `none` is a fresh clone.
_plf="$HERE/docker/python/python.local"
check "the instance's Python libraries are pinned (docker/python/python.local)" \
      "$( [ -f "$_plf" ] && echo pinned || echo none )" "$(python_local_report "$_plf")"
echo "== isolation"
# The addresses the checks below probe are the generated settings' (config/generated/runtime.json,
# generated above), read once here — the same ones every step reads, written in environment.yaml
# and nowhere else (OPERATIONS §80). preloop-api:8000 above is a different fact: the admin side's
# name for Preloop's api on its own network.
read -r RT_API RT_MCP RT_MLFLOW RT_PROXY <<<"$(in_agent "$PY_IN_AGENT -c 'import json;d=json.load(open(\"/work/config/generated/runtime.json\"));print(d[\"preloop\"][\"api_url\"],d[\"preloop\"][\"mcp_url\"],d[\"mlflow\"][\"url\"],d[\"egress\"][\"proxy\"])'")"
[ -n "${RT_PROXY:-}" ] || echo "  WARN  could not read config/generated/runtime.json from the agent — the address checks below will fail for that reason" >&2
check "agent default routes"            0   "$(in_agent 'ip route | grep -c default')"
check "agent direct egress"             000 "$(in_agent 'curl -s -o /dev/null -w %{http_code} --max-time 5 https://pypi.org')"
check "egress proxy refuses non-provider" 000 "$(in_agent 'curl -s -o /dev/null -w %{http_code} --max-time 8 -x '"$RT_PROXY"' https://example.com')"
echo "== services"
check "Preloop MCP (auth required)"      401 "$(in_agent 'curl -s -o /dev/null -w %{http_code} '"$RT_MCP"'')"
check "Preloop api"                      200 "$(in_agent 'curl -s -o /dev/null -w %{http_code} '"$RT_API"'/api/v1/openapi.json')"
case ",$COMPOSE_PROFILES," in *,record,*)
  check "MLflow"                         200 "$(in_agent 'curl -s -o /dev/null -w %{http_code} '"$RT_MLFLOW"'/health')";;
  *) printf '  --    %-44s %s
' "MLflow" "not in the $COMPOSITION composition";; esac
case ",$COMPOSE_PROFILES," in *,ui,*)
  check "ops API (127.0.0.1:$OPS_PORT)"    true "$(curl -s --max-time 5 http://127.0.0.1:$OPS_PORT/api/health | grep -q '"ok": true' && echo true || echo false)"
  check "hub UI (127.0.0.1:$HUB_PORT)"      200 "$(curl -s -o /dev/null -w %{http_code} --max-time 5 http://127.0.0.1:$HUB_PORT/)"
  check "hub has no Docker access"        none "$(docker inspect "$STACK-hub" --format '{{if .Mounts}}mounted{{else}}none{{end}}' 2>/dev/null)";;
  *) printf '  --    %-44s %s
' "ops API / hub UI" "not in the $COMPOSITION composition";; esac
check "provider host via proxy (TLS up)" yes "$(in_agent 'c=$(curl -s -o /dev/null -w %{http_code} --max-time 10 -x '"$RT_PROXY"' https://api.anthropic.com); [ "$c" != 000 ] && echo yes || echo no')"
# Not "are the tools listed" but "does a call reach the server": a tool server deleted and
# recreated keeps its listing while every call answers "MCP server <old id> not found"
# (OPERATIONS §28). The probe calls a read-only tool.
check "fsmcp tools work through Preloop"  yes "$(in_agent 'python3 /work/stack/mcp_list.py claude --probe | grep -q "PROBE OK" && echo yes || echo no')"
# The policy the account enforces is this checkout's: `cfg.py status` compares what was last
# applied with the file as it is now (changed_since_apply, replaced, unknown, apply_failed are the
# other answers). A checkout whose policy moved on without an apply is governed by the old one (§97).
check "the account enforces this checkout's policy" applied "$(in_agent "$PY_IN_AGENT"' /work/stack/cfg.py status 2>/dev/null | python3 -c "import json,sys; r=[t for t in json.load(sys.stdin).get(\"targets\",[]) if t[\"target\"].startswith(\"preloop-policy:\")]; print(r[0][\"state\"] if r else \"none\")"')"
# The approval boundary is a route, so it is checked from the position it constrains: the agent
# may read what is waiting and may not answer it (OPERATIONS.md §20).
check "runtime may read approvals"       200 "$(in_agent 'curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer $(cat $(ls /home/agent/.preloop/agents/*/permission_hook.json | head -1) | python3 -c "import json,sys;print(json.load(sys.stdin)[\"token\"])")" "'"$RT_API"'/api/v1/approval-requests?status=pending&limit=1"')"
check "runtime may not decide approvals" 403 "$(in_agent 'curl -s -o /dev/null -w %{http_code} -X POST -H "Content-Type: application/json" -d "{\"approved\":true}" '"$RT_API"'/api/v1/approval-requests/00000000-0000-0000-0000-000000000000/approve')"
check "runtime may read its tool rights"  200 "$(in_agent 'a=$(curl -s -H "Authorization: Bearer $(cat $(ls /home/agent/.preloop/agents/*/permission_hook.json | head -1) | python3 -c "import json,sys;print(json.load(sys.stdin)[\"token\"])")" '"$RT_API"'/api/v1/agents | python3 -c "import json,sys;d=json.load(sys.stdin);r=d if isinstance(d,list) else d.get(\"items\") or [];print(r[0][\"id\"])"); curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer $(cat $(ls /home/agent/.preloop/agents/*/permission_hook.json | head -1) | python3 -c "import json,sys;print(json.load(sys.stdin)[\"token\"])")" '"$RT_API"'/api/v1/agents/$a/governance')"
check "runtime may not rewrite them"      403 "$(in_agent 'curl -s -o /dev/null -w %{http_code} -X PUT -H "Content-Type: application/json" -d "{}" '"$RT_API"'/api/v1/agents/00000000-0000-0000-0000-000000000000/governance')"
check "runtime may not mint credentials"  403 "$(in_agent 'curl -s -o /dev/null -w %{http_code} -X POST -H "Content-Type: application/json" -d "{\"name\":\"probe\"}" '"$RT_API"'/api/v1/auth/api-keys')"
# An instance installed before #34 has claude, Conductor and the Preloop CLI in its home volume as
# well as in the image. The image's are on PATH and run; the volume's copy is dead weight, and
# removing it is the operator's one-time step — said here, not done (§76).
if [ "$(in_agent 'test -d /home/agent/.local/share/claude && echo yes || echo no')" = yes ]; then
  echo "  note  the home volume still carries the pre-#34 toolchain copy (/home/agent/.local), unused:"
  echo "        docker run --rm -v $STACK-agent-home:/vol alpine rm -rf /vol/.local   # with the stack down"
fi
echo "== logins (routing layer)"
check "claude /route login"              true "$(in_agent 'CLAUDE_CONFIG_DIR=/route/claude claude auth status 2>/dev/null | python3 -c "import json,sys;print(str(json.load(sys.stdin).get(\"loggedIn\")).lower())"')"
check "codex /route login"               yes "$(in_agent 'CODEX_HOME=/route/codex codex login status 2>&1 | grep -q "Logged in" && echo yes || echo no')"
check "grok /route login"                yes "$(in_agent 'test -s /route/grok/auth.json && echo yes || echo no')"
# The posture Grok's own config carries: deny Bash/Edit/Write/WebFetch/WebSearch, allow the Preloop
# tools (stack/grok_posture.py). Without it a Grok lane writes with its native tool, waits for a
# person, and ends DENIED. Reported for every grok login the profiles name; `--` when none exists.
if in_agent 'test -s /route/grok/auth.json' >/dev/null 2>&1; then
  check "grok native tools denied in its config" yes "$(in_agent "$PY_IN_AGENT"' /work/stack/grok_posture.py check --brief 2>/dev/null')"
  in_agent "$PY_IN_AGENT"' /work/stack/grok_posture.py check 2>/dev/null' | grep -v '"ok"' | sed 's/^/        /' || true
else
  printf '  --    %-44s %s\n' "grok native tools denied in its config" "no grok login"
fi
# The observer's own login is a second source, not a requirement: codex is read with the login that
# executes (OPERATIONS §29). Reported, not failed — a check that fails on something optional teaches
# an operator to ignore checks.
if docker ps --format '{{.Names}}' | grep -qx "$STACK-quota"; then
  printf '  --    %-44s %s
' "observer codex login (optional)"   "$(docker exec "$STACK-quota" sh -c 'codex login status 2>&1 | grep -q "Logged in" && echo yes || echo no' 2>/dev/null)"
else
  printf '  --    %-44s %s
' "observer codex login (optional)"   "not in this composition (scripts/up.sh --observer)"
fi
echo "== quota observer"
# A login file can exist while its token is dead: the router then reports the provider as
# ineligible for an *unknown* reason, and every run that needs it holds. Being at a limit or
# having a stale observation is ordinary; not being able to tell is not, so only "unknown:" fails.
check "every provider's state is knowable"  0 "$(in_agent "$PY_IN_AGENT"' -c "
import sys; sys.path.insert(0, \"/work/stack\")
import ops_health
bad = ops_health.unknowable()
print(len(bad))
for e in bad: print(\"        \" + e[\"provider\"] + \": \" + str(e[\"why\"]), file=sys.stderr)" 2>/tmp/unknowable')"
in_agent 'cat /tmp/unknowable 2>/dev/null' | head -4
# What the run will meet: the router's own answer, not one source's file. The freshness of the
# observer's file stopped being the model when codex became readable with the login that
# executes — the router said ROUTE while this said no (OPERATIONS §31).
check "the router can choose a provider"  yes "$(in_agent "$PY_IN_AGENT"' -c "
import sys; sys.path.insert(0, \"/work/stack\")
import capabilities
print(\"yes\" if capabilities.probe()[\"admission\"][\"available\"] else \"no\")"')"
# what only the host can see (backups, kept releases) — written down with the time it was looked at
bash "$HERE/scripts/host-state.sh" >/dev/null 2>&1 || true
# The allowlist is one file for one proxy, shared by every container on the governed network: a host
# opened for one package is reachable by all of them. So a bring-up says which open host no installed
# package asks for any more — the same shape as the identity report above (OPERATIONS §45).
orphan_hosts="$(in_agent "$PY_IN_AGENT"' -c "
import json, subprocess, sys
out = subprocess.run([sys.executable, \"/work/stack/packages.py\", \"egress\", \"--json\"],
                     capture_output=True, text=True).stdout
print(\" \".join(json.loads(out or \"{}\").get(\"open_and_undeclared\") or []))"' 2>/dev/null)"
[ -n "$orphan_hosts" ] && echo "  NOTE  open in docker/egress/allow and declared by no package: $orphan_hosts"

# Per-role egress (OPERATIONS §48): a role that declares hosts of its own runs as its own uid and
# reaches them through its own proxy. Nothing here changes for a role that declares none.
#
# Three things have to happen and none of them belongs inside the governed runtime: the role users
# are created (that needs root, so it is done from the host with `docker exec -u 0`), the proxy
# configurations and credentials are written into the volume the agent and the proxy share, and the
# proxy is restarted so it serves them. Not under --check, which asks and changes nothing: the
# platform's own egress-probe always declares hosts, so this block always ran, and every
# `--check` restarted the proxy under the runs (§86).
roles_json=""
[ "$MODE" = "--check" ] || roles_json="$(in_agent "$PY_IN_AGENT"' /work/stack/role_egress.py plan --json' 2>/dev/null)"
case "$roles_json" in
  *'"uid"'*)
    for r in $(echo "$roles_json" | tr ',' '\n' | grep -o '"[a-z][a-z0-9-]*": {"hosts"' | cut -d'"' -f2); do
      u="$(in_agent "$PY_IN_AGENT /work/stack/role_egress.py uid $r" 2>/dev/null)"
      [ -n "$u" ] || continue
      docker exec -u 0 "$STACK-agent" sh -c \
        "id -u $r >/dev/null 2>&1 || useradd -M -u $u -g roles -s /usr/sbin/nologin $r" >/dev/null 2>&1
    done
    # A role's step is the same step: it reads the Preloop permission hook and the provider login the
    # adapter presents, and writes what the CLI keeps beside them. Those are shared by every step in
    # this container today (one uid), and per-role egress does not change that — it changes which
    # hosts the step may reach. So the group the roles share is given what a step needs, and
    # OPERATIONS §48 says plainly that provider credentials are not per-role.
    docker exec -u 0 "$STACK-agent" sh -c '
      chgrp -R roles /home/agent/.preloop /route 2>/dev/null
      chgrp -R roles /home/agent 2>/dev/null
      chmod -R g+rwX /home/agent 2>/dev/null
      chmod g+rwX /route 2>/dev/null
      for d in /route/*/; do chmod -R g+rwX "$d" 2>/dev/null; done
      true' >/dev/null 2>&1
    out="$(docker exec -u 0 "$STACK-agent" $PY_IN_AGENT /work/stack/role_egress.py write 2>&1 | tail -1)"
    case "$out" in
      *'"wrote"'*) echo "== per-role egress: $out";;
      *) echo "  WARN  per-role egress could not be written: $out" >&2;;
    esac
    docker restart "$STACK-egress" >/dev/null 2>&1 && echo "   egress restarted with the role proxies"
    ;;
esac

echo "== capabilities in this composition"
in_agent 'python3 /work/stack/capabilities.py' || true
echo
# Leave the result where the screen can read it: when the checks last ran and what failed.
# A check that has not run for a long time is itself worth seeing.
mkdir -p "$HERE/evidence/checks"
printf '{"at":"%s","stack":"%s","composition":"%s","ok":%s,"failed":[%s],"capabilities":%s}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$STACK" "$COMPOSITION" \
  "$([ $fail = 0 ] && echo true || echo false)" "${FAILED%,}" \
  "$(in_agent 'python3 /work/stack/capabilities.py --json' || echo '{}')" \
  > "$HERE/evidence/checks/last.json"

[ $fail = 0 ] && echo "ALL CHECKS PASSED" || { echo "SOME CHECKS FAILED"; exit 1; }
