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

# ── Native tool names handled by AoTNativeToolEngine ──────────────────────────
_NATIVE_TOOLS = {"list_available_devices", "get_sensor_reading", "set_output_state"}


# =============================================================================
# Tool registry
# =============================================================================

def _get_all_tools(app):
    """Return merged list of VIRTUAL_TOOLS + AoTNativeToolEngine tools.

    Priority: VIRTUAL_TOOLS first (richer descriptions), then native tools
    not already present by name.
    """
    tools = []

    # 1. VIRTUAL_TOOLS from mcp_aot.py
    try:
        from aot.ai.agents.mcp_aot import VIRTUAL_TOOLS
        for vt in VIRTUAL_TOOLS:
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
                if nt["name"] not in existing:
                    tools.append({
                        "name": nt["name"],
                        "description": nt.get("description", ""),
                        "inputSchema": nt.get("inputSchema", {"type": "object", "properties": {}}),
                    })
    except Exception as exc:
        logger.warning(f"[AoTMCP] Could not load NativeToolEngine tools: {exc}")

    return tools


def _execute_tool(app, tool_name, arguments):
    """Execute a named tool and return MCP-format content list.

    Dispatches to AoTNativeToolEngine for native tools, and to
    AoTDataToolService for virtual tools.

    Returns:
        list[dict]: MCP content blocks, e.g. [{"type": "text", "text": "..."}]
    """
    with app.app_context():
        try:
            if tool_name in _NATIVE_TOOLS:
                from aot.ai.services.aot_native_tool_engine import AoTNativeToolEngine
                result = AoTNativeToolEngine.execute(tool_name, arguments)
            else:
                result = _dispatch_virtual_tool(tool_name, arguments)
        except ValueError as exc:
            result = {"status": "error", "message": str(exc)}
        except Exception as exc:
            logger.error(f"[AoTMCP] Tool '{tool_name}' failed: {exc}", exc_info=True)
            result = {"status": "error", "message": str(exc)}

    return [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]


def _dispatch_virtual_tool(tool_name, arguments):
    """Map virtual tool name to AoTDataToolService method."""
    from aot.ai.services.aot_data_tool_service import AoTDataToolService

    dispatch = {
        "get_sensor_detail": lambda a: AoTDataToolService.get_sensor_detail(
            loc_id=a.get("loc_id"),
            sensor_type=a.get("sensor_type"),
            time_range=a.get("time_range", "24h"),
        ),
        "get_spatial_tree": lambda a: AoTDataToolService.get_spatial_tree(
            depth=a.get("depth", 2),
            filter_type=a.get("filter_type"),
        ),
        "search_devices": lambda a: AoTDataToolService.search_devices(
            query=a.get("query", ""),
        ),
        "get_device_list": lambda a: AoTDataToolService.get_device_list_tool(),
        "get_energy_report": lambda a: AoTDataToolService.get_energy_report(
            period=a.get("period", "daily"),
            zone_id=a.get("zone_id"),
        ),
        "operate_device": lambda a: AoTDataToolService.operate_device_tool(
            device_id=a.get("device_id"),
            state=a.get("state"),
            value=a.get("value"),
            duration_seconds=a.get("duration_seconds"),
        ),
        "add_schedule": lambda a: AoTDataToolService.add_schedule_tool(
            date=a.get("date"),
            content=a.get("content"),
            worker=a.get("worker"),
            time=a.get("time", "09:00"),
            tags=a.get("tags"),
        ),
        "schedule_device_control": lambda a: AoTDataToolService.schedule_device_control_tool(
            device_id=a.get("device_id"),
            scheduled_time=a.get("scheduled_time"),
            state=a.get("state"),
            duration_minutes=a.get("duration_minutes", 5),
        ),
        "get_weather": lambda a: AoTDataToolService.get_weather_tool(
            zone_name=a.get("zone_name"),
            zone_id=a.get("zone_id"),
        ),
    }

    fn = dispatch.get(tool_name)
    if fn is None:
        raise ValueError(f"Unknown tool: '{tool_name}'")
    return fn(arguments)


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

    def _send(self, obj):
        """Write a JSON-RPC response line to stdout."""
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def _handle(self, msg):
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            self._send({
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            })

        elif method == "notifications/initialized":
            self._initialized = True
            logger.info("[AoTMCP] Client initialized — ready to serve tools.")

        elif method == "tools/list":
            tools = _get_all_tools(self._app)
            self._send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": tools}})

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                content = _execute_tool(self._app, tool_name, arguments)
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

    http_app = Flask("aot_mcp_http")

    @http_app.route("/mcp/info", methods=["GET"])
    def info():
        tools = _get_all_tools(app)
        return jsonify({
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "protocol": PROTOCOL_VERSION,
            "tool_count": len(tools),
        })

    @http_app.route("/mcp/tools/list", methods=["GET"])
    def tools_list():
        tools = _get_all_tools(app)
        return jsonify({"tools": tools})

    @http_app.route("/mcp/tools/call", methods=["POST"])
    def tools_call():
        data = request.get_json(silent=True) or {}
        tool_name = data.get("name", "")
        arguments = data.get("arguments", {})
        if not tool_name:
            return jsonify({"error": "Missing 'name' field"}), 400
        try:
            content = _execute_tool(app, tool_name, arguments)
            return jsonify({"content": content})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 400

    logger.info(f"[AoTMCP] HTTP mode started on port {port}")
    http_app.run(host="0.0.0.0", port=port, debug=False)


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

    if args.http:
        _run_http_server(app, port=args.port)
    else:
        server = StdioMCPServer(app)
        server.run()


if __name__ == "__main__":
    main()
