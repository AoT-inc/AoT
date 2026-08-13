# coding=utf-8
"""식생 구획(작기) API 라우트 — routes_geo 의 서브모듈.

routes_geo.py 맨 아래에서 import 되어 공유 blueprint 에 등록된다
(routes_geo_iec / routes_geo_commissioning 과 같은 방식).

설계 정본: docs/design/geo-vegetation-planting.md
"""
import logging
from datetime import datetime

from flask import request, jsonify
from flask_login import login_required

from aot.aot_flask.geo import planting_context, planting_io
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
