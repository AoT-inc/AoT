# coding=utf-8
"""
_cycle_mixin.py — CycleMixin: _run_cycle() (L1→L2→L3 pipeline).
"""

import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from aot.functions.utils.env_control.active_probe import ActiveProbeScheduler
from aot.functions.utils.env_control.actuator_feedback import ActuatorFeedbackRegistry
from aot.functions.utils.env_control.authority import authority_summary, derive_authority
from aot.functions.utils.env_control.calibration import CalibrationRegistry
from aot.functions.utils.env_control.coordinator import (
    coordinate, ActuatorCommand, CoordinatorState,
)
from aot.functions.utils.env_control import log_channels as _LC
from aot.functions.utils.env_control.data_hygiene import DataHygieneChecker
from aot.functions.utils.env_control.greybox.params import GreyboxParams
from aot.functions.utils.env_control.greybox.shadow import GreyboxShadow
from aot.functions.utils.env_control.ext_context_fallback import (
    build_fallback_context, carry_forward_outdoor)
from aot.functions.utils.env_control.goal import build_env_target
from aot.functions.utils.env_control.group_expander import expand_group_commands
from aot.functions.utils.env_control.log_channels import (
    CH_ACTUATOR_MISMATCH, CH_CLEAN_FOR_LEARNING, CH_GREYBOX_KPI_PASSED,
    CH_SAFETY_GATE,
    GATE_BIT_WIND, GATE_BIT_RAIN, GATE_BIT_HEAT, GATE_BIT_COLD,
    write_cycle_metrics, write_decision_log,
)
from aot.functions.utils.env_control.forecast_feedforward import (
    build_feedforward_signal_from_forecast,
    FeedforwardSignal, apply_feedforward, build_feedforward_signal,
)
from aot.functions.utils.env_control.safety_gates import (
    is_wetting_fogger, GateResult,
)
from aot.functions.utils.env_control.situation import assess, decompose_vpd_to_T_RH
from aot.functions.utils.env_control.types import ActuatorProfile, SituationReport


# ── 하드 임계 히스테리시스 폭 ────────────────────────────────────────────────
# 임계를 한 번 넘으면 이만큼 되돌아와야 해제된다. 없으면 값이 임계 근처에서
# 흔들릴 때 강제 오버라이드가 매 사이클 on/off 를 반복해 액추에이터가 왕복한다
# (2026-07-30 aot-005: 차광막이 17:50 개방 → 18:04 폐쇄. 차광막은 편도 285초
# full-stroke 주행이라 왕복 피해가 특히 크다).
@dataclass
class _CycleContext:
    """한 사이클이 만들어낸 값들의 묶음 — 단계 사이로 넘긴다.

    _run_cycle 이 727줄까지 자라면서 단계를 떼어내려 해도 지역변수 열몇 개가
    함께 흘러 시그니처가 감당이 안 됐다. 묶어서 넘기면 새 단계를 추출할 때
    필드만 늘리면 되고 호출부 시그니처는 그대로다.

    주의: 이건 사이클 **지역 상태**다. Function 의 설정 속성(self.target_vpd 등)은
    옵션 프레임워크가 setattr 로 평평하게 주입하므로 이런 식으로 묶을 수 없다.
    """
    uid: str = ''
    internal: dict = None
    external: dict = None
    external_for_control: dict = None
    env_target: Any = None
    situation: Any = None
    authority: Any = None
    gate_result: Any = None
    commands: dict = None
    final_cmds: dict = None
    is_probe: bool = False


TEMP_HYST_C     = 0.5    # °C
RH_HYST_PCT     = 2.0    # %
LIGHT_HYST_FRAC = 0.10   # 임계의 10% (광량은 절대폭이 0~1000 으로 넓어 비율 사용)


def latch_threshold(value: float, threshold: float, hysteresis: float,
                    was_breached: bool, mode: str) -> bool:
    """하드 임계 위반 여부를 히스테리시스 래치로 판정.

    mode='max': value > threshold 이면 위반. 위반 중에는 value 가
                threshold-hysteresis 아래로 내려가야 해제된다.
    mode='min': value < threshold 이면 위반. 위반 중에는 value 가
                threshold+hysteresis 위로 올라가야 해제된다.

    즉 진입 문턱과 해제 문턱을 비대칭으로 둔다. coordinator.py 의
    active_vars 히스테리시스(활성 시 문턱을 좁힘)와 같은 계열의 기법이다.
    """
    if mode == 'max':
        limit = threshold - hysteresis if was_breached else threshold
        return value > limit
    limit = threshold + hysteresis if was_breached else threshold
    return value < limit


def estimate_indoor_light(outdoor_light: float, profiles: list[ActuatorProfile],
                          apertures: dict, default_tau: float = 0.0) -> float:
    """실외 일사 + 차광막 개도로 차광막 '아래' 광량을 추정한다.

    실내 광센서가 없으면 internal['light'] 에 실외 일사가 그대로 들어가는데,
    그 값은 차광막을 닫아도 변하지 않는다. 즉 차광막이 스스로 만든 광부족을
    light_min 이 원리적으로 감지할 수 없다(2026-07-29 aot-005 사건). 이 함수가
    개도를 반영해 그 맹점을 메운다.

    투과율 τ = 완전히 닫았을 때 통과하는 광 비율(0.30 = 차광률 70%).
    폐쇄율 c = (100 - 개도)/100 이라 할 때 통과율은

        1 - c × (1 - τ)

    개도 100%(걷힘) → 통과율 1.0, 개도 0%(완전폐쇄) → 통과율 τ 로 수렴한다.

    투과율은 액추에이터별 값(env_actuator 액션)이 우선하고, 없으면 함수 레벨
    기본값(default_tau)을 쓴다. 시설 도면에서 자동 발견된 액추에이터는 액션 행
    자체가 없는 경우가 많아(aot-005 가 그렇다) 함수 레벨 값이 유일한 입력구다.

    둘 다 없으면 원본을 그대로 돌려준다(미설정 시 기존 동작 유지 — opt-in).

    주의: 온실 피복재 투과율은 곱하지 않는다. 그 값은 차광막 개도와 무관한
    상수라 사용자가 잡아둔 light_min/light_max 기준선에 이미 녹아 있고, 여기서
    다시 곱하면 임계가 갑자기 훨씬 자주 걸린다.
    """
    factors = []
    for p in profiles:
        if getattr(p, 'kind', '') != 'shade':
            continue
        tau = (getattr(p, 'capacity_meta', None) or {}).get('shade_transmittance')
        if not tau:
            tau = default_tau          # 액추에이터별 미설정 → 함수 레벨 기본값
        if not tau or not (0.0 < tau <= 1.0):
            continue
        aperture = apertures.get(p.actuator_id)
        if aperture is None:
            continue
        closed = max(0.0, min(1.0, (100.0 - float(aperture)) / 100.0))
        factors.append(1.0 - closed * (1.0 - float(tau)))
    if not factors:
        return outdoor_light
    # 차광막이 여러 장이면 가장 어두운 쪽(최소 통과율)을 대표값으로 쓴다.
    # 작물이 실제로 받는 최악 조건을 봐야 광부족을 놓치지 않는다.
    return outdoor_light * min(factors)


def apply_light_threshold_overrides(
        internal: dict, profiles: list[ActuatorProfile], final_cmds: dict) -> None:
    """광량 하드 임계(light_max/light_min) 위반 시 shade/lighting 강제 오버라이드.

    규약: 차광막 0%=닫힘=차광, 100%=열림=빛 유입.
      - 광량 과다(light_max) → 차광막을 닫아(0%) 빛 차단.
      - 광량 부족(light_min) → 보광등(lighting)이 있으면 100%로 켜고,
        **차광막도 함께 강제 개방(100%)** 한다. 과거엔 light_min 쪽에 보광등
        대응만 있고 차광막을 열어주는 대칭 로직이 없어서, 보광등이 없는(가장
        흔한) 시설은 광부족 상황에 아무 대응도 못 했다(2026-07-29 aot-005
        사건: 광량 부족한데도 온도 목적만으로 닫혀있던 차광막이 안 열림).
    """
    if internal.get('_force_shade'):
        for p in profiles:
            if p.kind == 'shade':
                final_cmds[p.actuator_id] = {'value': 0.0, 'reason': 'light_max'}
    if internal.get('_force_suplight'):
        for p in profiles:
            if p.kind == 'lighting':
                final_cmds[p.actuator_id] = {'value': 100.0, 'reason': 'light_min'}
            elif p.kind == 'shade':
                final_cmds[p.actuator_id] = {'value': 100.0, 'reason': 'light_min'}


def clamp_guide_range_to_hard_limits(
        guide, temp_min=None, temp_max=None,
        humid_min=None, humid_max=None):
    """유도 범위를 하드 임계 안으로 좁힌다 → ((T_min, T_max, RH_min, RH_max), [바뀐 것]).

    유도 범위(`guide_T_min/max`)와 하드 임계(`temp_max/min`)는 서로를 모르는 두
    설정이다. 그래서 유도 상한이 하드 상한보다 높으면 **파생 목표가 하드 상한
    밖에 떨어진다** — 코디네이터는 매 사이클 "거기까지 데워라" 를 계산하고,
    하드 임계는 매 사이클 그것을 강제로 끈다. 설정만으로 영구 교착이고, 그
    상태에서 나가는 명령은 서로 맞선다.

    실측(2026-08-26 温室環境制御): 유도 상한 32(기본값) · `temp_max` 30 →
    유효 목표 31.97 °C. 실내 32.7 °C 에서 난방기가 **VPD 를 이유로** 100% 로
    돌고 냉방기는 하드 임계로 100% 로 돌았다.

    목표는 하드 임계 **안에서만** 세운다. 임계에 딱 붙는 것은 괜찮다 — 판정에
    히스테리시스(`TEMP_HYST_C`)가 있어 경계에서 떨리지 않는다.

    ⚠ **여유(margin)를 임의로 빼지 말 것.** 근거 없는 상수가 하나 늘고, 그만큼
      사용자가 정한 문턱과 실제 목표가 조용히 어긋난다.

    ⚠ 좁힌 결과가 뒤집히면(하한 > 상한) 그 설정은 모순이다. 그때는 **하드
      임계가 이긴다** — 유도 범위를 살리면 "넘지 마라" 가 무의미해진다.

    ⚠ 0/None 은 "안 정했다" 로 읽는다(`Input.max_age_s` 와 같은 판단). 유효한
      한계로 받으면 실수로 0 을 넣은 시설의 목표가 0 °C 로 눌린다.
    """
    T_min, T_max, RH_min, RH_max = (float(v) for v in guide)
    changed = []
    if temp_max and T_max > float(temp_max):
        T_max = float(temp_max)
        changed.append('T상한→%.1f' % T_max)
    if temp_min and T_min < float(temp_min):
        T_min = float(temp_min)
        changed.append('T하한→%.1f' % T_min)
    if T_min > T_max:
        T_min = T_max
    if humid_max and RH_max > float(humid_max):
        RH_max = float(humid_max)
        changed.append('RH상한→%.0f' % RH_max)
    if humid_min and RH_min < float(humid_min):
        RH_min = float(humid_min)
        changed.append('RH하한→%.0f' % RH_min)
    if RH_min > RH_max:
        RH_min = RH_max
    return (T_min, T_max, RH_min, RH_max), changed


def apply_temp_humid_threshold_overrides(
        internal: dict, profiles: list[ActuatorProfile], final_cmds: dict) -> None:
    """온습도 하드 임계(temp_max/min, humid_max/min) — **제약**이지 목표가 아니다.

    ## 제약과 목표는 다른 것이다 (2026-08-26 재설계)

    이 시스템의 제어 중심은 **VPD** 하나다. `_decompose_vpd` 가 VPD 목표와
    측정이 둘 다 있으면 온도·습도를 제어목표에서 빼고 `_..._constraint` 로
    강등한다 — 그 주석이 말하는 대로 "T/RH 상·하한은 별도 constraint 검사가
    강제" 한다. 즉 온습도는 **참고값이자 넘지 말아야 할 선**이지, 좇아야 할
    목표가 아니다.

    그런데 예전 구현은 `GATE_BIT_HEAT/COLD`(폭염·한파 **비상** 게이트)의
    액추에이터 조합을 그대로 베껴 와서, 32°C 같은 평범한 상황에서 비상과
    똑같은 조치를 냈다:

        VPD 1.59 / 목표 1.61  → PI: 냉방기 0%      ← 제어 중심은 "할 일 없음"
        온도 32.2 > 상한 30   → 강제: 냉방기 100%  ← 참고값이 제어를 빼앗는다

    그리고 그것은 제어가 아니라 **래치**다. 관찰→비교→운전량 루프가 없어서
    100%로 몇 시간을 돌려 아무 변화가 없어도 판정은 똑같다 — 실외 35.1°C 에서
    실내를 30 아래로 내릴 방법이 없으니 영원히 돈다(실측: 温室環境制御).

    ## 그래서 규칙은 하나다 — **막는 것은 남기고, 미는 것은 뺀다**

        금지    그 방향으로 **더 밀지 못하게** 한다   (난방기 0 · 냉방기 0)
        예방    유입을 차단해 **더 나빠지지 않게** 한다 (차광막 침 · 개구부 폐쇄 ·
                보온커튼 침)
        구동    ✘ 목표 추종이다. 여기서 하지 않는다    (난방기 100 · 냉방기 100 ·
                개구부 100 · 배기팬 100 · 분무 100)

    구동이 필요한 값은 **제어 중심(VPD)이 정한다.** 그래야 운전량이 편차에
    비례하고, 결과가 안 따라오면 `_assess_strain` 이 "못 따라감" 을 말한다.

    ⚠ 진짜 위험 구간은 비어 있지 않다 — 폭염·한파는 `safety_gates` 의 비상
      게이트가 따로 맡고, 거기서는 bang-bang 이 맞다. 이 로컬 임계는 그보다
      훨씬 앞에서 서는 **선**이다.

    ⚠ **여기에 `= 100.0` 을 되살리지 말 것.** 그 한 줄이 참고값을 목표로
      바꾸고, 제어 중심을 덮어쓴다.
    """
    if internal.get('_force_cool'):
        for p in profiles:
            if p.kind == 'heater':
                # 금지 — 더워서 선을 넘었는데 가온하는 일은 없어야 한다.
                final_cmds[p.actuator_id] = {'value': 0.0, 'reason': 'temp_max'}
            elif p.kind == 'shade':
                # 예방 — 차광막을 쳐서 일사 유입을 끊는다(규약: 0 = 차광막 닫음).
                final_cmds[p.actuator_id] = {'value': 0.0, 'reason': 'temp_max'}
    if internal.get('_force_heat'):
        for p in profiles:
            if p.kind == 'cooler':
                final_cmds[p.actuator_id] = {'value': 0.0, 'reason': 'temp_min'}
            elif p.kind == 'opening':
                # 예방 — 찬 바깥공기 유입 차단.
                final_cmds[p.actuator_id] = {'value': 0.0, 'reason': 'temp_min'}
            elif p.kind == 'curtain':
                # 예방 — 보온커튼을 쳐서 열 손실을 줄인다(규약: 0 = 커튼 닫음).
                final_cmds[p.actuator_id] = {'value': 0.0, 'reason': 'temp_min'}
    if internal.get('_force_dehumid'):
        for p in profiles:
            if p.kind == 'fogger':
                # 금지 — 습해서 선을 넘었는데 가습하는 일은 없어야 한다.
                final_cmds[p.actuator_id] = {'value': 0.0, 'reason': 'humid_max'}
    if internal.get('_force_humid'):
        for p in profiles:
            if p.kind == 'exhaust_fan':
                # 금지 — 건조해서 선을 넘었는데 배기로 더 말리는 일은 없어야 한다.
                final_cmds[p.actuator_id] = {'value': 0.0, 'reason': 'humid_min'}


def apply_nursery_fog_derate(
        internal: dict, profiles: list[ActuatorProfile], final_cmds: dict) -> None:
    """육묘장 모드: 일사가 올라가는 구간에서 습윤형 분무 명령을 선형 감쇠한다.

    하드 잠금(광량 >= lockout)은 안전 프리게이트가 GATE_BIT_FOG_SUNBURN 으로
    처리한다. 여기서는 그 아래 구간을 다룬다 — release 미만은 그대로 두고,
    release~lockout 사이에서 1 → 0 으로 줄인다. 해가 뜨는 동안 분무가
    100%에서 0으로 절벽처럼 끊기지 않고 서서히 잦아들게 하기 위함이다.

    펄스 도징이 켜져 있으면 이 감쇠는 곧 "펄스 길이 축소"로 나타난다.

    `humid_min` 하드 임계가 분무를 100%로 강제한 뒤에 호출되어야 한다 —
    사용자가 설정한 최저 습도 때문에 일소 위험을 무릅쓰게 두면 안 된다.
    습도 하한 자체는 잠금 해제 시각(아침·저녁)에 회복된다.
    """
    # 육묘 모드를 전제하지 않는다 — 하드 잠금(safety_gates._eval_nursery_lock)
    # 과 같은 이유다. 잠금과 감쇠가 서로 다른 조건에서 서면, 잠기지도 감쇠되지도
    # 않는 구간이나 감쇠 없이 절벽처럼 끊기는 구간이 생긴다.
    if internal.get('evening_block'):
        # 저녁 차단은 안전 게이트가 0 으로 강제한다 — 여기서 감쇠할 대상이 아니다.
        return
    light = internal.get('light_est')
    if light is None:
        # 게이트와 같은 폴백을 쓴다 — 잠금은 걸리는데 그 아래 구간의 감쇠만
        # 빠지면, 센서 없는 시설에서 분무가 절벽처럼 끊긴다.
        light = internal.get('_nursery_light_fallback')
    if light is None:
        return
    lockout = float(internal.get('_nursery_solar_lockout') or 0.0)
    release = float(internal.get('_nursery_solar_release') or 0.0)
    if lockout <= 0.0 or lockout <= release or light <= release:
        return

    scale = max(0.0, min(1.0, (lockout - light) / (lockout - release)))
    for p in profiles:
        if not is_wetting_fogger(p):
            continue
        cmd = final_cmds.get(p.actuator_id)
        if not cmd:
            continue
        value = cmd.get('value', 0.0) if isinstance(cmd, dict) else getattr(cmd, 'value', 0.0)
        if value <= 0.0:
            continue
        final_cmds[p.actuator_id] = {
            'value': value * scale,
            'reason': 'nursery_fog_derate',
        }


def apply_wetting_fog_humidity_ceiling(
        internal: dict, profiles: list[ActuatorProfile], final_cmds: dict) -> None:
    """습도가 이미 허용 범위 위면 **습윤형 분무를 쓰지 않는다**.

    결합 drive 는 각 축을 자기 허용오차로 정규화해 겨루게 하므로, "이미 한참
    벗어난 축을 더 나빠지게 하면 안 된다" 는 개념이 없다. 실측(2026-08-25
    イチゴ): 습도 편차 +26.5%(허용 5) · 온도 편차 +1.4°C(허용 1) 상황에서

        온도  e=+0.233  g=0.285  w=0.1425     ← 냉각 방향
        습도  e=-0.883  g=0.014  w=0.0072     ← 가습 방향(반대)
        e_norm = +0.180 → 분무 20% 켜짐   (가중치 20 : 1)

    방향 신호는 습도가 4배 강한데 **유효도 가중치가 20배**라 온도가 이긴다.
    분무기의 습도 효과가 물리적으로 작기 때문이고(RH 89%에서 ΔRH 0.43%),
    그 작음이 곧 "습도는 어차피 못 건드리니 온도나 잡자" 로 읽힌 것이다.

    얻는 것은 1.71°C 냉각인데, 대가는 이미 포화에 가까운 공기에서 잎이 젖고
    마를 틈이 없는 것이다 — 딸기·토마토에 잿빛곰팡이가 오는 조건이다. 그
    거래는 성립하지 않는다.

    **왜 drive 가 아니라 게이트인가.** 결합 drive 에 "초과 축 페널티" 를 넣는
    일반해도 있지만 그것은 **모든 액추에이터의 거동을 바꾼다.** 여기서 막고
    싶은 것은 한 종류(습윤형 분무기)의 한 상황이고, 이유도 습도 숫자가 아니라
    **젖은 잎**이다 — 일소 잠금과 같은 성격이라 같은 자리에 같은 모양으로 둔다.

    고압 미세포그와 드립은 대상이 아니다. 전자는 잎을 적시지 않아 VPD 제어의
    정당한 수단이고, 후자는 애초에 대기 액추에이터가 아니다.
    """
    if not internal.get('_fog_humidity_block'):
        return
    for p in profiles:
        if not is_wetting_fogger(p):
            continue
        cmd = final_cmds.get(p.actuator_id)
        if not cmd:
            continue
        value = cmd.get('value', 0.0) if isinstance(cmd, dict) else getattr(cmd, 'value', 0.0)
        if value <= 0.0:
            continue
        final_cmds[p.actuator_id] = {'value': 0.0, 'reason': 'fog_humidity_ceiling'}


# ── 맞서는 짝 인터록 ─────────────────────────────────────────────────────────
# 냉방과 난방이 동시에 도는 것은 정상 동작이 아니라 서로의 에너지를 상쇄하며
# 버리는 상태다. PID 는 raise/lower 출력을 두고 **오차 부호가 한쪽만 고르는 것**
# 자체가 인터록인데, 코디네이터는 액추에이터마다 따로 PI 를 돌리므로 그 성질이
# 공짜로 따라오지 않는다.
#
# ⚠ **반드시 맨 마지막이다.** 예전에는 이 검사가 Post-Gate 안에 있어서 임계
#   오버라이드보다 **앞**에서 돌았다 — 그 시점에는 아직 충돌이 없고(코디네이터가
#   난방 100 · 냉방 0), 충돌은 그 뒤 `_force_cool` 이 냉방을 100 으로 올리면서
#   **새로 생겼다.** 검사는 통과했는데 나가는 명령은 둘 다 100 이었다
#   (2026-08-26 실측: 温室環境制御, temp_max=30 · 실내 32.7°C).
#
# ⚠ **구현을 두 벌 두지 말 것.** 같은 규칙이 Post-Gate 와 여기 양쪽에 있으면
#   갈라지고, 갈라지면 늦게 도는 쪽이 실질 규칙이 된다. Post-Gate 의 것은
#   이 함수로 옮기면서 지웠다.

# 명령의 출처 서열. 큰 쪽이 이긴다.
#   3 안전 게이트  — 언제나 최우선
#   2 하드 임계    — 사용자가 정한 문턱. 수동 락보다 앞이다(오버라이드가 수동
#                    락 뒤에 적용되는 기존 순서를 그대로 옮긴 것).
#   1 수동 락
#   0 그 밖(코디네이터 PI)
# ⚠ 코드 번호를 여기 옮겨 적지 말 것 — 정본은 `log_channels` 다. 베껴 두면
#   규약이 바뀔 때 조용히 어긋나고, 그러면 서열이 전부 0 이 되어 인터록이
#   비용 판정으로만 돌아간다(=하드 임계가 전기요금에 진다).
# ⚠ 온습도 하드 임계('temp_max' 등)는 여기 없다 — 그 제약은 맞서는 짝을
#   **끄기만** 하므로(위 `apply_temp_humid_threshold_overrides`) 켜진 쪽으로
#   나타나는 일이 없다. 없는 경우를 위한 칸을 만들어 두면 검사할 수 없는
#   규칙이 되고, 검사할 수 없는 규칙은 조용히 틀린다.
_INTERLOCK_RANK = {
    _LC.REASON_SAFETY_PRE_GATE:  3,
    _LC.REASON_SAFETY_POST_GATE: 3,
    _LC.REASON_MANUAL_OVERRIDE:  1,
}
_INTERLOCK_ON_PCT = 5.0


def apply_hvac_opposition_interlock(
        profiles: list[ActuatorProfile], final_cmds: dict) -> bool:
    """냉방과 난방이 동시에 돌면 한쪽을 끈다 → 껐으면 True.

    이기는 쪽은 **출처가 더 센 쪽**이다(`_INTERLOCK_RANK`). 서열이 같으면
    예전 규칙대로 **비용이 싼 쪽**이 이긴다.

    ⚠ 비용만으로 정하면 안 된다 — 사용자가 정한 하드 임계로 강제된 쪽이
      비용 때문에 꺼질 수 있다. "30°C 를 넘지 마라" 는 설정이 전기요금에
      지는 것은 뜻이 뒤집히는 것이다.
    """
    cooler_ids = [p.actuator_id for p in profiles if p.kind == 'cooler']
    heater_ids = [p.actuator_id for p in profiles if p.kind == 'heater']
    if not cooler_ids or not heater_ids:
        return False

    def _on(ids):
        return any((final_cmds.get(a) or {}).get('value', 0.0) > _INTERLOCK_ON_PCT
                   for a in ids)

    if not (_on(cooler_ids) and _on(heater_ids)):
        return False

    def _rank(ids):
        best = 0
        for a in ids:
            c = final_cmds.get(a) or {}
            if c.get('value', 0.0) > _INTERLOCK_ON_PCT:
                best = max(best, _INTERLOCK_RANK.get(c.get('reason'), 0))
        return best

    pm = {p.actuator_id: p for p in profiles}

    def _cost(ids):
        vals = [pm[a].cost_fn({}, 50) for a in ids if a in pm]
        return min(vals) if vals else float('inf')

    c_rank, h_rank = _rank(cooler_ids), _rank(heater_ids)
    if c_rank != h_rank:
        cooler_wins = c_rank > h_rank
    else:
        cooler_wins = _cost(cooler_ids) <= _cost(heater_ids)

    losers = heater_ids if cooler_wins else cooler_ids
    for aid in losers:
        final_cmds[aid] = {'value': 0.0,
                           'reason': _LC.REASON_SAFETY_POST_GATE}
    return True


def apply_threshold_and_gate_overrides(
        internal: dict, profiles: list[ActuatorProfile], final_cmds: dict,
        partial_overrides: dict) -> None:
    """임계 오버라이드(광량·온습도) + 안전 프리게이트를 **정해진 순서로** 적용.

    순서가 곧 우선순위이며, 안전 프리게이트가 반드시 마지막(=최우선)이다.
    partial 게이트는 강풍 단독(풍향 차등 폐쇄) 또는 외부센서 만료 시 발동하는데,
    임계 오버라이드가 그 뒤에 오면 _force_cool 이 풍상측 개구부 폐쇄(opening=0)를
    100 으로 덮어써 강풍 속에 창을 활짝 열어버린다(한여름엔 실내 고온 + 강풍이
    동시에 오므로 실제로 발생 가능한 조합).

    게이트는 자신이 명령한 액추에이터만 덮으므로, 풍하측 개구부는 냉방을 위해
    계속 열릴 수 있다.

    육묘 분무 감쇠는 온습도 임계 뒤에 온다 — `humid_min` 이 분무를 100%로
    강제한 뒤에 깎아야 습도 하한 설정이 일소 위험을 무효화하지 못한다.
    안전 프리게이트(하드 잠금 포함)는 그보다 뒤, 여전히 최우선이다.

    이 순서 보장이 리팩터링으로 조용히 깨지는 것을 막으려고 한 함수로 묶었다.
    """
    apply_light_threshold_overrides(internal, profiles, final_cmds)
    apply_temp_humid_threshold_overrides(internal, profiles, final_cmds)
    apply_nursery_fog_derate(internal, profiles, final_cmds)
    # 감쇠(비율)보다 뒤 = 더 강한 규칙(0 으로 끊는다). 안전 프리게이트보다
    # 앞 = 게이트가 여전히 최우선.
    apply_wetting_fog_humidity_ceiling(internal, profiles, final_cmds)
    if partial_overrides:
        for aid, override in partial_overrides.items():
            final_cmds[aid] = override
    # 맞서는 짝 인터록은 **모든 것이 끝난 뒤**다 — 위 어느 단계든 충돌을 만들 수
    # 있고, 그중 임계 오버라이드는 실제로 만들었다(위 함수 주석 참조).
    apply_hvac_opposition_interlock(profiles, final_cmds)


class CycleMixin:
    """Mixin: one coordination cycle (L1 target → L2 situation → L3 coordinate → dispatch)."""

    # ── lazy-initialized helpers ──────────────────────────────────────────────
    @property
    def _feedback_registry(self) -> ActuatorFeedbackRegistry:
        if not hasattr(self, '_feedback_registry_inst'):
            self._feedback_registry_inst = ActuatorFeedbackRegistry()
        return self._feedback_registry_inst

    @property
    def _hygiene_checker(self) -> DataHygieneChecker:
        if not hasattr(self, '_hygiene_checker_inst'):
            wt = getattr(self, 'gate_wind_threshold', 5.0) or 5.0
            self._hygiene_checker_inst = DataHygieneChecker(wind_threshold=wt)
        return self._hygiene_checker_inst

    @property
    def _cal_registry(self) -> CalibrationRegistry:
        if not hasattr(self, '_cal_registry_inst'):
            cal_enabled = bool(getattr(self, 'calibration_enabled', False))
            self._cal_registry_inst = CalibrationRegistry(enabled=cal_enabled)
        return self._cal_registry_inst

    @property
    def _greybox_shadow(self) -> GreyboxShadow:
        if not hasattr(self, '_greybox_shadow_inst'):
            # 1순위: 학습·영속된 파라미터. 2순위: 설계 capacity_meta 프라이어.
            gb_params = None
            try:
                _gbp = (self._read_calibration_state() or {}).get('greybox_params')
                if _gbp:
                    gb_params = GreyboxParams.from_dict(_gbp)
                    self.logger.info(
                        'greybox params loaded from store: n=%s rmse_T=%s',
                        _gbp.get('n_updates'), _gbp.get('rmse_T'))
            except Exception:
                gb_params = None
            if gb_params is None:
                cap = {}
                for p in getattr(self, '_profiles', []):
                    if p.capacity_meta:
                        cap = p.capacity_meta
                        break
                gb_params = GreyboxParams.from_capacity_meta(cap)
            self._greybox_shadow_inst = GreyboxShadow(params=gb_params)
        return self._greybox_shadow_inst

    @property
    def _probe_scheduler(self) -> ActiveProbeScheduler:
        if not hasattr(self, '_probe_scheduler_inst'):
            probe_enabled  = bool(getattr(self, 'enable_active_probing', False))
            probe_interval = float(getattr(self, 'probe_interval_sec', 3600.0) or 3600.0)
            self._probe_scheduler_inst = ActiveProbeScheduler(
                interval_sec=probe_interval, enabled=probe_enabled)
        return self._probe_scheduler_inst

    def _compute_light_est(self, internal: dict, external: dict = None) -> None:
        """실내 추정 광량을 internal['light_est'] 에 채우고 육묘 설정을 함께 싣는다.

        실내 광센서가 없어 실외 일사가 그대로 들어온 경우에만(_light_is_outdoor)
        차광막 개도를 반영한 추정치로 바꾼다. 실내 센서가 있으면 이미 차광이
        반영된 값이므로 손대지 않는다.

        실외 일사는 유입구가 둘이다 — 시설 도면의 실외 센서(_collect_internal 이
        internal['light'] 로 넣는다)와 ext_context_collector 공유 컨텍스트
        (external['solar']). **둘 다 차광막 개도를 반영해야 한다.** 후자를
        빠뜨리면 같은 물리 상황에서 센서를 어느 수집기에 물렸느냐로 판정이
        갈린다 — 차광막을 완전히 닫아 실내가 210 W/m² 인데도 실외 원본
        700 W/m² 으로 일소 잠금이 걸리는 식이다. 차광막 투과율을 도입한
        목적(광량 맹점 제거) 자체가 그 경로에서만 무효가 된다.

        시설 실외 센서가 우선한다 — 더 가까운 실측이다.

        육묘 옵션(_nursery_*)도 여기서 internal 에 넣는다. 오버라이드 함수들이
        모듈 레벨 함수라 코디네이터 인스턴스에 접근할 수 없으므로, 기존
        `_force_*` 플래그와 같은 경로로 전달한다.
        """
        light_val  = internal.get('light')
        is_outdoor = bool(internal.get('_light_is_outdoor'))
        if light_val is None and external:
            # 일사 센서를 지정하지 않은 ext_context_collector 도 solar 를 0.0 으로
            # 채워 공유한다. 그 0.0 을 측정값으로 받으면 light_est 가 0 으로 굳어
            # 태양고도 어림값 폴백까지 막히므로, 양수만 측정값으로 인정한다.
            solar = external.get('solar')
            if solar is not None and solar > 0.0:
                light_val  = float(solar)
                is_outdoor = True
        if light_val is not None and is_outdoor:
            est = estimate_indoor_light(
                light_val, self._profiles, self._coord_state.prev_commands,
                default_tau=float(getattr(self, 'shade_transmittance', 0.0) or 0.0))
            if est != light_val and getattr(self, 'debug_logging', False):
                self.logger.debug(
                    '실내광 추정: 실외 %.0f → %.0f W/m² (차광막 개도 반영)',
                    light_val, est)
            light_val = est
        if light_val is not None:
            internal['light_est'] = light_val

        # 일소 임계와 광량 폴백은 **육묘 여부와 무관하게** 심는다. 습윤형
        # 분무기가 있으면 언제나 잠금·감쇠가 서야 하기 때문이다. 육묘 모드는
        # 그 위에서 더 조이는 축이다(임계 하향·짧은 펄스·저녁 차단).
        internal['_nursery_solar_lockout'] = float(
            getattr(self, 'nursery_solar_lockout', 250.0) or 250.0)
        internal['_nursery_solar_release'] = float(
            getattr(self, 'nursery_solar_release', 150.0) or 150.0)
        if light_val is None:
            internal['_nursery_light_fallback'] = self._clear_sky_light_fallback()

        if getattr(self, 'nursery_mode', False):
            internal['_nursery_mode'] = True
            if self._evening_fog_blocked():
                internal['evening_block'] = True

    def _clear_sky_light_fallback(self) -> float:
        """일사 센서가 전혀 없을 때 쓸 광량 어림값(W/m²). 못 구하면 None.

        일소 게이트는 광량을 모르면 잠그지 않는다 — 야간에 계속 잠겨 정상 가습까지
        막는 것이 더 해롭기 때문이다. 그런데 그 결과, **일사 센서가 없는 시설은
        일소 보호가 아예 꺼진 채로 돌아간다.** 육묘장에서 정오에 분무가 그대로
        나가는 상황이 조용히 성립한다.

        좌표만 있으면 태양고도로 맑은 날 기준 일사를 어림할 수 있다(§13.9).
        측정값이 아니므로 **측정값이 하나라도 있으면 절대 쓰지 않고**, 없을 때만
        차광막 개도를 반영해 실내 추정으로 환산한다. 맑은 하늘 가정이라 과대평가
        쪽이며, 이는 일소 보호에서 안전한 방향이다.
        """
        try:
            from aot.utils.solar import clear_sky_irradiance
            outdoor = clear_sky_irradiance(target_id=self.unique_id)
            if outdoor is None:
                return None
            return estimate_indoor_light(
                outdoor, self._profiles, self._coord_state.prev_commands,
                default_tau=float(getattr(self, 'shade_transmittance', 0.0) or 0.0))
        except Exception as exc:
            if getattr(self, 'debug_logging', False):
                self.logger.debug('맑은날 광량 어림 실패(폴백 없음): %s', exc)
            return None

    def _evening_fog_blocked(self) -> bool:
        """지금이 '일몰 전 분무 중단' 구간인가.

        관수는 보통 일출·일몰 두 시간대에 하는데, 저녁 분무는 잎이 젖은 채로
        밤을 넘기게 만든다. 엽면 습윤 지속 시간이 길수록 잿빛곰팡이·노균병
        위험이 커지고, 육묘장은 밀식이라 확산이 빠르다. 작물에 따라 저녁
        관수가 필요한 경우도 있으므로 사용자가 켜고 끌 수 있게 둔다.

        차단 구간: (일몰 − cutoff) ~ 다음 일출.
        태양시를 구하지 못하면(좌표 미설정 등) 차단하지 않는다 — 위치를
        모른다고 정상 가습까지 막으면 오히려 해롭다.
        """
        if getattr(self, 'nursery_evening_fog', True):
            return False   # 저녁 분무 허용 — 차단 안 함

        try:
            from aot.utils.solar import sun_times
            from aot.utils.timekit import utc_now
            st = sun_times(target_id=self.unique_id)
            if st is None or st.sunset is None:
                return False
            cutoff_min = float(getattr(self, 'nursery_evening_cutoff_min', 120.0) or 0.0)
            now = utc_now()
            block_from = st.sunset - timedelta(minutes=cutoff_min)
            if now >= block_from:
                return True
            # 자정을 넘긴 이른 새벽 — 아직 일출 전이면 계속 차단.
            if st.sunrise is not None and now < st.sunrise:
                return True
            return False
        except Exception as exc:
            if getattr(self, 'debug_logging', False):
                self.logger.debug('저녁 분무 차단 판정 실패 (차단 안 함): %s', exc)
            return False

    def _classify_emergency(
            self, gate_result: GateResult,
            situation: SituationReport) -> tuple[bool, str]:
        """이번 사이클이 '긴급'인지 판정 — 개구부 정상 구동주기를 우회할지 결정한다.

        긴급 판정 시 _dispatch() 는 actuation_profile 주기 대신 emergency_period_sec
        만 적용한다(완전 무시가 아니라 연타 방지 하한만 유지). 긴급 사유:
          1. 안전게이트 발동/부분발동 — 돌풍·강우·폭염·한파·센서만료(이미 SafetyPreGate 가 판정)
          2. 급격한 편차 — |deviation| >= tolerance × emergency_deviation_mult
          3. 급격한 변화율 — 내부온도 변화율 >= emergency_rate_c_per_10min (situation.context['T_trend'], °C/min)
          4. setpoint 변경 직후 1회 — cmd_reload/cmd_run_now 가 남긴 _force_immediate 플래그(1회성 소비)

        Returns: (is_emergency: bool, reason: str)
        """
        if getattr(self, '_force_immediate', False):
            self._force_immediate = False
            return True, 'setpoint_change'

        if gate_result.triggered or gate_result.partial:
            return True, 'safety_gate'

        mult = float(getattr(self, 'emergency_deviation_mult', 3.0) or 3.0)
        for var, dev in situation.deviation_native.items():
            tgt = situation.target.get(var)
            if tgt is None or tgt.tolerance <= 0:
                continue
            if abs(dev) >= tgt.tolerance * mult:
                return True, f'deviation:{var}'

        rate_thr = float(getattr(self, 'emergency_rate_c_per_10min', 2.0) or 2.0)
        t_trend_per_min = abs(situation.context.get('T_trend', 0.0) or 0.0)
        if (t_trend_per_min * 10.0) >= rate_thr:
            return True, 'T_rate'

        return False, ''

    def _collect_external_context(self, max_age):
        """이번 사이클의 **실외 컨텍스트**를 정한다.

        세 갈래가 같은 dict 를 순서대로 덮는다 — ext_context_collector 의
        공유 컨텍스트 · 시설 실외 센서(이긴다) · 값이 빈 사이클의 마지막
        실측 승계. 흩어 두면 "무엇이 이겼는가" 를 읽어서 알 수 없고, 이
        결함은 조용하다(지어낸 20°C/60% 가 제어로 흘러간 것이 그것이다).

        반환 `(external, outdoor_cache)` — 뒤엣것은 `_collect_internal` 에
        그대로 넘겨 같은 InfluxDB 조회를 두 번 하지 않게 한다.
        """
        # ── External context ──────────────────────────────────────────────────
        # 외부 환경 데이터는 facility 실외 센서(주력) 또는 ext_context_collector
        # (선택)에서 받는다. 먼저 ext_context_collector 공유 컨텍스트를 읽고,
        # facility 실외 센서가 있으면 아래에서 override 한다.
        try:
            from aot.functions.ext_context_collector import get_shared_context
            _shared = get_shared_context()
            if _shared:
                external = dict(_shared)
                # situation.py 는 'T'/'RH'/'CO2' 키를 읽으나 ext_context_collector 는
                # 'T_ext'/'RH_ext'/'CO2_ext' 로 저장하므로 양쪽 키를 맞춰준다.
                # **값이 없으면 키를 만들지 않는다** — 없는 실외값을 20°C/60% 로
                # 지어내면 아래 캐시 승계도, P2-2 의 fallback 컨텍스트도 발동하지
                # 못한 채 그 상수가 그대로 제어로 흘러간다(아래 긴 주석 참조).
                for _src, _dst in (('T_ext', 'T'), ('RH_ext', 'RH'), ('CO2_ext', 'CO2')):
                    _v = _shared.get(_src)
                    if _v is not None and _dst not in external:
                        external[_dst] = _v
            else:
                external = {}
        except Exception:
            external = {}

        # Facility outdoor sensors override external context values.
        # sensor_role='outdoor' fittings → T_ext/T, RH_ext/RH, wind, rain, solar.
        # read_outdoor_sensors() 는 여기서 한 번만 호출하고 결과를 _collect_internal
        # 에 전달해 중복 InfluxDB 쿼리를 방지한다.
        _outdoor_sr = getattr(self, '_sensors_resolved_outdoor', [])
        _od_cache: dict = {}
        if _outdoor_sr:
            try:
                from aot.aot_flask.geo.facility_sensors import read_outdoor_sensors
                _od_cache = read_outdoor_sensors(_outdoor_sr, max_age=int(max_age)) or {}
                _od_fresh = False
                # T/RH: 두 키 모두 채워 situation.py('T') 와 _build_gate_env('T_ext') 양쪽 호환
                if _od_cache.get('T_ext') is not None:
                    external['T_ext'] = _od_cache['T_ext']
                    external['T']     = _od_cache['T_ext']
                    _od_fresh = True
                if _od_cache.get('RH_ext') is not None:
                    external['RH_ext'] = _od_cache['RH_ext']
                    external['RH']     = _od_cache['RH_ext']
                    _od_fresh = True
                if _od_cache.get('CO2_ext') is not None:
                    external['CO2_ext'] = _od_cache['CO2_ext']
                    external['CO2']     = _od_cache['CO2_ext']
                    _od_fresh = True
                if _od_cache.get('rain_mm') is not None:
                    external['rain'] = _od_cache['rain_mm']
                    _od_fresh = True
                # wind/solar 도 external 에 반영 (situation.py 가 external.get('wind') 사용)
                if _od_cache.get('wind_ms') is not None:
                    external['wind'] = _od_cache['wind_ms']
                    _od_fresh = True
                if _od_cache.get('wind_deg') is not None:
                    external['wind_dir'] = _od_cache['wind_deg']
                if _od_cache.get('solar_wm2') is not None:
                    external['solar'] = _od_cache['solar_wm2']
                    _od_fresh = True
                # ── 마지막 유효 실외값을 기억한다 (2026-08-22) ─────────────────
                # 실외 센서가 값을 준 사이클에는 **무조건** 캐시를 채운다. 아래
                # `if not ext_stale:` 안에서만 갱신하면, ext_context_collector 가
                # 없는 설치에서는 캐시가 영원히 빈 채로 남는다 — `_shared` 가 {}
                # 라 `last_ext_ts` 가 0.0 이고, 그러면 `ext_stale` 이 항상 True 라
                # 갱신 분기에 도달하지 못하기 때문이다. 정작 값이 빈 순간에
                # 기댈 것이 없어진다.
                if (_od_cache.get('T_ext') is not None
                        or _od_cache.get('RH_ext') is not None):
                    self._ext_cache.update(
                        {k: v for k, v in external.items() if v is not None},
                        now=time.time())

                # facility 실외 센서가 신선한 값을 제공하면 외부 컨텍스트를 신선으로 갱신.
                # (직접 센서가 만료돼 동결됐더라도 facility 가 live source 이면 정상 처리)
                if _od_fresh:
                    external['last_ext_ts'] = time.time()
            except Exception:
                pass

        # ── 실외값이 이번 사이클에 비면 **마지막 유효값으로 잇는다** ────────────
        # 없는 값을 지어내는 것과 마지막 실측을 잠깐 더 쓰는 것은 전혀 다르다.
        # `situation.py` 는 external 에 'T'/'RH' 가 없으면 20°C/60% 를 기본값으로
        # 만들어 넣는데(그 파일의 EnvContext 구성부), 그 가짜 실외는 VPD 0.93 이라
        # 실내(0.32)보다 높다 → "창을 열면 건조해진다" 로 읽혀 환기 무익 게이트가
        # 풀리고 창이 열린다. 실제 실외(23°C/96%, VPD 0.11)면 정반대다.
        #
        # 2026-08-22 aot-005 새벽 창호 진동의 원인이 이것이다. 기상대 관측이
        # 간헐적으로 최대 31분 벌어지는데(중앙값 60초) `sensor_max_age`(1200초)를
        # 넘긴 사이클마다 이 가짜 실외가 들어가 40분 주기로 창이 열렸다 닫혔다 했다.
        # 실측 리플레이: 가짜 실외가 뜬 야간 사이클 10회 = 창이 열린 10회, 1:1 대응.
        # 고친 뒤 같은 입력에서 10회 → 0회.
        #
        # 밤사이 실외는 천천히 변하므로 20~30분 된 실측이 지어낸 상수보다 비교할
        # 수 없이 낫다. 캐시조차 비어 있으면 손대지 않는다 — 그 경우는 아래 P2-2
        # 의 fallback 컨텍스트가 맡는다. (판정은 `carry_forward_outdoor` 에 있다 —
        # 인라인으로 두면 단위 검증이 안 되고, 이 결함은 조용해서 검증이 필요하다.)
        _carried = carry_forward_outdoor(
            external, getattr(self._ext_cache, 'values', None) or {})
        if _carried and getattr(self, 'debug_logging', False):
            self.logger.debug(
                'EnvCoordinator: 실외 %s 를 마지막 유효값으로 승계 (관측 지연)',
                ','.join(_carried))
        return external, _od_cache

    def _run_cycle(self, cycle_sec: float) -> None:
        uid     = self.unique_id
        max_age = self.sensor_max_age or 120.0
        # 구획 목표는 사이클당 한 번만 읽는다. 항목마다 따로 읽으면 DB 를 여러
        # 번 치는 것도 문제지만, 그 사이에 값이 바뀌면 **한 사이클 안에서 서로
        # 다른 목표**를 보게 된다.
        self._plot_targets_cache = None
        self._crop_params_cache = None

        if not self._profiles:
            if getattr(self, 'debug_logging', False):
                self.logger.debug(
                    'EnvCoordinator: no actuators registered — skipping cycle')
            return

        # ── Schedule end gate ─────────────────────────────────────────────────
        # 종료 날짜가 지나면 제어를 정지한다: 각 액추에이터를 end_behavior 로
        # 복귀시키고 이후 사이클을 건너뛴다. Method 는 종료 전까지 실제 경과
        # 주차를 그대로 따른다.
        if self._schedule_ended():
            if not getattr(self, '_schedule_ended_logged', False):
                self.logger.info(
                    'EnvCoordinator: 종료 날짜(%s) 도달 — 제어 정지, '
                    '액추에이터 end_behavior 복귀', self.schedule_end_time)
                self._schedule_ended_logged = True
            self._apply_end_behaviors()
            return
        else:
            # 종료일 이전(또는 종료일 재설정)으로 복귀 시 재가동 로그 재무장
            if getattr(self, '_schedule_ended_logged', False):
                self._schedule_ended_logged = False
                self.logger.info(
                    'EnvCoordinator: 종료 날짜 이전 — 제어 재개')

        # ── Time window gate ──────────────────────────────────────────────────
        if self.time_enable and not self._in_time_window():
            self._apply_end_behaviors()
            return

        # ── External context ──────────────────────────────────────────────────
        external, _od_cache = self._collect_external_context(max_age)

        # P2-2: 외부 컨텍스트 신선도 확인 — 유효하면 캐시 갱신, 만료면 fallback 준비
        now_ts      = time.time()
        ext_max_age = self._pre_gate.config.ext_context_max_age if self._pre_gate else 300.0
        # 기본값은 0.0 이어야 한다. external 에 타임스탬프가 없다는 것은 "외부
        # 정보를 한 번도 받지 못했다" 는 뜻이지 "방금 받았다" 가 아니다. 예전처럼
        # now 를 기본값으로 쓰면 ext_context_collector 도 없고 시설 실외 센서도
        # 없는 설치에서 (now - now) = 0 이라 **영원히 fresh** 로 판정돼 fallback
        # 컨텍스트가 한 번도 작동하지 않는다.
        last_ext_ts = external.get('last_ext_ts', 0.0)
        ext_stale   = (now_ts - last_ext_ts) > ext_max_age

        if not ext_stale:
            self._ext_cache.update(external, now=now_ts)

        # ── Internal sensors ──────────────────────────────────────────────────
        # outdoor_data 전달 → _collect_internal 내부의 중복 read_outdoor_sensors 호출 생략
        internal = self._collect_internal(max_age, outdoor_data=_od_cache or None)
        if not internal:
            if getattr(self, 'debug_logging', False):
                self.logger.warning(
                    'EnvCoordinator: no internal sensor data — skipping cycle')
            return

        # P2-2: 외부 센서 만료 시 fallback 컨텍스트로 교체
        if ext_stale:
            stale_age = self._ext_cache.age(now_ts)
            if last_ext_ts <= 0.0:
                # 외부 소스 자체가 없는 설치 — "만료" 가 아니라 "미연결" 이다.
                self.logger.warning(
                    'EnvCoordinator: 외부 컨텍스트 없음(수집기·실외센서 모두 미연결) '
                    '— fallback 컨텍스트 사용')
            else:
                self.logger.warning(
                    'EnvCoordinator: 외부 센서 만료 %.0fs — fallback 컨텍스트 사용',
                    stale_age)
            external_for_control = build_fallback_context(
                self._ext_cache, internal, now_ts)
        else:
            external_for_control = external

        # ── 실내 추정 광량 ────────────────────────────────────────────────────
        # 육묘 일소 게이트와 광량 하드 임계가 같은 값을 봐야 하므로 여기서 한 번만
        # 계산해 internal['light_est'] 에 실어 둔다. Pre-Gate 가 이 값을 쓰기
        # 때문에 게이트 평가보다 앞서야 한다.
        # external 은 게이트와 같은 dict 를 넘긴다(아래 _build_gate_env 와 동일).
        # 실외 일사가 ext_context_collector 로만 들어오는 시설에서도 차광막
        # 투과율이 반영되게 하려면 이 인자가 필요하다.
        self._compute_light_est(internal, external)

        # ── Pre-Gate ──────────────────────────────────────────────────────────
        gate_env    = self._build_gate_env(internal, external)
        gate_result = self._pre_gate.evaluate(gate_env, self._profiles, uid)

        if gate_result.triggered:
            # 안전게이트 강제명령은 항상 즉시 반영 — 구동주기 설정(actuation_profile)의
            # 정상-사이클 최소 이동 간격에 지연되면 안 된다(강우·돌풍·폭염·한파 대응).
            self._dispatch(gate_result.forced_commands, cycle_sec, emergency=True)
            write_decision_log(uid, 'safety_gate_active',
                               CH_SAFETY_GATE, float(gate_result.gate_mask))
            # ── 심각 이벤트 이메일 알림 (1일 1회) ─────────────────────────────
            mask   = gate_result.gate_mask
            ext_t  = gate_env.get('external', {})
            int_t  = gate_env.get('internal', {})
            if mask & GATE_BIT_WIND:
                wind_v = ext_t.get('wind', 0.0)
                self._send_critical_email(
                    'wind_gate',
                    f'[돌풍 경보] 풍속 {wind_v:.1f} m/s 감지 — '
                    f'환기구 전체 강제 폐쇄 중. 시설 고정 상태를 점검하세요.',
                )
            if mask & GATE_BIT_RAIN:
                self._send_critical_email(
                    'rain_gate',
                    '[강우 경보] 강우 감지 — 환기구 폐쇄. '
                    '전기 장치 수분 노출 여부를 점검하세요.',
                )
            if mask & GATE_BIT_HEAT:
                T_e = ext_t.get('T', 0.0)
                T_i = int_t.get('T', 0.0)
                self._send_critical_email(
                    'extreme_heat',
                    f'[폭염 경보] 외부 {T_e:.1f}°C / 내부 {T_i:.1f}°C — '
                    f'냉방 장치 최대 가동 중. 그늘막·차광 설비를 점검하세요.',
                )
            if mask & GATE_BIT_COLD:
                T_e = ext_t.get('T', 0.0)
                T_i = int_t.get('T', 0.0)
                self._send_critical_email(
                    'extreme_cold',
                    f'[한파 경보] 외부 {T_e:.1f}°C / 내부 {T_i:.1f}°C — '
                    f'난방 장치 최대 가동 중. 보온재 및 배관 동결 여부를 점검하세요.',
                )
            # ── 게이트로 멈춰도 **말은 해야 한다** (2026-08-26) ───────────────
            # 이 경로는 L1~L3 앞에서 반환하므로 `_build_cycle_summary` 가 돌지
            # 않는다. 그러면 요약의 `ts` 가 안 갱신되고, 화면은 그것을 보고
            # **"자동 제어가 응답하지 않습니다"** 라고 말한다 — 제어는 매 사이클
            # 정상 실행 중인데도.
            #
            # 가장 알려야 할 순간에 화면이 정반대를 말하는 셈이다. "지금 비가
            # 와서 창을 닫았습니다" 가 나와야 할 자리이고, 게다가 **진짜로
            # 죽었을 때와 구분되지 않는다**(실측: 강우 게이트 45분 → 화면은
            # 응답 없음).
            #
            # ⚠ 여기에는 `situation` 이 없다(L2 전이다). 그래서 전체 요약을
            #   쓸 수 없고 **게이트 사실만** 담은 축소 요약을 쓴다. 환경 값은
            #   이 사이클의 것이 아니므로 싣지 않는다 — 낡은 값을 지금 값으로
            #   보이게 하는 것이 침묵보다 나쁘다. 화면은 `gate_only` 를 보고
            #   "환경 데이터는 이 사이클의 것이 아님" 을 말한다.
            self._write_gate_only_summary(gate_result, gate_env, now_ts)
            return
        elif gate_result.gate_mask == 0:
            # P6: integral 은 액추에이터별 평형 개도(%) 기억이므로 매 사이클 지우지
            # 않는다(지우면 평형 hold 불가 → 진동 재발). [0,100] 클램프 + 자기복원
            # 으로 폭주 위험이 없다. active_vars(hysteresis 텔레메트리)만 정리.
            self._coord_state.active_vars.clear()

        # partial=True: EXT_EXP 단독 또는 풍향 차등 모드.
        # L1~L3 정상 실행 후 _dispatch 직전 forced_commands 를 override 로 적용.
        partial_overrides = (gate_result.forced_commands
                             if gate_result.partial else {})

        self._check_hard_constraints(internal)

        # ── L1: EnvTarget (VPD-primary) ───────────────────────────────────────
        vpd_t = self._get_vpd_setpoint()
        co2_t = self._get_co2_setpoint()

        # Guide 범위
        T_g_min  = self.guide_T_min  if self.guide_T_min  is not None else 12.0
        T_g_max  = self.guide_T_max  if self.guide_T_max  is not None else 32.0
        RH_g_min = self.guide_RH_min if self.guide_RH_min is not None else 40.0
        RH_g_max = self.guide_RH_max if self.guide_RH_max is not None else 85.0

        # 하드 임계는 **목표의 한계**다 — 판정은 아래 모듈 함수 하나에 있다.
        (T_g_min, T_g_max, RH_g_min, RH_g_max), _clamped = \
            clamp_guide_range_to_hard_limits(
                (T_g_min, T_g_max, RH_g_min, RH_g_max),
                temp_min=self.temp_min, temp_max=self.temp_max,
                humid_min=self.humid_min, humid_max=self.humid_max)
        # ⚠ **매 사이클 찍지 않는다.** 설정이 안 바뀌면 같은 줄이 영원히 쌓여
        #   정작 읽어야 할 로그를 밀어낸다. 바뀔 때만 한 번 — 사용자가 자기
        #   설정이 좁혀졌다는 것을 알아야 한다.
        # ⚠ **`warning` 이 아니라 `error` 다.** 컨트롤러 로거는 `log_level_debug`
        #   가 꺼져 있으면 레벨이 ERROR 라(`base_controller.py`), warning 으로
        #   찍으면 **기본 설치에서 아무 데도 안 남는다** — 알리려고 만든 줄이
        #   정확히 알려야 할 사람에게만 안 보인다. 등급을 올리는 근거는 두 가지다:
        #   설정 모순이라 사람이 고쳐야 하고, 한 번만 찍으므로 시끄럽지 않다.
        _clamp_key = ','.join(_clamped)
        if _clamp_key != getattr(self, '_last_guide_clamp', None):
            if _clamped:
                self.logger.error(
                    '유도 범위가 하드 임계를 넘어 좁혔습니다 (%s) — '
                    '설정한 목표 범위가 그대로 쓰이지 않습니다. '
                    '유도 범위와 온습도 상·하한 설정을 맞춰 주세요.', _clamp_key)
            self._last_guide_clamp = _clamp_key

        self._warn_inert_options_once()

        T_int  = internal.get('T',  22.0)
        RH_int = internal.get('RH', 60.0)

        if vpd_t and vpd_t > 0.0:
            # VPD → (T_aux, RH_aux) 분해 후 guide 범위 클램프
            w_T = self.vpd_weight_T if self.vpd_weight_T is not None else 0.6
            T_aux, RH_aux = decompose_vpd_to_T_RH(
                vpd_target=vpd_t,
                T_int=T_int,
                RH_int=RH_int,
                w_T=w_T,
            )
            T_aux  = max(T_g_min, min(T_g_max,  T_aux))
            RH_aux = max(RH_g_min, min(RH_g_max, RH_aux))
        else:
            # VPD 타겟 없을 때 guide 중앙값 사용
            T_aux  = (T_g_min + T_g_max)  / 2.0
            RH_aux = (RH_g_min + RH_g_max) / 2.0

        env_target = build_env_target(
            T_target   = T_aux,
            T_tol      = 1.0,
            T_pri      = 0.5,
            RH_target  = RH_aux,
            RH_tol     = 5.0,
            RH_pri     = 0.5,
            CO2_target = co2_t or 1000.0,
            CO2_tol    = self.tolerance_co2 or 100.0,
            CO2_pri    = self.priority_co2  or 0.8,
            VPD_target = vpd_t,
            VPD_tol    = self.tolerance_vpd or 0.1,
            VPD_pri    = self.priority_vpd  or 1.2,
        )
        if co2_t is None:
            env_target.pop('co2', None)

        self._apply_forecast_feedforward(env_target, internal, T_int, RH_int)

        # 목표값/우선순위는 write_cycle_metrics(env_control, CH20~27)로 일원화 기록.

        # ── P5-2: Control Authority 도출 (매 사이클 — 프로파일 변경 대응) ─────
        authority = derive_authority(self._profiles)
        # 상태 변화 시에만 기록: None(초기) 또는 내용이 바뀐 경우.
        # `not dict` 는 빈 dict({})도 True 이므로 is None 으로 정확히 비교한다.
        if getattr(self, '_last_authority', None) is None:
            self.logger.info(
                'EnvCoordinator authority: %s', authority_summary(authority))
        elif authority != self._last_authority:
            self.logger.info(
                'EnvCoordinator authority changed: %s', authority_summary(authority))
        self._last_authority = authority

        self._apply_photosynthesis_priority(env_target, internal, authority)

        # ── L2: SituationReport ───────────────────────────────────────────────
        situation, self._trend_state = assess(
            env_target=env_target,
            internal=internal,
            external=external_for_control,
            cycle_sec=cycle_sec,
            now_ts=time.time(),
            last_ext_ts=external.get('last_ext_ts'),
            last_int_ts=None,
            trend_state=self._trend_state,
            authority=authority,
            light_sat=self.light_max if (self.light_max and self.light_max > 0) else None,
        )

        # ── 습윤형 분무 습도 상한 판정 ──────────────────────────────────────
        # `_check_hard_constraints`(정적 humid_max)와 달리 **여기서** 판정한다 —
        # 유효 목표는 프로그램·VPD 분해를 거쳐 `assess` 가 정하므로, 함수 옵션의
        # `target_humidity` 로 판정하면 실제로 쓰인 목표와 어긋난다(실측: 설정
        # 65.0 인데 유효 목표 62.5).
        #
        # ⚠ **VPD 직접 제어 모드에서는 'humidity' 키가 없다.** VPD 목표+측정이
        # 둘 다 있으면 `situation._decompose_vpd` 가 'humidity'/'temperature' 를
        # 제어목표에서 빼고 `_humidity_constraint`/`_temperature_constraint` 로
        # 이름만 바꿔 진단용으로 남긴다(TargetVar 는 그대로). 원래 코드는
        # 'humidity' 만 봐서 VPD 모드가 걸린 뒤로 **항상 "목표 없음"으로 빠져
        # 게이트가 한 번도 서지 않았다** — 습도 91%(목표+허용오차 대비 초과)에서
        # 분무 67% 가 그대로 나간 실사고로 발견했다(2026-08-25 イチゴ).
        # 값·허용오차는 옮겨진 뒤에도 같은 TargetVar 이므로 폴백으로 집는다.
        _rh_now = internal.get('RH')
        _rh_tv = ((situation.target or {}).get('humidity')
                 or (situation.target or {}).get('_humidity_constraint'))
        if _rh_now is not None and _rh_tv is not None and _rh_tv.tolerance > 0:
            _ceiling = float(_rh_tv.value) + float(_rh_tv.tolerance)
            _cbs = self._constraint_breach_state
            _cbs['fog_RH'] = latch_threshold(
                float(_rh_now), _ceiling, RH_HYST_PCT, _cbs.get('fog_RH', False),
                'max')
            if _cbs['fog_RH']:
                internal['_fog_humidity_block'] = True
        else:
            # 습도 목표가 없으면 막을 근거가 없다 — 종전대로 둔다.
            self._constraint_breach_state['fog_RH'] = False

        # 개구부 파킹 관련 옵션 — coordinator 가 ctx 에서 읽는다. ctx 경유인
        # 이유는 coordinate() 시그니처를 늘리지 않기 위해서다(vent_open_frac 과
        # 같은 방식).
        situation.context['vent_futility_gate'] = bool(
            getattr(self, 'vent_futility_gate', True))
        _interlock = bool(getattr(self, 'hvac_interlock', False))
        situation.context['hvac_interlock'] = _interlock
        situation.context['hvac_running'] = (
            self._hvac_running(self._coord_state.prev_commands)
            if (_interlock and getattr(self, '_coord_state', None) is not None)
            else False)
        # `hvac_interlock` 의 짝 — 환기로 닿을 수 있으면 냉난방을 쓰지 않는다.
        situation.context['vent_first'] = bool(getattr(self, 'vent_first', False))
        # 야간에는 개구부만 닫고 냉난방·제습으로 관리한다. 하드 임계를 넘으면
        # 스스로 풀린다(`_night_vent_parked` 의 탈출구).
        situation.context['night_vent_park'] = self._night_vent_parked(internal)

        # 편차/모드/제한인자는 write_cycle_metrics(env_control, CH30~32·71·72)로 일원화 기록.

        # ── 구동주기: 이번 사이클이 긴급인지 판정 ─────────────────────────────
        # 긴급이면 개구부 정상-사이클 최소 이동 간격(actuation_profile)을 건너뛰고
        # emergency_period_sec 만 적용해 즉시 반영한다.
        self._emergency_now, self._emergency_reason = self._classify_emergency(
            gate_result, situation)

        # ── P5-3: Passive/Natural 알림 ────────────────────────────────────────
        self._emit_authority_alerts(situation)

        # ── Stage 1: calibrated_K 주입 (학습값 있을 때만) ────────────────────
        if self._cal_registry.enabled:
            for p in self._profiles:
                k_all = {
                    var: kv
                    for var in ('temperature', 'humidity', 'co2', 'vpd')
                    if (kv := self._cal_registry.k_hat(p.actuator_id, var)) is not None
                }
                if k_all:
                    p.calibrated_K = k_all   # effect_functions._calibrated_k 가 읽음

        # ── Effect engine 선택 (legacy / greybox 물리 제어) ──────────────────
        # greybox 모드 + 게이트 통과 시 effect_model 을 물리 어댑터로 교체. coordinator
        # 의 PI·slew·conflict·anti-windup 안전로직은 그대로 재사용된다.
        self._greybox_active = self._apply_effect_engine(situation)

        # ── slew 기준을 장치 실제 위치로 동기화 (위치 desync 방지) ──────────────
        # 코디네이터 prev_commands 와 장치 last_position_pct 가 어긋나면 반대로
        # 움직이므로, 제어 직전에 장치 실측 위치로 맞춘다.
        self._sync_prev_from_devices()

        # ── 이 사이클의 전달 비율을 프로필에 싣는다 (coordinate() 앞) ──────────
        # 명령이 요구대로 다 못 나가는 물리 제약은 **코디네이터가 알아야 한다**.
        # 예전에는 coordinate() 뒤에서 명령에 직접 곱했는데, 그러면 코디네이터는
        # 원래 값이 나갔다고 믿어 적분이 영영 수렴하지 못하고 부하분담에도
        # 과장된 효과가 실린다. 실측 두 건이 같은 모양이었다(2026-08-26 イチゴ):
        #   側面窓右  24.6% 명령 / 5.0% 실제  — 풍향 가중치 0.2 를 밖에서 곱함
        #   バルブ3   61%   명령 / 0%   실제  — 습도 상한 게이트가 밖에서 끊음
        # 후자는 적분이 64.3 에 실린 채 얼어붙어, 게이트가 풀리는 순간 분무가
        # 60% 로 튀어나오는 상태였다.
        self._apply_cmd_scales(internal, external)

        # ── L3: Coordination (MPC → greybox-PI → legacy) ──────────────────────
        commands, new_state = self._run_control(situation, uid)
        self._coord_state = new_state

        # ── P2-4: 복합 액추에이터 그룹 명령 확장 ──────────────────────────────────
        if self._groups:
            commands = expand_group_commands(
                commands, self._groups, new_state.prev_commands)

        # (D1 풍향 가중치는 coordinate() **앞**의 `_apply_cmd_scales` 로 옮겼다.
        #  여기서 곱하면 코디네이터가 그 사실을 배우지 못한다 — 위 주석 참조.)

        # ── Stage 1: 능동 탐색 적용 ──────────────────────────────────────────
        # Post-Gate **앞**이어야 한다. 예전에는 뒤에 있었는데, final_cmds 는
        # Post-Gate 가 만든 별개 dict 라 여기서 commands 를 고쳐 봐야 전송 대상에
        # 닿지 않았다 — 능동 탐색이 로그에는 찍히고 장치에는 나가지 않았다.
        # 앞에 두면 탐색 값도 Post-Gate 의 NaN/범위 검증을 함께 받는다.
        probe_cmd_pcts = {
            aid: (c.value if hasattr(c, 'value') else c.get('value', 0.0))
            for aid, c in commands.items()
        }
        probe_cmd_pcts, is_probe = self._probe_scheduler.step(
            commands=probe_cmd_pcts,
            profiles=self._profiles,
            situation=situation,
            gate_triggered=gate_result.triggered,
        )
        if is_probe:
            from aot.functions.utils.env_control.coordinator import ActuatorCommand
            from aot.functions.utils.env_control.log_channels import REASON_PRIMARY
            for aid, pct in probe_cmd_pcts.items():
                if aid in commands and abs(pct - commands[aid].value) > 0.5:
                    commands[aid] = ActuatorCommand(value=pct, reason=REASON_PRIMARY,
                                                    var_source='probe')

        # ── 0.4: circulation_fan 독립 제어 ────────────────────────────────────
        # circulation_fan 은 coordinator effect 방향 '~' 로 인해 coordinator 가
        # 선택하지 못함. T 공간 불균일 감지 시 독립 룰로 ON/OFF 결정.
        # 이것도 Post-Gate 앞이다. 뒤에서 final_cmds 를 고치면 전송은 되지만
        # write_cycle_metrics(commands) 에 잡히지 않아 결정 근거를 추적할 수 없고,
        # dict 규약인 final_cmds 에 ActuatorCommand 를 섞어 타입도 흐트러뜨렸다.
        self._apply_mixing_actuators(commands, internal)

        # ── Post-Gate ─────────────────────────────────────────────────────────
        final_cmds, _ = self._post_gate.check(
            {aid: {'value': c.value, 'reason': c.reason}
             for aid, c in commands.items()},
            self._profiles,
            uid,
        )

        # ── 임계 오버라이드 + 안전 프리게이트 (순서 보장은 헬퍼 안에) ───────────
        apply_threshold_and_gate_overrides(
            internal, self._profiles, final_cmds, partial_overrides)

        # ── P1-3: 사이클 메트릭 일괄 기록 (debug_logging 활성 시에만) ─────────────
        if getattr(self, 'debug_logging', False):
            ctx_metrics = {
                'T_int':    internal.get('T',        0.0),
                'RH_int':   internal.get('RH',       0.0),
                'VPD_int':  internal.get('VPD',      0.0),
                'CO2_int':  internal.get('CO2',      0.0),
                'T_ext':    external.get('T_ext',    0.0),
                'RH_ext':   external.get('RH_ext',   0.0),
                'wind':     internal.get('wind',     external.get('wind',     0.0)),
                'wind_dir': internal.get('wind_dir', external.get('wind_dir', 0.0)),
                'rain':     external.get('rain',     0.0),
            }
            write_cycle_metrics(
                unique_id=uid,
                ctx=ctx_metrics,
                target=env_target,
                deviation=situation.deviation_native,
                commands=commands,
                limiting_factor=situation.limiting_factor,
                modes=situation.modes,
                facility_id=self.geo_facility_id_device_id or None,
            )

        failed = self._dispatch(final_cmds, cycle_sec, emergency=self._emergency_now)

        # ── 0.1: 피드백 레지스트리 업데이트 ──────────────────────────────────
        now_ts = time.time()
        for aid, cmd in final_cmds.items():
            val = (cmd.get('value', 0.0) if isinstance(cmd, dict)
                   else getattr(cmd, 'value', 0.0))
            self._feedback_registry.record_dispatch(
                aid, val, success=(aid not in failed), ts=now_ts)

        # ── 0.1: 의심 액추에이터 로깅 ─────────────────────────────────────────
        suspicious = self._feedback_registry.suspicious_ids()
        if suspicious:
            self.logger.warning(
                'EnvCoordinator: 신뢰도 낮은 액추에이터 %d개 — %s',
                len(suspicious), suspicious[:5])
        if getattr(self, 'debug_logging', False):
            write_decision_log(self.unique_id, 'actuator_mismatch_count',
                               CH_ACTUATOR_MISMATCH, float(len(suspicious)))

        self._finalize_cycle(_CycleContext(
            uid=uid,
            internal=internal,
            external=external,
            external_for_control=external_for_control,
            env_target=env_target,
            situation=situation,
            authority=authority,
            gate_result=gate_result,
            commands=commands,
            final_cmds=final_cmds,
            is_probe=is_probe,
        ))

    def _apply_cmd_scales(self, internal: dict, external: dict) -> None:
        """이 사이클에 명령이 실제로 전달되는 비율을 프로필에 싣는다.

        `coordinate()` 는 `finalize_command` 에서 이 값을 곱하므로, 슬루·부하분담·
        anti-windup 이 전부 **실제로 나가는 값**을 기준으로 돈다. 반대로 이것을
        `coordinate()` 뒤에서 곱하면 코디네이터는 원래 값이 나갔다고 믿는다 —
        적분이 수렴하지 못하고, 제약이 풀리는 순간 쌓인 적분이 계단으로 튀어나온다.

        ⚠ **매 사이클 전부 1.0 으로 되돌린 뒤 다시 채운다.** 남겨 두면 바람이
        멎거나 게이트가 풀린 뒤에도 옛 제약이 계속 걸린다.
        """
        for p in self._profiles:
            p.cmd_scale = 1.0

        # ── 습윤형 분무: 습도 상한 게이트 ────────────────────────────────────
        # 잎을 적시는 분무는 습도가 이미 넘쳤을 때 쓰지 않는다(잿빛곰팡이).
        # 판정은 `assess` 뒤에서 이미 끝나 있다 — 여기서는 그 결론만 싣는다.
        if internal.get('_fog_humidity_block'):
            for p in self._profiles:
                if is_wetting_fogger(p):
                    p.cmd_scale = 0.0

        # ── 개구부: 풍향 가중치 (D1) ────────────────────────────────────────
        # 풍속을 함께 넘긴다 — 무풍이면 풍압이 없으므로 깎을 근거가 없는데,
        # 기상 소스가 무풍일 때 풍향을 0.0(정북)으로 내보내면 북향이 아닌 측창이
        # 영구히 leeward 로 판정돼 하한 0.2 에 갇힌다(2026-08-26 실측).
        _vos = getattr(self, '_vent_openings', [])
        _wind_dir = internal.get('wind_dir', external.get('wind_dir'))
        if not _vos or _wind_dir is None:
            return
        from aot.aot_flask.geo.facility_wind import wind_biased_opening
        _speed = internal.get('wind', external.get('wind'))
        _bias = wind_biased_opening(
            _vos, float(_wind_dir),
            getattr(self, '_facility_orientation_deg', 0.0),
            wind_speed_ms=None if _speed is None else float(_speed))
        for p in self._profiles:
            if p.kind != 'opening':
                continue
            w = _bias.get(p.actuator_id)
            if w is not None:
                p.cmd_scale = min(p.cmd_scale, max(0.0, min(1.0, float(w))))

    def _apply_forecast_feedforward(
            self, env_target: dict, internal: dict,
            T_int: float, RH_int: float) -> None:
        """기상 예보로 목표를 선제 보정한다(피드포워드).

        env_target 을 제자리에서 고치고 self._last_ff_signal 에 신호를 남긴다.
        가이드 범위(guide_T_min 등)는 사이클 중 바뀌지 않으므로 여기서 다시
        읽어도 값이 달라지지 않는다.
        """
        T_g_min  = self.guide_T_min  if self.guide_T_min  is not None else 12.0
        T_g_max  = self.guide_T_max  if self.guide_T_max  is not None else 32.0
        RH_g_min = self.guide_RH_min if self.guide_RH_min is not None else 40.0
        RH_g_max = self.guide_RH_max if self.guide_RH_max is not None else 85.0
        # ── P3-4: Forecast Feedforward ────────────────────────────────────────
        if getattr(self, 'forecast_feedforward_enabled', False):
            _forecast_bindings = getattr(self, '_sensors_forecast', [])
            if _forecast_bindings:
                # facility weather_bindings 경로 — 서비스 무관 범용 경로
                try:
                    from aot.aot_flask.geo.facility_sensors import read_forecast_sensors
                    _fc_data = read_forecast_sensors(_forecast_bindings)
                except Exception:
                    _fc_data = {}
                ff_sig = build_feedforward_signal_from_forecast(
                    forecast       = _fc_data,
                    T_int          = T_int,
                    RH_int         = RH_int,
                    wind_threshold = self.gate_wind_threshold or 12.0,
                )
            else:
                # fallback: KMA forecast.json 파일 경로 (하위 호환)
                ff_sig = build_feedforward_signal(
                    T_int          = T_int,
                    RH_int         = RH_int,
                    lookahead_h    = getattr(self, 'forecast_lookahead_h', 3.0) or 3.0,
                    wind_threshold = self.gate_wind_threshold or 12.0,
                )
            if ff_sig.valid and ff_sig.reason != '정상 범위':
                if getattr(self, 'debug_logging', False):
                    self.logger.debug('Feedforward: %s', ff_sig.reason)
                apply_feedforward(
                    env_target,
                    ff_sig,
                    T_g_min=T_g_min, T_g_max=T_g_max,
                    RH_g_min=RH_g_min, RH_g_max=RH_g_max,
                )
                # 환기 억제 신호를 internal에 전달 → safety_gates에서 참조 가능
                if ff_sig.wind_inhibit:
                    internal['_ff_wind_inhibit'] = True
            self._last_ff_signal = ff_sig
        else:
            self._last_ff_signal = FeedforwardSignal()

    def _apply_photosynthesis_priority(
            self, env_target: dict, internal: dict, authority: dict) -> None:
        """광합성 모드에서 제한 인자를 찾아 해당 변수의 우선순위를 격상한다.

        env_target 을 제자리에서 고친다(반환 없음). 제어권이 없는 변수는
        격상해도 소용없으므로 authority 를 함께 본다.
        """
        # ── P5-4: Photosynthesis-oriented priority 격상 ───────────────────────
        if self.photosynth_mode_enabled and internal.get('light') is not None:
            from aot.functions.utils.env_control.photosynthesis import (
                boost_limiting_priority, decay_priorities,
                find_limiting_factor, ppfd_from_wm2,
            )
            crop = self._crop_params()
            vpd_now = internal.get('VPD') or 0.0
            limiting = find_limiting_factor(
                # ⚠ 단위 경계. internal['light'] 는 W/m²(전천일사)인데 crop 의
                # K_L 은 µmol/m²/s 다 — 변환 없이 넣으면 다른 단위를 같은 축에서
                # 비교하게 되고, 광이 제한 인자인지 아닌지가 통째로 뒤집힌다.
                L=ppfd_from_wm2(internal.get('light', 0.0)),
                CO2=internal.get('CO2', 400.0),
                T=internal.get('T', 22.0),
                VPD=vpd_now,
                crop_params=crop,
            )
            base_priorities = {
                'temperature': self.priority_vpd  or 0.5,   # T 추적 우선순위 = vpd 기반
                'humidity':    0.5,
                'co2':         self.priority_co2  or 0.8,
                'vpd':         self.priority_vpd  or 1.2,
                'light':       0.9,
            }
            boost_limiting_priority(
                env_target=env_target,
                limiting_factor=limiting,
                authority=authority,
                priority_ewa_state=self._priority_ewa_state,
                base_priorities=base_priorities,
            )
            if getattr(self, 'debug_logging', False):
                self.logger.debug(
                    'Photosynthesis limiting factor: %s', limiting)
        elif self.photosynth_mode_enabled:
            # 광 센서 없음 — 우선순위 기본값으로 복귀
            from aot.functions.utils.env_control.photosynthesis import decay_priorities
            base_priorities = {
                'temperature': 0.5, 'humidity': 0.5,
                'co2': self.priority_co2 or 0.8,
                'vpd': self.priority_vpd or 1.2,
            }
            decay_priorities(env_target, self._priority_ewa_state, base_priorities)

    def _check_hard_constraints(self, internal: dict) -> None:
        """온습도·광량 하드 임계를 히스테리시스 래치로 판정한다.

        위반 시 internal 에 _force_cool/_force_heat/_force_dehumid/_force_humid,
        _force_shade/_force_suplight 플래그를 심는다. 이 플래그는 L3 뒤의
        임계 오버라이드(apply_*_threshold_overrides)가 소비한다.

        래치 상태(self._constraint_breach_state/_light_breach_state)는 사이클
        간에 유지된다 — 진입 문턱과 해제 문턱을 비대칭으로 두어 경계에서
        액추에이터가 왕복하는 것을 막는다.
        """
        # ── T/RH constraint check (before L1) ────────────────────────────────
        t_val  = internal.get('T')
        rh_val = internal.get('RH')
        # Per-cycle WARN spam → state-transition only. Re-arm when value returns
        # to within bounds, so the next breach is logged again.
        cbs = self._constraint_breach_state

        if t_val is not None:
            if self.temp_max:
                breached = latch_threshold(t_val, self.temp_max, TEMP_HYST_C,
                                           cbs['T_max'], 'max')
                if breached:
                    if not cbs['T_max']:
                        self.logger.warning(
                            'T=%.1f > max=%.1f — forcing cooling', t_val, self.temp_max)
                    internal['_force_cool'] = True
                elif cbs['T_max'] and getattr(self, 'debug_logging', False):
                    self.logger.debug(
                        'T=%.1f — max=%.1f 강제 해제(히스테리시스 %.1f)',
                        t_val, self.temp_max, TEMP_HYST_C)
                cbs['T_max'] = breached
            if self.temp_min:
                breached = latch_threshold(t_val, self.temp_min, TEMP_HYST_C,
                                           cbs['T_min'], 'min')
                if breached:
                    if not cbs['T_min']:
                        self.logger.warning(
                            'T=%.1f < min=%.1f — forcing heating', t_val, self.temp_min)
                    internal['_force_heat'] = True
                elif cbs['T_min'] and getattr(self, 'debug_logging', False):
                    self.logger.debug(
                        'T=%.1f — min=%.1f 강제 해제(히스테리시스 %.1f)',
                        t_val, self.temp_min, TEMP_HYST_C)
                cbs['T_min'] = breached
        if rh_val is not None:
            if self.humid_max:
                breached = latch_threshold(rh_val, self.humid_max, RH_HYST_PCT,
                                           cbs['RH_max'], 'max')
                if breached:
                    internal['_force_dehumid'] = True
                cbs['RH_max'] = breached
            if self.humid_min:
                breached = latch_threshold(rh_val, self.humid_min, RH_HYST_PCT,
                                           cbs['RH_min'], 'min')
                if breached:
                    internal['_force_humid'] = True
                cbs['RH_min'] = breached

        # ── Light threshold constraint check ──────────────────────────────────
        # 실내 추정 광량은 사이클 앞에서 _compute_light_est() 가 이미 계산했다.
        light_val = internal.get('light_est', internal.get('light'))
        lbs = self._light_breach_state
        if light_val is not None:
            dbg = getattr(self, 'debug_logging', False)
            if self.light_max and self.light_max > 0:
                breached = latch_threshold(
                    light_val, self.light_max, self.light_max * LIGHT_HYST_FRAC,
                    lbs['max'], 'max')
                if breached:
                    if not lbs['max'] and dbg:
                        self.logger.debug(
                            'light=%.0f > max=%.0f — forcing shade',
                            light_val, self.light_max)
                    internal['_force_shade'] = True
                elif lbs['max'] and dbg:
                    self.logger.debug(
                        'light=%.0f — max=%.0f 차광강제 해제(히스테리시스 %.0f)',
                        light_val, self.light_max, self.light_max * LIGHT_HYST_FRAC)
                lbs['max'] = breached
            if self.light_min and self.light_min > 0:
                breached = latch_threshold(
                    light_val, self.light_min, self.light_min * LIGHT_HYST_FRAC,
                    lbs['min'], 'min')
                if breached:
                    if not lbs['min'] and dbg:
                        self.logger.debug(
                            'light=%.0f < min=%.0f — forcing supplemental light',
                            light_val, self.light_min)
                    internal['_force_suplight'] = True
                elif lbs['min'] and dbg:
                    self.logger.debug(
                        'light=%.0f — min=%.0f 보광강제 해제(히스테리시스 %.0f)',
                        light_val, self.light_min, self.light_min * LIGHT_HYST_FRAC)
                lbs['min'] = breached

    def _finalize_cycle(self, ctx: '_CycleContext') -> None:
        """사이클 꼬리 — 학습·누적·상태 저장. 제어 명령은 이미 나간 뒤다.

        데이터 위생 판정, 캘리브레이션 push, 누적 목표 추적, greybox shadow,
        커미셔닝 앵커 폴링, 런타임 스냅샷, PI 상태 DB 저장을 순서대로 한다.
        모두 이번 사이클의 **결과를 소비**할 뿐 명령을 바꾸지 않는다 — 그래서
        _run_cycle 에서 통째로 떼어낼 수 있었다.

        지역변수 이름을 그대로 되살려 본문을 한 글자도 바꾸지 않았다. 727줄
        짜리 제어 사이클을 쪼개는 중이라, 각 단계에서 '옮기기만 했다' 를
        보장하는 편이 검토와 되돌리기 모두 쉽다.
        """
        uid = ctx.uid
        internal = ctx.internal
        external = ctx.external
        external_for_control = ctx.external_for_control
        env_target = ctx.env_target
        situation = ctx.situation
        authority = ctx.authority
        gate_result = ctx.gate_result
        commands = ctx.commands
        final_cmds = ctx.final_cmds
        is_probe = ctx.is_probe

        # ── 0.5: 데이터 위생 체크 + 로깅 ─────────────────────────────────────
        current_cmd_pcts = {
            aid: (cmd.get('value', 0.0) if isinstance(cmd, dict)
                  else getattr(cmd, 'value', 0.0))
            for aid, cmd in final_cmds.items()
        }
        clean = self._hygiene_checker.check(external, internal, current_cmd_pcts)
        if getattr(self, 'debug_logging', False):
            write_decision_log(self.unique_id, 'clean_for_learning',
                               CH_CLEAN_FOR_LEARNING, 1.0 if clean else 0.0)
        self._last_clean_for_learning = clean

        # ── Stage 1: CalibrationRegistry push_cycle ───────────────────────────
        if self._cal_registry.enabled:
            sensor_snapshot = {
                'temperature': internal.get('T'),
                'humidity':    internal.get('RH'),
                'co2':         internal.get('CO2'),
            }
            sensor_snapshot = {k: v for k, v in sensor_snapshot.items() if v is not None}
            for p in self._profiles:
                trust = self._feedback_registry.trust_score(p.actuator_id)
                cmd_pct = current_cmd_pcts.get(p.actuator_id, 0.0)
                self._cal_registry.push_cycle(
                    actuator_id=p.actuator_id,
                    kind=p.kind,
                    cmd_pct=cmd_pct,
                    sensor_snapshot=sensor_snapshot,
                    clean_for_learning=clean,
                    trust_score=trust,
                    is_probe=is_probe,
                )

        # ── P5-5: Cumulative Goal Tracker ────────────────────────────────────
        if self.cumulative_tracker_enabled:
            self._update_cumulative_tracker(
                internal=internal,
                cycle_sec=cycle_sec,
                authority=authority,
            )

        # ── Stage 2: greybox shadow run ──────────────────────────────────────
        gb_mode = getattr(self, 'effect_engine', 'legacy')
        if gb_mode in ('greybox', 'shadow'):
            try:
                _kind_by_aid = {
                    p.actuator_id: getattr(p, 'kind', None)
                    for p in getattr(self, '_profiles', [])
                }
                self._greybox_shadow.step(
                    unique_id=uid,
                    internal=internal,
                    external=external_for_control,
                    cmds_pct=current_cmd_pcts,
                    dt=cycle_sec,
                    kind_by_aid=_kind_by_aid,
                )
                # Hourly KPI log + auto-transition check
                if (int(time.time()) % 3600) < int(cycle_sec):
                    mae_t  = self._greybox_shadow.mae_T()
                    mae_rh = self._greybox_shadow.mae_RH()
                    if mae_t is not None:
                        kpi_ok = self._greybox_shadow.kpi_passed()
                        self.logger.info(
                            'greybox shadow KPI — MAE_T=%.2f°C MAE_RH=%.1f%% passed=%s active=%s',
                            mae_t, mae_rh or 0.0, kpi_ok, getattr(self, '_greybox_active', False))
                        # KPI 통과 알림: shadow 모드, 또는 greybox 모드인데 아직 물리 제어가
                        # 활성화되지 않은(게이트 미통과) 경우. 이미 활성이면 알림 불필요.
                        if kpi_ok and not getattr(self, '_greybox_active', False):
                            self._handle_greybox_kpi_passed(mae_t, mae_rh or 0.0)
                # Periodic batch re-identification of greybox params
                self._maybe_run_greybox_identification(cycle_sec)
            except Exception as _gb_exc:
                self.logger.debug('greybox shadow error: %s', _gb_exc)

        # ── Commissioning anchor live-poll ───────────────────────────────────
        # Check for pending_anchors written by the Flask verdict API while the
        # daemon is running. Runs at most once every _ANCHOR_POLL_INTERVAL_S so
        # it does not add DB load on every cycle.
        now_ts = time.time()
        last_poll = getattr(self, '_last_anchor_poll_ts', 0.0)
        if (now_ts - last_poll) >= self._ANCHOR_POLL_INTERVAL_S:
            fac_uuid = self.geo_facility_id_device_id or ''
            if fac_uuid:
                try:
                    self._apply_pending_commissioning_anchors(fac_uuid)
                except Exception:
                    pass
            self._last_anchor_poll_ts = now_ts

        # Periodic facility profile reload — picks up sensor/actuator fitting changes
        _last_reload = getattr(self, '_last_profile_reload_ts', 0.0)
        if (now_ts - _last_reload) >= self._PROFILE_RELOAD_INTERVAL_S:
            fac_uuid = self.geo_facility_id_device_id or ''
            if fac_uuid:
                try:
                    self._reload_profiles()
                except Exception:
                    pass
            self._last_profile_reload_ts = now_ts

        # ── P2-5: PI 상태 DB 저장 ────────────────────────────────────────────
        self._last_cycle_ts = now_ts
        try:
            self._last_cycle_summary = self._build_cycle_summary(
                now_ts=now_ts,
                situation=situation,
                env_target=env_target,
                final_cmds=final_cmds,
                commands=commands,
                gate_result=gate_result,
                internal=internal,
            )
        except Exception:
            # 요약은 부가 정보 — 실패해도 PI 상태 저장을 막지 않는다.
            self.logger.debug(
                'EnvCoordinator: cycle summary build failed', exc_info=True)

        # 맵 위젯 /runtime 용 센서 스냅샷 — 사이클이 어차피 센서를 읽으므로
        # 같은 값을 미리 직렬화해 둔다. 웹 요청이 InfluxDB 를 직접 조회하지
        # 않고 이 스냅샷을 읽게 한다(저사양 호스트 스레드 풀 포화 방지).
        # 부가 정보이므로 실패해도 PI 상태 저장을 막지 않는다.
        try:
            from aot.aot_flask.geo.facility_sensors import build_sensor_snapshot
            snap = build_sensor_snapshot(
                getattr(self, '_sensors_resolved', None) or [],
                getattr(self, '_sensors_resolved_outdoor', None) or [],
            )
            snap['ts'] = now_ts
            self._last_cycle_runtime_snapshot = snap
        except Exception:
            self.logger.debug(
                'EnvCoordinator: runtime snapshot build failed', exc_info=True)

        self._save_runtime_state()

    # ── 맵 팝업 [현황] 요약 (summary_json) ────────────────────────────────────

    _SUMMARY_MAX_COMMANDS = 32
    _SUMMARY_MAX_TEXT     = 200

    # 변수 × 편차 방향 → 그 방향으로 밀 수 있는 액추에이터 종류.
    # `_KIND_CAPABILITIES` 와 같은 어휘를 쓴다(그쪽이 정본).
    _STRAIN_KINDS = {
        ('temperature', 'above'): ('cooler', 'opening', 'exhaust_fan', 'shade'),
        ('temperature', 'below'): ('heater', 'curtain'),
        ('humidity', 'above'):    ('opening', 'exhaust_fan', 'heater'),
        ('humidity', 'below'):    ('fogger',),
        ('vpd', 'above'):         ('fogger',),                 # 너무 건조
        ('vpd', 'below'):         ('opening', 'exhaust_fan', 'heater'),
        ('co2', 'below'):         ('co2_injector',),
        ('co2', 'above'):         ('opening', 'exhaust_fan'),
    }
    _STRAIN_SATURATED_PCT = 99.0     # 이 이상이면 더 밀 여지가 없다고 본다
    _STRAIN_MIN_SEC = 900.0          # 15분 — 한두 사이클의 흔들림과 가른다

    def _deviation_from_hard_limit(self, var, internal):
        """사용자가 정한 선을 넘은 정도 → float|None (안 넘었으면 None).

        제어목표에서 강등된 변수(VPD 직접 제어 모드의 온도·습도)에는 편차가
        없다. 그 변수에 대해 사용자가 실제로 정한 기준은 **하드 임계** 하나뿐
        이므로 그것을 기준으로 잰다. 부호 규약은 편차와 같다(양수 = 초과).

        ⚠ 래치(`_force_cool`/`_force_heat` 등)를 근거로 삼는다 — 진입과 해제
          문턱이 다른 히스테리시스가 이미 걸려 있어 경계에서 떨지 않는다.
          여기서 값을 다시 비교하면 그 히스테리시스 밖에서 판정하게 된다.
        """
        internal = internal or {}
        spec = {
            'temperature': ('_force_cool', '_force_heat', 'T',
                            self.temp_max, self.temp_min),
            'humidity':    ('_force_dehumid', '_force_humid', 'RH',
                            self.humid_max, self.humid_min),
        }.get(var)
        if not spec:
            return None
        hi_flag, lo_flag, key, hi, lo = spec
        now = internal.get(key)
        if now is None:
            return None
        if internal.get(hi_flag) and hi:
            return float(now) - float(hi)
        if internal.get(lo_flag) and lo:
            return float(now) - float(lo)
        return None

    def _assess_strain(self, situation, env_target, outputs_by_kind, ctx, now_ts,
                       internal_for_strain=None):
        """설비가 목표를 **못 따라가고 있는가** → dict|None.

        화면이 "냉각기 100%" 만 보이면 그것이 좋은 신호인지 나쁜 신호인지 알 수
        없다. 최대로 밀고 있는데도 편차가 안 줄면 그건 **설비 한계**이고, 사람이
        해야 할 판단(차광을 더 치든, 목표를 낮추든, 장비를 늘리든)이 생긴다.

        판정 셋을 모두 만족해야 한다:
          1. 편차가 허용 오차를 넘는다
          2. 그 방향으로 밀 수 있는 종류가 **전부** 포화(≥99%)
          3. 추세가 목표 쪽으로 오지 않는다 — 그리고 그 상태가 15분 이상

        한두 사이클의 흔들림을 "한계" 라고 부르면 경고가 값을 잃는다. 그래서
        지속 시간을 함께 본다(상태는 인스턴스에 들고, 조건이 풀리면 지운다).
        """
        dev_all = situation.deviation_native or {}
        trend_of = {'temperature': ctx.get('T_trend'),
                    'humidity': ctx.get('RH_trend'),
                    'co2': ctx.get('CO2_trend')}
        since = getattr(self, '_strain_since', None)
        if since is None:
            since = {}
            self._strain_since = since

        worst = None
        seen = set()
        for var, tv in (env_target or {}).items():
            if var.startswith('_'):
                continue
            dev = dev_all.get(var)
            tol = float(getattr(tv, 'tolerance', 0.0) or 0.0)
            # ── 제어목표에서 강등된 변수 (2026-08-26) ─────────────────────────
            # VPD 직접 제어 모드에서는 `_decompose_vpd` 가 온도·습도를
            # `_..._constraint` 로 강등하므로 `deviation_native` 에 **없다.**
            # 그래서 이 판정이 온도로는 **한 번도 서지 않았다** — 냉방기가
            # 몇 시간째 돌고 실내가 상한을 2°C 넘긴 채여도 화면은 조용했다
            # (2026-08-26 실측: 温室環境制御 의 strain 이 계속 null).
            #
            # 그 변수에 대해 사용자가 실제로 정한 유일한 기준은 **하드 임계**다.
            # 목표가 아니라 **선**이므로 허용오차는 없다(넘은 것 자체가 사실).
            # 노이즈는 이미 걸러져 있다 — 진입/해제 문턱이 다른 래치
            # (`_check_hard_constraints`)를 통과한 뒤에만 여기 온다.
            #
            # ⚠ 이것은 온도를 목표로 되살리는 것이 **아니다.** 제어는 여전히
            #   VPD 하나가 한다. 여기서 하는 일은 **보고**뿐이다.
            _by_limit = False
            if dev is None:
                dev = self._deviation_from_hard_limit(var, internal_for_strain)
                if dev is None:
                    since.pop(var, None)
                    continue
                tol = 0.0
                _by_limit = True
            if abs(dev) <= tol:
                since.pop(var, None)
                continue
            kinds = self._STRAIN_KINDS.get((var, 'above' if dev > 0 else 'below'))
            if not kinds:
                since.pop(var, None)
                continue
            present = [k for k in kinds if k in outputs_by_kind]
            if not present:
                # 그 방향으로 밀 장치가 **아예 없다** — 이것도 사람이 알아야
                # 하지만 "한계" 와는 다른 사실이라 따로 말한다.
                since.pop(var, None)
                if worst is None:
                    worst = {'var': var, 'dev': round(dev, 2), 'kinds': [],
                             'reason': 'no_actuator', 'since_s': 0}
                continue
            # ⚠ **제약 위반에는 포화를 요구하지 않는다.** 목표 추종이면 "최대로
            # 미는데 안 준다" 가 한계의 증거지만, 제약은 제어 중심이 그 방향을
            # 아예 요구하지 않을 수 있다 — VPD 가 목표에 있으면 냉방기는 0% 다.
            # 그때도 선을 넘은 채 있다는 사실은 그대로다. 포화를 요구하면 바로
            # 그 경우에 화면이 조용해진다(고치려던 증상 그 자체).
            if not _by_limit and not all(
                    outputs_by_kind[k] >= self._STRAIN_SATURATED_PCT
                    for k in present):
                since.pop(var, None)
                continue
            # 추세가 목표 쪽으로 오고 있으면 기다리면 된다 — 한계가 아니다.
            tr = trend_of.get(var)
            if tr is not None and dev * tr < 0:
                since.pop(var, None)
                continue
            since.setdefault(var, now_ts)
            seen.add(var)
            held = now_ts - since[var]
            if held < self._STRAIN_MIN_SEC:
                continue
            # 포화까지 갔으면 '설비 한계' 이고, 아니면 '선을 넘은 채 유지' 다.
            # 사람이 할 일이 다르다 — 앞은 장비를 늘리거나 목표를 낮추는 것이고,
            # 뒤는 그 선이 지금 조건에서 지킬 수 있는 값인지 다시 보는 것이다.
            _saturated = all(outputs_by_kind[k] >= self._STRAIN_SATURATED_PCT
                             for k in present)
            cand = {'var': var, 'dev': round(dev, 2), 'kinds': present,
                    'reason': ('saturated' if _saturated else 'limit_breached'),
                    'since_s': int(held)}
            if worst is None or cand['since_s'] > worst.get('since_s', 0):
                worst = cand
        for var in list(since):
            if var not in seen:
                since.pop(var, None)
        return worst

    def _write_gate_only_summary(self, gate_result, gate_env, now_ts) -> None:
        """안전 게이트로 조기 종료할 때 남기는 **축소 요약**.

        전체 요약(`_build_cycle_summary`)은 `situation` 이 있어야 만들 수 있는데
        이 경로는 그 앞에서 반환한다. 그래서 담을 수 있는 것만 담는다 —
        **제어가 살아 있다는 사실과 멈춘 이유**.

        ⚠ 환경 값(측정·목표·편차)은 싣지 않는다. 이 사이클에서 계산하지 않은
          값이라, 실으면 낡은 값이 지금 값으로 읽힌다 — 침묵보다 나쁘다.
        """
        try:
            mask = int(getattr(gate_result, 'gate_mask', 0) or 0)
            # `GateResult.description` 은 사유를 ', ' 로 이어 붙인 것이다
            # (`safety_gates` 의 `', '.join(reasons)`). 화면이 사유마다 문구를
            # 고를 수 있게 다시 쪼개 준다 — 이어 붙은 문자열은 번역할 수 없다.
            _fc = gate_result.forced_commands or {}
            desc = (getattr(gate_result, 'description', '') or '')
            reasons = [r.strip() for r in desc.split(',') if r.strip()]
            self._last_cycle_summary = {
                'ts': now_ts,
                # 화면이 "환경 데이터는 이 사이클의 것이 아니다" 를 말할 근거.
                'gate_only': True,
                'gate': {
                    'triggered': True,
                    'mask': mask,
                    'description': desc[:self._SUMMARY_MAX_TEXT],
                    'reasons': reasons[:4],
                },
                # ⚠ **강제된 장치만 싣지 말 것.** 강우 게이트는 개구부와 분무만
                # 건드리므로, 그것만 실으면 냉난방기가 목록에서 통째로
                # 사라진다 — 사용자는 "그 장치는 어디 갔나" 를 묻게 된다
                # (2026-08-26 지적). 게이트가 안 건드린 장치도 **여전히 거기
                # 있고 상태가 있다.**
                #
                # 건드리지 않은 장치의 `pct` 는 **None** 이다. 0 을 쓰면
                # "이번에 0 을 명령했다" 가 되어 거짓이 된다 — 이번 사이클에는
                # 그 장치에 대해 아무 명령도 내리지 않았다. 화면은 None 을 보고
                # 실제 상태만 그린다(명령 대조를 하지 않는다).
                'commands': [
                    {'slot_key': (p.slot_key or p.actuator_id[:8]),
                     'kind': p.kind,
                     'pct': (round(float(_fc[p.actuator_id].get('value', 0.0)), 1)
                             if p.actuator_id in _fc else None),
                     'reason': (_LC.REASON_SAFETY_PRE_GATE
                                if p.actuator_id in _fc else None),
                     'var': None}
                    for p in self._profiles
                ][:self._SUMMARY_MAX_COMMANDS],
            }
            # ⚠ **이것도 완료된 사이클이다.** 코디네이터가 돌았고, 판단했고,
            # 명령을 내보냈다 — L1~L3 를 건너뛰었을 뿐이다. 여기서 도장을
            # 안 찍으면 `last_cycle_ts` 가 늙어 `IEC stale (Ns ago)` 가 남고,
            # 그 stale 하나 때문에 [시설 세부]·측정 스냅샷이 **통째로 빈다**
            # (2026-08-26 실측: 강우 게이트 45분 → 탭이 "설명할 제어 사이클이
            # 없습니다" 만 띄웠다).
            self._last_cycle_ts = now_ts
            self._save_runtime_state()
        except Exception:
            self.logger.debug('EnvCoordinator: 게이트 요약 기록 실패', exc_info=True)

    def _build_cycle_summary(self, now_ts: float, situation: SituationReport,
                             env_target: dict, final_cmds: dict,
                             commands: dict, gate_result: GateResult,
                             internal: dict = None) -> dict:
        """사이클 중 이미 산출된 값을 UI 요약 dict 로 직렬화한다.

        추가 계산 없음 — situation/명령/예보 신호의 스냅샷.
        _save_runtime_state() 가 summary_json 으로 저장하고
        /api/aot/facility/<uuid>/env_summary 가 읽는다.
        """
        ctx = situation.context

        def _r(v: Any, nd: int = 2) -> 'float | None':
            try:
                return round(float(v), nd)
            except (TypeError, ValueError):
                return None

        def _pct(cmd: 'ActuatorCommand | dict') -> float:
            return float(cmd.get('value', 0.0) if isinstance(cmd, dict)
                         else getattr(cmd, 'value', 0.0))

        cmd_pcts = {aid: _pct(c) for aid, c in final_cmds.items()}

        vent_total = 0.0
        vent_eff   = 0.0
        kind_acc   = {}      # kind → [pct 합, 개수]
        cmd_list   = []
        for p in self._profiles:
            pct = cmd_pcts.get(p.actuator_id)
            if p.kind == 'opening' and p.area_m2:
                vent_total += float(p.area_m2)
                if pct is not None:
                    vent_eff += float(p.area_m2) * pct / 100.0
            if pct is None:
                continue
            acc = kind_acc.setdefault(p.kind, [0.0, 0])
            acc[0] += pct
            acc[1] += 1
            if len(cmd_list) < self._SUMMARY_MAX_COMMANDS:
                src = commands.get(p.actuator_id)
                # ── 값과 근거는 **같은 시점**이어야 한다 (2026-08-26) ────────
                # `pct` 는 `final_cmds`(오버라이드 뒤)에서, `reason`/`var` 는
                # `commands`(오버라이드 **앞**)에서 왔다. 그래서 냉방기가
                # "100% · 목표를 좇는 중 · VPD 때문" 으로 나왔는데, 실제로는
                # 코디네이터가 0% 를 명령했고 100% 는 **온도 하드 상한**이
                # 강제한 값이었다(실측: 温室環境制御, 실내 32.9°C · temp_max 30).
                # 한 줄 안에서 값과 설명이 서로 다른 것을 가리키면, 이 탭이
                # 없애려던 바로 그 거짓 설명이 된다.
                #
                # 오버라이드가 값을 바꿨으면 **그쪽 근거**를 쓴다. 그때
                # `var`(코디네이터가 좇던 변수)는 더 이상 이 값을 설명하지
                # 않으므로 함께 버린다 — 남기면 "온도 때문에 켜졌는데 VPD 가
                # 이유" 라는 또 다른 거짓이 된다.
                _fin = final_cmds.get(p.actuator_id)
                _fin_reason = (_fin.get('reason') if isinstance(_fin, dict)
                               else getattr(_fin, 'reason', None))
                _src_reason = (int(getattr(src, 'reason', 0))
                               if src is not None else None)
                _overridden = (_fin_reason is not None
                               and _fin_reason != _src_reason)
                cmd_list.append({
                    'slot_key': p.slot_key or p.actuator_id[:8],
                    'kind':     p.kind,
                    # 개구부의 유효 면적 — 화면이 장치마다 "열린/전체 면적" 을
                    # 3행에 적는다(시설 합계와 같은 모양). 없으면 안 적는다.
                    'area_m2':  (round(float(p.area_m2), 1)
                                 if getattr(p, 'area_m2', None) else None),
                    'pct':      round(pct, 1),
                    'reason':   (_fin_reason if _overridden else _src_reason),
                    'var':      (None if _overridden else
                                 (getattr(src, 'var_source', None)
                                  if src is not None else None)),
                })

        ff = getattr(self, '_last_ff_signal', None)
        ff_dict = {'active': False}
        if ff is not None and ff.valid and ff.reason and ff.reason != '정상 범위':
            ff_dict = {
                'active':        True,
                'reason':        ff.reason[:self._SUMMARY_MAX_TEXT],
                'T_bias':        _r(ff.T_bias),
                'RH_bias':       _r(ff.RH_bias),
                'wind_inhibit':  bool(ff.wind_inhibit),
                'rain_expected': bool(ff.rain_expected),
            }

        internal = internal or {}

        # ── Growth Schedule (시작/종료일 + 경과 주차) ────────────────────────
        # 시작일은 구획의 것이다(함수에는 그 칸이 없다). 종료일은 성격이 달라
        # 남아 있다 — 수확일이 아니라 "이후 제어 정지" 라는 안전 결정이다.
        _pt = self._plot_targets()
        _started = _pt.get('started_on')
        sched = {
            'start': _started.isoformat() if _started else None,
            'end':   (getattr(self, 'schedule_end_time', '') or '').strip() or None,
            'week':  None,
            'plot':  _pt.get('plot_name'),
            'stage': (_pt.get('stage') or {}).get('name'),
        }
        if sched['start']:
            try:
                sched['week'] = _r(self._get_weeks_elapsed(), 1)
            except Exception:
                pass

        # ── Photosynthesis 목표 대비 (작물 파라미터 + 현재 환경) ──────────────
        photo = {'enabled': bool(getattr(self, 'photosynth_mode_enabled', False))}
        try:
            from aot.functions.utils.env_control.photosynthesis import (
                estimate_net_photosynthesis, ppfd_from_wm2)
            crop = self._crop_params()
            # 화면이 이 값을 µmol/m²/s 목표(K_L) 옆에 나란히 놓으므로 **여기서**
            # 바꿔 싣는다. 요약이 W/m² 를 담고 화면이 µmol 라벨을 붙이던 것이
            # 2026-08-26 에 발견된 문제다.
            L   = ppfd_from_wm2(internal.get('light'))
            CO2 = internal.get('CO2')
            T   = internal.get('T')
            VPD = internal.get('VPD')
            photo.update({
                'crop':  crop.name,
                'light': _r(L, 0),
                'co2':   _r(CO2, 0),
                'temp':  _r(T, 1),
                'rh':    _r(internal.get('RH'), 1),
                'vpd':   _r(VPD, 2),
                'opt': {
                    't_opt':    _r(crop.T_opt, 1),
                    'light_k':  _r(crop.K_L, 0),     # half-saturation PPFD
                    'co2_k':    _r(crop.K_C, 0),     # half-saturation ppm
                    'vpd_half': _r(crop.VPD_half, 2),
                },
            })
            if None not in (L, CO2, T, VPD) and crop.A_max > 0:
                a_n = estimate_net_photosynthesis(
                    L=float(L), CO2=float(CO2), T=float(T), VPD=float(VPD),
                    crop_params=crop)
                photo['rate_rel_pct'] = _r(a_n / crop.A_max * 100.0, 0)
        except Exception:
            pass
        try:
            acc = getattr(self, '_daily_acc', None)
            if acc is not None and getattr(acc, 'dli', None) is not None:
                photo['dli_today'] = _r(acc.dli, 1)
            dli_t = float(getattr(self, 'dli_target', 0) or 0.0)
            if dli_t > 0:
                photo['dli_target'] = _r(dli_t, 1)
        except Exception:
            pass

        obk = {k: round(s / n, 1) for k, (s, n) in kind_acc.items() if n}
        return {
            'ts':              now_ts,
            'modes':           list(situation.modes or []),
            # "설비가 못 따라가고 있다" — 숫자만 보고하지 않고 그 뜻을 말한다.
            'strain':          self._assess_strain(
                                   situation, env_target, obk, ctx, now_ts,
                                   internal_for_strain=internal),
            'limiting_factor': situation.limiting_factor,
            'deviation': {k: _r(v) for k, v
                          in (situation.deviation_native or {}).items()},
            'trend': {
                'T_per_min':   _r(ctx.get('T_trend'),   3),
                'RH_per_min':  _r(ctx.get('RH_trend'),  3),
                'CO2_per_min': _r(ctx.get('CO2_trend'), 2),
            },
            'targets': {k: _r(tv.value) for k, tv in (env_target or {}).items()},
            'vent': {
                'effective_area_m2': _r(vent_eff),
                'total_area_m2':     _r(vent_total),
                'open_ratio_pct':    (_r(vent_eff / vent_total * 100.0, 1)
                                      if vent_total > 0 else None),
            },
            'outputs_by_kind': obk,
            'gate': {
                'triggered':   bool(gate_result.triggered),
                'description': (gate_result.description or '')[:self._SUMMARY_MAX_TEXT],
            },
            'feedforward': ff_dict,
            'schedule':    sched,
            'photo':       photo,
            'commands':    cmd_list,
            'actuation':   self._build_actuation_summary(now_ts),
        }

    def _build_actuation_summary(self, now_ts: float) -> dict:
        """개구부 구동주기 설정과 이번 사이클 긴급 여부를 요약한다(관측성).

        actuation_profile 설정 효과(정상 180/600s 등)를 사용자가 [현황] 화면에서
        직접 확인할 수 있게 한다 — 값을 바꿔도 실제로 뭐가 달라졌는지 보이지 않으면
        튜닝이 불가능하다.
        """
        normal_sec, emergency_sec = self._actuation_params()
        moved = getattr(self, '_dispatch_moved', {}) or {}
        vents = []
        for p in self._profiles:
            if p.kind != 'opening':
                continue
            moved_ts = moved.get(p.actuator_id)
            vents.append({
                'slot_key':       p.slot_key or p.actuator_id[:8],
                'since_move_sec': (round(now_ts - moved_ts, 0)
                                   if moved_ts is not None else None),
            })
        return {
            'profile':          getattr(self, 'actuation_profile', 'standard') or 'standard',
            'normal_period_sec':    normal_sec,
            'emergency_period_sec': emergency_sec,
            'emergency':        bool(getattr(self, '_emergency_now', False)),
            'reason':           getattr(self, '_emergency_reason', '') or None,
            'vents':            vents,
        }

    # ── Greybox KPI auto-transition ───────────────────────────────────────────

    _KPI_NOTIFY_INTERVAL_S    = 86400.0   # re-notify at most once per day
    _ANCHOR_POLL_INTERVAL_S   = 300.0     # check pending commissioning anchors every 5 min
    _PROFILE_RELOAD_INTERVAL_S = 600.0    # re-sync facility fittings every 10 min

    def _handle_greybox_kpi_passed(self, mae_t: float, mae_rh: float) -> None:
        """Called when shadow mode KPI passes. Logs a prominent notification.

        Does NOT auto-switch effect_engine — that requires user confirmation
        since it changes live control behaviour. Instead it logs a clear alert
        visible in the function decision log so the operator can switch via UI.
        """
        last_notify = getattr(self, '_greybox_kpi_notify_ts', 0.0)
        now = time.time()
        if (now - last_notify) < self._KPI_NOTIFY_INTERVAL_S:
            return
        self._greybox_kpi_notify_ts = now

        self.logger.warning(
            'greybox KPI PASSED — MAE_T=%.2f°C MAE_RH=%.1f%%. '
            'Shadow model is accurate. Switch effect_engine to "greybox" '
            'in function settings to enable physics-based control.',
            mae_t, mae_rh)

        # Write to decision log so the event appears in the UI timeline
        try:
            write_decision_log(
                self.unique_id,
                f'greybox_kpi_passed mae_T={mae_t:.2f} mae_RH={mae_rh:.1f}',
                channel=CH_GREYBOX_KPI_PASSED,
                value=1.0,
            )
        except Exception:
            pass

        # Persist KPI-passed flag in runtime state so it survives restart
        self._merge_calibration_state({
            'greybox_kpi_passed': True,
            'greybox_kpi_mae_T':  round(mae_t, 3),
            'greybox_kpi_mae_RH': round(mae_rh, 3),
            'greybox_kpi_ts':     now,
        })

    # ── Greybox calibration-state persistence (FunctionRuntimeState JSON) ──────
    def _read_calibration_state(self) -> dict:
        """함수 런타임 상태의 calibration_state_json 을 dict 로 읽음(없으면 {})."""
        try:
            from aot.config import AOT_DB_PATH
            from aot.databases.models import FunctionRuntimeState
            from aot.databases.utils import session_scope
            import json as _json
            with session_scope(AOT_DB_PATH) as sess:
                row = sess.query(FunctionRuntimeState).filter_by(
                    function_id=self.unique_id).first()
                if row and row.calibration_state_json:
                    return _json.loads(row.calibration_state_json)
        except Exception:
            self.logger.debug('greybox: read calibration_state failed', exc_info=True)
        return {}

    def _merge_calibration_state(self, updates: dict) -> None:
        """calibration_state_json 에 키를 병합 저장(재시작 후에도 유지)."""
        try:
            from aot.config import AOT_DB_PATH
            from aot.databases.models import FunctionRuntimeState
            from aot.databases.utils import session_scope
            import json as _json
            with session_scope(AOT_DB_PATH) as sess:
                row = sess.query(FunctionRuntimeState).filter_by(
                    function_id=self.unique_id).first()
                if row:
                    try:
                        cal = _json.loads(row.calibration_state_json or '{}')
                    except Exception:
                        cal = {}
                    cal.update(updates)
                    row.calibration_state_json = _json.dumps(cal)
                    sess.commit()
        except Exception:
            self.logger.debug('greybox: merge calibration_state failed', exc_info=True)

    def _maybe_run_greybox_identification(self, cycle_sec: float) -> None:
        """주기적으로 그레이박스 파라미터를 배치 학습·영속화.

        shadow 입력 버퍼(state/ext/cmds 이력)로 identification.fit 를 실행하고,
        성공 시 shadow.params 를 갱신하고 calibration_state_json 에 저장한다.
        """
        now = time.time()
        last = getattr(self, '_greybox_fit_ts', None)
        interval = getattr(self, '_GREYBOX_FIT_INTERVAL_S', 6 * 3600)
        if last is None:
            # 첫 호출 — 시계만 시작(데이터가 쌓일 시간을 둠)
            self._greybox_fit_ts = now
            return
        if (now - last) < interval:
            return
        self._greybox_fit_ts = now   # 성공/실패와 무관하게 다음 주기까지 대기
        try:
            from aot.functions.utils.env_control.greybox.identification import fit, N_MIN_SAMPLES
            states, exts, cmds = self._greybox_shadow.fit_window()
            if len(exts) < N_MIN_SAMPLES:
                return
            new_p = fit(states, exts, cmds, dt=cycle_sec,
                        prev_params=self._greybox_shadow.params)
            if new_p is not None:
                self._greybox_shadow.params = new_p
                self._merge_calibration_state({'greybox_params': new_p.to_dict()})
                self.logger.info(
                    'greybox params re-identified: n=%d rmse_T=%.3f rmse_RH=%.3f',
                    new_p.n_updates, new_p.rmse_T, new_p.rmse_RH)
        except Exception:
            self.logger.debug('greybox identification failed', exc_info=True)

    # ── Greybox physics control: gating + effect-model swap ───────────────────
    def _greybox_control_gate_ok(self) -> bool:
        """greybox 물리 제어를 활성화해도 되는지 — shadow 검증 + 학습 수렴 게이트.

        조건: (영속 또는 라이브) KPI 통과 AND 파라미터가 1회 이상 학습됨 AND
        rmse 가 KPI 한계(T≤1.5°C, RH≤8%) 이내. 하나라도 불충족이면 레거시 폴백.
        DB 조회 부하를 줄이려 KPI-passed 플래그는 메모리 캐시(TTL).
        """
        now = time.time()
        cache = getattr(self, '_greybox_gate_cache', None)
        if cache is None or (now - cache.get('ts', 0.0)) > 300.0:
            kpi_persisted = bool((self._read_calibration_state() or {}).get('greybox_kpi_passed'))
            cache = {'ts': now, 'kpi': kpi_persisted}
            self._greybox_gate_cache = cache
        kpi_ok = cache['kpi'] or self._greybox_shadow.kpi_passed()
        if not kpi_ok:
            return False
        params = self._greybox_shadow.params
        if getattr(params, 'n_updates', 0) < 1:
            return False
        if getattr(params, 'rmse_T', 999.0) > 1.5 or getattr(params, 'rmse_RH', 999.0) > 8.0:
            return False
        return True

    def _apply_effect_engine(self, situation: SituationReport) -> bool:
        """coordinate() 직전에 effect_model 출처를 결정.

        greybox 모드 + 게이트 통과 시 각 프로필 effect_model 을 greybox 물리 어댑터로
        교체(미모델 kind 는 레거시 유지)하고 base 명령을 컨텍스트에 주입한다.
        그 외 모드/게이트 미통과 시 레거시 effect_model 로 복원하고 False 반환.

        Returns: greybox 물리 제어 활성 여부.
        """
        # 최초 1회 레거시 effect_model 백업
        for p in self._profiles:
            if not hasattr(p, '_legacy_effect_model'):
                p._legacy_effect_model = p.effect_model

        mode = getattr(self, 'effect_engine', 'legacy')
        use_gb = (mode == 'greybox') and self._greybox_control_gate_ok()

        if not use_gb:
            for p in self._profiles:
                p.effect_model = p._legacy_effect_model
            if mode == 'greybox':
                self._warn_greybox_fallback()
            return False

        try:
            from aot.functions.utils.env_control.greybox.effect_adapter import greybox_effect_model
            from aot.functions.utils.env_control.greybox.channels import aggregate_cmds_by_kind
            kind_by_aid = {p.actuator_id: getattr(p, 'kind', None) for p in self._profiles}
            base = aggregate_cmds_by_kind(self._coord_state.prev_commands, kind_by_aid)
            situation.context['_gb_base_cmds'] = base
            params = self._greybox_shadow.params
            dt = float(situation.context.get('cycle_sec', 60.0) or 60.0)
            for p in self._profiles:
                gm = greybox_effect_model(getattr(p, 'kind', None), params, dt_default=dt)
                p.effect_model = gm if gm is not None else p._legacy_effect_model
            return True
        except Exception:
            # 어떤 실패든 레거시로 안전 폴백
            self.logger.debug('greybox effect-model swap failed; legacy fallback', exc_info=True)
            for p in self._profiles:
                p.effect_model = p._legacy_effect_model
            return False

    def _warn_greybox_fallback(self) -> None:
        now = time.time()
        last = getattr(self, '_greybox_fallback_warn_ts', 0.0)
        if (now - last) < 3600.0:
            return
        self._greybox_fallback_warn_ts = now
        self.logger.warning(
            'effect_engine=greybox 이지만 게이트 미통과(shadow KPI 미검증 또는 학습 미수렴) '
            '— 레거시 제어로 폴백. shadow 로 충분히 검증되면 자동 활성됩니다.')

    # ── Control dispatch: MPC → greybox-PI → legacy ───────────────────────────
    def _run_control(
            self, situation: SituationReport,
            uid: str) -> tuple[dict, CoordinatorState]:
        """제어 엔진 디스패치.

        greybox 물리 제어 활성 시 우선 MPC(수신지평 최적화)를 시도하고, 실패/미수렴/
        비활성이면 coordinate()(greybox-PI effect_model 또는 레거시) 로 폴백한다.
        coordinate() 의 effect_model 은 _apply_effect_engine 에서 이미 결정돼 있다.
        """
        if getattr(self, '_greybox_active', False) and getattr(self, '_mpc_enabled', True):
            try:
                result = self._run_mpc(situation, uid)
                if result is not None:
                    self._last_control_engine = 'mpc'
                    return result
            except Exception:
                self.logger.debug('MPC 실패 — greybox-PI 로 폴백', exc_info=True)
        self._last_control_engine = 'greybox-pi' if getattr(self, '_greybox_active', False) else 'legacy'
        return coordinate(
            situation=situation,
            profiles=self._profiles,
            state=self._coord_state,
            unique_id=uid,
            actuator_index=self._actuator_idx,
        )

    def _build_mpc_ext_seq(self, situation: SituationReport, horizon: int) -> list[dict]:
        """MPC 예측용 외기(ext) 시퀀스. v1: 현재 외기를 지평 동안 유지(persistence).

        예보 기반 곡선 enrichment 는 후속(여기만 교체하면 됨). 짧은 지평(≈수분)에서는
        persistence 가 합리적 근사다.
        """
        ctx = situation.context or {}
        base = {
            'T_ext':   ctx.get('T_ext',   20.0),
            'RH_ext':  ctx.get('RH_ext',  60.0),
            'CO2_ext': ctx.get('CO2_ext', 400.0),
            'solar':   ctx.get('solar',   0.0) or 0.0,
            'wind':    ctx.get('wind',    0.0) or 0.0,
        }
        return [dict(base) for _ in range(max(1, horizon))]

    def _run_mpc(
            self, situation: SituationReport,
            uid: str) -> 'tuple[dict, CoordinatorState] | None':
        """greybox MPC 로 modeled 채널을 최적화하고, 미모델 actuator 는 레거시
        coordinate() 로 처리해 병합한다. 적용 불가 시 None(상위에서 PI 폴백)."""
        from aot.functions.utils.env_control.greybox import mpc as gbmpc
        from aot.functions.utils.env_control.greybox.channels import (
            channel_for_kind, aggregate_cmds_by_kind,
        )
        from aot.functions.utils.env_control.coordinator import (
            finalize_command, ActuatorCommand, CoordinatorState,
        )
        from aot.functions.utils.env_control.log_channels import (
            REASON_PRIMARY, REASON_MANUAL_OVERRIDE,
        )

        modeled   = [p for p in self._profiles if channel_for_kind(getattr(p, 'kind', None))]
        unmodeled = [p for p in self._profiles if not channel_for_kind(getattr(p, 'kind', None))]
        if not modeled:
            return None

        ctx = situation.context or {}
        state = (ctx.get('T_int', 20.0), ctx.get('RH_int', 60.0), ctx.get('CO2_int', 400.0))
        cycle_sec = float(ctx.get('cycle_sec', 60.0) or 60.0)

        targets = {}
        for var in ('temperature', 'humidity', 'co2'):
            tv = situation.target.get(var)
            if tv is not None:
                targets[var] = (tv.value, tv.tolerance, tv.priority)
        if not targets:
            return None

        cfg = getattr(self, '_mpc_config', None) or gbmpc.MPCConfig()
        ext_seq = self._build_mpc_ext_seq(situation, cfg.horizon)
        kind_by_aid = {p.actuator_id: getattr(p, 'kind', None) for p in self._profiles}
        prev_ch = aggregate_cmds_by_kind(self._coord_state.prev_commands, kind_by_aid)

        res = gbmpc.optimize_channels(
            state=state, targets=targets, profiles=modeled, ext_seq=ext_seq,
            params=self._greybox_shadow.params, prev_channel_cmds=prev_ch,
            cycle_sec=cycle_sec, config=cfg,
        )
        if res.method == 'noop':
            return None

        apertures = gbmpc.distribute_to_actuators(res.channel_cmds, modeled)
        commands = {}
        new_prev = dict(self._coord_state.prev_commands)
        for p in modeled:
            if p.manual_lock.is_active():
                commands[p.actuator_id] = ActuatorCommand(
                    value=p.manual_lock.manual_value, reason=REASON_MANUAL_OVERRIDE)
                new_prev[p.actuator_id] = p.manual_lock.manual_value
                continue
            ap = apertures.get(p.actuator_id, 0.0)
            prev = self._coord_state.prev_commands.get(p.actuator_id, 0.0)
            cmd = finalize_command(p, ap, prev, cycle_sec,
                                   reason=REASON_PRIMARY, var_source='mpc')
            commands[p.actuator_id] = cmd
            new_prev[p.actuator_id] = cmd.control_value()

        # 미모델 actuator(shade/curtain/lighting/circulation_fan)는 레거시 경로로 제어
        integral = dict(self._coord_state.integral)
        active_vars = dict(self._coord_state.active_vars)
        if unmodeled:
            um_state = CoordinatorState(
                prev_commands=dict(self._coord_state.prev_commands),
                integral=integral, active_vars=active_vars,
                # ⚠ 사이클을 넘어 쌓이는 값은 **여기서도 이어 받아야** 한다.
                #   빠뜨리면 매 사이클 0 에서 다시 세어 환기 우선의 인내가
                #   영영 차지 않는다(= 냉난방에 넘기는 경로가 죽는다).
                vent_first_held_s=getattr(
                    self._coord_state, 'vent_first_held_s', 0.0) or 0.0,
                deadzone_wrong_side=dict(getattr(
                    self._coord_state, 'deadzone_wrong_side', None) or {}))
            um_cmds, um_new = coordinate(
                situation=situation, profiles=unmodeled, state=um_state,
                unique_id=uid, actuator_index=self._actuator_idx)
            commands.update(um_cmds)
            for p in unmodeled:
                new_prev[p.actuator_id] = um_new.prev_commands.get(p.actuator_id, 0.0)
            integral = um_new.integral
            active_vars = um_new.active_vars

        return commands, CoordinatorState(
            prev_commands=new_prev, integral=integral, active_vars=active_vars,
            vent_first_held_s=(um_new.vent_first_held_s if unmodeled
                               else (getattr(self._coord_state,
                                             'vent_first_held_s', 0.0) or 0.0)),
            deadzone_wrong_side=(um_new.deadzone_wrong_side if unmodeled
                                 else dict(getattr(self._coord_state,
                                           'deadzone_wrong_side', None) or {})))

    # ── 0.4: circulation_fan 독립 혼합 제어 ───────────────────────────────────

    _MIXING_HOTSPOT_THRESHOLD_C = 0.5   # °C: 공간 온도 구배 임계 (핫스팟 감지 플래그)
    _MIXING_MIN_CYCLE_SEC       = 300.0 # s: 너무 빠른 ON/OFF 방지

    def _apply_mixing_actuators(self, commands: dict, internal: dict) -> None:
        """circulation_fan 을 공간 온도 불균일 기준으로 독립 제어.

        coordinator 는 circulation_fan 을 선택하지 않으므로 (effect 방향 '~')
        이 메서드가 post-coordinator 룰로 처리한다.

        조건:
          - _spatial_hotspot_T 플래그(D2 공간센서) 또는 hotspot_RH 플래그
          - 또는 사용자가 임계 설정 시 직접 임계 비교
        동작:
          - 조건 충족 → 해당 circulation_fan 을 100% ON
          - 조건 미충족 → safe_default(0%) 유지 (coordinator 결과 그대로)
        """
        hotspot_T  = bool(internal.get('_spatial_hotspot_T',  False))
        hotspot_RH = bool(internal.get('_spatial_hotspot_RH', False))
        need_mix   = hotspot_T or hotspot_RH

        from aot.functions.utils.env_control.coordinator import ActuatorCommand
        from aot.functions.utils.env_control.log_channels import REASON_PRIMARY

        for p in getattr(self, '_profiles', []):
            if p.kind not in ('circulation_fan',):
                continue
            if need_mix:
                commands[p.actuator_id] = ActuatorCommand(
                    value=100.0, reason=REASON_PRIMARY, var_source='mixing')
            # need_mix=False 시 coordinator 가 이미 safe_default(0.0) 로 설정했으므로 유지
