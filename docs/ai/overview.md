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

Tools exposed by the external MCP server and the internal `mcp_aot` engine. Read tools run immediately; control and scheduling tools pass through the approval gate when called from the in-app assistant.

### Observation (read — immediate)

| Tool | Description |
|------|-------------|
| `get_spatial_tree` | Spatial hierarchy (Site > Zone > Device) tree |
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

### Control (user approval required)

| Tool | Description |
|------|-------------|
| `operate_device` | Immediate physical control of valves/pumps/lights |
| `set_output_state` | Turn an output on/off (optional duration, native bridge) |
| `schedule_device_control` | Reserve a one-off device operation at a specific time |

> In the in-app assistant, the control tools above and `add_schedule` execute only after confirmation via the approval card. When called directly through the external MCP server there is no approval gate, so — since it exposes control tools — connect that server only to trusted clients.

### Extended In-app Assistant Tools

Beyond the MCP catalog above, the in-app AI assistant uses additional tools for entity assembly, automation, and knowledge. Every state-changing tool requires approval.

- **Input/Output management**: `list_device_types`, `get_device_type_options`, `create_input`·`modify_input`·`delete_input`, `create_output`·`modify_output`·`delete_output`, `get_device_measurements`
- **Functions (automation)**: `get_function_list`, `create_function`, `create_sequence_function`, `modify_function_options`, `activate_function`·`deactivate_function`·`delete_function`
- **Schedule ledger**: `search_schedule`, `edit_schedule`, `delete_schedule`
- **Map (GIS)**: `list_geo_maps`, `get_device_location`, `set_device_location`, `delete_geo_shape`
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

Non-mutating **read tools** run immediately. **State-changing tools** pass through the approval gate when called from the in-app assistant.

- **Approval required (mutation / physical control)**: device control (`operate_device`, `set_output_state`, `schedule_device_control`), create/edit/delete of inputs/outputs/functions/notices/AI agents, map placement changes (`set_device_location`, `delete_geo_shape`), `add_schedule`, `configure_library_source`, etc.
- **No approval (low-risk writes)**: `create_note`, `knowledge_shelve` — reversible personal memos / unconfirmed knowledge that save immediately and are treated as non-authoritative until confirmed.

Actions requiring approval are not applied immediately; they are presented in the chat as an **approval card**. They execute only after the user approves, and nothing changes if the user rejects.

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

> This server executes tools as invoked (no approval gate of its own). Because it exposes control tools, connect it only to trusted clients. The approval card applies to the in-app assistant path only.

---

## Related Pages

- [Environmental Control Automation](env-control.md)
- [Full AI Guide](../ai_guide.md)
