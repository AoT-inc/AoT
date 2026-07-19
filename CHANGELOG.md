# AoT — 변경 이력

AoT는 오픈소스 환경 제어 시스템을 기반으로,  
**AI 오케스트레이션**과 **벡터 기반 GIS** 를 통합한 스마트팜 특화 플랫폼입니다.

---

## 플랫폼 주요 특징 (Platform Overview)

### 벡터 기반 GIS
타일 기반이 아닌 벡터 렌더링으로 부드럽고 자연스러운 지도를 제공합니다.

- **GeoMap**: OSM / 위성 등 다양한 맵 프로바이더, 도형 그리기, 장치 배치
- **GeoFacility + 3D Widget**: 시설(온실/하우스) 외형을 폴리곤으로 정의하고 3D로 시각화
- **자동 액추에이터 제어**: 환기창(vent), 커튼(curtain), 측창(side window), 도어, 조명 등 시설 구성 요소를 GIS 폴리곤에 연결해 자동 제어
- **풍향 차등 제어**: 강풍 시 windward(풍상) 개구부만 강제 폐쇄, leeward(풍하) 환기 유지
- **GeoShape 기반 효과 산출**: 개구부 면적·방위각을 폴리곤에서 자동 계산해 제어 효과에 반영
- **시설 센서 바인딩**: 실내/외 온도·습도·CO₂·풍향 센서를 시설에 역할별로 연결

### 통합 환경 제어 (Layer 3 Coordinator)
PI 제어 기반의 다중 액추에이터 조율 시스템입니다.

- **ActuatorProfile**: GIS 폴리곤에서 azimuth·면적을 자동 산출해 프로필 구성
- **SafetyPreGate**: 강풍·강우·폭염·혹한 안전 관문 (하드 제약, 롤백 보장)
- **예측 피드포워드**: 외부 기상 예보 기반 선행 제어
- **광합성 모델**: Big-Leaf 모델(A_max, K_L, T_opt, VPD_half)로 작물 맞춤 목표값 산출
- **누적 추적**: DLI(일적산광량), GDD(적산온도), VPD, CO₂ 일별 누적 관리
- **보정 시스템**: 센서·액추에이터 오차 캘리브레이션

### AI beta: 테스트 중인 버전입니다. 간략한 대화와 안내가 가능합니다.
사용자가 직접 AI API 키를 등록해 **조언형(Advisory)** 또는 **챗봇형(Chat)** AI를 구성할 수 있습니다.

- **다중 AI 제공자 지원**: Anthropic(Claude), Google(Gemini), OpenAI, Mistral, Groq, Ollama(로컬 LLM), MiniMax
- **파이프라인 역할 분리**: Router → Planner → Executor → Synthesizer → Worker 계층 구조
- **Tier 기반 분류기**: Tier0 사전분류(0-토큰) → Tier1 라우팅 → Tier2 실행으로 응답 속도 최적화
- **MCP(Model Context Protocol) 서버**: AI가 시설 상태 조회(Observe), 이상 분석(Diagnose), 설정 변경(Control)을 도구 호출로 수행
- **사용자 승인 게이트**: 쓰기 도구(설정 변경)는 60초 내 사용자 승인 필요, 감사 로그 90일 보존

### AI 지식 레이어
AI 학습에 필요한 지식을 사용자가 직접 구성할 수 있는 레이어 시스템입니다.

- **AIContextSource**: REST API / 문서 / 웹 URL / 내부 쿼리 등 외부 지식 소스 등록 및 주기적 동기화
- **AIDomainGlossary**: 스마트팜 도메인 용어사전 (pending/active 상태 관리)
- **AIFacilityLearning**: 시설별 패턴 학습 및 모델 버전 관리
- **AIUserProfile**: 사용자별 선호 에이전트 및 피드백 설정
- **AISummary / AIRecommendation**: 일간 환경 요약 및 AI 권장사항 기록
---

# v26.07.3 (2026-07-20) — 인앱 GitHub 업그레이드 정상화 · config 정본 정합

## 시스템 / 배포

- **인앱 GitHub 업그레이드 실패 3종 근본원인 수정**: (1) `ts`(moreutils) 미설치 시 실행 파이프가 SIGPIPE로 붕괴 → 업그레이드 미실행·로그 0바이트. `ts` 의존 17곳을 `command -v ts && ts || cat` 폴백으로 교체(타임스탬프만 잃고 로그·실행 보존). (2) `upgrade_install.sh`가 구 레이아웃 루트 `databases/`를 참조해 GIS `aot/databases/`와 어긋나 DB 복사에서 중단 → 경로 정합(+wipe 존재검사 `-d`→`-f`). (3) config가 매 import마다 stderr로 찍던 디버그가 `URL=$(... 2>&1)` 캡처에 섞여 `wget` URL을 파괴 → 스크립트 캡처 `2>/dev/null`·config 디버그 `AOT_CONFIG_DEBUG` 게이팅·regex raw-string으로 `SyntaxWarning` 제거.
- **config 패키지 이전 잔재 정합**: `config.py`를 `aot/config/__init__.py` 패키지로 병합한 뒤 남은 '존재하지 않는 `aot/config.py`' 유령 참조 2곳 교정 — `release_helper.py`(버전 자동범프가 `FileNotFoundError`로 사망하던 것, 릴리스 태그 불일치의 원인)·`settings_diagnostic_upgrade_master`(마스터 업그레이드 토글 무동작). 무력했던 2D→GIS 호환성 가드 경로도 교정.

---

# v26.07.2 (2026-07-19) — 에이전트 루프 아키텍처 전환

## AI 시스템

- **에이전트 루프 아키텍처**: 라우터 팬아웃(Router→Planner→Executor→Synthesizer) 대신 단일 상태보존 루프(전체 도구 카탈로그 + `ask_user` 확인 + 모델 불가지)로 전환, 기본 경로로 승격(레거시는 플래그로 즉시 롤백 가능하도록 보존)
- **레거시/UOC 서브시스템 정리**: 고아 상태였던 `ai/knowledge`·`ai/orchestration`·`ai/ui`·`ai/validation` 서브시스템 및 4종 shim 모듈, `utils/sse_manager.py` 삭제
- **지식베이스 강화**: 출처 추적(provenance), chunk 재사용 카운트·플래그 사유 필드 추가, 지식 주입 기본 활성화, 승격/보관(promotion/shelve) 서비스 신설
- **스마트팜코리아 외부 소스 연동**: 시설/노지/축산 3개 데이터셋을 AI 컨텍스트 소스로 등록·조회
- AI 라이브러리/채팅 UI 정비, 지도위젯의 구형 'AI 조언 표시' 옵션 제거(신규 스코프별 조언 칩으로 대체됨)

## 벡터 GIS / 지도

- **지도 LCP 지연 해소**: `/runtime` 센서 스냅샷을 논블로킹 캐시로 전환, 액추에이터 요약(LCP 요소)이 라이브 InfluxDB 조회를 기다리지 않도록 수정

## 노트

- 노트 드로어/입력 컴포넌트 UI 개선, 공용 드로어 CSS 컴포넌트 분리

## i18n

- 카메라 장치 카탈로그·GIS 입력 모듈·시설 용량산정 라벨의 한국어 하드코딩 문자열을 `gettext` 래핑 및 영문 기본값으로 전환, 전체 언어 번역 카탈로그 재추출

## DB 마이그레이션 (HEAD: `p5_52_agent_loop_default_on`)

`p5_46` → `p5_47`(knowledge provenance) → `p5_48`(flagged_reason) → `p5_49`(reuse_count) → `p5_50`(지식주입 기본on) → `p5_51`(agent_loop 카나리 플래그) → `p5_52`(agent_loop 기본전환)

---

# v26.07.1 (2026-07-18) — 레거시 2D→GIS 업그레이드 가드

- **업그레이드 호환성 가드**: 레거시 2D(지도) 에디션에서 GIS 에디션으로의 in-place 업그레이드를 차단(`upgrade_install.sh`). 두 에디션은 DB 스키마(alembic 계보)가 비호환이라 in-place 업그레이드 시 데이터가 손상됨. 2D 설치(config 단일모듈) 감지 시 아무것도 변경하기 전에 중단하고 신규 설치를 안내. → 레거시 사용자는 업그레이드가 GIS 최신(major 26)으로 연결되던 위험에서 보호됨.
- `upgrade-master` 도움말 URL을 `AoT-inc/AoT`로 정정(Mycodo 잔재 제거).

---

# v26.07.0 (2026-07-18) — 벡터 지도·3D·AI 공개 릴리스

벡터 지도(GIS)·3D 시설 관리·AI가 포함된 공개 버전입니다. 이전 2D 지도 기반 버전(v26.0.x)은 `legacy-2d` 브랜치에 보존되어 있으며, 본 버전과 DB 스키마가 호환되지 않습니다(구버전에서 업그레이드 불가, 신규 설치 필요).

## 벡터 GIS / 지도

- **드론·항공사진 이미지 오버레이** + 대형 이미지 XYZ 타일화(줌 대응)
- **측정값 패널**: 제어상태·정렬·풍향 표시, 문자 비율 조절 핸들, 패널 테마 전역 적용
- **액추에이터 오버레이 막대 렌더** + 소형 위젯 compact 모드
- **시설 라벨**: 충돌 시 중앙 기준 좌우 자동 배열, 단동 시설 구역 칩(bay/이름)
- **zone/facility 모달**: zone 정보 모달, 장치 작동 이력 차트, facility 센서 모달 통일
- **사이트 목록 모달**: 아코디언 + zone 드롭다운 + 사용자 정의 순서
- 레이어별 저작권 표시, 라벨 마스터 스위치, MapLibre 로컬 서빙 옵션
- 3D 위젯: renderMode 초기빌드·performance 모드·중복 렌더 수정
- 성능: MapTiler preconnect, 지도 위젯 공통 fetch 공유

## 환경 제어

- **창호 position-form PI 재설계**: 릴레이 진동 제거, 장치 실측 위치 기준 동기화
- **개도 규약 통일**(100%=열림): 커튼·차광막 이중반전 제거
- **안전 게이트**: 강풍/강우 시 내부 스크린(차광막·보온커튼) 강제 해제, 스크린 idle 기본값 걷힘
- **팬 모델 현실화**: 덕트 없는 벽면 배기팬은 창 열림 시 무력, 환기팬 구배의존·유효도 게이트
- **VPD 직접제어 전환** + 입력별 자동 VPD 계산 서비스
- PID 스케줄, 주간 스케줄, 환경 요약 스냅샷, 시설 사진 업로드

## LoRaWAN / ChirpStack

- **사이트 단위 Class A/C 스케줄러** + 공통 ChirpStack REST 헬퍼
- **밸브 명령 신뢰성**: 업링크 확인, 앱레벨 재전송, 전역 페이싱
- **스케줄러 강화**: reconcile·밸브 interlock·배터리 게이트·우선순위
- HB 전류 디코딩(7바이트), valve_active 전류 기반 판정, RSSI/SNR 측정타입 정정
- ChirpStack API 키를 API Keys 저장소로 통합, tenant/application 필터

## Function / 시퀀스

- **시퀀스 장치 그룹(동시작동)**: 그룹 묶기/해제, 위젯 행 접기
- **요일별 작동**: 요일 선택, 요일별 그룹·작동시간, 리더 자동상속
- **통합 모달 시간휠 UI** + 위젯 목록 재설계·전역 툴팁
- 단일 장치 시간축 누적/지점 합산 function, sum_accumulate 즉시 측정 버튼
- 액션 순서 저장, 소스 디바이스 타임존 기준 집계, execute_now 기준점 리셋 등 다수 수정

## UI / UX

- **색상 시스템**: 테마 프리셋(측정 밴드·차트 시리즈 포함), z-index 토큰화
- **브랜딩**: 네비바 브랜드 이미지(SVG·GIF·WebP), 데몬/앱 상태 표시 개선
- **그래프**: 이전 기간 on-demand 로드, 기간버튼 최신시점 앵커 수정, 모바일 툴팁
- 모달 모던화(모바일 중앙 카드), 위젯 설정 모달에서 탭 이동, 장치 탭 이동
- i18n: GIS 오버레이 범례 등 다국어 번역 정비, 하드코딩 영어 메시지 gettext 래핑

## AI 시스템

- **v3.1 티어 아키텍처**: Tier0 사전분류 → Router → Planner → Supervisor → Synthesizer 파이프라인 재편, 목표지향 연속 실행 루프
- **AI 엔티티 관리**: Input / Output / Function / GIS 배치 / AI Agent 5종을 AI가 생성·편집·삭제, 변이 작업은 사용자 승인 게이팅
- **지식 다이제스트 파이프라인**: 멀티사이트 facility 스코핑, 환경제어 조언 연동, 시스템 지식 레이어
- **지도 연동**: 지도 뷰포트 스코프 장치 제어, 배치 승인, 위치(구역) 기반 장치 해석, 스코프별 AI 조언 칩·Q&A
- **서버측 페이지 컨텍스트 조립**: 대시보드 상태를 서버에서 구성해 DOM 스크래핑 대체
- **다국어**: 사용자 대면 문자열·분류 규칙 언어무관화
- 안정화: MCP 기동·OOM 크래시루프·장치목록 조회·팬텀 승인버튼·대화맥락 수정

## 시스템 / 배포

- 환경 적응형 gunicorn 스레드, 서비스 재시작·리로드 일원화
- Docker: aot 사용자/그룹 생성, InfluxDB 포트 127.0.0.1 전용 바인딩
- 대시보드 `/last`·`/past` 요청을 배치 API로 통합해 요청 폭증 해소
- JS 빌드 오케스트레이터(rollup/esbuild) — geo/notes 번들 통합 관리

## DB 마이그레이션 (HEAD: `p5_46_input_auto_vpd_toggle`)

26.06에서 alembic 계보를 재베이스라인하여 구 8.16.x 계열과 분리했습니다. v26.0.x(legacy-2d) DB는 본 버전으로 마이그레이션할 수 없습니다.

---

# v26.05.0 (2026-05-18) — 최초 공식 릴리스

## AI 시스템

- **MCP 서버** (`aot/mcp_server/`): FastMCP 기반, stdio/HTTP SSE 모드 지원
  - `Observe` 도구: 시설 상태·센서 이력·액추에이터 명령값 조회
  - `Diagnose` 도구: 센서 이상 탐지·환경 제어 성능 분석
  - `Control` 도구: VPD 목표값·메서드 제어점 변경, 수동 잠금 (사용자 승인 필요)
- **MCPAuditLog / MCPConfirmation**: 도구 호출 이력 및 승인 큐
- **AIAgent `allowed_tools`**: 에이전트별 MCP 도구 접근 범위 제한

## 벡터 GIS

- **GeoFacility fittings**: 창호·도어·커튼 등 시설 구성 요소 등록 및 GeoShape 연결
- **시설 센서 바인딩** (`facility_sensors.py`): 실내외 센서를 역할별로 시설에 연결, 가중 평균 산출
- **시설 풍향 분석** (`facility_wind.py`): 외부 풍향 데이터 처리 및 개구부 방위각 비교
- **GeoFacility timezone** 필드 추가

## 통합 환경 제어

- **Function cumulative state**: DLI·GDD 일별 누적 및 보상 제어 (`FunctionCumulativeState`)
- **Function crop preset**: 작물 광합성 파라미터 DB 저장 (`FunctionCropPreset`)
- **lighting 액추에이터**: `ACTUATOR_KINDS` 정식 등록, R2 경로(보광 등록 시 활성)
- **풍향 차등 SafetyPreGate**: windward 60° arc 내 개구부만 강제 폐쇄, leeward 환기 유지
- **EffectFn 면적·단열 가중**: 개구부 면적·u_effective 반영 효과 산출
- **GIS 기반 profile builder**: GeoShape per-device 우선 조회, fallback 균등 분할 유지
- **env_control 모듈**: `authority`, `calibration`, `cumulative_tracker`, `forecast_feedforward`, `photosynthesis`, `group_expander`, `ext_context_fallback`
- **작물 프리셋**: 상추·파프리카·고추·딸기·토마토 VPD 프리셋 기본 제공

## DB 마이그레이션 (HEAD: `p5_6_geo_facility_fittings`)

`p2_5` → `p3_5` → `p4_3` → `p4_4` → `p5_1` → `p5_5` → `p5_3` → `p5_6`
