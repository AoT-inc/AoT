# AoT_facility Widget

The `AoT_facility` widget shows a facility's 3D view, live environment readings, and — when an Integrated Environment Control (IEC) function is linked — setpoint editing and actuator control, on the dashboard.

---

## Adding the Widget { #adding-the-widget }

1. On the dashboard, select **Add Widget → AoT Facility**.
2. In the settings, select the **IEC Function** — an `env_coordinator` function, not the facility itself. The facility is auto-discovered from that function's configuration.
3. Leave **IEC Function** blank to auto-select the first activated `env_coordinator` function (if none is activated, the first one by name). If there is no `env_coordinator` function at all, or the chosen one has no facility configured, the widget falls back to the most recently updated facility. Without a linked function the status strip shows `IDLE` (unless sensor health raises it) with the reason "No IEC function linked to this facility", but setpoint editing and the actuator panel still work — they act on the facility directly.
4. Click **Save**.

---

## Screen Layout { #screen-layout }

### 0. Status Strip { #0-status-strip }

Shown when **Show Status Strip** is on. A badge polled every 5 seconds from `/api/aot/facility/<uuid>/status`:

| Level | Meaning |
|-------|---------|
| `IDLE` | No linked IEC function, or nothing to report |
| `ACTIVE` | The linked function ran its last control cycle recently, or at least one actuator is currently running |
| `WARN` | The linked function is not activated; or it has not reported a cycle within three times its cycle period (at least 5 minutes); or some of the facility's sensors are not resolving; or VPD is more than 0.15 kPa off target; or CO₂ is more than 10 % above target |
| `EMERGENCY` | Fewer than half of the facility's sensors are resolving; or VPD is more than 0.45 kPa off target; or the indoor temperature is outside the safety limits |
| `ERR` | The status request itself failed — "Connection error" appears instead of the timestamp |

Next to the badge: the linked function's name, the reasons behind the current level, and a timestamp with the active/total actuator count.

### A. 3D View

A building model rendered with Three.js, automatically generated from the envelope parameters (bay dimensions, covering material, etc.) configured in `/geo/facility`.

- **Right-click drag**: Rotate
- **Left-click drag**: Pan
- **Scroll**: Zoom
- **Preset badge**: The facility's structural preset.
- **"connected xN" badge**: Shown for multi-bay (connected) structures.
- **"double layer" badge**: Shown when the envelope has two covering layers.
- **Layer buttons**: Show or hide Envelope, Window, Climate, Sensor, Lighting, and Irrigation.
- **Bottom edge**: Drag to change the view's height. The height and the camera angle are remembered in this browser.

### B. Environment { #b-environment }

7 cells with real-time values. Two of them open a range editor when clicked, if **Show Setpoints** is on and the viewer has permission to control (`edit_settings`):

| Cell | Clickable to edit ranges? |
|------|----|
| VPD | No — the target is set in the attached [Program](programs.md) |
| Indoor temperature | Yes — guidance range and hard safety limits |
| Indoor humidity | Yes — guidance range and hard safety limits |
| CO₂ | No — the target is set in the attached [Program](programs.md) |
| Outdoor temperature | No — weather data or an external sensor |
| Wind | No — weather data or an anemometer |
| Solar | No — weather data or a PAR sensor |

Cells without data display `—`. The VPD and CO₂ cells show the current target next to the reading — this is the *effective* target, read the same way control reads it from the attached Program stage ("Follows a curve" when that stage target follows a curve), not a separately-stored number that could silently disagree with it. The indoor temperature and humidity cells show their guidance range instead. All four are tinted by how far the reading sits from that target or range.

The editor holds two pairs per cell: a **guidance range**, the band within which the VPD target is decomposed into temperature and humidity, and **hard safety limits**, which force protective action regardless of the target. Targets cannot be set here — a target sent to this editor is refused, with a note that the Program is where it belongs.

### D. Actuator Control { #d-actuator-control }

Shown when **Show Actuator Grid** is on. The facility's bound actuators, grouped by kind — **Window**, **Insulation**, **Shade**, **Irrigation**, and **Other** (groups with no actuators are hidden; "No actuators registered" appears if there are none). For viewers with permission to control (`edit_settings`), **this is a live control surface**, not a read-only display. Each row's control depends on how the actuator is driven:

| Actuator | Control |
|----------|---------|
| Position (e.g. a paired open/close motor) | 0–100 % slider. A dot on the track marks the current position; above it, the last target (**Manual** or **System**, by who set it) and the **Current position**. |
| PWM | 0–100 % duty-cycle slider. |
| On/off | **ON** / **OFF** buttons. |

A slider sends its command when you release it; a button, when clicked. While a safety gate is active — high wind, for instance — a command that contradicts the value the gate forces is refused and the actuator stays where it is; the widget shows no message, so check the gate before assuming the row is broken. A command that does not contradict the gate (turning a heater on during a wind gate) goes through as a manual override. Drag a row's grip handle to reorder rows within a group — the order is saved per facility. Viewers without `edit_settings` see the same rows read-only, with no sliders, buttons, or handles. Values refresh every **Period**.

An **Emergency Stop** button sits under the grid when **Show Emergency Stop** is on — it is off by default, and it only appears for viewers with permission to control. It asks for confirmation, then sends every actuator of the facility to its safe state. It also stops automatic control: each activated linked function is given its own **Emergency Stop**, which holds that function's next control cycle for 60 seconds so it cannot move the actuators straight back. If no linked function is activated, the outputs are sent to their safe state directly. The outcome appears as a message with the number of actuators reached ([Emergency stop and safe state](../ai/env-control.md#emergency-stop)).

### E. AI Advice { #e-ai-advice }

!!! warning "Experimental — leave off in production"
    This panel currently shows **mock demo cards with hardcoded text**, not real recommendations. Its **Approve and apply** button, however, dispatches real actuator commands through `/api/geo/facility/<uuid>/apply`. Do not enable **Show AI Advice** until a real advisor backend is wired up.

---

## Widget Settings { #widget-settings }

### General

| Option | Description | Default |
|--------|-------------|---------|
| Period (seconds) | Refresh interval for runtime data. `0` disables auto-refresh. | 60 |
| IEC Function | The `env_coordinator` function to link; the facility follows from it. | (auto-select) |
| Show AI Advice (§ E) — EXPERIMENTAL | See the warning above — mock demo cards with fixed text; the cards never send actuator commands. | Off |

### Integrated Environment Control (IEC)

| Option | Description | Default |
|--------|-------------|---------|
| Show Status Strip (§ 0) | Emergency/warn/active/idle badge. | On |
| Show Setpoints (§ C) | Temperature/humidity guidance-range and safety-limit editor, opened by clicking a § B cell. Requires `edit_settings`. | On |
| Show Actuator Grid (§ D) | The actuator control panel. | On |
| Show Emergency Stop | The ALL STOP button under the actuator grid (§ D). Requires `edit_settings`. | Off |

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

## Data Refresh { #data-refresh }

The widget calls `/api/aot/facility/<uuid>/runtime` once on load and then at the configured **Period** (skipped while the browser tab is hidden) to refresh environment readings and actuator states, and — independent of Period, whenever the status strip is on — `/api/aot/facility/<uuid>/status` every 5 seconds.

Actuator states are always read live. Environment readings come from the linked function's own last control cycle while that function is activated and reporting, so they are as fresh as its cycle. Without such a function they are built in the background rather than holding up the response: right after a dashboard loads the cells can still show `—` and fill in on a later poll.

- Facilities without sensor bindings will display only `—`.
- Outdoor values come from the facility's outdoor sensor and weather Inputs; anything left unset is filled in from the shared external environment context, and only while that context is less than 10 minutes old.

---

## No Facility { #no-facility }

If the chosen IEC Function has no facility configured, the widget falls back to the most recently updated facility, so the message appears **only when no facility is registered anywhere in the system**: "No facility selected. Register one at `/geo/facility`."

How to register a facility:

1. `/geo/design` → Facility mode → Draw building polygon and save
2. `/geo/facility` → Select the facility → Configure envelope → **Save Facility**

---

## Related Pages

- [Facility Management](facility.md) — 3D model configuration, sensor binding
- [Management Programs](programs.md) — Stage-based targets the effective setpoint follows
- [Map Widget](map-widget.md) — Map-based monitoring
