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
import functools
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
    record_write: persists a RECORD (note, knowledge entry) with no device or
                 configuration effect. It is a write — role, read-only key,
                 group scope, advice-only mode and audit all apply exactly as
                 for other writes — but it never needs human approval. The
                 required role permission mirrors the web page that writes the
                 same record (`edit_settings`). See _RECORD_WRITE note below.
    advisory_write: persists an ADVICE row (submit_advice) — the channel a
                 refused caller is told to use instead. Audited as a write, but
                 NOT in write_tools(): read-only keys and advice-only mode may
                 still submit; only roles that cannot use the AI at all
                 (`use_ai_chat` off — Guest/Kiosk by default) are refused.
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
    record_write: bool = False
    advisory_write: bool = False
    manifest: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# _RECORD_WRITE — 승인은 없지만 쓰기인 기록 도구 (2026-09-23).
#
# create_note·knowledge_shelve 는 "승인이 필요 없다"는 판단(2026-07-18/19)을
# "쓰기가 아니다"로 표현해 왔다(플래그 없음 = 읽기). 그 결과 게이트가 읽기로
# 분류해 읽기 전용 API 키, 보기 전용 역할, 조언 전용 모드에서도 노트와 지식을
# 저장할 수 있었고 그룹 스코프도 보지 않았다. 웹은 같은 기록에 `edit_settings`
# 를 요구한다(routes_notes_api·routes_ai_library).
#
# '쓰기인가'와 '승인이 필요한가'는 다른 질문이다(config_only 와 같은 구분).
# record_write 는 앞의 답만 예로 바꾼다 — 승인 면제는 그대로다. 필요 권한은
# 웹과 같은 edit_settings(mcp_auth.role_can_record)이고, 제어 권한
# (edit_controllers)과 일부러 다르게 둔다.
#
# 새 도구가 기록만 남긴다면 여기에 넣고, 아무 플래그 없이 두지 말 것 —
# 플래그 없음은 '읽기'이고, 읽기는 누구에게나 열린다.
# ---------------------------------------------------------------------------


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
#
# 2026-09-09 — add_schedule · add_schedule_batch 추가.
#
# 사용자 지적: "노트·일정 작성 정도에도 승인이 필요해 보이지 않는다." 확인해보니
# `add_schedule_tool` 구현은 `SchedulerJobMeta` 행 하나를 `action_type='human'`으로
# 적을 뿐이다 — APScheduler 트리거를 만들지 않으므로 이 도구만으로는 어떤 장비도
# 움직이지 않는다. 사람이 그 일정을 읽고 직접 수행해야만 실제 효과가 생기는데,
# 그 "사람이 본다"는 단계 자체가 activate_function 같은 별도 게이트 역할을 한다 —
# 심지어 자동 실행 경로가 아예 없으므로 시퀀스 설정 편집 사례보다도 약하다.
# edit_schedule/delete_schedule 로 언제든 고치거나 지울 수 있어 되돌릴 수도 있다.
#
# 물리 장비를 실제로 예약 제어하는 `schedule_device_control`은 위 1번 조건 자체가
# 성립하지 않으므로 여기 넣지 않는다 — 계속 승인 대상이다.
#
# 2026-09-09 — create_gis_input · create_ai_agent 추가(사용자 지적의 연장선).
#
# 둘 다 "항상 비활성으로 생성되고, 활성화는 별도로 게이트된다"는 create_sequence_function
# 과 같은 구조다. GIS Input은 `create_gis_input` 구현 자체가 매번 비활성으로 만들고
# `activate_gis_input`(계속 승인 대상)을 거쳐야 실제로 지도/날씨 조회에 쓰인다. AI Agent는
# 한 걸음 더 강하다 — `create_ai_agent`가 `is_activated=False`로 만드는 것은 물론, **AI가
# 호출할 수 있는 활성화 도구 자체가 없다**(`activate_ai_agent` 없음). 파이프라인 라우터/
# 감독자/작업자 선택 쿼리가 전부 `is_activated=True`만 보므로(`ai_agent_service.py`), 오직
# 사람이 웹 UI에서 활성화해야만 그 에이전트가 실제로 쓰인다.
#
# `modify_gis_input`/`modify_ai_agent`는 여기 넣지 않았다 — 이미 활성 상태인 대상을
# 고치면 시퀀스 사례처럼 "즉시 반영"되는데, GIS Input의 옵션(api_key 등)은 시퀀스
# 시간표와 비슷한 무게로 볼 여지가 있지만, AI Agent의 system_prompt/tool_access는
# **AI 자신의 동작지침·도구권한을 스스로 고치는 셈**이라 위험의 종류가 다르다(밸브
# 타이밍 조정과 달리 프롬프트 인젝션/안전장치 무력화에 가깝다) — 사용자 판단 보류.
# `activate_gis_input`/`delete_gis_input`/`delete_ai_agent`는 각각 "실제로 발동하는
# 순간"과 "복구 불가"라 위 금지 조항대로 승인 대상으로 남는다.
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
        "description": "Reads a specific section from the AoT system manuals. Requires 'target_id' (filename from manual_index_files). 'params.section' (heading name) is optional — OMIT it to get that document's table of contents, then call again with one of the returned headings.",
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
    Tool('add_schedule', handler='add_schedule_tool', physical=True, config_only=True, manifest={
        "action_type": "add_schedule",
        "description": "Register a human work schedule or memo. Use for manual tasks such as weeding, inspection, or cleaning. Saves immediately (no approval) — it only records a reminder for a person; it does not move any equipment.",
        # Corrected 2026-07-08: add_schedule_tool proposes a SchedulerJobMeta
        # job (source_type='human'), NOT a Notes row — verified against the
        # actual implementation. Use create_note for a plain memo/journal entry.
        "usage_hint": "For a DATED work task/event (weeding, spraying, harvest, inspection) use this — it registers a human work item. Params: {date, content, worker, time, tags, target_name, target_id?}. PASS target_name (a zone/facility/device name like '온실', '3-1', '1포장 1-1') whenever the user names a place, so the schedule links to that real location (map + location search). If the name is not found the tool returns available_targets; if it names several places it returns candidates — call ask_user to pick, then retry with the chosen candidate's use_name (or pass its target_id as target_id when it has no use_name). Omit target_name only for a farm-wide event with no specific place. This is a GIS-based system: target_name resolves to exactly ONE entity and never auto-expands to its children. Before writing, if the request could apply per sub-unit ('각 구역별', 'each zone') call resolve_target(target_name) first — read-only, no approval — to see whether the name is a container with 'children'; if so, use add_schedule_batch to write all of them in one call instead of one add_schedule call per child. For an undated memo/note, use create_note instead.",
    }),
    Tool('add_schedule_batch', handler='add_schedule_batch_tool', physical=True, config_only=True, manifest={
        "action_type": "add_schedule_batch",
        "description": "Register MULTIPLE per-entity work schedules in ONE call — use instead of N separate add_schedule calls whenever a request applies per sub-unit ('각 구역별로', 'each zone'). Saves immediately (no approval, like add_schedule). Prefer this over N separate calls anyway: it rejects a duplicate target_name up front, and given window_start/window_end it runs a single capacity check across all entries that per-call add_schedule cannot see.",
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
        "usage_hint": "params.arguments: {job_id (required — from search_schedule), date (optional YYYY-MM-DD, keeps existing date if omitted), time (optional HH:MM, keeps existing time if omitted), duration_minutes (optional — new duration in minutes, replaces the existing one), content (optional new text), worker (optional new assignee), target_name (optional — re-link to a different zone/facility/device by name; an unknown name returns available_targets, a name shared by several places returns candidates → ask_user then retry with the chosen use_name), target_id (optional — re-link by unique_id instead)}.",
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
    # 장치 하나를 파악하는 데 드는 왕복을 하나로 접는다 (2026-09-21). 지금까지는
    # search_devices(무엇인지) → get_device_measurements(무엇을 재는지) →
    # get_device_location(어디인지) → get_device_freshness(살아있는지) 를 따로
    # 불러야 했다 — MCP 는 호출마다 고정비가 크다. 읽기 전용.
    Tool('get_device_detail', handler='get_device_detail', manifest={
        "tool_name": "get_device_detail",
        "action_type": "virtual_tool_call",
        "description": "One device's full picture in one call. Replaces chaining search_devices + get_device_measurements + get_device_location. Read-only.",
        "usage_hint": "params.arguments: {device_id} (unique_id or name). Ambiguous name → needs_disambiguation + candidates.",
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
    Tool('create_gis_input', handler='create_gis_input', mutating=True, config_only=True, manifest={
        "tool_name": "create_gis_input",
        "action_type": "virtual_tool_call",
        "description": "Creates a new GIS Input (map layer/provider, e.g. gis_vworld, gis_openweather). layer_type must be a 'gis_*' entry from list_device_types(kind='input'). Always created DEACTIVATED — call activate_gis_input once configured. Saves immediately (no approval); activate_gis_input still requires approval.",
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
    Tool('create_ai_agent', handler='create_ai_agent', mutating=True, config_only=True, manifest={
        "tool_name": "create_ai_agent",
        "action_type": "virtual_tool_call",
        "description": "Creates a new AI pipeline agent bound to an AIEntry. Always created DEACTIVATED (is_activated=False) — saves immediately (no approval). There is no AI-callable activation tool: only a human, via the web UI, can make it live, so it can have no effect until then.",
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
        "description": "Activates an existing function by function_id. Requires human approval. Refuses a trigger_sequence with no steps.",
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
    # record_write (2026-09-23): still no approval, but it IS a write — role
    # (edit_settings, as on the web), read-only key, group scope and advice-only
    # mode apply. See _RECORD_WRITE.
    Tool('create_note', handler='create_note', record_write=True, manifest={
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
    # record_write (2026-09-23): not approval-gated, but a write — see _RECORD_WRITE.
    Tool('knowledge_shelve', handler='knowledge_shelve', record_write=True, manifest={
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
    # 실행 대신 제안을 남기는 통로다. 다만 행을 저장하므로 '읽기'도 아니다 —
    # advisory_write 로 선언해 감사에는 쓰기로 남고, AI 를 못 쓰는 역할
    # (use_ai_chat 없음)은 거부된다. 읽기 전용 키·조언 전용 모드에는 열려 있다
    # (거부 안내가 조언 제출을 권하기 때문이다). create_note 는 record_write
    # (_RECORD_WRITE 주석)로 옮겼다.
    Tool('submit_advice', handler='submit_advice', advisory_write=True),
    Tool('list_advice', handler='list_advice'),

    # 오리엔테이션 진입점 — 외부 AI가 접속 직후 한 번 호출해 무엇을 언제 쓸지 파악한다.
    Tool('get_system_brief', handler='get_system_brief'),

    # --- registry-only validation names (dispatched elsewhere, NOT via tool_map) --
    # Known tool names that resolve_action must accept, but which are handled by the
    # native tool bridge, the legacy execute_action if/elif chain, or as special
    # action types. handler=None keeps them out of the VirtualToolResolver tool_map.
    Tool('abstract_plan', handler=None),
    Tool('note', handler=None, record_write=True),   # 옛 action_type 'note' (NoteResolver)
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
    'get_device_detail':         ('device', 'core', False),
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
# API 키별 도구 묶음(tool profile) — 외부 MCP 표면에서 **무엇을 보여 주는가**.
#
# 키의 scope(full/readonly)는 "무엇을 해도 되는가"(보안 경계)이고, 묶음은
# "무엇을 목록에 싣는가"(표면)다. 둘은 다른 축이라 섞지 않는다 — 묶음 밖 도구를
# 부르면 거절하지만, 그것은 목록과 실행을 맞추는 일관성일 뿐 권한 판단이 아니다.
#
#   operations    — 일상 운영(기본). 조회·제어·일정·기록·작기 단계 사건.
#   configuration — 운영 + 설정·작성(장치 정의, 자동화·시퀀스 작성, 구획·
#                   프로그램 작성, 지도 배치, 화면 구성, AI 설정, 보관 문서·
#                   라이브러리 소스). **더하기 방식**이라 운영을 항상 포함한다.
#
# 표 값은 넷 중 하나다:
#   'operations' / 'configuration' — 그 묶음부터 보인다.
#   'retired'   — 외부 MCP 목록에서 뺀 도구(같은 일을 하는 운영 도구가 있다).
#                 인앱 AI 처럼 묶음이 없는(제한 없는) 호출자에게는 그대로 있다.
#   'drawer'    — 서랍 기구(open_drawer·get_tool_detail·use_tool). 묶음과
#                 무관하게 서랍 스위치를 따른다.
#
# **왜 Tool(...) 안이 아니라 표인가** — 서랍 배정표와 같은 이유다. 이 분류는
# 사람이 주기적으로 다시 보는 판단이고, 표 하나가 곧 검토 단위다. 서랍(도메인)과
# 묶음(용도)은 다른 축이라 _TIER_ASSIGNMENT 에 칸을 더하지 않는다. MCP 표면의
# 도구마다 정확히 한 번 배정돼 있는지는 test_mcp_tool_profiles 가 양방향으로 본다.
# **실행할 수 있는 도구는 전부** 표에 있다(카탈로그에 없어도 use_tool 로 닿는
# 것 포함) — 표에 없는 이름을 설정으로 치는 규칙(tool_in_profile)은 새 도구가
# 배정 없이 들어올 때를 위한 안전장치일 뿐, 배정을 대신하지 않는다.
TOOL_PROFILE_OPERATIONS = 'operations'
TOOL_PROFILE_CONFIGURATION = 'configuration'
TOOL_PROFILES = (TOOL_PROFILE_OPERATIONS, TOOL_PROFILE_CONFIGURATION)
_PROFILE_RETIRED = 'retired'
_PROFILE_DRAWER = 'drawer'
#: 인증 스냅샷에만 싣는 표지 — 내부 AI 서비스 계정의 연결(인앱 물리 제어가
#: stdio 하위 프로세스로 들어오는 길)이다. 키에 저장하는 값이 아니며
#: (normalize_tool_profile 은 이 값을 운영으로 좁힌다), mcp_auth.tool_profile_of
#: 가 None(제한 없음)으로 바꿔 넘긴다. None 을 그대로 쓰지 않는 이유: 스냅샷의
#: None 은 "묶음이 비었다 → 기본 묶음" 으로 읽힌다.
TOOL_PROFILE_UNRESTRICTED = 'unrestricted'

_OPS = TOOL_PROFILE_OPERATIONS
_CFG = TOOL_PROFILE_CONFIGURATION

_MCP_PROFILE = {
    # --- 장치 ---------------------------------------------------------------
    'search_devices':            _OPS,
    'get_output_state':          _OPS,
    'operate_device':            _OPS,
    'get_device_measurements':   _OPS,
    'get_device_detail':         _OPS,
    'get_control_state':         _OPS,
    'get_device_list':           _OPS,
    # 카탈로그(tools/list)에는 없지만 use_tool 로 실행되는 도구 — 표에 없으면
    # 설정으로 쳐지는 안전장치에 기대지 않고 명시한다(test_mcp_tool_profiles).
    'list_unbound_slots':        _OPS,
    'rebind_device':             _CFG,
    # operate_device 와 같은 일을 하는 네이티브 도구. 인앱 AI 에는 남는다.
    'set_output_state':          _PROFILE_RETIRED,
    # get_device_list·search_devices 와 겹치는 네이티브 도구.
    'list_available_devices':    _PROFILE_RETIRED,
    # --- 측정 ---------------------------------------------------------------
    'get_sensor_detail':         _OPS,
    'get_zone_sensor_summary':   _OPS,
    'get_weather':               _OPS,
    'get_sensor_reading':        _OPS,
    'get_weather_forecast':      _OPS,
    'get_anomalies':             _OPS,
    'get_device_freshness':      _OPS,
    'get_energy_report':         _OPS,
    'get_cumulative_status':     _OPS,
    # --- 함수 ---------------------------------------------------------------
    'get_function_detail':       _OPS,
    'get_function_list':         _OPS,
    'get_active_functions_summary': _OPS,
    'activate_function':         _OPS,
    'deactivate_function':       _OPS,
    # 제어기 옵션·시퀀스 운전 시간 조정("관수 5분 늘려")은 현장의 일상이다.
    'modify_function_options':   _OPS,
    'modify_sequence_schedule':  _OPS,
    'create_function':           _CFG,
    'delete_function':           _CFG,
    'create_sequence_function':  _CFG,
    'configure_sequence_day':    _CFG,
    # 기존 단계 하나의 시간·순서·켜짐 조정("관수 5분 늘려")도 현장의 일상이다.
    # 운영 안내문이 "시퀀스 운전 시간" 을 약속하는데 이것이 설정에만 있어서
    # 프로필 벤치마크(26-09-24, 432회) lat_19 가 운영 키에서 실패했다. 단계를
    # 새로 깔거나 지우는 일(configure_sequence_day·create_sequence_function)은
    # 설정에 남는다.
    'modify_sequence_step':      _OPS,
    # --- 일정 ---------------------------------------------------------------
    'search_schedule':           _OPS,
    'add_schedule':              _OPS,
    'add_schedule_batch':        _OPS,
    'edit_schedule':             _OPS,
    'delete_schedule':           _OPS,
    'schedule_device_control':   _OPS,
    # --- 기록 ---------------------------------------------------------------
    'search_notes':              _OPS,
    'create_note':               _OPS,
    'get_note_attachment':       _OPS,
    'knowledge_search':          _OPS,
    'query_data_source':         _OPS,
    'list_lookup_sources':       _OPS,
    'query_reference_table':     _OPS,
    'list_notices':              _OPS,
    'create_notice':             _OPS,
    # 거부 응답이 "대신 조언으로 남겨라" 고 안내하므로 운영 키에 있어야 한다.
    'submit_advice':             _OPS,
    'list_advice':               _OPS,
    # search_notes 응답이 보관 문서 검색을 가리킨다.
    'search_archives':           _OPS,
    'get_archived_document':     _CFG,
    'archive_note':              _CFG,
    'restore_note_from_archive': _CFG,
    'set_document_tier':         _CFG,
    'delete_archive':            _CFG,
    'modify_notice':             _CFG,
    'delete_notice':             _CFG,
    'knowledge_shelve':          _CFG,
    'list_library_source_types': _CFG,
    'smartfarmkorea_lookup':     _CFG,
    'configure_library_source':  _CFG,
    # --- 공간 ---------------------------------------------------------------
    'list_plots':                _OPS,
    'get_plot':                  _OPS,
    'get_map_equipment':         _OPS,
    'get_map_equipment_detail':  _OPS,
    'get_spatial_tree':          _OPS,
    'list_geo_maps':             _OPS,
    'get_device_location':       _OPS,
    'get_crop_status':           _OPS,
    'get_facility_capacity':     _OPS,
    'get_plot_history':          _OPS,
    'list_plot_journals':        _OPS,
    'get_plot_journal':          _OPS,
    'create_plot_journal':       _OPS,
    # 작기 단계 사건 — 사용자가 직접 말하는 일("육묘기 끝났어", "관수 시작해").
    'end_plot':                  _OPS,
    'confirm_plot_stage':        _OPS,
    'reschedule_plot_stage':     _OPS,
    'undo_plot_stage':           _OPS,
    'apply_plot_resources':      _OPS,
    'create_plot':               _CFG,
    'modify_plot':               _CFG,
    'delete_plot':               _CFG,
    'copy_plot':                 _CFG,
    'propose_plot_split':        _CFG,
    'apply_plot_split':          _CFG,
    'set_plot_stage_guidance':   _CFG,
    'add_plot_stage':            _CFG,
    'remove_plot_stage':         _CFG,
    'save_plot_schedule_as_program': _CFG,
    'list_programs':             _CFG,
    'get_program':               _CFG,
    'create_program':            _CFG,
    'modify_program':            _CFG,
    'delete_program':            _CFG,
    'get_address':               _CFG,
    'distance_between':          _CFG,
    'nearest':                   _CFG,
    'set_device_location':       _CFG,
    'delete_geo_shape':          _CFG,
    # --- 장치 정의 ----------------------------------------------------------
    'list_device_types':         _CFG,
    'get_device_type_options':   _CFG,
    'create_input':              _CFG,
    'modify_input':              _CFG,
    'delete_input':              _CFG,
    'create_output':             _CFG,
    'modify_output':             _CFG,
    'delete_output':             _CFG,
    'list_gis_inputs':           _CFG,
    'create_gis_input':          _CFG,
    'modify_gis_input':          _CFG,
    'activate_gis_input':        _CFG,
    'delete_gis_input':          _CFG,
    # --- 시스템 -------------------------------------------------------------
    'resolve_target':            _OPS,
    'get_system_brief':          _OPS,
    'list_pending_confirmations': _OPS,
    # 운영 묶음에 승인이 필요한 도구가 있는 한 필수다.
    'respond_to_confirmation':   _OPS,
    # 서버 안내문(TIME 단락)이 이름으로 부른다 — 빠지면 없는 도구를 가리킨다.
    'get_local_time':            _OPS,
    # 선언만 있고 MCP 실행층에는 처리기가 없다(인앱 action_type). 읽기라 운영.
    'read_manual':               _OPS,
    'analyze_system_failure':    _OPS,
    'get_system_update_status':  _CFG,
    'get_storage_tier_status':   _CFG,
    'list_dashboards':           _CFG,
    'list_widget_types':         _CFG,
    'get_widget':                _CFG,
    'create_widget':             _CFG,
    'modify_widget':             _CFG,
    'delete_widget':             _CFG,
    'list_tabs':                 _CFG,
    'create_tab':                _CFG,
    'modify_tab':                _CFG,
    'delete_tab':                _CFG,
    'list_ai_agents':            _CFG,
    'list_ai_entries':           _CFG,
    'create_ai_agent':           _CFG,
    'modify_ai_agent':           _CFG,
    'delete_ai_agent':           _CFG,
    # 서랍 기구 — 묶음이 아니라 서랍 스위치를 따른다.
    'open_drawer':               _PROFILE_DRAWER,
    'get_tool_detail':           _PROFILE_DRAWER,
    'use_tool':                  _PROFILE_DRAWER,
}

_PROFILE_VALUES = frozenset(TOOL_PROFILES) | {_PROFILE_RETIRED, _PROFILE_DRAWER}
for _name, _value in _MCP_PROFILE.items():
    if _value not in _PROFILE_VALUES:
        raise ValueError(
            f"tool_registry: 묶음 표에 모르는 값이 있습니다 — {_name}: {_value}")


def normalize_tool_profile(value):
    """키에 저장할 묶음 값. 모르는 값·빈 값은 운영으로 좁힌다.

    scope 와 같은 원칙이다 — 오타 하나가 조용히 넓은 표면을 만들지 않게 한다."""
    return value if value in TOOL_PROFILES else TOOL_PROFILE_OPERATIONS


def mcp_profile_of(name):
    """MCP 표면 도구의 묶음 배정. 표에 없으면 None."""
    return _MCP_PROFILE.get(name)


def mcp_profile_table():
    """배정표 사본(검사·문서용)."""
    return dict(_MCP_PROFILE)


def profile_tools(profile):
    """그 묶음이 보여 주는 도구 이름. 설정은 운영을 포함한다(운영 ⊆ 설정).

    서랍 기구와 retired 는 어느 묶음에도 들지 않는다 — 앞의 것은 서랍 스위치가,
    뒤의 것은 "묶음 없음(제한 없음)" 호출자만 본다."""
    return _profile_tools(normalize_tool_profile(profile))


@functools.lru_cache(maxsize=None)
def _profile_tools(profile):
    wanted = {TOOL_PROFILE_OPERATIONS}
    if profile == TOOL_PROFILE_CONFIGURATION:
        wanted.add(TOOL_PROFILE_CONFIGURATION)
    return frozenset(n for n, v in _MCP_PROFILE.items() if v in wanted)


def is_declared_tool(name):
    """TOOLS 에 선언된 이름인가(MCP 카탈로그 밖의 내부 도구 포함)."""
    return name in _BY_NAME


def is_drawer_machinery(name):
    return _MCP_PROFILE.get(name) == _PROFILE_DRAWER


def is_retired_from_mcp(name):
    return _MCP_PROFILE.get(name) == _PROFILE_RETIRED


def tool_in_profile(name, profile):
    """묶음 `profile` 인 호출자에게 이 도구를 보여 주는가.

    profile 이 None 이면 제한이 없다(인앱 AI). 서랍 기구는 묶음과 무관하게
    참이다 — 서랍 스위치가 따로 정한다. 표에 없는 이름은 설정으로 친다(새
    도구가 배정 없이 들어와도 운영 키 표면이 조용히 커지지 않게)."""
    if profile is None:
        return True
    value = _MCP_PROFILE.get(name, TOOL_PROFILE_CONFIGURATION)
    if value == _PROFILE_DRAWER:
        return True
    return name in profile_tools(profile) or (
        value == TOOL_PROFILE_CONFIGURATION
        and name not in _MCP_PROFILE
        and normalize_tool_profile(profile) == TOOL_PROFILE_CONFIGURATION)


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
        "description": (
            "Vegetation plots: crop, zone, area, size, period. Growing only "
            "unless include_ended. The only source for open-field crops; "
            "greenhouse crops → get_crop_status. with_sensors adds each plot's sensors; valves, stages and capacity "
            "are in get_plot. Follow the reply's `_reading`. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "map_id": {"type": "string", "description": "Map unique_id. Omit for all maps."},
                "zone_id": {"type": "string", "description": "Zone or site unique_id or name — only plots inside it."},
                "include_ended": {"type": "boolean", "description": "Include finished plots (history)."},
                "on": {"type": "string", "description": "As-of date 'YYYY-MM-DD'."},
                "with_sensors": {"type": "boolean", "description": "Include each plot's sensors (not valves)."},
            },
        },
    },
    {
        "tool_name": "get_plot",
        "description": (
            "One plot in detail: crop, dates, area, dimensions, sensors, "
            "irrigation valves, current stage, stage schedule and target check. "
            "Give spacings to get 'capacity_estimate' counted here rather than in"
            " your head. Follow the reply's `_reading`. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id or name (plot name, crop or variety)."},
                "row_spacing_cm": {"type": "number", "description": "Spacing between rows in cm (e.g. 40), for a FLAT layout only. Rows are counted across the plot's SHORT side. Not needed — and not used — when a bed layout (bed_pitch_cm + rows_per_bed) is given, because rows_per_bed takes its place."},
                "plant_spacing_cm": {"type": "number", "description": "Spacing between plants within a row in cm (e.g. 15). Plants are counted along the plot's LONG side. Required for any count, in both flat and bed layouts."},
                "edge_margin_cm": {"type": "number", "description": "Extra margin left free at every edge, in cm — headland for machinery turning, bed shoulders, a path. Default 0. Half a spacing is ALREADY free at each edge without this, so only pass it when the plot genuinely needs more (e.g. 200 for a 2 m turning strip). Requires both spacings."},
                "bed_pitch_cm": {"type": "number", "description": "Bed spacing (두둑 간격) in cm, centre to centre — the furrow is INCLUDED, e.g. 160 for a 120 cm bed with a 40 cm furrow. Ask the grower for this as ONE number: they do not count a bed and its furrow separately, and asking for both invites two different readings of the same field. Give it with rows_per_bed to count the layout as actually planted; without it the count assumes a flat layout and OVERSTATES a bedded one by 20-30%."},
                "rows_per_bed": {"type": "integer", "description": "How many rows go on ONE bed, e.g. 2. Whole number, 1 or more. Crop-dependent — peppers take one row, lettuce or cabbage two or three. Must be given together with bed_pitch_cm; the bed spacing alone cannot say how many rows fit. When this is given, row_spacing_cm is not used."},
                "plot_ids": {"type": "array", "items": {"type": "string"}, "description": "Several at once (max 10)."},
            },
        },
    },
    {
        "tool_name": "get_plot_history",
        "description": (
            "What grew on the same ground before — every past or present plot "
            "overlapping a plot or zone, with the overlap area. Check it before "
            "advising on replanting or rotation. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id — its outline is the reference."},
                "zone_id": {"type": "string", "description": "Or a zone's unique_id."},
                "map_id": {"type": "string", "description": "Optional map hint."},
            },
        },
    },
    {
        "tool_name": "list_plot_journals",
        "description": (
            "Saved journals: title, period, status (no content). Omit "
            "target_type/target_id for all, or give both for one plot/zone/site. "
            "journal_id is an internal handle — refer to journals by title and "
            "period. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_type": {"type": "string", "enum": ["plot", "zone", "site"], "description": "Omit for all journals."},
                "target_id": {"type": "string", "description": "unique_id of that plot/zone/site."},
                "limit": {"type": "integer", "description": "Newest first. Default 50, max 200."},
            },
            "required": [],
        },
    },
    {
        "tool_name": "get_plot_journal",
        "description": (
            "One saved journal snapshot (environment, control runtime, notes, "
            "stage targets). Beyond ~3 days pass granularity or "
            "date_from/date_to, or the measurements are dropped to fit. Only "
            "status 'done' has data. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "journal_id": {"type": "string", "description": "From list_plot_journals."},
                "granularity": {"type": "string", "enum": ["day", "week", "month", "all"], "description": "Fold days into coarser periods (not finer than stored)."},
                "date_from": {"type": "string", "description": "YYYY-MM-DD, first period kept."},
                "date_to": {"type": "string", "description": "YYYY-MM-DD, last period kept."},
            },
            "required": ["journal_id"],
        },
    },
    {
        "tool_name": "create_plot_journal",
        "description": (
            "Builds a journal (what was grown, measured, controlled) for a "
            "plot/zone/site and period, to hand over or print. Runs in the "
            "background: returns journal_id, status 'pending' — poll "
            "get_plot_journal. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_type": {"type": "string", "enum": ["plot", "zone", "site"], "description": "What the journal is about."},
                "target_id": {"type": "string", "description": "unique_id of the plot/zone/site."},
                "start": {"type": "string", "description": "YYYY-MM-DD, first day."},
                "end": {"type": "string", "description": "YYYY-MM-DD, last day."},
                "granularity": {"type": "string", "enum": ["day", "week", "month"], "description": "Week/month for long periods. Omit to let the system choose."},
            },
            "required": ["target_type", "target_id", "start", "end"],
        },
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
        "description": (
            "Works out how a zone or site would divide into plots WITHOUT "
            "creating anything — counts, widths and lengths, no coordinates. "
            "Choose parts, strip_width_cm or widths_cm; each parameter states its"
            " own rule. An aspect_ratio far above ~4:1 means long narrow pieces —"
            " try the other orientation. The grower can see the proposal drawn on"
            " the map design page (plot mode). Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_id": {"type": "string", "description": "The zone or site shape to divide (GeoShape unique_id, from get_spatial_tree)."},
                "parts": {"type": "integer", "description": "Divide into this many equal pieces (1 or more). Use for 'three crops in this zone'. Pass 1 to NOT divide — the whole zone becomes a single plot (still inset by edge_margin_m if given), which is what a grower means by 'plant this whole field as one'. Ignored if widths_cm is given."},
                "strip_width_cm": {"type": "number", "description": "Or make pieces this wide in cm, e.g. 160. Use for bed-by-bed. Give this OR parts (or both together for an exact count at an exact width), never with widths_cm."},
                "widths_cm": {"type": "array", "items": {"type": "number"}, "description": "Give each piece its own width in cm instead of equal pieces, e.g. [200, 500, 300] for three different widths in that order. Overrides parts/strip_width_cm entirely. If the widths add up to more than the shape's short axis, only the LAST piece is shortened to fit (see widths_clamped_from_cm in the response) rather than rejecting the whole request; if the earlier pieces alone already don't fit, the request is rejected."},
                "edge_margin_m": {"type": "number", "description": "Leave this much free inside the whole outline, in METERS — headland for machinery. Default 0."},
                "orientation": {"type": "string", "enum": ["long", "short"], "description": "Which side the pieces run along. Optional — if omitted, the default depends on mode: 'long' when strip_width_cm is given (furrows must follow the shape's long side), 'short' when only parts (or only widths_cm) is given (squarer pieces, better for splitting between different crops). Pass explicitly to override that default. Ignored if angle_deg is given."},
                "angle_deg": {"type": "number", "description": "Direction in degrees (0 up to but excluding 180) for the pieces, overriding orientation entirely. Only meaningful when a human has looked at the map and chosen a specific angle (e.g. to match an adjacent field's existing beds) — do not invent a value yourself; the grower must supply it."},
            },
            "required": ["zone_id"],
        },
    },
    {
        "tool_name": "apply_plot_split",
        "description": (
            "Creates one plot per piece of a split — the write half of "
            "propose_plot_split. Pass exactly the SAME arguments as the proposal,"
            " leaving out what was left out there: the split is recomputed and "
            "must match. Check the piece count first (41 pieces = 41 plots). One "
            "crop over a whole zone is create_plot with zone_id. Requires human "
            "approval."
        ),
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
                "color": {"type": "string", "description": "'#rrggbb'"},
            },
            "required": ["zone_id", "subject", "started_on"],
        },
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
        "description": (
            "Marks a plot finished. The record is KEPT as history (rotation "
            "checks still see it) — use this, not deletion, for anything actually"
            " grown. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "ended_on": {"type": "string", "description": "'YYYY-MM-DD'. Default today."},
                "reason": {"type": "string", "description": "Default harvested.", "enum": ["harvested", "failed", "replaced", "removed"]},
            },
            "required": ["plot_id"],
        },
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
        "description": (
            "Records that a plot HAS entered a stage; the remaining stages are "
            "recomputed from that date. For a change that already happened (the "
            "grower says so, or get_plot's stage_proposal suggests it). A "
            "boundary still ahead is reschedule_plot_stage. Requires human "
            "approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "stage_key": {"type": "string", "description": "From get_plot's stage_proposal or stage_schedule. Never compose one."},
                "started_on": {"type": "string", "description": "'YYYY-MM-DD' it happened: stage_proposal.started_on unless the grower names a day. Never invent one."},
            },
            "required": ["plot_id", "stage_key"],
        },
    },
    {
        "tool_name": "reschedule_plot_stage",
        "description": (
            "Moves a stage boundary that is still AHEAD, for this plot only "
            "('transplanting slipped a week'); later boundaries shift with it and"
            " the programme is unchanged. A change that already happened is "
            "confirm_plot_stage. Keys and dates: get_plot's stage_schedule. "
            "Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
                "stage_key": {"type": "string", "description": "From get_plot's stage_schedule."},
                "days": {"type": "integer", "description": "Make that stage last N days (not the last stage)."},
                "shift_days": {"type": "integer", "description": "Move its start by N days: +7 delay, -3 earlier."},
                "started_on": {"type": "string", "description": "Or set its start to 'YYYY-MM-DD'."},
            },
            "required": ["plot_id", "stage_key"],
        },
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
        "description": (
            "Saves THIS plot's schedule (its stages, edited lengths and guidance)"
            " as a reusable programme; targets are copied unchanged. The plot is "
            "NOT moved onto it — use modify_plot(program_uuid=...) if the grower "
            "wants that. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "The plot whose schedule to register."},
                "name": {"type": "string", "description": "Name for the new programme. Omit to derive one from the plot."},
            },
            "required": ["plot_id"],
        },
    },
    {
        "tool_name": "undo_plot_stage",
        "description": (
            "Undoes the most recent stage confirmation (kept, marked undone); the"
            " previous one becomes the anchor again. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
            },
            "required": ["plot_id"],
        },
    },
    {
        "tool_name": "apply_plot_resources",
        "description": (
            "Starts the irrigation/fertigation Functions the plot's current stage"
            " declares, resolved from the site. PHYSICAL — water flows. Nothing "
            "is switched off. Check get_plot's stage.resources first. Follow the "
            "reply's `_reading`. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "plot_id": {"type": "string", "description": "Plot unique_id."},
            },
            "required": ["plot_id"],
        },
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
        "description": (
            "Creates a management programme (subject -> stages with lengths); the"
            " subject may be a crop, tree, turf, herd or structure. RECIPE: 1) "
            "list_programs — does it exist? 2) research with knowledge_search "
            "(empty library: say so, never pass your own knowledge off as a "
            "source). 3) Map findings onto YOUR stage keys; never bend a day "
            "count to fit. 4) Blank beats a guess. It drives nothing until a "
            "person marks it checked — only a person can."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Programme name."},
                "subject": {"type": "string", "description": "What it manages."},
                "source_note": {"type": "string", "description": "REQUIRED. What this is based on, and how that source's stages were mapped onto these ones — without it nobody can later judge whether a number is right."},
                "stages": {"type": "array", "description": "Ordered stages. 'days' is that stage's LENGTH, not a cumulative day; only the LAST stage may leave it blank (= until the end).", "items": {"type": "object", "properties": {"key": {"type": "string", "description": "Stage key, e.g. transplant / vegetative / flowering / fruiting / harvest."}, "name": {"type": "string", "description": "Display name."}, "days": {"type": "integer", "description": "Length of this stage in days. Blank only on the last stage."}, "targets": {"type": "object", "description": "{item_key: number}, this stage only. Keys MUST exist in target_defs — vegetation already has temp_day, temp_night, rh, co2, dli, vpd. Out-of-range values are refused."}, "guidance": {"type": "string", "description": "The half no sensor can do — what to LOOK at and DO BY HAND this stage. This is what a beginner opens the programme for, so fill it when you have a real basis."}}}},
                "kind": {"type": "string", "enum": ["vegetation", "livestock", "facility", "other"], "description": "Default 'vegetation'. Only vegetation has fixed target items; other kinds need target_defs before targets."},
                "variety": {"type": "string", "description": "Cultivar / breed."},
                "notes": {"type": "string", "description": "Free notes."},
                "target_defs": {"type": "array", "description": "Extra target ITEMS, only for a value the fixed vocabulary lacks.", "items": {"type": "object", "properties": {"key": {"type": "string", "description": "lowercase a-z0-9_ ."}, "label": {"type": "string"}, "unit": {"type": "string"}, "measurement": {"type": "string", "description": "Sensor measurement name this maps to — without it the value is display/advice only (control cannot act on a quantity it has no meaning for)."}}}},
                "base_temp_c": {"type": "number", "description": "GDD base temperature. Vegetation only."},
                "resource_defs": {"type": "array", "description": "What the subject NEEDS (roles), never which function does it — that is a fact about a place, so the site resolves it and one programme serves several greenhouses.", "items": {"type": "object", "properties": {"role": {"type": "string", "enum": ["irrigation", "fertigation", "other"]}}}},
                "tab_id": {"type": "string", "description": "Tab on the Programs page."},
            },
            "required": ["name", "subject", "source_note"],
        },
    },
    {
        "tool_name": "modify_program",
        "description": (
            "Edits a programme or moves it to another tab — also how an empty "
            "programme made in the UI gets filled (same stage shape and RECIPE as"
            " create_program). Call get_program first: 'stages' replaces the "
            "whole list. Send only changed fields. Built-in/external programmes "
            "accept only tab_id. Changing stages, targets or base_temp_c sends it"
            " back for a person to check — expected; say so rather than working "
            "around it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "program_id": {"type": "string", "description": "Programme unique_id."},
                "name": {"type": "string"},
                "variety": {"type": "string"},
                "stages": {"type": "array", "description": "Replaces the WHOLE stage list — same item shape as create_program (key, name, days, targets, guidance).", "items": {"type": "object"}},
                "target_defs": {"type": "array", "items": {"type": "object"}, "description": "Target item definitions — same shape as create_program."},
                "resource_defs": {"type": "array", "items": {"type": "object"}},
                "base_temp_c": {"type": "number"},
                "kind": {"type": "string", "enum": ["vegetation", "livestock", "facility", "other"]},
                "notes": {"type": "string"},
                "source_note": {"type": "string", "description": "Update the basis when you change what the programme says."},
                "tab_id": {"type": "string"},
            },
            "required": ["program_id"],
        },
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
        "description": (
            "Searches archived documents by stored metadata. A document only "
            "marked tier 3 but never moved does not appear; an empty result is "
            "normal. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword. Omit to list all."},
                "limit": {"type": "integer", "description": "1-200. Default 50."},
                "offset": {"type": "integer", "description": "Default 0."},
            },
        },
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
        "description": (
            "Sensor history with min/max/avg for a device or a zone. For many "
            "zones at once use get_zone_sensor_summary. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "loc_id": {"type": "string", "description": "Device or zone unique_id or name."},
                "sensor_type": {"type": "string", "description": "Measurement filter, e.g. temperature."},
                "time_range": {"type": "string", "description": "'1h', '24h', '7d'. Default 24h."},
                "loc_ids": {"type": "array", "items": {"type": "string"}, "description": "Several at once (max 10)."},
            },
        },
    },
    {
        "tool_name": "get_spatial_tree",
        "description": (
            "How the farm is divided: every site, zone and facility, with how "
            "many devices each holds. To find a device by name use "
            "search_devices. Follow the reply's `_reading`. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "depth": {"type": "integer", "description": "Omit = places only. N cuts at depth N (root 1) with devices; 0 = all. Cut nodes: 'children_omitted'."},
                "filter_type": {"type": "string", "description": "Only this node type, e.g. 'zone' (depth not applied)."},
            },
        },
    },
    {
        "tool_name": "resolve_target",
        "description": (
            "Resolves a place, device or crop name to one entity — read-only, no "
            "approval. Call it before a write that takes target_name when unsure"
            " of the name or when it could mean each sub-unit ('each zone'): the reply lists "
            "'children' and a 'note' on what a write would touch. Shared names "
            "return candidates."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "The user's own words, e.g. '3-1', '1포장 1-1', '콩밭'."},
            },
            "required": ["target_name"],
        },
    },
    {
        "tool_name": "get_zone_sensor_summary",
        "description": (
            "Latest value and period statistics for the sensors of MANY zones in "
            "one call — for any question across zones or the farm ('which plots "
            "are dry'). Narrow with measurement_type. Follow the reply's "
            "`_reading`. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_ids": {"type": "array", "items": {"type": "string"}, "description": "Zone/site unique_ids or names (max 10). Omit for every zone."},
                "measurement_type": {"type": "string", "description": "e.g. 'volumetric_water_content' (soil moisture), 'temperature'. Substring. Recommended."},
                "time_range": {"type": "string", "description": "e.g. '24h', '30d'. Default '7d'."},
            },
        },
    },
    {
        "tool_name": "search_devices",
        "description": (
            "Finds devices by name/type keyword and/or by the measurement they "
            "record. To find every sensor of a kind use measurement_type — names "
            "are not reliable. Follow the reply's `_reading`. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Name or type keyword."},
                "measurement_type": {"type": "string", "description": "Stored measurement name, substring: soil moisture = 'volumetric_water_content', rain = 'precipitation', wind = 'speed'/'direction'; 'temperature', 'humidity', 'co2', 'battery_voltage'. With query it intersects."},
            },
        },
    },
    {
        "tool_name": "get_device_list",
        "description": (
            "Every registered device (inputs, outputs, cameras, complex devices) "
            "— for a full listing without a keyword. Follow the reply's "
            "`_reading`. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "tool_name": "get_energy_report",
        "description": "Energy usage report for a period and/or zone. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "Default daily.", "enum": ["daily", "weekly", "monthly"]},
                "zone_id": {"type": "string", "description": "Zone unique_id. Omit for all."},
            },
        },
    },
    {
        "tool_name": "operate_device",
        "description": (
            "Switches an output now (valve, pump, light): on, off, or set_value "
            "for PWM/setpoint. PHYSICAL. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Output unique_id or name."},
                "state": {"type": "string", "enum": ["on", "off", "set_value"], "description": "Target state."},
                "value": {"type": "number", "description": "Number for set_value (PWM/setpoint)."},
            },
            "required": ["device_id", "state"],
        },
    },
    {
        "tool_name": "add_schedule",
        "description": (
            "Records a dated task or memo for a PERSON (weeding, inspection). "
            "Device control at a time is schedule_device_control. Saved without "
            "an approval step."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD."},
                "time": {"type": "string", "description": "HH:MM. Default '09:00'."},
                "content": {"type": "string", "description": "The work."},
                "worker": {"type": "string", "description": "Assignee."},
                "tags": {"type": "string", "description": "Comma-separated. Default: taken from content."},
                "target_name": {"type": "string", "description": "Name of the zone/facility/device this work applies to (e.g. '3-1', '1포장 1-1', '온실'). PASS this whenever the user names a place, so the schedule links to the real entity for map/location queries instead of relying on free-text tag extraction. If the name is ambiguous or not found, the tool returns status 'needs_disambiguation' with available_targets or candidates - ask the user, then retry with the exact name or use_name. Omit only for a farm-wide event with no specific place. This is a GIS-based system: a name resolves to exactly ONE entity and never fans out to its children automatically. If the request could apply per sub-unit (each zone/구역, each device under a site), call resolve_target(target_name) FIRST - it is read-only, needs no approval, and returns 'children' when the resolved entity contains finer-grained sub-entities. If so, use add_schedule_batch instead of calling this tool once per child."},
                "target_id": {"type": "string", "description": "Instead of target_name: a resolve_target candidate's target_id."},
            },
            "required": ["date", "content"],
        },
    },
    {
        "tool_name": "add_schedule_batch",
        "description": (
            "Per-target human tasks in ONE call for 'each zone' requests (not "
            "repeated add_schedule); exact child names come from resolve_target. "
            "With window_start/window_end it checks entries x duration_minutes "
            "fit and rejects up front with the numbers — then split across dates "
            "or ask. No approval step."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD for every entry."},
                "entries": {"type": "array", "description": "One per target; the same target twice is rejected.", "items": {"type": "object", "properties": {"target_name": {"type": "string", "description": "Exact place name, e.g. a resolve_target child."}, "target_id": {"type": "string", "description": "Instead: a candidate's target_id (wins over target_name)."}, "time": {"type": "string", "description": "HH:MM."}, "content": {"type": "string", "description": "Overrides the shared content."}, "worker": {"type": "string", "description": "Overrides the shared worker."}}, "required": ["target_name", "time"]}},
                "content": {"type": "string", "description": "Shared work text for entries without their own."},
                "worker": {"type": "string", "description": "Shared assignee."},
                "tags": {"type": "string", "description": "Comma-separated, for every entry."},
                "window_start": {"type": "string", "description": "'HH:MM' start of the work window (enables the fit check)."},
                "window_end": {"type": "string", "description": "'HH:MM' end; every entry's time must be at or before it."},
                "duration_minutes": {"type": "integer", "description": "Minutes per entry for the fit check. Default 60."},
            },
            "required": ["date", "entries"],
        },
    },
    {
        "tool_name": "search_notes",
        "description": (
            "Reads notes, memos and work records. For notes about a place or "
            "device pass target_name — notes are attached to the entity and may "
            "not mention it, so a keyword search misses them. A site includes its"
            " zones. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Place/device the notes are attached to, e.g. '3-1', '밸브1'."},
                "query": {"type": "string", "description": "Keyword. With target_name it filters within."},
                "category": {"type": "string", "description": "e.g. 'schedule', 'general'. Omit for all."},
                "limit": {"type": "integer", "description": "Default 10."},
                "target_names": {"type": "array", "items": {"type": "string"}, "description": "Several at once (max 10)."},
            },
        },
    },
    {
        "tool_name": "get_note_attachment",
        "description": (
            "Shows one photo attached to a note, as an image. search_notes lists "
            "only filenames — call this when the picture could settle the "
            "question. One image per call; a non-image returns 'not_an_image' "
            "(normal). Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "The note's unique_id (from search_notes)."},
                "filename": {"type": "string", "description": "One of that note's 'files'. Omit for the first."},
                "max_dimension": {"type": "integer", "description": "Longest edge in px. Default 1024 (256-2048)."},
            },
            "required": ["note_id"],
        },
    },
    {
        "tool_name": "schedule_device_control",
        "description": (
            "Schedules an output (valve, pump, sprinkler) to switch at a set "
            "time. PHYSICAL — registered after approval. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Output unique_id or name."},
                "scheduled_time": {"type": "string", "description": "ISO 8601 with offset, e.g. '2026-02-27T09:00:00+09:00'."},
                "state": {"type": "string", "enum": ["on", "off"], "description": "Target state."},
                "duration_minutes": {"type": "number", "description": "Default 5."},
            },
            "required": ["device_id", "scheduled_time", "state"],
        },
    },
    {
        "tool_name": "get_weather",
        "description": (
            "Current weather for a site or zone from the station serving it; "
            "'weather_source' says which. Follow 'weather_source_warning' / "
            "'weather_device_note' when present. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_name": {"type": "string", "description": "Site or zone name, e.g. '1포장'."},
                "zone_id": {"type": "string", "description": "Or its unique_id."},
            },
        },
    },
    {
        "tool_name": "get_cumulative_status",
        "description": (
            "Daily DLI and GDD for an environment coordinator function, with the "
            "running deficit and suggested compensation. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "The coordinator function's unique_id."},
                "days": {"type": "integer", "description": "Recent days. Default 7."},
            },
            "required": ["function_id"],
        },
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
        "description": (
            "Saves a note now (an undated memo; dated work is add_schedule). No "
            "approval step. A note is visible only on the entity it is attached "
            "to, so name the place or device in target_name. Call the tool — do "
            "not just say you will."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "Body text."},
                "name": {"type": "string", "description": "Short title."},
                "target_name": {"type": "string", "description": "Name of the location/device to attach the note to (e.g. '1포장 1-1', '밸브1'). The tool resolves it to a unique_id. Strongly recommended, otherwise the note will not be visible anywhere. This is a GIS-based system: the name resolves to exactly ONE entity and never fans out to its children, and this tool saves immediately with no approval step to catch a wrong hierarchy level afterward. If the request could apply per sub-unit (each zone/구역 under a site), call resolve_target(target_name) FIRST (read-only, no approval) and, if it returns 'children', call this tool once per child name."},
                "tags": {"type": "string", "description": "Comma separated."},
                "category": {"type": "string", "description": "Default 'general'."},
                "target_id": {"type": "string", "description": "Target unique_id, instead of target_name."},
                "target_type": {"type": "string", "description": "Type of that target, e.g. 'zone', 'input', 'output'."},
            },
            "required": ["note"],
        },
    },
    {
        "tool_name": "list_notices",
        "description": "Notice-board posts (title, pinned, date). Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Default 10."},
            },
        },
    },
    {
        "tool_name": "create_notice",
        "description": "Creates a notice-board post. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Title."},
                "body": {"type": "string", "description": "Body text."},
                "pinned": {"type": "boolean", "description": "Pin to top (admin only)."},
            },
            "required": ["title", "body"],
        },
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
        "description": (
            "Design capacity of facilities drawn in geo/design: heating/cooling "
            "kW, floor/volume/glazing area, ventilation, irrigation summary, "
            "bound controllers. Engineering estimates (+/-5-10%). Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "facility_name": {"type": "string", "description": "e.g. '육묘장'. Omit for all."},
            },
        },
    },
    {
        "tool_name": "get_map_equipment",
        "description": (
            "Equipment drawn on the map with specs (flow, pressure, kW, airflow) "
            "plus a per-zone irrigation summary; sprinklers and drip are counted "
            "separately. Not controllers. Follow the reply's `_reading`. "
            "Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "area_name": {"type": "string", "description": "Site or zone name. Omit for the whole map."},
            },
        },
    },
    {
        "tool_name": "get_map_equipment_detail",
        "description": (
            "Per-zone geometry below get_map_equipment: sprinkler positions, "
            "radius and spacing; drip pipes with length, spacing and emitters. "
            "Only for what the summary lacks. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "area_name": {"type": "string", "description": "Site or zone name."},
            },
            "required": ["area_name"],
        },
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
        "description": (
            "Searches the knowledge layer — manuals, synced domain knowledge, "
            "shelved notes. Call it FIRST when asked to research something. If it"
            " finds nothing, say so rather than presenting your own knowledge as "
            "a source. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language, e.g. 'tomato irrigation interval'."},
                "top_k": {"type": "integer", "description": "Default 3."},
                "tags": {"type": "string", "description": "Narrow by tag."},
            },
            "required": ["query"],
        },
    },
    {
        "tool_name": "search_schedule",
        "description": (
            "Queries the schedule ledger (device reservations, human tasks, AI "
            "jobs) — check it before advising, to avoid duplicate or conflicting "
            "plans. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Matches content. Omit for all."},
                "target_name": {"type": "string", "description": "Only this place or device."},
                "include_past": {"type": "boolean", "description": "Include past entries."},
                "limit": {"type": "integer", "description": "Default 20."},
            },
        },
    },
    {
        "tool_name": "get_function_list",
        "description": (
            "Control Functions with type, trigger_type and activation state — "
            "what automation exists. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_type": {"type": "string", "description": "e.g. pid, conditional, trigger."},
                "active_only": {"type": "boolean", "description": "Active only."},
            },
        },
    },
    {
        "tool_name": "get_function_detail",
        "description": (
            "Full configuration of one control Function (e.g. PID setpoint, "
            "sequence plan) — to judge why control behaves as it does. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "unique_id or exact name."},
            },
            "required": ["function_id"],
        },
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
        "description": (
            "Changes a function's options and reloads it if running. Unknown "
            "option keys are refused with the valid list. Not for sequences — "
            "their timing is modify_sequence_schedule. Saved without an approval "
            "step (settings only)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "unique_id (from get_function_list)."},
                "params": {"type": "object", "description": "{option_id: value} to change; keys are get_function_detail options[].key."},
            },
            "required": ["function_id", "params"],
        },
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
        # 운영 묶음에 있다(프로필 벤치마크 26-09-24 lat_19) — 운영 크기 상한
        # 안에 들도록 설명을 줄였다. 자세한 규칙은 인앱 매니페스트의 usage_hint.
        "tool_name": "modify_sequence_step",
        "description": (
            "Changes ONE step of a sequence (steps: get_function_detail): run "
            "time, order, on/off, group, label. Same group = run together. Saved "
            "without an approval step (settings only)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "steps[].action_id."},
                "duration_seconds": {"type": "number", "description": "Run time; on a grouped step, the whole group's."},
                "order": {"type": "integer", "description": "Lowest runs first."},
                "enabled": {"type": "boolean"},
                "group_name": {"type": "string", "description": "Same name = run together; '' ungroups."},
                "mode": {"type": "string", "enum": ["single", "total"], "description": "'total' spans the whole cycle (a pump)."},
                "lead_seconds": {"type": "number", "description": "'total' only: start delay."},
                "lag_seconds": {"type": "number", "description": "'total' only: early stop."},
                "display_name": {"type": "string", "description": "Label; '' resets it."},
                "day": {"type": "integer", "description": "0=Mon..6=Sun: enabled/group_name/duration_seconds for that weekday only."}
            },
            "required": ["action_id"]
        }
    },
    {
        "tool_name": "modify_sequence_schedule",
        "description": (
            "Changes WHEN a sequence runs: daily window, cycle period, weekdays "
            "(the running cycle is kept). Saved without an approval step "
            "(settings only)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "Sequence unique_id or exact name."},
                "start": {"type": "string", "description": "'HH:MM' window start (device local time)."},
                "end": {"type": "string", "description": "'HH:MM'. '24:00' = end of day."},
                "period_seconds": {"type": "number", "description": "Seconds between cycle starts (a pass must fit the window)."},
                "weekdays": {"type": "array", "items": {"type": "integer"}, "description": "Days it runs, 0=Mon..6=Sun. Replaces the set."},
                "day": {"type": "integer", "description": "Apply start/end/period_seconds to this weekday only (0-6)."},
            },
            "required": ["function_id"],
        },
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
        "description": (
            "Activates a function. Refuses a sequence with no steps. Requires "
            "human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "unique_id or exact name."},
            },
            "required": ["function_id"],
        },
    },
    {
        "tool_name": "deactivate_function",
        "description": "Deactivates a function. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "unique_id or exact name."},
            },
            "required": ["function_id"],
        },
    },
    {
        "tool_name": "get_active_functions_summary",
        "description": (
            "What is running automatically right now (active Functions). "
            "Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "tool_name": "get_device_measurements",
        "description": "Measurement channels and units a device actually reports. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Device unique_id or name."},
            },
            "required": ["device_id"],
        },
    },
    {
        "tool_name": "get_device_detail",
        "description": (
            "One device's whole picture in one call: kind, map location, "
            "channels, controlled outputs, connection fields (secrets only as "
            "set/unset), bound place, approval needs. Use it instead of chaining "
            "lookups. Missing parts come as null with a '*_note'. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "unique_id or name. An ambiguous name returns candidates."},
            },
            "required": ["device_id"],
        },
    },
    {
        "tool_name": "get_local_time",
        "description": (
            "Local time and timezone at a zone, facility or device — check before"
            " any time-of-day reasoning; places can be in different timezones. "
            "Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Zone, facility or device name."},
                "target_id": {"type": "string", "description": "Or its unique_id."},
            },
        },
    },
    {
        "tool_name": "list_geo_maps",
        "description": "Registered maps (farms) with id, name and centre. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "tool_name": "list_gis_inputs",
        "description": "Lists registered GIS Inputs (map layers/providers — VWorld, Google, OpenWeather, etc). Read-only.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "tool_name": "create_gis_input",
        "description": "Creates a new GIS Input (map layer/provider, e.g. gis_vworld, gis_openweather). layer_type must be a 'gis_*' entry from list_device_types(kind='input'). Always created DEACTIVATED — call activate_gis_input once configured. Saves immediately (no approval); activate_gis_input still requires approval.",
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
        "description": "A device's map position (latitude/longitude). Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Device unique_id."},
            },
            "required": ["device_id"],
        },
    },
    {
        "tool_name": "distance_between",
        "description": (
            "Distance in metres between two things on the map, by name (the "
            "user's own words — '3-1', '관리사무소', a crop) or unique_id. Never work "
            "it out from coordinates yourself. Centre to centre, so touching "
            "plots still read tens of metres apart — pass that caveat on. An "
            "ambiguous name returns candidates: ask which, do not pick. "
            "Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_a": {"type": "string", "description": "Name or unique_id of the first entity (zone/site/facility, vegetation plot, or device)."},
                "target_b": {"type": "string", "description": "Name or unique_id of the second entity."},
            },
            "required": ["target_a", "target_b"],
        },
    },
    {
        "tool_name": "nearest",
        "description": (
            "Ranks things by distance from one reference ('which plots are "
            "closest to the office') in ONE call — do not loop distance_between. "
            "Names or unique_ids. Relay both 'unresolved' and 'ambiguous' — a "
            "shorter list otherwise reads as 'further away'. Centre to centre. "
            "Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "Name or unique_id of the thing to measure from (e.g. the office)."},
                "candidates": {"type": "array", "items": {"type": "string"}, "description": "Names or unique_ids to rank, closest first. Max 200."},
            },
            "required": ["reference", "candidates"],
        },
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
        "description": (
            "Edits a schedule (time, duration, text, worker, place); a device "
            "reservation is rescheduled too. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "From search_schedule."},
                "date": {"type": "string", "description": "YYYY-MM-DD. Omit to keep."},
                "time": {"type": "string", "description": "HH:MM. Omit to keep."},
                "duration_minutes": {"type": "number", "description": "New duration."},
                "content": {"type": "string", "description": "New text."},
                "worker": {"type": "string", "description": "New assignee."},
                "target_name": {"type": "string", "description": "Re-link to a place/device by name."},
                "target_id": {"type": "string", "description": "Or by a resolve_target target_id."},
            },
            "required": ["job_id"],
        },
    },
    {
        "tool_name": "delete_schedule",
        "description": (
            "Cancels a schedule (archived, reversible) and removes its device "
            "trigger. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "From search_schedule."},
                "reason": {"type": "string", "description": "Why."},
            },
            "required": ["job_id"],
        },
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
        "description": "Creates a new AI pipeline agent bound to an AIEntry. Always created DEACTIVATED (is_activated=False) — saves immediately (no approval). There is no AI-callable activation tool: only a human, via the web UI, can make it live.",
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
        "description": (
            "Saves knowledge into the library so a later search finds it (write "
            "side of knowledge_search) — including a summary of what you "
            "researched outside this system. Always stored as "
            "unconfirmed/ai_curated: you MUST tell the user it is an unconfirmed "
            "note, not fact. Only reusable findings, not chit-chat."
        ),
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
                "ttl_hours": {"type": "number", "description": "Optional — set for time-sensitive info so it expires."},
            },
            "required": ["content", "tags"],
        },
    },
    {
        "tool_name": "list_lookup_sources",
        "description": (
            "Lists what can be looked up on demand — registered reference tables "
            "and connected data APIs (not in knowledge_search). Check here before"
            " answering a per-item value or external data from memory. kind "
            "'table' -> query_reference_table, 'api' -> query_data_source. "
            "Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "tool_name": "query_data_source",
        "description": (
            "Runs one operation on a connected data API now (e.g. what other "
            "farms measured). A truncated result is not the whole set — report "
            "'total_available'. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source_id": {"type": "string", "description": "From list_lookup_sources."},
                "operation": {"type": "string", "description": "One of that source's operations."},
                "params": {"type": "object", "description": "Its parameters. Codes come from the source, not the user."},
                "limit": {"type": "integer", "description": "Default 5, max 25."},
                "columns": {"type": "string", "description": "Comma-separated, or '*'."},
            },
            "required": ["operation"],
        },
    },
    {
        "tool_name": "query_reference_table",
        "description": (
            "Looks up rows by name in a registered reference table (names in the "
            "table's own language). Quote the returned caveat when it changes the"
            " meaning; if nothing matches, say so. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "table_id": {"type": "string", "description": "From list_lookup_sources. Omit if only one table exists."},
                "query": {"type": "string", "description": "Name to look up — species, part, variety."},
                "limit": {"type": "integer", "description": "Default 5."},
                "columns": {"type": "string", "description": "Omit for the summary set, '*' for all. Ask only for what you need."},
            },
            "required": ["query"],
        },
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
        "description": (
            "Write/control requests awaiting human approval, with their "
            "confirmation_id. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    # NOTE: respond_to_confirmation is intentionally NOT here. It has handler=None
    # in TOOLS (special-dispatched by aot_mcp_server.py, same as the native-bridge
    # tools like set_output_state) — virtual_tools() requires every payload's Tool
    # to have a real handler, so it's advertised via aot_mcp_server._EXTRA_TOOLS
    # instead, the same way native tools are advertised via AoTNativeToolEngine
    # rather than through this payload list.
    {
        "tool_name": "analyze_system_failure",
        "description": (
            "Diagnoses system faults — recent failed AI tasks and MCP connection "
            "health. Sensor or environment anomalies are get_anomalies. "
            "Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "One device only."},
                "tool_name": {"type": "string", "description": "One tool only."},
                "lookback_minutes": {"type": "integer", "description": "Default 60."},
            },
        },
    },

    # ── (B) 신설 읽기 도구 ────────────────────────────────────────────────────
    {
        "tool_name": "get_control_state",
        "description": (
            "Current targets and latest decision of the environment-control "
            "coordinators: targets, tolerances, safety ranges, applied targets, "
            "limiting factor, actuator commands with reasons. Read it before "
            "advising on control. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "facility_name": {"type": "string", "description": "Facility name. Omit for all."},
                "facility_id": {"type": "string", "description": "Facility unique_id."},
                "include_inactive": {"type": "boolean", "description": "Include inactive coordinators."},
            },
        },
    },
    {
        "tool_name": "get_weather_forecast",
        "description": (
            "Short-term hourly forecast, for advice ahead of a change "
            "(get_weather is current only). Follow the 'warning' when it is too "
            "old. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "Hours ahead. Default 24."},
            },
        },
    },
    {
        "tool_name": "get_anomalies",
        "description": (
            "On-demand anomaly check: threshold violations, offline ratio, alert "
            "level. Evaluates only, sends nothing. Read 'metrics_definitions' "
            "before quoting a number. Silent sensors: get_device_freshness; "
            "system faults: analyze_system_failure. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope_type": {"type": "string", "description": "Default system.", "enum": ["system", "farm", "zone", "facility"]},
                "scope_id": {"type": "string", "description": "Scope unique_id. Omit for system."},
            },
        },
    },
    {
        "tool_name": "get_device_freshness",
        "description": (
            "Which sensors stopped reporting — last_seen and periods_late, judged"
            " by each device's own sampling period. Follow 'basis' and 'caveat' "
            "in the reply. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "One input only. Omit for all."},
                "include_fresh": {"type": "boolean", "description": "Also list devices reporting normally."},
            },
        },
    },
    {
        "tool_name": "get_crop_status",
        "description": (
            "Crop and growth stage per facility and plot, from the plot "
            "programmes (with optimal ranges when configured). Check it before "
            "cultivation advice. Follow the reply's `_reading`. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "facility_id": {"type": "string", "description": "Facility unique_id."},
                "facility_name": {"type": "string", "description": "Facility name. Omit for all."},
            },
        },
    },
    {
        "tool_name": "get_output_state",
        "description": (
            "Current on/off state of outputs (valve, pump, relay) with seconds on"
            " and start time; a vent/curtain also gets 'position'. No history. "
            "(get_control_state covers only climate-coordinator actuators.) "
            "Follow the reply's `_reading`. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Output unique_id or name."},
                "channel": {"type": "integer", "description": "One channel index. Omit for all."},
                "device_ids": {"type": "array", "items": {"type": "string"}, "description": "Several at once (max 10)."},
            },
        },
    },

    # ── (C) 오리엔테이션 + 의견 원장 ──────────────────────────────────────────
    {
        "tool_name": "get_system_brief",
        "description": (
            "Start here: what this farm is and how it is doing — places, crops "
            "and stages, control targets, anomalies, device counts, advice ledger"
            " — with 'how_to_proceed' naming the tools to dig further. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "tool_name": "submit_advice",
        "description": (
            "Records advice for a human to review; nothing is executed. When "
            "control seems needed, put it in proposed_action instead of "
            "executing. Differing opinions are kept side by side."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "advice": {"type": "string", "description": "What you observe and how you read it."},
                "title": {"type": "string", "description": "One line. Default: the first sentence."},
                "rationale": {"type": "string", "description": "Which readings or tool results it rests on."},
                "proposed_action": {"type": "string", "description": "Suggested action, in words. Not executed."},
                "scope_type": {"type": "string", "description": "system|farm|zone|facility|device (default system)."},
                "scope_id": {"type": "string", "description": "Target unique_id — set it whenever you can."},
                "severity": {"type": "string", "description": "Default info.", "enum": ["info", "advice", "warning", "urgent"]},
                "confidence": {"type": "number", "description": "0.0-1.0."},
                "agent_kind": {"type": "string", "description": "main|external|subordinate (default external)."},
            },
            "required": ["advice"],
        },
    },
    {
        "tool_name": "list_advice",
        "description": (
            "Reads the advice ledger (main, external and node AIs). Check it "
            "before submitting to avoid duplicates; targets with several opinions"
            " are flagged. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope_type": {"type": "string", "description": "system|farm|zone|facility|device."},
                "scope_id": {"type": "string", "description": "Target unique_id."},
                "status": {"type": "string", "description": "pending|accepted|rejected|superseded."},
                "agent_id": {"type": "string", "description": "Submitter."},
                "severity": {"type": "string", "description": "Severity."},
                "limit": {"type": "integer", "description": "Default 20, max 100."},
            },
        },
    },

    # ── (D) 화면 구성 — 대시보드 위젯과 탭 ────────────────────────────────────
    # Tool(...) 선언만으로는 MCP 에 안 나간다. **이 목록이 카탈로그의 정본**이라
    # 여기 없으면 서버에는 등록됐는데 클라이언트는 도구를 아예 못 본다.
    {
        "tool_name": "list_dashboards",
        "description": (
            "Dashboard tabs and their widgets — what the user sees. Read it "
            "before changing a dashboard. Widget settings are omitted unless "
            "with_options; get_widget reads one. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tab_id": {"type": "string", "description": "Restrict to one dashboard tab. Omit for all of them."},
                "with_options": {"type": "boolean", "description": "Include each widget's full settings. Off by default - it can make the response very large."},
            },
        },
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
        "description": (
            "Adds a widget to a dashboard tab, placed at the bottom. tab_id from "
            "list_dashboards, option ids from list_widget_types — unknown options"
            " are rejected. If the reply sets requires_restart, tell the user; do"
            " not restart anything yourself. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tab_id": {"type": "string", "description": "Dashboard tab to add it to (from list_dashboards)."},
                "widget_type": {"type": "string", "description": "A type from list_widget_types."},
                "name": {"type": "string", "description": "Title shown on the widget. Defaults to the type's name."},
                "options": {"type": "object", "description": "The type's own settings, keyed by the option ids from list_widget_types. Anything not in that schema is rejected."},
                "width": {"type": "integer", "description": "Grid columns. Defaults to the type's own default."},
                "height": {"type": "integer", "description": "Grid rows. Defaults to the type's own default."},
            },
            "required": ["tab_id", "widget_type"],
        },
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
    from aot.tools.aot_data_tool_service import AoTDataToolService
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
    write, even though nobody has to click Approve for it. record_write tools
    (notes, knowledge) are writes for the same reason — see _RECORD_WRITE."""
    return frozenset(t.name for t in TOOLS
                     if t.mutating or t.physical or t.record_write)


def record_write_tools() -> frozenset:
    """Writes that only persist a record (note/knowledge) — see _RECORD_WRITE.
    A subset of write_tools(); never in approval_required_tools()."""
    return frozenset(t.name for t in TOOLS if t.record_write)


#: 공간(space) 서랍의 쓰기 중 **작기 운영이 아닌 것** — 지도 도형·장치 배치.
#: 웹은 이 둘을 설계 권한(`edit_settings`, routes_geo_shape)으로 연다. 구획·
#: 작기 프로그램·단계·자원·구획 일지는 `edit_plots`(routes_geo_plot._require_edit,
#: routes_geo_journal)다. 새 space 쓰기 도구가 지도 편집이면 여기에 넣을 것 —
#: 안 넣으면 작기 운영 권한만으로 열린다(test_plot_write_permission 이 목록을
#: 고정해 새 도구가 들어오면 분류를 묻는다).
_SPACE_NON_PLOT_WRITES = frozenset({'delete_geo_shape', 'set_device_location'})


def plot_write_tools() -> frozenset:
    """작기 운영 쓰기 — 웹과 같은 `edit_plots` 가 필요하다(`edit_settings` 가 함의).

    레지스트리의 도메인(space)에서 파생한다: space 서랍의 쓰기 전부에서 지도
    편집(_SPACE_NON_PLOT_WRITES)을 뺀 것. 구획 생성·수정·종료·삭제·복제·분할,
    단계 이벤트, 자원 적용, 작기 프로그램, 구획 일지가 들어간다. 제어 권한
    (`edit_controllers`)과 일부러 다르다 — 웹이 작기 운영을 그 권한으로 나눴다
    (p6_51). 기록 쓰기와 겹치지 않는다."""
    return frozenset(
        name for name in write_tools()
        if tier_of(name)[0] == 'space' and name not in _SPACE_NON_PLOT_WRITES
    ) - record_write_tools()


def map_edit_tools() -> frozenset:
    """지도 편집 쓰기(도형 삭제·장치 배치) — 웹과 같은 `edit_settings` 가
    필요하다(mcp_safety_gate.required_write_permission). _SPACE_NON_PLOT_WRITES
    중 실제로 등록된 쓰기 도구만."""
    return frozenset(_SPACE_NON_PLOT_WRITES) & write_tools()


def advisory_write_tools() -> frozenset:
    """The advice ledger (submit_advice) — audited as a write, but open to
    read-only keys and advice-only mode. NOT in write_tools()."""
    return frozenset(t.name for t in TOOLS if t.advisory_write)


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
