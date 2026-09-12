# coding=utf-8
"""같은 비용(같은 kind) 액추에이터 2개의 부하분담 대칭 수렴 회귀 테스트.

## 재현된 결함 (aot-005, 2026-09)

천창(kind='opening') 2개가 같은 코디네이터 안에 있고, 내부 온도 편차가 거의
없는데도 한쪽 0% · 한쪽 100% 로 완전히 갈린 채 수십 사이클 동안 고착됐다.

근본 원인:
  1. `_build_cost_fn` 이 kind 별로 base_cost=5.0 고정값을 써서, 같은 kind 의
     두 액추에이터는 cost_fn 이 항상 동일한 값을 반환한다.
  2. Python `sorted` 는 안정정렬 — 동률이면 원래 리스트 순서를 유지한다.
     그래서 두 천창 중 하나가 매 사이클 항상 먼저 처리됐다.
  3. 루프 안에서 먼저 처리된 천창의 물리효과가 `accum` 에 즉시 반영되어,
     뒤에 처리되는 천창은 잔여편차가 거의 0 인 "평형 근방" 으로 빠져
     직전 상태(0%)를 그대로 유지했다.

## 수정 (d0bda60a 후속, tier 그룹화)

`coordinate()` 내부에서 비용 동률 액추에이터들을 하나의 tier 로 묶어,
묶음 안 모든 멤버가 **묶음 시작 전 accum 스냅숏**을 공통으로 보고 계산한다.
묶음 전체 처리 후 물리효과를 accum 에 한꺼번에 반영한다.

## 핵심 설계 근거

tier 수정이 공평하게 하는 것은 **잔여편차(accum 기반)** 뿐이다.
각 액추에이터의 적분(I) — "기억된 평형 개도" — 은 per-actuator 히스토리이므로
tier 안에서도 독립적으로 유지된다. 따라서:

  - 같은 초기 I 를 가진 두 액추에이터는 첫 사이클부터 **완전히 같은 명령**을 낸다.
  - 다른 초기 I 를 가진 두 액추에이터는 P+I 가 달라 즉시 대칭이 되지 않는다.
    그러나 **같은 잔여편차를 보고 같은 방향으로 적분을 쌓아** 결국 수렴한다.
    수정 전: 뒤에 처리되는 창은 잔여편차=0 을 보고 평형분기로 빠져 고착.
    수정 후: 뒤에 처리되는 창도 같은 잔여편차를 보고 같은 방향으로 움직인다.

## 테스트 목록

  TestSameCostTierSymmetry      — 핵심 회귀: 동일 초기 상태 → 완전 대칭
  TestTierFairResidue           — 두 번째 처리 창이 잔여편차 0을 보지 않는다
  TestDifferentCostTiers        — 비용이 다른 묶음 사이 부하분담은 기존대로
  TestSingleActuatorUnchanged   — 묶음이 1개면 기존 동작과 동일
  TestTierContract              — tier 코드가 소스에 존재하는지 구조 검사
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    CoordinatorState,
    coordinate,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile,
    CmdConstraints,
    EffectResult,
    TargetVar,
)


# ─────────────────────────────────────────────────────────────────────────────
# 공통 픽스처 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _effect(direction: str, magnitude: float):
    """단순 비례 EffectResult 팩토리."""
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    """coordinate() 가 요구하는 최소 SituationReport 흉내."""
    def __init__(self, target, deviation, context=None):
        self.target = target
        self.deviation_native = deviation
        self.context = context or {'cycle_sec': 600.0}


def _opening(aid: str, magnitude: float = 2.0, cost: float = 5.0,
             direction: str = '↑') -> ActuatorProfile:
    """천창(kind='opening') 프로파일 — cost 기본값 5.0 은 실제 _build_cost_fn 과 일치."""
    return ActuatorProfile(
        actuator_id=aid,
        kind='opening',
        effect_model={'temperature': _effect(direction, magnitude)},
        cost_fn=lambda env, pct, _c=cost: _c,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2},
        safe_default=0.0,
    )


# 내부 온도 20 °C · 목표 24 °C(허용 1.0) → +4 °C 필요.
_TARGET = {'temperature': TargetVar(value=24.0, tolerance=1.0,
                                    priority=1.0, unit='C')}
_DEV    = {'temperature': -4.0}          # current − target = −4

_CTX = {'cycle_sec': 600.0, 'vent_futility_gate': False}


def _run(profiles, state, dev=None, ctx=None):
    sit = _Situation(_TARGET, dev or _DEV, ctx or _CTX)
    return coordinate(sit, profiles, state, unique_id='test')


# ─────────────────────────────────────────────────────────────────────────────
# 1. 핵심 회귀 — 동일 초기 상태에서 완전 대칭
# ─────────────────────────────────────────────────────────────────────────────

class TestSameCostTierSymmetry:
    """수정의 핵심: 같은 초기 상태 → 첫 사이클부터 완전히 같은 명령.

    수정 전 버그: 같은 초기 상태에서도 먼저 처리된 창이 accum에 기여를 쌓아
    두 번째 창의 잔여편차를 줄여버렸다. 그 결과 첫 사이클부터 비대칭이었다.

    수정 후: accum_snapshot 공유로 두 창이 동일한 잔여편차를 보고 동일한
    e_norm을 계산하므로, 같은 I에서 시작하면 완전히 같은 명령이 나온다.
    """

    def _cycle(self, state):
        r = _opening('ridge_L', magnitude=2.0)
        l = _opening('ridge_R', magnitude=2.0)
        return _run([r, l], state)

    def test_동일_초기_첫_사이클_완전_대칭(self):
        """수정의 직접 검증: 같은 I에서 시작하면 첫 사이클부터 같은 명령.

        수정 전: ridge_L(먼저 처리) = 58.45%, ridge_R(나중 처리) = 38.93%
        수정 후: ridge_L = ridge_R (동일 잔여편차 → 동일 e_norm → 동일 P+I)
        """
        state = CoordinatorState()
        state.prev_commands = {'ridge_L': 0.0, 'ridge_R': 0.0}
        state.integral      = {'ridge_L': 0.0, 'ridge_R': 0.0}

        cmds, _ = self._cycle(state)
        v_L = cmds['ridge_L'].control_value()
        v_R = cmds['ridge_R'].control_value()

        assert abs(v_L - v_R) < 0.01, (
            f'같은 초기 상태인데 명령이 다르다: ridge_L={v_L:.2f}% ridge_R={v_R:.2f}%\n'
            '수정 전 버그: 먼저 처리된 창이 accum을 독식해 두 번째 창이 잔여편차≈0 을 봤다.')

    def test_리스트_순서_바꿔도_동일_결과(self):
        """순서를 바꾸면 버그가 어느 쪽에서 나타나는지 달라진다 — 양방향 모두 같아야 한다."""
        state_fwd = CoordinatorState()
        state_fwd.prev_commands = {'ridge_L': 0.0, 'ridge_R': 0.0}
        state_fwd.integral      = {'ridge_L': 0.0, 'ridge_R': 0.0}

        state_rev = CoordinatorState()
        state_rev.prev_commands = {'ridge_L': 0.0, 'ridge_R': 0.0}
        state_rev.integral      = {'ridge_L': 0.0, 'ridge_R': 0.0}

        r = _opening('ridge_L', magnitude=2.0)
        l = _opening('ridge_R', magnitude=2.0)

        cmds_fwd, _ = _run([r, l], state_fwd)    # L 먼저
        cmds_rev, _ = _run([l, r], state_rev)    # R 먼저

        for aid in ('ridge_L', 'ridge_R'):
            fwd = cmds_fwd[aid].control_value()
            rev = cmds_rev[aid].control_value()
            assert abs(fwd - rev) < 0.01, (
                f'{aid}: 순서 정방향={fwd:.2f}%, 역방향={rev:.2f}% 로 달라진다\n'
                'accum_snapshot 이 순서에 의존하고 있다.')

    def test_비대칭_적분은_둘_다_REASON_PRIMARY_로_움직인다(self):
        """초기 I가 다르더라도 두 창 모두 REASON_PRIMARY 분기를 거쳐 적분이 변해야 한다.

        수정 전 버그: 두 번째 창은 잔여편차≈0 을 보고 e_eff=0 평형분기로 빠져
        적분이 완전히 동결(freeze)됐다. 즉 REASON_PRIMARY 가 아닌
        평형/데드존 분기를 탔다.

        수정 후: accum_snapshot 공유로 두 창이 같은 잔여편차(-4 °C)를 보므로
        둘 다 REASON_PRIMARY 로 동작하고 적분이 변한다.
        적분이 올라갈지 내려갈지는 anti-windup·포화에 달려 있어 방향을 단정하지
        않는다 — 중요한 것은 "동결되지 않는다"는 것이다.
        """
        from aot.functions.utils.env_control.log_channels import REASON_PRIMARY

        state = CoordinatorState()
        state.prev_commands = {'ridge_L': 0.0, 'ridge_R': 50.0}
        state.integral      = {'ridge_L': 0.0, 'ridge_R': 50.0}

        r = _opening('ridge_L', magnitude=2.0)
        l = _opening('ridge_R', magnitude=2.0)

        cmds, new_state = _run([r, l], state)

        # 두 창 모두 REASON_PRIMARY 로 동작해야 한다.
        assert cmds['ridge_L'].reason == REASON_PRIMARY, (
            f'ridge_L reason={cmds["ridge_L"].reason}\n'
            '수정 전 버그: 잔여편차≈0 으로 e_eff=0 평형분기에 빠졌다.')
        assert cmds['ridge_R'].reason == REASON_PRIMARY, (
            f'ridge_R reason={cmds["ridge_R"].reason}')

        # 적분이 동결되지 않았음 — 방향은 포화/anti-windup에 따라 달라질 수 있다.
        I_L_before = state.integral['ridge_L']     # 0.0
        I_L_after  = new_state.integral['ridge_L']
        assert I_L_after != I_L_before, (
            f'ridge_L 적분이 전혀 변하지 않았다 '
            f'(before={I_L_before:.2f} after={I_L_after:.2f})\n'
            '수정 전 버그: 평형분기로 빠져 적분이 동결됐다.')

    def test_같은_적분_여러_사이클_대칭_유지(self):
        """초기가 같으면 계속 같아야 한다."""
        state = CoordinatorState()
        state.prev_commands = {'ridge_L': 40.0, 'ridge_R': 40.0}
        state.integral      = {'ridge_L': 40.0, 'ridge_R': 40.0}

        for _ in range(5):
            cmds, state = self._cycle(state)

        v_L = cmds['ridge_L'].control_value()
        v_R = cmds['ridge_R'].control_value()
        assert abs(v_L - v_R) < 0.01, (
            f'대칭 초기인데 비대칭으로 갈라졌다: L={v_L:.2f}% R={v_R:.2f}%')


# ─────────────────────────────────────────────────────────────────────────────
# 2. 잔여편차 공정성 직접 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestTierFairResidue:
    """tier 안에서 두 번째 처리 창이 첫 번째 창의 기여를 보지 않아야 한다.

    이것이 수정의 본질이다 — accum_snapshot 을 공유하므로
    두 번째 창이 보는 잔여편차 = 원래 편차 (첫 번째 기여 제외).
    """

    def test_작은_편차에서_둘_다_REASON_PRIMARY(self):
        """수정 전: 두 번째 창이 잔여편차≈0 을 보고 REASON_PRIMARY 가 아닌
        REASON_NO_GRADIENT 또는 e_eff=0 평형분기로 빠졌다.
        수정 후: 둘 다 같은 편차를 보고 REASON_PRIMARY 로 동작해야 한다.
        """
        from aot.functions.utils.env_control.log_channels import REASON_PRIMARY

        r = _opening('ridge_L', magnitude=2.0)
        l = _opening('ridge_R', magnitude=2.0)

        state = CoordinatorState()
        state.prev_commands = {'ridge_L': 0.0, 'ridge_R': 0.0}
        state.integral      = {'ridge_L': 0.0, 'ridge_R': 0.0}

        # 편차가 작지만 데드존 경계 밖 — 수정 전이라면 두 번째 창이 잔여편차≈0 으로
        # REASON_NO_GRADIENT 나 평형 freeze 로 빠진다.
        # pband = 3×1=3, HOLD_FRAC/PBAND_MULT≈0.033, e_norm(첫창)=2/(3×2)≈0.33
        # 첫 창의 물리기여: 0.33×kp_scale × magnitude × slew → accum에 누적
        # 두 번째 창(수정전): residual≈0 → e_norm≈0 → e_eff=0 → 평형고착
        sit = _Situation(_TARGET, {'temperature': -1.5}, _CTX)
        cmds, _ = coordinate(sit, [r, l], state, unique_id='test')

        reason_L = cmds['ridge_L'].reason
        reason_R = cmds['ridge_R'].reason

        assert reason_L == REASON_PRIMARY, (
            f'ridge_L reason={reason_L}, REASON_PRIMARY 여야 한다')
        assert reason_R == REASON_PRIMARY, (
            f'ridge_R reason={reason_R}, REASON_PRIMARY 여야 한다\n'
            '수정 전 버그: 잔여편차≈0 으로 e_eff=0 평형분기에 빠졌다.')

    def test_같은_초기_같은_명령_수치(self):
        """accum_snapshot 공유의 직접 결과: 같은 잔여편차 → 같은 e_norm → 같은 cmd."""
        r = _opening('ridge_L', magnitude=2.0)
        l = _opening('ridge_R', magnitude=2.0)

        state = CoordinatorState()
        state.prev_commands = {'ridge_L': 20.0, 'ridge_R': 20.0}
        state.integral      = {'ridge_L': 20.0, 'ridge_R': 20.0}

        cmds, _ = _run([r, l], state)
        assert cmds['ridge_L'].control_value() == pytest.approx(
            cmds['ridge_R'].control_value(), abs=0.01)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 비용이 다른 묶음 사이 부하분담은 기존대로
# ─────────────────────────────────────────────────────────────────────────────

class TestDifferentCostTiers:
    """저비용 tier 가 편차를 해소하면 고비용 tier 는 적게 동작해야 한다.

    이것은 d0bda60a 의 의도된 동작이다 — tier 그룹화 후에도 유지돼야 한다.
    """

    def _profiles(self, cheap_cost=2.0, expensive_cost=9.0):
        cheap     = _opening('vent',   magnitude=5.0, cost=cheap_cost)
        expensive = _opening('heater', magnitude=5.0, cost=expensive_cost)
        return cheap, expensive

    def test_저비용이_편차를_충분히_해소하면_고비용은_거의_0(self):
        """저비용 tier 가 편차를 전부 흡수할 만큼 크면 고비용 tier 는 idle 이어야 한다."""
        cheap, expensive = self._profiles()

        state = CoordinatorState()
        state.prev_commands = {'vent': 0.0, 'heater': 0.0}
        state.integral      = {'vent': 0.0, 'heater': 0.0}

        # 작은 편차 — 저비용 환기 하나로도 충분히 해소 가능
        sit = _Situation(_TARGET, {'temperature': -1.0}, _CTX)
        cmds, _ = coordinate(sit, [cheap, expensive], state, unique_id='test')

        v_cheap     = cmds['vent'].control_value()
        v_expensive = cmds['heater'].control_value()

        assert v_cheap > v_expensive, (
            f'저비용(vent={v_cheap:.1f}%)이 고비용(heater={v_expensive:.1f}%)보다 '
            '높아야 한다 — 비용 다른 tier 간 부하분담이 깨졌다')

    def test_저비용_단독으로_부족하면_고비용도_동원된다(self):
        """매우 큰 편차 — 저비용만으로 부족할 때 고비용도 켜져야 한다."""
        cheap, expensive = self._profiles()

        state = CoordinatorState()
        state.prev_commands = {'vent': 80.0, 'heater': 0.0}
        state.integral      = {'vent': 80.0, 'heater': 0.0}

        sit = _Situation(_TARGET, {'temperature': -10.0}, _CTX)
        cmds, _ = coordinate(sit, [cheap, expensive], state, unique_id='test')

        v_expensive = cmds['heater'].control_value()
        assert v_expensive > 0.0, (
            f'저비용만으로 부족한데 고비용(heater={v_expensive:.1f}%)이 켜지지 않았다')

    def test_저비용_묶음_안도_대칭(self):
        """같은 저비용 tier 2개 + 고비용 1개 — 저비용끼리 같은 초기면 동일 명령."""
        cheap_a = _opening('vent_a', magnitude=5.0, cost=2.0)
        cheap_b = _opening('vent_b', magnitude=5.0, cost=2.0)
        expensive = _opening('heater', magnitude=5.0, cost=9.0)

        state = CoordinatorState()
        state.prev_commands = {'vent_a': 0.0, 'vent_b': 0.0, 'heater': 0.0}
        state.integral      = {'vent_a': 0.0, 'vent_b': 0.0, 'heater': 0.0}

        sit = _Situation(_TARGET, {'temperature': -1.0}, _CTX)
        cmds, _ = coordinate(sit, [cheap_a, cheap_b, expensive], state, unique_id='test')

        v_a = cmds['vent_a'].control_value()
        v_b = cmds['vent_b'].control_value()
        assert abs(v_a - v_b) < 0.01, (
            f'같은 저비용 tier 안에서 비대칭: vent_a={v_a:.2f}% vent_b={v_b:.2f}%')


# ─────────────────────────────────────────────────────────────────────────────
# 4. 묶음이 1개일 때 기존 동작과 동일
# ─────────────────────────────────────────────────────────────────────────────

class TestSingleActuatorUnchanged:
    """액추에이터가 1개뿐인 경우 tier 로직이 개입해도 결과가 달라지지 않아야 한다."""

    def test_단일_액추에이터_명령_정상(self):
        r = _opening('single', magnitude=2.0)

        state = CoordinatorState()
        state.prev_commands = {'single': 0.0}
        state.integral      = {'single': 0.0}

        cmds, _ = _run([r], state)
        v = cmds['single'].control_value()

        assert v > 0.0, '단일 액추에이터가 명령을 받지 못했다'
        assert v <= 100.0

    def test_세_천창_중_하나가_비용_다르면_같은_묶음끼리_대칭(self):
        """cost 2개(같은 묶음 2개 + 다른 묶음 1개) — 같은 묶음끼리 같은 초기면 대칭."""
        a = _opening('a', magnitude=2.0, cost=5.0)
        b = _opening('b', magnitude=2.0, cost=5.0)   # a 와 같은 tier
        c = _opening('c', magnitude=2.0, cost=9.0)   # 별도 tier

        state = CoordinatorState()
        # a, b 초기 상태 동일
        state.prev_commands = {'a': 0.0, 'b': 0.0, 'c': 0.0}
        state.integral      = {'a': 0.0, 'b': 0.0, 'c': 0.0}

        cmds, _ = _run([a, b, c], state)
        v_a = cmds['a'].control_value()
        v_b = cmds['b'].control_value()

        assert abs(v_a - v_b) < 0.01, (
            f'같은 tier, 같은 초기(a={v_a:.2f}%, b={v_b:.2f}%) 가 같아야 한다')


# ─────────────────────────────────────────────────────────────────────────────
# 5. 구조 계약 — tier 로직이 코드에 존재하는지 소스 검사
# ─────────────────────────────────────────────────────────────────────────────

class TestTierContract:
    """tier 그룹화가 coordinator.py 소스에 실제로 있는지 확인한다.

    동작 테스트만으로는 로직이 우연히 통과하는 경우를 구분하기 어렵다.
    소스 검사를 병행해 구조적 보장을 명시한다.
    """

    def _src(self):
        import inspect
        from aot.functions.utils.env_control import coordinator as c
        return inspect.getsource(c.coordinate)

    def test_tier_그룹화_코드_존재(self):
        assert 'tiers' in self._src(), \
            'coordinate() 에 tier 그룹화 코드가 없다'

    def test_accum_snapshot_존재(self):
        assert 'accum_snapshot' in self._src(), \
            'tier 스냅숏(accum_snapshot) 이 없다 — 묶음 안에서 순차 갱신이 일어난다'

    def test_tier_effect_deltas_존재(self):
        assert 'tier_effect_deltas' in self._src(), \
            'tier_effect_deltas 가 없다 — 묶음 끝 일괄 반영이 없다'

    def test_math_isclose_사용(self):
        assert 'math.isclose' in self._src(), \
            '동률 판정에 math.isclose 를 쓰지 않는다'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
