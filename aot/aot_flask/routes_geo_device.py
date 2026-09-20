# coding=utf-8
"""routes_geo 의 출력 상태/이력/runtime·link_status·devices 라우트. blueprint 는 routes_geo 것을 공유한다."""
from flask import current_app, request, jsonify
from flask_login import login_required
from aot.aot_flask.utils import utils_general
from aot.aot_flask.utils import utils_http
from aot.databases.models import GeoShape, Input, Output, Function, DeviceMeasurements
from aot.aot_flask.utils import utils_geo
from aot.aot_flask.geo.schedule_helpers import pending_schedules
from aot.aot_flask.access import scope
from aot.aot_flask.routes_geo import blueprint  # noqa: E402





@blueprint.route('/api/geo/devices', methods=['GET'])
@login_required
def api_geo_devices_list():
    """Returns a unified list of all available devices for mapping."""
    try:
        map_uuid = request.args.get('map_uuid')
        device_ids_raw = request.args.get('device_ids')
        
        device_ids = None
        if device_ids_raw:
            device_ids = [d.strip() for d in device_ids_raw.split(',') if d.strip()]

        include_all_param = request.args.get('include_all')
        include_all = (include_all_param == 'true' or include_all_param == 'True' or include_all_param is True)
        
        # If explicitly requested, or if no device_ids provided, default to show all
        if include_all_param is None:
            include_all = (not device_ids)

        # 지도 위젯이 주기적으로 부르는 자리다 — INFO 로 두면 이 한 줄이 로그를
        # 통째로 덮는다(실측 2026-09-16: 최근 5,000줄 중 3,997줄, 80%). 필터링
        # 모드를 보려던 진단 로그이므로 debug 로 내린다.
        current_app.logger.debug(f"[AoT API] Fetching devices for map_uuid: {map_uuid} include_all: {include_all} device_ids_count: {len(device_ids) if device_ids else 0}")

        # [Optimization] Use shared logic from utils_geo to ensure consistency
        # collect_devices handles all types (Input, Output, Function, etc.) and styling (Icon, Color, Status)
        # If device_ids is provided, it prioritizes them. If None/Empty, include_all=True takes over.
        devices = utils_geo.collect_devices(device_ids, include_all=include_all, map_uuid=map_uuid)
        
        # [New] Fetch all measurements for Popups
        all_measurements_map = utils_geo.get_all_measurements_for_map(devices)

        resp = jsonify({
            'ok': True,
            'devices': devices,
            'all_measurements_map': all_measurements_map
        })

        # 지도 위젯이 이 응답을 5초마다 다시 받는데, 실측상 폴링 사이에 바이트가
        # 완전히 동일하다(66KB~125KB). 조건부 응답으로 304(본문 0)를 돌려준다 —
        # 함정과 근거는 utils_http.json_conditional 의 독스트링에 있다.
        return utils_http.json_conditional(resp, request)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'message': str(e)}), 500


@blueprint.route('/api/geo/inputs', methods=['GET'])
@login_required
def api_geo_inputs():
    """Return flat measurement-channel list for sensor fitting binding.

    Each entry maps to one DeviceMeasurements channel so the UI can pick a
    specific channel (not just a device).  The frontend stores both input_id
    (device) and measurement_id (channel) on the fitting.
    """
    from aot.databases.models import Input
    from aot.databases.models.measurement import DeviceMeasurements
    rows = Input.query.filter(Input.is_activated).order_by(Input.name.asc()).all()
    device_ids = [r.unique_id for r in rows]
    inp_map = {r.unique_id: r for r in rows}

    dm_rows = (DeviceMeasurements.query
               .filter(DeviceMeasurements.device_id.in_(device_ids))
               .order_by(DeviceMeasurements.channel.asc())
               .all()) if device_ids else []

    # Batch lookup of converted units
    from aot.databases.models.measurement import Conversion as _Conv
    from aot.databases.models import Measurement, Unit as _Unit
    from aot.aot_flask.utils.utils_general import add_custom_measurements, add_custom_units, find_name_unit
    _cids = {dm.conversion_id for dm in dm_rows if dm.conversion_id}
    _cmap = {}
    if _cids:
        for _cv in _Conv.query.filter(_Conv.unique_id.in_(_cids)).all():
            _cmap[_cv.unique_id] = _cv.convert_unit_to or ''
    _du = add_custom_units(_Unit.query.all())

    channels = []
    for dm in dm_rows:
        inp = inp_map.get(dm.device_id)
        if not inp:
            continue
        raw_unit = _cmap.get(dm.conversion_id, dm.unit or '') if dm.conversion_id else (dm.unit or '')
        unit = find_name_unit(_du, raw_unit)
        label = ('{} / {} {}'.format(
            inp.name or 'Input',
            dm.measurement or dm.unique_id,
            ('(' + unit + ')') if unit else '',
        )).strip()
        channels.append({
            'input_id':      dm.device_id,
            'input_name':    inp.name or 'Input',
            'device':        inp.device or '',
            'measurement_id': dm.unique_id,
            'measurement':   dm.measurement or '',
            'unit':          unit,
            'label':         label,
        })

    return jsonify({'ok': True, 'channels': channels})


@blueprint.route('/api/geo/outputs', methods=['GET'])
@login_required
def api_geo_outputs():
    """List Output devices for binding to actuating fittings (windows, fans, heaters, fixtures).

    Non-sensor fittings drive a physical output (relay, motor, valve, PWM).
    This returns a flat lightweight list for the fitting inspector dropdown.
    """
    from aot.databases.models import Output
    rows = Output.query.order_by(Output.name.asc()).all()
    items = [{
        'unique_id': r.unique_id,
        'name': r.name or 'Output',
        'output_type': r.output_type or '',
        'interface': r.interface or '',
    } for r in rows]
    return jsonify({'ok': True, 'outputs': items})


@blueprint.route('/api/geo/output/<string:output_uuid>/state', methods=['POST'])
@login_required
def api_geo_output_state(output_uuid):
    """장치(Output) ON/OFF 제어 (세션 인증 래퍼)."""
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403
    # 그룹 스코프(A1a) — docs/design/access-scope-groups.md
    if not scope.can_operate_device(output_uuid):
        return jsonify({'ok': False, 'error': scope.deny_message()}), 403

    data = request.get_json(force=True, silent=True) or {}
    state = data.get('state')
    channel = int(data.get('channel', 0))
    duration = data.get('duration')

    if state is None:
        return jsonify({'ok': False, 'error': 'state required'}), 422

    try:
        from aot.aot_client import DaemonControl, daemon_call_failed
        ctrl = DaemonControl()
        if duration is not None:
            ret = ctrl.output_on_off(output_uuid, bool(state),
                                     output_channel=channel,
                                     output_type='sec', amount=float(duration))
        else:
            ret = ctrl.output_on_off(output_uuid, bool(state),
                                     output_channel=channel)
        if ret is None:
            return jsonify({'ok': False, 'error': 'daemon unreachable'}), 500
        # output_on_off never returns None on a timeout -- it returns
        # (code, msg) with a non-zero code, so the None check above cannot
        # catch the failure that actually happens. Read the code.
        call_failed, fail_msg = daemon_call_failed(ret)
        if call_failed:
            current_app.logger.error(
                "api_geo_output_state could not command %s: %s",
                output_uuid, fail_msg)
            return jsonify({'ok': False, 'error': fail_msg}), 502
        return jsonify({'ok': True, 'result': ret})
    except Exception as e:
        current_app.logger.exception("api_geo_output_state failed")
        return jsonify({'ok': False, 'error': str(e)}), 500


@blueprint.route('/api/geo/output_states', methods=['POST'])
@login_required
def api_geo_output_states():
    """지정한 Output들의 현재 상태 일괄 조회 (구역 팝업 폴링용, 경량).

    'on'/'off'/'pending'/'fault'/숫자/불리언 원본 값을 그대로 반환한다.
    on/off 로 뭉뚱그리지 않는 이유: 'fault'(응답 없음/오프라인)를 truthy 로
    잘못 접어버리면 오프라인 장치가 켜진 것처럼 표시되는 버그가 난다. 최종
    on/off/pending/fault 판정은 프론트에서 공용 분류기 AoTOutputState.classify()
    (aot-output-state.js) 로 한다 — facility 팝업/장치 마커와 동일한 판정 기준.
    """
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids:
        return jsonify({'ok': True, 'states': {}})

    from aot.aot_client import DaemonControl
    try:
        all_states = DaemonControl().output_states_all() or {}
    except Exception:
        all_states = {}

    states = {}
    for uid in ids:
        ch_states = all_states.get(uid)
        if not isinstance(ch_states, dict):
            continue
        states[uid] = {str(ch): raw for ch, raw in ch_states.items()}
    return jsonify({'ok': True, 'states': states})


@blueprint.route('/api/geo/output_runtimes', methods=['POST'])
@login_required
def api_geo_output_runtimes():
    """출력들의 작동 경과·마지막 작동·다음 예약 일괄 조회 (모달 목록 2행용).

    **`/api/geo/output_states` 와 분리한 이유가 있다.** 그쪽은 구역 모달이 5초마다
    치는 폴링 경로다. 여기 있는 조회는 채널마다 influx 를 읽으므로(작동 시작
    시각·마지막 작동), 5초 폴링에 얹으면 모달을 열어 둔 내내 influx 를 두들긴다.
    이 응답은 모달을 열 때 한 번만 받는다.

    예약 시각은 **서버가 문자열로 만들어 보낸다** — 장치 현지 시각대 해석은
    서버에 있고(resolve_location_tz), 클라이언트가 다시 추측하면 두 벌이 된다.
    """
    data = request.get_json(force=True, silent=True) or {}
    items = data.get('items')
    if not isinstance(items, list) or not items:
        return jsonify({'ok': True, 'runtimes': {}})

    from aot.utils import runtime as _runtime
    from aot.utils.system_pi import is_int
    from aot.databases.models import OutputChannel

    out = {}
    for it in items[:60]:
        if not isinstance(it, dict):
            continue
        oid = str(it.get('id') or '').strip()
        if not oid:
            continue
        ch = it.get('channel', 0)
        key = '%s::%s' % (oid, ch)

        # get_elapsed_seconds()/get_last_duration() 은 정수 채널 인덱스를 요구한다
        # (daemon output_state 경유). 위젯 쪽은 select_measurement_channel 옵션이
        # OutputChannel.unique_id 를 주므로, output_mod 라우트와 같은 방식으로
        # 여기서도 UUID → 정수를 변환한다. 응답 key(oid::ch)는 요청자가 보낸
        # raw 값 그대로 유지 — 클라이언트가 자기가 보낸 값으로 그대로 찾는다.
        ch_idx = ch
        if not is_int(ch):
            ch_row = OutputChannel.query.filter_by(unique_id=str(ch)).first()
            ch_idx = ch_row.channel if ch_row else 0

        entry = {'elapsed_sec': None, 'last_duration_sec': None,
                 'next_schedule': None, 'schedules': []}
        try:
            entry['elapsed_sec'] = _runtime.get_elapsed_seconds(oid, ch_idx) or None
        except Exception:
            pass
        # 작동 중이면 마지막 작동은 굳이 읽지 않는다 — 화면에 쓰지 않는 값에
        # influx 왕복을 쓸 이유가 없다(우선순위: 작동 중 > 예약 > 마지막).
        if not entry['elapsed_sec']:
            try:
                entry['last_duration_sec'] = _runtime.get_last_duration(oid, ch_idx) or None
            except Exception:
                pass
        entry['schedules'] = pending_schedules(oid)
        entry['next_schedule'] = (entry['schedules'][0]['start']
                                  if entry['schedules'] else None)
        out[key] = entry

    return jsonify({'ok': True, 'runtimes': out})


@blueprint.route('/api/geo/link_status', methods=['POST'])
@login_required
def api_geo_link_status():
    """지정한 장치들의 배터리·통신품질 상태 일괄 조회 (장치 모달 배지용).

    Input 은 보통 자기 채널에서 나오지만, LoRaWAN Output 은 배터리도 RSSI 도
    자기 것이 없다 — 같은 DevEUI 를 가진 하트비트 Input/Function 이 값을 들고
    있다. 그 짝짓기를 서버에서 하는 이유는 클라이언트가 custom_options 를 볼 수
    없기 때문이고, 배치인 이유는 나중에 마커에도 배지를 달면 N+1 이 되기 때문이다.

    battery / link 이 null 이면 근거 채널이 없다는 뜻이다 — 이때 프론트는 배지를
    아예 그리지 않는다(빈 아이콘은 "정보 없음"이 아니라 "0%"로 읽힌다).
    """
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids:
        return jsonify({'ok': True, 'status': {}})

    from aot.aot_flask.geo.device_link_status import read_link_status_batch
    try:
        status = read_link_status_batch([str(i) for i in ids[:100] if i])
    except Exception as e:
        current_app.logger.error(f"link_status 조회 실패: {e}")
        return jsonify({'ok': False, 'status': {}}), 500
    return jsonify({'ok': True, 'status': status})


@blueprint.route('/api/geo/zone/<string:zone_uuid>/output_history', methods=['GET'])
@login_required
def api_geo_zone_output_history(zone_uuid):
    """Zone 장치 작동 이력 (sensor chart 오버레이용) — 하위호환 별칭.

    zone_uuid 는 존재 확인 외에는 쓰이지 않는다(조회는 output_id 로만 스코프).
    정본은 /api/geo/output/<output_uuid>/history — 구역 밖(시설 모달·장치 마커
    팝업)에서도 같은 이력 그래프를 그리려면 zone 스코프가 없어야 하기 때문이다.
    """
    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    output_id = request.args.get('output_id', '').strip()
    if not output_id:
        return jsonify({'ok': False, 'error': 'output_id required'}), 400
    return _output_history_response(output_id, request.args.get('hours'))


@blueprint.route('/api/geo/output/<string:output_uuid>/history', methods=['GET'])
@login_required
def api_geo_output_history(output_uuid):
    """장치(Output) 작동 이력 — 구역/시설/마커 팝업 공용.

    Query params: hours (기본 24, 최대 168)
    """
    output_uuid = (output_uuid or '').strip()
    if not output_uuid:
        return jsonify({'ok': False, 'error': 'output_id required'}), 400
    return _output_history_response(output_uuid, request.args.get('hours'))


def _output_history_response(output_id, hours_arg):
    """duty_cycle(%) 우선, 없으면 duration_time(작동 분) 시계열을 반환한다."""
    import time as _time
    from aot.utils.influx import query_string, influx_to_list

    try:
        hours = min(max(float(hours_arg if hours_arg is not None else 24), 1.0), 168.0)
    except (TypeError, ValueError):
        hours = 24.0
    past_sec = int(hours * 3600)

    points = []
    series_type = None

    _LOOKBACK_SEC = 7 * 86400
    try:
        now_ts = _time.time()
        window_start = now_ts - past_sec
        data = query_string('percent', output_id, measure='duty_cycle', channel=0,
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
            if anchor is not None and (not points or points[0][0] - window_start > 60):
                points.insert(0, [round(window_start, 1), anchor])
            if points and now_ts - points[-1][0] > 60:
                points.append([round(now_ts, 1), points[-1][1]])
            if points:
                series_type = 'percent'
    except Exception:
        pass

    if not points:
        try:
            data = query_string('s', output_id, measure='duration_time',
                                past_sec=past_sec, limit=1000)
            if data not in (None, False):
                for ts, dur in influx_to_list(data):
                    try:
                        dur = abs(float(dur))
                    except (TypeError, ValueError):
                        continue
                    if dur <= 0:
                        continue
                    points.append([round(ts, 1), round(dur / 60.0, 2)])
                points.sort(key=lambda p: p[0])
                if points:
                    series_type = 'onoff'
        except Exception:
            pass

    return jsonify({
        'ok': True,
        'output_id': output_id,
        'series_type': series_type,
        'points': points,
        'hours': hours,
        'ts': _time.time(),
    })


@blueprint.route('/api/geo/zone/<string:zone_uuid>/output_order', methods=['POST'])
@login_required
def api_geo_zone_output_order(zone_uuid):
    """Zone 장치 배치 순서 저장."""
    from aot.aot_flask.extensions import db as _db

    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    body = request.get_json(force=True, silent=True) or {}
    order = body.get('order', [])
    if not isinstance(order, list):
        return jsonify({'ok': False, 'error': 'order must be a list'}), 422

    # dict() 필수 — 제자리 수정은 SQLAlchemy 가 못 본다(rep_key 라우트 주석).
    meta = dict(zone.meta_json or {})
    meta['output_order'] = [str(x) for x in order]
    zone.meta_json = meta
    _db.session.commit()

    from aot.aot_flask.geo.site_summary import invalidate_zone_contents
    invalidate_zone_contents(zone_uuid)
    return jsonify({'ok': True})
