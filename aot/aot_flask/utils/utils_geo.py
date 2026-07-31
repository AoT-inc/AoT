# -*- coding: utf-8 -*-
import json
import logging
from aot.aot_flask.extensions import db
from aot.databases.models import (
    GeoSetting, GeoLayer, GeoMap,
    Input, Output, Misc, DeviceMeasurements, CustomController, GeoShape,
    Measurement, Unit, OutputChannel, Trigger, Conditional, PID, Conversion
)
from aot.utils.inputs import parse_input_information
from aot.databases import set_uuid
from flask_babel import gettext, get_locale
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
import threading

# Locale-aware cache for Geo configuration
# Format: { locale_str: (timestamp, config_dict) }
#
# These caches are read-through under gthread (multiple worker threads share the
# module globals). A naive "read DB → store in cache" is racy: a reader that
# snapshots the OLD DB value can write it back into the cache *after* a concurrent
# save has committed the NEW value and cleared the cache — re-poisoning the cache
# with stale data for the full TTL. To defeat this, every invalidate bumps a
# generation counter; a reader captures the generation before reading the DB and
# only stores its result if the generation is unchanged at store time (i.e. no
# invalidation happened while it was reading). Access is guarded by a lock.
_GEO_CONFIG_CACHE_MAP = {}
_CACHE_TTL = 300
_GEO_CACHE_LOCK = threading.Lock()
_GEO_CACHE_GEN = 0

# Serializes the read-modify-write of GeoSetting.theme_config/providers (JSON
# blobs patched one key at a time in api_geo_settings). Without this, two
# saves arriving close together (e.g. dragging the site color then the zone
# color within the panel's 400ms debounce) each read the same pre-save
# snapshot, patch their own key, and write the whole blob back — the second
# commit silently clobbers the first save's key with its stale copy (lost
# update). Reproduced live: two concurrent POSTs both return ok:true but only
# the later commit's key persists. gthread workers share this process, so a
# plain lock around read+commit is sufficient (SQLite serializes writes
# anyway; the race is in the Python-level read-before-either-commits window).
GEO_SETTINGS_SAVE_LOCK = threading.Lock()

# Cache for get_available_config_options (device/measurement dropdown lists)
_CONFIG_OPTIONS_CACHE = None
_CONFIG_OPTIONS_CACHE_TS = 0.0
_CONFIG_OPTIONS_TTL = 60

# Cache for Misc global settings
_MISC_CACHE = None
_MISC_CACHE_TS = 0.0
_MISC_CACHE_TTL = 300
_MISC_CACHE_LOCK = threading.Lock()
_MISC_CACHE_GEN = 0

# [3-way Actuator] Output module types that expose Open/Stop/Close + position control.
# Frontend renders a 3-button + slider popup instead of an on/off toggle.
from aot.outputs.paired_actuator_common import PAIRED_ACTUATOR_OUTPUT_TYPES

THREE_WAY_OUTPUT_TYPES = set(PAIRED_ACTUATOR_OUTPUT_TYPES)


def invalidate_geo_config_cache():
    global _GEO_CONFIG_CACHE_MAP, _GEO_CACHE_GEN
    with _GEO_CACHE_LOCK:
        _GEO_CONFIG_CACHE_MAP = {}
        _GEO_CACHE_GEN += 1


def invalidate_config_options_cache():
    global _CONFIG_OPTIONS_CACHE, _CONFIG_OPTIONS_CACHE_TS
    _CONFIG_OPTIONS_CACHE = None
    _CONFIG_OPTIONS_CACHE_TS = 0.0


def invalidate_misc_cache():
    global _MISC_CACHE, _MISC_CACHE_TS, _MISC_CACHE_GEN
    with _MISC_CACHE_LOCK:
        _MISC_CACHE = None
        _MISC_CACHE_TS = 0.0
        _MISC_CACHE_GEN += 1


def get_misc_cached():
    global _MISC_CACHE, _MISC_CACHE_TS
    now = time.time()
    with _MISC_CACHE_LOCK:
        if _MISC_CACHE is not None and (now - _MISC_CACHE_TS) < _MISC_CACHE_TTL:
            return _MISC_CACHE
        gen_at_read = _MISC_CACHE_GEN
    from aot.databases.models import Misc
    # populate_existing(): force a fresh DB read, bypassing a possibly-stale
    # identity-map object (same session-staleness class as get_geo_config — this
    # feeds custom_theme_json/custom UI colors, which otherwise revert intermittently).
    result = Misc.query.populate_existing().first()
    # Only cache if no invalidation happened during the DB read (see note above).
    with _MISC_CACHE_LOCK:
        if _MISC_CACHE_GEN == gen_at_read:
            _MISC_CACHE = result
            _MISC_CACHE_TS = now
    return result

def get_geo_config():
    """
    Returns the consolidated Geo configuration for the frontend.
    Includes:
    1. Global Settings (GeoSetting)
    2. Active Layers (GeoLayer)
    """
    global _GEO_CONFIG_CACHE_MAP

    # [Fix] Locale-aware caching to support dynamic legends in different languages
    try:
        current_locale = str(get_locale())
    except:
        current_locale = 'en'

    now = time.time()

    # Return cached if valid for current locale. Capture the generation while
    # holding the lock so we can detect a concurrent invalidation during the DB
    # read below (prevents re-poisoning the cache with a stale snapshot).
    with _GEO_CACHE_LOCK:
        if current_locale in _GEO_CONFIG_CACHE_MAP:
            ts, cached_config = _GEO_CONFIG_CACHE_MAP[current_locale]
            if (now - ts) < _CACHE_TTL:
                return cached_config
        gen_at_read = _GEO_CACHE_GEN

    # populate_existing(): bypass the SQLAlchemy identity-map cache and re-read
    # the row from the DB. A worker thread's scoped session can hold a STALE
    # GeoSetting object (theme_config from before another session committed a
    # change); returning that stale object here would cache it (TTL) and serve
    # old device/theme colors intermittently for a long time. Forcing a fresh
    # read is the fix (verified: without it, an external UPDATE is not seen).
    settings = GeoSetting.query.populate_existing().first()
    if settings:
        logger.debug(f"[Geo Config Debug] Loaded Theme Config from DB (Locale: {current_locale}): {settings.theme_config}")

    if not settings:
        settings = GeoSetting()
        settings.save()

    config = settings.state_dict()

    # [New] Expose Search Provider
    config['search_provider'] = config.get('providers', {}).get('search_provider')

    # Add Active Layers
    config['layers'] = get_active_geo_layers(config.get('keys', {}))

    # Update cache for current locale — but only if no invalidation happened
    # while we were reading the DB. Otherwise this snapshot may be stale (a save
    # committed + cleared the cache mid-read) and must not be written back.
    with _GEO_CACHE_LOCK:
        if _GEO_CACHE_GEN == gen_at_read:
            _GEO_CONFIG_CACHE_MAP[current_locale] = (now, config)
    
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
            'type': protocol_type, # 'xyz', 'wms', 'geojson', 'vector', or 'none' (data-only)
            'z_index': 0,
            # [Fix] Overlays OFF by default, Base OFF by default (prevent auto-loading multiple).
            # Frontend Logic (AoTMapLoader) will fallback to first available or use 'visible' option.
            'is_active': False,
            'role': layer_role,
            'refresh_interval': 0,
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

        # refresh_interval from InputModule instance (e.g. gis_openweather sets 600s)
        if inst and hasattr(inst, 'refresh_interval') and inst.refresh_interval:
            base_layer_data['refresh_interval'] = int(inst.refresh_interval)

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
            # Replace {time} placeholder in URL with the backend-computed date value
            # so MapLibre receives a fully-resolved URL (it does not understand {time}).
            if '{time}' in l_data.get('url', ''):
                time_val = l_opts.get('time', 'default')
                if time_val and time_val != 'default':
                    l_data['url'] = l_data['url'].replace('{time}', str(time_val))
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
                            logger.debug(f"[LegendDebug] {l_data['name']} (Ch:{var['channel_id']}) Legend: {specific_legend}")

                            if specific_legend:
                                l_data['legend'] = specific_legend
                except Exception as e:
                    logger.error(f"Error loading exploded legend: {e}")
                    pass
                
                # Replace {time} placeholder with backend-computed date (MapLibre can't substitute it)
                if '{time}' in l_data.get('url', ''):
                    time_val = l_opts.get('time', 'default')
                    if time_val and time_val != 'default':
                        l_data['url'] = l_data['url'].replace('{time}', str(time_val))

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
            new_layer.name = str(dict_inputs[layer_type]['input_name'])
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
            # [Image overlay] These are 'hidden' custom_options that
            # custom_options_return_json does not parse, so the generic Save
            # would otherwise drop a freshly-dragged placement. Carry them over
            # from the form's hidden inputs (only when present/non-empty).
            elif key in ('image_url', 'coordinates', 'opacity', 'meta', 'lock_aspect'):
                val = request_form.get(key)
                if val not in (None, ''):
                    new_opts_dict[key] = val

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
    """Return a list of device dicts with coordinates and status info.

    [Behavior] `device_ids`, when non-empty, is an EXCLUDE list, not an include
    list: every device placed on the map is always fetched, and entries whose
    entry-level id (base unique_id, or 'unique_id::channel' for non-zero output
    channels) appears in `device_ids` are dropped from the result afterward.
    This matches the AoT_map widget's "Device Filter" — placing a device on the
    map IS showing it; the filter exists only to hide the rare few, so with 50
    devices placed you pick the 2 to hide instead of the other 48 to keep.
    `include_all` is accepted for call-site compatibility but no longer gates
    the fetch (every caller now always wants the full map-scoped set); it is
    effectively "no exclusions" when there is no `device_ids` list.
    """
    devices = []

    # Handle possible "dev_id::channel" format from per-channel exclusion.
    # exclude_entry_ids mirrors the 'unique_id'/'entry_uuid' each device dict
    # is keyed by below (base id for channel 0, 'base_id::N' otherwise) so
    # exclusion is channel-precise — excluding one Output channel must not
    # also hide that Output's other channels.
    raw_ids = device_ids or []
    exclude_entry_ids = set()
    for rid in raw_ids:
        if not rid:
            continue
        if isinstance(rid, str) and '::' in rid:
            d_id, _, ch_p = rid.partition('::')
            try:
                ch = int(ch_p) if (ch_p and ch_p != 'None') else 0
            except (TypeError, ValueError):
                ch = 0
        else:
            d_id, ch = rid, 0
        exclude_entry_ids.add(d_id if ch == 0 else f"{d_id}::{ch}")

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
            if not feat: continue
            # [Fix] Column-level JSON queries on SQLite may return raw JSON strings
            # instead of deserialized dicts. Normalize here before key access.
            if isinstance(feat, str):
                try:
                    feat = json.loads(feat)
                except Exception:
                    continue
            if not isinstance(feat, dict) or 'geometry' not in feat: continue
            geom = feat['geometry']
            if not isinstance(geom, dict) or 'coordinates' not in geom: continue

            coords = geom['coordinates']
            if geom.get('type') == 'Point' and isinstance(coords, list) and len(coords) >= 2:
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
        if model_cls.__name__ == 'Output':
             col_names.append('output_type')

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

    # Always fetch the full map-scoped set — device_ids is an exclude filter
    # applied after process_records() builds the per-channel entries below, not
    # a query-level include filter (see docstring). `include_all`/target_ids
    # branching used to choose between "everything" vs "only the selected
    # ids" here; now there is only "everything", scoped to this map when one
    # is given.
    if map_uuid: # Filter by Map Scope (Current Map OR Unassigned OR Exists as Overlay on Map)
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
    # Covers every device actually fetched above (always the full map-scoped
    # set now — see collect_devices docstring), not just an exclude list.
    selected_measurement_names_map = {}
    all_fetched_ids = [r.unique_id for r in inputs] + [r.unique_id for r in outputs] \
        + [r.unique_id for r in ctrls] + [r.unique_id for r in pids]
    if all_fetched_ids:
        meas_records = db.session.query(
            DeviceMeasurements.device_id,
            DeviceMeasurements.channel,
            DeviceMeasurements.name
        ).filter(
            DeviceMeasurements.device_id.in_(all_fetched_ids)
        ).all()
        
        for r in meas_records:
            k = (r.device_id, r.channel or 0)
            if r.name:
                selected_measurement_names_map[k] = r.name



    # 3a. Fetch runtime output states once (daemon controller, not DB)
    output_runtime_states = {}
    try:
        output_runtime_states = DaemonControl().output_states_all()
    except Exception:
        pass

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
            if dev_type != 'output':
                if hasattr(record, 'is_activated'): status_active = bool(record.is_activated)
                elif hasattr(record, 'is_on'): status_active = bool(record.is_on)
            # output status_active is computed per-channel inside the loop below

            status = 'active' if status_active else 'idle'
            glyph = 'I' if dev_type == 'input' else 'O'
            
            color = (getattr(record, 'marker_color', None) or '').strip() or default_color
            size = getattr(record, 'marker_size', 3) or 3
            try: size = int(size)
            except: size = 3
            size = max(1, min(size, 5))

            # Always emit every known channel for an output device — the full
            # map-scoped set is always fetched now (see collect_devices
            # docstring), so there is no "only the selected channels" case
            # left to special-case.
            channels_to_emit = {0}
            if dev_type == 'output':
                dev_chans = output_channel_map.get(record.unique_id, {})
                channels_to_emit = set(dev_chans.keys()) or {0}
            
            # [3-way Actuator] Detect output_type-based control kind once per device
            control_kind = 'on_off'
            if dev_type == 'output':
                ot = getattr(record, 'output_type', None)
                if ot in THREE_WAY_OUTPUT_TYPES:
                    control_kind = 'value_3way'

            for ch_num in sorted(list(channels_to_emit)):
                # [Fix] ID Unification: Channel 0 uses base UUID, others use uuid::ch
                entry_uuid = f"{record.unique_id}::{ch_num}" if ch_num != 0 else record.unique_id

                # Per-channel runtime state for output devices
                position_pct = None
                if dev_type == 'output':
                    ch_runtime = output_runtime_states.get(record.unique_id, {}).get(ch_num)
                    if ch_runtime is not None:
                        status_active = ch_runtime == 'on' or (isinstance(ch_runtime, (int, float)) and ch_runtime > 0)
                        if isinstance(ch_runtime, (int, float)) and not isinstance(ch_runtime, bool):
                            position_pct = float(ch_runtime)
                    else:
                        status_active = False
                    if control_kind == 'value_3way' and position_pct is None:
                        position_pct = 0.0
                    status = 'active' if status_active else 'idle'
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

                import re
                is_ch_name_generic = output_ch_name and re.match(r'^CH\d+$', output_ch_name.strip())
                ch_total_count = len(output_channel_map.get(record.unique_id, {}))

                # Single-channel output: Output.name is the device label.
                # Multi-channel output: OutputChannel.name distinguishes channels.
                if ch_total_count > 1 and output_ch_name and not is_ch_name_generic:
                    entry_name = re.sub(r'\s*[\(\[]CH\d+[\)\]]\s*', '', output_ch_name).strip()
                    if not entry_name: entry_name = output_ch_name
                elif record.name:
                    entry_name = record.name
                elif meas_name:
                    entry_name = f"{record.name} {meas_name}"
                else:
                    entry_name = record.name

                if dev_type == 'output':
                    output_type_str = getattr(record, 'output_type', None)
                else:
                    output_type_str = None

                dev_data = {
                  'id': entry_uuid,
                  'unique_id': entry_uuid, # [Fix] Required by frontend (aot-geo-devices-v3.js)
                  'output_type': output_type_str, # [3-way] raw output module identifier
                  'control_kind': control_kind if dev_type == 'output' else None,
                  'position_pct': position_pct,
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

    if exclude_entry_ids:
        devices = [d for d in devices if d.get('unique_id') not in exclude_entry_ids]

    return devices

def get_available_config_options():
    """
    Deeply queries and returns all available devices and measurement channels.
    """
    global _CONFIG_OPTIONS_CACHE, _CONFIG_OPTIONS_CACHE_TS
    now = time.time()
    if _CONFIG_OPTIONS_CACHE is not None and (now - _CONFIG_OPTIONS_CACHE_TS) < _CONFIG_OPTIONS_TTL:
        return _CONFIG_OPTIONS_CACHE

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

    result = {
        'available_measurements_input': available_measurements_input,
        'available_measurements_output': available_measurements_output,
        'available_measurements_function': available_measurements_function,
        'available_inputs': available_inputs,
        'available_outputs': available_outputs,
        'available_functions': available_functions,
        'available_maps': available_maps
    }
    _CONFIG_OPTIONS_CACHE = result
    _CONFIG_OPTIONS_CACHE_TS = now
    return result

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
            DeviceMeasurements.conversion_id,
            DeviceMeasurements.device_id,
            DeviceMeasurements.device_type
        )).all()

        # conversion_id → convert_unit_to 일괄 조회 (변환 단위 우선)
        conv_ids = {m.conversion_id for m in all_meas_query if m.conversion_id}
        conv_unit_lookup = {}
        if conv_ids:
            convs = Conversion.query.filter(Conversion.unique_id.in_(conv_ids)).all()
            conv_unit_lookup = {c.unique_id: (c.convert_unit_to or '') for c in convs}

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
                'unit': (conv_unit_lookup.get(m.conversion_id) if m.conversion_id else None) or m.rescaled_unit or m.unit or '',
            })
        
        # Sort by channel
        for k in all_measurements_map:
            all_measurements_map[k].sort(key=lambda x: x['channel'])

    return all_measurements_map
