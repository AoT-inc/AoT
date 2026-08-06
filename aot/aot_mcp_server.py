#!/usr/bin/env python3
# coding=utf-8
"""
AoT MCP Server — Standalone Model Context Protocol server.

Exposes all AoT native tools (sensor queries, device control, spatial data,
schedules, energy reports) via the MCP protocol (2024-11-05).

Dual-mode transport:
  stdio (default) : JSON-RPC 2.0 over stdin/stdout.
                    For local AI clients (Claude Desktop, etc.)
  http  (--http)  : REST API on configurable port (default: 5700).
                    For remote AI clients over the network.

Usage:
  python3 aot_mcp_server.py                    # stdio mode
  python3 aot_mcp_server.py --http             # HTTP mode, port 5700
  python3 aot_mcp_server.py --http --port 5800 # HTTP mode, custom port

Claude Desktop stdio config:
  {
    "mcpServers": {
      "aot": {
        "command": "python3",
        "args": ["/opt/AoT/aot/aot_mcp_server.py"]
      }
    }
  }
"""

import sys
import os
import json
import logging
import argparse
import socket

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# Ensure /opt/AoT is on sys.path so AoT modules can be imported regardless
# of where this script is invoked from.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_INSTALL_DIR = os.path.dirname(_SCRIPT_DIR)  # /opt/AoT
if _INSTALL_DIR not in sys.path:
    sys.path.insert(0, _INSTALL_DIR)

logger = logging.getLogger("aot_mcp_server")

# ── MCP protocol constants ─────────────────────────────────────────────────────
PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "aot-mcp-server"
SERVER_VERSION = "1.0.0"
# 동일 사용자가 여러 AoT 인스턴스의 MCP 서버를 동시에 붙였을 때 응답을 구분할 수
# 있도록, 관리자가 별도로 설정하지 않아도 프로세스 호스트명을 자동으로 싣는다.
SERVER_HOST = socket.gethostname()

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
]


# =============================================================================
# Tool registry
# =============================================================================

def _get_all_tools(app, role=None):
    """Return merged list of VIRTUAL_TOOLS + AoTNativeToolEngine tools.

    Priority: VIRTUAL_TOOLS first (richer descriptions), then native tools
    not already present by name.

    `role` is whatever mcp_auth.authenticate_http/authenticate_stdio resolved
    (a Role row, or None for unauthenticated). Tools classified mutating/physical
    in tool_registry (tool_registry.approval_required_tools()) are left out of the
    list for callers without write access — this is advisory (it just shapes what
    tools/list advertises); the actual enforcement is mcp_safety_gate.gate()'s own
    role check, so hiding a tool here is a UX nicety, not the security boundary.
    """
    from aot.ai.services.mcp_auth import role_can_write
    from aot.ai.services.tool_registry import approval_required_tools

    hidden = frozenset() if role_can_write(role) else approval_required_tools()

    tools = []

    # 1. VIRTUAL_TOOLS from mcp_aot.py
    try:
        from aot.ai.agents.mcp_aot import VIRTUAL_TOOLS
        for vt in VIRTUAL_TOOLS:
            if vt["tool_name"] in hidden:
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
                if nt["name"] in hidden:
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
            if tool_name == _CONFIRMATION_RESPONSE_TOOL:
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
    return [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]


def _record_audit(audit, tool_name, arguments, agent_id, permission,
                  reason, blocked, result, error_text):
    """Write one mcp_audit_log row describing this call's outcome.

    Never raises: an audit failure must not turn a working tool call into an
    error for the caller (the audit helpers already swallow and log their own
    exceptions, but the status mapping below is ours).
    """
    try:
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

class StdioMCPServer:
    """Reads JSON-RPC requests from stdin, writes responses to stdout.

    Follows MCP protocol 2024-11-05:
      1. initialize       → capabilities handshake
      2. notifications/initialized → client ready signal
      3. tools/list       → return all available tools
      4. tools/call       → execute tool and return result
    """

    def __init__(self, app):
        self._app = app
        self._initialized = False
        # Identity of the connected client, taken from the initialize handshake's
        # clientInfo.name. Recorded on every call so a multi-AI setup can be
        # attributed (which AI asked for this?).
        self._agent_id = "unknown"
        # 인증된 호출자의 Role 행(mcp_auth._role_for). None = 조회 전용 취급.
        self._role = None
        # initialize 에서 인증에 성공해야 True. 실패하면 tools/* 를 거부한다.
        self._authed = False
        # 클라이언트가 initialize에서 capabilities.elicitation을 선언했는가.
        # 참이면 쓰기 도구 승인을 비동기 큐 대신 실시간 elicitation으로 처리한다
        # (2026-07-26 확인: Claude Code는 이 capability를 선언한다).
        self._supports_elicitation = False
        self._next_elicit_id = 0

    def _send(self, obj):
        """Write a JSON-RPC response line to stdout."""
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def _elicit_decision(self, tool_name, briefing, arguments):
        """Send a server-initiated 'elicitation/create' request over this same
        stdio connection and block for the client's reply. The client (e.g.
        Claude Code) shows ITS OWN native prompt UI to the human and returns
        their answer directly — the calling LLM has no path to fabricate or
        infer this reply, unlike the old 'call respond_to_confirmation
        yourself' flow.

        Returns True (approve) / False (decline or cancel) / None (no
        elicitation support, malformed reply, or any failure — caller should
        fall back to the async confirmation queue instead of blocking
        forever or guessing).
        """
        if not self._supports_elicitation:
            return None
        self._next_elicit_id += 1
        req_id = f"elicit-{self._next_elicit_id}"
        message = f"[{tool_name}] Approve this action?"
        if briefing:
            message += "\n\n" + briefing
        try:
            self._send({
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "elicitation/create",
                "params": {
                    "message": message,
                    "requestedSchema": {
                        "type": "object",
                        "properties": {
                            "decision": {
                                "type": "string",
                                "enum": ["approve", "reject"],
                                "title": "Decision",
                                "description": "Approve or reject this AI tool request.",
                            }
                        },
                        "required": ["decision"],
                    },
                },
            })
            raw = sys.stdin.readline()
            if not raw:
                return None
            resp = json.loads(raw.strip())
            if resp.get("id") != req_id:
                # Some other message arrived instead of the elicitation reply
                # (should not normally happen on a single-client stdio pipe) -
                # don't guess, fall back to the async queue.
                logger.warning("[AoTMCP] elicitation reply id mismatch — falling back to queue")
                return None
            result = resp.get("result") or {}
            action = result.get("action")
            # Confirmed 2026-07-26 (raw reply captured): a non-interactive
            # session replies {"action": "cancel"} - the client could not
            # present this to a human at all (no live interactive channel),
            # NOT a person clicking away. Only "decline" is a real human
            # answer; "cancel" (or anything else unrecognized) must fall back
            # to the async queue, or every non-interactive session would have
            # its writes silently hard-blocked with nothing a human could
            # ever approve.
            if action == "decline":
                return False
            if action != "accept":
                return None
            content = result.get("content") or {}
            return content.get("decision") == "approve"
        except Exception:
            logger.exception("[AoTMCP] elicitation exchange failed")
            return None

    def _handle(self, msg):
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            client = (params or {}).get("clientInfo") or {}
            declared = client.get("name") or "unknown"
            self._supports_elicitation = bool(
                ((params or {}).get("capabilities") or {}).get("elicitation") is not None)
            logger.info(f"[AoTMCP] client={declared} supports_elicitation="
                       f"{self._supports_elicitation}")
            # stdio 는 클라이언트가 프로세스를 spawn 하는 구조지만, 정책을 켜면
            # HTTP 와 동일하게 키를 요구한다(키는 클라이언트 설정의 env 로 전달).
            from aot.ai.services import mcp_auth
            with self._app.app_context():
                ok, agent_id, role, err = mcp_auth.authenticate_stdio(declared)
            if not ok:
                self._authed = False
                logger.warning(f"[AoTMCP] stdio 인증 실패: {err.get('message')}")
                self._send({"jsonrpc": "2.0", "id": msg_id,
                            "error": {"code": -32001, "message": err.get("message")}})
                return
            self._authed = True
            self._agent_id = agent_id
            self._role = role
            logger.info(f"[AoTMCP] Client identified as '{self._agent_id}' "
                        f"(role={getattr(role, 'name', None)})")
            self._send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION,
                                   "host": SERVER_HOST},
                },
            })

        elif method == "notifications/initialized":
            self._initialized = True
            logger.info("[AoTMCP] Client initialized — ready to serve tools.")

        elif method in ("tools/list", "tools/call") and not self._authed:
            self._send({"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32001,
                                  "message": "인증되지 않은 세션입니다. initialize 를 먼저 수행하세요."}})

        elif method == "tools/list":
            tools = _get_all_tools(self._app, role=self._role)
            self._send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                # elicit_fn 비활성화 (2026-07-26 실증): 클라이언트가 initialize에서
                # capabilities.elicitation을 선언해도, 실제로 사람에게 네이티브
                # 대화상자를 띄워준다는 보장이 없다 — 확인된 사례에서는 대화상자
                # 없이 곧장 "decline"을 합성 응답해, 최초 호출부터 진짜 사람 승인
                # 기회조차 없이 거부로 끝났다(_elicit_decision이 기대하는
                # cancel/None 폴백이 아니라 decline이 와서 async 큐로도 못 감).
                # 그래서 항상 host-agnostic한 비동기 승인 큐(pending_approval +
                # respond_to_confirmation, 사용자의 실제 채팅 텍스트 승인 기반)만
                # 쓴다. _elicit_decision 자체는 남겨둔다 — 특정 호스트의 elicitation
                # 지원이 검증되면 이 elicit_fn=None을 self._elicit_decision으로
                # 되돌리기만 하면 된다.
                content = _execute_tool(self._app, tool_name, arguments,
                                        agent_id=self._agent_id, role=self._role,
                                        elicit_fn=None)
                self._send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {"content": content},
                })
            except Exception as exc:
                self._send({
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32603, "message": str(exc)},
                })

        elif msg_id is not None:
            self._send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })

    def run(self):
        logger.info("[AoTMCP] stdio mode started. Waiting for JSON-RPC input...")
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                self._handle(msg)
            except json.JSONDecodeError as exc:
                self._send({
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                })


# =============================================================================
# HTTP transport — Flask REST API (MCP-compatible)
# =============================================================================

def _run_http_server(app, port=5700):
    """Serve MCP tools over HTTP REST API.

    Endpoints:
      GET  /mcp/info         → server metadata
      GET  /mcp/tools/list   → all tools
      POST /mcp/tools/call   → {name, arguments} → {content}
    """
    from flask import Flask, request, jsonify
    from aot.ai.services import mcp_auth
    from aot.databases.models import AIGlobalSettings

    http_app = Flask("aot_mcp_http")

    def _http_server_enabled():
        # Checked fresh every request (not cached) so the Settings > General >
        # AI Service toggle takes effect immediately — no restart of this
        # process/container needed. Defaults to enabled if the row doesn't
        # exist yet, matching the column's own default.
        with app.app_context():
            settings = AIGlobalSettings.query.first()
        return settings is None or settings.mcp_http_enabled is not False

    @http_app.before_request
    def _gate_disabled():
        if not _http_server_enabled():
            return jsonify({"error": "External MCP server is disabled in "
                                      "Settings > General > AI Service."}), 503

    @http_app.route("/mcp/info", methods=["GET"])
    def info():
        tools = _get_all_tools(app)
        return jsonify({
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "host": SERVER_HOST,
            "protocol": PROTOCOL_VERSION,
            "tool_count": len(tools),
        })

    @http_app.route("/mcp/tools/list", methods=["GET"])
    def tools_list():
        # 카탈로그도 능력 노출이므로 인증 뒤에 둔다. /mcp/info 만 생존 확인용으로 열어둔다.
        with app.app_context():
            ok, _agent, role, err = mcp_auth.authenticate_http(request.headers)
        if not ok:
            return jsonify(err), 401
        tools = _get_all_tools(app, role=role)
        return jsonify({"tools": tools})

    @http_app.route("/mcp/tools/call", methods=["POST"])
    def tools_call():
        data = request.get_json(silent=True) or {}
        tool_name = data.get("name", "")
        arguments = data.get("arguments", {})
        if not tool_name:
            return jsonify({"error": "Missing 'name' field"}), 400
        # Identity comes from the API key, not from a self-declared header —
        # X-MCP-Agent-Id alone was spoofable, which made the audit trail and the
        # advice ledger's attribution untrustworthy. The header now only
        # annotates which client is using that user's key.
        declared = request.headers.get("X-MCP-Agent-Id") or data.get("agent_id")
        with app.app_context():
            ok, agent_id, role, err = mcp_auth.authenticate_http(request.headers, declared)
        if not ok:
            return jsonify(err), 401
        try:
            content = _execute_tool(app, tool_name, arguments, agent_id=agent_id, role=role)
            return jsonify({"content": content})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    # 바인드 주소. 도커에서는 컨테이너 안에서 0.0.0.0 이어야 compose 의
    # 포트 매핑(`100.111.33.43:5700:5700`)이 노출면을 좁힐 수 있다. 네이티브
    # 설치(install/aotmcp.service)에는 그런 매핑이 없어 0.0.0.0 이 곧 전체
    # 인터페이스 노출이므로, 그쪽은 유닛 파일에서 이 값을 좁혀 쓴다.
    host = os.environ.get('AOT_MCP_HTTP_HOST', '0.0.0.0')

    # Flask 내장 서버(`http_app.run`)는 개발용이라 프로덕션에 쓰지 않는다 —
    # 단일 스레드로 요청을 직렬 처리해서, 도구 하나가 느리면 그 뒤 요청이 전부
    # 밀린다(여기 도구는 DB·InfluxDB 조회라 드문 일이 아니다). waitress 는 이미
    # requirements 에 있고 순수 파이썬이라 추가 설치가 필요 없다. 웹앱 쪽
    # gunicorn 을 쓰지 않는 이유는 이 Flask 앱이 모듈 전역이 아니라 이 함수의
    # 클로저 안에서 만들어지기 때문 — WSGI 엔트리포인트로 노출돼 있지 않다.
    try:
        from waitress import serve
    except ImportError:
        logger.warning(
            "[AoTMCP] waitress 를 찾을 수 없어 Flask 내장 서버로 시작한다 "
            "(개발용 — `pip install waitress` 권장)")
        logger.info(f"[AoTMCP] HTTP mode started on {host}:{port}")
        http_app.run(host=host, port=port, debug=False)
        return

    logger.info(f"[AoTMCP] HTTP mode started on {host}:{port} (waitress)")
    serve(http_app, host=host, port=port, threads=4, ident='AoT-MCP')


# =============================================================================
# Entry point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="AoT MCP Server — exposes AoT tools via MCP protocol."
    )
    parser.add_argument(
        "--http", action="store_true",
        help="Run in HTTP REST mode (default: stdio)",
    )
    parser.add_argument(
        "--port", type=int, default=5700,
        help="HTTP port (default: 5700, only used with --http)",
    )
    parser.add_argument(
        "--log", default="WARNING",
        help="Log level: DEBUG, INFO, WARNING, ERROR (default: WARNING)",
    )
    args = parser.parse_args()

    handlers = [logging.StreamHandler(sys.stderr)]
    aot_local_dir = os.environ.get('AOT_LOCAL_DIR')
    if aot_local_dir and os.path.exists(os.path.join(aot_local_dir, 'logs')):
        log_file = os.path.join(aot_local_dir, 'logs', 'mcp.log')
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, args.log.upper(), logging.WARNING),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers
    )

    # Bootstrap Flask app for SQLAlchemy / config access
    # Skip scheduler initialization in MCP server process to avoid DB job conflicts
    os.environ["AOT_SKIP_SCHEDULER"] = "1"
    from aot.aot_flask.app import create_app
    app = create_app()
    logger.info(f"[AoTMCP] Flask app context initialized (install dir: {_INSTALL_DIR})")

    # 이 프로세스는 외부 AI 전용이다. 등록하지 않으면 여기서 나가는 장치 명령이
    # 출처 불명(unknown)으로 감사로그에 남아 진짜 우회 접근과 구분되지 않는다.
    from aot.utils.command_origin import ROLE_MCP, set_process_role
    set_process_role(ROLE_MCP)

    if args.http:
        _run_http_server(app, port=args.port)
    else:
        server = StdioMCPServer(app)
        server.run()


if __name__ == "__main__":
    main()
