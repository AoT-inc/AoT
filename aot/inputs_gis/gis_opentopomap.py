# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg

INPUT_INFORMATION = {
    'input_name_unique': 'gis_opentopomap',
    'input_manufacturer': 'OpenTopoMap',
    'message': lg('OpenStreetMap 데이터를 기반으로 등고선과 지형 음영을 강조한 지형도 서비스입니다. 산악 지형이나 경사면 분석 시 구분이 명확하며 가독성이 높아 등산이나 야외 활동 관련 시각화에 적합합니다.'),
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
    OpenTopoMap GIS Input.
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
