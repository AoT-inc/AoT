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

# 승인 면제 (2026-08-07, 사용자 결정). koat 감사 로그 하루치: 쓰기 33건 중 실제로
# 장비를 움직인 것은 2건뿐이고 나머지는 전부 시퀀스 설정 편집이었다 — 승인 클릭
# 21번 중 19번이 "물이 흐르지 않는 편집"에 쓰였다. 게이트가 읽기/쓰기 이분법이라
# 단계 순서 바꾸기와 밸브 열기가 같은 무게를 받았고, 그 마찰이 실제로 잘못된 우회를
# 낳은 적도 있다(요일이 다르다는 이유로 시퀀스를 새로 만든 사건).
#
# 이 도구들만으로는 어떤 장비도 움직이지 않는다 — 편집이 실제로 도는 시점은
# activate_function 을 지나야 하고 그 활성화는 계속 승인 대상이다.
# **알고 받아들인 절충**: 이미 활성 상태인 시퀀스의 시간표를 고치면 오늘 밤 관수
# 시각이 승인 없이 바뀐다. 되돌리려면 tool_registry 에서 config_only 를 떼면 된다.
#
# 여기에 이름을 추가하는 것은 **승인 요구를 없애는 안전 결정**이다.
# 삭제(delete_*)와 활성/비활성(activate_/deactivate_)은 절대 넣지 말 것 —
# 전자는 복구 불가능하고 후자가 바로 "물이 흐르기 시작하는" 순간이다.
_CONFIG_ONLY_APPROVAL_EXEMPTIONS = {'modify_sequence_schedule',
                                    'modify_sequence_step',
                                    'configure_sequence_day',
                                    'create_sequence_function',
                                    'modify_function_options'}

# ---------------------------------------------------------------------------
# 이름 휴리스틱 가드 — 위 스냅샷들이 못 잡는 구멍을 메운다.
#
# 스냅샷은 **이미 누군가 판단한 도구만** 고정한다. 새 도구를 넣으면서 스냅샷을
# 함께 갱신하면 검사는 통과한다 — 그 도구가 mutating/physical 선언을 빠뜨려
# 승인 없이 도는 쓰기가 되어도 마찬가지다. 스냅샷 갱신이 곧 "판단했다"는
# 증거는 아니기 때문이다.
#
# 그래서 선언과 무관하게 **이름만 보고** 한 번 더 본다. 이름이 쓰기형인데
# mutating/physical 이 둘 다 없으면, 스냅샷을 아무리 맞춰도 여기서 걸린다.
#
# 휴리스틱의 한계는 분명하다 — 접두사에 안 걸리는 쓰기 도구
# (knowledge_shelve 가 그런 경우)는 이름만으로는 못 잡는다. 그래서 면제 목록은
# "접두사에 걸렸지만 봐준 것"이 아니라 **의도적으로 승인을 안 받는 쓰기 도구
# 전체 명부**로 둔다. 한 곳에서 다 보이는 편이 낫다.
_WRITE_NAME_PREFIXES = (
    'create_', 'delete_', 'set_', 'modify_', 'update_', 'add_', 'edit_',
    'configure_', 'activate_', 'deactivate_', 'respond_', 'submit_',
    'archive_', 'restore_', 'operate_', 'schedule_',
)

# 여기에 이름을 넣는 것은 **승인 요구를 없애는 안전 결정**이다. 스냅샷 갱신과
# 같은 무게로 다룰 것 — 근거를 주석으로 남기고, 되돌릴 수 있는 저위험 쓰기에만
# 쓴다. 물리 제어나 엔티티 설정 변경은 절대 여기에 오면 안 된다.
#
# - create_note      (2026-07-18): 사용자가 직접 적어달라고 한 사적인 메모.
#                    승인 큐에 태웠더니 저장이 조용히 누락되고 "기술적 오류"로
#                    표면화됐다. 공개 게시물인 create_notice 는 계속 게이트 대상.
# - knowledge_shelve (2026-07-19): 항상 최하위 신뢰 등급(provenance='ai_curated',
#                    unconfirmed)으로만 쓰며, 사람이 확인하기 전까지 권위를 갖고
#                    제시되지 않는다.
# - submit_advice               : AI가 '의견을 말하는 것'에까지 승인을 요구하면
#                    조언 원장의 존재 이유가 사라진다. 승인 대상은 실행이지 제안이 아니다.
_INTENTIONALLY_UNGATED_WRITE_TOOLS = {
    'create_note',
    'knowledge_shelve',
    'submit_advice',
}

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

# 공간-장치 바인딩 (2026-08-08, Phase D). list_unbound_slots 는 읽기;
# rebind_device 는 "이 구역에 물을 주는 기계"를 바꾸므로 승인 필수이며
# config_only 면제 대상이 절대 아니다(설계 문서 Phase D).
_GEO_BINDING_TOOL_ADDITIONS = {'list_unbound_slots', 'rebind_device'}

# 식생 구획(작기) — docs/design/geo-vegetation-planting.md (2026-08-13).
# "어디에 무엇이 심겨 있는가" 는 재배 조언의 전제인데, 시설(crop_preset /
# facility_registry) 외에는 AI 가 알 방법이 없었다. 읽기 3 + 쓰기 4.
_PLANTING_READ_TOOL_ADDITIONS = {
    'list_plantings', 'get_planting', 'get_planting_history',
    # propose_planting_split (2026-08-14): 계산만 하고 아무것도 만들지 않는다.
    'propose_planting_split',
}
# 쓰기 4종은 전부 승인 대상이다. config_only 로 면제하지 말 것 — end/delete 는
# 되돌릴 수단이 없고(그 자리의 이력이 사라진다), create/modify 는 사람이 밭에서
# 확인해야 하는 사실을 기록하는 행위다.
_PLANTING_WRITE_TOOL_ADDITIONS = {
    'create_planting', 'modify_planting', 'end_planting', 'delete_planting',
    # copy_planting (2026-08-14): 구현은 planting_io 와 REST 에 있었는데 AI
    # 도구로만 없었다. "작년 그 자리에 또" 는 가장 흔한 요청이고 좌표가 하나도
    # 필요 없는 유일한 생성 경로다 — LLM 은 구역이 지도 어디인지 알 방법이
    # 없으므로(어떤 도구도 경계 폴리곤을 안 내준다) 이 길이 없으면 좌표를
    # 지어내게 된다. 쓰기이므로 승인 대상.
    'copy_planting',
    # apply_planting_split (2026-08-14): 분할 제안을 실제 구획으로 만든다.
    # 조각마다 GeoPlanting 한 행이 생기므로 쓰기이고 승인 대상.
    'apply_planting_split',
}
_GEO_BINDING_MUTATING_ADDITIONS = {'rebind_device'}

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


def run(check_dispatch: bool = True):
    """check_dispatch=False 면 tool_map 검사를 건너뛴다.

    tool_map 검사만이 실제 핸들러를 필요로 한다 — build_tool_map() 이
    AoTDataToolService 를 import 하고, 그 사슬이 서드파티 17개(flask/sqlalchemy/
    shapely/Pyro5 …)를 끌어온다. 나머지 검사는 전부 선언만 읽으므로 표준
    라이브러리만으로 돈다.

    **승인 게이팅 검사가 설치 실패에 가려지면 안 된다.** 그래서 CI 는 잡을
    나눠 게이팅 쪽을 의존성 없이 먼저 돌린다 — geo-integrity 가 무거운 설치
    하나 때문에 통째로 가려졌던 것과 같은 실패를 피하려는 것이다.
    """
    from aot.ai.services import tool_registry as R

    print("=== SSOT tool_registry derivations vs pre-refactor snapshots ===")

    # 1. tool_map keys — original PLUS documented post-Phase-1 additions.
    #    (핸들러 import 가 필요한 유일한 검사)
    _check_dispatch_map(R) if check_dispatch else print("  --  tool_map keys: 건너뜀 (--no-dispatch)")

    _check_declarations(R)


def _check_dispatch_map(R):
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
           | _ADAPTIVE_STORAGE_READ_TOOL_ADDITIONS | _ADAPTIVE_STORAGE_WRITE_TOOL_ADDITIONS
           | _GEO_BINDING_TOOL_ADDITIONS
           | _PLANTING_READ_TOOL_ADDITIONS | _PLANTING_WRITE_TOOL_ADDITIONS,
           set(R.build_tool_map().keys()))


def _check_declarations(R):
    """선언만 읽는 검사들 — 서드파티 의존성 없이 돈다."""
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
           | _ADAPTIVE_STORAGE_READ_TOOL_ADDITIONS | _ADAPTIVE_STORAGE_WRITE_TOOL_ADDITIONS
           | _GEO_BINDING_TOOL_ADDITIONS
           | _PLANTING_READ_TOOL_ADDITIONS | _PLANTING_WRITE_TOOL_ADDITIONS,
           set(R.virtual_tool_registry()))

    # 4. dispatch approval set — original PLUS the mutating post-Phase-1 additions,
    #    MINUS the config_only exemptions.
    _check("_VIRTUAL_APPROVAL_TOOLS",
           (_ORIG_VIRTUAL_APPROVAL_TOOLS | _POST_PHASE1_MUTATING_ADDITIONS | _SFK_AI_MUTATING_ADDITIONS
            | _SEQUENCE_SCHEDULE_TOOL_ADDITIONS
            | _SCHEDULE_CRUD_MUTATING_ADDITIONS | _GIS_INPUT_CRUD_MUTATING_ADDITIONS
            | _CONFIRMATION_RELAY_MUTATING_ADDITIONS | _ADAPTIVE_STORAGE_WRITE_TOOL_ADDITIONS
            | _GEO_BINDING_MUTATING_ADDITIONS | _PLANTING_WRITE_TOOL_ADDITIONS)
           - _CONFIG_ONLY_APPROVAL_EXEMPTIONS,
           set(R.virtual_approval_tools()))

    # 5. planner approval set — original PLUS the same mutating additions PLUS the
    #    one new `physical` (not `mutating`) scheduling tool, add_schedule_batch,
    #    MINUS the config_only exemptions.
    _check("_APPROVAL_REQUIRED_TOOLS",
           (_ORIG_APPROVAL_REQUIRED_TOOLS | _POST_PHASE1_MUTATING_ADDITIONS | _SFK_AI_MUTATING_ADDITIONS
            | _SEQUENCE_SCHEDULE_TOOL_ADDITIONS
            | _SCHEDULE_CRUD_MUTATING_ADDITIONS | _GIS_INPUT_CRUD_MUTATING_ADDITIONS
            | _CONFIRMATION_RELAY_MUTATING_ADDITIONS | _ADAPTIVE_STORAGE_WRITE_TOOL_ADDITIONS
            | _GEO_BINDING_MUTATING_ADDITIONS | _SCHEDULE_BATCH_PHYSICAL_ADDITIONS
            | _PLANTING_WRITE_TOOL_ADDITIONS)
           - _CONFIG_ONLY_APPROVAL_EXEMPTIONS,
           set(R.approval_required_tools()))

    # 5b. 면제는 승인에서만 빠지고 '쓰기'에서는 빠지지 않는다. 이게 무너지면
    #     읽기 전용 키가 설정을 고칠 수 있게 되므로 따로 못 박아 둔다.
    missing_from_write = _CONFIG_ONLY_APPROVAL_EXEMPTIONS - set(R.write_tools())
    if missing_from_write:
        raise AssertionError(
            f"config_only tools dropped out of write_tools(): {sorted(missing_from_write)} — "
            "they would stop being role-checked and stop being audited as writes")
    if set(R.config_only_tools()) != _CONFIG_ONLY_APPROVAL_EXEMPTIONS:
        raise AssertionError(
            "config_only_tools() drifted from the snapshot:\n"
            f"  derived : {sorted(R.config_only_tools())}\n"
            f"  snapshot: {sorted(_CONFIG_ONLY_APPROVAL_EXEMPTIONS)}\n"
            "Exempting a tool from approval is a safety decision — update the snapshot "
            "deliberately, with a dated reason.")
    print(f"  OK  config_only exemptions: {len(_CONFIG_ONLY_APPROVAL_EXEMPTIONS)} tools, "
          f"all still classified as writes")

    test_write_tools_are_gated()

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


def test_write_tools_are_gated():
    """이름이 쓰기형인 도구는 mutating/physical 을 선언해야 한다.

    스냅샷 검사와 독립적이다. 스냅샷은 갱신하면 통과하지만 이 검사는 갱신으로
    통과시킬 수 없다 — 통과하려면 도구에 선언을 붙이거나, 승인을 안 받겠다는
    결정을 _INTENTIONALLY_UNGATED_WRITE_TOOLS 에 근거와 함께 명시해야 한다.
    """
    from aot.ai.services import tool_registry as R

    declared = {t.name for t in R.TOOLS}

    # 1) 이름은 쓰기형인데 선언이 없는 도구.
    ungated = sorted(
        t.name for t in R.TOOLS
        if t.name.startswith(_WRITE_NAME_PREFIXES)
        and not (t.mutating or t.physical)
        and t.name not in _INTENTIONALLY_UNGATED_WRITE_TOOLS
    )
    if ungated:
        raise AssertionError(
            "이름이 쓰기형인데 mutating=/physical= 선언이 없는 도구: "
            f"{ungated}\n"
            "  선언을 붙이거나, 승인을 안 받겠다는 결정이라면 "
            "_INTENTIONALLY_UNGATED_WRITE_TOOLS 에 근거를 적어 넣을 것. "
            "후자는 승인 요구를 없애는 안전 결정이다.")

    # 2) 면제 명부에 남아 있는 유령 이름. 도구가 이름이 바뀌거나 사라지면
    #    면제만 남아, 나중에 같은 이름의 새 도구가 아무 검토 없이 면제를
    #    물려받는다.
    stale = sorted(_INTENTIONALLY_UNGATED_WRITE_TOOLS - declared)
    if stale:
        raise AssertionError(
            f"_INTENTIONALLY_UNGATED_WRITE_TOOLS 에 존재하지 않는 도구: {stale}\n"
            "  이름이 바뀌었거나 삭제된 것이다. 면제를 함께 지울 것 — "
            "남겨두면 같은 이름의 새 도구가 검토 없이 면제를 물려받는다.")

    # 3) 면제 명부의 도구가 실제로 승인 집합 밖에 있는지. 명부에는 있는데
    #    선언이 mutating 이면 서로 모순이다.
    contradictory = sorted(
        n for n in _INTENTIONALLY_UNGATED_WRITE_TOOLS
        if n in R.approval_required_tools()
    )
    if contradictory:
        raise AssertionError(
            f"면제 명부에 있으면서 승인 대상이기도 한 도구: {contradictory}\n"
            "  둘 중 하나가 틀렸다. 명부에서 빼거나 선언을 떼거나.")

    print(f"  OK  write-name gating: {len(_WRITE_NAME_PREFIXES)} prefixes checked, "
          f"{len(_INTENTIONALLY_UNGATED_WRITE_TOOLS)} deliberate exemptions, no gaps")


if __name__ == '__main__':
    import sys
    run(check_dispatch='--no-dispatch' not in sys.argv)
