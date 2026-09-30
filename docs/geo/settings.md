# Global GIS Settings

The `/geo/setting` page configures system-wide GIS defaults. Settings are stored as a singleton record in the `geo_setting` table.

---

## Default Start Location { #default-start-location }

The default location shown when the map widget and design tool first open.

| Field | Default | Description |
|-------|---------|-------------|
| Latitude | 37.5665 | Center of Seoul |
| Longitude | 126.9780 | Center of Seoul |
| Zoom Level | 12 | Initial zoom (smaller = wider area, larger = closer in) |

Move the map to the location and zoom you want, then click **Get Location** on the **Current View** row to fill the three fields from the current map view.

---

## Design Theme Colors { #design-theme-colors }

Per-layer colors used in the design tool and map widget.

| Layer | Meaning |
|-------|---------|
| Site | Site boundary |
| Zone | Zone boundary |
| Facility | Facility building |
| Equipment | Equipment |
| Device | AoT device marker |
| Panel Background | Property panel background |

Each row has a color picker. A color you have never saved shows the colour currently in use (the global default) and stays unset — it is only saved once you change it. One **Panel Opacity** slider (0–100%, in steps of 5) applies to the property panel background.

---

## Map Behavior

### Zoom Settings { #zoom-settings }

| Field | Default | Description |
|-------|---------|-------------|
| Max Zoom | 25 | Maximum map zoom level (accepts 1–30) |
| Equipment Hide Zoom | 15 | Equipment items are hidden below this zoom level (accepts 1–25) |

**Equipment Hide Zoom** prevents large numbers of equipment items from cluttering the map when zoomed out. When zoom drops below `15`, pipes, connection points, sprinkler coverage areas and 3D facility models are automatically hidden. AoT device markers are not affected — they stay visible at every zoom level.

### Zoom Method { #zoom-method }

| Field | Default | Description |
|-------|---------|-------------|
| Digital Zoom | On | Continue CSS-scale zoom beyond tile resolution |
| Smooth Zoom | On | Smooth interpolation during pinch zoom |

---

## Performance & Rendering { #performance-rendering }

| Field | Default | Description |
|-------|---------|-------------|
| Tile Fade Animation | On | Fade-in animation when tiles load |
| Serve MapLibre Locally | On | Serve the MapLibre GL library from local files instead of the CDN. Turn it off to load the library from the CDN |
| Prefer Canvas Rendering | Off | Prefer Canvas renderer over SVG (Leaflet mode only) |

### Polygon Display Limits { #polygon-display-limits }

Upper counts kept with the map settings. They are stored and can be edited here, but the current map drawing does not apply them yet.

| Field | Default |
|-------|---------|
| Max Site Polygons | 1000 |
| Max Zone Polygons | 1000 |
| Max Device Polygons | 1000 |

---

## Unit Settings { #unit-settings }

Select the length unit for facility engineering calculations and dimension inputs.

| Code | Display |
|------|---------|
| `m` | Meters (default) |
| `cm` | Centimeters |
| `mm` | Millimeters |
| `ft` | Feet |
| `in` | Inches |

---

## API { #api }

```http
GET /api/geo/settings
```

Returns the current global settings as JSON. It requires the Edit Settings permission; without it the request is refused.

The response is `{"ok": true, "saved_state": { ... }, "geo_layers": [...], "search_inputs": [...], "search_provider": "..."}`. `saved_state` carries the stored settings — note that the default start zoom comes back as `zoom` — along with the saved map provider keys.

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

Every key is optional — an omitted key keeps its stored value, and keys that are not on the accepted list are silently ignored. Form-encoded bodies are accepted as well as JSON. Theme values are sent as flat `theme_*` keys, not as a nested object; the design drawer's visibility toggles are saved through the same `theme_*` family. An empty `search_provider` means "follow map settings". A successful save answers `{"ok": true, "message": "Settings Saved"}`, and saving also requires the Edit Settings permission.

The length unit is not part of this endpoint. It has its own:

```http
GET /api/geo/settings/length_unit
PUT /api/geo/settings/length_unit
Content-Type: application/json

{ "length_unit": "m" }
```

`GET` returns the current unit together with the list of supported units; `PUT` refuses any value outside that list.

---

## Related Pages

- [GIS Layers](layers.md) — Provider API key registration
- [Design Tool](design-tool.md) — Verifying theme color application
