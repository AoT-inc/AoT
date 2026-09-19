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
    vent_open_ceiling: bool = False
    # True: 강우·풍속을 **잃었다**(전에 받던 값이 끊겼다). 개구부는 제자리 또는
    # 닫기만 하고 **더 열지 않는다.** 강제 명령이 아니라 코디네이터에게 주는
    # 제약이다 — 호출자는 `situation.context['vent_open_ceiling']` 로 넘겨
    # coordinate() 안에서 걸어야 한다. 밖에서 명령을 자르면 적분이 그 사실을
    # 모른 채 감겨, 풀리는 순간 창이 튄다(`coordinator` 2.6 주석 참조).


# ─────────────────────────────────────────────────────────────────────────────
# Pre-Gate 설정
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PreGateConfig:
    """사용자 설정 가능한 Pre-Gate 임계값."""
    rain_threshold:       float = 0.5    # rain_sensor 임계 (mm/hr 또는 boolean 1)
    wind_threshold:       float = 12.0   # m/s
    # 실외 온습도의 **승계 유예**(초) — 이 시간 동안은 마지막 실측을 그대로 쓰고,
    # 넘으면 `build_fallback_context` 로 넘긴다(`_cycle_mixin` P2-2).
    # ⚠ **게이트는 이 값으로 나이를 재지 않는다**(2026-09-19). 값이 쓸 만한가는
    #   `measurement_freshness.effective_max_age`(장치값 > 요청 > 주기 파생)가
    #   장치마다 이미 정했고, 게이트는 그 결과(값이 왔는가)만 본다. 여기서 한
    #   번 더 재면 판정이 두 벌이 되고 느슨한 쪽이 실질이 된다.
    ext_context_max_age:  float = 300.0
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
    ⚠ 2026-09-19 현재 `reset_after_release()` 를 부르는 곳이 없다 — 전체 게이트
      해제 뒤 적분은 게이트 전 값 그대로 복귀한다. 알려진 미결 사항이다.
    """

    def __init__(self, config: PreGateConfig = None):
        self.config = config or PreGateConfig()
        self._last_triggered = False
        self._triggered_until: float = 0.0  # gate_ttl 보장용
        self._nursery_locked = False        # 육묘 일소 잠금 래치 (히스테리시스)
        # 잠금 사유 — 'sunburn'(광량 임계) | 'evening'(저녁 잎마름병 방지) | None.
        # ⚠ **`_nursery_locked` bool 하나로는 화면에 거짓말을 하게 된다.**
        #   저녁 차단은 광량과 **무관하게** 잠그는데, 이 값이 없으면 호출자가
        #   무조건 "햇빛에 잎이 델 수 있어" 라고 말한다 — 비 오는 밤에도 그
        #   문장이 나갔다(2026-08-28 사용자 지적: 강우 중 "일소" 안내는 모순).
        self._nursery_lock_reason: str | None = None
        # 강우·풍속의 **마지막 실측** — {'rain': 값, 'wind': 값, 'wind_dir': 값}.
        # 값이 끊겼을 때 "모른다" 와 "원래 없던 센서" 를 가르는 근거이자,
        # 끊기기 직전이 위험했는지를 기억하는 래치다(`_weather_view` 참조).
        # 프로세스 메모리에만 있다 — 재시작 뒤에는 "원래 없던 센서" 로 출발한다.
        self._weather_seen: Dict[str, float] = {}
        self._weather_lost_logged: set = set()

    def _weather_view(self, ext: dict) -> Tuple[dict, List[str]]:
        """강우·풍속을 **안전한 방향으로만** 쓰는 판정용 값과 잃은 항목.

        `docs/design/sensor-freshness-and-control-cadence.md` 규칙 A 다:

            오래된 "비 옴"·"바람 셈"   → 닫는 근거로 **쓴다** (래치)
            오래된 "비 안 옴"·"바람 없음" → 여는 근거로 **안 쓴다** (더 열지 않음)

        값 셋 중 하나다:
          - 이번에 왔다(None 이 아님)   → 그대로 쓰고 기억한다.
          - 안 왔는데 전에 봤다(잃음)   → 마지막 값을 쓴다. 위험했으면 그 게이트가
            계속 서고, 평온했으면 호출자가 "더 열지 않음" 을 건다.
          - 한 번도 못 봤다             → 그 센서가 없는 설치다. 예전과 같이
            제약하지 않는다(강우계 없는 시설은 원래 강우를 모른 채 돈다).

        "왔는가" 는 여기서 재지 않는다 — 상류(`read_outdoor_sensors`·수집기)가
        `measurement_freshness` 로 이미 가려 None 을 준다.
        """
        view = dict(ext)
        lost: List[str] = []
        for key in ('rain', 'wind'):
            v = ext.get(key)
            if v is not None:
                self._weather_seen[key] = float(v)
                if key == 'wind' and ext.get('wind_dir') is not None:
                    self._weather_seen['wind_dir'] = float(ext['wind_dir'])
                if key in self._weather_lost_logged:
                    logger.error('실외 %s 값이 돌아왔습니다', key)
                    self._weather_lost_logged.discard(key)
                continue
            if key in self._weather_seen:
                lost.append(key)
                view[key] = self._weather_seen[key]
                if key == 'wind' and view.get('wind_dir') is None:
                    view['wind_dir'] = self._weather_seen.get('wind_dir')
                if key not in self._weather_lost_logged:
                    # `error` — 컨트롤러 로거 기본 레벨이 ERROR 라 warning 은
                    # 아무 데도 안 남는다(`_cycle_mixin._clamp_key` 주석).
                    logger.error(
                        '실외 %s 값이 끊겼습니다 — 마지막 값 %.2f 기준으로 '
                        '개구부를 더 열지 않습니다(위험 값이면 닫힌 채 유지)',
                        key, self._weather_seen[key])
                    self._weather_lost_logged.add(key)
            else:
                view[key] = 0.0         # 원래 없는 센서 — 예전 기본값과 같다
        return view, lost

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
        # **육묘 모드에서만 잠근다** (2026-08-30 되돌림).
        #
        # 2026-08-25 `c6d0ec0b` 이 이 잠금을 육묘 밖으로 꺼내 습윤형 분무기가
        # 있으면 늘 걸리게 했다. 근거는 "물방울이 렌즈가 되는 것은 어린 모종만의
        # 일이 아니다" 였고 물리로는 맞지만, **과한 적용이었다.**
        #
        # 잎을 마른 상태로 관리하는 육묘에서는 옳다. 그러나 이미 자란 개체를
        # 키우는 쪽에서는 강일사야말로 증산이 가장 심한 때이고, 그때 분무를
        # 끊으면 일소를 막으려다 건조 스트레스를 만든다 — 보호가 아니라
        # 역효과다. 실측(2026-08-30 영양): 저녁 차단과 이어 붙어 하루 중
        # 분무 허용 창이 한 시간 남짓으로 좁혀졌고, 가습이 필요한 31 사이클
        # **전부**에서 코디네이터의 요청이 버려졌다.
        #
        # 화면도 원래 이쪽이었다 — 임계 두 필드는 `depends_on: nursery_mode`
        # 라 육묘 모드를 꺼면 보이지도 않는데 로직만 전원에게 적용됐다.
        # 즉 화면은 "육묘 전용"이라 말하고 동작은 아니었다.
        #
        # ⚠ 되돌리면 `c6d0ec0b` 이 막으려던 경우(육묘 모드를 끈 채 두상 살수를
        # 쓰는 딸기 온실)가 다시 열린다. 그 설치는 육묘 모드를 켜서 보호를
        # 받는다 — 보호의 유무를 사람이 정하게 두는 것이 이 되돌림의 요지다.
        #
        # 대상은 어디까지나 **습윤형 분무기**다(호출부의 `is_wetting_fogger`).
        # 드립과 고압 미세포그는 여기 걸리지 않는다.
        if env.get('internal', {}).get('evening_block'):
            # 래치는 건드리지 않는다 — 저녁 차단은 시간 기반이라 자체 해제된다.
            self._nursery_lock_reason = 'evening'
            return True

        if not cfg.nursery_mode:
            self._nursery_locked = False
            self._nursery_lock_reason = None
            return False

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
        if self._nursery_locked:
            self._nursery_lock_reason = 'sunburn'
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

        now_ts = env.get('now_ts', now)
        # 강우·풍속은 규칙 A 로 본 값이다 — 잃었으면 마지막 실측(`_weather_view`).
        ext, weather_lost = self._weather_view(env.get('external', {}))

        # ── 강우 ──────────────────────────────────────────────────────────────
        if ext['rain'] >= cfg.rain_threshold:
            mask |= GATE_BIT_RAIN
            reasons.append('rain')

        # ── 강풍 ──────────────────────────────────────────────────────────────
        if ext['wind'] >= cfg.wind_threshold:
            mask |= GATE_BIT_WIND
            reasons.append('wind')

        # ── 강우·풍속을 잃음 (2026-09-19 재정의) ───────────────────────────────
        # 예전에는 `last_ext_ts` 가 `ext_context_max_age`(300초)를 넘으면 개구부와
        # 차광막을 **0 으로 강제**했다. 그것은 두 가지로 틀렸다:
        #   - 실외를 모를 때 개구부를 제자리에 두는 코디네이터(2.6, 2026-08-22)와
        #     정반대였고, 뒤에서 덮어써 늘 이겼다 — 한여름 기상대 두절 = 창 폐쇄.
        #   - 차광막은 강우·강풍에서도 강제하지 않는 내부 시설인데, 두절이 실제
        #     비바람보다 더 세게 개입했다(0 = 전면 차광).
        # 지금은 규칙 A 다: 위험했던 마지막 값은 위 두 게이트가 이어서 닫고,
        # 평온했던 값은 "더 열지 않음"(vent_open_ceiling)만 건다.
        if weather_lost:
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
            # ⚠ **비트 이름(`_SUNBURN`)과 화면 문구를 혼동하지 말 것.** 비트는
            #   "습윤형 분무가 잠겨 있다" 는 사실 하나를 담지만, 잠근 이유는
            #   둘이다 — 광량 임계(진짜 일소)와 저녁 시간대(잎마름병 방지)는
            #   서로 무관하고 동시에 참일 이유가 없다(맑은 대낮 vs 비 오는
            #   밤). 사유 문자열은 실제로 잠근 근거를 따라간다.
            reasons.append('nursery_fog_evening'
                           if self._nursery_lock_reason == 'evening'
                           else 'nursery_fog_sunburn')

        # 아래 판정들은 "시설 비상 게이트"만 대상으로 한다. 육묘 분무 잠금이
        # 함께 켜졌다고 해서 풍향 차등 폐쇄 같은 기존 동작이 바뀌면 안 된다.
        mask_core = mask & ~GATE_BIT_FOG_SUNBURN

        # ── EXT_EXP 단독 발동 → partial gate (강제 명령 없음, 개구부 "더 열지 않음") ──
        # 다른 게이트(강우·강풍·폭염·한파·내부 만료)가 함께 발동된 경우는 일반 경로.
        ext_exp_only = (mask_core == GATE_BIT_EXT_EXP)

        triggered = bool(mask) or (now < self._triggered_until)
        # EXT_EXP 는 TTL 을 잡지 않는다 — 제약(더 열지 않음)이지 비상이 아니다.
        # 잡으면 값이 돌아온 뒤 300초 동안 L1~L3 가 통째로 멈춘다(TTL 구간은
        # 강제 명령 없는 전체 홀드다).
        if triggered and (mask_core & ~GATE_BIT_EXT_EXP):
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
        # 풍속을 잃었으면 풍향 차등을 하지 않는다 — 마지막 풍향이 지금도 맞다는
        # 근거가 없으므로 전부 닫는다(규칙 A: 오래된 값은 닫는 쪽으로만).
        per_opening_mode = (wind_only and wind_dir is not None and all_have_azimuth
                            and 'wind' not in weather_lost)

        # EXT_EXP 단독: partial=True, triggered=False → L1-L3 계속, 개구부는 "더 열지 않음"
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
            vent_open_ceiling=bool(mask & GATE_BIT_EXT_EXP),
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

            # EXT_EXP(강우·풍속 잃음)는 **강제 명령을 만들지 않는다.** "더 열지
            # 않음" 은 GateResult.vent_open_ceiling 으로 코디네이터가 건다 —
            # 여기서 값을 박으면 코디네이터 적분이 모르는 제약이 된다.
            # ⚠ 예전의 "개구부·차광막 0 강제" 를 되살리지 말 것(evaluate 주석).

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
