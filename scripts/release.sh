#!/usr/bin/env bash
# Releases: keep what is running now, change to something else, and go back to it.
#
#   scripts/release.sh record [--tag NAME]                    keep the running release
#   scripts/release.sh list                                   what is kept
#   scripts/release.sh update --to REV                        record, move to REV, rebuild, check
#   scripts/release.sh rollback --to TAG                      put a kept release back (operator-run)
#
# A release is
#
#   code revision + image ids (kept under a release tag) + configuration.
#
# The toolchain is the image's: every tool is installed under /opt (docker/agent.Dockerfile, #34,
# OPERATIONS §76), so the image ids say what runs. Until §76 claude, Conductor and the Preloop CLI
# lived in the home volume, which masked the image's copy, and a release had to carry the
# toolchain itself and swap it in. A release recorded then still holds that toolchain.tar.gz, and
# a rollback to it restores the archive into the volume: its revision runs nothing without it.
#
# Data is not part of a release: logins, the Preloop database, MLflow and run history stay where
# they are and must survive both directions. scripts/backup.sh covers those. The one exception is
# the Preloop *policy*, which is configuration held in another system: after a change of release
# the restored policy is applied again, so what the account enforces matches what was restored.
set -euo pipefail
export MSYS_NO_PATHCONV=1
# An empty path stays empty: Git Bash's cygpath refuses '' ("can't convert empty path") and under
# set -e that ended restore.sh --verify-only on the first host (§86, measured live).
u() { [ -n "$1" ] || return 0; if command -v cygpath >/dev/null; then cygpath -u "$1"; else printf '%s' "$1"; fi; }
m() { [ -n "$1" ] || return 0; if command -v cygpath >/dev/null; then cygpath -m "$1"; else printf '%s' "$1"; fi; }

HERE="${RELEASE_SH_HOME:-$(cd "$(dirname "$0")/.." && pwd)}"
# An update or a rollback checks out another revision of this very workspace — including this
# script. A shell reads a script as it goes, so replacing the file underneath a running one can
# change behaviour halfway or break it outright. Run from a copy instead.
if [ -z "${RELEASE_SH_PINNED:-}" ]; then
  SELF_COPY="${TMPDIR:-/tmp}/agentstack-release-$$.sh"
  cp "$0" "$SELF_COPY"
  RELEASE_SH_PINNED=1 RELEASE_SH_HOME="$HERE" RELEASE_SH_COPY="$SELF_COPY" \
    exec bash "$SELF_COPY" "$@"
fi
cleanup_all() {
  [ -n "${CAND_DIR:-}" ] && { git -C "$(m "$HERE")" worktree remove --force "$(m "$CAND_DIR")" >/dev/null 2>&1 || true; rm -rf "$CAND_DIR"; }
  # the candidate image exists for one comparison (what the update will change); the image the
  # stack runs is compose's own build. Left in place it accumulated one per update (§84).
  [ -n "${CAND_IMAGE:-}" ] && docker image rm -f "$CAND_IMAGE" >/dev/null 2>&1
  rm -f "${RELEASE_SH_COPY:-}"
}
trap cleanup_all EXIT
[ -f "$HERE/config/instance.env" ] && . "$HERE/config/instance.env"
STACK="${STACK:-agentstack}"
AGENT="$STACK-agent"
PY_IN_AGENT="/opt/venv/bin/python"
RELEASES="${RELEASE_DIR:-$HOME/agentstack-releases}"
RELEASESU="$(u "$RELEASES")"; RELEASES="$(m "$RELEASESU")"
# services of this stack (the agent and the observer share one image)
SERVICES="agent mlflow fsmcp egress ops hub"
# the tools whose versions a release records, all of them the image's
TOOLS="claude conductor preloop_cli codex grok node"

say()  { printf '  %-42s %s\n' "$1" "$2"; }
fail() { echo "release: $*" >&2; exit 1; }

# Whether an unpacked pre-#34 toolchain archive holds the three tools. The archive's bin/ entries
# can be absolute symlinks into /home/agent/.local (claude's installer writes one: bin/claude ->
# /home/agent/.local/share/claude/versions/<v>). Before the swap the archive sits somewhere else,
# so a plain `-e` follows the link to a place that is not there and calls the tool missing — the
# first live rollback to pre-202610 was refused that way, with the file present in the archive
# (OPERATIONS §84). The link is read and its target looked for where the archive is now. Kept as
# a string so the same text runs in the alpine container and in the review control.
TOOLCHAIN_USABLE='
toolchain_usable() {  # $1: the unpacked archive; exit 1 naming the first tool that is not there
  root="$1"
  for t in claude conductor preloop; do
    p="$root/bin/$t"
    if [ -L "$p" ]; then
      tgt="$(readlink "$p")"
      case "$tgt" in
        /home/agent/.local/*) tgt="$root/${tgt#/home/agent/.local/}" ;;
        /*) ;;
        *) tgt="$(dirname "$p")/$tgt" ;;
      esac
    else
      tgt="$p"
    fi
    [ -e "$tgt" ] || { echo "the archive has no $t (bin/$t -> $tgt is not there)" >&2; return 1; }
  done
}'

CMD="${1:-}"; shift || true
TAG=""; TO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="$2"; shift 2;;
    --to) TO="$2"; shift 2;;
    --replace-toolchain) echo "  --replace-toolchain is gone: the toolchain is the image's, and the recreate changes it (#34)"; shift;;
    *) echo "unknown argument: $1" >&2; exit 2;;
  esac
done

git_here() { git -C "$(m "$HERE")" "$@"; }
tool_cmd() {
  case "$1" in
    claude)      echo 'claude --version';;
    conductor)   echo 'conductor --version';;
    preloop_cli) echo 'preloop version';;
    codex)       echo 'codex --version';;
    grok)        echo 'grok --version';;
    node)        echo 'node -v';;
  esac
}
# A tool that cannot answer is information, not a reason to abort: the caller decides.
tool_running()  { docker exec "$AGENT" sh -c "$(tool_cmd "$1")" 2>/dev/null | head -1 | tr -d '\r' || true; }
tool_in_image() { docker run --rm --entrypoint sh "$1" -c "$(tool_cmd "$2")" 2>/dev/null | head -1 | tr -d '\r' || true; }

# Docker Desktop reports a bind source either as the host path or in the VM's own form.
norm_host() {
  case "$1" in
    /run/desktop/mnt/host/?/*|/host_mnt/?/*)
      p="${1#/run/desktop/mnt/host/}"; p="${p#/host_mnt/}"
      d="${p%%/*}"; printf '%s:/%s' "$(printf '%s' "$d" | tr 'a-z' 'A-Z')" "${p#*/}";;
    *) printf '%s' "$1";;
  esac
}
real_of() { (cd "$1" 2>/dev/null && pwd -P) || printf '%s' "$1"; }

require_same_workspace() {
  docker inspect "$AGENT" >/dev/null 2>&1 || fail "no container $AGENT"
  mounted="$(norm_host "$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/work"}}{{.Source}}{{end}}{{end}}' "$AGENT")")"
  [ -n "$mounted" ] || fail "cannot read the workspace mount (/work) of $AGENT"
  # A release describes what RUNS. Reading the revision and the configuration from a different
  # checkout than the mounted one would record a release that never ran — and this project has
  # more than one checkout of the same code.
  [ "$(real_of "$(u "$mounted")")" = "$(real_of "$HERE")" ] || \
    fail "this script is in $HERE but $AGENT runs $mounted — run it from the workspace in use"
}
require_clean_tree() {  # only tracked files matter; run evidence in the workspace is untracked data
  [ -z "$(git_here status --porcelain --untracked-files=no)" ] || \
    fail "the workspace has uncommitted changes to tracked files — commit or stash them first ($1)"
}

# Bring the Preloop policy in line with the configuration now on disk. The apply state lives in
# config/generated/state.json, which is NOT part of a release: it describes the account, not the
# code. Restoring an old copy of it would claim a policy the account does not have.
reapply_policy() {
  echo "== policy"
  # On the admin side: applying a policy is a write the guard refuses from the governed network,
  # which is the point of that guard (OPERATIONS.md §21).
  ADMIN="${ADMIN:-$STACK-admin}"
  docker exec "$AGENT" "$PY_IN_AGENT" /work/stack/cfg.py generate >/dev/null || fail "cfg.py generate failed"
  out="$(docker exec "$ADMIN" "$PY_IN_AGENT" /work/stack/cfg.py apply || true)"
  echo "$out" | grep -o '"preloop-policy[^,]*' | sed 's/^/  /' || true
  if ! echo "$out" | grep -q '"ok": true'; then
    echo "  the policy could not be applied — the account may still enforce the previous one" >&2
    return 1
  fi
  st="$(docker exec "$AGENT" "$PY_IN_AGENT" /work/stack/cfg.py status || true)"
  say "state" "$(echo "$st" | grep -A1 '"preloop-policy' | sed -n 's/.*"state": "\([^"]*\)".*/\1/p' | head -1)"
  return 0
}

# ---------------------------------------------------------------------------- record
cmd_record() {
  require_same_workspace
  require_clean_tree "a release keeps a revision, not a working tree"
  docker start "$AGENT" >/dev/null 2>&1 || true
  for i in $(seq 1 15); do docker exec "$AGENT" true >/dev/null 2>&1 && break; sleep 1; done
  REV="$(git_here rev-parse --short HEAD)"
  [ -n "$TAG" ] || TAG="$(date -u +%Y%m%d-%H%M%S)-$REV"
  DEST="$RELEASESU/$TAG"
  [ -e "$DEST" ] && fail "release $TAG already exists"
  mkdir -p "$DEST"
  echo "== recording release $TAG"
  say "workspace revision" "$REV"
  say "workspace" "$HERE (the one $AGENT runs)"

  : > "$DEST/images.txt"
  for s in $SERVICES; do
    ref="$(docker inspect -f '{{.Config.Image}}' "$STACK-$s" 2>/dev/null || true)"
    [ -n "$ref" ] || continue
    id="$(docker inspect -f '{{.Image}}' "$STACK-$s")"
    keep="${ref%%:*}:rel-$TAG"
    # A running container can reference an image a later rebuild pruned from under it
    # (containerd snapshotter, tag reassigned; measured on the second install, OPERATIONS §65).
    # The daemon's words for that are "No such image"; these are ours, with the way out.
    if ! docker image inspect "$id" >/dev/null 2>&1; then
      rm -rf "$DEST"
      echo "  $STACK-$s runs image $id, which no longer exists — a rebuild pruned it under the running container." >&2
      echo "  scripts/up.sh --recreate puts every container on an image that exists; then record again." >&2
      fail "cannot keep a release whose image is gone — nothing has been changed"
    fi
    docker tag "$id" "$keep"
    echo "$s $ref $id $keep" >> "$DEST/images.txt"
    say "image $s" "$keep"
  done

  # configuration sources only: config/generated is derived, and its state.json describes the
  # Preloop account rather than this code — see reapply_policy()
  tar czf "$DEST/config.tar.gz" --exclude='config/generated' -C "$HERE" config policy docker/.env 2>/dev/null || \
    tar czf "$DEST/config.tar.gz" --exclude='config/generated' -C "$HERE" config policy
  docker run --rm -v "$(m "$DEST"):/in:ro" alpine tar tzf /in/config.tar.gz >/dev/null \
    || fail "the configuration archive did not verify"
  say "configuration" "$(du -h "$DEST/config.tar.gz" | cut -f1) (sources only)"

  {
    echo "tag=$TAG"
    echo "recorded_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "workspace_revision=$REV"
    echo "workspace_dir=$HERE"
    echo "backup_at_update=${BACKUP_NOTE:-}"      # empty for a plain record; what update saw
    echo "stack=$STACK"
    echo "format=3"                  # 2: configuration sources only (no config/generated); 3: no toolchain archive (#34)
    for t in $TOOLS; do echo "tool.$t=$(tool_running "$t")"; done
  } > "$DEST/release.kv"
  for t in $TOOLS; do
    grep -q "^tool\.$t=." "$DEST/release.kv" || fail "could not read the $t version from $AGENT"
    say "$t" "$(sed -n "s/^tool\.$t=//p" "$DEST/release.kv")"
  done
  echo
  echo "kept in $RELEASES/$TAG"
}

# ---------------------------------------------------------------------------- list
cmd_list() {
  [ -d "$RELEASESU" ] || { echo "no releases kept yet ($RELEASES)"; return 0; }
  printf '%-28s %-10s %-22s %s\n' TAG REVISION RECORDED TOOLS
  for d in "$RELEASESU"/*/; do
    [ -f "$d/release.kv" ] || continue
    printf '%-28s %-10s %-22s %s\n' "$(basename "$d")" \
      "$(sed -n 's/^workspace_revision=//p' "$d/release.kv")" \
      "$(sed -n 's/^recorded_at=//p' "$d/release.kv")" \
      "claude $(sed -n 's/^tool.claude=//p' "$d/release.kv" | cut -d' ' -f1), conductor $(sed -n 's/^tool.conductor=//p' "$d/release.kv" | cut -d' ' -f2)"
  done
}

# ---------------------------------------------------------------------------- update
cmd_update() {
  [ -n "$TO" ] || fail "update needs --to REVISION"
  require_same_workspace
  require_clean_tree "an update checks out another revision"
  git_here rev-parse --verify --quiet "$TO" >/dev/null || fail "unknown revision $TO"
  # ---- build a candidate, before the workspace in use is touched -------------------------
  # The target revision is built in a throw-away worktree under its own image tag: a revision that
  # does not build changes nothing here (§66), and what the update will change is read from that
  # image before anything moves. Until this passes, /work and the `:local` tags are as they were.
  echo "== candidate $TO"
  CAND_DIR="$(u "${TMPDIR:-/tmp}")/agentstack-candidate-$$"
  CAND_IMAGE="$STACK/governed-runtime:cand-$(git_here rev-parse --short "$TO")"
  git_here worktree add --quiet --detach "$(m "$CAND_DIR")" "$TO" || fail "could not prepare a candidate worktree"
  # A worktree is the whole repository, and this stack may sit below its root (it does in the
  # repository layout, poc/281-routing/). The candidate's docker/ is therefore under the same
  # prefix as this workspace has inside its own repository.
  PREFIX="$(git_here rev-parse --show-prefix)"
  CAND_DOCKER="$(m "$CAND_DIR")/${PREFIX}docker"
  [ -f "$(u "$CAND_DOCKER")/agent.Dockerfile" ] || fail "the candidate has no ${PREFIX}docker/agent.Dockerfile"
  # a host that needs its own TLS root for the build keeps it untracked (docker/ca/README.md);
  # the worktree is clean, so the candidate gets this workspace's copy
  for _crt in "$HERE"/docker/ca/*.crt; do
    [ -f "$_crt" ] && mkdir -p "$(u "$CAND_DOCKER")/ca" && cp "$_crt" "$(u "$CAND_DOCKER")/ca/"
  done
  docker build --quiet -t "$CAND_IMAGE" -f "$CAND_DOCKER/agent.Dockerfile" "$CAND_DOCKER" >/dev/null \
    || fail "the candidate build failed; nothing was changed"
  say "built" "$CAND_IMAGE"
  for t in $TOOLS; do
    have="$(tool_running "$t")"; want="$(tool_in_image "$CAND_IMAGE" "$t")"
    [ -n "$want" ] || continue
    [ "$have" = "$want" ] && continue
    say "will change $t" "'$have' -> '$want'"
  done

  # The one thing a rollback cannot undo is a Preloop schema migration, and the backup is what
  # covers it (docs/update-day.md). Taking it is a person's decision, so this says, and records,
  # rather than refuses — update day 1 skipped it and took it after (OPERATIONS §65).
  BACKUPS="${BACKUP_DIR:-$HOME/agentstack-backups}"
  last_backup="$(ls -t "$BACKUPS"/agentstack-backup-*.tar.gz.enc 2>/dev/null | head -1 || true)"
  if [ -z "$last_backup" ]; then
    echo "  WARN  no backup under $BACKUPS — a rollback does not undo a Preloop schema migration; scripts/backup.sh first if this update moves Preloop" >&2
    BACKUP_NOTE="none found under $BACKUPS"
  else
    age_d=$(( ( $(date +%s) - $(stat -c %Y "$last_backup" 2>/dev/null || stat -f %m "$last_backup") ) / 86400 ))
    [ "$age_d" -gt 7 ] && echo "  WARN  the newest backup is $age_d days old ($(basename "$last_backup"))" >&2
    BACKUP_NOTE="$(basename "$last_backup") ($age_d days old)"
  fi
  say "backup" "$BACKUP_NOTE"

  echo "== keeping the release in use before changing anything"
  ( TAG=""; cmd_record )
  echo
  echo "== moving the workspace to $TO"
  git_here checkout --quiet "$TO"
  say "now at" "$(git_here rev-parse --short HEAD)"
  echo "== rebuilding images"
  (cd "$HERE/docker" && docker compose -f compose.poc.yaml build) || fail "the build failed; nothing was recreated"

  echo "== starting and checking"
  UP_RC=0
  (cd "$HERE" && bash scripts/up.sh --recreate) || UP_RC=1
  [ "$UP_RC" = 0 ] || {
    echo; echo "the checks did not pass after the update. Go back with:" >&2
    echo "  scripts/release.sh rollback --to <tag>   (scripts/release.sh list)" >&2
    exit 1; }
  # A policy that could not be applied means the account still enforces the previous one: that is
  # a failed update, not a warning.
  reapply_policy || {
    echo; echo "the update left the Preloop policy unapplied. Go back with:" >&2
    echo "  scripts/release.sh rollback --to <tag>   (scripts/release.sh list)" >&2
    exit 1; }
  for t in $TOOLS; do say "$t" "$(tool_running "$t")"; done
  echo
  echo "update done. If it misbehaves, go back with:"
  echo "  scripts/release.sh rollback --to <tag>   (scripts/release.sh list)"
}

# ---------------------------------------------------------------------------- rollback
cmd_rollback() {
  [ -n "$TO" ] || fail "rollback needs --to TAG"
  SRC="$RELEASESU/$TO"
  [ -f "$SRC/release.kv" ] || fail "no release $TO in $RELEASES"
  require_same_workspace
  require_clean_tree "a rollback checks out the release's revision"
  REV="$(sed -n 's/^workspace_revision=//p' "$SRC/release.kv")"
  echo "== rolling back to $TO (workspace $REV)"

  # Everything is verified BEFORE anything changes.
  git_here rev-parse --verify --quiet "$REV" >/dev/null || fail "the release's revision $REV is not in this repository"
  while read -r s ref id keep; do
    docker image inspect "$keep" >/dev/null 2>&1 || fail "kept image $keep is gone — cannot roll back"
  done < "$SRC/images.txt"
  docker run --rm -v "$(m "$SRC"):/in:ro" alpine tar tzf /in/config.tar.gz >/dev/null \
    || fail "the release's configuration archive does not verify — nothing was changed"
  # A release recorded before #34 (format 2) is a revision whose tools lived in the home volume,
  # and its archive is that toolchain. Its kept image has the same tools under /home/agent — but
  # the volume masks /home/agent, and on an instance that followed up.sh's note the volume's copy
  # is gone: restoring the images alone would bring back a revision with no claude, Conductor or
  # Preloop CLI (review 3, OPERATIONS §79; §76 said the opposite, and was wrong). So the archive is
  # restored, verified before the swap, and the swap happens only after everything else verified.
  OLD_TOOLCHAIN=0
  if [ -f "$SRC/toolchain.tar.gz" ]; then
    OLD_TOOLCHAIN=1
    # the unpacked copy is removed again when the check fails: "nothing was changed" must be true
    # of the volume too (the first live attempt left 656 MB of .local.new behind — §84)
    docker run --rm -v "$STACK-agent-home:/vol" -v "$(m "$SRC"):/in:ro" alpine sh -c "
      set -e
      rm -rf /vol/.local.new && mkdir -p /vol/.local.new
      tar xzf /in/toolchain.tar.gz -C /vol/.local.new --strip-components=1
      $TOOLCHAIN_USABLE
      toolchain_usable /vol/.local.new" \
      || { docker run --rm -v "$STACK-agent-home:/vol" alpine rm -rf /vol/.local.new
           fail "the release's toolchain archive does not restore a usable toolchain — nothing was changed"; }
    say "toolchain archive" "from before #34 — unpacked and verified; swapped into /home/agent/.local below"
  fi
  say "verified" "images and the archives"
  docker stop "$AGENT" >/dev/null 2>&1 || true
  if [ "$OLD_TOOLCHAIN" = 1 ]; then
    docker run --rm -v "$STACK-agent-home:/vol" alpine sh -c \
      'rm -rf /vol/.local.old; [ ! -e /vol/.local ] || mv /vol/.local /vol/.local.old; mv /vol/.local.new /vol/.local' \
      || fail "could not swap the release's toolchain into the home volume"
    say "toolchain" "/home/agent/.local from the release (a copy that was there is kept as .local.old until the checks pass)"
  fi

  git_here checkout --quiet "$REV" || fail "cannot check out $REV"
  say "workspace" "$(git_here rev-parse --short HEAD)"
  while read -r s ref id keep; do
    docker tag "$keep" "$ref"
    say "image $s" "$ref ← $keep"
  done < "$SRC/images.txt"
  # Releases recorded by an older version of this script carry config/generated, whose state.json
  # describes the ACCOUNT, not the code. Restoring it would claim a policy the account may not
  # have, and the apply below would then skip as "already applied".
  tar xzf "$SRC/config.tar.gz" -C "$HERE" --exclude='config/generated' --exclude='config/generated/*'
  rm -rf "$HERE/config/generated"
  say "configuration" "config/ and policy/ sources only (generated settings are rebuilt)"

  echo "== starting and checking"
  UP_RC=0
  (cd "$HERE" && bash scripts/up.sh --recreate) || UP_RC=1
  [ "$UP_RC" = 0 ] || { echo "the checks did not pass after the rollback" >&2; exit 1; }
  # the account must enforce the policy that was just restored, not the one from before
  reapply_policy || exit 1
  [ "$OLD_TOOLCHAIN" = 0 ] || docker run --rm -v "$STACK-agent-home:/vol" alpine rm -rf /vol/.local.old
  for t in $TOOLS; do say "$t" "$(tool_running "$t")"; done
  echo
  echo "rolled back to $TO"
  if [ "$OLD_TOOLCHAIN" = 1 ]; then
    # The workspace now holds this release's own scripts/release.sh, from before #34, and that is
    # the script `update` would run next: it looks for the tools in the new image's /home/agent,
    # where they no longer are. Measured on the live instance: it refused once, then moved the
    # workspace and failed, leaving new code on old images (OPERATIONS §84). The way back is the
    # target revision's own script, run against this workspace.
    PREFIX="$(git_here rev-parse --show-prefix)"
    echo
    echo "this release is from before #34, and so is the scripts/release.sh now in the workspace."
    echo "To come back to a current revision, run that revision's own script against this workspace:"
    echo "  git -C '$HERE' show <REV>:${PREFIX}scripts/release.sh > /tmp/release.sh"
    echo "  RELEASE_SH_HOME='$HERE' bash /tmp/release.sh update --to <REV>"
  fi
}

case "$CMD" in
  record)   cmd_record;;
  list)     cmd_list;;
  update)   cmd_update;;
  rollback) cmd_rollback;;
  *) sed -n '2,8p' "$0"; exit 2;;
esac
