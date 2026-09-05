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
import os
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
    config_only: a mutation that only edits a controller's CONFIGURATION — it moves no
                 equipment by itself, because nothing runs until the function is
                 activated, and activation is separately gated. Such a tool is still a
                 write (role check + audit still apply) but is exempt from human
                 approval. See _CONFIG_ONLY note below before adding one.
    manifest   : the VERBATIM manifest dict emitted into get_action_manifest()'s
                 system_tools list, or None to omit the tool from the LLM manifest.
                 Stored verbatim so the derived manifest is byte-identical to the
                 original hand-written entries.
    노출 등급(domain·base_tier·never_demote)은 이 선언이 아니라 아래
    `_TIER_ASSIGNMENT` 표가 갖는다. 주기적으로 사람이 다시 보는 판단이라
    한눈에 보이는 표가 검토 단위이기 때문이다 — 그 절의 주석 참조.

    (참고) domain : 어느 서랍에 들어가는가. 서랍은 **도메인 이름**으로 묶는다 —
                 빈도 기준 서랍("자주 안 쓰는 것 모음")은 LLM 이 안을 예측할 수
                 없어 여러 개를 열게 되고, 고정비를 줄이려다 왕복을 늘린다.
    base_tier  : 사용 데이터가 없을 때의 자리. 'core'=상시 노출, 'drawer'=서랍.
                 개발 단계에서는 이 값이 곧 유효 등급이다.
    never_demote: 호출이 적어도 자동 강등하지 않는다. 기준은 "사용자가 이름을
                 말해주는가, AI 가 스스로 떠올려야 하는가" — 후자만 보호한다.
                 (계절성만으로는 사유가 안 된다. 정식·수확은 사용자가 명시적으로
                 요청하므로 서랍이어도 단서가 서랍을 고른다.)
    """
    name: str
    handler: Optional[str] = None
    action_type: str = 'virtual_tool_call'
    registry: bool = True
    mutating: bool = False
    physical: bool = False
    config_only: bool = False
    manifest: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# _CONFIG_ONLY — 승인을 면제해도 되는 조건.
#
# 2026-08-07, koat 감사 로그 실측: 하루 쓰기 호출 33건 중 실제로 장비를 움직인
# 것은 2건(deactivate_function, operate_device)뿐이고 나머지 31건은 전부 시퀀스
# 설정 편집이었다. 승인 클릭 21번 중 19번이 "물이 흐르지 않는 편집"에 쓰였다.
# 게이트가 읽기/쓰기 이분법이라 밸브 여는 것과 단계 순서 바꾸는 것이 같은 무게를
# 받았고, 그 마찰이 실제로 잘못된 우회를 낳은 적도 있다(요일이 다르다는 이유로
# 시퀀스를 새로 만든 사건).
#
# config_only 를 붙이려면 셋 다 참이어야 한다:
#   1. 이 도구만으로는 어떤 장비도 움직이지 않는다.
#   2. 편집 결과가 실제로 도는 시점은 activate_function 을 지나야 하고,
#      그 활성화는 계속 승인 대상이다.
#   3. 되돌릴 수 있다. 삭제처럼 복구 불가능한 것은 해당 없음.
#
# 활성 상태인 시퀀스의 시간표를 고치면 오늘 밤 관수 시각이 승인 없이 바뀐다 —
# 이건 알고 받아들인 절충이다(2026-08-07 사용자 결정). 되돌리려면 해당 도구의
# config_only 를 떼면 된다. 삭제(delete_*)와 활성/비활성은 절대 넣지 말 것.
#
# 2026-08-24 — 프로그램(create_program·modify_program) 추가.
#
# 프로그램은 제어가 아니라 **제어에 영향을 주는 참고자료**다. 장치를 직접 움직이지
# 않고, 오래 두고 보는 문서인데 만들 때마다 승인을 받게 하면 마찰만 남는다
# (사용자 판단, 2026-08-24).
#
# 게이트가 이미 두 겹이었고 **뒤쪽이 더 강하다**. `GeoProgram.usable_for_control()`
# 은 `source='ai'` 인 프로그램을 `reviewed_at` 전까지 제어에서 배제하고, 그 판정을
# `coordinator_plot` 이 실제로 본다. `program_io.update_program(by='ai')` 는 AI 가
# 제어에 닿는 내용(단계·목표·광합성 상수)을 쓸 때마다 `source` 를 `ai` 로 되돌리고
# `reviewed_at` 을 지운다 — 사람이 껍데기를 만들고 AI 가 채우는 실제 흐름까지 덮는다.
#
# 위 세 조건 대조:
#   1. 이 도구만으로 장비가 움직이지 않는다 — `usable_for_control()` 이 막는다.
#   2. 실제로 도는 시점에 별도 게이트가 있다 — 검토(`reviewed_at`). 이쪽은
#      activate_function 보다 **더 강하다**: `by != 'ai'` 조건 때문에 AI 는 자기
#      프로그램을 스스로 검토 완료로 만들 수 없다(program_io 해당 줄 주석 참조).
#   3. 되돌릴 수 있다 — 다시 고치거나 지우면 된다.
#
# `delete_program` 은 그대로 승인 대상이다(위 금지 조항).
# ---------------------------------------------------------------------------


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
            "params: {device_id, scheduled_time (ISO8601) OR delay_seconds OR solar_event, state, duration_minutes}. "
            "For a time expressed relative to the sun ('내일 일몰 30분 전', 'at sunrise'), pass "
            "solar_event ('sunrise'|'sunset'|'solar_noon'|'civil_dawn'|'civil_dusk') with "
            "solar_offset_minutes (negative = before) and solar_date_offset_days — do NOT compute "
            "the sunset clock time yourself and pass it as scheduled_time: it changes with the "
            "season and the device's location, so a hand-computed value will be wrong.\n"
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
        "description": "Search for Input/Output/Camera/Zone/complex-Device entries by name or type keyword, and/or by the measurement a device actually records. When the results contain a complex device (e.g. a PLC — one physical unit split across separate Input and Output entries), the reply carries a '_reading' note saying how to treat it. Follow it.",
        "usage_hint": "params.arguments: {query?: '<keyword>', measurement_type?: '<e.g. volumetric_water_content>'} — at least one. measurement_type finds every device that really records it regardless of its name; give both to intersect (e.g. query='1포장' + measurement_type='temperature'). It matches the STORED name, not the everyday word — soil moisture is 'volumetric_water_content' ('moisture' returns nothing), rain is 'precipitation'. On 0 results check the real names with get_device_measurements. Returns matching devices with their unique_ids.",
    }),
    # 구역 단위 집계. Function 을 만들지 않는다 — 대상·기간이 질문마다 달라
    # 고정 계산기로는 답할 수 없고, influx.py 의 무상태 헬퍼를 조합해 계산만
    # 하고 남기지 않는다. 읽기 전용이므로 승인 대상이 아니다.
    Tool('get_zone_sensor_summary', handler='get_zone_sensor_summary', manifest={
        "tool_name": "get_zone_sensor_summary",
        "action_type": "virtual_tool_call",
        "description": ("Latest reading plus period min/max/avg for the sensors of "
                        "MANY zones in one call — use instead of looping "
                        "get_sensor_detail per zone. Read-only."),
        "usage_hint": ("params.arguments: {zone_ids?: [uuid,...], measurement_type?, "
                       "time_range?: '24h'|'7d'} — omit zone_ids for every zone."),
    }),
    # 서랍을 여는 유일한 수단. manifest 는 None 이다 — 등급이 켜졌을 때만
    # _drawer_index_manifest() 가 서랍 목록과 함께 싣는다(꺼져 있으면 서랍
    # 자체가 없으므로 이 도구도 보일 이유가 없다).
    Tool('open_drawer', handler='open_drawer'),
    Tool('get_device_measurements', handler='get_device_measurements', manifest={
        "tool_name": "get_device_measurements",
        "action_type": "virtual_tool_call",
        "description": "Returns all measurement channels (measurement_id, channel, measurement, unit) for a given device_id.",
        "usage_hint": "Call with params.arguments.device_id='<id>'. Use to resolve measurement IDs for create_function params.",
    }),
    # --- 적응형 문서 스토리지 (읽기 전용) ---------------------------------------
    # 티어 값은 "옮기겠다는 의도"이고 cold_documents 행이 "실제로 옮겨진 실물"이다.
    # 둘이 아직 연결돼 있지 않아서(이동이 placeholder), 도구 설명에 그 구분을 박아
    # 둔다 — AI 가 tier=3 을 보고 "아카이브됨" 이라고 사용자에게 말하면 안 된다.
    Tool('get_storage_tier_status', handler='get_storage_tier_status', manifest={
        "tool_name": "get_storage_tier_status",
        "action_type": "virtual_tool_call",
        "description": "Reports the adaptive document storage state: whether tiering is enabled, how many documents sit in each tier (1=hot, 2=warm, 3=cold), and how many are ACTUALLY archived. A tier value records an intent to move; only a row in the archive means the content was really moved. When both are present in the reply, trust the archive count.",
        "usage_hint": "Takes no arguments. Call this before answering anything about storage tiers, archiving, or where a document's content lives. Relay any 'warning' or 'note' field to the user rather than dropping it.",
    }),
    Tool('search_archives', handler='search_archives', manifest={
        "tool_name": "search_archives",
        "action_type": "virtual_tool_call",
        "description": "Searches ARCHIVED documents by their stored metadata. Only returns documents whose content was really moved to the archive — a document marked tier 3 that was never moved will NOT appear here.",
        "usage_hint": "Call with params.arguments.query='<keyword>' (optional), limit, offset. An empty result is a normal state, not an error.",
    }),
    Tool('get_archived_document', handler='get_archived_document', manifest={
        "tool_name": "get_archived_document",
        "action_type": "virtual_tool_call",
        "description": "Retrieves one archived document. Returns metadata only by default; pass include_content=true to decompress and return the full text. Reading an archive updates its last-accessed time, which feeds future tier decisions.",
        "usage_hint": "Call with params.arguments.document_id='<id>' and optional include_content=true. Use search_archives first if you only have a keyword.",
    }),

    # --- 적응형 문서 스토리지 (쓰기 — 전부 승인 게이트) ------------------------
    Tool('archive_note', handler='archive_note', mutating=True, manifest={
        "tool_name": "archive_note",
        "action_type": "virtual_tool_call",
        "description": "Archives a note: writes a compressed COPY into cold storage and marks the note tier 3. Requires human approval. The original note text is NOT deleted — archiving never removes content; only the retention policy does.",
        "usage_hint": "Call with params.arguments.note_id='<id>' and optional retention_policy ('default'|'1year'|'3year'|'7year'|'permanent'). Fails if the note is already archived.",
    }),
    Tool('restore_note_from_archive', handler='restore_note_from_archive', mutating=True, manifest={
        "tool_name": "restore_note_from_archive",
        "action_type": "virtual_tool_call",
        "description": "Reads a note back out of cold storage and moves it to a warmer tier. Requires human approval. If the archive exists but the original note is gone, the archived text is returned with status 'orphan_archive' instead of being silently recreated.",
        "usage_hint": "Call with params.arguments.note_id='<id>' and optional target_tier (1=hot, 2=warm; default 2).",
    }),
    Tool('set_document_tier', handler='set_document_tier', mutating=True, manifest={
        "tool_name": "set_document_tier",
        "action_type": "virtual_tool_call",
        "description": "Changes only a note's tier value (1=hot, 2=warm, 3=cold). Requires human approval. This moves NO data — it records an intent. To actually place content in the archive use archive_note.",
        "usage_hint": "Call with params.arguments.note_id='<id>' and tier=1|2|3.",
    }),
    Tool('delete_archive', handler='delete_archive', mutating=True, manifest={
        "tool_name": "delete_archive",
        "action_type": "virtual_tool_call",
        "description": "Deletes the archived COPY of a document (file + index rows). Requires human approval. The original note is untouched, so its tier may still read 3 afterwards. This is irreversible — the compressed copy is removed from disk.",
        "usage_hint": "Call with params.arguments.document_id='<id>' and an optional reason. Confirm with the user that they mean the archived copy, not the note itself.",
    }),

    Tool('create_function', handler='create_function_tool', mutating=True, manifest={
        "tool_name": "create_function",
        "action_type": "virtual_tool_call",
        "description": "Creates a new automation function/controller. Requires human approval. This — NOT schedule_device_control — is the right home for RECURRING device control (daily/weekly watering → trigger_timer_daily_time_point / trigger_timer_daily_time_span / trigger_timer_duration) and CONDITION-BASED control (when humidity < X → conditional_conditional). function_type MUST be one of: conditional_conditional, pid_pid, trigger_edge, trigger_output, trigger_output_pwm, trigger_run_pwm_method, trigger_sequence, trigger_sunrise_sunset, trigger_timer_daily_time_point, trigger_timer_daily_time_span, trigger_timer_duration, function_actions. For SEQUENTIAL control of several devices (e.g. a valve sequence), use 'trigger_sequence'.",
        "usage_hint": "params.arguments accepts ONLY {function_type, name, params}. Do NOT pass 'devices' or any other top-level key — there is no device-list parameter. The function is created first; its device steps/order are configured afterward. params is a dict of custom_option overrides (e.g. select_measurement fields as 'device_id,meas_id').",
    }),
    Tool('modify_function_options', handler='modify_function_options', mutating=True, config_only=True, manifest={
        "tool_name": "modify_function_options",
        "action_type": "virtual_tool_call",
        "description": "Updates custom_options of an existing function and reloads it in the daemon. Applies immediately — no approval needed; activating the function is separately approved.",
        "usage_hint": "params.arguments: {function_id, params: {<option_id>: <value>}}",
    }),
    # A sequence's schedule lives in Trigger columns/timer_schedule, not in
    # custom_options, so modify_function_options cannot reach it (it now says
    # so instead of silently no-op'ing). This is the way in.
    Tool('modify_sequence_schedule', handler='modify_sequence_schedule', mutating=True, config_only=True, manifest={
        "tool_name": "modify_sequence_schedule",
        "action_type": "virtual_tool_call",
        "description": "Changes WHEN a trigger_sequence runs — daily window, cycle period, and which weekdays. Use this (not modify_function_options) for any sequence timing change. Keeps the running cycle instead of restarting it. Applies immediately — no approval needed, because a sequence only runs once it is activated and activation is separately approved.",
        "usage_hint": "params.arguments: {function_id, start:'HH:MM', end:'HH:MM', period_seconds, weekdays:[0-6, 0=Mon], day:0-6}. Call get_function_detail first to see the current schedule. Omit 'day' to change every enabled day; pass it to change one weekday only. This does NOT change the step order or per-step durations.",
    }),
    # One call = one weekday's whole plan. The per-step tool below still exists
    # for touch-ups, but laying out a day through it costs ~20 gated calls, and
    # that friction is what pushed a caller into making a redundant sequence.
    Tool('configure_sequence_day', handler='configure_sequence_day', mutating=True, config_only=True, manifest={
        "tool_name": "configure_sequence_day",
        "action_type": "virtual_tool_call",
        "description": "Sets ONE weekday's entire run plan on an existing sequence in a single call: which devices run, in what order, for how long, and which run together. Prefer this over repeated modify_sequence_step. Applies immediately — no approval needed, because a sequence only runs once it is activated and activation is separately approved.",
        "usage_hint": "params.arguments: {function_id, day:0-6 (0=Mon), start:'HH:MM', slots:[{devices:['v321','v322'], minutes:40}, {devices:['v331'], minutes:60}]}. Slots run in the order given; devices inside one slot run SIMULTANEOUSLY. Steps not listed are turned off for that weekday only. end/period_seconds are optional — by default the window just fits one pass and it runs once. A different weekday needs another call with the same function_id; NEVER create a second sequence for that.",
    }),
    # create_sequence_function only lays down uniform steps; this shapes them
    # (groups = simultaneous, per-step duration, total-step margins).
    Tool('modify_sequence_step', handler='modify_sequence_step', mutating=True, config_only=True, manifest={
        "tool_name": "modify_sequence_step",
        "action_type": "virtual_tool_call",
        "description": "Configures ONE step of a trigger_sequence: run order, device group (steps sharing a group run SIMULTANEOUSLY), duration, single/total mode, total-step lead/lag margins, enabled, label — globally, or for ONE weekday via 'day'. Applies immediately — no approval needed, because a sequence only runs once it is activated and activation is separately approved.",
        "usage_hint": "params.arguments: {action_id, group_name, duration_seconds, mode:'single'|'total', enabled, display_name, lead_seconds, lag_seconds, order, day}. Get action_id from get_function_detail steps[].action_id. 'order' sets the run order (lower runs first). Pass 'day' (0=Mon..6=Sun) to override enabled/group_name/duration_seconds for that weekday only — that is how ONE sequence covers different valves on different days; do NOT create a second sequence for that. A group shares ONE duration — setting it on any member sets all. A 'total' step cannot be grouped; lead/lag apply only to it.",
    }),
    Tool('create_sequence_function', handler='create_sequence_function', mutating=True, config_only=True, manifest={
        "tool_name": "create_sequence_function",
        "action_type": "virtual_tool_call",
        "description": "Creates a trigger_sequence AND fills its steps — one ordered output action per device — so it is configured, not empty. Use for 'valve sequence' / sequential device control. Created inactive and applies immediately — no approval needed; activate_function still needs approval.",
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
    # --- 식생 구획(작기) — docs/design/geo-vegetation-plot.md -------------
    # "어디에 무엇이 심겨 있는가" 는 재배 조언의 전제다. 시설은 구획 프로그램 /
    # facility_registry 로 알 수 있었지만 노지는 알 방법이 없어, AI 가 노지
    # 구역에 대해서는 작물을 모른 채 답하고 있었다.
    #
    # 쓰기 3종은 전부 승인 대상이다. config_only 로 면제하지 말 것 —
    # end/delete 는 되돌릴 수단이 없고(그 자리의 이력이 사라진다),
    # create 는 사람이 밭에서 확인해야 하는 사실을 기록하는 행위다.
    Tool('list_plots', handler='list_plots', manifest={
        "tool_name": "list_plots",
        "action_type": "virtual_tool_call",
        "description": ("Lists vegetation plots (what crop is planted where). "
                        "Growing plots only unless include_ended=true. "
                        "with_sensors=true adds each plot's sensors in one call. "
                        "The reply carries a '_reading' list — the rules for "
                        "reading THIS result. Follow it; it is instruction, "
                        "not commentary. Read-only."),
        "usage_hint": ("params.arguments: {map_id?, zone_id?, include_ended?, "
                       "on?: 'YYYY-MM-DD', with_sensors?}"),
    }),
    Tool('get_plot', handler='get_plot', manifest={
        "tool_name": "get_plot",
        "action_type": "virtual_tool_call",
        "description": ("One plot in detail: crop, variety, period, area, size "
                        "(width x length), which sensors it reads (own plot or "
                        "falls back to its zone), which irrigation valves overlap "
                        "it, and its current programme stage. Give both spacings "
                        "to get row and plant counts. 'target_check' pairs this "
                        "stage's targets with the readings, now and over the last "
                        "14 days. The reply carries a "
                        "'_reading' list — the rules for reading THIS result. "
                        "Follow it; it is instruction, not commentary. Read-only."),
        "usage_hint": ("params.arguments: {plot_id, plant_spacing_cm, "
                       "row_spacing_cm? (flat only), bed_pitch_cm? + "
                       "rows_per_bed? (bed layout), edge_margin_cm?} — "
                       "bed_pitch_cm and rows_per_bed go together"),
    }),
    Tool('get_plot_history', handler='get_plot_history', manifest={
        "tool_name": "get_plot_history",
        "action_type": "virtual_tool_call",
        "description": ("What was planted on this spot before — the basis for crop "
                        "rotation and soil-borne disease judgement. Read-only."),
        "usage_hint": "params.arguments: {plot_id} or {zone_id}",
    }),
    Tool('list_plot_journals', handler='list_plot_journals', manifest={
        "tool_name": "list_plot_journals",
        "action_type": "virtual_tool_call",
        "description": ("Saved journals (title, period, status) for a plot/zone/site. "
                        "journal_id is an internal handle for get_plot_journal — do "
                        "not show it; use title/period instead. Read-only."),
        "usage_hint": ("params.arguments: {target_type?: plot|zone|site, "
                       "target_id?, limit?} — omit the target for all journals"),
    }),
    Tool('get_plot_journal', handler='get_plot_journal', manifest={
        "tool_name": "get_plot_journal",
        "action_type": "virtual_tool_call",
        "description": ("One saved journal — the snapshot from generation time. "
                        "For a long period pass granularity so the measurements "
                        "survive the response limit. status may be pending/"
                        "running/error; only 'done' has data. Read-only."),
        "usage_hint": ("params.arguments: {journal_id, granularity?: day|week|"
                       "month|all, date_from?, date_to?}"),
    }),
    # 생성은 InfluxDB 를 크게 읽는다(채널 수 × 기간) — 승인 대상이다.
    # 물리 작동은 없으므로 `physical` 은 아니다.
    Tool('create_plot_journal', handler='create_plot_journal', mutating=True,
         manifest={
        "tool_name": "create_plot_journal",
        "action_type": "virtual_tool_call",
        "description": ("Builds a journal — a snapshot of what was grown, "
                        "measured and controlled over a period. Runs in the "
                        "background; poll get_plot_journal for status 'done'. "
                        "Requires human approval."),
        "usage_hint": ("params.arguments: {target_type: plot|zone|site, "
                       "target_id, start: YYYY-MM-DD, end: YYYY-MM-DD, "
                       "granularity?: day|week|month}"),
    }),
    Tool('list_programs', handler='list_programs', manifest={
        "tool_name": "list_programs",
        "action_type": "virtual_tool_call",
        "description": ("Management programmes — a subject's stages with their "
                        "lengths. kind is vegetation | livestock | facility | other; "
                        "Attach one to a plot and the stage, remaining days and "
                        "expected harvest date follow from it. Check here before "
                        "creating a new one. Read-only."),
        "usage_hint": "params.arguments: {kind?, subject?, tab_id?}",
    }),
    Tool('get_program', handler='get_program', manifest={
        "tool_name": "get_program",
        "action_type": "virtual_tool_call",
        "description": ("One growing programme with its full stage list. A stage may "
                        "carry 'guidance' — free text written for that stage. "
                        "Read-only."),
        "usage_hint": "params.arguments: {program_id}",
    }),
    Tool('create_program', handler='create_program', mutating=True, config_only=True, manifest={
        "tool_name": "create_program",
        "action_type": "virtual_tool_call",
        "description": ("Creates a growing programme (subject -> stages with lengths). "
                        "'subject' is whatever the programme manages — a crop, a tree "
                        "species, a turf type, a herd, a structure; AoT is not "
                        "farm-only, so set 'kind' to match (default vegetation). "
                        "resource_defs declares WHAT the subject needs (roles), never "
                        "which function does it — that is a fact about a place, so the "
                        "site resolves it and one programme serves several "
                        "greenhouses. Made this way it is used for display and advice "
                        "but NOT for control until a person marks it as checked — "
                        "that check is the gate, and only a person can give it."),
        "usage_hint": ("params.arguments: {name, subject, source_note, "
                       "stages: [{key, name, days, targets?, guidance?}], kind?, "
                       "variety?, notes?, target_defs?: [{key, label, unit, "
                       "measurement}], base_temp_c?, "
                       "resource_defs?: [{role: irrigation|fertigation|"
                       "other}], tab_id?}. "
                       "days is that stage's LENGTH, not cumulative; only the "
                       "last may be blank (= until the end). source_note is "
                       "required. 'guidance' is the half no sensor can do — what "
                       "to LOOK at and what to DO BY HAND in that stage. Fill "
                       "it: it is what a beginner opens the programme for. "
                       "'targets' keys must exist in target_defs (vegetation "
                       "already has temp_day/temp_night/rh/co2/dli/vpd). "
                       "RECIPE: 1) list_programs — does it exist already? "
                       "2) knowledge_search the subject for stage-by-stage "
                       "practice. 3) Map what you find onto YOUR stage keys — "
                       "sources split stages their own way, so state the "
                       "mapping in source_note; never bend a day count to make "
                       "a source fit. 4) Cite in source_note. Leave a field "
                       "blank rather than guessing — a blank is normal, a "
                       "plausible wrong number is not."),
    }),
    Tool('modify_program', handler='modify_program', mutating=True, config_only=True, manifest={
        "tool_name": "modify_program",
        "action_type": "virtual_tool_call",
        "description": ("Edits a growing programme's name / variety / stages / notes, "
                        "or moves it to a different tab (tab_id) on the Programs page. "
                        "A tab_id-only call is allowed even for built-in/external "
                        "programmes (moving a tab is organisation, not content); any "
                        "other field on a built-in/external programme is refused — "
                        "it must be copied first (a person does that on the "
                        "Vegetation page). Writing stages or targets sends the "
                        "programme back for a person to check before it drives "
                        "control again — say so rather than working around it."),
        "usage_hint": ("params.arguments: {program_id, name?, variety?, "
                       "stages?: [{key, name, days, targets?, guidance?}], "
                       "target_defs?, base_temp_c?, "
                       "resource_defs?, kind?, notes?, source_note?, tab_id?}. "
                       "This is how an empty programme a person made in the UI "
                       "gets filled in — same stage shape and same RECIPE as "
                       "create_program, and get_program first to see what is "
                       "already there. Send only the fields you are changing; "
                       "'stages' replaces the whole list. Writing stages, "
                       "target items or base_temp_c sends the programme back "
                       "for a person to check before it drives control again — "
                       "that is expected, say so rather than working around it."),
    }),
    Tool('delete_program', handler='delete_program', mutating=True, manifest={
        "tool_name": "delete_program",
        "action_type": "virtual_tool_call",
        "description": ("Deletes a growing programme outright — for mistakes only. "
                        "Refused if any plot still uses it; unassign the plot's "
                        "programme first (modify_plot with program_uuid: null), or "
                        "just leave an unused programme in place — it costs nothing "
                        "to keep. Requires human approval."),
        "usage_hint": "params.arguments: {program_id}",
    }),
    Tool('list_tabs', handler='list_tabs', manifest={
        "tool_name": "list_tabs",
        "action_type": "virtual_tool_call",
        "description": ("Tabs group cards on a page into folders — the same "
                        "mechanism across the Dashboard, Input, Output, Function "
                        "and Programs pages. Read-only."),
        "usage_hint": "params.arguments: {page_type: dashboard|input|output|function|program}",
    }),
    # ── 대시보드 위젯 ────────────────────────────────────────────────────────
    # 위젯은 사람이 보는 화면이라, 여기서 하는 일은 전부 사용자의 대시보드를
    # 바꾼다. 물리 장치를 움직이지 않는다는 이유로 config_only(승인 면제)에
    # 넣지 말 것 — 면제의 근거는 "아무것도 움직이지 않는다" 인데, 위젯은
    # 사람이 지금 보고 있는 화면을 즉시 바꾼다.
    Tool('list_dashboards', handler='list_dashboards', manifest={
        "tool_name": "list_dashboards",
        "action_type": "virtual_tool_call",
        "description": ("Dashboard tabs and the widgets on each — what the user "
                        "actually sees. Read-only."),
        "usage_hint": ("params.arguments: {tab_id?, with_options?}. Widget settings "
                       "are omitted unless with_options is true; use get_widget for "
                       "one widget in detail."),
    }),
    Tool('list_widget_types', handler='list_widget_types', manifest={
        "tool_name": "list_widget_types",
        "action_type": "virtual_tool_call",
        "description": ("Widget types installed on this system, and the option "
                        "schema of one of them. Read-only."),
        "usage_hint": ("params.arguments: {widget_type?}. Call with no argument for "
                       "the list, then again with a type to get its options before "
                       "create_widget — every type takes different options."),
    }),
    Tool('get_widget', handler='get_widget', manifest={
        "tool_name": "get_widget",
        "action_type": "virtual_tool_call",
        "description": "One widget in detail, including its settings. Read-only.",
        "usage_hint": "params.arguments: {widget_id}",
    }),
    Tool('create_widget', handler='create_widget', mutating=True, manifest={
        "tool_name": "create_widget",
        "action_type": "virtual_tool_call",
        "description": ("Adds a widget to a dashboard tab. Requires human approval."),
        "usage_hint": ("params.arguments: {tab_id, widget_type, name?, options?, "
                       "width?, height?}. Get tab_id from list_dashboards and the "
                       "option schema from list_widget_types first — an option name "
                       "that is not in that schema is rejected rather than ignored."),
    }),
    Tool('modify_widget', handler='modify_widget', mutating=True, manifest={
        "tool_name": "modify_widget",
        "action_type": "virtual_tool_call",
        "description": ("Changes a widget's name, size, position, tab or settings. "
                        "Only what you pass is changed. Requires human approval."),
        "usage_hint": ("params.arguments: {widget_id, name?, options?, width?, "
                       "height?, position_x?, position_y?, tab_id?}. options are "
                       "merged into the existing settings, not replaced."),
    }),
    Tool('delete_widget', handler='delete_widget', mutating=True, manifest={
        "tool_name": "delete_widget",
        "action_type": "virtual_tool_call",
        "description": ("Removes a widget from the dashboard. Requires human "
                        "approval."),
        "usage_hint": "params.arguments: {widget_id}",
    }),

    Tool('create_tab', handler='create_tab', mutating=True, manifest={
        "tool_name": "create_tab",
        "action_type": "virtual_tool_call",
        "description": ("Creates a new tab on a page. Name is auto-generated if "
                        "omitted. Requires human approval."),
        "usage_hint": ("params.arguments: {page_type: dashboard|input|output|"
                       "function|program, name?}"),
    }),
    Tool('modify_tab', handler='modify_tab', mutating=True, manifest={
        "tool_name": "modify_tab",
        "action_type": "virtual_tool_call",
        "description": "Renames a tab. Requires human approval.",
        "usage_hint": "params.arguments: {tab_id, name}",
    }),
    Tool('delete_tab', handler='delete_tab', mutating=True, manifest={
        "tool_name": "delete_tab",
        "action_type": "virtual_tool_call",
        "description": ("Deletes a tab. On Input/Output/Function pages this also "
                        "deletes the cards inside it (same as the UI) — check "
                        "list_tabs and move anything worth keeping first. On "
                        "Programs, cards are never deleted this way; they move "
                        "to the page's default tab instead, because a programme "
                        "may still be in use by a plot elsewhere. The last "
                        "remaining tab on a page cannot be deleted. Requires "
                        "human approval."),
        "usage_hint": "params.arguments: {tab_id}",
    }),
    Tool('create_plot', handler='create_plot', mutating=True, manifest={
        "tool_name": "create_plot",
        "action_type": "virtual_tool_call",
        "description": ("Creates a vegetation plot. Inside a greenhouse pass "
                        "facility_id (+bay_id) and no geometry — a facility plot's "
                        "location IS the bay. Outdoors pass zone_id (whole zone) or "
                        "a GeoJSON polygon; the owning zone is derived server-side. "
                        "Requires human approval."),
        "usage_hint": ("params.arguments: {map_id, subject, kind?, program_id?, started_on: 'YYYY-MM-DD', "
                       "facility_id? + bay_id? | zone_id? | geometry: <GeoJSON Polygon>, "
                       "program_id?, variety?, name?, expected_end_on?, color?}"),
    }),
    Tool('modify_plot', handler='modify_plot', mutating=True, manifest={
        "tool_name": "modify_plot",
        "action_type": "virtual_tool_call",
        "description": ("Edits a plot's crop / variety / name / period / colour, and "
                        "for a facility plot the bay it sits in. Geometry is not "
                        "editable here. Requires human approval."),
        "usage_hint": ("params.arguments: {plot_id, subject?, kind?, program_uuid?, variety?, name?, "
                       "started_on?, expected_end_on?, color?, bay_id?, "
                       "program_uuid?, auto_advance?}"),
    }),
    Tool('propose_plot_split', handler='propose_plot_split', manifest={
        "tool_name": "propose_plot_split",
        "action_type": "virtual_tool_call",
        "description": ("Works out how a zone/site would divide into plots. "
                        "Direction defaults by mode: strip_width_cm (beds) follows "
                        "the longest side, parts alone follows the shortest side "
                        "(squarer pieces) — override with orientation. Computes "
                        "only — creates nothing. Read-only."),
        "usage_hint": ("params.arguments: {zone_id, parts? | strip_width_cm? | "
                       "widths_cm?, edge_margin_m?, orientation?, angle_deg?}"),
    }),
    Tool('apply_plot_split', handler='apply_plot_split', mutating=True, manifest={
        "tool_name": "apply_plot_split",
        "action_type": "virtual_tool_call",
        "description": ("Creates one plot per piece of a split, recomputed from "
                        "the same arguments. Requires human approval."),
        "usage_hint": ("params.arguments: {zone_id, subject, started_on, "
                       "parts? | strip_width_cm? | widths_cm?, edge_margin_m?, "
                       "orientation?, angle_deg?, name?}"),
    }),
    Tool('copy_plot', handler='copy_plot', mutating=True, manifest={
        "tool_name": "copy_plot",
        "action_type": "virtual_tool_call",
        "description": ("Re-uses a past plot's outline for a new plot — "
                        "'same spot as last year'. No coordinates needed. "
                        "Requires human approval."),
        "usage_hint": "params.arguments: {plot_id, subject?, started_on?}",
    }),
    Tool('end_plot', handler='end_plot', mutating=True, manifest={
        "tool_name": "end_plot",
        "action_type": "virtual_tool_call",
        "description": ("Ends a plot (harvested/failed/removed). The row is KEPT as "
                        "history — it only leaves the map. Requires human approval."),
        "usage_hint": "params.arguments: {plot_id, ended_on?, reason?: harvested|failed|replaced|removed}",
    }),
    Tool('confirm_plot_stage', handler='confirm_plot_stage', mutating=True,
         manifest={
        "tool_name": "confirm_plot_stage",
        "action_type": "virtual_tool_call",
        "description": ("Confirms that a plot moved into a new stage. This MOVES "
                        "THE ANCHOR — the remaining stages are recomputed from the "
                        "date given, so do not invent one: use get_plot's "
                        "stage_proposal.started_on (derived from the data) unless "
                        "the grower states a different day. If stage_proposal is "
                        "null there is nothing to confirm. Requires human approval."),
        "usage_hint": ("params.arguments: {plot_id, stage_key (from "
                       "stage_proposal.stage_key), started_on?: 'YYYY-MM-DD'}"),
    }),
    Tool('reschedule_plot_stage', handler='reschedule_plot_stage',
         mutating=True, manifest={
        "tool_name": "reschedule_plot_stage",
        "action_type": "virtual_tool_call",
        "description": ("Moves a stage boundary for THIS plot — 'transplanting "
                        "slipped a week'. The programme is a reference only and "
                        "is never changed. Boundaries after the one you move "
                        "shift with it; pin the next one too if it must stay. "
                        "Only boundaries still ahead can be moved — a change "
                        "that already happened is confirm_plot_stage. Read "
                        "get_plot's stage_schedule first. Requires human "
                        "approval."),
        "usage_hint": ("params.arguments: {plot_id, stage_key (from "
                       "stage_schedule), days?: 20 | shift_days?: +7|-3 | "
                       "started_on?: 'YYYY-MM-DD'} — exactly one of the three. "
                       "days sets how long THAT stage lasts (same wording as "
                       "the programme); shift_days moves its start boundary."),
    }),
    Tool('set_plot_stage_guidance', handler='set_plot_stage_guidance',
         mutating=True, manifest={
        "tool_name": "set_plot_stage_guidance",
        "action_type": "virtual_tool_call",
        "description": ("Writes what to do in one stage OF THIS PLOT. The "
                        "programme's guidance is general advice for the crop; "
                        "this is 'here, at this time, do X'. Catalogue "
                        "programmes usually ship with none, so write it even "
                        "when the stage shows nothing. An empty string clears "
                        "it and the programme's own text shows again. The "
                        "programme is NOT touched — use modify_program for "
                        "that. Requires human approval."),
        "usage_hint": ("params.arguments: {plot_id, stage_key (from "
                       "stage_schedule), guidance}"),
    }),
    Tool('add_plot_stage', handler='add_plot_stage', mutating=True, manifest={
        "tool_name": "add_plot_stage",
        "action_type": "virtual_tool_call",
        "description": ("Adds a stage to THIS PLOT only — e.g. a top-dressing "
                        "step the standard programme has no room for. 'after' "
                        "names the stage it follows (empty string = first, "
                        "omitted = last). The key is generated. The programme "
                        "is NOT touched. Requires human approval."),
        "usage_hint": ("params.arguments: {plot_id, name, days, after?, "
                       "guidance?}"),
    }),
    Tool('remove_plot_stage', handler='remove_plot_stage', mutating=True,
         manifest={
        "tool_name": "remove_plot_stage",
        "action_type": "virtual_tool_call",
        "description": ("Drops a stage from THIS PLOT only — e.g. a crop that "
                        "goes straight to transplanting with no seedling "
                        "stage. Stages already passed are refused: the ledger "
                        "points at them and removing one loses the answer to "
                        "what was done then. Requires human approval."),
        "usage_hint": "params.arguments: {plot_id, stage_key}",
    }),
    Tool('save_plot_schedule_as_program',
         handler='save_plot_schedule_as_program', mutating=True, manifest={
        "tool_name": "save_plot_schedule_as_program",
        "action_type": "virtual_tool_call",
        "description": ("Registers THIS PLOT's schedule as a reusable "
                        "programme — the stages it actually follows, with the "
                        "lengths as edited and the plot's own guidance. Targets "
                        "are copied, but the reply shows what the plot actually "
                        "measured against each. The plot is "
                        "NOT moved onto the new programme: registering is a "
                        "copy, and changing a running season's interpretation "
                        "would silently change what it was grown for. Requires "
                        "human approval."),
        "usage_hint": ("params.arguments: {plot_id, name?, adopt_targets? "
                       "(take the measured values as the new targets)}"),
    }),
    Tool('undo_plot_stage', handler='undo_plot_stage', mutating=True, manifest={
        "tool_name": "undo_plot_stage",
        "action_type": "virtual_tool_call",
        "description": ("Undoes the most recently confirmed stage change. The row "
                        "is KEPT (marked undone); the previous confirmation becomes "
                        "the anchor again and later stages are recomputed. Only the "
                        "last one can be undone. Requires human approval."),
        "usage_hint": "params.arguments: {plot_id}",
    }),
    Tool('apply_plot_resources', handler='apply_plot_resources', mutating=True,
         physical=True, manifest={
        "tool_name": "apply_plot_resources",
        "action_type": "virtual_tool_call",
        "description": ("Starts the irrigation/fertigation Functions that the "
                        "current stage needs, as resolved FROM THE SITE (the "
                        "programme declares roles, not functions). This makes water "
                        "flow — it is a physical action. Nothing is ever switched "
                        "off. Read get_plot's stage.resources first, and check the "
                        "reply: 'failed' (did not start), 'unresolved' (no device "
                        "for that role here — placement is a human job), "
                        "'ambiguous' (several candidates, so nothing was picked). "
                        "Requires human approval."),
        "usage_hint": "params.arguments: {plot_id}",
    }),
    Tool('delete_plot', handler='delete_plot', mutating=True, manifest={
        "tool_name": "delete_plot",
        "action_type": "virtual_tool_call",
        "description": ("Deletes a plot record outright — for mistakes only. A harvested "
                        "crop should use end_plot so its history survives. "
                        "Requires human approval."),
        "usage_hint": "params.arguments: {plot_id}",
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
    # --- 지도 거리 (@ANCHOR: GEO_DISTANCE_TOOLS, 2026-08-14) ------------------
    # LLM 은 좌표 산술을 조용히 틀린다. 거리는 서버가 세고 LLM 은 받는다.
    # uuid 만 받는 이유는 aot/utils/geo_distance.py docstring 참조 — 이름을
    # 받으면 작물명이 구획이 아니라 소속 zone 으로 해석되어 조용히 틀린다.
    Tool('distance_between', handler='distance_between', manifest={
        "tool_name": "distance_between",
        "action_type": "virtual_tool_call",
        "description": ("Distance in metres between two map entities, by name "
                        "or unique_id. Ambiguous names are returned as "
                        "candidates, never guessed. Read-only."),
        "usage_hint": "params.arguments: {target_a, target_b}",
    }),
    Tool('nearest', handler='nearest', manifest={
        "tool_name": "nearest",
        "action_type": "virtual_tool_call",
        "description": ("Sorts candidate entities by distance from a reference "
                        "entity, by name or unique_id. Read-only."),
        "usage_hint": "params.arguments: {reference, candidates: [name|unique_id, ...]}",
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
    # --- 공간-장치 바인딩 (Phase D, docs/design/geo-device-binding.md) ---------
    # rebind_device 는 config_only 로 면제하지 말 것. 설정 편집처럼 보이지만
    # 결과는 "이 구역에 물을 주는 기계가 바뀐다" 이다 — 승인 없이 실행되면
    # 사람이 모르는 사이에 다른 밸브가 열린다.
    Tool('list_unbound_slots', handler='list_unbound_slots', manifest={
        "tool_name": "list_unbound_slots",
        "action_type": "virtual_tool_call",
        "description": "Lists spatial slots (map zones, markers, facility fittings) that currently have NO device bound — what a device deletion or a swap left behind. The shape survives a device deletion on purpose, so these are real places waiting for a device, not errors. Read-only.",
        "usage_hint": "params.arguments: {map_id (optional), facility_id (optional), kinds (optional — comma-separated: shape,fitting,actuator,sensor_role,weather; omit for all)}. Returns slots[{spatial_kind, spatial_id, role, name, last_device, ...}].",
    }),
    Tool('rebind_device', handler='rebind_device', mutating=True, manifest={
        "tool_name": "rebind_device",
        "action_type": "virtual_tool_call",
        "description": "Moves every MAP slot held by one device (zones, markers) over to a different device, keeping the history of who held each slot. Use when hardware was physically replaced by a DIFFERENT device. Requires human approval — it changes which physical machine a zone commands. NOTE: if the same model was swapped in, updating the existing device's connection settings (DevEUI/address) is the better path and needs no rebinding at all. Facility fittings and sensor roles are refused here on purpose — the facility editor owns those, and a binding written here is erased by the next facility save.",
        "usage_hint": "params.arguments: {old_device_id, new_device_id}. Returns moved[], unassigned[] (channels the new device does not have — left as unassigned slots), refused[] (facility slots), warnings[]. Refuses with conflict=true if the new device already has a marker on the same map.",
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
        "description": "Saves a piece of knowledge into this system's knowledge library so a later query can retrieve it (the write counterpart to knowledge_search). Shelve what you derived, observed, were told, **or researched yourself** — a summary of material you looked up outside this system is exactly what this is for. ALWAYS saved as unconfirmed/ai_curated — you MUST tell the user it's an unconfirmed note you're keeping, not present it as fact. Only shelve something genuinely reusable (a pattern, an answer worth remembering) — not routine chit-chat.",
        "usage_hint": "params.arguments: {content (the knowledge text, required), tags (comma-separated scope tags — crop/livestock/structure/topic, REQUIRED — an untagged note would surface for every query), heading (short title that MUST carry the subject's name AS THE USER SAYS IT — search weighs the heading 3x; when the content came from a lookup table, keep that table's own name too, e.g. '땅콩(Arachis hypogaea) 재배 기준'), attribution (the source title/URL you got this from — omit only if there is none), entity_ref (optional AoT entity unique_id this is about), source_url (the http(s) address you got this from — without it a reviewer cannot check the note), source_ref (when the content came from a lookup here, pass the 'source_ref' that query returned — it marks the note as checkable), content_kind ('prose' default or 'structured'), ttl_hours (optional — set for time-sensitive info like a pest sighting so it expires; omit for a durable observation). RECIPE for 'research X and set it up': knowledge_search -> research -> shelve the summary WITH attribution -> then build on it (create_program etc.), citing it in source_note. Skip the shelve and the next question researches it all over again.",
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
        "usage_hint": "params.arguments: {query (free text, required), top_k (optional, default 3), tags (optional comma-separated scope filter)}.",
    }),

    # --- 참조표 (@ANCHOR: REFERENCE_TABLE_TOOLS, 2026-08-24) --------------------
    # 표를 지식 항목으로 적재하지 않고 등록만 해 두고 물어볼 때 조회한다
    # (reference_table_service 모듈 주석). 도구가 둘인 이유는 등록된 표가
    # 설치마다 달라 **정적인 도구 설명에 담을 수 없기** 때문이다. 둘 다 읽기 전용.
    Tool('list_lookup_sources', handler='list_lookup_sources', manifest={
        "tool_name": "list_lookup_sources",
        "action_type": "virtual_tool_call",
        "description": "Lists everything this system can LOOK THINGS UP IN: reference tables the operator registered (crop requirements, spec sheets) and connected data APIs (measured farm data). Read-only. These are queried on demand, so they are NOT in knowledge_search results — when a question asks for a per-item value or for external measured data and knowledge_search found nothing, check here before answering from your own memory.",
        "usage_hint": "params.arguments: {}. Returns sources[] each with kind. kind='table' -> query_reference_table (look a row up by name; see name_language/aliases). kind='api' -> query_data_source (run one operation with its params).",
    }),
    Tool('query_data_source', handler='query_data_source', manifest={
        "tool_name": "query_data_source",
        "action_type": "virtual_tool_call",
        "description": "Runs one operation against a connected data API right now, instead of relying on what was synced earlier. Read-only. Use it to answer 'what did other farms measure', 'what does this season look like' — questions the stored digest cannot cover because it holds one fixed selection. Always report 'total_available' honestly: a truncated result is not the complete set.",
        "usage_hint": "params.arguments: {source_id (from list_lookup_sources), operation (one of that source's operations), params (object with that operation's parameters), limit (default 5, max 25), columns (comma-separated, or '*')}. Codes like userId/facilityId/croppingSerlNo are not things a person knows — resolve them with smartfarmkorea_lookup first.",
    }),
    Tool('query_reference_table', handler='query_reference_table', manifest={
        "tool_name": "query_reference_table",
        "action_type": "virtual_tool_call",
        "description": "Looks a row up in a registered reference table by name. Read-only. Names are matched in the table's own language (see name_language/aliases). Returns matching rows plus the table's attribution and caveat — quote the caveat when it changes what the numbers mean (e.g. a suitability range is not a greenhouse setpoint). If nothing matches, say so; do not fill the gap from memory.",
        "usage_hint": "params.arguments: {table_id (from list_lookup_sources; omit only when exactly one table exists), query (the name to look up — species, part, variety), limit (default 5), columns (comma-separated; omit for the table's summary columns, '*' for all)}. Use the name the TABLE is keyed by (see name_language/aliases).",
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
        "usage_hint": "params.arguments: {preset_key (required), api_key (required), operations (list of EXACT operation keys — NOT generic words like 'growth'/'환경'; a wrong key returns valid_operations to retry with. 시설 growth keys are crop-specific: growth_strawberry(딸기)/growth_mum(국화)/growth_melon(참외)/growth_other; 노지: growth_radish(무)/growth_cabbage(배추)/growth_garlic(마늘)/growth_onion(양파)/growth_blueberry(블루베리); shared: identity/cropping/env), plus the params each operation needs. For 시설/노지 cropping/growth/env ops: userId, facilityId, croppingSerlNo, itemCode — RESOLVE THESE VIA smartfarmkorea_lookup, never ask the user for a code — and measDate/startDate/endDate (ask the user, YYYY-MM-DD). For 축산: only startDate/endDate (YYYYMMDD, no dashes). Optional: source_id (update instead of create), activate (default true), sync (default true), farm_label/season_label. NOTE: only register a farm whose crop (itemCode) matches what the user asked for — the lookup label shows the crop code. RECIPE: smartfarmkorea_lookup first, then this.",
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
        "description": "Returns the current local wall-clock time and IANA timezone for a specific location (zone/site/facility/device) or the farm-wide default, together with that location's sun times for today (sunrise, sunset, solar noon, civil twilight, day length, whether it is currently daytime, and how many minutes remain until the next sunrise/sunset). Every location resolves its own timezone and sun times from its coordinates. Read-only.",
        "usage_hint": "params.arguments: {target_name (optional — a zone/site/facility/device name, e.g. '3-1', '온실'; omit for the farm-wide default timezone)}. Call this before describing or planning around a specific location/time (e.g. 'is it night there now?', 'should this run today or tomorrow given the local time?') instead of assuming the same timezone applies everywhere. Because farm work follows the solar day rather than the clock — irrigation, misting, shading and venting all do — use the returned 'sun' block instead of assuming fixed hours: check sun.is_daytime and sun.next_event before advising on anything time-sensitive, and prefer phrasing tied to sunrise/sunset over fixed clock hours. sun is null when the location has no resolvable coordinates.",
    }),

    # --- virtual_tool_call tools WITHOUT a manifest entry (dispatch only) ---------
    # Read tools intentionally omitted from the slim LLM manifest; operate_device is
    # bound per-output via mcp_binding instead of a standalone system_tools entry.
    Tool('get_sensor_detail', handler='get_sensor_detail'),
    Tool('get_spatial_tree', handler='get_spatial_tree'),
    Tool('resolve_target', handler='resolve_target_tool', manifest={
        "tool_name": "resolve_target",
        "action_type": "virtual_tool_call",
        "description": "Read-only, NO approval needed. Resolve a place/device name to its exact entity BEFORE calling a write tool that takes target_name (add_schedule, create_note, create_notice, ...). Call this first whenever the request could apply per-sub-unit ('each zone', '구역별', 'per section'). The reply gives target_type, any 'children', and a 'note' saying exactly what a write to this target would and would not touch — follow it.",
        "usage_hint": "params.arguments: {target_name: '<place/device name>'}. Returns {status, target_id, target_type, resolved_name, children, note}. A CROP name also resolves ('콩밭', '상추 재배지' → the zone that crop currently grows in) — growers name plots by what is in them, so pass the user's own words rather than translating them to a map name first. If status is 'needs_disambiguation', show available_targets AND crop_targets to the user via ask_user and retry with the exact name (a crop growing in several zones is deliberately not guessed).",
    }),
    Tool('get_device_list', handler='get_device_list_tool'),
    Tool('search_notes', handler='search_notes_tool', manifest={
        "tool_name": "search_notes",
        "action_type": "virtual_tool_call",
        "description": "Reads FULL/older notes for one entity, or free-text searches notes. Read-only — NO approval needed. NOTE: a per-entity digest (each entity's INITIAL note + a few RECENT notes + total count) is ALREADY pre-injected in context under system_state.note_digests — use that to answer broad questions like '각 장치의 노트 확인' or 'which devices have notes' WITHOUT any tool call. Call this tool only to DRILL DOWN: read the full text or older notes of a SPECIFIC entity (pass target_name with that zone/device name — notes bind by target_id so keyword search alone misses them), or free-text keyword search (query). When target_name resolves to a SITE (포장), results automatically include every descendant zone's notes too (a site rarely has its own notes; per-zone notes like crop info live on the zones) — each result's target_name tells you which zone it came from, so attribute info per-zone rather than treating results as one undifferentiated pile.",
        "usage_hint": "params.arguments: {target_name (location/entity to read notes for, e.g. '3-1', '1포장 1-1', '밸브1'), query (optional keyword), category (optional), limit (optional, default 10)}. Returns note contents (up to 2000 chars each) for summarization.",
    }),
    # search_notes 의 읽기 짝. 파일명까지만 주는 그 도구에서 실제 픽셀로 내려가는
    # 유일한 경로다. manifest=None 이라 인앱 프롬프트 고정비는 0 이고, 발견은
    # search_notes 응답의 조건부 _reading 이 담당한다(첨부가 있을 때만 안내).
    Tool('get_note_attachment', handler='get_note_attachment_tool'),
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
    # comm_offline_devices 의 빈자리를 메우는 **별개 축**. 침묵을 장애로 승격하지
    # 않고 사실(마지막 수신 시각 · 주기 대비 배수)만 보고한다 — 이름과 의미를
    # get_anomalies 와 분리해 두는 것이 이 도구의 존재 이유다.
    Tool('get_device_freshness', handler='get_device_freshness'),
    Tool('get_crop_status', handler='get_crop_status'),
    Tool('get_output_state', handler='get_output_state'),

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
# 노출 등급 배정 — 설계: docs/design/ai-tool-architecture.md
#
# **왜 Tool(...) 안이 아니라 표인가.** 이 배정은 주기적으로 사람이 다시 보는
# 판단이다. 110개 선언에 흩어 두면 "지금 무엇이 상시 노출인가" 를 한눈에 볼 수
# 없어 검토가 불가능해진다. 표는 그 자체가 검토 단위다. 드리프트(도구를 추가하고
# 표를 빠뜨림)는 test_tool_registry_ssot 가 양방향으로 잡는다.
#
# 서랍은 도메인 이름으로 묶는다 — LLM 이 열기 전에 안을 예측할 수 있어야 한다.
DRAWERS = {
    'device':      '장치 조작·상태·검색',
    'measurement': '센서 값·환경·날씨·에너지',
    'function':    '함수·제어기·시퀀스',
    'schedule':    '일정·예약',
    'record':      '노트·공지·지식·조언',
    'space':       '지도·구역·시설·작물 구획',
    'definition':  '장치 정의 추가·수정·삭제',
    'system':      'AI 설정·시스템 상태·진단·매뉴얼',
}

# name → (domain, base_tier, never_demote)
#
# core 는 **5개뿐**이다(2026-08-21 축소). 예전에는 일상 동선을 근거로 16개를
# 상시 노출했는데, 그 크기가 정확히 서랍을 죽인다 — core 가 어중간하게 넓으면
# LLM 은 "이 안에서 어떻게든 되겠지" 로 판단하고 **서랍을 아예 열지 않는다.**
# 없는 기능을 없다고 결론짓거나, 맞지 않는 core 도구로 우회한다. 그래서 기준을
# "자주 쓰는가" 에서 **"이것이 없으면 다음 한 걸음을 뗄 수 없는가"** 로 바꿨다:
# 이름 해소(resolve_target) · 장치 찾기(search_devices) · 값 읽기
# (get_sensor_reading) · 즉시 제어(operate_device) · 승인 큐
# (list_pending_confirmations). 나머지는 전부 서랍이고, 서랍 인덱스가 그 안의
# **도구 이름까지** 싣는다(drawer_index) — 열 이유를 주는 것이 인덱스의 일이다.
#
# never_demote 의 기준은 "사용자가 이름을 말해주는가, AI 가 스스로 떠올려야
# 하는가" — 후자만 보호한다. 설계 문서의 두 절에 근거가 있다.
_TIER_ASSIGNMENT = {
    # --- 장치 ---------------------------------------------------------------
    'operate_device':            ('device', 'core', False),
    'set_output_state':          ('device', 'drawer', False),
    'get_output_state':          ('device', 'core', False),
    'get_control_state':         ('device', 'drawer', False),
    'search_devices':            ('device', 'core', False),
    'get_device_measurements':   ('device', 'core', False),
    'get_device_list':           ('device', 'core', False),
    'list_available_devices':    ('device', 'core', False),
    'list_unbound_slots':        ('device', 'drawer', False),
    'rebind_device':             ('device', 'drawer', False),
    # --- 측정 ---------------------------------------------------------------
    'get_sensor_detail':         ('measurement', 'core', False),
    'get_sensor_reading':        ('measurement', 'core', False),
    'get_zone_sensor_summary':   ('measurement', 'core', False),
    'get_weather':               ('measurement', 'core', False),
    'get_weather_forecast':      ('measurement', 'core', False),
    'get_anomalies':             ('measurement', 'drawer', False),
    'get_device_freshness':      ('measurement', 'drawer', False),
    'get_cumulative_status':     ('measurement', 'drawer', False),
    'get_energy_report':         ('measurement', 'drawer', False),
    # --- 함수 ---------------------------------------------------------------
    'get_function_list':         ('function', 'core', False),
    'get_function_detail':       ('function', 'drawer', False),
    'get_function_doc':          ('function', 'drawer', False),
    'get_active_functions_summary': ('function', 'core', False),
    'activate_function':         ('function', 'core', False),
    'deactivate_function':       ('function', 'core', False),
    'create_function':           ('function', 'drawer', False),
    'delete_function':           ('function', 'drawer', False),
    'modify_function_options':   ('function', 'drawer', False),
    'create_sequence_function':  ('function', 'drawer', False),
    'configure_sequence_day':    ('function', 'drawer', False),
    'modify_sequence_schedule':  ('function', 'drawer', False),
    'modify_sequence_step':      ('function', 'drawer', False),
    'function':                  ('function', 'drawer', False),
    'pid':                       ('function', 'drawer', False),
    # --- 일정 ---------------------------------------------------------------
    'search_schedule':           ('schedule', 'core', False),
    'add_schedule':              ('schedule', 'core', False),
    'edit_schedule':             ('schedule', 'drawer', False),
    'delete_schedule':           ('schedule', 'drawer', False),
    'add_schedule_batch':        ('schedule', 'drawer', False),
    'schedule_device_control':   ('schedule', 'drawer', False),
    # --- 기록 ---------------------------------------------------------------
    'create_note':               ('record', 'core', False),
    'search_notes':              ('record', 'core', False),
    # core 가 아닌 이유: 첨부가 있는 노트에서만 필요하고, 그때는 search_notes
    # 응답이 이름을 직접 알려 준다. 조건부 안내가 있는 드릴다운은 서랍이 맞다.
    'get_note_attachment':       ('record', 'drawer', False),
    'note':                      ('record', 'drawer', False),
    'archive_note':              ('record', 'drawer', False),
    'restore_note_from_archive': ('record', 'drawer', False),
    'search_archives':           ('record', 'drawer', False),
    'get_archived_document':     ('record', 'drawer', False),
    'delete_archive':            ('record', 'drawer', False),
    'set_document_tier':         ('record', 'drawer', False),
    # 읽기 동사만 core 다(2026-08-24 실측으로 결정, C5).
    #
    # 두 동사는 **필요해지는 시점이 다르다.** `knowledge_search` 는 답하기
    # 전에 가장 먼저 불려야 하는데, tools/list 에 없으면 LLM 이 ① 서랍
    # 인덱스에서 이름을 알아보고 ② 열기로 정하고 ③ 부르는 세 단계를 거쳐야
    # 한다. 단계마다 건너뛸 자리가 있고, 건너뛰면 자기 기억으로 답한다 —
    # 라이브러리가 막으려는 바로 그 실패다. `knowledge_shelve` 는 반대로
    # 이미 라이브러리를 쓴 뒤에 필요해지므로, 그때는 record 서랍이 이미
    # 열려 있어 정의가 손에 있다.
    #
    # 비용 실측: 상시 노출 6,958 → 7,164 토큰(+206), 상한 7,200 이라
    # **여유가 36 토큰뿐이다** — core 도구 설명을 늘리려면 무엇을 서랍으로
    # 내릴지 함께 정해야 한다(test_listed_surface_stays_small 이 잡는다).
    # 둘 다 올리면 7,575 로 상한을 넘는다.
    'list_lookup_sources':       ('record', 'drawer', True),
    'query_data_source':         ('record', 'drawer', True),
    'query_reference_table':     ('record', 'drawer', True),
    'knowledge_search':          ('record', 'core', True),
    'knowledge_shelve':          ('record', 'drawer', False),
    'list_notices':              ('record', 'drawer', False),
    'create_notice':             ('record', 'drawer', False),
    'modify_notice':             ('record', 'drawer', False),
    'delete_notice':             ('record', 'drawer', False),
    'list_advice':               ('record', 'drawer', False),
    'submit_advice':             ('record', 'drawer', False),
    'configure_library_source':  ('record', 'drawer', False),
    'list_library_source_types': ('record', 'drawer', False),
    'smartfarmkorea_lookup':     ('record', 'drawer', False),
    # --- 공간 ---------------------------------------------------------------
    'list_plots':            ('space', 'core', False),
    'list_programs':        ('space', 'drawer', False),
    'get_program':          ('space', 'drawer', False),
    'create_program':       ('space', 'drawer', False),
    'modify_program':       ('space', 'drawer', False),
    # 되돌릴 수 없는 동작이지만 **자주 쓰지 않는다** — 생성·편집과 같은 서랍이다
    # (서랍은 빈도가 아니라 도메인으로 묶는다).
    'delete_program':       ('space', 'drawer', False),
    'get_plot':              ('space', 'core', False),
    'get_plot_history':      ('space', 'drawer', False),
    'list_plot_journals':    ('space', 'drawer', False),
    'get_plot_journal':      ('space', 'drawer', False),
    'create_plot_journal':   ('space', 'drawer', True),
    'create_plot':           ('space', 'drawer', False),
    'modify_plot':           ('space', 'drawer', False),
    'end_plot':              ('space', 'drawer', False),
    'delete_plot':           ('space', 'drawer', False),
    'copy_plot':             ('space', 'drawer', False),
    'propose_plot_split':    ('space', 'drawer', False),
    'apply_plot_split':      ('space', 'drawer', False),
    # 단계 원장·자원(P6~P7). 다른 구획 도구와 같은 자리다 — 사용자가 "육묘기
    # 끝났어" / "관수 시작해" 처럼 **이름을 말해 주는** 쪽이라 강등 보호 대상이
    # 아니다(보호는 AI 가 스스로 떠올려야 하는 도구에만 붙인다).
    'confirm_plot_stage':    ('space', 'drawer', False),
    'reschedule_plot_stage': ('space', 'drawer', False),
    'set_plot_stage_guidance': ('space', 'drawer', False),
    'add_plot_stage':        ('space', 'drawer', False),
    'remove_plot_stage':     ('space', 'drawer', False),
    'save_plot_schedule_as_program': ('space', 'drawer', False),
    'undo_plot_stage':       ('space', 'drawer', False),
    'apply_plot_resources':  ('space', 'drawer', False),
    'get_spatial_tree':          ('space', 'core', False),
    'get_crop_status':           ('space', 'drawer', False),
    'list_geo_maps':             ('space', 'drawer', False),
    'delete_geo_shape':          ('space', 'drawer', False),
    'get_device_location':       ('space', 'drawer', False),
    'set_device_location':       ('space', 'drawer', False),
    'get_map_equipment':         ('space', 'core', False),
    'get_map_equipment_detail':  ('space', 'drawer', False),
    'get_facility_capacity':     ('space', 'drawer', False),
    'get_address':               ('space', 'drawer', False),
    'distance_between':          ('space', 'drawer', False),
    'nearest':                   ('space', 'drawer', False),
    # --- 장치 정의 ----------------------------------------------------------
    'create_input':              ('definition', 'drawer', False),
    'modify_input':              ('definition', 'drawer', False),
    'delete_input':              ('definition', 'drawer', False),
    'create_output':             ('definition', 'drawer', False),
    'modify_output':             ('definition', 'drawer', False),
    'delete_output':             ('definition', 'drawer', False),
    'create_gis_input':          ('definition', 'drawer', False),
    'modify_gis_input':          ('definition', 'drawer', False),
    'delete_gis_input':          ('definition', 'drawer', False),
    'activate_gis_input':        ('definition', 'drawer', False),
    'list_gis_inputs':           ('definition', 'drawer', False),
    'list_device_types':         ('definition', 'core', False),
    'get_device_type_options':   ('definition', 'drawer', False),
    'get_input_doc':             ('definition', 'drawer', False),
    'get_output_doc':            ('definition', 'drawer', False),
    # --- 시스템 -------------------------------------------------------------
    # 매니페스트도 핸들러도 없는 이름 검증용 항목이라 노출 비용이 0이다.
    'abstract_plan':             ('system', 'drawer', False),
    # 서랍을 여는 수단이라 core 이자 never_demote 다. 이것이 내려가면 나머지
    # 도구가 영영 안 열린다.
    'open_drawer':               ('system', 'core', True),
    'resolve_target':            ('system', 'core', False),
    'ask_user':                  ('system', 'core', False),
    'get_tool_detail':           ('system', 'core', False),
    # 탭은 페이지(대시보드·입력·출력·함수·프로그램)의 카드를 묶는 UI 구조라
    # 어느 도메인에도 속하지 않는다 — 화면 구성을 다루는 것이므로 system 이다.
    # 대시보드 위젯 — 탭과 같은 '화면 구성' 축이다.
    'list_dashboards':           ('system', 'drawer', False),
    'list_widget_types':         ('system', 'drawer', False),
    'get_widget':                ('system', 'drawer', False),
    'create_widget':             ('system', 'drawer', False),
    'modify_widget':             ('system', 'drawer', False),
    'delete_widget':             ('system', 'drawer', False),
    'list_tabs':                 ('system', 'drawer', False),
    'create_tab':                ('system', 'drawer', False),
    'modify_tab':                ('system', 'drawer', False),
    'delete_tab':                ('system', 'drawer', False),
    'get_local_time':            ('system', 'drawer', False),
    # 아래 둘은 사고 이력 때문에 core 다 — 2026-08-13 예약 10건이 전부 승인
    # 대기에 걸려 장치가 한 번도 안 켜졌는데 그때 아무도 큐를 안 봤다.
    # 서랍에 있으면 AI 도 안 본다.
    'list_pending_confirmations': ('system', 'core', True),
    'analyze_system_failure':    ('system', 'drawer', True),
    'respond_to_confirmation':   ('system', 'drawer', True),
    'read_manual':               ('system', 'drawer', True),
    'get_system_brief':          ('system', 'core', False),
    'get_system_update_status':  ('system', 'drawer', False),
    'get_storage_tier_status':   ('system', 'drawer', False),
    'get_detailed_manifest':     ('system', 'drawer', False),
    'list_ai_agents':            ('system', 'core', False),
    'list_ai_entries':           ('system', 'drawer', False),
    'create_ai_agent':           ('system', 'drawer', False),
    'modify_ai_agent':           ('system', 'drawer', False),
    'delete_ai_agent':           ('system', 'drawer', False),
}

# Tool 은 frozen 이다 — 선언을 뒤에서 고쳐 쓰지 않는다. 배정은 표에서 조회한다.
for _name in _TIER_ASSIGNMENT:
    if _name not in _BY_NAME:
        raise ValueError(
            f"tool_registry: 배정표에 실재하지 않는 도구가 있습니다 — {_name}")


def tier_of(name):
    """(domain, base_tier, never_demote). 배정이 없으면 보수적 기본값."""
    return _TIER_ASSIGNMENT.get(name, ('system', 'drawer', False))


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
    # ── 식생 구획(작기) — docs/design/geo-vegetation-plot.md ──────────────
    # MCP 카탈로그의 정본은 **이 목록**이다. Tool(...) 선언만 추가하면 디스패치는
    # 되지만 `tools/list` 에 안 실려 클라이언트가 도구를 아예 못 본다
    # (2026-08-13 실제로 그렇게 빠뜨려, 서버에는 등록됐는데 Claude/ChatGPT 에는
    # 안 보이는 상태로 한참 헤맸다).
    {
        "tool_name": "list_plots",
        "description": "Lists vegetation plots — what crop is planted where, with area, size (width x length), period and the zone each plot sits in. Growing plots only unless include_ended=true. This is the ONLY source for open-field crops; get_crop_status covers greenhouses. For row/plant counts at a given spacing, call get_plot on the one plot. Pass with_sensors=true to get every plot's sensors in ONE call instead of calling get_plot per plot. Irrigation valves are NOT included here (they are the expensive part); call get_plot on the single plot when you need them. zone_id answers whether one zone has a crop. The reply carries a '_reading' list: the rules for reading THIS result, narrowed to what it actually returned. Follow it — it is instruction, not commentary. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "map_id": {"type": "string", "description": "Map (farm) unique_id. Omit for all maps."},
                "zone_id": {"type": "string", "description": "Zone or site unique_id (from get_spatial_tree/resolve_target). Only plots spatially inside it."},
                "include_ended": {"type": "boolean", "description": "Include finished plots (history). Default: false."},
                "on": {"type": "string", "description": "As-of date 'YYYY-MM-DD' — what was growing on that day."},
                "with_sensors": {"type": "boolean", "description": "Include each plot's referenced sensors (in_plot / from_zone / source). Default false. Use this instead of calling get_plot once per plot when the question spans several plots ('which plots are too wet'). Valves are still excluded."}
            }
        }
    },
    {
        "tool_name": "get_plot",
        "description": "One vegetation plot in detail: crop, variety, planted/expected-end dates, area, dimensions (width x length, for any 'how many rows / will it fit' question that area alone cannot answer), the sensors it reads, the irrigation valves covering it, and its current programme stage. Pass plant_spacing_cm — with row_spacing_cm for a flat layout, or bed_pitch_cm + rows_per_bed for beds — to also get 'capacity_estimate' counted here rather than in your head. The reply carries a '_reading' list: the rules for reading THIS result, already narrowed to the fields it actually returned. Follow it — it is instruction, not commentary. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "row_spacing_cm": {"type": "number", "description": "Spacing between rows in cm (e.g. 40), for a FLAT layout only. Rows are counted across the plot's SHORT side. Not needed — and not used — when a bed layout (bed_pitch_cm + rows_per_bed) is given, because rows_per_bed takes its place."},
                "plant_spacing_cm": {"type": "number", "description": "Spacing between plants within a row in cm (e.g. 15). Plants are counted along the plot's LONG side. Required for any count, in both flat and bed layouts."},
                "edge_margin_cm": {"type": "number", "description": "Extra margin left free at every edge, in cm — headland for machinery turning, bed shoulders, a path. Default 0. Half a spacing is ALREADY free at each edge without this, so only pass it when the plot genuinely needs more (e.g. 200 for a 2 m turning strip). Requires both spacings."},
                "bed_pitch_cm": {"type": "number", "description": "Bed spacing (두둑 간격) in cm, centre to centre — the furrow is INCLUDED, e.g. 160 for a 120 cm bed with a 40 cm furrow. Ask the grower for this as ONE number: they do not count a bed and its furrow separately, and asking for both invites two different readings of the same field. Give it with rows_per_bed to count the layout as actually planted; without it the count assumes a flat layout and OVERSTATES a bedded one by 20-30%."},
                "rows_per_bed": {"type": "integer", "description": "How many rows go on ONE bed, e.g. 2. Whole number, 1 or more. Crop-dependent — peppers take one row, lettuce or cabbage two or three. Must be given together with bed_pitch_cm; the bed spacing alone cannot say how many rows fit. When this is given, row_spacing_cm is not used."}
            },
            "required": ["plot_id"]
        }
    },
    {
        "tool_name": "get_plot_history",
        "description": "What was grown on this same ground before — the basis for crop-rotation and soil-borne disease judgement. Give either a plot or a zone; returns every plot whose area overlaps it, past and present, with the overlapping area. Always check this before advising whether a crop can be planted again. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Use this plot's outline as the reference area."},
                "zone_id": {"type": "string", "description": "Or use a zone's outline (GeoShape unique_id)."},
                "map_id": {"type": "string", "description": "Optional map hint."}
            }
        }
    },
    {
        "tool_name": "list_plot_journals",
        "description": "Saved journals — title, period, status only, no content. Omit target_type/target_id to list every journal on this system; give both to list one plot/zone/site. A journal is a point-in-time snapshot of what was grown, measured, and controlled (never recomputed after generation). journal_id here is an internal handle for get_plot_journal — do not show it to the user, refer to journals by their title and period instead. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_type": {"type": "string", "enum": ["plot", "zone", "site"], "description": "What the journal is about. Omit for all journals."},
                "target_id": {"type": "string", "description": "unique_id of the plot/zone/site. Requires target_type."},
                "limit": {"type": "integer", "description": "Newest first. Default 50, max 200."}
            },
            "required": []
        }
    },
    {
        "tool_name": "get_plot_journal",
        "description": "One saved journal — the exact snapshot from when it was generated (environment, control runtime, notes, stage targets and deltas). IMPORTANT: a journal covering more than a few days does not fit the response limit, and the measurements (env) are the first thing dropped — pass granularity='week'|'month'|'all' to fold the periods, or date_from/date_to to narrow, whenever the period is longer than about three days. Folding is a view-time calculation; the stored snapshot is never altered. status may be pending/running/error; only 'done' carries data. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "journal_id": {"type": "string", "description": "From list_plot_journals — an internal handle, not something to show the user."},
                "granularity": {"type": "string", "enum": ["day", "week", "month", "all"], "description": "Fold the daily records into coarser periods. Cannot be finer than the journal was stored at."},
                "date_from": {"type": "string", "description": "YYYY-MM-DD — drop periods before this date."},
                "date_to": {"type": "string", "description": "YYYY-MM-DD — drop periods after this date."}
            },
            "required": ["journal_id"]
        }
    },
    {
        "tool_name": "create_plot_journal",
        "description": "Builds a journal for a plot/zone/site over a period — a snapshot of what was grown, measured and controlled, meant to be handed to someone else or printed. Reading that much sensor history is expensive, so this requires human approval and runs in the background: it returns a journal_id with status 'pending', and you poll get_plot_journal until status is 'done'. Pass granularity to store weekly or monthly instead of daily when the period is long — that is what makes a season-length journal possible. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_type": {"type": "string", "enum": ["plot", "zone", "site"], "description": "What the journal is about."},
                "target_id": {"type": "string", "description": "unique_id of the plot/zone/site."},
                "start": {"type": "string", "description": "YYYY-MM-DD, first day covered."},
                "end": {"type": "string", "description": "YYYY-MM-DD, last day covered."},
                "granularity": {"type": "string", "enum": ["day", "week", "month"], "description": "How finely to record. Omit to let the system choose (daily, or weekly if that would be too much data). Coarser makes a smaller document; daily detail cannot be recovered later."}
            },
            "required": ["target_type", "target_id", "start", "end"]
        }
    },
    {
        "tool_name": "create_plot",
        "description": "Records a new vegetation plot. Give zone_id (copies that zone/site outline — the usual case, no coordinates needed) OR geometry. For part of a zone, or a new shape, the map design page is the place to draw it. The owning zone is derived from the geometry — do not ask the user for it. Overlapping plots are NORMAL (intercropping), so do not refuse or warn about overlap. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "map_id": {"type": "string", "description": "Map (farm) unique_id."},
                "zone_id": {"type": "string", "description": "PREFERRED. The zone/site shape whose outline to copy — use this when the crop fills a whole zone. You cannot know where a zone is on the map (no tool returns zone boundaries), so inventing coordinates puts the plot in the wrong place and nothing reports it. Get the id from get_spatial_tree."},
                "geometry": {"type": "object", "description": "GeoJSON Polygon or MultiPolygon — only when the caller genuinely has real coordinates. Do NOT construct one from a guessed centre point. Points and lines are rejected."},
                "subject": {"type": "string", "description": "What is in the plot — crop, tree species, animal, whatever the kind implies."},
                "kind": {"type": "string", "enum": ["vegetation", "livestock", "facility", "other"], "description": "Subject kind. Default 'vegetation'. A program can only be attached if its kind matches."},
                "program_id": {"type": "string", "description": "Management program to attach (unique_id from list_programs). Its kind must match this plot's kind. Brings stages, targets and the expected end date."},
                "started_on": {"type": "string", "description": "Start date 'YYYY-MM-DD'."},
                "variety": {"type": "string", "description": "Cultivar (optional)."},
                "name": {"type": "string", "description": "Plot name, e.g. 'front bed' (optional)."},
                "expected_end_on": {"type": "string", "description": "Expected end date 'YYYY-MM-DD' (optional)."},
                "color": {"type": "string", "description": "Display colour '#rrggbb'. Omit to follow the map theme."}
            },
            "required": ["subject", "started_on"]
        }
    },
    {
        "tool_name": "modify_plot",
        "description": "Edits a plot's crop, variety, name, dates, colour or bed layout. Geometry is NOT editable here — reshaping a plot is done on the map design page. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "subject": {"type": "string"},
                "kind": {"type": "string", "enum": ["vegetation", "livestock", "facility", "other"]},
                "program_uuid": {"type": "string", "description": "Attach or change the management program. Empty string detaches. Kind must match."},
                "variety": {"type": "string"},
                "name": {"type": "string"},
                "started_on": {"type": "string", "description": "'YYYY-MM-DD'"},
                "expected_end_on": {"type": "string", "description": "'YYYY-MM-DD'"},
                "color": {"type": "string", "description": "'#rrggbb'"},
                "auto_advance": {"type": "boolean", "description": "Record stage changes for THIS plot without asking. Default false. It is a property of the plot, not of the programme — two plots on the same programme can differ."}
            },
            "required": ["plot_id"]
        }
    },
    {
        "tool_name": "propose_plot_split",
        "description": "Works out how a zone or site would divide into plots, WITHOUT creating anything. Pick the mode with parts, strip_width_cm or widths_cm; direction needs no input in the common case — each parameter below states its own rule, including the mode-dependent default on 'orientation' and when angle_deg may be used. Irregular edges are clipped, so pieces differ in length. You get counts, widths and lengths back, not coordinates. If a parts-only split comes back with aspect_ratio much above ~4:1 the pieces are unusually long and narrow — try orientation='long' or 'short' (whichever was not already used) for squarer pieces. Tell the grower they can SEE the proposal drawn on the map design page (plot mode) before deciding. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_id": {"type": "string", "description": "The zone or site shape to divide (GeoShape unique_id, from get_spatial_tree)."},
                "parts": {"type": "integer", "description": "Divide into this many equal pieces (1 or more). Use for 'three crops in this zone'. Pass 1 to NOT divide — the whole zone becomes a single plot (still inset by edge_margin_m if given), which is what a grower means by 'plant this whole field as one'. Ignored if widths_cm is given."},
                "strip_width_cm": {"type": "number", "description": "Or make pieces this wide in cm, e.g. 160. Use for bed-by-bed. Give this OR parts (or both together for an exact count at an exact width), never with widths_cm."},
                "widths_cm": {"type": "array", "items": {"type": "number"}, "description": "Give each piece its own width in cm instead of equal pieces, e.g. [200, 500, 300] for three different widths in that order. Overrides parts/strip_width_cm entirely. If the widths add up to more than the shape's short axis, only the LAST piece is shortened to fit (see widths_clamped_from_cm in the response) rather than rejecting the whole request; if the earlier pieces alone already don't fit, the request is rejected."},
                "edge_margin_m": {"type": "number", "description": "Leave this much free inside the whole outline, in METERS — headland for machinery. Default 0."},
                "orientation": {"type": "string", "enum": ["long", "short"], "description": "Which side the pieces run along. Optional — if omitted, the default depends on mode: 'long' when strip_width_cm is given (furrows must follow the shape's long side), 'short' when only parts (or only widths_cm) is given (squarer pieces, better for splitting between different crops). Pass explicitly to override that default. Ignored if angle_deg is given."},
                "angle_deg": {"type": "number", "description": "Direction in degrees (0 up to but excluding 180) for the pieces, overriding orientation entirely. Only meaningful when a human has looked at the map and chosen a specific angle (e.g. to match an adjacent field's existing beds) — do not invent a value yourself; the grower must supply it."}
            },
            "required": ["zone_id"]
        }
    },
    {
        "tool_name": "apply_plot_split",
        "description": "Creates one vegetation plot per piece of a split — the write half of propose_plot_split. Pass the SAME zone_id and parts/strip_width_cm/widths_cm, edge_margin_m, orientation and angle_deg used in the proposal (including leaving orientation/angle_deg out if you left them out there) — the split is recomputed, not replayed from a stored proposal, and the same arguments must produce the same default direction. Each piece becomes its own plot row, so check the piece count first: 41 pieces means 41 plots to manage, each with its own notes and history. For one crop over a whole zone use create_plot with zone_id instead. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_id": {"type": "string", "description": "The zone or site shape to divide."},
                "subject": {"type": "string", "description": "Subject for every piece."},
                "started_on": {"type": "string", "description": "Start date 'YYYY-MM-DD'."},
                "parts": {"type": "integer", "description": "Same value used in propose_plot_split."},
                "strip_width_cm": {"type": "number", "description": "Same value used in propose_plot_split."},
                "widths_cm": {"type": "array", "items": {"type": "number"}, "description": "Same value used in propose_plot_split."},
                "edge_margin_m": {"type": "number", "description": "Same value used in propose_plot_split, in METERS. Default 0."},
                "orientation": {"type": "string", "enum": ["long", "short"], "description": "Same value used in propose_plot_split. Leave out if it was left out there — the mode-based default must match."},
                "angle_deg": {"type": "number", "description": "Same value used in propose_plot_split."},
                "variety": {"type": "string"},
                "name": {"type": "string", "description": "Base name; pieces are numbered from it, e.g. 'A' becomes 'A 1', 'A 2'."},
                "expected_end_on": {"type": "string", "description": "'YYYY-MM-DD'"},
                "color": {"type": "string", "description": "'#rrggbb'"}
            },
            "required": ["zone_id", "subject", "started_on"]
        }
    },
    {
        "tool_name": "copy_plot",
        "description": "Creates a new plot on the SAME ground as an existing one, by copying its outline. This is how you answer 'plant it where the beans were last year' — no coordinates are involved. Check get_plot_history first if the same crop is going back on the same ground (soil-borne disease). Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "The plot whose outline to re-use (past or present)."},
                "subject": {"type": "string", "description": "Subject for the new plot. Omit to repeat the source's."},
                "started_on": {"type": "string", "description": "Start date 'YYYY-MM-DD'. Default: today."}
            },
            "required": ["plot_id"]
        }
    },
    {
        "tool_name": "end_plot",
        "description": "Marks a plot as finished (harvested / failed / replaced / removed). The record is KEPT as history — it only leaves the map, so later crop-rotation checks still see it. Prefer this over delete_plot for anything that was actually grown. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "ended_on": {"type": "string", "description": "End date 'YYYY-MM-DD'. Default: today."},
                "reason": {"type": "string", "description": "harvested | failed | replaced | removed. Default: harvested."}
            },
            "required": ["plot_id"]
        }
    },
    # --- 구획 단계 원장 (@ANCHOR: PLOT_STAGE_MCP_PAYLOADS, 2026-08-25) --------
    # 도구 8종은 2026-08-24 (624fa873) 부터 있었지만 **이 목록에 없어 어떤 MCP
    # 클라이언트로도 못 봤다** — 프로그램 도구 5종(위 PROGRAM_MCP_PAYLOADS)이
    # 겪은 것과 같은 함정이고, 이번에도 증상은 같았다: `get_plot` 이 이미
    # `stage_proposal` 을 내면서 "확인하라" 고 안내하는데 정작 확인할 도구가
    # 안 보였다. 서랍 인덱스도 이 목록에서 나오므로 `open_drawer('space')`
    # 에조차 이름이 없었다(디스패치는 registry.TOOLS 라 실행만은 가능했다 —
    # 이름을 아는 클라이언트가 없으니 무의미하다).
    {
        "tool_name": "confirm_plot_stage",
        "description": "Records that a plot has moved into a new stage. This MOVES THE ANCHOR — every remaining stage is recomputed from the date given, so do not invent one: use get_plot's stage_proposal.started_on (which is derived from the data) unless the grower states a different day. If stage_proposal is null there is nothing to confirm. To record a stage that is still ahead, use reschedule_plot_stage instead — this tool is for what already happened. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "stage_key": {"type": "string", "description": "Which stage was entered — take it from get_plot's stage_proposal.stage_key. Stage keys are not guessable; do not compose one."},
                "started_on": {"type": "string", "description": "The day the change happened, 'YYYY-MM-DD'. Default: stage_proposal's own date. Only override it when the grower names a different day."}
            },
            "required": ["plot_id", "stage_key"]
        }
    },
    {
        "tool_name": "reschedule_plot_stage",
        "description": "Moves a stage boundary for THIS plot — 'transplanting slipped a week'. The programme is a reference only and is never changed, so other plots on it are untouched. Boundaries after the one you move shift with it; pin the next one too if it must stay put. Only boundaries still AHEAD can be moved — a change that already happened is confirm_plot_stage. Read get_plot's stage_schedule first for the current dates and keys. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "stage_key": {"type": "string", "description": "Which stage to move — from get_plot's stage_schedule."},
                "days": {"type": "integer", "description": "Make THAT stage last this many days, e.g. 20 for 'raise the seedlings for 20 days'. Same wording as the programme, so the grower need not compute a date. Cannot be used on the last stage — when the season ends is decided by ending the plot."},
                "shift_days": {"type": "integer", "description": "Move that stage's START boundary by this many days: positive to delay (+7), negative to bring forward (-3)."},
                "started_on": {"type": "string", "description": "Or set that boundary to an absolute date 'YYYY-MM-DD' — for when the grower names the day."}
            },
            "required": ["plot_id", "stage_key"]
        }
    },
    {
        "tool_name": "set_plot_stage_guidance",
        "description": "Writes what to do in one stage OF THIS PLOT. The programme's guidance is general advice for the crop; this is 'here, at this time, do X'. Catalogue programmes usually ship with none, so write it even when the stage currently shows nothing. An empty string clears it and the programme's own text shows again. The programme is NOT touched — use modify_program for that. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "stage_key": {"type": "string", "description": "Which stage — from get_plot's stage_schedule."},
                "guidance": {"type": "string", "description": "What to do in that stage, in the grower's own terms. Empty string clears this plot's text and the programme's shows again."}
            },
            "required": ["plot_id", "stage_key"]
        }
    },
    {
        "tool_name": "add_plot_stage",
        "description": "Adds a stage to THIS PLOT only — e.g. a top-dressing step the standard programme has no room for. The programme is NOT touched, so other plots on it keep their own stage list. The stage key is generated here; do not supply one. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "name": {"type": "string", "description": "Stage name as the grower would say it, e.g. '웃거름'."},
                "days": {"type": "integer", "description": "How long the stage lasts, in days. 1 or more."},
                "after": {"type": "string", "description": "stage_key of the stage this one FOLLOWS. Empty string puts it first; omit to put it last. A stage cannot be inserted before an already-confirmed transition."},
                "guidance": {"type": "string", "description": "What to do in that stage (optional)."}
            },
            "required": ["plot_id", "name", "days"]
        }
    },
    {
        "tool_name": "remove_plot_stage",
        "description": "Drops a stage from THIS PLOT only — e.g. a crop that goes straight to transplanting with no seedling stage. Stages already passed are refused: the ledger points at them, and removing one loses the answer to what was done then. The programme is NOT touched. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "stage_key": {"type": "string", "description": "Which stage to drop — from get_plot's stage_schedule."}
            },
            "required": ["plot_id", "stage_key"]
        }
    },
    {
        "tool_name": "save_plot_schedule_as_program",
        "description": "Registers THIS PLOT's schedule as a reusable programme — the stages it actually follows, with the lengths as edited and the plot's own guidance. Targets are copied from the source programme unchanged. The plot is NOT moved onto the new programme: registering is a copy, and changing a running season's interpretation would silently change what it was grown for. Use modify_plot(program_uuid=...) if the grower does want to switch it. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "The plot whose schedule to register."},
                "name": {"type": "string", "description": "Name for the new programme. Omit to derive one from the plot."}
            },
            "required": ["plot_id"]
        }
    },
    {
        "tool_name": "undo_plot_stage",
        "description": "Undoes the most recently confirmed stage change. The row is KEPT (marked undone); the previous confirmation becomes the anchor again and later stages are recomputed from it. Only the last confirmation can be undone. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."}
            },
            "required": ["plot_id"]
        }
    },
    {
        "tool_name": "apply_plot_resources",
        "description": "Starts the irrigation/fertigation Functions that the current stage needs, as resolved FROM THE SITE (the programme declares roles, not functions). THIS MAKES WATER FLOW — it is a physical action. Nothing is ever switched off, and only what the stage declares is touched. Read get_plot's stage.resources first, and then check the reply: 'failed' (did not start), 'unresolved' (no device for that role here — placement is a human job), 'ambiguous' (several candidates, so nothing was picked). Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."}
            },
            "required": ["plot_id"]
        }
    },
    {
        "tool_name": "delete_plot",
        "description": "Deletes a plot record outright. FOR MISTAKES ONLY — the ground's cropping history is lost, which breaks future rotation advice. If the crop was actually grown and is now finished, use end_plot instead. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."}
            },
            "required": ["plot_id"]
        }
    },
    # --- 관리 프로그램 (@ANCHOR: PROGRAM_MCP_PAYLOADS, 2026-08-22) ------------
    # 도구 자체는 2026-08-19 부터 있었지만 **이 목록에 없어 어떤 MCP 클라이언트로도
    # 부를 수 없었다** — 카탈로그에도 서랍에도 없으면 그 도구는 존재하지 않는 것과
    # 같다(탭 도구 4종이 겪은 것과 같은 함정). `create_plot` 의 스키마가 이미
    # "unique_id from list_programs" 라고 안내하고 있었는데 정작 그 도구가 안
    # 보였다. `_TIER_ASSIGNMENT` 에는 이미 space/drawer 로 배정돼 있어, 여기
    # 실리면 곧바로 space 서랍에 들어간다.
    {
        "tool_name": "list_programs",
        "description": "Lists management programmes — a subject's stages with their lengths. A programme says what to grow/raise in what stages; attach one to a plot and the stage, remaining days and expected end date follow from it. Check here before creating one: duplicates are the common mistake. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["vegetation", "livestock", "facility", "other"],
                         "description": "Filter by subject kind."},
                "subject": {"type": "string", "description": "Filter by subject (crop/species/herd) name."},
                "tab_id": {"type": "string", "description": "Filter by the Programs page tab."}
            }
        }
    },
    {
        "tool_name": "get_program",
        "description": "One programme with its full stage list. Each stage may carry 'targets' (numbers the site should hold) and 'guidance' (free text — what to LOOK at and DO BY HAND that stage). Read this before modifying: 'stages' is replaced wholesale, so you need what is already there. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "program_id": {"type": "string", "description": "Programme unique_id."}
            },
            "required": ["program_id"]
        }
    },
    {
        "tool_name": "create_program",
        "description": "Creates a management programme (subject -> stages with lengths). 'subject' is whatever it manages — crop, tree species, turf, herd, structure; AoT is not farm-only. RECIPE: 1) list_programs — does it exist already? 2) research it (knowledge_search; if the library is empty, say so rather than passing your own knowledge off as a source). 3) Map what you find onto YOUR stage keys — sources split stages their own way; never bend a day count to fit one. 4) Blank beats a guess. Display/advice only until a person marks it checked — that check is what gates control, and only a person can give it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Programme name."},
                "subject": {"type": "string", "description": "What it manages."},
                "source_note": {"type": "string", "description": "REQUIRED. What this is based on, and how that source's stages were mapped onto these ones — without it nobody can later judge whether a number is right."},
                "stages": {
                    "type": "array",
                    "description": "Ordered stages. 'days' is that stage's LENGTH, not a cumulative day; only the LAST stage may leave it blank (= until the end).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "Stage key, e.g. transplant / vegetative / flowering / fruiting / harvest."},
                            "name": {"type": "string", "description": "Display name."},
                            "days": {"type": "integer", "description": "Length of this stage in days. Blank only on the last stage."},
                            "targets": {"type": "object", "description": "{item_key: number}, this stage only. Keys MUST exist in target_defs — vegetation already has temp_day, temp_night, rh, co2, dli, vpd. Out-of-range values are refused."},
                            "guidance": {"type": "string", "description": "The half no sensor can do — what to LOOK at and DO BY HAND this stage. This is what a beginner opens the programme for, so fill it when you have a real basis."}
                        }
                    }
                },
                "kind": {"type": "string", "enum": ["vegetation", "livestock", "facility", "other"],
                         "description": "Default 'vegetation'. Only vegetation has fixed target items; other kinds need target_defs before targets."},
                "variety": {"type": "string", "description": "Cultivar / breed."},
                "notes": {"type": "string", "description": "Free notes."},
                "target_defs": {
                    "type": "array",
                    "description": "Extra target ITEMS, only for a value the fixed vocabulary lacks.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "lowercase a-z0-9_ ."},
                            "label": {"type": "string"},
                            "unit": {"type": "string"},
                            "measurement": {"type": "string", "description": "Sensor measurement name this maps to — without it the value is display/advice only (control cannot act on a quantity it has no meaning for)."}
                        }
                    }
                },
                "base_temp_c": {"type": "number", "description": "GDD base temperature. Vegetation only."},
                "resource_defs": {
                    "type": "array",
                    "description": "What the subject NEEDS (roles), never which function does it — that is a fact about a place, so the site resolves it and one programme serves several greenhouses.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": ["irrigation", "fertigation", "other"]}
                        }
                    }
                },
                "tab_id": {"type": "string", "description": "Tab on the Programs page."}
            },
            "required": ["name", "subject", "source_note"]
        }
    },
    {
        "tool_name": "modify_program",
        "description": "Edits a programme, or moves it to another tab. THIS is how an empty programme a person made in the UI gets filled in — same stage shape and same RECIPE as create_program; call get_program first because 'stages' replaces the whole list. Send only the fields you are changing. Built-in/external programmes are refused for anything but tab_id (they must be copied first). Writing stages, target items or base_temp_c sends the programme back for a person to check before it drives control again — that is expected, say so rather than working around it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "program_id": {"type": "string", "description": "Programme unique_id."},
                "name": {"type": "string"},
                "variety": {"type": "string"},
                "stages": {"type": "array", "description": "Replaces the WHOLE stage list — same item shape as create_program (key, name, days, targets, guidance).",
                           "items": {"type": "object"}},
                "target_defs": {"type": "array", "items": {"type": "object"},
                                "description": "Target item definitions — same shape as create_program."},
                "resource_defs": {"type": "array", "items": {"type": "object"}},
                "base_temp_c": {"type": "number"},
                "kind": {"type": "string", "enum": ["vegetation", "livestock", "facility", "other"]},
                "notes": {"type": "string"},
                "source_note": {"type": "string", "description": "Update the basis when you change what the programme says."},
                "tab_id": {"type": "string"}
            },
            "required": ["program_id"]
        }
    },
    {
        "tool_name": "delete_program",
        "description": "Deletes a programme outright — for mistakes only. Refused while any plot still uses it; unassign that plot's programme first (modify_plot with program_id null), or just leave an unused programme in place, which costs nothing. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "program_id": {"type": "string", "description": "Programme unique_id."}
            },
            "required": ["program_id"]
        }
    },
    {
        "tool_name": "get_storage_tier_status",
        "description": "Reports the adaptive document storage state: whether tiering is enabled, how many documents sit in each tier (1=hot, 2=warm, 3=cold), and how many are ACTUALLY archived. A tier value records an intent to move; only a row in the archive means the content was really moved. Relay any 'warning' or 'note' field to the user instead of dropping it.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "tool_name": "search_archives",
        "description": "Searches ARCHIVED documents by their stored metadata. Only returns documents whose content was really moved to the archive — a document marked tier 3 that was never moved will NOT appear here. An empty result is a normal state, not an error.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword matched against stored metadata values. Optional — omit to list all archives."},
                "limit": {"type": "integer", "description": "Max results (1-200). Default: 50"},
                "offset": {"type": "integer", "description": "Pagination offset. Default: 0"}
            }
        }
    },
    {
        "tool_name": "get_archived_document",
        "description": "Retrieves one archived document. Returns metadata only by default; pass include_content=true to decompress and return the full text. Reading an archive updates its last-accessed time, which feeds future tier decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "unique_id of the archived document."},
                "include_content": {"type": "boolean", "description": "Decompress and return full text. Default: false (metadata only)."}
            },
            "required": ["document_id"]
        }
    },
    {
        "tool_name": "archive_note",
        "description": "Archives a note: writes a compressed COPY into cold storage and marks the note tier 3. Requires human approval. The original note text is NOT deleted — archiving never removes content; only the retention policy does.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "unique_id of the note to archive."},
                "retention_policy": {"type": "string", "description": "One of: default, 1year, 3year, 7year, permanent. Default: 'default' (3 years)."}
            },
            "required": ["note_id"]
        }
    },
    {
        "tool_name": "restore_note_from_archive",
        "description": "Reads a note back out of cold storage and moves it to a warmer tier. Requires human approval. If the archive exists but the original note is gone, returns status 'orphan_archive' with the archived text rather than silently recreating it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "unique_id of the archived note."},
                "target_tier": {"type": "integer", "description": "Tier to restore into: 1 (hot) or 2 (warm). Default: 2"}
            },
            "required": ["note_id"]
        }
    },
    {
        "tool_name": "set_document_tier",
        "description": "Changes only a note's tier value (1=hot, 2=warm, 3=cold). Requires human approval. This moves NO data — it records an intent. Use archive_note to actually place content in the archive.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "unique_id of the note."},
                "tier": {"type": "integer", "description": "1 (hot), 2 (warm) or 3 (cold)."}
            },
            "required": ["note_id", "tier"]
        }
    },
    {
        "tool_name": "delete_archive",
        "description": "Deletes the archived COPY of a document (file + index rows). Requires human approval. Irreversible. The original note is untouched, so its tier may still read 3 afterwards.",
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "string", "description": "unique_id of the archived document."},
                "reason": {"type": "string", "description": "Why it is being deleted (recorded in the audit log)."}
            },
            "required": ["document_id"]
        }
    },
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
        "description": "Retrieve the spatial hierarchy (Site > Zone > Device) tree structure with optional depth and type filtering. Answers how the farm is divided; to find a device by name use get_device_list or search_devices instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "depth": {"type": "integer", "description": "Maximum tree depth, root = 1. Default 2 (sites and their zones). Use 3+ to expand devices, 0 for no limit. Cut nodes carry 'children_omitted' — a per-type count of what is below them."},
                "filter_type": {"type": "string", "description": "Filter nodes by type (e.g. 'zone', 'device'). Optional. When given, depth is not applied — otherwise the matches could be cut away before they are found."}
            }
        }
    },
    {
        "tool_name": "resolve_target",
        "description": "Read-only, NO approval needed. Resolve a place/device name to its exact entity BEFORE calling a write tool that takes target_name (add_schedule, create_note, create_notice, ...). Write tools sit behind a human-approval gate that only checks the tool name - the actual name resolution runs only AFTER approval, too late to catch a wrong hierarchy level. Call this first whenever the request could apply per sub-unit ('each zone', '구역별', 'per section'). The reply gives target_type, any 'children', and a 'note' saying exactly what a write to this target would and would not touch - follow it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Name of the place/device to resolve (e.g. '3-1', '1포장 1-1', '온실'). A CROP name works too ('콩밭', '상추 재배지') and resolves to the zone that crop currently grows in — pass the user's own words instead of guessing a map name."}
            },
            "required": ["target_name"]
        }
    },
    {
        "tool_name": "get_zone_sensor_summary",
        "description": "Latest reading plus period statistics (min/max/avg/count) for the sensors of MANY zones in ONE call. Use this whenever a question spans more than one zone or the whole farm — 'which plots are too dry', 'soil moisture across the farm', 'compare the zones' — instead of calling get_sensor_detail once per zone. Narrow it with measurement_type (e.g. 'volumetric_water_content' for soil moisture), otherwise every measurement in those zones comes back and the answer gets long. The reply carries a '_reading' list when this particular result needs care (repeated channels, zones that returned nothing, a degraded read) — follow it. Read-only; it computes on the fly and stores nothing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_ids": {"type": "array", "items": {"type": "string"}, "description": "Zone/site unique_ids to report on. Omit for every named zone and site. Get ids from get_spatial_tree or resolve_target."},
                "measurement_type": {"type": "string", "description": "Restrict to one measurement, e.g. 'volumetric_water_content' (soil moisture), 'temperature', 'humidity'. Substring match. Strongly recommended."},
                "time_range": {"type": "string", "description": "Window for the statistics, e.g. '24h', '7d', '30d'. Default '7d'. The latest value is looked up within the same window."}
            }
        }
    },
    {
        "tool_name": "search_devices",
        "description": "Search for devices (inputs, outputs, cameras, complex devices) by name or type keyword, and/or by the measurement they actually record. When the results contain a complex device (e.g. a PLC), the reply carries a '_reading' note saying how to treat it — follow it. IMPORTANT: to find every sensor of a kind (all soil-moisture sensors, all thermometers), use measurement_type — device names are not reliable for this, the same soil probe may be called '토양온습도_1' on one plot and '온습도_1' on the next, so a name search silently misses sensors.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword for device name or type. Optional when measurement_type is given."},
                "measurement_type": {"type": "string", "description": "Measurement the device records. Substring match on the STORED name, which is rarely the everyday word: soil moisture = 'volumetric_water_content' ('moisture' matches nothing), rain = 'precipitation', wind = 'speed'/'direction'; also 'temperature', 'humidity', 'pressure', 'co2', 'dewpoint', 'battery_voltage', 'vapor_pressure_deficit'. Alone it returns every such device; with query it intersects (query='1포장' + measurement_type='temperature'). On 0 results check the real names with get_device_measurements instead of concluding there are none."}
            }
        }
    },
    {
        "tool_name": "get_device_list",
        "description": "List all registered devices (inputs, outputs, cameras, complex devices) in the AoT system. Use this when the user asks for a full device listing without a specific keyword. When the list contains a complex device (e.g. a PLC), the reply carries a '_reading' note saying how to treat it — follow it.",
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
        "tool_name": "get_note_attachment",
        "description": "Shows one photo/image attached to a note — the actual picture, returned as an image you can look at. Read-only. search_notes only lists attachment FILENAMES; a filename is not the content, so call this whenever a note's photo could settle the question (what the damage looks like, which row is which, what was written on a board). One image per call by design: images are large, so ask for the next filename in a second call. Non-image attachments come back as status 'not_an_image' with their name and size, which is a normal answer, not a failure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "unique_id of the note holding the attachment (from search_notes)."},
                "filename": {"type": "string", "description": "Which attachment to show — one of the names in that note's 'files'. Omit to get the first one. A name that is not attached to this note is refused and the real list is returned."},
                "max_dimension": {"type": "integer", "description": "Longest edge in pixels for the returned image (default 1024, clamped 256-2048). Lower it for a quick look, raise it only when fine detail matters (reading small text, spotting lesions)."}
            },
            "required": ["note_id"]
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
        "description": "Current weather for a site or zone, read from the weather station serving it (KMA / SenseCAP / Ecowitt / OpenWeatherMap, or any input recording wind or rain). 'weather_source' says where the numbers came from. When it is not a real station, or the station does not stand in the requested zone, the reply carries 'weather_source_warning' / 'weather_device_note' spelling out what you must say instead — follow them. Read-only.",
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
        "description": "Equipment drawn on the geo/design map plus a per-zone irrigation design summary. Separate from controllers (Outputs). `sprinklers` (spray heads) and `drip_emitters` (from drip pipe length / spacing) are counted separately and `method` says sprinkler | drip | mixed; when both are present the reply carries a '_reading' note — follow it. Individual equipment (irrigation valves, ventilation fans, heaters/chillers, window and curtain motors) is returned with its specs (flow_lph, pressure_kpa, capacity_kw, airflow_cmh, power_w). Read-only. Use for 'what irrigation equipment is there' and 'flow / sprinklers / drip / piping in zone X'. Report sprinklers and drip separately. (For a greenhouse's calculated heating and cooling design capacity use get_facility_capacity.)",
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
        "description": "Search the knowledge layer - system manuals, synced domain knowledge from external authorities, and notes shelved by you or a colleague - with a free-text query. Read-only. Call this FIRST when asked to research or look something up — it may already be here. If it returns nothing, say so rather than passing your own knowledge off as a source, then knowledge_shelve what you research.",
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
        "description": "Updates custom_options of an existing function and reloads it in the daemon. Requires human approval. Does NOT work on Triggers (including sequences) — their settings are columns, not custom_options; use modify_sequence_schedule for a sequence's timing.",
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
        "tool_name": "configure_sequence_day",
        "description": "Sets ONE weekday's entire run plan on an existing sequence in a single call — which devices run, in what order, how long, and which run together. Use this instead of many modify_sequence_step calls. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "unique_id or exact name of the sequence."},
                "day": {"type": "integer", "description": "Weekday this plan applies to, 0=Mon..6=Sun. Other weekdays are left alone."},
                "slots": {
                    "type": "array",
                    "description": "Ordered run plan. Each entry is one time slot; devices listed in the same slot run SIMULTANEOUSLY.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "devices": {"type": "array", "items": {"type": "string"}, "description": "Device names (or step action_ids) that run together in this slot."},
                            "minutes": {"type": "number", "description": "How long this slot runs, in minutes."},
                            "seconds": {"type": "number", "description": "Alternative to minutes."},
                            "group": {"type": "string", "description": "Optional label for a multi-device slot, shown in the widget."}
                        },
                        "required": ["devices"]
                    }
                },
                "start": {"type": "string", "description": "When the day's run begins, 'HH:MM' local. Optional — keeps the current start if omitted."},
                "end": {"type": "string", "description": "Window end 'HH:MM'. Optional — defaults to exactly one pass."},
                "period_seconds": {"type": "number", "description": "Seconds between repeats. Optional — defaults to one pass, i.e. it runs once."},
                "repeat": {"type": "boolean", "description": "Keep the existing repeat period instead of running once. Optional."}
            },
            "required": ["function_id", "day", "slots"]
        }
    },
    {
        "tool_name": "modify_sequence_step",
        "description": "Configures ONE step of a trigger_sequence: device group, duration, single/total mode, total-step margins, enabled state, label. Steps sharing a group name run SIMULTANEOUSLY as one slot. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "The step's id — get_function_detail returns it as steps[].action_id."},
                "group_name": {"type": "string", "description": "Device group. Steps sharing a name fire together as one slot with one common duration. Empty string ungroups. Not allowed on a 'total' step. Optional."},
                "duration_seconds": {"type": "number", "description": "How long this step stays on. On a grouped step this sets the whole group, since a group has one shared duration. Optional."},
                "mode": {"type": "string", "enum": ["single", "total"], "description": "'single' takes its turn in the running order; 'total' spans the whole cycle (a field's pump). Optional."},
                "enabled": {"type": "boolean", "description": "Whether this step runs at all. Optional."},
                "display_name": {"type": "string", "description": "Label shown in the widget. Empty string clears it back to the device name. Optional."},
                "lead_seconds": {"type": "number", "description": "'total' steps only: start this many seconds after the sequence begins, so the valve opens before the pump runs. Optional."},
                "lag_seconds": {"type": "number", "description": "'total' steps only: stop this many seconds before the sequence ends, so the pump stops before the valve closes. Optional."},
                "order": {"type": "integer", "description": "Run order — the step with the lowest value goes first. Slots follow the order of their first member, so to move a whole group forward set it on that group's earliest step. Optional."},
                "day": {"type": "integer", "description": "Scope this change to ONE weekday (0=Mon..6=Sun) instead of every day. Only enabled, group_name and duration_seconds can be per-weekday — this is how one sequence runs different valves on different days (e.g. an evening pass Thu and a dawn pass Fri) without creating a second sequence. Optional."}
            },
            "required": ["action_id"]
        }
    },
    {
        "tool_name": "modify_sequence_schedule",
        "description": "Changes WHEN a trigger_sequence runs — daily window, cycle period, and which weekdays. Use this (not modify_function_options) for any sequence timing change. The running cycle is kept, not restarted. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "unique_id or exact name of the sequence (from get_function_list)."},
                "start": {"type": "string", "description": "Window start, 'HH:MM' (device local time). Optional."},
                "end": {"type": "string", "description": "Window end, 'HH:MM'. '24:00' means end of day. Optional."},
                "period_seconds": {"type": "number", "description": "Seconds between cycle starts. One full pass of the steps must fit inside the window, or the cycle is cut short. Optional."},
                "weekdays": {"type": "array", "items": {"type": "integer"}, "description": "Days the sequence runs, 0=Mon..6=Sun. Replaces the current set. Optional."},
                "day": {"type": "integer", "description": "Apply start/end/period_seconds to this ONE weekday (0=Mon..6=Sun) instead of every enabled day. Optional."}
            },
            "required": ["function_id"]
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
        "tool_name": "distance_between",
        "description": "How far apart two things on the map are, in metres. DO NOT work distances out yourself from coordinates — that goes wrong quietly and the wrong number becomes a real decision about where to plant or place something. Takes either the name the grower uses ('관리사무소', '3-1', a crop name) or a unique_id; pass the user's own words rather than guessing a map name. If a name matches several things the reply is 'needs_disambiguation' with the candidates and their ids — a crop planted in five plots is the usual cause, and 'how far to the black beans' genuinely has no single answer then. Show those candidates and ask which one; do NOT pick one yourself. Measured centre point to centre point, so two plots that touch along an edge are still reported as tens of metres apart; pass that caveat on rather than presenting the number as a gap between boundaries. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_a": {"type": "string", "description": "Name or unique_id of the first entity (zone/site/facility, vegetation plot, or device)."},
                "target_b": {"type": "string", "description": "Name or unique_id of the second entity."}
            },
            "required": ["target_a", "target_b"]
        }
    },
    {
        "tool_name": "nearest",
        "description": "Ranks things by how far they are from one reference thing — 'which plots are closest to the office', 'which valve is nearest this bed'. Answers the whole question in ONE call: do not loop distance_between over the candidates and sort the numbers yourself. Names or unique_ids both work. Candidates that could not be placed come back in 'unresolved' (nothing of that name) or 'ambiguous' (several matches, with their ids) instead of being dropped — relay BOTH, because a shorter list otherwise reads as 'those were further away', and an ambiguous one is a question you can still get answered by asking which was meant. Distances are centre point to centre point, not edge to edge. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "Name or unique_id of the thing to measure from (e.g. the office)."},
                "candidates": {"type": "array", "items": {"type": "string"}, "description": "Names or unique_ids to rank, closest first. Max 200."}
            },
            "required": ["reference", "candidates"]
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
        "description": "Saves a piece of knowledge into this system's knowledge library so a later query can retrieve it (the write counterpart to knowledge_search). Shelve what you derived, observed, were told, **or researched yourself** — a summary of material you looked up outside this system is exactly what this is for. ALWAYS saved as unconfirmed/ai_curated — you MUST tell the user it's an unconfirmed note you're keeping, not present it as fact. Only shelve something genuinely reusable (a pattern, an answer worth remembering) — not routine chit-chat.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The knowledge text."},
                "tags": {"type": "string", "description": "Comma-separated scope tags (crop/livestock/structure/topic) — REQUIRED, an untagged note would surface for every query."},
                "heading": {"type": "string", "description": "Short title. MUST carry the subject's name AS THE USER SAYS IT — search weighs the heading 3x. When the content came from a lookup table, keep that table's own name (scientific/English) alongside it, so the note is findable from both sides."},
                "attribution": {"type": "string", "description": "Where this came from — source title and/or URL. Without it nobody can verify the note later, so it can never be promoted above unconfirmed."},
                "entity_ref": {"type": "string", "description": "Optional AoT entity unique_id this is about."},
                "source_url": {"type": "string", "description": "The http(s) address you got this from. A reviewer opens it to check the note; without it the note stays unconfirmed."},
                "source_ref": {"type": "string", "description": "When this came from a lookup here, the 'source_ref' that query_reference_table / query_data_source returned. Marks the note as checkable against a source this system has."},
                "content_kind": {"type": "string", "enum": ["prose", "structured"], "description": "Default 'prose'."},
                "ttl_hours": {"type": "number", "description": "Optional — set for time-sensitive info so it expires."}
            },
            "required": ["content", "tags"]
        }
    },
    {
        "tool_name": "list_lookup_sources",
        "description": "Lists everything this system can LOOK THINGS UP IN: reference tables the operator registered (crop requirements, spec sheets) and connected data APIs (measured farm data). Read-only. These are queried on demand, so they are NOT in knowledge_search results — when a question asks for a per-item value or for external measured data and knowledge_search found nothing, check here before answering from your own memory. Each entry has kind: 'table' -> query_reference_table, 'api' -> query_data_source.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "tool_name": "query_data_source",
        "description": "Runs one operation against a connected data API right now, instead of relying on what was synced earlier. Read-only. Answers 'what did other farms measure' — questions the stored digest cannot cover because it holds one fixed selection. Report 'total_available' honestly: a truncated result is not the complete set.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "From list_lookup_sources."},
                "operation": {"type": "string", "description": "One of that source's operations."},
                "params": {"type": "object", "description": "That operation's parameters. Codes (userId/facilityId/croppingSerlNo) come from smartfarmkorea_lookup, never from the user."},
                "limit": {"type": "integer", "description": "Default 5, max 25."},
                "columns": {"type": "string", "description": "Comma-separated columns, or '*'."}
            },
            "required": ["operation"]
        }
    },
    {
        "tool_name": "query_reference_table",
        "description": "Looks a row up in a registered reference table by name. Read-only. Names are matched in the table's own language (see name_language/aliases). Returns matching rows plus the table's attribution and caveat — quote the caveat when it changes what the numbers mean (e.g. a suitability range is not a greenhouse setpoint). If nothing matches, say so; do not fill the gap from memory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "table_id": {"type": "string", "description": "From list_lookup_sources. Omit only when exactly one table is registered."},
                "query": {"type": "string", "description": "The name to look up — species, part, variety."},
                "limit": {"type": "integer", "description": "Maximum rows (default 5)."},
                "columns": {"type": "string", "description": "Comma-separated columns to return; omit for the table's summary set, '*' for all. Ask only for what the question needs — a full row can be several times larger."}
            },
            "required": ["query"]
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
                "operations": {"type": "array", "items": {"type": "string"}, "description": "EXACT operation keys (not generic words) — a wrong key returns valid_operations to retry with. 시설: growth_strawberry/growth_mum/growth_melon/growth_other, 노지: growth_radish/growth_cabbage/growth_garlic/growth_onion/growth_blueberry, shared: identity/cropping/env."},
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
        "description": "KMA short-term hourly forecast. get_weather returns only current values, so pre-emptive advice (temperature about to drop - warm up in advance) needs this. The reply carries the issue time and its age, and a 'warning' when the forecast is too old to advise on — follow it. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "How many hours ahead to return (default 24)."}
            }
        }
    },
    {
        "tool_name": "get_anomalies",
        "description": "On-demand check for anomalies right now - threshold violations, device-offline ratio and an alert level (none/info/warning/critical). It only evaluates; it sends no notifications. Read 'metrics_definitions' in the reply before quoting a number: total_devices counts inputs only (get_system_brief's device_count also counts outputs/cameras, so the two differ by definition), and comm_offline_devices counts only drivers that report a fault themselves - a device that just went silent is never in it, use get_device_freshness for those. For system/integration faults use analyze_system_failure. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scope_type": {"type": "string", "description": "Scope: system | farm | zone | facility (default system)."},
                "scope_id": {"type": "string", "description": "unique_id of the scope target (omit for system)."}
            }
        }
    },
    {
        "tool_name": "get_device_freshness",
        "description": "Which sensors have stopped reporting - the question get_anomalies cannot answer (comm_offline_devices only counts drivers that report a fault themselves). Returns last_seen, age_readable and periods_late per device; stale means the newest value is older than 3x that device's OWN sampling period (minimum 300s), since periods range from 15 seconds to a full day and a fixed threshold would mark healthy daily sensors as broken. Switched-off devices go to inactive_devices, devices with no stored value to no_data_devices. These are observations, not a verdict: silence is not proof of failure, so report what is late and by how many periods rather than calling it a fault. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Check one input only. Omit to check every input."},
                "include_fresh": {"type": "boolean", "description": "Also return the devices that are reporting normally (default false - only counts are given)."}
            }
        }
    },
    {
        "tool_name": "get_crop_status",
        "description": "Crop and growth stage per facility - taken from the plot program growing there (crop, stage, growing-season window) and, when the domain registry is configured, stage-specific optimal ranges. Optimal-growing advice is not possible without knowing the crop, so check this before advising on cultivation. If the growth stage is missing, the reason is returned with it. Every plot entry carries 'stage.guidance' — what THIS programme says to do in the stage it is in now; quote it instead of generic crop advice, and when it is null say the programme has none rather than inventing one. (facilities[].stage is a stage NAME only — guidance never rides the control path.) Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "facility_id": {"type": "string", "description": "Filter by facility unique_id."},
                "facility_name": {"type": "string", "description": "Filter by facility name. Omit for all."}
            }
        }
    },
    {
        "tool_name": "get_output_state",
        "description": "Current ON/OFF state of an output device (valve, pump, relay, etc.) - the read counterpart to set_output_state, which has no way to check what it just toggled. For each channel, returns the live state, how many seconds it has been on, and (when available) the timestamp it actually turned on - taken from the same start-of-session marker the timer widget uses, so confirmation-based outputs (e.g. LoRaWAN) reflect the confirmed time, not the dispatch time. get_control_state only covers actuators registered to an environment-control coordinator; use this for any other output. Does not cover on/off history - only the current session. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Output unique_id. Required."},
                "channel": {"type": "integer", "description": "Restrict to one channel index. Omit for all channels on this device."}
            },
            "required": ["device_id"]
        }
    },

    # ── (C) 오리엔테이션 + 의견 원장 ──────────────────────────────────────────
    {
        "tool_name": "get_system_brief",
        "description": "Start here. Returns what this farm is and how it is doing right now in one call - spatial hierarchy (site/zone/facility), crop and growth stage, active environment-control targets, current anomalies, device count and advice-ledger status. devices.device_count counts every registered entity (inputs+outputs+cameras+complex devices, broken down in count_by_type) while the anomalies block's total_devices counts inputs only - they differ by design. The how_to_proceed list at the end names the next tools to use in order. It does not replace the individual query tools; it tells you where to dig. Read-only.",
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

    # ── (D) 화면 구성 — 대시보드 위젯과 탭 ────────────────────────────────────
    # Tool(...) 선언만으로는 MCP 에 안 나간다. **이 목록이 카탈로그의 정본**이라
    # 여기 없으면 서버에는 등록됐는데 클라이언트는 도구를 아예 못 본다.
    {
        "tool_name": "list_dashboards",
        "description": "The dashboard tabs and the widgets on each one - what the user actually sees when they open AoT. Use it before changing anything on a dashboard, so you are working from the real layout rather than assuming one. Widget settings are omitted by default because a single widget (a map, a facility) can carry a large configuration; pass with_options only when you need them, or use get_widget for one widget. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tab_id": {"type": "string", "description": "Restrict to one dashboard tab. Omit for all of them."},
                "with_options": {"type": "boolean", "description": "Include each widget's full settings. Off by default - it can make the response very large."}
            }
        }
    },
    {
        "tool_name": "list_widget_types",
        "description": "The widget types installed on this system (gauge, graph, map, camera, timer, facility, …), and the option schema of one of them. Knowing a type's name is NOT enough to create one - each type takes different options - so call this with widget_type before create_widget and use the ids it returns. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "widget_type": {"type": "string", "description": "A type from the list. Given, the reply includes that type's option schema and default size. Omitted, you get the list of types only."}
            }
        }
    },
    {
        "tool_name": "get_widget",
        "description": "One widget in detail: which tab it is on, its size and position, its current settings, and the schema those settings follow. Use it before modify_widget so you change one setting rather than overwriting a configuration you have not seen. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "widget_id": {"type": "string", "description": "Widget unique_id, from list_dashboards."}
            },
            "required": ["widget_id"]
        }
    },
    {
        "tool_name": "create_widget",
        "description": "Adds a widget to a dashboard tab. Requires human approval. Get tab_id from list_dashboards and the option ids from list_widget_types first: an option name that is not in that type's schema is REJECTED, not ignored, so a typo comes back as an error instead of a widget that silently does nothing. The widget is placed at the bottom of the tab so it never displaces what the user is currently looking at. If it is the first widget of its type on this system the reply sets requires_restart - tell the user, and do not restart anything yourself.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tab_id": {"type": "string", "description": "Dashboard tab to add it to (from list_dashboards)."},
                "widget_type": {"type": "string", "description": "A type from list_widget_types."},
                "name": {"type": "string", "description": "Title shown on the widget. Defaults to the type's name."},
                "options": {"type": "object", "description": "The type's own settings, keyed by the option ids from list_widget_types. Anything not in that schema is rejected."},
                "width": {"type": "integer", "description": "Grid columns. Defaults to the type's own default."},
                "height": {"type": "integer", "description": "Grid rows. Defaults to the type's own default."}
            },
            "required": ["tab_id", "widget_type"]
        }
    },
    {
        "tool_name": "modify_widget",
        "description": "Changes a widget's name, size, position, tab or settings. Requires human approval. ONLY what you pass is changed - an omitted argument means 'leave it alone', not 'clear it' - and options are MERGED into the existing settings rather than replacing them, so you can change one field without knowing the rest. Read the current state with get_widget first when you are changing settings.",
        "input_schema": {
            "type": "object",
            "properties": {
                "widget_id": {"type": "string", "description": "Widget unique_id."},
                "name": {"type": "string", "description": "New title."},
                "options": {"type": "object", "description": "Settings to merge in, keyed by this type's option ids."},
                "width": {"type": "integer", "description": "Grid columns."},
                "height": {"type": "integer", "description": "Grid rows."},
                "position_x": {"type": "integer", "description": "Grid column of the top-left corner."},
                "position_y": {"type": "integer", "description": "Grid row of the top-left corner."},
                "tab_id": {"type": "string", "description": "Move the widget to another dashboard tab."}
            },
            "required": ["widget_id"]
        }
    },
    {
        "tool_name": "delete_widget",
        "description": "Removes a widget from the dashboard. Requires human approval. This deletes the widget and its settings; it does not touch the devices or data the widget was displaying.",
        "input_schema": {
            "type": "object",
            "properties": {
                "widget_id": {"type": "string", "description": "Widget unique_id, from list_dashboards."}
            },
            "required": ["widget_id"]
        }
    },
    {
        "tool_name": "list_tabs",
        "description": "Tabs group the cards on a page into folders - the same mechanism on the Dashboard, Input, Output, Function and Programs pages. For dashboards, list_dashboards gives the same tabs plus their widgets. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_type": {"type": "string", "description": "Which page: dashboard | input | output | function | program."}
            },
            "required": ["page_type"]
        }
    },
    {
        "tool_name": "create_tab",
        "description": "Creates a new tab on a page. Requires human approval. The name is generated if you omit it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "page_type": {"type": "string", "description": "dashboard | input | output | function | program"},
                "name": {"type": "string", "description": "Tab name."}
            },
            "required": ["page_type"]
        }
    },
    {
        "tool_name": "modify_tab",
        "description": "Renames a tab. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tab_id": {"type": "string", "description": "Tab unique_id, from list_tabs."},
                "name": {"type": "string", "description": "New name."}
            },
            "required": ["tab_id", "name"]
        }
    },
    {
        "tool_name": "delete_tab",
        "description": "Deletes a tab. Requires human approval. On the Input/Output/Function pages this also deletes the cards inside it, exactly as the UI does - check list_tabs and move anything worth keeping first. On Programs the cards are never deleted this way; they move to the page's default tab, because a programme may still be in use by a plot elsewhere. The last remaining tab on a page cannot be deleted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tab_id": {"type": "string", "description": "Tab unique_id, from list_tabs."}
            },
            "required": ["tab_id"]
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


def write_tools() -> frozenset:
    """Every state-changing tool, INCLUDING the approval-exempt config_only ones.

    This is the set that decides 'is this a write?' — role check, audit
    permission column, and hiding tools from read-only keys. Approval is a
    separate, narrower question; use approval_required_tools() for that.
    Keeping the two apart is the point: a config_only tool must still be
    refused for a read-only key and must still land in the audit log as a
    write, even though nobody has to click Approve for it."""
    return frozenset(t.name for t in TOOLS if t.mutating or t.physical)


def config_only_tools() -> frozenset:
    """Write tools exempt from human approval — see the _CONFIG_ONLY note above."""
    return frozenset(t.name for t in TOOLS if t.config_only)


def virtual_approval_tools() -> frozenset:
    """Mutating virtual tools that require human approval at DISPATCH
    (ai_dispatch_service._VIRTUAL_APPROVAL_TOOLS). Physical control is gated
    separately by the P4 hard gate, so it is NOT included here."""
    return frozenset(t.name for t in TOOLS if t.mutating and not t.config_only)


def approval_required_tools() -> frozenset:
    """Tools the PLANNER executor must intercept as pending_approval
    (ai_planning_service._APPROVAL_REQUIRED_TOOLS): every mutation PLUS the
    physical-control / scheduling tools, MINUS the config_only ones."""
    return frozenset(t.name for t in TOOLS
                     if (t.mutating or t.physical) and not t.config_only)


def tiering_enabled() -> bool:
    """등급 적용 여부. **기본은 꺼짐이다.**

    켜면 매니페스트가 core + 서랍 목록으로 줄고, 나머지는 `open_drawer` 로만
    닿는다. 배포만으로 동작이 바뀌면 안 되므로 기본을 끔으로 두었다 — 켜는 것이
    명시적 결정이어야 하고, 문제가 생기면 이 스위치 하나로 되돌아간다.

    환경변수로 둔 이유: 안전 스위치는 **DB 가 이상해도 동작해야** 한다.
    """
    return os.environ.get('AOT_AI_TOOL_TIERING', '0') == '1'


def _drawer_index_manifest() -> Dict[str, Any]:
    """서랍 목록을 도구 하나로 싣는다 — 상시 노출.

    서랍의 **존재와 내용**까지 숨기면 LLM 은 열 생각을 못 한다. 설명은
    DRAWERS 에서, 도구 이름은 배정표에서 만들어 드리프트가 생기지 않게 한다.

    **도구 이름까지 싣는 것이 핵심이다.** 서랍 이름과 한 줄 설명만으로는 LLM 이
    자기가 찾는 기능이 그 안에 있는지 확신하지 못해, 열어 보는 대신 "그런 기능은
    없다" 로 결론짓거나 손에 든 core 도구로 우회한다 — 서랍을 안 여는 실패는
    에러가 아니라 **조용한 오답**이라 로그에도 안 남는다. 이름이 보이면 판단이
    추측에서 조회로 바뀐다. 이름만이면 서랍 전체를 실어도 3KB 미만이라, 카탈로그
    전량(약 56KB)에 비하면 무시할 비용이다.

    `available` 은 **이 표면이 실제로 가진 도구**로 좁힌다. 여기서는 매니페스트가
    있는 도구뿐이다(`open_drawer` 핸들러가 manifest 기준으로 돌려주므로, 그 밖의
    이름을 광고하면 열어도 안 나온다).
    """
    available = {t.name for t in TOOLS if t.manifest}
    listing = ' / '.join(
        '%s(%s): %s' % (name, desc, ', '.join(tools))
        for name, desc, tools in (
            (n, d, tools_in_drawer(n, available=available))
            for n, d in DRAWERS.items())
        if tools)
    return {
        "tool_name": "open_drawer",
        "action_type": "virtual_tool_call",
        "description": (
            "Opens a drawer and returns the full definitions of the tools inside. "
            "Only a handful of everyday tools are listed up front; everything else "
            "lives in a drawer, grouped by what it is for. The tool names in each "
            "drawer are listed below, so check them before you conclude that "
            "something cannot be done here or settle for a listed tool that only "
            "roughly fits — open the drawer and use the real one. "
            "Drawers: " + listing),
        "usage_hint": "params.arguments: {drawer: '<drawer name from the list>'}",
    }


def core_tools() -> frozenset:
    """상시 노출 도구 — 개발 단계의 유효 등급이 곧 base_tier 다."""
    return frozenset(n for n in _BY_NAME if tier_of(n)[1] == 'core')


def never_demote_tools() -> frozenset:
    """호출이 적어도 자동 강등하지 않는 도구."""
    return frozenset(n for n in _BY_NAME if tier_of(n)[2])


def drawer_index(available=None) -> List[Dict[str, Any]]:
    """서랍 목록 — 이름 + 한 줄 + **그 안의 도구 이름들**.

    상시 노출에 남긴다. 서랍의 존재까지 숨기면 LLM 은 열 생각을 못 한다.

    도구 **이름까지** 싣는 것이 이 인덱스의 핵심이다. 서랍 이름과 한 줄 설명만
    보여 주면 LLM 은 자기가 찾는 기능이 그 안에 있는지 확신하지 못해, 열어
    보는 대신 "그런 기능은 없다" 로 결론짓거나 손에 든 core 도구로 우회한다
    (서랍을 안 여는 실패는 에러가 아니라 **조용한 오답**으로 나타난다).
    이름 목록이 있으면 판단이 추측에서 조회로 바뀐다 — `get_weather_forecast`
    라는 이름이 measurement 서랍에 보이면 열지 말지가 더는 도박이 아니다.
    비용은 전량 실어도 3KB 미만이라, 카탈로그 전량(79KB)에 비하면 무시할 수준이다.

    available: 이 표면이 실제로 가진 도구 이름 집합. 주면 교집합만 싣는다.
        표면마다 도구 집합이 다르므로(MCP 카탈로그 ≠ 내부 매니페스트) 인덱스가
        **없는 도구를 광고하면 안 된다** — 열어도 안 나오는 이름은 LLM 을
        서랍에서 한 번 더 멀어지게 만든다.
    """
    return [{'drawer': name, 'description': desc,
             'tools': tools_in_drawer(name, available=available)}
            for name, desc in DRAWERS.items()]


def tools_in_drawer(drawer: str, available=None) -> List[str]:
    """그 서랍 안의 도구 이름 — 상시 노출이 아닌 것만.

    available 을 주면 그 표면에 실재하는 것만 남긴다(drawer_index 주석 참조)."""
    names = (n for n in _BY_NAME
             if tier_of(n)[0] == drawer and tier_of(n)[1] != 'core')
    if available is not None:
        avail = set(available)
        names = (n for n in names if n in avail)
    return sorted(names)


def manifest_system_tools() -> List[Dict[str, Any]]:
    """The system_tools list for get_action_manifest — emitted in declaration
    order, byte-identical to the original hand-written entries.

    등급이 켜져 있으면 core 만 싣고 서랍 목록을 더한다. 꺼져 있으면 예전과
    **바이트 단위로 같다** — SSOT 스냅샷 검사가 그것을 고정한다."""
    entries = [dict(t.manifest) for t in TOOLS if t.manifest]
    if not tiering_enabled():
        return entries
    core = core_tools()
    kept = [e for e in entries if e.get('tool_name') in core]
    kept.append(_drawer_index_manifest())
    return kept


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
    if not tiering_enabled():
        return out
    core = core_tools()
    kept = [e for e in out if e["tool_name"] in core]
    index = _drawer_index_manifest()
    kept.append({
        "tool_name": index["tool_name"],
        "description": index["description"],
        "input_schema": {
            "type": "object",
            "properties": {"drawer": {
                "type": "string",
                "description": "Drawer name from the list in the description.",
                "enum": sorted(DRAWERS)}},
            "required": ["drawer"],
        },
    })
    return kept
