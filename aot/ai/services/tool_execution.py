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
import json
import logging
import os
import socket

logger = logging.getLogger(__name__)

# 응답에 실려 나가는 인스턴스 식별자. 같은 사용자가 여러 AoT 의 MCP 를 동시에
# 붙였을 때 어느 쪽이 답했는지 구분한다.
SERVER_HOST = socket.gethostname()


def _server_instructions():
    """initialize 응답의 result.instructions.

    도구 설명이 아니라 여기 한 곳에 적어 두면 모든 클라이언트/세션에 일관되게
    반영된다. **서랍 안내를 여기 싣는 것이 중요하다** — tools/list 만 본 LLM 은
    거기 없는 기능을 "이 시스템은 못 한다" 로 결론짓는다. 그 실패는 에러가
    아니라 조용한 오답이라 로그에도 안 남는다. 서랍 이름은 DRAWERS 에서 만들어
    목록이 코드와 어긋나지 않게 한다.
    """
    base = (
        "When reporting results to the user, never surface raw unique_id/note_id "
        "UUIDs. Most lookup tools here return both a human-readable name (zone, "
        "crop, device, etc.) and its unique_id — refer to the entity by name "
        "instead. Only include the raw id if the user explicitly asks for it."
    )
    try:
        from aot.ai.services.tool_registry import DRAWERS
    except Exception:
        return base
    if not _tiering_enabled():
        return base
    drawers = "; ".join("%s (%s)" % (name, desc) for name, desc in DRAWERS.items())
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
_TIER_EXEMPT_TOOLS = frozenset({
    _CONFIRMATION_RESPONSE_TOOL, "open_drawer", "get_tool_detail", "use_tool"})


def _tiering_enabled():
    """서랍 적용 여부. **기본은 켜짐이다.**

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
    """
    return os.environ.get("AOT_MCP_TOOL_TIERING", "1") != "0"


def _drawer_index(app, role=None):
    """서랍 목록 — 이 표면이 실제로 가진 도구만.

    원천은 _get_all_tools 다. tool_registry 의 매니페스트로 인덱스를 만들면
    네이티브 도구가 빠지고 카탈로그에 없는 이름이 섞여, 열어도 안 나오는
    이름을 광고하게 된다.
    """
    from aot.ai.services.tool_registry import drawer_index
    names = _drawer_contents(app, role=role)
    return [d for d in drawer_index(available=names) if d["tools"]]


def _drawer_contents(app, role=None):
    """서랍에 담길 수 있는 도구 이름 — 전체 표면에서 **상시 노출을 뺀 것**.

    면제 도구를 빼지 않으면 이미 tools/list 에 있는 것이 서랍에도 보인다.
    그러면 LLM 은 손에 든 도구를 쓰려고 서랍을 한 번 더 여는데, 그 왕복이
    정확히 서랍이 없애려던 비용이다(respond_to_confirmation 이 실제로 그렇게
    보였다 — core 가 아니라 면제라서 등급 검사만으로는 안 걸러진다).
    """
    return _exclude_always_listed(
        {t["name"] for t in _get_all_tools(app, role=role, tiered=False)})


def _exclude_always_listed(names):
    """서랍에 담길 수 있는 이름 = 전체 − 상시 노출. (순수 함수 — 앱이 필요 없다.)

    앱 없이 부를 수 있게 떼어 둔다. 이 규칙이 깨지는 것은 조용한 실패라
    검사로 고정해야 하는데, `_get_all_tools` 는 DB 를 읽으므로 그대로는
    검사에서 부를 수 없다.
    """
    return {n for n in names if n not in _TIER_EXEMPT_TOOLS}


def _open_drawer(app, arguments, role=None):
    """서랍 하나를 열어 그 안 도구들의 완전한 정의를 돌려준다.

    모르는 이름이면 **오류로 끝내지 않고 목록을 함께 준다** — "없다"로 끝내면
    LLM 이 포기하는데, 목록을 주면 다시 고른다.
    """
    from aot.ai.services.tool_registry import DRAWERS, tools_in_drawer

    drawer = (arguments or {}).get("drawer")
    index = _drawer_index(app, role=role)
    if not drawer or drawer not in DRAWERS:
        return {
            "error": ("unknown drawer: %s" % drawer) if drawer else "drawer is required",
            "drawers": index,
        }

    every = {t["name"]: t for t in _get_all_tools(app, role=role, tiered=False)}
    names = tools_in_drawer(drawer, available=_drawer_contents(app, role=role))
    tools = [every[n] for n in names]
    return {
        "drawer": drawer,
        "description": DRAWERS[drawer],
        "count": len(tools),
        "tools": tools,
        "how_to_call": ("These tools are not in tools/list. Call one by passing its "
                        "name and arguments to use_tool, e.g. "
                        "use_tool({tool_name: '<name>', arguments: {...}})."),
    }


def _get_tool_detail(app, arguments, role=None):
    """도구 하나의 완전한 정의. 서랍 인덱스가 준 이름을 확인하는 자리."""
    name = (arguments or {}).get("tool_name")
    if not name:
        return {"error": "tool_name is required"}
    name = str(name).strip()
    for t in _get_all_tools(app, role=role, tiered=False):
        if t["name"] == name:
            return {"tool": t, "how_to_call": (
                "Call it via use_tool({tool_name: '%s', arguments: {...}}) "
                "unless it is already listed in tools/list." % name)}
    return {"error": "Unknown tool: %s" % name, "drawers": _drawer_index(app, role=role)}


# =============================================================================
# Tool registry
# =============================================================================

def _get_all_tools(app, role=None, tiered=None):
    """Return merged list of VIRTUAL_TOOLS + AoTNativeToolEngine tools.

    Priority: VIRTUAL_TOOLS first (richer descriptions), then native tools
    not already present by name.

    `role` is whatever mcp_auth.authenticate_http/authenticate_stdio resolved
    (a Role row, or None for unauthenticated). Tools classified mutating/physical
    in tool_registry (tool_registry.approval_required_tools()) are left out of the
    list for callers without write access — this is advisory (it just shapes what
    tools/list advertises); the actual enforcement is mcp_safety_gate.gate()'s own
    role check, so hiding a tool here is a UX nicety, not the security boundary.

    `tiered` selects whether the drawer split applies (None = follow
    _tiering_enabled()). Pass False to get the COMPLETE surface — that is what
    the drawer machinery itself reads, so that what tools/list advertises and
    what a drawer can hand out are always derived from the same list. Role
    filtering still applies in both cases; a read-only key must not be able to
    discover write tools through a drawer either.
    """
    from aot.ai.services.mcp_auth import role_can_write
    from aot.ai.services.tool_registry import approval_required_tools, tier_of

    hidden = frozenset() if role_can_write(role) else approval_required_tools()
    if tiered is None:
        tiered = _tiering_enabled()

    def _in_drawer(name):
        return (tiered
                and name not in _TIER_EXEMPT_TOOLS
                and tier_of(name)[1] != 'core')

    tools = []

    # 1. VIRTUAL_TOOLS from mcp_aot.py
    try:
        from aot.ai.agents.mcp_aot import VIRTUAL_TOOLS
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
            from aot.ai.services.aot_native_tool_engine import AoTNativeToolEngine
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
        if et["name"] in hidden or et["name"] in existing:
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
_MAX_RESPONSE_TOKENS = int(os.environ.get("AOT_MCP_MAX_RESPONSE_TOKENS", "20000"))


# ASCII 계열 몇 글자를 1토큰으로 셀 것인가. 영어 산문의 통념은 4지만 **여기서
# 재는 것은 JSON 이다** — 중괄호·따옴표·콜론·이스케이프가 촘촘해 같은 글자 수라도
# 토큰이 더 나온다. 실측으로 3을 골랐다(2026-08-21): 상한 초과로 실제 거부된
# 응답(89,672자 / CJK 937자)이 4자 기준으로는 23,120토큰이라 25,000 상한 아래로
# 보였고 — 즉 **위험한 쪽으로 빗나갔다** — 3자 기준으로는 30,515토큰이 되어
# 거부된 사실과 맞는다. 추정이 틀릴 때는 반드시 큰 쪽으로 틀려야 한다: 작게
# 잡으면 캡이 통과시킨 응답을 호스트가 버리는데, 그 실패는 서버에 안 보인다.
_CHARS_PER_TOKEN_ASCII = 3


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
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, list) and len(v) > 1 and not k.endswith("_truncated"):
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


def _cap_result(result, tool_name, max_tokens=None):
    """응답을 클라이언트 상한 아래로 줄인다. 이미 작으면 그대로 돌려준다.

    result 를 제자리에서 고친다 — 감사 로그는 이 앞에서 이미 원본을 기록했으므로
    (진단에는 잘리지 않은 것이 필요하다) 여기서 복사할 이유가 없고, 큰 응답을
    복사하면 그 순간 메모리를 두 배로 쓴다.
    """
    # `or` 로 쓰면 0(=끄기)이 falsy 라 기본값으로 되살아난다 — 끄는 수단이
    # 조용히 사라진다.
    if max_tokens is None:
        max_tokens = _MAX_RESPONSE_TOKENS
    if max_tokens <= 0 or not isinstance(result, dict):
        return result

    text = json.dumps(result, ensure_ascii=False)
    total = _estimate_tokens(text)
    if total <= max_tokens:
        return result

    original = total
    # 잘랐다는 안내(_truncated + 슬롯별 형제 키)도 응답에 실린다. 목표를 상한에
    # 딱 맞추면 그 안내를 붙이는 순간 다시 넘을 수 있으므로 자리를 비워 둔다.
    target = max(1, max_tokens - 400)
    dropped = []
    for _ in range(24):
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
        original_len = next((d["total"] for d in dropped if d["path"] == path), len(lst))
        parent[key] = lst[:keep]
        parent[key + "_truncated"] = (
            "showing first %d of %d — the response exceeded the client's size limit. "
            "Re-run with a narrower scope (a filter, a limit, or a single target) "
            "to see the rest." % (keep, original_len))
        dropped = [d for d in dropped if d["path"] != path]
        dropped.append({"path": path, "kept": keep, "total": original_len})

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
        result["_truncated"] = {
            "reason": "response exceeded the MCP response size limit",
            "estimated_tokens_before": original,
            "estimated_tokens_after": total,
            "limit": max_tokens,
            "lists_trimmed": dropped,
            "advice": ("This result is INCOMPLETE. Do not describe it as the full "
                       "picture — narrow the query and call again for the rest."),
        }
    return result


def _execute_tool(app, tool_name, arguments, agent_id="unknown", role=None, elicit_fn=None):
    """Execute a named tool and return MCP-format content list.

    Every call — read or write, executed or refused — is recorded in
    mcp_audit_log with the calling agent's identity and its stated reason, so a
    multi-AI setup (main AoT AI / external AI / subordinate node AI) can be told
    apart after the fact. Write tools do not execute until a human approves them
    (see aot/ai/services/mcp_safety_gate.py); the gate returns the response body
    to hand back instead.

    elicit_fn: optional callable(tool_name, briefing_message, arguments) -> True
        (human approved) / False (declined) / None (elicitation unavailable or
        failed, fall back to the async confirmation queue). Only the stdio
        transport can supply this — it needs a live, bidirectional connection
        to send the client a mid-call 'elicitation/create' request and block
        for its reply, which a stateless HTTP request/response cycle cannot
        do. See StdioMCPServer._elicit_decision.

    Returns:
        list[dict]: MCP content blocks, e.g. [{"type": "text", "text": "..."}]
    """
    from aot.ai.services import mcp_safety_gate as gate
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
        return _execute_tool(app, inner, merged, agent_id=agent_id,
                             role=role, elicit_fn=elicit_fn)
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
        try:
            if tool_name == "open_drawer":
                # 서랍 열기/스키마 조회는 읽기이고, 게이트가 아는 도구도 아니다
                # (tool_registry 의 동명 핸들러는 내부 AI 표면용이라 카탈로그가
                # 다르다 — 이 표면의 원천은 _get_all_tools 하나뿐이어야 한다).
                result = _open_drawer(app, arguments, role=role)
            elif tool_name == "get_tool_detail":
                result = _get_tool_detail(app, arguments, role=role)
            elif tool_name == _CONFIRMATION_RESPONSE_TOOL:
                # 승인 큐 응답 자체는 게이트를 거치지 않는다 — "승인하려면 승인이
                # 필요하다"는 순환을 피하기 위함. 대신 role 체크는 여기서 직접 한다.
                result = _respond_to_confirmation(arguments, agent_id, role)
            else:
                blocked = gate.gate(tool_name, arguments, agent_id=agent_id, role=role,
                                    reason=reason, elicit_fn=elicit_fn)
                if blocked is None:
                    call_args = gate.inject_agent(
                        tool_name, gate.strip_meta(arguments), agent_id)
                    if tool_name in _NATIVE_TOOLS:
                        from aot.ai.services.aot_native_tool_engine import AoTNativeToolEngine
                        result = AoTNativeToolEngine.execute(tool_name, call_args)
                    else:
                        result = _dispatch_virtual_tool(tool_name, call_args)
                else:
                    result = blocked
        except ValueError as exc:
            error_text = str(exc)
            result = {"status": "error", "message": error_text}
        except Exception as exc:
            error_text = str(exc)
            logger.error(f"[AoTMCP] Tool '{tool_name}' failed: {exc}", exc_info=True)
            result = {"status": "error", "message": error_text}

        _record_audit(audit, tool_name, arguments, agent_id, permission,
                      reason, blocked, result, error_text)

    if isinstance(result, dict):
        result.setdefault("server_host", SERVER_HOST)
        # 호출이 실제로 돌았는지를 도구별 어휘와 무관하게 한 키로 알린다.
        # 여기가 stdio/HTTP 양쪽이 반드시 지나는 단일 지점이라 한 번만 찍으면 된다.
        result["call_state"] = gate.call_state(blocked, result, error_text)
        # 감사 기록(위)이 끝난 뒤에 줄인다 — 진단에는 잘리지 않은 원본이 필요하다.
        result = _cap_result(result, tool_name)
    return [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]


def _tool_error(message):
    """MCP content 포맷의 오류 응답. use_tool 의 인자 검증처럼 감사 대상 실행에
    도달하지도 못한 경우에 쓴다 — 이 자리에서는 아직 어떤 도구도 돌지 않았다."""
    return [{"type": "text", "text": json.dumps(
        {"status": "error", "message": message, "call_state": "refused",
         "server_host": SERVER_HOST}, ensure_ascii=False)}]


def _record_audit(audit, tool_name, arguments, agent_id, permission,
                  reason, blocked, result, error_text):
    """Write one mcp_audit_log row describing this call's outcome.

    Never raises: an audit failure must not turn a working tool call into an
    error for the caller (the audit helpers already swallow and log their own
    exceptions, but the status mapping below is ours).
    """
    try:
        from aot.ai.services import mcp_safety_gate as gate
        confirmation_id = (blocked or {}).get("confirmation_id")
        uid = audit.log_call(
            tool_name=tool_name,
            params=arguments,
            agent_id=agent_id,
            permission=permission,
            reason=reason,
            confirmation_id=confirmation_id,
        )
        if permission == "read":
            status = "n/a"
        elif blocked is None and tool_name in gate.config_only_tools():
            # 승인이 면제된 설정 편집. 'approved' 로 적으면 아무도 보지 않은
            # 동작을 사람이 승인한 것처럼 남는다 — 안전 감사 로그에서 그건
            # 거짓이다. 승인이 애초에 요구되지 않았음을 그대로 적는다.
            status = "not_required"
        elif blocked is None:
            status = "approved"          # gate consumed a human approval
        elif blocked.get("status") == "pending_approval":
            status = "pending"
        else:
            status = "rejected"
        summary = (blocked or {}).get("reason_code") or (
            "" if error_text else str(result.get("status", ""))[:100])
        audit.update_status(uid, status, result_summary=summary, error=error_text)
    except Exception:
        logger.exception("[AoTMCP] audit record failed for '%s'", tool_name)


def _respond_to_confirmation(arguments, agent_id, role):
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
    """
    from aot.ai.services import mcp_auth
    if not mcp_auth.role_can_write(role):
        return {
            "status": "refused",
            "reason_code": "insufficient_role",
            "message": ("Your MCP key's role does not have write access — only "
                        "Admin/Editor role keys can approve or reject pending "
                        "confirmations."),
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

    from aot.ai.services import mcp_safety_gate as gate
    user_id = getattr(role, "user_id", None)
    results = []
    for cid in confirmation_ids:
        if decision == "approve":
            r = gate.approve(cid, user_id=user_id)
        else:
            r = gate.reject(cid, user_id=user_id)
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
    from aot.ai.services.tool_registry import build_tool_map

    tool_map = build_tool_map()
    handler = tool_map.get(tool_name)
    if handler is None:
        raise ValueError(f"Unknown tool: '{tool_name}'")

    # Strip transport/meta keys the handler signatures don't accept. _execute_tool
    # already removes the gate's own meta keys, but this stays defensive for any
    # caller that reaches this helper directly.
    from aot.ai.services.mcp_safety_gate import META_KEYS
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
    except (TypeError, ValueError):
        pass

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
                      server_id=None):
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
    from aot.ai.services import mcp_auth

    # ACL 은 브리지의 것을 그대로 쓴다. 규칙을 두 벌 만들면 갈라지고, 갈라지면
    # **느슨한 쪽이 실질 권한**이 된다(매핑이 없으면 기본 거부라 더더욱).
    if server_id:
        from aot.ai.services.mcp_bridge_service import MCPBridgeService
        if not MCPBridgeService._check_tool_access(agent_unique_id, server_id,
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

    content = _execute_tool(app, tool_name, arguments,
                            agent_id=agent_unique_id or "internal-ai", role=role)
    try:
        result = json.loads(content[0]["text"])
    except Exception:
        return {"status": "error", "message": "tool returned no parsable result"}

    # 게이트가 막았거나 도구가 실패한 것은 **성공이 아니다.** call_state 가
    # 그 판정의 정본이다(도구별 status 어휘는 12종이라 믿을 수 없다).
    state = result.get("call_state")
    if state not in ("executed", "already_executed"):
        return {"status": "error", "message": result.get("message") or state,
                "result": result}
    return {"status": "success", "result": result}


def tools_for_agent(app):
    """내부 AI 가 볼 도구 목록. MCP `tools/list` 와 **같은 원천**이다.

    권한은 서비스 계정 기준이라, 외부에서 같은 계정으로 붙었을 때와 목록이
    같다 — 한쪽에만 보이는 도구가 생기면 그쪽만 검증되지 않은 채 남는다.
    """
    from aot.ai.services import mcp_auth
    try:
        role = mcp_auth._role_for(mcp_auth.ensure_service_account())
    except Exception as exc:
        logger.warning("[tool_execution] 목록용 역할 조회 실패: %s", exc)
        role = None
    return _get_all_tools(app, role=role)


def _in_app_context():
    from flask import has_app_context
    return has_app_context()


class _nullcontext:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False
