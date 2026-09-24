#!/usr/bin/env bash
# From a clone to a running stack — the step OPERATIONS.md §6 used to call out of scope.
#
#   scripts/install.sh [--check] [--preloop-dir DIR] [--no-preloop]
#
#   --check         say what is missing and change nothing
#   --preloop-dir   where Preloop OSS lives (default ~/.preloop-oss)
#   --no-preloop    assume Preloop is already installed there
#   PRELOOP_VERSION which Preloop OSS to install (default 0.15.0, the measured one)
#
# What it does, in order:
#   1. checks the host has what this stack needs, with versions, and stops on the first thing
#      that is missing rather than failing later inside a container;
#   2. installs Preloop OSS if that directory is not there (their installer, not ours);
#   3. hands over to scripts/up.sh, which builds this tree's images, claims a fresh Preloop,
#      applies the policy and the declared principals, and then checks the result.
#
# What it deliberately does not do: sign in to any provider. Those are accounts at third parties,
# tied to a person, and the panel's 계정 tab is where that happens (README, OPERATIONS §22).
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
command -v cygpath >/dev/null && HERE="$(cygpath -m "$HERE")"
export MSYS_NO_PATHCONV=1

CHECK_ONLY=0
NO_PRELOOP=0
# An instance says what it is in config/instance.env — its name, ports, and where its Preloop
# lives. up.sh reads it; this must too, or a second instance's install would check, and then
# install over, the live one's directory. Values already in the environment win, as there.
if [ -f "$HERE/config/instance.env" ]; then
  while IFS='=' read -r k v; do
    case "$k" in ''|'#'*) continue;; esac
    eval "[ -n \"\${$k:-}\" ]" || eval "$k=\$v"
  done < "$HERE/config/instance.env"
fi
PRELOOP_DIR="${PRELOOP_DIR:-$HOME/.preloop-oss}"
PRELOOP_VERSION="${PRELOOP_VERSION:-0.15.0}"      # what this stack has been measured against
while [ $# -gt 0 ]; do
  case "$1" in
    --check) CHECK_ONLY=1;;
    --no-preloop) NO_PRELOOP=1;;
    --preloop-dir) PRELOOP_DIR="$2"; shift;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
  shift
done

miss=0
need() {   # name, what-we-found, how-to-get-it
  if [ -n "$2" ]; then printf '  ok    %-28s %s\n' "$1" "$2"
  else printf '  MISS  %-28s %s\n' "$1" "$3"; miss=1; fi
}
# A version as one comparable number: 2.24.1 -> 2024001. Enough for "at least".
vnum() { echo "$1" | awk -F. '{printf "%d%03d%03d", $1, $2, $3}'; }

echo "== the host"
need "bash"    "$(bash --version 2>/dev/null | head -1 | sed 's/.*version //;s/ .*//')" "install bash"
need "git"     "$(git --version 2>/dev/null | awk '{print $3}')" "install git"
need "docker"  "$(docker --version 2>/dev/null | awk '{print $3}' | tr -d ,)" "install Docker"
need "docker daemon" "$(docker info --format '{{.ServerVersion}}' 2>/dev/null)" "start Docker"

# Compose 2.24 is not a preference: docker/compose.poc.yaml uses `env_file: required: false`,
# and the throwaway-instance override uses `!reset`. Older compose fails with a parse error
# whose message does not say which feature it did not know.
cv="$(docker compose version --short 2>/dev/null | sed 's/^v//')"
if [ -n "$cv" ] && [ "$(vnum "$cv")" -ge "$(vnum 2.24.0)" ]; then
  need "docker compose >= 2.24" "$cv"
else
  need "docker compose >= 2.24" "" "have $cv — 2.24 introduced env_file.required and !reset"
fi

# The agent image picks its Node and CodexBar by architecture. amd64 is what this stack has been
# built and run on; arm64 is parameterized and untried, which is worth saying before a build rather
# than after it. Anything else fails at those lines by design.
arch="$(docker info --format '{{.Architecture}}' 2>/dev/null)"
case "$arch" in
  x86_64|amd64)  need "architecture" "$arch";;
  aarch64|arm64) need "architecture" "$arch (parameterized, never built here — OPERATIONS §25)";;
  "")            need "architecture" "" "could not ask Docker";;
  *)             need "architecture" "" "$arch — the agent image has no Node or CodexBar for it";;
esac

free_gb="$(docker run --rm alpine:3.20 df -P /var 2>/dev/null | awk 'NR==2 {print int($4/1048576)}')"
if [ -n "$free_gb" ] && [ "$free_gb" -ge 20 ]; then need "disk for images" "${free_gb}GB free"
else need "disk for images" "" "the images come to about 11GB (measured), plus volumes and build cache"; fi

# Preloop's compose writes 8000 / 8001 / 3000 into the file, so on a machine already running an
# instance the ports have to come from somewhere else. A `docker-compose.override.yaml` does NOT
# do it: compose reads that file only when it resolves the files itself, and every call here —
# theirs and ours — names them with `-f`. That was measured the wrong way round once and believed;
# an arm64 host with a Preloop already on 8000 is where it showed (OPERATIONS §25).
#
# So the file itself is made instance-aware, once, in place: the three published ports become
# variables with Preloop's own numbers as the defaults. Idempotent, and it survives their upgrade
# only until the installer re-downloads the file — which is why it runs on every install.
patch_preloop_ports() {
  f="$PRELOOP_DIR/docker-compose.yaml"
  [ -f "$f" ] || return 0
  # a stale override of ours would be a second owner of the same ports
  o="$PRELOOP_DIR/docker-compose.override.yaml"
  [ -f "$o" ] && grep -q 'written by agent-stack' "$o" && rm -f "$o"
  if grep -q 'PRELOOP_API_PORT' "$f"; then
    printf '  ok    %-28s %s\n' "ports are this instance's" "already patched"
    return 0
  fi
  cp "$f" "$f.before-agent-stack"
  sed -i.tmp \
    -e 's|^\( *- \)"8000:8000"|\1"${PRELOOP_API_PORT:-8000}:8000"|' \
    -e 's|^\( *- \)"8001:8000"|\1"${PRELOOP_GATEWAY_PORT:-8001}:8000"|' \
    -e 's|^\( *- \)"3000:80"|\1"${PRELOOP_CONSOLE_PORT:-3000}:80"|' "$f"
  rm -f "$f.tmp"
  if grep -q 'PRELOOP_API_PORT' "$f"; then
    printf '  ok    %-28s %s\n' "ports are this instance's" \
      "api ${PRELOOP_API_PORT:-8000}, gateway ${PRELOOP_GATEWAY_PORT:-8001}, console ${PRELOOP_CONSOLE_PORT:-3000}"
  else
    echo "  note  could not make $f use this instance's ports — it publishes whatever it says" >&2
  fi
}

echo "== Preloop OSS"
if [ -f "$PRELOOP_DIR/docker-compose.yaml" ]; then
  printf '  ok    %-28s %s\n' "installed" "$PRELOOP_DIR"
  [ -f "$PRELOOP_DIR/.env" ] || { printf '  MISS  %-28s %s\n' ".env" "$PRELOOP_DIR/.env is missing"; miss=1; }
  # an install that predates this file gets it too, so its ports stop depending on Preloop's own
  [ "$CHECK_ONLY" = 1 ] || patch_preloop_ports
elif [ "$NO_PRELOOP" = 1 ]; then
  printf '  MISS  %-28s %s\n' "installed" "--no-preloop was given but $PRELOOP_DIR has no compose file"; miss=1
elif [ "$CHECK_ONLY" = 1 ]; then
  printf '  --    %-28s %s\n' "installed" "not there; install.sh would run Preloop's own installer"
else
  echo "  not there — running Preloop's own installer into $PRELOOP_DIR"
  # INSTALL_DIR is theirs and defaults to ~/.preloop-oss: without passing it, --preloop-dir would
  # be honoured by the check above and ignored by the install, which on a machine that already has
  # an instance would write over it. PRELOOP_SKIP_ADMIN because claiming the instance is this
  # stack's own step (OPERATIONS §22) and it must not be done twice; PRELOOP_SKIP_SMTP because
  # this stack sends no mail.
  # Their installer takes whatever is current unless told otherwise. Everything this stack measures
  # — the governance endpoints, the MCP scan, what a credential resolves to — was measured against
  # 0.15.0, and a second machine that quietly got 0.16.0 is a different subject. Pin by default,
  # override deliberately: PRELOOP_VERSION=0.16.0 scripts/install.sh
  echo "  version $PRELOOP_VERSION (PRELOOP_VERSION overrides; this stack is measured against 0.15.0)"
  INSTALL_DIR="$PRELOOP_DIR" PRELOOP_VERSION="$PRELOOP_VERSION" \
    PRELOOP_SKIP_ADMIN=1 PRELOOP_SKIP_SMTP=1 \
    sh -c 'curl -fsSL https://preloop.ai/install/oss | sh' \
    || installer_rc=1
  [ -f "$PRELOOP_DIR/docker-compose.yaml" ] || {
    echo "  the installer did not leave a compose file in $PRELOOP_DIR — see README" >&2; exit 1; }
  # Their installer ends by starting the stack on its own numbers, which on a machine that already
  # runs a Preloop cannot bind. That is not a failed install: the files are there, and the ports
  # are this instance's from here on. Nothing of the other instance is touched either way.
  if [ "${installer_rc:-0}" != 0 ]; then
    echo "  the installer could not start Preloop itself (its own ports); continuing on this"
    echo "  instance's ports"
  fi
  patch_preloop_ports
fi

if [ "$miss" = 1 ]; then
  echo
  echo "something above is missing; nothing was changed" >&2
  exit 1
fi
if [ "$CHECK_ONLY" = 1 ]; then
  echo
  echo "the host can run this stack"
  exit 0
fi

echo "== the stack"
PRELOOP_DIR="$PRELOOP_DIR" exec bash "$HERE/scripts/up.sh"
