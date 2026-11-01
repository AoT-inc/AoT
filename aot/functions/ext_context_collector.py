# coding=utf-8
"""
ext_context_collector.py — External environment context collector Function (Phase A4).

Collects the facility's external environment values (temperature, humidity, wind speed,
rainfall, solar radiation, dew point, CO2) in one place and serves them as the system's
single source of truth.

Responsibilities:
  - Query each external sensor measurement via get_last_measurement
  - Check age -> staged fallback (§8.2)
  - Write the collected results to InfluxDB
  - Share the latest context so other Functions can fetch it via get_context()

Freshness (2026-09-19):
  Whether a reading is still usable is decided in ONE place —
  `aot.utils.measurement_freshness.effective_max_age` (device max_age_s >
  this Function's `sensor_max_age` > period-derived > floor). A reading
  that fails it is published as None — never replaced by a default. The
  control side decides what "unknown" means (rain/wind lost -> vents do not
  open further; see SafetyPreGate._weather_view). Items with NO sensor
  selected are not shared at all — no default values (a constant 20 °C/60 %
  read as a measurement is what made vents oscillate on 2026-08-22).

Reference: docs/dev/integrated_env_control_design.md §8
"""

import time
from statistics import median

from flask_babel import lazy_gettext

from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.functions.utils.env_control import psychro
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils import measurement_freshness as _freshness
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import write_influxdb_value
from aot.utils.lazy_text import lazy_format

# ─────────────────────────────────────────────────────────────────────────────
# Collection channels — InfluxDB measurement names
# ─────────────────────────────────────────────────────────────────────────────
MEAS_EXT_T        = 'ext_context_temperature'
MEAS_EXT_RH       = 'ext_context_humidity'
MEAS_EXT_WIND     = 'ext_context_wind'
MEAS_EXT_RAIN     = 'ext_context_rain'
MEAS_EXT_SOLAR    = 'ext_context_solar'
MEAS_EXT_DEWPOINT = 'ext_context_dewpoint'
MEAS_EXT_CO2      = 'ext_context_co2'
MEAS_EXT_AGE      = 'ext_context_age'         # age of the oldest sensor (seconds)
MEAS_EXT_VALID    = 'ext_context_valid'        # 1=valid, 0=expired

# ─────────────────────────────────────────────────────────────────────────────
# System-shared context cache (module-level sharing within the same process)
# ─────────────────────────────────────────────────────────────────────────────
_shared_context: dict = {}
_shared_context_ts: float = 0.0
_shared_context_period: float = 0.0     # 수집 주기 — 공유값 자체의 신선도 판정용

# 판정 배수·하한은 시설 실외 센서(`facility_sensors._max_age_for`)와 같다 —
# 같은 제어 경로의 실외값이라 근거(표본 1회 유실까지 정상)가 같다. 정본에
# 상수로 올리지 않는 이유는 `measurement_freshness` 머리말 참조.
_FRESH_FLOOR_S = 300
_FRESH_FACTOR = 2.0


def get_shared_context() -> dict:
    """Return the latest external environment context. Called by other Functions."""
    return dict(_shared_context)


def get_shared_context_ts() -> float:
    return _shared_context_ts


def shared_context_is_current(now: float = None) -> bool:
    """공유 컨텍스트가 **지금 것인가** — 수집기가 멈췄으면 False.

    수집기가 멈추거나 비활성화돼도 모듈 변수의 마지막 값은 남는다. 그것을
    이번 사이클 값으로 읽으면 강우·풍속이 끊긴 사실이 제어에 닿지 않는다.
    판정은 정본 규칙(주기 × 2, 하한 300초)이다.
    """
    if _shared_context_ts <= 0:
        return False
    limit = _freshness.effective_max_age(
        None, _shared_context_period or None, None,
        floor=_FRESH_FLOOR_S, factor=_FRESH_FACTOR)
    return ((now or time.time()) - _shared_context_ts) <= limit


def constraints_pass_current_value(mod_dev, value):
    """실외 항목(지금 값)에 **몇 시간 뒤 예보 입력**을 고르면 저장을 거부한다.

    드라이버 `data_time='forecast'`(OPEN_METEO_HOURLY_FORECAST)의 "+6h 강수" 를
    `sensor_rain` 에 두면 지금 오지 않는 비로 게이트가 걸린다(2026-10-13, 환경제어
    E4 — 경고가 아니라 거부). 표식이 없는 드라이버(`OPEN_METEO_FORECAST` 등)는
    '현재' 로 보아 그대로 받는다. 판정을 못 하면 받는다.

    웹 설정 폼(`custom_options_return_json`)과 AI 도구(modify_function_options ·
    create_function)가 같은 함수를 부른다.
    """
    try:
        from aot.utils.inputs import forecast_time_selection_problem
        why = forecast_time_selection_problem(value)
    except Exception:                                       # noqa: BLE001
        why = None
    if why:
        return False, [why], mod_dev
    return True, [], mod_dev


# ─────────────────────────────────────────────────────────────────────────────
# FUNCTION_INFORMATION
# ─────────────────────────────────────────────────────────────────────────────

FUNCTION_INFORMATION = {
    'function_name_unique': 'ext_context_collector',
    'function_name': lazy_gettext('External Environment Context Collector'),
    'function_name_short': 'Ext Context',

    'message': lazy_gettext(
        'Collects external temperature, humidity, wind speed, rainfall, solar radiation, '
        'dew point, and CO2 from outside the facility. The integrated environment control '
        'Function uses this collector as its single source of truth. Select the external '
        'sensor for each item. Items left blank are not shared — the integrated control '
        'treats them as unknown instead of assuming a value.'
    ),

    'options_enabled': ['custom_options'],
    'options_disabled': ['measurements_select', 'measurements_configure'],

    'custom_options': [
        {
            'id': 'update_period',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 60,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_format("{}: ({})", lazy_gettext('Update Period'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('Collection period (seconds). Set it equal to or shorter than the integrated control Function\'s cycle.'),
        },
        {
            'id': 'sensor_temperature',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'constraints_pass': constraints_pass_current_value,
            'name': lazy_gettext('External Temperature Sensor'),
            'phrase': lazy_gettext('Select the external air temperature measurement.'),
        },
        {
            'id': 'sensor_humidity',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'constraints_pass': constraints_pass_current_value,
            'name': lazy_gettext('External Humidity Sensor'),
            'phrase': lazy_gettext('Select the external relative humidity measurement.'),
        },
        {
            'id': 'sensor_wind',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'constraints_pass': constraints_pass_current_value,
            'name': lazy_gettext('Wind Speed Sensor'),
            'phrase': lazy_gettext('Select the wind speed (m/s) measurement.'),
        },
        {
            'id': 'sensor_rain',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'constraints_pass': constraints_pass_current_value,
            'name': lazy_gettext('Rain Sensor'),
            'phrase': lazy_gettext('Select the rainfall amount or rain detection measurement.'),
        },
        {
            'id': 'sensor_solar',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'constraints_pass': constraints_pass_current_value,
            'name': lazy_gettext('Solar Radiation Sensor'),
            'phrase': lazy_gettext('Select the solar radiation (W/m²) or illuminance measurement.'),
        },
        {
            'id': 'sensor_dewpoint',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'constraints_pass': constraints_pass_current_value,
            'name': lazy_gettext('Dew Point Sensor'),
            'phrase': lazy_gettext('Select the dew point (°C) measurement. If absent, it is calculated from temperature and humidity.'),
        },
        {
            'id': 'sensor_co2',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'constraints_pass': constraints_pass_current_value,
            'name': lazy_gettext('External CO₂ Sensor'),
            'phrase': lazy_gettext('Select the external CO₂ (ppm) measurement. If absent, the default is 400 ppm.'),
        },
        {
            'id': 'sensor_max_age',
            'type': 'float',
            # ⚠ **기본값을 숫자로 두지 말 것**(env_coordinator 의 같은 옵션과 같은
            #   사고). 120초였는데 기상청 300초·OpenWeather 600초라 실외
            #   데이터원이 사실상 전부 만료로 걸린다. 0 = "안 정했다" — 센서마다
            #   자기 주기로 판정한다(`measurement_freshness.as_seconds`).
            #   기존 설치의 120 은 `migrate_sensor_max_age_default` 가 눕힌다.
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Max Sensor Age (seconds)'),
            'phrase': lazy_gettext(
                'Reject sensor readings older than this. Leave at 0 to let '
                'each sensor decide from its own update interval.'
            ),
        },
        # ⚠ **기본값 옵션(`default_T_ext`·`default_RH_ext`·`default_wind`)을 되살리지
        #   말 것**(2026-09-19 제거). 센서를 고르지 않은 항목에 20 °C·60 %·바람 0 을
        #   채워 공유하면 제어는 그것을 **실측**으로 읽는다 — 지어낸 실외로 창이
        #   열렸다 닫혔다 한 2026-08-22 aot-005 사고와 같은 모양이다. 모르는 항목은
        #   공유하지 않고, "모른다" 의 처리는 제어가 한다(코디네이터 2.6 제자리 ·
        #   게이트의 "원래 없는 센서"). DB 에 남은 옛 값은 읽지 않으므로 무해하다.
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Function class
# ─────────────────────────────────────────────────────────────────────────────

class CustomFunction(AbstractFunction):
    """External environment context collector."""

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.update_period   = None
        self.sensor_max_age  = None

        # Sensor selection values (in device_id,channel_id form)
        self.sensor_temperature = None
        self.sensor_humidity    = None
        self.sensor_wind        = None
        self.sensor_rain        = None
        self.sensor_solar       = None
        self.sensor_dewpoint    = None
        self.sensor_co2         = None

        self.timer_loop = 0.0

        if not testing:
            self.setup_custom_options(
                FUNCTION_INFORMATION['custom_options'], function)
            self._log_startup()

    def _log_startup(self):
        self.logger.info(
            'ExtContextCollector started: period=%ss max_age=%ss',
            self.update_period, self.sensor_max_age)

    # ─────────────────────────────────────────────────────────────────────────
    # Main loop
    # ─────────────────────────────────────────────────────────────────────────

    def loop(self):
        if time.time() < self.timer_loop:
            return
        self.timer_loop = time.time() + (self.update_period or 60.0)
        self._collect_and_publish()

    # ─────────────────────────────────────────────────────────────────────────
    # Collect + publish
    # ─────────────────────────────────────────────────────────────────────────

    def _collect_and_publish(self):
        global _shared_context, _shared_context_ts, _shared_context_period

        now = time.time()
        requested = _freshness.as_seconds(self.sensor_max_age)
        selectors = {
            'T_ext':    self.sensor_temperature,
            'RH_ext':   self.sensor_humidity,
            'wind':     self.sensor_wind,
            'rain':     self.sensor_rain,
            'solar':    self.sensor_solar,
            'dewpoint': self.sensor_dewpoint,
            'CO2_ext':  self.sensor_co2,
        }
        # 장치 주기·max_age_s 는 IN 조회 한 번(데몬 안전 접근자 — 정본 모듈 주석).
        fresh_table = _freshness.freshness_by_device(
            [_split_selector(v)[0] for v in selectors.values() if v])

        values, stamps, stale = {}, {}, []
        for key, selector in selectors.items():
            if not selector:
                continue
            dev_id, meas_id = _split_selector(selector)
            period, device_max_age = _freshness.lookup(fresh_table, dev_id)
            window = _freshness.effective_max_age(
                requested, period, device_max_age,
                floor=_FRESH_FLOOR_S, factor=_FRESH_FACTOR)
            try:
                ts, val = _unpack_last(self.get_last_measurement(
                    dev_id, meas_id, max_age=window))
            except Exception:
                ts, val = None, None
            if val is None:
                stale.append(key)
                continue
            if key == 'rain':
                # 강우 게이트는 mm/h 로 본다 — 15 분 누적(KMA rn_15m) 등을 시간당으로
                # (`aot.utils.inputs.rain_unit_scale`). 모르는 단위는 그대로.
                from aot.utils.inputs import rain_measurement_mm_h
                val = rain_measurement_mm_h(val, meas_id)
            values[key] = val
            stamps[key] = ts if ts is not None else now

        # ── 센서를 고르지 않은 항목은 **공유하지 않는다** ──────────────────────
        # 값을 채우지 않는다 — 기본값도, 대기 배경 CO₂ 400 도. 채우면 제어가
        # 실측으로 읽는다(옵션 목록의 제거 주석). 없는 CO₂ 는 제어가 스스로 400 을
        # 가정한다(`situation.py` 의 EnvContext 구성) — 그 가정은 거기 한 곳이다.
        if not any(selectors.values()):
            if not getattr(self, '_warned_no_sensor', False):
                self.logger.error(
                    'ExtContext: 선택한 센서가 하나도 없습니다 — 공유할 실외값이 '
                    '없습니다(제어는 실외를 모르는 것으로 봅니다)')
                self._warned_no_sensor = True
        else:
            self._warned_no_sensor = False

        # 이슬점 센서가 없거나 늦으면 온습도로 계산한다 — 둘 다 있을 때만.
        if (values.get('dewpoint') is None and values.get('T_ext') is not None
                and values.get('RH_ext') is not None):
            values['dewpoint'] = _calc_dewpoint(values['T_ext'], values['RH_ext'])

        # 늦은 센서 목록이 **바뀔 때만** 남긴다(매 주기 찍으면 읽을 로그를 민다).
        stale_set = frozenset(stale)
        if stale_set != getattr(self, '_last_stale', frozenset()):
            if stale_set:
                self.logger.error(
                    'ExtContext: 값이 늦은 센서 — %s (값 없음으로 공유합니다)',
                    ', '.join(sorted(stale_set)))
            else:
                self.logger.error('ExtContext: 모든 센서 값이 돌아왔습니다')
            self._last_stale = stale_set

        # `last_ext_ts` = 실외 **온습도**를 마지막으로 받은 시각. 코디네이터가
        # 이것으로 마지막 실측 승계와 fallback 을 가른다(`_run_cycle` P2-2).
        # 온습도를 이번에 못 받았으면 **옛 시각을 그대로** 둔다 — now 로 덮으면
        # 끊긴 값을 영영 신선으로 읽는다(수리 전 결함).
        prev_ts = _shared_context.get('last_ext_ts', 0.0) or 0.0
        has_trh = (values.get('T_ext') is not None
                   or values.get('RH_ext') is not None)

        ctx = {key: values.get(key) for key in selectors}
        ctx['last_ext_ts'] = now if has_trh else prev_ts
        # 강우 값의 출처 — 예보 모델(Open-Meteo 등)이면 강우 게이트가 전면 폐쇄 대신
        # 단계 제한을 건다(`safety_gates.classify_rain`). 값이 없으면 싣지 않는다.
        if ctx.get('rain') is not None:
            from aot.utils.inputs import rain_origin_of
            ctx['rain_origin'] = rain_origin_of([_split_selector(self.sensor_rain)[0]])

        _shared_context        = ctx
        _shared_context_ts     = now
        _shared_context_period = float(self.update_period or 60.0)

        uid = self.unique_id
        for key, meas in (('T_ext', MEAS_EXT_T), ('RH_ext', MEAS_EXT_RH),
                          ('wind', MEAS_EXT_WIND), ('rain', MEAS_EXT_RAIN),
                          ('solar', MEAS_EXT_SOLAR), ('dewpoint', MEAS_EXT_DEWPOINT),
                          ('CO2_ext', MEAS_EXT_CO2)):
            if ctx[key] is not None:        # 값 없음은 기록하지 않는다(0 이 아니다)
                write_influxdb_value(uid, meas, value=ctx[key], channel=0)
        oldest_age = max((now - t for t in stamps.values()), default=0.0)
        write_influxdb_value(uid, MEAS_EXT_AGE, value=oldest_age, channel=0)
        write_influxdb_value(uid, MEAS_EXT_VALID,
                             value=0.0 if stale else 1.0, channel=0)


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _split_selector(selector: str):
    """'device_id,measurement_id' → (device_id, measurement_id)."""
    parts = (selector or '').split(',')
    return parts[0], (parts[1] if len(parts) > 1 else '')


def _unpack_last(result):
    """`get_last_measurement` 결과 → (시각, 값). 값이 없으면 (None, None).

    그 함수는 **`[시각, 값]` 리스트**를 준다(없으면 `[None, None]`). 수리 전
    이 모듈은 그것을 스칼라로 써서, 이슬점 센서가 없으면 이슬점 계산에서
    TypeError 로 매 주기 죽었고(공유 컨텍스트가 영영 빈 채), 있으면 리스트가
    그대로 실외 온도로 실렸다.
    """
    if isinstance(result, (list, tuple)):
        if len(result) < 2:
            return None, None
        ts, val = result[0], result[1]
    else:
        ts, val = None, result
    if val is None:
        return None, None
    try:
        val = float(val)
    except (TypeError, ValueError):
        return None, None
    try:
        ts = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        ts = None
    return ts, val


def _calc_dewpoint(T: float, RH: float) -> float:
    """Calculate the dew point (°C) with the Magnus formula (`psychro.dewpoint`).

    RH is floored at 0.1 % so a 0 reading does not take log(0).
    """
    return psychro.dewpoint(max(RH, 0.1) / 100.0 * psychro.svp(T))
