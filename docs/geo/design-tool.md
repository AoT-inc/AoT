# Map Design Tool

The `/geo/design` page is where you lay out a farm on a map — draw the property boundary, mark out growing zones, place buildings, and pin down exactly where each sensor and valve physically sits. Whatever you draw here is what shows up on the [AoT Map](../Data-Viewing.md#widget-map) dashboard widget, so this page is worth getting right before you start wiring up widgets.

---

## Worked Example: Laying Out a New Greenhouse Bay

A typical first pass, from the outside in:

1. **Site** — switch to **Site** mode and draw a polygon around the whole property. Name it in the property panel; it saves automatically as soon as you finish drawing.
2. **Zone** — switch to **Zone** mode and draw a polygon for the growing bay inside the site boundary. Name it (for example, "Bay 1").
3. **Facility** — switch to **Facility** mode and draw the building footprint inside the zone. Once it's named and saved, use the **Facility Design** button (or go to `/geo/facility` directly) to do the 3D setup — see [Facility Management](facility.md) for that part; this page only covers drawing the footprint.
4. **Equipment** — switch to **Equipment** mode to add a pump, a couple of valves, and the piping between them (see [Equipment mode](#equipment) below for the Pipe/Irrigation auto-generation tools).
5. **Devices** — switch to the device mode (labeled **A** in the mode panel) to place your real Input/Output/Function devices — see [Device mode](#device-a) below.
6. **Check the dashboard** — add an AoT Map widget pointed at this design; the shapes and markers you just placed appear there, and clicking a device marker shows its live value and controls.

Nothing in the tool forces you to follow this order (you can place a device before its zone exists, for instance), but drawing outside-in like this means equipment and device markers land inside their zone automatically once you draw the zone around them (see [Editing Modes](#editing-modes) for how that auto-linking actually works, and what it *doesn't* do).

---

## Screen Layout

```
┌─────────────────────────────────────────────────────┐
│  Top mode panel (Site / Zone / Facility / ...)       │
├──────┬──────────────────────────────────┬────────────┤
│      │                                  │            │
│ Left │       Map canvas                 │   Right    │
│tools │  (MapLibre GL vector rendering)  │  property  │
│      │                                  │   panel    │
├──────┴──────────────────────────────────┴────────────┤
│  Bottom status bar (coordinates, zoom, save state)   │
└─────────────────────────────────────────────────────┘
```

---

## Editing Modes { #editing-modes }

Select the editing target in the top mode panel — there are **6 modes**: Site, Zone, Facility, Planting, Equipment, and Device (labeled **A** in the panel, for "AoT device"). Each has different drawable shapes and properties.

### Site

Defines the top-level boundary of a property.

- **Draw**: Rectangle, Circle, or Polygon.
- **Properties**: Name, theme color, opacity — color changes save automatically.
- **Special**: VWorld/CSV parcel import (see [Parcel Import](#parcel-import) below).

### Zone

Defines growing blocks, sections, or management areas within a site.

- **Draw**: Rectangle, Circle, or Polygon.
- **Properties**: Name, theme color.

!!! note
    Drawing a Zone does **not** automatically link it to whichever Site it's inside — that link isn't tracked. What *is* automatic is the other direction: Equipment and Device items you place **inside** a Zone or Site get auto-linked to it (see below), which is why drawing zones before placing equipment/devices in them is the easier order.

### Facility

Places physical buildings (greenhouses, warehouses, equipment rooms).

- **Draw**: Line, Rectangle, Circle, Polygon, Marker, or Label — draw the building footprint as a polygon.
- **Properties**: Name, theme color.
- **Special**: After saving, use the **Facility Design** button (or go to `/geo/facility`) for 3D modeling, engineering calculations, and picking the parent zone — all of that happens on that page, not here. See [Facility Management](facility.md).

### Planting { #vegetation }

Records **what is planted where**. If a Zone says "this area is block 3-1", a planting plot says "in this part of block 3-1, lettuce has been growing since March 20".

- **Draw**: Rectangle, Circle, Polygon.
- **Properties**: Crop, variety, plot name, planted-on date, expected end date, color, bed width and furrow width.

!!! note "Unlike zones, plantings have a lifespan"
    A planting plot ends — 3 to 9 months for open-field beds, 30 years for an orchard. It is therefore **stored separately** from other shapes, and ending a season does not erase it: the record stays as history. That is what lets you answer "what has been in this spot for the last three years" for crop-rotation and replant-disease decisions.

**Overlapping is allowed.** Intercropping and mixed cropping are normal, so plots are not prevented from overlapping. Area percentages summing above 100% is not an error.

**You do not pick a parent zone.** Just draw it — which zone it belongs to is derived from its position, the same way equipment and devices work.

#### Bed layout { #bed-layout }

If you record bed width and furrow width, asking the AI "how many rows fit here?" is answered the way the field actually works — **plants go on the beds, not in the furrows**. Counting rows uniformly across the whole plot overestimated by 24% in a measured case (28.4 m wide, 40 cm row spacing: 71 rows uniform → 54 rows with 120 cm beds and 40 cm furrows).

- Both fields may be **left blank**, meaning "not known". Asked without them, the AI will **ask you first** rather than quietly handing you a uniform-layout number.
- A furrow width of `0` is a valid value (beds built flush against each other) — it is different from blank.
- Bed dimensions are **a property of the field**, so recording them once means not restating them in every conversation. To explore a different figure in one conversation, just say so; the stored value is untouched.

#### Migrating crops from facility bays

Crop names previously entered on facility (greenhouse) bays can be migrated into planting plots with a backfill script — ask your administrator. Geometry is **copied** as a snapshot at that moment, so changing the bay count later does not drag past seasons along with it.

### Equipment

Places pumps, valves, piping, and irrigation layouts. This mode has three sub-tabs:

- **Device** — a catalog of point markers grouped by category: Water Supply (river / water tank / pump), Filter (disc / screen / sand), Valve (union / adapter / inline / reducer), and Connection (suction / elbow / tee / reducer — pipe fittings, not a separate drawing mode). Pick an item and click on the map to place it.
- **Pipe** — draw a **Reference Line** or **Main Pipe**, set the branch spacing/angle/offset, then click **Generate** to automatically sweep parallel branch pipes across the zone, clipped to its boundary and split where they cross the main pipe.
- **Irrigation** — choose Sprinkler or Drip, set the interval, radius, flow, and pressure, then click **Generate** to lay out coverage points or emitters across the zone automatically, instead of placing them one by one.

Equipment placed inside a Zone or Site polygon is automatically linked to it — this re-check happens when the map loads and whenever you edit a shape, so a marker you *just* placed may not show its zone link in the stats panel until you reload or nudge it slightly.

### Device { #device-a }

Shows the physical location of your AoT Input, Output, and Function devices, and links them to the map. This mode also has sub-tabs (Input / Output / Function). The actual workflow:

1. Click **Selection List** to open a list of your real devices (per-channel for outputs).
2. Toggle a device on — it appears as a marker at the **center of the current map view**, not wherever you were looking. Drag it to its real physical position; the new position saves automatically.
3. Toggle a device off to remove its marker.

**Linking a shape (not just a marker) to a device**: click an already-placed device marker to "activate" it (it changes color and shows a toast confirming it's active) — the next shape you draw, of any kind, is automatically linked to that device instead of becoming a plain unlinked shape. Use this to draw, say, a fan's coverage area or a sprinkler zone tied to a specific device, separate from that device's own location marker.

*Notable:* clicking a device marker on the [AoT Map](../Data-Viewing.md#widget-map) widget's dashboard view shows its live value and, for outputs, an on/off control — this is why placing devices accurately here matters.

---

## Toolbar

### Left Toolbar

| Icon | Function |
|------|----------|
| + / − | Zoom in/out |
| Fullscreen | Toggle fullscreen |
| Search | Address/coordinate search |
| My location | Move to GPS position |
| Reset | Return to default position |

### Drawing Tools

Available tools depend on the mode: Site and Zone offer **Rectangle, Circle, and Polygon**; Facility, Equipment, and Device modes additionally offer **Line, Marker, and Label**. There are no keyboard shortcuts for any drawing tool — use the toolbar buttons.

- **Edit** — drag an existing shape's vertices to reshape it.
- **Delete** — click a shape to remove it. If shapes overlap, each click removes only the topmost one under your cursor, so click again to remove the shape underneath it.

---

## Saving Features

### Auto-save

Shapes save automatically as you draw, edit, or delete them — there's no separate "commit" step. If you want to double-check that a change really persisted, reloading the page is a reliable way to confirm it.

### Manual Save

The **Save** button at the top forces a full save of the current state. There is no keyboard shortcut for it.

---

## Parcel Import { #parcel-import }

Use Korean land data (VWorld) to quickly import site boundaries.

### Import by Address

1. Click **Parcel Import** in the top toolbar.
2. Enter an address and search (uses VWorld PNU API).
3. Select the parcel from the results.
4. Click **Save as Site** → a Site feature is automatically created.

### CSV Batch Import

Use this to import multiple parcels at once.

CSV format:
```csv
address,name
123 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do,Greenhouse Site 1
124 Gojung-ri, Songsan-myeon, Hwaseong-si, Gyeonggi-do,Greenhouse Site 2
```

1. Select **Parcel Import → CSV Import**.
2. Upload the CSV file.
3. Review the preview; rows with errors are highlighted in red.
4. Click **Import**.

See [Parcel Import Details](parcel-import.md) for more.

---

## Layer Control

Use the **Layers** panel in the upper right to toggle layer visibility.

- **Base layers**: select from registered GIS layer providers.
- **Overlays**: toggle Site, Zone, Facility, and Device shapes individually.
- **Weather layers**: RainViewer radar, OpenWeather overlay, where registered.

See [GIS Layers](layers.md) for registering new layer providers.

---

## Statistics Panel

Click the **Stats** button to view map statistics.

- Total site area (m²/pyeong)
- Number and area of zones
- Number of facilities
- Number of placed devices

---

## Map Lock

Click the **Lock** button in the upper right to lock map panning and zooming. This prevents accidental map movement in the AoT Map dashboard widget.

---

## Related Pages

- [Facility Management](facility.md) — 3D setup for buildings placed in Facility mode
- [GIS Layers](layers.md) — Base layer provider configuration
- [Parcel Import Details](parcel-import.md)
