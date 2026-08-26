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
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .log_channels import (
    GATE_BIT_RAIN, GATE_BIT_WIND, GATE_BIT_EXT_EXP,
    GATE_BIT_INT_EXP, GATE_BIT_HEAT, GATE_BIT_COLD,
    GATE_BIT_FOG_SUNBURN,
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
    # ── 육묘 일소 방지 (2026-07-31 aot-005) ───────────────────────────────
    nursery_mode:         bool  = False  # 육묘장 모드 — 습윤형 분무 일사 잠금
    nursery_solar_lockout: float = 250.0  # 실내 추정 광량 이 값 이상이면 분무 금지 (W/m²)
    nursery_solar_release: float = 150.0  # 이 값 미만으로 내려가야 잠금 해제 (히스테리시스)
    nursery_evening_fog:  bool  = True   # 일몰 전 분무 허용 여부 (끄면 야간 습윤 차단)


def is_wetting_fogger(profile: ActuatorProfile) -> bool:
    """이 액추에이터가 잎을 적시는 분무기인가.

    시설 도면의 노즐 배치에서 산출된 capacity_meta['nozzle']['wetting'] 을
    따른다. 노즐 정보가 없으면 (수동 등록 등) 보수적으로 습윤형으로 본다 —
    육묘장 모드를 켠 사용자의 의도는 "확실치 않으면 뿌리지 말 것"이다.
    """
    if getattr(profile, 'kind', None) != 'fogger':
        return False
    cap = getattr(profile, 'capacity_meta', None) or {}
    nozzle = cap.get('nozzle')
    if not nozzle:
        return True
    return bool(nozzle.get('wetting'))


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
        self._nursery_locked = False        # 육묘 일소 잠금 래치 (히스테리시스)

    def _eval_nursery_lock(self, env: EnvContext) -> bool:
        """육묘 일소 잠금 상태를 갱신하고 반환한다.

        판정 광량은 실내 추정 광량(internal['light_est'])을 우선한다 — 차광막을
        닫아 이미 그늘이 진 상태까지 잠글 이유가 없기 때문이다. 추정값이 없으면
        실외 일사(양수인 것만), 그것도 없으면 태양고도 어림값 순으로 폴백한다.

        lockout 에서 걸리고 release 아래로 내려가야 풀리는 래치라, 구름이
        지나갈 때마다 분무가 켜졌다 꺼졌다 하지 않는다.

        저녁 차단(internal['evening_block'])은 광량과 무관하게 우선한다 —
        해가 진 뒤에는 광량이 낮아 일소 게이트가 풀리지만, 밤새 잎이 젖어
        있으면 병해(잿빛곰팡이·노균병) 위험이 커진다. 육묘장은 밀식이라
        확산이 빠르다.
        """
        cfg = self.config
        # **육묘 모드를 전제하지 않는다.** 강일사에 젖은 잎이 타는 것은 어린
        # 모종만의 일이 아니다 — 물방울이 렌즈가 되어 빛을 모으는 것은 작물과
        # 무관한 물리다. 예전에는 이 잠금이 통째로 `nursery_mode` 안에 있어서,
        # 딸기 온실이 육묘 모드를 끄는 순간 두상 살수의 일소 보호가 함께
        # 사라졌다(2026-08-25 イチゴ에서 실제로 그렇게 됐다).
        #
        # 육묘 모드는 **이 게이트를 켜는 스위치가 아니라 더 조이는 축**이다:
        # 지하수 원수일 때 임계를 낮추고(150/100), 1회 분무를 짧게 끊고
        # (20초/10분), 저녁 차단을 추가한다.
        #
        # 대상은 어디까지나 **습윤형 분무기**다(호출부의 `is_wetting_fogger`).
        # 드립과 고압 미세포그는 여기 걸리지 않는다.

        if env.get('internal', {}).get('evening_block'):
            # 래치는 건드리지 않는다 — 저녁 차단은 시간 기반이라 자체 해제된다.
            return True

        light = env.get('internal', {}).get('light_est')
        if light is None:
            # 실외 일사는 **양수일 때만** 측정값으로 인정한다. 일사 센서를 지정하지
            # 않은 ext_context_collector 는 solar 를 0.0 으로 채워 공유하므로,
            # 0.0 을 측정값으로 받아들이면 "센서 없음"이 "한밤중"으로 둔갑해
            # 아래 어림값 폴백에 영원히 도달하지 못한다(일사 센서 없는 육묘장의
            # 하드 잠금이 통째로 죽는다).
            # 진짜 야간 0.0 을 흘려보내도 결과는 같다 — 어림값도 해가 지면 0.0 이라
            # 어느 쪽이든 잠기지 않는다. 대낮에 0.0 이 나오는 경우는 센서 고장이며,
            # 그때 어림값으로 잠그는 것은 일소 보호에서 안전한 방향이다.
            solar = env.get('external', {}).get('solar')
            if solar is not None and solar > 0.0:
                light = solar
        if light is None:
            # 측정값이 하나도 없으면 태양고도로 어림한 맑은날 일사로 판정한다.
            # 이 폴백이 없으면 일사 센서가 없는 시설은 일소 보호가 통째로 꺼진 채
            # 돌아간다(정오에 분무가 그대로 나간다). 어림값은 밤에 0 이므로
            # "야간에 계속 잠기는" 예전 우려도 생기지 않는다.
            light = env.get('internal', {}).get('_nursery_light_fallback')
        if light is None:
            # 좌표조차 없어 어림도 못 하면 잠그지 않는다 — 야간에도 계속 잠기면
            # 정상 가습까지 막혀 오히려 작물이 상한다.
            self._nursery_locked = False
            return False

        if self._nursery_locked:
            if light < cfg.nursery_solar_release:
                self._nursery_locked = False
        elif light >= cfg.nursery_solar_lockout:
            self._nursery_locked = True
        return self._nursery_locked

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

        # ── 육묘 일소: 고일사 중 습윤형 분무 잠금 ──────────────────────────────
        # 다른 게이트와 성격이 다르다 — 시설 전체를 비상 운전으로 돌리는 게
        # 아니라 분무기 하나만 끄는 국소 잠금이다. 따라서 gate_ttl 을 잡지 않고
        # (다른 제어를 얼려버리면 안 된다) 자체 히스테리시스 래치만 쓴다.
        nursery_lock = self._eval_nursery_lock(env)
        if nursery_lock and any(is_wetting_fogger(p) for p in profiles):
            mask |= GATE_BIT_FOG_SUNBURN
            reasons.append('nursery_fog_sunburn')

        # 아래 판정들은 "시설 비상 게이트"만 대상으로 한다. 육묘 분무 잠금이
        # 함께 켜졌다고 해서 풍향 차등 폐쇄 같은 기존 동작이 바뀌면 안 된다.
        mask_core = mask & ~GATE_BIT_FOG_SUNBURN

        # ── EXT_EXP 단독 발동 → partial gate (개구부만 강제 폐쇄, 내부 제어 지속) ──
        # 다른 게이트(강우·강풍·폭염·한파·내부 만료)가 함께 발동된 경우는 일반 경로.
        ext_exp_only = (mask_core == GATE_BIT_EXT_EXP)

        triggered = bool(mask) or (now < self._triggered_until)
        if triggered and mask_core:
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
        wind_only = (mask_core == GATE_BIT_WIND)
        wind_dir = ext.get('wind_dir')
        opening_profiles = [p for p in profiles if p.kind == 'opening']
        all_have_azimuth = (opening_profiles and
                            all(p.azimuth_deg is not None for p in opening_profiles))
        per_opening_mode = (wind_only and wind_dir is not None and all_have_azimuth)

        # EXT_EXP 단독: partial=True, triggered=False → L1-L3 계속, 개구부만 강제 폐쇄
        # 육묘 분무 잠금 단독(mask_core == 0)도 마찬가지 — 분무기만 끄고 나머지
        # 제어는 그대로 돈다. mask == 0 인 TTL 유지 구간은 기존대로 전체 홀드.
        is_partial = per_opening_mode or ext_exp_only
        if mask and mask_core == 0:
            is_partial = True

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

            # 육묘 일소 잠금은 마지막에 적용해 다른 게이트를 이긴다.
            # 특히 폭염 게이트와 겹치는 경우가 중요하다 — 한여름 정오는
            # 폭염 발동 조건이자 일소 위험이 최대인 시각이라, 여기서
            # 덮어쓰지 않으면 비상 냉방 중에 분무가 그대로 살아난다.
            if (mask & GATE_BIT_FOG_SUNBURN) and is_wetting_fogger(p):
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

        # ── 모순 검출(냉방+난방 동시 ON)은 **여기가 아니다** ──────────────
        # 2026-08-26 에 `_cycle_mixin.apply_hvac_opposition_interlock` 으로
        # 옮겼다. 이 Post-Gate 는 임계 오버라이드보다 **앞**에서 도는데, 충돌은
        # 그 뒤 `_force_cool` 이 냉방을 100 으로 올리면서 새로 생긴다 — 여기서
        # 검사하면 아직 없는 것을 검사하고 통과시킨다(실측: 검사 통과 후
        # 난방 100% + 냉방 100% 가 그대로 나갔다).
        #
        # ⚠ **되살리지 말 것.** 같은 규칙을 두 곳에 두면 갈라지고, 갈라지면
        #   늦게 도는 쪽이 실질 규칙이 된다.

        if corrected and unique_id:
            write_decision_log(unique_id, 'safety_gate_active', CH_SAFETY_GATE, -1.0)

        return result, corrected
