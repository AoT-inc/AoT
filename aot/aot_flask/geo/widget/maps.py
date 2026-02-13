# coding=utf-8
import logging
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_geo
from aot.config import (
    MAP_API_KEY,
    MAP_DEFAULT_CENTER,
    MAP_DEFAULT_ZOOM,
    MAP_PROVIDER,
    MAP_STYLE_URL,
)
from aot.databases.models import (
    Input,
    Output,
    Misc,
    DeviceMeasurements,
    CustomController,
    GeoMap,
    GeoSetting,
    GeoShape,
    Measurement,
    Unit,
    OutputChannel,
    Trigger,
    Conditional,
    PID
)
from flask_babel import gettext

from sqlalchemy.orm import load_only
from sqlalchemy import or_

# from .options import extract_device_ids, extract_measurements # [Refactor] Moved to internal
from aot.utils.runtime import get_started_at, get_last_duration # [Runtime Service]

logger = logging.getLogger(__name__)


def extract_device_ids(widget_options: dict) -> list:
    """Robustly extract device IDs from various saved option keys."""
    if not widget_options:
        return []
    ids = []
    # Prefer the new key
    keys = [
        'custom_option_device_ids', 
        'device_ids',
        'device_selection_input',
        'device_selection_output',
        'device_selection_function',
    ]
    for key in keys:
        raw = widget_options.get(key)
        if not raw:
            continue
        if isinstance(raw, str):
            parts = [p.strip() for p in raw.split(',') if p.strip()]
            ids.extend(parts)
        elif isinstance(raw, list):
            for entry in raw:
                try:
                    val = str(entry).strip()
                    if val:
                        val = val.split(',')[0].strip()
                        if val:
                            ids.append(val)
                except Exception:
                    continue
    # deduplicate preserving order
    return list(dict.fromkeys(ids))


def extract_measurements(widget_options: dict) -> dict:
    """
    Extract selected measurements from options.
    Returns: { device_id: [{'measurement_id': ..., 'channel': ...}, ...] }
    """
    if not widget_options:
        return {}, False

    measurements_config = {}
    measurements_map_has_any_selection = False
    
    # Keys for multi-select measurement options
    keys = [
        ('measurements_input', 'input'),
        ('measurements_function', 'function'),
        ('measurements_output', 'output'),
    ]

    for key, dev_type in keys:
        raw_val = widget_options.get(f"custom_option_{key}") or widget_options.get(key)
        if raw_val:
            logger.info(f"[AoT Map Opt TRACE] key={key} raw_val={raw_val} (type={type(raw_val)})")
        if not raw_val:
            continue
            
        items = []
        if isinstance(raw_val, str):
            items = [s.strip() for s in raw_val.split(',') if s.strip()]
        elif isinstance(raw_val, list):
            items = raw_val
            
        if items:
            measurements_map_has_any_selection = True
            
        for entry in items:
            # Format: "device_id::measurement_id" or "device_id,measurement_id"
            if not isinstance(entry, str):
                continue
                
            d_id, m_id = None, None
            if '::' in entry:
                parts = entry.split('::', 1)
                if len(parts) == 2:
                    d_id, m_id = parts[0].strip(), parts[1].strip()
            elif ',' in entry:
                parts = entry.split(',', 1)
                if len(parts) == 2:
                    d_id, m_id = parts[0].strip(), parts[1].strip()
            
            if not d_id or not m_id:
                continue

            if d_id not in measurements_config:
                measurements_config[d_id] = []
                
            measurements_config[d_id].append({
                'measurement_id': m_id,
                'device_type': dev_type
            })

    return measurements_config, measurements_map_has_any_selection



def generate_page_variables_logic(widget_unique_id, widget_options):
    """
    Prepare variables for template rendering using modular logic.
    """
    legacy_device_ids = extract_device_ids(widget_options or {})
    measurements_config, measurements_map_has_any_selection = extract_measurements(widget_options or {})
    
    # [Guaranteed Log] Trace widget options
    logger.info(f"\n[AoT Map TRACE] widget_unique_id: {widget_unique_id}")
    logger.info(f"[AoT Map TRACE] widget_options: {widget_options}")
    logger.info(f"[AoT Map TRACE] measurements_config: {measurements_config}\n")
    
    measurements_map = {}
    measurement_device_ids = []

    if measurements_config:
        all_meas_ids = []
        for dev_id, meas_list in measurements_config.items():
            for m in meas_list:
                all_meas_ids.append(m['measurement_id'])
        
        if all_meas_ids:
            meas_query = DeviceMeasurements.query.filter(
                DeviceMeasurements.unique_id.in_(all_meas_ids)
            ).options(load_only(
                DeviceMeasurements.unique_id, 
                DeviceMeasurements.name, 
                DeviceMeasurements.measurement, 
                DeviceMeasurements.channel,
                DeviceMeasurements.unit,
                DeviceMeasurements.rescaled_unit
            )).all()
            
            meas_lookup = {m.unique_id: m for m in meas_query}
            
            meas_lookup = {m.unique_id: m for m in meas_query}
            
            # [New] Fetch Device Names for Measurements Panel
            dev_name_lookup = {}
            # Group By Type
            ids_by_type = {'input': [], 'output': [], 'function': []}
            for dev_id, meas_list in measurements_config.items():
                if not meas_list: continue
                # Assume first item type is representative or check all? Usually same device.
                dt = meas_list[0].get('device_type', 'input')
                if dt == 'output': ids_by_type['output'].append(dev_id)
                elif dt == 'input': ids_by_type['input'].append(dev_id)
                else: ids_by_type['function'].append(dev_id) # catch-all for func/pid/etc

            if ids_by_type['input']:
                for r in Input.query.filter(Input.unique_id.in_(ids_by_type['input'])).options(load_only(Input.unique_id, Input.name)).all():
                    dev_name_lookup[r.unique_id] = r.name
            if ids_by_type['output']:
                for r in Output.query.filter(Output.unique_id.in_(ids_by_type['output'])).options(load_only(Output.unique_id, Output.name)).all():
                    dev_name_lookup[r.unique_id] = r.name
            if ids_by_type['function']:
                 # Check each table? Or just CustomController? Functions include PID, etc.
                 # Simplified: Try CustomController, PID, Trigger
                 # If needed, we can expand. For now, try common ones.
                 for Model in [CustomController, PID, Trigger, Conditional]:
                     for r in Model.query.filter(Model.unique_id.in_(ids_by_type['function'])).options(load_only(Model.unique_id, Model.name)).all():
                         dev_name_lookup[r.unique_id] = r.name

            for dev_id, meas_list in measurements_config.items():
                measurements_map[dev_id] = []
                for m_conf in meas_list:
                    m_id = m_conf['measurement_id']
                    if m_id in meas_lookup:
                        meas = meas_lookup[m_id]
                        chan = meas.channel if meas.channel is not None else 0
                        
                        measurements_map[dev_id].append({
                            'id': m_id, 
                            'device_unique_id': dev_id, 
                            'channel': chan,
                            'name': f"[CH{chan}] {gettext(meas.name or meas.measurement or '')}".strip(),
                            'meas_name': gettext(meas.name or meas.measurement or ''),
                            'device_type': m_conf['device_type'],
                            'device_name': gettext(dev_name_lookup.get(dev_id) or ''), 
                            'unit': (meas.rescaled_unit or meas.unit or ''), 
                            'last_value': getattr(meas, 'last_value', '')
                        })
                        measurement_device_ids.append(f"{dev_id}::{chan}")

    # [Fix] Strict Device Selection Logic for Map Rendering
    # 1. If 'Show All' is ON -> final_fetch_ids is None (fetch all)
    # 2. If 'Show All' is OFF and Manual List exists -> final_fetch_ids is ONLY manual list
    # 3. If 'Show All' is OFF and Manual List is EMPTY -> final_fetch_ids is measurement list (Fallback)
    
    # [Fix] include_all should strictly respect the saved configuration
    # If devices are manually selected, we should prioritize showing only them.
    include_all = widget_options.get('include_all_devices')
    if include_all is None:
        # If we have manual selections but include_all is unset (legacy), default to False
        if legacy_device_ids or measurement_device_ids:
            include_all = False
        else:
            include_all = True 
    else:
        # Normalize to boolean
        include_all = (include_all == "true" or include_all == "True" or include_all is True)

    if include_all:
        final_fetch_ids = None
    elif legacy_device_ids:
        final_fetch_ids = legacy_device_ids
    else:
        final_fetch_ids = measurement_device_ids

    logger.info(f"[AoT Map Logic] widget: {widget_unique_id} include_all: {include_all} manual_ids: {len(legacy_device_ids)} meas_ids: {len(measurement_device_ids)} final_fetch_count: {len(final_fetch_ids) if final_fetch_ids else 'ALL'}")
    
    layer_mode = widget_options.get('layer_mode', 'default') if widget_options else 'default'
    fallback_lat = widget_options.get('fallback_latitude', None) if widget_options else None
    fallback_lng = widget_options.get('fallback_longitude', None) if widget_options else None
    w_zoom = widget_options.get('default_zoom') if widget_options else None
    raw_map_uuid = (widget_options.get('map_uuid') or widget_options.get('custom_option_map_uuid')) if widget_options else None
    selected_map_uuid = str(raw_map_uuid).strip() if raw_map_uuid else None

    logger.info(f"[AoT Map Logic] widget: {widget_unique_id} map_uuid: {selected_map_uuid} include_all: {include_all}")
    
    period_seconds = widget_options.get('period', 5) if widget_options else 5
    map_locked = bool(widget_options.get('map_locked', False)) if widget_options else False
    hide_controls = bool(widget_options.get('hide_controls', False)) if widget_options else False
    show_drawn_shapes = bool(widget_options.get('show_drawn_shapes', False)) if widget_options else False
    selected_map = None
    if selected_map_uuid:
        selected_map = GeoMap.query.filter_by(unique_id=selected_map_uuid).first()

    if w_zoom is not None and str(w_zoom).strip() != '':
        try:
             default_zoom = float(w_zoom)
        except:
             default_zoom = MAP_DEFAULT_ZOOM
    elif selected_map and selected_map.zoom is not None:
         default_zoom = selected_map.zoom
    else:
         default_zoom = MAP_DEFAULT_ZOOM

    try:
        period_seconds = int(period_seconds)
    except Exception:
        period_seconds = 5
    
    misc = Misc.query.first()
    
    device_shape_opacity = widget_options.get('device_shape_opacity', 50) if widget_options else 50
    
    def to_bool(val, default):
        if val is None: return default
        if isinstance(val, bool): return val
        if isinstance(val, str):
            return val.lower() in ('true', '1', 't', 'y', 'yes')
        return bool(val)

    # device_shape_color = widget_options.get('device_shape_color', '#007bff') if widget_options else '#007bff'
    enable_label_collision = to_bool(widget_options.get('enable_label_collision'), True) if widget_options else True
    label_position = widget_options.get('label_position', 'bottom') if widget_options else 'bottom'
    label_spacing = int(widget_options.get('label_spacing', 0)) if widget_options else 0
    show_device_labels = to_bool(widget_options.get('show_device_labels'), True) if widget_options else True
    show_device_shapes = to_bool(widget_options.get('show_device_shapes'), True) if widget_options else True
    show_site_label = to_bool(widget_options.get('show_site_label'), True) if widget_options else True
    show_zone_label = to_bool(widget_options.get('show_zone_label'), True) if widget_options else True
    show_length_label = to_bool(widget_options.get('show_length_label'), True) if widget_options else True
    show_site_shape = to_bool(widget_options.get('show_site_shape'), True) if widget_options else True
    show_zone_shape = to_bool(widget_options.get('show_zone_shape'), True) if widget_options else True
    show_facility_shape = to_bool(widget_options.get('show_facility_shape'), True) if widget_options else True
    show_equipment_shape = to_bool(widget_options.get('show_equipment_shape'), True) if widget_options else True
    site_label_size = widget_options.get('site_label_size', '1.2') if widget_options else '1.2'
    zone_label_size = widget_options.get('zone_label_size', '1.0') if widget_options else '1.0'
    overlay_data_only = to_bool(widget_options.get('overlay_data_only'), False) if widget_options else False

    try:
        device_shape_opacity = int(device_shape_opacity)
        if device_shape_opacity < 0: device_shape_opacity = 0
        if device_shape_opacity > 100: device_shape_opacity = 100
    except Exception:
        device_shape_opacity = 50
    
    map_list = []
    config_map = selected_map
    if not config_map:
        config_map = GeoMap.query.order_by(GeoMap.updated_at.desc()).first()
    
    if not selected_map_uuid and config_map:
        selected_map_uuid = config_map.unique_id

    sites_in_map = []
    overlay_map_ids = set()
    map_provider_val = MAP_PROVIDER
    map_style_url_val = MAP_STYLE_URL
    map_api_key_val = MAP_API_KEY
    map_use_satellite = False
    
    if config_map:
        if config_map.unique_id:
            overlay_map_ids.add(config_map.unique_id)
        if config_map.provider:
            map_provider_val = config_map.provider
        if config_map.style_url:
            map_style_url_val = config_map.style_url
        if config_map.api_key:
            map_api_key_val = config_map.api_key
        if config_map.use_satellite:
            map_use_satellite = True

    saved_layer = widget_options.get('selected_base_layer') or widget_options.get('layer')
    if saved_layer:
        map_provider_val = saved_layer

    common_center = None
    if fallback_lat is not None and fallback_lng is not None:
        try:
            common_center = (float(fallback_lat), float(fallback_lng))
        except Exception:
            pass

    if common_center is None and selected_map:
        if selected_map.latitude is not None and selected_map.longitude is not None:
            common_center = (selected_map.latitude, selected_map.longitude)

    geo_setting = GeoSetting.query.first()
    if common_center is None and geo_setting and geo_setting.default_lat is not None and geo_setting.default_lng is not None:
        common_center = (geo_setting.default_lat, geo_setting.default_lng)

    if common_center is None and misc and misc.map_latitude is not None and misc.map_longitude is not None:
        common_center = (misc.map_latitude, misc.map_longitude)

    if layer_mode == 'default' and map_use_satellite and map_api_key_val:
        layer_mode = 'satellite'

    # [Optimization] Default to Async Loading (User Request to fix 1500ms lag)
    # If not explicitly set to False, default to True.
    async_opt = widget_options.get('async_devices') if widget_options else None
    if async_opt is not None:
        async_devices = bool(async_opt)
    else:
        async_devices = True # Default True

    # If user explicitly requests include_all, we treat it as async capable too,
    # but the primary switch is now async_devices.
    # However, if async_devices is False, we MUST load usage synchronously.
    
    devices = []
    
    if async_devices:
        # Skip synchronous loading
        pass
    else:
        # Load synchronously (Legacy behavior or small scale)
        # [Fix] Use final_fetch_ids (Priority: Manual > Measurement)
        # [Refactor] Device collection now relies on Theme/Individual Design (Decoupled)
        devices = utils_geo.collect_devices(final_fetch_ids, include_all, default_color=None, map_uuid=selected_map_uuid)
    
    data = {} # Empty for SSR
    # [Fix] Populate all configuration dropdown lists and measurements
    config_opts = utils_geo.get_available_config_options()
    available_inputs = config_opts.get('available_inputs', [])
    available_outputs = config_opts.get('available_outputs', [])
    available_functions = config_opts.get('available_functions', [])
    available_measurements_input = config_opts.get('available_measurements_input', [])
    available_measurements_output = config_opts.get('available_measurements_output', [])
    available_measurements_function = config_opts.get('available_measurements_function', [])
    available_maps = config_opts.get('available_maps', [])
    
    # [Fix] Populate Available Maps for SSR
    try:
        from sqlalchemy import or_
        maps = GeoMap.query.filter(or_(GeoMap.category == 'design', GeoMap.category == None)).order_by(GeoMap.updated_at.desc()).all()
        available_maps = [{
            'id': m.unique_id,
            'name': m.name,
            'latitude': m.latitude,
            'longitude': m.longitude,
            'zoom': m.zoom
        } for m in maps]
    except Exception as e:
        logger.error(f"Error fetching variable maps for config: {e}")
        available_maps = []
    
    measurements_map_has_any_selection = bool(measurements_map)
    if not measurements_map_has_any_selection:
        measurements_map = {}

    if measurements_map:
        logger.info(f"[AoT Map Debug] Final measurements_map size: {len(measurements_map)}")
        for dev_id in measurements_map:
            measurements_map[dev_id] = sorted(
                measurements_map[dev_id],
                key=lambda m: m.get('channel') if isinstance(m.get('channel'), (int, float)) else 999
            )
        measurements_map = {k: v for k, v in measurements_map.items() if v}

    selected_map_center = None
    selected_map_zoom = None
    if selected_map:
        if selected_map.latitude is not None and selected_map.longitude is not None:
            selected_map_center = [selected_map.latitude, selected_map.longitude]
        if selected_map.zoom is not None:
            selected_map_zoom = selected_map.zoom

    global_providers = {}
    global_keys = {}
    if geo_setting:
        try:
            import json
            global_providers = json.loads(geo_setting.providers) if geo_setting.providers else {}
            global_keys = json.loads(geo_setting.keys) if geo_setting.keys else {}
        except Exception:
            pass

    geo_config = utils_geo.get_geo_config()
    theme_config = geo_config.get('theme_config', {})
    if isinstance(theme_config, str):
        try:
            import json
            theme_config = json.loads(theme_config)
        except:
            theme_config = {}

    map_global_style = {}
    if config_map:
        if config_map.providers:
            try:
                import json
                map_specific_providers = json.loads(config_map.providers)
                if map_specific_providers:
                    global_providers = map_specific_providers
            except Exception:
                pass
        
        # [New] Prioritize Map-Specific Theme Colors
        state = config_map.state_dict()
        if state:
            map_theme = state.get('theme_config', {})
            if map_theme:
                # Merge map-specific theme into global theme_config
                if not theme_config:
                    theme_config = {}
                theme_config.update(map_theme)
                logger.info(f"[AoT Map Logic] Merged Map-Specific Theme: {map_theme}")

            if 'draw-fill-color' in state:
                map_global_style['fillColor'] = state['draw-fill-color']
            if 'draw-stroke-color' in state:
                map_global_style['color'] = state['draw-stroke-color']
            if 'draw-fill-off-color' in state:
                map_global_style['offColor'] = state['draw-fill-off-color']

            if 'draw-fill-off-color' in state:
                map_global_style['offColor'] = state['draw-fill-off-color']

    map_state_id_val = f"widget-{widget_unique_id}" 
    # Original func signature was (widget_unique_id, widget_options).
    # This func only takes widget_options?
    # Wait, in AoT_map.py, the wrapper calls generate_page_variables_logic(widget_options).
    # So I need to pass widget_unique_id to generate_page_variables_logic?
    # Or extract from options?
    # The original generate_page_variables had widget_unique_id as argument 1.
    # My simplified wrapper passed `generate_page_variables_logic(widget_options)`.
    # I should change wrapper to pass unique_id too or just assume it's lost.
    # It is used for map_state_id_val.
    
    geo_config['theme_config'] = theme_config

    saved_active_names = widget_options.get('active_layers')
    global_layers = geo_config.get('layers', [])
    
    saved_names_list = []
    if saved_active_names is not None:
        if isinstance(saved_active_names, str):
            saved_names_list = [s.strip() for s in saved_active_names.split(',') if s.strip()]
        elif isinstance(saved_active_names, list):
            saved_names_list = saved_active_names

    active_layers = []
    selected_base = widget_options.get('selected_base_layer')
    
    for l in global_layers:
        layer_copy = l.copy()
        layer_name = l.get('name')
        
        is_base = (l.get('is_base') is True) or (l.get('role') == 'base')
        
        if is_base:
            if selected_base:
                layer_copy['visible'] = (layer_name == selected_base)
            else:
                layer_copy['visible'] = l.get('visible', l.get('is_active', l.get('is_default', False)))
        else:
            if saved_active_names is not None:
                layer_copy['visible'] = (layer_name in saved_names_list)
            else:
                layer_copy['visible'] = l.get('visible', l.get('is_active', l.get('is_default', False)))
            
        active_layers.append(layer_copy)
    
    default_zoom = w_zoom
    
    if default_zoom is None and selected_map_zoom is not None:
        default_zoom = selected_map_zoom
    
    if default_zoom is None and geo_setting and geo_setting.zoom is not None:
        default_zoom = geo_setting.zoom

    if default_zoom is None and misc and misc.map_zoom is not None:
        default_zoom = misc.map_zoom
        
    if default_zoom is None:
        default_zoom = MAP_DEFAULT_ZOOM

    try:
        default_zoom = int(default_zoom)
    except:
        default_zoom = MAP_DEFAULT_ZOOM

    label_position = widget_options.get('label_position', 'bottom') if widget_options else 'bottom'

    # [Fix] Fetch ALL measurements for devices on the map (for Popups)
    # Replaced inline logic with reusable function
    all_measurements_map = {}
    if not async_devices and devices:
        all_measurements_map = utils_geo.get_all_measurements_for_map(devices)

    widget_vars = {
        'async_devices': async_devices,
        'devices': devices,
        'all_measurements_map': all_measurements_map, # [New]
        'selected_base_layer': widget_options.get('selected_base_layer'),
        'device_shape_opacity': device_shape_opacity,
        # 'device_shape_color': device_shape_color, # Legacy removed
        'enable_label_collision': enable_label_collision,
        'show_device_labels': show_device_labels,
        'show_site_label': show_site_label,
        'show_zone_label': show_zone_label,
        'show_length_label': show_length_label,
        'show_site_shape': show_site_shape,
        'show_zone_shape': show_zone_shape,
        'show_facility_shape': show_facility_shape,
        'show_equipment_shape': show_equipment_shape,
        'site_label_size': site_label_size,
        'zone_label_size': zone_label_size,
        'overlay_data_only': overlay_data_only,
        'include_all_devices': include_all,
        'device_ids': ",".join(legacy_device_ids) if isinstance(legacy_device_ids, list) else legacy_device_ids,
        'device_ids_str': ",".join(legacy_device_ids) if isinstance(legacy_device_ids, list) else legacy_device_ids, # [Fix] For checkboxes
        'map_device_ids': ",".join(final_fetch_ids) if final_fetch_ids else None, # [Fix] Strictly filtered for map
        'fallback_latitude': fallback_lat,
        'fallback_longitude': fallback_lng,
        'default_zoom': default_zoom,
        'map_provider': map_provider_val,
        'map_api_key': map_api_key_val,
        'map_style_url': map_style_url_val,
        'map_default_center': common_center or MAP_DEFAULT_CENTER,
        'map_default_zoom': default_zoom or MAP_DEFAULT_ZOOM,
        'fallback_center': common_center,
        'map_state_id': map_state_id_val,
        'map_state_key': selected_map_uuid,
        'selected_map_uuid': selected_map_uuid, 
        'map_uuid': selected_map_uuid, # [Alias] for config template
        'period': period_seconds,
        'map_locked': map_locked,
        'hide_controls': hide_controls,
        'show_drawn_shapes': show_drawn_shapes,
        'available_maps': available_maps, 
        'available_inputs': available_inputs,
        'available_outputs': available_outputs,
        'available_functions': available_functions,
        'available_measurements_input': available_measurements_input,
        'available_measurements_output': available_measurements_output,
        'available_measurements_function': available_measurements_function,
        'measurements_input': widget_options.get('measurements_input', ''),
        'measurements_output': widget_options.get('measurements_output', ''),
        'measurements_function': widget_options.get('measurements_function', ''),
        'period': max(5, period_seconds), 
        'map_locked': map_locked,
        'hide_controls': hide_controls,
        'show_drawn_shapes': show_drawn_shapes,
        'measurements_map': measurements_map,
        'map_overlay_ids': list(overlay_map_ids),
        'map_list': map_list,
        'sites_in_map': sites_in_map,
        # 'selected_map_uuid': selected_map_uuid, # Duplicate, removed
        'selected_map_center': selected_map_center,
        'selected_map_zoom': selected_map_zoom,
        'global_providers': global_providers,
        'global_keys': global_keys,
        'map_global_style': map_global_style,
        'widget_unique_id': widget_unique_id,
        'label_position': label_position,
        'label_spacing': label_spacing,
        'max_measure_age': int(widget_options.get('max_measure_age', 300)) if widget_options else 300,
        'input_update_interval': int(widget_options.get('input_update_interval', 300)) if widget_options else 300,
        'show_device_shapes': show_device_shapes,
        'show_facility_shape': show_facility_shape,
        'show_equipment_shape': show_equipment_shape,
        'hide_ui': widget_options.get('hide_ui', False) if widget_options else False,
        'theme_config': theme_config,
        'active_layers': active_layers,
        'geo_config': geo_config, 
    }

    return widget_vars
