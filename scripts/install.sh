#!/usr/bin/env bash
# From a clone to a running stack — the step OPERATIONS.md §6 used to call out of scope.
#
#   scripts/install.sh [--check] [--preloop-dir DIR] [--no-preloop]
#
#   --check         say what is missing and change nothing
#   --preloop-dir   where Preloop OSS lives (default ~/.preloop-oss)
#   --no-preloop    assume Preloop is already installed there
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
PRELOOP_DIR="${PRELOOP_DIR:-$HOME/.preloop-oss}"
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

# The agent image fetches x86_64 binaries (Node, CodexBar). On another architecture the build
# fails at those lines; saying so here is cheaper than a five-minute build that ends in a tar error.
arch="$(docker info --format '{{.Architecture}}' 2>/dev/null)"
case "$arch" in
  x86_64|amd64) need "architecture" "$arch";;
  "")           need "architecture" "" "could not ask Docker";;
  *)            need "architecture" "" "$arch — docker/agent.Dockerfile installs x86_64 Node and CodexBar";;
esac

free_gb="$(docker run --rm alpine:3.20 df -P /var 2>/dev/null | awk 'NR==2 {print int($4/1048576)}')"
if [ -n "$free_gb" ] && [ "$free_gb" -ge 20 ]; then need "disk for images" "${free_gb}GB free"
else need "disk for images" "" "about 20GB is needed for the images and volumes"; fi

echo "== Preloop OSS"
if [ -f "$PRELOOP_DIR/docker-compose.yaml" ]; then
  printf '  ok    %-28s %s\n' "installed" "$PRELOOP_DIR"
  [ -f "$PRELOOP_DIR/.env" ] || { printf '  MISS  %-28s %s\n' ".env" "$PRELOOP_DIR/.env is missing"; miss=1; }
elif [ "$NO_PRELOOP" = 1 ]; then
  printf '  MISS  %-28s %s\n' "installed" "--no-preloop was given but $PRELOOP_DIR has no compose file"; miss=1
elif [ "$CHECK_ONLY" = 1 ]; then
  printf '  --    %-28s %s\n' "installed" "not there; install.sh would run Preloop's own installer"
else
  echo "  not there — running Preloop's own installer into $PRELOOP_DIR"
  curl -fsSL https://preloop.ai/install/oss | sh || { echo "  the Preloop installer failed" >&2; exit 1; }
  [ -f "$PRELOOP_DIR/docker-compose.yaml" ] || {
    echo "  the installer did not leave a compose file in $PRELOOP_DIR — see README" >&2; exit 1; }
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
