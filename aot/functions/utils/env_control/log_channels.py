# coding=utf-8
"""
env_control/log_channels.py — 의사결정 로깅 채널 표준.

매 사이클의 결정을 InfluxDB 에 기록하는 채널 번호 상수와
write_decision_log() 헬퍼를 제공한다.

채널 레이아웃 (§10):
  0~9   : L1 goal_target_<var>
  10~19 : L1 goal_priority_<var>
  20~29 : L2 situation_deviation_<var>
  30    : L2 limiting_factor
  31    : L2 mode
  40+   : L3 액추에이터 명령  (actuator_idx × 2 + 40)
  50+   : L3 액추에이터 근거  (actuator_idx × 2 + 41, 위 채널과 쌍)
  60+   : L3 적분 누적 (debug)
  70    : Gate 활성 비트마스크

참조: docs/dev/integrated_env_control_design.md §10
"""

import logging
from typing import Dict, Optional

from aot.utils.influx import write_influxdb_value

logger = logging.getLogger(__name__)

# 기록 실패가 연속될 때 매 채널마다 경고를 찍으면 로그가 폭주한다(한 사이클에
# 수십 채널). 상태가 바뀌는 순간에만 남긴다 — 실패 시작과 복구.
_write_failing = False


def _safe_write(unique_id: str, measurement: str, value: float,
                channel: Optional[int] = None, extra_tags: Optional[Dict] = None):
    """의사결정/메트릭 기록. **실패해도 절대 호출자에게 예외를 던지지 않는다.**

    이 로그들은 사후 진단용 부가 정보이지 제어의 일부가 아니다. 그런데 기록
    경로가 예외를 올리면 호출자가 통째로 중단된다 — 특히 SafetyPreGate.evaluate()
    는 게이트 판정을 다 끝낸 **뒤** 마지막 줄에서 기록하므로, 여기서 터지면
    이미 계산된 강제 폐쇄 명령을 반환도 못 하고 사이클이 죽는다(강풍·강우
    대응 미실행). 로그 한 줄이 안전 동작을 막아선 안 된다.

    실패 경로가 InfluxDB 장애만이 아니라는 점이 특히 함정이다 —
    db_retrieve_table_daemon() 은 AoT DB 조회 실패 시 조용히 `[]` 를 돌려주고,
    write_influxdb_value() 가 그 리스트에 `.measurement_db_host` 로 접근해
    AttributeError 를 낸다. 즉 **DB 락 하나로 안전 게이트가 멎는다.**
    """
    global _write_failing
    try:
        write_influxdb_value(unique_id, measurement, value=value,
                             channel=channel, extra_tags=extra_tags)
    except Exception as exc:
        if not _write_failing:
            _write_failing = True
            logger.warning(
                '의사결정 로그 기록 실패 — 제어는 계속한다 (%s ch=%s): %s',
                measurement, channel, exc)
        return
    if _write_failing:
        _write_failing = False
        logger.info('의사결정 로그 기록 복구됨 (%s)', measurement)

# ─────────────────────────────────────────────────────────────────────────────
# 변수 인덱스 — 채널 계산 기준
# ─────────────────────────────────────────────────────────────────────────────
VAR_INDEX = {
    'temperature': 0,
    'humidity':    1,
    'co2':         2,
    'vpd':         3,
}

# ─────────────────────────────────────────────────────────────────────────────
# 채널 오프셋 상수
# ─────────────────────────────────────────────────────────────────────────────
CH_GOAL_TARGET_BASE      = 0    # + VAR_INDEX[var]
CH_GOAL_PRIORITY_BASE    = 10   # + VAR_INDEX[var]
CH_SITUATION_DEV_BASE    = 20   # + VAR_INDEX[var]
CH_SITUATION_LIMIT       = 30
CH_SITUATION_MODE        = 31
CH_COORD_CMD_BASE        = 40   # + actuator_idx × 2
CH_COORD_REASON_BASE     = 41   # + actuator_idx × 2
CH_INTEGRAL_BASE         = 60   # + VAR_INDEX[var]
CH_SAFETY_GATE           = 70
CH_DISPATCH_FAIL         = 71   # 한 사이클에서 dispatch 실패한 액추에이터 수
CH_RUNTIME_STATE_FAIL    = 72   # runtime state DB 저장 실패 누적 카운트
CH_ACTUATOR_MISMATCH     = 73   # trust_score < 0.5 인 의심 액추에이터 수
CH_CLEAN_FOR_LEARNING    = 74   # 이번 사이클 학습 가능 여부 (1.0 = clean, 0.0 = dirty)
CH_GREYBOX_KPI_PASSED   = 99   # greybox shadow KPI pass notification (value = 1.0)

# ─────────────────────────────────────────────────────────────────────────────
# 근거 코드 (§10.1)
# ─────────────────────────────────────────────────────────────────────────────
REASON_IDLE             = 0    # 모든 변수 허용 범위 내
REASON_PRIMARY          = 1    # 효과 방향 일치, 비용 최저
REASON_SECONDARY        = 2    # 효과 방향 일치, 보조
REASON_WRONG_DIRECTION  = 10   # 효과 방향 불일치 — 제외
REASON_SIDE_EFFECT      = 11   # 부작용 충돌 — 제외
REASON_SAFETY_PRE_GATE  = 12   # 안전 Pre-Gate 강제 명령
REASON_UNAVAILABLE      = 13   # Output unavailable (통신 실패)
REASON_SAFETY_POST_GATE = 14   # 안전 Post-Gate 보정
REASON_NO_GRADIENT      = 15   # 구동력 없음 — 내외부 차이 부족으로 효과 없음
REASON_NO_OUTDOOR_DATA  = 16   # 실외 측정 없음 — 판단 근거가 없어 개구부 제자리 유지
                               # 15 와 구분한다: 15 는 "차이가 없다"는 **판단**이고
                               # 16 은 "판단할 근거가 없다"다. 같은 코드로 뭉치면
                               # 로그만 보고 왜 안 움직였는지 알 수 없다.
REASON_OPPOSING_PARKED  = 17   # 맞서는 짝의 진 쪽 — 지금은 반대 방향이 필요하다
                               # 15 와 구분한다: 15 는 "밀어도 안 움직인다"이고
                               # 17 은 "지금 밀 방향이 아니다"다. 같은 코드로
                               # 뭉치면 0% 로 쉬는 난방기가 화면에서 "할 수 있는
                               # 만큼 하고 있다"고 말한다 — 정반대다.
REASON_DEADZONE_BACKOFF = 18   # 목표에 닿았는데 **넘어서** 있다 — 물러난다.
                               # 데드존 안이라 P·I 는 쉬지만, 잔여 편차의 부호가
                               # 이 장치의 효과 방향과 반대다(= 이 장치가 더 밀면
                               # 목표에서 멀어진다). 1(PRIMARY)과 반드시 구분한다:
                               # 1 은 "지금 이 편차가 이 값을 시킨다"인데 여기서는
                               # **아무도 밀고 있지 않다.** 뭉치면 화면이 "적정
                               # VPD 인데 냉방 100%" 를 PRIMARY 라고 설명하게 된다.
REASON_NIGHT_PARKED     = 19   # 야간 개구부 파킹 — 밤에는 환기 대신 장치로 관리
                               # 15 와 구분한다: 15 는 "밀어도 안 움직인다" 이고
                               # 19 는 "지금은 열지 않기로 했다" 다. 사용자가 켠
                               # 옵션의 결과이므로 화면이 그렇게 말해야 한다 —
                               # 무구배로 뭉치면 "왜 밤에 창이 안 열리나" 에
                               # 답이 없다.
REASON_MANUAL_OVERRIDE  = 20   # 수동 오버라이드 — 락 활성

# 안전 게이트 비트마스크 (CH_SAFETY_GATE)
GATE_BIT_RAIN    = 1 << 0
GATE_BIT_WIND    = 1 << 1
GATE_BIT_EXT_EXP = 1 << 2
GATE_BIT_INT_EXP = 1 << 3
GATE_BIT_HEAT    = 1 << 4
GATE_BIT_COLD    = 1 << 5
# 육묘 일소 방지 — 고일사 중 습윤형 분무 잠금 (2026-07-31 aot-005 사건)
GATE_BIT_FOG_SUNBURN = 1 << 6

# 운전 모드 → 정수 코드 (CH_SITUATION_MODE)
MODE_CODES = {
    'cooling':      1,
    'heating':      2,
    'humidify':     3,
    'dehumidify':   4,
    'co2_enrich':   5,
    'conservation': 0,
    'emergency':    99,
}

# 제한 인자 → 정수 코드 (CH_SITUATION_LIMIT)
LIMIT_CODES = {
    'light':       1,
    'co2':         2,
    'temperature': 3,
    'water':       4,
}

# ─────────────────────────────────────────────────────────────────────────────
# 채널 번호 계산 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def ch_goal_target(var: str) -> int:
    return CH_GOAL_TARGET_BASE + VAR_INDEX.get(var, 9)


def ch_goal_priority(var: str) -> int:
    return CH_GOAL_PRIORITY_BASE + VAR_INDEX.get(var, 9)


def ch_situation_deviation(var: str) -> int:
    return CH_SITUATION_DEV_BASE + VAR_INDEX.get(var, 9)


def ch_coord_cmd(actuator_idx: int) -> int:
    return CH_COORD_CMD_BASE + actuator_idx * 2


def ch_coord_reason(actuator_idx: int) -> int:
    return CH_COORD_REASON_BASE + actuator_idx * 2


def ch_integral(var: str) -> int:
    return CH_INTEGRAL_BASE + VAR_INDEX.get(var, 9)


# ─────────────────────────────────────────────────────────────────────────────
# write_decision_log — 의사결정 InfluxDB 기록 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def write_decision_log(unique_id: str, measurement: str, channel: int, value: float):
    """의사결정 로그를 InfluxDB 에 기록.

    Args:
        unique_id:   AoT Function unique_id (기록 주체)
        measurement: 측정값 이름 (예: 'goal_target_temperature')
        channel:     채널 번호 (위 상수 사용)
        value:       기록할 값

    기록 실패는 삼킨다 — 이유는 _safe_write() 참조.
    """
    _safe_write(unique_id, measurement, value, channel)


# ─────────────────────────────────────────────────────────────────────────────
# P1-3: 사이클 메트릭 일괄 기록 (설계 §3.3)
# ─────────────────────────────────────────────────────────────────────────────

# InfluxDB measurement 이름 (태그: function_id, facility_id)
_MEASUREMENT_ENV = 'env_control'


def write_cycle_metrics(
    unique_id: str,
    ctx: Dict,
    target: Dict,
    deviation: Dict,
    commands: Dict,
    limiting_factor: Optional[str],
    modes: list,
    facility_id: Optional[str] = None,
):
    """
    매 사이클 종료 시 **연산 결과만** InfluxDB 에 기록한다.

    정책 (사용자 지시): 이미 기록된 데이터는 다시 저장하지 않는다.
      - 내부/외부 센서 raw 값은 Input 디바이스가 이미 기록 → 여기서 재기록 금지.
      - 액추에이터 명령 percent 는 Output 컨트롤러가 작동 상태로 기록 → 재기록 금지.
      - 본 함수는 env_coordinator 가 산출한 "결정/편차/모드" 만 남긴다.

    저장 채널 규약 (env_coordinator 의 단일 사이클 메트릭 measurement):
      CH 20~23 : 목표값 (VPD_diag, T_aux, RH_aux, CO2)
      CH 24~27 : 우선순위 (VPD, T, RH, CO2) — 동적 격상(광합성 모드) 반영
      CH 30~32 : 편차 residual (temperature, humidity, co2)
      CH 41+   : 액추에이터 근거 코드 (ch_coord_reason — value 없음)
      CH 71    : 제한 인자 코드
      CH 72    : 운전 모드 코드 (첫 번째 모드)

    이 measurement 가 사이클 결정 데이터의 단일 소스다. 과거에는 동일 데이터가
    goal_target_* / goal_priority_* / situation_deviation_* / situation_mode /
    situation_limiting_factor 개별 measurement 로도 중복 기록됐으나, 중복을
    제거하고 본 measurement 로 일원화했다.

    Args:
        unique_id:       Function unique_id (InfluxDB tag)
        ctx:             EnvContext — **본 함수는 ctx 를 읽지 않는다** (호환용 인자 유지)
        target:          EnvTarget (VPD 분해 후 working_target)
        deviation:       deviation_native dict
        commands:        CoordResult {actuator_id: ActuatorCommand} — reason 만 기록
        limiting_factor: 제한 인자 문자열 또는 None
        modes:           운전 모드 리스트
        facility_id:     GeoFacility unique_id (extra tag, 선택적)
    """
    extra = {'facility_id': facility_id} if facility_id else None

    def _w(channel: int, value: float):
        _safe_write(unique_id, _MEASUREMENT_ENV, value, channel, extra)

    # ── 목표값 (연산 결과: VPD 분해 후 working_target) ─────────────────────
    vpd_diag = target.get('_vpd_diag') or target.get('vpd')
    _w(20, vpd_diag.value if vpd_diag else 0.0)
    t_tv = target.get('temperature')
    _w(21, t_tv.value if t_tv else 0.0)
    rh_tv = target.get('humidity')
    _w(22, rh_tv.value if rh_tv else 0.0)
    co2_tv = target.get('co2')
    _w(23, co2_tv.value if co2_tv else 0.0)

    # ── 우선순위 (연산 결과: 동적 격상 반영) ──────────────────────────────
    _w(24, vpd_diag.priority if vpd_diag else 0.0)
    _w(25, t_tv.priority  if t_tv  else 0.0)
    _w(26, rh_tv.priority if rh_tv else 0.0)
    _w(27, co2_tv.priority if co2_tv else 0.0)

    # ── 편차 (연산 결과) ─────────────────────────────────────────────────
    _w(30, deviation.get('temperature', 0.0))
    _w(31, deviation.get('humidity',    0.0))
    _w(32, deviation.get('co2',         0.0))

    # ── 액추에이터 근거 코드만 (명령 percent 는 Output 컨트롤러가 기록) ──
    for idx, (aid, cmd) in enumerate(sorted(commands.items())):
        _w(ch_coord_reason(idx), float(cmd.reason))

    # ── 제한 인자 + 운전 모드 (연산 결과) ────────────────────────────────
    _w(71, float(LIMIT_CODES.get(limiting_factor, 0)))
    primary_mode = modes[0] if modes else 'conservation'
    _w(72, float(MODE_CODES.get(primary_mode, 0)))
