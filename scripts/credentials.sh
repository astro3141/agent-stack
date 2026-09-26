#!/usr/bin/env bash
# Put a declared credential where its package says it lives — on the HOST, never through a screen.
#
#   scripts/credentials.sh              list every declared credential and whether it is present
#   scripts/credentials.sh fill         prompt for each MISSING one and write it to its file
#   scripts/credentials.sh set NAME     (re)enter one credential by name
#
# Why this is a terminal prompt and not a panel field: the panel deliberately shows presence only —
# a panel that accepted a credential would be a control-plane surface holding a secret, the one
# thing this stack takes care not to build (docs/packages.md, OPERATIONS §43). This script is the
# documented path ("a value the operator holds goes in the file") made one command: it prompts with
# echo off, writes the declared git-ignored file at 0600, and never prints, logs or transmits a
# value. What the panel shows afterwards (있음) comes from the same `packages.py needs` answer.
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
STACK="$(sed -n 's/^STACK=//p' "$HERE/config/instance.env" 2>/dev/null | head -1)"
STACK="${STACK:-agentstack}"
CMD="${1:-list}"
ONLY="${2:-}"

needs() {
  # the same single answer the panel reads; the container only reports presence
  docker exec "$STACK-agent" /opt/venv/bin/python /work/stack/packages.py needs
}

case "$CMD" in
  list)
    needs || echo "(no package declares a credential)"
    ;;
  fill|set)
    [ "$CMD" = set ] && [ -z "$ONLY" ] && { echo "usage: scripts/credentials.sh set NAME" >&2; exit 2; }
    updated=0
    # rows: <pkg> <NAME> <MISSING|present> <file> — <purpose>
    while IFS= read -r line; do
      [ -z "$line" ] && continue
      pkg=$(awk '{print $1}' <<<"$line")
      var=$(awk '{print $2}' <<<"$line")
      state=$(awk '{print $3}' <<<"$line")
      file=$(awk '{print $4}' <<<"$line")
      purpose="${line#*— }"
      if [ "$CMD" = fill ] && [ "$state" != "MISSING" ]; then continue; fi
      if [ "$CMD" = set ] && [ "$var" != "$ONLY" ]; then continue; fi
      case "$file" in docker/*) ;; *) echo "  skip $var: undeclared file location '$file'" >&2; continue;; esac
      target="$HERE/$file"
      printf '%s  (%s — %s)\n' "$var" "$pkg" "$purpose"
      # echo off; the value exists only in this shell's memory and the 0600 file
      IFS= read -rs -p "  value (input hidden, empty = skip): " value </dev/tty; echo
      [ -z "$value" ] && { echo "  skipped"; continue; }
      touch "$target"; chmod 600 "$target"
      # replace-or-append without ever echoing the value through argv/ps: write via a temp file
      tmp="$(mktemp "$target.XXXXXX")"; chmod 600 "$tmp"
      grep -v "^${var}=" "$target" > "$tmp" 2>/dev/null || true
      printf '%s=%s\n' "$var" "$value" >> "$tmp"
      mv "$tmp" "$target"
      unset value
      updated=$((updated+1))
      echo "  → $file 에 기록됨 (0600)"
    done < <(needs)
    if [ "$updated" -gt 0 ]; then
      echo
      echo "$updated개 기록. 컨테이너가 읽으려면 재기동이 필요합니다: scripts/up.sh"
    else
      echo "기록한 값 없음."
    fi
    ;;
  *)
    echo "usage: scripts/credentials.sh [list|fill|set NAME]" >&2; exit 2;;
esac
