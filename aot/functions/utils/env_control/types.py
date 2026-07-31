# coding=utf-8
"""
env_control/types.py — 통합 환경 제어 시스템 핵심 타입 정의.

참조: docs/dev/integrated_env_control_design.md §3
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# 단위 규약 R1 (§3.2)
#
# EffectResult.magnitude_native 단위 = 변수 native 단위 / 1 사이클
#   T:   °C/cycle
#   RH:  %/cycle
#   CO2: ppm/cycle
#
# accumulated, residual, tolerance 도 모두 native 단위 사용.
# 우선순위 정렬 시에만 정규화 (|deviation| / tolerance × priority).
# 정규화 값은 비교용 일시값이며 accumulated 에 들어가지 않는다.
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# 기본 자료형
# ─────────────────────────────────────────────────────────────────────────────

EnvContext = Dict  # 아래 키 집합을 포함하는 dict:
# 내부 상태
#   T_int, RH_int, CO2_int, VPD_int
# 외부 상태
#   T_ext, RH_ext, CO2_ext, wind, rain, solar, dewpoint
# 메타
#   now_ts (epoch float), cycle_sec (float)


@dataclass
class EffectResult:
    """EffectFn 반환값. 단위 규약 R1 준수."""
    direction: str          # '↑' | '↓' | '0'
    magnitude_native: float  # native 단위 / 사이클 (R1)


# EffectFn: (env_context, cmd_pct, profile=None) -> EffectResult
# profile 인자는 G3 도입. 모든 구현체는 profile=None 기본값을 가져 후방 호환됨.
EffectFn = Callable[..., EffectResult]

# CostFn: (env_context, cmd_pct) -> float  (낮을수록 우선)
CostFn = Callable[[EnvContext, float], float]


# ─────────────────────────────────────────────────────────────────────────────
# 수동 락 상태 (§3.6)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ManualLockState:
    locked: bool = False
    until_ts: float = 0.0         # 락 해제 epoch (0 = 영구 락 없음)
    manual_value: float = 0.0     # 사용자가 설정한 값
    reason: str = ''              # 'user_ui' | 'maintenance' | 'pre_gate'

    def is_active(self) -> bool:
        """현재 시각 기준으로 락이 유효한지 확인."""
        if not self.locked:
            return False
        if self.until_ts > 0 and time.time() > self.until_ts:
            self.locked = False
            return False
        return True


MANUAL_LOCK_DEFAULT = ManualLockState()


# ─────────────────────────────────────────────────────────────────────────────
# 명령 제약 조건 (§3.1, §4.1)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CmdConstraints:
    slew_per_cycle: float = 20.0    # 사이클당 최대 명령 변화 (%)
    min_on_pct: float = 5.0         # 미만이면 0으로 스냅
    min_dwell_sec: float = 30.0     # 명령 유지 최소 시간
    full_stroke_sec: float = 0.0    # 0→100% 이동 소요 시간 (s). 0 = 설정 안 함 (slew_per_cycle 그대로 사용)
    effective_start_pct: float = 0.0    # 실제 작동 효과가 시작되는 위치 (%). 이하 명령은 이 값으로 클램프
    effective_end_pct: float = 100.0    # 실제 작동 효과가 끝나는 위치 (%). 이상 명령은 이 값으로 클램프
    move_step_pct: float = 5.0      # 모터 최소 작동 조건 / 양자화 격자 (%). 직전 송신값과 이 값
                                    # 이상 벌어져야 이동(히스테리시스), 명령은 이 격자에 스냅.
                                    # 0 = 비활성 → 미세한 진동도 그대로 모터에 전달(기존 동작).
    # ── 관수식 펄스 도징 (분무 액추에이터) ──────────────────────────────────
    # 분무기를 개도(%)로 연속 변조하면 사이클의 절반을 계속 뿌리는 것과 같아
    # 잎이 마를 틈이 없다. max_on_sec 로 1회 분무를 짧게 끊고 min_off_sec 로
    # 건조 시간을 강제하면, 가습량은 "펄스 폭"이 아니라 "펄스 빈도"로 조절된다
    # — 관수 제어가 회당 정량 + 간격으로 물을 주는 방식과 같다.
    # 둘 다 0 = 비활성 (기존 연속 변조 동작).
    max_on_sec: float = 0.0         # 1회 가동 최대 지속 (s)
    min_off_sec: float = 0.0        # 가동 종료 후 강제 건조 시간 (s)

    @property
    def pulse_dosing(self) -> bool:
        """관수식 펄스 도징 활성 여부."""
        return self.max_on_sec > 0.0 and self.min_off_sec > 0.0

    def effective_slew(self, cycle_sec: float) -> float:
        """실제 적용할 slew_per_cycle 값.

        full_stroke_sec 가 설정된 경우 액추에이터 물리 속도로 상한을 클램프한다.
        이를 통해 한 사이클에 도달 불가능한 명령(과속)을 방지하고 방향 반전 빈도를 줄인다.
        """
        if self.full_stroke_sec > 0.0:
            physical_max = (cycle_sec / self.full_stroke_sec) * 100.0
            return min(self.slew_per_cycle, physical_max)
        return self.slew_per_cycle

    def map_aperture_to_motor(self, pct: float) -> float:
        """개구면적 명령(0–100%) → 실제 작동 범위 [open_start, open_full] 의 모터 위치(%).

        IEC(코디네이터)는 0–100% 개구면적 공간에서 제어량을 산출한다. 일반 창호
        제어에서 작동 구간 전체를 [open_start, open_full] 로 보고 선형 매핑한다:

            motor = open_start + (pct / 100) × (open_full − open_start)

        규칙:
          - 0 <= pct <= 100 → [open_start, open_full] 로 선형 매핑.
                               즉 일반 제어의 닫힘(pct=0)은 모터 open_start 이다
                               (예: 작동범위 10–100% 면 닫힘=모터 10%).
                               사용자는 UI 에서 10% 만 열려도 닫힌 상태로 인지한다.
          - start >= end (미설정/오설정) → 그대로 통과 (수동·UI 좌표 = 모터 좌표).

        비상 완전 밀폐(모터 0%)는 이 매핑을 거치지 않는다. 안전 게이트가
        forced_commands(value=0.0)를 coordinate() 우회하여 직접 디스패치하므로,
        일반 제어 경로에서는 open_start 미만으로 내려가지 않는다.
        """
        s = self.effective_start_pct
        e = self.effective_end_pct
        s = max(0.0, min(s, 100.0))
        e = max(0.0, min(e, 100.0))
        if s >= e:
            return pct                       # 미설정/오설정 → 변형 없음
        pct = max(0.0, min(100.0, pct))
        return s + (pct / 100.0) * (e - s)


# ─────────────────────────────────────────────────────────────────────────────
# ActuatorProfile (§3.1)
# ─────────────────────────────────────────────────────────────────────────────

# 지원 kind 목록
ACTUATOR_KINDS = frozenset({
    'opening',       # 개구부 (측창·천창)
    'cooler',        # 냉방기
    'heater',        # 난방기
    'fogger',        # 포그·관수 가습기
    'co2_injector',  # CO₂ 주입기
    'shade',         # 차광막 (외부)
    'curtain',       # 보온 커튼 (내부)
    'lighting',      # 보광등 (LED 등) — R2 secondary primary, optional
    'circulation_fan',  # 유동팬 (내부 공기 순환) — P3-1
    'exhaust_fan',      # 배기팬 (환기·배출) — P3-1
    'intake_fan',       # 흡기팬 (외기 도입) — P3-1
})


@dataclass
class ActuatorProfile:
    """Output 플러그인이 자기 자신을 신고하는 메타데이터."""
    actuator_id: str                          # AoT Output unique_id
    kind: str                                 # ACTUATOR_KINDS 중 하나
    capabilities: list = field(default_factory=list)
    cost_fn: CostFn = field(default_factory=lambda: (lambda env, pct: 3.0))
    response_sec: float = 60.0                # 명령 후 효과 발현까지 (초)
    safe_default: float = 0.0                 # 명령 없을 때 안전 위치
    manual_lock: ManualLockState = field(default_factory=ManualLockState)
    effect_model: Dict[str, EffectFn] = field(default_factory=dict)
    cmd_constraints: CmdConstraints = field(default_factory=CmdConstraints)
    # P6 position-form PI 기본 이득. kp=비례(e_norm→%), ki=적분(평형 개도 누적).
    # ki 는 정상상태 droop 제거용 — anti-windup(back-calc)이 포화 중 과적분을 막는다.
    gains: Dict[str, float] = field(default_factory=lambda: {'kp': 1.0, 'ki': 0.2})

    # ─── Facility / GIS metadata (optional, populated when linked to GeoFacility) ───
    geo_facility_id: Optional[str] = None     # GeoFacility.unique_id (None = unlinked)
    slot_key: Optional[str] = None            # 'outer_side_vent_motor' 등 (facility 슬롯 식별자)
    azimuth_deg: Optional[float] = None       # 외향 법선 방위각 (0=N, 90=E, 180=S, 270=W)
    area_m2: Optional[float] = None           # 개구부/장치 유효 면적
    capacity_meta: Dict[str, float] = field(default_factory=dict)  # u_eff, volume_m3 등 캐시

    # L3 가 매 사이클 채우는 필드 (Profile 원본에는 없음)
    live_effect: Dict[str, EffectResult] = field(default_factory=dict, repr=False)


# ─────────────────────────────────────────────────────────────────────────────
# 복합 액추에이터 그룹 (P2-4)
# ─────────────────────────────────────────────────────────────────────────────

GROUP_MODES = frozenset({'symmetric', 'windward_diff', 'stacked', 'multi_stage'})
"""
그룹 모드 의미:

  symmetric      — 모든 멤버가 리더 명령과 동일한 값 수신.
                   예) 좌/우 측창이 항상 같이 움직임.

  windward_diff  — 기본은 symmetric 이나 안전 게이트(G4)가 풍상측 멤버를
                   선택적으로 폐쇄한다. 리더 명령은 풍하측에만 적용.

  stacked        — 단계적 개방. 리더가 threshold_pct(%) 초과 시 팔로워 개방 시작.
                   예) 하단 측창(리더) → 상단 측창(팔로워).

  multi_stage    — 이중 커튼 등 순서 있는 개폐.
                   개방: 내부(리더) 먼저 100%, 이후 외부(팔로워) 시작.
                   폐쇄: 외부(팔로워) 먼저 0%, 이후 내부(리더) 폐쇄.
"""


@dataclass
class ActuatorGroup:
    """
    복합 액추에이터 그룹 정의.

    GeoFacility.groups JSON 에 기술되며 _reload_profiles() 에서 파싱된다.
    Coordinator 는 leader 에만 명령을 내리고, expand_group_commands() 가
    팔로워들에게 모드별 규칙으로 명령을 확장한다.
    """
    group_id: str
    mode: str                             # GROUP_MODES 중 하나
    leader_id: str                        # 조율 대상 actuator_id
    member_ids: List[str] = field(default_factory=list)   # leader 포함 전체
    threshold_pct: float = 50.0           # stacked 모드: 팔로워 개방 시작 임계값

    def follower_ids(self) -> List[str]:
        return [m for m in self.member_ids if m != self.leader_id]


# ─────────────────────────────────────────────────────────────────────────────
# 캘리브레이션 머지 규칙 R2 (§3.5)
# ─────────────────────────────────────────────────────────────────────────────

def apply_calibration(profile: dict, custom_options: dict) -> dict:
    """
    K_* 캘리브레이션 계수를 custom_options(DB)로 오버라이드한다.

    머지 규칙 R2:
      1. DB(custom_options)에 사용자가 입력한 값이 있으면 우선
      2. DB 값이 None / '' 이면 모듈 기본값 fallback
      3. 0 은 '비어있음'으로 간주 — 진짜 비활성화는 enabled 플래그 사용
    """
    result = dict(profile)
    k_keys = [k for k in profile if k.startswith('K_')]
    for key in k_keys:
        db_val = custom_options.get(key)
        if db_val is not None and db_val != '' and db_val != 0:
            result[key] = float(db_val)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# L1 출력: EnvTarget (§5.3)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TargetVar:
    value: float
    tolerance: float
    priority: float = 1.0
    unit: str = ''
    degraded: bool = False   # P5-3: NATURAL 권한으로 완화된 목표


EnvTarget = Dict[str, TargetVar]
# 키: 'temperature', 'humidity', 'co2', 'vpd', '_vpd_diag'(분해 후)


# ─────────────────────────────────────────────────────────────────────────────
# L2 출력: SituationReport (§2, §5.5)
# ─────────────────────────────────────────────────────────────────────────────

# 운전 모드 상수 (§5.7)
MODE_COOLING      = 'cooling'
MODE_HEATING      = 'heating'
MODE_HUMIDIFY     = 'humidify'
MODE_DEHUMIDIFY   = 'dehumidify'
MODE_CO2_ENRICH   = 'co2_enrich'
MODE_CONSERVATION = 'conservation'
MODE_EMERGENCY    = 'emergency'
# P5-2: Control Authority 모드 확장
MODE_DEGRADED     = 'degraded'    # 일부 변수 NATURAL — best-effort
MODE_NATURAL      = 'natural'     # 모든 능동 변수 NATURAL — 외기 추적만
MODE_UNATTAINABLE = 'unattainable'  # 목표 도달 불가 (외기 한계)


@dataclass
class SituationReport:
    context: EnvContext                      # 내부+외부+추세+now_ts+cycle_sec
    target: EnvTarget                        # L1 목표 (VPD 분해 후)
    deviation_native: Dict[str, float]       # 변수별 편차 (native 단위, R1)
    limiting_factor: Optional[str] = None   # 'light'|'co2'|'temperature'|'water'
    modes: list = field(default_factory=list)  # 복합 모드 리스트
    authority: Dict[str, str] = field(default_factory=dict)  # P5-2: 변수별 제어 권한
