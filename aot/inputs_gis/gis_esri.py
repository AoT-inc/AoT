# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg

INPUT_INFORMATION = {
    'input_name_unique': 'gis_esri',
    'input_manufacturer': lg('Esri'),
    'message': lg('세계적인 GIS 기업 Esri의 공신력 있는 지도 서비스입니다. 선명하고 정교한 World Imagery 항공 위성 사진을 제공하여 지형의 세부 형상과 시설물을 정확하게 조망하기에 최적화되어 있습니다.'),
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
