# coding=utf-8
import importlib
import json
import logging
import os
import pkgutil
from datetime import datetime

from aot.inputs.base_input import AbstractInput
from aot.databases.utils import session_scope
from aot.config import AOT_DB_PATH
from aot.databases.models import InputChannel, DeviceMeasurements

logger = logging.getLogger("aot.inputs.satellite_analysis")

# ------------------------------------------------------------------------------
# GIS Module Discovery
# ------------------------------------------------------------------------------
# This list will be populated by discover_analysis_modules
# Reference is maintained in INPUT_INFORMATION['custom_options']
ANALYSIS_MODULES = []

def discover_analysis_modules():
    """
    Scans aot/inputs_gis for modules that can provide measurements.
    Uses logic similar to parse_input_information for consistency.
    """
    global ANALYSIS_MODULES
    
    from aot.utils.modules import load_module_from_file
    from aot.config import PATH_INPUTS_GIS
    
    if not os.path.exists(PATH_INPUTS_GIS):
        logger.error(f" [Satellite Discovery] GIS Path not found: {PATH_INPUTS_GIS}")
        return

    # Start with an empty list for real modules
    temp_modules = []

    try:
        # Get list of files in PATH_INPUTS_GIS
        if os.path.exists(PATH_INPUTS_GIS):
            for each_file in os.listdir(PATH_INPUTS_GIS):
                if each_file.endswith('.py') and each_file not in ['__init__.py', 'base_input_gis.py']:
                    full_path = os.path.join(PATH_INPUTS_GIS, each_file)
                    module_name = each_file.split('.')[0]
                    
                    try:
                        # module_type='inputs_gis' results in aot.inputs_gis.xxxx
                        mod, status = load_module_from_file(full_path, 'inputs_gis')
                        
                        if mod and hasattr(mod, 'InputModule'):
                            # Check if it provides measurements (must have get_available_channels)
                            if hasattr(mod.InputModule, 'get_available_channels'):
                                # Name: Try input_name from INFO or fallback to module name
                                info = getattr(mod, 'INPUT_INFORMATION', {})
                                name = info.get('input_name', module_name)
                                
                                temp_modules.append((module_name, name))
                                logger.debug(f" [Satellite Discovery] Found: {name} ({module_name})")
                    except Exception as e:
                        logger.error(f" [Satellite Discovery] Failed to load {module_name}: {e}")
        else:
             logger.error(f" [Satellite Discovery] GIS Path not found: {PATH_INPUTS_GIS}")

    except Exception as e:
        logger.error(f" [Satellite Discovery] Fatal Error during discovery: {e}")

    # Fallback option if no real GIS modules were found
    if not temp_modules:
        temp_modules.append(('gis_isric', 'SoilGrids (Global Soil Info)'))
        logger.warning(" [Satellite Discovery] Using fallback option (gis_isric).")
    
    # Update global list (Reference remains the same for INPUT_INFORMATION)
    ANALYSIS_MODULES.clear()
    ANALYSIS_MODULES.extend(temp_modules)
    logger.debug(f" [Satellite Discovery] Discovery complete. Found {len(ANALYSIS_MODULES)} modules.")

# Run discovery at module load time
discover_analysis_modules()


def discover_and_query_for_ai(active_layers, lat, lng):
    """
    Dynamic AI context enrichment for map widgets.
    Parallelized in Phase 17 to prevent 30s+ blocks.
    """
    import importlib
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from flask import current_app

    if not active_layers or lat is None or lng is None:
        return []

    # v14.1: Capture app object in main thread — current_app is not available in worker threads
    app = current_app._get_current_object()

    results = []

    def fetch_module_reading(module_name, display_name):
        # Filter layers that match this module
        matched_layer = None
        display_lower = display_name.lower()
        for layer_name in active_layers:
            if display_lower in str(layer_name).lower():
                matched_layer = layer_name
                break

        if not matched_layer:
            return None

        try:
            # v14.1: Use captured app object instead of current_app (thread-safe)
            with app.app_context():
                with app.test_request_context(): # For babel _()
                    mod = importlib.import_module(f"aot.inputs_gis.{module_name}")
                    if not hasattr(mod, 'InputModule'):
                        return None
                    
                    instance = mod.InputModule(None, testing=True)
                    # Inject keys
                    try:
                        from aot.databases.models import GeoSetting
                        settings = GeoSetting.query.first()
                        if settings and settings.keys:
                            instance.global_api_keys = json.loads(settings.keys) or {}
                    except: pass

                    readings = instance.get_ai_reading(lat, lng)
                    if not readings:
                        return None
                    
                    batch = []
                    for r in readings:
                        batch.append({
                            "layer": matched_layer,
                            "property_detail": r.get('label', ''),
                            "value": r.get('value'),
                            "unit": r.get('unit', '')
                        })
                    return batch
        except Exception as e:
            logger.warning(f"[AI Enrichment] Thread failed for module {module_name}: {e}")
            return None

    # Parallel Execution (Max 5 GIS sources, 10s timeout per module)
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_mod = {executor.submit(fetch_module_reading, m[0], m[1]): m[0] for m in ANALYSIS_MODULES}
        for future in as_completed(future_to_mod):
            try:
                data = future.result(timeout=10) # 10 second limit per module
                if data:
                    results.extend(data)
            except Exception as e:
                mod_name = future_to_mod[future]
                logger.error(f"[AI Enrichment] Module {mod_name} timed out or failed: {e}")
    
    return results

# ------------------------------------------------------------------------------
# Input Information
# ------------------------------------------------------------------------------
measurements_dict = {}
channels_dict = {}

INPUT_INFORMATION = {
    'input_name_unique': 'SATELLITE_ANALYSIS',
    'input_manufacturer': 'Remote Sensing',
    'input_name': 'Satellite Analysis',
    'input_name_short': 'Sat Analysis',
    'input_library': 'requests',
    'measurements_name': 'Analysis Channels',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'interfaces': ['AoT'],

    'measurements_variable_amount': False, # Channels are managed automatically by the GIS source
    'channel_quantity_same_as_measurements': True,
    'measurements_use_same_timestamp': True,

    'message': 'Collects environmental data from satellite analysis and GIS layers based on the device location. '
               'Supports auto-adjustment for data gaps (e.g. coastal areas).',

    'options_enabled': [
        'period',
        'measurements_delay',
        'measurements_select',
        'coordinates'
    ],
    'options_disabled': ['interface'],

    'interfaces': ['AoT'],

    'dependencies_module': [],

    'custom_options': [
        {
            'id': 'gis_module',
            'type': 'select',
            'default_value': '',
            'required': True,
            'name': 'Active GIS Source',
            'phrase': 'Select the satellite/GIS analysis source.',
            'options_select': ANALYSIS_MODULES
        },
        {
            'id': 'auto_adjust',
            'type': 'bool',
            'default_value': True,
            'name': 'Auto-adjust Location',
            'phrase': 'Automatically search nearby valid coordinates if data is missing at the exact location (Spiral Search).'
        }
    ],
    'custom_channel_options': [],
    'execute_at_modification': None # Will be set below
}

# ------------------------------------------------------------------------------
# Normalization Logic
# ------------------------------------------------------------------------------
NORMALIZATION_MAP = {
    # NASA GIBS / Open-Meteo
    # NASA GIBS / Open-Meteo
    'soil_moisture_0_to_10cm': {'meas': 'volumetric_water_content', 'unit': 'm3_m3', 'name': '0-10cm'},
    'soil_moisture_10_to_40cm': {'meas': 'volumetric_water_content', 'unit': 'm3_m3', 'name': '10-40cm'},
    'soil_moisture_40_to_100cm': {'meas': 'volumetric_water_content', 'unit': 'm3_m3', 'name': '40-100cm'},
    'soil_moisture_100_to_200cm': {'meas': 'volumetric_water_content', 'unit': 'm3_m3', 'name': '100-200cm'},
    'soil_temperature_0_to_10cm': {'meas': 'temperature', 'unit': 'C'},
    
    # OpenWeather
    'temp': {'meas': 'temperature', 'unit': 'C'},
    'humidity': {'meas': 'humidity', 'unit': 'percent'},
    'pressure': {'meas': 'pressure', 'unit': 'hPa'},
    'wind_speed': {'meas': 'speed', 'unit': 'm_s'},
    'clouds': {'meas': 'sky_condition', 'unit': 'percent'},
    'rain_1h': {'meas': 'precipitation', 'unit': 'mm'},
    
    # ISRIC SoilGrids
    'phh2o': {'meas': 'ion_concentration', 'unit': 'pH'},
    'clay': {'meas': 'clay', 'unit': 'percent'},
    'sand': {'meas': 'sand', 'unit': 'percent'},
    'silt': {'meas': 'silt', 'unit': 'percent'},
    'soc': {'meas': 'soc', 'unit': 'dg_kg'},
    'bdod': {'meas': 'bdod', 'unit': 'cg_cm3'}
}

def normalize_channel_info(ch_info):
    """
    Normalizes GIS channel info to system standards.
    """
    raw_id = ch_info.get('id', ch_info.get('measurement', 'unknown'))
    raw_unit = ch_info.get('unit', 'none')
    name = ch_info.get('name', 'Unknown')
    
    # 1. Check direct mapping
    if raw_id in NORMALIZATION_MAP:
        mapping = NORMALIZATION_MAP[raw_id]
        return {
            'meas': mapping['meas'],
            'unit': mapping['unit'],
            'name': mapping.get('name', name)
        }
        
    # 2. General unit normalization
    unit_map = {
        '°C': 'C',
        'C': 'C',
        '%': 'percent',
        'hPa': 'hPa',
        'm/s': 'm_s',
        'mm': 'mm',
        'm3/m3': 'm3_m3',
        'm³/m³': 'm3_m3',
        'dg/kg': 'dg_kg',
        'cg/cm3': 'cg_cm3',
        'cg/cm³': 'cg_cm3'
    }
    
    norm_unit = unit_map.get(raw_unit, raw_unit)
    
    return {
        'meas': raw_id,
        'unit': norm_unit,
        'name': name
    }

# ------------------------------------------------------------------------------
# Hooks
# ------------------------------------------------------------------------------
def execute_at_modification(
        messages,
        mod_input,
        request_form,
        custom_options_dict_presave,
        custom_options_channels_dict_presave,
        custom_options_dict_postsave,
        custom_options_channels_dict_postsave):
    """
    Called when the Satellite Analysis input is modified.
    Syncs channels if the GIS Source has changed.
    """
    logger.info(f" [Satellite Sync] Hook called for Input {mod_input.unique_id}")
    import os
    from aot.aot_flask.extensions import db
    from aot.utils.modules import load_module_from_file
    from aot.config import PATH_INPUTS_GIS
    from aot.config_devices_units import add_measurement_unit

    old_gis = custom_options_dict_presave.get('gis_module')
    new_gis = custom_options_dict_postsave.get('gis_module')

    if new_gis:
        logger.info(f" [Satellite Sync] Synchronizing channels for GIS Source: {new_gis}")
        full_path = os.path.join(PATH_INPUTS_GIS, f"{new_gis}.py")
        mod, status = load_module_from_file(full_path, 'inputs_gis')

        if mod and hasattr(mod, 'InputModule'):
            gis_temp = mod.InputModule(mod_input)
            if hasattr(gis_temp, 'get_available_channels'):
                gis_channels = gis_temp.get_available_channels()

                # 1. Map existing channels/measurements by index
                existing_meas = {m.channel: m for m in DeviceMeasurements.query.filter_by(device_id=mod_input.unique_id).all()}
                existing_chans = {c.channel: c for c in InputChannel.query.filter_by(input_id=mod_input.unique_id).all()}

                # 2. Add/Update channels
                for ch_idx, ch_info in enumerate(gis_channels):
                    norm = normalize_channel_info(ch_info)
                    m_key = norm['meas']
                    m_name = norm['name']
                    u_key = norm['unit']

                    add_measurement_unit(m_key, u_key, meas_name=m_name)

                    # Update or Create Measurement
                    if ch_idx in existing_meas:
                        m_obj = existing_meas[ch_idx]
                        m_obj.name = m_name
                        m_obj.measurement = m_key
                        m_obj.unit = u_key
                        m_obj.is_enabled = True
                    else:
                        m_obj = DeviceMeasurements(
                            device_id=mod_input.unique_id,
                            name=m_name,
                            measurement=m_key,
                            unit=u_key,
                            channel=ch_idx,
                            is_enabled=True
                        )
                    db.session.add(m_obj)

                    # Update or Create Channel
                    if ch_idx in existing_chans:
                        c_obj = existing_chans[ch_idx]
                        c_obj.name = m_name
                    else:
                        c_obj = InputChannel(
                            input_id=mod_input.unique_id,
                            channel=ch_idx,
                            name=m_name,
                            custom_options='{}'
                        )
                    db.session.add(c_obj)

                # 3. Remove excess channels
                for ch_idx in existing_meas:
                    if ch_idx >= len(gis_channels):
                        db.session.delete(existing_meas[ch_idx])
                for ch_idx in existing_chans:
                    if ch_idx >= len(gis_channels):
                        db.session.delete(existing_chans[ch_idx])

                mod_input.num_channels = len(gis_channels)
                messages["info"].append(f"Synchronized {len(gis_channels)} channels for GIS Source: {new_gis}")
            else:
                messages["error"].append(f"GIS Module {new_gis} does not support data channels.")
        else:
             messages["error"].append(f"Failed to load GIS Module: {new_gis}")
    else:
        # If no GIS source, reset channels
        for m in DeviceMeasurements.query.filter_by(device_id=mod_input.unique_id).all():
            db.session.delete(m)
        for c in InputChannel.query.filter_by(input_id=mod_input.unique_id).all():
            db.session.delete(c)
        mod_input.num_channels = 0
        messages["warning"].append("No GIS Source selected. All channels removed.")
        logger.warning(" [Satellite Sync] No GIS Source selected. Channels cleared.")

    return (messages,
            mod_input,
            custom_options_dict_postsave,
            custom_options_channels_dict_postsave)

INPUT_INFORMATION['execute_at_modification'] = execute_at_modification

# ------------------------------------------------------------------------------
# Input Module Class
# ------------------------------------------------------------------------------
class InputModule(AbstractInput):
    """Collects environmental data from satellite and GIS layers based on device location.

    @phase active
    @stability stable
    @dependency AbstractInput"""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing)
        self.logger = logger
        self.gis_instance = None
        self.auto_adjust = True
        
        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            try:
                self.initialize()
            except Exception as e:
                self.logger.error(f"Initialization Failed: {e}")

    def initialize(self):
        self.auto_adjust = self.get_custom_option('auto_adjust')
        gis_module_name = self.get_custom_option('gis_module')
        
        self.logger.info(f"Initializing Satellite Input {self.unique_id}. GIS Source: {gis_module_name}")
        
        # Load GIS module
        self._load_gis_module(gis_module_name)
        
        if self.gis_instance:
            self._sync_channels()

    def _load_gis_module(self, module_name):
        if not module_name:
            return
            
        try:
            full_module_name = f"aot.inputs_gis.{module_name}"
            mod = importlib.import_module(full_module_name)
            
            if hasattr(mod, 'InputModule'):
                self.gis_instance = mod.InputModule(self.input_dev)
                
                # Inject global API keys from GeoSetting if available
                try:
                    from aot.databases.models import GeoSetting, GeoLayer
                    from aot.databases.utils import session_scope
                    from aot.config import AOT_DB_PATH
                    import json
                    with session_scope(AOT_DB_PATH) as session:
                        # 1. Global Keys from GeoSetting
                        all_keys = {}
                        settings = session.query(GeoSetting).first()
                        if settings and settings.keys:
                            all_keys = json.loads(settings.keys) or {}
                        
                        # 2. Inherit from existing GIS Layers if not in Global
                        module_info = getattr(mod, 'INPUT_INFORMATION', {})
                        lib_name = module_info.get('input_library') or module_name
                        kf = module_info.get('key_field')
                        gkf = module_info.get('global_key_field', kf)
                        
                        if kf and gkf not in all_keys:
                            # Try to find a GeoLayer of this type that has a key
                            # We search for layers matching the library name or type
                            matching_layer = session.query(GeoLayer).filter(
                                (GeoLayer.type == lib_name) | (GeoLayer.type == module_name)
                            ).first()
                            
                            if matching_layer and matching_layer.options:
                                l_opts = json.loads(matching_layer.options)
                                if l_opts.get(kf):
                                    all_keys[gkf] = l_opts.get(kf)
                                    self.logger.info(f" [Satellite Sync] Inherited API key for {lib_name} from GeoLayer '{matching_layer.name}'")

                        self.gis_instance.global_api_keys = all_keys
                except Exception as e:
                    self.logger.warning(f"Failed to load hierarchical API keys for GIS: {e}")
                    self.gis_instance.global_api_keys = {}

                # Inject options if needed
                if hasattr(self.gis_instance, 'get_custom_option') and hasattr(self, 'custom_options'):
                    self.gis_instance.custom_options = self.custom_options
                self.logger.info(f"Loaded GIS Source: {module_name}")
        except Exception as e:
            self.logger.error(f"Failed to load GIS Module {module_name}: {e}")

    def _sync_channels(self):
        """Syncs DB InputChannels with the GIS module's available channels."""
        if not self.gis_instance or not hasattr(self.gis_instance, 'get_available_channels'):
            return

        gis_channels = self.gis_instance.get_available_channels()
        input_id = self.unique_id
        
        self.logger.info(f"Syncing {len(gis_channels)} channels for Input {input_id}")

        try:
            with session_scope(AOT_DB_PATH) as session:
                # Get existing channels
                existing_channels = session.query(InputChannel).filter_by(input_id=input_id).all()
                existing_map = {c.channel: c for c in existing_channels}
                
                for ch_idx, ch_info in enumerate(gis_channels):
                    # AoT channels usually start from 0...N
                    if ch_idx in existing_map:
                        # Update
                        channel = existing_map[ch_idx]
                        channel.name = ch_info.get('name', channel.name)
                    else:
                        # Create
                        new_ch = InputChannel(
                            input_id=input_id,
                            channel=ch_idx,
                            name=ch_info.get('name', 'Unknown')
                        )
                        session.add(new_ch)
                
                session.commit()
        except Exception as e:
            self.logger.error(f"Failed to sync channels in DB: {e}")

    def get_measurement(self):
        """
        Main measurement loop.
        Fetches data from the GIS instance and maps to channels.
        """
        if not self.gis_instance:
            self.logger.error("No GIS Source loaded. Cannot take measurement.")
            return None

        # Fetch with spiral search if auto_adjust is on
        data = self._fetch_with_adjust()
        
        if not data:
            self.logger.warning("No data returned from GIS Source.")
            return None

        # Map data to AoT format { channel_id: { 'measurement': ..., 'unit': ..., 'value': ... } }
        measurements = {}
        gis_channels = self.gis_instance.get_available_channels()
        
        for ch_idx, ch_info in enumerate(gis_channels):
            norm = normalize_channel_info(ch_info)
            meas_key_norm = norm['meas']
            
            # Use the original ID to fetch data, but store with normalized metadata
            raw_id = ch_info.get('id', ch_info.get('measurement'))
            
            if raw_id in data:
                measurements[ch_idx] = {
                    'measurement': meas_key_norm,
                    'unit': norm['unit'],
                    'value': data[raw_id],
                    'timestamp_utc': datetime.utcnow()
                }

        return measurements

    def _fetch_with_adjust(self):
        """Fetches data, optionally performing a spiral search for valid data."""
        lat = self.input_dev.latitude
        lng = self.input_dev.longitude
        
        if lat is None or lng is None:
            self.logger.warning(f" [Satellite Sync] Device location missing. Searching fallback for Input {self.input_dev.unique_id}")
            
            # Try Zone (GeoShape) - map_overlay_id
            if self.input_dev.map_overlay_id:
                try:
                    from aot.databases.models import GeoShape
                    zone = GeoShape.query.get(self.input_dev.map_overlay_id)
                    if zone and zone.feature:
                        feat = zone.feature
                        geom = feat.get('geometry', feat)
                        coords = geom.get('coordinates')
                        g_type = geom.get('type')
                        
                        if g_type == 'Point':
                            lat, lng = coords[1], coords[0]
                        elif g_type in ['Polygon', 'MultiPolygon']:
                            # Centroid of outer ring
                            ring = coords[0] if g_type == 'Polygon' else coords[0][0]
                            lats = [c[1] for c in ring if isinstance(c, list)]
                            lngs = [c[0] for c in ring if isinstance(c, list)]
                            if lats and lngs:
                                lat, lng = sum(lats)/len(lats), sum(lngs)/len(lngs)
                    
                    if lat is not None:
                        self.logger.warning(f" [Satellite Sync] Found Zone location: {lat}, {lng}")
                except Exception as e:
                    self.logger.error(f" [Satellite Sync] Failed to get Zone location: {e}")

            # Try Site (GeoMap) - map_config_id
            if (lat is None or lng is None) and self.input_dev.map_config_id:
                try:
                    from aot.databases.models import GeoMap
                    site = GeoMap.query.filter_by(unique_id=self.input_dev.map_config_id).first()
                    if site and site.latitude is not None:
                        lat = site.latitude
                        lng = site.longitude
                        self.logger.warning(f" [Satellite Sync] Found Site location: {lat}, {lng}")
                except Exception as e:
                    self.logger.error(f" [Satellite Sync] Failed to get Site location: {e}")

        if lat is None or lng is None:
            self.logger.error("Device, Zone, or Site has no location set. Cannot fetch satellite data.")
            return None

        result = self.gis_instance.get_data_at_location(lat, lng)

        # If no data and auto_adjust, try spiral search
        if not result and self.auto_adjust:
            # Simplified spiral search: try 8 directions at ~100m distance
            offsets = [
                (0.001, 0), (-0.001, 0), (0, 0.001), (0, -0.001),
                (0.001, 0.001), (0.001, -0.001), (-0.001, 0.001), (-0.001, -0.001)
            ]
            for d_lat, d_lng in offsets:
                result = self.gis_instance.get_data_at_location(lat+d_lat, lng+d_lng)
                if result:
                    break
        
        return result

    def pre_stop(self):
        pass

    def stop_input(self):
        pass
