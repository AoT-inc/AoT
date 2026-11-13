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
| Stage Day temp · Night temp · Humidity | The [guide ranges](#stage-guide) for this cycle |
| DLI target · daily GDD target | The cumulative tracker |
| `T_base` | GDD accumulation |
| Plot start date | Elapsed weeks, which drive stage-based curves |
| Photosynthesis constants (`A_max`, `K_L`, `K_C`, `T_opt`, `T_sigma`, `VPD_half`) | The Big-Leaf model, and the light saturation point derived from `K_L` |

Targets are matched to a control axis by **measurement and shape**, not by the key
name — a user-named item such as "Indoor CO₂" still reaches CO₂ control as long as its
measurement is CO₂. An item with no measurement selected reaches no axis at all and is
shown as *For reference*.

### When there is no plot { #targets-no-plot }

The coordinator does **not** stop. With no plot, no program, an AI draft that has not
been reviewed, a program whose kind does not match the plot's, or no stage running
today, there are simply no targets: control keeps running inside its own guide ranges,
which is already the defined behaviour — an empty greenhouse still needs heating.

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

### Control basis — VPD direct / temperature first { #control-basis }

The default is **VPD direct**: the VPD target is followed as described above, and
temperature and humidity are guides. Setting **Control Basis** in the advanced settings to
**Temperature first** changes a coordinator as follows.

- **Temperature is the primary target.** It follows the stage day/night temperature (day and
  night from the facility's sunrise and sunset).
- **The humidity target comes from the VPD target** — the humidity that gives the VPD target
  at that temperature (for example about 66 % for VPD 1.0 at 24 °C), cut to the guide range.
- **VPD is a limit.** It is pushed back only when it falls 0.4 kPa below or rises 0.8 kPa
  above the target.
- Without a stage temperature, temperature is **not followed**, only kept inside the guide
  range.

Following VPD directly turns the same tolerance into ±9 % humidity at 8 °C but ±1.8 % at
35 °C, and at low temperature it can demand a humidity that cannot be reached. Temperature
first does not have that difference.

Whichever is chosen, the other one is computed every cycle as "the commands it would have
sent" and recorded (never used for control), so the two can be compared on the same
facility.

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

### Air VPD and leaf VPD — what the target is compared with { #leaf-vpd }

What drives transpiration is the difference between the inside of the leaf (saturated at
**leaf** temperature) and the surrounding air. The formula above is the **air VPD** — the
leaf taken to be at air temperature. The leaf VPD is

```
leaf VPD = SVP(T_leaf) − RH/100 × SVP(T_air)
```

A leaf cooler than the air has a lower VPD than the air VPD, a warmer one a higher VPD
(25 °C, 70 %: air 0.95 kPa; a leaf 1.5 °C cooler 0.68 kPa). For the crop, leaf VPD is what
counts and air VPD is a reference. Leaf temperature, however, is rarely measured, and the
coordinator's effect models, the split into temperature and humidity and the stage guides
all work in air VPD — so **the controlled quantity stays air VPD** and only the target
moves.

**VPD Target Applies To** (Advanced Settings) chooses:

| Setting | What happens |
|---|---|
| **Air VPD** (default) | The target is compared with air VPD from the filtered temperature and humidity — exactly as before. |
| **Leaf VPD** | The target is a leaf VPD. Each cycle it is turned into the air VPD that gives that leaf VPD at the measured leaf temperature: `air target = leaf target + SVP(T_air) − SVP(T_leaf)`. A leaf 1.5 °C cooler than 25 °C air raises a 0.80 kPa leaf target to about 1.07 kPa of air VPD. The tolerance is unchanged (kPa). |

Choose **Leaf VPD** when an infrared leaf or canopy temperature sensor is installed and
your targets are leaf VPD values (as most crop guides give them). Bind the sensor in
**Leaf Temperature Sensor**; without it the leaf setting does nothing but log an error once.

The leaf temperature is used only when it is fresh (judged by its own update interval, like
the indoor sensors), within physical range, not stuck on one value (the same
[stopped-sensor](#l2-situationreport-evaluation) windows as indoor temperature) and within
**10 °C of the air** — a larger gap means the sensor is looking at soil, structure or sky,
not leaves. It is lightly smoothed (a 0.3 °C flicker would otherwise move the target by about
0.06 kPa). When it cannot be used, **that cycle runs on the air basis** — the same number is
used as an air VPD target — and the change is logged once each way. **The leaf temperature is
never guessed from a fixed offset** (such as air − 1.5 °C): a sunlit leaf with closed stomata
is warmer than the air and a leaf under a clear night sky is cooler, so a fixed offset would
only rename an air target. If the leaf is so much warmer than the air that even saturated air
cannot bring its VPD down to the target, the air target stops at 0.1 kPa.

Binding the sensor is useful on the air basis too: leaf VPD is then recorded and given to the AI tools, and the
[facility widget](../geo/facility-widget.md#b-environment) shows it next to air VPD while the target is applied on the leaf basis. Cycles that skip
the target step (a safety gate, outside working hours) make no new judgement; once the last one
is more than three cycles old (at least 5 minutes) the widget stops showing it. While the sensor
is bound or the leaf basis is chosen, the coordinator records, every cycle and with or without
debug logging, channel 94 (0 air basis · 1 leaf basis · 2 leaf basis but no usable leaf
temperature, so air), channel 95 (leaf VPD, kPa) and channel 96 (the leaf target as set). On
the leaf basis the VPD target channel (3) holds the translated air target. The health check
reports the minutes spent on 2 — a person should look at the sensor. The AI tools (`get_control_state` and the AI summaries) report the same pair, labelled `vpd.air_kpa` and `vpd.leaf_kpa`; the leaf value is present only while the leaf temperature is measured.

> **Stored VPD values from earlier versions.** The automatic VPD channel of an input
> (*auto VPD*, leaf = air − 1.5 °C) and the **AoT VPD** function used to multiply the *air*
> humidity by the *leaf* saturation pressure, which overstated VPD for a cooler leaf (0.87
> instead of 0.68 kPa in the example above). They now use the formula above, so their stored
> values are about 0.06–0.4 kPa lower after the update. The coordinator never used them for control.

---

## env_coordinator Control Layers { #env_coordinator-control-layers }

### L1 — EnvTarget (setpoint) { #l1-envtarget-setpoint }

Resolves the targets described above into setpoints for this cycle. A target that
follows a Method is evaluated with the plot's elapsed weeks and the facility's local
timezone.

### L2 — SituationReport (evaluation) { #l2-situationreport-evaluation }

Evaluates current deviation, limiting factors, and trend.

Indoor temperature, humidity and VPD are **filtered for noise** first, so that a sensor
flicking between two display steps (0.1 °C, 1 %) does not move the vents. Exponential
smoothing is used, but when the reading moves 0.5 °C or 3 % away from the filtered value it
is treated as a real change and followed immediately. **The VPD that control uses is always
the air VPD computed from the filtered temperature and humidity.** A sensor's own VPD
channel is not used for control: some devices report a VPD based on an estimated leaf
temperature (air − 1.5 °C), which reads lower than the air VPD that the targets and the
temperature/humidity split are written for. The device's VPD stands in only when temperature
or humidity is lost and it is all that is left; the difference between the two is recorded.
**Safety gates and hard limits judge the raw readings**, so protection is never delayed by
the filter.

**Every reading gets a status.** For each axis that control reads — indoor temperature,
humidity, CO₂, VPD and light; outdoor temperature, humidity, wind, rain and sunlight — the
coordinator sorts what the sensors delivered into `valid`, `stale` (an old value past its
freshness limit), `missing` (no value at all), `outlier` (left out of the average because
the other sensors disagree), `out_of_range` or `frozen` (below), and the axis carries the
best status among its sensors. **Only the last two change what control does.** An impossible
value — humidity above 102 %, a temperature outside −40…70 °C, CO₂ outside 150–10,000 ppm
and so on — never enters the average or the control, so a sensor that reports 130 % humidity
counts as having no value; a stuck sensor is left out the same way. Humidity of 100–102 % is
a scale error and is used as 100 %, and a pyranometer's night reading down to −5 W/m² is
used as 0. The other statuses are only recorded. When an axis is left with no usable sensor,
[Axes without a measurement, axes without a device](#actuators-missing) applies. With debug
logging on, each axis is written to the `sensor_status` measurement, channels 80–89 (indoor
temperature, humidity, CO₂, VPD, light, then outdoor temperature, humidity, wind, rain,
sunlight) as 0 valid · 1 stale · 2 missing · 3 outlier · 4 out of range · 5 frozen; channel
90 holds where the controlling VPD came from (0 none · 1 computed from temperature and
humidity · 2 device) and channel 91 the device's VPD minus the controlling VPD, in kPa.

**A sensor whose value has stopped moving is set aside.** A mirror device or a gateway can
stop updating while still stamping every reading with the current time. The freshness check
then passes and the number looks plausible — a greenhouse at 46 °C reads as 30.7 °C and the
vents close. For each sensor, and for each of temperature, humidity and CO₂, the coordinator
therefore counts how long the value has stayed within the sensor's resolution (0.05 °C,
0.1 %, 1 ppm). When it has not changed for longer than a working sensor certainly would, and
at least six *different* readings have arrived, the sensor is treated like an impossible value
and left out of the average:

| Situation | Time without change |
|-----------|---------------------|
| Daylight (outdoor light above 100 W/m²) — temperature, humidity | 60 minutes |
| Night, but a device moved in the last 30 minutes — temperature, humidity | 2 hours |
| Quiet night — temperature, humidity | 3 hours |
| CO₂ | 2 hours |

Other healthy sensors on the axis keep controlling it. If the frozen sensor was the only one,
the axis counts as not measurable and the rules in [Axes without a measurement, axes without a device](#actuators-missing)
apply (equipment holds where it is). **The moment the value changes, the sensor is used
again.** A sensor that has only ever reported whole numbers — many humidity sensors do — gets
three times the time, because on a calm night the same whole number can last for hours
(measured: up to 4.5 hours). Humidity at 100 % is never counted. A slow device that
re-delivers the same reading between updates is not frozen either; only new readings count.
The count is kept in memory and starts over after a restart. Each switch is logged once, and
the health check lists the axis as `frozen`.

⚠ A device that writes a point every period and really stays on one value for the whole time
cannot be told from a frozen one — the cost is only that this one sensor leaves the average.
There is no per-device "reports only on change" setting to tell them apart.

| Evaluation item | Description |
|----------------|-------------|
| Deviation | `current value - target` |
| Limiting factor | Which of light, CO₂, temperature and water (VPD) is holding photosynthesis back |
| Trend | Whether the value is moving toward the target |

When there is a VPD target and VPD can be measured, temperature and humidity are
demoted to *constraints* — the range VPD is decomposed into, and the lines that must
not be crossed. This function is not a thermostat. If temperature or humidity is lost so that VPD cannot be computed, the cycle falls back to temperature/humidity control ([Axes without a measurement, axes without a device](#actuators-missing)).

While [Extreme Heat Protection](#heat-protect) is on, its mode is listed first — *Heat
Protection*, or *Emergency* in stage 2.

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
  indoor/outdoor difference), or it is parked (every mister, when [there is no water](#water-supply)), it moves toward its safe position,
  keeping 60 % of the remaining distance each cycle. A thermal curtain is the exception
  and **holds its position** — relaxing it to its safe position (open) would release the
  insulation at night as soon as the indoor/outdoor difference narrows. Holding is only for
  a night without heat demand: when the house needs its heat the curtain is closed instead
  ([night heat retention](#curtain-gap), reason 49). The judgement has
  hysteresis: a device that was judged able to help only rests once its effect falls below
  half of that threshold (1.25 %), so an effect hovering near 2.5 % does not make the vent
  open and close repeatedly (reason *primary* ↔ *no gradient*).
- **A suspected device is held.** An actuator whose sends keep failing, or a vent commanded hard for hours with no effect, is left where it stands, takes no new commands and adds nothing to the load-sharing ledger, so the rest of its domain takes over its share ([Suspected actuators](#actuators-suspected)).
- **In VPD-direct mode a heater never runs above the top of the temperature range.** There the only demand a heater receives is VPD, and after sunset the day VPD target falls slowly while the temperature range drops at once (22–32 → 12–22 °C). So the heater's output is cut linearly over the last 1 °C below the top of the guided range and is 0 at or above it — at once, not at the 20 %-per-cycle slew (reason 17). The hard minimum temperature (Min Temperature) still wins; with temperature as the control target this cap does not apply.
- **A vent about to be parked is not opened further.** In the 45 minutes before [night closing](#settings-ventilation) starts, a vent or fan may be closed but is not opened beyond its current opening for VPD, humidity or ordinary temperature reasons; the integral stops growing too (reason 48). The hard temperature/humidity limits, [Extreme Heat Protection](#heat-protect) and the condensation escape still open it.
- **In rain the vents keep a cap.** Under the [rain limit](#safety-gates) a side vent does not go above 30 % and a roof vent held for light forecast rain does not open beyond where it stands, whatever VPD, humidity, the sunshine floor, the [morning purge](#morning-purge) or [Extreme Heat Protection](#heat-protect) stage 1 ask for; the integral is held at the cap too, so the vent does not jump when the rain stops (reason 52).
- **In sunshine the vents keep a minimum opening.** When outdoor sunlight is 200 W/m² or more, indoor is above the crop's temperature line (target + tolerance — in VPD-direct mode never above the stage temperature + 1 °C) and it is not more than 1 °C hotter outside, VPD and humidity demands cannot close the vents below a floor of 15–80 % that grows with the excess (reason 51); the integral is held at it too. See [Venting the sun's heat](#solar-vent).
- **Without indoor readings, a sunny day still gets a small opening.** When the indoor temperature is lost but the outdoor reading is real, the sun is up, the outdoor air is at least 12 °C and outdoor temperature + 0.02 °C per W/m² is above the crop line, a vent that would hold for lack of a measurement is opened 5 points per cycle to 10–20 %, and after sunset a vent open that little is closed again at the same pace (reason 60). See [Indoor readings lost on a sunny day](#solar-vent-blind).
- **Holding keeps the opening that is actually delivered.** When a rule holds a vent where it stands (outdoor or indoor reading missing, ventilation futility about to take hold, the 45 minutes before night closing, "no further opening" for lost rain or wind readings, a vent that does not respond), the command is the last delivered opening divided by this cycle's delivery ratio (the wind-direction weighting). Sending the last opening unchanged applied the weighting again every cycle, so a "held" vent slowly closed — one recorded morning 20 → 16 → 13 → 12 → 7 → 0 % in 50 minutes under reason 21.
- **In the morning sun an over-humid house is aired a little.** When outdoor sunlight is 100 W/m² or more, indoor is in the over-humid zone and its dew point is at least 2 °C above the outdoor one, the vents get a minimum opening of 5–15 % instead of being parked as *outside too cold*, unless the house is far below the lower edge of the temperature target (reason 54). See [Morning purge](#morning-purge).
- **Thermal curtains stay open in the daytime.** The effect model knows only the curtain's
  heat exchange, not that it blocks light, so from sunrise to sunset at the facility's
  location the curtain stays open and is decided only at night. Safety gates such as extreme
  cold take precedence over this rule. A curtain that can stop part-way opens in steps at
  sunrise rather than all at once ([Thermal curtain — night gap and morning
  ramp](#curtain-gap)).
- **The shade screen follows the light.** Whether it may be used against heat and water
  stress is decided in one place from the light the crop would receive, and its moves are
  filtered so that it does not shuttle ([The shade screen against heat](#shade-heat)).
- **Curtains and shade screens are fully closed or fully open.** To move from the side it is
  on, the command must pass 60 % (to open) or 40 % (to close), so a command near 50 % does
  not swing it end to end. The log and the screen show the 0/100 actually sent. The one
  exception is a thermal curtain that can stop part-way: its night gap and morning ramp keep
  their stops (3 · 6 · 10 · 30 · 60 %), and what is logged is what is sent.
- **When the direction flips, it waits to see if the flip lasts.** A vent's effect on VPD
  is the sum of cooling and dry outdoor air working against each other, so when the two
  are close a few points of outdoor humidity flip the direction every cycle. The new
  direction is followed only once it has lasted at least 10 minutes (and two cycles);
  until then the device holds its position. The temperature term added as the indoor
  temperature reaches the guide ceiling also gains weight **gradually** with the excess,
  so hovering around that line does not step the vents up and down.
- **Side vents facing the wind open wider.** A side vent facing away from the wind is
  reduced to as little as 20 % of the command. Below 0.5 m/s this does not apply, and up
  to 3 m/s it strengthens gradually with wind pressure (speed²), so a light, shifting wind
  does not cut and restore the side vents from one cycle to the next.
- **It does not freeze past the target.** Even inside the deadzone, if the deviation keeps
  saying "less" for three cycles, the device backs off by keeping 60 % of its command each
  cycle. Thermal curtains and shade screens do the same: their effect is proportional to
  the opening, so reducing the command is what reduces the effect.
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
devices, weighted more the further it goes over. Once the term is on it stays until the
expected temperature falls a further 0.5 °C below that line, so a temperature sitting on
the line does not swing the vents between cooling and resting. At the **Max Temperature**
hard limit the term also applies to coolers, and terms from other axes that oppose cooling
are dropped. It is still a PI proportional to the deviation and forces nothing to 100 % —
when outdoor air is hotter, the vents move toward closing instead.

Below the line where the term switches off there is a **1.5 °C hold band**: vents the term
opened stay where they are (they may still open further, and night closing or other
parking still wins) and only move toward closing once the expected temperature falls below
the band. Without it, a house whose vents change the temperature by several degrees within
one cycle went open → switch off → close → reheat → open again about every 50 minutes.

While [Extreme Heat Protection](#heat-protect) is enabled, the ceiling is never above its
threshold — also outside protection — so ordinary control starts cooling just below the
threshold and protection only takes over when that is not enough. During protection the
ceiling is hard while the temperature is above the line; below it the term steps down the
same way as outside protection.

The derived ceiling **never exceeds the target temperature plus its tolerance.** With a 25 °C target and a
1 °C tolerance the temperature term starts at 26 °C even if the guide ceiling is 30 °C. Before, the term only
stood near the guide ceiling, so windows stayed shut on VPD alone while the house ran 2–5 °C over target.
If the target temperature is unknown, the guide ceiling is used as before.

---

## Actuator Domains { #domains }

Load sharing happens **within** a domain, and domains are separated by where the
energy ends up — not by how similar the devices look. The settings screen is grouped
along similar lines, except that supplemental lighting is set together with the
screens under Light and Shading.

| Domain | Devices | Nature |
|--------|---------|--------|
| Ventilation | Vents/openings, exhaust fan, intake fan | Can only push the inside toward the outside; neither a vent nor a fan moves it past the outdoor value, and a fan's effect follows its rated airflow over the length of the cycle |
| Heating, cooling and misting | Heater, cooler, fogger | Adds or removes directly, regardless of outdoor air |
| Screens | Shade screen, thermal curtain | Blocks incoming and outgoing radiation |
| Auxiliary | CO₂ injector, supplemental lighting, circulation fan | Each has its axis to itself, with nothing to share the load with. When vents are open, though, injected CO₂ leaves straight away, so the injection effect is reduced by the average vent opening (zero at 30 %) **and by the air the fans exchange** — a fan counts as an equivalent opening (20 air changes an hour = a fully open vent; zero when the fans reach 6 changes an hour, less when open windows leave them without pressure; exhaust and intake fans count the larger side, and a fan with no rated flow or house volume is not counted). If the effect becomes too small, the injector rests, even with the windows shut |

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
control is doing right now — each axis it is tracking as its current value against the
target (VPD, temperature, humidity, CO₂, light), the position of each device kind
(Vents, Heating, Cooling, Misting, Shade …), and how long ago the last decision was
made. A second line says what this facility can actually adjust on each axis: both ways,
raise only, lower only, watch only, or no sensor. Below it, a two-line summary names the
plot being followed, the stage it is in, and the targets in effect. States where nothing
can run are spelled out separately: no environment control linked to this facility,
control switched off (naming the coordinator that runs the facility instead, if there is
one), no decision for longer than this coordinator's own limit, and not having run a
cycle yet. Before a facility is picked the header stays empty — the picker is right
above it. If the plot ends within two weeks, one extra line says so.

**Settings are arranged in four layers, not by option type.**

| Layer | What | Shown |
|-------|------|-------|
| Connection | Facility, bay | Always |
| Commitments | Temperature/humidity ranges, extreme heat protection, CO₂ tolerance | Always |
| Strategy | Ventilation/HVAC teamwork, night closing, misting protection, use of the shade screen and thermal curtain | Always, as a toggle or a step scale |
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
under [Advanced] that do this anyway, saving warns you on the spot — naming the axis,
the two ranges, and the range targets will actually be built in — whenever one of that
axis's four values was part of what you just saved; the coordinator then narrows the
guide range to fit inside the hard limits and logs that it did.

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
| Reload Actuators | Re-reads the Actions table and this function's own settings, then rebuilds actuator profiles — no restart needed. |
| Run Now | Executes one coordination cycle immediately using current sensor readings. Ignored while an emergency stop is still holding control; the reply then says how many seconds remain. |
| Emergency Stop | Immediately sets all actuators to their safe default and pauses control for 60 s. |

After either of the first two, the next cycle is treated as urgent once, so vents may
move without waiting out their actuation profile interval.

### Facility Settings { #settings-facility }

| Field | Default | Description |
|-------|---------|-------------|
| Linked Facility | (none) | Which facility this coordinator runs. Actuators and sensors come from it — envelope, side/roof vents, curtains, fans, indoor and outdoor sensors. GIS metadata (azimuth, area, U-value) is attached to each actuator profile so wind direction and facility geometry can be considered. Without this, the remaining settings have nothing to act on. |
| Bay Scope (optional) | (empty) | Limits this coordinator to one bay. Only sensors and actuators inside that bay are used — a device that belongs to no single bay is left out, so it stays with the facility-wide coordinator — and facility volume, envelope and vent area are scaled to that bay's share of the combined width of all bays (by bay count instead, with a warning, when the widths are unknown). Leave blank for the whole facility; create one coordinator per bay to control several bays independently. A coordinator left blank steps around the bays that sibling coordinators on the same facility have already claimed, so one device never takes orders from two of them. This is a **dropdown** of the linked facility's bays — a saved value that no longer exists in the facility is kept and marked, rather than silently dropped; while it points at a bay that is not there, this coordinator takes on **no devices at all** instead of widening to the whole facility. |
| Devices under automatic control | (none excluded) | A folded box just under the facility settings lists every actuator of the linked facility with a toggle, except a device on an upper floor of a multi-floor facility model — this coordinator never controls those, so they are left off the list rather than shown and forced on (see [Facility — Plan Drawing](../geo/facility.md#plan-drawing)). Switching one off removes it from automatic control entirely — no commands, and the safety gates stop forcing it too, which is what a device under repair or held by hand needs. It is an exclusion list, so a device added to the facility later is controlled from the start. A device switched off that later disappears from the facility keeps its off state. If the list cannot be read, the box says so and the stored setting is left as it is rather than overwritten with an empty one. |

### Working Hours { #time-control }

Only the toggle is visible until it is switched on. This is a switch, not a schedule:
outside the window, target tracking (L1–L3) stops **entirely**, heating and cooling
included. Protection continues:

- The [Pre-Gate safety checks](#pre-gate-checked-before-l1l3) (rain, strong wind, cold
  emergency and so on) are evaluated every cycle, and a gate that fires sends its
  forced commands. The strong-wind stage 1 limit (reason 55, windward and roof vents
  closed, the rest capped) works the same way, and so does the [rain limit](#safety-gates) (reason 52): roof
  vents it closes stay closed, a capped side vent with no other command closes (there is
  no PI to pick a position under the cap), and a roof vent held for forecast rain stays
  where it is.
- The **protective side** of the temperature/humidity hard limits still acts. If the
  indoor temperature drops below the minimum, for example, vents and thermal curtains
  close and cooling is blocked. Hard limits never drive a device (they do not switch the
  heater on), so this does not conflict with "stopped". Light limits are not used outside
  the window, because the minimum-light response switches grow lights on.
- [Extreme Heat Protection](#heat-protect) still applies, directly: vents open only while
  it is cooler outside, shade drawn in the sun, coolers and circulation fans on, heating
  and misting off.
- Every device that received none of these protective commands gets its end behaviour. The window is judged
in the facility's local time, falling back to the farm's time zone when the facility's is unknown, and to
UTC only if that is unknown too.

| Field | Default | Description |
|-------|---------|-------------|
| Enable Time Window | Off | When enabled, target tracking only runs between Start and End. |
| Start Time (HH:MM) | 06:00 | When the coordinator starts working each day. Start and End must be entered as HH:MM; any other format is rejected when saving. |
| End Time (HH:MM) | 20:00 | When it stops. An end time earlier than the start time is read as a window that crosses midnight. What each device does outside the window is set in its Action (On Time Window End). |
| Photoperiod Method | (none) | Sets the window from a day-length curve instead of fixed times. Careful: a short day length means the coordinator runs only for those hours, so nothing is heated overnight. |
| Photoperiod Anchor (HH:MM) | 12:00 | Solar-noon equivalent — the window is centred on this time. |

### Target and Temperament { #settings-target }

| Field | Default | Description |
|-------|---------|-------------|
| Temperature Range | 12–32 °C | The range to grow in. Past a limit, control stops whatever pushes the wrong way — too warm: heating off and the shade screen drawn; too cold: cooling off, vents and thermal curtain closed. It does not slam anything to full. |
| Extreme Heat Protection | On | Above the threshold, keeping the crop out of heat stress comes before the target — shade drawn, heating off, circulation fans on, vents opened only while it is cooler outside, misting only while it can still cool ([Extreme Heat Protection](#heat-protect)). |
| Heat Protection Threshold (°C) | 30 | Average indoor temperature at which protection starts (20–45 °C). Set it to what the crop tolerates. Shown only while protection is on. |
| Humidity Range | 40–85 % | Same rule for humidity — too damp: misting off; too dry: exhaust and intake fans off together. |
| CO₂ Tolerance (ppm) | 100 | Within half this value of the target, CO₂ injection is left as it is. The value also sets how strongly control responds: at six times this value off target, it responds fully ([L3](#l3-coordinator-actuator-command)). Typical: 50–150 ppm. |
| Control Temperament | Standard | How hard the system chases the target. One step sets the cycle period, the vent actuation profile, the VPD tolerance and both emergency thresholds together. A newly added function's factory values are exactly the *Standard* step; change one of them by hand to a value that is on no step and the control reads *Custom*, with a line telling you to look under [Advanced]. |

Under [Advanced], each range band also shows the four numbers behind it
(`Guide T Min/Max`, `Min/Max Temperature`, and the humidity equivalents), Extreme Heat
Protection shows **Release Margin** (°C, default 1.5, 0.5–5 — protection ends only after
the temperature has stayed this far below the threshold for 10 minutes) and **Minimum Hold**
(minutes, default 20, 5–120), and Control Temperament shows its members:

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
Sensing and computation always run every cycle period, and curtains and shade screens are
unaffected (they open or close in one motion). A safety gate's forced command (closing
for rain or strong wind, for example) reaches **that device** immediately regardless;
vents that are not being forced keep this interval. The interval is skipped altogether
only when indoor temperature changes fast, or when a deviation exceeds the emergency
threshold **and is still widening** — merely staying far from the target is not an
emergency — for the one cycle right after the function is reloaded or told to run now,
and for the one cycle in which [Extreme Heat Protection](#heat-protect) goes
up a stage (staying in protection is not an emergency either).

### Ventilation { #settings-ventilation }

| Field | Default | Description |
|-------|---------|-------------|
| Ventilation and HVAC Teamwork | High performance | Keeps venting and HVAC from working against each other. Three steps, described below. |
| Close at Night | Off | Keeps the vents closed overnight and lets heating, cooling and drying carry the load. Only openings are parked; heating, cooling and dehumidification keep running. |
| Strong Wind Threshold (m/s) | 12 | 10-minute average wind at which every opening closes (or a measured gust at 1.5×). From 0.6× (or a measured gust at 0.9×) windward and roof vents close and the rest open only part way — see [Strong wind in two stages](#safety-gates). [Advanced] |

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
  rain or wind readings are lost and the vents cannot open further, or while rain has put
  a cap on them (reason 52), this judgement is switched off entirely — heating and cooling must not back off counting on a vent that
  cannot open. It is switched off as well while [Extreme Heat Protection](#heat-protect)
  is active — that is not a time to rest the cooling.
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

It lifts itself when staying closed becomes the greater risk: when a temperature or
humidity hard limit is crossed, and when **condensation is imminent and ventilation would
actually relieve it**. Imminent means the gap between indoor temperature and dew point is
under 2 °C; relieving means that mixing in a little outside air widens that gap. Cold,
humid outside air can cool the house into condensation, so dry outside air alone is not
a reason to open. Once lifted, parking returns when the gap recovers to 3 °C or
ventilation stops helping. With no outdoor readings it is not lifted — and neither with
readings that have *expired* (the last cached values are used then): an old "drier outside" is
not a reason to open, and the parking then closes the vent (reason 19). In one recorded night the
vents that dehumidified until the weather source went stale stayed 13–25 % for three hours.

The escape is **strict about vapor pressure.** The outdoor dew point must be at least 1.5 °C below the
indoor one (0.75 °C if already open) and mixing must widen the gap by at least 0.3 °C. A gap that
grows a little only because the mixed air is warmer does not open anything. Once lifted, the vent
still opens no further than 30 % under the [over-humid zone](#humid-zone) rules (the cap is lifted when the outdoor air is at about the same temperature or warmer and its dew point is more than 3 °C lower). It does not open while heating is demanded or when
the outdoor air is more than 8 °C colder than indoors. The same holds when indoors is at or below the
temperature baseline (target plus tolerance when temperature is the control target; the lower end of the guide range in direct VPD mode — the same line the [over-humid zone](#humid-zone) uses) and the outside air is more than 1 °C colder — temperature wins over dew point.
With a thermal curtain that can stop part-way, the curtain gap goes first and this escape waits until the gap is spent ([Thermal curtain — night gap and morning ramp](#curtain-gap)).

| Field (shown when Close at Night is on) | Default | Description |
|-------|---------|-------------|
| Night Starts At | Sunset to sunrise | Whether night is measured from sunset to sunrise, or by fixed clock times. |
| Close Before Sunset (min) | 0 | Start closing this many minutes before sunset. Negative values are discarded — a delay after sunset is exactly what this option removes. |
| Night Start / Night End (HH:MM) | 18:00 / 06:00 | Used only when night is measured by fixed clock times. |

Three guarantees hold: **safety gates win** (a summer night's heat still opens the
vents), the hard temperature/humidity limits break the parking, and if no coordinates
are available to compute solar time, nothing is parked at all. A fourth rule is not
specific to night closing: if the outdoor reading itself
is unavailable — no cache, only a synthetic fallback that assumes outdoor equals indoor
— the coordinator neither opens vents nor closes them on that guess; it holds them exactly where they are,
overriding the ventilation decisions this cycle's control rules made. Emergency safety gates (rain, wind) still win over this hold and can close vents.
Closing on a fabricated outdoor-equals-indoor guess could otherwise leave vents shut
through a hot day once the weather source dies.

**Not knowing is only a reason not to open.** While the outdoor reading is missing, three
closing moves still happen, because none of them rests on the missing reading: night closing
still closes (reason 19); the rain or wind limit from the last measured reading still holds
(reasons 52 and 55 — a vent above its cap comes down to it); and once the sun is down
(clear-sky sunshine below 50 W/m², which needs the facility's position) a vent open **10 % or
less** is closed to 0 (reason 58, which needs no night-closing option). The same goes when only
the rain or wind reading is lost (the vents are then "not opened further", and a small vent that
the control still wanted open used to stand there through a night of rain). A vent open wider is
left where it stands, and no vent is closed by daytime ignorance alone — a hot day would not
forgive that. The sunset move is skipped while a hard temperature or humidity limit wants
ventilation — and that gap was the problem in one recorded night: the side vents opened 25–30 %
to dehumidify (RH 91–95 % over the 90 % limit) and then stood at 13–25 % for three hours after
the weather source went stale, with rain unseen if it had started. So once the outdoor reading
(or the rain and wind reading) has been missing for **more than 30 minutes**, a vent that is
open at night only because of the hard humidity limit (or the night humidity/condensation
release of the night closing) is closed step by step: **5 percentage points per 10-minute cycle**
down to 0 (reason 58; the integral follows the command; a shorter cycle takes a proportionally
smaller step). Five points rather than halving because halving a 30 % vent drops it 15 points at
once and never quite reaches 0, while the fixed step is gentler on a wide opening and ends at 0.
Shorter outages change nothing (the weather source routinely skips up to half an hour), and so
do a hard temperature limit, Extreme Heat Protection and any daytime opening. The moment the
reading returns, normal control resumes — nothing stays latched. The 30-minute clock survives a
restart (it is kept with the other cycle memory, which expires after 30 minutes without a
cycle). Times are read in the facility's local timezone — falling back to the farm's timezone
when the facility's own cannot be determined — never the server's. On the facility popup, a device parked by
this option reads *Closed for the night — heating and cooling take over*, kept separate
from *Nothing this device can change right now*.

**Losing the indoor readings is the mirror case.** The vents hold where they stand (reason 21, at
the opening actually delivered), except that on a sunny day they get a small opening worked out
from the outdoor temperature and sunshine alone, closed again after sunset (reason 60 — [Indoor
readings lost on a sunny day](#solar-vent-blind)).

**Vents are not opened further just before closing.** For 45 minutes before the parking
starts (sunset minus *Close Before Sunset*, or the night start time), a vent or fan may
still be closed by the controller, but it is not opened beyond where it already stands for a
VPD, humidity or ordinary temperature reason. At dusk the indoor humidity rises while the
outdoor air stays drier, so venting looks useful for VPD — and ten minutes later the night
closing shuts the vent again. In one recorded evening the side vents opened
12 → 91 % between 16:48 and 17:49, then closed 70 → 0 % by 18:42. That swing costs motor
travel, drops the temperature just before dark and puts cold air on the seedlings. In the
window the opening is held at its previous value and the integral stops growing, so nothing
winds up and releases when the window ends. The facility popup reads *Held at its current
opening — the vents are about to close for the night* (reason 48). There is no ramp-down on
purpose: a house that really needs its vents is not closed ahead of schedule.

The hold is lifted for the same reasons that break the parking, and for heat: the hard
temperature limit (and the hard term of the temperature ceiling), the hard humidity limit,
[Extreme Heat Protection](#heat-protect), and the condensation escape above. Rain and wind
gates still close the vents. Where no solar time can be computed, there is no window. The 45
minutes are fixed, not an option. It applies to the rule-based control (Legacy and the
physical-model PI); the MPC does not apply it.

### Venting the sun's heat { #solar-vent }

A closed house in sunshine heats up within minutes: the sun warms the crop and the floor, and
the only way that heat leaves is with the air. Judged only by the current indoor–outdoor
difference, ventilation can look useless or harmful at exactly that moment — the outside air
is drier, so "opening raises VPD", and the indoor–outdoor temperature gap is only a degree or
so, so "venting has no driving force" (*no gradient*, reason 15). That small gap is often the
misters' own work: they cool the air they are kept running in. And evaporative cooling only
keeps working when the moist air is exchanged — misting, ventilation and shading go together.
Closing the vents to keep the humidity in is right only when there is no solar heat load
(night, overcast, cool weather).

So while the sun is up the vents get a **minimum opening**:

| Condition | Value |
|---|---|
| Sun | outdoor sunlight from 200 W/m² (released below 150). Without a reading, the clear-sky sunshine × how cloudy it has been over the last 30 minutes; with no sunlight sensor at all, half the clear-sky sunshine; without the facility's position, no judgement |
| Too warm | indoor above the *crop line* — the temperature target + tolerance when temperature is the control target; in VPD-direct mode the lower of the derived temperature target + tolerance and the crop line (below). Released 0.5 °C below that line — but for 30 minutes after it starts it stays at its minimum regardless of temperature (otherwise the vents cool the house past the release in one cycle, the sun reheats it once they close, and the minimum flips every 10 minutes) |
| Not hotter outside | outside no more than 1 °C warmer than inside (venting would bring heat in) |
| Minimum opening | 15 % just above the line, rising with the excess to 80 % at the [Extreme Heat Protection](#heat-protect) threshold (**Max Temperature** when protection is off), scaled by the sunshine (× 0.7 at 200 W/m², × 1 from 800 W/m²) |

VPD and humidity demands cannot close the vents below that opening; the humidity they would
have kept is supplied by misting (cooling and humidifying at once) and the
[shade screen](#shade-heat). The opening is held in the integral too, so the vents do not
snap shut when the rule releases — control continues from where they stand. (Lowering the minimum
step by step on release was tried and reverted: the controller pushed the vents back up against the
falling minimum, and the vents reversed more often than with a direct release.) Above the
protection threshold the minimum stays at its top value, so the handover to Extreme Heat
Protection has no step. It applies to the roof and side vents; fans get it only when there
are no vents (fans cost power, vents do not). The facility popup reads *Kept open to let the
sun's heat out — sunny and above the temperature target* (reason 51); the log notes when it
starts and stops.

**"Too warm" is drawn from the crop's temperature.** In VPD-direct mode the derived temperature
target is a temperature moved to reach the VPD — on a humid morning it sits above the indoor
temperature to raise VPD and climbs along with it, so by that line the house is "not too warm"
all the while the sun heats it shut (in simulation, after a night closed and humid, the minimum
came 90 minutes late). So that target cannot go above the *crop line*: the stage's current
(daytime) temperature + 1 °C, or without a stage temperature the point two thirds up the guided
range (12–32 °C → 25.3 °C — the range covers day and night, so its middle is low for a daytime
crop, and its top lies above the protection threshold), never above the protection threshold
− 0.5 °C (so the minimum still reaches 80 % at the threshold). When dry air pulls the derived
target lower, that lower line still applies as before. A temperature-first target that just
follows the current temperature (no stage temperature), and a fallback target used while VPD
cannot be measured, cannot go above the crop line either.

In this window a vent that would otherwise rest for *no gradient* (because the misters cooled
the air) stays at the minimum instead. The effect model itself is unchanged: counting the
solar heat into the ventilation's temperature effect was tried and made the vents open *less*
in simulation, because a heavier temperature term with a small error dilutes the VPD demand.

Ahead of the minimum: rain and wind gates, an unknown outdoor reading (the vents hold), lost
rain or wind readings (no further opening), night parking, the 45 minutes before it
([reason 48](#settings-ventilation)), the HVAC interlock, Extreme Heat Protection's "hotter
outside" (reason 28), the hard temperature and humidity limits, manual locks and suspected
actuators. The minimum wins over VPD and humidity demands, *no gradient*, ventilation
futility, the over-humid zone cap and "the vent does not respond". The values are fixed,
not options. It applies to the rule-based control (Legacy and the physical-model PI); the
MPC does not apply it.

#### Indoor readings lost on a sunny day { #solar-vent-blind }

The minimum above is decided from the indoor temperature. When every indoor sensor drops out,
a vent that can no longer be judged holds where it stands (reason 21) — and holding still on a
sunny morning means keeping the house shut. In one recorded outage (all indoor mirror sensors
lost at 07:29) the vents stayed at the night's 0 % into a clear, dry day: one site's side vents
were shut from 09:03 to 12:55 at 19 °C and 25 % RH outside, another site's vents at 656 W/m² of
sunshine. A closed plastic house in sunshine runs 15–20 °C above the outside air.

So while the indoor temperature is unknown and the outdoor reading is real (not the
outdoor-equals-indoor fallback), the vents get a small minimum worked out from outside alone:

| Condition | Value |
|---|---|
| Sun | outdoor sunlight from 200 W/m² (released below 150); without a reading, the clear-sky sunshine × recent cloudiness, or three quarters of the clear-sky sunshine with no sunlight sensor at all (more than the half used above: here underestimating costs a shut house on a clear day, overestimating only a 10 % opening on a dull one) |
| Not cold outside | outdoor air at least 12 °C — about where chilling injury starts for warm-season seedlings; colder air is not let in without knowing the indoor temperature |
| A closed house would be too warm | outdoor temperature + 0.02 °C per W/m² of sunshine is above the crop line (as above); released 0.5 °C below it. A single-film house settles about 0.033 °C per W/m² above the outside air, but the crop's transpiration and the floor's heat capacity slow the morning rise — in the closed-loop simulator a shut house on a clear autumn day ran 0.011 °C per W/m² above outside at 09:00 and 0.020 at 14:00. The afternoon value crosses the line at the same time the simulated house does; 0.033 would call a still-warming house "too warm" an hour early |
| Minimum opening | 10 % just above the line, rising to 20 % at the [Extreme Heat Protection](#heat-protect) threshold; only 10 % while the outdoor air itself is at or above that threshold |

It touches only vents that would otherwise hold for reason 21, and opens them **5 percentage
points per 10-minute cycle** (a shorter cycle takes a proportionally smaller step; the first step
goes at least to the device's minimum opening so it is not snapped back to 0). A vent already
open wider stays where it is — nothing is closed for lack of evidence. Overcast and twilight
hold. Once the sun is down (clear-sky sunshine below 50 W/m², as for reason 58) and the indoor
temperature is still unknown, a vent open 20 % or less is closed at the same pace; a wider one
still holds — except where [night closing](#settings-ventilation) is on: from sunset the night
closing (reason 19) takes that vent first. When the indoor readings return, normal control continues from where the vent
stands (the integral follows the opening). The facility popup reads *Indoor reading missing —
opened a little because a closed house heats fast in the sun (closed again after sunset)*
(reason 60), and the log notes when it starts and stops.

**Very hot outside is not a reason to close.** With the indoor temperature unknown, outdoor air
at or above the protection threshold keeps the vents at the smallest minimum instead of shutting
them. A closed house in sunshine is always warmer than the outside air; Extreme Heat
Protection's "hotter outside" (reason 28) closes the vents only after *measuring* that misting
and shading have kept the house cooler than outside, and without indoor readings there is no
such measurement. Nor is there a reason to open wide — if the misters were running, the house
may be cooler than outside and a wide opening would bring hot air in. The small opening lets
the misters' moisture out so their cooling keeps working.

Ahead of this minimum: everything ahead of the sunshine minimum above, and the rain, wind and
frost caps (reasons 52, 55, 56). The values are fixed, not options. It applies to the rule-based
control (Legacy and the physical-model PI); the MPC does not apply it.

### Heating, Cooling and Misting { #settings-hvac }

| Field | Default | Description |
|-------|---------|-------------|
| Use Micro Sprinklers to Raise Humidity | On | Use the wetting-type misters for humidity too. Turn off when the same nozzles are your irrigation — a sprinkler sized for irrigation leaves a film of water on the leaves after even one short burst. With it off those misters are left out of automatic environment control altogether — no commands are sent to them at all, so a separate irrigation control keeps them. |
| Enable Sunburn/Evening Protection | Off | Blocks wetting-type misting in strong light (droplets can lens sunlight onto leaves) and, optionally, before sunset. In extreme heat and dryness one short pulse is let through the lock — see [Short misting pulses](#pulse-fog). Independent of how often misting runs. |
| Stop Wetting Mist Toward Dusk | On (Advanced) | Wetting-type misting eases off as the light fades and stops 90 minutes before sunset (with sunburn/evening protection on, at its *Stop Misting Before Sunset* time) — see [Wetting mist toward dusk](#wetting-fog-dusk). Turn off to allow evening misting. |
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
| Misting by Sunlight Level | 150–250 W/m² | A band with two handles: below the lower value misting runs freely, above the upper it stops (except for the short pulses of [extreme heat and dryness](#pulse-fog)), and in between it tapers off linearly. The gap keeps the mist from switching on and off as clouds pass. **Applies to leaf-wetting misting only** — fog-type misting runs in strong sun too. The estimated *indoor* level is used, so closing the shade screen relaxes the lockout. With no light reading at all, a clear-sky estimate from the sun's position stands in, so a facility without a light sensor is still protected. With the default water source (groundwater) the values actually used are lowered to 100–150 W/m². |
| Short Mist Pulses in Extreme Heat/Dryness | On (Advanced) | While the lock is on, let one short pulse through (10 s on, at least 15 min off) when it is extremely hot or dry and wet leaves dry within minutes — see [Short misting pulses](#pulse-fog). Turn off to keep the lock absolute. |
| Allow Misting Before Sunset | On | Turn off to leave the leaves dry overnight. The longer leaves stay wet, the higher the risk of gray mold and downy mildew. **Only read while *Stop Wetting Mist Toward Dusk* is off** — with it on (the default) wetting misting already stops before sunset, whatever this says. |
| Stop Misting Before Sunset (min) | 120 | How long before sunset misting stops; *Stop Wetting Mist Toward Dusk* uses the same time in this mode. The block then holds until the next sunrise; where the site coordinates are unknown sunset cannot be worked out, and no evening block is applied. |
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
misting is not affected. During [Extreme Heat Protection](#heat-protect) this lock only
gets stricter — the lowest of the reference + 5 %, **Max Humidity** and 85 %. Wetting mist
is not one of protection's evaporative coolers: its water lands on leaves and trays and
cools only as those dry, so in already-humid air more of it only keeps leaves wet.

### Wetting mist toward dusk { #wetting-fog-dusk }

A wetting-type mister (leaf-wetting droplets, not fine fog) does not evaporate in the air: its
water lands on the leaves and trays and leaves only as they dry, and how fast they dry depends
on the sunshine. Misting into the evening therefore sends the crop into the night with wet
leaves — the longer leaves stay wet, the higher the risk of gray mold and downy mildew.
Measured case (a tomato house, VPD target 1.0 kPa, sunburn/evening protection off): the wetting
mister ran at 100 % (reason 1, VPD) from 12:00 to 17:00 while the sunshine fell from 150 to
31 W/m² and sunset was 17:54. The sunburn/evening protection above only exists in nursery mode,
so nothing stopped it.

So wetting-type misters are held back as the day ends (in sunburn/evening protection mode too — see below):

| Condition | Wetting mister |
|---|---|
| Outdoor sunshine 150 W/m² or more | No limit |
| 50 – 150 W/m² | Scaled in proportion — 100 W/m² allows half the command, 75 W/m² a quarter |
| 50 W/m² or less | Off |
| From 90 minutes before sunset until the next sunrise (in sunburn/evening protection mode: from *Stop Misting Before Sunset* — 120 minutes by default) | Off, whatever the sunshine reads |

The sunshine is the outdoor reading; with no reading it is the clear-sky sunshine × how cloudy
it has been (half the clear-sky value if the house has no sunlight sensor at all). Where neither
the sunshine nor the facility's position is known, nothing is limited — not knowing is no reason
to stop humidifying.

The rule can only reduce. It is applied **after** the hard limits, so a **Min Humidity** demand
cannot push a wetting mister to 100 % into the dusk; the humidity that is missing in the
evening is the job of ventilation and fine fog. Fine (high-pressure) fog does not wet the leaves
and is not touched; neither is drip. Safety gates still come after it.

Switch: **Stop Wetting Mist Toward Dusk** (Advanced, on by default). The values — 150 → 50 W/m²
and 90 minutes — are fixed, not options.

**Sunburn/evening protection mode (*Enable Sunburn/Evening Protection*) gets this rule too.** In
that mode the strong-sun lockout and its taper stay exactly as described under
[Heating, Cooling and Misting](#settings-hvac) and keep covering the bright part of the day; this
rule covers the weak light, the evening and the night. Before this, the protection lifted its
lockout in the evening and nothing held wetting misting back after sunset — in a simulated
tropical night the crop stayed wet about 590 minutes. The only difference in this mode is when
the evening stop starts: at *Stop Misting Before Sunset* (120 minutes by default) instead of 90.

How the settings fit together in that mode:

| *Stop Wetting Mist Toward Dusk* | *Allow Misting Before Sunset* | Result |
|---|---|---|
| On (default) | On (default) | Wetting misting stops before sunset and tapers in weak light |
| On | Off | The same — both stop at the same time, so nothing changes |
| Off | On | Evening misting is allowed (the behavior before this rule) |
| Off | Off | The old evening block alone: no misting from *Stop Misting Before Sunset* until sunrise |

So *Allow Misting Before Sunset* is only read once the rule is turned off; to keep evening
misting in sunburn/evening protection mode, turn *Stop Wetting Mist Toward Dusk* off. The facility popup reads *Wet misting is
held back as the light fades — leaves would stay wet overnight* (reason 53); the log notes when
the limit starts and stops. It applies to the rule-based control; the MPC does not apply it.

### Short misting pulses in extreme heat and dryness { #pulse-fog }

The sunburn lock above and the [dusk rule](#wetting-fog-dusk) keep a wetting-type mister at zero
while the sun is strong or the day is ending. On an ordinary day that is right. On an extreme
day it leaves the house with no humidifying and no cooling from the wetting mister at all: in
the closed-loop test of a tropical heatwave (indoor 42.5 °C, 337 minutes above 40 °C, VPD inside
its band 7 % of the time) and of a dry foehn wind (RH 15 %, VPD up to 7 kPa) it stayed off all day.
The lock was set to keep mineral residue from groundwater off the leaves and droplets from
lensing sunlight — a worry that was never actually observed in the crop. So on such days it
lets **one short pulse** through.

A pulse can go out only while the sunburn lock is on **and** every line below holds:

| Condition | Meaning |
|---|---|
| Hot or dry | [Extreme Heat Protection](#heat-protect) is in stage 1 or 2, **or** indoor VPD is above 3 kPa |
| Fast drying | Dry-bulb minus wet-bulb at least 8 °C — a wet leaf dries within minutes |
| Humidity | The wetting-mist humidity lock is not holding, and humidity is below **Max Humidity** and below 85 % |
| Water | The [misting water supply](#water-supply) says there is water (no signal chosen counts as water) |
| Not evening | Further than 4 hours before the [dusk rule](#wetting-fog-dusk) (reason 53) would start, and the evening block is not holding — **no pulse in the afternoon tail, at dusk or at night**. The water of the last pulses would otherwise keep evaporating into the house as it closes and bring the night dew forward (simulated heatwave: 5 % more wet night minutes with no margin, 0.4 % with 4 hours) |
| No other gate | No rain (measured or forecast), strong wind stage 2, cold emergency, frost watch or protection, and no lost indoor or outdoor reading. Strong wind stage 1 only limits the vents, so it does not stop a pulse |

The pulse itself is **10 seconds on, then at least 15 minutes off**, and it goes out only while
control is asking for humidity (a command of 5 % or more; with none, the mister stays off). It
rides the pulse dosing every wetting mister already has ([Automatic conversion by device
type](#actuators-adapters)): the on-time is the shorter of 10 s and *Max Spray Duration*, the
rest is the longer of 15 minutes and *Enforced Drying Interval*. The 15-minute rest is kept by the
coordinator itself, per mister, because the device adapters are rebuilt every 10 minutes and would
forget it. A mister set to spray shorter or less often keeps that setting, and the rest carries on
after the conditions end. A mister whose output cannot be cut by time or volume (a PWM or value output)
does not pulse at all — it stays locked. Fine fog and drip are not involved, and without
sunburn protection there is no lock, so nothing changes.

Switch: **Short Mist Pulses in Extreme Heat/Dryness** (Advanced, shown with sunburn protection,
on by default); off keeps the lock absolute as before. The values — 10 s, 15 min, 3 kPa, 8 °C —
are fixed, not options. The facility popup reads *Extreme heat and dry air — one short misting
burst is allowed through the sunburn lock* (reason 57); the log notes when pulses become
allowed and when they stop. It applies to the rule-based control; the MPC does not apply it.

### Misting Water Supply { #water-supply }

A mister that runs dry heats its pump and humidifies nothing, but the coordinator cannot
see a tank. **Check Misting Water Supply** binds one measurement to it — a tank level (%), a
line pressure or a flow switch — and says which side of a threshold means "there is water".

| Field (shown when the check is on) | Default | Description |
|-------|---------|-------------|
| Check Misting Water Supply | Off | Stops every mister while the signal below says there is no water. Off: water is assumed to be there, exactly as before. |
| Water Supply Signal | — | The measurement to read: a tank level, a line pressure or a flow switch. |
| Water Supply Threshold | 0.5 | In the signal's own unit. For an on/off switch (0 or 1) leave 0.5; for a tank level, the lowest level you still want to mist at. |
| Water Is Available When the Signal Is | At or above the threshold | *At or above*: level, pressure and flow — more means more water. *At or below*: an empty-tank alarm switch that reads 1 when dry. |

| Signal | Water | Misters |
|---|---|---|
| Check off, or no signal chosen | assumed there | as before |
| Fresh and on the right side of the threshold | there | as before |
| Fresh and on the wrong side | **none** (low) | all off |
| Missing or stale | **none** (unknown) | all off |

If the check is on but no signal is chosen, the log says so once and water is still assumed to be there.

An unknown signal counts as "no water" on purpose: running a pump without knowing whether
there is water costs more than resting a mister for a few minutes, and the rest ends the
cycle the signal returns. Freshness uses the signal's own period, like the heating/cooling
running signal. Once it has gone to "none", the signal must come 5 % of the threshold back
past it before water counts as there again, so a pump's own pressure dip does not flip it
every cycle.

While there is no water **every mister** — with or without extreme heat — is parked
(*No water for the misters*, reason 41) and delivered at 0 from that very cycle, and a final
override zeroes them whichever engine (including Grey-box MPC) produced the command and
even when a manual lock holds them. If Extreme Heat Protection is also blocking misting,
reason 41 wins over *misting cannot cool the air right now* — filling the tank is what
a person can do. Protection reads the same flag.

The change is logged once each way (*no water, stopping all misters* / *water supply is back*).
When the check is on, channel 92 records 1 (water) · 2 (low) · 3 (signal missing or stale)
every cycle, with or without debug logging, and the health check reports the minutes the
misters were stopped for lack of water — anything above zero means a person has to look at
the tank, the pressure or the signal.

### Light and Shading { #settings-light }

| Field | Default | Description |
|-------|---------|-------------|
| Shading and Supplemental Light | 0–800 W/m² | Two reference lines, not a range to stay inside. Darker than the band: supplemental lights come on and the shade screen opens. Brighter: the shade screen closes. Inside the band nothing happens. The reference is **the light the crop actually receives** — outdoor irradiance with the covering and shade screen transmittance applied. |
| Use the Shade Screen Against Heat | On | Lets the controller draw the shade screen to take heat and water stress off the crop — only while the crop still gets enough light for the day. Off: the screen follows the VPD and temperature deviations alone, as before. See [The shade screen against heat](#shade-heat). |
| Open the Thermal Curtain a Crack Against Night Condensation | On | At night, before any vent, opens a closed thermal curtain 3 → 6 → 10 % when the air nears its dew point — only as far as the heat it lets out allows. Only for curtain motors that can stop part-way. See [Thermal curtain — night gap and morning ramp](#curtain-gap). |

Either end can be switched off, and off means different things at the two ends: the
lower handle at 0 is *no supplemental light*, and the upper handle turned off is
*no shading*. If the facility has no shade screen or no supplemental lighting
registered, the screen says so rather than offering a handle that does nothing.

The shading line is judged on how bright it would be **with the screen drawn back**, not
on the light under a closed screen — otherwise closing it would darken the reading,
release the decision and open it again the next cycle. Where outdoor light is unknown
(an indoor sensor only), the current reading is used instead. While shading is in force,
supplemental light and screen opening are not forced at the same time: if the two lines
cannot both be met — a closed screen leaves the place darker than the supplemental-light
line — shading wins and the contradiction is written to the log once, for you to resolve.

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

### The shade screen against heat { #shade-heat }

A drawn shade screen cools the house twice over: less sunlight heats the air, and the crop
transpires less, so the air dries out more slowly. It also takes light away, and light is
not something the effect model weighs — left to itself the controller would treat shading
as free cooling. So whether the screen may be used for heat and humidity is decided in one
place (`screen_policy`), and the controller only reads the answer. This applies while the
sun is up (outdoor sunlight from 150 W/m², released below 100 — the same line Extreme Heat
Protection uses; without a sunlight reading, sunrise to sunset). A screen with nothing to do
goes back to open only while the sun is up — at night it stays where it is, because a drawn
screen keeps the crop from cooling to the sky.

**Three light states.** The judgement looks at the light the crop would get **with the
screen fully drawn**, and at today's light (DLI): what the crop has received so far plus
what the rest of the day would bring if the screen stayed drawn until sunset — clear-sky
sunshine from the facility's position, scaled by how cloudy it has been over the last 30
minutes, the covering and the screen cloth.

| State | When | What the screen does |
|---|---|---|
| Light to keep | Fully drawn, the light would fall below **Min Light Threshold**, or the day's light would fall short of the program's DLI target | Stays open (*Shade kept open*, reason 44) |
| Light to spare | Even fully drawn the crop stays at or above its light saturation point, or it is bright enough that the sunburn lock of wetting-type misters applies | Used freely for heat and VPD (*Shade drawn against the heat*, reason 43) |
| In between | Drawing would cost photosynthesis but the day's light is still enough — and also when the DLI target or the light is unknown | Used only once the cheaper means are spent: every vent and fan at 80 % or more (or it is warmer outside than 1 °C below inside) **and** misting spent (no mister, blocked by water, sunburn lock or heat protection, or running at 80 % or more). Until then it stays open (reason 44) |

When the screen may be used, the [temperature ceiling](#l3-coordinator-actuator-command)
term also drives it, so it draws before the temperature crosses the line rather than after.
The order on a hot, dry day therefore becomes: vents → (screen, light to spare) → misting →
(screen, in between) → fans → cooling. This order is applied by the "spent" check above,
not by cost: load sharing is kept per domain, so a cost on the screen could never make it
wait for the misters.

**Fewer trips.** A shade screen takes minutes to travel. Moves the controller asks for are
filtered: after a move the screen stays put for at least 15 minutes (or three full travel
times, whichever is longer); a request to move must persist for 5 minutes; it does not draw
without sun; and it moves at most 8 times a facility-local day — after that, controller
requests hold it where it is for the rest of the day (*Shade held where it is*, reason 45,
logged once). Opening after the sun has gone is never capped. Moves ordered by Max/Min
Light Threshold, the temperature hard limits, Extreme Heat Protection, a safety gate, a
manual lock or the light-keeping rule always go through.

**Who owns the screen.** While Extreme Heat Protection is on and has drawn the screen (or
held it back), protection owns it: none of the above is applied. Protection asks the same
light question here — in stage 1 it holds the screen back while the light state is *light
to keep* (Min Light Threshold or the day's DLI); in stage 2, or 3 °C above its threshold, it
draws regardless. Max/Min Light Threshold
and the temperature hard limits still win over everything in this section.

The effect model of the screen uses the cloth transmittance τ: a screen blocks only
(1 − τ) of the light, and opening it raises VPD by the warming *minus* the water the crop
transpires from the extra sunshine — about 60–80 % of what a plain temperature rise would
suggest. A screen whose coefficient was tuned by hand (`k_override`) reads that value in the
new units: at τ = 0.5 it now counts half.

The light state is written to the log only when it changes. The health check names reasons
43–45 (*shade · heat load*, *shade · keeping light*, *shade · anti-shuttle*).

### Thermal curtain — night gap and morning ramp { #curtain-gap }

A thermal curtain whose motor can stop part-way — it is driven by position (a paired motor
or a position output) and its full travel time is known — is used for more than open and
closed. Everything else (relay curtains, or no travel time) keeps the 0/100 behaviour.
Ordinary control commands stay 0/100 either way; only the two moves below stop part-way
(stops 0 · 3 · 6 · 10 · 30 · 60 · 100 %), and what is recorded is exactly what is sent.

**Night heat retention — every thermal curtain.** At night the curtain is closed whenever the
house needs its heat: indoor is less than 2 °C above the bottom of the temperature target (target −
tolerance when temperature is the control target; the guided range when VPD is controlled directly — the VPD-derived temperature is never used as the line), or it is colder outside than that bottom line — or the indoor air is within 3 °C of its dew point (dew
demand: under an open curtain the crop cools toward the night sky and gets wet before the air does; in
simulation the same summer evening left 173 night wet minutes when the curtain closed and 433 when *no
gradient* held it open; for dew demand only an indoor temperature above the top of the target counts as
cooling to do, and it is released once the margin is back above 4 °C; not while it rains, within an hour after rain, or while the outside air is at 95 % RH or more — the clouds then cut the sky radiation). **Heating running counts as heat demand too**: if a heater received a command above 0 in the previous cycle (and for 30 minutes after it stops) and it is colder outside than inside, the curtain is closed even when the room is in the middle of its range — otherwise the heater warms the house while an open curtain throws the heat away; while it runs, the curtain is not released just because indoor is well above the entry line. This is judged from
the target and the outdoor temperature, not from the current indoor–outdoor air difference — under
an open curtain the house follows the outside air, so that difference is small *because* the curtain
is open; and a closed curtain also cuts the radiative loss to a clear night sky, which the air
difference does not show. Ordinary control keeps the curtain when indoor is within 1 °C of the top of
the target or above it (there is cooling to do) or the outside air is warmer than inside; once closed,
it is released when indoor rises 1 °C above the entry line with outside 1 °C above the bottom line,
when indoor passes the top of the target, or when outside becomes more than 1 °C warmer than inside
(*Thermal curtain closed to keep the night heat in*, reason 49). Relay curtains are closed too. The
night gap below still cracks a closed curtain; **Min Temperature**, the safety gates and the sunrise
opening are unchanged.

**Night gap — condensation goes through the curtain first.** At night, with the curtain
closed (5 % or less), when the indoor air comes within 2 °C of its dew point the curtain opens
a crack: 3 %, then 6 %, then 10 %. Each step is held 15 minutes and the next is taken only if
the margin has not started to recover (*Thermal curtain opened a crack to let night moisture
out*, reason 46). It closes again once the margin is back above 3 °C (the same lines as the
[over-humid zone](#humid-zone)). Heat comes first: no gap while heating is forced
(**Min Temperature**) or, with no heater, while indoor is at or below the bottom of the
temperature target; only the first step while it is more than 8 °C colder outside than inside
or a heater is running at 80 % or more. The cold-weather gate and **Min Temperature** close
the curtain over all of this.

The vents' night condensation escape (see [Ventilation](#settings-ventilation)) waits for the
gap: it is allowed only once the gap has gone as far as it may and been held for 15 minutes
with the air still near its dew point. Without a curtain that can stop part-way, or with
this option off, the vents behave as before.

**Morning ramp.** At sunrise a curtain that was closed overnight opens in steps — 10, 30, 60,
then 100 % — instead of all at once, so the cold air above it does not drop onto the crop.
Each step lasts 10 minutes; the next is taken only if indoor fell by no more than 1 °C during
the step and is still at or above the bottom of the temperature range — the second condition only for the first two hours, so a house the heating cannot bring into range is not kept under a closed curtain all day (*Thermal curtain
opening in steps…*, reason 47). If indoor is less than 5 °C warmer than outside there is no
cold layer to worry about and the curtain opens at once. Daytime opening otherwise is as before
(reason 22).

### Advanced Settings { #settings-advanced }

This group is folded by default and is for engineers testing the function, not for
growers.

| Field | Default | Description |
|-------|---------|-------------|
| Max Sensor Age (seconds) | 0 | Reject sensor readings older than this. If a sensor (Input) has its own max age set, that value takes precedence over this option. **0 means "not set", not "no limit"** — each sensor is then judged by its own update interval × 2 (at least 300 s). A fixed number shorter than a source's period can never be satisfied: an outdoor station publishing every 300 s under a 120 s limit never has a valid reading. |
| Control Basis | VPD | `VPD`: follows the VPD target directly. `Temperature first`: follows the stage temperature and turns the VPD target into a humidity target ([Control basis](#control-basis)). |
| VPD Target Applies To | Air VPD | `Air VPD`: the target is compared with air VPD. `Leaf VPD`: the target is a leaf VPD, turned each cycle into the matching air VPD at the measured leaf temperature; without a usable leaf temperature that cycle uses it as an air VPD ([Air VPD and leaf VPD](#leaf-vpd)). |
| Leaf Temperature Sensor | — | An infrared leaf or canopy temperature. Shows leaf VPD next to air VPD and is required for a leaf VPD target. Readings more than 10 °C away from the air are treated as not seeing leaves. |
| Enable Photosynthesis-Oriented Control | Off | Each cycle, the Big-Leaf model identifies the current limiting factor (light / CO₂ / temperature / VPD) and raises that variable's priority. Requires a light sensor; the crop constants come from the plot's program. |
| Reference Plot (optional) | (empty) | Which plot this coordinator follows when more than one is growing in its scope. Leave empty when there is only one. |
| T Weight (0–1) | 0.6 | When the VPD target is split into auxiliary temperature and humidity targets, the share given to temperature (the rest goes to humidity). When VPD can be measured, VPD itself is what is controlled; this value only shapes the auxiliary targets — the never-cross lines and the reference for the wetting-mist lock. |
| VPD Priority | 1.2 | The weight used when a device that affects several axes combines their deviations — higher means this axis counts more in the command. The order in which devices are settled is set by cost index, not by priority ([L3](#l3-coordinator-actuator-command)). |
| CO₂ Priority | 0.8 | The same weight for CO₂, lower than VPD because enrichment is secondary. |
| Enable DLI / GDD Tracker | Off | Tracks daily light integral and growing degree-days, rolling over at facility-local midnight. Light is converted to PPFD by sensor unit. Targets come from the plot's program; requires a light sensor for DLI. At the day's end a gap either way against the target is recorded as a compensation suggestion — how much to make up per day, spread over three days, and whether the devices present can deliver it. |
| Night Dew Circulation Fan (Experimental) | Off | Runs the circulation fans after sunset while the indoor dew-point margin is small ([Circulation fans on dewy nights](#night-dew-fan), reason 59). Off by default — in simulation it did not shorten the wet hours of a closed house. |

#### Effect Calibration { #settings-calibration }

| Field | Default | Description |
|-------|---------|-------------|
| Effect Engine | Legacy | `Legacy`: built-in K_* constants (default, safe). `Shadow`: runs the grey-box model in parallel for logging only — no control change. It also records the commands MPC would have sent, with their prediction. `Grey-box`: physics-model control. Each cycle it tries MPC (an optimisation that looks several steps ahead) first, then falls back to the physics-model PI, then to Legacy. MPC looks ahead at the outdoor conditions like this. Solar radiation follows the clear-sky curve from the sun position, scaled by how clear it is right now (works anywhere the facility has coordinates). Outdoor temperature and humidity move from the current measurement by **the change the forecast predicts**. The forecast is the Open-Meteo hourly forecast input linked to the facility (Weather tab) when its file was received within the last 2 hours — it is for the facility's own coordinates, so time zones do not matter. Otherwise it is the KMA short-term forecast, when issued within the last 6 hours and in the same time zone as the facility. With neither, they stay at their current values. It uses the forecast change rather than the forecast value itself, to cancel the difference between the forecast (a wide grid average) and this facility's weather station. MPC follows **the same rules** as the PI: night closing, ventilation that cannot reach the target with the outdoor air, locking openings while heating or cooling runs, ventilation first, heating or cooling that works against the temperature, and the [over-humid zone](#humid-zone) (closed when the outdoor air is wetter, at most 30 % when opening is allowed). A device held by one of these rules is not opened or switched on by MPC. MPC treats windows and fans by **airflow** (window area, rated fan airflow). For the same airflow it opens roof vents first when it is warmer inside, and side vents first when it is warmer outside. If the fans move more air than the windows, it uses the fans and keeps the windows closed (a wall fan cannot pull air once the windows are open). MPC does not move the shade screen or the thermal curtain; it takes their current position into its prediction, including the lower heat loss of a closed thermal curtain. Recommended flow: Shadow first, then Grey-box. The collected data and scores carry over when the app or the daemon restarts (changing the control period, or a stop of more than a week, starts them over). The physics model **learns from the data Shadow collects, and Grey-box control switches on only when its 10-cycle-ahead prediction beats the simple "stays as it is now" prediction**. The comparison is made separately for each weather regime (hot day, mild day, sunrise/sunset, night and so on), and it must win in every regime that has collected enough observations, with at least two such regimes — until then control stays on Legacy. After an update that changes the model's equations, this learning and validation starts again on the new equations. While Shadow or Grey-box is selected, this parallel run has to keep working for any of that to progress — if it fails three cycles in a row the log reports it, and again every 60 cycles after that, so a stalled model does not stay silent. While [Extreme Heat Protection](#heat-protect) is on, those cycles run on Legacy (MPC does not know its rules). The same goes for a cycle with a [suspected actuator](#actuators-suspected) held out of load sharing, and for a cycle in which indoor temperature or humidity (or CO₂, when there is a CO₂ target) cannot be measured — MPC would be optimising on invented values; the log says why when the reason changes and once an hour while it lasts. Change only while testing. |
| Enable RLS Calibration | Off | Learns, per device, how strongly it actually moves each reading (temperature, humidity, CO₂) compared with the built-in model, as a **scale factor** (1.0 = the model as it is). The model's condition terms (indoor/outdoor difference, wind, area) stay; only the size is corrected. It learns only from cycles in which that device alone changed — when several move together, their shares cannot be told apart. Needs several days of data; until then the model is used as it is. |
| Enable Active Probing | Off | Periodically perturbs one actuator by ±10 % to improve calibration identifiability. Only triggers when load is low and no safety gate is active. A circulation fan is never picked. Requires RLS Calibration. |
| Probe Interval (seconds) | 3600 | Minimum time between probing events. Steps: Often (1800) / Standard (3600) / Rare (10800). |

#### Forecast Feedforward { #settings-forecast }

| Field | Default | Description |
|-------|---------|-------------|
| Enable Forecast Feedforward | Off | Uses the short-term weather forecast to proactively shift temperature/humidity setpoints before adverse weather arrives. A forecast more than 3 °C above the current indoor temperature lowers the temperature target by 1.5 °C, more than 3 °C below it raises the target by 1.0 °C, and a forecast above 85 %RH lowers the humidity target by 5 %RH; a shifted target still stays inside the range you set. Rain or strong wind in the forecast is reported with the decision summary but does not close the vents on its own — measured wind and rain do that. |
| Forecast Lookahead (hours) | 3 | How far ahead to check. Steps: Short (1) / Standard (3) / Long (6). Longer gives earlier warning but may over-correct. Hours are counted **from now**: if the forecast file is updated late, forecasts for hours that have already passed are not used, and if the file has no upcoming hours no correction is made. When the only forecast input linked to the facility is an Open-Meteo hourly forecast input and its file was received within the last 2 hours, this window is read from that file (highest and lowest temperature, highest humidity and wind); there, a rain probability of 50 % or more counts only if the hourly rain in the same window reaches 0.5 mm/h — without a rain amount the probability alone does not count. Otherwise, when the facility has forecast sources linked, their values are used as is and this value is not used. Only one of these is used, never both. |

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

Paired actuator modules are picked up automatically too, but only those that belong to the
linked facility: bound to one of its slots, or placed on its map. A module that no facility
uses and that is not on the map (a test unit, a device whose bindings have all ended) is
ignored, as is anything under another facility. A device on an upper floor of a multi-floor
facility model is left out the same way and does not appear in the *Devices under automatic
control* list either — this coordinator has no notion of floors, so neither its sensors nor
its actuators take part in control; it still shows on screen and can be operated by hand
(see [Facility — Plan Drawing](../geo/facility.md#plan-drawing)). A device switched off under
*Devices under automatic control* stays off however it is discovered. A fan's rated airflow is
read from the actuator's *Airflow* spec or from its fan fitting's airflow; when neither is set a default is used (3000 m³/h for an exhaust or intake fan, 1500 m³/h for a circulation fan).

| Action option | Default | Description |
|---------------|---------|-------------|
| Output Channel | — | The Output channel to control. |
| Actuator Type | — | Vent/Opening · Cooler · Heater · Fogger/Humidifier · CO₂ Injector · Shade Screen · Thermal Curtain · Supplemental Lighting · Circulation Fan · Exhaust Fan · Intake Fan. |
| Cost Index | 5.0 | Lower value = higher priority (1 = free natural ventilation, 10 = high-cost device). The device's energy cost (kW × opening) is added to it. kW comes first from the output channel's **current draw (A) × the system usage voltage**, then from the rating on the facility drawing, then from a per-type default. The usage voltage is a system setting that defaults to 120 V, so a 220 V installation should set it. |
| On Time Window End | Do Nothing | What happens to this actuator when the Working Hours window ends: Do Nothing / Turn Off / Turn On / Set Open % (vents only). |
| End Open % | 0 | Target opening percentage at that moment (vents/openings only). |
| Cloth Transmittance Override (0–1, Shade only) | 0 | Only for this screen, when its cloth differs from the rest. Leave 0 to use the value set on the linked facility. The value is used when there is no indoor light sensor: the indoor level is then estimated from outdoor irradiance and the screen position. |
| Effect Coefficient Override (K_*) | 0 | 0 = use default. Enter only when calibrating from measured data. |
| Full Stroke Time (s) | 0 | Seconds for this actuator to travel 0→100 %. Used to cap the command change per cycle so a physically impossible command is never sent. A vent motor taking 10 min → 600. |
| Min Repeat Interval (s) | 0 | Minimum seconds between repeated commands to this actuator even when the target has not changed. 0 = system default (600 s watchdog). Raise it for slow motorised actuators to extend relay life. |

### Automatic conversion by device type { #actuators-adapters }

A command is always computed as 0–100 %. The adapter is chosen from the Output module's
own metadata — no extra configuration:

| Output type | Adapter | Conversion |
|-------------|---------|------------|
| Paired actuator module | Paired | Forward/reverse pair conversion, internal to the module |
| Self-positioning `value` output (Matter curtain, shade, blind, motorised vent) | Paired | 0–100 % sent as a target position; 0 % closes fully instead of stopping |
| `vol` / `volume` (volumetric pump) | Volumetric | `vol_ml = flow_lpm × on_sec / 60 × 1000` |
| `pwm` | PWM | duty = pct |
| `on_off` relay | Time-proportional | `on_sec = cycle_sec × pct/100`; OFF below 5 % |
| anything else | Value | 0–100 % passed straight through (DAC, stepper) |

| Command (%) | on/off relay (60 s cycle) | PWM | volumetric pump (1.5 L/min) |
|---:|---|---|---|
| 0 | OFF | duty 0 | OFF |
| 30 | ON for 18 s | duty 30 | 450 mL/cycle |
| 100 | ON for 60 s (continuous) | duty 100 | 1,500 mL/cycle |

**Screens.** A shade screen or a thermal curtain is moved fully open or fully closed
whichever adapter drives it ([L3](#l3-coordinator-actuator-command)). The exception is a
screen driven by position — a paired motor or a position output whose full travel time is
known: the thermal curtain's night gap and morning ramp stop it part-way (3 · 6 · 10 · 30 ·
60 %, see [Thermal curtain — night gap and morning ramp](#curtain-gap)), and what is
recorded is exactly what is sent. A relay or PWM screen always goes 0/100.

A wetting-type mister is additionally wrapped in pulse dosing: one spray is cut at the
maximum on-time, and nothing sprays at all until the drying interval has passed. The one
short pulse of [extreme heat and dryness](#pulse-fog) (reason 57) uses this dosing with a
tighter cap — at most 10 s on, at least 15 minutes off (the rest is timed by the coordinator).
The drying interval carries over when the coordinator re-reads its settings and devices
(every 10 minutes, or on Reload): a mister that has just sprayed does not spray again right
after the re-read. If you shorten the drying interval, the new value counts from the last
spray straight away; a longer one extends the current rest. A restart of the coordinator
starts the interval afresh. The drying interval is read as the gap between the *starts* of two
sprays (a few seconds of cycle jitter allowed, at most a tenth of the interval), so a 600 s
interval on a 600 s cycle sprays every cycle rather than every other; the 15-minute rest after
a reason-57 pulse gets no such allowance.

Irrigation flow is aggregated from the facility drawing — every emitter under a layer is
summed into that actuator's `flow_lpm`, and the volumetric adapter uses it directly. The
fallback order is per-actuator flow, then the facility total, then 1.0 L/min.

The fogger effect model uses a **different** flow: only that actuator's non-drip spray
nozzles, and it never falls back. A dosed volume properly includes the drip lines that go
to the roots, but what evaporates into the air does not — so a mister with no nozzle
information on the drawing is credited with no cooling or humidifying effect at all,
rather than inheriting the facility total.

### Over-humid zone and windows that do not respond { #humid-zone }

When the air is close to saturation, judging ventilation by VPD goes wrong. VPD follows
temperature, so a warmer outdoor air shows a higher VPD even when it holds far more
moisture. The coordinator would then read "opening dries the house" and let humid air in.
So **when indoor VPD is below 0.3 kPa or the dew-point margin (temperature − dew point) is
below 2 °C**, ventilation is judged by vapor pressure (dew point) instead. The zone is left at
VPD 0.4 kPa and a 3 °C margin.

| Outdoor dew point | What the vent does | Label on screen |
|---|---|---|
| Outdoor air **more than 8 °C colder** than indoors, or **indoors at or below the temperature reference line** or heating demanded (including forced heating at the minimum-temperature limit) while the outdoor air is more than 1 °C colder | Whatever the dew point, does not open; heads **toward closed**. Temperature wins over the dew-point judgement — the heat lost (winter heating) outweighs the moisture removed. Exception: the [morning purge](#morning-purge) below | Too humid — outside too cold |
| At least 1.5 °C below indoors (0.75 °C if already open) | Opens, but **no more than 30 %** — the aim is to let moisture out. Exception: *lifting the cap* below | Too humid — venting limited |
| Less than that, or higher | Does not open; heads **toward closed**. A vent cannot fix this | Too humid — venting would not help |

- The **temperature reference line** is target + tolerance when temperature is a control target, and **the lower end of
  the guide range in direct-VPD mode**. In that mode the derived temperature target always runs ahead of the indoor
  temperature (further ahead the wetter it is), so using it as the reference made the outdoor air "too cold" as soon
  as it was 1 °C colder — at Gimje on 13 October, 12:48–15:59, indoor RH was 82–91 % with the outdoor air at almost the
  same temperature and a dew point 3–4 °C lower, yet the side vents stayed at 6–30 % and were closed twice. In that mode
  indoors now counts as heat-demanding only below the lower end of the guide range (the same line as the temperature
  floor of the [morning purge](#morning-purge)). A "heat demand" derived from the derived target is not used here;
  forced heating at the minimum-temperature limit still closes the vent.
- A heat emergency or an active temperature-ceiling term switches this zone off — on a hot,
  humid day the temperature asks for ventilation, not the humidity.
- Past the hard humidity limit the cap is lifted, but the vent still stays shut if the
  outdoor air is wetter.
- **Lifting the cap.** The 30 % cap means "do not open to fix temperature or VPD", not "remove less moisture". When the
  outdoor air is **at about the same temperature or warmer** (no more than 2 °C below indoors) and its **dew point is at
  least 3 °C lower** (twice the plain 1.5 °C threshold), opening further removes more moisture without losing more heat,
  so the vent opens without the cap. Once lifted, the thresholds relax to 3 °C and 2 °C so the cap does not flip at the
  boundary. Colder or less dry outdoor air keeps the 30 % cap as before.
- If the outdoor values are unknown this zone makes no judgement (the unknown-outdoor rule
  handles it).
- A facility with no heating or dehumidifier has no way to clear humidity a vent cannot clear.
  The screen says so plainly.

**A vent that does not respond is not opened further.** If a weak vent (effectiveness below 0.06)
is open 10 % or more and the deviation has not narrowed by 10 % in 45 minutes, it stays where
it is. This stops the controller from stacking up "open more" while the room does not change
and the vent creeping toward 100 % (drift). It resumes when the deviation narrows again.
A strong vent is not affected — when the sun gets stronger and the deviation grows it should open further. (A strong vent that stays wide open for hours with no response at all is a different case: see [Suspected actuators](#actuators-suspected).)

**A small VPD difference does not move the windows.** The ventilation-futility test now needs
the outdoor VPD to differ from indoors by **0.25 kPa**, not just the tolerance (default 0.1 kPa).
A difference inside 1–2 %RH of sensor noise does not open anything.

**The futility verdict does not flip at the threshold, and an open window is not cut at once.** To become
futile the difference must fall below 60 % of the threshold (0.15 kPa); to leave futility it must recover to
the threshold (0.25 kPa). An open window stays where it is until futility has lasted **20 minutes**, and only
then decays toward closed. A window that was already closed is parked immediately.

**Outdoor temperature and humidity are judged on a 10-minute moving average**, so integer steps
that change every few hours do not flip a decision. Safety gates such as rain and wind use the
raw values.

### Morning purge of an over-humid house { #morning-purge }

On a sunny morning the *outside too cold* row of the table above can keep the vents shut for hours
while the house sits at 90 % RH or more — a grey-mould risk — even though the sun is heating the house for free
and the outside air is drier. Yeongyang, 10 October: 91 % RH from 07:00 to 09:30 while the sun lifted the house
from 9.5 to 22.9 °C, vents at 0 %. So while the sun is warming the house, the vents get a **small minimum opening
of 5–15 %** (reason 54) instead of being parked:

| Condition | Value |
|---|---|
| Sun | outdoor sunlight from 100 W/m² (released below 70) — the same reading as the [sun's-heat rule](#solar-vent) |
| Too humid | the indoor air is inside the over-humid zone above (same entry and exit thresholds) |
| Drier outside | indoor dew point at least 2 °C above the outdoor one (1 °C if already purging) — judged by vapor pressure, so warm outdoor air with a high VPD but more moisture does not count |
| Little heat lost | indoors not more than 1 °C below the lower edge of the temperature target (target − tolerance); down to 3 °C below only while the house is warming (more than 0.5 °C/h, measured between cycles). No purge below that, while heating is forced by the hard minimum temperature, when the outside air is more than 15 °C colder than indoors, or when the house is cooling faster than 1 °C/h below the lower edge |
| Opening | 5 %, plus up to 10 % more growing with how far RH is above 85 % and with the sunlight (400 W/m² above the threshold gives the full amount); only 5 % when more than 1 °C below the lower edge |

The purge only lifts the vents to that opening — it does not open further to chase VPD or temperature (the
controller and the sun's-heat rule do that). The opening is held in the integral too, so nothing snaps
shut when it releases. It releases when the house leaves the over-humid zone, the sun fades, the outside air is no
longer drier, or the house cools. Ahead of it: rain and wind gates, the [rain limit](#safety-gates) (reason 52 — a purge never lifts a vent above its rain cap: a closed roof vent stays closed, a capped side vent stays at or below 30 %), an unknown outdoor reading, lost rain or wind
readings, night parking and the 45 minutes before it, the HVAC interlock, Extreme Heat Protection's "hotter
outside". It wins over *outside too cold*, *no gradient* and ventilation futility; a larger sun's-heat
minimum (reason 51) keeps its own label. The popup reads *Slightly open to let the night's moisture out — the sun is
warming the house and the air outside is drier*; the log notes when it starts and stops. The values are fixed, not
options. It applies to the rule-based control (Legacy and the physical-model PI); the MPC does not apply it.

### Circulation fans on dewy nights { #night-dew-fan }

On a tropical night the outdoor dew point can stay above the indoor one, so opening the vents lets moisture in
instead of letting it out. The house stays shut, the air sits near saturation and the crop stays wet until
morning — in the closed-loop `heatwave_tropical_night` run (3 days, night RH above 90 %) 1148 night minutes were
wet. Leaves stay wet longest in still air: a thick boundary layer slows evaporation and lets the leaf cool below
the air (dew). Moving the air thins that layer, so the leaf dries sooner and forms less dew. This does not remove
moisture from the house — it shortens how long the leaves are wet.

If a **circulation fan** is registered **and the advanced option *Night Dew Circulation Fan (Experimental)* is on** (it is **off by default**), the fans run at **100 %** (reason 59) when both hold:

| Condition | Value |
|---|---|
| Night | between sunset and sunrise at the facility's location. Unknown location: nothing happens |
| Small dew-point margin | indoor temperature − dew point below **2 °C**; it releases at **3 °C** and not before 30 minutes of running. The same thresholds as the [over-humid zone](#humid-zone) and the night [curtain gap](#curtain-gap) |

Continuous rather than 15 minutes on / 15 off: the effect follows the time the air is moving (the boundary layer
thickens again within minutes of the fan stopping), a duty cycle would need extra memory across 5–10 minute cycles,
and a circulation fan is the cheapest actuator while the rule only holds while the margin is small. Facilities
without a circulation fan are unchanged. [Extreme Heat Protection](#heat-protect) and a hot spot found by the
spatial sensors run the fans at 100 % under their own reasons (1); frost protection ([Frost](#frost), reason 56) holds
them at 100 % as well — those always win. The popup reads *Circulation fans on — the night air is close to its dew
point, and moving air shortens how long the leaves stay wet*; the log notes when the fans start and stop. The thresholds are fixed, not options (only the on/off switch is).

**Why it is off by default.** In the closed-loop `heatwave_tropical_night` run with a virtual circulation fan, the rule left the night wet minutes unchanged (918) while fan energy rose 17 % and cover condensation 80 minutes — a shut house on a tropical night cannot lift the leaves above the dew point with air movement alone. It stays available for testing; the health-check night dew and frost minutes below are counted either way.

The health check (`check_env_coordinator_health`) also reports, from the indoor temperature and humidity sensors,
the **night dew minutes** (night with indoor RH ≥ 95 % or a dew-point margin below 1 °C) and the **minutes at or
below 0 °C indoors** for the period, next to the frost watch/protection minutes. When night dew covers at least
a quarter of the night (and 60 minutes), or indoor frost lasts 15 minutes or frost protection 60 minutes, it adds a
facility line — *consider a dehumidifier, thermal curtain and heating* (and notes a missing circulation fan or
heater). These are facility matters, so they do not count as defects in the exit code.

### Axes without a measurement, axes without a device { #actuators-missing }

Every facility has different equipment. An axis that can be measured but not moved, and
one that can be moved but not measured, are both normal configurations. The coordinator
looks at the combination and adapts on its own.

| Situation | What the coordinator does |
|-----------|---------------------------|
| Measured, but no device moves that axis | The value is **for reference**. It leaves control (its target is replaced by the outdoor value when one is available) but is still used for the photosynthesis judgement and other axes' calculations. If it stays off target, the facility popup says *No device can move this*. |
| Only one direction exists (a heater but no cooler) | Normal. The device works when demand is in its direction and rests at 0 % otherwise. |
| A device exists, but that axis cannot be measured | If another axis the device moves can be measured, it keeps controlling through that axis (for example a vent where humidity is unknown but temperature is measured). Only when **none** of the axes it moves can be measured does it **hold where it is** — at the opening actually delivered, so a wind-direction weighting does not close it bit by bit. Moving without knowing the deviation would use equipment without evidence, and closing or opening is a decision too. The one exception is ventilation on a sunny day, when holding a shut vent would itself overheat the house: see [Indoor readings lost on a sunny day](#solar-vent-blind) (reason 60). |
| Indoor temperature or humidity cannot be measured | That axis leaves control entirely. A missing value is never invented as 0 — that would read as "0 °C indoors" and drive the heating to full. Leaf-wetting misting is locked while humidity is unknown. If humidity is lost while a VPD target is set, VPD cannot be computed from temperature and humidity either. A sensor that reports its own VPD then stands in; otherwise that cycle falls back to temperature/humidity control, so vents, heating and cooling keep working on temperature, and the log lists *vpd* among the missing items with that note. |

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

### Suspected actuators { #actuators-suspected }

A device that keeps failing, or that seems to do nothing, should not keep collecting
commands: the integral winds up, and the share the coordinator *believes* it is delivering
stays in the load-sharing ledger so the other devices work less. A **suspected** actuator is
therefore taken out of load sharing and held where it stands.

It becomes suspected in one of two ways:

| Way | Condition |
|---|---|
| Sends keep failing | 5 cycles in a row failed **and** at least 4 minutes since the first failure. One success restarts the count. Scattered failures over weeks never qualify (the lifetime count behind the learning weights is a different number and is not read here). |
| Strong command, no effect (ventilation only) | The same judgement as the *windows that do not respond* rule in [Over-humid zone and windows that do not respond](#humid-zone), applied to the opposite band: a vent the model says has a **clearly measurable** effect (effectiveness at or above 0.06), last commanded **80 % or more**, with the outdoor reading known, for **2 hours without the deviation narrowing by 10 %** — **and** it supplies at least 80 % of the ventilation effect being commanded (when several vents are wide open together and nothing improves, the cause is common — an open-loop sensor, a broken sensor, too little capacity — not one vent), **and** another vent remains. Only one actuator per domain can be taken out this way, and the next one only after 6 hours. |

While suspected the actuator is shown as *This device looks faulty* (reason 42), its
command stays at the last position, **nothing is sent to it**, its integral is left as it
was, and it adds nothing to the ledger — the rest of the same domain take over its share.
Safety gates, hard limits and extreme-heat protection still reach it, since they do not
come from this reason. With Grey-box selected, a cycle with a suspected actuator runs on
the Legacy controller (MPC does not know this rule).

It is released automatically after **30 minutes** and tried again. Right after the release,
two failed sends in a row (instead of five) put it back, and one success ends the trial.
Nothing is stored: a restart clears every suspicion.

The first time each actuator becomes suspected, and the first time it is released, the log says so
(once per change, with the reason). Channel 93 records how many are held (only while there
is at least one, plus one 0 when it ends), and the health check reports the held minutes,
the actuators and the cycles — anything there means a person should look at the device.
Channel 73 (*unreliable actuators*, debug only) is a different number: it follows the
learning weights and is not what takes a device out of control.

### Safe default { #actuators-safe-default }

Each actuator has a safe position it moves to when a safety gate fires, on emergency
stop, or on an external `force_safe_state()` call. This follows the device kind —
thermal curtains and shade screens park at 100 %, everything else at 0 (off) — whether
the actuator came from the facility drawing or from an Action.

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

## Extreme Heat Protection { #heat-protect }

Above a temperature the crop cannot take for long, the goal changes: keeping the crop out
of heat and water stress comes before following the setpoint. **Extreme Heat Protection**
does that. It is on by default, and the threshold is a setting in
[Target and Temperament](#settings-target) because crops differ (default 30 °C).

**When it starts and ends.** It judges the filtered **average** indoor temperature — the
hottest sensor would trip it far too often at 30 °C.

| Stage | Starts | Ends |
|---|---|---|
| 1 — protection | Indoor stays at or above the threshold for 3 minutes, or the temperature expected at the next decision (current + rate of rise × period) is at least 1 °C above it | Indoor has stayed at least the release margin (default 1.5 °C) below the threshold for 10 minutes **and** the minimum hold (default 20 min) has passed |
| 2 — severe | The **Max Temperature** hard limit is crossed (the same latch that turns heating off and draws the shade) | The hard limit releases; the stage 1 rules then apply |

If the indoor reading is lost, protection does not start; if it was already on, it holds for
up to 30 minutes (shade stays, heating stays off, misting stops, vents hold where they are)
and then ends. It also never stands together with [Frost](#frost): while a frost stage is on, heat
protection is released and does not start.

**What it does** — a higher line wins over a lower one:

1. Rain and strong-wind closing still win: vents a safety gate closed stay closed.
2. If the outdoor reading is unknown, vents and fans hold where they are.
3. Vents and fans open only while it is **at least 1 °C cooler outside** than inside, and keep
   that permission until it becomes warmer outside than inside. While they may open, night
   closing, the heating/cooling interlock, "ventilation cannot help" and "no response" do not
   close them. When it is hotter outside they move toward closed (*Extreme heat — it is hotter
   outside*). If fog-type misting ran in the last cycle they keep 15 % open — fans first,
   windows if there are no fans — so the moisture can leave and the misting keeps cooling.
   Vents that may open are not trimmed by the wind-direction weighting.
4. Temperature comes first. Above the [temperature ceiling](#l3-coordinator-actuator-command)
   line (threshold − 1 °C) the term is hard, so VPD or humidity terms that would close the
   vents are dropped; below it the vents hold or step down as in ordinary control. When
   temperature and humidity are controlled directly — temperature-first basis, or the
   temperature/humidity fallback after the humidity reading (and so VPD) is lost — the line
   still applies on top of the temperature target, whose value can be above the threshold
   (with no stage temperature it is the guide ceiling), and temperature's priority is raised
   to at least 2.0.
5. Misting runs only while there is water ([Misting Water Supply](#water-supply); with no signal chosen, water is assumed), the air can still take up water (dry-bulb minus
   wet-bulb at least 4 °C; it stops below 2.5 °C) and humidity is below 85 % (allowed again
   below 80 %). Unknown humidity stops it (*Extreme heat — misting cannot cool the air right
   now*). Only fog-type (high-pressure) misters are used as coolers — the hard temperature
   term drives them. Wetting-type misters (downward sprinklers) keep their normal control and
   their humidity lock, which protection can only tighten: their water lands on leaves and
   trays rather than evaporating in the air, so driving them for cooling mostly runs off and
   keeps leaves wet into the night. These three conditions stop every mister. The
   sunburn/evening misting lockout still wins, except for the one short pulse of [Short misting
   pulses](#pulse-fog).
6. The shade screen is drawn while there is sun (outdoor sunlight from 150 W/m², released
   below 100). In stage 1 only if the light under the drawn screen stays at or above
   **Min Light Threshold** and the day's light allows it (the *light to keep* state of
   [The shade screen against heat](#shade-heat));
   in stage 2, or 3 °C above the threshold, it is drawn regardless. Once drawn
   it stays drawn while the sun is up, and protection owns the screen while it does.
7. Heating off, circulation fans on, coolers follow the hard temperature term in stage 1 and
   run at 100 % in stage 2. In stage 2, vents and fans that may open (cooler outside) also run
   at 100 % — the full capacity, not the model's estimate — and this wins over the
   **Min Humidity** fan shut-off. *Rest Heating and Cooling When Venting Can Reach the Target* is
   suspended.

While protection is on, the cycle runs on the Legacy controller even when Grey-box is
selected — MPC does not know these rules. Going up a stage counts as an emergency **once**:
the vent actuation interval is skipped for that one cycle only. Cycles that skip L1–L3 (a
rain or wind gate, or outside working hours) still apply protection directly: vents 100 %,
15 % or 0 %, misting off, coolers and circulation fans 100 %, heating off, shade drawn —
never touching a device the gate commanded.

Every cycle records the stage (channel 75: 0/1/2) and what was decided (channel 76, a bit
mask: vents may open · hotter outside · misting allowed · too little evaporation headroom ·
humidity too high · no water · shade drawn · shade held back for Min Light · indoor reading
lost), whether or not debug logging is on. The health check (`check_env_coordinator_health`) reports
active minutes and stage changes; more than one change an hour means the temperature is
hovering at the threshold. Entering stage 2 sends the extreme-heat alert email (at most once
a day). A threshold at or above Max Temperature is reported once in the log.

This replaces the old *Heat Emergency* gate (outdoor ≥ 45 °C and indoor ≥ 35 °C → vents
fully open). Under those conditions it was almost always hotter outside, so opening wide
heated the house, and the gate never acted in the 30–35 °C range where crops actually
suffer.

## Safety Gates { #safety-gates }

Safety runs outside the L1–L3 coordination algorithm — a Pre-Gate checked every cycle
before L1–L3, and a Post-Gate that sanity-checks the L3 result before it is dispatched.
Once triggered, a Pre-Gate stays active for at least 300 s after its last trigger
(prevents rapid on/off flapping). When a gate releases, the devices it moved find their
equilibrium again **from where the gate left them** rather than jumping back to the
pre-gate opening, because conditions may have changed in the meantime. A gate's forced
commands go out at once, and are re-sent every cycle while the gate holds, without
waiting for the actuation interval. Devices the gate did not force keep their normal
interval — a gate standing on one device does not speed up the rest of the facility.

### Pre-Gate (checked before L1–L3) { #pre-gate-checked-before-l1l3 }

| Gate | Trigger condition | Action |
|------|--------------------|--------|
| Rain (measured) | A rain gauge or weather station reports ≥ 0.5 mm/hr (fixed, not user-configurable), **and** it is not light rain in still air (see below) | Closes side/roof vents and skips L1–L3. Curtains/shades are interior equipment and are left alone. |
| Rain (limited) | Rain from a **forecast model** (Open-Meteo, KMA short-term forecast, NASA POWER), or light measured rain in still air | Does not close everything — see [Rain: measured or forecast](#safety-gates) below. Control keeps running (reason 52). |
| Strong Wind (stage 2) | 10-minute average wind ≥ **Strong Wind Threshold** (default 12 m/s), or a measured gust ≥ 1.5 × it (18 m/s) | Closes every vent, whatever the wind direction, and skips L1–L3. |
| Strong Wind (stage 1) | 10-minute average ≥ 0.6 × the threshold (7.2 m/s), or a measured gust ≥ 0.9 × it (10.8 m/s) | Does not close everything — see [Strong wind in two stages](#safety-gates) below. Control keeps running (reason 55). |
| Cold Emergency | Outdoor T ≤ −5 °C **and** indoor T ≤ 5 °C (both fixed). Releases once either rises 2 °C above its threshold | Closes vents, closes thermal curtains, forces heaters to 100 %. |
| Frost watch / protection | Effective indoor ≤ 4 °C / ≤ 2 °C — see [Frost](#frost) | Watch: curtain closed, vents not opened further. Protection: vents and curtain closed, heaters and circulation fans 100 %, misting/CO₂/cooling off; skips L1–L3. Reason 56. |
| Cold cannot be judged | Indoor temperature unknown | The emergency gate **does not fire** — it drives every device one way, so it fires only on firm evidence. |
| Indoor values lost | Indoor temperature/humidity stop arriving (judged by each sensor's own freshness rule — there is no separate 120 s clock) | **Nothing is forced.** The deviation cannot be measured, so that axis leaves control and devices that lost their evidence hold where they are. Axes that can still be measured (CO₂, light) keep being controlled, and control resumes as soon as values return (no 300 s hold). |
| Outdoor Rain/Wind Lost | A rain or wind reading that used to arrive stops arriving (judged by each sensor's own freshness rule — no separate 300 s clock). A sensor the facility never had does not count. The last reading survives a restart (a memory of the last 30 minutes), so a sensor that was already lost is not mistaken for one the facility never had. | If the last value was rain or strong wind, the Rain/Wind gate keeps the vents **closed** until a fresh reading says otherwise. Otherwise vents may hold or close but **never open further** — a stale "no rain" is not a reason to open. Exception: above your **Max Temperature** hard limit vents may still open. Shades and everything else keep normal control. |
| Misting Lockout | Strong light, or the evening cutoff, with Sunburn/Evening Protection on | Locks wetting-type misters only. A local lock: it does not freeze the rest of the facility and does not hold for 300 s. In extreme heat or dryness one short pulse passes it (reason 57, [Short misting pulses](#pulse-fog)). |

**Rain: measured or forecast.** A forecast model's hourly precipitation says rain *may*
fall on that grid square that hour, not that rain is blowing in through your vents. So the
gate first asks where the rain value came from: an input whose driver declares itself a
model (`data_origin: model` — Open-Meteo, KMA short-term forecast, NASA POWER) is a
forecast; everything else, and anything it cannot tell, is treated as measured (the stricter
side).

**Several rain sources are never averaged.** If any measured source has a fresh value, the
gate uses measured sources only — whatever their main/backup priority — and takes the
highest of them (a 0/1 rain switch reading 1 next to a gauge reading 0 means rain, not
"0.5"). Forecast rain is used only when no measured source has a fresh value, and is then
treated as a forecast. Before, a gauge reading 0 and an unmarked Open-Meteo input reading
1.2 were averaged to 0.6 and treated as measured rain, closing every vent at noon. If a
gauge that was reporting rain stops arriving, the forecast does not take over: the gate
keeps the gauge's last value and stays closed until the gauge is back (a gauge whose last
value was 0 hands over to the forecast at once).

**All rain values are in mm per hour.** Each channel is converted before the gate: a
15-minute total (KMA `rn_15m`, channels named like `rain_15m` or `15-min`) is multiplied by
4, a 10-minute total by 6, Open-Meteo's and KMA forecast's hourly totals are already per hour,
NASA POWER's daily total is divided by 24, and inch units are converted to mm. A 0/1 rain
switch stays 0/1. A channel whose period is unknown is used as it is, and a measured total
over more than an hour is never scaled down — both can only err toward closing.

| Rain value | Roof vents (and vents of unknown form) | Side vents |
|---|---|---|
| Forecast 0.1 to under 1.0 mm/h | Up to **30 %** (a wider roof vent closes down to 30 %) | Normal control |
| Forecast ≥ 1.0 mm/h (or your rain threshold, if higher) | Closed | Up to **30 %**; a windward side vent closes when wind is 2 m/s or more and its direction is known |
| Measured ≥ 0.5 and under 1.0 mm/h, wind measured this cycle below 2 m/s | Closed | Up to **30 %** |
| Measured, any other case (1.0 or more — a 0/1 rain switch reads 1 —, wind 2 m/s or more, no wind sensor, or a value that stopped arriving) | Closed | Closed — the full Rain gate above |

A limit, once set, steps down no sooner than 30 minutes later, so an hourly forecast
flipping between 0.9 and 1.0 mm or a shower that stops and starts does not swing the roof
vents. Limits are applied inside the coordinator, so its memory (integral) does not wind
up against them, and checked once more at the end: [Extreme Heat Protection](#heat-protect)
may open a side vent only up to its cap and cannot reopen a roof vent rain closed; the
30 % caps hold even at heat protection stage 2. A reading that stops arriving keeps its rule: a lost
measured rain value closes everything, a lost forecast keeps its limit and adds "never open
further". Outside the working-hours window there is no PI to choose a position under the
cap, so a capped vent with no other command closes.

**Strong wind in two stages.** One threshold used to close every vent in a single cycle and
reopen them the next; in a steady 10–12 m/s foehn that flipped the house shut and open several
times a day, and a sunny afternoon jumped 10 °C in one cycle. Now the **Strong Wind
Threshold** is the anchor for two stages, and every other number is a multiple of it:

| Stage | Enters at | Windward vents (within ±60° of the wind) | Other roof vents (and vents of unknown form) | Other side vents |
|---|---|---|---|---|
| 1 | Average ≥ 0.6× (7.2 m/s) or gust ≥ 0.9× (10.8 m/s) | Closed | Up to **30 %**; closed if its direction or the wind direction is unknown | Up to **50 %** |
| 2 | Average ≥ 1× (12 m/s) or gust ≥ 1.5× (18 m/s) | Closed | Closed | Closed |

A stage is entered at once. It is left one stage at a time — so a storm easing off goes
2 → 1 → none — when the **average of the readings over the last 20 minutes** since the stage
was entered (the 10-minute average and the measured gust, each on its own) is below **0.85×**
that stage's entry values. With the usual 10-minute cycle that is three readings, so the
earliest step down is 30 minutes after the stage was entered. A single reading back above the
exit value only weighs into the average; it does not restart the count (a steady foehn wavering
around 10.2 m/s used to restart a "20 minutes in a row" clock again and again and kept every
vent shut for 80 minutes of sun). A reading back above the stage's **entry** value starts the
20 minutes again. While a wind reading is lost nothing counts, and the window is emptied (a
stale "calm" is not a reason to open).

**Heat shortens stage 2.** When the house is hot — indoor at or above the [Extreme Heat
Protection](#heat-protect) threshold, or protection already active — stage 2 steps straight
down to stage 1 on the first cycle in which its cause is gone: the 10-minute average is below
the threshold and a measured gust (if there is a gust sensor) is below 1.5× it. Windward and
roof vents stay closed and the rest open only up to the stage-1 caps; if stage-2 wind returns,
every vent closes again at once. It never applies while a wind or gust reading is lost, and not
when Extreme Heat Protection is switched off. Stage 1 → none never takes this shortcut. Gusts are used only when a
sensor measures them: bind a channel with the measurement item **Wind gust** on an outdoor
sensor (see [Sensor Roles](../geo/facility.md#sensor-roles)); with several, the strongest
counts. Without one the gust is **not estimated** — stage 1's 0.6× average already sits where
a typical 1.5 gust factor would put a 0.9× gust, and an estimated gust must not close every
vent at midday. Stage 2's gust value (1.5×) follows the same factor: a station's gust is the
maximum over 10 minutes, and at 1.25× (15 m/s) a steady 10 m/s foehn never dropped back below the
exit value, so every vent stayed shut for a whole sunny day in simulation. A vent's direction comes from the map shape its device is bound to; vents
with no direction are logged once ("side vent azimuth not set"), and the health check lists
them when a wind-direction sensor is bound. Stage-1 caps work like the rain caps: applied
inside the coordinator with its memory held at the cap, checked again at the end so
[Extreme Heat Protection](#heat-protect) may open a vent only up to its cap, and closed when
nothing else commands the vent outside the working hours. When rain and wind both cap a
vent, the lower cap wins. Stage 2 is the full gate — heat protection cannot reopen it (it
only shortens how long stage 2 lasts, above).

**Lost values are a constraint, not an emergency.** Indoor values lost and outdoor
rain/wind lost both create no forced command and no 300 s hold, and when only these two
are active, L1–L3 run normally. The rule is that equipment is not moved just because
evidence is missing; whether to move is decided axis by axis by the coordinator.

**There is no heat gate.** High temperature is handled by
[Extreme Heat Protection](#heat-protect), at a threshold you set. Rain and Cold thresholds
are fixed in code — the **Wind** threshold is the only one exposed as a function option.
Multiple gates can be active at once (e.g. rain + strong wind); vents then close
unconditionally regardless of direction. When a gate and heat protection disagree about one
vent, the gate wins — rain and strong wind keep it closed even while heat protection would
open it, and the shade screen, coolers and fans still take heat protection's commands.

**A gated cycle is still a cycle.** When a gate ends the cycle early, a reduced summary
is written and the cycle is stamped, so the facility widget keeps showing what happened
instead of reporting the coordinator as unresponsive. The reduced summary still carries
the environment values measured this cycle — sensors keep measuring while a gate holds —
and leaves out only what L1–L3 would have produced, such as targets and deviations.
Every device stays listed, not just the ones the gate forced — a device that was not
touched carries no command at all, rather than 0 %. The per-device final command log
(channels 100+) is written on gated cycles too: the gate's own commands, any heat
protection commands, and for every other device its last command with reason 12, so a
closed vent at any hour can be explained from the log. The rules' memory also moves on during a
gated cycle — today's light sum, the cloud ratio, the clear-sky estimate and the "sun is up" latch
of the solar heat-load floor — so the first cycle after a long gate does not judge with values
frozen at the moment the gate closed. The gate still decides what the devices do.

### Frost { #frost }

The Cold Emergency gate above is for a freezing facility (outdoor −5 °C **and** indoor 5 °C). A crop is
hurt long before that: on a clear, still night the leaves and the cover are 2–4 K colder than the air
(radiative cooling), so air at 2–4 °C already means 0 °C on the leaf. In the closed-loop test *cold snap
frost* (a sunny 18 °C day, then a calm clear night down to −4 °C) the emergency gate never fired and the
crop spent about 390 minutes below freezing with no warning and no action. **Frost** is a two-stage
protection that stands much earlier, judged mainly on the **indoor** temperature (the coldest sensor).

| Stage | Starts | What it does |
|---|---|---|
| Frost watch | Effective indoor ≤ **4 °C** | Closes the thermal curtain; vents are **not opened further** (they may close). Control (L1–L3) keeps running. Shown as reason 56. |
| Frost protection | Effective indoor ≤ **2 °C** | Closes vents, exhaust/intake fans and the thermal curtain; heaters 100 %; **circulation fans 100 %** (mixes the cold air that settles on the leaves); misting, CO₂ and cooling off. Skips L1–L3 like the Cold Emergency. One alert e-mail per day. Shade screens and lighting are left alone. |

*Effective indoor* is the indoor reading minus 2 °C when radiative cooling is likely: outdoor ≤ 2 °C, wind
under 2 m/s, no measured rain, and the sun down (measured, or estimated from the sun position when there
is no light sensor). The controller receives no cloud reading, so a cloudy night counts as clear — missing
a frost is the expensive mistake, and a wrongly raised watch costs only a closed curtain. Frost protection
therefore stands at an indoor 4 °C on a clear still night.

**Crops.** Frost is a physical line (ice forms near 0 °C), so it is fixed — but never above your own limit:
the protection line is the lower of 2 °C and **Min Temperature − 1 °C** (watch = protection + 2 °C). With
Min Temperature at 9 °C (a tomato nursery) the lines stay at 4 / 2 °C; below 9 °C that is cold, not frost,
and the Min Temperature limit handles it (reason 33). A crop that tolerates freezing, with Min Temperature
at 1 °C, gets lines of 2 / 0 °C. There is no separate setting.

**Not flapping.** A stage starts at once and ends only when the indoor reading is 1 °C above its line
**and** 30 minutes have passed since the stage was last needed; protection may drop straight to nothing.
If the indoor reading is lost, a standing stage holds for up to 30 minutes and then ends; it never starts
without a reading. The stage survives a restart (memory of the last 30 minutes).

**With the other rules.** Frost and [Extreme Heat Protection](#heat-protect) never stand together: while
frost is on, heat protection is released and does not start. Frost wins over the night humidity gap of the
thermal curtain (reason 46), the morning ramp (47) and the sun-load and morning-purge vent floors (51, 54):
the curtain stays closed and a vent is not opened further. Where rain and frost both limit a vent, the rain
cap stays. Together with the Cold Emergency, that gate's values stand and frost adds the circulation fans
and the mist, CO₂ and cooler shut-off. A device that does not exist gets no command (a facility with no heater
still closes up, and the alert e-mail says it cannot warm). The facility check reports the minutes spent
in frost watch and protection.

### Post-Gate (checked after L3, before dispatch) { #post-gate-checked-after-l3-before-dispatch }

| Check | Action |
|-------|--------|
| Non-finite command (NaN/Inf) | Actuator falls back to its safe default. |
| Out-of-range command | Clamped to [0, 100]. |
| Manual Lock active | Overrides with the locked value. |
| No water for misting ([Misting Water Supply](#water-supply)) | Every mister is forced to 0 — even one under Manual Lock, because a pump must not run dry. |
| Suspected actuator held (reason 42) | Not sent at all — it stays where it is ([Suspected actuators](#actuators-suspected)). Commands that a safety gate, a hard limit or extreme-heat protection put in its place are still sent. |
| Cooler and heater both ON at once (both above 5 %) | Not allowed. Checked **last**, after the hard-limit responses, and the side whose command has the stronger source wins — safety gate > extreme heat protection > manual lock > normal control. On a tie, the lower cost index wins; the other side is forced to 0. L3 also rests the side opposing the temperature demand in advance (the heater when too warm, the cooler when too cold), so this check is rarely reached. |

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
| Vents are closed on a very hot afternoon | During [Extreme Heat Protection](#heat-protect), vents close when it is hotter outside than inside — opening would let hotter air in. The facility popup says *Extreme heat — it is hotter outside*. Shade, cooling and (if the air can still take up water) misting do the cooling. |
| Vents stay closed at night | Expected when **Close at Night** is on — the facility popup says *Closed for the night*. Hard temperature/humidity limits and safety gates still break it. |
| Outdoor readings are reported as missing | Max Sensor Age may be shorter than the source's own period. Leave it at 0 so each sensor is judged by its own interval. |
| Heating and cooling both ran | The interlock just before dispatch forbids it ([Post-Gate](#post-gate-checked-after-l3-before-dispatch)). A configuration whose guide range is wider than the hard limits is warned about at save time rather than blocked, and the coordinator narrows the guide range to fit inside the hard limits. |
| A setting appears to be ignored | It may be conditional — the custom actuation period applies only to the *Custom* profile, and the night clock times only when night is measured by fixed times. The screen reports values entered but unused. |
| Every device is holding still | Indoor measurements may have disappeared. When temperature or humidity cannot be measured, that axis leaves control, and a device with no measurable axis left **does nothing** — it neither closes nor opens. The facility popup says *Holding — cannot measure right now*, and the log records it once. Check the sensor connections and Max Sensor Age. |
| A device drawn on the map does not appear in control | It may be a kind that control does not handle (vents, shade screens, thermal curtains, heating/cooling, misting, CO₂, supplemental light, fans). Such equipment is left out of registration and that is logged once — change its kind in the facility editor to bring it in. |
| A facility change isn't taking effect | Run **Reload Actuators**, or deactivate and reactivate the function. |
| The watchdog reports a long outage | An intentional pause — outside the working-hours window, or with no actuators registered — is reported as a pause, not a fault. A genuine outage still warns. |

### Reason codes and log channels { #log-codes }

The facility popup gives each device a reason, and the coordinator writes its decisions to the function's log channels. These belong to the features described on this page.

| Reason | Shown as |
|---|---|
| 28 | Extreme heat — it is hotter outside, so the vents stay closed |
| 29 | Extreme heat — misting cannot cool the air right now |
| 40 | Extreme heat protection put this command in |
| 41 | No water for the misters |
| 42 | This device looks faulty — held in place |
| 43 | Shade drawn against the heat |
| 44 | Shade kept open |
| 45 | Shade held where it is |
| 46 | Thermal curtain opened a crack to let night moisture out |
| 47 | Thermal curtain opening in steps |
| 48 | Held at its current opening — the vents are about to close for the night |
| 49 | Thermal curtain closed to keep the night heat in |
| 51 | Kept open to let the sun's heat out — sunny and above the temperature target |
| 52 | Limited for rain — roof vents shut, side vents opened only part way |
| 53 | Wet misting is held back as the light fades — leaves would stay wet overnight |
| 54 | Slightly open to let the night's moisture out — the sun is warming the house and the air outside is drier |
| 55 | Limited for wind — opened only part way, windward side kept shut |
| 56 | Frost protection — kept sealed and warm so frost does not form on the crop |
| 57 | Extreme heat and dry air — one short misting burst is allowed through the sunburn lock |
| 58 | Closed while the outdoor reading is missing — it is night, so a small opening is shut |
| 59 | Circulation fans on — the night air is close to its dew point, and moving air shortens how long the leaves stay wet |
| 60 | Indoor reading missing — opened a little because a closed house heats fast in the sun (closed again after sunset) |

| Channel | Holds | Written |
|---|---|---|
| 75 | [Extreme heat protection](#heat-protect) stage (0 none · 1 protection · 2 severe) | every cycle |
| 76 | What protection decided (bit mask) | every cycle |
| 80–89 | Sensor status per axis | with debug logging |
| 90 | Where the controlling VPD came from | with debug logging |
| 91 | Device VPD minus controlling VPD (kPa) | with debug logging |
| 92 | [Misting water supply](#water-supply) (1 water · 2 low · 3 signal missing) | every cycle, with the check on |
| 93 | Suspected actuators held | every cycle while any is held |
| 94–96 | VPD target basis · leaf VPD · leaf target | every cycle, with a leaf sensor bound or the leaf basis chosen |

---

## AI Integration { #ai-integration }

The AI in AoT's chat, and an AI connected over MCP, use the following tools to look at
this coordinator. Every write tool goes through human approval.

| Tool | What it does |
|------|--------------|
| `get_control_state` | Read. Per coordinator: targets, tolerances, priorities, safety ranges and operating windows, plus the latest cycle's actually-applied targets, limiting factor, safety-gate status and each device's command with its reason. This is what to read before advising on control. Each coordinator's latest cycle also carries the current VPD, labelled: `vpd.air_kpa` is the air VPD computed from temperature and humidity, and `vpd.leaf_kpa` (with `leaf_temp_c`) appears only when a leaf temperature is actually measured. The target's basis (`air` or `leaf`) is reported as `vpd_basis`, so a deviation is never read against the wrong VPD. |
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
