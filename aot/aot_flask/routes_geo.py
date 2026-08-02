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
from aot.aot_flask.utils import utils_general
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
        # [Optimization] Filter by category='design' in SQL to avoid heavy JSON parsing
        all_maps = GeoMap.query.filter_by(category='design').order_by(GeoMap.updated_at.desc()).all()
        result = []
        for m in all_maps:
            state = m.state_dict()
            # Basic metadata for dropdown
            center = state.get('center', [37.5665, 126.9780])
            result.append({
                'unique_id': m.unique_id,
                'name': m.name,
                'latitude': center[0] if isinstance(center, list) and len(center) >= 2 else 37.5665,
                'longitude': center[1] if isinstance(center, list) and len(center) >= 2 else 126.9780,
                'zoom': state.get('zoom', 13)
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
    data = request.get_json()
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
                theme_keys = [
                    'theme_site', 'theme_zone', 'theme_facility', 'theme_equipment', 'theme_device',
                    'theme_input', 'theme_output', 'theme_function',
                    'theme_panel_bg', 'theme_panel_opacity',
                    'theme_hide_label', 'theme_vis_input', 'theme_vis_output', 'theme_vis_function'
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
            
        data = request.get_json()
        result, error = GeoOverlayManager.save_overlays(data)
        
        if error:
            return jsonify({'ok': False, 'message': error}), 500
            
        return jsonify(result)

@blueprint.route('/api/geo/overlays/delta', methods=['POST'])
@login_required
def api_geo_overlays_delta():
    """Efficient Delta Save for individual features"""
    from aot.aot_flask.geo.geo_overlays import GeoOverlayManager
    
    data = request.get_json()
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
    feature['properties']['aot_type'] = 'site'
    # [Fix] Assign node_id — cleanupOrphanLabels finds the parent via
    # label.parent_node_id ↔ site.node_id, so without a node_id the label is
    # deleted as an orphan on every load.
    site_node_id = feature['properties'].get('node_id') or str(_uuid.uuid4())
    feature['properties']['node_id'] = site_node_id

    geo_id = map_uuid or '__parcel_import__'

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
                'aot_type': 'label_aux',
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
@cache.cached(timeout=300, query_string=True, unless=lambda: hasattr(g, '_wms_proxy_error') and g._wms_proxy_error)
def api_geo_proxy_wms(unique_id):
    """
    Server-side WMS tile proxy.

    Fetches a WMS GetMap tile on behalf of the browser to bypass CORS restrictions
    on third-party WMS services (e.g. VWorld) that do not send CORS headers.

    MapLibre uses this URL template:
        /api/geo/proxy/wms/<unique_id>?BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256
    """
    try:
        base_url, leaflet_opts = _get_wms_layer_info(unique_id)
        if base_url is None:
            g._wms_proxy_error = True
            return Response('Layer not found or not configured', status=404)

        bbox = request.args.get('BBOX', '')
        width = request.args.get('WIDTH', '256')
        height = request.args.get('HEIGHT', '256')

        if not bbox:
            g._wms_proxy_error = True
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

        resp = requests.get(base_url, params=wms_params, timeout=15,
                            headers={'Referer': request.host_url})

        content_type = resp.headers.get('Content-Type', 'image/png')
        if resp.status_code != 200 or 'xml' in content_type or 'html' in content_type:
            current_app.logger.warning(
                f'[WMS Proxy] Upstream error {resp.status_code} for {unique_id}: {resp.text[:200]}'
            )
            g._wms_proxy_error = True
            return Response(
                _TRANSPARENT_1X1_PNG,
                status=200,
                content_type='image/png',
                headers={'Cache-Control': 'no-cache'}
            )

        return Response(
            resp.content,
            status=200,
            content_type=content_type,
            headers={'Cache-Control': 'public, max-age=300'}
        )

    except Exception as e:
        # Even if the upstream WMS (e.g. maps.isric.org) is slow or unresponsive and
        # raises an exception (timeout, etc.), do not throw a 500. Otherwise MapLibre
        # endlessly re-requests the tile, flooding the console and obscuring other
        # working overlays. Just like a non-200 response, gracefully degrade with a
        # transparent tile (200) — only the overlay is blank while the map keeps working.
        current_app.logger.warning(f'[WMS Proxy] Exception for {unique_id}: {e}')
        g._wms_proxy_error = True
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

        # Fetch the tile
        import requests
        resp = requests.get(target_url, headers=headers, timeout=10)

        if resp.status_code != 200:
            current_app.logger.warning(f'[Tile Proxy] Non-200 status: {resp.status_code} for {target_url}')
            return Response(
                _TRANSPARENT_1X1_PNG,
                status=200,
                mimetype='image/png'
            )
        
        # Determine content type
        content_type = resp.headers.get('Content-Type', 'image/png')
        
        return Response(
            resp.content,
            status=200,
            content_type=content_type,
            headers={'Cache-Control': 'public, max-age=3600'}
        )
        
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
        
        return jsonify({
            'ok': True, 
            'devices': devices,
            'all_measurements_map': all_measurements_map
        })
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
    design_maps = GeoMap.query.filter_by(category='design').order_by(GeoMap.updated_at.desc()).all()

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

    design_maps = GeoMap.query.filter_by(category='design')\
        .order_by(GeoMap.updated_at.desc()).all()
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
    from aot.utils.outputs import parse_output_information

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
                last_pct, last_src = _get_target_pct(uuid) if ctrl_type == 'value' else (None, None)
                actuator_states[slot_key] = {
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
    }
    return jsonify(runtime)


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


def _shapes_to_geojson(shape_type, default_color):
    """Build a FeatureCollection from GeoShape rows of the given type.

    GeoShape stores the GeoJSON Feature in the `feature` JSON column. The
    hierarchy field is `type` ('site', 'zone', 'feature', 'facility', ...),
    and there is no `name` / `category` column on GeoShape — the human-readable
    name lives inside feature.properties.
    """
    shapes = GeoShape.query.filter_by(type=shape_type).all()
    features = []
    for shape in shapes:
        try:
            feat = _shape_feature_dict(shape)
            geometry = feat.get('geometry')
            if not geometry:
                continue
            props = dict(feat.get('properties') or {})
            props.setdefault('id', shape.unique_id)
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
    """Get all sites as GeoJSON for MapLibre overlay."""
    try:
        return jsonify(_shapes_to_geojson('site', '#DF5353'))
    except Exception as e:
        current_app.logger.exception("api_geo_sites failed")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/api/geo/zones', methods=['GET'])
@login_required
def api_geo_zones():
    """Get all zones as GeoJSON for MapLibre overlay."""
    try:
        return jsonify(_shapes_to_geojson('zone', '#28a745'))
    except Exception as e:
        current_app.logger.exception("api_geo_zones failed")
        return jsonify({'error': str(e)}), 500


@blueprint.route('/api/geo/shapes/<string:category>', methods=['GET'])
@login_required
def api_geo_shapes_by_category(category):
    """Get shapes by hierarchy type (site, zone, facility, feature, ...)."""
    try:
        return jsonify(_shapes_to_geojson(category, '#995aff'))
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
    """Zone 내부 센서·장치·함수 인벤토리 반환."""
    from aot.databases.models import OutputChannel

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

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

    # 상위 site 이름
    site_name = None
    if zone.parent_id:
        parent = GeoShape.query.get(zone.parent_id)
        if parent:
            pf = _shape_feature_dict(parent)
            site_name = (pf.get('properties') or {}).get('name')

    # ── 기하학적 포함 판정 (map_overlay_id 폴백) ─────────────────────────────
    # 장치가 zone 생성 이전에 배치된 경우 map_overlay_id 가 site/다른 shape 의
    # id 로 저장돼 있을 수 있다. zone 폴리곤 내부에 있는 aot_device GeoShape 를
    # 기하학적으로 찾아 보완한다.
    zone_polygon = None
    try:
        from shapely.geometry import shape as _shapely_shape, Point as _Point
        _geom = feat.get('geometry') or {}
        if _geom.get('type') in ('Polygon', 'MultiPolygon'):
            zone_polygon = _shapely_shape(_geom)
    except Exception:
        pass

    def _device_ids_in_zone():
        """zone 폴리곤 안에 좌표가 있는 aot_device GeoShape 의 device_id 집합."""
        if not zone_polygon:
            return set()
        try:
            device_shapes = GeoShape.query.filter_by(
                geo_id=zone.geo_id, type='aot_device').all()
            result = set()
            for ds in device_shapes:
                coords = ((ds.feature or {}).get('geometry') or {}).get('coordinates')
                if not coords or len(coords) < 2:
                    continue
                try:
                    p = _Point(float(coords[0]), float(coords[1]))
                    if zone_polygon.contains(p):
                        result.add(ds.device_id)
                except Exception:
                    pass
            return result
        except Exception:
            return set()

    geo_device_ids = _device_ids_in_zone()

    # 센서 목록 (Input) — map_overlay_id 직접 매칭 + 기하 포함 폴백
    direct_inputs = Input.query.filter_by(map_overlay_id=zone_id).all()
    geo_input_ids = {inp.unique_id for inp in direct_inputs}
    extra_inputs = []
    for dev_id in geo_device_ids:
        if dev_id and dev_id not in geo_input_ids:
            inp = Input.query.filter_by(unique_id=dev_id).first()
            if inp:
                extra_inputs.append(inp)
                geo_input_ids.add(dev_id)
    inputs = direct_inputs + extra_inputs

    from aot.aot_flask.geo.facility_sensors import channel_meta_for_dm
    sensors_out = []
    for inp in inputs:
        meas = DeviceMeasurements.query.filter_by(device_id=inp.unique_id).all()
        channels = [channel_meta_for_dm(m) for m in meas]
        sensors_out.append({
            'unique_id': inp.unique_id,
            'name': inp.name,
            'device': getattr(inp, 'device', ''),
            'is_activated': bool(inp.is_activated),
            'interface': getattr(inp, 'interface', ''),
            'channels': channels,
        })

    # 장치 목록 (Output) — map_overlay_id 직접 매칭 + 기하 포함 폴백
    direct_outputs = Output.query.filter_by(map_overlay_id=zone_id).all()
    geo_out_ids = {out.unique_id for out in direct_outputs}
    extra_outputs = []
    for dev_id in geo_device_ids:
        if dev_id and dev_id not in geo_out_ids:
            out = Output.query.filter_by(unique_id=dev_id).first()
            if out:
                extra_outputs.append(out)
                geo_out_ids.add(dev_id)
    outputs_rows = direct_outputs + extra_outputs

    outputs_out = []
    for out in outputs_rows:
        channels = OutputChannel.query.filter_by(output_id=out.unique_id).order_by(OutputChannel.channel).all()
        ch_list = [{'channel': c.channel, 'name': c.name or str(c.channel)} for c in channels]
        if not ch_list:
            ch_list = [{'channel': 0, 'name': out.name}]
        outputs_out.append({
            'unique_id': out.unique_id,
            'name': out.name,
            'output_type': out.output_type or '',
            'channels': ch_list,
        })

    # 함수 목록 (CustomController + Function + Conditional + Trigger + PID)
    func_rows = []
    for model, kind in [
        (CustomController, 'custom'),
        (Function,         'function'),
        (Conditional,      'conditional'),
        (Trigger,          'trigger'),
        (PID,              'pid'),
    ]:
        for row in model.query.filter_by(map_overlay_id=zone_id).all():
            func_rows.append({
                'unique_id': row.unique_id,
                'name': row.name,
                'kind': kind,
                'is_activated': bool(getattr(row, 'is_activated', False)),
            })

    counts = {
        'sensors': len(sensors_out),
        'outputs': len(outputs_out),
        'functions': len(func_rows),
    }

    meta = zone.meta_json or {}
    photo_url = meta.get('photo_url')
    output_order = meta.get('output_order', [])
    can_edit = utils_general.user_has_permission('edit_settings', silent=True)

    return jsonify({
        'ok': True,
        'zone': {
            'unique_id': zone.unique_id,
            'name': zone_name,
            'site_name': site_name,
            'area_m2': area_m2,
            'counts': counts,
            'photo_url': photo_url,
            'output_order': output_order,
            'can_edit': can_edit,
        },
        'sensors': sensors_out,
        'outputs': outputs_out,
        'functions': func_rows,
    })


@blueprint.route('/api/geo/output/<string:output_uuid>/state', methods=['POST'])
@login_required
def api_geo_output_state(output_uuid):
    """장치(Output) ON/OFF 제어 (세션 인증 래퍼)."""
    if not utils_general.user_has_permission('edit_controllers'):
        return jsonify({'ok': False, 'error': 'permission denied'}), 403

    data = request.get_json(force=True, silent=True) or {}
    state = data.get('state')
    channel = int(data.get('channel', 0))
    duration = data.get('duration')

    if state is None:
        return jsonify({'ok': False, 'error': 'state required'}), 422

    try:
        from aot.aot_client import DaemonControl
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

    meta = zone.meta_json or {}
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
    """Zone 장치 작동 이력 (sensor chart 오버레이용).

    Query params: output_id (필수), hours (기본 24, 최대 168)
    """
    import time as _time
    from aot.utils.influx import query_string, influx_to_list

    zone = GeoShape.query.filter_by(unique_id=zone_uuid, type='zone').first()
    if not zone:
        return jsonify({'ok': False, 'error': 'zone not found'}), 404

    output_id = request.args.get('output_id', '').strip()
    if not output_id:
        return jsonify({'ok': False, 'error': 'output_id required'}), 400

    try:
        hours = min(max(float(request.args.get('hours', 24)), 1.0), 168.0)
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

    meta = zone.meta_json or {}
    meta['output_order'] = [str(x) for x in order]
    zone.meta_json = meta
    _db.session.commit()

    return jsonify({'ok': True})


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
