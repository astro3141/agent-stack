#!/usr/bin/env bash
# config/instance.env → docker/.env, key by key, so that `docker compose` run by hand in this
# directory names the same instance scripts/up.sh does.
#
#   scripts/instance_env.sh [<workspace>]      default: the tree this script is in
#
# up.sh exported STACK and the ports into its own environment only; compose read docker/.env, which
# nothing on a fresh clone wrote. In a second instance's tree a bare `docker compose …` therefore
# fell back to `${STACK:-agentstack}` — the live instance's names — and made its networks there
# (measured on the second cold start, OPERATIONS §69). Keys the operator added to docker/.env by
# hand (this host's own paths) are kept; only the keys instance.env names are written.
set -u
WS="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
SRC="$WS/config/instance.env"; DST="$WS/docker/.env"
[ -f "$SRC" ] || exit 0
touch "$DST"
TMP="$(mktemp)"
# every key instance.env names, with its value from instance.env; every other line of docker/.env as it was
awk -F= '
  NR == FNR { if ($0 ~ /^[A-Za-z_][A-Za-z0-9_]*=/) { v[$1] = substr($0, length($1) + 2); order[++n] = $1 }; next }
  /^[A-Za-z_][A-Za-z0-9_]*=/ && ($1 in v) { if (!($1 in done)) { print $1 "=" v[$1]; done[$1] = 1 }; next }
  { print }
  END { for (i = 1; i <= n; i++) if (!(order[i] in done)) print order[i] "=" v[order[i]] }
' "$SRC" "$DST" > "$TMP" && mv "$TMP" "$DST"
