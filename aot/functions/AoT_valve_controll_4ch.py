# coding=utf-8
#
#  accumulated_temperature.py - Calculates daily GDD and cumulative accumulated temperature (GDD)
#
#  Copyright (C)
#
#  This file is part of AoT
#
#  AoT is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License.
#
#  Contact at aot-inc.com

import time

from flask_babel import lazy_gettext

from aot.databases.models import CustomController
from aot.databases.models import FunctionChannel
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl

from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon


# Minimal channel/measurement descriptors so at least 1 channel exists on first load
measurements_dict = {}
channels_dict = {
    0: {'name': 'Valve 1', 'enabled': [], 'time': [], 'time_sign': [], 'output': []},
    1: {'name': 'Valve 2', 'enabled': [], 'time': [], 'time_sign': [], 'output': []},
    2: {'name': 'Valve 3', 'enabled': [], 'time': [], 'time_sign': [], 'output': []},
    3: {'name': 'Valve 4', 'enabled': [], 'time': [], 'time_sign': [], 'output': []}
}

FUNCTION_INFORMATION = {
    'function_name_unique': 'valve_control_4ch',
    'function_name': 'AoT: 밸브제어 4ch',
    'function_name_short': '밸브제어 4ch',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'message': lazy_gettext('최대 4개 밸브를 순차 제어하고, 펌프를 밸브와 함께 작동 시키는 함수 입니다.'),

    'options_enabled': [
        'custom_options',
        'custom_channel_options',
        'channels_configure',
        'enable_actions',
        'measurements_configure'
    ],

    'custom_options': [
        {
            'id': 'period',
            'type': 'float',
            'default_value': 600,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('주기'), lazy_gettext('초')),
            'phrase': lazy_gettext('실행 주기, 시간(초 단위)')
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('시작 지연'), lazy_gettext('초')),
            'phrase': lazy_gettext('첫 실행 전에 대기할 시간(초)')
        },
        {
            'id': 'measurement_max_age',
            'type': 'integer',
            'default_value': 360,
            'required': True,
            'name': "{}: {} ({})".format(lazy_gettext("Measurement"), lazy_gettext("Max Age"),
                                         lazy_gettext("Seconds")),
            'phrase': lazy_gettext('측정값의 최대 허용 시간입니다.'),
        },
        {
            'id': 'min_runtime_sec',
            'type': 'integer',
            'default_value': 15,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('최소 작동시간'), lazy_gettext('초')),
            'phrase': lazy_gettext('이 시간(초) 미만의 밸브 동작은 무시됩니다.')
        },
        {
            'id': 'output_pump',
            'type': 'select_channel',
            'default_value': '',
            'required': True,
            'options_select': [
                'Output_Channels',
            ],
            'name': '펌프 출력',
            'phrase': lazy_gettext('펌프 제어에 사용할 출력을 선택합니다.')
        }
    ],
    'custom_channel_options': [
        {
            'id': 'enabled',
            'type': 'select',
            'default_value': 'False',
            'required': False,
            'options_select': [('True', lazy_gettext('사용')), ('False', lazy_gettext('미사용'))],
            'name': lazy_gettext('채널 사용'),
            'phrase': lazy_gettext('이 채널을 작동에 포함합니다.')
        },
        {
            'id': 'time',
            'type': 'select_measurement',
            'default_value': '',
            'required': True,
            'options_select': ['Input', 'Function', 'PID'],
            'name': lazy_gettext('입력-시간'),
            'phrase': lazy_gettext('해당 채널의 밸브 동작 시간을 가져올 측정값을 선택합니다.')
        },
        {
            'id': 'time_sign',
            'type': 'select',
            'default_value': 'positive',
            'required': True,
            'options_select': [('positive', '+양수'), ('negative', '-음수')],
            'name': lazy_gettext('시간해석'),
            'phrase': lazy_gettext('양수만 처리하거나 음수만 처리하도록 선택합니다.')
        },
        {
            'id': 'output',
            'type': 'select_channel',
            'default_value': '',
            'required': True,
            'options_select': ['Output_Channels'],
            'name': lazy_gettext('출력'),
            'phrase': lazy_gettext('이 채널의 밸브로 사용할 출력을 선택합니다.')
        }
    ],

}


class CustomModule(AbstractFunction):
    """
    Class to operate custom controller
    """
    def _resolve_output_device_id(self, ch_obj, fallback=None):
        """Return the OUTPUT (device) unique_id that owns this channel, mirroring remote_output logic.
        Priority:
        1) ch_obj.output_id (parent Output unique_id)
        2) ch_obj.output.unique_id
        3) ch_obj.device_id / ch_obj.device.unique_id (as last resort)
        """
        if ch_obj is None:
            return fallback
        try:
            oid = getattr(ch_obj, 'output_id', None)
            if oid:
                return oid
            out = getattr(ch_obj, 'output', None)
            if out is not None:
                oid = getattr(out, 'unique_id', None) or getattr(out, 'id', None)
                if oid:
                    return oid
            # very last resort: some deployments map device==output for on_off
            dev = getattr(ch_obj, 'device', None)
            if dev is not None:
                oid = getattr(dev, 'unique_id', None) or getattr(dev, 'device_id', None)
                if oid:
                    return oid
        except Exception:
            pass
        return fallback

    def _resolve_channel_index(self, ch_obj, fallback=None):
        """Return the numeric channel index (int) for this OutputChannel.
        Prefer ch_obj.channel; otherwise try DB lookup on OutputChannel by unique_id.
        """
        if ch_obj is None:
            return fallback
        try:
            idx = getattr(ch_obj, 'channel', None)
            if isinstance(idx, int):
                return idx
            if isinstance(idx, str) and idx.isdigit():
                return int(idx)
        except Exception:
            pass
        # DB fallback
        try:
            from aot.databases.models import OutputChannel as _OC
            entry = db_retrieve_table_daemon(_OC, unique_id=getattr(ch_obj, 'unique_id', None))
            if entry:
                val = getattr(entry, 'channel', None)
                if isinstance(val, int):
                    return val
                if isinstance(val, str) and val.isdigit():
                    return int(val)
        except Exception:
            pass
        return fallback

    # --- Helpers: parsing & safety ---
    def _parse_seconds_from_measurement(self, raw, sign_policy):
        """Parse seconds from a measurement value under a sign policy ('positive'/'negative').
        Returns (seconds:int, reason:str) where reason is 'ok' or the skip reason.
        """
        try:
            if isinstance(raw, (int, float)):
                v = float(raw)
            else:
                s = str(raw).strip()
                # Normalize Korean prefixes: "음수NN"->"-NN", "양수NN"->"+NN"
                if s.startswith('음수') and not s.lstrip().startswith('-'):
                    s = '-' + s.replace('음수', '', 1)
                elif s.startswith('양수') and not s.lstrip().startswith(('+', '-')):
                    s = '+' + s.replace('양수', '', 1)
                cleaned = []
                for ch in s:
                    if ch.isdigit() or ch in ['.', '-', '+']:
                        cleaned.append(ch)
                s_clean = ''.join(cleaned)
                v = float(s_clean)

            if sign_policy == 'negative':
                if v < 0:
                    return int(abs(v)), 'ok'
                return 0, 'filtered_positive_by_sign'
            # positive policy (default)
            if v > 0:
                return int(v), 'ok'
            return 0, 'filtered_negative_by_sign'
        except Exception:
            try:
                hint = str(raw)
                if len(hint) > 16:
                    hint = hint[:16] + '…'
            except Exception:
                hint = ''
            return 0, f'non_numeric_value:{hint}'

    def _clamp_seconds(self, seconds, max_cap):
        try:
            cap = int(max_cap)
            if cap > 0:
                return min(int(seconds), cap)
        except Exception:
            pass
        return int(seconds)

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.control = DaemonControl()

        # Placeholders that will be populated by setup_custom_options
        self.period = None  # seconds
        self.measurement_max_age = None

        # Per-valve measurement refs (auto-populated):
        # time_1_device_id, time_1_measurement_id, ... time_4_*
        # Sign options: time_1_sign .. time_4_sign
        # Outputs: output_1_device_id, output_1_channel_id, ... output_pump_*

        # Register all custom options at once (all merged in custom_options)
        custom_function = db_retrieve_table_daemon(CustomController, unique_id=self.unique_id)
        self.setup_custom_options(FUNCTION_INFORMATION['custom_options'], custom_function)
        self.options_channels = None
        self.output_channels_dyn = {}
        self.output_channels_dyn_ids = {}

        # Channels resolved in initialize()
        self.output_channels = [None, None, None, None]
        self.output_pump_channel = None

        # Simple scheduler: run once per period (seconds); honor start_offset on first run
        try:
            start_delay = int(getattr(self, 'start_offset', 0) or 0)
        except Exception:
            start_delay = 0
        self._next_run = time.time() + max(0, start_delay)
        self._in_cycle = False

        if not testing:
            self.try_initialize()

    def _safe_turn_off_channel(self, ch_obj, label=""):
        try:
            if ch_obj is None:
                return False
            out_id = self._resolve_output_device_id(ch_obj, fallback=None)
            ch_idx = self._resolve_channel_index(ch_obj, fallback=None)
            if out_id is None or ch_idx is None:
                return False
            try:
                self.control.output_on_off(out_id, "off", output_type='sec', amount=0, output_channel=ch_idx)
                return True
            except Exception as e:
                self.logger.error(f"[IrrigationControl] OFF at init failed: {label} err={e}")
                return False
        except Exception as e:
            self.logger.error(f"[IrrigationControl] OFF at init fatal: {label} err={e}")
            return False

    def initialize(self):
        # No internal scheduling by period_seconds; removed.

        # Resolve output channels from stored channel_ids
        self.output_channels = []
        for idx in range(1, 5):
            ch_id = getattr(self, f'output_{idx}_channel_id', None)
            ch = self.get_output_channel_from_channel_id(ch_id) if ch_id is not None else None
            self.output_channels.append(ch)
        pump_ch_id = getattr(self, 'output_pump_channel_id', None)
        self.output_pump_channel = self.get_output_channel_from_channel_id(pump_ch_id) if pump_ch_id is not None else None
        if self.output_pump_channel is None:
            try:
                pump_fallback_id = getattr(self, 'output_pump', None)
                if pump_fallback_id:
                    self.output_pump_channel = self.get_output_channel_from_channel_id(pump_fallback_id)
            except Exception:
                pass

        # --- Ensure all configured outputs start from OFF state (pump + valves) ---
        try:
            # Pump first (if configured)
            if self.output_pump_channel is not None:
                self._safe_turn_off_channel(self.output_pump_channel, label="pump")

            # Static 1~4 outputs resolved earlier
            for i, ch in enumerate(self.output_channels, start=1):
                if ch is not None:
                    self._safe_turn_off_channel(ch, label=f"valve_static_{i}")

            # Dynamic outputs if any (dedupe by (output_id, ch_idx))
            seen = set()
            try:
                for k, ch in (self.output_channels_dyn or {}).items():
                    if ch is None:
                        continue
                    # Resolve to pair for dedupe
                    out_id = self._resolve_output_device_id(ch, fallback=None)
                    ch_idx = self._resolve_channel_index(ch, fallback=None)
                    key = (out_id, ch_idx)
                    if out_id is None or ch_idx is None or key in seen:
                        continue
                    if self._safe_turn_off_channel(ch, label=f"valve_dyn_{k}"):
                        seen.add(key)
            except Exception:
                pass
        except Exception as e:
            self.logger.error(f"[IrrigationControl] init OFF sweep encountered an issue: {e}")


        # Load per-channel options (dynamic channels) similar to inputs
        try:
            function_channels = db_retrieve_table_daemon(FunctionChannel).\
                filter(FunctionChannel.function_id == self.unique_id).all()
            self.options_channels = self.setup_custom_channel_options_json(
                FUNCTION_INFORMATION['custom_channel_options'], function_channels)
            # Normalize options_channels: convert list-of-dicts to dict keyed by channel index
            if isinstance(self.options_channels, list):
                norm = {'enabled': {}, 'time': {}, 'time_sign': {}, 'output': {}, 'output_channel_id': {}}
                for i, row in enumerate(self.options_channels):
                    if not isinstance(row, dict):
                        continue
                    idx = row.get('index', i)
                    for k in ('enabled', 'time', 'time_sign', 'output', 'output_channel_id'):
                        if k in row:
                            norm[k][str(idx)] = row[k]
                self.options_channels = norm

            # If output values are dict-shaped, pull out an id field
            for k_map in ('output', 'output_channel_id'):
                m = self.options_channels.get(k_map, {})
                if isinstance(m, dict):
                    for kk, vv in list(m.items()):
                        if isinstance(vv, dict):
                            cid = vv.get('channel_id') or vv.get('output_channel_id') or vv.get('unique_id') or vv.get('id') or vv.get('channel')
                            if cid:
                                m[kk] = cid
                    self.options_channels[k_map] = m
            # Resolve output channel objects for dynamic channels (support both legacy and new keys)
            self.output_channels_dyn = {}
            self.output_channels_dyn_ids = {}
            out_ch_ids = self.options_channels.get('output_channel_id', {}) or self.options_channels.get('output', {})
            if isinstance(out_ch_ids, dict):
                for ch_key, ch_id in out_ch_ids.items():
                    self.output_channels_dyn_ids[ch_key] = ch_id
                    try:
                        self.output_channels_dyn[ch_key] = self.get_output_channel_from_channel_id(ch_id)
                    except Exception:
                        self.output_channels_dyn[ch_key] = None
        except Exception as e:
            self.logger.warning(f"[IrrigationControl] Dynamic channel options load failed: {e}")




    def loop(self):
        # Periodic scheduler: run once per period seconds (period provided by core/user option in seconds)
        try:
            period_sec = float(getattr(self, 'period', 0) or 0)
        except Exception:
            period_sec = 0
        if period_sec <= 0:
            period_sec = 1.0  # minimal backoff to avoid tight loop if misconfigured
        # Ensure measurement_max_age is not shorter than period (avoids stale filtering on every cycle)
        try:
            mma = getattr(self, 'measurement_max_age', None)
            if mma is not None and int(mma) < int(period_sec):
                self.logger.warning(
                    "[IrrigationControl] measurement_max_age (%ss) < period (%ss); adjusting to period",
                    mma, period_sec
                )
                self.measurement_max_age = int(period_sec)
        except Exception:
            pass
        # gate
        now = time.time()
        if now < getattr(self, '_next_run', 0):
            return
        if getattr(self, '_in_cycle', False):
            # Prevent overlap if previous cycle is still running
            return
        self._in_cycle = True
        try:
            # --- Dynamic channel handling: run channels defined via custom_channel_options ---
            dyn = self.options_channels if hasattr(self, 'options_channels') else None
            if isinstance(dyn, list):
                norm = {'enabled': {}, 'time': {}, 'time_sign': {}, 'output': {}, 'output_channel_id': {}}
                for i, row in enumerate(dyn):
                    if not isinstance(row, dict):
                        continue
                    idx = row.get('index', i)
                    for k in ('enabled', 'time', 'time_sign', 'output', 'output_channel_id'):
                        if k in row:
                            norm[k][str(idx)] = row[k]
                dyn = norm
            dyn_out_ch_objs = getattr(self, 'output_channels_dyn', {}) or {}
            dyn_out_ch_ids = (dyn.get('output_channel_id') or dyn.get('output') or {}) if isinstance(dyn, dict) else {}
            dyn_enabled = dyn.get('enabled') or {}
            def _is_enabled(k):
                v = dyn_enabled.get(k)
                if v is None:
                    try:
                        v = dyn_enabled.get(int(k))
                    except Exception:
                        v = None
                # Default to False if unset (safer default)
                if v is None:
                    return False
                # Accept common truthy forms
                try:
                    if isinstance(v, bool):
                        return v
                    if isinstance(v, (int, float)):
                        return v != 0
                    s = str(v).strip().lower()
                    return s in ('1', 'true', 'on', 'yes', 'y')
                except Exception:
                    return False
            if isinstance(dyn_out_ch_ids, dict):
                for kk, vv in list(dyn_out_ch_ids.items()):
                    if isinstance(vv, dict):
                        cid = vv.get('channel_id') or vv.get('output_channel_id') or vv.get('unique_id') or vv.get('id') or vv.get('channel')
                        if cid:
                            dyn_out_ch_ids[kk] = cid
            if not dyn or not isinstance(dyn, dict):
                return

            # Keys: support both legacy split maps and unified 'time'
            dyn_time = dyn.get('time') or {}
            dyn_time_dev = dyn.get('time_device_id') or {}
            dyn_time_meas = dyn.get('time_measurement_id') or {}
            dyn_sign = dyn.get('time_sign') or {}
            # Channel objects resolved in initialize(); prefer these over raw ids
            dyn_out_ch_objs = dyn_out_ch_objs

            def _key_index(k):
                try:
                    return int(k)
                except Exception:
                    # Non-integer keys are placed at the end
                    return 10**9

            # Merge keys from all channel maps (some deployments store keys as strings)
            key_sets = [dyn_time.keys(), dyn_time_dev.keys(), dyn_time_meas.keys(), dyn_sign.keys(), dyn_out_ch_objs.keys()]
            keys_allowed = list({str(k) for ks in key_sets for k in ks})
            # Sort by numeric index to ensure deterministic execution order
            keys_allowed.sort(key=_key_index)

            # Filter to keys that have BOTH a time reference and an output channel configured
            def _has_time_ref(k):
                m = dyn_time.get(k)
                if not m:
                    try:
                        m = dyn_time.get(int(k))
                    except Exception:
                        pass
                if m in (None, '', 'None'):
                    # try legacy split maps
                    md = dyn_time_dev.get(k)
                    mm = dyn_time_meas.get(k)
                    if md is None:
                        try:
                            md = dyn_time_dev.get(int(k))
                        except Exception:
                            pass
                    if mm is None:
                        try:
                            mm = dyn_time_meas.get(int(k))
                        except Exception:
                            pass
                    return bool(md and mm)
                return True

            def _has_output(k):
                ch = dyn_out_ch_objs.get(k)
                if ch is None:
                    try:
                        ch = dyn_out_ch_objs.get(int(k))
                    except Exception:
                        pass
                if ch is not None:
                    return True
                # fallback: accept presence of a channel id string
                cid = dyn_out_ch_ids.get(k)
                if cid is None:
                    try:
                        cid = dyn_out_ch_ids.get(int(k))
                    except Exception:
                        pass
                return bool(cid)

            keys_allowed = [k for k in keys_allowed if _is_enabled(k) and _has_time_ref(k) and _has_output(k)]
            if not keys_allowed:
                self._in_cycle = False
                self._next_run = now + period_sec
                return

            # Safety cap: per-valve max seconds = period / number of **enabled** valves
            try:
                candidates = dyn_enabled.keys() if isinstance(dyn_enabled, dict) else []
                enabled_keys_all = [str(k) for k in candidates if _is_enabled(str(k))]
            except Exception:
                enabled_keys_all = []
            num_enabled = len(enabled_keys_all)
            if num_enabled <= 0:
                # Fallback to actually schedulable keys if no explicit enabled map is present
                num_enabled = len(keys_allowed)
            max_per_valve_sec = int(period_sec / num_enabled) if num_enabled > 0 else 0

            # --- Build plan (key, None, out_ch_obj, seconds) ---
            plan = []
            reasons_map = {}

            def _resolve_out_ch(k):
                ch = dyn_out_ch_objs.get(k)
                if ch is None:
                    try:
                        ch = dyn_out_ch_objs.get(int(k))
                    except Exception:
                        pass
                if ch is None:
                    # try resolving from stored channel id on the fly
                    cid = dyn_out_ch_ids.get(k)
                    if cid is None:
                        try:
                            cid = dyn_out_ch_ids.get(int(k))
                        except Exception:
                            cid = None
                    if cid:
                        try:
                            ch = self.get_output_channel_from_channel_id(cid)
                        except Exception:
                            ch = None
                return ch

            for ch_key in keys_allowed:
                if not _is_enabled(ch_key):
                    reasons_map[str(ch_key)] = 'disabled'
                    continue

                # Resolve measurement identifiers
                dev_id = dyn_time_dev.get(ch_key)
                if dev_id is None:
                    try:
                        dev_id = dyn_time_dev.get(int(ch_key))
                    except Exception:
                        pass
                meas_id = dyn_time_meas.get(ch_key)
                if meas_id is None:
                    try:
                        meas_id = dyn_time_meas.get(int(ch_key))
                    except Exception:
                        pass
                # Fallback: unified 'time' may store a measurement id directly
                if meas_id is None:
                    meas_id = dyn_time.get(ch_key)
                    if meas_id is None:
                        try:
                            meas_id = dyn_time.get(int(ch_key))
                        except Exception:
                            pass
                # Support dict-shaped unified time entries like {'device_id': '...', 'measurement_id': '...'}
                if (not dev_id or not meas_id) and isinstance(meas_id, dict):
                    try:
                        dev_id = meas_id.get('device_id', dev_id)
                        meas_id = meas_id.get('measurement_id', meas_id)
                    except Exception:
                        pass
                if isinstance(meas_id, dict):
                    # Accept {'device_id': '...', 'measurement_id': '...'} or {'id': '...'}
                    dev_id = meas_id.get('device_id', dev_id)
                    meas_id = meas_id.get('measurement_id') or meas_id.get('id') or meas_id

                # Resolve output channel OBJECT
                out_ch = _resolve_out_ch(ch_key)

                # Normalize sign
                sign = dyn_sign.get(ch_key)
                if sign is None:
                    try:
                        sign = dyn_sign.get(int(ch_key))
                    except Exception:
                        sign = None
                if sign in ('+양수', '+', 'pos', 'positive', None, ''):
                    sign = 'positive'
                elif sign in ('-음수', '-', 'neg', 'negative'):
                    sign = 'negative'
                else:
                    sign = 'positive'

                # Fetch last measurement
                last = None
                if dev_id and meas_id:
                    try:
                        last = self.get_last_measurement(dev_id, meas_id, max_age=self.measurement_max_age)
                    except Exception:
                        last = None
                if last is None and meas_id:
                    try:
                        if hasattr(self, 'get_last_measurement_by_measurement_id'):
                            last = self.get_last_measurement_by_measurement_id(meas_id, max_age=self.measurement_max_age)
                    except Exception:
                        last = None

                if last is None:
                    reasons_map[str(ch_key)] = 'no_recent_measurement'
                    continue

                raw_value = last.get('value') if isinstance(last, dict) else last
                sec, reason = self._parse_seconds_from_measurement(raw_value, sign)
                if reason != 'ok':
                    reasons_map[str(ch_key)] = reason
                    continue

                plan.append((ch_key, None, out_ch, int(sec)))

            # --- Build final sequential execution plan with min/max filtering ---
            filtered = []
            total_sec = 0
            try:
                min_runtime_sec = int(getattr(self, 'min_runtime_sec', 15) or 0)
            except Exception:
                min_runtime_sec = 15
            if min_runtime_sec < 0:
                min_runtime_sec = 0

            for item in plan:
                if len(item) != 4:
                    continue
                k, a, b, sec = item
                try:
                    sec = int(sec)
                except Exception:
                    continue
                if sec < min_runtime_sec:
                    reasons_map[str(k)] = f'skipped_below_min_runtime({sec}s < {min_runtime_sec}s)'
                    continue
                if max_per_valve_sec > 0 and sec > max_per_valve_sec:
                    sec = self._clamp_seconds(sec, max_per_valve_sec)
                if sec <= 0:
                    reasons_map[str(k)] = 'zero_after_clamp'
                    continue
                filtered.append((k, a, b, sec))
                total_sec += sec

            if not filtered:
                self._in_cycle = False
                self._next_run = now + period_sec
                return

            # Optional: keep within period budget (leave 1s guard)
            if total_sec > int(period_sec) - 1:
                scaled = []
                remain = int(period_sec) - 1
                if remain <= 0:
                    self.logger.warning("[IrrigationControl] total_sec(%s) > period(%s). Skipping cycle.", total_sec, period_sec)
                    self._in_cycle = False
                    self._next_run = now + period_sec
                    return
                ratio = float(remain) / float(total_sec)
                total_sec = 0
                for (k, a, b, sec) in filtered:
                    new_sec = max(min_runtime_sec, int(sec * ratio))
                    if max_per_valve_sec > 0:
                        new_sec = self._clamp_seconds(new_sec, max_per_valve_sec)
                    if new_sec < min_runtime_sec:
                        reasons_map[str(k)] = 'dropped_after_scaling'
                        continue
                    scaled.append((k, a, b, new_sec))
                    total_sec += new_sec
                filtered = scaled
                if not filtered:
                    self._in_cycle = False
                    self._next_run = now + period_sec
                    return

            # --- Resolve pump output id/channel ---
            pump_out_id = self._resolve_output_device_id(self.output_pump_channel, fallback=None)
            pump_ch_idx = self._resolve_channel_index(self.output_pump_channel, fallback=None)

            # --- Turn pump ON for the entire total_sec, then sequentially run valves ---
            pump_started = False
            if pump_out_id is not None and pump_ch_idx is not None:
                try:
                    self.control.output_on_off(pump_out_id, "on", output_type='sec', amount=total_sec, output_channel=pump_ch_idx)
                    pump_started = True
                except Exception as e:
                    self.logger.error("[IrrigationControl] Failed to turn pump ON: %s", e)
                    # Safety: do not run valves if pump couldn't start
                    self._in_cycle = False
                    self._next_run = now + period_sec
                    return

            def _valve_on_for_sec(a, b, sec):
                try:
                    if a is None:
                        ch_obj = b
                        out_id = self._resolve_output_device_id(ch_obj, fallback=None)
                        ch_idx = self._resolve_channel_index(ch_obj, fallback=None)
                    else:
                        out_id, ch_idx = a, b
                    if out_id is None or ch_idx is None:
                        return False
                    self.control.output_on_off(out_id, "on", output_type='sec', amount=int(sec), output_channel=int(ch_idx))
                    return True
                except Exception as e:
                    self.logger.error("[IrrigationControl] Valve ON failed: %s", e)
                    return False

            for (_, a, b, sec) in filtered:
                _ = _valve_on_for_sec(a, b, sec)
                time.sleep(max(0, int(sec)))

            # --- Ensure everything is OFF at the end (pump + all candidate valves) ---
            try:
                if pump_started and pump_out_id is not None and pump_ch_idx is not None:
                    self.control.output_on_off(pump_out_id, "off", output_type='sec', amount=0, output_channel=pump_ch_idx)
            except Exception:
                pass

            try:
                seen = set()
                def _off_pair(a, b):
                    if a is None:
                        ch_obj = b
                        out_id = self._resolve_output_device_id(ch_obj, fallback=None)
                        ch_idx = self._resolve_channel_index(ch_obj, fallback=None)
                    else:
                        out_id, ch_idx = a, b
                    if out_id is None or ch_idx is None:
                        return
                    key = (out_id, ch_idx)
                    if key in seen:
                        return
                    seen.add(key)
                    self.control.output_on_off(out_id, "off", output_type='sec', amount=0, output_channel=ch_idx)

                for (_, a, b, _) in filtered:
                    _off_pair(a, b)
            except Exception:
                pass

            self._in_cycle = False
            self._next_run = time.time() + period_sec
            return
