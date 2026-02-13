# coding=utf-8
"""
Geo Information Service Routes.
Unified Geo System.
"""
from flask import Blueprint, render_template, redirect, url_for, current_app, request, jsonify, Response, g
import requests
from datetime import datetime
import json
import os
import math
from flask_login import login_required, current_user
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
# [New] GIS Proxy Routes (Specific)
# ---------------------------------------------------------------------------

@blueprint.route('/api/geo/proxy/rainviewer/meta', methods=['GET'])
@login_required
@cache.cached(timeout=300, query_string=True, unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_rainviewer_meta():
    """
    Proxy RainViewer Metadata to avoid client-side CORS/Network issues.
    Fetches https://api.rainviewer.com/public/weather-maps.json server-side.
    """
    try:
        url = 'https://api.rainviewer.com/public/weather-maps.json'
        # Set a reasonable timeout (e.g. 5 seconds) to avoid hanging
        resp = requests.get(url, timeout=5)
        
        if resp.status_code != 200:
             g._proxy_error = True
             return jsonify({'error': f"Upstream error: {resp.status_code}", 'details': resp.text}), 502
             
        return jsonify(resp.json())
    except Exception as e:
        g._proxy_error = True
        current_app.logger.error(f"RainViewer Proxy Error: {e}")
        return jsonify({'error': str(e)}), 502

@blueprint.route('/api/geo/proxy/isric', methods=['GET'])
@login_required
# Cache only successful responses (exclude errors)
@cache.cached(timeout=300, query_string=True, unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_isric():
    """
    Proxy for ISRIC SoilGrids API to avoid CORS.
    Pass query params: lon, lat, property, depth, value
    """
    try:
        # Whitelisted params to forward
        params = {k: v for k, v in request.args.items() if k in ['lon', 'lat', 'property', 'depth', 'value']}
        
        # Validations
        if not params.get('lon') or not params.get('lat'):
            return jsonify({'error': 'Missing coordinates'}), 400
            
        url = 'https://rest.isric.org/soilgrids/v2.0/properties/query'
        
        # Verify=False might be needed for some older ISRIC SSL certs, but usually True is fine.
        # Use timeout.
        resp = requests.get(url, params=params, timeout=5)
        
        if resp.status_code != 200:
            g._proxy_error = True  # Mark as error to skip caching
            return jsonify({'error': f"Upstream error: {resp.status_code}", 'text': resp.text}), 502
            
        return jsonify(resp.json())
        
    except Exception as e:
        g._proxy_error = True  # Mark as error to skip caching
        current_app.logger.error(f"ISRIC Proxy Error: {e}")
        return jsonify({'error': str(e)}), 500

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

@blueprint.route('/api/geo/proxy/openmeteo', methods=['GET'])
@login_required
@cache.cached(timeout=300, query_string=True, unless=lambda: hasattr(g, '_proxy_error') and g._proxy_error)
def api_geo_proxy_openmeteo():
    """
    Proxy for Open-Meteo API (Used by NASA GIBS legends).
    """
    try:
        # Whitelisted params
        # OpenMeteo uses 'latitude', 'longitude', 'current', 'hourly', 'daily', etc.
        params = request.args.to_dict()
        
        if not params.get('latitude') or not params.get('longitude'):
             return jsonify({'error': 'Missing coordinates'}), 400
             
        # Base URL
        url = 'https://api.open-meteo.com/v1/forecast'
        resp = requests.get(url, params=params, timeout=5)
        
        if resp.status_code != 200:
             g._proxy_error = True
             return jsonify({'error': f"Upstream error: {resp.status_code}", 'text': resp.text}), 502
             
        return jsonify(resp.json())
    except Exception as e:
        g._proxy_error = True
        current_app.logger.error(f"OpenMeteo Proxy Error: {e}")
        return jsonify({'error': str(e)}), 500

# ---------------------------------------------------------------------------
# [New] GIS Proxy Routes (Generic)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# [New] GIS Proxy Routes (Generic) - DEPRECATED/REMOVED
# Using Client-Side HTTPS Endpoint instead to reduce server load.
# ---------------------------------------------------------------------------

# @blueprint.route('/api/geo/tile_proxy/<unique_id>/<int:z>/<int:x>/<int:y>', methods=['GET'])
# @login_required
# def api_geo_tile_proxy(unique_id, z, x, y):
#    ... removed ...
#    return Response("Proxy Disabled", status=404)



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
    
    return render_template('pages/geo/geo_design.html', 
                           active_page='geo_design',
                           map_configs=design_maps, 
                           geo_config=utils_geo.get_geo_config())

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
    
    geo_layers = GeoLayer.query.all()
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
    # Using existing template but we should update it to use 'geo_layers'
    return render_template('pages/geo_input.html', 
                           active_page='geo_layer',
                           geo_layers=geo_layers, # Passed as geo_layers
                           gis_inputs=geo_layers, # Alias for legacy template compat
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
        
        for item in layout_data:
            layer_id = item.get('id')
            pos_y = item.get('y')
            
            if layer_id is not None and pos_y is not None:
                layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
                if layer:
                    try:
                        opts = json.loads(layer.options) if layer.options else {}
                    except:
                        opts = {}
                    
                    if opts.get('position_y') != pos_y:
                        opts['position_y'] = int(pos_y)
                        layer.options = json.dumps(opts)
                        
        db.session.commit()
        return jsonify(result='success')

    except Exception as e:
        return jsonify(result='error', message=str(e))

@blueprint.route('/geo/setting', methods=['GET', 'POST'])
@login_required
def page_settings():
    """
    Geo Settings.
    Global configurations.
    """
    if not utils_general.user_has_permission('view_settings'):
        return redirect(url_for('routes_general.home'))
    
    # from aot.utils.map_providers import MAP_PROVIDERS (Deleted)
    
    # helper to get settings
    def _ensure_global_settings():
        inst = GeoSetting.query.first()
        if not inst:
            inst = GeoSetting()
            inst.save()
        return inst

    global_settings = _ensure_global_settings()
    
    if request.method == 'POST':
        if not utils_general.user_has_permission('edit_settings'):
            return "Permission Denied", 403
            
        # 1. Process Providers (Simplified - now handled via GeoLayer DB)
        providers_state = {}
        # Legcay loop removed
        
        # 2. Process Keys (Simplified - legacy keys handled by DB)
        keys_state = global_settings.state_dict().get('keys', {}) or {}
        
        # [New] Global Search Provider
        # Storing inside 'providers' JSON to avoid schema change
        search_provider = request.form.get('search_provider')
        if search_provider:
             providers_state['search_provider'] = search_provider

        global_settings.providers = json.dumps(providers_state)
        global_settings.keys = json.dumps(keys_state)
        
        # 3. Geo Params
        try:
            global_settings.max_zoom = int(request.form.get('max_zoom', 25))
        except:
            global_settings.max_zoom = 25

        try:
            global_settings.max_polygons_device = int(request.form.get('max_polygons_device', 1000))
        except:
            global_settings.max_polygons_device = 1000

        try:
            global_settings.max_polygons_site = int(request.form.get('max_polygons_site', 1000))
        except:
            global_settings.max_polygons_site = 1000

        try:
            global_settings.max_polygons_zone = int(request.form.get('max_polygons_zone', 1000))
        except:
            global_settings.max_polygons_zone = 1000
            
        try:
            global_settings.default_lat = float(request.form.get('default_lat', 37.5665))
        except:
            pass # Keep previous or default if error

        try:
            global_settings.default_lng = float(request.form.get('default_lng', 126.9780))
        except:
            pass 

        try:
            global_settings.zoom = float(request.form.get('default_zoom', 12.0))
        except:
            pass 

        global_settings.digital_zoom = (request.form.get('digital_zoom') == 'true')
        # 4. Layer Modifications (Visibility)
        layer_mods_json = request.form.get('layer_modifications')
        if layer_mods_json:
            current_app.logger.info(f"Geo Setting Layer Mods Received: {layer_mods_json}")
            try:
                mods = json.loads(layer_mods_json)
                for unique_id, changes in mods.items():
                    layer = GeoLayer.query.filter_by(unique_id=unique_id).first()
                    if layer:
                        curr_opts = json.loads(layer.options or '{}')
                        updated = False
                        for k, v in changes.items():
                            if k == 'layer_visible' or k.startswith('channel_visible_'):
                                curr_opts[k] = v
                                updated = True
                        if updated:
                            layer.options = json.dumps(curr_opts)
                            layer.save()
            except Exception as e:
                current_app.logger.error(f"Error saving layer mods: {e}")

        # 5. Theme Configuration
        try:
            theme_conf = global_settings.state_dict().get('theme_config', {}) or {}
            
            # Map form fields to config keys
            theme_keys = [
                'theme_site', 'theme_zone', 'theme_facility', 'theme_equipment', 'theme_device', 
                'theme_input', 'theme_output', 'theme_function',
                'theme_panel_bg', 'theme_panel_opacity',
                'theme_hide_label', 'theme_vis_input', 'theme_vis_output', 'theme_vis_function'
            ]
            
            for key in theme_keys:
                val = request.form.get(key)
                if val is not None:
                    # Strip 'theme_' prefix for storage key if desired, or keep as is.
                    # Let's keep keys clean: 'site', 'zone' etc.
                    clean_key = key.replace('theme_', '')
                    theme_conf[clean_key] = val
            
            global_settings.theme_config = json.dumps(theme_conf)
        except Exception as e:
            current_app.logger.error(f"Error saving theme config: {e}")

        global_settings.save()
        
        # Invalidate Cache
        utils_geo.invalidate_geo_config_cache()
        
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'status': 'success', 'message': 'Settings Saved'})
        
        return redirect(url_for('routes_geo.page_settings'))

    # GET
    saved_state = global_settings.state_dict()
    
    # [Fix] Pass Active GeoLayers for Search Provider selection AND Filter by Key Availability
    # User requested: "Appear according to activation" -> Show only activated layers
    # User requested: "Exclude if API Key missing"
    
    from aot.utils.inputs import parse_input_information
    dict_inputs = parse_input_information()
    
    # Load Global API Keys
    try:
        api_keys = json.loads(global_settings.keys) if global_settings.keys else {}
    except:
        api_keys = {}

    all_active_layers = GeoLayer.query.filter_by(is_activated=True).all()
    valid_search_layers = []
    
    for layer in all_active_layers:
        layer_def = dict_inputs.get(layer.type, {})
        
        # Check if layer requires key
        # Convention: 'key_field' in INPUT_INFORMATION implies key requirement
        if 'key_field' in layer_def:
            key_field = layer_def['key_field']
            global_key_field = layer_def.get('global_key_field', key_field)
            
            # Check Global Key
            has_global_key = bool(api_keys.get(global_key_field))
            
            # Check Local Key Override (in options)
            has_local_key = False
            try:
                opts = json.loads(layer.options or '{}')
                if opts.get(key_field):
                    has_local_key = True
            except:
                pass
            
            if not has_global_key and not has_local_key:
                # Key Missing -> Skip
                continue
                
        valid_search_layers.append(layer)
    
    from flask_wtf.csrf import generate_csrf
    return render_template('pages/geo/geo_setting.html', 
                           active_page='geo_setting',
                           saved_state=saved_state,
                           geo_config=utils_geo.get_geo_config(),
                           geo_layers=valid_search_layers,
                           csrf_token=generate_csrf)

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
