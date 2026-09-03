# AoT AI Agent Guide

Explains how AoT's AI agent observes, diagnoses, and controls a greenhouse or growing facility. The AI runs through two paths: the dashboard's **in-app assistant** (the agent loop), and an **external MCP server** (`aot/aot_mcp_server.py`) that external clients such as Claude Desktop connect to. Both paths pull their tools from the same registry (`aot/ai/services/tool_registry.py`).

---

## 1. Tool Catalog

### 1.1 MCP Tools (external server + the `mcp_aot` engine)

| Category | Tool | Description | Approval |
|------|------|------|------|
| Observe | `get_spatial_tree` | Spatial hierarchy tree (site > zone > device) | Not required |
| Observe | `resolve_target` | Resolves a name to the exact entity, and whether it's a container (has child zones) | Not required |
| Observe | `get_device_list` | Full list of registered devices | Not required |
| Observe | `search_devices` | Search devices by name/type or `measurement_type`, combinable with a zone name | Not required |
| Observe | `get_sensor_detail` | Sensor time-series history (min/max/avg), Functions (aggregated values) included | Not required |
| Observe | `get_zone_sensor_summary` | Latest values + period stats for every sensor across one or more zones, in one call | Not required |
| Observe | `list_plantings` | List of vegetation plots (growing seasons); `with_sensors` includes each plot's sensor values | Not required |
| Observe | `get_weather` | Current weather for a field/zone | Not required |
| Observe | `get_energy_report` | Energy usage by period and zone | Not required |
| Observe | `get_cumulative_status` | EnvCoordinator's accumulated DLI/GDD status | Not required |
| Observe | `list_available_devices` | List of devices eligible for AI decisions (native) | Not required |
| Observe | `get_sensor_reading` | Latest reading of a specific sensor (native) | Not required |
| Notes | `search_notes` | Look up notes/work logs for a zone or device | Not required |
| Notes | `get_note_attachment` | Retrieve a photo attached to a note, as an actual image | Not required |
| Notes | `create_note` | Attach and save a memo/note to a target | Not required |
| Notices | `list_notices` | List notice-board posts | Not required |
| System | `get_system_update_status` | Compares the installed version against the latest on GitHub | Not required |
| Tasks | `add_schedule` | Register a human work schedule (weeding, inspection, cleaning) | **Required** |
| Tasks | `add_schedule_batch` | Register schedules for multiple targets (e.g. per zone) under a single approval | **Required** |
| Control | `operate_device` | Immediate control of a valve, pump, light, etc. | **Required** |
| Control | `set_output_state` | Output on/off (optional duration, native) | **Required** |
| Control | `schedule_device_control` | Schedule a one-shot device control at a specific time | **Required** |
| Approval | `respond_to_confirmation` | Approve/reject one or more pending `confirmation_id`s | N/A (this *is* the approval) |

### 1.2 Additional In-App Assistant Tools

Beyond the catalog above, the in-app assistant also uses tools for assembling entities, automation, and knowledge. Every tool that changes state requires approval.

- **Inputs/Outputs**: `list_device_types`, `get_device_type_options`, `create_input`/`modify_input`/`delete_input`, `create_output`/`modify_output`/`delete_output`, `get_device_measurements`
- **Functions (automation)**: `get_function_list`, `create_function`, `create_sequence_function`, `modify_function_options`, `activate_function`/`deactivate_function`/`delete_function`
- **Schedule ledger**: `search_schedule`, `edit_schedule`, `delete_schedule`
- **Map (GIS)**: `list_geo_maps`, `get_device_location`, `set_device_location`, `delete_geo_shape`, `list_unbound_slots`, `rebind_device`
- **GIS inputs (map layers)**: `list_gis_inputs`, `create_gis_input`/`modify_gis_input`/`delete_gis_input`, `activate_gis_input`
- **Notices**: `create_notice`/`modify_notice`/`delete_notice`
- **AI agents**: `list_ai_agents`, `list_ai_entries`, `create_ai_agent`/`modify_ai_agent`/`delete_ai_agent`
- **Knowledge library**: `knowledge_search`, `knowledge_shelve`, `list_library_source_types`, `smartfarmkorea_lookup`, `configure_library_source`
- **Diagnostics and misc.**: `analyze_system_failure`, `get_local_time`, `get_tool_detail`, `read_manual`, `get_detailed_manifest`, `ask_user`

> The single source of truth for tools is `aot/ai/services/tool_registry.py`. When a tool is added or changed, that file takes precedence over this document.

---

## 2. Safety and Approval Policy

- **Read tools** execute immediately.
- **State-changing tools** (mutation, physical control, scheduling) go through an approval gate regardless of which path calls them.
  - **In-app assistant**: not applied immediately — presented in chat as an **approval card**, and only runs once the user approves it.
  - **External MCP server** (`aot_mcp_server.py`, `aot/ai/services/mcp_safety_gate.py`): the first call does not execute; it responds with `pending_approval` + a `confirmation_id`. Only once the user explicitly approves or rejects that `confirmation_id` within the conversation does `respond_to_confirmation` (or the web approval page `/ai/mcp_review`) process it — the same tool must then be called again with `_confirmation_id` attached to the same arguments for it to actually run. The calling AI cannot decide approval on its own or answer on the user's behalf. With `AOT_MCP_WRITE_ENABLED=0`, write tools are refused outright and serve advice only. Approval requests expire after 15 minutes by default; once approved, the execution window is another 5 minutes from the moment of approval.
- As an exception, `create_note` and `knowledge_shelve` save immediately without approval, since they are reversible, low-risk records — until confirmed, they are treated as unauthoritative information.
- **Per-device "include in AI" toggle**: turning this off in a device's modal under **Settings → Inputs/Outputs** excludes that device from AI tools' queries and control (`is_ai_enabled`).
- The **external MCP server** also goes through the approval gate, but since it is a server that exposes control tools in its own right, connect it only to clients you trust.

---

## 3. Recommended Workflows

### Check status → control

```
1. get_spatial_tree
   → confirm the site > zone > device hierarchy and the target device's unique_id

2. search_devices(query='valve')  or  get_device_list
   → get the unique_id of the output device to control

3. get_sensor_detail(loc_id, sensor_type='temperature', time_range='24h')
   → check the recent trend (diagnose the cause first if it looks off)

4. operate_device(device_id, state='on', value=...)
   → an approval card is presented → the device only actually moves once the user approves it
```

### Look up notes → summarize

```
1. (context) Each entity's note digest (earliest + most recent) is already
   injected into system state
   → a broad question like "check each device's notes" can be answered
     directly, without a tool call

2. search_notes(target_name='v111')
   → drill down into the full/past notes for a specific device or zone
```

### Building automation (repeating/conditional control)

```
1. list_device_types(kind='function')
   → confirm the valid function types (never invent a type)

2. create_function(function_type='trigger_timer_daily_time_point', name=..., params={...})
   → created once approved. Repeating irrigation belongs in a function,
     not schedule_device_control.

3. get_function_list  /  activate_function(function_id)
   → confirm creation and activate it (approval)
```

---

## 4. Domain Knowledge

### VPD (Vapor Pressure Deficit)

VPD = SVP × (1 − RH/100)
SVP = 0.6108 × exp(17.27T / (T + 237.3)) [kPa]

| Range | State | Recommended crop stage |
|------|------|--------------|
| < 0.4 kPa | Too low — transpiration suppressed, mold risk | — |
| 0.4 – 0.8 kPa | Optimal (seedling stage) | Germination / early transplant |
| 0.8 – 1.2 kPa | Optimal (vegetative growth) | Growth stage |
| 1.2 – 1.8 kPa | Optimal (reproductive growth) | Flowering / fruit set |
| > 1.8 kPa | Too high — water-stress risk | — |

### The three environmental control layers (EnvCoordinator)

- **L1 EnvTarget**: reads VPD/CO₂/light targets from a Method curve or a fixed value
- **L2 SituationReport**: evaluates deviation, limiting factors, and trend
- **L3 Coordinator**: positional PI + slew-rate limiting + anti-windup → actuator commands

`get_cumulative_status` shows the daily accumulation of DLI (daily light integral) and GDD (accumulated heat), and how far each is toward or behind its target. See [Environmental Control Automation](ai/env-control.md) for details.

---

## 5. Claude Desktop Setup

`claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "aot": {
      "command": "python3",
      "args": ["/opt/AoT/aot/aot_mcp_server.py"]
    }
  }
}
```

A remote client can run it in HTTP mode instead:

```bash
python3 /opt/AoT/aot/aot_mcp_server.py --http --port 5700
```

---

## 6. Prohibited Actions

The AI agent must never:

- **Invent** data (sensor readings, weather, etc.) it did not get from a tool. When it doesn't know, it must say so ("I don't know / need to check") and either call a tool or ask a follow-up question.
- Run a control or mutation tool without the user's approval.
- **Make up** a device or function type without checking the valid list (`list_device_types`, etc.) first.
- Control a device that has been excluded from AI decisions (`is_ai_enabled=False`).
- Disable a safety-related function or setting without the user's confirmation.

---

## 7. Common Mistakes

| Symptom | Cause | Fix |
|------|------|------|
| A tool can't find a note | Called without `target_name`, so it fell back to a plain keyword search | Pass the zone/device name as `target_name` |
| A device doesn't show up to the AI | `is_ai_enabled=False` | Turn on "include in AI decisions" in the device's settings modal |
| Repeating control won't stay as a schedule | Confused with a one-shot reservation | Use `create_function` for repeating/conditional control |
| An external MCP write call never leaves `pending_approval` | `respond_to_confirmation` was called without the user's explicit approval text in that conversation (or wasn't called at all) | Only call `respond_to_confirmation` after the user has explicitly approved or rejected the `confirmation_id` in that conversation |
| A per-zone schedule lands on the container (site) instead | The site's name was passed straight into `add_schedule`/`add_schedule_batch` | Check with `resolve_target` first; if `children` is present, call `add_schedule_batch` with those children's names |
| Creation fails with a type error | An invented type that doesn't exist | Check the valid types with `list_device_types` first |
