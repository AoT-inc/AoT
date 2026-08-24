# AI Features Overview

AoT uses an MCP (Model Context Protocol) based AI agent to observe, diagnose, and control the environment in greenhouses and growing facilities. The AI acts in an advisory role — any action that moves equipment requires user approval before execution (edits that only change configuration are exempt; see the Sequences section).

---

## Getting started: there are two switches { #enable-and-start }

Using the AI takes two switches in two different places. They are deliberately not one.

| Switch | Where | What it turns on |
|--------|-------|------------------|
| **Enable AI Service** | Settings > General | The AI menu appears in the navigation and the AI page becomes reachable. Chat and advice requests work. |
| **AI Service Operation** | AI > AI Agent | Work that runs without anyone asking for it — periodic summaries, context broadcast, weather summary, MCP health checks, real-time alerts. |

The order is **enable in Settings → register a model (agent) on the AI page → start operation**.

- **Operation cannot be started with no model registered.** Running background work with nothing to ask only piles up errors in the log every cycle. The switch is available only once at least one agent is activated.
- **Deactivating or deleting the last model stops operation too.** Re-activating a model later does not silently resume autonomous operation — start it again on the AI page.
- **Chat and advice requests still work while operation is off.** That way you can try a freshly registered model without committing to autonomous operation.

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

Tools exposed by the external MCP server and the internal `mcp_aot` engine. Read tools and configuration-edit tools run immediately; control, scheduling and activation tools pass through an approval gate either way — the in-app assistant's chat approval card, or the external MCP server's approval queue (`pending_approval` + `respond_to_confirmation`, see "Running the MCP Server" below).

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

### Sequences (configuration edits need no approval)

A [sequence](../Functions.md#trigger-sequence) runs several outputs in a set order — the usual shape for irrigation, where valves take turns and a pump spans the run. These tools read and shape one.

| Tool | Description |
|------|-------------|
| `configure_sequence_day` | Set one weekday's entire run plan in a single call: which devices run, in what order, for how long, and which run together |
| `modify_sequence_step` | One step's group, duration, single/total mode, total-step lead/lag margins, run order, enabled state, label — globally or for one weekday |
| `modify_sequence_schedule` | The daily window, cycle period and which weekdays the sequence runs |

> **Sequence configuration edits apply immediately, without approval.** The three
> tools above, plus `create_sequence_function` and `modify_function_options`,
> change configuration only — they move no equipment. An edit takes effect on the
> ground only after `activate_function`, and activation is still gated.
> The accepted trade-off: editing the schedule of an *already active* sequence
> shifts its next run without approval (decided 2026-08-07).

`get_function_detail` returns a sequence's steps plus `weekly_plan` — what actually runs each weekday, in wall-clock time. Read that back to confirm a change rather than repeating the request.

Two things are worth knowing before using them:

- **Devices listed in the same slot run simultaneously**, and a slot shares one duration. That is how "open these two valves together for 40 minutes" is expressed.
- **A weekday can override which steps run, their group and their duration.** One sequence therefore covers, say, an evening pass on Thursday and a dawn pass on Friday. Do not create a second sequence just because a day differs.

`modify_function_options` does not work on sequences (or any trigger) — their settings are database columns, not `custom_options`. It refuses with a pointer to the tools above.

### Call state (`call_state`) { #call-state }

Every `tools/call` response carries a `call_state`. It tells you **whether the call
actually ran** without having to know each tool's own `status` vocabulary
(`modified`, `created`, `deleted`, `configured`, `success`, …).

| Value | Meaning | What the client should do |
|------|------|------|
| `executed` | Ran on this call (read tools included) | Report the result |
| `already_executed` | The server already ran it when the user approved | Report the enclosed `result`; do not call again |
| `pending_approval` | Not executed, waiting on a human | Point the user at the approval page and wait |
| `approval_rejected` | The user rejected it | Do not execute; switch to advice |
| `approval_expired` | The confirmation expired | Request approval again |
| `refused` | Refused for another reason (rate limit, argument mismatch, …) | Read `reason_code` and explain |
| `failed` | The tool ended in an error | Report the error |

The existing `status` values are unchanged — code and deployed configs already
branch on them, so this adds an axis rather than redefining one.

### Extended In-app Assistant Tools

Beyond the MCP catalog above, the in-app AI assistant uses additional tools for entity assembly, automation, and knowledge. Every state-changing tool requires approval.

- **Input/Output management**: `list_device_types`, `get_device_type_options`, `create_input`·`modify_input`·`delete_input`, `create_output`·`modify_output`·`delete_output`, `get_device_measurements`
- **Functions (automation)**: `get_function_list`, `get_function_detail`, `create_function`, `create_sequence_function`, `modify_function_options` (not for triggers — see Sequences above), `activate_function`·`deactivate_function`·`delete_function`, plus the sequence tools `configure_sequence_day`·`modify_sequence_step`·`modify_sequence_schedule`
- **Schedule ledger**: `search_schedule`, `edit_schedule`, `delete_schedule`
- **Map (GIS)**: `list_geo_maps`, `get_device_location`, `set_device_location`, `delete_geo_shape`, `list_unbound_slots` (which places have no device), `rebind_device` (move every map slot of one device onto another)
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

- **Approval required (mutation / physical control)**: device control (`operate_device`, `set_output_state`, `schedule_device_control`), create/edit/delete of inputs/outputs/functions/notices/AI agents/GIS inputs, map placement changes (`set_device_location`, `delete_geo_shape`), device replacement (`rebind_device`), `add_schedule`·`add_schedule_batch`, `configure_library_source`, etc.
- **No approval (low-risk writes)**: `create_note`, `knowledge_shelve` — reversible personal memos / unconfirmed knowledge that save immediately and are treated as non-authoritative until confirmed.

Actions requiring approval are not applied immediately. In the **in-app assistant** they are presented in chat as an **approval card**, executed only once the user approves. Through the **external MCP server** they come back as a `pending_approval` response (a queued confirmation_id) and only proceed once the user explicitly approves or rejects that id — either path, nothing changes if the user rejects.

Approving on the web review page (`AI → MCP Servers → AI Requests & Advice`) **runs it there and then**. Previously approval only issued a permit: the person had to go back to the AI and tell it, and the AI had to call again — a round trip the AI could not close on its own, since a chat model only acts when spoken to. The server now executes using exactly the arguments stored with the confirmation, so what the approval screen showed and what runs cannot diverge. If the AI later calls again with the same confirmation_id it gets that stored result back instead of a second execution. Only irreversible physical control (valves, pumps) asks for one extra confirmation on the approval screen.

---

## Knowledge Library

The `AI -> Library` page (`/ai/library`) is where you register the **context sources** that ground the AI's answers. Sources can be documents (PDF/text), web URLs, REST APIs, or internal queries.

### Where knowledge comes from

Four kinds of thing live in the library, and the AI cites each of them differently:

| Origin | What it is | How the AI cites it |
|---|---|---|
| Authoritative | A synced public-data feed (e.g. RDA, Nongsaro) | Stated as fact, with the source named |
| Entered by a person | You typed it in, or uploaded a document | Trusted — you are the source |
| Derived from data | Worked out from this system's own measurements | Presented as an observation here, not a general rule |
| AI-curated | The AI looked something up or worked it out and saved it | **Flagged as an unconfirmed note** until a person confirms it |

The AI can write to the library itself: when it researches something it saves a
summary so the next question does not start from nothing. Those notes always
enter unconfirmed and are always disclosed as such — the server appends the
disclosure even if the model forgets to.

### Reviewing what the AI wrote

The **AI-Curated Knowledge Review** section lists the AI's own notes. Open the
source link to check the original, then confirm, edit or retire. Confirming is
what promotes a note out of "unconfirmed"; a note with no source link cannot
really be checked, so it shows no link and stays unconfirmed.

**Reviewed knowledge only** (off by default) stops the AI citing its own
unreviewed notes. Authoritative and hand-entered knowledge is unaffected.

### Browsing and adding

The **Knowledge Items** section shows everything the AI can cite — search it,
filter by tag or origin, and set aside anything stale (set-aside keeps the row;
it only takes it out of the AI's reach).

**Add Knowledge** writes in what you already know, without an AI turn or a
registered source. What you write is treated as confirmed: you are the source.

### Knowledge Digest Pipeline

Long prose sources such as documents and web URLs are pre-processed **once**, at
registration time:

1. The source is split into **chunks**.
2. Each chunk is **digested (LLM summarize + keyword extraction)** and cached in the `ai_knowledge_chunk` table.
3. At query time there is **no LLM call** — retrieval is pure DB lookup + deterministic search, so answers are fast and cheap.

### Scoping is by tag, not by site

!!! warning "This changed — the library is farm-wide"
    Knowledge used to be filtered by `facility_id`, and earlier versions of this
    page said a document registered for one site could never surface for
    another. **That is no longer true.** The library is a flat, farm-wide
    catalog: any item can be retrieved for any question, and relevance is
    decided by tags and keyword scoring.

    Do not treat the library as a confidentiality boundary. If something must
    not be visible to everyone who uses this AI, do not put it in the library.

Scope comes from **tags** instead — free text (`radish`, `north-block`,
`bridge-a`), whatever you actually manage. AoT is not farm-only, so there is no
fixed vocabulary; tags are how a query narrows to the right subject.

### Built-in feeds are Korean

Every pre-built public-data feed in the Add list is Korean (RDA, Nongsaro,
NCPMS, SmartFarmKorea) and needs an API key from that provider. Everywhere else,
the library is filled the other way: your own documents, web pages, REST APIs —
plus whatever the AI looks up and shelves as it works.

---

## Running the MCP Server

A standard MCP server for external MCP clients. It is warm-started automatically when the app boots, and can also be run manually.

```bash
# stdio mode (default) — a local client on the same machine
python3 /opt/AoT/aot/aot_mcp_server.py

# HTTP mode — remote clients (default port 5700)
python3 /opt/AoT/aot/aot_mcp_server.py --http --port 5700
```

HTTP mode serves two things side by side.

| Path | What | Used by |
|------|------|------|
| `POST /mcp` | **MCP Streamable HTTP** (the standard transport) | Claude Desktop/Code, Cursor, any MCP client |
| `GET /mcp/info`, `GET /mcp/tools/list`, `POST /mcp/tools/call` | Custom REST | ChatGPT Custom GPT (OpenAPI Actions), curl checks |

A standard client needs only the URL and an API key — no relay script.

```bash
claude mcp add --transport http aot https://<host>/aotmcp/mcp \
  --header "X-API-KEY: <base64 api key>"
```

`GET /mcp` returns 405: this server offers no server-to-client SSE stream. It runs
waitress with four threads, so one held connection would starve tool calls. The
spec allows this, and it is where server-initiated notifications would go later.

The REST API stays because ChatGPT Custom GPTs on ordinary plans cannot register
an MCP server — they attach through OpenAPI Actions only.

### Connecting a ChatGPT Custom GPT { #chatgpt-setup }

Register the three REST paths above (`/mcp/info`, `/mcp/tools/list`,
`/mcp/tools/call`) as an **OpenAPI Action**. Creating a Custom GPT with
Actions requires a paid ChatGPT plan (Plus/Team/Enterprise/Pro) — free
accounts cannot use this path at all.

1. **Issue an API key** — under `Settings > Users`, generate a new API key for
   your account (name it something like "ChatGPT" so you can revoke just this
   connection later). If this GPT should only ever read, pick scope
   `readonly` at issue time — write tool calls are then refused server-side,
   so a Custom GPT misconfiguration cannot touch a device by accident. If
   more than one person will use it, issue a separate key per person — the
   audit log then shows who called what, and a leaked key can be revoked
   without cutting off everyone else.
2. **Confirm HTTP mode is on and reachable** — the server must be running
   with `--http --port 5700`, and ChatGPT must be able to reach that port (or
   whatever path your reverse proxy exposes it at). Check unauthenticated
   first (returns only version and tool count, no key needed):
   ```bash
   curl https://<host>:5700/mcp/info
   ```
3. **Create the GPT**: in ChatGPT, go to **Explore GPTs → Create →
   Configure**. Fill in a name and description, and in **Instructions** paste
   at least the following — copy it verbatim or adapt it to your site:

   ```
   You are an assistant for this AoT system: you observe status, advise, and
   can register device-control requests when asked.

   - Don't call listTools out of habit. The full tool catalog is a large
     response that eats into the conversation budget. Call it once early to
     learn tool names and arguments, then call only the tools you need.
   - Prefer narrow tools. For a single device or zone, use a tool that
     targets just that instead of a broad summary tool.
   - When calling callTool, always JSON-encode `arguments` into a string.
     E.g. not {"zone_name": "North Field"} but
     "{\"zone_name\": \"North Field\"}". Empty is "{}".
   - Every tool response carries call_state. Judge success/failure from that
     field alone — each tool's own `status` field uses different words:
       executed / already_executed → done, relay the result
       pending_approval            → not yet run, tell the user to approve it
       approval_rejected           → rejected, don't retry — offer advice instead
       approval_expired            → approval window expired, ask again
       refused / failed            → refused or errored, relay the reason
   - If a state-changing request comes back pending_approval, don't retry it
     yourself — tell the user to approve it on the web approval screen.
   - Answer in plain language, without jargon.
   ```

4. **Add the Action**: further down the same screen, under **Actions →
   Create new action**, paste the schema below (replace `<host>` with your
   real address):

   ```yaml
   openapi: 3.1.0
   info:
     title: AoT MCP
     version: "1.0.0"
   servers:
     - url: https://<host>:5700
   paths:
     /mcp/tools/list:
       get:
         operationId: listTools
         summary: List available tools and each tool's argument schema.
         responses:
           "200": { description: OK }
     /mcp/tools/call:
       post:
         operationId: callTool
         summary: Call one tool by name with arguments.
         requestBody:
           required: true
           content:
             application/json:
               schema:
                 type: object
                 required: [name]
                 properties:
                   name:
                     type: string
                     description: A tool name returned by listTools
                   arguments:
                     type: string
                     description: >-
                       Tool arguments serialized as a JSON object string.
                       E.g. "{\"zone_name\": \"North Field\"}". Empty is "{}".
         responses:
           "200": { description: OK }
   ```

5. **Set authentication**: Authentication → API Key → Auth Type `Custom` →
   Header name `X-API-KEY` → value is the API key (base64) from step 1.
6. **⚠️ Declare `arguments` as a string — never as an object.** There are
   over 100 tools, so their argument shapes cannot all be declared in one
   OpenAPI schema. Leave `arguments` as a free-form object and ChatGPT
   Actions silently drops the field it cannot fill (real incident,
   2026-08-09: a `list_devices_in_area` call required `area_name`, but the
   request body arrived with no `arguments` key at all). Declaring it as a
   string, as shown above, already avoids this — and step 3's Instructions
   restate the same rule for the same reason.
7. **Save and verify**: keep visibility set to **Only me** unless you mean to
   share it. In the chat, ask something like "give me a status briefing" — if
   a tool call and a response come back, it's connected.
8. **State-changing tools still don't execute immediately on this path.** The
   first call comes back as `pending_approval` with a `confirmation_id` —
   ChatGPT should show that to the user, who approves it on the web approval
   screen, then the same call is retried with `_confirmation_id` added to
   actually execute. There is no automatic re-approval inside a Custom GPT.
   Two screens show the approval list — day to day, the scheduler page
   (`/scheduler`) works fine (the "Pending control requests" block at the
   top). For the audit log and advice history alongside it, there's a
   dedicated page (`/api/v1/mcp/review_page`, menu: **AI → MCP Servers → AI
   Requests & Advice**) — the approval list itself is the same either way.

**When it won't connect**

| Symptom | Check |
|---|---|
| "unauthorized" / API key error | Whitespace around the key pasted in step 5, or a revoked key |
| Action won't save | Whether step 4's schema was pasted whole — a truncated brace breaks the save |
| Keeps answering "I can't find that tool" | The GPT isn't calling listTools first — nudge it with "check the tool list first" |
| Reads fine but never controls anything | Expected — writes always go through human approval (step 8) |
| Name-based questions still give odd answers | Check the version with `get_system_update_status` — see the note below |

> The map-related bug fixes covered on this page (`get_weather` name lookup
> always landing on the same wrong shape, `get_spatial_tree`'s filter doing
> nothing, a zone disappearing from the hierarchy query) ship in **AoT app
> v26.08.8 and later**. Right after connecting, call the
> `get_system_update_status` tool once to confirm the installed version — on
> an older install, questions asked by field/zone name may still return the
> old wrong answers.

### Connecting Claude Desktop

Add to `claude_desktop_config.json`:

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

> State-changing tool calls do not execute immediately here either (`aot/ai/services/mcp_safety_gate.py`). The first call comes back as `pending_approval` with a `confirmation_id`; the user must explicitly approve or reject it, in that same conversation or on the scheduler page (`/scheduler`; for the audit log too, `/api/v1/mcp/review_page`), which is handled through `respond_to_confirmation`. Approving executes nothing by itself — retry the same call with `_confirmation_id` added afterward. The calling AI has no way to decide or fake this approval on its own. Set `AOT_MCP_WRITE_ENABLED=0` to refuse write tools outright (advice-only mode). Two separate deadlines apply: 15 minutes by default for a human to approve (`AOT_MCP_CONFIRM_TTL_SEC`), then a fresh 5 minutes from the moment of approval to execute (`AOT_MCP_APPROVED_TTL_SEC`). It still exposes control tools, so connect this server only to trusted clients.

---

## Related Pages

- [Environmental Control Automation](env-control.md)
- [Scheduler](scheduler.md)
- [Full AI Guide](../ai_guide.md)
