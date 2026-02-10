# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg

CHANNELS = {
    0: {'name': '일반지도 (Basic)', 'options': {'type': 'base', 'url_template': 'https://map.pstatic.net/nrb/styles/basic/{z}/{x}/{y}.png'}},
    1: {'name': '위성지도 (Satellite)', 'options': {'type': 'base', 'url_template': 'https://map.pstatic.net/nrb/styles/satellite/{z}/{x}/{y}.png'}},
    2: {'name': '지형도 (Terrain)', 'options': {'type': 'base', 'url_template': 'https://map.pstatic.net/nrb/styles/terrain/{z}/{x}/{y}.png'}}
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_naver',
    'input_manufacturer': 'Naver',
    'country': ['KO'],
    'input_name': 'Naver Map',
    'input_library': 'gis_naver',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://map.naver.com/',
    'attribution': '&copy; <a href="https://map.naver.com/">Naver</a>',
    'requires_key': False, 
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
    'default_url': 'https://map.pstatic.net/nrb/styles/basic/{z}/{x}/{y}.png',
    'layer_type': 'xyz',
    'leaflet_options': {
        'maxNativeZoom': 19,
        'maxZoom': 22,
        'tms': False # Naver (nrb) uses standard XYZ
    }
}

class InputModule(AbstractGisInput):
    """
    Naver Map Input Module.
    Uses Public/Mobile Tile API (Enterprise style).
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
        return options
