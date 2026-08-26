# coding=utf-8
"""환기로 닿을 수 있으면 냉난방을 쉬게 한다 (`vent_first`, 2026-08-26).

## 왜 필요한가

부하분담을 도메인으로 나눈 뒤(2026-08-26) **냉난방은 창이 하는 일을 모른다.**
그것이 도메인 분리의 목적이자 대가다 — 창 하나의 오작동이 냉난방을 거꾸로
켜는 경로는 사라졌지만, 창이 이미 해결하고 있는 일을 냉난방이 또 한다.

실측(2026-08-26 イチゴ): 실내 VPD 0.253 · 목표 0.579 · 실외 0.895.
창을 다 열면 한 사이클에 0.588 kPa 를 옮길 수 있는데 **난방기가 80% 로**
올라가고 있었다. 바깥 공기가 공짜로 할 일을 돈 주고 한 셈이다.

도메인 간 조율은 암묵적 효과 누적이 아니라 **선언된 인터록**이 맡는다 —
선언돼 있어 감사 가능하고 안전한 쪽으로 실패한다. 이것은 이미 있던
`hvac_interlock`(냉난방 가동 중 창 잠금)의 짝이다.

## 파킹 조건 셋 — 하나라도 어긋나면 냉난방을 그대로 둔다

    ① 실외가 목표를 여유(tolerance×VENT_REACH_MARGIN)만큼 **지나** 있다
    ② 제어 대상 변수가 **전부** 그렇다
    ③ 환기에 **여력이 남아 있다** (직전 평균 개도 < VENT_HEADROOM_PCT)

③ 이 없으면 창이 만개인데도 편차가 남는 상황에서 냉난방까지 파킹되어
**아무도 일하지 않는 상태**가 된다.

## ⚠ 기본값은 꺼짐

업그레이드로 조용히 달라지는 설치가 없어야 한다. 창이 작거나 실외 측정이
믿을 만하지 않은 설치에서는 켜면 안 되는 기능이다.

## ⚠ `hvac_interlock` 과 교착하지 않는다

둘 다 켜도 된다. 이 판정은 **실외 조건만** 보므로(냉난방이 지금 도는지를 보지
않는다) 냉난방이 파킹되면 `hvac_running` 이 내려가고 개구부 잠금이 풀린다.
반대 방향으로는 ③ 이 막는다.
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    VENT_HEADROOM_PCT, VENT_REACH_MARGIN, _ventilation_reaches_all_targets,
    coordinate, CoordinatorState,
)
from aot.functions.utils.env_control.log_channels import REASON_NO_GRADIENT
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, target, deviation, context=None):
        self.target = target
        self.deviation_native = deviation
        self.context = context or {'cycle_sec': 600.0}


def _profile(aid, kind, direction='↑', magnitude=1.0):
    return ActuatorProfile(
        actuator_id=aid, kind=kind,
        effect_model={'temperature': _effect(direction, magnitude)},
        cost_fn=lambda env, pct: 5.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)


# 실내 20 °C · 목표 24 °C(허용 1.0) → 4 °C 올려야 한다.
_TARGET = {'temperature': TargetVar(value=24.0, tolerance=1.0,
                                    priority=1.0, unit='C')}
_DEV = {'temperature': -4.0}          # 측정 − 목표


def _ctx(T_ext):
    return {'cycle_sec': 600.0, 'T_ext': T_ext, 'vent_first': True}


class TestReachJudgement:
    """① 실외가 목표를 여유만큼 지나 있는가."""

    def _judge(self, T_ext, prev=0.0, vents=None):
        v = vents if vents is not None else [_profile('vent', 'opening')]
        return _ventilation_reaches_all_targets(
            _Situation(_TARGET, _DEV), _ctx(T_ext), v,
            {p.actuator_id: prev for p in v})

    def test_실외가_목표를_충분히_넘으면_닿는다(self):
        """실외 30 °C — 목표 24 를 6 도 넘는다(필요 4 + 여유 1)."""
        assert self._judge(30.0) is True

    def test_딱_목표면_닿았다고_보지_않는다(self):
        """점근할 뿐이고, 경계에서 켜졌다 꺼졌다 한다."""
        assert self._judge(24.0) is False

    def test_여유가_부족하면_닿았다고_보지_않는다(self):
        margin = 1.0 * VENT_REACH_MARGIN
        assert self._judge(24.0 + margin * 0.5) is False

    def test_방향이_반대면_안_닿는다(self):
        """실외가 더 추우면 환기로는 데울 수 없다 — 난방기가 필요하다."""
        assert self._judge(10.0) is False

    def test_실외를_모르면_단정하지_않는다(self):
        v = [_profile('vent', 'opening')]
        assert _ventilation_reaches_all_targets(
            _Situation(_TARGET, _DEV), {'cycle_sec': 600.0}, v,
            {'vent': 0.0}) is False


class TestHeadroom:
    """③ 창이 이미 만개면 냉난방이 도와야 한다."""

    def test_여력이_있으면_파킹한다(self):
        v = [_profile('vent', 'opening')]
        assert _ventilation_reaches_all_targets(
            _Situation(_TARGET, _DEV), _ctx(30.0), v,
            {'vent': VENT_HEADROOM_PCT - 10.0}) is True

    def test_만개면_파킹하지_않는다(self):
        """여기서 파킹하면 아무도 일하지 않는 상태가 된다."""
        v = [_profile('vent', 'opening')]
        assert _ventilation_reaches_all_targets(
            _Situation(_TARGET, _DEV), _ctx(30.0), v,
            {'vent': 100.0}) is False

    def test_환기_장치가_없으면_파킹하지_않는다(self):
        assert _ventilation_reaches_all_targets(
            _Situation(_TARGET, _DEV), _ctx(30.0), [], {}) is False


class TestAllVariablesMustBeReachable:
    """② 하나라도 환기로 못 가면 냉난방이 필요하다."""

    def test_한_변수만_반대여도_안_판다(self):
        target = dict(_TARGET)
        target['humidity'] = TargetVar(value=60.0, tolerance=5.0,
                                       priority=1.0, unit='percent')
        dev = dict(_DEV)
        dev['humidity'] = +20.0        # 실내가 20% 더 습하다 → 낮춰야 한다
        ctx = _ctx(30.0)
        ctx['RH_ext'] = 95.0           # 실외가 더 습하다 → 환기로는 못 낮춘다
        v = [_profile('vent', 'opening')]
        assert _ventilation_reaches_all_targets(
            _Situation(target, dev), ctx, v, {'vent': 0.0}) is False

    def test_범위_안_변수는_판정에서_뺀다(self):
        """포함시키면 평형 변수의 avail 이 0 이라 항상 False 가 된다."""
        target = dict(_TARGET)
        target['humidity'] = TargetVar(value=60.0, tolerance=5.0,
                                       priority=1.0, unit='percent')
        dev = dict(_DEV)
        dev['humidity'] = 0.0          # 이미 목표
        ctx = _ctx(30.0)
        ctx['RH_ext'] = 60.0
        v = [_profile('vent', 'opening')]
        assert _ventilation_reaches_all_targets(
            _Situation(target, dev), ctx, v, {'vent': 0.0}) is True

    def test_벗어난_변수가_없으면_판정하지_않는다(self):
        """평형에서 냉난방을 파킹하는 것은 이 옵션의 일이 아니다."""
        v = [_profile('vent', 'opening')]
        assert _ventilation_reaches_all_targets(
            _Situation(_TARGET, {'temperature': 0.0}), _ctx(30.0), v,
            {'vent': 0.0}) is False


class TestEndToEnd:
    """coordinate() 를 통과시켜 실제로 냉난방이 쉬는지 본다."""

    def _run(self, vent_first, T_ext=30.0):
        vent   = _profile('vent', 'opening', '↑', magnitude=2.0)
        heater = _profile('heater', 'heater', '↑', magnitude=2.0)
        ctx = {'cycle_sec': 600.0, 'T_ext': T_ext,
               'vent_first': vent_first, 'vent_futility_gate': False}
        state = CoordinatorState()
        state.prev_commands = {'vent': 10.0, 'heater': 60.0}
        state.integral = {'vent': 10.0, 'heater': 60.0}
        return coordinate(_Situation(_TARGET, _DEV, ctx),
                          [vent, heater], state, unique_id='t')[0]

    def test_켜면_난방기가_쉰다(self):
        cmds = self._run(vent_first=True)
        assert cmds['heater'].reason == REASON_NO_GRADIENT
        assert cmds['heater'].control_value() < 60.0, '안전 위치로 수렴해야 한다'

    def test_켜도_창은_계속_연다(self):
        """냉난방을 쉬게 하는 것이지 환기를 멈추는 게 아니다."""
        assert self._run(vent_first=True)['vent'].control_value() > 10.0

    def test_끄면_종전대로_난방기가_돈다(self):
        """기본값은 꺼짐 — 업그레이드로 조용히 달라지는 설치가 없어야 한다."""
        cmds = self._run(vent_first=False)
        assert cmds['heater'].reason != REASON_NO_GRADIENT

    def test_실외가_추우면_켜도_난방기가_돈다(self):
        cmds = self._run(vent_first=True, T_ext=10.0)
        assert cmds['heater'].reason != REASON_NO_GRADIENT


class TestContract:

    def test_기본값이_꺼짐이다(self):
        from aot.functions.custom_functions.env_coordinator_impl import (
            _function_info as fi)
        opt = next(o for o in fi.FUNCTION_INFORMATION['custom_options']
                   if o.get('id') == 'vent_first')
        assert opt['default_value'] is False
        assert opt['type'] == 'bool'

    def test_옵션_스키마에_있다(self):
        """스키마에 없으면 화면에 안 나오고 값도 안 채워진다
        (test_env_coordinator_dead_options 참조)."""
        from aot.functions.custom_functions.env_coordinator_impl import (
            _function_info as fi)
        ids = {o.get('id') for o in fi.FUNCTION_INFORMATION['custom_options']}
        assert 'vent_first' in ids

    def test_ctx_로_전달된다(self):
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl import (
            _cycle_mixin as m)
        src = inspect.getsource(m.CycleMixin._run_cycle)
        assert "situation.context['vent_first']" in src

    def test_hvac_도메인만_판다(self):
        """차광막·CO2 주입기까지 파킹하면 다른 일이 멈춘다."""
        import inspect
        from aot.functions.utils.env_control import coordinator as c
        src = inspect.getsource(c.coordinate)
        i = src.index("ctx.get('vent_first'")
        assert "== 'hvac'" in src[i:i + 500]


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
