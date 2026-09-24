#!/usr/bin/env bash
# Stop the instance THIS workspace belongs to — the one named in config/instance.env if that file
# exists (a restored copy), otherwise the live one.
#
#   scripts/down.sh [--volumes] [--now]
#
# A run that is going is stopped first, and stopped the way a person would stop it: Conductor's
# graceful cancel, which lets the run write a checkpoint (OPERATIONS.md §23). Pulling the container
# out from under a run instead loses the step it was in and everything it had not recorded, and
# leaves nothing to resume from. --now skips that and takes the containers down immediately.
#
# --volumes also deletes that instance's volumes: its provider logins, its Preloop database and
# its agent home. It prints exactly what it will remove and refuses anything named differently.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$HERE/config/instance.env" ]; then
  while IFS='=' read -r k v; do
    case "$k" in ''|'#'*) continue;; esac
    eval "[ -n \"\${$k:-}\" ]" || eval "$k=\$v"
  done < "$HERE/config/instance.env"
fi
PRELOOP_DIR="${PRELOOP_DIR:-$HOME/.preloop-oss}"
command -v cygpath >/dev/null && { PRELOOP_DIR="$(cygpath -m "$PRELOOP_DIR")"; HERE="$(cygpath -m "$HERE")"; }
export MSYS_NO_PATHCONV=1
STACK="${STACK:-agentstack}"
PRELOOP_PROJECT="${PRELOOP_PROJECT:-preloop-oss}"
# as in up.sh: never default a path here, or it would win over docker/.env
export STACK
[ -n "${POC_HOST_DIR:-}" ] && export POC_HOST_DIR
[ -n "${RESEARCH_HOST_DIR:-}" ] && export RESEARCH_HOST_DIR
VOLUMES=0; NOW=0
for a in "$@"; do
  case "$a" in
    --volumes) VOLUMES=1;;
    --now) NOW=1;;
    *) echo "unknown argument: $a" >&2; exit 2;;
  esac
done

echo "instance : $STACK   (Preloop project $PRELOOP_PROJECT)"
echo "workspace: ${POC_HOST_DIR:-$HERE (compose defaults / docker/.env)}"
# A run in flight is stopped before the containers are, so it leaves a checkpoint and can be
# continued after the next bring-up. Asked of the run list, not assumed from a lock file.
if [ "$NOW" = 0 ] && docker ps --format '{{.Names}}' | grep -qx "$STACK-agent"; then
  RUNNING="$(docker exec "$STACK-agent" /opt/venv/bin/python -c '
import json, subprocess
out = subprocess.run(["/opt/venv/bin/python", "/work/stack/run_workflow.py", "list"],
                     capture_output=True, text=True).stdout
print(" ".join(r["ui_id"] for r in json.loads(out or "[]") if r.get("state") == "running"))
' 2>/dev/null | tr -d '\r')"
  if [ -n "${RUNNING:-}" ]; then
    echo "== runs in flight: $RUNNING"
    for ui in $RUNNING; do
      echo "   stopping $ui (graceful: it keeps its checkpoint)"
      docker exec "$STACK-agent" /opt/venv/bin/python /work/stack/run_workflow.py stop "$ui" >/dev/null 2>&1 \
        || echo "   WARN  $ui did not accept the stop" >&2
    done
    # give the runs their own cancel path; a run that ignores it is reported, not waited on forever
    for _ in $(seq 1 30); do
      left="$(docker exec "$STACK-agent" sh -c 'ps -eo args | grep -c "[r]un_workflow.py start"' 2>/dev/null | tr -d '\r')"
      [ "${left:-0}" = "0" ] && break
      sleep 2
    done
    [ "${left:-0}" = "0" ] || echo "   WARN  $left launcher(s) still running; taking the stack down anyway" >&2
  fi
fi

echo "== stopping"
# every profile, whatever composition was up: nothing may be left behind because it was optional
(cd "$HERE/docker" && COMPOSE_PROFILES="record,ui" docker compose -f compose.poc.yaml down) || exit 1
docker compose --project-directory "$PRELOOP_DIR" -p "$PRELOOP_PROJECT" \
  -f "$PRELOOP_DIR/docker-compose.yaml" -f "$PRELOOP_DIR/docker-compose.auth.yaml" down || exit 1

if [ "$VOLUMES" = 1 ]; then
  # Exact names only. A prefix match would also take another instance's volumes: with
  # STACK=agentstackr, "agentstackr-second-route-creds" starts with "agentstackr-" too.
  VOLS=""
  for n in "$STACK-agent-home" "$STACK-ws" "$STACK-quota-home" "$STACK-route-creds" \
           "$STACK-quota-obs" "${PRELOOP_PROJECT}_postgres-data"; do
    docker volume inspect "$n" >/dev/null 2>&1 && VOLS="$VOLS $n"
  done
  if [ -z "$VOLS" ]; then
    echo "== no volumes of $STACK left"
  else
    echo "== removing the volumes of $STACK (logins, Preloop database, agent home):"
    for n in $VOLS; do echo "     $n"; done
    docker volume rm $VOLS >/dev/null && echo "  removed"
  fi
fi
