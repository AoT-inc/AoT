# coding=utf-8
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg

CHANNELS = {
    0: {'name': 'Clouds', 'options': {'layer': 'clouds_new'}},
    1: {'name': 'Precipitation', 'options': {'layer': 'precipitation_new'}},
    2: {'name': 'Pressure', 'options': {'layer': 'pressure_new'}},
    3: {'name': 'Wind', 'options': {'layer': 'wind_new'}},
    4: {'name': 'Temperature', 'options': {'layer': 'temp_new'}}
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_openweather',
    'input_manufacturer': 'OpenWeatherMap',
    'url_manufacturer': 'https://openweathermap.org/',
    'url_api_key': 'https://home.openweathermap.org/api_keys',
    'message': lg('전 세계 날씨 정보를 지도에 중첩하여 보여주는 기상 전문 서비스입니다. 구름, 강수량, 기온, 풍속, 기압 및 레이더 정보를 실시간으로 제공하여 현재 기상 상황을 직관적으로 파악할 수 있게 돕습니다.'),
    'country': ['GL'],
    'input_name': 'OpenWeatherMap',
    'input_library': 'gis_openweather',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'url_manufacturer': 'https://openweathermap.org/',
    'attribution': '&copy; <a href="http://openweathermap.org">OpenWeatherMap</a>',
    'key_field': 'api_key',
    'global_key_field': 'owm',
    'requires_key': True,
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'overlay',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': 'API Key',
            'required': True
        },
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': 'Active Layers',
            'channel_def': CHANNELS,
            'default': [0],
            'multiple': True
        }
    ],
    'dependencies_module': [],
    'default_url': 'https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png?appid={api_key}',
    'layer_type': 'xyz',
    'time_enabled': False
}

class InputModule(AbstractGisInput):
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'overlay'
        self.default_url = 'https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png?appid={api_key}'
        self.attribution = INPUT_INFORMATION['attribution']
        self.api_key = ''
        
        # Load API Key from config immediately if possible
        if not testing:
            self.api_key = self.get_custom_option('api_key') or ''

    def get_url(self):
        # Channel logic
        active_channels = self.get_custom_option('active_channels')
        
        if not active_channels: active_channels = [0]
        elif not isinstance(active_channels, list): active_channels = [active_channels]
        
        first_ch_id = active_channels[0]
        try: first_ch_id = int(first_ch_id)
        except: pass
        
        from aot.inputs_gis.gis_openweather import CHANNELS
        
        layer = 'clouds_new'
        if first_ch_id in CHANNELS:
            layer = CHANNELS[first_ch_id]['options'].get('layer', 'clouds_new')
            
        # Refetch key in case it changed
        self.api_key = self.get_custom_option('api_key') or ''
        
        # Base class get_url() handles {api_key}, we handle {layer}
        base_url = super().get_url()
        return base_url.replace('{layer}', layer)

    def get_leaflet_options(self):
        options = super().get_leaflet_options()
        options.update({
            'maxZoom': 19,
            'opacity': 1.0
        })
        return options

    def get_legend(self):
        """
        Return legend configuration for the active channel.
        """
        active_channels = self.get_custom_option('active_channels')
        if not active_channels: active_channels = [0]
        elif not isinstance(active_channels, list): active_channels = [active_channels]
        
        first_ch_id = active_channels[0]
        try: first_ch_id = int(first_ch_id)
        except: pass

        # CHANNELS is in global scope
        # from aot.inputs_gis.gis_openweather import CHANNELS
        
        # Default empty
        legend_data = None
        layer_name = 'Clouds' # Default
        
        if first_ch_id in CHANNELS:
            layer_info = CHANNELS[first_ch_id]
            layer_name = layer_info['name']
            layer_key = layer_info['options'].get('layer')
            
            # HTML Legends
            if layer_key == 'temp_new':
                # Temperature
                legend_data = {
                    'type': 'html',
                    'content': '<div class="aot-legend-wrapper">' + 
                               '  <div class="aot-legend-content">' +
                               '    <div class="aot-legend-title">Temperature</div>' + 
                               '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #9d64a0, #7d52a7, #62439d, #3e50b4, #4893d0, #5cc0c0, #98d1a4, #c9e48a, #f2f7bd, #f9cc76, #f29655, #e05847, #b21f37);"></div>' +
                               '    <div class="aot-legend-labels"><span>-40</span><span>0</span><span>40</span></div>' +
                               '  </div>' +
                               '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openweather?lat={lat}&lon={lon}&appid={apiKey}&units=metric" data-api-param="main.temp" data-unit="°C">' +
                               '    <div class="aot-legend-value-text">--</div>' +
                               '    <div class="aot-legend-value-unit">°C</div>' +
                               '  </div>' +
                               '</div>'
                }
            elif layer_key == 'wind_new':
                 # Wind
                legend_data = {
                    'type': 'html',
                    'content': '<div class="aot-legend-wrapper">' + 
                               '  <div class="aot-legend-content">' +
                               '    <div class="aot-legend-title">Wind Speed</div>' + 
                               '    <div class="aot-legend-bar" style="background: linear-gradient(to right, rgba(255,255,255,0), rgba(238,206,206,0.4), rgba(179,100,188,0.7), rgba(63,33,59,0.8), rgba(116,76,172,0.9), rgba(70,0,175,1.0), rgba(13,17,38,1.0));"></div>' +
                               '    <div class="aot-legend-labels"><span>0</span><span>50</span><span>100+</span></div>' +
                               '  </div>' +
                               '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openweather?lat={lat}&lon={lon}&appid={apiKey}&units=metric" data-api-param="wind.speed" data-unit="m/s">' +
                               '    <div class="aot-legend-value-text">--</div>' +
                               '    <div class="aot-legend-value-unit">m/s</div>' +
                               '  </div>' +
                               '</div>'
                }
            elif layer_key == 'clouds_new':
                # Clouds
                legend_data = {
                    'type': 'html',
                    'content': '<div class="aot-legend-wrapper">' + 
                               '  <div class="aot-legend-content">' +
                               '    <div class="aot-legend-title">Clouds</div>' + 
                               '    <div class="aot-legend-bar" style="background: linear-gradient(to right, rgba(255,255,255,0.0), rgba(253,253,255,1.0)); border: 1px solid #eee;"></div>' +
                               '    <div class="aot-legend-labels"><span>0</span><span>50</span><span>100</span></div>' +
                               '  </div>' +
                               '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openweather?lat={lat}&lon={lon}&appid={apiKey}&units=metric" data-api-param="clouds.all" data-unit="%">' +
                               '    <div class="aot-legend-value-text">--</div>' +
                               '    <div class="aot-legend-value-unit">%</div>' +
                               '  </div>' +
                               '</div>'
                }
            elif layer_key == 'precipitation_new':
                # Precipitation
                legend_data = {
                    'type': 'html',
                    'content': '<div class="aot-legend-wrapper">' + 
                               '  <div class="aot-legend-content">' +
                               '    <div class="aot-legend-title">Precipitation</div>' + 
                               '    <div class="aot-legend-bar" style="background: linear-gradient(to right, rgba(225,200,100,0), rgba(200,150,150,0), rgba(150,150,170,0), rgba(120,120,190,0), rgba(110,110,205,0.3), rgba(80,80,225,0.7), rgba(20,20,255,0.9));"></div>' +
                               '    <div class="aot-legend-labels"><span>0</span><span>10</span><span>100+</span></div>' +
                               '  </div>' +
                               '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openweather?lat={lat}&lon={lon}&appid={apiKey}&units=metric" data-api-param="rain.1h" data-unit="mm">' +
                               '    <div class="aot-legend-value-text">--</div>' +
                               '    <div class="aot-legend-value-unit">mm</div>' +
                               '  </div>' +
                               '</div>'
                }
            elif layer_key == 'pressure_new':
                # Pressure
                legend_data = {
                    'type': 'html',
                    'content': '<div class="aot-legend-wrapper">' + 
                               '  <div class="aot-legend-content">' +
                               '    <div class="aot-legend-title">Pressure</div>' + 
                               '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #0073ff, #00aaf7, #00d6de, #6cff9e, #b8ff61, #ffff00, #ffbb00, #ff6f00, #ff0000);"></div>' +
                               '    <div class="aot-legend-labels"><span>950</span><span>1013</span><span>1070</span></div>' +
                               '  </div>' +
                               '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openweather?lat={lat}&lon={lon}&appid={apiKey}&units=metric" data-api-param="main.pressure" data-unit="hPa">' +
                               '    <div class="aot-legend-value-text">--</div>' +
                               '    <div class="aot-legend-value-unit">hPa</div>' +
                               '  </div>' +
                               '</div>'
                }
                
        return legend_data

    def get_available_channels(self):
        """
        Returns supported channels for Satellite Analysis.
        """
        return [
            {'id': 'temp', 'name': 'Temperature', 'unit': '°C'},
            {'id': 'humidity', 'name': 'Humidity', 'unit': '%'},
            {'id': 'pressure', 'name': 'Pressure', 'unit': 'hPa'},
            {'id': 'wind_speed', 'name': 'Wind Speed', 'unit': 'm/s'},
            {'id': 'clouds', 'name': 'Cloudiness', 'unit': '%'},
            {'id': 'rain_1h', 'name': 'Rain (1h)', 'unit': 'mm'}
        ]

    def get_data_at_location(self, lat, lng, **kwargs):
        """
        Fetches current weather data from OpenWeatherMap API.
        """
        import requests
        
        # Ensure API Key is available
        self.api_key = self.get_custom_option('api_key') or ''
        if not self.api_key:
            self.logger.warning(f"[OpenWeather] API Key missing for Input {self.unique_id}")
            return None
            
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lng}&appid={self.api_key}&units=metric"
            resp = requests.get(url, timeout=5)
            
            if resp.status_code != 200:
                self.logger.error(f"[OpenWeather] Error fetching data: {resp.status_code} {resp.text} (URL: {url.replace(self.api_key, '***')})")
                return None
                
            data = resp.json()
            
            # Extract relevant fields
            result = {}
            
            if 'main' in data:
                main = data['main']
                result['temp'] = main.get('temp')
                result['humidity'] = main.get('humidity')
                result['pressure'] = main.get('pressure')
            
            if 'wind' in data:
                result['wind_speed'] = data['wind'].get('speed')
                
            if 'clouds' in data:
                result['clouds'] = data['clouds'].get('all')
                
            if 'rain' in data and '1h' in data['rain']:
                result['rain_1h'] = data['rain']['1h']
            else:
                result['rain_1h'] = 0 # Default 0 if no rain block
                
            self.logger.debug(f"[OpenWeather] Data fetched successfully at {lat}, {lng}")
            return result
            
        except Exception as e:
            self.logger.exception(f"[OpenWeather] Exception in get_data_at_location: {e}")
            return None
