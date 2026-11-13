# coding=utf-8
"""
env_control/coordinator.py — Layer 3 actuator coordination algorithm (C2~C5).

Implements the design §4 pseudocode:
  - C2: live_effect evaluation engine
  - C3: coordination algorithm (position-form PI, slew, deadband-hold, anti-windup)
  - C4: side-effect conflict detection
  - C5: decision logging (caller passes unique_id)

Control law (P6 재설계 — position-form PI):
  기존 deadbeat 법칙(cmd = residual/unit_mag×100)은 작은 편차도 100% 로 포화시켜
  창호가 0↔100 릴레이 진동을 일으켰다. 이를 다음으로 교체한다.

    drive   = -residual × effect_sign        # 액추에이터 자기 프레임의 부호 있는 오차
                                             #  ( + = 더 열어야 함, - = 닫아야 함 )
    e_norm  = drive / pband                   # 비례 밴드(=PBAND_MULT×tolerance)로 정규화
    e_eff   = sign(e_norm)·max(0,|e_norm|-hb) # 데드존(hb=HOLD_FRAC/PBAND_MULT)을 '뺀' 유효오차
    I       = clamp(I + ki·e_eff, 0, 100)     # 적분 = '평형 개도(%)' 기억, 항상 [0,100]
    cmd     = clamp(kp·e_eff·100 + I, 0,100)  # P(전이) + I(평형 유지)

  성질:
    - 평형/밴드 내 → e_eff=0 → P=0, I 유지 → 직전 개도 hold (진동 제거)
    - 오버슈트(너무 차가움 등) → drive<0 → I 감소 → 점진적 폐쇄
    - "올림" 방향도 effect_sign 으로 대칭 처리 (기존 부호 버그 제거)
    - I 는 [0,100] 하드클램프 + back-calculation anti-windup (무한 와인드업 제거)

  레일 고착 회복 (2026-08-20):
    back-calculation 은 포화 **직후** 한 사이클에만 맡기고, 레일에 계속 눌러붙어
    있으면 적분을 실제 개도 쪽으로 기하 감쇠시킨다. 이유는 back-calc 의 부호에
    있다 — 아래쪽 레일(u<0)에서는 `I -= (u−c)·β` 가 I 를 **위로** 밀고, 요구값
    −P 가 100 을 넘으면 상한에 눌러붙어 그대로 굳는다. 그렇게 굳은 I 는 '기억된
    평형 개도'가 아니라 포화 부산물인데, 편차가 풀리는 순간 `cmd = P + I` 의
    I 가 통째로 계단으로 튀어나온다.
    위쪽 레일에서는 대칭으로 반대 사고가 난다 — dispatch 는 며칠째 100% 인데
    I 만 조용히 0 근처로 깎여, 무구배로 전환되는 순간 명령이 급락한다
    (2026-07-29 aot-005 폭염 중 보온커튼 오폐쇄). 회복 경로는 이 괴리 자체를
    없앤다: 레일에 눌러붙어 있는 동안 I 는 그 레일 값으로 수렴한다.
    편차가 반대로 서면 `cmd = P + I ≈ P` 라 **편차에 비례해서** 되돌아온다.

  아래쪽 레일 갓 포화 = 적분 동결 (2026-09-19):
    아래쪽 레일의 갓 포화는 back-calculation 대신 조건부 적분(이번 사이클 누적과
    슬루 되먹임을 버림)이다. 하드 온도 상한 항이 P 를 크게 음으로 만들자 닫히는
    개구부의 적분이 한 사이클에 0→100 으로 튀었다(섀도 실행). 위쪽 레일은 종전대로.

  데드존을 '빼는' 이유 (2026-08-06 aot-005 야간 창호 진동):
    이전 구현은 |e_norm|<hb 이면 cmd=I, 아니면 cmd=I+kp·e_norm·100 으로 **분기**했다.
    경계에서 P항이 0 에서 kp·hb·100(=8.33%p, 부호 반전 시 16.7%p)으로 **계단 점프**해,
    입력이 경계를 넘나들기만 하면 평형 상태에서도 명령이 그만큼 튄다. 그런데 경계를
    넘나들게 하는 데는 실제 외란이 필요 없다 — 습도 센서 1% 눈금(≈0.028kPa)이
    데드존 반폭(tolerance×HOLD_FRAC=0.05kPa)의 절반을 넘으므로 센서 최소 눈금
    하나로 충분하다. 실측: 새벽 VPD 편차 0.00~0.05kPa(허용오차 이내)인데 천창 명령이
    ±8/±16%p 로 계속 튀어 6시간 동안 12회 움직였다.
    데드존을 빼면 경계에서 P항이 0 으로 **연속** 수렴해 이 계단이 사라진다. 밴드 밖
    기울기(kp·100)는 그대로이고, 완전동작 도달점만 e_norm=1 → 1+hb 로 밀린다.

  integral 키 규약 변경: 변수별(native) → 액추에이터별(개도 %). 과거 var-키/범위
  밖 값은 coordinate() 진입 시 자동 폐기(마이그레이션)된다.

Unit convention R1:
  All deviation, accumulated, residual, magnitude are in native units.
  Normalization is used only for priority sorting and proportional-band scaling.

Reference: docs/dev/integrated_env_control_design.md §4
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .log_channels import (
    write_decision_log,
    ch_coord_cmd, ch_coord_reason, ch_integral,
    REASON_IDLE, REASON_PRIMARY, REASON_SECONDARY,
    REASON_WRONG_DIRECTION, REASON_SIDE_EFFECT, REASON_MANUAL_OVERRIDE,
    REASON_NO_GRADIENT, REASON_NO_OUTDOOR_DATA, REASON_OPPOSING_PARKED,
    REASON_DEADZONE_BACKOFF, REASON_NIGHT_PARKED, REASON_NO_MEASUREMENT,
    REASON_CURTAIN_DAY_OPEN, REASON_DIRECTION_UNSETTLED,
    REASON_HUMID_NO_RELIEF, REASON_HUMID_CAPPED, REASON_NO_RESPONSE,
    REASON_HUMID_COLD, REASON_HEAT_VENT_HOT_OUTSIDE, REASON_HEAT_FOG_BLOCKED,
    REASON_NO_WATER, REASON_ACTUATOR_SUSPECT, REASON_PREPARK_HOLD,
    REASON_SOLAR_VENT_FLOOR, REASON_RAIN_RESTRICT, REASON_MORNING_PURGE,
    REASON_OUTAGE_CLOSE, REASON_BLIND_SUN_VENT,
)
from . import humid_regime as HR
from .outage_clock import OUTAGE_DEHUMID_GRACE_S
from . import solar_vent as SV
from aot.utils import psychro
from . import screen_policy as SP
from .authority import is_natural_var
from .effect_functions import fan_ach_total
from .types import (
    ACTUATOR_DOMAIN, DEFAULT_DOMAIN, VENTILATING_KINDS,
    ActuatorProfile, SituationReport, domain_of,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Control-law tuning constants (profile.gains 로 액추에이터별 오버라이드 가능)
# ─────────────────────────────────────────────────────────────────────────────
# @manual ai/env-control#l3-coordinator-actuator-command
PBAND_MULT = 6.0     # 비례 밴드 폭 = PBAND_MULT × tolerance (native). 편차가 이만큼이면 P=100%.
                     # 6 = 허용오차의 6배 편차에서 완전동작 → 작은 편차엔 부드럽게 반응
                     # (작게 할수록 민감/급격, 크게 할수록 완만). 평형개도는 적분이 찾음.
POS_KP     = 1.0     # 비례 이득 (e_norm → 명령 %)
POS_KI     = 0.2     # 적분 이득 (사이클당 e_norm 만큼 평형 개도 누적)
HOLD_FRAC  = 0.5     # 데드존 반폭 = tolerance×HOLD_FRAC. 이 안에서는 P·I 모두 0 이라
                     # 직전 평형 개도를 유지한다. 데드존은 '분기'가 아니라 유효오차에서
                     # '빼는' 방식이라 경계에서 P항이 연속이다(모듈 docstring 참조).
# 데드존 안에서 잔여 편차의 부호가 **반대쪽**으로 넘어간 채 몇 사이클 이어지면
# 그 장치는 물러난다(REASON_DEADZONE_BACKOFF). 단위가 초가 아니라 **사이클**인
# 이유는 여기서 거르려는 것이 시간이 아니라 **잡음**이기 때문이다 — 잡음은
# 사이클마다 부호가 뒤집히므로 표본 수로 세는 것이 맞다. 데드존이 존재하는 이유가
# 그 잡음이고, 한 사이클의 부호로 물러나면 데드존을 만든 이유가 사라진다.
# 3 = 잡음으로 세 번 연속 같은 쪽이 나올 확률이 낮으면서, 편차가 허용오차 안이라
#     그동안의 손해가 제한적인 지점.
DEADZONE_BACKOFF_CYCLES = 3
# 미는 방향이 뒤집히면 새 방향이 이만큼 **이어져야** 따른다 — 사이클 수와 시간을
# 둘 다 채워야 한다(60초 주기면 10사이클, 600초 주기면 2사이클). 그 전에는 제자리.
# 창의 VPD 효과는 식힘(↓)과 건조한 외기(↑)가 겨룬 합이라, 둘이 비슷하면 실외 습도
# 몇 %p 로 부호가 사이클마다 바뀐다 — 실측(2026-09-24 영양, 실외 RH 44↔53 %):
# 천창이 10분마다 열림·닫힘을 번갈아 6시간 24회 반전했다. 효과 **크기**는 그때도
# 0.12~0.27 kPa 로 작지 않아 유효도 하한(G_MIN_EFFECT)으로는 걸러지지 않는다.
DRIVE_FLIP_MIN_CYCLES = 2
DRIVE_FLIP_MIN_SEC = 600.0

RELAX_FACTOR = 0.6   # 평형 개도 기하 감쇠 비율. **세** 자리가 쓴다 —
                     #  (a) 무구배·파킹: safe_default 로 수렴
                     #  (b) 레일 고착 회복: 실제 개도(0 또는 100)로 수렴
                     #  (c) 데드존 역부호 물러남: safe_default 로 수렴 (a 와 같다)
                     # 100 → 1 미만까지 약 11 사이클.
AW_BETA    = 0.5     # back-calculation anti-windup 강도 (포화 **직후** 한정)
RAIL_EPS   = 0.5     # 직전 개도가 레일에 있다고 볼 허용오차 [%]
# @manual-end

# ── 실외를 모르는 동안 **닫는 쪽은 허용** (2026-10-12 김제, 근거 58) ─────────────────────
# 2.6 의 제자리는 "근거 없이 열지 말라" 인데 닫는 방향까지 얼렸다. 김제 10/10 22:30 밤새 제습으로 열린 창
# 25 %가 기상청 값이 끊긴 01:30 이후 3 시간 13~25 % 로 묶였고(근거 16), 폐루프 sensor_storm_outage 에서는
# 해 질 녘 5 %로 열린 창이 비 70 분을 맞았다. 열 근거가 없다는 것이 닫을 수 없다는 뜻은 아니다 — 규칙 A
# (오래된 '비 안 옴' 은 여는 근거가 못 된다)의 짝으로, 실외 모름은 **여는 쪽만** 막는다.
#   · 야간 파킹(19)·마지막 실측 비·강풍의 상한(52·55)은 모른다는 이유로 끄지 않는다.
#   · 해가 진 뒤(맑은 하늘 일사 < OUTAGE_NIGHT_SOLAR_W) 조금(≤ OUTAGE_CLOSE_MAX_PCT) 열린 개구부는 0 으로 닫는다 —
#     실외 값이 없을 때(2.6)뿐 아니라 강우·풍속을 잃어 '더 열지 않음'(2.7)일 때도(PI 가 열자고 하면 제자리에 서던 창).
#   · 낮에 크게 열린 창은 그대로다 — 실외를 모른다는 이유만으로 닫으면 더위가 온다.
OUTAGE_NIGHT_SOLAR_W = 50.0     # 이 아래면 해가 졌다(맑은 하늘 기준 — 구름이 있어도 해가 있으면 이보다 크다)
OUTAGE_CLOSE_MAX_PCT = 10.0     # 이 이하로 열린 창만 한 번에 0 으로 닫는다

# ── 두절이 30 분 넘게 이어지면 **제습으로 열린 창**도 단계로 닫는다 (2026-10-12 김제, 근거 58) ──────────────────────
# 위 '10 % 이하만 0 으로' 는 하드 습도 상한(`_force_dehumid`)이 환기를 원하는 동안 건너뛰었다(PR #161 의 결정). 그 결과
# 김제 10/10 22:30 에 RH 91~95 % 로 25~30 % 열린 창이 기상청 값이 끊긴 01:30 이후 3 시간 13~25 % 로 묶였다 — 비가 오기
# 시작해도 볼 수 없는 채로. 끊김이 `OUTAGE_DEHUMID_GRACE_S`(`outage_clock`) 를 넘기면 밤에 이 습도 때문에 열린 창
# (하드 습도 상한 · 야간 파킹을 푸는 습도/결로 탈출)을 **사이클당 `OUTAGE_DEHUMID_STEP_PCT` %p 씩** 0 까지 내린다.
#   · 30 분 안의 끊김은 종전대로다 — 기상대 관측은 간헐적으로 그만큼 벌어지고, 그때마다 제습을 흔들 일이 아니다.
#   · 계단은 -5 %p 의 일정 폭이다. ×0.5 는 30 % 창을 한 번에 15 %p 내려(5 %p 의 세 배) 갑작스럽고 끝이 0 에 닿지도
#     않는다(30→15→7.5→3.8…). 일정 폭은 큰 창에서 더 부드럽고(일사 하한을 푸는 폭 `SV_FLOOR_RELEASE_STEP_PCT` 와 같은 5 %p),
#     0 에 정확히 닿는다. 폭은 사이클 길이에 비례해(600 s 기준, 더 길어도 5 %p 가 상한) 짧은 주기에서 시간당 속도가 같다.
#   · 온도 비상(`_force_cool` · 극한 고온 보호)은 건드리지 않는다 — 더위는 비보다 빠르다. 낮의 큰 열림도 그대로다(해가 지지
#     않았고 습도 때문에 연 것도 아니다).
#   · 실외 값이 돌아오면(두절 시계 0) 다음 사이클부터 보통의 제어다. 래치는 없다.
OUTAGE_DEHUMID_STEP_PCT = 5.0       # 사이클당(600 s 기준) 내리는 폭 [%p]
OUTAGE_DEHUMID_REF_CYCLE_S = 600.0  # 이 길이의 사이클에서 위 폭을 쓴다(짧은 주기는 비례해 줄인다)

# ─────────────────────────────────────────────────────────────────────────────
# 액추에이터 도메인 — 부하분담이 미치는 범위 (2026-08-26)
# ─────────────────────────────────────────────────────────────────────────────
# 부하분담(accumulated)은 "앞이 이미 한 만큼 뒤가 적게 한다" 인데, 이는 둘이
# **같은 일의 대체재**일 때만 뜻이 있다. 대체재가 아닌 것끼리 나누면, 한쪽이
# 낸 잘못된 주장이 다른 쪽을 **거꾸로 켠다**.
#
# 실사고(2026-08-25 イチゴ): 측창 하나의 적분이 폭주해 88.7% 를 확정했고 그
# 물리 기여가 accumulated['vpd']=+1.2556 — 원래 편차(−0.2215)의 5.7배였다.
# 뒤에 처리된 분무기·냉방기는 "이미 크게 과했다" 고 읽어 반대 방향으로 켜졌다:
# 습도 92% 인데 가습이, 목표보다 시원한데 냉방이 올라갔다. 실제 온실에서
# 측창 모터가 고장 나도 같은 경로로 재현되고, 실패 방향이 최악이다 — 하나가
# 고장 나면 나머지가 그 몫까지 떠안아야 하는데 정확히 반대로 나머지를 끈다.
#
# 그래서 누적은 **도메인 안에서만** 흐른다. 표의 정본은 `types.ACTUATOR_DOMAIN`
# 이다 — effect_functions 의 도달 한계 클램프가 같은 표를 본다.
#
# ⚠ **도메인을 넘는 조율은 명시적 인터록이 맡는다** — `hvac_interlock`(냉난방
# 가동 중 개구부 잠금)·`vent_futility_gate` 가 이미 그 자리에 있다. 인터록은
# 선언돼 있어 감사 가능하고 안전한 쪽으로 실패하지만, 효과 누적은 암묵적이라
# **조용히** 실패한다. 이번 사고가 정확히 그것이었다.
# **여기에 "에너지 절약" 을 이유로 도메인 간 누적을 되살리지 말 것.** 그것을
# 원하면 인터록으로 선언할 것 — 그래야 왜 그렇게 됐는지 답할 수 있다.


# ── 환기 무익 게이트 (사용자 옵션 vent_futility_gate) ─────────────────────────
# 외기와 공기를 바꾸는 장치는 실내 상태를 **실외 상태 쪽으로**밖에 못 민다.
# 목표가 실외의 반대쪽에 있으면 아무리 열어도 목표에 가까워질 수 없다 — 야간
# 제습이 대표적이다(실외 노점이 실내보다 높으면 창을 열수록 더 습해진다).
# G_MIN_EFFECT 는 '구동력 크기'만 보므로 이 경우를 못 걸러낸다: 면적이 큰 천창은
# 방향이 반대라도 magnitude 가 커서 항상 문턱을 통과한다. 실측(2026-08-06 aot-005)
# 에서 밤새 근거코드가 전부 PRIMARY 였고 창이 40~70% 열린 채 유지됐다.
#
# 어휘를 둘로 두지 않는다 — types 의 도메인 명부에서 파생한 것을 재수출한다.
# (기존 import 경로를 유지하려고 여기 이름을 남긴다)

# 판정 문턱 — 잡음으로 게이트가 깜빡이지 않게 한다.
#   need  : |목표-측정| 이 tolerance×VENT_NEED_FRAC 미만이면 '중립'(찬반 근거 아님)
#   avail : |실외-측정| 이 tolerance 미만이면 환기로 의미 있게 못 옮긴다고 본다
# @manual ai/env-control#settings-ventilation
VENT_NEED_FRAC = HOLD_FRAC   # 데드존과 같은 기준 — 제어가 쉬는 구간은 판정도 쉰다

# ── 환기 우선 (사용자 옵션 vent_first) ────────────────────────────────────────
# `hvac_interlock`(냉난방 가동 중 창 잠금)의 짝이다. 실외가 목표 **너머**에
# 있으면 환기만으로 목표에 닿을 수 있고, 그때 냉난방을 함께 돌리는 것은 바깥
# 공기가 공짜로 할 일을 돈 주고 하는 것이다.
#
# 실측(2026-08-26 イチゴ): 실내 VPD 0.253 · 목표 0.579 · 실외 0.895 에서 창을
# 다 열면 한 사이클에 0.588 kPa 를 옮길 수 있는데, 난방기가 80% 로 올라가고
# 있었다. 도메인 분리 이후 난방기는 창이 하는 일을 모르기 때문이다 —
# 도메인 간 조율은 암묵적 누적이 아니라 **이렇게 선언된 인터록**이 맡는다.
#
# 파킹 조건 셋을 모두 만족해야 한다(하나라도 어긋나면 냉난방을 그대로 둔다):
#   ① 실외가 목표를 **여유(tolerance×VENT_REACH_MARGIN)만큼 지나** 있다.
#      딱 걸치면 환기는 목표에 점근할 뿐 닿지 못하고 경계에서 깜빡인다.
#   ② 제어 대상 변수가 **전부** 그렇다. 하나라도 환기로 못 가면 냉난방이 필요하다.
#   ③ 환기에 **여력이 남아 있다**. 창이 이미 만개인데 편차가 남으면 그때는
#      냉난방이 도와야 한다 — 여기서 파킹하면 아무도 일하지 않는다.
#   ④ 파킹한 지 얼마 안 됐다. 아래 '실패하면 넘긴다' 참조.
VENT_REACH_MARGIN  = 1.0     # 실외가 목표를 넘어서야 할 여유 (tolerance 배수)

# ⚠ **평균이 아니라 최댓값이다.** 평균을 쓰면 안 열리는 창 하나가 escalation 을
#   통째로 막는다 — 개구부 셋 중 하나가 0% 에 고착되면 나머지 둘이 만개해도
#   평균은 67% 라 90% 에 영영 못 닿고, 냉난방은 어떤 경우에도 안 켜진다
#   (2026-08-26 実測: 側面窓 9%/33% · 天窓 0% 인 채로 난방기가 계속 파킹됐다).
#   한 창이라도 만개면 그 창은 더 밀 데가 없다 — 그것이 '여력 없음' 의 뜻이다.
VENT_HEADROOM_PCT  = 90.0    # 직전 **최대** 개도가 이보다 낮아야 '여력 있음'

# ── 실패하면 넘긴다 ──────────────────────────────────────────────────────────
# ③ 만으로는 부족하다. "여력이 있나" 는 물어도 "실제로 되고 있나" 는 안 묻기
# 때문에, 창이 조금 열린 채 목표에 안 닿아도 냉난방은 무한정 파킹된다.
# 예측(실외가 목표 너머)이 맞다면 편차는 줄어들어 판정이 스스로 꺼진다 —
# 그러지 않고 계속 벗어나 있다는 것은 **예측이 틀렸다**는 뜻이고, 그때는
# 냉난방에 넘긴다.
#
# 값은 strain 판정(`_STRAIN_MIN_SEC`)과 같은 15분이다. 둘 다 "한두 사이클의
# 흔들림과 가른다" 는 같은 이유이고, 다르게 두면 화면이 "못 따라가고 있다"고
# 말하는 동안에도 냉난방은 파킹돼 있는 구간이 생긴다.
VENT_FIRST_PATIENCE_S = 900.0
# @manual-end

# @manual ai/env-control#l3-coordinator-actuator-command
G_MIN_EFFECT = 0.025 # 유효도(g=magnitude/pband) 하한. 100% 가동해도 변수를 비례밴드의
                     # 2.5%/cycle 미만으로밖에 못 움직이면(예: 환기인데 내외차 거의 없음)
                     # 권한 없음으로 보고 idle — 헛돌며 적분 와인드업 하는 것 방지.
                     # 측정상 무구배 g≈0.008~0.011, 약구배(ΔT≥1°C) g≳0.05 로 명확히 분리.

# 유효도 문턱의 **이력(히스테리시스)**. 한 번 '구동력 있음' 으로 판정한 장치는
# g 가 G_MIN_EFFECT 아래로 내려가도 이 비율 아래로 가기 전에는 그 판정을 유지한다.
#
# 문턱 하나로 가르면 g 가 문턱 근처에서 오르내릴 때 판정이 사이클마다 뒤집힌다.
# 뒤집힐 때마다 무구배 경로가 명령과 적분을 RELAX_FACTOR 로 깎고, 다음 사이클에
# PI 가 그 깎인 자리에서 다시 출발한다 — 톱니가 된다.
#
# 실측(2026-09-30 로컬 3포장, 갱신 60초): 측창이 100→0→70→0 % 를 20~30분
# 주기로 오갔다. 내외 VPD 차 0.2 kPa · 풍속 0.7~1.4 m/s 에서 g 가 0.018~0.034 로
# 문턱(0.025) 양쪽에 걸려 있었고, 실제 판정 로그(근거 1↔15)와 분 단위로 겹쳤다.
# 진짜 무구배는 g≈0.008~0.011 이라 이 이력 폭(문턱의 절반 = 0.0125) 아래이므로
# 그대로 걸러진다. 반대 방향 진입 문턱은 종전과 같다(G_MIN_EFFECT).
GRADIENT_EXIT_FRAC = 0.5

# ── 열어도 편차가 줄지 않는 창 — 더 열지 않는다 (2026-10-01) ────────────────────
# 효과가 작은 창(유효도 g 가 낮다)이 오래 열려 있는데 편차가 좁혀지지 않으면, PI 는
# "더 열어라" 를 계속 내고 적분만 쌓여 창이 천천히 100 % 로 올라간다. 실측(로컬
# 쿠마모토 천창, 실내 습도 93 %): 2시간 동안 8 → 21 %. 열어도 실내가 안 변하는
# 동안의 적분은 **배운 것이 아니라 실행되지 않은 요구**다.
#
# ⚠ **유효도가 낮을 때만 건다**(`STALL_G_MAX`). 효과가 큰 창은 편차가 안 줄어도
#   (한낮에 해가 더 세지는 경우) 더 열어야 하는 것이 맞다 — 그때는 "열어도 소용없다"
#   가 아니라 "아직 모자라다" 다. 약구배(g≳0.05) 아래만 "열어도 소용없다" 로 본다.
# ⚠ 풀리는 조건은 편차가 `STALL_IMPROVE_FRAC` 이상 좁혀지거나 열림이 문턱 아래로
#   내려가는 것이다. 벌어진 편차는 풀지 않는다 — 더 열어도 소용이 없다는 뜻이다.
STALL_AFTER_S = 2700.0        # 45분 — 한두 사이클의 흔들림과 가른다
STALL_IMPROVE_FRAC = 0.10     # 기준 편차보다 이만큼 좁혀지면 "반응이 있다"
STALL_MIN_OPEN_PCT = 10.0     # 이 이상 열려 있어야 "열었다" 로 센다
STALL_G_MAX = 0.06            # 이 유효도 미만의 창에만 건다

# ── 의심 액추에이터: 세게, 오래, 반응 없음 (2026-10-09) ───────────────────────────────
# 위 '열어도 편차가 줄지 않는 창' 의 짝이다. 같은 판정(`_no_improvement_step` — 기준 편차보다
# STALL_IMPROVE_FRAC 이상 좁혀지면 "반응이 있다")을 **반대 대역**에 적용한다: STALL 은 효과가 작은
# 창(g < STALL_G_MAX)이 "열어도 소용없다" 는 것이고, 여기는 모델이 **효과가 뚜렷하다**고 말하는
# 창(g ≥ STALL_G_MAX)이 세게 열려 있는데도 반응이 없다는 것이다. 탐지기를 하나 더 만들지 않았다.
#
# ⚠ **편차를 공유하는 장치들의 개별 고장은 편차만으로는 안 보인다** — 한 창이 죽어도 나머지가
# 편차를 줄이면 죽은 창의 편차도 같이 줄어 '반응 있음' 이 된다. 그래서 이 판정은 거짓 제외를
# 만들지 않는 쪽으로만 선다(조건을 전부 만족해야 한다):
#   ① 환기 장치(VENTILATING_KINDS)이고 세게 — 직전 명령 NOFX_MIN_CMD_PCT 이상(`prev_val`)
#   ② 효과가 뚜렷 — g ≥ STALL_G_MAX (모델이 '측정될 만큼 크다' 고 하는 구간)
#   ③ 실외를 안다 — 지어낸 실외(`_ext_synthetic`)가 아니고 '더 열지 않음' 이 걸리지 않았다
#      (실외를 모르면 환기의 효과 방향부터 모른다)
#   ④ 오래 — NOFX_AFTER_S 동안 끊김 없이(명령이 문턱 아래로 한 번 내려오면 처음부터)
#   ⑤ 혼자 한 일이다 — 이 도메인의 '명령된 효과'(g × 명령) 중 이 장치 몫이 NOFX_SOLE_SHARE 이상.
#      여러 창이 함께 세게 열렸는데 편차가 안 줄면 **공통 원인**(열린 루프 센서·센서 고장·용량
#      부족)이지 창 하나의 고장이 아니다 — 김제·영양처럼 실내 센서가 명령에 반응하지 않는
#      시설에서 창이 전부 제외되는 것을 막는 것이 이 조건이다.
#   ⑥ 제외하고도 환기 장치가 하나 이상 남는다 — 아무도 일 못 하게 만들지 않는다.
# 그래도 센서가 열린 루프인 시설에서 창이 하나만 세게 열려 있으면 서 버릴 수 있어, 도메인당 한 번에
# 하나만 제외하고 다음 제외까지 쉬는 시간을 둔다(`actuator_feedback.NOFX_DOMAIN_COOLDOWN_S`).
NOFX_AFTER_S = 7200.0         # 2시간 — STALL 의 45분보다 훨씬 길다(제외는 되돌리기 어렵다)
NOFX_MIN_CMD_PCT = 80.0       # 직전 명령이 이 이상일 때만 '세게'
NOFX_SOLE_SHARE = 0.8         # 도메인 명령 효과 중 이 장치 몫이 이 이상일 때만 '혼자 한 일'


def _no_improvement_step(ref, elapsed_s, e_norm, cycle_sec):
    """'편차가 좁혀지지 않은 시간' 한 걸음 → (기준 편차, 누적 초).

    기준보다 STALL_IMPROVE_FRAC 이상 좁혀졌거나 기준이 없으면 다시 센다. 약한 창의 '열어도 소용없음'
    (STALL_AFTER_S)과 센 창의 '반응 없음'(NOFX_AFTER_S)이 **같은 판정**을 쓰도록 한 곳에 둔다.
    """
    if ref is None or e_norm < ref * (1.0 - STALL_IMPROVE_FRAC):
        return e_norm, 0.0
    return ref, float(elapsed_s) + float(cycle_sec)

# ── 환기를 움직이는 최소 VPD 차이 (2026-10-01) ─────────────────────────────────
# 무익 판정의 "실외가 실내보다 이만큼은 달라야 한다" 를 허용오차(기본 0.1 kPa)만으로
# 잡으면 0.15 kPa 차이에도 창이 열린다. 그 차이는 RH 1~2 %p 의 센서 잡음 안이다.
VENT_MIN_VPD_GAP = 0.25

# 환기 무익 판정의 **이력** (2026-10-08). 문턱 하나로 가르면 실외·실내 값이 문턱(0.25 kPa) 근처에서
# 조금만 흔들려도 판정이 사이클마다 뒤집힌다 — 환경은 매끄럽게 변하는데 창만 올라갔다 내려갔다
# 했다(로컬 3개 시설 24시간 반전 7~11회, 근거 1 ↔ 15 가 10~60분 간격). 15 가 될 때마다 명령이
# RELAX_FACTOR 로 깎여(80→60→40→24→15→9→6→0) 목표보다 2 °C 넘게 더운데도 닫혔다.
#   무익이 아니던 장치: 문턱의 이 비율 아래로 내려가야 무익이 된다
#   무익이던 장치     : 문턱 이상으로 회복돼야 무익에서 나온다
FUTILE_ENTER_FRAC = 0.6
# 열려 있는 창은 '무익' 이 이만큼(초) 이어져야 감쇠 파킹한다. 그 전에는 **제자리**다. 이력만으로는
# 입력이 실제로 문턱을 넘나드는 경우를 못 막고, 파킹은 한 번에 명령을 40 % 씩 깎는다 — 짧은
# 흔들림이 100 → 0 % 톱니가 된다. 닫혀 있던 창은 기다릴 이유가 없다(바로 파킹).
FUTILE_DWELL_S = 1200.0

# ── 온도 상한 (2026-09-14) ───────────────────────────────────────────────────
# VPD 를 직접 제어하면 `_decompose_vpd` 가 온도를 제어목표에서 뺀다. 그래서
# 온도가 유도 상한을 넘어도 **창을 여는 힘이 하나도 없었고**, 하드 상한
# (`temp_max`)을 넘어도 임계 오버라이드는 난방 끄기·차광막 닫기만 한다.
#
# 실측(2026-09-14 aot-005 육묘장): 08:10 20.8 °C → 10:00 33.7 °C, 유도 상한
# 27 · 하드 상한 32, 실외 19~24 °C. 천창·측창은 두 시간 내내 근거 '주작용'
# 으로 0 % 였고 사람이 강제로 열고서야 내려갔다. VPD 가 목표보다 낮아서
# (습도 97 %) "닫아 둔다" 가 VPD 쪽 판단이었다.
#
# 규칙 셋:
#   ① 선을 **넘을 것 같으면** 반응한다 — 지금 온도가 아니라 다음 결정 시점의
#      예상 온도(T + 상승률 × 제어주기)로 본다. 오늘 상승은 10분당 1.5~1.8 °C
#      였고 긴급 판정(10분당 2 °C)에는 한 번도 안 걸렸다.
#   ② 유도 상한 초과분에 비례해 온도 항을 **더한다**. 넘은 만큼 우선순위가
#      커지므로 VPD 와 맞서면 온도가 점점 이긴다. 환기(vent)에만 건다 —
#      공짜로 식힐 수 있는 수단이 먼저다.
#   ③ 하드 상한에 닿으면 온도가 **이긴다** — 식히는 방향과 맞서는 다른 변수의
#      항을 뺀다. 이때는 냉방(hvac)에도 건다.
# 강제 100 % 가 아니다. 여전히 편차에 비례하는 PI 이고, 실외가 더 더우면 온도
# 효과 방향이 ↑ 라 창은 **닫히는** 쪽으로 간다.
T_CEILING_TOL      = 1.0   # `_cycle_mixin` 의 T_tol 과 같다 — 비례 밴드 기준
T_CEILING_PRIORITY = 1.0   # 초과 0 에서의 우선순위. (1 + 초과/허용오차) 배로 커진다
# 한 번 켜진 온도 상한 항은 진입선보다 이만큼 더 내려가야 꺼진다(°C). 항이 켜지고
# 꺼지는 것은 창이 "PI 로 식힌다" 와 "환기 무익 — 파킹(60 %씩 닫기)" 사이를 오가는
# 것이다 — 실측(2026-09-24 영양 천창 리플레이): 실내 27.7~28.8 °C 가 진입선 28 °C 를
# 오르내리며 85 → 65(파킹) → 85 → 65 % 로 10분마다 오르내렸다. 다른 하드 임계
# 판정(0.5 °C)과 같은 폭이다.
T_CEILING_HYST = 0.5
# 항이 꺼지는 선 아래로 이만큼(°C)은 **유지 구간**이다 — 상한 항으로 열어 둔 창은 닫는
# 쪽으로 움직이지 않는다(더 열 수는 있다). 이 아래로 내려가야 종전처럼 물러난다.
#
# 왜: 창이 한 사이클(10분) 안에 실내를 2~4 °C 바꾸는 시설에서, 상한 항은 "선 위 → 연다,
# 선 아래 → 항이 꺼져 무구배 감쇠(×0.6/사이클)로 닫힌다" 를 오가는 이완 발진기였다
# (폐루프 2026-10-09, 김제 측창 56 m² × 2: 0 → 20 → 12 → 7 → 0 → 20 %, 주기 약 50 분).
# 유지 구간이 있으면 평형 개도에서 멈춘다 — 열고·멈추고·닫는 3위치 조절기다. 1.5 °C 는
# 한 번 열었을 때 실내가 선 아래로 내려가는 폭(김제 시뮬레이터 1.5~3 °C)과 극한 고온
# 보호의 해제 여유(기본 1.5 °C)에 맞춘 값이다.
T_CEILING_HOLD_BAND = 1.5
_T_CEILING_DOMAINS      = frozenset({'vent'})
_T_CEILING_HARD_DOMAINS = frozenset({'vent', 'hvac'})
# @manual-end


# @manual ai/env-control#l3-coordinator-actuator-command
def _temperature_ceiling(situation: SituationReport, ctx: Dict,
                         cycle_sec: float) -> Optional[Tuple[float, bool]]:
    """(유도 상한 초과분 °C, 하드 상한 도달) — 걸린 것이 없으면 None.

    온도가 이미 제어목표(deviation)에 있으면 None 이다. 그때는 온도가 자기
    목표로 스스로 끌리므로 여기서 한 번 더 더하면 이중계상이다 — **극한 고온 보호
    중만 빼고**(아래).

    부수 효과: `ctx['_t_ceiling_hp_only']` — 하드가 보호(단계 1) 때문만인가.
    """
    ctx['_t_ceiling_hp_only'] = False
    _hp = ctx.get('heat_protect')
    _hp_on = bool(getattr(_hp, 'active', False))
    if 'temperature' in (situation.deviation_native or {}) and not _hp_on:
        # ⚠ 보호 중에는 온도가 제어목표여도 보호의 선을 건다(2026-10-09 폐루프). 온·습도
        #   직접 제어 — 온도 우선 기준이거나, VPD 기준인데 습도(따라서 VPD)를 잃은 폴백 —
        #   의 온도 목표는 단계 온도가 없으면 유도 범위로 클램프한 값(가이드 상한 32 °C)이라,
        #   보호 문턱 30 °C 는 우선순위(`situation` HP_T_PRIORITY)로만 닿고 **선**으로는
        #   아무 데도 닿지 않았다. 폐루프 sensor_indoor_oor(습도 130 % 보고 → 버림 → 온·습도
        #   폴백): 창이 온도 목표 32 °C 를 좇아 40~50 % 에 머물고 실내 36 °C(단계 2).
        #   이중계상은 보호 중에만, 식히는 쪽으로만 생긴다 — 보호가 원하는 방향이다.
        return None
    t_now = ctx.get('T_int')
    ceiling = ctx.get('T_ceiling')
    # 극한 고온 보호(`heat_protect`)가 **켜져 있으면** 선은 문턱을 넘지 않는다 — 보호 중이
    # 아니어도. 보호 중에는 그 선이 **하드**다(냉각과 맞서는 VPD·습도 항을 뺀다). 판정은
    # 그 모듈 한 곳이고 여기서는 결론만 읽는다.
    #
    # ⚠ 보호 밖에서도 문턱으로 좁히는 이유(2026-10-09 폐루프): 유도 상한(가이드 32 °C)이
    #   문턱(30 °C)보다 높으면 평소 PI 는 31 °C 부터 식히기 시작한다 — 실내가 문턱을 넘는
    #   것이 평소 제어의 **정상 운전점**이 되어, 래치(진입 → 20 분 유지 → 해제 → 닫힘 →
    #   다시 진입)가 조절기 노릇을 했다. humid_night 에서 36 시간에 10 번 진입(진입마다
    #   긴급 1회), 창 반전 0.68 → 0.92 /h. 평소 PI 가 문턱 아래(문턱 − 허용오차)부터
    #   부드러운 상한 항으로 식히면 보호는 평소 제어가 못 막을 때만 서는 뒷받침이 된다.
    if _hp is not None and (_hp_on or getattr(_hp, 'enabled', False)):
        ceiling = (min(float(ceiling), float(_hp.threshold)) if ceiling
                   else float(_hp.threshold))
    if t_now is None or not ceiling:
        return None
    # ⚠ 유도 상한은 **목표 온도 + 허용오차** 를 넘지 않는다 (2026-10-08). 가이드 상한(딸기 30 °C)만
    #   보면 목표 25 °C 보다 2~5 °C 더운 채로(실측: 27.5~30.4 °C) 온도 항이 꺼져 있어, 창이 VPD
    #   하나만 보고 파킹돼 닫혀 있었다 — "충분히 안 열린다". 목표 온도는 VPD 제어 중 제어목표에서
    #   강등돼 `_temperature_constraint` 로 남아 있다. 하드 상한(temp_max)은 그대로다.
    _tc = (getattr(situation, 'target', None) or {}).get('_temperature_constraint')
    if _tc is not None:
        ceiling = min(float(ceiling),
                      float(_tc.value) + float(getattr(_tc, 'tolerance', 0.0) or 0.0)
                      + T_CEILING_TOL)
    trend = max(0.0, float(ctx.get('T_trend') or 0.0))          # °C/min
    projected = float(t_now) + trend * float(cycle_sec) / 60.0
    # 선에 **닿기 전에** 반응한다 — 허용오차만큼 앞에서 시작한다. 선에서
    # 시작하면 유도 상한 = 하드 상한(하드 임계로 좁혀진 경우)일 때 막 넘은
    # 초과분이 데드존(허용오차 × HOLD_FRAC) 안이라 아무 일도 안 일어난다.
    start = float(ceiling) - T_CEILING_TOL
    if ctx.get('_t_ceiling_active_prev'):
        # 켜져 있던 항은 HYST 만큼 더 내려가야 꺼진다 — 그 구간의 초과분은 작아서
        # 무게도 작다(가중치 연속화, `coordinate`).
        start -= T_CEILING_HYST
    excess = max(0.0, projected - start)
    hard_max = ctx.get('temp_max')
    hard_limit = (bool((ctx.get('internal') or {}).get('_force_cool'))
                  or (bool(hard_max) and projected >= float(hard_max)))
    # ⚠ 보호 중이어도 **선 아래로 내려오면 항을 내린다**(초과 0 이면 None). 예전에는 보호
    #   중이면 초과 0 에서도 하드 항(오차 0 · 무게 최대)이 남았다. 그 항은 아무것도 밀지
    #   않으면서 (1) 무구배 → 완만한 감쇠(RELAX_FACTOR) 경로를 막고 (2) 맞서는 VPD 항만
    #   남겨 P 가 거의 전부인 PI 를 0 으로 떨어뜨렸다. 창이 한 사이클 만에 반응하는
    #   시설에서는 선 위(맞서는 항 뺌 → 연다)와 선 아래(맞서는 항 복귀 → 닫는다)를 10분마다
    #   오갔다 — 폐루프 normal: 보호 중 창 20 ↔ 0 %, 실내 26 ↔ 31 °C 를 매 사이클 반전.
    #   선 아래에서는 보호가 없을 때와 같은 경로로 물러난다. 하드 임계(`_force_cool`·
    #   temp_max)는 종전대로 초과 0 에서도 하드다.
    hard = (_hp_on and excess > 0.0) or hard_limit
    # 하드가 **보호 때문만**인가 — 그때 하드 항은 보호가 증발냉각기로 쓰는 분무기만 민다
    # (`heat_protect.cooling_foggers`: 습윤형은 평소 제어가 다룬다). 하드 임계는 종전대로 전부.
    ctx['_t_ceiling_hp_only'] = bool(hard and not hard_limit)
    if excess <= 0.0 and not hard:
        # 유지 구간(T_CEILING_HOLD_BAND) — 켜져 있던 항이 꺼지는 선 아래로 막 내려왔다.
        # (0.0, False) 는 "항은 서 있되 미는 힘 0" 이다: 상한으로 연 창은 제자리, 무익
        # 판정·과습 구간은 종전처럼 '상한이 서 있다' 로 본다.
        if (ctx.get('_t_ceiling_active_prev')
                and projected >= start - T_CEILING_HOLD_BAND):
            return 0.0, False
        return None
    return excess, hard


# ─────────────────────────────────────────────────────────────────────────────
# Coordination state (preserved across cycles)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CoordinatorState:
    """Returned as the result of each cycle, passed as prev to the next cycle.

    integral: 액추에이터별 평형 개도(%) 기억. 키 = actuator_id, 값 ∈ [0,100].
              (P6 이전엔 변수별 native 누적이었음 — 자동 마이그레이션됨)
    """
    prev_commands: Dict[str, float] = field(default_factory=dict)
    integral:      Dict[str, float] = field(default_factory=dict)
    active_vars:   Dict[str, bool]  = field(default_factory=dict)  # 텔레메트리/hysteresis
    # 직전 사이클의 구동 방향(+1 더 열기 / −1 닫기). 방향 전환 감지 전용.
    # **일부러 영속화하지 않는다** — 재시작 직후 한 사이클만 전환 감지를 쉬면
    # 되고(보수적), 그것 때문에 마이그레이션을 만들 값어치가 없다.
    drive_sign:    Dict[str, int]   = field(default_factory=dict)
    # 환기 우선이 냉난방을 파킹한 채 목표를 못 맞추고 있는 누적 시간(초).
    # 판정이 꺼지면(=편차가 사라졌거나 환기로 못 간다고 판단) 0 으로 되돌린다.
    # **영속화하지 않는다** — 재시작 직후 인내를 처음부터 세는 것은 보수적인
    # 쪽이고(냉난방을 늦게 켠다), 그 때문에 마이그레이션을 만들 값어치가 없다.
    vent_first_held_s: float = 0.0
    # 데드존 안에서 잔여 편차가 **반대쪽**으로 넘어간 연속 사이클 수.
    # 한 번이라도 되돌아오면 0 이다 — 잡음으로 한 사이클 뒤집힌 것과
    # 진짜로 넘어간 것을 가르는 유일한 수단이다.
    # `drive_sign` 과 같은 이유로 **영속화하지 않는다**(재시작 후 한 사이클만
    # 보수적으로 쉬면 된다).
    deadzone_wrong_side: Dict[str, int] = field(default_factory=dict)
    # 뒤집힌 구동 방향이 확정을 기다리는 중: {actuator_id: (새 부호, 지난 초, 사이클 수)}.
    # 한 번이라도 옛 방향으로 돌아오면 지운다. `drive_sign` 과 같은 이유로 영속화하지 않는다.
    drive_flip_pending: Dict[str, tuple] = field(default_factory=dict)
    # 직전 사이클에 온도 상한 항이 켜져 있었나(T_CEILING_HYST). `cycle_memory` 가 재시작을 넘긴다 — 잃으면
    # 첫 사이클만 '닫기' 쪽 힘이 작아져 열린다(김제 2026-10-12 22:14). 다른 이력과 달리 보수적이지 않다.
    t_ceiling_active: bool = False
    # 직전 사이클에 '환기 무익' 으로 판정된 장치(FUTILE_ENTER_FRAC 의 이력)와, 그 판정이 이어진
    # 시간(초, FUTILE_DWELL_S). 영속화하지 않는다.
    futile_active: set = field(default_factory=set)
    futile_s: Dict[str, float] = field(default_factory=dict)
    # 액추에이터가 직전 사이클에 '구동력 있음'(g 가 문턱 이상)이었나 — 유효도 문턱의
    # 이력(GRADIENT_EXIT_FRAC). 없는 항목은 False(=종전대로 G_MIN_EFFECT 로 진입).
    # 영속화하지 않는다 — 재시작 직후 한 사이클만 종전 규칙으로 돌면 된다.
    gradient_active: Dict[str, bool] = field(default_factory=dict)
    # 과습 구간에 있는가(humid_regime 의 진입/이탈 이력). `cycle_memory` 가 재시작을 넘긴다 — 잃으면 이탈 문턱
    # 전(VPD 0.30~0.40 · 여유 2~3 °C)이던 집이 '구간 밖' 으로 읽혀 실외가 더 습해도 닫지 않고 열림 상한도 풀린다.
    humid_zone: bool = False
    # 아침 습기 빼기(`humid_regime.morning_purge`)의 이력 — 켜짐·직전 실내 온도·평활한 변화율.
    # `cycle_memory` 가 재시작을 넘긴다(`humid_zone` 과 같다) — 잃으면 구간 안이어도 켬 문턱·'오르는 중인지 모름'
    # 으로 읽혀 5~15 % 하한이 한 사이클 사라진다.
    purge: Optional[HR.PurgeState] = None
    # 열어도 편차가 줄지 않은 누적 시간(초)과 그 기준 편차 — `STALL_AFTER_S` 주석.
    # 영속화하지 않는다: 재시작 후 45분을 다시 세면 되고, 그 사이는 종전 동작이다.
    stall_s: Dict[str, float] = field(default_factory=dict)
    stall_ref: Dict[str, float] = field(default_factory=dict)
    # 세게 열렸는데 편차가 안 줄어든 누적 시간(초)·기준 편차 — `NOFX_AFTER_S` 주석. 영속화하지 않는다.
    nofx_s: Dict[str, float] = field(default_factory=dict)
    nofx_ref: Dict[str, float] = field(default_factory=dict)
    # 이번 사이클에 '오래 세게 명령했는데 반응이 없다' 로 서는 장치 — **출력**이다(다음 사이클로 안
    # 넘긴다). 의심 판정(`actuator_feedback.record_no_effect`)이 읽는다. 영속화하지 않는다.
    noeffect_ids: set = field(default_factory=set)


# ─────────────────────────────────────────────────────────────────────────────
# Command result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ActuatorCommand:
    value: float                       # dispatch value (motor position %, after operating-range mapping)
    reason: int
    var_source: Optional[str] = None   # the variable that triggered this command
    aperture: Optional[float] = None   # control coordinate (aperture %, for slew/prev computation)
    slewed: Optional[float] = None     # 슬루까지만 적용한 개도 (min-ON 스냅 **전**).
                                       # 적분 되먹임이 "속도에 막힌 것"과 "너무 작아
                                       # 버린 것"을 갈라 보기 위한 값 — 섞으면 안 된다
                                       # (coordinate() 의 되먹임 주석 참조).

    def control_value(self) -> float:
        """Coordinate value for slew/prev_commands computation — aperture preferred, otherwise value."""
        return self.aperture if self.aperture is not None else self.value


CoordResult = Dict[str, ActuatorCommand]


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

# @manual ai/env-control#settings-ventilation
@dataclass
class ParkDecision:
    """한 사이클의 파킹·제자리 판정 — PI(`coordinate`)와 MPC(`_run_mpc`)가 함께 읽는다.

    두 엔진이 판정을 따로 하면 엔진을 바꿀 때 동작이 갈린다(MPC 보강 D 단계,
    2026-09-22). 그래서 판정은 여기 한 곳이고, PI 는 파킹된 장치를 safe_default 로
    감쇠시키고 MPC 는 그 채널의 상한으로 받는다.
    """
    park_ids: set                      # safe_default 로 보낼 장치(아래 사유의 합)
    night_parked: set                  # 야간 파킹(결로 탈출 포함 — `_night_vent_parked`)
    opposing_ids: set                  # 온도 축 요구의 반대편 냉·난방
    hold_ids: set                      # 실외를 모름 — 제자리(파킹에서 빠짐)
    ceiling_ids: set                   # 강우·풍속 모름 — 더 열지 않음
    vent_credit: Dict[str, float]      # 환기 우선 — 실외가 대신 해 주는 몫(PI 전용)
    t_ceiling: Optional[Tuple[float, bool]]
    vent_first_held_s: float           # 다음 사이클로 넘길 환기 우선 인내 시간
    futile_ids: set = field(default_factory=set)       # 환기 무익(감쇠 파킹 중)
    futile_raw: set = field(default_factory=set)       # 이번 사이클 무익 판정 전부(이력용)
    futile_s: Dict[str, float] = field(default_factory=dict)  # 무익이 이어진 시간(초)
    futile_dwell_ids: set = field(default_factory=set) # 무익이나 대기 중 — 제자리
    interlock_ids: set = field(default_factory=set)    # 냉난방 연동 잠금
    vent_first_ids: set = field(default_factory=set)   # 환기 우선으로 쉬는 냉난방
    day_open_ids: set = field(default_factory=set)     # 낮 — 걷어 두는 보온커튼
    humid_zone: bool = False                           # 과습 구간(다음 사이클의 이력)
    heat_cap_ids: set = field(default_factory=set)     # VPD 직접 모드 — 유도 범위 상한에서 난방 출력을 깎는 난방기
    heat_cap_pct: Optional[float] = None               # 그 상한(%), None = 걸지 않음 (`HR.heat_cap_pct`)
    humid_parked: set = field(default_factory=set)     # 과습 — 환기로 해소 불가(닫는 쪽)
    humid_cap_ids: set = field(default_factory=set)    # 과습 — 열림 상한(HR.CAP_PCT)
    humid_cold: set = field(default_factory=set)       # 과습 — 실외가 너무 차서 닫는 쪽
    # 극한 고온 보호(`heat_protect`) — 판정은 그 모듈, 여기는 이 사이클의 장치 집합.
    heat_open_ids: set = field(default_factory=set)        # 열어도 됨(실외가 더 차다)
    heat_closed_ids: set = field(default_factory=set)      # 바깥이 더 덥다 — 파킹(근거 28)
    heat_fog_blocked_ids: set = field(default_factory=set) # 분무 차단 — 파킹(근거 29)
    heat_floor_ids: set = field(default_factory=set)       # 닫는 중이어도 하한까지는 연다
    heat_floor_pct: float = 0.0
    # 분무용 물이 없다(`water_supply`) — 폭염과 무관하게 분무기 전부를 쉰다(근거 41).
    water_blocked_ids: set = field(default_factory=set)
    # 야간 파킹 직전 완충 구간 — 이 환기 장치들은 VPD·습도 요구로 **더 열리지 않는다**(근거 48).
    taper_ids: set = field(default_factory=set)
    # 낮 일사 부하 환기 하한(`solar_vent`, 근거 51) — 이 장치들은 VPD·습도 요구로 하한 아래로 닫히지 않는다.
    solar_floor_ids: set = field(default_factory=set)
    solar_floor_pct: float = 0.0
    # 아침 습기 빼기 하한(`humid_regime.morning_purge`, 근거 54) — 27 로 닫는 대신 조금 연다.
    purge_ids: set = field(default_factory=set)
    purge_pct: float = 0.0
    purge_state: Optional[HR.PurgeState] = None        # 다음 사이클의 이력
    # 실외를 모르는 동안(`hold_ids`)에도 닫는 쪽은 허용한다(근거 58, 모듈 상수 주석).
    outage_park_ids: set = field(default_factory=set)  # 야간 파킹 — 실외를 몰라도 감쇠해 닫는다(근거 19)
    outage_zero_ids: set = field(default_factory=set)  # 해 진 뒤 ≤ 10 % 열린 개구부 — 0 으로(근거 58)
    # 두절이 30 분 넘게 이어진 밤, 습도 때문에 열린 개구부 — 사이클당 `outage_dehumid_step_pct` %p 씩 0 까지(근거 58).
    outage_dehumid_ids: set = field(default_factory=set)
    outage_dehumid_step_pct: float = 0.0
    # 실내를 모르는 동안 해를 보고 정한 작은 환기(근거 60, `solar_vent` 머리말 마지막 절) — 실제로 서는 것은
    # 그 사이클에 근거 21(실내 모름, 제자리)로 갈 장치뿐이다(`coordinate` 2.8).
    blind_floor_ids: set = field(default_factory=set)  # 맑은 낮 — 하한까지 단계로 연다
    blind_floor_pct: float = 0.0
    blind_close_ids: set = field(default_factory=set)  # 해 진 뒤 — 하한 크기 이하로 열린 것을 단계로 닫는다
    blind_step_pct: float = 0.0


# @manual ai/env-control#settings-ventilation
def decide_parking(available: List[ActuatorProfile], situation: SituationReport,
                   ctx: Dict, cycle_sec: float, prev_commands: Dict[str, float],
                   vent_first_held_s: float = 0.0,
                   log: bool = True,
                   humid_prev: bool = False,
                   purge_prev: Optional[HR.PurgeState] = None) -> ParkDecision:
    """파킹 판정(2.5~2.6). `log=False` 는 그림자 계산용 — 인내 시간 경고를 두 번
    남기지 않는다(상태도 호출부가 버린다). `purge_prev` 는 아침 습기 빼기의 이력(2.95) —
    이력을 이어 주지 않는 호출부(MPC 경로: 그 하한을 모른다)는 None 이고, 그러면 켜지고 꺼질 때의
    한 줄도 남기지 않는다."""
    _err = logger.error if log else (lambda *a, **k: None)
    held = float(vent_first_held_s or 0.0)
    futile_ids: set = set()
    futile_raw: set = set()
    futile_s: Dict[str, float] = {}
    futile_dwell_ids: set = set()
    interlock_ids: set = set()
    vent_first_ids: set = set()
    # ── 2.5. 개구부 파킹 판정 (사용자 옵션 2종) ────────────────────────────────
    # 파킹된 액추에이터는 편차 비례로 조금씩 여는 대신 NO_GRADIENT 완화 경로로
    # 보내 safe_default 로 수렴시킨다. 두 판정은 성격이 다르다.
    #   (a) 환기 무익  — 실외 상태로는 목표에 갈 수 없다 (도달 가능성)
    #   (b) 냉난방 연동 — 갈 수는 있으나 냉난방과 맞서 에너지를 버린다 (상충)
    park_ids: set = set()
    vents = [p for p in available if getattr(p, 'kind', '') in VENTILATING_KINDS]

    # 극한 고온 보호(`heat_protect`)의 결론 — 판정은 그 모듈이 이미 했다.
    _hp = ctx.get('heat_protect')
    _hp_on = bool(getattr(_hp, 'active', False))

    # 온도 상한 — 무익 게이트와 PI 가 같은 판정을 본다(한 번만 계산).
    t_ceiling = _temperature_ceiling(situation, ctx, cycle_sec)
    ctx['_t_ceiling'] = t_ceiling
    if t_ceiling is not None:
        logger.debug('온도 상한 — 초과 %.2f °C, 하드 %s', t_ceiling[0], t_ceiling[1])

    if bool(ctx.get('vent_futility_gate', False)):
        futile_raw = {p.actuator_id for p in vents
                      if _ventilation_is_futile(p, situation, ctx)}
        _prev_s = ctx.get('_futile_s_prev') or {}
        futile_s = {i: float(_prev_s.get(i, 0.0)) + float(cycle_sec or 0.0)
                    for i in futile_raw}
        futile_dwell_ids = {
            i for i in futile_raw
            if futile_s[i] < FUTILE_DWELL_S
            and float(prev_commands.get(i, 0.0) or 0.0) > 1.0}
        futile = futile_raw - futile_dwell_ids
        futile_ids = set(futile)
        if futile_dwell_ids:
            logger.debug('환기 무익 대기 — %d개 제자리(%.0f초 미만): %s',
                         len(futile_dwell_ids), FUTILE_DWELL_S,
                         sorted(i[:8] for i in futile_dwell_ids))
        if futile:
            park_ids |= futile
            logger.debug(
                '환기 무익 — 실외 상태로는 목표에 못 감, %d개 파킹: %s',
                len(futile), sorted(i[:8] for i in futile))

    # ── 야간 개구부 파킹 ─────────────────────────────────────────────────────
    # 밤에는 습도가 오르고 이슬이 맺힌다 — 환기 대신 장치로 관리하는 시간대다.
    # **개구부만** 닫고 냉난방·제습은 그대로 돌린다(제어의 중단이 아니라 수단의
    # 제한이다). 넘을지 말지의 판정과 하드 임계 탈출구는 호출자에 있다
    # (`_night_vent_decide`) — 여기 오는 것은 그 결론뿐이다.
    #
    # ⚠ **안전 게이트가 이긴다.** 게이트는 이 함수 앞에서 명령을 강제하거나
    #   (triggered) 뒤에서 덮어쓰므로(partial), 파킹은 그 사이에서만 유효하다.
    #   여름밤 고온에 창이 잠긴 채 방치되면 작물 손실이다 — 파킹이 잠금이
    #   아니라 park_ids 인 덕분에 이 성질이 공짜로 따라온다.
    night_parked: set = set()
    if bool(ctx.get('night_vent_park', False)):
        night_parked = {p.actuator_id for p in vents}
        if night_parked:
            park_ids |= night_parked
            logger.debug(
                '야간 파킹 — 개구부 %d개를 닫는다: %s',
                len(night_parked), sorted(i[:8] for i in night_parked))

    if bool(ctx.get('hvac_interlock', False)) and bool(ctx.get('hvac_running', False)):
        locked = {p.actuator_id for p in vents}
        interlock_ids = set(locked)
        if locked:
            park_ids |= locked
            logger.debug(
                '냉난방 연동 — 가동 중이라 개구부 %d개 잠금: %s',
                len(locked), sorted(i[:8] for i in locked))

    # ── 환기 우선 — 실외가 목표 너머면 냉난방을 쉬게 한다 ──────────────────────
    # `hvac_interlock` 의 짝이다. 둘 다 켜도 교착하지 않는다: 이 판정은 실외
    # 조건만 보므로 냉난방이 파킹되면 hvac_running 이 내려가고 개구부 잠금이
    # 풀린다. 반대로 환기 여력이 없으면 여기서 파킹하지 않으므로 냉난방이 계속
    # 일한다 — 아무도 일하지 않는 상태로 떨어지지 않는다.
    #
    # ⚠ 판정이 참인 동안 **인내 시간을 센다.** 예측이 맞다면 편차가 줄어 판정이
    #   스스로 꺼지므로 시간은 쌓이지 않는다. 쌓인다는 것은 곧 예측이 틀렸다는
    #   뜻이고, 그때는 파킹을 풀어 냉난방에 넘긴다(VENT_FIRST_PATIENCE_S).
    #
    # ⚠ **의지하는 정도는 둘이 아니라 연속이다** (2026-08-26). 예전에는
    #   "전부 된다"(파킹) 아니면 "아니다"(냉난방이 전체 편차를 혼자 계산)뿐이라,
    #   흔한 중간(실외가 목표의 일부를 메운다)에서 냉난방이 과다 가동했다.
    #   `_ventilation_credit` 이 그 몫을 재서 냉난방의 편차에서 뺀다.
    #   판단 기준은 스위치가 아니라 **내외 환경 차이**다 — 실외가 못 도우면
    #   크레딧이 0 이라 저절로 예전 동작이 된다.
    # 강우·풍속을 잃은 개구부 — "더 열지 않음"(2.6 아래 주석). 환기 우선보다
    # **앞에서** 정한다: 더 열 수 없는 창의 도움을 믿고 냉난방이 물러나면 안
    # 된다(비 오는 날 난방이 모자라는 모양, `_ventilation_credit` 안전 조건).
    ceiling_ids = vent_open_ceiling_ids(ctx, vents)

    vent_credit: Dict[str, float] = {}
    # 극한 고온 보호 중에는 환기 우선을 끈다 — 냉방을 쉬게 할 때가 아니다(`heat_protect`).
    # 강우 단계 제한(근거 52)으로 상한이 걸린 창도 같다 — 상한 위의 도움을 믿으면 안 된다.
    if (bool(ctx.get('vent_first', False)) and not ceiling_ids and not _hp_on
            and not rain_vent_caps(ctx, vents)):
        hvac_ids = {p.actuator_id for p in available
                    if ACTUATOR_DOMAIN.get(getattr(p, 'kind', '')) == 'hvac'}
        _reaches = _ventilation_reaches_all_targets(
            situation, ctx, vents, prev_commands)
        _credit = ({} if _reaches else
                   _ventilation_credit(situation, ctx, vents, park_ids))
        if _reaches or _credit:
            # 환기에 **의지하고 있는** 동안 인내를 센다. 전부 맡기든 일부만
            # 맡기든, 목표에 못 닿은 채 시간이 흐르면 예측이 틀린 것이다.
            _held_before = held
            held += float(cycle_sec)
            if held >= VENT_FIRST_PATIENCE_S:
                # 넘겼다는 사실은 남긴다 — 안 그러면 "왜 갑자기 켜졌나" 에
                # 답할 근거가 어디에도 없다.
                #
                # ⚠ **문턱을 처음 넘는 사이클에 한 번만** (2026-09-20). 예전에는
                #   넘긴 뒤 매 사이클 찍어서 aot-005 에서 하루 14~80줄이 쌓였다
                #   — 읽어야 할 로그를 밀어낸다. 한 번이면 "언제부터" 가 남고,
                #   풀릴 때 한 번 더 남겨 "언제까지" 를 닫는다(아래 else).
                # ⚠ **냉난방이 없으면 "넘긴다" 고 말하지 않는다.** 넘길 대상이
                #   없는데 넘긴다고 쓰면 거짓이고, 그 시설에서 이 판정의 실제
                #   뜻은 "환기만으로 목표에 못 닿는다"(설비 한계)다.
                if _held_before < VENT_FIRST_PATIENCE_S:
                    if hvac_ids:
                        _err(
                            '환기 우선 — %.0f분째 목표에 못 닿아 냉난방 %d개에 '
                            '넘깁니다(실외 예측이 빗나갔습니다)',
                            held / 60.0, len(hvac_ids))
                    else:
                        _err(
                            '환기만으로 목표에 닿지 못하고 있습니다(%.0f분째) — '
                            '넘길 냉난방 장치가 없어 환기로 계속 버팁니다',
                            held / 60.0)
            elif _reaches and hvac_ids:
                park_ids |= hvac_ids
                vent_first_ids = set(hvac_ids)
                logger.debug(
                    '환기 우선 — 실외로 목표에 닿으므로 냉난방 %d개 파킹: %s',
                    len(hvac_ids), sorted(i[:8] for i in hvac_ids))
            else:
                vent_credit = _credit
                logger.debug(
                    '환기 우선 — 실외가 대신 해 주는 몫: %s',
                    {k: round(v, 3) for k, v in _credit.items()})
        else:
            if held >= VENT_FIRST_PATIENCE_S:
                # 위에서 한 번 남긴 경고를 닫는다 — 없으면 로그만 보고는
                # 그 상태가 지금도 이어지는지 알 수 없다.
                _err(
                    '환기 우선 — 판정이 풀렸습니다(%.0f분 지속). 목표에 '
                    '들어왔거나 환기로 갈 수 없는 조건이 되었습니다',
                    held / 60.0)
            held = 0.0
    else:
        held = 0.0

    # ── 2.55. 맞서는 짝은 **온도 축의 요구가 한쪽만 고른다** ──────────────────
    # 냉방과 난방은 온도 축에서 정확히 raise/lower 쌍이다. PID 는 오차 부호가
    # 한쪽만 고르므로 **방향을 정하는 행위 자체가 인터록**인데, 코디네이터는
    # 액추에이터마다 따로 PI 를 돌려서 그 성질이 공짜로 따라오지 않는다.
    # 그래서 여기서 명시적으로 준다 — 요구 방향의 반대편을 이 사이클의 후보에서
    # 뺀다(파킹).
    #
    # ⚠ **뒤에서 끄는 것으로는 부족하다.** 디스패치 직전 인터록
    # (`_cycle_mixin.apply_hvac_opposition_interlock`)은 마지막 방어선이지만,
    # 그때까지 진 쪽은 **매 사이클 100% 를 원하며 적분을 쌓는다.** 여기서 빼면
    # 적분이 safe_default 로 풀린다(아래 NO_GRADIENT 경로).
    #
    # ⚠ **VPD 직접 제어 모드에서는 온도가 제어목표에 없다.** `_decompose_vpd`
    # 가 'temperature' 를 `_temperature_constraint` 로 강등하므로
    # `deviation_native` 에 온도가 아예 없다 — 그래서 편차 부호만 보면 이 판정이
    # **통째로 서지 않는다.** 실측(2026-08-26 温室環境制御)에서 난방기를 100%
    # 로 만든 근거는 온도가 아니라 VPD 였고, 그동안 실내는 하드 상한을 4°C
    # 넘겨 있었다. 그래서 하드 임계를 **먼저** 본다.
    #
    #   1) 하드 임계 위반(temp_max/temp_min) — 사용자가 정한 문턱. 최우선.
    #   2) 온도 잔여 편차의 부호 — 허용오차 밖일 때만. 제어목표에서 강등됐어도
    #      목표·허용오차는 `_temperature_constraint` 에 그대로 남아 있다.
    #   3) 둘 다 없으면 제한하지 않는다 — 온도가 편안한 구간이면 VPD 를 위해
    #      가온하거나 냉방하는 것이 옳다.
    # 파킹 사유를 구분해 두는 집합. 같은 파킹이라도 **왜** 쉬는지가 다르면
    # 화면이 다른 말을 해야 한다(0% 로 쉬는 난방기에게 "할 수 있는 만큼 하고
    # 있다" 는 정반대의 말이다).
    opposing_ids: set = set()
    _internal = (ctx.get('internal') or {})
    _demand = None
    if bool(_internal.get('_force_cool')) or _hp_on:
        # 극한 고온 보호 중에는 난방이 설 자리가 없다 — 냉각 요구로 본다.
        _demand = 'cool'
    elif bool(_internal.get('_force_heat')):
        _demand = 'heat'
    else:
        _t_now = ctx.get('T_int')
        _t_tv = ((situation.target or {}).get('temperature')
                 or (situation.target or {}).get('_temperature_constraint'))
        _tol = float(getattr(_t_tv, 'tolerance', 0.0) or 0.0) if _t_tv else 0.0
        if _t_now is not None and _t_tv is not None and _tol > 0:
            _t_dev = float(_t_now) - float(_t_tv.value)
            if _t_dev > _tol:
                _demand = 'cool'
            elif _t_dev < -_tol:
                _demand = 'heat'
    # ── 2.56. VPD 직접 모드의 난방 출력 상한 — 유도 범위 상한에서 0 ─────────────────
    # 위 2.55 의 맞서는 짝은 '유도 목표 ± 허용오차' 를 넘어야 서는데, 유도 목표는 범위 상한으로 잘려 있어 실제 문턱이 상한 +
    # 허용오차였다. 그 사이에서 VPD 항(낮 목표가 해 진 뒤에도 천천히 내려온다)이 난방기를 80~100 % 로 몰았다. 기준선 정의는
    # `HR.temp_band_c` 의 위 선이다(`HR.heat_cap_pct`). 하드 한계(`_force_heat`)는 이긴다.
    heat_cap_pct = HR.heat_cap_pct(
        ctx.get('T_int'), (situation.target or {}).get('temperature'),
        ctx.get('T_guide_low'), ctx.get('T_ceiling'), force_heat=bool(_internal.get('_force_heat')))
    heat_cap_ids = ({p.actuator_id for p in available if getattr(p, 'kind', '') in SP.HEATING_KINDS}
                    if heat_cap_pct is not None else set())
    if _demand:
        _losing_kind = 'heater' if _demand == 'cool' else 'cooler'
        _losers = {p.actuator_id for p in available
                   if getattr(p, 'kind', '') == _losing_kind}
        if _losers:
            park_ids |= _losers
            opposing_ids |= _losers
            logger.debug(
                '온도 축 요구=%s — 반대편 %s %d개 파킹: %s',
                _demand, _losing_kind, len(_losers),
                sorted(i[:8] for i in _losers))

    # ── 2.6. 실외 근거가 지어낸 것이면 → **제자리 유지**(hold) ──────────────────
    # 환기는 실내를 실외 쪽으로만 밀 수 있으므로, 실외를 모르면 열지 닫을지 말할
    # 근거가 없다. 그런데 지금 구조는 실외를 모를 때 fallback 이 **실외=실내**로
    # 가정해 채운다(`ext_context_fallback`, 캐시가 비었을 때). 그러면 내외 차이가
    # 0 이라 환기 무익 판정이 서고 개구부가 safe_default(닫힘)로 수렴한다 —
    # 한여름에 기상대가 죽으면 창이 닫힌다는 뜻이다. 실측(리플레이에서 기상대만
    # 제거): 71 사이클 전부 NO_GRADIENT, 개도가 0 까지 내려갔다.
    #
    # 파킹(위 2.5)과 다르다 — 파킹은 닫는 것이고, 여기서 해야 할 일은 **아무것도
    # 하지 않는 것**이다. 근거가 없다는 이유로 장비를 움직여서는 안 된다.
    #
    # 판정은 `_ext_synthetic`(캐시조차 없어 지어낸 실외) 하나로 한다. 마지막
    # 실측이 남아 있으면(캐시 hit) 그것은 근거이므로 여기 걸리지 않는다.
    if bool((ctx.get('external') or {}).get('_ext_synthetic')):
        hold_ids = {p.actuator_id for p in vents}
    else:
        hold_ids = set()
    if hold_ids:
        # 근거 없음이 근거 있는 판정을 이겨서는 안 되므로 파킹에서 뺀다.
        park_ids -= hold_ids
        logger.debug(
            '실외 측정 없음(지어낸 값) — 개구부 %d개 제자리 유지: %s',
            len(hold_ids), sorted(i[:8] for i in hold_ids))

    # ── 2.65. 과습 구간 — 환기를 **수증기압**(이슬점)으로 판단한다 (2026-10-01) ──
    # 근거·문턱·예외는 `humid_regime` 모듈 머리말에 있다. 요점: 공기가 포화에 가까우면
    # VPD 는 온도에 끌려다니는 양이라 "실외 VPD 가 더 높다" 가 "열면 건조해진다" 를
    # 뜻하지 않는다(실외가 따뜻하면 수분이 더 많아도 VPD 가 높다).
    #
    #   실외 이슬점이 실내보다 1.5 °C 이상 낮다  → 열 수 있다(상한 HR.CAP_PCT)
    #   그렇지 않다                               → 창으로 해소 불가 — 닫는 쪽(파킹)
    #
    # ⚠ **온도 비상이 이긴다.** 덥고 습한 날의 환기는 습도가 아니라 온도가 요구한다 —
    #   `_force_cool`·온도 상한 항이 서 있으면 이 구간을 적용하지 않는다.
    # ⚠ **실외를 모르면 판단하지 않는다**(2.6 의 제자리가 맡는다). 모르는 채로 닫거나
    #   여는 것은 근거 없는 결정이다.
    # ⚠ 하드 습도 상한(`_force_dehumid`)을 넘었으면 **상한을 풀되**(습기를 빼야 한다)
    #   실외가 더 습하면 여전히 열지 않는다 — 열어서 더 습해지는 것은 해소가 아니다.
    humid_zone = False
    humid_parked: set = set()
    humid_cold: set = set()
    humid_cap_ids: set = set()
    if (t_ceiling is None and not bool(_internal.get('_force_cool'))):
        humid_zone = HR.in_overhumid_zone(
            ctx.get('T_int'), ctx.get('RH_int'), was_in=bool(humid_prev))
    if humid_zone != bool(humid_prev):
        _err('과습 구간 %s — 실내 %s °C · %s %%(이슬점 여유 %s °C)',
             '진입' if humid_zone else '이탈',
             ctx.get('T_int'), ctx.get('RH_int'),
             '-' if HR.dewpoint_c(ctx.get('T_int'), ctx.get('RH_int')) is None
             else '%.1f' % (float(ctx['T_int']) - HR.dewpoint_c(
                 ctx.get('T_int'), ctx.get('RH_int'))))
    # ⚠ **온도 기준선 이하에서는 이슬점 기준 환기를 빼고 온도가 이긴다**(2026-10-01 사용자
    #   제안). 실내가 기준선 이하이면 더 식힐 이유가 없고, 차가운 외기는 그 온도를
    #   더 떨어뜨린다 — 이슬점이 낮다는 이유로 열면 안 된다. 외기가 더 **따뜻**하면(밤의
    #   3포장) 열어도 온도가 오르므로 이 규칙에 걸리지 않는다(`relief_verdict` 는 실외가
    #   `HEAT_DEMAND_COLD_DELTA_C` 넘게 차가울 때만 COLD 로 본다).
    # ⚠ **기준선은 `humid_regime.temp_edge_c` 한 곳이 정한다**(아침 습기 빼기 2.95 와 같은 함수). 온도가 제어
    #   목표면 목표 + 허용오차(예전 그대로), **VPD 직접 모드면 유도 범위의 아래 끝**이다 — 그 모드의 유도 온도
    #   목표는 실내 + 0.6 × (필요한 만큼)이라 늘 실내보다 앞서 가서 '실내 ≤ 목표 + 허용오차' 가 늘 참이었다
    #   (김제 2026-10-13: 외기가 1 °C 만 차도 COLD → 13:48 에 27 로 닫힘, 과습 3시간). 같은 이유로 유도
    #   목표에서 나온 `_demand == 'heat'` 는 쓰지 않는다 — 온도가 제어 목표면 그 요구는 기준선 이하에 이미
    #   들어 있고(허용오차 > 0), VPD 직접 모드에서는 가짜 요구다. 진짜 난방 요구는 `_force_heat`(최저 온도 한계).
    _warm_side = HR.warm_side(ctx.get('T_int'), (situation.target or {}).get('temperature'),
                              ctx.get('T_guide_low'), force_heat=bool(_internal.get('_force_heat')))
    if humid_zone:
        for p in vents:
            if p.actuator_id in hold_ids:
                continue
            _was_open = float(prev_commands.get(p.actuator_id, 0.0) or 0.0) > 1.0
            verdict = HR.relief_verdict(
                ctx.get('T_int'), ctx.get('RH_int'),
                ctx.get('T_ext'), ctx.get('RH_ext'), was_open=_was_open,
                heat_demand=_warm_side)
            if verdict is None:
                continue
            if verdict == HR.OK:
                # 열림 상한 — 열 손실이 작고 실외가 충분히 건조하면 푼다(`humid_regime.relief_cap_pct`).
                # 이미 풀려 있던 중(직전 명령이 CAP 위)이면 문턱이 완화된다.
                _was_lifted = float(prev_commands.get(p.actuator_id, 0.0) or 0.0) > HR.CAP_PCT + 1.0
                if (not bool(_internal.get('_force_dehumid'))
                        and HR.relief_cap_pct(
                            ctx.get('T_int'), ctx.get('RH_int'), ctx.get('T_ext'),
                            ctx.get('RH_ext'), was_lifted=_was_lifted) < HR.CAP_FREE_PCT):
                    humid_cap_ids.add(p.actuator_id)
            elif verdict == HR.COLD:
                # ⚠ **겨울 난방 중에는 열지 않는다.** 실외 이슬점이 훨씬 낮아 "습기를 뺀다" 로
                #   읽히지만, 온도차가 크면 열 손실·저온 피해가 습기 제거보다 크다
                #   (`humid_regime.relief_verdict`).
                humid_cold.add(p.actuator_id)
            else:
                humid_parked.add(p.actuator_id)
        if humid_parked or humid_cold:
            park_ids |= humid_parked | humid_cold
            logger.debug(
                '과습 구간 — 환기로 해소 불가(더 습함 %d · 너무 참 %d): %s',
                len(humid_parked), len(humid_cold),
                sorted(i[:8] for i in humid_parked | humid_cold))

    # ── 낮에는 보온커튼을 걷어 둔다 ───────────────────────────────────────────
    # 효과 모델은 커튼의 **열 교환**만 안다(걷힘 = 외기와 섞임). 빛을 막는다는
    # 사실은 모델 밖에 있어서, 맡겨 두면 VPD 를 올리려 낮에도 닫는다 — 실측
    # (2026-09-25 영양): 오전 8시 22분에 닫혀 다음 날 정오까지 그대로였다. 낮·밤은
    # 시설 위치의 일출·일몰로 가른다(호출자, `curtain_day_open`). 모르면(좌표 없음)
    # 걸지 않는다. 차광막은 빛을 다루는 장치라 대상이 아니다.
    day_open_ids = ({p.actuator_id for p in available
                     if getattr(p, 'kind', '') == 'curtain'}
                    if bool(ctx.get('curtain_day_open', False)) else set())

    # ── 2.65b. 분무용 물이 없다 — 분무기 전부를 쉰다(`water_supply`, 근거 41) ───────
    # 극한 고온 보호 안의 분무 차단(근거 29)과 달리 **폭염이 아니어도** 선다 — 물 없이
    # 펌프를 돌리면 상한다. 판정은 `water_supply` 한 곳이고(코디네이터가 internal 에 싣는다),
    # 여기서는 그 결론만 읽는다. 옵션을 안 켰으면 키가 True 라 아무 일도 없다.
    # 파킹(감쇠)과 함께 전달 비율 0(`_apply_cmd_scales`)이 이번 사이클부터 0 을 내보낸다.
    water_blocked_ids: set = set()
    if _internal.get('_water_available', True) is False:
        water_blocked_ids = {p.actuator_id for p in available
                             if getattr(p, 'kind', '') == 'fogger'}
        if water_blocked_ids:
            park_ids |= water_blocked_ids
            logger.debug('분무용 물 없음 — 분무기 %d개 파킹: %s', len(water_blocked_ids),
                         sorted(i[:8] for i in water_blocked_ids))

    # ── 2.7. 극한 고온 보호 — 결론만 싣는다(판정은 `heat_protect` 한 곳) ──────────
    # 열어도 되는 환기 장치는 야간 파킹·냉난방 연동·환기 무익에서 뺀다 — 바깥이 더
    # 시원한 폭염 중에 창을 잠가 둘 이유가 없다. 바깥이 더 더우면 닫는 쪽(파킹, 근거 28),
    # 분무를 쓸 수 없으면 분무도 파킹(근거 29). 그 뒤 **실외를 모르는 장치는 여전히
    # 제자리**다(2.6 — 근거 없음이 근거 있는 판정을 이기지 않듯, 보호도 지어낸 실외로
    # 창을 움직이지 않는다).
    heat_open_ids: set = set()
    heat_closed_ids: set = set()
    heat_fog_blocked_ids: set = set()
    heat_floor_ids: set = set()
    heat_floor_pct = 0.0
    if _hp_on:
        _avail = {p.actuator_id for p in available}
        heat_open_ids = set(_hp.vent_open_ids) & _avail
        heat_closed_ids = set(_hp.vent_closed_ids) & _avail
        heat_fog_blocked_ids = set(_hp.fog_blocked_ids) & _avail
        heat_floor_ids = set(_hp.floor_ids) & heat_closed_ids
        heat_floor_pct = float(_hp.floor_pct or 0.0) if heat_floor_ids else 0.0
        park_ids = ((park_ids - heat_open_ids) | heat_closed_ids
                    | heat_fog_blocked_ids)
        night_parked -= heat_open_ids
        interlock_ids -= heat_open_ids
        futile_ids -= heat_open_ids
        futile_dwell_ids -= heat_open_ids
        park_ids -= hold_ids
        heat_closed_ids -= hold_ids
        heat_floor_ids -= hold_ids
        if heat_open_ids or heat_closed_ids or heat_fog_blocked_ids:
            logger.debug(
                '극한 고온 보호 — 열어도 됨 %d · 바깥이 더 더움 %d(하한 %.0f %%) · '
                '분무 차단 %d', len(heat_open_ids), len(heat_closed_ids),
                heat_floor_pct, len(heat_fog_blocked_ids))

    # ── 2.8. 야간 파킹 직전 완충 구간 — 곧 닫힐 창을 더 열지 않는다 (2026-10-09 김제) ─────────
    # 해 질 무렵에는 실내 RH 가 오르고 실외가 더 건조해서 "환기하면 VPD 가 오른다" 가 창을 연다.
    # 그 창을 10분 뒤 야간 파킹이 닫는다(16:48 12 % → 17:49 91 % → 18:42 0 %). 구간(`_night_vent_clock`,
    # 파킹 시작 전 45분) 안에서는 환기 장치가 **현재 열림을 넘겨 열리지 않는다** — 닫는 쪽은 그대로
    # PI 가 한다. 상한을 점점 낮추는 경사(램프)는 일부러 두지 않았다: 평형으로 열려 있어야 하는 집을
    # 파킹보다 먼저 억지로 닫게 되고, 그 닫음 자체가 모터 이동이다. 막는 것은 **늘어나는** 이동 하나다.
    #
    # ⚠ **안전·한계 사유가 이긴다.** 아래는 구간을 적용하지 않는다(= 열 수 있다):
    #   · `_force_cool`·`_force_dehumid` — 하드 온·습도 임계 (호출자가 구간 값을 이미 비운다)
    #   · 온도 상한의 하드 항 — 투영 온도가 `temp_max` 에 닿았다
    #   · 극한 고온 보호 중 — 열어도 되는 창은 열린다(2.7)
    #   · 결로 탈출 — 호출자(`_night_vent_decide`)가 구간 값을 비운다
    #   강우·풍속 게이트는 이 판정과 무관하게 닫는다(안전 게이트가 위에 있다).
    # ⚠ 이미 닫히는 중인 장치(파킹·실외 모름·더 열지 않음)는 뺀다 — 그쪽 근거가 더 정확하다.
    taper_ids: set = set()
    _taper_s = ctx.get('night_vent_taper_s')
    if (_taper_s is not None and not night_parked and not _hp_on
            and not bool(_internal.get('_force_cool'))
            and not bool(_internal.get('_force_dehumid'))
            and not (t_ceiling is not None and bool(t_ceiling[1]))):
        taper_ids = {p.actuator_id for p in vents} - park_ids - hold_ids - ceiling_ids
        if taper_ids:
            logger.debug(
                '야간 파킹 %.0f분 전 — 개구부 %d개를 더 열지 않는다: %s',
                float(_taper_s) / 60.0, len(taper_ids), sorted(i[:8] for i in taper_ids))

    # ── 2.9. 낮 일사 부하 환기 하한 — 결론만 싣는다(판정은 `solar_vent` 한 곳, 근거 51) ──────────
    # 해가 들고 실내가 온도 목표 위면 환기 장치(개구부, 없으면 팬)를 하한까지 연다. 위가 이긴다:
    # 실외 모름(제자리) · 강우·풍속 모름(더 열지 않음) · 야간 파킹 · 파킹 직전 완충 · 냉난방 연동 ·
    # 보호의 '바깥이 더 덥다'. 이기는 쪽: VPD·습도 항 · 무구배 · 환기 무익 · 과습 구간(열을 빼는 것이 먼저).
    # 풀릴 때는 한 번에 푼다 — 내림 램프(2026-10-12 #161)는 PI 와 번갈아 창을 올렸다 내려 창 반전이 기준보다
    # 나빠졌고(최종 폐루프 회귀 R1·R5, 고친 뒤에도 normal 0.98 → 1.19 · fog 0.20 → 0.76 /h) 되돌렸다. 선 뒤 30 분
    # 유지(`solar_vent.SV_MIN_ON_S`)가 짧은 켬/끔을 맡는다.
    solar_floor_ids: set = set()
    solar_floor_pct = 0.0
    _sv = ctx.get('solar_vent')
    if bool(getattr(_sv, 'active', False)) and float(getattr(_sv, 'floor_pct', 0.0) or 0.0) > 0.0:
        solar_floor_ids = (SV.floor_targets(vents) - hold_ids - ceiling_ids - night_parked
                           - taper_ids - interlock_ids - heat_closed_ids)
        if solar_floor_ids:
            solar_floor_pct = float(_sv.floor_pct)
            logger.debug('일사 부하 — 환기 %d개 하한 %.1f %%: %s', len(solar_floor_ids),
                         solar_floor_pct, sorted(i[:8] for i in solar_floor_ids))

    # ── 2.95. 아침 습기 빼기 하한 — 결론만 싣는다(판정은 `humid_regime.morning_purge` 한 곳, 근거 54) ──
    # 해가 들어 집이 데워지는데 실내가 과습이고 실외 공기가 더 건조하면, 2.65 가 27(실외가 너무 참)로 닫아
    # 두던 환기창을 5~15 % 연다. 몇 시간의 RH 90 % 이상은 병의 조건이다(영양 2026-10-10 07~09시 RH 91 %
    # · 창 0 %). 위가 이긴다(일사 하한과 같은 집합): 실외 모름 · 강우·풍속 모름 · 야간 파킹 · 파킹 직전
    # 완충 · 냉난방 연동 · 보호의 '바깥이 더 덥다'. 이기는 쪽: 2.65 의 파킹(27·24)·무구배·환기 무익.
    # 온도 비상이면 과습 구간이 아예 서지 않는다(`humid_zone` 참조) — 그때는 온도가 환기를 요구한다.
    purge_ids: set = set()
    purge_pct = 0.0
    # 온도 하한선(`humid_regime.temp_edge_c` — 2.65 의 `_warm_side` 와 같은 함수): 온도가 제어 목표면
    # 목표 − 허용오차. **VPD 직접 모드에서는 유도 온도 목표를 쓰지 않는다** —
    # 그 값은 현재 실내 온도 + 0.6 × (VPD 를 맞추는 데 필요한 만큼)이라 항상 지금보다 앞서 있고 습할수록 더
    # 멀리 간다(영양 2026-10-10: 실내 15.8 → 목표 하한 18.5, 20.8 → 22.7). 가장 습한 때 '너무 춥다' 로 막힌다.
    # 그때는 유도 범위의 아래 끝(`T_guide_low` — 하드 최저로 좁힌 뒤)이 작물이 견디는 하한이다.
    _t_low_p = HR.temp_edge_c((situation.target or {}).get('temperature'), ctx.get('T_guide_low'))
    _pdec = HR.morning_purge(
        ctx.get('T_int'), ctx.get('RH_int'), ctx.get('T_ext'), ctx.get('RH_ext'),
        getattr(ctx.get('solar_vent'), 'solar_w', None), _t_low_p, humid_zone,
        prev=purge_prev,
        force_heat=bool(_internal.get('_force_heat')),
        dT_h=HR.temp_trend_h(purge_prev, ctx.get('T_int'), cycle_sec))
    # 파킹 직전 완충 구간(2.8)이면 걸지 않는다 — 곧 야간 파킹이 닫을 창을 열면 모터만 움직인다.
    if _pdec.active and _taper_s is None:
        purge_ids = (SV.floor_targets(vents) - hold_ids - ceiling_ids - night_parked
                     - interlock_ids - heat_closed_ids)
        if purge_ids:
            purge_pct = float(_pdec.pct)
            logger.debug('아침 습기 빼기 — 환기 %d개 하한 %.1f %%: %s', len(purge_ids),
                         purge_pct, sorted(i[:8] for i in purge_ids))
    if purge_prev is not None and bool(purge_prev.on) != _pdec.active:
        _err('아침 습기 빼기 %s — %s', '켬' if _pdec.active else '끔', _pdec.describe())
    _ti = ctx.get('T_int')
    purge_state = HR.PurgeState(
        on=_pdec.active, T_prev=None if _ti is None else float(_ti),
        dT_h=HR.temp_trend_h(purge_prev, _ti, cycle_sec))

    # ── 2.6b. 실외를 모르는 동안에도 **닫는 쪽은 한다**(근거 58, 모듈 상수 주석) ─────────────────
    # 위 모든 집합이 `hold_ids` 를 빼므로, 닫는 이동만 여기서 따로 짚는다. 닫는 근거가 실외 값이 아닌 것만
    # 고른다: 야간 파킹은 옵션과 시각이, 해 진 뒤 닫기는 맑은 하늘 일사(좌표)가 근거다. 그 밖의 파킹(무익·
    # 연동·과습)은 지어낸 실외로 계산한 것이라 쓰지 않는다. 하드 한계가 열라고 하는 동안은 건너뛴다.
    # 대상: 실외를 모르는 창(`hold_ids`)과 강우·풍속을 잃은 창(`ceiling_ids`, 2.7 — 지난 값은 온화했고 '더 열지 않음'
    # 뿐이라 PI 가 열자고 해도 제자리에 서던 5 % 창, 폐루프 sensor_storm_outage). 야간 파킹 감쇠는 실외 모름에만
    # 새로 필요하다 — 강우·풍속 모름은 파킹이 이미 park_ids 로 닫는다.
    outage_park_ids: set = set()
    outage_zero_ids: set = set()
    outage_dehumid_ids: set = set()
    outage_dehumid_step = 0.0
    _outage_ids = hold_ids | ceiling_ids
    if _outage_ids:
        outage_park_ids = night_parked & hold_ids
        if not (_internal.get('_force_cool') or _internal.get('_force_dehumid') or _hp_on):
            # 맑은 하늘 일사(좌표로 계산)만 쓴다 — 실측 일사는 두절 중 굳은 값일 수 있어(폐루프: 해 질 녘
            # 74 W/m² 에서 굳음) 밤이 와도 문턱을 못 내려온다. 구름은 맑은 하늘보다 밝게 못 하므로
            # 맑은 하늘이 어두우면 어두운 것이다.
            _sun = SV._num(ctx.get('clear_sky_now'))
            if _sun is not None and _sun < OUTAGE_NIGHT_SOLAR_W:
                outage_zero_ids = {
                    p.actuator_id for p in vents
                    if getattr(p, 'kind', '') == 'opening'
                    and p.actuator_id in _outage_ids
                    and p.actuator_id not in night_parked
                    and RAIL_EPS < float(prev_commands.get(p.actuator_id, 0.0) or 0.0)
                    <= OUTAGE_CLOSE_MAX_PCT}
        # 두절이 오래(30 분 넘게) 이어졌고, 밤에 **습도 때문에** 연 창이면 사이클당 일정 폭으로 닫는다 — 위 '≤ 10 %'
        # 규칙이 하드 습도 상한 아래에서 건너뛴 창. `outdoor_outage_s` 는 두절 시계(`outage_clock`)가 싣는다.
        _out_s = ctx.get('outdoor_outage_s')
        if (_out_s is not None and float(_out_s) >= OUTAGE_DEHUMID_GRACE_S
                and not (_internal.get('_force_cool') or _hp_on)):
            _sun_d = SV._num(ctx.get('clear_sky_now'))
            _released = bool(ctx.get('night_vent_released'))   # 야간 파킹 옵션이 켜진 밤인데 파킹이 풀려 있다
            _night_d = _released or (_sun_d is not None and _sun_d < OUTAGE_NIGHT_SOLAR_W)
            if _night_d and (_released or bool(_internal.get('_force_dehumid'))):
                outage_dehumid_ids = {
                    p.actuator_id for p in vents
                    if getattr(p, 'kind', '') == 'opening'
                    and p.actuator_id in _outage_ids
                    and p.actuator_id not in night_parked
                    and float(prev_commands.get(p.actuator_id, 0.0) or 0.0) > RAIL_EPS}
                _cyc = float(cycle_sec or 0.0)
                outage_dehumid_step = OUTAGE_DEHUMID_STEP_PCT * (
                    min(1.0, _cyc / OUTAGE_DEHUMID_REF_CYCLE_S) if _cyc > 0.0 else 1.0)
        if outage_park_ids or outage_zero_ids or outage_dehumid_ids:
            logger.debug('실외 모름이어도 닫는다 — 야간 파킹 %d · 해 진 뒤 작은 열림 %d · 두절 %.0f분째 제습 열림 %d(-%.1f %%p)',
                         len(outage_park_ids), len(outage_zero_ids),
                         float(_out_s or 0.0) / 60.0, len(outage_dehumid_ids), outage_dehumid_step)

    # ── 2.8b. 실내를 모르는 동안 해를 보고 정한 작은 환기 — 결론만 싣는다(판정은 `solar_vent`, 근거 60) ──────
    # 실내 센서가 모두 끊기면 2.8 의 제자리(근거 21)가 밤의 0 % 를 맑은 낮까지 끌고 간다(2026-10-14 김제 09~13시 ·
    # 구마모토 일사 656 W/m², 창 0 %). 닫힌 집은 해 아래서 바깥보다 15~20 °C 더워진다 — 실외 기온과 일사로 세운
    # 작은 하한까지는 연다. 위가 이긴다(일사 하한과 같은 집합): 실외 모름 · 강우·풍속 모름 · 야간 파킹 · 파킹 직전
    # 완충 · 냉난방 연동 · 보호의 '바깥이 더 덥다'. 강우 단계·서리 주의 상한(52·55·56)은 명령 뒤에서 이긴다.
    # 해가 진 뒤(맑은 하늘 < `OUTAGE_NIGHT_SOLAR_W`, 근거 58 과 같은 선) 실내를 여전히 모르면 그 하한 크기
    # 이하로 열린 창을 같은 폭으로 닫는다 — 이 규칙이 연 것은 이 규칙이 닫는다. 하드 한계·보호가 열라고 하는
    # 동안은 닫지 않는다(2.6b 와 같은 판단). 더 크게 열린 창은 여전히 제자리다(왜 열렸는지 모른다).
    blind_floor_ids: set = set()
    blind_close_ids: set = set()
    blind_floor_pct = 0.0
    blind_step = 0.0
    if bool(getattr(_sv, 'blind', False)):
        _btargets = (SV.floor_targets(vents) - hold_ids - ceiling_ids - night_parked
                     - taper_ids - interlock_ids - heat_closed_ids)
        blind_step = SV.blind_step_pct(cycle_sec)
        if float(getattr(_sv, 'blind_floor_pct', 0.0) or 0.0) > 0.0:
            blind_floor_ids = _btargets
            blind_floor_pct = float(_sv.blind_floor_pct)
        elif not (_internal.get('_force_cool') or _internal.get('_force_dehumid') or _hp_on):
            _sun_b = SV._num(ctx.get('clear_sky_now'))
            if _sun_b is not None and _sun_b < OUTAGE_NIGHT_SOLAR_W:
                blind_close_ids = {
                    i for i in _btargets
                    if RAIL_EPS < float(prev_commands.get(i, 0.0) or 0.0)
                    <= SV.BLIND_FLOOR_MAX_PCT + RAIL_EPS}
        if blind_floor_ids or blind_close_ids:
            logger.debug('실내 모름 — 해를 보고 환기 하한 %.1f %% %d개 · 해 진 뒤 닫기 %d개(사이클당 %.1f %%p)',
                         blind_floor_pct, len(blind_floor_ids), len(blind_close_ids), blind_step)

    return ParkDecision(
        blind_floor_ids=blind_floor_ids, blind_floor_pct=blind_floor_pct,
        blind_close_ids=blind_close_ids, blind_step_pct=blind_step,
        outage_park_ids=outage_park_ids, outage_zero_ids=outage_zero_ids,
        outage_dehumid_ids=outage_dehumid_ids, outage_dehumid_step_pct=outage_dehumid_step,
        purge_ids=purge_ids, purge_pct=purge_pct, purge_state=purge_state,
        solar_floor_ids=solar_floor_ids, solar_floor_pct=solar_floor_pct,
        park_ids=park_ids, night_parked=night_parked, opposing_ids=opposing_ids,
        hold_ids=hold_ids, ceiling_ids=ceiling_ids, vent_credit=vent_credit,
        t_ceiling=t_ceiling, vent_first_held_s=held, futile_ids=futile_ids,
        futile_raw=futile_raw, futile_s=futile_s, futile_dwell_ids=futile_dwell_ids,
        interlock_ids=interlock_ids, vent_first_ids=vent_first_ids,
        day_open_ids=day_open_ids, humid_zone=humid_zone,
        humid_parked=humid_parked, humid_cap_ids=humid_cap_ids,
        heat_cap_ids=heat_cap_ids, heat_cap_pct=heat_cap_pct,
        humid_cold=humid_cold, heat_open_ids=heat_open_ids,
        heat_closed_ids=heat_closed_ids,
        heat_fog_blocked_ids=heat_fog_blocked_ids,
        heat_floor_ids=heat_floor_ids, heat_floor_pct=heat_floor_pct,
        water_blocked_ids=water_blocked_ids, taper_ids=taper_ids)


def _noeffect_candidates(nofx_s: Dict[str, float], vent_strength: Dict[str, float],
                         available: List[ActuatorProfile], suspect_ids: set) -> set:
    """'오래 세게 명령했는데 반응이 없다' 로 서는 장치 — ⑤ 혼자 한 일 · ⑥ 하나는 남긴다.

    ①~④ 는 루프 안에서 `nofx_s` 가 이미 가렸다(세게 · 뚜렷 · 실외를 앎 · 오래). 여기서는 나머지
    둘로 거짓 제외를 막는다 — 모듈 상단 `NOFX_AFTER_S` 주석 참조. 후보가 없으면 빈 집합이다.
    """
    due = {aid for aid, sec in (nofx_s or {}).items() if sec >= NOFX_AFTER_S}
    if not due:
        return set()
    vent_ids = {p.actuator_id for p in available
                if getattr(p, 'kind', '') in VENTILATING_KINDS} - set(suspect_ids)
    total = sum(max(0.0, vent_strength.get(a, 0.0)) for a in vent_ids)
    out = set()
    for aid in due & vent_ids:
        share = (vent_strength.get(aid, 0.0) / total) if total > 1e-12 else 0.0
        if share >= NOFX_SOLE_SHARE:
            out.add(aid)
        else:
            logger.debug('반응 없음 후보 %s 는 환기 효과의 %.0f %% 뿐 — 공통 원인으로 보고 제외하지 않음',
                         aid[:8], share * 100.0)
    # ⑥ 제외하고도 환기 장치가 하나는 남아야 한다.
    if out and len(vent_ids - out) < 1:
        logger.debug('반응 없음 후보 전부가 마지막 환기 장치 — 제외하지 않음')
        return set()
    return out


# @manual ai/env-control#l3-coordinator-actuator-command, ai/env-control#actuators-missing
def coordinate(
    situation: SituationReport,
    profiles: List[ActuatorProfile],
    state: CoordinatorState,
    unique_id: str = '',
    actuator_index: Dict[str, int] = None,
) -> Tuple[CoordResult, CoordinatorState]:
    """
    Run the L3 coordination algorithm (position-form PI).

    Args:
        situation:      L2 SituationReport
        profiles:       list of registered actuators (result of get_profile())
        state:          previous cycle state (pass CoordinatorState() for the first cycle)
        unique_id:      Function unique_id for InfluxDB recording
        actuator_index: {actuator_id: idx} — for logging channel computation

    Returns:
        (commands dict, updated CoordinatorState)
    """
    commands: CoordResult = {}
    ctx = situation.context
    cycle_sec = ctx.get('cycle_sec', 60.0)
    a_idx = actuator_index or {}

    valid_ids = {p.actuator_id for p in profiles}

    # ── 0. integral 마이그레이션/정합 ─────────────────────────────────────────
    # 키가 actuator_id 이고 값이 [0,100] 인 항목만 보존. 과거 변수별 native 누적
    # (예: 'humidity': -394) 은 키가 actuator_id 가 아니므로 자동 폐기된다.
    migrated_integral: Dict[str, float] = {}
    for aid, val in (state.integral or {}).items():
        if aid in valid_ids and isinstance(val, (int, float)):
            migrated_integral[aid] = _clamp(float(val), 0.0, 100.0)

    new_state = CoordinatorState(
        prev_commands=dict(state.prev_commands),
        integral=migrated_integral,
        active_vars=dict(state.active_vars),
        drive_sign=dict(state.drive_sign or {}),
        drive_flip_pending=dict(getattr(state, 'drive_flip_pending', None) or {}),
        t_ceiling_active=bool(getattr(state, 't_ceiling_active', False)),
        gradient_active=dict(getattr(state, 'gradient_active', None) or {}),
        stall_s=dict(getattr(state, 'stall_s', None) or {}),
        stall_ref=dict(getattr(state, 'stall_ref', None) or {}),
        nofx_s=dict(getattr(state, 'nofx_s', None) or {}),
        nofx_ref=dict(getattr(state, 'nofx_ref', None) or {}),
        vent_first_held_s=float(getattr(state, 'vent_first_held_s', 0.0) or 0.0),
        # ⚠ **복사하지 않는다 — 매 사이클 새로 센다.** 이 카운터는 "지금
        # 데드존 안에서 반대쪽에 있다" 의 연속 횟수인데, 복사해 들고 다니면
        # 데드존을 벗어났다 돌아온 장치가 **옛 횟수를 이어받아** 한 사이클
        # 만에 물러난다. 이번 사이클에 그 경로를 지난 장치만 항목을 갖는다.
    )

    # 개구부 평균 개도(직전 명령 기준)를 ctx 에 주입 → 배기팬 압력 모델이 사용.
    # 덕트 없는 벽면 배기팬은 창이 열려 있으면 압력차가 안 생겨 무력하다.
    _op_aps = [state.prev_commands.get(p.actuator_id, 0.0)
               for p in profiles if getattr(p, 'kind', '') == 'opening']
    ctx['vent_open_frac'] = (sum(_op_aps) / len(_op_aps) / 100.0) if _op_aps else 0.0
    # 팬이 바꾸는 공기(시간당 횟수) — CO₂ 주입 보존율이 창과 함께 센다. 창 개도만 보면 창이 닫힌 채
    # 팬이 도는 동안에도 주입기가 돈다(`effect_functions.co2_retention`).
    ctx['fan_ach'] = fan_ach_total(profiles, state.prev_commands)

    # ── 1. Manual-lock handling + live_effect computation (C2) ───────────────
    for p in profiles:
        if p.manual_lock.is_active():
            commands[p.actuator_id] = ActuatorCommand(
                value=p.manual_lock.manual_value,
                reason=REASON_MANUAL_OVERRIDE,
            )
            _log_cmd(unique_id, p.actuator_id, a_idx, p.manual_lock.manual_value,
                     REASON_MANUAL_OVERRIDE)
            continue

        p.live_effect = {
            var: p.effect_model[var](ctx, 100.0, p)   # G3: pass profile
            for var in p.effect_model
        }

    available = [p for p in profiles if p.actuator_id not in commands]

    # ── 2. Hysteresis 텔레메트리 (active_vars) ────────────────────────────────
    for var in situation.deviation_native:
        tgt = situation.target.get(var)
        if tgt is None:
            continue
        residual = situation.deviation_native[var]
        was_active = new_state.active_vars.get(var, False)
        thr = tgt.tolerance * (0.5 if was_active else 1.0)
        new_state.active_vars[var] = abs(residual) >= thr

    # ── P5-2: NATURAL 변수는 제어 대상에서 제외 (능동 권한 없음) ────────────────
    authority = getattr(situation, 'authority', {})
    natural_vars = {
        v for v in situation.deviation_native
        if authority and is_natural_var(authority, v)
    }

    # ── 2.5~2.6. 파킹·제자리 판정 — `decide_parking` 한 곳에서(MPC 도 같은 것을 읽는다)
    # 그림자 계산(`unique_id=''` — 제어 기준 비교 등)은 판정 로그를 남기지 않는다.
    # 남기면 본 계산과 다른 기준의 인내 시간이 매 사이클 "판정이 풀렸습니다(N분
    # 지속)" 로 찍힌다(2026-09-26 리플레이에서 1분마다 N 이 1씩 늘며 반복).
    ctx['_t_ceiling_active_prev'] = bool(getattr(state, 't_ceiling_active', False))
    ctx['_futile_prev'] = set(getattr(state, 'futile_active', None) or ())
    ctx['_futile_s_prev'] = dict(getattr(state, 'futile_s', None) or {})
    _pk = decide_parking(available, situation, ctx, cycle_sec,
                         state.prev_commands,
                         getattr(state, 'vent_first_held_s', 0.0) or 0.0,
                         log=bool(unique_id),
                         humid_prev=bool(getattr(state, 'humid_zone', False)),
                         purge_prev=getattr(state, 'purge', None))
    new_state.vent_first_held_s = _pk.vent_first_held_s
    new_state.humid_zone = _pk.humid_zone
    new_state.purge = _pk.purge_state
    purge_ids, purge_pct = _pk.purge_ids, _pk.purge_pct
    humid_parked = _pk.humid_parked
    humid_cold = _pk.humid_cold
    humid_cap_ids = _pk.humid_cap_ids
    new_state.t_ceiling_active = _pk.t_ceiling is not None
    new_state.futile_active = set(_pk.futile_raw)
    new_state.futile_s = dict(_pk.futile_s)
    futile_dwell_ids = _pk.futile_dwell_ids
    park_ids = _pk.park_ids
    night_parked = _pk.night_parked
    opposing_ids = _pk.opposing_ids
    hold_ids = _pk.hold_ids
    ceiling_ids = _pk.ceiling_ids
    day_open_ids = _pk.day_open_ids
    vent_credit = _pk.vent_credit
    t_ceiling = _pk.t_ceiling
    heat_open_ids = _pk.heat_open_ids
    heat_closed_ids = _pk.heat_closed_ids
    heat_fog_blocked_ids = _pk.heat_fog_blocked_ids
    heat_floor_ids = _pk.heat_floor_ids
    heat_floor_pct = _pk.heat_floor_pct
    water_blocked_ids = _pk.water_blocked_ids
    taper_ids = _pk.taper_ids
    solar_floor_ids, solar_floor_pct = _pk.solar_floor_ids, _pk.solar_floor_pct
    # 의심 액추에이터(`actuator_feedback`) — 부하 분담에서 빼고 제자리에 둔다. 판정은 피드백
    # 레지스트리가 하고(사이클이 ctx 로 싣는다), 여기서는 결론만 읽는다.
    suspect_ids = set(ctx.get('suspected_ids') or ()) & valid_ids
    vent_strength: Dict[str, float] = {}  # 환기 장치의 '명령된 효과' = g × 직전 명령(%)/100

    # ── 2.7. 강우·풍속을 잃었으면 → **더 열지 않음**(ceiling, 2026-09-19) ──────
    # 2.6 과 같은 원칙의 짝이다(`docs/design/sensor-freshness-and-control-
    # cadence.md` 규칙 A). 온습도는 마지막 실측으로 계속 판단할 수 있지만,
    # 오래된 "비 안 옴"·"바람 없음" 은 **여는 근거가 못 된다** — 10분 전 맑음을
    # 믿고 열면 그 사이 시작된 비가 들이친다. 닫는 쪽은 그 위험이 없으므로 PI
    # 판단대로 둔다. 마지막 값이 위험이었으면 여기 오지 않는다 — 안전 게이트가
    # 그 값으로 계속 닫는다(래치).
    #
    # 두 층이 서로 다른 답을 내던 것이 이것으로 하나가 된다: 온습도까지 지어낸
    # 것이면 2.6 이 이기고(제자리), 아니면 제자리 또는 닫기다. 어느 쪽도 모른다는
    # 이유로 창을 **열거나 닫지** 않는다.
    #
    # ⚠ **적분.** 상한에 걸린 동안 PI 는 계속 "더 열어라" 를 낸다. 적분을 그대로
    #   두면 사이클마다 감겨, 값이 돌아오는 순간 창이 한 번에 튄다(이 파일의
    #   '속도에 막힌 몫' 되먹임 주석과 같은 사고). 그래서 걸린 사이클에는 적분을
    #   **쌓지 않고**(조건부 적분) 실제로 서 있는 개도를 넘지 않게 한다. 풀린
    #   뒤에는 막히기 전의 PI 가 그대로 이어진다(bumpless — 테스트
    #   `test_outdoor_unknown_consistency::TestIntegralUnderCeiling`).
    #
    # ⚠ 명령을 coordinate() **밖에서** 자르지 말 것. 예전 EXT_EXP 가 그렇게
    #   했고(개구부 0 강제), 적분은 자기 명령이 나간 줄 알았다.
    ceiling_ids -= hold_ids
    if ceiling_ids:
        logger.debug(
            '강우·풍속 모름 — 개구부 %d개 더 열지 않음: %s',
            len(ceiling_ids), sorted(i[:8] for i in ceiling_ids))
    # 강우 단계 제한(근거 52) — 측창 상한·약한 예보 비의 천창 상한(30 %). 실외 모름
    # (제자리)이 이긴다 — 그쪽은 이미 움직이지 않는다.
    # 숫자 상한은 제자리(2.6) 중에도 건다 — 마지막 실측이 비·강풍이었으면 그 값으로 닫는 게 맞고
    # (규칙 A: 오래된 '비 옴' 은 닫는 근거다), 제자리가 상한 위의 개도를 붙들면 안 된다. 상한이 None
    # ("더 열지 않음")이면 제자리와 같아 달라지는 것이 없다.
    rain_caps = dict(rain_vent_caps(ctx, profiles))
    # 상한마다 근거 — 52(비) | 55(강풍 1단계). 같은 상한 장치를 쓴다(`safety_gates._merge_vent_caps`).
    cap_reasons = ctx.get('vent_open_cap_reasons') or {}

    # ── 2.8. 실내 측정이 없으면 → **제자리 유지**(2026-09-20) ─────────────────
    # 2.6 과 같은 원칙의 실내판이다. 실외를 모르면 창을 움직일 근거가 없듯,
    # 실내를 모르면 **어떤 장치도** 움직일 근거가 없다 — 편차를 잴 수가 없다.
    #
    # 예전에는 없는 실내값이 0 으로 채워져(`situation.assess`) 편차가 온도
    # −22 °C · 습도 −60 % 로 서고 난방기·분무가 근거 1(주작용)로 100 % 까지
    # 올라갔다. 지금은 그 값이 None 이라 편차가 서지 않고 효과 모델도 구동력
    # 0 을 신고하므로, 그대로 두면 **무구배 완화 경로**로 떨어져 safe_default
    # 로 수렴한다 — 그것은 개구부를 닫고 스크린을 걷는 **결정**이다. 근거가
    # 없다는 이유로 장비를 움직이지 않는다(2.6 주석과 같은 판단).
    #
    # ⚠ 판정은 "이 장치가 미는 축 중 하나라도 잴 수 없다" 가 **아니다.** 그러면
    #   습도 센서 하나가 끊긴 날 개구부까지 멈춰 더위에 창이 잠긴다. 잴 수 있는
    #   축이 하나라도 남아 구동력이 서면(den > 0) 그쪽으로 정상 제어한다 —
    #   여기 걸리는 것은 **남은 근거가 하나도 없는** 장치뿐이다.
    # ⚠ 파킹(2.5)이 이긴다. 그쪽은 근거가 있는 결정이고 이쪽은 근거의 부재다.
    unmeasured = set(ctx.get('unmeasured') or ())
    blind_ids: set = set()
    if unmeasured:
        blind_ids = {p.actuator_id for p in available
                     if set(p.effect_model or {}) & unmeasured} - park_ids
        if blind_ids:
            # 여기 담기는 것은 **후보**다 — 다른 축이 남아 구동력이 서면 그
            # 장치는 아래에서 정상 제어로 간다. 실제로 선 장치는 근거 21 로
            # 남는다(명령 로그).
            logger.debug(
                '실내 측정 없음(%s) — 그 축을 다루는 %d개: %s',
                ','.join(sorted(unmeasured)), len(blind_ids),
                sorted(i[:8] for i in blind_ids))

    # ── 3. Per-actuator position-form PI (다목적 결합 drive) ───────────────────
    # accumulated: 이미 확정된 명령들이 만들 **부호 있는 물리 변화량**(native).
    # 부호는 물리 방향 그대로다('↑'=+, '↓'=−, 아래 축적부 참조). 따라서 잔여
    # 편차는 deviation **+** accumulated 다 — 편차가 current−target 이고
    # accumulated 가 current 에 더해질 변화량이므로, 확정 후 예상 편차는
    # (current + accumulated) − target 이다.
    #
    # **도메인마다 따로 쌓는다**(ACTUATOR_DOMAIN 주석 참조). 창의 기여는 창끼리만
    # 보고, 냉방·가습은 그것을 아예 모른다 — 한 장비의 오작동이 남을 거꾸로
    # 켜는 경로를 구조적으로 없앤다.
    accumulated: Dict[str, Dict[str, float]] = {
        dom: {var: 0.0 for var in situation.deviation_native}
        for dom in set(ACTUATOR_DOMAIN.values()) | {DEFAULT_DOMAIN}
    }

    # 저렴한 액추에이터부터 확정 → 이후 것들은 잔여 편차를 보고 적게 동작(부하분담).
    order = sorted(available, key=lambda p: p.cost_fn(ctx, 100.0))

    # ── tier 그룹화: 비용이 동률인 액추에이터들은 같은 잔여편차 스냅숏을 보고 계산한다.
    #
    # 배경(aot-005 실사례, 2026-09): 같은 kind 의 천창 2개는 _build_cost_fn 에서
    # base_cost=5.0 고정이라 cost_fn 값이 항상 동일하다. 정렬 후 순차 처리하면
    # 먼저 처리된 천창의 기여가 accum 에 즉시 반영되어 뒤에 오는 천창은 잔여편차가
    # 거의 0 인 "평형 근방" 으로 진입해 0% 에 고착된다. 처리 순서가 매 사이클
    # 안정정렬로 고정되므로 자기수정 메커니즘 없이 0%/100% 비대칭이 영속된다.
    #
    # 해법: 비용 동률 묶음(tier) 안에서는 **묶음 시작 전 accum 스냅숏**을 공통으로
    # 사용한다. 그래야 같은 kind 의 두 천창이 동일한 잔여편차를 보고 동일한
    # e_norm 을 계산해 대칭적 명령으로 수렴한다. 묶음 전체 처리가 끝난 뒤에만
    # 각 멤버의 물리효과를 accum 에 한꺼번에 반영한다.
    #
    # 서로 다른 비용의 묶음 사이 순서(저비용→고비용)는 그대로이므로
    # "환기 먼저, 부족하면 냉난방" 동작은 변경 없다.
    #
    # 동률 판정: 같은 kind 면 cost_fn 이 수치상 완전히 같지만 부동소수점 연산
    # 경로가 달라질 수 있는 미래를 대비해 math.isclose 로 방어한다.

    def _cost_key(p: 'ActuatorProfile') -> float:
        return p.cost_fn(ctx, 100.0)

    # order 를 비용 동률 묶음(tier) 리스트로 분할.
    # 예: [cost=5, cost=5, cost=9] → [[p0,p1], [p2]]
    tiers: list = []
    for p in order:
        c = _cost_key(p)
        if tiers and math.isclose(c, _cost_key(tiers[-1][-1]), rel_tol=1e-9):
            tiers[-1].append(p)
        else:
            tiers.append([p])

    for tier in tiers:
        # ── 묶음 시작 전 accum 스냅숏 — 모든 도메인 × 변수를 얕은 복사로 확보.
        # 묶음 안에서 순서대로 갱신하지 않으므로 모든 멤버가 같은 잔여편차를 본다.
        accum_snapshot: Dict[str, Dict[str, float]] = {
            dom: dict(dv) for dom, dv in accumulated.items()
        }

        # 묶음 처리 중 각 멤버의 물리효과를 임시로 모아 두었다가 묶음 끝에 반영.
        tier_effect_deltas: Dict[str, Dict[str, float]] = {}

        for p in tier:
            accum = accum_snapshot[domain_of(p)]  # 스냅숏 읽기 전용
            _is_hvac = ACTUATOR_DOMAIN.get(getattr(p, 'kind', '')) == 'hvac'
            prev_val = state.prev_commands.get(p.actuator_id, 0.0)
            I = new_state.integral.get(p.actuator_id, 0.0)
            if p.actuator_id in suspect_ids:
                # ── 의심 액추에이터: 제자리에 둔다(구동하지 않는다) ─────────────────────────
                # 고장일 수 있는 장치에 계속 명령을 쌓으면 적분이 와인드업하고, 그 장치가 하고 있다고
                # 믿는 몫이 부하 분담 장부에 남아 나머지가 덜 일한다. 그래서 **장부에 아무것도
                # 올리지 않고**(tier_effect_deltas 를 건드리지 않는다 — 나머지가 그 몫을 이어받는다)
                # 직전 위치를 그대로 낸다. 슬루·전달 비율·min-ON 도 건너뛴다 — '움직이지 않는다' 가 곧
                # 이 명령이다. 적분도 그대로 둔다: 회복해 돌아오면 그 자리에서 이어 간다.
                # 이 명령은 디스패치에도 나가지 않는다(`_cycle_mixin` — 근거 42 는 전송 제외).
                _held = _clamp(prev_val, 0.0, 100.0)
                for _d in (new_state.stall_s, new_state.stall_ref,
                           new_state.nofx_s, new_state.nofx_ref):
                    _d.pop(p.actuator_id, None)
                commands[p.actuator_id] = ActuatorCommand(
                    value=p.cmd_constraints.map_aperture_to_motor(_held),
                    reason=REASON_ACTUATOR_SUSPECT, aperture=_held, slewed=_held)
                _log_cmd(unique_id, p.actuator_id, a_idx, _held, REASON_ACTUATOR_SUSPECT)
                continue
            kp = p.gains.get('kp', POS_KP)
            ki = p.gains.get('ki', POS_KI)
            _freeze_lower = False   # 아래쪽 레일 갓 포화 — 이번 사이클 적분 동결

            # ── 결합 drive: 이 액추에이터가 제어 가능한 모든 변수의 정규화 drive 를
            #    priority × 유효도(effect magnitude)로 가중합한다. 이는 가중 오차제곱합의
            #    음의 기울기(gradient-descent) 방향으로, "냉방 개방 이득 vs 습도 악화"
            #    같은 다목적 트레이드오프를 단일 평형으로 수렴시킨다.
            #    (기존 primary-var 선택 + binary conflict 의 toggle limit-cycle 제거)
            #    effect 방향이 외기차 부호에 따라 뒤집히므로(외기가 더 더우면 개방=가온),
            #    역방향 개방도 자동 음(─) drive 로 차단된다.
            #    주의: g_v 는 변수 간 '상대' 가중치만 정한다. e_norm=num/den 은 정규화되어
            #    절대 유효도를 반영하지 못하므로(무구배에도 편차 비례로 명령 → 헛돎),
            #    아래에서 max_g(절대 유효도)로 권한 게이트를 따로 건다.
            # 변수별 항 (v, w, e, g, score) — 온도 상한이 하드 임계에서 맞서는
            # 항을 뺄 수 있도록 먼저 모으고 나중에 합친다.
            terms: list = []
            for v, eff in p.live_effect.items():
                if eff.direction not in ('↑', '↓'):
                    continue
                if v in natural_vars or v not in situation.deviation_native:
                    continue
                t = situation.target.get(v)
                if t is None or t.tolerance <= 0:
                    continue
                # 부호 주의: 빼면 부하'분담'이 부하'증폭'이 된다. 앞 장비가 −3°C 를
                # 확정했는데 편차 +5 에서 5−(−3)=8 을 보면 뒤 장비는 혼자일 때보다
                # 더 세게 돈다. 실제로 2026-08-20 로컬 육묘장에서 분무 64.9%(모델상
                # −29.6°C)가 냉방기에 +29.6°C 로 넘어가 편차 0 인데도 냉방 100%,
                # 난방 0% 로 고착됐다. 위 주석의 "적게 동작"과도 반대였다.
                residual_v  = situation.deviation_native[v] + accum.get(v, 0.0)
                if _is_hvac:
                    # 실외가 대신 해 주는 몫만큼 냉난방의 짐을 던다. 부호는 편차를
                    # **0 쪽으로** 옮기는 방향이고(`_ventilation_credit` 이 need 를
                    # 넘지 않게 잘라 놓는다), 그래서 부호가 뒤집힐 수 없다.
                    # ⚠ 환기 자신에게는 적용하지 않는다 — 자기가 할 일을 자기
                    #   편차에서 빼면 창이 열리지 않는다.
                    residual_v += vent_credit.get(v, 0.0)
                effect_sign = 1.0 if eff.direction == '↑' else -1.0
                pband_v     = max(PBAND_MULT * t.tolerance, 1e-9)
                e_v         = (-residual_v * effect_sign) / pband_v    # + = 더 열기
                g_v         = eff.magnitude_native / pband_v           # 유효도(구동력)
                w_v         = max(t.priority, 1e-6) * g_v
                score = abs(residual_v) / t.tolerance * t.priority
                terms.append((v, w_v, e_v, g_v, score))

            # ── 온도 상한 항 (위 `_temperature_ceiling` 주석 참조) ────────────
            _dom_p = ACTUATOR_DOMAIN.get(getattr(p, 'kind', ''))
            # 온도가 제어목표여도 보호 중에는 `_temperature_ceiling` 이 항을 낸다(그 주석).
            if t_ceiling is not None:
                _excess, _hard = t_ceiling
                _eff_t = p.live_effect.get('temperature')
                _allowed = (_T_CEILING_HARD_DOMAINS if _hard else _T_CEILING_DOMAINS)
                if SP.shade_ceiling_allowed(ctx.get('screen'), p):
                    # 광 상태가 허락한 차광막(FREE, 또는 창·분무를 다 쓴 TRADE)도 상한 항을
                    # 받는다 — 판정은 `screen_policy` 한 곳. 보온커튼은 아니다.
                    _allowed = _allowed | {'screen'}
                # 보호(단계 1)의 하드 항은 습윤형 분무를 몰지 않는다(`_temperature_ceiling`).
                _hp_skip = (_hard and getattr(p, 'kind', '') == 'fogger'
                            and bool(ctx.get('_t_ceiling_hp_only'))
                            and p.actuator_id not in getattr(
                                ctx.get('heat_protect'), 'cooling_fog_ids', frozenset()))
                if (not _hp_skip and _dom_p in _allowed and _eff_t is not None
                        and _eff_t.direction in ('↑', '↓')
                        and _eff_t.magnitude_native > 0.0):
                    _sign_t = 1.0 if _eff_t.direction == '↑' else -1.0
                    _pband_t = PBAND_MULT * T_CEILING_TOL
                    # 초과분이 곧 편차다(측정 − 선). 같은 도메인이 이미 확정한
                    # 냉각 몫은 부하분담으로 뺀다.
                    _resid_t = _excess + accum.get('temperature', 0.0)
                    _e_t = (-_resid_t * _sign_t) / _pband_t
                    _g_t = _eff_t.magnitude_native / _pband_t
                    _pri_t = T_CEILING_PRIORITY * (1.0 + _excess / T_CEILING_TOL)
                    if not _hard:
                        # 선에 막 닿았을 때 가중치가 0 에서 **연속으로** 커지게 한다.
                        # 예전에는 초과 0⁺ 에서 바로 우선순위 1 로 들어와, 오차가 0 에
                        # 가까운 이 항이 결합 오차(가중 평균)를 한 사이클에 절반쯤으로
                        # 희석했다 — 실내가 선 근처를 오르내리면 창이 사이클마다 계단으로
                        # 오르내렸다(2026-09-24 영양 천창, 14:05 39.7 → 19.7 %). 허용오차
                        # 1개 이상 넘으면 종전과 같다. 하드 상한은 그대로(안전).
                        _pri_t *= min(1.0, _excess / T_CEILING_TOL)
                    terms.append(('temperature', _pri_t * _g_t, _e_t, _g_t,
                                  _excess / T_CEILING_TOL * _pri_t + 1e6 * _hard))
                    if _hard and _e_t > 0.0:
                        # 하드 상한 — 식히는 방향과 맞서는 항을 뺀다.
                        terms = [tm for tm in terms
                                 if tm[0] == 'temperature' or tm[2] >= 0.0]

            num = sum(tm[1] * tm[2] for tm in terms)
            den = sum(tm[1] for tm in terms)
            max_g = max((tm[3] for tm in terms), default=0.0)
            primary_var = (max(terms, key=lambda tm: tm[4])[0] if terms else None)

            # 유효도 문턱은 이력을 갖는다(GRADIENT_EXIT_FRAC 주석). 구동력이 있던
            # 장치는 문턱의 절반 아래로 내려가야 '없음' 이 되고, 없던 장치는 문턱을
            # 넘어야 '있음' 이 된다 — 문턱 근처의 흔들림이 판정을 뒤집지 못한다.
            _was_active = bool(
                (getattr(state, 'gradient_active', None) or {}).get(p.actuator_id))
            _g_floor = G_MIN_EFFECT * (GRADIENT_EXIT_FRAC if _was_active else 1.0)
            weak_gradient = den <= 1e-12 or max_g < _g_floor
            new_state.gradient_active[p.actuator_id] = not weak_gradient
            if getattr(p, 'kind', '') in VENTILATING_KINDS:
                vent_strength[p.actuator_id] = (
                    max_g * max(0.0, float(prev_val or 0.0)) / 100.0)
            # '열어도 소용없음' 누적은 **연속한** 사이클에서만 이어진다 — 일반 PI 분기를
            # 지나지 않은 사이클(파킹·제자리·데드존)은 여기서 지워, 돌아왔을 때 옛 누적으로
            # 곧장 멈추지 않게 한다(아래 일반 분기가 다시 센다).
            new_state.stall_s.pop(p.actuator_id, None)
            new_state.stall_ref.pop(p.actuator_id, None)
            new_state.nofx_s.pop(p.actuator_id, None)
            new_state.nofx_ref.pop(p.actuator_id, None)

            if p.actuator_id in day_open_ids:
                # 낮 — 보온커튼은 걷어 둔다(`decide_parking` 주석). 적분도 그 자리로
                # 맞춘다 — 해가 진 뒤 코디네이터가 '걷혀 있다' 에서 출발해야 한다.
                # 위치를 잡는 커튼은 아침에 단계로 걷는다(`screen_policy._curtain_ramp`,
                # 근거 47) — 적분도 그 단계 값이다.
                cmd_raw, reason = SP.curtain_day_command(ctx.get('screen'), p.actuator_id)
                I = cmd_raw
            elif p.actuator_id in hold_ids:
                # 실외 근거 없음 → **제자리**. 감쇠하지 않는다(그건 닫는 것이다).
                # 적분도 그대로 둔다 — 모르는 동안 '평형 개도 기억'을 흔들면 실외가
                # 돌아왔을 때 엉뚱한 자리에서 다시 출발한다.
                # 제자리는 **실제 개도**다 — 전달 비율로 나눠 낸다(`hold_command`).
                cmd_raw = hold_command(p, prev_val)
                reason = REASON_NO_OUTDOOR_DATA
                # 단 **닫는 쪽은 한다**(근거 58, 모듈 상수 주석) — 야간 파킹은 감쇠, 해 진 뒤
                # 작은 열림은 0. 열 근거가 없다는 것이 닫을 수 없다는 뜻은 아니다.
                _oc = outage_close_command(_pk, p, prev_val)
                if _oc is not None:
                    cmd_raw, reason = _oc
                    I = cmd_raw
            elif p.actuator_id in futile_dwell_ids:
                # 환기 무익 판정이 막 섰다 — FUTILE_DWELL_S 동안 **제자리**. 적분도 그대로 둔다.
                cmd_raw = hold_command(p, prev_val)
                reason = REASON_NO_GRADIENT
            elif p.actuator_id in blind_ids and weak_gradient:
                # 실내 측정 없음(2.8) → 제자리. hold_ids 와 같은 처리다 —
                # 감쇠하지 않고 적분도 그대로 둔다(모르는 동안 '평형 개도
                # 기억' 을 흔들면 센서가 돌아왔을 때 엉뚱한 자리에서 출발한다).
                # 제자리는 **실제 개도**다 — 전달 비율로 나눠 낸다(`hold_command`, 김제 10/14 20 → 0 %).
                cmd_raw = hold_command(p, prev_val)
                reason = REASON_NO_MEASUREMENT
                # 단 맑은 낮이면 실외·해로 세운 작은 하한까지 열고, 해가 진 뒤에는 그만큼을 닫는다(근거 60,
                # `decide_parking` 2.8b). 적분은 그 자리에 맞춘다 — 실내가 돌아오면 PI 가 거기서 이어 간다.
                _bv = blind_vent_command(_pk, p, prev_val)
                if _bv is not None:
                    cmd_raw, reason = _bv
                    I = cmd_raw
            elif weak_gradient or p.actuator_id in park_ids:
                # 제어 가능 변수 없음 OR 유효 구동력 없음(무구배 환기 등) OR 파킹 대상
                # (환기 무익 / 냉난방 연동 — 2.5 참조) → 안전 idle
                # 위치(safe_default)로 부드럽게 수렴하고 적분을 풀어준다. 100% 가동해도
                # 효과 없는 액추에이터를 편차 비례로 켜 두면 성과 없이 작동시간만 늘고
                # 적분이 와인드업한다. safe_default 기준으로 감쇠하므로 개구부(sd=0)는
                # 닫힘, 스크린(보온커튼·차광막 sd=100)은 걷힘으로 수렴한다.
                #
                # 주의: 여기서 반드시 prev_val(직전 실제 dispatch 위치)에서 감쇠해야
                # 한다. I(적분)에서 감쇠하면 안 된다 — I 는 포화(saturation) 중
                # anti-windup back-calculation(아래 else 분기, L266~267)에 의해
                # dispatch 값과 무관하게 낮아질 수 있다. 예: 스크린이 며칠째 100%로
                # 열려 있어도(강한 냉방 수요로 P+I 가 100을 크게 초과) I 는 그 이면에서
                # 조용히 0 근처까지 깎일 수 있고, 그 상태에서 갑자기 무구배로 전환되면
                # "표시상 100%였는데 다음 사이클에 40%로 뚝 떨어지는" 것처럼 보이는
                # 명령 급변이 발생한다(2026-07-29 aot-005 폭염 중 보온커튼 오폐쇄 사건의
                # 원인). prev_val 은 dispatch 좌표 그대로이므로 이 괴리가 없다.
                sd = p.safe_default
                if getattr(p, 'kind', '') == 'curtain' and p.actuator_id not in park_ids:
                    # 보온커튼은 **제자리**다. safe_default(100 = 걷힘)는 고장·게이트
                    # 때 돌아갈 자리이지 제어 방향이 아니다(데드존 물러남과 같은
                    # 이유, 2026-09-22). 이리로 풀면 밤에 안팎 온도차가 작아지는
                    # 순간 커튼이 걷힌다 — 실측(2026-09-24 영양): 실내 14~18°C·VPD
                    # 목표보다 0.8 낮은 채 밤새 100 %. 한 사이클 풀림이 정확히 40 %
                    # (100 + (0−100)×0.6)로 찍혀 "왜 40 인가" 도 이것이었다.
                    # ⚠ 제자리는 **열 수요가 없을 때만** 맞다. 걷힌 커튼 아래의 작은 안팎 온도차는
                    #   커튼이 지운 것이라 무구배의 근거가 못 된다 — 밤 보온은 아래
                    #   `SP.adjust_pi_command` 가 목표·실외로 판단해 닫는다(근거 49, 2026-10-10 영양:
                    #   실내 9~12 °C 인데 밤새 100 %·근거 15).
                    I = prev_val
                    cmd_raw = _clamp(prev_val, 0.0, 100.0)
                else:
                    I = sd + (prev_val - sd) * RELAX_FACTOR
                    cmd_raw = _clamp(I, 0.0, 100.0)
                # 같은 감쇠 경로를 쓰되 **사유는 나눈다** — 맞서는 짝의 진 쪽은
                # "밀어도 안 움직인다"(무구배)가 아니라 "지금 밀 방향이 아니다"다.
                # 야간 파킹은 사용자가 켠 옵션의 결과다 — 무구배로 뭉치면
                # "왜 밤에 창이 안 열리나" 에 화면이 답할 수 없다.
                if p.actuator_id in water_blocked_ids:
                    # 물이 없다는 사실이 폭염 판정보다 앞이다 — 사람이 할 일(물 채우기)이 보인다.
                    reason = REASON_NO_WATER
                elif p.actuator_id in heat_closed_ids:
                    reason = REASON_HEAT_VENT_HOT_OUTSIDE
                elif p.actuator_id in heat_fog_blocked_ids:
                    reason = REASON_HEAT_FOG_BLOCKED
                elif p.actuator_id in night_parked:
                    reason = REASON_NIGHT_PARKED
                elif p.actuator_id in opposing_ids:
                    reason = REASON_OPPOSING_PARKED
                elif p.actuator_id in humid_cold:
                    reason = REASON_HUMID_COLD
                elif p.actuator_id in humid_parked:
                    reason = REASON_HUMID_NO_RELIEF
                else:
                    reason = REASON_NO_GRADIENT
            else:
                e_norm = num / den
                # ── 열어도 편차가 줄지 않는 창 추적(STALL_AFTER_S 주석) ──────────
                # 유효도가 낮은 환기 장치만 본다. 기준 편차보다 STALL_IMPROVE_FRAC 이상
                # 좁혀지면 "반응이 있다" 로 보고 다시 센다.
                _is_vent = getattr(p, 'kind', '') in VENTILATING_KINDS
                if _is_vent and e_norm > 0.0 and prev_val >= STALL_MIN_OPEN_PCT \
                        and max_g < STALL_G_MAX:
                    new_state.stall_ref[p.actuator_id], new_state.stall_s[p.actuator_id] = \
                        _no_improvement_step(
                            (getattr(state, 'stall_ref', None) or {}).get(p.actuator_id),
                            (getattr(state, 'stall_s', None) or {}).get(p.actuator_id, 0.0),
                            e_norm, cycle_sec)
                else:
                    new_state.stall_ref.pop(p.actuator_id, None)
                    new_state.stall_s.pop(p.actuator_id, None)
                # 같은 판정의 반대 대역 — 세게 열렸고 모델이 효과가 뚜렷하다고 하는데 반응이 없다
                # (`NOFX_AFTER_S` 주석). 실외를 모르거나(지어낸 실외 · 더 열지 않음) 보호가 환기를
                # 열어 둔 창은 편차 때문에 열린 것이 아니므로 센 적이 없다.
                if (_is_vent and e_norm > 0.0 and prev_val >= NOFX_MIN_CMD_PCT
                        and max_g >= STALL_G_MAX
                        and not (ctx.get('external') or {}).get('_ext_synthetic')
                        and p.actuator_id not in ceiling_ids
                        and p.actuator_id not in heat_open_ids):
                    new_state.nofx_ref[p.actuator_id], new_state.nofx_s[p.actuator_id] = \
                        _no_improvement_step(
                            (getattr(state, 'nofx_ref', None) or {}).get(p.actuator_id),
                            (getattr(state, 'nofx_s', None) or {}).get(p.actuator_id, 0.0),
                            e_norm, cycle_sec)
                # 데드존을 분기가 아니라 '빼기'로 적용한다 — 경계에서 P항이 0 으로
                # 연속 수렴하므로 입력이 경계를 넘나들어도 명령 계단이 생기지 않는다.
                # (분기 구현이 만들던 ±kp·hb·100 계단 = 야간 창호 진동의 직접 원인)
                e_eff = math.copysign(
                    max(0.0, abs(e_norm) - HOLD_FRAC / PBAND_MULT), e_norm)
                if e_eff == 0.0:
                    # ── 평형 근방(결합오차 작음) → 적분 동결, 직전 평형 개도 유지
                    #
                    # ⚠ 그런데 **넘어선 채로 얼어붙을 수 있다.** 데드존 안에서는
                    # e_eff=0 이라 구동이 없고, 구동이 없으면 방향 판정도 서지
                    # 않는다 — 그래서 잔여 편차가 부호를 넘어가도 그 순간의 명령이
                    # 그대로 유지되고 근거는 PRIMARY 로 남는다.
                    #
                    # 실측(2026-08-26 영양 육묘장): 낮에 VPD 가 목표보다 높아 냉방기
                    # 적분이 100% 까지 감겼고, VPD 가 목표로 내려와 편차가 −0.0 이
                    # 된 순간 그 100% 가 얼어붙었다. 그 시점의 냉방기는 VPD 를
                    # **내리는** 쪽(모델: vpd ↓0.484)이라 방향이 이미 반대였다.
                    # **목표에 도달했다는 사실이 잘못된 출력을 고정한 것이다.**
                    #
                    # 그래서 데드존 안이라도 부호가 반대면 물러난다. 다만 **한
                    # 사이클의 부호로 판단하지 않는다** — 데드존이 있는 이유가
                    # 센서 잡음이고, 잡음은 매 사이클 부호가 뒤집힌다. 연속으로
                    # 같은 쪽이어야 "넘어갔다" 이고, 한 번이라도 되돌아오면 0 이다.
                    # 읽기는 직전 상태, 쓰기는 새 상태 — 새 상태는 비어서 출발하므로
                    # 이 경로를 안 지난 장치는 자동으로 0 이 된다.
                    if e_norm < 0.0:
                        _n = (state.deadzone_wrong_side or {}).get(
                            p.actuator_id, 0) + 1
                        new_state.deadzone_wrong_side[p.actuator_id] = _n
                    else:
                        _n = 0
                    if _n >= DEADZONE_BACKOFF_CYCLES:
                        # 감쇠율은 파킹과 같은 RELAX_FACTOR 다. 그러나 **향하는 곳은
                        # safe_default 가 아니라 0 이다** — e_norm < 0 은 장치 자기
                        # 기준으로 "명령을 줄여라" 이고, 모든 효과 모델은 명령(개도)에
                        # 비례한다. 창·냉방기는 safe_default 가 0 이라 둘이 같지만,
                        # 보온커튼·차광막은 safe_default 가 100(걷힘)이라 예전에는 과한
                        # 효과를 **더 키우는 쪽**(걷힘)으로 물러났다. safe_default 는
                        # 고장·게이트 때 돌아갈 자리이지 제어 방향이 아니다
                        # (2026-09-22 외부 검토 대조로 확인).
                        I = prev_val * RELAX_FACTOR
                        cmd_raw = _clamp(I, 0.0, 100.0)
                        reason = REASON_DEADZONE_BACKOFF
                    else:
                        cmd_raw = _clamp(I, 0.0, 100.0)
                        reason = REASON_PRIMARY
                else:
                    # ── 방향 전환 시 적분을 실제 개도로 되앉힌다 (PID 컨트롤러 차용)
                    # PID 는 direction='both' 에서 올림↔내림이 뒤집히는 순간
                    # `integrator = 0.0` 으로 지운다. 한쪽에서 쌓은 누적이 반대쪽으로
                    # 넘어가면, 이미 방향이 바뀌었는데도 그 값이 명령을 계속 밀기
                    # 때문이다 — 실측: 냉방기가 I=97.9 를 들고 있어, VPD 를 올려야
                    # 하는 상황으로 바뀐 뒤에도 계속 돌았다.
                    #
                    # ⚠ **0 으로 지우면 안 된다.** 여기서 적분은 PID 의 '누적 오차'가
                    # 아니라 **'기억된 평형 개도(%)'** 다. 0 = "완전히 닫아라" 라서,
                    # 그대로 베끼면 방향이 바뀔 때마다 창이 쾅 닫혔다 다시 열린다.
                    # 같은 뜻을 갖는 조치는 **실제 서 있는 자리로 되앉히는 것**이다:
                    # 옛 방향의 기억은 지우면서 물리적 연속성은 지킨다.
                    _sign = 1 if e_eff > 0 else -1
                    _flipped = new_state.drive_sign.get(p.actuator_id, 0) == -_sign
                    if _flipped:
                        # 뒤집힌 방향은 이어져야 따른다(DRIVE_FLIP_* 주석).
                        _pend = new_state.drive_flip_pending.get(p.actuator_id)
                        if _pend and _pend[0] == _sign:
                            _pend = (_sign, _pend[1] + float(cycle_sec), _pend[2] + 1)
                        else:
                            _pend = (_sign, 0.0, 1)
                        if (_pend[2] < DRIVE_FLIP_MIN_CYCLES
                                or _pend[1] < DRIVE_FLIP_MIN_SEC):
                            new_state.drive_flip_pending[p.actuator_id] = _pend
                            _unsettled = True
                        else:
                            new_state.drive_flip_pending.pop(p.actuator_id, None)
                            I = _clamp(prev_val, 0.0, 100.0)
                            _unsettled = False
                    else:
                        new_state.drive_flip_pending.pop(p.actuator_id, None)
                        _unsettled = False
                    if _unsettled:
                        # 제자리 — 적분도 그대로(옛 방향의 기억을 아직 지우지 않는다).
                        cmd_raw = _clamp(prev_val, 0.0, 100.0)
                        reason = REASON_DIRECTION_UNSETTLED
                    else:
                        new_state.drive_sign[p.actuator_id] = _sign

                        _I_entry = I      # 이번 사이클 누적 전(방향 전환 되앉힘 후)
                        I = _clamp(I + ki * e_eff, 0.0, 100.0)
                        p_term = kp * e_eff * 100.0
                        cmd_unclamped = p_term + I
                        cmd_raw = _clamp(cmd_unclamped, 0.0, 100.0)
                        if cmd_unclamped != cmd_raw:
                            if abs(prev_val - cmd_raw) <= RAIL_EPS:
                                # ── 레일 고착 회복 경로 ────────────────────────────
                                # 직전 dispatch 가 이미 이 레일이다 = 최소 한 사이클
                                # 이상 여기 눌러붙어 있었다. 그 상태의 적분은 '기억된
                                # 평형 개도'가 아니라 **포화 부산물**이라 값에 뜻이 없다.
                                # 실제 개도(cmd_raw) 쪽으로 기하 감쇠시켜 적분이 자기
                                # 정의(=이 액추에이터가 서 있는 자리)를 되찾게 한다.
                                I = cmd_raw + (I - cmd_raw) * RELAX_FACTOR
                            elif cmd_unclamped < 0.0:
                                # ── 아래쪽 레일 갓 포화 — 적분 **동결** (2026-09-19) ──
                                # back-calculation `I −= (u − c)·β` 은 여기서 I 를
                                # **위로** 민다(u < 0). 교과서에서는 P + I 를 레일에
                                # 맞추는 동작이지만, 이 코드의 적분은 '기억된 평형
                                # 개도(%)' 라 그 값은 P 의 거울상일 뿐 뜻이 없다.
                                # P 가 커지면 그대로 드러난다 — 로컬 섀도 실행(하드
                                # 온도 상한, 실외가 더 더워 닫는 중)에서 개도 0 %·10 %
                                # 인 개구부 둘의 적분이 한 사이클에 0→100, 3.53→100
                                # 이 됐다. 상한이 풀린 뒤에도 '조금 더 닫아라' 면
                                # 방향 전환 되앉힘이 돌지 않아 `cmd = P + 100` 이 창을
                                # **연다**. 상한이 아니어도 같은 경로로 추운데 창이
                                # 열린 채 버틴다(합성 폐루프 A/B: IAE 295 → 187).
                                #
                                # 그래서 조건부 적분 — 막힌 방향으로 가는 이번 사이클의
                                # 누적을 버리고, 슬루 되먹임도 걸지 않는다(아래). 적분은
                                # 이 사이클에 들어올 때의 값 그대로다: 포화가 **새로
                                # 더하는 것이 없다.**
                                #
                                # ⚠ '실제 개도로 되앉힘'(I = min(I, 개도))은 고르지
                                # 않았다. 기억된 평형까지 지워서, 강한 외란이 잠깐
                                # 창을 닫았다 풀리면 적분이 0 에서 다시 쌓여야 한다 —
                                # ki 가 사이클당 0.2 % 라 100 사이클 넘게 2.6 °C 벗어난
                                # 채 고착됐다(합성 A/B: IAE 96 → 284, 동결은 105).
                                # 레일에 **계속** 붙어 있으면 레일 회복 경로가 따로
                                # 실제 개도로 감쇠시킨다(위 분기).
                                # ⚠ 위쪽 레일은 종전 back-calculation 그대로다. 같은
                                # A/B 에서 위쪽까지 동결하면 짧은 고온 스파이크 뒤
                                # 회복이 나빠졌다(IAE 108 → 138).
                                I = _I_entry
                                _freeze_lower = True
                            else:
                                # 위쪽 레일 갓 포화 — 표준 back-calculation(포화분만큼
                                # 되돌림). 첫 사이클의 빠른 anti-windup 은 그대로 둔다.
                                I = _clamp(I - (cmd_unclamped - cmd_raw) * AW_BETA,
                                           0.0, 100.0)
                        reason = REASON_PRIMARY

            if p.actuator_id in humid_cap_ids and cmd_raw > HR.CAP_PCT:
                # 과습 구간의 열림 상한(2.65). 습기를 빼는 것이 목적이지 환기로 온도·VPD 를
                # 맞추는 것이 아니다. 적분도 상한에 묶는다 — 묶지 않으면 상한에 걸린 채
                # 사이클마다 감겨, 구간을 나가는 순간 창이 한 번에 튄다(ceiling 과 같은 사고).
                cmd_raw = HR.CAP_PCT
                I = min(I, HR.CAP_PCT)
                if reason == REASON_PRIMARY:
                    reason = REASON_HUMID_CAPPED

            if p.actuator_id in solar_floor_ids and cmd_raw < solar_floor_pct:
                # 낮 일사 부하 환기 하한(2.9, `solar_vent`) — VPD·습도·무구배가 닫으라고 해도 일사 열을
                # 뺄 만큼은 연다. 과습 상한 **뒤**라 그것도 이긴다. 적분도 하한에 묶는다(극한 고온 보호의
                # 하한과 같은 방식) — 하한이 풀리면 PI 가 그 자리에서 이어 간다(계단 없음).
                cmd_raw = solar_floor_pct
                I = max(I, solar_floor_pct)
                reason = REASON_SOLAR_VENT_FLOOR

            if p.actuator_id in purge_ids and cmd_raw < purge_pct:
                # 아침 습기 빼기 하한(2.95, `humid_regime.morning_purge`) — 27·24 파킹·무구배가 닫으라고
                # 해도 해가 집을 데우는 동안 습기를 뺄 만큼은 연다. 과습 상한(30 %)보다 작아 그것과
                # 부딪치지 않고, 일사 하한이 더 크게 섰으면 그쪽(51)이 이긴 채 남는다. 적분도 하한에
                # 묶는다 — 풀릴 때 PI 가 그 자리에서 이어 간다(계단 없음).
                cmd_raw = purge_pct
                I = max(I, purge_pct)
                reason = REASON_MORNING_PURGE

            if p.actuator_id in heat_floor_ids and cmd_raw < heat_floor_pct:
                # 극한 고온 보호의 환기 하한(2.7) — 바깥이 더 더워 닫는 중이어도 분무가
                # 돌았으면 습기를 뺄 만큼은 연다. 과습 상한과 같은 방식으로 적분도
                # 하한에 묶는다 — 묶지 않으면 하한이 풀리는 순간 창이 한 번에 닫힌다.
                cmd_raw = heat_floor_pct
                I = max(I, heat_floor_pct)

            if p.actuator_id in taper_ids and cmd_raw > hold_command(p, prev_val) + 1e-9:
                # 야간 파킹 직전(2.8) — 곧 닫힐 창을 더 열지 않는다. 직전 개도에 묶고, 적분은
                # 이번 사이클에 쌓은 몫을 버려 **그 자리를 넘지 않게** 한다(조건부 적분 — 더
                # 열라는 요구는 실행되지 않았으므로 배우지 않는다. `ceiling_ids` 와 같은 원칙).
                # 전달 비율(풍향 가중치)이 곱해지므로 요구는 그만큼 나눠 낸다 — 안 나누면 비율만큼
                # 사이클마다 닫혀 '제자리'가 감쇠가 된다(온도 상한 유지와 같은 이유).
                cmd_raw = hold_command(p, prev_val)
                I = min(new_state.integral.get(p.actuator_id, I), cmd_raw)
                reason = REASON_PREPARK_HOLD

            # 보호 중 열어도 되는 창은 '열어도 반응 없음' 으로 멈추지 않는다 — 바깥이 더
            # 시원한 동안의 환기는 편차가 줄든 말든 열·수분 스트레스를 던다(2.7).
            # 일사 하한이 선 창도 같다 — 그 개도는 편차가 아니라 일사 열 때문이다(2.9).
            _stalled = (new_state.stall_s.get(p.actuator_id, 0.0) >= STALL_AFTER_S
                        and p.actuator_id not in heat_open_ids
                        and p.actuator_id not in solar_floor_ids
                        and p.actuator_id not in purge_ids)
            if _stalled and cmd_raw > hold_command(p, prev_val) + 1e-9:
                # 열어도 편차가 줄지 않는다(STALL_AFTER_S). 더 열지 않고 배운 것도 없다 —
                # 그 사이 PI 가 본 편차는 실행되지 않은 요구다(ceiling 과 같은 원칙).
                # '더 열지 않음' 은 실제 개도 기준이다 — 전달 비율로 나눠 낸다(`hold_command`).
                cmd_raw = hold_command(p, prev_val)
                I = min(new_state.integral.get(p.actuator_id, I), cmd_raw)
                reason = REASON_NO_RESPONSE
            if unique_id and _stalled != (
                    (getattr(state, 'stall_s', None) or {}).get(
                        p.actuator_id, 0.0) >= STALL_AFTER_S):
                # 바뀔 때만 한 번 — 매 사이클 찍으면 읽어야 할 로그를 밀어낸다.
                logger.error(
                    '창 %s: %s', p.actuator_id[:8],
                    '열어도 편차가 줄지 않아 더 열지 않습니다(%d분째)'
                    % int(new_state.stall_s.get(p.actuator_id, 0.0) // 60)
                    if _stalled else '편차가 다시 좁혀져 제어를 이어 갑니다')

            if (t_ceiling is not None and t_ceiling[0] <= 0.0 and not t_ceiling[1]
                    and cmd_raw < prev_val and _dom_p in _T_CEILING_DOMAINS
                    and p.actuator_id not in park_ids):
                # (제자리 경로들 — 실외 모름·무익 대기·실내 모름 — 은 이미 prev_val 이라
                #  여기 오지 않는다. `blind_ids` 는 후보 집합이라 조건으로 쓰면 안 된다:
                #  CO₂ 측정이 없는 시설에서는 모든 창이 후보다.)
                # 온도 상한 유지 구간(T_CEILING_HOLD_BAND) — 식히는 창은 닫는 쪽으로 가지
                # 않는다. 적분도 그 자리로 되앉힌다: 다시 선을 넘으면 0 이 아니라 지금
                # 개도에서 P 만큼 더 연다. 파킹(야간·연동·보호의 '바깥이 더 덥다' 등)은 이긴다.
                _eff_hold = p.live_effect.get('temperature')
                if (_eff_hold is not None and _eff_hold.direction == '↓'
                        and _eff_hold.magnitude_native > 0.0):
                    # 제자리는 **실제 개도**다. 전달 비율(풍향 가중치 등, `finalize_command`)이
                    # 곱해지므로 요구는 그만큼 나눠 낸다 — 직전 개도를 그대로 내면 비율이
                    # 1 미만인 동안 사이클마다 비율만큼 닫혀(실측 시뮬레이터: 20 → 13.6 →
                    # 10 → 7 %) 유지가 감쇠가 된다.
                    cmd_raw = hold_command(p, prev_val)
                    I = cmd_raw
                    reason = REASON_PRIMARY
                    primary_var = 'temperature'

            if p.actuator_id in ceiling_ids and cmd_raw > hold_command(p, prev_val) + 1e-9:
                # 더 열지 않음(2.7). 근거는 16(판단할 근거 없음, 제자리) —
                # 화면 문구 "실외 값이 돌아올 때까지 제자리" 가 그대로 맞다.
                #
                # 적분은 **이번 사이클에 쌓은 것을 버리고**(조건부 적분) 실제
                # 개도를 넘지 않게 한다. `min(I, 개도)` 만으로는 부족했다 — 적분이
                # 개도 아래에 있으면 막힌 동안에도 조금씩 계속 쌓여(실측: 55.002
                # → 55.007/사이클), 긴 두절 끝에 개도까지 차오른 채 풀리면 그
                # 몫이 한 번에 창을 민다. 막힌 방향으로는 **아무것도 배우지
                # 않는다**가 맞다 — 그 사이 PI 가 본 편차는 실행되지 않은 요구다.
                # '더 열지 않음' 은 실제 개도 기준이다 — 전달 비율로 나눠 낸다(`hold_command`).
                cmd_raw = hold_command(p, prev_val)
                I = min(new_state.integral.get(p.actuator_id, I), cmd_raw)
                reason = REASON_NO_OUTDOOR_DATA
            if p.actuator_id in ceiling_ids:
                # 닫는 쪽은 허용(근거 58) — 해 진 뒤 조금 열린 창은 닫는다. 위 '더 열지 않음'은 PI 가 열 때만 걸려
                # 제자리에 서던 창이다.
                _oc = outage_close_command(_pk, p, prev_val)
                if _oc is not None:
                    cmd_raw, reason = _oc
                    I = cmd_raw

            if p.actuator_id in rain_caps:
                # 강우 단계 제한(`safety_gates.classify_rain`, 근거 52). 일사 하한·극한 고온
                # 보호의 하한보다 **뒤** — 비가 이긴다. 상한이 None 이면 지금 개도("더 열지
                # 않음"). 적분은 2.7 과 같은 조건부 적분: 상한을 넘는 요구는 실행되지 않았으므로
                # 배우지 않는다 — 안 그러면 비가 그치는 순간 쌓인 몫이 창을 한 번에 민다.
                _cap = rain_caps[p.actuator_id]
                _cap = hold_command(p, prev_val) if _cap is None else float(_cap)
                if cmd_raw > _cap:
                    cmd_raw = _clamp(_cap, 0.0, 100.0)
                    I = min(new_state.integral.get(p.actuator_id, I), cmd_raw)
                    # 근거는 상한을 건 쪽의 것이다 — 52(비)·55(강풍 1단계)·56(서리 주의의 "더 열지 않음").
                    reason = cap_reasons.get(p.actuator_id, REASON_RAIN_RESTRICT)

            # 스크린 판단(`screen_policy`) — 차광막 바닥(빛 지킴)·근거. 적분도 함께 맞춘다.
            cmd_raw, I, reason = SP.adjust_pi_command(
                ctx.get('screen'), p, cmd_raw, I, reason, primary_var)

            # VPD 직접 모드의 난방 출력 상한(2.56) — 상한을 넘는 요구는 실행되지 않으므로 적분도 그 값을 넘지 않게 하고,
            # 내려가는 쪽은 슬루를 타지 않는다(난방기는 모터가 아니다 — 20 %p/사이클로 내리면 상한을 넘은 채 몇 사이클을 더 돈다).
            _heat_cut = False
            if p.actuator_id in _pk.heat_cap_ids and cmd_raw > _pk.heat_cap_pct + 1e-9:
                cmd_raw = _clamp(_pk.heat_cap_pct, 0.0, 100.0)
                I = min(I, cmd_raw)
                reason = REASON_OPPOSING_PARKED
                _heat_cut = True

            cmd = finalize_command(p, cmd_raw, prev_val, cycle_sec,
                                   reason=reason, var_source=primary_var, no_slew_down=_heat_cut)
            commands[p.actuator_id] = cmd
            cmd_ap = cmd.control_value()

            # ── 속도에 막힌 몫만 적분에 되먹인다 (2026-08-26) ────────────────────
            # 적분의 뜻은 '기억된 평형 개도'다. 그런데 anti-windup 이 [0,100] 클램프
            # 만 되먹이고 **슬루(변화율) 제한은 되먹이지 않아**, PI 가 88.7% 를
            # 원하고 실제로는 25% 만 나가도 적분은 88.7 이 나간 것처럼 계속 자랐다.
            # 그렇게 부풀려진 적분은 자기 정의를 잃고(실측: 側面窓右 I=67.9 인데
            # 실제 개도 25.0), 그 값이 만든 과장된 물리 기여가 부하분담을 타고
            # 남을 거꾸로 켰다 — 2026-08-25 사고의 근원이다.
            #
            # ⚠⚠ **min-ON 스냅은 되먹이면 안 된다.** 둘은 "요구만큼 못 나갔다" 로
            # 같아 보이지만 뜻이 정반대다.
            #
            #   슬루     장치가 **가고는 있다**. 덜 간 몫은 허구이므로 되돌린다.
            #   min-ON  장치가 **아무것도 안 했다**. 몇 초 켜서는 실제 출력이 안
            #           나오는 장치가 많아 일부러 버린 것이다. 여기서 적분까지
            #           깎으면 적분이 문턱을 **영영 못 넘어** 장치가 한 번도 안
            #           도는 교착이 된다.
            #
            # 그래서 버린 몫은 적분에 남긴다 — 쌓여서 의미 있는 한 번을 만들 때
            # 몰아서 켜진다. 펄스 **폭**이 아니라 **빈도**로 조절하는 것이고,
            # PID 컨트롤러의 on/off 경로가 같은 판단을 한다(`raise_min_duration`
            # 미만이면 출력을 건너뛰되 integrator 는 그대로 쌓는다). 적분은
            # [0,100] 하드클램프가 있으므로 이래도 무한히 자라지 않는다.
            #
            # ⚠ 세 분기(hold·무구배·평형)는 적분을 이미 자기 규칙으로 정했으므로
            # 건드리지 않는다 — 그 값들은 요구가 아니라 **의도된 위치**다.
            reachable = cmd.slewed if cmd.slewed is not None else cmd_ap
            # 아래쪽 레일 동결 사이클은 건너뛴다 — 닫는 중 슬루에 막힌 몫을
            # 되먹이면 `I += β·(개도 − 0)` 이라 다시 위로 민다(위 분기 참조).
            if (reason == REASON_PRIMARY and not _freeze_lower
                    and abs(cmd_raw - reachable) > 1e-9):
                I = _clamp(I - (cmd_raw - reachable) * AW_BETA, 0.0, 100.0)

            new_state.integral[p.actuator_id] = I

            # 물리효과를 tier_effect_deltas 에 임시 보관 — 묶음 끝에 accum 반영.
            # **자기 도메인 안에만** 쌓는다(위 accumulated 주석 참조).
            dom = domain_of(p)
            if dom not in tier_effect_deltas:
                tier_effect_deltas[dom] = {}
            for v, e in p.live_effect.items():
                s = 1.0 if e.direction == '↑' else (-1.0 if e.direction == '↓' else 0.0)
                delta = e.magnitude_native * (cmd_ap / 100.0) * s
                tier_effect_deltas[dom][v] = (
                    tier_effect_deltas[dom].get(v, 0.0) + delta)

            _log_cmd(unique_id, p.actuator_id, a_idx, cmd_ap, reason)

        # ── 묶음 전체 처리 완료 → 물리효과를 accumulated 에 한꺼번에 반영.
        # 이 시점 이후의 다음 tier 는 이 묶음 전체의 기여를 포함한 잔여편차를 본다.
        for dom, var_deltas in tier_effect_deltas.items():
            for v, delta in var_deltas.items():
                accumulated[dom][v] = accumulated[dom].get(v, 0.0) + delta

    # ── 3b. 오래 세게 명령했는데 반응이 없는 장치 → 의심 후보(`NOFX_AFTER_S` 주석) ────────
    # 후보는 나열일 뿐이다 — 제외는 피드백 레지스트리가 도메인 쿨다운까지 보고 정한다.
    new_state.noeffect_ids = _noeffect_candidates(
        new_state.nofx_s, vent_strength, available, suspect_ids)

    # ── 4. 명령을 못 받은 프로필(이론상 없음) → 안전 기본값 ──────────────────────
    for p in profiles:
        if p.actuator_id not in commands:
            commands[p.actuator_id] = ActuatorCommand(
                value=p.safe_default, reason=REASON_IDLE)
            _log_cmd(unique_id, p.actuator_id, a_idx, p.safe_default, REASON_IDLE)

    # prev_commands 갱신 — slew 계산은 개도(aperture) 좌표 사용.
    new_state.prev_commands = {
        aid: cmd.control_value() for aid, cmd in commands.items()}

    return commands, new_state


# ─────────────────────────────────────────────────────────────────────────────
# 실외를 모를 때 개구부 규칙 — coordinate() 와 MPC 경로가 **같은 판정**을 쓴다
# ─────────────────────────────────────────────────────────────────────────────

# @manual ai/env-control#pre-gate-checked-before-l1l3
def vent_open_ceiling_ids(ctx: dict, vents) -> set:
    """"더 열지 않음" 을 걸 개구부 id — 강우·풍속을 잃었을 때(2.7).

    **온도 하드 상한(`temp_max`) 위에서는 걸지 않는다.** 고온 피해는 몇 분이면
    오고 빗물 유입은 복구할 수 있다. 이 상한이 서 있다는 것 자체가 마지막
    강우·풍속이 평온했다는 뜻이다 — 위험했으면 안전 게이트가 이미 닫고
    L1~L3 를 건너뛰었다. 그래서 여기서는 `_force_cool`(= `temp_max` 래치)
    하나만 보면 "평온했을 때만 넘는다" 가 성립한다(2026-09-19 결정).

    대상은 `opening` 뿐이다 — 비바람이 들이치는 것은 개구부다. 배기팬은
    같은 환기 도메인이지만 빗물 유입 경로가 아니다.
    """
    if not bool(ctx.get('vent_open_ceiling', False)):
        return set()
    if bool((ctx.get('internal') or {}).get('_force_cool')):
        return set()
    return {p.actuator_id for p in vents if getattr(p, 'kind', '') == 'opening'}


# @manual ai/env-control#safety-gates
def rain_vent_caps(ctx: dict, vents) -> Dict[str, Optional[float]]:
    """강우·강풍 단계 제한의 개구부 상한 {id: 상한 % | None(지금 개도)} — 근거 52·55.

    강풍 1단계(`safety_gates.classify_wind`)도 같은 상한으로 온다 — 숫자 상한이라 늘 건다
    (극한 고온 보호는 그 상한까지 쓴다). 근거는 `ctx['vent_open_cap_reasons']` 에 따로 있다.

    판정은 `safety_gates.classify_rain` 이 끝냈고(`GateResult.vent_caps` →
    `ctx['vent_open_caps']`), 여기서는 이 사이클의 개구부로 거른다.

    **"더 열지 않음"(None) 은 온도 하드 상한(`_force_cool` = 극한 고온 보호 단계 2) 위에서만
    푼다** — `vent_open_ceiling_ids` 와 같은 판단이다(고온 피해는 몇 분, 빗물은 복구할 수
    있다). 보호 단계 1 에서는 묶어 둔다: 그때 열 창은 측창이다(상한이 없거나 30 %). 구마모토
    리플레이에서 단계 1 에 이것을 풀었더니 예보 비 0.7 mm 에 천창이 100 % 까지 갔다.
    숫자 상한(측창 30 %)은 언제나 건다 — 보호는 그 상한까지 쓴다. 닫힌 천창은 강제
    명령(0)이라 여기 오지 않는다.
    """
    raw = ctx.get('vent_open_caps') or {}
    if not raw:
        return {}
    _hp = ctx.get('heat_protect')
    hot = (int(getattr(_hp, 'tier', 0) or 0) >= 2
           or bool((ctx.get('internal') or {}).get('_force_cool')))
    ids = {p.actuator_id for p in vents if getattr(p, 'kind', '') == 'opening'}
    return {aid: cap for aid, cap in raw.items()
            if aid in ids and not (cap is None and hot)}


def outage_close_command(pk: 'ParkDecision', profile, prev: float
                         ) -> Optional[Tuple[float, int]]:
    """실외를 모르는 동안(제자리) 이 개구부가 **닫는 쪽으로** 움직일 값 → (개도 %, 근거) | None.

    PI(`coordinate`)와 MPC(`limit_vent_for_unknown_outdoor`)가 같은 것을 읽는다. 야간 파킹은 평소 파킹과
    같은 감쇠(safe_default 쪽으로 RELAX_FACTOR)이고 근거 19, 해 진 뒤 작은 열림은 0 이고 근거 58, 두절이 30 분 넘게 이어진
    밤에 습도로 열린 창은 사이클당 `OUTAGE_DEHUMID_STEP_PCT` %p 씩 내려 가며 근거 58. 결코 `prev` 를 넘지 않는다.
    """
    aid = profile.actuator_id
    prev = _clamp(prev, 0.0, 100.0)
    if aid in pk.outage_park_ids:
        sd = float(getattr(profile, 'safe_default', 0.0) or 0.0)
        return min(prev, _clamp(sd + (prev - sd) * RELAX_FACTOR, 0.0, 100.0)), REASON_NIGHT_PARKED
    if aid in pk.outage_zero_ids:
        return 0.0, REASON_OUTAGE_CLOSE
    if aid in pk.outage_dehumid_ids:
        return _clamp(prev - float(pk.outage_dehumid_step_pct or 0.0), 0.0, 100.0), REASON_OUTAGE_CLOSE
    return None


def hold_command(profile, prev: float) -> float:
    """'제자리' 를 내는 명령 [개도 %] — 직전 **실제** 개도가 그대로 나가게 한다.

    `finalize_command` 가 전달 비율(풍향 가중치 등, `cmd_scale`)을 곱하므로 직전 개도를 그대로 내면 비율이
    1 미만인 동안 사이클마다 그만큼 닫힌다 — 실측(2026-10-14 김제 측창, 근거 21): 20 → 16 → 13 → 12 → 7 → 0 %
    (08:13~09:03). 그래서 비율로 나눠 낸다. 비율 0(게이트 차단)은 무엇을 내도 0 이라 나누지 않는다.
    """
    prev = _clamp(prev, 0.0, 100.0)
    sc = float(getattr(profile, 'cmd_scale', 1.0) or 0.0)
    return _clamp(prev / sc if 0.0 < sc < 1.0 else prev, 0.0, 100.0)


def blind_vent_command(pk: 'ParkDecision', profile, prev: float
                       ) -> Optional[Tuple[float, int]]:
    """실내를 모르는(근거 21 로 제자리에 설) 환기 장치가 해를 보고 움직일 값 → (명령 %, 근거 60) | None.

    맑은 낮(`blind_floor_ids`)이면 하한까지 사이클당 `blind_step_pct` %p 씩 올린다 — 이미 그 위면 None
    (제자리, 닫지 않는다). 첫 걸음은 min-ON 을 넘긴다: 짧은 주기의 작은 걸음이 매번 0 으로 스냅되면 영영
    못 연다. 해 진 뒤(`blind_close_ids`)면 같은 폭으로 내린다. 값은 명령 좌표다(전달 비율로 나눠 낸다 —
    `hold_command` 와 같은 이유). PI 경로만 쓴다(MPC 는 동결 — 이 하한을 모른다, 일사 하한과 같다).
    """
    aid = profile.actuator_id
    prev = _clamp(prev, 0.0, 100.0)
    step = float(pk.blind_step_pct or 0.0)
    sc = float(getattr(profile, 'cmd_scale', 1.0) or 0.0)
    if sc <= 0.0:
        return None

    def _cmd(actual: float) -> float:
        return _clamp(actual / sc if sc < 1.0 else actual, 0.0, 100.0)

    if aid in pk.blind_floor_ids and pk.blind_floor_pct > 0.0:
        _min_on = float(getattr(getattr(profile, 'cmd_constraints', None), 'min_on_pct', 0.0) or 0.0)
        nxt = min(float(pk.blind_floor_pct), _cmd(max(prev + step, _min_on + 1e-6)))
        if nxt > hold_command(profile, prev) + 1e-9:
            return nxt, REASON_BLIND_SUN_VENT
        return None
    if aid in pk.blind_close_ids and step > 0.0:
        return _cmd(max(0.0, prev - step)), REASON_BLIND_SUN_VENT
    return None


# @manual ai/env-control#pre-gate-checked-before-l1l3, ai/env-control#settings-ventilation
def limit_vent_for_unknown_outdoor(ctx: dict, profile, value: float,
                                   prev: float, pk: Optional['ParkDecision'] = None
                                   ) -> Tuple[float, Optional[int]]:
    """적분이 없는 경로(MPC)용 — 2.6 제자리 · 2.7 더 열지 않음을 한 번에 건다.

    반환 (값, 근거) — 근거가 None 이면 손대지 않은 것이다. coordinate() 는 이
    함수를 쓰지 않는다: 거기서는 적분까지 함께 정해야 해서 루프 안에 있다.
    두 곳의 판정 조건(`_ext_synthetic`, `vent_open_ceiling_ids`)은 같은 것을
    부른다 — 조건을 여기 따로 적으면 갈라진다.
    """
    if getattr(profile, 'kind', '') not in VENTILATING_KINDS:
        return value, None
    if bool((ctx.get('external') or {}).get('_ext_synthetic')):
        _oc = outage_close_command(pk, profile, prev) if pk is not None else None
        if _oc is not None:
            return _oc
        return _clamp(prev, 0.0, 100.0), REASON_NO_OUTDOOR_DATA
    if profile.actuator_id in vent_open_ceiling_ids(ctx, [profile]):
        _oc = outage_close_command(pk, profile, prev) if pk is not None else None
        if _oc is not None:
            return _oc
        if value > prev:
            return _clamp(prev, 0.0, 100.0), REASON_NO_OUTDOOR_DATA
    return value, None


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


# @manual ai/env-control#l3-coordinator-actuator-command
def finalize_command(
    p: ActuatorProfile,
    aperture_pct: float,
    prev_aperture: float,
    cycle_sec: float,
    reason: int,
    var_source: Optional[str] = None,
    no_slew_down: bool = False,
) -> ActuatorCommand:
    """0–100% aperture 명령에 slew·min-ON·operating-range 매핑을 적용.
    `no_slew_down` 은 내려가는 쪽만 슬루를 건너뛴다(난방 출력 상한 — 상한은 한 사이클에 지켜져야 한다).

    PI(coordinator), greybox-PI, MPC 세 경로가 공유하는 명령 최종화 단계.
    - slew: 물리 속도 한계 내로 이전 명령 대비 변화량 제한
    - min-ON: 미세 개도(0<x<min_on)는 0 으로 스냅
    - operating-range: aperture 0–100 을 실제 모터 작동범위로 선형 매핑
    """
    # ── 이 사이클의 전달 비율을 **먼저** 반영한다 (2026-08-26) ──────────────────
    # 풍향 가중치·게이트 차단처럼 "요구대로 다 못 나가는" 물리 제약은 반드시
    # 여기를 지나야 한다. coordinate() **밖**에서 명령에 곱하면 코디네이터는
    # 원래 값이 나갔다고 믿어 ① 적분이 영영 수렴하지 못하고 ② 부하분담에
    # 과장된 효과가 실리고 ③ 제약이 풀리는 순간 쌓인 적분이 계단으로 튀어나온다.
    # 셋 다 실측했다 — 側面窓右(24.6% 명령 / 5.0% 실제, 풍향 가중치 0.2)와
    # 습윤형 분무기(61% 명령 / 0% 실제, 습도 상한 게이트).
    #
    # 슬루보다 앞이다: 실제 움직임이 속도 한계를 받아야 하기 때문이다.
    # ⚠ **0 은 슬루를 지나지 않는다.** 비율(0<s<1)은 "위치 목표를 이만큼 낮춰라"
    # 라서 장치가 자기 속도로 이동하는 게 맞지만, 0 은 "이번 사이클엔 아예 주지
    # 마라"(게이트 차단)라 중간 위치를 거칠 것이 없다. 슬루를 태우면 직전 60%
    # 였던 분무기가 차단 후에도 40% → 20% 로 계속 뿌리고, 코디네이터는 그 값이
    # 나갔다고 배워 적분도 안 내려간다 — 막았다는 사실이 아무 데도 안 닿는다.
    scale = getattr(p, 'cmd_scale', 1.0)
    if scale is not None and float(scale) <= 0.0:
        return ActuatorCommand(
            value=p.cmd_constraints.map_aperture_to_motor(0.0), reason=reason,
            var_source=var_source, aperture=0.0, slewed=0.0)
    if scale is not None and scale != 1.0:
        aperture_pct = _clamp(aperture_pct * float(scale), 0.0, 100.0)

    # 스크린(curtain/shade)은 디스패치에서 0/100 binary 로 스냅된다. slew 를 적용하면
    # 50% 경계를 못 넘어(예: 100→80→여전히 열림) 닫힘/열림 전환이 봉쇄되므로 우회한다.
    if getattr(p, 'kind', '') in ('curtain', 'shade'):
        cmd_slew = aperture_pct
    else:
        slew = p.cmd_constraints.effective_slew(cycle_sec)
        cmd_slew = _clamp(aperture_pct, prev_aperture - slew, prev_aperture + slew)
        if no_slew_down and aperture_pct < prev_aperture:
            cmd_slew = aperture_pct
    reachable = cmd_slew                 # 속도 한계까지만 반영 — 되먹임의 기준
    # min-ON 스냅은 스크린에 걸지 않는다 — 스크린은 0/100 이거나 정지점(커튼 틈 3 %·램프)이고,
    # 걸면 틈 3 % 가 0 이 되어 첫 단계가 통째로 사라진다(폐루프 humid_gap_night).
    if (0.0 < cmd_slew < p.cmd_constraints.min_on_pct
            and getattr(p, 'kind', '') not in ('curtain', 'shade')):
        cmd_slew = 0.0
    cmd_motor = p.cmd_constraints.map_aperture_to_motor(cmd_slew)
    return ActuatorCommand(value=cmd_motor, reason=reason,
                           var_source=var_source, aperture=cmd_slew,
                           slewed=reachable)


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _same_sign(a: float, b: float) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)


def _outdoor_reachable(var: str, ctx: Dict) -> Optional[float]:
    """환기를 최대로 했을 때 실내 변수가 수렴하는 값(= 실외 값). 모르면 None.

    환기는 실내 공기를 실외 공기로 바꾸는 것이므로, 도달 가능한 끝점은 실외
    상태다. 그 사이 어디까지 갈지는 개도와 풍량이 정하지만, **어느 쪽 방향으로
    갈 수 있는지**는 이 값 하나로 정해진다.
    """
    if var == 'temperature':
        return ctx.get('T_ext')
    if var == 'humidity':
        return ctx.get('RH_ext')
    if var == 'co2':
        return ctx.get('CO2_ext')
    if var == 'vpd':
        T_e, RH_e = ctx.get('T_ext'), ctx.get('RH_ext')
        if T_e is None or RH_e is None:
            return None
        return psychro.svp(float(T_e)) * (1.0 - float(RH_e) / 100.0)
    return None


# @manual ai/env-control#settings-ventilation
def _ventilation_reaches_all_targets(
        situation: SituationReport, ctx: Dict, vents: List[ActuatorProfile],
        prev_commands: Dict[str, float]) -> bool:
    """환기만으로 **모든** 제어 목표에 닿을 수 있는가 (vent_first 판정).

    닿는다 = 실외가 목표를 tolerance×VENT_REACH_MARGIN 만큼 **지나** 있다.
    딱 걸치면 환기는 목표에 점근할 뿐이라 닿았다고 할 수 없고, 경계에서
    켜졌다 꺼졌다 한다.

    ⚠ 판정 대상은 **벗어난 변수만**이다. 이미 범위 안인 변수는 찬반 근거가
    못 되므로 건너뛴다 — 포함시키면 "평형이라 avail 이 0" 이라는 이유로 항상
    False 가 되어 이 기능이 한 번도 서지 않는다.

    ⚠ 벗어난 변수가 하나도 없으면 False 다. 평형 상태에서 냉난방을 파킹하는
    것은 이 옵션이 하려는 일이 아니다(그건 데드존이 이미 한다).
    """
    if not vents:
        return False
    # 환기 여력이 없으면(창이 이미 만개) 냉난방이 도와야 한다.
    # ⚠ **최댓값**이다 — 평균이면 0% 에 고착된 창 하나가 escalation 을 영영
    #   막는다(VENT_HEADROOM_PCT 주석 참조).
    aps = [prev_commands.get(p.actuator_id, 0.0) for p in vents]
    if aps and max(aps) >= VENT_HEADROOM_PCT:
        return False

    decisive = False
    for var, dev in situation.deviation_native.items():
        t = situation.target.get(var)
        if t is None or t.tolerance <= 0:
            continue
        need = -dev                                  # + = 값을 올려야 함
        if abs(need) <= t.tolerance * VENT_NEED_FRAC:
            continue                                 # 범위 안 — 판정 대상 아님
        reachable = _outdoor_reachable(var, ctx)
        if reachable is None:
            return False                             # 실외를 모르면 단정하지 않는다
        measured = t.value + dev
        avail = float(reachable) - measured
        decisive = True
        if not _same_sign(need, avail):
            return False                             # 방향이 반대 — 환기로는 못 간다
        if abs(avail) < abs(need) + t.tolerance * VENT_REACH_MARGIN:
            return False                             # 목표에 못 미친다(점근만)
    return decisive


# @manual ai/env-control#settings-ventilation
def _ventilation_credit(
        situation: SituationReport, ctx: Dict, vents: List[ActuatorProfile],
        blocked: set) -> Dict[str, float]:
    """실외가 **대신 해 줄 수 있는 몫** → {변수: 편차 보정값}.

    ## 왜 필요한가 — `vent_first` 는 이분법이었다

    파킹 판정은 "환기로 **전부** 되는가" 하나만 묻는다. 그래서 상태가 둘뿐이다:

        전부 된다  → 냉난방 파킹
        아니다     → 냉난방이 **전체 편차**를 자기 혼자 메울 값으로 계산

    실제로 흔한 것은 그 중간이다. 실측(2026-08-26 쿠마모토 イチゴ):

        실내 VPD 0.67   목표 1.0   실외 0.897
        실외가 메울 수 있는 몫 = (0.897−0.67)/(1.0−0.67) = 69%

    실외가 목표까지의 69% 를 공짜로 해 주는데, 난방기는 그것을 **모른 채**
    −0.33 전부를 자기 몫으로 계산해 46.5% 로 돌고 있었다. 창은 열려 있고
    난방기는 과다 가동 — 열을 버리며 데운다.

    ## 왜 `hvac_interlock`(창 잠금)이 답이 아닌가

    잠그면 그 69% 를 통째로 버리고 난방 부하가 3배가 된다. 열 손실은 막지만
    더 많은 에너지를 쓴다. 판단 기준은 스위치가 아니라 **내외 환경 차이**여야
    한다 — 실외가 도울 수 있으면 맡기고, 못 하면 그만큼만 냉난방이 진다.
    실외가 전혀 못 도우면 이 함수가 0 을 돌려주므로 냉난방이 전부 맡는다
    (= 잠금 없이도 겨울에는 저절로 예전 동작이 된다).

    ## ⚠ 도메인 간 부하분담을 되살리는 것이 아니다

    2026-08-25 사고는 액추에이터가 **주장한 효과**(모델 출력)를 도메인 너머로
    넘기다 부호가 뒤집혀 반대편을 켰다. 여기서 넘기는 것은 모델 출력이 아니라
    **실외 측정값**이다 — 어떤 액추에이터의 주장도 아닌 독립적인 물리 상한이고,
    한 장치가 고장 나도 값이 바뀌지 않는다. 그래서 그 사고의 성립 조건
    ("남의 주장을 근거로 내 방향을 정한다")이 여기엔 없다.

    ## 안전 조건 — 하나라도 어긋나면 그 변수는 크레딧 0

    창이 못 열리면(비·바람 게이트, 무익 판정, 실외 근거 없음) 실외는 아무것도
    못 해 준다. 그때 크레딧을 주면 **냉난방이 있지도 않은 도움을 믿고 물러난다**
    — 비 오는 날 난방이 모자라는 모양이 된다.
    """
    out: Dict[str, float] = {}
    live = [p for p in vents if p.actuator_id not in blocked]
    if not live:
        return out                          # 창이 하나도 못 움직인다 → 도움 없음
    if bool((ctx.get('external') or {}).get('_ext_synthetic')):
        return out                          # 실외를 지어낸 값이면 근거가 아니다

    for var, dev in situation.deviation_native.items():
        t = situation.target.get(var)
        if t is None or t.tolerance <= 0:
            continue
        need = -dev                                  # + = 값을 올려야 함
        if abs(need) <= t.tolerance * VENT_NEED_FRAC:
            continue                                 # 범위 안 — 나눌 것이 없다
        reachable = _outdoor_reachable(var, ctx)
        if reachable is None:
            continue
        measured = t.value + dev
        help_ = float(reachable) - measured          # 실외가 데려다 줄 수 있는 거리
        if not _same_sign(need, help_):
            continue                                 # 방향이 반대 — 도움이 아니다
        # ⚠ **need 를 넘겨선 안 된다.** 넘기면 보정된 편차의 부호가 뒤집혀
        #   냉난방이 반대로 돈다 — 2026-08-25 사고와 같은 모양이다.
        #   목표를 지나는 경우는 파킹 판정이 이미 전부 맡으므로 여기선 자른다.
        if abs(help_) > abs(need):
            help_ = need
        out[var] = help_
    return out


# @manual ai/env-control#settings-ventilation
def _ventilation_is_futile(profile: ActuatorProfile,
                           situation: SituationReport,
                           ctx: Dict) -> bool:
    """이 환기 장치가 **어떤 제어변수도** 목표 쪽으로 못 옮기는가.

    변수마다 세 가지를 본다.
      need  = 목표 - 측정        (+ 면 값을 올려야 함)
      avail = 실외 - 측정        (환기로 갈 수 있는 방향과 여유)
      부호가 같고 둘 다 문턱을 넘으면 그 변수는 '환기로 개선 가능'.

    하나라도 개선 가능하면 무익이 아니다(False). 판단 근거가 될 만큼 벗어난
    변수가 하나도 없으면(전부 중립) 역시 False — 이때는 평상시 hold 가 맞다.
    실외값을 모르면 보수적으로 False(게이트 미발동).

    deviation_native 는 '측정 - 목표' 규약이므로 need = -deviation 이다.

    ⚠ **온도 상한이 걸려 있으면 온도도 본다.** VPD 제어 중에는 온도가
    deviation 에 없어서, 실외 VPD 가 도움이 안 되는 순간 창이 "무익" 으로
    파킹된다 — 실내가 33 °C 로 오르고 실외가 23 °C 라도.
    """
    tc = ctx.get('_t_ceiling')
    if tc is not None:
        eff_t = (profile.live_effect or {}).get('temperature')
        if (eff_t is not None and eff_t.direction == '↓'
                and eff_t.magnitude_native > 0.0):
            return False                          # 식힐 수 있다 — 무익이 아니다
    decisive = False
    for var in profile.live_effect:
        if var not in situation.deviation_native:
            continue
        t = situation.target.get(var)
        if t is None or t.tolerance <= 0:
            continue
        dev = situation.deviation_native[var]      # 측정 - 목표
        need = -dev
        if abs(need) <= t.tolerance * VENT_NEED_FRAC:
            continue                              # 중립 — 찬반 근거가 못 된다
        reachable = _outdoor_reachable(var, ctx)
        if reachable is None:
            return False                          # 판정 불가 → 미발동
        measured = t.value + dev
        avail = float(reachable) - measured
        decisive = True
        # VPD 는 잡음 안의 차이(RH 1~2 %p ≈ 0.05 kPa)로 창을 움직이지 않는다 —
        # `VENT_MIN_VPD_GAP` 주석. 다른 변수는 종전처럼 허용오차가 문턱이다.
        _min_gap = (max(t.tolerance, VENT_MIN_VPD_GAP) if var == 'vpd'
                    else t.tolerance)
        # 이력: 무익이던 장치는 문턱 전체를, 아니던 장치는 문턱의 FUTILE_ENTER_FRAC 만 넘으면 된다.
        if profile.actuator_id not in (ctx.get('_futile_prev') or ()):
            _min_gap *= FUTILE_ENTER_FRAC
        if abs(avail) >= _min_gap and _same_sign(need, avail):
            return False                          # 하나라도 환기로 개선 가능
    return decisive


def _log_cmd(
    unique_id: str,
    actuator_id: str,
    a_idx: Dict[str, int],
    value: float,
    reason: int,
):
    if not unique_id or actuator_id not in a_idx:
        return
    idx = a_idx[actuator_id]
    write_decision_log(unique_id, f'coord_actuator_{actuator_id[:8]}_command',
                       ch_coord_cmd(idx), value)
    write_decision_log(unique_id, f'coord_actuator_{actuator_id[:8]}_reason',
                       ch_coord_reason(idx), float(reason))
