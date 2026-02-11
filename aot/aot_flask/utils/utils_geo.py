# -*- coding: utf-8 -*-
import json
import logging
from aot.aot_flask.extensions import db
from aot.databases.models import (
    GeoSetting, GeoLayer, GeoMap,
    Input, Output, Misc, DeviceMeasurements, CustomController, GeoShape,
    Measurement, Unit, OutputChannel, Trigger, Conditional, PID
)
from aot.utils.inputs import parse_input_information
from aot.databases import set_uuid
from flask_babel import gettext
from aot.aot_flask.utils.utils_general import custom_options_return_json
from aot.aot_client import DaemonControl
from aot.utils.modules import load_module_from_file
from sqlalchemy.orm import load_only
from sqlalchemy import or_
from aot.utils.runtime import get_started_at, get_last_duration


# Helper wrapper for instantiating Inputs without full DB object
class MockInputDev:
    def __init__(self, layer):
        self.unique_id = layer.unique_id
        self.name = layer.name
        self.custom_options = '{}' # Initialize empty, will override
        self.log_level_debug = False # Required by AbstractInput.setup_logger

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Global Config
# ------------------------------------------------------------------------------
import time

_GEO_CONFIG_CACHE = None
_GEO_CONFIG_TS = 0
_CACHE_TTL = 300 # Restore cache for performance

def invalidate_geo_config_cache():
    global _GEO_CONFIG_CACHE
    _GEO_CONFIG_CACHE = None

def get_geo_config():
    """
    Returns the consolidated Geo configuration for the frontend.
    Includes:
    1. Global Settings (GeoSetting)
    2. Active Layers (GeoLayer)
    """
    global _GEO_CONFIG_CACHE, _GEO_CONFIG_TS
    
    # Return cached if valid
    if _GEO_CONFIG_CACHE and (time.time() - _GEO_CONFIG_TS) < _CACHE_TTL:
        return _GEO_CONFIG_CACHE

    settings = GeoSetting.query.first()
    if settings:
        logger.info(f"[Geo Config Debug] Loaded Theme Config from DB: {settings.theme_config}")

    if not settings:
        settings = GeoSetting()
        settings.save()
        
    config = settings.state_dict()
    
    # [New] Expose Search Provider
    # `state_dict` includes `providers` as parsed dict, so config['providers']['search_provider'] is available if set.
    # explicit set for clarity if needed, but existing logic covers it since `providers` is loaded.
    
    config['search_provider'] = config.get('providers', {}).get('search_provider')

    # Add Active Layers
    # Each layer needs: name, type, url, attribution, etc.
    # We combine DB data (GeoLayer) with static definition (parse_input_information)
    
    # 1. Active Layers
    # Separated logic for clarity
    config['layers'] = get_active_geo_layers(config.get('keys', {}))
    
    # Update Cache
    _GEO_CONFIG_CACHE = config
    _GEO_CONFIG_TS = time.time()
    
    return config

# ------------------------------------------------------------------------------
# Geo Data Helpers
# ------------------------------------------------------------------------------
def get_active_geo_layers(api_keys=None):
    """
    Returns a list of configured, active map layers.
    Merges:
    - Legacy Providers (MAP_PROVIDERS): If enabled in Settings
    - GeoLayer (DB): User settings (enabled, custom name/options)
    - GIS Input Definitions (Static): Default URLs, attributes
    - API Keys (GeoSetting): Global keys
    """
    settings = GeoSetting.query.first()
    if not settings:
         settings = GeoSetting() # Should be saved?
    
    # Reload keys if not provided
    if api_keys is None:
         try:
             api_keys = json.loads(settings.keys) if settings.keys else {}
         except:
             api_keys = {}

    # Load Enabled Providers (Legacy)
    try:
        enabled_providers = json.loads(settings.providers) if settings.providers else {}
    except:
        enabled_providers = {}

    layers_data = []

    # Legacy Providers (Removed)
    
    # 2. Geo Layers (DB)
    active_layers = GeoLayer.query.filter_by(is_activated=True).all()
    dict_inputs = parse_input_information()
    
    # [New] Build a complete API Key map by scanning all layers
    # This allows layers with missing keys to inherit from those that have them.
    for each_layer in active_layers:
        layer_def_temp = dict_inputs.get(each_layer.type, {})
        if 'key_field' in layer_def_temp:
            kf_temp = layer_def_temp['key_field']
            gkf_temp = layer_def_temp.get('global_key_field', kf_temp)
            if gkf_temp not in api_keys:
                try:
                    c_opts_temp = json.loads(each_layer.options) if each_layer.options else {}
                    if c_opts_temp.get(kf_temp):
                        api_keys[gkf_temp] = c_opts_temp.get(kf_temp)
                except:
                    pass
    
    for layer in active_layers:
        layer_def = dict_inputs.get(layer.type, {})
        
        # Merge custom options
        try:
            custom_opts = json.loads(layer.options) if layer.options else {}
        except:
            custom_opts = {}

        # Determine Protocol Type (xyz vs wms)
        protocol_type = layer_def.get('layer_type', 'xyz')
        if 'layer_role' in custom_opts:
            layer_role = custom_opts['layer_role']
        else:
            layer_role = layer_def.get('layer_role', 'base')

        # Base info template
        base_layer_data = {
            'id': layer.unique_id,
            'name': layer.name,
            'type': protocol_type, # MUST be 'xyz' or 'wms' for aot-map-loader
            'z_index': 0,
            # [Fix] Overlays OFF by default, Base OFF by default (prevent auto-loading multiple).
            # Frontend Logic (AoTMapLoader) will fallback to first available or use 'visible' option.
            'is_active': False, 
            'role': layer_role
        }
        # Populate Default Options if missing
        if 'custom_options' in layer_def:
            for opt_def in layer_def['custom_options']:
                opt_id = opt_def.get('id')
                if opt_id and opt_id not in custom_opts:
                    if 'default' in opt_def:
                        custom_opts[opt_id] = opt_def['default']
                        
        # [New] Resource Cache for this execution
        _module_cache = {}
        def _get_input_instance(l_type, l_obj, l_opts):
            cache_key = f"{l_type}_{l_obj.unique_id}"
            if cache_key in _module_cache:
                return _module_cache[cache_key]
            
            try:
                if 'file_path' in layer_def:
                    mod, status = load_module_from_file(layer_def['file_path'], 'inputs')
                    if mod and hasattr(mod, 'InputModule'):
                        mock_dev = MockInputDev(l_obj)
                        inst = mod.InputModule(mock_dev)
                        
                        # Inject options (Ensure API Key present)
                        l_inst_opts = l_opts.copy()
                        if 'key_field' in layer_def:
                            kf = layer_def['key_field']
                            gkf = layer_def.get('global_key_field', kf)
                            if kf not in l_inst_opts and api_keys.get(gkf):
                                l_inst_opts[kf] = api_keys.get(gkf)
                        
                        inst.custom_options = l_inst_opts
                        
                        # Monkey patch
                        def mock_get_option(opt, default=None):
                            return inst.custom_options.get(opt, default)
                        inst.get_custom_option = mock_get_option
                        
                        _module_cache[cache_key] = inst
                        return inst
            except:
                pass
            return None

        # URL Logic
        layer_url = layer_def.get('default_url', '')
        
        # [Fix] Dynamic URL Resolution via InputModule
        inst = _get_input_instance(layer.type, layer, custom_opts)
        if inst:
            layer_url = inst.get_url()
            # If get_url returns None or empty, fallback? 
            # Usually it returns default_url if logic falls through.

        # User Override takes precedence (if explicitly set in form, which saves to 'url' option?)
        # Actually 'url' in custom_options usually comes from Generic WMS overrides.
        if 'url' in custom_opts and custom_opts['url']:
            layer_url = custom_opts['url']
            
        base_layer_data['url'] = layer_url
        
        # Merge Leaflet Options (Technical Overrides like maxNativeZoom)
        if 'leaflet_options' in layer_def:
            l_opts_def = layer_def['leaflet_options']
            for k, v in l_opts_def.items():
                # Only set if not overridden by user custom options
                if k not in custom_opts:
                    custom_opts[k] = v
            
        # Attribution
        if 'attribution' in layer_def:
            base_layer_data['attribution'] = layer_def['attribution']
            
        # Keys
        if 'key_field' in layer_def:
            kf = layer_def['key_field']
            gkf = layer_def.get('global_key_field', kf)
            key_val = api_keys.get(gkf, '')
            base_layer_data['api_key'] = key_val

        # [New] Legend Support (Dynamic)
        # Attempt to load dynamic legend from InputModule first
        if inst:
            try:
                dynamic_legend = inst.get_legend()
                if dynamic_legend:
                    base_layer_data['legend'] = dynamic_legend
            except Exception as e:
                logger.error(f"Error loading dynamic legend for {layer.type}: {e}")

        # Fallback to static legend config if dynamic failed or returned None
        if 'legend' not in base_layer_data and 'legend' in layer_def:
            base_layer_data['legend'] = layer_def['legend']

        # Logic for Channel Architecture (Multi-Layer)
        variations = []
        is_exploded = False
        
        if 'custom_options' in layer_def:
            for opt_def in layer_def['custom_options']:
                # New Channel Logic
                if opt_def.get('type') == 'channel_selector':
                    is_exploded = True
                    opt_id = opt_def['id']
                    
                    # 1. Get Active Channels (List of IDs)
                    raw_val = custom_opts.get(opt_id)
                    
                    # Normalized active IDs list
                    active_ids = []
                    
                    if raw_val is None:
                        # Use default if not saved yet
                        active_ids = opt_def.get('default', [])
                    elif isinstance(raw_val, list):
                        active_ids = raw_val
                    else:
                        # Handle single value edge case
                        active_ids = [raw_val]
                        
                    # Normalize comparison (backend keys are ints usually, json is strs)
                    active_ids_str = [str(x) for x in active_ids]
                    
                    # 2. Iterate Channel Definition
                    channel_def = opt_def.get('channel_def', {})
                    
                    for ch_id, ch_info in channel_def.items():
                        if str(ch_id) in active_ids_str:
                             # Check for Custom Channel Name
                             ch_name_key = f"channel_name_{ch_id}"
                             ch_display_name = custom_opts.get(ch_name_key) or ch_info['name']
                             
                             variations.append({
                                'opt_id': opt_id, 
                                'channel_id': ch_id,
                                'suffix_id': f"_{ch_id}",
                                'suffix_name': f" {ch_display_name}",
                                'suffix_id': f"_{ch_id}",
                                'suffix_name': f" {ch_display_name}",
                                'extra_options': ch_info.get('options', {}),
                                'visible': custom_opts.get(f'channel_visible_{ch_id}', False)
                             })
                    break # Support only one channel selector per Input (primary)
                
                # Legacy Explosion Fallback (if kept for backward compat? No, removing)
                elif opt_def.get('multiple'):
                    # (Removed previous logic to enforce Channel architecture)
                    pass
        
        if not is_exploded:
            # Single Layer Case
            l_data = base_layer_data.copy()
            l_data['base_id'] = base_layer_data['id'] # [Fix] Propagate DB ID
            l_opts = custom_opts.copy() # Use a copy to avoid mutation issues
            
            # [Fix] Recalculate Dynamic Options for Single Layer (e.g. dynamic date)
            if inst and hasattr(inst, 'get_leaflet_options'):
                try:
                    dyn_l_opts = inst.get_leaflet_options()
                    l_opts.update(dyn_l_opts)
                except Exception as e:
                    logger.error(f"Error resolving dynamic options for single layer {layer.name}: {e}")

            l_data['options'] = l_opts
            l_data['visible'] = custom_opts.get('layer_visible')
            l_data['channel_visible'] = custom_opts.get('layer_visible') # Single layer uses layer_visible
            layers_data.append(l_data)
        else:
            # Exploded Case
            for var in variations:
                l_data = base_layer_data.copy()
                l_opts = custom_opts.copy() # Shallow copy is fine for dict of strings
                
                # Merge Channel options (e.g. style='light_all')
                if 'extra_options' in var:
                    l_opts.update(var['extra_options'])
                    
                # Support Legacy Value Override if existing
                if 'value' in var:
                    l_opts[var['opt_id']] = var['value']
                    
                l_data['options'] = l_opts
                
                # [Fix] Recalculate Dynamic URL & Options for this specific Variation (Channel)
                # Re-instantiating with channel options is necessary if logic depends on channel
                # But we can still optimize load_module_from_file via a module level cache or by re-using mod.
                try:
                    # For channels, we need a fresh instance with the channel-specific options
                    inst_v = _get_input_instance(layer.type, layer, l_opts)
                    if inst_v:
                        # Ensure the channel selection is set in the instance
                        inst_v.custom_options[var['opt_id']] = [var['channel_id']]
                        
                        # 1. Dynamic URL
                        specific_url = inst_v.get_url()
                        if specific_url:
                            l_data['url'] = specific_url
                            
                        # 2. Dynamic Leaflet Options
                        if hasattr(inst_v, 'get_leaflet_options'):
                            dyn_l_opts = inst_v.get_leaflet_options()
                            l_opts.update(dyn_l_opts)
                except Exception as e:
                     logger.error(f"Error resolving exploded URL/Options for {layer.name} Ch {var['channel_id']}: {e}")

                # [Fix] Role Override from Channel Definition
                if 'extra_options' in var and 'role' in var['extra_options']:
                    l_data['role'] = var['extra_options']['role']

                # [Fix] Type/Protocol Override from Channel Definition (Critical for Unified Modules)
                if 'extra_options' in var and 'type' in var['extra_options']:
                    l_data['type'] = var['extra_options']['type']
                
                # [Fix] Reload Dynamic Legend for Specific Channel
                # OpenWeatherMap (and others) need 'active_channels' to contain only the specific channel ID
                # to return the correct legend for this exploded layer.
                try:
                    if 'file_path' in layer_def: # Always check for dynamic legend if module path exists
                        mod, status = load_module_from_file(layer_def['file_path'], 'inputs')
                        if mod and hasattr(mod, 'InputModule'):
                            mock_dev = MockInputDev(layer)
                            inst = mod.InputModule(mock_dev)
                            
                            # Inject specific channel config (Ensure API Key present)
                            l_var_leg_opts = l_opts.copy() # l_opts already includes channel-specific overrides
                            if 'key_field' in layer_def:
                                kf = layer_def['key_field']
                                gkf = layer_def.get('global_key_field', kf)
                                if kf not in l_var_leg_opts and api_keys.get(gkf):
                                    l_var_leg_opts[kf] = api_keys.get(gkf)

                            # Force the active channel to be the single one for this variation
                            # 'opt_id' is usually 'active_channels'
                            l_var_leg_opts[var['opt_id']] = [var['channel_id']]
                            
                            inst.custom_options = l_var_leg_opts
                            
                            # [Fix] Monkey-patch get_custom_option to read from injected dict instead of DB
                            # The default behavior queries the DB using unique_id, ignoring our per-channel overrides.
                            def mock_get_option(opt, default=None):
                                return inst.custom_options.get(opt, default)
                            inst.get_custom_option = mock_get_option

                            specific_legend = inst.get_legend()
                            logger.info(f"[LegendDebug] {l_data['name']} (Ch:{var['channel_id']}) Legend: {specific_legend}")

                            if specific_legend:
                                l_data['legend'] = specific_legend
                except Exception as e:
                    logger.error(f"Error loading exploded legend: {e}")
                    pass
                
                # Modify ID and Name
                l_data['id'] = f"{l_data['id']}{var['suffix_id']}"
                l_data['name'] = f"{l_data['name']}{var['suffix_name']}"
                # [Fix] Propagate DB ID and Channel ID
                l_data['base_id'] = base_layer_data['id']
                l_data['channel_id'] = var['channel_id']
                
                # Visibility (User Preference)
                # Default to False for Overlays as requested, True for Base?
                # Actually, pass the Raw value. If None, we handle default in Frontend.
                l_data['visible'] = var.get('visible') 
                l_data['channel_visible'] = var.get('visible') 
                
                layers_data.append(l_data)
        
    return layers_data
        
    # Also add "Default" OpenStreetMap if no layers?
    # Or if 'osm' is in providers?
    # For now, rely on GeoLayer.
    
    return config

# ------------------------------------------------------------------------------
# Geo Layer CRUD
# ------------------------------------------------------------------------------
def geo_layer_add(form):
    messages = { "success": [], "info": [], "warning": [], "error": [] }
    
    try:
        layer_type = form.input_type.data
        dict_inputs = parse_input_information()
        
        if layer_type not in dict_inputs:
             messages["error"].append(f"Geo Layer type not found: {layer_type}")
             return messages
             
        new_layer = GeoLayer()
        new_layer.type = layer_type
        new_layer.unique_id = set_uuid()
        
        # Name
        if 'input_name' in dict_inputs[layer_type]:
            new_layer.name = dict_inputs[layer_type]['input_name']
        else:
            new_layer.name = layer_type
            
        # Default to Deactivated (As per user request)
        new_layer.is_activated = False
            
        # Options
        messages["error"], options = custom_options_return_json(
            messages["error"], dict_inputs, device=layer_type, use_defaults=True)
            
        # [New] Auto-Calc Position Y (Append to Bottom)
        try:
            # 1. Get all existing layers to find max y
            existing_layers = GeoLayer.query.all()
            max_y = -1
            
            for l in existing_layers:
                try:
                    l_opts = json.loads(l.options) if l.options else {}
                    # GridStack y is int
                    y = int(l_opts.get('position_y', 0))
                    if y > max_y:
                        max_y = y
                except:
                    pass
            
            # 2. Update new options with max_y + 1
            # We need to load the just-generated options string back to dict
            opts_dict = json.loads(options) if options else {}
            opts_dict['position_y'] = max_y + 1
            options = json.dumps(opts_dict)
            
        except Exception as e:
            logger.error(f"Error calculating auto-position for new layer: {e}")
            # Fallback will rely on default (0 or undefined)
            pass

        new_layer.options = options
        
        if not messages["error"]:
            new_layer.save()
            invalidate_geo_config_cache()
            messages["success"].append(f"Added Map Layer: {new_layer.name}")
            
    except Exception as e:
        logger.exception("geo_layer_add")
        messages["error"].append(str(e))
        
    return messages

def geo_layer_mod(form, request_form):
    messages = { "success": [], "info": [], "warning": [], "error": [] }
    
    try:
        layer_id = form.input_id.data
        layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
        
        if not layer:
            messages["error"].append("Layer not found")
            return messages
            
        if form.name.data:
            layer.name = form.name.data
            
        # Options
        try:
            curr_opts = json.loads(layer.options)
        except:
            curr_opts = {}
            
        dict_inputs = parse_input_information()
        messages["error"], new_opts = custom_options_return_json(
            messages["error"], 
            dict_inputs, 
            request_form=request_form,
            mod_dev=None, # Not passing Input model
            device=layer.type,
            custom_options=curr_opts
        )

        
        # [Fix] Manually save channel names (dynamic fields not in INPUT_INFORMATION)
        # Parse return string to dict first
        try:
             new_opts_dict = json.loads(new_opts)
        except:
             new_opts_dict = {}

        for key in request_form:
            if key.startswith('channel_name_') or key.startswith('channel_visible_') or key == 'layer_visible':
                new_opts_dict[key] = request_form[key]
                
        layer.options = json.dumps(new_opts_dict)
        
        if not messages["error"]:
            layer.save()
            invalidate_geo_config_cache()
            messages["success"].append(f"Modified Map Layer: {layer.name}")
            messages["name"] = layer.name

    except Exception as e:
        logger.exception("geo_layer_mod")
        messages["error"].append(str(e))
        
    return messages

def geo_layer_del(layer_id):
    messages = { "success": [], "info": [], "warning": [], "error": [] }
    try:
        layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
        if layer:
            db.session.delete(layer)
            db.session.commit()
            invalidate_geo_config_cache()
            messages["success"].append("Deleted Map Layer")
    except Exception as e:
        logger.exception("geo_layer_del")
        messages["error"].append(str(e))
    return messages

def geo_layer_activate(layer_id, active=True):
    messages = { "success": [], "info": [], "warning": [], "error": [] }
    try:
        layer = GeoLayer.query.filter_by(unique_id=layer_id).first()
        if layer:
            layer.is_activated = active
            db.session.commit()
            invalidate_geo_config_cache()
            action = "Activated" if active else "Deactivated"
            messages["success"].append(f"{action} Map Layer: {layer.name}")
        else:
             messages["error"].append("Layer not found")
    except Exception as e:
        logger.exception("geo_layer_activate")
        messages["error"].append(str(e))
    return messages

# ------------------------------------------------------------------------------
# Device Collection & Helpers (Shared between Widget and API)
# ------------------------------------------------------------------------------
def collect_devices(device_ids, include_all, default_color='blue', map_uuid=None):
    """Return a list of device dicts with coordinates and status info."""
    devices = []
    
    # Handle possible "dev_id::meas_id" format from channel-level selection
    raw_ids = device_ids or []
    cleaned_ids = []
    selected_channels_map = {} # { unique_id: set(channels) }

    for rid in raw_ids:
        if isinstance(rid, str) and '::' in rid:
            parts = rid.split('::')
            d_id = parts[0]
            try:
                # Handle 'None' string or empty
                ch_p = parts[1]
                ch = int(ch_p) if (ch_p and ch_p != 'None') else 0
            except:
                ch = 0
            
            cleaned_ids.append(d_id)
            if d_id not in selected_channels_map:
                selected_channels_map[d_id] = set()
            selected_channels_map[d_id].add(ch)
        else:
            cleaned_ids.append(rid)
            if rid not in selected_channels_map:
                selected_channels_map[rid] = set()
            selected_channels_map[rid].add(0) # Default to 0
            
    target_ids = set(cleaned_ids) if cleaned_ids else set()

    # If no specific IDs and not include_all, return empty
    if not target_ids and not include_all:
        return []

    # [Moved Up] Fetch Map-Specific Device Locations (Overlays) BEFORE Querying
    # This ensures we know which devices are ON the map even if their config is set elsewhere.
    # [Fix] Support per-channel coordinates using 'device_id::channel_id' key
    device_loc_map = {}
    if map_uuid:
        device_shapes = db.session.query(
            GeoShape.device_id, 
            GeoShape.channel_id,
            GeoShape.feature
        ).filter(
            GeoShape.geo_id == map_uuid,
            GeoShape.device_id != None
        ).all()

        for d_id, ch_id, feat in device_shapes:
            if not feat or 'geometry' not in feat: continue
            geom = feat['geometry']
            if not geom or 'coordinates' not in geom: continue
            
            coords = geom['coordinates']
            if geom.get('type') == 'Point' and len(coords) >= 2:
                # Key formatted as 'uuid' (legacy) or 'uuid::ch'
                # [Fix] ID Unification: Channel 0 (Primary) uses base UUID, others use uuid::ch
                loc_key = f"{d_id}::{ch_id}" if ch_id and str(ch_id) != '0' else d_id
                device_loc_map[loc_key] = {
                    'lat': coords[1],
                    'lng': coords[0],
                    'is_overlay': True
                }

    # Helper to define columns to load (Common + Specific)
    def get_load_options(model_cls):
        # Common columns
        col_names = ['id', 'unique_id', 'name', 'latitude', 'longitude', 
                'marker_color', 'marker_size', 'marker_icon', 
                'map_overlay_id', 'map_config_id', 'custom_options']
        
        # Specific Status Columns
        if hasattr(model_cls, 'is_activated'): col_names.append('is_activated')
        if hasattr(model_cls, 'is_on'): col_names.append('is_on')
        if hasattr(model_cls, 'last_update'): col_names.append('last_update')
        
        # Model specific fields that might be used
        if model_cls.__name__ == 'Input':
             col_names.extend(['label_color', 'font_size', 'label_style'])

        # Resolve strings to attributes
        attrs = [getattr(model_cls, name) for name in col_names if hasattr(model_cls, name)]
        return load_only(*attrs)

    # 1. Fetch Records (Optimized)
    inputs = []
    outputs = []
    ctrls = []

    pids = []
    triggers = []
    conditionals = []

    if target_ids:
        inputs = Input.query.filter(Input.unique_id.in_(target_ids)).options(get_load_options(Input)).all()
        outputs = Output.query.filter(Output.unique_id.in_(target_ids)).options(get_load_options(Output)).all()
        ctrls = CustomController.query.filter(CustomController.unique_id.in_(target_ids)).options(get_load_options(CustomController)).all()
        pids = PID.query.filter(PID.unique_id.in_(target_ids)).options(get_load_options(PID)).all()
    
    # [Fix] Logic Refinement: Prioritize target_ids if present.
    # User Requirement: 
    #   - If Selection List has items -> Show ONLY those items.
    #   - If Selection List is empty -> Show ALL (if include_all is checked, which defaults to True).
    
    # Separate IDs into categories to prevent cross-fetching between Inputs and Outputs
    if include_all:
        if map_uuid: # [Restored] Filter by Map Scope (Current Map OR Unassigned OR Exists as Overlay on Map)
             # [Fix] Filter by Map Scope (Current Map OR Unassigned OR Exists as Overlay on Map)
             overlay_ids = list(device_loc_map.keys())
             
             inputs = Input.query.filter(or_(Input.map_config_id == map_uuid, Input.map_config_id == None, Input.unique_id.in_(overlay_ids))).options(get_load_options(Input)).all()
             outputs = Output.query.filter(or_(Output.map_config_id == map_uuid, Output.map_config_id == None, Output.unique_id.in_(overlay_ids))).options(get_load_options(Output)).all()
             
             # Fallback to ALL for items without map assignment yet
             ctrls = CustomController.query.options(get_load_options(CustomController)).all() 
             pids = PID.query.options(get_load_options(PID)).all() 
             triggers = Trigger.query.options(get_load_options(Trigger)).all()
             conditionals = Conditional.query.options(get_load_options(Conditional)).all()
        else:
             inputs = Input.query.options(get_load_options(Input)).all()
             outputs = Output.query.options(get_load_options(Output)).all()
             ctrls = CustomController.query.options(get_load_options(CustomController)).all()
             pids = PID.query.options(get_load_options(PID)).all()
             triggers = Trigger.query.options(get_load_options(Trigger)).all()
             conditionals = Conditional.query.options(get_load_options(Conditional)).all()
             
    elif target_ids:
        # [Fix] Single-Channel Visibility (Round 19)
        # Refactored: Query all relevant tables for all provided base IDs.
        # This fixes the bug where IDs without '::' were only checked against Input.
        base_query_ids = []
        for rid in raw_ids:
            if isinstance(rid, str) and '::' in rid:
                base_query_ids.append(rid.split('::')[0])
            else:
                base_query_ids.append(str(rid))
        
        base_query_ids = list(set(base_query_ids))

        if base_query_ids:
            inputs = Input.query.filter(Input.unique_id.in_(base_query_ids)).options(get_load_options(Input)).all()
            outputs = Output.query.filter(Output.unique_id.in_(base_query_ids)).options(get_load_options(Output)).all()
            ctrls = CustomController.query.filter(CustomController.unique_id.in_(base_query_ids)).options(get_load_options(CustomController)).all()
            pids = PID.query.filter(PID.unique_id.in_(base_query_ids)).options(get_load_options(PID)).all()
            triggers = Trigger.query.filter(Trigger.unique_id.in_(base_query_ids)).options(get_load_options(Trigger)).all()
            conditionals = Conditional.query.filter(Conditional.unique_id.in_(base_query_ids)).options(get_load_options(Conditional)).all()

    # 2. [Optimization] Batch Fetch Output Channels (Eliminate N+1)
    # [New] Fetch Channel Names for Map Labels
    output_channel_map = {} # { output_id: { channel_num: { 'uuid': ..., 'name': ... } } }
    if outputs:
        o_ids = [o.unique_id for o in outputs]
        all_channels = OutputChannel.query.filter(OutputChannel.output_id.in_(o_ids)).options(
            load_only(OutputChannel.unique_id, OutputChannel.output_id, OutputChannel.channel, OutputChannel.name)
        ).all()
        
        for ch in all_channels:
            if ch.output_id not in output_channel_map:
                output_channel_map[ch.output_id] = {}
            
            output_channel_map[ch.output_id][ch.channel or 0] = {
                'unique_id': ch.unique_id,
                'name': ch.name
            }

    # [New] Batch Fetch Measurement Names for Map Labels
    selected_measurement_names_map = {}
    if target_ids:
        meas_records = db.session.query(
            DeviceMeasurements.device_id, 
            DeviceMeasurements.channel, 
            DeviceMeasurements.name
        ).filter(
            DeviceMeasurements.device_id.in_(target_ids)
        ).all()
        
        for r in meas_records:
            k = (r.device_id, r.channel or 0)
            if r.name:
                selected_measurement_names_map[k] = r.name



    # 3. Processing Helper
    def process_records(records, dev_type, model_cls):
        for record in records:
            if not record: continue
            
            try:
                # [Fix] Prioitize Map-Specific Overlay Location
                lat = None
                lng = None
                
                if record.unique_id in device_loc_map:
                    lat = device_loc_map[record.unique_id]['lat']
                    lng = device_loc_map[record.unique_id]['lng']
                else:
                    # Fallback to Global Device Config
                    if record.latitude is not None and record.longitude is not None:
                         lat = float(record.latitude)
                         lng = float(record.longitude)

                # [Fix] Allow devices without location (Palette Mode)
                # Frontend will handle missing lat/lng (won't render marker, but will show in list)
                # if lat is None or lng is None:
                #    continue
            except (ValueError, TypeError):
                continue

            status_active = False
            if hasattr(record, 'is_activated'): status_active = bool(record.is_activated)
            elif hasattr(record, 'is_on'): status_active = bool(record.is_on)
            # [Fix] Outputs lack an explicit is_activated flag in DB. 
            # We treat them as active if they are OutputChannel records (meaning they are configured) 
            # or if they are the base Output record.
            elif dev_type == 'output': 
                 status_active = True
            
            status = 'active' if status_active else 'idle'
            glyph = 'I' if dev_type == 'input' else 'O'
            
            color = (getattr(record, 'marker_color', None) or '').strip() or default_color
            size = getattr(record, 'marker_size', 3) or 3
            try: size = int(size)
            except: size = 3
            size = max(1, min(size, 5))

            # [New] Explode Output Channels for include_all mode
            channels_to_emit = selected_channels_map.get(record.unique_id)
            if include_all and dev_type == 'output':
                # Emit all known channels for this output device
                dev_chans = output_channel_map.get(record.unique_id, {})
                channels_to_emit = set(dev_chans.keys())
            
            if not channels_to_emit:
                channels_to_emit = {0}
            
            for ch_num in sorted(list(channels_to_emit)):
                # [Fix] ID Unification: Channel 0 uses base UUID, others use uuid::ch
                entry_uuid = f"{record.unique_id}::{ch_num}" if ch_num != 0 else record.unique_id
                meas_name = selected_measurement_names_map.get((record.unique_id, ch_num))
                
                # Check for Output Channel Name override
                ch_info = output_channel_map.get(record.unique_id, {}).get(ch_num, {})
                output_ch_name = ch_info.get('name')

                # [Fix] Coordinate Resolution (Per-Channel Priority)
                ch_lat, ch_lng = lat, lng
                loc_key_ch = entry_uuid 
                if loc_key_ch in device_loc_map:
                    ch_lat = device_loc_map[loc_key_ch]['lat']
                    ch_lng = device_loc_map[loc_key_ch]['lng']

                # Naming Logic Priority (Round 19 Refined):
                # 1. Output Channel Name (Specified by user per channel)
                # 2. Device Name (Fallback if channel name is missing or generic)
                # 3. Measurement Name (Usually for inputs/functions)
                import re
                
                # [Fix] Naming Fallback (Round 19): 
                # If output_ch_name is missing or generic "CHx", use record.name (Device Name)
                is_ch_name_generic = output_ch_name and re.match(r'^CH\d+$', output_ch_name.strip())
                
                if output_ch_name and not is_ch_name_generic:
                    # Strip any (CHx) or [CHx] patterns as requested
                    entry_name = re.sub(r'\s*[\(\[]CH\d+[\)\]]\s*', '', output_ch_name).strip()
                    if not entry_name: entry_name = output_ch_name 
                elif record.name:
                    # Fallback to Device Name
                    entry_name = record.name
                elif meas_name:
                    entry_name = f"{record.name} {meas_name}"
                else:
                    entry_name = record.name

                dev_data = {
                  'id': entry_uuid,
                  'unique_id': entry_uuid, # [Fix] Required by frontend (aot-geo-devices-v3.js)
                  'int_id': record.id,
                  'device_unique_id': record.unique_id, # [New] Base UUID
                  'channel_id': ch_num,
                  'name': entry_name,
                  'device_name': entry_name, # [Fix] Use channel-aware name for marker labels
                  'type': dev_type,
                  'device_type': dev_type, # [Fix] Explicitly expose device_type for frontend Color Logic
                  'lat': ch_lat,
                  'lng': ch_lng,
                  'status': status,
                  'is_activated': status_active, # [New] Expose raw activation state
                  'opacity': 0.8 if status == 'active' else 0.2,
                  'color': color,
                  'glyph': glyph,
                  'marker_icon': getattr(record, 'marker_icon', None),
                  'marker_size': size,
                  'marker_color': color,
                  'group_id': getattr(record, 'map_overlay_id', None),
                  'map_config_id': getattr(record, 'map_config_id', None), # [Fix] Required for frontend filtering
                  'is_on_map': (entry_uuid in device_loc_map), # [Fix] Use Unified ID (loc_key_ch/entry_uuid)
                  # [Runtime Service] Use centralized backend logic for accurate started_at
                  # [Optimization] Disabled for performance (N+1 InfluxDB Queries causing 1.5s delay)
                  'last_status_change': None, # get_started_at(record.unique_id, ch_num) if status == 'active' else None,
                  'last_duration': None, # get_last_duration(record.unique_id, ch_num),
                }
                
                if dev_type == 'input':
                    dev_data['label_color'] = getattr(record, 'label_color', None)
                    dev_data['font_size'] = getattr(record, 'font_size', None)
                    dev_data['label_style'] = getattr(record, 'label_style', None)

                    if record.custom_options:
                        try:
                            import json
                            opts = json.loads(record.custom_options)
                            if not dev_data.get('label_color'): dev_data['label_color'] = opts.get('label_color')
                            if not dev_data.get('font_size'): dev_data['font_size'] = opts.get('font_size')
                            if not dev_data.get('label_style'): dev_data['label_style'] = opts.get('label_style')
                        except: pass
                
                devices.append(dev_data)

    process_records(inputs, 'input', Input)
    process_records(outputs, 'output', Output)
    process_records(ctrls, 'function', CustomController)
    process_records(pids, 'function', PID)
    process_records(triggers, 'function', Trigger)
    process_records(conditionals, 'function', Conditional)

    return devices

def get_available_config_options():
    """
    Deeply queries and returns all available devices and measurement channels.
    """
    available_inputs = []
    available_outputs = []
    available_functions = []
    device_info_map = {}

    # 1. Inputs
    results_input = db.session.query(
        DeviceMeasurements.unique_id.label('meas_uuid'),
        Input.unique_id.label('device_id'),
        DeviceMeasurements.channel,
        DeviceMeasurements.name.label('meas_name'),
        Input.name.label('dev_name'),
        Input.latitude,
        Input.longitude
    ).outerjoin(
        DeviceMeasurements,
        (DeviceMeasurements.device_id == Input.unique_id)
    ).order_by(
        Input.name, DeviceMeasurements.channel
    ).all()

    seen_input_ids = set()
    for row in results_input:
        d_id = row.device_id
        d_name = row.dev_name
        # [Refactor] Group by Device ID (User Request)
        # We only list the device once. Selecting it effectively selects the device (defaulting to CH0 in logic).
        
        if d_id not in seen_input_ids:
            # ID is just the UUID, not uuid::ch
            entry = {
                'id': d_id,
                'name': d_name, # Just Device Name
                'has_coords': row.latitude is not None and row.longitude is not None
            }
            available_inputs.append(entry)
            seen_input_ids.add(d_id)
            
        device_info_map[d_id] = {'name': d_name, 'type': 'input'}

    # 2. Outputs
    results_output = db.session.query(
        Output.unique_id,
        Output.name.label('dev_name'),
        Output.latitude,
        Output.longitude,
        OutputChannel.channel,
        OutputChannel.name.label('ch_name')
    ).join(
        OutputChannel,
        (OutputChannel.output_id == Output.unique_id)
    ).order_by(
        Output.name, OutputChannel.channel
    ).all()

    for row in results_output:
        d_id = row.unique_id
        d_name = row.dev_name
        ch = row.channel if row.channel is not None else 0
        ch_name = row.ch_name
        
        if ch_name:
            import re
            full_name = re.sub(r'\s*[\(\[]CH\d+[\)\]]\s*', '', ch_name).strip()
            if not full_name: full_name = ch_name
        else:
            full_name = d_name
            
        comp_id = f"{d_id}::{ch}"

        available_outputs.append({
            'id': comp_id,
            'name': full_name,
            'has_coords': row.latitude is not None and row.longitude is not None
        })
        device_info_map[d_id] = {'name': d_name, 'type': 'output'}

    # 3. Functions
    def process_func_channel_list(model_cls, device_type_str, target_list):
        from sqlalchemy import literal
        
        results = db.session.query(
            model_cls.unique_id,
            model_cls.name,
            model_cls.latitude,
            model_cls.longitude,
            DeviceMeasurements.channel,
            DeviceMeasurements.name.label('meas_name')
        ).outerjoin(
            DeviceMeasurements,
            (DeviceMeasurements.device_id == model_cls.unique_id) & 
            ((DeviceMeasurements.device_type == 'function') | 
             (DeviceMeasurements.device_type == 'pid') |
             (DeviceMeasurements.device_type == 'trigger') |
             (DeviceMeasurements.device_type == 'conditional') |
             (DeviceMeasurements.device_type == 'trigger_sequence')) 
        ).all()
        
        results.sort(key=lambda x: (x.name, x.channel or 0))

        for row in results:
            d_id = row.unique_id
            d_name = row.name
            ch = row.channel if row.channel is not None else 0
            m_name = row.meas_name
            
            type_prefix = f"[{device_type_str}]"
            
            if m_name:
                full_name = f"{type_prefix} {d_name} {m_name}"
            else:
                full_name = f"{type_prefix} {d_name} (CH{ch})"

            comp_id = f"{d_id}::{ch}"

            target_list.append({
                'id': comp_id,
                'name': full_name,
                'has_coords': row.latitude is not None and row.longitude is not None
            })
            device_info_map[d_id] = {'name': d_name, 'type': 'function'}

    process_func_channel_list(CustomController, 'Function', available_functions)
    process_func_channel_list(PID, 'PID', available_functions)
    process_func_channel_list(Conditional, 'Conditional', available_functions)
    process_func_channel_list(Trigger, 'Trigger', available_functions)
    
    available_functions.sort(key=lambda x: x['name'])

    # 4. Measurement Collection
    available_measurements_input = []
    available_measurements_output = []
    available_measurements_function = []
    
    meas_cols = [DeviceMeasurements.device_id, DeviceMeasurements.unique_id, DeviceMeasurements.name, DeviceMeasurements.measurement, DeviceMeasurements.channel, DeviceMeasurements.device_type]
    for m in DeviceMeasurements.query.with_entities(*meas_cols).all():
        dev_info = device_info_map.get(m.device_id)
        dev_name = dev_info['name'] if dev_info else m.device_id
        m_suffix = f" - {m.name or m.measurement}" if (m.name or m.measurement) else ""
        m_label = f"{dev_name} [CH{m.channel or 0}]{m_suffix}"
        m_val = f"{m.device_id}::{m.unique_id}"
        
        m_type_lower = (m.device_type or (dev_info['type'] if dev_info else '')).lower()
        
        target_list = None
        if m_type_lower == 'input': target_list = available_measurements_input
        elif m_type_lower == 'output': target_list = available_measurements_output
        elif m_type_lower in ['function', 'pid', 'trigger', 'conditional', 'trigger_sequence']: target_list = available_measurements_function
        
        if target_list is not None:
            target_list.append({
                'id': m_val, 
                'name': m_label,
                'dev_name': dev_name, 
                'channel': m.channel or 0
            })

    available_measurements_input.sort(key=lambda x: (x['dev_name'], x['channel']))
    available_measurements_output.sort(key=lambda x: (x['dev_name'], x['channel']))
    available_measurements_function.sort(key=lambda x: (x['dev_name'], x['channel']))

    # 5. Available Maps
    available_maps = []
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
        logger.error(f"Error fetching maps for config: {e}")
        available_maps = []

    return {
        'available_measurements_input': available_measurements_input,
        'available_measurements_output': available_measurements_output,
        'available_measurements_function': available_measurements_function,
        'available_inputs': available_inputs,
        'available_outputs': available_outputs,
        'available_functions': available_functions,
        'available_maps': available_maps
    }

def get_all_measurements_for_map(devices):
    """
    Fetch all measurements for the given list of device dicts.
    Returns a dict mapping device_unique_id to a list of measurement dicts.
    """
    all_measurements_map = {}
    if not devices:
        return all_measurements_map

    # Extract unique device IDs (base UUIDs)
    map_device_ids = set()
    device_name_lookup = {}
    
    for d in devices:
        d_uid = d.get('device_unique_id')
        if not d_uid and 'id' in d:
            d_uid = d['id'].split('::')[0]
            
        if d_uid:
            map_device_ids.add(d_uid)
            device_name_lookup[d_uid] = d.get('device_name', d.get('name'))

    if map_device_ids:
        all_meas_query = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id.in_(list(map_device_ids))
        ).options(load_only(
            DeviceMeasurements.unique_id, 
            DeviceMeasurements.name, 
            DeviceMeasurements.measurement, 
            DeviceMeasurements.channel,
            DeviceMeasurements.unit,
            DeviceMeasurements.rescaled_unit,
            DeviceMeasurements.device_id,
            DeviceMeasurements.device_type
        )).all()
        
        for m in all_meas_query:
            d_id = m.device_id
            if d_id not in all_measurements_map:
                all_measurements_map[d_id] = []
            
            chan = m.channel if m.channel is not None else 0
            all_measurements_map[d_id].append({
                'id': m.unique_id, 
                'device_unique_id': d_id, 
                'channel': chan,
                'name': f"[CH{chan}] {m.name or m.measurement or ''}".strip(),
                'meas_name': (m.name or m.measurement or ''),
                'device_type': m.device_type,
                'device_name': device_name_lookup.get(d_id),
                'unit': (m.rescaled_unit or m.unit or ''), 
            })
        
        # Sort by channel
        for k in all_measurements_map:
            all_measurements_map[k].sort(key=lambda x: x['channel'])

    return all_measurements_map
