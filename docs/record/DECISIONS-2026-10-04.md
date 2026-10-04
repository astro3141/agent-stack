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
