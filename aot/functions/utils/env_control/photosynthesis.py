# coding=utf-8
"""
env_control/photosynthesis.py — Big-Leaf 광합성 모델 + 작물 프리셋 (P5-4).

단순화 Big-Leaf 모델로 순광합성률(A_n)을 추정하고,
민감도 분석으로 현재 제한인자를 자동 식별한다.

참조: docs/env_control_enhancement_design.md §3.19
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Optional

# ─────────────────────────────────────────────────────────────────────────────
# 작물 파라미터 (CropParams)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CropParams:
    """Big-Leaf 모델 작물 파라미터.

    Attributes:
        name:       작물 이름 (표시용)
        A_max:      최대 순광합성률 [μmol CO₂/m²/s] — 광·CO₂ 포화 + 최적 T/VPD 조건
        K_L:        광 반포화 상수 [μmol/m²/s] — 이 PPFD에서 A_max/2
        K_C:        CO₂ 반포화 상수 [ppm]
        T_opt:      최적 온도 [°C] — Gaussian 피크
        T_sigma:    온도 응답 폭 [°C] — 클수록 넓은 범위 허용
        VPD_half:   기공 전도 반포화 VPD [kPa] — 이 값에서 g_stomata = 0.5
        T_base:     GDD 기준 온도 [°C] (광합성 계산에 직접 사용 안 함, GDD 참조용)
        dli_target: 권장 일적산광량 [mol/m²/day] — DLI 추적 목표 기본값
        gdd_daily:  권장 일일 적산온도 [°C·day/day] — GDD 추적 목표 기본값
                    (최적 생육 시 ≈ T_opt − T_base)
        vpd_target: 권장 VPD 목표 [kPa] — 정적 VPD 목표 기본값
        co2_target: 권장 CO₂ 목표 [ppm] — 정적 CO₂ 목표 기본값
        temp_min:   권장 하한 온도 [°C] — 강제 난방 한계
        temp_max:   권장 상한 온도 [°C] — 강제 냉방 한계
    """
    name:      str   = 'generic'
    A_max:     float = 25.0
    K_L:       float = 200.0
    K_C:       float = 400.0
    T_opt:     float = 25.0
    T_sigma:   float = 8.0
    VPD_half:  float = 1.5
    T_base:    float = 10.0
    dli_target: float = 0.0    # 0 = 미설정
    gdd_daily:  float = 0.0    # 0 = 미설정
    vpd_target: float = 0.0    # 0 = 미설정
    co2_target: float = 0.0    # 0 = 미설정
    temp_min:   float = 0.0    # 0 = 미설정
    temp_max:   float = 0.0    # 0 = 미설정


# ─────────────────────────────────────────────────────────────────────────────
# 작물 프리셋 5종 (시드)
# ─────────────────────────────────────────────────────────────────────────────

# DLI(mol/m²/day)·gdd_daily(°C·day/day) 는 시설 재배 권장 범위 기준값(작물별 문헌).
# gdd_daily ≈ T_opt − T_base (최적 생육 시 일일 적산온도).
CROP_PRESETS: Dict[str, CropParams] = {
    'tomato': CropParams(
        name='Tomato',
        A_max=25.0, K_L=200.0, K_C=350.0,
        T_opt=24.0, T_sigma=7.0, VPD_half=1.2,
        T_base=10.0, dli_target=22.0, gdd_daily=14.0,
        vpd_target=1.0, co2_target=900.0, temp_min=12.0, temp_max=32.0,
    ),
    'lettuce': CropParams(
        name='Lettuce',
        A_max=15.0, K_L=120.0, K_C=300.0,
        T_opt=20.0, T_sigma=6.0, VPD_half=1.8,
        T_base=4.0, dli_target=14.0, gdd_daily=16.0,
        vpd_target=0.8, co2_target=800.0, temp_min=4.0, temp_max=27.0,
    ),
    'cucumber': CropParams(
        name='Cucumber',
        A_max=28.0, K_L=220.0, K_C=380.0,
        T_opt=26.0, T_sigma=7.0, VPD_half=1.3,
        T_base=12.0, dli_target=22.0, gdd_daily=14.0,
        vpd_target=0.9, co2_target=1000.0, temp_min=14.0, temp_max=34.0,
    ),
    'strawberry': CropParams(
        name='Strawberry',
        A_max=18.0, K_L=150.0, K_C=320.0,
        T_opt=20.0, T_sigma=6.0, VPD_half=1.4,
        T_base=7.0, dli_target=17.0, gdd_daily=13.0,
        vpd_target=0.8, co2_target=800.0, temp_min=4.0, temp_max=28.0,
    ),
    'pepper': CropParams(
        name='Pepper',
        A_max=22.0, K_L=180.0, K_C=360.0,
        T_opt=25.0, T_sigma=7.5, VPD_half=1.3,
        T_base=10.0, dli_target=22.0, gdd_daily=15.0,
        vpd_target=1.0, co2_target=900.0, temp_min=12.0, temp_max=32.0,
    ),
}

DEFAULT_CROP = CROP_PRESETS['tomato']


def get_crop_params(crop_key: Optional[str]) -> CropParams:
    """crop_key로 프리셋을 반환한다. 없으면 tomato(기본)."""
    if not crop_key:
        return DEFAULT_CROP
    return CROP_PRESETS.get(crop_key, DEFAULT_CROP)


# ─────────────────────────────────────────────────────────────────────────────
# Big-Leaf 광합성 모델
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# 광 단위 경계 — 이 모듈은 **PPFD(µmol/m²/s)** 로만 말한다
# ─────────────────────────────────────────────────────────────────────────────
# `internal['light']` 은 시스템 관례상 **W/m²(전천일사)** 다(_cycle_mixin 주석).
# 그런데 여기 `K_L` 은 µmol/m²/s 반포화 상수라, 변환 없이 넣으면 **다른 단위를
# 같은 축에서 비교**하게 된다. 화면에서도 "광량 482 / 100 µmol/m²/s" 처럼
# 482(W/m²) 옆에 µmol 목표가 붙어, 실제로는 목표를 한참 넘긴 상태가 부족한
# 것처럼(혹은 그 반대로) 보였다 — 2026-08-26 지적으로 발견.
#
# 계수는 `config_devices_units` 의 W_m2 → umol_m2_s 와 **같은 2.02** 다.
# ⚠ 4.57 이 아니다 — 그 값은 PAR 대역 W/m² 전용이고, 전천일사에는 2.02 다
# (2026-08-25 `a2b1974a` 에서 시스템 전체를 이 값으로 맞췄다).
WM2_TO_PPFD = 2.02


def ppfd_from_wm2(w_m2):
    """전천일사 W/m² → PPFD µmol/m²/s. None 은 그대로 통과."""
    if w_m2 is None:
        return None
    return float(w_m2) * WM2_TO_PPFD


def estimate_net_photosynthesis(
    L: float,
    CO2: float,
    T: float,
    VPD: float,
    crop_params: CropParams,
) -> float:
    """순광합성률 A_n [μmol CO₂/m²/s] 추정 (단순화 Big-Leaf).

    4개 응답 함수의 곱:
      1. 광 응답 (rectangular hyperbola)
      2. CO₂ 응답 (Michaelis-Menten)
      3. 온도 응답 (Gaussian)
      4. VPD 응답 (기공 전도 감소)

    Args:
        L:           PPFD [μmol/m²/s] — 0 이하면 0 반환
        CO2:         CO₂ 농도 [ppm]
        T:           기온 [°C]
        VPD:         수증기압 부족 [kPa] — 0 이하면 0.01로 클램프
        crop_params: 작물 파라미터

    Returns:
        A_n ≥ 0 [μmol CO₂/m²/s]
    """
    L   = max(0.0, L)
    CO2 = max(1.0, CO2)
    VPD = max(0.01, VPD)

    if L < 1e-6:
        return 0.0

    p = crop_params

    # 1. 광 응답
    A_light = (p.A_max * L) / (L + p.K_L)

    # 2. CO₂ 응답
    A_co2 = A_light * (CO2 / (CO2 + p.K_C))

    # 3. 온도 응답 (Gaussian)
    T_factor = math.exp(-((T - p.T_opt) ** 2) / (2.0 * p.T_sigma ** 2))

    # 4. VPD 응답 (기공 전도)
    g_stomata = 1.0 / (1.0 + (VPD / p.VPD_half) ** 2)

    return max(0.0, A_co2 * T_factor * g_stomata)


# ─────────────────────────────────────────────────────────────────────────────
# 제한인자 식별
# ─────────────────────────────────────────────────────────────────────────────

# 민감도 분석 섭동 (퍼센트 또는 절댓값)
_PERTURB = {
    'light': ('rel', 1.1),   # L × 1.1
    'co2':   ('rel', 1.1),   # CO2 × 1.1
    'temperature': ('abs', 1.0),  # T + 1°C
    'vpd':   ('rel', 0.9),   # VPD × 0.9 (낮을수록 유리)
}


def find_limiting_factor(
    L: float,
    CO2: float,
    T: float,
    VPD: float,
    crop_params: CropParams,
) -> str:
    """현재 조건에서 광합성을 가장 제한하는 인자를 반환한다.

    각 변수를 소폭 개선(+10% 또는 절댓값 δ)했을 때 A_n 증가량을 비교.
    가장 큰 증가를 주는 변수가 현재 제한인자.

    Returns:
        'light' | 'co2' | 'temperature' | 'vpd'
    """
    base = estimate_net_photosynthesis(L, CO2, T, VPD, crop_params)

    sensitivities: Dict[str, float] = {}
    for factor, (mode, delta) in _PERTURB.items():
        if mode == 'rel':
            perturbed = estimate_net_photosynthesis(
                L * delta if factor == 'light' else L,
                CO2 * delta if factor == 'co2' else CO2,
                T,
                VPD * delta if factor == 'vpd' else VPD,
                crop_params,
            )
        else:  # abs
            perturbed = estimate_net_photosynthesis(
                L, CO2, T + delta, VPD, crop_params)
        sensitivities[factor] = max(0.0, perturbed - base)

    # 모두 0이면 (야간 등) — 빛이 기본 제한인자
    if max(sensitivities.values()) < 1e-9:
        return 'light'

    return max(sensitivities, key=sensitivities.get)


# ─────────────────────────────────────────────────────────────────────────────
# Priority 격상 헬퍼 (§3.19.3)
# ─────────────────────────────────────────────────────────────────────────────

# EnvTarget 변수명 → find_limiting_factor 반환값 매핑
_FACTOR_TO_VAR = {
    'light':       'light',
    'co2':         'co2',
    'temperature': 'temperature',
    'vpd':         'vpd',
}

# 지수가중평균 α (안정성 §3.19.4)
_EWA_ALPHA = 0.3
# 우선순위 최대 배율 상한 (기본값 대비)
_PRIORITY_MAX_RATIO = 2.0
# 사이클당 최대 우선순위 변화 비율
_PRIORITY_STEP_MAX = 0.20


def boost_limiting_priority(
    env_target,
    limiting_factor: str,
    authority: Dict[str, str],
    priority_ewa_state: Dict[str, float],
    base_priorities: Dict[str, float],
) -> None:
    """제한인자 변수의 우선순위를 일시 격상한다 (in-place).

    안정성 §3.19.4:
      - EWA 평활화 (α=0.3) 로 급격한 변동 억제
      - 사이클당 ±20% 이내
      - 기본값의 2배 상한

    Args:
        env_target:         EnvTarget (in-place 수정)
        limiting_factor:    find_limiting_factor() 반환값
        authority:          derive_authority() 결과
        priority_ewa_state: {var: ewa_priority} 사이클 간 보존 상태 (in-place 갱신)
        base_priorities:    {var: base_priority} — 기본 우선순위 (상한 계산 기준)
    """
    var = _FACTOR_TO_VAR.get(limiting_factor)
    if var is None or var not in env_target:
        return

    # NATURAL 제한인자는 격상 불가
    from .authority import is_natural_var
    if is_natural_var(authority, var):
        return

    tv = env_target[var]
    base_pri = base_priorities.get(var, tv.priority)
    target_pri = min(base_pri * 1.5, base_pri * _PRIORITY_MAX_RATIO)

    # EWA 평활화
    prev_ewa = priority_ewa_state.get(var, tv.priority)
    new_ewa = _EWA_ALPHA * target_pri + (1.0 - _EWA_ALPHA) * prev_ewa

    # Slew rate 제한
    max_delta = base_pri * _PRIORITY_STEP_MAX
    new_pri = max(prev_ewa - max_delta, min(prev_ewa + max_delta, new_ewa))

    priority_ewa_state[var] = new_pri
    tv.priority = new_pri


def decay_priorities(
    env_target,
    priority_ewa_state: Dict[str, float],
    base_priorities: Dict[str, float],
) -> None:
    """제한인자가 없을 때 모든 변수 우선순위를 기본값으로 복귀 (in-place)."""
    alpha = _EWA_ALPHA
    for var, tv in env_target.items():
        if var.startswith('_'):
            continue
        base_pri = base_priorities.get(var, tv.priority)
        prev_ewa = priority_ewa_state.get(var, base_pri)
        new_ewa  = alpha * base_pri + (1.0 - alpha) * prev_ewa
        priority_ewa_state[var] = new_ewa
        tv.priority = new_ewa
