# Map Design Tool

The `/geo/design` page is an interactive editing environment for placing and managing sites, zones, facilities, and devices on a map.

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

## Editing Modes (7 types)

Select the editing target in the top mode panel. Each mode has different drawable shapes and properties.

### Site

Defines the top-level boundary of a site.

- **Draw**: Polygon
- **Properties**: Name, color, opacity
- **Special**: VWorld/CSV parcel import (see below)

### Zone

Defines growing blocks, sections, or management areas within a site.

- **Draw**: Polygon
- **Properties**: Name, parent site link, color
- **Tip**: Spatial Join automatically detects which Site contains a newly drawn Zone.

### Facility

Places physical buildings (greenhouses, warehouses, equipment rooms).

- **Draw**: Polygon (building footprint)
- **Properties**: Name, structure type, parent zone link
- **Special**: After saving, go to `/geo/facility` for 3D modeling and engineering calculations.

### Equipment

Places mechanical equipment (fans, pumps, heaters) inside a facility.

- **Draw**: Polygon or marker
- **Properties**: Name, equipment type, parent facility link

### Device

Shows the physical location of AoT Input/Output devices.

- **Draw**: Marker
- **Properties**: Select linked AoT device, marker color
- **Dashboard integration**: Clicking a marker in a widget shows real-time values and a control switch popup.

### Connection

Shows pipe, wiring, or communication routes.

- **Draw**: Polyline
- **Properties**: Name, connection type (water/electric/communication), thickness, color
- **Auto pipe generation**: Use `/api/geo/generate-pipes` for automatic routing between devices.

### Infrastructure

Shows boundary markers, roads, and other reference shapes.

- **Draw**: Polygon, polyline, marker
- **Properties**: Name, color

---

## Toolbar

### Left Toolbar

| Icon | Function |
|------|----------|
| + / - | Zoom in/out |
| Fullscreen | Toggle fullscreen |
| Search | Address/coordinate search |
| My location | Move to GPS position |
| Reset | Return to default position |

### Drawing Tools

| Tool | Shortcut | Description |
|------|----------|-------------|
| Polygon | P | Draw a polygon |
| Polyline | L | Draw a line |
| Circle | C | Draw a circle (specify radius) |
| Marker | M | Place a point marker |
| Edit | E | Edit vertices of an existing feature |
| Delete | Del | Delete selected feature |

---

## Saving Features

### Auto-save (Delta)

Whenever a feature is added, modified, or deleted, only the changes are sent to the server. Even maps with thousands of features can be saved without delay.

### Manual Save

Use the **Save** button at the top or `Ctrl+S` to force a full state save.

---

## Parcel Import

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

---

## Layer Control

Use the **Layers** panel in the upper right to toggle layer visibility.

- **Base layers**: Select from registered GIS layer providers
- **Overlays**: Toggle Site, Zone, Facility, Device individually
- **Weather layers**: RainViewer radar, OpenWeather overlay

---

## Statistics Panel

Click the **Stats** button to view map statistics.

- Total site area (m²/pyeong)
- Number and area of zones
- Number of facilities
- Number of placed devices

---

## Map Lock

Click the **Lock** button in the upper right to lock map panning and zooming. This prevents accidental map movement in the AoT_map dashboard widget.

---

## Related Pages

- [Facility Management](facility.md) — 3D setup for buildings placed in Facility mode
- [GIS Layers](layers.md) — Base layer provider configuration
- [Parcel Import Details](parcel-import.md)
