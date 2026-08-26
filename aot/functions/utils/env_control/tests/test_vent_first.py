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

## 파킹 조건 넷 — 하나라도 어긋나면 냉난방을 그대로 둔다

    ① 실외가 목표를 여유(tolerance×VENT_REACH_MARGIN)만큼 **지나** 있다
    ② 제어 대상 변수가 **전부** 그렇다
    ③ 환기에 **여력이 남아 있다** (직전 **최대** 개도 < VENT_HEADROOM_PCT)
    ④ 파킹한 지 VENT_FIRST_PATIENCE_S 를 넘지 않았다

③ 이 없으면 창이 만개인데도 편차가 남는 상황에서 냉난방까지 파킹되어
**아무도 일하지 않는 상태**가 된다.

## ⚠ ③ 은 평균이 아니라 **최댓값**이다 (2026-08-26 수정)

평균이면 안 열리는 창 하나가 escalation 을 **산술적으로 불가능**하게 만든다 —
개구부 셋 중 하나가 0% 에 고착되면 나머지 둘이 만개해도 평균은 66.7% 라
90% 에 영영 못 닿고, 냉난방은 어떤 조건에서도 안 켜진다. イチゴ 온실이 실제로
그 상태였다(側面窓 9%/33% · 天窓 0%).

## ⚠ ③ 만으로는 부족하다 — "여력" 은 "결과" 가 아니다 (④)

③ 은 "더 밀 데가 있나" 를 물을 뿐 "실제로 되고 있나" 는 묻지 않는다. 창이
조금 열린 채 목표에 안 닿아도 여력은 남아 있으므로 냉난방은 **무한정**
파킹된다. 예측(실외가 목표 너머)이 맞다면 편차가 줄어 판정이 스스로 꺼지므로
인내 시간은 쌓이지 않는다 — 쌓인다는 것은 예측이 틀렸다는 뜻이다.

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
    VENT_FIRST_PATIENCE_S, VENT_HEADROOM_PCT, VENT_REACH_MARGIN,
    _ventilation_reaches_all_targets,
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

    def test_하나만_만개여도_파킹하지_않는다(self):
        """**평균이면 여기서 틀린다.**

        (100+0+0)/3 = 33% 라 평균 기준은 "여력 있음" 이라 답하고 파킹을
        이어 간다. 그런데 만개한 창은 더 밀 데가 없다.
        """
        v = [_profile(a, 'opening') for a in ('r', 'l', 'ridge')]
        prev = {'r': 100.0, 'l': 0.0, 'ridge': 0.0}
        assert _ventilation_reaches_all_targets(
            _Situation(_TARGET, _DEV), _ctx(30.0), v, prev) is False

    def test_고착된_창이_escalation_을_막지_않는다(self):
        """실측 모양 — 天窓 0% 고착. 나머지 둘이 만개하면 넘어가야 한다.

        평균 기준에서는 (100+100+0)/3 = 66.7% 로 90% 에 **영영 못 닿아**
        냉난방이 어떤 경우에도 안 켜졌다.
        """
        v = [_profile(a, 'opening') for a in ('r', 'l', 'ridge')]
        prev = {'r': 100.0, 'l': 100.0, 'ridge': 0.0}
        assert _ventilation_reaches_all_targets(
            _Situation(_TARGET, _DEV), _ctx(30.0), v, prev) is False


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


class TestPatience:
    """④ 환기가 실제로 못 해내면 냉난방에 넘긴다.

    `coordinate()` 를 통과시켜야 하는 검사다 — 인내는 사이클 사이에 **상태로**
    쌓이므로, 판정 함수만 불러서는 존재 자체를 확인할 수 없다.
    """

    def _cycle(self, state, T_ext=30.0, dev=-4.0, cycle_sec=600.0):
        vent   = _profile('vent', 'opening', '↑', magnitude=2.0)
        heater = _profile('heater', 'heater', '↑', magnitude=2.0)
        ctx = {'cycle_sec': cycle_sec, 'T_ext': T_ext,
               'vent_first': True, 'vent_futility_gate': False}
        return coordinate(_Situation(_TARGET, {'temperature': dev}, ctx),
                          [vent, heater], state, unique_id='t')

    def _run(self, cycles, **kw):
        state = CoordinatorState()
        state.prev_commands = {'vent': 10.0, 'heater': 60.0}
        state.integral      = {'vent': 10.0, 'heater': 60.0}
        out = []
        for _ in range(cycles):
            cmds, state = self._cycle(state, **kw)
            out.append(cmds['heater'].reason)
        return out, state

    def test_인내_안에는_계속_파킹한다(self):
        """한두 사이클 만에 넘기면 창이 움직일 시간도 없이 냉난방이 켜진다."""
        reasons, st = self._run(int(VENT_FIRST_PATIENCE_S // 600) - 1)
        assert all(r == REASON_NO_GRADIENT for r in reasons), reasons
        assert st.vent_first_held_s < VENT_FIRST_PATIENCE_S

    def test_인내를_넘기면_난방기에_넘긴다(self):
        """편차가 그대로라는 것은 실외 예측이 틀렸다는 뜻이다."""
        reasons, st = self._run(int(VENT_FIRST_PATIENCE_S // 600) + 1)
        assert reasons[-1] != REASON_NO_GRADIENT, (
            '%.0f초를 못 맞췄는데도 난방기가 파킹돼 있다' % st.vent_first_held_s)

    def test_목표에_들어오면_인내가_되돌아간다(self):
        """환기가 해내면 다시 환기 우선으로 돌아간다 — 넘긴 뒤 굳으면
        바깥 공기가 공짜로 할 일을 계속 돈 주고 하게 된다."""
        state = CoordinatorState()
        state.prev_commands = {'vent': 10.0, 'heater': 60.0}
        for _ in range(3):
            _, state = self._cycle(state)
        assert state.vent_first_held_s > 0.0
        _, state = self._cycle(state, dev=0.0)     # 목표 도달
        assert state.vent_first_held_s == 0.0

    def test_판정이_꺼져_있으면_쌓이지_않는다(self):
        """실외가 추워 환기로 못 가는 동안 인내가 쌓이면, 나중에 환기가
        가능해진 순간 파킹이 시작도 못 해 보고 바로 풀린다."""
        _, st = self._run(5, T_ext=10.0)
        assert st.vent_first_held_s == 0.0

    def test_사이클_길이가_아니라_시간으로_센다(self):
        """사이클 수로 세면 주기가 짧은 설치에서 인내가 그만큼 짧아진다."""
        _, fast = self._run(3, cycle_sec=60.0)
        _, slow = self._run(3, cycle_sec=600.0)
        assert fast.vent_first_held_s == pytest.approx(180.0)
        assert slow.vent_first_held_s == pytest.approx(1800.0)

    def test_greybox_경로도_인내를_이어_받는다(self):
        """MPC 경로는 `CoordinatorState` 를 새로 만든다 — 거기서 빠뜨리면
        매 사이클 0 에서 다시 세어 인내가 **영영 차지 않는다.**
        증상은 "④ 가 없는 것" 과 구분되지 않는다."""
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl \
            import _cycle_mixin as m
        src = inspect.getsource(m)
        # ⚠ `')'` 로 자르면 안 된다 — 인자 안의 `dict(...)` 가 먼저 걸린다.
        #   생성 호출은 짧으므로 고정 창으로 본다.
        for i, block in enumerate(src.split('CoordinatorState(')[1:], 1):
            assert 'vent_first_held_s' in block[:600], (
                '%d번째 CoordinatorState 생성이 인내를 안 넘긴다' % i)

    def test_인내가_strain_판정과_같은_길이다(self):
        """다르면 화면이 "못 따라가고 있다" 고 말하는 동안에도 냉난방이
        파킹돼 있는 구간이 생긴다."""
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin \
            import CycleMixin
        assert VENT_FIRST_PATIENCE_S == CycleMixin._STRAIN_MIN_SEC


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
