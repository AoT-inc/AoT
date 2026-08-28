# coding=utf-8
#
#  lorawan_mode_manager.py — LoRaWAN mode/period decision engine for the RAK3172E Valve Controller (skeleton)
#
#  Reference structure: aot/functions/base_function.py, bang_bang_on_off.py
#
#  Role:
#    - Based on inputs (battery V, RSSI, SNR, valve-activity flag, current time),
#      compute the target (mode, period_min) and apply it only when conditions are met (calls the send hook).
#    - The send hook is to be connected later to on_off_chirpstack.OutputModule (e.g. set_mode_period).
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
from aot.utils.device_tz import resolve_location_tz
from aot.utils.timekit import utc_now

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
    'function_name': lazy_gettext('LoRaWAN Mode/Period Manager (RAK3172E)'),
    'function_name_short': 'LoRa Mode Manager',

    'message': lazy_gettext('Determines the Class/heartbeat period based on battery, time of day, valve activity, and link quality. Queues downlinks directly via ChirpStack gRPC (DeviceService.Enqueue).'),

    'options_enabled': [
        'measurements_configure',
        'custom_options'
    ],
    'custom_commands': {},

    'custom_options': [
        {
            'id': 'device_role',
            'type': 'select',
            'default_value': 'controller',
            'required': True,
            'options_select': [
                ('controller', lazy_gettext('Controller (valve/actuator) — Class C preferred')),
                ('sensor',     lazy_gettext('Sensor — Class A, low power (no gateway GPS required)')),
                ('hybrid',     lazy_gettext('Hybrid — manual configuration')),
            ],
            'name': lazy_gettext('Device Role'),
            'phrase': lazy_gettext(
                'controller: Class C during operating hours, B at night. '
                'sensor: Class A always (no gateway GPS required), longer HB at night. '
                'hybrid: follow the settings below exactly.'
            )
        },
        {
            'id': 'update_period',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 60,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('Period'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('Evaluation and apply period (seconds)')
        },
        {
            'type': 'message',
            'default_value': '<b>{}</b>'.format(lazy_gettext('Server Connection'))
        },
        {
            'id': 'cs_server',
            'type': 'text',
            'default_value': '127.0.0.1:8080',
            'required': True,
            'name': lazy_gettext('ChirpStack gRPC Server'),
            'phrase': lazy_gettext('host:port format (e.g. 127.0.0.1:8080) or http(s)://host:port')
        },
        {
            'id': 'cs_api_token',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': 'API Key',
            'phrase': lazy_gettext('Enter the JWT token value (without "Bearer")')
        },
        {
            'id': 'dev_eui',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': 'DevEUI',
            'phrase': lazy_gettext('16-digit hexadecimal DevEUI (separators allowed)')
        },
        {
            'type': 'new_line'
        },
        {
            'type': 'message',
            'default_value': '<b>{}</b>'.format(lazy_gettext('Measurement Inputs'))
        },
        {
            'id': 'cs_rest_port',
            'type': 'integer',
            'default_value': 8090,
            'required': True,
            'name': 'ChirpStack REST Port',
            'phrase': lazy_gettext('ChirpStack REST API port (default 8090)')
        },
        {
            'id': 'measurement_max_age',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 4000,
            'required': True,
            'name': "{}: {} ({})".format(lazy_gettext('Measurement'), lazy_gettext('Max Age'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('How far back (seconds) to look in ChirpStack metrics history')
        },
        {
            'id': 'retry_interval_min',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'name': lazy_gettext('Retry Interval (min)'),
            'phrase': lazy_gettext('Interval at which to re-apply the same mode when there is no ACK (0 disables retry)')
        },
        {
            'id': 'class_c_policy',
            'type': 'select',
            'default_value': 'auto',
            'required': True,
            'options_select': [
                ('auto', lazy_gettext('Auto')),
                ('force_class_a', 'CLASS-A'),
                ('force_class_b', 'CLASS-B'),
                ('force_class_c', 'CLASS-C')
            ],
            'name': lazy_gettext('LoRa Class Policy'),
            'phrase': lazy_gettext('Only in Auto mode is the Class switched according to the mode; selecting a specific class keeps that class.')
        },
        {
            'id': 'apply_only_when_valid',
            'type': 'bool',
            'default_value': False,
            'required': True,
            'name': lazy_gettext('Switch Mode Only When Inputs Are Valid'),
            'phrase': lazy_gettext('Apply the mode only when the input conditions/measurements are valid')
        },

        {
            'type': 'new_line'
        },
        {
            'type': 'message',
            'default_value': '<b>{}</b><br/><small>{}</small>'.format(lazy_gettext('Operating Hours'), lazy_gettext('Sets the hours during which performance mode operates. Enter 0–24, or if the start and end times are equal it means 24 hours.'))
        },
        {
            'id': 'day_window_mode',
            'type': 'select',
            'default_value': 'fixed',
            'options_select': [
                ('fixed', lazy_gettext('Fixed hours — the start and end hours below')),
                ('solar', lazy_gettext('Sunrise to sunset — follows the season at this location')),
            ],
            'name': lazy_gettext('Operating Hours Basis'),
            'phrase': lazy_gettext(
                'Fixed hours keep the same clock times all year. Sunrise to sunset follows the '
                'daylight at this device\'s location, so performance mode tracks the season '
                'without being re-entered each month. The location is inherited from the map; '
                'if it cannot be resolved, the fixed hours below are used instead.')
        },
        {
            'id': 'sun_offset_start_min',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Sunrise Offset (min)'),
            'phrase': lazy_gettext('Shifts the start of the operating window relative to sunrise. Negative starts earlier (-30 begins 30 minutes before sunrise). Only used when the basis is sunrise to sunset.')
        },
        {
            'id': 'sun_offset_end_min',
            'type': 'integer',
            'default_value': 0,
            'required': True,
            'name': lazy_gettext('Sunset Offset (min)'),
            'phrase': lazy_gettext('Shifts the end of the operating window relative to sunset. Positive ends later (30 keeps performance mode for 30 minutes after sunset). Only used when the basis is sunrise to sunset.')
        },
        {
            'id': 'day_start_hour',
            'type': 'integer',
            'default_value': 4,
            'required': True,
            'name': lazy_gettext('Performance Mode Start (hour)'),
            'phrase': lazy_gettext('Performance mode start time (0–23)')
        },
        {
            'id': 'day_end_hour',
            'type': 'integer',
            'default_value': 18,
            'required': True,
            'name': lazy_gettext('Performance Mode End (hour)'),
            'phrase': lazy_gettext('Performance mode end time (0–23)')
        },
        {
            'id': 'perf_lead_min',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': lazy_gettext('Performance Mode Lead (min)'),
            'phrase': lazy_gettext('Specifies, in minutes, how far in advance of the daytime start to switch to performance (Class C) mode.')
        },
        {
            'type': 'new_line'
        },
        {
            'type': 'message',
            'default_value': '<b>{}</b><br/><small>{}</small>'.format(lazy_gettext('HB Period per Mode'), lazy_gettext('Sets the heartbeat period for each mode.'))
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
            'name': lazy_gettext('Performance Mode Class'),
            'phrase': lazy_gettext('LoRa class to apply to the firmware under the performance (C) policy')
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
            'name': lazy_gettext('Power-saving Mode Class'),
            'phrase': lazy_gettext('LoRa class to apply to the firmware under the power-saving (B) policy')
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
            'name': lazy_gettext('Ultra-saving Mode Class'),
            'phrase': lazy_gettext('LoRa class to apply to the firmware under the ultra-saving (A) policy')
        },
        {
            'id': 'c_period_min',
            'type': 'integer',
            'default_value': 30,
            'required': True,
            'name': lazy_gettext('Performance Heartbeat (min)'),
            'phrase': lazy_gettext('Performance (C) mode heartbeat period (min)')
        },
        {
            'id': 'b_period_min',
            'type': 'integer',
            'default_value': 30,
            'required': True,
            'name': lazy_gettext('Power-saving Heartbeat (min)'),
            'phrase': lazy_gettext('Power-saving (B) mode heartbeat period (min)')
        },
        {
            'id': 'a_period_min',
            'type': 'integer',
            'default_value': 60,
            'required': True,
            'name': lazy_gettext('Ultra-saving Heartbeat (min)'),
            'phrase': lazy_gettext('Ultra-saving (A) mode heartbeat period (min)')
        },


        {
            'type': 'new_line'
        },
        {
            'type': 'message',
            'default_value': '<b>{}</b><br/><small>{}</small>'.format(lazy_gettext('Threshold Options'), lazy_gettext('Sets the mode-switching thresholds. Defaults assume a 4S LiFePO4 pack (12.8 V nominal). For a 12 V lead-acid pack use 12.00 / 11.70 / 11.40 instead — the two chemistries have completely different voltage curves.'))
        },
        {
            'id': 'battery_policy_enabled',
            'type': 'bool',
            'default_value': False,
            'required': True,
            'name': lazy_gettext('Battery Management'),
            'phrase': lazy_gettext('Automatically switches the mode according to the battery voltage. (Active only when the LoRa class policy is Auto.)')
        },
        {
            'id': 'vbat_recover_v',
            'type': 'float',
            'default_value': 13.20,
            'required': True,
            'name': lazy_gettext('Performance Mode Threshold (V)'),
            'phrase': lazy_gettext('Voltage threshold at which stable operation is possible (4S LiFePO4: 13.20 V ≈ 70%; lead-acid 12 V: 12.00 V)')
        },
        {
            'id': 'vbat_low_v',
            'type': 'float',
            'default_value': 13.00,
            'required': True,
            'name': lazy_gettext('Power-saving Threshold (V)'),
            'phrase': lazy_gettext('Voltage threshold for switching to power-saving mode (4S LiFePO4: 13.00 V ≈ 25%; lead-acid 12 V: 11.70 V)')
        },
        {
            'id': 'vbat_critical_v',
            'type': 'float',
            'default_value': 12.80,
            'required': True,
            'name': lazy_gettext('Ultra-saving Threshold (V)'),
            'phrase': lazy_gettext('Voltage threshold for switching to ultra-saving mode (4S LiFePO4: 12.80 V ≈ 10%, past the knee; lead-acid 12 V: 11.40 V)')
        },
        {
            'id': 'missing_vbat_is_critical',
            'type': 'bool',
            'default_value': True,
            'required': True,
            'name': lazy_gettext('Halt Mode Application When Battery Is Missing'),
            'phrase': lazy_gettext('Holds off on mode/period changes when the battery measurement is missing or too old.')
        },
        {
            'id': 'link_rssi_min',
            'type': 'integer',
            'default_value': -110,
            'required': True,
            'name': lazy_gettext('Link RSSI Minimum (dBm)'),
            'phrase': lazy_gettext('At or above this value, the link is considered good')
        },
        {
            'id': 'link_snr_min',
            'type': 'integer',
            'default_value': -10,
            'required': True,
            'name': lazy_gettext('Link SNR Minimum (dB)'),
            'phrase': lazy_gettext('At or above this value, the link is considered good')
        },
        {
            'id': 'valve_active_threshold_ma',
            'type': 'float',
            'default_value': 50.0,
            'required': False,
            'name': lazy_gettext('Valve Active Threshold (mA)'),
            'phrase': lazy_gettext(
                'If battery current exceeds this value, the valve is considered active '
                'and the device stays in performance mode. 0 disables this check.'
            )
        },
        {
            'id': 'debug_logging',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable Debug Logging'),
            'phrase': lazy_gettext(
                'Log "no apply" notices when mode/period is unchanged. '
                'Leave off in production.'
            )
        }
    ]
}


# ----- Mode/period computation logic (pure functions) -----
MODE_A = 1  # Ultra-saving policy state
MODE_B = 2  # Power-saving policy state
MODE_C = 3  # Performance policy state

# Common: policy mode code -> logical LoRa class string
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
    # 'fixed' = 위 시각 그대로, 'solar' = 이 장치 위치의 일출~일몰(±오프셋)
    day_window_mode: str = 'fixed'
    sun_offset_start_min: int = 0
    sun_offset_end_min: int = 0
    perf_lead_min: int = 10
    # MODE_A: ultra-saving profile heartbeat (min)
    a_period_min: int = 60
    # MODE_B: power-saving profile heartbeat (min)
    b_period_min: int = 30
    # MODE_C: performance profile heartbeat (min)
    c_period_min: int = 30
    # 4S 인산철(LiFePO4) 기준 — 2026-08-04 실측 대조로 납산 기준에서 이관.
    # 인산철은 13.0~13.3V 구간이 극단적으로 평평해 그 안에서 잔량을 가르는 것은
    # 무의미하다. 대신 "평탄부 위(여유) / 평탄부 하단(절전) / 무릎 아래(초절전)"
    # 세 지점을 잡는다. device_link_status 의 lifepo4_4s 배지 곡선과 같은 점을
    # 지나므로, 데몬이 절전으로 내릴 때 화면 배지도 25% 이하를 가리킨다.
    #   납산 12V 팩이라면 12.00 / 11.70 / 11.40 으로 되돌려야 한다.
    vbat_recover_v: float = 13.20    # ≈70%
    vbat_low_v: float = 13.00        # ≈25%
    vbat_critical_v: float = 12.80   # ≈10% (무릎 아래)
    link_rssi_min: int = -110
    link_snr_min: int = -10


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


def resolve_day_window(
    o: 'ModeOpts',
    now_minute: int,
    *,
    target_id: Optional[str] = None,
    now=None,
    logger=None
) -> Tuple[bool, int]:
    """운영시간(주간) 여부와 다음 시작까지 남은 분을 함께 돌려준다.

    'fixed'  — day_start_hour ~ day_end_hour (장치 현지 벽시계 기준).
    'solar'  — 이 장치 위치의 일출~일몰 ± 오프셋. 위도가 높을수록, 계절이 바뀔수록
               고정 시각과 벌어진다. 여름 새벽 4시는 이미 밝고 겨울 4시는 한밤중인데,
               고정 시각은 그 차이를 사용자가 매달 다시 입력해야 따라간다.

    좌표를 해석하지 못하면(위치 미설정 등) 조용히 죽지 않고 고정 시각으로 물러난다 —
    운영시간을 잃는 것보다 계절 추종을 잃는 편이 낫다.
    """
    if (o.day_window_mode or 'fixed') != 'solar':
        return (_is_daytime_minutes(now_minute, o.day_start_hour, o.day_end_hour),
                _minutes_until_start(now_minute, o.day_start_hour))

    try:
        from aot.utils.solar import is_daytime, next_sun_event
        from aot.utils.timekit import utc_now

        at = now or utc_now()
        day = is_daytime(target_id=target_id, at=at,
                         start_offset_minutes=o.sun_offset_start_min,
                         end_offset_minutes=o.sun_offset_end_min)
        if day is None:
            raise ValueError("좌표를 해석할 수 없습니다")

        minutes_until = 24 * 60
        next_start = next_sun_event('sunrise', target_id=target_id, now=at,
                                    time_offset_minutes=o.sun_offset_start_min)
        if next_start is not None:
            minutes_until = max(0, int((next_start - at).total_seconds() // 60))
        return day, minutes_until
    except Exception as exc:
        if logger is not None:
            logger.warning(
                f"태양시 기준 운영시간을 계산하지 못해 고정 시각으로 대체합니다: {exc}")
        return (_is_daytime_minutes(now_minute, o.day_start_hour, o.day_end_hour),
                _minutes_until_start(now_minute, o.day_start_hour))


def compute_target_mode_period(
    *,
    vbat_V: Optional[float],
    now_hour: int,
    now_minute: int,
    valve_active: bool,
    link_rssi: Optional[float],
    link_snr: Optional[float],
    o: ModeOpts,
    target_id: Optional[str] = None,
    now=None,
    logger=None
) -> Tuple[int, int, str]:
    """
    New policy (no automatic entry into Class A):
    - The mode codes are the same, but the automatic policy never uses MODE_A(1).
    - Ultra-saving is handled by always staying in MODE_B while lengthening the heartbeat period.
      * That is, Class A can only be entered when an administrator deliberately commands it for a specific purpose.

      1 = A: (admin) ultra-saving mode – not used by the automatic policy
      2 = B: power-saving mode – default operating mode, HB period adjusted longer/shorter by situation
      3 = C: performance mode – communicates most frequently, Class C based

    Battery-priority rules:
    - vbat <= vbat_critical_v:
        -> MODE_B, ultra-saving HB (hb_ultra), reason="critical_battery_b_mode"

    Day/night + battery:
    - Day (operating hours + lead included):
        vbat >= vbat_recover_v              -> MODE_C, c_period_min,  reason="day_perf" (or day_perf_prefetch)
        vbat_low_v <= vbat < vbat_recover_v -> MODE_B, b_period_min,  reason="day_b_guard"
        vbat_critical_v < vbat < vbat_low_v -> MODE_B, hb_ultra,      reason="day_ultra_low_b_mode"
    - Night:
        vbat >= vbat_low_v                  -> MODE_B, b_period_min,  reason="night_b_guard"
        vbat_critical_v < vbat < vbat_low_v -> MODE_B, hb_ultra,      reason="night_ultra_low_b_mode"

    Battery not measured (vbat_V is None):
    - If link quality is good: C or B during the day, B at night.
    - If link quality is poor or unknown: stay in B mode + ultra-saving HB, operating conservatively.
    """

    # The ultra-saving HB period is reused in B mode (A mode is not used by the automatic policy)
    hb_ultra = max(o.a_period_min, o.b_period_min, 60)

    # 0) Battery hard gate
    if vbat_V is not None and vbat_V <= o.vbat_critical_v:
        # Previously this dropped to MODE_A; now it stays in B mode + ultra-saving HB
        return MODE_B, hb_ultra, "critical_battery_b_mode"

    # Day/night decision + lead application
    day, minutes_until = resolve_day_window(
        o, now_minute, target_id=target_id, now=now, logger=logger)
    prefetch_active = False
    solar_mode = (o.day_window_mode or 'fixed') == 'solar'
    # 고정 시각에서 시작==종료는 "24시간 운영"이라 선행 전환할 대상이 없다.
    lead_applies = solar_mode or o.day_start_hour != o.day_end_hour
    if not day and o.perf_lead_min > 0 and lead_applies:
        if 0 < minutes_until <= o.perf_lead_min:
            day = True
            prefetch_active = True

    if vbat_V is not None:
        # --- Normal battery-based path ---
        if day:
            if vbat_V >= o.vbat_recover_v:
                reason = "day_perf_prefetch" if prefetch_active else "day_perf"
                return MODE_C, o.c_period_min, reason
            if vbat_V >= o.vbat_low_v:
                return MODE_B, o.b_period_min, "day_b_guard"
            # vbat_critical_v < vbat < vbat_low_v (the critical range is handled above)
            return MODE_B, hb_ultra, "day_ultra_low_b_mode"
        else:
            if vbat_V >= o.vbat_low_v:
                return MODE_B, o.b_period_min, "night_b_guard"
            # vbat_critical_v < vbat < vbat_low_v
            return MODE_B, hb_ultra, "night_ultra_low_b_mode"

    # ----- vbat unknown -> conservative link/time-based policy -----
    link_ok = True
    if link_rssi is not None:
        link_ok &= (link_rssi > o.link_rssi_min)
    if link_snr is not None:
        link_ok &= (link_snr > o.link_snr_min)

    if day:
        if valve_active and link_ok:
            # Load present and link good -> C mode
            return MODE_C, o.c_period_min, "fallback_day_perf"
        if link_ok:
            # Link good but no load -> B mode
            return MODE_B, o.b_period_min, "fallback_day_b"
        # Link poor -> stay in B mode + ultra-saving HB
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
    Serialize the policy mode into a firmware CFG frame.

    FPort 14 format: [0xD0, mode(1=A,2=B,3=C), hb_min]

    Note: the second byte is the policy mode code; the actual LoRa Class switch is
    handled by the DeviceProfile synchronization logic.
    """

    def _positive_int(value, default):
        try:
            iv = int(value)
        except Exception:
            return default
        return iv if iv > 0 else default

    # Default HB setting per mode (the class_* arguments are not used in the wire
    # format, but the signature is kept for option compatibility.)
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
    """Determine and apply optimal LoRaWAN Class and heartbeat period for a RAK3172E valve controller.

    Evaluates battery voltage, RSSI, SNR, valve activity, and time-of-day to compute the
    target mode (Class A/C) and reporting period. Enqueues downlink commands via ChirpStack
    gRPC API (DeviceService.Enqueue) only when conditions warrant a change.

    @phase co-growth
    @stability experimental
    @dependency AbstractFunction, DaemonControl, ChirpStack API
    """
    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)
        self.control = DaemonControl()
        self.timer_loop = time.time()

        # Option binding
        custom_function = db_retrieve_table_daemon(CustomController, unique_id=self.unique_id)
        self.setup_custom_options(FUNCTION_INFORMATION['custom_options'], custom_function)

        # Internal cache
        self._last_applied = None  # (mode, period)
        self._pending_apply = None  # {'mode':int, 'period':int, 'ts':float}
        self._last_rest_state = {}  # last result from _fetch_device_state()
        # ChirpStack gRPC channel cache (reused so a new channel is not created on every loop())
        self._cs_channel = None
        self._cs_channel_target = None
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
        Throttled log when no mode/period update is applied.
        Only emits when debug_logging is enabled.
        """
        if not getattr(self, 'debug_logging', False):
            return
        now = time.time()
        if (now - getattr(self, "_no_target_throttle_ts", 0.0)) < 60.0:
            return
        self._no_target_throttle_ts = now
        self.logger.info(f"lorawan_mode_manager: no apply ({reason})")

    def initialize(self):
        self.logger.info("LoRaWAN mode manager started")

    def stop_function(self):
        """Clean up the cached gRPC channel when the Function is deactivated."""
        chan = getattr(self, '_cs_channel', None)
        if chan is not None:
            try:
                chan.close()
            except Exception as e:
                self.logger.debug(f"gRPC channel close failed: {e}")
            self._cs_channel = None
            self._cs_channel_target = None
        super().stop_function()

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
        Common ChirpStack gRPC connection helper.

        - Normalizes the server address (strips http(s)://, strips path, fixes the default port)
        - Reads the API token and DevEUI
        - Checks whether grpc / chirpstack_api are available
        - Returns the gRPC channel, auth metadata, and DevEUI.

        Returns:
            (channel, metadata, deveui) or (None, None, None) on error
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

        md = [("authorization", f"Bearer {token}")]

        # 1) If a channel is already open for the same target, reuse it (avoid leaks)
        cached = getattr(self, '_cs_channel', None)
        if cached is not None and getattr(self, '_cs_channel_target', None) == server:
            return cached, md, deveui

        # 2) If the target changed or there is no channel, close the existing one and create a new one
        if cached is not None:
            try:
                cached.close()
            except Exception:
                pass
            self._cs_channel = None
            self._cs_channel_target = None

        try:
            channel = grpc.insecure_channel(server)
        except Exception:
            return None, None, None

        self._cs_channel = channel
        self._cs_channel_target = server
        return channel, md, deveui

    # --- REST API: ChirpStack device state retrieval ---
    def _rest_base(self) -> Tuple[Optional[str], dict]:
        """Return (base_url, headers) for ChirpStack REST API, or (None, {}) on error."""
        server = self._normalize_server()
        if not server:
            return None, {}
        host = server.split(':')[0]
        try:
            rest_port = int(getattr(self, 'cs_rest_port', 8090) or 8090)
        except Exception:
            rest_port = 8090
        token = self._normalize_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return f"http://{host}:{rest_port}", headers

    @staticmethod
    def _latest_metric_val(metric: dict, skip_zero: bool = True) -> Optional[float]:
        """Extract the most recent non-null, non-zero value from a ChirpStack metric dict.

        ChirpStack fills aggregation slots with 0 when no uplink arrived in that period,
        so zero is treated as "no data" by default.
        """
        datasets = metric.get('datasets', [])
        timestamps = metric.get('timestamps', [])
        if not datasets or not timestamps:
            return None
        for i in range(len(timestamps) - 1, -1, -1):
            for ds in datasets:
                data = ds.get('data', [])
                if i < len(data) and data[i] is not None:
                    try:
                        v = float(data[i])
                        if skip_zero and v == 0.0:
                            continue
                        return v
                    except Exception:
                        pass
        return None

    def _fetch_device_state(self) -> dict:
        """
        Fetch battery_V, node_class, node_hb_min, rssi, snr from ChirpStack REST API.
        Uses /api/devices/{devEui}/metrics for decoded payload fields and
        /api/devices/{devEui}/link-metrics for RSSI/SNR.
        Returns dict with Optional float/int values.
        """
        result = {'battery_V': None, 'current_mA': None, 'rssi': None, 'snr': None,
                  'node_class': None, 'node_hb_min': None, 'last_seen_at': None}

        base_url, headers = self._rest_base()
        deveui = self._normalize_deveui()
        if not base_url or not deveui:
            return result

        try:
            max_age = int(getattr(self, 'measurement_max_age', 4000) or 4000)
        except Exception:
            max_age = 4000

        now = datetime.utcnow()
        start = (now - timedelta(seconds=max_age)).strftime('%Y-%m-%dT%H:%M:%SZ')
        end = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        # HOUR aggregation: MINUTE returns 0 for sub-minute gaps with no data
        aggregation = 'HOUR' if max_age >= 3600 else 'MINUTE'
        params = {'start': start, 'end': end, 'aggregation': aggregation}

        # Device metrics: battery_V, node_class, node_hb_min
        try:
            resp = requests.get(
                f"{base_url}/api/devices/{deveui}/metrics",
                headers=headers, params=params, timeout=5)
            if resp.status_code == 200:
                metrics = resp.json().get('metrics', {})
                if 'battery_V' in metrics:
                    result['battery_V'] = self._latest_metric_val(metrics['battery_V'])
                if 'current_mA' in metrics:
                    result['current_mA'] = self._latest_metric_val(metrics['current_mA'], skip_zero=False)
                if 'node_class' in metrics:
                    v = self._latest_metric_val(metrics['node_class'])
                    result['node_class'] = int(v) if v is not None else None
                if 'node_hb_min' in metrics:
                    v = self._latest_metric_val(metrics['node_hb_min'])
                    result['node_hb_min'] = int(v) if v is not None else None
        except Exception as e:
            self.logger.debug(f"REST metrics fetch failed: {e}")

        # Link metrics: RSSI, SNR
        try:
            resp = requests.get(
                f"{base_url}/api/devices/{deveui}/link-metrics",
                headers=headers, params=params, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if 'gwRssi' in data:
                    result['rssi'] = self._latest_metric_val(data['gwRssi'])
                if 'gwSnr' in data:
                    result['snr'] = self._latest_metric_val(data['gwSnr'])
        except Exception as e:
            self.logger.debug(f"REST link-metrics fetch failed: {e}")

        # Last uplink time (used to gate measurement storage so the same value
        # is not re-stored every loop when no new uplink/HB has arrived)
        try:
            resp = requests.get(
                f"{base_url}/api/devices/{deveui}",
                headers=headers, timeout=5)
            if resp.status_code == 200:
                result['last_seen_at'] = resp.json().get('lastSeenAt')
        except Exception as e:
            self.logger.debug(f"REST device lastSeenAt fetch failed: {e}")

        self.logger.debug(
            f"REST state: battery={result['battery_V']}V "
            f"rssi={result['rssi']} snr={result['snr']} "
            f"class={result['node_class']} hb={result['node_hb_min']}min"
        )
        return result

    def _store_fetched_measurements(self, rssi, snr, battery_V, last_seen=None):
        """Write the REST-fetched link/battery values to this controller's
        measurement channels so they appear on the dashboard.

        Channel mapping (matches device_measurements config):
          0 = RSSI (dBm), 1 = SNR (dB), 2 = electrical_potential (mV)

        Duplicate handling:
        The loop runs every update_period (e.g. 10 min) but the device may send
        a heartbeat far less often, so successive loops would otherwise re-store
        the exact same REST value. Two guards prevent that:
          1) Gate on last_seen (ChirpStack lastSeenAt): skip entirely when no
             new uplink has arrived since the last stored one.
          2) Timestamp each point with the uplink time (last_seen) instead of
             "now", so even a repeated write maps to the same InfluxDB series
             point (same measurement+tags+time) and is overwritten in place
             rather than accumulating duplicates.

        battery_V comes from _fetch_device_state() in volts; channel 2 is mV,
        so it is scaled by 1000. Invalid/missing values are skipped (e.g. the
        INA219 sentinel makes battery_V None, so nothing is written for it).
        """
        # Guard 1: skip when there is no new uplink since the last store.
        if last_seen is not None and getattr(self, '_last_stored_seen', None) == last_seen:
            return

        # Parse the uplink timestamp so the point is stamped at HB time.
        ts_utc = None
        if last_seen:
            try:
                ts_utc = datetime.fromisoformat(str(last_seen).replace('Z', '+00:00'))
            except Exception:
                ts_utc = None

        def _ch(measurement, unit, value):
            m = {'measurement': measurement, 'unit': unit, 'value': float(value)}
            if ts_utc is not None:
                m['timestamp_utc'] = ts_utc
            return m

        measurements = {}
        if rssi is not None:
            measurements[0] = _ch('rssi', 'dBm', rssi)
        if snr is not None:
            measurements[1] = _ch('snr', 'dB', snr)
        if battery_V is not None:
            measurements[2] = _ch('electrical_potential', 'mV', float(battery_V) * 1000.0)
        if not measurements:
            return
        try:
            from aot.utils.influx import add_measurements_influxdb
            # use_same_timestamp=False -> use each measurement's timestamp_utc
            # (the uplink time) when available, making repeat writes idempotent.
            add_measurements_influxdb(self.unique_id, measurements,
                                      use_same_timestamp=(ts_utc is None))
            self._last_stored_seen = last_seen
            self.logger.debug(
                f"stored measurements channels={list(measurements.keys())} "
                f"seen={last_seen}")
        except Exception as e:
            self.logger.debug(f"store measurements failed: {e}")

    def _read_node_class_from_state(self, state: dict) -> Optional[str]:
        """Convert node_class int (1=A, 2=B, 3=C) from REST state to 'CLASS_X' string."""
        cid = state.get('node_class')
        if cid is None:
            return None
        mapping = {1: 'CLASS_A', 2: 'CLASS_B', 3: 'CLASS_C'}
        return mapping.get(int(cid))

    def _reconcile_device_state(self, state: dict):
        """
        Compare the (class, hb_min) the device reported via REST against the server cache.
        On mismatch (reboot / lost command), invalidate the cache to force re-sync.
        """
        node_class = self._read_node_class_from_state(state)
        node_hb = state.get('node_hb_min')
        if node_class is None and node_hb is None:
            return

        last_pair = getattr(self, '_last_class_hb', None)
        if not isinstance(last_pair, tuple) or len(last_pair) != 2:
            return  # No apply history yet, so nothing to compare against

        last_class, last_hb = last_pair
        mismatch = False
        if node_class is not None and node_class != last_class:
            mismatch = True
        if node_hb is not None and last_hb is not None and int(node_hb) != int(last_hb):
            mismatch = True

        if mismatch:
            self.logger.debug(
                f"reconcile: device reports class={node_class} hb={node_hb}min "
                f"but server cached {last_pair}; invalidating cache to resync"
            )
            self._last_class_hb = None
            self._last_applied = None

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
        Align the ChirpStack DeviceProfile's supports_class_[b|c] and the Class-B
        ping-slot freq with the end-node's actual LoRaWAN class (A/B/C).

        - node_class: 'CLASS_A' / 'CLASS_B' / 'CLASS_C'
        - previous:   previously observed class (None if unknown)

        Class A:
          - A regular user should not be able to enter it unless an administrator has a
            specific purpose, so the automatic policy does not change the DeviceProfile flags.
        """
        if not node_class:
            return

        # When the node has entered CLASS_A, leave the profile untouched.
        if node_class == 'CLASS_A':
            self.logger.debug("node_class=CLASS_A -> DeviceProfile flags unchanged")
            return

        channel, md, deveui = self._get_cs_base()
        if not channel:
            return

        try:
            dev_client = cs_api.DeviceServiceStub(channel)
            dp_client = cs_api.DeviceProfileServiceStub(channel)

            # 1) Look up Device -> DeviceProfile ID
            dreq = cs_api.GetDeviceRequest()
            dreq.dev_eui = deveui
            dresp = dev_client.Get(dreq, metadata=md)
            device = dresp.device
            profile_id = getattr(device, 'device_profile_id', '') or ''
            if not profile_id:
                self.logger.warning("Profile sync: device_profile_id not found")
                return

            # 2) Look up the DeviceProfile
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

            # 3) Target state per end-node class — ADDITIVE ONLY.
            # This DeviceProfile is shared by many devices and ChirpStack class
            # support is a per-profile setting. Disabling a class for one device
            # (e.g. a Class-B node forcing supports_class_c=False) would break
            # downlink delivery for every other device on the profile and cause
            # managers to flip-flop the flags. So we only ever ENABLE a class,
            # never disable the other one.
            if node_class == 'CLASS_B':
                want_b = True
                want_c = current_c            # keep C enabled (do not disable)
                want_freq = 923100000         # Hz, fixed ping-slot frequency
            elif node_class == 'CLASS_C':
                want_b = current_b            # keep B as-is (do not disable)
                want_c = True
                want_freq = current_freq      # no need to touch ping-slot freq for C
            else:
                # Defensive (CLASS_A already returned above)
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
            day_window_mode=str(getattr(self, 'day_window_mode', 'fixed') or 'fixed'),
            sun_offset_start_min=int(getattr(self, 'sun_offset_start_min', 0) or 0),
            sun_offset_end_min=int(getattr(self, 'sun_offset_end_min', 0) or 0),
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
        Determine the vbat value to pass to compute_target_mode_period(), reflecting the
        battery/class policy.
        Returns: (vbat_for_policy, should_skip_loop)
        - If should_skip_loop is True, the calling loop() must return immediately.
        """
        apply_only_when_valid = bool(getattr(self, 'apply_only_when_valid', False))
        role = self._role()
        # role-based default: sensor → conservative (halt on missing bat),
        #                     controller/hybrid → keep running without battery info
        _missing_default = (role == 'sensor')
        missing_vbat_is_critical = bool(getattr(self, 'missing_vbat_is_critical', _missing_default))

        # Filter out sensor invalid-sentinel / unrealistic values:
        #  - On INA219 absence/failure, the firmware sends 0xFFFF mV (=65.535V).
        #  - 0V (or near 0V) and unrealistically high voltages are "not measurable" rather than
        #    a "real low voltage", so demote them to None (missing) to avoid a false critical-battery decision.
        if vbat is not None and not (0.5 <= vbat <= 60.0):
            self.logger.debug(
                f"vbat={vbat} out of valid range [0.5, 60.0] -> treated as missing"
            )
            vbat = None

        # Conservative behavior when the battery is missing (keeps prior behavior)
        if vbat is None and apply_only_when_valid and missing_vbat_is_critical:
            self._log_no_target("skip: vbat missing & apply_only_when_valid")
            return None, True

        battery_policy_enabled = bool(getattr(self, 'battery_policy_enabled', False))
        class_policy = self._class_policy()  # 'auto' / 'force_class_*'

        if battery_policy_enabled and class_policy == 'auto':
            vbat_for_policy = vbat if (vbat is not None or missing_vbat_is_critical) else None
        else:
            # Do not switch mode based on battery -> use only the link/time-based fallback policy with vbat_V=None
            vbat_for_policy = None

        # Debug log (optional)
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
        Decide whether to apply the downlink this time, considering the last applied state
        and the retry interval. When not applying, record the reason via _log_no_target().
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

    def _role(self) -> str:
        """Return 'controller', 'sensor', or 'hybrid'."""
        return str(getattr(self, 'device_role', 'controller') or 'controller').lower()

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
                self.logger.warning("Class-C policy: device_profile_id not found")
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
            self.logger.warning(f"ChirpStack Class-C update failed: {e}")
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

        Flow:
        1) Reflect the current policy mode/heartbeat period in internal state
        2) Read the end-node class (A/B/C) from the HB measurement (input_node_class)
        3) Compare with the previously observed class and align the DeviceProfile B/C options only when it changed
           (the existing class_c_policy-based behavior is kept only when end-node class info is unavailable)
        """
        # 1) Update policy mode/HB period state
        self._current_mode = mode
        try:
            self._uplink_predictor.set_hb_period(int(period_min) * 60)
        except Exception:
            pass

        # 2) Read the end-node class from REST state cache (passed in via _last_rest_state)
        try:
            node_class = self._read_node_class_from_state(
                getattr(self, '_last_rest_state', {}))
        except Exception as e:
            self.logger.debug(f"read node_class failed: {e}")
            node_class = None

        policy = self._class_policy()
        auto_policy = (policy == 'auto')

        # 3) If end-node class info is available, sync the DeviceProfile only under the auto policy
        if node_class:
            prev = self._last_node_class_state
            self._last_node_class_state = node_class

            if auto_policy:
                # No DeviceProfile update needed if unchanged from before
                if prev == node_class:
                    return
                self._sync_profile_to_node_class(node_class, previous=prev)
                return

        # Policy-based Class management (manual policy, or no node-class measurement)
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
        # - build_mode_downlink() reflects the HB minutes (hb_min) it will actually send into
        #   the payload, so we re-parse it here and compare against the actual value.
        # - When the class is the same but the HB changed, a downlink must be sent.
        hb_min = None
        try:
            if payload and payload[0] == 0xD0 and len(payload) >= 3:
                hb_min = int(payload[2])
        except Exception:
            hb_min = None

        if hb_min is None:
            # If parsing fails, best-effort fall back to the requested period_min
            try:
                hb_min = int(period_min)
            except Exception:
                hb_min = 0

        # MODE_A/B/C -> logical class string (using the common constant)
        target_class = MODE_TO_CLASS.get(mode)

        # Skip if identical to the last successfully queued (class, hb_min)
        last_pair = getattr(self, "_last_class_hb", None)
        if target_class and hb_min > 0 and isinstance(last_pair, tuple):
            last_class, last_hb = last_pair
            if last_class == target_class and last_hb == hb_min:
                self.logger.debug(
                    f"mode-dl skip: unchanged class/HB "
                    f"class={target_class} hb={hb_min} (reason={reason})"
                )
                return True

        # 2) ChirpStack connection parameters (using the common helper)
        channel, md, deveui = self._get_cs_base()
        if not channel:
            self.logger.warning("mode-dl enqueue aborted: ChirpStack base not ready")
            return False

        # 3) Enqueue via DeviceService.Enqueue()
        # Site-wide pacing (shared limiter with the on/off output + class
        # scheduler) so concurrent mode downlinks don't flood the single
        # half-duplex gateway. (This per-device manager is deprecated, but keep
        # it paced in case it is re-enabled.)
        try:
            from aot.utils.lorawan_pacing import pace_send
            if not pace_send():
                self.logger.warning(
                    f"Mode downlink dropped ({reason}): pacing backlog too deep")
                return False
        except Exception:
            pass
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
            self.logger.debug(
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

        1) Fetch the latest readable measurements.
        2) Compute the target (mode, period_min) with compute_target_mode_period().
        3) Compare with the previously applied state and Enqueue a CFG downlink only when needed.
        4) On success, synchronize internal state/profile via _update_mode_state().
        """
        now_ts = time.time()
        try:
            update_period = float(getattr(self, 'update_period', 60.0) or 60.0)
        except Exception:
            update_period = 60.0

        # Control the loop period with an internal timer
        if now_ts < getattr(self, "timer_loop", 0.0):
            return
        self.timer_loop = now_ts + update_period

        state = self._fetch_device_state()
        self._last_rest_state = state
        vbat = state.get('battery_V')
        rssi = state.get('rssi')
        snr  = state.get('snr')

        # Persist the fetched link/battery metrics to this controller's own
        # channels (0=RSSI dBm, 1=SNR dB, 2=전위 mV) so they are visible on the
        # dashboard like the MQTT input. The function previously only used these
        # values internally for mode decisions and never stored them.
        self._store_fetched_measurements(rssi, snr, vbat, state.get('last_seen_at'))

        try:
            self._reconcile_device_state(state)
        except Exception as e:
            self.logger.debug(f"reconcile skipped due to error: {e}")

        # 운영시간은 **이 장치가 있는 곳의 벽시계**로 해석한다.
        # 예전에는 naive datetime.now() 를 썼는데, 도커 컨테이너는 tz=UTC 라
        # "4시~18시"가 한국 기준 13시~다음날 3시로 해석되고 있었다(네이티브 설치는
        # 시스템 tz 라 또 달랐다). timekit 체인으로 위치 tz 를 명시 해석한다.
        now_utc = utc_now()
        try:
            now_dt = now_utc.astimezone(resolve_location_tz(self.unique_id))
        except Exception as e:
            self.logger.debug(f"위치 tz 해석 실패, 시스템 시각 사용: {e}")
            now_dt = datetime.now()
        now_hour = now_dt.hour
        now_minute = now_dt.hour * 60 + now_dt.minute

        # current_mA > threshold → solenoid energized → valve active
        current_mA = state.get('current_mA')
        try:
            valve_active_threshold = float(getattr(self, 'valve_active_threshold_ma', 50.0) or 50.0)
        except Exception:
            valve_active_threshold = 50.0
        valve_active = (current_mA is not None and current_mA > valve_active_threshold)

        # Option binding
        opts = self._build_mode_opts()

        vbat_for_policy, should_skip = self._derive_vbat_for_policy(vbat)
        if should_skip:
            return

        # --- Added below: battery policy OFF + class policy AUTO -> simple time-based policy ---
        battery_policy_enabled = bool(getattr(self, 'battery_policy_enabled', False))
        class_policy = self._class_policy()  # 'auto' / 'force_class_*'

        if (not battery_policy_enabled) and class_policy == 'auto':
            role = self._role()
            is_day, _minutes_until = resolve_day_window(
                opts, now_minute, target_id=self.unique_id, now=now_utc, logger=self.logger)
            hb_ultra = max(opts.a_period_min, opts.b_period_min, 60)

            if role == 'sensor':
                # Sensors: Class A always (no GPS needed), longer HB at night
                if is_day:
                    mode = MODE_A
                    period_min = opts.a_period_min
                    reason = "sensor_day_a"
                else:
                    mode = MODE_A
                    period_min = hb_ultra
                    reason = "sensor_night_ultra_a"

            elif role == 'controller':
                # Controllers need responsiveness: C during operating hours, B at night
                if is_day:
                    mode = MODE_C
                    period_min = opts.c_period_min
                    reason = "ctrl_day_perf"
                else:
                    mode = MODE_B
                    period_min = opts.b_period_min
                    reason = "ctrl_night_save"

            else:
                # hybrid: time-based only, C during day as before
                if is_day:
                    mode = MODE_C
                    period_min = opts.c_period_min
                    reason = "time_only_day_perf"
                else:
                    mode = MODE_B
                    period_min = opts.b_period_min
                    reason = "time_only_night_save"
        else:
            # --- Existing policy: use forced mode / battery/link-based policy ---
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
                        target_id=self.unique_id,
                        now=now_utc,
                        logger=self.logger,
                    )
                except Exception as e:
                    self.logger.warning(f"compute_target_mode_period failed: {e}")
                    return

        now_ts = time.time()
        if not self._should_apply(mode, period_min, reason, now_ts):
            return

        # Perform the actual downlink Enqueue
        if self._enqueue_mode_downlink(mode, period_min, reason):
            self._last_applied = (mode, period_min)
            self._pending_apply = {'mode': mode, 'period': period_min, 'ts': now_ts}
            try:
                self._update_mode_state(mode, period_min)
            except Exception as e:
                self.logger.debug(f"update_mode_state failed: {e}")
