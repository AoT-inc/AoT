# coding=utf-8
"""
Geo Information Service Routes.
Unified Geo System.
"""
from flask import Blueprint, render_template, redirect, url_for, current_app, request, jsonify, Response, g
import requests
import urllib3

# Several GIS upstreams (open-meteo, vworld, ISRIC fallback) are intentionally
# called with verify=False on servers with certificate-chain issues. Suppress the
# resulting InsecureRequestWarning noise — the verify=False choice is deliberate.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from datetime import datetime
import json
import os
import math
import time
import threading
from flask_login import login_required, current_user
from flask_babel import gettext as _
from aot.aot_flask.access import scope
from aot.aot_flask.utils import utils_general
from aot.aot_flask.utils import utils_http
from aot.databases.models import GeoMap, GeoSetting, GeoLayer, GeoShape, Input, Output, PID, Trigger, Conditional, CustomController, Function, DeviceMeasurements
from aot.aot_flask.extensions import db, cache
from aot.utils.inputs import parse_input_information

# Additional imports for GIS Input logic
from sqlalchemy import or_
from aot.aot_flask.forms import forms_geo
from aot.aot_flask.utils import utils_geo

blueprint = Blueprint('routes_geo', __name__)

from aot.aot_flask.routes_static import inject_variables


@blueprint.after_request
def add_cors_headers(response):
    """Add CORS headers to API responses so cross-origin callers can read them."""
    if request.path.startswith('/api/'):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-API-KEY'
    return response

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

@blueprint.route('/api/geo/init_design', methods=['GET'])
@login_required
def api_geo_init_design():
    """
    Auto-load the latest Design Map on page entry.
    Delegates to GeoDesignManager.
    """
    from aot.aot_flask.geo import GeoDesignManager
    result, error = GeoDesignManager.init_design_map(current_user.id)
    
    if error:
        return jsonify({'ok': False, 'message': error}), 500
        
    return jsonify(result)

@blueprint.route('/api/geo/designs/<string:map_uuid>', methods=['GET'])
@login_required
def api_geo_design_get(map_uuid):
    """Get GeoMap Metadata & State by UUID"""
    from aot.aot_flask.geo import GeoDesignManager
    result, error = GeoDesignManager.get_design_map(map_uuid)
    
    if error:
        status_code = 404 if "not found" in error else 500
        return jsonify({'ok': False, 'message': error}), status_code
        
    return jsonify(result)

@blueprint.route('/api/geo/designs/list', methods=['GET'])
@login_required
def api_geo_designs_list():
    """Get List of all Design Maps for selectors"""
    try:
        # [P3] 지도 종류 구분 없음 — 전체 목록.
        # [P3] 모든 지도가 동등하다 — category 분기 폐기.
        all_maps = GeoMap.query.order_by(GeoMap.updated_at.desc()).all()
        result = []
        for m in all_maps:
            # The saved camera lives in state_json under 'center' as {lat, lng};
            # reading it as a list matched nothing and handed every map the same
            # Seoul default. GeoMap.viewport() is the one place that resolves it.
            lat, lng, zoom = m.viewport()
            result.append({
                'unique_id': m.unique_id,
                'name': m.name,
                'latitude': lat if lat is not None else 37.5665,
                'longitude': lng if lng is not None else 126.9780,
                'zoom': zoom if zoom is not None else 13
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

@blueprint.route('/api/geo/designs/<map_uuid>', methods=['DELETE'])
@login_required
def api_geo_design_delete(map_uuid):
    """Delete GeoMap"""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

    # 그룹 스코프 — 지도는 자기 자신이 부여 단위다.
    # (정본: docs/design/access-scope-groups.md)
    if not scope.can_operate('geo_map', map_uuid):
        return jsonify({'ok': False, 'message': scope.deny_message()}), 403
        
    from aot.aot_flask.geo import GeoDesignManager
    result, error = GeoDesignManager.delete_design_map(map_uuid)
    
    if error:
        status_code = 404 if "not found" in error else 500
        return jsonify({'ok': False, 'message': error}), status_code
        
    return jsonify(result)

@blueprint.route('/api/geo/designs', methods=['POST'])
@login_required
def api_geo_design_save():
    """Create or Update GeoMap Metadata & State"""
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403
    
    from aot.aot_flask.geo import GeoDesignManager
    data = request.get_json() or {}

    # 그룹 스코프 — 기존 지도를 고칠 때만 판정한다. 새 지도(uuid 없음)는
    # 부여할 대상이 아직 없으므로 막을 것이 없다.
    _map_uuid = data.get('map_uuid')
    if _map_uuid and not scope.can_operate('geo_map', _map_uuid):
        return jsonify({'ok': False, 'message': scope.deny_message()}), 403

    result, error = GeoDesignManager.save_design_map(data, current_user.id)
    
    if error:
         status_code = 404 if "not found" in error else 500
         return jsonify({'ok': False, 'message': error}), status_code
         
    return jsonify(result)

@blueprint.route('/api/tools/kma_lookup', methods=['POST'])
@login_required
def api_tools_kma_lookup():
    """
    Find Nearest KMA Grid (nx, ny) for given Lat/Lon.
    Uses Nearest Neighbor Search on pre-processed JSON lookup.
    """
    try:
        data = request.get_json()
        user_lat = float(data.get('lat'))
        user_lon = float(data.get('lon'))
        
        # Path to lookup JSON
        json_path = os.path.join(current_app.static_folder, 'json', 'kma_grid_lookup.json')
        
        if not os.path.exists(json_path):
            return jsonify({'ok': False, 'message': 'Lookup data not found'}), 500
            
        with open(json_path, 'r', encoding='utf-8') as f:
            grid_data = json.load(f)
            
        # Nearest Neighbor Search
        min_dist = float('inf')
        nearest_point = None
        
        for point in grid_data:
            # Euclidean distance squared (lat diff^2 + lon diff^2)
            dist = (user_lat - point['lat'])**2 + (user_lon - point['lon'])**2
            
            if dist < min_dist:
                min_dist = dist
                nearest_point = point
                
        if nearest_point:
            return jsonify({
                'ok': True,
                'nx': nearest_point['nx'],
                'ny': nearest_point['ny'],
                'lat': nearest_point['lat'],
                'lon': nearest_point['lon']
            })
        else:
            return jsonify({'ok': False, 'message': 'No matching grid found'}), 404

    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

@blueprint.route('/api/geo/settings', methods=['GET', 'POST'])
@login_required
def api_geo_settings():
    """
    Geo Settings API for Modal integration.
    GET: Returns current settings JSON.
    POST: Updates settings via JSON or Form.
    """
    def _ensure_global_settings():
        inst = GeoSetting.query.first()
        if not inst:
            inst = GeoSetting()
            db.session.add(inst)
            db.session.commit()
        return inst

    global_settings = _ensure_global_settings()

    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

        # Support both JSON and Form data
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form

        # [Fix] Serialize the whole read-modify-write against concurrent saves
        # (see GEO_SETTINGS_SAVE_LOCK docstring — patching one key of the
        # theme_config/providers JSON blobs is a lost-update race otherwise).
        # Re-fetch fresh inside the lock so this request's merge is based on
        # the latest committed row, not whatever was read before the lock.
        utils_geo.GEO_SETTINGS_SAVE_LOCK.acquire()
        try:
            global_settings = GeoSetting.query.populate_existing().first() or global_settings

            # 1. Process Providers & Keys
            try:
                providers_state = json.loads(global_settings.providers) if global_settings.providers else {}
                # Merge search provider
                search_provider = data.get('search_provider')
                if search_provider is not None:
                     providers_state['search_provider'] = search_provider
                # MapLibre 라이브러리 로컬 서빙 여부 (기본: CDN)
                maplibre_local = data.get('maplibre_local_serving')
                if maplibre_local is not None:
                     providers_state['maplibre_local_serving'] = (str(maplibre_local).lower() == 'true')
                global_settings.providers = json.dumps(providers_state)
            except Exception as e:
                current_app.logger.error(f"Error processing geo providers: {e}")

            # 2. Geo Params
            numeric_fields = {
                'max_zoom': 25,
                'max_polygons_device': 1000,
                'max_polygons_site': 1000,
                'max_polygons_zone': 1000,
                'equipment_cull_zoom': 15
            }
            for field, default in numeric_fields.items():
                try:
                    val = data.get(field)
                    if val is not None:
                        setattr(global_settings, field, int(val))
                except:
                    pass

            float_fields = {
                'default_lat': 37.5665,
                'default_lng': 126.9780,
                'default_zoom': 12.0
            }
            for field, default in float_fields.items():
                try:
                    val = data.get(field)
                    if val is not None:
                        attr_name = 'zoom' if field == 'default_zoom' else field
                        setattr(global_settings, attr_name, float(val))
                except:
                    pass

            # Boolean: digital_zoom, smooth_zoom, tile_fade_animation, prefer_canvas
            bool_fields = ['digital_zoom', 'smooth_zoom', 'tile_fade_animation', 'prefer_canvas']
            for field in bool_fields:
                val = data.get(field)
                if val is not None:
                     setattr(global_settings, field, (str(val).lower() == 'true'))

            # 3. Theme Configuration
            try:
                theme_conf = global_settings.state_dict().get('theme_config', {}) or {}
                # 화이트리스트에 없는 키는 **조용히 버려진다.** 새 종류를
                # 추가하면 여기도 함께 늘릴 것 — 안 그러면 피커는 색이 바뀐
                # 것처럼 보이고 새로고침하면 되돌아온다(2026-08-08 실제로
                # theme_vis_device_unit 이 빠져 복합장치 표시 토글이 저장되지
                # 않았다).
                theme_keys = [
                    'theme_site', 'theme_zone', 'theme_facility', 'theme_equipment', 'theme_device',
                    'theme_plot',
                    'theme_input', 'theme_output', 'theme_function', 'theme_device_unit',
                    'theme_panel_bg', 'theme_panel_opacity',
                    'theme_hide_label', 'theme_vis_input', 'theme_vis_output',
                    'theme_vis_function', 'theme_vis_device_unit',
                    # 모드별 "지도에서 보기"(설정 드로어). 장치 종류별
                    # theme_vis_* 와 키를 나눈 이유는 'equipment' 처럼 이름이
                    # 겹치는 축이 있어서다 — 같은 키를 쓰면 서로를 덮어쓴다.
                    'theme_vis_shape_site', 'theme_vis_shape_zone',
                    'theme_vis_shape_facility', 'theme_vis_shape_vegetation',
                    'theme_vis_shape_equipment', 'theme_vis_shape_aot_device',
                ]
                for key in theme_keys:
                    val = data.get(key)
                    if val is not None:
                        clean_key = key.replace('theme_', '')
                        theme_conf[clean_key] = val
                global_settings.theme_config = json.dumps(theme_conf)
            except Exception as e:
                current_app.logger.error(f"Error saving theme config in API: {e}")

            db.session.commit()
            utils_geo.invalidate_geo_config_cache()
        finally:
            utils_geo.GEO_SETTINGS_SAVE_LOCK.release()

        return jsonify({'ok': True, 'message': 'Settings Saved'})

    # GET
    # saved_state carries the map providers' API keys in the clear. Its only
    # caller is the geo settings modal (templates/modals/geo_settings_modal.html,
    # reached from the map design page), which is an editing surface — so gate
    # reads at the same level the POST above already requires.
    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

    saved_state = global_settings.state_dict()
    geo_layers = GeoLayer.query.filter_by(is_activated=True).all()
    layers_data = [{'unique_id': l.unique_id, 'name': l.name, 'type': l.type} for l in geo_layers]

    # Build search_inputs: all GeoLayer records with search capability
    _SEARCH_CAPABLE_TYPES = ['gis_osm', 'gis_google', 'gis_gsi', 'gis_vworld']
    try:
        all_layers = GeoLayer.query.all()
        search_inputs = [
            {'unique_id': l.unique_id, 'name': l.name, 'type': l.type}
            for l in all_layers if l.type in _SEARCH_CAPABLE_TYPES
        ]
        # Add native types not yet registered as layers
        covered_types = {l['type'] for l in search_inputs}
        try:
            _dict_inputs = parse_input_information()
            for type_name in _SEARCH_CAPABLE_TYPES:
                if type_name not in covered_types and type_name in _dict_inputs:
                    search_inputs.append({
                        'unique_id': type_name,
                        'name': _dict_inputs[type_name].get('input_name', type_name),
                        'type': type_name
                    })
        except Exception:
            pass
        current_app.logger.warning(f"[GeoSettings] search_inputs={[i['type'] for i in search_inputs]}")
    except Exception as e:
        current_app.logger.error(f"[GeoSettings] search_inputs build failed: {e}")
        search_inputs = []

    current_search_provider = utils_geo.get_geo_config().get('search_provider')

    return jsonify({
        'ok': True,
        'saved_state': saved_state,
        'geo_layers': layers_data,
        'search_inputs': search_inputs,
        'search_provider': current_search_provider
    })

@blueprint.route('/api/geo/overlays/list', methods=['GET'])
@login_required
def api_geo_overlays_list():
    from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
    return GeoOverlayManager.get_overlays()

@blueprint.route('/api/geo/overlays', methods=['GET', 'POST'])
@login_required
def api_geo_overlays():
    """Unified Overlays Interface (GET: load, POST: bulk save)"""
    from aot.aot_flask.geo import GeoOverlayManager
    
    if request.method == 'GET':
        map_uuid = request.args.get('map_uuid')
        parent_id = request.args.get('parent_id')
        target_type = request.args.get('type')
        device_id = request.args.get('device_id')
        
        result, error = GeoOverlayManager.get_overlays(map_uuid, target_type, parent_id, device_id=device_id)
        if error:
            return jsonify({'error': error}), 500
        return jsonify(result)
        
    else: # POST
        if not utils_general.user_has_permission('edit_settings'):
            return jsonify({'ok': False, 'message': 'Permission Denied'}), 403
            
        data = request.get_json() or {}

        # 그룹 스코프 — 도형은 지도에 속한다. 여기를 막지 않으면 부여된 지도의
        # 도형을 남이 통째로 갈아치울 수 있다(이 경로는 전량 교체다).
        if not scope.can_operate('geo_map', data.get('map_uuid')):
            return jsonify({'ok': False, 'message': scope.deny_message()}), 403

        result, error = GeoOverlayManager.save_overlays(data)
        
        if error:
            return jsonify({'ok': False, 'message': error}), 500
            
        return jsonify(result)

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
# Parcel Import Routes — address → parcel polygon → Site conversion
# ---------------------------------------------------------------------------

def _get_vworld_credentials():
    """Read api_key / domain from the registered VWorld GIS Input.
    Prefer an activated layer; if none, also check inactive layers."""
    import json as _json
    layer = (GeoLayer.query.filter_by(type='gis_vworld', is_activated=True).first()
             or GeoLayer.query.filter_by(type='gis_vworld').first())
    if not layer:
        return None, None
    try:
        opts = _json.loads(layer.options) if layer.options else {}
    except Exception:
        opts = {}
    return opts.get('api_key', ''), opts.get('vworld_domain', '')


@blueprint.route('/api/geo/parcel/from_address', methods=['POST'])
@login_required
def api_geo_parcel_from_address():
    """Look up a VWorld parcel polygon for a single address.
    The API Key is fetched automatically from the registered VWorld GIS Input."""
    data = request.get_json()
    address = data.get('address', '').strip()
    if not address:
        return jsonify({'ok': False, 'error': 'address required'}), 400
    api_key, domain = _get_vworld_credentials()
    if not api_key:
        return jsonify({'ok': False, 'error': _('VWorld GIS Input is not registered or its API Key is missing.')}), 400
    from aot.inputs_gis.gis_vworld import InputModule as VWorldInput
    result = VWorldInput.parcel_from_address(address, api_key, domain)
    return jsonify(result)


@blueprint.route('/api/geo/parcel/from_csv', methods=['POST'])
@login_required
def api_geo_parcel_from_csv():
    """Batch-look up parcel polygons from a list of addresses in a CSV file.
    The API Key is fetched automatically from the registered VWorld GIS Input."""
    import io
    import csv as csv_mod
    f = request.files.get('file')
    if not f:
        return jsonify({'ok': False, 'error': 'file required'}), 400
    api_key, domain = _get_vworld_credentials()
    if not api_key:
        return jsonify({'ok': False, 'error': _('VWorld GIS Input is not registered or its API Key is missing.')}), 400
    content = f.read().decode('utf-8-sig')
    reader = csv_mod.reader(io.StringIO(content))
    addresses = [row[0].strip() for row in reader if row and row[0].strip()]
    from aot.inputs_gis.gis_vworld import InputModule as VWorldInput
    result = VWorldInput.parcels_from_addresses(addresses, api_key, domain)
    return jsonify(result)


def _parcel_geom_key(geometry, tolerance=1e-6):
    """기하를 좌표 반올림 후 정규화 문자열로. 없으면 None.

    `check_geo_integrity._geom_key` 와 같은 규칙이다. 반올림하는 이유도 같다:
    같은 필지를 두 번 가져오는 사이 좌표가 미세하게 달라질 수 있어, 완전
    일치만 보면 중복을 놓친다.
    """
    import math
    if not isinstance(geometry, dict) or not geometry.get('type'):
        return None
    ndigits = max(0, -int(round(math.log10(tolerance)))) if tolerance > 0 else 12

    def _round(node):
        if isinstance(node, (int, float)):
            return round(float(node), ndigits)
        if isinstance(node, (list, tuple)):
            return [_round(x) for x in node]
        return node

    return json.dumps(
        {'type': geometry['type'], 'coordinates': _round(geometry.get('coordinates'))},
        sort_keys=True)


def _find_duplicate_site(geo_id, geometry):
    """같은 지도에 기하가 같은 site 도형이 있으면 그것을 반환. 없으면 None."""
    key = _parcel_geom_key(geometry)
    if not key:
        return None
    for s in GeoShape.query.filter_by(geo_id=geo_id, type='site').all():
        feat = s.feature
        if isinstance(feat, str):
            try:
                feat = json.loads(feat)
            except Exception:
                continue
        if not isinstance(feat, dict):
            continue
        if _parcel_geom_key(feat.get('geometry')) == key:
            return s
    return None


@blueprint.route('/api/geo/parcel/save_as_site', methods=['POST'])
@login_required
def api_geo_parcel_save_as_site():
    """Save a GeoJSON Feature as a GeoShape(Site) and also create a label_aux for labeling."""
    import json as _json
    data = request.get_json()
    feature = data.get('feature')
    name = data.get('name', 'Site')
    map_uuid = data.get('map_uuid')
    if not feature:
        return jsonify({'ok': False, 'error': 'feature required'}), 400

    import uuid as _uuid
    if 'properties' not in feature or feature['properties'] is None:
        feature['properties'] = {}
    feature['properties']['name'] = name
    feature['properties']['category'] = 'site'
    # [Fix] Assign node_id — cleanupOrphanLabels finds the parent via
    # label.parent_node_id ↔ site.node_id, so without a node_id the label is
    # deleted as an orphan on every load.
    site_node_id = feature['properties'].get('node_id') or str(_uuid.uuid4())
    feature['properties']['node_id'] = site_node_id

    # [I8] 실존 지도 필수. 과거 '__parcel_import__' 센티널은 어떤 GeoMap 에도
    # 속하지 않는 도형을 만들었고, 모든 삭제 경로가 실존 지도의 geo_id 를
    # 키로 잡으므로 영구 누수였다. Tier-2 트리거(GEO-I8)가 이를 봉인한다.
    if not map_uuid:
        return jsonify({'ok': False,
                        'message': 'map_uuid is required for parcel import'}), 400
    if not GeoMap.query.filter_by(unique_id=map_uuid).first():
        return jsonify({'ok': False,
                        'message': f'map not found: {map_uuid}'}), 404
    geo_id = map_uuid

    # [중복 방지] 같은 지도에 같은 필지가 이미 있으면 만들지 않는다.
    #
    # 예전에는 무조건 새로 만들었다. 클라이언트가 저장 중 버튼을 잠그지만
    # 그건 **한 번의 저장 안에서 더블클릭만** 막는다 — 모달을 닫았다 다시
    # 열어 같은 주소를 가져오면 대지와 라벨이 한 벌 더 생겼다. 실제로
    # 81초 간격으로 그렇게 만들어진 짝을 2026-08-08 에 지웠다.
    #
    # 판정 기준은 `check_geo_integrity` 의 duplicate 와 **같은 규칙**이다
    # (종류 + 좌표 반올림 기하). 검사기가 중복이라 부르는 것을 여기서 막지
    # 않으면, 만들 때는 통과하고 점검에서만 걸리는 상태가 된다.
    existing = _find_duplicate_site(geo_id, feature.get('geometry'))
    if existing is not None:
        ex_props = (existing.feature or {}).get('properties', {}) \
            if isinstance(existing.feature, dict) else {}
        return jsonify({
            'ok': False,
            'duplicate': True,
            'shape_id': existing.id,
            'existing_name': ex_props.get('name') or ex_props.get('label_name'),
            'message': '이미 이 지도에 가져온 필지입니다.',
        }), 409

    shape = GeoShape()
    shape.type = 'site'
    shape.feature = feature
    shape.geo_id = geo_id

    from aot.aot_flask.extensions import db as _db
    _db.session.add(shape)
    _db.session.flush()  # obtain shape.unique_id (before commit)

    # ── Auto-create label_aux GeoShape ──────────────────────────────────────
    # Compute polygon centroid: approximate via coordinate average without shapely
    def _centroid(geom):
        try:
            gtype = geom.get('type', '')
            if gtype == 'Polygon':
                ring = geom['coordinates'][0]
            elif gtype == 'MultiPolygon':
                ring = geom['coordinates'][0][0]
            else:
                return None
            lng = sum(p[0] for p in ring) / len(ring)
            lat = sum(p[1] for p in ring) / len(ring)
            return [lng, lat]
        except Exception:
            return None

    centroid = _centroid(feature.get('geometry') or {})
    if centroid:
        label_feature = {
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': centroid},
            'properties': {
                'label_name': name,
                'label_area': '',
                'is_label': True,
                'parent_type': 'site',                # apply site color (#DF5353)
                'parent_node_id': site_node_id,       # matches the parent Site's node_id
                'node_id': str(_uuid.uuid4()),        # the label's own node_id (for dirty tracking on rename)
            },
        }
        label_shape = GeoShape()
        label_shape.type = 'label_aux'
        label_shape.feature = label_feature
        label_shape.geo_id = geo_id
        _db.session.add(label_shape)

    _db.session.commit()
    return jsonify({'ok': True, 'id': shape.unique_id, 'name': name})


# ---------------------------------------------------------------------------
# GG Public Park Import Routes — Gyeonggi-do urban park CityPark API import
# ---------------------------------------------------------------------------

@blueprint.route('/api/geo/import/gg_parks/preview', methods=['GET'])
@login_required
def api_geo_import_gg_parks_preview():
    """
    Gyeonggi-do urban park import preview (dry_run).
    Returns the polygon acquisition result without actually saving to the DB.

    Query params:
        sigun_nm: city/county filter (optional, e.g. Suwon-si)
        limit:    maximum number of records to process (default: 10)
    """
    sigun_nm = request.args.get('sigun_nm', '').strip() or None
    try:
        limit = int(request.args.get('limit', 10))
    except (ValueError, TypeError):
        limit = 10

    api_key, domain = _get_vworld_credentials()
    if not api_key:
        return jsonify({'ok': False, 'error': _('VWorld GIS Input is not registered or its API Key is missing.')}), 400

    from aot.aot_flask.geo.importers.gg_public_park_importer import GgPublicParkImporter
    importer = GgPublicParkImporter(api_key=api_key, domain=domain)
    result = importer.import_parks(
        geo_id='__preview__',
        sigun_nm=sigun_nm,
        dry_run=True,
        limit=limit,
        delay_sec=0.3,
    )
    return jsonify({'ok': True, **result})


@blueprint.route('/api/geo/import/gg_parks', methods=['POST'])
@login_required
def api_geo_import_gg_parks():
    """
    Save Gyeonggi-do urban parks as GeoShape(site).

    Request JSON:
        map_uuid:  target GeoMap UUID to save into (required)
        sigun_nm:  city/county filter (optional)
        limit:     maximum number of records to process (optional, default: all)
        delay_sec: delay in seconds between API calls (optional, default: 0.3)
    """
    data = request.get_json() or {}
    map_uuid = data.get('map_uuid', '').strip()
    if not map_uuid:
        return jsonify({'ok': False, 'error': 'map_uuid required'}), 400

    sigun_nm = (data.get('sigun_nm') or '').strip() or None
    limit = data.get('limit')       # None means all
    try:
        delay_sec = float(data.get('delay_sec', 0.3))
    except (ValueError, TypeError):
        delay_sec = 0.3

    api_key, domain = _get_vworld_credentials()
    if not api_key:
        return jsonify({'ok': False, 'error': _('VWorld GIS Input is not registered or its API Key is missing.')}), 400

    from aot.aot_flask.geo.importers.gg_public_park_importer import GgPublicParkImporter
    importer = GgPublicParkImporter(api_key=api_key, domain=domain)
    result = importer.import_parks(
        geo_id=map_uuid,
        sigun_nm=sigun_nm,
        dry_run=False,
        limit=limit,
        delay_sec=delay_sec,
    )
    return jsonify({'ok': True, **result})


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
    """
    Proxy for OpenWeatherMap API.
    """
    try:
        # Whitelisted params
        params = {k: v for k, v in request.args.items() if k in ['lat', 'lon', 'appid', 'units']}
        
        if not params.get('lat') or not params.get('lon') or not params.get('appid'):
            return jsonify({'error': 'Missing required parameters'}), 400
            
        url = 'https://api.openweathermap.org/data/2.5/weather'
        resp = requests.get(url, params=params, timeout=5)
        
        if resp.status_code != 200:
             g._proxy_error = True
             return jsonify({'error': f"Upstream error: {resp.status_code}", 'text': resp.text}), 502
             
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

        # CSV 파싱 (kma_weather_500.pre_fetch_data와 동일 로직)
        _fields = ['ta', 'hm', 'wd_10m', 'ws_10m', 'pa', 'rn_ox', 'rn_15m', 'vs', 'sd_tot']
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
            if best_ts is None or ts > best_ts:
                best_ts = ts
                result = {}
                for i, field in enumerate(_fields, 1):
                    try:
                        v = cols[i].strip()
                        result[field] = float(v) if v not in ('', 'nan') else None
                    except Exception:
                        result[field] = None

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

        # [Fix] Explicitly log the filtering mode
        current_app.logger.info(f"[AoT API] Fetching devices for map_uuid: {map_uuid} include_all: {include_all} device_ids_count: {len(device_ids) if device_ids else 0}")

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

@blueprint.context_processor
def inject_dictionary():
    context = inject_variables()
    
    # Inject Unified Geo Config
    if 'geo_config' not in context:
        context['geo_config'] = utils_geo.get_geo_config()
        # Alias for backward compatibility if needed, but we aim for unified 'geo_config'
        # context['gis_global_config'] = context['geo_config'] 
        
    return context

@blueprint.route('/geo/design')
@login_required
def page_design():
    """
    Geo Design Tool.
    Interactive map editor for Sites, Zones, and Devices.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))
    
    # GeoMap configs - [Optimization] Filter for Design Maps only in SQL
    # [P3] 모든 지도가 동등하다 — category 분기 폐기.
    design_maps = GeoMap.query.order_by(GeoMap.updated_at.desc()).all()

    # [Auto-Create] Default Map if none exist
    if not design_maps:
        import json
        default_state = {
            'category': 'design',
            'layers': []
        }
        # Create default map
        new_map = GeoMap(
            name="My design",
            state_json=json.dumps(default_state),
            created_by=str(current_user.id) # user_id is integer usually, cast to string for safety
        )
        db.session.add(new_map)
        db.session.commit()
        
        # Refresh list
        design_maps = [new_map]
    
    _SEARCH_CAPABLE_TYPES = ['gis_osm', 'gis_google', 'gis_gsi', 'gis_vworld']
    all_layers = GeoLayer.query.all()
    design_search_inputs = [
        {'unique_id': l.unique_id, 'name': l.name, 'type': l.type}
        for l in all_layers if l.type in _SEARCH_CAPABLE_TYPES
    ]

    from flask import make_response
    resp = make_response(render_template('pages/geo/geo_design.html',
                           active_page='geo_design',
                           map_configs=design_maps,
                           geo_config=utils_geo.get_geo_config(),
                           design_search_inputs=design_search_inputs))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# ============================================================
# Programs (관리 프로그램) Route
# ============================================================

@blueprint.route('/geo/programs')
@login_required
def page_programs():
    """설정 > 프로그램 — 관리 프로그램 목록·편집.

    **식생은 대상 중 하나일 뿐이다.** 같은 구조("무엇을, 어떤 단계로, 어떤
    목표로")가 가축·시설물·도로에도 그대로 쓰이므로, 이 화면은 종류(`kind`)를
    가진 프로그램 전체를 다룬다.

    프로그램은 **지도에 속하지 않는 전역 자원**이다(대상의 단계·기간·목표는 어느
    지도에서 쓰든 같다). 그래서 지도 선택 없이 열린다.

    목록·편집은 클라이언트가 `/api/geo/program*` 로 한다 — 서버 렌더 폼을
    또 만들면 같은 검증이 두 벌이 되고, 이 도메인은 그 실패를 이미 겪었다.

    탭은 input 페이지(`routes_input.page_input`)와 같은 방식으로 다룬다 —
    `?tab_id=` 로 현재 탭을 고르고, 레거시(탭 도입 전) 행의 `tab_id IS NULL`
    은 여기서 기본 탭으로 지연 백필한다. 마이그레이션이 이 백필을 하지 않는
    이유는 `alembic_db/.../p6_49_program_tab_20260821.py` 참조.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return redirect(url_for('routes_general.home'))

    from aot.databases.models import GeoProgram
    from aot.services.tab_service import TabService

    tab_id = request.args.get('tab_id', None)
    # 조작할 수 없는 탭은 목록에서 뺀다(그룹 스코프). 정보 격리가 아니다.
    tabs = TabService.visible_tabs_for_page('program')
    current_tab = (TabService.get_tab_by_id(tab_id) if tab_id else None)
    if current_tab is not None and current_tab not in tabs:
        current_tab = None          # URL 로 지정된 스코프 밖 탭
    current_tab = current_tab or TabService.default_visible_tab('program')

    # ⚠ **탭이 하나도 없으면 여기서 만든다.** 이 화면의 편집은 전부 탭을 전제로
    # 하는데(프로그램 행은 `tab_id` 를 갖는다), 새 설치에는 program 탭이 없다 —
    # 다른 페이지는 장치를 **추가할 때** `get_default_tab` 이 만들지만 이 화면의
    # 생성은 클라이언트 API 라 그 경로를 지나지 않는다. 그래서 처음 여는 사람은
    # 탭도 없고 아래 백필도 못 돌아, 이름조차 저장되지 않는 화면을 본다(2026-08-23
    # koat 실측: 사용자가 손으로 탭을 만들자 그때부터 동작했다).
    #
    # **보이는 탭이 없다는 것과 탭이 없다는 것은 다르다** — 그룹 스코프로 남의
    # 탭만 가려진 경우까지 여기서 새 탭을 만들면, 그 사람에게 만들 권한이 없는데도
    # 자원이 늘어난다. 그래서 `get_tabs_for_page`(전체)로 판정한다.
    if current_tab is None and not TabService.get_tabs_for_page('program'):
        TabService.get_default_tab('program')
        tabs = TabService.visible_tabs_for_page('program')
        current_tab = TabService.default_visible_tab('program')

    if current_tab:
        null_count = GeoProgram.query.filter(GeoProgram.tab_id.is_(None)).count()
        if null_count:
            default_tab = TabService.get_default_tab('program')
            GeoProgram.query.filter(GeoProgram.tab_id.is_(None)) \
                .update({'tab_id': default_tab.unique_id})
            db.session.commit()
            tabs = TabService.visible_tabs_for_page('program')

    return render_template('pages/geo/programs.html',
                           active_page='geo_programs',
                           tabs=tabs,
                           current_tab_id=(current_tab.unique_id
                                          if current_tab else None))


@blueprint.route('/plots')
@login_required
def page_plots():
    """구획 운영 페이지 — 전체 목록·검색·이력.

    ## 왜 페이지가 필요한가

    지금까지 구획의 중간 지점은 지도 위젯 모달이었고 그 판단은 옳다(일반
    사용자의 세계는 대시보드가 전부다). 다만 모달은 **하나의 대상**을 다루기에
    적합하고, 구획은 수가 느는 대상이라 곧 감당이 안 된다 — 작기 20개, 시설
    5동, 지난 이력. "이번 철에 무엇을 어디에 심었나" 는 지도를 세 번 오가며
    답할 질문이 아니다.

    ## 진입은 누구나, 편집은 `edit_plots`

    **보기는 전원 공개**다(그룹 스코프 A 결정 — 그룹은 조작만 제한한다).
    그래서 진입에 권한을 걸지 않는다. 걸면 Monitor 가 "이번 철에 뭐 심었나" 를
    보려고 대시보드를 열어 지도를 돌려야 하는데, 그 정보는 원래 그에게 공개다.

    편집 가능 여부는 **서버가 판정해 응답에 싣는다**(`can_edit`) — 화면이 스스로
    판단하면 곧 갈라지고, 그 갈라짐은 "눌러도 403" 으로만 드러난다.

    ## 목록은 클라이언트가 API 로 받는다

    `/api/geo/plots` 를 그대로 쓴다(`map_uuid` 없으면 전체). 서버 렌더 목록을
    또 만들면 같은 필터·정렬이 두 벌이 되고, 이 도메인은 그 실패를 이미 겪었다.
    """
    from aot.databases.models import GeoMap

    maps = GeoMap.query.order_by(GeoMap.sort_order.asc(),
                                 GeoMap.name.asc()).all()
    return render_template(
        'pages/geo/plots.html',
        active_page='plots',
        maps=[{'unique_id': m.unique_id, 'name': m.name} for m in maps],
        can_edit=utils_general.user_has_permission('edit_plots', silent=True),
        can_design=utils_general.user_has_permission('edit_settings',
                                                     silent=True))


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
        logger.exception("[actuator_order] save failed")
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
        logger.exception('[bay_capacity] save failed')
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
                  "k_hat": 0.042,
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

    def get_custom_option(layer_obj, option_id):
        import json
        try:
            options = json.loads(layer_obj.options) if layer_obj.options else {}
            return options.get(option_id)
        except:
            return None

    from flask_wtf.csrf import generate_csrf
    return render_template('pages/geo_input.html',
                           active_page='geo_layer',
                           geo_layers=geo_layers,
                           gis_inputs=geo_layers,
                           dict_inputs=dict_inputs,
                           form_add_gis=form_add,
                           form_mod_gis=form_mod,
                           get_custom_option=get_custom_option,
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


@blueprint.route('/geo/settings', methods=['GET'])
@blueprint.route('/geo/setting', methods=['GET', 'POST'])
@login_required
def page_settings():
    """
    Geo Settings - Redirect to Geo Design.
    Legacy page is now integrated as a modal in Geo Design.
    """
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))
    
    # 301 Redirect to Geo Design page where the settings are now a modal
    return redirect(url_for('routes_geo.page_design'), code=301)
    
    # Functionality moved to api_geo_settings and geo_design modal
    pass

@blueprint.route('/location/entry')
@login_required
def location_entry():
    """
    Location Option Picker.
    Simplified map for selecting device location.
    """
    return render_template('pages/location_option/entry.html')

# --- Helper Utilities ---
def _next_map_name(base_label="Map"):
    """Generate next incremental map name."""
    existing = GeoMap.query.filter(GeoMap.name.ilike(f"{base_label}%")).all()
    max_idx = 0
    for m in existing:
        try:
            suffix = m.name.replace(base_label, '').strip()
            if suffix:
                num = int(suffix)
                if num > max_idx:
                    max_idx = num
        except Exception:
            continue
    return f"{base_label} {max_idx + 1}"


# =============================================================================
# GeoJSON API Routes (for Pure MapLibre Widget)
# =============================================================================

def _shape_feature_dict(shape):
    """Return the GeoShape.feature column as a dict (JSON column may be str)."""
    feat = shape.feature
    if isinstance(feat, dict):
        return feat
    if isinstance(feat, str) and feat:
        try:
            return json.loads(feat)
        except Exception:
            return {}
    return {}


def _shapes_to_geojson(shape_type, default_color, map_uuid=None):
    """Build a FeatureCollection from GeoShape rows of the given type.

    GeoShape stores the GeoJSON Feature in the `feature` JSON column. The
    hierarchy field is `type` ('site', 'zone', 'feature', 'facility', ...),
    and there is no `name` / `category` column on GeoShape — the human-readable
    name lives inside feature.properties.

    map_uuid, when given, scopes the query to one map's shapes (geo_id).
    Omitting it returns shapes from every map — callers that render onto a
    single map's widget must always pass it, or shapes belonging to other
    maps bleed onto their view (2026-08-09: an "이천시" test shape named
    청와대, located at the real Blue House in Seoul, rendered on the 김제
    widget because this query had no map filter at all).
    """
    query = GeoShape.query.filter_by(type=shape_type)
    if map_uuid:
        query = query.filter_by(geo_id=map_uuid)
    shapes = query.all()
    features = []
    for shape in shapes:
        try:
            feat = _shape_feature_dict(shape)
            geometry = feat.get('geometry')
            if not geometry:
                continue
            props = dict(feat.get('properties') or {})
            props.setdefault('id', shape.unique_id)
            # 도형 uuid 를 **항상** 실어 보낸다. `id` 는 setdefault 라 저장된
            # feature 에 draw id 가 이미 있으면 그것이 남고, MapLibre 는
            # queryRenderedFeatures 에서 문자열 feature.id 를 버린다 — 그래서
            # 도형 클릭이 uuid 를 되찾을 다른 길이 없다.
            props['shape_uuid'] = shape.unique_id
            props.setdefault('name', props.get('name') or '')
            props['category'] = shape_type
            props.setdefault('color', props.get('fill') or default_color)
            features.append({
                'type': 'Feature',
                'id': shape.unique_id,
                'geometry': geometry,
                'properties': props,
            })
        except Exception:
            continue
    return {'type': 'FeatureCollection', 'features': features}


@blueprint.route('/api/geo/sites', methods=['GET'])
@login_required
def api_geo_sites():
    """Get sites as GeoJSON for MapLibre overlay, scoped to ?map_uuid= when given."""
    try:
        return jsonify(_shapes_to_geojson('site', '#DF5353', request.args.get('map_uuid')))
    except Exception as e:
        current_app.logger.exception("api_geo_sites failed")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/api/geo/zones', methods=['GET'])
@login_required
def api_geo_zones():
    """Get zones as GeoJSON for MapLibre overlay, scoped to ?map_uuid= when given."""
    try:
        return jsonify(_shapes_to_geojson('zone', '#28a745', request.args.get('map_uuid')))
    except Exception as e:
        current_app.logger.exception("api_geo_zones failed")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/api/geo/shapes/<string:category>', methods=['GET'])
@login_required
def api_geo_shapes_by_category(category):
    """Get shapes by hierarchy type (site, zone, facility, feature, ...), scoped to ?map_uuid= when given."""
    try:
        return jsonify(_shapes_to_geojson(category, '#995aff', request.args.get('map_uuid')))
    except Exception as e:
        current_app.logger.exception("api_geo_shapes_by_category failed")
        return jsonify({'error': str(e)}), 500


def _polygon_area_m2(coords):
    """Shoelace + equirectangular projection for a GeoJSON ring [[lng,lat], ...]."""
    if not coords or len(coords) < 3:
        return 0.0
    R = 6371000.0
    lat0 = sum(c[1] for c in coords) / len(coords)
    cos_lat = math.cos(math.radians(lat0))
    area = 0.0
    n = len(coords)
    for i in range(n):
        x1 = math.radians(coords[i][0]) * cos_lat * R
        y1 = math.radians(coords[i][1]) * R
        x2 = math.radians(coords[(i + 1) % n][0]) * cos_lat * R
        y2 = math.radians(coords[(i + 1) % n][1]) * R
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


@blueprint.route('/api/geo/zone/<string:zone_uuid>/contents', methods=['GET'])
@login_required
def api_geo_zone_contents(zone_uuid):
    """Zone 내부 센서·장치·함수 인벤토리 반환.

    30초 캐시 + 단일 비행(site 요약과 같은 헬퍼). 캐시가 없을 때 로컬 실측
    280ms 였고, 그게 **열 때마다** 나갔다 — 이 응답은 도형 스캔 + 장치별
    DeviceMeasurements + influx 집계라 싸질 수 없다. 사람이 창을 여는
    순간에만 필요한 값이고 30초 안에 달라질 것이 없어서, 계산을 줄이는
    대신 캐시로 덮는 쪽이 맞다. 장치 on/off 는 이 응답이 아니라 별도
    폴링이 따라가므로 캐시가 상태를 늦추지 않는다.

    can_edit 는 권한이라 사용자마다 다르지만 캐시는 전역이다 —
    캐시 밖에서 매번 다시 넣는다(아래).
    """
    from aot.aot_flask.geo.site_summary import cached_zone_contents

    payload = cached_zone_contents(
        zone_uuid, lambda: _build_zone_contents(zone_uuid))
    if payload is None:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    payload = dict(payload)
    payload['zone'] = dict(payload['zone'])
    payload['zone']['can_edit'] = utils_general.user_has_permission(
        'edit_settings', silent=True)
    return jsonify(payload)


def _build_area_contents(device_ids, scope_of=None, env=None):
    """장치 참조 집합 → 모달의 인벤토리(센서·장치·기능 + 집계 + 상태).

    **구역 모달과 식생 모달이 이 하나를 함께 쓴다.** 두 벌로 복사하면 같은
    장치를 두 화면이 다르게 세게 되는데, 이 도메인은 정확히 그 실패로 이미
    크게 데었다(`_build_zone_contents` 의 "같은 구역의 센서 수가 화면마다
    달랐다" 주석 참조). 스코프를 정하는 일(어떤 장치가 이 영역의 것인가)은
    호출자가 하고, 여기서는 **정해진 집합을 푸는 일만** 한다.

    `scope_of(unique_id) -> 'plot'|'zone'|None` 를 주면 항목마다 `scope` 를
    붙인다. 식생 모달이 "구획 안의 것" 과 "구역에서 빌려온 것" 을 화면에서
    구분하는 근거다 — 구역 모달은 빌려오는 것이 없으므로 주지 않는다(그러면
    키 자체가 안 붙어 기존 응답 모양이 그대로 유지된다).
    """
    from aot.databases.models import OutputChannel
    from aot.aot_flask.geo.facility_sensors import channel_meta_for_dm

    device_ids = device_ids or set()

    def _scope(uid):
        return {'scope': scope_of(uid)} if scope_of else {}

    # 센서 목록 (Input)
    inputs = (Input.query.filter(Input.unique_id.in_(device_ids)).all()
              if device_ids else [])

    sensors_out = []
    for inp in inputs:
        meas = DeviceMeasurements.query.filter_by(device_id=inp.unique_id).all()
        channels = [channel_meta_for_dm(m) for m in meas]
        row = {
            'unique_id': inp.unique_id,
            'name': inp.name,
            'device': getattr(inp, 'device', ''),
            'is_activated': bool(inp.is_activated),
            'interface': getattr(inp, 'interface', ''),
            'channels': channels,
        }
        row.update(_scope(inp.unique_id))
        sensors_out.append(row)

    # 장치 목록 (Output) — 동일하게 파생만 사용
    outputs_rows = (Output.query.filter(
        Output.unique_id.in_(device_ids)).all()
        if device_ids else [])

    outputs_out = []
    for out in outputs_rows:
        channels = OutputChannel.query.filter_by(output_id=out.unique_id).order_by(OutputChannel.channel).all()
        ch_list = [{'channel': c.channel, 'name': c.name or str(c.channel)} for c in channels]
        if not ch_list:
            ch_list = [{'channel': 0, 'name': out.name}]
        row = {
            'unique_id': out.unique_id,
            'name': out.name,
            'output_type': out.output_type or '',
            'channels': ch_list,
        }
        row.update(_scope(out.unique_id))
        outputs_out.append(row)

    # 함수 목록 (CustomController + Function + Conditional + Trigger + PID)
    # 함수도 지도에 배치되면 마커(device_id=함수 uuid)를 갖는다 — 같은 파생.
    # 복합장치(그릇)는 함수와 같은 테이블에 있지만 성격이 다르다 — Input/Output 을
    # 담는 그릇이지 무언가를 판단하는 규칙이 아니다. 목록에서 섞이면 "이 구역의
    # 기능"에 장치가 끼어 보인다. 가르는 기준은 collect_devices 와 같다.
    try:
        from aot.utils.functions import device_module_names
        _device_names = device_module_names()
    except Exception:
        _device_names = set()

    func_rows = []
    for model, kind in [
        (CustomController, 'custom'),
        (Function,         'function'),
        (Conditional,      'conditional'),
        (Trigger,          'trigger'),
        (PID,              'pid'),
    ]:
        if not device_ids:
            break
        for row in model.query.filter(
                model.unique_id.in_(device_ids)).all():
            row_kind = kind
            if kind == 'custom' and getattr(row, 'device', None) in _device_names:
                row_kind = 'device'
            item = {
                'unique_id': row.unique_id,
                'name': row.name,
                'kind': row_kind,
                'is_activated': bool(getattr(row, 'is_activated', False)),
            }
            item.update(_scope(row.unique_id))
            func_rows.append(item)

    # 현재 환경 — 예전에는 구역 모달 어디에도 "지금 몇 도인가"가 숫자로 없었다.
    # 차트 레전드의 마지막 값에 의존하다 보니, 그래프를 못 읽거나 센서 탭을
    # 넘겨보지 않으면 알 수 없었다. 집계는 필지 요약과 같은 함수를 쓴다 —
    # 한쪽만 고치면 같은 구역이 두 화면에서 다른 온도를 말한다.
    # env 를 이미 계산해 둔 호출자는 넘겨서 **influx 왕복을 한 번 아낀다**.
    # 넘길 수 있는 조건은 하나뿐이다: 그 계산의 대상 집합이 여기 `device_ids`
    # 와 **같은 Input 들을 담을 때**. env 는 Input 만 보므로 Output·Function 이
    # 더 있고 없고는 상관없다(실측: 왕복 1회 약 64ms).
    from aot.aot_flask.geo.site_summary import env_for_devices, status_from
    if env is None:
        try:
            env = env_for_devices(device_ids)
        except Exception:
            current_app.logger.exception("area contents: env aggregation failed")
            env = {'readings': [], 'sensors': {'valid': 0, 'total': 0}}

    # 제목줄 상태 점 — 필지 요약의 행과 같은 판정을 쓴다. env 를 넘겨
    # influx 재조회를 피한다.
    return {
        'sensors': sensors_out,
        'outputs': outputs_out,
        'functions': func_rows,
        'counts': {
            'sensors': len(sensors_out),
            'outputs': len(outputs_out),
            'functions': len(func_rows),
        },
        'env': env,
        'status': status_from(device_ids, env),
    }


def _build_zone_contents(zone_uuid):
    """구역 모달 응답 본체. 못 찾으면 None(캐시에 남기지 않는다)."""

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return None

    zone_id = zone.id
    feat = _shape_feature_dict(zone)
    props = feat.get('properties') or {}
    zone_name = props.get('name') or zone.unique_id

    # 면적
    area_m2 = None
    try:
        geom = feat.get('geometry') or {}
        ring = None
        if geom.get('type') == 'Polygon':
            ring = (geom.get('coordinates') or [[]])[0]
        elif geom.get('type') == 'MultiPolygon':
            ring = ((geom.get('coordinates') or [[[]]])[0] or [[]])[0]
        if ring:
            area_m2 = round(_polygon_area_m2(ring), 1)
    except Exception:
        pass

    # 상위 site — 모달의 "상위로" 화살표와 [현황]의 소속 표시에 함께 쓴다.
    # 예전에는 zone.parent_id 만 봤는데 그 컬럼은 운영 데이터에서 전 행이
    # NULL 이라(geo_hierarchy 주석) 소속 줄이 늘 비어 있었다. 공간 포함
    # 관계로 푸는 공용 리졸버로 바꾼다.
    from aot.aot_flask.geo.site_summary import parent_site_for_shape
    try:
        parent_site = parent_site_for_shape(zone.unique_id)
    except Exception:
        current_app.logger.exception("zone contents: parent site lookup failed")
        parent_site = None
    site_name = parent_site['name'] if parent_site else None
    site_uuid = parent_site['uuid'] if parent_site else None

    # ── 소속 판정: 순수 파생 (S3) ────────────────────────────────────────────
    # 과거에는 map_overlay_id 직접 매칭 + 기하 폴백의 합집합이었다. 저장된
    # 컬럼은 복제·zone 재생성·도형 삭제로 끊기거나 남의 지도를 가리켰고
    # (2026-08-03 사고), 합집합은 그 낡은 값으로 엉뚱한 장치까지 끌어왔다.
    # 이제 마커 좌표에서 실시간 파생하는 단일 리졸버만 쓴다 —
    # aot/aot_flask/geo/device_membership.py 가 유일한 정본이다.
    # device_ids_in_area 는 4겹으로 본다: 마커 · 바인딩 · **그릇** · 참조.
    # 예전에는 마커만 보는 device_ids_in_shape 를 썼는데, 그러면
    #  - 복합장치(그릇)가 구역에 놓여 있어도 그 안의 Input/Output 이 빠지고
    #    (실측: 구역 3-1 의 AoT-C 안에 있는 OpenWeather 가 목록에 없었다),
    #  - 마커 없이 바인딩으로만 매인 출력이 통째로 빠진다(출력 16개 중 마커는 1개).
    # 게다가 같은 구역을 두고 지도 라벨·필지 요약(site_summary)은 4겹으로,
    # 이 모달만 1겹으로 세어 **같은 구역의 센서 수가 화면마다 달랐다.**
    # 그래프 구역 필터도 같은 이유로 이미 이쪽으로 옮겼다(b72bc47).
    from aot.aot_flask.geo.device_membership import device_ids_in_area
    geo_device_ids = device_ids_in_area(zone.unique_id) or set()

    inv = _build_area_contents(geo_device_ids)

    # "켜면 무엇이 함께 젖는가" — 식생 모달에만 붙이면 안 된다. 구역에서 켠
    # 밸브도 그 안의 여러 작물에 물을 주므로, 한쪽에만 경고가 있으면
    # "구역에서 켜면 안전하다" 는 잘못된 대비가 생긴다(설계 §5-2).
    try:
        from aot.aot_flask.geo import plot_context
        _cover = plot_context.plots_by_valve_device(zone.geo_id)
        for _out in inv['outputs']:
            names = plot_context.covered_subject_names(
                _cover.get(_out['unique_id']))
            if names:
                _out['also_covers'] = names
    except Exception:
        # 식생이 없는 지도가 정상이다 — 여기서 실패해도 구역 모달은 떠야 한다.
        current_app.logger.exception("zone contents: 관수 교차 계산 실패")

    # 지금 심겨 있는 것 — 농장 지도인데 계층 어디에도 작물이 없었다.
    # 배분 계산(미배정 = **합집합**으로 빼기)은 zone_allocation 이 정본이다.
    allocation = None
    try:
        from aot.aot_flask.geo import plot_context as _pc
        allocation = _pc.zone_allocation(zone)
    except Exception:
        current_app.logger.exception("zone contents: 식생 배분 계산 실패")

    # 다가오는 일정 — 구역 자신을 대상으로 한 농작업(제초·방제 등)과 구역 안
    # 장치의 예약. `target_id` 가 도형 uuid 도 담는다는 것이 근거다.
    schedule = {'own': [], 'devices': []}
    try:
        from aot.aot_flask.geo.site_summary import upcoming_schedule
        schedule = upcoming_schedule(zone, geo_device_ids)
    except Exception:
        current_app.logger.exception("zone contents: 일정 조회 실패")

    sensors_out = inv['sensors']
    outputs_out = inv['outputs']
    func_rows = inv['functions']
    counts = inv['counts']
    env = inv['env']
    zone_status = inv['status']

    from aot.aot_flask.geo.site_summary import rep_key_of, hidden_rows_of

    meta = zone.meta_json or {}
    photo_url = meta.get('photo_url')
    output_order = meta.get('output_order', [])

    # can_edit 는 여기서 넣지 않는다 — 캐시는 전역이라 처음 연 사람의 권한이
    # 다음 사람에게 그대로 간다. 라우트가 응답마다 다시 채운다.
    from aot.aot_flask.geo import irrigation_status, weather_hazards
    # 노지의 마지막 관수 — 이 구역에서 자라는 구획의 프로그램이 "관수" 라고
    # 선언한 함수만 근거다. 영역에 묶인 범용 on/off 를 관수라고 부르지 않는다.
    _irr = None
    try:
        from aot.aot_flask.geo import plot_context as _pc
        for _p in _pc.active_plots(zone.geo_id):
            _irr = irrigation_status.last_irrigation(None, _p)
            if _irr:
                break
    except Exception:                                       # noqa: BLE001
        _irr = None
    return {
        'ok': True,
        'rep_key': rep_key_of(zone),
        # [현황] 카드에서 빼 둔 항목 — 거르는 것은 화면이 한다(site_summary 주석).
        'hidden_rows': hidden_rows_of(zone),
        'irrigation': _irr,
        # 시설과 **같은 판정**(같은 예보 파일) — 노지에서 오히려 더 자주 행동을
        # 부르는 정보다.
        'hazards': weather_hazards.upcoming_cached(),
        'zone': {
            'unique_id': zone.unique_id,
            'name': zone_name,
            'site_name': site_name,
            'site_uuid': site_uuid,
            'area_m2': area_m2,
            'counts': counts,
            'photo_url': photo_url,
            'output_order': output_order,
            'env': env,
            'status': zone_status,
            # 지금 심겨 있는 것. `zone` 안에 두는 이유는 [현황] 탭이 이 객체
            # 하나만 받기 때문이다(buildZoneStatusHtml).
            'allocation': allocation,
            'schedule': schedule,
        },
        'sensors': sensors_out,
        'outputs': outputs_out,
        'functions': func_rows,
    }



# ── 일정: 네 계층 공통 ──────────────────────────────────────────────────────
#
# 대지·구역·식생·시설이 **같은 창(지금부터)·같은 목록**을 쓴다. 예전에는
# 대지만 "오늘 N건" 숫자였고 구역·식생은 목록, 시설은 아예 없었다 — 창이
# 달라서 **대지가 0인데 구역을 열면 내일 일이 있는** 상태가 실제로 났다
# (실측: 3포장 '오늘 0' / 3-2 구역 8/19 08:00 제초). 위 계층이 아래를 덮지
# 못하면 롤업이라고 부를 수 없다.

@blueprint.route('/api/geo/schedule/<string:target_id>', methods=['GET'])
@login_required
def api_schedule_for_target(target_id):
    """이 대상(도형·구획)에 걸린 다가오는 일정."""
    payload = _schedule_payload(target_id)
    if payload is None:
        return jsonify({'ok': False, 'message': 'target not found'}), 404
    return jsonify(dict(payload, ok=True))


def _schedule_payload(target_id):
    """대상 종류를 가려 `upcoming_schedule` 을 부른다. 못 찾으면 None.

    **"그 안에서 일어나는 일" 전부다.** 예전에는 site 만 직속 자식 도형까지
    보고 zone 은 자기 것만 봤으며, 식생은 `GeoShape` 가 아니라 어느 층위에서도
    빠졌다. 그 결과 화면과 AI 가 **다른 답**을 했다 — 실측(2026-08-18 김제):
    구역 '3-1' 모달은 예정 0건인데 `search_schedule('3-1')` 은 2건(그 안 식생의
    드론 점검·지게차)이었고, '3포장' 은 1건 대 7건이었다. 사용자가 방금 만든
    예정이 그 구역 화면에 안 보였다.

    이제 AI 도구와 **같은 헬퍼**(`descendant_target_ids`)를 쓴다. 두 벌로 두면
    한쪽만 고쳐지고, 그 어긋남은 "AI 는 아는데 화면은 모른다" 로 나타난다.

      plot  구획에 **닿는** 장치만(구획 안 + 겹치는 장치 영역) — 최하위라
                자손이 없고, 별도 경로(`_plot_schedule`)가 맡는다.
    """
    from aot.aot_flask.geo import device_membership
    from aot.aot_flask.geo.site_summary import upcoming_schedule
    from aot.utils.geo_hierarchy import descendant_target_ids

    shape = GeoShape.query.filter_by(unique_id=target_id).first()
    if shape is not None:
        ids = device_membership.device_ids_in_area(shape.unique_id) or set()
        try:
            kids, _bd = descendant_target_ids(shape, include_self=False)
        except Exception:
            kids = []
            current_app.logger.exception('schedule: 자손 조회 실패')
        return upcoming_schedule(shape, ids, kids)

    from aot.databases.models import GeoPlot
    row = GeoPlot.query.filter_by(unique_id=target_id).first()
    if row is not None:
        from aot.aot_flask.routes_geo_plot import _plot_schedule
        return _plot_schedule(row)

    # 시설은 GeoFacility 이고 도형(GeoShape)이 따로 있다 — 도형으로 옮겨 푼다.
    from aot.databases.models import GeoFacility
    fac = GeoFacility.query.filter_by(unique_id=target_id).first()
    if fac is not None:
        sh = GeoShape.query.filter_by(
            unique_id=getattr(fac, 'shape_uuid', None)).first()
        if sh is not None:
            ids = device_membership.device_ids_in_area(sh.unique_id) or set()
            # 시설 uuid 도 대상에 넣는다 — 일정·노트는 GeoFacility uuid 로
            # 붙는데 장치·기하는 도형 쪽이라, 도형만 보면 방금 만든 일정이
            # 그 시설 화면에서 안 보인다.
            try:
                kids, _bd = descendant_target_ids(sh, include_self=False)
            except Exception:
                kids = []
            return upcoming_schedule(sh, ids, list(kids) + [fac.unique_id])
        return {'own': [], 'devices': []}
    return None


@blueprint.route('/api/geo/schedule', methods=['POST'])
@login_required
def api_schedule_create():
    """어느 계층에든 일정 하나를 만든다.

    본문: `{target_id, date:'YYYY-MM-DD', time:'HH:MM', content, worker?}`

    **대상은 uuid 로 온다** — 이름으로 고르지 않는다. 이름 리졸버는 같은
    작물이 두 구역에 있을 때 하나를 골라버리는 문제가 있어 구역을 돌려주도록
    정해져 있고(설계 §이름 해석), 이 경로는 사람이 그 모달을 열어 놓고 쓰므로
    고를 것이 없다.

    `action_type='human'` 이라 장치를 움직이지 않는다(APScheduler 트리거 없음).

    **지도 모달은 더 이상 이 경로를 쓰지 않는다**(2026-08-18). 예정을 만드는
    자리는 노트 하나로 모았다 — 노트 본문의 한 구간을 골라 시각을 주면
    `/notes/<id>/schedule` 이 같은 헬퍼(`_create_human_schedule`)를 부른다.
    이 라우트는 API 계약으로 남긴다. **여기에 기대어 새 UI 를 만들지 말 것** —
    화면에 두 번째 입력 경로가 생기는 순간 "쓰기 전에 종류 고르기" 로 되돌아간다.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

    data = request.get_json(silent=True) or {}
    target_id = (data.get('target_id') or '').strip()
    content = (data.get('content') or '').strip()
    date_str = (data.get('date') or '').strip()
    if not target_id:
        return jsonify({'ok': False, 'message': 'target_id required'}), 400
    if not content:
        return jsonify({'ok': False, 'message': _('Enter what to do')}), 400
    if not date_str:
        return jsonify({'ok': False, 'message': _('Enter a date')}), 400

    label, kind = _schedule_target_label(target_id)
    if label is None:
        return jsonify({'ok': False, 'message': 'target not found'}), 404

    return _create_human_schedule(
        target_id, kind, label, date_str,
        (data.get('time') or '').strip(),
        content, (data.get('worker') or '').strip())


def _create_human_schedule(target_id, kind, label, date_str, time_str,
                           content, worker):
    """사람이 만든 예정 하나. (flask 응답, 상태코드) 를 돌려준다.

    `/api/geo/schedule`(지도 모달)과 `/notes/<id>/schedule`(노트 구간 선택)이
    **함께 쓴다** — 두 벌로 두면 `propose_job` 의 자가승인 같은 함정을 한쪽
    에서만 지키게 된다.
    """
    time_str = time_str or '09:00'

    from aot.ai.services.aot_data_tool_service import AoTDataToolService as _T
    from aot.ai.services.ai_scheduler_service import AISchedulerService

    anchor_tz, anchor_name, anchor_src = _T._resolve_schedule_anchor(target_id)
    try:
        run_at = _T._schedule_wall_to_utc(date_str, time_str, anchor_tz=anchor_tz)
    except Exception as exc:
        return jsonify({'ok': False,
                        'message': '날짜/시각 형식이 올바르지 않습니다 (%s)' % exc}), 400

    params = {'content': content, 'worker': worker, 'target_type': kind,
              'target_name': label, 'tags': 'human_work'}
    try:
        # ⚠ `propose_job` 은 proposed_by='HUMAN' 이고 승인이 필요 없으면
        # **스스로 approve_job 까지 부른다.** 뒤에서 또 부르면 "not in DRAFT
        # state" 로 죽는데, 행은 이미 만들어진 뒤라 사용자는 "저장 실패" 를
        # 보면서 일정은 생겨 있다(실제로 그렇게 나갔다).
        meta = AISchedulerService.propose_job(
            action_type='human', target_id=target_id, params=params,
            reasoning='[human_schedule] %s @ %s | tags: human_work' % (content, label),
            schedule_time=run_at, proposed_by='HUMAN',
            approval_required=False, source_type='human',
            # 발화 시 스코프를 다시 묻기 위한 신원(§8-7). 'human' 예약은
            # 장치를 움직이지 않지만, 소유자를 남기는 규칙은 예약 종류마다
            # 갈리지 않아야 한다 — 갈리면 어느 종류가 검사되는지 세야 한다.
            user_id=utils_general.current_user_id())
        meta.anchor_tz = anchor_name
        meta.anchor_source = anchor_src
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('schedule: 생성 실패')
        return jsonify({'ok': False, 'message': str(exc)}), 500

    # 방금 만든 것이 바로 보여야 한다 — 모달들이 30초 캐시를 다시 읽는다.
    try:
        from aot.aot_flask.geo.site_summary import (
            invalidate_plot_contents, invalidate_zone_contents_all,
            invalidate)
        invalidate_plot_contents(None)
        invalidate_zone_contents_all()
        invalidate()
    except Exception:
        pass

    return jsonify({'ok': True, 'kind': 'schedule', 'job_id': meta.unique_id,
                    'schedule': _schedule_payload(target_id)})


def _schedule_target_label(target_id):
    """(사람이 읽을 이름, 종류) 또는 (None, None)."""
    from aot.databases.models import GeoFacility, GeoPlot

    shape = GeoShape.query.filter_by(unique_id=target_id).first()
    if shape is not None:
        props = (_shape_feature_dict(shape).get('properties') or {})
        return props.get('name') or target_id, shape.type
    row = GeoPlot.query.filter_by(unique_id=target_id).first()
    if row is not None:
        return row.subject or row.name or target_id, 'plot'
    fac = GeoFacility.query.filter_by(unique_id=target_id).first()
    if fac is not None:
        return getattr(fac, 'name', None) or target_id, 'facility'
    return None, None


@blueprint.route('/api/geo/site/<string:site_uuid>/contents', methods=['GET'])
@login_required
def api_geo_site_contents(site_uuid):
    """필지 안 장치 인벤토리 — 센서·출력. 필지 모달의 [환경·제어]가 쓴다.

    **`_build_area_contents` 를 그대로 쓴다.** 구역 모달·구획 모달이 이미 같은
    함수를 쓰고 있고, 따로 만들면 같은 장치를 화면마다 다르게 세게 된다 —
    이 도메인이 정확히 그 실패로 크게 데었다(그 함수의 docstring 참조).
    여기서 하는 일은 **집합을 정하는 것**뿐이다: 필지 안 구역·시설의 장치 전부.

    `device_ids_in_area` 는 site 도형에도 그대로 동작한다(포함 판정은 종류를
    가리지 않는다). 필지 요약(`summary_for_site`)도 같은 집합을 쓰므로 두
    화면의 장치 수가 갈리지 않는다.
    """
    from aot.databases.models import GeoShape as _GS
    from aot.aot_flask.geo.device_membership import device_ids_in_area

    site = _GS.query.filter_by(unique_id=site_uuid).first()
    if not site:
        return jsonify({'ok': False, 'error': 'site not found'}), 404

    inv = _build_area_contents(device_ids_in_area(site_uuid) or set())

    # "켜면 무엇이 함께 젖는가" — 구역 모달과 같은 경고를 단다. 한쪽에만 있으면
    # "필지에서 켜면 안전하다" 는 잘못된 대비가 생긴다.
    try:
        from aot.aot_flask.geo import plot_context
        _cover = plot_context.plots_by_valve_device(site.geo_id)
        for _out in inv['outputs']:
            names = plot_context.covered_subject_names(
                _cover.get(_out['unique_id']))
            if names:
                _out['also_covers'] = names
    except Exception:                                       # noqa: BLE001
        pass

    payload = {'ok': True}
    payload.update(inv)
    # 권한은 캐시 밖에서 매번(구역과 같은 규칙). 필지에는 구역 전용 쓰기
    # (rep_key·output_order)가 없으므로 제어 권한만 낸다.
    payload['can_edit'] = utils_general.user_has_permission(
        'edit_controllers', silent=True)
    return jsonify(payload)


@blueprint.route('/api/geo/site/<string:site_uuid>/summary', methods=['GET'])
@login_required
def api_geo_site_summary(site_uuid):
    """site(필지) 요약 — 하위 구역·시설 상태 + 오늘 할 일 + 노트.

    zone 은 `/contents` 로 인벤토리를 내지만 site 에는 대응물이 없어, 지도에서
    필지를 눌러도 이름과 면적밖에 볼 게 없었다. 집계 본체는
    aot/aot_flask/geo/site_summary.py 에 있다(정본 설계:
    docs/design/map-site-summary.md).

    `?force=1` 은 30초 캐시를 건너뛴다 — 사람이 새로고침을 누른 경우용.
    """
    from aot.aot_flask.geo import site_summary

    force = request.args.get('force') in ('1', 'true', 'yes')
    try:
        payload = site_summary.summary_for_site(site_uuid, force=force)
    except Exception as e:
        current_app.logger.exception("api_geo_site_summary failed")
        return jsonify({'ok': False, 'error': str(e)}), 500

    if payload is None:
        return jsonify({'ok': False, 'error': 'site not found'}), 404

    result = {'ok': True}
    result.update(payload)
    # 권한은 **캐시 밖에서 매번** 채운다(구역 모달과 같은 규칙) — 요약 자체는
    # 30초 캐시라, 안에 넣으면 권한이 바뀌어도 30초 동안 옛 값이 나간다.
    if isinstance(result.get('site'), dict):
        result['site'] = dict(result['site'])
        result['site']['can_edit'] = utils_general.user_has_permission(
            'edit_settings', silent=True)
    return jsonify(result)


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


@blueprint.route('/api/geo/zones/status', methods=['GET'])
@login_required
def api_geo_zones_status():
    """지도의 구역별 대표값·상태 일괄 — 지도 라벨용.

    구역 라벨이 이름만 달고 있어, 어느 구역이 문제인지 알려면 하나씩 열어
    봐야 했다. 시설 bay 칩이 이미 하는 일(대표값 + 밴드색)을 구역으로 올린다.
    """
    from aot.aot_flask.geo.site_summary import zone_status_for_map

    map_uuid = request.args.get('map_uuid', '').strip()
    if not map_uuid:
        return jsonify({'ok': False, 'error': 'map_uuid required'}), 422
    return jsonify({'ok': True, 'zones': zone_status_for_map(map_uuid)})


@blueprint.route('/api/geo/device/<string:device_uuid>/detail', methods=['GET'])
@login_required
def api_geo_device_detail(device_uuid):
    """장치 상세 모달용 묶음 — 정체·소속·상태·작동 시간.

    마커의 소형 팝업은 "지도 위에서 빠른 제어"라는 고유 가치가 있어 그대로
    두고(팝업 높이가 커지면 anchor 계산이 깨진다), 이력·소속·노트처럼 파고드는
    정보는 이 응답으로 중앙 모달이 받는다.
    """
    from aot.databases.models import (
        CustomController, DeviceMeasurements, Function, Input, Output,
        OutputChannel)
    from aot.aot_flask.geo.site_summary import (
        parent_area_for_device, status_from)

    channel = request.args.get('channel', '0')

    name = kind = None
    for model, label in ((Input, 'input'), (Output, 'output'),
                         (CustomController, 'custom'), (Function, 'function')):
        row = model.query.filter_by(unique_id=device_uuid).first()
        if row is not None:
            name, kind = row.name, label
            break
    if kind is None:
        return jsonify({'ok': False, 'error': 'device not found'}), 404

    # 복합장치(Device)는 CustomController 와 같은 테이블에 있다 — 가르는 기준은
    # 행이 아니라 그 행의 device 모듈이 is_device 를 선언했는지다
    # (device_module_names 가 유일한 판정처, collect_devices 와 같은 규칙).
    if kind == 'custom':
        try:
            from aot.utils.functions import device_module_names
            if getattr(row, 'device', None) in device_module_names():
                kind = 'device'
        except Exception:
            current_app.logger.debug('device_module_names lookup failed')

    # 개폐형(3-way)인가. 지도 마커가 쓰는 판정과 **같은 집합**을 본다
    # (utils_geo.THREE_WAY_OUTPUT_TYPES = PAIRED_ACTUATOR_OUTPUT_TYPES).
    # 이걸 안 보내면 모달이 개폐 3버튼 대신 ON/OFF 토글을 그린다 — 창문을
    # 여닫는 장치에 켜기/끄기 스위치가 달린다.
    control_kind = 'on_off'
    if kind == 'output':
        output_type = getattr(row, 'output_type', None)
        try:
            from aot.outputs.paired_actuator_common import (
                PAIRED_ACTUATOR_OUTPUT_TYPES)
            if output_type in PAIRED_ACTUATOR_OUTPUT_TYPES:
                control_kind = 'value_3way'
        except Exception:
            current_app.logger.debug('paired actuator type lookup failed')

        # PWM(듀티) 출력이면 켜기/끄기가 아니라 0~100% 를 정하는 장치다.
        # 판정은 출력 모듈이 선언한 채널 타입으로 한다 — output_type 이름으로
        # 넘겨짚으면 모듈이 늘 때마다 여기를 고쳐야 한다.
        # 모듈 import 가 실패하는 환경(GPIO 없는 컨테이너 등)에서는 조용히
        # on_off 로 남는다. 잘못된 UI 를 그리느니 기본형이 낫다.
        if control_kind == 'on_off' and output_type:
            try:
                from aot.utils.outputs import parse_output_information
                info = (parse_output_information() or {}).get(output_type) or {}
                types = set()
                for ch in (info.get('channels_dict') or {}).values():
                    types.update(ch.get('types') or [])
                if 'pwm' in types:
                    control_kind = 'pwm'
            except Exception:
                current_app.logger.debug('output module type lookup failed')

    # 복합장치는 그릇이다 — 안에 든 Input/Output 이 곧 이 장치의 내용물이다.
    # 그릇만 보여 주면 "이 장치가 무엇을 재고 무엇을 움직이는가"를 알 수 없다.
    children = []
    if kind == 'device':
        for model, label in ((Input, 'input'), (Output, 'output')):
            for child in model.query.filter_by(
                    parent_device_id=device_uuid).order_by(model.name).all():
                children.append({'uuid': child.unique_id,
                                 'name': child.name,
                                 'kind': label})

    # 채널 목록 — Input 은 측정 채널, Output 은 출력 채널.
    channels = []
    if kind == 'input':
        for dm in DeviceMeasurements.query.filter_by(
                device_id=device_uuid).order_by(DeviceMeasurements.channel).all():
            channels.append({'channel': dm.channel,
                             'name': dm.name or dm.measurement or ''})
    elif kind == 'output':
        for oc in OutputChannel.query.filter_by(
                output_id=device_uuid).order_by(OutputChannel.channel).all():
            channels.append({'channel': oc.channel,
                             'name': oc.name or str(oc.channel)})

    runtime = {'elapsed_sec': None, 'last_duration_sec': None,
               'next_schedule': None, 'schedules': []}
    if kind in ('output', 'function', 'custom'):
        from aot.utils import runtime as _runtime
        try:
            runtime['elapsed_sec'] = _runtime.get_elapsed_seconds(
                device_uuid, channel) or None
        except Exception:
            pass
        if not runtime['elapsed_sec']:
            try:
                runtime['last_duration_sec'] = _runtime.get_last_duration(
                    device_uuid, channel) or None
            except Exception:
                pass
        # 모달의 '예약 상황' 블록은 이 목록을 그대로 그린다 — 라벨과 같은
        # 조회에서 나와야 한쪽만 갱신되는 순간이 없다.
        runtime['schedules'] = pending_schedules(device_uuid)
        runtime['next_schedule'] = (runtime['schedules'][0]['start']
                                    if runtime['schedules'] else None)

    return jsonify({
        'ok': True,
        'device': {'uuid': device_uuid, 'name': name, 'kind': kind,
                   'channel': channel, 'channels': channels,
                   'children': children, 'control_kind': control_kind},
        'parent': parent_area_for_device(device_uuid),
        'status': status_from({device_uuid}),
        'runtime': runtime,
    })


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


def _schedule_display_tz(target_id):
    """예약 시각을 보여줄 시간대 — 장치 로컬(timezone-management.md §6)."""
    try:
        from aot.utils.device_tz import resolve_location_tz
        return resolve_location_tz(target_id)
    except Exception:
        return None


def _fmt_schedule_when(when_utc, tzinfo, now_local):
    """UTC datetime → 표시 문자열. 오늘 'HH:MM' · 내일 'HH:MM(+1)' · 그 외 'M/D HH:MM'."""
    from datetime import timedelta, timezone as _tz
    when = when_utc.replace(tzinfo=_tz.utc)
    if tzinfo is not None:
        when = when.astimezone(tzinfo)
    if when.date() == now_local.date():
        return when.strftime('%H:%M')
    if when.date() == (now_local + timedelta(days=1)).date():
        return when.strftime('%H:%M') + '(+1)'
    return when.strftime('%-m/%-d %H:%M')


def pending_schedules(target_id, limit=20):
    """이 장치에 걸린 예약 — 설정 모달의 '예약 상황' 블록용.

    라벨(_next_schedule_label)은 다음 하나를 문자열로만 준다. 모달은 시작·종료·
    작동 시간을 각각 보여주고 취소까지 해야 하므로 job_id 와 초 단위 값이 필요하다.

    **정본은 서버다.** 예약을 브라우저에 저장하면 같은 예약이 다른 사람에게도,
    같은 사람의 다른 기기에도 보이지 않는다 — 예약은 브라우저를 닫아도 실행되는
    것이므로 화면만 모르는 상태가 된다.
    """
    from datetime import timedelta, timezone as _tz

    from aot.databases.models.scheduler import SchedulerJobMeta
    from aot.utils.time_utils import utc_now

    try:
        now = utc_now().replace(tzinfo=None)
        q = (SchedulerJobMeta.query
             .filter(SchedulerJobMeta.target_id == target_id,
                     SchedulerJobMeta.state.in_(('DRAFT', 'PENDING', 'RUNNING')),
                     SchedulerJobMeta.schedule_time.isnot(None),
                     SchedulerJobMeta.schedule_time >= now)
             .order_by(SchedulerJobMeta.schedule_time.asc()))
        cap = max(1, int(limit))
        rows = q.limit(cap + 1).all()
        # 상한을 넘겼다는 사실을 숨기지 않는다 — 조용히 자르면 화면은 "이게
        # 전부" 라고 말하게 되고, 안 보이는 예약이 시간에 맞춰 장치를 움직인다.
        # 한 건 더 읽어 초과 여부만 보고, 목록 자체는 상한까지만 돌려준다.
        overflow = len(rows) > cap
        rows = rows[:cap]
        if not rows:
            return []

        tzinfo = _schedule_display_tz(target_id)
        now_local = utc_now().astimezone(tzinfo) if tzinfo is not None else utc_now()

        out = []
        for row in rows:
            dur = int(row.duration_sec or 0) or None
            end_utc = row.end_time
            if end_utc is None and dur:
                end_utc = row.schedule_time + timedelta(seconds=dur)
            out.append({
                'job_id': row.id,
                'state': row.state,
                'start': _fmt_schedule_when(row.schedule_time, tzinfo, now_local),
                'start_epoch': int(row.schedule_time.replace(
                    tzinfo=_tz.utc).timestamp()),
                'duration_sec': dur,
                'end': (_fmt_schedule_when(end_utc, tzinfo, now_local)
                        if end_utc is not None else None),
            })
        if overflow:
            out[-1]['more'] = True
        return out
    except Exception:
        current_app.logger.debug('pending schedule lookup failed for %s', target_id)
        return []


def _next_schedule_label(target_id):
    """이 장치의 다음 예약 — 장치 현지 시각 'HH:MM'(오늘이 아니면 'M/D HH:MM').

    pending_schedules 의 첫 줄을 그대로 쓴다 — 라벨과 모달이 같은 조회에서
    나오지 않으면 한쪽만 갱신되는 순간이 생긴다.
    """
    rows = pending_schedules(target_id, limit=1)
    return rows[0]['start'] if rows else None


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


@blueprint.route('/api/geo/function/<string:kind>/<string:func_uuid>/activate', methods=['POST'])
@login_required
def api_geo_function_activate(kind, func_uuid):
    """함수(CustomController/Conditional/Trigger/PID/Function) 활성 토글."""
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    data = request.get_json(force=True, silent=True) or {}
    active = bool(data.get('active', True))

    try:
        from aot.aot_flask.utils import (
            utils_controller, utils_conditional, utils_pid, utils_trigger,
        )
        if kind == 'custom':
            msgs = (utils_controller.controller_activate(func_uuid) if active
                    else utils_controller.controller_deactivate(func_uuid))
        elif kind == 'conditional':
            msgs = (utils_conditional.conditional_activate(func_uuid) if active
                    else utils_conditional.conditional_deactivate(func_uuid))
        elif kind == 'pid':
            msgs = (utils_pid.pid_activate(func_uuid) if active
                    else utils_pid.pid_deactivate(func_uuid))
        elif kind == 'trigger':
            msgs = (utils_trigger.trigger_activate(func_uuid) if active
                    else utils_trigger.trigger_deactivate(func_uuid))
        elif kind == 'function':
            # Function 타입은 별도 activate util 없음 — DB 직접 갱신 후 데몬 reload
            row = Function.query.filter_by(unique_id=func_uuid).first()
            if not row:
                return jsonify({'ok': False, 'error': 'not found'}), 404
            row.is_activated = active
            db.session.commit()
            msgs = [{'success': True}]
        else:
            return jsonify({'ok': False, 'error': 'unknown kind'}), 422

        success = any(getattr(m, 'get', lambda k, d=None: d)('success', False)
                      if hasattr(m, 'get') else bool(m)
                      for m in (msgs or []))
        return jsonify({'ok': True, 'active': active, 'success': success})
    except Exception as e:
        current_app.logger.exception("api_geo_function_activate failed")
        return jsonify({'ok': False, 'error': str(e)}), 500


@blueprint.route('/api/geo/zone/<string:zone_uuid>/photo', methods=['POST'])
@login_required
def api_geo_zone_photo(zone_uuid):
    """Zone 대표사진 업로드 (edit_settings 이상). multipart field: photo"""
    import os
    import time as _time
    import uuid as _uuid
    from aot.config import PATH_GEO_ZONE_PHOTOS
    from aot.aot_flask.extensions import db as _db
    from werkzeug.utils import secure_filename

    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    file = request.files.get('photo')
    if not file or not file.filename:
        return jsonify({'ok': False, 'error': 'photo file required'}), 400

    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    if ext not in ('png', 'jpg', 'jpeg', 'gif', 'webp'):
        return jsonify({'ok': False, 'error': 'file type not allowed'}), 400

    unique_filename = '{}_{}'.format(_uuid.uuid4(), filename)
    os.makedirs(PATH_GEO_ZONE_PHOTOS, exist_ok=True)
    file.save(os.path.join(PATH_GEO_ZONE_PHOTOS, unique_filename))

    # dict() 필수 — 제자리 수정은 SQLAlchemy 가 못 본다(rep_key 라우트 주석).
    meta = dict(zone.meta_json or {})
    old_fn = meta.get('photo_filename')
    if old_fn:
        old_path = os.path.join(PATH_GEO_ZONE_PHOTOS, old_fn)
        if os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    photo_url = '/geo_zone_photo/' + unique_filename
    meta['photo_url'] = photo_url
    meta['photo_filename'] = unique_filename
    zone.meta_json = meta
    _db.session.commit()

    from aot.aot_flask.geo.site_summary import invalidate_zone_contents
    invalidate_zone_contents(zone_uuid)
    return jsonify({'ok': True, 'photo_url': photo_url, 'ts': _time.time()})


@blueprint.route('/geo_zone_photo/<path:filename>', methods=['GET'])
@login_required
def serve_geo_zone_photo(filename):
    """Zone 대표사진 서빙."""
    import os
    from flask import send_file, abort
    from aot.config import PATH_GEO_ZONE_PHOTOS

    base = os.path.realpath(PATH_GEO_ZONE_PHOTOS)
    file_path = os.path.realpath(os.path.join(base, filename))
    if not file_path.startswith(base + os.sep) or not os.path.isfile(file_path):
        return abort(404)
    return send_file(file_path)


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


@blueprint.route('/api/geo/shape/<string:shape_uuid>/description',
                 methods=['POST'])
@login_required
def api_geo_shape_description(shape_uuid):
    """도형(필지·구역)의 설명 — 사람이 적는 한 문단.

    **`meta_json` 에 담는다.** `feature` 가 아닌 이유가 중요하다 — 도형 저장
    (`save_overlays`)은 `feature` 를 통째로 갈아 끼우므로, 거기 두면 지도에서
    도형을 한 번 다시 그리는 것만으로 설명이 사라진다. `meta_json` 은 그 경로가
    건드리지 않는다(실측: `geo_overlays.py` 에 `meta_json` 참조 0건).
    사진(`photo_url`)·대표 측정(`rep_key`)이 이미 같은 자리를 쓴다.

    site 와 zone 이 같은 `GeoShape` 라 **한 라우트가 둘 다 받는다.** 계층마다
    엔드포인트를 따로 두면 같은 검증이 두 벌이 되고, 이 도메인은 그 실패를
    이미 겪었다.
    """
    if not utils_general.user_has_permission('edit_settings'):
        return jsonify({'ok': False, 'error': 'Insufficient permission'}), 403

    shape = GeoShape.query.filter_by(unique_id=shape_uuid).first()
    if not shape:
        return jsonify({'ok': False, 'error': 'shape not found'}), 404

    body = request.get_json(force=True, silent=True) or {}
    desc = body.get('description')
    if desc is None:
        return jsonify({'ok': False, 'error': 'description required'}), 422
    desc = str(desc).strip()
    if len(desc) > 2000:
        return jsonify({'ok': False, 'error': 'description too long'}), 422

    # dict() 필수 — 제자리 수정은 SQLAlchemy 가 못 본다(rep_key 라우트 주석).
    meta = dict(shape.meta_json or {})
    if desc:
        meta['description'] = desc
    else:
        meta.pop('description', None)      # 비우면 지운다
    shape.meta_json = meta
    db.session.commit()

    # 필지 요약은 30초 캐시라, 비우지 않으면 방금 적은 설명이 다음 갱신까지
    # 안 보인다("저장했는데 화면이 그대로").
    #
    # 이 도형이 site 면 자기 캐시를, zone 이면 자기 내용 캐시와 **상위 site 의
    # 요약**을 함께 버린다(필지 요약이 자식 이름을 싣는다). `invalidate_rep` 가
    # 같은 이유로 같은 일을 한다 — 전체 `invalidate()` 는 부르지 않는다:
    # `_PARENT_CACHE` 까지 날아가 지도 도형 전량을 다시 훑게 된다.
    try:
        from aot.aot_flask.geo import site_summary
        site_summary.invalidate(shape_uuid)
        site_summary.invalidate_zone_contents(shape_uuid)
        parent = site_summary.parent_site_for_shape(shape_uuid)
        if parent:
            site_summary.invalidate(parent['uuid'])
    except Exception:                                       # noqa: BLE001
        pass
    return jsonify({'ok': True, 'description': desc})


@blueprint.route('/api/geo/zone/<string:zone_uuid>/rep_key', methods=['POST'])
@login_required
def api_geo_zone_rep_key(zone_uuid):
    """구역의 대표 측정 지정 — 현재 블록에서 값을 눌러 정한다.

    도형에 붙인다(`meta_json['rep_key']`). 위젯 옵션에 두면 같은 구역이
    대시보드마다 다른 것을 대표로 내세우고, 지도 라벨·필지 요약·구역 모달이
    서로 다른 값을 말하게 된다.

    `key` 가 비면 지정 해제(우선순위 기본값으로 돌아간다). 값이 실제로
    존재하는 측정인지 검사하지 않는다 — 센서가 잠시 죽어도 지정은 남아야
    하고, `_pick_rep` 이 값이 없을 때만 우선순위로 물러선다.
    """
    from aot.aot_flask.extensions import db as _db

    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    body = request.get_json(force=True, silent=True) or {}
    key = body.get('key')
    if key is not None and not isinstance(key, str):
        return jsonify({'ok': False, 'error': 'key must be a string or null'}), 422
    key = (key or '').strip() or None

    # dict() 로 **새 객체**를 만든다. meta_json 은 MutableDict 가 아닌 평범한
    # JSON 컬럼이라, 기존 dict 를 제자리에서 고치고 같은 객체를 도로 대입하면
    # SQLAlchemy 가 변경을 못 알아채고 UPDATE 를 아예 내지 않는다 — 에러 없이
    # 저장만 안 된다. meta_json 이 비어 있을 때는 `or {}` 가 새 dict 를 만들어
    # 우연히 동작하므로, 다른 값이 이미 있는 구역에서만 조용히 실패한다.
    meta = dict(zone.meta_json or {})
    if key:
        meta['rep_key'] = key
    else:
        meta.pop('rep_key', None)
    zone.meta_json = meta
    _db.session.commit()

    # 구역 모달·지도 라벨·필지 요약 셋이 이 값을 쓴다 — 하나만 버리면 라벨이
    # 60초 동안 옛 대표를 계속 내건다.
    from aot.aot_flask.geo.site_summary import invalidate_rep
    invalidate_rep(zone)
    return jsonify({'ok': True, 'rep_key': key})


# [현황] 카드에서 뺄 항목 — 항목이 많아지면 화면이 읽히지 않는다. 무엇을 빼도
# 되는지는 그 자리를 쓰는 사람만 안다(노지에 실내 습도 줄, 창이 없는 시설에
# 환기 면적 줄).
#
# `rep_key` 와 **같은 자리·같은 규칙**이다(도형 meta_json). 저장 실패를 조용히
# 넘기지 않도록 카드 이름을 검사한다 — 오타 하나가 아무 데도 안 쓰이는 키를
# 만들어 두면 화면은 계속 전부 보여 주고 사용자는 저장이 안 된 줄 모른다.
def _save_hidden_rows(shape, body):
    """(오류응답, 저장된 목록) — 저장에 성공하면 오류응답이 None."""
    from aot.aot_flask.extensions import db as _db
    from aot.aot_flask.geo.site_summary import (
        hidden_rows_of, _HIDDEN_ROW_CARDS)

    card = (body.get('card') or '').strip()
    if card not in _HIDDEN_ROW_CARDS:
        return jsonify({'ok': False, 'error': 'unknown card'}), 422, None
    keys = body.get('keys')
    if not isinstance(keys, list):
        return jsonify({'ok': False, 'error': 'keys must be a list'}), 422, None
    keys = [k.strip() for k in keys if isinstance(k, str) and k.strip()]

    # dict() 로 새 객체 — 제자리 수정은 SQLAlchemy 가 못 본다(rep_key 주석).
    meta = dict(shape.meta_json or {})
    rows = dict(meta.get('hidden_rows') or {})
    if keys:
        rows[card] = keys
    else:
        # 전부 켠 상태를 빈 목록으로 남기지 않는다 — 기본값(감춘 것 없음)과
        # 같은 뜻이고, 남겨 두면 무엇이 설정된 것인지 읽는 쪽이 매번 판단해야
        # 한다.
        rows.pop(card, None)
    if rows:
        meta['hidden_rows'] = rows
    else:
        meta.pop('hidden_rows', None)
    shape.meta_json = meta
    _db.session.commit()
    return None, None, hidden_rows_of(shape)


@blueprint.route('/api/geo/zone/<string:zone_uuid>/hidden_rows', methods=['POST'])
@login_required
def api_geo_zone_hidden_rows(zone_uuid):
    """구역 [현황] 카드에서 뺄 항목 — 카드 제목 옆 설정에서 정한다."""
    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    body = request.get_json(force=True, silent=True) or {}
    err, code, rows = _save_hidden_rows(zone, body)
    if err is not None:
        return err, code
    return jsonify({'ok': True, 'hidden_rows': rows})


def _geo_map_state(geo_map):
    """GeoMap.state_json(Text) 안전 파싱 → dict."""
    raw = getattr(geo_map, 'state_json', None)
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


@blueprint.route('/api/geo/map/<string:map_uuid>/site_order', methods=['GET'])
@login_required
def api_geo_map_site_order_get(map_uuid):
    """맵의 사용자 지정 사이트 목록 순서 조회.

    Zone 장치 순서(output_order)와 동일한 정책: 저장된 키 순서를 그대로 반환한다.
    순서는 GeoMap.state_json['site_order'] 에 사이트 식별 키(보통 db_id 문자열)의
    평면 리스트로 보관된다.
    """
    geo_map = GeoMap.query.filter_by(unique_id=map_uuid).first()
    if not geo_map:
        return jsonify({'ok': False, 'error': 'map not found'}), 404
    state = _geo_map_state(geo_map)
    order = state.get('site_order', [])
    if not isinstance(order, list):
        order = []
    zone_order = state.get('zone_order', {})
    if not isinstance(zone_order, dict):
        zone_order = {}
    # Normalize: {site_key: [zone_key, ...]} with all keys as strings.
    zone_order = {
        str(k): [str(x) for x in v]
        for k, v in zone_order.items() if isinstance(v, list)
    }
    return jsonify({
        'ok': True,
        'order': [str(x) for x in order],
        'zone_order': zone_order,
    })


@blueprint.route('/api/geo/map/<string:map_uuid>/site_order', methods=['POST'])
@login_required
def api_geo_map_site_order_save(map_uuid):
    """맵의 사이트 목록 배치 순서 저장 (zone output_order 와 대칭)."""
    from aot.aot_flask.extensions import db as _db

    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    # 그룹 스코프 — 지도는 자기 자신이 부여 단위다.
    if not scope.can_operate('geo_map', map_uuid):
        return jsonify({'ok': False, 'error': scope.deny_message()}), 403

    geo_map = GeoMap.query.filter_by(unique_id=map_uuid).first()
    if not geo_map:
        return jsonify({'ok': False, 'error': 'map not found'}), 404

    body = request.get_json(force=True, silent=True) or {}
    state = _geo_map_state(geo_map)

    # Two partial-update shapes (either or both may be present):
    #   { order: [...] }                       → site display order
    #   { site_key: '...', zone_order: [...] } → one site's zone display order
    touched = False

    if 'order' in body:
        order = body.get('order') or []
        if not isinstance(order, list):
            return jsonify({'ok': False, 'error': 'order must be a list'}), 422
        state['site_order'] = [str(x) for x in order]
        touched = True

    if 'zone_order' in body:
        zorder = body.get('zone_order') or []
        site_key = body.get('site_key')
        if not isinstance(zorder, list):
            return jsonify({'ok': False, 'error': 'zone_order must be a list'}), 422
        if site_key in (None, ''):
            return jsonify({'ok': False, 'error': 'site_key required for zone_order'}), 422
        zmap = state.get('zone_order')
        if not isinstance(zmap, dict):
            zmap = {}
        zmap[str(site_key)] = [str(x) for x in zorder]
        state['zone_order'] = zmap
        touched = True

    if not touched:
        return jsonify({'ok': False, 'error': 'nothing to update'}), 422

    geo_map.state_json = json.dumps(state)
    _db.session.commit()

    return jsonify({'ok': True})


# ── Sub-module route registrations ────────────────────────────────────────
from aot.aot_flask import routes_geo_commissioning  # noqa: E402,F401
from aot.aot_flask import routes_geo_iec            # noqa: E402,F401
from aot.aot_flask import routes_geo_plot       # noqa: E402,F401
# routes_geo_plot 뒤에 와야 한다 — 공용 분할 파라미터 계층을 그쪽에서 가져온다.
from aot.aot_flask import routes_geo_device_split   # noqa: E402,F401
