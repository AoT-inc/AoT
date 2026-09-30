# GIS Layer Management

The `/geo/layer` page is where you register and manage external map data sources. Registered layers can be used as base layers or overlays in the design tool and dashboard map widget.

---

## Supported Providers

### Domestic (Korea) { #domestic-korea }

| Provider | Type code | Features | API key required |
|----------|-----------|----------|-----------------|
| VWorld | `gis_vworld` | Official government map, cadastral, aerial imagery, parcel lookup by address | Required |
| Kakao Maps | `gis_kakao` | Base map, satellite and hybrid tiles for Korea | Not required |
| Naver Maps | `gis_naver` | Base map, satellite and terrain tiles for Korea | Not required |

### International General { #international-general }

| Provider | Type code | Features | API key required |
|----------|-----------|----------|-----------------|
| OpenStreetMap | `gis_osm` | Free open-source map | Not required |
| Google Maps | `gis_google` | Satellite/road/hybrid | Required |
| ESRI | `gis_esri` | World Imagery satellite imagery | Not required |
| Mapbox | `gis_mapbox` | Map tiles in eight preset styles | Required |
| MapTiler | `gis_maptiler_vector` | Vector tiles, various styles | Required |
| Bing | `gis_bing` | Aerial, aerial with labels, road map | Optional |
| Carto | `gis_carto` | Restrained design maps (Positron, Dark Matter, Voyager) | Not required |
| Stadia Maps | `gis_stadia` | High-quality design maps | Required |
| Thunderforest | `gis_thunderforest` | Cycling/hiking/transport specialized | Required |

### Satellite / Aerial { #satellite-aerial }

| Provider | Type code | Features | API key required |
|----------|-----------|----------|-----------------|
| NASA GIBS | `gis_nasa_gibs` | Satellite imagery and environmental layers, selectable by date | Not required |
| Soil Moisture (NASA SMAP) | `gis_esa` | Surface soil moisture (0–5 cm) overlay at about 9 km, selectable by date | Not required |
| Sentinel Hub | `gis_sentinelhub` | Sentinel-2 at 10 m: NDVI, moisture and water indices | Required (OAuth client) |

### Weather Overlays { #weather-overlays }

| Provider | Type code | Features | API key required |
|----------|-----------|----------|-----------------|
| RainViewer | `gis_rainviewer` | Real-time and historical rainfall radar | Not required (premium only) |
| OpenWeather | `gis_openweather` | Clouds, precipitation, pressure, wind and temperature layers | Required |
| KMA Weather | `gis_kma` | Korea 500 m observation values, shown as a map legend | Required |
| Open-Meteo | (built-in proxy) | Weather forecast data | Not required |

### Specialized Data { #specialized-data }

| Provider | Type code | Features | API key required |
|----------|-----------|----------|-----------------|
| OpenTopoMap | `gis_opentopomap` | Contour and terrain map | Not required |
| ISRIC | `gis_isric` | Global soil data (SoilGrids) | Not required |
| GSI | `gis_gsi` | Japan Geospatial Information Authority | Not required |
| SGIS | `gis_sgis` | Statistics Korea geospatial statistics | Required |
| Agromonitoring | `gis_agromonitoring` | Per-field NDVI statistics, soil moisture and soil temperature | Required |

---

## How to Register a Layer { #how-to-register-a-layer }

1. Navigate to `/geo/layer`.
2. Select the desired provider from the **Select GIS Service** dropdown at the top of the page.
3. Click **Add**. The layer is created deactivated.
4. Click the **Settings (gear) icon** on the new item.
5. Enter the required options (API key, layer type, etc.).
6. Click **Save**, then click **Activate** to enable it.

---

## Provider-Specific Settings

### VWorld { #vworld }

Korea's National Spatial Data Infrastructure platform. You must obtain an API key from the VWorld developer site (https://map.vworld.kr).

| Option | Description |
|--------|-------------|
| API Key | VWorld API key |
| Registered Domain | Domain the key is registered under; left empty, the current access URL is used |
| Map Layer / Style | Backgrounds: `Base Map` / `Satellite` / `Hybrid` / `Gray Map` / `Dark Map`. Overlays: cadastral map, agricultural promotion area, ecological naturalness, development restriction zone, individual official land price |
| Show Legend | Whether to show the layer's legend on the map |

VWorld is also used for **parcel import**. The API key must be registered for address search to work; the key is read from the registered VWorld layer even when that layer is not activated.

### Google Maps { #google-maps }

Obtain a Maps JavaScript API key from the Google Cloud Console.

| Option | Description |
|--------|-------------|
| Google Maps API Key | Google Maps API key |
| Map Style | `Roadmap` / `Satellite` / `Hybrid` / `Terrain`, one at a time |

### Mapbox / MapTiler { #mapbox-maptiler }

MapTiler serves vector tiles, rendered natively by MapLibre GL; Mapbox is served as map tiles rendered from the style you pick.

| Option | Description |
|--------|-------------|
| API Key / Token | Obtain from each service's dashboard |
| Map Style | Pick one preset style (Mapbox: 8, MapTiler: 6) |
| Label Language | MapTiler only — language for map labels (e.g. `ko`, `en`, `auto`) |

### RainViewer { #rainviewer }

Works without an API key — the key field is only for RainViewer's premium features. Supports real-time radar and up to 2 hours of historical data (12 frames, 10 minutes apart). Radar detail stops at about zoom level 7.

Radar tiles are fetched from RainViewer by the browser; only the list of available frames goes through the AoT server (`/api/geo/proxy/rainviewer/*`). If that list cannot be obtained, the layer simply shows no frames instead of reporting an error.

### ISRIC (SoilGrids) { #isric-soilgrids }

Provides global soil data via WMS: pH (water), clay, sand and silt content, soil organic carbon and bulk density, each for the 0–5 cm layer. Detail stops at the 250 m source grid, so zooming in beyond that only enlarges the same picture. Useful for soil analysis in agricultural smart farm applications.

### Sentinel Hub (Sentinel-2) { #sentinel-hub-sentinel-2 }

Sentinel-2 imagery at 10 m resolution — the 6.25 ha that MODIS NDVI covers with a single 250 m pixel is 625 pixels here, so growth differences inside one field become visible.

Register a free account on the [Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/), create an OAuth client in the dashboard, and enter its Client ID and Secret. Because Sentinel Hub authenticates with OAuth2 client credentials, the AoT server fetches every tile on your behalf (`/api/geo/proxy/sentinelhub/<unique_id>`) — the secret never reaches the browser.

| Option | Description |
|--------|-------------|
| Layer | NDVI, True Color, NDMI (moisture), NDWI (water), False Color |
| Collection | L2A (atmospherically corrected) or L1C |
| Search Window | Clouds leave holes in any single date, so the most recent usable scene inside this window is drawn |
| Max Cloud Coverage / Scene Priority | Which scene to pick inside that window |

The free tier allows 30,000 processing units per month. One map screen costs roughly 4, tiles are cached for a day, and zoom levels below 9 are not requested at all — a 10 m dataset viewed at continental scale would spend the budget without showing anything.

### Agromonitoring (Field NDVI / Soil) { #agromonitoring-field-ndvi-soil }

Reports NDVI statistics and **soil moisture and soil temperature as numbers** for a field boundary you registered — the only layer here that does. The SMAP overlay is a 9 km picture, and the NASA GIBS legend borrows its soil-moisture figure from an Open-Meteo model value.

Draw the field in the Agromonitoring dashboard (1–3000 ha) and either paste its polygon ID or leave the field empty, in which case the polygon containing the clicked point is matched automatically; if the point falls outside every registered polygon, the one with the nearest centre is used instead. The API key is the same one used for OpenWeatherMap.

**Active Channels** decides which values are shown: NDVI (mean), soil moisture, surface soil temperature, soil temperature at 10 cm. **NDVI Search Window** (14 / 30 / 60 / 90 days, 30 by default) sets how far back the most recent pass is looked for — clouds can leave weeks without a usable scene.

Values are read through the server (`/api/geo/proxy/agromonitoring/<unique_id>`) and cached for 30 minutes, because the free tier's call limits are not published.

---

## WMS Layers { #wms-layers }

Some providers deliver their overlays over WMS (Web Map Service) instead of ready-made tiles — the VWorld data overlays (cadastral map, agricultural promotion area, ecological naturalness, development restriction zone, individual official land price) and ISRIC SoilGrids. There is no separate WMS entry to fill in: register the provider and pick the channel you want in its settings.

| Request detail | Value |
|--------|-------------|
| Request | `GetMap`, one 256×256 image per tile |
| Version | `1.3.0`, unless the provider declares another |
| Coordinate system | Always `EPSG:3857` |
| Image format | `image/png` with transparency, unless the provider declares another |

The AoT server fetches these images on your behalf (`/api/geo/proxy/wms/<unique_id>`), because the services do not let the browser read them directly. Two effects are visible on the map:

- If the upstream server errors out or does not answer within 15 seconds, that overlay stays blank while the rest of the map keeps working, and nothing is reported as an error. Failures are not kept, so the overlay returns as soon as the service does.
- An image once fetched is reused for a week on the server and a day in the browser, so a change made upstream can take that long to appear. Changing the layer's own settings takes effect at once.

---

## Layer Order and Visibility { #layer-order-and-visibility }

Drag a layer by the grip handle on its left to reorder it; the new order is saved as soon as you drop it. On a narrow screen the list switches to a single column, and dragging there does not change the saved order.

**Activate** / **Deactivate** on each row decides whether the layer is offered on the map at all. Which channels of a layer are shown is set inside its settings window, with the layer button on the preview map — those toggles are saved together with the layer.

---

## Layer Preview { #layer-preview }

Open a layer's settings window (gear icon) and a preview map appears at the top, drawn with the options currently entered. It reloads whenever you change an option, so a key or a style can be checked before saving.

- The layer button at the top right of the preview switches the base map and toggles overlay channels; those toggles are saved with the layer.
- If no preview appears, check the API key or network connection.

---

## Related Pages

- [Global GIS Settings](settings.md) — Default layer selection, theme colors
- [Design Tool](design-tool.md) — Using the layer control panel
- [Parcel Import](parcel-import.md) — Using VWorld
