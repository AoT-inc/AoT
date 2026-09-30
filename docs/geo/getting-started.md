# Getting Started with GIS

A quick setup guide for first-time AoT GIS users. Follow these steps to have a map displaying your device locations within 10 minutes.

---

## Prerequisites

- AoT installed and logged in with an admin account
- At least one Input device registered (a map can be created without devices)

---

## Step 1: Global GIS Settings

Go to **Settings → Map** (`/geo/design`) and click the **Settings** button below the page title to open the **GIS Settings** window. The old address `/geo/setting` only redirects to this page.

### Set Default Location

1. Before opening the window, move the map to the location and zoom you want as the default (you can also type an address in the search bar).
2. In the window, click **Get Location** under **Default Start Location** to fill in **Latitude**, **Longitude** and **Zoom Level** from the current view. You can also type the values.
3. Click **Save**.

### Theme Colors (Optional)

Change the per-layer colors under **Design Theme Settings**.

| Element | Default | Description |
|---------|---------|-------------|
| Site Color | Red tones | Site boundary color |
| Zone Color | Green tones | Zone color |
| Facility Color | Gray | Facility building color |
| Equipment Color | Blue tones | Equipment color |
| Device Color | Purple tones | AoT device marker color |

---

## Step 2: Register a Map Layer (Optional)

If you need aerial imagery or a domestic map beyond the default OSM, register a GIS layer.

Navigate to **Settings → GIS Input** or go to `/geo/layer`.

**Example: Adding VWorld (Korean cadastral map/aerial):**

1. Select `VWorld` from the **Select GIS Service** dropdown at the top of the page.
2. Click **Add**.
3. Click the **Settings (gear) icon** on the newly created item.
4. Enter your VWorld API key and save.
5. Click **Activate** to enable it.

See [GIS Layer Management](layers.md) for details.

---

## Step 3: Create Your First Map Design

Navigate to **Settings → Map** or go to `/geo/design`.

### Create a New Map { #create-a-new-map }

1. In **Map Design**, choose **Create New Map** from the map dropdown; the new map is created right away.
2. Click **Edit** to rename the map.

### Draw a Site Boundary

1. Select **Site** mode in the mode tabs below the map.
2. Pick the polygon tool from the drawing tools.
3. Click on the map to place vertices; connect the last point to the first to complete the polygon.
4. Enter the site name in the property panel. Shapes are saved automatically as you draw.

**Faster option — use VWorld parcel import:**

1. In the Site settings drawer, click **Search** next to **Add from Address**.
2. Type an address and click **Search**.
3. Check the parcels found in the preview.
4. Click **Save as Site**.

### Set Up Zones

1. Switch to **Zone** mode.
2. Draw a zone polygon inside the site.
3. Enter the zone name (e.g., "Block 1", "Growing Zone A").

---

## Step 4: Place Devices

1. Switch to the device mode (**A**) in the mode tabs.
2. Under **Device kind**, pick **Input**, **Output**, **Function** or **Device**, then click **Open** next to **Selection list**.
3. Turn on the switch of the device you want to place; its marker appears at the center of the current map view.
4. Drag the marker to where the device is physically located. The new position is saved automatically.

See [Design Tool — Device mode](design-tool.md#device-a) for details.

---

## Step 5: Add a Dashboard Widget

1. Go to the dashboard.
2. Select **Add Widget → AoT Map**.
3. In the widget settings, pick the map created in Step 3 under **Select Map**.
4. Click **Save**.

Device markers will appear on the map. Clicking a marker shows real-time values and a control switch.

---

## Next Steps

- [Design Tool Guide](design-tool.md) — Full guide for all 6 modes (Site, Zone, Facility, Plot, Equipment, Device)
- [Plots](plots.md) and [Management Programs](programs.md) — Track what is growing where and toward what target
- [Facility Management](facility.md) — 3D building modeling and engineering calculations
- [Map Widget Settings](map-widget.md) — Detailed widget options
