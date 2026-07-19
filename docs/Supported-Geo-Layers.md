## Built-In Map Layers (Providers)

### CARTO: GL: Carto Maps

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://carto.com/attributions">CARTO</a>
- Service URL: `https://{s}.basemaps.cartocdn.com/{style}/{z}/{x}/{y}{r}.png`
- Manufacturer: CARTO
- Libraries: gis_carto
- Manufacturer URL: [Link](https://carto.com/)

CARTO DB에서 제공하는 데이터 분석 전용 지도입니다. 색감이 절제된 Positron(밝음), Dark Matter(어두움), Voyager 스타일을 제공하여, 위에 표현되는 데이터 포인트나 센서 정보가 더욱 돋보이도록 설계되었습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Active Map Styles</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### ESA: GL: Soil Moisture (NASA SMAP)

- Layer Type: xyz
- Default Role: Overlay
- Attribution: NASA SMAP L4 Soil Moisture
- Service URL: `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/SMAP_L4_Analyzed_Surface_Soil_Moisture/default/{time}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png`
- Time Enabled: Yes
- Manufacturer: ESA
- Libraries: gis_esa
- Manufacturer URL: [Link](https://smap.jpl.nasa.gov/)

유럽우주국(ESA)의 Sentinel-2 위성 데이터를 기반으로 한 전 세계 토지 피복(Land Cover) 지도입니다. 식생, 도시, 농경지, 산림, 수역 등을 10m급 고해상도로 분석하여 색상별로 확인할 수 있어 환경 분석에 유용합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Date Mode</td><td>Select</td><tr><td>Custom Date</td><td>Text</td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### Esri: GL: Esri World Imagery

- Layer Type: xyz
- Attribution: &copy; <a href="https://www.esri.com/">Esri</a>
- Service URL: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`
- Manufacturer: Esri
- Libraries: gis_esri
- Manufacturer URL: [Link](https://www.esri.com/)

세계적인 GIS 기업 Esri의 공신력 있는 지도 서비스입니다. 선명하고 정교한 World Imagery 항공 위성 사진을 제공하여 지형의 세부 형상과 시설물을 정확하게 조망하기에 최적화되어 있습니다.


- GIS Search: Supported (Address/Place)
  - Capabilities: 

### GSI: JP: GSI Maps

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://maps.gsi.go.jp/development/ichiran.html">Geospatial Information Authority of Japan</a>
- Service URL: `https://cyberjapandata.gsi.go.jp/xyz/{layer}/{z}/{x}/{y}.png`
- Manufacturer: GSI
- Libraries: gis_gsi
- Manufacturer URL: [Link](https://maps.gsi.go.jp/)

일본 국토지리원(GSI)에서 제공하는 고정밀 공공 지도 서비스입니다. 일본 전역의 세부적인 지형과 지명 정보를 담고 있으며, 표준 지도뿐만 아니라 담색 지도, 항공 사진 등 전문적인 레이어를 활용할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Map Style</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: address, place

### Google: GL: Google Maps

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://www.google.com/maps">Google Maps</a>
- Service URL: `https://mt1.google.com/vt/lyrs={layer}&x={x}&y={y}&z={z}`
- Manufacturer: Google
- Libraries: gis_google
- Manufacturer URL: [Link](https://www.google.com/maps)

가장 널리 사용되는 구글의 웹 지도 서비스입니다. 방대한 지리 정보를 바탕으로 Road, Satellite, Hybrid, Terrain 등 4가지 모드를 지원하며, 특히 지형의 등고와 음영을 보여주는 Terrain 지도가 우수합니다. 또한, 구글의 Geocoding API를 이용하여 주소를 좌표로 변환할 수 있습니다. API 키는 구글 개발자 콘솔에서 발급 가능합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Google Maps API Key</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: address, place

### ISRIC: GL: SoilGrids (Global Soil Info)

- Layer Type: wms
- Default Role: Overlay
- Attribution: ISRIC - World Soil Information
- Service URL: `https://maps.isric.org/mapserv`
- Manufacturer: ISRIC
- Libraries: gis_isric
- Manufacturer URL: [Link](https://soilgrids.org/)

세계 토양 정보 서비스(ISRIC)에서 제공하는 글로벌 토양 특성 지도입니다. 지질학적 분석을 위한 토양 성분(점토, 모래 등), pH 수치, 탄소 함유량 등 전 세계의 지하 자원 및 환경 정보를 레이어 형태로 시각화해 줍니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Soil Property</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### Kakao: KO: Kakao Map

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://map.kakao.com/">Kakao</a>
- Service URL: `http://map1.daumcdn.net/map_2d/2103cov/L{z}/{y}/{x}.png`
- Manufacturer: Kakao
- Libraries: gis_kakao
- Manufacturer URL: [Link](https://map.kakao.com/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Map Type</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### Mapbox: GL: Mapbox

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://www.mapbox.com/about/maps/">Mapbox</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>
- Service URL: `https://api.mapbox.com/styles/v1/{layer}/tiles/{z}/{x}/{y}?access_token={api_key}`
- Manufacturer: Mapbox
- Libraries: gis_mapbox
- Manufacturer URL: [Link](https://www.mapbox.com/)

세련된 디자인과 커스터마이징이 강점인 맵박스의 벡터 및 타일 지도입니다. Streets, Satellite, Dark, Light 스타일을 지원하며, 렌더링 성능이 매우 우수하여 부드러운 지도 조작 환경을 제공합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Mapbox Access Token</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: address, place

### Microsoft: GL: Bing Maps

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://www.bing.com/maps">Microsoft Bing Maps</a>
- Service URL: `https://ecn.t1.tiles.virtualearth.net/tiles/{style}{q}.{ext}?g=12986`
- Manufacturer: Microsoft
- Libraries: gis_bing
- Manufacturer URL: [Link](https://www.bing.com/maps)

마이크로소프트의 글로벌 지도 서비스입니다. 고해상도 항공 사진(Aerial)과 이름이 포함된 항공 사진(Hybrid)을 제공하며, MS만의 깨끗하고 정밀한 도로 지도를 활용할 수 있는 장점이 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bing Maps API Key</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: address, place

### NASA: NASA GIBS

- Layer Type: xyz
- Default Role: Base
- Attribution: NASA EOSDIS GIBS
- Service URL: `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/{time}/{tilematrixset}/{z}/{y}/{x}.{ext}`
- Time Enabled: Yes
- Manufacturer: NASA
- Libraries: gis_nasa_gibs
- Manufacturer URL: [Link](https://earthdata.nasa.gov/eosdis/science-system-description/eosdis-components/gibs)

미국 항공우주국(NASA)의 위성 관측 시스템(GIBS)을 통해 수집된 실시간 지구 관측 지도입니다. 위성 사진(Blue Marble)뿐만 아니라 기온, 구름, 화재 등 환경 관련 데이터를 날짜별로 선택하여 시계열 분석이 가능합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Satellite Layer</td></td><tr><td>Date Mode</td><td>Select</td><tr><td>Custom Date</td><td>Text</td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### Naver: KO: Naver Map

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://map.naver.com/">Naver</a>
- Service URL: `https://map.pstatic.net/nrb/styles/basic/{z}/{x}/{y}.png`
- Manufacturer: Naver
- Libraries: gis_naver
- Manufacturer URL: [Link](https://map.naver.com/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Map Type</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### OpenStreetMap: GL: OpenStreetMap

- Layer Type: xyz
- Attribution: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>
- Service URL: `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`
- Manufacturer: OpenStreetMap
- Libraries: gis_osm
- Manufacturer URL: [Link](https://www.openstreetmap.org/)

전 세계 사용자들이 협업하여 만든 위키피디아 방식의 자유 지도 데이터입니다. 무료로 사용 가능하며, 전 세계 도로와 건물 정보가 꾸준히 업데이트되는 활발한 커뮤니티 성격의 표준 웹 지도입니다.


- GIS Search: Supported (Address/Place)
  - Capabilities: address, place

### OpenTopoMap: GL: OpenTopoMap

- Layer Type: xyz
- Default Role: Base
- Attribution: Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)
- Manufacturer: OpenTopoMap
- Libraries: gis_opentopomap
- Manufacturer URL: [Link](https://opentopomap.org)

OpenStreetMap 데이터를 기반으로 등고선과 지형 음영을 강조한 지형도 서비스입니다. 산악 지형이나 경사면 분석 시 구분이 명확하며 가독성이 높아 등산이나 야외 활동 관련 시각화에 적합합니다.


- GIS Search: Supported (Address/Place)
  - Capabilities: 

### OpenWeatherMap: GL: OpenWeatherMap

- Layer Type: xyz
- Default Role: Overlay
- Attribution: &copy; <a href="http://openweathermap.org">OpenWeatherMap</a>
- Service URL: `https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png?appid={api_key}`
- Manufacturer: OpenWeatherMap
- Libraries: gis_openweather
- Manufacturer URL: [Link](https://openweathermap.org/)

전 세계 날씨 정보를 지도에 중첩하여 보여주는 기상 전문 서비스입니다. 구름, 강수량, 기온, 풍속, 기압 및 레이더 정보를 실시간으로 제공하여 현재 기상 상황을 직관적으로 파악할 수 있게 돕습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>Text</td><tr><td>Active Layers</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### RainViewer: GL: RainViewer (Radar) [Discontinued]

- Layer Type: xyz
- Default Role: Overlay
- Attribution: Map Data &copy; <a href="https://www.rainviewer.com/api.html">RainViewer</a>
- Service URL: `https://tilecache.rainviewer.com/v2/radar/{ts}/256/{z}/{x}/{y}/{color_scheme}/{smoothing}_1.png?key={api_key}`
- Time Enabled: Yes
- Manufacturer: RainViewer
- Libraries: gis_rainviewer
- Manufacturer URL: [Link](https://www.rainviewer.com/)

[Service Discontinued / 서비스 중단 안내] RainViewer의 Radar API 서비스가 2026년 1월 31일부로 종료되었습니다. 현재 이 레이어의 실시간 데이터 수신은 불가능합니다. 대안으로 OpenWeatherMap (Radar) 레이어 사용을 권장합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>Text</td><tr><td>Color Scheme</td><td>Select</td><tr><td>Smoothing</td><td>Boolean</td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### Stadia Maps: GL: Stadia Maps

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://stadiamaps.com/">Stadia Maps</a>
- Service URL: `https://tiles.stadiamaps.com/tiles/{layer}/{z}/{x}/{y}{r}.{ext}?api_key={api_key}`
- Manufacturer: Stadia Maps
- Libraries: gis_stadia
- Manufacturer URL: [Link](https://stadiamaps.com/)

고품질 디자인을 강조하는 Stadia Maps의 지도 서버입니다. Alidade Smooth, Dark, OSMBright 등 눈이 편안한 색감과 고품질 폰트가 적용된 깔끔한 레이아웃을 제공하여 전문가용 대시보드 제작에 유리합니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Stadia/Stamen API Key</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: address, place

### Statistics Korea: KO: SGIS (Statistics Korea)

- Layer Type: geojson
- Default Role: Overlay
- Attribution: &copy; <a href="https://sgis.kostat.go.kr/">Statistics Korea (KOSTAT)</a>
- Manufacturer: Statistics Korea
- Libraries: gis_sgis
- Manufacturer URL: [Link](https://sgis.kostat.go.kr/)

대한민국 통계청(SGIS)에서 제공하는 통계 지리 정보 서비스입니다. 한국의 시군구별 인구, 가구, 사업체 등 다양한 통계 데이터를 공간적으로 분석하고 시각화하기 위한 최적의 국내 전용 서비스입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>SGIS Service ID (Consumer Key)</td><td>Text</td><tr><td>SGIS Security Key (Consumer Secret)</td><td>Text</td><tr><td>Data Configuration</td></td><tr><td>Statistic Subject</td><td>Select</td><tr><td>Year (YYYY)</td><td>Text</td><tr><td>Target Admin Code (adm_cd)</td><td>Text</td><tr><td>Visualization</td><td>Select</td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: address

### Thunderforest: GL: Thunderforest

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://www.thunderforest.com/">Thunderforest</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>
- Service URL: `https://tile.thunderforest.com/{layer}/{z}/{x}/{y}.png?apikey={api_key}`
- Manufacturer: Thunderforest
- Libraries: gis_thunderforest
- Manufacturer URL: [Link](https://www.thunderforest.com/)

OpenStreetMap 데이터를 활용하여 특정 목적에 맞춘 독창적인 테마 지도를 제공합니다. 자전거 도로(Cycle), 대중교통(Transport), 밤 지도, 거친 풍경 등 시각적으로 강렬한 고유 스타일을 경험할 수 있습니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Thunderforest API Key</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: address, place

### Vworld: KO: Vworld

- Layer Type: xyz
- Default Role: Base
- Attribution: <a href="https://www.vworld.kr/" target="_blank"><img src="https://www.vworld.kr/img/img_opentype01.png" alt="Vworld" style="height:28px;"></a>
- Service URL: `https://api.vworld.kr/req/wmts/1.0.0/{api_key}/{layer}/{z}/{y}/{x}.png`
- Manufacturer: Vworld
- Libraries: gis_vworld
- Manufacturer URL: [Link](https://www.vworld.kr/)

대한민국 국토교통부의 공간정보 오픈플랫폼 브이월드 서비스입니다. 국내에서 가장 정밀한 국가 고해상도 항공 사진과 수치 지도, 지적도, 실시간 교통량 등을 제공하며 국내 업무 지원에 가장 특화된 국가 국가표준 지도입니다.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>Text</td><tr><td>등록 도메인</td><td>Text</td><tr><td>Map Layer / Style</td></td><tr><td>범례 보기</td><td>Boolean</td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: address, place

## GIS Proxy & Search Capabilities

AoT provides built-in proxy and search support for common GIS services to handle CORS and provide unified search.

| Service | Description | Proxy Endpoint |
| :--- | :--- | :--- |
| RainViewer | Weather Radar Tiles & Metadata | `/api/geo/proxy/rainviewer/meta` |
| ISRIC SoilGrids | Soil property data lookups | `/api/geo/proxy/isric` |
| OpenWeatherMap | Current weather data | `/api/geo/proxy/openweather` |
| Open-Meteo | Weather forecast and historical data | `/api/geo/proxy/openmeteo` |

