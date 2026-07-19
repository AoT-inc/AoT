# coding=utf-8
import time
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg, gettext as _

INPUT_INFORMATION = {
    'input_name_unique': 'gis_rainviewer',
    'input_manufacturer': lg('RainViewer'),
    'message': lg('RainViewer radar precipitation data overlay. Supports real-time rainfall tracking and animation. Compatible with both vector and raster modes.'),
    'country': ['GL'],
    'input_name': 'RainViewer (Radar)',
    'input_library': 'gis_rainviewer',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://www.rainviewer.com/',
    'url_api_key': 'https://www.rainviewer.com/api.html',
    'requires_key': True,
    'key_field': 'rainviewer',
    'attribution': 'Map Data &copy; <a href="https://www.rainviewer.com/api.html">RainViewer</a>',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'overlay',
    'legend': 'dynamic',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': 'API Key',
            'required': False,
            'description': 'Optional: Required for premium features'
        },
        {
            'id': 'color_scheme',
            'type': 'select',
            'default': '2',
            'options': [
                {'value': '2', 'name': 'Universal Blue'}
            ],
            'name': 'Color Scheme',
            'required': True,
            'description': 'Note: RainViewer API v2 supports only Universal Blue color scheme'
        },
        {
            'id': 'smoothing',
            'type': 'bool',
            'default': True,
            'name': 'Smoothing',
            'required': False
        }
    ],
    'dependencies_module': [],
    'default_url': 'https://tilecache.rainviewer.com/v2/radar/{ts}/256/{z}/{x}/{y}/{color_scheme}/{smoothing}_1.png',
    'layer_type': 'xyz',
    'time_enabled': True,
    'leaflet_options': {
        'maxNativeZoom': 7,
        'maxZoom': 25
    }
}

class InputModule(AbstractGisInput):
    """
    GIS overlay provider for RainViewer radar data.
    Supports both Leaflet (raster mode) and MapLibre (vector mode).
    Uses RainViewer API v2 for radar tile access.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'overlay'
        self.default_url = INPUT_INFORMATION['default_url']
        self.attribution = INPUT_INFORMATION['attribution']
        self.requires_key = True
        self.key_field = 'rainviewer'
        self.time_enabled = True

    def get_url(self):
        # Replace options first
        color = self.get_custom_option('color_scheme')
        if not color: color = '2'
        
        smooth = '1' if self.get_custom_option('smoothing') else '0'
        
        # Get base URL (which already has {api_key} logic if needed)
        base = super().get_url()
        
        # The frontend will need to inject {ts}
        return base.replace('{color_scheme}', color).replace('{smoothing}', smooth)

    def get_time_params(self, timestamp=None):
        # Hook for time-based logic, similar to legacy or future implementation
        return {}

    def get_leaflet_options(self):
        options = super(InputModule, self).get_leaflet_options()
        options.update(INPUT_INFORMATION.get('leaflet_options', {}))
        return options

    def get_layer_config(self):
        """
        Override to provide RainViewer-specific configuration for frontend.
        Returns config compatible with MapLibre-GL (raster tile source).
        """
        color_scheme = self.get_custom_option('color_scheme', '2')
        smoothing = '1' if self.get_custom_option('smoothing') else '0'

        # RainViewer API v2 URL pattern (timestamp placeholder for animation)
        # Note: API key is optional for tile access, but recommended
        api_key = self.get_custom_option('api_key', '')

        # Base tile URL with placeholder for timestamp (frontend will inject)
        base_url = (
            f'https://tilecache.rainviewer.com/v2/radar/'
            f'{{ts}}/256/{{z}}/{{x}}/{{y}}/{color_scheme}/{smoothing}_1.png'
        )
        if api_key:
            base_url += f'?key={api_key}'

        config = {
            'unique_id': self.unique_id,
            'name': self.input_dev.name,
            'category': 'overlay',
            'type': 'raster',  # RainViewer is raster tile
            'provider': 'rainviewer',  # Provider identifier
            'url': base_url,
            'attribution': self.attribution,
            'options': {
                'opacity': self.opacity,
                'zIndex': self.z_index,
                'visible': self.is_visible,
                'maxNativeZoom': 7,
                'maxZoom': 25,
                'tileSize': 256,
                'colorScheme': color_scheme,
                'smoothing': smoothing == '1',
                # Animation settings
                'frameInterval': 600,  # 10 minutes between frames
                'totalFrames': 12,     # 2 hours of data
            },
            'legend': self.get_legend(),
            'time_enabled': True,  # RainViewer supports time-based animation
            'api_key': api_key,
            # [GIS Vector Migration] MapLibre-specific source config
            'maplibre': {
                'sourceType': 'raster',
                'tileSize': 256,
                'minzoom': 0,
                'maxzoom': 7,
                'bounds': [-180, -85.0511, 180, 85.0511],
                'animate': True
            }
        }

        return config

    def get_legend(self):
        """
        Returns Legend HTML based on color scheme.
        """
        try:
            scheme = int(self.get_custom_option('color_scheme', 2))
        except:
            scheme = 2

        # Gradients Approximation
        gradients = {
            1: "linear-gradient(to right, #ffffff, #ababab, #575757, #000000)", # Original (Greyscale?) - Actually 'Original' is usually colored. Let's use 2 as default Blue.
            2: "linear-gradient(to right, #d1e5f0, #92c5de, #4393c3, #2166ac, #053061)", # Universal Blue
            3: "linear-gradient(to right, #ffffcc, #a1dab4, #41b6c4, #2c7fb8, #253494)", # TITAN
            4: "linear-gradient(to right, #f7fcf0, #e0f3db, #ccebc5, #a8ddb5, #7bccc4, #4eb3d3, #2b8cbe, #0868ac, #084081)", # TWC
            5: "linear-gradient(to right, #fff5f0, #fee0d2, #fcbba1, #fc9272, #fb6a4a, #ef3b2c, #cb181d, #99000d)", # Meteored
            6: "linear-gradient(to right, #00ff00, #ffff00, #ff0000, #ff00ff)", # NEXRAD
            7: "linear-gradient(to right, #00e600, #ffff00, #ff0000, #ff00ff)", # RAINBOW
            8: "linear-gradient(to right, #f7fbff, #deebf7, #c6dbef, #9ecae1, #6baed6, #4292c6, #2171b5, #08519c, #08306b)" # Dark Sky
        }

        # Fallback for 1 (Original) - often multi-colored
        if scheme == 1:
            grad = "linear-gradient(to right, #cce5ff, #00cd00, #ffff00, #ff0000, #8b008b)" 
        else:
            grad = gradients.get(scheme, gradients[2])

        title = _("Rain/Snow Intensity")
        light = _("Light")
        heavy = _("Heavy")
        snow = _("Snow")
        rain = _("Rain")
        storm = _("Storm")
        html = f"""
        <div class="aot-legend-wrapper">
            <div class="aot-legend-content">
                <div class="aot-legend-title">{title}</div>
                <div class="aot-legend-bar" style="background:{grad};"></div>
                <div class="aot-legend-labels"><span>{light}</span><span>{heavy}</span></div>

                <div style="margin-top:5px; padding-top:4px; border-top:1px solid #eee; display:flex; justify-content:space-between; font-size:9px; color:#555;">
                   <div style="display:flex; align-items:center;">
                       <span style="width:8px; height:8px; background:#ff00ff; display:inline-block; border-radius:50%; margin-right:3px;"></span> {snow}
                   </div>
                   <div style="display:flex; align-items:center;">
                       <span style="width:8px; height:8px; background:#2166ac; display:inline-block; border-radius:50%; margin-right:3px;"></span> {rain}
                   </div>
                   <div style="display:flex; align-items:center;">
                       <span style="width:8px; height:8px; background:#ff0000; display:inline-block; border-radius:50%; margin-right:3px;"></span> {storm}
                   </div>
                </div>
            </div>
            <div class="aot-legend-value-box" 
                 data-api-url="/api/geo/proxy/openmeteo?latitude={{lat}}&longitude={{lon}}&current=precipitation&forecast_days=1" 
                 data-api-param="current.precipitation" 
                 data-unit="mm/h">
                <div class="aot-legend-value-text">--</div>
                <div class="aot-legend-value-unit">mm/h</div>
            </div>
        </div>
        """
        
        return {
            'type': 'html',
            'content': html
        }
