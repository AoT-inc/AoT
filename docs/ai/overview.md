# AI Features Overview

AoT uses an MCP (Model Context Protocol) based AI agent to observe, diagnose, and control the environment in greenhouses and growing facilities. The AI acts in an advisory role — all control actions require user approval before execution.

---

## AI Agent Architecture { #agents }

```
Claude / OpenAI API
        ↓
   MCP Server (FastMCP)
        ↓
   ┌────────────────────┐
   │  Observation tools  │  → Query InfluxDB / SQLite
   │  Diagnostic tools   │  → Anomaly detection, perf analysis
   │  Control tools      │  → Require user approval
   └────────────────────┘
        ↓
   AoT system (Daemon / Output Controller)
```

---

## Key Tools

### Observation (read — immediate)

| Tool | Description |
|------|-------------|
| `list_facilities` | List registered facilities |
| `get_facility_state` | Current T / RH / VPD / CO₂ / PAR |
| `get_sensor_history` | Sensor time series (1h / 24h / 7d) |
| `list_functions` | Active Function list |
| `get_function_state` | env_coordinator cycle state |
| `list_methods` | Method (setpoint curve) list |
| `list_outputs` | Current actuator command values |
| `get_recent_events` | Recent MCP audit log |

### Diagnostic (read — immediate)

| Tool | Description |
|------|-------------|
| `analyze_control_performance` | VPD tracking RMSE and oscillation analysis |
| `detect_sensor_anomaly` | Sensor outlier and drift detection |
| `suggest_setpoint_adjustment` | Recommended VPD target suggestion |
| `compare_periods` | Statistical comparison of two time periods |

### Control (write — user approval required)

| Tool | Description | Limits |
|------|-------------|--------|
| `set_vpd_target` | Change VPD target | ±0.5 kPa/call, 5/h |
| `update_method_point` | Modify Method control point | ±0.3 kPa/call, 10/h |
| `request_manual_lock` | Pause AI automatic control | 1–120 min, 3/h |
| `acknowledge_alert` | Acknowledge alert | 20/h |

---

## 3-Layer Safety Gates

### Layer 1 — Global write flag

Control tools are **disabled by default**. To enable:

```bash
# Environment variable
AOT_MCP_WRITE_ENABLED=1 python -m aot.mcp_server.server

# CLI flag
python -m aot.mcp_server.server --write
```

### Layer 2 — Value range validation

Each control tool has range, delta, and rate limits.

| Tool | Value range | Max delta/call | Max calls/h |
|------|-------------|----------------|-------------|
| `set_vpd_target` | 0.3–2.5 kPa | 0.5 kPa | 5 |
| `update_method_point` | 0.0–3.0 kPa | 0.3 kPa | 10 |
| `request_manual_lock` | 1–120 min | — | 3 |

### Layer 3 — User approval token

Write tools do not apply immediately. They return a 60-second TTL token. The user must call `confirm_action` to apply the change.

```
set_vpd_target(value=1.2)
    → { "pending": true, "token_id": "xxx", "expires_in": 60 }
        ↓
confirm_action(token_id="xxx", user_id="operator")
    → { "ok": true, ... }   ← applied at this point
```

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

```bash
# Read-only (default)
python -m aot.mcp_server.server

# Enable writes
AOT_MCP_WRITE_ENABLED=1 python -m aot.mcp_server.server --write
```

To connect from Claude Desktop, add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aot": {
      "command": "python",
      "args": ["-m", "aot.mcp_server.server"],
      "env": {
        "AOT_MCP_WRITE_ENABLED": "1"
      }
    }
  }
}
```

---

## Related Pages

- [Environmental Control Automation](env-control.md)
- [Full AI Guide](../ai_guide.md)
