# Phase 1 착수 지시서 — Geo/Facility 3D Preview 정상화 + GLTF 임포트

- **상위 설계문서**: [docs/design_facility_3d_preview.md](design_facility_3d_preview.md)
- **빌드 범위**: `aot/aot_flask/` 단독
- **승인 상태**: 본 지시서는 **착수 전 사용자 최종 승인 대기**. 승인 문구: "Phase 1 진행"
- **선행 조건**: 본 지시서가 directive.prompt에 포함되어야 T2 실행 가능

---

## 1. 목표

1. spec 패널 ↔ 3D Preview 양방향 바인딩 정상화 (회귀 0).
2. 외부 `.glb`/`.gltf` 모델 업로드 및 시설 단위 첨부 가능.
3. `/geo/model_assets` 진입 페이지(GLTF 임포트 자산만 표시)와 시설 § 인라인 모달 구축.
4. 서버 사이드 썸네일 생성 (실패 시 폴백).
5. 단위 선택(기본 미터) 사용자 설정 도입. DB는 미터 정규화.
6. 기존 시설 렌더 100% 역호환.

## 2. 사전 조사 (Pre-investigation) — 코드 변경 전 필수

1. `aot/databases/models.py`에서 `GeoFacility`/`GeoShape` 정의 위치·관계 확인.
2. 사용자 설정 저장 경로 (`routes_settings.py`, 모델, 템플릿) 식별.
3. `aot-facility-3d.js`의 외부 호출자(`aot-facility-widget.js`, 템플릿) 식별 — 시그니처 보존.
4. `output_entry.html` 등에서 spec 입력 폼 ↔ 3D 갱신 트리거 경로 추적.
5. `facility_calc.py`에서 spec 항목 전수 목록 작성 → 인스펙터 누락 필드 식별.
6. 환경에 `trimesh`/`pyrender` 설치 가능 여부 확인 (불가 시 §5.2 폴백 사용).

**산출**: `investigation_summary` (지시 보고서에 포함). 위 6항목 각각 결과 기록.

## 3. 구현 작업 (순서 보장)

### 3.1 DB 마이그레이션
- 신규 테이블 `geo_model_asset` (P1 컬럼셋 — `is_public` 제외, 설계문서 §4.1).
- `geo_facility`에 컬럼 추가: `model_asset_uuid TEXT NULL`, `model_transform JSON NULL`, `render_mode TEXT NOT NULL DEFAULT 'parametric'`.
- 다운그레이드 스크립트 포함.

### 3.2 백엔드 모듈
| 파일 | 역할 |
|---|---|
| `aot/aot_flask/geo/units.py` (신규) | `to_meters(v, unit)`, `from_meters(v, unit)`, `SUPPORTED_UNITS` |
| `aot/aot_flask/geo/model_asset_io.py` (신규) | `ModelAssetManager.{list,get,create,update,delete,attach_to_facility,detach}` |
| `aot/aot_flask/geo/preview_renderer.py` (신규) | `render_preview(asset) -> path`, 3-tier 폴백 |
| `aot/aot_flask/routes_general.py` (수정) | §5 라우트 등록 (자산 CRUD/업로드/시설 첨부/썸네일/페이지) |
| `aot/aot_flask/routes_settings.py` (수정) | `length_unit` 키 처리 |
| `aot/databases/models.py` (수정) | `GeoModelAsset` 모델 + `GeoFacility` 컬럼 추가 |

### 3.3 업로드 가드 (필수 보안)
- 확장자: `.glb`, `.gltf` 화이트리스트
- 매직바이트: glb의 `glTF` 헤더 검증
- 크기 상한: 25 MB (`MAX_CONTENT_LENGTH` 또는 라우트 내 검사)
- 저장 경로: `aot/aot_flask/static/uploads/model_assets/<uuid>.<ext>` — uuid 외부 노출 금지(파일명 정규화)
- 디렉터리 트래버설 차단

### 3.4 프런트엔드 모듈 분할
**순수 이동**(동작 변경 금지). `aot-facility-3d.js` (886줄) →
```
core/scene.js        -- Scene/Camera/Renderer/Lights/Controls
core/parametric.js   -- _buildMultiSpanShape, buildSideVentSash 등
core/materials.js    -- MAT 팔레트
```
기존 `aot-facility-3d.js`는 위 모듈을 import하는 얇은 진입점으로 축소. 외부 호출 API는 그대로.

### 3.5 양방향 바인딩
- `core/scene.js`에 `FacilityState` 도입 (단일 상태 객체, pub/sub).
- spec 입력 변경 → `FacilityState.patch()` → 150ms 디바운스 → 부분 리렌더 + 저장 큐.
- spec 미반영 필드는 §2.5 조사 결과를 토대로 보강.

### 3.6 GLTF 로딩 경로
- `assets/gltf_loader.js` (신규) — 캐시 + 에러 처리.
- 시설 로딩 시 `render_mode==='asset'`이면 GLTF 로드 → `model_transform` 적용 → 씬에 부착.
- 파라메트릭 메시 빌드 스킵.

### 3.7 자산 라이브러리 UI (P1 한정)
- `ui/asset_library.js` (신규) — `mode: 'page' | 'modal'`.
- P1에서는 **GLTF 임포트 자산만** 표시 (kind 필터). 프리미티브 등록 UI는 P2.
- 페이지: `/geo/model_assets` (목록 + 업로드 + 삭제).
- 모달: 시설 § 3D Preview 우상단 "자산 라이브러리" 버튼.

## 4. 검증

### 4.1 기능 검증
- [ ] spec 필드 N개 변경 → 3초 이내 3D 반영 (조사 단계에서 전수 목록 작성, 케이스별 PASS/FAIL)
- [ ] 25 MB `.glb` 업로드 → 시설 첨부 → 새로고침 후 유지
- [ ] 잘못된 확장자/크기 업로드 거부 (4xx)
- [ ] 자산 삭제 시 참조 시설 있으면 409
- [ ] `render_mode='parametric'` 시설은 변경 전과 동일 외형 (스크린샷 비교)

### 4.2 안정성 검증
- [ ] Three.js geometry/material dispose 누락 없음 (씬 재빌드 10회 후 메모리 안정)
- [ ] 단위 변환 왕복 정합: `from_meters(to_meters(v, u), u) == v` (부동소수 오차 허용)

### 4.3 회귀 검증
- [ ] 기존 시설 5종(gable/arch/flat/box + 다중베이) 시각 비교
- [ ] 기존 spec 저장/로드 흐름 (`FacilityManager`) 변경 없음

## 5. 산출물 (Done Report 필수 포함)

- 생성 파일 목록 (전체 경로)
- 수정 파일 목록 (전체 경로 + 변경 요약)
- 실행 명령 및 출력 요약 (마이그레이션, 테스트)
- §2 사전 조사 결과 (`investigation_summary`)
- §4 검증 체크리스트 결과
- 회귀가 발견된 항목 (있다면 즉시 보고, 임의 수정 금지)

## 6. 금지 사항 (헌법 준수)

- **삭제 작업 금지**: 본 Phase는 신규 추가만. 기존 파일/테이블/컬럼 제거 없음.
- **다른 빌드 수정 금지**: `aot/aot_flask/` 외 변경 발견 시 즉시 중단·보고.
- **--no-verify 등 훅 우회 금지**.
- **자의적 리팩터 금지**: §3에 명시된 모듈 분할 외 추가 정리 금지.
- **자의적 의존성 추가 금지**: `trimesh`/`pyrender` 외 신규 패키지 도입 시 사전 승인 필요.

## 7. 미해결 시 에스컬레이션

다음 상황은 즉시 작업 중단 후 보고:
- `trimesh`/`pyrender` 설치 불가 → 폴백 방식 합의 필요
- 기존 시설 데이터 회귀 발견 → 원인 분석만 제시
- spec 항목 중 인스펙터-3D 매핑이 모호한 필드 발견 → 결정 요청

---

## 승인 절차

본 지시서로 진행하려면 다음 문구 회신:

> **"Phase 1 진행"**

수정 사항이 있으면 항목 번호로 지정해 주십시오 (예: §3.6 GLTF 캐시 정책 변경).
