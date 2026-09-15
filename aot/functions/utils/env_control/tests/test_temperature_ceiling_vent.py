# coding=utf-8
"""VPD 를 제어하는 중에도 온도가 상한을 향해 오르면 창이 반응한다 (2026-09-14).

## 실측 (aot-005 육묘장, 2026-09-14 오전)

    08:10  실내 20.8 °C · 89 % · VPD 0.25     창 0 %  근거 '주작용'
    09:40  실내 30.5 °C · 98 % · VPD 0.08     창 0 %  근거 '주작용'
           실외 22.9 °C · 62 % · VPD 1.07     (목표 VPD ≈ 1.0)
    10:00  실내 33.7 °C                        창 0 %  (차광막만 온도 상한으로 닫힘)
    10:11  사람이 창을 강제로 연 뒤            VPD 1.3 · 27 °C

결함이 둘이었다.

1. **개구부 VPD 효과의 방향이 반대였다.** 습도 효과를 상대습도 차로, 온도와
   다른 계수로 계산해 "실외가 더 차다" 만으로 환기 = VPD 하강이 나왔다.
2. **온도가 창을 움직일 수단이 없었다.** VPD 모드에서는 온도가 제어목표에서
   빠지고, 하드 상한은 난방 끄기·차광막 닫기만 한다.
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, _temperature_ceiling, _ventilation_is_futile, coordinate,
)
from aot.functions.utils.env_control.effect_functions import (
    _vpd_gap, build_effect_model,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 개구부 VPD 효과 — 실외 VPD 쪽으로
# ─────────────────────────────────────────────────────────────────────────────

class _Window:
    kind = 'opening'
    area_m2 = 10.0
    capacity_meta = {}

    def __init__(self, form=None):
        self.vent_form = form


# (실내T, 실내RH, 실외T, 실외RH) — 2026-09-14 aot-005 기상대 실측
_MORNING = [
    (24.1, 86.9, 19.6, 76.7),
    (24.6, 91.0, 21.6, 67.5),
    (26.9, 95.8, 22.5, 62.8),
    (30.0, 96.8, 22.9, 61.7),
    (32.9, 95.4, 24.1, 58.4),
]


@pytest.mark.parametrize('form', ['side', 'ridge', None])
@pytest.mark.parametrize('t_in,rh_in,t_out,rh_out', _MORNING)
def test_실외가_차고_건조하면_환기는_vpd_를_올린다(form, t_in, rh_in, t_out, rh_out):
    """회귀의 본체 — 수정 전에는 다섯 시각 전부 ↓ 였다."""
    env = {'T_int': t_in, 'RH_int': rh_in, 'T_ext': t_out, 'RH_ext': rh_out,
           'wind': 0.5}
    eff = build_effect_model('opening', {})['vpd'](env, 100.0, _Window(form))
    assert _vpd_gap(env) > 0
    assert eff.direction == '↑'
    assert 0.0 < eff.magnitude_native <= _vpd_gap(env) + 1e-9


def test_실외_vpd_가_낮으면_환기는_vpd_를_내린다():
    env = {'T_int': 28.0, 'RH_int': 50.0, 'T_ext': 20.0, 'RH_ext': 95.0,
           'wind': 0.5}
    eff = build_effect_model('opening', {})['vpd'](env, 100.0, _Window('side'))
    assert _vpd_gap(env) < 0
    assert eff.direction == '↓'


def test_닫힌_창은_vpd_를_못_옮긴다():
    env = {'T_int': 30.0, 'RH_int': 96.8, 'T_ext': 22.9, 'RH_ext': 61.7}
    eff = build_effect_model('opening', {})['vpd'](env, 0.0, _Window('side'))
    assert eff.magnitude_native == 0.0


def test_배기팬도_같은_규칙을_따른다():
    """opening 만 고치고 팬을 빠뜨리면 그쪽으로 샌다."""
    env = {'T_int': 30.0, 'RH_int': 96.8, 'T_ext': 22.9, 'RH_ext': 61.7,
           'vent_open_frac': 0.0}
    eff = build_effect_model('exhaust_fan', {})['vpd'](env, 100.0, None)
    assert eff.direction in ('↑', '0')


def test_난방기는_여전히_연쇄법칙이다():
    """실외를 지나칠 수 있는 장치는 끝점 모델을 쓰지 않는다."""
    env = {'T_int': 30.0, 'RH_int': 96.8, 'T_ext': 22.9, 'RH_ext': 61.7}
    eff = build_effect_model('heater', {})['vpd'](env, 100.0, None)
    assert eff.direction == '↑' and eff.magnitude_native > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. 코디네이터 — 온도 상한
# ─────────────────────────────────────────────────────────────────────────────

def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, target, deviation, context):
        self.target = target
        self.deviation_native = deviation
        self.context = context


def _profile(aid, kind, temp_dir='↓', temp_mag=2.0, vpd_dir='↓', vpd_mag=0.1):
    return ActuatorProfile(
        actuator_id=aid, kind=kind,
        effect_model={'temperature': _effect(temp_dir, temp_mag),
                      'vpd': _effect(vpd_dir, vpd_mag)},
        cost_fn=lambda env, pct: 5.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2},
        safe_default=0.0,
    )


# VPD 모드 — 온도는 deviation 에 없다. VPD 0.13 · 목표 1.0 → 올려야 한다.
_TARGET = {'vpd': TargetVar(value=1.0, tolerance=0.1, priority=1.2, unit='kPa')}
_DEV = {'vpd': -0.87}


def _ctx(**kw):
    ctx = {'cycle_sec': 600.0, 'vent_futility_gate': False,
           'T_int': 30.5, 'T_trend': 0.18, 'T_ceiling': 27.0, 'temp_max': 32.0}
    ctx.update(kw)
    return ctx


def _run(profiles, ctx):
    cmds, _ = coordinate(_Situation(_TARGET, dict(_DEV), ctx), profiles,
                         CoordinatorState(), unique_id='test')
    return cmds


class TestVentRespondsToTemperature:

    def test_상한이_없으면_예전처럼_vpd_가_창을_닫아_둔다(self):
        """대조군 — 온도 상한 정보가 없으면 VPD 만 보고 닫는다(수정 전 동작)."""
        ctx = _ctx(T_ceiling=None, temp_max=None)
        assert _run([_profile('w', 'opening')], ctx)['w'].value == 0.0

    def test_유도_상한을_넘어_오르면_창이_열린다(self):
        """09:40 재현 — VPD 가 닫자고 해도 온도가 이긴다."""
        cmd = _run([_profile('w', 'opening')], _ctx())['w']
        assert cmd.value > 0.0
        assert cmd.var_source == 'temperature'

    def test_아직_선_아래고_오르지도_않으면_개입하지_않는다(self):
        ctx = _ctx(T_int=24.0, T_trend=0.0)
        assert _run([_profile('w', 'opening')], ctx)['w'].value == 0.0

    def test_상승률로_미리_반응한다(self):
        """지금은 선 아래지만 다음 결정 시점에는 넘는다."""
        assert _temperature_ceiling(
            _Situation(_TARGET, _DEV, {}), _ctx(T_int=25.5, T_trend=0.18),
            600.0) is not None
        assert _temperature_ceiling(
            _Situation(_TARGET, _DEV, {}), _ctx(T_int=25.5, T_trend=0.0),
            600.0) is None

    def test_실외가_더_더우면_창을_열지_않는다(self):
        """환기가 데우는 쪽이면 온도 항은 오히려 닫는 쪽이다."""
        p = _profile('w', 'opening', temp_dir='↑', vpd_dir='↑')
        assert _run([p], _ctx(T_int=33.0))['w'].value == 0.0

    def test_하드_상한에서는_맞서는_vpd_항이_빠진다(self):
        """유도 상한 = 하드 상한이라 초과분이 작아도 반응해야 한다."""
        p = _profile('w', 'opening', vpd_mag=1.0)
        ctx = _ctx(T_int=32.2, T_trend=0.0, T_ceiling=32.0, temp_max=32.0)
        assert _run([p], ctx)['w'].value > 0.0

    def test_냉방기는_하드_상한에서만_온도를_본다(self):
        """공짜로 식힐 수 있는 환기가 먼저다."""
        # 유도 상한(27)만 넘고 하드 상한(32)에는 한참 먼 조건 — 예상 온도가
        # 32 에 닿으면 하드다(기본 _ctx 는 30.5 + 1.8 = 32.3 이라 하드에 걸린다).
        soft = _run([_profile('c', 'cooler')], _ctx(T_int=28.0, T_trend=0.0))['c']
        hard = _run([_profile('c', 'cooler')],
                    _ctx(T_int=32.5, T_trend=0.0))['c']
        assert soft.value == 0.0
        assert hard.value > 0.0

    def test_온도가_이미_제어목표면_더하지_않는다(self):
        """VPD 없이 온도를 직접 제어할 때 이중계상하지 않는다."""
        sit = _Situation({}, {'temperature': 3.5}, {})
        assert _temperature_ceiling(sit, _ctx(), 600.0) is None


class TestFutilityGateSeesTemperature:

    def test_식힐_수_있으면_무익이_아니다(self):
        p = _profile('w', 'opening')
        p.live_effect = {'temperature': EffectResult('↓', 2.0),
                         'vpd': EffectResult('↓', 0.1)}
        sit = _Situation(_TARGET, dict(_DEV), {})
        assert _ventilation_is_futile(p, sit, {'_t_ceiling': (1.0, False)}) is False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
