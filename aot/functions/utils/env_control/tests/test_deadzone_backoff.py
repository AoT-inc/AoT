# coding=utf-8
"""목표에 닿았는데 **넘어서** 있으면 물러난다 (2026-08-26).

## 무엇이 잘못됐었나

데드존 안에서는 `e_eff = 0` 이라 P·I 가 모두 쉬고 `cmd = I`(기억된 평형
개도)가 그대로 나간다. 진동을 없애려고 일부러 그렇게 만든 것이고, 그 설계는
**유지되는 값이 평형이라는 전제** 위에 있다.

편차가 부호를 넘어가는 순간 그 전제가 깨진다. 구동이 0 이므로 방향 판정도
서지 않아, 방향이 이미 반대가 된 장치가 **그 순간의 명령으로 얼어붙고**
근거코드는 `PRIMARY` 로 남는다.

실측(영양 육묘장, 2026-08-26 19:47):

    편차 vpd = −0.0        목표 0.64 에 도달
    냉방기 100%  근거 = PRIMARY  var = vpd

낮에 VPD 가 목표보다 높아 냉방기 적분이 100% 까지 감겼고, VPD 가 목표로
내려와 편차가 부호를 넘은 순간 그 100% 가 굳었다. 그 시점의 냉방기는 VPD 를
**내리는** 쪽이다(모델 실측: `cooler → vpd ↓0.484`, 제습 효과는 모델에 없다).
즉 목표에서 멀어지는 방향으로 100% 를 밀고 있었다.

**목표에 도달했다는 사실이 잘못된 출력을 고정한 것이다.** 그리고 스스로
풀리지 않는다 — 데드존을 벗어날 만큼 나빠져야 비로소 구동이 선다.

## 왜 한 사이클로 판단하지 않나

데드존이 존재하는 이유가 **센서 잡음**이다. 잡음은 사이클마다 부호가
뒤집히므로, 한 사이클의 부호로 물러나면 데드존을 만든 이유가 그대로
사라진다(야간 창호 진동이 정확히 그 실패였다). 그래서 연속으로 같은 쪽일
때만 물러나고, 한 번이라도 되돌아오면 횟수는 0 이다.

단위가 초가 아니라 **사이클**인 것도 같은 이유다 — 여기서 거르는 것은
시간이 아니라 표본이다.
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    DEADZONE_BACKOFF_CYCLES, CoordinatorState, coordinate,
)
from aot.functions.utils.env_control.log_channels import (
    REASON_DEADZONE_BACKOFF, REASON_PRIMARY,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, deviation, context=None):
        self.target = {'vpd': TargetVar(value=0.64, tolerance=0.1,
                                        priority=1.2, unit='kPa')}
        self.deviation_native = deviation
        self.context = context or {'cycle_sec': 600.0}


def _cooler():
    """모델대로 — 냉방기는 VPD 를 **내린다**(제습 효과가 모델에 없다)."""
    return ActuatorProfile(
        actuator_id='cooler', kind='cooler',
        effect_model={'vpd': _effect('↓', 0.484)},
        cost_fn=lambda env, pct: 5.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)


def _run(devs, profile=None):
    """편차 수열을 그대로 먹인다 → [(pct, reason), …]"""
    p = profile or _cooler()
    st = CoordinatorState()
    st.prev_commands = {p.actuator_id: 100.0}
    st.integral      = {p.actuator_id: 100.0}
    out = []
    for d in devs:
        cmds, st = coordinate(_Situation({'vpd': d}), [p], st, unique_id='t')
        c = cmds[p.actuator_id]
        out.append((round(c.control_value(), 1), c.reason))
    return out, st


# 데드존 반폭 = tolerance × HOLD_FRAC = 0.05.
# −0.02 는 데드존 **안**이면서 부호가 반대인 자리 — 실측이 있던 바로 그 자리.
_WRONG = -0.02


class TestTheFrozenRail:
    """실측 재현 — 이 검사가 없던 동안 냉방기가 100% 로 굳어 있었다."""

    def test_it_holds_before_the_threshold(self):
        """잡음 한두 번으로 물러나면 데드존을 만든 이유가 사라진다."""
        rows, _ = _run([_WRONG] * (DEADZONE_BACKOFF_CYCLES - 1))
        assert all(r == REASON_PRIMARY for _pct, r in rows), rows
        assert all(pct == 100.0 for pct, _r in rows), rows

    def test_it_backs_off_at_the_threshold(self):
        rows, _ = _run([_WRONG] * DEADZONE_BACKOFF_CYCLES)
        pct, reason = rows[-1]
        assert reason == REASON_DEADZONE_BACKOFF, rows
        assert pct < 100.0, '부호가 반대인 채 굳어 있다 — %r' % (rows,)

    def test_it_keeps_coming_down(self):
        """한 번 내리고 마는 것이 아니라 safe_default 로 수렴해야 한다."""
        rows, _ = _run([_WRONG] * 12)
        pcts = [pct for pct, _r in rows]
        assert pcts[-1] < 5.0, pcts
        assert pcts == sorted(pcts, reverse=True), '단조 감소가 아니다: %r' % pcts

    def test_the_reason_is_not_primary(self):
        """1(PRIMARY)은 "지금 이 편차가 이 값을 시킨다" 는 뜻이다.

        여기서는 **아무도 밀고 있지 않다** — 뭉치면 화면이 "적정 VPD 인데
        냉방 100%" 를 PRIMARY 라고 설명하게 된다(사용자가 본 그 화면이다).
        """
        rows, _ = _run([_WRONG] * DEADZONE_BACKOFF_CYCLES)
        assert rows[-1][1] != REASON_PRIMARY


class TestNoiseDoesNotTriggerIt:
    """데드존이 있는 이유가 잡음이다 — 그것으로 물러나면 안 된다."""

    def test_alternating_sign_never_backs_off(self):
        rows, _ = _run([_WRONG, +0.02] * 10)
        assert all(r == REASON_PRIMARY for _pct, r in rows), rows

    def test_one_return_resets_the_count(self):
        """한 번이라도 되돌아오면 처음부터 다시 센다."""
        devs = ([_WRONG] * (DEADZONE_BACKOFF_CYCLES - 1) + [+0.02]
                + [_WRONG] * (DEADZONE_BACKOFF_CYCLES - 1))
        rows, _ = _run(devs)
        assert all(r == REASON_PRIMARY for _pct, r in rows), rows

    def test_the_right_side_holds_as_before(self):
        """부호가 맞으면 예전 그대로 hold 다 — 이 변경으로 평형이 흔들리면 안 된다."""
        rows, _ = _run([+0.02] * 10)
        assert all((pct, r) == (100.0, REASON_PRIMARY) for pct, r in rows), rows

    def test_dead_centre_holds(self):
        """정확히 0 은 '넘어갔다' 가 아니다 — 어느 쪽도 아니다."""
        rows, _ = _run([0.0] * 10)
        assert all(r == REASON_PRIMARY for _pct, r in rows), rows


class TestItOnlyAppliesInsideTheDeadzone:

    def test_outside_the_deadzone_the_normal_law_runs(self):
        """밖에서는 P·I 가 일한다 — 여기서 가로채면 제어가 통째로 바뀐다."""
        rows, _ = _run([-0.5] * DEADZONE_BACKOFF_CYCLES)
        assert all(r != REASON_DEADZONE_BACKOFF for _pct, r in rows), rows

    def test_leaving_and_returning_does_not_inherit_the_count(self):
        """데드존 밖에 있던 사이클이 횟수를 이어받으면 돌아오자마자 물러난다."""
        devs = [_WRONG] * (DEADZONE_BACKOFF_CYCLES - 1) + [-0.5] + [_WRONG]
        rows, _ = _run(devs)
        assert rows[-1][1] != REASON_DEADZONE_BACKOFF, rows


class TestScreensConvergeToTheirOwnRest:
    """물러남은 '닫기' 가 아니라 **safe_default 로 수렴**이다.

    보온커빈·차광막은 `safe_default=100`(걷힘)이라, 닫는 것으로 구현하면
    스크린이 반대로 움직인다.
    """

    def test_a_screen_relaxes_upward(self):
        screen = ActuatorProfile(
            actuator_id='curtain', kind='curtain',
            effect_model={'vpd': _effect('↓', 0.3)},
            cost_fn=lambda env, pct: 1.0,
            cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
            gains={'kp': 1.0, 'ki': 0.2}, safe_default=100.0)
        st = CoordinatorState()
        st.prev_commands = {'curtain': 20.0}
        st.integral      = {'curtain': 20.0}
        last = None
        for _ in range(DEADZONE_BACKOFF_CYCLES + 3):
            cmds, st = coordinate(_Situation({'vpd': _WRONG}), [screen], st,
                                  unique_id='t')
            last = cmds['curtain']
        assert last.reason == REASON_DEADZONE_BACKOFF
        assert last.control_value() > 20.0, '스크린이 반대로 움직인다'


class TestStateWiring:
    """카운터가 사이클을 넘어 이어지는가 — 끊기면 영영 안 찬다."""

    def test_the_counter_survives_the_cycle(self):
        _rows, st = _run([_WRONG] * (DEADZONE_BACKOFF_CYCLES - 1))
        assert st.deadzone_wrong_side.get('cooler') == \
            DEADZONE_BACKOFF_CYCLES - 1

    def test_the_counter_is_not_carried_when_the_path_is_not_taken(self):
        """복사해 들고 다니면 데드존을 벗어났다 돌아온 장치가 옛 횟수를
        이어받아 한 사이클 만에 물러난다."""
        _rows, st = _run([_WRONG, _WRONG, -0.5])
        assert not st.deadzone_wrong_side

    def test_the_greybox_path_carries_it_too(self):
        """MPC 경로는 `CoordinatorState` 를 새로 만든다 — 거기서 빠뜨리면
        매 사이클 0 에서 다시 세어 **영영 물러나지 않는다.**"""
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl \
            import _cycle_mixin as m
        src = inspect.getsource(m)
        for i, block in enumerate(src.split('CoordinatorState(')[1:], 1):
            assert 'deadzone_wrong_side' in block[:800], (
                '%d번째 CoordinatorState 생성이 카운터를 안 넘긴다' % i)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
