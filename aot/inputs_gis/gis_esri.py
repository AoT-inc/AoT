# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg

INPUT_INFORMATION = {
    'input_name_unique': 'gis_esri',
    'input_manufacturer': lg('Esri'),
    'message': lg('Authoritative map service from global GIS leader Esri. Provides crisp and detailed World Imagery aerial satellite photos, optimized for accurate terrain and facility visualization.'),
    'country': ['GL'],
    'input_name': 'Esri World Imagery',
    'input_library': 'gis_esri',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://www.esri.com/',
    'attribution': '&copy; <a href="https://www.esri.com/">Esri</a>',
    'options_enabled': [],
    'options_disabled': ['period', 'measurements_delay'],
    'dependencies_module': [],
    'default_url': 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    'layer_type': 'xyz',
    'time_enabled': False,
    'leaflet_options': {
        'maxZoom': 17,
        'maxNativeZoom': 17
    }
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for Esri World Imagery.
    Provides high-resolution satellite aerial imagery.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base'
        self.default_url = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
        self.attribution = INPUT_INFORMATION['attribution']

    def get_leaflet_options(self):
        options = super().get_leaflet_options()
        options.update({
            'maxZoom': 17,
            'maxNativeZoom': 17
        })
        return options
