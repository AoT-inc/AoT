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
import requests
import datetime
from datetime import timezone

from flask_babel import lazy_gettext

# Optional AoT DB/Influx helpers for backfill (guarded imports)
try:
    from aot.config import AOT_DB_PATH
    from aot.databases.models import Input
    from aot.databases.utils import session_scope
    from aot.utils.influx import add_measurements_influxdb
    _AOT_BACKFILL_AVAILABLE = True
except Exception:
    _AOT_BACKFILL_AVAILABLE = False

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
        {
            'id': 'split_precip_measurements',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': lazy_gettext("Separate Precipitation Series"),
            'phrase': lazy_gettext("Record the precipitation indicator (rn_ox) and 15-min precipitation (rn_15m) under different measurement names to avoid conflicts.")
        },
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
        itv = 5

        # KMA sfc_nc_var.php rejects windows >2 days (error -9) and silently
        # truncates responses to ~1 day of rows, so fetch in 1-day chunks.
        chunk_minutes = 1440
        rows = []
        seen_ts = set()
        chunk_start = now - datetime.timedelta(minutes=minutes)
        while chunk_start < now:
            chunk_end = min(chunk_start + datetime.timedelta(minutes=chunk_minutes), now)
            tm1 = chunk_start.strftime("%Y%m%d%H%M")
            tm2 = chunk_end.strftime("%Y%m%d%H%M")
            chunk_start = chunk_end
            if tm1 >= tm2:
                continue

            url = (
                "https://apihub.kma.go.kr/api/typ01/url/sfc_nc_var.php"
                f"?tm1={tm1}&tm2={tm2}&lon={self.lon}&lat={self.lat}"
                f"&obs=ta,hm,wd_10m,ws_10m,pa,rn_ox,rn_15m,vs,sd_tot"
                f"&itv={itv}&help=0&authKey={self.api_key}"
            )
            self.logger.debug("Backfill URL: {}".format(url))

            try:
                response = requests.get(url, timeout=180)
                response.raise_for_status()
            except Exception as e:
                self.logger.error(f"Backfill request error ({tm1}-{tm2}): {e}")
                continue

            if 'error' in response.text[:200]:
                self.logger.error(f"Backfill API error for window {tm1}-{tm2}: {response.text[:120]}")
                continue

            lines = response.text.strip().split('\n')
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                cols = [col.strip() for col in line.split(',')]
                if len(cols) != 10:
                    continue
                pub_timestamp = cols[0]
                if len(pub_timestamp) != 12:
                    continue
                if pub_timestamp in seen_ts:
                    continue
                # Skip obviously bogus triple-zero rows
                try:
                    if (float(cols[1]) == 0.0 and float(cols[2]) == 0.0 and float(cols[5]) == 0.0):
                        self.logger.debug(f"Ignoring invalid data row with ta=0, hm=0, pa=0 at {pub_timestamp}")
                        continue
                except Exception:
                    pass
                row = {
                    'pub_timestamp': pub_timestamp,
                    'ta': _to_float_or_none(cols[1] if len(cols) > 1 else None),
                    'hm': _to_float_or_none(cols[2] if len(cols) > 2 else None),
                    'wd_10m': _to_float_or_none(cols[3] if len(cols) > 3 else None),
                    'ws_10m': _to_float_or_none(cols[4] if len(cols) > 4 else None),
                    'pa': _to_float_or_none(cols[5] if len(cols) > 5 else None),
                    'rn_ox': _to_float_or_none(cols[6] if len(cols) > 6 else None),
                    'rn_15m': _to_float_or_none(cols[7] if len(cols) > 7 else None),
                    'vs': _to_float_or_none(cols[8] if len(cols) > 8 else None),
                    'sd_tot': _to_float_or_none(cols[9] if len(cols) > 9 else None),
                }
                # if all numeric fields are None, skip this row
                if all(v is None for k, v in row.items() if k != 'pub_timestamp'):
                    continue
                seen_ts.add(pub_timestamp)
                rows.append(row)

        if not rows:
            self.logger.info("No rows parsed for backfill window.")
            return
        self.logger.info(f"Backfill parsed {len(rows)} rows across {max(1, -(-minutes // chunk_minutes))} chunk(s).")

        rows.sort(key=lambda r: r['pub_timestamp'])
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
            # Choose measurement names for precipitation series to avoid overwrite
            split_precip = bool(_get_opt(self, 'split_precip_measurements', True))
            meas_rn_flag = 'precipitation_flag' if split_precip else 'precipitation'
            meas_rn_15m = 'precipitation_mm_15m' if split_precip else 'precipitation'
            if self.is_enabled(5) and row.get('rn_ox') is not None:
                measurements[5] = {'measurement': meas_rn_flag, 'unit': 'none', 'value': row['rn_ox'], 'timestamp_utc': ts}
            if self.is_enabled(6) and row.get('rn_15m') is not None:
                measurements[6] = {'measurement': meas_rn_15m, 'unit': 'mm', 'value': row['rn_15m'], 'timestamp_utc': ts}
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
        if latest_ts_seen:
            try:
                # Normalize to naive UTC for DB comparison/storage to avoid naive/aware TypeError
                latest_ts_aware = latest_ts_seen
                if latest_ts_aware.tzinfo is not None:
                    latest_ts_naive_utc = latest_ts_aware.astimezone(timezone.utc).replace(tzinfo=None)
                else:
                    latest_ts_naive_utc = latest_ts_aware

                with session_scope(AOT_DB_PATH) as new_session:
                    mod_input = new_session.query(Input).filter(Input.unique_id == self.unique_id).first()
                    if mod_input is not None:
                        db_dt = getattr(mod_input, 'datetime', None)
                        if db_dt is not None and getattr(db_dt, 'tzinfo', None) is not None:
                            db_dt_naive_utc = db_dt.astimezone(timezone.utc).replace(tzinfo=None)
                        else:
                            db_dt_naive_utc = db_dt

                        if db_dt_naive_utc is None or db_dt_naive_utc < latest_ts_naive_utc:
                            mod_input.datetime = latest_ts_naive_utc
                            new_session.commit()
            except Exception as e:
                self.logger.error(f"Persisting latest datetime failed: {e}")

    def pre_fetch_data(self):
        """Perform the API call and response parsing, returning a dict with the latest data."""
        try:
            response = requests.get(self.api_url, timeout=120)
            response.raise_for_status()
            data_text = response.text
            self.logger.debug("KMA raw response:\n{}".format(data_text))
        except Exception as e:
            self.logger.error(f"Error acquiring weather information: {e}")
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
            self.logger.error("No valid data found in the response.")
            return None
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
        # - If DB has data within the last 7 days, SKIP the initial weekly backfill.
        # - Otherwise, backfill up to 7 days (or since last data, whichever is smaller).
        if self.first_run:
            self.first_run = False
            week_sec = 7 * 86400
            do_backfill = True
            seconds_download = week_sec
            try:
                utc_now = datetime.datetime.utcnow()
                if self.latest_datetime:
                    # self.latest_datetime is stored as naive UTC (see get_new_data persist)
                    seconds_since_last = (utc_now - self.latest_datetime).total_seconds()
                    if 0 <= seconds_since_last <= week_sec:
                        # Recent data exists within 7 days → skip heavy initial backfill
                        self.logger.info("Recent data found in DB within 7 days; skipping initial weekly backfill.")
                        do_backfill = False
                    else:
                        # No recent data (or very old gap) → cap initial backfill to 7 days
                        seconds_download = min(max(0, seconds_since_last), week_sec) if seconds_since_last > 0 else week_sec
            except Exception:
                # On any error, fall back to a 7-day backfill to heal gaps
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
            self.logger.debug("URL: {}".format(self.api_url))
        else:
            self.logger.error("API key or coordinates are missing. Please save the latitude/longitude in the input settings.")
            return

        self.return_dict = copy.deepcopy(measurements_dict)
        # Align live measurement names with split option (to match backfill)
        try:
            split_precip = bool(_get_opt(self, 'split_precip_measurements', True))
        except Exception:
            split_precip = True
        if split_precip:
            self.return_dict[5]['measurement'] = 'precipitation_flag'
            self.return_dict[6]['measurement'] = 'precipitation_mm_15m'
        else:
            self.return_dict[5]['measurement'] = 'precipitation'
            self.return_dict[6]['measurement'] = 'precipitation'
        data = self.pre_fetch_data()
        if data is None:
            return

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
            self.value_set(0, ta)
        if self.is_enabled(1) and hm is not None:
            self.value_set(1, hm)
        if self.is_enabled(2) and pressure is not None:
            self.value_set(2, pressure)
        if self.is_enabled(3) and wd_10m is not None:
            self.value_set(3, wd_10m)
        if self.is_enabled(4) and ws_10m is not None:
            self.value_set(4, ws_10m)
        if self.is_enabled(5) and rn_ox is not None:
            self.value_set(5, rn_ox)
        if self.is_enabled(6) and rn_15m is not None:
            self.value_set(6, rn_15m)
        if self.is_enabled(7) and vs is not None:
            self.value_set(7, vs)
        if self.is_enabled(8) and sd_tot is not None:
            self.value_set(8, sd_tot)
        if self.is_enabled(9) and dew_point is not None:
            self.value_set(9, dew_point)

        return self.return_dict
