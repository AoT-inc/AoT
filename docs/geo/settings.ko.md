# GIS 전역 설정

`/geo/setting` 페이지에서 시스템 전체에 적용되는 GIS 기본값을 설정합니다. 설정은 `geo_setting` 테이블의 싱글턴 레코드로 저장됩니다.

---

## 기본 시작 위치

지도 위젯과 디자인 도구가 처음 열릴 때 표시할 기본 위치입니다.

| 항목 | 기본값 | 설명 |
|------|--------|------|
| 위도 (Latitude) | 37.5665 | 서울 중심 좌표 |
| 경도 (Longitude) | 126.9780 | 서울 중심 좌표 |
| 줌 레벨 | 13 | 초기 줌 (1=세계, 22=건물) |

지도에서 원하는 위치와 줌으로 이동한 후 **현재 위치로 설정** 버튼을 클릭하면 자동으로 입력됩니다.

---

## 디자인 테마 색상

디자인 도구와 지도 위젯에서 사용할 계층별 색상입니다.

| 계층 | 의미 |
|------|------|
| Site | 부지 경계 |
| Zone | 구역 경계 |
| Facility | 시설 건물 |
| Equipment | 설비 |
| Device | AoT 장치 마커 |
| Panel Background | 속성 패널 배경 |

각 항목에 색상 피커와 불투명도(0~100%) 슬라이더가 제공됩니다.

---

## 지도 동작 설정

### 줌 설정

| 항목 | 기본값 | 설명 |
|------|--------|------|
| Max Zoom | 22 | 지도 최대 줌 레벨 |
| Equipment Cull Zoom | 15 | 이 줌 레벨 미만에서 Equipment/Device 마커 숨김 |

**Equipment Cull Zoom** 설정은 넓은 지역을 줌아웃할 때 수많은 장치 마커가 지도를 가리는 것을 방지합니다. 줌이 `15` 미만이 되면 Equipment/Device 마커가 자동으로 숨겨집니다.

### 줌 방식

| 항목 | 기본값 | 설명 |
|------|--------|------|
| Digital Zoom | Off | 타일 해상도를 초과한 후에도 CSS 배율로 줌 지속 |
| Smooth Zoom | On | 핀치 줌 시 부드러운 보간 |

---

## 성능 및 렌더링

| 항목 | 기본값 | 설명 |
|------|--------|------|
| Tile Fade Animation | On | 타일 로드 시 페이드인 애니메이션 |
| Prefer Canvas | Off | Canvas 렌더러 우선 사용 (SVG 대신, Leaflet 모드만 해당) |

### 폴리곤 표시 한도

대시보드 지도 위젯에서 한번에 렌더링하는 폴리곤 수를 제한합니다. 초과 시 클러스터링됩니다.

| 항목 | 기본값 |
|------|--------|
| Site 폴리곤 최대 수 | 500 |
| Zone 폴리곤 최대 수 | 1000 |
| Device 마커 최대 수 | 2000 |

---

## 단위 설정

시설 공학 계산 및 치수 입력에 사용할 길이 단위를 선택합니다.

| 단위 코드 | 표시 |
|----------|------|
| `m` | 미터 (기본값) |
| `cm` | 센티미터 |
| `mm` | 밀리미터 |
| `ft` | 피트 |
| `in` | 인치 |

---

## API

```http
GET /api/geo/settings
```

현재 전역 설정을 JSON으로 반환합니다.

```http
POST /api/geo/settings
Content-Type: application/json

{
  "default_lat": 37.5665,
  "default_lng": 126.9780,
  "default_zoom": 13,
  "max_zoom": 22,
  "equipment_cull_zoom": 15,
  "digital_zoom": false,
  "smooth_zoom": true,
  "tile_fade_animation": true,
  "prefer_canvas": false,
  "length_unit": "m",
  "max_polygons_site": 500,
  "max_polygons_zone": 1000,
  "max_polygons_device": 2000,
  "theme_config": {
    "site": { "color": "#2563eb", "opacity": 0.3 },
    "zone": { "color": "#16a34a", "opacity": 0.3 },
    "facility": { "color": "#ea580c", "opacity": 0.4 },
    "equipment": { "color": "#6b7280", "opacity": 0.5 },
    "device": { "color": "#dc2626", "opacity": 1.0 }
  }
}
```

---

## 관련 페이지

- [GIS 레이어](layers.md) — 제공자 API 키 등록
- [디자인 도구](design-tool.md) — 테마 색상 적용 확인
