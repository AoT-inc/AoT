# GIS API Reference

All GIS API endpoints require login. Endpoints that modify data require `edit_settings` or `edit_controllers` permissions.

---

## Map Designs

### Initialize New Design

```http
GET /api/geo/init_design
```

Creates a new empty map design and returns its UUID.

### Get Design

```http
GET /api/geo/designs/<map_uuid>
```

Returns the full state of a saved map (features, zoom, center coordinates, layer settings).

### List Designs

```http
GET /api/geo/designs
```

Returns a list of all registered maps.

### Save Design

```http
POST /api/geo/designs
Content-Type: application/json

{
  "name": "Main Farm Map",
  "lat": 37.5665,
  "lng": 126.9780,
  "zoom": 16
}
```

### Delete Design

```http
DELETE /api/geo/designs/<map_uuid>
```

---

## Overlays (Features)

### List Overlays

```http
GET /api/geo/overlays/list
```

Returns a list of all GeoShape features.

### Load Overlays

```http
GET /api/geo/overlays?geo_id=<map_uuid>
```

Returns all features for a specific map as a GeoJSON FeatureCollection.

### Save Overlays (Full)

```http
POST /api/geo/overlays
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Polygon", "coordinates": [...] },
      "properties": {
        "type": "site",
        "name": "Site 1",
        "unique_id": "<uuid>"
      }
    }
  ]
}
```

### Delta Save (Efficient)

Sends only added, modified, or deleted features instead of the full feature set. Improves performance on large maps.

```http
POST /api/geo/overlays/delta
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "added": [...],
  "modified": [...],
  "deleted": ["<uuid1>", "<uuid2>"]
}
```

---

## Facilities

### List Facilities

```http
GET /api/geo/facility/list
```

### Get Facility

```http
GET /api/geo/facility/<facility_uuid>
```

Returns full facility data including envelope parameters, sensor/actuator bindings, and 3D settings.

### Create / Update Facility

```http
POST /api/geo/facility
Content-Type: application/json

{
  "unique_id": "<uuid>",
  "name": "Greenhouse Block 1",
  "shape_uuid": "<geo_shape_uuid>",
  "preset": "greenhouse",
  "structure": "single",
  "bay_count": 1,
  "envelope": {
    "material": "vinyl_double",
    "bay_width_m": 8.0,
    "length_m": 50.0,
    "eave_height_m": 3.5,
    "ridge_height_m": 2.0
  },
  "sensors": [
    {
      "role": "indoor_temp",
      "device_id": "<input_uuid>",
      "measurement_id": "<measurement_uuid>",
      "name": "Indoor Temperature Sensor"
    }
  ],
  "actuators": [
    {
      "role": "heater",
      "device_id": "<output_uuid>",
      "name": "Heater"
    }
  ]
}
```

### Delete Facility

```http
DELETE /api/geo/facility/<facility_uuid>
```

### Capacity Calculation Preview

Returns engineering calculation results for envelope parameters without saving.

```http
POST /api/geo/facility/compute
Content-Type: application/json

{
  "envelope": {
    "material": "vinyl_double",
    "bay_width_m": 8.0,
    "length_m": 50.0,
    "eave_height_m": 3.5,
    "ridge_height_m": 2.0
  },
  "bay_count": 3
}
```

Response:
```json
{
  "area_m2": 1200.0,
  "volume_m3": 5400.0,
  "heating_load_kw": 42.3,
  "cooling_load_kw": 31.7,
  "forced_ventilation_m3h": 32400,
  "natural_ventilation_m3h": 15000
}
```

### Integration State

Returns the current values of all sensors and actuators bound to a facility.

```http
GET /api/geo/facility/<facility_uuid>/integration
```

### Runtime State

Returns real-time sensor values, actuator states, and alert summary.

```http
GET /api/geo/facility/<facility_uuid>/runtime
```

### Ventilation Simulation

Returns natural ventilation wind pressure simulation results.

```http
GET /api/geo/facility/<facility_uuid>/wind?wind_speed=3.5&wind_dir=270
```

### Apply Configuration

Sends commands to actuators bound to the facility.

```http
POST /api/geo/facility/<facility_uuid>/apply
Content-Type: application/json

{
  "actions": [
    { "role": "heater", "state": true }
  ]
}
```

---

## Commissioning

### Start Commissioning

```http
POST /api/geo/facility/<facility_uuid>/commissioning/start
```

Response:
```json
{
  "check_id": "<uuid>",
  "status": "running"
}
```

### Get Commissioning Result

```http
GET /api/geo/facility/<facility_uuid>/commissioning/<check_id>
```

### Submit Verdict

```http
POST /api/geo/facility/<facility_uuid>/commissioning/<check_id>/verdict
Content-Type: application/json

{
  "device_id": "<uuid>",
  "verdict": "approved"
}
```

---

## Parcel Import

### Look Up Parcel by Address

```http
POST /api/geo/parcel/from_address
Content-Type: application/json

{
  "address": "123 Gojung-ri, Songsan-myeon, Hwaseong-si"
}
```

### CSV Batch Import

```http
POST /api/geo/parcel/from_csv
Content-Type: multipart/form-data

file=<CSV file>
```

### Save Parcel as Site

```http
POST /api/geo/parcel/save_as_site
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "geometry": { "type": "Polygon", "coordinates": [...] },
  "name": "Greenhouse Site 1"
}
```

---

## Proxy Services

The AoT server relays external services that are difficult for clients to access directly due to CORS policies.

| Endpoint | Target service |
|----------|---------------|
| `GET /api/geo/proxy/rainviewer/*` | RainViewer rainfall radar |
| `GET /api/geo/proxy/isric` | ISRIC SoilGrids soil data |
| `GET /api/geo/proxy/openweather` | OpenWeather weather overlay |
| `GET /api/geo/proxy/openmeteo` | Open-Meteo weather forecast |
| `GET /api/geo/proxy/wms/<unique_id>` | WMS layer tiles |
| `GET /api/geo/tile_proxy` | Generic tile proxy (NASA, Naver, Kakao) |

---

## Settings

### Get Global Settings

```http
GET /api/geo/settings
```

### Save Global Settings

```http
POST /api/geo/settings
Content-Type: application/json

{ ... }
```

See [GIS Settings](settings.md#api) for the full request schema.

---

## Device Lists

Returns lists of AoT devices available for map placement.

```http
GET /api/geo/devices
GET /api/geo/inputs
GET /api/geo/outputs
```

---

## Auto Pipe Generation

Automatically generates optimal pipe routes between devices.

```http
POST /api/geo/generate-pipes
Content-Type: application/json

{
  "geo_id": "<map_uuid>",
  "device_ids": ["<uuid1>", "<uuid2>", "<uuid3>"]
}
```

---

## Response Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad request (input error) |
| 401 | Authentication required |
| 403 | Forbidden |
| 404 | Resource not found |
| 500 | Server error |
