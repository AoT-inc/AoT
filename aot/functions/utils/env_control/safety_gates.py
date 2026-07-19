# coding=utf-8
"""
env_control/safety_gates.py — 안전 게이트 프레임워크 (P8).

P8 원칙: 안전은 조율 알고리즘 외부에 있다.
  - Pre-Gate: L1~L3 진입 전 평가. 발동 시 조율 우회 → 직접 강제 명령 생성.
  - Post-Gate: L3 결과를 L4 전달 전 정합성 검사·보정.

Phase A 에서는 호출 지점을 확보하고 기본 구현체를 제공한다.
각 Gate 조건의 임계값은 Function custom_options 로 사용자 설정 가능.

참조: docs/dev/integrated_env_control_design.md §6
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .log_channels import (
    GATE_BIT_RAIN, GATE_BIT_WIND, GATE_BIT_EXT_EXP,
    GATE_BIT_INT_EXP, GATE_BIT_HEAT, GATE_BIT_COLD,
    REASON_SAFETY_PRE_GATE, REASON_SAFETY_POST_GATE,
    write_decision_log, CH_SAFETY_GATE,
)
from .types import ActuatorProfile, EnvContext, ManualLockState

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Gate 발동 결과
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GateResult:
    triggered: bool = False
    gate_mask: int = 0                              # 활성 게이트 비트마스크
    forced_commands: Dict[str, dict] = field(default_factory=dict)
    # {actuator_id: {'value': float, 'reason': int, 'ttl': float}}
    description: str = ''
    partial: bool = False
    # True 일 경우: triggered=False 라도 forced_commands 가 비어있지 않을 수 있다.
    # 호출자는 L1~L3 를 정상 실행하고 마지막 단계에서 forced_commands 를 override 로 적용해야 한다.
    # 예: 풍향 차등 폐쇄 — windward openings 만 강제 폐쇄, leeward 는 정상 운용.


# ─────────────────────────────────────────────────────────────────────────────
# Pre-Gate 설정
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PreGateConfig:
    """사용자 설정 가능한 Pre-Gate 임계값."""
    rain_threshold:       float = 0.5    # rain_sensor 임계 (mm/hr 또는 boolean 1)
    wind_threshold:       float = 12.0   # m/s
    ext_context_max_age:  float = 300.0  # 외부 컨텍스트 만료 (초)
    int_sensor_max_age:   float = 120.0  # 내부 센서 만료 (초)
    heat_ext_threshold:   float = 38.0   # 폭염: 외부 온도 임계 (°C)
    heat_int_threshold:   float = 35.0   # 폭염: 내부 온도 임계 (°C)
    cold_ext_threshold:   float = -2.0   # 한파: 외부 온도 임계 (°C)
    cold_int_threshold:   float = 5.0    # 한파: 내부 온도 임계 (°C)
    gate_ttl:             float = 300.0  # 게이트 발동 후 최소 유지 시간 (초)
    windward_arc_deg:     float = 60.0   # 풍향 ±이 각도 이내 = windward (강제 폐쇄 대상)


# ─────────────────────────────────────────────────────────────────────────────
# Pre-Gate
# ─────────────────────────────────────────────────────────────────────────────

class SafetyPreGate:
    """L1~L3 진입 전 안전 검사.

    evaluate() 를 매 사이클 호출.
    GateResult.triggered == True 이면 forced_commands 를 그대로 L4 에 전달하고
    L1~L3 를 건너뛴다.

    게이트 해제 후 호출자는 L3 적분 상태를 reset 해야 한다 (bumpless 복귀).
    """

    def __init__(self, config: PreGateConfig = None):
        self.config = config or PreGateConfig()
        self._last_triggered = False
        self._triggered_until: float = 0.0  # gate_ttl 보장용

    def evaluate(
        self,
        env: EnvContext,
        profiles: List[ActuatorProfile],
        unique_id: str = '',
    ) -> GateResult:
        """안전 조건을 평가하고 GateResult 를 반환."""
        cfg = self.config
        now = time.time()
        mask = 0
        reasons: List[str] = []

        ext = env.get('external', {})
        now_ts = env.get('now_ts', now)

        # ── 강우 ──────────────────────────────────────────────────────────────
        if ext.get('rain', 0.0) >= cfg.rain_threshold:
            mask |= GATE_BIT_RAIN
            reasons.append('rain')

        # ── 강풍 ──────────────────────────────────────────────────────────────
        if ext.get('wind', 0.0) >= cfg.wind_threshold:
            mask |= GATE_BIT_WIND
            reasons.append('wind')

        # ── 외부 컨텍스트 만료 ─────────────────────────────────────────────────
        last_ext_ts = env.get('last_ext_ts', now_ts)
        if (now_ts - last_ext_ts) > cfg.ext_context_max_age:
            mask |= GATE_BIT_EXT_EXP
            reasons.append('ext_context_expired')

        # ── 내부 센서 만료 ─────────────────────────────────────────────────────
        last_int_ts = env.get('last_int_ts', now_ts)
        if (now_ts - last_int_ts) > cfg.int_sensor_max_age:
            mask |= GATE_BIT_INT_EXP
            reasons.append('int_sensor_expired')

        # ── 폭염 / 한파 ────────────────────────────────────────────────────────
        # 등가 환경 전제 + 공간 outlier 제거 후의 극값으로 판정.
        # T_max/T_min 이 없으면 (단일 센서) T 로 폴백.
        int_state = env.get('internal', {})
        T_int_hot  = int_state.get('T_max', int_state.get('T', 999))
        T_int_cold = int_state.get('T_min', int_state.get('T', -999))

        if (ext.get('T', 999) >= cfg.heat_ext_threshold and
                T_int_hot >= cfg.heat_int_threshold):
            mask |= GATE_BIT_HEAT
            reasons.append('heat_emergency')

        if (ext.get('T', -999) <= cfg.cold_ext_threshold and
                T_int_cold <= cfg.cold_int_threshold):
            mask |= GATE_BIT_COLD
            reasons.append('cold_emergency')

        # ── EXT_EXP 단독 발동 → partial gate (개구부만 강제 폐쇄, 내부 제어 지속) ──
        # 다른 게이트(강우·강풍·폭염·한파·내부 만료)가 함께 발동된 경우는 일반 경로.
        ext_exp_only = (mask == GATE_BIT_EXT_EXP)

        triggered = bool(mask) or (now < self._triggered_until)
        if triggered and mask:
            self._triggered_until = now + cfg.gate_ttl

        if not triggered:
            if self._last_triggered:
                logger.info('SafetyPreGate released')
            self._last_triggered = False
            return GateResult(triggered=False)

        if not self._last_triggered:
            logger.warning('SafetyPreGate triggered: %s', ', '.join(reasons))
        self._last_triggered = True

        # ── 풍향 차등 가능 여부 판정 ────────────────────────────────────────────
        # 조건: 강풍 단독 발동 + wind_dir 존재 + 모든 opening profile 에 azimuth_deg 존재.
        #       다른 게이트(강우·폭염·한파·만료) 동시 발동 시는 보수적 일괄 폐쇄.
        wind_only = (mask == GATE_BIT_WIND)
        wind_dir = ext.get('wind_dir')
        opening_profiles = [p for p in profiles if p.kind == 'opening']
        all_have_azimuth = (opening_profiles and
                            all(p.azimuth_deg is not None for p in opening_profiles))
        per_opening_mode = (wind_only and wind_dir is not None and all_have_azimuth)

        # EXT_EXP 단독: partial=True, triggered=False → L1-L3 계속, 개구부만 강제 폐쇄
        is_partial = per_opening_mode or ext_exp_only

        forced = self._build_forced_commands(mask, profiles, ext, per_opening_mode)

        if unique_id:
            write_decision_log(unique_id, 'safety_gate_active', CH_SAFETY_GATE, float(mask))

        return GateResult(
            triggered=(not is_partial),   # partial 모드는 triggered=False
            gate_mask=mask,
            forced_commands=forced,
            description=', '.join(reasons),
            partial=is_partial,
        )

    def reset_after_release(self):
        """게이트 해제 후 호출 — 적분 상태 리셋 신호."""
        self._last_triggered = False
        self._triggered_until = 0.0

    def _build_forced_commands(
        self, mask: int, profiles: List[ActuatorProfile],
        ext: dict = None, per_opening_mode: bool = False,
    ) -> Dict[str, dict]:
        """비트마스크에 따라 액추에이터별 강제 명령 생성.

        per_opening_mode=True 일 때 강풍 단독 발동: opening 별 azimuth 와
        ext['wind_dir'] 비교해 windward (±windward_arc_deg) 만 폐쇄.

        safe_default 의 'kind별 의미':
          opening/shade: 0 = 닫힘/걷힘 (강풍·강우 시 안전)
          curtain:       0 = 걷힘     (독립 판단 필요)
          cooler/heater: 0 = OFF
        """
        cfg = self.config
        ext = ext or {}
        wind_dir = ext.get('wind_dir')

        cmds = {}
        for p in profiles:
            value: Optional[float] = None

            if mask & (GATE_BIT_RAIN | GATE_BIT_WIND):
                # 강풍·강우는 외부 개구부(측창/천창)만 위협한다. 차광막·보온커튼은
                # 내부 시설이라 비바람에 노출되지 않으므로 강제하지 않는다(미명령 →
                # 직전 위치 유지). 외부 개구부만 폐쇄한다.
                if p.kind == 'opening':
                    if (per_opening_mode
                            and not (mask & GATE_BIT_RAIN)
                            and p.azimuth_deg is not None
                            and wind_dir is not None):
                        # 풍향 차등: windward 만 폐쇄, leeward 는 명령 없음
                        angle_diff = abs(((wind_dir - p.azimuth_deg + 180) % 360) - 180)
                        if angle_diff < cfg.windward_arc_deg:
                            value = 0.0
                        # else leeward → value 미설정 (조율자 정상 운용)
                    else:
                        value = 0.0                      # 일괄 폐쇄

            if mask & GATE_BIT_HEAT:
                # 규약: 100=완전 열림, 0=완전 닫힘
                if p.kind == 'opening':
                    value = 100.0                        # 최대 개방 (환기 냉각)
                elif p.kind == 'shade':
                    value = 0.0                          # 최대 차광 = 차광막 닫음
                elif p.kind == 'cooler':
                    value = 100.0

            if mask & GATE_BIT_COLD:
                if p.kind == 'opening':
                    value = 0.0                          # 완전 폐쇄
                elif p.kind == 'curtain':
                    value = 0.0                          # 보온 = 커튼 닫음(단열)
                elif p.kind == 'heater':
                    value = 100.0

            if mask & GATE_BIT_INT_EXP:
                # 내부 센서 만료: 모두 안전 기본값 (제어 불가)
                value = p.safe_default

            if (mask & GATE_BIT_EXT_EXP) and not (mask & GATE_BIT_INT_EXP):
                # 외부 센서 단독 만료: 개구부·차광막만 보수적 폐쇄.
                # 내부 전용 액추에이터(heater/cooler/fogger/co2_injector/curtain)는
                # L1-L3 제어 지속 → forced 명령 생성 안 함.
                if p.kind in ('opening', 'shade'):
                    value = 0.0

            if value is not None:
                cmds[p.actuator_id] = {
                    'value': value,
                    'reason': REASON_SAFETY_PRE_GATE,
                    'ttl': 300.0,
                }

        return cmds


# ─────────────────────────────────────────────────────────────────────────────
# Post-Gate
# ─────────────────────────────────────────────────────────────────────────────

class SafetyPostGate:
    """L3 결과를 L4 전달 전 정합성 검사·보정.

    check() 는 L3 commands dict 를 받아 보정된 commands dict 를 반환한다.
    """

    def check(
        self,
        commands: Dict[str, dict],
        profiles: List[ActuatorProfile],
        unique_id: str = '',
    ) -> Tuple[Dict[str, dict], bool]:
        """
        Returns:
            (보정된 commands, 보정 발생 여부)
        """
        result = dict(commands)
        corrected = False
        profile_map = {p.actuator_id: p for p in profiles}

        for aid, cmd in list(result.items()):
            p = profile_map.get(aid)
            if p is None:
                continue

            value = cmd.get('value', 0.0)

            # ── NaN / Inf 방어 ──────────────────────────────────────────────
            import math
            if not math.isfinite(value):
                result[aid] = {'value': p.safe_default, 'reason': REASON_SAFETY_POST_GATE}
                corrected = True
                logger.warning('PostGate: NaN/Inf on %s → safe_default', aid)
                continue

            # ── 하드 한계 [0, 100] ──────────────────────────────────────────
            clamped = max(0.0, min(100.0, value))
            if clamped != value:
                result[aid]['value'] = clamped
                result[aid]['reason'] = REASON_SAFETY_POST_GATE
                corrected = True

            # ── 수동 락 ─────────────────────────────────────────────────────
            if p.manual_lock.is_active():
                result[aid] = {
                    'value': p.manual_lock.manual_value,
                    'reason': 20,   # REASON_MANUAL_OVERRIDE
                }
                corrected = True

        # ── 모순 검출: 냉방 + 난방 동시 ON ─────────────────────────────────
        cooler_ids = [p.actuator_id for p in profiles if p.kind == 'cooler']
        heater_ids = [p.actuator_id for p in profiles if p.kind == 'heater']

        cooler_on = any(result.get(aid, {}).get('value', 0) > 5 for aid in cooler_ids)
        heater_on = any(result.get(aid, {}).get('value', 0) > 5 for aid in heater_ids)

        if cooler_on and heater_on:
            # 비용이 낮은 쪽 우지, 다른 쪽 0
            cooler_cost = min(
                profile_map[a].cost_fn({}, 50) for a in cooler_ids if a in profile_map
            )
            heater_cost = min(
                profile_map[a].cost_fn({}, 50) for a in heater_ids if a in profile_map
            )
            if cooler_cost <= heater_cost:
                for aid in heater_ids:
                    result[aid] = {'value': 0.0, 'reason': REASON_SAFETY_POST_GATE}
            else:
                for aid in cooler_ids:
                    result[aid] = {'value': 0.0, 'reason': REASON_SAFETY_POST_GATE}
            corrected = True
            logger.warning('PostGate: cooler+heater conflict resolved')

        if corrected and unique_id:
            write_decision_log(unique_id, 'safety_gate_active', CH_SAFETY_GATE, -1.0)

        return result, corrected
