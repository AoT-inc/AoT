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
  75·76 : 극한 고온 보호 단계·플래그 (매 사이클, debug 무관)
  80~91 : 센서 상태·VPD 출처 (measurement `sensor_status`, 아래 CH_SENSOR_STATUS_BASE)
  92    : 분무용 물 공급 판정 (옵션을 켰을 때만, debug 무관)
  93    : 제어에서 빼 둔 의심 액추에이터 수 (매 사이클, debug 무관)
  94~96 : VPD 목표 기준(공기/잎)·잎 VPD·잎 기준 목표 (엽온을 묶었거나 잎 기준일 때만, debug 무관)

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
CH_SITUATION_DEV_VPD     = 33   # VPD 직접 제어 모드의 편차(측정-목표) — write_cycle_metrics 전용.
                                 # T/RH 는 VPD 모드에서 '_temperature_constraint' 로 강등돼
                                 # deviation_native 에서 빠지므로 CH30/31 은 항상 0 이 찍히고,
                                 # 실제로 액추에이터를 움직이는 이 값만 로그에 없었다
                                 # (2026-08-29 영양 육묘장 — 난방기가 VPD 편차와 반대로
                                 # 40분간 올라간 사건을 사후에 재구성할 수 없었던 원인).
CH_COORD_CMD_BASE        = 40   # + actuator_idx × 2 — 코디네이터가 **요청한** 값
CH_COORD_REASON_BASE     = 41   # + actuator_idx × 2
# 요청과 실제로 나간 값은 다르다. coordinate() 가 낸 명령은 그 뒤
# `apply_threshold_and_gate_overrides`(임계·육묘 분무 감쇠·안전 프리게이트·
# 냉난방 인터록)와 Post-Gate 를 지나며 통째로 0 이 될 수 있고, 위 40/41 은
# 그 **앞**에서 기록된다. 그래서 40 만 읽으면 "요청했다" 를 "작동했다" 로
# 오독한다 — 2026-08-30 영양·쿠마모토 점검에서 실제로 그렇게 오보했다
# (분무 게이트가 98% 잠겨 이틀간 한 번도 안 나갔는데 "평균 23% 작동 중").
CH_COORD_FINAL_BASE      = 100  # + actuator_idx × 2 — 디스패치 직전 **최종** 값
CH_COORD_FINAL_REASON_BASE = 101  # + actuator_idx × 2
CH_INTEGRAL_BASE         = 60   # + VAR_INDEX[var]
CH_SAFETY_GATE           = 70
CH_DISPATCH_FAIL         = 71   # 한 사이클에서 dispatch 실패한 액추에이터 수
# ⚠ **71·72 는 번호가 두 번 쓰인다** — 측정 이름으로 가른다. `dispatch_fail_count`
#   (실패 수) / `runtime_state_fail`(저장 실패) 와, `write_cycle_metrics` 의
#   `env_control` 71(제한 인자 코드)·72(운전 모드 코드)는 다른 값이다. 번호만 보고
#   읽으면 낮마다 "디스패치 실패 1" 로 오독한다(2026-09-26 점검에서 실제로 그랬다).
#   과거 기록과 이어지지 않으므로 번호는 바꾸지 않는다.
CH_RUNTIME_STATE_FAIL    = 72   # runtime state DB 저장 실패 누적 카운트
CH_ACTUATOR_MISMATCH     = 73   # trust_score < 0.5 인 의심 액추에이터 수
CH_CLEAN_FOR_LEARNING    = 74   # 이번 사이클 학습 가능 여부 (1.0 = clean, 0.0 = dirty)
# 극한 고온 보호(`heat_protect`, 2026-10-09) — **debug 여부와 무관하게 매 사이클** 기록한다.
# 보호가 섰는지·왜 그 조치였는지는 사후에 반드시 답해야 하는 질문이라 `env_control`
# (debug 전용)에 싣지 않는다. 71·72 는 이중 의미라(위 주석) 쓰지 않는다.
CH_HEAT_PROTECT_TIER     = 75   # 0 보호 아님 · 1 문턱 초과 · 2 하드 상한(temp_max) 초과
CH_HEAT_PROTECT_FLAGS    = 76   # 비트마스크 — `heat_protect.HP_FLAG_*`
# ── 센서 상태 (measurement 'sensor_status') ──────────────────────────────────
# 75·76 은 극한 고온 보호(heat_protect_*)가 쓰고, 80 미만은 건드리지 않는다.
# 71·72 처럼 번호를 다른 측정과 나눠 쓰지 않도록 **자기 측정 이름**을 갖는다.
# 값은 `sensor_status.STATUS_CODES`: 0 valid · 1 stale · 2 missing · 3 outlier ·
# 4 out_of_range · 5 frozen. 축을 먹이는 센서 중 **가장 좋은** 상태다(`best_status`).
CH_SENSOR_STATUS_BASE    = 80   # + 축 위치 — 아래 SENSOR_STATUS_AXES 순서(80~89)
CH_VPD_SOURCE            = 90   # 제어 VPD 출처: 0 none · 1 computed(T/RH) · 2 device
CH_VPD_DEVICE_DIFF       = 91   # 장치 VPD − 제어 VPD [kPa] (둘 다 있을 때만 기록)
MEAS_SENSOR_STATUS       = 'sensor_status'
# 축 순서가 곧 채널 번호다 — 바꾸면 과거 기록과 이어지지 않는다.
SENSOR_STATUS_AXES = ('T', 'RH', 'CO2', 'VPD', 'light',
                      'T_ext', 'RH_ext', 'wind', 'rain', 'solar')
# 분무용 물 공급(`water_supply`, 2026-10-09) — 옵션을 켠 코디네이터만 매 사이클 남긴다
# (켜지 않은 설치에 쓸모없는 행을 쌓지 않는다). 77~79 는 비워 두고 80~91 은 센서 상태가 쓴다.
CH_WATER_SUPPLY          = 92   # 1 정상 · 2 부족(문턱 미달) · 3 신호 끊김(없음·만료) — `water_supply.WATER_*`
# 의심 액추에이터(`actuator_feedback`, 2026-10-09) — 제어에서 빼고 제자리에 둔(보류 중인) 수.
# 73 은 trust_score 기반의 **로그 전용** 수이고 debug 에서만 남는다 — 이것은 제어 결정이라 늘 남긴다.
CH_ACTUATOR_SUSPECT      = 93
# VPD 목표 기준(`leaf_vpd`, 2026-10-09) — 엽온 신호를 묶었거나 `vpd_target_basis=leaf` 인
# 코디네이터만 매 사이클 남긴다(기본 설치에는 행이 없다). 잎 기준이면 CH3(goal_target_vpd)은
# **옮긴 공기 목표**가 되므로, 사람이 정한 잎 목표는 96 에서 읽는다.
CH_VPD_TARGET_BASIS      = 94   # 0 공기 기준 · 1 잎 기준(엽온으로 옮김) · 2 잎 기준인데 엽온 없음 → 공기 — `leaf_vpd.TARGET_*`
CH_LEAF_VPD              = 95   # 잰 엽온의 잎 VPD [kPa] (엽온이 유효할 때만)
CH_LEAF_VPD_TARGET       = 96   # 잎 기준 목표 [kPa] — 옮기기 전, 사람이 정한 값(잎 기준·목표가 있을 때만)
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
REASON_NO_MEASUREMENT   = 21   # 실내 측정 없음 — 이 장치를 움직일 근거가 없어
                               # 제자리 유지. **16 의 실내판**이다(16 은 실외).
                               # 15 와 반드시 구분한다: 15 는 "차이가 없다"는
                               # 판단이고 21 은 "판단할 값이 없다" 다. 뭉치면
                               # 센서가 끊긴 시설에서 화면이 "지금은 효과가
                               # 없습니다" 라고 말하는데, 실제로는 효과를 잴
                               # 수단이 없는 것이다 — 사람이 해야 할 조치
                               # (센서 점검)가 그 문장에서 안 보인다.
REASON_CURTAIN_DAY_OPEN = 22   # 낮 — 보온커튼은 걷어 둔다(빛). 효과 모델은 커튼의 열
                               # 교환만 보고 빛 차단을 모르므로, 모델에 맡기면 낮에도
                               # 닫는다(2026-09-25~26 영양 — 오전 8시에 닫혀 28시간
                               # 그대로였다). 안전 게이트(한파 등)는 이것보다 뒤에서 이긴다.
REASON_DIRECTION_UNSETTLED = 23  # 미는 방향이 막 뒤집혔다 — 확정될 때까지 제자리.
                               # 창의 VPD 효과는 "식힘(↓)" 과 "건조한 외기(↑)" 가 겨룬
                               # 합이라, 실외 습도가 조금만 흔들려도 부호가 사이클마다
                               # 바뀐다(2026-09-24 영양 천창: 6시간 반전 24회). 1 과
                               # 뭉치면 "왜 안 움직이나" 에 답이 없다.
REASON_HUMID_NO_RELIEF = 24    # 과습 — 환기로 해소할 수 없다: 실외 이슬점이 실내보다 낮지
                               # 않아 창을 열면 습기를 들인다. 창은 닫는 쪽으로 가고 난방·
                               # 제습 장치가 있으면 그쪽이 맡는다. **15(무구배)와 구분한다**
                               # — 15 는 "차이가 없다" 이고 24 는 "차이는 있는데 방향이
                               # 나쁘다" 다. 뭉치면 화면이 "효과가 없다" 고만 말해, 실제로는
                               # 해소 수단이 없는 과습 상태라는 사실이 가려진다.
REASON_HUMID_CAPPED    = 25    # 과습 — 환기가 습기를 빼지만 열림을 제한한다(기본 30 %).
                               # 습기를 빼는 것이 목적이지 환기로 온도·VPD 를 맞추는 것이
                               # 아니다. 1(주작용)로 두면 "왜 더 안 여나" 에 답이 없다.
REASON_HUMID_COLD      = 27    # 과습이지만 실외가 너무 차다(또는 난방 요구 중) — 열면 열을 버린다.
                               # 24 와 구분한다: 24 는 실외가 **더 습하다**, 27 은 실외는 건조한데
                               # **차다**. 뭉치면 겨울 난방 중 "환기해도 소용없다" 고만 읽혀 닫힌
                               # 이유(열 손실)가 가려진다.
REASON_NO_RESPONSE     = 26    # 창을 열어도 편차가 줄지 않는다 — 더 열지 않는다. 효과가 작은
                               # 창(유효도 낮음)이 오래 열려 있는데 실내가 안 변하면, 적분만
                               # 쌓여 창이 천천히 100 % 로 올라간다(드리프트, 2026-10-01).
REASON_HEAT_VENT_HOT_OUTSIDE = 28  # 극한 고온 보호 중인데 바깥이 더 덥다 — 환기를 닫는 쪽(파킹).
                               # 15(무구배)와 구분한다: 15 는 "차이가 없다" 이고 28 은 "열면
                               # 더 뜨거운 공기를 들인다" 다. 뭉치면 폭염 중 창이 닫힌 이유가
                               # 화면에서 "효과 없음" 으로만 읽힌다(`heat_protect`).
REASON_HEAT_FOG_BLOCKED = 29   # 극한 고온 보호 중 분무를 쉰다 — 물이 없거나, 증발 여력(건구 −
                               # 습구)이 모자라거나, 습도가 이미 높다. 17(맞선 짝)과 구분한다:
                               # 냉각이 필요한데 분무로는 식힐 수 없거나 해롭다는 판단이다.

# ── 임계 오버라이드 계열 (30~) ────────────────────────────────────────────────
# `apply_threshold_and_gate_overrides` 가 지나는 헬퍼들은 근거를 **문자열**로
# 남긴다(`{'value': 0.0, 'reason': 'humid_max'}`). coordinate() 가 내는 정수
# 코드와 어휘가 갈라져 있는데, 최종 명령 로그(CH100 계열)는 그 둘을 한 채널에
# 싣는다 — 그래서 여기서 정수로 옮긴다.
#
# ⚠ 2026-08-30: 이 표가 없던 사이 `write_final_commands` 가 문자열을
#   `float()` 에 넘겨 **사이클을 통째로 죽였다**. 예외가 디스패치 앞에서
#   터지므로, 하필 하드 임계가 걸린 그 사이클의 명령이 전송되지 않았다.
REASON_LIMIT_LIGHT_MAX     = 30
REASON_LIMIT_LIGHT_MIN     = 31
REASON_LIMIT_TEMP_MAX      = 32
REASON_LIMIT_TEMP_MIN      = 33
REASON_LIMIT_HUMID_MAX     = 34
REASON_LIMIT_HUMID_MIN     = 35
REASON_FOG_DERATE          = 36
REASON_FOG_HUMIDITY_CEILING = 37
REASON_NO_ACTUATOR         = 38
REASON_UNKNOWN             = 39   # 표에 없는 근거 — 삼키지 않고 '모른다'로 남긴다
REASON_HEAT_PROTECT        = 40   # 극한 고온 보호 오버라이드(`heat_protect.apply_heat_protect_overrides`)
REASON_NO_WATER            = 41   # 분무용 물이 없다 — 분무기 전부를 쉰다(`water_supply`). 29(폭염 중 분무 불가:
                                  # 물·증발 여력·습도 중 하나)와 구분한다: 41 은 **원인이 물**이라는 뜻이고
                                  # 폭염이 아니어도 선다. 둘이 겹치면 41 이 이긴다 — 사람이 할 일(물 채우기)이 보인다.
REASON_ACTUATOR_SUSPECT    = 42   # 의심 액추에이터 — 고장일 수 있어 부하 분담에서 빼고 제자리에 둔다
                                  # (`actuator_feedback`; 같은 도메인의 나머지가 몫을 이어받는다).
                                  # 13(REASON_UNAVAILABLE, 통신 실패)과 구분한다: 13 은 한 번의 실패,
                                  # 42 는 반복된 전송 실패 또는 오래 세게 명령했는데 반응이 없다는 **판정**이다.
# 43~47 = 스크린 판단(`screen_policy`, 2026-10-09). 1(주작용)·15(무구배)와 뭉치지 말 것 — 스크린은
# 빛·결로를 함께 다뤄 "왜 이 막이 이 자리인가" 의 답이 열·VPD 편차만이 아니다.
REASON_SHADE_HEAT          = 43   # 차광막을 열부하·증산 조절에 쓰는 중(광 상태가 허락한다)
REASON_SHADE_LIGHT_KEEP    = 44   # 차광막을 걷어 둔다 — 빛이 모자라거나(DLI·light_min) 더 싼 냉각 수단이 남았다
REASON_SCREEN_HOLD         = 45   # 차광막 왕복 방지 — 최소 유지·진입 지속·일사 이력·하루 이동 한도로 제자리
REASON_CURTAIN_GAP         = 46   # 밤 결로 — 보온커튼을 조금(3·6·10 %) 연다(부분 개도가 되는 커튼만)
REASON_CURTAIN_RAMP        = 47   # 아침 — 보온커튼을 단계(10·30·60 %)로 걷는 중(부분 개도가 되는 커튼만)
REASON_PREPARK_HOLD        = 48   # 야간 파킹 직전 — 해 질 무렵 창을 VPD·습도 요구로 더 열지 않는다(제자리).
                                  # 19(REASON_NIGHT_PARKED)와 구분한다: 19 는 닫는 중이고 48 은 닫기 **전에**
                                  # 열림을 키우지 않는 중이다 — 요구는 열라고 하는데 곧 닫힐 것이라 묶어 둔 것.
                                  # 16(실외 모름)·23(방향 확정 대기)과도 다르다: 이유가 시각(파킹 시작 45분 전)이다.
REASON_CURTAIN_NIGHT_CLOSE = 49   # 밤 보온 — 열 수요(실내가 목표 하한 근처·아래, 또는 실외가 목표 하한 아래)로
                                  # 보온커튼을 닫아 둔다(`screen_policy._curtain_night_close`, 2026-10-10).
                                  # 15(무구배)와 뭉치지 말 것: 걷힌 커튼 아래의 작은 안팎 온도차는 커튼이
                                  # 지운 것이라 "닫아도 소용없다" 의 근거가 못 된다. 33(최저 온도 한계)은
                                  # 하드 한계가 닫은 것이고 49 는 그 전에 보온으로 닫은 것이다.
# 50 은 비워 둔다 — 병합 전 다른 브랜치가 쓰고 있다(2026-10-10).
REASON_SOLAR_VENT_FLOOR    = 51   # 낮 일사 부하 — 해가 들고 실내가 온도 목표 위라 환기를 하한까지 연다
                                  # (`solar_vent`, 2026-10-10 영양). VPD·습도 항은 그 아래로 닫지 못한다 —
                                  # 모자라는 습도는 분무·차광이 맡는다. 1(주작용)·15(무구배)와 뭉치지 말 것:
                                  # 요구가 닫으라고 하는데 일사 열을 빼려고 열어 둔 것이다. 40(극한 고온
                                  # 보호)과도 다르다 — 그 문턱 **아래**에서, 일사가 있을 때만 선다.
REASON_RAIN_RESTRICT       = 52   # 비 — 전면 폐쇄까지는 아닌 강우의 단계 제한(`safety_gates.classify_rain`,
                                  # 2026-10-10 구마모토). 예보 모델 강우(Open-Meteo 등)나 바람 없는 약한 실측
                                  # 강우에서 천창을 닫고(0) 측창은 상한(30 %) 아래로만 쓴다. 약한 모델 강우에서는
                                  # 천창을 **더 열지 않는다**(제자리). 12(전면 강제 폐쇄)와 뭉치지 말 것 — 12 는
                                  # 실측 강우·강풍으로 L1~L3 를 건너뛴 것이고, 52 는 제어가 돌면서 비 때문에
                                  # 열림을 묶은 것이다. 16(실외 모름, 더 열지 않음)과도 다르다: 값은 있다.
REASON_WETTING_FOG_DUSK    = 53   # 습윤형 분무를 해 질 녘에 줄이거나 쉰다 — 일사가 약하거나(150→50 W/m² 비례 감쇠)
                                  # 일몰 90분 전부터 일출까지(육묘 모드는 `nursery_evening_cutoff_min`, 기본 120분)
                                  # (`wet_fog_dusk`, 2026-10-10 영양·김제). 36(분무 감쇠)과
                                  # 뭉치지 말 것: 36 은 육묘 모드에서 **강한** 햇빛 쪽을 줄이고 53 은 **약한**
                                  # 햇빛·저녁 쪽을 줄인다. 37(분무 습도 상한)과도 다르다 — 이유가 습도 숫자가 아니라
                                  # 잎이 밤을 젖은 채 넘기는 것이다. 29(폭염 중 분무 불가)와도 다르다.
REASON_MORNING_PURGE       = 54   # 아침 습기 빼기 — 해가 들었고 실내가 과습인데 실외 공기가 더 건조해, 27(실외가 너무
                                  # 참)로 닫는 대신 환기창을 조금(5~15 %) 연다(`humid_regime.morning_purge`,
                                  # 2026-10-10 영양·김제). 27·24·25 와 뭉치지 말 것: 27 은 닫은 것, 25 는 상한,
                                  # 54 는 닫으라는 판단을 **이기고** 열어 둔 하한이다. 51(일사 부하)과도 다르다 —
                                  # 51 은 실내가 온도 목표 위일 때의 열 빼기이고 54 는 목표 아래에서도 서는 습기 빼기다.
REASON_WIND_RESTRICT       = 55   # 바람 — 전면 폐쇄까지는 아닌 강풍 1단계(`safety_gates.classify_wind`, 2026-10-10
                                  # 폭풍 시뮬 푄). 10분 평균이 문턱의 0.6 배 이상이거나 돌풍이 0.9 배 이상이면 풍상측
                                  # 개구부·방위각 모르는 천창을 닫고(0) 나머지는 상한(천창 30 %·측창 50 %) 아래로만
                                  # 쓴다. 12(전면 강제 폐쇄 = 강풍 2단계)와 뭉치지 말 것 — 12 는 L1~L3 를 건너뛴
                                  # 것이고 55 는 제어가 돌면서 바람 때문에 열림을 묶은 것이다. 52(비 단계 제한)와도
                                  # 다르다: 같은 상한 장치를 쓰지만 이유가 바람이다.

REASON_FROST_PROTECT       = 56   # 서리 — 서리 주의·보호 단계가 시킨 값(`safety_gates.evaluate_frost`, 2026-10-10
                                  # 극단 날씨 폐루프 cold_snap_frost). 보호: 개구부 닫음·커튼 닫음·난방 100·유동팬 100·분무
                                  # ·CO₂ 끔. 주의: 커튼 닫음, 개구부는 더 열지 않음. 12(한파 비상·강우·강풍 전면 폐쇄)와
                                  # 뭉치지 말 것 — 12 는 실외 −5 °C **그리고** 실내 5 °C 이하의 비상이고, 56 은 그보다 훨씬
                                  # 일찍(실내 4 °C·복사냉각이면 6 °C) 서는 작물 보호다. 33(최저 온도 한계)과도 다르다 — 그쪽은
                                  # 사용자가 정한 선이고 56 은 얼음이 맺히는 물리의 선이다. 52(강우 제한)와도 같이 서지 않는다.

REASON_EXTREME_PULSE_FOG   = 57   # 극한 고온·건조의 짧은 펄스 분무 — 일소 잠금이 서 있어도(극한 고온 보호 단계 ≥ 1 또는
                                  # 실내 VPD > 3 kPa, 건구−습구 ≥ 8 °C, 습도·물·저녁 제한·게이트 모두 통과) 10초 켜고 15분 이상
                                  # 쉬는 펄스 하나를 낸다(`pulse_fog`, 2026-10-12). 36(분무 감쇠)·53(해 질 녘 제한)과 뭉치지 말 것:
                                  # 둘은 분무를 **줄이는** 이유이고 57 은 잠금 속에서 **허용한** 펄스다. 29(폭염 중 분무 불가)와도
                                  # 반대다 — 29 는 증발 여력이 없어 막은 것, 57 은 여력이 커서 짧게 연 것이다.

REASON_OUTAGE_CLOSE        = 58   # 실외 값이 없는 동안 닫는 쪽 — 해가 진 뒤 조금(≤ 10 %) 열린 창을 닫는다. 두절이 30 분 넘게
                                  # 이어진 밤에는 습도(하드 상한·파킹 해제)로 열린 창도 사이클당 5 %p 씩 0 까지 내린다
                                  # (`coordinator.decide_parking` 2.6b·`outage_clock`, 2026-10-12 김제). 16(실외 모름, 제자리)과
                                  # 뭉치지 말 것: 16 은 움직이지 않는 것이고 58 은 **닫는** 이동이다 — 실외를 몰라
                                  # 열 근거는 없지만, 밤에 조금 열린 창은 닫아 두는 쪽이 안전하다(비·찬 공기). 19(야간
                                  # 파킹)와도 다르다: 19 는 사용자가 켠 파킹 옵션이 시킨 닫음이고 58 은 옵션과 무관하다.

REASON_NIGHT_DEW_FAN       = 59   # 밤 이슬 — 해 진 뒤 닫힌 집의 이슬점 여유가 작아(< 2 °C, 풀림 3 °C) 순환팬을 100 % 로 돌린다
                                  # (`night_dew`, 2026-10-12 폐루프 heatwave_tropical_night: 열대야에는 창을 열어도 습기가
                                  # 안 빠져 밤 작물 젖음 1148 분). 습기를 빼는 것이 아니라 잎이 젖어 있는 시간을 줄이는 수단이다.
                                  # 1(주작용)과 뭉치지 말 것 — 1 은 효과 방향이 맞는 일반 명령이고 59 는 이 규칙만이 팬을 세운
                                  # 사이클이다(공간 불균일·극한 고온 보호로 선 팬은 1·40 을 그대로 둔다). 56·40(서리·고온 보호가
                                  # 세운 유동팬)과도 다르다: 그쪽이 이긴다.

REASON_BLIND_SUN_VENT      = 60   # 실내 측정이 모두 끊긴 동안 **해를 보고** 정한 작은 환기 — 맑은 낮(일사 · 외기 ≥ 12 °C ·
                                  # 외기 + 0.02 × 일사 > 작물 선)이면 환기창을 10~20 % 까지 사이클당 5 %p 씩 열고, 해가 진
                                  # 뒤에도 실내를 모르면 그 크기 이하로 열린 창을 같은 폭으로 닫는다(`solar_vent` 머리말 마지막
                                  # 절, 2026-10-14 김제·구마모토: 실내 두절 중 맑은 낮에 창 0 %). 21(실내 모름, 제자리)과
                                  # 뭉치지 말 것 — 21 은 움직이지 않은 것이고 60 은 실외·해만으로 **움직인** 것이다. 51(일사
                                  # 부하 하한)과도 다르다: 51 은 실내가 선 위인 것을 **재서** 연 것이다. 58(실외 모름 닫기)은
                                  # 실외를 모를 때의 닫음이고 60 은 실내를 모를 때다.

# 문자열 근거 → 정수 코드. **새 문자열 근거를 만들면 여기 넣을 것** — 빠뜨려도
# 이제 죽지는 않지만(REASON_UNKNOWN 으로 떨어진다) 화면이 이유를 말하지 못한다.
STRING_REASON_CODES = {
    'light_max':            REASON_LIMIT_LIGHT_MAX,
    'light_min':            REASON_LIMIT_LIGHT_MIN,
    'temp_max':             REASON_LIMIT_TEMP_MAX,
    'temp_min':             REASON_LIMIT_TEMP_MIN,
    'humid_max':            REASON_LIMIT_HUMID_MAX,
    'humid_min':            REASON_LIMIT_HUMID_MIN,
    'nursery_fog_derate':   REASON_FOG_DERATE,
    'fog_humidity_ceiling': REASON_FOG_HUMIDITY_CEILING,
    'no_actuator':          REASON_NO_ACTUATOR,
    'unavailable':          REASON_UNAVAILABLE,
    'heat_protect':         REASON_HEAT_PROTECT,
    'no_water':             REASON_NO_WATER,
    'wetting_fog_dusk':     REASON_WETTING_FOG_DUSK,
    'extreme_pulse_fog':    REASON_EXTREME_PULSE_FOG,
}


def reason_code(reason) -> float:
    """근거를 정수 코드로 옮긴다. **어떤 입력에도 예외를 던지지 않는다.**

    최종 명령의 근거는 정수(coordinate())일 수도 문자열(임계 오버라이드)일
    수도 있다. 여기서 터지면 로그 한 줄이 제어를 멈춘다 — 실제로 그렇게
    했다(2026-08-30, 'humid_max' → ValueError → 디스패치 미실행).
    """
    if reason is None:
        return float(REASON_IDLE)
    if isinstance(reason, str):
        return float(STRING_REASON_CODES.get(reason, REASON_UNKNOWN))
    try:
        return float(reason)
    except (TypeError, ValueError):
        return float(REASON_UNKNOWN)

def reason_name(reason) -> str:
    """근거 → 이름(`REASON_HUMID_COLD` → 'humid_cold'). 예외를 던지지 않는다.

    이름은 이 모듈의 상수에서 파생한다 — 표를 따로 두면 새 코드가 생길 때
    갈라진다. 외부 AI 가 `get_control_state` 의 숫자 근거(27·12)만 보고는 창이
    왜 닫혀 있는지 알 수 없었다(2026-10-10 외부 AI 5차 점검)."""
    code = int(reason_code(reason))
    for k, v in globals().items():
        if k.startswith('REASON_') and v == code and isinstance(v, int):
            return k[len('REASON_'):].lower()
    return 'unknown'


# 안전 게이트 비트마스크 (CH_SAFETY_GATE)
GATE_BIT_RAIN    = 1 << 0
GATE_BIT_WIND    = 1 << 1
GATE_BIT_EXT_EXP = 1 << 2   # 강우·풍속을 잃음 → 개구부 "더 열지 않음"(2026-09-19 재정의;
                            # 전에는 실외 컨텍스트 300초 만료 → 개구부·차광막 0 강제)
GATE_BIT_INT_EXP = 1 << 3   # 실내 값을 잃음 → 근거를 잃은 장치는 **제자리**
                            # (2026-09-20 재정의; 전에는 내부 센서 120초 만료 →
                            # 전 액추에이터 safe_default 강제. 그 타이머는
                            # 호출자가 `last_int_ts` 에 매번 now 를 실어 보내
                            # 한 번도 돈 적이 없다)
# ⚠ 폭염 비상 게이트는 2026-10-09 에 없앴다(`heat_protect` 가 대신한다). 이 비트는
#   **옛 CH70 기록을 해독하려고만** 남긴다 — 지금 코드는 세우지 않는다.
GATE_BIT_HEAT    = 1 << 4
GATE_BIT_COLD    = 1 << 5
# 육묘 일소 방지 — 고일사 중 습윤형 분무 잠금 (2026-07-31 aot-005 사건)
GATE_BIT_FOG_SUNBURN = 1 << 6
# 강우 **단계 제한**(2026-10-10) — 예보 모델 강우 또는 바람 없는 약한 실측 강우. 전면 폐쇄
# (`GATE_BIT_RAIN`)가 아니라 제약이다: 천창 닫음·측창 상한·천창 더 열지 않음(근거 52),
# L1~L3 는 그대로 돈다. RAIN 과 같은 사이클에 서지 않는다(전면 폐쇄가 이긴다).
GATE_BIT_RAIN_LIGHT = 1 << 7
# 강풍 **1단계**(2026-10-10) — 10분 평균 ≥ 문턱×0.6 또는 돌풍 ≥ 문턱×0.9. 전면 폐쇄
# (`GATE_BIT_WIND` = 2단계)가 아니라 제약이다: 풍상측·방위각 모르는 천창 닫음, 나머지 상한
# (근거 55), L1~L3 는 그대로 돈다. WIND 와 같은 사이클에 서지 않는다(2단계가 이긴다).
GATE_BIT_WIND_LIGHT = 1 << 8
# 서리(2026-10-10) — 한파 비상(`GATE_BIT_COLD`, 실외 −5 °C·실내 5 °C)보다 훨씬 일찍 서는 작물 보호.
# WATCH 는 제약이다(커튼 닫음·개구부 더 열지 않음, L1~L3 는 그대로 돈다), 보호(`GATE_BIT_FROST`)는
# 한파 비상처럼 L1~L3 를 건너뛰고 강제 명령을 낸다. 둘은 같은 사이클에 함께 서지 않는다.
GATE_BIT_FROST_WATCH = 1 << 9
GATE_BIT_FROST       = 1 << 10

# 운전 모드 → 정수 코드 (CH_SITUATION_MODE)
MODE_CODES = {
    'cooling':      1,
    'heating':      2,
    'humidify':     3,
    'dehumidify':   4,
    'co2_enrich':   5,
    'heat_protect': 6,    # 극한 고온 보호 단계 1 (단계 2 는 'emergency' 99)
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


def ch_coord_final(actuator_idx: int) -> int:
    return CH_COORD_FINAL_BASE + actuator_idx * 2


def ch_coord_final_reason(actuator_idx: int) -> int:
    return CH_COORD_FINAL_REASON_BASE + actuator_idx * 2


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
      CH 33    : 편차 residual (vpd) — VPD 직접 제어 모드에서만 값이 실린다
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
    # VPD 직접 제어 모드(vpd_sp_type=method)에서는 온습도가 '_temperature_constraint'
    # 로 강등돼 위 두 줄이 항상 0 을 찍는다 — 실제로 액추에이터를 움직이는 값은
    # 이 채널뿐이다. deviation 에 'vpd' 가 없으면(T/RH 직접 제어 모드) 0.0.
    _w(CH_SITUATION_DEV_VPD, deviation.get('vpd', 0.0))

    # ── 액추에이터 근거 코드만 (명령 percent 는 Output 컨트롤러가 기록) ──
    for idx, (aid, cmd) in enumerate(sorted(commands.items())):
        _w(ch_coord_reason(idx), float(cmd.reason))

    # ── 제한 인자 + 운전 모드 (연산 결과) ────────────────────────────────
    _w(71, float(LIMIT_CODES.get(limiting_factor, 0)))
    primary_mode = modes[0] if modes else 'conservation'
    _w(72, float(MODE_CODES.get(primary_mode, 0)))


# ─────────────────────────────────────────────────────────────────────────────
# 최종 명령 기록 — 게이트·감쇠·인터록을 **모두 지난 뒤**의 값
# ─────────────────────────────────────────────────────────────────────────────

def write_final_commands(unique_id: str, final_cmds: Dict,
                         actuator_index: Dict[str, int]):
    """디스패치 직전의 최종 명령을 기록한다.

    `coord_actuator_<id8>_command`(CH40+) 는 coordinate() 안에서 찍히므로
    **요청값**이다. 그 뒤 임계 오버라이드·육묘 분무 감쇠·습윤 분무 상한·
    안전 프리게이트·냉난방 인터록이 값을 바꾸거나 0 으로 끊는다. 그 결과를
    남기지 않으면 "왜 장치가 안 돌았는가" 를 로그로 답할 수 없다.

    둘을 **함께** 남기는 이유: 차이 자체가 진단이다. 요청 23% · 최종 0% 이면
    코디네이터 판단이 아니라 게이트를 봐야 한다는 뜻이고, 둘이 같으면
    코디네이터를 봐야 한다는 뜻이다. 한쪽만 남기면 그 갈림길이 사라진다.

    Args:
        unique_id:      Function unique_id
        final_cmds:     {actuator_id: {'value':…, 'reason':…}} 또는 ActuatorCommand
        actuator_index: {actuator_id: idx} — CH40 계열과 **같은 인덱스**여야
                        요청/최종이 같은 장치로 짝지어진다.
    """
    if not unique_id or not actuator_index:
        return
    for aid, cmd in (final_cmds or {}).items():
        # ⚠ **한 액추에이터의 기록 실패가 사이클을 멈춰서는 안 된다.**
        # 이 호출은 `_dispatch` **앞**에 있으므로, 여기서 예외가 나면 이미
        # 계산된 명령이 통째로 전송되지 않는다. 실제로 그렇게 됐다
        # (2026-08-30, 문자열 근거 'humid_max' → ValueError → 하드 임계가
        # 걸린 그 사이클의 명령이 미실행). `_safe_write` 는 **쓰기**만
        # 감싸므로 값을 만드는 이 구간도 함께 감싼다.
        try:
            idx = actuator_index.get(aid)
            if idx is None:
                continue
            if isinstance(cmd, dict):
                value = cmd.get('value', 0.0)
                reason = cmd.get('reason', REASON_IDLE)
            else:
                value = getattr(cmd, 'value', 0.0)
                reason = getattr(cmd, 'reason', REASON_IDLE)
            try:
                value = float(value or 0.0)
            except (TypeError, ValueError):
                continue        # 값이 숫자가 아니면 남길 것이 없다
            short = aid[:8]
            _safe_write(unique_id, 'coord_actuator_%s_final' % short,
                        value, ch_coord_final(idx))
            _safe_write(unique_id, 'coord_actuator_%s_final_reason' % short,
                        reason_code(reason), ch_coord_final_reason(idx))
        except Exception as exc:   # noqa: BLE001 — 제어를 막지 않는 것이 우선
            logger.warning(
                '최종 명령 기록 실패 — 제어는 계속한다 (%s): %s', aid, exc)


# ─────────────────────────────────────────────────────────────────────────────
# 센서 상태 기록 — 축별 상태와 VPD 출처
# ─────────────────────────────────────────────────────────────────────────────

def ch_sensor_status(axis: str) -> int:
    """축 이름 → 채널 번호. 모르는 축이면 ValueError (조용히 다른 번호로 가지 않게)."""
    return CH_SENSOR_STATUS_BASE + SENSOR_STATUS_AXES.index(axis)


def write_sensor_status(unique_id: str, snapshot: Optional[Dict],
                        facility_id: Optional[str] = None):
    """사이클의 센서 상태·VPD 출처를 기록한다. **실패해도 제어를 막지 않는다.**

    snapshot: `{'axes': {축: {'status': …}}, 'vpd_source': 'computed'|'device'|'none',
               'vpd_device_diff': float|None}`. 축이 빠져 있으면 missing 으로 적는다 —
    "기록 없음" 과 "센서 없음" 을 가르려면 늘 열 개 축이 다 있어야 한다.
    `write_cycle_metrics` 와 같은 조건(디버그 로깅)에서 호출된다.
    """
    if not unique_id or not snapshot:
        return
    from aot.utils import sensor_status as _ss
    extra = {'facility_id': facility_id} if facility_id else None
    try:
        axes = snapshot.get('axes') or {}
        for axis in SENSOR_STATUS_AXES:
            _safe_write(unique_id, MEAS_SENSOR_STATUS,
                        float(_ss.encode(axes.get(axis))),
                        ch_sensor_status(axis), extra)
        _safe_write(unique_id, MEAS_SENSOR_STATUS,
                    float(_ss.encode_vpd_source(snapshot.get('vpd_source'))),
                    CH_VPD_SOURCE, extra)
        diff = snapshot.get('vpd_device_diff')
        if diff is not None:
            _safe_write(unique_id, MEAS_SENSOR_STATUS, float(diff),
                        CH_VPD_DEVICE_DIFF, extra)
    except Exception as exc:   # noqa: BLE001 — 로그 한 줄이 제어를 멈춰선 안 된다
        logger.warning('센서 상태 기록 실패 — 제어는 계속한다: %s', exc)
