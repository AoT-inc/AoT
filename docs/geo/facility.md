# Facility Management

The `/geo/facility` page is where you perform 3D modeling, engineering calculations, sensor/actuator binding, and device checks for buildings such as greenhouses, growing houses, and equipment rooms. The model fills the window; the facility's settings are one settings panel, opened with **Settings**, in six tabs: **Position · Structure · Envelope · Components · Connections · Review**.

---

## Screen Layout

```
Facility Design · [Back to map] · <facility name> <still to do> · [Unsaved changes] · [Save Facility]   ← title bar
[Map | 3D]  Add [Select] [Openings] [Fixtures] [Irrigation] [Sensor]  [View: Direction · Perspective | Isometric · Show in 3D]  [Tools & Export] [Undo]  [Settings]   ← toolbar
┌── Stage: 3D or Map (one at a time, as tall as the window) ──┐   ┌── Settings panel (right-hand drawer; the stage stays in view) ──┐
│                                                              │   │  Position · Structure · Envelope · Components · Connections · Review │
│                                                              │   │  (content of the selected tab)                                     │
└── status line (what is selected · tool hints) ───────────────┘   │  [New Facility] [Duplicate Facility] [Save Facility]               │
                                                                   └────────────────────────────────────────────────────────────────────┘
```

- **Title bar** — **Facility Design**, **Back to map**, the name of the facility that is open with tags for what is **still to do** beside it, an **Unsaved changes** badge and **Save Facility**. The tags are not buttons and name only what is left: **Position to do** (a name, the map or the placement is missing) and **Not connected 3** (components with no device yet). Nothing is said about what is done, so the tags disappear once everything is filled in. Hovering **Position to do** says what is missing (**Enter a name**, **Select a map and place the facility on it**). Dimensions, plan, structure, position and envelope are stored only when you click **Save Facility**. On a saved facility, changes to components and to the **Connections** settings are saved by themselves about 1.5 seconds after you stop editing; the title bar then shows **Saved HH:MM**.
- **Toolbar** — one line above the model. **Settings** at its right end opens the settings panel. **Map | 3D** switches the stage; **Position** opens on the map, the other tabs on 3D, and a view you pick by hand is remembered per tab for the session. On the map: **Clear placement** and **Place on Map**. In 3D: the add tools (**Select**, **Openings**, **Fixtures**, **Irrigation**, **Sensor**; **Fixtures › From the map…** adds components from what is drawn on the map), the **View** menu (**Direction** — the nine preset views, **Perspective | Isometric**, and **Show in 3D** — hide or show each kind in the model; when something is hidden, the count follows **View**), **Tools & Export** (Asset Library · Export PNG/Spec/GLB · Import Spec/GLB · High Quality / Fast Preview · **Rebuild 3D model**) and **Undo**. When the settings panel leaves the stage narrow, **Undo** moves to the top of the **Show more** (= **Tools & Export**) menu so the toolbar stays on one line.
- **Stage — 3D** — the model fills the window down to the bottom and the page does not scroll. Nothing is laid over the model. The status line at the very bottom shows what is selected, the tool that is armed and how to finish it, and the mouse controls.
- **Stage — Map** — click **Place on Map**, then click the facility center on the map. Drag the placed facility to move it; dimensions and rotation update the rectangle as you type.
- **Settings panel** — **Settings** slides it in from the right like a drawer; while it is open the stage stays visible and usable, so you change a value while watching the model. Clicking a component in 3D opens it too, and a new facility starts with it open. **Close** leaves the stage alone. At its top the six tabs sit in one row and only the selected tab's content shows; the tab row stays at the top while the content scrolls, and the arrow keys move between tabs. **Saved Facilities** is a button in the panel header, left of **Close**: it shows the list at the panel's full height, opened at the facility being edited, and pressing it again, or picking a facility, returns to the tab you came from.
- **Components tab** — lists every component by type; rows without a device are tagged **No device** or **No input**. Pick a type next to **Add** above the list to add one at a default position. Selecting a row selects that component in 3D. Components generated together (the roof vents of every span, sharing one device) fold into one row such as **Roof vent ×6**; picking a device on that row applies it to the whole group, and clicking the row unfolds it to show each member. A member detached to use its own device is marked **detached** in the unfolded list and is not changed by the group's choice. A group in which every member uses its own device (the left and right side windows, for example) is not folded.
- **Selected component** — selecting one in 3D or in the **Components** tab turns the panel into that component (name, device, position, size, rotation, opening method, delete); **Back to facility** returns. The **Connections** and **Review** tabs cannot be pressed until the facility is saved, and one line right under the tab row says so.
- **On a phone** — view and small edits only. There is no title bar: one line under the menu holds **Back to map**, **Map | 3D** and **Settings** (the add tools, view menu, map placement and status line are left out), and the open facility's name is the settings panel's title. With the panel closed the model fills the screen; **Settings** opens the same panel covering the screen, and pulling its handle at the top drops it down so the model shows. While it is down the buttons on the line above still work, and **Settings** raises it again. The panel starts with **Placement and plan editing are on a wider screen.** and shows only the tabs **Position**, **Structure** (numbers and switches), **Envelope** and **Components** (**Connections** and **Review** are not shown), or, for a component picked in 3D or the list, its name and device. Progress is one line such as **3/4 steps · Not connected 2**.

What each tab holds:

| Tab | Contents |
|------|-----------------|
| **Saved Facilities** (button in the header) | the list (select to open · Delete) — **New Facility** and **Duplicate Facility** are at the bottom of the column |
| **Position** | **Map & Site** (Name · Map · Site), **Position** (Rotation) |
| **Structure** | **Structure** (Structure · plan · Bays · Spacing · Zones), **Specification** (Groups that can operate this facility · Preset · Span · Eave Height · Ridge Height · Length · Roof Type), **Capacity Preview**, **Zones** (the zones of the plan, when one is drawn) |
| **Envelope** | **Covering & Ventilation**, **Curtains** |
| **Components** | the component list and **Add**, **Irrigation** (auto-generate pipes, irrigation devices and valves) — **Auto-generate…** in the toolbar's Irrigation menu opens this tab |
| **Connections** | **Weather** (forecast Inputs), **Groups** (leader/follower groups of same-kind actuators), **Label Color** (color ranges per measurement item) — available once the facility is saved |
| **Review** | **Device Check**, **IEC Integration Summary**, and the link line to the Plots page — available once the facility is saved |

What is grown in each zone is recorded on the Plots page, not here — the last line of the **Review** tab links to it.

---

## Facility Registration Flow { #facility-registration-flow }

```
Open /geo/facility  (Facility Design › Open in the Facility settings of /geo/design, a facility on the map, or the address directly)
         ↓
Position › Name · Map (Site is optional) → Place on Map → click the facility center on the map · Rotation
         ↓
Structure › structure, dimensions, roof → Envelope › covering, vents and curtains → check it in 3D
         ↓
Toolbar › place sensors and actuators on the model → select each one → connect its device in the settings panel
         ↓
Save Facility
         ↓
Connections › weather services, actuator groups, label colors → Review › Device Check
```

- A facility is created on this page, by **Save Facility** — you do not draw it in `/geo/design` first. Saving also puts the facility's outline on the selected map.
- Opened without a facility, the page starts on a blank new facility with the **Position** tab open on the map. Opened from a map, that map is already selected. Saved facilities are opened from the **Saved Facilities** list; the address then carries `?facility_uuid=`, so a reload or bookmark reopens the same one.
- Saving needs a map and a placement — without **Place on Map** the save is refused. The name can be left empty, but the **Position to do** tag in the title bar keeps saying **Enter a name**.
- **Duplicate Facility** copies the facility that is open; its connected sensors and outputs are not carried over.
- The **Connections** and **Review** tabs — and with them **IEC Integration Summary** and **Device Check** — work only after the facility has been saved.

---

## Envelope Configuration

The building's shape and skin are set in the **Structure** and **Envelope** tabs — structure, bays and plan under **Structure › Structure**, dimensions under **Structure › Specification**, then **Envelope › Covering & Ventilation** and **Envelope › Curtains**; its rotation is under **Position**. All of it feeds the heating/cooling load calculation and the 3D model, which follows each change as you make it.

What the **Envelope** tab holds about the skin:

- **Covering & Ventilation**
    - **Outer (full)** — the outer covering; it is always there, you only pick its material.
    - **Inner cover** (toggle) — a second, inner covering: **Cover layers** (material) and **Airgap** (m).
    - **Side reinforcement** (toggle) — **Cover layers**, **Position** (X− · X+ · Y+ · Y−) and **Depth** (m, how far it stands out from the wall).
    - **Front reinforcement** (toggle) — **Position** (Y+ · Y−) and **Depth** (m).
    - **Outer side vent** (toggle) — side windows along the side walls, in **1 stage** or **2 stages**; with two stages, each stage gets its own height and start height (m).
    - **Outer roof vent** (toggle) — roof vents, **Position** **Center** or **Left/Right**.
- **Curtains**
    - **Ceiling thermal curtain** (toggle) — **1 layer** or **2 layers**.
    - **Wall thermal curtain** (toggle) — follows the side-vent stages.
    - **Shade curtain** (toggle) — **Transmittance**: the fraction of light that passes when fully closed (0.30 lets three tenths through). Left empty, 0.50 is assumed.

Vents and curtains switched on here appear as components marked **From envelope** — in the settings panel's **Components** tab and in the panel when you select one — where you connect the actuators that drive them.

### Structure Type { #structure-type }

Picked under **Structure › Structure**.

| On screen | Value | Description |
|-----------|-------|-------------|
| **Single-span** | `single` | Each bay stands on its own. With more than one bay they stand in a row, **Spacing (m)** apart. |
| **Multi-span** | `connected` | The bays share side walls and form one building; there is no spacing field. |

### Covering Materials { #covering-materials }

The materials offered in the covering dropdowns of **Envelope › Covering & Ventilation**, with the values the load calculation uses:

| Code | Name | U-value (W/m²K) | Light transmittance | Offered for |
|------|------|----------------|---------------------|-------------|
| `vinyl_single` | Vinyl (single) | 6.0 | 85% | Outer (full) · Side reinforcement / Inner cover |
| `vinyl_double` | Vinyl (double) | 4.0 | 78% | Outer (full) · Side reinforcement |
| `po_film` | PO film | 6.5 | 85% | Outer (full) · Side reinforcement |
| `pe_film` | PE film | 6.5 | 85% | Inner cover |
| `polycarbonate` | Polycarbonate | 3.0 | 78% | Outer (full) · Side reinforcement / Inner cover |
| `glass` | Glass | 5.8 | 85% | Outer (full) · Side reinforcement |
| `non_woven_fabric` | Non-woven fabric | 3.5 | 50% | Inner cover |
| `air_cushion` | Air cushion | 2.8 | 75% | Inner cover |
| `film_white_opaque` | Opaque white film | 6.5 | 0% (opaque) | Outer (full) · Side reinforcement / Inner cover |
| `film_grey` | Grey film | 6.5 | 0% (opaque) | Outer (full) · Side reinforcement / Inner cover |
| `film_black` | Black film | 6.5 | 0% (opaque) | Outer (full) · Side reinforcement / Inner cover |
| `sandwich_panel` | Sandwich panel | 0.45 | 0% (opaque) | Outer (full) · Side reinforcement / Inner cover |
| `concrete` | Concrete | 3.1 | 0% (opaque) | Outer (full) · Side reinforcement |
| `brick` | Brick | 2.4 | 0% (opaque) | Outer (full) · Side reinforcement |

### Bay Configuration { #bay-configuration }

- **Structure › Specification**
    - **Preset** — **Standard Arch**
    - **Span (m)** — width of one bay
    - **Eave Height (m)** — floor to eave
    - **Ridge Height (m)** — floor to ridge; the difference from the eave height is the height of the roof
    - **Length (m)** — length of the building
    - **Roof Type** — **Arch**, **Gable**, **Gable ×2** (two ridges on one bay) or **Flat**
- **Structure › Structure**
    - **Bays** (N) — 1 to 20
    - **Spacing (m)** — gap between bays; **Single-span** only
    - **Zones** — shown from two bays up. Click the boundary between bays to split or merge zones; the map widget and per-zone environment control use them.
- **Position › Position** — **Rotation** (°), 0–359, typed as a number (drag the facility on the map to move it)

### Plan Drawing { #plan-drawing }

For more than one floor, or a shape that is not a plain rectangle, open **Structure › Structure › Draw plan**. A facility with one rectangular floor can ignore this: nothing else on the screen changes.

The stage turns into a plan seen from above, north up. The settings panel shows the floors, the tools and the values of what you selected; **Close plan** at its bottom leaves the plan.

- **Add floor above** — a new floor starts empty with the outline of the floor below as a guide. **Copy floor below** starts it the same way: outlines, zones and boundaries are copied, crops and floor openings are not, and a curved or gable roof moves up to the new floor. You only enter the **Floor height (m)**; each floor's elevation follows from the floors below. Only the top floor can be deleted.
- **Draw outline** — press two opposite corners. **Draw by points** places one point at a time; press the first point again to close the shape. Points snap to existing corners, then to right angles, then to a 0.5 m grid. An outline may not overlap another one on the same floor. An L-shaped greenhouse is two rectangles side by side. Curved and gable roofs need a rectangular outline.
- **Split zone** — press one wall, then the opposite wall. The larger piece keeps the zone's identity, so plots placed there stay put.
- Press a line between two zones to choose **Wall**, **Curtain** or **Open gap**, or to **Merge zones**. A line between two touching outlines works the same way.
- **Floor opening** — for stairs or a double-height space, on any floor above the first. Press two opposite corners on that floor.
- **Undo** steps back through the changes. Nothing is stored until you press **Save Facility**. If you only look at the plan and close it, the facility stays as it was.

Fitting positions never move when the plan changes. If a change puts devices in a different zone, the editor says how many before saving.

Once a plan is saved, the map shape is derived from the outlines of all floors, and the structure, bay count, span, length, heights and roof type above are locked: change them in the plan. **Structure › Zones** lists the zones you drew. **Environment control does not use these zones yet**: it keeps working from the stored dimensions and the zones it had. The capacity preview shows the floor area, volume, glazing and envelope of the plan (the zones add up to the floor total); heating, cooling and vent open stay reference values from the stored dimensions.

To place a device on an upper floor, select that floor in **Show in 3D** (toolbar **View** menu) and place it on the floor. A spot outside that floor, or over a floor opening, is refused with a message.

Coordinators and plots connect through the saved zones.

- A crop in a split zone becomes a candidate for the coordinator of the saved zone that covers its width.
- Upper-floor zones and zones outside the saved width have no coordinator to connect to. **Structure › Zones**, the plan, the save notice, and the zone choices for a plot all say so.
- A plot in an upper-floor zone is not under environment control, even for a coordinator with no zone set: it is never a candidate, and the plot screens say so.
- Upper-floor devices stay out of the environment control inputs. Upper-floor sensor values do not mix into the ground-floor control values, and coordinators do not move upper-floor devices. They still appear on screen and can be operated by hand.
- A zone total stays with the original zone when you split it. When you merge zones, totals with the same unit are added.

---

## 3D Preview { #3d-preview }

With the stage set to **3D**, the building is drawn with Three.js, and the model follows the values you change in the settings panel as you edit them.

- **Right mouse drag**: Rotate
- **Left mouse drag**: Pan (click to select)
- **Scroll**: Zoom

The **N arrow** on the floor is this facility's true north (it follows the rotation set under **Position**). The default view looks from the south toward the north, so right is east and far is north — the same left/right and front/back as a north-up map. In the toolbar's **View** menu, the northern views under **Direction** look from the north, so east appears on the left there.

A facility saved with a multi-floor structure model shows its floors in the **Show in 3D** (toolbar **View** menu), topmost first. Pick a floor to hide everything above it and look at that floor as a section. A single-floor facility has no floor rows, and the 3D view on the map always shows the whole building.

### 3D Asset Mode { #3d-asset-mode }

Instead of automatic parametric generation, you can apply a custom GLTF model.

1. Upload a GLTF file at `/geo/model_assets`.
2. In the toolbar, open **Tools & Export › Asset Library** and select the model.
3. To go back to the parametric model, click **Detach Asset**.

---

## Engineering Calculations { #engineering-calculations }

Calculates first-order reference values for heating/cooling and ventilation capacity based on the building envelope (±5–10% margin; for equipment estimation purposes only).

The values are recalculated automatically whenever dimensions or materials change, and shown under **Capacity Preview** in the **Structure** tab:

| Item | Unit | Description |
|------|------|-------------|
| Floor | m² | Footprint area of the building |
| Volume | m³ | Enclosed air volume |
| Glazing | m² | Covering area of the envelope (side walls + roof + end walls) |
| Vent open | m² | Total open area of the vents and openings |
| Heating | kW | Envelope transmission + infiltration loss |
| Cooling | kW | Solar gain + crop transpiration load |
| ACH | /h | Air changes per hour — natural ventilation plus the fans |

Heating and Cooling show the calculated load. Once a capacity is set on the actuators, their total is shown instead; hover the value to compare that nameplate total with the calculated load.

### Natural Ventilation Wind Pressure Simulation { #natural-ventilation-wind-pressure-simulation }

The `/api/geo/facility/<uuid>/wind` endpoint accepts building geometry plus wind direction/speed and simulates ventilation performance.

The query values are `speed` (wind speed in m/s, default 3.0), `dir` (meteorological wind direction 0–359°, where 0 means wind from the north, default 0) and `pct` (opening aperture 0–100%, default 100).

The answer gives the effective air changes per hour — the smaller of total inflow and outflow — plus the two totals, and for each opening its open area, pressure coefficient, hourly airflow and whether air goes in or out. An opening facing into the wind takes positive pressure and draws air in, one facing away takes suction and lets air out, and one edge-on to the wind passes almost nothing. Roof openings are treated as direction-independent and vent a fixed fraction of the wind speed.

The same wind reading also weights the opening commands that environment control sends:

| Wind | Weight on the opening command |
|------|-------------------------------|
| Below 0.5 m/s | None — every opening moves to the commanded position |
| 0.5 – 3.0 m/s | Fades in with the wind pressure, so weak, unsteady wind barely changes the command |
| 3.0 m/s and above | Applied in full |

Roof openings are never weighted down, since they vent heat regardless of wind direction, and an opening whose facing is unknown is left at the commanded position. A side opening facing into the wind keeps its command; one facing away is reduced, but never below 20%.

The weights returned with the simulation are the direction-only values at full strength — the `speed` you pass does not soften them.

---

## Sensor & Actuator Binding { #sensor-actuator-binding }

Connect AoT devices to their roles within the facility.

### Sensor Roles { #sensor-roles }

A sensor has no separate role name to pick. What you set on its row — select the sensor in 3D or in the settings panel's **Components** tab, and the panel shows that row — is its role:

| Field | Choices | Meaning |
|-------|---------|---------|
| **— Select channel —** | Measurement channels of Input and Function devices | You can tick several channels of one device (e.g. temperature and humidity of one probe). Ticking a channel on another device moves the whole sensor to that device. |
| Measurement item | **— Auto —** · **Temperature** · **Humidity** · **CO2** · **VPD** · **Solar radiation** · **Wind speed** · **Wind direction** · **Wind gust** · **Precipitation** | **— Auto —** guesses the item from the channel; pick one by hand if the guess is wrong. A gust channel named only "speed" (some stations report the peak gust that way) must be set to **Wind gust** by hand, or it is read as wind speed. |
| Location | **Indoor** · **Outdoor** | Indoor sensors give the facility's indoor values (several are combined as a weighted average); outdoor sensors give the outside conditions. |
| Priority (**Outdoor** only) | **Main sensor** · **Backup sensor** | A backup sensor is used only while the main sensor is silent; the two are not averaged. Within the same priority, a forecast-model input (Open-Meteo and the like) is not averaged with a measured sensor either — it fills in only what no measured sensor provides. For rainfall a fresh measured value always wins over a forecast, whatever the priority. |

Ticking one channel of a device does not throw the rest away: the device's other channels are read as well, as long as a measurement item has exactly one candidate channel on that device — so a weather station bound only by its solar-radiation channel still supplies temperature, humidity, wind speed, wind direction and precipitation. Where one device reports the same item on several channels (a console sending six temperature channels), nothing is filled in automatically, because averaging readings from different places would be wrong; tick the channel you want. A channel you ticked yourself always wins, and an item already ticked on another sensor of the same **Location** is not pulled in a second time.

### Actuator Roles { #actuator-roles }

Every row that is not a sensor has an **Actuator** field (**— None —** or an Output) for the device that drives that component; one actuator can drive several components. What the environment control uses the device for follows from the component type:

| Component | Row settings | Role in control |
|-----------|--------------|-----------------|
| **Fan** | Actuator · **Fan Role** (**Circulation Fan** / **Exhaust Fan** / **Intake Fan**) | The selected fan role (Circulation Fan if unset) |
| **Heater** | Actuator | Heating (the 3D tool is labeled **Heater/AC**) |
| **Humidifier** | Actuator | Humidifying |
| **Curtain** | Actuator | Thermal (insulation) curtain (the ceiling and wall thermal curtains from **Envelope** are this type) |
| **Shade curtain** | Actuator | Shade (the shade curtain from **Envelope**) |
| **Window** | Actuator | Opening, treated as a roof vent (roof vents from **Envelope** are this type) |
| **Side Window** | Actuator | Opening, side vent (lets outside air straight in) |
| **Door** | Actuator | Opening, treated like a side vent |
| **Fixture** | Actuator | Not registered with the environment control |
| **Irrigation Layer** | Actuator — the layer's **Water supply** (pump or main valve) | Registered as a humidifying device when sprinklers are attached; drip-only layers are not used for environment control |
| **Irrigation Valve** | Actuator — one **Zone** inside the layer | Same as Irrigation Layer |
| **Main Pipe** | none | The row is there to select the pipe in 3D and delete it |

**How to register:**

1. Open the **3D** stage.
2. Place components with the toolbar's **Add** menu (**Openings**, **Fixtures**, **Sensor**, **Irrigation**) by clicking a position, or open the settings panel's **Components** tab, choose a type next to **Add** and click **Add**.
3. Select the component in 3D or in the Components tab. In the settings panel, pick the measurement channel for a sensor with **— Select channel —** and set its measurement item and **Indoor**/**Outdoor**. For every other component, pick the actuator that drives it.
4. On a saved facility the change is saved by itself after a moment (**Saved HH:MM**); a new facility needs **Save Facility**.

### Weather Forecast Bindings { #weather-forecast-bindings }

The facility's forecast values (used for pre-emptive control such as warming up before a cold night) come from **Weather** in the **Connections** tab. Each row ties one measurement item, such as **Temperature (°C)**, to one Input channel.

To use an **Open-Meteo Hourly Forecast** Input, click **Fill recommended connections from Open-Meteo forecast Input**. The table is filled with one channel per measurement item:

| Measurement item | Channel it fills in |
|---|---|
| Temperature | Temperature +3h |
| Humidity | Window Max Humidity |
| Wind speed | Window Max Wind |
| Precipitation probability | Window Max Rain Probability |
| Precipitation | Window Max Hourly Rain |
| Solar radiation | Solar +1h |

- Only one channel is filled per item, because several connections of the same item are averaged.
- Each filled row is set to ignore values older than 1 hour (3600 s). A forecast Input refreshes every 30 minutes, so a value that missed two refreshes is no longer used.
- The button only fills the table. Check the rows, then click **Save Facility**.
- If you have more than one Open-Meteo hourly forecast Input, choose the one to use in the list next to the button. If none is active, the screen tells you to add one first.
- A row of the same item that already uses this Input is updated in place (your own row name is kept). Rows that use another Input are left alone and are averaged with the new ones.

---

## Integration View { #integration-view }

The `/api/geo/facility/<uuid>/integration` endpoint returns the current state of all sensors and actuators bound to a facility in a unified response. The AoT_facility widget's environment panel uses this API. For fans, each actuator entry carries the rated airflow (`rated_m3h`) read from the actuator's Airflow spec or, when that is empty, from the airflow set on the fan fitting. Channels of an hourly forecast Input (**Open-Meteo Hourly Forecast**) are never filled in automatically for a sensor, and such an Input cannot be saved as a facility sensor at all — a value for a few hours ahead would be read as a present one. Connect forecasts in the **Weather** tab under **Connections** instead.

---

## Device Check { #device-check }

A diagnostic workflow that briefly runs the facility's actuators to confirm that commands reach them and the sensors respond. It is available once the facility is saved.

1. Under **Device Check** in the **Review** tab, select the devices to test (or **Select All**) and click **Start Check**.
2. The system turns each selected actuator on and off in turn and records how the indoor sensors respond.
3. The result status for each device is displayed:
   - **Normal**: the command was delivered and the sensors responded in the expected direction
   - **Needs Review**: no sensor response, or a response opposite to what was expected (check sensor placement and device wiring)
   - **No Response**: the command could not be delivered (check the device connection)
4. For each device, choose a **Judgment** (Normal / Sensor Suspect / Device Fault / External Disturbance / Skip) and click **Apply Judgment**; the result is applied to the control algorithm settings immediately.

---

## AI Advice Panel

The facility screen has no AI advice panel. Advice from the in-app AI and from other connected AIs is collected under **AI advice** on the **AI → Requests** screen (`/ai`). Accepting a piece of advice only records that you agree — it does not run anything. See [AI Features Overview](../ai/overview.md).

---

## Related API

| Endpoint | Description |
|----------|-------------|
| `GET /api/geo/facility/list` | List facilities |
| `GET /api/geo/facility/<uuid>` | Get facility details |
| `POST /api/geo/facility` | Create/update facility |
| `POST /api/geo/facility/compute` | Capacity calculation preview |
| `GET /api/geo/facility/<uuid>/integration` | Get integrated state |
| `GET /api/geo/facility/<uuid>/wind` | Ventilation simulation |
| `GET /api/aot/facility/<uuid>/runtime` | Real-time runtime state |
| `POST /api/geo/facility/<uuid>/apply` | Apply configuration |
| `POST /api/geo/facility/<uuid>/commissioning/start` | Start a device check |

---

## Related Pages

- [Design Tool](design-tool.md) — Drawing facility polygons
- [Facility Widget](facility-widget.md) — Dashboard 3D widget
- [API Reference](api-reference.md)
