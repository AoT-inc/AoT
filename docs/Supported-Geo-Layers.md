## Built-In Map Layers (Providers)

### Carto: Carto Maps

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://carto.com/attributions">CARTO</a>
- Service URL: `https://{s}.basemaps.cartocdn.com/{style}/{z}/{x}/{y}{r}.png`
- Manufacturer: Carto
- Libraries: gis_carto
- Manufacturer URL: [Link](https://carto.com/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Active Map Styles</td></td></tbody></table>

### Esri: Esri World Imagery

- Layer Type: xyz
- Attribution: &copy; <a href="https://www.esri.com/">Esri</a>
- Service URL: `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}`
- Manufacturer: Esri
- Libraries: gis_esri
- Manufacturer URL: [Link](https://www.esri.com/)


### ISRIC: SoilGrids (Global Soil Info)

- Layer Type: wms
- Default Role: Overlay
- Attribution: ISRIC - World Soil Information
- Service URL: `https://maps.isric.org/mapserv`
- Manufacturer: ISRIC
- Libraries: gis_isric
- Manufacturer URL: [Link](https://soilgrids.org/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Soil Property</td></td></tbody></table>

### NASA: NASA GIBS

- Layer Type: xyz
- Default Role: Base
- Attribution: NASA EOSDIS GIBS
- Service URL: `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/{time}/{tilematrixset}/{z}/{y}/{x}.{ext}`
- Time Enabled: Yes
- Manufacturer: NASA
- Libraries: gis_nasa_gibs
- Manufacturer URL: [Link](https://earthdata.nasa.gov/eosdis/science-system-description/eosdis-components/gibs)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Satellite Layer</td></td><tr><td>Target Date (YYYY-MM-DD)</td><td>Text</td></tbody></table>

### NASA: Soil Moisture (NASA SMAP)

- Layer Type: xyz
- Default Role: Overlay
- Attribution: NASA SMAP L4 Soil Moisture
- Service URL: `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/SMAP_L4_Analyzed_Surface_Soil_Moisture/default/{time}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png`
- Time Enabled: Yes
- Manufacturer: NASA
- Libraries: gis_esa
- Manufacturer URL: [Link](https://smap.jpl.nasa.gov/)


### OpenStreetMap: OpenStreetMap

- Layer Type: xyz
- Attribution: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>
- Service URL: `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png`
- Manufacturer: OpenStreetMap
- Libraries: gis_osm
- Manufacturer URL: [Link](https://www.openstreetmap.org/)


### OpenTopoMap: OpenTopoMap

- Layer Type: xyz
- Default Role: Base
- Attribution: Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)
- Manufacturer: OpenTopoMap
- Libraries: gis_opentopomap
- Manufacturer URL: [Link](https://opentopomap.org)


### OpenWeatherMap: OpenWeatherMap

- Layer Type: xyz
- Default Role: Overlay
- Attribution: &copy; <a href="http://openweathermap.org">OpenWeatherMap</a>
- Service URL: `https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png?appid={api_key}`
- Manufacturer: OpenWeatherMap
- Libraries: gis_openweather
- Manufacturer URL: [Link](https://openweathermap.org/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>API Key</td><td>Text</td><tr><td>Active Layers</td></td></tbody></table>

### RainViewer: RainViewer (Radar)

- Layer Type: xyz
- Default Role: Overlay
- Attribution: Map Data &copy; <a href="https://www.rainviewer.com/api.html">RainViewer</a>
- Service URL: `https://tile.rainviewer.com{ts}/{z}/{x}/{y}/{color_scheme}/{smoothing}_1.png`
- Time Enabled: Yes
- Manufacturer: RainViewer
- Libraries: gis_rainviewer
- Manufacturer URL: [Link](https://www.rainviewer.com/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Color Scheme</td><td>Select</td><tr><td>Smoothing</td><td>Boolean</td></tbody></table>

### Vworld: Vworld (Korea)

- Layer Type: xyz
- Default Role: Base
- Attribution: &copy; <a href="https://www.vworld.kr/">Vworld</a>
- Service URL: `https://api.vworld.kr/req/wmts/1.0.0/{api_key}/{layer}/{z}/{y}/{x}.png`
- Manufacturer: Vworld
- Libraries: gis_vworld
- Manufacturer URL: [Link](https://www.vworld.kr/)
<table><thead><tr class="header"><th>Option</th><th>Type</th><th>Description</th></tr></thead><tbody><tr><td>Vworld API Key</td><td>Text</td><tr><td>Map Style</td></td></tbody></table>

