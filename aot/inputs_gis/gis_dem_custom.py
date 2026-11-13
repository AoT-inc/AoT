# coding=utf-8
import html

from aot.inputs_gis.base_input_dem import DEM_ENCODINGS, DEM_INFORMATION, AbstractDemInput
from flask_babel import lazy_gettext as lg

# @manual geo/layers#elevation
INPUT_INFORMATION = {
    **DEM_INFORMATION,
    'input_name_unique': 'gis_dem_custom',
    'input_manufacturer': 'Custom',
    'message': lg('Elevation tiles for 3D terrain from a tile server you choose, such as your own copy. The operator is responsible for the data license and attribution.'),
    'input_name': 'Custom Terrain Tiles',
    'input_library': 'gis_dem_custom',
    'options_enabled': ['custom_options'],
    'custom_options': [
        {
            'id': 'url',
            'type': 'text',
            'default': '',
            'name': lg('Tile URL'),
            'phrase': lg('XYZ tile URL with {z}, {x}, {y}, or a TileJSON URL'),
            'required': True
        },
        {
            'id': 'encoding',
            'type': 'select',
            'default': 'terrarium',
            'options_select': [(e, e) for e in DEM_ENCODINGS],
            'name': lg('Elevation Encoding')
        },
        {
            'id': 'tile_size',
            'type': 'select',
            'default': '256',
            'options_select': [('256', '256'), ('512', '512')],
            'name': lg('Tile Size')
        },
        {
            'id': 'max_zoom',
            'type': 'integer',
            'default': 12,
            'name': lg('Maximum Zoom')
        },
        {
            'id': 'attribution_text',
            'type': 'text',
            'default': '',
            'name': lg('Attribution'),
            'phrase': lg('Plain text shown on the map')
        },
    ],
}


class InputModule(AbstractDemInput):
    """운영자가 지정한 고도 타일 서버."""

    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)

    def get_url(self):
        return self.get_custom_option('url') or ''

    def get_terrain_config(self):
        encoding = self.get_custom_option('encoding')
        try:
            tile_size = int(self.get_custom_option('tile_size'))
            max_zoom = int(self.get_custom_option('max_zoom'))
        except (TypeError, ValueError):
            tile_size, max_zoom = self.dem_tile_size, self.dem_max_zoom
        return {
            'encoding': encoding if encoding in DEM_ENCODINGS else self.dem_encoding,
            'tileSize': tile_size,
            'maxzoom': max_zoom,
            'attribution': html.escape(self.get_custom_option('attribution_text') or ''),
        }
