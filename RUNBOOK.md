# RUNBOOK — #278 composition stack and #280 research runtime

**State as of 2026-09-21.** This replaces the 2026-09-20 version, which described the stack
*before* Preloop was provisioned and gave an onboarding rule (F6, project-scope hooks) that was
superseded by container isolation (F9). Following the old text would have re-created the F8
incident path. If you are reading an older copy of this file, discard it.

Everything below was measured on the running system on the date above.

---

## 1. What is running

```
Windows 11 host
└─ Docker Desktop 4.91.0 (engine 29.8.0, compose v5.5.1, WSL2 backend `docker-desktop`)
   ├─ Preloop OSS 0.15.0          compose project `preloop-oss`, installed at ~/.preloop-oss
   │    api        :8000  control plane + MCP firewall (/mcp/v1)
   │    gateway    :8001  model gateway (/anthropic, /openai/v1)
   │    console    :3000  web UI + nginx proxy for /api and /mcp
   │    postgres, nats, worker, scheduler, flow-worker
   │    (scheduler and flow-worker ship in the stock compose and are unused; Flow is a #278 non-goal)
   └─ PoC project `cadp278`       compose file D:/Work/poc-278/docker/compose.poc.yaml
        cadp278-agent    governed runtime: Conductor + Claude Code + Preloop CLI + /opt/venv
        cadp278-mlflow   MLflow 3.16.1
        cadp278-toolsvc  disposable MCP tool service (write_marker / list_markers)
```

### Versions (measured 2026-09-21)

| Component | Version | Where |
|---|---|---|
| Conductor | v0.1.37 (`main @ 87f7788e`) | agent container |
| Claude Code | 2.1.278 | agent container |
| Preloop CLI | 0.15.0 | agent container and host `C:\Users\astro\.local\bin` |
| Preloop server | 0.15.0 (`ghcr.io/preloop/preloop:0.15.0`) | preloop-oss compose |
| MLflow | 3.16.1 | cadp278-mlflow |
| SymPy | 1.14.0 | agent container `/opt/venv` |
| node | **not installed** | — |
| codex | **not installed** | — |

### Image IDs

| Image | ID (short) |
|---|---|
| cadp278/governed-runtime:local | `0da188833195` |
| cadp278/mlflow:3.16.1 | `57a342f2b725` |
| cadp278/toolsvc:local | `38b87dca3845` |
| ghcr.io/preloop/preloop:0.15.0 | `82728945c4b6` |

### Networks — this is the isolation, check it before trusting any result

| Container | Networks |
|---|---|
| cadp278-agent | `cadp278-governed` **only** — internal, no default route, no egress |
| cadp278-mlflow | `cadp278-governed`, `cadp278-observe` (inbound-only path for the host browser) |
| cadp278-toolsvc | `cadp278-toolnet` only — the agent cannot reach it directly |
| preloop api | `cadp278-governed`, `cadp278-toolnet`, `preloop-oss_default` |
| preloop gateway, console | `cadp278-governed`, `preloop-oss_default` |

The Preloop containers are attached to the PoC networks **out of band**, with aliases, and the
attachment does not survive a container restart. See §3.

### Volumes

| Volume | Holds | Losing it means |
|---|---|---|
| `cadp278-agent-home` | the agent's own Claude login, Preloop CLI login, onboarding state | re-login inside the container, re-onboard |
| `preloop-oss_postgres-data` | Preloop account, policies, approval history, usage rows | re-bootstrap Preloop from scratch |

### Workspaces

| Path | Purpose | Mounted in the agent as |
|---|---|---|
| `D:/Work/poc-278` | #278 PoC: workflows, Gate, policies, evidence | `/work` |
| `D:/Work/research-280` | #280 research: checkers, stack, artifacts, reports | `/research` |

---

## 2. Rules that exist because something went wrong

| Rule | Why (finding) |
|---|---|
| **Never run `preloop agents onboard` or `preloop agents discover` on the host.** | F8 — onboarding took custody of the host's rotating subscription token and logged the host's daily Claude out repeatedly. |
| Never run `preloop agents discover` without `--json` or `--no-onboard-prompt` anywhere. | F8 — in a non-TTY shell its prompts default to Y and it onboards. |
| Never mount the host's `~/.claude` into any container. | F9/F12 — the container must hold its own credential lineage. |
| Onboard **only inside the agent container**, and pin a model in its `~/.claude/settings.json` first. | F11 — without a model pin, credential resolution silently fails. |
| Remove `CLAUDE_CODE_SIMPLE` from the container's settings env after onboarding. | F22 — onboarding writes `CLAUDE_CODE_SIMPLE=1`, which skips the very hook it installs. It is currently **removed**. |
| Do not treat a hook invocation as governance. | F22 — with hooks running, the hook still returned local `allow` and never contacted Preloop. |
| Do not put a venv or any baked tool under `$HOME` in the image. | #280 — `$HOME` is a volume; image changes under it silently do not apply. Tools live in `/opt/venv`. |
| Do not use Preloop usage or spend figures as a budget. | F25 — no budget API in 0.15.0, subscription spend recorded as $0, successful agent calls produce no usage row. |
| Approve Preloop requests over HTTP, not the CLI. | F20 — `preloop approvals approve` posts an empty body and is rejected 422. |

---

## 3. Bringing it back up

### After a host reboot

```powershell
# Docker Desktop must be running; the engine takes ~30s
Start-Process 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
docker version
```

Both compose projects restart on their own. What does **not** come back:

```bash
# Re-attach Preloop to the PoC networks, with the aliases the agent resolves.
docker network connect --alias api     cadp278-governed preloop-oss-api-1
docker network connect --alias console cadp278-governed preloop-oss-console-1
docker network connect --alias gateway cadp278-governed preloop-oss-gateway-1
docker network connect --alias api     cadp278-toolnet  preloop-oss-api-1
```

Without the aliases the agent cannot resolve `console`, `api` or `gateway` and every governed
call fails. `docker network connect` on an already-attached container errors harmlessly.

### Rebuilding the agent image

```bash
cd D:/Work/poc-278/docker
POC_HOST_DIR=D:/Work/poc-278 RESEARCH_HOST_DIR=D:/Work/research-280 \
  docker compose -f compose.poc.yaml up -d --build agent
# then re-run the network-connect lines above for `api` on cadp278-governed
```

The `cadp278-agent-home` volume survives a rebuild, so the container's login and onboarding
are kept. Anything that must change with the image goes in `/opt`, not `$HOME`.

### Verify the isolation before running anything

```bash
docker exec cadp278-agent sh -c 'ip route'                       # must show NO default route
docker exec cadp278-agent sh -c 'curl -s -o /dev/null -w "%{http_code}" --max-time 5 https://pypi.org; echo " exit=$?"'
#   expected: 000 exit=6   (cannot resolve — no egress)
docker exec cadp278-agent sh -c 'curl -s -o /dev/null -w "%{http_code}\n" http://console/mcp/v1'
#   expected: 401          (reachable, auth required)
```

### Temporary egress (provisioning only)

A login or a package install inside the agent needs the internet. Attach, do the one thing,
detach, and re-verify:

```bash
docker network connect    cadp278-provision cadp278-agent
# ... one provisioning action ...
docker network disconnect cadp278-provision cadp278-agent
docker exec cadp278-agent sh -c 'ip route'                       # default route must be gone again
```

If `cadp278-provision` does not exist: `docker network create cadp278-provision`.

---

## 4. Running things

Every run needs the MCP bearer taken from the container's own config, never written to a file:

```bash
docker exec cadp278-agent sh -c '
export PRELOOP_MCP_TOKEN=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser(\"~/.claude.json\")))[\"mcpServers\"][\"preloop\"][\"headers\"][\"Authorization\"].split()[-1])")
cd /work && conductor run workflows/slice.yaml'
```

OTLP to MLflow is set in the compose environment (`http://mlflow:5000`, `http/protobuf`,
experiment `1`). MLflow UI from the host: <http://127.0.0.1:5000>.

| Workflow | Path in container | What it is |
|---|---|---|
| #278 vertical slice | `/work/workflows/slice.yaml` | Research → Implement → Test → attest → Review → governance → verify → Gate → preserve |
| #280 Phase R smoke | `/research/stack/phase-r-smoke.yaml` | propose → normalize → manifest → verify ×2 → review → input-verify → Gate → preserve |
| probes | `/work/workflows/probes/*.yaml` | one per control |

Policies are applied from inside the container: `preloop policy apply /work/policy/<file>.yaml`.
The baseline is `policy/allow.yaml`; `n1-deny.yaml` and `n2-approval.yaml` are controls and
must be reverted afterwards.

The fixture under `/work/fixture` is a git repository with a committed baseline; reset it with
`git -C /work/fixture checkout -- .` (before 2026-09-20 there was no commit and this silently
did nothing).

---

## 5. What has been measured, and where

### #278 negative controls

| Control | Status | Where |
|---|---|---|
| N1 Preloop deny | **CONFIRMED** — underlying effect prevented | F14, F17, `evidence/n1-deny-evidence.txt` |
| N2 approval path | **CONFIRMED** — resumes in the same run | F20 |
| N3 missing evidence | **CONFIRMED** live | F17 |
| N4 failed test | **CONFIRMED** live | F17 |
| N5 MLflow unavailable | **CONFIRMED** — same PASS, loss reported | F17 |
| N6 Preloop unavailable | **CONFIRMED**, strong form — bypass available and not taken | F18 |
| N7 bypass inventory | **CLOSED** — native tools not governed in the measured configuration | F19 → corrected by F22 |
| N8 direct MCP over HTTP | **CONFIRMED** — static rejection | F2 |
| G1–G5 Gate binding | three gaps found and closed; run scope already sound | F23 |
| restart recovery | works once preserved; per-item re-derivability differs | F24 |
| spend control | **not demonstrable** on this build | F25 |

### #280

| Item | Status | Where |
|---|---|---|
| Gate A source extraction | done — the paper states the level set, not the invariant | `research-280/research/research-pack.md` |
| M1–M6 | all pass, two independent engines | `research-280/reports/baseline-receipt.md` |
| Gate C SDK turn cap | enforced, measured | `research-280/reports/comment-280.md` |
| Phase R on the stack | ADMIT, candidate hash identical to baseline | `research-280/reports/stacked-vs-direct.md` |
| W1 / W9 / W12 | pass | same |
| Phase E grid | 24/24 cells agree across two engines | `research-280/reports/phase-e-findings.md` |

Public record: #278 (receipt, corrections, findings log F1–F25), #279 (CADP TD re-measurement),
#280 (execution results).

---

## 6. Known open items

- Attempt identity is implicit — binding is by artifact digest, so an identical retry is
  indistinguishable from the previous attempt.
- `review.verdict` carries no artifact binding.
- Preloop tool-policy decisions are enforced but exist only in the api container's log.
- Successful agent model calls produce no Preloop usage row.
- Neither workspace is under version control, so "revision" cannot currently be recorded for
  workflows, the Gate or policies. (Addressed at the start of #281 — see §7 when written.)
- The Conductor `claude-agent-sdk` provider offers only two tool configurations; a
  "tools present, not bypass" posture is not expressible.
