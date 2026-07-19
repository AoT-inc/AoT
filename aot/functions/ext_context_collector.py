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

Fallback policy (§8.2):
  Normal collection -> refresh cache + update last_ts
  age > 60s   -> warning log
  age > 5 min -> expired — last_ext_ts for the Pre-Gate signal is stale
  age > 30 min -> system alert (ERROR log)

Reference: docs/dev/integrated_env_control_design.md §8
"""

import time
from statistics import median

from flask_babel import lazy_gettext

from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import write_influxdb_value

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


def get_shared_context() -> dict:
    """Return the latest external environment context. Called by other Functions."""
    return dict(_shared_context)


def get_shared_context_ts() -> float:
    return _shared_context_ts


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
        'sensor for each item. Leave items blank to apply the fallback default value.'
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
            'name': "{}: ({})".format(lazy_gettext('Update Period'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('Collection period (seconds). Set it equal to or shorter than the integrated control Function\'s cycle.'),
        },
        {
            'id': 'sensor_temperature',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'name': lazy_gettext('External Temperature Sensor'),
            'phrase': lazy_gettext('Select the external air temperature measurement.'),
        },
        {
            'id': 'sensor_humidity',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'name': lazy_gettext('External Humidity Sensor'),
            'phrase': lazy_gettext('Select the external relative humidity measurement.'),
        },
        {
            'id': 'sensor_wind',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'name': lazy_gettext('Wind Speed Sensor'),
            'phrase': lazy_gettext('Select the wind speed (m/s) measurement.'),
        },
        {
            'id': 'sensor_rain',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'name': lazy_gettext('Rain Sensor'),
            'phrase': lazy_gettext('Select the rainfall amount or rain detection measurement.'),
        },
        {
            'id': 'sensor_solar',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'name': lazy_gettext('Solar Radiation Sensor'),
            'phrase': lazy_gettext('Select the solar radiation (W/m²) or illuminance measurement.'),
        },
        {
            'id': 'sensor_dewpoint',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'name': lazy_gettext('Dew Point Sensor'),
            'phrase': lazy_gettext('Select the dew point (°C) measurement. If absent, it is calculated from temperature and humidity.'),
        },
        {
            'id': 'sensor_co2',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input', 'Function'],
            'name': lazy_gettext('External CO₂ Sensor'),
            'phrase': lazy_gettext('Select the external CO₂ (ppm) measurement. If absent, the default is 400 ppm.'),
        },
        {
            'id': 'sensor_max_age',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 120,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext('Sensor Maximum Allowed Age (seconds)'),
            'phrase': lazy_gettext('Measurements older than this are replaced with the fallback default value.'),
        },
        {
            'id': 'default_T_ext',
            'type': 'float',
            'default_value': 20.0,
            'required': False,
            'name': lazy_gettext('Fallback External Temperature (°C)'),
            'phrase': lazy_gettext('Default value to use when the sensor is absent or expired.'),
        },
        {
            'id': 'default_RH_ext',
            'type': 'float',
            'default_value': 60.0,
            'required': False,
            'name': lazy_gettext('Fallback External Humidity (%)'),
            'phrase': '',
        },
        {
            'id': 'default_wind',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Fallback Wind Speed (m/s)'),
            'phrase': '',
        },
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
        self.default_T_ext   = None
        self.default_RH_ext  = None
        self.default_wind    = None

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
        global _shared_context, _shared_context_ts

        max_age = self.sensor_max_age or 120.0
        now = time.time()
        oldest_age = 0.0

        def fetch(selector_val, fallback):
            """Query the measurement. Return the fallback on failure or expiry."""
            nonlocal oldest_age
            if not selector_val:
                return fallback, True
            try:
                dev_id, meas_id = selector_val.split(',')[:2]
                val = self.get_last_measurement(dev_id, meas_id, max_age=max_age)
                if val is None:
                    return fallback, False
                oldest_age = max(oldest_age, now - self._get_last_ts(dev_id, meas_id))
                return val, True
            except Exception:
                return fallback, False

        T_ext,    T_ok   = fetch(self.sensor_temperature, self.default_T_ext or 20.0)
        RH_ext,   RH_ok  = fetch(self.sensor_humidity,    self.default_RH_ext or 60.0)
        wind,     w_ok   = fetch(self.sensor_wind,        self.default_wind or 0.0)
        rain,     r_ok   = fetch(self.sensor_rain,        0.0)
        solar,    s_ok   = fetch(self.sensor_solar,       0.0)
        co2_ext,  c_ok   = fetch(self.sensor_co2,         400.0)
        dewpoint, d_ok   = fetch(self.sensor_dewpoint,    None)

        # Dew point: if no sensor, calculate with the Magnus formula
        if dewpoint is None:
            dewpoint = _calc_dewpoint(T_ext, RH_ext)

        # age-based valid determination
        age_warn  = oldest_age > 60.0
        age_exp   = oldest_age > 300.0
        valid     = not age_exp

        if age_exp:
            self.logger.error(
                'ExtContext: sensors stale %.0fs — system alert!', oldest_age)
        elif age_warn:
            self.logger.warning(
                'ExtContext: sensors age %.0fs', oldest_age)

        ctx = {
            'T_ext':    T_ext,
            'RH_ext':   RH_ext,
            'wind':     wind,
            'rain':     rain,
            'solar':    solar,
            'dewpoint': dewpoint,
            'CO2_ext':  co2_ext,
            'last_ext_ts': now if valid else (_shared_context.get('last_ext_ts', 0)),
        }

        _shared_context    = ctx
        _shared_context_ts = now

        uid = self.unique_id
        write_influxdb_value(uid, MEAS_EXT_T,        value=T_ext,    channel=0)
        write_influxdb_value(uid, MEAS_EXT_RH,       value=RH_ext,   channel=0)
        write_influxdb_value(uid, MEAS_EXT_WIND,     value=wind,     channel=0)
        write_influxdb_value(uid, MEAS_EXT_RAIN,     value=rain,     channel=0)
        write_influxdb_value(uid, MEAS_EXT_SOLAR,    value=solar,    channel=0)
        write_influxdb_value(uid, MEAS_EXT_DEWPOINT, value=dewpoint, channel=0)
        write_influxdb_value(uid, MEAS_EXT_CO2,      value=co2_ext,  channel=0)
        write_influxdb_value(uid, MEAS_EXT_AGE,      value=oldest_age, channel=0)
        write_influxdb_value(uid, MEAS_EXT_VALID,    value=1.0 if valid else 0.0, channel=0)

    def _get_last_ts(self, dev_id: str, meas_id: str) -> float:
        """Query the measurement's actual timestamp (for age calculation). On failure, return the current time."""
        try:
            from aot.utils.influx import read_last_influxdb
            last = read_last_influxdb(dev_id, meas_id)
            if last:
                return last[0]
        except Exception:
            pass
        return time.time()


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _calc_dewpoint(T: float, RH: float) -> float:
    """Calculate the dew point (°C) with the Magnus formula."""
    import math
    a, b = 17.27, 237.3
    alpha = (a * T) / (b + T) + math.log(max(RH, 0.1) / 100.0)
    return (b * alpha) / (a - alpha)
