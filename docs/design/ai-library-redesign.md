# AI 라이브러리 재설계 — 통합 지식 저장소 (Agentic Knowledge Store)

작성: 2026-07-18 (rev.2). 단일 기준 문서.

**핵심 전환(rev.2):** 라이브러리를 "외부 권위 지식 채널"로 좁히려던 rev.1을 폐기한다.
AoT는 GIS·시설 기반 **범용** IoT 플랫폼이라 관리 대상은 작물·축산·도로·철도·시설
무엇이든 될 수 있고, 사용자 자신도 무엇을 관리하게 될지 미리 모르는 경우가 많다.
따라서 라이브러리는 **도메인 불가지(domain-agnostic)** 하고, **AI가 필요에 따라 유용한
정보를 스스로 비치(write)하고 찾아 쓰는(read)** 유기적 저장소여야 한다.

설계 원칙 한 줄: **"외부 권위 지식"과 "AI 운영기억"은 별도 시스템이 아니라, 출처
(provenance)만 다른 하나의 저장소다.** 작물·가축·교량은 도메인 스키마가 아니라 태그/
엔티티 링크일 뿐이다.

---

## 1. 무엇을 만드는가

**AI 라이브러리 = AI가 읽고 쓰는 도메인 불가지 지식 저장소.**

- **읽기**: AI가 답변·판단 근거로 관련 지식을 검색해 주입.
- **쓰기**: AI가 작업 중 유용하다고 판단한 정보(외부 조회 결과, 추론 산물, 사용자 발화
  중 확정 사실, 시스템 텔레메트리에서 도출한 패턴)를 저장소에 비치.
- **성장**: 사용자가 사전에 도메인을 선언하지 않아도, 쓰이면서 유기적으로 축적.

이 구조에서 rev.1의 "외부 권위 지식(RDA 설정값·재배 가이드·병해충)"은 **provenance=
external_authority 인 항목들의 한 부류**로 흡수된다. 특별 취급이 아니라 최고 신뢰
출처일 뿐.

---

## 2. 통합 지식 항목 모델

모든 지식은 provenance·형태가 달라도 **하나의 항목 스키마**로 표현한다.

| 필드 | 의미 | 예 |
|---|---|---|
| `content` | 지식 본문 (구조화 JSON 또는 산문 digest) | `{opt_temp:[18,26]}` / "장마철 배수 점검…" |
| `content_kind` | `structured` \| `prose` | 조회·주입 형식 분기 |
| `provenance` | 출처 부류 (신뢰 등급의 근거) | §3 |
| `trust_state` | 신뢰 상태 (주입 가중치·플래그) | §3 |
| `tags` | 자유 태그 (도메인 불가지 스코프) | `tomato,flowering` / `railway,bridge-A` / `축산,환기` |
| `entity_ref` | AoT 엔티티 링크 (선택) | site/zone/device/facility unique_id |
| `attribution` | 출처 표기 (감사·인용용) | "RDA SmartFarm API" / "대화 2026-07-18" / "텔레메트리 분석" |
| `source_id` | 등록 소스 FK (외부 피드일 때) | `AIContextSource` |
| `freshness` | `created_at`/`updated_at`/선택 `ttl` | 병해충 경보는 TTL 있음 |
| `content_hash` | 중복제거·모순탐지 키 | sha256 |
| `is_enabled` | 소스/항목 활성 | |

`content_kind`로 형태를 가른다(rev.1의 source_type 분기 폐기):
- **structured**: 작물×단계 설정값처럼 정규 구조. 조회=키 매칭, 주입=구조 블록. 절대
  평면 문자열로 shred하지 않는다.
- **prose**: 가이드·경보·AI 정리 노트. 조회=태그 필터+키워드/의미 검색, 주입=섹션 블록.

---

## 3. Provenance & 신뢰 거버넌스 (핵심)

AI가 쓰기 때문에 **오염 방지가 저장소의 생사를 가른다.** rev.1에서 삭제하려던 신뢰상태
기계를 여기서 **되살려 코어로 삼는다** — 단, 막다른 길이던 승격 경로를 채운다.

### 3.1 Provenance → 기본 신뢰

| provenance | 뜻 | 기본 trust | 주입 |
|---|---|---|---|
| `external_authority` | RDA·Nongsaro·NCPMS 등 권위 기관 피드 | 높음 | 전량 인용, 리뷰 불필요 |
| `user_provided` | 사용자가 대화/업로드로 확정한 사실 | 높음 | 전량 |
| `data_derived` | 시스템 텔레메트리에서 도출 (예: 밸브 응답시간) | 중간 | 인용, "관측 기반" 표기 |
| `ai_curated` | AI가 추론/외부조회로 정리해 비치 | **낮음(미확인)** | 사용 가능하나 "AI 정리·미확인" 플래그, 낮은 가중치 |

### 3.2 신뢰상태 전이 (승격 경로 = rev.1의 빠진 조각)

```
ai_curated (system_generated)
   ├─ 사용자 확인/수정         → user_confirmed   (최고 신뢰)
   ├─ 권위 소스와 교차일치      → corroborated     (승격)
   ├─ N회 재사용·무반박        → corroborated     (사용 신호 기반 자동 승격)
   └─ 사용자 반박 / 모순 탐지   → retired          (주입 제외, 이력 보존)
```

- **핵심 규칙: ai_curated 는 절대 authoritative 를 덮어쓰지 않는다.** 같은 주제에
  권위 항목이 있으면 그것이 이기고, AI 정리본은 보조로만 주입.
- 승격은 있어도 **리뷰가 주입의 전제는 아니다.** AI 정리본은 낮은 가중치로 즉시
  사용 가능(리뷰 UI 부재로 전 지식이 소멸하던 rev.0 트랩 방지).
- `attribution`으로 항상 출처 추적 가능 → AI가 "이 값은 RDA 권위 / 이건 제가 정리한
  미확인 사항"을 구분해 인용.

### 3.3 오염 방지 장치

- `content_hash` 중복제거 + 유사 주제 **모순 탐지**(같은 태그·엔티티에 상충 수치 →
  플래그, 낮은 신뢰끼리면 retire 후보).
- 휘발성 지식 TTL(경보·시세 등) → 만료분 주입 제외.
- AI 쓰기 쿼터/속도 제한(무한 적립 폭주 방지).
- 경량 리뷰 서피스(비차단): "AI가 최근 비치한 항목" 목록에서 확인/수정/폐기.

---

## 4. AI 접근 인터페이스 (2 동사)

기존 `knowledge_search` action_type를 확장하고 쓰기 동사를 신설한다.

- **`knowledge_search(query, tags?, entity_ref?, top_k)`** — 읽기.
  후보 = 태그/엔티티 필터 통과분 + 전역 매뉴얼. 스코어 = 키워드(현행) → 후속 의미검색.
  결과에 provenance·trust·attribution 동반 → 주입 시 신뢰 구분 표기.
- **`knowledge_shelve(content, content_kind, tags, entity_ref?, attribution, ttl?)`** —
  쓰기. AI가 유용 정보를 비치. provenance는 호출 맥락에서 결정(외부조회→
  external_authority면 소스경유, AI추론→ai_curated). 항상 `ai_curated` 이하로 진입,
  §3.2로만 승격.

쓰기 게이팅 **[결정: 자율 쓰기]**: AoT의 승인게이트 문화상 **물리 제어는 항상 승인**
이지만, 지식 비치는 부작용이 낮으므로 **AI 자율 쓰기를 허용**한다. 안전은 사전 승인이
아니라 §3.3 거버넌스(항상 ai_curated 이하 진입·낮은 가중치·모순/중복 차단·쿼터·비차단
리뷰)로 사후 확보한다. 유기적 성장이 매번 확인 마찰보다 우선.

---

## 5. 도메인 불가지 스코핑 — 태그 + 엔티티

rev.1의 "작물 축"을 폐기. 스코프는 두 축의 결합:

1. **자유 태그**: AI/사용자가 쓰기 시 부여. 작물·가축·시설 종류가 전부 여기로 수렴.
   "무엇을 관리할지 모름"에 대응 — 미리 스키마를 강제하지 않고 쓰이며 태그가 생김.
2. **엔티티 링크(선택)**: AoT GIS 엔티티(site/zone/device/facility)에 지식을 결부.
   "이 교량 센서군에 대한 지식", "3번 존 환기 특성" 등. AoT는 이미 **노트가 엔티티
   링크**(target_id==unique_id, per-entity) 패턴을 쓰므로 이를 정렬·재사용.

검색 시 현재 맥락(열린 지도 뷰포트의 site/zone, 대화 대상 장치)에서 관련 태그·엔티티를
유도해 후보를 좁힌다. rev.1의 `facility_id` 하드 스코프는 폐기(엔티티 링크가 더 일반적).

노트 관계 **[결정: 검색만 합류]**: AoT엔 이미 **semantic notes = "confirmed
knowledge/decisions"** 경로가 있다(`ai_context_service.get_global_decisions`). 라이브러리는
노트 저장/UX를 건드리지 않고 **`knowledge_search`가 노트+라이브러리를 함께 검색**한다.
항목 모델 일원화는 하지 않는다(노트=사람이 남긴 결정지식, 라이브러리=AI 큐레이션 —
두 저장소 이원 유지). 이유: 노트 UX 파급을 피하고 재설계 범위를 좁게. 검색 계층에서만
provenance를 부여해(노트→`user_provided`) 통합 결과로 표기.

---

## 6. AI 주입 — provenance 구분 grounding

`_manual_grounding`(서버측 결정적 주입) 패턴을 통합 저장소로 확장.

- 트리거: 발화가 특정 주제/엔티티를 건드릴 때(현행 키워드 게이팅 재사용).
- structured 주입: 관련 태그/엔티티의 구조 항목을 블록으로.
  ```
  [권위 — RDA SmartFarm, tomato/flowering, 갱신 2026-07-18]
  온도 18–26°C · 습도 60–80% · CO2 400–800ppm
  [AI 정리 — 미확인, 대화 2026-07-10]
  이 농장 3번 존은 오후 습도 급상승 경향 …
  ```
- 신뢰 구분 표기 필수 — AI가 권위/관측/미확인을 나눠 인용하도록.
- TTL·모순 플래그 항목은 주입 시 반영(만료 제외, 상충 시 고신뢰 우선).
- 플래그 정책: 활성 지식이 있으면 **주입 기본 ON**(rev.0의 "동작하는 척" 해소).

---

## 7. 현 자산 처리 (2026-07 실측 기준)

### 재사용
- `AIContextSource` + CRUD + 스케줄러 sync 잡 — 외부 피드 등록·주기 fetch 골격.
- ext 클라이언트 3종 + **구조화 캐시 테이블**(`ext_smartfarm_setpoints` 등, crop×stage
  정규 구조·TTL) — external_authority·structured 항목의 fetch 계층으로 유지.
- markdown 매뉴얼 결정적 검색 — 전역 지식으로 유지.
- `AIKnowledgeChunk` + `context_state` — **폐기가 아니라 §2 통합 항목 모델의 기반으로
  진화**(provenance·tags·entity_ref·attribution 필드 추가). rev.1의 삭제 판단 철회.
- `AILibrarySyncLog` — 감사 유지.

### 수정
- ext `sync()`의 "AIContextRecord 평면 문자열 bridge" 폐기 → structured 항목은 캐시
  테이블 직접 조회(구조 보존).
- `knowledge_search`: facility_id 하드필터 → 태그/엔티티 필터, trust/provenance 동반.
- `knowledge_chunk_confirmed_only` 의미 재정의: "리뷰=주입전제"가 아니라 §3.2 신뢰
  가중치. 켜도 전 지식 소멸하지 않도록.

### 신설
- 통합 항목 스키마 필드(§2), provenance/trust 전이(§3), `knowledge_shelve` 동사(§4),
  경량 리뷰 서피스, 모순/중복 거버넌스(§3.3).

---

## 8. UI

라이브러리 페이지 = **"지식 저장소 관리"**:
- 외부 피드 카드(연결·API 키·sync 상태) — external_authority 소스.
- **AI가 비치한 항목 목록** — provenance·trust·attribution·태그 표시, 확인/수정/폐기
  (비차단 리뷰).
- 태그/엔티티 필터 브라우징, 모순 플래그 표시.
- API 키는 기존 `APIKey` 저장소 참조(raw 직접입력 금지).

---

## 9. 스키마 / 마이그레이션

- `AIKnowledgeChunk` 확장: `provenance`, `tags`, `entity_ref`, `attribution`,
  `content_kind`, `ttl` 컬럼 추가. `context_state`는 §3.2 상태값으로 확장.
- external_authority structured 항목은 캐시 테이블(불변) + 조회 헬퍼로 노출 — 반드시
  청크 테이블에 사본을 둘지, 조회 시 어댑터로 통합할지는 구현 결정(경량 어댑터 우선).
- semantic notes는 모델 정렬 없음(검색 계층 합류만, §5) — 노트 스키마 불변.
- 하드코딩 `crop_type or 'tomato'` 제거.

---

## 10. 단계별 실행 계획

| 단계 | 내용 | 검증 | 상태 |
|---|---|---|---|
| P1 | 통합 항목 스키마(§2) + provenance/trust(§3.1) — 읽기 경로부터 | 유닛: 항목 CRUD·필터 | **완료** (2026-07-18) |
| P2 | `knowledge_search` 확장(태그/엔티티/trust 동반) + provenance 구분 주입(§6) | 로컬: 권위/미확인 구분 인용 | **완료** (2026-07-18) |
| P3 | external_authority structured 캐시 직접조회 어댑터(§7) | 로컬: "…설정값?" 구조 정답 | **완료** (2026-07-19) |
| P4 | `knowledge_shelve` 쓰기 동사(§4) + §3.3 거버넌스(중복·모순·쿼터) | 로컬: AI 비치→재검색→주입 | **완료** (2026-07-19) |
| P5 | 신뢰 승격 전이(§3.2) + 경량 리뷰 UI(§8) | 브라우저 실측 | **완료** (2026-07-19) |
| P6 | 폐기 정리, 플래그 기본 ON, semantic notes 검색 합류 | 회귀: 매뉴얼 검색 불변 | **완료** (2026-07-19) |

P1/P2 구현 메모(2026-07-18):
- 스키마: `aot/databases/models/ai_knowledge_chunk.py` (provenance/tags/entity_ref/
  attribution/content_kind/ttl 추가). 마이그레이션 `p5_47_knowledge_item_provenance`
  (p5_46 뒤에 체결, 기존 행 backfill).
- 쓰기: `context_source_service._write_knowledge_chunks`가 provenance='user_provided'/
  content_kind='prose'/attribution을 스탬프(유일한 현재 writer).
- 읽기: `knowledge_search.search()`/`search_as_text()`에 선택적 `tags` 파라미터 추가
  (무전달 시 기존 farm-wide 동작 그대로, 하위호환 확인됨), ttl 만료 필터, 결과에
  provenance/trust_state/attribution 노출.
- 주입: `search_as_text()`가 provenance별 인용 태그(`[권위]`/`[Library]`/`[관측]`/
  `[AI 정리 — 미확인]`) 부여, `ai_agent_service._MANUAL_GROUNDING_DIRECTIVE`가 태그별
  인용 방식을 모델에 지시(미확인 항목은 사용자에게 미확인임을 먼저 밝히도록).
- 검증: `aot/tests/test_knowledge_library_p1.py` 7건 전부 통과(도커 컨테이너 내
  in-memory sqlite, 라이브 DB 미접촉). 마이그레이션은 alembic ScriptDirectory로
  read-only 체인 검증(단일 head 확인, DB 미접촉).
- 미해결(P2 시점): external_authority/ai_curated provenance는 스키마·포맷팅 경로만
  준비됨 — 실제 writer는 아직 없음. → **P3에서 external_authority 해소.**

P3 구현 메모(2026-07-19):
- `knowledge_search._load_external_authority_sections()` 신설 — `ext_smartfarm_setpoints`
  /`ext_nongsaro_guides`/`ext_pest_alerts` 3개 캐시 테이블을 직접 ORM 조회, `_load_library_
  sections()`와 동일한 dict 셰이프(origin/tags/provenance/ttl 등)로 변환해 `search()`의
  태그·TTL 필터·`search_as_text()`의 인용 태그를 그대로 재사용. SmartFarm 8개 필드는
  **한 구조 블록**으로 합성(예: "온도 18–26°C · 습도 60–80% · CO2 400–800ppm") — rev.1에서
  진단한 "AIContextRecord 8행 shred" 문제의 실제 수정. crop_type/growth_stage(또는
  guide_type/pest_code)가 그대로 태그가 됨(§5 도메인 불가지 원칙 그대로 적용). 병해충
  경보만 6시간 TTL 적용(fetched_at 기준, 013_DATA_SOURCES.yaml 명시값) — 나머지 두 피드는
  만료 없음(정적 농업 상수/가이드이므로).
- get_setpoints()/GrowthStageResolver/env_coordinator 제어 경로는 전혀 손대지 않음 —
  get_setpoints()는 캐시 미스 시 네트워크 재조회를 트리거하는 부수효과가 있어 검색-시점
  경로에 부적합하다고 판단, 캐시 테이블을 별도 read-only로 직접 조회.
- **설계 이탈(의도적)**: §7/§10이 지시한 "ext sync()의 AIContextRecord bridge 제거"는
  **보류**했다. 이유: `context_metadata_builder.py`가 `AIContextRecord`를 facility_id로
  필터링해 `get_master_context()`의 `context_metadata.per_parameter`에 주입하는 **살아있는
  소비 경로**(tier≠lightweight 및 로그인 사용자 facility_id 존재 시 작동)를 확인함 —
  bridge를 제거하면 이 경로가 정보를 잃는 실제 회귀가 된다. P3는 대신 **순수 추가
  (additive)** 방식으로: 기존 shred bridge는 그대로 두고, `knowledge_search`(AI 답변
  근거 경로)에만 새 구조화 어댑터를 병행 추가했다. 부작용: 같은 정보가 두 경로
  (`context_metadata.per_parameter`의 개별 flat 값 vs `manual_reference`의 통합 구조
  블록)에 중복 존재할 수 있음 — 기능적 충돌은 아니나 향후 bridge 제거 시 재검토 필요.
- 검증: `aot/tests/test_knowledge_library_p1.py`에 P3 케이스 5건 추가(구조 정답 단일화,
  crop/stage 태그 스코핑, 가이드 prose 노출, TTL 만료/유효 배제·포함) — 전체 12/12 통과.

P4 구현 메모(2026-07-19):
- `knowledge_shelve_service.shelve_knowledge()` 신설 — 항상 `provenance='ai_curated'`,
  `context_state='system_generated'`(최저 신뢰)로 기록, 신뢰 승격은 하지 않음(P5 몫).
  §3.3 거버넌스 중 P4 스코프(중복·쿼터·모순플래그)만 구현, **승격/자동폐기 전이(§3.2)와
  리뷰 UI는 P5로 명시적으로 남김**:
  - 중복: content_hash 동일 시 재작성 없이 기존 chunk_id 반환.
  - 쿼터: `provenance='ai_curated'` 24시간 롤링 카운트, 기본 50건 초과 시 거부.
  - 모순 플래그: 동일 태그+동일 제목(정규화)+다른 내용의 **peer-trust**(ai_curated/
    data_derived) 기존 항목이 있으면 신규 컬럼 `flagged_reason`에 기록 — 차단이나 자동
    폐기는 하지 않음(둘 다 검색 가능한 채 남음, P5 리뷰 대상). external_authority/
    user_provided와의 충돌은 여기서 플래그하지 않음(인용 시점 우선순위로 이미 처리, P2).
  - 태그 필수화: `tags`가 비면 거부 — 무태그 ai_curated 항목이 전 쿼리에 노출되는 걸
    방지(§2의 "무태그=항상 후보" 규칙은 고신뢰 항목 전제였음, AI 저신뢰 쓰기엔 안전하지
    않다고 판단해 이 쓰기 경로에만 추가 제약).
- 스키마: `flagged_reason`(Text, nullable) 컬럼 추가, 마이그레이션
  `p5_48_knowledge_chunk_flagged_reason`(p5_47 뒤 체결, 단일 head 확인).
- `source_id` NOT NULL FK 문제 해결: shelve 글은 등록된 외부 소스가 없으므로, 마이그레이션
  없이(FK 완화 대신) **예약된 단일 `AIContextSource`**("AI 자율 비치") 를 get-or-create해
  귀속. `sync_interval_min=0`으로 스케줄러가 이 소스에 sync job을 절대 등록하지 않음
  (`ai_scheduler_service.py`의 `if interval_min <= 0: continue` 재사용) — 실수로 주기
  동기화가 도는 일 없음.
- 모델 호출 도구화: `tool_registry.py`에 `Tool('knowledge_shelve', ...)` 1건 추가
  (`create_note` 선례를 그대로 따름 — **`mutating=True`를 의도적으로 생략**해 승인게이트
  대상에서 제외, 결정 #1 "AI 자율 쓰기"의 실제 구현). 핸들러는
  `aot_data_tool_service.AoTDataToolService.knowledge_shelve`(파라미터: content/tags 필수,
  heading/attribution/entity_ref/content_kind/ttl_hours 선택 — attribution 생략 시
  서버시계 기준 날짜로 기본값 생성, LLM이 날짜를 추측하게 두지 않음). SSOT 특성화
  테스트(`test_tool_registry_ssot.py`)에 `_KNOWLEDGE_SHELVE_TOOL_ADDITIONS` 추가해
  tool_map/registry엔 있으나 두 승인셋 어디에도 없음을 명시적으로 고정.
- 검증: `aot/tests/test_knowledge_shelve_p4.py` 신설, 12건(쓰기 불변식, 소스 재사용,
  태그/내용 필수, 중복·쿼터·모순플래그, shelve→search 왕복 인용, 도구 매핑·승인제외
  확인, 핸들러 종단간 attribution/ttl_hours 변환) 전부 통과. 기존 P1-P3(12건)+P4(12건)
  =24건 전체 재실행 통과, SSOT 레지스트리 테스트 통과, 마이그레이션 체인 단일 head
  재확인. 라이브 DB 미접촉.

P5 구현 메모(2026-07-19):
- **자동 전이 스코프를 의도적으로 좁힘** — §3.2 다이어그램의 4개 분기 중 사람 주도
  확인/수정(→user_confirmed)·폐기(→retired) 2개만 실제 자동화하고, 나머지 2개("권위
  소스와 교차일치"→corroborated, "모순 탐지"→retired)는 **자문(advisory) 배지로만**
  구현: 제목이 같다고 내용이 실제로 일치/상충한다는 보장이 없어(의미비교 불가), 자동
  승격/자동폐기는 틀린 쪽을 승격하거나 맞는 쪽을 폐기할 위험이 있다고 판단. 사람이
  배지를 보고 최종 결정. 유일한 완전자동 전이는 "N회 재사용·무반박→corroborated"
  (의미판단 불필요, 재사용 횟수만이 근거).
- **캐시 무효화 회피**: 재사용 카운트 증가는 raw SQL(`UPDATE ... SET reuse_count =
  reuse_count + 1`)로 ORM `onupdate=updated_at` 훅을 우회 — 매 검색 히트마다
  `updated_at`이 갱신되면 `knowledge_search`의 `max(updated_at)` 기반 프로세스 캐시가
  검색할 때마다 깨져 캐싱 자체가 무의미해짐. 실제 신뢰상태 전이(드물게 1회)만 정상
  ORM 경로로 커밋해 그때만 캐시 무효화. 유닛테스트로 "캐시 stamp 불변" 명시 검증.
- **버그 발견 및 수정**: 브라우저 실측 중 발견 — 인용 태그(`_PROVENANCE_TAG`)가
  `provenance`(불변)에만 의존해, 사람이 확인(confirm)한 ai_curated 항목도 영원히
  "[AI 정리 — 미확인]"로 인용되는 버그. `_AI_CURATED_TRUST_TAG`(system_generated/
  user_confirmed/corroborated → 각각 다른 태그)로 분리해 trust_state를 반영하도록
  수정, `_MANUAL_GROUNDING_DIRECTIVE`도 3가지 신규 태그의 인용 방식을 모델에 지시하도록
  갱신. 회귀 테스트 2건 추가.
- **source_id FK 정합성**: P4의 예약 소스("AI 자율 비치")가 일반 소스 목록에 섞여
  "활성화" 버튼이 뜨는 게 혼란을 줘, `page_ai_library`/`api_list_sources`에서
  `source_type != 'ai_curated'` 필터로 제외(리뷰 섹션이 그 역할을 대신함).
- UI: `ai_library.html`에 "AI-Curated Knowledge Review" 섹션 추가(기존 gridstack
  엔트리 스타일 재사용) — 상태 배지(미확인/확인됨/교차검증/폐기), 모순 플래그·권위
  일치 배지(title 툴팁), 확인/폐기/재활성 버튼, 편집 모달(제목/태그/내용). 라우트
  5개(`review` GET/`confirm`/`edit`/`retire`/`reactivate` POST) 추가, 기존
  `edit_settings` 권한 게이트 재사용.
- **알렘빅 상수 함정 실측 재확인**: `alembic_upgrade_db()`가 실제 스크립트 head가
  아니라 `aot/config/__init__.py`의 하드코딩 `ALEMBIC_VERSION` 상수와 DB 스탬프만
  비교 — 새 마이그레이션 3개(p5_47/48/49)를 추가했는데도 상수를 안 올리면 앱이
  "이미 최신"이라 착각해 **영원히 미적용**됨(기존 메모 `project_aot_dev_env_footguns.md`
  실증). 상수를 `p5_49_knowledge_chunk_reuse_count`로 수동 갱신 후 컨테이너 재시작해
  실제 적용 확인.
- 검증(브라우저 실측, 로컬 docker `aot_local-aot-app-1`): 스키마 마이그레이션 적용 →
  실제 `knowledge_shelve_service`로 테스트 항목 2건 생성 → `/ai/library` 페이지 로드 →
  리뷰 섹션 렌더링 확인 → **실제 클릭으로 확인(Confirm)·폐기(Retire) 실행** → DB
  read-only 조회로 `context_state`/`is_enabled` 정확히 반영됨을 확인 → 테스트 데이터
  정리. 유닛테스트: `aot/tests/test_knowledge_promotion_p5.py` 신설 15건(사람주도
  전이, advisory 배지, 재사용 자동승격, 캐시 불변, 인용태그 trust_state 반영) 전부
  통과. 전체 P1-P5 39건 + SSOT 재실행 통과.

P6 구현 메모(2026-07-19):
- **플래그 기본 ON (핵심 수정)**: `t3_knowledge_search_enabled`/`knowledge_digest_enabled`
  default를 `False`→`True`로 전환(`aot/databases/models/ai_settings.py`). 사전 확인:
  두 플래그 모두 템플릿·라우트 어디서도 읽거나 쓰지 않음(grep 0건) — UI가 아예 없으니
  기존 `False`는 "운영자가 의도적으로 끔"이 아니라 "만질 방법이 없었음"만을 의미, 뒤집어도
  아무도의 명시적 선택을 뒤집는 게 아니라고 판단. 마이그레이션
  `p5_50_knowledge_injection_default_on`이 컬럼 기본값(신규 설치용)과 **기존 설치의
  저장된 값**(신규 행이 생기지 않는 한 컬럼 기본값만으론 반영 안 되므로) 둘 다 갱신.
  downgrade()는 의도적으로 no-op(스키마 롤백이 런타임 동작 결정까지 되돌리면 안 됨).
- **`knowledge_chunk_confirmed_only` 의미 재정의**(§9 지시 이행): 기존엔 켜면
  `context_state='user_confirmed'`가 아닌 모든 행(external_authority·user_provided
  포함)이 통째로 안 보였음 — P5 리뷰 UI 없던 시절엔 "켜는 순간 전 지식 소멸, 되돌릴
  방법 없음"이던 rev.0 트랩. 이제는 `provenance != 'ai_curated' OR context_state !=
  'system_generated'`로 필터해 **미확인 AI 정리본만** 숨기고 권위/사용자제공/승격된
  AI정리본은 그대로 유지. 기본값은 그대로 `False` 유지(비검토 상태도 즉시 사용 가능해야
  한다는 §3.2 원칙 — 이 플래그는 원할 때만 켜는 강화 옵션이지 P6가 켜는 대상 아님).
- **semantic notes 검색 합류**(§5 결정 #2 구현): `knowledge_search._load_semantic_note_sections()`
  신설 — `Notes.category=='ai_semantic'`(기존 `ai_context_service.get_global_decisions`가
  쓰는 것과 동일 기준, `incorrect/obsolete/error` 태그·archived 제외)를 검색 후보로 편입,
  `provenance='user_provided'`로 표기(§3.1: 사람이 확정한 사실은 고신뢰). Notes 저장/모델은
  전혀 안 건드림(§5 결정: 항목 모델 일원화 안 함, 검색 계층 합류만). 캐시 미적용(의도적) —
  Notes엔 신뢰할 만한 "최종수정" 컬럼이 없어 스탬프 캐시를 만들 수 없고, ai_semantic 노트는
  소량·저빈도라 매 호출 재조회 비용이 잘못된 캐시보다 저렴하다고 판단.
- 검증: `aot/tests/test_knowledge_p6.py` 신설 8건(플래그 기본값, confirmed_only
  재정의로 미확인만 배제·확인본/권위는 유지, semantic note 검색 편입·비대상 노트
  배제·태그 스코핑, 매뉴얼 검색 불변) 전부 통과. 전체 P1-P6 47건 + SSOT 재실행 통과.
  마이그레이션 체인 read-only 검증(단일 head) 후 로컬 docker에 실제 적용, **수동
  플래그 오버라이드 없이** shelve→`AIAgentService._manual_grounding()`(실제 프로덕션
  경로) 호출 종단 테스트로 이 대화 최초 진단("라이브러리에 넣어도 AI에 안 닿음")이
  실제로 해소됐음을 확인. 테스트 데이터 정리 완료.

검증-수정 라운드(2026-07-19, P6 완료 후 종단 verify에서 발견된 3중 결함 수정):
실제 gemini 채팅으로 종단 구동한 결과, 검색·주입은 완벽했지만(라이브러리 항목이 score
19 vs 7로 1위 매칭) 최종 답변은 "데이터 없음"이었다. 원인 3개가 겹쳐 있었고 순차 격리해
전부 수정:
1. **프롬프트 절단이 grounding을 삼킴**: `manual_reference`가 컨텍스트 dict의 마지막
   삽입 키라, 대형 설치(실측 195k 프롬프트)에서 base_ai의 100k 꼬리 절단에 잘림.
   → `_inject_context_front()` 헬퍼 신설(system_knowledge의 FIRST-key 선례 일반화),
   fast path·collab 두 주입 지점 모두 front 배치로 전환.
2. **collab 경로 intent 게이트가 None을 놓침**: auto-dispatch가 intent_override=None으로
   이 경로에 진입하면 grounding이 통째로 스킵됨. → 게이트를 `in ('DATA_QUERY', None)`으로
   확장(디렉티브가 자체 게이팅하므로 None 포함 위험 낮음, CONTROL 등 명시 intent는 계속 제외).
3. **semantic guard 오탐이 정답을 폐기**: `control_intent` 글로서리에 장치 **명사**
   ('밸브'/'valve'/'전등'/'에어컨'/'티비')가 시드돼 있어, "밸브"를 언급하는 모든 정상
   지식 답변이 "제어 주장 + actions 없음 = 환각"으로 강제 폐기·에스컬레이션됨 —
   v26.10/BUG-06이 tool 이름에 대해 고친 것과 동일한 오탐 계열. → 시드에서 명사 5종 제거
   + 부트스트랩에 멱등 소급 비활성화(system_bootstrap 출처만, 운영자 추가 용어 불변).
   추가로 `_MANUAL_GROUNDING_DIRECTIVE`에 DATA_QUERY ENFORCEMENT 대비 우선순위 조항
   명시(grounding에 답이 이미 있으면 도구 호출 없이 직접 답변).
- 관측성: `_manual_grounding`이 주입 성공 시 섹션 수·문자 수를 INFO 로그로 남김(검증 중
  주입 여부를 로그로 판별 불가했던 문제 해소).
- 최종 실증: 동일 채팅 질문 재전송 → **"김제 포장 급수 밸브의 경우, 개방 후 압력이
  안정되기까지는 일반적으로 약 45초가 소요되는 것으로 확인되었습니다"** — 비치한 지식이
  에스컬레이션 없이(fast path 단독, 4.7s) 정확히 인용됨. 유닛 49건+SSOT 재통과.
- ~~잔여 관찰: flash-lite 모델이 미확인 항목임을 밝히라는 디렉티브 지시를 생략~~ →
  **해소(2026-07-19)**: `_enforce_unconfirmed_disclosure()` 서버측 결정적 후처리 가드
  신설. 디렉티브 준수가 모델 역량 의존적임이 실증됐으므로, 신뢰 표기(§6)도 검색(P2)과
  같은 원칙 — 모델에 맡기지 않고 서버가 강제 — 으로 승격:
  - 최종 insight가 `[AI 정리 — 미확인]` 섹션에서 실제로 인용했는데 고지가 없으면
    고지 문구("※ 위 답변의 일부는 AI가 자체 기록해 둔 미확인 메모를 근거로...")를 부착.
  - "실제로 인용했는가"는 **distinctive-token 교집합**으로 결정적 판정: 미확인 섹션에만
    있고 다른 grounding 섹션에는 없는 토큰(숫자+단어)이 답변에 등장할 때만 발화 —
    같은 주제를 권위 소스에서 답한 경우엔 오탐하지 않음(공유 토큰은 비식별로 제외).
  - 모델이 이미 스스로 고지한 경우('미확인'/'unconfirmed' 포함) 중복 부착 안 함.
    실패 시 무조건 원문 반환(표현 가드가 응답 경로를 깨면 안 됨).
  - fast path·collab 두 경로의 sanitizer 직후에 훅. 함정 1건 수정: `search_as_text`가
    검색 헤더를 첫 섹션 블록에 붙여 내보내므로 블록 첫 줄이 아니라 블록 내 `### ` 라인에서
    태그를 찾아야 함.
  - 라이브 실증(동일 채팅 질문): 미확인 상태 → 답변 뒤 고지 자동 부착 확인. 리뷰 API로
    confirm 처리 후 재질문 → 같은 지식이 **고지 없이** 인용됨(user_confirmed는 완전 신뢰,
    §3.2 계약 그대로). 유닛 5건 추가(부착/중복방지/무관답변 스킵/확인됨 스킵/공유토큰
    비식별) — 전체 54건+SSOT 통과.

원칙: 라이브 DB 테스트 금지(읽기전용/복사본), 요청 없는 배포 금지, 각 단계 로컬 검증 후
사용자 확인.

---

## 10.1 Phase A — 에이전트 루프 이관 이후 (2026-08-24)

P6 완료 시점의 검증은 전부 `ai_agent_service` 의 fast path·collab 경로에서 이뤄졌다.
그 뒤 `AgentLoopService`(docs/design/ai-agent-loop.md)가 기본 경로가 되면서
**§6 이 세운 두 계약이 새 경로에 옮겨지지 않아 조용히 깨져 있었다.** 유닛테스트
65건은 그대로 통과했고 — 계약이 서비스 경로 배선에 있었기 때문이다 — 실제로는
"모델이 스스로 `knowledge_search` 를 부를 때만" 지식이 닿는 상태였다.

### 복구한 것

- **결정적 주입** (`@ANCHOR: AGENT_LOOP_KNOWLEDGE_GROUNDING`): `AgentLoopService.run()`
  이 `_manual_grounding()` 을 **한 번** 호출하고, 결과를 `_inject_context_front` 로
  매 스텝 컨텍스트 **맨 앞**에 싣는다. 인용 규약(`_MANUAL_GROUNDING_DIRECTIVE`)은
  스텝 프롬프트에 붙는다 — base_ai 가 `goal` 을 프롬프트 앞에 두므로 절단을 탄다.
  - 조회는 1회, 적재는 매 스텝인 이유: 검색은 결정적이라 재조회할 이유가 없지만,
    모델이 3스텝째에 답하기로 정했는데 근거가 0스텝에만 있으면 같은 실패가 난다.
  - 비용 실측(로컬): 근거 1.8~2.1k자 vs `system_state` 95k + `capabilities` 72k
    = 스텝당 약 1.2%.
  - 앞 배치 이유 **정정(2026-08-24)**: 처음엔 "이 설치가 이미 절단되고 있다"
    고 적었으나 틀렸다 — GeminiAI 는 standard 를 600k 자로 오버라이드하고 실측
    프롬프트는 197k 라 지금은 잘리지 않는다. 다만 오버라이드가 없는 엔진
    (anthropic·openai·mistral·ollama·openai_compatible)은 base_ai 기본 100k 를
    써서 같은 프롬프트에서 97,767자를 잃는다. 앞 배치는 "지금 잘려서" 가 아니라
    **예산이 사용자가 고르는 엔진에 달려 있어서** 옳다. 자세한 진단은
    docs/design/ai-agent-loop.md §3.2.
- **미확인 고지 가드** (`@ANCHOR: AGENT_LOOP_UNCONFIRMED_DISCLOSURE`):
  `_enforce_unconfirmed_disclosure` 를 `_finish` — 여섯 종료 경로가 전부 지나는
  단일 지점 — 에 건다. 각 `return` 마다 걸면 다음에 추가되는 종료 경로가 조용히
  빠진다.
  - 한계(실측): 가드는 부분문자열 매칭이라 한국어 어미가 바뀌면 못 잡는다
    ('압력이' vs '압력은'). 형태소 수준 매칭은 Phase C 로 미룸.
- **프롬프트 정합화**: 루프 프롬프트에 "주제·도메인 질문이면 `knowledge_search`
  를 먼저" 라는 **긍정 지시**를 넣었다(기존엔 "노트 질문에 쓰지 말라" 는 부정
  지시만 있어 모델이 도서관을 아예 안 뒤졌다). `base_ai` 의 힌트는 레거시
  `action_type='knowledge_search'` 표현에서 도구 이름 호출로 바꿨다.

### 회귀 방어

`aot/tests/test_agent_loop_knowledge_grounding.py` 신설(8건) — 프롬프트 계약,
FRONT 배치, 1회 조회, 고지 부착/중복방지/무관답변 스킵. **이 파일의 목적은
knowledge_search 의 동작이 아니라 "루프가 그것을 부르고 결과를 어디에 싣는가" 를
고정하는 것이다** — 다음 경로 이관 때 같은 방식으로 끊기면 여기서 잡힌다.

### 소스 동기화 위생 (같은 라운드)

- **활성화 플래그가 갈라져 있었다**: 화면의 활성/비활성은 `is_enabled` 를
  토글하는데 스케줄러는 `is_active`(= 삭제 안 됨, 소프트삭제용)로 잡을 등록했다.
  그래서 **운영자가 끄지 않은 적 없는 소스를 매 주기 동기화**했다(실측: 비활성
  document 소스가 매시간 `file_path is required` 오류를 적립). 수동 동기화
  라우트는 이미 `is_enabled` 를 보고 있었으니 두 경로가 다른 기준으로 돌던 셈.
  → 스케줄러 등록을 `is_active AND is_enabled` 로, `sync_source()` 에도 방어선
  추가. 실측: 등록 대상 3건 → 0건.
- **ext 클라이언트가 오류를 지식으로 적립했다**: 키 미설정 시 `{'error':...}` 가
  아니라 상태 '레코드' 를 돌려줘서 `sync_status='ok'`, `records_written=1` 로
  기록되고 "API key not configured. Set NCPMS_API_KEY." 라는 **오류 문구가 지식
  레코드가 됐다.** 게다가 `_dispatch_ext_client` 가 list 가 아닌 반환을 `[]` 로
  뭉개서, 클라이언트가 제대로 오류를 돌려줘도 호출부는 "성공 0건" 으로 봤다.
  → 클라이언트 계약을 `list | {'error':...}` 로 명문화하고 통과시킨다.
- **프리셋 중복 등록**: 담기 버튼이 누를 때마다 새 행을 만들어 18행 중
  SmartFarmKorea 계열만 7행이 중복이었다. → 같은 프리셋이 이미 있으면 그 행을
  멱등 반환.

## 10.2 Phase B — 작동 테스트 (2026-08-24, 일부)

라이브 LLM 실행에 의존하는 판정은 사용자 요청으로 **뒤로 미뤘다**. 아래는 그날
결정적으로 확인된 것만이다.

### 확인된 것

| 검사 | 결과 |
|---|---|
| 빈 라이브러리 가드 | `knowledge_search` 가 주제 자료 없음을 `library_empty: true` 와 "NO SOURCE FOUND" 안내로 정직하게 보고 |
| MCP 쓰기 경로 | 외부 클라이언트가 웹 조사 요약을 `knowledge_shelve` 로 적립 → 재검색에서 1순위로 회수, 출처(URL) 그대로 표시 |
| **저장소 공유** | **MCP 가 비친 지식을 내장 AI(에이전트 루프)가 결정적 주입으로 회수해 도구 호출 0회로 인용**, 미확인 노트임과 출처를 함께 밝힘 |
| 가드 해제 | 지식이 생긴 뒤 `library_empty` 플래그가 사라짐 |
| 승인 게이트 | `create_program` 이 실행되지 않고 `pending_approval` 로 정지, 자기승인 불가 |
| 매뉴얼 검색 불변 | 시스템 how-to 질의가 여전히 해당 매뉴얼 섹션을 1순위로 반환 |
| 접지가 실데이터 질의를 방해하지 않음 | 센서 질문에 무관한 근거가 실려도 모델이 `search_devices` 를 호출해 실데이터로 답함 |

### Phase B 에서 발견해 고친 것

- **짧은 후속 발화 가드 누락**: Phase A 가 접지를 루프로 옮기면서 접지를 **하지
  않을 조건**은 같이 옮기지 않았다. fast path 에는 '안내해줘' 같은 짧은 이어말에
  역량 문서를 실으면 답변이 일반적인 시스템 소개로 납치되는 실측 사례가 있어
  가드가 있었다. 루프에도 추가하고 회귀 테스트로 고정.

### 남은 것

- **B2 실데이터 적재** — 외부 공공데이터 API 키 필요. P3 의 external_authority
  구조 블록 어댑터는 여전히 합성 데이터로만 검증된 상태다.
- 라이브 LLM 판정(인용 태그 정확도·도구 왕복 횟수 매트릭스)은 모델 상태가 나아진
  뒤 일괄 수행.
- 접지가 매 발화에 무조건 실린다(관련도 임계 없음). 답변을 망치지는 않으나
  발화당 약 1.7~2.4k자를 쓴다 — 관련도 게이팅은 Phase C1 로.

---

### MCP 클라이언트 동등성 (도구 설명 층)

외부 LLM 도 내장 AI 와 같은 "조사 → 요약 → 비치 → 활용" 을 할 수 있어야 한다는
요구에 대해, Phase A 는 **문장 층만** 손봤다(스키마 확장은 Phase C):

- `knowledge_shelve` 설명이 "derived / observed / were told" 뿐이라 **웹 조사
  결과 적립을 명시적으로 허용하지 않았다** — 외부 LLM 이 "내가 조사한 자료는 이
  도구 대상이 아니다" 로 읽을 수 있었다. → "or researched yourself" 를 명시.
- `attribution` 을 출처(제목/URL) 자리로 못박았다. 출처가 없으면 사람이 원문을
  확인할 수 없어 §3.2 승격 경로가 막힌다.
- 연쇄 레시피(`knowledge_search` → 조사 → `knowledge_shelve` → `create_program`
  의 `source_note` 에 인용)를 도구 힌트에 넣었다. `create_program` 은 이미 절반을
  갖고 있었다.
- 표면별로 나눠 실었다: 내장 에이전트는 루프 프롬프트가 연쇄를 말하므로 도구
  힌트에서 되풀이하지 않고, MCP 카탈로그는 그 프롬프트가 없으므로 카탈로그
  설명에 남긴다. 도구 표면 토큰 예산(`test_tool_cost_budget`)은 상한을 올리지
  않고 문구 중복을 덜어 맞췄다(`propose_plot_split` 선례).

---

## 10.3 Phase C — 고도화 (2026-08-24~, 진행 중)

### C4 — `knowledge_shelve` 계약 확장 (완료)

**출처 주소 자리 신설** (`AIKnowledgeChunk.source_url`, 마이그레이션
`p6_56_knowledge_source_url_20260824`). §3.2 는 "사람이 확인하면 승격된다" 를
전제하는데, 확인할 방법이 없었다 — 출처를 담는 자리가 `attribution` 자유
텍스트뿐이라 리뷰어가 **원문으로 돌아갈 길이 없었다.** 그래서 미확인 항목은
실질적으로 영원히 미확인이었다. MCP 로 연결된 외부 LLM 이 웹 조사 요약을
비치하게 되면서 이 구멍이 결정적이 됐다: 그런 항목은 정의상 바깥에 원문이 있고,
그 주소가 승격 판단의 전부다.

- `attribution`(사람이 읽는 표기)과 나눈 이유: 화면이 링크를 걸려면 "여기에
  주소가 있다" 가 스키마여야 한다. 자유 텍스트 파싱은 쓰는 쪽의 표기 습관에
  기댄다.
- **신뢰는 올리지 않는다.** 쓰는 쪽의 자기 신고("이건 권위 출처야")를 믿으면
  §3.3 오염 방지가 무너진다. 진입은 여전히 `ai_curated`/미확인이고, 이 값은
  사람이 확인할 수 있게 할 뿐이다.
- 저장 시점에 http/https 만 통과시킨다 — 리뷰 화면에서 클릭 가능한 링크가
  되므로, 렌더 시점마다 방어하는 것보다 확실하다.
- 리뷰 UI 에서 **'원문 열기' 를 '확인' 앞에** 뒀다. 순서가 곧 동선이다: 출처를
  보지 않고 누르는 '확인' 은 검토가 아니라 통과다. 주소가 없는 항목은 그
  버튼이 아예 없어서, 확인할 수 없는 항목임이 화면에서 보인다.

**쿼터 가시화**: `quota_remaining` 을 응답에 실어, 여러 항목을 비치하는 호출자가
거부당하고서야 상한을 알게 되는 일을 없앴다. 상한값(50/24h) 자체는 그대로 —
병적 반복을 막는 장치이지 정상 사용을 재는 값이 아니다.

**미이행**: 지식↔프로그램 구조적 링크(N6). `create_program.source_note` 는 여전히
자유 텍스트이고, 도구 힌트가 "비친 항목을 인용하라" 고 안내할 뿐이다. 프로그램
하나가 지식 여러 건을 근거로 삼을 수 있어 스키마 결정이 따로 필요하다.

### C5 — 서랍 발견성 (완료, 실측 기반)

`knowledge_search` 를 core 로 올리고 `knowledge_shelve` 는 서랍에 남겼다.
**두 동사는 필요해지는 시점이 다르다** — 읽기는 답하기 전 첫 수여서 tools/list
에 없으면 LLM 이 ①인덱스에서 이름 알아보기 ②열기로 정하기 ③부르기 세 단계를
거쳐야 하고, 건너뛰면 자기 기억으로 답한다. 쓰기는 이미 라이브러리를 쓴 뒤라
그때는 서랍이 열려 있다.

실측: 상시 노출 6,958 → 7,164 토큰(상한 7,200, **여유 36**). 둘 다 올리면
7,575 로 초과. 등급 매니페스트는 3,600 → 3,679 라 상한을 3,700 으로 올렸고,
그 전에 대신 내릴 도구를 찾아봤으나 이 작업과 무관한 흐름이 쓰는 것뿐이라
건드리지 않았다.

---

### C6 — 지식 저장소 관리 화면 (완료, 브라우저 실측은 보류)

설계 §8 이 요구했으나 P5 에서 리뷰 섹션만 만들고 멈춰 있던 부분.

**무엇이 없었나.** 화면은 `provenance='ai_curated'` 만 보여줬다 — "AI 가 뭘
썼는지 검사한다" 가 리뷰 섹션의 일이니 맞다. 하지만 그것만으로는 운영자가
저장소에 무엇이 들어 있는지 볼 수 없고, **비어 있는 것과 고장난 것을 구분할 수
없다.** 그리고 자기가 이미 아는 사실을 넣으려면 AI 턴이나 외부 피드 등록을
거쳐야 했다 — 10년 농사지은 사람이 "북쪽 구획은 7월에 물이 찬다" 를 적으려고
AI 에게 부탁해야 하는 구조였다(feedback: 기능이 어려우면 AI 말고 화면을 고칠 것).

**신설**: `knowledge_library_service.py` (browse / tag_counts / summary /
add_user_knowledge / set_enabled) + 라우트 3종 + '지식 항목' 섹션.

- **직접 입력은 `user_provided` / `user_confirmed` 로 들어간다.** 이 시스템에서
  쓰기 시점에 신뢰를 주는 유일한 경로다 — 내용이 권위 있어 보여서가 아니라
  **사람이 직접 썼기 때문에** 준다(§3.1). 쿼터도 모순 플래그도 없다: 사람이
  타이핑하는 것은 스스로 제한되고, 모순 플래그는 AI 출력을 감시하는 장치다.
- 예약 소스를 둘로 나눴다(AI 자율 비치 / 직접 입력). 소스 목록은 사람이
  "이 지식이 어디서 왔나" 를 보는 자리라, 합치면 그 구분이 사라진다.
- **빈 상태는 "없음" 만 말하지 않는다.** 라이브러리가 비면 AI 는 주제 질문에
  자기 기억으로 답할 수밖에 없는데, 화면이 그 사실도 다음 할 일도 안 알려 주면
  운영자는 페이지가 고장난 줄 안다. 필터 결과 0건과는 다른 문구를 쓴다.
- 태그 필터는 `무` 가 `무름병` 에 걸리지 않게 양쪽 쉼표로 경계를 잡는다.
- 목록은 gridstack 을 쓰지 않는다 — 필터마다 통째로 다시 그리고 드래그
  순서변경도 없는데, gridstack 은 절대배치를 자기가 계산해서 동적 innerHTML 에
  레이아웃이 붙지 않는다. `.aot-entry-item` 이 자립 클래스라 그대로 쓴다.
- '치우기'는 삭제가 아니라 `is_enabled=False` 다(되돌릴 수 있다). 리뷰 섹션의
  retire/reactivate 는 신뢰 상태 의미를 갖는 ai_curated 전용 경로이고, 이쪽은
  어떤 항목에나 쓰는 단순 on/off 다.

검증: 유닛 12건(`test_knowledge_library_browse_c6.py`). **브라우저 실측은
사용자 요청으로 보류** — 모델 상태가 나아진 뒤 Phase B 잔여분과 함께 일괄.

### C6d — 플래그: 하나만 노출한다

지식 플래그는 셋인데 **조작할 값은 하나뿐**이다.
`t3_knowledge_search_enabled` / `knowledge_digest_enabled` 는 끄면 라이브러리가
조용히 아무 일도 안 하는 상태가 된다 — 그건 P6 가 고친 "동작하는 척" 바로
그것이고, 그 자리를 원하는 사람은 없다. **켜짐 말고 쓸 자리가 없는 스위치는
설정이 아니다**(feedback: 불필요한 설정 금지). 그래서 UI 를 주지 않는다.

`knowledge_chunk_confirmed_only` 만 진짜 선택이다: 신중한 운영자가 "AI 가 자기가
쓴 미검토 노트는 인용하지 못하게" 정할 수 있고, 대가는 AI 가 알아낸 것을 사람이
확인할 때까지 잊는다는 것이다. 이것만 토글로 낸다.

### C7 — 관측성 (완료)

"무엇이 들어 있나" 만으로는 다음에 무엇을 채울지 정할 수 없다. `usage_stats()`
가 한 번이라도 검색에 걸린 항목 수, 출처 링크를 가진 항목 수, AI 노트의 검토율·
폐기율, 가장 많이 걸린 항목을 낸다.

**문구를 정확히 쓴다**: `reuse_count` 는 `knowledge_search` 가 항목을 내보낼 때
오르므로 '검색에 걸린 횟수'이지 '답변이 인용한 횟수'가 아니다. 그 둘을 가르는
계측은 아직 없고, 화면이 이것을 '인용'이라 부르면 거짓말이 된다. 테스트가 이
구분을 고정한다.

**미이행(Phase C 잔여)**: 검색 스코프 자동 유도(C1a)·의미검색(C1c), 엔티티 링크
실사용(C2), 거버넌스 성숙(C3), shred bridge 부채(C8), 지식↔프로그램 구조 링크(N6).

C1a 를 지금 하지 않은 이유: 태그 자동 유도는 후보를 **좁히는** 변경이라 재현율이
떨어질 수 있고, 그 판정에는 실제 질의 실행이 필요하다. 라이브 검증이 보류된
상태에서 검색 동작을 바꾸는 것은 순서가 틀렸다.

C1b(다국어 토크나이저)는 **이미 돼 있었다** — 2026-08-22 에 `_NO_WORD_BREAK`
bigram 경로로 ja·zh·th 가 해결됐다. 계획서의 갭 항목이 낡았던 것.

---

## 10.4 Phase D — 자원 확대 (2026-08-24, 1차)

### D3 — 카탈로그의 지역·주제 축 (완료)

**무엇이 문제였나.** 내장 프리셋 여섯은 전부 한국 공공데이터(RDA·농사로·NCPMS·
스마트팜코리아)인데 화면도 도구도 그 사실을 말하지 않았다. 드롭다운 그룹은
'System Library / Custom Source' 였다 — 한국 밖 운영자에게 그 목록은 "고를 수
있는 것 전부" 처럼 보이고, AI 는 어느 나라 사용자에게든 EXT-KR-01 을 권할 수
있었다. AoT 는 22개 언어로 나간다(feedback: AoT 는 한국 전용이 아니다).

- 모든 프리셋이 `region`('KR'|'any')과 `topics` 를 선언한다.
- 드롭다운 그룹을 **지역으로** 가른다: '공공데이터 — 한국' / '내 자료 —
  어디서나'. 무엇을 고를 수 **없는지**가 보여야 아래 그룹으로 눈이 간다.
- `list_library_source_types` 가 항목마다 region/topics 를 싣고, 지역 목록은
  **결과에서 계산한다** — 상수로 "한국 전용" 이라 적어 두면 지역 불가지
  프리셋이 하나라도 생기는 순간 거짓말이 된다. note 는 "한국이 아니면 그렇게
  말하고 custom_types 로 안내하라" 를 명시한다(지역을 실어만 놓고 무엇을
  하라는 말이 없으면 모델은 무시한다).
- 회귀: `test_library_catalog_regions_d3.py` 5건 — 축 누락, 범용 타입의 지역
  불가지성, **한국 밖에서 쓸 수 있는 소스가 최소 하나는 남아 있는지**, 도구의
  계산값·안내 문구.

### 남은 Phase D — 사용자 결정이 필요한 범위

| # | 항목 | 왜 여기서 멈추는가 |
|---|---|---|
| D1 | MCP 조사 결과의 상시 품질·오염 관리 | 정책 조정의 근거가 실사용 통계인데, 라이브 검증이 보류돼 아직 데이터가 없다. C7 관측성이 그 계기를 만들어 뒀다 |
| D2 | 문서 업로드를 1급 경로로 | 현재 `document` 소스는 서버 파일 경로를 손으로 적어야 한다. 업로드는 저장 위치·용량 한도·파싱 범위(PDF/OCR 여부) 결정이 먼저다 |
| D4 | 지역 불가지 시스템 소스 후보 | **무엇을 넣을지가 사용자 결정 사항.** 라이선스·재배포 조건 확인이 선행 |
| D5 | 농업 외 도메인 시드(축산·시설·인프라) | 같음 — 넣을 내용을 정하는 일이다 |
| D6 | `data_derived` 파이프라인(텔레메트리 → 패턴 지식) | 별도 설계 규모 |

---

## 10.5 참조표 — 적재하지 않고 조회한다 (2026-08-24)

### 왜 §2 의 항목 모델을 쓰지 않는가

설계 §2 는 모든 지식을 하나의 항목 스키마로 담는다. 행이 수천 개인 **표**는 그
틀에 넣으면 두 군데가 깨진다.

1. **관련도 오염.** 모든 행이 비슷한 낱말을 담고 있어 매 질의에서 매뉴얼과
   경쟁한다. 실측(ECOCROP 2,568종): 검색 14ms → 73ms. 느려지는 것보다 **엉뚱한
   행이 답의 근거로 실리는 쪽**이 문제였다.
2. **미리 고른 것만 답할 수 있다.** 오염을 피하려고 일부만 적재하면, 표의 값어치
   절반인 "아직 다루지 않는 것도 찾아볼 수 있다" 가 죽는다.

그래서 표는 **등록만 하고 물어볼 때 조회**한다(`source_type='csv_table'`,
`reference_table_service`). 행을 DB 에 넣지 않고 파일 한 벌을
`AOT_LOCAL_DIR/reference_tables/` 에 받아 둔다 — 마이그레이션이 없고, 평소 검색은
조금도 무거워지지 않으며, 표 전체가 답변 범위에 들어온다.

### 그 대가와 갚는 법

표는 검색되지 않으므로 **모델이 표의 존재를 모를 수 있다.** 실측(2026-08-24):
오크라 생육 온도 질문에서 AI 가 `knowledge_search` 만 부르고 "정보가 없습니다" 로
끝냈다 — 답은 등록된 표 안에 있었는데.

메우는 자리는 매니페스트가 아니라 **응답**이다. `knowledge_search` 가 빈손일 때
등록된 표를 한 줄 가리킨다. 표가 없는 설치에서는 그 줄이 나가지 않으므로 고정비가
0 이다. 이 뒤로 연쇄가 돌았다: `knowledge_search`(빈손·표를 가리킴) →
`list_reference_tables` → `query_reference_table` → 답변.

### 도구가 둘인 이유

등록된 표는 설치마다 다르므로 **정적인 도구 설명에 담을 수 없다.** 무엇이 있는지
먼저 보고(`list_reference_tables`), 맞으면 조회한다(`query_reference_table`).
둘 다 읽기 전용이고 `record` 서랍이다. 고정비 353토큰을 내고 가변비(적재된 행이
매 질의의 후보가 되는 비용)를 없앤 거래다.

### 순위 — 실측으로 필요해진 것

`tomato` 로 찾으면 `tree tomato`(Cyphomandra betacea)가 진짜 토마토
(Lycopersicon esculentum)보다 먼저 나왔다. 낱말 매치를 이름 전체 매치와 같이
취급했기 때문이다. 셋으로 나눴다: 이름 하나와 통째로 같음 → 칸 전체와 같음 →
이름 안의 낱말. 남의 작물 수치를 자기 작물 값으로 읽는 일을 막는다.

### 첫 사례 — FAO ECOCROP (EXT-GL-01)

한국 밖에서 쓸 수 있는 첫 내장 소스다. 2,568종 55열, **CC BY 4.0**(재배포 허용,
출처 표기 조건). AoT 는 이 자료를 재배포하지 않고 조회 시점에 받아 둔다.
전용 클라이언트를 두지 않았다 — 특별한 자료여서가 아니라 **범용 참조표의 기본값이
채워진 한 사례**일 뿐이다.

**주의를 데이터에 박았다.** ECOCROP 의 값은 `TMIN/TOPMN/TOPMX/TMAX` 형태의
**적합성 포락선**이지 온실 설정값이 아니다. 이 구분이 흐려지면 AI 가 `[권위]` 로
인용한 숫자가 프로그램의 목표 온도로 옮겨간다. 그래서 `caveat` 필드를 두고 조회
응답에 함께 실어, 모델이 수치와 같이 인용하게 했다 — 실측에서 실제로 그렇게
답했다("생육 단계별 목표값이 아니므로 온실 설정값으로 그대로 사용해서는 안 됩니다").

---

## 10.6 연결된 API 를 물어볼 때 조회한다 (2026-08-25)

### 기대되던 동작과 실제

사용자가 기대한 흐름은 이것이다 — **MCP 사용자의 요청을 LLM 이 연결된 지식 API 로
사람 대신 조회하고, 그 결과를 근거로 추론하고, 쓴 내용을 라이브러리에 비치해
메모리처럼 재사용한다.**

라이브러리는 그중 ①③④를 이미 했지만 ②가 반쪽이었다. REST 소스는 등록할 때
정한 파라미터 하나로 **한 번 동기화**해 지식으로 굳히는 구조라, 그 선택 밖은
답할 수 없었다. 실측(2026-08-25): 스마트팜코리아 노지 농가 1,650곳 중 라이브러리에
들어온 것은 **한 곳**뿐이었고, "다른 농가는 어떤가" 는 새 소스를 등록해야 답이
됐다.

### 무엇을 했나

`data_source_query_service` + `query_data_source` 도구. 등록된 소스의 오퍼레이션
하나를 **지금** 호출한다. 도구 하나로 1,650곳이 답변 범위에 들어온다.

- **조회 가능한 것만 내보낸다.** 오퍼레이션을 선언한 소스(스마트팜코리아 3종)만
  이다. `EXT_CLIENT_MAP` 계열(농사로·병해충·RDA)은 `sync()` 하나뿐이라 "이
  파라미터로 이것만" 을 표현할 수 없다 — 조회 가능한 척 내보내면 모델이 부를 수
  없는 것을 부르려 든다.
- **잘렸다는 사실을 반드시 말한다.** `total_available` 을 항상 싣고, 잘렸으면
  "이것을 전부로 보지 말라" 를 덧붙인다. identity 는 한 번에 2,308행을 준다 —
  잘린 줄 모르면 모델은 그것을 전부로 읽고 "그런 농가는 없다" 고 단정한다.
- 소스에 이미 지정된 값(userId 등)은 기본값으로 쓰고, 호출자가 주면 그것이 이긴다.
- 파라미터가 없으면 **무엇이 없는지와 어디서 구하는지**(smartfarmkorea_lookup)를
  말한다. 추측해서 부르게 두지 않는다.

### 발견 지점은 하나로

`list_reference_tables` → **`list_lookup_sources`** 로 바꾸고 표와 API 를 한
자리에서 보여준다(`kind` 로 구분). 둘로 나누면 모델이 한쪽만 보고 "없다" 고
단정한다 — 실측으로 이미 한 번 겪었다(§10.5). `knowledge_search` 의 빈손 안내도
두 종류를 함께 가리킨다.

### 남은 것

비치되는 항목은 여전히 전부 `ai_curated`(미확인)다. 그런데 **조회 결과를 그대로
옮긴 것**과 **AI 가 추론해 만든 것**은 성격이 다르다 — 전자는 `source_url` 이
있어 원문 확인이 기계적으로 가능하다. 지금은 둘 다 미확인이라 리뷰 부담만 쌓인다.
신뢰 어휘를 넓히는 문제(§3.1)와 같은 뿌리다.

---

## 10.7 옮긴 것과 지어낸 것을 가른다 (2026-08-25)

### 문제

AI 가 비치하는 항목은 전부 `ai_curated`/미확인으로 들어간다(§4). 그 원칙은
옳다 — 쓰는 쪽의 자기 신고를 믿으면 §3.3 오염 방지가 무너진다.

그런데 §10.6 이후 성격이 다른 둘이 같은 칸에 쌓이기 시작했다.

- **옮긴 것** — `query_reference_table`/`query_data_source` 로 등록된 소스를
  조회해 그대로 적은 것. 확인이 **기계적**이다: 어느 소스인지 알면 거기 가서
  대조하면 끝이다.
- **지어낸 것** — 대화 중 관찰이나 추론을 정리한 메모. 사람 판단이 필요하다.

둘을 구분하지 못하면 리뷰 부담만 쌓이고, 결국 아무도 안 본다.

### `attribution`·`source_url` 로는 못 가른다

둘 다 **자유 텍스트**다. AI 가 그럴듯한 문자열을 적어 넣어도 서버는 모른다.

`source_ref`(P6-59)는 `ai_context_source.source_id` 를 가리키고, **쓰기 시점에
그런 소스가 실제로 등록돼 있는지 서버가 확인한다.** "AI 가 ECOCROP 이라고
말했다" 와 "이 시스템에 실제로 있는 ECOCROP 소스를 가리킨다" 의 차이다. 가짜
값은 조용히 버려지지만 **지식 자체는 저장된다** — 출처 표기가 틀렸다고 내용을
잃을 이유는 없다.

### 신뢰를 올리지는 않는다

여전히 `ai_curated`/`system_generated` 다. 바뀌는 것은 **인용 태그와 리뷰
화면**뿐이다:

```
[AI 정리 — 출처 FAO ECOCROP …, 미확인]   옮긴 것 — 확인할 데가 있다
[AI 정리 — 미확인]                        지어낸 것 — 사람이 판단해야 한다
```

디렉티브도 둘을 나눠 지시한다: 앞엣것은 **출처를 이름으로 인용하되 미검토임을
밝히고, 자기 추측이라고 말하지 말 것**(확인 가능하므로). 뒤엣것은 종전대로
"내 미확인 메모" 라고 먼저 밝힌다.

승격된 뒤에는 일반 `ai_curated` 태그를 따른다 — 그때는 사람이 이미 봤다는 뜻이다.

### 흐름

조회 도구가 응답에 자기 `source_ref` 를 함께 돌려준다. 모델은 그것을 그대로
`knowledge_shelve(source_ref=…)` 에 넘기면 된다 — 코드를 외우거나 지어낼 필요가
없다.

### 남은 것

Wikidata 처럼 **공개 참고자료이나 기관 검증은 아닌** 소스를 담을 provenance 가
아직 없다(§10.5 조사에서 드러난 빈칸). 그런 소스를 실제로 붙일 때 정한다 —
아무도 만들지 않는 값을 미리 만들지 않는다.

---

## 10.8 기상·토양·증발산 — Open-Meteo (EXT-GL-02, 2026-08-25)

### 왜

"농업 MCP 서버를 붙이면 종합해서 더 나은 답이 나오지 않겠나" 라는 물음에서
출발해 생태계를 조사했다. 결과는 반대 방향을 가리켰다.

- Claude 커넥터 레지스트리에 농업 항목 **0건**.
- 공개 저장소는 있으나 규모가 없다 — `etudelab/agri-weather-mcp` 별 0개·커밋
  6개, `AiAgentKarl/agriculture-mcp-server` 별 1개. 둘 다 **Open-Meteo 등
  무료 REST API 의 얇은 래퍼**다.
- Leaf/John Deere 계열은 상용이고, 무엇보다 **AoT 와 같은 층**이다(농기계·필드
  데이터 통합). 붙여도 재배 조언은 나아지지 않고 장치 목록만 둘로 늘어난다.

대신 조사 과정에서 AoT 자신의 공백이 드러났고, 그쪽이 진짜 문제였다.

  1. `get_weather_forecast` 는 **기상청 단기예보 전용**이다. AoT 는 22개 언어로
     나가는데 한국 밖 설치에는 예보가 아예 없다 — 선제 조언이 불가능하다.
  2. `get_weather` 는 외부 API 를 부르지 않고 **AoT 자신의 InfluxDB 센서만**
     읽는다. 기상 Input 을 안 꽂은 농가는 빈손이다.
  3. **토양 온도·수분과 ET0 는 어느 경로로도 없었다.** 물리 센서를 꽂은 곳만
     알 수 있었고, ET0 는 그나마 계산해 주는 곳이 없었다.

### 무엇을 했나

`openmeteo_client` 를 `query_data_source` 의 두 번째 소스 계열로 붙였다.
오퍼레이션 4개 — `forecast_daily`, `forecast_hourly`, `soil`, `climate_history`.
전세계, 좌표만으로, 키 없이.

**외부 MCP 서버가 아니라 원본 API 를 직접 부른 이유**는 별 0~1개짜리 저장소의
수명에 의존하지 않으려는 것도 있지만, 결정적인 것은 따로다 — **내장 AI 는 MCP
클라이언트가 아니다.** 외부 MCP 서버로 붙였다면 MCP 로 접속한 LLM 만 혜택을
봤을 것이다. 소스로 등록하면 두 경로가 같은 것을 쓴다.

### 설계상 판단 세 가지

- **단위를 컬럼 이름에 박는다** (`soil_moisture_3_to_9cm (m³/m³)`). 토양수분
  0.268 을 26.8% 로 읽는 사고는 단위가 없으면 반드시 난다.
- **시간별은 3시간 간격으로 솎는다.** 48시간을 시간마다 주면 48행이고 조회
  상한(25행)에 걸려 **오늘까지만** 남는다 — "내일 아침 추워지나" 가 정확히
  잘려 나가는 자리다. 농업 조언에 필요한 것은 시간 단위 해상도가 아니라 추세다.
- **과거 기후는 월별 집계로 돌려준다.** 날짜별이면 한 해가 365행이라 앞 25일만
  남고, 모델은 9월 상순만 보고 "9월은 이렇다" 고 말한다. 평균과 함께 **최저기온의
  최저값과 영하일수**를 내는 이유는, 월평균 최저가 영상이어도 서리는 내리기
  때문이다(실측: 2025-11 평균최저 4.3°C, 최저 -1.9°C, 영하 1일).

### 라이선스 — 무료 티어는 비상업 전용이다

`api.open-meteo.com` 은 약관상 **비상업 이용 전용**이고(약관이 드는 예시:
"구독·광고 없는 개인/비영리 사이트", "개인 홈오토메이션"), 자료는 CC BY 4.0 이라
출처 표시가 필요하다. 한도 600회/분·10,000회/일.

상업 농가는 유료 키로 `customer-api.open-meteo.com` 을 쓴다. 그래서 **키를 선택
항목**으로 두고, 키가 있으면 상업 엔드포인트로 보낸다. AoT 가 어느 쪽인지 대신
판단하지 않는다 — 설치 운영자가 안다. AoT 가 할 일은 그 선택을 표현할 수단을
주는 것까지다.

### 프리셋 등록 (`ext_openmeteo`)

**새 도구를 만들지 않았다.** `query_data_source` 를 그대로 쓴다. MCP 초기
텍스트 비용이 이미 한계에 닿아 있어(카탈로그 100,028자·50,086토큰) 도구를
하나 더 얹을 자리가 없다. 실측으로 등록 전후 고정비가 **바이트 단위로 동일**함을
확인했다 — 프리셋은 런타임 응답에만 실린다.

`source_type='query_api'` 를 새로 뒀다. 참조표와 같은 이유로 적재하지 않지만,
이유가 하나 더 있다: 기상은 시시각각 바뀌므로 지식 항목으로 굳히는 순간 그 값이
틀린 채로 라이브러리에 영원히 남는다. `sync_interval_min=0` 이고, 활성화가 하는
일은 좌표가 실제로 응답하는지 한 번 확인하는 것뿐이다.

**좌표는 어디서 오는가 — 한 번 틀렸다.** 첫 구현은 `Misc.map_latitude` 를
읽었고 실측에서 하나도 못 채웠다: 이 설치의 `Misc` 와 지도 5개가 전부 NULL
이었다. 그 컬럼들은 어느 쓰기 경로도 채우지 않는 레거시이고,
`GeoMap.viewport()` 의 독스트링이 같은 함정을 이미 경고하고 있었다("컬럼만 보는
독자는 모든 지도를 같은 기본 좌표로 보낸다"). 고친 뒤에는 둘을 순서대로 본다 —
지도의 저장된 카메라(`state_json`, `viewport()` 경유), 그다음 그려 둔 도형의
대표점(`containment_point()`; 이 설치에 183개). GeoJSON 은 (경도, 위도) 순이라
뒤집기 쉽고 **뒤집어도 조회는 성공한다** — 바다 한가운데 기온이 오류 없이
돌아오므로, 축 순서를 검사로 고정했다.

활성화 게이트의 좌표 검사는 `is_system` 분기보다 **앞에** 둔다. 조회 전용 API 는
전부 내장 프리셋이라, 뒤에 두면 `return None` 으로 빠져나가 검사가 죽은 채
통과한다.

`get_weather_forecast` 의 `unavailable` 응답이 이 소스를 가리킨다. 그 경로는
기상청 전용이라 한국 밖에서는 채워질 일이 없는 파일을 보고 끝나 있었다.
**등록돼 있을 때만** 권한다 — 없는 것을 권하면 모델이 부를 수 없는 것을 부르고,
그 실패는 사용자에게 그냥 고장으로 보인다.

실증(2026-08-25, 로컬 설치에서 화면 → MCP 전 구간): 프리셋 추가 → 좌표
자동채움(도형에서 35.85/126.875) → 활성화 → MCP `list_lookup_sources` 에
오퍼레이션 4개 노출 → `query_data_source` 로 예보·토양·과거기후 조회. 과거기후는
2025-11 최저 −2.4°C·영하 1일, 2025-12 영하 20일을 돌려줬다 — "서리가 언제
오나" 가 답이 되는 형태다.

### 남은 것

- 저작권 표시 — CC BY 4.0 출처를 어디에 적을지(§THIRD-PARTY-LICENSES).
- 좌표를 구역별로 잡는 것 — 지금은 설치에 하나다. 넓은 농장에서 구역마다
  기후가 갈리면 그때 필요해진다(모델이 좌표를 직접 넘기는 길은 이미 열려 있다).

---

## 11. 결정 기록 (2026-07-18)

1. **AI 자율 쓰기** — 확정. AI가 자율 비치하되 항상 ai_curated 이하·낮은 가중치로
   진입, 안전은 §3.3 사후 거버넌스로. (§4 반영)
2. **semantic notes = 검색만 합류** — 확정. 노트 저장/UX 불변, `knowledge_search`가
   노트+라이브러리 함께 검색하고 노트는 `user_provided`로 표기. 항목 모델 일원화 안 함.
   (§5 반영)
3. **엔티티 링크 = 태그 우선, 엔티티 링크는 P5+ 후속** — 기본값으로 진행. 태그만으로
   시작해 스코핑 실효를 확인하고, 엔티티 결부는 필요 시 승격. (미이견 시 이대로)

---

## 12. 후속

- 의미검색(임베딩) — 태그 필터로 당장 실용적, 재현율 부족 시 추가.
- 사용자 문서 업로드(PDF/URL) — 통합 항목 모델의 `provenance=user_provided,
  content_kind=prose`로 자연 흡수(별도 제품 불필요).
- data_derived 자동 도출 파이프라인(텔레메트리 → 패턴 지식) — P4 이후 확장.
