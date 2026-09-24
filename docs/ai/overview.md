# AI Features Overview

AoT uses an MCP (Model Context Protocol) based AI agent to observe, diagnose, and control the environment of a site — a greenhouse, a field, a park, a building, anywhere devices are laid out in space. The AI acts in an advisory role — any action that moves equipment requires user approval before execution (edits that only change configuration are exempt; see Safety & Approval Model).

---

## Getting started: there are two switches { #enable-and-start }

Using the AI takes two switches in two different places. They are deliberately not one.

| Switch | Where | What it turns on |
|--------|-------|------------------|
| **Enable AI Service** | Settings > General | The AI menu appears in the navigation and the AI page becomes reachable. Chat and advice requests work. |
| **Run built-in AI** | AI > Connection > Built-in AI | Work that runs without anyone asking for it — periodic summaries, context broadcast, weather summary, MCP health checks, real-time alerts. |

The order is **enable in Settings → register a model (agent) on the AI > Connection page → start operation**.

**Connecting your own AI app** (Claude Desktop and the like) works independently of this switch. It only needs external MCP access allowed in Settings > General and a per-user access key — the built-in AI can stay off. The top of the AI > Connection page shows both and links to each screen.

That "external MCP access" toggle (**Settings > General > Enable External MCP Server**, `AIGlobalSettings.mcp_http_enabled`) is checked fresh on every HTTP request to the MCP server, not cached — turning it off returns `503` to every external MCP call immediately, with no restart needed, and turning it back on restores access just as fast.

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
                tool_execution.py — approval gate + audit log
                                     ↓
      Tool registry (tool_registry.py) — single source of tool
      declarations; its dispatch map resolves the call to a handler
                                     ↓
                        AoT system (Daemon / InfluxDB / SQLite)
```

Both paths execute through the same gate (`aot/tools/tool_execution.py`) and pull tool
definitions from the same registry (`aot/tools/tool_registry.py`), so neither their
approval rules nor their tool lists can ever diverge between the in-app assistant and an
external MCP client.

---

## MCP Tool List

Tools exposed by the external MCP server and the internal `mcp_aot` engine. Read tools and configuration-edit tools run immediately; control, scheduling and activation tools pass through an approval gate either way — the in-app assistant's chat approval card, or the external MCP server's approval queue (`pending_approval` + `respond_to_confirmation`, see "Running the MCP Server" below).

### Two layers: `tools/list` vs. drawers { #tool-drawers }

The catalog is not one flat list. Listing every tool up front costs roughly 20K tokens before the conversation even starts, so `tools/list` returns only two layers, and the rest is opened on demand:

- **Core — 27 tools, always listed.** The narrow set an agent needs to take its next step without guessing: name resolution (`resolve_target`), device lookup, reading a value, immediate control, the approval queue, and a handful more (`aot/tools/tool_registry.py`, the `_TIER_ASSIGNMENT` table).
- **4 meta tools, always listed alongside core:** `open_drawer` (lists a drawer's tools, or all drawers with no argument), `get_tool_detail` (one tool's full schema by name), `use_tool` (actually *calls* a drawer tool by name — the only way to execute one; `open_drawer`/`get_tool_detail` only return definitions), `respond_to_confirmation` (approve/reject a pending confirmation).
- **101 tools live in 8 drawers**, grouped by purpose, and only appear once `open_drawer` is called: `device` (device control/state), `measurement` (sensors, environment, weather, energy), `function` (functions/controllers/sequences), `schedule` (scheduling), `record` (notes/notices/knowledge/advice), `space` (map/zones/facilities/plots), `definition` (device-definition CRUD), `system` (AI settings, system status, diagnostics, screens).

Drawers are now optional. External MCP connections list the key's whole tool profile (next section) with no drawers — that is the default. Set `AOT_MCP_TOOL_TIERING=1` (or `true`/`yes`/`on`) to bring the drawer layout back; it then works inside the key's profile and `open_drawer`, `get_tool_detail` and `use_tool` are listed again. The in-app assistant's built-in tool list keeps the drawer layout (`AOT_AI_BUILTIN_MCP_TIERING`, on by default).

### Tool profiles per API key { #tool-profiles }

Each API key also chooses which tools an external AI app sees — its **tool profile**. This is separate from the key's permissions: permissions decide what the key may do, the profile decides what is listed.

- **Operations** (the default for new keys) — everyday work: reading devices, sensors, weather, schedules, notes and plots; controlling devices and functions; adjusting function options, sequence run times and existing sequence steps; scheduling; recording notes, notices, advice and plot-stage events.
- **Operations + configuration** — adds setup tools: device definitions, creating or deleting automations and sequence steps, creating or editing plots and programs, map placement, dashboards and tabs, AI settings, archive and library-source management. The tool list sent to the AI in every conversation becomes much longer, so choose it only for keys that do setup work.

Pick the profile when you issue a key under `Settings > Users` (API Key section, **AI Tools**), or change it later on the same screen without reissuing the key. Changing it takes the same permission as revoking a key (user editing) and is recorded in the audit log; issuing a new key additionally asks for a recent sign-in. A connected app may need to reconnect before it sees the new list. With drawers on, a drawer only holds tools from the key's profile.

If a key on the operations profile calls a setup tool anyway, the server refuses it (`call_state: refused`, `reason_code: tool_profile`) with a message that says who can switch it and where; nothing is queued for approval. `get_tool_detail` and `open_drawer` answer the same way for tools and drawers outside the profile instead of reporting them as unknown or empty. When the key's permissions would block the tool anyway (for example a write tool on a read-only key), the message does not suggest switching, since that would not help. Other refusals — advice-only mode, the key's role, approval — never suggest switching: advice-only mode is a server-wide setting that no profile changes. Pending approvals for tools outside the profile are listed without the tool name (a neutral label and the area instead); the key can reject them but not approve them. The server instructions and `get_system_brief` also tell the AI which profile it is on, so it can point the user to the switch instead of saying the system cannot do something.

- Keys issued before profiles existed are assigned once, on the first start after the upgrade: a key whose owner called a setup tool in the last 90 days gets operations + configuration, every other key gets operations. The audit log does not record which key made a call, so this is decided per person — all of one person's keys get the same profile. Adjust individual keys afterwards if needed.
- The in-app assistant is not limited by profiles, and neither is the built-in AI's own service-account key (in-app device control goes through it). The screen shows no profile selector for that account's keys.
- `knowledge_search` suggests saving findings with `knowledge_shelve` only on connections that can use it (the configuration profile, or the in-app assistant, with note-editing permission).
- `set_output_state` and `list_available_devices` are no longer listed for API keys — `operate_device`, `get_device_list` and `search_devices` do the same jobs.
- `AOT_MCP_TOOL_PROFILES=0` turns profiles off (every key sees the full list, as before). `AOT_MCP_DEFAULT_TOOL_PROFILE` sets the profile of a server that runs without authentication (default `operations`).

### Names, several targets and argument checks { #tool-arguments }

- **Names where an id used to be needed.** `get_output_state`, `get_device_measurements`, `get_sensor_detail` and `get_sensor_reading` take a device name; `get_zone_sensor_summary` and `list_plots` take a zone or site name; `get_plot` takes the name, crop or variety of a growing plot. An id still works and is checked first. A name shared by several things returns `needs_disambiguation` with candidates described by where they are, instead of a guess.
- **Several targets in one call** (up to 10): `device_ids` (`get_output_state`, `get_sensor_reading`), `loc_ids` (`get_sensor_detail`), `plot_ids` (`get_plot`), `target_names` (`search_notes`), `zone_ids` (`get_zone_sensor_summary`). The reply is `{count, results}` — one entry per target, shaped like a single call.
- **Argument checks come first.** Write tools check their arguments before any permission or approval step: missing arguments, argument names that look like a typo of a valid one, and for `modify_function_options` unknown option keys or invalid values come back as `reason_code: invalid_arguments` with the valid names — also in advice-only mode (`get_function_detail` lists a function's option keys, current values and ranges up front; a range such as `temperature` is not a key — its min/max keys are), and the reply says so when the key could not run the call anyway. Other unknown arguments are ignored and listed in `_ignored_arguments`.
- `get_sensor_reading` no longer lists every device id in its schema, so the tool list does not grow with the number of devices.
- `search_devices` marks devices that share a name (`same_name_count`, `where`, `same_name_groups`).
- `get_spatial_tree` without `depth` lists every site, zone and facility at every level and counts the devices in each; pass `depth` to list devices.
- Plot stages: a change that already happened is `confirm_plot_stage`; a boundary still ahead is `reschedule_plot_stage`. `confirm_plot_stage` needs a date (`started_on`) unless `get_plot` proposes that stage.
- Tool descriptions are short. How to read a particular result comes in the reply's `_reading` field, which the AI should follow.

The tables in this section describe tools regardless of which layer they're in — a **Drawer** column marks the ones that are *not* in `tools/list` and must be opened first. For the complete tool list, including every drawer-only tool with its full argument schema, see the AI Agent Guide (`docs/ai_guide.md`) — this page does not duplicate that reference.

### Observation (read — immediate)

| Tool | Description | Drawer |
|------|-------------|--------|
| `get_spatial_tree` | Every site, zone and facility with device counts (`depth` lists devices) | — (core) |
| `resolve_target` | Resolve a place/device name to its exact entity — check upfront whether it's a container (has children). When the name belongs to several different places or devices it picks none and lists the candidates with where each one is, plus a name that points at only that one when there is one — otherwise pass its `target_id` (`add_schedule`, `edit_schedule`, `create_note` accept one). Same-name shapes nested inside each other count as one place: the name means the outer one, and the inner one is listed as `also_inside` | — (core) |
| `get_device_list` | List of all registered devices (inputs/outputs/cameras) | — (core) |
| `search_devices` | Find devices by name or type keyword | — (core) |
| `get_sensor_detail` | Sensor time-series history (min/max/avg stats) | — (core) |
| `get_weather` | Current weather for a field/zone (temp, RH, wind, precip) | — (core) |
| `get_energy_report` | Energy usage report by period/zone | `measurement` |
| `get_cumulative_status` | EnvCoordinator DLI / GDD cumulative status | `measurement` |
| `search_notes` | Read notes/memos/work logs attached to a zone or device | — (core) |
| `get_note_attachment` | View a photo attached to a note as an actual image (one per call) | `record` |
| `list_notices` | Notice board post list | `record` |
| `get_system_update_status` | Installed version vs latest GitHub release | `system` |
| `list_available_devices` | Devices available for AI judgment (native bridge) | — (in-app only) |
| `get_sensor_reading` | Latest reading of one or more sensors, by id or name (native bridge) | — (core) |

### Record / Task

| Tool | Description | Approval | Drawer |
|------|-------------|----------|--------|
| `create_note` | Create an undated memo/note attached to an entity, saved immediately | Not required | — (core) |
| `add_schedule` | Register a human work task (weeding, inspection, cleaning) | Not required — `config_only`: it only creates a Draft scheduler job, it moves no equipment. A person still reviews it on the scheduler screen afterward, as a separate step. | — (core) |
| `add_schedule_batch` | Register schedules for multiple targets (e.g. per zone) in one call | Not required — same `config_only` reasoning as `add_schedule` | `schedule` |

### Control (user approval required)

| Tool | Description | Drawer |
|------|-------------|--------|
| `operate_device` | Immediate physical control of valves/pumps/lights | — (core) |
| `set_output_state` | Turn an output on/off (optional duration, native bridge) | `device` |
| `schedule_device_control` | Reserve a one-off device operation at a specific time | `schedule` |

> In the in-app assistant, the control tools above execute only after confirmation via the approval card. Calling directly through the external MCP server goes through the same kind of gate: the first call is not executed and comes back as `pending_approval` with a `confirmation_id`; the user must explicitly approve or reject that confirmation_id in chat (handled via `respond_to_confirmation`) or on the web review page, then the caller retries the same arguments plus `_confirmation_id` to actually execute it. See "Running the MCP Server" below for the full flow. `add_schedule`/`add_schedule_batch` are not in this gate — see the Record / Task table above.

### Sequences (configuration edits need no approval)

A [sequence](../Functions.md#trigger-sequence) runs several outputs in a set order — the usual shape for irrigation, where valves take turns and a pump spans the run. These tools read and shape one. All four tools on this page (the three below, plus `create_sequence_function`) live in the `function` drawer.

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

When a state-changing call did **not** take effect (any state other than
`executed`/`already_executed`, or an approval-time run that failed), the response
also carries `performed: false` and a short `_reading`: tell the user plainly that
nothing was applied — or, for `pending_approval`, that it is still waiting for a
person — and describe things by name, not by id. A few tools report "not done"
through their own `status` word rather than an error; for state-changing tools
these count as not applied too: `refused` (call state `refused`), and
`rejected`, `quota_exceeded`, `not_found`, `target_not_found`, `orphan_archive`,
`needs_disambiguation`, `ambiguous` and `unavailable` (call state `failed`).
The refusal rate in the call-quality metrics therefore counts only permission,
policy and human refusals.

Device commands (`operate_device`, `set_output_state`, `schedule_device_control`)
are the exception. If the command may already have reached the device — a
timeout, a communication error or a controller error after sending —
`performed` is `"unknown"` instead of `false`. A timeout only means the caller
stopped waiting, so check the current state (`get_output_state`, or
`search_schedule` for a schedule) before retrying, and do not tell the user it
was done or not done until that check confirms it. A failure that stopped before
anything was sent (unknown device, bad argument, refusal) is still
`performed: false`. The in-app assistant reads the same result the same way, and
the web approval screen shows "command sent, but whether it took effect is
unconfirmed — check the device state" instead of a plain failure.

Turning a function or input on or off saves the setting first and then tells
the running controller. If the controller does not confirm (it may be offline or
busy), the response keeps the saved values, its call state stays `executed`,
and `performed` is `"unknown"`: say the setting was saved but is not yet
confirmed live, not that it is now on or off. `get_active_functions_summary`
shows only the saved setting, so it cannot confirm this.

A `submit_advice` reply likewise says that only a suggestion was saved, not the
change that was asked for. When a name matches several places or devices, each
of those candidates has a `where` so they can be told apart without ids
(distance lookups list their candidates without one).

### Extended In-app Assistant Tools

Beyond the tools above, the in-app AI assistant (and, for the ones that are `core`, the external MCP server directly) uses additional tools for entity assembly, automation, and knowledge. Most state-changing tools require approval; the `config_only` ones noted below don't — see Safety & Approval Model.

- **Input/Output management**: `list_device_types`, `get_device_type_options`, `create_input`·`modify_input`·`delete_input`, `create_output`·`modify_output`·`delete_output`, `get_device_measurements`
- **Functions (automation)**: `get_function_list`, `get_function_detail`, `create_function`, `create_sequence_function` (`config_only`), `modify_function_options` (`config_only`; not for triggers — see Sequences above), `activate_function`·`deactivate_function`·`delete_function`, plus the sequence tools `configure_sequence_day`·`modify_sequence_step`·`modify_sequence_schedule` (all `config_only`)
- **Schedule ledger**: `search_schedule`, `edit_schedule`, `delete_schedule`
- **Map (GIS)**: `list_geo_maps`, `get_device_location`, `set_device_location`, `delete_geo_shape`, `list_unbound_slots` (which places have no device), `rebind_device` (move every map slot of one device onto another)
- **GIS inputs (map layers)**: `list_gis_inputs`, `create_gis_input` (`config_only` — always created deactivated), `modify_gis_input`·`delete_gis_input`·`activate_gis_input` (approval required) — manage map layer providers such as VWorld/Google/OpenWeather
- **Facility/equipment lookup**: `get_facility_capacity` (a facility's heating/cooling capacity, volume, ventilation, irrigation design summary), `get_map_equipment` (map-drawn equipment's irrigation design summary per site/zone, sprinkler vs. drip kept separate), `get_map_equipment_detail` (individual sprinkler positions/spacing/radius, per-pipe detail — only when the summary isn't enough)
- **Notice board**: `create_notice`·`modify_notice`·`delete_notice`
- **AI agent management**: `list_ai_agents` — this one is `core`, so it's already in `tools/list` for the external MCP server too, not just the in-app assistant; `list_ai_entries`, `create_ai_agent` (`config_only`), `modify_ai_agent`·`delete_ai_agent` (approval required)
- **Knowledge library**: `knowledge_search`, `knowledge_shelve`, `list_library_source_types`, `smartfarmkorea_lookup`, `configure_library_source`
- **Document storage tiers**: `get_storage_tier_status`, `search_archives`, `get_archived_document`, `archive_note`·`restore_note_from_archive`·`delete_archive`·`set_document_tier` — an optional cold archive for old notes. `archive_note` copies a note's content into compressed long-term storage and flags it tier 3; the original note is left untouched either way. `delete_archive` removes only that archived copy, never the note itself. There is no screen for this — it is AI-tool-only.
- **Diagnostics / misc**: `analyze_system_failure`, `get_local_time`, `get_tool_detail`, `read_manual`, `get_detailed_manifest`, `ask_user`

> The single source of truth for tools is `aot/tools/tool_registry.py`. When a tool is added or changed, that file — not this page — is authoritative. For the full tool list with arguments, including everything behind a drawer, see the AI Agent Guide (`docs/ai_guide.md`).

---

## Per-Device AI Inclusion Toggle { #device-ai-toggle }

Each device's settings modal under `Configure -> Inputs` / `Configure -> Outputs` has an **Include in AI Judgment** toggle.

- On (default): the input/output is visible to AI judgment and control tools (spatial tree, device lookup, sensor/control tools, etc.).
- Off: the device is excluded from those tools' queries and control targets. Use this to hide sensitive devices, or devices the AI should never touch, on a per-device basis.

New inputs and outputs are created with this enabled by default (`is_ai_enabled=True`).

---

## Safety & Approval Model

Non-mutating **read tools** run immediately. Writes split into two categories.

- **Approval required (mutation / physical control)**: device control (`operate_device`, `set_output_state`, `schedule_device_control`), create/edit/delete of inputs/outputs/functions/notices, `modify_gis_input`·`delete_gis_input`·`activate_gis_input`, `modify_ai_agent`·`delete_ai_agent`, map placement changes (`set_device_location`, `delete_geo_shape`), device replacement (`rebind_device`), `configure_library_source`, etc.
- **Config-only writes (approval exempt)**: `add_schedule`, `add_schedule_batch`, `create_gis_input`, `create_ai_agent`, `create_program`, `modify_program`, `create_sequence_function`, `modify_function_options`, `modify_sequence_schedule`, `modify_sequence_step`, `configure_sequence_day`. These save immediately, without approval, because they never move equipment by themselves: most of them (`create_gis_input`, `create_ai_agent`, the sequence tools, etc.) only ever produce something that is created **inactive**, with its own separate activation step that *is* still gated — `create_gis_input` saves at once but stays off until `activate_gis_input` (approval required), and a sequence's schedule can be edited freely but only takes effect on the ground once `activate_function` (approval required) runs it. `create_note` and `knowledge_shelve` are **record writes**: they also save without approval — they have no activation step and knowledge stays unconfirmed/non-authoritative until a person confirms it (see AI Knowledge below). They are still writes: they need the same settings-edit permission as the web notes page, are refused for read-only keys and in advice-only mode, and respect group scope. Approval-exempt is not permission-exempt: in the in-app assistant and over MCP alike, every write — config-only ones included — runs only if the person asking has the role for it (settings-edit permission for notes, knowledge and map edits — deleting a map shape or placing a device, as on the web map editor; plot-edit permission — the same one the web plot pages use — for plots, stage records, plot resources, crop programmes and plot journals; control permission for everything else; with the default roles, Monitor, Guest and Kiosk cannot) and only on targets inside that person's group scope, whether the target is given by id or by name. The group check is made on what the tool actually changes — the device, function, schedule or step it resolves to — not only on the arguments, so naming a target, giving a schedule or step id, or mentioning another group's resource in free text does not get around it. Approving a pending request needs the same permission as the request itself (plot-edit for plot requests, settings-edit for map edits, control for the rest), on both the web and `respond_to_confirmation`. If an approver is outside the target's group, the request is not run and goes back to the pending list for someone who may decide it. Scheduled jobs are checked again every time they fire, as the person responsible for them (whoever created the job, or whoever approved an AI-proposed one): if that person has since lost the permission or the group, the job does not run and is marked failed. Background AI jobs with no person behind them (periodic summaries and the like) are exempt.

Actions requiring approval are not applied immediately. In the **in-app assistant** they are presented in chat as an **approval card**, executed only once the user approves. Through the **external MCP server** they come back as a `pending_approval` response (a queued confirmation_id) and only proceed once the user explicitly approves or rejects that id — either path, nothing changes if the user rejects.

Approving on the web Requests screen (`AI → Requests`) **runs it there and then**. Previously approval only issued a permit: the person had to go back to the AI and tell it, and the AI had to call again — a round trip the AI could not close on its own, since a chat model only acts when spoken to. The server now executes using exactly the arguments stored with the confirmation, so what the approval screen showed and what runs cannot diverge. If the AI later calls again with the same confirmation_id it gets that stored result back instead of a second execution. Only irreversible physical control (valves, pumps) asks for one extra confirmation on the approval screen.

A **dashboard widget** (`aot/widgets/widget_mcp_review.py`, `js/common/aot-mcp-approval.js`) offers the same approval queue as a widget: approve/reject one at a time or several at once, or **edit then approve** — correct the stored arguments before running them. It asks for that same extra confirmation before any physical control.

---

## AI Records { #ai-records }

**AI → Records** (`/ai/manage`) looks back at what the AI did. It has four tabs: **Tool calls**, **Conversations**, **Error reports** and **Call quality**.

### Call quality { #call-quality }

The **Call quality** tab summarises how connected AIs have been using the tools. It is calculated from the same tool-call records as the Tool calls tab — nothing extra is stored, and nothing leaves this system.

Pick a period (24 hours, 7 days or 30 days) and, if you like, one connection type (MCP over HTTP, MCP on this computer, REST API, built-in AI). Each line shows one number:

- **Call bundles** — calls from one conversation with less than 90 seconds between them. The server cannot see where a question ends, so a bundle only approximates one question. Shown with calls per bundle (median and 90th percentile) and the share of bundles with 10 or more calls.
- **Same tool called again right away**, and the longest such run — a sign that a tool did not give the AI what it needed.
- **Bundles that start by looking up tools or targets**, and **tool lists opened and then used**.
- **Time between calls** (median, 90th percentile) — roughly how long the AI spends thinking between calls.
- **Lookup time** (median, 90th percentile) — only for read calls that ran.
- **Failed**, **refused** and **waiting for approval** calls, **empty results** (an estimate), **calls that asked which target was meant**, and **responses shortened to fit the size limit**. A call that answered "not found" or asked which target was meant is counted as an empty result or a question back, not as a failure, and its time counts as lookup time.

A table below breaks the same numbers down by tool drawer. Tool names are not shown on this screen.

Limits worth knowing:

- Changes the server carried out after a person approved them are not included.
- Response sizes leave out images.
- Calls recorded before this measurement was added are left out. The share of measured calls is shown so you can tell.

The same numbers, including a per-tool breakdown, are available from `GET /api/v1/mcp/quality?days=1|7|30&transport=` (requires the *view logs* permission). The response contains no user names, conversation keys or arguments.

Setting `AOT_MCP_QUALITY_LEDGER=0` stops filling in the measurement fields; the tool-call record itself is kept as before.

---

## AI Knowledge { #knowledge-library }

The `AI -> Knowledge` page (`/ai/library`) holds what grounds the AI's answers,
in two tabs. **Knowledge** lists every item the AI can cite; **Data sources**
lists where that knowledge comes in from — documents (PDF/text), web URLs, REST
APIs, internal queries and public-data feeds. The second column of a source row
is its sync status (synced, sync failed, not synced yet, or "Looked up on demand"
for sources queried live); hover it or open the source's settings for the last
sync time. Sync now lives in the settings window too.

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

When notes the AI wrote are waiting for a person, a one-line notice sits at the
top of the Knowledge tab; **Show them** filters the list to *Needs confirming*.
Click an item to open it, check the source link if it has one, then **Save and
confirm** (after correcting anything wrong) or **Retire**. Confirming is what
promotes a note out of "unconfirmed". A note with no source link shows no link —
there is no original to check it against.

**Knowledge settings → Cite confirmed knowledge only** (off by default) stops the
AI citing its own unconfirmed notes. Authoritative and hand-entered knowledge is
unaffected.

### Browsing and adding

The **Knowledge** tab lists one item per row (title, trust) and by default shows
only what people and the AI wrote. Data synced from sources is left out — every
synced chunk carries the source's name as its title, so mixed in they read as
the same line over and over; pick it in the source filter or manage it on the
Data sources tab. Tags are shown in the item's window. Search, filter by origin,
state or tag, and set aside anything
stale from the item's window (set-aside keeps the row; it only takes it out of
the AI's reach — show set-aside items with the state filter to put one back).

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

### Region-agnostic built-in sources { #global-sources }

Most built-in sources are Korean public data (RDA, Nongsaro, NCPMS,
SmartFarmKorea) and need an API key from that provider. Everywhere else, two
built-ins work out of the box — **no key, anywhere on Earth:**

| Source | What it answers |
|---|---|
| FAO ECOCROP (EXT-GL-01) | Growth temperature, rainfall, soil pH and altitude limits for 2,500+ species |
| Open-Meteo (EXT-GL-02) | Global forecast, soil temperature/moisture by depth, reference evapotranspiration (ET₀), past climate |

Open-Meteo fills a gap AoT's own weather tools cannot reach: `get_weather` reads
only the weather sensors wired into this install, and `get_weather_forecast` is
Korea-only (KMA). With no sensor, or outside Korea, this is the only weather
evidence available — and soil values and ET₀ come from here regardless of what
sensors you have.

Beyond those, the library is filled the other way: your own documents, web
pages, REST APIs — plus whatever the AI looks up and shelves as it works.

### Data credits { #data-credits }

Both global built-ins are **CC BY 4.0** data. That licence requires the credit
to appear where the data is shown, so AoT shows it in two places.

- **AI Knowledge page** — a "Data credits" line under the list on the Data
  sources tab, covering the sources you have enabled.
- **AI answers** — query responses carry the credit text, so the AI includes it
  when it quotes those values.

| Source | Licence | Credit |
|---|---|---|
| Open-Meteo | CC BY 4.0 (free tier is non-commercial) | Weather data by [Open-Meteo.com](https://open-meteo.com/) |
| FAO ECOCROP | CC BY 4.0 | FAO ECOCROP |

!!! warning "Commercial use"
    Open-Meteo's free endpoint is **limited to non-commercial use** by its terms
    (services with subscriptions or advertising, and integration into commercial
    products, count as commercial). Commercial growers and services should get an
    [Open-Meteo API key](https://open-meteo.com/en/pricing) and enter it in the
    source settings — with a key, AoT queries the commercial endpoint instead.

You can override the credit text in the source's settings (gear icon) under
**Attribution**. Left empty, the built-in default is used.

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
   `readonly` at issue time — write tool calls (notes and knowledge included) are then refused server-side,
   so a Custom GPT misconfiguration cannot touch a device by accident. If
   more than one person will use it, issue a separate key per person — the
   audit log then shows who called what, and a leaked key can be revoked
   without cutting off everyone else. Leave **AI Tools** on Operations
   unless this GPT will do setup work ([tool profiles](#tool-profiles)).
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
   Approve it on the **AI → Requests** screen (`/ai`), in the "Control requests
   awaiting approval" block at the top. Schedule proposals and advice from the
   AI are decided on the same screen.

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

> State-changing tool calls do not execute immediately here either (`aot/tools/mcp_safety_gate.py`). The first call comes back as `pending_approval` with a `confirmation_id`; the user must explicitly approve or reject it, in that same conversation or on the **AI → Requests** screen (`/ai`), which is handled through `respond_to_confirmation`. (`/api/v1/mcp/review_page` still exists as a bookmark-compatible redirect to `/ai`, but the audit log itself moved — it's now **AI → Records** (`/ai/manage`), under the Tool Calls tab, alongside Conversations, Error Reports and Call Quality.) Approving executes nothing by itself — retry the same call with `_confirmation_id` added afterward. The calling AI has no way to decide or fake this approval on its own. Set `AOT_MCP_WRITE_ENABLED=0` to refuse write tools outright, notes and knowledge included (advice-only mode; `submit_advice` still works). Two separate deadlines apply: 15 minutes by default for a human to approve (`AOT_MCP_CONFIRM_TTL_SEC`), then a fresh 5 minutes from the moment of approval to execute (`AOT_MCP_APPROVED_TTL_SEC`). It still exposes control tools, so connect this server only to trusted clients.

---

## Related Pages

- [Environmental Control Automation](env-control.md)
- [Scheduler](scheduler.md)
- Full AI Guide — `docs/ai_guide.md` in the repository (not part of this published manual): the complete tool list, including everything behind a drawer, with arguments
