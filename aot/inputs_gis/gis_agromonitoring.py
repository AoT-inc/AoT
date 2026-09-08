# coding=utf-8
"""Agromonitoring — 등록한 필지(폴리곤)의 NDVI 통계와 토양 수분·지온.

## 왜 넣었나

두 가지가 다른 입력에 없다.

1. **토양 수분·지온을 숫자로** 준다. `gis_esa`(NASA GIBS SMAP)는 9km 격자를
   그림으로 덮을 뿐이고, `gis_nasa_gibs` 범례의 토양 수분 숫자는 실은
   Open-Meteo 모델값을 빌려 온 것이다(그 파일 `get_data_at_location` 참조).
   여기 값은 필지 폴리곤 단위다.
2. **위성 처리 파이프라인 없이** NDVI 통계(mean/min/max)를 바로 준다.
   `gis_sentinelhub` 은 10m 원본을 직접 다루는 대신 계정·PU 예산이 필요한데,
   이쪽은 폴리곤을 등록해 두면 계산된 값이 나온다.

## 그림(타일)은 일부러 안 붙였다

Agromonitoring 도 NDVI 타일을 주지만 두 가지 이유로 값만 쓴다.
첫째, 10m 원본 그림은 `gis_sentinelhub` 이 더 잘 그린다. 둘째, 무료 등급의
호출·폴리곤 한도가 공개돼 있지 않다(2026-09 확인: 가격 페이지에 수치 없음).
타일은 화면 한 번에 십수 번 호출되므로, 한도를 모르는 채 붙이면 사용자
계정이 조용히 막힌다. 값 조회는 화면당 한 번이고 서버에서 30분 캐시한다.

## 폴리곤

Agromonitoring 은 좌표가 아니라 **등록된 폴리곤 id** 로 조회한다.
필지는 agromonitoring.com 대시보드에서 만든다(1~3000ha). 여기에 id 를 비워
두면 계정의 폴리곤 목록에서 클릭 지점을 포함하는 것을 찾아 쓴다 —
없으면 중심이 가장 가까운 것을 쓰고, 그것도 없으면 값을 못 준다.

## 단위

지온은 **켈빈**으로 온다(문서 명시). °C 로 바꿔 내보낸다 — 안 바꾸면
지온 300 이 그대로 표시된다.
"""
import math
import time

import requests
from flask_babel import lazy_gettext as lg

from aot.inputs_gis.base_input_gis import AbstractGisInput

API_BASE = 'https://api.agromonitoring.com/agro/1.0'
_TIMEOUT = 15

CHANNELS = {
    0: {'name': lg('NDVI (mean)'),        'options': {'key': 'ndvi',     'unit': 'index'}},
    1: {'name': lg('Soil Moisture'),      'options': {'key': 'moisture', 'unit': 'm³/m³'}},
    2: {'name': lg('Soil Temp (surface)'), 'options': {'key': 't0',      'unit': '°C'}},
    3: {'name': lg('Soil Temp (10cm)'),   'options': {'key': 't10',      'unit': '°C'}},
}

INPUT_INFORMATION = {
    'input_name_unique': 'gis_agromonitoring',
    'input_manufacturer': 'Agromonitoring',
    'url_manufacturer': 'https://agromonitoring.com/',
    'url_api_key': 'https://home.openweathermap.org/api_keys',
    'message': lg(
        'Per-field NDVI statistics and soil moisture / soil temperature for a '
        'polygon registered at agromonitoring.com — the only input here that '
        'reports soil moisture as a number for your own field boundary rather '
        'than as a coarse satellite overlay. Draw the field in the '
        'Agromonitoring dashboard (1-3000 ha) and either paste its polygon ID '
        'below or leave it empty to match the polygon containing the point '
        'you click. Uses the same account as OpenWeatherMap.'),
    'country': ['GL'],
    'input_name': 'Agromonitoring (Field NDVI/Soil)',
    'input_library': 'gis_agromonitoring',
    'measurements_name': 'Status',
    'measurements_dict': {
        'status': {
            'measurement': 'status',
            'unit': 'enabled',
            'name': 'Status'
        }
    },
    'attribution': '&copy; <a href="https://agromonitoring.com/">Agromonitoring</a>',
    'key_field': 'api_key',
    'global_key_field': 'agromonitoring',
    'requires_key': True,
    'options_enabled': ['custom_options'],
    'options_disabled': ['period', 'measurements_delay'],
    'layer_role': 'overlay',
    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default': '',
            'name': lg('API Key'),
            'required': True
        },
        {
            'id': 'polygon_id',
            'type': 'text',
            'default': '',
            'name': lg('Polygon ID'),
            'description': lg(
                'Leave empty to auto-match the registered polygon that '
                'contains the clicked point.')
        },
        {
            'id': 'active_channels',
            'type': 'channel_selector',
            'name': lg('Active Channels'),
            'channel_def': CHANNELS,
            'default': [0, 1, 2],
            'multiple': True
        },
        {
            'id': 'ndvi_window_days',
            'type': 'select',
            'name': lg('NDVI Search Window'),
            'default': '30',
            'options': [
                {'value': '14', 'name': lg('Last 14 days')},
                {'value': '30', 'name': lg('Last 30 days')},
                {'value': '60', 'name': lg('Last 60 days')},
                {'value': '90', 'name': lg('Last 90 days')}
            ],
            'description': lg(
                'The most recent pass within this window is used. Clouds can '
                'leave weeks without a usable scene.')
        }
    ],
    'dependencies_module': [],
    'default_url': '',
    # 타일 없이 값만 그린다(파일 상단 주석) — gis_kma 와 같은 방식.
    'layer_type': 'none',
    'time_enabled': False,
    'interfaces': ['AoT'],
}

# 폴리곤 목록은 자주 바뀌지 않는다. 좌표 조회마다 목록을 다시 받으면 호출
# 한도를 그만큼 더 쓴다.
_POLYGON_CACHE_TTL = 600
_polygon_cache = {}  # {api_key: (polygons, expires_at)}


def _kelvin_to_c(value):
    try:
        return round(float(value) - 273.15, 2)
    except (TypeError, ValueError):
        return None


def _point_in_ring(lng, lat, ring):
    """레이 캐스팅. 닫힌 링·열린 링 모두 그대로 받는다.

    turf 의 `booleanPointInPolygon` 은 열린 링에 예외를 던지는데(그 함정으로
    한 번 데인 적이 있다), 여기서는 첫 점과 끝 점이 같든 다르든 각 변을 도는
    같은 계산이라 문제가 되지 않는다.
    """
    inside = False
    count = len(ring)
    if count < 3:
        return False
    j = count - 1
    for i in range(count):
        try:
            xi, yi = float(ring[i][0]), float(ring[i][1])
            xj, yj = float(ring[j][0]), float(ring[j][1])
        except (TypeError, ValueError, IndexError):
            j = i
            continue
        if ((yi > lat) != (yj > lat)) and \
                (lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def _polygon_contains(polygon, lat, lng):
    geo = (polygon or {}).get('geo_json') or {}
    geometry = geo.get('geometry') or geo
    coords = geometry.get('coordinates') or []
    gtype = geometry.get('type')
    if gtype == 'Polygon':
        rings = [coords[0]] if coords else []
    elif gtype == 'MultiPolygon':
        rings = [part[0] for part in coords if part]
    else:
        return False
    # 안쪽 구멍(hole)은 보지 않는다 — 농지 폴리곤에 구멍이 있는 경우는 드물고,
    # 있더라도 "이 필지의 값" 이라는 답은 달라지지 않는다.
    return any(_point_in_ring(lng, lat, ring) for ring in rings)


def list_polygons(api_key, logger=None):
    """계정의 폴리곤 목록(캐시 적용). 실패 시 빈 리스트."""
    now = time.time()
    cached = _polygon_cache.get(api_key)
    if cached and cached[1] > now:
        return cached[0]

    try:
        resp = requests.get(f'{API_BASE}/polygons',
                            params={'appid': api_key}, timeout=_TIMEOUT)
        if resp.status_code != 200:
            if logger:
                logger.warning('[Agromonitoring] polygons %s: %s',
                               resp.status_code, resp.text[:200])
            return []
        polygons = resp.json()
    except Exception as exc:                                    # noqa: BLE001
        if logger:
            logger.warning('[Agromonitoring] polygons request failed: %s', exc)
        return []

    if not isinstance(polygons, list):
        return []
    _polygon_cache[api_key] = (polygons, now + _POLYGON_CACHE_TTL)
    return polygons


def resolve_polygon_id(api_key, lat, lng, explicit_id='', logger=None):
    """조회에 쓸 폴리곤 id. 명시값이 있으면 그대로 쓴다."""
    if explicit_id:
        return explicit_id

    polygons = list_polygons(api_key, logger=logger)
    if not polygons:
        return None

    for polygon in polygons:
        if _polygon_contains(polygon, lat, lng):
            return polygon.get('id')

    # 클릭 지점이 어느 필지에도 안 들어가면 중심이 가장 가까운 것을 쓴다 —
    # 지도에서 필지 옆을 눌렀을 때 아무 값도 안 나오는 것보다 낫다.
    best, best_dist = None, None
    for polygon in polygons:
        center = polygon.get('center') or []
        if len(center) < 2:
            continue
        try:
            dist = math.hypot(float(center[0]) - lng, float(center[1]) - lat)
        except (TypeError, ValueError):
            continue
        if best_dist is None or dist < best_dist:
            best, best_dist = polygon.get('id'), dist
    return best


def fetch_soil(api_key, polygon_id, logger=None):
    """{moisture, t0, t10, dt} — 지온은 °C 로 변환해 돌려준다."""
    try:
        resp = requests.get(f'{API_BASE}/soil',
                            params={'polyid': polygon_id, 'appid': api_key},
                            timeout=_TIMEOUT)
        if resp.status_code != 200:
            if logger:
                logger.warning('[Agromonitoring] soil %s: %s',
                               resp.status_code, resp.text[:200])
            return {}
        payload = resp.json() or {}
    except Exception as exc:                                    # noqa: BLE001
        if logger:
            logger.warning('[Agromonitoring] soil request failed: %s', exc)
        return {}

    result = {}
    if payload.get('moisture') is not None:
        try:
            result['moisture'] = round(float(payload['moisture']), 3)
        except (TypeError, ValueError):
            pass
    for field in ('t0', 't10'):
        celsius = _kelvin_to_c(payload.get(field))
        if celsius is not None:
            result[field] = celsius
    if payload.get('dt'):
        result['dt'] = payload['dt']
    return result


def fetch_ndvi(api_key, polygon_id, window_days=30, logger=None):
    """가장 최근 통과의 NDVI 통계 {ndvi, ndvi_min, ndvi_max, dt}."""
    try:
        window_days = int(window_days)
    except (TypeError, ValueError):
        window_days = 30

    end = int(time.time())
    start = end - max(window_days, 1) * 86400

    params = {
        'appid': api_key,
        'start': start,
        'end': end,
        # 문서가 페이지마다 다르다 — 토양 쪽은 `polyid`, NDVI 이력 쪽은
        # `polygon_id` 로 적혀 있다. 둘 다 보낸다(모르는 파라미터는 무시된다).
        'polyid': polygon_id,
        'polygon_id': polygon_id,
    }

    try:
        resp = requests.get(f'{API_BASE}/ndvi/history', params=params,
                            timeout=_TIMEOUT)
        if resp.status_code != 200:
            if logger:
                logger.warning('[Agromonitoring] ndvi %s: %s',
                               resp.status_code, resp.text[:200])
            return {}
        entries = resp.json()
    except Exception as exc:                                    # noqa: BLE001
        if logger:
            logger.warning('[Agromonitoring] ndvi request failed: %s', exc)
        return {}

    if not isinstance(entries, list) or not entries:
        return {}

    latest = max(entries, key=lambda e: e.get('dt') or 0)
    data = latest.get('data') or {}
    if data.get('mean') is None:
        return {}

    result = {'ndvi': round(float(data['mean']), 3), 'dt': latest.get('dt')}
    for src, dst in (('min', 'ndvi_min'), ('max', 'ndvi_max')):
        if data.get(src) is not None:
            try:
                result[dst] = round(float(data[src]), 3)
            except (TypeError, ValueError):
                pass
    return result


class InputModule(AbstractGisInput):
    """Agromonitoring 필지 값 레이어 — 타일 없이 범례 숫자만 그린다.

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
        # 토양값은 하루 몇 번, NDVI 는 위성 통과마다 바뀐다. 30분이면 넉넉하고
        # 무료 등급의 호출 한도(비공개)를 아낀다.
        self.refresh_interval = 1800

        if not testing:
            self.api_key = self.get_custom_option('api_key') or ''

    def get_url(self):
        return ''

    def _active_channel_ids(self):
        active = self.get_custom_option('active_channels')
        if not active:
            active = [0, 1, 2]
        elif not isinstance(active, list):
            active = [active]
        ids = []
        for channel in active:
            try:
                ids.append(int(channel))
            except (TypeError, ValueError):
                pass
        return ids

    def get_legend(self):
        channel_ids = self._active_channel_ids()
        if not channel_ids:
            return None

        input_id = getattr(self, 'unique_id', '')
        proxy_url = (f'/api/geo/proxy/agromonitoring/{input_id}'
                     '?lat={lat}&lon={lon}')

        items_html = ''
        for channel_id in channel_ids:
            if channel_id not in CHANNELS:
                continue
            info = CHANNELS[channel_id]
            # 채널 이름은 이미 lazy_gettext 다 — f-string 이 현재 로케일로 편다.
            name = info['name']
            key = info['options']['key']
            unit = info['options']['unit']
            items_html += (
                '<div class="aot-legend-item-wrapper">'
                '<div class="aot-legend-wrapper">'
                '<div class="aot-legend-content">'
                f'<div class="aot-legend-title">{name}</div>'
                '</div>'
                f'<div class="aot-legend-value-box" data-api-url="{proxy_url}"'
                f' data-api-param="{key}" data-unit="{unit}">'
                '<div class="aot-legend-value-text">--</div>'
                f'<div class="aot-legend-value-unit">{unit}</div>'
                '</div>'
                '</div>'
                '</div>'
            )

        return {'type': 'html', 'content': items_html} if items_html else None

    def get_available_channels(self):
        return [{'id': info['options']['key'],
                 'name': str(info['name']),
                 'unit': info['options']['unit']}
                for info in CHANNELS.values()]

    def get_data_at_location(self, lat, lng, **kwargs):
        """이 좌표를 담은 필지의 토양값·NDVI. 폴리곤을 못 찾으면 None."""
        self.api_key = self.get_custom_option('api_key') or ''
        if not self.api_key:
            self.logger.warning('[Agromonitoring] API Key missing for Input %s',
                                getattr(self, 'unique_id', '?'))
            return None

        polygon_id = resolve_polygon_id(
            self.api_key, float(lat), float(lng),
            explicit_id=(self.get_custom_option('polygon_id') or '').strip(),
            logger=self.logger)
        if not polygon_id:
            self.logger.warning(
                '[Agromonitoring] no polygon registered for %s,%s', lat, lng)
            return None

        result = {'polygon_id': polygon_id}
        result.update(fetch_soil(self.api_key, polygon_id, logger=self.logger))
        result.update(fetch_ndvi(
            self.api_key, polygon_id,
            window_days=self.get_custom_option('ndvi_window_days') or 30,
            logger=self.logger))
        # 값이 하나도 없으면(전부 실패) 빈 껍데기를 돌려주지 않는다.
        return result if len(result) > 1 else None

    def get_ai_reading(self, lat, lng):
        """AI용: 필지의 토양 수분·지온·NDVI."""
        labels = {
            'ndvi':     ('NDVI (mean)', 'index'),
            'ndvi_min': ('NDVI (min)', 'index'),
            'ndvi_max': ('NDVI (max)', 'index'),
            'moisture': ('Soil Moisture', 'm³/m³'),
            't0':       ('Soil Temperature (surface)', '°C'),
            't10':      ('Soil Temperature (10cm)', '°C'),
        }
        try:
            data = self.get_data_at_location(lat, lng)
            if not data:
                return None
            readings = []
            for key, (label, unit) in labels.items():
                if data.get(key) is None:
                    continue
                readings.append({'label': label, 'value': data[key], 'unit': unit})
            return readings or None
        except Exception:
            return None
