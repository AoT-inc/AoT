---
guide_id: g10-dashboard
title: Dashboard setup
level: 1
minutes: 40
needs: ["g05-sensors"]
kind: 실습
---

# Dashboard setup

A dashboard is where you gather only what you need on one screen, and it is the screen users look at most every day.
Dashboards are **shared by all users.** The key is to split tabs by "who looks at it, and for what purpose".

Among the widgets, the **AoT Map** widget is the center. On the map you see values from the site, move between sites, zones, facilities and plots,
switch outputs on and off, and leave records, all in one place. [Step 4](#step-4) and [step 5](#step-5) of this chapter cover the map widget.

## When you finish this chapter { #goal }

- You split dashboard tabs by the people who use them and place widgets on them
- You use the map widget to look around the site, check values and handle outputs

## Before you start { #prepare }

- An AoT system that receives sensor values ([Sensor connection](g05-sensors.md#check)). With functions and a map set up, you can use more widgets
- An account that can edit dashboards (Admin or Editor)

## Steps { #steps }

### 1. Split the tabs { #step-1 }

At first there is only one tab. Click **+** at the top of the dashboard page to add another tab
(named "Dashboard {number}"). Click the gear icon and
change the name in **Dashboard Settings**. Tab names must be unique. You can drag tabs to change their order.

Administrators can use **Select Group** in **Dashboard Settings** to choose the groups that can operate that tab. If no group is selected,
anyone can operate it.

We recommend starting with this split.

| Tab | Who looks at it | What it holds |
|---|---|---|
| Site overview | Everyone | Map, a few gauges for key values, function status |
| Inspection | Administrator | Graphs per sensor, sequence and timer widgets |
| By facility | Facility staff | Facility widget, graphs for that facility |

Too many graphs on one tab make it slow. If a tab has more than six graphs, split it.

### 2. Add widgets { #step-2 }

1. Open **Dashboard Settings** with the tab's gear icon and look at the buttons at the bottom. If you see an **Unlock** button, the tab is locked; click it to unlock the tab.
   When the tab is unlocked, a **Lock** button appears in its place. While it is locked, you cannot add or move widgets.
2. Choose a widget from the **Add Widget** list. Its settings fields open.
3. **Name** contains the widget type name (for example, "Function Status"). If you will use several widgets of the same type, change it so that it tells what the widget shows.
4. Fill in the fields under **User Options**, then click **Add Widget** at the bottom.

The **first** time you add a widget of a given type, a "Please wait 10 seconds" screen appears and the web interface restarts once.
Wait, and you return to the dashboard with the widget in place.

Drag a widget by its header to move it, and drag its bottom-right corner to resize it. The position is saved automatically.
Widget settings are saved as soon as you change them. If you do not like a change, click **Revert** to go back to how it was when you opened the settings window.
When you are finished, click **Lock** in Dashboard Settings so that no one moves anything by mistake. The lock only prevents mistakes;
it is not a permission. Anyone with edit permission can unlock it.

### 3. Commonly used widgets { #step-3 }

| Widget | What it shows and what you can do | What you must choose |
|---|---|---|
| AoT Map | The site map with values and outputs on it. See [step 4](#step-4) and [step 5](#step-5) for details | **Select Map** |
| AoT Graph | How several values change over time. Zoom in or use the period buttons to see past values, and reset to return to now. You can turn on night-time shading and export | **Data Source** (inputs, functions, outputs, note tags), display period |
| AoT Circular Gauge, Gauge (Solid) | One value as a needle or bar with color ranges | **Measurement**, minimum and maximum, color ranges |
| Function Status | The current status of one function. You can open and change its options with **Details** (some options cannot be changed while the function is active) | **Function** (conditional and custom functions; for sequences, use the widget below) |
| Sequence Controller | Turns the whole sequential irrigation on and off, and sets the weekdays and time slots it runs. Time slots are shared or per weekday | **Sequence Function** |
| AoT Timer | Turns one output on and off, or repeats run and rest a set number of times. It runs on the server, so it continues even if you close the screen | **Output** |
| AoT Plot | A list of plots, with each plot's stage, current values against targets, and accumulated temperature | **Map or site** |
| AoT Facility | A 3D model of the facility, environment values, targets and device status | The facility's environment control function |
| Calendar | Scheduled events, notes and notices on a calendar | View mode (month, week, list) |
| Notice & Notes Board | View and write notices and notes | The place to show |
| MCP Approval Requests | Approve or reject operation requests posted by AI ([AI & MCP connection](g12-ai-mcp.md)) | None |

### 4. Place the map widget { #step-4 }

1. In **Add Widget**, choose **AoT Map**.
2. In **Select Map**, choose the map to show. If you leave it empty, the most recently edited map is shown.
   All devices placed on the map appear automatically, so you do not need to choose devices separately ([Map setup](g04-map.md)).
3. Set the following if needed. You can leave them as they are at first.
   - **Show Labels**: turns all name and value text on the map on or off
   - **Shapes**: the kinds of shapes to draw on the map (sites, zones, plots, facilities, equipment, devices). At first only plots are on
   - **Device Filter**: inputs, outputs and functions to **hide** on the map. If empty, everything is shown
   - **Data Transfer Period**: the interval for re-reading the widget, values and output status
   - **Label Style**: which labels appear at each zoom level, how sensors are displayed (circle or text), and which tab appears first when a window opens
   - There are also settings such as **Display Data Only (Hide Map)**, **Show AI Advice**, **Show Local Time**, **Measurement Panel**, and **3D Map (Vector Mode)**. Click a collapsed section to expand it
4. Click **Add Widget** and make it large. It is best to make the map widget larger than the other widgets.

If you change **Select Map**, the saved view position is reset.

### 5. Use the map widget { #step-5 }

**Looking around**

- Tools on the left: zoom in and out, compass, **Fullscreen**, **Search Address**, **My Location**, **Reset View**, **Site List**.
  **Reset View** tilts the map and turns it slowly once around; click it again to stop where it is
- **Site List**: shows the sites on this map. Click a site to expand the zones inside it; click it again to move the map to that site
  and open the site window. Click a zone to open the zone window. With control permission, you can drag to change the order
- Tools on the right: **Layers** (choose one **Base Map**, and turn registered overlays, shapes and labels on or off), **Distance measurement**, **Add note** (click the map to add a note at that spot),
  and switches for input, output, plot and facility labels
- In the widget title bar, **Lock Map** stops the map from being dragged or zoomed, and **Hide Controls** hides the toolbars.
  These work separately from the dashboard lock
- A view you have moved or zoomed is saved automatically, and the map starts there the next time it opens

**Viewing values**

- Click a sensor marker to see all channels of that input, a 24-hour graph and the communication status
- Click a zone to open the zone window, divided into the **Overview / Environment & Control / About** tabs. Overview shows plots, environment values and notes;
  risks and irrigation appear only when there are any. Environment & Control has graphs per sensor and the list of outputs and functions for that zone;
  About has information such as photos and area
- Click a site to open the site window. Its Overview lists the zones and facilities in the site, and today's advice and the number of unresponsive devices
- Click a facility's name tag on the map to open the facility window. If it has several buildings, choose one to view. A facility connected to an environment control function has an extra **Facility detail** tab
- Click a plot to see its stage, environment and settings
- Click **Go up** at the top of a window to go one level up, for example zone → site → site list

**Handling outputs**

- Output markers appear only when the map is zoomed in far enough. Click one and the window shows **Control**, **History** and **Notes** in turn.
  On/off outputs have a switch, windows and curtains have **Close / Stop / Open**,
  and outputs with an intensity, such as brightness, have a slider
- For an on/off output, click **Settings** to set a **Start time** and **Run time** and schedule it. If you set the run time to 00:00,
  it stays on until you turn it off. The same window shows the current schedule status, and **Turn off now** stops it
- Operations you click on the map **run immediately.** Only requests posted by AI have an approval step. Check the target output before you click
- Switches, sliders and schedule buttons are shown only to users with control permission. The Monitor, Guest and Kiosk roles can only view

**On a phone**

When you open a window, the map becomes full screen; the window slides up from the bottom in portrait orientation and docks at the side in landscape.
On a computer or tablet, the window docks at the side and you can keep using the map.

### 6. View on a phone { #step-6 }

On a narrow screen, widgets are re-stacked into two columns. Map, sequence, timer, plot, and facility widgets fill the full screen width
on a phone, and you can make other widgets do the same with **Full Width on Mobile** in their settings. Moving widgets on a phone
does not change the layout on a computer screen.

## Check { #check }

You are done when, with the tab locked, **someone seeing it for the first time can describe the site status without explanation.**

- No two widgets share the same name, and no widget still has a copy's leftover name
- No Function Status widget shows "Failed to load" or "Deactivated" (this appears when it points to a deleted or turned-off function)
- You can move between sites and zones with the map widget's **Site List**
- The dashboard is readable when opened on a phone

## Site A { #site-a }

| Tab | Widgets |
|---|---|
| Site A overview | Map (whole land parcel), gauges (3-1 and 3-2 soil moisture, greenhouse temperature and humidity), function status (greenhouse environment control) |
| Site A irrigation | Sequence Controller (open-field sequential irrigation, 3-2 extra supply), graph (soil moisture 3-1 and 3-2) |
| Site A greenhouse | Facility widget, graph (temperature, humidity, VPD), function status |

Put only **functions and sensors that are actually running** in graphs. A graph that points to a turned-off function draws only empty lines.

## Site B { #site-b }

| Tab | Widgets |
|---|---|
| Site B greenhouse | Map, gauges (VPD, temperature, humidity, wind speed), graph (greenhouse environment), function status (environment control) |

One tab is enough for Site B. On the wall-mounted screen next to the greenhouse, this tab is shown with a monitor account that uses it as the landing page.

## Troubleshooting { #trouble }

| Symptom | What to check |
|---|---|
| The Add Widget list does not appear | The tab is locked, or the account does not have edit permission |
| The map widget shows no devices | The devices have not been placed on the map, or they are hidden by the **Device Filter** ([Sensor connection step 7](g05-sensors.md#step-7)) |
| The map widget does not show site or zone shapes | Turn on sites and zones in **Shapes** in the widget settings |
| Output switches do not appear on the map | The role has no control permission |
| The map widget shows the wrong place | A view you dragged has been saved. Click a site in **Site List** to go back |
| A gauge is empty | The value is older than Max Age. Check whether the sensor has stopped sending |
| The page is slow | Reduce the number of graphs on one tab and lengthen the refresh interval |
| Only some people cannot operate a tab, or cannot see it | A group is assigned to the tab ([Main settings step 3](g02-settings.md#step-3)) |

## Learn more { #more }

- [Dashboard](../Data-Viewing.md#dashboard)
- [Key widgets](../Data-Viewing.md#key-widgets)
- [Supported widgets](../Supported-Widgets.md)
- [Map widget](../geo/map-widget.md)
