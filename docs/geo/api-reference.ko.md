# GIS API 레퍼런스

이 페이지의 모든 엔드포인트는 로그인(세션 쿠키 또는 [API 키](../Security.ko.md#api-keys))이 필요합니다. 데이터를 바꾸는 엔드포인트는 리소스에 따라 `edit_settings`, `edit_controllers`, `edit_plots` 중 하나의 권한이 추가로 필요하고, 특정 지도·시설에 묶인 엔드포인트는 호출자의 접근 그룹이 그 지도·시설을 포함하는지도 함께 검사합니다(`scope.can_operate`). 필요 권한이 `edit_settings`가 아닌 경우 각 절에 따로 표시했습니다.

> **알려진 중복:** `POST /api/geo/designs`, `GET`/`DELETE /api/geo/designs/<uuid>`, `GET`/`POST /api/geo/overlays` 는 코드에 각각 두 번(flask-restx 리소스 한 벌, 일반 Flask 라우트 한 벌) 정의돼 있습니다. Flask의 라우트 등록 순서 때문에 이 다섯 경로는 flask-restx 쪽만 실제로 동작하고, 일반 라우트 쪽 사본은 호출되지 않습니다. 아래 문서는 실제로 동작하는 flask-restx 쪽 동작을 기준으로 적었습니다. 이 중복은 내부 정리 대상이지 문서화된 계약의 일부가 아니며, 예고 없이 정리될 수 있습니다.

---

## 지도 디자인

"디자인"은 `GeoMap` 행 하나 — 자체 중심좌표/줌/레이어 상태를 갖고, 그 위에 그려진 모든 도형(부지, 구역, 시설, 장치)을 담는 이름 붙은 지도입니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/init_design` | 현재 사용자가 가장 최근에 쓴 지도를 불러옵니다(하나도 없으면 자동 생성). 전체 상태를 반환합니다. |
| GET | `/api/geo/designs` | 모든 지도를 `{unique_id, name, latitude, longitude, zoom}` 형태로 나열합니다(중심좌표/줌은 저장된 상태에서 파생하며, 없으면 `[37.5665, 126.9780]` / 줌 13이 기본값). |
| GET | `/api/geo/designs/list` | 위와 거의 동일한 지도 목록을 반환하는 두 번째 엔드포인트입니다(`routes_geo.py`에 나중에 추가됨 — 경로가 다르므로 위 항목과 충돌하지 않습니다). 응답 형태는 동일합니다. |
| GET | `/api/geo/designs/<map_uuid>` | 지도 하나의 전체 상태: `{ok, uuid, name, state}`. 없으면 404. |
| POST | `/api/geo/designs` | 지도를 생성(`map_uuid` 생략)하거나 이름·상태를 수정합니다. 본문: `{map_uuid?, name, state}` — `state`는 기존 상태에 **병합**되며 통째로 교체되지 않습니다. 응답: `{ok, uuid, name}`. |
| DELETE | `/api/geo/designs/<map_uuid>` | 지도와 그 위의 모든 것(시설 설정값 → 시설 → 도형 → 지도 행 순)을 삭제합니다. 이 지도 밖에서 아직 참조하는 대상이 있으면 `409 {blocked: true}`를 반환합니다. |
| POST | `/api/geo/maps/<map_uuid>/restore-original` | 마이그레이션 이전 스냅샷(`original_data`)을 갖고 있는 지도 위 도형을 전부 그 스냅샷 상태로 되돌립니다. 응답: `{ok, map_uuid, restored, skipped}`. 마이그레이션 추적 컬럼이 아직 없으면(`alembic upgrade head` 필요) 400. |

---

## 오버레이 & 도형 (GeoJSON)

"오버레이"는 지도 위에 그려진 GeoJSON 피처 — 부지, 구역, 시설 외곽선, 장치 마커, 설비를 말합니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/overlays/list` | 모든 지도를 통틀어 `GeoShape` 행 전체를, GeoJSON으로 감싸지 않고 평평하게 반환합니다. |
| GET | `/api/geo/overlays?map_uuid=<uuid>&type=&parent_id=&device_id=` | 한 지도의 피처를 GeoJSON `FeatureCollection`으로 반환합니다. `type`은 예전 명칭도 함께 매칭합니다(`equipment` ⇒ `equipment_collection`, `aot_device` ⇒ `device`). 각 피처에는 서버가 `db_id`, 해석된 `device_id`/`device_type`, `parent_id`, (`type=facility`인 경우) 3D 메타데이터를 채워 넣습니다. |
| POST | `/api/geo/overlays` | 한 `map_uuid` + `type`에 대한 일괄 저장/교체입니다. 이 페이지에서 가장 까다로운 엔드포인트라 아래 **상세**에 따로 설명했습니다. |
| POST | `/api/geo/overlays/delta` | 전체 피처 대신 바뀐 것만 보냅니다 — 큰 지도에 유리합니다. 본문: `{geo_id, added: [...], modified: [...], deleted: [uuid, ...]}`. 이 경로도 `edit_settings`와 지도 스코프를 요구합니다. |
| GET | `/api/geo/sites` | `site` 타입 도형 전체를 GeoJSON으로. `?map_uuid=` 선택적. |
| GET | `/api/geo/zones` | `zone` 타입 도형 전체를 GeoJSON으로. `?map_uuid=` 선택적. |
| GET | `/api/geo/shapes/<category>` | 임의의 도형 카테고리(`site`, `zone`, `facility`, `feature` 등)를 GeoJSON으로. |
| POST | `/api/geo/generate-pipes` | 저장하지 않고 장치 사이 배관 경로만 계산합니다. 본문: `{parent_feature, ref_line, config, map_uuid}`. |

### 상세: `POST /api/geo/overlays`

- 들어온 피처를 `db_id` → `node_id` 순으로 기존 행과 매칭합니다. 나머지는 전부 여기서 파생됩니다.
- **본문에 없다고 삭제되지 않습니다.** 명시적인 `deletes: [node_id_또는_db_id, ...]` 목록, 또는 `features: []` + `allow_empty: true` 조합만 행을 지웁니다. (예전에 "본문에 없음"을 "삭제"로 처리하다가 도형이 통째로 날아간 사고가 있었습니다.)
- `aot_device` 마커는 이 엔드포인트로 절대 일괄 삭제할 수 없습니다 — 장치 배치는 오직 `POST /api/geo/device/location`을 통해서만 이뤄집니다.
- `equipment` 피처는 하나로 묶인 `equipment_collection` 행 하나로 저장됩니다(세트 전체를 통째로 교체). 그 외에는 피처 단위로 저장됩니다.
- `aot_type`, `device_id`, `channel_id`는 저장되는 JSON에서 제거됩니다 — 조회 시 파생되는 값이라 그대로 왕복 저장되리라 기대하면 안 됩니다.
- 응답: `{ok, count, id_map: {node_id: db_id}, stats: {deleted, updated, inserted}}` (설비 일괄 저장 경로는 `stats.mode: 'bulk_bundle'` 형태).

---

## 검색

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/geo/search` | 검색 제공자로 설정된 GIS 입력 모듈을 통한 지오코딩/주소 검색. 본문: `{query, type: 'address' (기본값), layer_id?}`. `layer_id`로 특정 `GeoLayer`를 고를 수 있고, 없으면 지도의 `search_provider` 설정을 쓰다가 최종적으로 `gis_osm`으로 폴백합니다. 응답: `{ok, results}` (형태는 제공자마다 다름). |

---

## 장치 바인딩

"바인딩"은 장치(센서 또는 액추에이터)를 공간 슬롯 — 구역 폴리곤, 시설 피팅, 센서 역할 등 — 에 연결하는 것입니다. 바인딩은 이력을 갖는 독립 객체입니다: 하나를 끊어도 행은 지워지지 않고 남습니다(감사 목적).

공통 필드(`spatial_kind`, `spatial_id`, `role`, `device_id`, `device_kind`, `channel_id`, `measurement_id`)는 아래 **상세**를 참고하세요.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/binding?spatial_kind=&spatial_id=&role=` | 한 슬롯의 현재 바인딩과 과거 이력. 응답: `{ok, bindings, history}` (`history`는 끝난 것만). |
| POST | `/api/geo/binding` | 비어 있는 슬롯에 장치를 묶습니다. 이미 묶여 있으면 `409 {conflict: true}`, 알 수 없는 장치/도형이면 `400`. |
| PUT | `/api/geo/binding` | 슬롯의 장치를 교체합니다 — 기존 바인딩을 끝내고(이력에 남김) 새 바인딩을 한 번에 만듭니다. |
| GET | `/api/geo/binding/unbound?kinds=&facility_uuid=&map_uuid=` | 아직 아무 장치도 묶이지 않은 슬롯 목록(빈 구역 폴리곤, 장치를 잃어버린 시설 피팅 등) — "무엇을 배선해야 하는지" 화면용입니다. `kinds`는 항상 구체적인 공간 종류로 좁혀서 써야 합니다. |
| DELETE | `/api/geo/binding/<binding_uid>` | 바인딩을 끊습니다(`valid_to` 설정, 행은 유지). 본문/쿼리: `reason`(기본값 `unbound`). 존재하지 않는 id면 `404`. |

### 상세: 바인딩 필드

- `spatial_kind`: `shape` \| `fitting` \| `actuator` \| `sensor_role` \| `weather`.
- `spatial_id`: 슬롯 식별자. `spatial_kind=shape`인 경우 저장된 `GeoShape.unique_id` 또는 아직 저장되지 않은 클라이언트 측 `node_id` 둘 다 받으며, 서버가 알아서 해석합니다.
- `role`: 슬롯의 용도(`marker`, `area`, `actuator`, `sensor` 등). 도형 슬롯의 경우 role은 그 도형 자체의 `type`에서 서버가 파생합니다 — 클라이언트가 보낸 값은 도형에 한해 신뢰하지 않습니다.
- `device_id`: `<device_uuid>::<channel>` 접미사를 받을 수 있으며, 분리되어 `channel_id`가 됩니다.
- `device_kind`는 클라이언트가 보내도 서버에서 항상 다시 검증/해석됩니다.

---

## 장치 위치·목록·상세 { #device-location-lists-detail }

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/geo/device/location` | 장치의 지도 위 위치를 설정/이동합니다. 본문: `{unique_id, type, lat, lng, map_uuid?, channel_id?}` — `type`은 `input\|output\|pid\|trigger\|conditional\|device\|function\|custom\|generic_function` 중 하나. `map_uuid`가 있으면 해당 지도에 마커도 배치/갱신하고 소속 구역을 파생시킵니다. 성공 시 데몬에 해당 장치의 설정 재적용을 최선노력으로 요청합니다(위치가 바뀌며 타임존이 달라졌을 때 즉시 반영되도록). 응답: `{ok, message, overlay_id}`. |
| GET | `/api/geo/devices?map_uuid=&device_ids=&include_all=` | 지도에 배치 가능한 장치 목록. 응답: `{ok, devices, all_measurements_map}`. 조건부(304) 응답을 지원합니다. |
| GET | `/api/geo/inputs` | 센서 피팅 바인딩 화면용 채널 단위 평면 목록(`DeviceMeasurements`). |
| GET | `/api/geo/outputs` | 액추에이터 피팅 바인딩 화면용 `Output` 평면 목록. |
| GET | `/api/geo/device/<device_uuid>/detail` | 장치 모달 전체 데이터: 식별 정보, 소속 영역, 제어 방식(on/off, value, PWM, 3방향), 채널, 복합장치의 하위 장치, 런타임 정보(경과시간/마지막 작동시간/대기 중인 예약). |
| POST | `/api/geo/link_status` | 지도 배지용 배터리/RSSI 일괄 조회. 본문: `{ids: [...]}` (최대 100개). |
| POST | `/api/geo/device/split-apply` | 구역을 여러 조각(스트립/격자)으로 나누고 조각마다 장치 마커 도형을 만들어, 그 조각 안에 있는 장치 마커에 자동으로 배정합니다. `edit_plots` 필요. 구획 분할기와 분할 파라미터 및 *미리보기* 엔드포인트(아래 `GET /api/geo/plot/split-preview`)를 공유합니다 — 조각이 장치가 되든 구획이 되든 기하 계산 자체는 같기 때문입니다. 응답: `{ok, created, info, assigned, unassigned, message?}`. |

---

## 구역 { #zones }

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/zone/<zone_uuid>/contents` | 구역의 "[환경·제어]" 모달용 장치 인벤토리(구역 안 센서/출력/함수). 서버 캐시 30초. |
| GET | `/api/geo/zone/<zone_uuid>/allocation?on=YYYY-MM-DD` | 구역 면적이 산하 구획들에게 어떻게 나뉘는지(구획별 면적/비율 + 미배정 잔여). 구획이 겹치면 합이 100%를 넘을 수 있으며 `overlaps`로 표시됩니다. |
| GET | `/api/geo/zone/<zone_uuid>/output_history?output_id=<uuid>&hours=` | 아래 `GET /api/geo/output/<uuid>/history`의 구역 스코프 예전 별칭입니다. |
| POST | `/api/geo/zone/<zone_uuid>/photo` | 구역 대표 이미지 업로드 (multipart `photo`). |
| POST | `/api/geo/zone/<zone_uuid>/rep_key` | 구역의 "대표" 측정값을 설정/해제합니다. |
| POST | `/api/geo/zone/<zone_uuid>/hidden_rows` | 본문: `{card, keys}` — 이 구역에서 숨길 상태 카드 행. |
| POST | `/api/geo/zone/<zone_uuid>/output_order` | 본문: `{order}` — 구역 장치 목록의 표시 순서를 저장합니다. |
| POST | `/api/geo/shape/<shape_uuid>/description` | 부지 또는 구역의 자유 서술(2000자 이하). |

---

## 부지

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/site/<site_uuid>/contents` | 부지 안의 장치 인벤토리(시설 피팅 액추에이터는 제외 — 그건 부지가 아니라 소속 시설에 속합니다). |
| GET | `/api/geo/site/<site_uuid>/summary?force=` | 부지의 상태/오늘 할 일/노트 요약. 30초 캐시(`force=1`이면 무시). |
| GET | `/api/geo/site/<site_uuid>/weather` | 현재 지정된 기상 관측 장치. 응답: `{selected, source, candidates}`. |
| POST | `/api/geo/site/<site_uuid>/weather` | 본문: `{device_ids: [...]}` (빈 배열이어도 키는 필요) — 부지의 기상 소스를 설정합니다. |

---

## 시설

"시설"은 외피(치수·자재)를 갖고 센서·액추에이터가 묶인 구조물(온실, 축사 등)입니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/facility/list?geo_id=<map_uuid>` | 모든 시설, 지도 하나로 범위를 좁힐 수 있습니다. 각 항목에 `rep_key`가 포함됩니다. |
| GET | `/api/geo/facility/<facility_uuid>` | 시설 전체 데이터: 외피, 바인딩, 3D/렌더링 설정. |
| POST | `/api/geo/facility` | 생성 또는 수정(본체·외피 스펙·베이를 하나의 트랜잭션으로 원자적 처리). 본문: `unique_id?`(생성 시 생략), `name`, `shape_uuid`, `preset`, `structure`, `bay_count`, `envelope: {material, bay_width_m, length_m, eave_height_m, ridge_height_m}`. |
| POST | `/api/geo/facility/<facility_uuid>/clone` | 시설을 복제하며 장치 바인딩은 초기화합니다(복제본은 원본의 배선을 물려받지 않습니다). |
| DELETE | `/api/geo/facility/<facility_uuid>` | 본문/쿼리: `confirm_name`이 현재 시설명과 일치해야 합니다. |
| POST | `/api/geo/facility/compute` | 저장 없이 주어진 외피에 대한 공학 계산 미리보기(면적/체적/난방·냉방 부하/환기량). 본문: `{envelope: {...}, bay_count}`. 계산 모듈이 없으면 `501`. |
| GET | `/api/geo/facility/<facility_uuid>/integration` | 통합 센서/액추에이터 바인딩 뷰 — 환경 코디네이터 자신이 읽는 것과 같은 데이터입니다. |
| GET | `/api/geo/facility/<facility_uuid>/wind?wind_speed=&wind_dir=` | 자연환기 풍압 시뮬레이션. |
| POST | `/api/geo/facility/<facility_uuid>/apply` | 시설에 묶인 액추에이터에 명령을 보냅니다. 본문: `{horizon, commands: [{kind, action, pct?}, ...]}`. VEE(가상 실행 엔진) 기능 플래그가 켜져 있으면 먼저 어드바이저리 사전 시뮬레이션을 돌리며, 실제 명령 전달은 어느 경우든 데몬을 통합니다. |

시설의 실시간 상태 조회/제어(실시간 액추에이터 상태, 안전 범위 설정값, 수동 제어, 비상정지)는 **다른 URL 접두사를 쓰는 별도 API 계열**입니다 — 아래 [시설 실시간 제어](#facility-runtime-control-apiaotfacility-apiaotcoordinator)를 참고하세요.

### 시설 3D 모델 에셋

시설의 기본 파라메트릭 형상 대신 붙일 수 있는 재사용 3D 모델(기본 도형 또는 가져온 `.glb`/`.gltf` 파일)입니다. 로그인만 필요하며(추가 권한 검사 없음), 목록/생성은 `owner_user_id = current_user.id`로 범위가 좁혀집니다(조회/수정/삭제/부착은 id로 직접 접근 시 소유자 검사가 없습니다).

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/model_assets?kind=&tag=` | 현재 사용자의 모델 에셋 목록. |
| POST | `/api/geo/model_assets` | 생성. JSON 본문 또는 멀티파트(`kind=imported_gltf`면 `file` 필드 필수). 필드: `name`, `kind`(기본값 `primitive`), `spec_json`, `authored_unit`(기본값 `m`), `tags`, `notes`. 업로드 파일: 25MB 이하, 허용된 확장자만, `.glb`는 매직바이트(`glTF` 헤더) 검증. 생성 후 미리보기 이미지 렌더링을 트리거합니다. |
| GET | `/api/geo/model_assets/<asset_uuid>` | 에셋 하나 조회. 없으면 404. |
| PUT | `/api/geo/model_assets/<asset_uuid>` | `name`/`spec_json`/`authored_unit`/`tags`/`notes`/`sort_order` 수정(본문에 있는 키만 반영). 미리보기를 다시 렌더링합니다. |
| DELETE | `/api/geo/model_assets/<asset_uuid>` | 에셋 행과 디스크 파일을 삭제합니다. 아직 참조하는 시설이 있으면 `409`(`referencing_facilities` 포함). |
| POST | `/api/geo/model_assets/<asset_uuid>/regenerate_preview` | 썸네일을 강제로 다시 렌더링합니다. |
| POST | `/api/geo/facility/<facility_uuid>/attach_model` | 시설에 모델 에셋을 붙입니다(`render_mode='asset'`). 본문: `{asset_uuid, transform?}`(`transform` 기본값: 위치·회전 항등, 스케일 1). |
| DELETE | `/api/geo/facility/<facility_uuid>/attach_model` | 부착을 해제합니다(`render_mode`가 `parametric`으로 돌아감). |

### 시설 커미셔닝

설치 후 검증: 시설 액추에이터에 대해 자동 점검을 돌린 뒤, 액추에이터별로 사람이 판정을 내립니다. 결과 조회를 제외하면 `edit_settings`가 필요합니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/geo/facility/<facility_uuid>/commissioning/start` | 본문: `{actuator_ids?}`(생략 시 시설의 모든 액추에이터). 응답: `{ok, check_id, actuator_count}`. 점검할 대상이 없으면 `400`. |
| GET | `/api/geo/facility/<facility_uuid>/commissioning/<check_id>` | 점검 상태/결과를 폴링합니다. 로그인만 필요, 추가 권한 없음. 점검이 다른 시설 소속이면 `403`, 없으면 `404`. |
| POST | `/api/geo/facility/<facility_uuid>/commissioning/<check_id>/verdict` | 본문: `{actuator_id, verdict: 'ok'\|'sensor'\|'device'\|'external'\|'skip', note?}`. 판정에 따라 시설에 후속 조치가 기록될 수 있습니다(센서 신뢰불가 표시, 제어 게인 상한 조정, 캘리브레이션 앵커 추가, 경보 등록) — 응답의 `actions` 목록으로 반환됩니다. |

---

## 시설 실시간 제어 (`/api/aot/facility`, `/api/aot/coordinator`) { #facility-runtime-control-apiaotfacility-apiaotcoordinator }

여기는 **다른 URL 접두사**(`/api/geo/`가 아닌 `/api/aot/`)를 씁니다 — 시설의 환경 코디네이터가 돌아가기 시작한 뒤의 실시간 쪽: 상태, 안전 범위 설정값, 수동 개입, 비상정지, 이력입니다. 위의 시설과 개념적으로 같은 객체(같은 `facility_uuid`)이며 단지 라우트 계열이 다를 뿐입니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/aot/facility/<facility_uuid>/status?function_uuid=` | 폴링용 경량 상태 배지(약 5초 주기): `{level: 'idle'\|'warn'\|'active'\|'emergency', reasons, active_count, total_count, function_active, function_stale}`. |
| GET | `/api/aot/facility/<facility_uuid>/setpoints` | 저장된 **안전 범위** 한계값과 `effective`(제어 루프가 실제로 따르는 실시간 목표 — 이건 여기가 아니라 구획의 프로그램/단계에서 나옵니다). |
| POST | `/api/aot/facility/<facility_uuid>/setpoints` | `edit_settings` 필요. 본문: `guide_t_min_c`/`guide_t_max_c`, `guide_rh_min_pct`/`guide_rh_max_pct`, `temp_min_c`/`temp_max_c`, `humid_min_pct`/`humid_max_pct` 중 아무거나(전부 범위 검증). `target_vpd_kpa`/`target_co2_ppm`을 여기로 보내면 거부됩니다 — 목표는 재배 프로그램을 통해서만 설정합니다. 바뀐 값을 연결된 모든 환경 코디네이터 함수에 반영하고 즉시 재적용을 트리거합니다. |
| POST | `/api/aot/facility/<facility_uuid>/control` | 코디네이터를 건너뛴 단일 액추에이터 수동 제어이며, 안전 게이트 인터락이 함께 걸립니다(예: 풍속 안전 게이트가 강제로 닫아둔 창을 열라는 요청은 거부). `edit_settings` + 시설 스코프 필요. 본문: `{slot_key, action: 'on'\|'off'\|'set', percent?, reason?}`. 게이트가 막으면 `400`. |
| POST | `/api/aot/facility/<facility_uuid>/estop` | 비상정지 — 모든 액추에이터를 안전한 사전 설정 상태로 강제합니다(난방/환기/팬/CO2/관수/조명 끔, 보온커튼 전개, 차광커튼 개방). 본문: `{confirm: "STOP"}`(정확히 이 문자열이어야 함). `edit_settings` 필요. |
| GET | `/api/aot/facility/<facility_uuid>/runtime` | 무거운 실시간 스냅샷: 듀티/최근 작동 이력을 포함한 액추에이터 상태, 실내외 센서, 베이, 구획, 베이별 용량. 120초 프로세스 캐시, 조건부(304) 응답 지원. |
| GET | `/api/aot/facility/<facility_uuid>/env_summary` | 코디네이터가 마지막 주기에 데몬에 저장해 둔 요약(시계열 조회 없이 단일 행만 읽는 저렴한 호출). |
| GET | `/api/aot/facility/<facility_uuid>/env_week?bay=&days=` | 일별 환경 추이 시계열(기본 7일, 1~31). 10분 캐시. |
| GET | `/api/aot/facility/<facility_uuid>/actuator_history?slot_key=&hours=` | 액추에이터 하나의 작동 이력(퍼센트/듀티 시계열, 없으면 on/off 지속시간으로 대체). `hours` 기본 24, 1~168로 제한. |
| GET | `/api/aot/facility/<facility_uuid>/overview?fresh=` | 지도 팝업이 여러 요청을 한꺼번에 쏘지 않도록 status + env_summary + info + irrigation + 기상 위험 + 부지 + 영역 상태 + 대표값 + 숨김행 + 구획 GDD/DLI를 한 번에 묶어 반환합니다. 30초 캐시 + 단일실행 락(`fresh=1`이면 무시). |
| POST | `/api/aot/facility/<facility_uuid>/function_state` | 본문: `{action: 'activate'\|'deactivate'}` — 연결된 환경 코디네이터 함수를 켜고 끕니다. `edit_controllers` + 스코프 필요. |
| GET | `/api/aot/facility/<facility_uuid>/info` | 지도 팝업용 대표 사진/설명/치수. |
| POST | `/api/aot/facility/<facility_uuid>/info` | 본문: `{description}`(2000자 이하). `edit_settings` 필요. |
| POST | `/api/aot/facility/<facility_uuid>/photo` | 대표 사진 업로드(멀티파트, png/jpg/jpeg/gif/webp). `edit_settings` 필요. |
| GET | `/facility_photo/<filename>` | 업로드된 시설 사진을 서빙합니다(로그인 필요, 경로 탈출 방지). |
| POST | `/api/aot/facility/<facility_uuid>/rep_key` | 시설의 대표 측정값을 설정/해제합니다. 매핑된 도형이 없으면 `422`. `edit_settings` 필요. |
| POST | `/api/aot/facility/<facility_uuid>/hidden_rows` | 위 구역 버전과 같은 형태를, 시설에 대해. `edit_settings` 필요. |
| POST | `/api/aot/facility/<facility_uuid>/actuator_order` | 본문: `{order: [slot_key, ...]}`. `edit_settings` 필요. |
| GET | `/api/aot/facility/<facility_uuid>/bays` | 베이 스코프 선택용 `{ok, bays: [{id, name}]}`. |
| POST | `/api/aot/facility/<facility_uuid>/bay_capacity` | 본문: `{bay_id, unit, total}`(`total<=0`이면 해제). `edit_settings`가 아니라 **의도적으로** `edit_plots`(작기 운영자 권한)를 요구합니다. |
| GET | `/api/aot/facility/<facility_uuid>/calibration_status` | 연결된 코디네이터의 액추에이터별 제어 루프 캘리브레이션 상태와 커미셔닝 상태. |
| GET | `/api/aot/coordinator/<function_uuid>/overview` | 환경 코디네이터 설정 페이지 헤더: 어느 시설을 제어하는지, 그 시설의 활성 구획과 프로그램, (같은 시설에 비활성 중복 코디네이터가 있으면) `other_coordinator` 경고. |
| GET | `/api/aot/coordinator/<function_uuid>/actuators` | 이 코디네이터가 제어할 수 있는 액추에이터, 현재 비활성화된 것(`disabled_actuators` 옵션), 그리고 더 이상 실재 장치로 해석되지 않는 낡은 비활성화 항목. |

---

## 재배 프로그램

"프로그램"은 구획이 따라가는 재사용 가능한 생육단계 템플릿(단계, GDD/DLI 목표, 관수·시비 일정)입니다. 쓰기 작업은 `edit_plots`가 필요합니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/programs?subject=&kind=&tab_id=` | 구획이 쓸 수 있는 프로그램 목록. `subject`는 `crop`도 별칭으로 받습니다. 같은 subject라면 품종 전용 프로그램이 일반 기본 프로그램보다 앞에 정렬됩니다. |
| GET | `/api/geo/program/<program_uuid>` | 단계 목록까지 포함한 프로그램 전체. |
| POST | `/api/geo/program` | 생성. 본문: `name`, `subject`/`crop`, `kind`(기본값 `vegetation`), `stages`, `photosynthesis`, `target_defs`, `resource_defs`, `notes`, 또는 내장 템플릿에서 시작할 `template_key`. 항상 `source: 'user'`로 저장됩니다. |
| POST / PUT | `/api/geo/program/<program_uuid>` | 수정. 내장/외부 프로그램은 내용 수정을 거부합니다 — 먼저 복제하세요(아래). `tab_id`만 있는 요청은 내장 프로그램에도 허용됩니다(탭 이동은 내용 수정이 아니므로). AI 에이전트가 수정하면 `source`가 `ai`로 바뀌고 기존 검토 이력이 지워집니다. |
| DELETE | `/api/geo/program/<program_uuid>` | 아직 참조하는 구획이 있으면 거부됩니다. |
| POST | `/api/geo/program/<program_uuid>/clone` | 내장/외부 프로그램을 수정하는 유일한 방법 — 편집 가능한 사본으로 복제합니다. 본문에서 `name`, `subject`/`crop`, `kind`, `variety`, `stages`, `target_defs`, `photosynthesis`, `targets_methods`, `notes`, `tab_id`를 덮어쓸 수 있습니다. 참고용으로 `derived_from`을 기록합니다(살아있는 연결은 아님). |
| GET | `/api/geo/program-templates` | 내장 시드 템플릿 카탈로그(DB에 저장되지 않음). |
| GET | `/api/geo/target-methods` | 프로그램의 단계별 고정값 대신 목표로 쓸 수 있는 `Method`(시간축 곡선) 컨트롤러 목록. |
| GET | `/api/geo/target-measurements` | 목표가 바인딩될 수 있는 측정값 어휘와, 각 종류의 기본 목표 정의. |
| GET | `/api/geo/coordinator/<function_uuid>/plot-targets?on=YYYY-MM-DD` | 환경 코디네이터 함수가 지금 따르는 구획과 그 단계 목표를 읽기 전용으로 보여줍니다 — 실제 제어가 쓰는 것과 같은 코드 경로로 계산하므로 여기서 표시되는 값과 실제 동작이 어긋날 수 없습니다. |
| POST | `/api/geo/coordinator/<function_uuid>/reference-plot` | 본문: `{plot_uuid}`(빈 문자열이면 해제). 간작 등으로 겹치는 구획이 여럿일 때 코디네이터가 기준으로 삼을 구획을 고정합니다. |

---

## 재배 구획

"구획"은 땅 또는 시설 베이 한 곳에서의 한 작기 — 그 자체의 단계 타임라인·목표·일정을 가지며, 따르고 있는 공유 프로그램과는 독립적입니다. 쓰기 작업은 `edit_plots`가 필요합니다.

### 목록·상세

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/plots?map_uuid=&on=&include_ended=&include_planned=&facility_uuid=` | 구획 목록. 기본은 한 지도의 활성 구획만; `include_ended`/`include_planned`로 범위를 넓힙니다. `map_uuid`를 생략하면 지도 전체를 아우르는 "운영" 뷰가 됩니다. |
| GET | `/api/geo/plot/<plot_uuid>` | 구획 하나의 상세(대기 중인 단계 전환이 있으면 먼저 자동 승인). `can_edit`, `can_design`, 그 구획 자체의 다가오는 장치 일정을 포함합니다. |
| GET | `/api/geo/plot/<plot_uuid>/contents` | "[환경·제어]" 모달 인벤토리 — 장치를 구획 안(plot), 구획까지 닿는 관수(irrigation), 장치 종류별 최근접 대체(nearest)로 분류합니다. 자체 폴리곤이 없는 시설 기반 구획은 베이 스코프 변형을 씁니다. 30초 캐시. |
| GET | `/api/geo/plot/<plot_uuid>/resource_usage?days=` | "[현황]" 카드용 관수 작동시간/용량. `days` 1~30. |
| GET | `/api/geo/plot/<plot_uuid>/env_series` / `/env_week?days=&end=&stage=&unit=` | 구획 자신의 타임존 기준 환경 추이 시계열. `stage=<key>`를 주면 `days`/`end` 대신 그 단계의 기간을 씁니다. |
| GET | `/api/geo/plot/<plot_uuid>/sensors` | 이 구획이 현재 참조하는 장치들(저장값이 아니라 파생값). |
| GET | `/api/geo/zone/<zone_uuid>/allocation?on=` | [구역](#zones) 절 참고 — 구역 관점에서 본 산하 구획들의 면적 배분. |
| POST | `/api/geo/plots/history` | "여기 예전에 뭘 심었었나" — 주어진 도형과 기하가 겹치는 과거 구획(작물 순환/연작피해 확인용). 본문: `plot_uuid`, `zone_uuid`, 원시 `geometry` 중 하나, 그리고 유추할 수 없으면 `map_uuid`. |

### 생애주기 & 단계

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/geo/plot` | 생성(`unique_id` 없음) 또는 수정(있으면 — 부분 저장, 준 필드만 바뀜). `map_uuid`/`geo_id`와 `feature`(GeoJSON) 또는 `facility_uuid`(+`bay_id`) 중 하나가 필요합니다. |
| DELETE | `/api/geo/plot/<plot_uuid>` | **완전** 삭제 — 잘못 입력한 것을 지울 때만. 정상적인 작기 종료는 아래 `/end`를 쓰세요. |
| POST | `/api/geo/plot/<plot_uuid>/end` | 작기를 부드럽게 종료합니다(종료일만 설정, 삭제하지 않음). 본문: `{ended_on, reason: 기본값 'harvested'}`. |
| POST | `/api/geo/plot/<plot_uuid>/succeed` | 현재 작기를 끝내면서 같은 자리에 바로 다시 심는 것을 한 번에 처리합니다. 본문: `{ended_on, reason, subject, started_on, program_uuid?, variety?}` — `program_uuid`를 생략하면 기존 프로그램을 물려받고, 명시적으로 `null`을 주면 비웁니다(휴경). |
| POST | `/api/geo/plot/<plot_uuid>/copy` | 과거 작기의 기하를 재사용해 새 구획을 만듭니다(같은 자리에 재정식). 본문: `{started_on, subject}`. |
| POST | `/api/geo/plot/<plot_uuid>/stage` | 단계 전환을 확정합니다 — 이후 모든 단계 계산의 기준일이 되는 값입니다. 본문: `{stage_key, stage_index, started_on, source, note}`. |
| DELETE | `/api/geo/plot/<plot_uuid>/stage` | 마지막으로 확정한 단계 전환을 되돌립니다(행은 남고 취소 표시만 됨). |
| POST | `/api/geo/plot/<plot_uuid>/stage-guidance` | 프로그램의 안내와는 별개로, 이 구획만의 단계별 자유 안내문을 설정합니다. 본문: `{stage_key, guidance}`. |
| POST | `/api/geo/plot/<plot_uuid>/stage-name` | 이 구획에서만 단계 이름을 바꿉니다. 본문: `{stage_key, name}`. stage-guidance와 달리 이미 지난 단계도 이름을 바꿀 수 있습니다. |
| POST | `/api/geo/plot/<plot_uuid>/stage-target` | 이 구획에 한해 단계 목표값을 덮어씁니다. 본문: `{stage_key, target_key, value}` — `value`를 비우면 프로그램 값으로 되돌아갑니다. **화면 표시용이 아닙니다** — 제어는 프로그램의 참조값보다 구획 덮어쓰기 값을 우선해서 읽습니다. |
| POST | `/api/geo/plot/<plot_uuid>/stages` | 공유 프로그램은 건드리지 않고 이 구획에만 커스텀 단계를 추가합니다. 본문: `{name, days, after, guidance}`. |
| DELETE | `/api/geo/plot/<plot_uuid>/stages/<stage_key>` | 구획 전용 단계를 제거합니다. 이미 지난 단계면 거부됩니다. |
| POST | `/api/geo/plot/<plot_uuid>/save-as-program` | 이 구획의 현재 단계 일정을 재사용 가능한 프로그램으로 등록합니다 — 살아있는 연결이 아니라 사본입니다(이 구획은 원래 쓰던 것을 계속 따라갑니다). 본문: `{name, adopt_targets}` — `adopt_targets`는 모호하지 않은 범위 내에서 이 구획의 실측 중앙값을 새 프로그램의 단계별 목표로 채택합니다. |
| POST | `/api/geo/plot/<plot_uuid>/resources` | 구획의 현재 단계에 등록된 자원 함수(예: 관수)를 수동으로 작동시킵니다. 물을 트는 동작이라 단계 전환이나 자동 승인으로는 **절대** 자동 실행되지 않습니다. |

### 일정

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/geo/plot/<plot_uuid>/schedule` | 단계 경계를 한꺼번에 조정합니다. 본문: `days`(`{stage_key: 일수}`, 기간 기준) 또는 `plan`(`{stage_key: date|null}`, 절대 날짜 기준) 중 정확히 하나. |
| POST | `/api/geo/plot/<plot_uuid>/schedule/shift` | 단계 경계 하나를 상대적으로 옮깁니다. 본문: `{stage_key, days: ±N}` — 저장 시점에 절대 날짜로 변환되므로, 나중에 다시 옮겨도 예전 "+7일"이 뜻했던 날짜 자체는 바뀌지 않습니다. |

### 구역을 구획으로 분할

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/plot/split-preview?zone_id=&parts=\|strip_width_cm=\|widths_cm=&edge_margin_m=&min_length_cm=&orientation=&angle_deg=` | 도형을 스트립/격자로 나누는 안을 **아무것도 저장하지 않고** 계산합니다 — 분할은 결정적이므로(같은 도형+파라미터 ⇒같은 결과) 미리보기를 따로 저장해 둘 필요가 없습니다. |
| POST | `/api/geo/plot/split-apply` | 본문: 같은 분할 파라미터에 더해 `subject`(필수), `kind`(기본값 `vegetation`), `variety`, `started_on`, `expected_end_on`, `color`, `name`. **클라이언트가 보낸 미리보기 폴리곤을 절대 신뢰하지 않고 같은 파라미터로 서버에서 분할을 다시 계산**한 뒤, 각 조각마다 구획을 하나씩 만듭니다. 조각 하나라도 실패하면 절대 전체 성공으로 보고하지 않습니다: `{ok, created, errors: [{index, message}], message}`. |

(장치 마커 버전의 분할기는 `POST /api/geo/device/split-apply`이며 [장치 위치·목록·상세](#device-location-lists-detail) 절에 있습니다 — 조각이 무엇이 되든 기하 계산은 같으므로 이 `split-preview`를 그대로 재사용합니다.)

---

## 수동 일정

장치를 직접 작동시키지 않는 가벼운 일정 항목입니다(특정 날짜에 작업자가 할 일을 적어두는 메모) — 장치를 자동으로 작동시키는 스케줄러와는 별개입니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/schedule/<target_id>` | 도형/구획/시설의 다가오는 일정(하위 항목 포함). |
| POST | `/api/geo/schedule` | 본문: `{target_id, date, time, content, worker}`. |

---

## 출력 제어 (지도 팝업)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/geo/output/<output_uuid>/state` | 데몬을 통해 출력을 켜고 끕니다. 본문: `{state, channel, duration}`. `edit_controllers` + 장치 스코프 필요. |
| POST | `/api/geo/output_states` | 구역 팝업용 배치 raw on/off 상태 조회. 본문: `{ids: [...]}`. 읽기 전용 — 로그인만 필요, 추가 권한 없음. |
| POST | `/api/geo/output_runtimes` | 더 무거운 배치 조회(경과시간, 마지막 작동시간, 다음 예약) — 폴링용이 아니라 모달을 열 때만 씁니다. 본문: `{items: [{id, channel}, ...]}` (최대 60개). |
| GET | `/api/geo/output/<output_uuid>/history?hours=` | 듀티사이클/on-off 이력 시계열. `hours` 1~168, 기본 24. |
| POST | `/api/geo/function/<kind>/<func_uuid>/activate` | `kind`는 `custom`\|`conditional`\|`pid`\|`trigger`\|`function`. 본문: `{active: bool}`. `edit_controllers` 필요. |

---

## 필지 가져오기

실제 필지/공원 경계를 지도 도형으로 가져옵니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/geo/parcel/from_address` | 본문: `{address}`. VWorld를 통해 필지(지적) 폴리곤을 조회합니다(API 키는 등록된 `gis_vworld` 레이어에서 해석). |
| POST | `/api/geo/parcel/from_csv` | 멀티파트 `file` — 첫 컬럼이 주소인 CSV를 일괄 가져옵니다. |
| POST | `/api/geo/parcel/save_as_site` | 본문: `{feature, name, map_uuid}`(`map_uuid` 필수). 가져온 필지를 `site` 도형으로 저장합니다. 같은 필지를 기하 키 기준으로 중복 가져오기하면 `409`로 거부하고, 라벨 도형도 함께 자동 생성합니다. |
| GET | `/api/geo/import/gg_parks/preview?sigun_nm=&limit=` | 경기도 공공공원 경계 가져오기 미리보기(실제 저장 없음). |
| POST | `/api/geo/import/gg_parks` | 본문: `{map_uuid, sigun_nm, limit, delay_sec}`. 미리 본 공원을 `site` 도형으로 저장합니다. |

---

## 항공/드론 이미지 오버레이

지도 위에 씌우는 지리참조 래스터 이미지(드론 사진, 항공 이미지)입니다. `edit_controllers` 필요.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/geo/overlay_image/upload` | 멀티파트 `file` + `layer_id`. 그 레이어에 이전 배치가 없으면 EXIF/XMP 메타데이터로 자동 지리참조하고, 있으면 기존 네 귀퉁이에 텍스처만 교체합니다. 이미지 크기/용량에 따라 타일 피라미드 방식과 단일 이미지 방식 중 하나로 결정됩니다. |
| POST | `/api/geo/overlay_image/save` | 본문: `{layer_id, coordinates: [[lng,lat], ...] (네 귀퉁이), opacity}`. 귀퉁이 좌표가 바뀌면 타일링을 다시 트리거합니다. |
| GET | `/api/geo/overlay_image/tile_status/<layer_id>` | 타일링 진행 상태 폴링: `{tile_status, render_mode, tile_url, minzoom, maxzoom, tile_count, tile_error}`. |

---

## 프록시 서비스

브라우저 클라이언트가 상위 서비스의 API 키를 절대 보지 못하게 하고 CORS 제약도 피하도록 서버가 이 외부 서비스들을 중계합니다. 전부 `GET`이며, 대부분 상위 응답을 잠시 캐시합니다(아는 범위에서 표기).

| 엔드포인트 | 대상 |
|---|---|
| `/api/geo/layer_secrets?ids=` | 호출자 본인이 등록한 레이어 최대 12개의 평문 API 키/URL(페이지에 렌더되는 목록은 마스킹되며, 여기서 드러나려면 레이어가 실제로 활성화돼 있어야 함). |
| `/api/geo/proxy/rainviewer/meta` | RainViewer 레이더 메타데이터(5분 캐시). |
| `/api/geo/proxy/rainviewer/timestamps` | RainViewer 사용 가능한 프레임 타임스탬프. |
| `/api/geo/proxy/isric?lon=&lat=&property=&depth=&value=` | ISRIC SoilGrids 토양 데이터(5분 캐시). |
| `/api/geo/proxy/openweather?lat=&lon=&units=&input_id=` | OpenWeather 오버레이(키는 `input_id`에서 서버가 해석하며, 클라이언트가 보낸 키는 무시됨). |
| `/api/geo/proxy/kma?lat=&lon=&input_id=` | 기상청 API 허브 지상 관측 데이터. |
| `/api/geo/proxy/openmeteo` | Open-Meteo 예보(상위 서비스가 다운됐을 때 쿼리별로 60초 재시도 대기). |
| `/api/geo/proxy/wms/<layer_id>?BBOX=&WIDTH=&HEIGHT=` | WMS `GetMap` 타일 프록시. 2단 캐시(디스크 + 브라우저 ETag), 상위 실패 시 오류 대신 투명 1×1 PNG 반환. |
| `/api/geo/tile/<layer_id>/<z>/<x>/<y>` | 키가 필요한 범용 XYZ 타일 프록시(예: OpenWeather 타일 오버레이). |
| `/api/geo/proxy/sentinelhub/<layer_id>?z=&x=&y=` | Sentinel Hub Process API 타일(OAuth2 자격증명은 서버 밖으로 나가지 않음). |
| `/api/geo/proxy/sentinelhub/<layer_id>/value?lat=&lon=` | 범례 표시용, 한 지점의 지수값(NDVI 등). 15분 캐시. |
| `/api/geo/proxy/agromonitoring/<layer_id>?lat=&lon=` | 등록된 폴리곤의 토양수분/온도/NDVI. 30분 캐시. |
| `/api/geo/tile_proxy?url=` | 범용 타일 프록시. `gibs.earthdata.nasa.gov`, `map.pstatic.net`(네이버), `daumcdn.net`(카카오)만 허용목록에 있습니다. |

---

## 설정

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/settings` | 전역 GIS 설정: `saved_state`, `geo_layers`, `search_inputs`, `search_provider`. |
| POST | `/api/geo/settings` | 전역 설정 갱신 — 검색 제공자, 줌/컬링 임계값, 렌더링 스위치, `theme_*` 색상 키. 쓰기는 (한 번에 하나씩) 직렬화돼 갱신 유실 경쟁을 막습니다. |
| GET | `/api/geo/settings/length_unit` | `{length_unit, supported: ["mm","cm","m","in","ft"]}`. |
| PUT | `/api/geo/settings/length_unit` | 본문: `{length_unit}`. 캐시된 클라이언트 측 지도 설정을 TTL을 기다리지 않고 즉시 무효화합니다. |

---

## 지도 정렬

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/map/<map_uuid>/site_order` | 저장된 부지 목록 표시 순서와 부지별 구역 순서. |
| POST | `/api/geo/map/<map_uuid>/site_order` | 본문: `{order}` 그리고/또는 `{site_key, zone_order}`. |

---

## 시각·일출일몰

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/api/geo/local_time?lat=&lng=` | 지도 위젯 시계 독용 — 현지 타임존/시각과 일출·일몰 이벤트 창(어제부터 모레까지). |
| GET | `/api/geo/sun_event?target_id=` | 대상이 물려받은 위치 기준 오늘의 일출·일몰(하루 중 초 단위). |

---

## 구획/구역 일지 (`/geo/journal`)

**다른 접두사입니다** — `/api/geo`가 아니라 `/geo/journal` 밑에 있습니다. 일지는 구획·구역·부지에 대해 지정한 기간의 GDD, DLI, 일장, 관수량, 기상을 담은 생성 보고서로, 백그라운드에서 한 번 만들어진 뒤 저장된 스냅샷에서 그대로 서빙됩니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/geo/journal/plot_history?area_id=` | 주어진 지도 영역을 거쳐간 구획/작물 목록 — 일지 대상 선택기에서 씁니다. |
| GET | `/geo/journal` | 일지 허브 페이지(최근 일지 + 생성 폼). |
| POST | `/geo/journal` | 본문: `{target_type: 'plot'\|'zone'\|'site', target_id, start, end, measurements?, granularity?}`. 요청한 기간/채널 수가 너무 비싸면 작업을 시작하기도 전에 거부합니다. 비동기 백그라운드 생성을 시작합니다. JSON 호출자는 `{ok, unique_id, url}`을, 그 외는 리다이렉트를 받습니다. `edit_plots` 필요. |
| GET | `/geo/journal/<journal_uuid>?format=html\|md\|json\|csv\|odt&granularity=` | **저장된** 스냅샷을 읽습니다 — 원본 데이터를 다시 계산하지 않습니다(곡선 델타처럼 표시 전용 값 일부는 조회 시점에 계산). 생성이 끝나기 전에 파일 형식을 요청하면 `409`. `csv`는 엑셀 호환용 UTF-8 BOM 포함, `odt`는 `application/vnd.oasis.opendocument.text`. |
| DELETE | `/geo/journal/<journal_uuid>` | 일지와 거기 달린 노트를 삭제합니다. `edit_plots` 필요. |
| GET | `/geo/journal/target_info?target_type=&target_id=` | 대상의 가장 이른 데이터 날짜와 사용 가능한 측정 그룹 — 생성 폼을 미리 채우는 용도입니다. 최선노력이며 실패해도 조용히 넘어갑니다. |

---

## 그 밖

- `POST /api/tools/kma_lookup` — 작은 독립 유틸리티입니다(다른 접두사, `/api/geo/`가 아니라 `/api/tools/`): 주어진 위경도에 대한 기상청 격자 좌표(nx, ny)의 최근접 조회.

---

## 응답 코드

| 코드 | 의미 |
|------|------|
| 200 | 성공 |
| 201 | 생성 성공 |
| 400 | 잘못된 요청 (검증 오류) |
| 401 | 인증 필요 |
| 403 | 권한 없음 (권한, 스코프, 또는 읽기 전용 API 키) |
| 404 | 리소스 없음 |
| 409 | 충돌 (예: 이미 점유된 바인딩 슬롯, 참조 때문에 막힌 삭제, 필지 중복 가져오기) |
| 500 | 서버 오류 |
