# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg
import datetime

INPUT_INFORMATION = {
    'input_name_unique': 'gis_esa', # Keep ID
    'input_manufacturer': 'NASA',
    'message': lg("Global surface soil moisture (0-5cm) from NASA's SMAP (Soil Moisture Active Passive) L4 product, delivered as a near-real-time overlay via NASA GIBS. Available at roughly 9km resolution with selectable dates, useful for irrigation planning and drought monitoring."),
    'country': ['GL'],
    'input_name': 'Soil Moisture (NASA SMAP)',
    'input_library': 'gis_esa',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://smap.jpl.nasa.gov/',
    'attribution': 'NASA SMAP L4 Soil Moisture',
    'options_enabled': [],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'overlay',
    'custom_options': [
        {
            'id': 'date_mode',
            'type': 'select',
            'name': 'Date Mode',
            'default': '1_day_ago',
            'options': [
                {'value': 'default', 'name': 'Auto (NASA Default)'},
                {'value': 'today', 'name': 'Today (UTC)'},
                {'value': '1_day_ago', 'name': '1 Day Ago'},
                {'value': '2_days_ago', 'name': '2 Days Ago'},
                {'value': '7_days_ago', 'name': '7 Days Ago'},
                {'value': 'custom', 'name': 'Custom Date (YYYY-MM-DD)'}
            ],
            'description': 'Choose date mode for this layer.'
        },
        {
            'id': 'target_date',
            'type': 'text',
            'name': 'Custom Date',
            'default': '',
            'placeholder': 'YYYY-MM-DD',
            'description': 'Only used if Date Mode is "Custom Date".'
        }
    ],
    'dependencies_module': [],
    # Corrected TileMatrixSet: GoogleMapsCompatible_Level6 (Confirmed by caps.xml)
    # Template: .../default/{time}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png
    'default_url': 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/SMAP_L4_Analyzed_Surface_Soil_Moisture/default/{time}/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png',
    'layer_type': 'xyz',
    'time_enabled': True,
    'leaflet_options': {
        'maxNativeZoom': 6, 
        'minZoom': 1,
        'bounds': [[-85.05112877980659,-180], [85.05112877980659,180]],
        'errorTileUrl': 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7',
        'time': 'default'
    },
    'legend': {
        'type': 'image',
        'url': 'https://gibs.earthdata.nasa.gov/legends/SMAP_Analyzed_Soil_Moisture_H.svg'
    }
}

class InputModule(AbstractGisInput):
    """
    GIS overlay provider for NASA SMAP L4 Soil Moisture.
    Provides global soil moisture data as a time-enabled overlay.

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
        self.time_enabled = True

    def _get_default_date(self):
        """
        SMAP L4 has latency. Try Yesterday.
        """
        yesterday = self._device_local_now() - datetime.timedelta(days=1)
        return yesterday.strftime('%Y-%m-%d')

    def get_url(self):
        # Return default URL template (placeholders managed by Frontend/Leaflet)
        return self.default_url

    def get_leaflet_options(self):
        """
        Leaflet 옵션을 반환하며 날짜를 동적으로 계산합니다.
        """
        options = super(InputModule, self).get_leaflet_options()
        
        base_options = INPUT_INFORMATION['leaflet_options'].copy()
        
        # 날짜 계산 로직 (Backend Smart Time)
        date_mode = self.get_custom_option('date_mode') or 'default'
        target_time = 'default'

        now = self._device_local_now()
        if date_mode == 'today':
            target_time = now.strftime('%Y-%m-%d')
        elif date_mode == '1_day_ago':
            target_time = (now - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        elif date_mode == '2_days_ago':
            target_time = (now - datetime.timedelta(days=2)).strftime('%Y-%m-%d')
        elif date_mode == '7_days_ago':
            target_time = (now - datetime.timedelta(days=7)).strftime('%Y-%m-%d')
        elif date_mode == 'custom':
            user_date = self.get_custom_option('target_date')
            if user_date and len(str(user_date).strip()) == 10:
                target_time = str(user_date).strip()
            else:
                target_time = (now - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
            
        base_options['time'] = target_time
        options.update(base_options)
        return options
        
    def get_legend(self):
        """
        Return legend configuration for NASA SMAP Soil Moisture.
        Implemented in OpenWeather style with Gradient Bar and Value Box.
        """
        return {
            'type': 'html',
            'content': '<div class="aot-legend-wrapper">' + 
                       '  <div class="aot-legend-content">' +
                       '    <div class="aot-legend-title">Soil Moisture (Root Zone)</div>' + 
                       '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #ffffe5, #f7fcb9, #addd8e, #41ab5d, #238443, #005a32);"></div>' +
                       '    <div class="aot-legend-labels"><span>Dry (0)</span><span>Wet (0.6)</span></div>' +
                       '  </div>' +
                       '  <div class="aot-legend-value-box" data-api-url="https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=soil_moisture_0_to_1cm" data-api-param="current.soil_moisture_0_to_1cm" data-unit="m³/m³">' +
                       '    <div class="aot-legend-value-text">--</div>' +
                       '    <div class="aot-legend-value-unit">m³/m³</div>' +
                       '  </div>' +
                       '</div>'
        }
