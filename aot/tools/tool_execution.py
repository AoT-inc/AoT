# coding=utf-8
"""도구 실행층 — 승인 게이트·감사·응답 캡·도구 목록.

**이 모듈이 본질이고, MCP 서버는 이것을 프로토콜로 감싸는 어댑터다.**

예전에는 이 코드가 `aot_mcp_server.py` 안에 있었고, 내부 AI 는 그것을 쓰려고
`MCPBridge` 로 **subprocess 를 띄워 자기 자신에게 JSON-RPC 를 보냈다.** 같은
프로세스 안에 도구 구현이 있는데도 그랬다. 대가가 셋이었다:

  - 메모리: subprocess 가 Flask 앱을 통째로 다시 로드해 약 400MB.
    앱 컨테이너가 1G 에서 OOM 나 3072M 로 올린 원인이 이것이다.
  - 상태 분기: 두 프로세스가 각자 코드를 읽어 서로 다른 버전으로 돈다
    (2026-08-21 실측: 상주 HTTP 는 도구 102개, stdio 는 32개).
  - 조용한 고장: 내부 AI 는 같은 도구를 `system_tools` 매니페스트로도 볼 수
    있어서, MCP 쪽이 죽어도 그쪽으로 우회해 **아무도 모른다.** 실제로
    `MCPBridge` 초기화가 늘 실패해 `mcp_tools: 0`(operate_device 포함 전 도구
    없음)인 채로 굴러가고 있었다.

이제 호출자는 둘이고 실행층은 하나다:

    내부 AI ─────────────┐
                        ├──→ 이 모듈 (게이트 + 감사 + 도구)
    외부 AI ─→ MCP 서버 ─┘

**게이트를 우회하는 경로를 새로 만들지 말 것.** 여기를 지나야 승인·감사·응답
캡이 걸린다. MCP 를 거치지 않는다는 이유로 게이트를 건너뛰면, 그 경로만 조용히
무방비가 된다(`human_device_control` 이 그렇게 예외가 됐다 — 그때는 승인 토큰이
MCP 경계를 못 넘어서였고, 이 모듈을 직접 부르면 그 제약 자체가 없다).
"""
import hashlib
import json
import logging
import os
import socket
import time

logger = logging.getLogger(__name__)

# 응답에 실려 나가는 인스턴스 식별자. 같은 사용자가 여러 AoT 의 MCP 를 동시에
# 붙였을 때 어느 쪽이 답했는지 구분한다.
SERVER_HOST = socket.gethostname()


def _server_instructions(profile=None):
    """initialize 응답의 result.instructions.

    도구 설명이 아니라 여기 한 곳에 적어 두면 모든 클라이언트/세션에 일관되게
    반영된다. **서랍 안내를 여기 싣는 것이 중요하다** — tools/list 만 본 LLM 은
    거기 없는 기능을 "이 시스템은 못 한다" 로 결론짓는다. 그 실패는 에러가
    아니라 조용한 오답이라 로그에도 안 남는다. 서랍 이름은 DRAWERS 에서 만들어
    목록이 코드와 어긋나지 않게 한다.

    profile: 이 연결의 도구 묶음(`mcp_auth.tool_profile_of(role)`). 주면 묶음
    안내 한 단락을 더하고, 서랍 목록도 그 묶음에 도구가 있는 서랍만 싣는다.
    표준 호스트는 목록에 없는 도구를 모델에게 주지 않으므로, 묶음 밖 거절
    메시지가 아니라 **여기와 get_system_brief** 가 묶음을 알리는 자리다.
    """
    base = (
        "When reporting results to the user, never surface raw unique_id/note_id "
        "UUIDs. Most lookup tools here return both a human-readable name (zone, "
        "crop, device, etc.) and its unique_id — refer to the entity by name "
        "instead. Only include the raw id if the user explicitly asks for it."
        "\n\nTIME — do not infer the current time from the data. Every response "
        "carries `now` = {farm_local, tz}: that, and nothing else in the payload, "
        "is what time it is. Timestamps in the data are past events, and a field "
        "like `evaluated_at` or `last_seen` is when something was measured, not "
        "now. Read every timestamp by its own offset (they are ISO 8601 and are "
        "not all in the same zone — sensor values come back in their device's "
        "local time). Devices can sit in different timezones from the farm "
        "default, so before any day/night, scheduling or 'is it due yet' "
        "reasoning about a particular place, call get_local_time%s "
        "for that location." % (" (system drawer)" if _tiering_enabled() else "")
    )
    profile = _effective_profile(profile)
    note = _profile_note(profile)
    if note:
        base += "\n\n" + note
    try:
        from aot.tools.tool_registry import DRAWERS, profile_tools, tools_in_drawer
    except Exception:
        return base
    if not _tiering_enabled():
        return base
    shown = DRAWERS.items()
    if profile is not None:
        allowed = profile_tools(profile)
        shown = [(n, d) for n, d in shown if tools_in_drawer(n, available=allowed)]
    drawers = "; ".join("%s (%s)" % (name, desc) for name, desc in shown)
    return base + (
        "\n\nIMPORTANT — tools/list is NOT the full set of what this server can do. "
        "Only a few everyday tools are listed; the rest live in drawers, grouped by "
        "purpose: " + drawers + ". Call open_drawer with no argument to see every "
        "drawer and the names of the tools inside, open_drawer({drawer: '<name>'}) "
        "for their full schemas, and use_tool({tool_name, arguments}) to run one. "
        "Before you tell the user something is not possible here, or settle for a "
        "listed tool that only roughly fits, open the drawer that matches the job. "
        "Drawer tools are ordinary tools: approval and permissions are unchanged."
    )





# ── 도구 묶음(tool profile) ─────────────────────────────────────────────────
# 외부 키마다 보여 줄 도구의 범위(tool_registry._MCP_PROFILE). None = 제한 없음
# (인앱 AI). 묶음 밖 호출을 거절하는 것은 **외부 전송만**이다 — 인앱 AI 가 같은
# 실행층을 지나도 막지 않는다.
_PROFILE_ENFORCED_TRANSPORTS = frozenset({"mcp_stdio", "mcp_http", "rest"})

#: 묶음을 바꾸는 곳 — 화면 경로와 같은 말을 쓴다(영문 화면 기준).
_PROFILE_SWITCH_PLACE = "Settings > Users > API keys"
#: 누가 바꾸는가 — 키 폐기와 같은 문턱(사용자 편집 권한)이다. 키 소유자가
#: 아니다: 소유자라도 그 권한이 없으면 못 바꾼다.
_PROFILE_SWITCH_WHO = (
    "an administrator (user-edit permission) can switch this key to the "
    "configuration set in " + _PROFILE_SWITCH_PLACE)


def _effective_profile(profile):
    """스위치(AOT_MCP_TOOL_PROFILES=0)가 꺼져 있으면 묶음을 무시한다."""
    if profile is None:
        return None
    from aot.tools.mcp_auth import tool_profiles_enabled
    from aot.tools.tool_registry import normalize_tool_profile
    if not tool_profiles_enabled():
        return None
    return normalize_tool_profile(profile)


def _profile_note(profile):
    """이 연결의 묶음을 모델에게 알리는 한 단락. 제한이 없으면 빈 문자열.

    **도구 이름을 싣지 않는다** — 목록에 없는 이름을 가리키는 안내는 모델이
    주입으로 오인했다. 설정 묶음이 더하는 일을 분야로만 말한다."""
    from aot.tools.tool_registry import TOOL_PROFILE_CONFIGURATION
    if profile is None:
        return ""
    if profile == TOOL_PROFILE_CONFIGURATION:
        return ("TOOL PROFILE — this API key uses the 'operations + "
                "configuration' tool profile: day-to-day tools plus setup tools.")
    return (
        "TOOL PROFILE — this API key uses the 'operations' tool profile: tools for "
        "day-to-day work (reading devices, sensors, weather, schedules, notes and "
        "plots; controlling devices and functions; adjusting function options and "
        "sequence run times; scheduling; recording notes, notices, advice and "
        "plot-stage events). Setup work is in the 'configuration' profile and is "
        "not offered on this key: adding or editing device definitions, creating "
        "or deleting automations and sequence steps, creating or editing plots and "
        "programs, map placement, dashboards and tabs, AI settings, and "
        "archive or library-source management. If the user asks for that, do not "
        "say this system cannot do it — tell them " + _PROFILE_SWITCH_WHO +
        ", and to reconnect afterwards so the tool list refreshes. Only for setup "
        "work or a 'tool_profile' refusal — never for other refusals.")


def _profile_refusal(tool_name, profile, transport, role=None):
    """묶음 밖 호출의 거절 본문. 통과면 None.

    외부 전송(stdio·HTTP·REST)에서만 판정한다. 서랍 기구는 묶음과 무관하다.
    이 거절은 보안 경계가 아니다(경계는 역할·스코프·게이트) — 목록과 실행이
    어긋나지 않게 하는 일관성이다. 승인 큐에 들어가지 않는다."""
    from aot.tools import tool_registry as registry

    if transport not in _PROFILE_ENFORCED_TRANSPORTS:
        return None
    profile = _effective_profile(profile)
    if profile is None or registry.tool_in_profile(tool_name, profile):
        return None
    if registry.mcp_profile_of(tool_name) is None \
            and not registry.is_declared_tool(tool_name):
        # 모르는 이름은 실행층이 "Unknown tool" 로 답한다 — 묶음 탓으로 돌리지 않는다.
        return None
    return _profile_refusal_body(tool_name, profile, role)


def _profile_refusal_body(tool_name, profile, role=None):
    """묶음 밖 도구에 대한 거절 본문(전송·통과 판정 없이 본문만).

    호출 거절과 get_tool_detail 의 묶음 밖 조회가 같은 본문을 쓴다 — 같은
    사실을 자리마다 다르게 말하면 모델이 어느 쪽을 믿을지 모른다(서랍·승인
    요청은 같은 모양으로 _empty_drawer_refusal·_approval_refusal 이 만든다).

    바꾸는 안내는 **바꿔서 풀리는 경우에만** 붙인다. 이 키의 역할·스코프가
    어차피 막는 도구(읽기 전용 키의 쓰기 도구 등)는 묶음을 바꿔도 못 쓰므로,
    바꾸라고 하면 헛걸음을 시킨다."""
    from aot.tools import tool_registry as registry
    from aot.tools.mcp_safety_gate import classify_permission

    subject = "'%s'" % tool_name
    if registry.is_retired_from_mcp(tool_name):
        message = (
            "%s is not offered to API keys. Use the listed tools instead — "
            "operate_device to control a device, get_device_list or "
            "search_devices to find one. Nothing was changed." % subject)
    elif tool_name in _hidden_tools(role):
        message = (
            "%s is not in this API key's tool profile (%s), and this key's "
            "permissions do not allow it either, so switching the profile would "
            "not help. Nothing was changed." % (subject, profile))
    else:
        message = (
            "%s is not in this API key's tool profile (%s). It belongs to the "
            "configuration profile. %s Nothing was changed."
            % (subject, profile, _switch_sentence()))
    body = {"status": "refused", "reason_code": "tool_profile",
            "tool_profile": profile, "message": message}
    # 쓰기 도구는 실행층이 performed:false 와 해석 규칙을 함께 붙인다
    # (mcp_safety_gate.annotate_write_outcome). 읽기 도구에는 여기서 적는다.
    if classify_permission(tool_name) != "write":
        body["performed"] = False
    return body


def _switch_sentence():
    """거절 메시지의 "누가 어디서 바꾸는가" 한 문장."""
    return ("%s%s; reconnect afterwards so the tool list refreshes."
            % (_PROFILE_SWITCH_WHO[0].upper(), _PROFILE_SWITCH_WHO[1:]))


def _profile_enforced(profile, transport):
    """이 연결에 묶음을 적용하는가 → 적용할 묶음, 아니면 None."""
    if transport not in _PROFILE_ENFORCED_TRANSPORTS:
        return None
    return _effective_profile(profile)


#: 승인 대기 목록에서 묶음 밖 항목의 도구 이름 대신 싣는 말. 목록에 없는 도구
#: 이름을 응답이 가리키면 모델이 그 이름을 부르려 든다(R6, 서버 안내문 주석).
_OUT_OF_PROFILE_LABEL = "a tool outside this key's tool profile"


def _mask_out_of_profile_pending(result, profile):
    """list_pending_confirmations 응답에서 묶음 밖 항목의 도구 이름을 가린다.

    항목은 그대로 싣는다 — 이 키로도 거절은 할 수 있고, 무엇이 기다리는지는
    사람이 알아야 한다. 가리는 것은 도구 이름(과 도구 고유의 인자 틀)이고,
    대신 중립 표시와 분야(서랍 이름)를 싣는다. 제목(title)은 사람이 읽는
    헤드라인이라 남긴다."""
    from aot.tools import tool_registry as registry
    if not isinstance(result, dict) or not isinstance(result.get("pending"), list):
        return result
    masked = 0
    for item in result["pending"]:
        if not isinstance(item, dict):
            continue
        name = item.get("tool_name")
        if not name or registry.tool_in_profile(name, profile):
            continue
        item.pop("tool_name", None)
        item.pop("params", None)
        item["tool"] = _OUT_OF_PROFILE_LABEL
        try:
            item["domain"] = registry.tier_of(name)[0]
        except Exception:                                   # noqa: BLE001
            item["domain"] = None
        item["can_approve_with_this_key"] = False
        masked += 1
    if masked:
        result["out_of_profile_note"] = (
            "%d pending request(s) are for tools outside this API key's tool "
            "profile (%s). You may reject them here if the user asks; approving "
            "them needs the web review page or a key on the configuration set — "
            "%s." % (masked, profile, _PROFILE_SWITCH_WHO))
    return result


def _approval_refusal(tool_name, profile, role=None):
    """묶음 밖 도구의 승인 요청을 이 키로 승인하려 할 때의 거절 본문.

    _profile_refusal_body 와 같은 모양이되 도구 이름을 싣지 않는다(목록에서도
    가렸다). 바꾸는 안내는 바꿔서 풀리는 경우에만 붙인다."""
    from aot.tools import tool_registry as registry
    head = ("This request is for %s (%s), so it cannot be approved with this "
            "key. You can still reject it here, or approve it on the web review "
            "page." % (_OUT_OF_PROFILE_LABEL, profile))
    if registry.is_retired_from_mcp(tool_name) or tool_name in _hidden_tools(role):
        message = head + " Nothing was changed."
    else:
        message = "%s %s Nothing was changed." % (head, _switch_sentence())
    return {"status": "refused", "reason_code": "tool_profile",
            "tool_profile": profile, "message": message}


def _confirmation_tool(cid):
    """승인 요청 행의 도구 이름. 없으면 None."""
    try:
        from aot.databases.models import MCPConfirmation
        row = MCPConfirmation.query.filter_by(unique_id=cid).first()
        return row.tool_name if row is not None else None
    except Exception:                                       # noqa: BLE001
        logger.exception("[AoTMCP] 승인 요청 조회 실패")
        return None


#: knowledge_search 응답에 싣는 한 줄 — 찾아낸 것을 보관하라는 안내.
#: 도구 설명이 아니라 응답에 두는 이유: 설명은 운영 키에도 같은 글이 나가는데
#: knowledge_shelve 는 설정 묶음이라, 설명이 그 이름을 부르면 목록에 없는 도구를
#: 가리키게 된다. 응답은 부른 연결마다 다르게 만들 수 있다.
KNOWLEDGE_SHELVE_READING = (
    "If you research this outside this system, save a short summary with "
    "knowledge_shelve (with its source) so the next search finds it — it is "
    "stored as an unconfirmed note.")


def _attach_shelve_hint(result, profile, role):
    """보관할 수 있는 연결에만 knowledge_search 응답에 안내를 붙인다.

    profile 은 이 연결에 적용되는 묶음(None = 제한 없음: 인앱·서비스 계정).
    묶음에 knowledge_shelve 가 있고(설정 묶음, 또는 제한 없음) 역할이 기록
    쓰기를 허락할 때(웹과 같은 edit_settings)만 붙인다."""
    from aot.tools import tool_registry as registry
    from aot.tools.mcp_auth import role_can_record
    if not isinstance(result, dict):
        return result
    if profile is not None and not registry.tool_in_profile(
            "knowledge_shelve", profile):
        return result
    if not role_can_record(role):
        return result
    prev = result.get("_reading")
    if isinstance(prev, str):
        prev = [prev]
    prev = list(prev or [])
    if KNOWLEDGE_SHELVE_READING not in prev:
        prev.append(KNOWLEDGE_SHELVE_READING)
    result["_reading"] = prev
    return result


# ── Native tool names handled by AoTNativeToolEngine ──────────────────────────
_NATIVE_TOOLS = {"list_available_devices", "get_sensor_reading", "set_output_state"}

# 승인 큐에 직접 응답하는 도구 — 일반 가상도구/네이티브도구 디스패치가 아니라
# mcp_safety_gate.approve/reject를 곧장 호출한다(아래 _respond_to_confirmation).
_CONFIRMATION_RESPONSE_TOOL = "respond_to_confirmation"

# tool_registry.TOOLS 에는 handler=None(특수 디스패치, set_output_state 등 네이티브
# 브릿지 도구와 동일 취급)으로 등록돼 있어 virtual_tools()/_MCP_TOOL_PAYLOADS 경로로는
# 못 내보낸다(그 경로는 handler 필수). tools/list 에는 여기서 직접 얹는다.
_EXTRA_TOOLS = [
    {
        "name": _CONFIRMATION_RESPONSE_TOOL,
        "description": (
            "Approves or rejects ONE OR MORE pending confirmations (from a prior "
            "'pending_approval' response or from list_pending_confirmations) over MCP — "
            "this is the primary approval path; the web review page is only an "
            "alternative for whoever is at a browser. Call this ONLY after the user has "
            "explicitly told you, in THIS conversation, to approve or reject THOSE "
            "SPECIFIC confirmation_id(s) — never call it on your own judgment, and "
            "never infer approval from the user's ORIGINAL task request alone (e.g. "
            "'create these schedules' is the task; it is NOT, by itself, 'yes, execute "
            "confirmation_id X' — that needs its own explicit go-ahead, even if it "
            "comes right after you show the pending confirmation). This applies just as "
            "much to a batch as to a single one: 'clean up whatever is pending' is NOT "
            "authorization to approve/reject an unnamed set — only a set the user "
            "actually named or that you listed and the user confirmed applies here). If "
            "you are unsure whether the user actually approved, ask them plainly before "
            "calling this. Approving executes nothing by itself — retry the original "
            "write tool call with the same arguments plus '_confirmation_id' afterward. "
            "Requires an Admin/Editor-role key."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "confirmation_id": {"type": "string", "description": "The confirmation_id from the pending_approval response. Use for a single confirmation."},
                "confirmation_ids": {"type": "array", "items": {"type": "string"}, "description": "Multiple confirmation_ids to approve/reject with the same decision in one call, instead of one confirmation_id per call. Use only the exact id set the user named."},
                "decision": {"type": "string", "enum": ["approve", "reject"], "description": "What the user explicitly told you to do, in this conversation, about these specific id(s)."},
            },
            "required": ["decision"],
        },
    },
    {
        "name": "open_drawer",
        "description": (
            "Opens a drawer and returns the FULL definitions of the tools inside it. "
            "Only a handful of everyday tools are listed in tools/list; the rest of "
            "this server's capabilities live in drawers, grouped by what they are for "
            "(devices, measurements, functions, schedules, records, spatial/plots, "
            "device definitions, system). The drawer index — every drawer with the "
            "names of the tools in it — is returned by calling this with no argument, "
            "and it is also in the server instructions. "
            "IMPORTANT: before you conclude that this system cannot do something, or "
            "settle for a listed tool that only roughly fits, open the drawer whose "
            "name matches the job and look. Most of what this server can do is NOT in "
            "tools/list. Tools obtained this way are executed with use_tool. Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "drawer": {"type": "string", "description": "Drawer name. Omit to get the index of all drawers and the tool names in each."},
            },
        },
    },
    {
        "name": "get_tool_detail",
        "description": (
            "Returns the full description and argument schema for ONE tool by name — "
            "including tools that are not in tools/list. Use it when the drawer index "
            "shows a tool name that sounds right and you only need its arguments, "
            "instead of opening the whole drawer. Read-only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "Exact tool name, e.g. one from the drawer index."},
            },
            "required": ["tool_name"],
        },
    },
    {
        "name": "use_tool",
        "description": (
            "Executes any tool on this server BY NAME, including the ones that are not "
            "in tools/list because they live in a drawer. This is how a drawer tool is "
            "actually run — open_drawer/get_tool_detail only show you its definition. "
            "Pass the tool's own arguments as `arguments`. Approval, role checks and "
            "auditing are identical to calling the tool directly: a write tool invoked "
            "this way still needs human approval and still returns pending_approval."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool_name": {"type": "string", "description": "Name of the tool to run (from the drawer index, open_drawer or get_tool_detail)."},
                "arguments": {"type": "object", "description": "That tool's arguments, exactly as its own schema defines them."},
            },
            "required": ["tool_name"],
        },
    },
]


# ── 도구 노출 등급(서랍) ──────────────────────────────────────────────────────
# 카탈로그 전량을 tools/list 에 실으면 그것만으로 약 22,000 토큰이다(2026-08-21
# 실측: 로컬 88KB/102개, koat 84KB). 대화가 시작되기도 전에 나가는 고정비이고,
# 그 위에 도구 응답이 얹힌다. tool_registry 의 등급 표(core / 서랍)를 이 표면에도
# 적용해 상시 노출을 core + 아래 면제 도구로 줄이고, 나머지는 서랍에서 꺼내 쓴다.
#
# **면제 4종이 서랍 구조의 전부다.** open_drawer 로 열고, get_tool_detail 로
# 스키마를 보고, use_tool 로 실행한다. use_tool 이 없으면 서랍은 장식이다 — MCP
# 호스트는 tools/list 에 실린 도구만 모델에게 함수로 주므로, 서랍을 열어 정의를
# 받아도 **그것을 호출할 수단이 없다.** 내부 AI 매니페스트는 프롬프트 텍스트라
# 이 제약이 없어서, 같은 서랍이 두 표면에서 다르게 동작한다 — MCP 쪽에만
# 실행 도구가 필요한 이유가 이것이다.
_DRAWER_MACHINERY = frozenset({"open_drawer", "get_tool_detail", "use_tool"})
_TIER_EXEMPT_TOOLS = frozenset({_CONFIRMATION_RESPONSE_TOOL}) | _DRAWER_MACHINERY


def _tiering_enabled():
    """서랍 적용 여부. **기본은 꺼짐이다**(2026-09-24, 아래 (4)).

    이 스위치는 두 번 뒤집혔다. 그 과정이 곧 근거다.

      (1) 처음엔 켬. 근거는 추정이었다 — "use_tool 이 있으니 기능은 안 사라진다".
      (2) 5건 실측 후 끔. core 가 5개(노출 7)일 때 외부 클라이언트가 왕복 6.6회,
          턴한도 초과 4/5, 정상 응답 0 이었다. `get_weather_forecast` 가 서랍에
          멀쩡히 있는데 열어보지도 않고 "알려드릴 수 없습니다" 라고 답했다.
      (3) 20건 실측 후 다시 켬. **문제는 서랍이 아니라 core 크기였다.**

    (3)의 측정(Gemini 2.5 Flash, DB 표본 20건, 서랍 필요 12건):

        노출 도구   크기      왕복   답변 성공   서랍 열기
        9 (core 5)  11,017자  5.5    8/20        13회
        32 (core 31) 31,426자 3.6    15/20        3회
        115 (끔)    96,136자  2.9    14/20        0회

    core 31 은 전량 노출과 **동등한 성능을 크기 33%로** 냈다(15 대 14 는 20건에서
    차이가 아니다). 반면 core 5 는 서랍을 **더 많이 열고도**(13회 대 3회) 더 많이
    실패했다 — 여는 능력이 부족한 게 아니라, 열어야 하는 상황 자체가 실패 요인이다.

    ⚠ **여기서 배울 것: core 를 좁혀도 LLM 은 서랍을 열지 않는다.** 좁히면 서랍을
    열게 만드는 것이 아니라 요청을 실패시킨다. core 의 목적은 서랍을 열게 만드는
    압력이 아니라 **서랍을 안 열어도 되게 하는 것**이다. 그래서 core 를 다시
    좁히는 변경은 이 스위치를 끄는 것과 같은 무게로 다뤄야 한다
    (`test_core_stays_bounded` 가 하한 20개를 고정한다).

    되돌릴 때는 AOT_MCP_TOOL_TIERING=0. 왕복이 2.9→3.6 으로 24% 늘어나는 것은
    실재하는 비용이라, 토큰보다 지연이 중요한 배포에서는 끄는 것이 맞다.
    측정은 모델 하나로만 했다 — 다른 모델은 서랍을 다르게 다룰 수 있다.

      (4) 2026-09-24 다시 끔. 서랍이 필요한 질문에서 서랍을 거치는 쪽이 여러
          배 느렸다(모델 두 종 반복 측정). 대신 API 키별 도구 묶음
          (tool_registry._MCP_PROFILE)이 목록 크기를 정하고, 운영 묶음은
          설명·스키마를 줄여 예전 core 표면과 비슷한 크기로 맞췄다
          (test_mcp_tool_profiles 의 크기 상한). 서랍 기구(open_drawer·
          get_tool_detail·use_tool)는 코드와 스위치가 남아 있다 —
          AOT_MCP_TOOL_TIERING=1 이면 묶음 **안에서** 예전처럼 동작한다.
          끈 상태에서는 목록에 싣지 않는다(실행은 된다 — 목록을 캐시한
          호스트가 부르더라도 깨지지 않게).

    인앱 AI 가 보는 내장 MCP 목록은 이 스위치를 따르지 않는다 —
    `tools_for_agent` 가 AOT_AI_BUILTIN_MCP_TIERING(기본 켬)으로 따로 고정한다.
    """
    return _env_flag_on("AOT_MCP_TOOL_TIERING")


#: 켬으로 읽는 스위치 값(대소문자 무시). 예전 기본(켬) 시절에는 "0" 만 끔이라
#: `true` 도 켬으로 동작했다 — 기본을 뒤집으며 "1" 만 받으면 그 설정이 조용히
#: 꺼진다.
_FLAG_ON_VALUES = frozenset({"1", "true", "yes", "on"})


def _env_flag_on(name, default=""):
    return os.environ.get(name, default).strip().lower() in _FLAG_ON_VALUES


def _builtin_tiering_enabled():
    """인앱 AI 의 내장 MCP 목록(`tools_for_agent`)에 서랍을 쓰는가. 기본 켬.

    외부 MCP 의 기본값(AOT_MCP_TOOL_TIERING)을 끄면서 인앱 목록까지 34개에서
    전량으로 바뀌지 않게 따로 둔다 — 인앱 AI 의 표면은 인앱 평가 세트로 따로
    재고 정한다(설계 §3.7). 되돌리기: AOT_AI_BUILTIN_MCP_TIERING=0."""
    return os.environ.get("AOT_AI_BUILTIN_MCP_TIERING", "1") != "0"


def _drawer_index(app, role=None, profile=None):
    """서랍 목록 — 이 표면이 실제로 가진 도구만.

    원천은 _get_all_tools 다. tool_registry 의 매니페스트로 인덱스를 만들면
    네이티브 도구가 빠지고 카탈로그에 없는 이름이 섞여, 열어도 안 나오는
    이름을 광고하게 된다. 묶음(profile)도 같은 이유로 함께 건다 — 서랍이
    묶음 밖 도구를 내주면 목록에서 숨긴 의미가 없다.
    """
    from aot.tools.tool_registry import drawer_index
    names = _drawer_contents(app, role=role, profile=profile)
    return [d for d in drawer_index(available=names) if d["tools"]]


def _drawer_contents(app, role=None, profile=None):
    """서랍에 담길 수 있는 도구 이름 — 전체 표면에서 **상시 노출을 뺀 것**.

    면제 도구를 빼지 않으면 이미 tools/list 에 있는 것이 서랍에도 보인다.
    그러면 LLM 은 손에 든 도구를 쓰려고 서랍을 한 번 더 여는데, 그 왕복이
    정확히 서랍이 없애려던 비용이다(respond_to_confirmation 이 실제로 그렇게
    보였다 — core 가 아니라 면제라서 등급 검사만으로는 안 걸러진다).
    """
    return _exclude_always_listed(
        {t["name"] for t in _get_all_tools(app, role=role, tiered=False,
                                           profile=profile)})


def _exclude_always_listed(names):
    """서랍에 담길 수 있는 이름 = 전체 − 상시 노출. (순수 함수 — 앱이 필요 없다.)

    앱 없이 부를 수 있게 떼어 둔다. 이 규칙이 깨지는 것은 조용한 실패라
    검사로 고정해야 하는데, `_get_all_tools` 는 DB 를 읽으므로 그대로는
    검사에서 부를 수 없다.
    """
    return {n for n in names if n not in _TIER_EXEMPT_TOOLS}


def _open_drawer(app, arguments, role=None, profile=None):
    """서랍 하나를 열어 그 안 도구들의 완전한 정의를 돌려준다.

    인자 없이 부르면 서랍 목록만 준다 — 서버 안내문이 "인자 없이 부르면 모든
    서랍을 본다" 고 하므로 오류가 아니다(예전에는 'drawer is required' 오류를
    함께 실어 안내문과 어긋났고, 호출 품질 기록에서도 실패로 잡혔다).
    모르는 이름이면 **오류로 끝내지 않고 목록을 함께 준다** — "없다"로 끝내면
    LLM 이 포기하는데, 목록을 주면 다시 고른다.
    """
    from aot.tools.tool_registry import DRAWERS, tools_in_drawer

    drawer = (arguments or {}).get("drawer")
    index = _drawer_index(app, role=role, profile=profile)
    if not drawer:
        return {"drawers": index}
    if drawer not in DRAWERS:
        return {
            "error": "unknown drawer: %s" % drawer,
            "drawers": index,
        }

    every = {t["name"]: t for t in _get_all_tools(app, role=role, tiered=False,
                                                  profile=profile)}
    names = tools_in_drawer(drawer, available=_drawer_contents(
        app, role=role, profile=profile))
    tools = [every[n] for n in names]
    if not tools:
        refused = _empty_drawer_refusal(app, drawer, role, profile)
        if refused is not None:
            return refused
    return {
        "drawer": drawer,
        "description": DRAWERS[drawer],
        "count": len(tools),
        "tools": tools,
        "how_to_call": ("These tools are not in tools/list. Call one by passing its "
                        "name and arguments to use_tool, e.g. "
                        "use_tool({tool_name: '<name>', arguments: {...}})."),
    }


def _empty_drawer_refusal(app, drawer, role, profile):
    """묶음 때문에 빈 서랍이면 묶음 거절 본문, 아니면 None.

    빈 목록만 돌려주면 모델은 "이 시스템엔 없다" 로 읽는다(2026-09-24 검토:
    운영 키로 definition 서랍을 열면 조용히 0건이었다). 설정 묶음이었다면 도구가
    있었을 때만 묶음 탓이라고 말한다 — 역할 때문에 빈 서랍은 그대로 둔다."""
    from aot.tools import tool_registry as registry
    from aot.tools.tool_registry import tools_in_drawer
    profile = _effective_profile(profile)
    if profile is None or profile == registry.TOOL_PROFILE_CONFIGURATION:
        return None
    wider = tools_in_drawer(drawer, available=_drawer_contents(
        app, role=role, profile=registry.TOOL_PROFILE_CONFIGURATION))
    if not wider:
        return None
    # wider 는 역할 숨김을 거친 뒤라, 바꾸면 이 역할로 쓸 도구가 실제로 있다.
    return {"status": "refused", "reason_code": "tool_profile",
            "tool_profile": profile, "performed": False,
            "message": ("The '%s' drawer has no tools in this API key's tool "
                        "profile (%s). Its tools belong to the configuration "
                        "profile. %s" % (drawer, profile, _switch_sentence())),
            "drawers": _drawer_index(app, role=role, profile=profile)}


def _get_tool_detail(app, arguments, role=None, profile=None):
    """도구 하나의 완전한 정의. 서랍 인덱스가 준 이름을 확인하는 자리.

    묶음 밖 도구면 호출했을 때와 같은 거절 본문을 준다 — "Unknown tool" 로
    답하면 모델은 없는 기능으로 읽고, 부르면 다른 말(묶음 거절)이 나와
    두 응답이 서로 어긋난다."""
    from aot.tools import tool_registry as registry
    name = (arguments or {}).get("tool_name")
    if not name:
        return {"error": "tool_name is required"}
    name = str(name).strip()
    for t in _get_all_tools(app, role=role, tiered=False, profile=profile):
        if t["name"] == name:
            return {"tool": t, "how_to_call": (
                "Call it via use_tool({tool_name: '%s', arguments: {...}}) "
                "unless it is already listed in tools/list." % name)}
    eff = _effective_profile(profile)
    if eff is not None and registry.mcp_profile_of(name) is not None \
            and not registry.tool_in_profile(name, eff):
        return _profile_refusal_body(name, eff, role)
    return {"error": "Unknown tool: %s" % name,
            "drawers": _drawer_index(app, role=role, profile=profile)}


# =============================================================================
# Tool registry
# =============================================================================

def _hidden_tools(role):
    """이 호출자에게 광고하지 않을 도구 — 게이트가 거부할 것과 같은 기준이다.

    예전에는 approval_required_tools() 로 숨겨서, 승인이 면제된 쓰기(config_only·
    기록 쓰기)가 읽기 전용 키의 목록에 그대로 보였다 — 부르면 거부되는 도구를
    광고한 셈이다. 이제 mcp_safety_gate.gate() 의 판정과 같은 세 갈래로 숨긴다:

      - 제어·설정 쓰기(아래 셋 제외)        → role_can_write
      - 기록 쓰기(노트·지식, record_write)  → role_can_record (웹과 같은 edit_settings)
      - 지도 편집(도형 삭제·장치 배치)       → role_can_record (웹과 같은 edit_settings)
      - 작기 운영(구획·프로그램 등)         → role_can_edit_plots (웹과 같은 edit_plots)
      - 조언 제출(advisory_write)           → role_can_advise
      - respond_to_confirmation             → 하나라도 결정할 수 있는 역할
        (gate.role_can_decide_any — 항목별 판정은 승인 경로가 한다)
    """
    from aot.tools import mcp_safety_gate as gate
    from aot.tools.mcp_auth import (role_can_advise, role_can_edit_plots,
                                    role_can_record, role_can_write)

    record = gate.record_write_tools()
    plot = gate.plot_write_tools()
    map_edit = gate.map_edit_tools()
    hidden = set()
    if not role_can_write(role):
        # respond_to_confirmation 은 레지스트리에 쓰기로 올라 있지만 판정은
        # 아래 한 줄이 한다(작기 운영만 맡은 역할도 자기 항목은 결정한다).
        hidden |= (gate.write_tools() - record - plot - map_edit
                   - {_CONFIRMATION_RESPONSE_TOOL})
    if not gate.role_can_decide_any(role):
        hidden.add(_CONFIRMATION_RESPONSE_TOOL)
    if not role_can_record(role):
        hidden |= record | map_edit
    if not role_can_edit_plots(role):
        hidden |= plot
    if not role_can_advise(role):
        hidden |= gate.advisory_write_tools()
    return frozenset(hidden)


def _get_all_tools(app, role=None, tiered=None, profile=None):
    """Return merged list of VIRTUAL_TOOLS + AoTNativeToolEngine tools.

    Priority: VIRTUAL_TOOLS first (richer descriptions), then native tools
    not already present by name.

    `role` is whatever mcp_auth.authenticate_http/authenticate_stdio resolved
    (a Role row, or None for unauthenticated). Tools classified mutating/physical
    in tool_registry are left out of the list for callers without write access —
    including the approval-exempt ones (config_only, record_write): a read-only
    key must not be advertised a tool the gate will refuse. This is advisory (it just shapes what
    tools/list advertises); the actual enforcement is mcp_safety_gate.gate()'s own
    role check, so hiding a tool here is a UX nicety, not the security boundary.

    `tiered` selects whether the drawer split applies (None = follow
    _tiering_enabled()). Pass False to get the COMPLETE surface — that is what
    the drawer machinery itself reads, so that what tools/list advertises and
    what a drawer can hand out are always derived from the same list. Role
    filtering still applies in both cases; a read-only key must not be able to
    discover write tools through a drawer either.

    `profile` is the key's tool profile (tool_registry._MCP_PROFILE) —
    'operations' or 'configuration'. None means unrestricted (the in-app AI).
    Only tools in the profile are listed; the drawer machinery follows the
    drawer switch, not the profile. Order: role hiding → profile → drawer split
    (all three are intersections, so the order does not change the result).
    """
    from aot.tools.tool_registry import tier_of, tool_in_profile

    hidden = _hidden_tools(role)
    if tiered is None:
        tiered = _tiering_enabled()
    profile = _effective_profile(profile)

    def _in_drawer(name):
        if not tool_in_profile(name, profile):
            return True          # 묶음 밖 — 목록에도 서랍에도 없다
        return (tiered
                and name not in _TIER_EXEMPT_TOOLS
                and tier_of(name)[1] != 'core')

    tools = []

    # 1. VIRTUAL_TOOLS — owned by the tool layer itself (aot/tools/virtual_tools.py,
    #    derived from tool_registry.virtual_tools()). mcp_aot.py re-exports the same
    #    value for its own callers; reading it from here directly means this module
    #    never has to import aot.ai (tools-no-ai guard).
    try:
        from aot.tools.virtual_tools import VIRTUAL_TOOLS
        for vt in VIRTUAL_TOOLS:
            if vt["tool_name"] in hidden or _in_drawer(vt["tool_name"]):
                continue
            tools.append({
                "name": vt["tool_name"],
                "description": vt["description"],
                "inputSchema": vt.get("input_schema", {"type": "object", "properties": {}}),
            })
    except Exception as exc:
        logger.warning(f"[AoTMCP] Could not load VIRTUAL_TOOLS: {exc}")

    # 2. AoTNativeToolEngine tools (deduplicated)
    try:
        with app.app_context():
            from aot.tools.aot_native_tool_engine import AoTNativeToolEngine
            native_tools = AoTNativeToolEngine.get_tools()
            existing = {t["name"] for t in tools}
            for nt in native_tools:
                if nt["name"] in hidden or _in_drawer(nt["name"]):
                    continue
                if nt["name"] not in existing:
                    tools.append({
                        "name": nt["name"],
                        "description": nt.get("description", ""),
                        "inputSchema": nt.get("inputSchema", {"type": "object", "properties": {}}),
                    })
    except Exception as exc:
        logger.warning(f"[AoTMCP] Could not load NativeToolEngine tools: {exc}")

    # 3. Extra tools that bypass the normal handler-based dispatch (see _EXTRA_TOOLS)
    existing = {t["name"] for t in tools}
    for et in _EXTRA_TOOLS:
        if et["name"] in hidden or et["name"] in existing \
                or not tool_in_profile(et["name"], profile):
            continue
        # 서랍 기구는 서랍을 켰을 때만 목록에 싣는다. 끈 목록에 두면 모델이
        # "목록이 전부가 아니다" 로 읽고 서랍을 뒤지는 왕복을 만든다.
        # tiered=False 로 부르는 서랍 내부 조회는 어차피 이 셋을 걸러 낸다.
        if et["name"] in _DRAWER_MACHINERY and not tiered:
            continue
        tools.append(dict(et))

    return tools


# ── 응답 크기 상한 ────────────────────────────────────────────────────────────
# MCP 클라이언트는 도구 응답에 저마다 상한을 갖는다. 넘으면 호스트가 잘라내거나
# 통째로 버리는데, **서버는 성공으로 알고 넘어간다** — 실패가 응답 내용으로
# 오지 않고 클라이언트 쪽에서 일어나므로 여기서는 아무 것도 안 보인다.
#
# 2026-08-21 실측: 로컬 get_system_brief 가 89,623자로 상한을 넘어 호출이 실패했다
# (구획 30건이 49.6KB, 공간 계층 41노드가 25.4KB). 도구별 limit 인자는 있었지만
# 전역 상한이 없어, 데이터가 늘면 응답이 그대로 따라 커진다. 그래서 stdio/HTTP 가
# 모두 지나는 이 단일 지점에서 한 번만 재고 줄인다(call_state 를 찍는 자리와 같다).
#
# **자를 때는 문자열이 아니라 구조를 줄인다.** JSON 을 문자로 자르면 파싱조차
# 안 되는 조각이 되어 LLM 이 무엇을 받았는지도 모른다. 대신 가장 큰 리스트의
# 항목 수를 줄이고 형제 키로 "N건 중 M건" 을 남긴다 — 남은 응답이 유효한 JSON
# 이고, 잘렸다는 사실과 좁혀 다시 부를 근거가 함께 간다.
# 2026-08-25 재발: 캡이 19,163토큰으로 재고 20,000 아래라 통과시킨 응답(56,209자)을
# 호스트가 그대로 거부했다. 상한 25,000 에 견줘 20,000 은 여유가 1.25배뿐인데,
# 아래 추정기의 오차가 그보다 컸다 — **여유가 오차보다 작으면 캡은 없는 것과 같다.**
# 15,000 으로 낮춰 1.67배를 둔다. 추정기를 함께 고쳤으므로 이중 안전장치다.
_MAX_RESPONSE_TOKENS = int(os.environ.get("AOT_MCP_MAX_RESPONSE_TOKENS", "15000"))

#: 도구가 응답에 실어 보내는 캡 우선순위 힌트의 키. `_cap_result` 가 읽고
#: **응답에서 떼어낸다** — 클라이언트가 볼 내용이 아니다.
CAP_PRIORITY_KEY = _CAP_PRIORITY_KEY = "_cap_priority"


def _farm_now():
    """모든 응답에 실리는 "지금" — 농장 기준 현지시각과 그 IANA 시간대.

    **외부 AI 에게는 시계가 없다.** 인앱 AI 는 컨텍스트에 현재 시각이 주입되지만
    MCP 로 붙은 AI 는 대개 날짜까지만 알고, 그래서 응답 안에서 시각처럼 보이는
    값을 "지금" 의 대용으로 집는다. 2026-09-16 실제 사고가 그랬다: 브리핑의
    `evaluated_at`(UTC 05:10) 을 현재 시각으로 읽고 "지금은 새벽, 곧 05:30 관수"
    라고 답했는데 실제로는 한낮 14:10 이었다.

    그래서 기준선을 **도구마다가 아니라 여기 한 곳에서** 준다. 여기는 stdio /
    HTTP 양쪽이 반드시 지나는 단일 지점이라, 서랍 안에 있든 없든 모든 도구가
    같은 값을 달고 나간다. 장치별 tz 는 장치마다 다를 수 있으므로 이 값은
    **농장 기본 시간대**임을 키 이름(`farm_local`)으로 분명히 한다 — 특정 위치의
    현지시각이 필요하면 `get_local_time` 이 답한다.

    실패해도 응답을 깨서는 안 된다(시계 하나 때문에 도구 결과를 잃는 것이 훨씬
    나쁘다). 해석이 안 되면 UTC 로라도 반드시 무언가를 싣는다.
    """
    try:
        from aot.utils.device_tz import resolve_location_tz
        from aot.utils.timekit import utc_now
        tz = resolve_location_tz(None)
        local = utc_now().astimezone(tz)
        return {"farm_local": local.isoformat(), "tz": str(tz)}
    except Exception:                                       # noqa: BLE001
        from datetime import datetime, timezone as _tz
        return {"farm_local": datetime.now(_tz.utc).isoformat(), "tz": "UTC"}


# ASCII 계열 몇 글자를 1토큰으로 셀 것인가. 영어 산문의 통념은 4지만 **여기서
# 재는 것은 JSON 이다** — 중괄호·따옴표·콜론·이스케이프가 촘촘해 같은 글자 수라도
# 토큰이 더 나온다. 추정이 틀릴 때는 반드시 큰 쪽으로 틀려야 한다: 작게 잡으면
# 캡이 통과시킨 응답을 호스트가 버리는데, 그 실패는 서버에 안 보인다.
#
# 처음엔 3을 골랐다(2026-08-21). 거부된 응답(89,672자 / CJK 937자)이 4자
# 기준으로는 23,120토큰이라 상한 25,000 아래로 보였고 — 즉 위험한 쪽으로
# 빗나갔고 — 3자 기준으로는 30,515토큰이 되어 거부된 사실과 맞았기 때문이다.
# **그러나 그 관측은 "실제 > 25,000" 이라는 한쪽 부등식일 뿐이다**: 3.58 이하
# 어떤 값을 넣어도 똑같이 들어맞으므로, 3 이 충분한지는 그때 검증되지 않았다.
#
# 2026-08-25 그 미검증분이 재발로 드러났다. 56,209자 응답을 3자 기준으로
# 19,163토큰이라 재어 통과시켰으나 호스트가 거부했다 — 실제가 25,000 을
# 넘었다는 뜻이니 참값은 문자당 2.25 미만, 3 은 최소 1.3배 과소평가였다.
# 그 응답은 20.5%가 UUID(262건)·ISO 날짜·장수점 실수 같은 무작위 식별자였는데,
# 무작위 hex 는 토큰당 약 2자로 쪼개진다. 산문이 아니라 **식별자가 응답의
# 밀도를 정한다**. 그래서 2 로 내린다.
_CHARS_PER_TOKEN_ASCII = 2


def _estimate_tokens(text):
    """대략적인 토큰 수.

    바이트/4 는 한국어에서 크게 빗나간다(한글은 UTF-8 3바이트인데 대략 1토큰).
    CJK 계열은 글자당 1토큰, 나머지는 위 상수로 센다 — 정확한 수가 필요한 것이
    아니라 **상한을 넘겼는지** 만 알면 되고, 이 근사는 큰 쪽으로 어긋난다.
    """
    cjk = 0
    for ch in text:
        if ord(ch) > 0x2E7F:
            cjk += 1
    return cjk + (len(text) - cjk) // _CHARS_PER_TOKEN_ASCII


def _list_slots(obj, out, path=""):
    """dict 안에 들어 있는 리스트를 모두 모은다 — (부모dict, 키, 경로, 리스트).

    부모가 dict 인 것만 모으는 이유는 잘랐다는 안내를 **형제 키**로 남기기
    위해서다. 리스트 안의 리스트는 그 자리에 안내를 넣을 데가 없다.

    `_` 로 시작하는 키(`_reading` 같은 해석 규칙)는 자르지 않는다 — 응답의
    내용이 아니라 "이 응답을 어떻게 말하나" 이고, 잘리면 거부·미확인 응답이
    완료로 읽힌다. 짧게 유지하는 것은 그 규칙을 싣는 쪽의 몫이다.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if (isinstance(v, list) and len(v) > 1 and not k.endswith("_truncated")
                    and not str(k).startswith("_")):
                out.append((obj, k, (path + "." + k).lstrip("."), v))
            _list_slots(v, out, (path + "." + k).lstrip("."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _list_slots(v, out, "%s[%d]" % (path, i))


def _str_slots(obj, out, path=""):
    """dict 안에 들어 있는 긴 문자열 — (부모dict, 키, 경로, 값). 리스트 슬롯과
    같은 이유로 부모가 dict 인 것만 모은다."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, str) and len(v) > 500 and not k.endswith("_truncated"):
                out.append((obj, k, (path + "." + k).lstrip("."), v))
            elif isinstance(v, (dict, list)):
                _str_slots(v, out, (path + "." + k).lstrip("."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _str_slots(v, out, "%s[%d]" % (path, i))


def _heaviest_column(lst):
    """목록 항목들이 공유하는 키 중 **가장 무거운 컨테이너 열** → (키, 토큰).

    떨어뜨릴 후보를 컨테이너(dict/list) 값으로 한정한다. 무거운 것은 늘 중첩
    구조이고(단계 일정·타임라인·자식 노드·제어 사이클 요약), 스칼라는 짧은
    데다 그 항목이 **무엇인지** 말하는 이름·식별자·날짜다. 스칼라까지 손대면
    남은 행이 무엇인지 알 수 없어져, 행을 자른 것과 다를 바가 없어진다.

    긴 문자열 하나가 대부분인 항목(문서·매뉴얼)은 여기 걸리지 않는다 —
    컨테이너가 없어 None 이 나가고, 그 부류는 뒤쪽 문자열 절삭이 맡는다.
    """
    if len(lst) < 2 or not all(isinstance(it, dict) for it in lst):
        return None
    weights = {}
    for item in lst:
        for k, v in item.items():
            if isinstance(v, (dict, list)):
                weights[k] = weights.get(k, 0) + _estimate_tokens(
                    json.dumps(v, ensure_ascii=False))
    if not weights:
        return None
    k = max(weights, key=lambda x: weights[x])
    return k, weights[k]


def _thin_lists(result, target, priority=None):
    """상한을 넘긴 응답에서 목록의 **열**부터 줄인다 → {경로: [뺀 키…]}.

    행을 자르면 남는 것은 "몇 건 중 몇 건" 이다. 실측(2026-08-26, 로컬
    get_system_brief): 21,485 토큰을 캡에 태우자 공간 계층이 **루트 47개 중
    1개**로 잘렸다 — 그 응답으로는 농장이 몇 개 대지로 나뉘는지조차 답할 수
    없다. 같은 목록을 열로 줄이면 47개가 다 남고 각자의 이름·종류를 지킨다.
    목록에서 나오는 질문은 대개 "무엇이 몇 개 있나" 라서, 잃는 쪽을 고른다면
    행이 아니라 열이다.

    **응답 전체를 놓고 고른다.** 목록 하나에 초과분 전체를 떠넘기면(행 자르기
    가 그렇게 한다) 어느 목록도 열만으로는 예산에 못 들어와 전부 행 자르기로
    떨어진다 — 실제로 그렇게 만들어 보고 나서야 알았다. 여러 목록이 초과분을
    나눠 지면 셋 다 전 건을 지킬 수 있다.

    열을 다 빼도 상한 아래로 못 내려가면 남은 몫은 호출부의 행 자르기가
    맡는다. 그때 그 목록은 이미 얇아져 있으므로, 같은 상한 안에 **더 많은
    행**이 남는다.

    ## `priority` — 크기만으로 고르면 요청한 것이 먼저 사라진다

    무게로만 고르면 **호출자가 달라고 한 것**이 가장 크다는 이유로 먼저
    잘린다. 실측(2026-09-05): 일지를 하루로 좁혀 부르는데도 `buckets.env`
    (그 하루의 측정값 — 부른 이유 그 자체)가 빠지고, 날짜와 무관하게 늘 실리는
    `stage_summaries.target_drift` 가 남았다.

    그래서 도구가 자기 응답의 순서를 말할 수 있게 한다:

        {'drop_first': [('stage_summaries', 'target_drift'), …],
         'keep_last':  [('buckets', 'env'), …],
         'narrow_with': "Call again with date_from/date_to …"}

    `drop_first` 는 무게와 무관하게 **먼저** 빼고, `keep_last` 는 다른 후보가
    하나도 없을 때만 건드린다. 힌트를 주지 않는 도구는 예전 그대로 무게로
    고른다 — 규칙을 캡 쪽 표에 두면 도구가 늘 때마다 두 곳이 갈라진다.

    `narrow_with` 는 이 함수가 아니라 호출부(`_cap_result`)가 쓴다 — 잘렸을 때
    안내 문장에 이어 붙는다. 같은 딕셔너리에 둔 이유는 **둘 다 "도구가 자기
    응답에 대해 아는 것"** 이고, 키를 나누면 도구가 두 개를 관리하게 되기
    때문이다.
    """
    omitted = {}
    for _ in range(24):
        total = _estimate_tokens(json.dumps(result, ensure_ascii=False))
        if total <= target:
            break
        slots = []
        _list_slots(result, slots)

        drop_first = list((priority or {}).get('drop_first') or [])
        keep_last = {tuple(x) for x in ((priority or {}).get('keep_last') or [])}

        # 1) 도구가 "이것부터 빼라" 고 한 것 — 무게를 보지 않는다.
        #
        # `_heaviest_column` 과 달리 **컨테이너로 한정하지 않는다.** 그 제한은
        # "무엇인지 말하는 이름·식별자를 지킨다" 는 뜻인데, 여기서는 도구가
        # 자기 응답을 알고 지목한 것이므로 긴 산문(`stages.guidance`) 같은
        # 문자열 열도 뺄 수 있다. 자동 선택에는 그 제한이 그대로 남는다.
        pick = None
        for want_path, want_col in drop_first:
            for parent, key, path, lst in slots:
                if path != want_path:
                    continue
                if not any(isinstance(it, dict) and want_col in it for it in lst):
                    continue      # 이미 빠졌다
                pick = (parent, key, path, lst, want_col)
                break
            if pick:
                break

        # 2) 없으면 예전대로 가장 무거운 열. 단 `keep_last` 는 미뤄 둔다.
        if pick is None:
            # `keep_last` 로 지목된 열은 후보에서 아예 뺀다(위 3 참고).
            best = None
            for parent, key, path, lst in slots:
                col = _heaviest_column(lst)
                if not col:
                    continue
                cand = (col[1], parent, key, path, lst, col[0])
                if (path, col[0]) in keep_last:
                    continue
                if best is None or col[1] > best[0]:
                    best = cand
            # 3) 미뤄 둔 것밖에 남지 않았으면 **여기서 멈춘다.** 열은 통째로
            #    빠지므로, 조금 모자란 것을 메우려고 지켜야 할 열을 뽑으면
            #    과잉 절삭이 된다 — 실측: 340 토큰이 모자란데 5,682 토큰짜리
            #    `env` 를 통째로 뺐다(측정값 없는 일지가 나갔다).
            #
            #    남은 몫은 호출부의 **행 자르기**가 맡는다. "3건 중 2건" 이지만
            #    측정값이 살아 있는 편이, 3건 모두 있으나 측정값이 없는 것보다
            #    쓸모 있다.
            if best is None:
                break
            _, parent, key, path, lst, col_key = best
            pick = (parent, key, path, lst, col_key)

        parent, key, path, lst, col_key = pick
        for item in lst:
            item.pop(col_key, None)
        keys = omitted.setdefault(path, {"keys": [], "count": len(lst)})["keys"]
        keys.append(col_key)
        # 안내는 **누적**해서 다시 쓴다. 마지막에 뺀 것만 적으면 앞서 빠진
        # 필드는 "원래 없던 값" 으로 읽힌다.
        parent[key + "_fields_omitted"] = (
            "all %d entries are here, but these fields were dropped from each "
            "to fit the client's size limit: %s. They exist — a field missing "
            "here says nothing about the entry. Ask for a single entry (or a "
            "narrower scope) to see them." % (len(lst), ", ".join(keys)))
    return omitted


def _cap_result(result, tool_name, max_tokens=None, stats=None):
    """응답을 클라이언트 상한 아래로 줄인다. 이미 작으면 그대로 돌려준다.

    result 를 제자리에서 고친다 — 감사 로그에 남기는 결과 요약(status·
    reason_code)은 이 앞에서 이미 떼어 두었으므로 여기서 복사할 이유가 없고,
    큰 응답을 복사하면 그 순간 메모리를 두 배로 쓴다.

    stats: dict 를 넘기면 **캡 전** 추정 토큰 수를 `stats['original']` 에 담아
    돌려준다(호출 품질 기록용). 이미 재는 값을 받아 가는 것뿐이라 추정을 한 번
    더 돌리지 않는다. 캡이 꺼져 있거나(0) 결과가 dict 가 아니면 비워 둔다.
    """
    # `or` 로 쓰면 0(=끄기)이 falsy 라 기본값으로 되살아난다 — 끄는 수단이
    # 조용히 사라진다.
    if max_tokens is None:
        max_tokens = _MAX_RESPONSE_TOKENS
    if not isinstance(result, dict):
        return result

    # 힌트는 캡을 위한 지시이지 응답의 내용이 아니다 — **항상** 떼어낸다.
    # 캡이 꺼져 있거나(0) 응답이 작아 자를 필요가 없을 때도 마찬가지다.
    priority = result.pop(_CAP_PRIORITY_KEY, None)
    # 여러 대상 응답(`share_across`)은 대상마다 자기 힌트를 실을 수 있다 —
    # 그것도 떼어 두었다가 그 대상을 줄일 때 쓴다.
    share_key = (priority or {}).get("share_across")
    shared = result.get(share_key) if share_key else None
    item_priorities = []
    if isinstance(shared, list):
        item_priorities = [it.pop(_CAP_PRIORITY_KEY, None)
                           if isinstance(it, dict) else None for it in shared]
    else:
        shared = None
    if max_tokens <= 0:
        return result

    text = json.dumps(result, ensure_ascii=False)
    total = _estimate_tokens(text)
    if stats is not None:
        stats["original"] = total
    if total <= max_tokens:
        return result

    original = total
    # 잘랐다는 안내(_truncated + 슬롯별 형제 키)도 응답에 실린다. 목표를 상한에
    # 딱 맞추면 그 안내를 붙이는 순간 다시 넘을 수 있으므로 자리를 비워 둔다.
    target = max(1, max_tokens - 400)
    dropped = []

    # 여러 대상 응답 — 대상 목록을 행으로 자르면 **대상이 통째로** 빠진다
    # ("3곳을 물었는데 2곳만 답한" 응답). 그래서 먼저 대상마다 몫을 정해 그
    # 안의 목록부터 줄인다. 작은 대상이 남긴 몫은 큰 대상에게 넘긴다. 대상
    # 안의 잘림 표시(`*_truncated`·`*_fields_omitted`)는 그 자리에 남고, 요약은
    # 아래 `_truncated` 로 모은다. 그래도 넘으면 예전 경로가 이어 받는다.
    if shared:
        sizes = [_estimate_tokens(json.dumps(it, ensure_ascii=False))
                 for it in shared]
        budget = max(0, target - (total - sum(sizes)))
        alloc = [0] * len(shared)
        left = len(shared)
        for i in sorted(range(len(shared)), key=lambda j: sizes[j]):
            alloc[i] = min(sizes[i], budget // left)
            budget -= alloc[i]
            left -= 1
        for i, it in enumerate(shared):
            if not isinstance(it, dict) or sizes[i] <= alloc[i]:
                continue
            if item_priorities[i]:
                it[_CAP_PRIORITY_KEY] = item_priorities[i]
            # 대상 하나를 캡에 태운다(목표 = 몫). 대상 안의 요약은 위로 올린다.
            _cap_result(it, tool_name, max_tokens=max(200, alloc[i]) + 400)
            inner = it.pop("_truncated", None) or {}
            for d in inner.get("lists_trimmed") or []:
                d = dict(d)
                d["path"] = "%s[%d].%s" % (share_key, i, d.get("path", ""))
                dropped.append(d)
        total = _estimate_tokens(json.dumps(result, ensure_ascii=False))

    # 열을 먼저 줄인다. 여기서 상한 아래로 내려가면 행은 하나도 안 잘리고,
    # 못 내려가더라도 목록이 얇아진 만큼 아래 행 자르기가 더 많이 남긴다.
    for path, info in _thin_lists(result, target, priority).items():
        # 열만 줄인 목록은 **전 건이 남아 있다** — kept 와 total 을 같이 적어
        # 진단에서 "몇 건 중 몇 건" 과 한눈에 구분되게 한다.
        dropped.append({"path": path, "kept": info["count"],
                        "total": info["count"],
                        "fields_dropped": info["keys"]})
    total = _estimate_tokens(json.dumps(result, ensure_ascii=False))

    for _ in range(24):
        # 들어오자마자 확인한다. 예전에는 이 검사가 **루프 끝**에만 있었다 —
        # 진입 시점이 늘 초과 상태였기 때문이다. 이제 열 자르기가 앞서 돌면서
        # 이미 상한 아래로 내려놓을 수 있고, 그때 이 검사가 없으면 자를 필요가
        # 없는 목록에서 행이 한 건 잘려 나간다.
        if total <= target:
            break
        slots = []
        _list_slots(result, slots)
        if not slots:
            break
        parent, key, path, lst = max(
            slots, key=lambda sl: len(json.dumps(sl[3], ensure_ascii=False)))
        lst_tokens = _estimate_tokens(json.dumps(lst, ensure_ascii=False))
        excess = total - target

        # 항목을 앞에서부터 누적해 예산 안에 들어가는 개수를 센다.
        # 평균 항목 크기로 나누면 안 된다 — 실제 목록은 크기 편차가 크고(공간
        # 계층은 첫 노드 하나가 나머지 40개를 합친 것보다 크다), 평균으로 셈하면
        # 한 번에 두어 개씩만 줄어 반복 상한에 걸린 채 여전히 큰 응답이 나간다.
        budget = max(0, lst_tokens - excess)

        acc = 0
        keep = 0
        for item in lst:
            item_tokens = _estimate_tokens(json.dumps(item, ensure_ascii=False))
            if keep >= 1 and acc + item_tokens > budget:
                break
            acc += item_tokens
            keep += 1
        keep = max(1, min(keep, len(lst) - 1))

        # 같은 목록을 두 번 자르게 되더라도 **처음 개수**를 유지한다. 잘린
        # 길이를 total 로 다시 쓰면 "36건 중 34건" 처럼 원래 규모가 사라진다.
        prev = next((d for d in dropped if d["path"] == path), None)
        original_len = (prev or {}).get("total", len(lst))
        parent[key] = lst[:keep]
        parent[key + "_truncated"] = (
            "showing first %d of %d — the response exceeded the client's size limit. "
            "Re-run with a narrower scope (a filter, a limit, or a single target) "
            "to see the rest." % (keep, original_len))
        dropped = [d for d in dropped if d["path"] != path]
        entry = {"path": path, "kept": keep, "total": original_len}
        # 이 목록을 앞서 열로도 줄였다면 그 사실을 잃지 않는다 — 진단에서
        # "왜 이 항목에 이 필드가 없나" 의 답이 거기 있다.
        if prev and prev.get("fields_dropped"):
            entry["fields_dropped"] = prev["fields_dropped"]
        dropped.append(entry)

        text = json.dumps(result, ensure_ascii=False)
        total = _estimate_tokens(text)
        if total <= target:
            break

    # 리스트로 줄일 수 없는 응답 — 긴 본문 하나가 대부분인 경우(문서, 매뉴얼,
    # 로그 덩어리)가 그렇다. 그때는 가장 긴 문자열을 자른다. 여기서 포기하면
    # 캡이 있으나 마나 한 응답 부류가 생기고, 하필 그 부류가 가장 크다.
    if total > target:
        for _ in range(8):
            slots = []
            _str_slots(result, slots)
            if not slots:
                break
            parent, key, path, val = max(slots, key=lambda sl: len(sl[3]))
            excess_chars = (total - target) * _CHARS_PER_TOKEN_ASCII
            # 여유 300자. 딱 맞춰 자르면 바로 뒤에 붙는 안내문이 그만큼을 도로
            # 채워, 매번 수십 자씩만 줄면서 반복 상한까지 진동한다(실측).
            keep = max(200, len(val) - excess_chars - 300)
            if keep >= len(val):
                break
            original_chars = next((d["total_chars"] for d in dropped
                                   if d.get("path") == path and "total_chars" in d),
                                  len(val))
            parent[key] = val[:keep] + " …[truncated]"
            parent[key + "_truncated"] = (
                "showing the first %d of %d characters — the response exceeded the "
                "client's size limit." % (keep, original_chars))
            dropped = [d for d in dropped if d.get("path") != path]
            dropped.append({"path": path, "kept_chars": keep,
                            "total_chars": original_chars})
            total = _estimate_tokens(json.dumps(result, ensure_ascii=False))
            if total <= target:
                break

    if dropped:
        # 무엇을 잃었는지에 따라 말이 달라야 한다. 열만 줄인 응답은 **목록이
        # 온전하다** — 거기에 "INCOMPLETE, 좁혀서 다시 부르라" 고 하면 모델은
        # 없는 항목을 찾아 같은 조회를 되풀이하고, 그 재조회는 같은 상한에
        # 걸려 또 같은 답을 받는다. 반대로 행이나 본문이 잘렸을 때 이 경고를
        # 빼면 모델이 일부를 전부로 읽는다 — 그쪽이 훨씬 위험하므로 판정이
        # 애매하면 경고를 남기는 쪽으로 기운다.
        rows_cut = any(d["kept"] != d["total"] for d in dropped if "kept" in d)
        text_cut = any("kept_chars" in d for d in dropped)
        if rows_cut or text_cut:
            advice = ("This result is INCOMPLETE. Do not describe it as the full "
                      "picture — narrow the query and call again for the rest.")
        else:
            advice = ("Every list here is COMPLETE — no entries were dropped. "
                      "Only some FIELDS were removed from each entry to fit the "
                      "size limit (see the '*_fields_omitted' notes for which). "
                      "Do not re-query looking for missing entries; ask for a "
                      "single entry if you need the dropped fields.")
        # ── 어떻게 좁히는지는 **도구만 안다** ──────────────────────────
        # 위 문장은 "narrow the query" 까지밖에 말하지 못한다. 무엇으로
        # 좁히는지(어떤 인자가 있는지)는 도구마다 다르고, 여기서는 알 수
        # 없다. 그래서 도구가 `_cap_priority.narrow_with` 로 한 줄을 실어
        # 보내면 그것을 이어 붙인다 — 없으면 예전 그대로다.
        #
        # 실측(2026-09-04)에서 실제로 아팠던 자리다: 일지를 통째로 부르면
        # 측정값이 잘리는데, 안내는 "좁혀서 다시 부르라" 고만 해서 모델이
        # **같은 조회를 반복**했다. `date_from`/`granularity` 가 있다는 것을
        # 말해 주면 두 번째 호출이 달라진다.
        narrow = (priority or {}).get("narrow_with")
        if rows_cut or text_cut:
            if isinstance(narrow, str) and narrow.strip():
                advice = advice + " " + narrow.strip()
        result["_truncated"] = {
            "reason": "response exceeded the MCP response size limit",
            "estimated_tokens_before": original,
            "estimated_tokens_after": total,
            "limit": max_tokens,
            "lists_trimmed": dropped,
            "advice": advice,
        }
    return result


def _execute_tool(app, tool_name, arguments, agent_id="unknown", role=None,
                  elicit_fn=None, scope_user_uuid=None, transport=None,
                  session_key=None, via_drawer=False, tool_profile=None):
    """Execute a named tool and return MCP-format content list.

    Every call — read or write, executed or refused — is recorded in
    mcp_audit_log with the calling agent's identity and its stated reason, so a
    multi-AI setup (main AoT AI / external AI / subordinate node AI) can be told
    apart after the fact. Write tools do not execute until a human approves them
    (see aot/tools/mcp_safety_gate.py); the gate returns the response body
    to hand back instead.

    elicit_fn: optional callable(tool_name, briefing_message, arguments) -> True
        (human approved) / False (declined) / None (elicitation unavailable or
        failed, fall back to the async confirmation queue). Only the stdio
        transport can supply this — it needs a live, bidirectional connection
        to send the client a mid-call 'elicitation/create' request and block
        for its reply, which a stateless HTTP request/response cycle cannot
        do. See StdioMCPServer._elicit_decision.

    transport / session_key / via_drawer: 호출 품질 칸(p6_74)용. 전송 계층이
        넘긴다 — transport 는 mcp_stdio|mcp_http|rest|in_app, session_key 는
        같은 대화를 묶는 **원문**(여기서 해시해 16자만 남긴다), via_drawer 는
        use_tool 위임이 True 로 넘긴다. 이 함수 안에서 요청 헤더를 읽지 않는다 —
        여기는 test_request_context 라 원래 요청이 보이지 않는다.

    tool_profile: 이 연결의 도구 묶음(`mcp_auth.tool_profile_of(role)`).
        None 이면 제한 없음. 외부 전송(mcp_stdio·mcp_http·rest)에서 묶음 밖
        도구를 부르면 게이트 앞에서 거절한다(reason_code=tool_profile, 승인 큐에
        들어가지 않는다). 서랍 조회도 이 묶음 안에서만 답한다.

    Returns:
        list[dict]: MCP content blocks, e.g. [{"type": "text", "text": "..."}]
    """
    from aot.tools import mcp_safety_gate as gate
    from aot.mcp_server import audit

    arguments = arguments or {}

    # use_tool 은 실행을 **위임**한다 — 게이트도 감사도 안쪽 호출이 남긴다.
    # 여기서 한 겹 더 기록하면 같은 실행이 감사 로그에 두 줄로 남아 호출 횟수를
    # 셀 수 없게 되고, 바깥에서 게이트를 한 번 더 태우면 승인 대상이 use_tool
    # 이라는 이름으로 큐에 들어가 사람이 무엇을 승인하는지 알 수 없게 된다.
    if tool_name == "use_tool":
        inner = arguments.get("tool_name")
        inner_args = arguments.get("arguments")
        if inner_args is None:
            inner_args = {}
        if not inner or not isinstance(inner, str):
            return _tool_error("use_tool requires 'tool_name' — the name of the tool "
                               "to run. Call open_drawer to see what is available.")
        inner = inner.strip()
        if inner == "use_tool":
            return _tool_error("use_tool cannot call itself. Pass the name of the "
                               "actual tool you want to run.")
        if not isinstance(inner_args, dict):
            return _tool_error("use_tool's 'arguments' must be an object holding the "
                               "target tool's own arguments.")
        # 메타 키(_reason, _confirmation_id …)를 바깥에 실어 보내는 클라이언트가
        # 있다. 안쪽이 그것을 못 보면 승인 후 재시도가 조용히 다시 큐로 간다.
        merged = dict(inner_args)
        for k, v in arguments.items():
            if k.startswith("_") and k not in merged:
                merged[k] = v
        # scope_user_uuid 를 함께 넘긴다 — 빠뜨리면 **use_tool 로 감싸 부르는
        # 것만으로 스코프를 벗어난다.** 서랍 안 도구는 전부 이 경로를 지난다.
        return _execute_tool(app, inner, merged, agent_id=agent_id,
                             role=role, elicit_fn=elicit_fn,
                             scope_user_uuid=scope_user_uuid,
                             transport=transport, session_key=session_key,
                             via_drawer=True, tool_profile=tool_profile)
    # 호출 품질의 duration_ms 는 여기서부터 잰다 — use_tool 의 인자 검증은
    # 빼고, 스코프·게이트·실행·캡·최종 직렬화를 넣는다(감사 쓰기·전송은 뺀다).
    _t0 = time.monotonic()
    # `agent_id` is decided by the transport (API key, or the declared name when
    # auth is off) and is NOT overridable from the arguments. An earlier version
    # honoured a `_agent_id` argument here, which let any caller stamp someone
    # else's name on its calls and defeated authentication entirely. The key is
    # still accepted and stripped for backward compatibility, but ignored.
    # `_reason` is free-text and stays caller-supplied — it is not an identity.
    reason = arguments.get("_reason") or ""
    permission = gate.classify_permission(tool_name)

    blocked = None
    error_text = ""
    # 무엇이 실패하든 기록은 남는다(아래 finally). 실행에 닿기도 전에 깨지면
    # 이 초기값 그대로 'failed' 로 적힌다.
    result = None
    # ── 감사 기록 — 캡·직렬화까지 끝난 뒤 **한 번에** 쓴다 ──────────────
    # 예전에는 실행 직후 INSERT 하고 곧바로 UPDATE 했다(커밋 2회). 둘 다
    # 실행이 끝난 뒤였으므로 캡 뒤로 옮겨 한 번에 써도 남는 내용은 같다 —
    # 다만 결과 요약은 **캡이 손대기 전**에 떼어 둔다(_audit_outcome).
    # try/finally 로 감싸는 이유: 직렬화가 깨지면 예전에는 행이 이미 executed
    # 로 적힌 채 오류가 숨었다. 이제는 failed 로 정확히 남고 예외는 그대로
    # 올라간다.
    outcome = None
    quality = {"call_state": "failed"}
    record_error = ""
    cap_stats = {}
    try:
        # test_request_context (not just app_context): several handlers call
        # parse_input_information()/parse_output_information() (create_input,
        # create_output, create_gis_input, list_device_types(kind='input'|'output'),
        # get_device_type_options(...)), which need flask_babel's request-bound
        # gettext for translated option labels and raise "Working outside of
        # request context" under a bare app_context. The in-app AI never hits this
        # because it always runs inside a real Flask request; this standalone
        # server previously only pushed an app context, so every one of those
        # tools was silently broken here until now (found 2026-07-26 testing
        # create_gis_input). test_request_context() pushes both a request and an
        # app context, so this is a strict superset of the old app_context() call.
        with app.test_request_context():
            # 코드가 연 가짜 요청이라는 표지 — 인앱 AI 가 이 안에서 사람을
            # 찾지 않게 한다(aot/ai/ai_request_context.SYNTHETIC_REQUEST_KEY).
            from flask import request as _req
            _req.environ["aot.synthetic_request"] = True
            try:
                # 묶음 밖 호출 — 게이트·스코프보다 먼저, 승인 큐에 넣지 않고
                # 거절한다. 거절은 blocked 로 흘려 감사·호출 품질이 다른
                # 거부와 같은 모양(call_state=refused)으로 남게 한다.
                profile_refused = _profile_refusal(tool_name, tool_profile,
                                                   transport, role=role)
                # 이 연결에 실제로 적용되는 묶음(인앱·서비스 계정·스위치 끔 = None).
                enforced = _profile_enforced(tool_profile, transport)
                if profile_refused is not None:
                    result = blocked = profile_refused
                elif tool_name in ("open_drawer", "get_tool_detail"):
                    # 서랍 열기/스키마 조회는 읽기이고, 게이트가 아는 도구도 아니다
                    # (tool_registry 의 동명 핸들러는 내부 AI 표면용이라 카탈로그가
                    # 다르다 — 이 표면의 원천은 _get_all_tools 하나뿐이어야 한다).
                    lookup = (_open_drawer if tool_name == "open_drawer"
                              else _get_tool_detail)
                    result = lookup(app, arguments, role=role,
                                    profile=tool_profile)
                    # 묶음 밖 조회는 호출과 같은 거절로 기록한다.
                    if isinstance(result, dict) and \
                            result.get("reason_code") == "tool_profile":
                        blocked = result
                elif tool_name == _CONFIRMATION_RESPONSE_TOOL:
                    # 승인 큐 응답 자체는 게이트를 거치지 않는다 — "승인하려면 승인이
                    # 필요하다"는 순환을 피하기 위함. 대신 role 체크는 여기서 직접 한다.
                    result = _respond_to_confirmation(arguments, agent_id, role,
                                                      profile=enforced)
                    if isinstance(result, dict) and \
                            result.get("reason_code") == "tool_profile":
                        blocked = result
                else:
                    result, blocked = _run_gated_tool(
                        tool_name, arguments, agent_id=agent_id, role=role,
                        reason=reason, elicit_fn=elicit_fn,
                        scope_user_uuid=scope_user_uuid)
                    if blocked is None and tool_name == "get_system_brief":
                        _attach_profile_note(result, tool_profile)
                    elif blocked is None and enforced is not None and \
                            tool_name == "list_pending_confirmations":
                        _mask_out_of_profile_pending(result, enforced)
                    elif blocked is None and tool_name == "knowledge_search":
                        _attach_shelve_hint(result, enforced, role)
            except ValueError as exc:
                error_text = str(exc)
                result = {"status": "error", "message": error_text}
            except Exception as exc:
                error_text = str(exc)
                logger.error(f"[AoTMCP] Tool '{tool_name}' failed: {exc}", exc_info=True)
                result = {"status": "error", "message": error_text}

        outcome = _audit_outcome(tool_name, permission, blocked, result,
                                 error_text)
        record_error = error_text
        out = _finish_result(result, tool_name, blocked, error_text,
                             quality, cap_stats)
    except Exception as exc:
        quality["call_state"] = "failed"
        quality["response_bytes"] = None
        record_error = repr(exc)
        raise
    except BaseException as exc:
        # KeyboardInterrupt·SystemExit·작업 취소 등 — 기록은 failed 로 남기고
        # 그대로 올려 보낸다(삼키지 않는다). 아래 finally 가 한 번만 적는다.
        quality["call_state"] = "failed"
        quality["response_bytes"] = None
        record_error = repr(exc)
        raise
    finally:
        quality["duration_ms"] = int(round((time.monotonic() - _t0) * 1000))
        if outcome is None:
            outcome = _audit_outcome(tool_name, permission, blocked, result,
                                     error_text)
        _record_audit(audit, tool_name, arguments, agent_id, permission,
                      reason, outcome, record_error, quality,
                      transport=transport, session_key=session_key,
                      via_drawer=via_drawer, cap_stats=cap_stats)
    return out


def _attach_profile_note(result, profile):
    """get_system_brief 응답에 이 연결의 묶음을 싣는다(시작점이라 여기서 알린다).

    서버 안내문을 보여 주지 않는 호스트도 있어, 대화의 첫 조회에도 같은 말을
    둔다. 제한이 없으면(인앱 AI) 아무것도 붙이지 않는다."""
    profile = _effective_profile(profile)
    if profile is None or not isinstance(result, dict):
        return result
    result["tool_profile"] = {"name": profile, "note": _profile_note(profile)}
    return result


def _scope_precheck_refusal(tool_name, arguments, scope_user_uuid):
    """앞 단계(인자 짐작) 스코프 거부 본문. 통과면 None."""
    denied = _scope_refusal(tool_name, arguments, scope_user_uuid)
    if not denied:
        return None
    from aot.aot_flask.access import scope as _scope
    if denied == SCOPE_CHECK_FAILED:
        return {"status": "refused", "reason_code": "group_scope",
                "message": ("Could not check this request against your groups "
                            "- nothing was changed. Try again, or ask an "
                            "administrator if it keeps failing."),
                "target": None}
    if denied == _scope.SCAN_LIMIT:
        return {"status": "refused", "reason_code": "group_scope",
                "message": ("This request has too many items (or is nested too "
                            "deeply) to check every target against your groups "
                            "- split it into smaller requests."),
                "target": None}
    return {"status": "refused", "reason_code": "group_scope",
            "message": _scope.deny_message(), "target": denied}


def _run_gated_tool(tool_name, arguments, agent_id, role, reason, elicit_fn,
                    scope_user_uuid):
    """스코프 앞 판정 → 승인 게이트 → 실행. (result, blocked) 를 돌려준다.

    그룹 스코프는 두 겹이다(설계 §6-2a):

      1. **앞 판정**(`_scope_refusal`) — 인자를 훑어 대상을 짐작한다. 승인
         게이트보다 먼저 묻는 이유는, 뒤에 두면 어차피 거부될 호출이 승인
         큐에 들어가 사람이 승인한 뒤에야 거부되기 때문이다. **조언일 뿐
         경계가 아니다** — 처리기가 대상을 푸는 방식을 다 알 수 없다.
      2. **쓰기 시점 판정**(`write_scope.enforce`) — 처리기와 공용 리졸버가
         실제로 쓸 행을 손에 쥔 순간 묻는다. 경계는 여기다. 이 함수가 호출
         동안 호출자를 묶어 두고(`acting_as`), 거부(`WriteScopeDenied`)를
         잡아 앞 판정과 같은 모양의 거부로 바꾼다.

    읽기 도구는 묶지 않는다 — 읽기 경로의 리졸버가 거부를 던지면 안 된다.
    """
    from aot.aot_flask.access import write_scope
    from aot.tools import mcp_safety_gate as gate

    is_write = tool_name in gate.write_tools()
    with write_scope.acting_as(scope_user_uuid if is_write else None,
                               tool=tool_name) as principal:
        try:
            blocked = _scope_precheck_refusal(tool_name, arguments,
                                              scope_user_uuid)
            if blocked is None and is_write:
                blocked = _pre_gate_validation(tool_name, arguments, role)
            if blocked is None:
                blocked = gate.gate(tool_name, arguments, agent_id=agent_id,
                                    role=role, reason=reason,
                                    elicit_fn=elicit_fn)
            if blocked is not None:
                return blocked, blocked
            call_args = gate.inject_agent(
                tool_name, gate.strip_meta(arguments), agent_id)
            # 승인된 확인 번호로 다시 부른 호출이면 **승인한 사람도** 함께
            # 판정한다(설계 §6-2a). 부른 사람과 승인한 사람이 다를 수 있고,
            # 한쪽만 보면 다른 쪽의 그룹 밖 대상이 움직인다 — 둘 다 통과해야
            # 쓴다. 게이트가 방금 소비한 행에 승인자가 적혀 있다.
            approver = (_confirmation_approver(arguments)
                        if is_write else None)
            with write_scope.also_acting_as(approver, tool=tool_name):
                if tool_name in _NATIVE_TOOLS:
                    from aot.tools.aot_native_tool_engine import AoTNativeToolEngine
                    result = AoTNativeToolEngine.execute(tool_name, call_args)
                else:
                    result = _dispatch_virtual_tool(tool_name, call_args)
        except write_scope.WriteScopeDenied as exc:
            _rollback_session()
            refused = write_scope.refusal(exc)
            return refused, refused
        if is_write and write_scope.was_denied(principal):
            # 처리기가 거부를 문자열로 바꿔 삼켰다 — 결과를 거부로 바로잡는다.
            _rollback_session()
            refused = write_scope.refusal()
            return refused, refused
    return result, None


# ── 인자 검증 — 승인·조언 전용 거절보다 먼저 (P2) ─────────────────────────────
# 게이트는 인자를 보지 않는다. 그래서 조언 전용 모드·읽기 전용 키·승인 대기에서
# 모델은 "쓰기 불가" 만 받고, 지어낸 옵션 키나 빠진 인자가 틀렸다는 것을 끝내
# 모른다(재측정 26-09-23 lat_24: 없는 옵션 키 6건). 그 상태로 조언을 남기면
# 틀린 조언이 된다. 쓰기 도구는 게이트 **앞에서** 인자를 먼저 본다 — 틀리면
# 무엇이 틀렸고 무엇이 맞는지 말하고, 맞으면 게이트가 평소대로 판정한다.
# 스코프 앞 판정 뒤에 둔다 — 그룹 밖 대상의 존재·정의를 알려 주지 않게.

#: 도구별 추가 검증 — AoTDataToolService 의 메서드 이름. (인자) → None | 오류 dict.
_PRE_GATE_VALIDATORS = {
    'modify_function_options': 'validate_function_options',
    'confirm_plot_stage': 'validate_confirm_plot_stage',
}

#: 스키마 검사에서 인자로 치지 않는 전송·메타 키.
_TRANSPORT_KEYS = frozenset({"tool_name", "server_id", "agent_unique_id",
                             "context"})


def _tool_schema(tool_name):
    """MCP 에 광고하는 inputSchema(앱 없이). 모르면 None."""
    from aot.tools import tool_registry as registry
    for p in registry._MCP_TOOL_PAYLOADS:
        if p.get("tool_name") == tool_name:
            return p.get("input_schema")
    for t in _EXTRA_TOOLS:
        if t["name"] == tool_name:
            return t.get("inputSchema")
    if tool_name in _NATIVE_TOOLS:
        from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
        builder = getattr(N, "_schema_%s" % tool_name, None)
        if builder is not None:
            try:
                return builder([]).get("inputSchema")
            except TypeError:
                return builder().get("inputSchema")
    return None


def _handler_takes_any_key(tool_name):
    """처리기가 모르는 키를 **실제로 쓰는가**(임의 설정 키를 받는 도구). 그런
    도구는 이름 검사를 하지 않는다 — 잉여 키가 본론이다."""
    import inspect
    if tool_name in _NATIVE_TOOLS:
        return False
    try:
        from aot.tools.tool_registry import build_tool_map
        handler = build_tool_map().get(tool_name)
    except Exception:                                       # noqa: BLE001
        return True
    if handler is None:
        return True
    try:
        params = inspect.signature(handler).parameters
    except (TypeError, ValueError):
        return True
    if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return False
    return _discarded_kwarg_sink(handler) is None


def _handler_param_names(tool_name):
    """처리기 서명의 이름 인자들(**kwargs 제외). 모르면 빈 집합."""
    import inspect
    try:
        if tool_name in _NATIVE_TOOLS:
            return set()
        from aot.tools.tool_registry import build_tool_map
        handler = build_tool_map().get(tool_name)
        return {n for n, p in inspect.signature(handler).parameters.items()
                if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                              inspect.Parameter.KEYWORD_ONLY)} - {"cls", "self"}
    except Exception:                                       # noqa: BLE001
        return set()


def _handler_optional_names(tool_name):
    """처리기 서명에서 기본값이 있는 인자 — 스키마가 필수로 적어도 처리기가
    없이 받는다면 여기서 막지 않는다."""
    import inspect
    try:
        if tool_name in _NATIVE_TOOLS:
            return set()
        from aot.tools.tool_registry import build_tool_map
        handler = build_tool_map().get(tool_name)
        return {n for n, p in inspect.signature(handler).parameters.items()
                if p.default is not inspect.Parameter.empty}
    except Exception:                                       # noqa: BLE001
        return set()


#: 클라이언트가 흔히 덧붙이는 메타 인자 — 스키마에 없어도 오타로 보지 않는다
#: (`_reason`·`_title` 의 밑줄 없는 형태 등). 처리기가 무시하고 응답의
#: `_ignored_arguments` 가 알린다.
_CLIENT_META_ARGS = frozenset({"reason", "title", "confirm", "confirmed",
                               "confirmation", "rationale", "justification",
                               "dry_run"})


def _likely_typo(key, valid):
    """모르는 인자 이름이 맞는 이름의 오타로 보이면 그 이름, 아니면 None.

    거절은 **오타로 보일 때만** 한다(26-09-24 결정). 모르는 키를 다 거절하면
    클라이언트가 습관처럼 싣는 메타 키(reason·title)까지 막혀 멀쩡한 호출이
    틀린 호출이 된다. 오타는 반대로 조용히 버리면 필터·대상이 빠진 채 실행된다
    (`zone_id` ↔ `zone_ids`). 가르는 기준: 대소문자·구분자·단복수·`_id` 꼬리를
    뺀 줄기가 같거나, difflib 유사도 0.8 이상."""
    import difflib
    if key in _CLIENT_META_ARGS or not valid:
        return None

    def stem(k):
        k = str(k).lower().replace("-", "").replace("_", "")
        for tail in ("ids", "id", "s"):
            if k.endswith(tail) and len(k) > len(tail) + 1:
                return k[:-len(tail)]
        return k
    for v in sorted(valid):
        if stem(v) == stem(key):
            return v
    close = difflib.get_close_matches(str(key), sorted(valid), n=1, cutoff=0.8)
    return close[0] if close else None


def _pre_gate_validation(tool_name, arguments, role=None):
    """쓰기 호출의 인자를 게이트 앞에서 본다. 문제 없으면 None, 있으면 거절 본문.

    거절하는 것(26-09-24 결정): (a) 빠진 필수 인자(스키마가 필수로 적고
    처리기에도 기본값이 없는 것), (b) 맞는 이름과 아주 가까운 모르는 인자
    이름 = 오타(`_likely_typo`), (c) 도구별 검증(_PRE_GATE_VALIDATORS —
    modify_function_options 의 없는 옵션 키 등). 그 밖의 모르는 인자는 거절하지
    않는다 — 처리기가 버리고 응답의 `_ignored_arguments` 가 알린다(예전과 같다).
    처리기가 임의 키를 받는 도구는 이름을 보지 않는다. 선택지(enum) 밖 값도
    보지 않는다 — 스키마의 선택지가 처리기보다 좁은 도구가 있다(operate_device
    는 open·close 도 받는다).

    거절할 때, 이 호출자의 역할·조언 전용 모드가 **어차피** 막을 호출이면 같은
    메시지에 그렇게 적는다 — 인자를 고쳐 다시 부르는 헛걸음을 막는다. 묶음
    밖 호출은 이 앞(_profile_refusal)에서 이미 거절된다.
    검사 자체가 깨지면 통과시킨다 — 게이트와 처리기가 뒤에 있다."""
    from aot.tools.mcp_safety_gate import META_KEYS
    try:
        args = {k: v for k, v in (arguments or {}).items()
                if k not in META_KEYS and k not in _TRANSPORT_KEYS
                and not str(k).startswith("_")}
        problems, valid = [], None
        schema = _tool_schema(tool_name) or {}
        props = schema.get("properties") or {}
        if props:
            valid = sorted(props)
            optional = _handler_optional_names(tool_name)
            missing = [k for k in schema.get("required") or []
                       if args.get(k) in (None, "") and k not in optional]
            if missing:
                problems.append("missing required argument(s): %s"
                                % ", ".join(missing))
            if not _handler_takes_any_key(tool_name):
                # 처리기가 이름으로 받는 인자도 맞는 이름이다 — 인앱 매니페스트가
                # 스키마에 없는 인자를 안내하는 도구가 있다.
                known = set(props) | _handler_param_names(tool_name)
                typos = []
                for k in sorted(args):
                    if k in known:
                        continue
                    near = _likely_typo(k, known)
                    if near:
                        typos.append("'%s' (did you mean '%s'?)" % (k, near))
                if typos:
                    problems.append("unknown argument(s): %s" % ", ".join(typos))
        body = None
        if problems:
            body = {"error": "; ".join(problems) + "."}
            if valid:
                body["valid_arguments"] = valid
        else:
            method = _PRE_GATE_VALIDATORS.get(tool_name)
            if method:
                from aot.tools.aot_data_tool_service import AoTDataToolService
                body = getattr(AoTDataToolService, method)(**args)
        if not body:
            return None
    except Exception as exc:                                # noqa: BLE001
        logger.warning("[AoTMCP] 인자 사전 검증 실패(게이트로 넘김) %s: %s",
                       tool_name, exc)
        return None
    message = ("%s Fix the arguments and call again. This was checked before "
               "any permission or approval step."
               % (body.get("error") or "Invalid arguments."))
    out = {"status": "refused", "reason_code": "invalid_arguments",
           "tool_name": tool_name}
    try:
        from aot.tools import mcp_safety_gate as gate
        blocked = gate.role_refusal(tool_name, role)
    except Exception:                                       # noqa: BLE001
        blocked = None
    if blocked:
        message = ("%s Fix the arguments and note that even with correct "
                   "arguments this call would be refused: %s"
                   % (body.get("error") or "Invalid arguments.",
                      blocked.get("message") or ""))
        out["also_refused"] = blocked.get("reason_code")
    out["message"] = message
    out.update({k: v for k, v in body.items() if k != "error"})
    return out


def _confirmation_approver(arguments):
    """이 호출이 실어 온 확인 번호를 승인한 사람의 uuid. 없으면 None."""
    cid = (arguments or {}).get('_confirmation_id')
    if not cid:
        return None
    try:
        from aot.databases.models import MCPConfirmation
        row = MCPConfirmation.query.filter_by(unique_id=cid).first()
        return (row.user_id or None) if row is not None else None
    except Exception:
        logger.exception('[write-scope] 승인자 조회 실패')
        return None


def _rollback_session():
    """거부된 쓰기가 세션에 남긴 것을 버린다(아직 커밋 전이다)."""
    try:
        from aot.aot_flask.extensions import db
        db.session.rollback()
    except Exception:
        logger.exception('[write-scope] 세션 되돌리기 실패')


#: 결과 건수를 셀 때 보지 않는 곁가지 목록 — 본 결과가 아니라 경고·안내·
#: 참고 링크 같은 덧붙임이다. 이것까지 세면 결과가 비었는데도 "경고 1건"
#: 때문에 빈 결과가 아닌 것으로 잡힌다. `_` 로 시작하는 키도 내부 칸이라 뺀다.
_RESULT_ITEMS_AUX_KEYS = frozenset({
    "errors", "warnings", "notes", "hints", "see", "see_also",
    "available_releases", "controlling_tools", "suggestions", "next_steps",
})


def _result_items(result):
    """결과 건수 근사치 — 빈 결과율의 분자.

    1. 최상위 `count`·`total`·`matched` 중 정수가 있으면 그 값(도구가 직접 센 값).
    2. 없으면 곁가지 목록(_RESULT_ITEMS_AUX_KEYS)과 `_` 로 시작하는 키를 뺀
       최상위 목록을 본다. **정확히 하나**면 그 길이.
    3. 둘 이상이면 어느 것이 본 결과인지 모르므로 None(모름). 없어도 None.
    """
    if not isinstance(result, dict):
        return None
    for key in ("count", "total", "matched"):
        val = result.get(key)
        if isinstance(val, int) and not isinstance(val, bool):
            return val
    lists = [v for k, v in result.items()
             if isinstance(v, list) and not str(k).startswith("_")
             and k not in _RESULT_ITEMS_AUX_KEYS]
    return len(lists[0]) if len(lists) == 1 else None


def _finish_result(result, tool_name, blocked, error_text, quality, cap_stats):
    """실행 결과 → MCP 블록. 호출 품질 칸을 `quality` 에 채운다."""
    from aot.tools import mcp_safety_gate as gate

    quality["call_state"] = gate.call_state(blocked, result, error_text,
                                            tool_name=tool_name)

    # 텍스트가 아닌 블록(이미지 등)을 실어 보내는 통로. 도구가 결과 dict 에
    # `_content_blocks` 로 담아 두면 여기서 꺼내 MCP 블록으로 나란히 붙인다.
    #
    # **캡보다 먼저 꺼내는 것이 이 코드의 핵심이다.** _cap_result 는 dict 를
    # json 으로 덤프해 글자 수로 토큰을 어림하는데, base64 이미지는 한 장에
    # 수십만 자라 그대로 두면 캡이 즉시 발동해 이미지도 잘리고 정작 남겨야 할
    # 텍스트 필드까지 함께 버려진다. 이미지는 클라이언트에서 이미지 토큰으로
    # 계산되지 텍스트 글자 수로 계산되지 않으므로, 애초에 캡의 자에 올리지
    # 않는 것이 옳다.
    _blocks = None
    if isinstance(result, dict):
        _blocks = result.pop("_content_blocks", None)
        result.setdefault("server_host", SERVER_HOST)
        # 호출이 실제로 돌았는지를 도구별 어휘와 무관하게 한 키로 알린다.
        # 여기가 stdio/HTTP 양쪽이 반드시 지나는 단일 지점이라 한 번만 찍으면 된다.
        result["call_state"] = quality["call_state"]
        # 쓰기가 실제로 일어나지 않았으면 그 사실과 "사람에게 뭐라고 말하나"
        # 를 싣는다(performed:false + _reading). 거부가 만들어지는 자리는
        # 게이트·스코프·처리기로 여럿이지만 모두 이 한 지점을 지난다.
        gate.annotate_write_outcome(tool_name, quality["call_state"], result)
        # 건수는 `now`·`_truncated` 를 붙이기 전, 캡이 목록을 줄이기 전에 센다.
        quality["result_items"] = _result_items(result)
        result["now"] = _farm_now()
        result = _cap_result(result, tool_name, stats=cap_stats)
        quality["truncated"] = "_truncated" in result
    text = json.dumps(result, ensure_ascii=False)
    # 실제로 나간 크기 — 잘린 뒤의 텍스트. 이미지 블록은 넣지 않는다.
    quality["response_bytes"] = len(text.encode("utf-8"))
    out = [{"type": "text", "text": text}]
    if _blocks:
        out.extend(_blocks)
    return out


def _current_request_user_uuid():
    """지금 요청을 낸 사람의 uuid. 요청 밖이거나 미인증이면 None.

    **요청 밖 = 사람이 없는 호출**이다(백그라운드 AI 잡·주기 요약·예약 발화).
    그 경우 스코프는 면제이고, 그것이 A1 이 막은 것을 여는 구멍이라는 사실은
    설계 §6-2 와 매뉴얼에 적혀 있다.
    """
    try:
        from flask import has_request_context
        if not has_request_context():
            return None
        import flask_login
        current = flask_login.current_user
        if not current or not current.is_authenticated:
            return None
        from aot.databases.models import User
        row = User.query.filter(User.name == current.name).first()
        return row.unique_id if row else None
    except Exception:
        return None


def _scope_refusal(tool_name, arguments, scope_user_uuid):
    """그룹 스코프가 이 도구 호출을 막는가. 막으면 거부된 자원 uuid, 아니면 None.

    정본 설계: `docs/design/access-scope-groups.md` §6-2

    신원은 **`scope_user_uuid` 하나**다:

      - 외부 MCP: 전송 계층이 확인한 **키 소유자**(`RoleInfo.user_id`).
      - 인앱 채팅: 부른 사람.
      - `None`: **사람이 없는 호출**(백그라운드 AI 잡·주기 요약) → 면제.
        §6-1 데몬과 같은 근거다. 이 면제가 A1 이 막은 것을 여는 구멍이라는
        사실은 설계 문서와 매뉴얼에 적혀 있다.

    ⚠ **`role` 로 판정하지 말 것.** 내부 AI 의 `role` 은 서비스 계정
    `aot-system` 에서 오고, 그것을 신원으로 쓰면 내부 AI 가 아무것도 못 하게
    된다 — 그것을 고치려고 서비스 계정을 면제하면 **같은 계정 키로 붙는 외부
    클라이언트까지 함께 열린다**(`scope.is_exempt` 주석).

    검사 자체가 깨지면 — **쓰기 도구는 거부**(`SCOPE_CHECK_FAILED`), 읽기
    도구는 통과(A 범위에서 보기는 전원 공개다). 예전에는 쓰기도 통과시켰는데,
    그러면 판정 코드의 예외 하나가 그룹 밖 쓰기를 여는 문이 된다. 뒤의 쓰기
    시점 강제도 판정 실패를 거부로 닫으므로 두 겹이 같은 방향이다.
    """
    try:
        from aot.aot_flask.access import scope
        from aot.databases.models import User

        if not scope.scoping_active():
            return None
        if not scope_user_uuid:
            return None                  # 사람이 없는 호출 = 면제
        user = User.query.filter(User.unique_id == scope_user_uuid).first()
        if user is None:
            # 신원을 확인했는데 그 사용자가 없다 — 판정 근거가 없으므로
            # 거부하지 않는다(예약 재검사에서 지워진 소유자를 면제하는 것과
            # 같은 판단).
            return None
        allowed, denied_uuid = scope.can_operate_tool_call(
            tool_name, scope_arguments(tool_name, arguments), user=user)
        return None if allowed else denied_uuid
    except Exception as exc:
        try:
            from aot.tools import mcp_safety_gate as _gate
            is_write = tool_name in _gate.write_tools()
        except Exception:
            is_write = True              # 분류도 못 하면 쓰기로 본다
        if is_write:
            logger.error("[scope] 쓰기 도구 판정 실패 — 거부로 닫는다: %s", exc)
            return SCOPE_CHECK_FAILED
        logger.error("[scope] 읽기 도구 판정 실패, 실행은 계속합니다: %s", exc)
        return None


#: `_scope_refusal` 이 판정 실패로 쓰기를 거부할 때 돌려주는 표지(uuid 아님).
SCOPE_CHECK_FAILED = 'scope-check-failed'


# 판정 사본에 덧붙이는 키. 처리기로는 가지 않는다(사본에만 있다).
SCOPE_RESOLVED_KEY = '_scope_resolved_targets'

#: 장치를 이름으로도 받는 id 키 — 처리기(operate_device·schedule_device_control
#: 등)가 `resolve_output` 으로 이름·부분 이름까지 푼다. 인앱 판정이 예전부터 이
#: 셋을 풀어 왔고, 외부 MCP 판정은 풀지 않았다 — 이제 한 자리에서 푼다.
_DEVICE_TOKEN_KEYS = ('device_id', 'output_id', 'unique_id')

#: 중첩 인자를 훑는 깊이·목록 길이 상한 — 옛 action_type 은 `{'target_id', 'params': {...}}`
#: 로 한 겹 싸여 오고, 일괄 도구는 목록 안에 대상을 둔다.
#: 이름 풀기의 한계는 `scope.SCAN_MAX_DEPTH`·`SCAN_MAX_ITEMS` 를 따른다. 한계를
#: 넘는 인자는 `scope.can_operate_tool_call` 이 **거부**한다 — 예전에는 여기서
#: 목록 앞 200개만 보고 나머지를 조용히 건너뛰어, 201번째 항목이 판정 밖에서
#: 실행됐다(2026-09-23 재현).


def _has_target_id(value):
    return isinstance(value, str) and bool(value.strip()) and value.strip() != 'none'


def _resolve_name_for_scope(name):
    """처리기와 **같은 리졸버**로 이름을 푼다. 한 곳으로 풀리면 그 id, 아니면 None.

    모호하거나 못 찾으면 None — 그 경우 처리기가 어차피 쓰지 않고 되묻거나
    거부한다(`_ambiguity_refusal`·`_schedule_target_refusal`).
    """
    try:
        from aot.tools.aot_data_tool_service import AoTDataToolService
        tid = AoTDataToolService._resolve_note_target(name)[0]
        return tid if isinstance(tid, str) and tid else None
    except Exception as exc:
        logger.warning("[scope] 이름 해석 실패(판정은 id 만으로): %s", exc)
        return None


def _resolve_device_for_scope(token):
    """장치 id 자리에 온 이름 → 장치 uuid. 이미 uuid 모양이거나 못 풀면 None."""
    try:
        from aot.aot_flask.access import scope
        if not isinstance(token, str) or not token.strip():
            return None
        if scope._looks_like_uuid(token.strip()):
            return None                  # uuid 는 값 훑기가 직접 본다
        rid = scope.resolve_device_token(token.strip())
        return rid if isinstance(rid, str) and rid != token.strip() else None
    except Exception as exc:
        logger.warning("[scope] 장치 이름 해석 실패(판정은 id 만으로): %s", exc)
        return None


#: 함수·제어기를 이름으로도 받는 id 키 — 처리기가 Conditional·Trigger·PID·
#: CustomController 를 `unique_id == x OR name == x` 로 찾는다(activate_function·
#: configure_sequence_day·modify_sequence_schedule, 옛 'activate').
_FUNCTION_TOKEN_KEYS = ('function_id', 'entity_id')


def _resolve_function_for_scope(token):
    """함수 id 자리에 온 이름 → 그 함수 uuid(들). uuid 모양이면 값 훑기가 본다."""
    try:
        from aot.aot_flask.access import scope
        if not isinstance(token, str) or not token.strip():
            return []
        token = token.strip()
        if scope._looks_like_uuid(token):
            return []
        from aot.databases.models import (Conditional, CustomController,
                                          Function, Input, PID, Trigger)
        out = []
        for model in (Conditional, Trigger, PID, CustomController, Function,
                      Input):
            out.extend(r.unique_id for r in model.query.filter(
                model.name == token).all())
        return out
    except Exception as exc:
        logger.warning("[scope] 함수 이름 해석 실패(판정은 id 만으로): %s", exc)
        return []


def _resolve_child_for_scope(d):
    """자식 행 id(`action_id` — 시퀀스 단계, `job_id` — 일정) → 그것이 움직이는
    대상 uuid. 처리기는 그 행을 찾아 부모·대상에 쓴다."""
    out = []
    try:
        from aot.aot_flask.access import write_scope
        action_id = d.get('action_id')
        if isinstance(action_id, str) and action_id.strip():
            from aot.databases.models.function import Actions
            row = Actions.query.filter_by(unique_id=action_id.strip()).first()
            if row is not None:
                out.extend(uid for _m, uid in write_scope.refs_of(row))
        job_id = d.get('job_id')
        if job_id is not None and str(job_id).strip():
            from aot.tools.aot_data_tool_service import AoTDataToolService
            meta = AoTDataToolService._lookup_schedule_job(job_id)
            if meta is not None:
                out.extend(uid for _m, uid in write_scope.refs_of(meta))
    except Exception as exc:
        logger.warning("[scope] 자식 행 대상 해석 실패(판정은 id 만으로): %s", exc)
    return [u for u in out if u]


def scope_arguments(tool_name, arguments, is_write=None):
    """그룹 스코프 판정에 넘길 인자 — 이름으로 준 대상을 id 로 풀어 덧붙인다.

    `scope.can_operate_tool_call` 은 인자 안의 **uuid 값**만 훑는다. 그런데
    쓰기 도구 여럿이 대상을 **이름**으로 받고 처리기가 나중에 id 로 푼다:

      - 위치 이름 — `target_name` 과 그 옛 별칭(`location`·`zone_name`…).
        키 목록은 처리기와 같은 정본 `aot.tools.target_names` 를 읽는다.
        (2026-09-23: `add_schedule(location=...)` 가 별칭만으로 스코프를 넘었다.)
      - 장치 이름 — `device_id`·`output_id`·`unique_id` 에 이름을 줘도
        처리기가 `resolve_output` 으로 푼다.
      - 함수 이름 — `function_id` 에 이름을 줘도 처리기가 Conditional·Trigger·
        PID·CustomController 를 이름으로 찾는다.
      - 자식 행 id — `action_id`(시퀀스 단계 → 부모 함수), `job_id`(일정 → 그
        일정이 움직이는 대상). uuid 모양이 아니거나 대상과 이어지는 흔적이 없다.

    ⚠ 이것은 **이른 거부**(승인 큐에 헛된 항목이 쌓이지 않게)일 뿐 경계가 아니다.
    경계는 처리기가 실제 대상을 손에 쥔 자리의 `write_scope.enforce` 다(설계 §6-2a).

    맨 위뿐 아니라 **중첩 dict 와 목록 항목**도 본다(깊이 제한). 옛 action_type
    은 인자를 `{'target_id': …, 'params': {...}}` 로 싸서 보내고, 일괄 도구는
    `entries` 목록 안에 대상을 둔다 — 맨 위만 보면 한 겹 싸는 것만으로 샌다.

    한 층에 `target_id` 가 있으면 그 층의 위치 이름은 풀지 않는다 — 처리기가
    id 를 먼저 쓰고(`add_schedule`·`edit_schedule`), 일괄 도구는 이름이 다른
    곳을 가리키면 거절한다. 그 층의 이름 키가 여럿이면 **전부** 푼다(처리기는
    첫 값만 쓰지만, 판정은 넓게 보는 쪽이 안전하다).

    풀린 id 는 판정 사본의 `SCOPE_RESOLVED_KEY` 에 덧붙인다. 원본은 건드리지
    않는다. 읽기 도구는 풀지 않는다(판정 대상이 아니고 해석 비용만 든다).
    `is_write=True` 를 주면 레지스트리 분류를 건너뛴다 — 인앱 옛 action_type
    처럼 호출자가 이미 쓰기로 판정한 경우.
    """
    if not isinstance(arguments, dict):
        return arguments
    if not is_write:
        try:
            from aot.tools import mcp_safety_gate as gate
            if tool_name not in gate.write_tools():
                return arguments
        except Exception:
            pass
    from aot.tools.target_names import TARGET_NAME_KEYS
    found = []

    def _visit_dict(d, depth):
        if not _has_target_id(d.get('target_id')):
            for key in TARGET_NAME_KEYS:
                name = d.get(key)
                if isinstance(name, str) and name.strip():
                    rid = _resolve_name_for_scope(name.strip())
                    if rid:
                        found.append(rid)
        for key in _DEVICE_TOKEN_KEYS:
            rid = _resolve_device_for_scope(d.get(key))
            if rid:
                found.append(rid)
        for key in _FUNCTION_TOKEN_KEYS:
            found.extend(_resolve_function_for_scope(d.get(key)))
        found.extend(_resolve_child_for_scope(d))
        for key, value in d.items():
            if key == SCOPE_RESOLVED_KEY:
                continue
            _visit(value, depth + 1)

    from aot.aot_flask.access.scope import SCAN_MAX_DEPTH, SCAN_MAX_ITEMS

    def _visit(value, depth):
        if depth > SCAN_MAX_DEPTH:
            return
        if isinstance(value, dict):
            _visit_dict(value, depth)
        elif isinstance(value, (list, tuple)):
            for item in list(value)[:SCAN_MAX_ITEMS]:
                _visit(item, depth + 1)

    _visit(arguments, 0)
    if not found:
        return arguments
    out = dict(arguments)
    out[SCOPE_RESOLVED_KEY] = list(dict.fromkeys(found))
    return out


def _tool_error(message):
    """MCP content 포맷의 오류 응답. use_tool 의 인자 검증처럼 감사 대상 실행에
    도달하지도 못한 경우에 쓴다 — 이 자리에서는 아직 어떤 도구도 돌지 않았다."""
    return [{"type": "text", "text": json.dumps(
        {"status": "error", "message": message, "call_state": "refused",
         "server_host": SERVER_HOST}, ensure_ascii=False)}]


def _audit_outcome(tool_name, permission, blocked, result, error_text):
    """감사 행의 (confirmation_status, result_summary) — 예전 2단계 기록과 같은 값.

    캡이 결과를 줄이기 **전에** 부른다. 예전 방식에서 이 둘이 정해지는
    규칙을 그대로 옮긴 것이고, 행 단위 동등성은 테스트가 고정한다.

    요약을 만들다 깨지면(결과가 dict 가 아닌 경우 등) 예전에는 INSERT 만 되고
    UPDATE 가 빠져 상태가 INSERT 의 기본값('n/a' 또는 'pending')으로 남았다.
    그 결과도 그대로 재현한다. (그 경로는 error_text 가 빈 경우뿐이라 error
    칸도 예전과 같다.)
    """
    from aot.tools import mcp_safety_gate as gate
    confirmation_id = (blocked or {}).get("confirmation_id") \
        if isinstance(blocked, dict) else None
    try:
        if permission == "read":
            status = "n/a"
        elif blocked is None and tool_name in gate.approval_exempt_writes():
            # 승인이 면제된 쓰기(설정 편집·기록·조언). 'approved' 로 적으면
            # 아무도 보지 않은 동작을 사람이 승인한 것처럼 남는다 — 안전 감사
            # 로그에서 그건 거짓이다. 승인이 애초에 요구되지 않았음을 적는다.
            status = "not_required"
        elif blocked is None:
            status = "approved"          # gate consumed a human approval
        elif blocked.get("status") == "pending_approval":
            status = "pending"
        else:
            status = "rejected"
        summary = (blocked or {}).get("reason_code") or (
            "" if error_text else str(result.get("status", ""))[:100])
        return {"status": status, "summary": summary,
                "confirmation_id": confirmation_id}
    except Exception:
        return {"status": "n/a" if permission == "read" else "pending",
                "summary": "", "confirmation_id": confirmation_id}


def _quality_ledger_enabled():
    """호출 품질 칸을 채울지. 기본 켬 — 끄면 새 칸만 NULL 로 남는다.

    매 호출마다 읽는다(재시작 없이 끌 수 있게). 감사 행 자체와 단일 INSERT
    는 이 스위치와 무관하다.
    """
    return os.environ.get("AOT_MCP_QUALITY_LEDGER", "1") != "0"


#: 세션 열쇠 원문의 최대 길이. 넘으면 저장하지 않는다(해시 전 원문 길이 기준).
SESSION_KEY_MAX_LEN = 128


def session_key_hash(raw):
    """세션 열쇠 원문 → sha256 앞 16자. 비었거나 너무 길면 None."""
    if raw is None:
        return None
    raw = str(raw)
    if not raw or len(raw) > SESSION_KEY_MAX_LEN:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _record_audit(audit, tool_name, arguments, agent_id, permission,
                  reason, outcome, error_text, quality, transport=None,
                  session_key=None, via_drawer=False, cap_stats=None):
    """Write one mcp_audit_log row describing this call's outcome — one INSERT.

    Never raises: an audit failure must not turn a working tool call into an
    error for the caller (record_call swallows and logs its own exceptions;
    the field assembly below is ours).
    """
    try:
        fields = {}
        if _quality_ledger_enabled():
            fields = {
                "duration_ms": quality.get("duration_ms"),
                "session_key": session_key_hash(session_key),
                "transport": transport,
                "via_drawer": bool(via_drawer),
                "response_tokens": (cap_stats or {}).get("original"),
                "response_bytes": quality.get("response_bytes"),
                "truncated": quality.get("truncated"),
                "call_state": quality.get("call_state"),
                "result_items": quality.get("result_items"),
            }
        audit.record_call(
            tool_name=tool_name,
            params=arguments,
            agent_id=agent_id,
            permission=permission,
            reason=reason,
            confirmation_id=outcome["confirmation_id"],
            confirmation_status=outcome["status"],
            result_summary=outcome["summary"],
            error=error_text,
            **fields,
        )
    except Exception:
        logger.exception("[AoTMCP] audit record failed for '%s'", tool_name)


def _respond_to_confirmation(arguments, agent_id, role, profile=None):
    """respond_to_confirmation 의 실제 실행부.

    사용자가 '이 채팅 안에서' 명시적으로 승인/거부한다고 말한 뒤에만 호출되어야
    한다는 전제를 도구 설명(tool_registry._MCP_TOOL_PAYLOADS)에 강하게 못박아
    두었다 — 여기서는 그 전제가 지켜졌다고 신뢰하고, 대신 "쓰기 권한이 없는
    role은 애초에 아무것도 승인 못 하게" 막는 것만 서버 쪽에서 강제한다. 웹
    승인 엔드포인트(routes_mcp_api.py)와 동일하게 mcp_safety_gate.approve/
    reject를 그대로 호출하고, user_id도 같은 규약(User.unique_id)을 쓴다.

    confirmation_ids(복수, 배열)도 받는다 — 사용자가 여러 건을 한 번에 지목해
    거부/승인하라고 말했을 때(예: 잘못된 배치를 통째로 폐기) 한 건씩 반복 호출할
    필요가 없게 하기 위함이다. 단일 confirmation_id와 동일한 신뢰 전제를 그대로
    적용한다 — 사용자가 이 대화에서 명시적으로 지목한 id들에 한해서만 호출돼야
    하며, "대기 중인 거 알아서 정리해" 같은 막연한 지시로부터 추론해 부르면 안 된다.

    profile: 이 연결에 적용되는 도구 묶음(외부 전송에서만, 아니면 None).
    묶음 밖 도구의 요청은 **거절은 받고 승인은 거절한다** — 치우는 일은 막을
    이유가 없지만, 승인은 그 도구를 이 키로 실행하게 하는 일이라 묶음 밖
    호출을 막는 것과 같은 이유로 막는다. 거절 본문은 도구 이름을 싣지 않는다
    (목록도 가린다 — _mask_out_of_profile_pending).
    """
    from aot.tools import mcp_safety_gate as gate
    from aot.tools import tool_registry as registry
    # 무엇이든 하나는 결정할 수 있는 역할인가(제어·작기 운영·설정 편집). 항목별
    # 판정은 gate._decide 가 도구의 쓰기 권한으로 한다 — 키 역할(role)과 키
    # 소유자의 DB 역할을 **둘 다** 본다(읽기 전용 키는 역할이 무엇이든 못 한다).
    if not gate.role_can_decide_any(role):
        return {
            "status": "refused",
            "reason_code": "insufficient_role",
            "message": ("Your MCP key's role does not have write access — it "
                        "cannot approve or reject pending confirmations."),
        }

    decision = arguments.get("decision")
    if decision not in ("approve", "reject"):
        return {"status": "error",
                "message": "decision ('approve'|'reject') is required."}

    confirmation_ids = arguments.get("confirmation_ids")
    if confirmation_ids is None:
        single = arguments.get("confirmation_id")
        if not single:
            return {"status": "error",
                    "message": "confirmation_id or confirmation_ids is required."}
        confirmation_ids = [single]
    elif not isinstance(confirmation_ids, list) or not confirmation_ids:
        return {"status": "error",
                "message": "confirmation_ids must be a non-empty list of confirmation_id strings."}

    user_id = getattr(role, "user_id", None)
    results = []
    for cid in confirmation_ids:
        target = (_confirmation_tool(cid)
                  if decision == "approve" and profile is not None else None)
        if target and not registry.tool_in_profile(target, profile):
            r = _approval_refusal(target, profile, role)
        elif decision == "approve":
            r = gate.approve(cid, user_id=user_id, role=role)
        else:
            r = gate.reject(cid, user_id=user_id, role=role)
        results.append({"confirmation_id": cid, **r})
        logger.info("[AoTMCP] respond_to_confirmation agent=%s decision=%s confirmation=%s -> %s",
                    agent_id, decision, cid, r.get("status"))

    if len(results) == 1:
        return results[0]
    return {
        "status": "batch_complete",
        "count": len(results),
        "succeeded": sum(1 for r in results if r.get("status") == "success"),
        "results": results,
    }


_KWARG_SINK_CACHE = {}


def _discarded_kwarg_sink(handler):
    """핸들러가 `**extra` 로 **받기만 하고 쓰지 않는** 경우 그 이름을 돌려준다.

    `aot_data_tool_service` 의 도구 함수 대부분이 `**extra` 를 단다 — 외부 AI 가
    잉여 인자를 흔히 실어 보내고, 그것 때문에 도구가 `TypeError` 로 통째로 못
    쓰이게 되는 일을 막기 위함이다. 그런데 그 방벽은 **이름을 틀린 경우까지
    함께 삼킨다**: `get_zone_sensor_summary(zone_ids=…)` 를 `zone_id=…` 로 부르면
    필터가 조용히 사라지고 **필터 없는 전체 스캔**이 정상 응답으로 돌아온다.
    (2026-08-23 실측: 같은 오타로 9회 호출 → 9회 모두 같은 전체 스냅샷.
    "서버가 필터를 무시한다" 로 오진하는 데 오래 걸렸다.)

    그래서 아래 `_dispatch_virtual_tool` 이 그런 키를 `_ignored_arguments` 로
    돌려준다 — 다만 **`extra` 를 실제로 쓰는 핸들러는 제외해야 한다.**
    `create_input`/`modify_plot` 처럼 임의 설정 키를 그 자리로 받는 함수가
    25개 있고, 거기서는 잉여 키가 오류가 아니라 **본론**이다.

    판정은 소스 AST 로 한다(핸들러당 한 번, 코드 객체로 캐시). 이름으로
    가를 수는 없다 — 쓰는 쪽도 안 쓰는 쪽도 똑같이 `extra` 다.
    """
    code = getattr(handler, '__code__', None)
    if code is None:
        return None
    if code in _KWARG_SINK_CACHE:
        return _KWARG_SINK_CACHE[code]

    sink = None
    try:
        import ast
        import inspect
        import textwrap

        params = inspect.signature(handler).parameters
        name = next((p.name for p in params.values()
                     if p.kind is inspect.Parameter.VAR_KEYWORD), None)
        if name is not None:
            tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
            # 서명의 `**extra` 는 ast.arg 라 Name 으로 안 잡힌다 — 본문에서
            # Name 으로 등장하면 그 핸들러는 잉여 인자를 실제로 쓴다.
            used = any(isinstance(node, ast.Name) and node.id == name
                       for node in ast.walk(tree))
            sink = None if used else name
    except Exception:
        # 소스를 못 읽으면 아무 말도 하지 않는다 — 근거 없는 경고보다 낫다.
        sink = None

    _KWARG_SINK_CACHE[code] = sink
    return sink


def _dispatch_virtual_tool(tool_name, arguments):
    """Map a virtual tool name to its AoTDataToolService handler.

    Derives the dispatch table from the SSOT tool registry (build_tool_map) so
    EVERY declared virtual tool — search_notes, create_note, list_notices,
    get_cumulative_status, … — is executable here, not just a hand-maintained
    subset. The old explicit dict omitted several tools that tools/list still
    advertised (via VIRTUAL_TOOLS), so an external MCP client calling e.g.
    search_notes got 'Unknown tool' despite the tool being listed. Registering a
    tool once in tool_registry.py now suffices for both list and execute.
    """
    from aot.tools.tool_registry import build_tool_map

    tool_map = build_tool_map()
    handler = tool_map.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: '{tool_name}'")

    # Strip transport/meta keys the handler signatures don't accept. _execute_tool
    # already removes the gate's own meta keys, but this stays defensive for any
    # caller that reaches this helper directly.
    from aot.tools.mcp_safety_gate import META_KEYS
    _meta = {"tool_name", "server_id", "agent_unique_id", "context"} | set(META_KEYS)
    kwargs = {k: v for k, v in (arguments or {}).items() if k not in _meta}

    # 시그니처에 없는 인자는 버린다. 외부 AI는 잉여 인자를 흔히 실어 보내는데,
    # **extra 를 받지 않는 핸들러(get_energy_report 등)는 TypeError 로 죽어버려
    # 도구가 통째로 못 쓰이게 된다.
    # 다만 조용히 버리지는 않는다 — 'zone' 을 'zone_id' 로 잘못 쓴 경우를 감추면
    # 엉뚱한 범위의 답을 정답으로 오해하게 되므로, 무엇을 무시했는지 돌려준다.
    ignored = []
    try:
        import inspect
        params = inspect.signature(handler).parameters
        if not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            ignored = sorted(k for k in kwargs if k not in params)
            for k in ignored:
                kwargs.pop(k, None)
        elif _discarded_kwarg_sink(handler):
            # `**extra` 가 있어도 그 자리를 **쓰지 않는** 핸들러라면 잉여 키는
            # 조용히 사라진다 — 오타로 필터가 빠진 것과 구분이 안 된다.
            # 넘기는 것은 그대로 넘긴다(핸들러가 흡수하므로 동작은 안 바뀐다).
            # 바뀌는 것은 **말해 준다**는 것뿐이다.
            ignored = sorted(k for k in kwargs if k not in params)
    except (TypeError, ValueError):
        pass

    # 필수 인자가 아예 빠지면 여기서 잡는다. 그러지 않으면 `handler(**kwargs)`
    # 가 곧장 raw `TypeError` 를 내고, 그게 `_execute_tool` 의 바깥 except 에
    # 잡혀 응답에 그대로 실린다 — "AoTDataToolService.resolve_target_tool()
    # missing 1 required positional argument: 'target_name'" 처럼 내부 클래스명
    # ·메서드명이 노출된다(2026-09-16 실측: `resolve_target` 을 잘못된 인자명
    # `query` 로, `get_sensor_detail` 을 `device_id` 로 호출했을 때 재현,
    # mcp_tool_audit_tracker.md #19). 위의 '알 수 없는 인자를 조용히 무시'와
    # 대칭인 반대쪽 실패 모드라 같은 자리에서 함께 정리한다.
    try:
        import inspect as _inspect
        _sig_params = _inspect.signature(handler).parameters
        _missing = [
            name for name, p in _sig_params.items()
            if p.default is _inspect.Parameter.empty
            and p.kind in (_inspect.Parameter.POSITIONAL_OR_KEYWORD,
                           _inspect.Parameter.KEYWORD_ONLY)
            and name not in kwargs
        ]
    except (TypeError, ValueError):
        _missing = []
    if _missing:
        return {
            "status": "error",
            "message": (
                f"Missing required argument(s) for '{tool_name}': "
                f"{', '.join(_missing)}. Received: "
                f"{', '.join(sorted(kwargs.keys())) or '(none)'}. "
                f"Check this tool's input schema in tools/list for the "
                f"exact parameter names — a near-miss name (e.g. 'query' instead of "
                f"'target_name') is silently NOT what you meant."),
        }

    result = handler(**kwargs)
    if ignored and isinstance(result, dict):
        result = dict(result)
        result["_ignored_arguments"] = ignored
        result["_ignored_note"] = (
            f"이 도구가 받지 않는 인자를 무시했습니다: {', '.join(ignored)}. "
            f"의도한 인자였다면 tools/list 의 input_schema 에서 정확한 이름을 확인하세요.")
    return result


# =============================================================================
# stdio transport — JSON-RPC 2.0 over stdin/stdout
# =============================================================================


# ── 내부 AI 진입점 ────────────────────────────────────────────────────────────
# 외부 AI 는 MCP 서버(전송)를 지나 여기 닿고, 내부 AI 는 여기를 **직접** 부른다.
# 같은 게이트를 지나므로 승인·감사·응답 캡이 양쪽에서 동일하다.

def execute_for_agent(app, tool_name, arguments, agent_unique_id=None,
                      server_id=None, scope_user_uuid=None, session_key=None):
    """내부 AI 의 도구 호출. 반환 형식은 `MCPBridgeService.call_tool` 과 같다.

    리졸버가 그 형식을 기대하므로 맞춘다 — 호출 방식이 바뀐 것이지 계약이
    바뀐 것은 아니다.

    신원이 두 갈래인 것에 주의:
      - **권한**(role)은 서비스 계정 `aot-system` 에서 온다. MCP 로 붙을 때
        `AOT_MCP_API_KEY` 가 가리키던 바로 그 계정이라 권한 범위가 그대로다.
      - **감사 로그의 주체**(agent_id)는 호출한 AI 에이전트다. 예전에는 MCP
        인증이 서비스 계정 하나뿐이라 모든 내부 호출이 같은 이름으로 남았는데,
        이제 어느 에이전트가 불렀는지 구분된다.
    """
    from aot.tools import mcp_auth

    # ACL 은 브리지의 것을 그대로 쓴다. 규칙을 두 벌 만들면 갈라지고, 갈라지면
    # **느슨한 쪽이 실질 권한**이 된다(매핑이 없으면 기본 거부라 더더욱).
    if server_id:
        from aot.tools import providers
        if not providers.get('tool_access_allowed')(agent_unique_id, server_id,
                                                     tool_name):
            return {"status": "error",
                    "message": "Access denied: tool '%s' not permitted." % tool_name}

    with app.app_context() if not _in_app_context() else _nullcontext():
        try:
            user = mcp_auth.ensure_service_account()
            role = mcp_auth._role_for(user)
        except Exception as exc:
            logger.warning("[tool_execution] 서비스 계정 조회 실패: %s", exc)
            role = None

    # 그룹 스코프(A2) — 신원은 **요청을 낸 사람**이다(설계 §6-2).
    #
    # 호출자가 명시하지 않으면 요청 컨텍스트에서 찾는다. 인앱 채팅은 실제
    # Flask 요청 안에서 돌므로 여기서 사람이 잡히고, 백그라운드 AI 잡은
    # app_context 만 갖고 요청 컨텍스트가 없으므로 `None` — 즉 **사람이 없는
    # 호출**이라 면제다(§6-1 데몬과 같은 근거).
    #
    # ⚠ `role` 을 신원으로 쓰지 않는 이유는 `_scope_refusal` 주석 참조 —
    # 그 역할은 서비스 계정 `aot-system` 에서 온다.
    #
    # 부른 쪽(인앱 AI 의 MCP 리졸버)은 **요청자 표지**의 uuid 를 넘긴다 —
    # 계획 실행기의 워커 스레드처럼 요청 컨텍스트가 없는 곳에서도 사람이
    # 보이게 하려는 것이다(이 모듈은 aot.ai 를 import 하지 않으므로 받기만
    # 한다). 넘기지 않았을 때만 요청 컨텍스트에서 찾는다.
    if scope_user_uuid is None:
        scope_user_uuid = _current_request_user_uuid()

    # session_key: 부른 쪽이 넘긴 대화 번호(인앱 채팅의 thread_id). 이 모듈은
    # aot.ai 를 import 하지 않으므로(tools-no-ai) 직접 찾지 않고 받기만 한다.
    content = _execute_tool(app, tool_name, arguments,
                            agent_id=agent_unique_id or "internal-ai", role=role,
                            scope_user_uuid=scope_user_uuid,
                            transport="in_app", session_key=session_key)
    try:
        result = json.loads(content[0]["text"])
    except Exception:
        return {"status": "error", "message": "tool returned no parsable result"}

    # 게이트가 막았거나 도구가 실패한 것은 **성공이 아니다.** call_state 가
    # 그 판정의 정본이다(도구별 status 어휘는 12종이라 믿을 수 없다).
    state = result.get("call_state")
    from aot.tools import mcp_safety_gate as gate
    performed = result.get("performed")
    # 이번 호출에서 쓰기는 됐는데(executed) 실행 중인 제어기가 받았는지 모르는
    # 경우(함수 켜기/끄기의 데몬 무응답) — 저장은 사실이므로 실패로 싸지 않는다.
    # 물리 명령의 "모름" 은 call_state 가 failed·already_executed 라 여기 오지 않는다.
    runtime_unknown = (state == "executed"
                       and performed == gate.PERFORMED_UNKNOWN)
    if not runtime_unknown and (
            state not in ("executed", "already_executed") or
            performed in (False, gate.PERFORMED_UNKNOWN)):
        out = {"status": "error", "message": result.get("message") or state,
               "result": result}
        # 인앱 AI 도 MCP 와 같은 판정을 맨 위에서 본다(안쪽 result 에도 있다).
        # "unknown" 은 물리 명령이 나갔을 수 있다는 뜻이다 — 실패로 싸되 그대로 싣는다.
        if performed in (False, gate.PERFORMED_UNKNOWN):
            out["performed"] = performed
        return out
    if runtime_unknown:
        return {"status": "success", "performed": performed, "result": result}
    return {"status": "success", "result": result}


def tools_for_agent(app):
    """내부 AI 가 볼 도구 목록. MCP `tools/list` 와 **같은 원천**이다.

    권한은 서비스 계정 기준이라, 외부에서 같은 계정으로 붙었을 때와 목록이
    같다 — 한쪽에만 보이는 도구가 생기면 그쪽만 검증되지 않은 채 남는다.
    """
    from aot.tools import mcp_auth
    try:
        role = mcp_auth._role_for(mcp_auth.ensure_service_account())
    except Exception as exc:
        logger.warning("[tool_execution] 목록용 역할 조회 실패: %s", exc)
        role = None
    return _get_all_tools(app, role=role, tiered=_builtin_tiering_enabled())


def _in_app_context():
    from flask import has_app_context
    return has_app_context()


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False
