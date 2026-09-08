# coding=utf-8
"""Copernicus Sentinel-2 (Sentinel Hub / CDSE) — 10m 해상도 식생지수 레이어.

## 왜 넣었나

기존 NDVI 소스는 NASA GIBS 의 `MODIS_Terra_NDVI_8Day`(250m)뿐이다. 250m 격자
한 칸이 6.25ha 라 웬만한 필지 하나가 픽셀 하나 안에 통째로 들어간다 — 필지
안의 생육 편차는 물론이고 필지 단위 판단조차 어렵다. Sentinel-2 는 10m 라
같은 6.25ha 를 625 픽셀로 본다.

## 인증 — 브라우저에 자격증명을 내리지 않는다

Sentinel Hub 는 OAuth2 client credentials 다. 타일 URL 에 키를 박아
브라우저가 직접 상류를 부르는 방식(gis_openweather 등)은 여기서 쓸 수 없다 —
client_secret 이 그대로 노출된다. 그래서 타일은 **서버 프록시**
(`/api/geo/proxy/sentinelhub/<unique_id>`)를 거친다. 토큰은 이 모듈이
프로세스 안에 캐시한다(만료 60초 전 갱신). CDSE 문서가 명시적으로 경고한다 —
요청마다 토큰을 새로 받으면 429 가 난다.

## PU(Processing Unit) 예산

CDSE 무료 등급은 월 30,000 PU 다. Process API 는 512×512·3밴드 요청이 1 PU
이고 우리는 256×256 을 쓰므로 타일 한 장이 약 0.25 PU — 화면 한 번(약 15장)에
4 PU 남짓, 월 12만 장 정도가 한도다. 그래서:

  - 타일 캐시를 24시간으로 길게 잡는다. Sentinel-2 재방문이 5일이라
    한 시간짜리 캐시(`_TILE_PROXY_TTL`)는 같은 그림을 24번 다시 사는 셈이다.
  - `minZoom` 아래(광역 뷰)에서는 프록시가 상류를 부르지 않는다. 10m 자료를
    z8 로 보는 것은 PU 만 쓰고 얻는 게 없다.

## 시간 범위

단일 날짜가 아니라 **최근 N일 구간을 모자이킹**한다. 광학위성이라 구름이 끼면
그날 그 자리는 비는데, 날짜를 하나로 고정하면 화면이 통째로 빈다. 기본은
최근 30일·구름 40% 이하·`leastCC`(그 구간에서 가장 맑은 장면)다.
"""
import json
import threading
import time

import requests
from flask_babel import gettext as _
from flask_babel import lazy_gettext as lg

from aot.inputs_gis.base_input_gis import AbstractGisInput

# CDSE(Copernicus Data Space Ecosystem) 엔드포인트. 상용 Sentinel Hub
# (services.sentinel-hub.com)와 자료·스크립트는 같고 호스트와 계정만 다르다.
TOKEN_URL = 'https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token'
PROCESS_URL = 'https://sh.dataspace.copernicus.eu/api/v1/process'
STATISTICS_URL = 'https://sh.dataspace.copernicus.eu/api/v1/statistics'

TILE_SIZE = 256
_HTTP_TIMEOUT = 30

# 지수 색상표(공통 정의). 범례 그라디언트와 evalscript 의 colorBlend 가 같은
# 색을 써야 지도와 범례가 어긋나지 않는다.
_NDVI_STOPS = [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8]
_NDVI_COLORS_JS = ('[[0.65,0.00,0.15],[0.84,0.19,0.15],[0.99,0.68,0.38],'
                   '[1.00,1.00,0.75],[0.40,0.74,0.39],[0.00,0.41,0.22]]')
_NDVI_GRADIENT_CSS = ('#a50026, #d73027, #fdae61, #ffffbf, #66bd63, #006837')

_MOISTURE_COLORS_JS = ('[[0.55,0.35,0.15],[0.87,0.76,0.55],[0.95,0.95,0.95],'
                       '[0.50,0.78,0.85],[0.10,0.45,0.72],[0.02,0.20,0.45]]')
_MOISTURE_GRADIENT_CSS = '#8c5926, #ddc28c, #f2f2f2, #80c7d9, #1a73b8, #053473'


def _index_evalscript(band_a, band_b, colors_js, stops):
    """(A-B)/(A+B) 정규화지수를 색으로 칠하는 evalscript(V3).

    알파에 `dataMask` 를 그대로 넣는다 — 관측이 없는 화소(구름 마스크·궤도 밖)를
    0 으로 칠하면 "NDVI 가 매우 낮은 땅"으로 보인다. 투명해야 없는 것이다.
    """
    return (
        '//VERSION=3\n'
        'function setup() {\n'
        f'  return {{input: ["{band_a}", "{band_b}", "dataMask"], output: {{bands: 4}}}};\n'
        '}\n'
        'function evaluatePixel(s) {\n'
        f'  let v = (s.{band_a} - s.{band_b}) / (s.{band_a} + s.{band_b});\n'
        f'  let c = colorBlend(v, {json.dumps(stops)}, {colors_js});\n'
        '  return [c[0], c[1], c[2], s.dataMask];\n'
        '}\n'
    )


def _index_stats_evalscript(band_a, band_b):
    """Statistical API 용 — 색이 아니라 값 자체를 돌려준다.

    Statistical API 는 출력 id 가 `data` 여야 하고 `dataMask` 출력이 필수다
    (없으면 구름 낀 화소가 통계에 섞인다).
    """
    return (
        '//VERSION=3\n'
        'function setup() {\n'
        f'  return {{\n'
        f'    input: [{{bands: ["{band_a}", "{band_b}", "dataMask"]}}],\n'
        '    output: [\n'
        '      {id: "data", bands: 1, sampleType: "FLOAT32"},\n'
        '      {id: "dataMask", bands: 1}\n'
        '    ]\n'
        '  };\n'
        '}\n'
        'function evaluatePixel(s) {\n'
        f'  let v = (s.{band_a} - s.{band_b}) / (s.{band_a} + s.{band_b});\n'
        '  return {data: [v], dataMask: [s.dataMask]};\n'
        '}\n'
    )


_TRUECOLOR_EVALSCRIPT = (
    '//VERSION=3\n'
    'function setup() {\n'
    '  return {input: ["B02", "B03", "B04", "dataMask"], output: {bands: 4}};\n'
    '}\n'
    'function evaluatePixel(s) {\n'
    '  return [2.5 * s.B04, 2.5 * s.B03, 2.5 * s.B02, s.dataMask];\n'
    '}\n'
)

_FALSECOLOR_EVALSCRIPT = (
    '//VERSION=3\n'
    'function setup() {\n'
    '  return {input: ["B03", "B04", "B08", "dataMask"], output: {bands: 4}};\n'
    '}\n'
    'function evaluatePixel(s) {\n'
    '  return [2.5 * s.B08, 2.5 * s.B04, 2.5 * s.B03, s.dataMask];\n'
    '}\n'
)

# 채널 = 화면에 그릴 지수 한 종류. `index` 가 있는 채널만 값 조회(범례 숫자·AI)를
# 지원한다 — 트루컬러는 숫자로 요약할 값이 없다.
CHANNELS = {
    0: {
        'name': lg('NDVI (Vegetation)'),
        'options': {
            'key': 'ndvi',
            'index': ('B08', 'B04'),
            'role': 'overlay',
            'evalscript': _index_evalscript('B08', 'B04', _NDVI_COLORS_JS, _NDVI_STOPS),
            'gradient': _NDVI_GRADIENT_CSS,
            'range': ('-0.2', '0.4', '1.0'),
        }
    },
    1: {
        'name': lg('True Color'),
        'options': {
            'key': 'truecolor',
            'index': None,
            'role': 'base',
            'evalscript': _TRUECOLOR_EVALSCRIPT,
        }
    },
    2: {
        'name': lg('NDMI (Moisture)'),
        'options': {
            'key': 'ndmi',
            'index': ('B08', 'B11'),
            'role': 'overlay',
            'evalscript': _index_evalscript('B08', 'B11', _MOISTURE_COLORS_JS, _NDVI_STOPS),
            'gradient': _MOISTURE_GRADIENT_CSS,
            'range': ('-0.2', '0.3', '0.8'),
        }
    },
    3: {
        'name': lg('NDWI (Water)'),
        'options': {
            'key': 'ndwi',
            'index': ('B03', 'B08'),
            'role': 'overlay',
            'evalscript': _index_evalscript('B03', 'B08', _MOISTURE_COLORS_JS, _NDVI_STOPS),
            'gradient': _MOISTURE_GRADIENT_CSS,
            'range': ('-0.5', '0.0', '0.5'),
        }
    },
    4: {
        'name': lg('False Color (NIR)'),
        'options': {
            'key': 'falsecolor',
            'index': None,
            'role': 'base',
            'evalscript': _FALSECOLOR_EVALSCRIPT,
        }
    },
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_sentinelhub',
    'input_manufacturer': 'Copernicus',
    'url_manufacturer': 'https://dataspace.copernicus.eu/',
    'url_api_key': 'https://shapps.dataspace.copernicus.eu/dashboard/#/account/settings',
    'message': lg(
        'Sentinel-2 imagery at 10 m resolution through Sentinel Hub on the '
        'Copernicus Data Space Ecosystem — fine enough to read growth '
        'differences inside a single field, unlike the 250 m MODIS NDVI. '
        'Register a free CDSE account, create an OAuth client and paste its '
        'Client ID and Secret below. The free tier allows 30,000 processing '
        'units per month; one map screen costs roughly 4, and tiles are '
        'cached for a day.'),
    'country': ['GL'],
    'input_name': 'Sentinel-2 (Sentinel Hub)',
    'input_library': 'gis_sentinelhub',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'attribution': '&copy; <a href="https://dataspace.copernicus.eu/">Copernicus Sentinel-2</a>',
    'key_field': 'client_id',
    'global_key_field': 'sentinelhub',
    'requires_key': True,
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'overlay',
    'custom_options': [
        {
            'id': 'client_id',
            'type': 'text',
            'default': '',
            'name': lg('OAuth Client ID'),
            'required': True
        },
        {
            'id': 'client_secret',
            'type': 'text',
            'default': '',
            'name': lg('OAuth Client Secret'),
            'required': True
        },
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': lg('Layer'),
            'channel_def': CHANNELS,
            'default': [0],
            'multiple': False
        },
        {
            'id': 'collection',
            'type': 'select',
            'name': lg('Collection'),
            'default': 'sentinel-2-l2a',
            'options': [
                {'value': 'sentinel-2-l2a', 'name': lg('Sentinel-2 L2A (atmospherically corrected)')},
                {'value': 'sentinel-2-l1c', 'name': lg('Sentinel-2 L1C (top of atmosphere)')}
            ]
        },
        {
            'id': 'time_window_days',
            'type': 'select',
            'name': lg('Search Window'),
            'default': '30',
            'options': [
                {'value': '7', 'name': lg('Last 7 days')},
                {'value': '14', 'name': lg('Last 14 days')},
                {'value': '30', 'name': lg('Last 30 days')},
                {'value': '60', 'name': lg('Last 60 days')},
                {'value': '90', 'name': lg('Last 90 days')}
            ],
            'description': lg(
                'Clouds leave holes in any single date, so the most recent '
                'usable scene within this window is drawn instead.')
        },
        {
            'id': 'max_cloud',
            'type': 'select',
            'name': lg('Max Cloud Coverage'),
            'default': '40',
            'options': [
                {'value': '10', 'name': '10%'},
                {'value': '20', 'name': '20%'},
                {'value': '40', 'name': '40%'},
                {'value': '70', 'name': '70%'},
                {'value': '100', 'name': '100%'}
            ]
        },
        {
            'id': 'mosaicking_order',
            'type': 'select',
            'name': lg('Scene Priority'),
            'default': 'leastCC',
            'options': [
                {'value': 'leastCC', 'name': lg('Clearest scene in window')},
                {'value': 'mostRecent', 'name': lg('Most recent scene')}
            ]
        }
    ],
    'dependencies_module': [],
    # 실제 URL 은 get_url() 이 프록시 경로로 만든다. 자격증명이 브라우저로
    # 나가면 안 되므로 상류 URL 을 템플릿에 두지 않는다.
    'default_url': '',
    'layer_type': 'xyz',
    'time_enabled': False,
    'interfaces': ['AoT'],
}

# 10m 자료를 광역 뷰에서 부르는 것은 PU 낭비다(파일 상단 주석).
MIN_ZOOM = 9
MAX_NATIVE_ZOOM = 16

# ---------------------------------------------------------------------------
# OAuth 토큰 캐시 — 프로세스 공용
# ---------------------------------------------------------------------------
# CDSE 는 토큰 발급 자체에 rate limit 을 건다("Do not fetch a new token for each
# API request"). 타일 프록시는 화면당 십수 번 호출되므로 캐시가 필수다.
_token_lock = threading.Lock()
_token_cache = {}  # {client_id: (access_token, expires_at_epoch)}
_TOKEN_EARLY_REFRESH = 60  # 만료 직전 요청이 401 로 죽지 않도록 미리 갱신


def get_access_token(client_id, client_secret, logger=None):
    """client credentials 로 액세스 토큰을 얻는다(캐시 적용). 실패 시 None."""
    if not client_id or not client_secret:
        return None

    now = time.time()
    cached = _token_cache.get(client_id)
    if cached and cached[1] > now:
        return cached[0]

    with _token_lock:
        cached = _token_cache.get(client_id)
        if cached and cached[1] > time.time():
            return cached[0]
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    'grant_type': 'client_credentials',
                    'client_id': client_id,
                    'client_secret': client_secret,
                },
                timeout=_HTTP_TIMEOUT)
            if resp.status_code != 200:
                if logger:
                    logger.error('[SentinelHub] token %s: %s',
                                 resp.status_code, resp.text[:200])
                return None
            payload = resp.json()
        except Exception as exc:                                # noqa: BLE001
            if logger:
                logger.error('[SentinelHub] token request failed: %s', exc)
            return None

        token = payload.get('access_token')
        if not token:
            return None
        expires_in = int(payload.get('expires_in') or 600)
        _token_cache[client_id] = (
            token, time.time() + max(expires_in - _TOKEN_EARLY_REFRESH, 30))
        return token


def get_channel_config(channel_id):
    """채널 정의. 범위를 벗어나면 기본 채널(NDVI)."""
    try:
        channel_id = int(channel_id)
    except (TypeError, ValueError):
        channel_id = 0
    return CHANNELS.get(channel_id, CHANNELS[0])


def time_range(days):
    """(from, to) ISO8601 UTC 문자열. **날짜 경계로 맞춘다.**

    초 단위 `now` 를 그대로 쓰면 요청 본문이 매 초 달라져 타일 캐시 키가 늘
      새것이 된다 — 캐시가 영영 안 맞고 PU 만 쓴다. 하루 단위로 끊으면 같은
    날 안에서는 같은 요청이 되어 캐시 수명(24시간)과도 맞아떨어진다.
    """
    import datetime as _dt
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 30
    today = _dt.datetime.now(_dt.timezone.utc).date()
    start = today - _dt.timedelta(days=max(days, 1))
    end = today + _dt.timedelta(days=1)  # 오늘 관측분까지 포함
    fmt = '%Y-%m-%dT00:00:00Z'
    return start.strftime(fmt), end.strftime(fmt)


def _data_filter(settings):
    flt = {
        'timeRange': {
            'from': settings['time_from'],
            'to': settings['time_to'],
        },
        'mosaickingOrder': settings.get('mosaicking_order') or 'leastCC',
    }
    try:
        max_cloud = int(settings.get('max_cloud') or 40)
    except (TypeError, ValueError):
        max_cloud = 40
    if max_cloud < 100:
        flt['maxCloudCoverage'] = max_cloud
    return flt


def tile_bbox_3857(z, x, y):
    """XYZ 타일 좌표 → EPSG:3857 BBOX (minx, miny, maxx, maxy).

    origin 은 웹 메르카토르의 반폭 π·6378137 m 이다.
    """
    origin = 20037508.342789244
    span = (2.0 * origin) / (2 ** z)
    minx = -origin + x * span
    maxx = minx + span
    maxy = origin - y * span
    miny = maxy - span
    return (minx, miny, maxx, maxy)


def fetch_tile_png(settings, z, x, y, logger=None):
    """Process API 로 타일 한 장(PNG bytes)을 받아온다. 실패 시 None."""
    token = get_access_token(settings.get('client_id'),
                             settings.get('client_secret'), logger=logger)
    if not token:
        return None

    channel = get_channel_config(settings.get('channel_id'))
    bbox = tile_bbox_3857(z, x, y)

    body = {
        'input': {
            'bounds': {
                'bbox': list(bbox),
                'properties': {'crs': 'http://www.opengis.net/def/crs/EPSG/0/3857'}
            },
            'data': [{
                'type': settings.get('collection') or 'sentinel-2-l2a',
                'dataFilter': _data_filter(settings),
            }]
        },
        'output': {
            'width': TILE_SIZE,
            'height': TILE_SIZE,
            'responses': [{'identifier': 'default', 'format': {'type': 'image/png'}}]
        },
        'evalscript': channel['options']['evalscript'],
    }

    try:
        resp = requests.post(
            PROCESS_URL,
            json=body,
            headers={'Authorization': f'Bearer {token}', 'Accept': 'image/png'},
            timeout=_HTTP_TIMEOUT)
    except Exception as exc:                                    # noqa: BLE001
        if logger:
            logger.warning('[SentinelHub] tile request failed: %s', exc)
        return None

    if resp.status_code != 200:
        if logger:
            logger.warning('[SentinelHub] tile %s: %s',
                           resp.status_code, resp.text[:200])
        return None
    return resp.content


def fetch_index_stats(settings, lat, lng, box_m=60, logger=None):
    """좌표 주변 정사각 구역의 지수 통계(mean/min/max). 실패 시 None.

    `box_m` 는 한 변 길이(m). 기본 60m 는 Sentinel-2 화소 6×6 으로, 한 화소만
    보면 구름 가장자리 하나에 값이 휘둘리고 너무 넓으면 옆 필지가 섞인다.
    """
    channel = get_channel_config(settings.get('channel_id'))
    index = channel['options'].get('index')
    if not index:
        return None  # 트루컬러 등 값이 없는 채널

    token = get_access_token(settings.get('client_id'),
                             settings.get('client_secret'), logger=logger)
    if not token:
        return None

    import math
    half_lat = (box_m / 2.0) / 111320.0
    half_lng = half_lat / max(math.cos(math.radians(lat)), 0.01)
    bbox = [lng - half_lng, lat - half_lat, lng + half_lng, lat + half_lat]

    band_a, band_b = index
    body = {
        'input': {
            'bounds': {
                'bbox': bbox,
                'properties': {'crs': 'http://www.opengis.net/def/crs/OGC/1.3/CRS84'}
            },
            'data': [{
                'type': settings.get('collection') or 'sentinel-2-l2a',
                'dataFilter': _data_filter(settings),
            }]
        },
        'aggregation': {
            'timeRange': {
                'from': settings['time_from'],
                'to': settings['time_to'],
            },
            # 구간 전체를 한 칸으로 묶는다 — 날짜별로 쪼개면 구름 낀 날의 빈
            # 구간까지 응답에 섞여 "최근 값" 을 고르는 일이 다시 생긴다.
            'aggregationInterval': {'of': 'P100Y'},
            'resx': 10,
            'resy': 10,
            'evalscript': _index_stats_evalscript(band_a, band_b),
        }
    }

    try:
        resp = requests.post(
            STATISTICS_URL,
            json=body,
            headers={'Authorization': f'Bearer {token}'},
            timeout=_HTTP_TIMEOUT)
        if resp.status_code != 200:
            if logger:
                logger.warning('[SentinelHub] stats %s: %s',
                               resp.status_code, resp.text[:200])
            return None
        payload = resp.json()
    except Exception as exc:                                    # noqa: BLE001
        if logger:
            logger.warning('[SentinelHub] stats request failed: %s', exc)
        return None

    for entry in reversed(payload.get('data') or []):
        stats = (((entry.get('outputs') or {}).get('data') or {})
                 .get('bands') or {}).get('B0', {}).get('stats')
        if not stats:
            continue
        # 전 화소가 마스킹된 구간(구름·궤도 밖)은 mean 이 없다 — 건너뛰고
        # 더 이전 구간을 본다.
        mean = stats.get('mean')
        if mean is None:
            continue
        return {
            'key': channel['options']['key'],
            'mean': mean,
            'min': stats.get('min'),
            'max': stats.get('max'),
            'interval_to': (entry.get('interval') or {}).get('to'),
        }
    return None


class InputModule(AbstractGisInput):
    """Sentinel-2 10m 타일 레이어 — 타일은 서버 프록시를 거친다.

    @phase active
    @stability stable
    @dependency AbstractGisInput
    """

    def __init__(self, input_dev, testing=False):
        super(InputModule, self).__init__(input_dev, testing=testing, name=__name__)
        self.layer_type = 'tile'
        self.layer_category = 'overlay'
        self.default_url = ''
        self.attribution = INPUT_INFORMATION['attribution']
        # 재방문 5일짜리 자료다. 화면을 다시 그릴 때마다 상류를 부르면 PU 만 쓴다.
        self.refresh_interval = 0

    # -- 설정 ---------------------------------------------------------------

    def _channel_id(self):
        active = self.get_custom_option('active_channels')
        if isinstance(active, list):
            active = active[0] if active else 0
        try:
            return int(active)
        except (TypeError, ValueError):
            return 0

    def request_settings(self):
        """프록시/통계 호출이 필요로 하는 값 한 벌."""
        time_from, time_to = time_range(self.get_custom_option('time_window_days') or 30)
        return {
            'client_id': self.get_custom_option('client_id') or '',
            'client_secret': self.get_custom_option('client_secret') or '',
            'collection': self.get_custom_option('collection') or 'sentinel-2-l2a',
            'max_cloud': self.get_custom_option('max_cloud') or 40,
            'mosaicking_order': self.get_custom_option('mosaicking_order') or 'leastCC',
            'channel_id': self._channel_id(),
            'time_from': time_from,
            'time_to': time_to,
        }

    # -- 레이어 -------------------------------------------------------------

    def get_url(self):
        return (f'/api/geo/proxy/sentinelhub/{getattr(self, "unique_id", "")}'
                '?z={z}&x={x}&y={y}')

    def get_leaflet_options(self):
        options = super(InputModule, self).get_leaflet_options()
        channel = get_channel_config(self._channel_id())
        options.update({
            'minZoom': MIN_ZOOM,
            'maxNativeZoom': MAX_NATIVE_ZOOM,
            'maxZoom': 20,
            'tileSize': TILE_SIZE,
            'opacity': 1.0,
            # 타일 프록시가 이 값을 캐시 수명으로 읽는다.
            'cache_seconds': 86400,
            'role': channel['options'].get('role', 'overlay'),
        })
        return options

    def get_legend(self):
        channel = get_channel_config(self._channel_id())
        opts = channel['options']
        if not opts.get('gradient'):
            return None

        # 채널 이름은 이미 lazy_gettext 다 — f-string 이 현재 로케일로 편다.
        title = channel['name']
        low, mid, high = opts.get('range', ('-1', '0', '1'))
        input_id = getattr(self, 'unique_id', '')
        proxy_url = (f'/api/geo/proxy/sentinelhub/{input_id}/value'
                     '?lat={lat}&lon={lon}')

        return {
            'type': 'html',
            'content': (
                '<div class="aot-legend-wrapper">'
                '<div class="aot-legend-content">'
                f'<div class="aot-legend-title">{title}</div>'
                f'<div class="aot-legend-bar" style="background: linear-gradient(to right, {opts["gradient"]});"></div>'
                f'<div class="aot-legend-labels"><span>{low}</span><span>{mid}</span><span>{high}</span></div>'
                '</div>'
                f'<div class="aot-legend-value-box" data-api-url="{proxy_url}"'
                ' data-api-param="mean" data-unit="">'
                '<div class="aot-legend-value-text">--</div>'
                f'<div class="aot-legend-value-unit">{_("index")}</div>'
                '</div>'
                '</div>'
            )
        }

    # -- 값 조회 ------------------------------------------------------------

    def get_available_channels(self):
        return [{'id': info['options']['key'],
                 'name': str(info['name']),
                 'unit': 'index'}
                for info in CHANNELS.values()
                if info['options'].get('index')]

    def get_data_at_location(self, lat, lng, **kwargs):
        stats = fetch_index_stats(self.request_settings(), float(lat), float(lng),
                                  logger=self.logger)
        if not stats:
            return None
        return {stats['key']: stats['mean']}

    def get_ai_reading(self, lat, lng):
        """AI용: 이 좌표의 지수 평균과 그 값이 관측된 시점."""
        try:
            settings = self.request_settings()
            stats = fetch_index_stats(settings, float(lat), float(lng),
                                      logger=self.logger)
            if not stats:
                return None
            channel = get_channel_config(settings['channel_id'])
            readings = [{
                'label': str(channel['name']),
                'value': round(stats['mean'], 3),
                'unit': 'index'
            }]
            if stats.get('interval_to'):
                readings.append({
                    'label': 'Observed within',
                    'value': f"{settings['time_from'][:10]} ~ {settings['time_to'][:10]}",
                    'unit': ''
                })
            return readings
        except Exception:
            return None
