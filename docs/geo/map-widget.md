# AoT_map Widget

`AoT_map` is a dashboard widget that shows the sensors and devices scattered across your greenhouses on a single map, and lets you control them right there. Say you have 20 irrigation valves and 10 temperature/humidity sensors spread across 5 greenhouse bays — this one widget lets you see the whole layout at a glance, click a device to turn it on or off immediately, and check each location's latest readings and AI advice. It's built on MapLibre GL, so it supports 3D terrain, 3D facility rendering, and smooth zooming.

![AoT Map widget — device markers, the measurement panel, and the map's tool buttons](../images/aot-dashboard-map.png)

---

## Adding the Widget { #adding-the-widget }

1. On the dashboard, select **Add Widget → AoT Map**.
2. In the settings, choose the map to display (leave empty to use the most recently modified map).
3. Click **Save**.

---

## Key Features

### Device Markers { #device-markers }

Input, Output, and Function devices placed in **Device** mode in `/geo/design` appear as markers on the map.

- **Marker color**: Changes automatically based on the device's active/inactive/error state.
- **Overlap handling**: When markers overlap at a low zoom level, they collapse into a single badge showing the count; zooming in spreads them back out into individual markers.
- **Device icons**: Icons vary by device type (temperature sensor, relay, pump, and so on).

### Control Right From the Popup { #control-right-from-the-popup }

Clicking a marker opens the window that fits the device type.

**Input (sensor)** — clicking a value key opens a detail window with a 24-hour
chart, the current reading of every measurement, and a shortcut to write a note.
It is the **same window** you get when opening a sensor from a facility or zone
modal.

**Output / function** — opens the same centre window zones and facilities use,
in three blocks from the top:

1. **Control** — the device name and an On/Off toggle (shown only to users with
   **edit** permission), with the run time and the next scheduled run below it,
   and for an on/off output a **Settings** button as well. It comes first
   because operating the device is usually why the window was opened.
2. **History** — the recent run chart, which is what backs that decision up.
3. **Notes**

The run time is **one slot shared by two states**. While the device is off it
shows how long it last ran (dimmed); the moment it turns on that same slot
becomes a live running timer (bold). It keeps following the device while the
window stays open, even if another window or a schedule switches it.

Position actuators (windows, curtains, …) get Close/Stop/Open buttons in place of the toggle, and a PWM output shows its current percentage with a 0–100% slider. Neither gets the **Settings** button.

A composite device runs nothing of its own, so its window opens with **Contents** — the sensors and devices held inside it — and no history. Click a line to drop into that device's own window.

Clicking a Facility marker shows a 3D preview and an environment-data summary — see [3D Facility Popup](#3d-facility-popup) below.

### Click a Zone/Site — Control From a Device List { #click-a-zonesite-control-from-a-device-list }

Clicking a Zone or Site shape opens a popup listing every sensor and output device placed inside it.

- **Sensors**: If there's more than one, switch between them with tabs to see a 24-hour chart.
- **Output device list**: On/Off toggle for immediate control (requires **edit** permission), drag to reorder.
  Run times follow the same rule as the device window (off = last run, on = live timer), with the next scheduled run beside them.
  Click a device's name and its run history is drawn in the chart area above.
- **What else it affects**: Right under the toggle, a device that also covers other plots names them, so what a switch-on touches is readable before you press it.
- **Functions**: Functions in the area are listed below the device list, each with its type and an On/Off switch that activates or deactivates it. A composite device opens its own window when you click its name.
- **Settings (schedule on)**: Each output has a **Settings** button — see [Scheduled On](#scheduled-on).

The order you drag the devices into belongs to the **zone**, so everyone who opens that zone sees the same order. A Site window has no stored order of its own.

### Clicking a Plot — What Is Here { #plot }

Plots drawn in the design tool's [Plot mode](design-tool.md#plot) appear on the map; clicking one opens its operational view. The window has three tabs: **Overview / Environment & Control / Settings**.

- **[Overview] > Resources** — two layers: what the current stage declares it needs, and under it, for each irrigation device that reaches this plot, how long it ran **today** and over the **last 7 days** and how much water that is (estimated), with a **Total** row once more than one device has a volume. The volume is designed flow (a facility's piping layout, or the emitters drawn on an outdoor map) x run time x the plot's share, so it is **not a flow-meter reading**. A device with no run in the window says so rather than showing 0. A device whose volume cannot be worked out gets no row at all — the note **below the table** names it and says which reason applies: no emitter is mapped inside this plot, or the flow rate is unknown. That same note says once, for the table as a whole, that the figures are estimates and what the plot's share is. If an area lying over this plot has no device assigned to it yet, **[Overview]** says so too — that is a missing means of control, not a device to list. For the same figures broken down by period, use the [Journal](journal.md).
- **[Overview]** — a **Program stages** card with the current stage, days elapsed, accumulated heat and the current stage's guidance, plus a live **Environment** card with day-of-target readings including **GDD** (accumulated heat since the season started, [see Journals](journal.md#gdd)) and **DLI** (today's light vs. target, [see Journals](journal.md#dli)) where the program and sensors support them. If either can't be calculated, the card says why (no program, no base temperature, not enough measured days) instead of just showing nothing.
- **[Overview] > Stage change** — when the calculation says the next stage has begun, **Confirm** or **Postpone** it here. The record of confirmed changes (**Stage log**) and **Undo last** are under **[Settings] > Program**. Stage targets are shown next to the current readings in the **Environment** card. See [Management Programs](programs.md#stage-events).
- **[Settings] > Stage schedule** — where the real schedule is edited. Programme lengths are only a reference, so stages can be **postponed or pulled forward**, and this one plot can be set to advance automatically. See [Editing the schedule](programs.md#stage-schedule).

!!! note "Targets are read-only here"
    This popup shows each stage's targets but does not edit them — [overriding a plot's own target](programs.md#plot-override) is done from the [`/plots` page](programs.md#plots-page) or the [AoT Plot widget](plot-widget.md), not from the map.

- **[Settings] > Plot information** — area and dimensions; width and length are shown together, because area alone cannot answer "how many rows fit here?".
- **[Settings] > Basics** — subject, variety, plot name, start date and expected end; change them with **Edit**.
- **[Environment & Control], control list** — the devices whose area overlaps this plot, most overlap first, each showing how much of the plot it covers and, where it reaches other plots as well, their names. One area covers several crops and one crop may straddle two areas, so no single device is designated; the overlapping areas are shown as they are. Percentages are **relative to the plot** ("how much of my bed is covered"). What the device actually does is not something the system knows — only that the two areas overlap — so the screen says "covers", not "waters".
- **[Environment & Control], sensors** — sensors inside the plot. If there are none, or the ones inside have stopped reporting, the closest sensor in the parent zone is borrowed and tagged with its distance; the tag's tooltip says which of the two reasons applies. A sensor inside the plot that is not reporting keeps its place with a **no data** tag instead of disappearing, and the ones that are reporting come first so the tab that opens is not an empty chart.
- **[Overview] > Notes** — the same shared notes block as other shapes.

!!! note "Per-crop requirements are not apportioned"
    Water is physically shared across overlapping areas, so summing per-crop **requirements** produces a wrong number. The widget shows the inputs and leaves the judgement to you. (How much water actually went out is a different question, answered under **[Overview] > Resources** above.)

Plot labels (chips) follow the same **Hide Labels When Zoomed Out — L1** threshold as other labels (default 17) — the map already carries many labels, so always-on labels would collide. Plot shapes are toggled from the layer control or the **Plot Shape** setting (both share the same value); plot labels are turned off separately under **Layers → Labels**.

### Choosing the Representative Measurement { #representative-measurement }

The **Overview → Environment** card of a zone or facility window lists the readings inside
it side by side. **Click a value and that measurement becomes the representative
one**; it keeps a filled background so you can see which one is chosen. Click it
again to clear (requires **edit** permission).

The choice is shared by three places:

- the value on the **facility chip** on the map
- the value on the zone/facility row of the **site** window
- the Environment card itself (the highlight)

With nothing chosen, the order is VPD > temperature > humidity > CO₂ > light >
wind speed. The choice is stored **per zone and per facility**, so a nursery can
show temperature while an open field shows soil moisture. While the chosen sensor
has no fresh reading the automatic order takes over temporarily; the choice comes
back as soon as the sensor reports again.

### Scheduled On { #scheduled-on }

The **Settings** button on an on/off output opens a window for picking a start
time and a run time. It is the same window whether you open it from a zone modal, a
facility modal, or a device marker popup.

- Leaving the run time at `00:00` keeps the device on until you turn it off manually.
- If the start time is effectively "now", it turns on immediately and switches off once the run time is up.
- If the start time already went by earlier today, it is moved to the same time tomorrow rather than firing on the spot.
- If the start time is in the future, it is **registered with the server scheduler**.
  It runs as planned even if you close the browser, and you can review, edit, or
  cancel it on the [Scheduler](../ai/scheduler.md) page.
- If registering fails (for example, you do not have permission for that device), you are asked
  whether to fall back to having the current tab wait and fire instead. Only in
  that case does closing the tab prevent it from running.

Under the two dials, a line states what you picked — when it turns on, when it turns off, and how long it runs. If that stretch overlaps a schedule already on the device, the line says so and names the time it will actually switch off, because whichever timer ends first turns it off. Below that the window lists the schedules already on this device so you can cancel one, and it stays open after you save.

Position actuators (windows, curtains, …) do not get this button — "on from X until Y" has no meaning for them.

### Real-Time Refresh

The widget automatically refreshes device state at a configured interval (default: 5 seconds). Marker colors and measurement labels update live, and values keep refreshing even while a popup is open.

### Map Tool Buttons

The following tool buttons appear in a corner of the map:

| Button | Function |
| :--- | :--- |
| +/− | Zoom in / out |
| Fullscreen | Display the widget in fullscreen |
| Search | Search an address and fly to it |
| My Location | Move to your browser's GPS position |
| Reset | Return to the originally saved position and zoom |
| Site List | Pick a registered site or zone and jump straight to it |
| Copyright (ⓘ) | Shows the attribution for the currently displayed base/overlay maps. Opens automatically when the map first loads or when you switch the base/overlay, and collapses when you interact with the map (drag, zoom, touch). |

Separately, the widget's title bar has **Lock Map** (locks panning/zooming) and **Hide Controls** (hides the tool buttons) icons. These are toggled directly from the title bar, not from the settings form.

---

## Widget Settings { #widget-settings }

These follow the order of the settings panel. The collapsible groups (Data
Transfer Period, Device Filter, Measurement Panel, Label Style, Shapes, 3D Map)
expand when clicked.

### Map { #map }

| Option | Description |
| :--- | :--- |
| Select Map | The saved map to display. Leave empty to use the most recently modified map. |
| Show Labels | The master switch for all site/zone/facility/device/sensor labels. Fine-tune which types show up under **Layers → Labels** in the map's right-hand tools. |
| Display Data Only (Hide Map) | Hides the map background and overlays, showing only the side measurement panel. |
| Show AI Advice | Shows the latest AI advice summary for this map's facility/site as a clickable chip at the top of the map (requires the global AI to be configured). |
| Show Local Time | Shows a three-cell dock at the top-centre of the map with the time **for wherever the map is centred** — the current time in the middle, the sun event that just passed on the left, and the next one on the right. So it reads `sunrise · now · sunset` during the day and `sunset · now · tomorrow's sunrise` at night. Pan the map and it recomputes for that location's timezone. When the map's local date differs from your browser's, the clock also carries that date, and hovering it names the timezone (or says the location's timezone could not be resolved and the farm timezone is being used). Where the sun does not rise or set, an extra cell reads **Midnight sun** or **Polar night** in place of the events. Scroll the wheel over the small circle at its bottom-left (drag vertically on a phone) to resize the clock; the size is saved with the widget. While it is on, the address search bar and AI advice chips move below it. |

!!! note
    Switching **Select Map** to a different map automatically resets the stored position and zoom, so they can be re-fit to the new map.

### Data Transfer Period

| Option | Description |
| :--- | :--- |
| Widget Refresh Period (Seconds) | How often the widget refreshes. **Set to 0 to disable auto-refresh.** (Default: 5s) |
| Input Value Refresh Period (Seconds) | How often input measurement values in the panel are refreshed. (Default: 300s) |
| Output Status Refresh Period (Seconds) | How often output on/off status is refreshed on the map. (Default: 5s) |

### Device Filter { #device-filter }

| Option | Description |
| :--- | :--- |
| Input / Output / Function | Choose which devices of each type to **hide** from the map (an exclude list). If none are selected, every device placed in `/geo/design` is shown — only use this to hide specific devices. |

### Measurement Panel { #measurement-panel }

| Option | Description |
| :--- | :--- |
| Show Measurement Panel | Shows the measurement panel. Turn it off to hide the panel entirely even if measurements are selected below (the selection is kept and comes back when you turn it on again). |
| Input / Output / Function | Choose which measurements of each type are shown in the side data panel. |

What you pick is saved as you pick it, and the panel redraws with the new selection without a page reload.

### Label Style

Applies to **both** name labels (site/zone/facility) and value keys (input sensor
readings). Whether they show at all still follows the **Show Labels** master
switch above.

| Option | Default | Description |
| :--- | :--- | :--- |
| Prevent Label Collision | On | Clusters overlapping labels automatically. **The more specific label survives** — function > input > output > equipment > facility > zone > site claim space in that order, and whatever yields is surfaced as a `name +N` badge rather than disappearing silently. |
| Label Text Size | 1.0 | Font size (em) of every map label and value key. 1.0–3.0. |
| Hide Labels When Zoomed Out — L1 | 17 | Below this zoom level, output / input / function / equipment / sensor / plot / bay / note labels and value keys are hidden. Site labels always stay visible so the map keeps its bearings. Zone and facility labels use the wider L2 threshold below. **Set 0 to never hide.** |
| Hide Labels & Shapes When Zoomed Out — L2 | 15.5 | A second, independent threshold for the things that need to stay readable at a wider view than L1: **zone and facility labels**, and **zone / plot / equipment shapes**. Site shapes and device markers are never culled by zoom. A running output normally keeps its label and shape visible even when hidden — but below this zoom it folds away too, unless its window is open. **Set 0 to never hide.** |
| Facility-centric Labels | Off | Switches the per-zoom exposure rules between outdoor-centric (off, default) and facility-centric (on). Stacking order — which label draws on top — is unaffected and is always site > zone > facility > equipment > output > input > function. |
| Sensor Marker Style | Circle (integer value) | **Circle (integer value)** (a compact round marker showing the representative value as an integer, colored by measurement band) or **Text label** (value with unit). |
| Enable Sensor Popup | On | Clicking a value key opens a detail window with a 24-hour chart. |
| Popup Default Tab | Overview | Which tab opens first in the zone, facility and plot windows (**Overview** / **Environment & Control** / **About**). The device window has no tabs. |

!!! note
    Hovering or clicking any label brings it to the very front, whatever its type.
    A label you clicked stays in front until the window it opened is closed.

### Shapes

Toggles, by type, whether the polygons you drew in the design tool are shown as translucent overlays on the map.

| Option | Description |
| :--- | :--- |
| Site Shape | Site boundaries (using the configured theme color). |
| Zone Shape | Zone boundaries. |
| Plot Shape | Plots (what is where). Plot labels follow the **Hide Labels When Zoomed Out — L1** threshold. |
| Facility Shape | Building footprints. |
| Equipment Shape | Shapes for equipment such as pipes. |
| Device Shape | The area a device occupies. |
| Other Drawn Shapes | Freeform shapes made with the drawing tools. |
| Device Shape Opacity | Opacity of the device shapes above (0–100) — 0 is transparent, 100 is fully opaque. |

### 3D Map (Vector Mode) { #3d-map-vector-mode }

| Option | Description |
| :--- | :--- |
| Enable 3D Terrain | Turns on elevation-based 3D terrain (hillshade) rendering. The row appears only when the map engine shipped with your installation can render terrain; the version shipped today cannot, so it is hidden here and a value saved earlier has no effect. |
| Facility Render Mode | How 3D facility (building) models are drawn: **Default (transparent)** / **Solid (opaque)** / **Wireframe** / **Performance (mobile)** (minimizes load). |
| Vector Style URL | A custom MapLibre style JSON, if you need one. Leave empty to use the GIS input setting. |

### Values Saved Automatically { #values-saved-automatically }

These are **not** in the settings panel — the widget remembers them as you use
the map. You never type them in.

| Value | Saved when |
| :--- | :--- |
| Position, zoom, pitch, bearing | You pan, zoom, or tilt the map |
| Active overlay layers / selected base map | You use the map's layer picker |
| Per-type label visibility | You use the toolbar label buttons or the **Layers → Labels** checkboxes |
| Per-type shape visibility | You use the shape checkboxes in **Layers** — the same values as **Shapes** in the settings panel |
| Map lock / hidden controls | You press those tool buttons |
| Local-time clock size, folded or not | You resize or fold the clock |
| Measurement panel split, folded or not | You drag its divider or fold it |
| AI advice chips hidden | You press the toolbar **AI** button |

---

## Legend

A legend is displayed automatically in the bottom-right of the map — there's no setting to configure it. It explains the colors of whichever overlay layers are currently active and the Input/Output device icons; clicking a legend entry toggles that layer or device type on or off.

---

## 3D Facility Popup { #3d-facility-popup }

Clicking a Facility marker or polygon shows a brief 3D preview and an environment-data summary in a popup. The **Overview** pane's environment card includes GDD and DLI the same way a [plot's does](#plot) — for the facility as a whole, regardless of which bay you're looking at. When the facility holds more than one plot, those two figures follow its first plot rather than totalling all of them. The same pane also carries the last irrigation run and any weather hazard coming up, read from the same forecast outdoor areas use. For the full facility view, use the [AoT_facility widget](facility-widget.md).

---

## Site Weather Station { #site-weather }

A site's popup has an **About** pane, and in it a **Weather station** section for telling AoT which of the site's own devices to trust for sunlight and rainfall — values a plot or zone inside that site borrows rather than measuring itself (see [Journals](journal.md#dli) and [day/night targets](journal.md#daylight)).

- **Left unset**, AoT infers a source automatically from what each device measures — a safety net for installations where nobody has touched this setting, not a guarantee. If the site has two solar sensors, or one of them is experimental, there is no way to tell AoT which one is authoritative without setting it here.
- **Checking one or more devices** designates them explicitly; that designation now overrides the automatic guess.
- **Unchecking everything is "not designated," not "off."** It returns the site to automatic inference — it does not stop weather values from showing.

Each row names a device and, under the name, what that device measures; on a site with many devices that second line is often the only way to tell two of them apart. Devices that only switch something are left out, and the ones AoT found on its own are listed first. A line above the list says which rule is in force right now — set here, found automatically, or nothing found at all. Your choices take effect when you press **Apply**, and without edit permission the list is read-only.

---

---

## Multiple Maps on One Dashboard

You can add multiple `AoT_map` widgets to the same dashboard, each showing a different map — for example, an overview map of the whole site alongside a zoomed-in view of one specific bay.

---

## Related Pages

- [Design Tool](design-tool.md) — Placing devices and shapes
- [Facility Widget](facility-widget.md) — The dedicated 3D facility widget
- [GIS Layers](layers.md) — Registering overlay layers
- [Journals](journal.md) — Snapshot documents built from the same GDD/DLI/irrigation data
- [AoT Plot Widget](plot-widget.md) — Dashboard widget for keeping one plot in view, with target editing this popup doesn't have
