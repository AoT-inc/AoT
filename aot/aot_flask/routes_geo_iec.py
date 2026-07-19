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
    function_uuid = request.args.get('function_uuid', '').strip()
    try:
        fn = None
        if function_uuid:
            fn = CustomController.query.filter_by(
                unique_id=function_uuid, device='env_coordinator').first()
        if fn is None:
            # Auto-select: prefer activated
            fn = CustomController.query.filter_by(
                device='env_coordinator', is_activated=True).first()
            if fn is None:
                fn = CustomController.query.filter_by(
                    device='env_coordinator').first()

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
            reasons.append('No IEC function configured')
            level = 'warn'
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

        if sp and sp.target_vpd_kpa is not None and indoor.get('vpd_kpa') is not None:
            tol = 0.15
            deviation = abs(indoor['vpd_kpa'] - sp.target_vpd_kpa)
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

        if sp and sp.target_co2_ppm is not None and indoor.get('co2_ppm') is not None:
            if indoor['co2_ppm'] > sp.target_co2_ppm * 1.1:
                reasons.append('CO2 {}>{} ppm'.format(int(indoor['co2_ppm']), int(sp.target_co2_ppm)))
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


@blueprint.route('/api/aot/facility/<facility_uuid>/setpoints', methods=['GET', 'POST'])
@login_required
def api_facility_setpoints(facility_uuid):
    """IEC § C — read or write facility setpoints.

    Columns mirror env_coordinator custom_options directly:
      target_vpd_kpa   → target_vpd      (L1 primary VPD target)
      guide_t_min/max  → guide_T_min/max (VPD decomposition T guidance)
      guide_rh_min/max → guide_RH_min/max (VPD decomposition RH guidance)
      temp_min/max_c   → temp_min/max    (hard safety constraint)
      humid_min/max_pct→ humid_min/max   (hard safety constraint)
      target_co2_ppm   → target_co2      (secondary CO2 target)
    """
    from aot.databases.models import GeoFacility
    from aot.databases.models.geo_facility_setpoint import GeoFacilitySetpoint
    from aot.databases import set_uuid

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    if request.method == 'GET':
        sp = GeoFacilitySetpoint.query.filter_by(facility_uuid=facility_uuid).first()
        if not sp:
            return jsonify({'ok': True, 'setpoints': None})
        return jsonify({'ok': True, 'setpoints': sp.to_dict()})

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

    vpd       = _float('target_vpd_kpa')
    g_t_min   = _float('guide_t_min_c')
    g_t_max   = _float('guide_t_max_c')
    g_rh_min  = _float('guide_rh_min_pct')
    g_rh_max  = _float('guide_rh_max_pct')
    t_min     = _float('temp_min_c')
    t_max     = _float('temp_max_c')
    h_min     = _float('humid_min_pct')
    h_max     = _float('humid_max_pct')
    co2       = _float('target_co2_ppm')

    _in_range(vpd,      0.1, 3.0,  'target_vpd_kpa')
    _in_range(g_t_min,  0,   40,   'guide_t_min_c')
    _in_range(g_t_max,  0,   45,   'guide_t_max_c')
    _in_range(g_rh_min, 10,  95,   'guide_rh_min_pct')
    _in_range(g_rh_max, 10,  99,   'guide_rh_max_pct')
    _in_range(t_min,   -10,  40,   'temp_min_c')
    _in_range(t_max,    0,   50,   'temp_max_c')
    _in_range(h_min,    10,  95,   'humid_min_pct')
    _in_range(h_max,    10,  99,   'humid_max_pct')
    _in_range(co2,      300, 2000, 'target_co2_ppm')

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

    if vpd      is not None: sp.target_vpd_kpa   = vpd
    if g_t_min  is not None: sp.guide_t_min_c    = g_t_min
    if g_t_max  is not None: sp.guide_t_max_c    = g_t_max
    if g_rh_min is not None: sp.guide_rh_min_pct = g_rh_min
    if g_rh_max is not None: sp.guide_rh_max_pct = g_rh_max
    if t_min    is not None: sp.temp_min_c        = t_min
    if t_max    is not None: sp.temp_max_c        = t_max
    if h_min    is not None: sp.humid_min_pct     = h_min
    if h_max    is not None: sp.humid_max_pct     = h_max
    if co2      is not None: sp.target_co2_ppm    = co2

    sp.source   = 'manual'
    sp.operator = current_user.name if current_user.is_authenticated else None
    from datetime import datetime
    sp.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'ok': False, 'message': str(e)}), 500

    # ── Mirror to env_coordinator CustomController.custom_options + cmd_reload ──
    # Without this the GeoFacilitySetpoint row is updated but env_coordinator
    # keeps the old self.target_vpd / self.guide_T_* values until restart.
    mirror_result = {'mirrored': False, 'reload_sent': False, 'detail': None}
    try:
        from aot.databases.models import CustomController
        import json as _json
        funcs = CustomController.query.filter_by(device='env_coordinator').all()
        matched = [
            f for f in funcs
            if (_json.loads(f.custom_options or '{}') or {})
                .get('geo_facility_id_device_id') == facility_uuid
        ]
        _COL_TO_OPT = {
            'target_vpd_kpa':   'target_vpd',
            'guide_t_min_c':    'guide_T_min',
            'guide_t_max_c':    'guide_T_max',
            'guide_rh_min_pct': 'guide_RH_min',
            'guide_rh_max_pct': 'guide_RH_max',
            'temp_min_c':       'temp_min',
            'temp_max_c':       'temp_max',
            'humid_min_pct':    'humid_min',
            'humid_max_pct':    'humid_max',
            'target_co2_ppm':   'target_co2',
        }
        new_vals = {
            'target_vpd_kpa':   vpd,
            'guide_t_min_c':    g_t_min,
            'guide_t_max_c':    g_t_max,
            'guide_rh_min_pct': g_rh_min,
            'guide_rh_max_pct': g_rh_max,
            'temp_min_c':       t_min,
            'temp_max_c':       t_max,
            'humid_min_pct':    h_min,
            'humid_max_pct':    h_max,
            'target_co2_ppm':   co2,
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

    return jsonify({
        'ok': True,
        'setpoints': sp.to_dict(),
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
    from aot.aot_client import DaemonControl
    from aot.aot_flask.geo.facility_integration import get_facility_integration
    from aot.aot_flask.geo.facility_sensors import read_outdoor_sensors, compute_spatial_internal
    from aot.functions.utils.env_control.safety_gates import (
        SafetyPreGate, PreGateConfig,
    )

    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Insufficient permission'}), 403

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
            opts = _json.loads(f.custom_options or '{}') or {}
            if opts.get('geo_facility_id_device_id') == facility_uuid:
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
    try:
        if action == 'off':
            daemon.output_off(output_uuid, output_channel=0)
        elif action == 'on':
            daemon.output_on(output_uuid, output_channel=0, amount=0)
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
                daemon.output_on(output_uuid, output_type='value', amount=pct,
                                 output_channel=0, additional_options={'source': 'manual'})
            elif 'pwm' in types_list:
                # PWM 출력 — duty cycle(%). 0% 는 OFF.
                if pct > 0.0:
                    daemon.output_on(output_uuid, output_type='pwm', amount=pct,
                                     output_channel=0)
                else:
                    daemon.output_off(output_uuid, output_channel=0)
            elif 'on_off' in types_list:
                # on/off 릴레이 — 1 사이클(60s) 내 비례 ON 시간으로 변환(시간비례 제어).
                # 5% 미만은 소음·수명 보호를 위해 OFF.
                if pct >= 5.0:
                    daemon.output_on(output_uuid, output_type='sec',
                                     amount=max(1.0, 60.0 * pct / 100.0),
                                     output_channel=0)
                else:
                    daemon.output_off(output_uuid, output_channel=0)
            else:
                # 알 수 없는 타입 — value 패스스루(기존 동작 유지).
                daemon.output_on(output_uuid, output_type='value', amount=pct,
                                 output_channel=0, additional_options={'source': 'manual'})
    except Exception as e:
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
    from aot.aot_client import DaemonControl

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
                daemon.output_off(uuid, output_channel=0)
            else:
                daemon.output_on(uuid, output_channel=0, amount=0)
            applied.append({'kind': kind, 'uuid': uuid, 'action': safe})
        except Exception as e:
            failed.append({'kind': kind, 'uuid': uuid, 'error': str(e)})

    return jsonify({
        'ok':      True,
        'applied': len(applied),
        'failed':  len(failed),
        'details': applied,
        'errors':  failed,
        'ts':      _time.time(),
    })


# ── 맵 팝업 [현황] 탭 APIs ──────────────────────────────────────────────────────


def _find_facility_env_coordinator(facility_uuid):
    """facility 에 연결된 env_coordinator CustomController 를 역추적한다.

    custom_options 의 geo_facility_id_device_id (또는 legacy geo_facility_id)
    가 facility_uuid 와 일치하는 function 을 찾는다. 복수면 활성 우선.
    """
    import json as _json
    from aot.databases.models.controller import CustomController

    matched = []
    try:
        funcs = CustomController.query.filter_by(device='env_coordinator').all()
        for f in funcs:
            try:
                opts = _json.loads(f.custom_options or '{}') or {}
            except (TypeError, ValueError):
                continue
            fac_id = (opts.get('geo_facility_id_device_id')
                      or opts.get('geo_facility_id') or '')
            if fac_id == facility_uuid:
                matched.append(f)
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
    """
    import time as _time

    def _unwrap(resp):
        r = resp[0] if isinstance(resp, tuple) else resp
        try:
            return r.get_json()
        except Exception:
            return None

    return jsonify({
        'ok':          True,
        'env_summary': _unwrap(api_facility_env_summary(facility_uuid)),
        'status':      _unwrap(api_facility_iec_status(facility_uuid)),
        'info':        _unwrap(api_facility_info(facility_uuid)),
        'ts':          _time.time(),
    })


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
