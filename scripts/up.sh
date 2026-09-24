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
# What is never optional: Preloop (tool rights and approvals), the egress allowlist proxy, the
# file tool server and the quota observer. Dropping any of those does not make the stack smaller,
# it makes it something else — one that cannot say what an agent was allowed to do.
#
# No manual step afterwards: Preloop joins the PoC networks through docker/preloop.cadp.yaml,
# every PoC container restarts on its own, the quota observer's loop is its container process,
# and logins / Preloop's database / MLflow live in volumes or bind mounts.
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
fi
PRELOOP_DIR="${PRELOOP_DIR:-$HOME/.preloop-oss}"
# docker on Windows needs native paths; path conversion is off below (MSYS_NO_PATHCONV)
command -v cygpath >/dev/null && { PRELOOP_DIR="$(cygpath -m "$PRELOOP_DIR")"; HERE="$(cygpath -m "$HERE")"; }
export MSYS_NO_PATHCONV=1
MODE="up"; COMPOSITION="${COMPOSITION:-full}"
while [ $# -gt 0 ]; do
  case "$1" in
    --composition) COMPOSITION="${2:-full}"; shift 2;;
    --check|--recreate|up) MODE="$1"; shift;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done
case "$COMPOSITION" in
  full)      COMPOSE_PROFILES="record,ui";;
  no-record) COMPOSE_PROFILES="ui";;
  runtime)   COMPOSE_PROFILES="";;
  *) echo "unknown composition: $COMPOSITION (full | no-record | runtime)" >&2; exit 2;;
esac
export COMPOSE_PROFILES
# One instance per name: STACK selects container/volume/network names and the published ports.
# The defaults are the live instance; a restored copy runs under another name (scripts/restore.sh).
STACK="${STACK:-cadp278}"
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
  # `--build` because the images whose source is this tree (agent, ops, hub, toolsvc, fsmcp,
  # egress, mlflow) are built from it: without it an edit to ops/server.py or hub/index.html
  # simply does not reach the running stack, and nothing says so. Layers are cached, so an
  # unchanged tree costs a few seconds.
  (cd "$HERE/docker" && docker compose -f compose.poc.yaml up -d --build $FORCE) || exit 1
  # `up` only starts; a service left out of this composition would keep running from the last one,
  # and freeing its memory is the reason for choosing a smaller composition in the first place.
  # Removing the container leaves its data alone: MLflow's database and artifacts are a bind mount.
  drop=""
  case ",$COMPOSE_PROFILES," in *,record,*) ;; *) drop="$drop mlflow";; esac
  case ",$COMPOSE_PROFILES," in *,ui,*) ;; *) drop="$drop ops hub replay";; esac
  if [ -n "$drop" ]; then
    echo "   not in this composition:$drop"
    (cd "$HERE/docker" && COMPOSE_PROFILES="record,ui" docker compose -f compose.poc.yaml rm -sf $drop >/dev/null) || exit 1
  fi
  echo "== Preloop (+ PoC network attachment)"
  docker compose --project-directory "$PRELOOP_DIR" -p "$PRELOOP_PROJECT" \
    -f "$PRELOOP_DIR/docker-compose.yaml" -f "$PRELOOP_DIR/docker-compose.auth.yaml" \
    -f "$HERE/docker/preloop.cadp.yaml" up -d $FORCE || exit 1
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
    preloop_exec api printenv PRELOOP_BOOTSTRAP_TOKEN       | docker exec -i "$STACK-admin" /opt/venv/bin/python /work/p281/bootstrap_preloop.py           --unclaimed --api http://preloop-api:8000       || { echo "  the instance could not be claimed — nothing below will be governed" >&2; exit 1; }
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
    docker exec "$STACK-agent" /opt/venv/bin/python /work/p281/cfg.py generate >/dev/null 2>&1 || true
    docker exec "$STACK-admin" /opt/venv/bin/python /work/p281/cfg.py apply       | grep -o '"preloop-policy[^,]*' | sed 's/^/  /' || true
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

# The identities a workflow's steps run as, and the rights each carries, are declared in
# config/principals.yaml — not remembered from whoever created them by hand. Applying that on
# every bring-up is what keeps a second machine governed the same way as this one; it writes to
# Preloop, so it runs on the admin side (OPERATIONS.md §21, §25).
if docker ps --format '{{.Names}}' | grep -qx "$STACK-admin"; then
  out="$(docker exec "$STACK-admin" /opt/venv/bin/python /work/p281/principals.py apply 2>&1 | tail -1)"
  case "$out" in
    *'"ok": true'*) echo "$out" | grep -q '"changes": \[\]' || echo "== principals: $out";;
    *) echo "  WARN  the declared principals could not be applied: $out" >&2;;
  esac
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
      echo "   new credentials — restarting the agent so it reads them"
      (cd "$HERE/docker" && docker compose -f compose.poc.yaml up -d --force-recreate agent >/dev/null 2>&1) \
        || echo "  WARN  the agent did not restart; run scripts/up.sh again" >&2;;
  esac
fi

# Preloop exposes a tool server's tools only after it has scanned it, and a scan that ran before
# that server was listening leaves a server registered with nothing on it — which `cfg.py apply`
# then records as applied, so no later bring-up puts it right. Measured on a fresh install
# elsewhere: the runtime saw Preloop's own four tools and none of the file tools. The truth is what
# the runtime can see, so that is what is asked, and a scan is the way out.
if [ "$MODE" != "--check" ] && docker ps --format '{{.Names}}' | grep -qx "$STACK-agent"; then
  if ! docker exec "$STACK-agent" sh -c 'python3 /work/p281/mcp_list.py claude 2>/dev/null'        | grep -q write_file; then
    echo "== the tool servers are registered but not exposed — scanning them again"
    docker exec "$STACK-admin" /opt/venv/bin/python /work/p281/cfg.py rescan | sed 's/^/   /' || true
    sleep 3
  fi
fi

# The guard's rules are a bind-mounted file, and compose does not restart a container because a
# file under it changed — a rule edited without this reload is a rule that is not enforced.
if docker ps --format '{{.Names}}' | grep -qx "$STACK-apiguard"; then
  docker exec "$STACK-apiguard" nginx -t >/dev/null 2>&1 &&
    docker exec "$STACK-apiguard" nginx -s reload >/dev/null 2>&1 ||
    echo "  WARN  the guard did not accept its configuration — the rules in effect are the old ones" >&2
fi

echo "== isolation"
check "agent default routes"            0   "$(in_agent 'ip route | grep -c default')"
check "agent direct egress"             000 "$(in_agent 'curl -s -o /dev/null -w %{http_code} --max-time 5 https://pypi.org')"
check "egress proxy refuses non-provider" 000 "$(in_agent 'curl -s -o /dev/null -w %{http_code} --max-time 8 -x http://egress:8888 https://github.com')"
echo "== services"
check "Preloop MCP (auth required)"      401 "$(in_agent 'curl -s -o /dev/null -w %{http_code} http://console/mcp/v1')"
check "Preloop api"                      200 "$(in_agent 'curl -s -o /dev/null -w %{http_code} http://api:8000/api/v1/openapi.json')"
case ",$COMPOSE_PROFILES," in *,record,*)
  check "MLflow"                         200 "$(in_agent 'curl -s -o /dev/null -w %{http_code} http://mlflow:5000/health')";;
  *) printf '  --    %-44s %s
' "MLflow" "not in the $COMPOSITION composition";; esac
case ",$COMPOSE_PROFILES," in *,ui,*)
  check "ops API (127.0.0.1:$OPS_PORT)"    true "$(curl -s --max-time 5 http://127.0.0.1:$OPS_PORT/api/health | grep -q '"ok": true' && echo true || echo false)"
  check "hub UI (127.0.0.1:$HUB_PORT)"      200 "$(curl -s -o /dev/null -w %{http_code} --max-time 5 http://127.0.0.1:$HUB_PORT/)"
  check "hub has no Docker access"        none "$(docker inspect "$STACK-hub" --format '{{if .Mounts}}mounted{{else}}none{{end}}' 2>/dev/null)";;
  *) printf '  --    %-44s %s
' "ops API / hub UI" "not in the $COMPOSITION composition";; esac
check "provider host via proxy (TLS up)" yes "$(in_agent 'c=$(curl -s -o /dev/null -w %{http_code} --max-time 10 -x http://egress:8888 https://api.anthropic.com); [ "$c" != 000 ] && echo yes || echo no')"
check "fsmcp tools exposed via Preloop"  yes "$(in_agent 'python3 /work/p281/mcp_list.py claude | grep -q write_file && echo yes || echo no')"
# The approval boundary is a route, so it is checked from the position it constrains: the agent
# may read what is waiting and may not answer it (OPERATIONS.md §20).
check "runtime may read approvals"       200 "$(in_agent 'curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer $(cat /home/agent/.preloop/agents/*/permission_hook.json | python3 -c "import json,sys;print(json.load(sys.stdin)[\"token\"])")" "http://api:8000/api/v1/approval-requests?status=pending&limit=1"')"
check "runtime may not decide approvals" 403 "$(in_agent 'curl -s -o /dev/null -w %{http_code} -X POST -H "Content-Type: application/json" -d "{\"approved\":true}" http://api:8000/api/v1/approval-requests/00000000-0000-0000-0000-000000000000/approve')"
check "runtime may read its tool rights"  200 "$(in_agent 'a=$(curl -s -H "Authorization: Bearer $(cat /home/agent/.preloop/agents/*/permission_hook.json | python3 -c "import json,sys;print(json.load(sys.stdin)[\"token\"])")" http://api:8000/api/v1/agents | python3 -c "import json,sys;d=json.load(sys.stdin);r=d if isinstance(d,list) else d.get(\"items\") or [];print(r[0][\"id\"])"); curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer $(cat /home/agent/.preloop/agents/*/permission_hook.json | python3 -c "import json,sys;print(json.load(sys.stdin)[\"token\"])")" http://api:8000/api/v1/agents/$a/governance')"
check "runtime may not rewrite them"      403 "$(in_agent 'curl -s -o /dev/null -w %{http_code} -X PUT -H "Content-Type: application/json" -d "{}" http://api:8000/api/v1/agents/00000000-0000-0000-0000-000000000000/governance')"
check "runtime may not mint credentials"  403 "$(in_agent 'curl -s -o /dev/null -w %{http_code} -X POST -H "Content-Type: application/json" -d "{\"name\":\"probe\"}" http://api:8000/api/v1/auth/api-keys')"
echo "== logins (routing layer)"
check "claude /route login"              true "$(in_agent 'CLAUDE_CONFIG_DIR=/route/claude claude auth status 2>/dev/null | python3 -c "import json,sys;print(str(json.load(sys.stdin).get(\"loggedIn\")).lower())"')"
check "codex /route login"               yes "$(in_agent 'CODEX_HOME=/route/codex codex login status 2>&1 | grep -q "Logged in" && echo yes || echo no')"
check "grok /route login"                yes "$(in_agent 'test -s /route/grok/auth.json && echo yes || echo no')"
check "observer codex login"             yes "$(docker exec "$STACK-quota" sh -c 'codex login status 2>&1 | grep -q "Logged in" && echo yes || echo no' 2>/dev/null)"
echo "== quota observer"
# A login file can exist while its token is dead: the router then reports the provider as
# ineligible for an *unknown* reason, and every run that needs it holds. Being at a limit or
# having a stale observation is ordinary; not being able to tell is not, so only "unknown:" fails.
check "every provider's state is knowable"  0 "$(in_agent '/opt/venv/bin/python -c "
import sys; sys.path.insert(0, \"/work/p281\")
import ops_health
bad = ops_health.unknowable()
print(len(bad))
for e in bad: print(\"        \" + e[\"provider\"] + \": \" + str(e[\"why\"]), file=sys.stderr)" 2>/tmp/unknowable')"
in_agent 'cat /tmp/unknowable 2>/dev/null' | head -4
check "observation fresh (< 10 min)"     yes "$(in_agent 'python3 -c "
import json,datetime as d
r=json.load(open(\"/obs/codex.raw.json\")); t=d.datetime.fromisoformat(r[\"collected_at\"].replace(\"Z\",\"+00:00\"))
print(\"yes\" if r.get(\"exit\")==0 and (d.datetime.now(d.timezone.utc)-t).total_seconds()<600 else \"no\")"')"
# what only the host can see (backups, kept releases) — written down with the time it was looked at
bash "$HERE/scripts/host-state.sh" >/dev/null 2>&1 || true
echo "== capabilities in this composition"
in_agent 'python3 /work/p281/capabilities.py' || true
echo
# Leave the result where the screen can read it: when the checks last ran and what failed.
# A check that has not run for a long time is itself worth seeing.
mkdir -p "$HERE/evidence/checks"
printf '{"at":"%s","stack":"%s","composition":"%s","ok":%s,"failed":[%s],"capabilities":%s}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$STACK" "$COMPOSITION" \
  "$([ $fail = 0 ] && echo true || echo false)" "${FAILED%,}" \
  "$(in_agent 'python3 /work/p281/capabilities.py --json' || echo '{}')" \
  > "$HERE/evidence/checks/last.json"

[ $fail = 0 ] && echo "ALL CHECKS PASSED" || { echo "SOME CHECKS FAILED"; exit 1; }
