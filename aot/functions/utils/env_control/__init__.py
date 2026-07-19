# coding=utf-8
"""
env_control — 통합 환경 제어 시스템 인프라 패키지 (Phase A).

공개 인터페이스:
  types          — 핵심 타입 (ActuatorProfile, ManualLockState, EnvTarget 등)
  effect_functions — 액추에이터별 EffectFn 구현체
  log_channels   — InfluxDB 의사결정 로깅 채널 상수
  safety_gates   — Pre-Gate / Post-Gate 프레임워크

Output 플러그인이 구현해야 하는 인터페이스 (A3):
  - 모듈 수준 변수 ACTUATOR_PROFILE: dict  (ActuatorProfile 필드 포함)
  - 인스턴스 메서드 get_profile() -> ActuatorProfile
  - 인스턴스 메서드 manual_acquire(value, ttl_sec, reason)
  - 인스턴스 메서드 manual_release()

참조: docs/dev/integrated_env_control_design.md §3, §7
"""

from .types import (
    ActuatorProfile,
    CmdConstraints,
    CostFn,
    EffectFn,
    EffectResult,
    EnvContext,
    EnvTarget,
    ManualLockState,
    SituationReport,
    TargetVar,
    apply_calibration,
)

from .effect_functions import DEFAULT_EFFECT_MODELS

from .log_channels import (
    write_decision_log,
    REASON_IDLE,
    REASON_PRIMARY,
    REASON_SECONDARY,
    REASON_WRONG_DIRECTION,
    REASON_SIDE_EFFECT,
    REASON_SAFETY_PRE_GATE,
    REASON_UNAVAILABLE,
    REASON_SAFETY_POST_GATE,
    REASON_MANUAL_OVERRIDE,
    CH_DISPATCH_FAIL,
    CH_RUNTIME_STATE_FAIL,
    CH_ACTUATOR_MISMATCH,
    CH_CLEAN_FOR_LEARNING,
)

from .safety_gates import (
    GateResult,
    PreGateConfig,
    SafetyPreGate,
    SafetyPostGate,
)

__all__ = [
    # types
    'ActuatorProfile', 'CmdConstraints', 'CostFn', 'EffectFn', 'EffectResult',
    'EnvContext', 'EnvTarget', 'ManualLockState', 'SituationReport', 'TargetVar',
    'apply_calibration',
    # effect_functions
    'DEFAULT_EFFECT_MODELS',
    # log_channels
    'write_decision_log',
    'REASON_IDLE', 'REASON_PRIMARY', 'REASON_SECONDARY',
    'REASON_WRONG_DIRECTION', 'REASON_SIDE_EFFECT',
    'REASON_SAFETY_PRE_GATE', 'REASON_UNAVAILABLE',
    'REASON_SAFETY_POST_GATE', 'REASON_MANUAL_OVERRIDE',
    'CH_DISPATCH_FAIL', 'CH_RUNTIME_STATE_FAIL',
    'CH_ACTUATOR_MISMATCH', 'CH_CLEAN_FOR_LEARNING',
    # safety_gates
    'GateResult', 'PreGateConfig', 'SafetyPreGate', 'SafetyPostGate',
]
