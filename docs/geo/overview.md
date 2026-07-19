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

- **7 editing modes**: Site → Zone → Facility → Equipment → Device → Connection → Infrastructure
- **Vector drawing**: Create and edit polygons, polylines, circles, and markers
- **Parcel import**: Instantly generate site boundaries via VWorld address search or CSV batch import
- **Delta save**: Only changed features are transmitted, enabling fast saves on large maps

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
        └── Facility   ← Building unit
              └── Equipment / Device
```

---

## Related Pages

- [Getting Started](getting-started.md)
- [Design Tool](design-tool.md)
- [Facility Management](facility.md)
- [GIS Layers](layers.md)
- [Map Widget](map-widget.md)
- [Facility Widget](facility-widget.md)
- [Settings](settings.md)
- [API Reference](api-reference.md)
