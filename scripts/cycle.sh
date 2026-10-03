#!/usr/bin/env bash
# One unattended cycle, for a scheduler to call.
#
#   scripts/cycle.sh <workflow> [profile] [--allow-unrecorded] [--retain-days N] [--retain-keep M]
#
# The rules live in stack/cycle.py — one cycle at a time behind a lock this never breaks, a refusal
# when the stack is missing a capability the run needs, one line per cycle (and per skip, and per
# refusal) in evidence/ops/cycles.jsonl, and retention only when asked for. This script is the way
# a scheduler on the host reaches that implementation; it deliberately holds no rules of its own,
# because a second copy of them would drift from the first.
#
# Exit codes are for the scheduler: 0 = a cycle ran (whatever the workflow decided) or one was
# already running; 3 = the stack could not run it; anything else = the runner itself failed.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
command -v cygpath >/dev/null && HERE="$(cygpath -m "$HERE")"
export MSYS_NO_PATHCONV=1
[ -f "$HERE/config/instance.env" ] && . "$HERE/config/instance.env"
STACK="${STACK:-agentstack}"

exec docker exec "$STACK-agent" /opt/venv/bin/python /work/stack/cycle.py "$@" --by scheduler
