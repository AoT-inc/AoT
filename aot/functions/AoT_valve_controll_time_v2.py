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
import re

from flask_babel import lazy_gettext

from aot.databases.models import CustomController
from aot.databases.models import FunctionChannel
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl

from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon


# Minimal channel/measurement descriptors so at least 1 channel exists on first load
MAX_CHANNELS = 16
measurements_dict = {}
channels_dict = {i: {} for i in range(1, MAX_CHANNELS + 1)}

FUNCTION_INFORMATION = {
    'function_name_unique': 'valve_control_v2',
    'function_name': 'AoT: 밸브제어 v2',
    'function_name_short': '밸브제어 v2',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,

    'message': lazy_gettext(
        '최대 16개 밸브를 순차 제어하고, 펌프를 총합 시간만큼 동작하는 관수 제어입니다.\n'
        '사용 방법: \n'
        '1) 입력이 있으면 센서 값(부호 무시, 절댓값 초)으로 작동 시간을 결정합니다.\n'
        '2) 입력 값이 없으면 작동시간(분)을 사용합니다.\n'
        '3) 입력도 없고 작동시간이 0이면 해당 채널은 스킵합니다.\n'
        '4) 최소 작동시간 미만은 무시 됩니다.\n'
        '5) 펌프 사용 여부를 선택할 수 있습니다.\n'
        '6) 초기화 시 장치들을 OFF 상태로 만들 수 있습니다.'
    ),

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
            'id': 'start_time',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('시작 시간'),
            'phrase': lazy_gettext('HH:MM 또는 HHMM 형식. 비워두면 제한 없음.')
        },
        {
            'id': 'end_time',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('종료 시간'),
            'phrase': lazy_gettext('HH:MM 또는 HHMM 형식. 비워두면 제한 없음.')
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
            'id': 'overlap_sec',
            'type': 'float',
            'default_value': 1.0,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('밸브 전환 오버랩'), lazy_gettext('초')),
            'phrase': lazy_gettext('밸브→밸브 전환 시 겹치는 시간(초). 0이면 겹침 없이 전환합니다.')
        },
        {
            'id': 'pump_lead_sec',
            'type': 'float',
            'default_value': 0.8,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('펌프 프라이밍'), lazy_gettext('초')),
            'phrase': lazy_gettext('밸브 시작 전 펌프를 미리 켜 두는 시간(초).')
        },
        {
            'id': 'pump_tail_sec',
            'type': 'float',
            'default_value': 0.8,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('펌프 플러시'), lazy_gettext('초')),
            'phrase': lazy_gettext('마지막 밸브 종료 후 펌프를 잠시 더 유지하는 시간(초).')
        },
        {
            'id': 'pump_overlap_sec',
            'type': 'float',
            'default_value': 1.0,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('펌프 오버랩'), lazy_gettext('초')),
            'phrase': lazy_gettext('세트 간 전환 시 펌프를 끄지 않고 유지하는 시간(초). 밸브 오버랩 이상을 권장.')
        },
        {
            'id': 'use_pump',
            'type': 'select',
            'default_value': 'True',
            'required': True,
            'options_select': [('True', lazy_gettext('사용')), ('False', lazy_gettext('미사용'))],
            'name': lazy_gettext('펌프 사용'),
            'phrase': lazy_gettext('펌프를 사용할지 여부를 선택합니다.')
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
        },
        {
            'id': 'init_off',
            'type': 'select',
            'default_value': 'True',
            'required': True,
            'options_select': [('True', lazy_gettext('예')), ('False', lazy_gettext('아니오'))],
            'name': lazy_gettext('초기화 시 OFF'),
            'phrase': lazy_gettext('초기화 실행 시 펌프와 등록된 밸브들에 OFF 명령을 일괄 전송합니다.')
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
            'required': False,
            'options_select': ['Input', 'Function', 'PID'],
            'name': lazy_gettext('입력-시간'),
            'phrase': lazy_gettext('해당 채널의 밸브 동작 시간을 가져올 측정값을 선택합니다.')
        },
        {
            'id': 'output',
            'type': 'select_channel',
            'default_value': '',
            'required': True,
            'options_select': ['Output_Channels'],
            'name': lazy_gettext('출력'),
            'phrase': lazy_gettext('이 채널의 밸브로 사용할 출력을 선택합니다.')
        },
        {
            'id': 'duration_min',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': "{} ({})".format(lazy_gettext('작동시간'), lazy_gettext('분')),
            'phrase': lazy_gettext('이 채널의 밸브를 작동할 시간(분 단위)입니다. (채널 미사용 시 비워두어도 됩니다)')
        },
    ],

}


class CustomModule(AbstractFunction):
    """
    Class to operate custom controller
    """
    class _Cancelled(Exception):
        pass

    def _check_cancel(self):
        # Cooperative preemption: allow immediate stop mid-set when self.running is cleared
        if not getattr(self, 'running', True):
            raise self._Cancelled()
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
    def _send_off(self, out_id, ch_idx, label=""):
        """Turn OFF a channel, preferring DaemonControl.output_off() when available.
        Falls back to legacy output_on_off() variants for maximum compatibility.
        Returns True if any attempt succeeds.
        """
        if out_id is None or ch_idx is None:
            return False
        # 0) Preferred: dedicated output_off API (simple and explicit)
        try:
            if hasattr(self.control, 'output_off'):
                self.control.output_off(out_id, output_channel=ch_idx)
                return True
        except Exception as e:
            self.logger.debug(f"[IrrigationControl] output_off() failed ({label}): {e}")
        # 1) on_off semantic
        try:
            self.control.output_on_off(out_id, "off", output_type='on_off', amount=0, output_channel=ch_idx)
            return True
        except Exception as e:
            self.logger.debug(f"[IrrigationControl] OFF on_off failed ({label}): {e}")
        # 2) sec semantic with 0 seconds
        try:
            self.control.output_on_off(out_id, "off", output_type='sec', amount=0, output_channel=ch_idx)
            return True
        except Exception as e:
            self.logger.debug(f"[IrrigationControl] OFF sec failed ({label}): {e}")
        # 3) No output_type
        try:
            self.control.output_on_off(out_id, "off", output_channel=ch_idx)
            return True
        except Exception as e:
            self.logger.error(f"[IrrigationControl] OFF all attempts failed ({label}): {e}")
            return False

    # --- Helpers: parsing & safety ---
    def _parse_seconds_from_measurement(self, raw):
        """Return (abs seconds:int, reason:str). Accepts number or string; extracts first numeric token.
        Examples: -5 -> 5, "음수10초" -> 10, "+12.7s" -> 13.
        """
        try:
            # Fast path for numeric inputs
            if isinstance(raw, (int, float)):
                return int(round(abs(float(raw)))), 'ok'

            # String path: normalize simple Korean prefixes, then regex-extract first number
            s = str(raw).strip()
            if s.startswith('음수'):
                s = '-' + s[2:]
            elif s.startswith('양수'):
                s = '+' + s[2:]

            m = re.search(r"[-+]?\d+(?:\.\d+)?", s)
            if not m:
                hint = s if len(s) <= 16 else s[:16] + '…'
                return 0, f'non_numeric_value:{hint}'

            v = float(m.group(0))
            return int(round(abs(v))), 'ok'
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

    def _extract_value(self, last):
        if last is None:
            return None
        if isinstance(last, dict):
            for k in ('value', 'last_value', 'measurement'):
                if k in last:
                    return last[k]
        if isinstance(last, (list, tuple)) and len(last) >= 2:
            return last[1]
        return last

    def _parse_hhmm_text_to_seconds(self, txt):
        """Parse 'HH:MM' or 'HHMM' (ASCII or fullwidth digits/colon) into seconds since midnight.
        Returns int seconds or None if invalid.
        """
        try:
            if txt is None:
                return None
            s = str(txt).strip()
            if not s:
                return None
            # Normalize fullwidth digits/colon to ASCII
            trans = str.maketrans({
                '０':'0','１':'1','２':'2','３':'3','４':'4','５':'5','６':'6','７':'7','８':'8','９':'9','：':':'
            })
            s = s.translate(trans)
            s = s.replace(' ', '')
            if ':' in s:
                hh, mm = s.split(':', 1)
            else:
                # HHMM
                if len(s) not in (3,4):
                    return None
                hh, mm = s[:-2], s[-2:]
            if not (hh.isdigit() and mm.isdigit()):
                return None
            h = int(hh)
            m = int(mm)
            if not (0 <= h <= 23 and 0 <= m <= 59):
                return None
            return h*3600 + m*60
        except Exception:
            return None

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
        self.max_channels = MAX_CHANNELS
        self.output_channels = [None] * self.max_channels
        self.output_pump_channel = None

        # Simple scheduler: run once per period (seconds); honor start_offset on first run
        try:
            start_delay = int(getattr(self, 'start_offset', 0) or 0)
        except Exception:
            start_delay = 0
        self._next_run = time.time() + max(0, start_delay)
        self._in_cycle = False
        # Base stop flag handled by AbstractFunction.stop_function()
        self.running = True

        if not testing:
            self.try_initialize()

    def _sync_logger_level(self):
        """Keep logger level aligned with Function.log_level_debug with minimal overhead."""
        try:
            fn = getattr(self, 'function', None)
            if not fn:
                return
            want_debug = bool(getattr(fn, 'log_level_debug', False))
            cur = self.logger.getEffectiveLevel()
            if want_debug and cur != 10:  # logging.DEBUG
                self.logger.setLevel(10)
            elif not want_debug and cur != 20:  # logging.INFO
                self.logger.setLevel(20)
        except Exception:
            pass

    def stop_function(self):
        """Called when Function is deactivated.
        Standard stop flag + immediate OFF sweep (force) for safety.
        """
        # 1) Signal loops to exit
        self.running = False

        # Immediate hard kill to cancel any duration-based timers
        try:
            self._emergency_off_now()
        except Exception:
            pass

        # 2) Aggressive OFF sweep for all configured outputs (pump + valves)
        try:
            pairs = self._collect_all_configured_outputs(include_unused=True)
        except Exception:
            pairs = set()
        try:
            if pairs:
                attempted, success = self._off_sweep(pairs, only_if_on=False, label='stop')
                self.logger.info(f"[IrrigationControl] Stop OFF sweep (force): {success}/{attempted} succeeded")
        except Exception as e:
            self.logger.error(f"[IrrigationControl] Stop OFF sweep encountered an issue: {e}")
    def _emergency_off_now(self):
        """Immediate best-effort OFF for pump + all configured outputs. Safe to call anywhere."""
        try:
            pairs = []
            # Pump (if resolvable)
            if getattr(self, 'output_pump_channel', None) is not None:
                oid = self._resolve_output_device_id(self.output_pump_channel, None)
                chx = self._resolve_channel_index(self.output_pump_channel, None)
                if oid is not None and chx is not None:
                    pairs.append((oid, chx))
            # All configured outputs (deduped)
            all_pairs = self._collect_all_configured_outputs(include_unused=True)
            for p in all_pairs:
                if p not in pairs:
                    pairs.append(p)
            for (oid, chx) in pairs:
                try:
                    self._switch(oid, chx, 'off', label='emergency')
                except Exception:
                    continue
        except Exception:
            pass

    def listener(self, message):
        """Handle external stop/emergency events from the controller."""
        try:
            # Normalize message to string for robust matching
            text = ''
            if message is None:
                text = ''
            elif isinstance(message, dict):
                try:
                    text = ' '.join(str(v).lower() for v in message.values())
                except Exception:
                    text = str(message).lower()
            else:
                text = str(message).lower()
            # Detect emergency/stop/deactivate intents
            if any(tok in text for tok in ('emergency', 'e-stop', 'estop', 'stop', 'deactivate', 'shutdown')):
                self.logger.warning('[IrrigationControl] listener: emergency/stop detected → killing outputs now')
                self.running = False
                self._emergency_off_now()
        except Exception as e:
            self.logger.error(f"[IrrigationControl] listener() error: {e}")

    def _safe_turn_off_channel(self, ch_obj, label=""):
        try:
            if ch_obj is None:
                return False
            out_id = self._resolve_output_device_id(ch_obj, fallback=None)
            ch_idx = self._resolve_channel_index(ch_obj, fallback=None)
            if out_id is None or ch_idx is None:
                return False
            if self._send_off(out_id, ch_idx, label=f"{label}_safe"):
                return True
            return False
        except Exception as e:
            self.logger.error(f"[IrrigationControl] OFF at init fatal: {label} err={e}")
            return False

    def _off_by_channel_id(self, channel_unique_id, label=""):
        """Turn OFF using OutputChannel unique_id directly (when channel object is unavailable)."""
        try:
            channel_unique_id = self._coerce_channel_id(channel_unique_id)  # ⬅️ 추가
            if not channel_unique_id:
                return False
            from aot.databases.models import OutputChannel as _OC
            row = db_retrieve_table_daemon(_OC, unique_id=channel_unique_id)
            if not row:
                return False
            out_id = getattr(row, 'output_id', None) or getattr(row, 'device_id', None)
            ch_idx = getattr(row, 'channel', None)
            if isinstance(ch_idx, str) and ch_idx.isdigit():
                ch_idx = int(ch_idx)
            # If channel index unknown, choose 0 or the smallest existing channel for that output
            if out_id is not None and ch_idx is None:
                try:
                    rows = db_retrieve_table_daemon(_OC).filter(_OC.output_id == out_id).all()
                    if rows:
                        preferred = None
                        smallest = None
                        for r in rows:
                            rc = getattr(r, 'channel', None)
                            if isinstance(rc, str) and rc.isdigit():
                                rc = int(rc)
                            if rc == 0:
                                preferred = 0
                                break
                            if isinstance(rc, int):
                                if smallest is None or rc < smallest:
                                    smallest = rc
                        ch_idx = 0 if preferred == 0 else smallest
                except Exception:
                    pass
            if ch_idx is None:
                ch_idx = 0
            if out_id is None:
                return False
            return self._send_off(out_id, ch_idx, label=f"{label}_by_chid")
        except Exception as e:
            self.logger.error(f"[IrrigationControl] OFF by channel_id failed: {label} err={e}")
            return False

    def _off_by_output_id(self, output_unique_id, label=""):
        """Turn OFF the preferred (0) or smallest channel for a given Output unique_id."""
        try:
            if not output_unique_id:
                return False
            from aot.databases.models import OutputChannel as _OC
            rows = db_retrieve_table_daemon(_OC).filter(_OC.output_id == output_unique_id).all()
            if not rows:
                return False
            preferred = None
            smallest = None
            for r in rows:
                rc = getattr(r, 'channel', None)
                if isinstance(rc, str) and rc.isdigit():
                    rc = int(rc)
                if rc == 0:
                    preferred = 0
                    break
                if isinstance(rc, int):
                    if smallest is None or rc < smallest:
                        smallest = rc
            ch_idx = 0 if preferred == 0 else smallest
            if ch_idx is None:
                return False
            return self._send_off(output_unique_id, ch_idx, label=f"{label}_by_outid")
        except Exception as e:
            self.logger.error(f"[IrrigationControl] OFF by output_id failed: {label} err={e}")
            return False

    def _coerce_channel_id(self, ch_id):
        """Normalize channel identifier to a usable unique_id string. Returns None if not resolvable."""
        if ch_id is None:
            return None
        # Primitive types first
        if isinstance(ch_id, int):
            return str(ch_id)
        if isinstance(ch_id, str):
            s = ch_id.strip()
            return s or None
        # Mapping/dict shapes
        if isinstance(ch_id, dict):
            for k in ('channel_id', 'output_channel_id', 'unique_id', 'id', 'channel'):
                v = ch_id.get(k)
                if v is None or isinstance(v, dict):
                    continue
                if isinstance(v, int):
                    return str(v)
                if isinstance(v, str):
                    v = v.strip()
                    if v:
                        return v
            return None
        # Fallback to string cast
        try:
            s = str(ch_id).strip()
            return s or None
        except Exception:
            return None

    def _truthy(self, v, default=False):
        """Return True/False for typical truthy strings/numbers; fallback to default when unset."""
        if v is None:
            return default
        if isinstance(v, bool):
            return v
        if isinstance(v, (int, float)):
            return v != 0
        try:
            s = str(v).strip().lower()
            return s in ('1', 'true', 'on', 'yes', 'y')
        except Exception:
            return default

    # --- State cache for output status (TTL ~3s) ---
    _status_cache_ttl = 3.0
    _status_cache = {}
    # Cache/Status metrics (low-noise)
    _status_cache_hits = 0
    _status_cache_misses = 0
    _status_driver_queries = 0
    _status_log_mod = 200  # log every 200 lookups

    def _log_cache_stats_if_needed(self):
        try:
            total = int(self._status_cache_hits + self._status_cache_misses)
            if total > 0 and (total % int(self._status_log_mod)) == 0:
                self.logger.debug(
                    "[IrrigationControl] status-cache stats: hits=%s misses=%s driver_queries=%s",
                    self._status_cache_hits, self._status_cache_misses, self._status_driver_queries
                )
        except Exception:
            pass

    def _cache_key(self, out_id, ch_idx):
        try:
            return f"{out_id}:{int(ch_idx)}"
        except Exception:
            return f"{out_id}:{ch_idx}"

    def _cache_set(self, out_id, ch_idx, state):
        try:
            self._status_cache[self._cache_key(out_id, ch_idx)] = (state, time.time())
        except Exception:
            pass

    def _cache_get(self, out_id, ch_idx):
        try:
            st, ts = self._status_cache.get(self._cache_key(out_id, ch_idx), (None, None))
            if st is None or ts is None:
                return None
            if (time.time() - ts) <= self._status_cache_ttl:
                return st
        except Exception:
            pass
        return None

    def _normalize_state(self, v):
        if v is None:
            return 'none'
        # Dicts from some drivers: {'state': 'ON'} or {'value': 1}
        try:
            if isinstance(v, dict):
                for k in ('state', 'status', 'value', 'on', 'power'):
                    if k in v:
                        return self._normalize_state(v[k])
        except Exception:
            pass
        # Booleans
        if isinstance(v, bool):
            return 'on' if v else 'off'
        # Numbers: >0 -> on, ==0 -> off, <0 -> off (conservative)
        if isinstance(v, (int, float)):
            try:
                return 'on' if float(v) > 0 else 'off'
            except Exception:
                return 'none'
        # Strings and other types
        try:
            s = str(v).strip().lower()
            if s in ('on', 'off', 'none'):
                return s
            if s in ('1', 'true', 'yes', 'y', 'up', 'high', 'open', 'active', 'enabled'):
                return 'on'
            if s in ('0', 'false', 'no', 'n', 'down', 'low', 'close', 'closed', 'inactive', 'disabled'):
                return 'off'
        except Exception:
            pass
        return 'none'

    def _get_output_state(self, out_id, ch_idx):
        """Return 'on' | 'off' | 'none'.
        Priority: driver status -> recent cache -> 'none'.
        """
        if out_id is None or ch_idx is None:
            return 'none'
        # 1) Driver-provided status
        try:
            if hasattr(self.control, 'output_status'):
                self._status_driver_queries += 1
                st = self.control.output_status(out_id, output_channel=ch_idx)
                stn = self._normalize_state(st)
                if stn != 'none':
                    self._cache_set(out_id, ch_idx, stn)
                    self._log_cache_stats_if_needed()
                    return stn
        except Exception:
            pass
        # 2) Cache fallback
        c = self._cache_get(out_id, ch_idx)
        if c is not None:
            self._status_cache_hits += 1
            self._log_cache_stats_if_needed()
            return self._normalize_state(c)
        # 3) Unknown
        self._status_cache_misses += 1
        self._log_cache_stats_if_needed()
        return 'none'

    def _switch(self, out_id, ch_idx, mode, amount_sec=0, label=''):
        """Unified ON/OFF with retries, multiple driver fallbacks, and post-verify.
        mode: 'on' | 'off'. Returns True on success.
        On success, updates state cache immediately.
        """
        if out_id is None or ch_idx is None:
            return False
        tries = 3
        backoff = 0.1
        for attempt in range(tries):
            try:
                if mode == 'off':
                    ok = False
                    # Preferred dedicated API
                    try:
                        if hasattr(self.control, 'output_off'):
                            self.control.output_off(out_id, output_channel=ch_idx)
                            ok = True
                    except Exception:
                        ok = False
                    if not ok:
                        # Fallbacks
                        for args in (
                            dict(cmd='off', output_type='on_off', amount=0, output_channel=ch_idx),
                            dict(cmd='off', output_type='sec', amount=0, output_channel=ch_idx),
                            dict(cmd='off', output_channel=ch_idx),
                        ):  # try variants
                            try:
                                self.control.output_on_off(out_id, args.get('cmd'),
                                                           output_type=args.get('output_type'),
                                                           amount=args.get('amount'),
                                                           output_channel=args.get('output_channel'))
                                ok = True
                                break
                            except Exception:
                                ok = False
                    # Post-verify (best-effort)
                    if ok:
                        time.sleep(0.05)
                        st = self._get_output_state(out_id, ch_idx)
                        if st == 'on':
                            # Try once more to ensure OFF
                            try:
                                if hasattr(self.control, 'output_off'):
                                    self.control.output_off(out_id, output_channel=ch_idx)
                                else:
                                    self.control.output_on_off(out_id, 'off', output_channel=ch_idx)
                                time.sleep(0.03)
                                st = self._get_output_state(out_id, ch_idx)
                            except Exception:
                                pass
                        if st in ('off', 'none'):
                            self._cache_set(out_id, ch_idx, 'off')
                            return True
                else:  # mode == 'on'
                    ok = False
                    # 1) Dedicated API if available
                    try:
                        if hasattr(self.control, 'output_on'):
                            self.control.output_on(out_id, output_channel=ch_idx)
                            ok = True
                    except Exception:
                        ok = False
                    # 2) Generic ON without duration
                    if not ok:
                        try:
                            self.control.output_on_off(out_id, 'on', output_type='on_off', amount=None, output_channel=ch_idx)
                            ok = True
                        except Exception:
                            ok = False
                    # 3) Duration-based fallback
                    if not ok:
                        amt = float(amount_sec or 0)
                        if amt <= 0:
                            amt = 1.0  # minimal pulse
                        try:
                            self.control.output_on_off(out_id, 'on', output_type='sec', amount=amt, output_channel=ch_idx)
                            ok = True
                        except Exception:
                            ok = False
                    # Post-verify (best-effort)
                    if ok:
                        time.sleep(0.05)
                        st = self._get_output_state(out_id, ch_idx)
                        if st in ('on', 'none'):
                            self._cache_set(out_id, ch_idx, 'on')
                            return True
            except Exception:
                pass
            if attempt < tries - 1:
                time.sleep(backoff * (attempt + 1))
        return False

    def _ensure_on(self, out_id, ch_idx, label=''):
        """Best-effort ON (non-latching). Returns True if ON."""
        try:
            if out_id is None or ch_idx is None:
                return False
            if self._switch(out_id, ch_idx, 'on', amount_sec=0, label=f"{label}_on"):
                return True
        except Exception:
            pass
        return False

    def _sleep_exact(self, seconds):
        """Sleep for `seconds` in small chunks; abort immediately if cancelled.
        - Checks self.running every 10–20ms for fast emergency-stop.
        - Raises _Cancelled to unwind to the orchestrator which will OFF-sweep.
        """
        try:
            if seconds is None:
                return
            target = time.monotonic() + max(0.0, float(seconds))
            # Use progressively larger chunks but keep quick responsiveness
            while True:
                self._check_cancel()
                now = time.monotonic()
                remain = target - now
                if remain <= 0:
                    return
                # short, fixed granularity for responsiveness
                chunk = 0.02 if remain > 0.02 else remain
                time.sleep(chunk)
        except self._Cancelled:
            raise
        except Exception:
            # Fallback simple sleep but still allow a last preemption check
            self._check_cancel()
            time.sleep(max(0.0, float(seconds)))

    def _run_valve_pump_set(self, pump_out_id, pump_ch_idx, valve_out_id, valve_ch_idx,
                             valve_sec, pump_lead, pump_tail,
                             valve_overlap_next, has_next_set, pump_overlap):
        """
        Run one (Pump ↔ Valve) set with optional overlap to the *next* set.
        Cooperative preemption: if self.running becomes False, abort immediately,
        OFF current valve and pump, and propagate cancellation upward.
        """
        try:
            # 0) Early cancel
            self._check_cancel()

            # 1) Pump lead (prime)
            if pump_out_id is not None and pump_ch_idx is not None:
                self._ensure_on(pump_out_id, pump_ch_idx, label='set_pump_lead')
                if pump_lead > 0:
                    self._sleep_exact(pump_lead)

            # 2) Valve ON (non-latching)
            if valve_out_id is not None and valve_ch_idx is not None:
                self._ensure_on(valve_out_id, valve_ch_idx, label='set_valve')
            start_ts = time.monotonic()

            # 3) Run with optional pre-overlap to next set
            if has_next_set and valve_overlap_next > 0 and valve_sec > valve_overlap_next:
                self._sleep_exact(valve_sec - valve_overlap_next)
            else:
                self._sleep_exact(valve_sec)

            # 4) Valve OFF at end of this set
            if valve_out_id is not None and valve_ch_idx is not None:
                self._switch(valve_out_id, valve_ch_idx, 'off', label='set_valve_end')

            # 5) Pump overlap or tail
            if pump_out_id is not None and pump_ch_idx is not None:
                if has_next_set:
                    if pump_overlap > 0:
                        self._sleep_exact(pump_overlap)
                else:
                    if pump_tail > 0:
                        self._sleep_exact(pump_tail)
                    self._switch(pump_out_id, pump_ch_idx, 'off', label='set_pump_end')

            # 6) Final cancel check at set boundary
            self._check_cancel()

        except self._Cancelled:
            # Immediate OFF sweep for safety, best-effort
            try:
                if valve_out_id is not None and valve_ch_idx is not None:
                    self._switch(valve_out_id, valve_ch_idx, 'off', label='cancel_valve')
            except Exception:
                pass
            try:
                if pump_out_id is not None and pump_ch_idx is not None:
                    self._switch(pump_out_id, pump_ch_idx, 'off', label='cancel_pump')
            except Exception:
                pass
            raise

    def _ensure_off_if_on(self, out_id, ch_idx, label=''):
        st = self._get_output_state(out_id, ch_idx)
        if st == 'on':
            return self._switch(out_id, ch_idx, 'off', label=f"{label}_ensure")
        return st == 'off'

    def _collect_all_configured_outputs(self, include_unused=True):
        """Return a set of (out_id, ch_idx) pairs for pump + all valves (static/dynamic)."""
        pairs = set()
        # Pump
        try:
            pump = getattr(self, 'output_pump_channel', None)
            if pump is not None:
                oid = self._resolve_output_device_id(pump, None)
                chx = self._resolve_channel_index(pump, None)
                if oid is not None and chx is not None:
                    pairs.add((oid, int(chx)))
        except Exception:
            pass
        # Static 1..max_channels
        try:
            for ch in getattr(self, 'output_channels', []) or []:
                if ch is None:
                    continue
                oid = self._resolve_output_device_id(ch, None)
                chx = self._resolve_channel_index(ch, None)
                if oid is not None and chx is not None:
                    pairs.add((oid, int(chx)))
        except Exception:
            pass
        # Dynamic channel ids
        try:
            dids = getattr(self, 'output_channels_dyn_ids', {}) or {}
            if isinstance(dids, dict):
                from aot.databases.models import OutputChannel as _OC
                for _, cid in dids.items():
                    try:
                        row = db_retrieve_table_daemon(_OC, unique_id=self._coerce_channel_id(cid))
                        if row:
                            oid = getattr(row, 'output_id', None) or getattr(row, 'device_id', None)
                            chx = getattr(row, 'channel', None)
                            if isinstance(chx, str) and chx.isdigit():
                                chx = int(chx)
                            if oid is not None and chx is not None:
                                pairs.add((oid, int(chx)))
                    except Exception:
                        continue
        except Exception:
            pass
        return pairs

    def _off_sweep(self, pairs, only_if_on=True, label='init'):
        attempted = 0
        success = 0
        for (oid, chx) in pairs:
            attempted += 1
            try:
                if only_if_on:
                    st = self._get_output_state(oid, chx)
                    if st != 'on':
                        continue
                if self._switch(oid, chx, 'off', label=f"{label}_off"):
                    success += 1
            except Exception:
                continue
        return attempted, success

    def initialize(self):
        # No internal scheduling by period_seconds; removed.

        # Resolve output channels from stored channel_ids (coerce to id)
        self.output_channels = []
        for idx in range(1, self.max_channels + 1):
            ch_id_raw = getattr(self, f'output_{idx}_channel_id', None)
            ch_id = self._coerce_channel_id(ch_id_raw)
            ch = self.get_output_channel_from_channel_id(ch_id) if ch_id is not None else None
            self.output_channels.append(ch)
        pump_ch_id_raw = getattr(self, 'output_pump_channel_id', None)
        pump_ch_id = self._coerce_channel_id(pump_ch_id_raw)
        self.output_pump_channel = self.get_output_channel_from_channel_id(pump_ch_id) if pump_ch_id is not None else None
        if self.output_pump_channel is None:
            try:
                pump_fallback_id = getattr(self, 'output_pump', None)
                if pump_fallback_id:
                    self.output_pump_channel = self.get_output_channel_from_channel_id(pump_fallback_id)
            except Exception:
                pass

        # Load per-channel options (dynamic channels) similar to inputs
        try:
            function_channels = db_retrieve_table_daemon(FunctionChannel).\
                filter(FunctionChannel.function_id == self.unique_id).all()
            self.options_channels = self.setup_custom_channel_options_json(
                FUNCTION_INFORMATION['custom_channel_options'], function_channels)
            # Normalize options_channels: convert list-of-dicts to dict keyed by channel index
            if isinstance(self.options_channels, list):
                norm = {'enabled': {}, 'time': {}, 'output': {}, 'output_channel_id': {}, 'duration_min': {}}
                for i, row in enumerate(self.options_channels):
                    if not isinstance(row, dict):
                        continue
                    idx = row.get('index', i)
                    for k in ('enabled', 'time', 'output', 'output_channel_id', 'duration_min'):
                        if k in row:
                            norm[k][str(idx)] = row[k]
                self.options_channels = norm

            # If output values are dict-shaped, pull out an id field
            for k_map in ('output', 'output_channel_id', 'duration_min'):
                m = self.options_channels.get(k_map, {})
                if isinstance(m, dict):
                    for kk, vv in list(m.items()):
                        if isinstance(vv, dict):
                            # For outputs: collapse to id; for duration_min: allow numeric or string inside dict
                            cid = vv.get('channel_id') or vv.get('output_channel_id') or vv.get('unique_id') or vv.get('id') or vv.get('channel')
                            if cid is not None:
                                m[kk] = cid
                            elif 'value' in vv:
                                m[kk] = vv.get('value')
                    self.options_channels[k_map] = m
            # Resolve output channel objects for dynamic channels (support both legacy and new keys)
            self.output_channels_dyn = {}
            self.output_channels_dyn_ids = {}
            out_ch_ids = self.options_channels.get('output_channel_id', {}) or self.options_channels.get('output', {})
            if isinstance(out_ch_ids, dict):
                for ch_key, ch_id_raw in out_ch_ids.items():
                    cid = self._coerce_channel_id(ch_id_raw)  # ⬅️ 정규화
                    self.output_channels_dyn_ids[ch_key] = cid
                    try:
                        self.output_channels_dyn[ch_key] = self.get_output_channel_from_channel_id(cid) if cid else None
                    except Exception:
                        self.output_channels_dyn[ch_key] = None
        except Exception as e:
            self.logger.warning(f"[IrrigationControl] Dynamic channel options load failed: {e}")

        # --- Ensure all configured outputs (static + dynamic) start from OFF state ---
        try:
            try:
                init_off_opt = str(getattr(self, 'init_off', 'True')).strip().lower() in ('1', 'true', 'yes', 'on')
            except Exception:
                init_off_opt = True
            if init_off_opt:
                pairs = self._collect_all_configured_outputs(include_unused=True)
                # Aggressive at init: some drivers don't support output_status, so we force OFF.
                attempted, success = self._off_sweep(pairs, only_if_on=False, label='init')
                self.logger.info(f"[IrrigationControl] Init OFF sweep (force): {success}/{attempted} succeeded")
        except Exception as e:
            self.logger.error(f"[IrrigationControl] init OFF sweep encountered an issue: {e}")




    def loop(self):
        self._sync_logger_level()
        # Periodic scheduler: run once per period seconds (period provided by core/user option in seconds)
        try:
            period_sec = float(getattr(self, 'period', 0) or 0)
        except Exception:
            period_sec = 0
        if period_sec <= 0:
            period_sec = 1.0  # minimal backoff to avoid tight loop if misconfigured

        # Precompute constants
        use_pump = self._truthy(getattr(self, 'use_pump', 'True'), default=True)
        try:
            min_runtime_sec = int(getattr(self, 'min_runtime_sec', 15) or 0)
        except Exception:
            min_runtime_sec = 15
        if min_runtime_sec < 0:
            min_runtime_sec = 0

        # Overlap seconds between valves (user option, default 1.0s)
        try:
            overlap_sec = float(getattr(self, 'overlap_sec', 1.0) or 0.0)
        except Exception:
            overlap_sec = 1.0
        if overlap_sec < 0:
            overlap_sec = 0.0
        if overlap_sec > 5.0:
            overlap_sec = 5.0

        # Ensure measurement_max_age is not shorter than period (avoids stale filtering on every cycle)
        try:
            mma = getattr(self, 'measurement_max_age', None)
            if mma is not None:
                if int(mma) < int(period_sec):
                    self.logger.warning(
                        "[IrrigationControl] measurement_max_age (%ss) < period (%ss); adjusting to period",
                        mma, period_sec
                    )
                    self.measurement_max_age = int(period_sec)
        except Exception:
            pass

        # If function has been deactivated, do nothing
        if not getattr(self, 'running', True):
            return

        # Gate
        now = time.time()
        if now < getattr(self, '_next_run', 0):
            return
        if getattr(self, '_in_cycle', False):
            # Prevent overlap if previous cycle is still running
            return
        self._in_cycle = True
        try:
            if not getattr(self, 'running', True):
                return
            # --- Time window gating (start_time/end_time) ---
            st_txt = getattr(self, 'start_time', '')
            et_txt = getattr(self, 'end_time', '')
            gating_intended = bool(str(st_txt).strip() or str(et_txt).strip())
            if gating_intended:
                ss = self._parse_hhmm_text_to_seconds(st_txt)
                es = self._parse_hhmm_text_to_seconds(et_txt)
                if ss is None or es is None:
                    # Invalid format when gating intended: skip this cycle and retry next period
                    self.logger.warning('[IrrigationControl] Invalid start_time/end_time. Skipping cycle.')
                    return
                # Compute seconds since midnight (local time)
                now_ts = time.time()
                lt = time.localtime(now_ts)
                ns = lt.tm_hour*3600 + lt.tm_min*60 + lt.tm_sec
                def in_window(ns_, ss_, es_):
                    if ss_ == es_:
                        return True  # 24h open
                    if ss_ < es_:
                        return ss_ <= ns_ <= es_
                    return (ns_ >= ss_) or (ns_ <= es_)
                if not in_window(ns, ss, es):
                    # Schedule next start boundary
                    # Base midnight (today)
                    midnight = now_ts - (ns)
                    next_start = midnight + ss
                    if ss < es:
                        # Normal window: if current before start, today ss; else tomorrow ss
                        if ns < ss:
                            pass  # today
                        else:
                            next_start += 24*3600
                    else:
                        # Wrap window: we are outside only when ns in (es, ss)
                        if not (ns >= ss or ns <= es):
                            # in the gap → today ss
                            pass
                        else:
                            # Should not happen (would be inside), but guard by moving to next day
                            next_start += 24*3600
                    # Ensure next_run is at least 1s in the future
                    self._next_run = max(next_start, now_ts + 1.0)
                    return
                # If we are inside the window, ensure there is at least one full period remaining; otherwise skip
                if gating_intended:
                    # recompute ss/es if needed and now seconds since midnight
                    now_ts2 = time.time()
                    lt2 = time.localtime(now_ts2)
                    ns2 = lt2.tm_hour*3600 + lt2.tm_min*60 + lt2.tm_sec

                    def _remaining_window(ns_, ss_, es_):
                        # returns remaining seconds inside window from now to end boundary
                        if ss_ == es_:
                            return 24*3600 - (ns_ - ss_)  # treat as always-open; large value
                        if ss_ < es_:
                            # normal window
                            return max(0, es_ - ns_)
                        # wrapped window
                        if ns_ <= es_:
                            # we are in [0..es]
                            return max(0, es_ - ns_)
                        # we are in [ss..24h)
                        return max(0, (24*3600 - ns_))

                    rem_window = _remaining_window(ns2, ss, es)
                    if rem_window < period_sec:
                        self.logger.warning(
                            "[IrrigationControl] Skipping: remaining window %ss < period %ss (예약 시간 범위보다 주기가 짧습니다.)",
                            rem_window, period_sec
                        )
                        # schedule next at least one second later to avoid tight loop
                        self._next_run = time.time() + max(1.0, period_sec)
                        return
            # --- Dynamic channel handling: run channels defined via custom_channel_options ---
            dyn = self.options_channels if isinstance(getattr(self, 'options_channels', None), dict) else {}
            dyn_out_ch_objs = getattr(self, 'output_channels_dyn', {}) or {}
            dyn_out_ch_ids = (dyn.get('output_channel_id') or dyn.get('output') or {})
            dyn_enabled = dyn.get('enabled') or {}
            dyn_duration = dyn.get('duration_min') or {}

            def _get_out_ch(k):
                ch = dyn_out_ch_objs.get(k)
                if ch is None:
                    try:
                        ch = dyn_out_ch_objs.get(int(k))
                    except Exception:
                        pass
                if ch is None:
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

            if not dyn or not isinstance(dyn, dict):
                return

            # Keys: support both legacy split maps and unified 'time'
            dyn_time = dyn.get('time') or {}
            dyn_time_dev = dyn.get('time_device_id') or {}
            dyn_time_meas = dyn.get('time_measurement_id') or {}
            # Channel objects resolved in initialize(); prefer these over raw ids
            dyn_out_ch_objs = dyn_out_ch_objs

            def _key_index(k):
                try:
                    return int(k)
                except Exception:
                    # Non-integer keys are placed at the end
                    return 10**9

            # Merge keys from all channel maps (some deployments store keys as strings)
            key_sets = [dyn_time.keys(), dyn_time_dev.keys(), dyn_time_meas.keys(), dyn_out_ch_objs.keys()]
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

            def _duration_positive(k):
                if not isinstance(dyn_duration, dict):
                    return False
                d = dyn_duration.get(k)
                if d is None:
                    try:
                        d = dyn_duration.get(int(k))
                    except Exception:
                        d = None
                try:
                    return float(d) > 0
                except Exception:
                    return False

            keys_allowed = [
                k for k in keys_allowed
                if _is_enabled(k) and _has_output(k) and (_has_time_ref(k) or _duration_positive(k))
            ]
            if not keys_allowed:
                return

            # PATCH 2: Remove per-valve auto-scaling and per-valve max clamp

            # Read minimum runtime cap (seconds)
            try:
                min_runtime_sec = int(getattr(self, 'min_runtime_sec', 15) or 0)
            except Exception:
                min_runtime_sec = 15
            if min_runtime_sec < 0:
                min_runtime_sec = 0

            # Build plan (key, out_id, ch_idx, seconds)
            plan = []
            reasons_map = {}
            for ch_key in keys_allowed:
                # Skip if channel disabled (double guard)
                if not _is_enabled(ch_key):
                    reasons_map[str(ch_key)] = 'disabled'
                    continue
                # ---- default: original measurement-based logic ----
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

                # Resolve output channel OBJECT (from initialize())
                out_ch = dyn_out_ch_objs.get(ch_key)
                if out_ch is None:
                    try:
                        out_ch = dyn_out_ch_objs.get(int(ch_key))
                    except Exception:
                        pass
                if out_ch is None:
                    # try resolving from stored channel id on the fly
                    cid = dyn_out_ch_ids.get(ch_key)
                    if cid is None:
                        try:
                            cid = dyn_out_ch_ids.get(int(ch_key))
                        except Exception:
                            cid = None
                    if cid:
                        try:
                            out_ch = self.get_output_channel_from_channel_id(cid)
                        except Exception:
                            out_ch = None
                out_ch = _get_out_ch(ch_key)
                if out_ch is None:
                    self.logger.warning(f"[ValveTime] Channel {ch_key} skipped: no output selected or resolvable.")
                    continue

                # Use measurement-derived seconds (abs value)
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
                        try:
                            row = db_retrieve_table_daemon('measurements', unique_id=meas_id, max_age=self.measurement_max_age)
                            if row:
                                if isinstance(row, dict):
                                    ts = row.get('timestamp') or row.get('last_timestamp') or row.get('ts')
                                    val = row.get('value') or row.get('last_value') or row.get('measurement')
                                else:
                                    ts = getattr(row, 'timestamp', None) or getattr(row, 'last_timestamp', None) or getattr(row, 'ts', None)
                                    val = getattr(row, 'value', None) or getattr(row, 'last_value', None) or getattr(row, 'measurement', None)
                                if val is not None:
                                    last = (ts, val)
                        except Exception:
                            last = None
                if last is None and dev_id and meas_id:
                    try:
                        last = self.get_last_measurement(dev_id, meas_id)
                    except Exception:
                        last = None
                if last is None and meas_id and hasattr(self, 'get_last_measurement_by_measurement_id'):
                    try:
                        last = self.get_last_measurement_by_measurement_id(meas_id)
                    except Exception:
                        last = None
                if last is None and meas_id:
                    try:
                        row = db_retrieve_table_daemon('measurements', unique_id=meas_id)
                        if row:
                            if isinstance(row, dict):
                                ts = row.get('timestamp') or row.get('last_timestamp') or row.get('ts')
                                val = row.get('value') or row.get('last_value') or row.get('measurement')
                            else:
                                ts = getattr(row, 'timestamp', None) or getattr(row, 'last_timestamp', None) or getattr(row, 'ts', None)
                                val = getattr(row, 'value', None) or getattr(row, 'last_value', None) or getattr(row, 'measurement', None)
                            if val is not None:
                                last = (ts, val)
                    except Exception:
                        pass

                if not last:
                    # Measurement missing/stale — try duration_min fallback
                    dur = None
                    if isinstance(dyn_duration, dict):
                        dur = dyn_duration.get(ch_key)
                        if dur is None:
                            try:
                                dur = dyn_duration.get(int(ch_key))
                            except Exception:
                                pass
                    if dur is not None and str(dur).strip() != '':
                        try:
                            dur_min = float(dur or 0.0)
                        except Exception:
                            dur_min = 0.0
                        sec = int(dur_min * 60.0) if dur_min > 0 else 0
                        if sec < min_runtime_sec or sec <= 0:
                            reasons_map[str(ch_key)] = 'below_min_runtime_cap'
                        else:
                            # Resolve output/channel indices now
                            out_ch = _get_out_ch(ch_key)
                            if out_ch is None:
                                self.logger.warning(f"[ValveTime] Channel {ch_key} skipped: no output selected or resolvable.")
                            else:
                                out_id_resolved = None
                                ch_idx_resolved = None
                                try:
                                    if out_ch is not None:
                                        try:
                                            out_id_resolved = getattr(out_ch, 'output_id', None) or getattr(getattr(out_ch, 'output', None), 'unique_id', None) or getattr(getattr(out_ch, 'device', None), 'unique_id', None)
                                        except Exception:
                                            pass
                                        try:
                                            ci = getattr(out_ch, 'channel', None)
                                            if isinstance(ci, str) and ci.isdigit():
                                                ci = int(ci)
                                            if isinstance(ci, int):
                                                ch_idx_resolved = ci
                                        except Exception:
                                            pass
                                    if out_id_resolved is None or ch_idx_resolved is None:
                                        cid = dyn_out_ch_ids.get(ch_key)
                                        if cid is None:
                                            try:
                                                cid = dyn_out_ch_ids.get(int(ch_key))
                                            except Exception:
                                                cid = None
                                        if cid:
                                            try:
                                                from aot.databases.models import OutputChannel as _OC
                                                row = db_retrieve_table_daemon(_OC, unique_id=cid)
                                                if row:
                                                    out_id_resolved = out_id_resolved or getattr(row, 'output_id', None) or getattr(row, 'device_id', None)
                                                    if ch_idx_resolved is None:
                                                        rc = getattr(row, 'channel', None)
                                                        if isinstance(rc, str) and rc.isdigit():
                                                            rc = int(rc)
                                                        if isinstance(rc, int):
                                                            ch_idx_resolved = rc
                                                if out_id_resolved is None:
                                                    out_id_resolved = cid
                                                if ch_idx_resolved is None:
                                                    rows = db_retrieve_table_daemon(_OC).filter(_OC.output_id == out_id_resolved).all()
                                                    if rows:
                                                        preferred = None
                                                        smallest = None
                                                        for r in rows:
                                                            rc = getattr(r, 'channel', None)
                                                            if isinstance(rc, str) and rc.isdigit():
                                                                rc = int(rc)
                                                            if rc == 0:
                                                                preferred = 0
                                                                break
                                                            if isinstance(rc, int):
                                                                if smallest is None or rc < smallest:
                                                                    smallest = rc
                                                        ch_idx_resolved = 0 if preferred == 0 else smallest
                                            except Exception:
                                                pass
                                except Exception:
                                    pass
                                if out_id_resolved is None or ch_idx_resolved is None:
                                    self.logger.warning(f"[ValveTime] Channel {ch_key} skipped: no output selected or resolvable.")
                                else:
                                    plan.append((ch_key, out_id_resolved, ch_idx_resolved, int(sec)))
                                    continue  # duration_min fallback used; proceed next key
                    # No measurement and no valid duration_min: skip with reason
                    if isinstance(meas_id, str) and meas_id.strip().lower() in ('', 'none', 'null'):
                        meas_id = None
                    if not meas_id:
                        reason = 'no_measurement_or_duration'
                    else:
                        reason = 'stale_or_missing_value_and_no_duration'
                    reasons_map[str(ch_key)] = reason
                    continue

                raw_val = self._extract_value(last)
                sec, reason = self._parse_seconds_from_measurement(raw_val)
                sec = int(sec)
                try:
                    pass  # min_runtime_sec is already precomputed above
                except Exception:
                    pass
                if sec < min_runtime_sec:
                    reason = 'below_min_runtime_cap'
                if reason != 'ok' or sec <= 0:
                    reasons_map[str(ch_key)] = reason
                    continue

                # Resolve output/channel indices now
                out_id_resolved = None
                ch_idx_resolved = None
                try:
                    if out_ch is not None:
                        try:
                            out_id_resolved = getattr(out_ch, 'output_id', None) or getattr(getattr(out_ch, 'output', None), 'unique_id', None) or getattr(getattr(out_ch, 'device', None), 'unique_id', None)
                        except Exception:
                            pass
                        try:
                            ci = getattr(out_ch, 'channel', None)
                            if isinstance(ci, str) and ci.isdigit():
                                ci = int(ci)
                            if isinstance(ci, int):
                                ch_idx_resolved = ci
                        except Exception:
                            pass
                    if out_id_resolved is None or ch_idx_resolved is None:
                        cid = dyn_out_ch_ids.get(ch_key)
                        if cid is None:
                            try:
                                cid = dyn_out_ch_ids.get(int(ch_key))
                            except Exception:
                                cid = None
                        if cid:
                            try:
                                from aot.databases.models import OutputChannel as _OC
                                row = db_retrieve_table_daemon(_OC, unique_id=cid)
                                if row:
                                    out_id_resolved = out_id_resolved or getattr(row, 'output_id', None) or getattr(row, 'device_id', None)
                                    if ch_idx_resolved is None:
                                        rc = getattr(row, 'channel', None)
                                        if isinstance(rc, str) and rc.isdigit():
                                            rc = int(rc)
                                        if isinstance(rc, int):
                                            ch_idx_resolved = rc
                                if out_id_resolved is None:
                                    out_id_resolved = cid
                                if ch_idx_resolved is None:
                                    rows = db_retrieve_table_daemon(_OC).filter(_OC.output_id == out_id_resolved).all()
                                    if rows:
                                        preferred = None
                                        smallest = None
                                        for r in rows:
                                            rc = getattr(r, 'channel', None)
                                            if isinstance(rc, str) and rc.isdigit():
                                                rc = int(rc)
                                            if rc == 0:
                                                preferred = 0
                                                break
                                            if isinstance(rc, int):
                                                if smallest is None or rc < smallest:
                                                    smallest = rc
                                        ch_idx_resolved = 0 if preferred == 0 else smallest
                            except Exception:
                                pass
                except Exception:
                    pass

                if out_id_resolved is None or ch_idx_resolved is None:
                    self.logger.warning(f"[ValveTime] Channel {ch_key} skipped: no output selected or resolvable.")
                    continue

                plan.append((ch_key, out_id_resolved, ch_idx_resolved, sec))

            if not plan:
                self.logger.info(f"[IrrigationControl] Skips: {reasons_map}")
                return

            # --- Strict budget: if total runtime exceeds period, skip with warning ---
            total_sec = sum(p[3] for p in plan)
            if total_sec > int(period_sec):
                self.logger.warning(
                    "[IrrigationControl] Skipping: total runtime %ss exceeds period %ss (작동 주기가 장치 작동 시간보다 짧습니다.)",
                    total_sec, int(period_sec)
                )
                # schedule next run after one period
                self._next_run = time.time() + period_sec
                return

            # --- Set-based orchestration with pump overlap matching ---
            # Parameters
            try:
                pump_lead = float(getattr(self, 'pump_lead_sec', 0.8) or 0.0)
            except Exception:
                pump_lead = 0.8
            try:
                pump_tail = float(getattr(self, 'pump_tail_sec', 0.8) or 0.0)
            except Exception:
                pump_tail = 0.8
            try:
                pump_overlap = float(getattr(self, 'pump_overlap_sec', overlap_sec) or overlap_sec)
            except Exception:
                pump_overlap = overlap_sec
            # Ensure pump overlap is not smaller than valve overlap
            if pump_overlap < overlap_sec:
                pump_overlap = overlap_sec

            # Resolve pump identifiers once
            pump_dev = getattr(self, 'output_pump_device_id', None)
            pump_ch = self.output_pump_channel
            pump_out_id = None
            pump_ch_idx = None
            if use_pump and pump_ch is not None:
                pump_out_id = self._resolve_output_device_id(pump_ch, fallback=pump_dev)
                pump_ch_idx = self._resolve_channel_index(pump_ch, fallback=getattr(pump_ch, 'channel', None))
                if pump_ch_idx is None:
                    pump_ch_idx = 0

            # Orchestrate each valve as an independent set
            for i, (key, out_id, ch_idx, sec) in enumerate(plan):
                has_next = (i + 1) < len(plan)
                next_overlap = overlap_sec if has_next else 0.0
                try:
                    self._run_valve_pump_set(
                        pump_out_id, pump_ch_idx,
                        out_id, ch_idx,
                        float(sec), pump_lead, pump_tail,
                        float(next_overlap), has_next, float(pump_overlap)
                    )
                except self._Cancelled:
                    # Already OFF-swept in the set; just stop the cycle
                    break

                # Boundary-only stop policy (still honored)
                if not getattr(self, 'running', True):
                    try:
                        self._emergency_off_now()
                    except Exception:
                        pass
                    break
        finally:
            # Schedule next run based on end-of-cycle time to avoid drift/overrun
            self._next_run = time.time() + period_sec
            self._in_cycle = False
            return
