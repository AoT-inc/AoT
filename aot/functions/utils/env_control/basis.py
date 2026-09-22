# coding=utf-8
"""
env_control/basis.py — 제어 기준(control basis): VPD 직접 / 온도 우선.

## 왜 온도 우선인가 (2026-09-22, 계획서 `env-vpd-role-shift.md`)

VPD 를 1차 목표로 직접 좇으면 고온·저온에서 틀린다.

- ∂VPD/∂RH = SVP(T)/100 — 같은 허용오차 0.1 kPa 가 8 °C 에선 RH ±9 %, 35 °C
  에선 ±1.8 %. 고온에선 과민, 저온에선 둔감하다.
- 12 °C 에서 VPD 1.0 은 RH 29 % 가 필요하다 — 유도 범위로는 닿지 못해 가온·
  건조 요구가 영영 남는다.
- 실외가 건조하면 창을 열수록 VPD 가 올라, VPD 제어는 고온에서도 창을 닫는
  쪽으로 기운다.

그래서 온도 우선 모드는 **온도를 1차로** 좇고, VPD 목표는 **그 온도에서의 습도
목표**로 바꾼다: RH* = 100·(1 − VPD*/SVP(T*)). 습도 오차는 %RH 단위라 온도에
따른 민감도 차이가 없다. VPD 자체는 목표가 아니라 **경계**(너무 낮으면 결로·병해,
너무 높으면 수분 스트레스)로만 남는다.

⚠ 예전에 폐기한 "VPD 분해" 와 다르다 — 그것은 VPD 를 맞추려고 **온도 목표를
  옮겼고**, 작은 VPD 편차가 큰 온도 오차로 부풀었다. 여기서는 온도 목표가 VPD 와
  무관하게 정해지고, VPD 로는 습도 목표만 만든다.

⚠ **단계에 온도가 없으면 온도를 좇지 않는다(밴드 모드).** 목표 = 지금 온도를
  유도 범위로 클램프한 값이라, 범위 안에서는 편차 0 으로 쉬고 밖에서만 경계로
  끌어온다. 유도 범위 중앙(기본 22 °C)을 조용히 능동 추종하면 사람이 정한 적 없는
  목표가 생긴다 — 2026-08-22 에 기록한 옛 목표 소실 사고와 같은 모양이다.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from .goal import build_env_target
from .types import EnvTarget, TargetVar

BASIS_VPD         = 'vpd'
BASIS_TEMPERATURE = 'temperature'

T_TOL,  T_PRI  = 1.0, 1.2     # 온도가 VPD 의 우선도 자리를 받는다
RH_TOL, RH_PRI = 5.0, 0.8
VPD_BAND_BELOW = 0.4          # 경계 = VPD 목표 − 이것 ~ + VPD_BAND_ABOVE (kPa)
VPD_BAND_ABOVE = 0.8
VPD_BAND_FLOOR = 0.05
VPD_LIMIT_TOL  = 0.1
VPD_LIMIT_PRI  = 1.0


def _svp(T: float) -> float:
    return 0.6108 * math.exp(17.27 * T / (T + 237.3))


def temperature_basis(vpd_target: Optional[float], stage_T: Optional[float],
                      T_int: Optional[float], RH_int: Optional[float],
                      guide: Tuple[float, float, float, float]) -> dict:
    """온도 우선 모드의 목표 한 벌. 순수 함수.

    Args:
        vpd_target: 이번 사이클 VPD 목표(kPa) — 없으면 습도는 밴드 모드
        stage_T:    단계의 지금(주간/야간) 온도 — 없으면 온도는 밴드 모드
        guide:      이번 사이클 유도 범위 (T_min, T_max, RH_min, RH_max)
    """
    T_lo, T_hi, RH_lo, RH_hi = (float(v) for v in guide)

    def clamp(v, lo, hi):
        return max(lo, min(hi, float(v)))

    if stage_T is not None:
        T_target, t_mode = clamp(stage_T, T_lo, T_hi), 'stage'
    elif T_int is not None:
        T_target, t_mode = clamp(T_int, T_lo, T_hi), 'band'
    else:
        T_target, t_mode = (T_lo + T_hi) / 2.0, 'band'

    if vpd_target and vpd_target > 0.0:
        # 기준 온도는 **온도 목표**다(D1) — 지금 온도로 역산하면 온도가 흔들릴
        # 때마다 습도 목표도 따라 흔들린다.
        rh_raw, rh_mode = 100.0 * (1.0 - vpd_target / _svp(T_target)), 'vpd'
    elif RH_int is not None:
        rh_raw, rh_mode = float(RH_int), 'band'
    else:
        rh_raw, rh_mode = (RH_lo + RH_hi) / 2.0, 'band'
    RH_target = clamp(rh_raw, RH_lo, RH_hi)

    band = None
    if vpd_target and vpd_target > 0.0:
        band = (max(VPD_BAND_FLOOR, vpd_target - VPD_BAND_BELOW),
                vpd_target + VPD_BAND_ABOVE)
    return {
        'T_target': round(T_target, 2), 'T_mode': t_mode,
        'RH_target': round(RH_target, 1), 'RH_mode': rh_mode,
        'RH_clamped': abs(RH_target - rh_raw) > 1e-6,
        'vpd_band': None if band is None else (round(band[0], 3), round(band[1], 3)),
    }


def build_temperature_env_target(basis: dict, vpd_int: Optional[float],
                                 co2_target: Optional[float],
                                 co2_tol: float, co2_pri: float) -> EnvTarget:
    """온도 우선 모드의 EnvTarget. VPD 는 경계를 넘은 사이클에만 경계 항으로 든다."""
    target = build_env_target(
        T_target=basis['T_target'], T_tol=T_TOL, T_pri=T_PRI,
        RH_target=basis['RH_target'], RH_tol=RH_TOL, RH_pri=RH_PRI,
        CO2_target=co2_target or 1000.0, CO2_tol=co2_tol, CO2_pri=co2_pri,
        VPD_target=None)
    if co2_target is None:
        target.pop('co2', None)
    band = basis.get('vpd_band')
    if band and vpd_int is not None:
        lo, hi = band
        edge = lo if vpd_int < lo else hi if vpd_int > hi else None
        if edge is not None:
            target['vpd'] = TargetVar(edge, VPD_LIMIT_TOL, VPD_LIMIT_PRI, 'kPa',
                                      limit=True)
    return target
