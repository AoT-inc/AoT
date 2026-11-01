# coding=utf-8
"""
env_control/dispatch_adapters.py — 액추에이터 종류별 dispatch 어댑터.

coordinator 가 0~100% percent 명령을 내리면, 장치 output_types 에 따라
적절한 output_type 과 amount 로 변환해서 controller 에 전달한다.

어댑터 종류:
  ValueAdapter              — output_type='value'  (DAC, 스텝모터, 0-100% 직접 제어)
  PwmAdapter                — output_type='pwm'    (PWM 출력, 0-100% 듀티)
  TimeProportionalAdapter   — output_type='sec'    (on/off 릴레이 → 사이클 내 비례 시간)
  PairedAdapter             — output_type='value'  (actuator_paired 내부 변환 위임)
  VolumetricAdapter         — output_type='vol'    (용량형 펌프 → mL 변환)

어댑터 선택 우선순위 (select_adapter):
  1. output_name_unique == 'actuator_paired'  → PairedAdapter
  2. 'vol' 또는 'volume' in output_types_list → VolumetricAdapter
  3. 'pwm' in output_types_list              → PwmAdapter
  4. 'on_off' in output_types_list           → TimeProportionalAdapter
  5. 기본                                    → ValueAdapter (0-100% 직접)

참조: docs/dev/integrated_env_control_design.md §P0
"""
# @manual ai/env-control#actuators-adapters
from __future__ import annotations

from .log_channels import REASON_CURTAIN_GAP, REASON_CURTAIN_RAMP

# on/off 어댑터 최소 작동 임계 (%)
_MIN_ON_PCT = 5.0

# 펄스 도징 쉼의 사이클 흔들림 여유 (s) — `PulsedDoseAdapter._grace` 참조.
_PULSE_JITTER_SEC = 5.0


# ─────────────────────────────────────────────────────────────────────────────
# 데몬 반환값 검사 — **이 경로의 실패는 예외로 오지 않는다**
# ─────────────────────────────────────────────────────────────────────────────
# `control.output_on/off` 는 Pyro5 RPC 다. 그 너머에서 무슨 일이 나든 예외가
# 이쪽으로 넘어오지 않는다 — 데몬(`aot_daemon.output_on`)과 클라이언트
# (`DaemonControl.output_on`)가 **각자 `except Exception` 으로 잡아
# `(1, msg)` 로 바꾼다.** 그래서 반환값을 안 보면 실패를 알 방법이 통째로
# 없어진다.
#
# 실측(2026-09-07 영양 천창1): 릴레이 설정이 비어 명령이 한 번도 실행되지
# 않았는데, 어댑터가 반환값을 버리고 코디네이터의 `_dispatch` 는 예외만
# 보았기 때문에 130회가 전부 성공으로 집계됐다. `record_dispatch` 는 그
# 성공을 근거로 신뢰도를 **올렸고**, `actuator_mismatch` 는 48시간 내내 0
# 이었다 — 감지 장치가 정확히 반대로 작동한 것이다.
#
# 판정 규약은 `controller_output.output_on_off` 가 감사로그를 남길 때 쓰는
# 것과 **같다**(`bool(ret[0])`). 두 벌을 만들면 갈라지고, 갈라지면 감사로그와
# 제어가 서로 다른 성패를 기록하게 된다.
#
# ⚠ 튜플이 아닌 반환(None 포함)은 **성공으로 본다.** 이 경로에는 아직
#   반환값을 안 주는 자리가 남아 있어, 모르는 것을 실패로 바꾸면 정상
#   동작하던 장치가 무더기로 신뢰를 잃는다(그쪽 오탐이 훨씬 위험하다).

def _raise_if_failed(ret, actuator_id: str, what: str) -> None:
    """데몬 반환값이 실패(`(1, msg)`)면 예외로 올린다.

    코디네이터의 `_dispatch` 가 예외를 잡아 `failed` 에 넣고, 그것이
    `record_dispatch(success=False)` → 신뢰도 하락 → `actuator_mismatch`
    로그로 이어진다. 즉 **이 한 줄이 실패를 다시 보이게 하는 이음매다.**
    """
    if not isinstance(ret, (tuple, list)) or not ret:
        return
    if not ret[0]:
        return
    detail = ret[1] if len(ret) > 1 else ''
    raise RuntimeError(f'{what} 거부됨 (actuator={actuator_id}): {detail}')


# ─────────────────────────────────────────────────────────────────────────────
# 어댑터 클래스
# ─────────────────────────────────────────────────────────────────────────────

class DispatchAdapter:
    """기본 어댑터 — 0~100% → output_type='value' 직접 전달 (DAC / 스텝모터)."""

    def send(
        self,
        control,
        actuator_id: str,
        pct: float,
        ch: int,
        cycle_sec: float,
    ) -> None:
        if pct > 0.0:
            _raise_if_failed(control.output_on(
                actuator_id,
                output_type='value',
                amount=pct,
                output_channel=ch,
            ), actuator_id, 'output_on(value)')
        else:
            _raise_if_failed(
                control.output_off(actuator_id, output_channel=ch),
                actuator_id, 'output_off')

    def adopt_runtime_state(self, prev: 'DispatchAdapter') -> bool:
        """재적재 전 어댑터(`prev`)의 사이클 간 상태를 이어받는다 — 이어받았으면 True.

        기본 어댑터는 사이클 간 상태가 없다(설정값뿐이다). 상태를 가진 어댑터만
        덮어쓴다 — 지금은 `PulsedDoseAdapter`(분무 쉼) 하나다. `carry_adapter_state` 참조.
        """
        return False

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}()'


# ValueAdapter = DispatchAdapter alias (가독성용)
ValueAdapter = DispatchAdapter


class PwmAdapter(DispatchAdapter):
    """PWM 출력 장치 — output_type='pwm', amount=duty_cycle (0-100%)."""

    def send(
        self,
        control,
        actuator_id: str,
        pct: float,
        ch: int,
        cycle_sec: float,
    ) -> None:
        if pct > 0.0:
            _raise_if_failed(control.output_on(
                actuator_id,
                output_type='pwm',
                amount=pct,
                output_channel=ch,
            ), actuator_id, 'output_on(pwm)')
        else:
            _raise_if_failed(
                control.output_off(actuator_id, output_channel=ch),
                actuator_id, 'output_off')


class TimeProportionalAdapter(DispatchAdapter):
    """on/off 릴레이 → 사이클 내 비례 시간 제어.

    on_sec = cycle_sec × pct / 100
    _MIN_ON_PCT 미만이면 OFF (소음·수명 보호).
    """

    def send(
        self,
        control,
        actuator_id: str,
        pct: float,
        ch: int,
        cycle_sec: float,
    ) -> None:
        if pct >= _MIN_ON_PCT:
            on_sec = max(1.0, cycle_sec * pct / 100.0)
            _raise_if_failed(control.output_on(
                actuator_id,
                output_type='sec',
                amount=on_sec,
                output_channel=ch,
            ), actuator_id, 'output_on(sec)')
        else:
            _raise_if_failed(
                control.output_off(actuator_id, output_channel=ch),
                actuator_id, 'output_off')


class PairedAdapter(DispatchAdapter):
    """actuator_paired 장치 — percent 그대로 'value' 전달.

    actuator_paired 드라이버가 내부에서 position → run_sec 변환을 수행한다.
    (output_on(..., output_type='value', amount=pct) 형태를 그대로 수용)

    pct=0 이더라도 output_off() 가 아닌 output_on(amount=0) 으로 전달한다.
    이유: output_off() 는 output_switch(state='off') 를 호출해 Stop 경로로 빠지고
          _last_target_pct 추적 코드를 우회한다. amount=0 을 값 명령으로 전달하면
          actuator_paired 가 0% 목표로 인식해 물리 끝점까지 닫고 last_target 을
          올바르게 기록한다.
    """

    def send(
        self,
        control,
        actuator_id: str,
        pct: float,
        ch: int,
        cycle_sec: float,
    ) -> None:
        """0% 포함 모든 명령을 output_type='value' 로 전달해 last_target 추적을 보장한다."""
        _raise_if_failed(control.output_on(
            actuator_id,
            output_type='value',
            amount=pct,
            output_channel=ch,
        ), actuator_id, 'output_on(value)')


class VolumetricAdapter(DispatchAdapter):
    """용량형 장치 (펌프·관수) — mL 단위로 변환해서 output_type='vol' 전달.

    vol_ml = flow_lpm × (cycle_sec × pct/100) / 60 × 1000
    flow_lpm: capacity_meta['irrigation_flow_lpm'] 기본 1.0 L/min
    최소 1 mL 미만이면 OFF.
    """

    def __init__(self, flow_lpm: float = 1.0):
        self._flow_lpm = max(0.001, float(flow_lpm))

    def send(
        self,
        control,
        actuator_id: str,
        pct: float,
        ch: int,
        cycle_sec: float,
    ) -> None:
        if pct >= _MIN_ON_PCT:
            on_sec  = cycle_sec * pct / 100.0
            vol_ml  = self._flow_lpm * on_sec / 60.0 * 1000.0
            if vol_ml >= 1.0:
                _raise_if_failed(control.output_on(
                    actuator_id,
                    output_type='vol',
                    amount=vol_ml,
                    output_channel=ch,
                ), actuator_id, 'output_on(vol)')
                return
        _raise_if_failed(control.output_off(actuator_id, output_channel=ch),
                         actuator_id, 'output_off')

    def __repr__(self) -> str:
        return f'VolumetricAdapter(flow_lpm={self._flow_lpm})'


# @manual ai/env-control#settings-hvac
class PulsedDoseAdapter(DispatchAdapter):
    """관수식 펄스 도징 — 짧은 정량 분무 + 강제 건조 간격.

    연속 변조(사이클의 pct% 만큼 계속 분무)는 엽면이 마를 틈을 주지 않는다.
    이 어댑터는 1회 분무를 max_on_sec 이내로 끊고, 끝난 뒤 min_off_sec 동안은
    무슨 명령이 와도 분무하지 않는다. 가습량은 펄스 폭이 아니라 펄스 빈도로
    조절된다 — 관수 제어가 회당 정량 + 간격으로 물을 주는 방식과 같다.

    요청 개도(pct)는 "이번 펄스의 길이"로 해석된다:
        on_sec = max_on_sec × pct/100  (하한 1초)

    on/off 릴레이('sec')와 용량형 펌프('vol')는 직접 시간·용량 명령을 만들고,
    그 외(PWM·value)는 물리적으로 펄스를 만들 수 없으므로 내부 어댑터에 그대로
    위임한다 — 다만 건조 간격 동안 0 을 보내는 억제는 동일하게 적용된다.

    NOTE: 시간 판정은 monotonic 이 아니라 wall clock(time.time)을 쓴다.
    호출자(_dispatch)가 같은 시계로 명령 이력을 관리하므로 기준을 맞춘다.
    """

    def __init__(self, inner: DispatchAdapter, max_on_sec: float,
                 min_off_sec: float, flow_lpm: float = 0.0):
        self._inner       = inner
        self._max_on_sec  = max(1.0, float(max_on_sec))
        self._min_off_sec = max(0.0, float(min_off_sec))
        self._flow_lpm    = max(0.0, float(flow_lpm))
        self._blocked_until: float = 0.0
        # 마지막 펄스가 끝난 시각과 그 펄스에 걸린 쉼 하한(`pulse_cap[1]`, 없으면 0).
        # 재적재 때 새 설정(min_off_sec)으로 쉼을 다시 계산하는 데 쓴다(`adopt_runtime_state`).
        self._last_pulse_end: 'float | None' = None
        self._last_on_sec: float = 0.0
        self._rest_floor: float = 0.0

    @property
    def blocked_until(self) -> float:
        """마지막 펄스 끝 + 쉼 (epoch). 실제 허용은 `_grace` 만큼 앞당겨진다. 테스트·로깅용."""
        return self._blocked_until

    def _grace(self) -> float:
        """막힌 시각을 이만큼 앞당겨 허용한다 (s) — 쉼을 "펄스 **시작** 간격 ≥ min_off" 로 읽는다.

        쉼을 펄스 **끝**부터 재면, 주기 600 s · 쉼 600 s · 켬 20 s 에서 막힌 시각이 다음
        사이클을 20 s 넘겨 분무가 10분이 아니라 20분마다 나간다. "쉼 600 s" 를 정한 뜻은
        사실상 "사이클마다 한 번까지" 다. 그래서 남은 막힘이 켬 시간 + 흔들림 여유
        (`_PULSE_JITTER_SEC` — 사이클마다 계산·전송 지연이 몇 초씩 달라 간격이 597 s 처럼 짧아진다)
        이하면 허용한다. 상한은 쉼의 10 % — 쉼이 짧은 설정에서 건조 시간을 크게 깎지 않는다.

        근거 57 펄스(`pulse_cap`)가 남긴 쉼에는 적용하지 않는다 — 그 15분 하한은 그대로다.
        """
        if self._rest_floor > 0.0 or self._last_on_sec <= 0.0:
            return 0.0
        return max(0.0, min(self._last_on_sec + _PULSE_JITTER_SEC,
                            0.1 * self._min_off_sec))

    def send(
        self,
        control,
        actuator_id: str,
        pct: float,
        ch: int,
        cycle_sec: float,
        pulse_cap: 'tuple[float, float] | None' = None,
    ) -> None:
        """`pulse_cap` = (켜는 시간 상한 s, 쉬는 시간 하한 s) — 이번 한 번만 더 조이는 값.

        극한 고온·건조의 짧은 펄스(`pulse_fog`, 근거 57)가 쓴다: 켜는 시간은 min(설정, 상한),
        쉬는 시간은 max(설정, 하한). 사용자가 더 짧게·더 드물게 정했으면 그쪽이 이긴다. 새 타이머를
        만들지 않고 이 어댑터의 시계(`_blocked_until`)를 그대로 쓴다 — 펄스가 끝난 뒤의 쉬는 시간은
        그 규칙이 풀려도 이어진다.
        """
        import time as _t
        now = _t.time()
        max_on, min_off = self._max_on_sec, self._min_off_sec
        if pulse_cap is not None:
            max_on = max(1.0, min(max_on, float(pulse_cap[0])))
            min_off = max(min_off, float(pulse_cap[1]))

        can_pulse = ((isinstance(self._inner, VolumetricAdapter) and self._flow_lpm > 0.0)
                     or isinstance(self._inner, TimeProportionalAdapter))
        if pct < _MIN_ON_PCT or now < self._blocked_until - self._grace() \
                or (pulse_cap is not None and not can_pulse):
            # 요청 없음, 또는 건조 시간 중 — 확실히 끈다. 짧은 펄스는 시간·용량으로 끊을 수 있는
            # 장치에만 나간다: PWM/값 장치는 켜 놓으면 다음 사이클까지 그대로라 10초를 지킬 수 없다.
            _raise_if_failed(
                control.output_off(actuator_id, output_channel=ch),
                actuator_id, 'output_off')
            return

        on_sec = max(1.0, max_on * min(100.0, pct) / 100.0)

        if isinstance(self._inner, VolumetricAdapter) and self._flow_lpm > 0.0:
            vol_ml = self._flow_lpm * on_sec / 60.0 * 1000.0
            if vol_ml < 1.0:
                _raise_if_failed(
                    control.output_off(actuator_id, output_channel=ch),
                    actuator_id, 'output_off')
                return
            _raise_if_failed(
                control.output_on(actuator_id, output_type='vol',
                                  amount=vol_ml, output_channel=ch),
                actuator_id, 'output_on(vol)')
        elif isinstance(self._inner, TimeProportionalAdapter):
            _raise_if_failed(
                control.output_on(actuator_id, output_type='sec',
                                  amount=on_sec, output_channel=ch),
                actuator_id, 'output_on(sec)')
        else:
            # PWM/value: 펄스를 만들 수 없다 → 진폭 그대로 위임.
            # 건조 간격 억제만으로 습윤 시간을 줄인다.
            self._inner.send(control, actuator_id, pct, ch, cycle_sec)

        self._last_pulse_end = now + on_sec
        self._last_on_sec = on_sec
        self._rest_floor = float(pulse_cap[1]) if pulse_cap is not None else 0.0
        self._blocked_until = self._last_pulse_end + min_off

    def adopt_runtime_state(self, prev: 'DispatchAdapter') -> bool:
        """재적재 전 펄스 도징 어댑터의 쉼(`_blocked_until`)을 이어받는다.

        어댑터 맵은 10분마다(`_reload_profiles`) 새로 지어진다. 이어받지 않으면 새 어댑터의
        시계가 0 이라 **방금 뿌린 분무기가 바로 다시 뿌린다** — 사용자가 정한 최소 쉼
        (`nursery_min_off_sec`)이 재적재 직후 한 번씩 풀린다(10/12 회귀 보고의 알려진 과제).

        설정값(max_on_sec·min_off_sec·flow)은 **새 것**이고, 이어받는 것은 "마지막 펄스가 언제
        끝났나" 라는 사실뿐이다. 내부 장치 종류가 바뀌었으면(릴레이 → 펌프 등) 다른 장치로 보고
        이어받지 않는다.

        쉼은 새 min_off_sec 로 **다시 계산한다**: 끝난 시각 + max(새 min_off, 그 펄스의 하한).
          * 새 값이 더 길면 늘어난다 — 새 설정이 이기고, 보수적인 쪽이다.
          * 새 값이 더 짧으면 **줄어든다.** 최소 쉼은 사용자(또는 단계별 분무 빈도 축
            `misting_care`)가 잎이 마를 시간으로 직접 고른 값이고, 그것을 줄였다는 것은
            "이제 이만큼이면 마른다" 는 새 판단이다. 옛 값으로 한 번 더 붙잡으면 바뀐 설정이
            펄스 한 번 늦게 먹을 뿐 얻는 안전이 없다. 다만 극한 고온 펄스(근거 57)가 얹은
            하한(`pulse_cap[1]`, 15분)은 설정이 아니라 그 펄스의 성질이라 그대로 지킨다.
          * 끝난 시각을 모르면(옛 판에서 만든 어댑터) 막혀 있던 시각을 그대로 쓴다.
        """
        if not isinstance(prev, PulsedDoseAdapter):
            return False
        if type(prev._inner) is not type(self._inner):
            return False
        end = prev._last_pulse_end
        if end is None:
            self._blocked_until = float(prev._blocked_until)
        else:
            self._last_pulse_end = end
            self._last_on_sec = prev._last_on_sec
            self._rest_floor = prev._rest_floor
            self._blocked_until = end + max(self._min_off_sec, prev._rest_floor)
        return True

    def __repr__(self) -> str:
        return (f'PulsedDoseAdapter(inner={self._inner!r}, '
                f'max_on_sec={self._max_on_sec}, min_off_sec={self._min_off_sec})')


def carry_adapter_state(prev_map: 'dict | None', new_map: dict) -> list:
    """재적재 전 어댑터 맵의 사이클 간 상태를 새 맵으로 넘긴다 — 넘긴 actuator_id 목록.

    같은 actuator_id 이고 **같은 어댑터 종류**일 때만 넘긴다. 장치가 빠졌으면 새 맵에 없어
    넘길 곳이 없고, 종류가 바뀌었으면 각 어댑터의 `adopt_runtime_state` 가 거절한다.
    새 맵은 제자리에서 바뀐다(설정은 새 것, 런타임 상태만 옛 것).
    """
    carried = []
    for aid, new in (new_map or {}).items():
        old = (prev_map or {}).get(aid)
        if old is None or old is new or type(old) is not type(new):
            continue
        try:
            if new.adopt_runtime_state(old):
                carried.append(aid)
        except Exception:                                           # noqa: BLE001
            # 상태를 못 넘겨도 어댑터 자체는 쓸 수 있다 — 재적재를 막지 않는다.
            continue
    return carried


# ─────────────────────────────────────────────────────────────────────────────
# 어댑터 선택 팩토리
# ─────────────────────────────────────────────────────────────────────────────

def select_adapter(
    output_name_unique: str,
    output_types_list: list,
    capacity_meta: dict | None = None,
    self_positioning: bool = False,
) -> DispatchAdapter:
    """output_name_unique 와 output_types 목록으로 적합한 어댑터를 반환한다.

    Args:
        output_name_unique: Output.output_type 필드값 (모듈 고유 이름)
        output_types_list:  parse_output_information()[module]['output_types']
                            예: ['on_off'], ['pwm'], ['value'], ['vol']
        capacity_meta:      ActuatorProfile.capacity_meta
                            (irrigation_flow_lpm 조회용)
        self_positioning:   OUTPUT_INFORMATION['self_positioning'] — 장치가 스스로
                            위치를 잡는 value 출력(Matter 창 덮개). paired 와 같이
                            0 % 도 위치 명령으로 보낸다(output_off 는 Stop 이다).

    Returns:
        DispatchAdapter 인스턴스
    """
    cap = capacity_meta or {}
    types = output_types_list or []
    if isinstance(types, str):
        types = [types]

    # 우선순위 1: paired 액추에이터(actuator_paired / actuator_paired_bus) → 내부 변환 위임
    from aot.outputs.paired_actuator_common import PAIRED_ACTUATOR_OUTPUT_TYPES
    if output_name_unique in PAIRED_ACTUATOR_OUTPUT_TYPES:
        return PairedAdapter()

    # 우선순위 1b: 스스로 위치를 잡는 value 출력 — paired 와 같은 전달 방식.
    # PAIRED_ACTUATOR_OUTPUT_TYPES 에 넣지 않는 이유: 그 집합은 자동 발견·3방향
    # UI·다리(leg) 인터록까지 끌고 오는데, 이런 장치에는 다리가 없다.
    if self_positioning and 'value' in types:
        return PairedAdapter()

    # 우선순위 2: 용량형 펌프 (vol / volume)
    if 'vol' in types or 'volume' in types:
        flow = float(cap.get('irrigation_flow_lpm') or 1.0)
        return VolumetricAdapter(flow_lpm=flow)

    # 우선순위 3: PWM
    if 'pwm' in types:
        return PwmAdapter()

    # 우선순위 4: on/off 릴레이 → 시간 비례
    if 'on_off' in types:
        return TimeProportionalAdapter()

    # 기본: value (DAC, 스텝모터 등 0-100% 직접)
    return ValueAdapter()


# ─────────────────────────────────────────────────────────────────────────────
# 어댑터 맵 빌더 (ProfileLoaderMixin 에서 호출)
# ─────────────────────────────────────────────────────────────────────────────

def build_adapter_map(by_id: dict) -> dict:
    """actuator_id → DispatchAdapter 맵핑을 빌드한다.

    각 Output 의 모듈 종류(output_name_unique)와 output_types 로
    어댑터를 동적으로 선택한다 — on_off / pwm / value(actuator_paired) / vol 등.
    하드코딩 없이 등록된 장치 형식에 따라 제어 방식이 결정된다.

    Args:
        by_id: {actuator_id: ActuatorProfile} — _reload_profiles() 내부 dict

    Returns:
        {actuator_id: DispatchAdapter}

    NOTE: 이 함수는 데몬(env_coordinator) 컨텍스트에서 호출되므로 Flask 의
    Output.query (app context 필요) 를 쓰면 RuntimeError 로 실패해 모든
    어댑터가 기본 ValueAdapter 로 떨어진다. 그 결과 actuator_paired 장치가
    on/off 로 잘못 제어된다. 따라서 반드시 db_retrieve_table_daemon 을 쓴다.
    """
    try:
        from aot.utils.outputs import parse_output_information
        output_info = parse_output_information()
    except Exception:
        output_info = {}

    # Output 레코드 조회 — 모듈 이름(output_type) 파악용.
    # 데몬 컨텍스트 안전: db_retrieve_table_daemon (Flask app context 불요).
    output_module_map: dict = {}
    try:
        from aot.databases.models import Output
        from aot.utils.database import db_retrieve_table_daemon
        for aid in by_id.keys():
            row = db_retrieve_table_daemon(Output, unique_id=aid)
            if row is not None:
                output_module_map[aid] = row.output_type
    except Exception:
        pass

    adapters: dict = {}
    for aid, profile in by_id.items():
        module_name  = output_module_map.get(aid, '')
        module_info  = output_info.get(module_name, {})
        types_list   = module_info.get('output_types') or []
        cap_meta     = getattr(profile, 'capacity_meta', None) or {}
        adapter      = select_adapter(module_name, types_list, cap_meta,
                                      bool(module_info.get('self_positioning')))

        # 관수식 펄스 도징: 프로필에 max_on_sec/min_off_sec 가 설정돼 있으면
        # (분무 액추에이터 + 육묘장 모드) 어댑터를 펄스 도징으로 감싼다.
        cc = getattr(profile, 'cmd_constraints', None)
        if cc is not None and getattr(cc, 'pulse_dosing', False):
            adapter = PulsedDoseAdapter(
                adapter,
                max_on_sec=cc.max_on_sec,
                min_off_sec=cc.min_off_sec,
                flow_lpm=float(cap_meta.get('irrigation_flow_lpm') or 0.0),
            )

        adapters[aid] = adapter

    return adapters


# ── 스크린(커튼·차광막) 0/100 결정 ────────────────────────────────────────────
# 부분 전개는 스크린이 고르지 않아 쓰지 않는다 — 완전히 닫거나 완전히 걷는다.
# 경계(50 %) 한 점으로 자르면 명령이 그 근처에 앉았을 때 사이클마다 끝에서 끝으로
# 오간다(편도 수 분 주행). 그래서 지금 서 있는 쪽에서 반대쪽으로 넘어가려면
# 경계를 한 칸 더 넘어야 한다.
SCREEN_KINDS = ('curtain', 'shade')
SCREEN_OPEN_AT = 60.0      # 닫혀 있을 때 이 이상이면 걷는다
SCREEN_CLOSE_AT = 40.0     # 걷혀 있을 때 이 이하면 닫는다


# 부분 개도의 예외 — **위치를 잡을 수 있는** 스크린(`capacity_meta['screen_positional']`:
# Paired/Value 어댑터 + 주행 시간을 안다)에, 스크린 판단(`screen_policy`)이 정한 정지점만.
# PI 의 명령은 지금처럼 0/100 이다. 근거 46(밤 결로 틈)·47(아침 램프)만 정지점 그대로 둔다.
CURTAIN_STOPS = (0.0, 3.0, 6.0, 10.0, 30.0, 60.0, 100.0)
SCREEN_PARTIAL_REASONS = (REASON_CURTAIN_GAP, REASON_CURTAIN_RAMP)


def screen_partial_ok(profile, value, reason) -> bool:
    """이 스크린 명령을 0/100 으로 자르지 않고 그대로 보내는가."""
    if not (getattr(profile, 'capacity_meta', None) or {}).get('screen_positional'):
        return False
    try:
        r = int(reason)
        v = float(value)
    except (TypeError, ValueError):
        return False
    return r in SCREEN_PARTIAL_REASONS and any(abs(v - s) < 1e-6 for s in CURTAIN_STOPS)


def snap_screen_value(value: float, current: 'float | None') -> float:
    """스크린 명령을 0/100 으로. `current` 는 지금 서 있는 개도(모르면 None)."""
    v = float(value)
    if current is None:
        return 100.0 if v >= 50.0 else 0.0
    if float(current) >= 50.0:
        return 0.0 if v <= SCREEN_CLOSE_AT else 100.0
    return 100.0 if v >= SCREEN_OPEN_AT else 0.0


def snap_screen_commands(final_cmds: dict, profiles, positions: dict) -> None:
    """`final_cmds` 의 스크린 명령을 제자리에서 0/100 으로 바꾼다(기록·전송 공통).

    예외는 `screen_partial_ok` 하나 — 위치를 잡는 스크린의 틈·램프 정지점은 그대로 둔다.
    """
    by_id = {p.actuator_id: p for p in profiles or []}
    for aid, cmd in final_cmds.items():
        p = by_id.get(aid)
        if getattr(p, 'kind', '') not in SCREEN_KINDS:
            continue
        if isinstance(cmd, dict):
            if screen_partial_ok(p, cmd.get('value', 0.0), cmd.get('reason')):
                continue
            cmd['value'] = snap_screen_value(cmd.get('value', 0.0), positions.get(aid))
        elif hasattr(cmd, 'value'):
            if screen_partial_ok(p, cmd.value, getattr(cmd, 'reason', None)):
                continue
            cmd.value = snap_screen_value(cmd.value, positions.get(aid))
