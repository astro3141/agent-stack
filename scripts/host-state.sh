#!/usr/bin/env bash
# Record the parts of this stack's state that live on the host, where no container can see them.
#
#   scripts/host-state.sh        writes evidence/ops/host-state.json
#
# Backups and kept releases are deliberately outside the workspace and outside every container
# (scripts/backup.sh --out, scripts/release.sh; OPERATIONS.md §7–8) — which also means the panel,
# which only ever talks to containers, cannot see them. So the host writes down what it has, with
# the time it looked, and the panel shows that with its age. A number with no age would be worse
# than none: a backup that existed last week is not a backup that exists.
#
# Run by scripts/up.sh --check, and on its own whenever you want the panel to catch up.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
command -v cygpath >/dev/null && HERE="$(cygpath -m "$HERE")"
[ -f "$HERE/config/instance.env" ] && . "$HERE/config/instance.env"
BACKUPS="${BACKUP_DIR:-$HOME/cadp-backups}"
RELEASES="${RELEASE_DIR:-$HOME/cadp-releases}"
OUT="$HERE/evidence/ops/host-state.json"
mkdir -p "$HERE/evidence/ops"

# newest backup: name, size and age. `find` rather than `ls` so a name with spaces survives.
b_count=0; b_name=""; b_mb=""; b_at=""
if [ -d "$BACKUPS" ]; then
  b_count="$(find "$BACKUPS" -maxdepth 1 -type f -name '*.tar*' 2>/dev/null | wc -l | tr -d ' ')"
  newest="$(find "$BACKUPS" -maxdepth 1 -type f -name '*.tar*' -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)"
  if [ -n "$newest" ]; then
    b_name="$(basename "$newest")"
    b_mb="$(du -m "$newest" 2>/dev/null | cut -f1)"
    b_at="$(date -u -r "$newest" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"
  fi
fi

r_tags=""; r_count=0
if [ -d "$RELEASES" ]; then
  for d in "$RELEASES"/*/; do
    [ -d "$d" ] || continue
    r_tags="$r_tags${r_tags:+,}\"$(basename "$d")\""
    r_count=$((r_count + 1))
  done
fi

printf '{"at":"%s","backups":{"dir":"%s","count":%s,"newest":{"name":"%s","size_mb":"%s","at":"%s"}},"releases":{"dir":"%s","count":%s,"tags":[%s]}}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$BACKUPS" "${b_count:-0}" "$b_name" "${b_mb:-}" "$b_at" \
  "$RELEASES" "$r_count" "$r_tags" > "$OUT"
cat "$OUT"
