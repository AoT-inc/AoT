# coding=utf-8
"""routes_geo 의 시설 CRUD·runtime·bays·calibration·apply 라우트. blueprint 는 routes_geo 것을 공유한다."""
from flask import render_template, redirect, url_for, current_app, request, jsonify, Response
from datetime import datetime
import time
import threading
from flask_login import login_required, current_user
from flask_babel import gettext as _
from aot.aot_flask.utils import utils_general
from aot.aot_flask.utils import utils_http
from aot.databases.models import GeoMap, GeoShape, Input, Output, PID, Conditional, CustomController, Function, DeviceMeasurements
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_geo
from aot.aot_flask.access import scope
from aot.aot_flask.routes_geo import blueprint  # noqa: E402




# ============================================================
# Facility Routes (PRD/DESIGN-GEO-FACILITY-001)
# ============================================================

@blueprint.route('/geo/facility')
@login_required
def page_facility():
    """Facility Design page — register building-level facility specs."""
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))

    from aot.databases.models import GeoFacility, Measurement, Unit
    from aot.aot_flask.utils.utils_general import add_custom_measurements, add_custom_units

    # [P3] 모든 지도가 동등하다 — category 분기 폐기.
    design_maps = GeoMap.query.order_by(GeoMap.updated_at.desc()).all()
    facilities = GeoFacility.query.order_by(GeoFacility.updated_at.desc()).all()

    # Input channel choices — system-standard pattern (same as PID/Function/Conditional pages).
    # Value format: '{input_id},{measurement_id}'
    all_inputs = Input.query.filter(Input.is_activated).order_by(Input.name.asc()).all()
    dict_measurements = add_custom_measurements(Measurement.query.all())
    dict_units = add_custom_units(Unit.query.all())
    choices_input = utils_general.choices_inputs(all_inputs, dict_units, dict_measurements)

    # measurement_id → raw slug (e.g. 'temperature') for JS type auto-detection.
    input_ids = [inp.unique_id for inp in all_inputs]
    dm_rows = (DeviceMeasurements.query
               .filter(DeviceMeasurements.device_id.in_(input_ids))
               .order_by(DeviceMeasurements.channel.asc())
               .all()
               if input_ids else [])
    meas_id_slug = {dm.unique_id: dm.measurement or '' for dm in dm_rows}

    # conversion_id → convert_unit_to batch lookup (for displaying the converted unit)
    from aot.databases.models.measurement import Conversion as _Conversion
    _conv_ids = {dm.conversion_id for dm in dm_rows if dm.conversion_id}
    _conv_unit = {}
    if _conv_ids:
        for _cv in _Conversion.query.filter(_Conversion.unique_id.in_(_conv_ids)).all():
            _conv_unit[_cv.unique_id] = _cv.convert_unit_to or ''

    def _effective_unit(dm):
        """Use convert_unit_to if a conversion is configured, otherwise the raw unit. Both mapped to display names."""
        raw = _conv_unit.get(dm.conversion_id) if dm.conversion_id else None
        if raw is None:
            raw = dm.unit or ''
        return utils_general.find_name_unit(dict_units, raw)

    # Device-grouped channel list for 2-step sensor installer UI.
    # Format: [{input_id, name, device_type, channels: [{measurement_id, measurement, unit}]}]
    inp_order = {inp.unique_id: idx for idx, inp in enumerate(all_inputs)}
    devices_tmp = {}
    for dm in dm_rows:
        if dm.device_id not in devices_tmp:
            inp = next((i for i in all_inputs if i.unique_id == dm.device_id), None)
            if not inp:
                continue
            devices_tmp[dm.device_id] = {
                'input_id':    dm.device_id,
                'name':        inp.name or 'Input',
                'device_type': 'input',
                'channels':    [],
            }
        devices_tmp[dm.device_id]['channels'].append({
            'measurement_id': dm.unique_id,
            'measurement':    dm.measurement or '',
            'unit':           _effective_unit(dm),
        })
    input_devices = sorted(devices_tmp.values(), key=lambda d: inp_order.get(d['input_id'], 9999))

    # Function-grouped channel list (same structure as input_devices).
    all_func_objs = Function.query.order_by(Function.name.asc()).all()
    all_custom_objs = CustomController.query.order_by(CustomController.name.asc()).all()
    all_function_combined = all_func_objs + all_custom_objs
    choices_function = utils_general.choices_functions(all_function_combined, dict_units, dict_measurements)
    func_ids = [f.unique_id for f in all_function_combined]
    func_dm_rows = (DeviceMeasurements.query
                    .filter(DeviceMeasurements.device_id.in_(func_ids))
                    .order_by(DeviceMeasurements.channel.asc())
                    .all()
                    if func_ids else [])
    meas_id_slug.update({dm.unique_id: dm.measurement or '' for dm in func_dm_rows})

    # Supplement converted units for function channels
    _func_conv_ids = {dm.conversion_id for dm in func_dm_rows if dm.conversion_id} - _conv_ids
    if _func_conv_ids:
        for _cv in _Conversion.query.filter(_Conversion.unique_id.in_(_func_conv_ids)).all():
            _conv_unit[_cv.unique_id] = _cv.convert_unit_to or ''

    func_order = {f.unique_id: idx for idx, f in enumerate(all_function_combined)}
    func_devices_tmp = {}
    for dm in func_dm_rows:
        if dm.device_id not in func_devices_tmp:
            fn = next((f for f in all_function_combined if f.unique_id == dm.device_id), None)
            if not fn:
                continue
            func_devices_tmp[dm.device_id] = {
                'input_id':    dm.device_id,
                'name':        fn.name or 'Function',
                'device_type': 'function',
                'channels':    [],
            }
        if not dm.measurement and not dm.unit:
            continue
        func_devices_tmp[dm.device_id]['channels'].append({
            'measurement_id': dm.unique_id,
            'measurement':    dm.measurement or '',
            'unit':           _effective_unit(dm),
        })
    function_devices = sorted(
        [v for v in func_devices_tmp.values() if v['channels']],
        key=lambda d: func_order.get(d['input_id'], 9999)
    )

    return render_template(
        'pages/geo/geo_facility.html',
        active_page='geo_facility',
        map_configs=design_maps,
        facilities=facilities,
        geo_config=utils_geo.get_geo_config(),
        choices_input=choices_input,
        choices_function=choices_function,
        meas_id_slug=meas_id_slug,
        input_devices=input_devices,
        function_devices=function_devices,
    )


@blueprint.route('/api/geo/facility/list', methods=['GET'])
@login_required
def api_facility_list():
    """List all facilities, optionally filtered by ?geo_id=<map_uuid>."""
    from aot.aot_flask.geo import FacilityManager
    geo_id = request.args.get('geo_id')
    result, error = FacilityManager.list_facilities(geo_id=geo_id)
    if error:
        return jsonify({'ok': False, 'message': error}), 500

    # 대표 측정 지정을 함께 실어 보낸다. 지도 위 시설 칩이 이 값을 쓰는데,
    # 시설 모달(/overview)에서만 받으면 **모달을 한 번 열기 전까지** 칩이
    # 지정을 무시하고 기본 우선순위를 내건다. 목록은 지도 로드 때 한 번만
    # 부르는 자리라 여기 얹는 것이 가장 싸다.
    try:
        from aot.aot_flask.geo.site_summary import rep_key_of
        shape_ids = [f.get('shape_uuid') for f in result if f.get('shape_uuid')]
        by_shape = {}
        if shape_ids:
            for shape in GeoShape.query.filter(
                    GeoShape.unique_id.in_(shape_ids)).all():
                by_shape[shape.unique_id] = rep_key_of(shape)
        for f in result:
            f['rep_key'] = by_shape.get(f.get('shape_uuid'))
    except Exception:
        current_app.logger.warning('[facility/list] rep_key lookup failed',
                                   exc_info=True)

    return jsonify({'ok': True, 'facilities': result})


@blueprint.route('/api/geo/facility/<facility_uuid>/integration', methods=['GET'])
@login_required
def api_facility_integration(facility_uuid):
    """Unified Facility view for IEC consumers (Integrated Environment Control).

    Delegates to get_facility_integration() (facility_integration.py) so that
    the same logic is reusable by the env_coordinator profile loader (B2) without
    going through HTTP.
    """
    from aot.aot_flask.geo.facility_integration import get_facility_integration

    try:
        result, error = get_facility_integration(facility_uuid)
    except Exception as exc:
        current_app.logger.exception('api_facility_integration: unhandled error')
        return jsonify({'ok': False, 'message': str(exc)}), 500

    if error:
        status = 404 if 'not found' in error.lower() else 500
        return jsonify({'ok': False, 'message': error}), status

    return jsonify({'ok': True, **result})


@blueprint.route('/api/geo/facility/<facility_uuid>/wind', methods=['GET'])
@login_required
def api_facility_wind(facility_uuid):
    """Natural ventilation wind-pressure simulation (D1).

    Query params
    ------------
    speed  : wind speed m/s  (default 3.0)
    dir    : meteorological wind direction 0-359° (0=northerly, 90=easterly)  (default 0)
    pct    : opening aperture ratio 0-100%  (default 100)

    Response
    --------
    { ok, effective_ach, inflow_m3h, outflow_m3h,
      openings[{id, face, world_face, area_m2, cp, flow_m3h, direction, actuator_id}],
      wind_bias{actuator_id: weight},
      method, inputs }
    """
    from aot.aot_flask.geo.facility_integration import get_facility_integration
    from aot.aot_flask.geo.facility_wind import compute_natural_ventilation, wind_biased_opening

    try:
        wind_speed  = float(request.args.get('speed', 3.0))
        wind_dir    = float(request.args.get('dir',   0.0))
        opening_pct = float(request.args.get('pct',   100.0))
    except (TypeError, ValueError) as e:
        return jsonify({'ok': False, 'message': f'Invalid param: {e}'}), 400

    integ, error = get_facility_integration(facility_uuid)
    if error:
        status = 404 if 'not found' in error.lower() else 500
        return jsonify({'ok': False, 'message': error}), status

    vent_openings   = integ.get('vent_openings') or []
    capacity_meta   = integ.get('capacity_meta') or {}
    volume_m3       = float(capacity_meta.get('volume_m3') or 1.0)
    orientation_deg = float(
        ((integ.get('geometry_3d') or {}).get('orientation_deg'))
        or 0.0
    )

    result = compute_natural_ventilation(
        vent_openings   = vent_openings,
        wind_speed_ms   = wind_speed,
        wind_dir_deg    = wind_dir,
        orientation_deg = orientation_deg,
        volume_m3       = volume_m3,
        opening_pct     = opening_pct,
    )

    bias = wind_biased_opening(vent_openings, wind_dir, orientation_deg)

    return jsonify({
        'ok':            True,
        'facility_uuid': facility_uuid,
        'wind_bias':     bias,
        **result,
    })


@blueprint.route('/api/geo/facility/compute', methods=['POST'])
@login_required
def api_facility_compute():
    """Preview capacity computation for given facility spec (no DB write)."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

    data = request.get_json() or {}
    try:
        from aot.aot_flask.geo.facility_calc import compute_capacity
    except ImportError:
        return jsonify({
            'ok': False,
            'message': 'facility_calc module not available yet (P4 pending)'
        }), 501

    try:
        result = compute_capacity(data)
        return jsonify({'ok': True, 'computed': result})
    except Exception as e:
        current_app.logger.error(f"facility/compute error: {e}")
        return jsonify({'ok': False, 'message': str(e)}), 500


@blueprint.route('/api/geo/facility/<facility_uuid>', methods=['GET'])
@login_required
def api_facility_get(facility_uuid):
    """Get one facility by unique_id."""
    from aot.aot_flask.geo import FacilityManager
    result, error = FacilityManager.get_facility(facility_uuid)
    if error:
        status = 404 if 'not found' in error.lower() else 500
        return jsonify({'ok': False, 'message': error}), status
    return jsonify({'ok': True, 'facility': result})


@blueprint.route('/api/geo/facility', methods=['POST'])
@login_required
def api_facility_save():
    """Create or update a facility (atomic outer + spec + bays)."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

    from aot.aot_flask.geo import FacilityManager
    from aot.aot_flask.geo.facility_integration import invalidate_facility_integration_cache
    data = request.get_json() or {}
    result, error = FacilityManager.save_facility(data, user_id=current_user.id)
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    # Evict TTL cache so next poll gets fresh structure.
    invalidate_facility_integration_cache(result.get('unique_id') or data.get('unique_id'))
    return jsonify(result)


@blueprint.route('/api/geo/facility/<facility_uuid>/clone', methods=['POST'])
@login_required
def api_facility_clone(facility_uuid):
    """Duplicate a facility (same geometry/spec, device bindings reset to empty)."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

    from aot.aot_flask.geo import FacilityManager
    result, error = FacilityManager.clone_facility(facility_uuid, user_id=current_user.id)
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify(result)


@blueprint.route('/api/geo/facility/<facility_uuid>', methods=['DELETE'])
@login_required
def api_facility_delete(facility_uuid):
    """Delete a facility — requires confirm_name in payload (Constitution Art.5)."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

    from aot.aot_flask.geo import FacilityManager
    payload = request.get_json(silent=True) or {}
    confirm_name = payload.get('confirm_name') or request.args.get('confirm_name')

    result, error = FacilityManager.delete_facility(facility_uuid, confirm_name=confirm_name)
    if error:
        if 'not found' in error.lower():
            return jsonify({'ok': False, 'message': error}), 404
        if 'confirmation' in error.lower():
            return jsonify({'ok': False, 'message': error}), 400
        return jsonify({'ok': False, 'message': error}), 500
    return jsonify(result)


def _read_facility_runtime_snapshot(facility_uuid):
    """env_coordinator 가 사이클마다 미리 써둔 센서 스냅샷을 읽는다.

    활성 코디네이터가 stale 하지 않게 돌고 있고 runtime_json 이 있으면 그 dict
    를 반환, 아니면 None (호출자가 라이브 계산으로 폴백). DB 1행 읽기뿐 —
    InfluxDB/데몬 IPC 없음.
    """
    try:
        import time as _t
        import json as _j
        from aot.aot_flask.routes_geo_iec import (
            _find_facility_env_coordinator, _iec_stale_threshold)
        from aot.databases.models.function import FunctionRuntimeState

        fn = _find_facility_env_coordinator(facility_uuid)
        if fn is None or not fn.is_activated:
            return None
        rs = FunctionRuntimeState.query.filter_by(function_id=fn.unique_id).first()
        if not rs or not getattr(rs, 'runtime_json', None):
            return None
        # 코디네이터가 stale 하면(주기*3 초과 무사이클) 스냅샷도 너무 오래된
        # 것으로 보고 폴백 — env_summary 와 동일한 생존 판정.
        if rs.last_cycle_ts and (_t.time() - rs.last_cycle_ts) > _iec_stale_threshold(fn):
            return None
        snap = _j.loads(rs.runtime_json)
        return snap if isinstance(snap, dict) else None
    except Exception:
        return None


# ── Non-blocking sensor-snapshot cache for /runtime ─────────────────────────
# When no env_coordinator snapshot exists, the live per-sensor InfluxDB build
# (build_sensor_snapshot) costs ~1 query/sensor (~0.7s for a 10-sensor
# facility). On the /runtime request path that delays the map's actuator
# summary — the LCP element, which only needs the fast actuator_states, NOT the
# sensors. To keep /runtime fast without activating the coordinator, serve the
# last cached snapshot immediately and refresh it in a daemon thread; the
# summary paints at once and sensor labels fill in on a later poll (~1 cycle).
_SENSOR_SNAP_CACHE = {}         # facility_uuid -> {'snap': dict, 'ts': float}
_SENSOR_SNAP_INFLIGHT = set()   # facility_uuids with a refresh running
_SENSOR_SNAP_LOCK = threading.Lock()
_SENSOR_SNAP_TTL = 20.0         # seconds a cached snapshot stays "fresh"
_EMPTY_SENSOR_SNAP = {
    'indoor': None, 'outdoor': None,
    # degraded=False: a cold cache means "sensors still loading", not
    # "registered sensors unavailable" — avoid a false degraded indicator on
    # first paint. Real degraded state arrives with the background-built snapshot.
    'sensors': {'detail': [], 'valid_count': 0, 'total_count': 0, 'degraded': False},
    'fitting_sensors': [],
}


def _get_or_refresh_sensor_snapshot(facility_uuid, sensors_resolved, sensors_outdoor):
    """Return a cached sensor snapshot immediately; refresh in the background.

    Never blocks the request on the live InfluxDB computation. Cold cache → an
    empty/degraded snapshot now + a background build; warm cache → the cached
    (possibly stale) snapshot now + a background refresh once past the TTL.
    """
    now = time.time()
    with _SENSOR_SNAP_LOCK:
        entry = _SENSOR_SNAP_CACHE.get(facility_uuid)
        fresh = bool(entry) and (now - entry['ts']) < _SENSOR_SNAP_TTL
        need_refresh = (not fresh) and (facility_uuid not in _SENSOR_SNAP_INFLIGHT)
        if need_refresh:
            _SENSOR_SNAP_INFLIGHT.add(facility_uuid)

    if need_refresh:
        app = current_app._get_current_object()

        def _bg_build():
            snap = None
            try:
                from aot.aot_flask.geo.facility_sensors import build_sensor_snapshot as _bss
                with app.app_context():
                    snap = _bss(sensors_resolved, sensors_outdoor)
            except Exception:
                snap = None
            with _SENSOR_SNAP_LOCK:
                if isinstance(snap, dict):
                    _SENSOR_SNAP_CACHE[facility_uuid] = {'snap': snap, 'ts': time.time()}
                _SENSOR_SNAP_INFLIGHT.discard(facility_uuid)

        threading.Thread(
            target=_bg_build,
            name='facility_snap_%s' % (facility_uuid or '')[:8],
            daemon=True).start()

    with _SENSOR_SNAP_LOCK:
        entry = _SENSOR_SNAP_CACHE.get(facility_uuid)
    return entry['snap'] if entry else _EMPTY_SENSOR_SNAP


def _facility_plots_block(facility_uuid):
    """시설에서 자라는 구획 요약 — 실패해도 런타임 응답을 막지 않는다.

    폴링 응답이라 여기서 예외가 나면 3D 위젯 전체가 멈춘다. 식생은 **부가
    정보**이므로 조용히 비운다(빈 목록은 "심은 것이 없다" 와 같은 화면이고,
    그 차이는 로그로 남긴다).
    """
    try:
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoFacility
        # **화면 목록이라 계획까지 낸다.** 몫(베드)을 함께 세야 "5베드 남음"
        # 이 거짓말이 되지 않는다 — 9월에 2베드를 쓰기로 해 둔 것을 빼고 세면
        # 그 자리에 또 배정할 수 있고, 그날이 오면 조용히 초과된다.
        # 제어 경로(`routes_geo_iec`·코디네이터)는 기본값 그대로 활성만 본다.
        rows = plot_context.plots_in_facility(facility_uuid, include_planned=True)
        # 구역 총량은 시설 하나당 **한 번만** 읽어 넘긴다 — 구획마다 다시 읽으면
        # 폴링 응답 하나에 N+1 이 된다.
        fac = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
        caps = plot_context.bay_capacities(fac) if fac is not None else {}
        return [plot_context.plot_brief_for_control(r, capacities=caps)
                for r in rows]
    except Exception as exc:
        current_app.logger.warning(
            '[Facility] 구획 요약 실패(%s) — 런타임은 계속: %s',
            facility_uuid, exc)
        return []


def _facility_bay_capacities(facility_uuid):
    """구역 총량 — 실패해도 런타임 응답을 막지 않는다(구획 요약과 같은 규칙)."""
    try:
        from aot.aot_flask.geo import plot_context
        from aot.databases.models import GeoFacility
        fac = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
        return plot_context.bay_capacities(fac) if fac is not None else {}
    except Exception as exc:
        current_app.logger.warning(
            '[Facility] 구역 총량 읽기 실패(%s) — 런타임은 계속: %s',
            facility_uuid, exc)
        return {}


@blueprint.route('/api/aot/facility/<facility_uuid>/runtime', methods=['GET'])
@login_required
def api_facility_runtime(facility_uuid):
    """Real-time runtime snapshot for the 3D facility widget.

    Returns:
        actuator_states : live on/off+percent via DaemonControl.output_states_all()
        indoor          : weighted average from facility.sensors (role=indoor_*)
        outdoor         : facility.sensors (role=outdoor_*) → fallback to
                          ext_context_collector shared context
        sensors         : per-sensor detail list (valid/stale/degraded_reason)
        degraded        : True if any registered sensor is unavailable
    """
    import time as _time
    from aot.databases.models import GeoFacility, Output, OutputChannel
    from aot.aot_client import DaemonControl
    from aot.aot_flask.geo.facility_sensors import read_facility_sensors, compute_spatial_internal, read_fitting_sensors, build_sensor_snapshot
    from aot.aot_flask.geo.facility_integration import get_facility_integration
    from aot.utils.outputs import parse_output_information, get_pwm_invert_signal

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    # ── Live output states via daemon ─────────────────────────────────────────
    try:
        _dc = DaemonControl()
        all_states = _dc.output_states_all() or {}
    except Exception:
        _dc = None
        all_states = {}

    _RUN_CACHE_TTL = 120.0     # 초. 마지막 작동은 초 단위로 바뀌지 않는다.
    _run_cache = getattr(api_facility_runtime, '_run_cache', None)
    if _run_cache is None:
        _run_cache = {}
        api_facility_runtime._run_cache = _run_cache

    _DUTY_BASELINE_DAYS = 7    # 비교 대상. 한 주면 요일 주기(주말 관수 등)를 담는다.

    def _history_cached(uuid, want_duty):
        """{'last_run_at', 'duty_24h_s', 'duty_avg_s'} — 프로세스 캐시.

        **on/off 장치의 "얼마나" 는 시간축에만 있다.** 지금 켜졌다/꺼졌다는 0
        아니면 100 이라, 그것을 출력 %로 그리면 비례 장치의 개도와 같은 모양이
        되어 "절반쯤 돌고 있다" 같은 없는 뜻이 생긴다.

        ⚠ 그런데 **"24시간 중 0.6시간" 도 그 자체로는 아무 말을 하지 않는다.**
          난방기의 하루 0.6시간은 여름이면 흔한 일이고 겨울이면 고장 신호다.
          24시간은 비교 기준이 아니라 그냥 하루의 길이다(2026-08-26 지적).
          기준은 **그 장치 자신의 최근 실적**이어야 한다 —

              평소(최근 7일 일평균)  ·  가장 많이 돈 날(그 기간 최대)

          그래야 "평소보다 덜 돈다" 를 화면이 말할 수 있다.

        ⚠ 오늘(진행 중인 날)은 **평균·최대에서 뺀다.** 아직 안 끝난 하루를
          지난 날들과 같은 무게로 섞으면 기준이 아침마다 낮아진다 — 그러면
          "평소보다 많다" 가 오후에 저절로 참이 된다.

        ⚠ 비례 장치(개도·PWM)에는 계산하지 않는다. 그쪽은 지금 개도가 이미
          "얼마나" 이고, 여기서까지 이력을 캐면 조회만 늘어난다.

        한 캐시 항목에 함께 담는다. 따로 두면 TTL 이 어긋나 같은 줄의 값과
        기준이 서로 다른 시점을 가리킨다.
        """
        now = _time.time()
        hit = _run_cache.get(uuid)
        if hit and (now - hit[0]) < _RUN_CACHE_TTL and (hit[1].get('duty_24h_s')
                                                        is not None
                                                        or not want_duty):
            return hit[1]
        rec = {'last_run_at': None, 'duty_24h_s': None, 'duty_avg_s': None}
        try:
            from aot.utils import runtime as _rt
            rec['last_run_at'] = _rt.get_started_at(uuid, 0, lookback_days=30)
            if want_duty:
                rec['duty_24h_s'] = _rt.get_operational_seconds(uuid, 86400, 0)
                # 오늘까지 포함해 받고 **마지막 버킷(진행 중인 하루)을 버린다.**
                daily = _rt.get_daily_operational_seconds(
                    uuid, _DUTY_BASELINE_DAYS + 1, 0)
                past = daily[:-1] if daily else []
                # 하루치로는 "평소" 라고 부를 수 없다. 근거가 없으면 기준을
                # 만들지 않는다 — 화면은 기준 없이 시간만 적는다.
                if len(past) >= 2:
                    rec['duty_avg_s'] = sum(past) / len(past)
        except Exception:
            pass
        _run_cache[uuid] = (now, rec)
        return rec

    def _get_target_pct(uuid):
        """Return actuator_paired's (last_target_pct, last_target_source). (None, None) if absent.

        Fetches the last specified target (regardless of user/system) and its source for display.
        """
        try:
            if _dc:
                result = _dc.output_target_pct(uuid, 0)
                if isinstance(result, tuple) and len(result) == 2:
                    val, src = result
                    return (float(val) if val is not None else None, src)
        except Exception:
            pass
        return None, None

    # ── Actuator resolution ───────────────────────────────────────────────────
    # Actuators come exclusively from facility configuration (slot_map + fittings.actuator_id).
    # If a single Output controls multiple fittings, actuators_resolved is already
    # grouped by output_uuid, so no extra handling is needed. The display name aggregates fitting names.
    try:
        dict_outputs = parse_output_information()
    except Exception:
        dict_outputs = {}

    def _resolve_control_type(output_type_key):
        """Determine the control UI from the module's OUTPUT_INFORMATION['output_types'] array.
            'value' → 'value'  (Actuator Paired position slider)
            'pwm'   → 'pwm'    (PWM slider)
            else    → 'binary' (ON/OFF toggle)
        """
        ot_list = (dict_outputs.get(output_type_key, {}) or {}).get('output_types') or []
        if 'value' in ot_list:
            return 'value'
        if 'pwm' in ot_list:
            return 'pwm'
        return 'binary'

    integ = None
    actuator_states = {}

    try:
        integ, integ_err = get_facility_integration(facility_uuid)
        if integ and not integ_err:
            # fitting_id → fitting name lookup (for displaying the control target)
            fitting_name_lookup = {}
            for f in (integ.get('fittings') or []):
                fid = f.get('id')
                if fid and f.get('name'):
                    fitting_name_lookup[fid] = f['name']

            for act in (integ.get('actuators_resolved') or []):
                uuid     = act.get('output_uuid') or ''
                slot_key = act.get('slot_key') or uuid
                kind     = act.get('kind') or ''
                if not uuid:
                    continue
                # If kind is still a raw actuator_paired kind value, map it to profile kind.
                if kind not in ('opening', 'curtain', 'shade', 'exhaust_fan',
                                'intake_fan', 'lighting',
                                'heater', 'cooler', 'fogger',
                                'co2_injector', 'circulation_fan'):
                    try:
                        from aot.outputs.paired_actuator_common import KIND_TO_PROFILE_KIND as _PKM
                        kind = _PKM.get(kind, kind)
                    except ImportError:
                        pass

                ch_states = all_states.get(uuid, {})
                raw_state = ch_states.get(0) if isinstance(ch_states, dict) else None
                on_val = raw_state not in (None, 'off', False, 0)
                pct    = float(raw_state) if isinstance(raw_state, (int, float)) and raw_state not in (False,) else None

                # Use the actuator name (fixed to output_name instead of fitting names)
                label = act.get('output_name') or slot_key

                ctrl_type   = _resolve_control_type(act.get('output_type') or '')

                # PWM 채널의 'Invert Signal' 옵션은 물리 신호만 반전한다(pwm_gpio.py
                # output_switch) — daemon 의 실시간 상태(all_states, 위 raw_state)는
                # 그 반전된 물리 duty 를 그대로 담고 있으므로, 지도에 보여줄 때는
                # 되돌려야 사용자가 요청한 값과 일치한다.
                if ctrl_type == 'pwm' and pct is not None and get_pwm_invert_signal(uuid, 0):
                    pct = 100.0 - abs(pct)

                last_pct, last_src = _get_target_pct(uuid) if ctrl_type == 'value' else (None, None)
                # ── 마지막 작동 시각 (2026-08-26) ──────────────────────────
                # 예전에는 `last_irrigation` 만 있어서 **관수 계열 한 대만**
                # "마지막 작동" 이 보였다 — 같은 목록의 다른 장치는 그 칸이
                # 비어 있어, 사용자는 "왜 이것만 나오나" 를 묻게 됐다.
                # 쉬고 있는 장치일수록 그 값이 필요하다(지금 0% 인 것이 방금
                # 껐기 때문인지 며칠째 안 돈 것인지가 갈린다).
                #
                # ⚠ 조회는 **한 번만** 하고 캐시한다. 이 응답은 주기 폴링을
                # 받으므로 장치 수만큼 InfluxDB 를 매번 때리면 폴링 비용이
                # 장치 수에 비례해 커진다. 마지막 작동은 초 단위로 바뀌는 값이
                # 아니라 캐시가 값의 뜻을 해치지 않는다.
                _hist = _history_cached(uuid, ctrl_type == 'binary')
                actuator_states[slot_key] = {
                    'last_run_at':        _hist['last_run_at'],
                    # on/off 장치만. 비례 장치는 지금 개도가 곧 "얼마나" 다.
                    # 기준(평소·최대)이 없으면 None — 화면이 없는 기준을
                    # 지어내지 않도록 24시간 같은 임의의 축을 주지 않는다.
                    'duty_24h_s':         _hist['duty_24h_s'],
                    'duty_avg_s':         _hist['duty_avg_s'],
                    'output_uuid':        uuid,
                    'name':               label,
                    'on':                 on_val,
                    'percent':            pct,
                    'last_target_pct':    last_pct,
                    'last_target_source': last_src,
                    'kind':               kind,
                    'output_type':        act.get('output_type') or '',
                    'control_type':       ctrl_type,
                    # 구역(bay) 귀속 — fitting 위치 기반. [] = 시설 공통.
                    'bay_ids':            act.get('bay_ids') or [],
                }
    except Exception:
        pass

    # ── Sensor data ───────────────────────────────────────────────────────────
    # env_coordinator 가 사이클마다 미리 계산해둔 스냅샷(FunctionRuntimeState.
    # runtime_json)을 우선 읽는다. 센서당 InfluxDB 조회(compute_spatial_internal
    # + read_fitting_sensors)가 /runtime 비용의 대부분이라, 이를 요청 경로에서
    # 제거하면 저사양 호스트의 스레드 풀 포화가 근본적으로 완화된다.
    # 코디네이터가 없거나 stale 이면 라이브로 계산(폴백) — 동작은 종전과 동일.
    sensors_resolved = (integ.get('sensors_resolved') or []) if integ else []
    sensors_outdoor  = (integ.get('sensors_outdoor') or []) if integ else []

    _snap = _read_facility_runtime_snapshot(facility_uuid)
    if not (isinstance(_snap, dict) and 'fitting_sensors' in _snap):
        # No coordinator snapshot → serve cached (or empty) sensors immediately
        # and refresh in the background, so /runtime never blocks on the live
        # per-sensor InfluxDB build. The actuator summary (LCP element) stays
        # fast; sensor labels fill in on a subsequent poll. See
        # _get_or_refresh_sensor_snapshot.
        _snap = _get_or_refresh_sensor_snapshot(
            facility_uuid, sensors_resolved, sensors_outdoor)

    indoor          = _snap.get('indoor')  or {'temp_c': None, 'humidity_pct': None, 'co2_ppm': None, 'vpd_kpa': None}
    outdoor         = _snap.get('outdoor') or {'temp_c': None, 'humidity_pct': None, 'wind_ms': None, 'wind_deg': None, 'solar_wm2': None}
    sensors_block   = _snap.get('sensors') or {'detail': [], 'valid_count': 0, 'total_count': 0, 'degraded': False}
    fitting_sensors = _snap.get('fitting_sensors') or []

    # User-specified actuator display order (view_options.actuator_order, flat slot_key list).
    # If absent, an empty list → the front end displays in natural sort order (text→number).
    try:
        actuator_order = (facility.view_options or {}).get('actuator_order') or []
    except Exception:
        actuator_order = []

    runtime = {
        'ok': True,
        'facility_uuid':  facility_uuid,
        'actuator_states': actuator_states,
        'actuator_order': actuator_order,
        'indoor':  indoor,
        'outdoor': outdoor,
        'sensors': sensors_block,
        'fitting_sensors': fitting_sensors,
        # bay(구역) 슬라이스 — 2개 이상일 때만 비어있지 않음. 지도 위젯의
        # 구역 칩/모달이 fitting_sensors.bay_id / actuator_states.bay_ids 와
        # 조합해 구역별 뷰를 구성한다.
        'bays': (integ.get('bays') or []) if integ else [],
        # 지금 이 시설에서 자라는 것 — **제어 → 식생** 방향이다.
        #
        # 설정값을 보는 화면이 "무엇이 며칠째 자라고 있나" 를 함께 말할 수
        # 있어야 그 값의 근거가 생긴다. 이것이 없으면 식생은 기록으로만 남고
        # 제어와 만나지 않는다(그 반대 방향은 구획 모달의 [환경·제어]).
        #
        # 면적·치수는 싣지 않는다 — 시설에서는 낼 수 없는 값이다. 구역 없는
        # 구획(bay_id=None)은 시설 전체에 심은 것이라 어느 구역 뷰에서도 보여야
        # 한다(`plots_in_facility` 가 그렇게 낸다).
        'plots': _facility_plots_block(facility_uuid),
        # 구역 총량(p6_50) — 구획의 몫이 이것을 분모로 삼는다. 화면이 "4/12 베드"
        # 를 그리려면 분모가 목록과 **같은 응답**에 있어야 한다(따로 조회하면
        # 둘이 어긋난 순간이 생긴다).
        'bay_capacities': _facility_bay_capacities(facility_uuid),
        # 설계 화면(geo/facility·geo/programs)에 갈 수 있는가. 구획 폼의
        # "여기서 설정합니다" 링크를 보일지 정한다 — 권한 없는 사람에게 보이면
        # 눌러도 리다이렉트만 되고 무엇이 잘못됐는지 알 수 없다.
        'can_design': utils_general.user_has_permission(
            'edit_settings', silent=True),
        # 구획 카드(추가·몫·총량)를 열 권한. 대표 센서 선택 같은 **시설 설정**과
        # 다른 축이라 따로 내린다 — 하나로 묶으면 작기만 맡는 사람에게 시설
        # 설정이 열리거나, 반대로 구획을 못 만들게 된다.
        'can_edit_plots': utils_general.user_has_permission(
            'edit_plots', silent=True),
    }
    # 시설 1개당 분당 3회 안팎으로 폴링되고, 액추에이터 상태·센서값이 안 바뀌면
    # 응답 바이트가 그대로다(실측 815 B, 3회 연속 해시 동일). 조건부 응답으로
    # 안 바뀐 주기의 회선·파싱을 없앤다.
    return utils_http.json_conditional(jsonify(runtime), request)


@blueprint.route('/api/aot/facility/<facility_uuid>/actuator_order', methods=['POST'])
@login_required
def api_facility_actuator_order(facility_uuid):
    """Persist a user-defined actuator/device display order for one facility.

    Body: { order: [slot_key, ...] }

    Storage location is GeoFacility.view_options.actuator_order — kept in the UI
    display-options JSON as a flat slot_key list (no schema change required). All
    device-control lists for the same facility (map popup/panel/grid, etc.) share this order.
    """
    from sqlalchemy.orm.attributes import flag_modified
    from aot.databases.models import GeoFacility

    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Insufficient permission'}), 403

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    body  = request.get_json(silent=True) or {}
    order = body.get('order')
    if not isinstance(order, list):
        return jsonify({'ok': False, 'message': 'order must be a list'}), 400

    # Allow only slot keys (strings) + deduplicate while preserving order.
    seen = set()
    clean = []
    for sk in order:
        sk = str(sk).strip()
        if sk and sk not in seen:
            seen.add(sk)
            clean.append(sk)

    vo = dict(facility.view_options or {})
    vo['actuator_order'] = clean
    facility.view_options = vo
    flag_modified(facility, 'view_options')   # force-detect JSON column change
    facility.updated_at = datetime.utcnow()

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("[actuator_order] save failed")
        return jsonify({'ok': False, 'message': str(e)}), 500

    return jsonify({'ok': True, 'order': clean})


@blueprint.route('/api/aot/facility/<facility_uuid>/bays', methods=['GET'])
@login_required
def api_facility_bays(facility_uuid):
    """시설의 구역 목록 → `{ok, bays:[{id, name}]}` (읽기 전용).

    통합환경제어의 `bay_scope` 드롭다운이 쓴다. `/runtime` 에도 같은 목록이
    있지만 그쪽은 센서 스냅샷·액추에이터 상태까지 만드는 무거운 응답이라,
    설정 화면이 선택지 몇 개를 채우려고 부를 것이 아니다.

    ⚠ 이름은 **보여 주기용**이고 저장되는 값은 `id` 다. 사용자가 구역 이름을
      바꿔도 이미 저장된 코디네이터가 계속 같은 구역을 가리킨다.
    """
    from aot.databases.models import GeoFacility
    from aot.aot_flask.geo.facility_bays import compute_bay_slices
    # ⚠ `spec_from_row` 가 이 용도의 정본이다 — 구역 유효성 검사
    #   (`facility_io` 의 bay_id 검증)가 쓰는 것과 **같은 입력**이어야 화면의
    #   선택지와 서버의 판정이 갈리지 않는다.
    from aot.aot_flask.geo.facility_bays import spec_from_row

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404
    try:
        slices = compute_bay_slices(spec_from_row(facility)) or []
    except Exception as exc:                                    # noqa: BLE001
        return jsonify({'ok': False, 'message': str(exc)}), 500
    return jsonify({'ok': True, 'bays': [
        {'id': s.get('id'), 'name': s.get('name') or s.get('id')}
        for s in slices if s.get('id')]})


@blueprint.route('/api/aot/facility/<facility_uuid>/bay_capacity', methods=['POST'])
@login_required
def api_facility_bay_capacity(facility_uuid):
    """구역 총량을 적는다 (p6_50) — `{bay_id, unit, total}`.

    구획의 몫(`geo_plot.allocation.amount`)이 이 값을 분모로 삼는다. "12베드 중
    4베드" 의 12 가 여기서 온다.

    **총량은 시설의 사실이고 구획은 참조만 한다.** 구획 저장이 이 값을 고칠 수
    있으면 마지막에 저장한 구획이 분모를 정하게 되므로, 쓰는 자리를 시설 쪽에
    따로 둔다.

    `total` 을 0 이하나 빈 값으로 주면 총량을 **지운다** — 잘못 적은 것을 되돌릴
    수단이 없으면 사람은 아무 숫자나 넣어 두고 만다. 그때 그 구역의 구획들은
    비율(percent) 축으로 되돌아간다(값 자체는 지우지 않는다 — 총량을 다시 적으면
    그대로 되살아난다).
    """
    from sqlalchemy.orm.attributes import flag_modified
    from aot.databases.models import GeoFacility
    from aot.aot_flask.geo.plot_context import _CAPACITY_UNITS

    # 총량은 시설의 사실이지만 **작기마다 달라지는 운영 값**이다(같은 온실을
    # 이번 작기에는 8베드로 쓸 수 있다). 그래서 설계 권한이 아니라 작기 운영
    # 권한으로 연다 — 설계 화면에 못 가는 사람이 실제로 이 값을 쓴다.
    if not utils_general.user_has_permission('edit_plots'):
        return jsonify({'ok': False, 'message': 'Insufficient permission'}), 403

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    body = request.get_json(silent=True) or {}
    bay_id = str(body.get('bay_id') or '').strip()
    if not bay_id:
        return jsonify({'ok': False, 'message': 'bay_id required'}), 400

    raw_total = body.get('total')
    total = None
    if raw_total not in (None, ''):
        try:
            total = float(raw_total)
        except (TypeError, ValueError):
            return jsonify({'ok': False,
                            'message': '총량은 숫자여야 합니다'}), 400
        if total <= 0:
            total = None                       # 0 이하 = 지우기
        elif float(total).is_integer():
            total = int(total)
        else:
            total = round(total, 2)

    unit = body.get('unit')
    if unit not in _CAPACITY_UNITS:
        unit = 'bed'

    bays = facility.bays if isinstance(facility.bays, list) else []
    target = None
    for b in bays:
        if isinstance(b, dict) and b.get('id') == bay_id:
            target = b
            break
    if target is None:
        return jsonify({'ok': False,
                        'message': "구역 '%s' 가 시설에 없습니다" % bay_id}), 400

    if total is None:
        target.pop('capacity', None)
    else:
        target['capacity'] = {'unit': unit, 'total': total}

    facility.bays = bays
    flag_modified(facility, 'bays')     # JSON 컬럼 변경 감지
    facility.updated_at = datetime.utcnow()
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('[bay_capacity] save failed')
        return jsonify({'ok': False, 'message': str(e)}), 500

    return jsonify({'ok': True, 'bay_id': bay_id,
                    'capacity': target.get('capacity')})


@blueprint.route('/api/aot/facility/<facility_uuid>/calibration_status', methods=['GET'])
@login_required
def api_calibration_status(facility_uuid):
    """Return the CalibrationRegistry learning state for every actuator linked
    to env_coordinator functions that have this facility configured.

    Response schema:
        {
          "ok": true,
          "function_id": "<uuid>",
          "actuators": [
            {
              "actuator_id": "<uuid>",
              "kind": "heater",
              "vars": {
                "temperature": {
                  "k_hat": 0.85,        # 효과 배율 θ(무차원, 1.0 = 모델 그대로)
                  "n_updates": 18,
                  "P": 0.08,
                  "trusted": true
                }
              }
            },
            ...
          ],
          "greybox_kpi": {
            "passed": true,
            "mae_T": 1.1,
            "mae_RH": 5.2,
            "ts": 1716000000.0
          },
          "commissioning_state": { ... }
        }

    Reads directly from FunctionRuntimeState (calibration_state_json) — no
    daemon RPC needed so it works even when the function is stopped.
    """
    import json as _json
    from aot.databases.models import GeoFacility, FunctionRuntimeState
    from aot.databases.models import CustomController

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    # Find env_coordinator function(s) linked to this facility.
    # CustomController identifies type by the `device` column (NOT function_type;
    # function_type is on the separate `function` table). The facility uuid is
    # stored in custom_options as geo_facility_id_device_id.
    try:
        funcs = CustomController.query.filter_by(device='env_coordinator').all()
    except Exception:
        funcs = []

    matched_func = None
    for f in funcs:
        try:
            opts = _json.loads(f.custom_options or '{}')
            if opts.get('geo_facility_id_device_id') == facility_uuid:
                matched_func = f
                break
        except Exception:
            continue

    if matched_func is None:
        return jsonify({
            'ok': True,
            'function_id': None,
            'actuators': [],
            'greybox_kpi': None,
            'commissioning_state': facility.commissioning_state or {},
            'message': 'No env_coordinator linked to this facility',
        })

    # Load runtime state from DB
    row = FunctionRuntimeState.query.filter_by(
        function_id=matched_func.unique_id).first()

    actuators_out = []
    greybox_kpi   = None

    if row and row.calibration_state_json:
        try:
            cal_state = _json.loads(row.calibration_state_json)
        except Exception:
            cal_state = {}

        # Extract greybox KPI meta (stored at top level of cal_state)
        if cal_state.get('greybox_kpi_passed'):
            greybox_kpi = {
                'passed': True,
                'mae_T':  cal_state.get('greybox_kpi_mae_T'),
                'mae_RH': cal_state.get('greybox_kpi_mae_RH'),
                'ts':     cal_state.get('greybox_kpi_ts'),
            }

        # Per-actuator RLS learning state
        cals = cal_state.get('cals', {})
        for aid, cal_entry in cals.items():
            kind = cal_entry.get('kind', '')
            rls_dict = cal_entry.get('rls', {})
            vars_out = {}
            for var, rls_entry in rls_dict.items():
                k_hat     = rls_entry.get('k_hat', 0.0)
                n_updates = rls_entry.get('n_updates', 0)
                p_val     = rls_entry.get('P', 1.0)
                vars_out[var] = {
                    'k_hat':     round(float(k_hat), 5),
                    'n_updates': int(n_updates),
                    'P':         round(float(p_val), 5),
                    'trusted':   int(n_updates) >= 5,
                }
            actuators_out.append({
                'actuator_id': aid,
                'kind':        kind,
                'vars':        vars_out,
            })

    return jsonify({
        'ok':                  True,
        'function_id':         matched_func.unique_id,
        'actuators':           actuators_out,
        'greybox_kpi':         greybox_kpi,
        'commissioning_state': facility.commissioning_state or {},
    })


@blueprint.route('/api/geo/facility/<facility_uuid>/apply', methods=['POST'])
@login_required
def api_facility_apply(facility_uuid):
    """AI recommendation approval — immediately deliver structured commands to mapped outputs.

    Request body:
        {
            "horizon": "now" | "1h" | "6h",
            "commands": [
                {"kind": "side_window_motor", "action": "off"},
                {"kind": "thermal_curtain_motor", "action": "on"},
                {"kind": "side_window_motor", "action": "set", "pct": 30}
            ]
        }

    command.action:
        "off"  → output_off (channel 0)
        "on"   → output_on (duration=0, stays on)
        "set"  → output_on(output_type='value', amount=pct)

    kind mapping: collect the device_uuid of items whose kind matches in the
    facility.actuators array. Legacy (dict) actuators are also handled via key-prefix matching.

    VEE (VirtualExecutionEngine): pre-flight conflict check on MEDIUM/HIGH hardware profiles.
    VEE is advisory-only — execution proceeds even when a conflict is detected, and the result is included in the response.

    Returns:
        {"ok": True, "applied": N, "failed": [...], "horizon": "...",
         "simulation": {"conflict_flags": [...], "confidence_score": 0.8, "advisory_only": True}}
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission denied'}), 403

    # 그룹 스코프(A1a) — 시설 단위로 묻는다. 시설 제어는 그 안의 액추에이터
    # 여럿을 한 번에 움직이므로 장치마다 묻는 것보다 시설 자체가 맞는 단위다.
    # (설계 §8-3 — 시설은 지도에서 상속받지 않고 따로 부여한다.)
    if not scope.can_operate('geo_facility', facility_uuid):
        return jsonify({'ok': False, 'message': scope.deny_message()}), 403

    from aot.databases.models import GeoFacility
    from aot.aot_client import DaemonControl

    facility = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    if not facility:
        return jsonify({'ok': False, 'message': 'Facility not found'}), 404

    body = request.get_json(silent=True) or {}
    horizon  = body.get('horizon', 'now')
    commands = body.get('commands') or []

    if not commands:
        return jsonify({'ok': False, 'message': _('No commands')}), 400

    # ── VEE pre-flight conflict check (advisory-only, MEDIUM/HIGH profiles) ─────────────
    simulation_result = None
    try:
        from aot.config.feature_flags import capability_manager
        if capability_manager.is_enabled('VEE'):
            from aot.ai.services.virtual_execution_engine import (
                VirtualExecutionEngine, SimulationRequest, URGENCY_NORMAL, URGENCY_CRITICAL)
            from aot.functions.ext_context_collector import (
                get_shared_context, get_shared_context_ts)
            import time as _time

            ext = get_shared_context() or {}
            ext_age = _time.time() - get_shared_context_ts()
            weather = {}
            if ext and ext_age < 600:
                weather = {
                    'temperature_c':  ext.get('T_ext'),
                    'wind_speed_ms':  ext.get('wind'),
                }

            urgency = URGENCY_CRITICAL if horizon == 'now' else URGENCY_NORMAL
            kinds = [c.get('kind', '') for c in commands]
            sim_req = SimulationRequest(
                action_payload={
                    'action_type':  'facility_apply',
                    'tool_name':    'facility_apply',
                    'target_id':    facility_uuid,
                    'kinds':        kinds,
                    'horizon':      horizon,
                },
                spatial_snapshot={},
                weather_forecast=weather,
                simulation_horizon_minutes=60 if horizon == '1h' else (360 if horizon == '6h' else 5),
                urgency_level=urgency,
            )
            vee_result = VirtualExecutionEngine().simulate(sim_req)
            simulation_result = {
                'conflict_flags':   vee_result.conflict_flags,
                'confidence_score': vee_result.confidence_score,
                'proceed_recommended': vee_result.proceed_recommended,
                'advisory_only':    True,
            }
    except Exception:
        pass  # VEE failure never blocks execution

    # ── actuators → device_uuid index by kind ──────────────────────────────
    actuators_raw = facility.actuators or {}
    kind_to_uuids: dict = {}

    if isinstance(actuators_raw, list):
        # New array format: [{kind, device_uuid, ...}]
        for act in actuators_raw:
            k = act.get('kind') or ''
            u = act.get('device_uuid') or ''
            if k and u:
                kind_to_uuids.setdefault(k, []).append(u)
    else:
        # Legacy dictionary format: {slot_key: device_uuid}
        _KIND_ALIAS = {
            'side_window_motor':     ['outer_side_vent_motor', 'inner_side_vent_motor', 'side_vent_motor'],
            'roof_vent_motor':       ['outer_roof_vent_motor', 'inner_roof_vent_motor', 'roof_vent_motor'],
            'thermal_curtain_motor': ['thermal_curtain', 'thermal_curtain_motor'],
            'shade_curtain_motor':   ['shade_curtain', 'shade_curtain_motor'],
            'exhaust_fan':           ['exhaust_fan'],
            'circulation_fan':       ['circulation_fan'],
            'heater':                ['heater'],
            'cooler':                ['cooler'],
        }
        for slot_key, uuid in actuators_raw.items():
            if not uuid:
                continue
            for kind, aliases in _KIND_ALIAS.items():
                if any(slot_key == alias or slot_key.startswith(alias) for alias in aliases):
                    kind_to_uuids.setdefault(kind, []).append(uuid)

    # ── Execute commands ────────────────────────────────────────────────────────
    # 'set' (pct) is converted to the output_type the device actually supports before dispatch.
    # (If output_type='value' is sent to every device, base_output ignores the command on a
    #  type mismatch, so % control on PWM/on-off relays is reduced to simple on/off.)
    from aot.utils.outputs import parse_output_information
    from aot.databases.models import Output as _Output
    try:
        _out_info = parse_output_information()
    except Exception:
        _out_info = {}

    def _dispatch_set(control, uuid, pct):
        """Dispatch a % command using the output_type appropriate for the device module type."""
        row = _Output.query.filter_by(unique_id=uuid).first()
        module_name = row.output_type if row else ''
        types_list = (_out_info.get(module_name, {}) or {}).get('output_types') or []
        if 'value' in types_list:
            control.output_on(uuid, output_type='value', amount=pct,
                              additional_options={'source': 'system'})
        elif 'pwm' in types_list:
            if pct > 0.0:
                control.output_on(uuid, output_type='pwm', amount=pct)
            else:
                control.output_off(uuid)
        elif 'on_off' in types_list:
            if pct >= 5.0:
                control.output_on(uuid, output_type='sec',
                                  amount=max(1.0, 60.0 * pct / 100.0))
            else:
                control.output_off(uuid)
        else:
            control.output_on(uuid, output_type='value', amount=pct)

    control = DaemonControl()
    applied = 0
    failed  = []

    for cmd in commands:
        kind   = cmd.get('kind', '')
        action = cmd.get('action', 'off')
        pct    = float(cmd.get('pct', 0) or 0)
        uuids  = kind_to_uuids.get(kind, [])

        if not uuids:
            failed.append({'kind': kind, 'reason': _('No mapped output')})
            continue

        for uuid in uuids:
            try:
                if action == 'off':
                    control.output_off(uuid)
                elif action == 'on':
                    control.output_on(uuid, output_type='sec', amount=0)
                elif action == 'set':
                    _dispatch_set(control, uuid, pct)
                else:
                    failed.append({'kind': kind, 'uuid': uuid, 'reason': _('Unknown action: %(action)s', action=action)})
                    continue
                applied += 1
            except Exception as exc:
                failed.append({'kind': kind, 'uuid': uuid, 'reason': str(exc)})

    resp = {
        'ok':      len(failed) == 0,
        'applied': applied,
        'failed':  failed,
        'horizon': horizon,
        'facility_uuid': facility_uuid,
    }
    if simulation_result is not None:
        resp['simulation'] = simulation_result
    return jsonify(resp)
