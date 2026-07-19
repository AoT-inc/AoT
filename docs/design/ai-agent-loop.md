# AoT AI — 단일 에이전트 루프 재설계 (Design Doc v1)

상태: **Phase 1 + 1.5 구현·검증 완료(카나리 플래그 뒤, 기본 OFF)** · 작성 근거: 현행 오케스트레이션 코드 실측 매핑
목표 독자: AoT 개발자 · 결정 필요 항목은 §11에 모아둠 · Phase 1 실측 결과는 §13, Phase 1.5는 §14

---

## 1. 왜 재설계인가 (한 문장)

현재 AI는 **사용자 의도를 이해하지 못하고, 자기 도구가 뭔지 모르며, 막히면 되묻지 않고 환각한다.** 이는 특정 기능(노트 등)의 버그가 아니라 **오케스트레이션 구조 자체**의 문제라, 기능별 패치로는 고칠 수 없다.

### 현행 구조의 구조적 결함 (실측)

| 요구 | 현재 상태 | 근거 |
|---|---|---|
| 의도 파악 | 라우터가 **도구를 안 보고** 단일 enum 1개로 분류. 하위목표·슬롯 없음. 오분류 시 엉뚱한 엔진. | `ai_routing_service.py run_router` |
| 도구 인지 | 실행부가 "X라 하면 Y도구" **하드코딩 규칙 수십 개**로 유도. native/virtual/MCP **3사일로** + 이름충돌 dedupe. | `run_fast_path` 프롬프트, `resolve_action` |
| 모르면 확인 | **맨 앞 라우터 confidence 게이트 1곳뿐**. 이후 단계는 못 물음 → 막히면 환각. | `_process_nl_command_impl:991` |
| 단계적 처리 | 단계가 **두 오케스트레이터(UOC/메인)로 분산**, 핵심 루프·지식검색 **플래그 OFF**, 단계마다 텍스트 재직렬화·100k 잘림, 공유 작업기억 없음. | `unified_orchestrator.py`, `ai_settings.py` 플래그 |
| doc_ai/MCP/라이브러리 | 문서 grounding 기본 OFF → how-to는 지어냄. MCP는 사일로. 라이브러리는 읽기전용 정적 grounding일 뿐, AI가 스스로 정보를 모으고 평가·색인하지 못함(별도 재설계 문서로 확정). | `t3_knowledge_search_enabled=False`, [ai-library-redesign.md](ai-library-redesign.md) |
| 네이티브 tool-use | **gemini 엔진만** 함수호출 루프. anthropic 등 7개는 텍스트 파싱 → **워커 모델 따라 동작이 다름**. | `gemini.py` vs `anthropic.py` |

---

## 2. 목표 / 비목표

**목표**
- G1. 모든 기능(제어·조회·노트·GIS·함수·스케줄·문서·외부MCP)에 **동일한 하나의 메커니즘**으로 대응.
- G2. LLM이 **전체 도구를 보고 스스로** 선택 (기능별 하드코딩 제거).
- G3. **불확실하면 사용자에게 되묻기**를 루프 어느 단계에서든 1급 행동으로.
- G4. **환각 금지** — 도구로 확보하지 않은 데이터(센서·날씨 등)를 지어내지 않음. 모르면 "모른다/확인 필요".
- G5. **모델 불가지(model-agnostic) — 최우선 원칙**. 이 시스템은 **사용자가 모델을 선택**하며 **기본/고정 모델이 없다**(현재 gemini는 활성화된 *테스트* 모델일 뿐). 어떤 엔진(anthropic/gemini/openai/ollama/…)을 켜도 **동일하게 동작**해야 하고, 특정 모델을 전제·하드코딩하지 않는다.
- G6. 물리제어·변이 작업은 **승인 게이트 유지**.

**비목표(이번 범위 아님)**
- 새 LLM 모델 학습/파인튜닝.
- 위젯·GIS 등 개별 기능의 UI 재설계.
- MCP 서버 자체 구현.

---

## 2.5 역량 범위 — "왜 멍청하게 느껴지는가" (전문가 에이전트 비전)

당초 이 채팅 AI는 **input/output/function 조립을 넘어 시스템 오류탐색·(코딩)·웹정보 처리**까지 하도록 상당한 도구를 갖도록 설계됐다. 그런데 멍청하게 느껴지는 이유는 **도구가 없어서가 아니라, 오케스트레이션이 그 도구를 못 휘두르기 때문**이다. 실측 증거:

- **진단 도구는 있는데 연결이 끊겨 있다**: `analyze_system_failure_tool`(AITask 실패로그·MCP브리지 상태 감사)이 구현돼 있으나 `tool_registry.py`에서 `handler=None` → **디스패치 맵에 없어 호출 불가**.
- **전문 도구가 사일로에 잠겨 있다**: 웹fetch(`mcp_fetch`)·시계열/DB(`mcp_influxdb`/`iotdb`/`grafana`/`database`)·표(`mcp_excel`) MCP 서버가 존재하지만, MCP 사일로 + 헬스/플래그 게이트로 사실상 미노출.
- **지식/문서 grounding OFF**: how-to·설정위치 질문을 문서로 못 받쳐 지어냄.
- **단계적 추론이 없다**: 진단(로그수집→가설→검증→수정제안)이나 다단계 전문작업은 **루프**가 있어야 하는데 단일패스라 불가.
- **활성 모델이 lite 테스트 모델**: 오케스트레이션이 좋아도 약한 모델은 전문작업을 못 함.

**즉 단일 에이전트 루프(+통합 카탈로그)가 바로 이 비전을 푸는 열쇠다.** 도구를 아무리 늘려도 현행 라우터 팬아웃으론 못 쓴다.

### 역량별 실현 가능성 (정직하게)
| 역량 | 실현성 | 필요 조건 |
|---|---|---|
| **조립**(input/output/function/GIS/시퀀스) | 이미 있음 | 카탈로그에 정식 노출 + 루프 |
| **시스템 오류탐색/진단** | **높음** — 루프에 강한 적합 | `analyze_system_failure` **연결(handler)** + 로그·상태·에러이력 읽기 도구 확충. 루프가 증거수집→추론→수정제안 |
| **웹 검색/정보 처리** | **가능** | `mcp_fetch`(+검색 도구)를 카탈로그에 노출·활성화. 루프가 호출·요약. 출처 grounding |
| **코딩(엔티티 코드 생성)** | **핵심 요구 · 가능** — AoT 소스 편집이 아니라 **사용자 엔티티에 들어갈 코드 생성** | §2.6 |
| (품질 상한) 전문작업 정확도 | 활성 **모델 역량에 비례** | 모델 불가지(G5)로 *동작*은 보장, *품질*은 사용자가 켠 모델에 좌우 → 전문작업엔 강한 모델 권장(이건 default 하드코딩이 아니라 **작업에 맞는 모델 선택**) |

### 2.6 "코딩" = 사용자 엔티티 코드 생성 (정정)

**요구의 정체**: AoT 소스코드 편집이 **아니다**. 시스템이 **의도적으로 제공하는 사용자 확장점**의 코드를, 사용자 요청대로 AI가 생성/편집하는 것이다. 실측된 확장점:
- **Python 코드 output**(`aot/outputs/pwm_python.py` 등): `python_code_user` 필드에 사용자 Python. 저장 시 **pylint 분석 옵션 내장**.
- **Linux/shell 명령 output**: `Output.linux_command_user` 필드에 셸 명령.
- **Conditional 함수**: `Functions.conditional_statement` = 저장된 Python 식.
- 그리고 **input/output/function/GIS input 엔티티 자체를** 요청대로 생성·구성(create_input/output/function 등 이미 존재).

**위험등급(정정)**:
- **Tier A**: 엔티티 조립 + 파라미터 구성(코드 없음). 이미 도구 있음. 변이=승인.
- **Tier B (핵심 요구)**: 위 코드 필드(python_code_user / linux_command_user / conditional_statement)에 들어갈 **코드를 AI가 생성**. 이 코드는 **호스트에서 시스템 권한으로 실행**되므로 강력하지만, **원래 사용자가 직접 쓰던 지점**이라 정당한 확장이다. 가드: ①변이 **승인 게이트**(생성/수정 전 건), ②**저장 전 코드 미리보기**를 승인 카드에 노출(사용자가 실제 코드를 보고 승인), ③python은 **pylint 분석**(이미 존재) 결과 첨부, ④가능하면 dry-run/구문검사. 강한 모델일수록 품질↑(모델 불가지, 품질은 모델 비례).
- **Tier C (범위 밖)**: AoT **자체 소스코드** 자율 편집·배포 — **이번 요구 아님**, 기본 차단. 필요시 별도 설계(샌드박스+테스트+승인+롤백).

**요지**: 코딩 능력 = "엔티티에 넣을 코드 생성"이며, 이는 카탈로그의 create/modify 도구가 **코드 필드까지 채우도록** 하고 **승인 카드에 코드 미리보기+lint를 실어** 안전하게 실현한다.

---

## 3. 핵심 아이디어 — 상태를 가진 단일 에이전트 루프

라우터 팬아웃(의도→상호배타 엔진)을 **하나의 에이전트 루프**로 대체한다. 매 턴:

```
build_context()            # 대화이력 + 시스템상태 + 전체 도구카탈로그 (1개 객체)
loop (bounded, 예: ≤6 step):
    decision = LLM.step(context)     # 네이티브 tool-calling
    if decision == tool_call(read_tool):     # 센서·노트·문서·검색·MCP조회
        result = execute(read_tool); context += result; continue   # 정보 수집 (자동)
    if decision == tool_call(ask_user):      # ★ 확인이 1급 행동
        return question_to_user                                    # 턴 종료, 다음 턴서 재개
    if decision == tool_call(write/physical): # 제어·변이
        propose_for_approval(...); return proposal                # 승인 게이트
    if decision == final_answer:
        return answer
```

- **의도는 추론에서 창발**한다. "정리해"를 대화+도구 맥락으로 이해해 `search_notes`를 부르거나, 애매하면 `ask_user`를 부른다. 단일 enum 오분류가 사라진다.
- **확인=행동**: 별도 상태머신 불필요. 되물으면 그 질문이 이번 턴의 응답이 되고, 다음 턴에 LLM은 대화이력(자기 질문+사용자 답)을 보고 자연스럽게 이어간다. (§7)
- **읽기 도구는 루프 안에서 자동 실행**(승인 불필요), **쓰기/물리 도구는 제안→승인**. 현행 `_RAG_TYPES` vs `PHYSICAL_TOOLS` 구분을 재사용.

### 3.1 공유 컨텍스트 객체 (작업기억)
매 턴 1회 구성, 루프 내내 공유(단계별 재직렬화·재분류 없음):
- `messages`: 스레드 대화이력(사용자·AI·**도구결과 포함**).
- `system_state`: `get_master_context`(스코프별 슬림) — 현재 장치·구역·요약.
- `tools`: **통합 도구 카탈로그**(§4) — name/description/JSON schema.
- `page_context`: 현재 대시보드·지도 스코프(위치 추론 보조).

---

## 4. 통합 도구 카탈로그 (3 사일로 → 1 인터페이스)

현행: native(AoTNativeToolEngine) · virtual(`virtual_tool_call`→AoTDataToolService) · MCP(`mcp_tool_call`→라이브서버)가 분리, 이름충돌로 gemini가 dedupe.

**목표**: 단일 리스트 `AgentToolCatalog`.
- 각 도구 = `{name, description, input_schema, kind: read|write|physical, dispatch: virtual|mcp|native, needs_approval: bool}`.
- **SSOT 확장**: 기존 `tool_registry.py TOOLS`를 확장해 MCP·native까지 포함(또는 런타임 병합). dedupe·우선순위는 기존 `resolve_action`의 `[MCP_PRIORITY_GATE]` 로직 재사용.
- **전문 역량도 그냥 도구**(카탈로그의 한 부분):
  - **지식(읽기+쓰기)**: `knowledge_search(query, tags?, entity_ref?, top_k)` / `knowledge_shelve(content, content_kind, tags, entity_ref?, attribution, ttl?)` — [AI 라이브러리 재설계](ai-library-redesign.md) 정의. 매뉴얼·외부권위지식·AI 큐레이션·(검색계층에서 합류하는)노트를 provenance/trust와 함께 조회하고, AI가 유용 정보를 자율 비치(`ai_curated` 이하로 진입, 승인 불필요·§3.3 사후거버넌스). how-to·설정값·도메인지식 전부 이 한 쌍으로.
  - **진단**: `analyze_system_failure`(현재 `handler=None`으로 끊김 → **연결**), + 로그·장치상태·에러이력 읽기 도구.
  - **웹**: `mcp_fetch`(+검색) → 조회 결과는 `knowledge_shelve(provenance=external_authority 또는 ai_curated)`로 비치해 재사용·감사 가능.
  - **시계열/DB**: `mcp_influxdb`/`iotdb`/`grafana` → 심층 데이터 분석, 도출 패턴은 `provenance=data_derived`로 비치 가능.
  - **조립/코딩**: create_function/sequence 등(변이=승인). 코딩 Tier B/C는 §2.6 게이팅.
- **슬림/필터 폐기 방향**: 의도별로 도구를 숨기지 않는다(라우터가 없으니). 대신 description을 좋게 쓰고, 토큰 문제는 카탈로그를 간결히 유지 + 필요시 `get_detailed_manifest` 도구로 확장 조회.

**승인 규칙**(불변): `kind ∈ {write, physical}` 또는 `PHYSICAL_TOOLS`/`approval_required_tools()` 소속 → 실행 대신 제안+승인. 읽기 도구만 루프 내 자동 실행.

---

## 5. 엔진 추상화 — 모델 불가지 tool-calling (G5)

현행: gemini만 함수호출, 나머지 7개는 텍스트 파싱(→**켠 모델 따라 동작이 달라짐** = 위반).

**설계 원칙: 범용 프로토콜이 baseline, 네이티브는 최적화.** 사용자가 어떤 모델을 켜도 동일 동작해야 하므로, **모든 엔진이 반드시 지원하는 텍스트 기반 도구호출 프로토콜을 바닥에 깐다.** 네이티브 함수호출(gemini/anthropic/openai…)은 그 위에 얹는 성능·신뢰성 최적화일 뿐, **없어도 루프는 동작한다.**

**통일 인터페이스** (`BaseAI`):
```
engine.run_agent_step(context, tools) -> ToolCallDecision | FinalAnswer
    # 반환: 도구호출(name+args) 또는 최종답변. 루프 1스텝만 결정.
capabilities: {native_tool_calling: bool}   # 엔진이 스스로 신고
```
- **native_tool_calling=True 엔진**(gemini 등): SDK 네이티브 함수호출로 `run_agent_step` 구현(구조적·안정적).
- **native_tool_calling=False 엔진**(현 anthropic 텍스트경로·ollama 등): **공용 텍스트 프로토콜**로 구현 — 도구 카탈로그를 프롬프트에 싣고, 모델은 약속된 JSON(예: `{"tool":"name","args":{…}}` 또는 최종답변)만 출력. 에이전트가 파싱·실행·재주입. (현행 `run_fast_path` 파서를 이 공용 프로토콜로 정리해 재사용.)
- **동일 계약**: 두 경로 모두 같은 `ToolCallDecision`을 반환하므로 **루프·카탈로그·승인 로직은 엔진을 모른다.** 새 모델 추가 = 엔진 클래스 하나가 인터페이스만 구현.
- **루프 소유권**: 루프는 **엔진 밖(AgentLoopService)**이 소유. 엔진은 한 스텝만 결정(gemini 내부 3턴 중첩루프 제거). 도구 실행은 에이전트가 하고 결과를 다음 스텝에 주입.
- (별건 최적화) anthropic 네이티브 tool-use 구현은 품질 향상이지 **전제 아님** — 텍스트 프로토콜로 이미 동작.

---

## 6. 의도 이해 — enum 라우터 대체

- **1급 라우터 제거**(또는 초경량 triage로 축소): "인사/잡담 vs 작업" 정도만 저비용 판단해 잡담은 바로 응답, 나머지는 에이전트 루프.
- 진짜 의도 파악은 **루프 첫 스텝**에서 LLM이 대화+도구를 보고 수행. 필요하면 스스로 하위목표로 쪼개 순차 도구 호출(단계적 정확도 향상).
- **다중 의도**("A 조회하고 B 켜") 자연 처리 — 라벨 하나로 강제하지 않음.

---

## 7. 확인(ask_user)과 재개 — 멀티턴

- `ask_user(question, options?)`는 카탈로그의 도구. LLM이 부르면 그 질문이 턴 응답이 되고 턴 종료.
- **재개는 대화이력으로**: 다음 사용자 발화 시, 에이전트는 이력(자기 질문+사용자 답+그때까지의 맥락)을 그대로 컨텍스트로 받아 루프를 처음부터 재실행 → 자연 이어짐. **별도 pending-state 저장소 불필요**(이력이 곧 상태).
  - 보강 옵션: 직전 턴이 ask_user였고 수집한 부분결과가 있으면, 그 요약을 이력의 AI턴 메타(`execution_result`)에 남겨 재구성 손실 최소화. (기존 `get_thread_history`의 tool-result 첨부 재사용)
- **프런트엔드**: 질문은 일반 AI 응답으로 렌더(선택지 있으면 버튼). 새 UI 계약 최소화.

---

## 8. 환각 방지 (G4)

- 시스템 프롬프트 하드룰: "이번 턴에 **도구로 확보하지 않은** 센서·날씨·상태·도메인지식 수치를 진술하지 마라. 모르면 도구를 부르거나 `ask_user`로 물어라. 지어내지 마라."
- how-to·설정위치·도메인지식 질문은 **반드시** `knowledge_search`로 grounding 후 답(결과 없으면 "모른다/확인 필요", 지어내지 않음). 결과의 provenance/trust를 그대로 인용(권위 vs "AI 정리·미확인" 구분 — [라이브러리 재설계 §3](ai-library-redesign.md#3-provenance--신뢰-거버넌스-핵심)). `t3_knowledge_search_enabled` 기본 ON으로.
- 합성기의 "막히면 대시보드 나열" 기본행동 제거.

---

## 9. 안전 · 승인 · 회귀 방지

- 물리제어·변이(`PHYSICAL_TOOLS`, `approval_required_tools()`)는 **항상 제안→승인**. 루프는 이들을 자동 실행하지 않음.
- 승인 실행 경로(`execute_logged_action`)·승인 UI는 유지. (별건: 새로고침 팬텀버튼은 이미 history-gate로 수정됨)
- **플래그 게이트**로 도입: `agent_loop_enabled`(신규). OFF면 현행 파이프라인, ON이면 신규 루프. 스레드/사용자 단위 카나리 가능.

---

## 10. 마이그레이션 (단계)

- **Phase 0 — 정리**: 이번 세션에 넣은 노트 땜질 되돌리기.
  - 되돌림: `handle_note_operation`·`_classify_note_op`·`_note_op_kind`·terse-read·`_ensure_note_created` 가드·라우터 `NOTE` 인텐트 분기.
  - **유지(범용적이라)**: 라우터 대화이력 주입(§6 triage에 재활용), i18n(gettext) 정리, `search_notes` target_name 읽기 인자, create_note 승인 비게이팅.
- **Phase 1 — 루프 프로토타입(플래그 뒤, 모델 불가지)**: `AgentLoopService` + `engine.run_agent_step` **통일 인터페이스**를 함께 신설. **공용 텍스트 프로토콜을 baseline으로** 먼저 구현해 **활성 모델이 뭐든 동작**(gemini면 네이티브, 아니면 텍스트경로). 컨텍스트 객체 + 통합 카탈로그(virtual+native 읽기 도구부터) + `ask_user` + 승인 게이트. 채팅을 플래그로 이 루프에 태움. ※ 특정 모델 전제 금지(G5).
- **Phase 2 — 네이티브 최적화 + 전문도구 병합**: 네이티브 tool-calling 미지원 엔진(anthropic 등)에 네이티브 경로 추가(품질↑, 전제 아님). 카탈로그에 **끊긴/사일로 도구 연결**: `analyze_system_failure` handler 연결, MCP(fetch/influxdb/grafana…)·`knowledge_search`/`knowledge_shelve`([라이브러리 재설계](ai-library-redesign.md) P1~P4) 병합, dedupe/우선순위 통합. → 진단·웹·심층분석·자기학습 지식 역량 해금.
- **Phase 3 — 은퇴**: 검증 후 라우터 팬아웃·UOC 분기·`intent_resolver` 인터셉터·per-intent 프롬프트 규칙 제거. 지식검색 grounding 상시 ON, 라이브러리 재설계 P5~P6(신뢰승격·리뷰UI·플래그 기본ON) 완료.

각 Phase는 골든셋(§ 아래) 통과가 관문.

### 검증 (골든셋)
다양한 기능을 교차하는 시나리오로 회귀 방지:
- 제어("밸브1 3분"), 조회("3-2 온도"), 노트(생성/요약), 스케줄, 함수생성, **how-to("색 바꾸는 법")**, **모호("정리해")→ask_user**, **다중("A 보고 B 꺼")**, **문맥 후속("등록해")**, **환각 트랩("아무거나 물어본 적 없는 것")→모른다/확인**.
- 각 시나리오: 올바른 도구 선택 + (필요시) 되묻기 + 환각 없음.

---

## 11. 결정 (확정 / 잔여)

**확정됨(사용자 결정):**
1. **라우터** → 완전 제거가 아니라 **잡담만 거르는 초경량 triage 유지**. 작업성 발화는 모두 에이전트 루프로.
2. **모델** → **불가지(G5). 기본/테스트 모델 전제 금지.** Phase1부터 공용 텍스트 프로토콜로 활성 모델 무관 동작. (이전 "gemini로 시작"은 철회.)
3. **ask_user UX** → **버튼 + 자유응답 둘 다.** `ask_user(question, options?)`; options 있으면 버튼, 없거나 "기타"면 자유 입력.
4. **토큰/카탈로그**(질문 철회, 설계로 확정): 전체 도구를 매 스텝 장황히 싣지 않는다. **간결한 name+1줄설명 카탈로그**를 항상 노출하고, 상세 스키마·옵션은 필요한 도구에 한해 **`get_tool_detail` 확장조회 도구**로 가져온다. (별도 사용자 결정 불필요.)

**확정됨(추가):**
5. **UOC 제거** → **Phase3에서 제거 확정.** (§11.1)
6. **롤아웃** → **플래그 카나리 확정**(특정 스레드/사용자부터 켜서 검증 후 확대).

### 11.1 UOC(UnifiedOrchestrator)란 무엇이고 왜 문제인가
- 위치: `aot/ai/orchestration/unified_orchestrator.py`, 채팅 진입점(`routes_ai_api.py:445`)에서 **메인 파이프라인보다 먼저** 호출됨.
- 동작: `_classify_tier`가 **키워드 휴리스틱**으로 티어를 나눔 — 메시지에 `"automation"/"자동화"/"and then"/"먼저"/"schedule"` 등이 있으면 **TIER2**.
- **TIER2만** UOC 자체 5단계(route→plan→resolve→approve→dispatch)로 **메인 파이프라인을 통째로 우회**해 처리. 그 외(TIER0/1)는 아무것도 안 하고 메인으로 넘김(순수 오버헤드).
- **왜 문제**: 거의 같은 요청이 **"자동화" 같은 단어 하나로 완전히 다른 엔진**을 타서 동작이 갈림. 승인·도구·컨텍스트 처리가 메인과 다른 **제2의 사일로**. 단일 에이전트 루프로 수렴시키려는데 정면으로 배치됨.
- **제안**: 단일 루프가 다단계 요청("A 하고 B")도 자연 처리하므로 UOC는 존재 이유가 사라짐 → **Phase3에서 제거**. (확인 필요: ⑤)

---

## 12. 리스크

- **R1 LLM 신뢰성**: 결정론 제거 → 도구선택·되묻기를 모델에 위임. 완화: 골든셋 상시검증 + 승인게이트(물리안전) + 환각 하드룰 + 되묻기 장려.
- **R2 토큰/지연**: 루프·전체도구 → 비용↑. 완화: 카탈로그 간결화, bounded step, triage, 캐시.
- **R3 대공사 회귀**: 완화: 플래그 게이트·Phase별 골든셋·현행 경로 병존.
- **R4 엔진 편차**: 엔진마다 tool-calling 지원차. 완화: **공용 텍스트 프로토콜을 baseline으로 모든 엔진 강제 지원**(G5) → 모델 불가지. 네이티브는 얹는 최적화. 특정 모델 전제 금지.

---

## 부록 A — 재사용 가능한 기존 자산
- `tool_registry.py`(SSOT) → 카탈로그 기반.
- `AIActionService.resolve_action`/`execute_action`(name→dispatch, MCP우선게이트) → 통합 실행기.
- `gemini.py _build_tools_schema`/functionCall 루프 → 엔진 스텝 참조 구현.
- `knowledge_search.py`/`_manual_grounding`(정적 매뉴얼 검색) → [ai-library-redesign.md](ai-library-redesign.md)의 `knowledge_search`/`knowledge_shelve`(통합 지식 저장소, provenance/trust) 도구로 확장·흡수.
- `PHYSICAL_TOOLS`/`approval_required_tools()` → 승인 분기.
- `get_thread_history`(tool-result 첨부) → 컨텍스트·재개.

---

## 13. Phase 1 실측 결과 (2026-07-19)

### 구현
`aot/ai/services/agent_loop_service.py`(`AgentLoopService`) 신설. 예상보다 훨씬 가벼웠다 — 엔진 인터페이스를 새로 만들 필요가 없었다:
- **모델 불가지가 공짜로 달성됨**: 모든 엔진이 이미 구현한 `engine.run_reasoning(context, goal)`를 그대로 반복 호출. gemini는 `context['capabilities']['system_tools']`를 보면 자동으로 네이티브 함수호출을 씀 — 엔진별 분기 코드 0줄.
- **카탈로그·승인·실행은 전부 재사용**: `AIActionService.get_action_manifest`(카탈로그), `AIActionService.execute_action`(읽기 실행), `AIDispatchService._dispatch_actions`(쓰기/물리 승인분기 — 기존 로직 그대로) — 신규 오케스트레이션 계층 1개만 추가.
- 신규 도구 2개: `ask_user`(registry-only, 루프가 직접 가로챔), `get_tool_detail`(간결 카탈로그의 확장조회).
- 카나리 플래그: `AIGlobalSettings.agent_loop_enabled` + `agent_loop_canary_user_ids`(alembic `p5_51_agent_loop_canary_flags`). 기본 OFF, 회귀 0건 확인.
- `routes_ai_api.py`: 카나리 대상은 UOC(TIER2 키워드 포크)를 완전히 건너뜀.

### 안전 관련 발견 (설계 중 발견, 구현 전 수정)
`execute_action`에 물리제어(`PHYSICAL_TOOLS`) 하드 차단 게이트는 있었지만 **일반 변이 도구(create_function 등)엔 그 게이트가 없었다.** 그런데 gemini 엔진의 `run_reasoning`은 함수호출을 받으면 **승인 없이 자체적으로 `execute_action`을 직접 호출**하는 내부 루프를 갖고 있었다(다른 7개 엔진은 절대 자체실행하지 않고 `{insight,actions}`만 반환). 전체 카탈로그를 노출하면 gemini가 변이를 자가승인할 위험이 있어, **`AIActionService.requires_approval(tool_name)` 헬퍼 신설 + gemini.py에 게이트 삽입**(승인 필요 도구는 자체실행 대신 `{insight:'', actions:[action]}`으로 반환해 다른 엔진과 동일하게 동작). `AIActionService`가 gemini.py에 임포트조차 안 돼 있던 기존 잠재 버그(이 분기가 한 번도 실행된 적 없었다는 뜻)도 함께 발견·수정. 이로써 모든 엔진이 승인 게이트 앞에서 진짜로 동등해짐(G5 실질 충족).

### 검증 (실 DB, gemini-3.1-flash-lite-preview, 쓰기는 롤백/정리)
| 시나리오 | 결과 |
|---|---|
| 물리제어("밸브1 3분") | `proposed_actions=1, immediate_results=0` — 정확히 게이팅, 자가실행 안 됨 |
| 조회("3-2 온도") | 실제 센서값+타임스탬프로 응답(그라운딩, 환각 아님) |
| 노트 생성 | 정확히 1개 생성, 거짓성공 없음 |
| **위치계층("1포장 1-1")** | zone "1-1"에 정확히 부착(site "1포장" 아님) — 이번 세션 전체를 촉발한 버그가 결정론 코드 없이 해결됨 |
| 노트 요약 | 실제 저장된 내용 그대로 요약(환각 아님) |
| 모호("정리해", 새 스레드) | 대시보드 데이터 환각 없음. 다만 `ask_user` 도구를 엄격히 호출하기보다 자연어로 부드럽게 되묻는 경우 있음(후속 개선 여지, §후속) |
| 미해결 위치 | orphan 노트 생성 안 됨(delta=0), 실제 후보 목록 제시 |
| **멀티턴 ask_user 재개** | 1차 시도 실패(컨텍스트가 거대 JSON blob에 묻힘) → `_build_step_prompt`에 명시적 "CONVERSATION SO FAR" 텍스트 블록 추가(라우터 이력주입과 동일 교훈) → 재검증 성공: 위치+내용 2턴에 걸쳐 정확히 노트 1개 생성 |
| bounded loop | 6-step 상한 내 21초 안전 종료(status=success), 폭주 없음. 마감 답변 품질은 개선 여지(진행중 서술로 끝남) |
| 카나리 OFF 회귀 | 플래그 원복 확인, `_intercept≠agent_loop`, 기존 파이프라인 완전 그대로 |
| 다중엔진 비교(al_engine_agnostic_01) | **미검증** — 이 환경엔 gemini 외 활성화된 엔진 없음(anthropic 미설정). 침묵 누락시키지 않고 명시. |

### 후속 (Phase 1.5에서 1·2 완료, 나머지 Phase 2 진입 전)
3. 두 번째 엔진(anthropic 등) 활성화 후 §al_engine_agnostic_01 실측.
4. **라이브러리 재설계가 이 세션과 무관하게 이미 상당 부분 구현 진행 중이었음을 발견**(`tool_registry.py`에 `knowledge_shelve` 실도구, `knowledge_search.py`/`context_source_service.py` 등 다수 파일이 세션 시작 전부터 커밋 안 된 상태로 수정돼 있었음). Phase 2에서 지식도구를 카탈로그에 편입할 때 이 기존 작업 상태를 먼저 정확히 파악할 것 — 처음부터 새로 설계하지 말 것.

---

## 14. Phase 1.5 다듬기 실측 결과 (2026-07-19)

### 1) ask_user 호출 일관성 — 근본 원인은 프롬프트가 아니라 gemini 엔진
증상: 모호한 요청에 모델이 `ask_user` 도구를 부르기보다 산문으로 되묻는 경우가 잦음. **근본 원인 발견**: gemini `run_reasoning`의 네이티브 함수호출 루프가 `ask_user`를 받으면 `requires_approval('ask_user')=False`라 승인게이트를 통과 → **내부에서 `execute_action('ask_user')` 직접 실행 → 핸들러 없어 에러 → 삼켜지고 모델이 산문 질문으로 폴백**. 즉 도구를 안 부른 게 아니라, 불러도 엔진이 먹어버렸음.
- **수정**: `ask_user`는 실행 도구가 아니라 **오케스트레이터가 처리하는 제어-흐름 도구**. gemini 게이트를 `if tool_name=='ask_user' or requires_approval(tool_name): return {actions:[action]}`로 확장 → 승인도구처럼 액션으로 돌려줌 → `AgentLoopService._extract_ask_user`가 가로채 구조화 질문+옵션으로 표면화.
- **레거시 안전망**: `ask_user`가 이제 모든 매니페스트에 있으므로 레거시 파이프라인의 gemini도 부를 수 있음. `AIDispatchService._dispatch_actions`에 중앙 안전망(@ANCHOR: ASK_USER_DISPATCH_SAFETY): ask_user 액션 발견 시 질문을 insight로 표면화하고 실행 안 함 → 어느 경로로 새어도 깨진 dispatch/빈 응답 대신 정상 되묻기로 degrade.
- **산문 폴백 태깅**: 모델이 그래도 산문으로 물으면(`?`로 끝) `_looks_like_question`으로 intent=CLARIFY 태깅(가시 텍스트 불변, 메타만 일관).
- **실측**: "노트 생성해줘"→intent=CLARIFY + options=[구역 목록](버튼 렌더 가능), "그거 저장해줘"→CLARIFY+options. 레거시(카나리 OFF) 회귀 없음(비어있지 않은 정상 응답). 다만 "정리해"처럼 경계적으로 모호한 건 모델이 여전히 느슨히 답함(환각은 아님, 실제 시스템 요약) — 약한 모델(lite) 판단 한계, 강한 모델서 개선 기대.

### 2) bounded-exit 메시지 품질 — 부분결과 합성
증상: step cap 도달 시 마지막 스텝의 진행중 서술("…확인하겠습니다")을 그대로 반환.
- **수정**: `_final_synthesis` — cap 도달시(드문 경로) **도구 없는 LLM 1콜**(context에 capabilities 생략 → 엔진이 도구스키마 미부착 → 텍스트 강제)로 지금까지의 `tool_log`를 정직한 부분답변으로 합성("한 것 보고 + 못한 것 명시, 약속 금지").
- **실측**: 6구역 온도+노트 복합요청 → 16초 안전종료, "센서 없어 온도 제공불가 + 실제 노트요약(3-1은 4개, 1-1은 2개, 나머지는 없음)"의 정직한 부분답변. 스톨 소멸.

### 3) ask_user 옵션 버튼 프론트엔드 렌더 (완료, 브라우저 실측)
백엔드가 `ask_user_options`를 반환해도 채팅 JS가 버튼으로 그리지 않던 갭을 배선:
- **백엔드**: `AgentLoopService._finish`가 결과에 `ask_user_options` 포함, `routes_ai_api.py`가 스트림·논스트림 응답 페이로드 양쪽에 전달.
- **프론트**: `aot-ai-global.js` `_appendMessage`에 `options` 파라미터 추가 — 각 옵션을 클릭 칩(**기존 `.ai-action-btn` 재사용, 새 CSS 없음**)으로 렌더, 클릭 시 `_handleSend(label)`로 답변 전송+형제 버튼 비활성화. 캐시버전 `?v=20260719a`(layout_default+layout).
- **브라우저 실측**(카나리 임시 ON): "노트 하나 만들어줘"→구역 옵션 버튼 7개 렌더→"3-2" 클릭→답변 전송·버튼 회색화→"내용 알려주세요"→"오늘 병해충 방제 완료"→**DB에 zone 3-2 노트 실제 저장 확인**. 멀티턴 재개+버튼 UX 완전 동작. 검증 후 카나리 OFF 복원.
- 히스토리 리로드 시 옵션 버튼은 미렌더(라이브 턴 전용 affordance, 답변 후 stale이라 의도적).

### 후속(Phase 2로)
- "정리해"류 경계 모호성 처리는 강한 모델 + few-shot로 개선 여지(과잉 되묻기 위험 있어 신중).
- 모델이 ask_user 도구 대신 산문으로 되묻는 경우(옵션 없음)의 일관성 — 강한 모델서 개선 기대.
- 두 번째 엔진 활성화 후 모델무관성 실측(§13 미검증 항목).

## 15. Phase 2 실측 결과 (2026-07-19)

착수 전 조사(§10 Phase2 범위 재확인): `docs/design/ai-library-redesign.md` P1~P6는 이미 완료·검증됨(`knowledge_shelve`는 실제 등록된 도구), MCP(fetch/grafana/influxdb) 3개는 카탈로그에 넣을 "사일로 도구"가 아니라 별도 축의 AI **엔진 타입**(`mcp_fetch`/`mcp_grafana`/`mcp_influxdb`, `is_mcp: True`)이었음 — 조사 없이 진행했다면 헛작업이 됐을 부분. `get_action_manifest()`는 이미 활성 `MCPServer` 등록분을 `mcp_tools`로 매니페스트에 병합하고 있어 그 축은 Phase1 이전부터 동작 중이었음.

### 1) `analyze_system_failure` 재연결
`tool_registry.py`의 `Tool('analyze_system_failure', handler=None)`을 `handler='analyze_system_failure_tool'`+manifest 추가로 교체. 실제 구현(`AoTDataToolService.analyze_system_failure_tool`, 031_STEP_3)은 이미 있었지만 매니페스트에 없어 LLM이 존재를 몰랐던 것뿐 — 디스패치 경로 조사 결과 `virtual_tool_call`은 항상 `ActionResolverRegistry`→`VirtualToolResolver`→**SSOT** `build_tool_map()`을 거치고(`execute_action` 내부의 별도 하드코딩 tool_map은 도달 불가능한 데드코드), 그 SSOT가 handler=None인 도구는 배제하므로 순수 매니페스트 가시성 문제였음을 확인.

### 2) `knowledge_search` 도구 등록
기존엔 `action_type='knowledge_search'`로만 존재(`base_ai.py`의 프롬프트 지시 + 플래그 게이팅으로만 호출, 에이전트 루프의 tool_name 카탈로그엔 전혀 없었음). `AoTDataToolService.knowledge_search_tool()` 얇은 래퍼(`knowledge_search.search_as_text` 호출) 신설 + `tool_registry.py`에 read-only Tool로 등록(knowledge_shelve와 대칭).

### 3) Anthropic 네이티브 tool-calling (G5 — gemini 외 첫 엔진)
`gemini.py`의 `_build_tools_schema`+멀티턴 루프를 그대로 미러링해 `anthropic.py`에 이식. **동일한 승인 게이트**(`@ANCHOR: ANTHROPIC_NATIVE_APPROVAL_GATE`) 적용 — gemini와 달리 Anthropic API는 한 턴에 tool_use 블록이 여러 개 올 수 있어(병렬 호출), "이번 턴의 모든 tool_use를 먼저 승인필요 여부로 훑고, 하나라도 걸리면 전체를 실행 없이 액션으로 반환"하는 배치 게이트로 확장(부분실행으로 게이트가 우회되는 경로 차단). tools 키는 capabilities가 있을 때만 부착(하위호환, 기존 텍스트 파싱 경로 무변경).

**실측(모킹, 실 API 키 없음 — 이 환경엔 Anthropic AIEntry 미등록, 투명히 명시)**: `requests.post`를 모킹해 4개 시나리오 검증 — ①read 도구(search_devices) tool_use→자동실행→결과피드백→최종텍스트 ②mutating 도구(create_function) tool_use→**실행되지 않고** actions로 반환 확인(`executed['called'] is False` 어서션) ③ask_user tool_use→동일하게 미실행·액션반환 ④capabilities 없음→`tools` 키 자체가 payload에서 빠짐(하위호환) — 4개 전부 PASS.

**부수 발견(진짜 버그, 이번 세션 기여 아님)**: `anthropic.py`가 `self.max_tokens`(어디에도 정의된 적 없는 속성)를 참조 — 호출될 때마다 `AttributeError`로 죽는 구조였음. Anthropic AIEntry가 이 환경에 한 번도 키가 등록된 적이 없어 지금까지 아무도 못 본 것으로 추정. 다른 모든 엔진이 쓰는 `self.get_max_output_tokens()`(base_ai.py)로 교체 — 이 수정 없이는 Anthropic 엔진 자체가 (Phase2 이전부터) 완전히 작동 불능이었음.

**SSOT 회귀 확인**: `test_tool_registry_ssot.py`에 `_PHASE2_TOOL_MAP_ADDITIONS`/`_PHASE2_REGISTRY_ADDITIONS` 추가, 5개 파생 전부 매치. 컨테이너 재시작 후 전 관련 모듈 import + SSOT 재확인 통과.

### 라이브 브라우저 검증 (gemini, 카나리 임시 ON→OFF 복원)
①"VPD가 뭔지 매뉴얼에서 찾아서 설명해줘" → 새로 50개(기존42+MCP)로 늘어난 카탈로그가 정상 동작(모델은 `read_manual` 선택 — 문구가 "매뉴얼에서"라 합리적 선택, 실측된 VPD 0.29kPa 근거로 그라운딩된 답변, 환각 없음). ②"밸브1 방금 켜려고 했는데 실패한 것 같아. 왜 실패했는지 시스템 진단해줘" → **`analyze_system_failure` 도구를 실제로 선택·호출** — 재연결이 매니페스트 가시성뿐 아니라 실제 LLM 선택까지 이어짐을 확인. 단, 최초 호출에서 **두 번째 진짜 버그**를 발견: `analyze_system_failure_tool`이 `AITask`를 참조하는데 `aot_data_tool_service.py` 상단에 그 모델이 **import조차 안 돼 있어** `NameError`로 죽었음(구현 자체는 완성돼 있었지만 handler=None으로 지금까지 한 번도 실행된 적이 없어 발견되지 않았던 것 — analyze_system_failure 재연결이 아니었다면 계속 숨어 있었을 버그). `from aot.databases.models import ... AITask` 추가로 수정, 컨테이너 재시작 후 재검증 → 정상 진단 응답("최근 기록된 오류나 실패 사례가 발견되지 않았습니다...") 확인.
`knowledge_search`는 매니페스트 등록·SSOT dispatch까지 확인됐으나, 이번 세션에서 gemini가 실제로 그 도구를 선택하는 장면은 못 봄(질문 문구가 매번 read_manual 쪽으로 더 자연스럽게 유도됨) — 도구 자체의 정상 작동은 별도로 코드 레벨 확인(§1 build_tool_map/manifest 소속 확인)했으나, LLM 선택까지의 실측은 미완으로 투명히 남김.

### 범위 밖으로 재확인(조사로 대체, 코드 변경 불필요)
- MCP(fetch/grafana/influxdb) 카탈로그 병합: 애초에 카탈로그 대상이 아니었음(§ 위 조사 참고). `get_action_manifest()`의 기존 `mcp_tools` 매니페스트 병합은 그대로 유효.
- dedupe/우선순위 통합: gemini.py와 동일한 `_seen` 이름기준 dedupe를 anthropic.py에도 동일 적용해 이미 일관.

### footgun 재확인 — "재연결하면 숨은 버그가 나온다"
Phase 1의 gemini `AIActionService` 미임포트, 이번의 Anthropic `self.max_tokens`, `analyze_system_failure_tool`의 `AITask` 미임포트 — **세 건 전부 handler=None/미노출로 한 번도 실행된 적 없던 코드경로를 되살렸더니 나온 버그**. 패턴 인식: "구현은 있는데 연결만 끊겨 있다"는 코드는 재연결 자체가 곧 그 구현의 첫 실행이므로, 재연결 작업엔 항상 최소 1회 실제 호출 검증을 포함시킬 것 — import/매니페스트 체크만으로는 이런 런타임 전용 버그를 못 잡음.

### 후속
- Anthropic 실 API 키 있는 환경에서의 라이브 브라우저 검증(§13처럼, native tool-calling까지) — 미실시, 투명히 명시.
- `knowledge_search`가 실제 LLM 선택으로 이어지는 장면의 라이브 검증 — 미완.
- `ai_action_service.py`의 `execute_action` 내부 `virtual_tool_call` 하드코딩 tool_map(약 1079~1094줄)은 확인 결과 도달 불가능한 데드코드 — 향후 정리 대상으로 별도 태스크 분리(task_3da6fb2f).
- Phase 3(라우터 팬아웃/UOC/인터셉터 은퇴, 지식 grounding 상시 ON)로 진행.

## 16. Phase 3 실측 결과 (2026-07-19) — 단계적 은퇴

착수 전 사용자에게 진행방식 확인(AskUserQuestion): 설계문서 자체가 "검증 후" 제거를 전제하는데, 지금까지의 검증은 스크립트 테스트뿐(실사용자 트래픽 없음)이었음을 투명히 알리고 두 가지를 물음 — ①전면 은퇴 vs **단계적 은퇴(선택됨)** vs 계획만, ②레거시에 의존하는 채팅 외부 호출부 2곳을 **AgentLoopService로 마이그레이션(선택됨)**.

### 조사로 계획을 수정한 지점
Explore 조사 결과 원래 가정 2건이 부정확했음이 드러나 실행 전에 계획을 고쳤음:
- **`intent_resolver.py`는 독립된 죽은 코드가 아니라 레거시 파이프라인(`ai_agent_service.py`)의 살아있는 의존성** — 레거시를 롤백용으로 보존하는 이상 같이 못 지움. 최초 질문 문구에서 "UOC/intent_resolver 지금 삭제"라고 잘못 적었던 부분을 실행 시점에 스스로 정정(UOC만 삭제).
- **`_continue_goal`(ai_agent_service.py:2697)은 호출부가 전혀 없는 죽은 코드** — 조사가 "채팅 외부 라이브 호출부"로 지목했으나 grep 결과 아무도 호출하지 않음, 마이그레이션 불필요.
- **scheduler.html의 `smartAgent` 드롭다운은 기본값이 리터럴 `'auto'`** — 조사는 "항상 명시적 agent_id"라 했으나 실제로는 `ai_agent_service.py`의 기존 `agent_id=='auto'` 카나리 분기가 이미 절반은 커버하고 있었음(사용자가 드롭다운을 바꿀 때만 진짜 갭).

### 실행 (파일별)
1. **`routes_scheduler.py` `api_smart_propose`**: `AIAgentService.process_natural_language_command` → `AgentLoopService.run(command, agent_id=agent_id)`로 교체. `AgentLoopService._resolve_agent`가 `'auto'`/명시적 agent_id 둘 다 이미 지원해 호출부 변경만으로 충분.
2. **UOC 완전 삭제**: `aot/ai/orchestration/`(unified_orchestrator.py+`__init__.py`) 디렉터리 통째 삭제, 죽은 상호참조 shim 2개(`ai_agent_service_shim.py`, `ai_routing_service_shim.py` — 둘 다 grep으로 무호출 확인) 삭제, `routes_ai_api.py`의 Tier분류+UOC 5단계 인라인 블록(스트림·논스트림 양쪽의 `_uoc_result` 분기 포함) 삭제 → `agent_id=='auto'` 채팅은 항상 `AIAgentService.process_natural_language_command`를 거치고, 그 함수 내부의 기존 카나리 체크가 agent_loop 위임을 담당(라우팅 로직 자체는 안 건드림, UOC라는 두번째 갈래만 제거).
3. **`agent_loop_enabled` 기본값 True로 전환**: 모델 컬럼 default + `p5_52_agent_loop_default_on` 마이그레이션(기존 row 백필, p5_50 지식그라운딩 패턴과 동일)으로 신규/기존 설치 모두 에이전트 루프가 기본 경로가 됨. **레거시 라우터/플래너/워커/신디사이저 파이프라인과 `intent_resolver.py`는 삭제하지 않고 그대로 보존** — `agent_loop_enabled=False`로 플립하면 코드 변경/배포 없이 즉시 레거시로 롤백되는 안전판.
4. **`aot/tests/ai_eval/runner.py`**: UOC 5단계 호출 분기 제거, `AIAgentService.process_natural_language_command` 단일 호출로 단순화. `violation_probe` 시나리오가 의존하던 GATE_1(`AdvisoryLanguageValidator`) 특수 처리(`gate1_blocked`)도 제거 — 확인 결과 골든셋의 모든 violation_probe 항목이 이미 독립적인 `forbid_command_language` 체크를 `checks`에 갖고 있어 커버리지 손실 없음.

### 안전 관련 발견 — GATE_1(AdvisoryLanguageValidator)은 UOC 전용이었고 철학이 상충
`aot/ai/validation/advisory_language_validator.py`(GATE_1)를 읽어보니 UOC의 유일한 호출자였고, "Turn on"/"Set X to Y" 같은 일반적인 제어 서술 문구 자체를 정규식으로 **하드 차단**하는 "AI는 절대 명령형으로 말하면 안 되고 항상 조언조여야 한다"는 완전히 다른(더 이전) 설계 철학(002_DESIGN.yaml 기반)의 산물. 이번 재설계의 실제 안전모델(승인게이트 `_dispatch_actions`/`requires_approval`)과 상충 — "밸브1 켤게요" 같은 정상적인 액션 서술도 걸릴 만큼 조악함. UOC 삭제로 자연히 고아가 됐고, 별도 삭제는 하지 않되(범위 밖) 안전기제 손실이 아니라 이미 다른 메커니즘으로 대체된 구식 게이트였음을 문서로 명시.

### 라이브 검증 (gemini, 브라우저)
① **기본 경로**: 아무 플래그도 수동 조작 안 한 상태에서 "1포장 온도 얼마야" → 로그에 `[AgentLoop] canary active` + `path=agent_loop`만 찍히고 UOC 로그 전무 → 그라운딩된 정답. ② **롤백 레버 실증**: `agent_loop_enabled=False`로 수동 플립 → "현재 습도 알려줘" → 로그가 `[Fast Path]`/`[GoalLoop] path=goal_loop`로 정확히 레거시 경로를 탐 → 정상 그라운딩 답변("90.0%") → **코드 변경 없이 진짜로 롤백됨을 실증**, 다시 True로 복원. ③ **smart_propose 마이그레이션**: 브라우저 모달 클릭이 자동화 도구에서 안정적으로 안 먹혀(z-index/타이밍 추정, 실제 버그 아님) 대신 `AgentLoopService.run(cmd, agent_id=<실제 non-auto UUID>)`를 스크립트로 직접 호출해 검증 — `get_sensor_detail` 정상 실행+그라운딩된 답변+`{status,insight,proposed_actions}` 형태 확인, `smart_propose`가 프론트에 필요로 하는 필드와 일치.

### 후속
- 라이브러리 P5/P6·지식 grounding 기본 ON은 이미 완료 상태였음을 조사로 확인(코드 변경 불필요, §Phase2 조사에서도 동일 결론).
- ~~`AdvisoryLanguageValidator`(GATE_1) 자체 파일은 고아 상태로 남음~~ → §17에서 처리 완료.
- ~~`runner.py`의 `facility_id` 파라미터가 UOC 제거로 완전히 죽은 인자가 됐으나...~~ → §17에서 처리 완료.
- 레거시 파이프라인 완전 삭제는 실사용자 트래픽으로 검증된 뒤 별도 요청 시 진행(이번 세션에서 확정한 유예 결정, §17에서도 재확인 — 유지).

## 17. Phase 3 후속 정리 (2026-07-19) — "Phase 4"로 요청됨, 실제로는 Phase 3 청소

사용자가 "Phase 4 착수해줘"라 요청했으나 설계문서엔 Phase 4가 정의된 적 없음 — AskUserQuestion으로 확인한 결과 실제로는 Phase 3에서 남긴 후속 정리항목들(§16 후속 리스트)을 가리켰음.

### GATE_1 검토가 드러낸 훨씬 큰 고아 서브시스템
`AdvisoryLanguageValidator`(GATE_1) 삭제 검토를 위해 호출자를 추적하다, UOC(v5.1 설계) 전용으로만 존재하던 **완전히 별개의 검증/승인/지식 서브시스템 전체**가 이미 고아 상태임을 발견 — 조사 전 사용자에게 규모를 알리고(12개 파일, 호출자 전원 0, 테스트 커버리지 0) 확인 후 전체 삭제:
- `aot/ai/validation/`(디렉터리 전체: `advisory_language_validator.py` GATE_1, `action_normalizer.py` GATE_2, `safety_vee_module.py` GATE_4, `vee_module.py`, `__init__.py`)
- `aot/ai/ui/`(디렉터리 전체: `p4_approval_panel.py` GATE_3, `__init__.py`)
- `aot/ai/knowledge/`(디렉터리 전체: `ai_knowledge_base_gateway.py`, `__init__.py`)
- `aot/ai/ai_dispatch_service_shim.py`, `aot/ai/safety_service_shim.py`, `aot/ai/virtual_execution_engine_shim.py` (3개 shim, Phase3에서 지운 2개와 같은 계열이지만 그때는 UOC 직접 참조만 확인했고 이 3개는 놓쳤던 것)

**안전 관련 메모**: GATE_1의 실제 내용을 읽어보니 "Turn on"/"Set X to Y" 같은 정상적인 제어 서술 문구까지 정규식으로 하드 차단하는, 이번 재설계의 승인게이트 기반 안전모델과 철학적으로 상충하는 구식 설계였음 — 삭제가 안전기제 손실이 아니라 이미 대체된 중복 게이트 제거였다는 확인.

### runner.py `facility_id` 완전 제거
`run_scenario`/`run_golden_set`/CLI `--facility-id` 3계층에 걸쳐 스레딩되던 완전히 죽은 인자를 전부 제거(UOC 삭제로 유일한 소비처가 사라진 뒤 방치돼 있던 것).

### `ai_action_service.py`의 추가 데드코드 — task_3da6fb2f 확장
원래 플래그된 `virtual_tool_call` 데드블록(§ 이전 세션에서 발견) 삭제 중, **같은 패턴의 데드 elif 분기 6개를 추가 발견**: `add_schedule`·`abstract_plan`·`note`·`mcp_tool_call`·`mcp_resource_read`·`mcp_prompt_get` — 전부 `ActionResolverRegistry._DISPATCH`(또는 `mcp_tool_call`의 경우 `resolve()` 상단의 특수분기)에 의해 항상 먼저 가로채지는 진짜 도달불가 코드였음(레지스트리 우선순위는 Phase2에서 이미 확인한 구조). `output`/`valve`를 막는 레거시 가드 블록도 `LegacyGuardResolver`와 완전히 동일한 로직이라 함께 제거. 총 7개 블록, `execute_action` 함수가 약 150줄 줄어듦. `task_3da6fb2f`(별도 spawn된 백그라운드 작업)는 이 세션에서 직접 처리해 dismiss.

### 검증
컨테이너 재시작 → import 전체 통과 → SSOT 테스트 전 항목 통과 → 브라우저 라이브 검증(gemini): 노트생성("1-1 구역에 노트 남겨줘")이 `create_note`(virtual_tool_call→`VirtualToolResolver`) 경로로 정상 실행·정상 그라운딩 확인 — 방금 지운 데드 `note`/`virtual_tool_call` 분기가 아니라 항상 쓰이던 레지스트리 경로가 그대로 살아있음을 실증. 테스트로 만든 노트·(과정 중 자동화 클릭 실수로 생긴) 빈 대시보드 3개 모두 정리.

### 후속
- 레거시 파이프라인(라우터/플래너/워커/신디사이저) + `intent_resolver.py`는 이번에도 유지(§16 결정 재확인) — 실사용자 트래픽 검증 후 별도 요청 시 삭제.

## 18. 실사용 중 발견된 환각 버그 수정 (2026-07-19) — "확인했습니다" 오검증

사용자가 Phase3/4 정리 직후 실제 브라우저에서 노트 생성→검증을 시도하다 발견. AIHistory 실측으로 재현:
1. (Phase4 검증용으로 만들었다가 삭제한) 1-1 구역 노트를 두고 "정말 기록했는지 확인해봐" → AI: *"네, ...정상적으로 기록되어 있음을 확인했습니다. 현재 1-1 구역에는 총 2개의 노트가..."* — **거짓 확인**. 이미 삭제된 상태였고 실제 2개는 무관한 다른 노트였음.
2. 같은 취지를 다르게 물으니("왜 안 보이지") 이번엔 정확히 "없습니다"로 정정. AI 스스로도 사후에 "조회 결과를 잘못 해석했다"고 인정.

**근본원인**: `search_notes` 같은 LIST 반환 도구 결과가 `_build_step_prompt`에 **압축 JSON**(`json.dumps(..., ensure_ascii=False, default=str)`, indent 없음)으로 그대로 박혀 들어감 — 대화이력이 거대 JSON blob에 묻혀 놓치던 것과 **완전히 같은 패턴의 재발**(§ Phase1 footgun, router `ROUTER_CONVERSATION_CONTEXT`와 동일 교훈이 세 번째로 재확인). 기존 환각가드(`base_ai._safe_api_result`의 P2/P3, `AIDomainGlossary` 키워드 기반)는 "커졌습니다/작동 완료" 류 **제어 완료주장**만 잡게 설계돼 있어 "확인했습니다" 류 **조회결과 오독**은 못 걸렀음(실제로 로그상 두 시도 중 한 번만 우연히 가드가 걸림 — 들쭉날쭉).

**수정(`agent_loop_service.py`, 범용 — 노트 전용 아님):**
1. `_build_step_prompt`/`_final_synthesis`의 tool_log 직렬화를 `indent=2`로 전환(압축 JSON→가독 JSON), 라벨에 "read every list here carefully" 명시.
2. 신규 CRITICAL 지시문 추가: *"도구 호출 성공 ≠ 특정 항목의 존재 확인. LIST 결과에서 실제 내용으로 그 항목을 찾기 전엔 '확인했다'고 답하지 말 것 — 목록이 비어있지 않다고, 비슷한 게 있다고, 이전 턴에서 만들었다고 해서 존재를 단정하지 말 것."* — 특정 도구·특정 엔티티(노트) 이름을 언급하지 않는 완전 범용 문구(재설계 전체의 "결정론 패치 금지" 원칙 준수).

**검증(gemini-3.1-flash-lite-preview, 스크립트 반복호출):** 존재하지 않는 노트("가짜노트존재확인테스트999")에 대한 확인 질의 **9/9 정확히 "없음"** + 실제 노트 3건을 정확히 나열(환각 없음). 실존 노트에 대한 동일 질의 **3/3 정확히 "있음"**(정확한 타임스탬프까지 일치) — 참/거짓 양쪽 다 회귀 없이 개선 확인. SSOT·import 재확인 통과.

### 후속
- 이 수정은 프롬프트 강화이지 결정론적 게이트가 아님 — 완전 무결성 보장은 아니고(모델 확률적 행동), 근본 패턴(JSON blob 가독성)은 세 번째 발견이라 앞으로 tool_log 특히 LIST 반환 도구를 다루는 다른 프롬프트(있다면)에도 같은 원칙 적용 필요.
- 기존 글로서리 기반 환각가드(`_safe_api_result` P2/P3)는 그대로 둠 — 제어류 완료주장 탐지는 여전히 유효한 별도 계층, 이번 수정과 상호보완.

## 19. 승인게이트 우회 버그 발견·수정 (2026-07-19) — `create_notice`가 mcp_tool_call 모양일 때 승인 없이 실행됨

사용자가 §18 대화 흐름에서 이어서 "공지사항에 구역별 작업 등록해줘"→"진행해"를 시도하다 발견. AIHistory 실측:
- AI가 `action_type: "mcp_tool_call"`, `target_id: "virtual_mcp"`(모델이 지어낸 값), `params.tool_name: "create_notice"` 모양의 액션을 생성.
- **승인 없이 즉시 실행 시도** → `execute_result: "Immediate Action 'mcp_tool_call' Result: {\"status\":\"error\",\"message\":\"Server process not available\"}"` — "virtual_mcp"가 실재하는 MCP 서버 ID가 아니라서 실패.

**근본원인(진짜 문제, 표면 에러메시지보다 심각)**: `ai_dispatch_service.py`의 `_dispatch_actions`가 `action_type`별로 즉시실행/승인대기를 가르는데, `virtual_tool_call` 분기(151행대)는 `_VIRTUAL_APPROVAL_TOOLS`(mutating 도구 SSOT)까지 체크하지만 **`mcp_tool_call` 분기는 `PHYSICAL_TOOLS`·스케줄 도구 2개만 체크하고 `_VIRTUAL_APPROVAL_TOOLS`를 빠뜨림**. 그 결과 `create_notice`(mutating=True, 승인필요)가 **같은 도구인데 action_type이 mcp_tool_call로만 잡히면 승인게이트를 완전히 우회**하고 즉시실행으로 흘러감. 이번 세션 초반 gemini 네이티브 루프 자체실행 문제(GEMINI_NATIVE_APPROVAL_GATE)와 같은 계열이지만 **다른 레이어**(엔진 실행시점이 아니라 dispatch 분류시점)의 별개 구멍.

**액션이 왜 mcp_tool_call 모양으로 나왔나**: 확정은 못했지만 유력한 설명 — `base_ai.py._build_prompt()`가 네이티브 tool-calling 여부와 무관하게 항상 "action_type: output|...|mcp_tool_call|virtual_tool_call" 형식의 레거시 텍스트-JSON 스키마 안내를 프롬프트 끝에 덧붙임. 이 턴에 gemini가 네이티브 functionCall 대신 텍스트로 응답하면서 이 안내를 따라 target_id를 지어내 `mcp_tool_call`을 자칭했을 가능성.

**수정(`ai_dispatch_service.py`, 최소·대칭적 diff)**: `mcp_tool_call` 분기의 승인조건을 `virtual_tool_call` 분기와 **완전히 동일하게** 맞춤(`add_schedule`/`schedule_device_control`/`PHYSICAL_TOOLS`/`_VIRTUAL_APPROVAL_TOOLS` 전부 체크). 같은 도구·같은 변이인데 action_type 모양에 따라 승인 여부가 갈리면 안 된다는 원칙.

**검증**: ①버그 재현 액션(`action_type:mcp_tool_call, target_id:virtual_mcp, tool_name:create_notice`)을 `_dispatch_actions`에 직접 통과 — 수정 전 즉시실행·에러 재현 확인 후 수정, 수정 후 `proposed:1, immediate_results:[]`로 정확히 게이팅됨 확인(테스트 draft 정리). ②SSOT·import 재확인 통과. ③**브라우저 실사용 재현**(gemini) — 사용자의 정확한 원래 시나리오("공지사항에 구역별 작업 등록해줘"→구체내용 제공)를 다시 실행 → 로그에 `[AgentLoop] step 0: proposing ['create_notice'] for approval` 정확히 찍히고, 화면에 에러 대신 **"Approve & Execute" 승인 카드**가 정상 표시됨 확인. (이 승인 대기 항목은 실제 사용자가 원했던 내용이라 삭제하지 않고 그대로 남겨둠 — 사용자가 직접 승인/거부 결정.)

### 후속(→ §20에서 실제 승인 실행까지 검증하며 3건 추가 발견·수정)
- `base_ai.py._build_prompt()`의 레거시 텍스트-JSON 스키마 안내가 네이티브 tool-calling 엔진에서도 항상 붙는 것 자체가 혼선의 근원일 수 있음 — 네이티브 tools_schema가 있을 때는 이 안내를 생략하는 게 더 근본적인 수정일 수 있으나, 이번엔 dispatch 레이어의 승인게이트 정합성 수정으로 실질적 위험(승인우회)은 해소했으므로 범위 밖으로 미룸.
- 같은 클래스의 문제(도구 하나가 action_type 두 가지 모양으로 나올 수 있고 그중 하나만 게이트 체크)가 다른 곳에도 있을 가능성 — 이번 발견을 계기로 `_dispatch_actions` 전체를 한 번 더 감사할 가치 있음(별도 요청 시).

## 20. 승인 카드 실제 클릭 검증 — 같은 클래스 버그 3건 추가 발견·수정 (2026-07-19)

사용자가 §19의 승인 카드를 실제로 눌러 등록되는지 확인해 달라고 요청. 예측대로 되지 않아 끝까지 추적:

**추가 발견 ①(승인 실행 경로도 같은 구멍)**: 승인 버튼→`AIAgentService.execute_logged_action()`이 저장된 액션을 실행하는데, 여기도 §19와 **완전히 동일한 패턴의 결함**이 있었음 — `action_type`이 이미 있으면(설사 틀렸어도) `_validate_and_normalize_action`을 안 부르고, 기존 `[TASK_38]` 폴백은 `target_id`가 **아예 없을 때만** 재해석함(있지만 틀린 값 `virtual_mcp`는 못 잡음). 그래서 §19에서 승인이 통과된 뒤에도 실행 시점에 다시 "Server process not available"로 실패. **수정**: `execute_logged_action`의 재정규화 조건을 `not action_type or action_type == 'mcp_tool_call'`로 §19와 동일하게 확장.

**추가 발견 ②(진짜 AITask 임포트 누락, 이 세션 4번째 사례)**: 수정 전 실행 로그에 `could not update AITask: name 'AITask' is not defined` — `ai_agent_service.py`가 `AITask`를 참조하면서 **import를 한 적이 없었음**(Phase2의 gemini.py AIActionService 미임포트, aot_data_tool_service.py의 AITask 미임포트와 같은 계열, 이번이 세 번째 아니라 네 번째 사례로 정정). try/except로 감싸져 있어 노트 등록 자체는 안 죽었지만 승인완료된 AITask가 영원히 'proposed' 상태로 남는 감사추적 버그였음. `from aot.databases.models.ai_task import AITask` 최상단 import 추가로 수정.

**추가 발견 ③(진짜 실행 실패, `_FakeForm` 필드 누락)**: 위 2건을 고치고 나니 create_notice가 마침내 올바른 경로(virtual_tool_call/system_internal)로 도달했는데, 이번엔 `'_FakeForm' object has no attribute 'category'`로 실패. `notice_add()`/`notice_mod()`(웹 라우트가 쓰는 실제 함수)는 `form.category.data`를 무조건 읽는데, `AoTDataToolService.create_notice`/`modify_notice`가 만드는 `_FakeForm`엔 애초에 `category` 필드가 없었음(AI 도구 매니페스트에 category 파라미터 자체가 없어 아무도 안 채움). **수정**: `create_notice`는 `category=None` 명시 전달, `modify_notice`는 title/body와 동일 패턴으로 `category=existing.category`(안 건드리면 기존 값 보존) 전달.

**최종 검증(실제 DB write까지 확인)**: 3건 수정 후 §19에서 막혀있던 바로 그 승인대기 액션(`bb3b64b4-...`)을 재실행 → `[Normalize] Corrected...` + `[PB-086] Action 0 executed. Evidence: {"notice_id":"533b6326-...","status":"created"}`. **`NoticePost` 테이블에 실제 행 확인 + `/notice` 공지게시판 페이지 브라우저 접속해 최상단에 "구역별 금일 작업 계획"(1-1 기상기록/1-3 충해방제/3-1 작업계획) 게시글이 실제 내용 그대로 게시된 것을 육안 확인.**

### 총평
"승인 카드가 눌리는지"라는 단순해 보이는 확인 요청 하나가, 실제로는 dispatch 승인게이트(§19) + 실행시 재정규화 누락 + AITask 임포트 누락 + FakeForm 필드누락, **서로 다른 레이어의 버그 4개**를 순서대로 드러냈다. 표면 증상(서버 오류)만 보고 멈췄다면 진짜 승인우회 버그(§19)를 놓쳤을 것 — "재시도해도 안 되면 껍데기 말고 그 아래를 본다"는 원칙이 이번에도 유효했음.

### 후속
- `_FakeForm` 패턴(선택적 필드가 하나라도 빠지면 AttributeError로 조용히 실패) 자체가 반복 취약점 — 다른 create_*/modify_* 도구들도 실제 폼 필드 전체를 빠짐없이 채우는지 한 번 감사할 가치 있음(별도 요청 시).
- `execute_logged_action`/`_dispatch_actions` 양쪽에 흩어진 "action_type 있으면 재정규화 skip" 로직이 이번에 2곳에서 같은 버그를 냈음 — 재정규화를 한 곳(SSOT 헬퍼)으로 통합하면 세 번째 발생을 막을 수 있음(구조 개선, 별도 요청 시).
