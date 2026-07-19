# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg
import requests

CHANNELS = {
    0: {'name': 'OpenCycleMap', 'options': {'layer': 'cycle'}},
    1: {'name': 'Transport', 'options': {'layer': 'transport'}},
    2: {'name': 'Landscape', 'options': {'layer': 'landscape'}},
    3: {'name': 'Outdoors', 'options': {'layer': 'outdoors'}},
    4: {'name': 'Transport Dark', 'options': {'layer': 'transport-dark'}},
    5: {'name': 'Spinal Map', 'options': {'layer': 'spinal-map'}},
    6: {'name': 'Pioneer', 'options': {'layer': 'pioneer'}},
    7: {'name': 'Mobile Atlas', 'options': {'layer': 'mobile-atlas'}},
    8: {'name': 'Neighbourhood', 'options': {'layer': 'neighbourhood'}},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_thunderforest',
    'input_manufacturer': 'Thunderforest',
    'url_manufacturer': 'https://www.thunderforest.com/',
    'url_api_key': 'https://manage.thunderforest.com/dashboard',
    'message': lg('Unique themed maps tailored for specific purposes using OpenStreetMap data. Experience visually striking styles including cycling routes (Cycle), public transport (Transport), night maps, and rugged landscapes.'),
    'country': ['GL'],
    'input_name': 'Thunderforest',
    'input_library': 'gis_thunderforest',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'key_field': 'api_key',
    'global_key_field': 'thunderforest',
    'requires_key': True,
    'url_manufacturer': 'https://www.thunderforest.com/',
    'attribution': '&copy; <a href="https://www.thunderforest.com/">Thunderforest</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': 'Thunderforest API Key',
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
    'default_url': 'https://tile.thunderforest.com/{layer}/{z}/{x}/{y}.png?apikey={api_key}',
    'layer_type': 'xyz',
    'time_enabled': False,
    'leaflet_options': {
        'maxZoom': 22,
        'maxNativeZoom': 18
    }
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for Thunderforest.
    Provides themed tile styles including OpenCycleMap, Transport, Landscape, and Outdoors.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base'
        self.default_url = 'https://tile.thunderforest.com/{layer}/{z}/{x}/{y}.png?apikey={api_key}'
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
        
        from aot.inputs_gis.gis_thunderforest import CHANNELS
        if layer_id in CHANNELS:
            return CHANNELS[layer_id]['options']['layer']
        return 'cycle'

    def get_url(self):
        layer = self._get_active_layer_id()
        self.api_key = self.get_custom_option('api_key') or ''
        
        return self.default_url.replace('{layer}', layer).replace('{api_key}', self.api_key)

    # Search: Nominatim Fallback
    search_capabilities = ['address', 'place']

    def search(self, query, search_type='address', **kwargs):
        # Fallback to Nominatim
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': query,
            'format': 'json',
            'limit': kwargs.get('limit', 10),
            'addressdetails': 1
        }
        headers = {
            'User-Agent': 'AoT-GIS-Client/1.0',
            'Referer': 'https://aot-dev.internal'
        }
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for item in data:
                    results.append({
                        'name': item.get('display_name'),
                        'lat': float(item.get('lat')),
                        'lng': float(item.get('lon')),
                        'address': item.get('display_name'),
                        'provider': 'nominatim-fallback'
                    })
                return results
            return {'error': 'Search Unavailable'}
        except Exception as e:
            return {'error': str(e)}
