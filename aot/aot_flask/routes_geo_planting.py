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
