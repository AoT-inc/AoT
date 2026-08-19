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
┌──────┬──────────────────────────────────┬────────────┐
│      │                                  │            │
│ Left │       Map canvas                 │  Settings  │
│tools │  (MapLibre GL vector rendering)  │  drawer    │
│      │                                  │            │
│      │  ┌────────────────────────────┐  │ (per mode) │
│      │  │ Mode tabs (Site/Zone/…)    │  │            │
└──────┴──┴────────────────────────────┴──┴────────────┘
```

**Mode tabs sit in a bar below the map; that mode's settings live in a drawer to the right.** The drawer pushes the map aside rather than covering it, so you can see the effect of a setting while you change it, and you can still pan the map or click shapes with the drawer open. On a phone the drawer covers the screen, and a handle at the top drops it down so you can see the map.

---

## Editing Modes { #editing-modes }

Select the editing target from the mode tabs below the map — there are **6 modes**: Site, Zone, Facility, Plot, Equipment, and Device (labeled **A**, for "AoT device"). Each has different drawable shapes and properties. Pressing a tab also opens that mode's settings drawer.

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

### Plot { #plot }

Records **what is where**. If a Zone says "this area is block 3-1", a plot says "in this part of block 3-1, lettuce has been there since March 20".

**Not vegetation-only.** A plot has a **kind** — Vegetation, Livestock, Facility, Other. Choosing the kind narrows the program choices to that kind.

**Attach a program** and the current stage, target environment and expected end date follow automatically. See [Management Programs](programs.md).

- **Draw**: Rectangle, Circle, Polygon.
- **Properties**: Crop, variety, plot name, planted-on date, expected end date, color.

!!! note "Unlike zones, plots have a lifespan"
    A plot ends — 3 to 9 months for open-field beds, 30 years for an orchard. It is therefore **stored separately** from other shapes, and ending a season does not erase it: the record stays as history. That is what lets you answer "what has been in this spot for the last three years" for crop-rotation and replant-disease decisions.

**Overlapping is allowed.** Intercropping and mixed cropping are normal, so plots are not prevented from overlapping. Area percentages summing above 100% is not an error.

**You do not pick a parent zone.** Just draw it — which zone it belongs to is derived from its position, the same way equipment and devices work.

#### Splitting a zone into plots { #split }

When one zone is planted in several pieces, you do not have to draw each piece — you can have it **split**. Switch to Plot mode and the split form is already there, above the plot's subject/variety fields.

- **Area to split** — pick from the zones and sites already drawn on the map. A shape you have not saved yet is not in the list (save it first).
- **Split by** — either **Equal parts** (how many pieces) or **Strip width** (how many cm each piece is). Setting **Equal parts** to **1** does not divide at all — the whole area becomes a single plot (still inset if you set an edge margin), which is what you want when a field is planted as one. Choosing **Strip width** also reveals **Exact piece count (optional)** — leave it empty and the count is worked out automatically from the width (as many as fit); fill it in and exactly that many pieces are cut at exactly that width, with the leftover space becoming margin split evenly on both sides. This is not an equal split — use it when both the count and the spacing are already decided (e.g. "5 rows, exactly 40 cm apart").
- **Direction** — shown for **Equal parts**, and for **Strip width** once you fill in an exact piece count (both are then "N pieces laid out which way"). **Long side** (default) follows the field's long direction; **Short side** divides across it instead, giving squarer pieces. If the goal is splitting the zone between different crops rather than laying beds, the short side is often easier to manage. **Custom angle** shows an angle slider so you can rotate to any direction — while you drag it, a baseline through the zone's center turns to match on the map, and after a brief pause the piece preview redraws at that angle.
- **Edge margin** — leaves room inside the shape for machinery to turn. Use 0 if you do not need it.
- **Adjust each piece width** — the modes above all cut equal-width pieces. Turn this on to give each piece its own width instead: it starts from the equal split you already have, with one number field per piece (in meters) so you can edit them, plus buttons to add or remove a piece (minimum 2). Direction still applies — the width list only sets how thick each piece is, not which way the cutting axis runs. If the last piece you enter is too wide for what is left, it is not rejected — it is shortened to whatever fits, and the summary line below says so. On the map, each dashed preview piece is numbered to match its input field.
- **Crop, variety, plot name, planted-on date, color** — every piece gets the same values. The plot name gets the piece number appended (`Trial 1`, `Trial 2`, …).

**The map follows as you change values.** The proposal is drawn as a **dashed** outline, with the piece count, piece width, length range and direction shown below the form. If the pieces come out long and narrow (roughly above 4:1), the aspect ratio is shown as a warning — a hint to try the short side instead. There is no separate step to confirm the preview — because the drawer does not cover the map, **what you see is the proposal**. If it looks right press **Create plots**; otherwise just close the drawer (nothing is saved).

!!! note "Pieces follow the field's long direction by default"
    Cutting on true north leaves beds running diagonally across an irregular field, producing nothing but offcuts. So pieces follow the shape's **longest side** by default, and irregular edges are clipped. That is why pieces differ in length, and pieces too short to be a bed (under 2 m) are dropped — the number dropped is shown too. Strip-width (bed-by-bed) splits always follow the long side — furrow direction has to match how the field is actually worked, so direction cannot be changed there.

#### Bed layout goes in a note { #bed-layout }

Ask the AI "how many rows fit here?" and it counts the way the field actually works — **plants go on the beds, not in the furrows**. Counting rows uniformly across the whole plot overestimated by 24% in a measured case (28.4 m wide: 71 rows uniform → 54 rows bedded).

That layout is recorded as **a sentence in the plot's notes, not in a form field**. When the AI does not know the layout it will **ask you first** rather than quietly handing you a uniform-layout number, and tell you to record what you agree on as a note. The next conversation reads that note.

!!! note "Why not a form field"
    Ask for "bed width" and some people answer with the **planting surface excluding the furrow** while others give **the bed and its furrow as one set**. The same field gets recorded as `120+40` or as `160+0`, and **nothing errors — only the bed count changes.** A number field cannot carry which reading was meant. Bed layout is also only the start; mulching, trellising and irrigation practice follow, and those cannot all become fields. That is what notes are for.

Two values are used when you ask for a count:

- **Bed pitch** — centre of one bed to the centre of the next, **furrow included**, as a single number (a 120 cm bed with a 40 cm furrow is `160`). Growers do not count a bed and its furrow separately, so asking for one number avoids the split reading.
- **Rows per bed** — crop-dependent: peppers take one row, lettuce or cabbage two or three. The pitch alone cannot say how many rows fit.

The two go **together**. For flat (unbedded) planting, give row spacing instead.

#### Migrating crops from facility bays

Crop names previously entered on facility (greenhouse) bays can be migrated into plots with a backfill script — ask your administrator. Geometry is **copied** as a snapshot at that moment, so changing the bay count later does not drag past seasons along with it.

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
