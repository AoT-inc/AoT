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
        "args": ["/opt/AoT/aot/aot_mcp_server.py"],
        "env": { "AOT_MCP_API_KEY": "<base64 api key>" }
      }
    }
  }

  stdio requires an API key too (AOT_MCP_REQUIRE_AUTH=0 turns this off). Issue
  one under Manage > System Management > Users.
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
#: HTTP 요청 본문 상한. 앞의 것은 Flask(MAX_CONTENT_LENGTH, JSON-RPC 413 본문), 뒤의 것은
#: waitress(max_request_body_size — 받는 중에 끊어 디스크·메모리에 쌓이지 않게).
MCP_HTTP_BODY_LIMIT = 8 * 1024 * 1024
MCP_HTTP_BODY_HARD_LIMIT = 16 * 1024 * 1024
# 동일 사용자가 여러 AoT 인스턴스의 MCP 서버를 동시에 붙였을 때 응답을 구분할 수
# 있도록, 관리자가 별도로 설정하지 않아도 프로세스 호스트명을 자동으로 싣는다.
SERVER_HOST = socket.gethostname()

# ── 실행층 ────────────────────────────────────────────────────────────────────
# 도구 실행·승인 게이트·감사·응답 캡·도구 목록은 **이 파일에 없다.** 내부 AI 도
# 같은 것을 쓰기 때문이다 — 예전에는 그러려고 여기를 subprocess 로 띄워 자기
# 자신에게 JSON-RPC 를 보냈고, 그 대가로 앱을 한 벌 더 로드(약 400MB)하면서
# 두 프로세스의 코드 버전이 갈렸다. 이 파일이 하는 일은 이제 **전송**뿐이다:
# stdio/HTTP 로 받아 tool_execution 에 넘기고 결과를 돌려준다.
from aot.tools.tool_execution import (  # noqa: E402
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


#: initialize 응답의 능력 선언 — 도구와 읽기 전용 자료(resources). subscribe·listChanged 는 없다.
_CAPABILITIES = {"tools": {}, "resources": {}}


def _session_head(content, name, arguments, session_key, role):
    """MCP 세션 단위 응답 머리(설계 F-16 ②·④) — 세션 첫 응답의 핵심 규칙, 같은 세션의 규칙 위반 교정 한 줄.

    전송층에서만 싣는다 — 인앱 AI 는 지침을 받으므로 지나지 않고, 실행층에 MCP 가정을 넣지 않는다. 규칙과 교정은
    도메인 표면의 이름(weather 의 at·focus)을 쓰므로 옛 표면에서는 싣지 않는다. 실패해도 응답은 그대로 나간다."""
    try:
        from aot.tools.tool_execution import domain_surface_enabled
        if not domain_surface_enabled():
            return content
        from aot.tools.domain import session_rules
        return session_rules.annotate(content, name, arguments, session_key,
                                      getattr(role, 'user_id', None))
    except Exception:                                       # noqa: BLE001
        logger.debug("[AoTMCP] session head skipped", exc_info=True)
        return content


class StdioMCPServer:
    """Reads JSON-RPC requests from stdin, writes responses to stdout.

    Follows MCP protocol 2024-11-05 (요청한 버전이 _SUPPORTED_PROTOCOLS 안이면 그 버전으로 협상):
      1. initialize       → capabilities handshake
      2. notifications/initialized → client ready signal
      3. tools/list       → return all available tools
      4. tools/call       → execute tool and return result
      5. resources/list·read·templates/list → AI 수신함 카드(P2, 읽기 전용)
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
        # 이 연결의 도구 묶음(mcp_auth.tool_profile_of). initialize 에서 정한다.
        self._tool_profile = None
        # initialize 에서 인증에 성공해야 True. 실패하면 tools/* 를 거부한다.
        self._authed = False
        # initialize 에서 협상한 프로토콜 버전. ≥2025-06-18 이면 post 결과에 resource_link 를 싣는다.
        self._protocol = PROTOCOL_VERSION
        # 클라이언트가 initialize에서 capabilities.elicitation을 선언했는가.
        # 참이면 쓰기 도구 승인을 비동기 큐 대신 실시간 elicitation으로 처리한다
        # (2026-07-26 확인: Claude Code는 이 capability를 선언한다).
        self._supports_elicitation = False
        self._next_elicit_id = 0
        # 호출 품질 기록의 세션 열쇠 — stdio 는 프로세스 하나가 곧 클라이언트
        # 연결 하나라, 시작할 때 만든 무작위 값 하나로 같은 연결의 호출을 묶는다.
        # 실행층이 해시해서 저장한다(원문은 어디에도 남지 않는다).
        import uuid as _uuid
        self._session_key = _uuid.uuid4().hex

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
            from aot.tools import mcp_auth
            with self._app.app_context():
                ok, agent_id, role, err = mcp_auth.authenticate_stdio(declared)
            if not ok:
                self._authed = False
                logger.warning(f"[AoTMCP] stdio 인증 실패: {err.get('message')}")
                self._send({"jsonrpc": "2.0", "id": msg_id,
                            "error": {"code": -32001, "message": err.get("message")}})
                return
            self._authed = True
            asked = str((params or {}).get("protocolVersion") or "").strip()
            self._protocol = asked if asked in _SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
            self._agent_id = agent_id
            # stdio 는 연결 주소가 없으므로 환경변수로 좁힌다(HTTP 의 ?tools=lite).
            role = mcp_auth.narrow_profile(role, os.environ.get("AOT_MCP_TOOLS"))
            self._role = role
            self._tool_profile = mcp_auth.tool_profile_of(role)
            logger.info(f"[AoTMCP] Client identified as '{self._agent_id}' "
                        f"(role={getattr(role, 'name', None)})")
            self._send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": self._protocol,
                    "capabilities": dict(_CAPABILITIES),
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION,
                                   "host": SERVER_HOST},
                    "instructions": _server_instructions(self._tool_profile, self._role),
                },
            })

        elif method == "notifications/initialized":
            self._initialized = True
            logger.info("[AoTMCP] Client initialized — ready to serve tools.")

        elif (method in ("tools/list", "tools/call") or method in _RESOURCE_METHODS) \
                and not self._authed:
            self._send({"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32001,
                                  "message": "인증되지 않은 세션입니다. initialize 를 먼저 수행하세요."}})

        elif method in _RESOURCE_METHODS:
            self._resources(msg_id, method, params)

        elif method == "tools/list":
            tools = _get_all_tools(self._app, role=self._role,
                                   profile=self._tool_profile)
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
                                            self._role, 'user_id', None),
                                        transport="mcp_stdio",
                                        session_key=self._session_key,
                                        tool_profile=self._tool_profile,
                                        resource_links=_resource_links_ok(self._protocol))
                content = _session_head(content, tool_name, arguments, self._session_key, self._role)
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

    def _resources(self, msg_id, method, params):
        """resources/* — AI 수신함 카드(키 주인 본인 것만). 실패는 JSON-RPC 오류로."""
        from aot.utils import ai_card_resources as res
        if msg_id is None:                    # 알림에는 응답하지 않는다
            return
        try:
            result = res.handle(self._app, method, params,
                                getattr(self._role, "user_id", None),
                                agent_id=self._agent_id, transport="mcp_stdio",
                                session_key=self._session_key)
            self._send({"jsonrpc": "2.0", "id": msg_id, "result": result})
        except res.RpcError as exc:
            self._send({"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": exc.code, "message": exc.message}})

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

#: resources/* 로 처리하는 메서드(읽기 전용 AI 카드 자료). 그 밖의 resources/* 는 "없는 메서드".
_RESOURCE_METHODS = ("resources/list", "resources/read", "resources/templates/list")

#: 2026-07-28 부터는 initialize 가 없다 — 요청마다 `_meta` 에 규격 버전을 싣고, 클라이언트는
#: `server/discover` 로 먼저 묻는다(현대 방식). 이 버전들은 http 에서만 받는다. 구 방식(initialize)
#: 연결은 위 _SUPPORTED_PROTOCOLS 로 그대로 협상한다 — 한 주소에서 두 방식을 같이 받는다(dual-era).
#: discover 에 "없는 메서드" 로 답하면 2026-07-28 클라이언트가 이 서버를 못 쓰는 것으로 볼 수 있다
#: (2026-11-08 claude.ai 음성 모드에서 이 서버만 도구 목록에서 빠짐 — 같은 계정의 SDK 2.x 서버는 보임).
_MODERN_PROTOCOLS = ("2026-07-28",)
_META_VERSION = "io.modelcontextprotocol/protocolVersion"
_META_CLIENT = "io.modelcontextprotocol/clientInfo"
_META_SERVER = "io.modelcontextprotocol/serverInfo"
#: 현대 방식에서 결과를 캐시해도 되는 목록 결과 — ttlMs·cacheScope 가 필수다(0·private = 캐시 안 함).
_CACHEABLE_METHODS = ("server/discover", "tools/list", "resources/list", "resources/templates/list")
#: 현대 방식의 오류 코드 → HTTP 상태. 그 밖의 오류는 200 으로 둔다(구 방식과 같다).
_MODERN_ERROR_STATUS = {-32022: 400, -32020: 400, -32601: 404}


def _modern_version(msg, header):
    """이 요청이 현대 방식(2026-07-28~)이면 요청한 버전, 아니면 None.

    `_meta` 의 버전이 정본이고, 없으면 `MCP-Protocol-Version` 헤더가 현대 버전일 때만 현대로
    본다(구 방식 클라이언트도 2025-06-18 부터 헤더를 싣는다). initialize 는 언제나 구 방식이다.
    """
    if not isinstance(msg, dict) or msg.get("method") == "initialize":
        return None
    params = msg.get("params")
    meta = params.get("_meta") if isinstance(params, dict) else None
    asked = meta.get(_META_VERSION) if isinstance(meta, dict) else None
    if isinstance(asked, str) and asked.strip():
        return asked.strip()[:32]
    return header if header in _MODERN_PROTOCOLS else None


def _client_name(msg):
    """기록용 클라이언트 이름 — initialize 의 clientInfo 또는 현대 요청의 `_meta` clientInfo."""
    params = msg.get("params") if isinstance(msg, dict) else None
    if not isinstance(params, dict):
        return None
    info = params.get("clientInfo")
    if not isinstance(info, dict):
        meta = params.get("_meta")
        info = meta.get(_META_CLIENT) if isinstance(meta, dict) else None
    if not isinstance(info, dict):
        return None
    return "%s/%s" % (str(info.get("name") or "?")[:64], str(info.get("version") or "")[:40])


def _resource_links_ok(version):
    """협상한 버전이 post 결과의 resource_link 블록을 받을 수 있는가(≥2025-06-18).
    http 는 요청의 `MCP-Protocol-Version` 헤더 값을 넘긴다(없으면 2025-03-26 으로 본다)."""
    from aot.utils import ai_card_resources
    return ai_card_resources.supports_links(version)


#: `Mcp-Session-Id` 헤더를 세션 열쇠로 받을 최대 길이. 넘으면 없는 것으로 본다.
_SESSION_HEADER_MAX_LEN = 128


def _session_header(headers):
    """요청 헤더의 `Mcp-Session-Id` 원문. 없거나 128자를 넘으면 None."""
    raw = (headers.get("Mcp-Session-Id") or "").strip()
    if not raw or len(raw) > _SESSION_HEADER_MAX_LEN:
        return None
    return raw


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
    from aot.tools import mcp_auth, mcp_central
    from aot.databases.models import AIGlobalSettings

    http_app = Flask("aot_mcp_http")
    # 요청 본문 상한 8 MiB — screen_action 의 attach.b64 (5 MiB 파일 ≈ 6.7 MB) + JSON
    # 여유. 넘으면 413(JSON-RPC 본문). 받기 자체의 상한은 아래 serve() 의
    # max_request_body_size 가 맡는다(웹 쪽 nginx 30M 은 그대로).
    http_app.config["MAX_CONTENT_LENGTH"] = MCP_HTTP_BODY_LIMIT

    @http_app.errorhandler(413)
    def _too_large(_err):
        return jsonify({"jsonrpc": "2.0", "id": None, "error": {
            "code": -32600,
            "message": "Request body too large (limit 8 MiB). Attach a smaller file."}}), 413

    # @manual ai/overview#enable-and-start
    def _http_server_enabled():
        # Checked fresh every request (not cached) so the Settings > General >
        # AI Service toggle takes effect immediately — no restart of this
        # process/container needed. Defaults to enabled if the row doesn't
        # exist yet, matching the column's own default.
        with app.app_context():
            settings = AIGlobalSettings.query.first()
        return settings is None or settings.mcp_http_enabled is not False

    # @manual ai/overview#enable-and-start
    @http_app.before_request
    def _gate_disabled():
        if not _http_server_enabled():
            return jsonify({"error": "External MCP server is disabled in "
                                      "Manage > System Management > General Settings > "
                                      "Enable External MCP Server."}), 503

    # ── MCP Streamable HTTP ────────────────────────────────────────────────
    def _rpc_error(msg_id, code, message):
        return {"jsonrpc": "2.0", "id": msg_id,
                "error": {"code": code, "message": message}}

    def _log_request(messages, protocol, status, eras, error=None):
        """POST /mcp 한 건을 한 줄로 남긴다 — 메서드·규격·클라이언트·상태. 토큰·인자는 남기지 않는다.

        initialize·tools/call 만 남기던 때는 tools/list·401·server/discover 가 안 보여서,
        클라이언트가 어디서 멈췄는지(2026-11-08 음성 모드) 가릴 수 없었다."""
        dicts = [m for m in messages if isinstance(m, dict)]
        methods = [str(m.get("method"))[:40] for m in dicts]
        names = [str((m.get("params") or {}).get("name") or "")[:40] for m in dicts
                 if m.get("method") == "tools/call" and isinstance(m.get("params"), dict)]
        client = next((c for c in (_client_name(m) for m in dicts) if c), "-")
        era = next((e for e in (eras or []) if e), None)
        logger.info("[AoTMCP] http %s%s proto=%s%s client=%s -> %s%s",
                    ",".join(methods) or "-", (" " + ",".join(names)) if names else "",
                    protocol or "-", (" modern=" + era) if era else "", client, status,
                    (" err=%s" % (error,)) if error else "")

    def _unauthorized(err):
        """401 — 중앙 인증을 켰으면 인가 서버를 찾는 길(RFC 9728)을 헤더로 알린다."""
        resp = jsonify(err)
        resp.status_code = 401
        with app.app_context():
            cfg = mcp_central.config()
        if mcp_central.is_active(cfg):
            resp.headers["WWW-Authenticate"] = mcp_central.www_authenticate(
                cfg, invalid=(err or {}).get("error") == "invalid_token")
        return resp

    # @manual ai/overview#central-auth
    @http_app.route("/.well-known/oauth-protected-resource", methods=["GET"])
    @http_app.route("/.well-known/oauth-protected-resource/<path:_rest>", methods=["GET"])
    def protected_resource_metadata(_rest=None):
        # 클라이언트에 따라 경로 없는 주소를 먼저 찾으므로 두 경로 모두 같은 내용을 낸다.
        with app.app_context():
            cfg = mcp_central.config()
        if not mcp_central.is_active(cfg):
            return jsonify({"error": "not found"}), 404
        return jsonify(mcp_central.protected_resource_metadata(cfg))

    def _handle_rpc(msg, agent_id, role, session_key=None, blocked=None,
                    protocol=None, modern=None):
        """현대 방식(modern=요청 버전)이면 버전을 확인하고 server/discover 에 답한 뒤, 결과에
        2026-07-28 필수 필드(resultType·목록의 ttlMs/cacheScope)를 채운다. 나머지는 구 방식과 같다."""
        if not modern:
            return _handle_rpc_core(msg, agent_id, role, session_key, blocked, protocol)
        msg_id = msg.get("id") if isinstance(msg, dict) else None
        if modern not in _MODERN_PROTOCOLS:
            err = _rpc_error(msg_id, -32022, "Unsupported protocol version")
            err["error"]["data"] = {"supported": list(_MODERN_PROTOCOLS), "requested": modern}
            return err
        method = msg.get("method", "")
        if method == "server/discover":
            profile = mcp_auth.tool_profile_of(role)
            resp = {"jsonrpc": "2.0", "id": msg_id, "result": {
                "supportedVersions": list(_MODERN_PROTOCOLS),
                "capabilities": dict(_CAPABILITIES),
                "instructions": (blocked + "\n\n" if blocked else "") + _server_instructions(profile, role),
                "_meta": {_META_SERVER: {"name": SERVER_NAME, "version": SERVER_VERSION,
                                         "host": SERVER_HOST}},
            }}
        else:
            resp = _handle_rpc_core(msg, agent_id, role, session_key, blocked,
                                    protocol or modern)
        result = (resp or {}).get("result")
        if isinstance(result, dict) and method != "ping":
            result.setdefault("resultType", "complete")
            if method in _CACHEABLE_METHODS:
                result.setdefault("ttlMs", 0)
                result.setdefault("cacheScope", "private")
        return resp

    def _handle_rpc_core(msg, agent_id, role, session_key=None, blocked=None,
                         protocol=None):
        """One JSON-RPC message → response dict, or None for a notification.

        Routes to the same _get_all_tools/_execute_tool the stdio transport and
        the REST API use, so a tool never behaves differently depending on how
        it was reached.

        session_key: 요청의 `Mcp-Session-Id` 헤더 원문(호출 품질 기록용). 헤더는
        **여기 전송층에서만** 읽는다 — 실행층은 test_request_context 안이라 원래
        요청의 헤더가 보이지 않는다.

        blocked: 토큰은 맞지만 이 AoT 사용자와 이어지지 않은 연결의 안내문. 연결과
        목록은 그대로 주고, 도구 실행만 이 안내를 담은 도구 오류로 돌려준다.

        protocol: 요청의 `MCP-Protocol-Version` 헤더 원문(없으면 None = 2025-03-26 취급).
        ≥2025-06-18 이면 post 결과에 resource_link 블록을 싣는다.
        """
        if not isinstance(msg, dict):
            return _rpc_error(None, -32600, "Invalid Request")
        # 이 키의 도구 묶음 — 목록·실행·안내문이 같은 값을 본다.
        profile = mcp_auth.tool_profile_of(role)
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            asked = (params.get("protocolVersion") or "").strip()
            version = asked if asked in _SUPPORTED_PROTOCOLS else PROTOCOL_VERSION
            # 어떤 AI 클라이언트가 붙었는지 남긴다(stdio 는 이미 남김). 화면 연동
            # 설계(2026-10)에서 클라이언트별 동작을 실측하려는 것 — 사용자 기기는
            # 여기서 알 수 없다(원격 커넥터는 그 회사 서버가 호출한다).
            client = params.get("clientInfo") or {}
            logger.info("[AoTMCP] http initialize client=%s/%s agent=%s ua=%s",
                        str(client.get("name") or "unknown")[:64],
                        str(client.get("version") or "")[:32], agent_id,
                        (request.headers.get("User-Agent") or "")[:120])
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "protocolVersion": version,
                "capabilities": dict(_CAPABILITIES),
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION,
                               "host": SERVER_HOST},
                "instructions": (blocked + "\n\n" if blocked else "") + _server_instructions(profile, role),
            }}
        if method.startswith("notifications/"):
            return None                      # 알림에는 응답하지 않는다
        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"tools": _get_all_tools(app, role=role,
                                                       profile=profile)}}
        if method in _RESOURCE_METHODS:
            if msg_id is None:
                return None
            if blocked:
                return _rpc_error(msg_id, -32001, blocked)
            from aot.utils import ai_card_resources as res
            try:
                return {"jsonrpc": "2.0", "id": msg_id, "result": res.handle(
                    app, method, params, getattr(role, "user_id", None),
                    agent_id=agent_id, transport="mcp_http", session_key=session_key)}
            except res.RpcError as exc:
                return _rpc_error(msg_id, exc.code, exc.message)
        if method == "tools/call":
            name = params.get("name", "")
            if not name:
                return _rpc_error(msg_id, -32602, "Missing tool name")
            if blocked:
                return {"jsonrpc": "2.0", "id": msg_id, "result": {
                    "content": [{"type": "text", "text": blocked}], "isError": True}}
            try:
                # 그룹 스코프(A2) — 신원은 키 소유자(`RoleInfo.user_id`).
                content = _execute_tool(app, name, params.get("arguments") or {},
                                        agent_id=agent_id, role=role,
                                        scope_user_uuid=getattr(
                                            role, 'user_id', None),
                                        transport="mcp_http",
                                        session_key=session_key,
                                        tool_profile=profile,
                                        resource_links=_resource_links_ok(protocol))
                content = _session_head(content, name, params.get("arguments") or {}, session_key, role)
                return {"jsonrpc": "2.0", "id": msg_id,
                        "result": {"content": content}}
            except Exception as exc:
                logger.exception("[AoTMCP] streamable tools/call 실패: %s", name)
                return _rpc_error(msg_id, -32603, str(exc))
        if msg_id is None:
            return None
        return _rpc_error(msg_id, -32601, f"Method not found: {method}")

    # @manual ai/overview#running-the-mcp-server
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
        role = mcp_auth.narrow_profile(role, request.args.get("tools"))
        payload = request.get_json(silent=True)
        protocol = (request.headers.get("MCP-Protocol-Version") or "").strip()[:32] or None
        messages = payload if isinstance(payload, list) else [payload]
        blocked = None
        if not ok:
            if (err or {}).get("error") != mcp_auth.ERROR_NOT_LINKED:
                _log_request(messages, protocol, 401, [], (err or {}).get("error"))
                return _unauthorized(err)
            blocked = err["message"]

        if payload is None:
            _log_request([], protocol, 400, [], "parse")
            return jsonify(_rpc_error(None, -32700, "Parse error")), 400

        # 우리가 initialize 에서 준 세션 번호를 클라이언트가 되돌려 보낸다.
        # 호출 품질 기록에서 같은 대화를 묶는 데만 쓴다(해시로만 저장). 길이가
        # 비정상이면 버린다 — 임의 길이의 헤더를 해시 입력으로 받지 않는다.
        session_key = _session_header(request.headers)
        batch = isinstance(payload, list)
        eras = [_modern_version(m, protocol) for m in messages]
        responses = [r for r in (_handle_rpc(m, agent_id, role, session_key, blocked,
                                             protocol, modern)
                                 for m, modern in zip(messages, eras))
                     if r is not None]

        # 알림만 담긴 요청에는 본문 없이 202 로 답한다(스펙 요구사항).
        if not responses:
            _log_request(messages, protocol, 202, eras)
            return Response(status=202)

        body = responses if batch else responses[0]
        resp = jsonify(body)
        # 현대 방식은 규격 오류를 HTTP 상태로도 알린다(버전 불일치 400, 없는 메서드 404).
        # 구 방식은 지금처럼 200 + JSON-RPC 오류다 — 구 클라이언트의 동작을 바꾸지 않는다.
        if not batch and eras[0]:
            code = ((body or {}).get("error") or {}).get("code")
            resp.status_code = _MODERN_ERROR_STATUS.get(code, 200)
        _log_request(messages, protocol, resp.status_code, eras,
                     [((r or {}).get("error") or {}).get("code") for r in responses
                      if (r or {}).get("error")])
        # 세션 식별자. 인증은 요청마다 헤더로 하므로 서버가 세션 상태를 들고
        # 있지는 않지만, 클라이언트가 기대하는 값이라 initialize 응답에 실어준다.
        if any((m or {}).get("method") == "initialize" for m in messages):
            resp.headers["Mcp-Session-Id"] = _uuid.uuid4().hex
        return resp

    # @manual ai/overview#running-the-mcp-server
    @http_app.route("/mcp", methods=["GET"])
    def mcp_streamable_get():
        # 서버→클라이언트 SSE 스트림은 제공하지 않는다. waitress 를 4스레드로
        # 돌리는 서버라 접속 하나가 스레드를 붙잡고 있으면 도구 호출이 밀린다.
        # 스펙은 스트림을 제공하지 않는 서버가 405 를 주도록 허용한다.
        # 서버발 알림(tools/list_changed 등)이 필요해지면 그때 여는 자리다.
        return jsonify({"error": "This server does not offer an SSE stream."}), 405

    # @manual ai/overview#running-the-mcp-server
    @http_app.route("/mcp", methods=["DELETE"])
    def mcp_streamable_delete():
        # 세션 상태를 두지 않으므로 종료할 것이 없다. 클라이언트의 정리 요청은
        # 성공으로 받아준다.
        return Response(status=204)

    # @manual ai/overview#chatgpt-setup
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

    # @manual ai/overview#chatgpt-setup
    @http_app.route("/mcp/tools/list", methods=["GET"])
    def tools_list():
        # 카탈로그도 능력 노출이므로 인증 뒤에 둔다. /mcp/info 만 생존 확인용으로 열어둔다.
        with app.app_context():
            ok, _agent, role, err = mcp_auth.authenticate_http(request.headers)
        if not ok:
            return _unauthorized(err)
        role = mcp_auth.narrow_profile(role, request.args.get("tools"))
        tools = _get_all_tools(app, role=role,
                               profile=mcp_auth.tool_profile_of(role))
        return jsonify({"tools": tools})

    # @manual ai/overview#chatgpt-setup
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
            return _unauthorized(err)
        role = mcp_auth.narrow_profile(role, request.args.get("tools"))
        try:
            # 그룹 스코프(A2) — 신원은 키 소유자(`RoleInfo.user_id`).
            content = _execute_tool(app, tool_name, arguments,
                                    agent_id=agent_id, role=role,
                                    scope_user_uuid=getattr(role, 'user_id', None),
                                    transport="rest",
                                    tool_profile=mcp_auth.tool_profile_of(role))
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
    # waitress 는 본문 전체를 받아 둔 뒤에야 Flask 를 부른다(기본 상한 1 GiB, 넘치면
    # 임시 파일). MAX_CONTENT_LENGTH 만으로는 인증 전 요청도 1 GiB 까지 디스크에 쌓인다
    # (P1 보안 리뷰 M1). 8~16 MiB 는 Flask 가 JSON-RPC 413 을 주고, 그 위는 waitress 가
    # 받기 전에 끊는다.
    serve(http_app, host=host, port=port, threads=4, ident='AoT-MCP',
          max_request_body_size=MCP_HTTP_BODY_HARD_LIMIT)


# =============================================================================
# Entry point
# =============================================================================

# @manual ai/overview#running-the-mcp-server
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
        from aot.utils.logging_setup import SharedRotatingFileHandler
        # mcp 컨테이너와 웹 워커가 띄우는 stdio MCP 가 같은 파일을 쓸 수 있다.
        file_handler = SharedRotatingFileHandler(
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
    # NOTE: create_app() (routes_ai_agent et al.) imports aot.ai as a side effect,
    # which binds the aot/tools/providers.py callbacks the tool layer needs
    # (aot/ai/services/tool_providers.py::bind_all(), called from aot/ai/__init__.py).
    # Deliberately NOT importing aot.ai directly in this file — the mcp-no-ai guard
    # (check_import_layers.py) forbids this module from depending on aot.ai, and this
    # transitive import already satisfies the binding requirement before any tool runs.
    from aot.aot_flask.app import create_app
    app = create_app()
    logger.info(f"[AoTMCP] Flask app context initialized (install dir: {_INSTALL_DIR})")

    # 이 프로세스는 외부 AI 전용이다. 등록하지 않으면 여기서 나가는 장치 명령이
    # 출처 불명(unknown)으로 감사로그에 남아 진짜 우회 접근과 구분되지 않는다.
    from aot.utils.command_origin import ROLE_MCP, set_process_role
    set_process_role(ROLE_MCP)

    if args.http:
        # AI·슬라이더의 예보 조회가 첫 호출에 계산(0.7~1.1초)을 기다리지 않게 대지 예보 계열을 미리 채운다.
        # 이 프로세스의 캐시는 웹 워커와 따로다. stdio 모드는 앱이 띄우는 부속 프로세스라 하지 않는다.
        try:
            from aot.space.forecast_series import start_prewarm
            start_prewarm(app)
        except Exception as e:  # never block server startup
            logger.warning(f"[AoTMCP] forecast series prewarm scheduling failed: {e}")
        _run_http_server(app, port=args.port)
    else:
        server = StdioMCPServer(app, out=protocol_stdout)
        server.run()


if __name__ == "__main__":
    main()
