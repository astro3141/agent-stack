#\g<1>fixture 받음, 모델 없는 절반 분리·재생 4/4(§74); provider 표와 LOGIN/PRINCIPAL은 full 레벨 \2| 컴포넌트 | pinned → latest | 읽은 것 | 위험 | 추천 |
|---|---|---|---|---|
| codexbar | 0.63.0 → 0.70.0 | 0.64~0.70: Claude 읽기 안정화 세 건 — 일시적 타임아웃 뒤 CLI 소스 유지(#4129), "usage insights가 보일 때 실제 쿼터 값을 기다림"(#4115/#4083), 정규 윈도우가 없을 때 모델별 주간 쿼터로 대체(#4126). Grok 빌링 윈도우 구조는 변화 없음(GrokCreditsProxyFetcher·GrokStatusProbe 핀과 head 동일) | 낮음 | **1차에 포함.** §64의 429 사례를 CodexBar 쪽에서도 완화하는 변경이다 |
| claude-code | 2.1.278 → 2.1.287 | 2.1.281~287: 프로젝트 `permissions.deny`(우리가 native tools를 끄는 방법)에 변화 없음. managed settings 추가(`allowedProviders`, `allowManagedPermissionRulesOnly`), headless MCP 재시도, OAuth 만료 메시지 개선 | 낮음 | **1차에 포함**, N7(native write off) 1회 측정 |
| supergateway | 4.0.0 → 4.1.0 | minor | 낮음 | **1차에 포함** |
| codex + codex-acp | 0.155.1 → 0.160.0 / 1.12.0 → 2.1.1 | codex-acp **2.0.0(09-28) breaking: "AIR tool call contract, exact diff patches"**, `_meta.mcpStartupAwaitTimeoutMs` 추가, read-only mode 복원, codex 0.157+ 와 짝. codex 0.160: Guardian review(opt-in), workspace defaults. 둘은 함께 움직여야 한다(1.13.x↔0.155/0.156, 2.x↔0.157+) | **높음** — run-agent.mjs가 tool_call 이벤트의 모양을 읽는다 | **별도 세션.** "ACP 계약 변경" 하나로 묶어 측정 |
| claude-agent-acp | 0.79.0 → 0.85.0 | **0.82.0(09-28) breaking: 같은 "AIR tool call contract"**; 0.81.1 `permissions.disableBypassPermissionsMode` 반영; 0.85 SDK 0.3.286 | **높음** — 위와 같은 이유 | **별도 세션**, codex-acp와 함께 |
| acpx | 0.18.0 → 0.19.4 | sdk 의존 ^1.4 → ^1.5 (ACP v1 라인 유지; 2.0은 Rust crate 얘기). 어댑터는 `acpx/dist/runtime.js`·`agent-registry.js`를 경로로 import | 중간 — 내부 모듈 경로 | **별도 세션**, 위 둘과 함께 |
| conductor | 87f7788(09-18) → 0.1.41(09-29) | +45k줄. 새로 생긴 것: **secret bindings**(`execution.secrets` — 우리 manifest `requires.env`와 같은 문제의 엔진 측 답), **run bundle**(워크플로 closure의 content-addressed 묶음 — 우리 package lock·`requires.stack`과 같은 문제), claude-agent-sdk 과금 출처 표시 | 중간~높음 — 크기 | **보류.** 다만 secret bindings는 `requires.env`를 그쪽으로 옮길 후보라 다음 update day의 안건 |
| grok | 1.0.40 → 1.0.46 | 체인지로그 없음(npm·웹 모두). posture가 config `[permission]` 평가 순서에 의존 | 중간 — 기록 없음 | **보류**, N7 측정 가능한 세션에서 |

**추천: 1차 = codexbar·claude-code·supergateway.** 절차는 docs/update-day.md 그대로(브랜치, 핀
한 개당 커밋, cold-start-linux, 인스턴스에서 `release.sh update` → `verify.sh --level full`,
claude N7). ACP 셋(codex·codex-acp·claude-agent-acp·acpx)은 "tool call 계약이 바뀐" 한 묶음이라
따로 한 세션을 쓰는 게 맞고, 그 세션의 첫 측정은 §50의 grok principal 호출과 §64의 cold 역할이다.

## 결정 3. 매트릭스 후보 4·6·7·8 — 무엇을 스택으로 올리는가

### 후보 8: sub-run·wait·cycle 입력 — **올리지 않는다. 이미 Conductor에 있다**

- 패키지 관점(기록): devflow `drive.py`가 `run_workflow.py start/show`를 셸로 불러 자식 run을 돌리고
  `--suite/--case`를 쓰지 않아 record에서 안 묶인다; trading은 `slots.sh`가 cycle.sh를 세 번 돈다.
  둘 다 "스택에 primitive가 없다"는 전제로 만든 것.
- 같은 부품의 방향: **핀 시점의 Conductor(09-18)에 이미 `type: workflow`(sub-workflow, `for_each`
  팬아웃 포함)와 `type: wait`(폴링은 wait + route loop-back)가 있다.** head도 같다.
- in-tree 제작자 의견: novel·auto·research-r은 sub-run이 없다. 필요해지면 `type: workflow`를 쓰지
  스택 API를 기다리지 않겠다.
- **추천:** 스택 코드 없음. docs/packages.md에 한 절("자식 run은 `type: workflow`, 대기는 `type:
  wait`")과, run_workflow가 `subworkflow_started/completed` 이벤트를 record에 묶는지 **측정 1회**.
  devflow·trading의 이관은 패키지 쪽 일.

### 후보 6: run 밖에 남는 패키지 상태 — **계약 문서만, 헬퍼 없음**

- 패키지 관점(기록): devflow는 GitHub 코멘트(기계용 사본)와 `.devflow-cache`(정리 주인 없음),
  trading은 `handoff/`(입력용 디렉터리를 DB로)와 `/research` 마운트, research-r도 `/research`,
  novel은 workspace 안에 둔다. 네 패키지가 네 가지로 푼다.
- 같은 부품의 방향: Conductor는 run 안의 checkpoint/resume만 다루고 **run 사이 상태는 다루지 않는다**
  (run bundle은 입력 closure, 상태가 아님). 엔진이 답을 주지 않는 자리다.
- in-tree 제작자 의견: research-r이 `/research`에 의존하는 게 §3의 위반 목록에 있다. "어디에 두고
  누가 지우나"만 정해지면 따르겠다. 헬퍼는 필요 없다 — 경로 하나와 규칙 하나면 된다.
- **추천:** docs/packages.md에 계약 한 절: 위치 `<state_root>/<package>/`(settings에 한 줄), 소유자는
  패키지, manifest `requires.state: true`로 선언, `cleanup.py`는 선언 없는 디렉터리를 **보고**만
  하고 삭제는 운영자. 코드는 settings 키 하나와 cleanup의 보고 한 줄.

### 후보 4: artifact binding(frozen input 해시에 결과 묶기) — **지금 안 한다**

- 패키지 관점(기록): novel은 receipt의 `context`=draft sha256으로 묶고 triage가 검증한다(controls
  32개가 고정); trading은 packet을 두 번 만들어 sha 비교; devflow는 tree hash. 셋 다 **동작한다**.
- 같은 부품의 방향: Conductor run bundle은 워크플로 파일 closure의 digest이지 run artifact의 묶음이
  아니다. 엔진 측 답 없음.
- in-tree 제작자 의견: novel 제작자로서 헬퍼가 있으면 쓰겠지만 지금 코드가 틀린 게 아니다. 이득은
  "세 번째 패키지가 같은 걸 또 쓸 때" 생긴다.
- **추천:** 보류. 트리거는 새 패키지가 X2 행을 OWN으로 추가하는 순간.

### 후보 7: HTTP remote 역학 — **패키지에 둔다**

- 해당 패키지는 trading(KIS, DART)과 devflow(GitHub) 둘뿐이고 둘 다 private. in-tree 패키지에는
  remote가 없다. 공통부(proxy-aware opener, transient/permanent 분류, 토큰 캐시)는 각각 ~300줄.
- **추천:** 올리지 않는다. 세 번째 remote 패키지가 생기면 그때 셋에서 뽑는다.

## 결정이 아닌 것 (측정으로 닫힘)

- grok의 raw billing 응답(플랜인지 프록시인지): 런북 "Runs hold"의 명령 한 줄. Windows에서 실행.
- cost-first·long-task 프로파일의 `require_windows`를 research-default와 같은 provider별 형태로:
  이 커밋에서 했다(long-task는 claude만 쓰므로 claude만).

## 조건부 (그대로)

CADP effect client와 CADP-GAP의 큰 갭 1~4는 CADP가 v0.5를 authority로 올리고 policy delta를
정의한 뒤의 일이다. 이 쪽에서 먼저 움직일 것은 없다.

## 추후 과제 (GitHub 이슈, 2026-10-02 등록 — 운영자 건 먼저)

같은 날의 재검토에서 "계약으로 닫음·최소 코드·보류"의 근거를 다시 따진 결과도 반영돼 있다:
기존 패키지는 **수요**의 근거이지 **모양**의 근거가 아니고(결핍이 만든 형태), in-tree 패키지는
스택의 자기 시험이라 제작자 의견으로 치지 않는다. 운영자의 원칙 — 공통은 스택이 구현하고,
특수한 것은 패키지가 구현하되 그 자리는 스택이 마련한다 — 로 후보 4와 7의 판정이 바뀌었다.

| # | 순서 | 내용 |
|---|---|---|
| [#10](https://github.com/astro3141/agent-stack/issues/10) | 운영자 | update day 1 마무리: release.sh update → verify full → claude N7 → §65 기록. 그 전엔 PR #9 머지 안 함 |
| [#11](https://github.com/astro3141/agent-stack/issues/11) | 운영자 | Grok raw billing 응답: 플랜인지 프록시인지 |
| [#12](https://github.com/astro3141/agent-stack/issues/12) | 다음 | CONTRACT에 원칙 한 문단; 후보 4(artifact binding)는 공통 → step.py 헬퍼, context 의미는 패키지 |
| [#13](https://github.com/astro3141/agent-stack/issues/13) | 완료(§66·§71) | 후보 8: 자식 run·wait이 스택의 문을 통과하는지 CI 픽스쳐로 측정; cycle.py 입력 전달 구현 |
| [#14](https://github.com/astro3141/agent-stack/issues/14) | 다음 | 후보 6: 자리가 devflow·trading의 필요에 맞는지(제작자 질문 2개), backup.sh에 state 포함 |
| [#15](https://github.com/astro3141/agent-stack/issues/15) | 다음 | 선언되지 않은 것 셋: grok posture vs native_tools(cfg 검증), keeper 120 s(quota.reuse_s), direct 경로의 observer 문구 |
| [#16](https://github.com/astro3141/agent-stack/issues/16) | 다음 | 구성: toolsvc 제거, probe 둘·quota를 compose profile로, replay 요청 시 |
| [#17](https://github.com/astro3141/agent-stack/issues/17) | 읽음(§72), 핀 브랜치 준비·cold start 측정(§73) — full 레벨 측정은 운영자 | update day 2: ACP 어댑터 묶음(tool-call contract), Conductor 0.1.41, grok 1.0.46 |
| [#18](https://github.com/astro3141/agent-stack/issues/18) | 스택 쪽 완료(§72); HTTP remote 역학은 보류 | 후보 7 HTTP remote 역학(원칙상 공통, 크기로 뒤); 스택 컨트롤의 trading fixture → 스택 소유 |
| [#19](https://github.com/astro3141/agent-stack/issues/19) | 조건부 | CADP effect client와 갭 1~4: CADP policy delta 이후 |
| [#20](https://github.com/astro3141/agent-stack/issues/20) | 운영자 + 문서 | update day 1 대조: backup.sh 건너뜀(사후 실행), update-day.md에 `--replace-toolchain` 누락 |
| [#22](https://github.com/astro3141/agent-stack/issues/22) | 완료(§71) | 실행 사실은 플랫폼이 모은다: receipt가 아니라 evidence에서 기록, step이 시작한 자식 run의 연결(#13의 남은 절반) |
| [#23](https://github.com/astro3141/agent-stack/issues/23) | 완료(§71) | step/요청/결과 계약 버전, docs/packages.md 예제를 static 검사가 실행 |
| [#24](https://github.com/astro3141/agent-stack/issues/24) | **결정: 패널에서 시작 제거** | CONTRACT 화면 규칙 vs 패널: 운영자가 (B)를 택했다 — 시작(precheck/start)·재개·설정 생성·적용은 명령으로, 패널은 상태와 명령을 보여 준다 (§70). 남은 버튼은 사람의 것뿐: 로그인 코드, 승인·거부, 중지, 그래프 보기 |
| [#25](https://github.com/astro3141/agent-stack/issues/25) | 완료(§71, 계약 절) | 자기 런타임을 가져오는 패키지(trading)의 확장 계약 — 스택이 마련할 자리 (#18과 함께) |
| [#26](https://github.com/astro3141/agent-stack/issues/26) | 완료(§71, #24로 재해석) | 새 제작자의 첫 성공 측정: 문서 예제 그대로의 패키지가 로그인 없이 패널에서 시작되는지 |
| [#27](https://github.com/astro3141/agent-stack/issues/27) | 운영자 full 레벨 | run-agent.mjs 분리(공급자 어댑터 / 승인 / 원장 / 결과) — 모델 호출이 있어야 검증되므로 fixture부터 |

#22–#26은 PR #21 머지 전 외부 리뷰를 코드로 검증한 결과(OPERATIONS §67)에서 나온 설계 수준 항목이다. 확인된 결함 일곱은 같은 PR에서 고쳤다.

구조 리뷰(OPERATIONS §68)의 다섯 징후 중 넷은 PR #21에서 정리했고(admission.py, execution.py, runstate.py/runevents.py, 단일 door), run-agent.mjs만 #27로 남겼다.
