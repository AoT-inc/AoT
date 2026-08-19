# coding=utf-8
"""장치 담당 구역 분할 API — routes_geo 의 서브모듈.

routes_geo.py 맨 아래에서 import 되어 공유 blueprint 에 등록된다
(routes_geo_plot 과 같은 방식).

설계 정본: docs/design/geo-device-area-split.md

**미리보기는 식생과 같은 엔드포인트를 쓴다**(`/api/geo/plot/split-preview`).
그쪽은 도형을 잘라 조각을 돌려줄 뿐 작기와 아무 상관이 없어서, 장치용으로
똑같은 것을 하나 더 만들 이유가 없다. 갈리는 것은 **적용**뿐이다 — 식생은
GeoPlot 을, 여기서는 `GeoShape(type='device')` 를 만들고 장치에 배정한다.
"""
import logging

from flask import request, jsonify
from flask_login import login_required

from aot.aot_flask.geo import device_split
from aot.aot_flask.routes_geo import blueprint  # noqa: E402
from aot.aot_flask.routes_geo_plot import (  # 공용 분할 파라미터 계층
    _require_edit, compute_split, split_args_from, split_kwargs_from)

logger = logging.getLogger(__name__)


@blueprint.route('/api/geo/device/split-apply', methods=['POST'])
@login_required
def api_device_split_apply():
    """구역을 잘라 **장치 담당 구역**을 만들고, 조각 안의 마커로 자동 배정한다.

    미리보기와 **같은 파라미터로 서버가 다시 계산**한다 — 화면이 본 폴리곤을
    되돌려받지 않는다(식생 분할과 같은 이유: 본 것과 저장된 것이 같다는 보장은
    재계산이 한다).
    """
    denied = _require_edit()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    args, err = split_args_from(data)
    if err:
        return jsonify({'ok': False, 'message': err}), 400

    # 도형을 찾고 파라미터가 유효한지 먼저 확인한다 — 여기서 걸리면 아무것도
    # 만들지 않는다.
    out, fail = compute_split(args)
    if fail:
        return fail
    _strips, _info, shape = out

    result, error = device_split.split_shape_into_device_areas(
        shape, name_base=(data.get('name') or '').strip() or None,
        # 어느 종류의 장치로 나눌지 — 비우면 전 종류가 후보다(그러면 마커가
        # 섞인 지도에서는 거의 전부 '애매함' 이 된다, device_split 주석 참조).
        device_kind=(data.get('device_kind') or '').strip() or None,
        **split_kwargs_from(args))
    if error:
        return jsonify({'ok': False, 'message': error}), 400

    unassigned = result['unassigned']
    return jsonify({
        'ok': True,
        'created': result['created'],
        'info': result['info'],
        'assigned': result['assigned'],
        'unassigned': unassigned,
        # 몇 개가 배정되지 않았는지 **숨기지 않는다** — 지도에는 구역이 다
        # 생겼는데 절반이 장치 없이 남은 것을 모르면, 그 구역은 아무 일도 하지
        # 않으면서 있는 것처럼 보인다.
        'message': (None if not unassigned else
                    '%d of %d areas had no single device inside'
                    % (len(unassigned), len(result['created']))),
    })
