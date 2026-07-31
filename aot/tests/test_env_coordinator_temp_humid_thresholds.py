# coding=utf-8
"""온습도 하드 임계(temp_max/min, humid_max/min) 오버라이드 회귀 테스트.

2026-07-29 발견: `_force_cool`/`_force_heat`/`_force_dehumid`/`_force_humid`
플래그가 _cycle_mixin.py 에서 세팅만 되고 어디서도 소비되지 않는 죽은
코드였다 — 사용자가 설정한 temp_max/min, humid_max/min 이 (debug_logging
꺼진 상태에서는) 완전히 무효였다. apply_temp_humid_threshold_overrides() 로
실제 강제 오버라이드를 wiring.
"""
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    apply_temp_humid_threshold_overrides,
    apply_threshold_and_gate_overrides,
)
from aot.functions.utils.env_control.types import ActuatorProfile


def _profiles(*kinds):
    return [ActuatorProfile(actuator_id=f'{k}-1', kind=k) for k in kinds]


def test_force_cool_mirrors_gate_bit_heat_actuators():
    profiles = _profiles('opening', 'shade', 'cooler', 'heater', 'curtain')
    final_cmds = {}
    apply_temp_humid_threshold_overrides({'_force_cool': True}, profiles, final_cmds)

    assert final_cmds.get('opening-1') == {'value': 100.0, 'reason': 'temp_max'}
    assert final_cmds.get('shade-1') == {'value': 0.0, 'reason': 'temp_max'}
    assert final_cmds.get('cooler-1') == {'value': 100.0, 'reason': 'temp_max'}
    # 한파 전용 액추에이터는 건드리지 않는다.
    assert 'heater-1' not in final_cmds
    assert 'curtain-1' not in final_cmds


def test_force_heat_mirrors_gate_bit_cold_actuators():
    profiles = _profiles('opening', 'curtain', 'heater', 'shade', 'cooler')
    final_cmds = {}
    apply_temp_humid_threshold_overrides({'_force_heat': True}, profiles, final_cmds)

    assert final_cmds.get('opening-1') == {'value': 0.0, 'reason': 'temp_min'}
    assert final_cmds.get('curtain-1') == {'value': 0.0, 'reason': 'temp_min'}
    assert final_cmds.get('heater-1') == {'value': 100.0, 'reason': 'temp_min'}
    assert 'shade-1' not in final_cmds
    assert 'cooler-1' not in final_cmds


def test_force_dehumid_uses_exhaust_fan_only():
    profiles = _profiles('exhaust_fan', 'opening', 'fogger')
    final_cmds = {}
    apply_temp_humid_threshold_overrides({'_force_dehumid': True}, profiles, final_cmds)

    assert final_cmds.get('exhaust_fan-1') == {'value': 100.0, 'reason': 'humid_max'}
    # 온도 강제 액추에이터 집합과 겹치지 않아야 한다(충돌 방지 설계).
    assert 'opening-1' not in final_cmds
    assert 'fogger-1' not in final_cmds


def test_force_humid_uses_fogger_only():
    profiles = _profiles('fogger', 'exhaust_fan')
    final_cmds = {}
    apply_temp_humid_threshold_overrides({'_force_humid': True}, profiles, final_cmds)

    assert final_cmds.get('fogger-1') == {'value': 100.0, 'reason': 'humid_min'}
    assert 'exhaust_fan-1' not in final_cmds


def test_temp_and_humid_forces_never_collide_on_same_actuator():
    # 극단 케이스: 덥고 습한 상황 동시 발생 — 온도 강제(opening/shade/cooler)와
    # 습도 강제(exhaust_fan/fogger) 액추에이터 집합이 겹치지 않으므로 서로
    # 덮어쓰지 않아야 한다.
    profiles = _profiles('opening', 'shade', 'cooler', 'exhaust_fan')
    final_cmds = {}
    apply_temp_humid_threshold_overrides(
        {'_force_cool': True, '_force_dehumid': True}, profiles, final_cmds,
    )

    assert final_cmds.get('opening-1') == {'value': 100.0, 'reason': 'temp_max'}
    assert final_cmds.get('exhaust_fan-1') == {'value': 100.0, 'reason': 'humid_max'}


def test_no_breach_leaves_commands_untouched():
    profiles = _profiles('opening', 'shade', 'cooler', 'heater', 'curtain',
                         'exhaust_fan', 'fogger')
    final_cmds = {}
    apply_temp_humid_threshold_overrides({}, profiles, final_cmds)

    assert final_cmds == {}


# ── 안전 프리게이트 우선순위 ────────────────────────────────────────────────

def test_safety_gate_wins_over_force_cool_in_high_wind():
    """강풍(풍향 차등 폐쇄) + 실내 고온 동시 발생 시 게이트가 이겨야 한다.

    한여름엔 실내 33~36°C(_force_cool 발동)와 강풍이 동시에 오는 게 흔하다.
    임계 오버라이드가 게이트보다 뒤에 적용되면 풍상측 개구부 폐쇄(0)를
    100으로 덮어써 강풍 속에 창을 활짝 열어버린다.
    """
    profiles = _profiles('opening', 'cooler')
    final_cmds = {}
    # 안전 프리게이트가 풍상측 개구부를 폐쇄하도록 강제한 상태.
    partial_overrides = {'opening-1': {'value': 0.0, 'reason': 'safety_pre_gate'}}

    apply_threshold_and_gate_overrides(
        {'_force_cool': True}, profiles, final_cmds, partial_overrides,
    )

    assert final_cmds['opening-1'] == {'value': 0.0, 'reason': 'safety_pre_gate'}, (
        '강풍 중 안전 게이트의 개구부 폐쇄를 _force_cool 이 덮어썼다 — '
        '임계 오버라이드가 게이트보다 뒤에 적용된다는 뜻(안전 회귀).'
    )
    # 게이트가 건드리지 않은 액추에이터는 냉방 강제가 그대로 살아 있어야 한다.
    assert final_cmds['cooler-1'] == {'value': 100.0, 'reason': 'temp_max'}


def test_safety_gate_wins_over_light_min_shade_open():
    profiles = _profiles('shade')
    final_cmds = {}
    partial_overrides = {'shade-1': {'value': 0.0, 'reason': 'safety_pre_gate'}}

    apply_threshold_and_gate_overrides(
        {'_force_suplight': True}, profiles, final_cmds, partial_overrides,
    )

    assert final_cmds['shade-1'] == {'value': 0.0, 'reason': 'safety_pre_gate'}


def test_thresholds_still_apply_when_gate_inactive():
    profiles = _profiles('opening', 'cooler')
    final_cmds = {}

    apply_threshold_and_gate_overrides({'_force_cool': True}, profiles, final_cmds, {})

    assert final_cmds['opening-1'] == {'value': 100.0, 'reason': 'temp_max'}
    assert final_cmds['cooler-1'] == {'value': 100.0, 'reason': 'temp_max'}
