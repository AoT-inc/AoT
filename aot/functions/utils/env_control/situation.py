# coding=utf-8
"""
env_control/situation.py — Layer 2 상황 평가자 (Phase D 완전 구현).

D1: 내부/외부 상태 + 추세 산출 (5분 슬라이딩 윈도우 선형 회귀)
D2: 광합성 제한 인자 평가 (light/co2/temperature/water 단순 경험 모델)
D3: 운전 모드 자동 결정 (제한 인자 + 추세 반영)
D4: VPD 분해 (Phase C 구현, 유지)

참조: docs/dev/integrated_env_control_design.md §5.4~§5.7
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .types import (
    EnvContext, EnvTarget, SituationReport, TargetVar,
    MODE_COOLING, MODE_HEATING, MODE_HUMIDIFY, MODE_DEHUMIDIFY,
    MODE_CO2_ENRICH, MODE_CONSERVATION, MODE_DEGRADED, MODE_NATURAL,
)


# ─────────────────────────────────────────────────────────────────────────────
# D1: 추세 상태 (사이클 간 보존)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TrendState:
    """슬라이딩 윈도우 추세 계산 상태. assess() 호출 간 보존."""
    history: Dict[str, List[Tuple[float, float]]] = field(default_factory=dict)
    window_sec: float = 300.0  # 슬라이딩 윈도우 크기 (초)


def _update_trend(state: TrendState, now: float, values: Dict[str, float]) -> Dict[str, float]:
    """히스토리 갱신 후 각 변수의 변화율(단위/min) 반환."""
    slopes: Dict[str, float] = {}
    for var, val in values.items():
        # **측정이 없는 주기는 이력에 넣지 않는다.** 넣으면 회귀 계산이 None 을
        # 더하다 죽고(사이클 통째로 실패), 0 으로 바꿔 넣으면 없는 값이 급락
        # 추세로 둔갑한다. 그 변수의 기울기는 0(모름)으로 둔다.
        if val is None:
            slopes[var] = 0.0
            continue
        buf = state.history.setdefault(var, [])
        buf.append((now, val))
        # 윈도우 바깥 포인트 제거
        cutoff = now - state.window_sec
        state.history[var] = [(t, v) for t, v in buf if t >= cutoff]
        slopes[var] = _slope_per_min(state.history[var])
    return slopes


def _slope_per_min(points: List[Tuple[float, float]]) -> float:
    """최소제곱 선형 회귀 기울기 (단위/min). 포인트 2개 미만이면 0 반환."""
    n = len(points)
    if n < 2:
        return 0.0
    sum_t = sum(t for t, _ in points)
    sum_v = sum(v for _, v in points)
    sum_tt = sum(t * t for t, _ in points)
    sum_tv = sum(t * v for t, v in points)
    denom = n * sum_tt - sum_t * sum_t
    if abs(denom) < 1e-9:
        return 0.0
    # slope in 단위/sec → 단위/min
    return (n * sum_tv - sum_t * sum_v) / denom * 60.0


# ─────────────────────────────────────────────────────────────────────────────
# 공개 진입점
# ─────────────────────────────────────────────────────────────────────────────

def assess(
    env_target: EnvTarget,
    internal: Dict[str, float],
    external: Dict[str, float],
    cycle_sec: float = 60.0,
    now_ts: Optional[float] = None,
    last_ext_ts: Optional[float] = None,
    last_int_ts: Optional[float] = None,
    trend_state: Optional[TrendState] = None,
    authority: Optional[Dict] = None,
    light_sat: Optional[float] = None,
) -> Tuple[SituationReport, TrendState]:
    """
    L2 상황 평가: 편차 계산 + VPD 분해 + 추세 + 제한 인자 + 운전 모드.

    Args:
        env_target:   L1 EnvTarget (온도·습도·CO₂·VPD)
        internal:     내부 센서 {'T', 'RH', 'CO2', 'VPD'}
        external:     외부 센서 {'T', 'RH', 'wind', 'rain', 'solar', 'CO2', 'dewpoint'}
        cycle_sec:    현재 사이클 주기
        now_ts:       현재 epoch (None 이면 time.time())
        last_ext_ts:  외부 센서 마지막 수신 epoch
        last_int_ts:  내부 센서 마지막 수신 epoch
        trend_state:  이전 사이클 TrendState (None 이면 새로 생성)

    Returns:
        (SituationReport, 업데이트된 TrendState)
    """
    now = now_ts or time.time()
    ts = trend_state if trend_state is not None else TrendState()

    # ── EnvContext 구성 ────────────────────────────────────────────────────────
    ctx: EnvContext = {
        'T_int':   internal.get('T',   0.0),
        'RH_int':  internal.get('RH',  0.0),
        # **없는 측정을 400 으로 지어내지 않는다.** 그러면 CO₂ 센서가 없는
        # 시설에서도 편차가 계산돼 화면이 "CO2 −500 ppm 벗어남" 이라 말하는데,
        # 바로 옆 광합성 블록은 같은 값을 "—"(없음) 으로 보인다 — 한 화면이 두
        # 소리를 낸다(2026-08-20 지적). None 이면 `_get_measured` 가 그 항목을
        # 건너뛰므로 편차도, 그 편차를 근거로 한 모드도 서지 않는다.
        'CO2_int': internal.get('CO2'),
        'VPD_int': internal.get('VPD', 0.0),
        'T_ext':   external.get('T',   20.0),
        'RH_ext':  external.get('RH',  60.0),
        'CO2_ext': external.get('CO2', 400.0),
        'wind':    external.get('wind', 0.0),
        'rain':    external.get('rain', 0.0),
        'solar':   external.get('solar', 0.0),
        'dewpoint':external.get('dewpoint', 10.0),
        'now_ts':  now,
        'cycle_sec': cycle_sec,
        'last_ext_ts': last_ext_ts or now,
        'last_int_ts': last_int_ts or now,
        'internal': internal,
        'external': external,
    }

    # ── D1: 추세 계산 ─────────────────────────────────────────────────────────
    obs = {
        'T':   ctx['T_int'],
        'RH':  ctx['RH_int'],
        'CO2': ctx['CO2_int'],
    }
    slopes = _update_trend(ts, now, obs)
    ctx['T_trend']   = slopes.get('T',   0.0)  # °C/min
    ctx['RH_trend']  = slopes.get('RH',  0.0)  # %/min
    ctx['CO2_trend'] = slopes.get('CO2', 0.0)  # ppm/min

    # ── D4: VPD 분해 (§5.4 옵션 A) ───────────────────────────────────────────
    working_target = _decompose_vpd(env_target, ctx)

    # ── 편차 계산 (native 단위, R1) ───────────────────────────────────────────
    deviation: Dict[str, float] = {}
    for var, tv in working_target.items():
        if var.startswith('_'):
            continue
        measured = _get_measured(var, ctx)
        if measured is None:
            continue
        # 편차 = 현재 - 목표 (양수 = 목표 초과 → 낮춰야 함)
        deviation[var] = measured - tv.value

    # ── D2: 광합성 제한 인자 ─────────────────────────────────────────────────
    limiting = _assess_limiting_factor(ctx, light_sat=light_sat)

    # ── D3: 운전 모드 결정 ────────────────────────────────────────────────────
    modes = _decide_modes(working_target, ctx, limiting)

    # ── P5-2/P5-3: Authority 기반 모드 보강 + 목표 완화 ─────────────────────
    auth = authority or {}
    if auth:
        from .authority import degrade_target, is_all_natural, LEVEL_NATURAL
        if is_all_natural(auth):
            if MODE_NATURAL not in modes:
                modes = [MODE_NATURAL] + [m for m in modes if m != MODE_CONSERVATION]
            # 모든 NATURAL → 목표를 외기에 맞게 완화
            degrade_target(working_target, auth, external)
        else:
            has_natural = any(v == LEVEL_NATURAL for v in auth.values())
            if has_natural:
                if MODE_DEGRADED not in modes:
                    modes = modes + [MODE_DEGRADED]
                # 일부 NATURAL 변수만 완화
                degrade_target(working_target, auth, external)

    report = SituationReport(
        context=ctx,
        target=working_target,
        deviation_native=deviation,
        limiting_factor=limiting,
        modes=modes,
        authority=auth,
    )
    return report, ts


# ─────────────────────────────────────────────────────────────────────────────
# D2: 광합성 제한 인자 (§5.6)
# ─────────────────────────────────────────────────────────────────────────────

# 간이 경험 임계값 (Phase E 작물 라이브러리로 교체 예정)
_LIGHT_SAT    = 600.0   # W/m²  — 이 이상이면 광 비제한
_LIGHT_COMP   = 30.0    # W/m²  — 광보상점 미만이면 야간 취급
_CO2_OPT      = 800.0   # ppm   — 이 이상이면 CO₂ 비제한
_CO2_COMP     = 200.0   # ppm   — CO₂ 보상점
_T_OPT_LO     = 18.0    # °C    — 최적 온도 하한
_T_OPT_HI     = 28.0    # °C    — 최적 온도 상한
_T_LIMIT_BAND = 6.0     # °C    — 최적대 이탈 시 제한 인자 득점 스케일
_VPD_STRESS   = 1.5     # kPa   — VPD 기공 폐쇄 임계
_VPD_SEVERE   = 2.5     # kPa   — VPD 심각 수분 스트레스


def _assess_limiting_factor(ctx: EnvContext, light_sat: Optional[float] = None) -> Optional[str]:
    """
    광합성 제한 인자를 단순 점수 기반으로 평가.

    야간(solar < _LIGHT_COMP)이면 None 반환 (광합성 없음).
    주간에는 light/co2/temperature/water 중 득점 최고 인자 반환.
    모든 조건 충족 시(득점 0) → None.
    """
    solar = ctx.get('solar', 0.0)

    if solar < _LIGHT_COMP:
        return None   # 야간 — 광합성 평가 불필요

    sat = light_sat if (light_sat and light_sat > 0) else _LIGHT_SAT
    scores: Dict[str, float] = {}

    # 광 제한
    if solar < sat:
        scores['light'] = (sat - solar) / sat

    # CO₂ 제한 — 측정이 없으면 판단하지 않는다(없는 값으로 제한 인자를
    # 고르면 늘 CO₂ 가 부족하다고 답한다).
    co2 = ctx.get('CO2_int')
    if co2 is not None and co2 < _CO2_OPT:
        scores['co2'] = max(0.0, (_CO2_OPT - co2) / (_CO2_OPT - _CO2_COMP + 1e-6))

    # 온도 제한
    T = ctx['T_int']
    if T < _T_OPT_LO:
        scores['temperature'] = min(1.0, (_T_OPT_LO - T) / _T_LIMIT_BAND)
    elif T > _T_OPT_HI:
        scores['temperature'] = min(1.0, (T - _T_OPT_HI) / _T_LIMIT_BAND)

    # 수분(VPD) 제한
    vpd = ctx.get('VPD_int', 0.0)
    if vpd <= 0.0:
        vpd = _compute_vpd(T, ctx['RH_int'])
    if vpd > _VPD_STRESS:
        scores['water'] = min(1.0, (vpd - _VPD_STRESS) / (_VPD_SEVERE - _VPD_STRESS + 1e-6))

    if not scores:
        return None
    return max(scores, key=scores.__getitem__)


# ─────────────────────────────────────────────────────────────────────────────
# D3: 운전 모드 결정 (§5.7)
# ─────────────────────────────────────────────────────────────────────────────

# 추세 기반 예측 리드 타임 — 이 분 이내에 허용 범위를 벗어날 것 같으면 선제 대응
_TREND_LEAD_MIN = 5.0


def _decide_modes(
    target: EnvTarget,
    ctx: EnvContext,
    limiting: Optional[str],
) -> List[str]:
    """
    운전 모드를 결정한다. 편차(정적) + 추세(동적) + 제한 인자(광합성)를 모두 반영.

    선제 대응 조건:
      trend_lead = (tol - |deviation|) / |trend_per_cycle|
      trend_lead < _TREND_LEAD_MIN 이면 이미 편차 없어도 모드 활성
    """
    modes: List[str] = []
    T_now   = ctx['T_int']
    RH_now  = ctx['RH_int']
    CO2_now = ctx.get('CO2_int')
    solar   = ctx.get('solar', 0.0)

    T_trend   = ctx.get('T_trend',   0.0)   # °C/min
    RH_trend  = ctx.get('RH_trend',  0.0)   # %/min
    CO2_trend = ctx.get('CO2_trend', 0.0)   # ppm/min

    # ── 온도 ─────────────────────────────────────────────────────────────────
    if 'temperature' in target:
        tv  = target['temperature']
        dev = T_now - tv.value
        if T_now > tv.value + tv.tolerance:
            modes.append(MODE_COOLING)
        elif T_now < tv.value - tv.tolerance:
            modes.append(MODE_HEATING)
        else:
            # 추세 선제 대응
            margin = tv.tolerance - abs(dev)
            if T_trend > 0 and margin > 0:
                lead = margin / (T_trend + 1e-9)
                if lead < _TREND_LEAD_MIN:
                    modes.append(MODE_COOLING)
            elif T_trend < 0 and margin > 0:
                lead = margin / (abs(T_trend) + 1e-9)
                if lead < _TREND_LEAD_MIN:
                    modes.append(MODE_HEATING)
            # 광합성 온도 제한 → 목표 초과/미달 아니어도 모드 활성
            elif limiting == 'temperature':
                if T_now > _T_OPT_HI:
                    modes.append(MODE_COOLING)
                elif T_now < _T_OPT_LO:
                    modes.append(MODE_HEATING)

    # ── 습도 ─────────────────────────────────────────────────────────────────
    if 'humidity' in target:
        hv  = target['humidity']
        dev = RH_now - hv.value
        if RH_now < hv.value - hv.tolerance:
            modes.append(MODE_HUMIDIFY)
        elif RH_now > hv.value + hv.tolerance:
            modes.append(MODE_DEHUMIDIFY)
        else:
            margin = hv.tolerance - abs(dev)
            if RH_trend < 0 and margin > 0:
                lead = margin / (abs(RH_trend) + 1e-9)
                if lead < _TREND_LEAD_MIN:
                    modes.append(MODE_HUMIDIFY)
            elif RH_trend > 0 and margin > 0:
                lead = margin / (RH_trend + 1e-9)
                if lead < _TREND_LEAD_MIN:
                    modes.append(MODE_DEHUMIDIFY)
            # 수분 스트레스 → 습도 올리기
            elif limiting == 'water':
                modes.append(MODE_HUMIDIFY)

    # ── CO₂ ─────────────────────────────────────────────────────────────────
    # 측정이 없으면 주입 판단을 하지 않는다 — 없는 값으로 "부족하다" 고 답하면
    # 센서 없는 시설에서 낮마다 CO₂ 주입 모드가 선다.
    if 'co2' in target and CO2_now is not None:
        cv  = target['co2']
        dev = CO2_now - cv.value
        if CO2_now < cv.value - cv.tolerance and solar > 10:
            modes.append(MODE_CO2_ENRICH)
        elif solar > 10 and limiting == 'co2':
            # 광합성이 CO₂ 제한이고 낮이면 허용 범위 안이어도 주입
            if CO2_now < _CO2_OPT:
                modes.append(MODE_CO2_ENRICH)

    if not modes:
        modes.append(MODE_CONSERVATION)

    return modes


# ─────────────────────────────────────────────────────────────────────────────
# D4: VPD 분해 (§5.4 옵션 A) — Phase C 구현 유지
# ─────────────────────────────────────────────────────────────────────────────

def _decompose_vpd(target: EnvTarget, ctx: EnvContext) -> EnvTarget:
    """VPD 우선 정책 (P6 — 분해 폐기, VPD 직접 제어).

    사용자 정책: VPD 측정값과 목표가 모두 있으면 VPD 가 다른 무엇보다 우선되어야
    하고, VPD 가 없으면 온/습도가 후순위 제어 기준이 된다.

    - VPD 목표 + VPD 측정 존재  → VPD 를 1차 제어변수로 유지(deviation 에 'vpd').
      T/RH 는 제어목표에서 제외(`_..._constraint` 로 강등, 진단 보존). 액추에이터엔
      유도 VPD effect(effect_functions.make_vpd_effect)가 있어 결합 drive 가 VPD 를
      직접 제어한다. 기존 VPD→T 분해의 ∂VPD/∂T 증폭(작은 VPD 편차 → 큰 온도오차)
      이 사라진다. T/RH 상·하한은 별도 constraint 검사가 강제.
    - VPD 미설정/측정불가 → T/RH 를 제어 기준으로 사용(폴백). vpd 는 진단으로.
    """
    import copy
    t = copy.deepcopy(target)
    vpd_tv  = t.get('vpd')
    vpd_int = ctx.get('VPD_int') or 0.0

    if vpd_tv is not None and vpd_int > 0.05:
        # VPD 직접 제어 — T/RH 제어목표 제외(진단/제약 보존)
        for k in ('temperature', 'humidity'):
            if k in t:
                t['_%s_constraint' % k] = t.pop(k)
        return t

    # 폴백: VPD 사용 불가 → T/RH 제어 기준. vpd 는 진단으로 강등.
    if vpd_tv is not None:
        t['_vpd_diag'] = t.pop('vpd')
    return t


# ─────────────────────────────────────────────────────────────────────────────
# 공개 유틸리티 (테스트·외부 사용 가능)
# ─────────────────────────────────────────────────────────────────────────────

def svp(T: float) -> float:
    """포화 수증기압 [kPa], Magnus 공식. T: °C."""
    return 0.6108 * math.exp(17.27 * T / (T + 237.3))


def compute_vpd(T: float, RH: float) -> float:
    """실제 VPD [kPa] = SVP(T) × (1 - RH/100)."""
    return max(0.0, (1 - RH / 100.0) * svp(T))


def decompose_vpd_to_T_RH(
    vpd_target: float,
    T_int: float,
    RH_int: float,
    w_T: float = 0.6,
) -> Tuple[float, float]:
    """
    VPD 목표값을 (T_aux, RH_aux) 보조목표로 분해한다. (P1-1, 설계 §3.1)

    알고리즘:
      1. 현재 수증기압(ea) 유지 시 VPD 목표를 달성하는 T_needed 를 산출
      2. T_aux = lerp(T_int, T_needed, w_T)  (w_T 비중만큼 T 이동)
      3. T_aux 에서 VPD 제약을 정확히 만족하는 RH_aux 를 역산
      4. RH_aux 를 [0, 100] 으로 클램프

    **1번에서 고정하는 것은 RH 가 아니라 ea 다.** 밀폐 공간을 가열해도 물이
    늘지 않으므로 보존되는 것은 수증기압이고 RH 는 따라 내려간다. RH 를
    고정으로 두면 VPD = (1−RH/100)·svp(T) 의 (1−RH/100) 인자가 그대로 남아,
    **RH=100% 에서 온도가 VPD 에 아무 영향이 없다**는 결론이 나온다 — 즉
    포화 상태(VPD=0)에서 난방 요구가 0 이 되어 가열이 영영 일어나지 않는다.
    RH=99.9% 에서는 반대로 T_needed 가 상한(50°C)까지 튀어 "아무것도 안 함"과
    "최대 가열" 사이에 중간이 없었다. ea 고정은 두 경우 모두 같은 답을 준다.

    부수 효과로 1번과 3번이 서로 맞는다: w_T=1 이면 3번이 되돌리는 RH_aux 가
    정확히 ea 를 보존한다(RH_aux/100·svp(T_aux) = ea). 예전에는 1번이 RH 고정,
    3번이 VPD 고정이라 두 단계가 서로 다른 물리를 쓰고 있었다.

    Args:
        vpd_target: 목표 VPD [kPa]
        T_int:      현재 실내 온도 [°C]
        RH_int:     현재 실내 습도 [%]
        w_T:        온도 변경 비중 (0=RH만, 1=T만, 기본 0.6)

    Returns:
        (T_aux, RH_aux) — 보조 목표 (T °C, RH %)
    """
    vpd_target = max(0.0, vpd_target)  # 물리적 하한

    # 이미 목표 충족 시 현재값 반환
    vpd_now = compute_vpd(T_int, RH_int)
    if abs(vpd_now - vpd_target) < 1e-4:
        return T_int, RH_int

    # 1. 현재 수증기압(ea) 유지 시 필요한 T_needed
    T_needed = _invert_svp_for_T(vpd_target, RH_int, T_ref=T_int)

    # 2. w_T 비중만큼 T 이동
    T_aux = T_int + w_T * (T_needed - T_int)
    T_aux = max(-10.0, min(50.0, T_aux))

    # 3. T_aux 에서 VPD 제약 정확히 만족하는 RH_aux
    svp_aux = svp(T_aux)
    if svp_aux < 1e-9:
        RH_aux = RH_int
    else:
        RH_aux = (1.0 - vpd_target / svp_aux) * 100.0

    # 4. 물리 범위 클램프
    RH_aux = max(0.0, min(100.0, RH_aux))

    return T_aux, RH_aux


# ─────────────────────────────────────────────────────────────────────────────
# 내부 유틸리티 (하위 호환 aliases)
# ─────────────────────────────────────────────────────────────────────────────

def _get_measured(var: str, ctx: EnvContext) -> Optional[float]:
    mapping = {
        'temperature': ctx.get('T_int'),
        'humidity':    ctx.get('RH_int'),
        'co2':         ctx.get('CO2_int'),
        'vpd':         ctx.get('VPD_int'),
    }
    return mapping.get(var)


# 기존 코드 호환용 내부 별칭
def _svp(T: float) -> float:
    return svp(T)


def _compute_vpd(T: float, RH: float) -> float:
    return compute_vpd(T, RH)


def _invert_svp_for_T(vpd_target: float, RH: float, T_ref: float = 20.0) -> float:
    """수증기압(ea)을 고정한 채 VPD 목표를 만족하는 T 를 해석적으로 구한다.

    ea    = RH/100 · svp(T_ref)          — (T_ref, RH) 상태의 수증기압
    조건  = svp(T) − ea = vpd_target     → svp(T) = vpd_target + ea
    Magnus 역함수로 닫힌 해를 얻는다. 반복이 필요 없다.

    **RH 고정이 아니라 ea 고정인 이유**: 가열은 물을 늘리지 않으므로 보존되는
    것은 ea 다. RH 를 고정으로 두면 f·df 에 (1−RH/100) 이 공통으로 남아
    RH=100 에서 df=0 → 뉴턴법이 첫 회에 탈출하며 **T_guess 를 그대로 반환**했다.
    호출부가 T_guess=T_int 를 넘기므로 "필요 온도 = 현재 온도" 가 되어 난방
    요구가 0 이 된다(포화 상태에서 가열이 일어나지 않던 원인).

    Args:
        vpd_target: 목표 VPD [kPa] (음수는 0 으로 클램프)
        RH:         기준 상태의 상대습도 [%]
        T_ref:      기준 상태의 온도 [°C] — ea 산출에 쓰인다

    Returns:
        목표 VPD 를 만족하는 온도 [°C], [-10, 50] 클램프.
    """
    vpd_target = max(0.0, vpd_target)
    ea = max(0.0, min(100.0, RH) / 100.0) * svp(T_ref)
    s_need = vpd_target + ea
    if s_need <= 0.0:
        return max(-10.0, min(50.0, T_ref))
    r = math.log(s_need / 0.6108)
    if r >= 17.27:                       # Magnus 의 점근선 — 물리적 상한 밖
        return 50.0
    return max(-10.0, min(50.0, 237.3 * r / (17.27 - r)))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t
