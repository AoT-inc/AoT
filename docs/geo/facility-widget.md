# AoT_facility Widget

The `AoT_facility` widget displays a facility's 3D view together with indoor/outdoor environment data on the dashboard.

---

## Adding the Widget

1. On the dashboard, select **Add Widget → AoT_facility**.
2. In the settings, select the facility to display (registered in `/geo/facility`).
3. Click **Save**.

---

## Screen Layout

### A. 3D View

A building model rendered with Three.js.

- **Left mouse drag**: Rotate
- **Right mouse drag**: Pan
- **Scroll**: Zoom
- **Preset badge**: Shows the currently applied environment preset.
- **Structure badge**: Displays `Single` or `Multi-span` structure type.

The 3D model is automatically generated from the envelope parameters (bay dimensions, covering material, etc.) configured in `/geo/facility`.

### B. Environment Data Panel

Displays real-time values from bound sensors in 6 cells.

| Cell | Data | Unit |
|------|------|------|
| Indoor temperature | Indoor temperature sensor | °C |
| Indoor humidity | Indoor humidity sensor | %RH |
| Indoor CO₂ | CO₂ sensor | ppm |
| Outdoor temperature | Weather data or external sensor | °C |
| Wind speed/direction | Weather data or anemometer | m/s |
| Solar radiation | Weather data or PAR sensor | W/m² |

Cells without data display `—`.

### C. AI Advice Panel (Optional)

Displayed when **Show AI Advice** is enabled in settings.

- Urgency colors: **Red** (immediate action) / **Orange** (caution) / **Green** (normal)
- AI-detected anomalies or optimization suggestions.

---

## Widget Settings

| Option | Description | Default |
|--------|-------------|---------|
| Facility | Select facility to display | — |
| Refresh Period | Environment data refresh interval (seconds) | 30 |
| Show AI Advice | Show AI advice panel | Off |

---

## Data Refresh

The widget calls `/api/geo/facility/<uuid>/integration` at the configured interval to refresh environment data.

- Facilities without sensor bindings will display only `—`.
- External weather data (Open-Meteo) is automatically retrieved based on the facility's GPS coordinates.

---

## No Facility Registered

If no facility has been registered in `/geo/facility`, the widget displays "No facilities registered."

How to register:
1. `/geo/design` → Facility mode → Draw building polygon and save
2. `/geo/facility` → Select the facility → Configure envelope → Save

---

## Related Pages

- [Facility Management](facility.md) — 3D model configuration, sensor binding
- [Map Widget](map-widget.md) — Map-based monitoring
