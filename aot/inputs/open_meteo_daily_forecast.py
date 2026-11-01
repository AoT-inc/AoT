# coding=utf-8
"""Open-Meteo 일별 **예보** — "며칠 뒤" 를 채널로 (OPEN_METEO_DAILY_FORECAST).

`OPEN_METEO_HOURLY_FORECAST`(open_meteo_hourly_forecast.py) 는 +1/+3/+6 h 와 앞 N 시간 창만 낸다.
앞날 물 수지(노지 디지털트윈)가 필요한 것은 **앞 며칠의 하루 합**이라 이 입력이 따로 있다.
같은 API 를 한 번 불러 오늘(+0 d)부터 +7 d 까지의 일 합·일 최고/최저를 낸다.

## 채널 = 묶음 × 리드

채널 번호 = `묶음 * 8 + 리드(일)`. 묶음: 0 강수 일 합(mm), 1 ET0(mm, FAO-56), 2 최고기온(°C),
3 최저기온(°C), 4 강수확률 일 최대(%). **리드 0 은 값을 받은 날(구획 현지 시각)**, 리드 k 는 k 일 뒤.
값은 **수신 시각**에 저장한다(hourly 예보 입력과 같다 — 대상 날짜로 찍지 않는다. 갱신마다 덮어써
"언제 발표된 값인가" 가 사라지는 것을 피한다). 읽는 쪽은 `저장 시각의 현지 날짜 + 리드` 가 그 값의
대상 날짜라고 읽고, 같은 대상 날짜에 여러 값이 있으면 **가장 늦게 받은 값**을 쓴다.

리드는 응답의 날짜(`daily.time`, 현지)와 받은 시각의 현지 날짜(`utc_offset_seconds`)의 차로
정한다 — 응답 배열 순서를 믿지 않는다.

## 쓰지 않는 것

- 결측을 0 으로 채우지 않는다(키가 없으면 값을 쓰지 않는다).
- 앙상블(멤버)은 받지 않는다. 앙상블이 없으므로 읽는 쪽(트윈)이 비 배율 오차로 불확실성을 둔다.

## 요청 한도

429 는 `open_meteo_weather._RATE_LIMITED_UNTIL` **같은 dict** 를 공유한다(공인 IP 한도라 함께 멈추고 함께 풀린다).
"""
import copy
import math
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from flask_babel import lazy_gettext

from aot.inputs.base_input import AbstractInput
# 같은 dict·같은 함수를 쓴다(복사 금지) — 기존 파일은 수정하지 않는다.
from aot.inputs.open_meteo_weather import (
    _COMMERCIAL_URL, _FORECAST_URL, _RATE_LIMITED_UNTIL, _rate_limit_until,
)

LEADS = 8                                   # 리드 0 … 7 일

# (묶음 이름, 측정, 단위, 이름, Open-Meteo daily 변수, 일 통계)
_GROUPS = (
    ('rain', 'rain', 'mm', 'Rain (daily sum)', 'precipitation_sum', 'sum'),
    ('et0', 'evapotranspiration', 'mm', 'ET0 (daily)', 'et0_fao_evapotranspiration', 'sum'),
    ('t_max', 'temperature', 'C', 'Max Temperature', 'temperature_2m_max', 'max'),
    ('t_min', 'temperature', 'C', 'Min Temperature', 'temperature_2m_min', 'min'),
    ('pop', 'precipitation', 'percent', 'Rain Probability (daily max)',
     'precipitation_probability_max', 'max'),
)
GROUP_INDEX = {g[0]: i for i, g in enumerate(_GROUPS)}
# 묶음 → L0(`fc_daily`) 중립 변수 이름.
_L0_VARS = {'rain': 'RAIN', 'et0': 'ET0', 't_max': 'TMAX', 't_min': 'TMIN', 'pop': 'POP'}


def channel_of(group, lead):
    """묶음 이름·리드(일) → 채널 번호. 읽는 쪽(트윈 설정 예시)도 이 규칙을 쓴다."""
    return GROUP_INDEX[group] * LEADS + lead


def _build_measurements():
    """채널마다 `forecast_lead_d`(리드, 일)·`daily_stat`(sum·max·min)을 밝힌다 — 읽는 쪽(디지털트윈)이
    채널 번호를 손으로 적지 않고 이 메타로 리드 사다리를 만든다(`aot.twin.forecast.ladder_from_channels`)."""
    out = {}
    for gi, (_g, meas, unit, name, _var, stat) in enumerate(_GROUPS):
        for lead in range(LEADS):
            out[gi * LEADS + lead] = {
                'measurement': meas, 'unit': unit, 'name': '{} +{}d'.format(name, lead),
                'forecast_lead_d': lead, 'daily_stat': stat}
    return out


measurements_dict = _build_measurements()


# ── 순수 계산 — 네트워크·DB 없이 시험할 수 있게 입력 클래스 밖에 둔다 ──────────

def local_today(now, utc_offset_s):
    """받은 시각의 현지 날짜."""
    return (datetime.fromtimestamp(now, timezone.utc) + timedelta(seconds=utc_offset_s)).date()


def values_from_daily(daily, now, utc_offset_s, is_enabled=lambda ch: True):
    """응답 `daily` → {채널: 값}. 오늘 이전·+7 일 너머 날짜와 숫자가 아닌 값은 버린다."""
    out = {}
    if not isinstance(daily, dict):
        return out
    times = daily.get('time')
    if not isinstance(times, list):
        return out
    today = local_today(now, utc_offset_s)
    for idx, ds in enumerate(times):
        try:
            lead = (date.fromisoformat(str(ds)[:10]) - today).days
        except ValueError:
            continue
        if not 0 <= lead < LEADS:
            continue
        for gi, (_g, _m, _u, _n, var, _s) in enumerate(_GROUPS):
            series = daily.get(var)
            if not isinstance(series, list) or idx >= len(series):
                continue
            val = series[idx]
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                continue
            if isinstance(val, float) and not math.isfinite(val):
                continue
            ch = gi * LEADS + lead
            if is_enabled(ch):
                out[ch] = round(float(val), 3)
    return out


def needed_variables(is_enabled):
    """켜진 채널이 쓰는 Open-Meteo daily 변수 집합."""
    return {var for gi, g in enumerate(_GROUPS) for var in (g[4],)
            if any(is_enabled(gi * LEADS + k) for k in range(LEADS))}


_MODEL_CHOICES = ('best_match', 'kma_seamless', 'jma_seamless',
                  'ecmwf_ifs025', 'icon_seamless', 'gfs_seamless')
# (connect, read) — 연결 단계 장애를 20 초 기다리지 않는다.
_TIMEOUT = (5, 15)
_RETRY_WAIT_S = 1.5


def _now():
    return time.time()


# Input information
INPUT_INFORMATION = {
    'input_name_unique': 'OPEN_METEO_DAILY_FORECAST',
    'input_manufacturer': 'Open-Meteo',
    'input_name': 'Open-Meteo Daily Forecast (Coords, +0…+7 d)',
    'input_name_short': 'Open-Meteo Daily Forecast',
    # 예보 모델 값이다 — 현장 실측이 아니다(aot.utils.inputs.model_input_drivers).
    'data_origin': 'model',
    # 이 입력의 값은 **미래 날짜에 대한 것**이다(오용 가드용 표식).
    'data_time': 'forecast',
    'measurements_name': 'Daily rain/ET0/Tmax/Tmin/rain probability, today to +7 d',
    'measurements_dict': measurements_dict,
    'url_additional': 'https://open-meteo.com',
    'measurements_rescale': False,
    'period': 10800,

    'message': 'Daily FORECAST (not a measurement): per-day rain sum, ET0, max/min '
               'temperature and rain probability for today … +7 days, from one API call '
               'per cycle. Channel = group*8 + lead(days). Values are stored at the time '
               'they were received; a value on channel "+k d" is for the local date of '
               'its timestamp plus k days. Do not bind these channels as an outdoor sensor. '
               'No API key needed — enter Latitude/Longitude only. Free use is '
               'non-commercial (CC-BY 4.0); a paid key switches to the commercial endpoint.',

    'options_enabled': [
        'measurements_select',
        'period',
        'pre_output',
        'coordinates'
    ],
    'options_disabled': ['interface'],
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
        {
            'id': 'model',
            'type': 'select',
            'default_value': 'best_match',
            'required': True,
            'options_select': [(m, m) for m in _MODEL_CHOICES],
            'name': lazy_gettext('Forecast Model'),
            'phrase': 'best_match picks the best model per location. Regional models '
                      '(kma_seamless, jma_seamless) may not reach +7 days or provide '
                      'rain probability.'
        },
        {
            'id': 'store_issue',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext('Store Forecast Issues'),
            'phrase': 'Keep every received daily forecast with its lead time (data layer L0) '
                      'so past forecasts can be compared with field measurements. '
                      'The channels are unaffected.'
        },
    ]
}


class InputModule(AbstractInput):
    """Open-Meteo 일별 예보 → 묶음×리드 채널.

    @phase active
    @stability stable
    @dependency AbstractInput
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.api_key = None
        self.model = 'best_match'
        # 시험(testing=True)은 사용자 옵션을 읽지 않으므로 Influx 를 건드리지 않게 꺼 둔다.
        self.store_issue = False

        if not testing:
            self.setup_custom_options(
                INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        if self.latitude is None or self.longitude is None:
            self.logger.error('Latitude/Longitude required')

    def _base_url(self):
        return _COMMERCIAL_URL if self.api_key else _FORECAST_URL

    def _get(self, url, params):
        """requests.get — 연결 오류·연결 시간 초과·5xx 에 한해 1 회만 다시. 429 는 그대로 돌려준다."""
        last_exc = None
        for attempt in (0, 1):
            try:
                resp = requests.get(url, params=params, timeout=_TIMEOUT)
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.ConnectTimeout) as exc:
                last_exc = exc
            else:
                if resp.status_code >= 500 and attempt == 0:
                    last_exc = None
                else:
                    return resp
            if attempt == 0:
                time.sleep(_RETRY_WAIT_S)
        if last_exc is not None:
            raise last_exc
        return resp

    def _store_issue(self, values, now, offset, payload):
        """받은 발표본을 L0(`fc_daily`)에 남긴다. 실패해도 채널 값을 막지 않는다."""
        try:
            from aot.utils import fc_store
            by_group = {g[0]: _L0_VARS[g[0]] for g in _GROUPS}
            vals = {}
            for ch, v in values.items():
                gi, lead = divmod(ch, LEADS)
                vals[(by_group[_GROUPS[gi][0]], lead)] = v
            fc_store.store_daily(
                getattr(self, 'unique_id', None), now, offset, vals,
                lat=payload.get('latitude'), lon=payload.get('longitude'),
                elev=payload.get('elevation'), model=self.model)
        except Exception as exc:                                # noqa: BLE001
            self.logger.error('예보 발표본(L0) 저장 실패: %s', exc)

    def get_measurement(self):
        """예보를 한 번 받아 일별 채널을 채운다."""
        if self.latitude is None or self.longitude is None:
            self.logger.error('Latitude/Longitude required')
            return

        self.return_dict = copy.deepcopy(measurements_dict)

        need = needed_variables(self.is_enabled)
        if not need:
            self.logger.debug('활성 채널 없음')
            return

        params = {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'daily': ','.join(sorted(need)),
            # 날짜를 좌표의 현지 날짜로 받는다 — 하루 합의 경계가 현장의 하루와 맞는다.
            'timezone': 'auto',
            'forecast_days': LEADS,
            'temperature_unit': 'celsius',
            'precipitation_unit': 'mm',
        }
        if self.model and self.model != 'best_match':
            params['models'] = self.model
        if self.api_key:
            params['apikey'] = self.api_key

        host = urlparse(self._base_url()).netloc
        now = _now()
        if _RATE_LIMITED_UNTIL.get(host, 0) > now:
            self.logger.debug('Open-Meteo 요청 한도 대기 중(%s 까지)',
                              datetime.fromtimestamp(_RATE_LIMITED_UNTIL[host],
                                                     timezone.utc).isoformat())
            return
        try:
            resp = self._get(self._base_url(), params)
            if resp.status_code == 429:
                until, why = _rate_limit_until(resp, now)
                _RATE_LIMITED_UNTIL[host] = until
                self.logger.error(
                    'Open-Meteo 요청 한도 초과(%s) — %s 까지 이 호스트의 모든 '
                    'Open-Meteo 입력이 묻지 않는다.', why or '429',
                    datetime.fromtimestamp(until, timezone.utc).isoformat())
                return
            resp.raise_for_status()
            payload = resp.json() or {}
        except Exception as exc:                                # noqa: BLE001
            self.logger.error('Open-Meteo 일별 예보 조회 실패: %s', exc)
            return
        if not isinstance(payload, dict):
            self.logger.error('Open-Meteo 예보 응답 모양이 다르다: %s',
                              type(payload).__name__)
            return

        offset = payload.get('utc_offset_seconds')
        if isinstance(offset, bool) or not isinstance(offset, (int, float)):
            # 오프셋을 모르면 날짜를 현지 날짜에 맞출 수 없다 — 틀린 리드로 쓰느니 쓰지 않는다.
            self.logger.error('응답에 utc_offset_seconds 가 없다 — 값을 쓰지 않는다')
            return
        values = values_from_daily(payload.get('daily'), now, int(offset), self.is_enabled)
        if not values:
            self.logger.error('일별 예보 값이 없다')
            return
        for ch, value in values.items():
            self.value_set(ch, value)
        if getattr(self, 'store_issue', False):
            self._store_issue(values, now, int(offset), payload)
        return self.return_dict
