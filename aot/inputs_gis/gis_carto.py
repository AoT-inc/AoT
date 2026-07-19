# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg

CHANNELS = {
    0: {'name': 'Positron (Light)', 'options': {'style': 'light_all'}},
    1: {'name': 'Dark Matter (Dark)', 'options': {'style': 'dark_all'}},
    2: {'name': 'Positron (No Labels)', 'options': {'style': 'light_nolabels'}},
    3: {'name': 'Dark Matter (No Labels)', 'options': {'style': 'dark_nolabels'}},
    4: {'name': 'Voyager', 'options': {'style': 'voyager'}},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_carto',
    'input_manufacturer': 'CARTO',
    'message': lg('Data analysis-focused maps from CARTO DB. Offers restrained color schemes with Positron (light), Dark Matter (dark), and Voyager styles, designed to make data points and sensor information stand out.'),
    'country': ['GL'],
    'input_name': 'Carto Maps',
    'input_library': 'gis_carto',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://carto.com/',
    'attribution': '&copy; <a href="https://carto.com/attributions">CARTO</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'custom_options': [
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': 'Active Map Styles',
            'channel_def': CHANNELS,
            'default': [0],
            'multiple': True
        }
    ],
    'dependencies_module': [],
    'default_url': 'https://{s}.basemaps.cartocdn.com/{style}/{z}/{x}/{y}{r}.png',
    'layer_type': 'xyz',
    'time_enabled': False
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for CARTO.
    Provides Positron (Light/Dark), Dark Matter, and Voyager tile styles optimized for data visualization.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base'
        self.default_url = 'https://{s}.basemaps.cartocdn.com/{style}/{z}/{x}/{y}{r}.png'
        self.attribution = INPUT_INFORMATION['attribution']

    def get_url(self):
        # Channel Support: Use the first active channel (or default)
        active_channels = self.get_custom_option('active_channels')
        
        # Ensure list (handle single value or None/Default)
        if not active_channels:
            active_channels = [0]
        elif not isinstance(active_channels, list):
            active_channels = [active_channels]
            
        # Get style from first active channel
        first_ch_id = active_channels[0]
        # Handle strict int/str typing
        try:
             first_ch_id = int(first_ch_id)
        except:
             pass
             
        # Import CHANNELS if not available in instance (It is global in file)
        from aot.inputs_gis.gis_carto import CHANNELS
        
        selected_style = 'light_all' # Fallback
        if first_ch_id in CHANNELS:
            selected_style = CHANNELS[first_ch_id]['options'].get('style', 'light_all')
            
        return self.default_url.replace('{style}', selected_style)

    def get_leaflet_options(self):
        options = super().get_leaflet_options()
        options.update({
            'subdomains': 'abcd',
            'maxZoom': 20
        })
        return options
