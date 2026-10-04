#!/usr/bin/env bash
# Install and verify the workflow packages this instance declares.
#
#   scripts/packages.sh list              what is declared, what is installed, what the lock says
#   scripts/packages.sh install [name]    fetch what is declared and not local, and lock it
#   scripts/packages.sh verify            is what is on disk what the lock says — then each
#                                         package's own controls.py, in the agent container
#   scripts/packages.sh controls [name]   only the controls
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
PY_IN_AGENT=/opt/venv/bin/python   # the agent container's interpreter — named once here (OPERATIONS §80)
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
  docker exec -i "$STACK-agent" $PY_IN_AGENT -c '
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

# A package's controls live with the package (docs/packages.md, "Controls"): packages/<name>/controls.py,
# run in the agent container where the stack's settings and PYTHONPATH are. A package without one is
# noted, not failed — the platform's suite (stack/trial_controls.py) never imports a package to pin
# that package's rules, so a package with no controls.py has nothing pinning them at all.
run_controls() {   # [name] — 0 when every controls.py passed
  local rc=0 any=0
  declared | while read -r name from ref; do
    [ -n "$1" ] && [ "$1" != "$name" ] && continue
    if [ ! -f "$PKGDIR/$name/controls.py" ]; then
      echo "  none     $name — no controls.py (nothing pins this package's own rules)"
      continue
    fi
    echo "== $name: controls"
    # The steps a package's controls drive reach the roots through the stack's settings, so the
    # controls used to write into the instance's real state and workspace (#54, devflow: 821 KB of
    # fixture trees under /work/state). A temporary directory in the agent stands in for the three
    # roots a step writes to, for this one process, and is removed after.
    scratch="/tmp/agentstack-controls-$name-$$"
    docker exec "$STACK-agent" sh -c "mkdir -p '$scratch'" 2>/dev/null || true
    docker exec -e "AGENTSTACK_CONTROLS_ROOT=$scratch" "$STACK-agent" $PY_IN_AGENT "/work/packages/$name/controls.py"; crc=$?
    docker exec "$STACK-agent" sh -c "rm -rf '$scratch'" 2>/dev/null || true
    [ "$crc" = 0 ] || { echo "  FAILED   $name — controls.py reported failures" >&2; exit 1; }
  done || rc=1
  return "$rc"
}

locked_commit() {   # name
  cat "$LOCK" "$LOCAL_LOCK" 2>/dev/null | grep -E "^$1 " | awk '{print $2}' | head -1
}

# `install` used to check out FETCH_HEAD, which leaves the tree detached — and an author who
# develops the package on the instance that runs it (the documented loop) then commits on the
# detached chain: `git push origin main` pushes a stale local main, says "Everything up-to-date",
# and the next install restores the old tree over the new files (#70, trading, measured twice; a
# cutover shipped on old code that way). So a ref that is a branch is checked out AS that branch,
# fast-forwarded to what was fetched, tracking origin; a local branch that holds commits the
# remote does not have is never moved — the install refuses and names both ends. A tag or a
# commit stays detached, and the line says so. Sets WHERE for the caller's line.
checkout_ref() {   # dir ref — 0 and WHERE; 1 with why on stderr, nothing moved
  local dir="$1" ref="$2" want local_tip base name
  name="$(basename "$dir")"
  if git -C "$dir" fetch --quiet origin "+refs/heads/$ref:refs/remotes/origin/$ref" 2>/dev/null; then
    want="$(git -C "$dir" rev-parse "refs/remotes/origin/$ref")"
    if git -C "$dir" show-ref --verify --quiet "refs/heads/$ref"; then
      local_tip="$(git -C "$dir" rev-parse "refs/heads/$ref")"
      if [ "$local_tip" != "$want" ]; then
        base="$(git -C "$dir" merge-base "$local_tip" "$want" 2>/dev/null || true)"
        if [ "$base" != "$local_tip" ]; then
          echo "  REFUSED  $name — the local branch $ref is at ${local_tip:0:8}, origin/$ref at ${want:0:8}:" >&2
          echo "           the branch holds commits the remote does not. Push them" >&2
          echo "           (git -C packages/$name push origin $ref) or drop them" >&2
          echo "           (git -C packages/$name checkout -B $ref origin/$ref); this install moved nothing." >&2
          return 1
        fi
      fi
      git -C "$dir" checkout --quiet "$ref" && git -C "$dir" merge --quiet --ff-only "$want" \
        || { echo "  could not check out $ref" >&2; return 1; }
    else
      git -C "$dir" checkout --quiet -b "$ref" "$want" || { echo "  could not check out $ref" >&2; return 1; }
    fi
    git -C "$dir" branch --quiet --set-upstream-to="origin/$ref" "$ref" 2>/dev/null || true
    WHERE="on branch $ref (tracks origin/$ref)"
    return 0
  fi
  git -C "$dir" fetch --quiet origin "$ref" || { echo "  could not fetch $ref" >&2; return 1; }
  want="$(git -C "$dir" rev-parse FETCH_HEAD)"
  git -C "$dir" checkout --quiet --detach "$want" || { echo "  could not check out $ref" >&2; return 1; }
  WHERE="detached — $ref is a tag or a commit, not a branch"
  return 0
}
where_of() {       # dir — where a fresh clone's tree is
  local b
  b="$(git -C "$1" symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  [ -n "$b" ] && echo "on branch $b" || echo "detached"
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
    run_controls "$ONLY" || fail=1
    exit "$fail";;

  controls)
    run_controls "$ONLY"; exit $?;;

  install)
    fail=0
    declared | while read -r name from ref; do
      [ "$from" = "local" ] && continue
      [ -n "$ONLY" ] && [ "$ONLY" != "$name" ] && continue
      dir="$PKGDIR/$name"
      if [ -d "$dir/.git" ]; then
        echo "== $name: fetching $ref"
        # a refusal (local commits the remote lacks, #70) is this command's failure, out loud
        checkout_ref "$dir" "$ref" || exit 1
      else
        echo "== $name: cloning $from at $ref"
        rm -rf "$dir"
        git clone --quiet --depth 1 --branch "$ref" "$from" "$dir" 2>/dev/null \
          || git clone --quiet "$from" "$dir" \
          || { echo "  could not clone $name" >&2; continue; }
        git -C "$dir" checkout --quiet "$ref" 2>/dev/null || true
        WHERE="$(where_of "$dir")"
      fi
      head="$(git -C "$dir" rev-parse HEAD)"
      write_lock "$name" "$head" "$ref" "$from"
      echo "   at ${head:0:8}, locked — $WHERE"
    done || fail=1
    echo
    [ "$fail" = 0 ] && echo "now: scripts/up.sh   (its principals are created and given credentials there)"
    exit "$fail";;

  *) echo "usage: scripts/packages.sh [list|install|verify|controls] [name]" >&2; exit 2;;
esac
