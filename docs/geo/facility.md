# Facility Management

The `/geo/facility` page is where you perform 3D modeling, engineering calculations, sensor/actuator binding, and device checks for buildings such as greenhouses, growing houses, and equipment rooms. Pick a step from the step bar at the top (**Basics · Position & Structure · Envelope · Equipment Layout · Connections · Plot · Review**) to configure it.

---

## Screen Layout

```
Facility Design · <facility name> · [Unsaved changes] · [Save Facility]        ← title bar
[Basics] [Position & Structure] [Envelope] [Equipment Layout] [Connections] [Plot] [Review]   [3D | Map]
├── Stage: 3D or Map (one at a time)
│     3D  — 3D Preview header · placement tools on the left · 3D view
│     Map — [Place on Map] · [Clear]
└── Settings drawer: opens on the right, titled with the current step
      settings for that step · [Previous] [Next] [Cancel] [Save Facility]
```

- **Title bar** — **Facility Design**, the name of the facility that is open, an **Unsaved changes** badge while there are unsaved edits, and **Save Facility**. Nothing is saved automatically: changes are stored only when you click **Save Facility**.
- **Step bar** — clicking a step opens its settings drawer on the right; the current step is shown as a filled button. There are no "done" marks. A step that is still missing something required tells you what when you hover over it (**Enter a name**, **Select a map and place the facility on it**, **Nothing placed yet**, **Not saved yet**).
- **3D | Map** — switches the stage on every step. **Position & Structure**, **Envelope** and **Equipment Layout** open on the map first, the other steps on 3D; a view you pick by hand is remembered per step for the session.
- **Stage — 3D** — the **3D Preview** header holds **Show in 3D** (display filter), **High Quality** / **Fast Preview** (rendering quality toggle), **Undo** and **Tools & Export** (Asset Library · Export PNG/Spec/GLB · Import Spec/GLB · Refresh). To the left of the 3D view are the placement tools: **Select**, **Openings**, **Fixtures**, **Irrigation**, **+ Sensor**, **Catalog**.
- **Stage — Map** — click **Place on Map**, then click the facility center on the map. Drag the placed facility to move it; dimensions and rotation update the rectangle as you type.
- **Settings drawer** — pushes the page aside instead of covering it, so you can watch the 3D view or map change while you edit. On a phone it opens as a sheet under the model, and **Hide model** gives the form the whole screen.

What each step's drawer holds:

| Step | Drawer contents |
|------|-----------------|
| **Basics** | **Saved Facilities** (list · **+ New Facility** · **Duplicate Facility** · Delete), **Specification** (Name · Groups that can operate this facility · Preset · Span · Eave Height · Ridge Height · Length · Roof Type) |
| **Position & Structure** | **Map & Site** (Map · Site), **Position & Structure** (Structure · Bays · Spacing · Zones · Rotation) |
| **Envelope** | **Covering & Ventilation** (covering layers · Outer side vent · Outer roof vent), **Curtains** (Ceiling thermal curtain · Wall thermal curtain · Shade curtain) |
| **Equipment Layout** | **Add Component**, the **Components** table (one tab per type; selecting a row opens its 3D placement right below it), **Places with no device** (only when a device was deleted but its component stayed) |
| **Connections** | **Weather** (forecast Inputs), **Groups** (leader/follower groups of same-kind actuators), **Label Color** (color ranges per measurement item) |
| **Plot** | What is grown in each zone — facility plots need no drawing; the zone itself is the location |
| **Review** | **Capacity Preview**, **IEC Integration Summary**, **Device Check** — the last two are available once the facility is saved |

---

## Facility Registration Flow { #facility-registration-flow }

```
Open /geo/facility  (Facility Design › Open in the Facility settings of /geo/design, or the address directly)
         ↓
Basics › + New Facility → Name and Specification
         ↓
Position & Structure › pick a Map (Site is optional) → Place on Map → click the facility center on the map
                       → Structure · Bays · Rotation
         ↓
Envelope › covering, vents and curtains → check it in 3D
         ↓
Equipment Layout › place sensors and actuators and connect their devices
         ↓
Connections › weather services, actuator groups, label colors
         ↓
Plot › record what is in each zone
         ↓
Save Facility → Review › Device Check
```

- A facility is created on this page, by **Save Facility** — you do not draw it in `/geo/design` first. Saving also puts the facility's outline on the selected map.
- Opened without a facility, the page starts on a blank new facility with the **Basics** drawer open. Saved facilities are opened from the **Saved Facilities** list; the address then carries `?facility_uuid=`, so a reload or bookmark reopens the same one.
- Saving needs a map and a placement — without **Place on Map** the save is refused. The name can be left empty, but the **Basics** step keeps saying **Enter a name**.
- **Duplicate Facility** copies the facility that is open; its connected sensors and outputs are not carried over.
- **IEC Integration Summary** and **Device Check** in **Review** work only after the facility has been saved.

---

## Envelope Configuration

The building's shape is set in two earlier steps — dimensions in **Basics › Specification**, structure, bays and rotation in **Position & Structure** — and its skin in the **Envelope** step. All of it feeds the heating/cooling load calculation and the 3D model, which follows each change as you make it.

What the **Envelope** step holds:

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

Vents and curtains switched on here appear in the **Equipment Layout** step's **Components** table as rows marked **From envelope**, where you connect the actuators that drive them.

### Structure Type { #structure-type }

Picked under **Structure** in the **Position & Structure** step.

| On screen | Value | Description |
|-----------|-------|-------------|
| **Single-span** | `single` | Each bay stands on its own. With more than one bay they stand in a row, **Spacing (m)** apart. |
| **Multi-span** | `connected` | The bays share side walls and form one building; there is no spacing field. |

### Covering Materials { #covering-materials }

The materials offered in the Envelope step's covering dropdowns, with the values the load calculation uses:

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

- **Basics › Specification**
    - **Preset** — **Standard Arch**
    - **Span (m)** — width of one bay
    - **Eave Height (m)** — floor to eave
    - **Ridge Height (m)** — floor to ridge; the difference from the eave height is the height of the roof
    - **Length (m)** — length of the building
    - **Roof Type** — **Arch**, **Gable**, **Gable ×2** (two ridges on one bay) or **Flat**
- **Position & Structure**
    - **Bays** (N) — 1 to 20
    - **Spacing (m)** — gap between bays; **Single-span** only
    - **Zones** — shown from two bays up. Click the boundary between bays to split or merge zones; the map widget and per-zone environment control use them.
    - **Rotation** (°) — 0–359, with the slider or by typing a value

---

## 3D Preview { #3d-preview }

With the stage set to **3D**, the building is drawn with Three.js, and the model follows the values you change in the settings drawer as you edit them.

- **Right mouse drag**: Rotate
- **Left mouse drag**: Pan (click to select)
- **Scroll**: Zoom

The **N arrow** on the floor is this facility's true north (it follows the rotation set in the position step). The default view looks from the south toward the north, so right is east and far is north — the same left/right and front/back as a north-up map. The view cube's N views look from the north, so east appears on the left there.

### 3D Asset Mode { #3d-asset-mode }

Instead of automatic parametric generation, you can apply a custom GLTF model.

1. Upload a GLTF file at `/geo/model_assets`.
2. In **3D Preview**, open **Tools & Export › Asset Library** and select the model.
3. To go back to the parametric model, click **Detach Asset**.

---

## Engineering Calculations { #engineering-calculations }

Calculates first-order reference values for heating/cooling and ventilation capacity based on the building envelope (±5–10% margin; for equipment estimation purposes only).

The values are recalculated automatically whenever dimensions or materials change, and shown under **Capacity Preview** in the **Review** step:

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

A sensor has no separate role name to pick. What you set on its row in the **Components** table is its role:

| Field | Choices | Meaning |
|-------|---------|---------|
| **— Select channel —** | Measurement channels of Input and Function devices | You can tick several channels of one device (e.g. temperature and humidity of one probe). Ticking a channel on another device moves the whole sensor to that device. |
| Measurement item | **— Auto —** · **Temperature** · **Humidity** · **CO2** · **VPD** · **Solar radiation** · **Wind speed** · **Wind direction** · **Precipitation** | **— Auto —** guesses the item from the channel; pick one by hand if the guess is wrong. |
| Location | **Indoor** · **Outdoor** | Indoor sensors give the facility's indoor values (several are combined as a weighted average); outdoor sensors give the outside conditions. |
| Priority (**Outdoor** only) | **Main sensor** · **Backup sensor** | A backup sensor is used only while the main sensor is silent; the two are not averaged. |

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

1. Open the **Equipment Layout** step.
2. Place components with the tools to the left of the 3D view (**+ Sensor**, **Openings**, **Fixtures**, **Irrigation**) by clicking a position, or choose a type under **Add Component** and click **+ Add**.
3. In the **Components** table, pick the measurement channel for a sensor row with **— Select channel —** and set its measurement item and **Indoor**/**Outdoor**. For every other row, pick the actuator that drives it.
4. Click **Save Facility**.

---

## Integration View { #integration-view }

The `/api/geo/facility/<uuid>/integration` endpoint returns the current state of all sensors and actuators bound to a facility in a unified response. The AoT_facility widget's environment panel uses this API.

---

## Device Check { #device-check }

A diagnostic workflow that briefly runs the facility's actuators to confirm that commands reach them and the sensors respond. It is available once the facility is saved.

1. Under **Device Check** in the **Review** step, select the devices to test (or **Select All**) and click **Start Check**.
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
