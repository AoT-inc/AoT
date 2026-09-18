# AoT_facility Widget

The `AoT_facility` widget shows a facility's 3D view, live environment readings, and — when an Integrated Environment Control (IEC) function is linked — setpoint editing and actuator control, on the dashboard.

---

## Adding the Widget

1. On the dashboard, select **Add Widget → AoT Facility**.
2. In the settings, select the **IEC Function** — an `env_coordinator` function, not the facility itself. The facility is auto-discovered from that function's configuration.
3. Leave **IEC Function** blank to auto-select the first activated `env_coordinator` function; if none exists, the widget falls back to the most recently updated facility (view-only — no linked function means no status strip, setpoints, or control).
4. Click **Save**.

---

## Screen Layout

### 0. Status Strip

Shown when **Show Status Strip** is on. A badge polled every 5 seconds from `/api/aot/facility/<uuid>/status`:

| Level | Meaning |
|-------|---------|
| `IDLE` | No linked IEC function, or nothing to report |
| `ACTIVE` | The linked function ran its last control cycle recently |
| `WARN` | The linked function is not activated, or hasn't reported a cycle recently (stale) |
| `EMERGENCY` | Sensor health degraded — fewer than half of the facility's sensors are resolving |

Next to the badge: the reasons behind the current level, and a timestamp with the active/total actuator count.

### A. 3D View

A building model rendered with Three.js, automatically generated from the envelope parameters (bay dimensions, covering material, etc.) configured in `/geo/facility`.

- **Right-click drag**: Rotate
- **Left-click drag**: Pan
- **Scroll**: Zoom
- **Preset badge**: The facility's structural preset.
- **"connected × N" badge**: Shown for multi-bay (connected) structures.
- **"double layer" badge**: Shown when the envelope has two covering layers.

### B. Environment

7 cells with real-time values. The first four open a setpoint editor when clicked, if in control mode with setpoints enabled and the viewer has permission to control (`edit_settings`):

| Cell | Clickable to set a target? |
|------|----|
| VPD | Yes |
| Indoor temperature | Yes |
| Indoor humidity | Yes |
| CO₂ | Yes |
| Outdoor temperature | No — weather data or an external sensor |
| Wind | No — weather data or an anemometer |
| Solar | No — weather data or a PAR sensor |

Cells without data display `—`. Editable cells also show the current target next to the reading — this is the *effective* target (a manual override, if any, otherwise whatever the attached [Program](programs.md) stage says), the same value control actually follows, not a separately-stored number that could silently disagree with it.

### D. Actuator Control

Shown when **Show Actuator Grid** is on. A grid of sliders and toggles for the facility's bound actuators — **this is a live control surface**, not a read-only display. If **Show Emergency Stop** is enabled, an "ALL STOP" button appears here.

### E. AI Advice

!!! warning "Experimental — leave off in production"
    This panel currently shows **mock demo cards with hardcoded text**, not real recommendations. Its **Approve** button, however, dispatches real actuator commands through `/api/geo/facility/<uuid>/apply`. Do not enable **Show AI Advice** until a real advisor backend is wired up.

---

## Widget Settings

### General

| Option | Description | Default |
|--------|-------------|---------|
| Period (seconds) | Refresh interval for runtime data. `0` disables auto-refresh. | 60 |
| IEC Function | The `env_coordinator` function to link; the facility follows from it. | (auto-select) |
| Show AI Advice (§ E) — EXPERIMENTAL | See the warning above — do not enable in production. | Off |

### Integrated Environment Control (IEC)

| Option | Description | Default |
|--------|-------------|---------|
| Show Status Strip (§ 0) | Emergency/warn/active/idle badge. Control mode only. | On |
| Show Setpoints (§ B/C) | Click-to-set target temp/RH/CO₂/VPD editor. Control mode only. | On |
| Show Actuator Grid (§ D) | Actuator sliders and toggles. Control mode only. | On |
| Show Emergency Stop | "ALL STOP" button in the actuator grid. | Off |

### 3D Rendering

| Option | Description | Default |
|--------|-------------|---------|
| Render Mode | `Default` (semi-transparent cover), `Solid` (opaque, lower overdraw), `Wireframe` (outlines only), or `Performance` (simplified shading + reduced resolution for mobile). | Default |

### Sensor Labels

Real-time measurement values shown next to each sensor in the 3D scene.

| Option | Description | Default |
|--------|-------------|---------|
| Show Sensor Labels | | On |
| Max Channels Shown | Values per label before extra channels collapse to "+" (1–5). | 1 |
| Decimals | Decimal places for label values (0–3). | 1 |
| Label Size (em) | Font size (0.5–2.0). | 0.85 |
| Label Background | CSS color. | `rgba(15,23,42,0.78)` |
| Label Text Color | CSS color. | `#f8fafc` |
| Vertical Offset (m) | Height above the sensor the label is anchored at (0.0–2.0). | 0.25 |
| Label Opacity | 0.0–1.0. | 0.7 |
| Enable Sensor Popup | Click a label to open a 24h chart. | On |

---

## Data Refresh

The widget calls `/api/geo/facility/<uuid>/integration` at the configured **Period** to refresh environment data, and — independent of Period, whenever the status strip is on — `/api/aot/facility/<uuid>/status` every 5 seconds.

- Facilities without sensor bindings will display only `—`.
- External weather data (Open-Meteo) is automatically retrieved based on the facility's GPS coordinates.

---

## No Facility

- **IEC Function set, but its facility isn't configured, or none is registered at all**: the widget shows "No facility selected. Register one at `/geo/facility`."
- **No facility registered anywhere in the system**: "No facilities registered."

How to register a facility:

1. `/geo/design` → Facility mode → Draw building polygon and save
2. `/geo/facility` → Select the facility → Configure envelope → Save

---

## Related Pages

- [Facility Management](facility.md) — 3D model configuration, sensor binding
- [Management Programs](programs.md) — Stage-based targets the effective setpoint follows
- [Map Widget](map-widget.md) — Map-based monitoring
