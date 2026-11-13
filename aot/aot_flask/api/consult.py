# coding=utf-8
"""상담용 읽기 전용 API — 주소 하나로 대지(필지) 도형을 돌려준다.

프로젝트 사이트(고객 상담 화면)의 서버가 API 키로 이 경로를 부른다. 고객은 AoT 에 직접
붙지 않는다.

`POST /api/consult/parcel` `{address}` →
    `{ok, feature(GeoJSON 필지 다각형, WGS84), pnu, area_m2, centroid:[lon,lat], address_normalized}`
    또는 `{ok:false, error:<코드>}` — 코드: `invalid_address`(400) · `not_found`(404) ·
    `vworld_unavailable`(503, 키 미등록·상류 장애) · `forbidden`(403) · `unauthorized`(401) ·
    `rate_limited`(429). 모든 실패가 같은 모양이다.

**읽기 전용이다. DB 에 아무것도 쓰지 않는다.** 필지 다각형은 응답으로만 주고 저장하지 않는다
(국토교통부 지오코더 안내의 저장 금지 문구 — 상담 설계 조사 §6-2).

왜 `/api/geo/parcel/from_address` 를 그대로 쓰지 않나: 그 경로는 `routes_geo` 블루프린트라 CSRF
면제 밖이어서 세션이 없는 API 키 클라이언트의 POST 가 400(csrf)으로 막힌다. 이 경로는 CSRF
면제인 `api_blueprint` 아래에 있고, 읽기 전용 키로도 열리도록 `app._READONLY_POST_PATHS` 에
등록돼 있다. **이 둘(면제·읽기 전용 예외)의 근거는 '아무것도 쓰지 않는다' 하나뿐이다.** 그
전제는 `aot/tests/test_consult_parcel_api.py` 가 정적으로 고정한다 — 쓰기 호출이 들어오면 깨진다.

필지 조회 자체는 새로 짜지 않고 `InputModule.parcel_from_address`(VWorld 3단계)를 재사용한다.
"""
import functools
import logging
import math
import os
import re

import flask_login
from flask import request
from flask_restx import Resource

from aot.aot_flask.api import api, default_responses
from aot.aot_flask.utils import utils_general
from aot.space.facility_calc import polygon_area_m2

logger = logging.getLogger(__name__)

ns_consult = api.namespace('consult', description='Read-only consulting helpers (no DB writes)')

#: 주소 길이 한도(공백 정리 뒤). 도로명+지번+건물명이 이보다 길 일은 없고, 외부 호출 URL 에 실리는 값이다.
ADDRESS_MIN_LEN = 2
ADDRESS_MAX_LEN = 200

_CONTROL_CHARS = re.compile(r'[\x00-\x1f\x7f]')
_BLANKS = re.compile(r'\s+')

#: 오류 코드 → HTTP 상태.
ERROR_STATUS = {
    'invalid_address': 400,
    'not_found': 404,
    'vworld_unavailable': 503,
}


def normalize_address(value):
    """요청의 주소를 정리한다. 쓸 수 없으면 None.

    문자열이 아니거나, 제어 문자가 있거나, 공백 정리 뒤 길이가 한도 밖이면 거절한다.
    """
    if not isinstance(value, str):
        return None
    if _CONTROL_CHARS.search(value):
        return None
    text = _BLANKS.sub(' ', value).strip()
    if not (ADDRESS_MIN_LEN <= len(text) <= ADDRESS_MAX_LEN):
        return None
    return text


def _outer_rings(geometry):
    """(Multi)Polygon 의 바깥 고리들. 다른 형식이면 빈 리스트."""
    if not isinstance(geometry, dict):
        return []
    coords = geometry.get('coordinates')
    if geometry.get('type') == 'Polygon':
        polys = [coords] if coords else []
    elif geometry.get('type') == 'MultiPolygon':
        polys = coords or []
    else:
        return []
    rings = []
    for poly in polys:
        if poly and poly[0] and len(poly[0]) >= 4:
            rings.append(poly[0])
    return rings


def centroid_lonlat(geometry):
    """면적 가중 무게중심 `[lon, lat]`. 고리가 없으면 None.

    경위도를 그대로 쓰면 위도에 따라 가로가 줄어드는 것을 무시하게 되므로, 고리별로
    `facility_calc` 와 같은 국소 미터 평면(위도 코사인 보정)으로 옮겨 계산한다.
    여러 조각이면 조각 면적으로 다시 가중한다.
    """
    sx = sy = total = 0.0
    for ring in _outer_rings(geometry):
        lat0 = sum(c[1] for c in ring) / len(ring)
        kx = 111320.0 * math.cos(math.radians(lat0))
        ky = 111320.0
        # 첫 점을 원점으로 옮긴다 — 경위도 그대로 미터로 바꾸면 ~1e7 끼리 곱해 작은 필지에서 자릿수가 깎인다.
        ox, oy = ring[0][0], ring[0][1]
        pts = [((c[0] - ox) * kx, (c[1] - oy) * ky) for c in ring]
        a2 = cx = cy = 0.0
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            f = x1 * y2 - x2 * y1
            a2 += f
            cx += (x1 + x2) * f
            cy += (y1 + y2) * f
        if abs(a2) < 1e-9:
            continue
        area = abs(a2) / 2.0
        gx, gy = cx / (3.0 * a2), cy / (3.0 * a2)       # a2 = 2*부호 있는 면적
        sx += (ox + gx / kx) * area
        sy += (oy + gy / ky) * area
        total += area
    if total <= 0.0:
        pts = [c for ring in _outer_rings(geometry) for c in ring]
        if not pts:
            return None
        return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)]
    return [sx / total, sy / total]


#: 외부 호출 3~7번을 부르므로 `app.extension_limiter` 의 블루프린트 한도(200/분)보다 촘촘히.
#: 환경 변수 `AOT_CONSULT_PARCEL_LIMIT`(예: "60/minute")로 바꾼다. 기본 30/분.
#: 고객별 한도는 프로젝트 사이트가 맡는다 — 여기서 세는 것은 호출한 **키 하나**의 몫이다.
PARCEL_RATE_LIMIT = "30/minute"
PARCEL_RATE_LIMIT_ENV = 'AOT_CONSULT_PARCEL_LIMIT'


def parcel_rate_limit():
    """적용할 한도 문자열. 환경 변수가 있고 해석되면 그것, 아니면 기본값."""
    raw = (os.environ.get(PARCEL_RATE_LIMIT_ENV) or '').strip()
    if not raw:
        return PARCEL_RATE_LIMIT
    try:
        from limits import parse
        parse(raw)
        return raw
    except Exception:
        logger.warning("consult/parcel: %s=%r 을 해석하지 못해 기본값 %s 를 쓴다",
                       PARCEL_RATE_LIMIT_ENV, raw, PARCEL_RATE_LIMIT)
        return PARCEL_RATE_LIMIT


def rate_limit_key():
    """빈도 제한을 세는 단위: API 키 하나(키 ID) → 세션이면 사용자명 → 마지막으로 IP.

    프로젝트 사이트 서버 한 대가 모든 고객 호출을 한 IP/계정으로 보내므로, IP·사용자명으로 세면
    고객 전원이 한 바구니를 나눠 쓴다(`app.extension_limiter` 의 기본 키 함수가 그렇다).
    키 ID 는 원문이 아니라 행 식별자라 저장소·로그에 남아도 키가 새지 않는다.
    """
    try:
        from aot.aot_flask.app import _raw_api_keys_from_request
        from aot.databases.models.user_api_key import UserAPIKey
        for raw_key in _raw_api_keys_from_request(request):
            row = UserAPIKey.find_active(raw_key)
            if row is not None:
                return 'consult-apikey:{}'.format(row.unique_id)
    except Exception as exc:
        logger.error("consult/parcel: 빈도 제한 키 계산 실패 (%s)", type(exc).__name__)
    name = getattr(flask_login.current_user, 'name', None)
    if name:
        return 'consult-user:{}'.format(name)
    return 'consult-ip:{}'.format(utils_general.get_ip_address() or '0.0.0.0')


def limit_consult_parcel(limiter, app):
    """`ConsultParcel` 뷰에 한도를 건다(`app.extension_limiter` 가 부른다).

    restx 리소스는 클래스라 데코레이터를 직접 못 얹으므로, 등록된 뷰 함수를 한도가 걸린 것으로
    **바꿔 끼운다.** (데코레이터가 돌려주는 함수를 버리면 한도가 걸리지 않는다 — 시험이 고정한다.)
    """
    from flask import jsonify
    from flask_limiter.errors import RateLimitExceeded

    for endpoint, view in list(app.view_functions.items()):
        if endpoint.endswith('.consult_consult_parcel'):
            limited = limiter.limit(parcel_rate_limit(), key_func=rate_limit_key)(view)

            @functools.wraps(view)
            def guarded(*args, **kwargs):
                # 한도 초과 예외를 여기서 받아 {ok, error} 모양으로 낸다. 밖으로 새면 restx(Api) 가 먼저
                # {"message": ...} 로 바꿔 버려 app 의 429 처리기에 닿지 않는다.
                try:
                    return limited(*args, **kwargs)
                except RateLimitExceeded as exc:
                    body = {'ok': False, 'error': 'rate_limited'}
                    retry_after = getattr(exc, 'retry_after', None)
                    if retry_after is not None:
                        body['retry_after'] = str(retry_after)
                    return jsonify(body), 429
            app.view_functions[endpoint] = guarded
            return True
    logger.warning("consult/parcel: 빈도 제한을 걸 뷰를 찾지 못했다")
    return False


def _fail(code):
    return {'ok': False, 'error': code}, ERROR_STATUS[code]


def lookup_parcel(address):
    """정리된 주소 → `(응답 dict, HTTP 상태)`. DB 를 쓰지 않는다.

    VWorld 키·도메인은 routes_geo_map 이 읽는 것과 같은 곳(등록된 `gis_vworld` GIS 입력)에서
    가져온다. 호출·필지 찾기는 `InputModule.parcel_from_address` 를 그대로 쓴다.
    """
    # 라우트 모듈은 늦게 import — api 패키지가 앱 조립 중에 라우트 모듈을 끌어오지 않게 한다.
    from aot.aot_flask.routes_geo_map import _get_vworld_credentials
    from aot.inputs_gis.gis_vworld import InputModule as VWorldInput

    try:
        api_key, domain = _get_vworld_credentials()
    except Exception as exc:
        # 예외 메시지·트레이스백을 남기지 않는다 — requests 예외 메시지에는 `key=` 가 든 URL 이 실린다.
        logger.error("consult/parcel: VWorld 키를 읽지 못했다 (%s)", type(exc).__name__)
        return _fail('vworld_unavailable')
    if not api_key:
        logger.warning("consult/parcel: 등록된 gis_vworld 입력이 없거나 api_key 가 비어 있다")
        return _fail('vworld_unavailable')

    try:
        result = VWorldInput.parcel_from_address(address, api_key, domain)
    except Exception as exc:
        logger.error("consult/parcel: 필지 조회 중 예외 (%s)", type(exc).__name__)   # 위와 같은 이유로 종류만
        return _fail('vworld_unavailable')

    if not isinstance(result, dict) or not result.get('ok'):
        if isinstance(result, dict) and result.get('upstream_failed'):
            logger.warning("consult/parcel: VWorld 호출이 모두 실패했다")
            return _fail('vworld_unavailable')
        return _fail('not_found')

    feature = result.get('feature')
    geometry = feature.get('geometry') if isinstance(feature, dict) else None
    centroid = centroid_lonlat(geometry)
    if centroid is None:
        return _fail('not_found')

    return {
        'ok': True,
        'feature': feature,
        'pnu': result.get('pnu') or (feature.get('properties') or {}).get('pnu') or '',
        'area_m2': round(polygon_area_m2(geometry), 1),
        'centroid': [round(centroid[0], 7), round(centroid[1], 7)],
        'address_normalized': result.get('name') or address,
    }, 200


@ns_consult.route('/parcel')
@ns_consult.doc(security='apikey', responses=default_responses)
class ConsultParcel(Resource):
    """Address → parcel polygon (read only)."""

    @flask_login.login_required
    def post(self):
        """
        Look up the parcel polygon for one address. Nothing is stored.

        Payload: `{"address": "..."}`
        Success: `{ok, feature, pnu, area_m2, centroid:[lon,lat], address_normalized}`
        Failure: `{ok:false, error: invalid_address | not_found | vworld_unavailable}`
        """
        if not utils_general.user_has_permission('view_settings', silent=True):
            return {'ok': False, 'error': 'forbidden'}, 403

        payload = request.get_json(silent=True)
        address = normalize_address(payload.get('address')) if isinstance(payload, dict) else None
        if address is None:
            return _fail('invalid_address')

        return lookup_parcel(address)
