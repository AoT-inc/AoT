# GIS 레이어 관리

`/geo/layer` 페이지에서 외부 지도 데이터 소스를 등록하고 관리합니다. 등록된 레이어는 디자인 도구와 대시보드 지도 위젯에서 기본 레이어 또는 오버레이로 사용됩니다.

---

## 지원 제공자 목록

### 국내 서비스

| 제공자 | 타입 코드 | 특징 | API 키 필요 |
|--------|----------|------|------------|
| VWorld | `gis_vworld` | 국토부 공식 지도, 지적도, 항공영상, PNU 필지 검색 | 필수 |
| Kakao Maps | `gis_kakao` | 국내 최고 정밀도 도로지도 | 필수 |
| Naver Maps | `gis_naver` | 실시간 교통 포함 국내 지도 | 필수 |

### 국제 일반

| 제공자 | 타입 코드 | 특징 | API 키 필요 |
|--------|----------|------|------------|
| OpenStreetMap | `gis_osm` | 무료 오픈소스 지도 | 불필요 |
| Google Maps | `gis_google` | 위성/도로/하이브리드 | 필수 |
| ESRI | `gis_esri` | 위성영상, 지형도, 도로지도 | 불필요 (일부 필요) |
| Mapbox | `gis_mapbox` | 벡터 타일, 커스텀 스타일 | 필수 |
| MapTiler | `gis_maptiler_vector` | 벡터 타일, 다양한 스타일 | 필수 |
| Bing | `gis_bing` | 위성영상, 조감도 | 필수 |
| Carto | `gis_carto` | 깔끔한 벡터 디자인 지도 | 불필요 |
| Stadia Maps | `gis_stadia` | 고품질 디자인 지도 | 선택 |
| Thunderforest | `gis_thunderforest` | 자전거/하이킹/교통 전문 지도 | 필수 |

### 위성·항공영상

| 제공자 | 타입 코드 | 특징 | API 키 필요 |
|--------|----------|------|------------|
| NASA GIBS | `gis_nasa_gibs` | 과학용 위성 영상, WMS | 불필요 |
| ESA | `gis_esa` | 유럽 우주기구 위성 | 불필요 |

### 기상 오버레이

| 제공자 | 타입 코드 | 특징 | API 키 필요 |
|--------|----------|------|------------|
| RainViewer | `gis_rainviewer` | 실시간/과거 강우 레이더 | 불필요 |
| OpenWeather | `gis_openweather` | 기온, 강수, 구름, 바람 레이어 | 필수 |
| Open-Meteo | (내장 프록시) | 기상 예보 데이터 | 불필요 |

### 전문 데이터

| 제공자 | 타입 코드 | 특징 | API 키 필요 |
|--------|----------|------|------------|
| OpenTopoMap | `gis_opentopomap` | 등고선·지형 지도 | 불필요 |
| ISRIC | `gis_isric` | 전세계 토양 데이터 (SoilGrids) | 불필요 |
| GSI | `gis_gsi` | 일본 국토지리원 지도 | 불필요 |
| SGIS | `gis_sgis` | 싱가포르 지리정보 | 불필요 |

---

## 레이어 등록 방법

1. `/geo/layer` 페이지로 이동합니다.
2. 우측 상단 **Input Type** 드롭다운에서 원하는 제공자를 선택합니다.
3. **Add** 버튼을 클릭합니다.
4. 생성된 항목의 **설정(기어) 아이콘**을 클릭합니다.
5. 필요한 옵션(API 키, 레이어 종류 등)을 입력합니다.
6. **Save** 후 **Activate** 버튼으로 활성화합니다.

---

## 제공자별 설정 상세

### VWorld

한국 국토정보플랫폼. VWorld 개발자 사이트(https://map.vworld.kr)에서 API 키를 발급받아야 합니다.

| 옵션 | 설명 |
|------|------|
| API Key | VWorld API 키 |
| Layer Type | `Base` (일반지도) / `Satellite` (항공영상) / `Hybrid` (하이브리드) / `Gray` (회색조) |

VWorld는 **필지 가져오기** 기능에도 사용됩니다. API 키가 등록되어야 주소 검색이 동작합니다.

### Google Maps

Google Cloud Console에서 Maps JavaScript API 키를 발급받아야 합니다.

| 옵션 | 설명 |
|------|------|
| API Key | Google Maps API 키 |
| Map Type | `roadmap` / `satellite` / `hybrid` / `terrain` |

### Mapbox / MapTiler

벡터 타일 제공자로, MapLibre GL과 네이티브 통합되어 부드러운 렌더링을 제공합니다.

| 옵션 | 설명 |
|------|------|
| API Key / Token | 각 서비스 대시보드에서 발급 |
| Style | 사용할 스타일 URL 또는 프리셋 선택 |

### RainViewer

API 키 없이 무료로 사용 가능한 강우 레이더입니다. 실시간 레이더 및 최근 2시간 과거 데이터를 지원합니다.

AoT 서버가 CORS 프록시(`/api/geo/proxy/rainviewer/*`)를 통해 중계하므로 클라이언트에서 직접 외부에 접근하지 않습니다.

### ISRIC (SoilGrids)

토양 유기물, pH, 질소 함량 등 전세계 토양 데이터를 WMS 방식으로 제공합니다. 농업 스마트팜에서 토양 분석에 활용됩니다.

---

## WMS 레이어

WMS(Web Map Service) 1.3.0 규격을 지원하는 모든 서버를 연동할 수 있습니다.

| 옵션 | 설명 |
|------|------|
| URL | WMS 서버 GetCapabilities URL |
| Layers | 표시할 레이어 이름 (쉼표 구분) |
| Format | `image/png` 또는 `image/jpeg` |
| CRS | 좌표계 (보통 `EPSG:3857`) |

AoT 서버가 WMS 타일 요청을 프록시(`/api/geo/proxy/wms/<unique_id>`)하여 CORS 문제를 해결합니다.

---

## 레이어 순서 및 표시 제어

GridStack 레이아웃으로 레이어 순서를 드래그하여 변경할 수 있습니다. 순서는 자동으로 저장됩니다.

각 레이어의 **눈 아이콘**으로 임시 표시/숨김을 전환합니다. **Activate/Deactivate**는 영구적으로 레이어를 활성화하거나 비활성화합니다.

---

## GIS 레이어 미리보기

레이어 항목의 **미리보기** 버튼을 클릭하면 해당 레이어가 지도에 어떻게 보이는지 팝업 미리보기를 확인할 수 있습니다.

- MapTiler, RainViewer의 경우 API 키 유효성 검증이 함께 수행됩니다.
- 미리보기가 표시되지 않으면 API 키 또는 네트워크 연결을 확인하세요.

---

## 관련 페이지

- [전역 GIS 설정](settings.md) — 기본 레이어 선택, 테마 색상
- [디자인 도구](design-tool.md) — 레이어 제어 패널 사용법
- [필지 가져오기](parcel-import.md) — VWorld 활용
