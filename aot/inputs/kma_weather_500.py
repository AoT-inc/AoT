# coding=utf-8
#
#  이 소프트웨어는 오픈소스 Mycodo 프로젝트(© Kyle T. Gabriel)를 기반으로
#  AoT 프로젝트 목적에 맞게 수정된 파생 버전입니다.
#  This file has been modified by AoT from the original Mycodo version.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#  Copyright (C) 2015-2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  본 파일은 GNU GPLv3 라이선스에 따라 배포됩니다.
#  원본 저작권 및 라이선스 조건은 아래에 명시되어 있습니다.
#
#  --------------------------------------------------------------
#  원본 파일 정보:
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
    0: {'measurement': 'temperature', 'unit': 'C', 'name': '기온'},
    1: {'measurement': 'humidity', 'unit': 'percent', 'name': '습도'},
    2: {'measurement': 'pressure', 'unit': 'hPa', 'name': '기압'},
    3: {'measurement': 'direction', 'unit': 'bearing', 'name': '풍향'},
    4: {'measurement': 'speed', 'unit': 'm_s', 'name': '풍속'},
    5: {'measurement': 'precipitation', 'unit': 'none', 'name': '비'},
    6: {'measurement': 'precipitation', 'unit': 'mm', 'name': '15분강수'},
    7: {'measurement': 'visibility', 'unit': 'km', 'name': '시정'},
    8: {'measurement': 'snowfall', 'unit': 'cm', 'name': '적설'},
    9: {'measurement': 'dewpoint', 'unit': 'C', 'name': '이슬점'}
}

INPUT_INFORMATION = {
    'input_name_unique': 'KMA_weather_500',
    'input_manufacturer': 'KMA',
    'input_name': '기상청 고해상도 500m',
    'input_name_short': '기상청 환경데이터',
    'measurements_dict': measurements_dict,
    'url_additional': 'https://apihub.kma.go.kr',
    'measurements_rescale': False,

    'message': '기상청 API 허브에서 무료 API 키를 발급받은 뒤, 입력 설정의 위치(위도/경도)에 따라 데이터를 요청합니다.'
               ' 참고: 대한민국 기상청 API는 하루 20000회 호출이 가능하며, 1회 호출당 1개의 관측지점 데이터를 반환합니다.',

    'options_enabled': [
        'measurements_select',
        'custom_channel_options',
        'pre_output'
    ],

    'custom_options': [
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': "API Key",
            'phrase': "기상청 API 허브에서 발급받은 API Key를 입력하세요."
        },
        {
            'id': 'period',
            'type': 'float',
            'default_value': 300,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': "측정 기간(초)",
            'phrase': "측정 주기를 초 단위로 입력하세요."
        }
    ],
    'custom_channel_options': [
        {
            'id': 'qc_enable',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': "품질검사(QC) 사용",
            'phrase': "명백한 이상치(예: 습도 0%, 기압 0hPa 등)를 무시하거나 보정합니다."
        },
        {
            'id': 'qc_hold_seconds',
            'type': 'float',
            'default_value': 1800,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': "QC 보정 유지시간(초)",
            'phrase': "이 시간 내의 마지막 정상값으로 대체합니다."
        },
        # --- Inserted manual backfill options here ---
        {
            'id': 'backfill_minutes',
            'type': 'float',
            'default_value': 1440,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': "수동 백필 기간(분)",
            'phrase': "사용자 요청 시 과거 이 기간만큼 데이터를 불러옵니다. 기본 1440분(1일)."
        },
        {
            'id': 'backfill_request',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': "지금 백필 실행",
            'phrase': "저장 후 활성화하면 즉시 백필을 1회 수행하고 자동으로 해제됩니다."
        },
        {
            'id': 'kma_tz_offset_hours',
            'type': 'float',
            'default_value': 9,
            'required': False,
            'name': "KMA 타임스탬프 오프셋(시간)",
            'phrase': "KMA 응답 시각이 로컬(KST,+9) 기준일 때 UTC로 저장하기 위해 빼줄 시간 (기본 9)."
        },
        {
            'id': 'split_precip_measurements',
            'type': 'bool',
            'default_value': True,
            'required': False,
            'name': "강수 계열 시계열 분리",
            'phrase': "강수 지표(rn_ox)와 15분 강수(rn_15m)를 서로 다른 측정명으로 기록해 충돌을 방지합니다."
        },
        {
            'id': 'qc_zero_accept_margin_deg',
            'type': 'float',
            'default_value': 3.0,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': "QC: 0°C 허용 범위(±°C)",
            'phrase': "직전 정상값이 0°C에서 이 범위 이내일 때만 0°C를 허용합니다. 기본 ±3°C."
        }
    ]
}


class InputModule(AbstractInput):
    """A sensor support class that gets high-resolution weather observation data from KMA API."""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)
        if not hasattr(self.input_dev, 'options'):
            self.input_dev.options = {}
        self.api_url = None
        self.api_key = None
        self.lon = None
        self.lat = None
        self.period = 600  # 기본값 600초
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
            try:
                self.setup_custom_options(INPUT_INFORMATION.get('custom_channel_options', []), input_dev)
            except Exception:
                pass
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
            self.logger.error("좌표가 설정되지 않았습니다. 입력 설정의 위치(위도/경도)를 먼저 저장하세요.")
            return

        now = datetime.datetime.now()
        tm1_dt = now - datetime.timedelta(minutes=minutes)
        tm1 = tm1_dt.strftime("%Y%m%d%H%M")
        tm2 = now.strftime("%Y%m%d%H%M")
        # Safety: Ensure tm1 < tm2 and window >= 5 minutes
        if tm1 >= tm2:
            self.logger.info("Backfill window collapsed (tm1>=tm2). Skipping.")
            return
        if minutes < 5:
            self.logger.info("Backfill window <5 minutes; skipping.")
            return
        itv = 5

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
            self.logger.error(f"Backfill request error: {e}")
            return

        lines = response.text.strip().split('\n')
        rows = []
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
            rows.append(row)

        if not rows:
            self.logger.info("No rows parsed for backfill window.")
            return

        rows.sort(key=lambda r: r['pub_timestamp'])
        latest_ts_seen = None
        rows_written = 0

        # QC options
        qc_enable = bool(_get_opt(self, 'qc_enable', True))
        qc_hold_seconds = float(_get_opt(self, 'qc_hold_seconds', 1800))

        for row in rows:
            # Build timestamp, convert KMA local to UTC
            try:
                ts_local = datetime.datetime.strptime(row['pub_timestamp'], "%Y%m%d%H%M")
                try:
                    tz_off = float(_get_opt(self, 'kma_tz_offset_hours', 9))
                except Exception:
                    tz_off = 9.0
                ts = (ts_local - datetime.timedelta(hours=tz_off)).replace(tzinfo=timezone.utc)  # store as UTC, tz-aware
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
        """API 호출 및 응답 파싱을 수행하여, 최신 데이터를 담은 딕셔너리를 반환합니다."""
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
            # YYYYMMDDHHMM 포맷이므로 문자열 비교로 최신 pub_timestamp 선택
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
        # Custom 옵션에서 값을 읽어옴 (now uses _get_opt)
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
            # 요청 시간: 지금 시간에서 5분 전부터 지금 시간까지의 데이터를 요청
            now = datetime.datetime.now()
            tm1_dt = now - datetime.timedelta(minutes=5)
            tm1 = tm1_dt.strftime("%Y%m%d%H%M")
            tm2 = now.strftime("%Y%m%d%H%M")
            # itv는 tm1과 tm2 사이의 시간(분)로, 여기서는 5분입니다.
            itv = 5

            self.api_url = (
                "https://apihub.kma.go.kr/api/typ01/url/sfc_nc_var.php"
                f"?tm1={tm1}&tm2={tm2}&lon={self.lon}&lat={self.lat}"
                f"&obs=ta,hm,wd_10m,ws_10m,pa,rn_ox,rn_15m,vs,sd_tot"
                f"&itv={itv}&help=0&authKey={self.api_key}"
            )
            self.logger.debug("URL: {}".format(self.api_url))
        else:
            self.logger.error("API key 또는 좌표가 없습니다. 입력 설정의 위도/경도를 저장하세요.")
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

        # 데이터를 분류하여 self.return_dict에 저장
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
