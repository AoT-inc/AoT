# coding=utf-8
"""
IEC Widget API route sub-module for routes_geo.

This file is imported at the bottom of routes_geo.py so that the route
functions are registered on the shared blueprint object without circular
imports.  All route paths and function signatures are unchanged.
"""
import logging

from flask import request, jsonify, current_app
from flask_login import login_required, current_user

from aot.aot_flask.access import scope
from aot.aot_flask.utils import utils_general
from aot.aot_flask.extensions import db
from aot.aot_flask.routes_geo import blueprint  # noqa: E402

logger = logging.getLogger(__name__)


# IEC function stale 판정 최소 임계값 (초) — status / env_summary 공용.
IEC_STALE_SEC = 300


def _iec_stale_threshold(fn):
    """function 의 사이클 주기(update_period)에 비례한 stale 임계값.

    데몬 watchdog 과 동일하게 주기의 3배를 기준으로 하되 최소 300초.
    (주기가 600초인 function 을 고정 300초로 판정하면 정상 동작 중에도
    사이클 사이 구간에서 항상 '응답 없음'으로 표시되는 거짓 경보가 난다.)
    """
    import json as _json
    try:
        opts = _json.loads(fn.custom_options or '{}') or {}
        period = float(opts.get('update_period') or 0.0)
    except (TypeError, ValueError):
        period = 0.0
    return max(IEC_STALE_SEC, period * 3.0)

# ── IEC Widget APIs ────────────────────────────────────────────────────────────


@blueprint.route('/api/aot/facility/<facility_uuid>/status', methods=['GET'])
@login_required
def api_facility_iec_status(facility_uuid):
    """IEC § 0 — lightweight status badge for 5-second polling.

    Query params:
      function_uuid — UUID of the linked env_coordinator CustomController
                      (optional; falls back to first activated env_coordinator)

    Returns level (emergency|warn|active|idle), reasons list,
    active_count, total_count, function_active, function_stale.
    """
    import time as _time
    try:
        from aot.databases.models import GeoFacility
        from aot.databases.models.geo_facility_setpoint import GeoFacilitySetpoint
        from aot.databases.models.controller import CustomController
        from aot.databases.models.function import FunctionRuntimeState
        from aot.aot_client import DaemonControl
        from aot.aot_flask.geo.facility_sensors import compute_spatial_internal as _csi
    except ImportError as exc:
        return jsonify({'ok': False, 'message': 'Import error: {}'.format(exc)}), 500

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    reasons = []
    level = 'idle'
    function_active = False
    function_stale = False
    function_name = None

    # ── IEC function state ────────────────────────────────────────────────────
    # facility 에 실제로 연결된 코디네이터만 본다 (env_summary 와 동일 기준 —
    # 시스템 전체에서 아무거나 골라 남의 코디네이터 상태를 표시하지 않는다).
    function_uuid = request.args.get('function_uuid', '').strip()
    if function_uuid:
        candidate = CustomController.query.filter_by(
            unique_id=function_uuid, device='env_coordinator').first()
        if candidate is None:
            return jsonify({'ok': False, 'message': 'function_uuid not found'}), 404
        if not _function_belongs_to_facility(candidate, facility_uuid):
            return jsonify({
                'ok': False,
                'message': 'function_uuid does not belong to this facility',
            }), 400

    try:
        fn = (CustomController.query.filter_by(
                  unique_id=function_uuid, device='env_coordinator').first()
              if function_uuid else _find_facility_env_coordinator(facility_uuid))

        if fn:
            function_name = fn.name
            function_active = bool(fn.is_activated)
            if not function_active:
                reasons.append('IEC function not activated ({})'.format(fn.name))
                level = 'warn'
            else:
                # Check last cycle timestamp
                rs = FunctionRuntimeState.query.filter_by(
                    function_id=fn.unique_id).first()
                if rs and rs.last_cycle_ts:
                    age = _time.time() - rs.last_cycle_ts
                    if age > _iec_stale_threshold(fn):
                        function_stale = True
                        reasons.append('IEC stale ({:.0f}s ago)'.format(age))
                        if level == 'idle':
                            level = 'warn'
                    else:
                        level = 'active'
                else:
                    function_stale = True
                    reasons.append('IEC not yet run')
                    if level == 'idle':
                        level = 'warn'
        else:
            # 이 시설에 연결된 코디네이터가 없다 — 문제 상황이 아니라 "자동
            # 제어 없음" 상태이므로 level 은 건드리지 않는다(경고로 승격 금지).
            reasons.append('No IEC function linked to this facility')
    except Exception as exc:
        logger.warning('[facility/status] function state error: %s', exc)

    # ── Sensor health (fittings 신경로) ──────────────────────────────────────
    indoor = {}
    try:
        from aot.aot_flask.geo.facility_integration import get_facility_integration as _gfi_h
        integ_h, _ = _gfi_h(facility_uuid)
        sensors_resolved = (integ_h.get('sensors_resolved') or []) if integ_h else []
        sr = _csi(sensors_resolved)
        valid_count  = sr.get('valid_count', 0)
        total_sensors = len(sensors_resolved)
        if total_sensors > 0 and valid_count < total_sensors * 0.5:
            reasons.append('sensor degraded ({}/{})'.format(valid_count, total_sensors))
            level = 'emergency'
        elif total_sensors > 0 and valid_count < total_sensors:
            reasons.append('sensor stale ({}/{})'.format(valid_count, total_sensors))
            if level == 'idle':
                level = 'warn'
        # remap spatial keys to downstream-compatible names
        indoor = {
            'vpd_kpa': sr.get('VPD'),
            'temp_c':  sr.get('T'),
            'co2_ppm': sr.get('CO2'),
        }
    except Exception as exc:
        logger.warning('[facility/status] sensor read error: %s', exc)

    # ── Setpoint deviation ────────────────────────────────────────────────────
    try:
        sp = GeoFacilitySetpoint.query.filter_by(facility_uuid=facility_uuid).first()
        # 편차는 **제어가 따르는 목표**와 견준다. 저장된 열과 견주면 화면은
        # "목표대로" 라는데 제어는 다른 값을 좇는 상태가 보이지 않는다.
        eff = _effective_targets(facility_uuid)

        if eff.get('vpd') is not None and indoor.get('vpd_kpa') is not None:
            tol = 0.15
            deviation = abs(indoor['vpd_kpa'] - eff['vpd'])
            if deviation > tol * 3:
                reasons.append('VPD dev {:.2f} kPa'.format(deviation))
                if level != 'emergency':
                    level = 'emergency'
            elif deviation > tol:
                reasons.append('VPD off target ({:.2f} kPa)'.format(deviation))
                if level == 'idle':
                    level = 'warn'

        if sp and indoor.get('temp_c') is not None:
            t = indoor['temp_c']
            if sp.temp_min_c is not None and t < sp.temp_min_c:
                reasons.append('temp below safety min ({:.1f}°C)'.format(t))
                if level != 'emergency':
                    level = 'emergency'
            elif sp.temp_max_c is not None and t > sp.temp_max_c:
                reasons.append('temp above safety max ({:.1f}°C)'.format(t))
                if level != 'emergency':
                    level = 'emergency'

        if eff.get('co2') is not None and indoor.get('co2_ppm') is not None:
            if indoor['co2_ppm'] > eff['co2'] * 1.1:
                reasons.append('CO2 {}>{} ppm'.format(int(indoor['co2_ppm']), int(eff['co2'])))
                if level == 'idle':
                    level = 'warn'
    except Exception as exc:
        logger.warning('[facility/status] setpoint check error: %s', exc)

    # ── Active actuator count (via get_facility_integration) ─────────────────
    total_count = 0
    active_count = 0
    try:
        from aot.aot_flask.geo.facility_integration import get_facility_integration as _gfi
        all_states_s = DaemonControl().output_states_all() or {}
        integ_s, _ = _gfi(facility_uuid)
        acts_resolved = (integ_s.get('actuators_resolved') or []) if integ_s else []
        total_count = len(acts_resolved)
        for act in acts_resolved:
            uid = act.get('output_uuid', '')
            if uid:
                ch = all_states_s.get(uid, {})
                val = ch.get(0) if isinstance(ch, dict) else None
                if val not in (None, 'off', False, 0):
                    active_count += 1
        if active_count > 0 and level == 'idle':
            level = 'active'
    except Exception:
        pass

    return jsonify({
        'ok':             True,
        'level':          level,
        'reasons':        reasons,
        'active_count':   active_count,
        'total_count':    total_count,
        'function_active': function_active,
        'function_stale':  function_stale,
        'function_name':   function_name,
        'ts':             _time.time(),
    })


def _effective_targets(facility_uuid):
    """이 시설의 제어가 **지금 따르는** 목표 → `{'vpd':…, 'co2':…, 'source':…}`.

    화면이 현재값을 색칠할 기준이다. 저장된 열이 아니라 제어와 **같은 계산**을
    거쳐야 한다 — 다른 경로로 구하면 화면은 맞는데 제어는 다르게 도는 상태가
    생기고, 그건 화면만 보고는 알 수 없다.
    """
    try:
        from aot.aot_flask.geo import coordinator_plot
        fn = _find_facility_env_coordinator(facility_uuid)
        if fn is None:
            return {'vpd': None, 'co2': None, 'source': 'no-coordinator'}
        t = coordinator_plot.control_targets(fn)
        return {'vpd': (t.get('vpd') or {}).get('value'),
                'co2': (t.get('co2') or {}).get('value'),
                'vpd_method': bool((t.get('vpd') or {}).get('method_id')),
                'co2_method': bool((t.get('co2') or {}).get('method_id')),
                'plot_name': t.get('plot_name'),
                'source': t.get('reason')}
    except Exception:                                       # noqa: BLE001
        return {'vpd': None, 'co2': None, 'source': 'error'}


@blueprint.route('/api/aot/facility/<facility_uuid>/setpoints', methods=['GET', 'POST'])
@login_required
def api_facility_setpoints(facility_uuid):
    """IEC § C — read or write facility setpoints.

    **여기서 정하는 것은 안전 범위뿐이다.** VPD·CO₂ 목표는 구획의 프로그램이
    정본이고 제어가 매 사이클 그것을 읽는다 — 예전에는 같은 목표를 프로그램 ·
    함수 옵션 · 이 API 세 곳에서 설정할 수 있었다. 목표를 여기로 보내면
    거부하고 어디서 정하는지 말한다(조용히 무시하면 화면에는 저장된 것처럼
    보이는데 제어는 그 값을 쓰지 않는다).

    코디네이터 옵션으로 그대로 옮겨지는 열:
      guide_t_min/max  → guide_T_min/max (VPD 분해의 온도 안내 범위)
      guide_rh_min/max → guide_RH_min/max (습도 안내 범위)
      temp_min/max_c   → temp_min/max    (하드 안전 한계)
      humid_min/max_pct→ humid_min/max   (하드 안전 한계)

    GET 응답의 `effective` 는 **지금 제어가 따르는 목표**다(프로그램에서 온다).
    """
    from aot.databases.models import GeoFacility
    from aot.databases.models.geo_facility_setpoint import GeoFacilitySetpoint
    from aot.databases import set_uuid

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    if request.method == 'GET':
        sp = GeoFacilitySetpoint.query.filter_by(facility_uuid=facility_uuid).first()
        out = sp.to_dict() if sp else {}
        # 화면은 이 dict 하나만 본다 — 목표를 형제 키로 두면 호출부마다 합치는
        # 코드가 생기고, 한 곳만 빠뜨리면 그 화면에서 목표가 사라진다.
        out['effective'] = _effective_targets(facility_uuid)
        return jsonify({'ok': True, 'setpoints': out})

    # POST — write
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Insufficient permission'}), 403

    body = request.get_json(silent=True) or {}

    errors = []

    def _float(key):
        v = body.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            errors.append('{} invalid'.format(key))
            return None

    def _in_range(val, lo, hi, name):
        if val is not None and not (lo <= val <= hi):
            errors.append('{} must be {}-{}'.format(name, lo, hi))

    # 목표는 여기서 받지 않는다 — 조용히 무시하면 저장된 것처럼 보이는데 제어는
    # 그 값을 쓰지 않는다(이 저장소가 반복해서 겪은 "성공이라 답하는데 안 돈 것").
    for gone in ('target_vpd_kpa', 'target_co2_ppm'):
        if body.get(gone) is not None:
            errors.append(
                '{}: 목표는 구획의 프로그램에서 정합니다 (단계 목표)'.format(gone))

    g_t_min   = _float('guide_t_min_c')
    g_t_max   = _float('guide_t_max_c')
    g_rh_min  = _float('guide_rh_min_pct')
    g_rh_max  = _float('guide_rh_max_pct')
    t_min     = _float('temp_min_c')
    t_max     = _float('temp_max_c')
    h_min     = _float('humid_min_pct')
    h_max     = _float('humid_max_pct')

    _in_range(g_t_min,  0,   40,   'guide_t_min_c')
    _in_range(g_t_max,  0,   45,   'guide_t_max_c')
    _in_range(g_rh_min, 10,  95,   'guide_rh_min_pct')
    _in_range(g_rh_max, 10,  99,   'guide_rh_max_pct')
    _in_range(t_min,   -10,  40,   'temp_min_c')
    _in_range(t_max,    0,   50,   'temp_max_c')
    _in_range(h_min,    10,  95,   'humid_min_pct')
    _in_range(h_max,    10,  99,   'humid_max_pct')

    if g_t_min is not None and g_t_max is not None and g_t_min >= g_t_max:
        errors.append('guide_t_min_c must be < guide_t_max_c')
    if g_rh_min is not None and g_rh_max is not None and g_rh_min >= g_rh_max:
        errors.append('guide_rh_min_pct must be < guide_rh_max_pct')
    if t_min is not None and t_max is not None and t_min >= t_max:
        errors.append('temp_min_c must be < temp_max_c')
    if h_min is not None and h_max is not None and h_min >= h_max:
        errors.append('humid_min_pct must be < humid_max_pct')

    if errors:
        return jsonify({'ok': False, 'errors': errors}), 400

    sp = GeoFacilitySetpoint.query.filter_by(facility_uuid=facility_uuid).first()
    if not sp:
        sp = GeoFacilitySetpoint()
        sp.unique_id     = set_uuid()
        sp.facility_uuid = facility_uuid
        db.session.add(sp)

    if g_t_min  is not None: sp.guide_t_min_c    = g_t_min
    if g_t_max  is not None: sp.guide_t_max_c    = g_t_max
    if g_rh_min is not None: sp.guide_rh_min_pct = g_rh_min
    if g_rh_max is not None: sp.guide_rh_max_pct = g_rh_max
    if t_min    is not None: sp.temp_min_c        = t_min
    if t_max    is not None: sp.temp_max_c        = t_max
    if h_min    is not None: sp.humid_min_pct     = h_min
    if h_max    is not None: sp.humid_max_pct     = h_max

    sp.source   = 'manual'
    sp.operator = current_user.name if current_user.is_authenticated else None
    from datetime import datetime
    sp.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'message': str(e)}), 500

    # ── 코디네이터 옵션으로 옮기고 reload ────────────────────────────────
    # 안 옮기면 GeoFacilitySetpoint 행만 바뀌고 코디네이터는 재시작 전까지 옛
    # guide/한계 값을 그대로 쓴다. **목표는 여기 없다** — 프로그램이 정본이다.
    mirror_result = {'mirrored': False, 'reload_sent': False, 'detail': None}
    try:
        from aot.databases.models import CustomController
        import json as _json
        funcs = CustomController.query.filter_by(device='env_coordinator').all()
        # 링크 판정은 헬퍼 하나로 — 여기서 다시 쓰면 저장 키가 갈릴 때
        # (`geo_facility_id` vs `..._device_id`) 이 경로만 조용히 안 맞는다.
        matched = [f for f in funcs
                   if _function_belongs_to_facility(f, facility_uuid)]
        # 목표(target_vpd/target_co2)는 옮기지 않는다 — 그 옵션은 더 이상
        # 없고, 제어는 프로그램을 읽는다.
        _COL_TO_OPT = {
            'guide_t_min_c':    'guide_T_min',
            'guide_t_max_c':    'guide_T_max',
            'guide_rh_min_pct': 'guide_RH_min',
            'guide_rh_max_pct': 'guide_RH_max',
            'temp_min_c':       'temp_min',
            'temp_max_c':       'temp_max',
            'humid_min_pct':    'humid_min',
            'humid_max_pct':    'humid_max',
        }
        new_vals = {
            'guide_t_min_c':    g_t_min,
            'guide_t_max_c':    g_t_max,
            'guide_rh_min_pct': g_rh_min,
            'guide_rh_max_pct': g_rh_max,
            'temp_min_c':       t_min,
            'temp_max_c':       t_max,
            'humid_min_pct':    h_min,
            'humid_max_pct':    h_max,
        }
        for func in matched:
            opts = _json.loads(func.custom_options or '{}') or {}
            changed = False
            for col, val in new_vals.items():
                if val is None:
                    continue
                opt_key = _COL_TO_OPT[col]
                if opts.get(opt_key) != val:
                    opts[opt_key] = val
                    changed = True
            if changed:
                func.custom_options = _json.dumps(opts)
                db.session.commit()
                mirror_result['mirrored'] = True
                # Trigger live reload of the running daemon function
                try:
                    from aot.aot_client import DaemonControl
                    DaemonControl().module_function(
                        'Function', func.unique_id, 'cmd_reload', {},
                        thread=True)
                    mirror_result['reload_sent'] = True
                except Exception as rexc:
                    mirror_result['detail'] = 'reload_failed: {}'.format(rexc)
    except Exception as exc:
        db.session.rollback()
        mirror_result['detail'] = 'mirror_failed: {}'.format(exc)

    saved = sp.to_dict()
    saved['effective'] = _effective_targets(facility_uuid)
    return jsonify({
        'ok': True,
        'setpoints': saved,
        'mirror': mirror_result,
    })


@blueprint.route('/api/aot/facility/<facility_uuid>/control', methods=['POST'])
@login_required
def api_facility_control(facility_uuid):
    """IEC § D — direct single-actuator manual control.

    Body: {slot_key, action: 'on'|'off'|'set', percent?, reason?}

    Safety policy:
      - Slot resolution uses get_facility_integration() (same source as env_coordinator
        and the runtime endpoint — no legacy facility.actuators list/dict parsing).
      - Sensor data comes from integration sensors_outdoor via read_outdoor_sensors
        (facility fittings sensor_role='outdoor') — no legacy facility.sensors column.
      - Before dispatch, SafetyPreGate is evaluated with current sensor state.
        If a gate is active AND the requested command conflicts with the forced-safe
        value for that actuator kind, the request is rejected with gate reason + warn.
        Manual commands that do NOT conflict (e.g. turning ON a heater while wind gate
        is active) are allowed and logged as 'manual_override'.
    """
    import time as _time
    import json as _json
    from aot.databases.models import GeoFacility
    from aot.aot_client import DaemonControl, daemon_call_failed
    from aot.aot_flask.geo.facility_integration import get_facility_integration
    from aot.aot_flask.geo.facility_sensors import read_outdoor_sensors, compute_spatial_internal
    from aot.functions.utils.env_control.safety_gates import (
        SafetyPreGate, PreGateConfig,
    )

    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Insufficient permission'}), 403

    # 그룹 스코프(A1a) — 시설 단위. docs/design/access-scope-groups.md
    if not scope.can_operate('geo_facility', facility_uuid):
        return jsonify({'ok': False, 'message': scope.deny_message()}), 403

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    body     = request.get_json(silent=True) or {}
    slot_key = body.get('slot_key', '')
    action   = body.get('action', '')
    percent  = body.get('percent')
    reason   = body.get('reason', 'manual')

    if action not in ('on', 'off', 'set'):
        return jsonify({'ok': False, 'message': 'action must be on|off|set'}), 400

    # ── #5: Slot resolution via integration (single authoritative source) ──────
    integ, integ_err = get_facility_integration(facility_uuid)
    if integ_err or not integ:
        return jsonify({'ok': False, 'message': 'Integration load failed: ' + (integ_err or 'unknown')}), 500

    actuators_resolved = integ.get('actuators_resolved') or []
    slot_map = integ.get('actuators_slot_map') or {}

    # Resolve slot_key →  output_uuid:
    #   1) facility.actuators slot_map (예: 'curtain_1' → uuid)
    #   2) actuators_resolved 의 slot_key 매칭 (slot 등록형)
    #   3) actuators_resolved 의 output_uuid 매칭 (fitting-only 액추에이터는
    #      runtime endpoint 가 slot_key=output_uuid 로 키잉하므로 필요)
    output_uuid = slot_map.get(slot_key) or ''
    kind = ''
    module_name = ''   # Output 모듈 종류(output_name_unique) — output_type 변환에 사용
    if not output_uuid:
        for ar in actuators_resolved:
            if ar.get('slot_key') == slot_key:
                output_uuid = ar.get('output_uuid', '')
                break
    if not output_uuid:
        for ar in actuators_resolved:
            if ar.get('output_uuid') == slot_key:
                output_uuid = slot_key
                break
    for ar in actuators_resolved:
        if ar.get('output_uuid') == output_uuid:
            kind = ar.get('kind', '')
            module_name = ar.get('output_type', '')
            break

    if not output_uuid:
        return jsonify({'ok': False, 'message': 'slot_key not found: ' + slot_key}), 404

    # ── #9: Sensor state via integration sensors (not legacy facility.sensors) ──
    outdoor = {}
    try:
        sensors_outdoor = integ.get('sensors_outdoor') or []
        if sensors_outdoor:
            od = read_outdoor_sensors(sensors_outdoor)
            outdoor = {
                'T':       od.get('T_ext'),
                'wind':    od.get('wind_ms'),
                'wind_dir': od.get('wind_deg'),
                'rain':    od.get('rain'),
            }
    except Exception:
        pass

    internal = {}
    try:
        sensors_resolved = integ.get('sensors_resolved') or []
        if sensors_resolved:
            sp = compute_spatial_internal(sensors_resolved)
            internal = {
                'T':    sp.get('T'),
                'T_max': sp.get('T_max'),
                'T_min': sp.get('T_min'),
                'RH':   sp.get('RH'),
            }
    except Exception:
        pass

    # ── #4: SafetyPreGate evaluation ──────────────────────────────────────────
    # Load wind_threshold from linked env_coordinator (best-effort; default 12 m/s).
    wind_threshold = 12.0
    try:
        from aot.databases.models import CustomController
        funcs = CustomController.query.filter_by(device='env_coordinator').all()
        for f in funcs:
            if _function_belongs_to_facility(f, facility_uuid):
                opts = _json.loads(f.custom_options or '{}') or {}
                wind_threshold = float(opts.get('gate_wind_threshold') or 12.0)
                break
    except Exception:
        pass

    gate_cfg = PreGateConfig(wind_threshold=wind_threshold)
    pre_gate = SafetyPreGate(gate_cfg)

    now_ts = _time.time()
    gate_env = {
        'internal': {
            'T':     internal.get('T',     25.0) or 25.0,
            'T_max': internal.get('T_max', internal.get('T', 25.0) or 25.0),
            'T_min': internal.get('T_min', internal.get('T', 25.0) or 25.0),
            'RH':    internal.get('RH',    60.0) or 60.0,
        },
        'external': {
            'T':       outdoor.get('T')       or 20.0,
            'wind':    outdoor.get('wind')    or 0.0,
            'wind_dir': outdoor.get('wind_dir'),
            'rain':    outdoor.get('rain')    or 0.0,
        },
        'now_ts':      now_ts,
        'last_ext_ts': now_ts,   # manual call — treat ext as fresh
        'last_int_ts': now_ts,
    }

    # Build minimal ActuatorProfile list (only target actuator) for gate evaluation
    from aot.functions.utils.env_control.types import ActuatorProfile, ManualLockState, CmdConstraints
    from aot.functions.utils.env_control.effect_functions import build_effect_model
    target_profile = ActuatorProfile(
        actuator_id=output_uuid,
        kind=kind or 'unknown',
        capabilities=[],
        cost_fn=lambda env, pct: 0.0,
        response_sec=60.0,
        safe_default=0.0,
        manual_lock=ManualLockState(),
        effect_model=build_effect_model(kind or 'unknown', {}),
        cmd_constraints=CmdConstraints(),
    )

    gate_result = pre_gate.evaluate(gate_env, [target_profile], unique_id='')
    gate_warn = None

    if gate_result.triggered or gate_result.partial:
        forced = gate_result.forced_commands.get(output_uuid)
        if forced is not None:
            forced_val = forced.get('value', 0.0)
            # Determine requested value
            req_val = 0.0 if action == 'off' else (100.0 if action == 'on' else float(percent or 0.0))
            # Conflict: gate forces 0 but user requests > 0, or gate forces 100 but user requests < 50
            conflict = (
                (forced_val == 0.0 and req_val > 0.0) or
                (forced_val >= 100.0 and req_val < 50.0)
            )
            if conflict:
                return jsonify({
                    'ok':      False,
                    'blocked': True,
                    'gate':    gate_result.description,
                    'message': (
                        '안전 게이트 활성 ({gate}) — {kind} 을 {req:.0f}%로 설정할 수 없습니다. '
                        '게이트 해제 후 다시 시도하거나, 강제 적용 엔드포인트를 사용하세요.'
                    ).format(
                        gate=gate_result.description,
                        kind=kind or slot_key,
                        req=req_val,
                    ),
                }), 400
            # Non-conflicting manual command during gate: allow, attach warning
            gate_warn = '게이트 활성 중 ({}) — 명령이 게이트 강제값과 충돌하지 않아 수동 적용'.format(
                gate_result.description)

    # ── Execute ────────────────────────────────────────────────────────────────
    # 'set' (percent) 명령은 장치가 실제로 지원하는 output_type 으로 변환해 전달한다.
    # base_output.output_on_off 는 output_type 이 장치 지원 타입과 일치할 때만
    # 명령을 실행하므로, 모든 장치에 output_type='value' 를 보내던 과거 코드는
    # PWM·on/off 릴레이에서 % 명령이 무시되거나 단순 on/off 로만 처리되는 버그가 있었다.
    # env_coordinator 와 동일하게 장치 종류별로 value / pwm / sec(시간비례) 로 매핑한다.
    daemon = DaemonControl()
    ret = None
    try:
        if action == 'off':
            ret = daemon.output_off(output_uuid, output_channel=0)
        elif action == 'on':
            ret = daemon.output_on(output_uuid, output_channel=0, amount=0)
        elif action == 'set' and percent is not None:
            pct = float(percent)
            from aot.utils.outputs import parse_output_information
            try:
                _out_info = parse_output_information()
            except Exception:
                _out_info = {}
            types_list = (_out_info.get(module_name, {}) or {}).get('output_types') or []

            if 'value' in types_list:
                # actuator_paired / DAC 등 위치형 — % 그대로. source=manual 로 사용자 목표 추적.
                ret = daemon.output_on(output_uuid, output_type='value', amount=pct,
                                       output_channel=0, additional_options={'source': 'manual'})
            elif 'pwm' in types_list:
                # PWM 출력 — duty cycle(%). 0% 는 OFF.
                if pct > 0.0:
                    ret = daemon.output_on(output_uuid, output_type='pwm', amount=pct,
                                           output_channel=0)
                else:
                    ret = daemon.output_off(output_uuid, output_channel=0)
            elif 'on_off' in types_list:
                # on/off 릴레이 — 1 사이클(60s) 내 비례 ON 시간으로 변환(시간비례 제어).
                # 5% 미만은 소음·수명 보호를 위해 OFF.
                if pct >= 5.0:
                    ret = daemon.output_on(output_uuid, output_type='sec',
                                           amount=max(1.0, 60.0 * pct / 100.0),
                                           output_channel=0)
                else:
                    ret = daemon.output_off(output_uuid, output_channel=0)
            else:
                # 알 수 없는 타입 — value 패스스루(기존 동작 유지).
                ret = daemon.output_on(output_uuid, output_type='value', amount=pct,
                                       output_channel=0, additional_options={'source': 'manual'})

        # The daemon returns (code, msg) on failure instead of raising, so the
        # except below cannot see a timed-out command. Reporting ok here made a
        # manual control that never reached the device look like it worked.
        call_failed, fail_msg = daemon_call_failed(ret)
        if call_failed:
            logger.error("Facility control failed for %s (%s): %s",
                         output_uuid, action, fail_msg)
            return jsonify({'ok': False, 'message': fail_msg}), 502
    except Exception as e:
        logger.exception("Facility control raised for %s (%s)", output_uuid, action)
        return jsonify({'ok': False, 'message': str(e)}), 500

    resp = {
        'ok':       True,
        'slot_key': slot_key,
        'action':   action,
        'percent':  percent,
        'kind':     kind,
        'reason':   reason,
        'ts':       _time.time(),
    }
    if gate_warn:
        resp['gate_warn'] = gate_warn
    return jsonify(resp)


@blueprint.route('/api/aot/facility/<facility_uuid>/estop', methods=['POST'])
@login_required
def api_facility_estop(facility_uuid):
    """IEC § D — emergency stop: set all actuators to safe state for the preset."""
    import time as _time
    from aot.databases.models import GeoFacility, Output
    from aot.aot_client import DaemonControl, daemon_call_failed

    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Insufficient permission'}), 403

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    body = request.get_json(silent=True) or {}
    if body.get('confirm') != 'STOP':
        return jsonify({'ok': False, 'message': 'confirm field must be "STOP"'}), 400

    # Preset-based safe state: heater off, vents closed, curtains open, fans off
    SAFE_ACTIONS = {
        'heater':           'off',
        'boiler':           'off',
        'heat_pump':        'off',
        'side_window':      'off',
        'roof_vent':        'off',
        'thermal_curtain':  'on',   # deploy = safe (insulate)
        'shade_curtain':    'off',  # retract = safe (allow light)
        'fan_circ':         'off',
        'fan_exhaust':      'off',
        'co2_injector':     'off',
        'irrigation':       'off',
        'lighting':         'off',
    }

    daemon = DaemonControl()
    actuators_raw = facility.actuators or {}
    applied = []
    failed  = []

    def _iter_actuators(raw):
        if isinstance(raw, list):
            for i, act in enumerate(raw):
                k = act.get('kind', '')
                yield k, act.get('device_uuid', '')
        else:
            for slot, uuid in raw.items():
                kind_guess = slot.rsplit('_', 1)[0] if '_' in slot else slot
                yield kind_guess, uuid

    for kind, uuid in _iter_actuators(actuators_raw):
        if not uuid:
            continue
        safe = SAFE_ACTIONS.get(kind)
        if safe is None:
            safe = 'off'
        try:
            if safe == 'off':
                ret = daemon.output_off(uuid, output_channel=0)
            else:
                ret = daemon.output_on(uuid, output_channel=0, amount=0)
            # The daemon call swallows timeouts and returns (code, msg) instead
            # of raising, so the except below never fires on the failure that
            # matters most here. Without this check an e-stop that reached
            # nothing still answered ok/failed=0.
            call_failed, fail_msg = daemon_call_failed(ret)
            if call_failed:
                logger.error(
                    "E-stop could not command %s (%s): %s", uuid, kind, fail_msg)
                failed.append({'kind': kind, 'uuid': uuid, 'error': fail_msg})
            else:
                applied.append({'kind': kind, 'uuid': uuid, 'action': safe})
        except Exception as e:
            logger.exception("E-stop raised for %s (%s)", uuid, kind)
            failed.append({'kind': kind, 'uuid': uuid, 'error': str(e)})

    return jsonify({
        # An e-stop that could not reach every actuator must not report ok.
        'ok':      not failed,
        'applied': len(applied),
        'failed':  len(failed),
        'details': applied,
        'errors':  failed,
        'ts':      _time.time(),
    })


# ── 맵 팝업 [현황] 탭 APIs ──────────────────────────────────────────────────────


def _function_facility_uuid(fn):
    """이 env_coordinator 가 붙은 시설 uuid → str|None.

    ⚠ **키가 둘이다.** `select_device` 옵션이 저장 시 `_device_id` 접미사를
      붙이므로 신규는 `geo_facility_id_device_id` 이고, 예전 값은
      `geo_facility_id` 다. 둘을 읽는 자리가 여럿이면 갈라지고, 갈라지면
      "붙었는데 안 붙은 것으로 보이는" 시설이 생긴다 — 읽는 곳은 여기 하나다.
    """
    import json as _json
    try:
        opts = _json.loads(fn.custom_options or '{}') or {}
    except (TypeError, ValueError):
        return None
    return (opts.get('geo_facility_id_device_id')
            or opts.get('geo_facility_id') or None)


def _function_belongs_to_facility(fn, facility_uuid):
    """fn(env_coordinator CustomController) 이 facility_uuid 에 연결된 것인지 확인.

    판정 기준은 `_function_facility_uuid` 하나다 — status/env_summary 공용.
    """
    return _function_facility_uuid(fn) == facility_uuid


def _find_facility_env_coordinator(facility_uuid):
    """facility 에 연결된 env_coordinator CustomController 를 역추적한다.

    복수면 활성 우선.
    """
    from aot.databases.models.controller import CustomController

    matched = []
    try:
        funcs = CustomController.query.filter_by(device='env_coordinator').all()
        matched = [f for f in funcs if _function_belongs_to_facility(f, facility_uuid)]
    except Exception as exc:
        logger.warning('[env_coordinator lookup] %s', exc)
        return None
    if not matched:
        return None
    for f in matched:
        if f.is_activated:
            return f
    return matched[0]


@blueprint.route('/api/aot/facility/<facility_uuid>/env_summary', methods=['GET'])
@login_required
def api_facility_env_summary(facility_uuid):
    """맵 팝업 [현황] 탭 — env_coordinator 사이클 요약 스냅샷.

    데몬이 매 사이클 FunctionRuntimeState.summary_json 에 저장한 값을
    그대로 반환한다 (InfluxDB 조회 없음 — DB 1행 읽기).
    """
    import json as _json
    import time as _time
    from aot.databases.models import GeoFacility
    from aot.databases.models.function import FunctionRuntimeState

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    fn = _find_facility_env_coordinator(facility_uuid)
    if fn is None:
        return jsonify({
            'ok': True, 'function': None, 'summary': None,
            'stale': True, 'ts': _time.time(),
        })

    summary = None
    last_cycle_ts = 0.0
    rs = FunctionRuntimeState.query.filter_by(function_id=fn.unique_id).first()
    if rs:
        last_cycle_ts = rs.last_cycle_ts or 0.0
        if getattr(rs, 'summary_json', None):
            try:
                summary = _json.loads(rs.summary_json)
            except (TypeError, ValueError):
                summary = None

    now = _time.time()
    stale = (not fn.is_activated) or (now - last_cycle_ts > _iec_stale_threshold(fn))
    return jsonify({
        'ok': True,
        'function': {
            'uuid':   fn.unique_id,
            'name':   fn.name,
            'active': bool(fn.is_activated),
        },
        'summary':       summary,
        'stale':         stale,
        # 판정에 쓴 **실제 기준**을 함께 보낸다. 화면이 "최근 몇 분간" 이라고만
        # 말하면 거짓이 된다 — 이 값은 `max(300, 제어주기×3)` 이라 10분 주기
        # 코디네이터에서는 30분이다(2026-08-28). 제어가 살아 있는지를 말하는
        # 가장 중요한 줄이라 여기서 모호하면 안 된다.
        'stale_after_s': int(_iec_stale_threshold(fn)),
        'last_cycle_ts': last_cycle_ts,
        'ts':            now,
    })


@blueprint.route('/api/aot/facility/<facility_uuid>/actuator_history', methods=['GET'])
@login_required
def api_facility_actuator_history(facility_uuid):
    """맵 팝업 차트 오버레이 — 액추에이터 작동 이력 시계열.

    Query params: slot_key (필수), hours (기본 24, 최대 168)

    소스 우선순위:
      1) Output 자체 기록 percent (actuator_paired 등 — measure='duty_cycle',
         unit='percent') → series_type='percent'
      2) duration_time 이벤트 (on/off Output — ON 시각 + 지속시간) →
         ON 시각마다 [ts, 작동분] 1점, series_type='onoff' (막대 렌더)
    """
    import time as _time
    from aot.databases.models import GeoFacility
    from aot.aot_flask.geo.facility_integration import get_facility_integration
    from aot.utils.influx import query_string, influx_to_list

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    slot_key = request.args.get('slot_key', '').strip()
    if not slot_key:
        return jsonify({'ok': False, 'message': 'slot_key required'}), 400
    try:
        hours = min(max(float(request.args.get('hours', 24)), 1.0), 168.0)
    except (TypeError, ValueError):
        hours = 24.0
    past_sec = int(hours * 3600)

    # slot_key → output_uuid (control 엔드포인트와 동일한 해석 순서)
    integ, integ_err = get_facility_integration(facility_uuid)
    if integ_err or not integ:
        return jsonify({'ok': False, 'message': 'Integration load failed'}), 500
    actuators_resolved = integ.get('actuators_resolved') or []
    slot_map = integ.get('actuators_slot_map') or {}
    output_uuid = slot_map.get(slot_key) or ''
    if not output_uuid:
        for ar in actuators_resolved:
            if ar.get('slot_key') == slot_key:
                output_uuid = ar.get('output_uuid', '')
                break
    if not output_uuid:
        for ar in actuators_resolved:
            if ar.get('output_uuid') == slot_key:
                output_uuid = slot_key
                break
    if not output_uuid:
        return jsonify({'ok': False, 'message': 'slot_key not found: ' + slot_key}), 404

    points = []
    series_type = None

    # 1) percent 기록 (위치형 액추에이터)
    # 이벤트 기반 시계열(움직일 때만 기록)이므로 상태 이월(carry-forward)로
    # 윈도 전체를 채운다: 윈도 이전 마지막 값을 윈도 시작점 앵커로 넣고,
    # 마지막 이벤트 값을 현재 시각까지 연장한다. 이 패딩이 없으면 드물게
    # 움직이는 장치는 그래프가 첫 이벤트부터만 그려지거나(짧아 보임),
    # 윈도 내 이벤트가 0건이면 아예 비어 센서 차트와 기간이 어긋난다.
    _LOOKBACK_SEC = 7 * 86400   # 앵커 탐색 범위 (윈도 이전 최대 7일)
    try:
        now_ts = _time.time()
        window_start = now_ts - past_sec
        data = query_string('percent', output_uuid,
                            measure='duty_cycle', channel=0,
                            past_sec=past_sec + _LOOKBACK_SEC, limit=4000)
        if data not in (None, False):
            raw = sorted(
                ([float(ts), float(v)] for ts, v in influx_to_list(data)),
                key=lambda p: p[0])
            anchor = None
            in_window = []
            for ts, v in raw:
                if ts <= window_start:
                    anchor = v
                else:
                    in_window.append([round(ts, 1), v])
            points = in_window
            # 윈도 시작 앵커 (이전 상태 이월)
            if anchor is not None and (not points or points[0][0] - window_start > 60):
                points.insert(0, [round(window_start, 1), anchor])
            # 현재 시각까지 마지막 상태 연장
            if points and now_ts - points[-1][0] > 60:
                points.append([round(now_ts, 1), points[-1][1]])
            if points:
                series_type = 'percent'
    except Exception as exc:
        logger.debug('[actuator_history] percent query failed: %s', exc)

    # 2) duration_time 이벤트 → on/off 작동시간(분) 막대 폴백
    #    ON 시각마다 1점 [ts, 작동분] — 프론트(_applyOverlaySeries)가 막대로 렌더.
    if not points:
        try:
            data = query_string('s', output_uuid,
                                measure='duration_time',
                                past_sec=past_sec, limit=1000)
            if data not in (None, False):
                for ts, dur in influx_to_list(data):
                    try:
                        dur = abs(float(dur))   # 초
                    except (TypeError, ValueError):
                        continue
                    if dur <= 0:
                        continue
                    points.append([round(ts, 1), round(dur / 60.0, 2)])  # 분
                points.sort(key=lambda p: p[0])
                if points:
                    series_type = 'onoff'
        except Exception as exc:
            logger.debug('[actuator_history] duration query failed: %s', exc)

    return jsonify({
        'ok':          True,
        'slot_key':    slot_key,
        'output_uuid': output_uuid,
        'series_type': series_type,
        'points':      points,
        'hours':       hours,
        'ts':          _time.time(),
    })


@blueprint.route('/api/aot/facility/<facility_uuid>/function_state', methods=['POST'])
@login_required
def api_facility_function_state(facility_uuid):
    """맵 팝업 [현황] 탭 — 연결된 env_coordinator 활성/비활성 토글.

    Body: {action: 'activate'|'deactivate'}

    기존 공통 로직(utils_controller.controller_activate/deactivate —
    권한 검사, DB 플래그, 데몬 기동/종료)을 그대로 재사용한다.
    """
    import time as _time
    from aot.databases.models import GeoFacility
    from aot.aot_flask.utils import utils_controller

    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'ok': False, 'message': 'Insufficient permission'}), 403

    # 그룹 스코프(A1a) — 시설 단위. docs/design/access-scope-groups.md
    if not scope.can_operate('geo_facility', facility_uuid):
        return jsonify({'ok': False, 'message': scope.deny_message()}), 403

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    body = request.get_json(silent=True) or {}
    action = body.get('action', '')
    if action not in ('activate', 'deactivate'):
        return jsonify({'ok': False,
                        'message': 'action must be activate|deactivate'}), 400

    fn = _find_facility_env_coordinator(facility_uuid)
    if fn is None:
        return jsonify({'ok': False,
                        'message': 'No env_coordinator linked to facility'}), 404

    if action == 'activate':
        messages = utils_controller.controller_activate(fn.unique_id)
    else:
        messages = utils_controller.controller_deactivate(fn.unique_id)

    errors = messages.get('error') or []
    if errors:
        return jsonify({'ok': False, 'message': '; '.join(str(e) for e in errors),
                        'function_uuid': fn.unique_id}), 400

    # 이 시설의 /overview 캐시를 버린다. 누른 사람의 창은 `?fresh=1` 로 다시
    # 읽지만, **다른 창·다른 사람·다른 경로**(AI 도구·스케줄러)로 바뀐 경우에는
    # 그 우회가 없다 — 안 버리면 열려 있는 모달이 최대 30초 동안 옛 운전 상태를
    # 내건다. 상태를 바꾼 쪽이 버리는 것이 맞다.
    invalidate_facility_overview(facility_uuid)

    return jsonify({
        'ok':            True,
        'function_uuid': fn.unique_id,
        'function_name': fn.name,
        'active':        action == 'activate',
        'ts':            _time.time(),
    })


# ── 맵 팝업 [현황] 시설 정보/사진/설명 APIs ─────────────────────────────────────


def _facility_dims(facility):
    """크기/면적/부피를 반환한다.

    부피/바닥면적: facility.computed (facility_calc.compute_capacity 결과 —
    지붕 형상(아치/박공)까지 반영한 정식 계산값) 우선.
    캐시가 없을 때만 geometry_3d 기반 단순 추정으로 폴백:
      면적 = area_m2 캐시 또는 span × length × bay 수,
      부피 = 면적 × 평균 높이(처마 + (용마루-처마)/2). 폴백 시 estimated=True.
    """
    g = facility.geometry_3d or {}
    if not isinstance(g, dict):
        return {}

    def _f(key):
        try:
            v = g.get(key)
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    span   = _f('span_width_m')
    length = _f('length_m')
    eave   = _f('eave_height_m')
    ridge  = _f('ridge_height_m')
    bays   = 1
    try:
        if (facility.structure or '') == 'connected':
            bays = max(int(facility.bay_count or 1), 1)
    except (TypeError, ValueError):
        pass

    # 정식 계산값 — get_facility_integration 이 compute_capacity(지붕 형상
    # 반영)를 실행해 capacity_meta.volume_m3 로 노출한다 (30초 TTL 캐시).
    # facility.computed DB 캐시는 저장 시점에만 갱신되므로 사용하지 않는다.
    area      = None
    volume    = None
    estimated = False
    try:
        from aot.aot_flask.geo.facility_integration import get_facility_integration
        integ, _ierr = get_facility_integration(facility.unique_id)
        if integ:
            v = (integ.get('capacity_meta') or {}).get('volume_m3')
            volume = float(v) if v is not None else None
    except Exception:
        pass

    if area is None:
        area = _f('area_m2')
        if area is None and span and length:
            # compute_capacity 의 floor_m2 와 동일한 공식 — 추정 아님
            area = span * length * bays

    if volume is None and area and eave is not None:
        avg_h = eave + ((ridge - eave) / 2.0
                        if (ridge is not None and ridge > eave) else 0.0)
        volume = area * avg_h
        estimated = True

    return {
        'span_width_m':  span,
        'length_m':      length,
        'eave_height_m': eave,
        'ridge_height_m': ridge,
        'bay_count':     bays,
        'area_m2':       round(area, 1) if area else None,
        'volume_m3':     round(volume, 1) if volume else None,
        'estimated':     estimated,
    }


@blueprint.route('/api/aot/facility/<facility_uuid>/info', methods=['GET', 'POST'])
@login_required
def api_facility_info(facility_uuid):
    """맵 팝업 [현황] — 시설 대표사진/치수/설명.

    GET  → {photo_url, description, dims, can_edit}
    POST → {description} 저장 (editor 이상 — edit_settings 권한)
    """
    import time as _time
    from aot.databases.models import GeoFacility
    from aot.aot_flask.extensions import db as _db

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    can_edit = utils_general.user_has_permission('edit_settings', silent=True)

    if request.method == 'POST':
        if not can_edit:
            return jsonify({'ok': False, 'message': 'Insufficient permission'}), 403
        body = request.get_json(silent=True) or {}
        desc = body.get('description')
        if desc is None or not isinstance(desc, str):
            return jsonify({'ok': False, 'message': 'description required'}), 400
        facility.notes = desc.strip()[:2000]
        _db.session.commit()

    photo_url = None
    if getattr(facility, 'photo_path', None):
        photo_url = '/facility_photo/' + facility.photo_path

    return jsonify({
        'ok':          True,
        'photo_url':   photo_url,
        'description': facility.notes or '',
        'dims':        _facility_dims(facility),
        'can_edit':    bool(can_edit),
        'ts':          _time.time(),
    })


_OVERVIEW_CACHE = {}
_OVERVIEW_LOCKS = {}
_OVERVIEW_TTL_S = 30


def invalidate_facility_overview(facility_uuid):
    """이 시설의 overview 캐시를 버린다.

    **상태를 바꾼 쪽이 부른다** — 대표 측정 지정(rep_key), 자동제어 토글
    (function_state). `?fresh=1` 은 누른 사람의 창만 구하므로, 다른 탭·다른
    사람·다른 경로(AI 도구·스케줄러)로 바뀐 경우에는 이것이 유일한 통로다.
    """
    _OVERVIEW_CACHE.pop(facility_uuid, None)


def _unwrap_json(resp):
    """뷰 함수를 직접 부른 결과(Response 또는 (Response, status))에서 dict 만."""
    r = resp[0] if isinstance(resp, tuple) else resp
    try:
        return r.get_json()
    except Exception:
        return None


@blueprint.route('/api/aot/facility/<facility_uuid>/overview', methods=['GET'])
@login_required
def api_facility_overview(facility_uuid):
    """맵 팝업 [현황]/[개요] 1-요청 묶음 — env_summary + status + info.

    팝업이 셋을 개별 fetch 하면 gunicorn(gthread) 워커 스레드를 3개
    동시에 점유해, 페이지 로드 직후 맵 위젯 폴링 버스트와 겹칠 때
    스레드 풀이 포화되어 모달 렌더가 1초+ 지연된다(콜드 시 4초+ 관측).
    셋을 한 요청으로 묶어 스레드 점유를 1/3 로 줄인다 — 서버 총 작업량은
    같지만 나머지 스레드를 다른 요청에 양보한다.

    개별 엔드포인트(/status 5초 폴링 등)는 그대로 유지된다.

    구역 내용과 같은 30초 캐시 + 단일 비행. 넣기 전 실측이 534~641ms 였고
    **열 때마다** 그 값이었다(같은 시설의 /runtime 은 17ms). `?fresh=1` 로
    우회한다 — 사진 교체·설명 저장·자동제어 토글 직후의 재조회는 캐시를
    타면 안 된다. 방금 끈 것이 켜진 채로 보이면 토글이 고장 난 것처럼 읽힌다.
    """
    import time as _time
    from aot.aot_flask.geo.site_summary import cached_build

    force = request.args.get('fresh') in ('1', 'true')
    payload = cached_build(_OVERVIEW_CACHE, _OVERVIEW_LOCKS, facility_uuid,
                           _OVERVIEW_TTL_S,
                           lambda: _build_facility_overview(facility_uuid),
                           force)
    if payload is None:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    # can_edit 는 캐시 밖에서 매번 다시 넣는다 — 캐시는 전역이라 처음 연
    # 사람의 권한이 다음 사람에게 그대로 간다(구역 내용과 같은 규칙).
    # info 안에도 같은 키가 있어 두 곳 다 덮는다.
    payload = dict(payload)
    can_edit = utils_general.user_has_permission('edit_settings', silent=True)
    payload['can_edit'] = can_edit
    if isinstance(payload.get('info'), dict):
        payload['info'] = dict(payload['info'])
        payload['info']['can_edit'] = can_edit
    payload['ts'] = _time.time()
    return jsonify(payload)


def _build_facility_overview(facility_uuid):
    """overview 응답 본체(캐시에 담기는 부분). 시설을 못 찾으면 None.

    상위 site 는 모달 제목줄의 "상위로" 화살표용이다. 시설은 구역 안에 있을
    수도 있어 한 단계 위가 아니라 site 가 나올 때까지 거슬러 올라간다.
    `area_status` 는 구역·필지와 **같은 판정**을 쓴다(통신·배터리·센서 응답)
    — IEC 의 `status.level` 과 다른 축이다. 그쪽은 자동제어가 도는지를 말하고
    이쪽은 장치가 살아 있는지를 말한다.
    """
    import time as _time

    site = None
    area_status = None
    rep_key = None
    hidden_rows = {}
    try:
        from aot.databases.models import GeoFacility, GeoShape
        from aot.aot_flask.geo.site_summary import (
            parent_site_for_shape, status_for_shape, rep_key_of, hidden_rows_of)
        row = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
        if row is not None and row.shape_uuid:
            site = parent_site_for_shape(row.shape_uuid)
            area_status = status_for_shape(row.shape_uuid)
            # 대표 측정 지정은 구역과 **같은 자리**(도형의 meta_json)에 있다 —
            # 필지 요약의 행(_child_entry)이 구역·시설을 가리지 않고 같은
            # rep_key_of() 로 읽으므로, 시설만 다른 데 두면 그 행이 지정을 무시한다.
            shape = GeoShape.query.filter_by(unique_id=row.shape_uuid).first()
            if shape is not None:
                rep_key = rep_key_of(shape)
                hidden_rows = hidden_rows_of(shape)
    except Exception:
        logger.warning('[facility/overview] parent site / status lookup failed',
                       exc_info=True)

    info = _unwrap_json(api_facility_info(facility_uuid))
    if info is None:
        return None   # 시설을 못 찾았다 — 캐시에 남기지 않는다

    # can_edit 는 라우트가 응답마다 다시 넣는다(캐시는 전역).
    from aot.aot_flask.geo import irrigation_status, weather_hazards
    # 마지막 관수 — 시설에서는 관수 피팅, 구획이 있으면 프로그램이 선언한
    # 관수 함수가 근거다. 근거가 없으면 None 이고 화면은 아무 말도 안 한다.
    _plot = None
    try:
        from aot.aot_flask.geo import plot_context as _pc
        _rows = _pc.plots_in_facility(facility_uuid)
        _plot = _rows[0] if _rows else None
    except Exception:                                       # noqa: BLE001
        _plot = None
    # 프로그램이 정한 **한계**(주/야간 온도 · 습도). 목표(vpd·co2)는 코디네이터의
    # 런타임 요약(env_summary)이 이미 싣고 있다 — 그쪽은 곡선까지 풀린 값이라
    # 여기서 다시 내면 두 숫자가 생긴다. 한계만 프로그램에서 가져온다.
    try:
        from aot.aot_flask.geo import coordinator_plot as _cp
        _limits = _cp.program_limits(_plot)
    except Exception:                                       # noqa: BLE001
        _limits = {}

    # 적산온도(GDD)·광합성 지표(DLI) — 시설 기준(bay 무관)으로 하나만 낸다.
    # 대표는 위에서 관수 근거로 이미 고른 `_plot`(구획 목록의 첫 번째)을
    # 그대로 쓴다 — 같은 시설에서 관수는 구획 A, GDD는 구획 B를 기준으로
    # 삼으면 사용자가 두 숫자를 다른 재배기로 오독한다.
    #
    # ⚠ 이 "첫 번째" 규칙은 구획이 둘 이상일 때 실증되지 않았다 — 실제로
    # 여러 작기가 함께 도는 시설에서 어느 것을 대표로 볼지는 운영 데이터로
    # 다시 봐야 한다(다구획 집계 방식은 후속 작업).
    _gdd, _dli = None, None
    if _plot is not None and getattr(_plot, 'program_uuid', None):
        try:
            from aot.databases.models import GeoProgram
            _program = GeoProgram.query.filter_by(
                unique_id=_plot.program_uuid).first()
            if _program is not None:
                from aot.aot_flask.geo import plot_context as _pc2
                _gdd = _pc2.gdd_accumulated(_plot, _program)
                _dli = _pc2.dli_accumulated(_plot, _program)
        except Exception:                                   # noqa: BLE001
            logger.warning('[facility/overview] GDD/DLI 계산 실패',
                           exc_info=True)

    return {
        'ok':          True,
        'limits':      _limits,
        'irrigation':  irrigation_status.last_irrigation(facility_uuid, _plot),
        # 곧 닥칠 기상 위험 — 시설·노지가 **같은 판정**을 쓴다(같은 예보 파일).
        # 여기 실어 보내면 모달이 별도 요청 없이 그린다.
        'hazards':     weather_hazards.upcoming_cached(),
        'env_summary': _unwrap_json(api_facility_env_summary(facility_uuid)),
        'status':      _unwrap_json(api_facility_iec_status(facility_uuid)),
        'info':        info,
        'site':        site,
        'area_status': area_status,
        'rep_key':     rep_key,
        # [현황] 카드에서 빼 둔 항목 — 거르는 것은 화면이 한다(site_summary 주석).
        'hidden_rows': hidden_rows,
        # 코디네이터 사이클 적분값(`env_summary.summary.photo.dli_today`)과는
        # **다른 값**이다 — 섞이지 않게 키를 분리한다(plot_context.dli_accumulated
        # 독스트링 참조). 코디네이터가 없는 시설에도 뜨는 것이 이 값의 존재 이유다.
        'plot_gdd':    _gdd,
        'plot_dli':    _dli,
        'ts':          _time.time(),
    }


@blueprint.route('/api/aot/facility/<facility_uuid>/rep_key', methods=['POST'])
@login_required
def api_facility_rep_key(facility_uuid):
    """시설의 대표 측정 지정 — 구역과 같은 자리·같은 규칙.

    시설 uuid 로 들어와 **도형**(GeoFacility.shape_uuid)에 쓴다. 지도에 올라와
    있지 않은 시설은 도형이 없어 지정할 자리도 없다(422).
    """
    from aot.aot_flask.extensions import db as _db
    from aot.databases.models import GeoFacility, GeoShape
    from aot.aot_flask.geo.site_summary import invalidate_rep

    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    row = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if row is None:
        return jsonify({'ok': False, 'error': 'facility not found'}), 404
    if not row.shape_uuid:
        return jsonify({'ok': False, 'error': 'facility has no shape'}), 422
    shape = GeoShape.query.filter_by(unique_id=row.shape_uuid).first()
    if shape is None:
        return jsonify({'ok': False, 'error': 'shape not found'}), 404

    body = request.get_json(force=True, silent=True) or {}
    key = body.get('key')
    if key is not None and not isinstance(key, str):
        return jsonify({'ok': False, 'error': 'key must be a string or null'}), 422
    key = (key or '').strip() or None

    # dict() 로 새 객체 — 제자리 수정은 SQLAlchemy 가 못 본다(routes_geo 주석).
    meta = dict(shape.meta_json or {})
    if key:
        meta['rep_key'] = key
    else:
        meta.pop('rep_key', None)
    shape.meta_json = meta
    _db.session.commit()

    invalidate_rep(shape)
    invalidate_facility_overview(facility_uuid)
    return jsonify({'ok': True, 'rep_key': key})


@blueprint.route('/api/aot/facility/<facility_uuid>/hidden_rows', methods=['POST'])
@login_required
def api_facility_hidden_rows(facility_uuid):
    """시설 [현황] 카드에서 뺄 항목 — 구역과 같은 자리·같은 규칙.

    저장 로직은 `routes_geo._save_hidden_rows` 하나다. 시설·구역이 각자
    한 벌씩 들고 있으면 검사 규칙이 조용히 갈린다(rep_key 가 실제로 그랬다).
    """
    from aot.databases.models import GeoFacility, GeoShape
    from aot.aot_flask.routes_geo import _save_hidden_rows

    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    row = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if row is None:
        return jsonify({'ok': False, 'error': 'facility not found'}), 404
    if not row.shape_uuid:
        return jsonify({'ok': False, 'error': 'facility has no shape'}), 422
    shape = GeoShape.query.filter_by(unique_id=row.shape_uuid).first()
    if shape is None:
        return jsonify({'ok': False, 'error': 'shape not found'}), 404

    body = request.get_json(force=True, silent=True) or {}
    err, code, rows = _save_hidden_rows(shape, body)
    if err is not None:
        return err, code

    invalidate_facility_overview(facility_uuid)
    return jsonify({'ok': True, 'hidden_rows': rows})


@blueprint.route('/api/aot/facility/<facility_uuid>/photo', methods=['POST'])
@login_required
def api_facility_photo(facility_uuid):
    """시설 대표사진 업로드 (editor 이상). multipart field: photo

    notes 첨부와 동일한 UUID 파일명 규칙. 기존 사진 파일은 교체 시 삭제.
    """
    import os
    import time as _time
    import uuid as _uuid
    from aot.config import PATH_FACILITY_PHOTOS
    from aot.databases.models import GeoFacility
    from aot.aot_flask.extensions import db as _db

    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'message': 'Insufficient permission'}), 403

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    file = request.files.get('photo')
    if not file or not file.filename:
        return jsonify({'ok': False, 'message': 'photo file required'}), 400

    from werkzeug.utils import secure_filename
    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
        return jsonify({'ok': False, 'message': 'File type not allowed'}), 400

    unique_filename = '{}_{}'.format(_uuid.uuid4(), filename)
    os.makedirs(PATH_FACILITY_PHOTOS, exist_ok=True)
    file.save(os.path.join(PATH_FACILITY_PHOTOS, unique_filename))

    # 기존 사진 삭제 (교체)
    old = getattr(facility, 'photo_path', None)
    if old:
        old_path = os.path.join(PATH_FACILITY_PHOTOS, old)
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    facility.photo_path = unique_filename
    _db.session.commit()

    return jsonify({
        'ok':        True,
        'photo_url': '/facility_photo/' + unique_filename,
        'ts':        _time.time(),
    })


@blueprint.route('/facility_photo/<path:filename>', methods=['GET'])
@login_required
def serve_facility_photo(filename):
    """시설 대표사진 서빙 (note_attachment 와 동일 패턴)."""
    import os
    from flask import send_file, abort
    from aot.config import PATH_FACILITY_PHOTOS

    base = os.path.realpath(PATH_FACILITY_PHOTOS)
    file_path = os.path.realpath(os.path.join(base, filename))
    if not file_path.startswith(base + os.sep) or not os.path.isfile(file_path):
        return abort(404)
    return send_file(file_path)


@blueprint.route('/api/aot/coordinator/<function_uuid>/overview', methods=['GET'])
@login_required
def api_coordinator_overview(function_uuid):
    """통합환경제어 **설정 화면 머리말** — 지금 무엇을 하고 있고 목표는 어디 있나.

    설계: `docs/design/env-coordinator-settings-redesign.md` §3-1 (단계 A).

    ## 왜 필요한가

    설정 화면이 "어떤 값을 설정했나" 만 보여 주고 **"그래서 어떻게 도는가" 는
    다른 화면(지도 위젯 모달)에 있었다.** 62개를 설정하고 저장했는데 결과를
    확인할 방법이 그 화면에 없으면, 설정이 맞는지 알 수 없고 **확인할 수 없는
    것은 믿을 수 없다.**

    그리고 목표(VPD·온도 곡선)는 이 화면이 아니라 **구획에 붙은 프로그램**이
    갖는데(`GeoProgram.targets_methods`), 화면이 그 사실을 말하지 않아서
    사용자가 "몇 도로 맞출까" 를 여기서 찾으면 영영 못 찾는다.

    ## ⚠ 요약 판정을 다시 쓰지 않는다

    `api_facility_env_summary` 를 그대로 부르고 결과만 푼다. 같은 사실을 두
    곳에서 계산하면 갈라지고, 갈라지면 설정 화면과 지도 모달이 **다른 말을
    한다** — 이 도메인이 이미 크게 데인 실패다.

    ## ⚠ 가벼워야 한다

    `/api/aot/facility/<uuid>/overview` 는 대지 요약·기상 위험·관수·면적까지
    묶어 30초 캐시로 낸다(실측 534~641ms). 설정 화면 머리말에는 과하다 —
    여기서는 런타임 요약 1행 + 구획 조회만 한다.
    """
    import time as _time

    from aot.databases.models import GeoFacility, GeoPlot, GeoProgram
    from aot.databases.models.controller import CustomController

    fn = CustomController.query.filter_by(unique_id=function_uuid).first()
    if fn is None or fn.device != 'env_coordinator':
        return jsonify({'ok': False, 'message': 'Not an env coordinator'}), 404

    facility_uuid = _function_facility_uuid(fn)
    if not facility_uuid:
        # 시설을 안 고른 상태도 **말해야 한다.** 침묵하면 "아직 안 붙었다" 와
        # "붙었는데 안 돈다" 를 화면이 구분하지 못한다.
        return jsonify({'ok': True, 'facility': None, 'env': None,
                        'plots': [], 'ts': _time.time()})

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    env = _unwrap_json(api_facility_env_summary(facility_uuid))

    # ⚠ **이 화면은 시설이 아니라 이 코디네이터를 말한다.**
    # 시설 요약은 코디네이터가 여럿이면 "활성 우선" 으로 하나를 고른다
    # (`_find_facility_env_coordinator`). 그래서 한 시설을 가리키는 코디네이터가
    # 둘이면, **꺼져 있는 쪽의 설정 창이 켜져 있는 쪽의 상태를 자기 것처럼**
    # 보여 준다 — 2026-08-28 실측: 비활성 코디네이터가 "현재 9분 전" 을 띄웠다.
    # 신원은 요청받은 함수의 것으로 되돌리고, 실제로 도는 쪽이 따로 있으면
    # 그 사실을 함께 싣는다(침묵하면 "왜 안 도나" 에 답할 근거가 없다).
    if isinstance(env, dict):
        reported = (env.get('function') or {}).get('uuid')
        if reported and reported != function_uuid:
            other_name = (env.get('function') or {}).get('name') or ''
            env = dict(env)
            env['function'] = {'uuid': function_uuid,
                               'name': fn.name,
                               'active': bool(fn.is_activated)}
            env['other_coordinator'] = {'uuid': reported, 'name': other_name}

    # 목표가 어디서 오는지 — 이 시설의 **살아 있는** 구획과 그 프로그램.
    plots = []
    try:
        rows = GeoPlot.query.filter_by(facility_uuid=facility_uuid).all()
        progs = {}
        for row in rows:
            if row.ended_on is not None:
                continue                       # 끝난 작기는 목표를 정하지 않는다
            prog = None
            if row.program_uuid:
                if row.program_uuid not in progs:
                    progs[row.program_uuid] = GeoProgram.query.filter_by(
                        unique_id=row.program_uuid).first()
                prog = progs[row.program_uuid]
            plots.append({
                'uuid':    row.unique_id,
                'name':    row.name or row.subject or '',
                'subject': row.subject or '',
                'bay_id':  row.bay_id,
                'program': ({'uuid': prog.unique_id, 'name': prog.name}
                            if prog is not None else None),
            })
    except Exception as exc:                                    # noqa: BLE001
        logger.warning('[coordinator overview] plot lookup: %s', exc)

    # 이 시설에 **어떤 종류의 액추에이터가 등록돼 있는가.** 설정 화면이
    # "없는 장비를 설정하고 있다" 를 말해 주려면 이것이 필요하다 — 차광막이
    # 없는 시설에서 차광 기준을 아무리 정해도 아무 일이 안 일어나는데, 화면은
    # 그 칸을 똑같이 보여 준다(2026-08-28: 세 시설 모두 shade·lighting 이
    # 하나도 없었다).
    #
    # ⚠ 출처는 **코디네이터가 쓰는 것과 같아야 한다**(`actuators_resolved`).
    #   `env.summary.commands` 로 대신하면 "이번 사이클에 명령을 받은 것" 만
    #   보이므로, 아직 한 번도 안 돈 코디네이터에서는 전부 없다고 말한다.
    actuator_kinds = []
    try:
        from aot.aot_flask.geo.facility_integration import (
            get_facility_integration as _gfi_kinds)
        _integ, _err = _gfi_kinds(facility_uuid)
        if not _err and isinstance(_integ, dict):
            actuator_kinds = sorted({
                a.get('kind') for a in (_integ.get('actuators_resolved') or [])
                if a.get('kind')})
    except Exception as exc:                                    # noqa: BLE001
        logger.warning('[coordinator overview] actuator kinds: %s', exc)

    return jsonify({
        'ok': True,
        'facility': ({'uuid': facility_uuid,
                      'name': getattr(facility, 'name', '') or '',
                      'actuator_kinds': actuator_kinds}
                     if facility is not None else
                     {'uuid': facility_uuid, 'name': '', 'missing': True,
                      'actuator_kinds': []}),
        'env':   env,
        'plots': plots,
        'ts':    _time.time(),
    })
