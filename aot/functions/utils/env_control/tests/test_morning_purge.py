# coding=utf-8
"""아침 습기 빼기 — 해가 집을 데우는데 실내가 과습이면 환기창을 조금 연다 (근거 54, 2026-10-10).

## 실측 (개발서버, 2026-10-10)

    영양 육묘장(토마토, VPD 목표 1.0)  07:00~09:30  실내 RH ≈ 91 % · VPD 0.1~0.4 · 해로 9.5 → 22.9 °C
                                       실외는 더 건조(RH 90 → 58 %) — 그런데 천창·측창 0 %, 근거 27(과습·실외 너무 참)
    김제 육묘장3                       ~10:00  실내 19~26 °C · RH 90~93 %, 실외 RH 72~94 %

난방 요구가 서 있으면(실내가 목표 + 허용오차 이하) 실외가 1 °C만 더 차도 COLD 라서 몇 시간을 RH 90 % 이상으로
둔다. 해가 드는 동안의 열은 공짜이고 그 습도는 병의 조건이다.

## 구조

    판정(해·과습·실외가 건조·열 손실 작음 → 하한 %)   `humid_regime.morning_purge`
    적용 대상                                          `decide_parking` 2.95 — ParkDecision.purge_ids
    명령·적분                                          `coordinate` — 하한에 묶는다(근거 54)
"""
import logging

import pytest

from aot.functions.utils.env_control import humid_regime as HR
from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control import solar_vent as SV
from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate, decide_parking,
)
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)

T_LOW = 21.0          # 목표 22 ± 1


def _dec(T_in=21.6, RH_in=91.0, T_out=13.0, RH_out=65.0, solar=300.0, T_low=T_LOW,
         zone=True, prev=None, **kw):
    return HR.morning_purge(T_in, RH_in, T_out, RH_out, solar, T_low, zone, prev=prev, **kw)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 판정
# ─────────────────────────────────────────────────────────────────────────────

class TestActivation:

    def test_the_reported_morning_gets_a_small_opening(self):
        d = _dec()
        assert d.active and d.why_off is None
        assert HR.PURGE_MIN_PCT <= d.pct <= HR.PURGE_MAX_PCT

    def test_the_stricter_dewpoint_gap_than_plain_relief(self):
        """이슬점 차가 `RELIEF_DEW_GAP_C` 이상이어도 `PURGE_DEW_GAP_C` 에 못 미치면 열지 않는다."""
        assert HR.PURGE_DEW_GAP_C > HR.RELIEF_DEW_GAP_C
        # 실내 21.6 °C · 91 % → 이슬점 ≈ 20.0. 실외 18 °C · 70 % → 이슬점 ≈ 12.4 (차 7.6)
        assert _dec(T_out=18.0, RH_out=70.0).active
        # 실외 22 °C · 87 % → 이슬점 ≈ 19.6 (차 0.4): 습기를 들이는 창이다
        d = _dec(T_out=22.0, RH_out=87.0)
        assert not d.active and d.why_off == 'wet'

    def test_warm_but_wetter_outdoor_air_is_not_purged_even_if_its_vpd_is_higher(self):
        """실외가 따뜻해 VPD 가 높아도 수증기압이 높으면 습기를 들인다(과습 구간 머리말과 같은 이유)."""
        d = _dec(T_in=15.0, RH_in=92.0, T_out=21.0, RH_out=88.0, T_low=14.0)
        assert HR.vpd_kpa(21.0, 88.0) > HR.vpd_kpa(15.0, 92.0)
        assert not d.active and d.why_off == 'wet'

    def test_outside_the_overhumid_zone_nothing(self):
        d = _dec(zone=False)
        assert not d.active and d.why_off == 'dry'

    @pytest.mark.parametrize('missing', ['T_in', 'RH_in', 'T_out', 'RH_out', 'solar', 'T_low'])
    def test_an_unknown_input_is_not_invented(self, missing):
        args = dict(T_in=21.6, RH_in=91.0, T_out=13.0, RH_out=65.0, solar=300.0, T_low=T_LOW)
        args[missing] = None
        d = _dec(**args)
        assert not d.active and d.why_off == 'unknown'


class TestSun:

    def test_below_the_threshold_no_purge(self):
        d = _dec(solar=HR.PURGE_SOLAR_ON_W - 1.0)
        assert not d.active and d.why_off == 'no_sun'

    def test_night_has_no_sun(self):
        assert _dec(solar=0.0).why_off == 'no_sun'

    def test_the_threshold_has_hysteresis(self):
        mid = (HR.PURGE_SOLAR_ON_W + HR.PURGE_SOLAR_OFF_W) / 2.0
        assert not _dec(solar=mid).active
        assert _dec(solar=mid, prev=HR.PurgeState(on=True)).active
        assert not _dec(solar=HR.PURGE_SOLAR_OFF_W - 1.0, prev=HR.PurgeState(on=True)).active

    def test_it_reuses_the_solar_vent_load(self):
        """일사 환산은 `solar_vent.solar_load` 하나다 — 실측이 없으면 맑은 하늘 × 구름비."""
        w = SV.solar_load({}, {}, clear_sky_now=400.0, cloud_ratio=0.5)
        assert w == pytest.approx(200.0)
        assert _dec(solar=w).active


class TestTemperatureGuard:

    def test_near_the_lower_edge_it_opens_without_a_trend(self):
        assert _dec(T_in=T_LOW - HR.PURGE_NEAR_BELOW_C).active
        assert _dec(T_in=T_LOW + 2.0).active

    def test_far_below_never(self):
        d = _dec(T_in=T_LOW - HR.PURGE_FAR_BELOW_C - 0.2, dT_h=3.0)
        assert not d.active and d.why_off == 'cold_in'

    def test_between_near_and_far_only_while_rising(self):
        T = T_LOW - 2.0
        assert _dec(T_in=T).why_off == 'cold_in'                     # 변화율 모름
        assert _dec(T_in=T, dT_h=0.0).why_off == 'cold_in'           # 안 오른다
        d = _dec(T_in=T, dT_h=HR.PURGE_RISING_C_PER_H + 0.1)
        assert d.active and d.pct == HR.PURGE_MIN_PCT                # 하한 아래에서는 최소만

    def test_falling_below_the_edge_closes(self):
        d = _dec(T_in=T_LOW - 0.5, dT_h=HR.PURGE_FALLING_C_PER_H - 0.1)
        assert not d.active and d.why_off == 'falling'
        # 하한 위에서는 식어도 습기를 뺀다
        assert _dec(T_in=T_LOW + 0.5, dT_h=-2.0).active

    def test_forced_heat_from_the_hard_minimum(self):
        """최저 온도 한계는 `_force_heat` 래치로 들어온다 — 서 있으면 안 연다."""
        assert _dec(force_heat=True).why_off == 'cold_in'

    def test_a_very_cold_outdoor_air_closes(self):
        d = _dec(T_in=22.0, T_out=22.0 - HR.PURGE_MAX_COLD_DELTA_C - 0.5, RH_out=60.0)
        assert not d.active and d.why_off == 'cold_out'

    def test_the_temperature_edges_have_hysteresis(self):
        on = HR.PurgeState(on=True)
        # far: 켜진 뒤엔 0.5 °C 완화
        T = T_LOW - HR.PURGE_FAR_BELOW_C - 0.3
        assert not _dec(T_in=T, dT_h=1.0).active
        assert _dec(T_in=T, dT_h=0.0, prev=on).active
        # 오르는 중 문턱은 켜진 뒤 0
        assert _dec(T_in=T_LOW - 2.0, dT_h=0.0, prev=on).active
        # 차가운 실외 문턱 ×1.25
        edge = 22.0 - HR.PURGE_MAX_COLD_DELTA_C - 1.0
        assert not _dec(T_in=22.0, T_out=edge, RH_out=60.0).active
        assert _dec(T_in=22.0, T_out=edge, RH_out=60.0, prev=on).active

    def test_the_dewpoint_gap_has_hysteresis(self):
        # 이슬점 차 ≈ 1.6 °C — 문턱(2.0)엔 못 미치고 절반(1.0)은 넘는다
        c = dict(T_out=20.0, RH_out=91.0)
        gap = HR.dew_gap_c(21.6, 91.0, c['T_out'], c['RH_out'])
        assert HR.PURGE_DEW_GAP_C * HR.RELIEF_KEEP_FRAC <= gap < HR.PURGE_DEW_GAP_C
        assert not _dec(**c).active
        assert _dec(prev=HR.PurgeState(on=True), **c).active


class TestSize:

    def test_grows_with_humidity_and_sun(self):
        a = _dec(RH_in=89.0, solar=150.0).pct
        b = _dec(RH_in=91.0, solar=150.0).pct
        c = _dec(RH_in=91.0, solar=400.0).pct
        d = _dec(RH_in=95.0, solar=600.0).pct
        assert a < b < c < d

    def test_bounded(self):
        lo = _dec(RH_in=84.0, solar=HR.PURGE_SOLAR_ON_W).pct
        hi = _dec(RH_in=99.0, solar=1000.0).pct
        assert lo == pytest.approx(HR.PURGE_MIN_PCT)
        assert hi == pytest.approx(HR.PURGE_MAX_PCT)

    def test_a_small_fixed_amount_not_a_ventilation_demand(self):
        assert HR.PURGE_MAX_PCT <= 15.0 < HR.CAP_PCT


class TestTrend:

    def test_unknown_without_history(self):
        assert HR.temp_trend_h(None, 20.0, 600.0) is None
        assert HR.temp_trend_h(HR.PurgeState(), 20.0, 600.0) is None
        assert HR.temp_trend_h(HR.PurgeState(T_prev=19.0), None, 600.0) is None

    def test_per_cycle_difference_in_degrees_per_hour(self):
        """600초 주기 시설 — 상황 보고의 5분 창 추세는 점이 하나뿐이라 늘 0 이다. 사이클 간 차로 잰다."""
        assert HR.temp_trend_h(HR.PurgeState(T_prev=19.0), 20.0, 600.0) == pytest.approx(6.0)
        assert HR.temp_trend_h(HR.PurgeState(T_prev=20.0), 19.5, 600.0) == pytest.approx(-3.0)

    def test_it_is_smoothed(self):
        v = HR.temp_trend_h(HR.PurgeState(T_prev=19.0, dT_h=0.0), 20.0, 600.0)
        assert v == pytest.approx(3.0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 적용 — decide_parking · coordinate
# ─────────────────────────────────────────────────────────────────────────────

def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, deviation, context, T_target=22.0, T_tol=1.0):
        self.target = {'vpd': TargetVar(value=1.0, tolerance=0.1, priority=1.2, unit='kPa'),
                       'temperature': TargetVar(value=T_target, tolerance=T_tol, priority=0.5,
                                                unit='°C')}
        self.deviation_native = deviation
        self.context = context


def _p(aid, kind='opening', magnitude=0.4, safe_default=0.0):
    p = ActuatorProfile(
        actuator_id=aid, kind=kind, effect_model={'vpd': _effect('↑', magnitude)},
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=safe_default)
    p.cmd_scale = 1.0
    return p


def _sun(w=300.0):
    return SV.SolarVentDecision(active=False, solar_w=w, sun_on=True)


def _cctx(sv=None, T_int=21.6, RH_int=91.0, T_ext=13.0, RH_ext=65.0, **kw):
    ctx = {'cycle_sec': 600.0, 'T_ext': T_ext, 'T_int': T_int, 'RH_int': RH_int,
           'RH_ext': RH_ext, 'vent_futility_gate': False, 'internal': {}, 'external': {},
           'solar_vent': _sun() if sv is None else sv}
    ctx.update(kw)
    return ctx


def _run(profiles, ctx, prev=0.0, cycles=1, dev=-0.8, state=None):
    """dev < 0 — VPD 가 목표보다 낮다(요구는 열라는 쪽). 과습 구간이 서면 27 이 그 요구를 닫는다."""
    st = state or CoordinatorState()
    st.prev_commands = {p.actuator_id: prev for p in profiles}
    st.integral = {p.actuator_id: prev for p in profiles}
    cmds = None
    for _ in range(cycles):
        cmds, st = coordinate(_Situation({'vpd': dev}, ctx), profiles, st, unique_id='')
    return cmds, st


def _pk(ctx, prof=None, prev=0.0, purge_prev=None):
    prof = prof or [_p('v')]
    return decide_parking(prof, _Situation({'vpd': -0.8}, ctx), ctx, 600.0,
                          {p.actuator_id: prev for p in prof}, log=False,
                          purge_prev=purge_prev, humid_prev=True)


class TestFloorInCoordinate:

    def test_baseline_without_sun_the_vent_is_parked_with_27(self):
        """대조 — 해가 없으면 종전대로 난방 요구 + 실외가 더 참 → 27 로 닫는다."""
        ctx = _cctx(SV.SolarVentDecision(active=False, solar_w=0.0))
        cmds, st = _run([_p('v')], ctx, prev=10.0, cycles=3)
        assert cmds['v'].reason == LC.REASON_HUMID_COLD
        assert cmds['v'].control_value() < 10.0

    def test_with_sun_it_holds_the_purge_opening_instead(self):
        cmds, st = _run([_p('v')], _cctx(), prev=0.0, cycles=4)
        assert cmds['v'].reason == LC.REASON_MORNING_PURGE
        assert HR.PURGE_MIN_PCT <= cmds['v'].control_value() <= HR.PURGE_MAX_PCT
        assert st.purge is not None and st.purge.on
        assert st.integral['v'] >= HR.PURGE_MIN_PCT - 1e-9

    def test_the_size_is_the_decision_size(self):
        ctx = _cctx(_sun(450.0), RH_int=93.0)
        want = HR.morning_purge(21.6, 93.0, 13.0, 65.0, 450.0, T_LOW, True,
                                prev=None, dT_h=None).pct
        cmds, _ = _run([_p('v')], ctx, cycles=3)
        assert cmds['v'].control_value() == pytest.approx(want)

    def test_it_lifts_a_vent_that_was_decaying_closed(self):
        cmds, _ = _run([_p('v')], _cctx(), prev=0.0, cycles=1)
        assert cmds['v'].control_value() > 0.0

    def test_no_gradient_vent_is_lifted_too(self):
        cmds, _ = _run([_p('v', magnitude=0.0)], _cctx(), cycles=3)
        assert cmds['v'].reason == LC.REASON_MORNING_PURGE

    def test_the_pi_may_open_beyond_the_floor(self):
        """온도 상한 항이 더 열라고 하면(실내가 목표 위) 과습 구간 밖이거나 PI 가 이긴다 — 하한은 바닥일 뿐이다."""
        ctx = _cctx(T_int=26.0, RH_int=90.0)             # 목표 위 + 실외가 더 참 → 27 이 아니라 상한 30 %
        cmds, _ = _run([_p('v')], ctx, prev=25.0, dev=-0.8, cycles=2)
        assert cmds['v'].control_value() >= HR.PURGE_MIN_PCT

    def test_the_bigger_solar_floor_keeps_reason_51(self):
        sv = SV.SolarVentDecision(active=True, floor_pct=40.0, solar_w=650.0, sun_on=True,
                                  t_line=22.0, excess_c=2.0)
        cmds, _ = _run([_p('v')], _cctx(sv), cycles=4)
        assert cmds['v'].reason == LC.REASON_SOLAR_VENT_FLOOR
        assert cmds['v'].control_value() == pytest.approx(40.0)

    def test_fans_only_when_there_is_no_opening(self):
        prof = [_p('v'), _p('f', kind='exhaust_fan')]
        cmds, _ = _run(prof, _cctx(), cycles=3)
        assert cmds['v'].reason == LC.REASON_MORNING_PURGE
        assert cmds['f'].reason != LC.REASON_MORNING_PURGE
        cmds, _ = _run([_p('f', kind='exhaust_fan')], _cctx(), cycles=3)
        assert cmds['f'].reason == LC.REASON_MORNING_PURGE

    def test_release_carries_the_integral(self):
        """하한이 풀려도 적분은 하한 자리에서 출발한다 — 0 으로 쾅 닫히지 않는다."""
        _, st = _run([_p('v')], _cctx(), cycles=3)
        assert st.integral['v'] >= HR.PURGE_MIN_PCT - 1e-9


class TestRainCapWins:
    """강우 단계 제한(근거 52)이 습기 빼기 하한(54)을 이긴다 — 하한은 상한 **앞**에서 걸린다.

    결과는 min(상한, max(하한, PI)). 일사 하한(51)과 같은 순서다(`coordinate` 의 장치별 루프).
    """

    def test_a_closed_roof_cap_keeps_the_vent_shut(self):
        cmds, st = _run([_p('v')], _cctx(vent_open_caps={'v': 0.0}), prev=0.0, cycles=4)
        assert cmds['v'].control_value() == pytest.approx(0.0)
        assert cmds['v'].reason == LC.REASON_RAIN_RESTRICT
        assert st.integral['v'] <= 1e-9           # 실행되지 않은 하한은 배우지 않는다

    def test_the_forecast_roof_cap_allows_the_purge_up_to_the_cap(self):
        from aot.functions.utils.env_control.safety_gates import RAIN_ROOF_FORECAST_CAP_PCT
        cmds, _ = _run([_p('v')], _cctx(vent_open_caps={'v': RAIN_ROOF_FORECAST_CAP_PCT}),
                       cycles=4)
        assert cmds['v'].reason == LC.REASON_MORNING_PURGE
        assert HR.PURGE_MIN_PCT <= cmds['v'].control_value() <= RAIN_ROOF_FORECAST_CAP_PCT

    def test_a_cap_below_the_purge_size_wins(self):
        cmds, st = _run([_p('v')], _cctx(vent_open_caps={'v': 3.0}), cycles=4)
        assert cmds['v'].control_value() == pytest.approx(3.0)
        assert cmds['v'].reason == LC.REASON_RAIN_RESTRICT
        assert st.integral['v'] <= 3.0 + 1e-9

    def test_no_further_opening_holds_a_closed_vent_closed(self):
        """상한 None(약한 예보 비 — 지금 개도) — 닫혀 있던 천창은 하한이 와도 열리지 않는다."""
        cmds, _ = _run([_p('v')], _cctx(vent_open_caps={'v': None}), prev=0.0, cycles=4)
        assert cmds['v'].control_value() == pytest.approx(0.0)

    def test_the_cap_applies_over_a_larger_solar_floor_too(self):
        from aot.functions.utils.env_control.safety_gates import RAIN_ROOF_FORECAST_CAP_PCT
        sv = SV.SolarVentDecision(active=True, floor_pct=40.0, solar_w=650.0, sun_on=True,
                                  t_line=22.0, excess_c=2.0)
        cmds, _ = _run([_p('v')], _cctx(sv, vent_open_caps={'v': RAIN_ROOF_FORECAST_CAP_PCT}),
                       cycles=4)
        assert cmds['v'].control_value() == pytest.approx(RAIN_ROOF_FORECAST_CAP_PCT)
        assert cmds['v'].reason == LC.REASON_RAIN_RESTRICT


class TestWinners:
    """하한보다 앞서는 판정 — 이것들이 서 있으면 하한을 걸지 않는다."""

    def test_baseline_purge_ids(self):
        pk = _pk(_cctx())
        assert pk.purge_ids == {'v'} and pk.purge_pct > 0.0
        # MPC 가 읽는 파킹 집합은 그대로다 — 하한은 PI 쪽에서만 걸린다(MPC 동결)
        assert 'v' in pk.humid_cold and 'v' in pk.park_ids

    def test_outdoor_invented_holds(self):
        ctx = _cctx(external={'_ext_synthetic': True})
        assert not _pk(ctx).purge_ids
        cmds, _ = _run([_p('v')], ctx, prev=10.0)
        assert cmds['v'].reason == LC.REASON_NO_OUTDOOR_DATA
        assert cmds['v'].control_value() == pytest.approx(10.0)

    def test_rain_wind_unknown_means_no_further_opening(self):
        ctx = _cctx(vent_open_ceiling=True)
        assert not _pk(ctx).purge_ids
        cmds, _ = _run([_p('v')], ctx, prev=2.0, cycles=3)
        assert cmds['v'].control_value() <= 2.0 + 1e-9
        assert cmds['v'].reason != LC.REASON_MORNING_PURGE

    def test_night_parking_wins(self):
        ctx = _cctx(night_vent_park=True)
        assert not _pk(ctx).purge_ids
        cmds, _ = _run([_p('v')], ctx, prev=10.0, cycles=2)
        assert cmds['v'].reason == LC.REASON_NIGHT_PARKED

    def test_prepark_taper_wins(self):
        ctx = _cctx(night_vent_taper_s=600.0)
        assert not _pk(ctx).purge_ids
        cmds, _ = _run([_p('v')], ctx, prev=2.0, cycles=3)
        assert cmds['v'].control_value() <= 2.0 + 1e-9

    def test_hvac_interlock_wins(self):
        assert not _pk(_cctx(hvac_interlock=True, hvac_running=True)).purge_ids

    def test_heat_protect_hot_outside_wins(self):
        closed = HeatProtectDecision(tier=1, threshold=30.0, vent_open_ok=False,
                                     vent_closed_ids=frozenset({'v'}))
        assert not _pk(_cctx(heat_protect=closed)).purge_ids

    def test_forced_heat_wins(self):
        assert not _pk(_cctx(internal={'_force_heat': True})).purge_ids

    def test_a_missing_temperature_floor_is_not_judged(self):
        sit = _Situation({'vpd': -0.8}, _cctx())
        sit.target.pop('temperature')
        pk = decide_parking([_p('v')], sit, sit.context, 600.0, {'v': 0.0}, log=False,
                            humid_prev=True)
        assert not pk.purge_ids

    def test_vpd_direct_mode_uses_the_guide_low_not_the_derived_target(self):
        """VPD 직접 모드의 유도 온도 목표는 실내보다 늘 앞서 간다(영양 2026-10-10: 실내 15.8 → 하한 18.5,
        20.8 → 22.7) — 그것을 하한으로 쓰면 가장 습한 때 '너무 춥다' 로 막힌다. 유도 범위의 아래 끝을 쓴다."""
        ctx = _cctx(T_int=19.5, T_guide_low=18.0)
        sit = _Situation({'vpd': -0.8}, ctx)
        sit.target.pop('temperature')
        sit.target['_temperature_constraint'] = TargetVar(value=24.0, tolerance=1.0,
                                                          priority=0.5, unit='°C')
        pk = decide_parking([_p('v')], sit, ctx, 600.0, {'v': 0.0}, log=False, humid_prev=True)
        assert pk.purge_ids == {'v'}
        # 같은 실내를 온도 목표 24 ± 1 이 제어 목표였다면 하한 23 에서 3.5 °C 아래 — 막힌다
        sit2 = _Situation({'vpd': -0.8}, ctx, T_target=24.0)
        pk = decide_parking([_p('v')], sit2, ctx, 600.0, {'v': 0.0}, log=False, humid_prev=True)
        assert not pk.purge_ids
        # 유도 범위의 아래 끝보다 한참 아래면 VPD 직접 모드에서도 막힌다
        cold = _cctx(T_int=14.0, T_guide_low=18.0)
        pk = decide_parking([_p('v')], sit, cold, 600.0, {'v': 0.0}, log=False, humid_prev=True)
        assert not pk.purge_ids

    def test_a_real_temperature_target_wins_over_the_guide_low(self):
        ctx = _cctx(T_int=19.5, T_guide_low=10.0)       # 목표 22 ± 1 → 하한 21, 1.5 °C 아래·변화율 모름
        pk = _pk(ctx)
        assert not pk.purge_ids

    def test_a_temperature_emergency_leaves_the_zone_so_no_purge(self):
        """온도 비상이면 과습 구간이 서지 않는다 — 그때는 온도가 환기를 요구한다."""
        ctx = _cctx(internal={'_force_cool': True}, T_int=30.0)
        pk = _pk(ctx)
        assert not pk.humid_zone and not pk.purge_ids

    def test_no_sun_no_purge_at_night(self):
        for sv in (SV.SolarVentDecision(solar_w=0.0), None):
            ctx = _cctx(sv)
            if sv is None:
                ctx.pop('solar_vent')
            assert not _pk(ctx).purge_ids

    def test_the_purge_beats_the_parking_of_27_24_and_futility(self):
        # 27(너무 참) — 위 baseline. 24(실외가 더 습함)는 이슬점 차 조건이 막는다.
        assert not _pk(_cctx(T_ext=20.0, RH_ext=95.0)).purge_ids
        ctx = _cctx(vent_futility_gate=True)
        cmds, _ = _run([_p('v')], ctx, prev=0.0, cycles=4)
        assert cmds['v'].reason == LC.REASON_MORNING_PURGE


class TestCyclesAndHysteresis:

    def test_it_stops_when_the_zone_is_left(self):
        st = CoordinatorState()
        _, st = _run([_p('v')], _cctx(), cycles=3, state=st)
        assert st.purge.on and st.humid_zone
        # 해가 데워 RH 가 82 % 밑으로 — 구간 이탈(VPD ≥ 0.40 · 여유 ≥ 3 °C)
        dry = _cctx(T_int=23.0, RH_int=78.0)
        cmds, st = _run([_p('v')], dry, prev=cmds_prev(st), cycles=1, state=st)
        assert not st.humid_zone and not st.purge.on
        assert cmds['v'].reason != LC.REASON_MORNING_PURGE

    def test_the_zone_hysteresis_keeps_it_on_between_the_thresholds(self):
        """구간은 들어갈 때 낮고 나갈 때 높다 — 사이에서는 켜진 채다."""
        T = 22.0
        rh_mid = next(r for r in range(99, 50, -1)
                      if HR.vpd_kpa(T, r) >= HR.ENTER_VPD_KPA
                      and (T - HR.dewpoint_c(T, r)) >= HR.ENTER_MARGIN_C
                      and (HR.vpd_kpa(T, r) < HR.EXIT_VPD_KPA
                           or (T - HR.dewpoint_c(T, r)) < HR.EXIT_MARGIN_C))
        st = CoordinatorState()
        _, st = _run([_p('v')], _cctx(), cycles=2, state=st)
        mid = _cctx(T_int=T, RH_int=float(rh_mid))
        cmds, st = _run([_p('v')], mid, prev=cmds_prev(st), cycles=1, state=st)
        assert st.humid_zone and st.purge.on
        assert cmds['v'].reason == LC.REASON_MORNING_PURGE

    def test_the_trend_is_carried_between_cycles(self):
        """오르는 중인지는 사이클 간 차로 안다 — 하한 아래(2 °C)는 첫 사이클엔 모르고 두 번째에 연다."""
        st = CoordinatorState()
        _, st = _run([_p('v')], _cctx(T_int=T_LOW - 2.4), cycles=1, state=st)
        assert not st.purge.on and st.purge.dT_h is None
        _, st = _run([_p('v')], _cctx(T_int=T_LOW - 2.0), cycles=1, state=st)
        assert st.purge.dT_h == pytest.approx(0.4 / 600.0 * 3600.0)       # 2.4 °C/h
        cmds, st = _run([_p('v')], _cctx(T_int=T_LOW - 1.6), cycles=1, state=st)
        assert st.purge.on
        assert cmds['v'].reason == LC.REASON_MORNING_PURGE
        assert cmds['v'].control_value() == pytest.approx(HR.PURGE_MIN_PCT)

    def test_a_cooling_house_below_the_edge_closes_again(self):
        st = CoordinatorState()
        _, st = _run([_p('v')], _cctx(T_int=T_LOW - 0.2), cycles=2, state=st)
        assert st.purge.on
        for T in (T_LOW - 0.9, T_LOW - 1.6, T_LOW - 2.3):                # -4 °C/h
            cmds, st = _run([_p('v')], _cctx(T_int=T), prev=cmds_prev(st), cycles=1, state=st)
        assert not st.purge.on
        assert cmds['v'].reason != LC.REASON_MORNING_PURGE

    @pytest.fixture
    def grab(self):
        # caplog 는 루트로 올라오는 기록만 받는다. 전체 스위트에서는 앞선 테스트(앱 생성의
        # 로깅 설정 등)가 상위 로거 전파·전역 비활성을 바꿔 caplog 가 비던 검사다 — 그래서
        # 코디네이터 로거에 직접 붙는다(`test_wind_gate_grading.grab` 과 같은 방식).
        from aot.functions.utils.env_control import coordinator as _co
        got = []

        class _H(logging.Handler):
            def emit(self, record):
                got.append(record.getMessage())

        h = _H()
        prev = (_co.logger.level, _co.logger.disabled, logging.root.manager.disable)
        _co.logger.addHandler(h)
        _co.logger.setLevel(logging.DEBUG)
        _co.logger.disabled = False
        logging.disable(logging.NOTSET)
        try:
            yield got
        finally:
            _co.logger.removeHandler(h)
            _co.logger.setLevel(prev[0])
            _co.logger.disabled = prev[1]
            logging.disable(prev[2])

    def test_transitions_are_logged_once(self, grab):
        ctx = _cctx()
        sit = _Situation({'vpd': -0.8}, ctx)
        decide_parking([_p('v')], sit, ctx, 600.0, {'v': 0.0}, log=True,
                       humid_prev=True, purge_prev=HR.PurgeState(on=False))
        decide_parking([_p('v')], sit, ctx, 600.0, {'v': 0.0}, log=True,
                       humid_prev=True, purge_prev=HR.PurgeState(on=True))
        lines = [m for m in grab if m.startswith('아침 습기 빼기 켬') or m.startswith('아침 습기 빼기 끔')]
        assert len(lines) == 1 and '켬' in lines[0]

    def test_a_caller_without_history_logs_nothing(self, grab):
        """MPC 경로는 이력을 안 이어 준다(purge_prev=None) — 매 사이클 '켬' 을 찍지 않는다."""
        ctx = _cctx()
        sit = _Situation({'vpd': -0.8}, ctx)
        decide_parking([_p('v')], sit, ctx, 600.0, {'v': 0.0}, log=True, humid_prev=True)
        assert not [m for m in grab if m.startswith('아침 습기 빼기 켬') or m.startswith('아침 습기 빼기 끔')]


def cmds_prev(st):
    return max(st.prev_commands.values() or [0.0])


# ─────────────────────────────────────────────────────────────────────────────
# 3. 근거 코드
# ─────────────────────────────────────────────────────────────────────────────

class TestReasonCode:

    def test_code_54_and_name(self):
        assert LC.REASON_MORNING_PURGE == 54
        assert LC.reason_name(54) == 'morning_purge'

    def test_neighbours_are_untouched(self):
        assert LC.REASON_SOLAR_VENT_FLOOR == 51 and LC.REASON_HUMID_COLD == 27
        # 50 은 비워 둔다. 52(강우 단계 제한)·53(해 질 녘 분무 제한)은 그대로다
        taken = {v for k, v in vars(LC).items() if k.startswith('REASON_') and isinstance(v, int)}
        assert 50 not in taken
        assert LC.REASON_RAIN_RESTRICT == 52 and LC.REASON_WETTING_FOG_DUSK == 53
        assert list(sorted(taken)).count(54) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. 배선 — 사이클이 VPD 직접 모드의 온도 하한선을 싣는다
# ─────────────────────────────────────────────────────────────────────────────

class TestCycleWiring:

    def test_the_cycle_publishes_the_guide_low_next_to_the_ceiling(self):
        """`decide_parking` 이 VPD 직접 모드에서 읽는 `T_guide_low` 는 사이클이 싣는다 — 빠지면 그 모드에서
        습기 빼기가 영영 서지 않는다(하한선을 모르면 판단하지 않는다). `T_ceiling` 과 같은 자리에서 싣는다."""
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin
        src = inspect.getsource(_cycle_mixin)
        assert "situation.context['T_guide_low'] = T_g_min" in src
        assert src.index("situation.context['T_ceiling'] = T_g_max") < src.index(
            "situation.context['T_guide_low'] = T_g_min")
