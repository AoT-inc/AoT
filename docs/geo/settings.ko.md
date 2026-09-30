# GIS 전역 설정

`/geo/setting` 페이지에서 시스템 전체에 적용되는 GIS 기본값을 설정합니다. 설정은 `geo_setting` 테이블의 싱글턴 레코드로 저장됩니다.

---

## 기본 시작 위치 { #default-start-location }

지도 위젯과 디자인 도구가 처음 열릴 때 표시할 기본 위치입니다.

| 항목 | 기본값 | 설명 |
|------|--------|------|
| 위도 (Latitude) | 37.5665 | 서울 중심 좌표 |
| 경도 (Longitude) | 126.9780 | 서울 중심 좌표 |
| 줌 레벨 (Zoom Level) | 12 | 초기 줌 (작을수록 넓은 범위, 클수록 가까이) |

지도에서 원하는 위치와 줌으로 이동한 뒤 **현재 화면(Current View)** 행의 **위치 가져오기** 버튼을 누르면 세 항목이 현재 지도 화면 값으로 채워집니다.

---

## 디자인 테마 색상 { #design-theme-colors }

디자인 도구와 지도 위젯에서 사용할 계층별 색상입니다.

| 계층 | 의미 |
|------|------|
| Site | 부지 경계 |
| Zone | 구역 경계 |
| Facility | 시설 건물 |
| Equipment | 설비 |
| Device | AoT 장치 마커 |
| Panel Background | 속성 패널 배경 |

각 행에는 색상 피커가 있습니다. 한 번도 저장하지 않은 색은 지금 실제로 쓰이는 색(전역 기본값)을 보여 주며 미설정 상태로 남고, 직접 바꿀 때만 저장됩니다. **패널 불투명도** 슬라이더(0~100%, 5단위) 하나가 속성 패널 배경에 적용됩니다.

---

## 지도 동작 설정

### 줌 설정 { #zoom-settings }

| 항목 | 기본값 | 설명 |
|------|--------|------|
| Max Zoom | 25 | 지도 최대 줌 레벨 (1~30 입력 가능) |
| Equipment Hide Zoom | 15 | 이 줌 레벨 미만에서 Equipment 항목 숨김 (1~25 입력 가능) |

**Equipment Hide Zoom** 설정은 넓은 지역을 줌아웃할 때 수많은 설비 항목이 지도를 가리는 것을 방지합니다. 줌이 `15` 미만이 되면 배관, 연결점, 살수 범위, 3D 시설 모형이 자동으로 숨겨집니다. AoT 장치 마커는 이 설정과 무관하게 모든 줌에서 계속 보입니다.

### 줌 방식 { #zoom-method }

| 항목 | 기본값 | 설명 |
|------|--------|------|
| Digital Zoom | On | 타일 해상도를 초과한 후에도 CSS 배율로 줌 지속 |
| Smooth Zoom | On | 핀치 줌 시 부드러운 보간 |

---

## 성능 및 렌더링 { #performance-rendering }

| 항목 | 기본값 | 설명 |
|------|--------|------|
| Tile Fade Animation | On | 타일 로드 시 페이드인 애니메이션 |
| Serve MapLibre Locally | On | MapLibre GL 라이브러리를 CDN 대신 로컬 파일로 제공. 끄면 CDN 에서 라이브러리를 받아옵니다 |
| Prefer Canvas Rendering | Off | Canvas 렌더러 우선 사용 (SVG 대신, Leaflet 모드만 해당) |

### 폴리곤 표시 한도 { #polygon-display-limits }

지도 설정과 함께 보관되는 상한값입니다. 저장되고 여기서 수정할 수 있지만, 현재 지도 그리기에는 아직 반영되지 않습니다.

| 항목 | 기본값 |
|------|--------|
| Max Site Polygons | 1000 |
| Max Zone Polygons | 1000 |
| Max Device Polygons | 1000 |

---

## 단위 설정 { #unit-settings }

시설 공학 계산 및 치수 입력에 사용할 길이 단위를 선택합니다.

| 단위 코드 | 표시 |
|----------|------|
| `m` | 미터 (기본값) |
| `cm` | 센티미터 |
| `mm` | 밀리미터 |
| `ft` | 피트 |
| `in` | 인치 |

---

## API { #api }

```http
GET /api/geo/settings
```

현재 전역 설정을 JSON으로 반환합니다. 설정 편집 권한이 필요하며, 권한이 없으면 요청이 거부됩니다.

응답은 `{"ok": true, "saved_state": { ... }, "geo_layers": [...], "search_inputs": [...], "search_provider": "..."}` 형태입니다. `saved_state`에는 저장된 설정이 담기며(기본 시작 줌은 `zoom` 키로 돌아옵니다), 저장된 지도 제공자 키도 함께 포함됩니다.

```http
POST /api/geo/settings
Content-Type: application/json

{
  "default_lat": 37.5665,
  "default_lng": 126.9780,
  "default_zoom": 12,
  "max_zoom": 25,
  "equipment_cull_zoom": 15,
  "digital_zoom": true,
  "smooth_zoom": true,
  "tile_fade_animation": true,
  "maplibre_local_serving": false,
  "prefer_canvas": false,
  "search_provider": "",
  "max_polygons_site": 1000,
  "max_polygons_zone": 1000,
  "max_polygons_device": 1000,
  "theme_site": "#2563eb",
  "theme_zone": "#16a34a",
  "theme_facility": "#ea580c",
  "theme_equipment": "#6b7280",
  "theme_device": "#dc2626",
  "theme_panel_bg": "#ffffff",
  "theme_panel_opacity": 90
}
```

모든 키는 선택입니다 — 보내지 않은 키는 저장된 값이 그대로 유지되고, 허용 목록에 없는 키는 조용히 무시됩니다. JSON 외에 폼 인코딩 본문도 받습니다. 테마 값은 중첩 객체가 아니라 평평한 `theme_*` 키로 보내며, 디자인 드로어의 표시 토글도 같은 `theme_*` 계열로 저장됩니다. `search_provider`가 비어 있으면 "지도 설정을 따름"입니다. 저장에 성공하면 `{"ok": true, "message": "Settings Saved"}`를 돌려주고, 저장에도 설정 편집 권한이 필요합니다.

길이 단위는 이 엔드포인트에 포함되지 않고 별도 엔드포인트를 씁니다.

```http
GET /api/geo/settings/length_unit
PUT /api/geo/settings/length_unit
Content-Type: application/json

{ "length_unit": "m" }
```

`GET`은 현재 단위와 지원 단위 목록을 함께 반환하고, `PUT`은 목록에 없는 값을 거부합니다.

---

## 관련 페이지

- [GIS 레이어](layers.md) — 제공자 API 키 등록
- [디자인 도구](design-tool.md) — 테마 색상 적용 확인
