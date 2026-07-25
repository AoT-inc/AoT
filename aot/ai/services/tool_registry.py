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
        "usage_hint": "For a DATED work task/event (weeding, spraying, harvest, inspection) use this — it registers a human work item. Params: {date, content, worker, time, tags, target_name}. PASS target_name (a zone/facility/device name like '온실', '3-1', '1포장 1-1') whenever the user names a place, so the schedule links to that real location (map + location search). If the name is ambiguous/not found the tool returns available_targets — call ask_user to pick, then retry. Omit target_name only for a farm-wide event with no specific place. For an undated memo/note, use create_note instead.",
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
        "description": "Search for Input/Output/Camera/Zone devices by name or type keyword.",
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
        "usage_hint": "params.arguments: {note (content, required), name (optional short title), target_name (location/entity name to attach to, e.g. '1포장 1-1' — STRONGLY preferred so the note is visible), tags (optional), category (optional, default 'general'). Advanced: target_id/target_type instead of target_name if the unique_id is already known. If target_name can't be resolved the tool returns available_targets — retry with an exact name.",
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
        "tool_name": "search_devices",
        "description": "Search for devices (inputs, outputs, cameras) by name or type keyword.",
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
        "description": "List all registered devices (inputs, outputs, cameras) in the AoT system. Use this when the user asks for a full device listing without a specific keyword.",
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
        "description": "[일반 작업/메모 기록용] 사람이 수행할 작업 일정이나 메모를 기록합니다. 제초작업, 점검, 청소 등 수동 작업에 사용하세요. 시스템 제어(밸브, 펌프 등)는 schedule_device_control을 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Target date (YYYY-MM-DD)"},
                "time": {"type": "string", "description": "Target time (HH:MM). Default '09:00'"},
                "content": {"type": "string", "description": "Description of the work or schedule"},
                "worker": {"type": "string", "description": "Name of the person assigned (optional)"},
                "tags": {"type": "string", "description": "Comma-separated tags (optional). If not provided, spatial tags are automatically extracted from content."}
            },
            "required": ["date", "content"]
        }
    },
    {
        "tool_name": "search_notes",
        "description": "[노트 읽기] 노트·메모·작업기록을 조회합니다. 읽기 전용이라 승인 불필요(요약은 데이터 가공). 특정 구역·장치에 붙은 노트를 읽거나 요약하려면(예: '3-1 구역 노트 요약') 반드시 target_name에 그 위치/장치 이름을 넣으세요 — 노트는 target_id로 엔티티에 붙어 있고 본문에 구역명이 없을 수 있어 키워드 검색으로는 못 찾습니다. target_name이 포장(site)이면 그 하위 모든 구역(zone)의 노트도 함께 반환됩니다(결과의 target_name으로 어느 구역인지 구분). query는 자유 키워드 검색용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "노트가 붙은 위치/장치 이름(예: '3-1', '1포장 1-1', '밸브1'). 구역·장치 노트 조회/요약 시 사용."},
                "query": {"type": "string", "description": "자유 키워드 검색(예: '콩밭', '제초'). target_name과 함께 주면 그 엔티티 내 추가 필터."},
                "category": {"type": "string", "description": "카테고리 필터: 'schedule'(일정), 'general'(일반) 등. 생략 시 전체."},
                "limit": {"type": "integer", "description": "최대 반환 건수 (기본 10)"}
            }
        }
    },
    {
        "tool_name": "schedule_device_control",
        "description": "[시스템 제어 예약 전용] 밸브, 펌프, 스프링클러 등 시스템 장치의 제어를 특정 시간에 예약합니다. 사용자 승인 후 스케줄러에 등록됩니다.",
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
        "description": "포장 또는 구역의 현재 기상 정보를 조회합니다. 기온, 습도, 풍속, 강수량, 날씨 상태를 반환합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_name": {
                    "type": "string",
                    "description": "조회할 포장 또는 구역 이름 (예: '1포장', '2포장'). zone_id 대신 사용 가능."
                },
                "zone_id": {
                    "type": "string",
                    "description": "GeoShape의 unique_id. zone_name 대신 사용 가능."
                }
            }
        }
    },
    {
        "tool_name": "get_cumulative_status",
        "description": "EnvCoordinator 함수의 DLI(일적산광량)·GDD(누적온도) 일별 누적 상태와 부채 현황을 조회합니다. 광량·온도 목표 달성 여부와 보상 제안을 확인할 때 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {
                    "type": "string",
                    "description": "EnvCoordinator 함수의 unique_id"
                },
                "days": {
                    "type": "integer",
                    "description": "조회할 최근 일수 (기본값: 7)"
                }
            },
            "required": ["function_id"]
        }
    },
    {
        "tool_name": "get_system_update_status",
        "description": "AoT 소프트웨어(시스템)의 업데이트 가용 여부를 확인합니다. 현재 설치 버전을 GitHub 최신 릴리스와 비교하여 반환합니다. 사용자가 '시스템 업데이트', '새 버전', '현재 버전'을 물으면 사용하세요. 읽기 전용.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "tool_name": "create_note",
        "description": "메모/노트를 즉시 생성·저장합니다(날짜 없는 메모 — 날짜 있는 작업은 add_schedule 사용). 승인 불필요. AoT에는 '노트 위젯' 같은 건 없고, 모든 장치·대지·구역 도형마다 각자의 노트가 있어 엔티티별로 조회됩니다. 노트는 대상에 부착되어야만 그 엔티티에서 보입니다. 따라서 사용자가 '1포장 1-1에', '밸브1에' 기록해달라고 하면 반드시 target_name에 그 위치/장치 이름을 넣으세요(도구가 실제 대상으로 해석해 부착). '생성하겠습니다'라고 말만 하지 말고 이 도구를 실제로 호출하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "노트 본문 내용"},
                "name": {"type": "string", "description": "노트 제목(짧게). 선택."},
                "target_name": {"type": "string", "description": "노트를 붙일 위치/장치 이름(예: '1포장 1-1', '밸브1'). 도구가 unique_id로 해석해 부착. 노트가 보이려면 강력 권장."},
                "tags": {"type": "string", "description": "태그(쉼표 구분). 선택."},
                "category": {"type": "string", "description": "분류(기본 'general'). 선택."},
                "target_id": {"type": "string", "description": "이미 아는 경우 대상 unique_id 직접 지정(target_name 대신). 선택."},
                "target_type": {"type": "string", "description": "연결 대상 유형(예: 'zone','input','output'). 선택."}
            },
            "required": ["note"]
        }
    },
    {
        "tool_name": "list_notices",
        "description": "공지사항 게시글 목록(제목·고정·날짜)을 조회합니다. 읽기 전용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "최대 반환 건수(기본 10)"}
            }
        }
    },
    {
        "tool_name": "get_facility_capacity",
        "description": "geo/design(지도)에서 그린 시설(온실/구조물)의 설계 산출 성능·용량을 반환한다: 냉난방 참조 용량(kW), 바닥/체적/피복 면적, 환기(ACH·개구부 m²), 관수 요약(배관·에미터 수·유량 L/min), 바인딩된 제어장치 수. 읽기 전용 — 요청 시 산출되는 공학적 참조 추정치(±5~10%). 용량 적정성/설계 질의('냉방 충분한가?', '관수 유량은?', '난방 용량')에 사용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "facility_name": {"type": "string", "description": "시설 이름(예: '육묘장'). 생략하면 전체 시설 반환."}
            }
        }
    },
    {
        "tool_name": "get_map_equipment",
        "description": "geo/design 지도에 그린 설비와 구역별 관수 설계 요약을 반환한다. 제어장치(Output)와 별개. 중요 — 관수 방식 두 가지를 정확히 구분하고 절대 하나의 'emitter'로 합치지 말 것: `sprinklers`(스프링클러 — 개별 살수 헤드, 각 살수반경+유량) vs `drip_emitters`(점적 — 점적배관 길이÷간격으로 산출). `method`=sprinkler|drip|mixed. 개별 장비(관수밸브·환기팬·난방/냉방기·창호/커튼 모터)는 스펙(flow_lph·pressure_kpa·capacity_kw·airflow_cmh·power_w)과 함께. 읽기 전용. '무슨 관수장치/설비가 있나', 'X구역 유량/스프링클러/점적/배관' 질의에 사용. 스프링클러와 점적을 따로 보고. (온실의 계산된 냉난방 설계 용량은 get_facility_capacity.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "area_name": {"type": "string", "description": "사이트/구역 이름(예: '1-1'). 생략하면 지도 전체."}
            }
        }
    },
    {
        "tool_name": "get_map_equipment_detail",
        "description": "get_map_equipment 요약의 한 단계 아래 지오메트리 상세(한 구역) — 개별 스프링클러 헤드 위치(lat/lng)·반경·유량, 계산된 스프링클러 간격(인접 중앙값), 점적은 배관별 간격·점적기 수, 배관별 길이·시작/끝 좌표. 스프링클러와 점적을 분리 유지. 읽기 전용. 요약으로 답 안 되는 구체 질의(정확한 위치, 간격, 반경, 특정 배관)일 때만 호출. 개수·총유량·총길이는 요약으로 충분.",
        "input_schema": {
            "type": "object",
            "properties": {
                "area_name": {"type": "string", "description": "사이트/구역 이름(예: '1-1'). 필수."}
            },
            "required": ["area_name"]
        }
    }
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
