## Built-In Map Layers (System)

### AoT: GL: Aerial Photo Overlay

- Layer Type: image
- Default Role: Overlay
- Manufacturer: AoT
- Libraries: gis_image_overlay

Overlay a user-uploaded aerial or drone photo on the map. On upload, GPS and camera pose embedded in the photo (EXIF/XMP) are used to place it automatically; the four corners can then be dragged to fine-tune the fit against map features.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Image URL</td></td><tr><td>Corner coordinates (JSON)</td></td><tr><td>Opacity</td></td><tr><td>Extracted metadata (JSON)</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

## Built-In Map Layers (Providers)

### CARTO: GL: Carto Maps

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://carto.com/attributions">CARTO</a>
- Service URL: `https://{s}.basemaps.cartocdn.com/{style}/{z}/{x}/{y}{r}.png`
- Manufacturer: CARTO
- Libraries: gis_carto
- Manufacturer URL: [Link](https://carto.com/)

Data analysis-focused maps from CARTO DB. Offers restrained color schemes with Positron (light), Dark Matter (dark), and Voyager styles, designed to make data points and sensor information stand out.
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

A global land cover map based on European Space Agency (ESA) Sentinel-2 satellite data. Vegetation, urban areas, cropland, forest, and water bodies are classified and color-coded at 10m resolution, useful for environmental analysis.
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

Authoritative map service from global GIS leader Esri. Provides crisp and detailed World Imagery aerial satellite photos, optimized for accurate terrain and facility visualization.


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

High-precision public map service from Japan Geospatial Information Authority (GSI). Contains detailed terrain and place name information across Japan, with professional layers including standard maps, pale maps, and aerial photography.
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

Most widely used Google web map service. Supports Road, Satellite, Hybrid, and Terrain modes based on vast geographic information. Terrain mode excels at showing contours and hillshading. Also supports Geocoding API for address-to-coordinate conversion. API key available from Google Developer Console.
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

Global soil characteristic map from World Soil Information Service (ISRIC). Visualizes soil composition (clay, sand, etc.), pH levels, and carbon content for geological analysis as overlayer data.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Soil Property</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### Kakao: KO: Kakao Map

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://map.kakao.com/">Kakao</a>
- Service URL: `https://map1.daumcdn.net/map_2d/2103cov/L{z}/{y}/{x}.png`
- Manufacturer: Kakao
- Libraries: gis_kakao
- Manufacturer URL: [Link](https://map.kakao.com/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Map Type</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### Korea Meteorological Administration: KR: KMA Weather

- Layer Type: none
- Default Role: Overlay
- Attribution: &copy; <a href="https://apihub.kma.go.kr/">Korea Meteorological Administration</a>
- Manufacturer: Korea Meteorological Administration
- Libraries: gis_kma
- Manufacturer URL: [Link](https://apihub.kma.go.kr/)

KMA API Hub (apihub.kma.go.kr) 500m high-resolution observation data — displays location-based multi-channel weather information as a map legend. Uses the same API key as the KMA_weather_500 input.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key (apihub.kma.go.kr authKey)</td><td>Text</td><tr><td>Active Channels</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### MapTiler: GL: MapTiler Vector

- Layer Type: vector
- Default Role: Base
- Attribution: &copy; <a href="https://www.maptiler.com/">MapTiler</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>
- Service URL: `https://api.maptiler.com/maps/{style}/style.json?key={api_key}`
- Manufacturer: MapTiler
- Libraries: gis_maptiler_vector
- Manufacturer URL: [Link](https://www.maptiler.com/)

High-performance vector tile map service. Supports multiple styles (streets, light, dark, satellite, etc.) with excellent rendering performance and HD display.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>MapTiler API Key</td><td>Text</td><tr><td>Map Style</td></td><tr><td>Label Language</td><td>Text</td></tbody></table>

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

Stylish Mapbox vector and tile maps with excellent customization. Supports Streets, Satellite, Dark, and Light styles with superior rendering performance for smooth map interaction.
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

Microsoft global map service providing high-resolution aerial imagery (Aerial) and aerial with labels (Hybrid), with clean and precise road maps.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Bing Maps API Key</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: address, place

### NASA: NASA GIBS

- Layer Type: xyz
- Default Role: Base
- Attribution: NASA EOSDIS GIBS
- Service URL: `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/{tilematrixset}/{z}/{y}/{x}.{ext}`
- Time Enabled: Yes
- Manufacturer: NASA
- Libraries: gis_nasa_gibs
- Manufacturer URL: [Link](https://earthdata.nasa.gov/eosdis/science-system-description/eosdis-components/gibs)

Real-time Earth observation maps from NASA GIBS satellite system. Includes satellite imagery (Blue Marble) plus environmental data like temperature, clouds, and fires, selectable by date for time-series analysis.
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

Free map data created collaboratively by users worldwide in Wikipedia-style. Available at no cost with road and building information continuously updated by an active community. Standard web map with global coverage.


- GIS Search: Supported (Address/Place)
  - Capabilities: address, place

### OpenTopoMap: GL: OpenTopoMap

- Layer Type: xyz
- Default Role: Base
- Attribution: Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)
- Manufacturer: OpenTopoMap
- Libraries: gis_opentopomap
- Manufacturer URL: [Link](https://opentopomap.org)

Terrain map service based on OpenStreetMap data with emphasized contours and hillshading. Clear differentiation for mountain terrain and slope analysis, high readability, suitable for hiking and outdoor activity visualization.


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

Weather-focused service displaying global weather information as map overlays. Provides real-time clouds, precipitation, temperature, wind speed, pressure, and radar data for intuitive weather situational awareness.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>Text</td><tr><td>Active Layers</td></td></tbody></table>

- GIS Search: Supported (Address/Place)
  - Capabilities: 

### RainViewer: GL: RainViewer (Radar)

- Layer Type: xyz
- Default Role: Overlay
- Attribution: Map Data &copy; <a href="https://www.rainviewer.com/api.html">RainViewer</a>
- Service URL: `https://tilecache.rainviewer.com/v2/radar/{ts}/256/{z}/{x}/{y}/{color_scheme}/{smoothing}_1.png`
- Time Enabled: Yes
- Manufacturer: RainViewer
- Libraries: gis_rainviewer
- Manufacturer URL: [Link](https://www.rainviewer.com/)

RainViewer radar precipitation data overlay. Supports real-time rainfall tracking and animation. Compatible with both vector and raster modes.
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

High-quality design-focused map server from Stadia Maps. Provides clean layouts with eye-comfortable colors and high-quality fonts using Alidade Smooth, Dark, OSMBright styles, ideal for professional dashboard creation.
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

Statistical geographic information service from Statistics Korea (SGIS). Optimal domestic service for spatial analysis and visualization of statistical data including population, households, and businesses by administrative district.
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

Unique themed maps tailored for specific purposes using OpenStreetMap data. Experience visually striking styles including cycling routes (Cycle), public transport (Transport), night maps, and rugged landscapes.
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

Vworld spatial information open platform from Korea Ministry of Land, Infrastructure and Transport. Provides the most precise national high-resolution aerial photography, digital maps, cadastral maps, and real-time traffic data. The most specialized national standard map for domestic business support.
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>Text</td><tr><td>Registered Domain</td><td>Text</td><tr><td>Map Layer / Style</td></td><tr><td>Show Legend</td><td>Boolean</td></tbody></table>

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

