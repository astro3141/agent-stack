# CADP v0.5 TD ↔ agent-stack 갭 분석 (2026-10-02)

기준: `astro3141/common-autonomous-development-platform` @ 3057c0d (2026-09-24, PR #293 merge) 의 v0.5 plane TD 3종
대상: `astro3141/agent-stack` @ ae45f85 (2026-09-27)

세부 표: `CADP-GAP-authority.md`, `CADP-GAP-execution.md`, `CADP-GAP-workflow.md` (요구사항별 verdict + 근거 파일/섹션)

## 0. 먼저 알아둘 것: 어느 TD가 권위인가

- CADP의 `Authority order.md`는 **v0.4** 세대(Spec v0.4 + TD v2.0)만 권위로 둔다.
- v0.5 plane TD 3종과 Spec v0.5는 트리에 있지만 헤더에 "CANDIDATE while unmerged"로 표시되어 있고, authority order에는 올라가 있지 않다.
- 그래도 v0.5가 agent-stack(Conductor + Preloop)을 명시적으로 다루는 유일한 세대이므로 v0.5를 기준으로 쟀다. v0.4 TD의 재배치(re-homed) 섹션은 v0.5 TD가 지목하는 범위까지 포함했다.

## 1. agent-stack을 v0.5 어휘로 분류하면

| CADP plane | agent-stack에서 대응하는 것 | 결론 |
|---|---|---|
| Workflow Plane | Conductor 그래프, checkpoint/resume, fan-out receipt, `REPEATABLE` 선언, `run_workflow.py` | **구현되어 있음** — 단, CADP와 접점이 전혀 없음 |
| Execution Plane | `run-agent.mjs` 라우팅 레이어, `router.py` 쿼터 admission, broker, per-role egress, Preloop principal | **역할은 같으나 계약은 없음** — 자세 조항은 맞고 계약 조항은 거의 전무 |
| Authority Plane | (없음) Preloop 툴콜 승인 + apiguard 경로 제한 + MLflow 기록이 그 자리를 대신함 | **커널이 없음** — K1–K7 레코드 0개 |

## 2. 수치로 본 갭

| plane | 요구사항(행) 수 | COVERED | PARTIAL | MISSING | N-A / 범위 밖 |
|---|---|---|---|---|---|
| Authority | 56 | 0 | 18 | 38 | 0 |
| Execution | 45 | 1 | 10 | 26 | 8 |
| Workflow | 32 | 4 | 6 | 16 | 6 |

(세부 표의 verdict 열을 집계. Authority 표는 Part B의 B1/B2/B5 같은 다항 요구를 한 행으로 묶었으므로 실제 조항 수는 더 많다. PARTIAL은 대부분 "비슷한 자리에 다른 물건이 있다"는 뜻이고, 계약 형태로는 맞지 않는다.)

## 3. 가장 큰 갭 5개

1. **effect client가 없다** (WP-01/04/07/11, K3/K6/K7). `EffectRequestV1`, `allocate_effect_id`, `submit_evidence` 등 커널 API 호출이 코드·문서 어디에도 없고, compose에 커널 서비스도 없다. v0.5 TD가 워크플로 플레인에 요구하는 **유일한** 필수 통합이 100% 열려 있다.
2. **외부 효과를 워크플로가 자기 credential로 직접 수행한다** (WP-12/27, S2.3, A5/B7.1). devflow 패키지가 agent 컨테이너 안의 `DEVFLOW_GITHUB_TOKEN`으로 PR을 열고, 세 provider 로그인이 한 컨테이너에 같이 마운트된다. OPERATIONS §38은 이것을 설계로 명시한다("nothing in the platform does, and nothing should").
3. **증거가 K2 envelope이 아니라 텔레메트리다** (WP-18/19/20, K2, A11). `evidence_index.json`을 워크플로의 judge 단계가 직접 쓰고 MLflow에 붙인다. 리뷰는 TD가 말하는 P0 "orchestrator-relayed review" 그 자체라서 CADP에 넣으면 `SELF_REPORT`로만 봉인된다.
4. **실행 계약(ExecutionRequest/Result)이 없다** (S4, B1.*, B2.*, B3.*). 프롬프트·리비전·프로파일 다이제스트 없음, broker가 발급하는 attempt identity 없음, 재시도가 같은 workspace·같은 이름을 덮어쓴다(B2.5와 정반대). 산출물 해시는 모델이 쓸 수 있는 공유 `/ws`에서 사후에 뜬다.
5. **정책 identity와 분류가 fail-open이다** (K1/K4/K5, S2.5, WP-31). Preloop 계정 정책은 제자리 교체되고 결정은 policy digest를 들고 있지 않다. 모든 `policy/*.yaml`이 `unknown_tools: allow`.

## 4. 갭이 아닌 것 (TD도 닫으라고 하지 않는 것)

- **run profile 비등록**(WP-24/25): TD §5.2가 Conductor를 등록하지 않기로 측정 기반으로 결정했고, agent-stack도 F21에서 같은 결론. 다만 F21은 §5.1의 세 근거 중 둘이 Conductor v0.1.37에서 재현되지 않음을 보였고, 이 수정은 CADP TD에 반영되지 않았다.
- **scope fence**(WP-29): DAG/retry/checkpoint를 CADP에 요구하지 않는 점은 D0 교훈과 일치.
- **자세 조항**: honest `UNKNOWN`(`served: "unknown"`), requested≠observed 분리, unknown provider fail-closed, 네트워크를 경계로 삼는 것은 TD 정신과 맞는다.
- **TD에 없는 것을 agent-stack이 더 가진 것**: 쿼터 admission, 계정 identity 매칭, 로그인 lineage, per-role egress 프로파일, 승인 경로(apiguard), MLflow 기록. 모두 TD가 deployment policy에 맡긴 영역이다.

## 5. 한 줄 평가

agent-stack은 CADP v0.5의 Workflow + Execution plane을 **운영 가능한 수준으로 측정해 둔** 스택이지만, CADP가 "헌법"이라 부르는 Authority plane과는 **접점이 0**이다. 둘 사이 갭은 "덜 구현됨"이 아니라 "다른 설계 결정"이다: agent-stack은 효과를 워크플로 소유로 두고(CONTRACT.md), CADP는 효과를 플랫폼 소유로 둔다(DESIGN D-preamble). 갭을 닫는다면 첫 단계는 TD WP §3.2가 정의한 effect client(ingress-only, admission은 fail-closed)이고, 그 전에 WP §3.2가 "out of scope"로 미룬 세 가지(외부 후보의 implementer identity, 리뷰어 독립성 계산, `backend_model_present` 적용)에 대한 reference-policy delta가 CADP 쪽에 필요하다.

## 6. CADP 쪽에 되돌릴 만한 측정 수정

- WP §3.3: `CONDUCTOR_RUN_ID`는 export되지 않는다고 했으나 agent-stack은 `CONDUCTOR_SELF_RUN_ID`를 쓰고 그것은 export된다.
- WP §5.1: "deleted on normal completion"/"no receipt" 두 근거는 v0.1.37에서 재현되지 않음(F21). 남는 근거는 K7의 target-authority 하나뿐이며, 그 근거로 §5.2를 다시 쓰는 편이 버전 드리프트에 강하다.
