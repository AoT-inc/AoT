# Getting Started with GIS

A quick setup guide for first-time AoT GIS users. Follow these steps to have a map displaying your device locations within 10 minutes.

---

## Prerequisites

- AoT installed and logged in with an admin account
- At least one Input device registered (a map can be created without devices)

---

## Step 1: Global GIS Settings

Navigate to **Gear → Configure → GIS Settings** or go to `/geo/setting`.

### Set Default Location

1. Move the map to your desired location, or type an address in the search bar.
2. Set the **zoom level** to the default you want to save.
3. Click **Save**.

### Theme Colors (Optional)

| Element | Default | Description |
|---------|---------|-------------|
| Site | Blue tones | Site boundary color |
| Zone | Green tones | Zone color |
| Facility | Orange tones | Facility building color |
| Equipment | Gray | Equipment color |
| Device | Red tones | AoT device marker color |

---

## Step 2: Register a Map Layer (Optional)

If you need aerial imagery or a domestic map beyond the default OSM, register a GIS layer.

Navigate to **GIS → Layer** or go to `/geo/layer`.

**Example: Adding VWorld (Korean cadastral map/aerial):**

1. Select `VWorld` from the **Input Type** dropdown in the top right.
2. Click **Add**.
3. Click the **Settings (gear) icon** on the newly created item.
4. Enter your VWorld API key and save.
5. Click **Activate** to enable it.

See [GIS Layer Management](layers.md) for details.

---

## Step 3: Create Your First Map Design

Navigate to **GIS → Design** or go to `/geo/design`.

### Create a New Map

1. Click the **+ New Map** button at the top of the left panel.
2. Enter a map name and confirm.

### Draw a Site Boundary

1. Select **Site** mode in the top mode panel.
2. Select **Draw polygon** from the toolbar.
3. Click on the map to place vertices; connect the last point to the first to complete the polygon.
4. Enter the site name in the right property panel and click **Save**.

**Faster option — use VWorld parcel import:**

1. Click the **Parcel Import** button in the top toolbar.
2. Type an address to search.
3. Select the parcel from the results.
4. Click **Save as Site**.

### Set Up Zones

1. Switch to **Zone** mode.
2. Draw a zone polygon inside the site.
3. Enter the zone name (e.g., "Block 1", "Growing Zone A") and save.

---

## Step 4: Place Devices

1. Switch to **Device** mode.
2. Select **Place marker** from the toolbar.
3. Click on the map where the device is physically located.
4. In the right panel, select the **AoT device** from the dropdown.
5. Click **Save**.

---

## Step 5: Add a Dashboard Widget

1. Go to the dashboard.
2. Select **Add Widget → AoT_map**.
3. In the widget settings, select the map created in Step 3.
4. Click **Save**.

Device markers will appear on the map. Clicking a marker shows real-time values and a control switch.

---

## Next Steps

- [Design Tool Guide](design-tool.md) — Full guide for all 7 modes
- [Facility Management](facility.md) — 3D building modeling and engineering calculations
- [Map Widget Settings](map-widget.md) — Detailed widget options
