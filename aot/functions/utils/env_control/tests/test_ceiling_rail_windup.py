# coding=utf-8
"""하드 온도 상한이 개구부를 아래쪽 레일로 누르는 동안 적분이 부풀지 않는다.

## 실측 (2026-09-19 로컬 섀도 실행, 温室環境制御, DB 사본)

하드 상한을 인위적으로 걸자(`temp_max=1.0` → `_force_cool` 래치) 실외가 29 °C 로
실내보다 더워 개구부 둘이 **닫히는** 쪽으로 갔다(0 %·10 %). 그런데 같은 사이클에
적분은 0.0→100.0, 3.53→100.0 으로 튀었다. 다음 정상 사이클에서 방향 전환
되앉힘이 겨우 되돌렸다(100→2.5 / 100→24.6).

원인은 '갓 포화' 분기의 back-calculation `I −= (u − c)·β` 였다. 온도 상한 항이
P 를 크게 음으로 만들면(u ≪ 0) 이 식은 I 를 **위로** 민다 — 교과서적으로는
P + I 를 레일에 맞추는 동작이지만, 이 코드의 적분은 '기억된 평형 개도(%)' 라
장치가 0 % 인데 I 가 100 이라는 것은 뜻이 없다.

방향 전환이 되돌려 준 것은 운이다. 상한이 풀린 뒤에도 **같은 방향**(조금 더
닫아라)이면 되앉힘이 안 돌고, `cmd = P + 100` 이 창을 **연다** — 요구와 반대다.
위쪽 레일에도 대칭 경로가 있다(식히려고 여는 중에 I 가 깎인다). 다만 0 아래로는
못 가므로 피해가 들어올 때 값까지로 묶인다 — 아래쪽처럼 0→100 이 되지는 않는다.

그래서 아래쪽 레일의 갓 포화는 **조건부 적분**이다 — 막힌 방향으로 가는 이번
사이클의 누적도, 슬루 되먹임도 버린다. 포화가 적분에 **새로 더하는 것이 없다.**

⚠ '적분 ≤ 실제 개도' 로 매 사이클 되앉히지 않는다. 그러면 들어올 때 갖고 있던
평형 기억까지 지워, 강한 외란이 잠깐 창을 닫았다 풀린 뒤 ki(사이클당 0.2 %)로
처음부터 다시 쌓아야 한다 — 합성 폐루프 A/B 에서 100 사이클 넘게 2.6 °C 벗어난
채 고착됐다. 그래서 여기서 고정하는 불변식은 둘이다.

  * 포화가 적분을 **올리지 않는다** — 들어올 때 값 이하.
  * 들어올 때 이미 실제 개도 이하였다면(섀도 실행이 그랬다) 레일에 있는 동안
    실제 개도를 넘지 않는다.

위쪽 레일은 종전 back-calculation 그대로다(같은 A/B 에서 동결하면 짧은 고온
스파이크 뒤 회복이 나빠졌다). 그래서 이 파일은 아래쪽 레일만 고정한다.
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, target, deviation, context):
        self.target = target
        self.deviation_native = deviation
        self.context = context


def _vent(aid, temp_dir, vpd_dir='↑', slew=10.0):
    """개구부. temp_dir='↑' = 실외가 더 더워 열면 데워진다(식히려면 닫는다)."""
    return ActuatorProfile(
        actuator_id=aid, kind='opening',
        effect_model={'temperature': _effect(temp_dir, 2.0),
                      'vpd': _effect(vpd_dir, 0.1)},
        cost_fn=lambda env, pct: 5.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=slew, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2},
        safe_default=0.0,
    )


# VPD 모드 — 온도는 deviation 에 없다(`_decompose_vpd` 가 뺀다).
_TARGET = {'vpd': TargetVar(value=1.0, tolerance=0.1, priority=1.2, unit='kPa')}


def _ceiling_ctx(kind):
    """하드 상한이 걸린 사이클의 ctx.

    artificial — 섀도 실행 재현: temp_max=1.0 이라 유도 상한도 1 로 좁혀지고
                 초과분이 약 28 °C, P 가 수백 % 다.
    realistic  — 실제로 날 수 있는 크기: 하드 32 °C 를 4 °C 넘었다.
                 초과분 5 °C, P ≈ −54 % 로 이것만으로도 레일에 닿는다.
    """
    base = {'cycle_sec': 60.0, 'vent_futility_gate': False, 'T_trend': 0.0}
    if kind == 'artificial':
        base.update(T_int=28.0, T_ceiling=1.0, temp_max=1.0,
                    internal={'_force_cool': True})
    else:
        base.update(T_int=36.0, T_ceiling=32.0, temp_max=32.0)
    return base


def _released_ctx():
    """상한이 풀린 사이클 — 온도 상한 항이 없다."""
    return {'cycle_sec': 60.0, 'vent_futility_gate': False, 'T_trend': 0.0,
            'T_int': 25.0, 'T_ceiling': None, 'temp_max': 32.0}


def _step(profiles, state, ctx, vpd_dev):
    cmds, new_state = coordinate(
        _Situation(_TARGET, {'vpd': vpd_dev}, dict(ctx)), profiles, state,
        unique_id='test')
    aps = {aid: c.control_value() for aid, c in cmds.items()}
    new_state.prev_commands = dict(aps)
    return new_state, aps


# 섀도 실행의 두 개구부. 한쪽은 이번 사이클에 0 까지 닿고(슬루 여유),
# 다른 쪽은 슬루에 막혀 10 % 에서 멈춘다.
_A, _B = 'bf73', '5f27'
_OBSERVED = CoordinatorState(prev_commands={_A: 8.0, _B: 20.0},
                             integral={_A: 0.0, _B: 3.53})

# 상한 동안 VPD 는 올려야 한다(창을 여는 쪽) — 하드 상한이 그것을 이겨 닫는다.
_VPD_WANTS_OPEN = -0.87
# 풀린 뒤 VPD 가 약간 높다 — 여전히 '조금 더 닫아라'. 방향 전환이 없어
# 되앉힘이 돌지 않으므로 쌓인 적분이 그대로 드러나는 경우다.
_VPD_WANTS_CLOSE = +0.3


def _clone(st):
    return CoordinatorState(prev_commands=dict(st.prev_commands),
                            integral=dict(st.integral),
                            drive_sign=dict(st.drive_sign))


@pytest.fixture(params=['artificial', 'realistic'])
def ceiling(request):
    return _ceiling_ctx(request.param)


class TestLowerRailUnderHardCeiling:
    """실외가 더 더워 식히려면 닫아야 한다 — 아래쪽 레일."""

    def _profiles(self):
        return [_vent(_A, '↑'), _vent(_B, '↑')]

    def test_재현_한_사이클에_적분이_실제_개도를_넘지_않는다(self, ceiling):
        st, aps = _step(self._profiles(), _clone(_OBSERVED), ceiling,
                        _VPD_WANTS_OPEN)
        assert aps[_A] == pytest.approx(0.0)
        assert aps[_B] == pytest.approx(10.0)     # 슬루에 막혀 닫히는 중
        for aid in (_A, _B):
            assert st.integral[aid] <= aps[aid] + 1e-9, (
                '%s: 개도 %.1f %% 인데 적분 %.1f' % (aid, aps[aid], st.integral[aid]))

    def test_상한이_이어지는_동안_적분이_오르지_않는다(self, ceiling):
        """레일에 붙어 있는 내내 — 포화는 적분에 아무것도 더하지 않는다.

        들어올 때 기억(3.53)은 남는다. 레일에 **계속** 붙으면 레일 회복 경로가
        그것을 실제 개도(0) 쪽으로 감쇠시킨다 — 그래서 '≤ 실제 개도' 가 아니라
        '≤ max(실제 개도, 들어올 때 값)' 이고, 단조 비증가다.
        """
        st = _clone(_OBSERVED)
        entry = dict(_OBSERVED.integral)
        prev_I = dict(entry)
        for _ in range(6):
            st, aps = _step(self._profiles(), st, ceiling, _VPD_WANTS_OPEN)
            for aid in (_A, _B):
                I = st.integral[aid]
                assert I <= prev_I[aid] + 1e-9, ('적분이 올랐다', aid, prev_I[aid], I)
                assert I <= max(aps[aid], entry[aid]) + 1e-9, (aid, aps[aid], I)
            prev_I = {aid: st.integral[aid] for aid in (_A, _B)}
        assert aps == {_A: pytest.approx(0.0), _B: pytest.approx(0.0)}
        assert st.integral[_B] < entry[_B], '레일 회복 감쇠가 돌지 않았다'

    def test_풀린_첫_사이클이_같은_방향이면_창을_열지_않는다(self, ceiling):
        """섀도 실행에서 운 좋게 피한 쪽 — 풀린 뒤에도 '더 닫아라' 인 경우.

        수정 전: I=100 이 그대로 남아 `cmd = P + 100` 이 창을 열었다.
        """
        st, aps = _step(self._profiles(), _clone(_OBSERVED), ceiling,
                        _VPD_WANTS_OPEN)
        _, after = _step(self._profiles(), st, _released_ctx(), _VPD_WANTS_CLOSE)
        for aid in (_A, _B):
            assert after[aid] <= aps[aid] + 1e-9, (
                '%s: 닫으라는데 %.1f → %.1f' % (aid, aps[aid], after[aid]))

    @pytest.mark.parametrize('vpd_after', [_VPD_WANTS_CLOSE, _VPD_WANTS_OPEN])
    def test_풀린_첫_사이클은_상한이_없던_것처럼_이어진다(self, ceiling, vpd_after):
        """bumpless — 상한은 적분에 흔적을 남기지 않는다.

        상한을 겪은 제어기와, 상한 사이클을 **건너뛰었지만** 장치는 같은 자리에
        서 있는 제어기(같은 평형 기억)가 풀린 첫 사이클에 같은 명령을 낸다.
        열라는 쪽은 수정 전에도 방향 전환 되앉힘 덕에 통과했다. 닫으라는 쪽이
        수정 전 실패하던 경우다(I=100 이 `cmd = P + I` 로 튀어나왔다).
        """
        st, aps = _step(self._profiles(), _clone(_OBSERVED), ceiling,
                        _VPD_WANTS_OPEN)
        _, after = _step(self._profiles(), st, _released_ctx(), vpd_after)

        skipped = CoordinatorState(prev_commands=dict(aps),
                                   integral=dict(_OBSERVED.integral),
                                   drive_sign=dict(st.drive_sign))
        _, ref = _step(self._profiles(), skipped, _released_ctx(), vpd_after)
        assert after == {aid: pytest.approx(v, abs=1e-6) for aid, v in ref.items()}


class TestNormalLowerRailIsFrozenToo:
    """상한과 무관하게 아래쪽 레일 갓 포화는 같은 규칙이다 — P 의 거울상을
    적분에 싣지 않는다."""

    def test_추워서_닫는_중_적분이_오르지_않는다(self):
        p = _vent(_A, '↓', vpd_dir='↓')          # 열면 식고 VPD 도 내린다
        target = {'temperature': TargetVar(value=25.0, tolerance=1.0, priority=1.0)}
        st = CoordinatorState(prev_commands={_A: 60.0}, integral={_A: 60.0})
        for _ in range(3):
            cmds, new = coordinate(
                _Situation(target, {'temperature': -8.0},
                           {'cycle_sec': 60.0, 'T_int': 17.0}),
                [p], st, unique_id='test')
            ap = cmds[_A].control_value()
            assert new.integral[_A] <= st.integral[_A] + 1e-9, (
                st.integral[_A], new.integral[_A])
            new.prev_commands = {_A: ap}
            st = new
        assert ap == pytest.approx(30.0)            # 슬루 10 으로 닫히는 중
        assert st.integral[_A] == pytest.approx(60.0)   # 평형 기억은 그대로
