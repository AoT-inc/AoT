# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg
import requests

CHANNELS = {
    0: {'name': 'Alidade Smooth', 'options': {'layer': 'alidade_smooth'}},
    1: {'name': 'Alidade Smooth Dark', 'options': {'layer': 'alidade_smooth_dark'}},
    2: {'name': 'OSM Bright', 'options': {'layer': 'osm_bright'}},
    3: {'name': 'Stamen Toner', 'options': {'layer': 'stamen_toner'}},
    4: {'name': 'Stamen Toner Lite', 'options': {'layer': 'stamen_toner_lite'}},
    5: {'name': 'Stamen Watercolor', 'options': {'layer': 'stamen_watercolor'}}, # JPG
    6: {'name': 'Stamen Terrain', 'options': {'layer': 'stamen_terrain'}},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_stadia',
    'input_manufacturer': 'Stadia Maps',
    'url_manufacturer': 'https://stadiamaps.com/',
    'url_api_key': 'https://client.stadiamaps.com/signup/',
    'message': lg('High-quality design-focused map server from Stadia Maps. Provides clean layouts with eye-comfortable colors and high-quality fonts using Alidade Smooth, Dark, OSMBright styles, ideal for professional dashboard creation.'),
    'country': ['GL'],
    'input_name': 'Stadia Maps',
    'input_library': 'gis_stadia',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'key_field': 'api_key',
    'global_key_field': 'stadia',
    # Stadia requires authentication for most domains now, though localhost is often whitelisted.
    # We enforce key field for long term stability.
    'requires_key': True,
    'url_manufacturer': 'https://stadiamaps.com/',
    'attribution': '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': 'Stadia/Stamen API Key',
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
    'default_url': 'https://tiles.stadiamaps.com/tiles/{layer}/{z}/{x}/{y}{r}.{ext}?api_key={api_key}',
    'layer_type': 'xyz',
    'time_enabled': False,
    'leaflet_options': {
        'maxZoom': 20,
        'maxNativeZoom': 20
    }
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for Stadia Maps.
    Provides Alidade Smooth, Dark, OSM Bright, and Stamen design tile styles.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base'
        self.default_url = 'https://tiles.stadiamaps.com/tiles/{layer}/{z}/{x}/{y}{r}.{ext}?api_key={api_key}'
        self.attribution = INPUT_INFORMATION['attribution']
        
        self.api_key = self.get_custom_option('api_key') or ''

    def _get_active_layer_info(self):
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
        
        from aot.inputs_gis.gis_stadia import CHANNELS
        if layer_id in CHANNELS:
            return CHANNELS[layer_id]['options']['layer']
        return 'alidade_smooth'

    def get_url(self):
        layer = self._get_active_layer_info()
        self.api_key = self.get_custom_option('api_key') or ''
        
        ext = 'png'
        if layer == 'stamen_watercolor':
            ext = 'jpg'
        
        # {r} is for retina (@2x) - we usually leave it empty unless device check?
        # Leaflet has detectRetina option, but URL needs to support it. 
        # For simplicity, we assume standard resolution or let advanced users manage retina via key/options if we supported it.
        # We'll leave {r} empty.
        
        return self.default_url.replace('{layer}', layer) \
                               .replace('{ext}', ext) \
                               .replace('{r}', '') \
                               .replace('{api_key}', self.api_key)

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
