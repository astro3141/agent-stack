#!/usr/bin/env bash
# Install and verify the workflow packages this instance declares.
#
#   scripts/packages.sh list              what is declared, what is installed, what the lock says
#   scripts/packages.sh install [name]    fetch what is declared and not local, and lock it
#   scripts/packages.sh verify            is what is on disk what the lock says
#
# Declared in config/packages.yaml, locked in config/packages.lock. A package that lives in this
# repository is `from: local` and needs neither: this repo's history is its history. One that lives
# elsewhere is fetched into packages/<name>. Nothing has to be excluded for it: packages/* is
# ignored by default and this repository's own packages are the named exceptions (OPERATIONS §42).
#
# **The fetch happens here, on the host.** Cloning from inside a container would mean a git
# credential the governed runtime can reach, for no reason: the package is a directory, and the
# host can put it there. Installing a package is also a trust decision — it brings principals that
# scripts/up.sh will create and give credentials to — which is why it is pinned and verified rather
# than followed (OPERATIONS §37).
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
command -v cygpath >/dev/null && HERE="$(cygpath -m "$HERE")"
export MSYS_NO_PATHCONV=1
DECL="$HERE/config/packages.yaml"
LOCK="$HERE/config/packages.lock"
PKGDIR="$HERE/packages"
CMD="${1:-list}"
ONLY="${2:-}"

[ -f "$DECL" ] || { echo "no config/packages.yaml — nothing is declared" >&2; exit 1; }

# The declaration is read with the same parser everything else uses, and printed as plain lines so
# this script never guesses at YAML: "<name> <from> <ref>"
declared() {
  docker exec -i "$STACK-agent" /opt/venv/bin/python -c '
import os, yaml
d = {}
for p in ("/work/config/packages.yaml", "/work/config/packages.local.yaml"):
    if os.path.isfile(p):
        d.update((yaml.safe_load(open(p, encoding="utf-8")) or {}).get("packages") or {})
for name, spec in sorted(d.items()):
    spec = spec or {}
    print(name, spec.get("from", "local"), spec.get("ref", "main"))
' 2>/dev/null
}

# A package this repository does not carry is declared in config/packages.local.yaml and pinned in
# config/packages.local.lock — both git-ignored, so the tracked declaration stays one a stranger
# who clones this repository can actually run (OPERATIONS §41).
LOCAL_LOCK="$HERE/config/packages.local.lock"

lock_file_for() {   # name — which lock this package's pin belongs in
  if grep -qE "^  $1:" "$HERE/config/packages.local.yaml" 2>/dev/null; then
    echo "$LOCAL_LOCK"
  else
    echo "$LOCK"
  fi
}
STACK="${STACK:-agentstack}"
[ -f "$HERE/config/instance.env" ] && . "$HERE/config/instance.env"

locked_commit() {   # name
  cat "$LOCK" "$LOCAL_LOCK" 2>/dev/null | grep -E "^$1 " | awk '{print $2}' | head -1
}

write_lock() {      # name commit ref url
  f="$(lock_file_for "$1")"
  touch "$f"
  grep -vE "^$1 " "$f" > "$f.tmp" 2>/dev/null || true
  printf '%s %s %s %s\n' "$1" "$2" "$3" "$4" >> "$f.tmp"
  sort -o "$f" "$f.tmp" && rm -f "$f.tmp"
}



state_of() {        # name from — prints one line
  local name="$1" from="$2" ref="$3" dir="$PKGDIR/$1"
  if [ "$from" = "local" ]; then
    [ -d "$dir" ] && printf '  %-14s %-8s %s\n' "$name" "local" "in this repository" \
                  || printf '  %-14s %-8s %s\n' "$name" "local" "DECLARED BUT NOT THERE"
    return
  fi
  if [ ! -d "$dir/.git" ]; then
    printf '  %-14s %-8s %s\n' "$name" "$ref" "not installed — scripts/packages.sh install"
    return
  fi
  local head dirty locked
  head="$(git -C "$dir" rev-parse HEAD 2>/dev/null)"
  dirty="$(git -C "$dir" status --porcelain 2>/dev/null | head -1)"
  locked="$(locked_commit "$name")"
  if [ -n "$dirty" ]; then
    printf '  %-14s %-8s %s\n' "$name" "$ref" "CHANGED on disk (${head:0:8})"
  elif [ -n "$locked" ] && [ "$head" != "$locked" ]; then
    printf '  %-14s %-8s %s\n' "$name" "$ref" "at ${head:0:8}, locked ${locked:0:8}"
  else
    printf '  %-14s %-8s %s\n' "$name" "$ref" "${head:0:8}"
  fi
}

case "$CMD" in
  list)
    echo "== declared in config/packages.yaml"
    declared | while read -r name from ref; do state_of "$name" "$from" "$ref"; done
    extra="$(comm -13 <(declared | awk '{print $1}' | sort) \
                      <(ls -1 "$PKGDIR" 2>/dev/null | sort) 2>/dev/null)"
    [ -n "$extra" ] && { echo "== on disk and not declared"; echo "$extra" | sed 's/^/  /'; }
    exit 0;;

  verify)
    fail=0
    declared | while read -r name from ref; do
      [ "$from" = "local" ] && continue
      dir="$PKGDIR/$name"
      [ -d "$dir/.git" ] || { echo "  MISSING  $name — declared, not installed" >&2; exit 1; }
      head="$(git -C "$dir" rev-parse HEAD)"
      locked="$(locked_commit "$name")"
      changed="$(git -C "$dir" status --porcelain | awk '{print $2}' | head -3)"
      changed="$(echo $changed)"        # one line, whatever the shell splits it into
      [ -n "$changed" ] && {
        echo "  CHANGED  $name — edited on disk: $changed" >&2
        echo "           commit it in its own repository, or re-install. A file the runtime writes" >&2
        echo "           (__pycache__) belongs in that repository's .gitignore, not in the pin." >&2
        exit 1; }
      [ "$head" = "$locked" ] || {
        echo "  DRIFT    $name — at ${head:0:8}, locked ${locked:0:8}" >&2; exit 1; }
    done || fail=1
    [ "$fail" = 0 ] && echo "every fetched package is at the commit config/packages.lock names"
    exit "$fail";;

  install)
    declared | while read -r name from ref; do
      [ "$from" = "local" ] && continue
      [ -n "$ONLY" ] && [ "$ONLY" != "$name" ] && continue
      dir="$PKGDIR/$name"
      if [ -d "$dir/.git" ]; then
        echo "== $name: fetching $ref"
        git -C "$dir" fetch --quiet origin "$ref" || { echo "  could not fetch $name" >&2; continue; }
        git -C "$dir" checkout --quiet FETCH_HEAD || { echo "  could not check out $ref" >&2; continue; }
      else
        echo "== $name: cloning $from at $ref"
        rm -rf "$dir"
        git clone --quiet --depth 1 --branch "$ref" "$from" "$dir" 2>/dev/null \
          || git clone --quiet "$from" "$dir" \
          || { echo "  could not clone $name" >&2; continue; }
        git -C "$dir" checkout --quiet "$ref" 2>/dev/null || true
      fi
      head="$(git -C "$dir" rev-parse HEAD)"
      write_lock "$name" "$head" "$ref" "$from"
      echo "   at ${head:0:8}, locked"
    done
    echo
    echo "now: scripts/up.sh   (its principals are created and given credentials there)"
    exit 0;;

  *) echo "usage: scripts/packages.sh [list|install|verify] [name]" >&2; exit 2;;
esac
