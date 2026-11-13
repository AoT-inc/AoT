# coding=utf-8
"""고도 타일(DEM) 입력의 공통 베이스.

DEM 은 다른 gis 입력과 같다. 운영자가 어느 입력을 켤지로 출처를 고르고, 키와 약관은
운영자가 해결한다. AoT 는 고도 자료를 호스팅하거나 재배포하지 않는다.

레이어 패널에 보이는 지도가 아니라 지형의 재료라서 `get_geo_config` 가 `layers` 에서
떼어 `terrain` 하나로 내린다(`utils_geo.split_terrain_layer`).
"""
from aot.inputs_gis.base_input_gis import AbstractGisInput

DEM_LAYER_TYPE = 'raster-dem'
DEM_ENCODINGS = ('terrarium', 'mapbox')

DEM_INFORMATION = {
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'options_disabled': ['period', 'measurements_delay'],
    'country': ['GL'],
    'layer_role': 'terrain',
    'layer_type': DEM_LAYER_TYPE,
    'time_enabled': False,
    'dependencies_module': [],
}


class AbstractDemInput(AbstractGisInput):
    """`raster-dem` 소스 사양을 돌려주는 입력."""

    dem_encoding = 'terrarium'
    dem_tile_size = 256
    dem_max_zoom = 12

    def __init__(self, input_dev, testing=False, name=__name__):
        super(AbstractDemInput, self).__init__(input_dev, testing=testing, name=name)
        self.layer_type = DEM_LAYER_TYPE
        self.layer_category = 'overlay'

    def get_terrain_config(self):
        """MapLibre `raster-dem` 소스에 들어갈 값. URL 은 레이어의 `url` 이 맡는다."""
        return {
            'encoding': self.dem_encoding,
            'tileSize': self.dem_tile_size,
            'maxzoom': self.dem_max_zoom,
        }
