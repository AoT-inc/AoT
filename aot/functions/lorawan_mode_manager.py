# coding=utf-8
#
#  lorawan_mode_manager.py — RAK3172E Valve Controller 용 LoRaWAN 모드/주기 결정기(스켈레톤)
#
#  참고 구조: aot/functions/base_function.py, bang_bang_on_off.py
#
#  역할:
#    - 입력(배터리 V, RSSI, SNR, 밸브활동 플래그, 현재 시각)을 바탕으로
#      목표 (mode, period_min)를 계산하고, 조건이 충족될 때만 적용(전송 훅 호출).
#    - 전송 훅은 이후 on_off_chirpstack.OutputModule에 연결(예: set_mode_period) 예정.
# Copyright (c) 2025, AoT Project Authors. All rights reserved.
# 2025-11-03

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Tuple

import requests

from flask_babel import lazy_gettext

from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl
from aot.utils.constraints_pass import constraints_pass_positive_value

from aot.utils.database import db_retrieve_table_daemon

try:
    import grpc  # type: ignore[import-not-found]
except ModuleNotFoundError:
    grpc = None

try:
    from chirpstack_api import api as cs_api  # type: ignore[import-not-found]
except ModuleNotFoundError:
    cs_api = None

FUNCTION_INFORMATION = {
    'function_name_unique': 'lorawan_mode_manager',
    'function_name': 'LoRaWAN 모드/주기 관리자 (RAK3172E)',
    'function_name_short': 'LoRa 모드 관리자',

    'message': '배터리·시간대·밸브활동·링크품질을 기준으로 Class/하트비트 주기를 결정합니다. ChirpStack gRPC(DeviceService.Enqueue)를 통해 직접 다운링크를 큐잉합니다.',

    'options_enabled': [
        'measurements_configure',
        'custom_options'
    ],
    'custom_commands': {},

    'custom_options': [
        {
            'id': 'update_period',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 60,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('Period'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('판정 및 적용 주기(초)')
        },
        {
            'type': 'message',
            'default_value': '<b>서버 연결</b>'
        },
        {
            'id': 'cs_server',
            'type': 'text',
            'default_value': '127.0.0.1:8080',
            'required': True,
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
            'required': True,
            'name': 'DevEUI',
            'phrase': '16자리 16진수 DevEUI (구분자 허용)'
        },
        {
            'type': 'new_line'
        },
        {
            'type': 'message',
            'default_value': '<b>측정 입력</b>'
        },
        {
            'id': 'input_vbat',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input'],
            'name': '배터리 측정',
            'phrase': '배터리 전압(V) 측정값을 선택합니다.'
        },
        {
            'id': 'input_rssi',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input'],
            'name': 'RSSI 측정',
            'phrase': 'RSSI(주파수세기, dBm) 측정값을 선택합니다.'
        },
        {
            'id': 'input_snr',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input'],
            'name': 'SNR 측정',
            'phrase': 'SNR(노이즈비율, dB) 측정값을 선택합니다.'
        },
        {
            'id': 'input_node_class',
            'type': 'select_measurement',
            'default_value': '',
            'required': False,
            'options_select': ['Input'],
            'name': '엔드노드 클래스',
            'phrase': 'HB에서 추출한 현재 장치 클래스(1=A,2=B,3=C) 측정값'
        },
        {
            'id': 'measurement_max_age',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 4000,
            'required': True,
            'name': "{}: {} ({})".format(lazy_gettext('Measurement'), lazy_gettext('Max Age'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('사용할 측정치의 최대 허용 연령(초)')
        },
        {
            'id': 'retry_interval_min',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': '재시도 간격(분)',
            'phrase': 'ACK가 없을 때 동일 모드를 다시 적용할 간격(0이면 재시도 안 함)'
        },
        {
            'id': 'class_c_policy',
            'type': 'select',
            'default_value': 'auto',
            'required': True,
            'options_select': [
                ('auto', '자동'),
                ('force_class_a', 'CLASS-A'),
                ('force_class_b', 'CLASS-B'),
                ('force_class_c', 'CLASS-C')
            ],
            'name': 'LoRa 클래스 정책',
            'phrase': '자동일 때만 모드에 따라 Class를 전환하며, 특정 클래스를 선택하면 그 클래스를 유지합니다.'
        },
        {
            'id': 'apply_only_when_valid',
            'type': 'bool',
            'default_value': False,
            'required': True,
            'name': '입력값 유효 시에만 모드 전환',
            'phrase': '입력 조건/측정값이 유효할 때만 모드 적용'
        },

        {
            'type': 'new_line'
        },
        {
            'type': 'message',
            'default_value': '<b>운영 시간대</b><br/><small>성능 모드로 작동할 시간을 설정 합니다. 0~24 입력 또는 시작과 종료시간이 같으면 24시간</small>'
        },
        {
            'id': 'day_start_hour',
            'type': 'integer',
            'default_value': 4,
            'required': True,
            'name': '성능 모드 시작(시)',
            'phrase': '성능 모드 시작 시각 (0–23)'
        },
        {
            'id': 'day_end_hour',
            'type': 'integer',
            'default_value': 18,
            'required': True,
            'name': '성능 모드 종료(시)',
            'phrase': '성능 모드 종료 시각 (0–23)'
        },
        {
            'id': 'perf_lead_min',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': '성능 모드 선행(분)',
            'phrase': '주간 시작 전에 미리 성능(Class C) 모드로 전환할 시간을 분 단위로 지정합니다.'
        },
        {
            'type': 'new_line'
        },
        {
            'type': 'message',
            'default_value': '<b>모드별 HB 주기</b><br/><small>모드 별 하트비트 주기를 설정 합니다.</small>'
        },
        {
            'id': 'c_mode_class',
            'type': 'select',
            'default_value': 'C',
            'required': True,
            'options_select': [
                ('A', 'Class A'),
                ('B', 'Class B'),
                ('C', 'Class C')
            ],
            'name': '성능 모드 클래스',
            'phrase': '성능(C) 정책일 때 펌웨어에 적용할 LoRa 클래스'
        },
        {
            'id': 'b_mode_class',
            'type': 'select',
            'default_value': 'B',
            'required': True,
            'options_select': [
                ('A', 'Class A'),
                ('B', 'Class B'),
                ('C', 'Class C')
            ],
            'name': '절전 모드 클래스',
            'phrase': '절전(B) 정책일 때 펌웨어에 적용할 LoRa 클래스'
        },
        {
            'id': 'a_mode_class',
            'type': 'select',
            'default_value': 'B',
            'required': True,
            'options_select': [
                ('A', 'Class A'),
                ('B', 'Class B'),
                ('C', 'Class C')
            ],
            'name': '초절전 모드 클래스',
            'phrase': '초절전(A) 정책일 때 펌웨어에 적용할 LoRa 클래스'
        },
        {
            'id': 'c_period_min',
            'type': 'integer',
            'default_value': 30,
            'required': True,
            'name': '성능 하트비트(분)',
            'phrase': '성능(C) 모드 하트비트 주기(분)'
        },
        {
            'id': 'b_period_min',
            'type': 'integer',
            'default_value': 30,
            'required': True,
            'name': '절전 하트비트(분)',
            'phrase': '절전(B) 모드 하트비트 주기(분)'
        },
        {
            'id': 'a_period_min',
            'type': 'integer',
            'default_value': 60,
            'required': True,
            'name': '초절전 하트비트(분)',
            'phrase': '초절전(A) 모드 하트비트 주기(분)'
        },


        {
            'type': 'new_line'
        },
        {
            'type': 'message',
            'default_value': '<b>임계값 옵션</b><br/><small>모드 전환 임계값을 설정 합니다.</small>'
        },
        {
            'id': 'battery_policy_enabled',
            'type': 'bool',
            'default_value': False,
            'required': True,
            'name': '배터리 관리',
            'phrase': '배터리 전압에 따라 모드를 자동으로 전환합니다. (LoRa 클래스 정책이 자동일 때만 동작)'
        },
        {
            'id': 'vbat_recover_v',
            'type': 'float',
            'default_value': 12.00,
            'required': True,
            'name': '성능 모드 임계(V)',
            'phrase': '안정적인 운영이 가능한 전압 기준'
        },
        {
            'id': 'vbat_low_v',
            'type': 'float',
            'default_value': 11.70,
            'required': True,
            'name': '절전 임계(V)',
            'phrase': '절전 모드로 전환하는 전압 기준'
        },
        {
            'id': 'vbat_critical_v',
            'type': 'float',
            'default_value': 11.40,
            'required': True,
            'name': '초절전 임계(V)',
            'phrase': '초절전 모드로 전환하는 전압 기준'
        },
        {
            'id': 'missing_vbat_is_critical',
            'type': 'bool',
            'default_value': True,
            'required': True,
            'name': '배터리 누락 시 모드 적용 중단',
            'phrase': '배터리 측정이 없거나 너무 오래되면 모드/주기 변경을 보류합니다.'
        },
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
MODE_A = 1  # 초절전(Ultra-saving) 정책 상태
MODE_B = 2  # 절전(Power-saving) 정책 상태
MODE_C = 3  # 성능(Performance) 정책 상태

# 공통: 정책 모드 코드 → 논리 LoRa 클래스 문자열
MODE_TO_CLASS = {
    MODE_A: 'CLASS_A',
    MODE_B: 'CLASS_B',
    MODE_C: 'CLASS_C',
}

class UplinkPredictor:
    """Predicts next uplink time from measurement arrivals and known HB period."""
    def __init__(self, measurement_delay_sec: int = 10):
        self.measurement_delay = timedelta(seconds=measurement_delay_sec)
        self.last_uplink_time: Optional[datetime] = None
        self.hb_period = timedelta(seconds=0)

    def register_measurement(self, arrival_time: datetime):
        """Store the estimated uplink time by subtracting the known delay."""
        if not isinstance(arrival_time, datetime):
            raise ValueError("arrival_time must be datetime")
        self.last_uplink_time = arrival_time - self.measurement_delay

    def set_hb_period(self, period_sec: int):
        """Lock the current heartbeat interval in seconds."""
        if period_sec <= 0:
            raise ValueError("period_sec must be > 0")
        self.hb_period = timedelta(seconds=period_sec)

    def get_next_uplink_time(self) -> Optional[datetime]:
        """Return predicted next uplink occurrence."""
        if self.last_uplink_time is None or self.hb_period.total_seconds() <= 0:
            return None
        return self.last_uplink_time + self.hb_period

@dataclass
class ModeOpts:
    day_start_hour: int = 4
    day_end_hour: int = 18
    perf_lead_min: int = 10
    # MODE_A: 초절전(ultra saving) 프로파일 하트비트(분)
    a_period_min: int = 60
    # MODE_B: 절전(power saving) 프로파일 하트비트(분)
    b_period_min: int = 30
    # MODE_C: 성능(performance) 프로파일 하트비트(분)
    c_period_min: int = 30
    vbat_recover_v: float = 12.00
    vbat_low_v: float = 11.70
    vbat_critical_v: float = 11.40
    link_rssi_min: int = -110
    link_snr_min: int = -10


def _is_daytime(now_hour: int, s: int, e: int) -> bool:
    if s <= e:
        return s <= now_hour < e
    return (now_hour >= s) or (now_hour < e)

def _is_daytime_minutes(now_minute: int, s_hour: int, e_hour: int) -> bool:
    start = (s_hour % 24) * 60
    end = (e_hour % 24) * 60
    if start == end:
        return True
    if start < end:
        return start <= now_minute < end
    return (now_minute >= start) or (now_minute < end)

def _minutes_until_start(now_minute: int, s_hour: int) -> int:
    start = (s_hour % 24) * 60
    return (start - now_minute) % (24 * 60)


def compute_target_mode_period(
    *,
    vbat_V: Optional[float],
    now_hour: int,
    now_minute: int,
    valve_active: bool,
    link_rssi: Optional[float],
    link_snr: Optional[float],
    o: ModeOpts
) -> Tuple[int, int, str]:
    """
    새 Policy (Class A 자동 진입 금지):
    - 모드 코드는 동일하나, 자동 정책에서는 MODE_A(1)를 사용하지 않는다.
    - 초절전(ultra-saving)은 항상 MODE_B 상태를 유지한 채, 하트비트 주기를 길게 가져가는 방식으로 처리한다.
      * 즉, Class A는 관리자가 별도 목적을 갖고 직접 내려야만 진입 가능하다.

      1 = A: (관리자용) 초절전 모드 – 자동 정책에서는 사용하지 않음
      2 = B: 절전 모드 – 기본 동작 모드, HB 주기를 상황에 따라 길게/짧게 조절
      3 = C: 성능 모드 – 가장 자주 통신, Class C 기반

    배터리 우선 규칙:
    - vbat <= vbat_critical_v:
        -> MODE_B, 초절전 HB (hb_ultra), reason="critical_battery_b_mode"

    주간/야간 + 배터리:
    - Day(운영 시간대 + lead 포함):
        vbat >= vbat_recover_v              -> MODE_C, c_period_min,  reason="day_perf" (또는 day_perf_prefetch)
        vbat_low_v <= vbat < vbat_recover_v -> MODE_B, b_period_min,  reason="day_b_guard"
        vbat_critical_v < vbat < vbat_low_v -> MODE_B, hb_ultra,      reason="day_ultra_low_b_mode"
    - Night:
        vbat >= vbat_low_v                  -> MODE_B, b_period_min,  reason="night_b_guard"
        vbat_critical_v < vbat < vbat_low_v -> MODE_B, hb_ultra,      reason="night_ultra_low_b_mode"

    배터리 미측정(vbat_V is None):
    - 링크 품질이 양호하면 주간에는 C 또는 B, 야간에는 B
    - 링크 품질이 나쁘거나 정보가 없으면 B 모드 유지 + 초절전 HB 로 보수적으로 동작.
    """

    # 초절전 HB 주기는 B 모드에서 재활용 (A 모드는 자동 정책에서 사용하지 않음)
    hb_ultra = max(o.a_period_min, o.b_period_min, 60)

    # 0) 배터리 하드 게이트
    if vbat_V is not None and vbat_V <= o.vbat_critical_v:
        # 예전에는 MODE_A로 떨어뜨렸지만, 이제는 B 모드 유지 + 초절전 HB 를 사용
        return MODE_B, hb_ultra, "critical_battery_b_mode"

    # 주/야 판정 + lead 적용
    day = _is_daytime_minutes(now_minute, o.day_start_hour, o.day_end_hour)
    prefetch_active = False
    if not day and o.perf_lead_min > 0 and o.day_start_hour != o.day_end_hour:
        minutes_until = _minutes_until_start(now_minute, o.day_start_hour)
        if 0 < minutes_until <= o.perf_lead_min:
            day = True
            prefetch_active = True

    if vbat_V is not None:
        # --- 배터리 기반 정상 경로 ---
        if day:
            if vbat_V >= o.vbat_recover_v:
                reason = "day_perf_prefetch" if prefetch_active else "day_perf"
                return MODE_C, o.c_period_min, reason
            if vbat_V >= o.vbat_low_v:
                return MODE_B, o.b_period_min, "day_b_guard"
            # vbat_critical_v < vbat < vbat_low_v (critical 구간은 위에서 처리됨)
            return MODE_B, hb_ultra, "day_ultra_low_b_mode"
        else:
            if vbat_V >= o.vbat_low_v:
                return MODE_B, o.b_period_min, "night_b_guard"
            # vbat_critical_v < vbat < vbat_low_v
            return MODE_B, hb_ultra, "night_ultra_low_b_mode"

    # ----- vbat unknown -> 링크/시간 기반 보수 정책 -----
    link_ok = True
    if link_rssi is not None:
        link_ok &= (link_rssi > o.link_rssi_min)
    if link_snr is not None:
        link_ok &= (link_snr > o.link_snr_min)

    if day:
        if valve_active and link_ok:
            # 부하가 있고 링크가 양호하면 C 모드
            return MODE_C, o.c_period_min, "fallback_day_perf"
        if link_ok:
            # 링크는 양호하나 부하가 없으면 B 모드
            return MODE_B, o.b_period_min, "fallback_day_b"
        # 링크가 나쁘면 B 모드 유지 + 초절전 HB
        return MODE_B, hb_ultra, "fallback_day_ultra_b_mode"
    else:
        if link_ok:
            return MODE_B, o.b_period_min, "fallback_night_b"
        return MODE_B, hb_ultra, "fallback_night_ultra_b_mode"


def build_mode_downlink(
    mode: int,
    period_min: int,
    *,
    perf_class: str = 'C',
    save_class: str = 'B',
    ultra_class: str = 'B',
    c_period_min: int = 30,
    b_period_min: int = 30,
    a_period_min: int = 60
) -> Tuple[int, bytes, str]:
    """
    정책 모드를 펌웨어 CFG 프레임으로 직렬화한다.

    FPort 14 포맷: [0xD0, mode(1=A,2=B,3=C), hb_min]

    주의: 두 번째 바이트는 정책 모드 코드이며, 실제 LoRa Class 전환은 DeviceProfile
    동기화 로직이 담당한다.
    """

    def _positive_int(value, default):
        try:
            iv = int(value)
        except Exception:
            return default
        return iv if iv > 0 else default

    # 모드별 기본 HB 설정 (class_* 인자는 wire 포맷에는 사용하지 않지만,
    # 옵션 호환성을 위해 시그니처만 유지한다.)
    profile_map = {
        MODE_C: ("perf", c_period_min),
        MODE_B: ("save", b_period_min),
        MODE_A: ("ultra", a_period_min),
    }
    profile_name, hb_opt = profile_map.get(
        mode,
        ("perf", c_period_min)
    )

    hb_from_profile = _positive_int(hb_opt, 0)
    hb_from_period = _positive_int(period_min, 0)
    hb = hb_from_profile or hb_from_period or 30
    hb = max(1, min(255, hb))

    payload = bytes([0xD0, mode & 0xFF, hb & 0xFF])

    desc = f"profile={profile_name}, mode={mode}, hb={hb}"
    return 14, payload, desc


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
        self._pending_apply = None  # {'mode':int, 'period':int, 'ts':float}
        try:
            self._retry_interval_min = float(getattr(self, 'retry_interval_min', 0.0))
        except Exception:
            self._retry_interval_min = 0.0
        # Throttle for repeated "no target" logs
        self._no_target_throttle_ts = 0.0

        # Scheduled send state for Class-A slot targeting
        self._sched = None  # {'mode':int,'period':int,'next_at':float,'left':int,'gap':float}
        self._last_input_ts = {}  # per-iteration cache of latest measurement timestamps
        self._last_class_setting = None  # 'CLASS_A' / 'CLASS_C'
        self._last_node_class_state: Optional[str] = None  # 'CLASS_A' / 'CLASS_B' / 'CLASS_C'
        self._current_mode: Optional[int] = None
        self._scheduled_class_c_time: Optional[datetime] = None
        self._uplink_predictor = UplinkPredictor(measurement_delay_sec=10)
        self._last_measurement_dt: Optional[datetime] = None

        if not testing:
            self.try_initialize()

    def _log_no_target(self, reason: str):
        """
        Throttled info-level log when no mode/period update is applied.
        Avoids spamming logs when inputs are missing or the target is unchanged.
        """
        now = time.time()
        # 최소 60초 간격으로만 같은 유형의 로그를 남긴다.
        if (now - getattr(self, "_no_target_throttle_ts", 0.0)) < 60.0:
            return
        self._no_target_throttle_ts = now
        self.logger.info(f"lorawan_mode_manager: no apply ({reason})")

    def initialize(self):
        self.logger.info("LoRaWAN mode manager started")

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

    def _get_cs_base(self):
        """
        공통 ChirpStack gRPC 접속 헬퍼.

        - 서버 주소 정규화 (http(s)://, path 제거, 포트 기본값 보정)
        - API 토큰, DevEUI 읽기
        - grpc / chirpstack_api 존재 여부 검사
        - gRPC 채널과 인증 metadata, DevEUI를 반환한다.

        반환:
            (channel, metadata, deveui) 또는 (None, None, None) on error
        """
        try:
            server = self._normalize_server()
            token = self._normalize_token()
            deveui = self._normalize_deveui()
        except Exception:
            return None, None, None

        if not (grpc and cs_api and server and token and deveui):
            return None, None, None

        if ":" not in server:
            server = server + ":8080"

        try:
            channel = grpc.insecure_channel(server)
            md = [("authorization", f"Bearer {token}")]
        except Exception:
            return None, None, None

        return channel, md, deveui

    # --- 유틸: AoT_VPD 스타일 selector 측정값 취득 ---
    def _get_measurement_val(self, base: str, max_age):
        """
        AoT style selector reader (like AoT_VPD):
        - For an option id like 'input_vbat' (type: select_measurement),
          AoT creates attributes: input_vbat_device_id, input_vbat_measurement_id.
        - This function resolves those and fetches the latest value with max_age.
        - Returns float value or None and logs precise reason.
        """
        try:
            dev_id = getattr(self, f"{base}_device_id", None)
            meas_id = getattr(self, f"{base}_measurement_id", None)
            if not dev_id or not meas_id:
                self.logger.debug(f"ingest:{base} selector_empty dev={dev_id} meas={meas_id}")
                self._last_input_ts[base] = None
                return None

            last = self.get_last_measurement(dev_id, meas_id, max_age=max_age)
            if not last:
                self.logger.debug(f"ingest:{base} no_recent_value (max_age={max_age}) dev={dev_id} meas={meas_id}")
                self._last_input_ts[base] = None
                return None

            try:
                val = float(last[1])
            except Exception:
                self.logger.debug(f"ingest:{base} value_not_numeric -> {last[1]}")
                self._last_input_ts[base] = None
                return None

            try:
                ts = float(last[0])
            except Exception:
                ts = None
            self._last_input_ts[base] = ts
            if ts is not None:
                try:
                    self.on_measurement_received(datetime.fromtimestamp(ts))
                except Exception:
                    pass
            self.logger.debug(f"ingest:{base} ok dev={dev_id} meas={meas_id} val={val}")
            return val
        except Exception as e:
            self.logger.debug(f"ingest:{base} exception -> {e}")
            self._last_input_ts[base] = None
            return None

    def _read_measurements(self):
        """
        Read vbat, RSSI, SNR measurements with the configured max age.
        Returns (vbat, rssi, snr).
        """
        try:
            max_age = int(getattr(self, 'measurement_max_age', 0) or 0)
        except Exception:
            max_age = 0

        if max_age > 0:
            vbat = self._get_measurement_val('input_vbat', max_age)
            rssi = self._get_measurement_val('input_rssi', max_age)
            snr = self._get_measurement_val('input_snr', max_age)
        else:
            vbat = self._get_measurement_val('input_vbat', 0)
            rssi = self._get_measurement_val('input_rssi', 0)
            snr = self._get_measurement_val('input_snr', 0)

        return vbat, rssi, snr
    
    def _read_node_class(self, max_age_sec: int) -> Optional[str]:
        """
        Read current node LoRaWAN class from a measurement (1=A, 2=B, 3=C) and
        normalize it to 'CLASS_A' / 'CLASS_B' / 'CLASS_C'.
        """
        try:
            val = self._get_measurement_val('input_node_class', max_age_sec)
        except Exception:
            val = None
        if val is None:
            return None
        try:
            cid = int(val)
        except Exception:
            self.logger.debug(f"node_class: non-integer value -> {val}")
            return None
        mapping = {1: 'CLASS_A', 2: 'CLASS_B', 3: 'CLASS_C'}
        node_class = mapping.get(cid)
        if not node_class:
            self.logger.debug(f"node_class: out-of-range id -> {cid}")
            return None
        return node_class

    # --- Class-C device profile management ----------------------------------
    def _get_profile_class_state(self) -> Optional[str]:
        """
        Read current ChirpStack DeviceProfile class capability via gRPC.
        Returns 'CLASS_C' when supports_class_c is True, otherwise 'CLASS_A'.
        """
        channel, md, deveui = self._get_cs_base()
        if not channel:
            return None

        try:
            dev_client = cs_api.DeviceServiceStub(channel)

            dreq = cs_api.GetDeviceRequest()
            dreq.dev_eui = deveui
            dresp = dev_client.Get(dreq, metadata=md)
            device = dresp.device
            profile_id = getattr(device, 'device_profile_id', '') or ''
            if not profile_id:
                self.logger.warning("Profile class state: device_profile_id not found")
                return None

            dp_client = cs_api.DeviceProfileServiceStub(channel)
            preq = cs_api.GetDeviceProfileRequest()
            preq.id = profile_id
            presp = dp_client.Get(preq, metadata=md)
            profile = presp.device_profile
            supports_c = bool(getattr(profile, 'supports_class_c', False))
            return 'CLASS_C' if supports_c else 'CLASS_A'
        except Exception as e:
            self.logger.warning(f"Profile class state read failed: {e}")
            return None

    def _sync_profile_to_node_class(self, node_class: Optional[str], previous: Optional[str] = None):
        """
        엔드노드 실제 LoRaWAN 클래스(A/B/C)를 기준으로
        ChirpStack DeviceProfile의 supports_class_[b|c] 및
        Class-B ping-slot freq를 정렬한다.

        - node_class: 'CLASS_A' / 'CLASS_B' / 'CLASS_C'
        - previous:   이전에 관측된 클래스 (없으면 None)

        Class A:
          - 관리자가 특별한 목적을 갖지 않는 한 일반 사용자는 진입하기 어려워야 하므로,
            자동 정책에서는 DeviceProfile 플래그를 변경하지 않는다.
        """
        if not node_class:
            return

        # CLASS_A 로 진입한 경우에는 프로파일을 건드리지 않고 그대로 둔다.
        if node_class == 'CLASS_A':
            self.logger.debug("node_class=CLASS_A -> DeviceProfile flags unchanged")
            return

        channel, md, deveui = self._get_cs_base()
        if not channel:
            return

        try:
            dev_client = cs_api.DeviceServiceStub(channel)
            dp_client = cs_api.DeviceProfileServiceStub(channel)

            # 1) Device → DeviceProfile ID 조회
            dreq = cs_api.GetDeviceRequest()
            dreq.dev_eui = deveui
            dresp = dev_client.Get(dreq, metadata=md)
            device = dresp.device
            profile_id = getattr(device, 'device_profile_id', '') or ''
            if not profile_id:
                self.logger.warning("Profile sync: device_profile_id not found")
                return

            # 2) DeviceProfile 조회
            preq = cs_api.GetDeviceProfileRequest()
            preq.id = profile_id
            presp = dp_client.Get(preq, metadata=md)
            profile = presp.device_profile

            current_b = bool(getattr(profile, 'supports_class_b', False))
            current_c = bool(getattr(profile, 'supports_class_c', False))
            try:
                current_freq = int(getattr(profile, 'class_b_ping_slot_freq', 0) or 0)
            except Exception:
                current_freq = 0

            # 3) 엔드노드 클래스별 목표 상태
            if node_class == 'CLASS_B':
                want_b = True
                want_c = False
                want_freq = 923100000  # Hz, AS923 ping-slot 고정 주파수
            elif node_class == 'CLASS_C':
                want_b = False
                want_c = True
                want_freq = current_freq  # C일 때는 ping-slot freq 건드릴 필요 없음
            else:
                # 방어용 (위에서 CLASS_A 는 이미 반환)
                want_b = current_b
                want_c = current_c
                want_freq = current_freq

            changed = (
                current_b != want_b or
                current_c != want_c or
                (node_class == 'CLASS_B' and current_freq != want_freq)
            )
            if not changed:
                return

            profile.supports_class_b = want_b
            profile.supports_class_c = want_c
            if node_class == 'CLASS_B':
                try:
                    profile.class_b_ping_slot_freq = want_freq
                except AttributeError:
                    self.logger.warning("class_b_ping_slot_freq field missing in DeviceProfile stub")

            ureq = cs_api.UpdateDeviceProfileRequest()
            ureq.device_profile.CopyFrom(profile)
            dp_client.Update(ureq, metadata=md)

            self.logger.info(
                f"DeviceProfile({profile_id}) updated by node_class change: prev={previous}, "
                f"now={node_class}, B={current_b}->{want_b}, C={current_c}->{want_c}, "
                f"ping_freq={current_freq}->{want_freq}"
            )
        except Exception as e:
            self.logger.warning(f"Profile class sync failed: {e}")

    def _build_mode_opts(self) -> ModeOpts:
        """
        Build ModeOpts from the current custom options.
        """
        return ModeOpts(
            day_start_hour=int(getattr(self, 'day_start_hour', 4) or 4),
            day_end_hour=int(getattr(self, 'day_end_hour', 18) or 18),
            perf_lead_min=int(getattr(self, 'perf_lead_min', 10) or 10),
            a_period_min=int(getattr(self, 'a_period_min', 60) or 60),
            b_period_min=int(getattr(self, 'b_period_min', 30) or 30),
            c_period_min=int(getattr(self, 'c_period_min', 30) or 30),
            vbat_recover_v=float(getattr(self, 'vbat_recover_v', 12.0) or 12.0),
            vbat_low_v=float(getattr(self, 'vbat_low_v', 11.7) or 11.7),
            vbat_critical_v=float(getattr(self, 'vbat_critical_v', 11.4) or 11.4),
            link_rssi_min=int(getattr(self, 'link_rssi_min', -110) or -110),
            link_snr_min=int(getattr(self, 'link_snr_min', -10) or -10),
        )

    def _derive_vbat_for_policy(self, vbat: Optional[float]) -> Tuple[Optional[float], bool]:
        """
        배터리/클래스 정책을 반영하여 compute_target_mode_period()에 넘길 vbat 값을 결정한다.
        반환값: (vbat_for_policy, should_skip_loop)
        - should_skip_loop 이 True이면, 상위 loop()에서 즉시 return 해야 한다.
        """
        apply_only_when_valid = bool(getattr(self, 'apply_only_when_valid', False))
        missing_vbat_is_critical = bool(getattr(self, 'missing_vbat_is_critical', True))

        # 배터리 누락 시 보수적 동작 (기존 동작 유지)
        if vbat is None and apply_only_when_valid and missing_vbat_is_critical:
            self._log_no_target("skip: vbat missing & apply_only_when_valid")
            return None, True

        battery_policy_enabled = bool(getattr(self, 'battery_policy_enabled', False))
        class_policy = self._class_policy()  # 'auto' / 'force_class_*'

        if battery_policy_enabled and class_policy == 'auto':
            vbat_for_policy = vbat if (vbat is not None or missing_vbat_is_critical) else None
        else:
            # 배터리로 모드 전환하지 않음 -> vbat_V=None 으로 링크/시간 기반 fallback 정책만 사용
            vbat_for_policy = None

        # 디버깅용 로그 (선택 사항)
        try:
            self.logger.debug(
                f"mode-eval: battery_policy={battery_policy_enabled}, "
                f"class_policy={class_policy}, vbat_raw={vbat}, "
                f"vbat_used={vbat_for_policy}"
            )
        except Exception:
            pass

        return vbat_for_policy, False

    def _should_apply(self, mode: int, period_min: int, reason: str, now_ts: float) -> bool:
        """
        마지막 적용 상태와 재시도 간격을 고려해 이번에 다운링크를 적용할지 여부를 결정한다.
        적용하지 않는 경우 _log_no_target()으로 이유를 남긴다.
        """
        last = self._last_applied
        need_apply = False

        if last is None:
            need_apply = True
        else:
            last_mode, last_period = last
            if last_mode != mode or last_period != period_min:
                need_apply = True
            elif self._retry_interval_min > 0.0:
                last_ts = 0.0
                if isinstance(self._pending_apply, dict):
                    last_ts = float(self._pending_apply.get('ts', 0.0) or 0.0)
                if (now_ts - last_ts) >= (self._retry_interval_min * 60.0):
                    need_apply = True

        if not need_apply:
            self._log_no_target(f"unchanged mode={mode} period={period_min} reason={reason}")
        return need_apply

    def _class_policy(self) -> str:
        raw = str(getattr(self, 'class_c_policy', 'auto') or 'auto').lower()
        legacy = {
            'none': 'auto',
            'follow_mode': 'auto',
            'always_on': 'force_class_c',
            'always_off': 'force_class_b'
        }
        return legacy.get(raw, raw)

    def _desired_class_c_state(self, mode: int) -> Optional[str]:
        policy = self._class_policy()
        if policy == 'auto':
            return 'CLASS_C' if mode == MODE_C else 'CLASS_B'
        if policy == 'force_class_a':
            return 'CLASS_A'
        if policy == 'force_class_b':
            return 'CLASS_B'
        if policy == 'force_class_c':
            return 'CLASS_C'
        return None

    def _forced_mode_override(self) -> Optional[int]:
        policy = self._class_policy()
        if policy == 'force_class_a':
            return MODE_A
        if policy == 'force_class_b':
            return MODE_B
        if policy == 'force_class_c':
            return MODE_C
        return None

    def _apply_device_class(self, target: str) -> bool:
        if target not in ('CLASS_A', 'CLASS_B', 'CLASS_C'):
            return False

        channel, md, deveui = self._get_cs_base()
        if not channel:
            return False

        try:
            dev_client = cs_api.DeviceServiceStub(channel)

            dreq = cs_api.GetDeviceRequest()
            dreq.dev_eui = deveui
            dresp = dev_client.Get(dreq, metadata=md)
            device = dresp.device
            profile_id = getattr(device, 'device_profile_id', '') or ''
            if not profile_id:
                self.logger.warning("Class-C 정책: device_profile_id를 찾을 수 없음")
                return False

            dp_client = cs_api.DeviceProfileServiceStub(channel)
            preq = cs_api.GetDeviceProfileRequest()
            preq.id = profile_id
            presp = dp_client.Get(preq, metadata=md)
            profile = presp.device_profile
            current = bool(getattr(profile, 'supports_class_c', False))
            want = (target == 'CLASS_C')

            if current == want:
                return True

            profile.supports_class_c = want
            ureq = cs_api.UpdateDeviceProfileRequest()
            ureq.device_profile.CopyFrom(profile)
            dp_client.Update(ureq, metadata=md)
            self.logger.info(f"ChirpStack DeviceProfile({profile_id}) supports_class_c: {current} -> {want}")
            return True
        except Exception as e:
            self.logger.warning(f"ChirpStack Class-C 업데이트 실패: {e}")
            return False

    # --- REST sync: device profile supportsClassC ---------------------------------
    def sync_class_with_device_profile(self, mode: int, profile_id: str, api_url: str, api_key: str) -> bool:
        """
        Ensure ChirpStack device profile's supportsClassC flag matches the active mode.
        Returns True when an update is performed.
        """
        try:
            wants_class_c = (mode == MODE_C)
            base = (api_url or "").rstrip("/")
            if not base:
                raise ValueError("API URL missing")
            url = f"{base}/device-profiles/{profile_id}"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            resp = requests.get(url, headers=headers, timeout=5)
            resp.raise_for_status()
            body = resp.json()
            profile = body.get("deviceProfile")
            if not profile:
                raise ValueError("deviceProfile not present in response")
            current = bool(profile.get("supportsClassC", False))
            if current == wants_class_c:
                return False
            profile["supportsClassC"] = wants_class_c
            update_payload = {"deviceProfile": profile}
            resp_put = requests.put(url, headers=headers, json=update_payload, timeout=5)
            resp_put.raise_for_status()
            self.logger.info(f"DeviceProfile {profile_id} supportsClassC -> {wants_class_c}")
            return True
        except Exception as err:
            self.logger.warning(f"Device profile sync failed: {err}")
            return False

    def _maybe_update_class_c(self, mode: int):
        target = self._desired_class_c_state(mode)
        if not target:
            return
        if self._last_class_setting == target:
            return
        if self._apply_device_class(target):
            self._last_class_setting = target

    # --- Uplink scheduling helper methods ----------------------------------
    def on_measurement_received(self, receive_time: datetime):
        """Register the measurement arrival so we can infer next uplink timing."""
        if not isinstance(receive_time, datetime):
            return
        self._last_measurement_dt = receive_time
        try:
            self._uplink_predictor.register_measurement(receive_time)
        except Exception as e:
            self.logger.debug(f"Uplink predictor register failed: {e}")

    def request_mode_change(self, new_mode: int) -> Optional[datetime]:
        """
        When switching from Class A to Class C, schedule a downlink just after the next expected uplink.
        Returns the scheduled datetime when applicable.
        """
        current_mode = self._current_mode
        if current_mode in (MODE_A, MODE_B) and new_mode == MODE_C:
            next_uplink = self._uplink_predictor.get_next_uplink_time()
            if not next_uplink:
                self.logger.warning("Cannot schedule Class-C switch (uplink prediction unavailable)")
                return None
            fire_at = next_uplink + timedelta(seconds=1)
            self._scheduled_class_c_time = fire_at
            self._schedule_downlink_at(fire_at, new_mode)
            return fire_at
        return None

    def _schedule_downlink_at(self, target_time: datetime, mode: int):
        """Placeholder for integration with actual scheduler/outbound queue."""
        self.logger.info(f"Planned downlink for mode={mode} at {target_time}")

    def _update_mode_state(self, mode: int, period_min: int):
        """
        Record the current mode and heartbeat period for prediction helpers,
        then synchronize ChirpStack DeviceProfile class to the *actual* node class
        when available.

        흐름:
        1) 현재 정책 모드/하트비트 주기를 내부 상태에 반영
        2) HB 측정(input_node_class)에서 엔드노드 클래스(A/B/C)를 읽음
        3) 이전에 관측된 클래스와 비교하여 변경이 있을 때만 DeviceProfile B/C 옵션을 정렬
           (엔드노드 클래스 정보를 사용할 수 없는 경우에만 기존 class_c_policy 기반 동작을 유지)
        """
        # 1) 정책 모드/HB 주기 상태 업데이트
        self._current_mode = mode
        try:
            self._uplink_predictor.set_hb_period(int(period_min) * 60)
        except Exception:
            pass

        # 2) 엔드노드 클래스 측정값 읽기
        try:
            max_age = int(getattr(self, 'measurement_max_age', 0) or 0)
        except Exception:
            max_age = 0

        try:
            node_class = self._read_node_class(max_age) if max_age > 0 else self._read_node_class(0)
        except Exception as e:
            self.logger.debug(f"read node_class failed: {e}")
            node_class = None

        policy = self._class_policy()
        auto_policy = (policy == 'auto')

        # 3) 엔드노드 클래스 정보가 있다면, 자동 정책일 때만 DeviceProfile 동기화
        if node_class:
            prev = self._last_node_class_state
            self._last_node_class_state = node_class

            if auto_policy:
                # 이전과 동일하면 DeviceProfile 업데이트 불필요
                if prev == node_class:
                    return
                self._sync_profile_to_node_class(node_class, previous=prev)
                return

        # 정책 기반 Class 관리 (수동 정책이거나 노드 클래스 측정이 없는 경우)
        try:
            self._maybe_update_class_c(mode)
        except Exception as e:
            self.logger.debug(f"class policy update skipped due to error: {e}")

    def _enqueue_mode_downlink(self, mode: int, period_min: int, reason: str) -> bool:
        """
        Build FPort 14 CFG frame and enqueue it via ChirpStack DeviceService.Enqueue.
        Returns True on successful enqueue.
        """
        # 1) Build payload
        try:
            perf_class = str(getattr(self, 'c_mode_class', 'C') or 'C')
            save_class = str(getattr(self, 'b_mode_class', 'B') or 'B')
            ultra_class = str(getattr(self, 'a_mode_class', 'B') or 'B')
            port, payload, desc = build_mode_downlink(
                mode,
                period_min,
                perf_class=perf_class,
                save_class=save_class,
                ultra_class=ultra_class,
                c_period_min=int(getattr(self, 'c_period_min', 30) or 30),
                b_period_min=int(getattr(self, 'b_period_min', 30) or 30),
                a_period_min=int(getattr(self, 'a_period_min', 60) or 60),
            )
        except Exception as e:
            self.logger.warning(f"mode-dl build failed: {e}")
            return False

        # 1.5) Derive effective HB minutes & skip when class/HB pair is unchanged.
        #
        # - build_mode_downlink()가 실제로 전송할 HB 분(hb_min)을 payload에 반영하므로
        #   여기서 다시 파싱해서 실제 값 기준으로 비교한다.
        # - 클래스는 같지만 HB가 바뀐 경우에는 반드시 다운링크를 보내야 한다.
        hb_min = None
        try:
            if payload and payload[0] == 0xD0 and len(payload) >= 3:
                hb_min = int(payload[2])
        except Exception:
            hb_min = None

        if hb_min is None:
            # 혹시 파싱 실패 시에는 요청된 period_min으로 best-effort 보정
            try:
                hb_min = int(period_min)
            except Exception:
                hb_min = 0

        # MODE_A/B/C -> 논리 클래스 문자열 (공통 상수 사용)
        target_class = MODE_TO_CLASS.get(mode)

        # 마지막으로 성공적으로 큐잉한 (class, hb_min)과 동일하면 스킵
        last_pair = getattr(self, "_last_class_hb", None)
        if target_class and hb_min > 0 and isinstance(last_pair, tuple):
            last_class, last_hb = last_pair
            if last_class == target_class and last_hb == hb_min:
                self.logger.info(
                    f"mode-dl skip: unchanged class/HB "
                    f"class={target_class} hb={hb_min} (reason={reason})"
                )
                return True

        # 2) ChirpStack connection parameters (공통 헬퍼 사용)
        channel, md, deveui = self._get_cs_base()
        if not channel:
            self.logger.warning("mode-dl enqueue aborted: ChirpStack base not ready")
            return False

        # 3) Enqueue via DeviceService.Enqueue()
        try:
            dev_client = cs_api.DeviceServiceStub(channel)

            req = cs_api.EnqueueDeviceQueueItemRequest()
            # ChirpStack v4: the payload is in req.queue_item (not device_queue_item)
            item = req.queue_item
            item.dev_eui = deveui
            item.f_port = port
            item.confirmed = False
            item.data = payload

            resp = dev_client.Enqueue(req, metadata=md)
            qid = getattr(resp, "id", "")
            self.logger.info(
                f"Enqueue mode DL: dev_eui={deveui} mode={mode} period={period_min}min "
                f"reason={reason} desc={desc} queue_id={qid}"
            )

            # Remember last successfully enqueued (class, HB-min) pair to avoid
            # redundant future downlinks when both are unchanged. This works
            # together with the early skip logic that compares (target_class, hb_min)
            # against _last_class_hb.
            try:
                if 'target_class' in locals() and 'hb_min' in locals() and target_class and hb_min > 0:
                    self._last_class_hb = (target_class, int(hb_min))
            except Exception as e:
                self.logger.debug(f"failed to update last_class_hb: {e}")

            return True
        except Exception as e:
            self.logger.warning(f"mode-dl enqueue failed: {e}")
            return False

    def loop(self):
        """
        Periodic entry point called by AoT controller.

        1) 읽을 수 있는 최신 측정값을 가져온다.
        2) compute_target_mode_period()로 목표 (mode, period_min)를 계산한다.
        3) 이전에 적용한 상태와 비교하여 필요 시에만 CFG 다운링크를 Enqueue 한다.
        4) 성공 시 _update_mode_state()를 통해 내부 상태/프로파일 동기화를 수행한다.
        """
        now_ts = time.time()
        try:
            update_period = float(getattr(self, 'update_period', 60.0) or 60.0)
        except Exception:
            update_period = 60.0

        # 내부 타이머로 루프 주기 제어
        if now_ts < getattr(self, "timer_loop", 0.0):
            return
        self.timer_loop = now_ts + update_period

        vbat, rssi, snr = self._read_measurements()

        # 현재 시각 (서버 로컬 시간 기준; 운영 시간대 옵션은 이 로컬 시간대에 맞춰 해석된다)
        now_dt = datetime.now()
        now_hour = now_dt.hour
        now_minute = now_dt.hour * 60 + now_dt.minute

        # 밸브 활동 플래그는 향후 측정/이벤트 연동 시 확장.
        valve_active = False

        # 옵션 바인딩
        opts = self._build_mode_opts()

        vbat_for_policy, should_skip = self._derive_vbat_for_policy(vbat)
        if should_skip:
            return

        # --- 여기부터 추가: 배터리 정책 OFF + 클래스 정책 AUTO -> 시간 기반 단순 정책 ---
        battery_policy_enabled = bool(getattr(self, 'battery_policy_enabled', False))
        class_policy = self._class_policy()  # 'auto' / 'force_class_*'

        if (not battery_policy_enabled) and class_policy == 'auto':
            # 시간대만 기준으로 모드 결정:
            # - 주간(운영 시간대)에는 성능 모드(MODE_C)
            # - 야간에는 절전 모드(MODE_B)
            is_day = _is_daytime_minutes(
                now_minute,
                opts.day_start_hour,
                opts.day_end_hour,
            )
            if is_day:
                mode = MODE_C
                period_min = opts.c_period_min
                reason = "time_only_day_perf"
            else:
                mode = MODE_B
                period_min = opts.b_period_min
                reason = "time_only_night_save"
        else:
            # --- 기존 정책: 강제 모드 / 배터리/링크 기반 정책 사용 ---
            forced_mode = self._forced_mode_override()
            if forced_mode is not None:
                mode = forced_mode
                period_lookup = {
                    MODE_A: opts.a_period_min,
                    MODE_B: opts.b_period_min,
                    MODE_C: opts.c_period_min
                }
                period_min = period_lookup.get(mode, opts.c_period_min)
                reason = f"policy_force_mode_{mode}"
            else:
                try:
                    mode, period_min, reason = compute_target_mode_period(
                        vbat_V=vbat_for_policy,
                        now_hour=now_hour,
                        now_minute=now_minute,
                        valve_active=valve_active,
                        link_rssi=rssi,
                        link_snr=snr,
                        o=opts,
                    )
                except Exception as e:
                    self.logger.warning(f"compute_target_mode_period failed: {e}")
                    return

        now_ts = time.time()
        if not self._should_apply(mode, period_min, reason, now_ts):
            return

        # 실제 다운링크 Enqueue 수행
        if self._enqueue_mode_downlink(mode, period_min, reason):
            self._last_applied = (mode, period_min)
            self._pending_apply = {'mode': mode, 'period': period_min, 'ts': now_ts}
            try:
                self._update_mode_state(mode, period_min)
            except Exception as e:
                self.logger.debug(f"update_mode_state failed: {e}")
