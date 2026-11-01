# coding=utf-8
"""낮 일사 부하 환기 하한 — 해가 들면 VPD 요구로 창을 닫아 두지 않는다 (2026-10-10 영양 육묘장).

## 실측

    12:45 실내 28.7 °C · 49 % · VPD 2.0(상승 중), 실외 27.6 °C · 40 % · VPD 2.2, 맑음
    천창·측창 0 %(근거 1 주작용 vpd · 15 무구배), 분무 100 %

닫힌 온실은 일사로 데워지고, 분무의 증발냉각은 공기 교환이 있어야 이어진다. 작은 안팎 차는
분무가 식혀 만든 것이라 '환기해도 소용없다' 의 근거가 못 된다.

## 구조

    판정(해·더움·바깥이 더 덥지 않음 → 하한 %)   `solar_vent.evaluate_solar_vent`
    적용 대상                                     `decide_parking` — ParkDecision.solar_floor_ids
    명령·적분                                     `coordinate` — 하한에 묶는다(근거 51)

효과 모델은 바꾸지 않는다(`solar_vent` 머리말 — 실효 온도차는 VPD 구동을 희석했다).
"""
import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.utils.env_control import effect_functions as EF
from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control import solar_vent as SV
from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate, decide_parking,
)
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _tc(value=25.7, tol=1.0):
    """VPD 직접 모드의 유도 온도 목표(`_temperature_constraint`)."""
    return {'_temperature_constraint': TargetVar(value=value, tolerance=tol, priority=1.0)}


def _sctx(T_int=28.7, T_ext=27.6, solar=650.0, **kw):
    ctx = {'T_int': T_int, 'T_ext': T_ext,
           'internal': {} if solar is None else {'_outdoor_solar': solar},
           'external': {}, 'heat_protect': HeatProtectDecision(tier=0, threshold=30.0),
           'temp_max': 36.0, 'T_ceiling': 31.0}
    ctx.update(kw)
    return ctx


def _eval(state=None, target=None, **kw):
    st = state or SV.SolarVentState()
    return SV.evaluate_solar_vent(st, _sctx(**kw), _tc() if target is None else target), st


# ─────────────────────────────────────────────────────────────────────────────
# 1. 판정
# ─────────────────────────────────────────────────────────────────────────────

class TestDecision:

    def test_the_reported_noon_gets_a_floor(self):
        """12:45 영양 — 해가 들고 실내가 선(26.7 °C)보다 2 °C 위. 하한이 선다."""
        dec, _ = _eval()
        assert dec.active and dec.t_line == pytest.approx(26.7)
        assert dec.excess_c == pytest.approx(2.0)
        assert 35.0 < dec.floor_pct < 55.0

    def test_no_sun_no_floor(self):
        dec, _ = _eval(solar=120.0)
        assert not dec.active and dec.why_off == 'no_sun'

    def test_unknown_sun_is_not_invented(self):
        """일사도 맑은 하늘(좌표)도 모르면 판단하지 않는다."""
        dec, _ = _eval(solar=None)
        assert not dec.active and dec.why_off == 'unknown'

    def test_no_solar_sensor_uses_half_the_clear_sky(self):
        """일사 센서가 없는 시설(김제) — 맑은 하늘의 절반으로 어림한다. 새벽·저녁은 문턱 아래."""
        st = SV.SolarVentState()
        dec = SV.evaluate_solar_vent(st, _sctx(solar=None), _tc(), clear_sky_now=820.0)
        assert dec.solar_w == pytest.approx(410.0) and dec.active
        dec = SV.evaluate_solar_vent(SV.SolarVentState(), _sctx(solar=None), _tc(),
                                     clear_sky_now=300.0)
        assert not dec.active and dec.why_off == 'no_sun'

    def test_clear_sky_times_cloud_ratio_fills_a_gap(self):
        st = SV.SolarVentState()
        dec = SV.evaluate_solar_vent(st, _sctx(solar=None), _tc(),
                                     clear_sky_now=800.0, cloud_ratio=0.5)
        assert dec.solar_w == pytest.approx(400.0) and dec.active

    def test_sun_hysteresis(self):
        st = SV.SolarVentState()
        assert not _eval(st, solar=180.0)[0].active        # 아직 문턱(200) 아래
        assert _eval(st, solar=210.0)[0].active
        assert _eval(st, solar=160.0)[0].active            # 이력 — 150 까지는 유지
        assert not _eval(st, solar=140.0)[0].active

    def test_temperature_hysteresis(self):
        st = SV.SolarVentState()
        assert not _eval(st, T_int=26.5, T_ext=24.0)[0].active   # 선 아래 — 들어가지 않는다
        assert _eval(st, T_int=26.9, T_ext=24.0)[0].active
        dec, _ = _eval(st, T_int=26.4, T_ext=24.0)               # 선 − 0.3 — 유지(하한은 최소값)
        assert dec.active
        assert dec.floor_pct == pytest.approx(SV.floor_pct(0.0, 26.7, 30.0, 650.0))
        assert not _eval(st, T_int=26.1, T_ext=24.0)[0].active   # 선 − 0.6 — 풀린다

    def test_floor_grows_with_excess_and_sun(self):
        f = [SV.floor_pct(e, 26.7, 30.0, 650.0) for e in (0.0, 1.0, 2.0, 3.3, 5.0)]
        assert f == sorted(f)
        assert f[0] == pytest.approx(SV.SV_FLOOR_MIN_PCT * 0.925)
        assert f[3] == pytest.approx(SV.SV_FLOOR_MAX_PCT * 0.925)
        assert f[4] == pytest.approx(f[3])                   # 보호 문턱 위는 그대로(이어진다)
        assert SV.floor_pct(1.0, 26.7, 30.0, 250.0) < SV.floor_pct(1.0, 26.7, 30.0, 900.0)
        assert SV.floor_pct(1.0, 26.7, 30.0, 900.0) <= SV.SV_FLOOR_MAX_PCT

    def test_hotter_outside_by_more_than_one_degree_gets_nothing(self):
        dec, _ = _eval(T_int=28.0, T_ext=29.5)
        assert not dec.active and dec.why_off == 'hot_outside'
        # 0.5 °C 더운 바깥은 분무가 식혀 만든 차일 수 있다 — 하한은 선다
        assert _eval(T_int=28.0, T_ext=28.5)[0].active

    def test_unknown_or_invented_outdoor_gets_nothing(self):
        assert not _eval(T_ext=None)[0].active
        dec, _ = _eval(external={'_ext_synthetic': True})
        assert not dec.active and dec.why_off == 'unknown'

    def test_temperature_target_and_guide_fallback(self):
        dec, _ = _eval(target={'temperature': TargetVar(value=24.0, tolerance=1.5)})
        assert dec.t_line == pytest.approx(25.5)
        # 목표 없음 · 유도 하한 모름 → 유도 상한(31). 단 보호 문턱(30) − 0.5 를 넘지 않는다.
        dec, _ = _eval(target={})
        assert dec.t_line == pytest.approx(29.5) and not dec.active
        dec, _ = _eval(target={}, T_ceiling=None)
        assert dec.why_off == 'unknown' and not dec.active

    def test_protect_threshold_sets_the_span(self):
        hot = _sctx(T_int=29.5, heat_protect=HeatProtectDecision(tier=0, threshold=30.0))
        off = _sctx(T_int=29.5, heat_protect=HeatProtectDecision(
            tier=0, threshold=30.0, enabled=False))     # 보호 꺼짐 → temp_max(36)
        a = SV.evaluate_solar_vent(SV.SolarVentState(), hot, _tc())
        b = SV.evaluate_solar_vent(SV.SolarVentState(), off, _tc())
        assert a.floor_pct > b.floor_pct

    def test_heat_protect_handover_is_continuous(self):
        """보호 문턱(30 °C)을 넘나들 때 하한이 계단으로 바뀌지 않는다."""
        a = _eval(T_int=29.95)[0].floor_pct
        b = _eval(T_int=30.05, heat_protect=HeatProtectDecision(tier=1, threshold=30.0))[0].floor_pct
        assert abs(a - b) < 2.0


# ─────────────────────────────────────────────────────────────────────────────
# 1b. '덥다' 의 선 — 작물의 온도 의도. VPD 를 좇는 유도 목표가 정하지 않는다
# ─────────────────────────────────────────────────────────────────────────────

class TestCropLine:
    """폐루프 김제 `foehn_dry_wind` 이튿날(2026-10-10 강풍 단계 판): 밤새 닫혀 습한 집에서 VPD 분해가
    온도 목표를 실내보다 0.3~0.7 °C 위로 끌어 올려 따라 올랐다(26.75 → 32.0 °C, 07:20~08:40). 선이
    목표 + 1 이라 하한은 08:50 에야 섰다. 단계 낮 온도 27 °C(유도 22~32), 보호 문턱 30 °C."""

    def _gimje(self, **kw):
        base = dict(T_stage=27.0, T_guide_low=22.0, T_ceiling=32.0)
        base.update(kw)
        return base

    def test_humid_morning_floor_stands_above_the_crop_line(self):
        """유도 목표(30.2)가 실내(29.6)보다 위여도, 실내가 작물 선(27 + 1) 위면 하한이 선다."""
        dec, _ = _eval(target=_tc(30.2), T_int=29.6, T_ext=26.0, solar=520.0, **self._gimje())
        assert dec.active and dec.t_line == pytest.approx(28.0)
        assert dec.excess_c == pytest.approx(1.6)
        # 종전(유도 목표 + 1 = 31.2)이라면 '덥지 않다' 였다
        assert SV.temperature_line(_tc(30.2)) == pytest.approx(31.2)

    def test_humid_morning_trajectory(self):
        """07:40~08:40 의 궤적 — 실내가 작물 선을 넘는 사이클에 켜지고, 오르는 유도 목표와 무관하다."""
        st = SV.SolarVentState()
        on = []
        for T_in, T_tc in ((27.56, 28.1), (28.12, 28.7), (28.71, 29.3), (29.34, 29.9)):
            dec = SV.evaluate_solar_vent(
                st, _sctx(T_int=T_in, T_ext=25.7, solar=450.0, **self._gimje()), _tc(T_tc))
            on.append(dec.active)
        assert on == [False, True, True, True]

    def test_dry_day_keeps_the_lower_derived_line(self):
        """건조해 유도 목표가 낮으면(VPD 를 내리려 온도를 낮춘다) 종전처럼 그쪽이 선이다."""
        dec, _ = _eval(target=_tc(22.8), T_int=25.2, T_ext=23.4, solar=354.0, **self._gimje())
        assert dec.t_line == pytest.approx(23.8) and dec.active

    def test_explicit_temperature_target_is_unchanged(self):
        """온도가 제어 목표(온도 우선 모드의 단계 목표 · VPD 없음)면 그 목표 + 허용오차 그대로."""
        for v, tol in ((24.0, 1.5), (29.0, 1.0)):
            dec, _ = _eval(target={'temperature': TargetVar(value=v, tolerance=tol)},
                           **self._gimje())
            assert dec.t_line == pytest.approx(v + tol)

    def test_tracking_temperature_targets_are_capped_by_the_crop_line(self):
        """VPD 를 못 재 물러난 분해 목표 · 온도 우선 모드의 밴드(지금 온도를 따라감)도 선을 못 끌어 올린다."""
        tv = {'temperature': TargetVar(value=30.5, tolerance=1.0)}
        assert _eval(target=tv, vpd_fallback=True, **self._gimje())[0].t_line == pytest.approx(28.0)
        assert _eval(target=tv, T_basis_band=True, **self._gimje())[0].t_line == pytest.approx(28.0)
        assert _eval(target=tv, **self._gimje())[0].t_line == pytest.approx(31.5)

    def test_without_a_stage_the_upper_third_of_the_guide(self):
        """단계 온도가 없으면 유도 범위의 위쪽 1/3 지점(22~32 → 28.67, 12~32 → 25.33)."""
        dec, _ = _eval(target=_tc(31.0), **self._gimje(T_stage=None))
        assert dec.t_line == pytest.approx(22.0 + 2.0 / 3.0 * 10.0)
        dec, _ = _eval(target={}, T_stage=None, T_guide_low=12.0, T_ceiling=32.0)
        assert dec.t_line == pytest.approx(12.0 + 2.0 / 3.0 * 20.0)

    def test_crop_line_stays_below_the_protect_threshold(self):
        """작물 선이 보호 문턱 위면(유도 25~35 → 31.67) 문턱 − 0.5 로 — 문턱에서 하한이 80 % 로 이어진다."""
        ctx = dict(T_stage=None, T_guide_low=25.0, T_ceiling=35.0)
        dec, _ = _eval(target=_tc(33.0), T_int=29.8, T_ext=27.0, solar=900.0, **ctx)
        assert dec.t_line == pytest.approx(29.5) and dec.active
        at = _eval(target=_tc(33.0), T_int=30.0, T_ext=27.0, solar=900.0, **ctx)[0].floor_pct
        assert at == pytest.approx(SV.SV_FLOOR_MAX_PCT)

    def test_threshold_continuity_on_the_crop_line(self):
        """작물 선 28 → 보호 문턱 30 에서 80 %(일사 가중 1), 문턱을 넘나들어도 계단이 없다."""
        a = _eval(target=_tc(31.0), T_int=29.95, solar=900.0, **self._gimje())[0].floor_pct
        b = _eval(target=_tc(31.0), T_int=30.05, solar=900.0,
                  heat_protect=HeatProtectDecision(tier=1, threshold=30.0),
                  **self._gimje())[0].floor_pct
        assert b == pytest.approx(SV.SV_FLOOR_MAX_PCT) and abs(a - b) < 2.0

    def test_hysteresis_on_the_crop_line(self):
        st = SV.SolarVentState()
        g = self._gimje()
        assert not _eval(st, target=_tc(29.5), T_int=27.9, T_ext=25.0, **g)[0].active
        assert _eval(st, target=_tc(29.5), T_int=28.1, T_ext=25.0, **g)[0].active
        assert _eval(st, target=_tc(29.5), T_int=27.6, T_ext=25.0, **g)[0].active
        assert not _eval(st, target=_tc(29.5), T_int=27.4, T_ext=25.0, **g)[0].active

    def test_minimum_on_time_rides_out_the_cooling_dip(self):
        """폐루프 recorded 10/6: 20 % 하한이 한 사이클에 집을 28.6 → 26.2 °C 로 식혀 풀렸고, 닫히자 해가 다시
        데워 10 분 켬/끔이 반복됐다. 선 뒤 30 분은 온도로 풀리지 않는다(최소값으로 남는다)."""
        st = SV.SolarVentState()
        g = self._gimje()

        def at(t, T):
            return SV.evaluate_solar_vent(st, _sctx(T_int=T, T_ext=18.0, solar=690.0, **g),
                                          _tc(29.0), now=t)
        assert at(0.0, 28.6).active and st.on_since == 0.0
        dip = at(600.0, 26.2)
        assert dip.active and dip.floor_pct == pytest.approx(SV.floor_pct(0.0, 28.0, 30.0, 690.0))
        assert at(1200.0, 26.5).active
        assert not at(1800.0, 26.6).active                    # 30 분 — 온도로 풀린다
        assert at(2400.0, 28.2).active and st.on_since == 2400.0

    def test_the_hold_never_beats_sunset_or_a_hotter_outside(self):
        st = SV.SolarVentState()
        g = self._gimje()
        assert SV.evaluate_solar_vent(st, _sctx(T_int=28.6, T_ext=18.0, **g), _tc(29.0), now=0.0).active
        dec = SV.evaluate_solar_vent(st, _sctx(T_int=28.6, T_ext=30.0, **g), _tc(29.0), now=60.0)
        assert not dec.active and dec.why_off == 'hot_outside'
        assert SV.evaluate_solar_vent(st, _sctx(T_int=28.6, T_ext=18.0, **g), _tc(29.0), now=120.0).active
        dec = SV.evaluate_solar_vent(st, _sctx(T_int=28.6, T_ext=18.0, solar=100.0, **g), _tc(29.0),
                                     now=180.0)
        assert not dec.active and dec.why_off == 'no_sun'

    def test_without_a_clock_the_temperature_hysteresis_alone(self):
        st = SV.SolarVentState()
        g = self._gimje()
        assert _eval(st, target=_tc(29.0), T_int=28.6, T_ext=18.0, **g)[0].active
        assert not _eval(st, target=_tc(29.0), T_int=26.2, T_ext=18.0, **g)[0].active

    def test_crop_tolerance_matches_the_temperature_target_tolerance(self):
        from aot.functions.utils.env_control import basis
        assert SV.SV_CROP_TOL_C == basis.T_TOL


# ─────────────────────────────────────────────────────────────────────────────
# 2. 효과 모델은 그대로다
# ─────────────────────────────────────────────────────────────────────────────

class TestEffectModelUntouched:

    def test_the_opening_temperature_effect_still_uses_the_plain_difference(self):
        """판단은 사이클 context 에 결론만 싣는다 — 효과 함수가 읽는 키는 없다."""
        env = {'T_ext': 28.4, 'T_int': 28.7, 'RH_ext': 40.0, 'RH_int': 49.0, 'wind': 0.0,
               'solar_vent': SV.SolarVentDecision(active=True, floor_pct=40.0)}
        assert EF.opening_temp_effect(env, 100.0).magnitude_native == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 3. 적용 — decide_parking · coordinate
# ─────────────────────────────────────────────────────────────────────────────

def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, deviation, context):
        self.target = {'vpd': TargetVar(value=1.0, tolerance=0.1, priority=1.2, unit='kPa')}
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


def _floor(pct=30.0):
    return SV.SolarVentDecision(active=True, floor_pct=pct, solar_w=650.0, sun_on=True,
                                t_line=26.7, excess_c=2.0)


def _cctx(sv=None, **kw):
    """실외가 더 건조 → 열면 VPD 가 오른다. 실내 VPD 는 목표보다 높다(+0.5) → PI 는 닫는다."""
    T = 28.0
    svp = 0.6108 * math.exp(17.27 * T / (T + 237.3))
    ctx = {'cycle_sec': 600.0, 'T_ext': T, 'T_int': 28.7,
           'RH_ext': (1.0 - 2.2 / svp) * 100.0, 'vent_futility_gate': False,
           'internal': {}, 'external': {}}
    if sv is not None:
        ctx['solar_vent'] = sv
    ctx.update(kw)
    return ctx


def _run(profiles, ctx, prev=40.0, cycles=1, dev=+0.5, integral=None):
    st = CoordinatorState()
    st.prev_commands = {p.actuator_id: prev for p in profiles}
    st.integral = {p.actuator_id: (prev if integral is None else integral) for p in profiles}
    cmds = None
    for _ in range(cycles):
        cmds, st = coordinate(_Situation({'vpd': dev}, ctx), profiles, st, unique_id='')
    return cmds, st


class TestFloorInCoordinate:

    def test_baseline_vpd_closes_the_vent(self):
        """대조 — 하한이 없으면 종전대로 VPD 가 창을 닫는다."""
        cmds, _ = _run([_p('v')], _cctx(), cycles=4)
        assert cmds['v'].control_value() < 5.0

    def test_vpd_cannot_close_below_the_floor(self):
        cmds, st = _run([_p('v')], _cctx(_floor(30.0)), cycles=6)
        assert cmds['v'].control_value() == pytest.approx(30.0)
        assert cmds['v'].reason == LC.REASON_SOLAR_VENT_FLOOR
        assert st.integral['v'] >= 30.0 - 1e-9

    def test_no_gradient_is_lifted_too(self):
        """구동력 0(근거 15 경로)이어도 하한까지는 연다."""
        cmds, _ = _run([_p('v', magnitude=0.0)], _cctx(_floor(25.0)), cycles=3)
        assert cmds['v'].control_value() == pytest.approx(25.0)
        assert cmds['v'].reason == LC.REASON_SOLAR_VENT_FLOOR

    def test_the_pi_may_open_beyond_the_floor(self):
        """VPD 가 낮아(열라는 요구) PI 가 하한보다 더 열면 근거는 주작용 그대로다."""
        cmds, _ = _run([_p('v')], _cctx(_floor(20.0)), dev=-0.5, cycles=3)
        assert cmds['v'].control_value() > 20.0
        assert cmds['v'].reason == LC.REASON_PRIMARY

    def test_inactive_decision_does_nothing(self):
        sv = SV.SolarVentDecision(active=False, floor_pct=0.0)
        cmds, _ = _run([_p('v')], _cctx(sv), cycles=4)
        assert cmds['v'].control_value() < 5.0

    def test_release_carries_the_integral(self):
        """하한이 풀려도 적분은 하한 자리에서 출발한다 — 0 으로 쾅 닫히지 않는다."""
        prof = [_p('v')]
        _, st = _run(prof, _cctx(_floor(30.0)), cycles=4)
        assert st.integral['v'] >= 30.0 - 1e-9

    def test_fans_only_when_there_is_no_opening(self):
        prof = [_p('v'), _p('f', kind='exhaust_fan')]
        cmds, _ = _run(prof, _cctx(_floor(30.0)), cycles=4)
        assert cmds['v'].reason == LC.REASON_SOLAR_VENT_FLOOR
        assert cmds['f'].reason != LC.REASON_SOLAR_VENT_FLOOR
        cmds, _ = _run([_p('f', kind='exhaust_fan')], _cctx(_floor(30.0)), cycles=4)
        assert cmds['f'].control_value() == pytest.approx(30.0)


class TestWinners:
    """하한보다 앞서는 판정 — 이것들이 서 있으면 하한을 걸지 않는다."""

    def _ids(self, ctx, prof=None, prev=40.0):
        prof = prof or [_p('v')]
        pk = decide_parking(prof, _Situation({'vpd': 0.5}, ctx), ctx, 600.0,
                            {p.actuator_id: prev for p in prof}, log=False)
        return pk

    def test_outdoor_invented_holds(self):
        ctx = _cctx(_floor(), external={'_ext_synthetic': True})
        assert not self._ids(ctx).solar_floor_ids
        cmds, _ = _run([_p('v')], ctx, prev=10.0)
        assert cmds['v'].reason == LC.REASON_NO_OUTDOOR_DATA
        assert cmds['v'].control_value() == pytest.approx(10.0)

    def test_rain_wind_unknown_means_no_further_opening(self):
        ctx = _cctx(_floor(), vent_open_ceiling=True)
        assert not self._ids(ctx).solar_floor_ids
        cmds, _ = _run([_p('v')], ctx, prev=10.0, cycles=3)
        assert cmds['v'].control_value() <= 10.0 + 1e-9

    def test_night_parking_wins(self):
        assert not self._ids(_cctx(_floor(), night_vent_park=True)).solar_floor_ids

    def test_prepark_taper_wins(self):
        ctx = _cctx(_floor(30.0), night_vent_taper_s=600.0)
        assert not self._ids(ctx).solar_floor_ids
        cmds, _ = _run([_p('v')], ctx, prev=10.0, cycles=3)
        assert cmds['v'].control_value() <= 10.0 + 1e-9

    def test_hvac_interlock_wins(self):
        ctx = _cctx(_floor(), hvac_interlock=True, hvac_running=True)
        assert not self._ids(ctx).solar_floor_ids

    def test_heat_protect_hot_outside_wins_but_open_vents_keep_the_floor(self):
        closed = HeatProtectDecision(tier=1, threshold=30.0, vent_open_ok=False,
                                     vent_closed_ids=frozenset({'v'}))
        assert not self._ids(_cctx(_floor(), heat_protect=closed)).solar_floor_ids
        opened = HeatProtectDecision(tier=1, threshold=30.0, vent_open_ok=True,
                                     vent_open_ids=frozenset({'v'}))
        pk = self._ids(_cctx(_floor(70.0), heat_protect=opened))
        assert pk.solar_floor_ids == {'v'} and pk.solar_floor_pct == pytest.approx(70.0)

    def test_the_floor_beats_vent_futility(self):
        """환기 무익(실외로 목표에 못 감)은 VPD 만 본 판정이다 — 일사 열은 그래도 빼야 한다."""
        ctx = _cctx(_floor(30.0), vent_futility_gate=True)
        cmds, _ = _run([_p('v')], ctx, prev=0.0, cycles=4)
        assert cmds['v'].control_value() == pytest.approx(30.0)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 배선 — 사이클이 결론을 context 에 싣는다
# ─────────────────────────────────────────────────────────────────────────────

class TestCycleWiring:

    def _coord(self):
        c = CustomModule.__new__(CustomModule)
        c.logger = MagicMock()
        c.unique_id = 'fn'
        c._status_log = MagicMock()
        return c

    def test_it_publishes_the_decision_and_the_effective_delta(self):
        c = self._coord()
        sit = SimpleNamespace(context=_sctx(), target=_tc())
        c._evaluate_solar_vent(sit, HeatProtectDecision(tier=0, threshold=30.0))
        assert sit.context['solar_vent'].active
        assert '_solar_vent_dT' not in sit.context
        c._status_log.assert_called_once()
        # 같은 상태가 이어지면 다시 말하지 않는다
        c._evaluate_solar_vent(sit, HeatProtectDecision(tier=0, threshold=30.0))
        c._status_log.assert_called_once()

    def test_it_hands_the_stage_temperature_and_band_mode_to_the_line(self):
        c = self._coord()
        c._last_stage_guide = {'T_stage': 27.0}
        c._last_basis_summary = {'mode': 'vpd', 'temperature': {'T_mode': 'stage'}}
        sit = SimpleNamespace(context=_sctx(T_guide_low=22.0, T_ceiling=32.0), target=_tc(30.5))
        c._evaluate_solar_vent(sit, HeatProtectDecision(tier=0, threshold=30.0))
        assert sit.context['T_stage'] == 27.0 and sit.context['T_basis_band'] is False
        assert sit.context['solar_vent'].t_line == pytest.approx(28.0)
        c._last_stage_guide = None
        c._last_basis_summary = {'mode': 'temperature', 'temperature': {'T_mode': 'band'}}
        c._evaluate_solar_vent(sit, None)
        assert sit.context['T_stage'] is None and sit.context['T_basis_band'] is True

    def test_it_reads_the_screen_cloud_memory(self):
        c = self._coord()
        c._clear_sky_now = 700.0
        c._screen_state = SimpleNamespace(cloud_ratio=0.6)
        sit = SimpleNamespace(context=_sctx(solar=None), target=_tc())
        c._evaluate_solar_vent(sit, None)
        assert sit.context['solar_vent'].solar_w == pytest.approx(420.0)
