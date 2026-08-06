# Environmental Control Automation

AoT's `env_coordinator` is a 3-layer control system that automatically manages greenhouse environment parameters — VPD, CO₂, temperature, and humidity.

---

## VPD (Vapor Pressure Deficit)

VPD is the key metric determining plant transpiration and water uptake.

```
VPD = SVP × (1 - RH/100)
SVP = 0.6108 × exp(17.27T / (T + 237.3))  [kPa]
```

| Range | Status | Recommended crop stage |
|-------|--------|----------------------|
| < 0.4 kPa | Too low — mold risk | — |
| 0.4–0.8 kPa | Optimal | Germination / early transplant |
| 0.8–1.2 kPa | Optimal | Vegetative growth |
| 1.2–1.8 kPa | Optimal | Flowering / fruiting |
| > 1.8 kPa | Too high — water stress | — |

---

## env_coordinator Control Layers

### L1 — EnvTarget (setpoint)

Reads VPD / CO₂ targets from a Method curve or fixed values.

- **Method**: Time-based target curve by crop stage (seeding to harvest)
- **Fixed value**: Use a constant setpoint for simple operation

### L2 — SituationReport (evaluation)

Evaluates current deviation, limiting factors, and trend.

| Evaluation item | Description |
|----------------|-------------|
| Deviation | `current value - target` |
| Limiting factor | Which of temperature/humidity/CO₂ is preventing VPD from reaching target |
| Trend | Whether the value is moving toward the target |

### L3 — Coordinator (actuator command)

Applies PI control + slew rate limiting + anti-windup to command actuators.

```
e(t) = setpoint - measurement
u(t) = Kp × e(t) + Ki × ∫e dt
slew: |Δu| ≤ slew_rate_per_cycle
output → heater / vent fan / humidifier / CO₂ supply
```

---

## Function Configuration

Navigate to `Functions → env_coordinator` in the AoT UI. Actuators themselves are
registered separately via "Environment Control: Register Actuator" actions, or
auto-discovered from a linked GeoFacility (see **Facility** below) — this function's
options only cover targets, timing, and safety thresholds.

### Commands

| Command | Effect |
|---------|--------|
| Reload Actuators | Re-reads the Actions table and rebuilds actuator profiles. |
| Run Now | Executes one coordination cycle immediately using current sensor readings. |
| Emergency Stop | Immediately sets all actuators to `safe_default` and pauses control for 60 s. |
| Apply Crop Preset Targets | Force-fills VPD / CO₂ / Temp / DLI / GDD target fields from the selected Crop Preset (overwrites current values; variables using a Method are skipped). Save the function first if you just changed the crop preset. |

### Basic

| Field | Default | Description |
|-------|---------|-------------|
| Period (seconds) | 60 | Coordination cycle interval — sensing, computation, and (subject to Actuation Rate below) dispatch. Recommended: slowest actuator response time × 1.5. |
| Max Sensor Age (seconds) | 120 | Reject sensor readings older than this value. 0 = no limit. |

### Actuation Rate

Governs only how often side/roof vents (`opening` actuators) are allowed to move under
normal conditions — a separate, slower cadence from the Period above, to reduce vent
motor wear. Sensing/computation always run every Period. Curtains/shades are unaffected
(they open/close in one fully-open-or-closed step, not a gradual position). Sudden
weather changes and safety gates (wind/rain/heat/cold) always move vents immediately,
regardless of this setting — see the emergency fields below.

| Field | Default | Description |
|-------|---------|-------------|
| Vent Actuation Profile | Standard (180s) | `Responsive` (60s) / `Standard` (180s) / `Gentle` (600s, extends vent motor life) / `Custom` (use the seconds field below). |
| Custom Actuation Period (seconds) | 0 | Used only when Vent Actuation Profile = Custom. 0 = fall back to the selected profile's default. |
| Emergency Minimum Interval (seconds) | 60 | Even during an emergency, vents will not be re-commanded more often than this — prevents rapid back-to-back moves. |
| Emergency Deviation Threshold (× tolerance) | 3.0 | If a variable deviates from its target by more than this many times its tolerance, treat the cycle as an emergency and move vents immediately (ignore the actuation period above). |
| Emergency Rate Threshold (°C / 10min) | 2.0 | If indoor temperature is changing faster than this rate, treat the cycle as an emergency and move vents immediately. |
| Close Vents When Ventilation Cannot Help | On | Ventilation can only pull the inside toward the outside. When the target lies on the far side of the outdoor air, opening moves away from it no matter how wide — the classic case is dehumidifying at night, when outdoor air is wetter than indoor. With this on, vents and exhaust/intake fans park closed in that situation instead of holding a partial opening all night. Applies whenever the outdoor air cannot deliver the target, not only at night. Safety gates and the temperature/humidity limits still override it. |

### Growth Schedule

| Field | Default | Description |
|-------|---------|-------------|
| Schedule Start (planting date) | (empty) | Planting/germination date. Interpreted in the device/facility local timezone. Used to compute `weeks_elapsed` for all Method curves. Leave empty to disable week-based progression (Methods use wall-clock day only). |
| Schedule End (harvest date) | (empty) | Harvest/cycle-end date. Methods keep following actual elapsed weeks until this date; once it passes, control stops — every actuator returns to its configured end-behavior and coordination cycles halt. Leave empty for no end date. |
| Week Offset | 0 | Direct week adjustment applied on top of elapsed weeks. Positive to fast-forward (e.g. system started mid-cycle), negative to compensate for downtime. |

### Facility (optional)

| Field | Default | Description |
|-------|---------|-------------|
| Linked Facility | (none) | When set, actuators are auto-discovered from this GeoFacility (envelope, side/roof vents, curtains, fans). GIS metadata (azimuth, area, U-value) is attached to each actuator profile so wind direction and facility geometry can be considered. Manual "Environment Control" actions still apply and are merged with the facility-derived list. Leave empty to use manual actions only. |
| Bay Scope (optional) | (empty) | Restrict this coordinator to one bay of the linked facility (bay ID, e.g. `bay_1`). Only sensors/actuators inside that bay are used, and facility volume/area are scaled to the bay share. Leave empty to control the entire facility; create one coordinator per bay to control multiple bays independently. |

### Time Control

| Field | Default | Description |
|-------|---------|-------------|
| Enable Time Window | Off | When enabled, control only runs between Start and End times. |
| Start Time (HH:MM) | 06:00 | Control period start time (24-hour format). Only active when Enable Time Window is on. |
| End Time (HH:MM) | 20:00 | Control period end time. On-end behavior per actuator is configured in each Action. Ignored when Photoperiod Method is set. |
| Photoperiod Method | (none) | Optional. An AoT Method returning photoperiod length in hours (e.g. 14.0 = 14 h light). Computes time_start/end symmetrically around the Anchor time, overriding the static Start/End times above. |
| Photoperiod Anchor (HH:MM) | 12:00 | Solar-noon equivalent — the photoperiod window is centred on this time. Adjust for latitude/season if needed. |

### VPD (primary control target)

| Field | Default | Description |
|-------|---------|-------------|
| Setpoint Type | Static Target | `Static`: use the fixed target below. `Method`: follow an AoT Method curve. |
| Target VPD (kPa) | 0.8 | Used when Setpoint Type = Static. 0 = disable VPD control. |
| Method | (none) | Used when Setpoint Type = Method. An AoT Method returning a VPD setpoint (kPa). |
| VPD Priority | 1.2 | Higher value = processed first. |
| VPD Tolerance (kPa) | 0.1 | Dead-band half-width around the VPD setpoint — adjustments are skipped inside this range, reducing unnecessary actuator cycling. Typical: 0.05–0.15 kPa. |

### Light Intensity

| Field | Default | Description |
|-------|---------|-------------|
| Max Light Threshold | 800 | Activates the shade screen when light exceeds this value. 0 = disabled. |
| Min Light Threshold (Supplemental) | 0 | Activates supplemental lighting when light falls below this value. 0 = disabled (most facilities — natural light only). |

### CO₂

| Field | Default | Description |
|-------|---------|-------------|
| CO₂ Setpoint Type | Static Target | `Static`: fixed target below. `Method`: AoT Method curve (ppm vs time-of-day / growth week). |
| Target CO₂ (ppm) | 1000 | Used when CO₂ Setpoint Type = Static. |
| CO₂ Method | (none) | Used when CO₂ Setpoint Type = Method. An AoT Method returning a CO₂ setpoint (ppm). |
| CO₂ Priority | 0.8 | Processing-order weight relative to other control variables — higher processes earlier. Lower than VPD (1.2) since CO₂ enrichment is secondary. |
| CO₂ Tolerance (ppm) | 100 | Dead-band half-width around the CO₂ setpoint. Typical: 50–150 ppm. |

### Temperature (hard constraint, not a primary target)

| Field | Default | Description |
|-------|---------|-------------|
| Max Temperature (°C) | 35 | Hard upper limit — forces cooling when exceeded, regardless of the VPD target. |
| Min Temperature (°C) | 5 | Hard lower limit — forces heating when below, regardless of the VPD target. |

### Humidity (hard constraint, not a primary target)

| Field | Default | Description |
|-------|---------|-------------|
| Max Humidity (%) | 90 | Hard upper limit — prevents VPD bypass via extreme humidity. |
| Min Humidity (%) | 30 | Hard lower limit — prevents VPD bypass via extreme dryness. |

### VPD Decomposition

| Field | Default | Description |
|-------|---------|-------------|
| T Weight (0–1) | 0.6 | Fraction of a VPD adjustment carried out via temperature (the rest via humidity). 0.6 favours temperature. |

### Photosynthesis Model (optional)

| Field | Default | Description |
|-------|---------|-------------|
| Enable Photosynthesis-Oriented Control | Off | The Big-Leaf photosynthesis model identifies the current limiting factor (Light / CO₂ / Temperature / VPD) each cycle and dynamically raises that variable's priority. Requires a Light sensor; recommended when ≥ 3 active actuator types are available. |
| Crop Preset | Tomato | `Tomato` / `Lettuce·Leafy greens` / `Cucumber` / `Strawberry` / `Pepper·Paprika`. On Save, fills VPD/CO₂/Temp min-max/DLI/GDD from this preset unless you changed a value or use a Method for that variable (your setting wins). Use the "Apply Crop Preset Targets" command to force-overwrite. Also selects Big-Leaf model parameters (A_max, K_L, K_C, T_opt, VPD_half), used only when Photosynthesis-Oriented Control is on. |

### Guide Ranges (T / RH)

| Field | Default | Description |
|-------|---------|-------------|
| Guide T Min (°C) | 12 | Advisory lower bound for temperature — triggers forced heating when exceeded. |
| Guide T Max (°C) | 32 | Advisory upper bound for temperature. |
| Guide RH Min (%) | 40 | Advisory lower bound for relative humidity. |
| Guide RH Max (%) | 85 | Advisory upper bound for relative humidity. |

### Cumulative Goal Tracker

| Field | Default | Description |
|-------|---------|-------------|
| Enable DLI / GDD Tracker | Off | Tracks daily light integral (DLI) and growing degree-days (GDD), rolling over at facility-local midnight. Requires a Light sensor for DLI tracking. |
| DLI Target (mol/m²/day) | 0 | 0 = use the selected crop preset default (leafy greens ~14, tomato/cucumber/pepper ~22, strawberry ~17). |
| GDD Target (°C·day/day) | 0 | 0 = use the selected crop preset default (≈ T_opt − T_base). Computed as max(0, T_mean − T_base) per cycle. |

### Wind

| Field | Default | Description |
|-------|---------|-------------|
| Strong Wind Threshold (m/s) | 12 | Openings (vents, side walls) are forced closed above this wind speed. |

### Effect Calibration

| Field | Default | Description |
|-------|---------|-------------|
| Effect Engine | Legacy | `Legacy`: built-in K_* constants (default, safe). `Shadow`: runs the grey-box model in parallel for KPI logging only — no control change. `Grey-box`: physics-model control (with MPC look-ahead when a forecast is available); activates only after the Shadow KPI passes and parameters converge, falling back to Legacy until then. Recommended flow: Shadow first, then Grey-box. |
| Enable RLS Calibration | Off | Learns per-actuator effect coefficients (K_*) from sensor response. Needs several days to converge; falls back to built-in defaults until then. |
| Enable Active Probing | Off | Periodically perturbs one actuator by ±10% to improve calibration identifiability. Only triggers when load is low and no safety gate is active. Requires RLS Calibration. |
| Probe Interval (seconds) | 3600 | Minimum time between active probing events. |

### Forecast Feedforward

| Field | Default | Description |
|-------|---------|-------------|
| Enable Forecast Feedforward | Off | Uses the KMA short-term weather forecast to proactively shift temperature/humidity setpoints and inhibit ventilation before adverse weather arrives. |
| Forecast Lookahead (hours) | 3 | How many hours ahead to check for incoming adverse weather (1–6 h). Longer gives earlier warning but may over-correct. |

### Diagnostics

| Field | Default | Description |
|-------|---------|-------------|
| Enable Debug Logging | Off | Writes per-cycle decision data to InfluxDB (targets, deviations, mode, cycle metrics, actuator-mismatch count, learning hygiene) and emits per-cycle DEBUG log lines. Leave off in production — critical events (safety gate, dispatch failure, runtime-state error) are always recorded regardless of this flag. |

---

## Methods (Setpoint Curves)

A Method defines how a setpoint changes over time.

**Example crop stage schedule (tomato):**

| Day | VPD target | CO₂ target |
|-----|-----------|-----------|
| Seeding–Day 7 | 0.6 kPa | 800 ppm |
| Day 8–21 | 0.8 kPa | 900 ppm |
| Day 22–42 | 1.0 kPa | 1000 ppm |
| Day 43+ | 1.3 kPa | 1000 ppm |

Methods prefixed with `SEED:` are seed presets and are read-only. Duplicate a preset before editing.

---

## Safety Gates

Safety runs outside the L1–L3 coordination algorithm — a Pre-Gate checked every
cycle before L1–L3, and a Post-Gate that sanity-checks the L3 result before it is
dispatched. Once triggered, a Pre-Gate stays active for at least 300 s after its
last trigger (prevents rapid on/off flapping).

### Pre-Gate (checked before L1–L3)

| Gate | Trigger condition | Action |
|------|--------------------|--------|
| Rain | Rain rate ≥ 0.5 mm/hr (fixed, not user-configurable) | Closes side/roof vents (`opening` actuators). Curtains/shades are interior equipment and are left alone. |
| Strong Wind | Wind speed ≥ **Strong Wind Threshold** option (default 12 m/s, see **Wind** above) | Closes vents. If wind is the *only* active gate and both wind direction and vent azimuth are known, only windward vents (within ±60°) are forced closed — leeward vents keep running under normal control. |
| Heat Emergency | Outdoor T ≥ 45°C **and** indoor T ≥ 35°C (both fixed) | Fully opens vents, closes shade screens, forces coolers to 100%. |
| Cold Emergency | Outdoor T ≤ −5°C **and** indoor T ≤ 5°C (both fixed) | Closes vents, closes thermal curtains, forces heaters to 100%. |
| Internal Sensor Expired | No fresh indoor reading for > 120 s (fixed) | Every actuator returns to its configured `safe_default` — control isn't possible without indoor data. |
| External Sensor Expired (alone) | No fresh outdoor reading for > 300 s, and no other gate is active | Partial gate: only vents/shade close conservatively; heater/cooler/fogger/CO₂/curtain keep running under normal L1–L3 control. |

Rain, Heat, and Cold thresholds are fixed in code — the **Wind** threshold is the
only one exposed as a function option. Multiple gates can be active at once (e.g.
rain + strong wind); vents then close unconditionally regardless of direction.

### Post-Gate (checked after L3, before dispatch)

| Check | Action |
|-------|--------|
| Non-finite command (NaN/Inf) | Actuator falls back to its `safe_default`. |
| Out-of-range command | Clamped to [0, 100]. |
| Manual Lock active | Overrides with the locked value. |
| Cooler and heater both ON at once | Not allowed — the cheaper one (lower `cost_fn`) keeps running, the other is forced to 0. |

---

## AI Integration

The AI agent uses `analyze_control_performance` to diagnose control quality.

```
vpd_rmse         → VPD tracking error (lower is better)
oscillation_index → Control oscillation index (lower is more stable)
assessment       → "good" / "moderate" / "poor"
```

Based on diagnostics, `suggest_setpoint_adjustment` proposes a target adjustment. After user approval, `set_vpd_target` applies it.

---

## Related Pages

- [AI Overview](overview.md)
- [Functions Guide](../Functions.md)
- [Methods Guide](../Methods.md)
