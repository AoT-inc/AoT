# coding=utf-8
"""Open-Meteo 시간별 **예보** — "몇 시간 뒤" 를 입력으로 (OPEN_METEO_HOURLY_FORECAST).

`OPEN_METEO_FORECAST`(open_meteo_weather.py) 는 "지금 시각이 속한 한 칸" 만 낸다.
이 입력은 같은 API 를 한 번 불러 **앞으로의 값**을 두 갈래로 낸다.

1. Influx 채널 — +1h/+3h/+6h 포인트 채널과 앞으로 N 시간(`window_h`) 창 집계 채널.
   시설 예보 바인딩(`facility_sensors.read_forecast_sensors`)이 코드 변경 없이 읽는다.
   저장 시각은 **수신(쓰기) 시각**이다 — "+3h 기온" 채널은 수신 시각에 찍힌,
   3시간 뒤를 가리키는 값이다. 대상 시각(미래)으로 찍지 않는다(조회의 기본 stop 이
   now 라 미래 점은 그 시각이 오기 전까지 LAST 에 안 보이고, 갱신마다 덮어써
   "언제 발표된 값인가" 가 사라진다).
2. 시간열 파일 — `DATABASE_PATH/openmeteo/forecast_<input_uuid>.json`. 기상청
   `forecast.json` 과 키(TMP/REH/WSD/VEC/RN1/POP)를 맞춘 0~48h 시간열이라
   `forecast_rows_ahead`·`kma_curve`·`build_feedforward_signal`·`weather_hazards`
   가 고치지 않고 읽는다. 정적 경로(static/json)에는 두지 않는다 — 좌표가 담긴
   파일이 노출될 수 있고 기존 `forecast.json` 과 섞이면 안 된다.

## 리드 정의 (환경제어 세션 확정, E6) — 파일 메타 `lead_definition` 과 같은 내용

기준은 "지금" (`now`, epoch 초). Open-Meteo 의 hourly 행은 정시 라벨이다.

- **순간값(기온·습도·풍속)**: `now+L` 에서 앞뒤 정시 행을 **직선 보간**한다.
  정각이면 그 행 값 그대로. 이웃 행 하나라도 비면 값 없음.
- **칸 값(강수·일사·강수확률·운량)**: `now+L` 을 **포함하는(끝나는) 칸**, 즉
  `ceil(now+L)` 정시 행의 값. Open-Meteo `precipitation` 은 그 정시까지 **직전
  1시간 합**, `shortwave_radiation` 은 직전 1시간 **평균**이라 라벨 정시가 칸의
  끝이다. 정각이면 그 정시 행 자체(= 방금 끝난 칸).
- **창 집계 (0 ~ window_h)**: 순간값은 `now`·`now+W` 의 보간값과 그 사이 정시 행
  값(`now ≤ ts ≤ now+W`)에서 최고/최저/최대. 칸 값(시간당 강수, 강수확률)은
  창과 겹치는 칸 — `now < ts < now+W+3600` 인 정시 행 — 중 최대. 이미 끝난 칸
  (`ts ≤ now`)은 넣지 않는다. 시간당 강수 최대는 환경제어가 강수확률과 AND 로 쓴다.
- **값이 없으면 쓰지 않는다.** 결측을 0.0 으로 채우지 않는다(기상청 예보 입력은
  0.0 으로 채워 결측이 0 으로 기록된다 — 따라 하지 말 것).

모든 강수 채널은 "1시간 합 mm" 이라 `utils.inputs._RAIN_ACCUM_BY_DRIVER` 에
`{'mm': 3600}` 한 줄로 단위가 일관된다. 창 "합계" 채널은 두지 않는다(구간이 채널마다
달라 단위표가 깨진다).

## 일사·운량

파일(SOL·CLD)과 채널에는 싣지만 지금 제어는 쓰지 않는다(E7). 일사는 전천일사라
PAR 환산 계수(4.57)를 그대로 곱하면 안 된다(open_meteo_weather.py 참조).

## 요청 한도

429 는 `open_meteo_weather._RATE_LIMITED_UNTIL` **같은 dict** 를 공유한다 — 같은
공인 IP 한도라 실시간 입력과 예보 입력이 함께 멈추고 함께 풀린다.
"""
import copy
import json
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from flask_babel import lazy_gettext

from aot.inputs.base_input import AbstractInput
# 같은 dict·같은 함수를 쓴다(복사 금지) — 기존 파일은 수정하지 않는다.
from aot.inputs.open_meteo_weather import (
    _COMMERCIAL_URL, _FORECAST_URL, _RATE_LIMITED_UNTIL, _rate_limit_until,
)

_LEAD_HOURS = (1, 3, 6)

# 리드 포인트 채널 한 묶음(7개). (측정, 단위, 이름, Open-Meteo 변수, 방식)
#   방식 'instant' = 정시 라벨 순간값(보간), 'cell' = 라벨 정시에 끝나는 칸 값.
_LEAD_SPECS = (
    ('temperature', 'C', 'Temperature', 'temperature_2m', 'instant'),
    ('humidity', 'percent', 'Humidity', 'relative_humidity_2m', 'instant'),
    ('rain', 'mm', 'Rain (1h sum)', 'precipitation', 'cell'),
    ('precipitation', 'percent', 'Rain Probability', 'precipitation_probability', 'cell'),
    ('speed', 'm_s', 'Wind', 'wind_speed_10m', 'instant'),
    ('sky_condition', 'percent', 'Cloud Cover', 'cloud_cover', 'cell'),
    ('light', 'W_m2', 'Solar', 'shortwave_radiation', 'cell'),
)
_PER_LEAD = len(_LEAD_SPECS)

# 창 집계 채널. (측정, 단위, 이름, 변수, 방식, 집계)
_WINDOW_SPECS = (
    ('temperature', 'C', 'Window Max Temperature', 'temperature_2m', 'instant', max),
    ('temperature', 'C', 'Window Min Temperature', 'temperature_2m', 'instant', min),
    ('humidity', 'percent', 'Window Max Humidity', 'relative_humidity_2m', 'instant', max),
    ('speed', 'm_s', 'Window Max Wind', 'wind_speed_10m', 'instant', max),
    ('rain', 'mm', 'Window Max Hourly Rain', 'precipitation', 'cell', max),
    ('precipitation', 'percent', 'Window Max Rain Probability',
     'precipitation_probability', 'cell', max),
)
_WINDOW_BASE = len(_LEAD_HOURS) * _PER_LEAD            # 21
DURATION_CHANNEL = _WINDOW_BASE + len(_WINDOW_SPECS)   # 27


def _build_measurements():
    out = {}
    for i, lead in enumerate(_LEAD_HOURS):
        for j, (meas, unit, name, _var, mode) in enumerate(_LEAD_SPECS):
            # 리드·칸 뜻을 채널에 밝힌다 — 이름은 사용자가 고칠 수 있어 읽는 쪽이 이름을 파지 않게
            # (일별 예보의 `forecast_lead_d` 와 같은 방식, `utils.inputs.hourly_lead_channels`).
            out[i * _PER_LEAD + j] = {
                'measurement': meas, 'unit': unit,
                'name': '{} +{}h'.format(name, lead),
                'forecast_lead_h': lead, 'forecast_kind': mode}
    for k, (meas, unit, name, _var, _mode, _fn) in enumerate(_WINDOW_SPECS):
        out[_WINDOW_BASE + k] = {'measurement': meas, 'unit': unit, 'name': name}
    # OWM 원콜 채널 8 과 같은 방식 — 창 길이(h).
    out[DURATION_CHANNEL] = {
        'measurement': 'duration_time', 'unit': 'h', 'name': 'Window Length'}
    return out


measurements_dict = _build_measurements()

# 파일 키 → Open-Meteo 변수. 기상청 forecast.json 과 키를 맞춘다.
_FILE_VARS = {
    'TMP': 'temperature_2m',
    'REH': 'relative_humidity_2m',
    'WSD': 'wind_speed_10m',
    'VEC': 'wind_direction_10m',
    'RN1': 'precipitation',
    'POP': 'precipitation_probability',
    'CLD': 'cloud_cover',
    'SOL': 'shortwave_radiation',
    'WMO': 'weather_code',
}
_FILE_UNITS = {
    'TMP': 'C', 'REH': 'percent', 'WSD': 'm_s', 'VEC': 'bearing',
    'RN1': 'mm', 'POP': 'percent', 'CLD': 'percent', 'SOL': 'W_m2',
    'WMO': 'wmo_code',
}
FILE_HOURS = 48
# 파일 키 → L0(`fc_hourly`) 중립 변수 이름. 풍향·날씨 코드(WMO)는 L0 대상이 아니다.
_L0_VARS = {'TMP': 'T', 'REH': 'RH', 'WSD': 'WS', 'VEC': 'WD',
            'RN1': 'RAIN', 'SOL': 'SOL', 'CLD': 'CLD', 'POP': 'POP'}
LEAD_DEFINITION = {
    'instant': 'temperature/humidity/wind: linear interpolation between the hourly '
               'rows around now+L (exact hour = that row)',
    'cell': 'precipitation/solar/probability/cloud: row at ceil(now+L) hour, the cell '
            'ending there (precipitation = sum of previous 1h, solar = mean of '
            'previous 1h)',
    'window': 'instant variables: now, now+W and hourly rows in between; cell '
              'variables: rows with now < ts < now+W+3600; finished cells excluded',
    'missing': 'no value is written when data is missing (never 0.0)',
}

_WINDOW_CHOICES = tuple(str(h) for h in range(1, 7))
_MODEL_CHOICES = ('best_match', 'kma_seamless', 'jma_seamless',
                  'ecmwf_ifs025', 'icon_seamless', 'gfs_seamless')
# (connect, read) — 연결 단계 장애를 20 초 기다리지 않는다.
_TIMEOUT = (5, 15)
_RETRY_WAIT_S = 1.5


def _now():
    return time.time()


# ── 순수 계산 — 네트워크·DB 없이 시험할 수 있게 입력 클래스 밖에 둔다 ──────────

def rows_from_hourly(hourly):
    """응답 `hourly`(time=epoch 정수) → {epoch: {변수: 값}}. 정시가 아니거나 망가진 시각은 버린다."""
    rows = {}
    # 응답이 JSON 이어도 모양이 다를 수 있다(dict 가 아닌 hourly, 목록이 아닌 time).
    if not isinstance(hourly, dict):
        return rows
    times = hourly.get('time')
    if not isinstance(times, list):
        return rows
    for idx, ts in enumerate(times):
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            continue
        ts = int(ts)
        if ts % 3600:
            continue
        row = rows.setdefault(ts, {})
        for var, series in hourly.items():
            if var == 'time' or not isinstance(series, list) or idx >= len(series):
                continue
            val = series[idx]
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                continue
            if isinstance(val, float) and not math.isfinite(val):
                continue
            row[var] = float(val)
    return rows


def _at(rows, ts, var):
    row = rows.get(ts)
    return None if row is None else row.get(var)


def _interp(rows, t, var):
    """t 시각의 순간값 — 앞뒤 정시 직선 보간. 이웃 하나라도 없으면 None."""
    lo = int(math.floor(t / 3600.0)) * 3600
    a = _at(rows, lo, var)
    if t == lo:
        return a
    b = _at(rows, lo + 3600, var)
    if a is None or b is None:
        return None
    return a + (t - lo) / 3600.0 * (b - a)


def _cell(rows, t, var):
    """t 를 포함하는(끝나는) 칸의 값 — ceil(t) 정시 행."""
    return _at(rows, int(math.ceil(t / 3600.0)) * 3600, var)


def _window(rows, now, hours, var, mode, fn):
    end = now + hours * 3600.0
    cands = []
    if mode == 'instant':
        cands = [_interp(rows, now, var), _interp(rows, end, var)]
        cands += [r.get(var) for ts, r in rows.items() if now <= ts <= end]
    else:
        cands = [r.get(var) for ts, r in rows.items() if now < ts < end + 3600.0]
    cands = [c for c in cands if c is not None]
    return fn(cands) if cands else None


def _window_missing(rows, now, hours, var, mode):
    """창 집계가 기대한 점 중 값이 없는 수.

    집계 값 자체는 남은 점으로 낸다(PR 1 정의 — `test_None_값은_건너뛴다`).
    이 수는 **알리기 위한 것**이다: 창 최대 강수가 한 칸 빠진 채 계산되면 실제보다
    작게 나올 수 있으므로, 수집 때 로그로 남겨 사람이 볼 수 있게 한다.
    """
    end = now + hours * 3600.0
    missing = 0
    if mode == 'instant':
        missing += sum(1 for t in (now, end) if _interp(rows, t, var) is None)
        first = int(math.ceil(now / 3600.0)) * 3600
        expected = range(first, int(math.floor(end / 3600.0)) * 3600 + 1, 3600)
    else:
        first = int(math.floor(now / 3600.0)) * 3600 + 3600
        last = int(math.ceil((end + 3600.0) / 3600.0)) * 3600 - 3600
        expected = range(first, last + 1, 3600)
    missing += sum(1 for ts in expected if _at(rows, ts, var) is None)
    return missing


def window_gaps(rows, now, window_h):
    """{창 채널: 빠진 점 수} — 하나도 안 빠졌거나 전부 빠진(채널 자체가 없는) 것은 뺀다."""
    out = {}
    for k, (_m, _u, _n, var, mode, fn) in enumerate(_WINDOW_SPECS):
        if _window(rows, now, window_h, var, mode, fn) is None:
            continue
        n = _window_missing(rows, now, window_h, var, mode)
        if n:
            out[_WINDOW_BASE + k] = n
    return out


def channel_values(rows, now, window_h):
    """{채널: 값} — 값이 없는 채널은 키 자체가 없다."""
    out = {}
    for i, lead in enumerate(_LEAD_HOURS):
        t = now + lead * 3600.0
        for j, (_m, _u, _n, var, mode) in enumerate(_LEAD_SPECS):
            v = _interp(rows, t, var) if mode == 'instant' else _cell(rows, t, var)
            if v is not None:
                out[i * _PER_LEAD + j] = round(v, 3)
    for k, (_m, _u, _n, var, mode, fn) in enumerate(_WINDOW_SPECS):
        v = _window(rows, now, window_h, var, mode, fn)
        if v is not None:
            out[_WINDOW_BASE + k] = round(v, 3)
    out[DURATION_CHANNEL] = float(window_h)
    return out


def needed_variables(is_enabled):
    """켜진 채널이 쓰는 Open-Meteo 변수 집합."""
    need = set()
    for i in range(len(_LEAD_HOURS)):
        for j, spec in enumerate(_LEAD_SPECS):
            if is_enabled(i * _PER_LEAD + j):
                need.add(spec[3])
    for k, spec in enumerate(_WINDOW_SPECS):
        if is_enabled(_WINDOW_BASE + k):
            need.add(spec[3])
    return need


def _stamp(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y%m%d%H%M')


def build_forecast_file(rows, fetched_epoch, meta):
    """시간열 파일 내용 — forecast.json 상위 호환(키·`tz`/`now`/`pub_dt`).

    오프셋 키는 `now`(UTC 정시) 기준이다. 값이 없는 키는 넣지 않는다. 모든 변수가
    빈 행은 통째로 뺀다.
    """
    anchor = int(fetched_epoch // 3600) * 3600
    forecasts = {}
    for off in range(0, FILE_HOURS + 1):
        row = rows.get(anchor + off * 3600)
        if not row:
            continue
        item = {fkey: row[var] for fkey, var in _FILE_VARS.items() if var in row}
        if not item:
            continue
        for fkey in ('VEC', 'WMO'):
            if fkey in item:
                item[fkey] = int(round(item[fkey]))
        for fkey in ('REH', 'POP', 'CLD'):
            if fkey in item:
                item[fkey] = int(round(item[fkey]))
        item['epoch'] = anchor + off * 3600
        forecasts[str(off)] = item
    out = {
        'source': 'open_meteo', 'kind': 'forecast',
        'tz': 'UTC', 'now': _stamp(anchor), 'pub_dt': _stamp(fetched_epoch),
        'pub_kind': 'fetched', 'fetched_epoch': int(fetched_epoch),
        'forecasts': forecasts,
        'units': dict(_FILE_UNITS),
        'lead_definition': copy.deepcopy(LEAD_DEFINITION),
    }
    out.update(meta or {})
    return out


_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


def forecast_file_path(input_uuid):
    """입력별 예보 파일 경로 — 소비처(PR 4·5)도 이 함수로 찾는다.

    입력 id 는 uuid 형식이어야 한다(아니면 ValueError). 파일 이름에 그대로 들어가므로
    `None`·빈 값·경로 문자(`../`)가 섞이면 엉뚱한 파일(`forecast_None.json`)이나
    디렉터리 밖을 가리키게 된다.
    """
    if not isinstance(input_uuid, str) or not _UUID_RE.match(input_uuid):
        raise ValueError('input_uuid 가 uuid 형식이 아니다: {!r}'.format(input_uuid))
    from aot import config
    return os.path.join(config.DATABASE_PATH, 'openmeteo',
                        'forecast_{}.json'.format(input_uuid))


def write_forecast_file(path, data):
    """임시 파일에 쓴 뒤 rename — 읽는 쪽이 반쯤 쓴 파일을 보지 않는다. 디렉터리는 만든다."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.forecast_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# Input information
INPUT_INFORMATION = {
    'input_name_unique': 'OPEN_METEO_HOURLY_FORECAST',
    'input_manufacturer': 'Open-Meteo',
    'input_name': 'Open-Meteo Hourly Forecast (Coords, +N h)',
    'input_name_short': 'Open-Meteo Forecast',
    # 예보 모델 값이다 — 현장 실측이 아니다(aot.utils.inputs.model_input_drivers).
    'data_origin': 'model',
    # 이 입력의 값은 **미래 시각에 대한 것**이다(오용 가드용 표식, 없으면 '현재').
    'data_time': 'forecast',
    'measurements_name': 'Forecast +1h/+3h/+6h and window max/min',
    'measurements_dict': measurements_dict,
    'url_additional': 'https://open-meteo.com',
    'measurements_rescale': False,
    'period': 1800,

    'message': 'Hourly FORECAST (not a measurement): +1h/+3h/+6h values and the '
               'max/min over the next N hours, from one API call per cycle. '
               'Values are stored at the time they were received. '
               'Do not bind these channels as an outdoor sensor. '
               'No API key needed — enter Latitude/Longitude only. '
               'Free use is non-commercial (CC-BY 4.0); a paid key switches to '
               'the commercial endpoint.',

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
            'id': 'window_h',
            'type': 'select',
            'default_value': '3',
            'required': True,
            'options_select': [(h, '{} h'.format(h)) for h in _WINDOW_CHOICES],
            'name': lazy_gettext('Window (hours)'),
            'phrase': 'Length of the "next N hours" window used by the max/min channels.'
        },
        {
            'id': 'model',
            'type': 'select',
            'default_value': 'best_match',
            'required': True,
            'options_select': [(m, m) for m in _MODEL_CHOICES],
            'name': lazy_gettext('Forecast Model'),
            'phrase': 'best_match picks the best model per location. Regional models '
                      '(kma_seamless, jma_seamless) may not provide rain probability.'
        },
        {
            'id': 'l0_leads',
            'type': 'select',
            'default_value': 'full',
            'required': False,
            'options_select': [('full', 'Every hour, 0-48 h'),
                               ('thin', 'Hourly to 24 h, then every 3 h (low-spec)'),
                               ('off', 'Do not store')],
            'name': lazy_gettext('Store Forecast Issues'),
            'phrase': 'Keep every received 0-48 h hourly forecast, tagged with its lead time, so '
                      'past forecasts can be compared with field measurements (data layer L0). '
                      'The channels and the hourly file are unaffected.'
        },
        {
            'id': 'write_file',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext('Write Hourly Forecast File'),
            'phrase': 'Also save the 0-48 h hourly series to a file for the '
                      'environment controller curve and weather hazards.'
        },
    ]
}


class InputModule(AbstractInput):
    """Open-Meteo 시간별 예보 → 리드·창 채널 + 시간열 파일.

    @phase active
    @stability stable
    @dependency AbstractInput
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)

        self.api_key = None
        self.window_h = '3'
        self.model = 'best_match'
        self.write_file = True
        # 시험(testing=True)은 사용자 옵션을 읽지 않으므로 Influx 를 건드리지 않게 꺼 둔다.
        self.l0_leads = 'off'

        if not testing:
            self.setup_custom_options(
                INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        if self.latitude is None or self.longitude is None:
            self.logger.error('Latitude/Longitude required')

    def _base_url(self):
        return _COMMERCIAL_URL if self.api_key else _FORECAST_URL

    def _window_hours(self):
        try:
            return min(6, max(1, int(self.window_h)))
        except (TypeError, ValueError):
            return 3

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

    def _store_issue(self, rows, now, payload):
        """받은 발표본을 L0(`fc_hourly`)에 남긴다 → 발표 기준 정시 epoch, 실패하면 None.

        실패해도 채널 값·파일을 막지 않는다. 제공자 행을 중립 변수 이름으로 옮기기만 하고 고치지 않는다.
        """
        try:
            from aot.utils import fc_store
            series = {}
            for fkey, var in _FILE_VARS.items():
                name = _L0_VARS.get(fkey)
                if not name:
                    continue
                col = {ts: row[var] for ts, row in rows.items() if var in row}
                if col:
                    series[name] = col
            leads = (fc_store.HOURLY_LEADS_THIN if getattr(self, 'l0_leads', 'off') == 'thin'
                     else fc_store.HOURLY_LEADS_FULL)
            n = fc_store.store_hourly(
                getattr(self, 'unique_id', None), now, series, leads,
                lat=payload.get('latitude'), lon=payload.get('longitude'),
                elev=payload.get('elevation'), model=self.model)
            return fc_store.issue_hour(now) if n else None
        except Exception as exc:                                # noqa: BLE001
            self.logger.error('예보 발표본(L0) 저장 실패: %s', exc)
            return None

    def get_measurement(self):
        """예보를 한 번 받아 리드·창 채널을 채우고 시간열 파일을 쓴다."""
        if self.latitude is None or self.longitude is None:
            self.logger.error('Latitude/Longitude required')
            return

        self.return_dict = copy.deepcopy(measurements_dict)

        need = needed_variables(self.is_enabled)
        want_file = bool(self.write_file)
        want_l0 = getattr(self, 'l0_leads', 'off') in ('full', 'thin')
        if want_file or want_l0:
            need |= set(_FILE_VARS.values())
        if not need:
            self.logger.debug('활성 채널 없음')
            return

        params = {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'hourly': ','.join(sorted(need)),
            # 시각을 UTC epoch 로 받는다 — 지역시각 문자열 해석을 없앤다.
            'timezone': 'UTC',
            'timeformat': 'unixtime',
            'forecast_hours': FILE_HOURS + 1,
            'past_hours': 1,         # 지금 칸 직전 정시 — 보간·경계용
            # ⚠ 단위를 명시한다(기본 풍속은 km/h — open_meteo_weather.py 참조).
            'wind_speed_unit': 'ms',
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
            self.logger.error('Open-Meteo 예보 조회 실패: %s', exc)
            return
        if not isinstance(payload, dict):
            # 200 인데 JSON 이 객체가 아니다(목록·문자열) — 값을 쓰지 않는다.
            self.logger.error('Open-Meteo 예보 응답 모양이 다르다: %s',
                              type(payload).__name__)
            return

        rows = rows_from_hourly(payload.get('hourly'))
        if not rows:
            self.logger.error('예보 행이 없다')
            return

        window_h = self._window_hours()
        for ch, value in channel_values(rows, now, window_h).items():
            self.value_set(ch, value)
        gaps = window_gaps(rows, now, window_h)
        if gaps:
            self.logger.warning(
                '창 집계 일부 결측 — 남은 칸으로 계산했다(실제보다 작거나 클 수 있음): %s',
                ', '.join('{} {}칸'.format(measurements_dict[ch]['name'], n)
                          for ch, n in sorted(gaps.items())))

        issued = None
        if want_l0:
            issued = self._store_issue(rows, now, payload)
        if want_file:
            try:
                meta = {
                    'input_uuid': getattr(self, 'unique_id', None),
                    'latitude': self.latitude, 'longitude': self.longitude,
                    'grid_latitude': payload.get('latitude'),
                    'grid_longitude': payload.get('longitude'),
                    'elevation': payload.get('elevation'),
                    'model': self.model or 'best_match',
                }
                if issued:
                    # L0(fc_hourly)에 같은 발표본이 있다 — 이 파일은 읽기용 사본이다.
                    meta['issued_epoch'] = issued
                    meta['l0_ref'] = 'fc_hourly'
                data = build_forecast_file(rows, now, meta)
                write_forecast_file(
                    forecast_file_path(meta['input_uuid']), data)
            except Exception as exc:                            # noqa: BLE001
                # 파일 실패가 채널 값을 막지 않는다.
                self.logger.error('예보 파일 쓰기 실패: %s', exc)

        return self.return_dict
