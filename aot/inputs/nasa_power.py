# coding=utf-8
"""NASA POWER — 좌표만으로 받는 일 단위 농업기상. **API 키가 필요 없다.**

## 왜 만들었나

관개량을 근거 있게 정하려면 **기준증발산 ET0**(FAO-56)가 필요한데, 지금까지
AoT 의 어떤 입력도 그 값을 주지 않았다. Open-Meteo 는 일사(W/m²)를 주지만
ET0 는 없고, 기상청 계열은 관측값이지 증발산 산식의 입력 한 벌이 아니다.

POWER 는 1981년부터 이어지는 NASA 공식 자료이고, ET0 산식이 요구하는 다섯
가지(일 최고·최저기온, 평균습도, 2m 풍속, 전천일사)를 한 번에 준다. 그래서
여기서 **ET0 를 직접 계산한다** — POWER 에 ET0 파라미터는 없다(2026-09 실측:
AG 커뮤니티 일 단위 152개 파라미터 중 증발산 계열은 `EVLAND`(mm/day, 실제
증발)와 `EVPTRNS`(MJ/m²/day, 증발산 에너지속)뿐이다).

## ⚠ 이 값은 "지금" 이 아니다 — 1~2주 전이다

POWER 는 준실시간이라고 하지만 실측(2026-09-07 기준)으로 일 자료는
**2026-08-25 까지만** 있었고 그 이후는 전부 결측이었다. 시간 자료는 더
늦다(2026-08-30 까지). 즉 이 입력은 **오늘의 제어 판단용이 아니라**
그 필지의 증발산·일사 수준을 며칠~2주 지연으로 따라가는 기준선이다.
관개 스케줄의 계절 보정, 현장 센서 없는 구획의 대략치, 지난 물 사용량의
사후 검증에 쓴다. 실시간이 필요하면 Open-Meteo 나 기상청 입력을 쓸 것.

그래서 폴링 주기를 짧게 잡을 이유가 없다. 하루 한 번(86400초)이면 충분하고,
기본 주기가 짧게 남아 있어도 값은 며칠에 한 번만 바뀐다.

## 결측 처리 — -999

POWER 는 미보고값을 `-999.0` 으로 채운다(응답 헤더의 `fill_value`). 그대로
받으면 기온 -999°C 가 실측값으로 들어간다 — 기상청 자료에서 이미 같은 문제를
겪었다(`kma_weather_500.py`, `gis_kma.py`). `_valid()` 가 -900 이하를 전부
결측으로 버리고, `_pick_latest_day()` 는 **필요한 값이 다 있는 가장 최근
날짜**를 고른다.
"""
import copy
import math
from datetime import datetime, timedelta, timezone

import requests
from flask_babel import lazy_gettext

from aot.inputs.base_input import AbstractInput

# Measurements
measurements_dict = {
    0: {
        'measurement': 'evapotranspiration',
        'unit': 'mm',
        'name': 'ET0 (Reference)'
    },
    1: {
        'measurement': 'light',
        'unit': 'W_m2',
        'name': 'Solar (daily mean)'
    },
    2: {
        'measurement': 'temperature',
        'unit': 'C'
    },
    3: {
        'measurement': 'humidity',
        'unit': 'percent'
    },
    4: {
        'measurement': 'speed',
        'unit': 'm_s',
        'name': 'Wind (2m)'
    },
    5: {
        'measurement': 'rain',
        'unit': 'mm'
    },
    6: {
        'measurement': 'evapotranspiration',
        'unit': 'mm',
        'name': 'Actual ET (EVLAND)'
    },
}

# 채널 0(ET0)은 POWER 파라미터가 아니라 계산값이므로 여기 없다.
_PARAM_BY_CHANNEL = {
    1: 'ALLSKY_SFC_SW_DWN',
    2: 'T2M',
    3: 'RH2M',
    4: 'WS2M',
    5: 'PRECTOTCORR',
    6: 'EVLAND',
}

# ET0 계산에 필요한 파라미터 한 벌. 채널 0 이 켜져 있으면 이것들을 함께 받는다.
_ET0_PARAMS = ('T2M', 'T2M_MAX', 'T2M_MIN', 'RH2M', 'WS2M', 'ALLSKY_SFC_SW_DWN')

_POWER_URL = 'https://power.larc.nasa.gov/api/temporal/daily/point'
_TIMEOUT = 30

# POWER 의 결측 표기. 헤더의 `fill_value` 가 -999.0 이다.
_MISSING_SENTINEL_MAX = -900.0

# MJ/m²/day → W/m² (24시간 평균). 1 W/m² × 86400초 = 0.0864 MJ/m².
_MJ_PER_DAY_TO_W_M2 = 1.0 / 0.0864


def _valid(value):
    """결측(-999)과 비수치를 None 으로 바꾼다.

    NaN 도 여기서 막는다 — `float('nan')` 은 예외 없이 통과하고 `nan <= -900`
    은 False 라, 센티널 검사만으로는 그대로 새어 들어간다. -999 보다 나쁘다:
    평균·합계에 섞이면 그 계산 전체가 조용히 NaN 이 된다.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    if v <= _MISSING_SENTINEL_MAX:
        return None
    return v


def _saturation_vapor_pressure(t_c):
    """포화수증기압 e°(T) [kPa] — FAO-56 식 (11)."""
    return 0.6108 * math.exp(17.27 * t_c / (t_c + 237.3))


def extraterrestrial_radiation(lat_deg, day_of_year):
    """대기외 일사 Ra [MJ/m²/day] — FAO-56 식 (21)."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * day_of_year / 365.0)
    decl = 0.409 * math.sin(2 * math.pi * day_of_year / 365.0 - 1.39)
    # 극지방에서는 -tan φ tan δ 가 [-1,1] 을 벗어난다(백야·극야). 잘라 준다.
    x = max(-1.0, min(1.0, -math.tan(phi) * math.tan(decl)))
    omega_s = math.acos(x)
    return ((24 * 60 / math.pi) * 0.0820 * dr *
            (omega_s * math.sin(phi) * math.sin(decl) +
             math.cos(phi) * math.cos(decl) * math.sin(omega_s)))


def reference_et0(t_mean, t_max, t_min, rh_mean, wind_2m, solar_mj,
                  lat_deg, elevation_m, day_of_year):
    """FAO-56 Penman-Monteith 기준증발산 ET0 [mm/day].

    POWER 의 `WS2M` 은 이미 2m 풍속이라 10m→2m 보정을 하지 않는다.
    지표열속 G 는 일 단위에서 0 으로 둔다(FAO-56 식 42).
    """
    delta = (4098 * _saturation_vapor_pressure(t_mean) /
             ((t_mean + 237.3) ** 2))

    pressure = 101.3 * (((293 - 0.0065 * elevation_m) / 293) ** 5.26)
    gamma = 0.000665 * pressure

    es = (_saturation_vapor_pressure(t_max) + _saturation_vapor_pressure(t_min)) / 2.0
    ea = es * max(min(rh_mean, 100.0), 0.0) / 100.0

    # 순단파복사: 기준작물 알베도 0.23
    rns = (1 - 0.23) * solar_mj

    ra = extraterrestrial_radiation(lat_deg, day_of_year)
    rso = (0.75 + 2e-5 * elevation_m) * ra
    # 흐린 날 보정항 Rs/Rso 는 1을 넘지 않게, 그리고 Rso 가 0 인 극야에는
    # 상대일사를 알 수 없으므로 맑음(1.0)으로 둔다.
    rel_sw = min(solar_mj / rso, 1.0) if rso > 0 else 1.0
    rnl = (4.903e-9 *
           (((t_max + 273.16) ** 4 + (t_min + 273.16) ** 4) / 2.0) *
           (0.34 - 0.14 * math.sqrt(max(ea, 0.0))) *
           (1.35 * rel_sw - 0.35))

    rn = rns - rnl

    numerator = (0.408 * delta * rn +
                 gamma * (900 / (t_mean + 273)) * wind_2m * (es - ea))
    denominator = delta + gamma * (1 + 0.34 * wind_2m)
    return numerator / denominator


# Input information
INPUT_INFORMATION = {
    'input_name_unique': 'NASA_POWER_DAILY',
    'input_manufacturer': 'NASA',
    'input_name': 'NASA POWER (Coords, Daily incl. ET0)',
    'input_name_short': 'NASA POWER',
    'measurements_name': 'ET0/Solar/Temperature/Humidity/Wind/Rain',
    'measurements_dict': measurements_dict,
    'url_additional': 'https://power.larc.nasa.gov/',
    'measurements_rescale': False,

    'message': 'No API key needed — enter Latitude/Longitude only. Reports '
               'FAO-56 reference evapotranspiration (ET0) computed from '
               "NASA's daily agroclimatology, which no other AoT input "
               'provides. Note the data lags real time by roughly one to two '
               'weeks, so treat it as a seasonal baseline for irrigation '
               'planning rather than a live reading; poll once a day.',

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
            'id': 'window_days',
            'type': 'integer',
            'default_value': 20,
            'required': True,
            'name': lazy_gettext('Search Window (days)'),
            'phrase': 'How far back to look for the most recent complete day. '
                      'NASA POWER lags real time by about 7-13 days, so a '
                      'window shorter than two weeks can come back empty.'
        },
    ]
}


class InputModule(AbstractInput):
    """NASA POWER 일 자료에서 가장 최근의 완전한 날짜를 읽고 ET0 를 계산한다.

    @phase active
    @stability stable
    @dependency AbstractInput
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.window_days = 20

        if not testing:
            self.setup_custom_options(
                INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        if self.latitude is None or self.longitude is None:
            self.logger.error('Latitude/Longitude required')

    def _wanted_parameters(self):
        """켜진 채널이 요구하는 POWER 파라미터 집합과 ET0 필요 여부."""
        params = set()
        want_et0 = self.is_enabled(0)
        if want_et0:
            params.update(_ET0_PARAMS)
        for channel, param in _PARAM_BY_CHANNEL.items():
            if self.is_enabled(channel):
                params.add(param)
        return params, want_et0

    @staticmethod
    def _pick_latest_day(parameter_block, required):
        """필요한 값이 모두 유효한 가장 최근 날짜의 (날짜, {param: value}).

        가장 최근 날짜가 결측이라고 포기하지 않는다 — POWER 는 끝쪽 며칠이
        통째로 -999 인 것이 정상이다(파일 상단 주석).
        """
        dates = set()
        for series in parameter_block.values():
            dates.update(series.keys())

        for date_str in sorted(dates, reverse=True):
            row = {}
            complete = True
            for param in required:
                value = _valid((parameter_block.get(param) or {}).get(date_str))
                if value is None:
                    complete = False
                    break
                row[param] = value
            if complete:
                return date_str, row
        return None, None

    def get_measurement(self):
        """POWER 에서 가장 최근의 완전한 하루를 읽어 채널을 채운다."""
        if self.latitude is None or self.longitude is None:
            self.logger.error('Latitude/Longitude required')
            return

        self.return_dict = copy.deepcopy(measurements_dict)

        wanted, want_et0 = self._wanted_parameters()
        if not wanted:
            self.logger.debug('활성 채널 없음')
            return

        try:
            window = int(self.window_days)
        except (TypeError, ValueError):
            window = 20
        window = max(window, 3)

        today = datetime.now(timezone.utc).date()
        params = {
            'parameters': ','.join(sorted(wanted)),
            'community': 'AG',
            'latitude': self.latitude,
            'longitude': self.longitude,
            'start': (today - timedelta(days=window)).strftime('%Y%m%d'),
            'end': today.strftime('%Y%m%d'),
            'format': 'JSON',
        }

        try:
            resp = requests.get(_POWER_URL, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:                                # noqa: BLE001
            self.logger.error('NASA POWER 조회 실패: %s', exc)
            return

        block = ((payload or {}).get('properties') or {}).get('parameter') or {}
        if not block:
            self.logger.error('응답에 parameter 블록이 없다')
            return

        date_str, row = self._pick_latest_day(block, wanted)
        if not row:
            self.logger.error(
                '최근 %s일 안에 완전한 날짜가 없다 — 창을 늘려 볼 것', window)
            return

        for channel, param in _PARAM_BY_CHANNEL.items():
            if not self.is_enabled(channel) or param not in row:
                continue
            value = row[param]
            if channel == 1:
                # POWER 는 MJ/m²/day, 시스템 채널은 W/m² 다.
                value = value * _MJ_PER_DAY_TO_W_M2
            self.value_set(channel, float(value))

        if want_et0:
            # 고도는 응답의 geometry 세 번째 좌표에 들어 있다(실측 확인).
            elevation = 0.0
            coords = ((payload.get('geometry') or {}).get('coordinates') or [])
            if len(coords) >= 3:
                elevation = _valid(coords[2]) or 0.0

            try:
                day_of_year = datetime.strptime(date_str, '%Y%m%d').timetuple().tm_yday
                et0 = reference_et0(
                    t_mean=row['T2M'],
                    t_max=row['T2M_MAX'],
                    t_min=row['T2M_MIN'],
                    rh_mean=row['RH2M'],
                    wind_2m=row['WS2M'],
                    solar_mj=row['ALLSKY_SFC_SW_DWN'],
                    lat_deg=float(self.latitude),
                    elevation_m=elevation,
                    day_of_year=day_of_year)
            except Exception as exc:                            # noqa: BLE001
                self.logger.error('ET0 계산 실패: %s', exc)
            else:
                if et0 is not None and et0 >= 0:
                    self.value_set(0, float(et0))

        self.logger.debug('NASA POWER %s 자료 사용(오늘: %s)',
                          date_str, today.strftime('%Y%m%d'))

        return self.return_dict
