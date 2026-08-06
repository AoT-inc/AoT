# AI Features Overview

AoT uses an MCP (Model Context Protocol) based AI agent to observe, diagnose, and control the environment in greenhouses and growing facilities. The AI acts in an advisory role — every state-changing action requires user approval before execution.

---

## AI System Architecture { #agents }

AoT's AI uses tools through two paths:

- **In-app AI assistant** — the dashboard chat assistant. A single agent loop sees the full tool catalog and selects/executes tools itself. State-changing actions (device control, entity create/edit/delete, etc.) run only after the user confirms them via the chat's **approval card**.
- **External MCP server** — `aot/aot_mcp_server.py` (standard MCP protocol, stdio/HTTP). Exposes AoT tools so external MCP clients such as Claude Desktop can call them directly.

```
User chat ───────────────┐            External MCP client (Claude Desktop, etc.)
                          ↓                          ↓
              In-app agent loop           aot_mcp_server.py (stdio/HTTP)
                          └──────────┬───────────────┘
                                     ↓
                     Tool registry (tool_registry.py, single source)
                                     ↓
                        AoT system (Daemon / InfluxDB / SQLite)
```

Both paths pull tools from the same registry (`aot/ai/services/tool_registry.py`), so their lists can never diverge.

---

## MCP Tool List

Tools exposed by the external MCP server and the internal `mcp_aot` engine. Read tools run immediately; control and scheduling tools pass through an approval gate either way — the in-app assistant's chat approval card, or the external MCP server's approval queue (`pending_approval` + `respond_to_confirmation`, see "Running the MCP Server" below).

### Observation (read — immediate)

| Tool | Description |
|------|-------------|
| `get_spatial_tree` | Spatial hierarchy (Site > Zone > Device) tree |
| `resolve_target` | Resolve a place/device name to its exact entity — check upfront whether it's a container (has children) |
| `get_device_list` | List of all registered devices (inputs/outputs/cameras) |
| `search_devices` | Find devices by name or type keyword |
| `get_sensor_detail` | Sensor time-series history (min/max/avg stats) |
| `get_weather` | Current weather for a field/zone (temp, RH, wind, precip) |
| `get_energy_report` | Energy usage report by period/zone |
| `get_cumulative_status` | EnvCoordinator DLI / GDD cumulative status |
| `search_notes` | Read notes/memos/work logs attached to a zone or device |
| `list_notices` | Notice board post list |
| `get_system_update_status` | Installed version vs latest GitHub release |
| `list_available_devices` | Devices available for AI judgment (native bridge) |
| `get_sensor_reading` | Latest reading for a specific sensor (native bridge) |

### Record / Task

| Tool | Description | Approval |
|------|-------------|----------|
| `create_note` | Create an undated memo/note attached to an entity, saved immediately | Not required |
| `add_schedule` | Register a human work task (weeding, inspection, cleaning) | Required |
| `add_schedule_batch` | Register schedules for multiple targets (e.g. per zone) behind a single approval | Required |

### Control (user approval required)

| Tool | Description |
|------|-------------|
| `operate_device` | Immediate physical control of valves/pumps/lights |
| `set_output_state` | Turn an output on/off (optional duration, native bridge) |
| `schedule_device_control` | Reserve a one-off device operation at a specific time |

> In the in-app assistant, the control tools above and `add_schedule` execute only after confirmation via the approval card. Calling directly through the external MCP server goes through the same kind of gate: the first call is not executed and comes back as `pending_approval` with a `confirmation_id`; the user must explicitly approve or reject that confirmation_id in chat (handled via `respond_to_confirmation`) or on the web review page, then the caller retries the same arguments plus `_confirmation_id` to actually execute it. See "Running the MCP Server" below for the full flow.

### Sequences (user approval required)

A [sequence](../Functions.md#trigger-sequence) runs several outputs in a set order — the usual shape for irrigation, where valves take turns and a pump spans the run. These tools read and shape one.

| Tool | Description |
|------|-------------|
| `configure_sequence_day` | Set one weekday's entire run plan in a single call: which devices run, in what order, for how long, and which run together |
| `modify_sequence_step` | One step's group, duration, single/total mode, total-step lead/lag margins, run order, enabled state, label — globally or for one weekday |
| `modify_sequence_schedule` | The daily window, cycle period and which weekdays the sequence runs |

`get_function_detail` returns a sequence's steps plus `weekly_plan` — what actually runs each weekday, in wall-clock time. Read that back to confirm a change rather than repeating the request.

Two things are worth knowing before using them:

- **Devices listed in the same slot run simultaneously**, and a slot shares one duration. That is how "open these two valves together for 40 minutes" is expressed.
- **A weekday can override which steps run, their group and their duration.** One sequence therefore covers, say, an evening pass on Thursday and a dawn pass on Friday. Do not create a second sequence just because a day differs.

`modify_function_options` does not work on sequences (or any trigger) — their settings are database columns, not `custom_options`. It refuses with a pointer to the tools above.

### Extended In-app Assistant Tools

Beyond the MCP catalog above, the in-app AI assistant uses additional tools for entity assembly, automation, and knowledge. Every state-changing tool requires approval.

- **Input/Output management**: `list_device_types`, `get_device_type_options`, `create_input`·`modify_input`·`delete_input`, `create_output`·`modify_output`·`delete_output`, `get_device_measurements`
- **Functions (automation)**: `get_function_list`, `get_function_detail`, `create_function`, `create_sequence_function`, `modify_function_options` (not for triggers — see Sequences above), `activate_function`·`deactivate_function`·`delete_function`, plus the sequence tools `configure_sequence_day`·`modify_sequence_step`·`modify_sequence_schedule`
- **Schedule ledger**: `search_schedule`, `edit_schedule`, `delete_schedule`
- **Map (GIS)**: `list_geo_maps`, `get_device_location`, `set_device_location`, `delete_geo_shape`
- **GIS inputs (map layers)**: `list_gis_inputs`, `create_gis_input`·`modify_gis_input`·`delete_gis_input`, `activate_gis_input` (manage map layer providers such as VWorld/Google/OpenWeather)
- **Facility/equipment lookup**: `get_facility_capacity` (a facility's heating/cooling capacity, volume, ventilation, irrigation design summary), `get_map_equipment` (map-drawn equipment's irrigation design summary per site/zone, sprinkler vs. drip kept separate), `get_map_equipment_detail` (individual sprinkler positions/spacing/radius, per-pipe detail — only when the summary isn't enough)
- **Notice board**: `create_notice`·`modify_notice`·`delete_notice`
- **AI agent management**: `list_ai_agents`, `list_ai_entries`, `create_ai_agent`·`modify_ai_agent`·`delete_ai_agent`
- **Knowledge library**: `knowledge_search`, `knowledge_shelve`, `list_library_source_types`, `smartfarmkorea_lookup`, `configure_library_source`
- **Diagnostics / misc**: `analyze_system_failure`, `get_local_time`, `get_tool_detail`, `read_manual`, `get_detailed_manifest`, `ask_user`

> The single source of truth for tools is `aot/ai/services/tool_registry.py`. When a tool is added or changed, that file — not this page — is authoritative.

---

## Per-Device AI Inclusion Toggle { #device-ai-toggle }

Each device's settings modal under `Configure -> Inputs` / `Configure -> Outputs` has an **Include in AI Judgment** toggle.

- On (default): the input/output is visible to AI judgment and control tools (spatial tree, device lookup, sensor/control tools, etc.).
- Off: the device is excluded from those tools' queries and control targets. Use this to hide sensitive devices, or devices the AI should never touch, on a per-device basis.

New inputs and outputs are created with this enabled by default (`is_ai_enabled=True`).

---

## Safety & Approval Model

Non-mutating **read tools** run immediately. **State-changing tools** pass through an approval gate no matter which path calls them.

- **Approval required (mutation / physical control)**: device control (`operate_device`, `set_output_state`, `schedule_device_control`), create/edit/delete of inputs/outputs/functions/notices/AI agents/GIS inputs, map placement changes (`set_device_location`, `delete_geo_shape`), `add_schedule`·`add_schedule_batch`, `configure_library_source`, etc.
- **No approval (low-risk writes)**: `create_note`, `knowledge_shelve` — reversible personal memos / unconfirmed knowledge that save immediately and are treated as non-authoritative until confirmed.

Actions requiring approval are not applied immediately. In the **in-app assistant** they are presented in chat as an **approval card**, executed only once the user approves. Through the **external MCP server** they come back as a `pending_approval` response (a queued confirmation_id) and only proceed once the user explicitly approves or rejects that id — either path, nothing changes if the user rejects.

---

## Knowledge Library

The `AI -> Library` page (`/ai/library`) is where you register the **context sources** that ground the AI's answers. Sources can be documents (PDF/text), web URLs, REST APIs, or internal queries.

### Knowledge Digest Pipeline

Long prose sources such as documents and web URLs are pre-processed **once**, at registration time:

1. The source is split into **chunks**.
2. Each chunk is **digested (LLM summarize + keyword extraction)** and cached in the `ai_knowledge_chunk` table.
3. At query time there is **no LLM call** — retrieval is pure DB lookup + deterministic search, so answers are fast and cheap.

Each chunk reuses the same **3-state trust pipeline** (`system_generated` → `pending` → `user_confirmed`) as context records, so document-shaped knowledge is reviewed and approved through the same UX.

### Multi-site Scoping (facility_id)

Each chunk stores the `facility_id` (site/facility boundary) of its source, and knowledge search filters on it.

- **A document uploaded for site A never surfaces in an answer for site B.**
- Searching **without** a `facility_id` excludes **all** library knowledge — a deliberate no-cross-site-leakage behavior, not an unfiltered fallback.

This scoping keeps each facility's manuals and cultivation guidance separate when several sites are operated from one system.

---

## Running the MCP Server

A standard MCP server for external MCP clients. It is warm-started automatically when the app boots, and can also be run manually.

```bash
# stdio mode (default) — local clients such as Claude Desktop
python3 /opt/AoT/aot/aot_mcp_server.py

# HTTP mode — remote clients (default port 5700)
python3 /opt/AoT/aot/aot_mcp_server.py --http --port 5700
```

To connect from Claude Desktop, add to `claude_desktop_config.json`:

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

> State-changing tool calls do not execute immediately here either (`aot/ai/services/mcp_safety_gate.py`). The first call comes back as `pending_approval` with a `confirmation_id`; the user must explicitly approve or reject it, in that same conversation or on the web review page (`/ai/mcp_review`), which is handled through `respond_to_confirmation`. Approving executes nothing by itself — retry the same call with `_confirmation_id` added afterward. The calling AI has no way to decide or fake this approval on its own. Set `AOT_MCP_WRITE_ENABLED=0` to refuse write tools outright (advice-only mode). Two separate deadlines apply: 15 minutes by default for a human to approve (`AOT_MCP_CONFIRM_TTL_SEC`), then a fresh 5 minutes from the moment of approval to execute (`AOT_MCP_APPROVED_TTL_SEC`). It still exposes control tools, so connect this server only to trusted clients.

---

## Related Pages

- [Environmental Control Automation](env-control.md)
- [Scheduler](scheduler.md)
- [Full AI Guide](../ai_guide.md)
