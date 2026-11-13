# coding=utf-8
"""Open-Meteo — 좌표만으로 받는 기상값. **API 키가 필요 없다.**

## 왜 만들었나

일사(W/m²)를 주는 무료 소스가 필요했다. env_coordinator 의 일소 잠금은 광량을
근거로 습윤형 분무를 막는데, 광센서가 없는 설치에서는 태양고도로 어림한
맑은날 값(`utils.solar.clear_sky_irradiance`)밖에 없다. 그 어림은 **구름을
무시**하므로 흐린 날에도 정오 900 W/m² 를 말한다.

Open-Meteo 의 `shortwave_radiation` 은 기상 모델값이라 구름이 반영된다.
현장 센서보다는 못하지만 맑은날 어림보다는 낫다.

⚠ **이것은 예보/모델값이지 측정값이 아니다.** 그런데 코디네이터는
`external['solar']` 를 측정값으로 대우해 어림값보다 **우선**한다
(`safety_gates._eval_nursery_lock`). 즉 이 입력을 붙이면 판정 근거가 바뀐다 —
정확도는 오르지만, 틀릴 때 어림값처럼 "과대평가(안전)" 쪽으로만 틀린다는
보장이 없다. 실물 온실에 쓸 때 알고 있어야 한다.

## 단위 — 전천일사이지 PAR 이 아니다

`shortwave_radiation` 은 **전천일사**(약 300~2800 nm)다. 시스템 변환표의
`W_m2 → umol_m2_s` 계수 **4.57 은 PAR 대역 W/m² 기준**이라, 이 값에 그대로
곱하면 PPFD 가 약 2.2 배로 나온다(전천일사 중 PAR 은 에너지 기준 45~50%).
DLI 누적(`cumulative_tracker`)이 그 경로를 쓰므로, 이 입력을 DLI 산정에
쓰려면 변환 계수를 먼저 정리해야 한다. 일소 잠금은 W/m² 를 그대로 쓰므로
영향이 없다.

## 관측 시각

`hourly` 배열에서 **현재 시각의 행**을 고르고(기온·습도·풍속 등 순간값은 지나온 마지막
정시 행, 강수·일사는 지금이 속한 칸이 끝나는 정시 행 — Open-Meteo 가 이 둘을 직전
1시간 합·평균으로 주기 때문이다), 저장 시각은 시스템 기본(쓰기
시각)을 쓴다. 관측 시각을 쓰려면 `measurements_use_same_timestamp: False` 가
필요한데(`base_input.value_set` 의 timestamp 는 그것 없이는 버려진다), 여기서
값은 "지금 시각이 속한 한 시간의 모델값" 이라 매 폴링이 같은 정시를 가리킨다
— 그 시각으로 찍으면 한 시간에 한 점만 남아 신선도 판정이 주기와 어긋난다.

무료 한도는 비상업 기준 하루 1만 호출이다. 기본 주기 600초면 하루 144회다.
"""
import copy
from datetime import datetime, timezone

import requests
from flask_babel import lazy_gettext

from aot.inputs.base_input import AbstractInput
from aot.utils.timekit import utc_now

# Measurements
measurements_dict = {
    0: {
        'measurement': 'temperature',
        'unit': 'C'
    },
    1: {
        'measurement': 'humidity',
        'unit': 'percent'
    },
    2: {
        'measurement': 'light',
        'unit': 'W_m2',
        'name': 'Solar'
    },
    3: {
        'measurement': 'speed',
        'unit': 'm_s',
        'name': 'Wind'
    },
    4: {
        'measurement': 'direction',
        'unit': 'bearing',
        'name': 'Wind'
    },
    5: {
        'measurement': 'rain',
        'unit': 'mm'
    },
    6: {
        'measurement': 'vapor_pressure_deficit',
        'unit': 'kPa'
    },
    7: {
        'measurement': 'dewpoint',
        'unit': 'C'
    },
}

# 채널 → Open-Meteo hourly 변수. 이름을 바꾸면 그 채널만 조용히 비므로
# 한 곳에 모아 둔다.
_HOURLY_VARS = {
    0: 'temperature_2m',
    1: 'relative_humidity_2m',
    2: 'shortwave_radiation',
    3: 'wind_speed_10m',
    4: 'wind_direction_10m',
    5: 'precipitation',
    6: 'vapour_pressure_deficit',
    7: 'dew_point_2m',
}

# 칸 값(직전 1시간 합·평균) 변수 — 행 시각이 칸의 끝이라 "지금이 속한 칸" 은 다음 정시 행이다.
_CELL_VARS = frozenset(('precipitation', 'shortwave_radiation'))

_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
_COMMERCIAL_URL = 'https://customer-api.open-meteo.com/v1/forecast'
_TIMEOUT = 20

# ── 요청 한도(429) — 같은 호스트의 입력 전부가 함께 멈춘다 ─────────────────────
# Open-Meteo 무료 엔드포인트의 한도는 **공인 IP 단위**다(분·시간·일). 한도를 넘으면
# 429 를 주는데, 예전에는 입력마다 제 주기대로 계속 다시 물어 막힌 시간 내내 요청을
# 보탰다(2026-10-10 실측: 주기 15초 입력 하나가 하루 약 5,760회 — 매일 아침 일
# 한도가 차서 UTC 자정까지 세 입력이 함께 멈췄다). 그래서 429 를 받으면 응답이
# 말하는 한도(daily/hourly/minutely)가 풀릴 때까지 **이 프로세스의 같은 호스트
# 입력 전부**가 묻지 않는다. 막힌 동안은 값이 없는 것이지 장애가 아니다.
_RATE_LIMITED_UNTIL = {}      # host → epoch 초
_RATE_LIMIT_FALLBACK_S = 600


def _rate_limit_until(resp, now):
    """429 응답 → 다시 물어도 되는 시각(epoch 초)과 사유 문장."""
    reason = ''
    try:
        reason = str((resp.json() or {}).get('reason') or '')
    except ValueError:
        pass
    low = reason.lower()
    if 'daily' in low:
        nxt = (datetime.fromtimestamp(now, timezone.utc)
               .replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
               + 86400)
        return nxt, reason
    if 'hourly' in low:
        return (now // 3600 + 1) * 3600, reason
    if 'minutely' in low:
        return (now // 60 + 1) * 60, reason
    try:
        return now + max(1.0, float(resp.headers.get('Retry-After'))), reason
    except (TypeError, ValueError):
        return now + _RATE_LIMIT_FALLBACK_S, reason

# Input information
INPUT_INFORMATION = {
    'input_name_unique': 'OPEN_METEO_FORECAST',
    'input_manufacturer': 'Open-Meteo',
    'input_name': 'Open-Meteo (Coords, Hourly incl. Solar)',
    'input_name_short': 'Open-Meteo',
    # 예보 모델 값이다 — 현장 실측이 아니다. 도구가 이 표식으로 가른다
    # (aot.utils.inputs.model_input_drivers).
    'data_origin': 'model',
    'measurements_name': 'Temperature/Humidity/Solar/Wind/Rain/VPD',
    'measurements_dict': measurements_dict,
    'url_additional': 'https://open-meteo.com',
    'measurements_rescale': False,

    'message': 'No API key needed — enter Latitude/Longitude only. '
               'Unlike most free weather sources this one reports solar '
               'radiation (W/m²), which the environment coordinator uses to '
               'lock out misting in strong sun. Note this is a forecast model '
               'value, not a measurement at your site. '
               'Free use is non-commercial (CC-BY 4.0); a paid key switches to '
               'the commercial endpoint.',

    'options_enabled': [
        'measurements_select',
        'period',
        'pre_output',
        'coordinates'
    ],
    'options_disabled': ['interface'],

    # `requests` 는 AoT 기본 의존성이라 선언하지 않는다 — requests 를 쓰는
    # 기존 기상 모듈 셋(openweathermap·ecowitt·kma) 도 선언이 없다. 버전을
    # 핀으로 적으면 설치본과 다를 때 **의존성 미충족으로 입력 추가가 막힌다**
    # (2.31.0 로 적었다가 설치본 2.33.0 에 걸렸다).

    'interfaces': ['AoT'],

    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('API Key (optional)'),
            'phrase': 'Leave empty for free non-commercial use. A key from '
                      'open-meteo.com switches to the commercial endpoint.'
        },
    ]
}


class InputModule(AbstractInput):
    """Open-Meteo 시간별 예보에서 현재 시각 행을 읽는다.

    @phase active
    @stability stable
    @dependency AbstractInput
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.api_key = None

        if not testing:
            self.setup_custom_options(
                INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        if self.latitude is None or self.longitude is None:
            self.logger.error('Latitude/Longitude required')

    def _base_url(self):
        return _COMMERCIAL_URL if self.api_key else _FORECAST_URL

    @staticmethod
    def _pick_cell_row(times, now_utc):
        """현재 시각이 속한 **칸**의 행 인덱스 — 칸이 끝나는 정시 행. 못 찾으면 None.

        강수·일사는 칸 값이다. Open-Meteo 는 그 정시까지 직전 1시간 합·평균으로 주므로
        행 시각이 칸의 끝이다 — 13:26 이 속한 13~14시 칸은 14:00 행이고, 정각이면 그
        정시 행(방금 끝난 칸)이다. `_pick_row` 의 "지나온 정시" 행을 쓰면 한 시간 전에
        내린 비를 지금 비로 읽는다. 시간별 예보 입력(open_meteo_hourly_forecast)의 칸
        값 리드 정의와 같다.
        """
        for i, t in enumerate(times or []):
            try:
                ts = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if ts >= now_utc:
                return i
        return None

    @staticmethod
    def _pick_row(times, now_utc):
        """현재 시각이 속한 한 시간의 인덱스. 못 찾으면 None.

        Open-Meteo 의 `time` 은 요청한 시간대의 지역시각 문자열이다
        (`timezone=UTC` 로 요청하므로 여기서는 UTC). 마지막으로 지나온 정시를
        고른다 — 미래 행을 고르면 아직 오지 않은 날씨로 제어하게 된다.
        """
        chosen = None
        for i, t in enumerate(times or []):
            try:
                ts = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
            if ts <= now_utc:
                chosen = i
            else:
                break
        return chosen

    def get_measurement(self):
        """Open-Meteo 에서 현재 시각의 기상값을 가져온다."""
        if self.latitude is None or self.longitude is None:
            self.logger.error('Latitude/Longitude required')
            return

        self.return_dict = copy.deepcopy(measurements_dict)

        # 켜진 채널만 요청한다 — 안 쓰는 변수를 받아 올 이유가 없고,
        # 응답도 그만큼 작아진다.
        wanted = {ch: var for ch, var in _HOURLY_VARS.items() if self.is_enabled(ch)}
        if not wanted:
            self.logger.debug('활성 채널 없음')
            return

        params = {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'hourly': ','.join(sorted(set(wanted.values()))),
            'timezone': 'UTC',
            # 둘째 날까지 — UTC 23시대에는 칸이 끝나는 정시(다음 날 00:00)가 필요하다.
            'forecast_days': 2,
            'past_days': 1,          # 자정 직후에도 '지나온 정시' 가 있도록
            # ⚠ **단위를 명시한다.** Open-Meteo 의 기본 풍속 단위는 km/h 라,
            # 안 적으면 `m_s` 로 선언한 채널에 3.6 배 값이 조용히 들어간다
            # (실측으로 확인). 나머지는 기본이 맞지만(°C·%·mm·W/m²·kPa)
            # 기본값에 기대지 않고 함께 못박는다.
            'wind_speed_unit': 'ms',
            'temperature_unit': 'celsius',
            'precipitation_unit': 'mm',
        }
        if self.api_key:
            params['apikey'] = self.api_key

        import time as _time
        from urllib.parse import urlparse
        host = urlparse(self._base_url()).netloc
        now = _time.time()
        if _RATE_LIMITED_UNTIL.get(host, 0) > now:
            self.logger.debug('Open-Meteo 요청 한도 대기 중(%s 까지)',
                              datetime.fromtimestamp(_RATE_LIMITED_UNTIL[host],
                                                     timezone.utc).isoformat())
            return
        try:
            resp = requests.get(self._base_url(), params=params, timeout=_TIMEOUT)
            if resp.status_code == 429:
                until, why = _rate_limit_until(resp, now)
                _RATE_LIMITED_UNTIL[host] = until
                self.logger.error(
                    'Open-Meteo 요청 한도 초과(%s) — %s 까지 이 호스트의 모든 '
                    'Open-Meteo 입력이 묻지 않는다. 주기가 짧은 입력이 있으면 늘리거나 '
                    'API 키를 넣을 것.', why or '429',
                    datetime.fromtimestamp(until, timezone.utc).isoformat())
                return
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:                                # noqa: BLE001
            self.logger.error('Open-Meteo 조회 실패: %s', exc)
            return

        hourly = (payload or {}).get('hourly') or {}
        now_utc = utc_now()
        idx = self._pick_row(hourly.get('time'), now_utc)
        if idx is None:
            self.logger.error('현재 시각에 해당하는 행이 없다')
            return
        cell_idx = self._pick_cell_row(hourly.get('time'), now_utc)

        for ch, var in wanted.items():
            series = hourly.get(var)
            row = cell_idx if var in _CELL_VARS else idx
            if row is None:
                # 칸이 끝나는 행이 응답에 없다 — 한 칸 앞 값으로 대신하지 않는다.
                self.logger.debug('칸 값 행 없음: %s', var)
                continue
            if not series or row >= len(series):
                # 변수 하나가 없다고 나머지를 버리지 않는다 — Open-Meteo 는
                # 지점·모델에 따라 일부 변수를 안 주는 경우가 있다.
                self.logger.debug('변수 없음: %s', var)
                continue
            value = series[row]
            if value is None:
                continue
            self.value_set(ch, float(value))

        return self.return_dict
