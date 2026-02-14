# GIS & Map System

The AoT system provides an integrated GIS environment to visualize and control the location of assets through Leaflet-based interactive maps. This system is configured through management pages and served as the AoT_map widget on the dashboard.

## 1. geo/setting (GIS Settings)

Manages common GIS parameters used across the system, including map center, zoom levels, search providers, and theme colors (Site, Zone, Device).

## 2. geo/layer (GIS Layer Management)

Defines and manages external data sources to be overlaid on the map, such as WMS/TMS layers from providers like VWorld or OpenStreetMap.

## 3. geo/design (Map Design & Editing)

An interactive editing tool for placing devices and setting up areas. Includes features like Spatial Join (auto-detecting zones for devices), Shape Editing (drawing sites/zones/pipes), and layout saving.

## 4. GIS Capabilities (Proxy & Search)

AoT includes built-in proxy support for services like RainViewer (Weather Radar) and ISRIC (Soil Grids) to handle CORS issues. It also supports multiple search providers for address and coordinate lookups.

## 5. AoT_map Widget

The dashboard widget integrates all settings to provide a real-time interface for monitoring and control. Features include status updates, device control via popups, and map locking for persistence.

---
## Library Information
- **Leaflet**: v1.9.4 (Core Map Engine)
- **Leaflet.draw**: v1.0.4 (Editor UI)
- **Leaflet.markercluster**: v1.4.1 (Marker Grouping)
