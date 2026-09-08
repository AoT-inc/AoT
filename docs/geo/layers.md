# GIS Layer Management

The `/geo/layer` page is where you register and manage external map data sources. Registered layers can be used as base layers or overlays in the design tool and dashboard map widget.

---

## Supported Providers

### Domestic (Korea)

| Provider | Type code | Features | API key required |
|----------|-----------|----------|-----------------|
| VWorld | `gis_vworld` | Official government map, cadastral, aerial imagery, PNU parcel search | Required |
| Kakao Maps | `gis_kakao` | Highest-precision road map in Korea | Required |
| Naver Maps | `gis_naver` | Korean map with real-time traffic | Required |

### International General

| Provider | Type code | Features | API key required |
|----------|-----------|----------|-----------------|
| OpenStreetMap | `gis_osm` | Free open-source map | Not required |
| Google Maps | `gis_google` | Satellite/road/hybrid | Required |
| ESRI | `gis_esri` | Satellite imagery, topographic, road maps | Not required (some layers) |
| Mapbox | `gis_mapbox` | Vector tiles, custom styles | Required |
| MapTiler | `gis_maptiler_vector` | Vector tiles, various styles | Required |
| Bing | `gis_bing` | Satellite imagery, bird's-eye view | Required |
| Carto | `gis_carto` | Clean vector design maps | Not required |
| Stadia Maps | `gis_stadia` | High-quality design maps | Optional |
| Thunderforest | `gis_thunderforest` | Cycling/hiking/transport specialized | Required |

### Satellite / Aerial

| Provider | Type code | Features | API key required |
|----------|-----------|----------|-----------------|
| NASA GIBS | `gis_nasa_gibs` | Scientific satellite imagery, WMS | Not required |
| ESA | `gis_esa` | European Space Agency satellite | Not required |
| Sentinel Hub | `gis_sentinelhub` | Sentinel-2 at 10 m: NDVI, moisture and water indices | Required (OAuth client) |

### Weather Overlays

| Provider | Type code | Features | API key required |
|----------|-----------|----------|-----------------|
| RainViewer | `gis_rainviewer` | Real-time and historical rainfall radar | Not required |
| OpenWeather | `gis_openweather` | Temperature, precipitation, cloud, wind layers | Required |
| Open-Meteo | (built-in proxy) | Weather forecast data | Not required |

### Specialized Data

| Provider | Type code | Features | API key required |
|----------|-----------|----------|-----------------|
| OpenTopoMap | `gis_opentopomap` | Contour and terrain map | Not required |
| ISRIC | `gis_isric` | Global soil data (SoilGrids) | Not required |
| GSI | `gis_gsi` | Japan Geospatial Information Authority | Not required |
| SGIS | `gis_sgis` | Statistics Korea geospatial statistics | Required |
| Agromonitoring | `gis_agromonitoring` | Per-field NDVI statistics, soil moisture and soil temperature | Required |

---

## How to Register a Layer

1. Navigate to `/geo/layer`.
2. Select the desired provider from the **Input Type** dropdown in the top right.
3. Click **Add**.
4. Click the **Settings (gear) icon** on the new item.
5. Enter the required options (API key, layer type, etc.).
6. Click **Save**, then click **Activate** to enable it.

---

## Provider-Specific Settings

### VWorld

Korea's National Spatial Data Infrastructure platform. You must obtain an API key from the VWorld developer site (https://map.vworld.kr).

| Option | Description |
|--------|-------------|
| API Key | VWorld API key |
| Layer Type | `Base` (standard map) / `Satellite` (aerial) / `Hybrid` / `Gray` |

VWorld is also used for **parcel import**. The API key must be registered for address search to work.

### Google Maps

Obtain a Maps JavaScript API key from the Google Cloud Console.

| Option | Description |
|--------|-------------|
| API Key | Google Maps API key |
| Map Type | `roadmap` / `satellite` / `hybrid` / `terrain` |

### Mapbox / MapTiler

Vector tile providers that integrate natively with MapLibre GL for smooth rendering.

| Option | Description |
|--------|-------------|
| API Key / Token | Obtain from each service's dashboard |
| Style | Select a style URL or preset |

### RainViewer

Free to use with no API key. Supports real-time radar and up to 2 hours of historical data.

The AoT server relays requests via a CORS proxy (`/api/geo/proxy/rainviewer/*`), so the client does not directly access external services.

### ISRIC (SoilGrids)

Provides global soil data (organic matter, pH, nitrogen content) via WMS. Useful for soil analysis in agricultural smart farm applications.

### Sentinel Hub (Sentinel-2)

Sentinel-2 imagery at 10 m resolution — the 6.25 ha that MODIS NDVI covers with a single 250 m pixel is 625 pixels here, so growth differences inside one field become visible.

Register a free account on the [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/), create an OAuth client in the dashboard, and enter its Client ID and Secret. Because Sentinel Hub authenticates with OAuth2 client credentials, the AoT server fetches every tile on your behalf (`/api/geo/proxy/sentinelhub/<unique_id>`) — the secret never reaches the browser.

| Option | Description |
|--------|-------------|
| Layer | NDVI, True Color, NDMI (moisture), NDWI (water), False Color |
| Collection | L2A (atmospherically corrected) or L1C |
| Search Window | Clouds leave holes in any single date, so the most recent usable scene inside this window is drawn |
| Max Cloud Coverage / Scene Priority | Which scene to pick inside that window |

The free tier allows 30,000 processing units per month. One map screen costs roughly 4, tiles are cached for a day, and zoom levels below 9 are not requested at all — a 10 m dataset viewed at continental scale would spend the budget without showing anything.

### Agromonitoring (Field NDVI / Soil)

Reports NDVI statistics and **soil moisture and soil temperature as numbers** for a field boundary you registered — the only layer here that does. The SMAP overlay is a 9 km picture, and the NASA GIBS legend borrows its soil-moisture figure from an Open-Meteo model value.

Draw the field in the Agromonitoring dashboard (1–3000 ha) and either paste its polygon ID or leave the field empty, in which case the polygon containing the clicked point is matched automatically. The API key is the same one used for OpenWeatherMap.

Values are read through the server (`/api/geo/proxy/agromonitoring/<unique_id>`) and cached for 30 minutes, because the free tier's call limits are not published.

---

## WMS Layers

Any server compliant with WMS (Web Map Service) 1.3.0 can be integrated.

| Option | Description |
|--------|-------------|
| URL | WMS server GetCapabilities URL |
| Layers | Layer names to display (comma-separated) |
| Format | `image/png` or `image/jpeg` |
| CRS | Coordinate system (usually `EPSG:3857`) |

The AoT server proxies WMS tile requests (`/api/geo/proxy/wms/<unique_id>`) to solve CORS issues.

---

## Layer Order and Visibility

Drag layers in the GridStack layout to reorder them. Order is saved automatically.

Use the **eye icon** on each layer to temporarily show/hide it. **Activate/Deactivate** permanently enables or disables a layer.

---

## Layer Preview

Click the **Preview** button on a layer item to see a popup preview of how the layer looks on the map.

- For MapTiler and RainViewer, API key validity is also verified.
- If no preview appears, check the API key or network connection.

---

## Related Pages

- [Global GIS Settings](settings.md) — Default layer selection, theme colors
- [Design Tool](design-tool.md) — Using the layer control panel
- [Parcel Import](parcel-import.md) — Using VWorld
