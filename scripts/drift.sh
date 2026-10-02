#!/usr/bin/env bash
# What this stack pins, and what each registry has now. Reports; changes nothing.
#
#   scripts/drift.sh            one line per pinned component: pinned, latest, same|newer|unknown
#   scripts/drift.sh --json     the same, as one JSON object
#
# Nine external things are pinned here, in five files, and a rebuild that drifted once pulled
# three newer versions at once (docker/agent.Dockerfile, the comment above CLAUDE_CODE_VERSION).
# The pins are read from those files, never repeated here, so this cannot disagree with them.
# A "newer" line is a question for update day (docs/update-day.md), not an action: the provider
# CLIs in particular change what a measured posture relies on, and a newer one is unmeasured.
#
# Runs on the host (npm, curl). A registry that does not answer gives "unknown", not a failure.
set -uo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
JSON=0; [ "${1:-}" = "--json" ] && JSON=1

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

npm_latest() { npm view "$1" version 2>/dev/null | tail -1; }
pypi_latest() { curl -fsS --max-time 15 "https://pypi.org/pypi/$1/json" 2>/dev/null \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["info"]["version"])' 2>/dev/null; }
gh_release() { curl -fsS --max-time 15 -H 'Accept: application/vnd.github+json' \
  "https://api.github.com/repos/$1/releases/latest" 2>/dev/null \
  | python3 -c 'import json,sys; print((json.load(sys.stdin).get("tag_name") or "").lstrip("v"))' 2>/dev/null; }
gh_head() { curl -fsS --max-time 15 -H 'Accept: application/vnd.github+json' \
  "https://api.github.com/repos/$1/commits/$2" 2>/dev/null \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["sha"][:12], d["commit"]["committer"]["date"][:10])' 2>/dev/null; }

ROWS=()
row() {  # component pinned latest where
  local state="unknown"
  if [ -n "$3" ]; then
    if [ "$2" = "$3" ] || [ "${3%% *}" = "${2:0:12}" ]; then state="same"; else state="newer"; fi
  fi
  ROWS+=("$1|$2|${3:-?}|$state|$4")
}

row "claude-code"        "$CLAUDE_CODE" "$(npm_latest @anthropic-ai/claude-code)"            "docker/agent.Dockerfile CLAUDE_CODE_VERSION"
row "conductor"          "${CONDUCTOR:0:12}" "$(gh_head microsoft/conductor main)"            "docker/agent.Dockerfile CONDUCTOR_COMMIT (main's head and date)"
row "preloop-oss"        "$PRELOOP"     ""                                                     "scripts/install.sh PRELOOP_VERSION — no registry to ask; https://preloop.ai"
row "preloop-cli"        "$PRELOOP_CLI" ""                                                     "docker/agent.Dockerfile PRELOOP_CLI_VERSION — no registry to ask"
row "acpx"               "$(npm_pin acpx agent.Dockerfile)" "$(npm_latest acpx)"              "docker/agent.Dockerfile"
row "claude-agent-acp"   "$(npm_pin @agentclientprotocol/claude-agent-acp agent.Dockerfile)" "$(npm_latest @agentclientprotocol/claude-agent-acp)" "docker/agent.Dockerfile"
row "codex-acp"          "$(npm_pin @agentclientprotocol/codex-acp agent.Dockerfile)" "$(npm_latest @agentclientprotocol/codex-acp)" "docker/agent.Dockerfile"
row "codex"              "$(npm_pin @openai/codex agent.Dockerfile)" "$(npm_latest @openai/codex)" "docker/agent.Dockerfile"
row "grok"               "$(npm_pin @xai-official/grok agent.Dockerfile)" "$(npm_latest @xai-official/grok)" "docker/agent.Dockerfile"
row "codexbar"           "$CODEXBAR"    "$(gh_release steipete/CodexBar)"                      "docker/agent.Dockerfile CODEXBAR_VERSION"
row "server-filesystem"  "$(npm_pin @modelcontextprotocol/server-filesystem fsmcp.Dockerfile)" "$(npm_latest @modelcontextprotocol/server-filesystem)" "docker/fsmcp.Dockerfile — a new version means re-reading its tool list into policy/b-fsmcp.yaml"
row "supergateway"       "$(npm_pin supergateway fsmcp.Dockerfile)" "$(npm_latest supergateway)" "docker/fsmcp.Dockerfile"
row "mlflow"             "$MLFLOW"      "$(pypi_latest mlflow)"                                "docker/mlflow.Dockerfile"
row "docker-cli"         "$DOCKER_CLI"  ""                                                     "docker/ops.Dockerfile — not checked (Docker Hub tags)"

if [ $JSON = 1 ]; then
  printf '{'
  first=1
  for r in "${ROWS[@]}"; do
    IFS='|' read -r c p l s w <<<"$r"
    [ $first = 1 ] || printf ','
    first=0
    printf '"%s":{"pinned":"%s","latest":"%s","state":"%s","where":"%s"}' "$c" "$p" "$l" "$s" "${w//\"/\\\"}"
  done
  printf '}\n'
else
  printf '%-19s %-14s %-24s %-8s %s\n' component pinned latest state where
  for r in "${ROWS[@]}"; do
    IFS='|' read -r c p l s w <<<"$r"
    printf '%-19s %-14s %-24s %-8s %s\n' "$c" "$p" "$l" "$s" "$w"
  done
fi
exit 0
