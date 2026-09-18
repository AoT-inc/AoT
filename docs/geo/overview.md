# GIS & Map System Overview

The AoT GIS system is an integrated geospatial platform built on the MapLibre GL vector map engine, combining device monitoring, facility design, and external GIS layer integration in one place.

---

## System Architecture

```
GIS & Map System
├── Map Engine
│   ├── MapLibre GL (primary — vector/3D)
│   └── Leaflet compatibility shim (legacy support)
│
├── Management Pages
│   ├── /geo/design   — Map design tool
│   ├── /geo/facility — Facility management
│   └── /geo/layer    — GIS layer management
│
├── Dashboard Widgets
│   ├── AoT_map      — Real-time device monitoring map
│   └── AoT_facility — 3D facility environment monitor
│
└── API
    └── /api/geo/*   — 30+ REST endpoints
```

---

## Core Features

### Map Design Tool

- **6 editing modes**: Site → Zone → Facility → Plot → Equipment → Device (labeled "A" in the mode bar, for "AoT device")
- **Vector drawing**: Create and edit polygons, polylines, circles, and markers
- **Parcel import**: Instantly generate site boundaries via VWorld address search or CSV batch import
- **Delta save**: Only changed features are transmitted, enabling fast saves on large maps

### Plots & Programs

- **Plots**: what is growing where, since when, and toward what — drawn in Plot mode, but the record (crop, variety, dates, stage schedule) lives separately from the shape and survives after the shape is redrawn or the season ends.
- **Programs**: reusable templates ("tomatoes, in 5 stages, toward these targets"). Attach one to a plot and the current stage, target environment, and expected end date follow automatically.
- **Kinds**: plots and programs are both typed — Vegetation, Livestock, Facility, Other — and only a matching kind can attach.
- **Journals**: a point-in-time, never-recalculated snapshot of what a plot/zone/site grew, measured, and was controlled by over a chosen period, for handoff or certification.

### Facility Management

- **3D parametric rendering**: Automatically generated from building structure parameters using Three.js
- **Building envelope configuration**: Materials (vinyl/glass/PC), insulation, and openings (windows/doors/vents)
- **Engineering calculations**: Heating/cooling load, ventilation capacity, natural ventilation wind pressure simulation (±5–10% reference values)
- **Sensor & actuator binding**: Link AoT devices by role (temperature/humidity/CO₂, etc.)
- **Commissioning**: Device communication check and diagnostic workflow
- **AI advice**: Automation recommendations based on facility learning

### GIS Layers

Integrates with 23 external GIS providers.

| Category | Providers |
|----------|-----------|
| Domestic (Korea) | VWorld, Kakao Maps, Naver Maps |
| International | OpenStreetMap, Google Maps, ESRI, Bing, Mapbox, MapTiler, Carto, Stadia |
| Satellite | NASA GIBS, ESA |
| Weather | RainViewer (radar), OpenWeather, Open-Meteo |
| Terrain | OpenTopoMap, Thunderforest |
| Specialized | ISRIC (soil), GSI (Japan), SGIS (Singapore) |

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Map rendering | MapLibre GL JS |
| 3D visualization | Three.js + GLTF |
| Drawing tools | terra-draw (Geoman API compatible) |
| Spatial operations | Turf.js |
| Marker clustering | Leaflet.MarkerCluster |
| WMS support | MapLibre + CORS proxy |
| Backend | Python/Flask, SQLAlchemy |
| Database | SQLite (config), InfluxDB (time-series) |

---

## Data Model

| Table | Role |
|-------|------|
| `geo_map` | Saved map views (center, zoom, provider, style) |
| `geo_setting` | Global GIS configuration (singleton) |
| `geo_shape` | GeoJSON overlay features (site/zone/facility/device) |
| `geo_layer` | External GIS layer source registry |
| `geo_facility` | Facility building specs (envelope, sensors, actuators, bays) |
| `geo_model_asset` | 3D asset library (primitives/GLTF) |

---

## Feature Hierarchy

```
Site          ← Top-level boundary (polygon)
  └── Zone    ← Growing blocks / sections
        ├── Facility    ← Building unit
        ├── Plot        ← What's planted, since when, toward what (see Plots & Programs)
        ├── Equipment   ← Pumps, valves, piping, irrigation
        └── Device      ← AoT Input/Output/Function markers
```

Which zone a plot, piece of equipment, or device belongs to is derived from where it is drawn on the map — it is never picked from a dropdown.

---

## Related Pages

- [Getting Started](getting-started.md)
- [Design Tool](design-tool.md)
- [Parcel Import](parcel-import.md)
- [Facility Management](facility.md)
- [Plots](plots.md)
- [Management Programs](programs.md)
- [Journals](journal.md)
- [GIS Layers](layers.md)
- [Map Widget](map-widget.md)
- [Facility Widget](facility-widget.md)
- [Plot Widget](plot-widget.md)
- [Settings](settings.md)
- [API Reference](api-reference.md)
