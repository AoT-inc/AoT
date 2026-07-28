# coding=utf-8
"""
Single source of truth (SSOT) for AI virtual tools — architecture-improvement Phase 1.

Before this file, one tool had to be hand-synced across FIVE places:
  1. `tool_map`               (virtual_tool_resolver.py)  — name → handler dispatch
  2. `VIRTUAL_TOOL_REGISTRY`  (ai_action_service.py)      — known-name validation gate
  3. `system_tools` manifest  (ai_action_service.get_action_manifest) — LLM-facing schema
  4. `_VIRTUAL_APPROVAL_TOOLS`(ai_dispatch_service.py)    — mutation → approval (dispatch)
  5. `_APPROVAL_REQUIRED_TOOLS`(ai_planning_service.py)   — mutation → approval (planner)

They had drifted: `get_weather` / `get_cumulative_status` were dispatchable in (1) but
absent from (2), so `resolve_action` raised InvalidToolError for them; the two approval
lists (4)/(5) were maintained separately and differed only by the physical/schedule
tools. This module declares each tool ONCE and DERIVES all five, so a new tool is a
single record and the sets can never silently diverge again.

Each derivation is value-preserving vs the pre-refactor hand-maintained sets — verified
1:1 by aot/tests/ai_eval/test_tool_registry_ssot.py — with ONE intended fix: the derived
VIRTUAL_TOOL_REGISTRY now includes `get_weather` and `get_cumulative_status` (they have
real handlers and were only ever missing by omission).

Scope: this SSOT covers the *virtual* tools (action_type='virtual_tool_call') plus the
registry-only validation names that are dispatched elsewhere (native bridge / legacy
execute_action chain / special action types like read_manual). Tools whose `handler` is
None are known-but-not-VirtualToolResolver-dispatched — they stay out of `tool_map`.
"""
import copy
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass(frozen=True)
class Tool:
    """One AI tool, declared once. Derivations read these fields — see module docstring.

    name       : the tool_name the LLM emits / the resolver dispatches on.
    handler    : AoTDataToolService staticmethod name for VirtualToolResolver dispatch,
                 or None if the tool is known for validation but dispatched elsewhere
                 (native bridge, legacy action_type chain, special action types).
    action_type: dispatch discriminant. Almost always 'virtual_tool_call'; a few special
                 tools (read_manual, get_detailed_manifest) are their own action_type.
    registry   : member of VIRTUAL_TOOL_REGISTRY (the resolve_action known-name gate).
    mutating   : a state-changing entity/function mutation → always needs human approval.
    physical   : a physical-control / scheduling tool → needs approval in the planner
                 path (the dispatch path gates these separately via the P4 hard gate).
    manifest   : the VERBATIM manifest dict emitted into get_action_manifest()'s
                 system_tools list, or None to omit the tool from the LLM manifest.
                 Stored verbatim so the derived manifest is byte-identical to the
                 original hand-written entries.
    """
    name: str
    handler: Optional[str] = None
    action_type: str = 'virtual_tool_call'
    registry: bool = True
    mutating: bool = False
    physical: bool = False
    manifest: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Tool declarations.
#
# ORDER MATTERS for one reason only: the derived system_tools manifest is emitted
# in this list's order, and it is kept identical to the original hand-written order
# so the LLM-facing prompt is unchanged. The manifest-bearing tools therefore come
# first, in their original sequence; dispatch-only and validation-only tools follow
# (tool_map is a dict and the approval sets are frozensets — order-independent).
# ---------------------------------------------------------------------------
TOOLS: List[Tool] = [
    # --- special action-type tools (manifest entries, not virtual_tool_call) -----
    Tool('read_manual', handler=None, action_type='read_manual', manifest={
        "action_type": "read_manual",
        "description": "Reads a specific section from the AoT system manuals. Requires 'target_id' (filename from manual_index) and Optional 'params.section' (heading name).",
        "usage_hint": "Use this when you need detailed technical specs for a specific sensor, output, or API endpoint.",
    }),
    Tool('get_detailed_manifest', handler=None, action_type='get_detailed_manifest', manifest={
        "action_type": "get_detailed_manifest",
        "target_id": "input | output | function | gis_input | mcp_<id>",
        "description": "Retrieves the full, non-slimmed registry of available components or MCP tools.",
        "usage_hint": "Use this if the current context says 'Use get_detailed_manifest for full list'.",
    }),

    # --- @ANCHOR: AGENT_LOOP_ASK_USER (Phase 1, docs/design/ai-agent-loop.md) ----
    # A first-class tool, not a fallback. Call this whenever you are not
    # confident what the user wants, which entity/zone/device they mean, or
    # whether a destructive action is what they intended — instead of
    # guessing, inventing data, or answering an unrelated question. This ends
    # the turn with your question shown to the user; their next message
    # continues the SAME request with your question as context. Handled
    # directly by the agent loop (not dispatched via virtual_tool_call).
    Tool('ask_user', handler=None, action_type='ask_user', registry=True, manifest={
        "tool_name": "ask_user",
        "action_type": "ask_user",
        "description": "Ask the user a clarifying question instead of guessing or fabricating an answer. Use whenever the request is ambiguous (which zone/device, what exactly to do) or you're not confident. This is not a failure fallback — it is the correct move whenever you are unsure.",
        "usage_hint": "params.arguments: {question: '<the question, in the user's language>', options: ['<choice1>', '<choice2>', ...] (optional — offer options when there is a short list of likely answers, e.g. candidate zone names; omit for a free-text question)}",
    }),

    # --- physical / scheduling tools ---------------------------------------------
    Tool('add_schedule', handler='add_schedule_tool', physical=True, manifest={
        "action_type": "add_schedule",
        "description": "Register a human work schedule or memo. Use for manual tasks such as weeding, inspection, or cleaning.",
        # Corrected 2026-07-08: add_schedule_tool proposes a SchedulerJobMeta
        # job (source_type='human'), NOT a Notes row — verified against the
        # actual implementation. Use create_note for a plain memo/journal entry.
        "usage_hint": "For a DATED work task/event (weeding, spraying, harvest, inspection) use this — it registers a human work item. Params: {date, content, worker, time, tags, target_name}. PASS target_name (a zone/facility/device name like '온실', '3-1', '1포장 1-1') whenever the user names a place, so the schedule links to that real location (map + location search). If the name is ambiguous/not found the tool returns available_targets — call ask_user to pick, then retry. Omit target_name only for a farm-wide event with no specific place. This is a GIS-based system: target_name resolves to exactly ONE entity and never auto-expands to its children. Before writing, if the request could apply per sub-unit ('각 구역별', 'each zone') call resolve_target(target_name) first — read-only, no approval — to see whether the name is a container with 'children'; if so, use add_schedule_batch to write all of them in one approval instead of one add_schedule call per child. For an undated memo/note, use create_note instead.",
    }),
    Tool('add_schedule_batch', handler='add_schedule_batch_tool', physical=True, manifest={
        "action_type": "add_schedule_batch",
        "description": "Register MULTIPLE per-entity work schedules in ONE call, behind a SINGLE approval — use instead of N separate add_schedule calls whenever a request applies per sub-unit ('각 구역별로', 'each zone'). Each add_schedule call needs its own approval AND consumes its own rate-limited request slot; a 9-entity request as 9 separate add_schedule calls can burn through the hourly limit before finishing.",
        "usage_hint": "params.arguments: {date, entries: [{target_name, time, content?, worker?}, ...], content?, worker?, tags?, window_start?, window_end?, duration_minutes?}. Call resolve_target on the container name FIRST to get the exact child names for `entries`. `content`/`worker` are shared defaults for entries that omit their own. Give BOTH window_start and window_end to get a server-side capacity check (entries.length * duration_minutes vs. available minutes) — if it doesn't fit, the call is rejected up front with the exact numbers instead of you having to compute it; the request then needs more than one date, so split entries across multiple calls (one per date) or ask the user how to compress/parallelize. Duplicate target_name within one batch is rejected.",
    }),
    Tool('schedule_device_control', handler='schedule_device_control_tool', physical=True, manifest={
        "action_type": "schedule_device_control",
        "description": "Reserve a ONE-OFF device operation (valve/pump/sprinkler) at a single specific future time — e.g. 'open valve 1 for 30 min this Saturday 15:00'. Requires approval. This is ONLY for irregular, one-time reservations; recurring or condition-based control belongs to a Function (create_function), NOT here.",
        "usage_hint": (
            "params: {device_id, scheduled_time (ISO8601) OR delay_seconds, state, duration_minutes}. "
            "DECISION RULE — the scheduler holds one-off events; regular automation belongs to Functions:\n"
            "- RECURRING ('every day 6am', '매일/매주 관수') → use create_function "
            "(trigger_timer_daily_time_point / trigger_timer_daily_time_span / trigger_timer_duration) INSTEAD, NOT this.\n"
            "- CONDITIONAL ('when humidity < 40%', '습도 낮으면 가동') → use create_function "
            "(conditional_conditional) INSTEAD.\n"
            "- IMMEDIATE ('run for 5 min now', '지금 1분간') → use operate_device, NOT this.\n"
            "- Only a single specific future time with NO repetition and NO condition belongs here.\n"
            "If you cannot tell whether the user wants a one-time reservation or a repeating/conditional "
            "automation, call ask_user to confirm BEFORE choosing."
        ),
    }),

    # --- Schedule CRUD (@ANCHOR: SCHEDULE_CRUD_TOOLS) ----------------------------
    # Completes the scheduler as a farm-operations ledger: add_schedule (create)
    # already existed; search/edit/delete close the CRUD loop so the AI can act on
    # a user's "reschedule the spraying" / "cancel Saturday's inspection". All read
    # from / write to SchedulerJobMeta (the ledger of record — A안). edit/delete are
    # `mutating` → the SSOT routes them through the human approval gate in EVERY
    # path (dispatch, planner, agent-loop) automatically; search is read-only.
    Tool('search_schedule', handler='search_schedule_tool', manifest={
        "tool_name": "search_schedule",
        "action_type": "virtual_tool_call",
        "description": "Lists farm schedules/events (work tasks, inspections, harvests, one-off device reservations) from the scheduler ledger. Read-only. Use this to answer 'what's coming up?' and to obtain the job_id needed before edit_schedule / delete_schedule (search→act, like search_notes).",
        "usage_hint": "params.arguments: {query (optional keyword over content/reasoning), target_name (optional — only schedules attached to a location/device), include_past (optional bool, default false = upcoming only), include_archived (optional bool, default false), limit (optional, default 20)}. Returns each schedule's job_id, when, content, kind, state, and editable/deletable flags.",
    }),
    Tool('edit_schedule', handler='edit_schedule_tool', mutating=True, manifest={
        "tool_name": "edit_schedule",
        "action_type": "virtual_tool_call",
        "description": "Edits an existing schedule's time, duration, content, or worker. Requires human approval. If the schedule is an already-registered device reservation, its trigger is rescheduled too. First call search_schedule to get the job_id.",
        "usage_hint": "params.arguments: {job_id (required — from search_schedule), date (optional YYYY-MM-DD, keeps existing date if omitted), time (optional HH:MM, keeps existing time if omitted), duration_minutes (optional — new duration in minutes, replaces the existing one), content (optional new text), worker (optional new assignee), target_name (optional — re-link to a different zone/facility/device by name; ambiguous name returns available_targets → ask_user then retry)}.",
    }),
    Tool('delete_schedule', handler='delete_schedule_tool', mutating=True, manifest={
        "tool_name": "delete_schedule",
        "action_type": "virtual_tool_call",
        "description": "Cancels/deletes a schedule. Requires human approval. Soft-deletes (archived, reversible) and removes any registered device trigger so it no longer fires. First call search_schedule to get the job_id.",
        "usage_hint": "params.arguments: {job_id (required — from search_schedule), reason (optional cancellation reason)}.",
    }),

    # --- virtual_tool_call tools WITH a manifest entry (original order) -----------
    Tool('search_devices', handler='search_devices', manifest={
        "tool_name": "search_devices",
        "action_type": "virtual_tool_call",
        "description": "Search for Input/Output/Camera/Zone/complex-Device entries by name or type keyword. A complex device (e.g. a PLC) is one physical unit whose readings/controls are split across separate Input and Output entries — results of type 'device' list its member_ids, and any input/output result belonging to one carries parent_device_id + parent_device_name. When a result has a parent device, prefer answering/acting at that device level rather than treating the input/output as standalone.",
        "usage_hint": "Call with params.arguments.query='<keyword>'. Returns list of matching devices with their unique_ids.",
    }),
    Tool('get_device_measurements', handler='get_device_measurements', manifest={
        "tool_name": "get_device_measurements",
        "action_type": "virtual_tool_call",
        "description": "Returns all measurement channels (measurement_id, channel, measurement, unit) for a given device_id.",
        "usage_hint": "Call with params.arguments.device_id='<id>'. Use to resolve measurement IDs for create_function params.",
    }),
    Tool('create_function', handler='create_function_tool', mutating=True, manifest={
        "tool_name": "create_function",
        "action_type": "virtual_tool_call",
        "description": "Creates a new automation function/controller. Requires human approval. This — NOT schedule_device_control — is the right home for RECURRING device control (daily/weekly watering → trigger_timer_daily_time_point / trigger_timer_daily_time_span / trigger_timer_duration) and CONDITION-BASED control (when humidity < X → conditional_conditional). function_type MUST be one of: conditional_conditional, pid_pid, trigger_edge, trigger_output, trigger_output_pwm, trigger_run_pwm_method, trigger_sequence, trigger_sunrise_sunset, trigger_timer_daily_time_point, trigger_timer_daily_time_span, trigger_timer_duration, function_actions. For SEQUENTIAL control of several devices (e.g. a valve sequence), use 'trigger_sequence'.",
        "usage_hint": "params.arguments accepts ONLY {function_type, name, params}. Do NOT pass 'devices' or any other top-level key — there is no device-list parameter. The function is created first; its device steps/order are configured afterward. params is a dict of custom_option overrides (e.g. select_measurement fields as 'device_id,meas_id').",
    }),
    Tool('modify_function_options', handler='modify_function_options', mutating=True, manifest={
        "tool_name": "modify_function_options",
        "action_type": "virtual_tool_call",
        "description": "Updates custom_options of an existing function and reloads it in the daemon. Requires human approval.",
        "usage_hint": "params.arguments: {function_id, params: {<option_id>: <value>}}",
    }),
    Tool('create_sequence_function', handler='create_sequence_function', mutating=True, manifest={
        "tool_name": "create_sequence_function",
        "action_type": "virtual_tool_call",
        "description": "Creates a trigger_sequence AND fills its steps — one ordered output action per device — so it is configured, not empty. Use for 'valve sequence' / sequential device control. Requires human approval.",
        "usage_hint": "params.arguments: {name, device_ids: ['<output_id>', ...] (ordered), state: 'on'|'off', step_duration (sec, optional), pause_seconds (optional)}",
    }),
    Tool('delete_function', handler='delete_function', mutating=True, manifest={
        "tool_name": "delete_function",
        "action_type": "virtual_tool_call",
        "description": "Deletes a function/controller by unique_id. Requires human approval.",
        "usage_hint": "params.arguments: {function_id: '<unique_id>'}",
    }),
    Tool('list_device_types', handler='list_device_types', manifest={
        "tool_name": "list_device_types",
        "action_type": "virtual_tool_call",
        "description": "Lists the valid TYPES available for creating an Input/Output/Function. Read-only. ALWAYS call this before create_input/create_output/create_function so the type is real — never invent a type.",
        "usage_hint": "params.arguments: {kind: 'input'|'output'|'function'}. Returns {types:[{type, name}]}.",
    }),
    # @ANCHOR: AGENT_LOOP_GET_TOOL_DETAIL (Phase 1) — the catalog every tool is
    # listed in shows only a name + one-line description to keep prompts lean.
    # Call this for the full argument schema of a specific tool before calling
    # it, if the one-line description isn't enough to know what to pass.
    Tool('get_tool_detail', handler='get_tool_detail_tool', manifest={
        "tool_name": "get_tool_detail",
        "action_type": "virtual_tool_call",
        "description": "Returns the full description and argument schema for ONE tool by name. Read-only. Use when the catalog's one-line summary isn't enough to know what arguments a tool needs.",
        "usage_hint": "params.arguments: {tool_name: '<name from the catalog>'}",
    }),
    Tool('get_device_type_options', handler='get_device_type_options', manifest={
        "tool_name": "get_device_type_options",
        "action_type": "virtual_tool_call",
        "description": "Returns the configurable option schema (id/type/name/default) for a given device type. Read-only. Use to learn which option ids to pass to modify_input/modify_output.",
        "usage_hint": "params.arguments: {kind: 'input'|'output'|'function', device_type: '<type>'}",
    }),
    Tool('create_input', handler='create_input', mutating=True, manifest={
        "tool_name": "create_input",
        "action_type": "virtual_tool_call",
        "description": "Creates a new Input (sensor / data source). Requires human approval. Create-then-configure: this makes the device with its type; fill options afterward with modify_input.",
        "usage_hint": "params.arguments: {input_type (from list_device_types kind=input), name, interface (optional), params (optional dict of option overrides)}. Do NOT invent other top-level keys.",
    }),
    Tool('modify_input', handler='modify_input', mutating=True, manifest={
        "tool_name": "modify_input",
        "action_type": "virtual_tool_call",
        "description": "Updates an Input's name and/or options and reloads it. Requires human approval.",
        "usage_hint": "params.arguments: {input_id, name (optional), params: {<option_id>: <value>}}",
    }),
    Tool('delete_input', handler='delete_input', mutating=True, manifest={
        "tool_name": "delete_input",
        "action_type": "virtual_tool_call",
        "description": "Deletes an Input by unique_id. Requires human approval.",
        "usage_hint": "params.arguments: {input_id: '<unique_id>'}",
    }),
    Tool('create_output', handler='create_output', mutating=True, manifest={
        "tool_name": "create_output",
        "action_type": "virtual_tool_call",
        "description": "Creates a new Output (actuator / relay / valve). Requires human approval. Create-then-configure: makes the device with its type; fill options afterward with modify_output.",
        "usage_hint": "params.arguments: {output_type (from list_device_types kind=output), name, interface (optional), params (optional dict)}. Do NOT invent other top-level keys.",
    }),
    Tool('modify_output', handler='modify_output', mutating=True, manifest={
        "tool_name": "modify_output",
        "action_type": "virtual_tool_call",
        "description": "Updates an Output's name and/or options and reloads it. Requires human approval.",
        "usage_hint": "params.arguments: {output_id, name (optional), params: {<option_id>: <value>}}",
    }),
    Tool('delete_output', handler='delete_output', mutating=True, manifest={
        "tool_name": "delete_output",
        "action_type": "virtual_tool_call",
        "description": "Deletes an Output by unique_id. Requires human approval.",
        "usage_hint": "params.arguments: {output_id: '<unique_id>'}",
    }),
    Tool('list_geo_maps', handler='list_geo_maps', manifest={
        "tool_name": "list_geo_maps",
        "action_type": "virtual_tool_call",
        "description": "Lists available maps (map_id, name, center). Read-only.",
        "usage_hint": "params.arguments: {}",
    }),
    # --- GIS Input CRUD (@ANCHOR: GIS_INPUT_CRUD_TOOLS, 2026-07-26) ---------------
    # GIS layers (VWorld/Google/OpenWeather/OSM/... providers overlaid on the map)
    # are GeoLayer rows, but their TYPE registry is the same parse_input_information()
    # as regular sensor Inputs — list_device_types(kind='input')/
    # get_device_type_options(kind='input', ...) already cover 'gis_*' types, so no
    # separate type-lookup tools are added here, just the CRUD that was missing.
    Tool('list_gis_inputs', handler='list_gis_inputs', manifest={
        "tool_name": "list_gis_inputs",
        "action_type": "virtual_tool_call",
        "description": "Lists registered GIS Inputs (map layers/providers — VWorld, Google, OpenWeather, etc). Read-only.",
        "usage_hint": "params.arguments: {}",
    }),
    Tool('create_gis_input', handler='create_gis_input', mutating=True, manifest={
        "tool_name": "create_gis_input",
        "action_type": "virtual_tool_call",
        "description": "Creates a new GIS Input (map layer/provider, e.g. gis_vworld, gis_openweather). layer_type must be a 'gis_*' entry from list_device_types(kind='input'). Always created DEACTIVATED — call activate_gis_input once configured. Requires human approval.",
        "usage_hint": "params.arguments: {layer_type (a 'gis_*' type from list_device_types(kind='input')), name (optional), params (optional dict, e.g. {'api_key': '...'})}",
    }),
    Tool('modify_gis_input', handler='modify_gis_input', mutating=True, manifest={
        "tool_name": "modify_gis_input",
        "action_type": "virtual_tool_call",
        "description": "Updates a GIS Input's name and/or options (e.g. api_key). Requires human approval.",
        "usage_hint": "params.arguments: {layer_id, name (optional), params: {<option_id>: <value>}}",
    }),
    Tool('activate_gis_input', handler='activate_gis_input', mutating=True, manifest={
        "tool_name": "activate_gis_input",
        "action_type": "virtual_tool_call",
        "description": "Activates or deactivates a GIS Input. New GIS Inputs are created deactivated. Requires human approval.",
        "usage_hint": "params.arguments: {layer_id, active (bool, default true)}",
    }),
    Tool('delete_gis_input', handler='delete_gis_input', mutating=True, manifest={
        "tool_name": "delete_gis_input",
        "action_type": "virtual_tool_call",
        "description": "Deletes a GIS Input by unique_id. Requires human approval.",
        "usage_hint": "params.arguments: {layer_id}",
    }),
    # --- Facility performance/capacity (@ANCHOR: FACILITY_CAPACITY_TOOL, 2026-07-22)
    # geo/design computes engineering capacity for each facility (heating/cooling
    # kW, volume/area, ventilation) plus an irrigation BOM (pipe/emitter/flow) via
    # facility_calc.compute_capacity, surfaced through get_facility_integration.
    # None of it reached the AI before this — neither context nor a tool exposed
    # it, so "is the cooling enough / 관수 유량은?" was unanswerable. Read-only;
    # values are on-demand reference estimates (±5-10%), not persisted nameplates.
    Tool('get_facility_capacity', handler='get_facility_capacity_tool', manifest={
        "tool_name": "get_facility_capacity",
        "action_type": "virtual_tool_call",
        "description": "Returns the performance/capacity data geo/design computes for a facility (greenhouse/structure) drawn on the map: reference heating/cooling capacity (kW), floor/volume/glazing area, ventilation (ACH, vent-opening m²), an irrigation summary (pipe/emitter counts, flow L/min), and how many control devices are bound. Read-only — on-demand engineering reference estimates (±5-10%). Use for sizing / what-if questions ('is cooling enough?', '관수 유량은?', '난방 용량').",
        "usage_hint": "params.arguments: {facility_name (optional — a facility name like '육묘장'; omit to return ALL facilities)}. Returns per-facility capacity{heating_kw,cooling_kw,volume_m3,floor_m2,glazing_m2,ach_total,vent_open_m2}, irrigation{total_length_m,emitters,flow_lpm,layers[]}, bound_actuators. If the name isn't found it returns available_facilities.",
    }),
    # --- Map-drawn equipment (@ANCHOR: MAP_EQUIPMENT_TOOL, 2026-07-22) -----------
    # Equipment placed in geo/design (irrigation valves, sprinklers/drip, fans,
    # heaters, window/curtain motors) is stored inside equipment_collection
    # GeoShapes' feature.features[] and was invisible to the AI — build_tree only
    # aggregates a category count and never descends into the collection. This
    # exposes each item's sub_type + specs + which site/zone it sits in.
    Tool('get_map_equipment', handler='get_map_equipment_tool', manifest={
        "tool_name": "get_map_equipment",
        "action_type": "virtual_tool_call",
        "description": "Returns the geo/design map-drawn equipment and its irrigation design summary per site/zone. Distinct from control devices (Outputs). IMPORTANT — distinguish the two irrigation METHODS precisely, never merge them into one 'emitter' number: `sprinklers`/스프링클러 (individual sprinkler heads, each with a spray radius+flow) vs `drip_emitters`/점적 (drip emitters counted along drip pipes = length ÷ interval). `method` says sprinkler|drip|mixed. Discrete devices (irrigation valves, fans, heaters/coolers, window/curtain motors) are listed with specs (flow_lph, pressure_kpa, capacity_kw, airflow_cmh, power_w). Read-only. Use whenever asked what 설비/관수장치 is installed/drawn or for 유량/스프링클러/점적/배관. (For a greenhouse's COMPUTED heating/cooling design capacity use get_facility_capacity.)",
        "usage_hint": "params.arguments: {area_name (optional — a site/zone name like '1-1'; omit for whole map)}. Returns equipment[{name,sub_type,location,specs{}}] and irrigation[{area, method, sprinklers, sprinkler_flow_lph, drip_emitters, drip_flow_lph, total_flow_lph, total_flow_lpm, main_pipes, main_pipe_length_m, branch_pipes, branch_pipe_length_m}]. Report 스프링클러 and 점적 SEPARATELY. Attribution uses ownership link (parent_node_id), matching the design panel. OVERVIEW tier; for positions/spacing use get_map_equipment_detail.",
    }),
    Tool('get_map_equipment_detail', handler='get_map_equipment_detail_tool', manifest={
        "tool_name": "get_map_equipment_detail",
        "action_type": "virtual_tool_call",
        "description": "The GEOMETRY-level detail behind get_map_equipment's summary for ONE area — individual SPRINKLER head positions (lat/lng) with radius+flow, the computed sprinkler spacing (nearest-neighbour interval), DRIP detail per drip-pipe (interval + emitter count), and each pipe's length + start/end coordinates. Keeps 스프링클러 and 점적 separate. Read-only. Call this ONLY when the user asks something the summary can't answer — exact position, spacing/간격, radius, or an individual pipe. For counts/총유량/총길이 the get_map_equipment summary is enough.",
        "usage_hint": "params.arguments: {area_name (required — a site/zone name like '1-1')}. Returns sprinkler_count, sprinkler_spacing_m, sprinklers[{lat,lng,radius_m,flow_lph}] (capped at 60), drip_pipes[{pipe,interval_m,drip_emitters,flow_lph_each}], drip_emitter_total, pipes[{name,sub_type,length_m,start,end}].",
    }),
    Tool('get_device_location', handler='get_device_location', manifest={
        "tool_name": "get_device_location",
        "action_type": "virtual_tool_call",
        "description": "Reads a device's current map location (lat/lng). Read-only.",
        "usage_hint": "params.arguments: {device_id}",
    }),
    Tool('set_device_location', handler='set_device_location', mutating=True, manifest={
        "tool_name": "set_device_location",
        "action_type": "virtual_tool_call",
        "description": "Places or moves a device (Input/Output) on the map by setting its latitude/longitude. This is the GIS create/edit for a device placement. Requires human approval.",
        "usage_hint": "params.arguments: {device_id, lat, lng, map_id (optional)}",
    }),
    Tool('delete_geo_shape', handler='delete_geo_shape', mutating=True, manifest={
        "tool_name": "delete_geo_shape",
        "action_type": "virtual_tool_call",
        "description": "Deletes a SINGLE geo shape (zone/area/marker) by unique_id. Requires human approval.",
        "usage_hint": "params.arguments: {shape_id}",
    }),
    # --- Reverse geocoding (@ANCHOR: REVERSE_GEOCODE_TOOL, 2026-07-25) -----------
    # get_device_location / get_local_time only ever returned coordinates; there
    # was no way to ask "what's the address there". VWorld's getAddress API was
    # already used internally (parcel_from_address's PNU pipeline) but never
    # exposed as a standalone lookup. Read-only; requires a registered VWorld
    # GIS Input (Map > GIS Inputs) with an API Key, else returns a clear error.
    Tool('get_address', handler='get_address', manifest={
        "tool_name": "get_address",
        "action_type": "virtual_tool_call",
        "description": "Reverse-geocodes a location into a human-readable street/parcel address via the registered VWorld GIS Input. Accepts a zone/site/facility/device name (resolved to its centroid/coordinates the same way get_local_time does), a unique_id, or explicit lat/lng. Read-only. Requires a VWorld API Key configured under Map > GIS Inputs; if none is set, returns a clear error rather than silently falling back to coordinates only.",
        "usage_hint": "params.arguments: {target_name (optional, e.g. '3포장'), target_id (optional, instead of target_name), lat/lng (optional, instead of target_name/target_id)}. Returns {address, type: 'road'|'parcel', lat, lng, location}.",
    }),
    # --- Confirmation queue relay (@ANCHOR: CONFIRMATION_RELAY_TOOLS, 2026-07-26) --
    # Write/physical tools return 'pending_approval' and previously could only be
    # resolved by a human clicking Approve/Reject on the web review page
    # (/api/v1/mcp/review_page) — a page that was hard to find and forced a
    # context switch away from the chat the user was already having with the
    # external AI. These two tools let that same human approval happen IN the
    # chat instead: the AI tells the user what's pending, the user says yes/no
    # in the conversation, and the AI relays that as this tool call. The AI is
    # NOT granted independent authority to approve anything — see the tool
    # description below, which is the actual behavioral safeguard (same pattern
    # as every other 'do not retry direct execution' instruction in this file).
    Tool('list_pending_confirmations', handler='list_pending_confirmations', manifest={
        "tool_name": "list_pending_confirmations",
        "action_type": "virtual_tool_call",
        "description": "Lists write/control requests currently awaiting human approval (each returned earlier by some other tool call as 'pending_approval', with a confirmation_id). Read-only. Use this to look up a confirmation_id you no longer have, or to show the user everything that's outstanding.",
        "usage_hint": "params.arguments: {}. Returns {pending: [{confirmation_id, tool_name, params, reason, agent_id, created_at, expires_in_sec}]}.",
    }),
    Tool('respond_to_confirmation', handler=None, mutating=True, manifest={
        "tool_name": "respond_to_confirmation",
        "action_type": "virtual_tool_call",
        "description": "Approves or rejects ONE OR MORE pending confirmations (from a prior 'pending_approval' response or from list_pending_confirmations) over MCP — this is the primary approval path; the web review page is only an alternative for whoever is at a browser. Call this ONLY after the user has explicitly told you, in THIS conversation, to approve or reject THOSE SPECIFIC confirmation_id(s) — never call it on your own judgment, and never infer approval from the user's ORIGINAL task request alone ('create these schedules' is the task, not 'yes, execute confirmation_id X' — that needs its own explicit go-ahead). This applies just as much to a batch as to a single one: a vague 'clean up whatever is pending' does NOT authorize a batch approve/reject — only an explicitly named or user-confirmed set does. If unsure whether the user actually approved, ask them plainly before calling this. Requires an Admin/Editor-role key.",
        "usage_hint": "params.arguments: {confirmation_id, decision: 'approve'|'reject'} for one, OR {confirmation_ids: [...], decision} for several with the same decision in one call.",
    }),
    Tool('list_ai_agents', handler='list_ai_agents', manifest={
        "tool_name": "list_ai_agents",
        "action_type": "virtual_tool_call",
        "description": "Lists AI pipeline agents. Read-only.",
        "usage_hint": "params.arguments: {}",
    }),
    Tool('list_ai_entries', handler='list_ai_entries', manifest={
        "tool_name": "list_ai_entries",
        "action_type": "virtual_tool_call",
        "description": "Lists AI service entries (models) an agent can bind to. Read-only. Call before create_ai_agent for a valid entry_id.",
        "usage_hint": "params.arguments: {}",
    }),
    Tool('create_ai_agent', handler='create_ai_agent', mutating=True, manifest={
        "tool_name": "create_ai_agent",
        "action_type": "virtual_tool_call",
        "description": "Creates a new AI pipeline agent bound to an AIEntry. Requires human approval.",
        "usage_hint": "params.arguments: {name, entry_id (from list_ai_entries), role, specialty, system_prompt, pipeline_role, model_tier, tool_access}",
    }),
    Tool('modify_ai_agent', handler='modify_ai_agent', mutating=True, manifest={
        "tool_name": "modify_ai_agent",
        "action_type": "virtual_tool_call",
        "description": "Updates an AI agent's fields (name/role/specialty/system_prompt/pipeline_role/model_tier/tool_access). Requires human approval.",
        "usage_hint": "params.arguments: {agent_id, <field>: <value>, ...}",
    }),
    Tool('delete_ai_agent', handler='delete_ai_agent', mutating=True, manifest={
        "tool_name": "delete_ai_agent",
        "action_type": "virtual_tool_call",
        "description": "Deletes an AI agent by unique_id (clears its MCP mappings too). Requires human approval.",
        "usage_hint": "params.arguments: {agent_id}",
    }),
    Tool('get_function_list', handler='get_function_list', manifest={
        "tool_name": "get_function_list",
        "action_type": "virtual_tool_call",
        "description": "Lists all functions (Conditional/Trigger/PID/CustomController). Optional filters: function_type, active_only.",
        "usage_hint": "Call to check if a function already exists before creating a new one.",
    }),
    Tool('activate_function', handler='activate_function_tool', mutating=True, manifest={
        "tool_name": "activate_function",
        "action_type": "virtual_tool_call",
        "description": "Activates an existing function by function_id. Requires human approval.",
        "usage_hint": "params.arguments: {function_id: '<unique_id>'}",
    }),
    Tool('deactivate_function', handler='deactivate_function_tool', mutating=True, manifest={
        "tool_name": "deactivate_function",
        "action_type": "virtual_tool_call",
        "description": "Deactivates an existing function by function_id. Requires human approval.",
        "usage_hint": "params.arguments: {function_id: '<unique_id>'}",
    }),

    # --- Notice board CRUD (@ANCHOR: NOTICE_CRUD_TOOLS, 2026-07-08) ---------------
    # Wraps the same web-route utility functions the notice board UI uses
    # (aot/aot_flask/utils/utils_notice.py notice_add/notice_mod/notice_del) via
    # the shared _FakeForm shim — the exact pattern used for Input/Output CRUD.
    # Attachments and polls are UI-only (the AI can create/edit plain title+body
    # posts; not currently supported here). modify/delete are permission-gated by
    # utils_notice.can_manage_post() on the ACTUAL calling user's session (admin,
    # or the post's own author) — this is enforced by the web layer itself, not
    # bypassed by going through the AI.
    Tool('list_notices', handler='list_notices', manifest={
        "tool_name": "list_notices",
        "action_type": "virtual_tool_call",
        "description": "Lists notice board posts (title, pinned, date). Read-only.",
        "usage_hint": "params.arguments: {limit (optional, default 10)}. Call before create_notice to check for an existing post on the same topic.",
    }),
    Tool('create_notice', handler='create_notice', mutating=True, manifest={
        "tool_name": "create_notice",
        "action_type": "virtual_tool_call",
        "description": "Creates a notice board post (title + body). Requires human approval.",
        "usage_hint": "params.arguments: {title, body, pinned (optional bool, admin-only)}. Attachments/polls are not supported here — use the web UI for those.",
    }),
    Tool('modify_notice', handler='modify_notice', mutating=True, manifest={
        "tool_name": "modify_notice",
        "action_type": "virtual_tool_call",
        "description": "Updates an existing notice post's title/body/pinned state. Requires human approval AND permission (admin, or the post's own author).",
        "usage_hint": "params.arguments: {notice_id, title (optional), body (optional), pinned (optional bool)}",
    }),
    Tool('delete_notice', handler='delete_notice', mutating=True, manifest={
        "tool_name": "delete_notice",
        "action_type": "virtual_tool_call",
        "description": "Deletes a notice post by unique_id. Requires human approval AND permission (admin, or the post's own author).",
        "usage_hint": "params.arguments: {notice_id}",
    }),

    # --- Notes create (@ANCHOR: NOTE_CREATE_TOOL, 2026-07-08) ----------------------
    # A plain, undated memo/journal entry — distinct from add_schedule (a DATED
    # human work task routed through SchedulerJobMeta, not this model). Direct ORM
    # write to the Notes model; search_notes already exists as its read-side.
    #
    # NOT approval-gated (2026-07-18): a note is a low-risk, reversible, PRIVATE memo
    # the user directly asked to record. The approval machinery is built around
    # physical control / entity config, and routing notes through it silently dropped
    # them (they were intercepted as pending_approval, never auto-saved, then
    # surfaced as a "technical error"). Notes save immediately like a safe write;
    # create_notice (PUBLIC board post) stays approval-gated.
    Tool('create_note', handler='create_note', manifest={
        "tool_name": "create_note",
        "action_type": "virtual_tool_call",
        "description": "Creates a memo/note and SAVES it immediately (no approval). In AoT there is NO 'note widget' — every device, land/facility, and zone/shape has its OWN notes, viewed per-entity. A note is only visible on an entity when it is attached to it. So when the user asks to note something 'at 1포장 1-1' or 'on 밸브1', ALWAYS pass target_name with that location/entity name — the tool resolves it to the entity and attaches the note. Do NOT just say you will create it; emit this tool call.",
        "usage_hint": "params.arguments: {note (content, required), name (optional short title), target_name (location/entity name to attach to, e.g. '1포장 1-1' — STRONGLY preferred so the note is visible), tags (optional), category (optional, default 'general'). Advanced: target_id/target_type instead of target_name if the unique_id is already known. If target_name can't be resolved the tool returns available_targets — retry with an exact name. This is a GIS-based system: target_name resolves to exactly ONE entity and never auto-expands to its children, and this tool saves IMMEDIATELY with no approval step to catch a wrong hierarchy level afterward. If the request could apply per sub-unit ('각 구역별', 'each zone'), call resolve_target(target_name) FIRST — read-only, no approval — and if it returns 'children', call this tool once per child.",
    }),

    # --- Knowledge shelve (@ANCHOR: KNOWLEDGE_SHELVE_TOOL, 2026-07-19) -----------
    # Write half of docs/design/ai-library-redesign.md §4 — knowledge_search (read)
    # already existed; nothing let the AI save what it just worked out. NOT
    # approval-gated for the same reason as create_note: it always writes at the
    # lowest trust tier (provenance='ai_curated', unconfirmed — see
    # knowledge_shelve_service.py) and is never presented with authority until a
    # human confirms it or it corroborates against a real source (P5, not built
    # yet) — a low-risk, reversible write, not a state-changing entity mutation.
    Tool('knowledge_shelve', handler='knowledge_shelve', manifest={
        "tool_name": "knowledge_shelve",
        "action_type": "virtual_tool_call",
        "description": "Saves a piece of knowledge you just derived, observed, or were told, so a later query can retrieve it (the write counterpart to knowledge_search). ALWAYS saved as unconfirmed/ai_curated — you MUST tell the user it's an unconfirmed note you're keeping, not present it as fact. Only shelve something genuinely reusable (a pattern, an answer worth remembering) — not routine chit-chat.",
        "usage_hint": "params.arguments: {content (the knowledge text, required), tags (comma-separated scope tags — crop/livestock/structure/topic, REQUIRED — an untagged note would surface for every query), heading (optional short title), attribution (optional — defaults to a dated 'AI 대화 비치' note if omitted), entity_ref (optional AoT entity unique_id this is about), content_kind ('prose' default or 'structured'), ttl_hours (optional — set for time-sensitive info like a pest sighting so it expires; omit for a durable observation).",
    }),

    # --- System update / version status (read-only, 2026-07-18) ------------------
    # Wires the AI to AoTRelease().github_upgrade_exists() (same check as the
    # admin/upgrade page) so "is there a system update?" is answerable. Before
    # this, no tool exposed version/update info and the AI could only give a
    # generic "cannot check for updates" reply. Read-only — not approval-gated.
    Tool('get_system_update_status', handler='get_system_update_status', manifest={
        "tool_name": "get_system_update_status",
        "action_type": "virtual_tool_call",
        "description": "Checks whether an AoT software/system update is available by comparing the installed version against the latest GitHub release. Read-only. Use whenever the user asks about system updates, new versions, or the currently installed software version.",
        "usage_hint": "params.arguments: {}. Returns {current_version, latest_version, update_available, message}.",
    }),

    # --- Diagnostic: analyze system failure (@ANCHOR: ANALYZE_SYSTEM_FAILURE_RECONNECT,
    # Phase 2, docs/design/ai-agent-loop.md) — the implementation already existed
    # (AoTDataToolService.analyze_system_failure_tool, 031_STEP_3) but was declared
    # here with handler=None: dispatchable if somehow called, but invisible in the
    # manifest, so the LLM never knew it existed. Read-only (audits AITask failure
    # logs + MCP bridge status) — not approval-gated.
    Tool('analyze_system_failure', handler='analyze_system_failure_tool', manifest={
        "tool_name": "analyze_system_failure",
        "action_type": "virtual_tool_call",
        "description": "Diagnoses why a device/system action failed by auditing recent AITask failure logs and MCP bridge server status. Read-only.",
        "usage_hint": "params.arguments: {device_id (optional), tool_name (optional, e.g. 'operate_device'), lookback_minutes (optional, default 60)}. Use when the user reports a control/device failure or asks why something isn't working.",
    }),

    # --- Knowledge search (@ANCHOR: KNOWLEDGE_SEARCH_TOOL, Phase 2) -------------
    # Read half of docs/design/ai-library-redesign.md §4 — knowledge_shelve (write)
    # was already a tool; search only existed as a legacy action_type='knowledge_search'
    # branch invoked via a prompt instruction (base_ai.py _build_prompt), never in
    # the tool catalog itself, so the agent loop (which offers tools, not prompt-
    # injected instructions) never surfaced it. Read-only.
    Tool('knowledge_search', handler='knowledge_search_tool', manifest={
        "tool_name": "knowledge_search",
        "action_type": "virtual_tool_call",
        "description": "Searches the AI knowledge LIBRARY (system manuals + domain knowledge synced from external sources — crops, pests, environment guides) by free-text query. Read-only. Broader than read_manual (no filename/section needed). NOT for per-entity notes/memos a user recorded on a specific device or zone — those are the Notes model; use search_notes(target_name=...) for anything the user 'wrote down / recorded / noted' about a named device or zone.",
        "usage_hint": "params.arguments: {query (free text, required), top_k (optional, default 3), tags (optional comma-separated scope filter)}. Prefer this over read_manual for capability/how-to/domain questions; use read_manual only when you already know the exact file.",
    }),

    # --- Knowledge-library catalog (@ANCHOR: LIBRARY_CATALOG_TOOL, 2026-07-19) ---
    # Without this the AI could only describe SmartFarmKorea (whose setup recipe
    # is injected into the tools below) and answered "what knowledge libraries
    # can I add?" with SmartFarmKorea alone. Read-only enumerator of the full
    # LIBRARY_PRESETS catalog so the AI recommends every source type.
    Tool('list_library_source_types', handler='list_library_source_types_tool', manifest={
        "tool_name": "list_library_source_types",
        "action_type": "virtual_tool_call",
        "description": "Lists EVERY knowledge-library source type the operator can add — the pre-built external public-data APIs (RDA SmartFarm 권장설정값, 농사로 재배가이드, 병해충경보 NCPMS, SmartFarmKorea 시설/노지/축산 실측데이터) AND the custom types (document upload, web page scrape, generic REST API, internal DB query). Read-only. Call this whenever the user asks what data/knowledge sources they can add or asks for a recommendation — then present the FULL range, never just SmartFarmKorea.",
        "usage_hint": "params.arguments: {}. Returns {system_presets:[{key,label,description,url}], custom_types:[{key,label,description,source_type}]}. Use it to answer 'what knowledge libraries can I add?' comprehensively; recommend based on what the user manages (crop/livestock/facility/their own docs).",
    }),

    # --- SmartFarmKorea AI-driven setup (@ANCHOR: SMARTFARMKOREA_AI_TOOLS,
    # Phase 2, docs/design/ai-library-redesign.md) — expose Phase 1's discovery
    # primitive so the AI can register a SmartFarmKorea source end-to-end. The
    # RECIPE (discovery order, which param comes from where) is encoded in the
    # usage_hints — the always-visible injection point — so the model can drive
    # the relational drill-down without the user ever typing a code. lookup is
    # read-only; configure mutates (creates a source + fetches external data) →
    # approval-gated.
    Tool('smartfarmkorea_lookup', handler='smartfarmkorea_lookup_tool', manifest={
        "tool_name": "smartfarmkorea_lookup",
        "action_type": "virtual_tool_call",
        "description": "Discover SmartFarmKorea farms or cropping seasons so you can fill in a library source's IDs WITHOUT the user typing any codes. Read-only. Steps 1-2 of registering SmartFarmKorea data for 시설원예 (smartfarmkorea) / 노지 (smartfarmkorea_outdoor). 축산 (smartfarmkorea_livestock) has NO discovery — it needs only a date range, so skip this for it.",
        "usage_hint": "params.arguments: {dataset (preset_key: smartfarmkorea | smartfarmkorea_outdoor), api_key (the user's service key), mode ('farms' or 'seasons'), user_id (REQUIRED for mode='seasons'), query (filter by region/id — there can be 2,000+ farms), crop (filter by crop NAME: 딸기/토마토/오이/참외/방울토마토/고추/감귤/만감류/블루베리 — ALWAYS pass this when the user named a crop, so a 딸기 request never returns a 토마토 farm), limit (default 20)}. Each returned farm/season carries its crop name in `crop` and in the label. RECIPE: 1) mode='farms' with crop=<user's crop> and query=<region> → their farm's userId+facilityId+itemCode. 2) mode='seasons' with that user_id → the season's croppingSerlNo. Then configure_library_source.",
    }),
    Tool('configure_library_source', handler='configure_library_source_tool', mutating=True, manifest={
        "tool_name": "configure_library_source",
        "action_type": "virtual_tool_call",
        "description": "Create or update a SmartFarmKorea library source and (by default) activate + sync it so its measured farm data enters the AI knowledge layer. Requires human approval (registers a source and fetches external data). Handles all three datasets: smartfarmkorea (시설원예), smartfarmkorea_outdoor (노지), smartfarmkorea_livestock (축산).",
        "usage_hint": "params.arguments: {preset_key (required), api_key (required), operations (list of EXACT operation keys — NOT generic words like 'growth'/'환경'; a wrong key returns valid_operations to retry with. 시설 growth keys are crop-specific: growth_strawberry(딸기)/growth_mum(국화)/growth_melon(참외)/growth_other; 노지: growth_garlic(마늘)/growth_onion(양파)/growth_blueberry(블루베리); shared: identity/cropping/env), plus the params each operation needs. For 시설/노지 cropping/growth/env ops: userId, facilityId, croppingSerlNo, itemCode — RESOLVE THESE VIA smartfarmkorea_lookup, never ask the user for a code — and measDate/startDate/endDate (ask the user, YYYY-MM-DD). For 축산: only startDate/endDate (YYYYMMDD, no dashes). Optional: source_id (update instead of create), activate (default true), sync (default true), farm_label/season_label. NOTE: only register a farm whose crop (itemCode) matches what the user asked for — the lookup label shows the crop code. RECIPE: smartfarmkorea_lookup first, then this.",
    }),

    # --- Local time per location (@ANCHOR: GET_LOCAL_TIME_TOOL, 2026-07-20) ------
    # Every map shape/device carries coordinates, and aot/utils/device_tz.py
    # already resolves an IANA timezone from them (timezonefinder) — but that
    # capability was previously only wired into device/controller/weather code,
    # never exposed to the AI. This gives the AI an explicit, on-demand way to
    # check a SPECIFIC location's actual local time before describing or
    # planning around it, instead of assuming a single global timezone always
    # applies. Read-only — not approval-gated.
    Tool('get_local_time', handler='get_local_time_tool', manifest={
        "tool_name": "get_local_time",
        "action_type": "virtual_tool_call",
        "description": "Returns the current local wall-clock time and IANA timezone for a specific location (zone/site/facility/device) or the farm-wide default. Every location resolves its own timezone from its coordinates. Read-only.",
        "usage_hint": "params.arguments: {target_name (optional — a zone/site/facility/device name, e.g. '3-1', '온실'; omit for the farm-wide default timezone)}. Call this before describing or planning around a specific location/time (e.g. 'is it night there now?', 'should this run today or tomorrow given the local time?') instead of assuming the same timezone applies everywhere.",
    }),

    # --- virtual_tool_call tools WITHOUT a manifest entry (dispatch only) ---------
    # Read tools intentionally omitted from the slim LLM manifest; operate_device is
    # bound per-output via mcp_binding instead of a standalone system_tools entry.
    Tool('get_sensor_detail', handler='get_sensor_detail'),
    Tool('get_spatial_tree', handler='get_spatial_tree'),
    Tool('resolve_target', handler='resolve_target_tool', manifest={
        "tool_name": "resolve_target",
        "action_type": "virtual_tool_call",
        "description": "Read-only, NO approval needed. Resolve a place/device name to its exact entity BEFORE calling a write tool that takes target_name (add_schedule, create_note, create_notice, ...). Returns target_type and, if the entity has finer-grained children (e.g. a site containing zones), their exact names in 'children'. A write tool call attaches to ONLY the resolved entity, never to 'children' automatically. Call this first whenever the request could apply per-sub-unit ('each zone', '구역별', 'per section') so you know whether to loop the write tool once per child instead of writing once to the container.",
        "usage_hint": "params.arguments: {target_name: '<place/device name>'}. Returns {status, target_id, target_type, resolved_name, children, note}. If status is 'needs_disambiguation', show available_targets to the user via ask_user and retry with the exact name.",
    }),
    Tool('get_device_list', handler='get_device_list_tool'),
    Tool('search_notes', handler='search_notes_tool', manifest={
        "tool_name": "search_notes",
        "action_type": "virtual_tool_call",
        "description": "Reads FULL/older notes for one entity, or free-text searches notes. Read-only — NO approval needed. NOTE: a per-entity digest (each entity's INITIAL note + a few RECENT notes + total count) is ALREADY pre-injected in context under system_state.note_digests — use that to answer broad questions like '각 장치의 노트 확인' or 'which devices have notes' WITHOUT any tool call. Call this tool only to DRILL DOWN: read the full text or older notes of a SPECIFIC entity (pass target_name with that zone/device name — notes bind by target_id so keyword search alone misses them), or free-text keyword search (query). When target_name resolves to a SITE (포장), results automatically include every descendant zone's notes too (a site rarely has its own notes; per-zone notes like crop info live on the zones) — each result's target_name tells you which zone it came from, so attribute info per-zone rather than treating results as one undifferentiated pile.",
        "usage_hint": "params.arguments: {target_name (location/entity to read notes for, e.g. '3-1', '1포장 1-1', '밸브1'), query (optional keyword), category (optional), limit (optional, default 10)}. Returns note contents (up to 2000 chars each) for summarization.",
    }),
    Tool('get_energy_report', handler='get_energy_report'),
    Tool('operate_device', handler='operate_device_tool', physical=True),
    Tool('get_weather', handler='get_weather_tool'),
    Tool('get_active_functions_summary', handler='get_active_functions_summary'),
    Tool('get_function_detail', handler='get_function_detail'),
    Tool('get_cumulative_status', handler='get_cumulative_status'),

    # --- @ANCHOR: ADVISORY_READ_TOOLS ------------------------------------------
    # 외부 AI가 상태를 점검하고 제어를 조언하는 데 필요한데 어느 경로에도 없던
    # 읽기 도구들. manifest=None 이므로 인앱 슬림 매니페스트(=매 프롬프트 토큰)는
    # 건드리지 않고 MCP 카탈로그에만 노출된다 — get_sensor_detail 등과 같은 취급.
    Tool('get_control_state', handler='get_control_state'),
    Tool('get_weather_forecast', handler='get_weather_forecast'),
    Tool('get_anomalies', handler='get_anomalies'),
    Tool('get_crop_status', handler='get_crop_status'),

    # --- @ANCHOR: ADVICE_LEDGER_TOOLS -------------------------------------------
    # 다자 AI 의견 원장. submit_advice 는 DB에 행을 쓰지만 의도적으로 mutating 이
    # 아니다 — AI가 '의견을 말하는 것'에까지 사람 승인을 요구하면 조언 원장의
    # 목적이 사라진다. 승인이 필요한 것은 실행(operate_device 등)이며, 이 원장은
    # 실행 대신 제안을 남기는 통로다. create_note 도 같은 이유로 비변이다.
    Tool('submit_advice', handler='submit_advice'),
    Tool('list_advice', handler='list_advice'),

    # 오리엔테이션 진입점 — 외부 AI가 접속 직후 한 번 호출해 무엇을 언제 쓸지 파악한다.
    Tool('get_system_brief', handler='get_system_brief'),

    # --- registry-only validation names (dispatched elsewhere, NOT via tool_map) --
    # Known tool names that resolve_action must accept, but which are handled by the
    # native tool bridge, the legacy execute_action if/elif chain, or as special
    # action types. handler=None keeps them out of the VirtualToolResolver tool_map.
    Tool('abstract_plan', handler=None),
    Tool('note', handler=None),
    Tool('function', handler=None),
    Tool('pid', handler=None),
    Tool('get_sensor_reading', handler=None),      # native bridge
    Tool('list_available_devices', handler=None),  # native bridge
    Tool('set_output_state', handler=None, physical=True),  # native bridge, physical
    Tool('get_function_doc', handler=None),
    Tool('get_input_doc', handler=None),
    Tool('get_output_doc', handler=None),
]

# Fast lookup by name (also guards against accidental duplicate declarations).
_BY_NAME: Dict[str, Tool] = {}
for _t in TOOLS:
    if _t.name in _BY_NAME:
        raise ValueError(f"Duplicate tool declared in tool_registry: {_t.name}")
    _BY_NAME[_t.name] = _t


# ---------------------------------------------------------------------------
# MCP tool payloads — the JSON-Schema catalog exposed to the mcp_aot engine and
# the standalone stdio MCP server (aot_mcp_server.py). This USED to be a second,
# independently hand-maintained list (`VIRTUAL_TOOLS` in aot/ai/agents/mcp_aot.py):
# it drifted from this registry (advertised tools the stdio server couldn't
# dispatch; a dead AoTDataToolService.execute() call). It now lives here as the
# single declaration site; mcp_aot.VIRTUAL_TOOLS is derived from virtual_tools().
#
# Entries are stored VERBATIM (and in their original order) so the derived list
# is byte-identical to the pre-refactor VIRTUAL_TOOLS. Each entry's tool_name
# MUST match a declared Tool that has a real handler — virtual_tools() enforces
# this, so an MCP-advertised tool can never again be non-executable.
#
# NOTE: this catalog is intentionally a DIFFERENT (smaller) set than the slim
# agent-loop manifest_system_tools() — several read tools here (get_sensor_detail,
# get_spatial_tree, …) are deliberately omitted from the slim manifest but exposed
# to the MCP surface. That is why the two are separate fields, not one derivation.
# ---------------------------------------------------------------------------
_MCP_TOOL_PAYLOADS: List[Dict[str, Any]] = [
    {
        "tool_name": "get_sensor_detail",
        "description": "Query detailed sensor history for a specific location/device. Returns time-series readings with min/max/avg statistics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "loc_id": {"type": "string", "description": "unique_id of the Input device or GeoShape zone"},
                "sensor_type": {"type": "string", "description": "Filter by measurement type (e.g. temperature, humidity). Optional."},
                "time_range": {"type": "string", "description": "Duration string: '1h', '24h', '7d'. Default: '24h'"}
            },
            "required": ["loc_id"]
        }
    },
    {
        "tool_name": "get_spatial_tree",
        "description": "Retrieve the spatial hierarchy (Site > Zone > Device) tree structure with optional depth and type filtering.",
        "input_schema": {
            "type": "object",
            "properties": {
                "depth": {"type": "integer", "description": "Maximum tree depth to return. Default: 2"},
                "filter_type": {"type": "string", "description": "Filter nodes by type (e.g. 'zone', 'device'). Optional."}
            }
        }
    },
    {
        "tool_name": "resolve_target",
        "description": "Read-only, NO approval needed. Resolve a place/device name to its exact entity BEFORE calling a write tool that takes target_name (add_schedule, create_note, create_notice, ...). Write tools sit behind a human-approval gate that only checks the tool name - the actual name resolution runs only AFTER approval, too late to catch a wrong hierarchy level. Call this first to see target_type and, if the entity has finer-grained children (e.g. a site containing zones), their exact names in 'children'. A write tool call attaches to ONLY the resolved entity, never to 'children' automatically - if the request applies per sub-unit ('each zone', 'per section'), call the write tool once per entry in 'children' instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Name of the place/device to resolve (e.g. '3-1', '1포장 1-1', '온실')."}
            },
            "required": ["target_name"]
        }
    },
    {
        "tool_name": "search_devices",
        "description": "Search for devices (inputs, outputs, cameras, complex devices) by name or type keyword. A complex device (e.g. a PLC) is one physical unit whose readings/controls are split across separate Input and Output entries — its 'device' result lists member_ids, and any input/output belonging to one carries parent_device_id + parent_device_name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword for device name or type"}
            },
            "required": ["query"]
        }
    },
    {
        "tool_name": "get_device_list",
        "description": "List all registered devices (inputs, outputs, cameras, complex devices) in the AoT system. Use this when the user asks for a full device listing without a specific keyword. A complex device (e.g. a PLC) is one physical unit whose readings/controls are split across separate Input and Output entries — its 'device' entry lists member_ids, and any input/output belonging to one carries parent_device_id + parent_device_name.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "tool_name": "get_energy_report",
        "description": "Generate an energy usage analysis report for a specific period and/or zone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "Analysis period: 'daily', 'weekly', 'monthly'. Default: 'daily'"},
                "zone_id": {"type": "string", "description": "Filter by zone unique_id. Optional (omit for all zones)."}
            }
        }
    },
    {
        "tool_name": "operate_device",
        "description": "[INTENT A] Direct physical control of devices. Use this for immediate operations like opening valves or turning on lights.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "unique_id of the output device"},
                "state": {"type": "string", "enum": ["on", "off", "set_value"], "description": "Target state"},
                "value": {"type": "number", "description": "Numeric value for PWM/Setpoints (optional)"}
            },
            "required": ["device_id", "state"]
        }
    },
    {
        "tool_name": "add_schedule",
        "description": "[Human task / memo] Record a work schedule or memo for a person to carry out - weeding, inspection, cleaning and other manual tasks. For system control (valves, pumps, ...) use schedule_device_control instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Target date (YYYY-MM-DD)"},
                "time": {"type": "string", "description": "Target time (HH:MM). Default '09:00'"},
                "content": {"type": "string", "description": "Description of the work or schedule"},
                "worker": {"type": "string", "description": "Name of the person assigned (optional)"},
                "tags": {"type": "string", "description": "Comma-separated tags (optional). If not provided, spatial tags are automatically extracted from content."},
                "target_name": {"type": "string", "description": "Name of the zone/facility/device this work applies to (e.g. '3-1', '1포장 1-1', '온실'). PASS this whenever the user names a place, so the schedule links to the real entity for map/location queries instead of relying on free-text tag extraction. If the name is ambiguous or not found, the tool returns status 'needs_disambiguation' with an available_targets list - show these to the user, then retry with the exact name. Omit only for a farm-wide event with no specific place. This is a GIS-based system: a name resolves to exactly ONE entity and never fans out to its children automatically. If the request could apply per sub-unit (each zone/구역, each device under a site), call resolve_target(target_name) FIRST - it is read-only, needs no approval, and returns 'children' when the resolved entity contains finer-grained sub-entities. If so, use add_schedule_batch instead of calling this tool once per child."}
            },
            "required": ["date", "content"]
        }
    },
    {
        "tool_name": "add_schedule_batch",
        "description": "Register MULTIPLE per-entity work schedules in ONE call, behind a SINGLE approval - use instead of N separate add_schedule calls whenever a request applies per sub-unit ('각 구역별로', 'each zone'). Each add_schedule call needs its own approval and its own rate-limited request slot; a 9-entity request as 9 separate add_schedule calls can exhaust the hourly limit before finishing. Call resolve_target on the container name first to get the exact child names for entries. If entries.length * duration_minutes would not fit inside window_start-window_end, the call is rejected up front with the exact numbers (nothing created) - this is checked by the server, not something you need to compute yourself, but if it rejects, the request needs more than one date and you must either split entries across multiple add_schedule_batch calls (one per date) or ask the user how to compress/parallelize the work.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Shared date (YYYY-MM-DD) for every entry."},
                "entries": {
                    "type": "array",
                    "description": "One item per target. Duplicate target_name within the same batch is rejected.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "target_name": {"type": "string", "description": "Exact zone/facility/device name (e.g. a child name returned by resolve_target)."},
                            "time": {"type": "string", "description": "Time for this entry (HH:MM)."},
                            "content": {"type": "string", "description": "Overrides the shared content for this entry only. Optional."},
                            "worker": {"type": "string", "description": "Overrides the shared worker for this entry only. Optional."}
                        },
                        "required": ["target_name", "time"]
                    }
                },
                "content": {"type": "string", "description": "Shared work description, used by any entry that omits its own content. Required unless every entry supplies its own."},
                "worker": {"type": "string", "description": "Shared worker name, used by any entry that omits its own worker. Optional."},
                "tags": {"type": "string", "description": "Comma-separated tags applied to every entry. Optional."},
                "window_start": {"type": "string", "description": "'HH:MM' - start of the work window. Combined with window_end, enables the capacity check (entries.length * duration_minutes vs. available window minutes). Optional but recommended whenever the request implies a bounded work window (e.g. '07:00~11:00')."},
                "window_end": {"type": "string", "description": "'HH:MM' - end of the work window. Alone: every entry's time must be <= this or the whole batch is rejected. Together with window_start: also rejects up front if entries.length * duration_minutes exceeds the window's total minutes, before any approval is created."},
                "duration_minutes": {"type": "integer", "description": "Assumed minutes needed per entry, used only for the window_start+window_end capacity check. Default 60."}
            },
            "required": ["date", "entries"]
        }
    },
    {
        "tool_name": "search_notes",
        "description": "[Read notes] Query notes, memos and work records. Read-only, so no approval is needed (summarising is data processing). To read or summarise notes attached to a particular zone or device (e.g. 'summarise notes for zone 3-1'), you MUST pass that location/device name in target_name - notes are attached to an entity by target_id and their text may not contain the zone name, so a keyword search will not find them. If target_name is a site, notes from every zone under it are returned as well (use each result's target_name to tell them apart). Use query for free keyword search.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Name of the location/device the notes are attached to (e.g. '3-1', '1포장 1-1', '밸브1'). Use this when reading or summarising notes for a zone or device."},
                "query": {"type": "string", "description": "Free keyword search (e.g. 'bean field', 'weeding'). When given together with target_name it further filters within that entity."},
                "category": {"type": "string", "description": "Category filter: 'schedule', 'general', etc. Omit for all."},
                "limit": {"type": "integer", "description": "Maximum number of results (default 10)."}
            }
        }
    },
    {
        "tool_name": "schedule_device_control",
        "description": "[Device control scheduling only] Schedule control of a system device - valve, pump, sprinkler and so on - at a specific time. It is registered with the scheduler after user approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "unique_id of the output device to control"},
                "scheduled_time": {"type": "string", "description": "ISO 8601 format datetime (e.g., '2026-02-27T09:00:00+09:00')"},
                "state": {"type": "string", "enum": ["on", "off"], "description": "Target state"},
                "duration_minutes": {"type": "number", "description": "Duration in minutes (optional, default: 5)"}
            },
            "required": ["device_id", "scheduled_time", "state"]
        }
    },
    {
        "tool_name": "get_weather",
        "description": "Current weather for a site or zone. Returns temperature, humidity, wind speed, precipitation and condition.",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_name": {
                    "type": "string",
                    "description": "Name of the site or zone to query (e.g. '1포장', '2포장'). Usable instead of zone_id."
                },
                "zone_id": {
                    "type": "string",
                    "description": "unique_id of the GeoShape. Usable instead of zone_name."
                }
            }
        }
    },
    {
        "tool_name": "get_cumulative_status",
        "description": "Daily cumulative DLI (daily light integral) and GDD (growing degree days) for an EnvCoordinator function, with the running deficit. Use it to check whether light and temperature targets are being met and what compensation is suggested.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {
                    "type": "string",
                    "description": "unique_id of the EnvCoordinator function."
                },
                "days": {
                    "type": "integer",
                    "description": "How many recent days to report (default 7)."
                }
            },
            "required": ["function_id"]
        }
    },
    {
        "tool_name": "get_system_update_status",
        "description": "Check whether an AoT software update is available by comparing the installed version with the latest GitHub release. Use it when the user asks about 'system update', 'new version' or 'current version'. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "tool_name": "create_note",
        "description": "Create and store a note immediately (an undated memo - for dated work use add_schedule). No approval needed. AoT has no 'note widget'; every device, plot and zone shape carries its own notes and they are read per entity. A note is only visible on the entity it is attached to. So when the user asks to record something 'on 1포장 1-1' or 'on 밸브1', always put that location/device name in target_name (the tool resolves it to the real target and attaches the note). Do not merely say you will create it - actually call this tool.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "Body text of the note."},
                "name": {"type": "string", "description": "Short note title. Optional."},
                "target_name": {"type": "string", "description": "Name of the location/device to attach the note to (e.g. '1포장 1-1', '밸브1'). The tool resolves it to a unique_id. Strongly recommended, otherwise the note will not be visible anywhere. This is a GIS-based system: the name resolves to exactly ONE entity and never fans out to its children, and this tool saves immediately with no approval step to catch a wrong hierarchy level afterward. If the request could apply per sub-unit (each zone/구역 under a site), call resolve_target(target_name) FIRST (read-only, no approval) and, if it returns 'children', call this tool once per child name."},
                "tags": {"type": "string", "description": "Tags, comma separated. Optional."},
                "category": {"type": "string", "description": "Category (default 'general'). Optional."},
                "target_id": {"type": "string", "description": "Target unique_id directly, when you already know it (instead of target_name). Optional."},
                "target_type": {"type": "string", "description": "Type of the linked target (e.g. 'zone', 'input', 'output'). Optional."}
            },
            "required": ["note"]
        }
    },
    {
        "tool_name": "list_notices",
        "description": "List notice-board posts (title, pinned flag, date). Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum number of results (default 10)."}
            }
        }
    },
    {
        "tool_name": "create_notice",
        "description": "Creates a notice board post (title + body). Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Notice title."},
                "body": {"type": "string", "description": "Notice body text."},
                "pinned": {"type": "boolean", "description": "Pin to top (admin-only). Optional."}
            },
            "required": ["title", "body"]
        }
    },
    {
        "tool_name": "modify_notice",
        "description": "Updates an existing notice post's title/body/pinned state. Requires human approval AND permission (admin, or the post's own author).",
        "input_schema": {
            "type": "object",
            "properties": {
                "notice_id": {"type": "string", "description": "unique_id of the notice (from list_notices)."},
                "title": {"type": "string", "description": "New title. Optional."},
                "body": {"type": "string", "description": "New body text. Optional."},
                "pinned": {"type": "boolean", "description": "New pinned state. Optional."}
            },
            "required": ["notice_id"]
        }
    },
    {
        "tool_name": "delete_notice",
        "description": "Deletes a notice post by unique_id. Requires human approval AND permission (admin, or the post's own author).",
        "input_schema": {
            "type": "object",
            "properties": {"notice_id": {"type": "string", "description": "unique_id of the notice to delete."}},
            "required": ["notice_id"]
        }
    },
    {
        "tool_name": "get_facility_capacity",
        "description": "Design-derived performance and capacity of facilities (greenhouses/structures) drawn in geo/design: reference heating and cooling capacity (kW), floor/volume/glazing area, ventilation (ACH and opening m2), irrigation summary (pipes, emitter count, flow L/min) and the number of bound controllers. Read-only - engineering reference estimates computed on demand (+/-5-10%). Use for capacity and design questions ('is cooling sufficient?', 'what is the irrigation flow?', 'heating capacity').",
        "input_schema": {
            "type": "object",
            "properties": {
                "facility_name": {"type": "string", "description": "Facility name (e.g. '육묘장'). Omit to return every facility."}
            }
        }
    },
    {
        "tool_name": "get_map_equipment",
        "description": "Equipment drawn on the geo/design map plus a per-zone irrigation design summary. Separate from controllers (Outputs). IMPORTANT - keep the two irrigation methods strictly apart and never merge them into a single 'emitter' figure: `sprinklers` (individual spray heads, each with throw radius and flow) versus `drip_emitters` (derived from drip pipe length / spacing). `method` = sprinkler | drip | mixed. Individual equipment (irrigation valves, ventilation fans, heaters/chillers, window and curtain motors) is returned with its specs (flow_lph, pressure_kpa, capacity_kw, airflow_cmh, power_w). Read-only. Use for 'what irrigation equipment is there' and 'flow / sprinklers / drip / piping in zone X'. Report sprinklers and drip separately. (For a greenhouse's calculated heating and cooling design capacity use get_facility_capacity.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "area_name": {"type": "string", "description": "Site or zone name (e.g. '1-1'). Omit for the whole map."}
            }
        }
    },
    {
        "tool_name": "get_map_equipment_detail",
        "description": "One level below the get_map_equipment summary: geometry detail for a single zone - individual sprinkler head positions (lat/lng), radius and flow, computed sprinkler spacing (median of neighbours), and for drip the per-pipe spacing and emitter count, plus each pipe's length and start/end coordinates. Sprinklers and drip stay separate. Read-only. Call it only for specific questions the summary cannot answer (exact position, spacing, radius, a particular pipe); counts, total flow and total length are already in the summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "area_name": {"type": "string", "description": "Site or zone name (e.g. '1-1'). Required."}
            },
            "required": ["area_name"]
        }
    },

    # =========================================================================
    # @ANCHOR: MCP_ADVISORY_CATALOG
    # 외부 AI가 "GIS·환경데이터·지식레이어를 근거로 최적 재배·공간운영을 조언"
    # 하려면 필요한 도구들. 아래 두 묶음으로 나뉜다.
    #
    # (A) 이미 실행은 되던 읽기 도구 — 광고만 빠져 있었다.
    #     tools/call 디스패치는 build_tool_map()(SSOT)을 쓰므로 이름만 알면
    #     실행됐지만, tools/list 에 없으니 외부 AI는 존재를 알 수 없어 영원히
    #     호출하지 않았다. 지식레이어 검색과 일정 조회가 여기 묶여 있었다.
    #
    # (B) 새로 만든 읽기 도구 4개 (ADVISORY_READ_TOOLS 참조).
    #
    # 변이/물리 도구는 여기 넣지 않는다 — 외부 AI는 조언까지만 하고 실행은 사람
    # 승인을 거친다(mcp_safety_gate). 승인이 필요한 도구를 카탈로그에서 늘리는
    # 것은 별도 판단 사항이다.
    # =========================================================================

    # ── (A) 실행은 되나 광고가 빠져 있던 읽기 도구 ───────────────────────────
    {
        "tool_name": "knowledge_search",
        "description": "Search the knowledge layer - system manuals, synced domain knowledge from agricultural authorities, and AI-curated notes - with a free-text query. Use it to ground growing, configuration and troubleshooting advice in a source. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, in natural language. E.g. 'tomato irrigation interval', 'setting a VPD target'."},
                "top_k": {"type": "integer", "description": "Maximum number of results (default 3)."},
                "tags": {"type": "string", "description": "Narrow the search by tag. Optional."}
            },
            "required": ["query"]
        }
    },
    {
        "tool_name": "search_schedule",
        "description": "Query the schedule ledger (device reservations, human tasks, AI-registered jobs). Essential before advising anything: it shows what is already planned, preventing duplicate or conflicting instructions. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term matched against schedule content. Omit for all."},
                "target_name": {"type": "string", "description": "Restrict to a particular zone or device name."},
                "include_past": {"type": "boolean", "description": "Include past entries as well (default false)."},
                "limit": {"type": "integer", "description": "Maximum number of results (default 20)."}
            }
        }
    },
    {
        "tool_name": "get_function_list",
        "description": "List registered control Functions with name, type and activation state. The entry point for understanding what automation is configured. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_type": {"type": "string", "description": "Filter by type (e.g. pid, conditional, trigger). Optional."},
                "active_only": {"type": "boolean", "description": "Active functions only (default false)."}
            }
        }
    },
    {
        "tool_name": "get_function_detail",
        "description": "Full configuration of one control Function - includes the setpoint for PID controllers. Use it to judge why control behaves the way it does. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "unique_id of the function (obtain it from get_function_list)."}
            },
            "required": ["function_id"]
        }
    },
    {
        "tool_name": "create_function",
        "description": "Creates a new automation function/controller. Requires human approval. This — NOT schedule_device_control — is the right home for RECURRING device control (daily/weekly watering) and CONDITION-BASED control (when humidity < X). For SEQUENTIAL control of several devices (e.g. a valve sequence), use create_sequence_function instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_type": {"type": "string",
                    "enum": ["conditional_conditional", "pid_pid", "trigger_edge", "trigger_output",
                             "trigger_output_pwm", "trigger_run_pwm_method", "trigger_sequence",
                             "trigger_sunrise_sunset", "trigger_timer_daily_time_point",
                             "trigger_timer_daily_time_span", "trigger_timer_duration", "function_actions"],
                    "description": "The kind of function to create."},
                "name": {"type": "string", "description": "Display name for the function."},
                "params": {"type": "object", "description": "Optional dict of custom_option overrides (e.g. select_measurement fields as 'device_id,meas_id')."}
            },
            "required": ["function_type", "name"]
        }
    },
    {
        "tool_name": "create_sequence_function",
        "description": "Creates a trigger_sequence AND fills its steps — one ordered output action per device — so it is configured, not empty. Use for 'valve sequence' / sequential device control. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Display name for the sequence function."},
                "device_ids": {"type": "array", "items": {"type": "string"}, "description": "Ordered list of output unique_ids — the order they fire in."},
                "state": {"type": "string", "enum": ["on", "off"], "description": "State applied to every step."},
                "step_duration": {"type": "number", "description": "Seconds each step stays in that state before moving on. Optional."},
                "pause_seconds": {"type": "number", "description": "Seconds to pause between steps. Optional."}
            },
            "required": ["name", "device_ids", "state"]
        }
    },
    {
        "tool_name": "modify_function_options",
        "description": "Updates custom_options of an existing function and reloads it in the daemon. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "unique_id of the function (from get_function_list)."},
                "params": {"type": "object", "description": "Dict of {option_id: value} to update."}
            },
            "required": ["function_id", "params"]
        }
    },
    {
        "tool_name": "delete_function",
        "description": "Deletes a function/controller by unique_id. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {"function_id": {"type": "string", "description": "unique_id of the function to delete."}},
            "required": ["function_id"]
        }
    },
    {
        "tool_name": "activate_function",
        "description": "Activates an existing function by function_id. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {"function_id": {"type": "string", "description": "unique_id of the function to activate."}},
            "required": ["function_id"]
        }
    },
    {
        "tool_name": "deactivate_function",
        "description": "Deactivates an existing function by function_id. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {"function_id": {"type": "string", "description": "unique_id of the function to deactivate."}},
            "required": ["function_id"]
        }
    },
    {
        "tool_name": "get_active_functions_summary",
        "description": "Summary of currently active control Functions - what is running automatically right now. Read-only.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "tool_name": "get_device_measurements",
        "description": "Measurement channels and units a device actually reports. Use before querying sensor values to learn which metrics exist. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "unique_id of an Input or CustomController."}
            },
            "required": ["device_id"]
        }
    },
    {
        "tool_name": "get_local_time",
        "description": "Current local time and timezone at a location (zone/facility/device). Devices may sit in different timezones, so check this before advising anything time-related (scheduling, day/night reasoning). Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Name of the zone, facility or device."},
                "target_id": {"type": "string", "description": "unique_id of the target (instead of the name)."}
            }
        }
    },
    {
        "tool_name": "list_geo_maps",
        "description": "List registered maps (farms) with geo_id, name and centre coordinates. Entry point for spatial queries. Read-only.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "tool_name": "list_gis_inputs",
        "description": "Lists registered GIS Inputs (map layers/providers — VWorld, Google, OpenWeather, etc). Read-only.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "tool_name": "create_gis_input",
        "description": "Creates a new GIS Input (map layer/provider, e.g. gis_vworld, gis_openweather). layer_type must be a 'gis_*' entry from list_device_types(kind='input'). Always created DEACTIVATED — call activate_gis_input once configured. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_type": {"type": "string", "description": "A 'gis_*' type from list_device_types(kind='input')."},
                "name": {"type": "string", "description": "Optional."},
                "params": {"type": "object", "description": "Optional dict of option overrides (e.g. {'api_key': '...'})."}
            },
            "required": ["layer_type"]
        }
    },
    {
        "tool_name": "modify_gis_input",
        "description": "Updates a GIS Input's name and/or options (e.g. api_key). Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {"type": "string", "description": "From list_gis_inputs."},
                "name": {"type": "string", "description": "Optional."},
                "params": {"type": "object", "description": "Dict of {option_id: value}."}
            },
            "required": ["layer_id"]
        }
    },
    {
        "tool_name": "activate_gis_input",
        "description": "Activates or deactivates a GIS Input. New GIS Inputs are created deactivated. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "layer_id": {"type": "string"},
                "active": {"type": "boolean", "description": "Default true."}
            },
            "required": ["layer_id"]
        }
    },
    {
        "tool_name": "delete_gis_input",
        "description": "Deletes a GIS Input by unique_id. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {"layer_id": {"type": "string"}},
            "required": ["layer_id"]
        }
    },
    {
        "tool_name": "get_device_location",
        "description": "A device's current map position (latitude/longitude). Use when advising based on spatial layout. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "unique_id of the device."}
            },
            "required": ["device_id"]
        }
    },
    {
        "tool_name": "set_device_location",
        "description": "Places or moves a device (Input/Output) on the map by setting its latitude/longitude. This is the GIS create/edit for a device placement. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "unique_id of the device."},
                "lat": {"type": "number"},
                "lng": {"type": "number"},
                "map_id": {"type": "string", "description": "Optional map unique_id to bind the device to."}
            },
            "required": ["device_id", "lat", "lng"]
        }
    },
    {
        "tool_name": "delete_geo_shape",
        "description": "Deletes a SINGLE geo shape (zone/area/marker) by unique_id. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {"shape_id": {"type": "string"}},
            "required": ["shape_id"]
        }
    },
    # --- Device (Input/Output) CRUD (@ANCHOR: DEVICE_CRUD_TOOLS, 2026-07-26) -----
    # Already fully implemented and used internally (create_input/modify_input/
    # delete_input, create_output/modify_output/delete_output, plus the
    # list_device_types/get_device_type_options lookups they depend on) but never
    # exposed to external MCP clients — same gap pattern as the Function/Notice
    # CRUD found earlier today.
    {
        "tool_name": "list_device_types",
        "description": "Lists the valid TYPES available for creating an Input/Output/Function. Read-only. ALWAYS call this before create_input/create_output/create_function so the type is real — never invent a type.",
        "input_schema": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["input", "output", "function"]}},
            "required": ["kind"]
        }
    },
    {
        "tool_name": "get_device_type_options",
        "description": "Returns the configurable option schema (id/type/name/default) for a given device type. Read-only. Use to learn which option ids to pass to modify_input/modify_output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["input", "output", "function"]},
                "device_type": {"type": "string", "description": "A type string returned by list_device_types."}
            },
            "required": ["kind", "device_type"]
        }
    },
    {
        "tool_name": "create_input",
        "description": "Creates a new Input (sensor / data source). Requires human approval. Create-then-configure: this makes the device with its type; fill options afterward with modify_input.",
        "input_schema": {
            "type": "object",
            "properties": {
                "input_type": {"type": "string", "description": "From list_device_types kind='input'."},
                "name": {"type": "string"},
                "interface": {"type": "string", "description": "Optional."},
                "params": {"type": "object", "description": "Optional dict of option overrides."}
            },
            "required": ["input_type", "name"]
        }
    },
    {
        "tool_name": "modify_input",
        "description": "Updates an Input's name and/or options and reloads it. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "input_id": {"type": "string"},
                "name": {"type": "string", "description": "Optional."},
                "params": {"type": "object", "description": "Dict of {option_id: value}."}
            },
            "required": ["input_id"]
        }
    },
    {
        "tool_name": "delete_input",
        "description": "Deletes an Input by unique_id. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {"input_id": {"type": "string"}},
            "required": ["input_id"]
        }
    },
    {
        "tool_name": "create_output",
        "description": "Creates a new Output (actuator / relay / valve). Requires human approval. Create-then-configure: makes the device with its type; fill options afterward with modify_output.",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_type": {"type": "string", "description": "From list_device_types kind='output'."},
                "name": {"type": "string"},
                "interface": {"type": "string", "description": "Optional."},
                "params": {"type": "object", "description": "Optional dict of option overrides."}
            },
            "required": ["output_type", "name"]
        }
    },
    {
        "tool_name": "modify_output",
        "description": "Updates an Output's name and/or options and reloads it. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_id": {"type": "string"},
                "name": {"type": "string", "description": "Optional."},
                "params": {"type": "object", "description": "Dict of {option_id: value}."}
            },
            "required": ["output_id"]
        }
    },
    {
        "tool_name": "delete_output",
        "description": "Deletes an Output by unique_id. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {"output_id": {"type": "string"}},
            "required": ["output_id"]
        }
    },
    # --- Schedule edit/delete (@ANCHOR: SCHEDULE_EDIT_DELETE_TOOLS, 2026-07-26) --
    # search_schedule/add_schedule were already exposed; edit/delete were not.
    {
        "tool_name": "edit_schedule",
        "description": "Edits an existing schedule's time, duration, content, or worker. Requires human approval. If the schedule is an already-registered device reservation, its trigger is rescheduled too. First call search_schedule to get the job_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "From search_schedule."},
                "date": {"type": "string", "description": "Optional YYYY-MM-DD, keeps existing date if omitted."},
                "time": {"type": "string", "description": "Optional HH:MM, keeps existing time if omitted."},
                "duration_minutes": {"type": "number", "description": "Optional new duration in minutes."},
                "content": {"type": "string", "description": "Optional new text."},
                "worker": {"type": "string", "description": "Optional new assignee."},
                "target_name": {"type": "string", "description": "Optional — re-link to a different zone/facility/device by name."}
            },
            "required": ["job_id"]
        }
    },
    {
        "tool_name": "delete_schedule",
        "description": "Cancels/deletes a schedule. Requires human approval. Soft-deletes (archived, reversible) and removes any registered device trigger so it no longer fires. First call search_schedule to get the job_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "From search_schedule."},
                "reason": {"type": "string", "description": "Optional cancellation reason."}
            },
            "required": ["job_id"]
        }
    },
    # --- AI agent / library management (@ANCHOR: AI_AGENT_LIBRARY_TOOLS, 2026-07-26)
    {
        "tool_name": "list_ai_agents",
        "description": "Lists AI pipeline agents. Read-only.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "tool_name": "list_ai_entries",
        "description": "Lists AI service entries (models) an agent can bind to. Read-only. Call before create_ai_agent for a valid entry_id.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "tool_name": "create_ai_agent",
        "description": "Creates a new AI pipeline agent bound to an AIEntry. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "entry_id": {"type": "string", "description": "From list_ai_entries."},
                "role": {"type": "string"},
                "specialty": {"type": "string"},
                "system_prompt": {"type": "string"},
                "pipeline_role": {"type": "string"},
                "model_tier": {"type": "string"},
                "tool_access": {"type": "string"}
            },
            "required": ["name", "entry_id"]
        }
    },
    {
        "tool_name": "modify_ai_agent",
        "description": "Updates an AI agent's fields (name/role/specialty/system_prompt/pipeline_role/model_tier/tool_access). Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "name": {"type": "string"}, "role": {"type": "string"}, "specialty": {"type": "string"},
                "system_prompt": {"type": "string"}, "pipeline_role": {"type": "string"},
                "model_tier": {"type": "string"}, "tool_access": {"type": "string"}
            },
            "required": ["agent_id"]
        }
    },
    {
        "tool_name": "delete_ai_agent",
        "description": "Deletes an AI agent by unique_id (clears its MCP mappings too). Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {"agent_id": {"type": "string"}},
            "required": ["agent_id"]
        }
    },
    {
        "tool_name": "knowledge_shelve",
        "description": "Saves a piece of knowledge you just derived, observed, or were told, so a later query can retrieve it (the write counterpart to knowledge_search). ALWAYS saved as unconfirmed/ai_curated — you MUST tell the user it's an unconfirmed note you're keeping, not present it as fact. Only shelve something genuinely reusable (a pattern, an answer worth remembering) — not routine chit-chat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The knowledge text."},
                "tags": {"type": "string", "description": "Comma-separated scope tags (crop/livestock/structure/topic) — REQUIRED, an untagged note would surface for every query."},
                "heading": {"type": "string", "description": "Optional short title."},
                "attribution": {"type": "string", "description": "Optional — defaults to a dated 'AI 대화 비치' note if omitted."},
                "entity_ref": {"type": "string", "description": "Optional AoT entity unique_id this is about."},
                "content_kind": {"type": "string", "enum": ["prose", "structured"], "description": "Default 'prose'."},
                "ttl_hours": {"type": "number", "description": "Optional — set for time-sensitive info so it expires."}
            },
            "required": ["content", "tags"]
        }
    },
    {
        "tool_name": "list_library_source_types",
        "description": "Lists EVERY knowledge-library source type the operator can add — the pre-built external public-data APIs (RDA SmartFarm 권장설정값, 농사로 재배가이드, 병해충경보 NCPMS, SmartFarmKorea 시설/노지/축산 실측데이터) AND the custom types (document upload, web page scrape, generic REST API, internal DB query). Read-only. Call this whenever the user asks what data/knowledge sources they can add or asks for a recommendation — then present the FULL range, never just SmartFarmKorea.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "tool_name": "smartfarmkorea_lookup",
        "description": "Discover SmartFarmKorea farms or cropping seasons so you can fill in a library source's IDs WITHOUT the user typing any codes. Read-only. Steps 1-2 of registering SmartFarmKorea data for 시설원예 (smartfarmkorea) / 노지 (smartfarmkorea_outdoor). 축산 (smartfarmkorea_livestock) has NO discovery — it needs only a date range, so skip this for it. RECIPE: 1) mode='farms' with crop=<user's crop> and query=<region> → userId+facilityId+itemCode. 2) mode='seasons' with that user_id → croppingSerlNo. Then configure_library_source.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "enum": ["smartfarmkorea", "smartfarmkorea_outdoor"]},
                "api_key": {"type": "string", "description": "The user's SmartFarmKorea service key."},
                "mode": {"type": "string", "enum": ["farms", "seasons"]},
                "user_id": {"type": "string", "description": "REQUIRED for mode='seasons'."},
                "query": {"type": "string", "description": "Filter by region/id — there can be 2,000+ farms."},
                "crop": {"type": "string", "description": "Filter by crop NAME (딸기/토마토/오이/참외/방울토마토/고추/감귤/만감류/블루베리) — ALWAYS pass when the user named a crop."},
                "limit": {"type": "integer", "description": "Default 20."}
            },
            "required": ["dataset", "api_key", "mode"]
        }
    },
    {
        "tool_name": "configure_library_source",
        "description": "Create or update a SmartFarmKorea library source and (by default) activate + sync it so its measured farm data enters the AI knowledge layer. Requires human approval (registers a source and fetches external data). Handles all three datasets: smartfarmkorea (시설원예), smartfarmkorea_outdoor (노지), smartfarmkorea_livestock (축산). RECIPE: smartfarmkorea_lookup first, then this. Only register a farm whose crop (itemCode) matches what the user asked for.",
        "input_schema": {
            "type": "object",
            "properties": {
                "preset_key": {"type": "string", "enum": ["smartfarmkorea", "smartfarmkorea_outdoor", "smartfarmkorea_livestock"]},
                "api_key": {"type": "string"},
                "operations": {"type": "array", "items": {"type": "string"}, "description": "EXACT operation keys (not generic words) — a wrong key returns valid_operations to retry with. 시설: growth_strawberry/growth_mum/growth_melon/growth_other, 노지: growth_garlic/growth_onion/growth_blueberry, shared: identity/cropping/env."},
                "userId": {"type": "string"}, "facilityId": {"type": "string"},
                "croppingSerlNo": {"type": "string"}, "itemCode": {"type": "string"},
                "measDate": {"type": "string"}, "startDate": {"type": "string"}, "endDate": {"type": "string"},
                "source_id": {"type": "string", "description": "Optional — update instead of create."},
                "activate": {"type": "boolean", "description": "Default true."},
                "sync": {"type": "boolean", "description": "Default true."},
                "farm_label": {"type": "string"}, "season_label": {"type": "string"}
            },
            "required": ["preset_key", "api_key", "operations"]
        }
    },
    {
        "tool_name": "get_address",
        "description": "Reverse-geocodes a location into a human-readable street/parcel address via the registered VWorld GIS Input. Accepts a zone/site/facility/device name, a unique_id, or explicit lat/lng. Read-only. Requires a VWorld API Key configured under Map > GIS Inputs; if none is set, returns a clear error.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Name of the zone, site, facility or device (e.g. '3포장')."},
                "target_id": {"type": "string", "description": "unique_id of the target, instead of target_name."},
                "lat": {"type": "number", "description": "Latitude, instead of target_name/target_id."},
                "lng": {"type": "number", "description": "Longitude, instead of target_name/target_id."}
            }
        }
    },
    {
        "tool_name": "list_pending_confirmations",
        "description": "Lists write/control requests currently awaiting human approval (each returned earlier by some other tool call as 'pending_approval', with a confirmation_id). Read-only. Use this to look up a confirmation_id you no longer have, or to show the user everything that's outstanding.",
        "input_schema": {"type": "object", "properties": {}}
    },
    # NOTE: respond_to_confirmation is intentionally NOT here. It has handler=None
    # in TOOLS (special-dispatched by aot_mcp_server.py, same as the native-bridge
    # tools like set_output_state) — virtual_tools() requires every payload's Tool
    # to have a real handler, so it's advertised via aot_mcp_server._EXTRA_TOOLS
    # instead, the same way native tools are advertised via AoTNativeToolEngine
    # rather than through this payload list.
    {
        "tool_name": "analyze_system_failure",
        "description": "Diagnose system failures - recent failed AI tasks and MCP connection health. Use to find out why something did not work. This covers system/integration faults, not sensor or environment anomalies (use get_anomalies for those). Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Restrict to a particular device. Optional."},
                "tool_name": {"type": "string", "description": "Restrict to a particular tool. Optional."},
                "lookback_minutes": {"type": "integer", "description": "Look-back window in minutes (default 60)."}
            }
        }
    },

    # ── (B) 신설 읽기 도구 ────────────────────────────────────────────────────
    {
        "tool_name": "get_control_state",
        "description": "Current targets and latest decision of the environment-control coordinators - target VPD/temperature/humidity/CO2, tolerances, priorities, safety ranges, operating windows, plus the latest cycle's actually-applied targets, limiting factor, safety-gate status and actuator commands with reason codes. Read this before advising on control: it shows what the system is currently trying to do. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "facility_name": {"type": "string", "description": "Filter by facility name. Omit for all."},
                "facility_id": {"type": "string", "description": "Filter by facility unique_id."},
                "include_inactive": {"type": "boolean", "description": "Include inactive coordinators as well (default false)."}
            }
        }
    },
    {
        "tool_name": "get_weather_forecast",
        "description": "KMA short-term hourly forecast. get_weather returns only current values, so pre-emptive advice (temperature about to drop - warm up in advance) needs this. The response carries the issue time, its age and a 'stale' flag; when stale is true do not base control advice on it - report that forecast collection needs checking. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "How many hours ahead to return (default 24)."}
            }
        }
    },
    {
        "tool_name": "get_anomalies",
        "description": "On-demand check for anomalies right now - threshold violations, device-offline ratio and an alert level (none/info/warning/critical). It only evaluates; it sends no notifications. For system/integration faults use analyze_system_failure. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scope_type": {"type": "string", "description": "Scope: system | farm | zone | facility (default system)."},
                "scope_id": {"type": "string", "description": "unique_id of the scope target (omit for system)."}
            }
        }
    },
    {
        "tool_name": "get_crop_status",
        "description": "Crop and growth stage per facility - crop_preset, growing-season window, and (when the domain registry is configured) growth stage, days after planting and stage-specific optimal ranges. Optimal-growing advice is not possible without knowing the crop, so check this before advising on cultivation. If the growth stage is missing, the reason is returned with it. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "facility_id": {"type": "string", "description": "Filter by facility unique_id."},
                "facility_name": {"type": "string", "description": "Filter by facility name. Omit for all."}
            }
        }
    },

    # ── (C) 오리엔테이션 + 의견 원장 ──────────────────────────────────────────
    {
        "tool_name": "get_system_brief",
        "description": "Start here. Returns what this farm is and how it is doing right now in one call - spatial hierarchy (site/zone/facility), crop and growth stage, active environment-control targets, current anomalies, device count and advice-ledger status. The how_to_proceed list at the end names the next tools to use in order. It does not replace the individual query tools; it tells you where to dig. Read-only.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "tool_name": "submit_advice",
        "description": "Submit advice grounded in observation to the advice ledger. Nothing is executed; a human reviews it. If you conclude control is needed, do not try to execute it - use this tool and put what should be done and why in proposed_action. That is the normal way to deliver advice in this system. Conflicting opinions are kept side by side rather than overwritten, so submit yours even if another AI disagrees.",
        "input_schema": {
            "type": "object",
            "properties": {
                "advice": {"type": "string", "description": "The advice itself. Required - what you observe and how you read it."},
                "title": {"type": "string", "description": "One-line title. If omitted, the first sentence of the body is used."},
                "rationale": {"type": "string", "description": "Evidence - which tool results or readings this is based on. This is what a human uses to weigh conflicting opinions."},
                "proposed_action": {"type": "string", "description": "Suggested action, in natural language. It is not executed."},
                "scope_type": {"type": "string", "description": "Target scope: system | farm | zone | facility | device (default system)."},
                "scope_id": {"type": "string", "description": "unique_id of the target. Set it whenever you can - advice with no target is hard to compare."},
                "severity": {"type": "string", "description": "info | advice | warning | urgent (default info)."},
                "confidence": {"type": "number", "description": "Self-assessed confidence, 0.0-1.0."},
                "agent_kind": {"type": "string", "description": "main | external | subordinate (default external)."}
            },
            "required": ["advice"]
        }
    },
    {
        "tool_name": "list_advice",
        "description": "Read the advice ledger - opinions from the main AI, external AI and subordinate node AIs. Check it before submitting so you avoid duplicates and can point at where judgements differ. The response flags targets where more than one agent has advised. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scope_type": {"type": "string", "description": "Filter by scope: system | farm | zone | facility | device."},
                "scope_id": {"type": "string", "description": "Filter by target unique_id."},
                "status": {"type": "string", "description": "pending | accepted | rejected | superseded"},
                "agent_id": {"type": "string", "description": "Filter by a particular submitter."},
                "severity": {"type": "string", "description": "Filter by severity."},
                "limit": {"type": "integer", "description": "Maximum number of results (default 20, max 100)."}
            }
        }
    },
]


# ---------------------------------------------------------------------------
# Derivations — the five consumers read these instead of hand-maintaining sets.
# ---------------------------------------------------------------------------
def build_tool_map() -> Dict[str, Any]:
    """name → bound AoTDataToolService handler, for VirtualToolResolver dispatch.
    Only tools with a `handler` are included (registry-only names are excluded)."""
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    out: Dict[str, Any] = {}
    for t in TOOLS:
        if t.handler:
            fn = getattr(AoTDataToolService, t.handler, None)
            if fn is None:
                raise AttributeError(
                    f"tool_registry: AoTDataToolService has no handler '{t.handler}' for tool '{t.name}'")
            out[t.name] = fn
    return out


def virtual_tool_registry() -> frozenset:
    """The known-name validation gate consumed by AIActionService.resolve_action."""
    return frozenset(t.name for t in TOOLS if t.registry)


def virtual_approval_tools() -> frozenset:
    """Mutating virtual tools that require human approval at DISPATCH
    (ai_dispatch_service._VIRTUAL_APPROVAL_TOOLS). Physical control is gated
    separately by the P4 hard gate, so it is NOT included here."""
    return frozenset(t.name for t in TOOLS if t.mutating)


def approval_required_tools() -> frozenset:
    """Tools the PLANNER executor must intercept as pending_approval
    (ai_planning_service._APPROVAL_REQUIRED_TOOLS): every mutation PLUS the
    physical-control / scheduling tools."""
    return frozenset(t.name for t in TOOLS if t.mutating or t.physical)


def manifest_system_tools() -> List[Dict[str, Any]]:
    """The system_tools list for get_action_manifest — emitted in declaration
    order, byte-identical to the original hand-written entries."""
    return [dict(t.manifest) for t in TOOLS if t.manifest]


def virtual_tools() -> List[Dict[str, Any]]:
    """The MCP tool catalog ({tool_name, description, input_schema}, in order)
    consumed by the mcp_aot engine and the stdio MCP server — replaces the
    hand-maintained VIRTUAL_TOOLS list. Every advertised tool is cross-checked
    against TOOLS so it is guaranteed dispatchable: a payload whose tool_name is
    unknown, or maps to a Tool without a handler, raises instead of silently
    advertising a tool the server would reject with 'Unknown tool'."""
    out: List[Dict[str, Any]] = []
    for payload in _MCP_TOOL_PAYLOADS:
        name = payload.get("tool_name")
        tool = _BY_NAME.get(name)
        if tool is None:
            raise ValueError(
                f"tool_registry: MCP payload '{name}' has no matching Tool declaration")
        if not tool.handler:
            raise ValueError(
                f"tool_registry: MCP tool '{name}' is advertised but has no handler "
                f"(would be non-dispatchable)")
        # Deep-ish copy so callers can't mutate the SSOT (input_schema is nested).
        out.append({
            "tool_name": name,
            "description": payload["description"],
            "input_schema": copy.deepcopy(payload["input_schema"]),
        })
    return out
