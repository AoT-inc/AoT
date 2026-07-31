# coding=utf-8
"""P6 coordinator — NO_GRADIENT 완화가 dispatch 위치가 아닌 내부 적분(I)에서
감쇠하면, 포화(anti-windup) 뒤에 명령이 예고 없이 뚝 떨어지는 회귀 테스트.

2026-07-29 aot-005 폭염 사건 재현: 보온커튼이 강한 냉방 수요로 며칠째 100%
(완전 개방)로 표시되고 있었지만, anti-windup back-calculation이 내부 I를
그 이면에서 낮은 값으로 깎아두고 있었다. 이후 사이클에서 무구배(NO_GRADIENT)로
전환되자, 그 낮은 I에서 감쇠가 시작되며 명령이 100→40으로 급락했다
(safe_default=100인 커튼/차광막인데도 닫히는 방향으로 움직임).
"""
from aot.functions.utils.env_control.coordinator import coordinate, CoordinatorState
from aot.functions.utils.env_control.types import (
    ActuatorProfile, SituationReport, TargetVar, EffectResult,
)


def _saturating_effect(env, cmd_pct, profile=None):
    # 매우 큰 편차 → P+I 가 100을 크게 초과해 포화되도록 유도.
    return EffectResult('↓', 50.0)


def _no_gradient_effect(env, cmd_pct, profile=None):
    # 내외차 소멸 → 구동력 없음 (curtain_temp_effect 의 |delta|<0.5 케이스와 동일 형태).
    return EffectResult('0', 0.0)


def _make_curtain_profile(effect_fn):
    return ActuatorProfile(
        actuator_id='curtain-1',
        kind='curtain',
        safe_default=100.0,             # 스크린은 idle 시 걷힘(열림)이 안전
        effect_model={'temperature': effect_fn},
    )


def _situation(deviation_temp):
    return SituationReport(
        context={'cycle_sec': 60.0, 'T_ext': 33.0, 'T_int': 36.0},
        target={'temperature': TargetVar(value=25.0, tolerance=1.0, priority=1.0)},
        deviation_native={'temperature': deviation_temp},
        authority={},   # falsy → natural_vars 필터 비활성 (모든 변수 능동 취급)
    )


def test_no_gradient_relax_holds_saturated_position_instead_of_collapsing():
    state = CoordinatorState()
    idx = {'curtain-1': 0}

    # ── 1~2 사이클: 강한 냉방 수요로 포화 (P+I ≫ 100) → dispatch 는 100에 클램프
    #    되지만 anti-windup 이 내부 I 를 그 이면에서 낮춘다.
    profile = _make_curtain_profile(_saturating_effect)
    for _ in range(2):
        commands, state = coordinate(
            _situation(deviation_temp=10.0), [profile], state, unique_id='', actuator_index=idx,
        )
        assert commands['curtain-1'].control_value() == 100.0

    hidden_integral_before = state.integral['curtain-1']
    # anti-windup 이 실제로 I 를 dispatch 값(100)보다 낮춰뒀어야 이 테스트가
    # 재현하려는 전제조건이 성립한다.
    assert hidden_integral_before < 100.0

    # ── 3번째 사이클: 무구배 전환. 커튼은 이미 100%(완전 개방)로 열려 있었으므로
    #    안전 위치(safe_default=100)에서 전혀 벗어나 있지 않다 → 명령이 100
    #    부근에 그대로 머물러야 한다(당겨져 닫히면 안 됨).
    profile2 = _make_curtain_profile(_no_gradient_effect)
    commands, state = coordinate(
        _situation(deviation_temp=10.0), [profile2], state, unique_id='', actuator_index=idx,
    )
    cmd = commands['curtain-1'].control_value()
    assert cmd > 95.0, (
        f'커튼이 이미 100%로 열려 있었는데 NO_GRADIENT 전환 후 {cmd}로 급락했다 — '
        'relax가 dispatch 위치가 아닌 깎여있던 내부 I에서 감쇠했다는 뜻(회귀).'
    )
