# coding=utf-8
"""광량 하드 임계(light_max/light_min) 오버라이드 회귀 테스트.

2026-07-29 aot-005 사건: 광량이 부족한데도 차광막이 계속 닫혀 있었다.
light_max 위반엔 차광막을 닫는 오버라이드가 있었지만, light_min 위반엔
보광등(lighting)만 켜려 하고 차광막을 열어주는 대칭 로직이 없었다 —
보광등이 없는(가장 흔한) 시설은 광부족에 아무 대응도 못 했다.
"""
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    apply_light_threshold_overrides,
)
from aot.functions.utils.env_control.types import ActuatorProfile


def _profiles(*kinds):
    return [ActuatorProfile(actuator_id=f'{k}-1', kind=k) for k in kinds]


def test_light_min_forces_shade_open_when_no_lighting_actuator():
    # 보광등 없이 차광막만 있는(가장 흔한) 시설 구성.
    profiles = _profiles('shade', 'opening')
    final_cmds = {}
    apply_light_threshold_overrides({'_force_suplight': True}, profiles, final_cmds)

    assert final_cmds.get('shade-1') == {'value': 100.0, 'reason': 'light_min'}
    # 무관한 액추에이터(opening)는 건드리지 않는다.
    assert 'opening-1' not in final_cmds


def test_light_min_also_turns_on_lighting_when_present():
    profiles = _profiles('shade', 'lighting')
    final_cmds = {}
    apply_light_threshold_overrides({'_force_suplight': True}, profiles, final_cmds)

    assert final_cmds.get('lighting-1') == {'value': 100.0, 'reason': 'light_min'}
    assert final_cmds.get('shade-1') == {'value': 100.0, 'reason': 'light_min'}


def test_light_max_still_forces_shade_closed():
    profiles = _profiles('shade')
    final_cmds = {}
    apply_light_threshold_overrides({'_force_shade': True}, profiles, final_cmds)

    assert final_cmds.get('shade-1') == {'value': 0.0, 'reason': 'light_max'}


def test_no_breach_leaves_commands_untouched():
    profiles = _profiles('shade', 'lighting')
    final_cmds = {}
    apply_light_threshold_overrides({}, profiles, final_cmds)

    assert final_cmds == {}
