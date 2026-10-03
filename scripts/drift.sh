#!/usr/bin/env bash
# What this stack pins, and what each registry has now. Reports; changes nothing.
#
#   scripts/drift.sh            one line per pinned component: pinned, latest, same|newer|unknown
#   scripts/drift.sh --json     the same, as one JSON object
#   scripts/drift.sh --offline  asks no registry: the pins and the shape, for a control run where
#                               there is no egress (the governed runtime; §75)
#
# Nine external things are pinned here, in five files, and a rebuild that drifted once pulled
# three newer versions at once (docker/agent.Dockerfile, the comment above CLAUDE_CODE_VERSION).
# The pins are read from those files, never repeated here, so this cannot disagree with them.
# A "newer" line is a question for update day (docs/update-day.md), not an action: the provider
# CLIs in particular change what a measured posture relies on, and a newer one is unmeasured.
#
# Runs on the host (npm, curl). A registry that does not answer is not a failure, but it is said:
# a line whose latest is "?" is either `unasked` (there is no registry for it) or `unanswered`
# (asked, with the reason in its last column — HTTP 403, npm's error, a timeout), and the last line
# counts the registries that did not answer. A host with no registry access then reads as such,
# not as "nothing newer" (OPERATIONS §73: every line `unknown`, and no way to tell which).
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
JSON=0; OFFLINE=0
for a in "$@"; do case "$a" in --json) JSON=1;; --offline) OFFLINE=1;; *) echo "drift.sh: unknown argument $a" >&2; exit 2;; esac; done

# pin <file> <grep -E pattern> <prefix glob to strip> [<suffix glob to strip>]
pin() { local v; v="$(grep -oE "$2" "$HERE/$1" | head -1)"; v="${v##$3}"; v="${v%${4:-}}"; printf '%s' "$v"; }

# ---- the pins, read from where they are
CLAUDE_CODE="$(pin docker/agent.Dockerfile 'CLAUDE_CODE_VERSION=[0-9.]+' '*=')"
CONDUCTOR="$(pin docker/agent.Dockerfile 'CONDUCTOR_COMMIT=[0-9a-f]+' '*=')"
PRELOOP_CLI="$(pin docker/agent.Dockerfile 'PRELOOP_CLI_VERSION=[0-9.]+' '*=')"
PRELOOP="$(pin scripts/install.sh 'PRELOOP_VERSION:-[0-9.]+' '*:-')"
CODEXBAR="$(pin docker/agent.Dockerfile 'CODEXBAR_VERSION=[0-9.]+' '*=')"
MLFLOW="$(pin docker/mlflow.Dockerfile 'mlflow==[0-9.]+' '*==')"
DOCKER_CLI="$(pin docker/ops.Dockerfile 'docker:[0-9.]+-cli' 'docker:' '-cli')"
npm_pin() { pin docker/"$2" "$1@[0-9.]+" '*@'; }

# Each ask sets LATEST (the registry's answer, or empty) and WHY (why it is empty, or empty).
# Not subshells: the reason has to come back with the answer.
ERR="$(mktemp)"; trap 'rm -f "$ERR"' EXIT
LATEST=""; WHY=""
ask_npm() {
  WHY=""; LATEST=""
  [ $OFFLINE = 0 ] || { WHY="npm: not asked (--offline)"; return; }
  # one try, and no longer than curl waits: a host with no registry access answers in seconds, not minutes
  LATEST="$(npm view --fetch-retries=0 --fetch-timeout=15000 "$1" version 2>"$ERR" | tail -1)"
  [ -n "$LATEST" ] || WHY="npm: $(grep -m1 -oE 'code E[A-Z0-9_]+' "$ERR" || grep -m1 . "$ERR" | cut -c1-70)"
  [ "$WHY" != "npm: " ] || WHY="npm: no answer"
}
ask_http() {  # <registry host> <url> <python expression over d=json>
  local code; WHY=""; LATEST=""
  [ $OFFLINE = 0 ] || { WHY="$1: not asked (--offline)"; return; }
  code="$(curl -sS --max-time 15 -o "$ERR.body" -w '%{http_code}' -H 'Accept: application/vnd.github+json' "$2" 2>"$ERR")"
  if [ "$code" = 200 ]; then
    LATEST="$(python3 -c "import json,sys; d=json.load(sys.stdin); print($3)" <"$ERR.body" 2>/dev/null)"
    [ -n "$LATEST" ] || WHY="$1: answered, but not in the shape expected"
  elif [ "$code" = 000 ] || [ -z "$code" ]; then
    WHY="$1: $(sed -n '1s/^curl: ([0-9]*) //p' "$ERR" | cut -c1-70)"   # curl's own words, e.g. "Failed to connect to …"
    [ "$WHY" != "$1: " ] || WHY="$1: no answer"
  else
    WHY="$1: HTTP $code"
  fi
  rm -f "$ERR.body"
}
ask_pypi()    { ask_http pypi.org "https://pypi.org/pypi/$1/json" 'd["info"]["version"]'; }
ask_release() { ask_http api.github.com "https://api.github.com/repos/$1/releases/latest" '(d.get("tag_name") or "").lstrip("v")'; }
ask_head()    { ask_http api.github.com "https://api.github.com/repos/$1/commits/$2" 'd["sha"][:12], d["commit"]["committer"]["date"][:10]'; }

ROWS=()
UNANSWERED=()
row() {  # component pinned latest where [why]   — state: same | newer | unasked | unanswered
  local state why="${5:-}"
  if [ -n "$3" ]; then
    if [ "$2" = "$3" ] || [ "${3%% *}" = "${2:0:12}" ]; then state="same"; else state="newer"; fi
  elif [ -n "$why" ]; then
    state="unanswered"; UNANSWERED+=("$why")
  else
    state="unasked"
  fi
  ROWS+=("$1|$2|${3:-?}|$state|$4|$why")
}
asked() { row "$1" "$2" "$LATEST" "$3" "$WHY"; }   # the ask that ran just before this row

ask_npm @anthropic-ai/claude-code;  asked "claude-code"       "$CLAUDE_CODE"      "docker/agent.Dockerfile CLAUDE_CODE_VERSION"
ask_head microsoft/conductor main;  asked "conductor"         "${CONDUCTOR:0:12}" "docker/agent.Dockerfile CONDUCTOR_COMMIT (main's head and date)"
row "preloop-oss"        "$PRELOOP"     ""  "scripts/install.sh PRELOOP_VERSION — no registry to ask; https://preloop.ai"
row "preloop-cli"        "$PRELOOP_CLI" ""  "docker/agent.Dockerfile PRELOOP_CLI_VERSION — no registry to ask"
ask_npm acpx;                                        asked "acpx"             "$(npm_pin acpx agent.Dockerfile)" "docker/agent.Dockerfile"
ask_npm @agentclientprotocol/claude-agent-acp;       asked "claude-agent-acp" "$(npm_pin @agentclientprotocol/claude-agent-acp agent.Dockerfile)" "docker/agent.Dockerfile"
ask_npm @agentclientprotocol/codex-acp;              asked "codex-acp"        "$(npm_pin @agentclientprotocol/codex-acp agent.Dockerfile)" "docker/agent.Dockerfile"
ask_npm @openai/codex;                               asked "codex"            "$(npm_pin @openai/codex agent.Dockerfile)" "docker/agent.Dockerfile"
ask_npm @xai-official/grok;                          asked "grok"             "$(npm_pin @xai-official/grok agent.Dockerfile)" "docker/agent.Dockerfile"
ask_release steipete/CodexBar;                       asked "codexbar"         "$CODEXBAR" "docker/agent.Dockerfile CODEXBAR_VERSION"
ask_npm @modelcontextprotocol/server-filesystem;     asked "server-filesystem" "$(npm_pin @modelcontextprotocol/server-filesystem fsmcp.Dockerfile)" "docker/fsmcp.Dockerfile — a new version means re-reading its tool list into policy/b-fsmcp.yaml"
ask_npm supergateway;                                asked "supergateway"     "$(npm_pin supergateway fsmcp.Dockerfile)" "docker/fsmcp.Dockerfile"
ask_pypi mlflow;                                     asked "mlflow"           "$MLFLOW" "docker/mlflow.Dockerfile"
row "docker-cli"         "$DOCKER_CLI"  ""  "docker/ops.Dockerfile — not checked (Docker Hub tags)"

# one line per registry that did not answer, with the first reason it gave
summary() {
  [ ${#UNANSWERED[@]} -gt 0 ] || { echo "every registry asked answered"; return; }
  printf '%s\n' "${UNANSWERED[@]}" | awk -F': ' '!seen[$1]++ {r[++n]=$0} END {
    printf "%d of %d lines unanswered — %d registr%s did not answer from this host: ", '"${#UNANSWERED[@]}"', '"${#ROWS[@]}"', n, (n==1?"y":"ies");
    for (i=1;i<=n;i++) printf "%s%s", r[i], (i<n?" · ":"\n") }'
}

if [ $JSON = 1 ]; then
  printf '{'
  first=1
  for r in "${ROWS[@]}"; do
    IFS='|' read -r c p l st w why <<<"$r"
    [ $first = 1 ] || printf ','
    first=0
    printf '"%s":{"pinned":"%s","latest":"%s","state":"%s","where":"%s","reason":"%s"}' "$c" "$p" "$l" "$st" "${w//\"/\\\"}" "${why//\"/\\\"}"
  done
  printf '}\n'
else
  printf '%-19s %-14s %-24s %-10s %s\n' component pinned latest state where
  for r in "${ROWS[@]}"; do
    IFS='|' read -r c p l st w why <<<"$r"
    printf '%-19s %-14s %-24s %-10s %s%s\n' "$c" "$p" "$l" "$st" "$w" "${why:+ — $why}"
  done
  echo
  summary
fi
exit 0
