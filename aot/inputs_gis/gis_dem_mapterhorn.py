# coding=utf-8
from aot.inputs_gis.base_input_dem import DEM_INFORMATION, AbstractDemInput
from flask_babel import lazy_gettext as lg

# @manual geo/layers#elevation
INPUT_INFORMATION = {
    **DEM_INFORMATION,
    'input_name_unique': 'gis_dem_mapterhorn',
    'input_manufacturer': 'Mapterhorn',
    'url_manufacturer': 'https://mapterhorn.com/data-access/',
    'message': lg('Elevation tiles for 3D terrain. No API key. Check the provider terms before use; the operator is responsible for them. Attribution for each data source is listed on the provider site.'),
    'input_name': 'Mapterhorn Terrain',
    'input_library': 'gis_dem_mapterhorn',
    'default_url': 'https://tiles.mapterhorn.com/{z}/{x}/{y}.webp',
    'attribution': '&copy; <a href="https://mapterhorn.com/attribution/">Mapterhorn</a> Contains modified Copernicus DEM GLO-30',
    'options_enabled': [],
}


class InputModule(AbstractDemInput):
    """Mapterhorn 고도 타일. terrarium 512 px."""

    dem_encoding = 'terrarium'
    dem_tile_size = 512
    dem_max_zoom = 12

    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.default_url = INPUT_INFORMATION['default_url']
        self.attribution = INPUT_INFORMATION['attribution']
