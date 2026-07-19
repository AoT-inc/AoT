# Environmental Control Automation

AoT's `env_coordinator` is a 3-layer control system that automatically manages greenhouse environment parameters — VPD, CO₂, temperature, and humidity.

---

## VPD (Vapor Pressure Deficit)

VPD is the key metric determining plant transpiration and water uptake.

```
VPD = SVP × (1 - RH/100)
SVP = 0.6108 × exp(17.27T / (T + 237.3))  [kPa]
```

| Range | Status | Recommended crop stage |
|-------|--------|----------------------|
| < 0.4 kPa | Too low — mold risk | — |
| 0.4–0.8 kPa | Optimal | Germination / early transplant |
| 0.8–1.2 kPa | Optimal | Vegetative growth |
| 1.2–1.8 kPa | Optimal | Flowering / fruiting |
| > 1.8 kPa | Too high — water stress | — |

---

## env_coordinator Control Layers

### L1 — EnvTarget (setpoint)

Reads VPD / CO₂ targets from a Method curve or fixed values.

- **Method**: Time-based target curve by crop stage (seeding to harvest)
- **Fixed value**: Use a constant setpoint for simple operation

### L2 — SituationReport (evaluation)

Evaluates current deviation, limiting factors, and trend.

| Evaluation item | Description |
|----------------|-------------|
| Deviation | `current value - target` |
| Limiting factor | Which of temperature/humidity/CO₂ is preventing VPD from reaching target |
| Trend | Whether the value is moving toward the target |

### L3 — Coordinator (actuator command)

Applies PI control + slew rate limiting + anti-windup to command actuators.

```
e(t) = setpoint - measurement
u(t) = Kp × e(t) + Ki × ∫e dt
slew: |Δu| ≤ slew_rate_per_cycle
output → heater / vent fan / humidifier / CO₂ supply
```

---

## Function Configuration

Navigate to `Functions → env_coordinator` in the AoT UI.

### Key settings

| Field | Description |
|-------|-------------|
| Input (temperature) | Connect indoor temperature sensor |
| Input (humidity) | Connect indoor humidity sensor |
| VPD Method | VPD target curve by crop stage |
| CO₂ Method | CO₂ target curve |
| Output (heater) | Connect heating actuator |
| Output (vent fan) | Connect ventilation actuator |
| Output (humidifier) | Connect humidifier actuator |
| Output (CO₂) | Connect CO₂ supply actuator |

---

## Methods (Setpoint Curves)

A Method defines how a setpoint changes over time.

**Example crop stage schedule (tomato):**

| Day | VPD target | CO₂ target |
|-----|-----------|-----------|
| Seeding–Day 7 | 0.6 kPa | 800 ppm |
| Day 8–21 | 0.8 kPa | 900 ppm |
| Day 22–42 | 1.0 kPa | 1000 ppm |
| Day 43+ | 1.3 kPa | 1000 ppm |

Methods prefixed with `SEED:` are seed presets and are read-only. Duplicate a preset before editing.

---

## Safety Gates

Multiple safety mechanisms are applied to control actions.

| Safety gate | Description |
|-------------|-------------|
| High-temp cutoff | Forces heating OFF if indoor temp > threshold |
| CO₂ ceiling | Forces CO₂ supply OFF if CO₂ > 1500 ppm |
| Sensor failure | Enters safe mode if sensor value stays `stale` |
| Manual Lock | AI or user can pause automatic control |

---

## AI Integration

The AI agent uses `analyze_control_performance` to diagnose control quality.

```
vpd_rmse         → VPD tracking error (lower is better)
oscillation_index → Control oscillation index (lower is more stable)
assessment       → "good" / "moderate" / "poor"
```

Based on diagnostics, `suggest_setpoint_adjustment` proposes a target adjustment. After user approval, `set_vpd_target` applies it.

---

## Related Pages

- [AI Overview](overview.md)
- [Functions Guide](../Functions.md)
- [Methods Guide](../Methods.md)
