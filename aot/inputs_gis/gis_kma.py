# coding=utf-8
import time
from aot.inputs_gis.base_input_gis import AbstractGisInput
from flask_babel import lazy_gettext as lg
from aot.utils.kma_clock import kma_wall, kma_wall_to_utc
from aot.utils.timekit import utc_now

# 필드명/단위는 kma_weather_500.py의 sfc_nc_var.php 응답 컬럼과 일치
CHANNELS = {
    0: {'name': lg('Temperature'),    'options': {'category': 'ta',     'unit': '°C'}},
    1: {'name': lg('Humidity'),       'options': {'category': 'hm',     'unit': '%'}},
    2: {'name': lg('Wind Speed'),     'options': {'category': 'ws_10m', 'unit': 'm/s'}},
    3: {'name': lg('Wind Direction'), 'options': {'category': 'wd_10m', 'unit': '°'}},
    4: {'name': lg('Pressure'),       'options': {'category': 'pa',     'unit': 'hPa'}},
    5: {'name': lg('15min Precip.'),  'options': {'category': 'rn_15m', 'unit': 'mm'}},
    6: {'name': lg('Visibility'),     'options': {'category': 'vs',     'unit': 'km'}},
    7: {'name': lg('Snow Depth'),     'options': {'category': 'sd_tot', 'unit': 'cm'}},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_kma',
    'input_manufacturer': 'Korea Meteorological Administration',
    'url_manufacturer': 'https://apihub.kma.go.kr/',
    'url_api_key': 'https://apihub.kma.go.kr/',
    'message': lg('KMA API Hub (apihub.kma.go.kr) 500m high-resolution observation data — displays location-based multi-channel weather information as a map legend. Uses the same API key as the KMA_weather_500 input.'),
    'country': ['KR'],
    'input_name': 'KMA Weather',
    'input_library': 'gis_kma',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'attribution': '&copy; <a href="https://apihub.kma.go.kr/">Korea Meteorological Administration</a>',
    'key_field': 'api_key',
    'global_key_field': 'kma',
    'requires_key': True,
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'overlay',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': 'API Key (apihub.kma.go.kr authKey)',
            'required': True
        },
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': 'Active Channels',
            'channel_def': CHANNELS,
            'default': [0, 1, 2],
            'multiple': True
        },
        {
            # 지도 위젯 기상 표현(강수·바람·시정 칸과 효과)의 데이터 출처로 쓸지.
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
    'default_url': '',
    'layer_type': 'none',
    'time_enabled': False
}

# CSV 컬럼 순서: pub_timestamp, ta, hm, wd_10m, ws_10m, pa, rn_ox, rn_15m, vs, sd_tot
_CSV_FIELDS = ['pub_timestamp', 'ta', 'hm', 'wd_10m', 'ws_10m', 'pa', 'rn_ox', 'rn_15m', 'vs', 'sd_tot']

# KMA는 미보고 관측값을 -999로 채워 보낸다(kma_weather_500.py와 동일 현상).
# 그대로 float으로 받으면 -999가 실측값(예: 기온 -999°C)으로 표시된다.
KMA_MISSING_SENTINEL_MAX = -900.0


def _to_float_or_none(v):
    try:
        v = str(v).strip()
        if v == '' or v.lower() == 'nan':
            return None
        val = float(v)
        if val <= KMA_MISSING_SENTINEL_MAX:
            return None
        return val
    except Exception:
        return None


def _parse_kma_csv(text):
    """sfc_nc_var.php CSV 응답을 파싱해 최신 행의 dict를 반환."""
    return _parse_kma_csv_with_ts(text)[1]


def _parse_kma_csv_with_ts(text):
    """(최신 행의 KST 타임스탬프 'YYYYmmddHHMM' | None, 최신 행 dict | None)."""
    best_ts = None
    best_row = {}
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        cols = [c.strip() for c in line.split(',')]
        if len(cols) != 10:
            continue
        ts = cols[0]
        if len(ts) != 12:
            continue
        try:
            if float(cols[1]) == 0.0 and float(cols[2]) == 0.0 and float(cols[5]) == 0.0:
                continue
        except Exception:
            pass
        row = {field: _to_float_or_none(cols[i]) for i, field in enumerate(_CSV_FIELDS[1:], 1)}
        # 전 필드가 -999/결측이면 이 행은 버리고 더 이전의 유효한 행을 채택한다
        # (그렇지 않으면 최신 타임스탬프가 결측행이어도 그대로 선택되어 표시할
        # 값이 하나도 안 남는다 — kma_weather_500.py에서 실제로 겪은 문제).
        if all(val is None for val in row.values()):
            continue
        if best_ts is None or ts > best_ts:
            best_ts = ts
            best_row = row
    return (best_ts, best_row) if best_ts else (None, None)


class InputModule(AbstractGisInput):
    """
    KMA (기상청) API Hub 500m 관측 데이터 레이어 — 타일 없음, 범례만 표시.
    kma_weather_500 input과 동일한 apihub.kma.go.kr API를 사용합니다.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """

    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'none'
        self.layer_category = 'overlay'
        self.default_url = ''
        self.attribution = INPUT_INFORMATION['attribution']
        self.api_key = ''
        self.refresh_interval = 300  # 5분 (kma_weather_500과 동일)

        if not testing:
            self.api_key = self.get_custom_option('api_key') or ''

    def get_url(self):
        return ''

    def _get_active_channel_ids(self):
        active = self.get_custom_option('active_channels')
        if not active:
            active = [0, 1, 2]
        elif not isinstance(active, list):
            active = [active]
        result = []
        for ch in active:
            try:
                result.append(int(ch))
            except Exception:
                pass
        return result

    def get_legend(self):
        active_channels = self._get_active_channel_ids()
        if not active_channels:
            return None

        input_id = getattr(self, 'unique_id', '')
        proxy_url = f'/api/geo/proxy/kma?lat={{lat}}&lon={{lon}}&input_id={input_id}'

        # Each active channel renders as its own standard legend row (same
        # aot-legend-wrapper/content/value-box markup every other gis_input
        # legend uses), stacked with aot-legend-item-wrapper's divider —
        # identical to how multiple distinct-layer legends stack together.
        items_html = ''
        for ch_id in active_channels:
            if ch_id not in CHANNELS:
                continue
            info = CHANNELS[ch_id]
            ch_name = info['name']
            category = info['options']['category']
            unit = info['options']['unit']
            items_html += (
                '<div class="aot-legend-item-wrapper">'
                '<div class="aot-legend-wrapper">'
                '<div class="aot-legend-content">'
                f'<div class="aot-legend-title">{ch_name}</div>'
                '</div>'
                '<div class="aot-legend-value-box"'
                f' data-api-url="{proxy_url}"'
                f' data-api-param="{category}"'
                f' data-unit="{unit}">'
                '<div class="aot-legend-value-text">--</div>'
                f'<div class="aot-legend-value-unit">{unit}</div>'
                '</div>'
                '</div>'
                '</div>'
            )

        return {
            'type': 'html',
            'content': items_html
        }

    def get_available_channels(self):
        return [{'id': info['options']['category'],
                 'name': info['name'],
                 'unit': info['options']['unit']}
                for info in CHANNELS.values()]

    def _fetch_latest(self, lat, lng, window_min, timeout=30, end=None):
        """(KST 타임스탬프, 최신 행) — 키가 없거나 실패하면 (None, None).

        ``end``: 이 시각(epoch 초)까지의 ``window_min`` 분 창을 읽는다(관측 이력). 없으면 지금까지."""
        import requests
        import datetime

        self.api_key = self.get_custom_option('api_key') or ''
        if not self.api_key:
            self.logger.warning(f"[KMA GIS] API Key missing for Input {self.unique_id}")
            return None, None

        now = kma_wall(utc_now())  # 기상청 요청 시계(KST, naive)
        if end is not None:
            now = kma_wall(float(end))
        tm2 = now.strftime('%Y%m%d%H%M')
        tm1 = (now - datetime.timedelta(minutes=window_min)).strftime('%Y%m%d%H%M')

        url = (
            'https://apihub.kma.go.kr/api/typ01/url/sfc_nc_var.php'
            f'?tm1={tm1}&tm2={tm2}&lon={lng}&lat={lat}'
            f'&obs=ta,hm,wd_10m,ws_10m,pa,rn_ox,rn_15m,vs,sd_tot'
            f'&itv=5&help=0&authKey={self.api_key}'
        )
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            if 'error' in resp.text[:200].lower():
                self.logger.error(f"[KMA GIS] API error: {resp.text[:200]}")
                return None, None
            return _parse_kma_csv_with_ts(resp.text)
        except Exception as e:
            # 예외 문구에는 authKey 가 든 URL 이 실려 오므로 종류만 남긴다.
            self.logger.error(f"[KMA GIS] request failed: {type(e).__name__}")
            return None, None

    def get_data_at_location(self, lat, lng, **kwargs):
        # kma_weather_500과 동일한 5분 윈도우 요청
        return self._fetch_latest(lat, lng, 5)[1]

    def get_ambient_max_age(self):
        # 5분 간격 관측이 보고되기까지 걸리는 시간을 넉넉히 본다.
        return 1800

    def get_ambient_values(self, lat, lng):
        """지도 위젯 기상 표현용 표준 값. 관측소망 밖이면 KMA 가 빈 응답을 주므로 None 이 된다."""
        # 위젯 응답을 오래 붙잡지 않는다 — 8초 안에 못 받으면 이번엔 건너뛴다.
        ts, row = self._fetch_latest(lat, lng, 30, timeout=8)
        return self._standard_values(ts, row)

    @staticmethod
    def _standard_values(ts, row):
        """KMA 행 → 표준 키·단위의 값 + 관측 시각(epoch 초)."""
        import datetime
        if not row:
            return None
        values = {}
        if row.get('ta') is not None:
            values['temp'] = row['ta']
        if row.get('ws_10m') is not None:
            values['wind_speed'] = row['ws_10m']
        if row.get('wd_10m') is not None:
            values['wind_dir'] = row['wd_10m'] % 360.0
        if row.get('rn_15m') is not None:
            # 15분 강수량(mm) → 시간당
            values['precip'] = max(0.0, row['rn_15m']) * 4.0
        if row.get('vs') is not None:
            # vs 는 km (sfc_nc_var 실측: 맑은 낮 36~41)
            values['visibility'] = row['vs']
        at = None
        try:
            at = kma_wall_to_utc(datetime.datetime.strptime(ts, '%Y%m%d%H%M')).timestamp()
        except (TypeError, ValueError):
            at = None
        return {'values': values, 'at': at}

    # ── 관측 이력 표준 메서드 ──
    # 관측소망 API 가 임의의 시각 창을 읽게 해 주므로 슬라이더의 과거 시각을 같은 경로로 답한다.
    _HISTORY_SPAN_S = 3 * 86400

    def get_ambient_history_range(self):
        if not (self.get_custom_option('api_key') or ''):
            return None
        now = time.time()
        return {'start': now - self._HISTORY_SPAN_S, 'end': now, 'step_s': 600}

    def get_ambient_history(self, lat, lng, t):
        """시각 ``t`` 직전 30분 창의 가장 최근 관측. 이력 범위 밖이거나 관측소망 밖이면 None."""
        try:
            t = float(t)
        except (TypeError, ValueError):
            return None
        now = time.time()
        if t > now or now - t > self._HISTORY_SPAN_S:
            return None
        ts, row = self._fetch_latest(lat, lng, 30, timeout=8, end=t)
        return self._standard_values(ts, row)

    def get_ai_reading(self, lat, lng):
        labels = {
            'ta':     ('Temperature',   '°C'),
            'hm':     ('Humidity',      '%'),
            'ws_10m': ('Wind Speed',    'm/s'),
            'wd_10m': ('Wind Dir.',     '°'),
            'pa':     ('Pressure',      'hPa'),
            'rn_15m': ('Precip 15min',  'mm'),
            'vs':     ('Visibility',    'km'),
            'sd_tot': ('Snow Depth',    'cm'),
        }
        try:
            data = self.get_data_at_location(lat, lng)
            if not data:
                return None
            return [{'label': labels.get(k, (k, ''))[0],
                     'value': v,
                     'unit':  labels.get(k, (k, ''))[1]}
                    for k, v in data.items() if v is not None]
        except Exception:
            return None
