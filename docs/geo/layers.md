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
| SGIS | `gis_sgis` | Singapore geospatial information | Not required |

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
