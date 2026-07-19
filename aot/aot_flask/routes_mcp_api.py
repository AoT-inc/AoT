# coding=utf-8
import logging
import json
from flask import Blueprint, jsonify, request
import flask_login
import select
import threading
import subprocess
import os
import platform
from aot.databases.models.mcp_server import MCPServer, AgentMCPAccess
from aot.aot_flask.extensions import db
from aot.ai.services.mcp_bridge_service import MCPBridgeService

logger = logging.getLogger(__name__)

blueprint = Blueprint('routes_mcp_api', __name__, url_prefix='/api/v1/mcp')

@blueprint.route('/servers_page', methods=['GET'])
@flask_login.login_required
def mcp_servers_page():
    """Render the standalone MCP Server Management UI page."""
    from flask import render_template
    return render_template('pages/ai/mcp_servers.html')

@blueprint.route('/servers', methods=['GET', 'POST'])
@flask_login.login_required
def mcp_servers():
    if request.method == 'GET':
        servers = MCPServer.query.all()
        return jsonify([{
            "id": s.id,
            "unique_id": s.unique_id,
            "name": s.name,
            "command": s.command,
            "env_json": json.dumps(s.env_vars) if s.env_vars else "",  # v26 BF-07
            "scope": s.scope,
            "is_activated": s.is_activated,
            "status": MCPBridgeService.get_server_status(s.unique_id),  # v25 BF-05
            "created_at": s.created_at.isoformat() if s.created_at else None
        } for s in servers])
    
    elif request.method == 'POST':
        data = request.json
        try:
            new_server = MCPServer(
                name=data.get('name'),
                command=data.get('command'),
                scope=data.get('scope', 'general'),
                is_activated=data.get('is_activated', False)
            )
            if 'env_json' in data:
                new_server.env_vars = data['env_json']  # v26 BF-06
            
            new_server.save()
            return jsonify({"status": "success", "unique_id": new_server.unique_id}), 201
        except Exception as e:
            logger.error(f"Error creating MCP server: {e}")
            return jsonify({"error": str(e)}), 400

@blueprint.route('/servers/<server_id>', methods=['GET', 'PUT', 'DELETE'])
@flask_login.login_required
def mcp_server_detail(server_id):
    server = MCPServer.query.filter_by(unique_id=server_id).first()
    if not server:
        return jsonify({"error": "Server not found"}), 404

    if request.method == 'GET':
        return jsonify({
            "id": server.id,
            "unique_id": server.unique_id,
            "name": server.name,
            "command": server.command,
            "env_vars": server.env_vars,
            "scope": server.scope,
            "is_activated": server.is_activated
        })

    elif request.method == 'PUT':
        data = request.json
        try:
            if 'name' in data: server.name = data['name']
            if 'command' in data: server.command = data['command']
            if 'scope' in data: server.scope = data['scope']
            if 'is_activated' in data: server.is_activated = data['is_activated']
            if 'env_json' in data: server.env_vars = data['env_json']  # v26 BF-06
            
            server.save()
            return jsonify({"status": "success"})
        except Exception as e:
            logger.error(f"Error updating MCP server: {e}")
            return jsonify({"error": str(e)}), 400

    elif request.method == 'DELETE':
        try:
            # Delete mappings first
            AgentMCPAccess.query.filter_by(mcp_unique_id=server_id).delete()
            server.delete()
            return jsonify({"status": "success"})
        except Exception as e:
            logger.error(f"Error deleting MCP server: {e}")
            return jsonify({"error": str(e)}), 400

@blueprint.route('/servers/<server_id>/test', methods=['POST'])
@flask_login.login_required
def mcp_server_test(server_id):
    """
    Ephemeral connection test: 
    start process -> initialize handshake -> tools/list -> return result -> terminate process.
    """
    server = MCPServer.query.filter_by(unique_id=server_id).first()
    if not server:
        return jsonify({"error": "Server not found"}), 404

    try:
        env = os.environ.copy()
        if server.env_vars:
            env.update(server.env_vars)

        process = subprocess.Popen(
            server.command,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1
        )

        # TG-02: Drain stderr in a background thread to prevent pipe saturation deadlock
        def _silent_drain(proc):
            try:
                for _ in proc.stderr:
                    pass
            except Exception:
                pass
        
        drain_thread = threading.Thread(target=_silent_drain, args=(process,), daemon=True)
        drain_thread.start()

        # 1. Initialize Handshake (One-off logic)
        init_req = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": "test-init",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "AoT-Test-UI", "version": "1.0.0"}
            }
        }
        process.stdin.write(json.dumps(init_req) + "\n")
        process.stdin.flush()
        
        # TG-01: Non-blocking read with timeout
        def _safe_read(pipe, timeout=10):
            r, _, _ = select.select([pipe], [], [], timeout)
            if r:
                return pipe.readline()
            return None

        line = _safe_read(process.stdout)
        init_res = json.loads(line) if line else {}
        
        if "error" in init_res or not init_res:
            process.terminate()
            return jsonify({"status": "error", "message": init_res.get("error", "No response/timeout during init")}), 400

        # 2. List Tools
        list_req = {"jsonrpc": "2.0", "method": "tools/list", "id": "test-list"}
        process.stdin.write(json.dumps(list_req) + "\n")
        process.stdin.flush()
        
        line = _safe_read(process.stdout)
        list_res = json.loads(line) if line else {}
        
        # 3. Cleanup
        process.terminate()
        
        return jsonify({
            "status": "success",
            "server_info": init_res.get("result", {}).get("serverInfo", {}),
            "tools": list_res.get("result", {}).get("tools", [])
        })

    except Exception as e:
        logger.error(f"MCP Test Failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@blueprint.route('/servers/<server_id>/tools', methods=['GET'])
@flask_login.login_required
def mcp_server_tools(server_id):
    """Return cached or live tools/list for an active server."""
    try:
        tools = MCPBridgeService.get_tools(server_id)
        return jsonify({"status": "success", "tools": tools})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@blueprint.route('/servers/<server_id>/stop', methods=['POST'])
@flask_login.login_required
def mcp_server_stop(server_id):
    """Stop a running MCP server process (TASK_25 BF-03)."""
    server = MCPServer.query.filter_by(unique_id=server_id).first()
    if not server:
        return jsonify({"error": "Server not found"}), 404
    try:
        MCPBridgeService.stop_server(server_id)
        return jsonify({"status": "success", "message": f"Server {server_id} stopped."})
    except Exception as e:
        logger.error(f"MCP Stop Failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@blueprint.route('/servers/<server_id>/restart', methods=['POST'])
@flask_login.login_required
def mcp_server_restart(server_id):
    """Stop and restart a running MCP server process (MCP_T09)."""
    server = MCPServer.query.filter_by(unique_id=server_id).first()
    if not server:
        return jsonify({"error": "Server not found"}), 404

    try:
        result = MCPBridgeService.restart_server(server_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"MCP Restart Failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# =============================================================================
# AoT MCP Server lifecycle control (systemd service: aotmcp)
# Controls the standalone AoT MCP Server process — separate from MCP 엔트리.
# =============================================================================

def _run_systemctl(action):
    """Run 'systemctl <action> aotmcp' and return (success, message)."""
    if platform.system() == 'Darwin':
        # v26.3 macOS Bypass (TASK_02): systemctl is not available on macOS.
        # Bypass for local dev environment.
        return True, f"macOS Bypass: aotmcp {action} OK"

    result = subprocess.run(
        ["systemctl", action, "aotmcp"],
        capture_output=True, text=True, timeout=15
    )
    if result.returncode == 0:
        return True, f"aotmcp {action} OK"
    return False, (result.stderr or result.stdout or f"systemctl {action} aotmcp failed").strip()


def _get_aot_mcp_server():
    from aot.databases.models.mcp_server import MCPServer
    return MCPServer.query.filter_by(name='AoT System Expert Server').first()

@blueprint.route('/aot-mcp/status', methods=['GET'])
@flask_login.login_required
def aot_mcp_status():
    """Return live status of the AoT MCP Server."""
    server = _get_aot_mcp_server()
    if server:
        status = MCPBridgeService.get_server_status(server.unique_id)
        # Map internal status to UI state
        # get_server_status() returns: 'running', 'cooldown', 'stopped'
        if status == 'running':
            state = 'active'
        elif status == 'cooldown':
            state = 'failed'
        else:
            state = 'inactive'
        return jsonify({"status": state})

    if platform.system() == 'Darwin':
        return jsonify({"status": "inactive", "note": "macOS: server record not found in DB"})

    result = subprocess.run(
        ["systemctl", "is-active", "aotmcp"],
        capture_output=True, text=True, timeout=5
    )
    return jsonify({"status": result.stdout.strip()})


@blueprint.route('/aot-mcp/start', methods=['POST'])
@flask_login.login_required
def aot_mcp_start():
    server = _get_aot_mcp_server()
    if server:
        try:
            # Tell the bridge to start tracking and spawning it
            server.is_activated = True
            server.save()
            MCPBridgeService.health_check_all() # force a spawn
            return jsonify({"status": "success", "message": "AoT MCP Server starting via Bridge"}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
            
    ok, msg = _run_systemctl("start")
    return jsonify({"status": "success" if ok else "error", "message": msg}), (200 if ok else 500)


@blueprint.route('/aot-mcp/stop', methods=['POST'])
@flask_login.login_required
def aot_mcp_stop():
    server = _get_aot_mcp_server()
    if server:
        try:
            MCPBridgeService.stop_server(server.unique_id)
            server.is_activated = False
            server.save()
            return jsonify({"status": "success", "message": "AoT MCP Server stopped via Bridge"}), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    ok, msg = _run_systemctl("stop")
    return jsonify({"status": "success" if ok else "error", "message": msg}), (200 if ok else 500)


@blueprint.route('/aot-mcp/restart', methods=['POST'])
@flask_login.login_required
def aot_mcp_restart():
    server = _get_aot_mcp_server()
    if server:
        try:
            server.is_activated = True
            server.save()
            result = MCPBridgeService.restart_server(server.unique_id)
            return jsonify(result), (200 if result.get('status') == 'success' else 500)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    ok, msg = _run_systemctl("restart")
    return jsonify({"status": "success" if ok else "error", "message": msg}), (200 if ok else 500)
