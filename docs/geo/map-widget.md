# AoT_map Widget

The `AoT_map` widget displays an interactive map on the dashboard. It supports device markers, real-time status polling, and output control switches.

---

## Adding the Widget

1. On the dashboard, select **Add Widget → AoT_map**.
2. In the settings, choose the map to display.
3. Click **Save**.

---

## Key Features

### Device Markers

AoT devices placed in **Device** mode in `/geo/design` appear as markers on the map.

- **Marker color**: Automatically changes based on device active/inactive/error state.
- **Marker clustering**: When zoomed out, nearby markers are grouped together.
- **Device icons**: Icons vary by device type (temperature sensor/relay/pump, etc.).

### Popup Controls

Clicking a marker opens a popup showing:

- Device name
- Latest measurement value (for Input devices)
- On/Off toggle switch (for Output devices)
- Last updated timestamp

Toggling the switch immediately controls the device via `/api/output/<id>/state`.

### Real-time Polling

The widget automatically refreshes device state at a configured interval (default: 10 seconds).

- Marker colors update in real time.
- Values refresh even while a popup is open.
- Stopwatch: Displays how long an output device has been on.

---

## Widget Settings

| Option | Description | Default |
|--------|-------------|---------|
| Map | Select the GeoMap to display | — |
| Refresh Rate | Device state refresh interval (seconds) | 10 |
| Show Legend | Show/hide legend | On |
| Lock Map | Lock map panning and zooming | Off |
| Hide Controls | Hide zoom/search buttons | Off |
| Geo Mode | `vector` (MapLibre) or `raster` (Leaflet) | vector |
| AI Advice | Show AI advice summary | Off |

### Choosing Geo Mode

| Mode | Description | Recommended for |
|------|-------------|----------------|
| `vector` | MapLibre GL, supports 3D and smooth zoom | Default — most cases |
| `raster` | Leaflet-based, legacy compatible | Older browsers, WMS-only setups |

---

## Map Control Buttons

| Button | Function |
|--------|----------|
| +/- | Zoom in/out |
| Search | Address/coordinate search (raster mode only) |
| Location | Move to GPS position |
| Lock | Toggle map pan lock |
| Hide | Toggle control buttons |
| RainViewer | Toggle rainfall radar overlay |

---

## Legend

A legend is displayed in the bottom right of the map.

- Shows registered GIS layer colors.
- Explains Input/Output device icons.
- Clicking the legend toggles visibility of that layer/device type.

---

## Feature Overlay Display

Site, Zone, and Facility polygons drawn in the design tool are displayed as semi-transparent overlays on the map.

- **Site**: Site boundary (using configured theme color)
- **Zone**: Zone color
- **Facility**: Building footprint
- **Connection**: Pipe/wiring routes

---

## 3D Facility Popup

Clicking a Facility marker or polygon shows a brief 3D preview and environment data summary in a popup. For full facility view, use the [AoT_facility widget](facility-widget.md).

---

## Multiple Maps on One Dashboard

You can add multiple AoT_map widgets to the same dashboard, each displaying a different map — for example, an overall site overview map alongside a zoomed-in view of a specific block.

---

## Related Pages

- [Design Tool](design-tool.md) — Placing device locations
- [Facility Widget](facility-widget.md) — 3D facility widget
- [GIS Layers](layers.md) — Layer registration
