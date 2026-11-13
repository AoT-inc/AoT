# coding=utf-8
"""routes_geo 의 GeoSetting·주소지 파싱·gg_parks 가져오기·site_order·/geo/design 라우트. blueprint 는 routes_geo 것을 공유한다."""
from flask import render_template, redirect, url_for, current_app, request, jsonify
import json
import math
from flask_login import login_required, current_user
from flask_babel import gettext as _
from aot.aot_flask.utils import utils_general
from aot.databases.models import GeoMap, GeoSetting, GeoLayer, GeoShape, Input
from aot.aot_flask.extensions import db
from aot.utils.inputs import parse_input_information
from aot.aot_flask.utils import utils_geo
from aot.utils import maplibre
from aot.functions.utils.water_net import parts as water_parts
from aot.aot_flask.access import scope
from aot.aot_flask.routes_geo import blueprint  # noqa: E402




# @manual geo/api-reference#design-maps
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

# @manual geo/api-reference#design-maps
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
                # 시작 위치가 없으면 세계 전도(0,0 줌 2) — 도시 리터럴 없음.
                'latitude': lat if lat is not None else 0,
                'longitude': lng if lng is not None else 0,
                'zoom': zoom if zoom is not None else (13 if lat is not None else 2)
            })
        return jsonify(result)
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 500

# @manual geo/settings#default-start-location, geo/settings#design-theme-colors, geo/settings#zoom-settings, geo/settings#zoom-method, geo/settings#performance-rendering, geo/settings#api, geo/api-reference#settings
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
                # MapLibre 라이브러리 로컬 서빙 여부 (미설정 = 로컬, layout.html 참조)
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
                'default_lat': None,
                'default_lng': None,
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
        'search_provider': current_search_provider,
        'terrain_available': maplibre.supports_terrain(utils_geo.get_geo_config().get('terrain'))
    })


# ---------------------------------------------------------------------------
# Parcel Import Routes — address → parcel polygon → Site conversion
# ---------------------------------------------------------------------------

# @manual geo/layers#vworld, geo/parcel-import#prerequisites
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


# @manual geo/design-tool#parcel-import, geo/parcel-import#address-input, geo/parcel-import#import-by-address, geo/api-reference#parcel-import
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


# @manual geo/design-tool#parcel-import, geo/parcel-import#csv-file-format, geo/parcel-import#how-to-import, geo/parcel-import#csv-batch-import_1, geo/api-reference#parcel-import
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


# @manual geo/parcel-import#reviewing-and-saving, geo/parcel-import#save-as-site
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


# @manual geo/design-tool#parcel-import, geo/parcel-import#reviewing-and-saving, geo/parcel-import#save-as-site
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


# @manual geo/design-tool#parcel-import, geo/parcel-import#reviewing-and-saving, geo/parcel-import#save-as-site, geo/api-reference#parcel-import
@blueprint.route('/api/geo/parcel/save_as_site', methods=['POST'])
@login_required
def api_geo_parcel_save_as_site():
    """Save a GeoJSON Feature as a GeoShape(Site) and also create a label_aux for labeling."""
    import json as _json
    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'message': 'permission denied'}), 403
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
    # 그룹 스코프 — 지도는 자기 자신이 부여 단위다(/api/geo/overlays 와 같다).
    if not scope.can_operate('geo_map', map_uuid):
        return jsonify({'ok': False, 'message': scope.deny_message()}), 403
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

# @manual geo/api-reference#parcel-import
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


# @manual geo/api-reference#parcel-import
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
    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403
    data = request.get_json() or {}
    map_uuid = data.get('map_uuid', '').strip()
    if not map_uuid:
        return jsonify({'ok': False, 'error': 'map_uuid required'}), 400
    # 그룹 스코프 — 지도는 자기 자신이 부여 단위다.
    if not scope.can_operate('geo_map', map_uuid):
        return jsonify({'ok': False, 'error': scope.deny_message()}), 403

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
                           equipment_parts=water_parts.panel_catalog(_),
                           design_search_inputs=design_search_inputs))
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


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
    
    # 301 Redirect to Geo Design page where the settings are now a modal.
    # 옛 페이지 템플릿(pages/geo/geo_setting.html)은 지웠다 — 이 return 뒤에
    # 도달 불가능한 render_template 이 남아 있었고, 그것이 그 파일의 유일한
    # 사용처였다. 실제 설정 UI 는 modals/geo_settings_modal.html 이고
    # geo_design.html 이 include 한다.
    return redirect(url_for('routes_geo.page_design'), code=301)

@blueprint.route('/location/entry')
@login_required
def location_entry():
    """
    Location Option Picker.
    Simplified map for selecting device location.
    """
    return render_template('pages/location_option/entry.html')


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


# @manual geo/api-reference#water-network
@blueprint.route('/api/geo/water_net', methods=['GET'])
@login_required
def api_geo_water_net():
    """지도 설비의 물 회로 — 회로·상류 경로·점검 항목. 저장 상태를 읽을 때마다 푼다.

    설계 페이지 전용 읽기라 그 페이지와 같은 역할을 요구하고, 그룹 스코프도 본다.
    """
    map_uuid = (request.args.get('map_uuid') or '').strip()
    if not map_uuid:
        return jsonify({'ok': False, 'message': 'map_uuid required'}), 400

    if not utils_general.user_has_permission('edit_settings', silent=True):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403

    # 그룹 스코프 — 지도는 자기 자신이 부여 단위다.
    if not scope.can_operate('geo_map', map_uuid):
        return jsonify({'ok': False, 'message': scope.deny_message()}), 403

    if not GeoMap.query.filter_by(unique_id=map_uuid).first():
        return jsonify({'ok': False, 'message': 'map not found'}), 404

    from aot.utils import water_net_link
    return jsonify({'ok': True, **water_net_link.report_for_map(map_uuid)})


def _terrain_switch_guard(map_uuid, write=False):
    """지형 바꾸기 API 공통 검사. 통과하면 None, 아니면 (응답, 코드). 쓰기(활성화·되돌리기)는 입력 편집 권한이 필요하다."""
    if not map_uuid:
        return jsonify({'ok': False, 'message': 'map_uuid required'}), 400
    if not utils_general.user_has_permission('edit_controllers' if write else 'edit_settings', silent=True):
        return jsonify({'ok': False, 'message': 'Permission Denied'}), 403
    if not scope.can_operate('geo_map', map_uuid):
        return jsonify({'ok': False, 'message': scope.deny_message()}), 403
    if not GeoMap.query.filter_by(unique_id=map_uuid).first():
        return jsonify({'ok': False, 'message': 'map not found'}), 404
    return None


# @manual geo/api-reference#water-network
@blueprint.route('/api/geo/water_net/terrain_switch', methods=['GET'])
@login_required
def api_geo_water_net_terrain_switch():
    """지형(DEM) 바꾸기 상태 — 지금 DEM·바꿀 수 있는 DEM·되돌릴 수 있는 기록. 키는 싣지 않는다."""
    map_uuid = (request.args.get('map_uuid') or '').strip()
    denied = _terrain_switch_guard(map_uuid)
    if denied:
        return denied
    from aot.utils import water_terrain_switch
    return jsonify({'ok': True, **water_terrain_switch.state()})


# @manual geo/api-reference#water-network
@blueprint.route('/api/geo/water_net/terrain_switch/preview', methods=['POST'])
@login_required
def api_geo_water_net_terrain_switch_preview():
    """다른 DEM 으로 계산하면 달라지는 것 — 시작하거나 지금 상태를 돌려준다. 아무것도 저장·변경하지 않는다.

    타일은 백그라운드가 받는다. 계산 중이면 ``state='warming'`` 이고, 같은 요청을 되풀이해 끝났는지 본다.
    ``restart`` 는 새 후보를 고를 때만 보낸다(관경 등 입력이 바뀌었을 수 있으니 처음부터 다시).
    """
    data = request.get_json(silent=True) or {}
    map_uuid = str(data.get('map_uuid') or '').strip()
    denied = _terrain_switch_guard(map_uuid)
    if denied:
        return denied
    candidate = str(data.get('candidate_id') or '').strip()
    if not candidate:
        return jsonify({'ok': False, 'message': 'candidate_id required'}), 400
    from aot.utils import water_terrain_switch
    return jsonify({'ok': True, **water_terrain_switch.start_preview(map_uuid, candidate, bool(data.get('restart')))})


# @manual geo/api-reference#water-network
@blueprint.route('/api/geo/water_net/terrain_switch/activate', methods=['POST'])
@login_required
def api_geo_water_net_terrain_switch_activate():
    """후보 DEM 만 켠다(다른 DEM 입력은 끈다). 되돌리기 기록을 남긴다."""
    data = request.get_json(silent=True) or {}
    map_uuid = str(data.get('map_uuid') or '').strip()
    denied = _terrain_switch_guard(map_uuid, write=True)
    if denied:
        return denied
    candidate = str(data.get('candidate_id') or '').strip()
    if not candidate:
        return jsonify({'ok': False, 'message': 'candidate_id required'}), 400
    from aot.utils import water_terrain_switch
    got = water_terrain_switch.activate(candidate)
    return jsonify(got), (200 if got.get('ok') else 409)


# @manual geo/api-reference#water-network
@blueprint.route('/api/geo/water_net/terrain_switch/revert', methods=['POST'])
@login_required
def api_geo_water_net_terrain_switch_revert():
    """마지막으로 바꾼 DEM 을 되돌린다(그때 켜져 있던 DEM 입력을 그대로 복원)."""
    data = request.get_json(silent=True) or {}
    map_uuid = str(data.get('map_uuid') or '').strip()
    denied = _terrain_switch_guard(map_uuid, write=True)
    if denied:
        return denied
    from aot.utils import water_terrain_switch
    got = water_terrain_switch.revert()
    return jsonify(got), (200 if got.get('ok') else 409)


# @manual geo/api-reference#water-network
@blueprint.route('/api/geo/water_net/paths', methods=['GET'])
@login_required
def api_geo_water_net_paths():
    """출력마다 그 물이 지나는 배관·부품 id — 지도 위젯이 켜진 출력의 경로를 굵게 그린다.

    도형을 읽는 `/api/geo/overlays` 와 같은 수준의 읽기다(로그인). 설계 기준이라 한 번만 읽으면 된다.
    """
    map_uuid = (request.args.get('map_uuid') or '').strip()
    if not map_uuid:
        return jsonify({'ok': False, 'message': 'map_uuid required'}), 400
    if not GeoMap.query.filter_by(unique_id=map_uuid).first():
        return jsonify({'ok': False, 'message': 'map not found'}), 404
    from aot.utils import water_net_link
    return jsonify({'ok': True, **water_net_link.output_paths(map_uuid)})


# @manual geo/api-reference#map-ordering
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


# @manual geo/api-reference#map-ordering
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
