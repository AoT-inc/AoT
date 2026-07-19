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
from __future__ import annotations

# on/off 어댑터 최소 작동 임계 (%)
_MIN_ON_PCT = 5.0


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
            control.output_on(
                actuator_id,
                output_type='value',
                amount=pct,
                output_channel=ch,
            )
        else:
            control.output_off(actuator_id, output_channel=ch)

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
            control.output_on(
                actuator_id,
                output_type='pwm',
                amount=pct,
                output_channel=ch,
            )
        else:
            control.output_off(actuator_id, output_channel=ch)


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
            control.output_on(
                actuator_id,
                output_type='sec',
                amount=on_sec,
                output_channel=ch,
            )
        else:
            control.output_off(actuator_id, output_channel=ch)


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
        control.output_on(
            actuator_id,
            output_type='value',
            amount=pct,
            output_channel=ch,
        )


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
                control.output_on(
                    actuator_id,
                    output_type='vol',
                    amount=vol_ml,
                    output_channel=ch,
                )
                return
        control.output_off(actuator_id, output_channel=ch)

    def __repr__(self) -> str:
        return f'VolumetricAdapter(flow_lpm={self._flow_lpm})'


# ─────────────────────────────────────────────────────────────────────────────
# 어댑터 선택 팩토리
# ─────────────────────────────────────────────────────────────────────────────

def select_adapter(
    output_name_unique: str,
    output_types_list: list,
    capacity_meta: dict | None = None,
) -> DispatchAdapter:
    """output_name_unique 와 output_types 목록으로 적합한 어댑터를 반환한다.

    Args:
        output_name_unique: Output.output_type 필드값 (모듈 고유 이름)
        output_types_list:  parse_output_information()[module]['output_types']
                            예: ['on_off'], ['pwm'], ['value'], ['vol']
        capacity_meta:      ActuatorProfile.capacity_meta
                            (irrigation_flow_lpm 조회용)

    Returns:
        DispatchAdapter 인스턴스
    """
    cap = capacity_meta or {}
    types = output_types_list or []
    if isinstance(types, str):
        types = [types]

    # 우선순위 1: actuator_paired → 내부 변환 위임
    if output_name_unique == 'actuator_paired':
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
        adapters[aid] = select_adapter(module_name, types_list, cap_meta)

    return adapters
