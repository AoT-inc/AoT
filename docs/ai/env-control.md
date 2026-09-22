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

### Day/night temperature and humidity guide the ranges { #stage-guide }

VPD stays the primary target. The stage's **Day temp**, **Night temp** and **Humidity**
are not targets — they keep VPD from being reached with a combination that is too hot
and humid or too cold and dry. Each cycle the coordinator replaces its guide ranges with:

| | Range |
|---|---|
| Temperature | stage Day temp (between sunrise and sunset at the facility's location) or Night temp, **± 5 °C** |
| Humidity | stage Humidity **± 10 %** |

- The width is fixed and not a programme setting — cultivation guides almost always give
  an average, not a day/night spread.
- A stage without the value, or a facility whose location is unknown (no sunrise/sunset),
  leaves the function's own guide range in charge for that quantity.
- The hard limits (`Min/Max Temperature`, `Min/Max Humidity`) still apply last.
- Everything that reads the guide range follows it: the temperature/humidity that VPD is
  split into, the mid-point used when there is no VPD target, forecast feedforward, and
  the ventilation temperature ceiling.
- The range actually used is shown as **Guide range** under the plot in the function's
  settings.

The coordinator has **no end-date option of its own**. Whether growing continues is the
plot's business. A date kept in the function could leave the facility stopped even after a
new crop was planted.

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
| Limiting factor | Which of light, CO₂, temperature and water (VPD) is holding photosynthesis back |
| Trend | Whether the value is moving toward the target |

When there is a VPD target and VPD can be measured, temperature and humidity are
demoted to *constraints* — the range VPD is decomposed into, and the lines that must
not be crossed. This function is not a thermostat.

### L3 — Coordinator (actuator command) { #l3-coordinator-actuator-command }

Each device gets a 0–100 % command from a **position-form PI** controller. It differs
from the textbook PI in three ways:

- **The integral is not accumulated error but the device's remembered equilibrium
  opening (%)**, always held within 0–100. When the deviation is small the integral
  stays put, so the device holds its last position.
- **A device that affects several axes combines them into one error.** A vent, for
  example, moves temperature, humidity and CO₂. Each axis's deviation is divided by its
  proportional band (tolerance × 6) so they share one scale, then averaged with the
  weight *priority × how strongly this device moves that axis*.
- **Within half the tolerance is a rest zone (dead zone).** Outside it, the dead zone is
  subtracted rather than switched on, so the command does not jump at the boundary.

```
e      = Σ(priority × effect × deviation/band) / Σ(priority × effect)
e_eff  = e minus the dead zone (tolerance × 0.5)
I      = clamp(I + 0.2 × e_eff, 0, 100)          # remembered equilibrium opening
cmd    = clamp(1.0 × e_eff × 100 + I, 0, 100)
```

- **Devices are settled in cost-index order** (cheapest first). Within a domain, each
  later device sees only the deviation left after the effect of those before it — this
  is load sharing.
- **A device that cannot help rests.** If running it at 100 % would move the variable by
  less than 2.5 % of the proportional band (for example ventilation with almost no
  indoor/outdoor difference), or it is parked, it moves toward its safe position,
  keeping 60 % of the remaining distance each cycle.
- **Anti-windup.** At the 100 % rail the overshoot is fed back into the integral; at the
  0 % rail that cycle's integration is frozen. If a device stays pinned to a rail, its
  integral is eased toward the actual opening.
- **Rate limit.** A command moves at most 20 percentage points per cycle; if the Action
  sets a full stroke time and the device can physically move less than that, the smaller
  value is used. Curtains and shade screens are exempt because they open or close in one
  motion. Commands below 5 % are sent as 0.

**Temperature ceiling in VPD mode.** When VPD is controlled directly, temperature is not
a control target — left alone, nothing would open the vents as the house heats up. So
when the temperature expected at the next decision (current + rate of rise × period)
comes within 1 °C of the guide ceiling, a temperature term is added for the ventilation
devices, weighted more the further it goes over. At the **Max Temperature** hard limit
the term also applies to coolers, and terms from other axes that oppose cooling are
dropped. It is still a PI proportional to the deviation and forces nothing to 100 % —
when outdoor air is hotter, the vents move toward closing instead.

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

If the drawing does not say which form an opening is, ridge and side vents use the same
model (no correction).

---

## Function Configuration { #function-configuration }

Navigate to `Functions → Integrated Environment Control` in the AoT UI. Actuators
themselves are registered separately (see [Registering Actuators](#actuators)) or
auto-discovered from the linked facility.

### Reading the settings screen { #settings-screen }

Five things are worth knowing before reading the tables below.

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
question — what range to grow in. Dragging a handle moves the matching never-cross line
with it by a fixed margin (±5 °C, ±5 %RH); if you never drag, the hard limits stay at
their factory values (5–35 °C, 30–90 %). The band cannot put a hard limit inside the
guide range, so "grow at 12–32 °C but never exceed 30 °C" cannot be expressed — that
combination is what sets a heater and a cooler against each other. If you type numbers
under [Advanced] that do this anyway, the coordinator narrows the guide range to fit
inside the hard limits and logs that it did.

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
outside the window, target tracking (L1–L3) stops **entirely**, heating and cooling
included. Protection continues:

- The [Pre-Gate safety checks](#pre-gate-checked-before-l1l3) (rain, strong wind, heat and
  cold emergencies and so on) are evaluated every cycle, and a gate that fires sends its
  forced commands. The partial gate that closes only the windward vents in strong wind
  works the same way.
- The **protective side** of the temperature/humidity hard limits still acts. If the
  indoor temperature drops below the minimum, for example, vents and thermal curtains
  close and cooling is blocked. Hard limits never drive a device (they do not switch the
  heater on), so this does not conflict with "stopped". Light limits are not used outside
  the window, because the minimum-light response switches grow lights on.
- Every device that received none of these protective commands gets its end behaviour. The window is judged
in the facility's local time, falling back to server time when the facility's timezone
is unknown.

| Field | Default | Description |
|-------|---------|-------------|
| Enable Time Window | Off | When enabled, target tracking only runs between Start and End. |
| Start Time (HH:MM) | 06:00 | When the coordinator starts working each day. |
| End Time (HH:MM) | 20:00 | When it stops. What each device does outside the window is set in its Action (On Time Window End). |
| Photoperiod Method | (none) | Sets the window from a day-length curve instead of fixed times. Careful: a short day length means the coordinator runs only for those hours, so nothing is heated overnight. |
| Photoperiod Anchor (HH:MM) | 12:00 | Solar-noon equivalent — the window is centred on this time. |

### Target and Temperament { #settings-target }

| Field | Default | Description |
|-------|---------|-------------|
| Temperature Range | 12–32 °C | The range to grow in. Past a limit, control stops whatever pushes the wrong way — too warm: heating off and the shade screen drawn; too cold: cooling off, vents and thermal curtain closed. It does not slam anything to full. |
| Humidity Range | 40–85 % | Same rule for humidity — too damp: misting off; too dry: exhaust fans off. |
| CO₂ Tolerance (ppm) | 100 | Within half this value of the target, CO₂ injection is left as it is. The value also sets how strongly control responds: at six times this value off target, it responds fully ([L3](#l3-coordinator-actuator-command)). Typical: 50–150 ppm. |
| Control Temperament | (Custom) | How hard the system chases the target. One step sets the cycle period, the vent actuation profile, the VPD tolerance and both emergency thresholds together. A newly added function's factory values match no step, so the control reads *Custom* until you pick one. |

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
  and the vents still have headroom (the last cycle's widest opening below 90 %). When
  outdoor air can cover only part of the way to the target, heating and cooling work
  only on what is left. If the target is still not reached after **15 minutes**,
  everything is handed back to heating and cooling — the prediction was wrong. While
  rain or wind readings are lost and the vents cannot open further, this judgement is
  switched off entirely — heating and cooling must not back off counting on a vent that
  cannot open.
- **Keep Vents Closed While Heating or Cooling Runs** — venting against a running unit
  throws that heat or cold straight outside. In a season where outdoor air could help
  toward the target, this throws that help away too.

Detection of a running unit needs **evidence**, and there are only two sources: this
coordinator commands the unit itself, or you point the signal field at a measurement
that rises when the unit runs. Indoor temperature is deliberately **not** used to guess.
On a sunny day a house can be cooler inside than outside with no cooler at all, so
"indoor cooler than outdoor means cooling is on" is often wrong even with a margin.

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

Sunburn protection is a **separate** decision from frequency — keeping them apart is what
lets you ask for "spray often but lock out in strong sun".

| Field (shown when protection is on) | Default | Description |
|-------|---------|-------------|
| Misting by Sunlight Level | 150–250 W/m² | A band with two handles: below the lower value misting runs freely, above the upper it stops, and in between it tapers off linearly. The gap keeps the mist from switching on and off as clouds pass. **Applies to leaf-wetting misting only** — fog-type misting runs in strong sun too. The estimated *indoor* level is used, so closing the shade screen relaxes the lockout. With the default water source (groundwater) the values actually used are lowered to 100–150 W/m². |
| Allow Misting Before Sunset | On | Turn off to leave the leaves dry overnight. The longer leaves stay wet, the higher the risk of gray mold and downy mildew. |
| Stop Misting Before Sunset (min) | 120 | How long before sunset misting stops. |
| Misting Water Source | Groundwater (untreated) | Untreated groundwater is usually hard and cold: drying droplets leave mineral spots and can chill a sunlit leaf. While it is selected (the default), the lockout/release thresholds are lowered automatically (to at most 150/100 W/m²). |

Whether or not protection is on, a wetting-type mister is dosed in pulses rather than
modulated continuously, because continuous modulation never lets the leaves dry. The run
time and interval come from the Misting Frequency scale (factory setting *Frequent*:
20 s maximum on, 600 s drying interval); only when those values are empty does it fall
back to 30 s / 180 s.

Wetting-type misting is also locked well before the **Max Humidity** hard limit. It is
locked when humidity rises above this cycle's humidity reference (the humidity split out
of the VPD target, kept inside the guide range) **plus 5 %**, and also whenever humidity
is unknown — so already-wet air does not wet the leaves further. Fog-type (high-pressure)
misting is not affected.

### Light and Shading { #settings-light }

| Field | Default | Description |
|-------|---------|-------------|
| Shading and Supplemental Light | 0–800 W/m² | Two reference lines, not a range to stay inside. Darker than the band: supplemental lights come on and the shade screen opens. Brighter: the shade screen closes. Inside the band nothing happens. The reference is **the light the crop actually receives** — outdoor irradiance with the covering and shade screen transmittance applied. |

Either end can be switched off, and off means different things at the two ends: the
lower handle at 0 is *no supplemental light*, and the upper handle turned off is
*no shading*. If the facility has no shade screen or no supplemental lighting
registered, the screen says so rather than offering a handle that does nothing.

The underlying values are **Min Light Threshold (Supplemental)** (default 0) and
**Max Light Threshold** (default 800), both visible under [Advanced].

Three related values are **not** on this screen:

- **Shade cloth transmittance** belongs to the facility, under the shade curtain in the
  facility editor. It is used only when there is no indoor light sensor: indoor light is
  then estimated from outdoor irradiance and the screen position. An unset or
  out-of-range value falls back to 0.50, and a facility that declares *no* shade curtain
  uses 1.0. A single screen whose cloth differs can still override it in its own Action.
- **Covering transmittance** comes automatically from the envelope material (glass 0.85 ·
  double film 0.78 · non-woven 0.50, and so on). A roof always cuts light even without a
  shade screen, so it is multiplied into the indoor light estimate. The
  light thresholds are therefore **indoor** values. The same 250 means nearly twice as much
  light for the crop in a glasshouse as under non-woven cover.
- **The light saturation point** is derived from the crop's `K_L` in the program, not
  from the shading threshold. If the two were one value, lowering the shading threshold
  would make the photosynthesis model conclude that light is already sufficient, and it
  would miss light limitation even under strong sun. With no `K_L`, the system default of 600 W/m² is used.

### Advanced Settings { #settings-advanced }

This group is folded by default and is for engineers testing the function, not for
growers.

| Field | Default | Description |
|-------|---------|-------------|
| Max Sensor Age (seconds) | 0 | Reject sensor readings older than this. If a sensor (Input) has its own max age set, that value takes precedence over this option. **0 means "not set", not "no limit"** — each sensor is then judged by its own update interval × 2 (at least 300 s). A fixed number shorter than a source's period can never be satisfied: an outdoor station publishing every 300 s under a 120 s limit never has a valid reading. |
| Enable Photosynthesis-Oriented Control | Off | Each cycle, the Big-Leaf model identifies the current limiting factor (light / CO₂ / temperature / VPD) and raises that variable's priority. Requires a light sensor; the crop constants come from the plot's program. |
| Reference Plot (optional) | (empty) | Which plot this coordinator follows when more than one is growing in its scope. Leave empty when there is only one. |
| T Weight (0–1) | 0.6 | When the VPD target is split into auxiliary temperature and humidity targets, the share given to temperature (the rest goes to humidity). When VPD can be measured, VPD itself is what is controlled; this value only shapes the auxiliary targets — the never-cross lines and the reference for the wetting-mist lock. |
| VPD Priority | 1.2 | The weight used when a device that affects several axes combines their deviations — higher means this axis counts more in the command. The order in which devices are settled is set by cost index, not by priority ([L3](#l3-coordinator-actuator-command)). |
| CO₂ Priority | 0.8 | The same weight for CO₂, lower than VPD because enrichment is secondary. |
| Enable DLI / GDD Tracker | Off | Tracks daily light integral and growing degree-days, rolling over at facility-local midnight. Light is converted to PPFD by sensor unit. Targets come from the plot's program; requires a light sensor for DLI. |

#### Effect Calibration { #settings-calibration }

| Field | Default | Description |
|-------|---------|-------------|
| Effect Engine | Legacy | `Legacy`: built-in K_* constants (default, safe). `Shadow`: runs the grey-box model in parallel for logging only — no control change. `Grey-box`: physics-model control. Each cycle it tries MPC (an optimisation that looks several steps ahead) first, then falls back to the physics-model PI, then to Legacy. MPC assumes outdoor conditions stay at their current values; it does not use the forecast. Recommended flow: Shadow first, then Grey-box. Change only while testing. |
| Enable RLS Calibration | Off | Learns per-actuator effect coefficients (K_*) from sensor response. Needs several days to converge; falls back to built-in defaults until then. |
| Enable Active Probing | Off | Periodically perturbs one actuator by ±10 % to improve calibration identifiability. Only triggers when load is low and no safety gate is active. Requires RLS Calibration. |
| Probe Interval (seconds) | 3600 | Minimum time between probing events. Steps: Often (1800) / Standard (3600) / Rare (10800). |

#### Forecast Feedforward { #settings-forecast }

| Field | Default | Description |
|-------|---------|-------------|
| Enable Forecast Feedforward | Off | Uses the short-term weather forecast to proactively shift temperature/humidity setpoints and inhibit ventilation before adverse weather arrives. |
| Forecast Lookahead (hours) | 3 | How far ahead to check. Steps: Short (1) / Standard (3) / Long (6). Longer gives earlier warning but may over-correct. When the facility has its own forecast source linked, that source's forecast is used as is and this value is not used. |

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
| 30 | ON for 18 s | duty 30 | 450 mL/cycle |
| 100 | ON for 60 s (continuous) | duty 100 | 1,500 mL/cycle |

A wetting-type mister is additionally wrapped in pulse dosing: one spray is cut at the
maximum on-time, and nothing sprays at all until the drying interval has passed.

Irrigation flow is aggregated from the facility drawing — every emitter under a layer is
summed into that actuator's `flow_lpm`, and the volumetric adapter and the fogger effect
model use it directly. The fallback order is per-actuator flow, then the facility total,
then 1.0 L/min.

### Axes without a measurement, axes without a device { #actuators-missing }

Every facility has different equipment. An axis that can be measured but not moved, and
one that can be moved but not measured, are both normal configurations. The coordinator
looks at the combination and adapts on its own.

| Situation | What the coordinator does |
|-----------|---------------------------|
| Measured, but no device moves that axis | The value is **for reference**. It leaves control (its target is replaced by the outdoor value when one is available) but is still used for the photosynthesis judgement and other axes' calculations. If it stays off target, the facility popup says *No device can move this*. |
| Only one direction exists (a heater but no cooler) | Normal. The device works when demand is in its direction and rests at 0 % otherwise. |
| A device exists, but that axis cannot be measured | If another axis the device moves can be measured, it keeps controlling through that axis (for example a vent where humidity is unknown but temperature is measured). Only when **none** of the axes it moves can be measured does it **hold where it is**. Moving without knowing the deviation would use equipment without evidence, and closing or opening is a decision too. |
| Indoor temperature or humidity cannot be measured | That axis leaves control entirely. A missing value is never invented as 0 — that would read as "0 °C indoors" and drive the heating to full. Leaf-wetting misting is locked while humidity is unknown. |

The **Can adjust** line at the top of the function settings shows this combination as one
word per axis (temperature, humidity, VPD, CO₂, light). The coordinator computes it from
the equipment and the values measured in the latest cycle; hover over a word to see the
devices that move that axis.

| Shown | Meaning |
|-------|---------|
| both ways | Measured, with devices that raise and devices that lower it. |
| raise only / lower only | Measured, with devices in one direction only. |
| watch only | Measured, but nothing can move it (reference value). |
| no sensor | A device moves this axis directly, but it cannot be measured. |

An axis with neither devices nor a sensor is not shown. An axis that is moved only **as a
side effect** — a vent lowering CO₂ a little, for example — is not shown either when it has
no sensor. VPD takes devices on both temperature and humidity into account: humidifying
mist lowers VPD, and ventilation raises it when the outside air is drier. For now this line
is **display only**; control follows the rules in the table above.

**The safety gates follow the same rule.** When indoor values are lost, the gate names
that fact on the screen and in the log, but **creates no forced command.** Driving
every device to its safe default (vents closed, screens retracted) would move equipment
precisely because there is no evidence. This is the same judgement as for
lost outdoor values, and control does not stop as a whole either: axes that can still be
measured, such as CO₂ or light, keep being controlled.

Risks that can be judged **from outdoor data alone**, such as rain and wind, are still
guarded. Heat and cold emergencies, on the other hand, are not judged while indoor
temperature is unknown — those gates drive every device one way, so they must only fire
on firm evidence.

The health check reports mismatched combinations as well:

```bash
python3 -m aot.scripts.check_env_coordinator_health
```

It reports under **configuration check** a target with no measurement, a target with no
device, and a device that cannot measure any of the axes it moves. An axis that has a
measurement but neither a target nor a device is not reported — that is exactly what a
reference value is.

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
| Strong Wind | Wind speed ≥ **Strong Wind Threshold** (default 12 m/s) | Closes vents. If wind is the *only* active gate (no lost readings either), the wind direction is known, and **every** vent has an azimuth, only windward vents (within ±60°) are forced closed — leeward vents keep running under normal control. |
| Heat Emergency | Outdoor T ≥ 45 °C **and** indoor T ≥ 35 °C (both fixed) | Fully opens vents, closes shade screens, forces coolers to 100 %. |
| Cold Emergency | Outdoor T ≤ −5 °C **and** indoor T ≤ 5 °C (both fixed) | Closes vents, closes thermal curtains, forces heaters to 100 %. |
| Heat/cold cannot be judged | Indoor temperature unknown | The emergency gates **do not fire** — they drive every device one way, so they fire only on firm evidence. |
| Indoor values lost | Indoor temperature/humidity stop arriving (judged by each sensor's own freshness rule — there is no separate 120 s clock) | **Nothing is forced.** The deviation cannot be measured, so that axis leaves control and devices that lost their evidence hold where they are. Axes that can still be measured (CO₂, light) keep being controlled, and control resumes as soon as values return (no 300 s hold). |
| Outdoor Rain/Wind Lost | A rain or wind reading that used to arrive stops arriving (judged by each sensor's own freshness rule — no separate 300 s clock). A sensor the facility never had does not count. | If the last value was rain or strong wind, the Rain/Wind gate keeps the vents **closed** until a fresh reading says otherwise. Otherwise vents may hold or close but **never open further** — a stale "no rain" is not a reason to open. Exception: above your **Max Temperature** hard limit vents may still open. Shades and everything else keep normal control. |
| Misting Lockout | Strong light, or the evening cutoff, with Sunburn/Evening Protection on | Locks wetting-type misters only. A local lock: it does not freeze the rest of the facility and does not hold for 300 s. |

**Lost values are a constraint, not an emergency.** Indoor values lost and outdoor
rain/wind lost both create no forced command and no 300 s hold, and when only these two
are active, L1–L3 run normally. The rule is that equipment is not moved just because
evidence is missing; whether to move is decided axis by axis by the coordinator.

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
| Cooler and heater both ON at once (both above 5 %) | Not allowed. Checked **last**, after the hard-limit responses, and the side whose command has the stronger source wins — safety gate > manual lock > normal control. On a tie, the lower cost index wins; the other side is forced to 0. L3 also rests the side opposing the temperature demand in advance (the heater when too warm, the cooler when too cold), so this check is rarely reached. |

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
| Heating and cooling both ran | The interlock just before dispatch forbids it ([Post-Gate](#post-gate-checked-after-l3-before-dispatch)). A configuration whose guide range is wider than the hard limits is warned about at save time rather than blocked, and the coordinator narrows the guide range to fit inside the hard limits. |
| A setting appears to be ignored | It may be conditional — the custom actuation period applies only to the *Custom* profile, and the night clock times only when night is measured by fixed times. The screen reports values entered but unused. |
| Every device is holding still | Indoor measurements may have disappeared. When temperature or humidity cannot be measured, that axis leaves control, and a device with no measurable axis left **does nothing** — it neither closes nor opens. The facility popup says *Holding — cannot measure right now*, and the log records it once. Check the sensor connections and Max Sensor Age. |
| A device drawn on the map does not appear in control | It may be a kind that control does not handle (vents, shade screens, thermal curtains, heating/cooling, misting, CO₂, supplemental light, fans). Such equipment is left out of registration and that is logged once — change its kind in the facility editor to bring it in. |
| A facility change isn't taking effect | Run **Reload Actuators**, or deactivate and reactivate the function. |
| The watchdog reports a long outage | An intentional pause — outside the working-hours window, or with no actuators registered — is reported as a pause, not a fault. A genuine outage still warns. |

---

## AI Integration { #ai-integration }

The AI in AoT's chat, and an AI connected over MCP, use the following tools to look at
this coordinator. Every write tool goes through human approval.

| Tool | What it does |
|------|--------------|
| `get_control_state` | Read. Per coordinator: targets, tolerances, priorities, safety ranges and operating windows, plus the latest cycle's actually-applied targets, limiting factor, safety-gate status and each device's command with its reason. This is what to read before advising on control. |
| `get_cumulative_status` | Read. Daily DLI and GDD totals and the running deficit (when the DLI / GDD tracker is on). |
| `get_function_detail` | Read. The function's full configuration. |
| `modify_function_options` | Write. Changes this function's options and reloads it. |
| `activate_function` / `deactivate_function` | Write. Turns the function on or off. |

Targets live on the plot's stage plan, not in this function. To change one plot's
targets, edit them on the plot screen. The AI can also change stage targets with the
program editing tool (`modify_program`), but that applies to every plot using the
program.

---

## Related Pages { #related-pages }

- [AI Overview](overview.md)
- [Functions Guide](../Functions.md)
- [Methods Guide](../Methods.md)
