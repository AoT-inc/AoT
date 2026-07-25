# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg, gettext as _

# Define Channels for Properties (maps to WMS 'map' param)
# Option 'map' will be passed as query param: &map=/map/phh2o.map
CHANNELS = {
    0: {'name': lg('pH (Water)'), 'options': {'map': '/map/phh2o.map', 'layers': 'phh2o_0-5cm_mean'}},
    1: {'name': lg('Clay Content'), 'options': {'map': '/map/clay.map', 'layers': 'clay_0-5cm_mean'}},
    2: {'name': lg('Sand Content'), 'options': {'map': '/map/sand.map', 'layers': 'sand_0-5cm_mean'}},
    3: {'name': lg('Silt Content'), 'options': {'map': '/map/silt.map', 'layers': 'silt_0-5cm_mean'}},
    4: {'name': lg('Soil Organic Carbon'), 'options': {'map': '/map/soc.map', 'layers': 'soc_0-5cm_mean'}},
    5: {'name': lg('Bulk Density'), 'options': {'map': '/map/bdod.map', 'layers': 'bdod_0-5cm_mean'}}
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_isric',
    'input_manufacturer': 'ISRIC',
    'message': lg('Global soil characteristic map from World Soil Information Service (ISRIC). Visualizes soil composition (clay, sand, etc.), pH levels, and carbon content for geological analysis as overlayer data.'),
    'country': ['GL'],
    'input_name': 'SoilGrids (Global Soil Info)',
    'input_library': 'gis_isric',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://soilgrids.org/',
    'attribution': 'ISRIC - World Soil Information',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'overlay',
    'custom_options': [
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': lg('Soil Property'),
            'channel_def': CHANNELS,
            'default': [0],
            'multiple': False
        },
        # Depth selector could be added if we explose all channel combos, but for now fixed to 0-5cm for simplicity
        # or we dynamically handle 'layers' param if we use the class. But since we use static dict,
        # we stick to the channel options.
    ],
    'dependencies_module': [],
    # Base URL for WMS (Leaflet appends ?service=WMS&request=GetMap&map=...&layers=...)
    'default_url': 'https://maps.isric.org/mapserv',
    'layer_type': 'wms',
    'leaflet_options': {
        'format': 'image/png',
        'transparent': True,
        'version': '1.3.0'
    },
    'time_enabled': False
}

class InputModule(AbstractGisInput):
    """
    GIS overlay provider for ISRIC SoilGrids global soil data.
    Provides WMS-based soil property overlays including pH, clay, sand, silt, organic carbon, and bulk density.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'wms'
        self.layer_category = 'overlay'
        self.default_url = 'https://maps.isric.org/mapserv'
        self.attribution = INPUT_INFORMATION['attribution']

    def get_url(self):
        # Channel logic
        active_channels = self.get_custom_option('active_channels')
        
        if not active_channels: active_channels = [0]
        elif not isinstance(active_channels, list): active_channels = [active_channels]
        
        first_ch_id = active_channels[0]
        try: first_ch_id = int(first_ch_id)
        except: pass
        
        # CHANNELS info
        layer_def = CHANNELS.get(first_ch_id, CHANNELS[0])
        map_path = layer_def['options'].get('map', '/map/phh2o.map')
        layers = layer_def['options'].get('layers', 'phh2o_0-5cm_mean')
        
        # [Fix] Return Base URL only. 
        # Leaflet WMS will append 'map' and 'layers' from options.
        # This prevents duplicate parameters (e.g. ?map=...&map=...) which break MapServer.
        return self.default_url

    def get_leaflet_options(self):
        options = super().get_leaflet_options()
        active_channels = self.get_custom_option('active_channels')
        if not active_channels: active_channels = [0]
        elif not isinstance(active_channels, list): active_channels = [active_channels]
        
        first_ch_id = active_channels[0]
        try: first_ch_id = int(first_ch_id)
        except: pass
        
        layer_def = CHANNELS.get(first_ch_id, CHANNELS[0])
        # WMS options (layers, map, etc.)
        options.update(layer_def['options'])
        # Add version and format if missing
        options.setdefault('version', '1.3.0')
        options.setdefault('format', 'image/png')
        options.setdefault('transparent', True)
        # Cap the WMS bridge's raster source at SoilGrids' native 250m grid
        # (docs.isric.org/globaldata/soilgrids/SoilGrids_faqs.html: "250m
        # resolution"). Web Mercator 256px tiles cross ~250m/pixel between
        # z9 (~306m) and z10 (~153m) at the equator, so z10 is the last level
        # where a tile can show something beyond an upscaled blur — without a
        # cap this had no ceiling at all and would repeat the OpenWeatherMap
        # tile-storm bug at any zoom the user reaches.
        options.setdefault('maxNativeZoom', 10)

        return options

    def get_legend(self):
        """
        Return legend configuration for the active channel.
        Implemented in OpenWeather style with Gradient Bar and Value Box.
        """
        active_channels = self.get_custom_option('active_channels')
        if not active_channels: active_channels = [0]
        elif not isinstance(active_channels, list): active_channels = [active_channels]
        
        first_ch_id = active_channels[0]
        try: first_ch_id = int(first_ch_id)
        except: pass
        
        legend_data = None
        layer_key = CHANNELS.get(first_ch_id, CHANNELS[0])['options'].get('layers', '')
        
        if 'phh2o' in layer_key:
            # pH (Water) - Rainbow scale for Acidic to Alkaline
            title = _("Soil pH (0-5cm)")
            legend_data = {
                'type': 'html',
                'content': '<div class="aot-legend-wrapper">' +
                           '  <div class="aot-legend-content">' +
                           f'    <div class="aot-legend-title">{title}</div>' +
                           '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #ff0000, #ff7f00, #ffff00, #00ff00, #00ffff, #0000ff, #8b00ff);"></div>' +
                           '    <div class="aot-legend-labels"><span>3.0</span><span>6.5</span><span>10.0</span></div>' +
                           '  </div>' +
                           '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/isric?lon={lon}&lat={lat}&property=phh2o&depth=0-5cm&value=mean" data-api-param="properties.layers.0.depths.0.values.mean" data-d-factor="10" data-unit="pH">' +
                           '    <div class="aot-legend-value-text">--</div>' +
                           '    <div class="aot-legend-value-unit">pH</div>' +
                           '  </div>' +
                           '</div>'
            }
        elif 'clay' in layer_key:
            # Clay Content (%) - Green Sequential
            title = _("Clay Content (%)")
            legend_data = {
                'type': 'html',
                'content': '<div class="aot-legend-wrapper">' +
                           '  <div class="aot-legend-content">' +
                           f'    <div class="aot-legend-title">{title}</div>' +
                           '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #f7fcf5, #e5f5e0, #c7e9c0, #a1d99b, #74c476, #41ab5d, #238b45, #006d2c, #00441b);"></div>' +
                           '    <div class="aot-legend-labels"><span>0</span><span>50</span><span>100</span></div>' +
                           '  </div>' +
                           '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/isric?lon={lon}&lat={lat}&property=clay&depth=0-5cm&value=mean" data-api-param="properties.layers.0.depths.0.values.mean" data-d-factor="10" data-unit="%">' +
                           '    <div class="aot-legend-value-text">--</div>' +
                           '    <div class="aot-legend-value-unit">%</div>' +
                           '  </div>' +
                           '</div>'
            }
        elif 'sand' in layer_key:
            # Sand Content (%) - Brown/Orange Sequential
            title = _("Sand Content (%)")
            legend_data = {
                'type': 'html',
                'content': '<div class="aot-legend-wrapper">' +
                           '  <div class="aot-legend-content">' +
                           f'    <div class="aot-legend-title">{title}</div>' +
                           '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #fff7bc, #fee391, #fec44f, #fe9929, #ec7014, #cc4c02, #8c2d04);"></div>' +
                           '    <div class="aot-legend-labels"><span>0</span><span>50</span><span>100</span></div>' +
                           '  </div>' +
                           '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/isric?lon={lon}&lat={lat}&property=sand&depth=0-5cm&value=mean" data-api-param="properties.layers.0.depths.0.values.mean" data-d-factor="10" data-unit="%">' +
                           '    <div class="aot-legend-value-text">--</div>' +
                           '    <div class="aot-legend-value-unit">%</div>' +
                           '  </div>' +
                           '</div>'
            }
        elif 'silt' in layer_key:
            # Silt Content (%) - Blue Sequential
            title = _("Silt Content (%)")
            legend_data = {
                'type': 'html',
                'content': '<div class="aot-legend-wrapper">' +
                           '  <div class="aot-legend-content">' +
                           f'    <div class="aot-legend-title">{title}</div>' +
                           '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #f7fbff, #deebf7, #c6dbef, #9ecae1, #6baed6, #4292c6, #2171b5, #084594);"></div>' +
                           '    <div class="aot-legend-labels"><span>0</span><span>50</span><span>100</span></div>' +
                           '  </div>' +
                           '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/isric?lon={lon}&lat={lat}&property=silt&depth=0-5cm&value=mean" data-api-param="properties.layers.0.depths.0.values.mean" data-d-factor="10" data-unit="%">' +
                           '    <div class="aot-legend-value-text">--</div>' +
                           '    <div class="aot-legend-value-unit">%</div>' +
                           '  </div>' +
                           '</div>'
            }
        elif 'soc' in layer_key:
            # Soil Organic Carbon - Brown/Red Sequential
            title = _("Organic Carbon (dg/kg)")
            legend_data = {
                'type': 'html',
                'content': '<div class="aot-legend-wrapper">' +
                           '  <div class="aot-legend-content">' +
                           f'    <div class="aot-legend-title">{title}</div>' +
                           '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #fff5eb, #fee6ce, #fdd0a2, #fdae6b, #fd8d3c, #f16913, #d94801, #a63603, #7f2704);"></div>' +
                           '    <div class="aot-legend-labels"><span>0</span><span>500</span><span>1000+</span></div>' +
                           '  </div>' +
                           '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/isric?lon={lon}&lat={lat}&property=soc&depth=0-5cm&value=mean" data-api-param="properties.layers.0.depths.0.values.mean" data-d-factor="10" data-unit="dg/kg">' +
                           '    <div class="aot-legend-value-text">--</div>' +
                           '    <div class="aot-legend-value-unit">dg/kg</div>' +
                           '  </div>' +
                           '</div>'
            }
        elif 'bdod' in layer_key:
            # Bulk Density - Purple Sequential
            title = _("Bulk Density (cg/cm³)")
            legend_data = {
                'type': 'html',
                'content': '<div class="aot-legend-wrapper">' +
                           '  <div class="aot-legend-content">' +
                           f'    <div class="aot-legend-title">{title}</div>' +
                           '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #fcfbfd, #efedf5, #dadaeb, #bcbddc, #9e9ac8, #807dba, #6a51a3, #54278f, #3f007d);"></div>' +
                           '    <div class="aot-legend-labels"><span>50</span><span>125</span><span>200+</span></div>' +
                           '  </div>' +
                           '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/isric?lon={lon}&lat={lat}&property=bdod&depth=0-5cm&value=mean" data-api-param="properties.layers.0.depths.0.values.mean" data-d-factor="100" data-unit="cg/cm³">' +
                           '    <div class="aot-legend-value-text">--</div>' +
                           '    <div class="aot-legend-value-unit">kg/dm³</div>' +
                           '  </div>' +
                           '</div>'
            }
        
        return legend_data

    def get_available_channels(self):
        """
        Returns supported channels for ISRIC SoilGrids.
        """
        return [
            {'id': 'phh2o', 'name': 'Soil pH', 'unit': 'pH'},
            {'id': 'clay', 'name': 'Clay Content', 'unit': '%'},
            {'id': 'sand', 'name': 'Sand Content', 'unit': '%'},
            {'id': 'silt', 'name': 'Silt Content', 'unit': '%'},
            {'id': 'soc', 'name': 'Soil Organic Carbon', 'unit': 'dg/kg'},
            {'id': 'bdod', 'name': 'Bulk Density', 'unit': 'cg/cm³'}
        ]

    def get_data_at_location(self, lat, lng, **kwargs):
        """
        Fetches soil data from ISRIC REST API.
        """
        import requests
        
        try:
            # ISRIC REST API endpoints:
            # https://rest.isric.org/soilgrids/v2.0/properties/query?lon=...&lat=...&property=...&depth=...
            
            # We fetch all properties in one go if possible, or iterate.
            # ISRIC API supports multiple properties in one call? Yes.
            # Example: &property=phh2o&property=clay...
            
            props = ['phh2o', 'clay', 'sand', 'silt', 'soc', 'bdod']
            props_query = "&property=".join(props)
            
            # Depth: 0-5cm is standard for surface analysis
            depth = '0-5cm'
            
            url = f"https://rest.isric.org/soilgrids/v2.0/properties/query?lon={lng}&lat={lat}&property={props_query}&depth={depth}&value=mean"
            
            resp = requests.get(url, timeout=10)
            if resp.status_code != 200:
                print(f"[ISRIC] Error fetching data: {resp.status_code} {resp.text}")
                return None
            
            data = resp.json()
            # Structure: 
            # {
            #   "type": "Feature",
            #   "properties": {
            #     "layers": [
            #       { "name": "phh2o", "unit_measure": {...}, "depths": [{ "range": {"top_depth": 0, "bottom_depth": 5}, "label": "0-5cm", "values": {"mean": 64} }] },
            #       ...
            #     ]
            #   }
            # }
            
            result = {}
            layers = data.get('properties', {}).get('layers', [])
            
            for layer in layers:
                name = layer.get('name')
                depths = layer.get('depths', [])
                if not depths: continue
                
                # Assume 0-5cm or first available
                val_obj = depths[0].get('values', {})
                val = val_obj.get('mean')
                
                if val is not None:
                    # Apply conversion factors
                    # pH is scaled by 10 (e.g. 64 -> 6.4)
                    # Clay/Sand/Silt is scaled by 10 (e.g. 250 -> 25.0 %)
                    # SOC is scaled by 10 (dg/kg) -> No, SOC is dg/kg in output? 
                    # Checking unit_measure from API:
                    # phh2o: d_factor 10
                    # clay/sand/silt: d_factor 10
                    # soc: d_factor 10
                    # bdod: d_factor 100
                    
                    if name in ['phh2o', 'clay', 'sand', 'silt', 'soc']:
                         result[name] = float(val) / 10.0
                    elif name == 'bdod':
                         result[name] = float(val) / 100.0
                    else:
                         result[name] = float(val)
                         
            return result
        
        except Exception as e:
            print(f"[ISRIC] Exception in get_data_at_location: {e}")
            return None

    def get_ai_reading(self, lat, lng):
        """AI용: 토양 데이터를 사람이 읽을 수 있는 형태로 반환."""
        channel_labels = {
            'phh2o': ('Soil pH (0-5cm)', 'pH'),
            'clay':  ('Clay Content (0-5cm)', '%'),
            'sand':  ('Sand Content (0-5cm)', '%'),
            'silt':  ('Silt Content (0-5cm)', '%'),
            'soc':   ('Organic Carbon (0-5cm)', 'dg/kg'),
            'bdod':  ('Bulk Density (0-5cm)', 'kg/dm³')
        }
        try:
            data = self.get_data_at_location(lat, lng)
            if not data:
                return None
            readings = []
            for key, value in data.items():
                label, unit = channel_labels.get(key, (key, ''))
                readings.append({'label': label, 'value': round(value, 2), 'unit': unit})
            return readings if readings else None
        except Exception:
            return None
