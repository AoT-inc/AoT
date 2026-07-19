# Geo/Facility § 3D Preview — 설계 문서

- **작성일**: 2026-05-13
- **상태**: Draft (승인 대기)
- **빌드 범위**: `aot/aot_flask/` (다른 빌드는 영향 없음)
- **선정안**: **C안 — 하이브리드(단계적 도입) + 사용자 기본형 모형 등록**

---

## 1. 목적과 범위

### 1.1 해결할 문제
1. **Spec 미반영**: Geo/Facility § 3D Preview에서 spec 패널의 설정 변경이 3D 미리보기에 일관되게 반영되지 않음.
2. **외부 모델 사용 불가**: 사용자가 SketchUp/Blender 등 외부 도구에서 만든 3D 모형을 가져올 수 없음.
3. **사용자 자작 도면 불가**: 시설 형태가 파라메트릭 프리셋(gable/arch/flat/box)에 묶여 있어 임의 형태를 표현할 수 없음.
4. **재사용 자산 부재**: 자주 쓰는 기본형(박스, 실린더, 폴리곤 압출 등)을 라이브러리로 등록·재사용하는 흐름이 없음.

### 1.2 범위
- 포함: 3D Preview 렌더러 확장, 모델 임포트/익스포트, 사용자 등록 프리미티브 라이브러리, spec ↔ 3D 양방향 바인딩.
- 제외(추후 검토): 풀-스펙 SketchUp 호환 모델링, 다중 사용자 동시 편집, 모바일 터치 제스처 최적화.

### 1.3 비목표 (Non-goals)
- SketchUp의 Push/Pull 전체 기능 재현 — Phase 3에서 최소 기능만.
- `.skp` 네이티브 파싱 — 외부 변환(.skp → .glb) 사용 권장.
- 물리 시뮬레이션, 그림자 정합, 포토리얼 렌더링.

---

## 2. 현황

### 2.1 자산
| 자산 | 경로 | 비고 |
|---|---|---|
| 3D 씬 빌더 | `aot/aot_flask/static/js/widget/AoT_facility/aot-facility-3d.js` (886 lines) | 파라메트릭 온실 메쉬 생성, Three.js r160+ |
| 위젯 래퍼 | `aot/aot_flask/static/js/widget/AoT_facility/aot-facility-widget.js` (219 lines) | 패널 통합 |
| Three.js 코어 | `three.min.js` | 번들됨 |
| 로더 | `GLTFLoader.js` (4725) | GLTF/GLB 지원 |
| 컨트롤 | `OrbitControls.js` (1421) | MapControls 사용 중 |
| 충돌/스냅 | `three-mesh-bvh.js` (8410) | 정밀 hit-test 가능 |
| 백엔드 CRUD | `aot/aot_flask/geo/facility_io.py` (`FacilityManager`) | `GeoFacility` + 외곽/베이 `GeoShape` |
| 계산 | `aot/aot_flask/geo/facility_calc.py` (371) | 치수·면적 계산 |
| 헬퍼 | `aot/aot_flask/geo/facility_geo_helpers.py` (202) | 좌표 변환 |
| 레지스트리 | `context_layer/facility_registry.yaml` | 시설 메타데이터 |

### 2.2 추정 결함 (Phase 1에서 사실 확인 필요)
- `aot-facility-3d.js`가 spec 변경을 받아 전체 씬을 재생성하는 경로가 단일/단방향임.
- spec 패널 → 백엔드 저장 → 3D 재로드 흐름에서 일부 필드(cover_material 보조 옵션, 베이 간격 등)가 누락될 가능성.

---

## 3. 채택 방향: C안 (하이브리드, 단계적)

| Phase | 산출물 | 기간 (목표) | 의존성 |
|---|---|---|---|
| **P1. Spec 바인딩 정상화 + GLTF 임포트** | spec ↔ 3D 양방향, 외부 `.glb/.gltf` 업로드, 시설별 외부 모델 1개 첨부 | 1–2주 | 없음 |
| **P2. 사용자 기본형 모형 등록 라이브러리** | 박스/실린더/구/콘/평면/압출 폴리곤 등 프리미티브 라이브러리, 등록·편집·재사용 | 1–2주 | P1 |
| **P3. SketchUp-라이트 드로잉 도구** | 폴리곤 2D 스케치 → extrude, 스냅·그리드, 인스펙터 | 2–3주 | P2 |

각 Phase는 독립 PR로 분할하고, 다음 Phase 진입 전 사용자 검증.

---

## 4. 데이터 모델 변경

### 4.1 신규 테이블 (DB 모델)

#### `GeoModelAsset` — 사용자 등록 자산
```
id              INTEGER PK
unique_id       UUID
owner_user_id   INTEGER
name            TEXT                 -- "내 비닐하우스 A형"
kind            TEXT                 -- 'primitive' | 'imported_gltf' | 'extruded_polygon'
spec_json       JSON                 -- 종류별 파라미터(아래 4.2 참고). 모든 길이값은 미터 기준.
is_public       BOOLEAN NOT NULL DEFAULT FALSE   -- 공용 공유 여부 (P2에서 추가)
authored_unit   TEXT     NOT NULL DEFAULT 'm'    -- 작성 당시 사용자 단위 (참고용, 'mm'|'cm'|'m'|'in'|'ft')
preview_png     TEXT NULL            -- 서버 렌더 썸네일 경로
preview_status  TEXT NOT NULL DEFAULT 'pending'  -- 'pending'|'ok'|'failed'
source_file     TEXT NULL            -- imported_gltf인 경우 업로드 파일 경로
tags            TEXT NULL            -- 쉼표 구분 (라이브러리 필터용)
created_at      DATETIME
updated_at      DATETIME
```

**P1 시점 도입 컬럼**: `is_public`을 제외한 전부. **P2 시점 도입**: `is_public`(UI 토글 동반). 마이그레이션을 2단계로 분리.

#### `GeoFacility` 확장 (기존 테이블)
```
+ model_asset_uuid  TEXT NULL    -- GeoModelAsset.unique_id (선택)
+ model_transform   JSON NULL    -- { position:[x,y,z], rotation:[rx,ry,rz], scale:[sx,sy,sz] }
+ render_mode       TEXT         -- 'parametric' | 'asset'  (기본: 'parametric')
```

`render_mode='asset'`이면 파라메트릭 빌더를 건너뛰고 `model_asset_uuid`를 로드.

### 4.2 `GeoModelAsset.spec_json` 스키마 (kind 별)

```jsonc
// kind = "primitive"
{
  "shape": "box" | "cylinder" | "sphere" | "cone" | "plane",
  "dimensions": { "w": 5.0, "h": 3.0, "d": 4.0, "r": 1.5, "segments": 32 },
  "material": { "color": "#9ecfef", "opacity": 0.6, "metalness": 0.0, "roughness": 0.5 },
  "origin": "bottom_center" | "center"
}

// kind = "extruded_polygon"
{
  "polygon_2d": [[x1,y1], [x2,y2], ...],   // 닫힌 폴리곤
  "extrude_height": 3.0,
  "bevel": { "enabled": false, "thickness": 0.0, "size": 0.0 },
  "material": { ... }
}

// kind = "imported_gltf"
{
  "filename": "barn_a.glb",
  "bounding_box": { "min":[x,y,z], "max":[x,y,z] },   // 캐시
  "default_scale": 1.0
}
```

### 4.3 `context_layer/facility_registry.yaml`
사용자 자산 카탈로그는 DB가 SoT(Source of Truth). YAML은 변경하지 않음.

### 4.4 사용자 설정 — 단위 체계
- 신규 키 `length_unit` 추가 (값: `mm`|`cm`|`m`|`in`|`ft`, 기본 `m`).
- 저장 위치는 기존 사용자 설정 흐름을 따른다 (`aot/aot_flask/routes_settings.py` 라우트 확장).
- **저장 규칙**: DB는 항상 미터로 정규화. 단위는 UI 입출력 변환에만 사용.
- 변환 헬퍼는 `aot/aot_flask/geo/units.py` 신설(상수 + `to_meters(value, unit)` / `from_meters(value, unit)`).

---

## 5. 백엔드 API

신규 라우트는 `aot/aot_flask/routes_general.py` 또는 `geo_*` 신규 모듈에 추가.

| Method | Path | 설명 |
|---|---|---|
| `GET` | `/api/geo/model_assets` | 자산 목록 (사용자 소유 + 공용) |
| `POST` | `/api/geo/model_assets` | 신규 자산 등록 (primitive / extruded_polygon: JSON, imported_gltf: multipart) |
| `GET` | `/api/geo/model_assets/<uuid>` | 단일 조회 |
| `PUT` | `/api/geo/model_assets/<uuid>` | 수정 (이름·spec·material) |
| `DELETE` | `/api/geo/model_assets/<uuid>` | 삭제 (참조 시설 있으면 409) — **삭제 4단계 프로토콜 적용** |
| `GET` | `/api/geo/model_assets/<uuid>/preview` | 썸네일 |
| `POST` | `/api/geo/facility/<uuid>/attach_model` | 시설에 자산 연결 + transform 저장 |
| `DELETE` | `/api/geo/facility/<uuid>/attach_model` | 연결 해제 → `render_mode='parametric'` 복귀 |
| `POST` | `/api/geo/model_assets/<uuid>/regenerate_preview` | 서버 사이드 썸네일 재생성 (등록·수정 시 자동 호출) |

### 5.1 페이지 라우트
| Method | Path | 설명 |
|---|---|---|
| `GET` | `/geo/model_assets` | 자산 라이브러리 페이지(D안 메인 진입) — `routes_general.py`에 등록 |
| `GET` | `/geo/model_assets/<uuid>` | 자산 상세 딥링크 (위 페이지에서 라우터 처리) |

### 5.2 썸네일 렌더 워커
- 위치: `aot/aot_flask/geo/preview_renderer.py` 신설.
- 의존성: `trimesh`(GLB/메시 처리) + `pyrender`(오프스크린 렌더, EGL/osmesa). 환경 의존성 이슈 대비:
  - 1차: `pyrender` 시도
  - 2차 폴백: `trimesh.Scene.save_image()` (Pyglet 헤드리스)
  - 3차 폴백: 회색 플레이스홀더 + `preview_status='failed'` 마킹
- 등록 직후 동기 호출(소형 자산), 25 MB 근접 자산은 백그라운드 큐(`threading` 또는 기존 스케줄러 활용 검토).

업로드 보안:
- 확장자 화이트리스트: `.glb`, `.gltf`
- 크기 상한: 25 MB (설정 가능)
- 저장 경로: `aot/aot_flask/static/uploads/model_assets/<uuid>.<ext>`
- 서빙 시 `Content-Type: model/gltf-binary` 명시, 디렉터리 트래버설 방지

---

## 6. 프런트엔드 설계

### 6.1 모듈 분할 (`aot-facility-3d.js` 리팩터)
현재 단일 IIFE → 모듈 분리:
```
static/js/widget/AoT_facility/
├── core/
│   ├── scene.js          -- Scene/Camera/Renderer/Lights/Controls 생성
│   ├── parametric.js     -- 기존 _buildMultiSpanShape 등 (이전됨)
│   └── materials.js      -- MAT 팔레트
├── assets/
│   ├── primitives.js     -- box/cylinder/sphere/cone/plane 빌더
│   ├── extruded.js       -- 2D 폴리곤 → Three.ExtrudeGeometry
│   ├── gltf_loader.js    -- GLTFLoader 래퍼 + 캐시
│   └── transform.js      -- gizmo(이동/회전/스케일)
├── ui/
│   ├── inspector.js      -- 우측 패널 spec 편집기
│   ├── asset_library.js  -- 자산 목록 모달
│   └── upload_dialog.js  -- 파일 업로드 UI
└── aot-facility-3d.js    -- 진입점 (얇은 오케스트레이터)
```

기존 함수 시그니처는 `parametric.js`에서 그대로 유지하여 외부 호출자 영향 없음.

### 6.2 Spec ↔ 3D 양방향 바인딩
- **단일 상태 객체** `FacilityState`: spec(파라메트릭 또는 asset 참조) + view(camera, selection) + dirty 플래그.
- `FacilityState.subscribe(fn)`: spec 변경 시 부분 재빌드 (전체 씬 폐기 금지).
- 인스펙터 패널의 입력 변경 → `FacilityState.patch({...})` → 디바운스(150ms) → 부분 리렌더 + 저장 큐.
- 저장은 `PUT /api/geo/facility/<uuid>` (기존 라우트 재사용), 자산 연결은 별도 엔드포인트(§5).

### 6.3 자산 등록 UX
- **자산 라이브러리 모달**: 좌측 목록(사용자 + 공용), 우측 미리보기(Three.js 미니 캔버스).
- **신규 등록 폼** (kind 선택):
  - `primitive`: shape 드롭다운 + 치수 입력 + 머티리얼.
  - `extruded_polygon`: 캔버스에서 2D 폴리곤 그리기(클릭으로 정점 추가, 더블클릭으로 닫기) + 압출 높이.
  - `imported_gltf`: 드래그-드롭/파일 선택 → 미리보기 → 저장.
- **시설에 적용**: "이 시설에 사용" 버튼 → 시설 3D Preview로 복귀하고 `model_transform` 기즈모 활성.

### 6.4 의존성 추가 검토
- 필수: 없음 (현재 번들로 충분).
- 선택: `TransformControls.js` (Three.js examples) — 자산 이동/회전/스케일 기즈모. ≈40 KB. **P2에서 추가**.

---

## 7. 마이그레이션

1. Alembic 또는 프로젝트의 DB 마이그레이션 규약에 따라:
   - `geo_model_asset` 테이블 생성
   - `geo_facility`에 `model_asset_uuid`, `model_transform`, `render_mode` 컬럼 추가 (NULL 허용, 기본 `'parametric'`)
2. 기존 시설은 모두 `render_mode='parametric'`로 동작 — **역호환 보장**.
3. 다운그레이드 스크립트 준비 (컬럼/테이블 drop).

---

## 8. 보안 / 안정성

| 항목 | 대응 |
|---|---|
| 임의 파일 업로드 | 확장자/MIME/매직바이트 검사, 25 MB 상한, 별도 디렉터리 격리 |
| GLTF 내장 스크립트 | GLTFLoader는 기본적으로 JS 미실행. 외부 텍스처 URL은 동일출처로 제한 |
| 자산 삭제 시 시설 참조 | DELETE에서 참조 카운트 확인 → 409 + 참조 시설 목록 반환 |
| 헌법 Art.5 (삭제 보호) | DELETE는 4단계 프로토콜(IDENTIFY/IMPACT/RECOVERY/CONFIRM) 준수, T2 실행 시 인용 확인 |
| 메모리 누수 | Three.js 씬 폐기 시 geometry/material/texture `dispose()` 강제 (lint 규칙 추가) |

---

## 9. 검증 계획

### 9.1 Phase 1 합격 기준
- [ ] spec 패널의 모든 필드 변경이 3초 이내 3D 반영
- [ ] `.glb` 25 MB 파일 업로드 → 시설에 첨부 → 새로고침 후에도 유지
- [ ] `model_asset_uuid=NULL` 시설은 기존과 100% 동일하게 렌더 (회귀 없음)

### 9.2 Phase 2 합격 기준
- [ ] 5종 프리미티브(box/cylinder/sphere/cone/plane) 등록 가능
- [ ] 등록 자산을 2개 이상 시설에 재사용 시 동일 외형
- [ ] 자산 편집 → 참조 시설 모두에 즉시 반영
- [ ] 참조 시설이 있는 자산은 삭제 불가(409)

### 9.3 Phase 3 합격 기준 (착수 시 별도 확정)
- 2D 폴리곤 스케치 → 압출 자산 등록
- 그리드 스냅 ON/OFF, 엣지 스냅 동작
- Undo/Redo 10단계

---

## 10. 리스크 & 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| `aot-facility-3d.js` 리팩터 중 회귀 | 기존 사용자 시설 깨짐 | 모듈 분할은 **순수 이동**만, 기능 변경 금지. 시각 회귀 스냅샷 테스트. |
| GLTF 파싱 비용/메모리 | 대형 모델로 브라우저 부담 | bounding box 캐시, draco 압축 권장, 25MB 상한 |
| 사용자 자산 권한 모델 부재 | 다중 사용자 환경에서 자산 충돌 | P1에서는 owner_user_id로 사용자별 격리, 공용 플래그는 P2 |
| Three.js 버전 업그레이드 | 기존 코드 깨짐 | r160 고정, 업그레이드는 별도 작업으로 분리 |

---

## 11. 작업 분해 (Phase 1 착수용)

### Phase 1 작업 목록
1. **DB 모델**: `GeoModelAsset` (P1 컬럼셋 — `is_public` 제외) 모델 + 마이그레이션 (`aot/databases/models.py`).
2. **DB 모델**: `GeoFacility`에 `model_asset_uuid`, `model_transform`, `render_mode` 3개 컬럼 + 마이그레이션.
3. **단위 헬퍼**: `aot/aot_flask/geo/units.py` 신설 (`to_meters` / `from_meters`).
4. **사용자 설정**: `length_unit` 키 추가 (`routes_settings.py` + 설정 UI).
5. **자산 매니저**: `aot/aot_flask/geo/model_asset_io.py` — `ModelAssetManager` CRUD.
6. **썸네일 렌더러**: `aot/aot_flask/geo/preview_renderer.py` (서버 사이드, 3-tier 폴백).
7. **API 라우트**: §5의 자산 CRUD + 업로드 + 시설 첨부 + 썸네일 재생성 (`routes_general.py`).
8. **페이지 라우트**: `/geo/model_assets` (D안 메인 진입, 단 P1에서는 임포트한 GLTF만 표시 — 프리미티브 등록 UI는 P2).
9. **JS 모듈 분할**: `aot-facility-3d.js` → `core/` + `assets/` + `ui/` 구조 (순수 이동, 동작 변경 금지).
10. **상태 관리**: `core/scene.js`에 `FacilityState` 도입, 인스펙터와 양방향 바인딩 (디바운스 150ms).
11. **GLTF 로더**: `assets/gltf_loader.js` + 시설 첨부 모델 렌더 경로 (`render_mode='asset'`).
12. **인라인 진입**: 시설 § 3D Preview 우상단 "자산 라이브러리" 버튼 → 모달 마운트 (P1은 GLTF 업로드/선택만).
13. **인스펙터 보강**: spec 미반영 항목 식별 후 수정 (조사 단계 산출물 필요).
14. **회귀 검증**: 기존 시설 5종 시각 비교 (스냅샷 또는 수동 비교 체크리스트).

### Phase 2 작업 목록
1. **DB**: `GeoModelAsset.is_public` 컬럼 추가 마이그레이션.
2. **프리미티브 빌더**: `assets/primitives.js` (box/cylinder/sphere/cone/plane).
3. **자산 라이브러리 UI**: `ui/asset_library.js` — `mode: 'page' | 'modal'` 양용 컴포넌트.
4. **신규 등록 폼**: kind=`primitive` 입력 폼(단위 토글 포함), kind=`extruded_polygon` 2D 캔버스.
5. **TransformControls 통합**: 시설에 첨부된 자산의 이동/회전/스케일 기즈모.
6. **참조 카운트**: 자산 ↔ 시설 N:M 참조 검증, 삭제 시 409 응답.
7. **공용 공유 UX**: `is_public` 토글, 공용 자산 목록 필터.
8. **태그/검색**: 자산 카탈로그 검색/태그 필터.

---

## 12. 확정 사항 (2026-05-13 결정)

### 12.1 자산 공용 공유
- **결정**: P2 구현 완료 직후 즉시 도입.
- **적용**: `GeoModelAsset.is_public BOOLEAN NOT NULL DEFAULT FALSE` 컬럼을 P2에서부터 포함. UI 토글은 P2 라이브러리 모달의 자산 편집 폼에 추가.
- **권한**: `owner_user_id`만 토글 가능, 비소유자는 읽기 전용.

### 12.2 썸네일 생성
- **결정**: 서버 사이드 렌더링.
- **구현**: Python에서 `pyrender` 또는 `trimesh` + headless EGL/osmesa로 GLB/spec → PNG 256×256. 라우트: `POST /api/geo/model_assets/<uuid>/regenerate_preview` (등록·수정 시 자동 호출).
- **저장**: `aot/aot_flask/static/uploads/model_assets/previews/<uuid>.png`. ETag 캐시.
- **폴백**: 서버 렌더 실패 시 회색 플레이스홀더 + 비동기 재시도 큐.

### 12.3 드로잉 캔버스 시점 (P3)
- **결정**: 사용자 선택 가능 — Plan(평면도, 기본), Front(정면도), Side(측면도), Free(자유 카메라).
- **UI**: 드로잉 도구 진입 시 상단 툴바에서 뷰 토글. Free 모드에서는 사용자가 지정한 작업 평면(work plane) 위에 정점 투영.
- **저장**: 폴리곤 자체는 2D 좌표 + 어느 평면에서 그려졌는지 메타(`spec_json.draw_plane: 'xy'|'xz'|'yz'|'custom'`).

### 12.4 단위 체계
- **결정**: 사용자 선택, 기본값 미터(SI).
- **지원**: `mm`, `cm`, `m`, `in`, `ft`.
- **저장 규칙**: DB는 **항상 미터로 정규화** 저장 (혼동 방지). UI 표시·입력 시점에 사용자 단위로 변환.
- **사용자 설정**: 기존 사용자 설정 테이블에 `length_unit` 키 추가 (`aot/aot_flask/routes_settings.py`).
- **자산 단위 메타**: `GeoModelAsset.spec_json.authored_unit`을 기록(참고용), 실제 값은 미터.

### 12.5 자산 라이브러리 진입 경로 (제안)

세 가지 후보를 비교한 뒤 **D안(하이브리드)** 권장.

| 안 | 진입 경로 | 장점 | 단점 |
|---|---|---|---|
| A | Geo 페이지 사이드바 메뉴 "3D 자산" 단독 페이지 | 자산을 독립 1급 객체로 인지, 대량 관리 용이 | 시설 작업 중 컨텍스트 전환 필요 |
| B | 시설 § 내 모달만 | 작업 흐름 단절 없음, 학습 비용 낮음 | 자산을 시설과 분리해서 보기 어려움, 검색·일괄작업 빈약 |
| C | 설정(Settings) 하위 메뉴 | 관리자 작업으로 분리 | 일반 사용자가 찾기 어려움, 시설 작업 중 호출 불편 |
| **D** | **하이브리드: Geo 페이지 사이드바 + 시설 § 모달 양쪽 모두** | **A의 관리성 + B의 작업 흐름. 동일 컴포넌트(`ui/asset_library.js`) 재사용** | 모달과 페이지 두 진입점 동기화 필요 (단일 상태로 해결) |

#### D안 상세
- **메인 진입**: Geo 페이지 좌측 사이드바에 "3D 자산" 항목 추가 → 전용 페이지 `routes_general.py` 내 `/geo/model_assets`.
  - 목록(그리드/리스트 토글), 검색, 태그 필터, 일괄 삭제(헌법 Art.5 4단계 프로토콜), 공용 공개 토글, 신규 등록.
- **인라인 진입**: 시설 spec 패널 § 3D Preview 우상단에 "자산 라이브러리" 버튼 → 동일 컴포넌트를 모달로 마운트.
  - 모달은 "이 시설에 사용" 버튼 노출, 선택 시 모달 닫고 시설에 첨부 + 기즈모 활성.
- **딥링크**: `/geo/model_assets/<uuid>` 직접 열기 지원 (자산 공유 URL).
- **컴포넌트 일원화**: `ui/asset_library.js`는 mount 옵션으로 `mode: 'page' | 'modal'` 받기. 페이지 모드는 라우터로 마운트, 모달 모드는 시설 위젯이 호출.

**확정 요청**: D안으로 진행해도 되겠는지 회신 부탁드립니다. (다른 안 선택 시 §6.3 자산 라이브러리 UX와 §11 작업 분해의 라우트 항목을 그에 맞게 수정)

---

## 13. 변경 이력

| 일자 | 변경 | 작성 |
|---|---|---|
| 2026-05-13 | 초안 | T2 |
| 2026-05-13 | §12 결정사항 반영 (공용공유 P2 동시, 서버 썸네일, 드로잉 뷰 선택, 단위 선택/미터 정규화), 자산 라이브러리 진입 경로 D안 제안 | T2 |
| 2026-05-13 | D안 채택 확정. §4 DB 스키마 확장(is_public, authored_unit, preview_status, tags), §4.4 단위 헬퍼, §5 썸네일 재생성·페이지 라우트·렌더러 추가, §11 Phase 1/2 작업 분해 재정렬 | T2 |
