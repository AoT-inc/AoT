# coding=utf-8
"""
env_control/goal.py — Layer 1 목표 관리자 (Phase E 구현 전 스텁).

현재는 Function custom_options 에서 사용자가 직접 입력한 정적 목표값을 반환.
Phase E 에서 작물 라이브러리 + 시간 곡선 보간으로 교체 예정.

참조: docs/dev/integrated_env_control_design.md §5.1~§5.3
"""

from __future__ import annotations

from typing import Optional

from .types import EnvTarget, TargetVar


def build_env_target(
    T_target: float   = 24.0, T_tol: float   = 1.0, T_pri: float   = 1.0,
    RH_target: float  = 65.0, RH_tol: float  = 5.0, RH_pri: float  = 0.8,
    CO2_target: float = 1000, CO2_tol: float = 100, CO2_pri: float = 0.6,
    VPD_target: Optional[float] = None,
    VPD_tol: float = 0.1, VPD_pri: float = 1.2,
    Light_target: Optional[float] = None,
    Light_tol: float = 50.0, Light_pri: float = 0.9,
) -> EnvTarget:
    """사용자 설정값으로 EnvTarget 생성 (L1 스텁).

    R1: VPD primary (VPD_target 설정 시 활성)
    R2: Light secondary primary, optional (Light_target 설정 시 활성, 보광 등록 시)
    R3: T/RH 는 호출자가 constraint 로 별도 관리 (이 함수는 추적 목표용 변수만 반환)

    Phase E 에서 작물 프로필·시간 보간으로 교체 시
    이 함수 서명을 유지한 채 내부만 교체.
    """
    target: EnvTarget = {
        'temperature': TargetVar(T_target,   T_tol,   T_pri,   '°C'),
        'humidity':    TargetVar(RH_target,  RH_tol,  RH_pri,  '%'),
        'co2':         TargetVar(CO2_target, CO2_tol, CO2_pri, 'ppm'),
    }
    if VPD_target is not None:
        target['vpd'] = TargetVar(VPD_target, VPD_tol, VPD_pri, 'kPa')
    if Light_target is not None and Light_target > 0:
        # R2: 보광 등록된 시설에서만 활성. 단위는 PPFD (µmol/m²/s).
        target['light'] = TargetVar(Light_target, Light_tol, Light_pri, 'µmol/m²/s')
    return target
