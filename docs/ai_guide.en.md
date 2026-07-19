# AoT AI Agent Guide (English)

This guide explains how AI agents can observe, diagnose, and control the AoT greenhouse environment system via the MCP server.

---

## 1. Overview

The AoT MCP server is built on **FastMCP** and exposes the following tools to MCP clients such as Claude Desktop.

| Category | Tool | Description |
|----------|------|-------------|
| Observe | `list_facilities` | List registered facilities |
| Observe | `get_facility_state` | Current T / RH / VPD / CO₂ / Light |
| Observe | `get_sensor_history` | Sensor time-series (1h / 24h / 7d) |
| Observe | `list_functions` | Active Function list |
| Observe | `get_function_state` | env_coordinator cycle state |
| Observe | `list_methods` | Method (setpoint curve) list |
| Observe | `list_outputs` | Actuator current command values |
| Observe | `get_recent_events` | Recent MCP audit log |
| Diagnose | `analyze_control_performance` | VPD tracking RMSE · oscillation |
| Diagnose | `detect_sensor_anomaly` | Sensor outliers · drift |
| Diagnose | `suggest_setpoint_adjustment` | Suggested VPD target (suggestion only) |
| Diagnose | `compare_periods` | Statistical comparison of two periods |
| Control | `set_vpd_target` | Change VPD target (**requires approval**) |
| Control | `update_method_point` | Edit curve control point (**requires approval**) |
| Control | `request_manual_lock` | Pause AI auto-control (**requires approval**) |
| Control | `acknowledge_alert` | Acknowledge alarm (**requires approval**) |
| Flow | `confirm_action` | Approve a pending write |
| Flow | `reject_action` | Reject a pending write |
| Flow | `get_pending_actions` | List pending approvals |
| Info | `get_system_manifest` | System domain + policy context |

---

## 2. Safety Policy

### 2.1 Write Default OFF

All control tools are **disabled by default**. To enable:

```bash
# Via environment variable
AOT_MCP_WRITE_ENABLED=1 python -m aot.mcp_server.server

# Via CLI flag
python -m aot.mcp_server.server --write
```

### 2.2 Three-Layer Safety

1. **Layer 1 — Permission**: Read tools are unrestricted. Write tools blocked by global flag.
2. **Layer 2 — Validation**: Value range, delta per call, and per-hour rate limits.
3. **Layer 3 — User Approval**: Every write requires a 60-second TTL confirmation token approved by the user.

### 2.3 Write Tool Limits

| Tool | Value Range | Max Delta/Call | Max Calls/Hour |
|------|------------|----------------|----------------|
| `set_vpd_target` | 0.3 ~ 2.5 kPa | 0.5 kPa | 5 |
| `update_method_point` | 0.0 ~ 3.0 kPa | 0.3 kPa | 10 |
| `request_manual_lock` | 1 ~ 120 min | — | 3 |
| `acknowledge_alert` | — | — | 20 |

### 2.4 Seed Preset Protection

Methods whose name starts with `SEED:` are **read-only**. Duplicate before editing.

---

## 3. Recommended Workflow

### Anomaly Response

```
1. list_facilities
   → Get facility unique_id

2. get_facility_state(facility_id)
   → Check current VPD / T / RH / CO₂
   → If sensors_health = 'stale', investigate sensor connectivity first

3. analyze_control_performance(function_id, window='1h')
   → Check vpd_rmse, oscillation_index, assessment

4. detect_sensor_anomaly(device_id, measurement_id)
   → verdict: 'anomaly_detected' / 'drift_detected' / 'normal'

5. suggest_setpoint_adjustment(facility_id)
   → Review suggested_target and reason

6. (with user approval)
   set_vpd_target(function_id, value=suggested_target, reason=reason)
   → Returns: {'pending': True, 'token_id': '...', 'expires_in': 60}

7. confirm_action(token_id='...', user_id='operator')
   → Applies the change
```

### Control Flow Example

```python
# 1. Request VPD target change
result = set_vpd_target(
    function_id='abc-123',
    value=1.2,
    reason='VPD too low, need to promote transpiration'
)
# → {'pending': True, 'token_id': 'xxx-yyy', 'expires_in': 60, ...}

# 2. User approves via UI or confirm_action
result = confirm_action(token_id='xxx-yyy', user_id='operator')
# → {'ok': True, 'tool_name': 'set_vpd_target', 'result': {...}}
```

---

## 4. Domain Knowledge

### VPD (Vapor Pressure Deficit)

VPD = SVP × (1 − RH/100)  
SVP = 0.6108 × exp(17.27T / (T + 237.3)) [kPa]

| Range | Status | Typical Growth Stage |
|-------|--------|---------------------|
| < 0.4 kPa | Too low — inhibits transpiration, fungal risk | — |
| 0.4 ~ 0.8 kPa | Optimal (seedling stage) | Germination / transplant |
| 0.8 ~ 1.2 kPa | Optimal (vegetative) | Growth phase |
| 1.2 ~ 1.8 kPa | Optimal (reproductive) | Flowering / fruiting |
| > 1.8 kPa | Too high — plant water stress risk | — |

### Control Layers (env_coordinator)

- **L1 EnvTarget**: Read VPD/CO₂ setpoint from Method curve or static value
- **L2 SituationReport**: Assess deviation, limiting factor, and trend
- **L3 Coordinator**: PI + slew rate + anti-windup → actuator commands

### Analysis Assessment Reference

`analyze_control_performance` return values:

| assessment | Meaning | Action |
|-----------|---------|--------|
| `excellent` | RMSE < 0.1 kPa | Maintain |
| `good` | RMSE 0.1 ~ 0.2 kPa | Monitor |
| `oscillating` | Sign changes > 30% | Increase tolerance_vpd or extend cycle period |
| `poor_tracking` | RMSE ≥ 0.2 kPa | Check limiting_factor, review K calibration |

---

## 5. Claude Desktop Configuration

`~/.config/claude/config.json` (macOS: `~/Library/Application Support/Claude/config.json`):

```json
{
  "mcpServers": {
    "aot": {
      "command": "python",
      "args": ["-m", "aot.mcp_server.server"],
      "cwd": "/path/to/AoT_ai",
      "env": {
        "AOT_MCP_WRITE_ENABLED": "1",
        "AOT_MCP_AGENT_ID": "claude"
      }
    }
  }
}
```

Remove `AOT_MCP_WRITE_ENABLED` (or set to `0`) if write access is not required.

---

## 6. Prohibited Actions

AI agents must NOT:

- Disable safety gates (wind / rain / temperature limits)
- Directly modify seed presets (`SEED:*`)
- Command actuators beyond hardware limits
- Execute write tools without user confirmation
- Change VPD by more than 0.5 kPa in a single call

---

## 7. Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `WriteDisabled` error | Write tools globally off | Set `AOT_MCP_WRITE_ENABLED=1` |
| `seed_protected` error | Attempting to edit SEED preset | Duplicate the Method first |
| `sensors_health: stale` | ext_context expired | Check sensor connections and ext_context_collector |
| Token expired | Not approved within 60 s | Call the tool again and approve immediately |
| `rate_limit` error | Per-hour call count exceeded | Retry in the next hour window |
