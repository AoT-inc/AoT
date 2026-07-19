# Global GIS Settings

The `/geo/setting` page configures system-wide GIS defaults. Settings are stored as a singleton record in the `geo_setting` table.

---

## Default Start Location

The default location shown when the map widget and design tool first open.

| Field | Default | Description |
|-------|---------|-------------|
| Latitude | 37.5665 | Center of Seoul |
| Longitude | 126.9780 | Center of Seoul |
| Zoom level | 13 | Initial zoom (1=world, 22=building) |

Click **Set to Current Position** after navigating to your desired location and zoom level to auto-fill the fields.

---

## Design Theme Colors

Per-layer colors used in the design tool and map widget.

| Layer | Meaning |
|-------|---------|
| Site | Site boundary |
| Zone | Zone boundary |
| Facility | Facility building |
| Equipment | Equipment |
| Device | AoT device marker |
| Panel Background | Property panel background |

Each item has a color picker and an opacity slider (0–100%).

---

## Map Behavior

### Zoom Settings

| Field | Default | Description |
|-------|---------|-------------|
| Max Zoom | 22 | Maximum map zoom level |
| Equipment Cull Zoom | 15 | Equipment/Device markers hidden below this zoom level |

**Equipment Cull Zoom** prevents large numbers of device markers from cluttering the map when zoomed out. When zoom drops below `15`, Equipment/Device markers are automatically hidden.

### Zoom Method

| Field | Default | Description |
|-------|---------|-------------|
| Digital Zoom | Off | Continue CSS-scale zoom beyond tile resolution |
| Smooth Zoom | On | Smooth interpolation during pinch zoom |

---

## Performance & Rendering

| Field | Default | Description |
|-------|---------|-------------|
| Tile Fade Animation | On | Fade-in animation when tiles load |
| Prefer Canvas | Off | Prefer Canvas renderer over SVG (Leaflet mode only) |

### Polygon Display Limits

Limits the number of polygons rendered at once in the dashboard map widget. Excess polygons are clustered.

| Field | Default |
|-------|---------|
| Max Site polygons | 500 |
| Max Zone polygons | 1000 |
| Max Device markers | 2000 |

---

## Unit Settings

Select the length unit for facility engineering calculations and dimension inputs.

| Code | Display |
|------|---------|
| `m` | Meters (default) |
| `cm` | Centimeters |
| `mm` | Millimeters |
| `ft` | Feet |
| `in` | Inches |

---

## API

```http
GET /api/geo/settings
```

Returns the current global settings as JSON.

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

## Related Pages

- [GIS Layers](layers.md) — Provider API key registration
- [Design Tool](design-tool.md) — Verifying theme color application
