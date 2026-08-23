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
from logging.handlers import RotatingFileHandler

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

# ── 실행층 ────────────────────────────────────────────────────────────────────
# 도구 실행·승인 게이트·감사·응답 캡·도구 목록은 **이 파일에 없다.** 내부 AI 도
# 같은 것을 쓰기 때문이다 — 예전에는 그러려고 여기를 subprocess 로 띄워 자기
# 자신에게 JSON-RPC 를 보냈고, 그 대가로 앱을 한 벌 더 로드(약 400MB)하면서
# 두 프로세스의 코드 버전이 갈렸다. 이 파일이 하는 일은 이제 **전송**뿐이다:
# stdio/HTTP 로 받아 tool_execution 에 넘기고 결과를 돌려준다.
from aot.ai.services.tool_execution import (  # noqa: E402
    SERVER_HOST,
    _CONFIRMATION_RESPONSE_TOOL,
    _EXTRA_TOOLS,
    _MAX_RESPONSE_TOKENS,
    _NATIVE_TOOLS,
    _TIER_EXEMPT_TOOLS,
    _cap_result,
    _drawer_index,
    _estimate_tokens,
    _execute_tool,
    _exclude_always_listed,
    _get_all_tools,
    _server_instructions,
    _tiering_enabled,
)


class StdioMCPServer:
    """Reads JSON-RPC requests from stdin, writes responses to stdout.

    Follows MCP protocol 2024-11-05:
      1. initialize       → capabilities handshake
      2. notifications/initialized → client ready signal
      3. tools/list       → return all available tools
      4. tools/call       → execute tool and return result
    """

    def __init__(self, app, out=None):
        self._app = app
        # JSON-RPC 를 내보낼 스트림. main() 이 로그를 stderr 로 몰아내면서
        # sys.stdout 을 갈아치우므로, **그 전에 잡아 둔 진짜 stdout** 을 받는다
        # (main() 의 주석 참조). 인자가 없으면 현재 stdout — 이 클래스를 다른
        # 자리에서 쓰거나 시험할 때를 위한 것이지, 정상 경로는 항상 주입한다.
        self._out = out or sys.stdout
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
        """Write a JSON-RPC response line to the protocol stream.

        `sys.stdout` 을 쓰지 않는다 — 그 이름은 로그가 프로토콜을 오염시키지
        않도록 stderr 로 바뀌어 있다.
        """
        self._out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self._out.flush()

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
                    "instructions": _server_instructions(),
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
                # 그룹 스코프(A2) — 신원은 **키 소유자**다(`RoleInfo.user_id`).
                # 역할 자체로 판정하지 않는다 — 역할은 서비스 계정에서 올 수도
                # 있고, 그러면 판정 근거가 사람이 아니게 된다.
                content = _execute_tool(self._app, tool_name, arguments,
                                        agent_id=self._agent_id, role=self._role,
                                        elicit_fn=None,
                                        scope_user_uuid=getattr(
                                            self._role, 'user_id', None))
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

#: initialize 에서 협상 가능한 프로토콜 버전. 도구만 노출하므로 이 범위에서는
#: 능력 선언이 동일하고, 클라이언트가 요구한 버전을 그대로 돌려주면 된다.
#: 2025-03-26 부터 Streamable HTTP 가 표준 전송이다.
_SUPPORTED_PROTOCOLS = ("2024-11-05", "2025-03-26", "2025-06-18")


def _run_http_server(app, port=5700):
    """Serve MCP over HTTP — standard Streamable HTTP plus the legacy REST API.

    Endpoints:
      POST /mcp              → MCP Streamable HTTP (JSON-RPC). 표준 클라이언트용.
      GET  /mcp              → 405. 서버→클라이언트 SSE 스트림은 제공하지 않는다
                               (아래 _mcp_streamable 주석 참조).
      GET  /mcp/info         → server metadata (인증 불필요, 생존 확인)
      GET  /mcp/tools/list   → all tools          ┐ 자체 REST. ChatGPT Actions 와
      POST /mcp/tools/call   → {name, arguments}  ┘ curl 점검이 계속 쓴다.
                               arguments 는 object 또는 그 JSON 문자열.

    REST 를 남겨두는 이유: 일반 요금제의 ChatGPT Custom GPT 는 MCP 서버를 직접
    등록할 수 없고 OpenAPI Actions 로만 붙는다. 현장 운영자가 쓰는 경로가 그쪽이라
    표준 전송이 생겼다고 걷어낼 수 없다.
    """
    import uuid as _uuid

    from flask import Flask, request, jsonify, Response
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

    # ── MCP Streamable HTTP ────────────────────────────────────────────────
    def _rpc_error(msg_id, code, message):
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": code, "message": message}}

    def _handle_rpc(msg, agent_id, role):
        """One JSON-RPC message → response dict, or None for a notification.

        Routes to the same _get_all_tools/_execute_tool the stdio transport and
        the REST API use, so a tool never behaves differently depending on how
        it was reached.
        """
        if not isinstance(msg, dict):
            return _rpc_error(None, -32600, "Invalid Request")
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            asked = (params.get("protocolVersion") or "").strip()
            version = asked if asked in _SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION,
                               "host": SERVER_HOST},
                "instructions": _server_instructions(),
            }}
        if method.startswith("notifications/"):
            return None                      # 알림에는 응답하지 않는다
        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"tools": _get_all_tools(app, role=role)}}
        if method == "tools/call":
            name = params.get("name", "")
            if not name:
                return _rpc_error(msg_id, -32602, "Missing tool name")
            try:
                # 그룹 스코프(A2) — 신원은 키 소유자(`RoleInfo.user_id`).
                content = _execute_tool(app, name, params.get("arguments") or {},
                                        agent_id=agent_id, role=role,
                                        scope_user_uuid=getattr(
                                            role, 'user_id', None))
                return {"jsonrpc": "2.0", "id": msg_id,
                        "result": {"content": content}}
            except Exception as exc:
                logger.exception("[AoTMCP] streamable tools/call 실패: %s", name)
                return _rpc_error(msg_id, -32603, str(exc))
        if msg_id is None:
            return None
        return _rpc_error(msg_id, -32601, f"Method not found: {method}")

    @http_app.route("/mcp", methods=["POST"])
    def mcp_streamable():
        # DNS 리바인딩 방어: 브라우저에서 온 요청이면 Origin 이 붙는다. 이 서버는
        # 브라우저용이 아니므로, Origin 이 있는데 우리 호스트가 아니면 거절한다.
        origin = request.headers.get("Origin")
        if origin and request.host not in origin:
            return jsonify({"error": "origin not allowed"}), 403

        declared = request.headers.get("X-MCP-Agent-Id")
        with app.app_context():
            ok, agent_id, role, err = mcp_auth.authenticate_http(request.headers, declared)
        if not ok:
            return jsonify(err), 401

        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify(_rpc_error(None, -32700, "Parse error")), 400

        batch = isinstance(payload, list)
        messages = payload if batch else [payload]
        responses = [r for r in (_handle_rpc(m, agent_id, role) for m in messages)
                     if r is not None]

        # 알림만 담긴 요청에는 본문 없이 202 로 답한다(스펙 요구사항).
        if not responses:
            return Response(status=202)

        body = responses if batch else responses[0]
        resp = jsonify(body)
        # 세션 식별자. 인증은 요청마다 헤더로 하므로 서버가 세션 상태를 들고
        # 있지는 않지만, 클라이언트가 기대하는 값이라 initialize 응답에 실어준다.
        if any((m or {}).get("method") == "initialize" for m in messages):
            resp.headers["Mcp-Session-Id"] = _uuid.uuid4().hex
        return resp

    @http_app.route("/mcp", methods=["GET"])
    def mcp_streamable_get():
        # 서버→클라이언트 SSE 스트림은 제공하지 않는다. waitress 를 4스레드로
        # 돌리는 서버라 접속 하나가 스레드를 붙잡고 있으면 도구 호출이 밀린다.
        # 스펙은 스트림을 제공하지 않는 서버가 405 를 주도록 허용한다.
        # 서버발 알림(tools/list_changed 등)이 필요해지면 그때 여는 자리다.
        return jsonify({"error": "This server does not offer an SSE stream."}), 405

    @http_app.route("/mcp", methods=["DELETE"])
    def mcp_streamable_delete():
        # 세션 상태를 두지 않으므로 종료할 것이 없다. 클라이언트의 정리 요청은
        # 성공으로 받아준다.
        return Response(status=204)

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
        # arguments 를 JSON 문자열로도 받는다. ChatGPT Custom GPT 의 Actions 는
        # properties 가 선언되지 않은 자유형 object 를 채우지 못하고 통째로 빠뜨린다
        # (2026-08-09: list_devices_in_area 가 "area_name is required" 로 실패 —
        # 실제로 나간 바디에 arguments 키 자체가 없었다). 도구 인자 키는 134 종이라
        # OpenAPI 에 전부 선언할 수 없으므로, 문자열 한 칸으로 받아 여기서 푼다.
        # 표준 MCP 전송(POST /mcp)은 규격대로 object 만 보내므로 그쪽은 손대지 않는다.
        if isinstance(arguments, str):
            blank = not arguments.strip()
            try:
                arguments = {} if blank else json.loads(arguments)
            except ValueError as exc:
                return jsonify({"error": f"'arguments' is not valid JSON: {exc}"}), 400
            if not isinstance(arguments, dict):
                return jsonify({
                    "error": "'arguments' must decode to a JSON object, "
                             f"got {type(arguments).__name__}."
                }), 400
        elif arguments is None:
            arguments = {}
        elif not isinstance(arguments, dict):
            return jsonify({
                "error": f"'arguments' must be an object or a JSON string, "
                         f"got {type(arguments).__name__}."
            }), 400
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
            # 그룹 스코프(A2) — 신원은 키 소유자(`RoleInfo.user_id`).
            content = _execute_tool(app, tool_name, arguments,
                                    agent_id=agent_id, role=role,
                                    scope_user_uuid=getattr(role, 'user_id', None))
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

    cli_level = getattr(logging, args.log.upper(), logging.WARNING)
    # 파일에는 최소 INFO 를 남긴다. stderr 는 --log 가 정한 그대로다.
    # 기본값(WARNING)으로 파일까지 묶으면 정상 운용 중에는 파일이 계속 비어
    # 있고, /logview 의 'MCP Server' 는 "로그가 없다" 로만 보인다 — MCP 로그를
    # 볼 수 없던 원래 문제가 파일만 생긴 채 그대로 남는다.
    file_level = min(cli_level, logging.INFO)

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(cli_level)
    handlers = [stream_handler]

    # 파일 핸들러는 config.MCP_LOG_FILE(= LOG_PATH/mcp.log) 하나로 통일한다.
    # 예전에는 AOT_LOCAL_DIR/logs 에만 썼는데 도커에서는 그 디렉터리가 없어
    # (LOG_PATH 는 /var/log/aot) 파일이 아예 안 생겼고, 앱 컨테이너에 docker
    # CLI 도 없어서 MCP 로그를 웹 UI 에서 볼 방법이 전혀 없었다. LOG_PATH 는
    # 세 컨테이너가 같은 호스트 디렉터리를 공유하므로 여기 쓰면 /logview 가 읽는다.
    try:
        from aot.config import MCP_LOG_FILE
        file_handler = RotatingFileHandler(
            MCP_LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3,
            encoding='utf-8')
        file_handler.setLevel(file_level)
        handlers.append(file_handler)
    except Exception as err:  # 로그 파일 하나 때문에 MCP 가 못 뜨면 안 된다
        print(f"[AoTMCP] file logging disabled: {err}", file=sys.stderr)

    logging.basicConfig(
        level=file_level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=handlers
    )

    # ── stdio 는 stdout 이 프로토콜 그 자체다 ────────────────────────────────
    # `create_app()` 이 부르는 `configure_aot_file_logging()` 은 'aot' 로거에
    # **StreamHandler(sys.stdout)** 을 붙인다(utils/logging_setup.py). 데몬에게는
    # 맞는 선택이지만(도커/systemd 가 stdout 을 수집한다) 여기서는 그 로그가
    # JSON-RPC 스트림 한가운데로 쏟아진다 — 클라이언트가 받는 첫 줄이
    # `2026-08-21 ... INFO ...` 라서 JSON 파싱이 그 자리에서 실패한다.
    #
    # 실제로 그래서 `MCPBridge` 의 initialize 핸드셰이크가 늘 실패했고
    # ("Invalid JSON from MCP server: Extra data: line 1 column 5"), 내부 AI 의
    # 매니페스트는 `mcp_tools: 0` 이었다 — operate_device 를 비롯한 MCP 도구를
    # **하나도 못 받는 상태**로 돌고 있었다. 관대한 클라이언트(줄 앞에 '{' 가
    # 없으면 건너뛰는 쪽)만 우연히 동작해서, 붙는 클라이언트가 있다는 사실이
    # 오히려 이 고장을 가렸다.
    #
    # **create_app() 앞에서** 바꿔야 한다. StreamHandler 는 생성 시점의 스트림
    # 객체를 붙잡으므로, 핸들러가 만들어진 뒤에 sys.stdout 을 갈아도 이미 붙은
    # 핸들러는 옛 객체(진짜 stdout)를 계속 쓴다.
    #
    # 스트림 자체를 바꾸는 이유는 핸들러 하나만 고치는 것으로는 부족해서다 —
    # 어떤 라이브러리든 print() 한 줄이면 같은 고장이 재발하는데, 그때는
    # 원인이 다시 보이지 않는다. HTTP 모드는 stdout 이 프로토콜이 아니므로
    # 건드리지 않는다.
    protocol_stdout = None
    if not args.http:
        protocol_stdout = sys.stdout
        sys.stdout = sys.stderr

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
        server = StdioMCPServer(app, out=protocol_stdout)
        server.run()


if __name__ == "__main__":
    main()
