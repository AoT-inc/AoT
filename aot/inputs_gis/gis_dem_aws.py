# coding=utf-8
from aot.inputs_gis.base_input_dem import DEM_INFORMATION, AbstractDemInput
from flask_babel import lazy_gettext as lg

# @manual geo/layers#elevation
INPUT_INFORMATION = {
    **DEM_INFORMATION,
    'input_name_unique': 'gis_dem_aws',
    'input_manufacturer': 'AWS Open Data',
    'url_manufacturer': 'https://registry.opendata.aws/terrain-tiles/',
    'message': lg('Elevation tiles for 3D terrain from the AWS Open Data registry. No API key. The data has not been updated since 2017. The operator is responsible for the provider terms.'),
    'input_name': 'AWS Terrain Tiles',
    'input_library': 'gis_dem_aws',
    'default_url': 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png',
    'attribution': '<a href="https://github.com/tilezen/joerd/blob/master/docs/attribution.md">Terrain Tiles</a>',
    'options_enabled': [],
}


class InputModule(AbstractDemInput):
    """AWS Terrain Tiles. terrarium 256 px."""

    dem_encoding = 'terrarium'
    dem_tile_size = 256
    dem_max_zoom = 15

    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.default_url = INPUT_INFORMATION['default_url']
        self.attribution = INPUT_INFORMATION['attribution']
