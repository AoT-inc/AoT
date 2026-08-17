# coding=utf-8
"""식생 구획(작기) API 라우트 — routes_geo 의 서브모듈.

routes_geo.py 맨 아래에서 import 되어 공유 blueprint 에 등록된다
(routes_geo_iec / routes_geo_commissioning 과 같은 방식).

설계 정본: docs/design/geo-vegetation-planting.md
"""
import logging
from datetime import datetime

from flask import request, jsonify, current_app
from flask_login import login_required

from aot.aot_flask.geo import planting_context, planting_io, planting_split
from aot.aot_flask.utils import utils_general
from aot.databases.models import GeoPlanting, GeoShape
from aot.aot_flask.routes_geo import blueprint  # noqa: E402

logger = logging.getLogger(__name__)


def _require_edit():
    """쓰기 권한 확인 — 없으면 응답 튜플, 있으면 None."""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403
    return None


def _parse_on(value):
    """?on=YYYY-MM-DD → date | None. 형식이 틀리면 None(=오늘)으로 떨어진다."""
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


# ── 목록 ───────────────────────────────────────────────────────────────────

@blueprint.route('/api/geo/plantings', methods=['GET'])
@login_required
def api_plantings_list():
    """지도의 식생 구획 목록.

    기본은 **재배 중인 것만** 준다. 종료된 작기까지 기본으로 실으면 몇 년 지난
    지도에서 목록도 렌더도 옛 두둑으로 뒤덮인다 — 이력은 요청해야 온다
    (`include_ended=1`).
    """
    map_uuid = request.args.get('map_uuid')
    if not map_uuid:
        return jsonify({'ok': False, 'message': 'map_uuid required'}), 400

    on = _parse_on(request.args.get('on'))
    include_ended = request.args.get('include_ended') in ('1', 'true', 'True')

    if include_ended:
        rows = GeoPlanting.query.filter_by(geo_id=map_uuid).order_by(
            GeoPlanting.planted_on.desc()).all()
    else:
        rows = planting_context.active_plantings(map_uuid, on=on)

    # 컨테이너를 한 번만 준비한다 — 구획마다 다시 훑으면 지도 도형 전량
    # 스캔이 행 수만큼 반복된다.
    from aot.aot_flask.geo import device_membership
    containers = device_membership.load_containers(map_uuid)

    items = [planting_context.to_dict(r, containers=containers) for r in rows]
    return jsonify({'ok': True, 'plantings': items, 'count': len(items)})


@blueprint.route('/api/geo/planting/<string:planting_uuid>', methods=['GET'])
@login_required
def api_planting_get(planting_uuid):
    row = GeoPlanting.query.filter_by(unique_id=planting_uuid).first()
    if row is None:
        return jsonify({'ok': False, 'message': 'planting not found'}), 404
    return jsonify({'ok': True,
                    'planting': planting_context.to_dict(row, with_sensors=True)})


@blueprint.route('/api/geo/planting/<string:planting_uuid>/contents',
                 methods=['GET'])
@login_required
def api_planting_contents(planting_uuid):
    """식생 구획 모달의 [환경·제어] 인벤토리 — 구역 모달과 **같은 모양**.

    본체는 구역과 공유한다(`_build_area_contents`). 두 벌로 만들면 같은 장치를
    두 화면이 다르게 세게 되고, 이 도메인은 이미 그 실패로 크게 데었다.

    ⚠ 이 응답은 **소유가 아니라 참조**다. 구획은 컨테이너가 아니므로
    (`device_membership._CONTAINER_TYPES` 에 넣지 말 것 — 설계 §256) 여기 실린
    장치는 "이 구획의 것" 이 아니라 "이 구획을 다루려면 손대는 것" 이다.
    그래서 항목마다 `scope` 로 **왜 여기 보이는지**를 함께 낸다.

    캐시는 구역과 같은 30초. can_edit 는 권한이라 캐시 밖에서 매번 채운다.
    """
    from aot.aot_flask.geo.site_summary import cached_planting_contents

    payload = cached_planting_contents(
        planting_uuid, lambda: _build_planting_contents(planting_uuid))
    if payload is None:
        return jsonify({'ok': False, 'error': 'planting not found'}), 404

    payload = dict(payload)
    payload['planting'] = dict(payload['planting'])
    payload['planting']['can_edit'] = utils_general.user_has_permission(
        'edit_settings', silent=True)
    return jsonify(payload)


def _env_of(input_ids):
    """센서 묶음의 현재 환경 — `{'readings', 'sensors': {'valid','total'}}`.

    `valid > 0` 이면 **지금 값을 주고 있다**는 뜻이다. 판정을 `env_for_devices`
    하나로 하는 이유: 필지 요약·구역 모달이 "센서 응답 2/3" 을 셀 때 쓰는 것과
    같은 함수여야 한다. 여기서 따로 세면 같은 센서를 두고 한 화면은 살아 있다
    하고 다른 화면은 죽었다 한다.

    조회가 실패하면 **살아 있는 것으로 본다**(`valid`를 1로). 실패를 "죽었다"
    로 읽으면 인플럭스가 잠깐 흔들릴 때마다 화면이 옆 구획 센서로 갈아탄다.
    """
    if not input_ids:
        return {'readings': [], 'sensors': {'valid': 0, 'total': 0}}
    from aot.aot_flask.geo.site_summary import env_for_devices
    try:
        return env_for_devices(input_ids)
    except Exception:
        current_app.logger.exception('planting contents: 센서 신선도 판정 실패')
        return {'readings': [], 'sensors': {'valid': 1, 'total': 1}}


def _sensor_order_key(item):
    """값을 주는 것 → 구획 안 → 가까운 것 순."""
    return (1 if item.get('no_data') else 0,
            0 if item.get('scope') == 'plot' else 1,
            item.get('distance_m') if item.get('distance_m') is not None else 0,
            item.get('name') or '')


def _involvement_key(item):
    """관여도 정렬 키 — 높을수록 위. `sort()` 용이라 **작을수록 앞**으로 뒤집는다.

    관여도의 정의:
      * 덮는 비율(`coverage_pct`)이 있으면 그 값. 측정된 정도라 가장 강한 근거다.
      * 없고 구획 안에 있으면(`plot`) 100 — 구획 전체를 상대한다고 본다.
        비율은 밸브에만 있는 개념이라, 구획 안의 팬·조명에는 잴 것이 없다.
      * 구획 밖에서 적시는데 비율이 없으면 0.
      * `nearest` 는 **직접 관여가 아니다** — 항상 맨 아래로 보내고, 그 안에서만
        가까운 순으로 둔다.
    """
    scope = item.get('scope')
    if scope == 'nearest':
        # 관여도 축 밖. 거리가 가까울수록 앞.
        return (1, item.get('distance_m') if item.get('distance_m') is not None
                else float('inf'), item.get('name') or '')

    pct = item.get('coverage_pct')
    if pct is None:
        pct = 100.0 if scope == 'plot' else 0.0
    return (0, -float(pct), item.get('name') or '')


def _classify_devices(device_ids):
    """장치 id 집합 → `{'inputs','outputs','functions'}` 로 나눈 집합들.

    종류별 폴백("센서가 하나도 없으면 가장 가까운 센서")을 하려면 어느 것이
    센서인지 **미리** 알아야 한다. id 만 뽑는 가벼운 조회 3번이다.
    """
    from aot.databases.models import (Conditional, CustomController, Function,
                                      Input, Output, Trigger, PID)

    if not device_ids:
        return {'inputs': set(), 'outputs': set(), 'functions': set()}

    ids = list(device_ids)

    def _pick(model):
        return {r[0] for r in model.query.with_entities(
            model.unique_id).filter(model.unique_id.in_(ids)).all()}

    funcs = set()
    for model in (CustomController, Function, Conditional, Trigger, PID):
        funcs |= _pick(model)
    return {'inputs': _pick(Input), 'outputs': _pick(Output),
            'functions': funcs}


def _build_planting_contents(planting_uuid):
    """식생 모달 인벤토리 본체. 못 찾으면 None(캐시에 남기지 않는다)."""
    from aot.aot_flask.geo import device_membership
    from aot.aot_flask.routes_geo import _build_area_contents

    row = GeoPlanting.query.filter_by(unique_id=planting_uuid).first()
    if row is None:
        return None

    geom = planting_context.geometry_of(row)

    # ── 무엇을 낼 것인가: **이 구획에 닿는 것만** ──────────────────────────
    #
    # 예전에는 구획 안 ∪ 구역 전체 ∪ 밸브를 합집합으로 냈다. 그러면 이 구획에
    # 물 한 방울 주지 않는 밸브까지 목록에 올라와, 식생 패널이 구역 패널의
    # 복사본이 된다 — 그럴 거면 구역 패널을 열면 된다. 실측(김제 새바람):
    # 출력 4개 중 실제로 이 구획에 닿는 것은 2개였고 나머지 둘은 교차가 0이었다.
    #
    #  plot        구획 폴리곤 안에 있다
    #  irrigation  구획 밖이지만 **이 구획을 적신다**(면적이 있는 교차)
    #  nearest     위 둘이 그 종류에서 하나도 없을 때만, 가장 가까운 것 하나
    #
    # 'zone'(구역에 있다는 이유만으로 싣기)은 없앴다. 구역 전체를 보려면 위로
    # 올라가는 화살표가 있다.
    plot_ids = set(device_membership.device_ids_in_geometry(
        row.geo_id, geom, _label='planting %s' % row.unique_id) or [])

    zone = planting_context.zone_for_planting(row)
    zone_ids = set(device_membership.device_ids_in_shape(zone) or []) if zone else set()

    # valves_for_planting 은 **면적이 있는 교차만** 낸다 — 여기 오는 밸브는
    # 전부 실제로 이 구획을 적신다.
    valves = planting_context.valves_for_planting(row)
    valve_ids = {v['device_id'] for v in valves if v.get('device_id')}

    direct = plot_ids | valve_ids

    # 종류별로 비었을 때만 가장 가까운 것 하나를 더한다. 종류를 섞어 판정하면
    # "센서는 있는데 밸브가 없는" 구획에서 센서까지 폴백이 걸린다.
    kinds_direct = _classify_devices(direct)
    kinds_zone = _classify_devices(zone_ids - direct)
    markers = device_membership.load_markers(row.geo_id)

    # 센서는 **있느냐가 아니라 값을 주느냐**로 판정한다. 구획 안에 센서가
    # 놓여 있어도 죽어 있으면 화면은 빈 차트가 되고, 사용자는 "이 구획은 볼
    # 값이 없다" 로 읽는다 — 바로 옆에 멀쩡한 센서가 있는데도.
    #
    # 죽은 센서를 목록에서 **빼지는 않는다.** 빼면 고장이 화면에서 사라져
    # 아무도 고치지 않는다. 대신 대체값을 함께 올리고, 정렬에서 값을 주는
    # 쪽을 위로 보낸다(아래 _sensor_order_key).
    #
    # env 는 여기서 **한 번만** 잰다. 판정에 쓰고, 값을 안 바꿔도 되는 경우
    # (= 인접 센서를 안 끌어온 경우)에는 그대로 아래 인벤토리에 넘긴다 —
    # 예전에는 같은 influx 왕복을 두 번 했다(실측 약 64ms 낭비).
    plot_env = None
    stale_direct = False
    if kinds_direct['inputs']:
        plot_env = _env_of(kinds_direct['inputs'])
        stale_direct = (plot_env.get('sensors') or {}).get('valid', 0) == 0

    nearest = {}          # device_id -> 거리(m)
    nearest_reason = {}   # device_id -> 'missing' | 'stale'
    for kind in ('inputs', 'outputs', 'functions'):
        have = kinds_direct[kind]
        reason = 'missing'
        if kind == 'inputs' and have and stale_direct:
            have = set()          # 있어도 값을 못 주면 없는 것으로 친다
            reason = 'stale'
        if have or not kinds_zone[kind]:
            continue
        for did, dist in planting_context.nearest_devices(
                row, kinds_zone[kind], markers=markers, limit=1):
            nearest[did] = dist
            nearest_reason[did] = reason

    # "켜면 무엇이 함께 젖는가" — 구역 모달과 **같은 함수**로 센다. 여기서
    # 따로 세면 같은 밸브가 두 화면에서 다른 작물 목록을 갖게 된다.
    cover = planting_context.plantings_by_valve_device(row.geo_id)

    coverage = {v['device_id']: v.get('coverage_pct')
                for v in valves if v.get('device_id')}

    def _scope_of(uid):
        if uid in plot_ids:
            return 'plot'
        if uid in nearest:
            return 'nearest'
        return 'irrigation'

    # 인접 센서를 끌어왔으면 집합이 달라졌으니 다시 재야 한다. 아니면 위에서
    # 이미 잰 것이 그대로 맞다 — env 는 Input 만 보고, direct 의 Input 은
    # kinds_direct['inputs'] 뿐이다(나머지는 Output·Function).
    added_input = any(d in kinds_zone['inputs'] for d in nearest)
    inv = _build_area_contents(direct | set(nearest), scope_of=_scope_of,
                               env=(None if added_input else plot_env))

    # 가장 가까운 것으로 끌어온 장치는 **거리를 함께 낸다** — 왜 여기 있는지,
    # 얼마나 믿을 값인지 사람이 판단할 근거다.
    for group in ('sensors', 'outputs', 'functions'):
        for item in inv[group]:
            if item['unique_id'] in nearest:
                item['distance_m'] = nearest[item['unique_id']]
                item['nearest_reason'] = nearest_reason.get(item['unique_id'])

    # 값을 못 주는 구획 센서에 표시를 남긴다 — 화면이 "왜 옆 것을 보여주나"
    # 를 설명할 근거이자, 고장이 있다는 사실 자체다.
    if stale_direct:
        for item in inv['sensors']:
            if item.get('scope') == 'plot':
                item['no_data'] = True

    # 값을 주는 센서가 먼저 온다 — 첫 탭이 자동으로 그려지므로, 죽은 센서가
    # 앞에 있으면 열자마자 빈 차트를 보게 된다.
    inv['sensors'].sort(key=_sensor_order_key)

    # 밸브 정보는 출력 행에 붙인다 — 별도 블록으로 내면 화면이 같은 장치를
    # 두 번 그리게 되고, 토글 옆에 있어야 할 경고가 토글에서 멀어진다.
    for out in inv['outputs']:
        pct = coverage.get(out['unique_id'])
        if pct is not None:
            out['coverage_pct'] = pct
        # 자기 자신은 "함께 젖는 것" 이 아니다.
        names = planting_context.covered_crop_names(
            cover.get(out['unique_id']), exclude_uuid=row.unique_id)
        if names:
            out['also_covers'] = names

    # ── 순서: 관여도가 높은 것이 위 ────────────────────────────────────────
    #
    # DB 순서 그대로 두면 이 구획의 75.9% 를 적시는 밸브가 24.1% 짜리 아래로
    # 내려간다(실측). 목록의 첫 줄이 가장 관여도가 낮은 장치면, 급한 상황에서
    # 사람이 맨 위를 누른다.
    #
    # ⚠ **`coverage_pct` 를 붙인 뒤에 정렬한다.** 순서를 바꾸면 정렬 시점에
    # 비율이 아직 없어 전부 0으로 읽히고, 조용히 **이름순**으로 떨어진다.
    # 실제로 그렇게 나갔다: 둘 다 irrigation 인 구획(블랙틴)에서 39.8% 가
    # 60.2% 보다 위였다. plot 과 irrigation 이 섞인 구획은 스코프만으로도
    # 우연히 맞아서 한동안 드러나지 않았다.
    #
    # 정렬은 **서버가** 한다 — 화면마다 각자 정렬하면 같은 구획이 창마다 다른
    # 순서로 보이고, AI 도구가 보는 순서와도 갈린다.
    #
    # 구역 모달은 이 정렬을 쓰지 않는다. 그쪽은 사람이 드래그로 정한 순서
    # (`output_order`)가 있고, 그것은 명시적 의사표시라 계산이 이겨선 안 된다.
    for group in ('outputs', 'functions'):
        inv[group].sort(key=_involvement_key)

    sensors = planting_context.sensors_for_planting(row)

    return {
        'ok': True,
        'planting': {
            'unique_id': row.unique_id,
            'crop': row.crop,
            'variety': row.variety,
            'name': row.name,
            'area_m2': round(planting_context.area_m2(row), 1),
            'dims': planting_context.dimensions(row),
            'days_since_planted': planting_context.elapsed_days(row),
            'days_to_expected_end': planting_context.days_to_expected_end(row),
            'active': row.is_active(),
            'zone_uuid': sensors.get('zone_uuid'),
            'zone_name': sensors.get('zone_name'),
            'counts': inv['counts'],
            'env': inv['env'],
            'status': inv['status'],
        },
        # 대표값의 출처 — 목록(위 sensors/outputs)이 "손댈 수 있는 것 전부"
        # 라면 이쪽은 "이 구획을 대표하는 값이 어디서 오는가" 하나다. 둘은
        # 다른 질문이라 한쪽으로 합치지 말 것.
        'source': sensors.get('source'),
        'sensors': inv['sensors'],
        'outputs': inv['outputs'],
        'functions': inv['functions'],
    }


# ── 쓰기 ───────────────────────────────────────────────────────────────────

@blueprint.route('/api/geo/planting', methods=['POST'])
@login_required
def api_planting_save():
    """생성 또는 수정. `unique_id` 가 있으면 수정."""
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    result, error = planting_io.save_planting(data)
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify({'ok': True, 'planting': result})


@blueprint.route('/api/geo/planting/<string:planting_uuid>/end',
                 methods=['POST'])
@login_required
def api_planting_end(planting_uuid):
    """작기 종료 — 행을 지우지 않고 종료일을 적는다."""
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    result, error = planting_io.end_planting(
        planting_uuid,
        ended_on=data.get('ended_on'),
        reason=data.get('reason') or 'harvested')
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify({'ok': True, 'planting': result})


@blueprint.route('/api/geo/planting/<string:planting_uuid>/copy',
                 methods=['POST'])
@login_required
def api_planting_copy(planting_uuid):
    """지난 작기의 기하로 새 작기를 만든다."""
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    result, error = planting_io.copy_planting(
        planting_uuid,
        planted_on=data.get('planted_on'),
        crop=data.get('crop'))
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify({'ok': True, 'planting': result})


@blueprint.route('/api/geo/planting/<string:planting_uuid>', methods=['DELETE'])
@login_required
def api_planting_delete(planting_uuid):
    """오기입 삭제. 정상 종료는 /end 를 쓴다."""
    denied = _require_edit()
    if denied:
        return denied

    result, error = planting_io.delete_planting(planting_uuid)
    if error:
        status = 404 if 'not found' in error.lower() else 400
        return jsonify({'ok': False, 'message': error}), status
    return jsonify(result)


# ── 파생 조회 ──────────────────────────────────────────────────────────────

@blueprint.route('/api/geo/planting/<string:planting_uuid>/sensors',
                 methods=['GET'])
@login_required
def api_planting_sensors(planting_uuid):
    """구획이 참조할 장치 — 저장된 값이 아니라 매번 파생한 결과."""
    row = GeoPlanting.query.filter_by(unique_id=planting_uuid).first()
    if row is None:
        return jsonify({'ok': False, 'message': 'planting not found'}), 404
    return jsonify({'ok': True,
                    'sensors': planting_context.sensors_for_planting(row)})


@blueprint.route('/api/geo/zone/<string:zone_uuid>/allocation',
                 methods=['GET'])
@login_required
def api_zone_allocation(zone_uuid):
    """zone 의 면적 배분 — 구획별 면적/비율 + 미배정.

    겹침이 정상이라 비율 합은 100%를 넘을 수 있다. 응답에 합계를 싣지 않는
    이유가 그것이다(`overlaps` 로 겹침 여부만 알린다).
    """
    zone = GeoShape.query.filter_by(unique_id=zone_uuid).first()
    if zone is None:
        return jsonify({'ok': False, 'message': 'zone not found'}), 404

    on = _parse_on(request.args.get('on'))
    return jsonify({'ok': True,
                    'allocation': planting_context.zone_allocation(zone, on=on)})


@blueprint.route('/api/geo/plantings/history', methods=['POST'])
@login_required
def api_plantings_history():
    """"이 자리에 뭐가 있었나" — 기하가 겹치는 작기 목록.

    연작 장해·윤작 판단의 근거다. 기준 기하는 본문으로 받는다:
      - `planting_uuid` 를 주면 그 구획의 기하
      - 또는 `geometry` 를 직접
    GET 이 아닌 이유는 폴리곤이 URL 에 담기지 않기 때문이다.
    """
    data = request.get_json(silent=True) or {}
    map_uuid = data.get('map_uuid')
    geom = data.get('geometry')

    if data.get('planting_uuid'):
        src = GeoPlanting.query.filter_by(
            unique_id=data['planting_uuid']).first()
        if src is None:
            return jsonify({'ok': False, 'message': 'planting not found'}), 404
        geom = planting_context.geometry_of(src)
        map_uuid = map_uuid or src.geo_id
    elif data.get('zone_uuid'):
        zone = GeoShape.query.filter_by(unique_id=data['zone_uuid']).first()
        if zone is None:
            return jsonify({'ok': False, 'message': 'zone not found'}), 404
        geom = planting_context.geometry_of(zone)
        map_uuid = map_uuid or zone.geo_id

    if not map_uuid or not geom:
        return jsonify({'ok': False,
                        'message': 'map_uuid and geometry required'}), 400

    pairs = planting_context.plantings_overlapping(map_uuid, geom)
    items = []
    for row, overlap_m2 in pairs:
        d = planting_context.to_dict(row)
        d['overlap_m2'] = round(overlap_m2, 1)
        items.append(d)
    return jsonify({'ok': True, 'history': items, 'count': len(items)})


# ── 분할 (미리보기 / 적용) ─────────────────────────────────────────────────
#
# **미리보기를 저장하지 않는다.** 분할은 결정적이라(같은 도형 + 같은 파라미터 →
# 항상 같은 결과) 미리보기는 보관할 상태가 아니라 다시 계산하면 되는 것이다.
# 그래서 임시 저장소도, TTL 도, 만료 처리도 없다 — 지도는 preview 로 그리고,
# 적용은 같은 파라미터로 재계산해서 만든다.
#
# 도형이 그 사이에 바뀌면 결과도 바뀐다. 그것이 맞다 — 사람이 밭 모양을 고쳤으면
# 새 모양대로 나뉘어야 한다.

def split_args_from(src):
    """요청에서 분할 파라미터를 뽑는다 → (kwargs, 오류문구).

    **식생 전용이 아니다.** 장치 담당 구역 분할(`routes_geo_device_split`)도
    같은 파라미터를 쓰므로 여기 하나를 공유한다 — 두 벌로 두면 한쪽에만 옵션이
    붙어 미리보기와 실제 결과가 갈린다.
    """
    shape_id = src.get('zone_id') or src.get('shape_id')
    if not shape_id:
        return None, 'zone_id is required'

    def _num(key):
        v = src.get(key)
        if v in (None, ''):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            raise ValueError('%s must be a number' % key)

    def _num_list(key):
        """조각별 폭 목록. POST(JSON)는 배열 그대로, GET(쿼리스트링)은 값이
        문자열뿐이라 콤마로 구분해 받는다(`widths_cm=500,1000,300`)."""
        v = src.get(key)
        if v in (None, ''):
            return None
        if isinstance(v, (list, tuple)):
            items = v
        else:
            items = [x for x in str(v).split(',') if x.strip() != '']
        try:
            return [float(x) for x in items]
        except (TypeError, ValueError):
            raise ValueError('%s must be a list of numbers' % key)

    orientation = src.get('orientation') or None
    if hasattr(orientation, 'strip'):
        orientation = orientation.strip().lower()

    try:
        return {
            'shape_id': shape_id,
            'parts': int(_num('parts')) if _num('parts') is not None else None,
            'strip_width_cm': _num('strip_width_cm'),
            # 있으면 parts/strip_width_cm 보다 우선한다(split_shape 의 규칙 —
            # 대체가 아니라 항상 함께 넘긴다, 상호배타 판단은 그쪽에서 한다).
            'widths_cm': _num_list('widths_cm'),
            'edge_margin_m': _num('edge_margin_m') or 0,
            # 이보다 짧은 조각은 버린다(cm). 두둑 기준 기본값(2m)은 장치 담당
            # 구역에는 너무 커서 좁은 구역이 조용히 사라진다 — 호출자가 정할 수
            # 있게 열어 둔다. **미리보기와 적용이 같은 값을 써야** 화면에서 본
            # 조각 수와 실제로 만들어지는 수가 갈리지 않는다.
            'min_length_cm': _num('min_length_cm'),
            # 생략(None)이면 split_shape() 이 모드(strip_width_cm 유무)로
            # 기본값을 정한다 — 여기서 'long' 을 하드코딩하면 그 분기와
            # 어긋날 수 있으므로 그대로 통과시킨다.
            'orientation': orientation,
            # 각도가 있으면 위 orientation 은 서버(split_shape)에서 무시된다 —
            # 대체가 아니라 공존이다. UI 는 둘 중 하나만 채워 보낸다.
            'angle_deg': _num('angle_deg'),
        }, None
    except ValueError as exc:
        return None, str(exc)


def split_kwargs_from(args):
    """`split_args_from` 결과 → `planting_split.split_shape` 키워드.

    한 곳에서 만든다 — 미리보기와 적용이 각자 조립하면 옵션 하나가 빠진 쪽만
    다른 결과를 낸다.
    """
    kwargs = dict(
        parts=args['parts'], strip_width_cm=args['strip_width_cm'],
        widths_cm=args.get('widths_cm'),
        edge_margin_m=args['edge_margin_m'], orientation=args['orientation'],
        angle_deg=args.get('angle_deg'))
    min_cm = args.get('min_length_cm')
    if min_cm is not None:
        kwargs['min_bed_length_m'] = float(min_cm) / 100.0
    return kwargs


def compute_split(args):
    """(strips, info, shape) 또는 (None, (응답, 코드))."""
    shape = GeoShape.query.filter_by(unique_id=args['shape_id']).first()
    if shape is None:
        return None, (jsonify({'ok': False,
                               'message': 'shape not found: %s' % args['shape_id']}), 404)
    strips, info = planting_split.split_shape(shape, **split_kwargs_from(args))
    if strips is None:
        return None, (jsonify({'ok': False, 'message': info}), 400)
    return (strips, info, shape), None


@blueprint.route('/api/geo/planting/split-preview', methods=['GET'])
@login_required
def api_planting_split_preview():
    """분할 제안을 계산해 돌려준다 — 아무것도 저장하지 않는다.

    지도가 이것을 점선으로 그린다. 사람이 보고 판단한 뒤 apply 로 넘어간다.
    """
    args, err = split_args_from(request.args)
    if err:
        return jsonify({'ok': False, 'message': err}), 400
    out, fail = compute_split(args)
    if fail:
        return fail
    strips, info, shape = out
    return jsonify({'ok': True, 'strips': strips, 'info': info,
                    'shape_uuid': shape.unique_id, 'geo_id': shape.geo_id})


@blueprint.route('/api/geo/planting/split-apply', methods=['POST'])
@login_required
def api_planting_split_apply():
    """미리보기와 **같은 파라미터로 재계산**해 구획을 만든다.

    미리보기에서 본 폴리곤을 클라이언트가 되돌려보내지 않는다 — 그러면 화면에서
    한 번 계산하고 저장할 때 다른 것을 보낼 수 있는 경로가 생긴다. 서버가 다시
    계산하는 편이 "본 것과 저장된 것이 같다" 를 구조로 보장한다.
    """
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    args, err = split_args_from(data)
    if err:
        return jsonify({'ok': False, 'message': err}), 400
    if not (data.get('crop') or '').strip():
        return jsonify({'ok': False, 'message': 'crop is required'}), 400
    out, fail = compute_split(args)
    if fail:
        return fail
    strips, info, shape = out

    name_base = (data.get('name') or '').strip()
    created, errors = [], []
    for strip in strips:
        payload = {
            'map_uuid': shape.geo_id,
            'feature': {'type': 'Feature', 'properties': {},
                        'geometry': strip['geometry']},
            'crop': data.get('crop'),
            'variety': data.get('variety'),
            'planted_on': data.get('planted_on'),
            'expected_end_on': data.get('expected_end_on'),
            'color': data.get('color'),
            'source_kind': 'copied',
            'source_ref': shape.unique_id,
        }
        if name_base:
            payload['name'] = '%s %d' % (name_base, strip['index'])
        row, error = planting_io.save_planting(payload)
        if error:
            errors.append({'index': strip['index'], 'message': error})
            continue
        row.pop('feature', None)
        created.append(row)

    # 일부만 저장된 것을 성공으로 말하지 않는다 — 지도에는 몇 개만 뜨는데
    # 응답은 성공이면 사용자는 나머지가 어디 갔는지 알 방법이 없다.
    return jsonify({'ok': not errors, 'created': created, 'info': info,
                    'errors': errors,
                    'message': (None if not errors else
                                '%d of %d pieces failed to save'
                                % (len(errors), len(strips)))})
