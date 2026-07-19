# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg
import requests

CHANNELS = {
    0: {'name': 'Streets', 'options': {'layer': 'mapbox/streets-v11'}},
    1: {'name': 'Outdoors', 'options': {'layer': 'mapbox/outdoors-v11'}},
    2: {'name': 'Light', 'options': {'layer': 'mapbox/light-v10'}},
    3: {'name': 'Dark', 'options': {'layer': 'mapbox/dark-v10'}},
    4: {'name': 'Satellite', 'options': {'layer': 'mapbox/satellite-v9'}},
    5: {'name': 'Satellite Streets', 'options': {'layer': 'mapbox/satellite-streets-v11'}},
    6: {'name': 'Navigation Day', 'options': {'layer': 'mapbox/navigation-day-v1'}},
    7: {'name': 'Navigation Night', 'options': {'layer': 'mapbox/navigation-night-v1'}},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_mapbox',
    'input_manufacturer': 'Mapbox',
    'url_manufacturer': 'https://www.mapbox.com/',
    'url_api_key': 'https://account.mapbox.com/access-tokens/',
    'message': lg('Stylish Mapbox vector and tile maps with excellent customization. Supports Streets, Satellite, Dark, and Light styles with superior rendering performance for smooth map interaction.'),
    'country': ['GL'],
    'input_name': 'Mapbox',
    'input_library': 'gis_mapbox',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'key_field': 'api_key',
    'global_key_field': 'mapbox',
    'requires_key': True,
    'url_manufacturer': 'https://www.mapbox.com/',
    'attribution': '&copy; <a href="https://www.mapbox.com/about/maps/">Mapbox</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': 'Mapbox Access Token',
            'required': True
        },
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': 'Map Style',
            'channel_def': CHANNELS,
            'default': [0],
            'multiple': False
        }
    ],
    'dependencies_module': [],
    'default_url': 'https://api.mapbox.com/styles/v1/{layer}/tiles/{z}/{x}/{y}?access_token={api_key}',
    'layer_type': 'xyz',
    'time_enabled': False,
    'leaflet_options': {
        'maxZoom': 22,
        'maxNativeZoom': 18
    }
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for Mapbox.
    Provides Streets, Outdoors, Light, Dark, Satellite, and Navigation tile styles.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base'
        self.default_url = 'https://api.mapbox.com/styles/v1/{layer}/tiles/{z}/{x}/{y}?access_token={api_key}'
        self.attribution = INPUT_INFORMATION['attribution']
        
        self.api_key = self.get_custom_option('api_key') or ''

    def _get_active_layer_id(self):
        active_channels = self.get_custom_option('active_channels')
        layer_id = 0
        if isinstance(active_channels, list) and len(active_channels) > 0:
            try:
                layer_id = int(active_channels[0])
            except:
                pass
        elif active_channels is not None:
            try:
                layer_id = int(active_channels)
            except:
                pass
        
        from aot.inputs_gis.gis_mapbox import CHANNELS
        if layer_id in CHANNELS:
            return CHANNELS[layer_id]['options'].get('layer', 'mapbox/streets-v11')
        return 'mapbox/streets-v11'

    def get_url(self):
        layer = self._get_active_layer_id()
        self.api_key = self.get_custom_option('api_key') or ''
        
        # Ensure 512px tiles are handled correctly or use 256 logic?
        # Mapbox standard is 512px, but Leaflet defaults to 256. 
        # Usually standard URLs work fine but might have scale issues.
        # Adding @2x or staying standard. Standard is safe.
        
        return self.default_url.replace('{layer}', layer).replace('{api_key}', self.api_key)

    def get_leaflet_options(self):
        options = super(InputModule, self).get_leaflet_options()
        options.update({
            'maxZoom': 22,
            'maxNativeZoom': 18,
            'tileSize': 512,
            'zoomOffset': -1
        })
        return options

    # Search: Mapbox Geocoding API
    search_capabilities = ['address', 'place']

    def search(self, query, search_type='address', **kwargs):
        self.api_key = self.get_custom_option('api_key') or ''
        
        if not self.api_key:
             return {'error': 'Mapbox Access Token Missing'}

        url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{query}.json"
        params = {
            'access_token': self.api_key,
            'limit': kwargs.get('limit', 10),
            'autocomplete': 'true'
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return {'error': f"Mapbox API Error: {resp.status_code}"}
            
            data = resp.json()
            features = data.get('features', [])
            
            results = []
            for feat in features:
                center = feat.get('center', [0, 0]) # [lng, lat]
                results.append({
                    'name': feat.get('place_name', ''),
                    'lat': center[1],
                    'lng': center[0],
                    'address': feat.get('place_name', ''),
                    'provider': 'mapbox'
                })
            
            return results

        except Exception as e:
            return {'error': str(e)}
