# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg

INPUT_INFORMATION = {
    'input_name_unique': 'gis_opentopomap',
    'input_manufacturer': 'OpenTopoMap',
    'message': lg('Terrain map service based on OpenStreetMap data with emphasized contours and hillshading. Clear differentiation for mountain terrain and slope analysis, high readability, suitable for hiking and outdoor activity visualization.'),
    'country': ['GL'],
    'input_name': 'OpenTopoMap',
    'input_library': 'gis_opentopomap',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://opentopomap.org',
    'attribution': 'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, <a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',
    'options_enabled': [],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'dependencies_module': [],
    'layer_type': 'xyz',
    'time_enabled': False,
    'leaflet_options': {
        'maxNativeZoom': 17,
        'maxZoom': 19,
        'subdomains': 'abc',
        'errorTileUrl': 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
    }
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for OpenTopoMap.
    Provides terrain-focused tiles with contour lines and hill shading from OSM and SRTM data.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base'
        self.default_url = 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png'
        self.attribution = INPUT_INFORMATION['attribution']

    def get_leaflet_options(self):
        options = super().get_leaflet_options()
        options.update({
            'maxNativeZoom': 15,
            'maxZoom': 19
        })
        return options
