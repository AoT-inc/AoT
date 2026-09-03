# EnvCoordinator User Guide

> **Audience**: people operating a facility or integrating it with other systems.
> **Scope**: configuring the env_coordinator Function, registering actuators,
> Facility integration, safe operation, logging policy, troubleshooting.
> **Version**: reflects patches P0–P3, dispatch_adapters, facility_integration 4c, safe_default, RotatingFileHandler.

---

## Contents

1. [Overview](#1-overview)
2. [Prerequisites](#2-prerequisites)
3. [Registering the Custom Function](#3-registering-the-custom-function)
4. [GeoFacility Integration](#4-geofacility-integration)
5. [Actuator Registration and Automatic Conversion](#5-actuator-registration-and-automatic-conversion)
6. [Automatic Irrigation Flow Calculation](#6-automatic-irrigation-flow-calculation)
7. [Safety Gates and Emergency Stop](#7-safety-gates-and-emergency-stop)
8. [Method Curves and Growth Schedule](#8-method-curves-and-growth-schedule)
9. [Grouped Actuators](#9-grouped-actuators)
10. [Weather Forecast Integration](#10-weather-forecast-integration)
11. [Operational Commands](#11-operational-commands)
12. [Logging Policy](#12-logging-policy)
13. [Troubleshooting](#13-troubleshooting)
14. [Terminology](#14-terminology)

---

## 1. Overview

EnvCoordinator brings a facility's (greenhouse or plant factory) environmental control together under a single Function.

```
L1 EnvTarget   → decide the target values (VPD, CO₂, T, RH, Light)
L2 Situation   → assess the current state (deviation, limiting factors, trend)
L3 Coordinator → work out each actuator's command + pass it through the safety gates
```

Key features:

- **Photosynthesis optimization** as the primary goal — VPD is controlled by decomposing it into temperature and humidity.
- **Automatic device-type handling**: adapters convert commands for on/off relays, PWM, DACs, and volumetric pumps alike.
- **Facility-shape aware**: uses the GeoFacility's area, volume, vent opening, and irrigation flow directly.
- **Safety first**: only outputs after clearing wind-speed/time-window/safety gates. Provides a single E-stop entry point.

---

## 2. Prerequisites

| Item | Required/Optional | Notes |
|------|----------|------|
| Input device (T/RH sensor) | Required | indoor role |
| Input device (CO₂, light) | Optional | when controlling CO₂/Light |
| Output device (actuator) | Required | vents, fans, heaters, pumps, etc. |
| GeoFacility | Recommended | used for automatic area/volume/irrigation calculation |
| GPS coordinates or GeoFacility location | Recommended | used to determine the timezone (Growth Schedule) |
| Action: `env_actuator` | Required | registers each actuator to the Function |

---

## 3. Registering the Custom Function

1. Go to **Setup → Function → Add** and choose `env_coordinator`.
2. Configure the option groups in order.

### 3.1 Basics

| Option | Recommended value | Description |
|------|--------|------|
| `update_period` | 60 s | Cycle period. 60–300 s recommended |
| `sensor_max_age` | 300 s | How long a sensor reading stays valid |
| `debug_logging` | OFF | ON increases INFO logging per cycle |

### 3.2 VPD Control

| Option | Description |
|------|------|
| `sensor_vpd` | (optional) a sensor that measures VPD directly |
| `vpd_sp_type` | `fixed` or `method` |
| `target_vpd` | used when `fixed` (kPa) |
| `vpd_method_id_device_id` | Method ID, used when `method` |
| `priority_vpd` | VPD's priority on conflict (0–10) |
| `tolerance_vpd` | deadband (kPa) |

### 3.3 Temperature/Humidity Guardrails

```
guide_T_min   < measured T  < guide_T_max
guide_RH_min  < measured RH < guide_RH_max
temp_min      < measured T  < temp_max     (absolute limit)
humid_min     < measured RH < humid_max    (absolute limit)
```

- **guide**: used as the corrected range that VPD decomposes into.
- **min/max**: violating these triggers an Override (safety bypass) command.

### 3.4 CO₂ and Light

`co2_sp_type` (fixed/method), `target_co2`, `co2_method_id_device_id`, `light_min`/`max`, etc.

### 3.5 Photosynthesis Optimization

Turning on `photosynth_mode_enabled = True` uses a crop-specific photosynthesis model (`crop_preset`) to automatically adjust VPD/CO₂ priority via an EWA (Exponentially-Weighted Average).

---

## 4. GeoFacility Integration

### 4.1 Connecting

Set `geo_facility_id` or `geo_facility_id_device_id` to a GeoFacility UUID.

Once connected, the following fill in automatically:

| Field | Source |
|------|------|
| `capacity_meta.volume_m3` | the facility's 3D shape |
| `capacity_meta.envelope_m2` | envelope area |
| `capacity_meta.transmittance` | solar transmittance |
| `capacity_meta.vent_open_m2` | sum of `vent_opening` G1 fittings |
| `capacity_meta.irrigation_flow_lpm` | sum of all emitter flow rates (L/min) |
| `actuators_resolved[*].flow_lpm` | per-actuator emitter flow (P3) |
| `sensors_resolved` | indoor sensor fittings |
| `sensors_outdoor` | outdoor sensor fittings |

### 4.2 Fittings structure

```
GeoFacility
├─ geometry_3d        (facility shape)
├─ fittings           (every fixture)
│  ├─ vent_opening    → actuator_id (vent motor)
│  ├─ irrigation_layer→ actuator_id (valve/pump)
│  ├─ irrigation_pipe → layer_id
│  ├─ irrigation_device (emitter) → pipe_id, layer_id, flow_lph
│  └─ sensor          → input_uuid, sensor_role (indoor/outdoor)
├─ weather_bindings   (forecast Input mapping)
└─ groups             (actuator group definitions)
```

### 4.3 Timezone

The timezone is determined once, from the device's location (GPS) or the GeoFacility's coordinates, and cached.
Without coordinates, the Growth Schedule's date progression may be inaccurate.

---

## 5. Actuator Registration and Automatic Conversion

### 5.1 Adding an Action

Register an actuator under **that Function → Add Action → `env_actuator`**.

| Action option | Description |
|-------------|------|
| Output | the Output to control (relay, PWM, pump, etc.) |
| `kind` | `vent`, `fan`, `heater`, `pump`, `valve`, `humidifier`, `dehumidifier`, `light`, `co2`, `shade`, `thermal_curtain`, `fogger`, etc. |
| `priority` | priority on conflict |
| `safe_default_pct` | the position (0–100) to move to when a safety gate fires or on emergency stop. 0 means OFF |
| `slot_key` | key to map to a GeoFacility slot (optional) |
| `end_behavior` | what happens when the Function is deactivated (`off`, `hold`, `safe_default`) |

### 5.2 Automatic conversion by device type

EnvCoordinator auto-detects the Output's output type and converts a 0–100% command into that device's own format.

| Output type | Adapter | Conversion |
|-------------|--------|----------|
| `on_off` relay | `TimeProportionalAdapter` | `on_sec = cycle_sec × pct/100`; OFF if `pct < 5%` |
| `pwm` | `PwmAdapter` | duty = pct (0–100%) |
| `value` (DAC, stepper) | `ValueAdapter` | passes 0–100% straight through |
| `vol` (volumetric pump) | `VolumetricAdapter` | `vol_ml = flow_lpm × on_sec / 60 × 1000` |
| `actuator_paired` | `PairedAdapter` | forward/reverse pair conversion, internal to the module |

> **Important**: this is decided purely from the Output module's metadata (`OUTPUT_INFORMATION.output_types`) — no separate configuration needed.
> The adapter map is built when `_reload_profiles()` runs and cached in `_adapter_by_id`.

### 5.3 Conversion examples

| Command (%) | on/off relay (60s cycle) | PWM | volumetric pump (1.5 L/min) |
|---------:|---------------------------|-----|------------------------|
| 0 | OFF | duty 0 | OFF |
| 30 | ON for 18 s | duty 30 | 750 ml/cycle |
| 100 | ON for 60 s (continuous) | duty 100 | 2,500 ml/cycle |

---

## 6. Automatic Irrigation Flow Calculation

For every `irrigation_layer` fitting in the GeoFacility, the following is aggregated automatically:

```
irrigation_layer (actuator_id = pump/valve Output)
   └─ irrigation_pipe (layer_id)
       └─ irrigation_device (layer_id, flow_lph)   ← emitter
```

- The sum of each layer's emitter flow is stored as `actuators_resolved[aid].flow_lpm`.
- `_profile_loader_mixin` injects it into `act_capacity_meta['irrigation_flow_lpm']`.
- `VolumetricAdapter` and the fogger effect model use this value directly.

If nothing is configured, the fallback priority is:

1. per-actuator `flow_lpm`
2. the facility-wide `irrigation_summary.totals.flow_lpm`
3. a default of 1.0 L/min

---

## 7. Safety Gates and Emergency Stop

### 7.1 Pre-gate (PreGate)

| Item | Threshold | Action |
|------|--------|------|
| Wind speed | `gate_wind_threshold` (default 12 m/s) | forces vents shut |
| Rain | 0.5 mm/h | restricts ventilation |
| Extreme heat/cold | 45 °C / -5 °C | triggers the appropriate correction command |
| Time window | `time_start`/`time_end` | an external correction gate |

### 7.2 Post-gate (PostGate)

Constrains commands to the slew rate, deadband, and safe range.

### 7.3 safe_default

Each actuator automatically moves to its `safe_default_pct` value in the following situations:

- when a safety gate triggers `forced_commands` (e.g. parking a thermal curtain)
- on a `cmd_emergency_stop` call
- on an external `force_safe_state()` trigger call
- when a Function with `end_behavior = safe_default` is deactivated

`safe_default_pct = 0` is equivalent to OFF.

### 7.4 Triggering an emergency stop

| Method | Description |
|------|------|
| Function Command → `emergency_stop` | UI button |
| Conditional / Trigger → `force_safe_state` | for immediate entry from external automation |
| RPC `output_off` | a bypass path (stops only that individual Output) |

The next cycle is delayed for 60 seconds after an emergency stop.

---

## 8. Method Curves and Growth Schedule

### 8.1 Method

Defines VPD/CO₂/photoperiod targets as a time-based curve.

- **Daily**: a setpoint per time of day (HH:MM)
- **Duration**: a setpoint per elapsed hour since start
- **Daily Bezier**: a smooth diurnal curve
- **Repeating**: a repeating pattern

### 8.2 Growth Schedule

Adds `schedule_week_offset` weeks to `schedule_start_time` to automatically pick the Method's matching stage curve.

> If a power outage or reboot of 24 hours or more is detected, the watchdog raises a warning.
> If it has drifted from the real growth clock, correct it manually with `schedule_week_offset`.

---

## 9. Grouped Actuators

Defined in the GeoFacility's `groups` field (via the Facility edit UI or the API).

```json
{
  "vent_array_1": {
    "mode": "multi_stage",
    "leader": "OUTPUT_UUID_A",
    "members": ["OUTPUT_UUID_B", "OUTPUT_UUID_C"],
    "threshold_pct": 50
  }
}
```

| `mode` | Behavior |
|--------|------|
| `multi_stage` | once the leader's command passes the threshold, members open in sequence |
| `stacked` | evenly distributed |
| `windward_diff` | differential opening based on wind direction |

> With no group defined, actuators are each controlled independently.

---

## 10. Weather Forecast Integration

Map forecast Inputs in the GeoFacility's `weather_bindings`.

```json
[
  {
    "measurement_type": "temperature_forecast",
    "input_uuid": "INPUT_UUID",
    "measurement_id": "MEAS_ID",
    "max_age_sec": 3600
  }
]
```

- If `max_age_sec` is set, that source's own lifetime is used (P2-1).
- Otherwise the Function's `sensor_max_age` applies.
- With `forecast_feedforward_enabled = True`, the lookahead window (`forecast_lookahead_h`) feeds into pre-emptive correction commands.

---

## 11. Operational Commands

Invoke via a Function Command or RPC:

| Command | Description |
|------|------|
| `reload` | reload adapters/profiles after an Action change |
| `run_now` | run the next cycle immediately |
| `emergency_stop` | move every actuator to `safe_default`/OFF + a 60-second delay |
| `force_safe_state` | an E-stop for external automation (no return value) |

---

## 12. Logging Policy

### 12.1 Defaults

- Normal mode: only **INFO** and above are written to file.
- Debug mode (`daemon_debug_mode = True`): DEBUG is also recorded.
- File handler: `RotatingFileHandler`, 50 MB × 5 files = 250 MB max.

### 12.2 What was trimmed to save space

- The InfluxDB `write_success` callback is silenced (the cause of a 15 GB/day spike in the past).
- `write_fail` is WARNING; a failed retry is ERROR.
- EnvCoordinator authority/feedforward messages log at INFO only on a state change; per-cycle detail is DEBUG, and only when `debug_logging = True`.

### 12.3 Recommendation

- Normal operation: `debug_logging = False`, daemon DEBUG OFF.
- When investigating a problem: turn it ON briefly → analyze → turn it back OFF.

---

## 13. Troubleshooting

| Symptom | What to check |
|------|----------|
| An actuator doesn't move | whether the Action is registered, the Output is active, and the adapter-map (`_adapter_by_id`) build log |
| An on/off relay turns on too briefly | the command value is probably below 5% — adjust `priority`/`tolerance` |
| A pump is always calculated at 1.0 L/min | check whether the GeoFacility's irrigation_device fittings have `flow_lph = 0`, and whether `irrigation_layer.actuator_id` matches the pump's Output |
| Vents don't close in high wind | check `gate_wind_threshold` and the wind sensor (`sensor_wind`) mapping |
| A 24-hour watchdog warning | correct the growth week manually with `schedule_week_offset` |
| Logs are growing fast | check that `debug_logging` and `daemon_debug_mode` are OFF, and that RotatingFileHandler is active |
| Growth Schedule dates are off | check whether the device's GPS or the GeoFacility's coordinates are set (used to determine the timezone) |
| Actuators don't move even after E-stop | this is the intended 60-second delay — wait for the `timer_loop` to expire |
| A facility change isn't taking effect | call the `reload` command, or deactivate and reactivate the Function |

---

## 14. Terminology

| Term | Definition |
|------|------|
| VPD | Vapor Pressure Deficit — the gap between saturated and actual vapor pressure (kPa) |
| L1 / L2 / L3 | EnvCoordinator's target / situation / command layers |
| Dispatch Adapter | the component that converts a 0–100% command into a device-type-specific call |
| capacity_meta | the bundle of facility shape/capacity data (volume, vent opening, flow rate, etc.) |
| safe_default | the actuator position (0–100%) to move to automatically in a safety situation |
| Forced Command | a command a safety gate forces to fire |
| Method | a time-based setpoint curve |
| Growth Schedule | a stage curve keyed to weeks since sowing |
| Pre/Post Gate | the safety-verification steps before/after a command is computed |

---

## Appendix Z — Settings, in Detail

The on-screen description is **one line** (2026-08-27). It only says what a setting is — *why* it matters and *when* to turn it on live here instead. Back when the tooltip ran 705 characters, nobody was going to hover long enough to read it.

### Facility and Zone

- **Linked Facility** — set this and actuators are found automatically from this facility (envelope, side/roof vents, curtains, fans). GIS values like orientation, area, and U-value attach to each actuator, so wind direction or solar gain can factor into the calculation. **Without this set, the rest of the settings mean nothing.**
- **Bay scope** — restricts the coordinator to a single bay of the facility. It then uses only that bay's sensors and actuators, and scales facility volume/area down to that bay's share. Leave it blank for the whole facility. Use this when several coordinators split one facility between them.

### Ventilation Strategy

- **Close vents when ventilation can't get there** — ventilation only pushes the indoors **toward the outdoors**. If the target is on the far side of outdoor conditions, opening further never gets closer. The classic case is dehumidifying at night — if it's more humid outside than in, opening the vent only makes it more humid. Leave this off and the vent keeps chasing the target, staying half-open all night.
- **Rest cooling/heating when ventilation can get there** — if outdoor air is **past** the target, ventilation alone can reach it, and running cooling/heating alongside it means paying to do what the outside air would do for free. If outdoor air can only cover part of the target, ventilation takes that part and cooling/heating carries the rest. **If the target still isn't reached after 15 minutes, everything is handed to cooling/heating** — because that means the prediction that "ventilation would get there" was wrong.
- **Lock vents while cooling/heating runs** — prevents heating (or cooling) while throwing that heat away through an open vent. ⚠ In a season where the outdoor air could actually help toward the target, this also throws that help away — check outdoor conditions before turning it on.
- **Running-detection signal** — for equipment **this system does not control**, like a manually switched heater/cooler. Anything that rises while that equipment runs works — a power-reporting smart plug, a current sensor, an auxiliary contact.
- **Park openings at night** — humidity rises and dew forms at night. An opening that looked useful at dusk can leave the crop wet by morning. Turning this on only closes the vents — cooling/heating and dehumidification keep running as normal. **Safety gates (wind, rain, heat, cold) override this and move the vents anyway**, and the temperature/humidity limits also break the parking if exceeded — a closed greenhouse should not cook or flood.

### Nursery and Misting

- **Nursery mode** — a fresh seedling scorches more easily than a mature leaf. A droplet left on a cotyledon focuses light under strong sun, and concentrates whatever minerals were dissolved in it as it dries.
- **Misting water source** — untreated groundwater is usually hard and cold. As droplets dry they leave mineral spots, and can chill a sunlit leaf. Choosing this automatically lowers the scorch-prevention threshold.
- **Allow misting before sunset** — irrigation normally happens in the two windows around sunrise and sunset, but an evening misting leaves leaves wet overnight. The longer leaves stay wet, the higher the risk of gray mold and downy mildew, and a nursery's tight spacing spreads it fast. Some crops genuinely need an evening watering, so this is left as a choice.
- **Use wetting-type misters for humidification** — turn this off when the same nozzles double as the irrigation system. A sprinkler chosen for irrigation puts out far more than humidification needs, leaving a film of water on leaves after even one short burst.

### Other

- **Control end date** — this is a **safety stop**, not a harvest date. Past this date, every actuator returns to its own configured end behavior and the cycle stops. The date is read in the device's/facility's own local timezone. Leave it blank to keep running indefinitely.
- **Vent actuation profile** — how often the vent physically **moves**. Sensing and calculation still run every control cycle, and sudden weather changes or a safety gate move the vent immediately regardless of this setting. Doesn't apply to curtains/shade screens, since those open and close in one motion.
- **Shade screen transmittance** — the fraction of light that gets through when fully deployed (0.30 = 70% shading). Used **only when there is no indoor light sensor** — in that case indoor light is estimated from outdoor solar radiation and the shade's opening. 0 means "not set," so no estimate is attempted at all.
- **Photosynthesis-centered control** — every cycle, figures out what's currently the limiting factor (light, CO₂, temperature, VPD) and raises that variable's priority. Requires a light sensor.
- **Effect engine** — what computes each actuator's effect. `legacy` uses built-in constants (default, safe); `shadow` runs a physics model alongside for logging only, control stays as-is; `grey-box` lets the physics model control. **No reason to change this unless you're testing.**
- **Debug logging** — records each cycle's decision data to InfluxDB. Turn it on only while diagnosing, and off again once done.

---

## Appendix A — Change Log (patch summary)

| Patch | Content |
|------|------|
| P0 | time-proportional conversion for on/off relays, sensor fallback |
| Stage 0–1 | introduced `dispatch_adapters.py`'s 5 adapters, automatic mapping |
| Stage 2 | GeoFacility `groups` column, irrigation_flow_lpm caching |
| Stage 3 | fogger physics model (based on latent heat of evaporation) |
| P2-1 | per-entry `max_age_sec` for weather_bindings |
| P2-3 | `safe_default_pct`, external entry point `force_safe_state()` |
| P3 | per-actuator `flow_lpm` (emitter sum) |
| Logging | RotatingFileHandler 250 MB, `write_success` silenced, fixed an authority bug (`not {}`) |
