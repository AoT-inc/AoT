# AoT AI Agent Guide (English)

Explains how AoT's AI observes, diagnoses, and controls facilities and fields. The AI runs through two paths: the dashboard's **in-app assistant** (the agent loop), and an **external MCP server** (`aot/aot_mcp_server.py`) that external clients such as Claude Desktop and ChatGPT connect to. Both paths pull their tools from the same tool registry (`aot/tools/tool_registry.py`).

---

## 1. Tool Surface — Always-Listed + Drawers

There are 146 tools in total, 128 of which are exposed to the external MCP. Listing all of them in a single `tools/list` response would alone exceed 20,000 tokens, so the surface is split into two layers.

- **Always-listed (core)** — 27 tools included in every `tools/list` call. Most everyday questions are answered with these alone.
- **Drawers** — the remaining 101 tools. They live in 8 purpose-grouped drawers, and their schemas are visible only once you open the drawer.

Four meta-tools for working with drawers are always listed.

| Tool | What it does |
|------|---------|
| `open_drawer` | Called with no argument, returns the list of drawers; called with `{drawer:'space'}`, returns the full definitions of that drawer's tools |
| `get_tool_detail` | Full definition of a single tool via `{tool_name}` |
| `use_tool` | Executes a tool inside a drawer via `{tool_name, arguments}`. Approval, permissions, and auditing behave the same as a direct call |
| `respond_to_confirmation` | Approves/rejects a pending confirmation (§3) |

> **Open the matching drawer before concluding something isn't possible.** Before answering "this system can't do that," or working around it with a core tool that only roughly fits, open the drawer for that purpose first. Drawer tools behave exactly like ordinary tools.

Setting the environment variable `AOT_MCP_TOOL_TIERING=0` exposes all 128 tools with no drawers (tiering is on by default).

### 1.1 Always-Listed Tools (27)

| Category | Tool | Description | Approval |
|------|------|------|------|
| Starting point | `get_system_brief` | One-glance system summary — start here | Not required |
| Resolve | `resolve_target` | Resolves a name to an entity, and whether it's a container (has child zones) | Not required |
| Space | `get_spatial_tree` | Site > zone > device hierarchy | Not required |
| Space | `get_map_equipment` | Equipment/devices placed on the map | Not required |
| Device | `get_device_list` / `search_devices` | Full list / search by name, type, or measurement kind | Not required |
| Device | `get_device_measurements` | List of a device's measurement channels | Not required |
| Device | `get_device_detail` | Everything about ONE device in a single call — what/where/measures/controls/communication/space/constraints, instead of chaining search_devices + get_device_measurements + get_device_location | Not required |
| Device | `get_output_state` | Current state of an output (valve, pump, light) | Not required |
| Measurement | `get_sensor_detail` | Sensor history (min/max/avg), including Function aggregate values | Not required |
| Measurement | `get_zone_sensor_summary` | Latest values plus period stats for an entire zone, in one call | Not required |
| Measurement | `get_weather` / `get_weather_forecast` | Current weather / forecast | Not required |
| Plot | `list_plots` / `get_plot` | List of crop plots / plot detail | Not required |
| Function | `get_function_list` / `get_active_functions_summary` | List of Functions / summary of active ones | Not required |
| Function | `activate_function` / `deactivate_function` | Turn a Function on/off | **Required** |
| Control | `operate_device` | Immediate control of a valve, pump, light, etc. | **Required** |
| Schedule | `search_schedule` | Look up schedules | Not required |
| Schedule | `add_schedule` | Register a human work schedule/memo | Not required (§3) |
| Record | `search_notes` / `create_note` | Look up notes / write a note | Not required |
| Knowledge | `knowledge_search` | Free-text search over the manual and knowledge library | Not required |
| Definition | `list_device_types` | List of valid device/Function types | Not required |
| System | `list_ai_agents` | Registered AI agents | Not required |
| Approval | `list_pending_confirmations` | Pending confirmations | Not required |

### 1.2 8 Drawers (101)

| Drawer | Contents | Tools |
|------|------|------|
| `device` | Device operation/status | `get_control_state`, `set_output_state`\* |
| `measurement` | Sensors, environment, energy | `get_anomalies`, `get_cumulative_status`, `get_device_freshness`, `get_energy_report` |
| `function` | Functions, controllers, sequences | `get_function_detail`, `create_function`\*, `delete_function`\*, `create_sequence_function`, `modify_function_options`, `modify_sequence_schedule`, `modify_sequence_step`, `configure_sequence_day` |
| `schedule` | Schedules, reservations | `schedule_device_control`\*, `edit_schedule`\*, `delete_schedule`\*, `add_schedule_batch` |
| `record` | Notes, notices, knowledge, advice | `list_notices`, `get_note_attachment`, `search_archives`, `get_archived_document`, `knowledge_shelve`, `list_advice`, `submit_advice`, `list_lookup_sources`, `query_data_source`, `query_reference_table`, `list_library_source_types`, `smartfarmkorea_lookup`, `create_notice`\*, `modify_notice`\*, `delete_notice`\*, `archive_note`\*, `restore_note_from_archive`\*, `delete_archive`\*, `set_document_tier`\*, `configure_library_source`\* |
| `space` | Map, zones, facilities, plots | `list_geo_maps`, `get_crop_status`, `get_device_location`, `get_map_equipment_detail`, `get_facility_capacity`, `get_address`, `distance_between`, `nearest`, `get_plot_history`, `list_plot_journals`, `get_plot_journal`, `list_programs`, `get_program`, `propose_plot_split`, 18 plot-ledger write tools\* (`create_plot`, `modify_plot`, `end_plot`, `copy_plot`, `delete_plot`, `apply_plot_split`, `confirm_plot_stage`, `reschedule_plot_stage`, `add_plot_stage`, `remove_plot_stage`, `undo_plot_stage`, `set_plot_stage_guidance`, `apply_plot_resources`, `save_plot_schedule_as_program`, `create_plot_journal`, `delete_program`, `set_device_location`, `delete_geo_shape`), `create_program`, `modify_program` |
| `definition` | Device-definition CRUD | `get_device_type_options`, `list_gis_inputs`, `create_input`\*, `modify_input`\*, `delete_input`\*, `create_output`\*, `modify_output`\*, `delete_output`\*, `modify_gis_input`\*, `delete_gis_input`\*, `activate_gis_input`\*, `create_gis_input` |
| `system` | AI settings, status, diagnostics, screens | `get_local_time`, `get_system_update_status`, `get_storage_tier_status`, `analyze_system_failure`, `list_ai_entries`, `list_dashboards`, `list_tabs`, `list_widget_types`, `get_widget`, 8 widget/tab/agent write tools\*, `create_ai_agent` |

\* marks tools that require approval. The other write tools are "config-only writes" per §3 and save immediately without approval.

### 1.3 In-App Assistant Only

In addition to the above, the in-app assistant also uses `read_manual` (reads the manual by file name + section), `get_detailed_manifest`, `ask_user`, `get_sensor_reading`, `list_available_devices`, `set_output_state`, `list_unbound_slots`, `rebind_device`, and `get_function_doc` / `get_input_doc` / `get_output_doc`. When looking up the manual from the external MCP, use `knowledge_search` instead of `read_manual` — it finds the relevant section across the whole manual even when you don't know the file name.

> The single source of truth for tools is `aot/tools/tool_registry.py`. If this document and that file disagree, the file is correct.

---

## 2. Time — Don't Infer "Now" from the Data

Every response carries `now` = {`farm_local`, `tz`}. **That is the only current time.** Timestamps inside the data are past events, and a field like `evaluated_at` or `last_seen` is "when it was measured," not now.

- Timestamps are ISO 8601 and **are not all in the same timezone** — sensor values come back in that device's local time. Read each value's own offset as given.
- A device may sit in a different timezone from the farm's default. Before reasoning about day/night, a scheduled time, or "is it due yet" for a particular place, check that location's time with `get_local_time` (system drawer).

---

## 3. Safety and Approval

Tools fall into three tiers.

1. **Reads** — execute immediately.
2. **Config-only writes (approval-exempt)** — `add_schedule`, `add_schedule_batch`, `create_sequence_function`, `modify_function_options`, `modify_sequence_schedule`, `modify_sequence_step`, `configure_sequence_day`, `create_program`/`modify_program`, `create_gis_input`, `create_ai_agent`. They move no equipment and are always created inactive, so they save immediately. A person still has to activate them separately before they do anything, and that activation (`activate_function`, `activate_gis_input`) does require approval. Creating or deleting a Function itself — `create_function`, `delete_function` — is not in this tier: those require approval.
   `create_note` and `knowledge_shelve` are not counted as write tools at all. They are low-risk records that save immediately, and are treated as non-authoritative until a person confirms them.
3. **Writes that require approval** — all physical control and all ledger changes.

### In-App Assistant

Presented in chat as an **approval card**; it only runs once the user approves it.

### External MCP (`aot/tools/mcp_safety_gate.py`)

1. The first call to a write tool → doesn't execute; responds with `pending_approval` + a `confirmation_id`.
2. A person approves — via the dashboard's **MCP Approval widget**, the AI screen, or `respond_to_confirmation` only when the user has explicitly told you to approve it in this conversation.
3. Once approved, the server **executes immediately** with the arguments it stored. If the AI calls the same tool again later with the same arguments plus `_confirmation_id`, it doesn't re-execute — it returns the stored result (`already_executed`).

Rules to follow:

- **The AI cannot decide approval or answer on the user's behalf.** The original task instruction ("create these schedules") is not by itself "execute confirmation_id X." The same goes for batches — "clean up whatever's pending" is not approval for an unnamed set.
- The arguments must be **exactly identical** to what was approved for the call to go through (this prevents approval substitution).
- Expiry: a pending confirmation lasts **15 minutes** (`AOT_MCP_CONFIRM_TTL_SEC=900`); once approved, the execution window is another **5 minutes** (`AOT_MCP_APPROVED_TTL_SEC=300`, counted from the moment of approval).
- Call caps: `operate_device`, `set_output_state`, `schedule_device_control` — 20 per hour; `modify_sequence_step` — 60 per hour; everything else defaults to 10. Since the approval request and the re-call each count separately, the number of tasks you can actually complete is half of that.
- With `AOT_MCP_WRITE_ENABLED=0`, write tools don't even create an approval queue entry — they're refused outright and serve advice only.
- Connecting with a read-only API key forcibly disables write permission, and `respond_to_confirmation` only works with an Admin/Editor key.

### Other Restrictions

- **Per-device "include in AI decisions" toggle**: turning it off in a device's modal under **Settings → Inputs/Outputs** excludes that device from AI tools' queries and control (`is_ai_enabled`).
- The external MCP server is a server that exposes control tools. Connect it only to clients you trust.

---

## 4. Recommended Workflows

### Check status → control

```
1. get_system_brief
   → everything that exists and what's running right now, in one call

2. resolve_target(name='House 3')
   → resolve the name to an entity. If it has children, it's a container — target the children instead

3. search_devices(query='valve', zone='House 3')  or  get_device_list
   → get the output device(s) to control

4. get_sensor_detail(sensor_type='temperature', time_range='24h')
   → check the trend. If it looks off, diagnose the cause first

5. operate_device(device_id, state='on', value=...)
   → sends an approval request → the device only actually moves once a person approves it
```

### Finding manuals and knowledge

```
knowledge_search(query='confirming a plot stage')
   → returns the matching manual section's text directly. You don't need to know the page.

From the in-app assistant you can also name the page. The context carries only the
list of page names (manual_index_files), so this is two steps:

1. read_manual(target_id='geo/plots.md')
   → that page's table of contents. Short pages with no sections come back whole.
2. read_manual(target_id='geo/plots.md', params={'section': '<a heading from step 1>'})
   → that section's body
```

### Look up notes → summarize

```
1. (context) Each entity's note digest is already injected into system state
   → a broad question like "check each device's notes" can be answered without a tool call

2. search_notes(target_name='v111')
   → drill down into the full/past notes for a specific device or zone
```

### Building automation (repeating/conditional control)

```
1. list_device_types(kind='function')
   → confirm the valid Function types (never invent a type)

2. use_tool('create_function', {function_type='trigger_timer_daily_time_point', ...})
   → repeating irrigation belongs in a Function, not schedule_device_control

3. get_function_list  →  activate_function(function_id)
   → confirm it was created, then activate it (requires approval)
```

---

## 5. Domain Knowledge

### VPD (Vapor Pressure Deficit)

VPD = SVP × (1 − RH/100)  
SVP = 0.6108 × exp(17.27T / (T + 237.3)) [kPa]

| Range | State | Recommended crop stage |
|------|------|--------------|
| < 0.4 kPa | Too low — transpiration suppressed, mold risk | — |
| 0.4 ~ 0.8 kPa | Optimal (seedling stage) | Germination / early transplant |
| 0.8 ~ 1.2 kPa | Optimal (vegetative growth) | Growth stage |
| 1.2 ~ 1.8 kPa | Optimal (reproductive growth) | Flowering / fruit set |
| > 1.8 kPa | Too high — water-stress risk | — |

### The three environmental control layers (EnvCoordinator)

- **L1 EnvTarget**: reads VPD/CO₂/light targets from a Method curve or a fixed value
- **L2 SituationReport**: evaluates deviation, limiting factors, and trend
- **L3 Coordinator**: positional PI + slew-rate limiting + anti-windup → actuator commands

`get_cumulative_status` (measurement drawer) shows the daily accumulation of DLI (daily light integral) and GDD (growing degree days), along with how far each is toward its target or in deficit. See [Environmental Control Automation](ai/env-control.md) for details.

---

## 6. Connection Setup

### stdio (Claude Desktop, etc.)

`claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "aot": {
      "command": "python3",
      "args": ["/opt/AoT/aot/aot_mcp_server.py"],
      "env": { "AOT_MCP_API_KEY": "<your issued API key>" }
    }
  }
}
```

### HTTP (remote clients)

```bash
python3 /opt/AoT/aot/aot_mcp_server.py --http --port 5700
```

- Endpoint: `POST/GET/DELETE /mcp` (Streamable HTTP). REST equivalents for compatibility: `GET /mcp/info`, `GET /mcp/tools/list`, `POST /mcp/tools/call`.
- Auth: the API key goes in the `X-API-KEY` header (base64). `Authorization: Basic`/`Bearer` is also accepted. Keys are issued from user settings, and **the key's owner is the caller's identity** — the call follows that user's permissions exactly.
- Turning off auth with `AOT_MCP_REQUIRE_AUTH=0` treats the caller as having no permissions, making it read-only.
- Turning off the MCP HTTP server toggle under **Settings → General** returns 503 without a restart.

---

## 7. Prohibited Actions

- **Inventing** data (sensor readings, weather, etc.) that wasn't obtained through a tool. When you don't know, say so ("I don't know / need to check") and either call a tool or ask a follow-up question.
- Running a control or mutation tool without the user's approval, or deciding approval on your own.
- **Making up** a device or Function type without checking the valid list (`list_device_types`, etc.) first.
- Controlling a device excluded from AI decisions (`is_ai_enabled=False`).
- Disabling a safety-related Function or setting without the user's confirmation.
- Showing the user raw UUIDs such as `unique_id`/`note_id` — refer to entities by name instead. The only exception is when the user explicitly asks for the id.

---

## 8. Common Mistakes

| Symptom | Cause | Fix |
|------|------|------|
| Answers "can't be done" for lack of a tool | Judged only from the 27 always-listed tools | Open the matching drawer with `open_drawer` first |
| Date calculations are off by a day | Inferred "now" from a data timestamp | Use `now.farm_local`, and `get_local_time` for location-specific reasoning |
| A tool can't find a note | Didn't pass `target_name`, so it ran a plain keyword search | Pass the zone/device name as `target_name` |
| A device doesn't show up to the AI | `is_ai_enabled=False` | Turn on "include in AI decisions" in the device's settings modal |
| Repeating control won't stick as a schedule | Confused with a one-shot reservation | Use `create_function` for repeating/conditional control |
| A write call never leaves `pending_approval` | Tried to proceed without the user's explicit approval | Only call `respond_to_confirmation` after the user has approved the confirmation_id in that conversation |
| Approved, but still rejected | Arguments differ from what was approved, or more than 5 minutes passed | Re-call with the identical arguments; if too late, get approval again first |
| A per-zone schedule lands on a single site | Passed the container's name straight into `add_schedule` | Check with `resolve_target` first; if `children` is present, use `add_schedule_batch` with the children's names |
| Creation fails with a type error | Invented a type that doesn't exist | Check valid types with `list_device_types` first |
