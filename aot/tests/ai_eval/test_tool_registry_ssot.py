# coding=utf-8
"""
Characterization test for the SSOT tool registry (architecture Phase 1).

Pins the PRE-refactor hand-maintained sets as literal snapshots and asserts the
registry derivations reproduce them 1:1 — so the "derive all five from one
declaration" refactor is provably value-preserving. The single intended change
(a drift FIX) is asserted explicitly, not hidden.

Runnable without a DB or credentials — the registry and its derivations are pure
Python (build_tool_map() only does getattr on AoTDataToolService, no DB). Run:
    python -m aot.tests.ai_eval.test_tool_registry_ssot
Exits non-zero on any mismatch.
"""

# --- Snapshots of the five sync points as they were BEFORE Phase 1 -----------

# 1. Resolver tool_map keys (virtual_tool_resolver.py) — 38 names.
_ORIG_TOOL_MAP_KEYS = {
    'get_sensor_detail', 'get_spatial_tree', 'search_devices', 'get_device_list',
    'search_notes', 'get_energy_report', 'operate_device', 'add_schedule',
    'schedule_device_control', 'get_weather', 'get_function_list', 'get_function_detail',
    'activate_function', 'deactivate_function', 'get_active_functions_summary',
    'create_function', 'create_sequence_function', 'modify_function_options',
    'delete_function', 'get_device_measurements', 'list_device_types',
    'get_device_type_options', 'create_input', 'modify_input', 'delete_input',
    'create_output', 'modify_output', 'delete_output', 'list_geo_maps',
    'get_device_location', 'set_device_location', 'delete_geo_shape', 'list_ai_agents',
    'list_ai_entries', 'create_ai_agent', 'modify_ai_agent', 'delete_ai_agent',
    'get_cumulative_status',
}

# 2. VIRTUAL_TOOL_REGISTRY (ai_action_service.py) — 49 names, PRE-fix (note the
#    absence of get_weather / get_cumulative_status — the drift Phase 1 fixes).
_ORIG_VIRTUAL_TOOL_REGISTRY = {
    'add_schedule', 'schedule_device_control', 'get_sensor_detail', 'get_spatial_tree',
    'search_devices', 'get_device_list', 'search_notes', 'get_energy_report',
    'get_detailed_manifest', 'read_manual', 'abstract_plan', 'note', 'function', 'pid',
    'operate_device', 'analyze_system_failure', 'get_sensor_reading',
    'list_available_devices', 'set_output_state', 'get_function_list',
    'get_function_detail', 'get_function_doc', 'get_input_doc', 'get_output_doc',
    'activate_function', 'deactivate_function', 'get_active_functions_summary',
    'get_device_measurements', 'create_function', 'create_sequence_function',
    'modify_function_options', 'delete_function', 'list_device_types',
    'get_device_type_options', 'create_input', 'modify_input', 'delete_input',
    'create_output', 'modify_output', 'delete_output', 'list_geo_maps',
    'get_device_location', 'set_device_location', 'delete_geo_shape', 'list_ai_agents',
    'list_ai_entries', 'create_ai_agent', 'modify_ai_agent', 'delete_ai_agent',
}

# The intended, documented drift FIX: two dispatchable handlers that were missing
# from the validation gate and would raise InvalidToolError in resolve_action.
_INTENDED_REGISTRY_ADDITIONS = {'get_weather', 'get_cumulative_status'}

# Post-Phase-1 additions (2026-07-08): Notice board CRUD + a plain Notes create
# tool, declared once in tool_registry.py — SSOT paid for itself here, since
# adding a tool is now ONE Tool(...) entry instead of hand-syncing 5 places.
# list_notices is read-only (not in the approval sets); the notice writes mutate.
# create_note is a tool_map/registry addition but NOT approval-gated as of
# 2026-07-18 (a private, reversible memo the user directly requested saves
# immediately — see tool_registry NOTE_CREATE_TOOL comment). create_notice
# (public board post) remains mutating/approval-gated.
_POST_PHASE1_TOOL_ADDITIONS = {
    'list_notices', 'create_notice', 'modify_notice', 'delete_notice', 'create_note',
}
_POST_PHASE1_MUTATING_ADDITIONS = {
    'create_notice', 'modify_notice', 'delete_notice',
}

# Agent loop redesign, Phase 1 (2026-07-19, docs/design/ai-agent-loop.md).
# get_tool_detail is a normal read-only virtual tool (handler → tool_map).
# ask_user is registry-only (handler=None, like read_manual/get_detailed_manifest)
# — the agent loop intercepts it directly, so it's NOT in tool_map, and it is
# NOT mutating/physical (asking a question has no side effect).
_AGENT_LOOP_TOOL_ADDITIONS = {'get_tool_detail', 'ask_user'}
_AGENT_LOOP_TOOL_MAP_ADDITIONS = {'get_tool_detail'}

# Phase 2 (2026-07-19, docs/design/ai-agent-loop.md §Phase2): reconnect
# analyze_system_failure (implementation existed; handler=None left it
# dispatch-invisible AND manifest-invisible — now both) + register
# knowledge_search as a real tool (previously only a legacy action_type
# invoked via a prompt instruction, never a tool_name the catalog could
# offer). Both read-only — no approval-set changes. analyze_system_failure
# was already in _ORIG_VIRTUAL_TOOL_REGISTRY (registry=True default even
# with handler=None), so only knowledge_search is a registry addition.
_PHASE2_TOOL_MAP_ADDITIONS = {'analyze_system_failure', 'knowledge_search'}
_PHASE2_REGISTRY_ADDITIONS = {'knowledge_search'}

# System update status tool (2026-07-18): read-only version/update check wired
# into the AI so "is there a system update?" is answerable. One Tool(...) entry;
# read-only, so it appears in tool_map + registry but neither approval set.
_UPDATE_STATUS_TOOL_ADDITIONS = {'get_system_update_status'}

# knowledge_shelve tool (2026-07-19, docs/design/ai-library-redesign.md §4): the
# write half of the AI library redesign. Same non-gated treatment as create_note
# (always writes at the lowest trust tier, never presented as authoritative) — a
# tool_map/registry addition, but NOT in either approval set.
_KNOWLEDGE_SHELVE_TOOL_ADDITIONS = {'knowledge_shelve'}

# SmartFarmKorea AI-driven setup (2026-07-19, docs/design/ai-library-redesign.md
# Phase 2): expose Phase 1's discovery primitive as two tools. lookup is
# read-only (tool_map + registry, no approval); configure_library_source
# mutates (creates a source + fetches external data) → both approval sets.
_SFK_AI_TOOL_ADDITIONS = {'smartfarmkorea_lookup', 'configure_library_source'}
_SFK_AI_MUTATING_ADDITIONS = {'configure_library_source'}

# Knowledge-library catalog tool (2026-07-19): read-only enumerator of the full
# LIBRARY_PRESETS catalog so the AI recommends every source type, not just
# SmartFarmKorea. tool_map + registry addition, no approval.
_LIBRARY_CATALOG_TOOL_ADDITIONS = {'list_library_source_types'}

# Sequence editing (2026-08-06). Three tools, all mutating → both approval sets.
# - configure_sequence_day: lays out one weekday's whole plan in a single call.
#   Doing it per step cost ~20 gated calls, and that friction pushed a caller
#   into building a redundant second sequence instead.
# - modify_sequence_schedule: modify_function_options writes custom_options, a
#   column Trigger does not have, so every sequence timing edit reported success
#   and changed nothing. It now refuses Triggers; this edits timer_schedule
#   (weekly_schedule v1) properly.
# - modify_sequence_step: create_sequence_function only lays down uniform steps
#   (one duration for all, always 'single', never grouped), so the AI could make
#   a sequence but not the shape real irrigation needs — valves opening together,
#   different durations per slot, a pump spanning the rest.
_SEQUENCE_SCHEDULE_TOOL_ADDITIONS = {'modify_sequence_schedule',
                                     'modify_sequence_step',
                                     'configure_sequence_day'}

# Scheduler CRUD close-out + per-location local time (2026-07-20, aa2c5bc
# "스케줄 원장 SchedulerJobMeta 일원화"): search/edit/delete_schedule complete
# the scheduler as a farm-operations ledger (@ANCHOR: SCHEDULE_CRUD_TOOLS);
# get_local_time (@ANCHOR: GET_LOCAL_TIME_TOOL) is unrelated but landed in the
# same commit. search_schedule and get_local_time are read-only; edit/delete
# mutate an existing schedule row → approval-gated.
_SCHEDULE_CRUD_TOOL_ADDITIONS = {'search_schedule', 'edit_schedule', 'delete_schedule'}
_SCHEDULE_CRUD_MUTATING_ADDITIONS = {'edit_schedule', 'delete_schedule'}
_LOCAL_TIME_TOOL_ADDITIONS = {'get_local_time'}

# geo/design facility performance + map-drawn equipment (2026-07-22, cc4c9a6
# "geo/design 설비 조회 도구 3종"): all three surface engineering reference
# data computed elsewhere (facility_calc, equipment_collection GeoShapes) —
# read-only, tool_map + registry only.
_FACILITY_MAP_TOOL_ADDITIONS = {
    'get_facility_capacity', 'get_map_equipment', 'get_map_equipment_detail',
}

# Reverse geocoding (2026-07-25, @ANCHOR: REVERSE_GEOCODE_TOOL): exposes the
# existing VWorld getAddress pipeline as a standalone lookup. Read-only.
_REVERSE_GEOCODE_TOOL_ADDITIONS = {'get_address'}

# GIS Input CRUD + scheduling batch + target resolution (2026-07-26, 6a0788a
# "외부 MCP 서버 사람 승인 게이트 + GIS 입력 CRUD + add_schedule_batch"):
# - GIS_INPUT_CRUD_TOOLS: map-layer/provider CRUD, same shape as Input/Output
#   CRUD — list is read-only, create/modify/activate/delete mutate.
# - add_schedule_batch is `physical` (like add_schedule), not `mutating` — a
#   scheduling tool, not an entity mutation, so it only joins the planner's
#   approval_required_tools (mutating OR physical), not the dispatch-only
#   virtual_approval_tools (mutating-only).
# - resolve_target is the read-only name-resolution primitive the batch/CRUD
#   tools' usage_hints tell the model to call first; no approval.
_GIS_INPUT_CRUD_TOOL_ADDITIONS = {
    'list_gis_inputs', 'create_gis_input', 'modify_gis_input',
    'activate_gis_input', 'delete_gis_input',
}
_GIS_INPUT_CRUD_MUTATING_ADDITIONS = {
    'create_gis_input', 'modify_gis_input', 'activate_gis_input', 'delete_gis_input',
}
_SCHEDULE_BATCH_TOOL_ADDITIONS = {'add_schedule_batch'}
_SCHEDULE_BATCH_PHYSICAL_ADDITIONS = {'add_schedule_batch'}
_TARGET_RESOLUTION_TOOL_ADDITIONS = {'resolve_target'}

# In-chat confirmation relay (2026-07-26, @ANCHOR: CONFIRMATION_RELAY_TOOLS):
# lets the human approve/reject a pending write from inside the chat instead
# of the web review page. list_pending_confirmations is a normal read-only
# virtual tool (tool_map + registry). respond_to_confirmation is registry-only
# (handler=None, like ask_user/read_manual — the dispatch layer intercepts it
# directly) but IS `mutating`: approving a confirmation triggers the write it
# was gating, so it must sit behind the same human-approval bookkeeping.
_CONFIRMATION_RELAY_TOOL_ADDITIONS = {'list_pending_confirmations', 'respond_to_confirmation'}
_CONFIRMATION_RELAY_TOOL_MAP_ADDITIONS = {'list_pending_confirmations'}
_CONFIRMATION_RELAY_MUTATING_ADDITIONS = {'respond_to_confirmation'}

# Advisory read tools + advice ledger + orientation brief (2026-07-26,
# @ANCHOR: ADVISORY_READ_TOOLS / ADVICE_LEDGER_TOOLS): read-only status tools
# an external advisory AI needs (control state, forecast, anomalies, crop
# status) plus the multi-AI opinion ledger. submit_advice writes a DB row but
# is deliberately NOT `mutating` — per the in-file comment, gating "the AI
# stating an opinion" behind human approval would defeat the ledger's purpose;
# only executions (operate_device etc.) need that gate. get_system_brief is
# the read-only orientation entry point. None are approval-gated.
_ADVISORY_READ_TOOL_ADDITIONS = {
    'get_control_state', 'get_weather_forecast', 'get_anomalies', 'get_crop_status',
}
_ADVICE_LEDGER_TOOL_ADDITIONS = {'submit_advice', 'list_advice'}
_SYSTEM_BRIEF_TOOL_ADDITIONS = {'get_system_brief'}

# Output current-state read tool (2026-07-28, b567814 "출력장치 현재 상태 읽기
# 도구 get_output_state 추가"). Read-only.
_OUTPUT_STATE_TOOL_ADDITIONS = {'get_output_state'}

# Adaptive document storage — read half (2026-08-04, 9c68ef2 "문서 스토리지
# 티어를 AI가 조회할 수 있게 (2/3)"). All three read tiering/archive state;
# read-only, tool_map + registry only.
_ADAPTIVE_STORAGE_READ_TOOL_ADDITIONS = {
    'get_storage_tier_status', 'search_archives', 'get_archived_document',
}

# Adaptive document storage — write half (2026-08-04, 8968d30 "스토리지 쓰기
# 도구 4종"). All four mutate archive/tier state → approval-gated.
_ADAPTIVE_STORAGE_WRITE_TOOL_ADDITIONS = {
    'archive_note', 'restore_note_from_archive', 'set_document_tier', 'delete_archive',
}

# 4. _VIRTUAL_APPROVAL_TOOLS (ai_dispatch_service.py) — 17 mutations, no physical.
_ORIG_VIRTUAL_APPROVAL_TOOLS = {
    'create_function', 'create_sequence_function', 'modify_function_options',
    'activate_function', 'deactivate_function', 'delete_function',
    'create_input', 'modify_input', 'delete_input',
    'create_output', 'modify_output', 'delete_output',
    'set_device_location', 'delete_geo_shape',
    'create_ai_agent', 'modify_ai_agent', 'delete_ai_agent',
}

# 5. _APPROVAL_REQUIRED_TOOLS (ai_planning_service.py) — the 17 mutations PLUS the
#    4 physical / scheduling tools.
_ORIG_APPROVAL_REQUIRED_TOOLS = _ORIG_VIRTUAL_APPROVAL_TOOLS | {
    'operate_device', 'set_output_state', 'schedule_device_control', 'add_schedule',
}


def _check(name, expected, actual):
    if expected != actual:
        missing = expected - actual
        extra = actual - expected
        raise AssertionError(
            f"{name} mismatch:\n  missing (in snapshot, not derived): {sorted(missing)}\n"
            f"  extra   (derived, not in snapshot): {sorted(extra)}")
    print(f"  OK  {name}: {len(actual)} entries match")


def run():
    from aot.ai.services import tool_registry as R

    print("=== SSOT tool_registry derivations vs pre-refactor snapshots ===")

    # 1. tool_map keys — original PLUS documented post-Phase-1 additions.
    _check("tool_map keys",
           _ORIG_TOOL_MAP_KEYS | _POST_PHASE1_TOOL_ADDITIONS | _UPDATE_STATUS_TOOL_ADDITIONS
           | _KNOWLEDGE_SHELVE_TOOL_ADDITIONS | _AGENT_LOOP_TOOL_MAP_ADDITIONS
           | _PHASE2_TOOL_MAP_ADDITIONS | _SFK_AI_TOOL_ADDITIONS | _LIBRARY_CATALOG_TOOL_ADDITIONS
           | _SEQUENCE_SCHEDULE_TOOL_ADDITIONS
           | _SCHEDULE_CRUD_TOOL_ADDITIONS | _LOCAL_TIME_TOOL_ADDITIONS
           | _FACILITY_MAP_TOOL_ADDITIONS | _REVERSE_GEOCODE_TOOL_ADDITIONS
           | _GIS_INPUT_CRUD_TOOL_ADDITIONS | _SCHEDULE_BATCH_TOOL_ADDITIONS
           | _TARGET_RESOLUTION_TOOL_ADDITIONS | _CONFIRMATION_RELAY_TOOL_MAP_ADDITIONS
           | _ADVISORY_READ_TOOL_ADDITIONS | _ADVICE_LEDGER_TOOL_ADDITIONS
           | _SYSTEM_BRIEF_TOOL_ADDITIONS | _OUTPUT_STATE_TOOL_ADDITIONS
           | _ADAPTIVE_STORAGE_READ_TOOL_ADDITIONS | _ADAPTIVE_STORAGE_WRITE_TOOL_ADDITIONS,
           set(R.build_tool_map().keys()))

    # 2. VIRTUAL_TOOL_REGISTRY — original PLUS the drift-fix PLUS post-Phase-1 additions.
    _check("VIRTUAL_TOOL_REGISTRY (drift-fixed)",
           _ORIG_VIRTUAL_TOOL_REGISTRY | _INTENDED_REGISTRY_ADDITIONS
           | _POST_PHASE1_TOOL_ADDITIONS | _UPDATE_STATUS_TOOL_ADDITIONS
           | _KNOWLEDGE_SHELVE_TOOL_ADDITIONS | _AGENT_LOOP_TOOL_ADDITIONS
           | _PHASE2_REGISTRY_ADDITIONS | _SFK_AI_TOOL_ADDITIONS | _LIBRARY_CATALOG_TOOL_ADDITIONS
           | _SEQUENCE_SCHEDULE_TOOL_ADDITIONS
           | _SCHEDULE_CRUD_TOOL_ADDITIONS | _LOCAL_TIME_TOOL_ADDITIONS
           | _FACILITY_MAP_TOOL_ADDITIONS | _REVERSE_GEOCODE_TOOL_ADDITIONS
           | _GIS_INPUT_CRUD_TOOL_ADDITIONS | _SCHEDULE_BATCH_TOOL_ADDITIONS
           | _TARGET_RESOLUTION_TOOL_ADDITIONS | _CONFIRMATION_RELAY_TOOL_ADDITIONS
           | _ADVISORY_READ_TOOL_ADDITIONS | _ADVICE_LEDGER_TOOL_ADDITIONS
           | _SYSTEM_BRIEF_TOOL_ADDITIONS | _OUTPUT_STATE_TOOL_ADDITIONS
           | _ADAPTIVE_STORAGE_READ_TOOL_ADDITIONS | _ADAPTIVE_STORAGE_WRITE_TOOL_ADDITIONS,
           set(R.virtual_tool_registry()))

    # 4. dispatch approval set — original PLUS the mutating post-Phase-1 additions.
    _check("_VIRTUAL_APPROVAL_TOOLS",
           _ORIG_VIRTUAL_APPROVAL_TOOLS | _POST_PHASE1_MUTATING_ADDITIONS | _SFK_AI_MUTATING_ADDITIONS
           | _SEQUENCE_SCHEDULE_TOOL_ADDITIONS
           | _SCHEDULE_CRUD_MUTATING_ADDITIONS | _GIS_INPUT_CRUD_MUTATING_ADDITIONS
           | _CONFIRMATION_RELAY_MUTATING_ADDITIONS | _ADAPTIVE_STORAGE_WRITE_TOOL_ADDITIONS,
           set(R.virtual_approval_tools()))

    # 5. planner approval set — original PLUS the same mutating additions PLUS the
    #    one new `physical` (not `mutating`) scheduling tool, add_schedule_batch.
    _check("_APPROVAL_REQUIRED_TOOLS",
           _ORIG_APPROVAL_REQUIRED_TOOLS | _POST_PHASE1_MUTATING_ADDITIONS | _SFK_AI_MUTATING_ADDITIONS
           | _SEQUENCE_SCHEDULE_TOOL_ADDITIONS
           | _SCHEDULE_CRUD_MUTATING_ADDITIONS | _GIS_INPUT_CRUD_MUTATING_ADDITIONS
           | _CONFIRMATION_RELAY_MUTATING_ADDITIONS | _ADAPTIVE_STORAGE_WRITE_TOOL_ADDITIONS
           | _SCHEDULE_BATCH_PHYSICAL_ADDITIONS,
           set(R.approval_required_tools()))

    # 3. manifest — every manifest entry names a known tool; the set of virtual-tool
    #    manifest names is a subset of the registry (no phantom manifest entries).
    manifest = R.manifest_system_tools()
    manifest_tool_names = {m['tool_name'] for m in manifest if 'tool_name' in m}
    unknown = manifest_tool_names - set(R.virtual_tool_registry())
    if unknown:
        raise AssertionError(f"manifest references tools not in registry: {sorted(unknown)}")
    print(f"  OK  manifest: {len(manifest)} entries, {len(manifest_tool_names)} virtual "
          f"tool names all in registry")

    # Every mutating/physical tool is a real dispatchable or known tool.
    for t in R.TOOLS:
        if t.handler is None and t.name not in R.virtual_tool_registry():
            raise AssertionError(f"tool '{t.name}' has no handler and is not in registry")

    print("\nALL SSOT DERIVATIONS MATCH (value-preserving; +2 intended registry drift fix).")


if __name__ == '__main__':
    run()
