# coding=utf-8
import datetime
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg, gettext as _

# 채널 정의 (Zoom Level 차이를 주의해야 함)
CHANNELS = {
    0: {
        'name': _('MODIS Terra TrueColor'),
        'options': {
            'layer': 'MODIS_Terra_CorrectedReflectance_TrueColor',
            'ext': 'jpg',
            'tilematrixset': 'GoogleMapsCompatible_Level9',
            'maxNativeZoom': 9
        }
    },
    1: {
        'name': _('VIIRS SNPP TrueColor'),
        'options': {
            'layer': 'VIIRS_SNPP_CorrectedReflectance_TrueColor',
            'ext': 'jpg',
            'tilematrixset': 'GoogleMapsCompatible_Level9',
            'maxNativeZoom': 9
        }
    },
    2: {
        'name': _('Blue Marble (Precip)'),
        'options': {
            'layer': 'BlueMarble_NextGeneration',
            'ext': 'jpg',
            'tilematrixset': 'GoogleMapsCompatible_Level8',
            'maxNativeZoom': 8
        }
    },
    3: {
        'name': _('Soil Moisture (SMAP)'),
        'options': {
            'layer': 'SMAP_L4_Analyzed_Root_Zone_Soil_Moisture',
            'ext': 'png',
            'tilematrixset': 'GoogleMapsCompatible_Level6',
            'maxNativeZoom': 6,
            'format': 'image/png',
            'role': 'overlay'
        }
    },
    4: {
        'name': _('Vegetation Index (NDVI)'),
        'options': {
            'layer': 'MODIS_Terra_NDVI_8Day',
            'ext': 'png',
            'tilematrixset': 'GoogleMapsCompatible_Level9',
            'maxNativeZoom': 9,
            'role': 'overlay'
        }
    },
    5: {
        'name': _('Land Surface Temp (Day)'),
        'options': {
            'layer': 'MODIS_Terra_Land_Surface_Temp_Day',
            'ext': 'png',
            'tilematrixset': 'GoogleMapsCompatible_Level7',
            'maxNativeZoom': 7,
            'role': 'overlay'
        }
    }
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_nasa_gibs',
    'input_manufacturer': 'NASA',
    'message': lg('Real-time Earth observation maps from NASA GIBS satellite system. Includes satellite imagery (Blue Marble) plus environmental data like temperature, clouds, and fires, selectable by date for time-series analysis.'),
    'input_name': 'NASA GIBS',
    'input_library': 'gis_nasa_gibs',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://earthdata.nasa.gov/eosdis/science-system-description/eosdis-components/gibs',
    'attribution': 'NASA EOSDIS GIBS',
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'base',
    'custom_options': [
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': _('Satellite Layer'),
            'channel_def': CHANNELS,
            'default': [0],
            'multiple': False
        },
        {
            'id': 'date_mode',
            'type': 'select',
            'name': _('Date Mode'),
            'default': 'default',
            'options': [
                {'value': 'default', 'name': _('Auto (NASA Default)')},
                {'value': 'today', 'name': _('Today (UTC)')},
                {'value': '1_day_ago', 'name': _('1 Day Ago')},
                {'value': '2_days_ago', 'name': _('2 Days Ago')},
                {'value': '7_days_ago', 'name': _('7 Days Ago')},
                {'value': 'custom', 'name': _('Custom Date (YYYY-MM-DD)')}
            ],
            'description': _('Choose date mode for this layer.')
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
    # Template
    'default_url': 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/{tilematrixset}/{z}/{y}/{x}.{ext}',
    'layer_type': 'xyz', # Leaflet에서는 TileLayer(xyz)로 처리
    'time_enabled': True,
    'interfaces': ['AoT'],
    'leaflet_options': {
        'minZoom': 1,
        'bounds': [[-85.05112877980659,-180], [85.05112877980659,180]],
        'errorTileUrl': 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7',
        'time': 'default' # Frontend에서 교체될 placeholder
    }
}

class InputModule(AbstractGisInput):
    """
    GIS tile provider for NASA GIBS (Global Imagery Browse Services).
    Provides satellite imagery including MODIS Terra, VIIRS, Blue Marble, plus environmental overlays for soil moisture, NDVI, and land surface temperature.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'base' # Default, will be overridden by channel
        self.default_url = INPUT_INFORMATION['default_url']
        self.attribution = INPUT_INFORMATION['attribution']
        self.time_enabled = True

    def _get_active_channel_config(self):
        """
        현재 선택된 채널의 설정(옵션)을 반환하는 헬퍼 메소드
        """
        active_channels = self.get_custom_option('active_channels')
        
        layer_id = 0 # Default ID
        
        if active_channels:
            if isinstance(active_channels, list):
                if len(active_channels) > 0:
                    layer_id = int(active_channels[0])
            else:
                try:
                    layer_id = int(active_channels)
                except:
                    pass
                    
        return CHANNELS.get(layer_id, CHANNELS[0])

    def get_url(self):
        """
        Leaflet에 전달할 URL 템플릿을 생성합니다.
        {layer}, {ext}, {tilematrixset}은 여기서 확정되고,
        {time}, {z}, {x}, {y}는 프론트엔드나 Leaflet이 처리하도록 남겨둡니다.
        """
        conf = self._get_active_channel_config()
        opts = conf.get('options', {})
        
        # URL 생성
        url = self.default_url.replace('{layer}', opts.get('layer', '')) \
                              .replace('{ext}', opts.get('ext', '')) \
                              .replace('{tilematrixset}', opts.get('tilematrixset', ''))
        
        return url

    def get_legend(self):
        """
        Return legend configuration for the active channel.
        Implemented in OpenWeather style with Gradient Bar and Value Box.
        """
        conf = self._get_active_channel_config()
        layer_name = conf.get('name', 'Satellite')
        layer_id = conf.get('options', {}).get('layer', '')
        
        legend_data = None
        
        if 'SMAP_L4_Analyzed_Root_Zone_Soil_Moisture' in layer_id:
            # Soil Moisture (SMAP)
            title = _("Soil Moisture (Root Zone)")
            dry = _("Dry")
            wet = _("Wet")
            legend_data = {
                'type': 'html',
                'content': '<div class="aot-legend-wrapper">' +
                           '  <div class="aot-legend-content">' +
                           f'    <div class="aot-legend-title">{title}</div>' +
                           '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #ffffe5, #f7fcb9, #addd8e, #41ab5d, #238443, #005a32);"></div>' +
                           f'    <div class="aot-legend-labels"><span>{dry} (0)</span><span>{wet} (0.6)</span></div>' +
                           '  </div>' +
                           '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openmeteo?latitude={lat}&longitude={lon}&current=soil_moisture_0_to_1cm" data-api-param="current.soil_moisture_0_to_1cm" data-unit="m³/m³">' +
                           '    <div class="aot-legend-value-text">--</div>' +
                           '    <div class="aot-legend-value-unit">m³/m³</div>' +
                           '  </div>' +
                           '</div>'
            }
        elif 'MODIS_Terra_NDVI_8Day' in layer_id:
            # Vegetation Index (NDVI)
            title = _("Vegetation Index (NDVI)")
            ndvi = _("NDVI")
            scale = _("Scale")
            legend_data = {
                'type': 'html',
                'content': '<div class="aot-legend-wrapper">' +
                           '  <div class="aot-legend-content">' +
                           f'    <div class="aot-legend-title">{title}</div>' +
                           '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #a50026, #d73027, #f46d43, #fdae61, #fee08b, #ffffbf, #d9ef8b, #a6d96a, #66bd63, #1a9850, #006837);"></div>' +
                           '    <div class="aot-legend-labels"><span>-0.2</span><span>0.4</span><span>1.0</span></div>' +
                           '  </div>' +
                           '  <div class="aot-legend-value-box">' +
                           f'    <div class="aot-legend-value-text">{ndvi}</div>' +
                           f'    <div class="aot-legend-value-unit">{scale}</div>' +
                           '  </div>' +
                           '</div>'
            }
        elif 'MODIS_Terra_Land_Surface_Temp_Day' in layer_id:
            # Land Surface Temp
            title = _("Land Surface Temp (Day)")
            legend_data = {
                'type': 'html',
                'content': '<div class="aot-legend-wrapper">' +
                           '  <div class="aot-legend-content">' +
                           f'    <div class="aot-legend-title">{title}</div>' +
                           '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #000080, #0000ff, #00ffff, #ffff00, #ff0000, #800000);"></div>' +
                           '    <div class="aot-legend-labels"><span>-20</span><span>20</span><span>60+</span></div>' +
                           '  </div>' +
                           '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openmeteo?latitude={lat}&longitude={lon}&current=temperature_2m" data-api-param="current.temperature_2m" data-unit="°C">' +
                           '    <div class="aot-legend-value-text">--</div>' +
                           '    <div class="aot-legend-value-unit">°C</div>' +
                           '  </div>' +
                           '</div>'
            }
            
        return legend_data

    def _get_default_date(self):
        """
        NASA GIBS는 실시간 업로드가 아니므로,
        데이터가 확실히 존재하는 '어제' 날짜를 기본값으로 사용합니다.
        """
        yesterday = datetime.datetime.utcnow() - datetime.timedelta(days=1)
        return yesterday.strftime('%Y-%m-%d')


    def get_leaflet_options(self):
        """
        Leaflet 옵션을 반환합니다. 
        선택된 채널에 따라 maxNativeZoom이 변경되며, 날짜를 동적으로 계산합니다.
        """
        options = super(InputModule, self).get_leaflet_options()
        config = self._get_active_channel_config()
        config_opts = config.get('options', {})
        
        # 기본 옵션 복제
        base_options = INPUT_INFORMATION['leaflet_options'].copy()
        base_options['maxNativeZoom'] = config_opts.get('maxNativeZoom', 9)
        base_options['tilematrixset'] = config_opts.get('tilematrixset', 'GoogleMapsCompatible_Level9')
        
        # 날짜 계산 로직 (Backend Smart Time)
        # SMAP 등 지연 레이어는 'default' (NASA 최신 가용 데이터)가 안전함
        date_mode = self.get_custom_option('date_mode')
        
        # if not date_mode check deleted

        target_time = 'default'
        
        # Blue Marble 등 시간 비종속 레이어 체크
        if 'BlueMarble' in config_opts.get('layer', ''):
             target_time = 'default'
        else:
            now = datetime.datetime.utcnow()
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

    def get_available_channels(self):
        """
        Returns supported channels for NASA GIBS (via Open-Meteo).
        """
        return [
            {'id': 'soil_moisture_0_to_10cm', 'name': 'Soil Moisture (0-10cm)', 'unit': 'm³/m³'},
            {'id': 'soil_temperature_0_to_10cm', 'name': 'Soil Temp (0-10cm)', 'unit': '°C'}
        ]

    def get_data_at_location(self, lat, lng, **kwargs):
        """
        Fetches data from Open-Meteo API (Acting as proxy for NASA GIBS analysis).
        """
        import requests
        
        try:
            # Open-Meteo API
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lng}&current=soil_moisture_0_to_10cm,soil_temperature_0_to_10cm"
            
            resp = requests.get(url, timeout=5)
            if resp.status_code != 200:
                print(f"[NASA GIBS] Error fetching data: {resp.status_code} {resp.text}")
                return None
            
            data = resp.json()
            # Structure: { "current": { "time": "...", "soil_moisture_0_to_10cm": 0.35, ... } }
            
            current = data.get('current', {})
            result = {}
            
            if 'soil_moisture_0_to_10cm' in current:
                result['soil_moisture_0_to_10cm'] = current['soil_moisture_0_to_10cm']
                
            if 'soil_temperature_0_to_10cm' in current:
                result['soil_temperature_0_to_10cm'] = current['soil_temperature_0_to_10cm']

            return result
            
        except Exception as e:
            print(f"[NASA GIBS] Exception in get_data_at_location: {e}")
            return None

    def get_ai_reading(self, lat, lng):
        """AI용: 위성 데이터를 사람이 읽을 수 있는 형태로 반환."""
        channel_labels = {
            'soil_moisture_0_to_10cm':    ('Soil Moisture (0-10cm)', 'm³/m³'),
            'soil_temperature_0_to_10cm': ('Soil Temperature (0-10cm)', '°C')
        }
        try:
            data = self.get_data_at_location(lat, lng)
            if not data:
                return None
            readings = []
            for key, value in data.items():
                label, unit = channel_labels.get(key, (key, ''))
                readings.append({'label': label, 'value': round(value, 3), 'unit': unit})
            return readings if readings else None
        except Exception:
            return None
