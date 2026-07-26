# AoT AI Agent Guide (English)

How AoT's AI agent observes, diagnoses, and controls greenhouses and growing facilities. The AI works through two paths: the dashboard's **in-app assistant** (agent loop), and the **external MCP server** (`aot/aot_mcp_server.py`) that external clients such as Claude Desktop connect to. Both paths pull tools from the same tool registry (`aot/ai/services/tool_registry.py`).

---

## 1. Tool Catalog

### 1.1 MCP tools (external server + `mcp_aot` engine)

| Category | Tool | Description | Approval |
|----------|------|-------------|----------|
| Observe | `get_spatial_tree` | Spatial hierarchy (Site > Zone > Device) tree | No |
| Observe | `resolve_target` | Resolve a name to its exact entity, check whether it's a container (has children) | No |
| Observe | `get_device_list` | List of all registered devices | No |
| Observe | `search_devices` | Find devices by name/type | No |
| Observe | `get_sensor_detail` | Sensor time-series history (min/max/avg) | No |
| Observe | `get_weather` | Current weather for a field/zone | No |
| Observe | `get_energy_report` | Energy usage by period/zone | No |
| Observe | `get_cumulative_status` | EnvCoordinator DLI/GDD cumulative status | No |
| Observe | `list_available_devices` | Devices available for AI judgment (native) | No |
| Observe | `get_sensor_reading` | Latest reading for a sensor (native) | No |
| Notes | `search_notes` | Read zone/device notes and work logs | No |
| Notes | `create_note` | Save a memo/note attached to an entity | No |
| Notices | `list_notices` | Notice board post list | No |
| System | `get_system_update_status` | Installed version vs latest GitHub release | No |
| Task | `add_schedule` | Register a human work task (weeding, inspection, cleaning) | **Yes** |
| Task | `add_schedule_batch` | Register schedules for multiple targets (e.g. per zone) behind a single approval | **Yes** |
| Control | `operate_device` | Immediate control of valves/pumps/lights | **Yes** |
| Control | `set_output_state` | Turn an output on/off (optional duration, native) | **Yes** |
| Control | `schedule_device_control` | Reserve a one-off device operation at a time | **Yes** |
| Approval | `respond_to_confirmation` | Approve/reject one or more pending confirmation_id(s) | N/A (this IS the approval) |

### 1.2 Extended in-app assistant tools

Beyond the catalog above, the in-app assistant uses additional tools for entity assembly, automation, and knowledge. Every state-changing tool requires approval.

- **Inputs/Outputs**: `list_device_types`, `get_device_type_options`, `create_input`·`modify_input`·`delete_input`, `create_output`·`modify_output`·`delete_output`, `get_device_measurements`
- **Functions (automation)**: `get_function_list`, `create_function`, `create_sequence_function`, `modify_function_options`, `activate_function`·`deactivate_function`·`delete_function`
- **Schedule ledger**: `search_schedule`, `edit_schedule`, `delete_schedule`
- **Map (GIS)**: `list_geo_maps`, `get_device_location`, `set_device_location`, `delete_geo_shape`
- **GIS inputs (map layers)**: `list_gis_inputs`, `create_gis_input`·`modify_gis_input`·`delete_gis_input`, `activate_gis_input`
- **Notices**: `create_notice`·`modify_notice`·`delete_notice`
- **AI agents**: `list_ai_agents`, `list_ai_entries`, `create_ai_agent`·`modify_ai_agent`·`delete_ai_agent`
- **Knowledge library**: `knowledge_search`, `knowledge_shelve`, `list_library_source_types`, `smartfarmkorea_lookup`, `configure_library_source`
- **Diagnostics / misc**: `analyze_system_failure`, `get_local_time`, `get_tool_detail`, `read_manual`, `get_detailed_manifest`, `ask_user`

> The single source of truth for tools is `aot/ai/services/tool_registry.py`. When a tool is added or changed, that file — not this page — is authoritative.

---

## 2. Safety & Approval Policy

- **Read tools** run immediately.
- **State-changing tools** (mutation / physical control / scheduling) pass through an approval gate no matter which path calls them.
  - **In-app assistant**: not applied immediately — they appear in the chat as an **approval card** and execute only after the user approves.
  - **External MCP server** (`aot_mcp_server.py`, `aot/ai/services/mcp_safety_gate.py`): the first call is not executed and comes back as `pending_approval` + `confirmation_id`. Once the user explicitly approves or rejects that confirmation_id in the same conversation, it's processed via `respond_to_confirmation` (or a click on the web review page `/ai/mcp_review`); after approval, the caller must retry the same tool with `_confirmation_id` added to actually execute it. The calling AI has no way to decide or fake this approval on its own. `AOT_MCP_WRITE_ENABLED=0` refuses write tools outright (advice-only mode).
- As exceptions, `create_note` and `knowledge_shelve` are reversible low-risk writes that save without approval and are treated as non-authoritative until confirmed.
- **Per-device AI inclusion toggle**: turning it off in a device's `Configure -> Inputs/Outputs` modal excludes that device from AI tools' queries and control (`is_ai_enabled`).
- The **external MCP server** goes through the same approval gate too, but it still exposes control tools — connect it only to trusted clients.

---

## 3. Recommended Workflows

### State check → control

```
1. get_spatial_tree
   → confirm Site > Zone > Device hierarchy and the target device's unique_id

2. search_devices(query='valve')  or  get_device_list
   → obtain the unique_id of the output device to control

3. get_sensor_detail(loc_id, sensor_type='temperature', time_range='24h')
   → check recent trend (diagnose the cause first if it looks off)

4. operate_device(device_id, state='on', value=...)
   → approval card is shown → executes only after the user approves
```

### Read notes → summarize

```
1. (context) each entity's note digest (first + recent) is pre-injected into system state
   → broad questions like "check each device's notes" can be answered with no tool call

2. search_notes(target_name='v111')
   → drill down into a specific device/zone's full/older notes
```

### Build automation (recurring/conditional control)

```
1. list_device_types(kind='function')
   → confirm valid function types (never invent a type)

2. create_function(function_type='trigger_timer_daily_time_point', name=..., params={...})
   → created after approval. Recurring irrigation belongs to a function, not schedule_device_control.

3. get_function_list  /  activate_function(function_id)
   → verify creation and activate (approval)
```

---

## 4. Domain Knowledge

### VPD (Vapor Pressure Deficit)

VPD = SVP × (1 − RH/100)  
SVP = 0.6108 × exp(17.27T / (T + 237.3)) [kPa]

| Range | State | Recommended crop stage |
|-------|-------|------------------------|
| < 0.4 kPa | Too low — suppressed transpiration, mold risk | — |
| 0.4 ~ 0.8 kPa | Optimal (seedling) | germination / early transplant |
| 0.8 ~ 1.2 kPa | Optimal (vegetative) | growth |
| 1.2 ~ 1.8 kPa | Optimal (generative) | flowering / fruit set |
| > 1.8 kPa | Too high — water stress risk | — |

### Environmental control 3-layer (EnvCoordinator)

- **L1 EnvTarget**: reads VPD/CO₂/light targets from a Method curve or fixed value
- **L2 SituationReport**: evaluates deviation, limiting factors, and trend
- **L3 Coordinator**: position-form PI + slew-rate limit + integral anti-windup → actuator commands

Use `get_cumulative_status` to check daily DLI (cumulative light) / GDD (cumulative temperature) and target attainment/debt. See [Environmental Control Automation](ai/env-control.md) for details.

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

Remote clients can run in HTTP mode:

```bash
python3 /opt/AoT/aot/aot_mcp_server.py --http --port 5700
```

---

## 6. Prohibitions

The AI agent must not:

- **Fabricate** data it did not obtain via a tool (sensors, weather, etc.). If unsure, answer "unknown / needs checking" and call a tool or ask the user.
- Execute control/mutation tools without user approval.
- **Invent** a device/function type without checking the valid list (`list_device_types`, etc.).
- Control a device excluded from AI judgment (`is_ai_enabled=False`).
- Disable safety-related functions/settings without user confirmation.

---

## 7. Common Mistakes

| Symptom | Cause | Fix |
|---------|-------|-----|
| Tool can't find a note | `target_name` not passed, so only keyword search ran | Pass the zone/device name as `target_name` |
| Device invisible to AI | `is_ai_enabled=False` | Turn on Include in AI Judgment in the device modal |
| Recurring control not schedulable | Confused with a one-off reservation | Use `create_function` for recurring/conditional control |
| External MCP write call stuck at `pending_approval` | Called `respond_to_confirmation` without the user's explicit approval text (or skipped it entirely) | Only call `respond_to_confirmation` after the user explicitly approves/rejects that confirmation_id in the conversation |
| A per-zone schedule attached to one container (site) instead | Passed the site name straight into `add_schedule`/`add_schedule_batch` | Call `resolve_target` first; if it returns `children`, call `add_schedule_batch` with those child names |
| Creation fails with a type error | Invented a nonexistent type | Confirm valid types first with `list_device_types` |
