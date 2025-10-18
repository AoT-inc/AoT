# coding=utf-8
#
#  AoT_valve_controll_8ch_time.py — Periodic sequential 8-valve controller for AoT (with optional pump)
#
#  Copyright (C)
#
#  This file is part of AoT
#
#  AoT is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License.
#
#  Contact at aot-inc.com
#  2025-10-11

import time
from typing import Any

from flask_babel import lazy_gettext

from aot.databases.models import CustomController
from aot.databases.models import FunctionChannel
from aot.databases.models import OutputChannel as DBOutputChannel
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl

from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon




def _seconds_since_midnight(ts: float = None) -> int:
    import time as _t
    if ts is None:
        ts = _t.time()
    lt = _t.localtime(ts)
    return lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec

# Lightweight HH:MM or HHMM parser for time window
def _parse_hhmm_text_to_seconds(s: str) -> int | None:
    """
    Parse 'HH:MM' or 'HHMM' (zero-padded) into seconds since midnight.
    Returns None if invalid.
    """
    if s is None:
        return None
    try:
        s = str(s).strip()
        if not s:
            return None
        # Normalize wide digits and separators
        trans = str.maketrans('０１２３４５６７８９：: ', '0123456789::')
        s = s.translate(trans)
        # Accept HH:MM
        if ':' in s:
            hh, mm = s.split(':', 1)
        else:
            # Accept HHMM (exact 4 digits)
            if len(s) != 4 or not s.isdigit():
                return None
            hh, mm = s[:2], s[2:]
        h = int(hh)
        m = int(mm)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h * 3600 + m * 60
    except Exception:
        return None

FUNCTION_INFORMATION = {
    'function_name_unique': 'valve_control_time',
    'function_name': 'AoT: 밸브제어 - 시간',
    'function_name_short': '밸브제어 - 시간 ',

    # 설명: 각 채널에 입력한 "분 단위" 작동시간을 합산하여 순차적으로 밸브를 ON/OFF합니다.
    # 총 작동시간이 주기(period)를 초과하면 자동 비율 스케일링합니다.
    # 펌프 출력이 활성화된 경우, 전체 밸브 작동 시간의 합 동안 펌프를 동작합니다.
    'message': lazy_gettext('각 채널의 분 단위 작동시간을 순차 실행합니다. 커스텀 옵션의 시작/종료 시각(HH:MM 또는 HHMM) 범위 안에서만 구동하며, 총합 시간 동안(스케일링 반영) 펌프를 함께 켤 수 있습니다.'),

    'options_enabled': [
        'custom_options',
        'custom_channel_options',
        'channels_configure',
        'enable_actions'
    ],

    # 전역 옵션 (시작/종료 시간 옵션 없음 — period 기반 반복)
    'custom_options': [
        {
            'id': 'period',
            'type': 'float',
            'default_value': 600,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('주기'), lazy_gettext('초')),
            'phrase': lazy_gettext('이 함수가 반복 실행되는 간격(초)입니다.')
        },
        {
            'id': 'time_window_enabled',
            'type': 'select',
            'default_value': 'False',
            'required': True,
            'options_select': [('True', lazy_gettext('사용')), ('False', lazy_gettext('미사용'))],
            'name': lazy_gettext('시간 사용'),
            'phrase': lazy_gettext('하루 중 특정 시간대에만 작동하도록 제한합니다.')
        },
        {
            'id': 'start_time',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('시작 시간'),
            'phrase': lazy_gettext('예: 03:00 또는 0300. 입력 시 사용됩니다.')
        },
        {
            'id': 'end_time',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': lazy_gettext('종료 시간'),
            'phrase': lazy_gettext('예: 17:30 또는 1730. 입력 시 사용됩니다.')
        },
        {
            'id': 'use_pump_output',
            'type': 'select',
            'default_value': 'False',
            'required': True,
            'options_select': [('True', lazy_gettext('사용')), ('False', lazy_gettext('미사용'))],
            'name': lazy_gettext('펌프 사용'),
            'phrase': lazy_gettext('펌프 출력을 함께 사용할지 선택합니다.')
        },
        {
            'id': 'output_pump',
            'type': 'select_channel',
            'default_value': '',
            'required': False,
            'options_select': [
                'Output_Channels',
            ],
            'name': lazy_gettext('펌프 출력'),
            'phrase': lazy_gettext('펌프 제어에 사용할 출력을 선택합니다. (사용 설정 시 필요)')
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
    ],

    # 채널 옵션
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
            'id': 'duration_min',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': "{} ({})".format(lazy_gettext('작동시간'), lazy_gettext('분')),
            'phrase': lazy_gettext('이 채널의 밸브를 작동할 시간(분 단위)입니다. (미사용 시 비워두거나 0으로 두세요)')
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
    def _read_raw_pump_spec(self):
        """Return the raw pump selector from various possible option storages.
        Tries attributes, dict/list option containers, and DB row to tolerate schema/UI differences.
        """
        # 0) quick fuzzy attribute scan first (covers variants like 'output_pump_channel_id')
        try:
            for ak, av in list(self.__dict__.items()):
                if not ak:
                    continue
                name = str(ak).lower()
                if ('pump' in name) and ('output' in name) and (av not in (None, '')):
                    # prefer exact known keys; otherwise accept fuzzy
                    if name in ('output_pump', 'pump_output', 'pump_channel', 'pump', 'output_pump_channel_id', 'output_pump_id'):
                        return av
        except Exception:
            pass

        # 1) direct attributes with common names
        for key in ('output_pump', 'pump_output', 'pump_channel', 'pump', 'output_pump_channel_id', 'output_pump_id'):
            try:
                val = getattr(self, key)
                if val not in (None, ''):
                    return val
            except Exception:
                pass

        # 2) known option containers on instance (dict or list)
        for key in ('custom_options', 'custom_options_json', 'options', 'opts', 'config', 'settings'):
            try:
                cont = getattr(self, key)
            except Exception:
                cont = None

            # dict-style container
            if isinstance(cont, dict):
                # direct field or nested under known wrappers
                val = (cont.get('output_pump') or cont.get('pump_output') or cont.get('pump_channel') or cont.get('pump')
                       or cont.get('output_pump_channel_id') or cont.get('output_pump_id'))
                if val not in (None, ''):
                    return val
                # wrapped objects
                for k2 in ('output_pump', 'pump_output', 'pump_channel', 'pump', 'output_pump_channel_id', 'output_pump_id'):
                    node = cont.get(k2)
                    if isinstance(node, dict):
                        # try direct
                        if node.get('channel_id') or node.get('output_channel_id') or node.get('unique_id'):
                            return node
                        # try nested 'value'
                        v2 = node.get('value')
                        if isinstance(v2, dict) and (v2.get('channel_id') or v2.get('output_channel_id') or v2.get('unique_id')):
                            return v2

            # list-style container (e.g., [{'id': 'output_pump', 'value': {...}}, ...])
            if isinstance(cont, list):
                try:
                    # prefer exact id match first
                    for row in cont:
                        if not isinstance(row, dict):
                            continue
                        rid = str(row.get('id', '')).lower()
                        if rid in ('output_pump', 'pump_output', 'pump_channel', 'pump', 'output_pump_channel_id', 'output_pump_id'):
                            v = row.get('value') if 'value' in row else row.get('val')
                            if v not in (None, ''):
                                return v
                    # fuzzy id contains both words
                    for row in cont:
                        if not isinstance(row, dict):
                            continue
                        rid = str(row.get('id', '')).lower()
                        if ('pump' in rid) and ('output' in rid):
                            v = row.get('value') if 'value' in row else row.get('val')
                            if v not in (None, ''):
                                return v
                except Exception:
                    pass

        # 3) shallow scan of dict-valued attributes
        try:
            for v in self.__dict__.values():
                if isinstance(v, dict):
                    # exact keys
                    for k2 in ('output_pump', 'pump_output', 'pump_channel', 'pump', 'output_pump_channel_id', 'output_pump_id'):
                        node = v.get(k2)
                        if node not in (None, ''):
                            return node
                    # fuzzy keys
                    for k2, node in v.items():
                        if isinstance(k2, str) and ('pump' in k2.lower()) and ('output' in k2.lower()) and node not in (None, ''):
                            return node
        except Exception:
            pass

        # 4) DB row fallback (dict or list forms)
        try:
            row = db_retrieve_table_daemon(CustomController, unique_id=self.unique_id)
            if row is not None:
                # attribute-like
                for key in ('output_pump', 'pump_output', 'pump_channel', 'pump', 'output_pump_channel_id', 'output_pump_id'):
                    try:
                        val = getattr(row, key)
                        if val not in (None, ''):
                            return val
                    except Exception:
                        pass
                # json/dict/list
                for key in ('custom_options', 'custom_options_json', 'options_json'):
                    try:
                        cont = getattr(row, key)
                    except Exception:
                        cont = None
                    if isinstance(cont, dict):
                        val = (cont.get('output_pump') or cont.get('pump_output') or cont.get('pump_channel') or cont.get('pump')
                               or cont.get('output_pump_channel_id') or cont.get('output_pump_id'))
                        if val not in (None, ''):
                            return val
                        for k2 in ('output_pump', 'pump_output', 'pump_channel', 'pump', 'output_pump_channel_id', 'output_pump_id'):
                            node = cont.get(k2)
                            if isinstance(node, dict):
                                if node.get('channel_id') or node.get('output_channel_id') or node.get('unique_id'):
                                    return node
                                v2 = node.get('value')
                                if isinstance(v2, dict) and (v2.get('channel_id') or v2.get('output_channel_id') or v2.get('unique_id')):
                                    return v2
                    if isinstance(cont, list):
                        try:
                            for row2 in cont:
                                if not isinstance(row2, dict):
                                    continue
                                rid = str(row2.get('id', '')).lower()
                                if rid in ('output_pump', 'pump_output', 'pump_channel', 'pump', 'output_pump_channel_id', 'output_pump_id'):
                                    v = row2.get('value') if 'value' in row2 else row2.get('val')
                                    if v not in (None, ''):
                                        return v
                            for row2 in cont:
                                if not isinstance(row2, dict):
                                    continue
                                rid = str(row2.get('id', '')).lower()
                                if ('pump' in rid) and ('output' in rid):
                                    v = row2.get('value') if 'value' in row2 else row2.get('val')
                                    if v not in (None, ''):
                                        return v
                        except Exception:
                            pass
        except Exception:
            pass
        return None
    """
    분 단위로 지정한 8채널 밸브 시간을 순차적으로 실행합니다.
    - 시작/종료 시각 옵션 없음 (period 기반 반복)
    - 채널별 '분 단위' 작동시간과 출력만 사용
    - period(초)마다 1회 실행
    - '펌프 출력 사용'이 True이고 펌프 출력이 지정된 경우, 총 밸브 작동시간(스케일링 반영) 동안 펌프를 구동
    """

    def _resolve_out_pair(self, spec):
        """
        Fast path: resolve a 'spec' into (output_id, channel_idx) without keeping ORM objects.
        Supported forms:
        - dict with channel unique id: {'channel_id': '<uuid>'} or {'output_channel_id': '<uuid>'} or {'unique_id': '<uuid>'}
        - dict with device + channel index: {'output_id'|'device_id'|'output_unique_id': '<id>', 'channel'|'ch'|'index': <int>}
        - string: '<device_id>:<idx>' or '<device_id>/<idx>' or '<channel_unique_id>'
        - integer: DB primary key id of OutputChannel, or channel index if default_output_id is set
        Returns (out_id, ch_idx) or (None, None) if unresolved.
        """
        try:
            if spec is None:
                return (None, None)

            # 1) If spec is already a tuple-like (out_id, ch_idx)
            if isinstance(spec, (tuple, list)) and len(spec) >= 2:
                out_id, ch_idx = spec[0], spec[1]
                try:
                    ch_idx = int(ch_idx)
                except Exception:
                    return (None, None)
                if out_id:
                    return (out_id, ch_idx)
                return (None, None)

            # 2) Integer: treat as OutputChannel PK id
            if isinstance(spec, int):
                # PK id lookup
                try:
                    row = db_retrieve_table_daemon(DBOutputChannel, id=spec)
                    if row:
                        oid = getattr(row, 'output_id', None)
                        idx = getattr(row, 'channel', None)
                        if oid is not None and idx is not None:
                            try:
                                idx = int(idx)
                                return (oid, idx)
                            except Exception:
                                pass
                except Exception:
                    pass
                # Unresolved
                return (None, None)

            # 3) Dict input
            if isinstance(spec, dict):
                # 3a) Direct channel unique id keys
                cand = (
                    spec.get('channel_id')
                    or spec.get('output_channel_id')
                    or spec.get('unique_id')
                    or spec.get('id')
                )
                if cand:
                    # First try framework helper
                    try:
                        ch_obj = self.get_output_channel_from_channel_id(cand)
                        oid = getattr(ch_obj, 'output_id', None) or getattr(getattr(ch_obj, 'output', None), 'unique_id', None)
                        idx = getattr(ch_obj, 'channel', None)
                        if oid is not None and idx is not None:
                            return (oid, int(idx))
                    except Exception:
                        pass
                    # Fallback: direct DB lookup by channel unique_id
                    try:
                        row = db_retrieve_table_daemon(DBOutputChannel, unique_id=cand)
                        if row:
                            oid = getattr(row, 'output_id', None)
                            idx = getattr(row, 'channel', None)
                            if oid is not None and idx is not None:
                                return (oid, int(idx))
                    except Exception:
                        pass

                # 3b) Device + channel index
                dev = (spec.get('output_id') or spec.get('device_id') or
                       spec.get('output_unique_id') or spec.get('output') or spec.get('device'))
                ch_raw = spec.get('channel') or spec.get('ch') or spec.get('index')
                if dev is not None and ch_raw is not None:
                    try:
                        return (str(dev), int(ch_raw))
                    except Exception:
                        return (None, None)

                # Nothing else
                return (None, None)

            # 4) String input
            if isinstance(spec, str):
                s = spec.strip()
                if not s:
                    return (None, None)
                if (':' in s) or ('/' in s):
                    sep = ':' if ':' in s else '/'
                    left, right = s.split(sep, 1)
                    try:
                        return (left.strip(), int(right.strip()))
                    except Exception:
                        return (None, None)
                # otherwise treat as channel unique_id string
                try:
                    ch_obj = self.get_output_channel_from_channel_id(s)
                    oid = getattr(ch_obj, 'output_id', None) or getattr(getattr(ch_obj, 'output', None), 'unique_id', None)
                    idx = getattr(ch_obj, 'channel', None)
                    if oid is not None and idx is not None:
                        return (oid, int(idx))
                except Exception:
                    pass
                try:
                    row = db_retrieve_table_daemon(DBOutputChannel, unique_id=s)
                    if row:
                        oid = getattr(row, 'output_id', None)
                        idx = getattr(row, 'channel', None)
                        if oid is not None and idx is not None:
                            return (oid, int(idx))
                except Exception:
                    pass
                return (None, None)

        except Exception:
            return (None, None)
        return (None, None)


    def _resolve_pump_pair_from_id(self, spec):
        """Resolve pump selector into (output_id, channel_idx).
        Accepts: channel unique_id string, OutputChannel PK int, or dict forms like
        {'channel_id': '...'} or {'device_id': '...','channel': 0}.
        """
        try:
            if spec is None:
                return (None, None)

            # tuple/list already
            if isinstance(spec, (tuple, list)) and len(spec) >= 2:
                out_id, ch_idx = spec[0], spec[1]
                try:
                    ch_idx = int(ch_idx)
                except Exception:
                    return (None, None)
                if out_id:
                    return (out_id, ch_idx)
                return (None, None)

            # integer: treat as OutputChannel PK id
            if isinstance(spec, int):
                try:
                    row = db_retrieve_table_daemon(DBOutputChannel, id=spec)
                    if row:
                        oid = getattr(row, 'output_id', None)
                        idx = getattr(row, 'channel', None)
                        if oid is not None and idx is not None:
                            return (oid, int(idx))
                except Exception:
                    pass
                return (None, None)

            # dict
            if isinstance(spec, dict):
                cand = (
                    spec.get('channel_id')
                    or spec.get('output_channel_id')
                    or spec.get('unique_id')
                    or spec.get('id')
                )
                if cand:
                    try:
                        row = db_retrieve_table_daemon(DBOutputChannel, unique_id=cand)
                        if row:
                            oid = getattr(row, 'output_id', None)
                            idx = getattr(row, 'channel', None)
                            if oid is not None and idx is not None:
                                return (oid, int(idx))
                    except Exception:
                        pass
                    try:
                        ch_obj = self.get_output_channel_from_channel_id(cand)
                        oid = getattr(ch_obj, 'output_id', None) or getattr(getattr(ch_obj, 'output', None), 'unique_id', None)
                        idx = getattr(ch_obj, 'channel', None)
                        if oid is not None and idx is not None:
                            return (oid, int(idx))
                    except Exception:
                        pass
                dev = (spec.get('output_id') or spec.get('device_id') or
                       spec.get('output_unique_id') or spec.get('output') or spec.get('device'))
                ch_raw = spec.get('channel') or spec.get('ch') or spec.get('index')
                if dev is not None and ch_raw is not None:
                    try:
                        return (str(dev), int(ch_raw))
                    except Exception:
                        return (None, None)
                return (None, None)

            # string
            if isinstance(spec, str):
                s = spec.strip()
                if not s:
                    return (None, None)
                if (':' in s) or ('/' in s):
                    sep = ':' if ':' in s else '/'
                    left, right = s.split(sep, 1)
                    try:
                        return (left.strip(), int(right.strip()))
                    except Exception:
                        return (None, None)
                try:
                    row = db_retrieve_table_daemon(DBOutputChannel, unique_id=s)
                    if row:
                        oid = getattr(row, 'output_id', None)
                        idx = getattr(row, 'channel', None)
                        if oid is not None and idx is not None:
                            return (oid, int(idx))
                except Exception:
                    pass
                try:
                    ch_obj = self.get_output_channel_from_channel_id(s)
                    oid = getattr(ch_obj, 'output_id', None) or getattr(getattr(ch_obj, 'output', None), 'unique_id', None)
                    idx = getattr(ch_obj, 'channel', None)
                    if oid is not None and idx is not None:
                        return (oid, int(idx))
                except Exception:
                    pass
                return (None, None)
        except Exception:
            return (None, None)
        return (None, None)


    def _extract_spec_for_channel(self, dyn: dict, key: str):
        """
        Best-effort extraction of an 'output channel spec' for a given channel key from dynamic options dict.
        Looks across multiple commonly-used field names to tolerate schema/UI differences.
        """
        if not isinstance(dyn, dict):
            return None
        # Known candidate maps in preferred order
        candidate_maps = [
            'output', 'output_channel_id',
            'select_channel', 'select_output',
            'channel', 'output_select',
            'outputId', 'output_id',
            'device', 'device_id', 'output_unique_id'
        ]
        # 1) Direct map by known keys
        for m in candidate_maps:
            d = dyn.get(m)
            if isinstance(d, dict):
                if key in d:
                    return d.get(key)
                try:
                    ik = int(key)
                    if ik in d:
                        return d.get(ik)
                except Exception:
                    pass
        # 2) Fallback: scan any dict-valued entries for this key
        for k, v in dyn.items():
            if isinstance(v, dict):
                if key in v:
                    return v.get(key)
                try:
                    ik = int(key)
                    if ik in v:
                        return v.get(ik)
                except Exception:
                    pass
        return None



    # ---- 초기화 ----
    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)
        self.control = DaemonControl()

        # 옵션 로드
        custom_function = db_retrieve_table_daemon(CustomController, unique_id=self.unique_id)
        self.setup_custom_options(FUNCTION_INFORMATION['custom_options'], custom_function)

        # 채널 옵션 준비
        self.options_channels = None
        self.output_channels_dyn = {}
        self.output_channels_dyn_ids = {}
        # Fast cache: per-channel resolved (output_id, channel_idx)
        self.out_pairs = {}           # e.g., {'0': ('relay_board_01', 0)}
        self.out_specs_raw = {}       # last seen raw spec per channel
        # 펌프 채널 (output_id, channel_idx)
        self.pump_pair = (None, None)
        self._pump_raw_last = object()

        # 상태
        self._next_run = time.time()
        self._in_cycle = False
        self._was_in_window = False

        if not testing:
            self.try_initialize()

    def initialize(self):
        # 채널 로딩
        try:
            function_channels = db_retrieve_table_daemon(FunctionChannel). \
                filter(FunctionChannel.function_id == self.unique_id).all()
            self.options_channels = self.setup_custom_channel_options_json(
                FUNCTION_INFORMATION['custom_channel_options'], function_channels)

            # list -> dict 정규화
            if isinstance(self.options_channels, list):
                norm = {'enabled': {}, 'duration_min': {}, 'output': {}, 'output_channel_id': {}}
                for i, row in enumerate(self.options_channels):
                    if not isinstance(row, dict):
                        continue
                    idx = row.get('index', i)
                    for k in ('enabled', 'duration_min', 'output', 'output_channel_id'):
                        if k in row:
                            norm[k][str(idx)] = row[k]
                self.options_channels = norm

            # 출력 채널 스펙(raw) 확보 및 해석 (관대한 키 지원)
            out_spec_map = {}
            # 수집 대상 키들
            _candidate_keys = [
                'output', 'output_channel_id',
                'select_channel', 'select_output',
                'channel', 'output_select',
                'outputId', 'output_id',
                'device', 'device_id', 'output_unique_id'
            ]
            # 채널 키 집합 만들기
            ch_keys = set()
            for k in _candidate_keys:
                m = self.options_channels.get(k)
                if isinstance(m, dict):
                    ch_keys.update(str(x) for x in m.keys())
            # 각 채널 키별로 가장 그럴싸한 스펙을 뽑아냄
            for ck in ch_keys:
                spec = self._extract_spec_for_channel(self.options_channels, ck)
                if spec is not None:
                    out_spec_map[str(ck)] = spec

            # 채널 (output_id, channel_idx)로 변환해서 캐시
            self.out_pairs = {}
            self.out_specs_raw = {}
            if isinstance(out_spec_map, dict):
                for ch_key, spec in out_spec_map.items():
                    self.out_specs_raw[str(ch_key)] = spec
                    oid, cidx = self._resolve_out_pair(spec)
                    if oid is not None and cidx is not None:
                        self.out_pairs[str(ch_key)] = (oid, cidx)
            # 펌프 채널 해석 (pair로 저장)
            try:
                pump_ch_id = self._read_raw_pump_spec()
                self.pump_pair = self._resolve_pump_pair_from_id(pump_ch_id)
            except Exception:
                self.pump_pair = (None, None)

        except Exception as e:
            self.logger.warning(f"[ValveTime] Channel options load failed: {e}")

        # Coerce malformed channel maps to dicts to avoid unpack errors
        if not isinstance(self.output_channels_dyn, dict):
            try:
                self.logger.warning('[ValveTime] output_channels_dyn is not a dict. Coercing to empty dict.')
            except Exception:
                pass
            self.output_channels_dyn = {}

    # ---- 실행 루프 ----
    def loop(self):
        # 주기 스케줄링
        now = time.time()
        cycle_start = now
        try:
            period_sec = float(getattr(self, 'period', 0) or 0)
        except Exception:
            period_sec = 0
        if period_sec <= 0:
            period_sec = 1.0  # 잘못된 설정으로 인한 바쁜 루프 방지

        if getattr(self, '_in_cycle', False):
            return

        self._in_cycle = True
        try:
            # --- Daily time-span gating (custom options: time_window_enabled, start_time, end_time) ---
            tw_enabled = str(getattr(self, 'time_window_enabled', 'False')).strip().lower() in ('true', '1', 'yes', 'y', '사용')
            _start_text = getattr(self, 'start_time', '') or ''
            _end_text = getattr(self, 'end_time', '') or ''
            # If user filled start/end text, treat gating as intended even if toggle is off
            gating_intended = tw_enabled or bool(str(_start_text).strip() or str(_end_text).strip())

            if gating_intended:
                start_s = _parse_hhmm_text_to_seconds(_start_text)
                end_s = _parse_hhmm_text_to_seconds(_end_text)
                if not (isinstance(start_s, int) and isinstance(end_s, int)):
                    # Configuration invalid → DO NOT RUN when gating is intended
                    try:
                        self.logger.warning("[ValveTime] Time-window intended but invalid config (start_time=%r, end_time=%r). Skipping this cycle.", _start_text, _end_text)
                    except Exception:
                        pass
                    self._next_run = now + period_sec
                    return

                now_s = _seconds_since_midnight(now)
                try:
                    self.logger.debug(f"[ValveTime] window ss={start_s} es={end_s} now_s={now_s}")
                except Exception:
                    pass

                def in_window(ns: int, ss: int, es: int) -> bool:
                    """
                    Return True if current seconds(ns) is within [ss, es] inclusively.
                    Handles both non-wrap (ss < es) and wrap (ss > es) windows.
                    If ss == es, treat as a 24h always-on window.
                    """
                    if ss == es:
                        return True
                    if ss < es:
                        return ss <= ns <= es
                    return ns >= ss or ns <= es

                in_now = in_window(now_s, start_s, end_s)
                # Clear schedule only on transition from OUTSIDE → INSIDE
                if in_now and not getattr(self, '_was_in_window', False):
                    self._next_run = 0.0
                self._was_in_window = in_now

                if not in_now:
                    # schedule next start boundary in local time and return
                    lt = time.localtime(now)
                    today_mid = now - (lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec)
                    next_start = today_mid + start_s
                    if start_s == end_s:
                        next_start = now + max(1.0, float(getattr(self, 'period', 1.0)))
                    else:
                        if start_s < end_s:
                            if now_s >= end_s:
                                next_start += 24 * 3600
                        else:
                            if now_s < start_s:
                                pass
                            else:
                                pass
                    try:
                        lt = time.localtime(next_start)
                        human = f"{lt.tm_year:04d}-{lt.tm_mon:02d}-{lt.tm_mday:02d} {lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}"
                        self.logger.info(f"[ValveTime] Outside window → next run at {human}")
                    except Exception:
                        pass
                    self._next_run = max(next_start, now + 1.0)
                    return
            else:
                # No gating intended → run regardless of time window
                pass

            # Schedule guard AFTER window handling so entering a window triggers the cycle immediately

            # Schedule guard AFTER window handling so entering a window triggers the cycle immediately
            if now < getattr(self, '_next_run', 0):
                return
            # 채널 구성 읽기
            dyn = getattr(self, 'options_channels', None)
            if isinstance(dyn, list):
                norm = {'enabled': {}, 'duration_min': {}, 'output': {}, 'output_channel_id': {}}
                for i, row in enumerate(dyn):
                    if not isinstance(row, dict):
                        continue
                    idx = row.get('index', i)
                    for k in ('enabled', 'duration_min', 'output', 'output_channel_id'):
                        if k in row:
                            norm[k][str(idx)] = row[k]
                dyn = norm
            # Defensive normalization for dyn: if not dict/list, coerce to empty dict
            if dyn is None:
                dyn = {}
            elif not isinstance(dyn, (dict, list)):
                self.logger.warning('[ValveTime] options_channels is %s; coercing to empty dict', type(dyn).__name__)
                dyn = {}
            if not dyn or not isinstance(dyn, dict):
                self.logger.info('[ValveTime] No dynamic channels configured.')
                self._next_run = now + period_sec
                return

            # (Optional debug: show runtime keys)
            try:
                self.logger.debug(f"[ValveTime] dyn keys={list(dyn.keys())}")
            except Exception:
                pass

            dyn_enabled = dyn.get('enabled') or {}
            dyn_duration = dyn.get('duration_min') or {}
            dyn_out_ch_specs = (dyn.get('output') or dyn.get('output_channel_id') or {}) if isinstance(dyn, dict) else {}

            # Guards: ensure dict types
            if not isinstance(dyn_enabled, dict):
                dyn_enabled = {}
            if not isinstance(dyn_duration, dict):
                dyn_duration = {}
            if not isinstance(dyn_out_ch_specs, dict):
                dyn_out_ch_specs = {}

            # On-demand reconstruction of dyn_out_ch_specs when empty or not a dict
            if not isinstance(dyn_out_ch_specs, dict) or not dyn_out_ch_specs:
                # 동적으로 스펙 맵을 구성 (관대한 키 지원)
                dyn_out_ch_specs = {}
                # 채널 키 후보군 만들기
                key_sources = []
                for _k, _v in dyn.items():
                    if isinstance(_v, dict):
                        key_sources.append(_v.keys())
                ch_keys_dyn = set(str(x) for ks in key_sources for x in ks)
                for ck in ch_keys_dyn:
                    spec = self._extract_spec_for_channel(dyn, ck)
                    if spec is not None:
                        dyn_out_ch_specs[str(ck)] = spec

            def _key_index(k):
                try:
                    return int(k)
                except Exception:
                    return 10 ** 9

            key_sets = [dyn_enabled.keys(), dyn_duration.keys(), dyn_out_ch_specs.keys()]
            all_keys = list({str(k) for ks in key_sets for k in ks})
            all_keys.sort(key=_key_index)

            def _is_enabled(v):
                if v is None:
                    return False
                if isinstance(v, bool):
                    return v
                if isinstance(v, (int, float)):
                    return v != 0
                s = str(v).strip().lower()
                return s in ('1', 'true', 'on', 'yes', 'y', '사용')

            try:
                min_runtime_sec = int(getattr(self, 'min_runtime_sec', 15) or 0)
            except Exception:
                min_runtime_sec = 15
            if min_runtime_sec < 0:
                min_runtime_sec = 0

            # 플랜 작성
            plan = []  # (key, out_id, ch_idx, sec)
            total_sec = 0
            for k in all_keys:
                en = dyn_enabled.get(k)
                if en is None:
                    try:
                        en = dyn_enabled.get(int(k))
                    except Exception:
                        en = None
                if not _is_enabled(en):
                    continue

                dur = dyn_duration.get(k)
                if dur is None:
                    try:
                        dur = dyn_duration.get(int(k))
                    except Exception:
                        dur = None

                # Use user-entered minutes as-is (normalize locale forms); skip if <= 0
                norm = None
                try:
                    if dur is None:
                        norm = ''
                    else:
                        s = str(dur).strip()
                        s = s.translate(str.maketrans('０１２３４５６７８９，．', '0123456789,.'))
                        s = s.replace(',', '.')
                        cleaned = []
                        dot_seen = False
                        for ch in s:
                            if ch.isdigit():
                                cleaned.append(ch)
                            elif ch == '.' and not dot_seen:
                                cleaned.append(ch)
                                dot_seen = True
                        norm = ''.join(cleaned)
                    dur_min = float(norm) if norm else 0.0
                except Exception:
                    dur_min = 0.0

                sec = int(dur_min * 60.0)
                if sec <= 0 or sec < min_runtime_sec:
                    continue

                # --- Fast resolution for this channel ---
                # Prefer cached pair; if absent, try current-cycle spec and cache it upon success
                out_id, ch_idx = self.out_pairs.get(str(k), (None, None))
                if (out_id is None) or (ch_idx is None):
                    spec_now = dyn_out_ch_specs.get(k)
                    if spec_now is None:
                        try:
                            spec_now = dyn_out_ch_specs.get(int(k))
                        except Exception:
                            spec_now = None
                    if spec_now is None:
                        # fallback to last-seen raw from init
                        spec_now = self.out_specs_raw.get(str(k))
                    if spec_now is not None:
                        oid2, cidx2 = self._resolve_out_pair(spec_now)
                        if oid2 is not None and cidx2 is not None:
                            out_id, ch_idx = oid2, cidx2
                            self.out_pairs[str(k)] = (out_id, ch_idx)
                            self.out_specs_raw[str(k)] = spec_now

                if (out_id is None) or (ch_idx is None):
                    self.logger.error(f"[ValveTime] Channel {k} unresolved pair; raw={self.out_specs_raw.get(str(k)) or dyn_out_ch_specs.get(k)}")
                    continue

                plan.append((k, out_id, ch_idx, sec))
                total_sec += sec

            if not plan:
                try:
                    # quick diagnostics: count reasons
                    _cnt_en = sum(1 for v in (dyn_enabled or {}).values() if v)
                    _cnt_dur = sum(1 for v in (dyn_duration or {}).values() if (float(str(v).replace(',', '.')) if str(v).strip() else 0.0) > 0.0)
                    self.logger.info('[ValveTime] Nothing to run this cycle. enabled_any=%s duration_any=%s (min_runtime_sec=%s)', bool(_cnt_en), bool(_cnt_dur), min_runtime_sec)
                except Exception:
                    self.logger.info('[ValveTime] Nothing to run this cycle.')
                self._next_run = now + period_sec
                return

            # 총합 시간이 period를 초과하면 스케일링 + 합계 보정
            if total_sec > int(period_sec) - 1:
                remain = int(period_sec) - 1
                if remain <= 0:
                    self.logger.warning('[ValveTime] total_sec(%s) > period(%s). Skipping cycle.', total_sec, period_sec)
                    self._next_run = now + period_sec
                    return
                ratio = float(remain) / float(total_sec)
                scaled = []
                # 1차 스케일
                for (k, oid, chidx, sec) in plan:
                    new_sec = max(min_runtime_sec, int(sec * ratio))
                    scaled.append([k, oid, chidx, new_sec])
                # 합계 보정
                adj_total = sum(x[3] for x in scaled)
                if adj_total > remain:
                    over = adj_total - remain
                    for x in reversed(scaled):
                        if over <= 0:
                            break
                        reducible = x[3] - min_runtime_sec
                        if reducible > 0:
                            d = min(reducible, over)
                            x[3] -= d
                            over -= d
                elif adj_total < remain and scaled:
                    under = remain - adj_total
                    i = 0
                    while under > 0:
                        x = scaled[i % len(scaled)]
                        x[3] += 1
                        under -= 1
                        i += 1
                plan = [(k, oid, chidx, sec) for (k, oid, chidx, sec) in scaled if sec >= min_runtime_sec]
                total_sec = sum(sec for _, _, _, sec in plan)
                if not plan:
                    self._next_run = now + period_sec
                    return

            try:
                self.logger.info(f"[ValveTime] Plan: {len(plan)} channel(s), total {total_sec}s")
            except Exception:
                pass

            # 펌프 동작 여부
            # 최신 옵션 반영: 루프마다 raw pump 스펙이 바뀌면 다시 해석
            raw_pump = None
            try:
                raw_pump = self._read_raw_pump_spec()
            except Exception:
                pass
            try:
                if raw_pump is not getattr(self, '_pump_raw_last', None):
                    self.pump_pair = self._resolve_pump_pair_from_id(raw_pump)
                    self._pump_raw_last = raw_pump
            except Exception:
                pass
            use_pump = str(getattr(self, 'use_pump_output', 'False')).lower() in ('true', '1', 'yes', 'y', '사용')

            # 펌프 ON (총합 시간)
            pump_started = False
            if use_pump and total_sec > 0:
                try:
                    pump_out_id, pump_ch_idx = getattr(self, 'pump_pair', (None, None))
                    if pump_out_id is not None and pump_ch_idx is not None:
                        self.control.output_on_off(pump_out_id, 'on', output_type='sec', amount=float(total_sec), output_channel=pump_ch_idx)
                        pump_started = True
                        self.logger.info(f'[ValveTime] Pump ON for {total_sec}s')
                    else:
                        raw_pump = self._read_raw_pump_spec()
                        try:
                            opt_keys = []
                            # attributes
                            for k in ('output_pump','pump_output','pump_channel','pump','output_pump_channel_id','output_pump_id'):
                                if hasattr(self, k):
                                    opt_keys.append(k)
                            # dict container
                            cont = getattr(self, 'custom_options', None)
                            if isinstance(cont, dict):
                                opt_keys.extend([f"custom_options.{k}" for k in cont.keys() if ('pump' in k and 'output' in k)])
                            # list container
                            cont_list = getattr(self, 'custom_options', None)
                            if isinstance(cont_list, list):
                                for row2 in cont_list:
                                    if isinstance(row2, dict) and 'id' in row2:
                                        rk = str(row2['id']).lower()
                                        if ('pump' in rk) and ('output' in rk):
                                            opt_keys.append(f"custom_options[{rk}]")
                        except Exception:
                            opt_keys = []
                        self.logger.error(f"[ValveTime] Pump pair unresolved; raw={raw_pump} (hint: set '펌프 출력'). Seen option keys={opt_keys}")
                except Exception as e:
                    self.logger.error(f'[ValveTime] Pump start failed: {e}')

            # 밸브 순차 실행
            for item in plan:
                try:
                    key, out_id, ch_idx, sec = item
                except Exception:
                    self.logger.error('[ValveTime] Invalid plan item during exec (skip): %r', item)
                    continue
                try:
                    self.logger.info(f"[ValveTime] RUN ch={key} output={out_id} channel={ch_idx} for {sec}s")
                except Exception:
                    pass
                try:
                    self.control.output_on_off(out_id, 'on', output_type='sec', amount=float(sec), output_channel=ch_idx)
                    time.sleep(sec)
                except Exception as e:
                    self.logger.error(f'[ValveTime] Channel {key} failed: {e}')
                # 안전 OFF
                try:
                    self.control.output_on_off(out_id, 'off', output_type='sec', amount=0, output_channel=ch_idx)
                except Exception:
                    pass

            # 펌프 OFF (명시)  
            if pump_started:
                try:
                    pump_out_id, pump_ch_idx = getattr(self, 'pump_pair', (None, None))
                    if pump_out_id is not None and pump_ch_idx is not None:
                        self.control.output_on_off(pump_out_id, 'off', output_type='sec', amount=0, output_channel=pump_ch_idx)
                        self.logger.info('[ValveTime] Pump OFF')
                except Exception:
                    pass

            # 다음 주기 예약: 주기는 사이클 시작 기준으로 고정 (행동 시간이 길어도 다음 시작은 주기 경과 후)
            self._next_run = cycle_start + period_sec
        finally:
            self._in_cycle = False
            return