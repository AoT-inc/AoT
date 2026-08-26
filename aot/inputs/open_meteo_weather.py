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

`hourly` 배열에서 **현재 시각의 행**을 고르고, 저장 시각은 시스템 기본(쓰기
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

_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
_COMMERCIAL_URL = 'https://customer-api.open-meteo.com/v1/forecast'
_TIMEOUT = 20

# Input information
INPUT_INFORMATION = {
    'input_name_unique': 'OPEN_METEO_FORECAST',
    'input_manufacturer': 'Open-Meteo',
    'input_name': 'Open-Meteo (Coords, Hourly incl. Solar)',
    'input_name_short': 'Open-Meteo',
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
            'forecast_days': 1,
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

        try:
            resp = requests.get(self._base_url(), params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:                                # noqa: BLE001
            self.logger.error('Open-Meteo 조회 실패: %s', exc)
            return

        hourly = (payload or {}).get('hourly') or {}
        idx = self._pick_row(hourly.get('time'), datetime.now(timezone.utc))
        if idx is None:
            self.logger.error('현재 시각에 해당하는 행이 없다')
            return

        for ch, var in wanted.items():
            series = hourly.get(var)
            if not series or idx >= len(series):
                # 변수 하나가 없다고 나머지를 버리지 않는다 — Open-Meteo 는
                # 지점·모델에 따라 일부 변수를 안 주는 경우가 있다.
                self.logger.debug('변수 없음: %s', var)
                continue
            value = series[idx]
            if value is None:
                continue
            self.value_set(ch, float(value))

        return self.return_dict
