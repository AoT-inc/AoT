# coding=utf-8
from aot.inputs_gis.base_input_dem import DEM_INFORMATION, AbstractDemInput
from flask_babel import lazy_gettext as lg

# @manual geo/layers#elevation
INPUT_INFORMATION = {
    **DEM_INFORMATION,
    'input_name_unique': 'gis_dem_maptiler',
    'input_manufacturer': 'MapTiler',
    'url_manufacturer': 'https://www.maptiler.com/',
    'url_api_key': 'https://cloud.maptiler.com/account/keys/',
    'message': lg('Elevation tiles for 3D terrain from MapTiler. Uses the MapTiler key and counts against its usage. The operator is responsible for the provider terms.'),
    'input_name': 'MapTiler Terrain',
    'input_library': 'gis_dem_maptiler',
    'default_url': 'https://api.maptiler.com/tiles/terrain-rgb-v2/tiles.json?key={api_key}',
    'key_field': 'api_key',
    'global_key_field': 'maptiler',
    'requires_key': True,
    'attribution': '&copy; <a href="https://www.maptiler.com/">MapTiler</a>',
    'options_enabled': ['custom_options'],
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': lg('MapTiler API Key'),
            'required': True
        },
    ],
}


class InputModule(AbstractDemInput):
    """MapTiler terrain-rgb. mapbox 인코딩, tiles.json."""

    dem_encoding = 'mapbox'
    dem_tile_size = 256
    dem_max_zoom = 14

    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.default_url = INPUT_INFORMATION['default_url']
        self.attribution = INPUT_INFORMATION['attribution']

    def get_url(self):
        self.api_key = self.get_custom_option('api_key') or ''
        return super(InputModule, self).get_url()
