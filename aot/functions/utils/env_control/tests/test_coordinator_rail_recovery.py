# coding=utf-8
"""레일(0%/100%)에 눌러붙은 적분의 회복 경로 회귀.

적분(`CoordinatorState.integral`)은 정의상 **평형 개도 기억**이다 — 이
액추에이터가 평형에서 서 있어야 할 자리(%). 그런데 포화 중에는 그 뜻이
깨진다.

  아래쪽 레일(u<0): back-calculation `I -= (u−c)·β` 가 I 를 **위로** 민다.
                    요구값 −P 가 100 을 넘으면 상한에 눌러붙어 굳는다.
  위쪽 레일(u>100): 대칭으로 I 가 아래로 깎여 0 근처까지 내려간다.

둘 다 dispatch 와 정반대 값이 남는다. 편차가 풀리는 순간 `cmd = P + I` 의 I 가
통째로 계단으로 튀어나온다.

실제로 두 번 났다:
  * 2026-07-29 aot-005 — 폭염 중 dispatch 100% 인데 I 는 0 근처로 깎여 있었고,
    무구배로 전환되는 순간 보온커튼이 급락(오폐쇄)했다.
  * 2026-08-20 로컬 육묘장 — 냉방 I 가 100 에 굳은 채 몇 시간을 버텼다.
    (그때 명령을 붙잡고 있던 것은 I 가 아니라 P 였지만, I 는 계단으로 남아 있었다.)

회복 경로: 직전 dispatch 가 이미 그 레일이면(=한 사이클 이상 눌러붙어 있었다)
적분을 **실제 개도 쪽으로** 기하 감쇠시킨다. 포화 직후 한 사이클은 종전대로
back-calculation 에 맡긴다.
"""

import pytest

from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, RAIL_EPS, RELAX_FACTOR, coordinate,
)
from aot.functions.utils.env_control.situation import assess
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)

AID = 'a'


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


# ⚠ **맞서는 짝(냉방·난방)을 쓰지 않는다** (2026-08-26).
# 이 파일이 재현하려는 것은 "아래쪽 레일에 눌러붙은 적분" 인데, 그 상황은
# 냉방기를 **추운 조건에서** 돌려야 만들어진다. 그런데 코디네이터는 이제 온도
# 축의 요구 방향으로 짝의 한쪽을 후보에서 빼므로(`coordinate` 2.55절), 추운
# 조건의 냉방기는 파킹되어 레일에 닿지 못한다 — 그것이 옳은 동작이고, 그래서
# 여기서는 짝이 아닌 **증발냉각(fogger)** 으로 같은 경로를 재현한다.
# 레일 회복 로직 자체는 종류를 가리지 않는다.
def _profile(kind='fogger', direction='↓', magnitude=2.5, slew=20.0):
    return ActuatorProfile(
        actuator_id=AID,
        kind=kind,
        effect_model={'temperature': _effect(direction, magnitude)},
        cost_fn=lambda env, pct: 3.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=slew, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2},
        safe_default=0.0,
    )


def _step(state, T_int, T_target, i, profile=None):
    """한 사이클 — (새 state, dispatch 개도) 반환."""
    p = profile or _profile()
    target = {'temperature': TargetVar(value=T_target, tolerance=1.0, priority=1.0)}
    report, _ = assess(
        target,
        {'T': T_int, 'RH': 65.0, 'CO2': 600.0},
        {'T': T_int, 'RH': 65.0, 'wind': 1.0, 'rain': 0.0, 'solar': 0.0},
        cycle_sec=60.0, now_ts=1767240000.0 + i * 60,
    )
    cmds, new_state = coordinate(report, [p], state)
    ap = cmds[AID].control_value()
    new_state.prev_commands = {AID: ap}
    return new_state, ap


def _run(state, T_int, T_target, n, start=0, profile=None):
    """n 사이클 — (마지막 state, [적분 이력], [개도 이력])."""
    integrals, apertures = [], []
    for i in range(n):
        state, ap = _step(state, T_int, T_target, start + i, profile)
        integrals.append(state.integral[AID])
        apertures.append(ap)
    return state, integrals, apertures


# 실내가 목표보다 한참 차가움 → 냉각 장치는 완전히 닫아야 한다(아래쪽 레일).
COLD = dict(T_int=15.0, T_target=25.0)
# 실내가 목표보다 한참 더움 → 냉각 장치 최대(위쪽 레일).
HOT  = dict(T_int=40.0, T_target=20.0)


class TestLowerRailRecovery:
    def test_integral_decays_toward_the_rail_it_is_stuck_on(self):
        """아래쪽 레일에 눌러붙으면 적분이 0 으로 수렴한다.

        예전에는 back-calculation 이 매 사이클 I 를 상한으로 되밀어 100 에서
        굳었다.
        """
        st = CoordinatorState(prev_commands={AID: 100.0}, integral={AID: 100.0})
        st, integrals, apertures = _run(st, n=20, **COLD)
        assert apertures[-1] == pytest.approx(0.0)
        assert integrals[-1] < 1.0, '적분이 레일에서 풀리지 않았다: %.2f' % integrals[-1]

    def test_decay_is_geometric_once_parked_on_the_rail(self):
        """레일에 닿은 뒤에는 RELAX_FACTOR 비율로 감쇠한다.

        정확히 그 비율은 아니다 — 사이클마다 `I += ki·e_eff` 가 **먼저** 돌고
        그 결과에 감쇠가 걸린다. 편차가 클수록 그 몫이 조금 더 깎는다.
        """
        st = CoordinatorState(prev_commands={AID: 0.0}, integral={AID: 100.0})
        st, integrals, apertures = _run(st, n=4, **COLD)
        assert apertures[0] == pytest.approx(0.0)
        ratios = [b / a for a, b in zip([100.0] + integrals, integrals)]
        for r in ratios:
            assert r < RELAX_FACTOR + 1e-9      # ki 항이 더 깎기만 한다
            assert r == pytest.approx(RELAX_FACTOR, abs=0.03)

    def test_recovery_completes_in_about_ten_cycles(self):
        """37시간이 아니라 십여 사이클 안에 끝난다."""
        st = CoordinatorState(prev_commands={AID: 0.0}, integral={AID: 100.0})
        st, integrals, _ = _run(st, n=15, **COLD)
        first_under_1 = next(i for i, v in enumerate(integrals) if v < 1.0)
        assert first_under_1 <= 12, '%d 사이클 걸렸다' % first_under_1


class TestUpperRailRecovery:
    def test_integral_converges_to_full_not_zero(self):
        """위쪽 레일에서는 적분이 100 으로 수렴한다.

        2026-07-29 aot-005 회귀 — dispatch 는 100% 인데 I 만 0 근처로 깎이면,
        무구배로 전환되는 순간 명령이 급락한다. 그 괴리 자체를 없앤다.
        """
        st = CoordinatorState(prev_commands={AID: 100.0}, integral={AID: 0.0})
        st, integrals, apertures = _run(st, n=15, **HOT)
        assert apertures[-1] == pytest.approx(100.0)
        assert integrals[-1] > 99.0, (
            'dispatch 100%% 인데 적분이 %.1f — 계단이 남아 있다' % integrals[-1])

    def test_integral_tracks_dispatch_not_the_opposite_rail(self):
        """포화가 길어질수록 적분과 실제 개도의 괴리가 줄어든다."""
        st = CoordinatorState(prev_commands={AID: 100.0}, integral={AID: 0.0})
        st, integrals, apertures = _run(st, n=10, **HOT)
        gaps = [abs(i - a) for i, a in zip(integrals, apertures)]
        assert all(a >= b for a, b in zip(gaps, gaps[1:])), gaps


class TestBackCalculationStillRunsFirst:
    def test_first_saturated_cycle_uses_back_calculation(self):
        """갓 포화된 사이클은 회복 경로가 아니라 back-calculation 이 처리한다.

        직전 개도가 레일에서 멀면(아직 도달 전) 빠른 anti-windup 을 유지한다.
        """
        st = CoordinatorState(prev_commands={AID: 100.0}, integral={AID: 100.0})
        st, integrals, apertures = _run(st, n=1, **COLD)
        assert apertures[0] == pytest.approx(80.0)      # slew 로 내려오는 중
        assert integrals[0] == pytest.approx(100.0)     # 감쇠 아직 없음

    def test_brief_saturation_does_not_trigger_the_relax(self):
        """레일에 닿지 못한 짧은 포화에서는 회복 경로가 돌지 않는다.

        이때 적분이 그대로인 것은 아니다 — 아래쪽 레일의 back-calculation 은
        I 를 **위로** 민다(그게 종전 동작이고, 여기서는 그대로 둔다). 확인할
        것은 "레일 쪽으로 감쇠하지 않았다" 는 것이다.
        """
        st = CoordinatorState(prev_commands={AID: 50.0}, integral={AID: 80.0})
        st, integrals, apertures = _run(st, n=2, **COLD)
        assert all(a > RAIL_EPS for a in apertures), apertures
        assert all(v >= 80.0 for v in integrals), integrals


class TestRecoveryIsProportional:
    def test_no_phantom_step_when_the_deviation_reverses(self):
        """회복 뒤 편차가 반대로 서면 명령이 **편차에 비례**해 돌아온다.

        회복 경로가 없으면 굳어 있던 I(=100)가 통째로 더해져, 편차가 17% 만
        요구하는데 명령이 100% 까지 걸어 올라간다.
        """
        # 한참 닫혀 있다가(아래쪽 레일에서 회복) …
        st = CoordinatorState(prev_commands={AID: 100.0}, integral={AID: 100.0})
        st, _, _ = _run(st, n=20, **COLD)
        assert st.integral[AID] < 1.0

        # … 더워져 냉방이 조금 필요해진다. 편차 +1.5°C, 허용오차 1.0.
        # e_norm = 1.5/6 = 0.25, 데드존 0.0833 → e_eff = 0.1667 → P ≈ 16.7%
        st, _, apertures = _run(st, T_int=26.5, T_target=25.0, n=6, start=100)
        assert apertures[-1] == pytest.approx(16.7, abs=1.0)
        assert max(apertures) < 30.0, '유령 계단이 남아 있다: %s' % apertures

    def test_stale_integral_still_overshoots_without_recovery(self):
        """대조군 — 회복을 못 거친 굳은 적분은 편차가 정당화하는 것보다 훨씬 높다.

        위 `test_no_phantom_step_…` 이 공허하지 않다는 것을 고정한다. 같은 편차
        (P ≈ 16.7%)인데 굳은 적분이 남아 있으면 개도가 그 몇 배까지 간다.

        ⚠ 2026-08-26 상한이 100 → 약 54 로 내려갔다. **회복 경로가 약해진 것이
        아니라 막는 수단이 하나 늘었다** — 슬루 되먹임(적분을 실제로 나간 개도로
        back-calculate)이 같은 허구를 다른 자리에서 함께 깎는다. 여기서 보는
        것은 절대값이 아니라 "편차가 정당화하는 수준을 넘는가" 이므로, 형제
        테스트의 문턱(30%)을 기준으로 삼는다.
        """
        st = CoordinatorState(prev_commands={AID: 0.0}, integral={AID: 100.0})
        # 감쇠가 돌지 않도록 포화되지 않는 완만한 편차만 준다.
        st, _, apertures = _run(st, T_int=26.5, T_target=25.0, n=6)
        assert max(apertures) > 30.0, (
            '굳은 적분이 아무 영향도 못 준다 — 형제 테스트가 공허해졌다: %s'
            % apertures)


class TestInvariants:
    def test_integral_stays_within_bounds(self):
        for scenario in (COLD, HOT):
            st = CoordinatorState(prev_commands={AID: 50.0}, integral={AID: 50.0})
            st, integrals, _ = _run(st, n=25, **scenario)
            assert all(0.0 <= v <= 100.0 for v in integrals), integrals

    def test_unsaturated_cycles_are_untouched(self):
        """포화가 없으면 적분은 종전대로 ki·e_eff 로만 움직인다."""
        st = CoordinatorState(prev_commands={AID: 20.0}, integral={AID: 20.0})
        st, integrals, apertures = _run(st, T_int=26.5, T_target=25.0, n=4)
        assert all(0.0 < a < 100.0 for a in apertures), apertures
        deltas = [b - a for a, b in zip([20.0] + integrals, integrals)]
        assert all(abs(d) < 0.2 for d in deltas), deltas

    def test_rail_epsilon_is_tight(self):
        """레일 판정 허용오차가 느슨해지면 정상 개도까지 감쇠 대상이 된다."""
        assert 0.0 < RAIL_EPS <= 1.0
