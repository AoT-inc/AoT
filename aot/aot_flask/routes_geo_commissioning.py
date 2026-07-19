# coding=utf-8
"""
Commissioning Diagnostic route sub-module for routes_geo.

This file is imported at the bottom of routes_geo.py so that the route
functions are registered on the shared blueprint object without circular
imports.  All route paths and function signatures are unchanged.
"""
import logging

from flask import request, jsonify, current_app
from flask_babel import gettext as _
from flask_login import login_required

from aot.aot_flask.utils import utils_general
from aot.aot_flask.extensions import db
from aot.aot_flask.routes_geo import blueprint  # noqa: E402

logger = logging.getLogger(__name__)


# ── 장치 점검 (Commissioning Diagnostic) ──────────────────────────────────────

@blueprint.route('/api/geo/facility/<facility_uuid>/commissioning/start', methods=['POST'])
@login_required
def api_commissioning_start(facility_uuid):
    """사용자 트리거 장치 점검 시작.

    Request body:
        {"actuator_ids": ["uuid1", "uuid2"]}   // 생략 시 시설 전체 액추에이터

    Response:
        {"ok": true, "check_id": "..."}
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission denied'}), 403

    from aot.databases.models import GeoFacility, Output
    from aot.functions.utils.env_control.commissioning import start_check

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    body = request.get_json(silent=True) or {}
    requested_ids = body.get('actuator_ids') or []

    # 시설 액추에이터 목록 구성
    actuators_raw = facility.actuators or {}
    all_acts = []
    if isinstance(actuators_raw, list):
        for act in actuators_raw:
            uid  = act.get('device_uuid') or ''
            kind = act.get('kind') or ''
            name = act.get('name') or kind
            if uid:
                all_acts.append({'actuator_id': uid, 'kind': kind, 'name': name})
    else:
        for slot_key, uid in actuators_raw.items():
            if uid:
                all_acts.append({'actuator_id': uid, 'kind': slot_key, 'name': slot_key})

    # 이름 보강: Output 테이블에서 실제 장치명 조회
    uuids = [a['actuator_id'] for a in all_acts]
    if uuids:
        try:
            rows = Output.query.filter(Output.unique_id.in_(uuids)).all()
            name_map = {r.unique_id: r.name for r in rows}
            for a in all_acts:
                a['name'] = name_map.get(a['actuator_id'], a['name']) or a['name']
        except Exception:
            pass

    # 선택 필터
    if requested_ids:
        all_acts = [a for a in all_acts if a['actuator_id'] in requested_ids]

    if not all_acts:
        return jsonify({'ok': False, 'message': _('No devices to inspect')}), 400

    check_id = start_check(facility_uuid, all_acts)
    return jsonify({'ok': True, 'check_id': check_id, 'actuator_count': len(all_acts)})


@blueprint.route('/api/geo/facility/<facility_uuid>/commissioning/<check_id>', methods=['GET'])
@login_required
def api_commissioning_result(facility_uuid, check_id):
    """점검 결과 조회."""
    from aot.functions.utils.env_control.commissioning import get_result

    data = get_result(check_id)
    if not data:
        return jsonify({'ok': False, 'message': 'check_id not found'}), 404
    if data.get('facility_uuid') != facility_uuid:
        return jsonify({'ok': False, 'message': 'facility mismatch'}), 403
    return jsonify({'ok': True, **data})


@blueprint.route('/api/geo/facility/<facility_uuid>/commissioning/<check_id>/verdict', methods=['POST'])
@login_required
def api_commissioning_verdict(facility_uuid, check_id):
    """인간 판정 제출 + 설정 반영.

    Request body:
        {
            "actuator_id": "uuid",
            "verdict": "ok" | "sensor" | "device" | "external" | "skip",
            "note": "..."
        }

    Response:
        {"ok": true, "actions": [...]}
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission denied'}), 403

    from aot.functions.utils.env_control.commissioning import submit_verdict, get_result

    data = get_result(check_id)
    if not data or data.get('facility_uuid') != facility_uuid:
        return jsonify({'ok': False, 'message': 'check not found'}), 404

    body = request.get_json(silent=True) or {}
    actuator_id = body.get('actuator_id', '')
    verdict     = body.get('verdict', '')
    note        = body.get('note', '')

    ok, msg, actions = submit_verdict(check_id, actuator_id, verdict, note)
    if not ok:
        return jsonify({'ok': False, 'message': msg}), 400

    # 판정 즉시 실효 가능한 인메모리 설정 적용
    _apply_commissioning_actions(facility_uuid, actions)

    return jsonify({'ok': True, 'actions': actions, 'message': msg})


def _apply_commissioning_actions(facility_uuid: str, actions: list):
    """Write verdict actions into facility.commissioning_state."""
    import time as _time
    from aot.databases.models import GeoFacility
    from sqlalchemy.orm.attributes import flag_modified

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return

    state = dict(facility.commissioning_state or {})

    for action in actions:
        atype = action.get('type')

        if atype == 'sensor_trust_zero':
            flags = dict(state.get('commissioning_flags', {}))
            flags[action['actuator_id']] = 'sensor_suspect'
            state['commissioning_flags'] = flags

        elif atype == 'k_upper_bound_adjust':
            k_bounds = dict(state.get('k_upper_bounds', {}))
            k_bounds[action['actuator_id']] = {
                'var':   action.get('var'),
                'ratio': action.get('ratio'),
            }
            state['k_upper_bounds'] = k_bounds

        elif atype == 'calibration_anchor':
            anchors = list(state.get('calibration_anchors', []))
            anchors.append({
                'actuator_id': action['actuator_id'],
                'var':         action.get('var'),
                'k_measured':  action.get('k_measured'),
                'ts':          _time.time(),
                'consumed':    False,   # cycle_mixin이 읽고 True 로 표시
            })
            state['calibration_anchors'] = anchors[-50:]
            state['pending_anchors'] = True

        elif atype == 'alarm':
            alarms = list(state.get('device_alarms', []))
            alarms.append({
                'actuator_id': action['actuator_id'],
                'message':     action['description'],
                'ts':          _time.time(),
            })
            state['device_alarms'] = alarms[-20:]

    facility.commissioning_state = state
    flag_modified(facility, 'commissioning_state')

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
