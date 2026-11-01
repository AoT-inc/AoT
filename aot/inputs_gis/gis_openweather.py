# coding=utf-8
import time

from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg, gettext as _

# ── 예보(지도 위젯 시간 슬라이더) ───────────────────────────────────────────────
# 5일·3시간 간격 예보 한 벌을 좌표별로 캐시해 두고, 슬라이더 시각의 값은 앞뒤 두 예보를 보간한다.
_FORECAST_URL = 'https://api.openweathermap.org/data/2.5/forecast'
_FORECAST_TTL_S = 600.0
_FORECAST_STEP_S = 3 * 3600
_FORECAST_HORIZON_S = 5 * 86400 - _FORECAST_STEP_S      # 첫 예보가 다음 3시간 칸이라 끝을 한 칸 줄여 잡는다
_FORECAST_CACHE = {}                                      # (lat2, lng2, key 지문) -> (ts, [예보 항목…])

CHANNELS = {
    # ambient_tile_alpha: 구름 타일 자체의 평균 알파(김제 z5 실측 ≈ 0.38) — 정책 불투명도를 이만큼 보정한다.
    0: {'name': 'Clouds', 'options': {'layer': 'clouds_new', 'ambient_role': 'weather.cloud',
                                      'ambient_tile_alpha': 0.38}},
    1: {'name': 'Precipitation', 'options': {'layer': 'precipitation_new', 'ambient_role': 'weather.precip'}},
    2: {'name': 'Pressure', 'options': {'layer': 'pressure_new', 'ambient_role': 'weather.field'}},
    3: {'name': 'Wind', 'options': {'layer': 'wind_new', 'ambient_role': 'weather.field'}},
    4: {'name': 'Temperature', 'options': {'layer': 'temp_new', 'ambient_role': 'weather.field'}}
}

# @manual geo/layers#weather-overlays
INPUT_INFORMATION = {
    'input_name_unique': 'gis_openweather',
    'input_manufacturer': 'OpenWeatherMap',
    'url_manufacturer': 'https://openweathermap.org/',
    'url_api_key': 'https://home.openweathermap.org/api_keys',
    'message': lg('Weather-focused service displaying global weather information as map overlays. Provides real-time clouds, precipitation, temperature, wind speed, pressure, and radar data for intuitive weather situational awareness.'),
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
    'ambient_role': 'weather.field',
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
        },
        {
            # 지도 위젯 기상 표현(운량·강수·바람 칸과 효과)의 데이터 출처로 쓸지 — 레이어를 꺼 둬도 값은 쓴다.
            'id': 'use_for_ambient',
            'type': 'bool',
            'default': True,
            'name': 'Use as weather data source',
            'required': False
        },
        {
            # 이 입력의 기상 값이 관측 시각 기준으로 이보다 오래되면(초) 다음 출처로 넘긴다.
            # 비워 두면 이 모듈의 기본값(get_ambient_max_age)을 쓴다.
            'id': 'ambient_max_age',
            'type': 'text',
            'default': '',
            'name': 'Weather data max age in seconds (blank = module default)',
            'required': False
        }
    ],
    'dependencies_module': [],
    'default_url': 'https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png?appid={api_key}',
    'layer_type': 'xyz',
    'time_enabled': False
}

class InputModule(AbstractGisInput):
    """
    GIS overlay provider for OpenWeatherMap.
    Provides weather overlay tiles including clouds, precipitation, pressure, wind, and temperature.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """
    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'overlay'
        self.default_url = 'https://tile.openweathermap.org/map/{layer}/{z}/{x}/{y}.png?appid={api_key}'
        self.attribution = INPUT_INFORMATION['attribution']
        self.api_key = ''
        self.refresh_interval = 600  # OpenWeatherMap tiles update every ~10 min
        
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
            # maxZoom: how far the user may zoom the VIEW in.
            # maxNativeZoom: the real tile ceiling — beyond this the last tile is
            # upscaled instead of fetched again. These used to collapse into one
            # value here (only maxZoom was set), and the vector widget's source
            # builder falls back to maxZoom for the native cap when
            # maxNativeZoom is absent — so this map fetched genuine z19 tiles.
            # OpenWeather's own tile-zoom FAQ table only documents z0–9
            # (https://openweathermap.org/faq, "What X, Y tile coordinate
            # numbers are possible..."); z19 is 2^10 = 1024x more tile requests
            # per screen than z9, which is what made overlay-enabled maps 5–10s
            # slower to finish loading.
            'maxZoom': 19,
            'maxNativeZoom': 9,
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
                title = _("Temperature")
                legend_data = {
                    'type': 'html',
                    'content': '<div class="aot-legend-wrapper">' +
                               '  <div class="aot-legend-content">' +
                               f'    <div class="aot-legend-title">{title}</div>' +
                               '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #9d64a0, #7d52a7, #62439d, #3e50b4, #4893d0, #5cc0c0, #98d1a4, #c9e48a, #f2f7bd, #f9cc76, #f29655, #e05847, #b21f37);"></div>' +
                               '    <div class="aot-legend-labels"><span>-40</span><span>0</span><span>40</span></div>' +
                               '  </div>' +
                               '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openweather?lat={lat}&lon={lon}&units=metric" data-api-param="main.temp" data-unit="°C">' +
                               '    <div class="aot-legend-value-text">--</div>' +
                               '    <div class="aot-legend-value-unit">°C</div>' +
                               '  </div>' +
                               '</div>'
                }
            elif layer_key == 'wind_new':
                 # Wind
                title = _("Wind Speed")
                legend_data = {
                    'type': 'html',
                    'content': '<div class="aot-legend-wrapper">' +
                               '  <div class="aot-legend-content">' +
                               f'    <div class="aot-legend-title">{title}</div>' +
                               '    <div class="aot-legend-bar" style="background: linear-gradient(to right, rgba(255,255,255,0), rgba(238,206,206,0.4), rgba(179,100,188,0.7), rgba(63,33,59,0.8), rgba(116,76,172,0.9), rgba(70,0,175,1.0), rgba(13,17,38,1.0));"></div>' +
                               '    <div class="aot-legend-labels"><span>0</span><span>50</span><span>100+</span></div>' +
                               '  </div>' +
                               '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openweather?lat={lat}&lon={lon}&units=metric" data-api-param="wind.speed" data-unit="m/s">' +
                               '    <div class="aot-legend-value-text">--</div>' +
                               '    <div class="aot-legend-value-unit">m/s</div>' +
                               '  </div>' +
                               '</div>'
                }
            elif layer_key == 'clouds_new':
                # Clouds
                title = _("Clouds")
                legend_data = {
                    'type': 'html',
                    'content': '<div class="aot-legend-wrapper">' +
                               '  <div class="aot-legend-content">' +
                               f'    <div class="aot-legend-title">{title}</div>' +
                               '    <div class="aot-legend-bar" style="background: linear-gradient(to right, rgba(255,255,255,0.0), rgba(253,253,255,1.0)); border: 1px solid #eee;"></div>' +
                               '    <div class="aot-legend-labels"><span>0</span><span>50</span><span>100</span></div>' +
                               '  </div>' +
                               '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openweather?lat={lat}&lon={lon}&units=metric" data-api-param="clouds.all" data-unit="%">' +
                               '    <div class="aot-legend-value-text">--</div>' +
                               '    <div class="aot-legend-value-unit">%</div>' +
                               '  </div>' +
                               '</div>'
                }
            elif layer_key == 'precipitation_new':
                # Precipitation
                title = _("Precipitation")
                legend_data = {
                    'type': 'html',
                    'content': '<div class="aot-legend-wrapper">' +
                               '  <div class="aot-legend-content">' +
                               f'    <div class="aot-legend-title">{title}</div>' +
                               '    <div class="aot-legend-bar" style="background: linear-gradient(to right, rgba(225,200,100,0), rgba(200,150,150,0), rgba(150,150,170,0), rgba(120,120,190,0), rgba(110,110,205,0.3), rgba(80,80,225,0.7), rgba(20,20,255,0.9));"></div>' +
                               '    <div class="aot-legend-labels"><span>0</span><span>10</span><span>100+</span></div>' +
                               '  </div>' +
                               '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openweather?lat={lat}&lon={lon}&units=metric" data-api-param="rain.1h" data-unit="mm">' +
                               '    <div class="aot-legend-value-text">--</div>' +
                               '    <div class="aot-legend-value-unit">mm</div>' +
                               '  </div>' +
                               '</div>'
                }
            elif layer_key == 'pressure_new':
                # Pressure
                title = _("Pressure")
                legend_data = {
                    'type': 'html',
                    'content': '<div class="aot-legend-wrapper">' +
                               '  <div class="aot-legend-content">' +
                               f'    <div class="aot-legend-title">{title}</div>' +
                               '    <div class="aot-legend-bar" style="background: linear-gradient(to right, #0073ff, #00aaf7, #00d6de, #6cff9e, #b8ff61, #ffff00, #ffbb00, #ff6f00, #ff0000);"></div>' +
                               '    <div class="aot-legend-labels"><span>950</span><span>1013</span><span>1070</span></div>' +
                               '  </div>' +
                               '  <div class="aot-legend-value-box" data-api-url="/api/geo/proxy/openweather?lat={lat}&lon={lon}&units=metric" data-api-param="main.pressure" data-unit="hPa">' +
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

    def _fetch_current(self, lat, lng):
        """OpenWeatherMap 현재 날씨 원본(JSON). 키가 없거나 실패하면 None."""
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
            return resp.json()
        except Exception as e:
            self.logger.exception(f"[OpenWeather] Exception in _fetch_current: {e}")
            return None

    def get_data_at_location(self, lat, lng, **kwargs):
        """
        Fetches current weather data from OpenWeatherMap API.
        """
        data = self._fetch_current(lat, lng)
        if data is None:
            return None

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

    def get_ambient_max_age(self):
        # 현재 날씨는 관측소 보고 주기에 따라 수십 분 늦을 수 있다.
        return 3600

    @staticmethod
    def _precip_type_code(weather_id):
        """OpenWeather 날씨 코드 → 표준 강수 종류 코드(1 비 · 2 눈 · 3 진눈깨비 · 4 우박). 모르면 None."""
        if isinstance(weather_id, bool) or not isinstance(weather_id, int):
            return None
        if weather_id in (611, 612, 613, 615, 616):
            return 3
        if weather_id == 906:
            return 4
        if 600 <= weather_id < 700:
            return 2
        if 200 <= weather_id < 600:
            return 1
        return None

    def get_ambient_values(self, lat, lng):
        """지도 위젯 기상 표현용 표준 값. 단위는 이미 metric(m/s·°C·mm/h)이고 시정만 m → km."""
        data = self._fetch_current(lat, lng)
        if not data:
            return None
        main = data.get('main') or {}
        wind = data.get('wind') or {}
        values = {
            'temp': main.get('temp'),
            'wind_speed': wind.get('speed'),
            'wind_dir': wind.get('deg'),
            'cloud': (data.get('clouds') or {}).get('all'),
        }
        # 비·눈 블록은 내릴 때만 온다 — 없으면 0 이다(관측이 있다는 뜻).
        # 눈은 물 환산량이라 비와 더해 시간당 강수로 본다.
        values['precip'] = ((data.get('rain') or {}).get('1h') or 0) + ((data.get('snow') or {}).get('1h') or 0)
        vis = data.get('visibility')
        if isinstance(vis, (int, float)) and not isinstance(vis, bool):
            values['visibility'] = vis / 1000.0
        # 강수 종류 — 지금 내리는 중일 때만 날씨 코드에서 읽는다(예보는 보간하므로 싣지 않는다).
        if values['precip'] > 0:
            kind = self._precip_type_code((data.get('weather') or [{}])[0].get('id'))
            if kind is not None:
                values['precip_type'] = kind
        at = data.get('dt')
        return {'values': {k: v for k, v in values.items() if v is not None},
                'at': at if isinstance(at, (int, float)) else None}

    # ── 예보 표준 메서드 ──
    def get_ambient_forecast_range(self):
        """지금부터 약 5일, 3시간 간격. 키가 없으면 예보를 줄 수 없다."""
        if not (self.get_custom_option('api_key') or ''):
            return None
        now = time.time()
        return {'start': now, 'end': now + _FORECAST_HORIZON_S, 'step_s': _FORECAST_STEP_S}

    def _fetch_forecast(self, lat, lng):
        """5일 예보 항목 목록(시각순). 키가 없거나 실패하면 None. 좌표별 10분 캐시."""
        import requests

        key = self.get_custom_option('api_key') or ''
        if not key:
            return None
        ck = (round(float(lat), 2), round(float(lng), 2), key[-4:])
        hit = _FORECAST_CACHE.get(ck)
        now = time.time()
        if hit and now - hit[0] < _FORECAST_TTL_S:
            return hit[1]
        try:
            resp = requests.get(_FORECAST_URL, params={'lat': lat, 'lon': lng, 'appid': key, 'units': 'metric'},
                                timeout=5)
            if resp.status_code != 200:
                self.logger.error(f"[OpenWeather] forecast HTTP {resp.status_code}")
                return hit[1] if hit else None
            items = sorted((resp.json() or {}).get('list') or [], key=lambda e: e.get('dt') or 0)
        except Exception as exc:                                  # noqa: BLE001
            self.logger.error(f"[OpenWeather] forecast failed: {type(exc).__name__}")
            return hit[1] if hit else None
        _FORECAST_CACHE[ck] = (now, items)
        return items

    @staticmethod
    def _forecast_values(e):
        """예보 항목 하나 → 표준 값(단위는 이미 metric, 시정 m → km, 3시간 강수량 → mm/h)."""
        main, wind = e.get('main') or {}, e.get('wind') or {}
        vals = {'temp': main.get('temp'), 'wind_speed': wind.get('speed'), 'wind_dir': wind.get('deg'),
                'cloud': (e.get('clouds') or {}).get('all')}
        # 비·눈 블록은 내릴 때만 온다 — 없으면 0. 3시간 누적(물 환산)을 시간당으로 편다.
        vals['precip'] = (((e.get('rain') or {}).get('3h') or 0) + ((e.get('snow') or {}).get('3h') or 0)) / 3.0
        vis = e.get('visibility')
        if isinstance(vis, (int, float)) and not isinstance(vis, bool):
            vals['visibility'] = vis / 1000.0
        return {k: float(v) for k, v in vals.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}

    def get_ambient_forecast(self, lat, lng, t):
        """시각 ``t`` 의 예보 — 앞뒤 3시간 예보를 선형 보간(풍향은 원형), 강수만 구간 값이라 계단. 예보 범위 밖이면 None."""
        items = self._fetch_forecast(lat, lng)
        if not items:
            return None
        try:
            t = float(t)
        except (TypeError, ValueError):
            return None
        pts = [(float(e['dt']), self._forecast_values(e)) for e in items if isinstance(e.get('dt'), (int, float))]
        pts = [p for p in pts if p[1]]
        if not pts or t > pts[-1][0]:
            return None
        if t <= pts[0][0]:
            # 첫 예보 칸 앞(지금~다음 3시간 칸)은 첫 예보로 갈음한다. 그보다 훨씬 이전이면 예보가 아니다.
            if pts[0][0] - t > _FORECAST_STEP_S:
                return None
            values = dict(pts[0][1])
        else:
            hi = next(i for i, p in enumerate(pts) if p[0] >= t)
            (t0, a), (t1, b) = pts[hi - 1], pts[hi]
            w = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            values = {}
            for k in set(a) | set(b):
                if k in a and k in b:
                    if k == 'wind_dir':
                        d = ((b[k] - a[k] + 540.0) % 360.0) - 180.0
                        values[k] = (a[k] + d * w) % 360.0
                    else:
                        values[k] = a[k] + (b[k] - a[k]) * w
                else:
                    values[k] = a.get(k, b.get(k))
        # 강수는 **구간 값**이다 — 항목의 rain.3h 는 그 시각까지 직전 3시간의 합이라 블록 사이를 보간하면
        # 거의 그친 비(0.25 mm/3h)가 앞뒤 시간으로 번져 계속 내리는 모양이 된다. t 가 속한 블록의 값을
        # 계단으로 쓴다(기온·바람 같은 순간 값만 보간).
        blk = next((p for p in pts if p[0] > t), pts[-1])
        if 'precip' in blk[1]:
            values['precip'] = blk[1]['precip']
        lead = max(0.0, t - time.time())
        # 예보는 멀수록 덜 믿을 만하다 — 지평선 끝에서 0.4.
        conf = 1.0 - 0.6 * min(1.0, lead / _FORECAST_HORIZON_S)
        return {'values': values, 'at': t, 'confidence': conf}

    def get_ai_reading(self, lat, lng):
        """AI용: 기상 데이터를 사람이 읽을 수 있는 형태로 반환."""
        channel_labels = {
            'temp':       ('Temperature', '°C'),
            'humidity':   ('Humidity', '%'),
            'pressure':   ('Pressure', 'hPa'),
            'wind_speed': ('Wind Speed', 'm/s'),
            'clouds':     ('Cloudiness', '%'),
            'rain_1h':    ('Rain (1h)', 'mm')
        }
        try:
            data = self.get_data_at_location(lat, lng)
            if not data:
                return None
            readings = []
            for key, value in data.items():
                if value is None:
                    continue
                label, unit = channel_labels.get(key, (key, ''))
                readings.append({'label': label, 'value': value, 'unit': unit})
            return readings if readings else None
        except Exception:
            return None
