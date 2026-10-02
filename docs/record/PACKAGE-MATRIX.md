# Capability × Package 매트릭스 (2026-10-02)

대상: agent-stack @ ae45f85 의 in-tree 패키지 4개(hello-lane, auto, novel, research-r) + 외부 패키지 2개(trading @ 4f1ada8, devflow @ 91300e8)
근거: `PACKAGE-MATRIX-in-tree.md`, `PACKAGE-MATRIX-trading.md`, `PACKAGE-MATRIX-devflow.md` (셀마다 file:line)

셀 값: **U** = 스택 capability를 쓴다 · **O** = 패키지가 직접 구현 · **B** = 둘 다 · **–** = 필요 없음 · **M** = 필요한데 양쪽 다 없음(우회) · **!** = 계약 위반

## 1. 매트릭스

| | hello-lane | auto | novel | research-r | trading | devflow |
|---|---|---|---|---|---|---|
| **C1** Admission (route / admit_models) | – | U | U (admit_models 미사용) | U | B (epoch·lane-i는 route 없음) | U |
| **C2** Role binding (roles.py) | – | – | U | – | U (b/shapes/port만) | **O** (roles.py 안 쓰고 Jinja로 principal 선택) |
| **C3** Execution (agent_task / broker_dispatch) | – | **O!** (run-agent.mjs 직접 호출) | U | U | B (official·epoch·lane-i는 harness가 claude CLI 직접 spawn) | U (broker_dispatch) |
| **C4** Tool rights (principal on call) | – | **M!** (requires 선언, principal 없음) | U | **M!** (requires 선언, principal 없음) | B (3개 워크플로는 principal 없음) | U |
| **C5** Concurrency (tasks / fanout / chain) | – | – | U | – | B (official은 receipt를 직접 조립) | U |
| **C6** Recording (record.py + items) | – | U | U | U! (review 호출 미기록, evidence 없음) | U (epoch·lane-i는 check만) | B! (implementer 호출 미기록) |
| **C7** Operation (cycle/soak/cleanup) | – | – | U (case set이 스택 안에) | – | B (launchd+slots 자체 구현, cycle.sh 호출) | – (drive.py가 자체 cycle) |
| **C8** Composition (manifest requires) | U | U | U (`principals` 키는 아무도 안 읽음) | U (`host_paths` 키는 아무도 안 읽음) | U (`platform_steps` 문서만 남음) | U (`principals` 키 미읽힘) |
| **P1** workspace via settings | **O!** (미정의 env var) | **O!** (`/ws/<run>-<provider>`) | U | U (+ `/research` 2차 트리) | B (`/tmp` fallback) | O (stackenv, fail-closed로 개선) |
| **P2** last-line JSON | U | U | U | U! (`/research` 없으면 traceback) | O (SHAPES로 전 키 채움) | O |
| **P3** REPEATABLE + guard | U | U | U! (stage가 repeat 시 삭제) | U (외부 6 step은 미선언) | B! (epoch·lane-i 미선언) | O (remote에 묻는 guard, marker 없음) |
| **P4** evidence `items` | – | – | U | **M!** | B (3개 워크플로는 0) | O |
| **P5** refuse-not-degrade | U | U | U | ! (`in`/`review` crash) | O (단 `/tmp` fallback) | O |
| **P6** hand-in by name / fixtures | – | – | U | **M!** (절대 호스트 경로) | B (`/` 경로 통과) | U + O |
| **P7** own credentials (env / login / egress) | U (login 예제) | – | – | – (host_paths로 대체) | O (`DART_API_KEY` 미선언, market.env) | U + O (ghauth) |
| **P8** principals in package | U | – | U | – | U | U |
| **X1** step boilerplate (run id, settings, emit) | O | O | O | O | O ×4 | O ×10 |
| **X2** tree snapshot / artifact hash / binding | – | M | B | O | B | O (wstree, cache) |
| **X3** external-effect guard mechanics | – | – | – | – | O (+harness) | O (remote.py: retry taxonomy, lost-answer, fixture fault) |
| **X4** token/credential lifecycle | O (예제) | M | U | U | O ×2 (KIS 캐시 2개, /route/claude 직접 갱신) | O (ghauth refresh+flock) |
| **X5** sub-run from step / shell | – | – | – | – | O (slots.sh, docker exec) | O (drive.py → run_workflow) |
| **X6** controls 소속 | 스택 안 | **M** (아무도 안 돌림) | 스택이 패키지 import (역방향) | **M** | B (패키지 17 + 스택이 패키지 import) | O (controls.py, 스택은 안 돌림) |
| **X7** prompt templating / freezing | – | O (inline f-string) | B | U | O (pins, freeze guard) | O (29 placeholders, frame digest) |
| **X8** waiting on time / calendar / CI | – | – | – | – | O (KRX calendar, launchd, day 해석) | O (CI poll) |
| **X9** cross-run package state | – | – | O (run 내) | O (`/research`) | O (`handoff/`를 DB로) | O (GitHub comment, `.devflow-cache`) |
| **X10** agent-step output schema를 YAML에 복사 | – | O ×2 (+flattening 중복) | O ×4 | O (anchor) | – | – |
| **X11** 플랫폼 레이아웃 직접 참조 | – | – | – | – | O (`/work/p281`, `/route/claude`) | O (egress profile 파일, principals.yaml 직접 읽음) |

## 2. OWN이 2개 패키지 이상인 행 = 스택으로 올릴 후보

| 순위 | 행 | 패키지 수 | 스택에 들어갈 것 | 비용 |
|---|---|---|---|---|
| 1 | X1 step boilerplate | 6/6 | `stack/steps/step.py`: `ws()`, `out()`, `refuse()`, crash→JSON. hello-lane의 P1 위반과 auto의 workspace 모양 이탈이 함께 사라짐 | 작음 |
| 2 | X10 output schema | 3 (auto, novel, research-r) | agent_task 출력 계약을 문서화하고 YAML fragment 하나로. auto의 flattening 중복(execute.py:42-66) 제거 | 작음 |
| 3 | C8 manifest 키 | 6/6 | 안 읽는 키(`principals`, `host_paths`, `platform_steps`)는 읽거나 거부. **스택 버전 하한**(`requires.stack: ">=<rev>"`) 추가 — 지금은 devflow RUNBOOK 산문에만 있음 | 작음 |
| 4 | X2 artifact binding | 4 (novel, research-r, trading, devflow) | "frozen input의 해시에 결과를 묶고 검증" 헬퍼 + 작업 트리 snapshot/diff. receipt에 이미 `context`와 sha256이 있으니 검증 쪽만 공통화 | 중간 |
| 5 | X6 controls 소속 | 6/6 | 규칙 하나: 패키지 controls는 `packages/<p>/controls.py`, `scripts/packages.sh verify`가 돌린다. 스택의 trial_controls가 novel·trading step을 import하는 것은 끊는다 | 중간 |
| 6 | X9 package state | 4 (research-r, trading, devflow, novel) | 계약 하나: run 밖에 남는 패키지 상태는 어디에 두고 누가 지우나. 지금은 `handoff/`(입력용)를 DB로, `/research` 마운트를, `.devflow-cache`를 각자 씀 | 중간 |
| 7 | X3+X4 HTTP remote 역학 | 2 (trading, devflow) | proxy-aware opener, transient/permanent 분류, 토큰 캐시·만료전 갱신·락, fixture fault injection. **remote 의미론은 패키지에 남김** | 중간 |
| 8 | X5+X8 sub-run, wait, cycle 입력 | 2 (trading, devflow) | step에서 run을 띄우고 결과를 읽는 API(`--suite/--case`로 묶이게), poll/wait primitive, `cycle.sh`가 워크플로 입력을 통과시키기 | 중간 |

OWN이 하나뿐이라 **패키지 영역으로 확정**: X7(freezing 의미론), X3의 remote 의미론(GitHub, KIS, 장부), X8의 달력, devflow 판정 기계, trading harness.

## 3. 패키지별 수정 목록 (계약 위반, `!`)

| 패키지 | 고칠 것 |
|---|---|
| hello-lane | write.py의 `AGENTSTACK_WORKSPACE_ROOT` → settings |
| auto | execute.py가 agent_task를 우회(produced 감지·login retry·principal 전부 상실); `tool_rights` 선언만 있고 principal 없음; workspace 모양 이탈 |
| novel | `stage`가 repeat 시 draft·reviews 삭제(guarded가 아님); admit_models를 쓸 자리인데 안 씀 |
| research-r | review 모델 호출이 record에 없음; evidence_file 없음; `/research` 없으면 traceback; fixture가 절대 호스트 경로; `tool_rights` 선언만 |
| trading | epoch·lane-i에 REPEATABLE 없음(스택 control 실패) 및 admission 없음; `DART_API_KEY` 미선언; `/work/p281` 잔존; `_ws_path`의 `/tmp` fallback; official·epoch·lane-i가 execution·tool rights를 우회; handoff를 상태 저장소로 사용 |
| devflow | roles.py 우회(login==provider 가정); implementer·researcher 호출이 record에 없음; push의 lost-answer를 "남이 옮김"으로 오판; `op_key` 쓰고 안 읽음; sub-run이 record에서 안 묶임 |

## 4. 스택 쪽 결함 (매트릭스가 드러낸 것)

- **문(door) 선택이 패키지에 새어 나감.** agent_task.py를 직접 부르면 role의 egress profile 밖에서 돌고, broker_dispatch.py를 불러야 안에서 돈다. devflow.yaml:27-31이 이 사실을 알고 있어야 한다. 스택이 role 선언을 보고 문을 고르면 패키지가 몰라도 된다.
- **스택 controls가 패키지를 import한다.** trial_controls.py가 novel_stage.py와 trade_stage.py를 로드한다. 외부 패키지가 설치되지 않은 머신에서는 스택 controls가 실패한다.
- **cycle.sh가 워크플로 입력을 못 넘긴다.** trading이 `day=`를 step 안에서 해석하는 이유.
- **manifest에 안 읽는 키가 3종 있고 버전 하한이 없다.** 인터페이스가 절대 경로 + argv 순서라서 스택 디렉터리 변경이 패키지를 조용히 깨뜨린다(stackenv.py가 그 사고의 기록).
- **record는 write-only.** 패키지가 run 간 상태를 둘 곳이 없어서 각자 만든다.

## 5. 제안 순서

1. 후보 1·2·3 (step 헬퍼, output schema, manifest 키·버전) — 작고 6개 패키지 전부에 적용. 이걸 하면서 §3의 hello-lane·auto·research-r 위반이 자연히 닫힌다.
2. §4의 door 문제와 controls 소속(후보 5) — 스택 설계 결정 2개.
3. 후보 4·6 (artifact binding, package state) — 계약 문서를 먼저 쓰고 헬퍼는 나중.
4. 후보 7·8 — trading과 devflow 두 패키지에서 공통 부분을 뽑아낼 때.
