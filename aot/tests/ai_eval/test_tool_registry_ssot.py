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
#
# create_program / modify_program (2026-08-24): 프로그램은 장치를 직접 움직이지
# 않는 참고자료다. 뗄 수 있는 근거는 위험이 작아서가 아니라 **더 강한 게이트가
# 뒤에 있어서다** — GeoProgram.usable_for_control() 이 source='ai' 를 reviewed_at
# 전까지 제어에서 배제하고, reviewed 는 by != 'ai' 조건 때문에 AI 가 스스로 세울
# 수 없다. 이 계약은 test_program_approval_contract.py 가 따로 붙들고 있다.
# delete_program 은 복구 불가라 위 금지 조항대로 승인 대상으로 남는다.
_CONFIG_ONLY_APPROVAL_EXEMPTIONS = {'modify_sequence_schedule',
                                    'modify_sequence_step',
                                    'configure_sequence_day',
                                    'create_sequence_function',
                                    'modify_function_options',
                                    'create_program',
                                    'modify_program'}

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
    # 프로그램(2026-08-24, 사용자 결정). 프로그램은 제어가 아니라 **제어에
    # 영향을 주는 참고자료**다 — 장치를 직접 움직이지 않고, 오래 두고 보는
    # 문서인데 만들 때마다 승인을 받게 하면 마찰만 남는다.
    #
    # 승인을 뗀 근거는 "위험이 작다" 가 아니라 **더 강한 게이트가 뒤에 있다**
    # 는 것이다: `GeoProgram.usable_for_control()` 이 `source='ai'` 프로그램을
    # `reviewed_at` 전까지 제어에서 배제하고 `coordinator_plot` 이 그 판정을
    # 실제로 본다. `program_io.update_program(by='ai')` 는 AI 가 단계·목표를
    # 쓸 때마다 그 상태로 되돌린다. 그리고 `reviewed` 는 `by != 'ai'` 조건 때문에
    # **AI 가 스스로 세울 수 없다** — activate_function 보다 강한 게이트다.
    # 자세한 대조는 tool_registry 의 _CONFIG_ONLY 주석(2026-08-24 항목).
    #
    # `delete_program` 은 뺐다 — 복구 불가라 _CONFIG_ONLY 금지 조항에 걸린다.
    'create_program',
    'modify_program',
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

# 식생 구획(작기) — docs/design/geo-vegetation-plot.md (2026-08-13).
# "어디에 무엇이 심겨 있는가" 는 재배 조언의 전제인데, 시설(crop_preset /
# facility_registry) 외에는 AI 가 알 방법이 없었다. 읽기 3 + 쓰기 4.
_PLANTING_READ_TOOL_ADDITIONS = {
    'list_plots', 'get_plot', 'get_plot_history',
    # propose_plot_split (2026-08-14): 계산만 하고 아무것도 만들지 않는다.
    'propose_plot_split',
}
# 쓰기 4종은 전부 승인 대상이다. config_only 로 면제하지 말 것 — end/delete 는
# 되돌릴 수단이 없고(그 자리의 이력이 사라진다), create/modify 는 사람이 밭에서
# 확인해야 하는 사실을 기록하는 행위다.
_PLANTING_WRITE_TOOL_ADDITIONS = {
    'create_plot', 'modify_plot', 'end_plot', 'delete_plot',
    # copy_plot (2026-08-14): 구현은 plot_io 와 REST 에 있었는데 AI
    # 도구로만 없었다. "작년 그 자리에 또" 는 가장 흔한 요청이고 좌표가 하나도
    # 필요 없는 유일한 생성 경로다 — LLM 은 구역이 지도 어디인지 알 방법이
    # 없으므로(어떤 도구도 경계 폴리곤을 안 내준다) 이 길이 없으면 좌표를
    # 지어내게 된다. 쓰기이므로 승인 대상.
    'copy_plot',
    # apply_plot_split (2026-08-14): 분할 제안을 실제 구획으로 만든다.
    # 조각마다 GeoPlot 한 행이 생기므로 쓰기이고 승인 대상.
    'apply_plot_split',
}

# 단계 전환·자원 (2026-08-19, P5~P7). 셋 다 승인 대상이다.
#
# - confirm_plot_stage / undo_plot_stage: **기준점을 옮긴다.** 이후 단계가 통째로
#   다시 계산되므로 "기록 하나 남기는 일" 이 아니다. 되돌리기가 있지만 마지막
#   것만 무를 수 있어, 잘못 확정하면 사람이 원장을 다시 정리해야 한다.
# - apply_plot_resources: **물이 나온다.** 그래서 `physical=True` 다 —
#   `activate_function` 이 승인 대상인 것과 같은 이유이고, 프로그램이 함수를
#   스스로 켜지 않기로 한 결정(P6)이 이 도구에서도 유지돼야 한다.
#   config_only 로 면제하지 말 것.
_PLOT_STAGE_TOOL_ADDITIONS = {
    'confirm_plot_stage', 'undo_plot_stage', 'apply_plot_resources',
}
# 단계 원장 편집 (2026-08-24, p6_56/p6_57). 다섯 종 전부 승인 대상이다.
#
# - reschedule_plot_stage / add_plot_stage / remove_plot_stage: 단계 자체를
#   고치므로 confirm_plot_stage 와 같은 급이다 — **기준점이 움직인다.** 뒤따르는
#   단계와 예상 수확일이 통째로 다시 계산되므로 config_only 로 면제하지 말 것.
# - set_plot_stage_guidance: 지침은 사람이 밭에서 할 일을 지시하는 문장이다.
#   모델이 그럴듯하게 지어낼 수 있는 값이라 사람이 읽고 넘겨야 한다.
# - save_plot_schedule_as_program: 구획의 일정을 재배 프로그램으로 굳힌다.
#   새 프로그램 행이 생기고 이후 다른 구획이 그것을 근거로 삼으므로,
#   create_program 이 승인 대상인 것과 같은 이유로 승인 대상이다.
_PLOT_STAGE_EDIT_TOOL_ADDITIONS = {
    'add_plot_stage', 'remove_plot_stage', 'reschedule_plot_stage',
    'set_plot_stage_guidance', 'save_plot_schedule_as_program',
}
# 연결된 조회 소스 (2026-08-24). 셋 다 읽기 전용이라 승인 집합에는 들어가지
# 않는다 — 등록해 둔 외부 API·참조표를 그때그때 물어보기만 하고, 무엇도
# 적재하거나 바꾸지 않는다.
_LOOKUP_SOURCE_READ_TOOL_ADDITIONS = {
    'list_lookup_sources', 'query_data_source', 'query_reference_table',
}
# 재배 프로그램 — docs/design/program-layer.md (2026-08-19, P3).
# 작물의 단계·기간 템플릿. 구획에 붙이면 단계·예상 수확일이 따라오므로, AI 가
# 구획을 만들 때 고를 수 있어야 하고(읽기 2) 없으면 만들 수 있어야 한다(쓰기 2).
_CROP_PROGRAM_READ_TOOL_ADDITIONS = {
    'list_programs', 'get_program',
}
# 쓰기 2종은 승인 대상이다. **config_only 로 면제하지 말 것** — 프로그램은 제어
# 목표의 근거가 되고, 단계 기간과 목표는 그럴듯하게 지어낼 수 있는 값이다.
# 별도의 안전장치가 하나 더 있다: 이렇게 만든 것은 `source='ai'` 라서 사람이
# 확인(reviewed_at)하기 전까지 제어에 쓰이지 않는다(모델 usable_for_control).
_CROP_PROGRAM_WRITE_TOOL_ADDITIONS = {
    'create_program', 'modify_program',
}
# delete_program(2026-08-20) — 승인 대상. `program_io.delete_program` 이
# 참조 무결성을 지킨다(쓰는 구획이 있으면 거절)는 것은 데이터 계층의 방어일
# 뿐 승인 생략의 근거가 아니다 — 삭제는 되돌릴 수 없는 동작이라 그 자체로
# 승인 대상이다.
_CROP_PROGRAM_DELETE_TOOL_ADDITIONS = {
    'delete_program',
}

# 범용 탭 도구(2026-08-21) — Dashboard/Input/Output/Function/Programs 가 공유하는
# `Tab`/`TabService` 위에 얹힌다. 이름은 하나뿐이라 page_type 인자로 페이지를
# 고른다. 쓰기 2종(create/modify)과 삭제 1종을 갈라 두는 것은 위 프로그램 도구와
# 같은 이유다 — 삭제는 되돌릴 수 없어 그 자체로 승인 대상이고, config_only 로
# 면제하지 않는다.
_TAB_READ_TOOL_ADDITIONS = {
    'list_tabs',
}
_TAB_WRITE_TOOL_ADDITIONS = {
    'create_tab', 'modify_tab',
}
_TAB_DELETE_TOOL_ADDITIONS = {
    'delete_tab',
}
# 대시보드 위젯 도구(2026-08-21) — 탭 도구와 같은 '화면 구성' 축이다. 읽기
# 3종은 승인 밖이고, 쓰기 3종은 전부 승인 대상이다. **물리 장치를 움직이지
# 않는다는 이유로 config_only(승인 면제)에 넣지 않았다**: 면제의 근거는 "아무
# 것도 움직이지 않는다" 인데, 위젯은 사람이 지금 보고 있는 화면을 즉시 바꾼다.
_WIDGET_READ_TOOL_ADDITIONS = {
    'list_dashboards', 'list_widget_types', 'get_widget',
}
_WIDGET_WRITE_TOOL_ADDITIONS = {
    'create_widget', 'modify_widget',
}
_WIDGET_DELETE_TOOL_ADDITIONS = {
    'delete_widget',
}

_GEO_BINDING_MUTATING_ADDITIONS = {'rebind_device'}

# 구역 단위 센서 집계(2026-08-14). 읽기 전용이라 승인 집합에는 들어가지 않는다 —
# 값을 계산해 낼 뿐 Function 도 채널도 만들지 않는다.
_ZONE_SUMMARY_TOOL_ADDITIONS = {'get_zone_sensor_summary'}

# 서랍 열기(2026-08-15). 읽기 전용이며 매니페스트에는 없다 — 등급이 켜졌을 때만
# _drawer_index_manifest() 가 서랍 목록과 함께 싣는다.
_DRAWER_TOOL_ADDITIONS = {'open_drawer'}

# 지도 거리 (2026-08-14) — aot/utils/geo_distance.py.
# LLM 이 좌표로 거리를 직접 재면 조용히 틀리고, 틀린 거리가 그대로 배치
# 결정이 된다("관리사무소에서 가까운 순으로 품종 배정"이 실제 요청이었다).
# 둘 다 읽기전용이라 승인 집합에는 넣지 않는다.
_GEO_DISTANCE_TOOL_ADDITIONS = {'distance_between', 'nearest'}

# 장치 신선도 (2026-08-17). get_anomalies 의 comm_offline_devices 는 드라이버가
# 스스로 보고한 통신 장애만 세므로, "39시간째 값이 안 들어오는 센서" 는 거기에
# 절대 안 잡힌다 — 그리고 잡히게 만들면 안 된다(침묵은 장애 신호가 아니다).
# 그래서 판정을 바꾸는 대신 사실만 보고하는 읽기 도구를 따로 뒀다. 이름·의미를
# comm_* 와 분리해 두는 것이 이 도구의 목적이다. 읽기 전용.
_DEVICE_FRESHNESS_TOOL_ADDITIONS = {'get_device_freshness'}

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
           | _PLANTING_READ_TOOL_ADDITIONS | _PLANTING_WRITE_TOOL_ADDITIONS
           | _PLOT_STAGE_TOOL_ADDITIONS | _PLOT_STAGE_EDIT_TOOL_ADDITIONS
           | _LOOKUP_SOURCE_READ_TOOL_ADDITIONS
           | _CROP_PROGRAM_READ_TOOL_ADDITIONS | _CROP_PROGRAM_WRITE_TOOL_ADDITIONS
           | _CROP_PROGRAM_DELETE_TOOL_ADDITIONS
           | _TAB_READ_TOOL_ADDITIONS | _TAB_WRITE_TOOL_ADDITIONS | _TAB_DELETE_TOOL_ADDITIONS
           | _WIDGET_READ_TOOL_ADDITIONS | _WIDGET_WRITE_TOOL_ADDITIONS | _WIDGET_DELETE_TOOL_ADDITIONS
           | _ZONE_SUMMARY_TOOL_ADDITIONS | _GEO_DISTANCE_TOOL_ADDITIONS
           | _DRAWER_TOOL_ADDITIONS | _DEVICE_FRESHNESS_TOOL_ADDITIONS,
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
           | _PLANTING_READ_TOOL_ADDITIONS | _PLANTING_WRITE_TOOL_ADDITIONS
           | _PLOT_STAGE_TOOL_ADDITIONS | _PLOT_STAGE_EDIT_TOOL_ADDITIONS
           | _LOOKUP_SOURCE_READ_TOOL_ADDITIONS
           | _CROP_PROGRAM_READ_TOOL_ADDITIONS | _CROP_PROGRAM_WRITE_TOOL_ADDITIONS
           | _CROP_PROGRAM_DELETE_TOOL_ADDITIONS
           | _TAB_READ_TOOL_ADDITIONS | _TAB_WRITE_TOOL_ADDITIONS | _TAB_DELETE_TOOL_ADDITIONS
           | _WIDGET_READ_TOOL_ADDITIONS | _WIDGET_WRITE_TOOL_ADDITIONS | _WIDGET_DELETE_TOOL_ADDITIONS
           | _ZONE_SUMMARY_TOOL_ADDITIONS | _GEO_DISTANCE_TOOL_ADDITIONS
           | _DRAWER_TOOL_ADDITIONS | _DEVICE_FRESHNESS_TOOL_ADDITIONS,
           set(R.virtual_tool_registry()))

    # 4. dispatch approval set — original PLUS the mutating post-Phase-1 additions,
    #    MINUS the config_only exemptions.
    _check("_VIRTUAL_APPROVAL_TOOLS",
           (_ORIG_VIRTUAL_APPROVAL_TOOLS | _POST_PHASE1_MUTATING_ADDITIONS | _SFK_AI_MUTATING_ADDITIONS
            | _SEQUENCE_SCHEDULE_TOOL_ADDITIONS
            | _SCHEDULE_CRUD_MUTATING_ADDITIONS | _GIS_INPUT_CRUD_MUTATING_ADDITIONS
            | _CONFIRMATION_RELAY_MUTATING_ADDITIONS | _ADAPTIVE_STORAGE_WRITE_TOOL_ADDITIONS
            | _GEO_BINDING_MUTATING_ADDITIONS | _PLANTING_WRITE_TOOL_ADDITIONS
            | _PLOT_STAGE_TOOL_ADDITIONS | _PLOT_STAGE_EDIT_TOOL_ADDITIONS
            | _CROP_PROGRAM_WRITE_TOOL_ADDITIONS | _CROP_PROGRAM_DELETE_TOOL_ADDITIONS
            | _TAB_WRITE_TOOL_ADDITIONS | _TAB_DELETE_TOOL_ADDITIONS
            | _WIDGET_WRITE_TOOL_ADDITIONS | _WIDGET_DELETE_TOOL_ADDITIONS)
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
            | _PLANTING_WRITE_TOOL_ADDITIONS | _PLOT_STAGE_TOOL_ADDITIONS
            | _PLOT_STAGE_EDIT_TOOL_ADDITIONS
            | _CROP_PROGRAM_WRITE_TOOL_ADDITIONS | _CROP_PROGRAM_DELETE_TOOL_ADDITIONS
            | _TAB_WRITE_TOOL_ADDITIONS | _TAB_DELETE_TOOL_ADDITIONS
            | _WIDGET_WRITE_TOOL_ADDITIONS | _WIDGET_DELETE_TOOL_ADDITIONS)
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


def test_ssot_derivations_match_snapshots():
    """위 run() 을 pytest 에서도 돌린다.

    **이 래퍼가 없으면 pytest 초록불이 CI 통과를 뜻하지 않는다.** 파생 검사는
    전부 run() 안에 있고 run() 은 `__main__` 에서만 불렸다 — CI 는 모듈을 직접
    실행(`python3 -m ...`)해서 잡지만, 개발자가 `pytest aot/tests/ai_eval/` 로
    확인하면 수집되는 것이 없어 조용히 지나갔다. 실제로 2026-08-24 도구 8종이
    스냅샷 갱신 없이 들어가 main 이 사흘간 붉었는데, 그동안 로컬 pytest 는
    계속 통과했다.
    """
    run(check_dispatch=True)


if __name__ == '__main__':
    import sys
    run(check_dispatch='--no-dispatch' not in sys.argv)
