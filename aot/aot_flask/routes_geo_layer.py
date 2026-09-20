# coding=utf-8
"""routes_geo 의 WMS·타일·오버레이 이미지·/geo/layer 라우트. blueprint 는 routes_geo 것을 공유한다."""
from flask import render_template, redirect, url_for, current_app, request, jsonify, Response, g
import requests
from datetime import datetime
import json
import os
import time
import threading
from flask_login import login_required
from flask_babel import gettext as _
from aot.aot_flask.utils import utils_general
from aot.aot_flask.utils import utils_http
from aot.databases.models import GeoSetting, GeoLayer, Input
from aot.aot_flask.extensions import db, cache
from aot.utils.inputs import parse_input_information
from aot.aot_flask.forms import forms_geo
from aot.aot_flask.utils import utils_geo
from aot.aot_flask.access import scope
from aot.aot_flask.routes_geo import blueprint  # noqa: E402



# WMS layer info cache: avoids parse_input_information() + module load per tile
_wms_layer_info_cache = {}  # {unique_id: (base_url, leaflet_opts, expires_at)}
_WMS_LAYER_INFO_TTL = 60.0


def _get_wms_layer_info(unique_id):
    """Return (base_url, leaflet_opts) for a WMS layer, with per-process TTL cache.
    Avoids calling parse_input_information() + load_module_from_file() on every tile."""
    import re as _re
    import time as _time
    import json as _json
    from aot.utils.inputs import parse_input_information
    from aot.utils.modules import load_module_from_file
    from aot.aot_flask.utils.utils_geo import MockInputDev

    now = _time.time()
    cached = _wms_layer_info_cache.get(unique_id)
    if cached and now < cached[2]:
        return cached[0], cached[1]

    channel_id = None
    layer = GeoLayer.query.filter_by(unique_id=unique_id).first()
    if not layer:
        m = _re.match(r'^(.+)_(\d+)$', unique_id)
        if m:
            base_uid, channel_id = m.group(1), int(m.group(2))
            layer = GeoLayer.query.filter_by(unique_id=base_uid).first()
    if not layer:
        return None, None

    dict_inputs = parse_input_information()
    layer_def = dict_inputs.get(layer.type, {})
    if not layer_def.get('file_path'):
        return None, None

    mod, _ = load_module_from_file(layer_def['file_path'], 'inputs')
    if not mod or not hasattr(mod, 'InputModule'):
        return None, None

    inst = mod.InputModule(MockInputDev(layer))

    if channel_id is not None:
        try:
            saved_opts = _json.loads(layer.options) if layer.options else {}
        except Exception:
            saved_opts = {}
        saved_opts['active_channels'] = [channel_id]
        inst.custom_options = saved_opts
        inst.get_custom_option = lambda opt, default=None: saved_opts.get(opt, default)

    base_url = inst.get_url()
    leaflet_opts = inst.get_leaflet_options()

    _wms_layer_info_cache[unique_id] = (base_url, leaflet_opts, now + _WMS_LAYER_INFO_TTL)
    return base_url, leaflet_opts

# ---------------------------------------------------------------------------
# 오버레이지도 타일 캐시 정책
# ---------------------------------------------------------------------------
# 화면 회전(세로↔가로)은 뷰포트 종횡비를 바꿔 MapLibre 가 새 타일 집합을 요구하게
# 만든다. 그것 자체는 정상인데, 예전 헤더(`max-age=300`)로는 5분만 지나면 이미
# 받았던 타일까지 **전량 재다운로드**됐다 — ETag 도 없어 304 재검증조차 불가능해
# 조건부 요청으로 아낄 여지가 아예 없었다. 실측(로컬, ISRIC SoilGrids 타일 1장):
#   첫 요청 1,739ms / 27,012바이트   ↔   캐시 적중 5ms / 0바이트
# 회전 한 번에 타일 10여 장이면 그 차이가 그대로 체감 지연이 된다.
#
# 게다가 MapLibre 의 `refreshExpiredTiles`(기본 켜짐)는 응답의 `max-age` 를 읽어
# **타일마다 만료 타이머**를 건다(maplibre-gl 4.1.2 `_setTileReloadTimer`). 즉
# 300초짜리 헤더는 아무도 지도를 만지지 않아도 5분마다 오버레이 전체를 다시 받게
# 한다. 헤더를 길게 주는 것은 캐시 정책이자 그 타이머를 끄는 수단이기도 하다.
#
# **상류 헤더를 그대로 따르지 않는다.** ISRIC 은 정적 데이터셋(SoilGrids, 2020)에
# `cache-control: max-age=0, must-revalidate, no-cache, no-store` 를 보낸다
# (2026-08-13 실측) — MapServer 기본값일 뿐 "자주 바뀐다"는 뜻이 아니다. 그대로
# 따르면 캐시가 통째로 무력화되므로, 캐시 수명은 프록시가 스스로 정한다.
_WMS_TILE_TTL = 86400          # 브라우저 캐시 수명(초). 토양도·지적도는 정적이다.
_WMS_TILE_SERVER_TTL = 604800  # 서버 캐시 수명(초). 브라우저가 비어도 상류 왕복 회피.

# NASA GIBS / 네이버 / 카카오 타일 프록시(`/api/geo/tile_proxy`)의 수명.
# **여기는 WMS 처럼 늘리면 안 된다.** GIBS 는 `date_mode='default'` 일 때 URL 의
# 시간 자리가 문자열 `default`(= NASA 최신 가용 데이터)로 남는다 — URL 은 그대로인데
# 그림은 매일 바뀐다. 하루짜리 캐시는 어제 데이터를 하루 더 보여준다는 뜻이다.
# 1시간이면 회전·새로고침 비용은 이미 전부 사라지고(그 간격은 초·분 단위다)
# 시간축 레이어의 신선도도 지킨다. 서버 캐시도 같은 값을 쓴다.
_TILE_PROXY_TTL = 3600

# 시간에 따라 변하는 WMS(기상 등)를 붙일 때를 위한 탈출구. 입력 모듈이
# `get_leaflet_options()` 에 이 키를 넣으면 그 레이어만 짧은 수명을 갖는다.
_WMS_TTL_OPTION_KEYS = ('cache_seconds', 'cacheSeconds', 'cache_max_age')


_tile_cache_lock = threading.Lock()
_tile_cache_store = [None]


def _tile_cache():
    """오버레이지도 타일 전용 파일 캐시(프로세스 간 공유).

    **앱 공용 `cache` 를 쓰지 않는 이유**: 그쪽은 `threshold=500`(cachelib 기본)
    이고 site_summary 같은 짧은 항목이 함께 산다. 27KB 짜리 타일 수백 장이
    같은 저장소에 들어가면 넘칠 때마다 그 항목들까지 함께 잘려나간다 — 타일을
    아끼려다 남의 캐시를 밀어내는 셈이다. 그래서 디렉터리와 정원을 따로 둔다.

    **정원(threshold)을 크게 잡지 말 것 — `/tmp` 는 tmpfs, 즉 RAM 이다.**
    (배포 서버 실측 2026-08-13: `tmpfs 3.8G /tmp`.) 타일 한 장이 5~30KB 이므로
    800장이면 최대 20MB 남짓이고, 이는 라즈베리파이급 장비의 tmpfs 에서도
    안전한 크기다. 넉넉하기도 하다 — 폰 화면 하나가 한 줌(약 15장)이고
    줌 단계를 오가도 레이어당 수십 장이다. SD 카드 마모를 피하려고 디스크가
    아니라 `/tmp` 를 쓰는 것은 앱 공용 캐시(`/tmp/aot_flask_cache`)와 같은 선택이다.

    지연 생성인 이유는 디렉터리 만들기를 import 시점에 하지 않기 위해서다
    (테스트·CLI 가 이 모듈만 import 할 때 파일시스템을 건드리지 않는다).
    """
    if _tile_cache_store[0] is None:
        with _tile_cache_lock:
            if _tile_cache_store[0] is None:
                from cachelib import FileSystemCache
                _tile_cache_store[0] = FileSystemCache(
                    '/tmp/aot_geo_tile_cache',
                    threshold=800,
                    default_timeout=_WMS_TILE_SERVER_TTL)
    return _tile_cache_store[0]


def _tile_cache_key(base_url, params):
    """상류 요청(=타일 내용)을 그대로 식별하는 키.

    요청 URL 이 아니라 **상류 파라미터**로 키를 만든다. 레이어 설정이 바뀌면
    (LAYERS·STYLES·FORMAT 등) 같은 BBOX 라도 다른 그림이 나오는데, URL 로만
    키를 잡으면 설정 변경 후에도 옛 그림이 계속 나온다.
    """
    import hashlib as _hashlib
    payload = json.dumps([base_url, sorted((str(k), str(v)) for k, v in params.items())],
                         ensure_ascii=False)
    return 'geotile:' + _hashlib.sha1(payload.encode('utf-8')).hexdigest()


def _tile_cache_get(base_url, params):
    """`(bytes, content_type)` 또는 미적중 시 None. 캐시 장애는 미적중과 같다."""
    try:
        hit = _tile_cache().get(_tile_cache_key(base_url, params))
    except Exception:
        return None
    if isinstance(hit, (tuple, list)) and len(hit) == 2 and isinstance(hit[0], bytes):
        return (hit[0], hit[1])
    return None


def _tile_cache_set(base_url, params, value, timeout=None):
    """타일을 서버 캐시에 넣는다. 실패해도 요청은 정상 처리된다(캐시는 보조수단)."""
    try:
        _tile_cache().set(_tile_cache_key(base_url, params), value,
                          timeout=timeout or _WMS_TILE_SERVER_TTL)
    except Exception:
        pass


def _wms_tile_ttl(leaflet_opts):
    """레이어별 타일 캐시 수명(초). 미지정이면 `_WMS_TILE_TTL`.

    상류가 정적 데이터에도 `no-store` 를 보내는 경우가 있어(위 주석) 상류 헤더는
    보지 않는다. 대신 레이어 자신이 값을 선언하면 그것을 따른다.
    """
    for key in _WMS_TTL_OPTION_KEYS:
        raw = (leaflet_opts or {}).get(key)
        if raw in (None, '', False):
            continue
        try:
            ttl = int(raw)
        except (TypeError, ValueError):
            continue
        if ttl > 0:
            return ttl
    return _WMS_TILE_TTL


# Minimal 1×1 transparent PNG — returned by the WMS proxy when the upstream
# WMS server responds with an XML/HTML service exception so that MapLibre can
# decode the tile without triggering "source image could not be decoded" errors.
_TRANSPARENT_1X1_PNG = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
    b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)

@blueprint.route('/api/geo/layer_secrets', methods=['GET'])
@login_required
def api_geo_layer_secrets():
    """요청한 지도 레이어의 완성 URL·키를 돌려준다 — **켤 때 그것만**.

    페이지에 실리는 레이어 목록에서는 키가 `{api_key}` 로 지워져 있다
    (utils_geo.mask_layer_secrets). 사용자가 레이어를 실제로 켜는 순간
    화면이 이 통로로 그 레이어의 값만 받아 채운다.

    `ids` 는 레이어 id 를 쉼표로 이은 목록이다. 한 번에 12개까지만 받는다 —
    목록 전체를 한 요청으로 긁어 예전 상태로 되돌리는 길을 막는다.
    """
    raw = (request.args.get('ids') or '').strip()
    ids = [i.strip() for i in raw.split(',') if i.strip()][:12]
    if not ids:
        return jsonify({'ok': False, 'message': 'missing ids'}), 400

    try:
        secrets = utils_geo.resolve_layer_secrets(ids)
    except Exception as e:
        current_app.logger.error(f"[Geo] layer_secrets failed: {e}")
        return jsonify({'ok': False, 'message': 'error'}), 500

    resp = jsonify({'ok': True, 'layers': secrets})
    # 프록시·브라우저 어디에도 남기지 않는다.
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    return resp

@blueprint.route('/api/geo/overlays/list', methods=['GET'])
@login_required
def api_geo_overlays_list():
    """지도 하나의 도형을 GeoJSON 으로 돌려준다.

    `get_overlays()` 는 `(FeatureCollection, error)` 튜플을 돌려주고 첫 인자로
    `map_uuid` 를 요구한다. 예전 호출은 인자 없이 불러 **항상** TypeError →
    500 이었다(2026-09-17 E2E 라우트 스모크가 처음 잡음). 필터 인자도 정의된
    대로 받아서 넘긴다.
    """
    from aot.aot_flask.geo.geo_overlays import GeoOverlayManager

    collection, error = GeoOverlayManager.get_overlays(
        request.args.get('map_uuid'),
        target_type=request.args.get('target_type'),
        parent_id=request.args.get('parent_id'),
        device_id=request.args.get('device_id'))
    if error:
        return jsonify({'ok': False, 'error': str(error)}), 500
    return jsonify(collection)

@blueprint.route('/api/geo/overlays/delta', methods=['POST'])
@login_required
def api_geo_overlays_delta():
    """Efficient Delta Save for individual features"""
    from aot.aot_flask.geo.geo_overlays import GeoOverlayManager

    # 이 경로에는 원래 **역할 검사조차 없었다**(로그인만 확인). 도형을
    # upsert/delete 하므로 실질적으로 쓰기 경로다 — 스코프를 붙이는 김에
    # 역할 검사도 함께 세운다. 스코프만 붙이면 그룹을 쓰지 않는 설치에서는
    # 여전히 아무나 도형을 고칠 수 있다.
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

    data = request.get_json() or {}
    if not scope.can_operate('geo_map', data.get('map_uuid')):
        return jsonify({'ok': False, 'message': scope.deny_message()}), 403

    result, error = GeoOverlayManager.save_delta(data)
    
    if error:
        return jsonify({'ok': False, 'message': error}), 500
        
    return jsonify(result)

@blueprint.route('/api/geo/generate-pipes', methods=['POST'])
@login_required
def api_geo_generate_pipes():
    """
    Generate Branch Pipes on the Backend for stability.
    Payload: { parent_feature, ref_line, config, map_uuid }
    """
    from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
    
    data = request.get_json()
    result, error = GeoOverlayManager.generate_pipes(data)
    
    if error:
        return jsonify({'ok': False, 'message': error}), 500
        
    return jsonify(result)


# ---------------------------------------------------------------------------
# [New] GIS Proxy Routes (Specific)
# ---------------------------------------------------------------------------

@blueprint.route('/api/geo/proxy/rainviewer/meta', methods=['GET'])
@login_required
@cache.cached(timeout=300, query_string=True, unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_rainviewer_meta():
    """
    Proxy RainViewer Metadata to avoid client-side CORS/Network issues.
    [Update 2026-02-21] RainViewer public API v2 has been largely discontinued by upstream.
    Returning 404 or empty data gracefully if upstream is down.
    """
    try:
        url = 'https://api.rainviewer.com/public/weather-maps.json'
        # Short timeout: (connect=1s, read=2s) so NGINX never sees a 504.
        resp = requests.get(url, timeout=(1, 2), verify=False)

        if resp.status_code != 200:
            g._proxy_error = True
            current_app.logger.warning(f'[RainViewer Meta] Upstream {resp.status_code}')
            return jsonify({'radar': {'past': [], 'nowcast': []}}), 200

        return jsonify(resp.json())
    except requests.exceptions.Timeout:
        g._proxy_error = True
        current_app.logger.warning('[RainViewer Meta] Upstream timeout')
        return jsonify({'radar': {'past': [], 'nowcast': []}}), 200
    except Exception as e:
        g._proxy_error = True
        current_app.logger.warning(f'[RainViewer Meta] Error: {e}')
        return jsonify({'radar': {'past': [], 'nowcast': []}}), 200

@blueprint.route('/api/geo/proxy/isric', methods=['GET'])
@login_required
# Cache only successful responses (exclude errors)
@cache.cached(timeout=300, query_string=True, unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_isric():
    """
    Proxy for ISRIC SoilGrids API to avoid CORS.
    Pass query params: lon, lat, property, depth, value
    """
    import traceback
    try:
        # Whitelisted params to forward
        params = {k: v for k, v in request.args.items() if k in ['lon', 'lat', 'property', 'depth', 'value']}

        # Validations
        if not params.get('lon') or not params.get('lat'):
            return jsonify({'error': 'Missing coordinates'}), 400

        # Round to 4 decimal places (~11m) to reduce ISRIC upstream load
        try:
            params['lat'] = round(float(params['lat']), 4)
            params['lon'] = round(float(params['lon']), 4)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid coordinates'}), 400

        url = 'https://rest.isric.org/soilgrids/v2.0/properties/query'

        # SoilGrids is a slow upstream; allow a long read timeout (30s) but a short
        # connect timeout (5s) so genuinely unreachable hosts still fail fast.
        try:
            resp = requests.get(url, params=params, timeout=(5, 30), verify=True)
        except requests.exceptions.SSLError:
            resp = requests.get(url, params=params, timeout=(5, 30), verify=False)

        if resp.status_code != 200:
            g._proxy_error = True
            current_app.logger.error(f"[ISRIC Proxy] Upstream {resp.status_code}: {resp.text[:200]}")
            return jsonify({'error': f"Upstream error: {resp.status_code}", 'detail': resp.text[:200]}), resp.status_code

        try:
            data = resp.json()
        except Exception:
            g._proxy_error = True
            current_app.logger.error(f"[ISRIC Proxy] Non-JSON response: {resp.text[:200]}")
            return jsonify({'error': 'Invalid JSON from upstream', 'detail': resp.text[:200]}), 502

        return jsonify(data)

    except requests.exceptions.ConnectionError as e:
        g._proxy_error = True
        current_app.logger.error(f"[ISRIC Proxy] Connection failed: {e}")
        return jsonify({'error': 'connection_failed', 'detail': str(e)}), 502
    except requests.exceptions.Timeout:
        g._proxy_error = True
        current_app.logger.error("[ISRIC Proxy] Request timed out")
        return jsonify({'error': 'timeout'}), 504
    except Exception as e:
        g._proxy_error = True
        current_app.logger.error(f"[ISRIC Proxy] Error: {e}\n{traceback.format_exc()}")
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500

@blueprint.route('/api/geo/proxy/openweather', methods=['GET'])
@login_required
@cache.cached(timeout=300, query_string=True, unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_openweather():
    """OpenWeatherMap 현재날씨 프록시 — **키는 서버가 찾는다.**

    예전에는 `appid` 를 쿼리로 받아 그대로 상류에 넘겼다. 키를 감추려고 둔
    통로인데 키가 클라이언트에서 왔으니 감추는 것이 하나도 없었고, 그 URL 이
    브라우저 방문기록·프록시 로그에 그대로 남았다. 바로 아래 KMA 프록시는
    처음부터 `input_id` 만 받아 서버에서 키를 찾는다 — 그 방식으로 맞춘다.

    `appid` 가 와도 무시한다(옛 캐시 페이지 호환). 키 출처는 두 곳:
    레이어별 옵션(`input_id` 로 지정) → 전역 GeoSetting.keys['owm'].
    """
    try:
        lat = request.args.get('lat')
        lon = request.args.get('lon')
        units = request.args.get('units', 'metric')
        input_id = request.args.get('input_id', '')

        if not lat or not lon:
            return jsonify({'error': 'Missing lat/lon parameters'}), 400

        api_key = ''
        if input_id:
            layer = GeoLayer.query.filter_by(unique_id=input_id).first()
            if layer and layer.options:
                try:
                    api_key = (json.loads(layer.options) or {}).get('api_key', '')
                except Exception:
                    api_key = ''
        if not api_key:
            api_key = utils_geo.global_map_key('owm')

        if not api_key:
            g._proxy_error = True
            return jsonify({'error': 'OpenWeatherMap API key not configured'}), 400

        url = 'https://api.openweathermap.org/data/2.5/weather'
        resp = requests.get(
            url, params={'lat': lat, 'lon': lon, 'units': units, 'appid': api_key},
            timeout=5)

        if resp.status_code != 200:
             g._proxy_error = True
             return jsonify({'error': f"Upstream error: {resp.status_code}"}), 502

        return jsonify(resp.json())
    except Exception as e:
        g._proxy_error = True
        current_app.logger.error(f"OpenWeather Proxy Error: {e}")
        return jsonify({'error': str(e)}), 500

@blueprint.route('/api/geo/proxy/kma', methods=['GET'])
@login_required
@cache.cached(timeout=300, query_string=True, unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_kma():
    """
    Proxy for KMA API Hub (apihub.kma.go.kr) sfc_nc_var.php — kma_weather_500 input과 동일한 API.
    input_id로 GeoLayer의 authKey를 조회해 요청한다.
    """
    import datetime as _dt

    try:
        lat = request.args.get('lat')
        lon = request.args.get('lon')
        input_id = request.args.get('input_id', '')

        if not lat or not lon:
            return jsonify({'error': 'Missing lat/lon parameters'}), 400

        try:
            lat_f = float(lat)
            lon_f = float(lon)
        except ValueError:
            return jsonify({'error': 'Invalid lat/lon'}), 400

        # GeoLayer에서 authKey 조회
        api_key = ''
        if input_id:
            layer = GeoLayer.query.filter_by(unique_id=input_id).first()
            if layer and layer.options:
                try:
                    opts = json.loads(layer.options)
                    api_key = opts.get('api_key', '')
                except Exception:
                    pass

        if not api_key:
            g._proxy_error = True
            return jsonify({'error': 'KMA API key not configured'}), 400

        # kma_weather_500과 동일: 5분 윈도우, KST naive datetime
        now_kst = _dt.datetime.utcnow() + _dt.timedelta(hours=9)
        tm2 = now_kst.strftime('%Y%m%d%H%M')
        tm1 = (now_kst - _dt.timedelta(minutes=5)).strftime('%Y%m%d%H%M')

        url = (
            'https://apihub.kma.go.kr/api/typ01/url/sfc_nc_var.php'
            f'?tm1={tm1}&tm2={tm2}&lon={lon_f}&lat={lat_f}'
            f'&obs=ta,hm,wd_10m,ws_10m,pa,rn_ox,rn_15m,vs,sd_tot'
            f'&itv=5&help=0&authKey={api_key}'
        )
        resp = requests.get(url, timeout=30)

        if resp.status_code != 200:
            g._proxy_error = True
            current_app.logger.error(f'[KMA Proxy] upstream {resp.status_code}: {resp.text[:300]}')
            return jsonify({
                'error': f'KMA upstream HTTP {resp.status_code}',
                'kma_body': resp.text[:300]
            }), 200

        if 'error' in resp.text[:200].lower():
            g._proxy_error = True
            current_app.logger.error(f'[KMA Proxy] API error in body: {resp.text[:200]}')
            return jsonify({'error': 'KMA API error', 'kma_body': resp.text[:200]}), 200

        # CSV 파싱 (kma_weather_500.pre_fetch_data와 동일 로직).
        # KMA는 미보고 관측값을 -999로 채워 보낸다 — 그대로 float으로 받으면
        # -999가 실측값(예: 기온 -999°C)으로 표시된다(kma_weather_500.py에서
        # 겪은 것과 동일한 문제). -900 이하를 결측으로 간주해 버린다.
        _fields = ['ta', 'hm', 'wd_10m', 'ws_10m', 'pa', 'rn_ox', 'rn_15m', 'vs', 'sd_tot']
        _MISSING_SENTINEL_MAX = -900.0

        def _to_float_or_none(v):
            try:
                v = str(v).strip()
                if v == '' or v.lower() == 'nan':
                    return None
                val = float(v)
                if val <= _MISSING_SENTINEL_MAX:
                    return None
                return val
            except Exception:
                return None

        best_ts = None
        result = {}
        for line in resp.text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            cols = [c.strip() for c in line.split(',')]
            if len(cols) != 10:
                continue
            ts = cols[0]
            if len(ts) != 12:
                continue
            try:
                if float(cols[1]) == 0.0 and float(cols[2]) == 0.0 and float(cols[5]) == 0.0:
                    continue
            except Exception:
                pass
            row = {field: _to_float_or_none(cols[i]) for i, field in enumerate(_fields, 1)}
            # 전 필드가 -999/결측이면 이 행은 버리고 더 이전의 유효한 행을
            # 채택한다 — 안 그러면 최신 타임스탬프가 결측행이어도 그대로
            # 선택되어 표시할 값이 하나도 안 남는다.
            if all(val is None for val in row.values()):
                continue
            if best_ts is None or ts > best_ts:
                best_ts = ts
                result = row

        if not best_ts:
            return jsonify({'error': 'No valid data in KMA response'}), 200

        return jsonify(result)

    except Exception as e:
        g._proxy_error = True
        current_app.logger.error(f"KMA Proxy Error: {e}")
        return jsonify({'error': str(e)}), 500


# Failed upstream calls are not cached by flask-caching (unless=_proxy_error),
# so while open-meteo is unreachable every legend refresh repeats the full
# requests timeout and pins a gunicorn thread. Remember recent failures per
# query string and short-circuit until the cooldown expires.
_openmeteo_fail_until = {}
OPENMETEO_FAIL_COOLDOWN_SEC = 60


@blueprint.route('/api/geo/proxy/openmeteo', methods=['GET'])
@login_required
@cache.cached(timeout=300, query_string=True, unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_openmeteo():
    """
    Proxy for Open-Meteo API (Used by NASA GIBS legends).
    """
    fail_key = request.query_string.decode('utf-8', 'ignore')
    try:
        # Whitelisted params
        # OpenMeteo uses 'latitude', 'longitude', 'current', 'hourly', 'daily', etc.
        params = request.args.to_dict()

        if not params.get('latitude') or not params.get('longitude'):
             return jsonify({'error': 'Missing coordinates'}), 400

        if _openmeteo_fail_until.get(fail_key, 0) > time.time():
            g._proxy_error = True
            return jsonify({'error': 'Upstream cooldown'}), 200

        # Base URL
        url = 'https://api.open-meteo.com/v1/forecast'

        # [Fix] SSL verification disabled for server environments with certificate issues
        resp = requests.get(url, params=params, timeout=3, verify=False)
        
        if resp.status_code != 200:
            g._proxy_error = True
            _openmeteo_fail_until[fail_key] = time.time() + OPENMETEO_FAIL_COOLDOWN_SEC
            current_app.logger.warning(f'[OpenMeteo Proxy] Upstream {resp.status_code}')
            # Return 200 so the browser doesn't log a network error; the legend
            # value-box JS handles missing fields by showing "--".
            return jsonify({'error': f'Upstream error: {resp.status_code}'}), 200

        # [Fix] Handle JSON parsing errors gracefully
        try:
            return jsonify(resp.json())
        except Exception as je:
            g._proxy_error = True
            _openmeteo_fail_until[fail_key] = time.time() + OPENMETEO_FAIL_COOLDOWN_SEC
            current_app.logger.error(f"OpenMeteo JSON parse error: {je}, response: {resp.text[:200]}")
            return jsonify({'error': 'Failed to parse response'}), 200
    except requests.exceptions.Timeout:
        g._proxy_error = True
        _openmeteo_fail_until[fail_key] = time.time() + OPENMETEO_FAIL_COOLDOWN_SEC
        current_app.logger.error("OpenMeteo Proxy Timeout")
        return jsonify({'error': 'Upstream timeout'}), 200
    except Exception as e:
        g._proxy_error = True
        _openmeteo_fail_until[fail_key] = time.time() + OPENMETEO_FAIL_COOLDOWN_SEC
        current_app.logger.error(f"OpenMeteo Proxy Error: {e}")
        return jsonify({'error': str(e)}), 200

@blueprint.route('/api/geo/proxy/rainviewer/timestamps', methods=['GET'])
@login_required
@cache.cached(timeout=300, query_string=True, unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_rainviewer_timestamps():
    """
    Proxy for RainViewer Radar Timestamps API.
    Returns list of available radar timestamps for animation.
    Cache: 5 minutes (300s) TTL.
    Upstream: https://api.rainviewer.com/v2/radar/timestamps.json
    """
    try:
        url = 'https://api.rainviewer.com/v2/radar/timestamps.json'
        resp = requests.get(url, timeout=10, verify=False)

        if resp.status_code != 200:
            g._proxy_error = True
            current_app.logger.warning(f"RainViewer Timestamps API error: {resp.status_code}")
            return jsonify({
                'error': 'RainViewer service unavailable',
                'status': resp.status_code,
                'timestamps': []
            }), 502

        try:
            data = resp.json()
            # Ensure timestamps array exists
            if not isinstance(data, list):
                data = {'timestamps': data.get('timestamps', []) or [], 'version': data.get('version', 'v2')}
            return jsonify({'ok': True, 'timestamps': data if isinstance(data, list) else data.get('timestamps', []), 'version': data.get('version', 'v2') if isinstance(data, dict) else 'v2'})
        except Exception as je:
            g._proxy_error = True
            current_app.logger.error(f"RainViewer JSON parse error: {je}")
            return jsonify({'ok': False, 'error': 'Failed to parse response', 'timestamps': []}), 500

    except requests.exceptions.Timeout:
        g._proxy_error = True
        current_app.logger.error("RainViewer Proxy Timeout")
        return jsonify({'ok': False, 'error': 'Upstream timeout', 'timestamps': []}), 504
    except Exception as e:
        g._proxy_error = True
        current_app.logger.error(f"RainViewer Proxy Error: {e}")
        return jsonify({'ok': False, 'error': str(e), 'timestamps': []}), 500

# ---------------------------------------------------------------------------
# [New] GIS Proxy Routes (Generic)
# ---------------------------------------------------------------------------

@blueprint.route('/api/geo/proxy/wms/<unique_id>', methods=['GET'])
@login_required
def api_geo_proxy_wms(unique_id):
    """
    Server-side WMS tile proxy.

    Fetches a WMS GetMap tile on behalf of the browser to bypass CORS restrictions
    on third-party WMS services (e.g. VWorld) that do not send CORS headers.

    MapLibre uses this URL template:
        /api/geo/proxy/wms/<unique_id>?BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256

    캐시는 두 겹이다(정책 근거는 파일 상단 `_WMS_TILE_TTL` 주석):
      - 서버: `_tile_cache` — 브라우저 캐시가 비어도 상류 왕복(실측 1.7초)을 피한다.
      - 브라우저: `utils_http.tile_conditional()` 이 다는 장기 `max-age` + ETag.

    **`@cache.cached` 를 다시 붙이지 말 것.** 그 데코레이터는 뷰가 돌려준 응답을
    그대로 캐시하는데, 이 뷰는 `If-None-Match` 가 맞으면 **304** 를 돌려준다 —
    그 304 가 캐시되면 ETag 를 보내지 않은 다음 사람이 본문 없는 304 를 받아
    타일이 영영 안 뜬다. 그래서 캐시 대상은 응답이 아니라 **타일 바이트**다.
    """
    try:
        base_url, leaflet_opts = _get_wms_layer_info(unique_id)
        if base_url is None:
            return Response('Layer not found or not configured', status=404)

        bbox = request.args.get('BBOX', '')
        width = request.args.get('WIDTH', '256')
        height = request.args.get('HEIGHT', '256')

        if not bbox:
            return Response('Missing BBOX parameter', status=400)

        wms_params = {
            'SERVICE': 'WMS',
            'REQUEST': 'GetMap',
            'VERSION': leaflet_opts.get('version', '1.3.0'),
            'LAYERS': leaflet_opts.get('layers', ''),
            'STYLES': leaflet_opts.get('styles', ''),
            'FORMAT': leaflet_opts.get('format', 'image/png'),
            'TRANSPARENT': 'TRUE' if leaflet_opts.get('transparent', True) else 'FALSE',
            'WIDTH': width,
            'HEIGHT': height,
            'BBOX': bbox,
        }

        if wms_params['VERSION'].startswith('1.3'):
            wms_params['CRS'] = 'EPSG:3857'
        else:
            wms_params['SRS'] = 'EPSG:3857'

        _WMS_STANDARD = {
            'service', 'request', 'version', 'layers', 'styles', 'format',
            'transparent', 'width', 'height', 'bbox', 'crs', 'srs',
        }
        for k, v in leaflet_opts.items():
            if k.lower() not in _WMS_STANDARD and v not in (None, '', False):
                wms_params[k] = v

        cached = _tile_cache_get(base_url, wms_params)
        if cached is None:
            resp = requests.get(base_url, params=wms_params, timeout=15,
                                headers={'Referer': request.host_url})

            content_type = resp.headers.get('Content-Type', 'image/png')
            if resp.status_code != 200 or 'xml' in content_type or 'html' in content_type:
                current_app.logger.warning(
                    f'[WMS Proxy] Upstream error {resp.status_code} for {unique_id}: {resp.text[:200]}'
                )
                # 실패는 캐시하지 않는다 — 상류가 잠깐 흔들린 것을 몇 시간짜리
                # 빈 타일로 굳혀 버리면 복구가 사용자 눈에는 영영 안 온다.
                return Response(
                    _TRANSPARENT_1X1_PNG,
                    status=200,
                    content_type='image/png',
                    headers={'Cache-Control': 'no-cache'}
                )

            cached = (resp.content, content_type)
            _tile_cache_set(base_url, wms_params, cached)

        return utils_http.tile_conditional(
            request, cached[0], cached[1], _wms_tile_ttl(leaflet_opts))

    except Exception as e:
        # Even if the upstream WMS (e.g. maps.isric.org) is slow or unresponsive and
        # raises an exception (timeout, etc.), do not throw a 500. Otherwise MapLibre
        # endlessly re-requests the tile, flooding the console and obscuring other
        # working overlays. Just like a non-200 response, gracefully degrade with a
        # transparent tile (200) — only the overlay is blank while the map keeps working.
        current_app.logger.warning(f'[WMS Proxy] Exception for {unique_id}: {e}')
        return Response(
            _TRANSPARENT_1X1_PNG,
            status=200,
            content_type='image/png',
            headers={'Cache-Control': 'no-cache'}
        )


_OVERLAY_TILE_TTL = 600        # 날씨 오버레이는 자주 바뀐다 — 10분.


@blueprint.route('/api/geo/tile/<layer_id>/<int:z>/<int:x>/<int:y>', methods=['GET'])
@login_required
def api_geo_tile_xyz(layer_id, z, x, y):
    """키가 필요한 **오버레이** XYZ 타일을 서버가 대신 받아 온다.

    OpenWeatherMap 같은 오버레이는 타일 URL 에 키를 붙여야 해서, 브라우저가
    직접 받으면 키가 URL 에 실린다. 이 통로를 거치면 브라우저는 키를 모른 채
    타일만 받는다.

    **베이스맵은 여기로 보내지 않는다.** 베이스는 화면을 채우느라 한 번에
    수십 장이 오고, 그 전부가 gunicorn 워커를 지나가면 대시보드의 다른 요청이
    밀린다. 오버레이는 장수가 적어 그 비용이 작다(적용 범위는
    utils_geo.proxy_overlay_tile_urls 가 정한다).

    캐시는 WMS 프록시와 같은 두 겹이다 — 서버 `_tile_cache` + 브라우저 조건부
    캐시. 상류가 실패하면 투명 타일을 200 으로 돌려준다(재요청 폭주 방지).
    """
    try:
        url_tmpl = utils_geo.resolve_layer_upstream_url(layer_id)
        if not url_tmpl or url_tmpl.startswith('/api/geo/tile/'):
            return Response('Layer not found', status=404)

        url = (url_tmpl
               .replace('{z}', str(z))
               .replace('{x}', str(x))
               .replace('{y}', str(y))
               .replace('{-y}', str((1 << z) - 1 - y))
               .replace('{s}', 'a')
               .replace('{r}', ''))
        if '{' in url.split('?')[0]:
            # 아직 풀리지 않은 자리표시자가 남았다 — 상류를 부르면 404 만 받는다.
            return Response('Unresolved tile URL', status=400)

        cache_params = {'z': z, 'x': x, 'y': y}
        cached = _tile_cache_get(url, cache_params)
        if cached is None:
            resp = requests.get(url, timeout=8, headers={'Referer': request.host_url})
            content_type = resp.headers.get('Content-Type', 'image/png')
            if resp.status_code != 200 or 'image' not in content_type:
                current_app.logger.warning(
                    f'[Tile Proxy] Upstream {resp.status_code} for layer {layer_id}')
                return Response(_TRANSPARENT_1X1_PNG, status=200,
                                content_type='image/png',
                                headers={'Cache-Control': 'no-cache'})
            cached = (resp.content, content_type)
            _tile_cache_set(url, cache_params, cached, timeout=_OVERLAY_TILE_TTL)

        return utils_http.tile_conditional(
            request, cached[0], cached[1], _OVERLAY_TILE_TTL)
    except Exception as e:
        current_app.logger.warning(f'[Tile Proxy] Exception for {layer_id}: {e}')
        return Response(_TRANSPARENT_1X1_PNG, status=200, content_type='image/png',
                        headers={'Cache-Control': 'no-cache'})


# ---------------------------------------------------------------------------
# Sentinel Hub (Copernicus) proxy
# ---------------------------------------------------------------------------
# Sentinel Hub 는 OAuth2 client credentials 를 쓴다 — 타일 URL 에 키를 박는
# 방식(gis_openweather 등)을 그대로 따르면 client_secret 이 브라우저로 나간다.
# 그래서 타일도 값 조회도 서버가 대신 부르고, 자격증명은 서버 밖으로 나가지
# 않는다. 요청 본문·PU 비용의 근거는 `aot/inputs_gis/gis_sentinelhub.py` 상단.
_SH_TILE_TTL = 86400        # Sentinel-2 재방문이 5일이라 한 시간 캐시는 낭비다.
_SH_SETTINGS_TTL = 60.0
_sh_settings_cache = {}     # {unique_id: (settings, expires_at)}


def _load_gis_layer_instance(unique_id):
    """GeoLayer 하나를 그 입력 모듈 인스턴스로 만든다. 못 찾으면 None.

    api/geo.py 의 검색 프록시가 하던 것과 같은 조립(옵션 기본값 채우기 →
    전역 키 폴백 → `get_custom_option` 대체)을 한 곳에 모은 것이다.
    """
    import re as _re
    from aot.utils.modules import load_module_from_file
    from aot.aot_flask.utils.utils_geo import MockInputDev

    channel_id = None
    layer = GeoLayer.query.filter_by(unique_id=unique_id).first()
    if not layer:
        # WMS 프록시와 같은 관례: 채널마다 레이어를 나눠 그릴 때 `<uid>_<채널>`.
        m = _re.match(r'^(.+)_(\d+)$', unique_id)
        if m:
            layer = GeoLayer.query.filter_by(unique_id=m.group(1)).first()
            if layer:
                channel_id = int(m.group(2))
    if not layer:
        return None

    layer_def = parse_input_information().get(layer.type, {})
    if not layer_def.get('file_path'):
        return None

    mod, _status = load_module_from_file(layer_def['file_path'], 'inputs')
    if not mod or not hasattr(mod, 'InputModule'):
        return None

    try:
        opts = json.loads(layer.options) if layer.options else {}
    except Exception:
        opts = {}

    required_ids = []
    for opt_def in layer_def.get('custom_options', []):
        opt_id = opt_def.get('id')
        if not opt_id:
            continue
        if opt_id not in opts and 'default' in opt_def:
            opts[opt_id] = opt_def['default']
        if opt_def.get('required'):
            required_ids.append(opt_id)

    # 키 필드는 전역 키 저장소를 따른다(다른 GIS 입력과 같은 규칙).
    key_field = layer_def.get('key_field')
    if key_field and not opts.get(key_field):
        settings_row = GeoSetting.query.first()
        if settings_row and settings_row.keys:
            try:
                global_keys = json.loads(settings_row.keys)
            except Exception:
                global_keys = {}
            global_val = global_keys.get(layer_def.get('global_key_field', key_field))
            if global_val:
                opts[key_field] = global_val

    # 전역 저장소에는 키 필드 자리가 **하나뿐**이라 두 값짜리 자격증명
    # (예: Sentinel Hub 의 client_id + client_secret)은 절반만 채워진다.
    # 같은 종류의 다른 레이어에 이미 적어 둔 필수값을 물려받게 한다 —
    # 지수마다 레이어를 나눠 두는 것이 보통인데, 그때마다 같은 비밀값을
    # 다시 적게 하지 않기 위해서다.
    missing = [opt_id for opt_id in required_ids if not opts.get(opt_id)]
    if missing:
        for sibling in GeoLayer.query.filter_by(type=layer.type).all():
            if not missing:
                break
            if sibling.unique_id == layer.unique_id or not sibling.options:
                continue
            try:
                sib_opts = json.loads(sibling.options)
            except Exception:
                continue
            for opt_id in list(missing):
                if sib_opts.get(opt_id):
                    opts[opt_id] = sib_opts[opt_id]
                    missing.remove(opt_id)

    if channel_id is not None:
        opts['active_channels'] = [channel_id]

    inst = mod.InputModule(MockInputDev(layer))
    inst.custom_options = opts
    inst.get_custom_option = lambda opt, default=None: opts.get(opt, default)
    return inst


def _get_sentinelhub_settings(unique_id):
    """Sentinel Hub 조회에 필요한 설정 한 벌. 못 찾으면 None.

    `_get_wms_layer_info` 와 같은 이유로 TTL 캐시를 둔다 — 타일 한 장마다
    parse_input_information() 과 모듈 로드를 다시 할 이유가 없다.
    """
    now = time.time()
    cached = _sh_settings_cache.get(unique_id)
    if cached and now < cached[1]:
        return cached[0]

    inst = _load_gis_layer_instance(unique_id)
    if not inst or not hasattr(inst, 'request_settings'):
        return None

    settings = inst.request_settings()
    _sh_settings_cache[unique_id] = (settings, now + _SH_SETTINGS_TTL)
    return settings


def _sh_blank_tile():
    """상류가 실패했을 때의 빈 타일. WMS 프록시와 같은 이유로 캐시하지 않는다."""
    return Response(_TRANSPARENT_1X1_PNG, status=200, content_type='image/png',
                    headers={'Cache-Control': 'no-cache'})


@blueprint.route('/api/geo/proxy/sentinelhub/<unique_id>', methods=['GET'])
@login_required
def api_geo_proxy_sentinelhub(unique_id):
    """Sentinel Hub Process API 타일 프록시.

    `@cache.cached` 를 붙이지 않는 이유는 WMS 프록시와 같다 — 캐시 대상은
    응답이 아니라 타일 바이트다.
    """
    from aot.inputs_gis import gis_sentinelhub as sh

    try:
        try:
            z = int(request.args.get('z', ''))
            x = int(request.args.get('x', ''))
            y = int(request.args.get('y', ''))
        except (TypeError, ValueError):
            return Response('Missing or invalid z/x/y', status=400)

        if z < 0 or z > 22 or not (0 <= x < 2 ** z) or not (0 <= y < 2 ** z):
            return Response('Tile coordinates out of range', status=400)

        # 광역 뷰에서는 상류를 부르지 않는다 — 10m 자료를 대륙 단위로 받아 봐야
        # 화면에는 뭉개진 한 덩어리고 PU 만 나간다.
        if z < sh.MIN_ZOOM:
            return _sh_blank_tile()

        settings = _get_sentinelhub_settings(unique_id)
        if not settings:
            return Response('Layer not found or not configured', status=404)
        if not settings.get('client_id') or not settings.get('client_secret'):
            current_app.logger.warning(
                '[SentinelHub Proxy] credentials missing for %s', unique_id)
            return _sh_blank_tile()

        # 캐시 키에서 자격증명은 뺀다 — 그림을 정하는 것은 아니고, 디스크
        # 캐시 키에 비밀값을 섞을 이유도 없다. 나머지는 전부 그림을 바꾼다.
        cache_params = {
            'z': z, 'x': x, 'y': y,
            'channel': settings.get('channel_id'),
            'collection': settings.get('collection'),
            'cloud': settings.get('max_cloud'),
            'order': settings.get('mosaicking_order'),
            'from': settings.get('time_from'),
            'to': settings.get('time_to'),
        }
        cached = _tile_cache_get('sentinelhub', cache_params)

        if cached is None:
            png = sh.fetch_tile_png(settings, z, x, y, logger=current_app.logger)
            if not png:
                return _sh_blank_tile()
            cached = (png, 'image/png')
            _tile_cache_set('sentinelhub', cache_params, cached, timeout=_SH_TILE_TTL)

        return utils_http.tile_conditional(request, cached[0], cached[1], _SH_TILE_TTL)

    except Exception as e:
        current_app.logger.warning('[SentinelHub Proxy] Exception for %s: %s',
                                   unique_id, e)
        return _sh_blank_tile()


@blueprint.route('/api/geo/proxy/sentinelhub/<unique_id>/value', methods=['GET'])
@login_required
@cache.cached(timeout=900, query_string=True,
              unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_sentinelhub_value(unique_id):
    """좌표 한 점의 지수 통계(범례 숫자 상자·AI 조회용).

    실패해도 200 을 돌려준다 — 범례 값 상자는 필드가 없으면 '--' 를 보여주고,
    그림 자체는 타일 프록시가 따로 그린다.
    """
    from aot.inputs_gis import gis_sentinelhub as sh

    try:
        lat = float(request.args.get('lat', ''))
        lon = float(request.args.get('lon', ''))
    except (TypeError, ValueError):
        return jsonify({'error': 'Missing coordinates'}), 400

    try:
        settings = _get_sentinelhub_settings(unique_id)
        if not settings:
            g._proxy_error = True
            return jsonify({'error': 'Layer not configured'}), 200

        stats = sh.fetch_index_stats(settings, lat, lon, logger=current_app.logger)
        if not stats:
            g._proxy_error = True
            return jsonify({'error': 'No cloud-free observation in window'}), 200

        return jsonify({
            'index': stats['key'],
            'mean': round(stats['mean'], 3),
            'min': round(stats['min'], 3) if stats.get('min') is not None else None,
            'max': round(stats['max'], 3) if stats.get('max') is not None else None,
            'window_to': stats.get('interval_to'),
        })
    except Exception as e:
        g._proxy_error = True
        current_app.logger.warning('[SentinelHub Value] Exception for %s: %s',
                                   unique_id, e)
        return jsonify({'error': str(e)}), 200


# ---------------------------------------------------------------------------
# Agromonitoring proxy
# ---------------------------------------------------------------------------
# 필지 폴리곤의 토양 수분·지온·NDVI. 키가 브라우저로 나가지 않게 서버가
# 부르고, 무료 등급의 호출 한도가 공개돼 있지 않아 30분 캐시를 건다
# (`aot/inputs_gis/gis_agromonitoring.py` 상단 참조).
@blueprint.route('/api/geo/proxy/agromonitoring/<unique_id>', methods=['GET'])
@login_required
@cache.cached(timeout=1800, query_string=True,
              unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_agromonitoring(unique_id):
    """좌표를 담은 등록 필지의 값. 실패해도 200 — 범례는 '--' 로 남는다."""
    try:
        lat = float(request.args.get('lat', ''))
        lon = float(request.args.get('lon', ''))
    except (TypeError, ValueError):
        return jsonify({'error': 'Missing coordinates'}), 400

    try:
        inst = _load_gis_layer_instance(unique_id)
        if not inst or not hasattr(inst, 'get_data_at_location'):
            g._proxy_error = True
            return jsonify({'error': 'Layer not configured'}), 200

        data = inst.get_data_at_location(lat, lon)
        if not data:
            g._proxy_error = True
            return jsonify({'error': 'No registered polygon or no data'}), 200

        return jsonify(data)
    except Exception as e:
        g._proxy_error = True
        current_app.logger.warning('[Agromonitoring Proxy] Exception for %s: %s',
                                   unique_id, e)
        return jsonify({'error': str(e)}), 200


# ---------------------------------------------------------------------------
# GIS Tile Proxy Routes (Generic) - NASA GIBS tile proxy
# ---------------------------------------------------------------------------

@blueprint.route('/api/geo/tile_proxy', methods=['GET'])
@login_required
def api_geo_tile_proxy():
    """
    Generic tile proxy endpoint for NASA GIBS and other tile services.
    Receives target URL via query parameter and returns the tile image.
    
    Query Parameters:
        url: The target tile URL to proxy (required)
    """
    try:
        target_url = request.args.get('url')
        
        if not target_url:
            return Response("Missing 'url' parameter", status=400)
        
        # Validate URL to prevent SSRF
        if not target_url.startswith(('http://', 'https://')):
            return Response("Invalid URL protocol", status=400)
        
        # Only allow specific tile servers (SSRF guard)
        # Each entry: (domain_suffix, referer, origin)
        ALLOWED_TILE_SERVERS = [
            ('gibs.earthdata.nasa.gov', 'https://gibs.earthdata.nasa.gov/', 'https://gibs.earthdata.nasa.gov'),
            ('map.pstatic.net',         'https://map.naver.com/',            'https://map.naver.com'),
            ('daumcdn.net',             'https://map.kakao.com/',             'https://map.kakao.com'),
        ]

        from urllib.parse import urlparse
        parsed = urlparse(target_url)
        matched = next(
            (entry for entry in ALLOWED_TILE_SERVERS if parsed.netloc.endswith(entry[0])),
            None
        )

        if not matched:
            current_app.logger.warning(f'[Tile Proxy] Blocked unauthorized domain: {parsed.netloc}')
            return Response("Unauthorized tile server", status=403)

        _, referer, origin = matched
        headers = {
            'Referer': referer,
            'Origin': origin,
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/png,image/*,*/*;q=0.8',
            'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        }

        # 서버 캐시 먼저 — WMS 프록시와 같은 이유다(파일 상단 주석). 여기는
        # 원래 서버 캐시가 아예 없어서 회전·새로고침마다 상류로 나갔다.
        cache_params = {'url': target_url}
        cached = _tile_cache_get('tile_proxy', cache_params)

        if cached is None:
            # Fetch the tile
            import requests
            resp = requests.get(target_url, headers=headers, timeout=10)

            if resp.status_code != 200:
                current_app.logger.warning(f'[Tile Proxy] Non-200 status: {resp.status_code} for {target_url}')
                # 실패는 캐시하지 않는다 — 상류의 일시 장애를 굳히지 않기 위해서.
                return Response(
                    _TRANSPARENT_1X1_PNG,
                    status=200,
                    mimetype='image/png',
                    headers={'Cache-Control': 'no-cache'}
                )

            # Determine content type
            content_type = resp.headers.get('Content-Type', 'image/png')
            cached = (resp.content, content_type)
            _tile_cache_set('tile_proxy', cache_params, cached, timeout=_TILE_PROXY_TTL)

        return utils_http.tile_conditional(
            request, cached[0], cached[1], _TILE_PROXY_TTL)


    except requests.Timeout:
        current_app.logger.error(f'[Tile Proxy] Timeout for {target_url}')
        return Response("Tile request timeout", status=504)
    except requests.RequestException as e:
        current_app.logger.error(f'[Tile Proxy] Request failed: {e}')
        return Response(f"Proxy error: {str(e)}", status=502)
    except Exception as e:
        current_app.logger.error(f'[Tile Proxy] Exception: {e}')
        return Response(str(e), status=500)


def _geo_layer_get_custom_option(layer_obj, option_id):
    import json
    try:
        options = json.loads(layer_obj.options) if layer_obj.options else {}
        return options.get(option_id)
    except:
        return None


@blueprint.route('/geo/layer') # Renamed from /geo/input
@blueprint.route('/geo/input') # Alias for compatibility
@login_required
def page_layer():
    """
    Geo Layer Manager.
    Manages external GIS inputs (Layers).
    """
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))

    geo_layers = sorted(GeoLayer.query.all(), key=lambda l: (l.position_y, l.id))
    dict_inputs = parse_input_information()

    form_add = forms_geo.GISInputAdd()
    form_mod = forms_geo.GISInputMod()

    from flask_wtf.csrf import generate_csrf
    return render_template('pages/geo_input.html',
                           active_page='geo_layer',
                           geo_layers=geo_layers,
                           gis_inputs=geo_layers,
                           dict_inputs=dict_inputs,
                           form_add_gis=form_add,
                           form_mod_gis=form_mod,
                           get_custom_option=_geo_layer_get_custom_option,
                           csrf_token=generate_csrf)


@blueprint.route('/geo/layer/options')
@blueprint.route('/geo/input/options') # Alias, matching page_layer()'s own naming
@login_required
def page_layer_options():
    """
    Settings-modal body fragment for one GeoLayer, fetched on demand.

    page_layer() used to render every layer's full geo_input_option.html
    inline (channel lists, image-overlay panel, map preview) even when the
    modal was never opened — same root cause as the input/output/function
    pages fixed alongside this (see routes_input.py's `input_type=options`
    endpoint and geo_input.html's openLayerSettingsModal()).
    """
    if not utils_general.user_has_permission('edit_settings'):
        return "Permission denied", 403

    input_id = request.args.get('input_id')
    each_input = GeoLayer.query.filter_by(unique_id=input_id).first()
    if not each_input:
        return "Not found", 404

    dict_inputs = parse_input_information()

    from flask_wtf.csrf import generate_csrf
    return render_template('pages/geo_input_components/geo_input_option.html',
                           each_input=each_input,
                           dict_inputs=dict_inputs,
                           get_custom_option=_geo_layer_get_custom_option,
                           csrf_token=generate_csrf)

@blueprint.route('/geo/layer/submit', methods=['POST'])
@blueprint.route('/geo/input/submit', methods=['POST'])
@login_required
def page_layer_submit():
    """Submit form for Geo Layer page"""
    messages = {
        "success": [],
        "info": [],
        "warning": [],
        "error": []
    }
    
    if not utils_general.user_has_permission('edit_controllers'):
        messages["error"].append("Your permissions do not allow this action")
        return jsonify(data={'messages': messages})
        
    form_add = forms_geo.GISInputAdd()
    form_mod = forms_geo.GISInputMod()
    
    target_input_id = None
    action_type = None

    if form_add.input_add.data:
        messages = utils_geo.geo_layer_add(form_add)
        # Assuming we can get the new ID? 
        # utils_geo.geo_layer_add currently returns only messages. 
        # Ideally we should modify it to return ID, but for activation focus we skip "add" DOM update for now (reload fallback)
        action_type = 'input_add'
        
    elif form_mod.input_mod.data:
        # Check standard modification
        messages = utils_geo.geo_layer_mod(form_mod, request.form)
        target_input_id = form_mod.input_id.data
        action_type = 'input_mod'
        
    elif form_mod.input_delete.data:
        target_input_id = form_mod.input_id.data
        messages = utils_geo.geo_layer_del(target_input_id)
        action_type = 'input_delete'

    # [Fix] Handle Activation/Deactivation (Standard AoT Input Logic)
    elif 'input_activate' in request.form:
        target_input_id = form_mod.input_id.data
        messages = utils_geo.geo_layer_activate(target_input_id, True)
        action_type = 'input_activate'
    elif 'input_deactivate' in request.form:
        target_input_id = form_mod.input_id.data
        messages = utils_geo.geo_layer_activate(target_input_id, False)
        action_type = 'input_deactivate'

    # Check global message settings
    from aot.databases.models import Misc
    misc = Misc.query.first()
    if misc:
        if misc.hide_alert_success:
            messages['success'] = []
        if misc.hide_alert_info:
            messages['info'] = []
        if misc.hide_alert_warning:
            messages['warning'] = []

    # [Fix] Return input_id and action for JS DOM update
    return jsonify(data={
        'messages': messages,
        'input_id': target_input_id,
        'action': action_type
    })

@blueprint.route('/geo/input/layout', methods=['POST'])
@blueprint.route('/geo/layer/layout', methods=['POST'])
@login_required
def page_layer_save_layout():
    """Save GridStack Layout for Geo Inputs"""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'error': 'Permission Denied'}), 403

    try:
        layout_data = request.get_json()
        if not layout_data:
            return jsonify(result='error', message='No data')
        
        # Format: [{'id': 'uuid', 'y': 0, 'x': 0, ...}, ...]
        # Note: GridStack serialization returns 'id' if we set gs-id properly.
        # Sort by reported y, then re-rank to sequential ints to eliminate ties.
        items = [d for d in layout_data
                 if d.get('id') is not None and d.get('y') is not None]
        items.sort(key=lambda d: (d['y'], d['id']))
        for rank, item in enumerate(items):
            layer = GeoLayer.query.filter_by(unique_id=item['id']).first()
            if layer:
                try:
                    opts = json.loads(layer.options) if layer.options else {}
                except:
                    opts = {}
                if opts.get('position_y') != rank:
                    opts['position_y'] = rank
                    layer.options = json.dumps(opts)

        db.session.commit()
        return jsonify(result='success')

    except Exception as e:
        return jsonify(result='error', message=str(e))


# ---------------------------------------------------------------------------
# Aerial / drone photo overlay (gis_image_overlay)
# ---------------------------------------------------------------------------

# Where uploaded overlay images are stored and served from.
_OVERLAY_SUBDIR = os.path.join('uploads', 'geo_overlays')
_OVERLAY_TILES_SUBDIR = os.path.join('uploads', 'geo_overlays', 'tiles')
_OVERLAY_ALLOWED_EXT = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp'}
_OVERLAY_MAX_BYTES = 60 * 1024 * 1024  # 60 MB; larger orthomosaics are tiled

# Zoom-responsive strategy threshold: an image larger than this (longest side in
# pixels OR file size) is rendered as an XYZ tile pyramid instead of a single
# MapLibre `image` source (which would exceed WebGL MAX_TEXTURE_SIZE and keep the
# whole image resident at every zoom). Below the threshold the simple image
# source is kept — fast and no tiling cost. See .local/reports/.
_OVERLAY_TILE_PX = 2048
_OVERLAY_TILE_BYTES = 12 * 1024 * 1024  # 12 MB
# Longest side of the downscaled preview shown immediately (and used as the
# `image` source for large originals while/instead of tiling).
_OVERLAY_PREVIEW_PX = 2048


def _overlay_dir():
    d = os.path.join(current_app.static_folder, _OVERLAY_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d


def _overlay_is_large(width, height, nbytes):
    """True when the image warrants a tile pyramid rather than an image source."""
    return (max(int(width or 0), int(height or 0)) > _OVERLAY_TILE_PX
            or int(nbytes or 0) > _OVERLAY_TILE_BYTES)


def _overlay_path_from_url(image_url):
    """Resolve a stored /static/uploads/geo_overlays/<f> URL to an absolute path."""
    if not image_url:
        return None
    fname = os.path.basename(image_url)
    if not fname:
        return None
    return os.path.join(_overlay_dir(), fname)


def _overlay_safe_id(layer_id):
    """Restrict a layer_id used as a tiles directory name to safe characters."""
    return ''.join(c for c in str(layer_id) if c.isalnum() or c in ('-', '_'))


def _overlay_tiles_dir(layer_id):
    return os.path.join(current_app.static_folder, _OVERLAY_TILES_SUBDIR,
                        _overlay_safe_id(layer_id))


def _overlay_tile_url(layer_id):
    return '/static/%s/%s/{z}/{x}/{y}.png' % (
        _OVERLAY_TILES_SUBDIR.replace(os.sep, '/'), _overlay_safe_id(layer_id))


def _make_overlay_preview(src_path):
    """Write a downscaled PNG preview next to the original; return its filename.

    Returns None on failure (caller falls back to the original image URL).
    """
    try:
        from PIL import Image as _PILImage
    except Exception:
        return None
    try:
        stem = os.path.splitext(os.path.basename(src_path))[0]
        out_name = '%s_preview.png' % stem
        out_path = os.path.join(_overlay_dir(), out_name)
        img = _PILImage.open(src_path)
        img = img.convert('RGBA')
        img.thumbnail((_OVERLAY_PREVIEW_PX, _OVERLAY_PREVIEW_PX), _PILImage.LANCZOS)
        img.save(out_path, 'PNG')
        return out_name
    except Exception:
        current_app.logger.exception('[overlay] preview generation failed')
        return None


def _start_overlay_tiling(layer_id):
    """Generate the XYZ tile pyramid for an image overlay in a background thread.

    Reads the layer's stored image + 4 corners, writes tiles under
    static/uploads/geo_overlays/tiles/<id>/, then flips the layer's options to
    tiled mode (render_mode/tile_url/min,maxzoom). Status is tracked in options
    (tile_status: pending -> ready|error) and pollable via the status endpoint.
    """
    import threading
    app = current_app._get_current_object()

    def _work():
        with app.app_context():
            try:
                from aot.utils.geo_tiler import generate_tiles
                layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
                if not layer:
                    return
                opts = json.loads(layer.options) if layer.options else {}
                coords = _parse_overlay_coords(opts.get('coordinates'))
                img_path = _overlay_path_from_url(opts.get('image_url'))
                if not coords or not img_path or not os.path.exists(img_path):
                    opts['tile_status'] = 'error'
                    opts['tile_error'] = 'missing image or coordinates'
                    layer.options = json.dumps(opts)
                    db.session.commit()
                    utils_geo.invalidate_geo_config_cache()
                    return

                info = generate_tiles(img_path, coords, _overlay_tiles_dir(layer_id))

                # Re-load: the row may have changed while tiling ran.
                layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
                if not layer:
                    return
                opts = json.loads(layer.options) if layer.options else {}
                opts['render_mode'] = 'tiled'
                opts['tile_status'] = 'ready'
                opts['tile_url'] = _overlay_tile_url(layer_id)
                opts['minzoom'] = info['minzoom']
                opts['maxzoom'] = info['maxzoom']
                opts['tile_count'] = info['tile_count']
                # Remember which corners these tiles were built for, so a later
                # placement edit knows it must re-tile.
                opts['tiled_coords'] = json.dumps(coords)
                opts.pop('tile_error', None)
                layer.options = json.dumps(opts)
                db.session.commit()
                utils_geo.invalidate_geo_config_cache()
                app.logger.info('[overlay] tiled %s: z%s-%s, %s tiles',
                                layer_id, info['minzoom'], info['maxzoom'],
                                info['tile_count'])
            except Exception as e:
                app.logger.exception('[overlay] tiling failed for %s', layer_id)
                try:
                    layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
                    if layer:
                        opts = json.loads(layer.options) if layer.options else {}
                        opts['tile_status'] = 'error'
                        opts['tile_error'] = str(e)[:200]
                        layer.options = json.dumps(opts)
                        db.session.commit()
                        utils_geo.invalidate_geo_config_cache()
                except Exception:
                    pass
            finally:
                db.session.remove()

    threading.Thread(target=_work, daemon=True).start()


def _parse_overlay_coords(raw):
    """Return a valid 4-corner [[lng,lat]x4] list from stored options, else None.

    The value may be a JSON string (how it is persisted) or an already-decoded
    list. Anything that is not exactly 4 [lng,lat] pairs is rejected.
    """
    if not raw:
        return None
    coords = raw
    if isinstance(coords, str):
        try:
            coords = json.loads(coords)
        except (TypeError, ValueError):
            return None
    if (isinstance(coords, list) and len(coords) == 4
            and all(isinstance(p, (list, tuple)) and len(p) == 2 for p in coords)):
        try:
            return [[float(p[0]), float(p[1])] for p in coords]
        except (TypeError, ValueError):
            return None
    return None


@blueprint.route('/api/geo/overlay_image/upload', methods=['POST'])
@login_required
def api_geo_overlay_image_upload():
    """
    Upload an aerial/drone photo for a gis_image_overlay layer.

    Multipart form: file=<image>, layer_id=<GeoLayer.unique_id>.
    Saves the image, attempts to auto-georeference it from EXIF/XMP, stores the
    image URL + auto footprint into the layer options, and returns both so the
    config UI can show a draggable preview.
    """
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'ok': False, 'error': 'Permission Denied'}), 403

    from werkzeug.utils import secure_filename
    import uuid as _uuid
    from aot.utils.geo_photo_georef import extract_photo_metadata, compute_footprint

    layer_id = request.form.get('layer_id')
    f = request.files.get('file')
    if not layer_id or not f or not f.filename:
        return jsonify({'ok': False, 'error': 'layer_id and file required'}), 400

    layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
    if not layer:
        return jsonify({'ok': False, 'error': 'layer not found'}), 404
    if layer.type != 'gis_image_overlay':
        return jsonify({'ok': False, 'error': 'layer is not an image overlay'}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in _OVERLAY_ALLOWED_EXT:
        return jsonify({'ok': False, 'error': 'unsupported file type: %s' % ext}), 400

    raw = f.read()
    if len(raw) > _OVERLAY_MAX_BYTES:
        return jsonify({'ok': False,
                        'error': 'file too large (max %d MB)' % (_OVERLAY_MAX_BYTES // (1024 * 1024))}), 400

    # Unique filename; keep a readable, sanitised stem.
    stem = secure_filename(os.path.splitext(f.filename)[0]) or 'overlay'
    fname = '%s_%s%s' % (stem[:40], _uuid.uuid4().hex[:8], ext)
    fpath = os.path.join(_overlay_dir(), fname)
    try:
        with open(fpath, 'wb') as out:
            out.write(raw)
    except Exception as e:
        return jsonify({'ok': False, 'error': 'save failed: %s' % e}), 500

    image_url = '/static/%s/%s' % (_OVERLAY_SUBDIR.replace(os.sep, '/'), fname)

    try:
        opts = json.loads(layer.options) if layer.options else {}
    except Exception:
        opts = {}

    # Detect an existing placement. When the layer is already georeferenced this
    # upload is treated as a *simple image replacement*: keep the corner
    # coordinates and only swap the texture, so the operator does not lose a
    # placement they already fine-tuned. Auto-georeferencing runs only on the
    # first upload (no existing coordinates).
    existing_coords = _parse_overlay_coords(opts.get('coordinates'))

    meta = extract_photo_metadata(raw)
    if existing_coords:
        coords = existing_coords
        preserved = True
        auto = False
    else:
        coords = compute_footprint(meta) if meta.get('has_geo') else None
        preserved = False
        auto = bool(coords)

    # Persist into the layer options. Existing opacity is preserved if present.
    opts['image_url'] = image_url
    if coords:
        opts['coordinates'] = json.dumps(coords)
    opts.setdefault('opacity', '0.85')
    # Slim metadata for UI display (drop bulky/irrelevant keys).
    opts['meta'] = json.dumps({k: meta.get(k) for k in (
        'lat', 'lon', 'rel_altitude', 'yaw', 'pitch', 'focal_35mm',
        'width', 'height', 'has_geo') if k in meta})

    # --- Zoom-responsive strategy: decide image vs tiled ---------------------
    width = meta.get('width') or 0
    height = meta.get('height') or 0
    large = _overlay_is_large(width, height, len(raw))
    opts['tile_eligible'] = bool(large)

    # A fresh image invalidates any previous tile pyramid.
    opts['tiled_coords'] = ''
    for _k in ('tile_url', 'minzoom', 'maxzoom', 'tile_count', 'tile_error'):
        opts.pop(_k, None)
    opts['render_mode'] = 'image'

    preview_url = None
    if large:
        # Show a lightweight downscaled preview immediately (and use it as the
        # image source until/unless tiles are ready).
        preview_name = _make_overlay_preview(fpath)
        if preview_name:
            preview_url = '/static/%s/%s' % (_OVERLAY_SUBDIR.replace(os.sep, '/'), preview_name)
            opts['preview_url'] = preview_url
        else:
            opts.pop('preview_url', None)
    else:
        opts.pop('preview_url', None)

    # Tile now only when we already have a placement (auto-georef or preserved);
    # otherwise tiling is deferred to the Save step once the user sets corners.
    will_tile = bool(large and coords)
    opts['tile_status'] = 'pending' if will_tile else 'none'

    layer.options = json.dumps(opts)
    db.session.commit()

    if will_tile:
        _start_overlay_tiling(layer_id)

    return jsonify({
        'ok': True,
        'image_url': image_url,
        'preview_url': preview_url,     # downscaled preview (large images only)
        'coordinates': coords,          # kept (replacement), auto, or null
        'auto_georeferenced': auto,
        'preserved_coords': preserved,  # True → coords kept from previous image
        'tile_eligible': bool(large),
        'render_mode': opts['render_mode'],
        'tile_status': opts['tile_status'],
        'meta': meta,
        'width': meta.get('width'),
        'height': meta.get('height'),
    })


@blueprint.route('/api/geo/overlay_image/save', methods=['POST'])
@login_required
def api_geo_overlay_image_save():
    """
    Persist corrected corner coordinates / opacity for an image overlay layer.

    JSON: { layer_id, coordinates: [[lng,lat]x4], opacity: float }.
    """
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'ok': False, 'error': 'Permission Denied'}), 403

    data = request.get_json(silent=True) or {}
    layer_id = data.get('layer_id')
    coords = data.get('coordinates')
    opacity = data.get('opacity')

    if not layer_id:
        return jsonify({'ok': False, 'error': 'layer_id required'}), 400

    layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
    if not layer or layer.type != 'gis_image_overlay':
        return jsonify({'ok': False, 'error': 'image overlay layer not found'}), 404

    # Validate coordinates: exactly 4 [lng, lat] pairs.
    if coords is not None:
        if (not isinstance(coords, list) or len(coords) != 4 or
                not all(isinstance(p, (list, tuple)) and len(p) == 2 for p in coords)):
            return jsonify({'ok': False, 'error': 'coordinates must be 4 [lng,lat] pairs'}), 400

    try:
        opts = json.loads(layer.options) if layer.options else {}
    except Exception:
        opts = {}
    if coords is not None:
        opts['coordinates'] = json.dumps([[float(p[0]), float(p[1])] for p in coords])
    if opacity is not None:
        try:
            opts['opacity'] = str(max(0.0, min(1.0, float(opacity))))
        except (TypeError, ValueError):
            pass

    # If this is a large image (tile-eligible) and its placement is now set or
    # changed, (re)build the tile pyramid for the new corners. Tiles built for a
    # different set of corners are stale, so compare against tiled_coords.
    tile_now = False
    if opts.get('tile_eligible'):
        coords_now = _parse_overlay_coords(opts.get('coordinates'))
        if coords_now:
            changed = opts.get('coordinates') != opts.get('tiled_coords')
            if changed or opts.get('tile_status') != 'ready':
                opts['tile_status'] = 'pending'
                tile_now = True

    layer.options = json.dumps(opts)
    db.session.commit()

    if tile_now:
        _start_overlay_tiling(layer_id)

    return jsonify({'ok': True,
                    'tile_status': opts.get('tile_status', 'none'),
                    'render_mode': opts.get('render_mode', 'image')})


@blueprint.route('/api/geo/overlay_image/tile_status/<layer_id>', methods=['GET'])
@login_required
def api_geo_overlay_image_tile_status(layer_id):
    """Poll the tiling state of an image overlay layer.

    Returns: { ok, tile_status: none|pending|ready|error, render_mode,
               tile_url, minzoom, maxzoom, tile_count, tile_error }.
    """
    layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
    if not layer or layer.type != 'gis_image_overlay':
        return jsonify({'ok': False, 'error': 'image overlay layer not found'}), 404
    try:
        opts = json.loads(layer.options) if layer.options else {}
    except Exception:
        opts = {}
    return jsonify({
        'ok': True,
        'tile_status': opts.get('tile_status', 'none'),
        'render_mode': opts.get('render_mode', 'image'),
        'tile_eligible': bool(opts.get('tile_eligible')),
        'tile_url': opts.get('tile_url'),
        'minzoom': opts.get('minzoom'),
        'maxzoom': opts.get('maxzoom'),
        'tile_count': opts.get('tile_count'),
        'tile_error': opts.get('tile_error'),
    })
