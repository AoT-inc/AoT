# coding=utf-8
#
#  lorawan_mode_manager.py — RAK3172E Valve Controller 용 LoRaWAN 모드/주기 결정기(스켈레톤)
#
#  참고 구조: aot/functions/base_function.py, bang_bang_on_off.py
#
#  역할:
#    - 입력(배터리 mV, RSSI, SNR, 밸브활동 플래그, 현재 시각)을 바탕으로
#      목표 (mode, period_min)를 계산하고, 조건이 충족될 때만 적용(전송 훅 호출).
#    - 전송 훅은 이후 on_off_chirpstack.OutputModule에 연결(예: set_mode_period) 예정.
#
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from flask_babel import lazy_gettext

from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl
from aot.utils.constraints_pass import constraints_pass_positive_value

from aot.utils.database import db_retrieve_table_daemon
import grpc
from chirpstack_api import api as cs_api
import math

import copy
from aot.inputs.sensorutils import convert_from_x_to_y_unit
from aot.utils.influx import add_measurements_influxdb
from aot.utils.system_pi import return_measurement_info

measurements_dict = {
    0: {
        'measurement': 'rssi',
        'unit': 'dBm'
    },
    1: {
        'measurement': 'snr',
        'unit': 'dB'
    },
    2: {
        'measurement': 'electrical_potential',
        'unit': 'mV'
    }
}

# --- Minimal RAK3172 valve codec (HB / HB-EXT / CFG-ACK) --------------------
SIG_HB = 0xA5
SIG_HB_EXT = 0xA6
SIG_CFG_ACK = 0xD1

def _to_bytes(data):
    if data is None:
        return b""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, str):
        s = data.strip()
        # try hex first
        try:
            return bytes.fromhex(s)
        except Exception:
            return s.encode("utf-8", errors="replace")
    try:
        return bytes(data)
    except Exception:
        return b""

def _le32(b0, b1, b2, b3):
    return (b0 & 0xFF) | ((b1 & 0xFF) << 8) | ((b2 & 0xFF) << 16) | ((b3 & 0xFF) << 24)

def decode_uplink(f_port: int, payload) -> dict:
    """
    Returns a dict describing the message.
    Recognizes:
      - FPort=14, [0xD1,mode,period] -> {'kind':'cfg_ack', 'mode':m, 'period_min':p}
      - FPort=225, 0xA5 base (len 6 or 8) -> {'kind':'hb', 'uptime':..., 'flags':..., 'vbat_mV':int|None}
      - FPort=225, 0xA6 ext (len 13) -> {'kind':'hb_ext', 'uptime':..., 'flags':..., 'last_error':..., 'warn':{...}}
    Unknowns return {}.
    """
    try:
        b = _to_bytes(payload)
        if not isinstance(f_port, int):
            try:
                f_port = int(f_port)
            except Exception:
                return {}
        n = len(b)
        if f_port == 14 and n >= 3 and b[0] == SIG_CFG_ACK:
            return {'kind': 'cfg_ack', 'mode': int(b[1]), 'period_min': int(b[2])}

        if f_port == 225 and n >= 1 and b[0] in (SIG_HB, SIG_HB_EXT):
            sig = b[0]
            if sig == SIG_HB and n in (6, 8):
                up = _le32(b[1], b[2], b[3], b[4])
                flags = int(b[5])
                vbat = None
                if n == 8:
                    vbat = ((b[6] & 0xFF) << 8) | (b[7] & 0xFF)
                return {'kind': 'hb', 'uptime': up, 'flags': flags, 'vbat_mV': vbat}
            if sig == SIG_HB_EXT and n == 13:
                up = _le32(b[1], b[2], b[3], b[4])
                flags = int(b[5])
                last_err = int(b[6])
                warn_i2c_w = ((b[7] & 0xFF) << 8) | (b[8] & 0xFF)
                warn_i2c_r = ((b[9] & 0xFF) << 8) | (b[10] & 0xFF)
                warn_gpio  = ((b[11] & 0xFF) << 8) | (b[12] & 0xFF)
                return {'kind': 'hb_ext', 'uptime': up, 'flags': flags, 'last_error': last_err,
                        'warn': {'i2c_w': warn_i2c_w, 'i2c_r': warn_i2c_r, 'gpio': warn_gpio}}
        return {}
    except Exception:
        return {}


FUNCTION_INFORMATION = {
    'function_name_unique': 'lorawan_mode_manager',
    'function_name': 'LoRaWAN 모드/주기 관리자 (RAK3172E)',
    'function_name_short': 'LoRa 모드 관리자',
    'measurements_dict': measurements_dict,

    'message': '배터리·시간대·밸브활동·링크품질을 기준으로 Class/하트비트 주기를 결정합니다. '
               '조건이 충족될 때만 전송 훅을 호출합니다(스켈레톤).',

    'options_enabled': [
        'measurements_configure',
        'custom_options'
    ],

    'custom_options': [
        # ======================= 시스템(연결/실행) 우선 =======================
        # ---- API 사용/연결 설정 ----
        {
            'id': 'api_enabled',
            'type': 'bool',
            'default_value': True,
            'required': True,
            'name': 'API 조회 사용',
            'phrase': '업링크/링크메타를 API로 확인'
        },
        {
            'id': 'cs_server',
            'type': 'text',
            'default_value': '127.0.0.1:8080',
            'required': False,
            'name': 'ChirpStack gRPC 서버',
            'phrase': '호스트:포트 형식 (예: 127.0.0.1:8080) 또는 http(s)://호스트:포트'
        },
        {
            'id': 'cs_api_token',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'API Key',
            'phrase': 'JWT 토큰 값을 입력하세요 (Bearer 제외)'
        },
        {
            'id': 'dev_eui',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'DevEUI',
            'phrase': '16자리 16진수 DevEUI (구분자 허용)'
        },
        {
            'id': 'api_pull_window_s',
            'type': 'integer',
            'default_value': 600,
            'required': True,
            'name': 'API 조회 윈도(초)',
            'phrase': '최근 업링크만 유효(초)'
        },
        {
            'id': 'api_required',
            'type': 'bool',
            'default_value': False,
            'required': True,
            'name': 'API 데이터 필수',
            'phrase': 'API로 신선한 데이터가 없으면 적용하지 않음'
        },

        # ---- CFG 전송 대상(Output) ----
        {
            'id': 'output_cfg',
            'type': 'select_measurement_channel',
            'default_value': '',
            'required': True,
            'options_select': ['Output_Channels_Measurements'],
            'name': '대상 Output (CFG 전송)',
            'phrase': '모드/주기 설정을 보낼 Output(예: ChirpStack gRPC)을 선택'
        },

        # ---- 측정/루프 기본 파라미터 ----
        {
            'id': 'measurement_max_age',
            'type': 'integer',
            'default_value': 600,
            'required': True,
            'name': "{}: {} ({})".format(lazy_gettext("Measurement"), lazy_gettext("Max Age"), lazy_gettext("Seconds")),
            'phrase': lazy_gettext('사용할 측정치의 최대 허용 연령(초)')
        },
        {
            'id': 'update_period',
            'type': 'float',
            'default_value': 30,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('Period'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('판정 및 적용 주기(초)')
        },
        {
            'id': 'apply_only_when_valid',
            'type': 'bool',
            'default_value': True,
            'required': True,
            'name': '유효할 때만 작동',
            'phrase': '입력 조건/측정값이 유효할 때만 모드 적용'
        },
        {
            'id': 'store_nan_when_no_data',
            'type': 'bool',
            'default_value': False,
            'required': True,
            'name': 'Store NaN when no data',
            'phrase': 'If no fresh API/telemetry is available, write NaN placeholders to measurements'
        },

        # ======================= 기능(정책/판정) 우선 =======================
        # ---- 운영 시간대 ----
        {
            'id': 'day_start_hour',
            'type': 'integer',
            'default_value': 5,
            'required': True,
            'name': '주간 시작(시)',
            'phrase': '밸브 운영 시작 시각 (0–23)'
        },
        {
            'id': 'day_end_hour',
            'type': 'integer',
            'default_value': 18,
            'required': True,
            'name': '주간 종료(시)',
            'phrase': '밸브 운영 종료 시각 (0–23)'
        },

        # ---- 주기(Class 별) ----
        {
            'id': 'a01_period_min',
            'type': 'integer',
            'default_value': 15,
            'required': True,
            'name': 'A-01 하트비트(분)',
            'phrase': 'Class A-01(절전) 업링크 주기(분)'
        },
        {
            'id': 'a02_period_min',
            'type': 'integer',
            'default_value': 60,
            'required': True,
            'name': 'A-02 하트비트(분)',
            'phrase': 'Class A-02(초절전) 업링크 주기(분)'
        },
        {
            'id': 'c01_period_min',
            'type': 'integer',
            'default_value': 30,
            'required': True,
            'name': 'C-01 하트비트(분)',
            'phrase': 'Class C-01(성능) 업링크 주기(분)'
        },

        # ---- 배터리 임계 ----
        {
            'id': 'vbat_low_mv',
            'type': 'integer',
            'default_value': 12100,
            'required': True,
            'name': '저전압 임계(mV)',
            'phrase': '이하이면 A-02로 강등'
        },
        {
            'id': 'vbat_recover_mv',
            'type': 'integer',
            'default_value': 12300,
            'required': True,
            'name': '전압 회복 임계(mV)',
            'phrase': '이상이면 절전에서 복귀 허용'
        },
        {
            'id': 'vbat_critical_mv',
            'type': 'integer',
            'default_value': 11900,
            'required': True,
            'name': '치명적 저전압 임계(mV)',
            'phrase': '이하이면 통신 최소화(알림 권고)'
        },

        # ---- 링크 품질 임계 ----
        {
            'id': 'link_rssi_min',
            'type': 'integer',
            'default_value': -110,
            'required': True,
            'name': '링크 RSSI 최소(dBm)',
            'phrase': '이상일 때 링크 양호로 간주'
        },
        {
            'id': 'link_snr_min',
            'type': 'integer',
            'default_value': -10,
            'required': True,
            'name': '링크 SNR 최소(dB)',
            'phrase': '이상일 때 링크 양호로 간주'
        }
    ]
}


# ----- 모드/주기 계산 로직(순수 함수) -----
MODE_A01 = 1
MODE_A02 = 2
MODE_C01 = 3

@dataclass
class ModeOpts:
    day_start_hour: int = 5
    day_end_hour: int = 18
    a01_period_min: int = 15
    a02_period_min: int = 60
    c01_period_min: int = 30
    vbat_low_mv: int = 12100
    vbat_recover_mv: int = 12300
    vbat_critical_mv: int = 11900
    link_rssi_min: int = -110
    link_snr_min: int = -10


def _is_daytime(now_hour: int, s: int, e: int) -> bool:
    if s <= e:
        return s <= now_hour < e
    return (now_hour >= s) or (now_hour < e)


def compute_target_mode_period(
    *,
    vbat_mV: Optional[int],
    now_hour: int,
    valve_active: bool,
    link_rssi: Optional[float],
    link_snr: Optional[float],
    o: ModeOpts
) -> Tuple[int, int, str]:
    # 1) 배터리 우선
    if vbat_mV is not None:
        if vbat_mV <= o.vbat_critical_mv:
            return MODE_A02, max(60, o.a02_period_min), "critical_battery"
        if vbat_mV <= o.vbat_low_mv:
            return MODE_A02, o.a02_period_min, "low_battery"

    day = _is_daytime(now_hour, o.day_start_hour, o.day_end_hour)

    link_ok = True
    if link_rssi is not None:
        link_ok &= (link_rssi > o.link_rssi_min)
    if link_snr is not None:
        link_ok &= (link_snr > o.link_snr_min)

    if day:
        if valve_active:
            if vbat_mV is not None and vbat_mV < o.vbat_recover_mv:
                return MODE_A01, o.a01_period_min, "day_active_batt_not_recovered"
            if not link_ok:
                return MODE_A01, o.a01_period_min, "day_active_link_poor"
            return MODE_C01, o.c01_period_min, "day_active_perf"
        else:
            return MODE_A01, o.a01_period_min, "day_idle_a01"
    else:
        return MODE_A02, o.a02_period_min, "night_a02"


class CustomModule(AbstractFunction):
    """
    AoT Function: LoRaWAN 모드/주기 결정 + 적용(스켈레톤)
    - base_function / bang_bang_on_off 스타일을 따름
    - 서버는 조건 유효 시에만 동작(게이트 내장)
    """
    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)
        self.control = DaemonControl()
        self.timer_loop = time.time()

        # 옵션 바인딩
        custom_function = db_retrieve_table_daemon(CustomController, unique_id=self.unique_id)
        self.setup_custom_options(FUNCTION_INFORMATION['custom_options'], custom_function)

        # 내부 캐시
        self._last_applied = None  # (mode, period)
        # Internal telemetry cache for direct uplink routing
        self._tel = {'updated_at': 0.0}
        # Throttle for repeated "no target" logs
        self._no_target_throttle_ts = 0.0

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.logger.info("LoRaWAN mode manager started")

    # --- 유틸: 최신 측정값 취득(없으면 None) ---
    def _get_measurement_val(self, sel, max_age):
        if not sel:
            return None
        try:
            dev_id, meas_id = sel.get('device_id'), sel.get('measurement_id')
            last = self.get_last_measurement(dev_id, meas_id, max_age=max_age)
            if not last:
                return None
            return float(last[1])
        except Exception:
            return None

    def _now_hour_local(self):
        # 서버 로컬 시간을 사용(필요시 타임존 옵션 추가 가능)
        return time.localtime().tm_hour

    def _opts(self) -> ModeOpts:
        def gi(k, d):  # get int
            try:
                v = int(getattr(self, k))
            except Exception:
                v = d
            return v
        return ModeOpts(
            day_start_hour = gi('day_start_hour', 5),
            day_end_hour   = gi('day_end_hour', 18),
            a01_period_min = gi('a01_period_min', 15),
            a02_period_min = gi('a02_period_min', 60),
            c01_period_min = gi('c01_period_min', 30),
            vbat_low_mv    = gi('vbat_low_mv', 12100),
            vbat_recover_mv= gi('vbat_recover_mv', 12300),
            vbat_critical_mv=gi('vbat_critical_mv', 11900),
            link_rssi_min  = gi('link_rssi_min', -110),
            link_snr_min   = gi('link_snr_min', -10),
        )

    # --- Helpers (on_off_chirpstack style) ---------------------------------
    def _normalize_server(self):
        srv = (getattr(self, 'cs_server', '') or '').strip()
        if '://' in srv:
            srv = srv.split('://', 1)[1]
        srv = srv.split('/', 1)[0]
        return srv

    def _normalize_token(self):
        tok = (getattr(self, 'cs_api_token', '') or '').strip()
        if tok.lower().startswith('bearer '):
            tok = tok[7:].strip()
        return tok

    def _normalize_deveui(self):
        dev = (getattr(self, 'dev_eui', '') or '').strip()
        dev = ''.join(ch for ch in dev if ch.isalnum())
        return dev.lower()

    # --- API polling (skeleton) --------------------------------------------
    def _fetch_latest_rxmeta_via_api(self):
        """
        Placeholder: poll ChirpStack gRPC/REST for the latest uplink of this DevEUI and
        return a dict like {'vbat_mV': int|None, 'rssi': float|None, 'snr': float|None, 'ts': epoch}.
        This skeleton only validates configuration and returns None.
        """
        try:
            if not bool(getattr(self, 'api_enabled', True)):
                return None
            server = self._normalize_server()
            token  = self._normalize_token()
            deveui = self._normalize_deveui()
            if not server or not token or not deveui:
                return None
            # TODO: Implement actual gRPC/REST call here (left intentionally blank).
            return None
        except Exception:
            return None

    # --- Optional direct uplink ingestion (function-level) -------------------
    def ingest_uplink(self, f_port, data, rxmeta=None):
        """
        Allow AoT bus to route device uplinks directly to this Function.
        Decodes RAK3172 heartbeat/ack frames and refreshes internal telemetry.
        rxmeta may contain e.g. {'rssi': -105.0, 'snr': -7.5}.
        """
        try:
            msg = decode_uplink(f_port, data)
            if not msg:
                return
            now = time.time()
            if not isinstance(self._tel, dict):
                self._tel = {}
            self._tel.setdefault('updated_at', 0.0)
            kind = msg.get('kind')
            if kind == 'cfg_ack':
                self._tel['cfg_mode'] = msg.get('mode')
                self._tel['cfg_period_min'] = msg.get('period_min')
                self._tel['updated_at'] = now
            elif kind == 'hb':
                if msg.get('vbat_mV') is not None:
                    self._tel['vbat_mV'] = int(msg['vbat_mV'])
                self._tel['uptime'] = msg.get('uptime')
                self._tel['flags'] = msg.get('flags')
                self._tel['updated_at'] = now
            elif kind == 'hb_ext':
                self._tel['uptime'] = msg.get('uptime')
                self._tel['flags'] = msg.get('flags')
                self._tel['last_error'] = msg.get('last_error')
                warn = msg.get('warn') or {}
                self._tel['warn_i2c_w'] = warn.get('i2c_w')
                self._tel['warn_i2c_r'] = warn.get('i2c_r')
                self._tel['warn_gpio']  = warn.get('gpio')
                self._tel['updated_at'] = now
            if isinstance(rxmeta, dict):
                if 'rssi' in rxmeta: self._tel['rssi'] = rxmeta['rssi']
                if 'snr'  in rxmeta: self._tel['snr']  = rxmeta['snr']
                self._tel['updated_at'] = now
        except Exception:
            pass

    # Match Output's routing name so the bus can call this function the same way
    on_device_uplink = ingest_uplink

    # --- 조건이 충족할 때만 전송 훅 호출 ---
    def loop(self):
        if self.timer_loop > time.time():
            return
        while self.timer_loop < time.time():
            self.timer_loop += float(self.update_period)

        # 적용 경로 결정: Output 또는 직접 API (둘 중 하나만 있어도 진행)
        # 1) Output 경로 확인
        cfg = None
        try:
            cfg = getattr(self, 'output_cfg', None)
        except Exception:
            cfg = None
        if not cfg:
            try:
                cfg = (getattr(self, 'options_custom', {}) or {}).get('output_cfg') \
                    or (getattr(self, 'custom_options', {}) or {}).get('output_cfg')
            except Exception:
                cfg = None

        # 2) API 경로 확인
        api_can_apply = False
        try:
            api_can_apply = bool(getattr(self, 'api_enabled', True)) \
                            and bool(self._normalize_server()) \
                            and bool(self._normalize_token()) \
                            and bool(self._normalize_deveui())
        except Exception:
            api_can_apply = False

        if (not cfg or cfg == '') and not api_can_apply:
            now_ts = time.time()
            if bool(getattr(self, 'api_required', False)):
                # Strict mode: error when API data is required but nothing configured
                self.logger.error("No Output/API configured -> skipping (api_required=True)")
            else:
                # Throttle noisy logs to once per 5 minutes
                if (now_ts - getattr(self, '_no_target_throttle_ts', 0.0)) >= 300.0:
                    self.logger.warning("No Output/API configured -> skipping (set API options or Output)")
                    self._no_target_throttle_ts = now_ts
            return

        max_age = int(self.measurement_max_age)

        # Prefer direct telemetry from uplink (fresh cache) over Inputs/API
        use_tel = False
        tel_vbat = tel_rssi = tel_snr = None
        try:
            tel = getattr(self, '_tel', {}) or {}
            upd = float(tel.get('updated_at', 0.0) or 0.0)
            if upd > 0 and (time.time() - upd) <= max_age:
                tel_vbat = tel.get('vbat_mV')
                tel_rssi = tel.get('rssi')
                tel_snr  = tel.get('snr')
                use_tel = True
        except Exception:
            pass

        # Use telemetry first; otherwise try API polling; no Input selection needed
        vbat = rssi = snr = None
        if use_tel:
            vbat, rssi, snr = tel_vbat, tel_rssi, tel_snr
        else:
            pull = self._fetch_latest_rxmeta_via_api()
            if pull:
                # Check recency against api_pull_window_s
                try:
                    win = int(getattr(self, 'api_pull_window_s', 600))
                except Exception:
                    win = 600
                ts = float(pull.get('ts', 0.0) or 0.0)
                if ts <= 0 or (time.time() - ts) <= max(1, win):
                    vbat = pull.get('vbat_mV')
                    rssi = pull.get('rssi')
                    snr  = pull.get('snr')

        # Valve activity: if not provided by API/telemetry, assume idle (False)
        valve_active = False

        # --- Save measurements to DB (AoT_VPD style) -----------------------
        try:
            measurement_dict = copy.deepcopy(measurements_dict)

            # Defensive: ensure channels are prepared by AoT (populated from measurements_dict)
            _cm = getattr(self, 'channels_measurement', None)
            _cc = getattr(self, 'channels_conversion', None)
            if not _cm or not _cc:
                # Fallback: store with measurements_dict names/units directly so time-series exists
                self.logger.debug("measurements not configured yet -> fallback save using measurements_dict")

                def _fallback_set(idx, value):
                    if value is None:
                        return
                    meta = measurements_dict.get(idx, {})
                    mname = meta.get('measurement', f'idx_{idx}')
                    munit = meta.get('unit', '')
                    measurement_dict[idx] = {
                        'measurement': mname,
                        'unit': munit,
                        'value': value
                    }

                _fallback_set(0, rssi)
                _fallback_set(1, snr)
                _fallback_set(2, vbat)

                should_push = any(isinstance(measurement_dict.get(i, {}), dict) and ('value' in measurement_dict.get(i, {}))
                                  for i in (0, 1, 2))
                if not should_push and bool(getattr(self, 'store_nan_when_no_data', False)):
                    # Write NaN placeholders to keep the time series alive during testing
                    for idx in (0, 1, 2):
                        meta = measurements_dict.get(idx, {})
                        mname = meta.get('measurement', f'idx_{idx}')
                        munit = meta.get('unit', '')
                        measurement_dict[idx] = {
                            'measurement': mname,
                            'unit': munit,
                            'value': float('nan')
                        }
                    should_push = True
                    self.logger.debug("no data available -> storing NaN placeholders (fallback)")
                if should_push:
                    self.logger.debug(f"saving measurements (fallback) -> {measurement_dict}")
                    add_measurements_influxdb(self.unique_id, measurement_dict)
            else:
                # helper to write a single index if value is present
                def _set_idx(idx, value, src_unit):
                    if value is None:
                        return
                    # channels_measurement[idx] / channels_conversion[idx] provide target unit/name
                    dev_meas = self.channels_measurement[idx]
                    ch, unit_target, measurement_name = return_measurement_info(
                        dev_meas, self.channels_conversion[idx]
                    )
                    # Try unit conversion when possible; otherwise pass-through
                    try:
                        if unit_target == src_unit:
                            val_store = value
                        else:
                            val_store = convert_from_x_to_y_unit(src_unit, unit_target, value)
                    except Exception:
                        val_store = value  # fallback: store raw
                    measurement_dict[idx] = {
                        'measurement': measurement_name,
                        'unit': unit_target,
                        'value': val_store
                    }

                # Index mapping: 0=RSSI(dBm), 1=SNR(dB), 2=Battery(mV)
                _set_idx(0, rssi, 'dBm')
                _set_idx(1, snr,  'dB')
                _set_idx(2, vbat, 'mV')

                # Only push if at least one value was set (has 'value' key)
                should_push = any(isinstance(measurement_dict.get(i, {}), dict) and ('value' in measurement_dict.get(i, {}))
                                  for i in (0, 1, 2))
                if not should_push and bool(getattr(self, 'store_nan_when_no_data', False)):
                    # Write NaN placeholders so charts don't have gaps during testing
                    for idx in (0, 1, 2):
                        dev_meas = self.channels_measurement[idx]
                        ch, unit_target, measurement_name = return_measurement_info(
                            dev_meas, self.channels_conversion[idx]
                        )
                        measurement_dict[idx] = {
                            'measurement': measurement_name,
                            'unit': unit_target,
                            'value': float('nan')
                        }
                    should_push = True
                    self.logger.debug("no data available -> storing NaN placeholders (channels)")
                if should_push:
                    self.logger.debug(f"saving measurements -> {measurement_dict}")
                    add_measurements_influxdb(self.unique_id, measurement_dict)
        except Exception as e:
            try:
                self.logger.debug(f"measurements save skipped/error: {e}")
            except Exception:
                pass

        # 게이트: 유효 입력이 하나도 없고 apply_only_when_valid=True 이면 skip
        if self.apply_only_when_valid:
            if vbat is None and rssi is None and snr is None and not valve_active:
                # If API is required, make that explicit in the log
                if bool(getattr(self, 'api_required', False)):
                    self.logger.debug("No fresh API/telemetry data -> skipping (api_required=True)")
                else:
                    self.logger.debug("No valid inputs -> skipping")
                return

        # 목표 계산
        try:
            mode, period, reason = compute_target_mode_period(
                vbat_mV=None if vbat is None else int(vbat),
                now_hour=self._now_hour_local(),
                valve_active=valve_active,
                link_rssi=rssi,
                link_snr=snr,
                o=self._opts()
            )
        except Exception as e:
            self.logger.error(f"판정 실패: {e}")
            return

        # 중복 적용 방지(같은 설정이면 스킵)
        if self._last_applied == (mode, period):
            self.logger.debug(f"No change (mode={mode}, period={period}) -> skip [{reason}]")
            return

        ok = self._apply_mode_period(mode, period)
        if ok:
            self._last_applied = (mode, period)
            self.logger.info(f"Applied: mode={mode}, period_min={period} [{reason}]")
        else:
            self.logger.warning(f"Apply failed: mode={mode}, period_min={period} [{reason}]")

    def _apply_mode_period(self, mode: int, period_min: int) -> bool:
        try:
            # 1) Direct API path via ChirpStack gRPC (preferred when configured)
            server = self._normalize_server()
            token  = self._normalize_token()
            deveui = self._normalize_deveui()
            if server and token and deveui:
                payload = bytes([0xD0, int(mode) & 0xFF, int(period_min) & 0xFF])
                channel = grpc.insecure_channel(server)
                client = cs_api.DeviceServiceStub(channel)
                md = [("authorization", f"Bearer {token}")]
                req = cs_api.EnqueueDeviceQueueItemRequest()
                req.queue_item.dev_eui   = deveui
                req.queue_item.f_port    = 14
                req.queue_item.confirmed = False
                req.queue_item.data      = payload
                client.Enqueue(req, metadata=md)
                return True

            # 2) Output path using configured output_cfg
            cfg = None
            try:
                cfg = getattr(self, 'output_cfg', None)
            except Exception:
                cfg = None
            if not cfg:
                try:
                    cfg = (getattr(self, 'options_custom', {}) or {}).get('output_cfg') \
                          or (getattr(self, 'custom_options', {}) or {}).get('output_cfg')
                except Exception:
                    cfg = None

            if isinstance(cfg, dict):
                dev_id = cfg.get('device_id')
                ch_id  = cfg.get('measurement_id') or cfg.get('channel')
                # 2a) Try typed method: set_mode_period
                try:
                    ok = bool(self.control.output_call(dev_id, ch_id, method='set_mode_period',
                                                       kwargs={'mode': int(mode), 'period_min': int(period_min)}))
                except Exception:
                    ok = False
                if ok:
                    return True
                # 2b) Fallback to generic hex enqueue if available
                hex_payload = bytes([0xD0, int(mode) & 0xFF, int(period_min) & 0xFF]).hex()
                try:
                    ok = bool(self.control.output_call(dev_id, ch_id, method='enqueue_hex',
                                                       kwargs={'f_port': 14, 'hex': hex_payload, 'confirmed': False}))
                except Exception:
                    ok = False
                if ok:
                    return True

            return False
        except Exception as e:
            try:
                self.logger.error(f"CFG enqueue error: {e}")
            except Exception:
                pass
            return False

    def stop_function(self):
        # 종료 시 별도 동작 없음
        pass