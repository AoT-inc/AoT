# Facility Management

The `/geo/facility` page is where you perform 3D modeling, engineering calculations, sensor/actuator binding, and commissioning for buildings such as greenhouses, growing houses, and equipment rooms.

---

## Screen Layout

```
┌─────────────────────────────────────┐
│  Facility selector dropdown          │
├───────────────┬─────────────────────┤
│  A. 3D View   │  B. Environment     │
│  (Three.js)   │  Indoor: T/RH/CO₂  │
│               │  Outdoor: T/Wind/PAR│
├───────────────┴─────────────────────┤
│  C. AI Advice panel                  │
├─────────────────────────────────────┤
│  D. Settings (envelope/sensors/act.)│
└─────────────────────────────────────┘
```

---

## Facility Registration Flow

```
Draw Facility polygon in /geo/design (Facility mode)
         ↓
    Save facility name
         ↓
Select facility in /geo/facility
         ↓
  Configure envelope → Verify 3D preview
         ↓
  Bind sensors & actuators
         ↓
  Run commissioning
```

---

## Envelope Configuration

Set the physical structure of the building. These values are used as inputs for heating/cooling load calculations.

### Structure Type

| Type | Description |
|------|-------------|
| `single` | Single-span greenhouse (standalone structure) |
| `connected` | Multi-span greenhouse (multiple spans sharing side walls) |

### Covering Materials { #covering-materials }

| Code | Name | U-value (W/m²K) | Light transmittance |
|------|------|----------------|---------------------|
| `vinyl_single` | Single-layer vinyl | 6.0 | 85% |
| `vinyl_double` | Double-layer vinyl | 4.0 | 78% |
| `po_film` | PO film | 6.5 | 85% |
| `polycarbonate` | Polycarbonate | 3.0 | 78% |
| `glass` | Glass | 5.8 | 85% |
| `air_cushion` | Air cushion film | 2.8 | 75% |

### Bay Configuration

Enter the dimensions of each bay (structural unit) of the greenhouse.

- **Bay count**: Number of spans (for multi-span)
- **Bay width (m)**: Width of each span
- **Length (m)**: Length of the structure
- **Eave height (m)**: Height from ground to eave
- **Ridge height (m)**: Height from eave to ridge

---

## 3D Preview

Once envelope settings are saved, a Three.js-rendered building model is displayed in the **A. 3D View** panel.

- **Left mouse drag**: Rotate
- **Right mouse drag**: Pan
- **Scroll**: Zoom

### 3D Asset Mode

Instead of automatic parametric generation, you can apply a custom GLTF model.

1. Upload a GLTF file at `/geo/model-assets`.
2. Switch the facility's **Render Mode → Asset**.
3. Select the model from the asset library and adjust position, rotation, and scale.

---

## Engineering Calculations

Calculates first-order reference values for heating/cooling and ventilation capacity based on the building envelope (±5–10% margin; for equipment estimation purposes only).

Click **Compute** to calculate:

| Item | Unit | Description |
|------|------|-------------|
| Heating load | kW | Envelope transmission + infiltration loss |
| Cooling load | kW | Solar gain + crop transpiration load |
| Forced ventilation | m³/h | Fan capacity based on required ACH |
| Natural ventilation | m³/h | Available natural ventilation through side/roof vents |

### Natural Ventilation Wind Pressure Simulation

The `/api/geo/facility/<uuid>/wind` endpoint accepts building geometry plus wind direction/speed and simulates ventilation performance.

---

## Sensor & Actuator Binding

Connect AoT devices to their roles within the facility.

### Sensor Roles

| Role | Recommended measurement |
|------|------------------------|
| Indoor temperature | Temperature (°C) |
| Indoor humidity | Humidity (%RH) |
| Indoor CO₂ | CO2 (ppm) |
| Soil temperature | Soil Temperature |
| Soil moisture | Soil Moisture |

### Actuator Roles

| Role | Output type |
|------|------------|
| Heater | On/Off Relay |
| Ventilation fan | On/Off or PWM |
| Shade screen | On/Off Relay |
| Irrigation pump | On/Off Relay |
| CO₂ supply | On/Off Relay |

**How to register:**

1. In the **Sensors** tab, click **+ Add Sensor**.
2. Select a role → Select an AoT Input device → Select the measurement channel.
3. Repeat for the **Actuators** tab.
4. Click **Save**.

---

## Integration View

The `/api/geo/facility/<uuid>/integration` endpoint returns the current state of all sensors and actuators bound to a facility in a unified response. The AoT_facility widget's environment panel uses this API.

---

## Commissioning

A diagnostic workflow to verify that facility devices are communicating properly.

1. In the **Commissioning** tab, click **Start Check**.
2. The system sends communication requests to all registered sensors and actuators.
3. The response status for each device is displayed:
   - `OK`: Normal communication
   - `TIMEOUT`: No response (check wiring and power)
   - `ERROR`: Error response (check device configuration)
4. Use the **Verdict** button to approve or hold individual results.

---

## AI Advice Panel

The AI analyzes bound sensor data to suggest anomaly alerts or operational improvements.

- **Urgency colors**: **Red** (immediate action) / **Orange** (caution) / **Green** (normal)
- Advice accuracy improves as more learning data accumulates.

---

## Related API

| Endpoint | Description |
|----------|-------------|
| `GET /api/geo/facility/list` | List facilities |
| `GET /api/geo/facility/<uuid>` | Get facility details |
| `POST /api/geo/facility` | Create/update facility |
| `POST /api/geo/facility/compute` | Capacity calculation preview |
| `GET /api/geo/facility/<uuid>/integration` | Get integrated state |
| `GET /api/geo/facility/<uuid>/wind` | Ventilation simulation |
| `GET /api/geo/facility/<uuid>/runtime` | Real-time runtime state |
| `POST /api/geo/facility/<uuid>/apply` | Apply configuration |
| `POST /api/geo/facility/<uuid>/commissioning/start` | Start commissioning |

---

## Related Pages

- [Design Tool](design-tool.md) — Drawing facility polygons
- [Facility Widget](facility-widget.md) — Dashboard 3D widget
- [API Reference](api-reference.md)
