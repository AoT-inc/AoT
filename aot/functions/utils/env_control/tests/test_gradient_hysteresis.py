# coding=utf-8
"""유효도 문턱(G_MIN_EFFECT)은 이력을 갖는다 (2026-09-30).

문턱 하나로 '구동력 있음/없음' 을 가르면 g 가 문턱 근처에서 오르내릴 때 판정이
사이클마다 뒤집힌다. 뒤집힐 때마다 무구배 경로가 명령과 적분을 깎고 PI 가 그
자리에서 다시 출발해 톱니가 된다 — 실측(로컬 3포장, 갱신 60초): 측창이 100→0→70→0 %.
g 가 0.018~0.034 로 문턱(0.025) 양쪽에 걸려 있었고 근거가 1↔15 로 분 단위 반복.

고친 뒤의 규칙:
  · 없던 장치는 g ≥ G_MIN_EFFECT 여야 '있음' 이 된다(종전과 같다).
  · 있던 장치는 g < G_MIN_EFFECT × GRADIENT_EXIT_FRAC 가 돼야 '없음' 이 된다.
  · 진짜 무구배(g≈0.01)는 이력 폭 아래라 종전처럼 걸러진다.
"""
from aot.functions.utils.env_control.coordinator import (
    G_MIN_EFFECT, GRADIENT_EXIT_FRAC, CoordinatorState, coordinate,
)
from aot.functions.utils.env_control.log_channels import (
    REASON_NO_GRADIENT, REASON_PRIMARY,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)

_PBAND = 6.0                                  # PBAND_MULT × tolerance(1.0)
_TARGET = {'temperature': TargetVar(value=24.0, tolerance=1.0,
                                    priority=1.0, unit='C')}
_DEV = {'temperature': -4.0}                  # 4 °C 올려야 한다


class _Situation:
    def __init__(self, ctx):
        self.target = _TARGET
        self.deviation_native = _DEV
        self.context = ctx


def _vent(g):
    """100 % 에서 유효도가 정확히 g 인 개구부."""
    def fn(env, cmd_pct, profile=None):
        return EffectResult('↑', g * _PBAND * (cmd_pct / 100.0))
    return ActuatorProfile(
        actuator_id='v', kind='opening', effect_model={'temperature': fn},
        cost_fn=lambda env, pct: 5.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)


def _run(gs, start_active=False, prev=40.0):
    state = CoordinatorState()
    state.prev_commands = {'v': prev}
    state.integral = {'v': prev}
    if start_active:
        state.gradient_active = {'v': True}
    reasons = []
    for g in gs:
        cmds, state = coordinate(_Situation({'cycle_sec': 60.0}),
                                 [_vent(g)], state, unique_id='t')
        reasons.append(cmds['v'].reason)
    return reasons, state


class TestHysteresis:
    def test_문턱_근처에서_흔들려도_판정이_뒤집히지_않는다(self):
        """실측 재현 — g 가 0.018~0.034 를 오간다."""
        gs = [0.034, 0.018, 0.026, 0.020, 0.030, 0.018, 0.024, 0.031]
        reasons, _ = _run(gs, start_active=True)
        assert set(reasons) == {REASON_PRIMARY}, reasons

    def test_문턱_위에서_시작하면_같은_흔들림에도_유지된다(self):
        reasons, _ = _run([0.040, 0.020, 0.030, 0.019, 0.022])
        assert reasons[0] == REASON_PRIMARY
        assert set(reasons) == {REASON_PRIMARY}, reasons

    def test_진짜_무구배는_종전처럼_걸러진다(self):
        gs = [0.040, 0.010, 0.009, 0.010]
        reasons, _ = _run(gs)
        assert reasons[0] == REASON_PRIMARY
        assert reasons[1:] == [REASON_NO_GRADIENT] * 3, reasons

    def test_이력_폭은_문턱의_절반이다(self):
        assert GRADIENT_EXIT_FRAC == 0.5
        just_above = G_MIN_EFFECT * GRADIENT_EXIT_FRAC * 1.05
        just_below = G_MIN_EFFECT * GRADIENT_EXIT_FRAC * 0.95
        assert _run([just_above], start_active=True)[0] == [REASON_PRIMARY]
        assert _run([just_below], start_active=True)[0] == [REASON_NO_GRADIENT]

    def test_없던_장치의_진입_문턱은_종전과_같다(self):
        """이력은 나가는 문턱만 낮춘다 — 처음 켜지는 문턱은 그대로다."""
        assert _run([G_MIN_EFFECT * 0.9])[0] == [REASON_NO_GRADIENT]
        assert _run([G_MIN_EFFECT * 1.1])[0] == [REASON_PRIMARY]

    def test_없음으로_떨어진_뒤에는_문턱을_넘어야_다시_켜진다(self):
        gs = [0.040, 0.010, 0.020, 0.020, 0.030]
        reasons, _ = _run(gs)
        assert reasons == [REASON_PRIMARY, REASON_NO_GRADIENT,
                           REASON_NO_GRADIENT, REASON_NO_GRADIENT,
                           REASON_PRIMARY], reasons

    def test_상태는_새_상태로_이어진다(self):
        _, state = _run([0.040])
        assert state.gradient_active == {'v': True}
        _, state = _run([0.040, 0.005])
        assert state.gradient_active == {'v': False}
