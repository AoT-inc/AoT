# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg

CHANNELS = {
    0: {'name': lg('Base Map'), 'options': {'type': 'base', 'url_template': 'https://map{s}.daumcdn.net/map_2d/2103cov/L{z}/{y}/{x}.png'}},
    1: {'name': lg('Satellite'), 'options': {'type': 'base', 'url_template': 'https://map{s}.daumcdn.net/map_skyview/L{z}/{y}/{x}.jpg'}},
    2: {'name': lg('Hybrid'), 'options': {'type': 'overlay', 'url_template': 'https://map{s}.daumcdn.net/map_hybrid/L{z}/{y}/{x}.png'}}
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_kakao',
    'input_manufacturer': 'Kakao',
    'country': ['KO'],
    'input_name': 'Kakao Map',
    'input_library': 'gis_kakao',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://map.kakao.com/',
    'attribution': '&copy; <a href="https://map.kakao.com/">Kakao</a>',
    'requires_key': False, # Direct Tile Access (Unofficial/Public)
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'custom_options': [
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': 'Map Type',
            'channel_def': CHANNELS,
            'default': [0],
            'multiple': False
        }
    ],
    'default_url': 'https://map1.daumcdn.net/map_2d/2103cov/L{z}/{y}/{x}.png',
    'layer_type': 'xyz',
    'params': {
        'minZoom': 1,
        'maxZoom': 14, # Kakao often has limited zoom logic in this schema?
        'tms': True # Kakao uses inverted Y (TMS style)
    },
    'leaflet_options': {
        'subdomains': '0123',
        'tms': True,
        'maxNativeZoom': 13, # Kakao L-level often maps differently
        'maxZoom': 19
    }
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for Kakao Map (Korea).
    Provides basic, satellite, and hybrid tile layers.
    WARNING: Uses EPSG:5181 internally usually. Misalignment expected on EPSG:3857.

    @phase active
    @stability unstable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.attribution = INPUT_INFORMATION['attribution']
        self._update_layer_properties()

    def _get_active_channel_id(self):
        active_channels = self.get_custom_option('active_channels')
        layer_id = 0
        if isinstance(active_channels, list) and len(active_channels) > 0:
            try: layer_id = int(active_channels[0])
            except: pass
        elif active_channels is not None:
            try: layer_id = int(active_channels)
            except: pass
        return layer_id

    def _update_layer_properties(self):
        layer_id = self._get_active_channel_id()
        channel_info = CHANNELS.get(layer_id, CHANNELS[0])
        self.layer_category = channel_info['options'].get('type', 'base')
        self.layer_type = 'tile'

    def get_url(self):
        layer_id = self._get_active_channel_id()
        channel_info = CHANNELS.get(layer_id, CHANNELS[0])
        return channel_info['options'].get('url_template', INPUT_INFORMATION['default_url'])

    def get_leaflet_options(self):
        options = super(InputModule, self).get_leaflet_options()
        options.update(INPUT_INFORMATION['leaflet_options'])
        
        # Kakao Specifics
        # Z-Index inversion logic if needed, but 'tms': True handles Y.
        # Z might need custom function if standard 3857 Z doesn't match Kakao L.
        # We rely on Leaflet's standard matching for now.
        
        return options
