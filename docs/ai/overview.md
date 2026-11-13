# AI Features Overview

AoT uses an MCP (Model Context Protocol) based AI agent to observe, diagnose, and control the environment of a site — a greenhouse, a field, a park, a building, anywhere devices are laid out in space. The AI acts in an advisory role — any action that moves equipment requires user approval before execution (edits that only change configuration are exempt; see Safety & Approval Model).

---

## Getting started: there are two switches { #enable-and-start }

Using the AI takes two switches in two different places. They are deliberately not one.

| Switch | Where | What it turns on |
|--------|-------|------------------|
| **Enable AI Service** | Manage > System Management > General Settings | The AI menu appears in the navigation and the AI page becomes reachable. |
| **Run built-in AI** | AI > Connection > Built-in AI | The built-in model itself: chat and advice requests, plus work that runs without anyone asking for it — periodic summaries, context broadcast, weather summary, MCP health checks, real-time alerts. |

The order is **enable in General Settings → register a model (agent) on the AI > Connection page → start operation**.

**Connecting your own AI app** (Claude Desktop and the like) works independently of this switch. It only needs external MCP access allowed in Manage > System Management > General Settings and a per-user access key — the built-in AI can stay off. The top of the AI > Connection page shows both and links to each screen.

That "external MCP access" toggle (**Manage > System Management > General Settings > Enable External MCP Server**, `AIGlobalSettings.mcp_http_enabled`) is checked fresh on every HTTP request to the MCP server, not cached — turning it off returns `503` to every external MCP call immediately, with no restart needed, and turning it back on restores access just as fast.

- **Operation cannot be started with no model registered.** Running background work with nothing to ask only piles up errors in the log every cycle. The switch is available only once at least one agent is activated.
- **Deactivating or deleting the last model stops operation too.** Re-activating a model later does not silently resume autonomous operation — start it again on the AI page.
- **With operation off, chat and advice requests are refused as well.** The switch means "the built-in model is running", so while it is off there is nothing to ask — the hint line on the AI page says so. One thing stays open: deciding advice that has already been submitted, including advice your own AI app sent over MCP, is still available on AI → Requests, so a pending decision never disappears just because the built-in model is stopped.

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

### One toolbox of 14, not one tool per feature { #tool-drawers }

By default an external connection's tool catalog is 14 tools, not a list that grows with every feature. Eight are read-only — `overview`, `measure`, `weather`, `find`, `detail`, `records`, `screen_view`, `help` — and six change something — `control`, `record`, `cultivate`, `configure`, `screen`, and `remove` (the one tool that deletes anything, so an app's "always allow" setting can apply to the rest without also covering deletes).

Each tool takes an `op` argument naming the specific operation (for example `measure` with `op: "latest"` for right-now values, or `op: "history"` for a period), plus a shared vocabulary of arguments used the same way across every operation: `target`, `period`, `at`, `measurement`, `value`, `query`, `limit`, `fields`, and a few more. A tool's description lists its operations with a one-line "when to use" for each, so the AI picks an operation the way it would otherwise pick a whole tool — there is no separate "open this first" step before an operation can be used.

For one operation's full arguments, defaults and examples, the AI calls `help` with `target` set to `"<tool>.<op>"` — for example `help(target: "weather.local_time")` for the local time of a place in another timezone. Calling `help` with no argument lists every operation available to the connection.

What a key can reach still follows its tool profile and setup modules (next section): an operation only appears once the work behind it is in the key's profile, so `configure` and `cultivate` list setup operations only on a key with the matching module turned on; asking for one that is off is answered the same way as any other request outside the profile.

**Earlier surface.** Before this, the catalog listed one named tool per feature, split into a small always-listed core set plus tools kept in subject drawers — device, measurement, function, schedule, record, space, definition, system — that had to be opened with a separate call before they could be used. Set `AOT_MCP_SURFACE=legacy` on the MCP container (and any app process with the assistant built in) to bring that surface back; `AOT_MCP_TOOL_TIERING=1` then splits it into core + drawers again, while leaving it unset keeps the flat list. The in-app assistant is not affected by this switch: it always uses the domain tools described above.

### Tool profiles per API key { #tool-profiles }

Each API key also chooses which operations an external AI app can reach — its **tool profile**. This is separate from the key's permissions: permissions decide what the key may do, the profile decides what is offered.

A profile is **operations** (always on) plus any **setup modules** you tick. Each module adds one kind of setup work; ticking one widens the operations offered under `configure`, `cultivate` and the other tools, so tick only what the key is for.

- **Operations** (always on; the only thing a new key gets by default) — everyday work: reading devices, sensors, weather, schedules, notes and plots; finding an address, a distance or the nearest place; controlling devices and functions; adjusting function options, sequence run times and existing sequence steps; scheduling; and recording, editing or deleting notes, notices, advice and plot-stage events.

| Module | Adds |
|---|---|
| `plots` — Plots and crop programs | creating, editing, copying and splitting plots, their stage templates and guidance, crop programs |
| `map` — Map and locations | device placement, pipe diameters, removing map shapes |
| `automation` — Building automations | creating or deleting functions and sequences, a sequence's whole day plan |
| `devices` — Device definitions | device types and options, creating/editing/deleting inputs, outputs and GIS inputs, rebinding a slot |
| `dashboard` — Dashboards | dashboards, widgets and tabs |
| `library` — Documents and library | archived documents, saving findings to the knowledge library, library sources |
| `admin` — System and AI settings | system update and storage-tier status, AI agents |

A key on operations alone sees a tool list of about 9,000 tokens; ticking every module (**configuration**) raises that to about 15,000.

**Lite** reaches the same operations as operations — the tool list no longer shrinks any further, since it is already the fixed set of 14 tools above. What lite still limits is the size of each *reply*: about 6,000 tokens against a higher cap otherwise, because a reply stays in the conversation and is sent again with every later message. A longer reply is shortened to the first items with a note to narrow the question. Because replies accumulate, lite is still the choice for a free AI plan with a tight daily budget. Setup modules cannot be added to lite.

**Changing the profile later.** Three ways, none of which needs a new key: on the key's row under `Manage > System Management > Users` (above); under `Settings > General > AI Tool List`, where each user sees their own keys and switches between lite, operations and configuration; or by asking the AI, which runs `configure` with `op: "tool_profile_set"` for the key of the connection it is using (it always needs human approval, and it cannot change another key). For a remote MCP connection you can also add `?tools=lite` to the connection address (`AOT_MCP_TOOLS=lite` for stdio): it narrows that connection to lite without changing the key — it never widens. The new list and reply cap apply after the app reconnects.

Ticking every module is the same as the earlier **Operations + configuration** profile and is stored that way (`configuration`), so such a key also gets any module added later. Keys that were on operations + configuration before modules existed keep exactly the list they had; operations keys keep operations. Nothing is converted.

Pick the modules when you issue a key under `Manage > System Management > Users` (API Key section, **AI Tools**) — or tick **Lite (small tool list)** there instead to issue the key straight into the lite profile, which turns off the module checkboxes. Change a key's profile later on the same screen (tick the boxes on the key's row, or that row's own Lite checkbox, then **Change**) without reissuing the key. Changing them takes the same permission as revoking a key (user editing) and is recorded in the audit log with the profile and module list before and after; issuing a new key additionally asks for a recent sign-in. A connected app may need to reconnect before it sees the new list.

If a key asks for an operation whose module is off, the server refuses it (`call_state: refused`, `reason_code: tool_profile`, `tool_module: <module>`) with a message that names the module and says who can turn it on and where; nothing is queued for approval. `help` answers the same way for an operation outside the profile instead of reporting it as unknown. When the key's permissions would block the operation anyway (for example a write operation on a read-only key), the message does not suggest switching, since that would not help. Other refusals — advice-only mode, the key's role, approval — never suggest switching: advice-only mode is a server-wide setting that no profile changes. Pending approvals for operations outside the profile are listed without naming the underlying feature (a neutral label and the area instead); the key can reject them but not approve them. The server instructions and `overview`'s `op: "brief"` tell the AI which modules are on and, one line each, what every module that is off would add — so it can tell the user which module to ask for instead of saying the system cannot do something.

- Keys issued before profiles existed are assigned once, on the first start after the upgrade: a key whose owner called a setup operation in the last 90 days gets operations + configuration (every module), every other key gets operations. The audit log does not record which key made a call, so this is decided per person — all of one person's keys get the same profile. Narrow individual keys to the modules they need afterwards.
- The in-app assistant is not limited by profiles, and neither is the built-in AI's own service-account key (in-app device control goes through it). The screen shows no module selector for that account's keys.
- Connections signed in through [central authentication](#central-auth) — apps that cannot hold a key, such as claude.ai connectors — keep their profile on the **linked account** instead. Pick it in the "Signed-in AI apps" row of `Settings > General > AI Tool List`, or by asking the AI (`configure` with `op: "tool_profile_set"`). If none is picked, it works as before: the `aot.config` scope gives every module, without it the connection gets operations. A picked profile never goes beyond the token's scopes — lite is always lite, while operations (+ modules) and configuration need `aot.config`.
- `records`'s `op: "knowledge_search"` suggests saving findings with `record`'s `op: "knowledge_shelve"` only on connections that can use it (the `library` module, or the in-app assistant, with note-editing permission).
- `AOT_MCP_TOOL_PROFILES=0` turns profiles off (every key sees every operation, as before). `AOT_MCP_DEFAULT_TOOL_PROFILE` sets the profile of a server that runs without authentication (default `operations`; `configuration` or a value such as `operations+plots+map` also work).

On the [earlier surface](#tool-drawers) (`AOT_MCP_SURFACE=legacy`), profiles still shape a flat list of named tools, and lite keeps its own short list (`get_place_overview`, `get_sensor_reading`, `list_plots`, `get_control_state`, `get_weather`, `operate_device`, `respond_to_confirmation`, `get_screen`) plus `read_tool`, `use_tool` and `get_tool_detail` to reach the rest.

### Names, several targets and argument checks { #tool-arguments }

- **Names where an id used to be needed.** `get_output_state`, `get_device_measurements`, `get_sensor_detail` and `get_sensor_reading` take a device name; `get_zone_sensor_summary` and `list_plots` take a zone or site name; `get_plot` takes the name, crop or variety of a growing plot. An id still works and is checked first. A name shared by several things returns `needs_disambiguation` with candidates described by where they are, instead of a guess. A device argument also takes a `search_devices` reply as it is; if that reply holds several devices none is picked and the candidates come back. When the argument takes one kind of device, another kind is refused with a line saying which kind it actually is.
- **A map is not a place.** A zone or site argument (`zone_id`, `zone_ids`, `loc_id`, `scope_id`) does not take the id of a map. The reply names the map that id belongs to and lists the sites on it (`sites_on_this_map`), instead of quietly answering for one of the shapes drawn there. A device name in an argument that only takes places (`zone_id`, `zone_ids`, `scope_id`) is refused as not being a place (`loc_id` reads a device name as that device first), and the name of a growing plot is read as the zone it sits in.
- **A place is not a plot.** A plot argument (`plot_id`, `plot_ids`) does not take a site, zone or facility. The reply says which of those the name or id belongs to and points at `list_plots` for the plots inside it, along with the names of the growing plots (`growing_plots`) — instead of only reporting that no plot has that name.
- **Several targets in one call** (up to 10): `device_ids` (`get_output_state`, `get_sensor_reading`), `loc_ids` (`get_sensor_detail`), `plot_ids` (`get_plot`), `target_names` (`search_notes`), `zone_ids` (`get_zone_sensor_summary`). The reply is `{count, results}` — one entry per target, naming the target it answers (`requested`) and shaped like a single call. A list given in the single-target argument (`device_id`, `plot_id`, …) is read the same way, repeats are dropped, and more than ten comes back asking you to split the call.
- **Argument checks come first.** Write tools check their arguments before any permission or approval step: missing arguments, argument names that look like a typo of a valid one, and for `modify_function_options` unknown option keys or invalid values come back as `reason_code: invalid_arguments` with the valid names — also in advice-only mode (`get_function_detail` lists a function's option keys, current values and ranges up front; a range such as `temperature` is not a key — its min/max keys are), and the reply says so when the key could not run the call anyway. Other unknown arguments are ignored and listed in `_ignored_arguments`. A read tool does not ignore a **target argument** it does not take (`target_name`, `zone_id`, `place`, `device_id`, …) — dropping it would answer for the whole farm as if for that target — so it runs nothing and returns `unknown_scope_argument` with the arguments it does accept.
- When a call is rejected for its arguments, the reply also carries that tool's detailed `schema` and a `hint` (nested item shapes, decision rules, a worked recipe). `get_tool_detail` returns the same fuller description for one tool. The tool list itself stays light and does not carry them.
- Large results come in a summary form to keep replies small: `list_plots` and `get_crop_status` return the first 10 (marked `truncated`), `get_control_state` leaves out screen-only diagnostics (pass `detail=true` to get them back), and `get_plot` leaves out the stage table's guidance and targets. What was left out is listed in `_omitted`.
- `get_sensor_reading` no longer lists every device id in its schema, so the tool list does not grow with the number of devices.
- `search_devices` marks devices that share a name (`same_name_count`, `where`, `same_name_groups`).
- `get_spatial_tree` without `depth` lists every site, zone and facility at every level and counts the devices in each; pass `depth` to list devices.
- Plot stages: a change that already happened is `confirm_plot_stage`; a boundary still ahead is `reschedule_plot_stage`. `confirm_plot_stage` needs a date (`started_on`) unless `get_plot` proposes that stage. On MCP the six stage tools (confirm, reschedule, undo, and — with the plots module — guidance, add, remove) are listed as one tool, `plot_stage`, whose `operation` is the tool name; each key sees only the operations it can use. Approval and the audit log name the operation's tool. Likewise `schedule_add` carries `add_schedule` and `add_schedule_batch`, and `notice` carries the three notice writes. When a key can use only one of a group's operations, that tool is listed under its own name. `AOT_MCP_FACADES=0` lists them separately again.
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

### Sequences (configuration edits need no approval) { #sequences-configuration-edits-need-no-approval }

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

A sequence can be named instead of given by id: the id is matched first, then the name. Function names are not unique, so when a name matches more than one function nothing is changed — the reply says the name is ambiguous and lists the candidates, each with its type, whether it is active and which tab it is on (at most ten, along with the total). Repeat the call with the id of the one you meant.

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
| `queued` | Sent to the user's screen, which has not confirmed running it yet (screen changes only) | Say it was sent, not done; check the screen before sending it again |
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
A read lookup that replies by asking which one you meant is `executed`, not
`failed`: the lookup ran and the candidate list is its answer. Only
state-changing tools read that reply as nothing done.
The refusal rate in the call-quality metrics therefore counts only permission,
policy and human refusals.

`screen_action`, which changes the screen the user is looking at without saving
anything, counts as a read for permissions but is reported the same way. A screen
whose device has AI screen control turned on (the gear in the AI bar at the bottom of the screen → AI settings) and was active in the last 30
minutes needs no agreement and runs at once. For any other screen, while it
waits for the user to agree to the screen it found (`needs_confirmation`) the call
state is `pending_approval`, and if nobody answers in time (`expired`) it is
`failed` — so a screen change is never reported as done before it happened. When
it was sent but the screen has not confirmed it yet (`sent`, `queued`) the call
state is `queued`, and when the user declines it (`rejected`) it is
`approval_rejected`. If the screen did something other than asked — for example it
highlighted the whole map because the item has no pin — the status is `partial`
with what was done in `done`; arguments the action does not use are listed under
`ignored` instead of being dropped silently.

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
- **Document storage tiers**: `get_storage_tier_status` reports how many documents sit in each tier. The cold-archive tools (archive, restore, search, delete) were removed on 2026-11-04; the storage service itself remains.
- **Diagnostics / misc**: `analyze_system_failure`, `get_local_time`, `get_tool_detail`, `read_manual`, `get_detailed_manifest`, `ask_user`

> The single source of truth for tools is `aot/tools/tool_registry.py`. When a tool is added or changed, that file — not this page — is authoritative. For the full tool list with arguments, including everything behind a drawer, see the AI Agent Guide (`docs/ai_guide.md`).

---

## Per-Device AI Inclusion Toggle { #device-ai-toggle }

Each device's settings modal under `Configure -> Inputs` / `Configure -> Outputs` has an **Include in AI Judgment** toggle.

- On (default): the input/output is visible to AI judgment and control tools (spatial tree, device lookup, sensor/control tools, etc.).
- Off: the device is excluded from those tools' queries and control targets. Use this to hide sensitive devices, or devices the AI should never touch, on a per-device basis.

New inputs and outputs are created with this enabled by default (`is_ai_enabled=True`).

---

## Safety & Approval Model { #safety-approval-model }

Non-mutating **read tools** run immediately. Writes split into two categories.

- **Approval required (mutation / physical control)**: device control (`operate_device`, `set_output_state`, `schedule_device_control`), create/edit/delete of inputs/outputs/functions/notices, `modify_gis_input`·`delete_gis_input`·`activate_gis_input`, `modify_ai_agent`·`delete_ai_agent`, map placement changes (`set_device_location`, `delete_geo_shape`), permanently deleting a note (`delete_note`), device replacement (`rebind_device`), `configure_library_source`, etc.
- **Config-only writes (approval exempt)**: `add_schedule`, `add_schedule_batch`, `create_gis_input`, `create_ai_agent`, `create_program`, `modify_program`, `create_sequence_function`, `modify_function_options`, `modify_sequence_schedule`, `modify_sequence_step`, `configure_sequence_day`. These save immediately, without approval, because they never move equipment by themselves: most of them (`create_gis_input`, `create_ai_agent`, the sequence tools, etc.) only ever produce something that is created **inactive**, with its own separate activation step that *is* still gated — `create_gis_input` saves at once but stays off until `activate_gis_input` (approval required), and a sequence's schedule can be edited freely but only takes effect on the ground once `activate_function` (approval required) runs it. `create_note`, `modify_note` and `knowledge_shelve` are **record writes**: they also save without approval — they have no activation step and knowledge stays unconfirmed/non-authoritative until a person confirms it (see AI Knowledge below). `modify_note` is the one record write whose approval is decided per call: it edits a note's title, body or tags and archives or restores it; it never permanently deletes a note itself, and it saves at once only when the note is the caller's own, or an author-less note the AI wrote at a user's request — someone else's note, or one whose author cannot be told, goes to the approval queue like any mutating call. Permanently deleting a note — the AI-side equivalent of the web notes page's delete — is instead a separate tool, `delete_note`: unlike the three record writes above, it always goes to the approval queue, needs the same settings-edit permission as map edits rather than the record-write exemption, and its approval card reads back the note's title, where it is attached, its first line and how many attachments go with it, since the deletion cannot be undone. Either way the values from before an edit are kept in the audit log, so an edit can be undone by hand. They are still writes: they need the same settings-edit permission as the web notes page, are refused for read-only keys and in advice-only mode, and respect group scope. Approval-exempt is not permission-exempt: in the in-app assistant and over MCP alike, every write — config-only ones included — runs only if the person asking has the role for it (settings-edit permission for notes, knowledge, notices and the knowledge-source settings (`configure_library_source`), and map edits — deleting a map shape or placing a device, as on the web map editor; plot-edit permission — the same one the web plot pages use — for plots, stage records, plot resources, crop programmes and plot journals; control permission for everything else, except changing a connection's own tool profile (`set_tool_profile`), which needs no specific role — just a signed-in key that is not read-only; with the default roles, Monitor, Guest and Kiosk cannot) and only on targets inside that person's group scope, whether the target is given by id or by name. The group check is made on what the tool actually changes — the device, function, schedule or step it resolves to — not only on the arguments, so naming a target, giving a schedule or step id, or mentioning another group's resource in free text does not get around it. Approving a pending request needs the same permission as the request itself (plot-edit for plot requests, settings-edit for map edits, control for the rest), on both the web and `respond_to_confirmation`. If an approver is outside the target's group, the request is not run and goes back to the pending list for someone who may decide it. Scheduled jobs are checked again every time they fire, as the person responsible for them (whoever created the job, or whoever approved an AI-proposed one): if that person has since lost the permission or the group, the job does not run and is marked failed. Background AI jobs with no person behind them (periodic summaries and the like) are exempt.

Actions requiring approval are not applied immediately. In the **in-app assistant** they are presented in chat as an **approval card**, executed only once the user approves. Through the **external MCP server** they come back as a `pending_approval` response (a queued confirmation_id) carrying a plain-language read-back of what the system resolved the request to — the target by name and the action — for the assistant to relay to the user before asking them to confirm; a yes to that specific read-back is what counts as approval, not the original request by itself, so a misidentified device or place gets caught before anything runs. If the AI sends the same request again (same tool, same arguments) while the earlier one is still waiting, no second request is queued: the existing confirmation_id comes back marked as already asked, so the user is not asked twice. Either path, nothing changes if the user rejects.

Approving in the **Approvals window** — opened by the **[Approvals N]** chip in the AI bar at the bottom of every screen — **runs it there and then**. The same window also asks about screen changes the AI wants to make (a screen action is allowed or declined there), so every decision waits in one place. Previously approval only issued a permit: the person had to go back to the AI and tell it, and the AI had to call again — a round trip the AI could not close on its own, since a chat model only acts when spoken to. The server now executes using exactly the arguments stored with the confirmation, so what the approval screen showed and what runs cannot diverge. If the AI later calls again with the same confirmation_id it gets that stored result back instead of a second execution. Each approval runs at most once: approving a request that was already decided or is already running is refused, two approvals at the same moment run it once, and a request interrupted while running is left as running rather than sent again — check the device before asking for it again. Only irreversible physical control (valves, pumps) asks for one extra confirmation on the approval screen.

The Approvals window lets you approve or reject one at a time or several at once, or **edit then approve** — correct the stored arguments before running them. It asks for that same extra confirmation, inside the item, before any physical control. The **AI → Requests** screen and the **dashboard widget** (`aot/widgets/widget_mcp_review.py`) show only the number waiting and a **View** button that opens the same window; the decisions themselves are not made there.

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

### Where knowledge comes from { #where-knowledge-comes-from }

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
disclosure even if the model forgets to. When the note was copied out of a
source registered in the library, the citation names that source too — still
unconfirmed, but there is somewhere to go and check it.

### Reviewing what the AI wrote { #reviewing-what-the-ai-wrote }

When notes the AI wrote are waiting for a person, a one-line notice sits at the
top of the Knowledge tab; **Show them** filters the list to *Needs confirming*.
Click an item to open it, check the source link if it has one, then **Save and
confirm** (after correcting anything wrong) or **Retire**. Confirming is what
promotes a note out of "unconfirmed". A note with no source link shows no link —
there is no original to check it against. Retiring is not final: a retired note
still appears in the list under **Include set-aside items**, and **Reactivate**
puts it back as *Needs confirming* — un-retiring is not the same as having
reviewed it.

**Knowledge settings → Cite confirmed knowledge only** (off by default) stops the
AI citing its own unconfirmed notes. Authoritative and hand-entered knowledge is
unaffected.

### Browsing and adding { #browsing-and-adding }

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

### Knowledge Digest Pipeline { #knowledge-digest-pipeline }

Long prose sources such as documents and web URLs are pre-processed **once**, at
registration time:

1. The source is split into **chunks**.
2. Each chunk is **digested (LLM summarize + keyword extraction)** and cached in the `ai_knowledge_chunk` table.
3. At query time there is **no LLM call** — retrieval is pure DB lookup + deterministic search, so answers are fast and cheap.

### Scoping is by tag, not by site { #scoping-is-by-tag-not-by-site }

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

Open-Meteo is also what the forecast tool runs on. `get_weather` reads only the
weather sensors wired into this install and only answers for now;
`get_weather_forecast` asks Open-Meteo for the place you name — anywhere, up to
14 days out, hour by hour for the first day, every three hours out to 72 hours,
and by day beyond that. It needs this source switched on, or an Open-Meteo
forecast input that has coordinates; with neither, the forecast tool answers that
there is no forecast source and points you to Settings > Inputs to add one. The
numbers are model values at the nearest grid point, not measurements at your
site, and the answer says which point replied and how far away it is. If
Open-Meteo cannot be reached, a forecast up to six hours old is reused and the
answer says how old it is. Soil values and ET₀ come from here regardless of what
sensors you have.

Two limits the source screen states as well. Open-Meteo's key-free endpoint is
for non-commercial use under its own terms — for commercial use, get an
Open-Meteo key and enter it on the source, and queries go to the commercial
endpoint instead; the key field is optional and exists only for that. And
ECOCROP's numbers are suitability ranges answering "can this species grow in
this climate", not setpoints to control to. Both ask for attribution (CC BY 4.0),
which the source carries by default.

Beyond those, the library is filled the other way: your own documents, web
pages, REST APIs — plus whatever the AI looks up and shelves as it works.

### Data credits { #data-credits }

Both global built-ins are **CC BY 4.0** data. That licence requires the credit
to appear where the data is shown, so AoT shows it in two places.

- **AI Knowledge page** — a "Data credits" line under the list on the Data
  sources tab, covering the sources you have enabled.
- **AI answers** — query responses carry the credit text, but it is tagged as
  already shown on screen, so the AI does not repeat, quote or read it in its
  answers.

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

## AI Cards { #ai-cards }

An **AI card** is a short message that a connected AI (an MCP client such as your own AI app) puts on the AoT screen a person is looking at. It appears on the AoT screen itself, separate from the chat window. The AI uses it when it has finished looking something up and the result is worth keeping. A card never moves a device or changes a setting. Cards belong to the account that owns them and are shown only on screens signed in with that account.

### Where cards appear { #ai-card-where }

- **Caption** — a new card pops up as a caption near the bottom of the screen. Only one is shown at a time, and a newer card replaces it. It goes away when you press the close button (×), when the next card arrives, or after 60 seconds; an unread card stays in the inbox either way. While the pointer is over it, the keyboard focus is inside it, or you are pressing it, it stays; cards that arrive meanwhile are held and only the newest one is shown afterwards. Long cards expand with **More** / **Less**. While the tab is hidden, or the viewer or inbox is open, no caption is shown and the card just goes to the inbox.
- **AI dock** — a small bar just below the caption, centred, showing the AI connection, the unread count, the screen-following mode (auto, ask, off) and a switch to turn it off. Pressing it opens the **inbox** upward in the same place. On a phone only the icon and count are shown; following and turning off move to the inbox header.
- **Inbox** — the list of received cards (see "Inbox" below).

While the AI runs a slow lookup, a short-lived "looking up" caption may appear for a moment. It is not kept in the inbox.

### What the AI puts on a card { #ai-card-content }

The **card operation** of the MCP `screen` tool creates a card. A card has a title (up to 80 characters), a body (up to 2000 characters, Markdown) and attachments. If the title is left out, the first line of the body is used.

- For a weather or place-summary answer, the server posts that result as a card by itself; the connected AI does not need to repeat it. For any other key result worth keeping (recommendation, comparison, plan, report, image, link list), the AI is told to post it once, as **a one-line conclusion, at most 5 lines, links as `[text](url)`, and images or files as attachments**. Plain chat answers and intermediate steps are not posted as cards.
- If the same title and body arrive again within 2 minutes, no new card is stacked (unless the card has attachments).
- The body is drawn with Markdown formatting: headings, lists, checkboxes, quotes, rules and tables. In a caption a table is a one-line summary; expanded, in the inbox or in the viewer you see the whole table.
- Each person can receive up to 6 cards a minute and 100 cards in 24 hours.
- With **AI result cards** under **Settings > General** on (the default), connected AIs receive the rule above as part of their instructions. A box with the same rule text lets you copy it for an AI that ignores server instructions. Turning it off simply stops sending that guidance.
- With **Hide AI messages** under **Settings > General** on, captions are not shown and cards only collect in the inbox.

### Attachments: images, files and video links { #ai-card-attachments }

A card can carry up to **8 attachments** (files, video links and value tiles together). Files on one card total at most 20 MiB and a single file at most 5 MiB. The AI can send the file contents directly or give a public https address; for an address, the AoT server downloads and stores the file.

| Kind | Formats | How it is shown |
|------|---------|-----------------|
| Image | png, jpg, jpeg, gif, webp | Thumbnail tile; opens enlarged in the viewer |
| File | pdf, csv, txt, md, json | Name plus a line with type and size. Text files get a preview in the viewer; `.md` switches between formatted and source view |
| Result page | html | Shown only inside an isolated frame, without scripts or outside connections, with a reminder not to enter passwords |
| Value tile | viz (gauge / mini-chart) | Drawn directly in the card, not a tile or a file — a gauge for one value against its range, a mini-chart for a short series |
| Video / web link | YouTube, Vimeo, direct mp4/webm addresses, ordinary web pages | Cover-image tile and a title link |

- Markdown images (`![](https://…)`) and ordinary links written in the body are also fetched by the server and turned into thumbnail tiles (up to 4 body images, 3 web-page links and 4 video tiles per card). An address that became a tile is hidden from the body text in captions, viewer and inbox. If the server cannot fetch it, it stays as a plain link.
- The server fetches only public https addresses (private-network and internal addresses are refused), at most 30 times an hour and 100 times a day per user.
- **Video** — in the viewer it appears as a 16:9 box (a 9:16 box for a YouTube Shorts link) with a title link. For YouTube the in-viewer player (`youtube-nocookie.com`) is created only after you press **Play here**; nothing is requested from the outside before that, and a notice says YouTube can see this device's IP address once you play. Direct mp4/webm addresses show **Play here** in the same way when they can be played in the viewer. Other videos (Vimeo and so on) and web pages open in a new tab through **Play on original site** or **Open original page**. The server itself fetches only the cover image (poster).
- With more than one attachment the tile row scrolls sideways and shows **+N** when it overflows. In the viewer, the ◀ ▶ buttons, the left/right arrow keys or a touch swipe move to the previous or next attachment, with a counter.
- **Value tiles** — to show queried numbers as a picture instead of text, attach a file named `something.viz` whose text is a small JSON spec. A gauge is `{"viz":"gauge","label":…,"value":…,"valueText":…,"unit":…,"min":…,"max":…,"okMin":…,"okMax":…}` (the ok range is optional); a mini-chart is `{"viz":"spark","label":…,"valueText":…,"unit":…,"span":…,"points":[oldest…newest]}` with at most 48 points. `valueText` shows a short text instead of the raw number (for a formatted or rounded reading). A mini-chart also prints the observed low–high range of its points under the line, and the optional `span` is a short time-window label shown beside it (e.g. `"last 6 h"`); a gauge prints its `min` and `max` at the foot of the arc — so the range is read from the picture without a separate line of text. Only finite numbers and short text are accepted, and each tile is drawn directly in the card and the inbox, separate from the tile row above and not part of the viewer's attachment list — a changing reading then reads at a glance rather than as a row of figures. A value tile still counts as one of the card's 8 attachments, but not against the daily file limit.
- **The server draws value tiles for you on a value query.** When an external connection reads current device values (`measure` `op: "latest"` on a device) or a short history (`measure` `op: "history"`), the server composes gauge/mini-chart tiles from that result and posts the card itself, the same way it posts weather and place-summary cards — so the connected AI does not attach its own `.viz` for those answers and does not repeat the card in chat; it just replies in words. The response carries a `card` field saying it was posted (or why it was skipped — screen off, auto-cards off, a measurement with no known scale, nothing to show). Attach a `.viz` yourself only for numbers that did not come from such a query. **Never build your own HTML or SVG gauge/chart to show a reading or a trend** — read it with `measure` (`latest` for a current value, `history` for a short series) and let the server draw the tile; a hand-built chart card is slower, looks inconsistent, and duplicates what the server already posts.
- Each user is limited to 20 files a day and 100 MiB of stored files in total.

### Inbox { #ai-card-inbox }

Press the AI dock to open it (the Inbox entry in the AI menu also works). New cards are marked **New**; cards you have read are marked read, and **Mark all read** does it in one go. **Show older** loads earlier cards.

- **Search** — finds AI messages by title and body.
- **Pin** — a pinned card is exempt from automatic clean-up. Up to 30 cards per person can be pinned, and **Pinned only** narrows the list. After you unpin a card it is kept for at least 7 more days.
- **Dismiss card** — a dismissed card disappears from the inbox.
- **Save to notes** — saves the card's contents as an AoT note (you need permission to create notes).
- **Post as notice** — for an HTML result card, posts it as a notice from the viewer after a confirmation step. Everyone on the farm sees it; you can choose whether to post the attachment too, and you need permission to write notices. It runs only when a person presses it; the AI cannot post a notice for you.

Cards are kept for 30 days from creation (pinned cards excepted), and beyond the latest 300 per user the oldest are cleaned up first. To see how an external AI can read the same cards, see the read-only resources under "Running the MCP Server" below.

### Colours { #ai-card-colors }

The surface and text colours of captions, inbox and viewer are set in **Custom UI** under **AI Card Surface** and **AI Card Text**. The surface is drawn at 0.8 opacity so the screen shows through, and the text is always opaque, so keep the two colours clearly different.

---

## Running the MCP Server { #running-the-mcp-server }

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

A standard client needs only the URL and an API key — no relay script. Clients that sign in through an OAuth authorization server (such as claude.ai connectors) can use [central authentication](#central-auth) or the [built-in authorization server](#embedded-auth) instead.

```bash
claude mcp add --transport http aot https://<host>/aotmcp/mcp \
  --header "X-API-KEY: <base64 api key>"
```

`GET /mcp` returns 405: this server offers no server-to-client SSE stream. It runs
waitress with four threads, so one held connection would starve tool calls. The
spec allows this, and it is where server-initiated notifications would go later.

The REST API stays because ChatGPT Custom GPTs on ordinary plans cannot register
an MCP server — they attach through OpenAPI Actions only.

Alongside tools, both transports also offer read-only **resources**: the AI messages posted to a person's screen (`resources/list` and `resources/read`; there are no resource templates). A client sees only the messages of the account its key or token identifies, and only ones that are still open (not closed or expired). A message arrives as markdown, an attached file as a resource of its own, and an HTML artifact as plain text so the client does not render it; both carry a line stating the text is stored inbox data rather than instructions. A listing returns only the latest 20 (older ones can still be read by their URI), reading is limited to 30 times a minute and 16 MiB of data a minute per person, and a long text file stops at 20,000 characters with a note of how many are left. Clients that negotiate protocol version 2025-06-18 or later (2024-11-05 and 2025-03-26 are accepted too) additionally get links to the message, and to its file, in the reply when the AI posts one.

An HTTP request body over 8 MiB is refused with an error. The case that gets close is an AI attaching a file to a screen message, and a single file may be at most 5 MiB anyway.

### Central authentication (OAuth access tokens) { #central-auth }

Besides API keys, the HTTP server can also accept access tokens issued by an OAuth authorization server — for example AoT Central Authentication, where one staff account signs in once and connects to many AoT sites. AoT is then a **resource server**: sign-in, consent and token issuing happen at the authorization server, and AoT only checks each token's signature, issuer, audience (`aud`), expiry and the revocation list. API keys keep working either way.

Nothing is tied to a particular network or domain. Set it up under `Settings > General > AI Service > MCP Authentication > Configure`:

| Field | What to enter |
|---|---|
| OAuth Authentication | Turn on to accept access tokens as well as API keys |
| Token Issuer | *Central* (this section) or [*This AoT (built in)*](#embedded-auth) |
| Authorization Server | Central only: the issuer address (https). This server fetches the signing keys from it, so it must be reachable from here |
| Public MCP Address | The address AI clients connect to, for example `https://farm.example.com/mcp`. Tokens must name exactly this address. Route `/mcp` and `/.well-known/oauth-protected-resource` at that address to the MCP server (port 5700) |
| Public Web Address | The address people open AoT at. Account linking returns here (shared with the Google integration) |
| Client ID / Client Secret | Issued by the authorization server when this site is registered; used only for account linking |

The dialog lists what to register at the authorization server — the resource (the public MCP address), the redirect URI and the scopes — and **Check** confirms that the authorization server and its signing keys can be reached before you save. The environment variables `AOT_MCP_CENTRAL`, `AOT_MCP_AUTH_MODE`, `AOT_MCP_CENTRAL_ISSUER`, `AOT_MCP_PUBLIC_URL`, `AOT_MCP_LINK_CLIENT_ID` and `AOT_MCP_LINK_CLIENT_SECRET` override the screen for fleets that share one deployment template.

A token's subject is an account at the authorization server, not an AoT user, so each person links once: sign in to AoT as yourself, open the same dialog and press **Link My Account**. Linking is refused if your account's role is not allowed to use AI connections; ask an administrator. Until then the AI can connect, but every tool call answers with a message explaining how to link. Accounts are never matched by e-mail. Once linked, the same dialog names the linked account and offers **Unlink My Account**; after unlinking, AI connections signed in with that account can no longer act here.

What a token may do is its scopes narrowed by the linked user's role: `aot.read` (required) reads, `aot.control` operates devices, `aot.config` changes settings and shows every setup module (the configuration tool profile). A profile picked for the linked account — in the "Signed-in AI apps" row of `Settings > General > AI Tool List`, or by asking the AI — takes precedence, as far as the token's scopes allow. State-changing calls still go through the same approval as API keys.

### Built-in authorization server (this AoT issues the tokens) { #embedded-auth }

Central authentication needs a separate authorization server and a staff account there. Customers who just want to connect their own AoT to a claude.ai connector can let **this AoT be the authorization server** instead. Pick **This AoT (built in)** under `Token Issuer` in the same dialog. People sign in with their ordinary AoT login (TOTP included), approve the connection on a consent screen that names this AoT, and the token's subject is that AoT user — there is no account-linking step. Only one of central and built-in can be on at a time; switching makes the other mode's tokens invalid.

**Before you turn it on**

- The connector runs in the AI company's cloud, so AoT needs a **public https address that the internet can reach**. That exposes the AoT sign-in page and `/mcp` to everyone. Use strong passwords and turn on two-factor authentication (TOTP) for every account that can control devices.
- On a **private network or VPN** the AI service cannot reach AoT. Use an [API key](#tool-profiles) there; it works everywhere.
- Web and MCP must share one origin. Route that address like this:

| Path | Goes to |
|---|---|
| `/mcp`, `/.well-known/oauth-protected-resource` | MCP server (port 5700) |
| everything else — including `/authorize`, `/token`, `/register`, `/revoke`, `/.well-known/oauth-authorization-server`, `/.well-known/jwks.json` | web server (port 8084) |

With Docker you do not need to split it: the web container passes these two paths to the MCP container itself, so point the whole address at port 8084. A native install's nginx does the same.

**Setup:** choose *This AoT (built in)*, enter the **Public MCP Address** (for example `https://farm.example.com/mcp`; the issuer is that address without the path), turn on **OAuth Authentication**, save, then press **Check**. In claude.ai add a custom connector with that MCP address — nothing else to enter. The first time you save, AoT creates a signing key.

**What it does**

- Only the redirect addresses listed in the dialog can register: claude.ai and claude.com connectors, plus `http://localhost` / `http://127.0.0.1` for tools on a person's own computer such as Claude Code. The administrator can replace the list with the environment variable `AOT_MCP_REDIRECT_ALLOWLIST` (comma-separated).
- The consent screen shows this AoT's name (the *Brand Text* in the custom UI settings, otherwise the address) in large letters, who is signed in and the three scopes. Scopes the user's role cannot use are greyed out. The app's own name is whatever it called itself — it is not verified. If the signed-in account's role is not allowed to use AI connections, no consent screen appears: the person only sees a message to ask an administrator, and no token is issued.
- Access tokens last one hour; the refresh token lasts 30 days and is replaced every time it is used. If an already-used refresh token or authorization code shows up again, the whole connection is closed.
- A connection is closed when the user changes their password, is disabled or deleted, presses **Disconnect** under *My Connected AI Apps* in the dialog, or the app revokes it.
- Sign-in attempts are limited by the same lockout as the web login; `/register` is limited to 30 per hour and the rest of these paths to 600 per hour per address.
- The signing key is a file (`mcp_oauth_es256.pem`, mode 600) in the AoT data folder (`databases/`) of each installation — not in the database, logs or backups. If the folder is restored without it, a new key is made and every AI app has to be authorized again.

What a token may do is the same as in central authentication: its scopes narrowed by the user's role. The environment variable `AOT_MCP_AUTH_MODE` (`central` or `embedded`) overrides the screen.

### Connecting a ChatGPT Custom GPT { #chatgpt-setup }

Register the three REST paths above (`/mcp/info`, `/mcp/tools/list`,
`/mcp/tools/call`) as an **OpenAPI Action**. Creating a Custom GPT with
Actions requires a paid ChatGPT plan (Plus/Team/Enterprise/Pro) — free
accounts cannot use this path at all.

1. **Issue an API key** — under `Manage > System Management > Users`, generate a new API key for
   your account (name it something like "ChatGPT" so you can revoke just this
   connection later). If this GPT should only ever read, pick scope
   `readonly` at issue time — write tool calls (notes and knowledge included) are then refused server-side,
   so a Custom GPT misconfiguration cannot touch a device by accident. If
   more than one person will use it, issue a separate key per person — the
   audit log then shows who called what, and a leaked key can be revoked
   without cutting off everyone else. Leave **AI Tools** on Operations
   alone unless this GPT will do setup work, and then tick only the modules
   it needs ([tool profiles](#tool-profiles)).
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
   screen. Approving there usually runs the request right away; only if the
   approval reply still says it hasn't run yet does the same call need
   retrying with `_confirmation_id` added to actually execute it. There is no
   automatic re-approval inside a Custom GPT. Approve it on the **AI →
   Requests** screen (`/ai`), in the "Control requests awaiting approval"
   block at the top. Schedule proposals and advice from the AI are decided on
   the same screen.

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
      "args": ["/opt/AoT/aot/aot_mcp_server.py"],
      "env": { "AOT_MCP_API_KEY": "<base64 api key>" }
    }
  }
}
```

stdio requires an API key by default too. Put a key issued under `Manage > System Management > Users` in `AOT_MCP_API_KEY` under `env` — without it the connection is refused with an authentication error right after it starts (`AOT_MCP_REQUIRE_AUTH=0` turns authentication off).

> State-changing tool calls do not execute immediately here either (`aot/tools/mcp_safety_gate.py`). The first call comes back as `pending_approval` with a `confirmation_id`; the user must explicitly approve or reject it, in that same conversation or on the **AI → Requests** screen (`/ai`), which is handled through `respond_to_confirmation`. (`/api/v1/mcp/review_page` still exists as a bookmark-compatible redirect to `/ai`, but the audit log itself moved — it's now **AI → Records** (`/ai/manage`), under the Tool Calls tab, alongside Conversations, Error Reports and Call Quality.) Approving through `respond_to_confirmation` runs the request in that same call — report its result and don't call the tool again; only if that reply says it hasn't run yet, retry the same call with `_confirmation_id` added. The calling AI has no way to decide or fake this approval on its own. Set `AOT_MCP_WRITE_ENABLED=0` to refuse write tools outright, notes and knowledge included (advice-only mode; `submit_advice` still works). Two separate deadlines apply: 15 minutes by default for a human to approve (`AOT_MCP_CONFIRM_TTL_SEC`), then a fresh 5 minutes from the moment of approval to execute (`AOT_MCP_APPROVED_TTL_SEC`). It still exposes control tools, so connect this server only to trusted clients.

---

## Related Pages

- [Environmental Control Automation](env-control.md)
- [Scheduler](scheduler.md)
- Full AI Guide — `docs/ai_guide.md` in the repository (not part of this published manual): the complete tool list, including everything behind a drawer, with arguments
