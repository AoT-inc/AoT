# Environmental Control Automation

AoT's `env_coordinator` (shown in the UI as **Integrated Environment Control**) is a
3-layer control system that coordinates every actuator in one facility — vents,
exhaust/intake fans, heaters, coolers, misters, shade screens, thermal curtains,
supplemental lights and CO₂ injectors.

Two things are decided in two different places, and mixing them up is the single
most common source of confusion:

- **What to aim for** — VPD, CO₂, DLI and the rest — belongs to the **plot** that is
  growing in the facility, through the cultivation program attached to it.
- **How to get there** — which equipment exists, what lines must never be crossed,
  how eagerly to chase the target — belongs to **this function**.

---

## Where Targets Come From { #targets }

| Layer | Owns | Edited in |
|-------|------|-----------|
| Program (`GeoProgram`) | The reference plan: stages, the target vocabulary, target curves, the crop's photosynthesis constants | Programs page |
| Plot (`GeoPlot`) | The actual plan: stage boundary dates and per-stage target values for this plot | Plot screen (stage schedule) |
| env_coordinator | How to reach it: equipment, safety limits, priorities, tuning, emergency behaviour | Function settings |

A plot **internalises** the program it selects. Editing a stage target on the plot
screen overrides that one item for that plot only; the program and every other plot
using it stay untouched. Clearing the field returns the item to the program value —
that is why there is no separate "revert" button.

Two limits are deliberate:

- The plot cannot invent new target **items**. The vocabulary is the program's
  (`target_defs`), so an unknown key is rejected rather than silently ignored.
- An item that follows a **curve** cannot be overridden with a number. The curve wins,
  and the plot screen shows that item as read-only.

### What the coordinator reads each cycle { #targets-read }

| Value | Used for |
|-------|----------|
| VPD target (number or curve) | The primary control target |
| CO₂ target (number or curve) | CO₂ enrichment; when absent, CO₂ control rests |
| DLI target · daily GDD target | The cumulative tracker |
| `T_base` | GDD accumulation |
| Plot start date | Elapsed weeks, which drive stage-based curves |
| Photosynthesis constants (`A_max`, `K_L`, `T_opt`, `VPD_half`) | The Big-Leaf model, and the light saturation point derived from `K_L` |

Targets are matched to a control axis by **measurement and shape**, not by the key
name — a user-named item such as "Indoor CO₂" still reaches CO₂ control as long as its
measurement is CO₂. An item with no measurement selected reaches no axis at all and is
shown as *For reference*.

### When there is no plot { #targets-no-plot }

The coordinator does **not** stop. With no plot, no program, an AI draft that has not
been reviewed, or no stage running today, there are simply no targets: control keeps
running inside its own guide ranges, which is already the defined behaviour — an empty
greenhouse still needs heating.

Since 2026-09-01 the coordinator has **no end-date option of its own**. Whether growing
continues is the plot's business. The previous behaviour was that a date set once in the
function kept the facility stopped even after a new crop was planted.

### More than one plot in scope { #targets-reference-plot }

Intercropping is normal, so the coordinator never guesses. With two or more plots in its
facility/bay scope it says so and offers a **Follow this one** button; the same choice is
stored in **Reference Plot** under Advanced Settings. If the pinned plot ends or leaves
the scope, the value is not erased — the screen says the pinned plot is no longer there
and the selection rules are applied again.

> The program version recorded on a plot pins the *version number*, not the *content*.
> Editing a program does change the interpretation of plots already in progress.

---

## VPD (Vapor Pressure Deficit) { #vpd-vapor-pressure-deficit }

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

## env_coordinator Control Layers { #env_coordinator-control-layers }

### L1 — EnvTarget (setpoint) { #l1-envtarget-setpoint }

Resolves the targets described above into setpoints for this cycle. A target that
follows a Method is evaluated with the plot's elapsed weeks and the facility's local
timezone.

### L2 — SituationReport (evaluation) { #l2-situationreport-evaluation }

Evaluates current deviation, limiting factors, and trend.

| Evaluation item | Description |
|----------------|-------------|
| Deviation | `current value - target` |
| Limiting factor | Which of temperature/humidity/CO₂/light is preventing the target from being reached |
| Trend | Whether the value is moving toward the target |

When VPD can be used, temperature and humidity are demoted to *constraints* — the
range VPD is decomposed into, and the lines that must not be crossed. This function
is not a thermostat.

### L3 — Coordinator (actuator command) { #l3-coordinator-actuator-command }

Applies PI control + slew rate limiting + anti-windup to command actuators.

```
e(t) = setpoint - measurement
u(t) = Kp × e(t) + Ki × ∫e dt
slew: |Δu| ≤ slew_rate_per_cycle
output → heater / vent / fan / mister / CO₂ supply
```

---

## Actuator Domains { #domains }

Load sharing happens **within** a domain, and domains are separated by where the
energy ends up — not by how similar the devices look. The settings screen follows the
same split.

| Domain | Devices | Nature |
|--------|---------|--------|
| Ventilation | Vents/openings, exhaust fan, intake fan | Can only push the inside toward the outside |
| Heating, cooling and misting | Heater, cooler, fogger | Adds or removes directly, regardless of outdoor air |
| Light and shading | Shade screen, thermal curtain, supplemental lighting | Blocks or adds incoming/outgoing radiation |
| CO₂ | CO₂ injector | Its own axis, with nothing to compete against |

Because domains do not see each other's work, coordination between them is done by
**declared interlocks** (see [Ventilation](#settings-ventilation)), never by implicit
accumulation of effects.

### Roof vents and side vents behave differently { #vent-form }

Both are `opening` actuators, but the facility drawing distinguishes a ridge (roof)
window from a side window, and the effect model uses it:

| Form | Indoor warmer than outdoor | Outdoor warmer than indoor |
|------|---------------------------|----------------------------|
| Ridge (roof) | Buoyancy helps — the same area removes more heat | Reversed — hot outdoor air does not descend easily |
| Side | The reference case | Direct inflow, which is straight heating |

If the drawing does not say which form an opening is, it behaves exactly as before
(no correction).

---

## Function Configuration { #function-configuration }

Navigate to `Functions → Integrated Environment Control` in the AoT UI. Actuators
themselves are registered separately (see [Registering Actuators](#actuators)) or
auto-discovered from the linked facility.

### Reading the settings screen { #settings-screen }

The screen was rebuilt in 2026-08. Five things are worth knowing before reading the
tables below.

**A status header sits at the top.** Under the facility picker the screen shows what
control is doing right now — the current VPD against its target, the position of each
device kind (Vents, Heating, Cooling, Misting, Shade …), and how long ago the last
decision was made. Below it, a two-line summary names the plot being followed, the
stage it is in, and the targets in effect. States where nothing can run are spelled
out separately: no facility linked, control switched off, no recent decision. If the
plot ends within two weeks, one extra line says so.

**Settings are arranged in four layers, not by option type.**

| Layer | What | Shown |
|-------|------|-------|
| Connection | Facility, bay | Always |
| Commitments | Temperature/humidity ranges, CO₂ tolerance | Always |
| Strategy | Ventilation/HVAC teamwork, night closing, misting protection | Always, as a toggle or a step scale |
| Tuning | Everything else | Behind **Advanced**, and inside the folded Advanced Settings group |

**A key setting carries its details with it.** Instead of asking for a number nobody
can answer ("should the emergency multiplier be 3.0 or 4.0?"), the screen asks a
question that can be answered and moves several values at once, the way a robot
vacuum offers Quiet / Normal / Strong. Three such controls exist: Control Temperament,
Ventilation and HVAC Teamwork, and Misting Frequency. **The step name itself is never
saved** — only the real values are, and the current step is inferred back from them.
If the values match no step, the control reads *Custom*.

**Ranges are asked as a band with two handles.** Temperature and humidity have one
question — what range to grow in — and the hard limits are derived from it by a fixed
margin (±5 °C, ±5 %RH). One consequence is deliberate: the hard limit can never be
tighter than the guide range, so "grow at 12–32 °C but never exceed 30 °C" cannot be
expressed. That combination is what once had a heater and a cooler both driven to
100 % against each other.

**One [Advanced] switch opens every numeric field.** It turns each step scale into a
step scale plus its number box, reveals every advanced-only row, and expands the folded
groups in one go. The switch lives in the browser only — it is not part of the saved
configuration, so two people never see the same function differently because of it.
Settings whose parent toggle is off are hidden rather than disabled, so their stored
values are still submitted and survive being toggled off and on.

> Some settings are read only under a specific condition — the custom actuation period
> only when the profile is *Custom*, the night clock times only when night is measured
> by fixed times. The screen reports a value that was entered but is not being used,
> because otherwise it silently does nothing.

### Commands { #commands }

| Command | Effect |
|---------|--------|
| Reload Actuators | Re-reads the Actions table and rebuilds actuator profiles. |
| Run Now | Executes one coordination cycle immediately using current sensor readings. |
| Emergency Stop | Immediately sets all actuators to their safe default and pauses control for 60 s. |

### Facility Settings { #settings-facility }

| Field | Default | Description |
|-------|---------|-------------|
| Linked Facility | (none) | Which facility this coordinator runs. Actuators and sensors come from it — envelope, side/roof vents, curtains, fans, indoor and outdoor sensors. GIS metadata (azimuth, area, U-value) is attached to each actuator profile so wind direction and facility geometry can be considered. Without this, the remaining settings have nothing to act on. |
| Bay Scope (optional) | (empty) | Limits this coordinator to one bay. Only sensors and actuators inside that bay are used, and facility volume/area are scaled to the bay's share. Leave blank for the whole facility; create one coordinator per bay to control several bays independently. This is a **dropdown** of the linked facility's bays — a saved value that no longer exists in the facility is kept and marked, rather than silently dropped. |

### Working Hours { #time-control }

Only the toggle is visible until it is switched on. This is a switch, not a schedule:
outside the window the coordinator stops **entirely**, heating and cooling included.
Safety limits still act.

| Field | Default | Description |
|-------|---------|-------------|
| Enable Time Window | Off | When enabled, control only runs between Start and End. |
| Start Time (HH:MM) | 06:00 | When the coordinator starts working each day. |
| End Time (HH:MM) | 20:00 | When it stops. What each device does at that moment is set in its Action. |
| Photoperiod Method | (none) | Sets the window from a day-length curve instead of fixed times. Careful: a short day length means the coordinator runs only for those hours, so nothing is heated overnight. |
| Photoperiod Anchor (HH:MM) | 12:00 | Solar-noon equivalent — the window is centred on this time. |

### Target and Temperament { #settings-target }

| Field | Default | Description |
|-------|---------|-------------|
| Temperature Range | 12–32 °C | The range to grow in. Past a limit, control stops whatever pushes the wrong way — too warm: heating off and the shade screen drawn; too cold: cooling off, vents and thermal curtain closed. It does not slam anything to full. |
| Humidity Range | 40–85 % | Same rule for humidity — too damp: misting off; too dry: exhaust fans off. |
| CO₂ Tolerance (ppm) | 100 | Dead-band half-width around the CO₂ setpoint. Typical: 50–150 ppm. |
| Control Temperament | (Custom) | How hard the system chases the target. One step sets the cycle period, the vent actuation profile, the VPD dead-band and both emergency thresholds together. A newly added function's factory values match no step, so the control reads *Custom* until you pick one. |

Under [Advanced], each range band also shows the four numbers behind it
(`Guide T Min/Max`, `Min/Max Temperature`, and the humidity equivalents), and Control
Temperament shows its members:

| Member | Relaxed | Standard | Responsive |
|--------|---------|----------|-----------|
| Period (seconds) | 600 | 120 | 60 |
| Vent Actuation Profile | Gentle (600 s) | Standard (180 s) | Responsive (60 s) |
| VPD Tolerance (kPa) | 0.15 | 0.1 | 0.05 |
| Emergency Deviation Threshold (× tolerance) | 4.0 | 3.0 | 2.0 |
| Emergency Rate Threshold (°C / 10 min) | 3.0 | 2.0 | 1.5 |

Two further members sit in the same place but are **not** set by the step, because
they are fine adjustments on the same axis: **Custom Actuation Period (seconds)** —
used only when the profile is *Custom* — and **Emergency Minimum Interval (seconds)**,
default 60, the floor between two vent commands even during an emergency.

The actuation profile governs only how often side/roof vents are allowed to *move*.
Sensing and computation always run every cycle period, curtains and shade screens are
unaffected (they open or close in one motion), and sudden weather changes or a safety
gate move the vents immediately regardless.

### Ventilation { #settings-ventilation }

| Field | Default | Description |
|-------|---------|-------------|
| Ventilation and HVAC Teamwork | High performance | Keeps venting and HVAC from working against each other. Three steps, described below. |
| Close at Night | Off | Keeps the vents closed overnight and lets heating, cooling and drying carry the load. Only openings are parked; heating, cooling and dehumidification keep running. |
| Strong Wind Threshold (m/s) | 12 | Openings are forced closed above this wind speed. [Advanced] |

**Ventilation and HVAC Teamwork** moves three toggles at once:

| Step | Close vents when ventilation cannot help | Rest heating/cooling when venting can reach the target | Keep vents closed while heating or cooling runs |
|------|---|---|---|
| High performance (default) | On | Off | Off |
| Standard | On | On | Off |
| Energy saving | On | On | On |

- **Close Vents When Ventilation Cannot Help** — ventilation can only pull the inside
  toward the outside. When the target lies on the far side of the outdoor air, opening
  moves away from it no matter how wide; the classic case is dehumidifying at night,
  when outdoor air is wetter than indoor. With this on, vents and exhaust/intake fans
  park closed instead of holding a partial opening all night.
- **Rest Heating and Cooling When Venting Can Reach the Target** — when outdoor air is
  already past the target, ventilation alone gets there and running HVAC alongside pays
  for what the outside would do for free. Three conditions must all hold: the outdoor
  value is past the target by more than the tolerance, *every* controlled variable is,
  and the vents still have headroom (the last cycle's widest opening below 90 %). If the
  target is still not reached after **15 minutes**, everything is handed back to heating
  and cooling — the prediction was wrong.
- **Keep Vents Closed While Heating or Cooling Runs** — venting against a running unit
  throws that heat or cold straight outside. In a season where outdoor air could help
  toward the target, this throws that help away too.

Detection of a running unit needs **evidence**, and there are only two sources: this
coordinator commands the unit itself, or you point the signal field at a measurement
that rises when the unit runs. Indoor temperature is deliberately **not** used to guess.
It was tested against 30 days of real data from a house with no cooler installed: under
300 W/m² or more of sun the indoor-to-outdoor difference had a median of +0.03 °C and a
minimum of −4.22 °C, so "indoor cooler than outdoor means cooling is on" misfired on
13 % of daytime samples even with a 1.5 °C margin.

| Field (shown when the interlock is on) | Default | Description |
|-------|---------|-------------|
| Heating / Cooling Running Signal | (none) | Only for units this coordinator does not switch itself. Pick any measurement that goes up when it runs — smart-plug watts, clamp-meter amps, an auxiliary contact as on/off. Leave empty if this coordinator commands the unit directly. |
| Running Signal Threshold | 0.5 | At or above this value the signal counts as running. Leave 0.5 for an on/off contact; for watts or amps set it above the unit's standby draw. |

If the signal has no freshness limit of its own, it is judged by its own measurement
period (×2, floor 300 s). An expired signal counts as *not running*, and that is logged.

**Night closing** exists because humidity rises and dew forms at night: an opening that
looked useful at dusk can leave the crop wet by morning. Its sub-settings appear only
once the toggle is on.

| Field (shown when Close at Night is on) | Default | Description |
|-------|---------|-------------|
| Night Starts At | Sunset to sunrise | Whether night is measured from sunset to sunrise, or by fixed clock times. |
| Close Before Sunset (min) | 0 | Start closing this many minutes before sunset. Negative values are discarded — a delay after sunset is exactly what this option removes. |
| Night Start / Night End (HH:MM) | 18:00 / 06:00 | Used only when night is measured by fixed clock times. |

Three guarantees hold: **safety gates win** (a summer night's heat still opens the
vents), the hard temperature/humidity limits break the parking, and if no coordinates
are available to compute solar time, nothing is parked at all. Times are read in the
facility's local timezone, not the server's. On the facility popup, a device parked by
this option reads *Closed for the night — heating and cooling take over*, kept separate
from *Nothing this device can change right now*.

### Heating, Cooling and Misting { #settings-hvac }

| Field | Default | Description |
|-------|---------|-------------|
| Use Micro Sprinklers to Raise Humidity | On | Use the wetting-type misters for humidity too. Turn off when the same nozzles are your irrigation — a sprinkler sized for irrigation leaves a film of water on the leaves after even one short burst. |
| Enable Sunburn/Evening Protection | Off | Blocks wetting-type misting in strong light (droplets can lens sunlight onto leaves) and, optionally, before sunset. Independent of how often misting runs. |
| Misting Frequency | Frequent | How often the misting runs — the run time and the gap until the next run. |

Misting valves are almost always on/off, so there is no way to reduce the flow: the only
adjustable quantities are how long one run lasts and how long the next one waits. That
is what this scale sets.

| Step | Max Spray Duration (s) | Enforced Drying Interval (s) |
|------|-----------------------|------------------------------|
| Infrequent | 5 | 1200 |
| Moderate | 10 | 900 |
| Frequent | 20 | 600 |
| Very frequent | 30 | 450 |

Sunburn protection is a **separate** decision from frequency — the two were briefly
merged, which made "spray often but lock out in strong sun" impossible to express.

| Field (shown when protection is on) | Default | Description |
|-------|---------|-------------|
| Misting by Sunlight Level | 150–250 W/m² | A band with two handles: below the lower value misting runs freely, above the upper it stops, and in between it tapers off linearly. The gap keeps the mist from switching on and off as clouds pass. **Applies to leaf-wetting misting only** — fog-type misting runs in strong sun too. The estimated *indoor* level is used, so closing the shade screen relaxes the lockout. |
| Allow Misting Before Sunset | On | Turn off to leave the leaves dry overnight. The longer leaves stay wet, the higher the risk of gray mold and downy mildew. |
| Stop Misting Before Sunset (min) | 120 | How long before sunset misting stops. |
| Misting Water Source | Groundwater (untreated) | Untreated groundwater is usually hard and cold: drying droplets leave mineral spots and can chill a sunlit leaf. Choosing it lowers the lockout/release thresholds automatically (to at most 150/100 W/m²). |

Even with protection off, a wetting-type mister is dosed in pulses rather than modulated
continuously — 30 s maximum on, 180 s minimum off by default — because continuous
modulation never lets the leaves dry.

### Light and Shading { #settings-light }

| Field | Default | Description |
|-------|---------|-------------|
| Shading and Supplemental Light | 0–800 W/m² | Two reference lines, not a range to stay inside. Darker than the band: supplemental lights come on and the shade screen opens. Brighter: the shade screen closes. Inside the band nothing happens. |

Either end can be switched off, and off means different things at the two ends: the
lower handle at 0 is *no supplemental light*, and the upper handle turned off is
*no shading*. If the facility has no shade screen or no supplemental lighting
registered, the screen says so rather than offering a handle that does nothing.

The underlying values are **Min Light Threshold (Supplemental)** (default 0) and
**Max Light Threshold** (default 800), both visible under [Advanced].

Two related properties are **not** on this screen:

- **Shade cloth transmittance** belongs to the facility, under the shade curtain in the
  facility editor. It is used only when there is no indoor light sensor: indoor light is
  then estimated from outdoor irradiance and the screen position. An unset or
  out-of-range value falls back to 0.50, and a facility that declares *no* shade curtain
  uses 1.0. A single screen whose cloth differs can still override it in its own Action.
- **The light saturation point** is derived from the crop's `K_L` in the program, not
  from the shading threshold. When those two were the same field, lowering the shading
  threshold made the photosynthesis model conclude that light was already sufficient —
  two coordinators set to 250 never once saw a light limitation while measured
  irradiance was 542 and 650 W/m². With no `K_L`, the system default of 600 W/m² is used.

### Advanced Settings { #settings-advanced }

This group is folded by default and is for engineers testing the function, not for
growers.

| Field | Default | Description |
|-------|---------|-------------|
| Max Sensor Age (seconds) | 0 | Reject sensor readings older than this. **0 means "not set", not "no limit"** — each sensor is then judged by its own update interval (×2). A fixed number that is shorter than a source's period can never be satisfied: an outdoor station publishing every 300 s under a 120 s limit reported zero valid channels for a full day. |
| Enable Photosynthesis-Oriented Control | Off | Each cycle, the Big-Leaf model identifies the current limiting factor (light / CO₂ / temperature / VPD) and raises that variable's priority. Requires a light sensor; the crop constants come from the plot's program. |
| Reference Plot (optional) | (empty) | Which plot this coordinator follows when more than one is growing in its scope. Leave empty when there is only one. |
| T Weight (0–1) | 0.6 | Fraction of a VPD adjustment carried out via temperature (the rest via humidity). |
| VPD Priority | 1.2 | Processing-order weight — higher is processed first. |
| CO₂ Priority | 0.8 | The same weight for CO₂, lower than VPD because enrichment is secondary. |
| Enable DLI / GDD Tracker | Off | Tracks daily light integral and growing degree-days, rolling over at facility-local midnight. Light is converted to PPFD by sensor unit. Targets come from the plot's program; requires a light sensor for DLI. |

#### Effect Calibration { #settings-calibration }

| Field | Default | Description |
|-------|---------|-------------|
| Effect Engine | Legacy | `Legacy`: built-in K_* constants (default, safe). `Shadow`: runs the grey-box model in parallel for logging only — no control change. `Grey-box`: physics-model control (with MPC look-ahead when a forecast is available). Recommended flow: Shadow first, then Grey-box. Change only while testing. |
| Enable RLS Calibration | Off | Learns per-actuator effect coefficients (K_*) from sensor response. Needs several days to converge; falls back to built-in defaults until then. |
| Enable Active Probing | Off | Periodically perturbs one actuator by ±10 % to improve calibration identifiability. Only triggers when load is low and no safety gate is active. Requires RLS Calibration. |
| Probe Interval (seconds) | 3600 | Minimum time between probing events. Steps: Often (1800) / Standard (3600) / Rare (10800). |

#### Forecast Feedforward { #settings-forecast }

| Field | Default | Description |
|-------|---------|-------------|
| Enable Forecast Feedforward | Off | Uses the short-term weather forecast to proactively shift temperature/humidity setpoints and inhibit ventilation before adverse weather arrives. |
| Forecast Lookahead (hours) | 3 | How far ahead to check. Steps: Short (1) / Standard (3) / Long (6). Longer gives earlier warning but may over-correct. |

> **Debug logging is no longer a separate option.** It duplicated the framework's own
> debug switch, and almost everything it guarded was written at DEBUG level, so on its
> own it produced nothing. The one switch in the function's Advanced settings now does
> both. Critical events — safety gate, dispatch failure, runtime-state error — are
> always recorded regardless.

---

## Registering Actuators { #actuators }

Actuators drawn in the linked facility are discovered automatically. Anything else is
registered with an **Environment Control** action on this function; add the action once
per device. Manual actions are merged with the facility-derived list.

| Action option | Default | Description |
|---------------|---------|-------------|
| Output Channel | — | The Output channel to control. |
| Actuator Type | — | Vent/Opening · Cooler · Heater · Fogger/Humidifier · CO₂ Injector · Shade Screen · Thermal Curtain · Supplemental Lighting · Circulation Fan · Exhaust Fan · Intake Fan. |
| Cost Index | 5.0 | Lower value = higher priority (1 = free natural ventilation, 10 = high-cost device). |
| On Time Window End | Do Nothing | What happens to this actuator when the Working Hours window ends: Do Nothing / Turn Off / Turn On / Set Open % (vents only). |
| End Open % | 0 | Target opening percentage at that moment (vents/openings only). |
| Cloth Transmittance Override (0–1, Shade only) | 0 | Only for this screen, when its cloth differs from the rest. Leave 0 to use the value set on the linked facility. |
| Effect Coefficient Override (K_*) | 0 | 0 = use default. Enter only when calibrating from measured data. |
| Full Stroke Time (s) | 0 | Seconds for this actuator to travel 0→100 %. Used to cap the command change per cycle so a physically impossible command is never sent. A vent motor taking 10 min → 600. |
| Min Repeat Interval (s) | 0 | Minimum seconds between repeated commands to this actuator even when the target has not changed. 0 = system default (600 s watchdog). Raise it for slow motorised actuators to extend relay life. |

### Automatic conversion by device type { #actuators-adapters }

A command is always computed as 0–100 %. The adapter is chosen from the Output module's
own metadata — no extra configuration:

| Output type | Adapter | Conversion |
|-------------|---------|------------|
| Paired actuator module | Paired | Forward/reverse pair conversion, internal to the module |
| `vol` / `volume` (volumetric pump) | Volumetric | `vol_ml = flow_lpm × on_sec / 60 × 1000` |
| `pwm` | PWM | duty = pct |
| `on_off` relay | Time-proportional | `on_sec = cycle_sec × pct/100`; OFF below 5 % |
| anything else | Value | 0–100 % passed straight through (DAC, stepper) |

| Command (%) | on/off relay (60 s cycle) | PWM | volumetric pump (1.5 L/min) |
|---:|---|---|---|
| 0 | OFF | duty 0 | OFF |
| 30 | ON for 18 s | duty 30 | 750 mL/cycle |
| 100 | ON for 60 s (continuous) | duty 100 | 2,500 mL/cycle |

A wetting-type mister is additionally wrapped in pulse dosing: one spray is cut at the
maximum on-time, and nothing sprays at all until the drying interval has passed.

Irrigation flow is aggregated from the facility drawing — every emitter under a layer is
summed into that actuator's `flow_lpm`, and the volumetric adapter and the fogger effect
model use it directly. The fallback order is per-actuator flow, then the facility total,
then 1.0 L/min.

### Safe default { #actuators-safe-default }

Each actuator has a safe position it moves to when a safety gate fires, on emergency
stop, or on an external `force_safe_state()` call. For actuators discovered from the
facility this follows the device kind: thermal curtains and shade screens park at
100 %, everything else at 0 (off).

---

## Methods (Setpoint Curves) { #methods-setpoint-curves }

A Method defines how a setpoint changes over time. Methods are attached to **target
items in the program**, not to this function — an item with a curve shows as
*Follows a curve* on the plot screen and cannot be overridden with a number.

- **Daily** — a setpoint per time of day (HH:MM)
- **Duration** — a setpoint per elapsed hour since start
- **Daily Bezier** — a smooth diurnal curve
- **Repeating** — a repeating pattern

Curves that progress by growth week are evaluated from the plot's start date, read at
midnight in the facility's local timezone, and from the elapsed weeks that the plot
screen and the plot journal also use.

**Example crop stage schedule (tomato):**

| Day | VPD target | CO₂ target |
|-----|-----------|-----------|
| Seeding–Day 7 | 0.6 kPa | 800 ppm |
| Day 8–21 | 0.8 kPa | 900 ppm |
| Day 22–42 | 1.0 kPa | 1000 ppm |
| Day 43+ | 1.3 kPa | 1000 ppm |

Methods prefixed with `SEED:` are seed presets and are read-only. Duplicate a preset
before editing.

---

## Safety Gates { #safety-gates }

Safety runs outside the L1–L3 coordination algorithm — a Pre-Gate checked every cycle
before L1–L3, and a Post-Gate that sanity-checks the L3 result before it is dispatched.
Once triggered, a Pre-Gate stays active for at least 300 s after its last trigger
(prevents rapid on/off flapping).

### Pre-Gate (checked before L1–L3) { #pre-gate-checked-before-l1l3 }

| Gate | Trigger condition | Action |
|------|--------------------|--------|
| Rain | Rain rate ≥ 0.5 mm/hr (fixed, not user-configurable) | Closes side/roof vents. Curtains/shades are interior equipment and are left alone. |
| Strong Wind | Wind speed ≥ **Strong Wind Threshold** (default 12 m/s) | Closes vents. If wind is the *only* active gate and both wind direction and vent azimuth are known, only windward vents (within ±60°) are forced closed — leeward vents keep running under normal control. |
| Heat Emergency | Outdoor T ≥ 45 °C **and** indoor T ≥ 35 °C (both fixed) | Fully opens vents, closes shade screens, forces coolers to 100 %. |
| Cold Emergency | Outdoor T ≤ −5 °C **and** indoor T ≤ 5 °C (both fixed) | Closes vents, closes thermal curtains, forces heaters to 100 %. |
| Internal Sensor Expired | No fresh indoor reading for > 120 s (fixed) | Every actuator returns to its safe default — control isn't possible without indoor data. |
| External Sensor Expired (alone) | No fresh outdoor reading for > 300 s, and no other gate is active | Partial gate: only vents/shade close conservatively; heater/cooler/fogger/CO₂/curtain keep running under normal L1–L3 control. |
| Misting Lockout | Strong light, or the evening cutoff, with Sunburn/Evening Protection on | Locks wetting-type misters only. A local lock: it does not freeze the rest of the facility and does not hold for 300 s. |

Rain, Heat and Cold thresholds are fixed in code — the **Wind** threshold is the only
one exposed as a function option. Multiple gates can be active at once (e.g. rain +
strong wind); vents then close unconditionally regardless of direction.

**A gated cycle is still a cycle.** When a gate ends the cycle early, a reduced summary
is written and the cycle is stamped, so the facility widget keeps showing what happened
instead of reporting the coordinator as unresponsive. The reduced summary deliberately
omits environment values that were not computed this cycle, and lists only the devices
the gate actually forced — a device that was not touched carries no command at all,
rather than 0 %.

### Post-Gate (checked after L3, before dispatch) { #post-gate-checked-after-l3-before-dispatch }

| Check | Action |
|-------|--------|
| Non-finite command (NaN/Inf) | Actuator falls back to its safe default. |
| Out-of-range command | Clamped to [0, 100]. |
| Manual Lock active | Overrides with the locked value. |
| Cooler and heater both ON at once | Not allowed — the cheaper one (lower cost index) keeps running, the other is forced to 0. |

### Emergency stop and safe state { #emergency-stop }

| Entry point | Description |
|-------------|-------------|
| Function Command → Emergency Stop | The UI button. |
| Conditional / Trigger → `force_safe_state` | Immediate entry from external automation. |
| RPC `output_off` | A bypass path that stops one individual Output. |

The next cycle is delayed 60 seconds after an emergency stop; actuators not moving
immediately afterwards is that delay, not a fault.

---

## Troubleshooting { #troubleshooting }

| Symptom | What to check |
|---------|---------------|
| The screen shows no targets | Is a plot growing in this facility/bay, does it have a program, and is that program reviewed? Without any of these the coordinator runs on its guide ranges only — this is normal, not a fault. |
| Targets exist but one axis is ignored | That target item may have no measurement selected, in which case it is *For reference* only. An item following a curve ignores any number entered on the plot. |
| An actuator doesn't move | Is the action registered and the Output active? Use **Reload Actuators** after changing actions or the facility. |
| An on/off relay turns on very briefly | The command is probably below 5 %, where the time-proportional adapter turns off. |
| A pump is always calculated at 1.0 L/min | Check that the facility's emitters have a non-zero flow and that the irrigation layer points at the pump's Output. |
| Vents don't close in high wind | Check the Strong Wind Threshold and the outdoor wind sensor binding on the facility. |
| Vents stay closed at night | Expected when **Close at Night** is on — the facility popup says *Closed for the night*. Hard temperature/humidity limits and safety gates still break it. |
| Outdoor readings are reported as missing | Max Sensor Age may be shorter than the source's own period. Leave it at 0 so each sensor is judged by its own interval. |
| Heating and cooling both ran | The post-gate forbids it; if the guide range is wider than the hard limits on an older configuration, the save screen warns rather than blocking. |
| A setting appears to be ignored | It may be conditional — the custom actuation period applies only to the *Custom* profile, and the night clock times only when night is measured by fixed times. The screen reports values entered but unused. |
| A facility change isn't taking effect | Run **Reload Actuators**, or deactivate and reactivate the function. |
| The watchdog reports a long outage | An intentional pause — outside the working-hours window, or with no actuators registered — is reported as a pause, not a fault. A genuine outage still warns. |

---

## AI Integration { #ai-integration }

The AI agent uses `analyze_control_performance` to diagnose control quality.

```
vpd_rmse         → VPD tracking error (lower is better)
oscillation_index → Control oscillation index (lower is more stable)
assessment       → "good" / "moderate" / "poor"
```

Based on diagnostics, `suggest_setpoint_adjustment` proposes a target adjustment. A
suggestion is advice only — the target itself lives on the plot's stage plan, so
applying it means editing that stage target on the plot screen, or, for a
Method-curve target, calling `update_method_point` (with user approval) to
change the relevant curve point.

---

## Related Pages { #related-pages }

- [AI Overview](overview.md)
- [Functions Guide](../Functions.md)
- [Methods Guide](../Methods.md)
