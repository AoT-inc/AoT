# coding=utf-8
"""카메라 드라이버(VIGI 등) 엔드포인트 — 연결 확인·다시 연결·기능 다시 읽기·인증서 신뢰·상태.

Open API 인증은 데몬만 한다. 여기서는 데몬 RPC 로 부탁하고 결과(비밀 없는 dict)를 돌려준다.
모든 POST 는 역할(edit_controllers) → 그룹 스코프(그 카메라의 탭) 순으로 **카메라에 닿기 전에** 묻는다.
연결 확인은 사용자가 누를 때만 일어난다(자동 호출 없음).
"""
from flask import Blueprint, jsonify, request
from flask_babel import gettext
from flask_login import current_user, login_required

from aot.aot_flask.access import scope
from aot.aot_flask.utils import utils_general
from aot.camera_drivers.status import build_status
from aot.databases.models import Camera, CameraDriver

blueprint = Blueprint('routes_camera_driver', __name__)

_POST_OPS = {
    'verify': 'verify',
    'reconnect': 'reconnect',
    'capabilities': 'refresh_capabilities',
    'cert_observe': 'observe_cert',
    'cert_trust': 'trust_new_cert',
}


def _status_of(camera_id, row):
    from aot.camera_drivers.status import recent_events
    from aot.aot_flask.extensions import db
    return build_status(row, recent_events(db.session, camera_id))


def _camera_or_404(camera_id):
    cam = Camera.query.filter_by(unique_id=camera_id).first()
    if cam is None or cam.library not in ('vigi', 'onvif'):
        return None
    return cam


@blueprint.route('/camera/driver/<camera_id>/status')
@login_required
def driver_status(camera_id):
    if not utils_general.user_has_permission('view_camera', silent=True):
        return jsonify({'status': 'error', 'message': gettext('Insufficient permission: view_camera')}), 403
    if _camera_or_404(camera_id) is None:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404
    row = CameraDriver.query.filter_by(camera_id=camera_id).first()
    return jsonify({'status': 'success', 'driver': _status_of(camera_id, row)})


@blueprint.route('/camera/driver/<camera_id>/<op>', methods=['POST'])
@login_required
def driver_op(camera_id, op):
    if op not in _POST_OPS:
        return jsonify({'status': 'error', 'message': 'Unknown operation'}), 404
    if not utils_general.user_has_permission('edit_controllers', silent=True):
        return jsonify({'status': 'error',
                        'message': gettext('Insufficient permission: edit_controllers')}), 403
    # 그룹 스코프 — 카메라에 자격 증명이 가기 전에 묻는다
    if not scope.can_operate_device(camera_id):
        return jsonify({'status': 'error', 'message': scope.deny_message()}), 403
    if _camera_or_404(camera_id) is None:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404

    arg = None
    if op == 'cert_trust':
        arg = (request.get_json(silent=True) or {}).get('fingerprint', '')

    from aot.aot_client import DaemonControl
    result = DaemonControl().camera_driver_call(_POST_OPS[op], camera_id, arg)
    row = CameraDriver.query.filter_by(camera_id=camera_id).first()
    return jsonify({'status': 'success' if result.get('ok') else 'error',
                    'result': result, 'driver': _status_of(camera_id, row)})


# -- 제어 (P3) — PTZ·프리셋·주야·경보·알림 스위치 --------------------------------
# 요청 본문의 op 이름 → 데몬 제어 op. 모두 카메라를 움직이거나 울리거나 설정을 쓴다.
_CONTROL_OPS = {
    'ptz_move': 'ptz_move', 'ptz_keepalive': 'ptz_keepalive', 'ptz_stop': 'ptz_stop',
    'ptz_goto': 'ptz_goto', 'ptz_set_preset': 'ptz_set_preset',
    'ptz_remove_preset': 'ptz_remove_preset',
    'day_night_get': 'day_night_get', 'day_night_set': 'day_night_set',
    'alarm': 'alarm', 'msg_push_on': 'msg_push_on',
}


@blueprint.route('/camera/driver/<camera_id>/control/<op>', methods=['POST'])
@login_required
def driver_control(camera_id, op):
    # 가장 먼저: 역할 → 그룹 스코프. 카메라에도 데몬에도 닿기 전에 묻는다.
    if not utils_general.user_has_permission('edit_controllers', silent=True):
        return jsonify({'status': 'error',
                        'message': gettext('Insufficient permission: edit_controllers')}), 403
    if not scope.can_operate_device(camera_id):
        return jsonify({'status': 'error', 'message': scope.deny_message()}), 403
    if op not in _CONTROL_OPS:
        return jsonify({'status': 'error', 'message': 'Unknown operation'}), 404
    if _camera_or_404(camera_id) is None:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404

    body = request.get_json(silent=True) or {}
    arg = {k: body[k] for k in ('vector', 'speed', 'preset', 'name', 'mode', 'start', 'kind')
           if k in body}
    from aot.aot_client import DaemonControl
    result = DaemonControl().camera_control_call(_CONTROL_OPS[op], camera_id, arg)
    return jsonify({'status': 'success' if result.get('ok') else 'error', 'result': result})


# -- 이벤트 구독 설정 (P4) ------------------------------------------------------------
@blueprint.route('/camera/driver/<camera_id>/events', methods=['POST'])
@login_required
def driver_events(camera_id):
    """이벤트 구독 켬/끔과 받을 종류를 저장하고 데몬에 구독을 맞추도록 알린다.
    역할 → 그룹 스코프를 맨 앞에서 묻는다. 카메라에는 닿지 않는다(구독은 데몬이 알아서 붙는다)."""
    if not utils_general.user_has_permission('edit_controllers', silent=True):
        return jsonify({'status': 'error',
                        'message': gettext('Insufficient permission: edit_controllers')}), 403
    if not scope.can_operate_device(camera_id):
        return jsonify({'status': 'error', 'message': scope.deny_message()}), 403
    if _camera_or_404(camera_id) is None:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404
    from aot.camera_drivers import capabilities as C
    from aot.aot_flask.extensions import db
    row = CameraDriver.query.filter_by(camera_id=camera_id).first()
    if row is None:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404
    body = request.get_json(silent=True) or {}
    if 'enabled' in body:
        row.events_enabled = bool(body['enabled'])
    if 'kinds' in body:
        kinds = body['kinds']
        if not isinstance(kinds, list) or any(not isinstance(k, str) for k in kinds):
            return jsonify({'status': 'error', 'message': 'kinds must be a list'}), 400
        supported = set(C.Capabilities.from_json(row.capabilities).event_kinds())
        bad = [k for k in kinds if k not in supported]
        if bad:
            return jsonify({'status': 'error', 'message': gettext('Unsupported event kind')}), 400
        row.event_kinds = kinds or None
    db.session.commit()
    from aot.aot_client import DaemonControl
    result = DaemonControl().camera_driver_call('events_refresh', camera_id)
    row = CameraDriver.query.filter_by(camera_id=camera_id).first()
    return jsonify({'status': 'success', 'result': result, 'driver': _status_of(camera_id, row)})


@blueprint.route('/camera/driver/<camera_id>/event_switches', methods=['POST'])
@login_required
def driver_event_switches(camera_id):
    """카메라 쪽 감지별 알림(msg_push) 상태를 읽는다. 읽기 전용이지만 카메라에 닿으므로 같은 게이트."""
    if not utils_general.user_has_permission('edit_controllers', silent=True):
        return jsonify({'status': 'error',
                        'message': gettext('Insufficient permission: edit_controllers')}), 403
    if not scope.can_operate_device(camera_id):
        return jsonify({'status': 'error', 'message': scope.deny_message()}), 403
    if _camera_or_404(camera_id) is None:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404
    from aot.aot_client import DaemonControl
    result = DaemonControl().camera_driver_call('event_switches', camera_id)
    return jsonify({'status': 'success' if result.get('ok') else 'error', 'result': result})


# -- 네트워크 검색 (P5, 설계 §8) ---------------------------------------------------------
# 사용자가 "카메라 찾기"를 눌렀을 때만. 카메라 자체에는 닿지 않고(포트 탐침 + 무인증 식별) 비밀도 보내지 않는다.
def _scan_error_message(code, retry_after=None):
    msgs = {
        'invalid': gettext('Enter a subnet such as 192.168.0.0/24.'),
        'not_private': gettext('Only private network addresses (10.x, 172.16-31.x, 192.168.x) can be searched.'),
        'too_wide': gettext('The range is too wide. Enter a range of /24 or narrower.'),
        'busy': gettext('A search is already running.'),
        'cooldown': gettext('This subnet was searched just now. Try again in %(n)s seconds.', n=retry_after or 60),
    }
    return msgs.get(code, gettext('The search could not be started.'))


def _scan_gate():
    if not utils_general.user_has_permission('edit_controllers', silent=True):
        return jsonify({'status': 'error',
                        'message': gettext('Insufficient permission: edit_controllers')}), 403
    return None


@blueprint.route('/camera/scan/defaults')
@login_required
def scan_defaults():
    denied = _scan_gate()
    if denied:
        return denied
    from aot.camera_drivers.discovery import default_subnet
    from aot.utils import system_environment as se
    docker = se.detect().get('platform_type') == se.PLATFORM_DOCKER
    return jsonify({'status': 'success', 'docker': docker,
                    'subnet': None if docker else default_subnet(is_docker=False)})


@blueprint.route('/camera/scan/start', methods=['POST'])
@login_required
def scan_start():
    denied = _scan_gate()
    if denied:
        return denied
    from aot.camera_drivers.discovery import ScanError, parse_subnet
    subnet = (request.get_json(silent=True) or {}).get('subnet', '')
    try:      # 데몬에 보내기 전에 한 번 더 거른다(같은 규칙)
        parse_subnet(subnet)
    except ScanError as e:
        return jsonify({'status': 'error', 'code': e.code, 'message': _scan_error_message(e.code)}), 400
    from aot.aot_client import DaemonControl
    r = DaemonControl().camera_scan_start(subnet)
    if not r.get('ok'):
        code = r.get('code', 'failed')
        status = 429 if code in ('busy', 'cooldown') else 503
        return jsonify({'status': 'error', 'code': code,
                        'message': _scan_error_message(code, r.get('retry_after'))}), status
    return jsonify({'status': 'success', 'scan_id': r['scan_id']})


@blueprint.route('/camera/scan/<scan_id>')
@login_required
def scan_result(scan_id):
    denied = _scan_gate()
    if denied:
        return denied
    from aot.aot_client import DaemonControl
    r = DaemonControl().camera_scan_result(scan_id)
    if not r.get('ok'):
        return jsonify({'status': 'error', 'message': gettext('The search could not be started.')}), 404
    scan = r['scan']
    # 제안은 조작할 수 있는 카메라 것만 낸다
    scan['suggestions'] = [s for s in scan.get('suggestions', [])
                           if scope.can_operate_device(s['camera_id'])]
    return jsonify({'status': 'success', 'scan': scan})


@blueprint.route('/camera/driver/<camera_id>/apply_host', methods=['POST'])
@login_required
def driver_apply_host(camera_id):
    """IP 바뀜 제안을 사용자가 확인한 뒤 주소를 바꾼다(Q8). 카메라에는 닿지 않는다.
    주소만 바뀐 것으로 다룬다: 인증 상태·검증 기록·인증서 고정을 지우고, 비밀번호는 '연결 확인'을 눌러야 간다."""
    if not utils_general.user_has_permission('edit_controllers', silent=True):
        return jsonify({'status': 'error',
                        'message': gettext('Insufficient permission: edit_controllers')}), 403
    if not scope.can_operate_device(camera_id):
        return jsonify({'status': 'error', 'message': scope.deny_message()}), 403
    if _camera_or_404(camera_id) is None:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404
    body = request.get_json(silent=True) or {}
    new_host = (body.get('host') or '').strip()
    from aot.aot_client import DaemonControl
    r = DaemonControl().camera_scan_result(body.get('scan_id', ''))
    sug = (r.get('scan') or {}).get('suggestions', []) if r.get('ok') else []
    if not any(s['camera_id'] == camera_id and s['new_host'] == new_host for s in sug):
        return jsonify({'status': 'error',
                        'message': gettext('This address is no longer suggested. Search again.')}), 409
    from aot.aot_flask.extensions import db
    row = CameraDriver.query.filter_by(camera_id=camera_id).first()
    if row is None:
        return jsonify({'status': 'error', 'message': 'Camera not found'}), 404
    row.host = new_host
    row.auth_state = 'unverified'
    row.attempt_lease_until = None
    row.auth_iface = row.auth_code = row.auth_at = None
    row.verified_fp = None
    row.tls_pin_sha256 = None
    db.session.commit()
    return jsonify({'status': 'success', 'driver': _status_of(camera_id, row)})
