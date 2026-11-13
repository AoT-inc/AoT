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
    manifest   : 인앱 AI 의 제어 흐름 항목(read_manual·get_detailed_manifest·ask_user)
                 만 갖는다 — get_action_manifest() 의 system_tools 로 그대로 나간다.
                 도구는 도메인 명부로만 노출한다(26-11 5단계) — 다른 도구에 다시
                 달지 말 것.
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
# 순서는 의미가 없다(tool_map 은 dict, 승인 집합은 frozenset). 옛 system_tools
# 매니페스트가 이 순서로 나가던 시절의 묶음 주석(WITH/WITHOUT a manifest)은 이력이다.
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
    Tool('add_schedule', handler='add_schedule_tool', physical=True, config_only=True),
    Tool('add_schedule_batch', handler='add_schedule_batch_tool', physical=True, config_only=True),
    Tool('schedule_device_control', handler='schedule_device_control_tool', physical=True),

    # --- Schedule CRUD (@ANCHOR: SCHEDULE_CRUD_TOOLS) ----------------------------
    # Completes the scheduler as a farm-operations ledger: add_schedule (create)
    # already existed; search/edit/delete close the CRUD loop so the AI can act on
    # a user's "reschedule the spraying" / "cancel Saturday's inspection". All read
    # from / write to SchedulerJobMeta (the ledger of record — A안). edit/delete are
    # `mutating` → the SSOT routes them through the human approval gate in EVERY
    # path (dispatch, planner, agent-loop) automatically; search is read-only.
    Tool('search_schedule', handler='search_schedule_tool'),
    Tool('edit_schedule', handler='edit_schedule_tool', mutating=True),
    Tool('delete_schedule', handler='delete_schedule_tool', mutating=True),

    # --- virtual_tool_call tools WITH a manifest entry (original order) -----------
    Tool('search_devices', handler='search_devices'),
    # 구역 단위 집계. Function 을 만들지 않는다 — 대상·기간이 질문마다 달라
    # 고정 계산기로는 답할 수 없고, influx.py 의 무상태 헬퍼를 조합해 계산만
    # 하고 남기지 않는다. 읽기 전용이므로 승인 대상이 아니다.
    Tool('get_zone_sensor_summary', handler='get_zone_sensor_summary'),
    Tool('get_device_measurements', handler='get_device_measurements'),
    # 장치 하나를 파악하는 데 드는 왕복을 하나로 접는다 (2026-09-21). 지금까지는
    # search_devices(무엇인지) → get_device_measurements(무엇을 재는지) →
    # get_device_location(어디인지) → get_device_freshness(살아있는지) 를 따로
    # 불러야 했다 — MCP 는 호출마다 고정비가 크다. 읽기 전용.
    Tool('get_device_detail', handler='get_device_detail'),
    # --- 적응형 문서 스토리지 (읽기 전용) ---------------------------------------
    # 티어 값은 "옮기겠다는 의도"이고 cold_documents 행이 "실제로 옮겨진 실물"이다.
    # 둘이 아직 연결돼 있지 않아서(이동이 placeholder), 도구 설명에 그 구분을 박아
    # 둔다 — AI 가 tier=3 을 보고 "아카이브됨" 이라고 사용자에게 말하면 안 된다.
    Tool('get_storage_tier_status', handler='get_storage_tier_status'),

    # --- 적응형 문서 스토리지 (쓰기 — 전부 승인 게이트) ------------------------

    Tool('create_function', handler='create_function_tool', mutating=True),
    Tool('modify_function_options', handler='modify_function_options', mutating=True, config_only=True),
    # A sequence's schedule lives in Trigger columns/timer_schedule, not in
    # custom_options, so modify_function_options cannot reach it (it now says
    # so instead of silently no-op'ing). This is the way in.
    Tool('modify_sequence_schedule', handler='modify_sequence_schedule', mutating=True, config_only=True),
    # One call = one weekday's whole plan. The per-step tool below still exists
    # for touch-ups, but laying out a day through it costs ~20 gated calls, and
    # that friction is what pushed a caller into making a redundant sequence.
    Tool('configure_sequence_day', handler='configure_sequence_day', mutating=True, config_only=True),
    # create_sequence_function only lays down uniform steps; this shapes them
    # (groups = simultaneous, per-step duration, total-step margins).
    Tool('modify_sequence_step', handler='modify_sequence_step', mutating=True, config_only=True),
    Tool('create_sequence_function', handler='create_sequence_function', mutating=True, config_only=True),
    Tool('delete_function', handler='delete_function', mutating=True),
    Tool('list_device_types', handler='list_device_types'),
    # @ANCHOR: AGENT_LOOP_GET_TOOL_DETAIL (Phase 1) — the catalog every tool is
    # listed in shows only a name + one-line description to keep prompts lean.
    # Call this for the full argument schema of a specific tool before calling
    # it, if the one-line description isn't enough to know what to pass.
    # 서랍 기구 두 개 — 실행은 MCP 실행층(tool_execution._open_drawer·_get_tool_detail)이
    # 한다. 인앱 처리기는 없다(인앱 AI 는 도메인 명부만 본다).
    Tool('get_tool_detail', handler=None),
    Tool('open_drawer', handler=None),
    Tool('get_device_type_options', handler='get_device_type_options'),
    Tool('create_input', handler='create_input', mutating=True),
    Tool('modify_input', handler='modify_input', mutating=True),
    Tool('delete_input', handler='delete_input', mutating=True),
    Tool('create_output', handler='create_output', mutating=True),
    Tool('modify_output', handler='modify_output', mutating=True),
    Tool('delete_output', handler='delete_output', mutating=True),
    # --- 식생 구획(작기) — docs/design/geo-vegetation-plot.md -------------
    # "어디에 무엇이 심겨 있는가" 는 재배 조언의 전제다. 시설은 구획 프로그램 /
    # facility_registry 로 알 수 있었지만 노지는 알 방법이 없어, AI 가 노지
    # 구역에 대해서는 작물을 모른 채 답하고 있었다.
    #
    # 쓰기 3종은 전부 승인 대상이다. config_only 로 면제하지 말 것 —
    # end/delete 는 되돌릴 수단이 없고(그 자리의 이력이 사라진다),
    # create 는 사람이 밭에서 확인해야 하는 사실을 기록하는 행위다.
    Tool('list_plots', handler='list_plots'),
    Tool('get_plot', handler='get_plot'),
    Tool('get_plot_history', handler='get_plot_history'),
    Tool('list_plot_journals', handler='list_plot_journals'),
    Tool('get_plot_journal', handler='get_plot_journal'),
    # 생성은 InfluxDB 를 크게 읽는다(채널 수 × 기간) — 승인 대상이다.
    # 물리 작동은 없으므로 `physical` 은 아니다.
    Tool('create_plot_journal', handler='create_plot_journal', mutating=True),
    Tool('list_programs', handler='list_programs'),
    Tool('get_program', handler='get_program'),
    Tool('create_program', handler='create_program', mutating=True, config_only=True),
    Tool('modify_program', handler='modify_program', mutating=True, config_only=True),
    Tool('delete_program', handler='delete_program', mutating=True),
    Tool('list_tabs', handler='list_tabs'),
    # ── 대시보드 위젯 ────────────────────────────────────────────────────────
    # 위젯은 사람이 보는 화면이라, 여기서 하는 일은 전부 사용자의 대시보드를
    # 바꾼다. 물리 장치를 움직이지 않는다는 이유로 config_only(승인 면제)에
    # 넣지 말 것 — 면제의 근거는 "아무것도 움직이지 않는다" 인데, 위젯은
    # 사람이 지금 보고 있는 화면을 즉시 바꾼다.
    Tool('list_dashboards', handler='list_dashboards'),
    Tool('list_widget_types', handler='list_widget_types'),
    Tool('get_widget', handler='get_widget'),
    Tool('create_widget', handler='create_widget', mutating=True),
    Tool('modify_widget', handler='modify_widget', mutating=True),
    Tool('delete_widget', handler='delete_widget', mutating=True),

    Tool('create_tab', handler='create_tab', mutating=True),
    Tool('modify_tab', handler='modify_tab', mutating=True),
    Tool('delete_tab', handler='delete_tab', mutating=True),
    Tool('create_plot', handler='create_plot', mutating=True),
    Tool('modify_plot', handler='modify_plot', mutating=True),
    Tool('propose_plot_split', handler='propose_plot_split'),
    Tool('apply_plot_split', handler='apply_plot_split', mutating=True),
    Tool('copy_plot', handler='copy_plot', mutating=True),
    Tool('end_plot', handler='end_plot', mutating=True),
    Tool('confirm_plot_stage', handler='confirm_plot_stage', mutating=True),
    Tool('reschedule_plot_stage', handler='reschedule_plot_stage',
         mutating=True),
    Tool('set_plot_stage_guidance', handler='set_plot_stage_guidance',
         mutating=True),
    Tool('add_plot_stage', handler='add_plot_stage', mutating=True),
    Tool('remove_plot_stage', handler='remove_plot_stage', mutating=True),
    Tool('save_plot_schedule_as_program',
         handler='save_plot_schedule_as_program', mutating=True),
    Tool('undo_plot_stage', handler='undo_plot_stage', mutating=True),
    Tool('apply_plot_resources', handler='apply_plot_resources', mutating=True,
         physical=True),
    Tool('delete_plot', handler='delete_plot', mutating=True),
    # --- GIS Input CRUD (@ANCHOR: GIS_INPUT_CRUD_TOOLS, 2026-07-26) ---------------
    # GIS layers (VWorld/Google/OpenWeather/OSM/... providers overlaid on the map)
    # are GeoLayer rows, but their TYPE registry is the same parse_input_information()
    # as regular sensor Inputs — list_device_types(kind='input')/
    # get_device_type_options(kind='input', ...) already cover 'gis_*' types, so no
    # separate type-lookup tools are added here, just the CRUD that was missing.
    Tool('list_gis_inputs', handler='list_gis_inputs'),
    Tool('create_gis_input', handler='create_gis_input', mutating=True, config_only=True),
    Tool('modify_gis_input', handler='modify_gis_input', mutating=True),
    Tool('activate_gis_input', handler='activate_gis_input', mutating=True),
    Tool('delete_gis_input', handler='delete_gis_input', mutating=True),
    # --- Facility performance/capacity (@ANCHOR: FACILITY_CAPACITY_TOOL, 2026-07-22)
    # geo/design computes engineering capacity for each facility (heating/cooling
    # kW, volume/area, ventilation) plus an irrigation BOM (pipe/emitter/flow) via
    # facility_calc.compute_capacity, surfaced through get_facility_integration.
    # None of it reached the AI before this — neither context nor a tool exposed
    # it, so "is the cooling enough / 관수 유량은?" was unanswerable. Read-only;
    # values are on-demand reference estimates (±5-10%), not persisted nameplates.
    Tool('get_facility_capacity', handler='get_facility_capacity_tool'),
    # --- Map-drawn equipment (@ANCHOR: MAP_EQUIPMENT_TOOL, 2026-07-22) -----------
    # Equipment placed in geo/design (irrigation valves, sprinklers/drip, fans,
    # heaters, window/curtain motors) is stored inside equipment_collection
    # GeoShapes' feature.features[] and was invisible to the AI — build_tree only
    # aggregates a category count and never descends into the collection. This
    # exposes each item's sub_type + specs + which site/zone it sits in.
    Tool('get_map_equipment', handler='get_map_equipment_tool'),
    Tool('get_map_equipment_detail', handler='get_map_equipment_detail_tool'),
    # --- 지도 거리 (@ANCHOR: GEO_DISTANCE_TOOLS, 2026-08-14) ------------------
    # LLM 은 좌표 산술을 조용히 틀린다. 거리는 서버가 세고 LLM 은 받는다.
    # uuid 만 받는 이유는 aot/utils/geo_distance.py docstring 참조 — 이름을
    # 받으면 작물명이 구획이 아니라 소속 zone 으로 해석되어 조용히 틀린다.
    Tool('nearest', handler='nearest'),
    Tool('set_device_location', handler='set_device_location', mutating=True),
    Tool('set_pipe_diameters', handler='set_pipe_diameters', mutating=True),
    Tool('delete_geo_shape', handler='delete_geo_shape', mutating=True),
    # --- Reverse geocoding (@ANCHOR: REVERSE_GEOCODE_TOOL, 2026-07-25) -----------
    # get_local_time (and the retired get_device_location) only returned coordinates; there
    # was no way to ask "what's the address there". VWorld's getAddress API was
    # already used internally (parcel_from_address's PNU pipeline) but never
    # exposed as a standalone lookup. Read-only; requires a registered VWorld
    # GIS Input (Map > GIS Inputs) with an API Key, else returns a clear error.
    Tool('get_address', handler='get_address'),
    # --- Forward geocoding (address -> coordinates) -------------------------------
    # get_address answers "what's the address here"; this is the other direction.
    # Both ask a GIS Input's geocoding API; this one goes through the single lookup
    # gate (aot_flask/geo/geo_lookup.py) so no caller picks a provider or reads a key itself.
    # manifest 없음 — 인앱 프롬프트(서랍 이름 목록)에 싣지 않는다(activate_input 과 같다). 등급 매니페스트의
    # 토큰 예산을 올리지 않으려는 것이고, 외부 MCP 는 도메인 틀의 find.location 과 _MCP_TOOL_PAYLOADS 로 부른다.
    Tool('find_location', handler='find_location'),
    # 지도 즐겨찾기 조회 — find_location 과 같은 까닭으로 manifest 를 두지 않는다(외부 MCP 의 find.favorites).
    Tool('find_favorites', handler='find_favorites'),
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
    Tool('list_pending_confirmations', handler='list_pending_confirmations'),
    Tool('respond_to_confirmation', handler=None, mutating=True),
    Tool('list_ai_agents', handler='list_ai_agents'),
    Tool('list_ai_entries', handler='list_ai_entries'),
    Tool('create_ai_agent', handler='create_ai_agent', mutating=True, config_only=True),
    Tool('modify_ai_agent', handler='modify_ai_agent', mutating=True),
    Tool('delete_ai_agent', handler='delete_ai_agent', mutating=True),
    Tool('get_function_list', handler='get_function_list'),
    Tool('activate_function', handler='activate_function_tool', mutating=True),
    Tool('deactivate_function', handler='deactivate_function_tool', mutating=True),

    # --- Notice board CRUD (@ANCHOR: NOTICE_CRUD_TOOLS, 2026-07-08) ---------------
    # Wraps the same web-route utility functions the notice board UI uses
    # (aot/aot_flask/utils/utils_notice.py notice_add/notice_mod/notice_del) via
    # the shared _FakeForm shim — the exact pattern used for Input/Output CRUD.
    # Attachments and polls are UI-only (the AI can create/edit plain title+body
    # posts; not currently supported here). modify/delete are gated by
    # utils_notice.may_manage_post() (admin, or the author holding edit_settings),
    # judged on the user bound for the call (write_scope) — MCP has no web session.
    Tool('list_notices', handler='list_notices'),
    Tool('create_notice', handler='create_notice', mutating=True),
    Tool('modify_notice', handler='modify_notice', mutating=True),
    Tool('delete_notice', handler='delete_notice', mutating=True),

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
    Tool('create_note', handler='create_note', record_write=True),

    # --- Notes modify/archive (G6, 2026-10-13) ---------------------------------
    # 노트 이름·본문·태그 수정과 보관(is_archived)·복원. 완전 삭제는 웹에만 둔다.
    # record_write(역할 edit_settings·그룹 스코프) 이되 승인은 **호출마다** 갈린다:
    # 본인이 쓴 노트(또는 작성자 기록이 없는 사용자 요청 AI 노트)는 바로, 남의
    # 노트·작성자 불명 노트는 승인 대기(mcp_safety_gate.CONDITIONAL_APPROVAL_TOOLS).
    # 바꾸기 전 값은 감사 로그(before_json)에 남는다. manifest=None — 인앱 프롬프트
    # 고정비 0, MCP 에서는 서랍(record)에 두고 search_notes 설명이 가리킨다.
    Tool('modify_note', handler='modify_note', record_write=True),

    # --- Notes delete (재설계 PR 5, 2026-11-03) ----------------------------------
    # 사용자 결정: AI 가 엉뚱한 곳·원치 않는 내용으로 쓴 노트를 바로 지울 수 있되 **사용자 승인 뒤에만** 실행한다
    # (승인 문구가 제목·붙은 곳·첫 줄을 되읽는다 — mcp_safety_gate.read_back_text). 숨기기(modify_note archive)와
    # 달리 되돌릴 수 없고 본문은 감사 로그에만 남는다. 역할은 웹과 같은 edit_settings(gate.required_write_permission).
    # manifest=None — 인앱 프롬프트 고정비 0.
    Tool('delete_note', handler='delete_note', mutating=True),

    # --- 대상 별칭 (MCP 점검 2026-10-28) ------------------------------------------
    # 사용자가 대상을 부르는 다른 이름(aot/tools/domain/aliases.py). 기록 쓰기 — 장치·설정을
    # 바꾸지 않고 지우면 되돌아가므로 승인 없음, 역할·읽기 전용 키·감사는 다른 기록과 같다.
    # 도메인 틀의 record.alias_add · remove.alias_delete 가 부른다(목록은 find.aliases, 읽기).
    Tool('add_target_alias', handler='add_target_alias', record_write=True),
    Tool('delete_target_alias', handler='delete_target_alias', record_write=True),

    # --- 입력(센서) 켜기/끄기 (MCP 체험 피드백 2026-10-30) ----------------------
    # 도메인 틀의 configure.input_activate 가 부른다(GIS 입력의 activate_gis_input 과 같은 모양).
    # mutating — 켜기·끄기 모두 승인 대상이다. 끌 때는 되읽기에 이 입력을 쓰는 것들과 놓인 곳이 실린다
    # (mcp_safety_gate.read_back_text → data_tools/input_impact). 쓰는 것들을 자동으로 끄지는 않는다.
    # manifest=None — 인앱 프롬프트 고정비 0, 옛 tools/list 에도 싣지 않는다(DOMAIN_ONLY_TOOLS).
    Tool('activate_input', handler='activate_input', mutating=True),

    # --- Knowledge shelve (@ANCHOR: KNOWLEDGE_SHELVE_TOOL, 2026-07-19) -----------
    # Write half of docs/design/ai-library-redesign.md §4 — knowledge_search (read)
    # already existed; nothing let the AI save what it just worked out. NOT
    # approval-gated for the same reason as create_note: it always writes at the
    # lowest trust tier (provenance='ai_curated', unconfirmed — see
    # knowledge_shelve_service.py) and is never presented with authority until a
    # human confirms it or it corroborates against a real source (P5, not built
    # yet) — a low-risk, reversible write, not a state-changing entity mutation.
    # record_write (2026-09-23): not approval-gated, but a write — see _RECORD_WRITE.
    Tool('knowledge_shelve', handler='knowledge_shelve', record_write=True),

    # --- System update / version status (read-only, 2026-07-18) ------------------
    # Wires the AI to AoTRelease().github_upgrade_exists() (same check as the
    # admin/upgrade page) so "is there a system update?" is answerable. Before
    # this, no tool exposed version/update info and the AI could only give a
    # generic "cannot check for updates" reply. Read-only — not approval-gated.
    Tool('get_system_update_status', handler='get_system_update_status'),

    # --- Diagnostic: analyze system failure (@ANCHOR: ANALYZE_SYSTEM_FAILURE_RECONNECT,
    # Phase 2, docs/design/ai-agent-loop.md) — the implementation already existed
    # (AoTDataToolService.analyze_system_failure_tool, 031_STEP_3) but was declared
    # here with handler=None: dispatchable if somehow called, but invisible in the
    # manifest, so the LLM never knew it existed. Read-only (audits AITask failure
    # logs + MCP bridge status) — not approval-gated.
    Tool('analyze_system_failure', handler='analyze_system_failure_tool'),

    # --- Knowledge search (@ANCHOR: KNOWLEDGE_SEARCH_TOOL, Phase 2) -------------
    # Read half of docs/design/ai-library-redesign.md §4 — knowledge_shelve (write)
    # was already a tool; search only existed as a legacy action_type='knowledge_search'
    # branch invoked via a prompt instruction (base_ai.py _build_prompt), never in
    # the tool catalog itself, so the agent loop (which offers tools, not prompt-
    # injected instructions) never surfaced it. Read-only.
    Tool('knowledge_search', handler='knowledge_search_tool'),

    # --- 참조표 (@ANCHOR: REFERENCE_TABLE_TOOLS, 2026-08-24) --------------------
    # 표를 지식 항목으로 적재하지 않고 등록만 해 두고 물어볼 때 조회한다
    # (reference_table_service 모듈 주석). 도구가 둘인 이유는 등록된 표가
    # 설치마다 달라 **정적인 도구 설명에 담을 수 없기** 때문이다. 둘 다 읽기 전용.
    Tool('list_lookup_sources', handler='list_lookup_sources'),
    Tool('query_data_source', handler='query_data_source'),
    Tool('query_reference_table', handler='query_reference_table'),

    # --- Knowledge-library catalog (@ANCHOR: LIBRARY_CATALOG_TOOL, 2026-07-19) ---
    # Without this the AI could only describe SmartFarmKorea (whose setup recipe
    # is injected into the tools below) and answered "what knowledge libraries
    # can I add?" with SmartFarmKorea alone. Read-only enumerator of the full
    # LIBRARY_PRESETS catalog so the AI recommends every source type.
    Tool('list_library_source_types', handler='list_library_source_types_tool'),

    # --- SmartFarmKorea AI-driven setup (@ANCHOR: SMARTFARMKOREA_AI_TOOLS,
    # Phase 2, docs/design/ai-library-redesign.md) — expose Phase 1's discovery
    # primitive so the AI can register a SmartFarmKorea source end-to-end. The
    # RECIPE (discovery order, which param comes from where) is encoded in the
    # usage_hints — the always-visible injection point — so the model can drive
    # the relational drill-down without the user ever typing a code. lookup is
    # read-only; configure mutates (creates a source + fetches external data) →
    # approval-gated.
    Tool('configure_library_source', handler='configure_library_source_tool', mutating=True),

    # --- Local time per location (@ANCHOR: GET_LOCAL_TIME_TOOL, 2026-07-20) ------
    # Every map shape/device carries coordinates, and aot/utils/device_tz.py
    # already resolves an IANA timezone from them (timezonefinder) — but that
    # capability was previously only wired into device/controller/weather code,
    # never exposed to the AI. This gives the AI an explicit, on-demand way to
    # check a SPECIFIC location's actual local time before describing or
    # planning around it, instead of assuming a single global timezone always
    # applies. Read-only — not approval-gated.
    Tool('get_local_time', handler='get_local_time_tool'),

    # --- virtual_tool_call tools WITHOUT a manifest entry (dispatch only) ---------
    # Read tools intentionally omitted from the slim LLM manifest; operate_device is
    # bound per-output via mcp_binding instead of a standalone system_tools entry.
    Tool('get_sensor_detail', handler='get_sensor_detail'),
    Tool('get_spatial_tree', handler='get_spatial_tree'),
    Tool('get_place_overview', handler='get_place_overview'),
    # 이 연결의 키 묶음을 바꾼다(2026-10-10) — 키 발급 뒤에도 사용자가 AI 에게
    # 요청해 가벼움/운영/설정을 오갈 수 있게. 키 id 는 인자가 아니라 인증에서
    # 온다(tool_execution 이 덮어쓴다) — 남의 키를 바꾸는 수단이 되면 안 된다.
    Tool('set_tool_profile', handler='set_tool_profile', mutating=True),
    # 사용자가 지금 어느 기기로 어느 웹 화면을 보는가(2026-10, 화면 연동 P1).
    # 웹 요청에서 짐작한 것이라 읽기다 — 조작은 P2 의 screen_action 이 맡는다.
    # user_id 는 인자가 아니라 인증에서 온다(tool_execution 이 덮어쓴다).
    Tool('get_screen', handler='get_screen'),
    # 화면 연동 P2 — 사용자가 보는 웹 화면을 바꾼다(이동·강조·설정 창 열기 등).
    # 아무것도 저장하지 않아 승인 게이트 대상이 아니다. 대신 세 겹으로 막는다:
    # 그 기기의 "AI 조작 허용" 과 짐작한 화면에 대한 사용자 확인(서버가 강제 —
    # data_tools.system). 키 단위 모듈은 2026-10-10 에 없앴다(운영에 배정).
    Tool('screen_action', handler='screen_action'),
    Tool('resolve_target', handler='resolve_target_tool'),
    Tool('get_device_list', handler='get_device_list_tool'),
    Tool('search_notes', handler='search_notes_tool'),
    # search_notes 의 읽기 짝. 파일명까지만 주는 그 도구에서 실제 픽셀로 내려가는
    # 유일한 경로다. manifest=None 이라 인앱 프롬프트 고정비는 0 이고, 발견은
    # search_notes 응답의 조건부 _reading 이 담당한다(첨부가 있을 때만 안내).
    Tool('get_note_attachment', handler='get_note_attachment_tool'),
    Tool('get_energy_report', handler='get_energy_report'),
    Tool('operate_device', handler='operate_device_tool', physical=True),
    Tool('get_weather', handler='get_weather_tool'),
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
# @manual ai/overview#tool-drawers
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
    'modify_note':               ('record', 'drawer', False),
    'delete_note':               ('record', 'drawer', False),
    'add_target_alias':          ('record', 'drawer', False),
    'delete_target_alias':       ('record', 'drawer', False),
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
    'get_place_overview':        ('space', 'core', False),
    'set_tool_profile':          ('system', 'drawer', False),
    # "이 화면" 을 말하는 사용자는 도구 이름을 모른다 — AI 가 떠올려야 한다.
    'get_screen':                ('system', 'core', True),
    # 서랍. 키에 'screen' 모듈을 켠 경우에만 보이고, get_screen(core)의 응답이
    # 화면마다 ai_control 을 알려 준다 — 상시 노출 상한(35)을 넘기지 않는다.
    'screen_action':             ('system', 'drawer', False),
    'get_crop_status':           ('space', 'drawer', False),
    'delete_geo_shape':          ('space', 'drawer', False),
    'set_pipe_diameters':        ('space', 'drawer', False),
    'set_device_location':       ('space', 'drawer', False),
    'get_map_equipment':         ('space', 'core', False),
    'get_map_equipment_detail':  ('space', 'drawer', False),
    'get_facility_capacity':     ('space', 'drawer', False),
    'get_address':               ('space', 'drawer', False),
    'find_location':             ('space', 'drawer', False),
    'find_favorites':            ('space', 'drawer', False),
    'nearest':                   ('space', 'drawer', False),
    # --- 장치 정의 ----------------------------------------------------------
    'create_input':              ('definition', 'drawer', False),
    'modify_input':              ('definition', 'drawer', False),
    'activate_input':            ('definition', 'drawer', False),
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
# @manual-end


# ---------------------------------------------------------------------------
# API 키별 도구 묶음(tool profile) — 외부 MCP 표면에서 **무엇을 보여 주는가**.
#
# 키의 scope(full/readonly)는 "무엇을 해도 되는가"(보안 경계)이고, 묶음은
# "무엇을 목록에 싣는가"(표면)다. 둘은 다른 축이라 섞지 않는다 — 묶음 밖 도구를
# 부르면 거절하지만, 그것은 목록과 실행을 맞추는 일관성일 뿐 권한 판단이 아니다.
#
# 묶음 = 운영(항상) + 사람이 고른 **설정 모듈**(2026-09-29). 모듈은 설정 도구를
# 용도별로 나눈 칸이다(TOOL_MODULES). 설정 전체(65개 ≈23k 토큰)를 켜거나 끄는
# 둘뿐이면, 구획만 설계하는 키도 장치 정의·화면·AI 설정까지 대화마다 싣는다.
# **모델이 대화 중에 고르는 구조가 아니라 사람이 키 발급 때 고르는 구조**다 —
# 모델이 고르는 서랍 방식은 모델이 서랍을 열지 않아 실패했다(_tiering_enabled).
#
#   operations    — 일상 운영(기본). 조회·제어·일정·기록·작기 단계 사건.
#   configuration — 운영 + **모든** 모듈. 모듈이 늘어도 저절로 포함된다
#                   ("더하기" — 예전 뜻 그대로라 기존 키의 목록이 바뀌지 않는다).
#   operations+plots+map … — 운영 + 고른 모듈(TOOL_MODULES 순서로 정규화).
#
# 이 "묶음 값"(문자열 하나)이 인증 스냅샷(RoleInfo.tool_profile)부터 전송(stdio·
# HTTP·REST·중앙 인증)·목록·실행·안내문·거절까지 그대로 흐른다. 값 하나로 두는
# 이유: 모듈 집합을 따로 들고 다니면 자리마다 둘 중 하나를 빠뜨려 목록과 실행이
# 갈라진다. 문자열이라 해시 가능하고(lru_cache), 옛 두 값은 뜻이 그대로다.
# 저장은 두 칸이다(user_api_key.tool_profile + tool_modules, p6_80).
#
# 표 값은 넷 중 하나다:
#   'operations' / 모듈 이름 — 운영이거나, 그 모듈을 켠 키부터 보인다.
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
# 것 포함) — 표에 없는 이름은 **모듈을 전부 켠 키에만** 보이게 하는 규칙
# (tool_in_profile)은 새 도구가 배정 없이 들어올 때를 위한 안전장치일 뿐, 배정을
# 대신하지 않는다.
#
# 모듈 배정 규칙(모듈 R6): 모듈 M 도구의 설명·응답은 운영 ∪ M 밖 도구 이름을
# 부르지 않는다 — M 만 켠 키에서 목록에 없는 이름을 가리키게 된다. 서로를
# 가리키는 도구는 같은 모듈에 둔다(test_mcp_tool_profiles 가 검사한다).
TOOL_PROFILE_OPERATIONS = 'operations'
TOOL_PROFILE_CONFIGURATION = 'configuration'
#: 가벼움(2026-10-10) — **할 수 있는 일은 운영과 같고 처음 싣는 목록만 작다.**
#: 무료 요금제에서 질문 한두 개로 사용 한도가 차던 원인이 매 요청 실리는 도구
#: 목록이었다(실제 대화 35개 계산: 총입력의 53~70%, .local/reports/
#: mcp-free-tier-token-baseline-20261010.md). LITE_LISTED 만 목록에 싣고 나머지
#: 운영 도구는 안내문의 이름 색인 + use_tool 로 부른다. 설정 모듈은 켜지 않는다
#: (켜면 목록이 다시 커진다).
TOOL_PROFILE_LITE = 'lite'
TOOL_PROFILES = (TOOL_PROFILE_OPERATIONS, TOOL_PROFILE_CONFIGURATION,
                 TOOL_PROFILE_LITE)
#: 가벼움 묶음이 tools/list 에 싣는 도구. 기준: 보통 설치(지도 1장·대지 1~5개)의
#: 흔한 질문이 서랍 없이 끝나는가 — 장소 하나·농장 전체는 get_place_overview 가
#: 한 번에 답한다. 이름 풀기는 도구들이 이름을 직접 받으므로 넣지 않았다.
LITE_LISTED = frozenset({
    'get_place_overview', 'get_sensor_reading', 'list_plots',
    'get_control_state', 'get_weather', 'operate_device',
    'respond_to_confirmation', 'use_tool', 'get_tool_detail', 'read_tool',
    # "이 화면" 을 말하는 사용자는 도구 이름을 모른다 — 색인 안의 이름으로는
    # 모델이 떠올리지 못한다(화면 연동의 core 배정과 같은 판단, 2026-10-10).
    'get_screen',
})
#: 가벼움 색인에서 인자까지 보여 주는 도구(2026-10-10). claude.ai 측정에서 모델은
#: 목록 밖 도구를 부르기 전에 get_tool_detail 로 인자를 먼저 물었다 — 쓰기 넷
#: (search_schedule·create_note·create_notice·schedule_device_control)이 매번 그랬고,
#: 그때마다 왕복 한 번과 허락 창 하나가 더해졌다. 자주 쓰는 도구만 싣는다 —
#: 전부 실으면 목록이 운영 묶음만큼 커진다. 필수 인자는 전부, 선택 인자는 흔히
#: 쓰는 것만(앞에 `?` 를 붙여 낸다). 스키마와 어긋나면 테스트가 막는다
#: (test_mcp_lite_profile.LiteArgHintTest).
LITE_ARG_HINTS = {
    'search_schedule':         ('query', 'include_past'),
    'search_notes':            ('query', 'target_name'),
    'get_plot':                ('plot_id',),
    'create_note':             ('note', 'name', 'target_name'),
    'create_notice':           ('title', 'body'),
    'add_schedule':            ('content', 'date', 'time', 'target_name'),
    'schedule_device_control': ('device_id', 'state', 'scheduled_time',
                                'duration_minutes'),
    'activate_function':       ('function_id',),
    'deactivate_function':     ('function_id',),
}
_PROFILE_RETIRED = 'retired'
_PROFILE_DRAWER = 'drawer'
#: 인증 스냅샷에만 싣는 표지 — 내부 AI 서비스 계정의 연결(인앱 물리 제어가
#: stdio 하위 프로세스로 들어오는 길)이다. 키에 저장하는 값이 아니며
#: (normalize_tool_profile 은 이 값을 운영으로 좁힌다), mcp_auth.tool_profile_of
#: 가 None(제한 없음)으로 바꿔 넘긴다. None 을 그대로 쓰지 않는 이유: 스냅샷의
#: None 은 "묶음이 비었다 → 기본 묶음" 으로 읽힌다.
TOOL_PROFILE_UNRESTRICTED = 'unrestricted'

#: 설정 모듈 — 이 순서가 묶음 값·화면·안내문의 순서다. 이름은 저장값이라
#: 바꾸지 말 것(바꾸면 그 모듈을 켠 키가 조용히 좁아진다 — 모르는 모듈은
#: 버린다). 모델 쪽 사본 user_api_key.TOOL_MODULES 와 같아야 한다(검사가 대조).
TOOL_MODULES = ('plots', 'map', 'automation', 'devices', 'dashboard',
                'library', 'admin')
#: 모듈마다 모델에게 알리는 한 줄(영문) — 서버 안내문·거절 메시지에 싣는다.
#: **도구 이름을 싣지 않는다**(R6 — 목록에 없는 이름을 가리키는 안내는 모델이
#: 주입으로 오인했다). 분야로만 말한다. 짧게: 꺼진 모듈마다 한 줄씩 나간다.
TOOL_MODULE_SUMMARIES = {
    'plots': 'plots, stages, splits, programs (assign to unassigned plots)',
    'map': 'placement, shapes, pipe diameters',
    'automation': 'create/delete automations, sequence day plans',
    'devices': 'device and GIS input definitions',
    'dashboard': 'dashboards, widgets, tabs',
    'library': 'library sources',
    'admin': 'update/storage status, AI agents',
}
#: 묶음 값에서 운영과 모듈을 잇는 기호. 쉼표가 아닌 이유: 거절 메시지 등에
#: "(operations+plots)" 로 그대로 실려도 목록처럼 읽히지 않고 한 값으로 읽힌다.
TOOL_PROFILE_SEP = '+'

_OPS = TOOL_PROFILE_OPERATIONS
_M_PLOTS, _M_MAP, _M_AUTO, _M_DEV, _M_DASH, _M_LIB, _M_ADMIN = TOOL_MODULES
#: 저장하지 않지만 사용자에게 보이는 무언가를 바꾸는 도구 — 게이트 분류로는
#: 'read' 다(승인 대상이 아니다). 그래도 읽기 전용 표시를 붙이거나 read_tool 이
#: 받으면 안 된다: 호스트가 묻지 않고 실행하고, 모델은 "조회" 로 알고 부른다.
#: screen_action 은 기기별 "AI 화면 조작 허용" 과 확인 토큰으로 따로 막는다.
#: action='post'(AI 수신함 카드)는 키 주인 본인의 수신함에만 쓴다 — 저장 대상이
#: 본인 하나뿐이고 분당 6/일 100 제한과 감사(ai_card.post)가 따로 있다(2026-10-19).
ACTS_WITHOUT_SAVING = frozenset({'screen_action'})

_MCP_PROFILE = {
    # --- 장치 ---------------------------------------------------------------
    'search_devices':            _OPS,
    'get_output_state':          _OPS,
    'operate_device':            _OPS,
    'get_device_measurements':   _OPS,
    'get_device_detail':         _OPS,
    'get_control_state':         _OPS,
    'get_device_list':           _OPS,
    # operate_device 와 같은 일을 하는 네이티브 도구. 인앱 AI 에는 남고, 외부 키는 도메인 operation
    # (control.output_timed)으로만 닿는다(DOMAIN_ROUTED_TOOLS).
    'set_output_state':          _PROFILE_RETIRED,
    # get_device_list·search_devices 와 겹치는 네이티브 도구. 외부 키는 find.controllable 로만 닿는다.
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
    'activate_function':         _OPS,
    'deactivate_function':       _OPS,
    # 제어기 옵션·시퀀스 운전 시간 조정("관수 5분 늘려")은 현장의 일상이다.
    'modify_function_options':   _OPS,
    'modify_sequence_schedule':  _OPS,
    # 자동화 작성(automation) — 함수·시퀀스를 새로 만들거나 지우고 요일 계획을
    # 통째로 까는 일. 켜고 끄기·옵션·운전 시간 조정은 위의 운영이다.
    'create_function':           _M_AUTO,
    'delete_function':           _M_AUTO,
    'create_sequence_function':  _M_AUTO,
    'configure_sequence_day':    _M_AUTO,
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
    'modify_note':               _OPS,
    'delete_note':               _OPS,
    'add_target_alias':          _OPS,
    'delete_target_alias':       _OPS,
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
    # 공지 수정/삭제·라이브러리 소스·지식 보관은 library 하나다 —
    # 모두 "쌓인 문서를 정리하는 일" 이고, 설명·응답이 서로를 가리킨다
    # (configure_library_source ↔ smartfarmkorea_lookup). 공지 **작성**(create_notice)과 조회는 현장
    # 일상이라 운영에 남는다.
    # 공지 작성(create_notice)에 이어 고치기·지우기도 운영이다(2026-11-03 재설계 PR 4) —
    # 방금 쓴 공지를 바로 바로잡을 수 있어야 한다. 승인 규칙은 안쪽 도구 그대로.
    'modify_notice':             _OPS,
    'delete_notice':             _OPS,
    'knowledge_shelve':          _M_LIB,
    'list_library_source_types': _M_LIB,
    'configure_library_source':  _M_LIB,
    # --- 공간 ---------------------------------------------------------------
    'list_plots':                _OPS,
    'get_plot':                  _OPS,
    'get_map_equipment':         _OPS,
    'get_map_equipment_detail':  _OPS,
    'get_spatial_tree':          _OPS,
    'get_place_overview':        _OPS,
    'set_tool_profile':          _OPS,
    'get_screen':                _OPS,
    # 화면 조작은 키마다 따로 켠다(사용자 결정 2026-10-10 — "화면 제어" 권한).
    # 운영(2026-10-10 사용자 결정 번복). 처음에는 키마다 켜는 'screen' 모듈에
    # 두었는데, 운영·설정 연결의 AI 가 "화면 제어 권한이 없다" 고 답했다 —
    # OAuth 연결은 aot.config 범위가 없으면 설정 묶음도 운영으로 내려가 모듈을
    # 못 받는다. 키 단위 허락은 없앴고, 기기별 "AI 화면 조작 허용" 과 확인
    # 토큰(data_tools.system)은 그대로다. 가벼움도 운영과 같이 닿는다.
    'screen_action':             _OPS,
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
    # 작기 설계(plots) — 구획 만들기·나누기·단계 틀·작기 프로그램. 프로그램
    # 조회(list_programs·get_program)도 여기다: 구획을 설계할 때만 쓰고, 운영
    # 키는 get_plot 이 그 구획의 일정을 이미 싣는다. 구획과 프로그램은 설명이
    # 서로를 가리켜(create_plot → list_programs, delete_program·
    # save_plot_schedule_as_program → modify_plot) 한 모듈이어야 한다.
    'create_plot':               _M_PLOTS,
    'modify_plot':               _M_PLOTS,
    'delete_plot':               _M_PLOTS,
    'copy_plot':                 _M_PLOTS,
    'propose_plot_split':        _M_PLOTS,
    'apply_plot_split':          _M_PLOTS,
    'set_plot_stage_guidance':   _M_PLOTS,
    'add_plot_stage':            _M_PLOTS,
    'remove_plot_stage':         _M_PLOTS,
    'save_plot_schedule_as_program': _M_PLOTS,
    'list_programs':             _M_PLOTS,
    'get_program':               _M_PLOTS,
    'create_program':            _M_PLOTS,
    'modify_program':            _M_PLOTS,
    'delete_program':            _M_PLOTS,
    # 지도·위치(map) — 장치 배치(set_device_location)와 도형 정리는 설정이다.
    # 위치 **조회**는 운영이다: get_device_location·get_map_equipment, 그리고
    # 주소·거리·가까운 것 찾기(2026-11-03 재설계 PR 4 — "가장 가까운 구획" 같은
    # 일상 질문이 설정 키에서만 되던 것을 올렸다). get_address 는 VWorld 키(GIS 입력)가
    # 있어야 한다 - 없는 설치에서는 오류로 그 사실을 말한다.
    'get_address':               _OPS,
    'find_location':             _OPS,
    'find_favorites':            _OPS,
    'nearest':                   _OPS,
    'set_device_location':       _M_MAP,
    'delete_geo_shape':          _M_MAP,
    'set_pipe_diameters':        _M_MAP,
    # --- 장치 정의 ----------------------------------------------------------
    # 장치 정의(devices) — 입출력·GIS 입력의 종류 조회와 CRUD. 종류 조회
    # (list_device_types)는 kind=function 도 받지만 create_function 이 종류를
    # enum 으로 싣고 있어 automation 은 이것 없이 닫혀 있다.
    'list_device_types':         _M_DEV,
    'get_device_type_options':   _M_DEV,
    'create_input':              _M_DEV,
    'modify_input':              _M_DEV,
    'activate_input':            _M_DEV,
    'delete_input':              _M_DEV,
    'create_output':             _M_DEV,
    'modify_output':             _M_DEV,
    'delete_output':             _M_DEV,
    'list_gis_inputs':           _M_DEV,
    'create_gis_input':          _M_DEV,
    'modify_gis_input':          _M_DEV,
    'activate_gis_input':        _M_DEV,
    'delete_gis_input':          _M_DEV,
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
    # 시스템·AI 설정(admin) — 업데이트·저장소 계층 상태와 AI 에이전트 설정.
    # 관리자가 가끔 보는 것이라 현장 키에는 필요 없다.
    'get_system_update_status':  _M_ADMIN,
    'get_storage_tier_status':   _M_ADMIN,
    # 화면(dashboard) — 대시보드·위젯·탭 구성.
    'list_dashboards':           _M_DASH,
    'list_widget_types':         _M_DASH,
    'get_widget':                _M_DASH,
    'create_widget':             _M_DASH,
    'modify_widget':             _M_DASH,
    'delete_widget':             _M_DASH,
    'list_tabs':                 _M_DASH,
    'create_tab':                _M_DASH,
    'modify_tab':                _M_DASH,
    'delete_tab':                _M_DASH,
    'list_ai_agents':            _M_ADMIN,
    'list_ai_entries':           _M_ADMIN,
    'create_ai_agent':           _M_ADMIN,
    'modify_ai_agent':           _M_ADMIN,
    'delete_ai_agent':           _M_ADMIN,
    # 서랍 기구 — 묶음이 아니라 서랍 스위치를 따른다.
    'open_drawer':               _PROFILE_DRAWER,
    'get_tool_detail':           _PROFILE_DRAWER,
    'use_tool':                  _PROFILE_DRAWER,
    # 가벼움 전용 — 목록 밖 **읽기** 도구를 부른다(읽기 전용 표시로 허락 창 없이).
    'read_tool':                 _PROFILE_DRAWER,
}

_PROFILE_VALUES = (frozenset({TOOL_PROFILE_OPERATIONS}) | frozenset(TOOL_MODULES)
                   | {_PROFILE_RETIRED, _PROFILE_DRAWER})
for _name, _value in _MCP_PROFILE.items():
    if _value not in _PROFILE_VALUES:
        raise ValueError(
            f"tool_registry: 묶음 표에 모르는 값이 있습니다 — {_name}: {_value}")
if set(TOOL_MODULE_SUMMARIES) != set(TOOL_MODULES):
    raise ValueError("tool_registry: 모듈 요약과 모듈 목록이 어긋났습니다")

_ALL_MODULES = frozenset(TOOL_MODULES)


# @manual ai/overview#tool-profiles
def compose_tool_profile(modules):
    """켤 모듈들 → 정규화한 묶음 값.

    모르는 모듈은 버린다(좁히는 쪽). 하나도 없으면 'operations', 전부면
    'configuration' — 전부 켠 키는 앞으로 생길 모듈까지 받는 설정 묶음과 같게
    둔다(화면에서 전부 체크 = 예전 "운영 + 설정")."""
    chosen = {m for m in (modules or ()) if m in _ALL_MODULES}
    if not chosen:
        return TOOL_PROFILE_OPERATIONS
    if chosen == _ALL_MODULES:
        return TOOL_PROFILE_CONFIGURATION
    return TOOL_PROFILE_SEP.join(
        [TOOL_PROFILE_OPERATIONS] + [m for m in TOOL_MODULES if m in chosen])


# @manual ai/overview#tool-profiles
def parse_tool_profile(value):
    """묶음 값을 엄격히 읽는다 — 정규화한 값, 읽을 수 없으면 None.

    화면·요청에서 들어온 값의 검증용이다(모르는 모듈이 하나라도 있으면 None →
    호출자가 거절한다). 저장값·스냅샷을 읽을 때는 normalize_tool_profile."""
    if not isinstance(value, str):
        return None
    if value in TOOL_PROFILES:
        return value
    head, _sep, rest = value.partition(TOOL_PROFILE_SEP)
    if head != TOOL_PROFILE_OPERATIONS or not rest:
        return None
    parts = rest.split(TOOL_PROFILE_SEP)
    if any(p not in _ALL_MODULES for p in parts):
        return None
    return compose_tool_profile(parts)


# @manual ai/overview#tool-profiles
def normalize_tool_profile(value):
    """키에 저장하거나 연결에 적용할 묶음 값. 모르는 값·빈 값은 운영으로 좁힌다.

    scope 와 같은 원칙이다 — 오타 하나가 조용히 넓은 표면을 만들지 않게 한다.
    'operations+…' 안의 모르는 모듈은 그 모듈만 버린다(없어진 모듈 이름이
    저장돼 있어도 나머지 모듈은 산다). 앞머리가 운영이 아니면 운영이다."""
    if value in TOOL_PROFILES:
        return value
    if not isinstance(value, str):
        return TOOL_PROFILE_OPERATIONS
    head, _sep, rest = value.partition(TOOL_PROFILE_SEP)
    if head != TOOL_PROFILE_OPERATIONS:
        return TOOL_PROFILE_OPERATIONS
    return compose_tool_profile(rest.split(TOOL_PROFILE_SEP))


# @manual ai/overview#tool-profiles
def profile_modules(profile):
    """그 묶음이 켠 모듈(frozenset). 'configuration' 은 지금 있는 모듈 전부."""
    return _profile_modules(normalize_tool_profile(profile))


@functools.lru_cache(maxsize=None)
def _profile_modules(profile):
    if profile == TOOL_PROFILE_CONFIGURATION:
        return _ALL_MODULES
    _head, _sep, rest = profile.partition(TOOL_PROFILE_SEP)
    return frozenset(rest.split(TOOL_PROFILE_SEP)) if rest else frozenset()


# @manual ai/overview#tool-profiles
def profile_from_storage(tool_profile, tool_modules):
    """키 행의 두 칸(user_api_key.tool_profile, tool_modules) → 묶음 값.

    'configuration' 은 모듈 칸을 보지 않는다(언제나 전부). 'operations' 이면
    모듈 칸(쉼표 목록)을 더한다. 그 밖(빈 값 포함)은 운영 — 배정 전(NULL)을
    운영으로 보는 것은 호출자(mcp_auth.key_tool_profile)의 규칙과 같다."""
    if tool_profile in (TOOL_PROFILE_CONFIGURATION, TOOL_PROFILE_LITE):
        return tool_profile
    if tool_profile != TOOL_PROFILE_OPERATIONS:
        return TOOL_PROFILE_OPERATIONS
    return compose_tool_profile(
        m.strip() for m in (tool_modules or '').split(','))


def mcp_profile_of(name):
    """MCP 표면 도구의 묶음 단계 — 'operations' / 'configuration'(어느 모듈이든)
    / 'retired' / 'drawer'. 표에 없으면 None. 모듈은 mcp_module_of."""
    value = _MCP_PROFILE.get(name)
    return TOOL_PROFILE_CONFIGURATION if value in _ALL_MODULES else value


def mcp_module_of(name):
    """설정 도구가 속한 모듈. 운영·retired·서랍 기구·표에 없는 이름은 None."""
    value = _MCP_PROFILE.get(name)
    return value if value in _ALL_MODULES else None


def mcp_profile_table():
    """배정표 사본 — 단계로(검사·문서용). 모듈 배정은 mcp_module_table."""
    return {n: mcp_profile_of(n) for n in _MCP_PROFILE}


def mcp_module_table():
    """배정표 원본 사본 — 설정 도구는 모듈 이름으로."""
    return dict(_MCP_PROFILE)


def module_tools(module):
    """그 모듈에 배정된 도구 이름(frozenset). 모르는 모듈은 빈 집합."""
    return frozenset(n for n, v in _MCP_PROFILE.items() if v == module)


# @manual ai/overview#tool-profiles
def profile_tools(profile):
    """그 묶음이 보여 주는 도구 이름 = 운영 + 켠 모듈의 도구(운영 ⊆ 모든 묶음).

    서랍 기구와 retired 는 어느 묶음에도 들지 않는다 — 앞의 것은 서랍 스위치가,
    뒤의 것은 "묶음 없음(제한 없음)" 호출자만 본다."""
    return _profile_tools(normalize_tool_profile(profile))


@functools.lru_cache(maxsize=None)
def _profile_tools(profile):
    wanted = {TOOL_PROFILE_OPERATIONS} | _profile_modules(profile)
    return frozenset(n for n, v in _MCP_PROFILE.items() if v in wanted)


def is_declared_tool(name):
    """TOOLS 에 선언된 이름인가(MCP 카탈로그 밖의 내부 도구 포함)."""
    return name in _BY_NAME


def is_drawer_machinery(name):
    return _MCP_PROFILE.get(name) == _PROFILE_DRAWER


def is_retired_from_mcp(name):
    return _MCP_PROFILE.get(name) == _PROFILE_RETIRED


#: 옛 tools/list 에는 없고(퇴역) 도메인 틀의 operation 으로만 닿는 네이티브 도구 — find.controllable ·
#: control.output_timed (2026-11-03 사용자 결정으로 되살림). 직접 이름으로 부르면 예전처럼 묶음 밖 거절이다.
DOMAIN_ROUTED_TOOLS = frozenset({'list_available_devices', 'set_output_state'})


# @manual ai/overview#tool-profiles
def tool_in_profile(name, profile, via_domain=False):
    """묶음 `profile` 인 호출자에게 이 도구를 보여 주는가.

    via_domain: 도메인 틀의 operation 이 안쪽 도구로 부르는 길이다 — 퇴역이지만 operation 으로만 닿는
    도구(DOMAIN_ROUTED_TOOLS)는 묶음이 있는 키에게 이 길로는 열린다.

    profile 이 None 이면 제한이 없다(인앱 AI). 서랍 기구는 묶음과 무관하게
    참이다 — 서랍 스위치가 따로 정한다. 표에 없는 이름은 **모듈을 전부 켠
    묶음에만** 보인다(새 도구가 배정 없이 들어와도 운영·일부 모듈 키의 표면이
    조용히 커지지 않게 — 어느 모듈 것인지 모르므로 좁은 쪽으로 친다)."""
    if profile is None:
        return True
    if via_domain and name in DOMAIN_ROUTED_TOOLS:
        return True
    value = _MCP_PROFILE.get(name)
    if value == _PROFILE_DRAWER:
        return True
    if value is None:
        return profile_modules(profile) >= _ALL_MODULES
    return name in profile_tools(profile)


#: 도메인 틀의 operation 으로만 부르는 안쪽 도구 — 옛 tools/list 에 싣지 않는다(실행·게이트·
#: 감사는 다른 도구와 같다). 도메인 틀이 생긴 뒤 들어온 기능이라 옛 목록에 이름을 늘릴 까닭이 없다
#: (대상 별칭, 2026-10-28: record.alias_add · remove.alias_delete).
DOMAIN_ONLY_TOOLS = frozenset({'add_target_alias', 'delete_target_alias', 'activate_input', 'find_location', 'find_favorites'})


#: 도메인 표면에서 **운영으로 올린** 도구 → 옛 표면이 두던 모듈(2026-11-03 재설계 PR 4). 위치 조회(주소·거리·가까운 것)와
#: 공지 고치기·지우기는 일상 질문이라 `_MCP_PROFILE` 에서 운영으로 올렸다. 그런데 옛 표면의 운영 목록은 크기 상한(기준선의
#: 115%)에 거의 닿아 있어 다섯을 더하면 넘는다 — 상한은 올리지 않는다. 그래서 옛 `tools/list` 는 이 도구를 **원래 모듈을
#: 켠 묶음에서만** 싣는다(옛 설정 묶음은 예전 그대로). 실행·권한은 운영 도구와 같아 호출 자체는 어느 묶음에서든 된다.
DOMAIN_PROMOTED_TOOLS = {
    'nearest': _M_MAP, 'get_address': _M_MAP,
    'modify_notice': _M_LIB, 'delete_notice': _M_LIB,
    # 노트 지우기(재설계 PR 5)도 같다 — 옛 표면의 운영 목록 크기 상한 때문에 옛 목록에는 도서관 모듈을 켠 묶음에서만 싣는다.
    'delete_note': _M_LIB,
}


def legacy_hidden_tools(profile):
    """옛 `tools/list` 에서 이 묶음에 싣지 않을 승격 도구 — 원래 모듈이 꺼진 묶음에서만."""
    modules = profile_modules(profile)
    return frozenset(n for n, m in DOMAIN_PROMOTED_TOOLS.items() if m not in modules)


# ---------------------------------------------------------------------------
# MCP 묶음 도구(facade) — 인자가 거의 같은 쓰기 도구 가족을 tools/list 에서 한
# 줄로 낸다(2026-10-10, 구획 단계 6종부터). 목록 크기의 대부분은 도구마다
# 되풀이되는 이름·설명·공통 인자라, 인자가 비슷한 가족만 묶어야 줄어든다
# (재판단 메모: .local/reports/mcp-surface-redesign-reassessment-20261010.md).
#
# - **operation 값은 안쪽 도구 이름 그대로다.** 응답·설명이 이미 그 이름으로
#   서로를 가리키고(STAGE_TOOL_RULE 등), 승인 큐·감사 기록에도 안쪽 이름이
#   남아야 사람이 무엇을 승인하는지 안다. 짧은 별칭을 두면 두 어휘가 생긴다.
# - 실행은 안쪽 도구로 **위임**한다(tool_execution._execute_tool) — 승인·묶음·
#   스코프·인자 검사가 직접 호출과 똑같다. 바깥에서 게이트를 한 번 더 태우지
#   않는다(use_tool 과 같은 이유).
# - 안쪽 도구는 TOOLS·_MCP_TOOL_PAYLOADS·_MCP_PROFILE 에 그대로 남는다. 인앱
#   AI·서랍·직접 호출은 영향이 없고, 바뀌는 것은 MCP tools/list 의 모양뿐이다.
# - 묶음이 갈리는 가족(구획 단계는 운영 3 + 구획 모듈 3)도 묶는다. 목록은 키가
#   쓸 수 있는 operation 과 그 인자만 싣고, 실행 판정은 안쪽 도구가 한다.
# ---------------------------------------------------------------------------
MCP_FACADES: Dict[str, Dict[str, Any]] = {
    'plot_stage': {
        'description': (
            "Changes ONE plot's stage schedule; the programme is never touched. "
            "Keys and dates: get_plot's stage_schedule / stage_proposal — never "
            "compose a key. Pick `operation`:"),
        'tail': "Requires human approval.",
        'common': ('plot_id',),
        'operations': {
            'confirm_plot_stage': (
                "the plot HAS entered a stage (the grower says so, or "
                "stage_proposal suggests it); later stages are recomputed from "
                "started_on (stage_proposal.started_on unless the grower names a "
                "day — never invent one)",
                ('stage_key', 'started_on')),
            'reschedule_plot_stage': (
                "move a boundary still AHEAD ('transplanting slipped a week'); "
                "exactly one of days | shift_days | started_on; later boundaries "
                "shift with it",
                ('stage_key', 'days', 'shift_days', 'started_on')),
            'undo_plot_stage': (
                "undo the most recent confirmation (kept, marked undone)",
                ()),
            'set_plot_stage_guidance': (
                "write what to do in that stage here; empty string clears it",
                ('stage_key', 'guidance')),
            'add_plot_stage': (
                "add a stage to this plot only (key is generated)",
                ('name', 'days', 'after', 'guidance')),
            'remove_plot_stage': (
                "drop a stage not yet passed",
                ('stage_key',)),
        },
        'properties': {
            'plot_id': {"type": "string", "description": "Plot unique_id."},
            'stage_key': {"type": "string", "description": "From stage_proposal or stage_schedule."},
            'started_on': {"type": "string", "description": "'YYYY-MM-DD'."},
            'days': {"type": "integer", "description": "reschedule: make that stage last N days. add: its length (1+)."},
            'shift_days': {"type": "integer", "description": "Move its start: +7 later, -3 earlier."},
            'name': {"type": "string", "description": "New stage name as the grower says it."},
            'after': {"type": "string", "description": "stage_key it follows; '' = first, omit = last."},
            'guidance': {"type": "string", "description": "What to do in that stage."},
        },
    },
    # 사람 작업 일정 만들기 — 둘 다 승인 없이 저장한다(같은 승인 성격).
    # 고치기·취소(edit/delete_schedule, 승인 필요)는 묶지 않는다: 둘을 묶어도
    # 586 → 567 추정 토큰이라(2026-10-10 실측) 줄어드는 것이 없다 — delete 가
    # 이미 작고 인자가 거의 겹치지 않는다. 나머지 이름에 schedule 이 든 도구는
    # 가족이 다르다(장치 제어·시퀀스·구획·읽기).
    'schedule_add': {
        'description': (
            "Records dated tasks for PEOPLE (weeding, inspection) — saved without "
            "an approval step. Device control at a time is schedule_device_control. "
            "A name resolves to ONE place and never fans out: for 'each zone' "
            "requests get the children from resolve_target and use the batch. "
            "Pick `operation`:"),
        'tail': ("An ambiguous or unknown place returns needs_disambiguation — ask, "
                 "then retry with the exact name or use_name."),
        'common': ('date',),
        'operations': {
            'add_schedule': (
                "one task; pass target_name whenever the user names a place, omit "
                "only for a farm-wide event",
                ('time', 'content', 'worker', 'tags', 'target_name', 'target_id')),
            'add_schedule_batch': (
                "one task per target in one call (no repeats); with window_start/"
                "window_end it checks entries x duration_minutes fit and rejects up "
                "front with the numbers — then split across dates or ask",
                ('entries', 'content', 'worker', 'tags', 'window_start',
                 'window_end', 'duration_minutes')),
        },
        'properties': {
            'date': {"type": "string", "description": "YYYY-MM-DD (batch: for every entry)."},
            'time': {"type": "string", "description": "HH:MM. Default '09:00'."},
            'content': {"type": "string", "description": "The work (batch: shared text for entries without their own)."},
            'worker': {"type": "string", "description": "Assignee (batch: shared)."},
            'tags': {"type": "string", "description": "Comma-separated. Default: taken from content."},
            'target_name': {"type": "string", "description": "Zone/facility/device the work applies to, e.g. '3-1', '1포장 1-1'."},
            'target_id': {"type": "string", "description": "Instead of target_name: a resolve_target candidate's target_id."},
            'entries': {"type": "array", "description": "One per target; keys: target_name/target_id, time, content?, worker?.", "items": {"type": "object"}},
            'window_start': {"type": "string", "description": "'HH:MM' start of the work window (enables the fit check)."},
            'window_end': {"type": "string", "description": "'HH:MM' end; every entry's time must be at or before it."},
            'duration_minutes': {"type": "integer", "description": "Minutes per entry for the fit check. Default 60."},
        },
    },
    # 공지 쓰기 — 셋 다 승인 필요. 운영 키에는 create_notice 하나만 보여 원래
    # 도구 그대로 나가고(_facade_entry), 서재 모듈을 켠 키가 셋을 한 줄로 받는다.
    'notice': {
        'description': "Notice-board posts. Pick `operation`:",
        'tail': ("Requires human approval; modify and delete also need admin or "
                 "the post's author."),
        'common': (),
        'operations': {
            'create_notice': ("new post", ('title', 'body', 'pinned')),
            'modify_notice': ("change title, body or pinned (omit what stays)",
                              ('notice_id', 'title', 'body', 'pinned')),
            'delete_notice': ("delete a post", ('notice_id',)),
        },
        'properties': {
            'notice_id': {"type": "string", "description": "From list_notices."},
            'title': {"type": "string", "description": "Title."},
            'body': {"type": "string", "description": "Body text."},
            'pinned': {"type": "boolean", "description": "Pin to top (admin only)."},
        },
    },
}


def facade_of(tool_name):
    """이 도구를 operation 으로 품은 묶음 도구 이름, 없으면 None."""
    for name, spec in MCP_FACADES.items():
        if tool_name in spec['operations']:
            return name
    return None


def facade_payload(name, operations=None):
    """묶음 도구의 MCP 정의 — `operations` 에 든 것만 싣는다(None 이면 전부).

    키마다 쓸 수 있는 operation 이 다르므로(묶음·역할) 설명·enum·인자를 그
    부분집합으로 만든다. 고를 수 없는 operation 과 그것만 쓰는 인자는 싣지
    않는다 — 실으면 부르면 거절당할 것을 광고하게 된다. 빈 집합이면 None."""
    spec = MCP_FACADES[name]
    ops = [o for o in spec['operations'] if operations is None or o in operations]
    if not ops:
        return None
    lines, args = [], list(spec['common'])
    for op in ops:
        text, op_args = spec['operations'][op]
        lines.append("%s — %s." % (op, text))
        for a in op_args:
            if a not in args:
                args.append(a)
    props = {'operation': {"type": "string", "enum": ops}}
    for a in args:
        props[a] = spec['properties'][a]
    return {
        "tool_name": name,
        "description": " ".join([spec['description']] + lines + [spec['tail']]),
        "input_schema": {"type": "object", "properties": props,
                         "required": ["operation"] + list(spec['common'])},
    }


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
            "Plots: crop, zone, area, period. Growing only unless include_ended. "
            "Source for open-field crops; greenhouse → get_crop_status. Valves, "
            "stages, capacity → get_plot. Follow `_reading`. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "map_id": {"type": "string", "description": "Map unique_id. Omit for all maps."},
                "zone_id": {"type": "string", "description": "Zone or site unique_id or name — only plots inside it."},
                "include_ended": {"type": "boolean", "description": "Include finished plots (history)."},
                "on": {"type": "string", "description": "As-of date 'YYYY-MM-DD'."},
                "with_sensors": {"type": "boolean", "description": "Include each plot's sensors (not valves)."},
                "query": {"type": "string", "description": "Crop or plot name (part ok)."},
                # 26-09-29 에는 토큰 예산 때문에 숨기고 잘린 응답의 안내문이
                # 알려 주리라 봤다. 실제로는 Sonnet 이 "limit 을 올려 다시 부르라"
                # 는 안내와 스키마를 대조해 **도구가 설명과 다르다** 고 보고하고
                # 나머지 구획을 끝내 못 봤다(2026-10-08). 안내문이 가리키는
                # 인자는 스키마에 있어야 한다(test_truncation_hint_args_are_advertised).
                "limit": {"type": "integer", "description": "Max plots returned (default 10)."},
                "detail": {"type": "boolean"},
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
                "row_spacing_cm": {"type": "number", "description": "Spacing between rows in cm (e.g. 40), for a FLAT layout only. Rows are counted across the plot's SHORT side. Not used when a bed layout (bed_pitch_cm + rows_per_bed) is given."},
                "plant_spacing_cm": {"type": "number", "description": "Spacing between plants within a row in cm (e.g. 15). Plants are counted along the plot's LONG side. Required for any count, in both flat and bed layouts."},
                "edge_margin_cm": {"type": "number", "description": "Extra free margin at every edge, cm (machinery turning strip, bed shoulders, path). Default 0; half a spacing is ALREADY free at each edge, so pass it only for more (e.g. 200). Requires both spacings."},
                "bed_pitch_cm": {"type": "number", "description": "Bed spacing (두둑 간격) in cm, centre to centre, furrow INCLUDED (e.g. 160 for a 120 cm bed + 40 cm furrow). Ask the grower for it as ONE number, not bed and furrow separately. Give it with rows_per_bed to count the layout as planted; without it the count assumes a flat layout and OVERSTATES a bedded one by 20-30%."},
                "rows_per_bed": {"type": "integer", "description": "Rows on ONE bed, e.g. 2 (whole number, 1+; crop-dependent: peppers one, lettuce or cabbage two or three). Give together with bed_pitch_cm."},
                "detail": {"type": "string"},
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
                "parts": {"type": "integer", "description": "Equal pieces (1+), e.g. 'three crops in this zone'. 1 = the whole zone as one plot (still inset by edge_margin_m). Ignored with widths_cm."},
                "strip_width_cm": {"type": "number", "description": "Or make pieces this wide in cm, e.g. 160. Use for bed-by-bed. Give this OR parts (or both together for an exact count at an exact width), never with widths_cm."},
                "widths_cm": {"type": "array", "items": {"type": "number"}, "description": "Each piece's own width in cm, in order, e.g. [200, 500, 300]; overrides parts/strip_width_cm. Too wide: only the LAST piece shrinks (widths_clamped_from_cm); refused if the others alone don't fit."},
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
            "propose_plot_split. Pass exactly the SAME arguments as the proposal"
            " (parts/strip_width_cm/widths_cm/edge_margin_m/orientation/"
            "angle_deg), leaving out what was left out there: the split is "
            "recomputed and must match. Check the piece count first (41 pieces ="
            " 41 plots). One crop over a whole zone is create_plot with "
            "zone_id. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_id": {"type": "string", "description": "The zone or site shape to divide."},
                "subject": {"type": "string", "description": "Subject for every piece."},
                "started_on": {"type": "string", "description": "Start date 'YYYY-MM-DD'."},
                "parts": {"type": "integer"},
                "strip_width_cm": {"type": "number"},
                "widths_cm": {"type": "array", "items": {"type": "number"}},
                "edge_margin_m": {"type": "number", "description": "METERS. Default 0."},
                "orientation": {"type": "string", "enum": ["long", "short"]},
                "angle_deg": {"type": "number"},
                "variety": {"type": "string"},
                "name": {"type": "string", "description": "Base name; pieces are numbered from it, e.g. 'A' becomes 'A 1', 'A 2'."},
                "expected_end_on": {"type": "string", "description": "'YYYY-MM-DD'"},
                "color": {"type": "string", "description": "'#rrggbb'"},
            },
            "required": ["zone_id", "subject", "started_on"],
        },
        "detail": {"input_schema": {
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
        }},
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
                "stages": {"type": "array", "description": "Ordered stages; each item keys: key, name, days, targets?, guidance?. 'days' is LENGTH not cumulative; only the LAST may be blank. Full item shape: get_tool_detail.", "items": {"type": "object"}},
                "kind": {"type": "string", "enum": ["vegetation", "livestock", "facility", "other"], "description": "Default 'vegetation'. Only vegetation has fixed target items; other kinds need target_defs before targets."},
                "variety": {"type": "string", "description": "Cultivar / breed."},
                "notes": {"type": "string", "description": "Free notes."},
                "target_defs": {"type": "array", "description": "Extra target items, only for a value the fixed vocabulary lacks; each item keys: key, label, unit, measurement.", "items": {"type": "object"}},
                "base_temp_c": {"type": "number", "description": "GDD base temperature. Vegetation only."},
                "resource_defs": {"type": "array", "description": "What the subject NEEDS (roles: irrigation/fertigation/other) — never which function does it; the site resolves that.", "items": {"type": "object"}},
                "tab_id": {"type": "string", "description": "Tab on the Programs page."},
            },
            "required": ["name", "subject", "source_note"],
        },
        "detail": {"input_schema": {
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
        }},
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
                "time_range": {"type": "string", "description": "'24h', '7d', or local days 'FROM/TO' (included). Default 24h."},
                "loc_ids": {"type": "array", "items": {"type": "string"}, "description": "Several at once (max 10)."},
                "limit": {"type": "integer"},
            },
        },
    },
    {
        # 화면 연동 P1(2026-10). 규칙을 설명에 싣는 이유: claude.ai 는 서버
        # 안내문을 모델에 주지 않는 것으로 보인다(_lite_note 주석).
        "tool_name": "get_screen",
        "description": (
            "What the user sees in AoT now and on which device: open window, "
            "else visible widgets or tab cards, with values. Call it first "
            "for 'this screen'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "focus": {"type": "string", "description": "Widget/card name, or 'widgets', 'tabs', 'map'."},
            },
        },
    },
    {
        "tool_name": "screen_action",
        "description": (
            "Change the user's open AoT page (notes, map). post: title + markdown to AI inbox, no OK. "
            "read: item=card (none=list), value=range. "
            "Unconfirmed screen: returns confirm_token; resend only it after OK (10 min free)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "screen": {"type": "string", "description": "From get_screen."},
                "action": {"type": "string", "enum": ["navigate", "highlight", "open_widget_settings", "open_map_item", "open_notes", "modal_tab", "map_control", "close_modal", "close_card", "post", "read", "reload"]},
                "page": {"type": "string", "description": "navigate: dashboard|inputs|outputs|functions|devices|plots|map|notes"},
                "dashboard": {"type": "string"},
                "tab": {"type": "string", "description": "Window tab."},
                "widget": {"type": "string", "description": "Widget name/id, or the map."},
                "item": {"type": "string", "description": "Place, plot or device on a map"},
                "kind": {"type": "string", "description": "site|zone|facility|plot|device; labels: input|output|equipment|function."},
                "op": {"type": "string", "enum": ["zoom_in", "zoom_out", "zoom", "rotate", "tilt", "reset_north", "orbit", "fullscreen", "labels", "shapes", "base_layer", "overlay", "time"]},
                "value": {"description": "Zoom/degrees, or true/false."},
                "layer": {"type": "string", "description": "get_screen focus=map."},
                "center": {"type": "boolean"},
                "title": {"type": "string"},
                "message": {"type": "string"},
                "attach": {"description": "post {name, text|b64|ref|url} or list"},
                "confirm_token": {"type": "string"},
            },
        },
    },
    {
        "tool_name": "set_tool_profile",
        "description": (
            "Changes which tools THIS connection's API key lists. 'lite': a few "
            "tools, smallest messages (free AI plans). 'operations': every "
            "day-to-day tool. 'operations' + modules adds setup tools. Takes "
            "effect when the app reconnects or a new chat starts. Requires "
            "human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "profile": {"type": "string", "enum": ["lite", "operations", "configuration"]},
                "modules": {"type": "array", "items": {"type": "string", "enum": list(TOOL_MODULES)}, "description": "With 'operations': setup modules to turn on."},
            },
            "required": ["profile"],
        },
    },
    {
        # 가벼움 묶음의 첫 도구(2026-10-10) — 여러 조회를 서버에서 한 번에 묶는다.
        "tool_name": "get_place_overview",
        "description": (
            "Current state of one place, or the whole farm if place is omitted: "
            "sensor values (min/avg/max), climate control and actuator positions, "
            "plots and stage, weather, alerts. Use it first for 'how is X doing?'. "
            "May open it on the user's screen."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "place": {"type": "string", "description": "Site, zone or facility name or id. Omit for the whole farm."},
                "_show_on_screen": {"type": "string", "description": "'off' = don't open it."},
            },
        },
    },
    {
        "tool_name": "get_spatial_tree",
        "description": (
            "How the farm is divided: every site, zone and facility, with how "
            "many devices each holds (map = one map only). To find a device by "
            "name use search_devices. Follow the reply's `_reading`. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "map": {"type": "string", "description": "Map name or id; omit = all maps."},
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
            "Latest values (detail=true adds period min/max/avg) for the sensors "
            "of MANY zones in one call — for questions across zones ('which plots "
            "are dry'). Follow the reply's `_reading`. Read-only."
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
                "measurement_type": {"type": "string", "description": "Stored measurement name, substring: soil moisture = 'volumetric_water_content', rain = 'precipitation'/'rain', wind = 'speed'/'direction'; 'temperature', 'humidity', 'co2', 'battery_voltage'. With query it intersects."},
                "limit": {"type": "integer"},
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
            "properties": {"limit": {"type": "integer"}},
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
            "for PWM/setpoint/position (0 = closed; off stops a vent or curtain). "
            "PHYSICAL. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Output unique_id or name."},
                "state": {"type": "string", "enum": ["on", "off", "set_value"], "description": "Target state."},
                "value": {"type": "number", "description": "For set_value: PWM duty/position 0-100 %, or setpoint."},
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
                "entries": {"type": "array", "description": "One per target (no repeats); keys: target_name/target_id, time, content?, worker?.", "items": {"type": "object"}},
                "content": {"type": "string", "description": "Shared work text for entries without their own."},
                "worker": {"type": "string", "description": "Shared assignee."},
                "tags": {"type": "string", "description": "Comma-separated, for every entry."},
                "window_start": {"type": "string", "description": "'HH:MM' start of the work window (enables the fit check)."},
                "window_end": {"type": "string", "description": "'HH:MM' end; every entry's time must be at or before it."},
                "duration_minutes": {"type": "integer", "description": "Minutes per entry for the fit check. Default 60."},
            },
            "required": ["date", "entries"],
        },
        "detail": {"input_schema": {
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
        }},
    },
    {
        "tool_name": "search_notes",
        "description": (
            "Reads notes, memos and work records. For notes about a place or "
            "device pass target_name — notes are attached to the entity and may "
            "not mention it, so a keyword search misses them. A site includes its"
            " zones. Read-only. Edit/archive: modify_note."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Place/device the notes are on, e.g. '3-1', '밸브1'."},
                "query": {"type": "string", "description": "Keyword; with target_name filters within."},
                "category": {"type": "string", "description": "e.g. 'schedule'. Omit for all."},
                "limit": {"type": "integer", "description": "Default 10."},
                "target_names": {"type": "array", "items": {"type": "string"}, "description": "Several (max 10)."},
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
                "filename": {"type": "string", "description": "One of that note's 'files'. Omit if only one."},
                "max_dimension": {"type": "integer", "description": "Longest edge in px. Default 1024 (256-2048)."},
            },
            "required": ["note_id"],
        },
    },
    {
        "tool_name": "schedule_device_control",
        "description": (
            "Schedules an output (valve, pump, PWM) to switch or set_value at a "
            "set time. PHYSICAL — registered after approval. Requires human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Output unique_id or name."},
                "scheduled_time": {"type": "string", "description": "ISO 8601 with offset, e.g. '2026-02-27T09:00:00+09:00'."},
                "state": {"type": "string", "enum": ["on", "off", "set_value"], "description": "Target state."},
                "value": {"type": "number", "description": "For set_value (PWM/position %)."},
                "duration_minutes": {"type": "number", "description": "Default 5."},
            },
            "required": ["device_id", "scheduled_time", "state"],
        },
    },
    {
        "tool_name": "get_weather",
        "description": (
            "Current weather for a site or zone from its station; "
            "'weather_source' says which. Follow 'weather_source_warning' / "
            "'weather_device_note' when present. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_name": {"type": "string", "description": "Site or zone."},
                "zone_id": {"type": "string", "description": "Or unique_id."},
                # 도메인 틀의 기간 검사가 이 설명의 FROM/TO 를 본다(`contract`). 나머지 안내는 help 가 한다.
                "time_range": {"type": "string", "description": "24h|FROM/TO"},
                "sensor_type": {"type": "string"},
                "detail": {"type": "boolean"},
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
            "Saves a note now (undated memo; dated work is schedule_add), no "
            "approval. It shows only on the entity it is attached to, so give "
            "target_name. Call the tool — do not just say you will."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "Body text."},
                "name": {"type": "string", "description": "Short title."},
                "target_name": {"type": "string", "description": "Place/device to attach to (e.g. '1포장 1-1'); ONE entity, not its children (resolve_target first). Without it the note shows nowhere."},
                "tags": {"type": "string", "description": "Comma separated."},
                "category": {"type": "string", "description": "Default 'general'."},
                "target_id": {"type": "string", "description": "Instead of target_name."},
                "target_type": {"type": "string", "description": "Type of target_id."},
                "attach": {"type": "array", "items": {"type": "object"}, "description": "[{url, name}] links shown as thumbnails."},
            },
            "required": ["note"],
        },
    },
    {
        "tool_name": "delete_note",
        "description": (
            "Permanently deletes one note and its attached files. Always needs "
            "human approval. To only hide a note use modify_note(archive=true)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "From search_notes or the create/edit response."},
            },
            "required": ["note_id"],
        },
    },
    {
        "tool_name": "modify_note",
        "description": (
            "Edits a note, moves it to another place, or archives it "
            "(archive=false restores); never deletes. Someone else's note "
            "needs human approval."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "From search_notes."},
                "name": {"type": "string"},
                "note": {"type": "string", "description": "New body."},
                "tags": {"type": "string", "description": "Replaces."},
                "archive": {"type": "boolean"},
            },
            "required": ["note_id"],
        },
    },
    {
        "tool_name": "add_target_alias",
        "description": "Saves an alias the user gave a target.",
        "input_schema": {
            "type": "object",
            "properties": {"target_id": {"type": "string"}, "name": {"type": "string"}},
            "required": ["target_id", "name"],
        },
    },
    {
        "tool_name": "delete_target_alias",
        "description": "Deletes an alias.",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "target_id": {"type": "string"}},
            "required": ["name"],
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
                "query": {"type": "string", "description": "Part of the name."},
                "limit": {"type": "integer"},
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
                    "description": "Ordered run plan; same-slot devices run SIMULTANEOUSLY. Each item keys: devices (required), minutes/seconds, group.",
                    "items": {"type": "object"},
                },
                "start": {"type": "string", "description": "When the day's run begins, 'HH:MM' local. Optional — keeps the current start if omitted."},
                "end": {"type": "string", "description": "Window end 'HH:MM'. Optional — defaults to exactly one pass."},
                "period_seconds": {"type": "number", "description": "Seconds between repeats. Optional — defaults to one pass, i.e. it runs once."},
                "repeat": {"type": "boolean", "description": "Keep the existing repeat period instead of running once. Optional."}
            },
            "required": ["function_id", "day", "slots"]
        },
        "detail": {"input_schema": {
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
        }},
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
            "One device's whole picture in one call: kind, location, channels, "
            "outputs, bound place, approval needs. Settings and connection values "
            "only via fields (options, connection, all). Replaces chained lookups. "
            "Missing parts are null with a '*_note'. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "unique_id or name. An ambiguous name returns candidates."},
                "fields": {"type": "array", "items": {"type": "string"}},
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
        "tool_name": "list_gis_inputs",
        "description": "Lists GIS Inputs (map layers/providers: VWorld, Google, OpenWeather). Read-only.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "tool_name": "create_gis_input",
        "description": "Creates a GIS Input (map layer/provider, e.g. gis_vworld). layer_type: a 'gis_*' entry from list_device_types(kind='input'). Created DEACTIVATED; activate_gis_input turns it on. No approval; activating needs one.",
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
                "params": {"type": "object", "description": "{key: value}; keys: get_device_detail fields=[options]."}
            },
            "required": ["layer_id"]
        }
    },
    {
        "tool_name": "activate_gis_input",
        "description": "Turns a GIS Input on or off. Requires human approval.",
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
        "tool_name": "nearest",
        "description": (
            "Ranks things by distance from one reference ('which plots are "
            "closest to the office') in ONE call. "
            "Names or unique_ids. Relay both 'unresolved' and 'ambiguous' — a "
            "shorter list otherwise reads as 'further away'. Centre to centre. "
            "Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reference": {"type": "string", "description": "Name or unique_id to measure from."},
                "candidates": {"type": "array", "items": {"type": "string"}, "description": "Names or unique_ids to rank, closest first. Max 200."},
            },
            "required": ["reference", "candidates"],
        },
    },
    {
        "tool_name": "set_device_location",
        "description": "Places or moves a device (Input/Output) on the map by latitude/longitude. Requires human approval.",
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
        "tool_name": "set_pipe_diameters",
        "description": "Sets main/branch pipe diameters (mm) of a site/zone; drip lines skipped. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "area_name": {"type": "string"},
                "main_mm": {"type": "number"},
                "branch_mm": {"type": "number"},
                "only_empty": {"type": "boolean", "description": "Default true; false overwrites."}
            },
            "required": ["area_name"]
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
    # 설명에 create_function 을 적지 않는다 — 이 도구는 devices 모듈이고
    # create_function 은 automation 모듈이라, devices 만 켠 키에서 목록에 없는
    # 이름을 가리키게 된다(모듈 R6, test_mcp_tool_profiles). create_function 은
    # function_type 을 enum 으로 싣고 있어 이 도구 없이도 종류를 고른다.
    {
        "tool_name": "list_device_types",
        "description": "Lists the valid TYPES for creating an Input/Output/Function. Read-only. Call before creating — never invent a type.",
        "input_schema": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["input", "output", "function"]},
                           "query": {"type": "string", "description": "Part of the type or name."}},
            "required": ["kind"]
        }
    },
    {
        "tool_name": "get_device_type_options",
        "description": "Returns the option schema (id/type/name/default) of a device type. Read-only. Gives the option ids for modify_input/modify_output.",
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
        "description": "Creates a new Input (sensor / data source) of a type; fill options afterward with modify_input. Requires human approval.",
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
        "description": "Updates an Input's name and/or options. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "input_id": {"type": "string"},
                "name": {"type": "string", "description": "Optional."},
                "params": {"type": "object", "description": "{key: value}; keys: get_device_detail fields=[options]."}
            },
            "required": ["input_id"]
        }
    },
    {
        "tool_name": "activate_input",
        "description": "Input on/off.",
        "input_schema": {
            "type": "object",
            "properties": {"input_id": {"type": "string"}, "active": {"type": "boolean"}},
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
        "description": "Creates a new Output (actuator / relay / valve) of a type; fill options afterward with modify_output. Requires human approval.",
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
        "description": "Updates an Output's name and/or options. Requires human approval.",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_id": {"type": "string"},
                "name": {"type": "string", "description": "Optional."},
                "params": {"type": "object", "description": "{key: value}; keys: get_device_detail fields=[options]."}
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
        "description": "Creates an AI pipeline agent bound to an AIEntry. Always created DEACTIVATED, saved without approval. No AI-callable activation tool exists: only a human, in the web UI, makes it live.",
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
        "description": "Updates an AI agent's fields. Requires human approval.",
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
                "attribution": {"type": "string", "description": "Source title and/or URL; without it the note stays unconfirmed."},
                "entity_ref": {"type": "string", "description": "Optional AoT entity unique_id this is about."},
                "source_url": {"type": "string", "description": "The http(s) address it came from, for a reviewer to check."},
                "source_ref": {"type": "string", "description": "The 'source_ref' a lookup here (query_reference_table / query_data_source) returned; marks it checkable."},
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
        "tool_name": "configure_library_source",
        "description": "Create or update a SmartFarmKorea library source and (by default) activate + sync it so its measured farm data enters the AI knowledge layer. Requires human approval (registers a source and fetches external data). Handles all three datasets: smartfarmkorea (시설원예), smartfarmkorea_outdoor (노지), smartfarmkorea_livestock (축산). RECIPE: look up the farm first (records.data_source), then this. Only register a farm whose crop (itemCode) matches what the user asked for.",
        "input_schema": {
            "type": "object",
            "properties": {
                "preset_key": {"type": "string", "enum": ["smartfarmkorea", "smartfarmkorea_outdoor", "smartfarmkorea_livestock"]},
                "operations": {"type": "array", "items": {"type": "string"}, "description": "EXACT operation keys, per-dataset (identity/cropping/env shared) — a wrong key is refused with the valid list, so a good first guess is fine."},
                "params": {"type": "object", "description": "Values the chosen operations need (userId, facilityId, croppingSerlNo, itemCode, measDate, startDate, endDate …)."},
                "source_id": {"type": "string", "description": "Optional — update instead of create."},
                "activate": {"type": "boolean", "description": "Default true."},
                "sync": {"type": "boolean", "description": "Default true."},
                "farm_label": {"type": "string"}, "season_label": {"type": "string"}
            },
            "required": ["operations"]
        },
        "detail": {"input_schema": {
            "type": "object",
            "properties": {
                "preset_key": {"type": "string", "enum": ["smartfarmkorea", "smartfarmkorea_outdoor", "smartfarmkorea_livestock"]},
                "operations": {"type": "array", "items": {"type": "string"}, "description": "EXACT operation keys (not generic words) — a wrong key returns valid_operations to retry with. 시설: growth_strawberry/growth_mum/growth_melon/growth_other, 노지: growth_radish/growth_cabbage/growth_garlic/growth_onion/growth_blueberry, shared: identity/cropping/env."},
                "params": {"type": "object", "description": "Values the chosen operations need (userId, facilityId, croppingSerlNo, itemCode, measDate, startDate, endDate …)."},
                "source_id": {"type": "string", "description": "Optional — update instead of create."},
                "activate": {"type": "boolean", "description": "Default true."},
                "sync": {"type": "boolean", "description": "Default true."},
                "farm_label": {"type": "string"}, "season_label": {"type": "string"}
            },
            "required": ["operations"]
        }},
    },
    {
        "tool_name": "get_address",
        "description": "Reverse-geocodes a zone/site/facility/device (name or unique_id) or lat/lng into an address via a GIS Input that supports it. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "Zone, site, facility or device name."},
                "target_id": {"type": "string", "description": "Instead of target_name."},
                "lat": {"type": "number", "description": "Instead of a name/id."},
                "lng": {"type": "number", "description": "Instead of a name/id."}
            }
        }
    },
    {
        "tool_name": "find_favorites",
        "description": "Shared saved map places. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"}
            }
        }
    },
    {
        "tool_name": "find_location",
        "description": "Coordinates for an address or place name via the GIS Input geocoding search. Several candidates: ask which one. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Address or place name."},
                "provider": {"type": "string", "description": "GIS Input id/name/type."},
                "limit": {"type": "integer"}
            },
            "required": ["query"]
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
                # `detail` 은 한때 토큰 예산 때문에 광고하지 않았다 — 기본 응답의
                # `_omitted` 가 그것을 쓰라고 안내하는데 스키마에 없어, 스키마 밖
                # 인자를 거부하는 클라이언트는 따를 수 없었다(2026-10-09 외부 점검).
                # 설명 없이 타입만 둔다(안내는 `_omitted` 가 한다).
                "detail": {"type": "boolean"},
            },
        },
    },
    {
        "tool_name": "get_weather_forecast",
        "description": "Weather forecast for a place, hourly or daily. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "place": {"type": "string", "description": "Site/zone/facility/device name or id. Omit: place on screen, else farm default."},
                "start": {"type": "string", "description": "Time the user names; map moves there. now, today, tomorrow, day_after [+ ' HH:MM'], YYYY-MM-DDTHH:MM"},
                "hours": {"type": "integer", "description": "Default 24, max 336 (over 72: daily)."},
                "sensor_type": {"type": "string"},
                "detail": {"type": "boolean"},
                "focus": {"type": "string", "description": "max|min|rain_start, or the hour the answer is about (HH:MM or ISO); the map moves there."},
            },
        },
    },
    {
        "tool_name": "get_anomalies",
        "description": (
            "Device CONNECTIVITY check (offline ratio, link drops) and alert "
            "level. Does NOT compare sensor values with limits — for that: "
            "get_control_state (safety_range, strain). Read "
            "'metrics_definitions' before quoting a number. Silent sensors: "
            "get_device_freshness. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "scope_type": {"type": "string", "description": "Default system. farm = one map.", "enum": ["system", "farm", "zone", "facility"]},
                "scope_id": {"type": "string", "description": "Scope id or name. Omit for system."},
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
                # list_plots 의 `limit` 주석과 같은 이유로 광고한다(2026-10-08).
                "limit": {"type": "integer", "description": "Max plots per list (default 10)."},
                "detail": {"type": "boolean"},
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
_SPACE_NON_PLOT_WRITES = frozenset({'delete_geo_shape', 'set_device_location', 'set_pipe_diameters'})


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


#: 웹이 **설정 편집**(`edit_settings`)으로 여는 쓰기 — 공지(routes_notice)와
#: 지식 출처 설정(routes_ai_library). 제어 권한(`edit_controllers`)이 아니다.
#: 승인 여부는 이 분류와 무관하다(레지스트리의 mutating/config_only 가 정한다).
_SETTINGS_EDIT_WRITES = frozenset({'create_notice', 'modify_notice', 'delete_notice',
                                   'configure_library_source'})

#: 자기 연결의 묶음을 바꾸는 쓰기 — 웹도 자기 키는 로그인만 요구한다
#: (routes_mcp_auth). 필요 역할 권한이 없다(승인은 유지). 대상 키는 실행층이
#: 인증된 연결로 덮어쓰므로 남의 키를 바꾸는 길은 MCP 에 없다.
_SELF_SERVICE_WRITES = frozenset({'set_tool_profile'})


def settings_edit_tools() -> frozenset:
    """공지·지식 출처 설정 — 웹과 같은 `edit_settings` 가 필요하다."""
    return frozenset(_SETTINGS_EDIT_WRITES) & write_tools()


def self_service_tools() -> frozenset:
    """필요 역할 권한이 없는 자기 연결 쓰기(로그인한 키 주인이면 된다)."""
    return frozenset(_SELF_SERVICE_WRITES) & write_tools()


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


# @manual ai/overview#tool-drawers
def core_tools() -> frozenset:
    """상시 노출 도구 — 개발 단계의 유효 등급이 곧 base_tier 다."""
    return frozenset(n for n in _BY_NAME if tier_of(n)[1] == 'core')


def never_demote_tools() -> frozenset:
    """호출이 적어도 자동 강등하지 않는 도구."""
    return frozenset(n for n in _BY_NAME if tier_of(n)[2])


# @manual ai/overview#tool-drawers
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


# @manual ai/overview#tool-drawers
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
    """인앱 AI 의 제어 흐름 항목(read_manual·get_detailed_manifest·ask_user) — 도구가
    아니라 인앱 대화가 직접 처리하는 행동이라 도메인 명부에 없다.

    인앱 AI 의 도구는 도메인 명부 하나다(`tool_execution.tools_for_agent`). 예전에는
    여기서 옛 도구 112개의 매니페스트(약 65,000자)를 매 호출 실었다 — 같은 기능에
    두 표면이었다(아키텍처 개선 26-11 5단계에서 걷어냄)."""
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


# ---------------------------------------------------------------------------
# 상세 기구(2026-09-29) — "가벼운 스키마 + 풍부한 오류".
#
# `virtual_tools()`(위)가 매 tools/list 에 싣는 것은 **가벼운** description·
# input_schema 뿐이다. 몇몇 큰 도구는 그 옆에 선택 필드 `detail` 을 들고 있다 —
# 중첩 item 의 전체 모양, 결정 규칙(예: propose_plot_split 의 orientation·
# widths_cm), RECIPE 류 긴 안내처럼 **고르기 전에는 필요 없고 인자를 채울 때만
# 필요한** 내용이다. `detail` 은 항상 원래 있던 내용을 옮긴 것이고
# (test_schema_detail_is_lossless), 지운 것이 아니다.
#
# 이 값은 세 자리에서만 나간다 — tools/list(virtual_tools) 는 절대 아니다:
#   1. get_tool_detail — 도구 하나의 완전한 정의를 요청받았을 때(tool_execution).
#   2. 인자 문제로 거절할 때 그 도구의 오류 본문(`schema`/`hint`) — 처음부터
#      상세를 실어 보내는 대신, 실수했을 때만 보여준다(tool_execution).
#
# `detail` 은 아래 모양이다(둘 다 선택):
#   {"input_schema": {...}}   # 같은 속성 이름·required, 더 깊은 설명/중첩 item
#   {"description": "..."}    # 더 긴 안내(RECIPE·결정 규칙)
def tool_detail(name: str) -> Optional[Dict[str, Any]]:
    """`name` 의 상세 동반물, 없으면 None. 항상 사본을 준다(SSOT 보호)."""
    for payload in _MCP_TOOL_PAYLOADS:
        if payload.get("tool_name") == name:
            detail = payload.get("detail")
            return copy.deepcopy(detail) if detail else None
    return None
