# 인수 점검 — agent-stack @ c872360 (2026-10-03)

전임 구현자의 인수인계 없이 레포만 보고 인수가 가능한지, 무엇이 빠져 있는지 점검한 기록.
문서 전체(README, CONTRACT, docs/*.md, docs/record/ 요약·§84·§85, DECISIONS)를 읽고, 코드는
세 영역(Python 코어 / 스크립트·Docker·운영 / Node 어댑터·패키지·컨트롤)으로 나눠 점검했다.
아래의 결함은 전부 파일:행을 직접 읽어 확인한 것이다. 레포는 수정하지 않았다.

## 결론

**인수는 가능하다. 레포 자체는 상태가 좋다.** 콜드 스타트 CI가 main에서 녹색(run 87), 정적 검증
13/13, 리뷰 컨트롤 189/189, 어댑터 리플레이 4/4가 이 체크아웃에서 그대로 통과한다. 문서는 양이
많고 대체로 코드와 맞는다. 147개 커밋 중 95개가 Claude 세션이 작성한 것이고, 운영자(astro3141)가
측정 결과를 OPERATIONS.md에 §85까지 남겨 두었기 때문에 "전임자의 머릿속에만 있던 것"은 생각보다
적다.

**빠진 것은 코드가 아니라 전임자의 머신에 있는 것이다.** 아래 "인수받아야 할 것" 목록 없이는
라이브 인스턴스를 이어받을 수 없고, 새로 설치하는 것만 가능하다.

## 1. 전임자 머신에만 있어서 반드시 받아야 할 것

| 항목 | 어디에 | 없으면 |
|---|---|---|
| **라이브 인스턴스** 자체 | Windows 11 + Docker Desktop + Git Bash, `STACK=cadp278` (문서의 `docker exec cadp278-agent`가 그 흔적) | 새로 설치는 가능. 기록된 측정의 재현 환경은 잃는다 |
| `config/instance.env` | git-ignored, 템플릿 파일 없음. 키 목록은 docs/install.md:124-136의 예시뿐 | 다른 포트·이름으로 새 인스턴스 |
| `docker/preloop-owner.env` | Preloop 콘솔 계정의 **유일한** 사본 (up.sh가 생성, 0600) | Preloop 콘솔 로그인 불가. `backup.sh`도 이 파일을 담지 않는다 (아래 2-3) |
| `docker/principals.env`, `operator.env`, `package.env`, `market.env` | 역할 principal·운영자·패키지 자격증명 | principals는 up.sh가 재발급(옛것은 Preloop에 남음); 나머지는 재발급 불가 |
| **백업 키** `~/.agentstack-backup.key` (구 `~/.cadp-backup.key`) 와 아카이브 `~/agentstack-backups/` | 호스트 홈 | 백업을 열 수 없다 (runbook도 그렇게 말한다). §84 기준 최신 백업 `agentstack-backup-20261003-104632` (985 MB) |
| 릴리스 디렉터리 `~/agentstack-releases/` | 호스트 홈 | 롤백 지점 상실. §84가 말한 잘못 라벨된 릴리스 `20261003-112907-7a57911`는 삭제 대상 |
| Preloop DB 볼륨 `preloop-oss_postgres-data` | Docker 볼륨 | 계정·정책·principal·승인 이력 전부 |
| **provider 로그인** (claude/codex/grok) | `/route` 볼륨. 사람 계정 | 재로그인은 사람만 가능. 인수자 본인 계정이어야 함 |
| `/research` 마운트 | `${RESEARCH_HOST_DIR:-../evidence/research}`, 레포에 없음 | `research-r` 패키지 실행 불가 (fixture 없음으로 refuse). `backup.sh`도 이를 필수로 요구 |
| 프라이빗 패키지 레포 3개 | `astro3141/agent-stack-trading`, `-devflow`, `-novel` (계정에 있음, 이 세션 scope 밖) | `trading-b`(cycle.sh·soak.sh 기본값!), `trading-port`, `devflow` 워크플로 없음. `trial_controls.py`의 5개 그룹 skip |
| 외부 문서 | Notion "AI Workflow Design Procedure v0.3" (COVERAGE.md의 기준), CADP 저장소 (CADP-GAP·#19의 기준), `poc/278-composition/` | COVERAGE·CADP-GAP을 다시 측정할 수 없음 |

**Kaspersky 루트 CA.** `docker/ca/kaspersky-root.crt`가 `agent.Dockerfile:22-26,58`로 모든 agent
이미지의 시스템 신뢰 저장소에 들어간다. 이유는 FINDINGS-278 F10: 전임자 Windows의 Kaspersky가
`claude.ai`를 MITM해서 빌드가 실패했기 때문이고, F10 스스로 "일반화 불가, 각주"라고 적었다.
Kaspersky가 없는 호스트(CI 포함)에서는 필요 없고, 개인 PC에 개인키가 있는 "Personal Root"를
governed agent가 신뢰하는 상태다. **제거 대상.**

## 2. 코드 결함 (확인됨, 심각도 순)

### 운영 스크립트

1. **`up.sh --check`는 "아무것도 바꾸지 않는다"가 거짓이다** (runbook:49, verify.sh:19, update-day:20이 그렇게 믿는다).
   `MODE != --check` 가드는 `up.sh:103, 263, 296`뿐이다. check 모드에서도 실행되는 것:
   `principals.py apply`(Preloop 쓰기, :217), 새 자격증명 시 `docker compose up --force-recreate agent broker`(:255, 진행 중 run을 체크포인트 없이 죽임), nginx reload(:287), 그리고 per-role egress 블록(:402-430) — `useradd`, `chgrp/chmod -R /home/agent`, `role_egress.py write`, **`docker restart $STACK-egress`**. 이 블록은 `role_egress.py plan --json`에 `"uid"`가 있으면 돌고, 트래킹된 `config/principals.yaml`의 `egress-probe`가 `egress: [example.com]`을 선언하므로 **항상** 돈다. 즉 `up.sh --check`를 칠 때마다 agent의 유일한 출구인 egress 프록시가 재시작된다.
2. **`backup.sh`는 기본 설치에서 실패한다.** `:192-193` `$STACK-quota-home` 볼륨 필수 — observer 프로파일(#16으로 기본 off)을 켠 적이 있어야 존재. `/research`(:217)와 mlflow(:210)도 필수라 `no-record` 구성도 백업 불가. `--allow-missing`로 만든 아카이브는 `restore.sh:238-240`에서 `set -e`로 죽는다. 그리고 **`docker/*.env`를 전혀 담지 않는다** — install.md가 "secrets"라고 부르는 세 파일 모두.
3. **`release.sh rollback`은 이미지를 되돌리지 않는다.** `:354-357`에서 `rel-<TAG>` → `:local` 재태그 후 `:367` `up.sh --recreate`를 부르는데, up.sh:123은 항상 `docker compose up -d --build`다. 빌드 캐시가 있으면 같은 결과, 캐시가 없으면 `curl | bash` 설치기들이 새 버전을 가져온다. "릴리스 = 리비전 + 이미지 id + 설정"은 캐시가 살아 있을 때만 참. §84의 롤백 통과는 캐시 히트와 일치한다.
4. `cleanup.sh`는 미리보기가 기본(`cleanup.py:17`, `--apply` 필요)인데 runbook:411과 commands.md:29는 "safe한 것을 지운다"고 쓴다. `--apply/--days/--keep` 어느 문서에도 없음.
5. `cycle.py:132`와 `soak.sh:25`의 기본 워크플로가 `trading-b` — 트리에 없다. README:112의 예시도 그것.

### Python 코어

6. **`trajectory.py:125`**: run에 `error`가 있으면 "no such run"처럼 거부한다. 그런데 `runevents.py:116`이 step 실패마다 `error`를 채우므로, **실패한 run일수록 trajectory가 안 나온다** — reading-a-run.md:62가 "step이 실패했을 때 1번"으로 권하는 바로 그 명령이. `suite.py:117`은 그런 run을 집계에서 떨어뜨린다.
7. **`cycle.py:76`**: refusal을 rc 3만 본다. `run_workflow.cmd_start`는 모르는 워크플로·잘못된 id·중복 id에 **rc 2**를 돌려주고(`run_workflow.py:183-200, 265-289`), 그 경우 `soak_outcome`으로 흘러가 `{"state": null}`이 "성공한 cycle"로 `cycles.jsonl`에 기록되고 exit 0. 스케줄러가 이름을 틀리면 영원히 성공으로 보인다. 5번과 결합되면 `scripts/cycle.sh` 무인자 실행이 정확히 이 경로.
8. `run_workflow.py:84-94` `described()`: except 절이 `needs, owner`만 재바인딩. `packages.needs_env()` 이후에 예외가 나면 `logins`/`runbooks` NameError → 패널의 워크플로 탭(`ops/server.py:141`)이 traceback.
9. `broker.py:51` `TOKEN_TTL_S = 3600` vs `long-task.yaml` `timeout_ms: 3600000`: 토큰은 러너 접촉 전에 태어나므로(:147) 1시간짜리 brokered 호출의 마지막 몇 초 MCP 호출은 401. 측정 전, 산술상 확실.
10. `steps/route.py:15`, `steps/admit_models.py:39`: `/work/evidence/p281/` 리터럴. 다른 모든 writer/reader는 `runtime()["paths"]["evidence_root"]`. evidence_root를 옮긴 인스턴스에서 라우팅 증거가 cleanup·record의 시야 밖에 떨어진다.
11. `steps/agent_task.py:98`: `role_egress.assignment()`를 `persist=True`로 불러 모델 step 안에서 `config/generated/role-uids.json`을 쓴다. `plan()`의 docstring이 금지한 바로 그 일. 러너 컨테이너는 `/work` 읽기 전용이라 거기선 예외가 삼켜져 uid 경로를 건너뛴다 — 컨테이너마다 다른 동작.
12. `ops_health.py:91-92` UTC 보정 부호가 반대(`+ time.timezone`; `calendar.timegm` 써야). 컨테이너 TZ가 UTC인 동안만 무해.
13. 작은 것들: `run_workflow.py` `stop`/`tail`은 id 검증 없이 경로 결합(:368,:446; show/resume은 검증함); `principals.py:37`, `elsewhere.py:29` 온보딩 전 `glob()[0]` IndexError; 알 수 없는 서브커맨드가 KeyError traceback(`cfg.py:437`, `run_workflow.py:575`, `principals.py:285`); `tasks.py:111`이 TIMED_OUT을 "denied"로 분류해 기본 retry가 타임아웃을 재시도하지 않음(문서 없음); `admission.py:257` 인자 파싱 wrap; `suite.py:72` id 40자 절단 충돌.

### Node 어댑터 / 패키지

14. **package.json·lockfile이 없다.** npm 의존성은 `agent.Dockerfile:141`의 `npm install -g` 한 줄이 전부. top-level은 핀되지만 transitive는 아니고, `run-agent.mjs:21-22`는 acpx의 **내부** 경로(`dist/runtime.js`, `dist/agent-registry.js`)를 절대경로로 import한다. 재현성 = "이미지 재빌드", 그것도 claude.ai / preloop.ai / nodejs.org / GitHub / npm 네트워크 필요.
15. `run-agent.mjs`는 비이동형: `:27-35` `/work/stack/adapter/*` 절대 import, `:46` `/work/config/generated/runtime.json`. 모듈 로드 실패(runtime.json 없음, acpx 없음)는 계약된 한 줄 `{"status":"FAILED"}`가 아니라 Node 스택 트레이스로 죽는다(`:295-298`의 catch는 `main()`만 감쌈). `agent_task.py:152`는 이를 참아주고, `verify.sh:320`은 "어댑터가 제 모양으로 답하지 않음"으로 분류.
16. **`packages/auto/steps/execute.py:42`가 `run-agent.mjs`를 직접 띄운다** — CONTRACT.md "모든 모델 호출은 `agent_task.py`를 통한다" 위반. produced/stale 스탬프·로그인 재시도·principal을 잃는다(자기 docstring도 인정). 그런데 `verify.sh --level full`이 "routed run의 증명"으로 쓰는 패키지가 이것.
17. `research-r`는 `/research/stack/steps.py`, `/research/stack/gate.py`를 절대경로로 호출(`research-r.yaml:98-187`) — 트리 밖. `requires.host_paths`는 아무도 읽지 않는 키(로더가 note로 알려줌). 새 clone에서 죽은 패키지.
18. provider별 암묵적 가정(설정 불가): `codex.mjs:34-35` `config.toml`의 Authorization을 **작은따옴표** 형태만 정규식으로 읽음; `:26-29` 계정 지문이 ChatGPT JWT `email` claim 가정(API-key 로그인이면 null → 세션 원장이 계정에 안 묶임); `claude.mjs:32` `~/.claude.json`의 preloop 헤더 없으면 TypeError; `grok.mjs` 자격증명은 `grok_posture.py`가 쓴 `config.toml`에 의존. `result.mjs:13` MCP 거부 감지가 `Access denied:` 문자열 매칭.
19. `verify.sh:189`가 `"4/4 recorded runs replayed"` 리터럴을 비교 — fixture를 하나 추가하면 정적 검사가 깨진다.

### 죽은 것 / 정리 대상

- `policy/allow.yaml`, `n1-deny.yaml`, `n2-approval.yaml`, `n7-native-deny.yaml`: 2026-10-02에 제거된 `toolsvc`를 가리키는 #278 fixture. 살아 있는 정책은 `policy/b-fsmcp.yaml` 하나. `cfg.py apply`에 넣으면 없는 서버를 등록한다.
- `compose.poc.yaml:1-9,26-27` 헤더와 `provision` 네트워크: #278 설계 잔재, 어떤 서비스도 안 씀. `install.sh:77`은 그걸 세서 15개 네트워크를 예산한다.
- `verify.sh:240`, `cold-start-linux.yml:55`의 허용 목록 `observation fresh (< 10 min)`: up.sh에 더 이상 없는 체크.
- `steps/fanout.py:3-4` docstring이 없는 파일 `novel_reviews.py`, `trade_lanes.py`를 가리킴. pyflakes: 미사용 import 6건, placeholder 없는 f-string 2건.
- `legacy/tools/keep-awake.ps1`: `D:\Work\poc-278\…` 하드코딩.

## 3. 문서 ↔ 코드 불일치

| 문서가 말하는 것 | 실제 |
|---|---|
| README:101 구성은 `full / no-record / minimal` | `up.sh:53` 은 `full / no-record / runtime` (install.md·commands.md는 맞음) |
| README:84 "arm64는 안 했다, x64 고정" | `agent.Dockerfile:127-156`은 `TARGETARCH`로 파라미터화됨 (install.md가 맞음). README의 "~20GB"도 install.md "~11GB"와 다름 |
| commands.md:77, concepts.md:84 패널이 "run 시작·재개" | #24(2026-10-02)로 패널은 시작·재개 안 함. CONTRACT.md가 맞음 |
| concepts.md:113 `packages/trading` ("셋을 담음") | 트리에 없음 (프라이빗 레포로 이전) |
| concepts.md:118 `stack/steps/`는 route·roles·agent_task·tasks·task_chain·fanout·record뿐 | `admit_models.py`, `broker_dispatch.py`, `step.py`도 있음 |
| packages.md:554 `step.runtime()["broker"]` | `environment.yaml`에 `broker:` 절 없음 → 생성된 runtime.json에서 KeyError. 동작하는 건 `settings.url("broker", …)` |
| packages.md:461 "`egress: [hosts]` 키는 retired" | `config/principals.yaml:33`의 플랫폼 자체 principal이 쓰고, `role_egress.py:51-70`·`agent_task.py:90-139`가 읽어 uid/sudo 경로를 탄다. 산문에서만 은퇴 |
| packages.md:184 `requires.principals`/`host_paths`를 "몇 주 동안 달고 있었다"(과거형) | `novel/manifest.yaml:7`, `research-r/manifest.yaml:8`에 아직 있음 |
| packages.md:266 capability는 `tool_rights, egress, record, admission` | `capabilities.py:287-291`은 `approvals`도 probe. 패키지 저자가 알 수 없음 |
| update-day.md:13 드리프트 리포트 "매주 자동" | `drift.sh`를 돌리는 워크플로 없음. CI의 `verify.sh:222-227`이 note 두 줄을 아티팩트 로그에 남길 뿐 |
| install.md:23 "첫 결핍에서 멈춤" | `install.sh:48-52`는 전부 검사 후 보고. `--check`가 `alpine:3.20`을 pull함(:100) |
| containers.md 표 | `broker`, `agent-probe/closed`, `egress-probe/closed`, 프로파일 게이트 `agent-research`/`egress-research(-review)` 7개 서비스 누락. `replay`는 `ui` 프로파일 전용 |
| commands.md 플래그 | `drift.sh --offline`, `packages.sh controls`, `backup.sh --no-stop --allow-missing`, `restore.sh --stack/--clone-from/--rev/--verify-only/--into-existing`, `release.sh record --tag`, `cycle.sh key=value --retain-*`, `cfg.py validate/apply --force`, `packages.py python/needs/egress/stack/state/logins`, `capabilities.py --json/--missing`, `admission.py <profile>`(실제 라우팅 문) 누락. `scripts/credentials.sh`는 아예 없음 |
| commands.md:70 `router.py`/`collect_obs.py` 단독 실행 | `AGENTSTACK_MODEL_ROUTES`/`AGENTSTACK_LOGINS` 없이 돌리면 grok 건너뜀, claude는 gateway 분기. 진짜 입구는 `admission.py` |
| runbook:122 `evidence/p281/route-<run>/obs/grok.json` | 실제 경로는 `route.py:15`가 만드는 `/work/evidence/p281/route-{run}` — 이 하나는 맞음 |
| `up.sh:25` "인터프리터는 여기서 한 번 이름 짓는다" | `:264,:327,:433,:441`은 bare `python3` (stdlib만 쓰는 동안 동작) |

문서에 없는 **숨은 환경변수** (실행 결과를 바꾸는 것만): `ROUTING_POLICY`(route.py:288, 프로파일의 라우팅 정책 교체), `AGENTSTACK_CHAIN_ENTRY`(tasks.py:90), `POC_PY`(tasks.py:50 등, 자식 step 인터프리터 교체), `MLFLOW_URL`(record.py:48), `ROUTER_NOW`(router.py:111). 그 외 plumbing용 `AGENTSTACK_*` 20여 개는 코어 점검 보고에 파일:행과 함께 있다.

문서에 없는 **매직 파일**: `/route/.quota/<provider>-<login>.json`(보관된 쿼터 읽기, `source: cache:…`의 정체), `/route/codex-session-ledger.jsonl`, `config/generated/role-uids.json`(append-only, 지우면 모든 역할의 uid가 바뀜), `evidence/ui-runs/<id>/keep`(cleanup 보호), `evidence/ops/.cycle.lock.d`(자동으로 안 풀림), admin 컨테이너의 `/tmp/principals-new.env`·`/tmp/preloop-owner.env`(up.sh가 옮기기 전까지 자격증명이 여기 있음).

## 4. 열린 이슈 (11개, PR 0개)

| # | 무엇 | 상태 |
|---|---|---|
| #51–#56 | devflow 저자의 package-feedback 6건 (오늘 14:15 등록): roles.py가 admit_models의 round를 바인딩 못 함(#51), `step.main`이 크래시를 `reason`에만 씀(#52), `requires.state`에 "여기+작업과 함께" 형태 없음(#53), 패키지 컨트롤이 실제 state_root에 씀(#54), `paths`에 handoff/config/egress-profile 루트 없음(#55), 필수 입력 워크플로의 첫 실행 줄 안내 없음(#56) | **triage는 "유지보수자의 것"** — 즉 인수자의 첫 일. 모두 작고 구체적 |
| #50 | trading·devflow를 현재 스택으로 옮기기 (추적) | devflow 완료(36b388d), trading 미완. 모델 호출 경로의 실측은 아직 |
| #48 | `release.sh update`를 타깃 리비전의 스크립트가 수행할지 | 설계 결정 대기 (운영자 몫) |
| #44 | claude OAuth 만료 → 쿼터 stale → claude 역할 run 전부 HOLD, 몇 시간마다 재로그인 | 이틀간 3회 재현. 미결 |
| #19 | CADP effect client | 조건부 (CADP 쪽 대기) |
| #18 | HTTP remote 역학 공통화; 컨트롤의 trading fixture | 스택 쪽 완료, remote는 보류 |

DECISIONS-2026-10-02.md의 표가 #10~#34까지의 처리 상태를 가장 잘 요약한다 (한국어).

## 5. 이 체크아웃에서 직접 돌려 본 것

| | 결과 |
|---|---|
| `scripts/verify.sh --level static` | 13/13, 35 s. `$TMPDIR` 밖에 쓰지 않음 |
| `node --check` 9개 .mjs / `replay.mjs` / `providers_check.mjs` | 모두 OK, 4/4, 20/20 |
| `review_controls.py` / `fanout_controls.py` / `cleanup_controls.py` / `doc_examples.py` / `packages/novel/controls.py` | 189/189, 8/8, 17/17, 10/10, 32/32 (`PYTHONPATH=stack:stack/steps`, `AGENTSTACK_ROOT`를 임시 디렉터리로) |
| `trial_controls.py` (플랫폼 메인 suite, 440개) | **호스트에서 즉사** — `/work` 리터럴 189개, `:1267`에서 FileNotFoundError. 컨테이너 전용 |
| `router_controls.py` | 라이브 관측 디렉터리 필요 |
| `py_compile` 45개, `bash -n` 전 스크립트, shellcheck | 깨끗 (shellcheck는 스타일 노이즈뿐) |
| `grep TODO/FIXME/XXX/HACK stack/` | 0건 |
| CI `cold-start-linux` | run 87 (main, c872360) 성공. 주간 스케줄 일 21:17 UTC |

CI가 **덮지 않는** 운영 경로: backup/restore(2-2가 안 잡힘), release record/update/rollback(2-3), drift 리포트, provider 로그인, `no-record`/`runtime` 구성, observer, 두 번째 인스턴스. 즉 운영 스크립트 쪽 결함은 라이브 인스턴스에서만 드러난다.

## 6. 추천 순서

1. **받을 것부터 받는다** (§1 표). 특히 백업 키·아카이브·`docker/*.env`·instance.env. 못 받으면 "새 설치"로 인수 범위를 명시한다.
2. 인수자 머신에서 `scripts/install.sh --check` → `install.sh` → 패널에서 본인 계정으로 세 provider 로그인 → `verify.sh --level full`. 이 과정이 OPERATIONS §64·§69의 "두 번째 설치" 기록과 같아야 한다.
3. 첫 코드 작업은 #51–#56 triage. 작고 구체적이며 저자가 기다린다.
4. 2-1(`--check`가 egress 재시작), 2-2(backup 기본 실패·secrets 미포함), 2-6(trajectory), 2-7(cycle rc 2)은 운영 사고로 이어지는 것이라 그 다음. 2-3(rollback 재빌드)은 #48과 함께 설계 결정.
5. Kaspersky CA 제거, `trading-b` 기본값 제거, 죽은 policy fixture 정리, README·commands.md·concepts.md 드리프트 수정은 한 PR로.
6. 문서 관례를 지킨다: 변경은 OPERATIONS.md에 §86부터 측정과 함께 기록, 컨트롤 ratchet 유지, 콜드 스타트 녹색 확인 후 머지. 이 레포의 가치는 그 기록에 있다.
