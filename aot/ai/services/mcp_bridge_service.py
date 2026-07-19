# coding=utf-8
import json
import logging
import os
import subprocess
import threading
import select
from typing import Dict, List, Optional
from aot.databases.models import MCPServer
from aot.config import MCP_FAILURE_COOLDOWN_SECONDS, INSTALL_DIRECTORY  # v23 (MCP_T06)

logger = logging.getLogger(__name__)

# [TASK_27] Set timeout to 60s to account for large DB initializations
# Timeout for MCP server responses (seconds)
MCP_READ_TIMEOUT = 60
MCP_INIT_TIMEOUT = 60


class MCPBridgeService:
    """
    Service to manage external MCP Server processes and their life-cycle.
    Maintains persistent stdio connections for high performance.
    Implements the MCP protocol initialize handshake.
    """
    _instances: Dict[str, subprocess.Popen] = {}
    _initialized: Dict[str, bool] = {}
    _tools_cache: Dict[str, List[dict]] = {}
    _resources_cache: Dict[str, List[dict]] = {}
    _prompts_cache: Dict[str, List[dict]] = {}
    _failure_counts: Dict[str, int] = {}
    _failed_servers: Dict[str, float] = {}  # server_id -> failure timestamp (cooldown)
    # @ANCHOR: HEARTBEAT_LAST_SEEN (TASK_7_8 Step 1)
    # In-memory heartbeat timestamps updated by health_check_all() on each 'ok' result.
    # get_server_status() uses this to enforce 120s expiry (Pessimistic Status).
    _last_seen: Dict[str, float] = {}  # server_id -> unix timestamp of last confirmed healthy check
    _HEARTBEAT_EXPIRY_SECONDS: int = 120
    _lock = threading.Lock()
    _request_counter: int = 0

    @classmethod
    def _next_request_id(cls) -> str:
        cls._request_counter += 1
        return str(cls._request_counter)

    @classmethod
    def _read_response(cls, process: subprocess.Popen, timeout: float = MCP_READ_TIMEOUT) -> Optional[dict]:
        """
        Read a single JSON-RPC response line from stdout with timeout.
        Returns parsed dict or None on failure.
        """
        try:
            # Use select for timeout on Unix (the AoT server runs on Linux)
            ready, _, _ = select.select([process.stdout], [], [], timeout)
            if not ready:
                logger.warning("[MCPBridge] Read timeout - no response from MCP server")
                return None

            line = process.stdout.readline()
            if not line:
                logger.warning("[MCPBridge] Empty response (EOF) from MCP server")
                return None

            return json.loads(line.strip())
        except json.JSONDecodeError as e:
            logger.error(f"[MCPBridge] Invalid JSON from MCP server: {e}")
            return None
        except Exception as e:
            logger.error(f"[MCPBridge] Read error: {e}")
            return None

    @classmethod
    def _send_request(cls, process: subprocess.Popen, method: str, params: dict = None, request_id: str = None) -> Optional[dict]:
        """
        Send a JSON-RPC 2.0 request and read the response.
        """
        rid = request_id or cls._next_request_id()
        request = {
            "jsonrpc": "2.0",
            "method": method,
            "id": rid
        }
        if params:
            request["params"] = params

        try:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            return cls._read_response(process)
        except (BrokenPipeError, OSError) as e:
            logger.error(f"[MCPBridge] Pipe error sending {method}: {e}")
            return None

    @classmethod
    def _send_notification(cls, process: subprocess.Popen, method: str, params: dict = None):
        """
        Send a JSON-RPC 2.0 notification (no id, no response expected).
        """
        notification = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            notification["params"] = params

        try:
            process.stdin.write(json.dumps(notification) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.error(f"[MCPBridge] Pipe error sending notification {method}: {e}")

    @classmethod
    def _do_initialize(cls, process: subprocess.Popen, server_id: str) -> bool:
        """
        Perform the MCP protocol initialize handshake.
        1. Send 'initialize' request
        2. Receive server capabilities
        3. Send 'notifications/initialized' notification
        """
        logger.info(f"[MCPBridge] Starting initialize handshake for {server_id}")

        response = cls._send_request(process, "initialize", params={
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "AoT-MCPBridge",
                "version": "1.0.0"
            }
        })

        if not response:
            logger.error(f"[MCPBridge] Initialize failed for {server_id}: no response")
            return False

        if "error" in response:
            logger.error(f"[MCPBridge] Initialize error for {server_id}: {response['error']}")
            return False

        server_info = response.get("result", {}).get("serverInfo", {})
        logger.info(f"[MCPBridge] Server {server_id} initialized: {server_info.get('name', 'unknown')} v{server_info.get('version', '?')}")

        # Send initialized notification
        cls._send_notification(process, "notifications/initialized")

        cls._initialized[server_id] = True
        return True

    @classmethod
    def _drain_stderr(cls, process: subprocess.Popen, server_id: str):
        """
        Daemon thread to drain stderr of an MCP subprocess and log it.
        """
        try:
            for line in iter(process.stderr.readline, ''):
                if line:
                    logger.info(f"[MCPBridge][stderr][{server_id}] {line.strip()}")
        except Exception as e:
            logger.debug(f"[MCPBridge] Stderr drain thread loop ended for {server_id}: {e}")
        finally:
            logger.debug(f"[MCPBridge] Stderr drain thread terminated for {server_id}")

    @classmethod
    def _drain_stderr_thread(cls, server_id: str, process: subprocess.Popen) -> None:
        """
        Daemon thread: continuously drains stderr of an MCP subprocess.
        Logs each non-empty line with prefix '[MCPBridge][stderr][{server_id}]'.
        Terminates cleanly when the process exits (empty readline + poll() not None).
        Added by MCP_T12 (TASK_22) — canonical method name per plan spec.
        """
        try:
            while True:
                line = process.stderr.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    continue
                logger.warning(f"[MCPBridge][stderr][{server_id}] {line.rstrip()}")
        except Exception as e:
            logger.warning(f"[MCPBridge] _drain_stderr_thread for {server_id} ended: {e}")

    @classmethod
    def get_server_process(cls, server_id: str) -> Optional[subprocess.Popen]:
        """Get or start a persistent process for the given MCP server."""
        import time as _time
        with cls._lock:
            # v6: Skip recently failed servers (5-minute cooldown)
            if server_id in cls._failed_servers:
                elapsed = _time.time() - cls._failed_servers[server_id]
                if elapsed < MCP_FAILURE_COOLDOWN_SECONDS:  # configurable (default 300s), set via MCP_FAILURE_COOLDOWN env var
                    return None
                else:
                    del cls._failed_servers[server_id]

            if server_id in cls._instances:
                # Check if process is still alive
                if cls._instances[server_id].poll() is None:
                    return cls._instances[server_id]
                else:
                    logger.warning(f"MCP Server '{server_id}' process terminated. Restarting...")
                    del cls._instances[server_id]
                    cls._initialized.pop(server_id, None)
                    cls._tools_cache.pop(server_id, None)

            # Start new process
            server = MCPServer.query.filter_by(unique_id=server_id).first()
            if not server or not server.is_activated:
                logger.error(f"MCP Server '{server_id}' not found or not activated.")
                return None

            try:
                # v16: Inject agent custom options (URL, Tokens) into environment/command
                env = os.environ.copy()
                server_command = cls._inject_agent_config(server_id, server.command, env)
                # v2.5: Dynamic path resolution (Law 1) — via mcp_config (no hardcoded paths)
                try:
                    from aot.config.mcp_config import BRIDGE_CONFIG
                    project_root = BRIDGE_CONFIG.get('root_path', INSTALL_DIRECTORY)
                except ImportError:
                    project_root = os.getenv('AOT_ROOT', INSTALL_DIRECTORY)
                server_command = server_command.replace('{{paths.project_root}}', project_root)
                # Replace any legacy absolute path fragments with dynamic root
                import re as _re
                server_command = _re.sub(r'/[^\s]*/Build/[^/]+/', project_root + '/', server_command)

                # Guard: Skip subprocess for Virtual MCP (empty command)
                if not server_command or not server_command.strip():
                    logger.warning(f"[MCPBridge] Skipping subprocess for '{server.name}' — no command defined (Virtual MCP).")
                    cls._failed_servers[server_id] = _time.time()
                    return None

                custom_env = server.env_vars
                if custom_env:
                    env.update(custom_env)

                process = subprocess.Popen(
                    server_command,
                    shell=True,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                    text=True,
                    bufsize=1
                )
                cls._instances[server_id] = process
                logger.info(f"Started MCP Server process: {server.name} (PID: {process.pid}, CMD: {server.command})")

                # v22: Spawn daemon thread to drain stderr to logs/aot.log (MCP_T12)
                # Note: spawned before _do_initialize() to capture init-phase stderr (TG-03 safe).
                stderr_thread = threading.Thread(
                    target=cls._drain_stderr_thread,
                    args=(server_id, process),
                    daemon=True
                )
                stderr_thread.start()

                # Perform MCP initialize handshake
                if not cls._do_initialize(process, server_id):
                    logger.error(f"[MCPBridge] Initialize handshake failed for {server.name}. Killing process.")
                    # v18: Standardized - daemon thread started above handles all stderr logging.
                    # Redundant manual read removed to resolve race condition TG-03.
                    process.terminate()
                    del cls._instances[server_id]
                    # v6: Mark as failed to prevent repeated startup attempts
                    cls._failed_servers[server_id] = _time.time()
                    return None

                return process
            except Exception as e:
                logger.error(f"Failed to start MCP Server '{server_id}': {e}")
                return None

    @classmethod
    def get_active_servers(cls) -> List['MCPServer']:
        """
        [OPTION_D] Returns a list of MCPServer objects that are currently running.
        Decorates each object with a 'tool_names' attribute from the cache.
        """
        from aot.databases.models.mcp_server import MCPServer
        with cls._lock:
            active_ids = [sid for sid, proc in cls._instances.items() if proc.poll() is None]
        
        # v26: Query servers and attach cached tool names for the resolver
        try:
            servers = MCPServer.query.filter(MCPServer.unique_id.in_(active_ids)).all()
            for s in servers:
                tools = cls._tools_cache.get(s.unique_id, [])
                s.tool_names = [t.get('name') for t in tools]
            return servers
        except Exception as e:
            logger.error(f"[get_active_servers] Database query failed: {e}")
            return []

    @classmethod
    def call_tool(cls, server_id: str, tool_name: str, arguments: dict, agent_unique_id: str = None) -> dict:
        """Call a specific tool on an MCP server via JSON-RPC over stdio."""
        # [DEBUG-BUG09] @ANCHOR: CALL_TOOL_DEBUG_LOG — log actual arguments reaching MCP layer
        logger.warning("[DEBUG-BUG09] call_tool server=%s tool=%s args=%r", server_id, tool_name, arguments)
        process = cls.get_server_process(server_id)
        if not process:
            return {"status": "error", "message": "Server process not available"}

        if not cls._initialized.get(server_id):
            return {"status": "error", "message": "Server not initialized"}

        # v23 (MCP_T09): Per-tool ACL — Default Deny
        if not cls._check_tool_access(agent_unique_id, server_id, tool_name):
            return {"status": "error", "message": f"Access denied: tool '{tool_name}' not permitted."}

        response = cls._send_request(process, "tools/call", params={
            "name": tool_name,
            "arguments": arguments
        })

        if not response:
            # Process may have died - clean up for next attempt
            cls._cleanup_server(server_id)
            return {"status": "error", "message": "No response from MCP server (timeout or crash)"}

        if "error" in response:
            return {"status": "error", "message": response["error"].get("message", "Unknown MCP error")}

        result = response.get("result", {})
        # v21: Validate tool result schema (Non-fatal)
        schema_ok = cls._validate_tool_result(server_id, tool_name, result)
        if not schema_ok:
            # Mark result metadata so caller (ai_action_service) knows validation failed
            result["_schema_warn"] = True

        return {"status": "success", "result": result}

    @classmethod
    def get_tools(cls, server_id: str, force_refresh: bool = False) -> List[dict]:
        """Fetch available tools from the MCP server."""
        if not force_refresh and server_id in cls._tools_cache:
            return cls._tools_cache[server_id]

        # v6: Handle Virtual MCPs (no command)
        server = MCPServer.query.filter_by(unique_id=server_id).first()
        if server and not server.command:
            logger.info(f"[MCPBridge] Checking virtual tools for server {server_id}")
            from aot.databases.models.mcp_server import AgentMCPAccess
            mapping = AgentMCPAccess.query.filter_by(mcp_unique_id=server_id).first()
            if mapping:
                logger.info(f"[MCPBridge] Found mapping: Agent {mapping.agent_unique_id}")
                from aot.databases.models.ai import AIAgent, AIEntry
                agent = AIAgent.query.filter_by(unique_id=mapping.agent_unique_id).first()
                if agent:
                    entry = AIEntry.query.filter_by(unique_id=agent.entry_id).first()
                    model_type = entry.model_type if entry else None
                    logger.info(f"[MCPBridge] Agent found: {agent.name}, Entry: {entry.name if entry else 'None'}, Type: {model_type}")
                    if model_type:
                        from aot.ai.services.ai_agent_service import AIAgentService
                        info = AIAgentService.get_engine_info(model_type)
                        engine_class = info.get('engine_class')
                        if engine_class and hasattr(engine_class, 'get_tools'):
                            tools = engine_class.get_tools()
                            logger.info(f"[MCPBridge] Virtual Tools Found: {len(tools)}")
                            return tools
                        else:
                            logger.warning(f"[MCPBridge] No get_tools method in engine {model_type}")
                else:
                    logger.warning(f"[MCPBridge] Agent mapping exists but agent record missing: {mapping.agent_unique_id}")
            else:
                logger.warning(f"[MCPBridge] No mapping found for virtual server {server_id}")
            return []

        process = cls.get_server_process(server_id)
        if not process:
            return []

        if not cls._initialized.get(server_id):
            logger.warning(f"[MCPBridge] Cannot list tools: server {server_id} not initialized")
            return []

        response = cls._send_request(process, "tools/list")

        if response and "result" in response:
            tools = response["result"].get("tools", [])
            with cls._lock:
                cls._tools_cache[server_id] = tools
            logger.info(f"[MCPBridge] Server {server_id}: {len(tools)} tools available")
            # @ANCHOR: ACTION_REGISTRY_AUTO_SYNC (REF-004)
            # Upsert discovered tools into AIActionRegistry post-connect (read-only, Law 3).
            try:
                from aot.ai.services.action_registry_sync import ActionRegistrySync
                ActionRegistrySync.sync(server_id)
            except Exception as _sync_err:
                logger.warning(f"[MCPBridge] Auto-Sync failed (non-fatal): {_sync_err}")
            return tools
        else:
            logger.warning(f"[MCPBridge] Failed to list tools for {server_id}")
            return []

    @classmethod
    def get_resources(cls, server_id: str, force_refresh: bool = False) -> List[dict]:
        """Fetch available resources from the MCP server (MCP_T04)."""
        if not force_refresh and server_id in cls._resources_cache:
            return cls._resources_cache[server_id]

        process = cls.get_server_process(server_id)
        if not process:
            return []

        if not cls._initialized.get(server_id):
            logger.warning(f"[MCPBridge] Cannot list resources: server {server_id} not initialized")
            return []

        response = cls._send_request(process, "resources/list")

        if response and "result" in response:
            resources = response["result"].get("resources", [])
            with cls._lock:
                cls._resources_cache[server_id] = resources
            logger.info(f"[MCPBridge] Server {server_id}: {len(resources)} resources available")
            return resources
        else:
            logger.warning(f"[MCPBridge] Failed to list resources for {server_id}")
            return []

    @classmethod
    def read_resource(cls, server_id: str, uri: str) -> dict:
        """Read a specific resource from the MCP server (MCP_T04)."""
        process = cls.get_server_process(server_id)
        if not process:
            return {"status": "error", "message": "Server process not available"}

        if not cls._initialized.get(server_id):
            return {"status": "error", "message": "Server not initialized"}

        response = cls._send_request(process, "resources/read", params={"uri": uri})

        if not response:
            return {"status": "error", "message": "No response from MCP server"}

        if "error" in response:
            return {"status": "error", "message": response["error"].get("message", "Unknown MCP error")}

        return {"status": "success", "result": response.get("result", {})}

    @classmethod
    def get_prompts(cls, server_id: str, force_refresh: bool = False) -> List[dict]:
        """Fetch available prompt templates from the MCP server (MCP_T07)."""
        if not force_refresh and server_id in cls._prompts_cache:
            return cls._prompts_cache[server_id]

        process = cls.get_server_process(server_id)
        if not process:
            return []

        if not cls._initialized.get(server_id):
            logger.warning(f"[MCPBridge] Cannot list prompts: server {server_id} not initialized")
            return []

        response = cls._send_request(process, "prompts/list")

        if response and "result" in response:
            prompts = response["result"].get("prompts", [])
            with cls._lock:
                cls._prompts_cache[server_id] = prompts
            logger.info(f"[MCPBridge] Server {server_id}: {len(prompts)} prompts available")
            return prompts
        else:
            logger.warning(f"[MCPBridge] Failed to list prompts for {server_id}")
            return []

    @classmethod
    def get_prompt_template(cls, server_id: str, prompt_name: str, arguments: dict = None) -> dict:
        """Get a specific prompt template from the MCP server (MCP_T07)."""
        process = cls.get_server_process(server_id)
        if not process:
            return {"status": "error", "message": "Server process not available"}

        if not cls._initialized.get(server_id):
            return {"status": "error", "message": "Server not initialized"}

        params = {"name": prompt_name}
        if arguments:
            params["arguments"] = arguments

        response = cls._send_request(process, "prompts/get", params=params)

        if not response:
            return {"status": "error", "message": "No response from MCP server"}

        if "error" in response:
            return {"status": "error", "message": response["error"].get("message", "Unknown MCP error")}

        return {"status": "success", "result": response.get("result", {})}

    @classmethod
    def health_check_all(cls) -> dict:
        """Perform health check on all activated MCP servers (MCP_T05).
        NOTE: Caller must ensure Flask app context is active (e.g., via app.app_context()).
        When called from scheduler, use the _mcp_health_check_job wrapper in app.py.
        """
        from aot.aot_flask.extensions import db
        results = {}

        # Get all activated servers from DB (caller provides app context)
        servers = MCPServer.query.filter_by(is_activated=True).all()

        for server in servers:
            sid = server.unique_id
            status = "ok"

            # 1. Attempt to get/start process
            process = cls.get_server_process(sid)

            # 2. If no process (failed startup or virtual failure)
            if not process:
                status = "degraded"
            else:
                # 3. Ping with tools/list (simple connectivity check)
                response = cls._send_request(process, "tools/list")
                if not response or "result" not in response:
                    status = "degraded"

            # 4. Manage failure counts
            if status == "degraded":
                cls._failure_counts[sid] = cls._failure_counts.get(sid, 0) + 1
                logger.warning(f"[MCPBridge][health] Server {server.name} ({sid}) is degraded. Failure count: {cls._failure_counts[sid]}")

                # Deactivate after 3 consecutive failures
                if cls._failure_counts[sid] >= 3:
                    logger.error(f"[MCPBridge][health] Server {server.name} ({sid}) failed 3 times. Deactivating.")
                    server.is_activated = False
                    db.session.commit()
                    cls.stop_server(sid)
                    status = "deactivated"
            else:
                cls._failure_counts[sid] = 0
                # @ANCHOR: HEARTBEAT_LAST_SEEN_UPDATE (TASK_7_8 Step 1)
                # Record the timestamp of the last confirmed healthy check.
                import time as _hc_time
                cls._last_seen[sid] = _hc_time.time()
                logger.debug(f"[MCPBridge][health] Server {server.name} ({sid}) is healthy.")

            results[sid] = status

        return results

    @classmethod
    def _validate_tool_result(cls, server_id: str, tool_name: str, result: dict) -> bool:
        """
        v21: Lightweight schema validation for MCP tool results (MCP_T11).
        Verifies 'content' list and basic type requirements.
        """
        # 1. Retrieve cached tool schema
        tools = cls._tools_cache.get(server_id, [])
        tool_def = next((t for t in tools if t.get('name') == tool_name), None)
        
        if not tool_def:
            # If no schema found: permissive (maybe cache was cleared)
            return True

        # 2. Verify result contains 'content' key (MCP spec requirement)
        if 'content' not in result:
            logger.warning(f"[MCPBridge][schema_warn] Tool '{tool_name}' result missing 'content' key from server {server_id}")
            return False

        content = result['content']
        if not isinstance(content, list):
            logger.warning(f"[MCPBridge][schema_warn] Tool '{tool_name}' result 'content' is not a list from server {server_id}")
            return False

        # 3. Verify each item has 'type' key
        for item in content:
            if not isinstance(item, dict) or 'type' not in item:
                logger.warning(f"[MCPBridge][schema_warn] Tool '{tool_name}' content item missing 'type' key from server {server_id}")
                return False

        return True

    @classmethod
    def _check_tool_access(cls, agent_unique_id: str, server_id: str, tool_name: str) -> bool:
        """
        v23 (MCP_T09): Per-tool access control check.
        - No agent_unique_id: return True (system/router calls — permissive).
        - No AgentMCPAccess mapping found: return False (Default Deny).
        - mapping.allowed_tool_list is None: return True (backward compat — all permitted).
        - tool_name in allowed_tool_list: return True, else return False (DENY + WARNING log).
        """
        if not agent_unique_id:
            return True
        from aot.databases.models.mcp_server import AgentMCPAccess
        mapping = AgentMCPAccess.query.filter_by(
            agent_unique_id=agent_unique_id,
            mcp_unique_id=server_id
        ).first()
        if not mapping:
            logger.warning(f"[MCPBridge][ACL] DENY — agent '{agent_unique_id}' has no access mapping for server '{server_id}'")
            return False
        allowed = mapping.allowed_tool_list
        if allowed is None:
            # @ANCHOR: OPERATE_DEVICE_ACL_FALLBACK (TASK_9-E / TASK_9-G / TASK_9-H — endpoint recovery)
            # Backward compat: all tools permitted when no per-tool whitelist is configured.
            # For 'operate_device', also refresh the server heartbeat to prevent PC-099 (stale session).
            # TASK_9-H: Relocated from dead code block (was after 'return True') to restore PC-099 fix.
            if tool_name == 'operate_device':
                import time as _rv_time
                logger.info(f"[MCPBridge][ACL] FALLBACK PERMIT — agent '{agent_unique_id}' granted 'operate_device' via safety override. (Heartbeat Re-validated)")
                with cls._lock:
                    cls._last_seen[server_id] = _rv_time.time()
            return True
        # Per-tool whitelist check
        if tool_name not in allowed:
            logger.warning(f"[MCPBridge][ACL] DENY — agent '{agent_unique_id}' tool '{tool_name}' not in whitelist for server '{server_id}'")
            return False
        return True

    @classmethod
    def _cleanup_server(cls, server_id: str):
        """Clean up a dead/failed server entry."""
        with cls._lock:
            process = cls._instances.pop(server_id, None)
            cls._initialized.pop(server_id, None)
            cls._tools_cache.pop(server_id, None)
            cls._failed_servers.pop(server_id, None)
            # v21: TG-04 clear failure count (consistent with stop_server / shutdown_all)
            cls._failure_counts.pop(server_id, None)
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    process.kill()

    @classmethod
    def get_tools_for_agent(cls, agent_unique_id: str) -> List[dict]:
        """
        v6: Returns all MCP tools accessible to a specific agent,
        based on its tool_access policy and AgentMCPAccess mappings.
        """
        from aot.databases.models import AIAgent
        from aot.databases.models.mcp_server import AgentMCPAccess

        agent = AIAgent.query.filter_by(unique_id=agent_unique_id).first()
        if not agent:
            return []

        tool_access = getattr(agent, 'tool_access', 'auto') or 'auto'

        if tool_access == 'none':
            return []
        elif tool_access == 'all':
            servers = MCPServer.query.filter_by(is_activated=True).filter(
                MCPServer.scope.in_(['general', 'assigned'])
            ).all()
        elif tool_access == 'assigned':
            mappings = AgentMCPAccess.query.filter_by(agent_unique_id=agent_unique_id).all()
            server_ids = [m.mcp_unique_id for m in mappings]
            if not server_ids:
                return []
            servers = MCPServer.query.filter(
                MCPServer.unique_id.in_(server_ids),
                MCPServer.is_activated == True
            ).all()
        else:  # 'auto' — legacy: all activated servers
            servers = MCPServer.query.filter_by(is_activated=True).all()

        all_tools = []
        for server in servers:
            tools = cls.get_tools(server.unique_id)
            # v23 (MCP_T09): Per-tool filtering by allowed_tool_list
            mapping = AgentMCPAccess.query.filter_by(
                agent_unique_id=agent_unique_id,
                mcp_unique_id=server.unique_id
            ).first() if agent_unique_id else None
            allowed = mapping.allowed_tool_list if (mapping and mapping.allowed_tool_list is not None) else None
            for tool in tools:
                if allowed is not None and tool.get('name') not in allowed:
                    continue
                tool['_server_id'] = server.unique_id
                tool['_server_name'] = server.name
                all_tools.append(tool)
        return all_tools

    @classmethod
    def _inject_agent_config(cls, server_id: str, server_command: str, env: dict) -> str:
        """
        Lookup the AIAgent linked to this server_id and inject its custom options
        into environment variables or the command line based on AI_INFORMATION metadata.
        v6: Also checks AgentMCPAccess mapping table for decoupled agents.
        """
        from aot.databases.models import AIAgent
        from aot.databases.models.mcp_server import AgentMCPAccess
        from aot.ai.services.ai_agent_service import AIAgentService

        # v6: Try mapping table first (decoupled), then fall back to legacy 1:1
        agent = None
        mapping = AgentMCPAccess.query.filter_by(mcp_unique_id=server_id.strip()).first()
        if mapping:
            agent_uid = mapping.agent_unique_id.strip()
            agent = AIAgent.query.filter_by(unique_id=agent_uid).first()
            logger.info(f"[MCPBridge] Mapping found for server {server_id} -> Agent UID {agent_uid} (Obj: {agent.name if agent else 'NULL'})")
        if not agent:
            agent = AIAgent.query.filter_by(unique_id=server_id.strip()).first()
            if agent:
                logger.info(f"[MCPBridge] Legacy 1:1 agent found for server {server_id}")
        if not agent:
            logger.warning(f"[MCPBridge] No agent found for server {server_id} in mapping or legacy.")
            return server_command

        # Identify model_type to get the correct metadata
        from aot.databases.models.ai import AIEntry
        entry_id = agent.entry_id
        entry = AIEntry.query.filter_by(unique_id=entry_id).first()
        model_type = entry.model_type if entry else None
        logger.info(f"[MCPBridge] Resolving config for {agent.name}. Entry: {entry.name if entry else 'None'}, Type: {model_type}")

        if not model_type:
            # v6: Fallback for MCP-only entries that might not have a full AIEntry but the agent is still mcp_*
            # Though AIAgent should always have an entry.
            return server_command
            
        info = AIAgentService.get_engine_info(model_type)
        custom_options_def = info.get('custom_options', [])
        
        try:
            values = json.loads(agent.custom_options_json) if agent.custom_options_json else {}
        except Exception:
            values = {}

        # Auto-populate InfluxDB settings from misc table when not configured by user.
        # This eliminates the need to visit the InfluxDB web UI after installation.
        if model_type == 'mcp_influxdb':
            try:
                from aot.databases.models.misc import Misc
                from aot.config import INFLUXDB_PORT, resolve_measurement_db_host
                settings = Misc.query.first()
                if settings:
                    if not values.get('influxdb_token') and settings.measurement_db_password:
                        values['influxdb_token'] = settings.measurement_db_password
                        logger.info("[MCPBridge] InfluxDB token auto-populated from misc.measurement_db_password")
                    if not values.get('influxdb_url'):
                        _host = resolve_measurement_db_host(settings.measurement_db_host or 'localhost')
                        _port = INFLUXDB_PORT or settings.measurement_db_port or '8086'
                        values['influxdb_url'] = f"http://{_host}:{_port}"
                        logger.info(f"[MCPBridge] InfluxDB URL auto-populated: {values['influxdb_url']}")
                    if not values.get('influxdb_bucket') and settings.measurement_db_dbname:
                        values['influxdb_bucket'] = settings.measurement_db_dbname
                        logger.info("[MCPBridge] InfluxDB bucket auto-populated from misc.measurement_db_dbname")
                    if not values.get('influxdb_org'):
                        values['influxdb_org'] = 'aot'
            except Exception as _e:
                logger.warning(f"[MCPBridge] InfluxDB auto-config failed: {_e}")

        for opt in custom_options_def:
            opt_id = opt.get('id')
            val = values.get(opt_id)
            if not val:
                continue
                
            # 1. Environment Variable Injection
            env_var = opt.get('env_var')
            if env_var:
                env[env_var] = str(val)
                logger.info(f"[MCPBridge] Injected env: {env_var} from agent metadata")
                
            # 2. Command Line Argument Injection
            if opt.get('is_cmd_arg'):
                # Only append if not already present in command
                if str(val) not in server_command:
                    server_command = f"{server_command} \"{val}\""
                    logger.info(f"[MCPBridge] Appended value to command from metadata: {opt_id}")

        return server_command

    @classmethod
    def stop_server(cls, server_id: str):
        """Stop a single MCP server process."""
        with cls._lock:
            process = cls._instances.pop(server_id, None)
            if process:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    process.kill()
                logger.info(f"Stopped MCP Server: {server_id}")
            cls._initialized.pop(server_id, None)
            cls._tools_cache.pop(server_id, None)
            cls._failed_servers.pop(server_id, None)
            # v21: TG-04 clear failure count
            if server_id in cls._failure_counts:
                del cls._failure_counts[server_id]

    @classmethod
    def get_server_status(cls, server_id: str) -> str:
        """Return live status string for the given server_id.
        Values: 'running' | 'cooldown' | 'stopped'
        Added by TASK_25 (BF-05).
        TASK_7_8 Step 1: Pessimistic Status — if last_seen is older than
        _HEARTBEAT_EXPIRY_SECONDS (120s), force 'stopped' regardless of process state.
        Truth (current time) over stale in-memory flags.
        """
        import time as _st_time
        with cls._lock:
            # @ANCHOR: HEARTBEAT_EXPIRY_GUARD (TASK_7_8 Step 1)
            last_seen = cls._last_seen.get(server_id)
            if last_seen is not None:
                elapsed = _st_time.time() - last_seen
                if elapsed > cls._HEARTBEAT_EXPIRY_SECONDS:
                    logger.warning(
                        f"[MCPBridge][status] Server '{server_id}' last_seen {elapsed:.0f}s ago "
                        f"(> {cls._HEARTBEAT_EXPIRY_SECONDS}s threshold). Forcing OFFLINE."
                    )
                    return 'stopped'

            process = cls._instances.get(server_id)
            if process and process.poll() is None:
                return 'running'
            if server_id in cls._failed_servers:
                return 'cooldown'
            return 'stopped'

    @classmethod
    def restart_server(cls, server_id: str) -> dict:
        """Stop and restart an MCP server process (MCP_T09)."""
        logger.info(f"[MCPBridge] Restarting server {server_id}...")
        cls.stop_server(server_id)
        # Clear failure history so restart begins with a clean state
        # v20: Manual pop (legacy) - redundant after stop_server change but safe
        with cls._lock:
            cls._failure_counts.pop(server_id, None)
        process = cls.get_server_process(server_id)
        if process:
            logger.info(f"[MCPBridge] Server {server_id} restarted successfully.")
            return {"status": "success", "message": f"Server {server_id} restarted."}
        else:
            logger.error(f"[MCPBridge] Server {server_id} failed to restart.")
            return {"status": "error", "message": f"Server {server_id} failed to restart."}

    @classmethod
    def shutdown_all(cls):
        """Cleanup all MCP processes on system shutdown."""
        with cls._lock:
            for server_id, process in cls._instances.items():
                try:
                    process.terminate()
                    process.wait(timeout=2)
                    logger.info(f"Terminated MCP Server: {server_id}")
                except Exception:
                    process.kill()
            cls._instances.clear()
            cls._initialized.clear()
            cls._tools_cache.clear()
            cls._failed_servers.clear()
            # v21: TG-04 clear all failure counts
            cls._failure_counts.clear()
