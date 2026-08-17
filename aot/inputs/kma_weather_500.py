# coding=utf-8
#
#  This software is a derivative version based on the open-source Mycodo
#  project (© Kyle T. Gabriel), modified to suit the goals of the AoT project.
#  This file has been modified by AoT from the original Mycodo version.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#  Copyright (C) 2015-2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  This file is distributed under the GNU GPLv3 license.
#  The original copyright and license terms are stated below.
#
#  --------------------------------------------------------------
#  Original file information:
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <http://www.gnu.org/licenses/>.
#
#  Contact:
#    - Original author: Kyle T. Gabriel (kylegabriel.com)
#    - Modified version: AoT (aot.inc.kr@gmail.com)
#  --------------------------------------------------------------
#  2025-11-03

import copy
import re
import requests
import datetime
import time
import zlib
from datetime import timezone

from flask_babel import lazy_gettext

# Optional AoT DB/Influx helpers for backfill (guarded imports)
try:
    from aot.config import AOT_DB_PATH
    from aot.databases.models import Input
    from aot.databases.utils import session_scope
    from aot.utils.influx import (
        add_measurements_influxdb, read_influxdb_list, read_influxdb_single)
    _AOT_BACKFILL_AVAILABLE = True
except Exception:
    _AOT_BACKFILL_AVAILABLE = False

# --- Backfill request tuning ---------------------------------------------
# apihub returns 504 on large windows: one-day chunks (288 rows at itv=5) timed
# out repeatedly on 2026-08-12 while the smaller tail chunks went through. The
# response size is what breaks, so the chunk is sized down rather than the
# timeout up. These are settled values, not user choices — no options for them.
BACKFILL_CHUNK_MINUTES = 360        # 72 rows per request at itv=5
BACKFILL_TIMEOUT_SEC = 90
BACKFILL_RETRY_COUNT = 3            # total attempts per window
BACKFILL_RETRY_DELAY_SEC = 5        # backs off 5s, 10s between attempts
BACKFILL_CHUNK_PAUSE_SEC = 1.0      # breathing room between windows
BACKFILL_STAGGER_MAX_SEC = 20       # spread concurrent inputs at daemon start
BACKFILL_RETRY_ROUNDS = 3           # later cycles given to a failed window
BACKFILL_RETRIES_PER_CYCLE = 2      # windows retried per live cycle
# A chunk counts as already stored above this fraction of its 5-minute slots.
# Not 1.0: KMA itself has gaps, and a chunk that can never reach full coverage
# would otherwise be re-requested on every single restart, forever.
BACKFILL_COVERAGE_RATIO = 0.95

_AUTH_KEY_RE = re.compile(r'(authKey=)[^&\s\'"]+')


def _mask_key(text):
    """Redact authKey= before anything reaches the log.

    The KMA key rode into koat's log file inside requests' exception text
    (the whole URL is in the message), where it sat in plaintext for anyone
    reading the logs. Everything that can carry a URL goes through here.
    """
    try:
        return _AUTH_KEY_RE.sub(r'\1***', str(text))
    except Exception:
        return '<unprintable>'

# --- Simple QC bounds (conservative) ---
QC_BOUNDS = {
    'ta': (-50.0, 60.0),        # Celsius
    'hm': (0.1, 100.0),         # percent; 0 is treated as invalid glitch
    'pa': (850.0, 1100.0),      # hPa; 0 or out of range invalid
    'ws_10m': (0.0, 60.0),      # m/s
    'wd_10m': (0.0, 360.0),     # bearing
    'rn_ox': (0.0, 1.0),        # indicator (0/1); 0 can be valid
    'rn_15m': (0.0, 500.0),     # mm/15min (large upper bound)
    'vs': (0.0, 100.0),         # km
    'sd_tot': (0.0, 500.0)      # cm
}


def _in_bounds(key, val):
    lo, hi = QC_BOUNDS[key]
    try:
        return lo <= float(val) <= hi
    except Exception:
        return False

# Helper: safely parse float or return None if invalid/empty
def _to_float_or_none(s):
    try:
        if s is None:
            return None
        s = str(s).strip()
        if s == "" or s.lower() == "nan":
            return None
        return float(s.replace(',', ''))
    except Exception:
        return None

from aot.inputs.base_input import AbstractInput
from aot.inputs.sensorutils import calculate_dewpoint
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.device_tz import get_device_tz

# Helper: read option from either custom_options or custom_channel_options
def _get_opt(inst, key, default=None):
    try:
        val = inst.get_custom_option(key)
        if val is not None:
            return val
    except Exception:
        pass
    try:
        if hasattr(inst, 'input_dev') and isinstance(inst.input_dev.options, dict):
            return inst.input_dev.options.get(key, default)
    except Exception:
        pass
    return default

measurements_dict = {
    0: {'measurement': 'temperature', 'unit': 'C', 'name': lazy_gettext('Temperature')},
    1: {'measurement': 'humidity', 'unit': 'percent', 'name': lazy_gettext('Humidity')},
    2: {'measurement': 'pressure', 'unit': 'hPa', 'name': lazy_gettext('Pressure')},
    3: {'measurement': 'direction', 'unit': 'bearing', 'name': lazy_gettext('Wind Direction')},
    4: {'measurement': 'speed', 'unit': 'm_s', 'name': lazy_gettext('Wind Speed')},
    5: {'measurement': 'precipitation', 'unit': 'none', 'name': lazy_gettext('Rain')},
    6: {'measurement': 'precipitation', 'unit': 'mm', 'name': lazy_gettext('15-min Precipitation')},
    7: {'measurement': 'visibility', 'unit': 'km', 'name': lazy_gettext('Visibility')},
    8: {'measurement': 'snowfall', 'unit': 'cm', 'name': lazy_gettext('Snow Depth')},
    9: {'measurement': 'dewpoint', 'unit': 'C', 'name': lazy_gettext('Dew Point')}
}

INPUT_INFORMATION = {
    'input_name_unique': 'KMA_weather_500',
    'input_manufacturer': 'KMA',
    'input_name': lazy_gettext('KMA High-Resolution 500m'),
    'input_name_short': lazy_gettext('KMA Environmental Data'),
    'measurements_dict': measurements_dict,
    'url_additional': 'https://apihub.kma.go.kr',
    'measurements_rescale': False,

    # 저장 시각을 InfluxDB 가 찍게 두면 라이브 포인트는 관측 시각이 아니라 쓰기
    # 시각(5분 경계 + 수십 초)에 떨어진다. 백필은 KMA 관측 시각(정확한 5분
    # 경계)에 쓰므로 같은 관측이 서로 다른 두 점이 되어 이중 저장된다.
    # 양쪽을 같은 격자에 올려 재백필이 덮어쓰기가 되게 한다.
    'measurements_use_same_timestamp': False,

    'message': lazy_gettext('After issuing a free API key from the KMA API Hub, data is requested based on the location (latitude/longitude) in the input settings.'
               ' Note: the Korea Meteorological Administration API allows 20000 calls per day, and each call returns data for a single observation station.'),

    'options_enabled': [
        'measurements_select',
        'pre_output'
    ],

    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext("API Key"),
            'phrase': lazy_gettext("Enter the API Key issued by the KMA API Hub.")
        },
        {
            'id': 'period',
            'type': 'float',
            'default_value': 300,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("Measurement Period (sec)"),
            'phrase': lazy_gettext("Enter the measurement interval in seconds.")
        },
        {
            'id': 'qc_enable',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext("Enable Quality Control (QC)"),
            'phrase': lazy_gettext("Ignore or correct obvious outliers (e.g. humidity 0%, pressure 0hPa, etc.).")
        },
        {
            'id': 'qc_hold_seconds',
            'type': 'float',
            'default_value': 1800,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("QC Hold Time (sec)"),
            'phrase': lazy_gettext("Replace with the last valid value within this time window.")
        },
        {
            'id': 'backfill_minutes',
            'type': 'float',
            'default_value': 1440,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("Manual Backfill Period (min)"),
            'phrase': lazy_gettext("On user request, load this much past data. Default 1440 min (1 day).")
        },
        {
            'id': 'backfill_request',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext("Run Backfill Now"),
            'phrase': lazy_gettext("When enabled after saving, performs a single backfill immediately and then turns off automatically.")
        },
        # NOTE (2026-08-17): 'split_precip_measurements' was removed. It renamed
        # channel 5/6 to 'precipitation_flag'/'precipitation_mm_15m' at WRITE
        # time only, while DeviceMeasurements (the table every READ path resolves
        # the measure tag from — return_measurement_info) still said
        # 'precipitation'. Influx stores the name as the `measure` tag, so every
        # read filtered on a tag that was never written: graphs, /last,
        # get_sensor_detail and the MCP tools all reported precipitation as
        # having no data at all, while snowfall (not renamed) recorded 0.0
        # normally. The conflict it claimed to avoid does not exist — the two
        # channels already differ by both `channel` tag and Influx measurement
        # (unit 'none' vs 'mm'), so they were never one series.
        {
            'id': 'qc_zero_accept_margin_deg',
            'type': 'float',
            'default_value': 3.0,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("QC: 0°C Accept Range (±°C)"),
            'phrase': lazy_gettext("Accept 0°C only when the previous valid value is within this range of 0°C. Default ±3°C.")
        }
    ]
}


class InputModule(AbstractInput):
    """KMA API weather station driver for high-resolution 500m grid observation data.

    Produces temperature (C), humidity (percent), pressure (hPa), wind direction (bearing),
    wind speed (m/s), precipitation, visibility (km), snowfall (cm), and dew point (C).

    @phase active
    @dependency AbstractInput
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)
        if not hasattr(self.input_dev, 'options'):
            self.input_dev.options = {}
        self.api_url = None
        self.api_key = None
        self.lon = None
        self.lat = None
        self.period = 600  # default 600 sec
        self._pre_output_pipeline_warned = False

        # Aggregated QC counters (reset per cycle)
        self._qc_live_replaced = 0
        self._qc_live_dropped = 0
        self._qc_live_zero_ta_dropped = 0
        self._qc_backfill_replaced = 0
        self._qc_backfill_dropped = 0
        self._qc_backfill_zero_ta_dropped = 0

        self._last_good = None
        self._last_good_ts = None

        self.first_run = True
        self.latest_datetime = None

        # Windows whose request failed transiently, retried on later cycles
        self._backfill_retry_windows = []
        # (channel, unit, measure) that answered the last freshness probe
        self._probe_channel = None
        # Rate limit for the recurring "response held no rows" notice
        self._empty_response_streak = 0

        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        # Load basic runtime config and last timestamp if available
        try:
            self.period = int(self.get_custom_option('period') or 300)
        except Exception:
            self.period = 300
        # Use device location from input settings (single source of truth)
        try:
            self.lon = float(self.input_dev.longitude) if self.input_dev.longitude is not None else None
            self.lat = float(self.input_dev.latitude) if self.input_dev.latitude is not None else None
        except Exception:
            self.lon = None
            self.lat = None
        # If controller persisted a last datetime, keep it for backfill window
        try:
            self.latest_datetime = getattr(self.input_dev, 'datetime', None)
        except Exception:
            self.latest_datetime = None

    def _latest_stored_datetime(self, duration_sec=None):
        """Newest stored data point for this input, as naive UTC (or None).

        The freshness gate must ask the measurement store, not `Input.datetime`.
        That column only ever advanced inside get_new_data(), so it recorded
        "when a backfill last ran" rather than "how far the data reaches" —
        letting a >7-day gap between daemon restarts re-download a week that
        was already complete.
        """
        if not _AOT_BACKFILL_AVAILABLE:
            return None
        # Precipitation channels are skipped: historical points written before
        # 2026-08-17 carry the old renamed measure tag
        # ('precipitation_flag'/'precipitation_mm_15m'), so probing them would
        # read as empty on exactly the installs that do have history. The rest
        # are ordered by how likely they are to be enabled — the common case
        # costs one query, and a disabled channel costs none.
        candidates = (
            (0, 'C', 'temperature'),
            (1, 'percent', 'humidity'),
            (2, 'hPa', 'pressure'),
            (9, 'C', 'dewpoint'),
            (4, 'm_s', 'speed'),
            (3, 'bearing', 'direction'),
            (7, 'km', 'visibility'),
            (8, 'cm', 'snowfall'),
        )
        for channel, unit, measure in candidates:
            try:
                if not self.is_enabled(channel):
                    continue
                last_time, _ = read_influxdb_single(
                    self.unique_id, unit, channel, measure=measure,
                    duration_sec=duration_sec, value='LAST')
                if last_time:
                    # Remember which channel answered: the coverage check must
                    # count on a channel that actually holds data, or a chunk
                    # would read as empty and be re-requested every restart.
                    self._probe_channel = (channel, unit, measure)
                    return datetime.datetime.utcfromtimestamp(float(last_time))
            except Exception:
                self.logger.exception(
                    f"Reading the newest stored measurement failed (channel {channel})")
                return None
        return None

    def _persist_latest_datetime(self, ts):
        """Advance Input.datetime if `ts` is newer than what is stored."""
        if not ts or not _AOT_BACKFILL_AVAILABLE:
            return
        try:
            # Normalize to naive UTC for DB comparison/storage to avoid naive/aware TypeError
            if ts.tzinfo is not None:
                ts_naive_utc = ts.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                ts_naive_utc = ts

            with session_scope(AOT_DB_PATH) as new_session:
                mod_input = new_session.query(Input).filter(
                    Input.unique_id == self.unique_id).first()
                if mod_input is None:
                    return
                db_dt = getattr(mod_input, 'datetime', None)
                if db_dt is not None and getattr(db_dt, 'tzinfo', None) is not None:
                    db_dt_naive_utc = db_dt.astimezone(timezone.utc).replace(tzinfo=None)
                else:
                    db_dt_naive_utc = db_dt

                if db_dt_naive_utc is None or db_dt_naive_utc < ts_naive_utc:
                    mod_input.datetime = ts_naive_utc
                    new_session.commit()
            self.latest_datetime = ts_naive_utc
        except Exception as e:
            self.logger.error(f"Persisting latest datetime failed: {e}")

    def _observation_datetime(self, pub_timestamp):
        """Convert a KMA 'YYYYMMDDHHMM' station-local stamp to naive UTC."""
        try:
            if not pub_timestamp or len(str(pub_timestamp)) != 12:
                return None
            device_tz = get_device_tz(self.input_dev)
            ts_local = datetime.datetime.strptime(str(pub_timestamp), "%Y%m%d%H%M")
            ts = device_tz.localize(ts_local).astimezone(timezone.utc).replace(tzinfo=None)
            utc_now = datetime.datetime.utcnow()
            if ts > utc_now + datetime.timedelta(minutes=2):
                self.logger.warning(
                    f"Observation ts in future after TZ adjust ({ts} > now). Clamping.")
                ts = utc_now - datetime.timedelta(minutes=2)
            return ts
        except Exception:
            return None

    def _stagger_delay(self):
        """Deterministic 0..N second offset, distinct per input.

        Every KMA input starts its backfill in the same second at daemon start
        and they all queue against the same upstream. Spreading them is not
        politeness — concurrent large windows are what tips apihub into 504.
        Derived from the uuid rather than random() so a restart reproduces the
        same ordering and the logs stay comparable.
        """
        try:
            return zlib.crc32(self.unique_id.encode()) % (BACKFILL_STAGGER_MAX_SEC + 1)
        except Exception:
            return 0

    def _chunk_is_covered(self, start_local, end_local, device_tz):
        """True when the store already holds this window at 5-minute density.

        Refetching a stored window is not harmless: it is the slowest request
        the driver makes, and enough of them in a row is what produced the 504
        storm. Coverage is measured on whichever channel answered the freshness
        probe, so a channel the user never enabled cannot report a false gap.
        """
        if not _AOT_BACKFILL_AVAILABLE or not self._probe_channel:
            return False
        channel, unit, measure = self._probe_channel
        try:
            start_utc = device_tz.localize(start_local).astimezone(timezone.utc)
            end_utc = device_tz.localize(end_local).astimezone(timezone.utc)
            expected = max(1, int((end_local - start_local).total_seconds() // 300))
            stored = read_influxdb_list(
                self.unique_id, unit, channel, measure=measure,
                start_str=start_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
                end_str=end_utc.strftime('%Y-%m-%dT%H:%M:%SZ'))
            count = len(stored) if stored else 0
            ratio = count / float(expected)
            if ratio >= BACKFILL_COVERAGE_RATIO:
                self.logger.debug(
                    f"Window {start_local:%Y%m%d%H%M}-{end_local:%Y%m%d%H%M} already stored "
                    f"({count}/{expected} slots); skipping.")
                return True
            return False
        except Exception:
            # An unanswerable store must not block a backfill — fetch instead.
            self.logger.debug("Coverage check failed; treating the window as missing.")
            return False

    def _plan_backfill_windows(self, now_local, minutes, device_tz):
        """Split the requested span into chunks, dropping ones already stored."""
        if self._probe_channel is None:
            # The manual "Run Backfill Now" path never went through the
            # freshness gate, so nothing has picked a probe channel yet.
            self._latest_stored_datetime(duration_sec=int(minutes * 60) + 86400)
        windows = []
        skipped = 0
        chunk_start = now_local - datetime.timedelta(minutes=minutes)
        while chunk_start < now_local:
            chunk_end = min(
                chunk_start + datetime.timedelta(minutes=BACKFILL_CHUNK_MINUTES), now_local)
            start, end = chunk_start, chunk_end
            chunk_start = chunk_end
            if start >= end:
                continue
            if self._chunk_is_covered(start, end, device_tz):
                skipped += 1
                continue
            windows.append((start.strftime("%Y%m%d%H%M"), end.strftime("%Y%m%d%H%M")))
        if skipped:
            self.logger.info(
                f"Backfill plan: {len(windows)} window(s) to fetch, "
                f"{skipped} already stored.")
        return windows

    def _fetch_window(self, tm1, tm2):
        """Fetch one window with retries. Returns (rows, ok).

        `ok` is False only when the window is worth trying again later; an API
        error (bad key, bad coordinates) is permanent and returns ok=True with
        no rows so it is not queued forever.
        """
        url = (
            "https://apihub.kma.go.kr/api/typ01/url/sfc_nc_var.php"
            f"?tm1={tm1}&tm2={tm2}&lon={self.lon}&lat={self.lat}"
            f"&obs=ta,hm,wd_10m,ws_10m,pa,rn_ox,rn_15m,vs,sd_tot"
            f"&itv=5&help=0&authKey={self.api_key}"
        )
        self.logger.debug("Backfill URL: {}".format(_mask_key(url)))

        last_error = None
        for attempt in range(1, BACKFILL_RETRY_COUNT + 1):
            try:
                response = requests.get(url, timeout=BACKFILL_TIMEOUT_SEC)
                response.raise_for_status()
            except Exception as e:
                last_error = _mask_key(e)
                if attempt < BACKFILL_RETRY_COUNT:
                    delay = BACKFILL_RETRY_DELAY_SEC * (2 ** (attempt - 1))
                    self.logger.warning(
                        f"Backfill {tm1}-{tm2} attempt {attempt}/{BACKFILL_RETRY_COUNT} "
                        f"failed ({last_error}); retrying in {delay}s")
                    time.sleep(delay)
                    continue
                # Transient by nature (timeout/gateway); worth a later cycle.
                self.logger.error(
                    f"Backfill {tm1}-{tm2} gave up after {BACKFILL_RETRY_COUNT} attempts: "
                    f"{last_error}")
                return [], False

            if 'error' in response.text[:200]:
                self.logger.error(
                    f"Backfill API error for window {tm1}-{tm2}: "
                    f"{_mask_key(response.text[:120])}")
                return [], True

            return self._parse_rows(response.text), True

        return [], False

    def _parse_rows(self, response_text):
        """Parse the sfc_nc_var CSV body into row dicts."""
        rows = []
        for line in response_text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            cols = [col.strip() for col in line.split(',')]
            if len(cols) != 10:
                continue
            pub_timestamp = cols[0]
            if len(pub_timestamp) != 12:
                continue
            # Skip obviously bogus triple-zero rows
            try:
                if (float(cols[1]) == 0.0 and float(cols[2]) == 0.0 and float(cols[5]) == 0.0):
                    self.logger.debug(
                        f"Ignoring invalid data row with ta=0, hm=0, pa=0 at {pub_timestamp}")
                    continue
            except Exception:
                pass
            row = {
                'pub_timestamp': pub_timestamp,
                'ta': _to_float_or_none(cols[1]),
                'hm': _to_float_or_none(cols[2]),
                'wd_10m': _to_float_or_none(cols[3]),
                'ws_10m': _to_float_or_none(cols[4]),
                'pa': _to_float_or_none(cols[5]),
                'rn_ox': _to_float_or_none(cols[6]),
                'rn_15m': _to_float_or_none(cols[7]),
                'vs': _to_float_or_none(cols[8]),
                'sd_tot': _to_float_or_none(cols[9]),
            }
            # if all numeric fields are None, skip this row
            if all(v is None for k, v in row.items() if k != 'pub_timestamp'):
                continue
            rows.append(row)
        return rows

    def _queue_failed_window(self, tm1, tm2):
        """Hand a transiently-failed window to later live cycles."""
        for pending in self._backfill_retry_windows:
            if pending['tm1'] == tm1 and pending['tm2'] == tm2:
                return
        self._backfill_retry_windows.append({'tm1': tm1, 'tm2': tm2, 'rounds': 0})

    def drain_backfill_retries(self):
        """Retry a couple of previously-failed windows. Called per live cycle.

        Without this a 504 silently costs a whole chunk of history: the old
        code logged the error and moved on, and nothing ever came back for it.
        """
        if not self._backfill_retry_windows:
            return
        device_tz = get_device_tz(self.input_dev)
        for _ in range(min(BACKFILL_RETRIES_PER_CYCLE, len(self._backfill_retry_windows))):
            pending = self._backfill_retry_windows.pop(0)
            pending['rounds'] += 1
            rows, ok = self._fetch_window(pending['tm1'], pending['tm2'])
            if rows:
                self.logger.info(
                    f"Backfill retry recovered {len(rows)} rows for "
                    f"{pending['tm1']}-{pending['tm2']}.")
                self._write_backfill_rows(rows, device_tz)
            elif not ok:
                if pending['rounds'] >= BACKFILL_RETRY_ROUNDS:
                    self.logger.error(
                        f"Backfill window {pending['tm1']}-{pending['tm2']} abandoned after "
                        f"{pending['rounds']} rounds; that history stays missing.")
                else:
                    self._backfill_retry_windows.append(pending)

    def get_new_data(self, past_minutes):
        """Backfill: fetch [now - past_minutes, now] at 5-min interval and write to InfluxDB.
        This mirrors the TTN input's initial backfill behavior.
        """
        if not _AOT_BACKFILL_AVAILABLE:
            self.logger.info("Backfill helpers unavailable in this build; skipping backfill.")
            return
        try:
            minutes = int(past_minutes)
        except Exception:
            self.logger.error("past_minutes must be integer-like")
            return

        # reset QC aggregation counters for backfill cycle
        self._qc_backfill_replaced = 0
        self._qc_backfill_dropped = 0
        self._qc_backfill_zero_ta_dropped = 0

        if not self.lon or not self.lat:
            self.logger.error("Coordinates are not set. Please save the location (latitude/longitude) in the input settings first.")
            return

        # KMA interprets tm1/tm2 in the station's local time. Use the device's
        # location-derived timezone so the window is correct on any host.
        device_tz = get_device_tz(self.input_dev)
        now = datetime.datetime.now(device_tz).replace(tzinfo=None)
        if minutes < 5:
            self.logger.info("Backfill window <5 minutes; skipping.")
            return

        # KMA sfc_nc_var.php rejects windows >2 days (error -9) and silently
        # truncates long responses, so the span is always chunked.
        windows = self._plan_backfill_windows(now, minutes, device_tz)
        if not windows:
            self.logger.info("Backfill span is already stored in full; nothing to fetch.")
            return

        delay = self._stagger_delay()
        if delay:
            self.logger.debug(f"Staggering backfill start by {delay}s.")
            time.sleep(delay)

        rows = []
        seen_ts = set()
        failed = 0
        for index, (tm1, tm2) in enumerate(windows):
            if index:
                time.sleep(BACKFILL_CHUNK_PAUSE_SEC)
            chunk_rows, ok = self._fetch_window(tm1, tm2)
            if not ok:
                failed += 1
                self._queue_failed_window(tm1, tm2)
            for row in chunk_rows:
                if row['pub_timestamp'] in seen_ts:
                    continue
                seen_ts.add(row['pub_timestamp'])
                rows.append(row)

        if failed:
            self.logger.warning(
                f"Backfill: {failed} of {len(windows)} window(s) failed; "
                f"queued for retry on later cycles.")

        if not rows:
            self.logger.info("No rows parsed for backfill window.")
            return
        self.logger.info(
            f"Backfill parsed {len(rows)} rows across {len(windows)} window(s).")

        self._write_backfill_rows(rows, device_tz)

    def _write_backfill_rows(self, rows, device_tz):
        """QC and store parsed backfill rows at their observation timestamps."""
        rows = sorted(rows, key=lambda r: r['pub_timestamp'])
        latest_ts_seen = None
        rows_written = 0

        # QC options
        qc_enable = bool(_get_opt(self, 'qc_enable', True))
        qc_hold_seconds = float(_get_opt(self, 'qc_hold_seconds', 1800))

        for row in rows:
            # Build timestamp, convert KMA local (device timezone) to UTC
            try:
                ts_local = datetime.datetime.strptime(row['pub_timestamp'], "%Y%m%d%H%M")
                ts = device_tz.localize(ts_local).astimezone(timezone.utc)  # store as UTC, tz-aware
                # Guard: if computed UTC is in the future by >2 minutes, clamp to now-2min
                utc_now = datetime.datetime.now(timezone.utc)
                if ts > utc_now + datetime.timedelta(minutes=2):
                    self.logger.warning(f"Backfill ts in future after TZ adjust ({ts} > now). Clamping.")
                    ts = utc_now - datetime.timedelta(minutes=2)
            except Exception:
                continue

            if qc_enable:
                now_ts = datetime.datetime.now()
                for k in ('ta','hm','wd_10m','ws_10m','pa','rn_ox','rn_15m','vs','sd_tot'):
                    if not _in_bounds(k, row[k]):
                        if self._last_good and self._last_good_ts and (now_ts - self._last_good_ts).total_seconds() <= qc_hold_seconds:
                            self.logger.debug(f"QC replacing invalid {k} with last good value during backfill.")
                            row[k] = self._last_good.get(k, row[k])
                            self._qc_backfill_replaced += 1
                        else:
                            self.logger.debug(f"QC dropping field {k} (no fallback) during backfill: {row[k]}")
                            row[k] = None
                            self._qc_backfill_dropped += 1

            # --- QC: accept 0°C only if previous good is within ±margin ---
            try:
                margin = float(_get_opt(self, 'qc_zero_accept_margin_deg', 3.0))
            except Exception:
                margin = 3.0
            prev_ta = self._last_good.get('ta') if self._last_good else None
            curr_ta = row.get('ta')
            if curr_ta is not None and float(curr_ta) == 0.0:
                if not (prev_ta is not None and abs(float(prev_ta) - 0.0) <= margin):
                    self.logger.debug(f"Backfill QC dropping suspicious 0°C temperature (prev={prev_ta}, margin=±{margin}°C).")
                    row['ta'] = None
                    self._qc_backfill_zero_ta_dropped += 1

            measurements = {}
            if self.is_enabled(0) and row.get('ta') is not None:
                measurements[0] = {'measurement': 'temperature', 'unit': 'C', 'value': row['ta'], 'timestamp_utc': ts}
            if self.is_enabled(1) and row.get('hm') is not None:
                measurements[1] = {'measurement': 'humidity', 'unit': 'percent', 'value': row['hm'], 'timestamp_utc': ts}
            if self.is_enabled(2) and row.get('pa') is not None:
                measurements[2] = {'measurement': 'pressure', 'unit': 'hPa', 'value': row['pa'], 'timestamp_utc': ts}
            if self.is_enabled(3) and row.get('wd_10m') is not None:
                measurements[3] = {'measurement': 'direction', 'unit': 'bearing', 'value': row['wd_10m'], 'timestamp_utc': ts}
            if self.is_enabled(4) and row.get('ws_10m') is not None:
                measurements[4] = {'measurement': 'speed', 'unit': 'm_s', 'value': row['ws_10m'], 'timestamp_utc': ts}
            # The measurement name MUST stay the one in measurements_dict — it is
            # what DeviceMeasurements holds and therefore what every read path
            # filters the `measure` tag on. See the removed-option note in
            # INPUT_INFORMATION.
            if self.is_enabled(5) and row.get('rn_ox') is not None:
                measurements[5] = {'measurement': 'precipitation', 'unit': 'none', 'value': row['rn_ox'], 'timestamp_utc': ts}
            if self.is_enabled(6) and row.get('rn_15m') is not None:
                measurements[6] = {'measurement': 'precipitation', 'unit': 'mm', 'value': row['rn_15m'], 'timestamp_utc': ts}
            if self.is_enabled(7) and row.get('vs') is not None:
                measurements[7] = {'measurement': 'visibility', 'unit': 'km', 'value': row['vs'], 'timestamp_utc': ts}
            if self.is_enabled(8) and row.get('sd_tot') is not None:
                measurements[8] = {'measurement': 'snowfall', 'unit': 'cm', 'value': row['sd_tot'], 'timestamp_utc': ts}
            if self.is_enabled(9) and row.get('ta') is not None and row.get('hm') is not None:
                dp = calculate_dewpoint(row['ta'], row['hm'])
                measurements[9] = {'measurement': 'dewpoint', 'unit': 'C', 'value': dp, 'timestamp_utc': ts}

            # Apply the same pre-output actions as live pipeline (if available)
            try:
                if hasattr(self, 'run_input_actions') and callable(getattr(self, 'run_input_actions')):
                    processed = self.run_input_actions(copy.deepcopy(measurements))
                    if isinstance(processed, dict) and processed:
                        measurements = processed
                else:
                    try:
                        if not getattr(self, '_pre_output_pipeline_warned', False):
                            self.logger.debug("Pre-output action pipeline not available; writing raw measurements (subsequent messages suppressed).")
                            self._pre_output_pipeline_warned = True
                    except Exception:
                        # Fallback: single debug log if attribute access fails
                        self.logger.debug("Pre-output action pipeline not available; writing raw measurements.")
            except Exception as e:
                self.logger.warning(f"pre-output actions during backfill failed: {e}")

            # Ensure per-point timestamps survive any action processing
            if isinstance(measurements, dict) and measurements:
                for _ch, pt in measurements.items():
                    if isinstance(pt, dict):
                        pt['timestamp_utc'] = ts
                        pt['timestamp'] = ts  # some builds expect 'timestamp'

            if measurements:
                try:
                    # Use per-point timestamps (do NOT collapse to now)
                    add_measurements_influxdb(self.unique_id, measurements, use_same_timestamp=False)
                    latest_ts_seen = ts
                    rows_written += 1
                    if rows_written <= 3:
                        try:
                            self.logger.debug(f"Backfill sample write[{rows_written}] ts={ts}")
                        except Exception:
                            pass
                except Exception as e:
                    self.logger.error(f"Failed to write backfill measurements: {e}")

            # update last-good cache (skip None)
            self._last_good = {}
            for key in ('ta','hm','wd_10m','ws_10m','pa','rn_ox','rn_15m','vs','sd_tot'):
                val = row.get(key)
                if val is not None:
                    self._last_good[key] = val
            self._last_good_ts = datetime.datetime.now()

        # Aggregated QC summary for backfill (single line per cycle)
        try:
            if (self._qc_backfill_replaced + self._qc_backfill_dropped + self._qc_backfill_zero_ta_dropped) > 0:
                self.logger.debug(
                    "QC(backfill) summary: replaced=%d, dropped=%d, zero_ta_dropped=%d",
                    self._qc_backfill_replaced, self._qc_backfill_dropped, self._qc_backfill_zero_ta_dropped
                )
        except Exception:
            pass

        # Persist latest timestamp for this input (if newer)
        self._persist_latest_datetime(latest_ts_seen)

    def pre_fetch_data(self):
        """Perform the API call and response parsing, returning a dict with the latest data."""
        try:
            response = requests.get(self.api_url, timeout=120)
            response.raise_for_status()
            data_text = response.text
            self.logger.debug("KMA raw response:\n{}".format(data_text))
        except Exception as e:
            self.logger.error(f"Error acquiring weather information: {_mask_key(e)}")
            return None

        lines = data_text.strip().split('\n')
        
        best_ts = None
        data = {}
        for line in lines:
            line = line.strip()
            # Skip comment lines (including block markers)
            if line.startswith('#'):
                continue

            cols = [col.strip() for col in line.split(',')]
            if len(cols) != 10:
                continue
            pub_timestamp = cols[0]
            if len(pub_timestamp) != 12:
                continue
            if not pub_timestamp:
                self.logger.error("No data available for this time. The response data is empty.")
                continue
            
            # Skip rows that are obviously bogus (core metrics all zero)
            try:
                if (float(cols[1]) == 0.0 and float(cols[2]) == 0.0 and float(cols[5]) == 0.0):
                    self.logger.debug(f"Ignoring invalid data row with ta=0, hm=0, pa=0 at {pub_timestamp}")
                    continue
            except Exception:
                pass

            curr_ta = _to_float_or_none(cols[1] if len(cols) > 1 else None)
            curr_hm = _to_float_or_none(cols[2] if len(cols) > 2 else None)
            curr_wd_10m = _to_float_or_none(cols[3] if len(cols) > 3 else None)
            curr_ws_10m = _to_float_or_none(cols[4] if len(cols) > 4 else None)
            curr_pa = _to_float_or_none(cols[5] if len(cols) > 5 else None)
            curr_rn_ox = _to_float_or_none(cols[6] if len(cols) > 6 else None)
            curr_rn_15m = _to_float_or_none(cols[7] if len(cols) > 7 else None)
            curr_vs = _to_float_or_none(cols[8] if len(cols) > 8 else None)
            curr_sd_tot = _to_float_or_none(cols[9] if len(cols) > 9 else None)
            # if all parsed values are None, skip this row
            if all(v is None for v in (curr_ta, curr_hm, curr_wd_10m, curr_ws_10m, curr_pa, curr_rn_ox, curr_rn_15m, curr_vs, curr_sd_tot)):
                continue
            # Since the format is YYYYMMDDHHMM, select the latest pub_timestamp by string comparison
            if best_ts is None or pub_timestamp > best_ts:
                best_ts = pub_timestamp
                data = {
                    "ta": curr_ta,
                    "hm": curr_hm,
                    "wd_10m": curr_wd_10m,
                    "ws_10m": curr_ws_10m,
                    "pa": curr_pa,
                    "rn_ox": curr_rn_ox,
                    "rn_15m": curr_rn_15m,
                    "vs": curr_vs,
                    "sd_tot": curr_sd_tot,
                    "pub_timestamp": pub_timestamp
                }
        if best_ts is None:
            # A 5-minute window with no observation yet is ordinary at this
            # grid resolution — koat logged 27 of these as ERROR in one day.
            # Only a run of them means something is actually wrong.
            #
            # The escalation stays at ERROR rather than WARNING on purpose:
            # an input logger sits at ERROR unless the user turns on debug
            # logging for that input (base_input.py), so a WARNING here would
            # make a real, sustained outage completely silent. Quiet for a
            # single gap, loud once it persists.
            self._empty_response_streak += 1
            streak = self._empty_response_streak
            if streak == 6 or (streak > 6 and streak % 12 == 0):
                minutes = streak * int(self.period or 300) // 60
                self.logger.error(
                    f"No valid data in the last {streak} responses (~{minutes} min).")
            else:
                self.logger.debug("No valid data found in the response.")
            return None
        self._empty_response_streak = 0
        return data

    def get_measurement(self):
        # Read values from custom options (now uses _get_opt)
        self.api_key = _get_opt(self, 'api_key', '')
        try:
            self.lon = float(self.input_dev.longitude) if self.input_dev.longitude is not None else None
            self.lat = float(self.input_dev.latitude) if self.input_dev.latitude is not None else None
        except Exception:
            self.lon = None
            self.lat = None
        try:
            self.period = int(_get_opt(self, 'period', 300))
        except Exception:
            self.period = 300

        # Manual backfill on user request (TTN-like)
        try:
            backfill_request = bool(_get_opt(self, 'backfill_request', False))
            backfill_minutes = int(float(_get_opt(self, 'backfill_minutes', 1440)))
        except Exception:
            backfill_request = False
            backfill_minutes = 1440

        did_backfill = False
        if backfill_request:
            self.logger.info(f"Manual backfill requested: fetching ~{backfill_minutes} minutes of past data...")
            try:
                self.get_new_data(backfill_minutes)
                did_backfill = True
            except Exception:
                self.logger.exception("Manual backfill get_new_data crashed")
            # Auto-reset toggle in DB to avoid repeated runs
            try:
                if _AOT_BACKFILL_AVAILABLE:
                    with session_scope(AOT_DB_PATH) as new_session:
                        mod_input = new_session.query(Input).filter(Input.unique_id == self.unique_id).first()
                        if mod_input is not None:
                            opts = dict(mod_input.options) if isinstance(mod_input.options, dict) else {}
                            if opts.get('backfill_request'):
                                opts['backfill_request'] = False
                                mod_input.options = opts
                                new_session.commit()
            except Exception as e:
                self.logger.error(f"Failed to auto-reset backfill_request: {e}")

        # First-run backfill policy:
        # - If the measurement store has data within the last 7 days, SKIP the
        #   initial weekly backfill.
        # - Otherwise, backfill up to 7 days (or since last data, whichever is smaller).
        #
        # Freshness is judged from the measurement store, falling back to
        # Input.datetime only when the store cannot answer. The column alone is
        # not a freshness signal: it used to advance only inside get_new_data(),
        # so a week without a daemon restart made the next restart re-download
        # seven days that were already complete.
        if self.first_run:
            self.first_run = False
            week_sec = 7 * 86400
            do_backfill = True
            seconds_download = week_sec
            try:
                utc_now = datetime.datetime.utcnow()
                # Bounded to just past the decision window: anything older than
                # this cannot make the gate skip, and an unbounded last() would
                # scan the whole retention on every daemon start.
                last_dt = self._latest_stored_datetime(duration_sec=week_sec + 86400)
                source = "measurement store"
                if last_dt is None:
                    last_dt = self.latest_datetime
                    source = "Input.datetime"
                if last_dt:
                    # last_dt is naive UTC
                    seconds_since_last = (utc_now - last_dt).total_seconds()
                    if 0 <= seconds_since_last <= week_sec:
                        # Recent data exists within 7 days → skip heavy initial backfill
                        hours_ago = round(seconds_since_last / 3600.0, 1)
                        self.logger.info(
                            f"Recent data found ({source}, newest {hours_ago}h ago); "
                            f"skipping initial weekly backfill.")
                        do_backfill = False
                    else:
                        # No recent data (or very old gap) → cap initial backfill to 7 days
                        seconds_download = min(max(0, seconds_since_last), week_sec) if seconds_since_last > 0 else week_sec
                else:
                    self.logger.info(
                        "No stored data found for this input; a full initial backfill will run.")
            except Exception:
                # On any error, fall back to a 7-day backfill to heal gaps
                self.logger.exception(
                    "Backfill freshness check failed; falling back to a full 7-day backfill")
                seconds_download = week_sec
                do_backfill = True
            if do_backfill:
                minutes_download = int(max(5, round(seconds_download / 60.0)))
                days_hint = round(minutes_download / 1440.0, 2)
                self.logger.info(f"Initial backfill: downloading ~{minutes_download} minutes (~{days_hint} days) of past data...")
                try:
                    self.get_new_data(minutes_download)
                    did_backfill = True
                except Exception:
                    self.logger.exception("Backfill get_new_data crashed")

        # If any backfill ran this cycle, skip the live 5-min fetch once
        if did_backfill:
            self.logger.info("Skipping live fetch this cycle to avoid overlapping with backfill request.")
            return

        # Windows that 504'd earlier get their later attempts here, spread
        # across cycles instead of hammering the API in one burst.
        try:
            self.drain_backfill_retries()
        except Exception:
            self.logger.exception("Backfill retry drain crashed")

        qc_enable = bool(_get_opt(self, 'qc_enable', True))
        qc_hold_seconds = float(_get_opt(self, 'qc_hold_seconds', 1800))

        if self.api_key and self.lon is not None and self.lat is not None:
            # Request window: data from 5 minutes ago up to now.
            # KMA interprets tm1/tm2 in the station's local time; use the
            # device's location-derived timezone (correct on any host).
            now = datetime.datetime.now(get_device_tz(self.input_dev)).replace(tzinfo=None)
            tm1_dt = now - datetime.timedelta(minutes=5)
            tm1 = tm1_dt.strftime("%Y%m%d%H%M")
            tm2 = now.strftime("%Y%m%d%H%M")
            # itv is the interval (in minutes) between tm1 and tm2; here it is 5 minutes.
            itv = 5

            self.api_url = (
                "https://apihub.kma.go.kr/api/typ01/url/sfc_nc_var.php"
                f"?tm1={tm1}&tm2={tm2}&lon={self.lon}&lat={self.lat}"
                f"&obs=ta,hm,wd_10m,ws_10m,pa,rn_ox,rn_15m,vs,sd_tot"
                f"&itv={itv}&help=0&authKey={self.api_key}"
            )
            self.logger.debug("URL: {}".format(_mask_key(self.api_url)))
        else:
            self.logger.error("API key or coordinates are missing. Please save the latitude/longitude in the input settings.")
            return

        # measurements_dict is the single source for the measurement names; the
        # live path must not rewrite them (see the removed-option note above).
        self.return_dict = copy.deepcopy(measurements_dict)
        data = self.pre_fetch_data()
        if data is None:
            return

        # Stamp the live reading with the KMA observation time, not the write
        # time, so it lands on the same 5-minute grid the backfill writes to.
        # Without this the two paths produce separate points for one
        # observation and any overlapping backfill doubles the series.
        live_ts = self._observation_datetime(data.get('pub_timestamp'))
        if live_ts is None:
            self.logger.debug(
                "No usable observation timestamp in the response; falling back to write time.")

        # reset QC aggregation counters for live cycle
        self._qc_live_replaced = 0
        self._qc_live_dropped = 0
        self._qc_live_zero_ta_dropped = 0

        # --- QC: guard against impossible zeros or out-of-range spikes ---
        if qc_enable:
            now_ts = datetime.datetime.now()
            for k in ('ta','hm','wd_10m','ws_10m','pa','rn_ox','rn_15m','vs','sd_tot'):
                if not _in_bounds(k, data[k]):
                    if self._last_good and self._last_good_ts and (now_ts - self._last_good_ts).total_seconds() <= qc_hold_seconds:
                        self.logger.debug(f"QC replacing invalid {k} with last good value.")
                        data[k] = self._last_good.get(k, data[k])
                        self._qc_live_replaced += 1
                    else:
                        self.logger.debug(f"QC dropping field {k} due to invalid value {data[k]} with no fallback.")
                        data[k] = None
                        self._qc_live_dropped += 1

        # --- QC: accept 0°C only if previous good is within ±margin ---
        try:
            margin = float(_get_opt(self, 'qc_zero_accept_margin_deg', 3.0))
        except Exception:
            margin = 3.0
        prev_ta = self._last_good.get('ta') if self._last_good else None
        curr_ta = data.get('ta')
        if curr_ta is not None and float(curr_ta) == 0.0:
            if not (prev_ta is not None and abs(float(prev_ta) - 0.0) <= margin):
                self.logger.debug(f"QC dropping suspicious 0°C temperature (prev={prev_ta}, margin=±{margin}°C).")
                data['ta'] = None
                self._qc_live_zero_ta_dropped += 1

        ta = data.get("ta")
        hm = data.get("hm")
        wd_10m = data.get("wd_10m")
        ws_10m = data.get("ws_10m")
        pa = data.get("pa")
        rn_ox = data.get("rn_ox")
        rn_15m = data.get("rn_15m")
        vs = data.get("vs")
        sd_tot = data.get("sd_tot")

        pressure = pa
        dew_point = None
        if ta is not None and hm is not None:
            dew_point = calculate_dewpoint(ta, hm)

        self.logger.debug(
            "Parsed -> Temp: {}, Hum: {}, Pressure: {}, Wind Dir: {}, Wind Speed: {}, "
            "Precipitation Indicator: {}, 15min Precip: {}, Visibility: {}, Snowfall: {}"
            .format(ta, hm, pressure, wd_10m, ws_10m, rn_ox, rn_15m, vs, sd_tot)
        )

        # Update last-good cache only with QC-passed values (skip None)
        self._last_good = {}
        for key in ('ta','hm','wd_10m','ws_10m','pa','rn_ox','rn_15m','vs','sd_tot'):
            val = data.get(key)
            if val is not None:
                self._last_good[key] = val
        self._last_good_ts = datetime.datetime.now()

        # Aggregated QC summary for live cycle (single line per cycle)
        try:
            if (self._qc_live_replaced + self._qc_live_dropped + self._qc_live_zero_ta_dropped) > 0:
                self.logger.debug(
                    "QC(live) summary: replaced=%d, dropped=%d, zero_ta_dropped=%d",
                    self._qc_live_replaced, self._qc_live_dropped, self._qc_live_zero_ta_dropped
                )
        except Exception:
            pass

        # Classify the data and store it in self.return_dict
        if self.is_enabled(0) and ta is not None:
            self.value_set(0, ta, timestamp=live_ts)
        if self.is_enabled(1) and hm is not None:
            self.value_set(1, hm, timestamp=live_ts)
        if self.is_enabled(2) and pressure is not None:
            self.value_set(2, pressure, timestamp=live_ts)
        if self.is_enabled(3) and wd_10m is not None:
            self.value_set(3, wd_10m, timestamp=live_ts)
        if self.is_enabled(4) and ws_10m is not None:
            self.value_set(4, ws_10m, timestamp=live_ts)
        if self.is_enabled(5) and rn_ox is not None:
            self.value_set(5, rn_ox, timestamp=live_ts)
        if self.is_enabled(6) and rn_15m is not None:
            self.value_set(6, rn_15m, timestamp=live_ts)
        if self.is_enabled(7) and vs is not None:
            self.value_set(7, vs, timestamp=live_ts)
        if self.is_enabled(8) and sd_tot is not None:
            self.value_set(8, sd_tot, timestamp=live_ts)
        if self.is_enabled(9) and dew_point is not None:
            self.value_set(9, dew_point, timestamp=live_ts)

        # Keep Input.datetime advancing on the live path too. Leaving it to the
        # backfill alone is what made the freshness gate misfire.
        self._persist_latest_datetime(live_ts)

        return self.return_dict
