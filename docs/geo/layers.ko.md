# GIS 레이어 관리

`/geo/layer` 페이지에서 외부 지도 데이터 소스를 등록하고 관리합니다. 등록된 레이어는 디자인 도구와 대시보드 지도 위젯에서 기본 레이어 또는 오버레이로 사용됩니다.

---

## 지원 제공자 목록

### 국내 서비스 { #domestic-korea }

| 제공자 | 타입 코드 | 특징 | API 키 필요 |
|--------|----------|------|------------|
| VWorld | `gis_vworld` | 국토부 공식 지도, 지적도, 항공영상, 주소로 필지 조회 | 필수 |
| Kakao Maps | `gis_kakao` | 국내 일반지도·위성·하이브리드 타일 | 불필요 |
| Naver Maps | `gis_naver` | 국내 일반지도·위성·지형 타일 | 불필요 |

### 국제 일반 { #international-general }

| 제공자 | 타입 코드 | 특징 | API 키 필요 |
|--------|----------|------|------------|
| OpenStreetMap | `gis_osm` | 무료 오픈소스 지도 | 불필요 |
| Google Maps | `gis_google` | 위성/도로/하이브리드 | 필수 |
| ESRI | `gis_esri` | World Imagery 위성영상 | 불필요 |
| Mapbox | `gis_mapbox` | 프리셋 스타일 8종의 지도 타일 | 필수 |
| MapTiler | `gis_maptiler_vector` | 벡터 타일, 다양한 스타일 | 필수 |
| Bing | `gis_bing` | 항공영상, 라벨 포함 항공영상, 도로지도 | 선택 |
| Carto | `gis_carto` | 절제된 디자인 지도(Positron, Dark Matter, Voyager) | 불필요 |
| Stadia Maps | `gis_stadia` | 고품질 디자인 지도 | 필수 |
| Thunderforest | `gis_thunderforest` | 자전거/하이킹/교통 전문 지도 | 필수 |

### 위성·항공영상 { #satellite-aerial }

| 제공자 | 타입 코드 | 특징 | API 키 필요 |
|--------|----------|------|------------|
| NASA GIBS | `gis_nasa_gibs` | 위성 영상과 환경 레이어, 날짜 선택 가능 | 불필요 |
| Soil Moisture (NASA SMAP) | `gis_esa` | 약 9km 지표 토양 수분(0~5cm) 오버레이, 날짜 선택 가능 | 불필요 |
| Sentinel Hub | `gis_sentinelhub` | Sentinel-2 10m 해상도 NDVI·수분·수계 지수 | 필요 (OAuth 클라이언트) |

### 기상 오버레이 { #weather-overlays }

| 제공자 | 타입 코드 | 특징 | API 키 필요 |
|--------|----------|------|------------|
| RainViewer | `gis_rainviewer` | 실시간/과거 강우 레이더 | 불필요 (프리미엄만 필요) |
| OpenWeather | `gis_openweather` | 구름, 강수, 기압, 바람, 기온 레이어 | 필수 |
| KMA Weather | `gis_kma` | 기상청 500m 관측값, 지도 범례로 표시 | 필수 |
| Open-Meteo | (내장 프록시) | 기상 예보 데이터 | 불필요 |

### 전문 데이터 { #specialized-data }

| 제공자 | 타입 코드 | 특징 | API 키 필요 |
|--------|----------|------|------------|
| OpenTopoMap | `gis_opentopomap` | 등고선·지형 지도 | 불필요 |
| ISRIC | `gis_isric` | 전세계 토양 데이터 (SoilGrids) | 불필요 |
| GSI | `gis_gsi` | 일본 국토지리원 지도 | 불필요 |
| SGIS | `gis_sgis` | 통계청 통계지리정보 | 필요 |
| Agromonitoring | `gis_agromonitoring` | 필지 단위 NDVI 통계·토양 수분·지온 | 필요 |

---

## 레이어 등록 방법 { #how-to-register-a-layer }

1. `/geo/layer` 페이지로 이동합니다.
2. 화면 위쪽 **Select GIS Service** 드롭다운에서 원하는 제공자를 선택합니다.
3. **Add** 버튼을 클릭합니다. 레이어는 비활성 상태로 만들어집니다.
4. 생성된 항목의 **설정(기어) 아이콘**을 클릭합니다.
5. 필요한 옵션(API 키, 레이어 종류 등)을 입력합니다.
6. **Save** 후 **Activate** 버튼으로 활성화합니다.

---

## 제공자별 설정 상세

### VWorld { #vworld }

한국 국토정보플랫폼. VWorld 개발자 사이트(https://map.vworld.kr)에서 API 키를 발급받아야 합니다.

| 옵션 | 설명 |
|------|------|
| API Key | VWorld API 키 |
| Registered Domain | 키를 등록한 도메인. 비워 두면 지금 접속한 주소를 씁니다 |
| Map Layer / Style | 배경: `Base Map` / `Satellite` / `Hybrid` / `Gray Map` / `Dark Map`. 오버레이: 지적도, 농업진흥지역, 생태자연도, 개발제한구역, 개별공시지가 |
| Show Legend | 그 레이어의 범례를 지도에 띄울지 |

VWorld는 **필지 가져오기** 기능에도 사용됩니다. API 키가 등록되어야 주소 검색이 동작하며, 등록된 VWorld 레이어가 활성화돼 있지 않아도 그 레이어의 키를 읽어 씁니다.

### Google Maps { #google-maps }

Google Cloud Console에서 Maps JavaScript API 키를 발급받아야 합니다.

| 옵션 | 설명 |
|------|------|
| Google Maps API Key | Google Maps API 키 |
| Map Style | `Roadmap` / `Satellite` / `Hybrid` / `Terrain` 중 하나 |

### Mapbox / MapTiler { #mapbox-maptiler }

MapTiler는 벡터 타일을 제공하며 MapLibre GL이 직접 그립니다. Mapbox는 고른 스타일로 렌더링된 지도 타일로 제공됩니다.

| 옵션 | 설명 |
|------|------|
| API Key / Token | 각 서비스 대시보드에서 발급 |
| Map Style | 프리셋 스타일 중 하나 선택(Mapbox 8종, MapTiler 6종) |
| Label Language | MapTiler 전용 — 지도 라벨 언어(예: `ko`, `en`, `auto`) |

### RainViewer { #rainviewer }

API 키 없이 쓸 수 있습니다 — 키 입력란은 RainViewer 프리미엄 기능용입니다. 실시간 레이더와 최근 2시간 과거 데이터(10분 간격 12장)를 지원합니다. 레이더의 상세도는 줌 7 정도에서 멈춥니다.

레이더 타일은 브라우저가 RainViewer에서 직접 받고, AoT 서버를 거치는 것은 사용 가능한 프레임 목록뿐입니다(`/api/geo/proxy/rainviewer/*`). 목록을 못 받으면 오류를 띄우지 않고 프레임이 없는 상태로 남습니다.

### ISRIC (SoilGrids) { #isric-soilgrids }

pH(물), 점토·모래·미사 함량, 토양 유기탄소, 용적밀도를 각각 0~5cm 깊이 기준으로 WMS 방식으로 제공합니다. 상세도는 원자료의 250m 격자에서 멈추므로, 그보다 더 확대해도 같은 그림이 커질 뿐입니다. 농업 스마트팜에서 토양 분석에 활용됩니다.

### Sentinel Hub (Sentinel-2) { #sentinel-hub-sentinel-2 }

10m 해상도 Sentinel-2 영상입니다. MODIS NDVI가 250m 화소 하나로 덮는 6.25ha를 여기서는 625개 화소로 보므로, 한 필지 안의 생육 편차가 드러납니다.

[Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/)에서 무료 계정을 만들고 대시보드에서 OAuth 클라이언트를 생성한 뒤 Client ID와 Secret을 입력합니다. Sentinel Hub는 OAuth2 client credentials 방식이라 타일을 AoT 서버가 대신 받아옵니다(`/api/geo/proxy/sentinelhub/<unique_id>`) — Secret은 브라우저로 나가지 않습니다.

| 옵션 | 설명 |
|--------|-------------|
| 레이어 | NDVI, 트루컬러, NDMI(수분), NDWI(수계), 위색조합 |
| 컬렉션 | L2A(대기보정) 또는 L1C |
| 검색 기간 | 특정 날짜 하나로는 구름 때문에 화면이 비므로, 이 기간에서 쓸 수 있는 가장 최근 장면을 그립니다 |
| 최대 운량 / 장면 우선순위 | 그 기간 안에서 어떤 장면을 고를지 |

무료 등급은 월 30,000 PU입니다. 지도 화면 한 번이 약 4 PU이고 타일은 하루 캐시하며, 줌 9 미만에서는 아예 요청하지 않습니다 — 10m 자료를 광역으로 보는 것은 예산만 쓰고 보이는 것이 없습니다.

### Agromonitoring (필지 NDVI·토양) { #agromonitoring-field-ndvi-soil }

등록한 필지 경계의 NDVI 통계와 **토양 수분·지온을 숫자로** 제공하는 유일한 레이어입니다. SMAP 오버레이는 9km 그림이고, NASA GIBS 범례의 토양 수분 숫자는 Open-Meteo 모델값을 빌려 온 것입니다.

필지는 Agromonitoring 대시보드에서 그립니다(1~3000ha). 폴리곤 ID를 붙여넣거나, 비워 두면 클릭한 지점을 포함하는 폴리곤을 자동으로 찾습니다. 어느 폴리곤에도 들어가지 않는 지점을 누르면 중심이 가장 가까운 폴리곤을 대신 씁니다. API 키는 OpenWeatherMap과 같은 계정의 것을 씁니다.

**Active Channels**에서 보여 줄 값을 고릅니다 — NDVI(평균), 토양 수분, 지표 지온, 10cm 지온. **NDVI Search Window**(14·30·60·90일, 기본 30일)는 가장 최근 통과를 어디까지 거슬러 찾을지 정합니다. 구름이 끼면 몇 주 동안 쓸 만한 장면이 없을 수 있습니다.

값은 서버를 거쳐 조회하고(`/api/geo/proxy/agromonitoring/<unique_id>`) 30분 캐시합니다 — 무료 등급의 호출 한도가 공개돼 있지 않기 때문입니다.

---

## WMS 레이어 { #wms-layers }

일부 제공자는 오버레이를 완성된 타일이 아니라 WMS(Web Map Service) 방식으로 내려줍니다 — VWorld 데이터 오버레이(지적도, 농업진흥지역, 생태자연도, 개발제한구역, 개별공시지가)와 ISRIC SoilGrids가 그렇습니다. WMS를 따로 입력하는 항목은 없습니다. 제공자를 등록하고 그 설정에서 원하는 채널을 고르면 됩니다.

| 요청 항목 | 값 |
|------|------|
| 요청 | `GetMap`, 타일 한 장은 256×256 이미지 |
| 버전 | `1.3.0`. 제공자가 다른 값을 선언하면 그것을 따릅니다 |
| 좌표계 | 항상 `EPSG:3857` |
| 이미지 형식 | 투명도가 있는 `image/png`. 제공자가 다른 값을 선언하면 그것을 따릅니다 |

이 이미지들은 AoT 서버가 대신 받아옵니다(`/api/geo/proxy/wms/<unique_id>`). 해당 서비스들이 브라우저에서 바로 읽는 것을 허용하지 않기 때문입니다. 지도에서 보이는 차이는 두 가지입니다.

- 상위 서버가 오류를 내거나 15초 안에 응답하지 않으면, 그 오버레이만 빈 상태로 남고 나머지 지도는 그대로 동작하며 오류로 알리지는 않습니다. 실패는 기억하지 않으므로 서비스가 돌아오면 오버레이도 바로 다시 나옵니다.
- 한 번 받은 이미지는 서버에서 일주일, 브라우저에서 하루 동안 다시 쓰이므로, 상위에서 바뀐 내용이 그만큼 늦게 보일 수 있습니다. 레이어 자체의 설정을 바꾸면 그 즉시 반영됩니다.

---

## 레이어 순서 및 표시 제어 { #layer-order-and-visibility }

각 레이어 왼쪽의 손잡이를 끌어 순서를 바꿉니다. 놓는 순간 새 순서가 저장됩니다. 화면이 좁아 목록이 한 열로 바뀌면, 그 상태에서 끌어 옮겨도 저장된 순서는 바뀌지 않습니다.

각 줄의 **Activate**/**Deactivate**는 그 레이어를 지도에서 쓸지 말지를 정합니다. 레이어의 어떤 채널을 보일지는 설정 창 안 미리보기 지도의 레이어 버튼에서 고르며, 이 선택은 레이어와 함께 저장됩니다.

---

## GIS 레이어 미리보기 { #layer-preview }

레이어의 설정 창(기어 아이콘)을 열면 맨 위에 미리보기 지도가 나타나며, 지금 입력된 옵션 그대로 그려집니다. 옵션을 바꿀 때마다 다시 그리므로, 저장하기 전에 키나 스타일을 확인할 수 있습니다.

- 미리보기 오른쪽 위의 레이어 버튼으로 배경지도를 바꾸고 오버레이 채널을 켜고 끕니다. 이 선택은 레이어와 함께 저장됩니다.
- 미리보기가 표시되지 않으면 API 키 또는 네트워크 연결을 확인하세요.

---

## 관련 페이지

- [전역 GIS 설정](settings.md) — 기본 레이어 선택, 테마 색상
- [디자인 도구](design-tool.md) — 레이어 제어 패널 사용법
- [필지 가져오기](parcel-import.md) — VWorld 활용
