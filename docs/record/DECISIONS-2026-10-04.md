# 결정이 필요한 것 — 2026-10-04 (인수 후 첫 주)

인수 점검(§86)과 패키지 저자들의 피드백(§87, §88)을 처리하고 남은 것 중, 코드를 읽어서는
답이 안 나오고 운영자가 정해야 하는 것. 각 항목은 질문 · 사실 · 선택지와 비용 · 추천 · 무엇이
판가름하는가 순이다. 사실은 전부 코드나 기록(§)에서 읽은 것이고, 추측은 그렇게 표시했다.

## 결정 1. #62 — trading harness를 단일 문(`agent_task.py`)에 올릴 것인가, 올린다면 문을 어떻게 넓힐 것인가

**질문.** CONTRACT.md는 "모든 모델 호출은 `agent_task.py`를 통한다"고 한다. trading의 harness는
아직 vendor CLI를 직접 부른다(`claude -p --json-schema`, stdin payload). trading 저자가 문을
측정해 보니 세 가지가 없어서 못 옮긴다고 한다. 문을 넓힐 것인가, 어느 방향으로.

**사실.**
- 문은 모든 provider를 **ACP**(acpx → claude-agent-acp / codex-acp / grok)로 돌린다. CLI의
  `-p --output-format json`이 아니다. 그래서 CLI envelope(`modelUsage`, `num_turns`,
  `server_tool_use`, `permission_denials`, `structured_output`)는 **애초에 생성되지 않는다**.
- ACP 경로가 호출마다 남기는 것(`stack/fixtures/run-agent/claude-auto`, 실측 2026-10-03):
  `events.jsonl`(원시 ACP 이벤트: status/tool_call/text_delta), `result.json`(`turn._meta.quota`에
  모델별 토큰: `model_usage[].model`, `token_count`; `status_raw`; `usage_events`),
  `permissions.jsonl`(모든 permission 요청과 Preloop의 답), `execution.json`(플랫폼 기록).
  즉 **model pin과 토큰은 있고**(`model_usage`), **permission denial도 있고**, `num_turns`와
  `structured_output`은 **없다**.
- trading의 freeze guard(segment registration, "pins contract 64 E6")는 그 envelope 필드를
  읽는다. 옮기면 재인증(re-qualification)이 필요하다 — 저자의 말.
- 세 요구 중 (1) stdin payload는 `agent_task.py`에 작은 변경(요청에 `payload` 필드 또는 `-`),
  어댑터 무관. (2) raw envelope는 "ACP 이벤트"로는 이미 있고 CLI envelope로는 불가능. (3)
  per-call schema는 ACP에 자리가 없다.
- trading은 **private 패키지**이고 이 스택의 in-tree 패키지 중 schema-pinned harness는 없다.
  §72·DECISIONS-10-02 후보 7과 같은 구도: 요구는 하나의 패키지에서 온다.

**선택지.**

| | 무엇 | 비용 | 얻는 것 | 잃는 것 |
|---|---|---|---|---|
| A | 아무것도 안 함. trading은 직접 호출을 유지(현재 상태, #62가 그 기록) | 0 | — | CONTRACT 위반이 한 패키지에 계속 남음. `/route`를 패키지가 쓰는 우회(trading#2)도 남음 |
| B | 문에 (1) stdin/inline payload + (3b) **step이 선언한 schema로 produced 파일을 사후 검증**해 불일치를 거절. envelope는 ACP 것으로 | 작음~중간: `agent_task.py` 수십 줄, 컨트롤, 문서. 어댑터 무변경 | 문 하나 유지(§55의 결과). schema pin이 플랫폼 보증이 됨 | trading은 freeze를 ACP envelope 기준으로 **재인증**해야 함(패키지의 일, 비용 미상) |
| C | 어댑터에 **두 번째 경로**: vendor CLI `-p --output-format json --json-schema`를 Preloop hook·egress 안에서 provider module로 추가 | 큼: 두 번째 실행 경로의 거버넌스 측정 전부(native tool 차단 N7, 승인 경로, 증거 모양, replay fixture) 다시 | trading이 freeze한 envelope 그대로 | 문이 둘이 됨. 리뷰 3·§55가 하나로 모은 것을 되돌림. 매 update day에 두 경로 측정 |

**추천: B.** 단, 순서는 trading 저자에게 "ACP envelope + 선언 schema로 재인증 가능한가"를
먼저 묻고(그게 안 되면 B도 소용없다), 가능하다는 답이 오면 B를 만든다. C는 하지 않는다 — 문을
하나로 만드는 데 든 비용(§51–§55)을 생각하면, 한 패키지의 freeze 형식을 위해 두 번째 문을 여는
것은 CONTRACT 2절("공통은 스택이, 특수한 것은 패키지가, 자리는 스택이 마련")의 "자리"가 아니라
"구현"을 스택이 떠안는 쪽이다.

**판가름하는 것.** trading 저자의 답 하나: freeze guard가 읽는 다섯 필드 중 `num_turns`와
`structured_output` 없이 재인증이 되는가. 된다 → B. 안 된다 → A를 유지하고 #62를 "문의 한계"로
기록, trading의 직접 호출을 계약의 **명시된 예외**로 적는다(지금은 암묵적 위반).

## 결정 2. #44 — claude 토큰을 자동으로 갱신할 것인가

**질문.** claude OAuth 토큰이 몇 시간마다 만료되고, 그때마다 사람이 패널에서 다시 로그인해야
claude 역할이 있는 run이 돈다. 스택이 토큰을 자동 갱신하게 할 것인가.

**사실.**
- 이제 스택은 **원인을 제대로 말한다**(§88): 라우터가 `unknown: the login's token expired … sign in
  on the panel`, 패널에 `토큰 만료`, `up.sh --check` 실패, standing risk에 remedy. 그리고 trading
  실측의 변종(만료가 아니라 **org-disable**)도 실행 레이어의 거절 문장이 관측으로 되먹여진다.
  즉 "뭐가 문제인지 모르는" 상태는 끝났고, 남은 건 "사람이 몇 시간마다 로그인하는" 비용이다.
- 갱신 방법 셋(§88): (a) 스택이 vendor의 토큰 엔드포인트를 직접 호출 — CLI 흐름 재구현, 로그인
  저장소에 쓰기, vendor 변경에 취약. (b) 예약된 `claude` 호출 — 일 없는 모델 호출, 단일 문 밖.
  (c) CodexBar `--source cli` — CLI를 띄워 갱신할 **수도** 있음, 미측정.
- trading 실측이 보여준 것: 10-02 09:41 이후 이 계정은 **조직 설정으로 차단**됐다. 그 경우
  자동 갱신은 아무 소용이 없다. 지금 라이브의 claude hold는 만료가 아니라 이것일 가능성이 높다
  (추측: 두 실측이 같은 credential이라면).
- 역할이 claude 하나에 고정된 워크플로(novel-a)는 `author=claude|codex:novel-author`로 vendor
  순서를 적을 수 있게 됐다(§88). 그러면 claude가 죽어도 run은 간다. 이건 novel의 판단.

**선택지.**

| | 무엇 | 비용 | 위험 |
|---|---|---|---|
| A | 자동 갱신 없음. 지금의 "제대로 말하기" + 워크플로의 vendor 순서로 운영 | 0 | 사람이 로그인하는 빈도는 그대로 |
| B | (c)를 측정해서 되면 수집기가 `login_expired`일 때 `--source cli`로 fallback | 측정 1회 + 수집기 몇 줄 | CodexBar가 CLI를 띄우는 비용/부작용 미상 |
| C | (a) 직접 갱신 구현 | 중간. vendor 엔드포인트·client id 의존 | 취약, 로그인 저장소 쓰기(§50의 금지선을 플랫폼이 넘음) |

**추천: A + B의 측정.** 먼저 지금 라이브의 hold가 만료인지 org-disable인지 확인한다(아래 명령
둘). org-disable이면 갱신은 논점이 아니고 **계정/조직 설정이 문제**다. 만료라면 (c)를 한 번
재 보고, 되면 B. C는 하지 않는다.

**판가름하는 명령(라이브, claude가 hold일 때).**
```
# 1. 지금 왜 안 되는가 — 실행 레이어의 문장
docker exec cadp278-agent sh -c 'CLAUDE_CONFIG_DIR=/route/claude HTTPS_PROXY=http://egress:8888 claude -p "say ok" --max-turns 1' ; echo rc=$?
# 2. CodexBar의 cli 소스가 토큰을 갱신하는가
docker exec cadp278-agent sh -c 'ls -l /route/claude/.credentials.json; CLAUDE_CONFIG_DIR=/route/claude HTTPS_PROXY=http://egress:8888 codexbar usage --provider claude --source cli --json | head -c 400; ls -l /route/claude/.credentials.json'
```
1에서 "organization has disabled"가 나오면 갱신은 무관하다. 2에서 mtime이 바뀌고 usage가 오면 B.

## 결정 3. #48 — `release.sh update`를 누구의 스크립트가 수행하는가

**질문.** 지금은 **워크스페이스에 있는(옛) 리비전의** `release.sh`가 업데이트를 수행한다.
§84에서 pre-#34로 롤백한 뒤 돌아올 때 옛 스크립트가 새 레이아웃(`/opt`)을 몰라 "new code on old
images" 상태를 만들고 잘못 라벨된 릴리스를 기록했다. 타깃 리비전의 스크립트가 수행하게 바꿀
것인가.

**사실.**
- `release.sh:30-38`: 시작 시 자신을 `/tmp`로 복사해 그 복사본으로 실행한다(체크아웃 중 파일이
  바뀌어도 안전). 그 결과 update는 항상 **옛** 스크립트의 로직으로 돈다.
- #46/§84의 완화: pre-#34 롤백이 끝날 때 "돌아오는 법"(타깃의 스크립트를 `git show`로 꺼내
  `RELEASE_SH_HOME`으로 실행)을 출력. 이미 배포된 옛 스크립트는 못 고치므로 이게 한계.
- 일반화: 레이아웃이 바뀌는 **모든** 미래 변경에서 같은 실패가 재현된다.
- 대안: `update --to X`가 X의 `scripts/release.sh`를 꺼내 그 복사본에 이관. 현재 스크립트는
  후보 이미지 빌드와 "현재 릴리스 기록"(롤백 지점)까지만 하고 넘긴다. 수십 줄.
- 트레이드: 지금은 "검증된 현재 스크립트가 모르는 리비전을 설치", 바꾸면 "모르는 리비전의
  스크립트가 현재 인스턴스를 만짐". 어느 쪽이든 콜드 스타트와 릴리스 기록이 안전망. 설치기는
  보통 "새 것이 설치한다".
- 콜드 스타트에는 update 경로가 없다. 측정은 라이브 update 1회.

**추천: 바꾼다**(타깃의 스크립트가 수행). 단 현재 스크립트가 (1) 후보 빌드, (2) 릴리스 기록을
마친 뒤에 넘기고, 타깃 스크립트에 `RELEASE_SH_HOME`과 "이미 기록됨" 표시를 넘겨 중복 기록을
막는다. 이유: 레이아웃 변경은 또 온다(§34 같은 것). 옛 스크립트는 미래를 모른다.

**판가름하는 것.** 이건 측정으로 안 정해진다. 신뢰 모델의 선택이다. 다음 update day에 라이브
update 1회가 측정.

## 결정 4. 예/아니오로 끝나는 것

| # | 질문 | 추천 |
|---|---|---|
| 4-1 | PR #60(#44) 머지 | 예. CI 녹색(run 93, 1caa81f는 진행 중). 라이브 측정은 다음 만료/거절 때 |
| 4-2 | #51~#56 닫기 | 예. 양쪽(스택 §87, devflow 0411f57) 확인 완료 |
| 4-3 | novel-a에 `author=claude\|codex:novel-author` 적용 | **novel의 판단**. claude가 죽었을 때 codex가 쓴 초고를 같은 리뷰 기준으로 볼 것인가. 적용하면 run은 가고, 안 하면 hold. TRIAL-A의 측정은 claude author 기준이었다 |
| 4-4 | #61, #62 — trading 피드백 중 #61 닫기 | 예(문서 반영됨). #62는 결정 1 |
| 4-5 | 라이브 잡무 | 잘못 라벨된 릴리스 `20261003-112907-7a57911` 삭제(§84); 볼륨의 옛 툴체인 `/home/agent/.local` 656 MB 제거(스택 내린 뒤, `up.sh`가 매번 알려줌); `docker/preloop-owner.env`에 콘솔 계정 적기(다음 백업부터 멤버); `--observer` 안 쓰면 그대로 |

## 결정이 아닌 것(이미 정해졌거나, 기다리는 것)

- #18 HTTP remote 역학: 세 번째 remote 패키지가 생기면. 지금은 둘(trading, devflow).
- #19 CADP effect client: CADP 쪽 조건 대기.
- update day 2 잔여(DECISIONS-10-02 결정 2의 ACP 셋): 이미 핀 올라감(claude-agent-acp 0.85.1,
  codex-acp 2.1.1, acpx 0.19.4 — fixture README). 다음 update day는 `drift.sh`가 말한다.

## 이번 주에 바뀐 것(참고)

§86 인수 점검 수정 10건, §86 라이브 측정 3건, §87 devflow 피드백 6건, §88 #44와 trading 변종,
#61. 머지: PR #57, #58, #59. 열림: PR #60. 콜드 스타트 run 88·91·93 녹색.

---

## 결정 1의 근거 자료 — 세 provider와 ACP의 구조화 출력 (2026-10-04 조사)

운영자의 질문: 문의 장기 형태는 무엇인가. JSON schema여야 하나. 세 provider가 다 지원하나.
JSON의 장점은. acpx가 그쪽으로 갈 것인가. 아래는 공식 문서·핀된 버전의 소스·npm tarball에서
읽은 것이고, 확인 못 한 것은 UNVERIFIED로 표시했다.

### 1. 각 provider CLI의 headless 모드 (우리 이미지에 핀된 버전 기준)

| | Claude Code 2.1.287 | Codex 0.160.0 | Grok 1.0.46 |
|---|---|---|---|
| headless JSON 출력 | `-p --output-format json` | `exec --json` (JSONL 이벤트 스트림) | `-p --output-format json` (docs.x.ai) |
| schema 제약 출력 | `--json-schema` → `structured_output`. 위반 시 내부 재시도, 소진되면 `subtype: error_max_structured_output_retries` | `--output-schema FILE` → 최종 메시지가 schema에 맞는 JSON 문자열 | `--json-schema` 있음 (`grok --help`, 7절) — 공식 문서에는 없고 바이너리에 있음 |
| payload를 stdin으로 | 가능 (10 MB) | 가능 (`-` 또는 파이프) | **불가** — "headless mode does not read piped stdin"; `--prompt-file` 사용 |
| 모델 이름(pin) | `modelUsage` | **없음** — 어떤 이벤트에도 model 필드 없음 | `modelUsage` (repo 문서) |
| 턴 수 | `num_turns` | `turn.*` 이벤트 수를 세면 됨 | `num_turns` |
| permission denial | `permission_denials` | **없음** — 비대화형이라 정책(`--sandbox`)으로 다룸, 이벤트 없음 | **없음** — "does not collect permission denials" |
| 토큰 사용량 | `usage`, `modelUsage` | `turn.completed.usage` | `usage`, `modelUsage`, `total_cost_usd` |

출처: code.claude.com/docs/en/headless, …/agent-sdk/structured-outputs, …/cli-reference;
developers.openai.com/codex/noninteractive, github.com/openai/codex `rust-v0.160.0`의
`exec/src/cli.rs`·`exec_events.rs`; docs.x.ai/build/cli/headless-scripting, xai-org/grok-build 사용자
가이드 14·15(브랜치 main, 1.0.46 태그 아님).

**읽는 법.** trading이 얼린 envelope(`modelUsage`, `num_turns`, `permission_denials`,
`structured_output`)은 **Claude Code CLI 하나에만 그 모양으로 존재**한다. Codex는 모델 이름과
denial이 없고, Grok은 denial이 없고 stdin을 안 읽는다. 즉 "CLI envelope를 문이
그대로 내줘라"(선택지 C)는 세 provider에 같은 보증을 줄 수 없다. 플랫폼 계약이 될 수 없는 모양이다.

### 2. API 레벨 (CLI 아래)

| | 구조화 출력 |
|---|---|
| Anthropic Messages API | `output_config.format` (json_schema). 현행 모델 전부. 제약: 재귀 schema·수치/길이 제약 불가, `additionalProperties: false` 필수. citations와 양립 불가 |
| OpenAI API | Responses `text.format {type: json_schema, strict}`, Chat `response_format` |
| xAI API | `response_format {type: json_schema}`; "tools와 함께는 Grok 4 family만" |

세 vendor의 **API**는 모두 schema 제약 출력을 지원한다. 그러니 장기적으로 이 능력은 vendor가
흔히 주는 것이고, 문제는 그것이 우리 경로(ACP)까지 닿느냐뿐이다.

### 3. ACP · acpx · 어댑터 (우리가 실제로 타는 경로)

- **ACP 프로토콜**: `session/prompt`에 schema/구조화 출력 필드가 **없다**. `PromptResponse`는
  `stopReason`, `_meta`, 그리고 "UNSTABLE, not part of the spec yet"인 `usage`. 턴 수·도구 호출 수
  필드 없음. RFD 목록에 구조화 출력 관련 RFD **없음**. 움직이는 건 토큰 사용량뿐(Session Usage
  완료, End-Turn Token Usage 초안). 출처: agentclientprotocol.com/protocol/v1/schema, /prompt-turn,
  /rfds/updates, /rfds/end-turn-token-usage.
- **acpx 0.19.4**: `sessionOptions`는 `model, allowedTools, maxTurns, systemPrompt, env`만 통과
  (`dist/session-options-*.d.ts`). 턴별 schema 옵션 없음. `turn.result`는 `status/stopReason/_meta`.
  확장 알림(`_claude/sdkMessage`)은 기록은 하되 타입된 스트림에서 **버림**. 로드맵 문서에 구조화
  출력 없음 (github.com/openclaw/acpx).
- **claude-agent-acp 0.85.1**: `_meta.claudeCode.options`로 `outputFormat`을 **받긴 하지만**
  `structured_output`을 PromptResponse에 **내보내지 않는다**(dist에 그 문자열 없음;
  `error_max_structured_output_retries`만 실패로 매핑). 유일한 우회는 `emitRawSDKMessages`로 raw SDK
  메시지를 확장 알림으로 흘리는 것인데 acpx가 그걸 버린다. 토큰은 `_meta.quota.model_usage`에
  모델별로 있음(0.71.0부터).
- **codex-acp 2.1.1**: schema를 `turn/start`로 넘기지 않음(내부 제목 생성용 schema 하나뿐).
  토큰은 같은 `_meta.quota` 모양.

**결론(3).** 지금 경로에서 "모델이 schema에 맞춰 생성한다"는 보증은 **닿지 않고, 위쪽 어디도
그쪽으로 움직이지 않는다**. 닿는 것은: 모델별 토큰(`model_usage`), 원시 이벤트(도구 호출 포함),
permission 요청과 Preloop의 답. 문이 이걸로 줄 수 있는 보증은 "모델 pin", "도구 호출 0건"(이벤트에
tool_call이 없음), "한 번의 prompt = 한 턴"이다. 없는 것은 "schema에 맞춰 디코딩"뿐이고, 그것은
사후 검증 + 유한 재시도로 대신할 수 있다. Claude Code CLI의 `--json-schema`도 내부적으로는
"위반 시 재시도, 소진 시 실패"다 — 문이 같은 의미론을 가질 수 있다.

### 4. "꼭 JSON이어야 하나", "JSON의 장점은"

trading이 실제로 필요한 것은 넷이다. (a) 기계가 검증할 수 있는 답, (b) 도구를 안 썼다는 증거,
(c) 모델 pin, (d) 입력 바이트를 그대로 넣을 수 있음. JSON schema는 (a)를 얻는 **한 방법**이지
유일한 방법이 아니다. 장점: 파싱이 결정적이고, schema로 형태를 얼릴 수 있고, diff와 기록이 쉽고,
세 vendor API가 다 지원한다. 단점: 우리 경로에선 모델 단 제약이 안 닿는다(3절), vendor CLI마다
다르다(1절).

in-tree 패키지의 현재 답: novel은 리뷰어에게 "이 JSON을 `review_story.json`에 써라"고 시키고
`novel_stage.py`가 **사후에** 객체인지·`verdict`가 허용값인지 검증한다. 즉 novel은 (a)를
"파일 + 사후 검증"으로 이미 풀고 있고, trading은 "CLI schema"로 풀고 있다. 같은 필요를 두
패키지가 각자 풀었다 — CONTRACT 2절이 "공통"이라고 부르는 바로 그 증거다.

### 5. 그래서 문의 장기 형태

문 하나, 호출 종류 둘.

| 종류 | 무엇 | 문이 주는 보증 | 지금 |
|---|---|---|---|
| **agent task** (지금의 문) | 도구를 써서 산출물을 만든다 | 권한은 Preloop, 산출물은 이 호출이 썼는가, 기록 | 있음 |
| **query** (추가) | 도구 없이 payload → 객체. 모델을 함수처럼 | 입력 바이트 기록(stdin/inline), **도구 호출 0건**(이벤트로 확인), 모델 pin(`model_usage`), **답이 선언된 schema를 통과**(사후 검증, 유한 재시도, 실패는 `SCHEMA_REJECTED`) | 없음 — 이것이 B |

query 종류는 ACP 위에서 지금 만들 수 있다(프롬프트로 JSON을 요구 → `text` 또는 파일 → 문이
검증). 나중에 ACP/acpx가 schema를 싣게 되면 검증 앞에 "모델 단 제약"을 **같은 문 안에서** 더하면
된다. 어댑터에 CLI 경로를 따로 여는 것(C)은 1절의 표가 말하듯 provider마다 다른 보증을 세 벌
관리하는 일이고, 그중 Claude만이 trading이 얼린 모양을 준다.

**trading에 되묻는 질문 하나는 그대로다.** "모델 단 schema 제약 대신 문의 사후 검증 + 유한
재시도로, 그리고 `num_turns` 대신 '한 prompt = 한 턴 + 도구 호출 0건'으로 freeze를 재인증할 수
있는가." 된다면 B의 query 종류를 만든다. 안 된다면 trading의 직접 호출을 계약의 명시된 예외로
적고(§88에 적은 대로), 문은 지금 모양으로 둔다.

### 6. 확인 못 한 것 (측정이 필요)

- Grok 1.0.46 바이너리에 `--json-schema`가 실제로 있는가: 이미지 안에서 `grok --help` 한 번.
- claude-agent-acp의 `emitRawSDKMessages` 경로로 `structured_output`이 acpx의 journal까지는
  오는가: 측정 전까지 우회로 치지 않는다.
- trading freeze guard의 다섯 필드 중 재인증 가능한 것: 저자의 답.

### 7. 6절의 미확인 셋, 답이 옴 (같은 날)

- **Grok 1.0.46에 `--json-schema` 있음.** 운영자가 `grok --help`로 확인: "JSON Schema for
  structured output. When set, the model is constrained to produce JSON matching this schema.
  Implies --output-format json." `--prompt-file`, `--prompt-json`, `-p`도 있음. 1절 표의
  "UNVERIFIED"는 "있음"으로 고친다. stdin은 여전히 안 읽는다(`--prompt-file`로).
- **claude-agent-acp의 raw 메시지 우회는 죽은 길.** 운영자의 라이브 확인: 어댑터가 `createAcpRuntime`로
  acpx를 쓰면 journal(`*.stream.ndjson`)은 **아예 만들어지지 않는다**(journal을 쓰는 코드는 acpx
  CLI 쪽에만). claude-agent-acp가 붙인 `_meta.claudeCode`는 acpx의 이벤트 변환에서 빠진다. 남는
  곳은 둘: permission 요청(`permissions.jsonl`, `_meta.claudeCode.mcpServer`)과 turn 결과의
  `_meta.quota`(`result.json`). 즉 3절의 결론 그대로 — 모델 단 schema 제약은 우리 경로에 닿지
  않고, 우회도 없다.
- **trading 저자의 답: 재인증 가능, 조건 셋.** (원문은 #62 스레드와 운영자 메시지.)
  1. *schema*: 모델측 제약 제거는 등가. 하네스는 이미 `contract_errors()`로 사후 검증을 또 하고
     있어서 하류가 받는 보장(적합 출력만 유효)은 불변. 단 **재시도 정의**가 계약 결정이다 — 동결
     계약은 "부적합 출력 = INVALID_OUTPUT, 무재질의"이고 이는 모델 신뢰도의 측정값이라, schema
     miss에 재시도를 주면 관측량의 정의가 바뀐다. 권고: 재시도는 transport 실패에만. 펜스 제거
     같은 결정론 추출 규칙은 사전 등록.
  2. *턴·도구*: "1 prompt = 1 turn + 도구 0"은 지금보다 **강한** 불변식. 지금 `num_turns=2`가
     정상인 유일한 이유가 `--json-schema`의 내부 왕복이었다.
  3. *문의 기록이 실어야 할 최소 필드*: 턴 수, server tool use(웹 검색 포함), 모델 식별. 그리고
     모델별 usage/cache 분해는 `measurements(total_tokens/wall_ms)`로는 대체가 안 된다(관측 축
     하나 약화, 승인 필요).

**세 번째 조건을 기록된 run으로 재 본 것** (`stack/fixtures/run-agent/*`, 2026-10-03 실측):

| | claude | codex | grok |
|---|---|---|---|
| 모델 식별 (`_meta.quota.model_usage[].model`) | `claude-haiku-4-5-20251001`, `claude-opus-5-5` (둘 — 하나는 Claude Code의 내부 호출) | `gpt-6.1-sol` | **없음** (`model_usage` 비어 있음) |
| 모델별 토큰 분해 (`token_count`: input/cached/write/output/reasoning) | 있음 | 있음 | 없음 |
| 도구 호출 이벤트 (auto 워크플로, 쓰기 1건이 목적) | 10 (`ToolSearch` 1, `mcp__preloop__write_file` 1, 그 외 Claude Code 내부) | 2 | 6 |

읽는 법. (a) 저자가 "측정 1회로 판정해야" 한다던 모델 식별은 claude·codex에서 **이미 채워진다**
— 다만 `execution.json`의 `model_adapter_reported`가 그걸 옮겨 담는 자리인데, 기록된 run 셋 모두
`execution.json`이 그 필드를 비워 두었거나 없다(이 fixture들은 §74 때 것; 지금 코드는
`model_usage`를 합쳐 넣는다 — **라이브 run 하나로 확인할 것**). grok은 어댑터가 모델을 보고하지
않으므로 **grok 역할의 모델 pin은 지금 경로에서 불가**. (b) 저자가 "약화"라고 한 모델별 usage/cache
분해는 **이미 `result.json`의 `turn._meta.quota.model_usage`에 있다**(claude·codex). 문의 기록에
그 블록을 `measurements.model_usage`로 옮겨 담으면 약화가 아니다. (c) "도구 0"은 이벤트의
`tool_call`을 세면 되는데, Claude Code는 내부 `ToolSearch`를 도구 호출로 올린다. query 종류는
acpx의 `sessionOptions.allowedTools`(통과되는 옵션 중 하나)를 빈 목록으로 주고 `permissions.deny`로
막은 뒤 **`tool_call` 이벤트 0건**을 불변식으로 기록하면 된다 — 라이브 측정 1회.

### 8. 그래서 B의 정확한 모양 (query 종류)

| 항목 | 결정 |
|---|---|
| 입력 | 요청에 `payload`(inline) 또는 prompt 파일 `-`(stdin). 바이트 그대로 `request.json`에 기록 |
| 도구 | `allowedTools: []` + `permissions.deny` 전부. 불변식: `tool_call` 이벤트 0 → 기록에 `tool_calls: 0`, 아니면 `TOOLS_USED` |
| 턴 | ACP는 1 prompt = 1 turn. 기록에 `turns: 1` |
| 답 | 모델의 `text`(또는 지정 파일). 사전 등록된 결정론 추출(펜스 제거) 뒤 JSON 파싱 → 선언된 schema로 검증. 통과 → `COMPLETED` + `answer`; 실패 → `INVALID_OUTPUT`, **재시도 없음** |
| 재시도 | CONTRACT 그대로: 인프라 결함(로그인 refresh, 프로세스 사망, 비-JSON 응답)만 1회, 모델이 만든 실패는 절대 아님. 저자의 transport-only 권고와 같은 문장 |
| 기록 | 기존 execution record + `turns`, `tool_calls`, `server_tool_use`(웹 검색 도구 호출 수), `measurements.model_usage`(모델별 토큰 분해), `schema_sha256` |
| 모델 pin | `model_adapter_reported`(claude·codex). grok은 보고 안 됨 — grok 역할은 pin 불가로 명시 |

이 모양이면 trading 저자의 조건 1·2·3이 모두 충족되고, "약화" 한 건은 사라진다. 남는 것은
trading의 절차(segment 경계에서 새 바인딩 버전, prompt sha, 동결 corpus 재주행, pins 갱신)인데
그건 패키지의 일이다.

**운영자에게 남은 결정은 하나: B(query 종류)를 만들 것인가.** 근거는 다 모였다. 만든다면
순서는 (1) 문에 query 종류 + 컨트롤, (2) 라이브 측정 2회(claude·codex에서 `model_adapter_reported`가
채워지는지, `allowedTools: []`로 `tool_call` 0이 되는지), (3) trading 저자에게 재인증 시작 신호.
