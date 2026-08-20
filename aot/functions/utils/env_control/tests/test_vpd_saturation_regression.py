# coding=utf-8
"""포화 공기(RH≈100%, VPD=0)에서 VPD 제어가 죽던 회귀 + 부하분담 부호 회귀.

2026-08-20 로컬 육묘장에서 관측된 상태를 고정한다.

    실내 24.34 °C / RH 100% / VPD 0.00,  VPD 목표 0.49 kPa
    → 난방기 0%, **냉방기 100%**, 분무 64.9% 로 고착

VPD 를 올리려면 가열해야 하는데 정반대로 돌고 있었고, 원인이 서로 독립된
두 결함이었다.

1. `(1 − RH/100)` 인자 — VPD→온도 역산(`_invert_svp_for_T`)과 유도 VPD
   효과(`make_vpd_effect`)가 **온도를 바꾸는 동안 RH 가 그대로**라고 가정했다.
   물을 넣지 않는 한 성립하지 않는 가정이고, RH=100 에서 인자가 0 이 되어
   "가열은 VPD 를 못 바꾼다" 는 결론이 나왔다. 역산은 뉴턴법 df=0 으로 첫 회에
   탈출하며 기준 온도를 그대로 돌려줘 **온도 편차가 0** 이 됐다.
   보존되는 것은 RH 가 아니라 수증기압 ea 다.

2. 부하분담 부호 — `residual = deviation − accumulated` 라 앞 장비가 낸 효과가
   뒤 장비에 **반대 부호 편차**로 넘어갔다. 분무의 모델상 −29.6 °C 가 냉방기에
   +29.6 °C("29.6도 덥다")로 전달돼 편차 0 인 축에서 냉방이 100% 로 켜졌다.

두 결함은 겹쳐 있었다 — 1번이 온도 요구를 0 으로 비우고, 그 자리를 2번이 만든
가짜 편차가 채웠다. 그래서 양쪽을 따로 고정한다.
"""

import math

import pytest

from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate,
)
from aot.functions.utils.env_control.effect_functions import (
    DEFAULT_EFFECT_MODELS, make_vpd_effect,
)
from aot.functions.utils.env_control.situation import (
    _invert_svp_for_T, assess, compute_vpd, decompose_vpd_to_T_RH, svp,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)

from .conftest import make_ctx

# 사고 당시 상태 (function_runtime_state 스냅샷)
T_INC   = 24.34
RH_INC  = 100.0
VPD_TGT = 0.49


def _ea(T, RH):
    """수증기압 [kPa]."""
    return RH / 100.0 * svp(T)


# ─────────────────────────────────────────────────────────────────────────────
# 1-A. VPD → 온도 역산
# ─────────────────────────────────────────────────────────────────────────────

class TestInversionAtSaturation:
    def test_saturated_air_still_has_a_reachable_temperature(self):
        """RH=100% 에서도 VPD 목표를 만족하는 온도가 존재하고, 그것을 찾아낸다.

        옛 구현은 뉴턴법 df=0 으로 첫 회에 탈출해 기준 온도를 그대로 돌려줬다.
        """
        T_needed = _invert_svp_for_T(VPD_TGT, RH_INC, T_ref=T_INC)
        assert T_needed > T_INC, '포화 상태에서 가열 목표가 나와야 한다'
        assert T_needed == pytest.approx(26.86, abs=0.05)

    def test_returned_temperature_actually_reaches_the_target(self):
        """찾은 온도로 (ea 고정) 가열하면 실제로 목표 VPD 가 된다 — 검산."""
        T_needed = _invert_svp_for_T(VPD_TGT, RH_INC, T_ref=T_INC)
        vpd_after = svp(T_needed) - _ea(T_INC, RH_INC)
        assert vpd_after == pytest.approx(VPD_TGT, abs=1e-6)

    def test_never_returns_the_reference_temperature_when_target_unmet(self):
        """목표에 도달하지 않은 상태라면 기준 온도를 그대로 돌려주지 않는다.

        기준 온도가 그대로 나오면 호출부에서 '온도 편차 0' 이 되어 난방·냉방
        요구가 통째로 사라진다. 그것이 이 사고의 형태였다.
        """
        for RH in (100.0, 99.9, 95.0, 80.0, 50.0):
            got = _invert_svp_for_T(VPD_TGT, RH, T_ref=T_INC)
            assert abs(got - T_INC) > 1e-6, f'RH={RH} 에서 기준 온도를 반환했다'

    def test_inversion_is_continuous_across_saturation(self):
        """RH 100 근방에서 연속이어야 한다.

        옛 구현은 RH=100 → 24.34(무동작), RH=99.9 → 50.0(상한 클램프)로 튀어
        '아무것도 안 함'과 '최대 가열' 사이에 중간이 없었다.
        """
        vals = [_invert_svp_for_T(VPD_TGT, rh, T_ref=T_INC)
                for rh in (100.0, 99.9, 99.0, 98.0)]
        for a, b in zip(vals, vals[1:]):
            assert abs(a - b) < 0.5, f'RH 0.1~1%p 차이에 온도가 {a}→{b} 로 튀었다'

    def test_preserves_vapor_pressure_not_relative_humidity(self):
        """역산이 고정하는 양은 ea 다 — RH 가 아니다."""
        T_needed = _invert_svp_for_T(VPD_TGT, 70.0, T_ref=T_INC)
        assert _ea(T_INC, 70.0) == pytest.approx(svp(T_needed) - VPD_TGT, rel=1e-9)


class TestDecomposeAtSaturation:
    def test_produces_a_heating_demand(self):
        """포화 상태 + VPD 목표 → 온도 보조목표가 현재보다 **높다**.

        이 값이 현재 온도와 같으면 난방기 편차가 0 이 되어 가열이 영영 없다.
        """
        T_aux, RH_aux = decompose_vpd_to_T_RH(VPD_TGT, T_INC, RH_INC, w_T=0.6)
        assert T_aux > T_INC + 0.5
        assert T_aux == pytest.approx(25.85, abs=0.05)
        assert RH_aux < RH_INC          # 제습 요구도 함께 남는다
        assert RH_aux == pytest.approx(85.29, abs=0.05)

    def test_both_axes_satisfy_the_vpd_constraint(self):
        """분해 결과 (T_aux, RH_aux) 는 목표 VPD 를 정확히 만족한다."""
        T_aux, RH_aux = decompose_vpd_to_T_RH(VPD_TGT, T_INC, RH_INC, w_T=0.6)
        assert compute_vpd(T_aux, RH_aux) == pytest.approx(VPD_TGT, abs=1e-3)

    def test_w_T_zero_leaves_temperature_alone(self):
        """w_T=0 이면 온도는 안 움직인다 — 포화 상태에서도 마찬가지."""
        T_aux, RH_aux = decompose_vpd_to_T_RH(VPD_TGT, T_INC, RH_INC, w_T=0.0)
        assert T_aux == pytest.approx(T_INC)
        assert RH_aux < RH_INC

    def test_weight_scales_the_heating_demand(self):
        """w_T 가 클수록 온도 요구가 크다 (단조)."""
        temps = [decompose_vpd_to_T_RH(VPD_TGT, T_INC, RH_INC, w_T=w)[0]
                 for w in (0.0, 0.3, 0.6, 1.0)]
        assert all(a < b for a, b in zip(temps, temps[1:]))


# ─────────────────────────────────────────────────────────────────────────────
# 1-B. 유도 VPD 효과 (make_vpd_effect)
# ─────────────────────────────────────────────────────────────────────────────

# 증발 가용도가 1.0 인 습도 (`_EVAP_REF_RH` 이하) — 유량 자체를 재는 시험용.
EVAP_OK_RH = 60.0


def _env(T=T_INC, RH=RH_INC):
    return {'T_int': T, 'RH_int': RH, 'T_ext': T, 'RH_ext': RH,
            'CO2_int': 600.0, 'CO2_ext': 400.0,
            'cycle_sec': 60.0, 'solar': 0.0, 'wind': 0.5}


class TestVpdEffectAtSaturation:
    def test_heater_raises_vpd_at_saturation(self):
        """RH=100% 에서도 난방기의 VPD 효과는 '↑' 이고 0 이 아니다.

        옛 식은 ∂VPD/∂T 에 (1−RH/100)=0 을 곱해 온도항을 통째로 지웠다.
        """
        eff = DEFAULT_EFFECT_MODELS['heater']['vpd'](_env(), 100.0, None)
        assert eff.direction == '↑'
        assert eff.magnitude_native > 0.3

    def test_cooler_lowers_vpd_at_saturation(self):
        eff = DEFAULT_EFFECT_MODELS['cooler']['vpd'](_env(), 100.0, None)
        assert eff.direction == '↓'
        assert eff.magnitude_native > 0.3

    def test_heater_effect_matches_constant_ea_physics(self):
        """모델값이 ea 고정 실제값과 1차 근사 오차(10%) 안에서 일치한다."""
        eff = DEFAULT_EFFECT_MODELS['heater']['vpd'](_env(), 100.0, None)
        dT = DEFAULT_EFFECT_MODELS['heater']['temperature'](_env(), 100.0, None)
        true = svp(T_INC + dT.magnitude_native) - svp(T_INC)
        assert eff.magnitude_native == pytest.approx(true, rel=0.10)

    def test_temperature_term_does_not_scale_with_humidity(self):
        """온도항은 RH 에 비례해 줄어들지 않는다.

        옛 식에서는 RH 50% 면 절반, RH 100% 면 0 이었다. 난방기는 수분을
        옮기지 않으므로 dVPD 는 RH 와 무관해야 한다.
        """
        vals = [DEFAULT_EFFECT_MODELS['heater']['vpd'](
            _env(RH=rh), 100.0, None).magnitude_native
            for rh in (30.0, 50.0, 80.0, 100.0)]
        assert max(vals) - min(vals) < 1e-9

    def test_thermal_rh_declaration_is_not_double_counted(self):
        """난방·냉방의 humidity effect 는 dea 에 더해지지 않는다.

        그 신고는 '온도가 올라서 RH 가 내려간 것'이라 dsvp·dT 항이 이미 담고
        있다. 함께 더하면 이중계상이 된다.
        """
        t_fn = DEFAULT_EFFECT_MODELS['heater']['temperature']
        h_fn = DEFAULT_EFFECT_MODELS['heater']['humidity']
        as_moisture = make_vpd_effect(t_fn, h_fn, humid_is_moisture=True)
        actual = DEFAULT_EFFECT_MODELS['heater']['vpd']
        assert (actual(_env(), 100.0, None).magnitude_native
                < as_moisture(_env(), 100.0, None).magnitude_native)

    def test_moisture_kinds_still_count_their_humidity_effect(self):
        """분무는 실제로 수분을 옮기므로 습도항이 살아 있어야 한다."""
        t_fn = DEFAULT_EFFECT_MODELS['fogger']['temperature']
        h_fn = DEFAULT_EFFECT_MODELS['fogger']['humidity']
        with_h = make_vpd_effect(t_fn, h_fn, humid_is_moisture=True)
        no_h   = make_vpd_effect(t_fn, None, humid_is_moisture=True)
        # 포화에서는 분무가 아무 효과도 없으므로(증발 가용도 0) 불포화에서 본다.
        env = _env(RH=EVAP_OK_RH)
        a = with_h(env, 100.0, None).magnitude_native
        b = no_h(env, 100.0, None).magnitude_native
        assert a != pytest.approx(b)
        # 분무는 습도항·온도항 모두 VPD 를 낮춘다
        assert with_h(env, 100.0, None).direction == '↓'


# ─────────────────────────────────────────────────────────────────────────────
# 2. 부하분담 부호 (coordinator)
# ─────────────────────────────────────────────────────────────────────────────

def _fixed_effect(direction, magnitude):
    """상태와 무관하게 고정된 효과를 신고하는 effect_fn."""
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


def _profile(actuator_id, kind, effects, cost=3.0, slew=100.0):
    return ActuatorProfile(
        actuator_id=actuator_id,
        kind=kind,
        effect_model=effects,
        cost_fn=(lambda env, pct, _c=cost: _c),
        cmd_constraints=CmdConstraints(slew_per_cycle=slew, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2},
        safe_default=0.0,
    )


def _coordinate(ctx, target, profiles, state=None):
    report, _ = assess(target, ctx['internal'], ctx['external'],
                       cycle_sec=60.0, now_ts=ctx['now_ts'])
    return coordinate(report, profiles, state or CoordinatorState())


class TestLoadSharingSign:
    def test_residual_is_a_forward_prediction(self):
        """산술 계약: 잔여 편차 = 편차 + 확정 변화량.

        편차는 current−target, accumulated 는 current 에 더해질 부호 있는
        변화량이므로 확정 후 예상 편차는 (current+accumulated)−target 이다.
        """
        deviation, accumulated = 5.0, -3.0     # 5°C 더움, 앞 장비가 3°C 낮춤
        assert deviation + accumulated == 2.0  # 남은 몫
        assert deviation - accumulated == 8.0  # 옛 코드 — 혼자일 때보다 커진다

    def test_second_cooler_does_less_than_the_first(self):
        """냉방 2대 — 뒤에 확정되는 쪽이 앞보다 적게 돈다(부하분담).

        옛 부호에서는 뒤쪽이 앞쪽보다 크거나 같아 둘 다 포화로 갔다.
        """
        ctx = make_ctx(T_int=27.0, RH_int=60.0)
        target = {'temperature': TargetVar(value=22.0, tolerance=1.0, priority=1.0)}
        cheap = _profile('cool_cheap', 'cooler',
                         {'temperature': _fixed_effect('↓', 2.5)}, cost=1.0)
        dear  = _profile('cool_dear', 'cooler',
                         {'temperature': _fixed_effect('↓', 2.5)}, cost=9.0)

        cmds, _ = _coordinate(ctx, target, [cheap, dear])
        assert cmds['cool_dear'].aperture <= cmds['cool_cheap'].aperture

    def test_peer_effect_does_not_invent_an_opposite_demand(self):
        """사고 재현 — 편차 0 인 축에서 남의 효과가 반대 장비를 켜지 않는다.

        분무가 큰 냉각을 신고하면 옛 부호에서는 그 −ΔT 가 냉방기에 +ΔT 로
        전달돼(29.6°C 더움) 온도 편차가 0 인데도 냉방 100%, 난방 0% 가 됐다.
        """
        ctx = make_ctx(T_int=24.34, RH_int=100.0)
        target = {
            # 온도는 이미 목표 — 편차 0
            'temperature': TargetVar(value=24.34, tolerance=1.0, priority=1.0),
            'humidity':    TargetVar(value=83.8, tolerance=5.0, priority=0.8),
        }
        fogger = _profile('fog', 'fogger', {
            'temperature': _fixed_effect('↓', 45.6),   # 사고 당시 모델값
            'humidity':    _fixed_effect('↑', 11.4),
        }, cost=1.0)
        cooler = _profile('cool', 'cooler', {
            'temperature': _fixed_effect('↓', 2.5),
            'humidity':    _fixed_effect('↑', 0.8),
        }, cost=5.0)
        heater = _profile('heat', 'heater', {
            'temperature': _fixed_effect('↑', 2.0),
            'humidity':    _fixed_effect('↓', 1.5),
        }, cost=5.0)

        # 사고 당시의 고착 지점에서 출발시킨다.
        state = CoordinatorState(
            prev_commands={'fog': 64.9, 'cool': 100.0, 'heat': 0.0},
            integral={'fog': 64.9, 'cool': 0.0, 'heat': 100.0},
        )
        cmds, _ = _coordinate(ctx, target, [fogger, cooler, heater], state=state)

        assert cmds['cool'].aperture < 100.0, '편차 0 인데 냉방이 최대로 남았다'
        assert cmds['cool'].aperture < cmds['fog'].aperture

    def test_load_sharing_converges_instead_of_saturating(self):
        """같은 구성을 여러 사이클 돌려도 냉방이 100% 에 고착되지 않는다."""
        ctx = make_ctx(T_int=24.34, RH_int=100.0)
        target = {
            'temperature': TargetVar(value=24.34, tolerance=1.0, priority=1.0),
            'humidity':    TargetVar(value=83.8, tolerance=5.0, priority=0.8),
        }
        fogger = _profile('fog', 'fogger', {
            'temperature': _fixed_effect('↓', 45.6),
            'humidity':    _fixed_effect('↑', 11.4),
        }, cost=1.0)
        cooler = _profile('cool', 'cooler', {
            'temperature': _fixed_effect('↓', 2.5),
            'humidity':    _fixed_effect('↑', 0.8),
        }, cost=5.0)

        state = CoordinatorState(
            prev_commands={'fog': 64.9, 'cool': 100.0},
            integral={'fog': 64.9, 'cool': 0.0},
        )
        for _ in range(10):
            cmds, state = _coordinate(ctx, target, [fogger, cooler], state=state)
            state.prev_commands = {k: c.aperture for k, c in cmds.items()}
        assert cmds['cool'].aperture < 50.0

    def test_dehumidify_never_commands_a_humidifier_up(self):
        """제습 국면에서 분무는 올라가지 않는다 (방향 가드)."""
        ctx = make_ctx(T_int=24.34, RH_int=100.0)
        target = {'humidity': TargetVar(value=83.8, tolerance=5.0, priority=1.0)}
        fogger = _profile('fog', 'fogger',
                          {'humidity': _fixed_effect('↑', 11.4)}, cost=1.0)
        state = CoordinatorState(prev_commands={'fog': 64.9},
                                 integral={'fog': 64.9})
        cmds, _ = _coordinate(ctx, target, [fogger], state=state)
        assert cmds['fog'].aperture < 64.9


# ─────────────────────────────────────────────────────────────────────────────
# 3. 두 결함이 함께 만들던 최종 증상
# ─────────────────────────────────────────────────────────────────────────────

class TestIncidentEndToEnd:
    def test_saturated_air_with_a_vpd_goal_asks_for_heat_not_cold(self):
        """VPD 0 · 목표 0.49 → 난방 요구가 서고 냉방 요구는 서지 않는다.

        1번(역산)이 온도 보조목표를 세우고, 2번(부호)이 그것을 뒤집지 않는지
        한 번에 확인한다.
        """
        T_aux, RH_aux = decompose_vpd_to_T_RH(VPD_TGT, T_INC, RH_INC, w_T=0.6)
        ctx = make_ctx(T_int=T_INC, RH_int=RH_INC)
        target = {
            'temperature': TargetVar(value=T_aux, tolerance=1.0, priority=1.0),
            'humidity':    TargetVar(value=RH_aux, tolerance=5.0, priority=0.8),
        }
        heater = _profile('heat', 'heater', {
            'temperature': _fixed_effect('↑', 2.0),
            'humidity':    _fixed_effect('↓', 1.5),
        }, cost=5.0)
        cooler = _profile('cool', 'cooler', {
            'temperature': _fixed_effect('↓', 2.5),
            'humidity':    _fixed_effect('↑', 0.8),
        }, cost=5.0)

        cmds, _ = _coordinate(ctx, target, [heater, cooler])
        assert cmds['heat'].aperture > 0.0, '가열 요구가 서야 한다'
        assert cmds['cool'].aperture == pytest.approx(0.0), '냉방이 돌면 안 된다'
        assert cmds['heat'].aperture > cmds['cool'].aperture

    def test_target_temperature_is_not_pinned_to_the_measurement(self):
        """온도 목표가 현재 온도에 붙어버리지 않는다.

        사고 당시 요약의 targets.temperature 는 24.34 로 측정값과 완전히
        같았고 deviation.temperature 는 0.0 이었다 — 그것이 난방 요구가
        사라진 형태다.
        """
        T_aux, _ = decompose_vpd_to_T_RH(VPD_TGT, T_INC, RH_INC, w_T=0.6)
        assert T_aux != pytest.approx(T_INC, abs=0.1)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 분무 증발 유량 — 관수(드립) 유량을 분무량으로 쓰던 문제
# ─────────────────────────────────────────────────────────────────────────────
#
# 같은 사고의 세 번째 성분. 노즐 정보가 없는 분무기가 `irrigation_flow_lpm`
# 폴백으로 **시설 전체 관수 유량 216 L/min**(드립 에미터 324개, 배관 508 m)을
# 물려받아, 9448 m³ 온실에서 증발냉각 45.637 °C/사이클이 나왔다. 결합 drive 에서
# 이 한 항의 가중치가 나머지의 20배가 되어 다른 축을 전부 무의미하게 만들었다.

FACILITY_VOL_M3   = 9448.35   # 실측 (육묘장)
FACILITY_IRRIG_LPM = 216.0    # 실측 — 드립 관수 총유량


class _FakeProfile:
    """capacity_meta 만 갖는 최소 프로필."""
    def __init__(self, **cap):
        self.capacity_meta = cap
        self.calibrated_K = None
        self.kind = 'fogger'


def _fog(cap, var, pct=100.0, rh=EVAP_OK_RH):
    """분무 효과 한 번 평가.

    기본 습도를 `EVAP_OK_RH` 로 두는 이유: 포화에서는 증발 가용도가 0 이라
    **유량이 무엇이든 결과가 0** 이다. 유량 배선을 재려면 증발이 되는 조건에서
    봐야 한다. 포화에서의 거동은 `TestFoggerAtSaturation` 이 따로 고정한다.
    """
    return DEFAULT_EFFECT_MODELS['fogger'][var](_env(T=23.34, RH=rh),
                                                pct, _FakeProfile(**cap))


class TestFoggerEvaporativeFlow:
    def test_no_nozzle_data_falls_back_to_the_conservative_constant(self):
        """노즐 유량 미상 → 물리 계산을 포기하고 K 상수로 떨어진다.

        지어낸 참조 유량으로 물리식을 돌리면 그 값이 실측처럼 흘러다닌다.
        """
        from aot.functions.utils.env_control.effect_functions import K_FOG_T, K_FOG_RH
        assert _fog({'volume_m3': FACILITY_VOL_M3}, 'temperature'
                    ).magnitude_native == pytest.approx(K_FOG_T)
        assert _fog({'volume_m3': FACILITY_VOL_M3}, 'humidity'
                    ).magnitude_native == pytest.approx(K_FOG_RH)

    def test_irrigation_flow_is_ignored_by_the_evaporative_model(self):
        """`irrigation_flow_lpm` 이 있어도 증발 효과는 그것을 보지 않는다.

        그 키는 투여량 환산용(VolumetricAdapter)이라 드립을 포함하고,
        액추에이터 값이 없으면 시설 합계로 폴백한다 — 증발량이 아니다.
        """
        with_irrig = _fog({'volume_m3': FACILITY_VOL_M3,
                           'irrigation_flow_lpm': FACILITY_IRRIG_LPM}, 'temperature')
        without    = _fog({'volume_m3': FACILITY_VOL_M3}, 'temperature')
        assert with_irrig.magnitude_native == pytest.approx(without.magnitude_native)
        # 사고 당시 값이 되살아나면 실패한다.
        assert with_irrig.magnitude_native < 1.0

    def test_incident_magnitude_cannot_recur(self):
        """사고 당시 45.637 °C/사이클 이 다시 나오지 않는다."""
        eff = _fog({'volume_m3': FACILITY_VOL_M3,
                    'irrigation_flow_lpm': FACILITY_IRRIG_LPM}, 'temperature')
        assert eff.magnitude_native < 5.0, (
            '분무 온도효과 %.3f °C/사이클 — 관수 유량이 다시 새어 들어왔다'
            % eff.magnitude_native)

    def test_nozzle_flow_drives_the_physics(self):
        """`fog_flow_lpm` 이 있으면 그 값으로 물리 계산한다."""
        eff = _fog({'volume_m3': FACILITY_VOL_M3, 'fog_flow_lpm': 3.0}, 'temperature')
        # ΔT = liters × L_vap / (vol × ρcp),  liters = 3 L/min × 60s /60 = 3 L
        expected = 3.0 * 2430.0 / (FACILITY_VOL_M3 * 1.21 * 1.006)
        assert eff.magnitude_native == pytest.approx(expected, rel=0.01)

    def test_flow_scales_with_command_percent(self):
        cap = {'volume_m3': FACILITY_VOL_M3, 'fog_flow_lpm': 12.0}
        full = _fog(cap, 'temperature', 100.0).magnitude_native
        half = _fog(cap, 'temperature', 50.0).magnitude_native
        assert half == pytest.approx(full / 2.0, rel=1e-6)

    def test_fogger_does_not_dominate_the_other_actuators(self):
        """분무의 온도 유효도가 냉방기를 압도하지 않는다.

        결합 drive 의 가중치는 priority × (magnitude/pband) 라, 한 액추에이터의
        magnitude 가 자릿수로 크면 그 항이 혼자 방향을 정한다.
        """
        fog_dT  = _fog({'volume_m3': FACILITY_VOL_M3,
                        'irrigation_flow_lpm': FACILITY_IRRIG_LPM}, 'temperature')
        cool_dT = DEFAULT_EFFECT_MODELS['cooler']['temperature'](_env(), 100.0, None)
        assert fog_dT.magnitude_native <= cool_dT.magnitude_native

    def test_calibrated_k_still_wins(self):
        """실측 캘리브레이션 값이 있으면 그것이 최우선이다."""
        p = _FakeProfile(volume_m3=FACILITY_VOL_M3, fog_flow_lpm=3.0)
        p.calibrated_K = {'temperature': 1.25}
        eff = DEFAULT_EFFECT_MODELS['fogger']['temperature'](
            _env(RH=EVAP_OK_RH), 100.0, p)
        assert eff.magnitude_native == pytest.approx(1.25)


class TestSprinklerFlowSplit:
    """드립은 뿌리로 간다 — 증발 유량에서 빠져야 한다."""

    def _sum(self, devices):
        from aot.aot_flask.geo.irrigation_nozzles import summarize_nozzles
        return summarize_nozzles(devices)

    def test_drip_only_has_no_evaporative_flow(self):
        s = self._sum([{'sub_type': 'drip', 'flow_lph': 40.0},
                       {'sub_type': 'drip', 'flow_lph': 40.0}])
        assert s['total_flow_lph'] == pytest.approx(80.0)
        assert s['sprinkler_flow_lph'] == pytest.approx(0.0)

    def test_mixed_counts_only_the_sprinklers(self):
        s = self._sum([{'sub_type': 'drip',      'flow_lph': 40.0},
                       {'sub_type': 'sprinkler', 'flow_lph': 6.0, 'radius_m': 0.8},
                       {'sub_type': 'sprinkler', 'flow_lph': 6.0, 'radius_m': 0.8}])
        assert s['total_flow_lph'] == pytest.approx(52.0)
        assert s['sprinkler_flow_lph'] == pytest.approx(12.0)

    def test_empty_is_zero_not_missing(self):
        s = self._sum([])
        assert s['sprinkler_flow_lph'] == 0.0


class TestEvaporativeFlowSourceIsPinned:
    """증발 유량의 출처가 조용히 관수 유량으로 되돌아가지 못하게 소스로 고정."""

    def _src(self):
        import inspect
        from aot.functions.utils.env_control import effect_functions
        return inspect.getsource(effect_functions._fog_liters)

    def test_fog_liters_never_reads_irrigation_flow(self):
        body = self._src().split('"""')[-1]      # docstring 뒤 실제 코드만
        assert 'irrigation_flow_lpm' not in body, (
            '_fog_liters 가 관수 유량을 다시 읽는다 — 드립과 시설합계 폴백이 함께 들어온다')
        assert 'fog_flow_lpm' in body

    def test_fog_liters_returns_none_when_unknown(self):
        from aot.functions.utils.env_control.effect_functions import _fog_liters
        assert _fog_liters(_env(), 100.0, _FakeProfile(volume_m3=100.0)) is None
        assert _fog_liters(_env(), 100.0, None) is None

    def test_loader_sets_fog_flow_only_from_nozzle_sprinkler_flow(self):
        """프로필 로더가 `fog_flow_lpm` 을 노즐 스프링클러 유량에서만 만든다."""
        import pathlib, re
        src = pathlib.Path(
            'aot/functions/custom_functions/env_coordinator_impl'
            '/_profile_loader_mixin.py').read_text(encoding='utf-8')
        assigns = re.findall(r"\['fog_flow_lpm'\]\s*=\s*(.+)", src)
        assert assigns, 'fog_flow_lpm 배선이 사라졌다'
        for rhs in assigns:
            assert 'irrigation' not in rhs, rhs
        assert 'sprinkler_flow_lph' in src


class TestFoggerAtSaturation:
    """포화 공기에서는 분무해도 증발하지 않는다 — 냉각도 가습도 없다.

    증발을 미는 힘은 VPD 이고 RH=100% 에서 그 값은 0 이다. 그런데 모델은
    RH 와 무관하게 같은 ΔT·ΔRH 를 신고했다. 2026-08-20 로컬 육묘장이 정확히
    RH 100% 였고, 거기서 분무가 냉각 효과를 주장한 것이 결합 drive 를 엉뚱하게
    몰고 간 성분 중 하나다.

    ⚠ 여기 쓰이는 `(1−RH/100)` 은 `make_vpd_effect` 에서 **제거한** 인자와
    형태만 같고 성격이 다르다(거기선 틀린 가정, 여기선 실제 구동력).
    """

    CAP = {'volume_m3': FACILITY_VOL_M3, 'fog_flow_lpm': 12.0}

    def test_no_cooling_in_saturated_air(self):
        eff = _fog(self.CAP, 'temperature', rh=100.0)
        assert eff.magnitude_native == pytest.approx(0.0)
        assert eff.direction == '0'      # 제어 축에서 아예 빠진다

    def test_no_humidification_in_saturated_air(self):
        eff = _fog(self.CAP, 'humidity', rh=100.0)
        assert eff.magnitude_native == pytest.approx(0.0)
        assert eff.direction == '0'

    def test_vpd_effect_is_zero_in_saturated_air(self):
        assert _fog(self.CAP, 'vpd', rh=100.0).magnitude_native == pytest.approx(0.0)

    def test_availability_is_monotone_in_humidity(self):
        """습할수록 효과가 작아진다 (단조 감소)."""
        vals = [_fog(self.CAP, 'temperature', rh=rh).magnitude_native
                for rh in (60.0, 80.0, 90.0, 95.0, 100.0)]
        assert all(a >= b for a, b in zip(vals, vals[1:]))
        assert vals[0] > 0.0 and vals[-1] == 0.0

    def test_unchanged_below_the_reference_humidity(self):
        """기준 습도 이하에서는 계수를 그대로 쓴다 — 건조하다고 키우지 않는다."""
        from aot.functions.utils.env_control.effect_functions import _EVAP_REF_RH
        base = _fog(self.CAP, 'temperature', rh=_EVAP_REF_RH).magnitude_native
        for rh in (0.0, 20.0, 50.0, _EVAP_REF_RH):
            assert _fog(self.CAP, 'temperature',
                        rh=rh).magnitude_native == pytest.approx(base)

    def test_calibrated_k_is_also_scaled(self):
        """캘리브레이션 값이라도 포화에서는 증발하지 않는다."""
        p = _FakeProfile(volume_m3=FACILITY_VOL_M3, fog_flow_lpm=3.0)
        p.calibrated_K = {'temperature': 1.25}
        eff = DEFAULT_EFFECT_MODELS['fogger']['temperature'](
            _env(RH=100.0), 100.0, p)
        assert eff.magnitude_native == pytest.approx(0.0)

    def test_coordinator_parks_the_fogger_in_saturated_air(self):
        """포화 상태에서 코디네이터가 분무를 켜지 않는다 (전 구간)."""
        ctx = make_ctx(T_int=23.34, RH_int=100.0)
        target = {'humidity': TargetVar(value=85.0, tolerance=5.0, priority=1.0)}
        fogger = _profile('fog', 'fogger', dict(DEFAULT_EFFECT_MODELS['fogger']),
                          cost=1.0)
        fogger.capacity_meta = dict(self.CAP)
        cmds, _ = _coordinate(ctx, target, [fogger],
                              state=CoordinatorState(prev_commands={'fog': 60.0},
                                                     integral={'fog': 60.0}))
        assert cmds['fog'].aperture < 60.0
