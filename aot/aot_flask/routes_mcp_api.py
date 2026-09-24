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


#: 엔드포인트별로 필요한 역할 권한. 여기 없는 것(승인 대기 목록·화면)은 로그인만 본다.
#:
#: 이 블루프린트는 `login_required` 만 걸려 있어서 **게스트도** 다음을 할 수 있었다
#: (2026-09-18 E2E 권한 경계 검사가 실측으로 잡음):
#:   - AI 가 올린 물리 제어 요청을 승인해 **출력을 실제로 켠다** — 같은 동작을
#:     직접 누르는 `/output_mod` 는 `edit_controllers` 를 요구하는데, 승인을 거치면
#:     그 검사를 건너뛰었다.
#:   - MCP 서버의 실행 명령과 환경변수(API 키가 들어가는 자리)를 읽는다.
#:   - MCP 서버를 등록·시험·재시작한다 — 등록한 명령은 서버 프로세스로 실행된다.
#:
#: 승인은 "대신 눌러 주는 것" 이므로 직접 누를 자격보다 넓을 수 없다. 그 자격은
#: **도구마다** 다르다(`mcp_safety_gate.required_write_permission` — 노트·지식·
#: 지도 편집 `edit_settings`, 작기 운영 `edit_plots`, 나머지 `edit_controllers`).
#: 그래서 승인·거부 엔드포인트는 여기서 "무엇이든 하나는 결정할 수 있는 사람"
#: 인지만 보고(`_DECIDE_ENDPOINTS`), 항목별 판정은 `mcp_safety_gate._decide` 가
#: 한다. 예전에는 전부 `edit_controllers` 여서 작기 운영만 맡은 사람은 자기
#: 구획 요청도 못 결정했고, 제어만 가진 사람이 구획 편집을 승인했다.
_DECIDE_ENDPOINTS = frozenset({
    'routes_mcp_api.mcp_confirmation_approve',
    'routes_mcp_api.mcp_confirmation_reject',
    'routes_mcp_api.mcp_confirmation_batch_approve',
    'routes_mcp_api.mcp_confirmation_batch_reject',
})

_REQUIRED_PERMISSION = {
    'routes_mcp_api.mcp_server_test': 'edit_settings',
    'routes_mcp_api.mcp_server_stop': 'edit_settings',
    'routes_mcp_api.mcp_server_restart': 'edit_settings',
    'routes_mcp_api.aot_mcp_start': 'edit_settings',
    'routes_mcp_api.aot_mcp_stop': 'edit_settings',
    'routes_mcp_api.aot_mcp_restart': 'edit_settings',
    'routes_mcp_api.mcp_server_tools': 'view_settings',
    'routes_mcp_api.aot_mcp_status': 'view_settings',
    'routes_mcp_api.mcp_audit_recent': 'view_logs',
    # 호출 품질 지표 — 감사 기록에서 계산하므로 감사 목록과 같은 권한.
    # (화면 AI → 기록 자체는 edit_controllers 가 있어야 열린다. API 가 더 넓다.)
    'routes_mcp_api.mcp_call_quality': 'view_logs',
}

#: 한 엔드포인트가 읽기와 쓰기를 함께 받는 경우 — 읽기는 설정 보기, 쓰기는 설정 편집.
_READ_WRITE_ENDPOINTS = frozenset({
    'routes_mcp_api.mcp_servers',
    'routes_mcp_api.mcp_server_detail',
})


@blueprint.before_request
def _require_role_permission():
    # 로그인하지 않은 요청은 각 라우트의 login_required 가 로그인으로 돌려보낸다.
    # 여기서 403 을 먼저 주면 그 흐름이 깨진다.
    if not flask_login.current_user.is_authenticated:
        return None

    if request.endpoint in _DECIDE_ENDPOINTS:
        from aot.aot_flask.utils import utils_general
        if (utils_general.user_has_permission('edit_controllers', silent=True)
                or utils_general.user_has_permission('edit_plots', silent=True)):
            return None
        from flask_babel import gettext
        return jsonify({
            "status": "error",
            "message": gettext("Insufficient permission: %(permission)s",
                               permission='edit_controllers'),
        }), 403

    permission = _REQUIRED_PERMISSION.get(request.endpoint)
    if request.endpoint in _READ_WRITE_ENDPOINTS:
        permission = 'view_settings' if request.method == 'GET' else 'edit_settings'
    if permission is None:
        return None

    from aot.aot_flask.utils import utils_general
    if utils_general.user_has_permission(permission, silent=True):
        return None
    from flask_babel import gettext
    return jsonify({
        "status": "error",
        "message": gettext("Insufficient permission: %(permission)s",
                           permission=permission),
    }), 403


def _parse_env(value):
    """설정 화면이 보낸 환경변수를 dict 로 — 아니면 (None, 이유).

    화면의 입력칸은 JSON **문자열**을 보낸다. 그것을 그대로 저장하면 문자열
    안에 JSON 이 든 채로 남는다(모델 `env_vars` 참고). 객체가 아니면 저장하지
    않고 이유를 돌려준다 — 조용히 빈 값으로 바꾸면 API 키가 사라진다.
    """
    if value is None or value == '':
        return {}, None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            return None, f"env_json is not valid JSON: {exc}"
    if not isinstance(value, dict):
        return None, "env_json must be a JSON object, e.g. {\"KEY\": \"value\"}"
    return {str(k): '' if v is None else str(v) for k, v in value.items()}, None


def _can_see_server_config():
    """실행 명령·환경변수(API 키 자리)는 설정을 **고칠 수 있는** 사람에게만."""
    from aot.aot_flask.utils import utils_general
    return utils_general.user_has_permission('edit_settings', silent=True)


@blueprint.route('/servers_page', methods=['GET'])
@flask_login.login_required
def mcp_servers_page():
    """Render the standalone MCP Server Management UI page."""
    from flask import render_template
    return render_template('pages/ai/mcp_servers.html', active_page='mcp_servers')

@blueprint.route('/servers', methods=['GET', 'POST'])
@flask_login.login_required
def mcp_servers():
    if request.method == 'GET':
        servers = MCPServer.query.all()
        show_config = _can_see_server_config()
        return jsonify([{
            "id": s.id,
            "unique_id": s.unique_id,
            "name": s.name,
            "command": s.command if show_config else None,
            "env_json": (json.dumps(s.env_vars) if s.env_vars else "") if show_config else None,  # v26 BF-07
            "scope": s.scope,
            "is_activated": s.is_activated,
            "status": MCPBridgeService.get_server_status(s.unique_id),  # v25 BF-05
            "created_at": s.created_at.isoformat() if s.created_at else None
        } for s in servers])
    
    elif request.method == 'POST':
        data = request.json
        env, env_error = _parse_env(data.get('env_json'))
        if env_error:
            return jsonify({"error": env_error}), 400
        try:
            new_server = MCPServer(
                name=data.get('name'),
                command=data.get('command'),
                scope=data.get('scope', 'general'),
                is_activated=data.get('is_activated', False)
            )
            new_server.env_vars = env  # v26 BF-06
            
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
        show_config = _can_see_server_config()
        return jsonify({
            "id": server.id,
            "unique_id": server.unique_id,
            "name": server.name,
            "command": server.command if show_config else None,
            "env_vars": server.env_vars if show_config else None,
            "scope": server.scope,
            "is_activated": server.is_activated
        })

    elif request.method == 'PUT':
        data = request.json
        if 'env_json' in data:
            env, env_error = _parse_env(data['env_json'])
            if env_error:
                return jsonify({"error": env_error}), 400
        try:
            if 'name' in data: server.name = data['name']
            if 'command' in data: server.command = data['command']
            if 'scope' in data: server.scope = data['scope']
            if 'is_activated' in data: server.is_activated = data['is_activated']
            if 'env_json' in data: server.env_vars = env  # v26 BF-06
            
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
# 외부 MCP 승인 큐 + 감사 로그 (aot/tools/mcp_safety_gate.py)
#
# 외부 AI가 쓰기 도구를 호출하면 MCP 서버 프로세스가 mcp_confirmation 에
# pending 행을 만들고 실행을 보류한다. 승인은 사람이 여기서 한다 — MCP 서버는
# 별도 프로세스라 인메모리로는 승인을 주고받을 수 없어 DB를 경유한다.
# =============================================================================

@blueprint.route('/review_page', methods=['GET'])
@flask_login.login_required
def mcp_review_page():
    """옛 "AI 요청 및 조언" 화면 — AI → 요청(승인·제안·조언)과 AI → 기록(도구 호출)으로
    나눠 옮겼다(2026-09-10). 북마크·문서 링크를 살리려고 주소는 남겨 요청으로 보낸다."""
    from flask import redirect, url_for
    return redirect(url_for('routes_ai_agent.page_ai_dashboard'))


def _current_role_row():
    """로그인한 사람의 DB 역할 행. 못 찾으면 None."""
    try:
        from aot.databases.models import Role
        role_id = getattr(flask_login.current_user, 'role_id', None)
        return Role.query.filter(Role.id == role_id).first() if role_id else None
    except Exception:
        return None


@blueprint.route('/confirmations', methods=['GET'])
@flask_login.login_required
def mcp_confirmations_list():
    """승인 대기 중인 외부 AI 쓰기 요청 목록."""
    from aot.tools import mcp_safety_gate as gate
    try:
        # 항목마다 이 사람이 결정할 수 있는지(can_decide)를 싣는다 — 화면이
        # 누를 수 없는 버튼을 그리지 않게. 막는 것은 승인 엔드포인트다.
        return jsonify({"status": "success",
                        "pending": gate.list_pending(viewer=_current_role_row())})
    except Exception as e:
        logger.error(f"MCP confirmations list failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


def _execution_unconfirmed(exec_status, exec_result):
    """승인 실행이 실패로 끝났지만 명령이 나갔을 수 있는가(performed "unknown")."""
    return (exec_status == 'failed' and isinstance(exec_result, dict)
            and exec_result.get('performed') == 'unknown')


@blueprint.route('/confirmations/<confirmation_id>/approve', methods=['POST'])
@flask_login.login_required
def mcp_confirmation_approve(confirmation_id):
    """대기 중인 요청을 승인하고 **그 자리에서 실행**한다.

    예전에는 승인이 실행 허가증일 뿐이어서, 사람이 승인 버튼을 누른 뒤 채팅으로
    돌아가 AI 에게 알려줘야 AI 가 재호출해 실행됐다(승인 후 5분 안에). 농가가
    한 마디 시킨 것을 반영하는 데 앱 전환 두 번이 필요했고, 승인해도 끝이 아니라는
    점이 특히 혼란스러웠다. 이제 승인이 곧 실행이다.

    실행은 저장해둔 인자로만 하므로 승인 화면에 보인 것과 실제 실행이 어긋나지
    않는다. 나중에 AI 가 _confirmation_id 로 재호출하면 재실행 없이 저장된 결과가
    돌아간다(mcp_safety_gate.gate 의 executed 분기).

    body 에 선택적으로 {"modified_params": {...}} 를 실어 보내면, 승인자가 값을
    고쳐서 승인한 것으로 취급한다(mcp_review 위젯의 "수정" 기능) — 그 값이 곧
    "화면에 보인 최종값"이 되어 그대로 실행된다. body 를 안 보내는 기존
    호출(스케줄러 화면 include 등)은 silent=True 라 그대로 동작한다.
    """
    from aot.tools import mcp_safety_gate as gate
    try:
        body = request.get_json(silent=True) or {}
        modified_params = body.get('modified_params')
        if modified_params is not None and not isinstance(modified_params, dict):
            return jsonify({"status": "error", "message": "modified_params must be an object"}), 400

        user_id = getattr(flask_login.current_user, 'unique_id', None)
        result = gate.approve(confirmation_id, user_id=user_id, modified_params=modified_params)
        if result.get('status') != 'success':
            # 그룹 스코프 거부는 "요청이 무효" 가 아니라 "이 승인자에게 권한이
            # 없음" 이므로 403 — 직접 제어 경로(scope.deny_message())와 같은
            # 뜻의 코드를 쓴다. 그 밖의 실패(만료·이미 처리됨 등)는 400 그대로.
            status_code = 403 if result.get('reason_code') == 'group_scope_denied' else 400
            return jsonify(result), status_code

        exec_status, exec_result = gate.execute_approved(confirmation_id)
        result['executed'] = (exec_status == 'executed')
        result['execution'] = exec_result
        # 명령은 나갔는데 결과를 모른다(시간 초과 등) — 화면이 "실패" 대신
        # "적용 여부 미확인 — 장치 상태를 확인" 을 보이게 한다. 행 상태는 failed.
        result['unconfirmed'] = _execution_unconfirmed(exec_status, exec_result)
        # 실행이 실패해도 승인 자체는 처리된 것이므로 200 으로 돌려주고, 화면이
        # 실패 사유를 그대로 보여준다. 400 으로 만들면 "승인이 안 됐다"로 오인된다.
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"MCP confirmation approve failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@blueprint.route('/confirmations/<confirmation_id>/reject', methods=['POST'])
@flask_login.login_required
def mcp_confirmation_reject(confirmation_id):
    """대기 중인 요청을 거부."""
    from aot.tools import mcp_safety_gate as gate
    try:
        user_id = getattr(flask_login.current_user, 'unique_id', None)
        result = gate.reject(confirmation_id, user_id=user_id)
        return jsonify(result), (200 if result.get('status') == 'success' else 400)
    except Exception as e:
        logger.error(f"MCP confirmation reject failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@blueprint.route('/confirmations/batch_approve', methods=['POST'])
@flask_login.login_required
def mcp_confirmation_batch_approve():
    """선택된 여러 요청을 원본 그대로 일괄 승인+즉시실행 (mcp_review 위젯의
    일괄처리용). 수정 파라미터는 받지 않는다 — 수정은 항목 하나씩만 다루는
    단건 전용 UX(여러 항목을 서로 다른 값으로 동시에 고치는 폼은 복잡도만
    커지고 실수요는 낮다고 보고 만들지 않음).

    부분 실패를 허용한다: 한 항목이 실패해도(만료, 이미 처리됨 등) 나머지는
    계속 처리하고, 항목별 결과를 모아 돌려준다.
    """
    from aot.tools import mcp_safety_gate as gate
    data = request.get_json(silent=True) or {}
    ids = data.get('confirmation_ids')
    if not isinstance(ids, list) or not ids:
        return jsonify({"status": "error", "message": "confirmation_ids (non-empty array) required"}), 400

    user_id = getattr(flask_login.current_user, 'unique_id', None)
    results = []
    for cid in ids:
        try:
            r = gate.approve(cid, user_id=user_id)
            if r.get('status') != 'success':
                results.append({"confirmation_id": cid, "ok": False,
                                "message": r.get('message'),
                                "reason_code": r.get('reason_code')})
                continue
            exec_status, exec_result = gate.execute_approved(cid)
            results.append({
                "confirmation_id": cid,
                "ok": True,
                "executed": exec_status == 'executed',
                "unconfirmed": _execution_unconfirmed(exec_status, exec_result),
                "execution": exec_result,
            })
        except Exception as e:
            logger.error(f"MCP batch approve item failed cid={cid}: {e}")
            results.append({"confirmation_id": cid, "ok": False, "message": str(e)})

    succeeded = sum(1 for r in results if r.get('ok'))
    return jsonify({
        "status": "success", "results": results,
        "succeeded": succeeded, "total": len(ids),
        "unconfirmed": sum(1 for r in results if r.get('unconfirmed')),
    }), 200


@blueprint.route('/confirmations/batch_reject', methods=['POST'])
@flask_login.login_required
def mcp_confirmation_batch_reject():
    """선택된 여러 요청을 일괄 거부 (mcp_review 위젯의 일괄처리용)."""
    from aot.tools import mcp_safety_gate as gate
    data = request.get_json(silent=True) or {}
    ids = data.get('confirmation_ids')
    if not isinstance(ids, list) or not ids:
        return jsonify({"status": "error", "message": "confirmation_ids (non-empty array) required"}), 400

    user_id = getattr(flask_login.current_user, 'unique_id', None)
    results = []
    for cid in ids:
        try:
            r = gate.reject(cid, user_id=user_id)
            results.append({"confirmation_id": cid, "ok": r.get('status') == 'success',
                             "message": r.get('message')})
        except Exception as e:
            logger.error(f"MCP batch reject item failed cid={cid}: {e}")
            results.append({"confirmation_id": cid, "ok": False, "message": str(e)})

    succeeded = sum(1 for r in results if r.get('ok'))
    return jsonify({"status": "success", "results": results,
                     "succeeded": succeeded, "total": len(ids)}), 200


def _audit_title(tool_name, params, permission=None):
    """AI → 기록의 도구 호출 한 줄 제목 — 도구 이름 원문(search_notes 등)은 싣지 않는다.

    synthesize_title 의 표는 승인이 걸리는 쓰기 도구만 채워 두어, 조회 도구는 원문
    이름으로 떨어졌다(2026-09-10 실측: open_drawer·search_notes 가 그대로 보였다).
    표에 없으면 도구가 든 서랍(tool_registry)의 범주로 사람 말을 만든다 — 새 도구가
    늘어도 따로 채울 것이 없다. 요청 문맥이 있어 번역된다."""
    from flask_babel import gettext as _t
    from aot.tools import mcp_safety_gate as gate
    name = tool_name or ''
    title = gate.synthesize_title(name, params)
    if title and title != name:
        return title
    meta = {
        'open_drawer': _t('Browsed the tool list'),
        'get_tool_detail': _t('Browsed the tool list'),
        'list_pending_confirmations': _t('Checked pending approvals'),
        'respond_to_confirmation': _t('Answered an approval request'),
    }
    if name in meta:
        return meta[name]
    drawer = None
    try:
        from aot.tools import tool_registry as reg
        # tier_of 는 배정이 없는 도구에 'system' 을 기본으로 준다 — 그대로 쓰면 모르는
        # 도구가 전부 "AI 설정·시스템 상태 조회" 가 된다. 배정된 도구만 서랍을 쓴다.
        if name in getattr(reg, '_TIER_ASSIGNMENT', {}):
            drawer = reg.tier_of(name)[0]
    except Exception:
        drawer = None
    if permission == 'read':
        by_drawer = {
            'device': _t('Looked up devices'),
            'measurement': _t('Read sensor values'),
            'function': _t('Looked up functions and controllers'),
            'schedule': _t('Looked up the schedule'),
            'record': _t('Looked up notes and knowledge'),
            'space': _t('Looked up the map and zones'),
            'definition': _t('Looked up device definitions'),
            'system': _t('Looked up AI settings and system status'),
        }
        return by_drawer.get(drawer) or _t('Looked something up')
    return _t('Made a change')


@blueprint.route('/audit', methods=['GET'])
@flask_login.login_required
def mcp_audit_recent():
    """최근 MCP 도구 호출 감사 로그 — 어느 AI가 무엇을 왜 호출했는지."""
    from aot.mcp_server import audit
    try:
        limit = min(int(request.args.get('limit', 50)), 500)
        from aot.tools import mcp_safety_gate as gate
        entries = audit.get_recent(
            limit=limit,
            agent_id=request.args.get('agent_id'),
            tool_name=request.args.get('tool_name'),
        )
        # 화면(AI → 기록)은 도구 이름·인자 원문 대신 사람 말 제목을 싣는다. 인자에는
        # 대상 UUID 가 들어 있어 응답에서도 뺀다(도구 이름은 필터용으로 남긴다).
        for e in entries:
            e['title'] = _audit_title(e.get('tool_name'), e.pop('params', None), e.get('permission'))
        return jsonify({"status": "success", "entries": entries})
    except Exception as e:
        logger.error(f"MCP audit query failed: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@blueprint.route('/quality', methods=['GET'])
@flask_login.login_required
def mcp_call_quality():
    """MCP 호출 품질 지표 — 호출 묶음·지연·오류·빈 결과·캡 발동.

    days: 1 | 7 | 30 (그 밖의 값은 7). transport: mcp_stdio | mcp_http | rest |
    in_app | 비움(전체). 응답에는 UUID·인자·agent_id·세션 열쇠가 없다.
    도구 이름(by_tool)은 여기에만 싣고 화면은 서랍 범주(by_category)만 쓴다.
    """
    from aot.mcp_server import quality
    try:
        try:
            days = int(request.args.get('days', 7))
        except (TypeError, ValueError):
            days = 7
        transport = request.args.get('transport') or None
        data = quality.compute_quality(days=days, transport=transport)
        return jsonify({"status": "success", "quality": data})
    except Exception as e:
        logger.error(f"MCP call quality failed: {e}")
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
