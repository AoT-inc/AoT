# coding=utf-8
"""실외를 모르는 동안 **닫는 쪽은 허용** (근거 58, 2026-10-12) + 일사 하한은 풀리면 바로 푼다(내림 램프 되돌림).

## 실측

    김제 10/10 22:30 → 01:30   밤새 제습으로 창 25 % → 기상청 값 끊김(EXT_EXP) → 3 시간 13~25 % 로 묶임(근거 16)
    폐루프 sensor_storm_outage  해 질 녘 5 % 로 열린 창이 `r16` 에 붙잡혀 비 70 분을 맞음 (screens)

## 규칙

    실외 모름(2.6 제자리)은 **여는 쪽만** 막는다. 야간 파킹(19)은 그대로 닫고, 마지막 실측 비·강풍의 상한(52·55)도
    건다. 해가 진 뒤(맑은 하늘 일사 < 50 W/m²) 조금(≤ 10 %) 열린 개구부는 0 으로 닫는다(근거 58).
    낮에 크게 열린 창은 닫지 않는다(더위).
    일사 하한의 내림 램프(#161)는 창 반전을 늘려 되돌렸다 — 판단이 풀리면 하한도 바로 풀린다(#136 과 같다).
"""
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator import CustomModule

from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control import solar_vent as SV
from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate, decide_parking, limit_vent_for_unknown_outdoor,
    outage_close_command,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, deviation, context):
        self.target = {'vpd': TargetVar(value=1.0, tolerance=0.1, priority=1.2, unit='kPa')}
        self.deviation_native = deviation
        self.context = context


def _p(aid='v', kind='opening', magnitude=0.4, safe_default=0.0):
    p = ActuatorProfile(
        actuator_id=aid, kind=kind, effect_model={'vpd': _effect('↑', magnitude)},
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=safe_default)
    p.cmd_scale = 1.0
    return p


def _ctx(**kw):
    T = 24.0
    svp = 0.6108 * math.exp(17.27 * T / (T + 237.3))
    ctx = {'cycle_sec': 600.0, 'T_ext': T, 'T_int': 24.0,
           'RH_ext': (1.0 - 1.0 / svp) * 100.0, 'vent_futility_gate': False,
           'internal': {}, 'external': {}}
    ctx.update(kw)
    return ctx


def _outage(**kw):
    """실외를 지어낸 사이클 — 맑은 하늘 일사만 안다(좌표)."""
    kw.setdefault('external', {'_ext_synthetic': True})
    return _ctx(**kw)


def _run(profiles, ctx, prev=40.0, cycles=1, dev=-0.5, integral=None, state=None):
    st = state or CoordinatorState()
    if state is None:
        st.prev_commands = {p.actuator_id: prev for p in profiles}
        st.integral = {p.actuator_id: (prev if integral is None else integral) for p in profiles}
    cmds = None
    for _ in range(cycles):
        cmds, st = coordinate(_Situation({'vpd': dev}, ctx), profiles, st, unique_id='')
        # 다음 사이클은 나간 개도에서 시작한다.
    return cmds, st


# ─────────────────────────────────────────────────────────────────────────────
# 1. 실외 모름 — 닫는 쪽 허용
# ─────────────────────────────────────────────────────────────────────────────

class TestNightParkingStillCloses:

    def test_parking_decays_the_vent_with_reason_19(self):
        """김제 22:30 → 01:30 — 야간 파킹은 실외를 몰라도 창을 닫는다(종전엔 16 으로 25 % 붙잡힘)."""
        ctx = _outage(night_vent_park=True, clear_sky_now=0.0)
        cmds, st = _run([_p()], ctx, prev=25.0, cycles=1, dev=-0.5)
        assert cmds['v'].reason == LC.REASON_NIGHT_PARKED
        assert cmds['v'].control_value() < 25.0 - 1e-6
        assert st.integral['v'] == pytest.approx(cmds['v'].control_value())

    def test_it_keeps_closing_each_cycle(self):
        ctx = _outage(night_vent_park=True, clear_sky_now=0.0)
        prof = [_p()]
        vals = []
        st = CoordinatorState()
        st.prev_commands, st.integral = {'v': 25.0}, {'v': 25.0}
        for _ in range(5):
            cmds, st = coordinate(_Situation({'vpd': -0.5}, ctx), prof, st, unique_id='')
            vals.append(cmds['v'].control_value())
        assert vals == sorted(vals, reverse=True) and vals[-1] < 5.0

    def test_without_the_option_the_vent_holds(self):
        ctx = _outage(clear_sky_now=300.0)
        cmds, _ = _run([_p()], ctx, prev=25.0, cycles=3)
        assert cmds['v'].reason == LC.REASON_NO_OUTDOOR_DATA
        assert cmds['v'].control_value() == pytest.approx(25.0)

    def test_it_never_opens(self):
        """열라는 요구가 아무리 커도(VPD 낮음) 실외 모름이면 밤에도 열지 않는다."""
        ctx = _outage(night_vent_park=True, clear_sky_now=0.0)
        cmds, _ = _run([_p()], ctx, prev=0.0, cycles=3, dev=-2.0)
        assert cmds['v'].control_value() == pytest.approx(0.0)

    def test_the_hard_limits_release_the_parking_and_the_hold(self):
        """하드 한계가 열라고 하는 동안은 닫지 않는다(호출자가 파킹을 풀어 night_vent_park 가 거짓)."""
        ctx = _outage(night_vent_park=False, clear_sky_now=0.0,
                      internal={'_force_cool': True})
        cmds, _ = _run([_p()], ctx, prev=8.0, cycles=2)
        assert cmds['v'].control_value() == pytest.approx(8.0)
        assert cmds['v'].reason == LC.REASON_NO_OUTDOOR_DATA


class TestExpiredOutdoorDoesNotLiftTheParking:
    """김제 10/10 — 제습으로 열린 창이 기상청 값이 끊긴 뒤에도 밤새 13~25 % 로 남았다.

    결로 탈출구는 "실외가 지금 건조하다" 가 근거다. 만료돼 마지막 캐시(`_stale`)나 지어낸 값(`_ext_synthetic`)으로 판단하는
    동안은 그 근거가 못 되므로 파킹을 풀지 않는다 — 창은 근거 19 로 닫힌다.
    """
    NIGHT = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)           # 18:00 KST = 일몰
    SUNRISE = datetime(2026, 10, 8, 21, 20, tzinfo=timezone.utc)

    def _coord(self, monkeypatch):
        c = CustomModule.__new__(CustomModule)
        c.logger = MagicMock()
        c.unique_id = 'fn'
        c.night_vent_park = True
        c.night_vent_basis = 'sun'
        c.night_vent_sunset_offset_min = 10.0
        st = SimpleNamespace(sunset=self.NIGHT, sunrise=self.SUNRISE)
        monkeypatch.setattr('aot.utils.solar.sun_times', lambda **kw: st)
        monkeypatch.setattr('aot.utils.timekit.utc_now', lambda: self.NIGHT + timedelta(hours=1))
        return c

    IN = {'T': 15, 'RH': 95}
    OUT = {'T': 12, 'RH': 60}          # 열면 결로가 덜어진다(탈출 조건)

    def test_a_fresh_outdoor_still_lifts_the_parking(self, monkeypatch):
        assert self._coord(monkeypatch)._night_vent_decide(self.IN, dict(self.OUT)) == (False, None)

    @pytest.mark.parametrize('marker', ['_stale', '_ext_synthetic'])
    def test_an_expired_outdoor_keeps_it(self, monkeypatch, marker):
        ext = dict(self.OUT, **{marker: True})
        assert self._coord(monkeypatch)._night_vent_decide(self.IN, ext) == (True, None)

    def test_the_hard_humidity_limit_still_lifts_it(self, monkeypatch):
        internal = dict(self.IN, _force_dehumid=True)
        ext = dict(self.OUT, _stale=True)
        assert self._coord(monkeypatch)._night_vent_decide(internal, ext) == (False, None)


class TestSmallOpeningsCloseAfterSunset:

    def test_five_percent_goes_to_zero_with_reason_58(self):
        """폐루프 sensor_storm_outage — 해 질 녘 5 % 가 비를 70 분 맞던 자리."""
        ctx = _outage(clear_sky_now=10.0)
        cmds, st = _run([_p()], ctx, prev=5.0)
        assert cmds['v'].reason == LC.REASON_OUTAGE_CLOSE == 58
        assert cmds['v'].control_value() == pytest.approx(0.0)
        assert st.integral['v'] == pytest.approx(0.0)

    def test_the_boundary_is_ten_percent(self):
        ctx = _outage(clear_sky_now=10.0)
        assert _run([_p()], ctx, prev=10.0)[0]['v'].reason == LC.REASON_OUTAGE_CLOSE
        c = _run([_p()], ctx, prev=12.0)[0]['v']
        assert c.reason == LC.REASON_NO_OUTDOOR_DATA and c.control_value() == pytest.approx(12.0)

    def test_an_already_closed_vent_keeps_reason_16(self):
        c = _run([_p()], _outage(clear_sky_now=0.0), prev=0.0)[0]['v']
        assert c.reason == LC.REASON_NO_OUTDOOR_DATA and c.control_value() == 0.0

    def test_not_while_the_sun_is_up(self):
        for cs in (50.0, 300.0, 800.0):
            c = _run([_p()], _outage(clear_sky_now=cs), prev=6.0)[0]['v']
            assert c.reason == LC.REASON_NO_OUTDOOR_DATA, cs
            assert c.control_value() == pytest.approx(6.0)

    def test_a_frozen_measured_sunlight_does_not_hold_the_vent_open(self):
        """두절 중 실측 일사는 마지막 값에서 굳는다(폐루프: 해 질 녘 74 W/m²). 맑은 하늘이 어두우면 어둡다."""
        ctx = _outage(clear_sky_now=5.0, internal={'_outdoor_solar': 74.0},
                      external={'_ext_synthetic': True, 'solar': 74.0})
        c = _run([_p()], ctx, prev=5.0)[0]['v']
        assert c.reason == LC.REASON_OUTAGE_CLOSE and c.control_value() == 0.0

    def test_unknown_sun_is_not_guessed(self):
        """좌표가 없어 맑은 하늘을 모르면 해가 졌다고 하지 않는다."""
        c = _run([_p()], _outage(), prev=6.0)[0]['v']
        assert c.reason == LC.REASON_NO_OUTDOOR_DATA and c.control_value() == pytest.approx(6.0)

    def test_a_widely_open_vent_is_not_closed_by_ignorance_alone(self):
        """낮 40 % 도, 밤 40 % 도(파킹 옵션이 없으면) 모른다는 이유만으로 닫지 않는다."""
        for cs in (800.0, 0.0):
            c = _run([_p()], _outage(clear_sky_now=cs), prev=40.0)[0]['v']
            assert c.reason == LC.REASON_NO_OUTDOOR_DATA
            assert c.control_value() == pytest.approx(40.0)

    def test_hard_limits_that_want_the_vent_open_win(self):
        for key in ('_force_cool', '_force_dehumid'):
            ctx = _outage(clear_sky_now=0.0, internal={key: True})
            c = _run([_p()], ctx, prev=5.0)[0]['v']
            assert c.reason == LC.REASON_NO_OUTDOOR_DATA
            assert c.control_value() == pytest.approx(5.0)

    def test_fans_are_not_closed_by_this_rule(self):
        c = _run([_p('f', kind='exhaust_fan')], _outage(clear_sky_now=0.0), prev=5.0)[0]['f']
        assert c.reason == LC.REASON_NO_OUTDOOR_DATA

    def test_known_outdoor_is_untouched(self):
        """실외를 아는 사이클에는 아무 영향이 없다."""
        ctx = _ctx(clear_sky_now=0.0)
        c = _run([_p()], ctx, prev=5.0, dev=-0.5)[0]['v']
        assert c.reason != LC.REASON_OUTAGE_CLOSE


class TestRainWindLostAlsoClosesSmallOpeningsAfterSunset:
    """폐루프 sensor_storm_outage — 마지막 값은 온화했고(`ceiling`), PI 는 열자고 하며 5 % 창이 제자리에 섰다."""

    def test_five_percent_closes_though_the_pi_wants_it_open(self):
        ctx = _ctx(vent_open_ceiling=True, clear_sky_now=0.0)
        c = _run([_p()], ctx, prev=5.0, dev=-0.5)[0]['v']
        assert c.reason == LC.REASON_OUTAGE_CLOSE
        assert c.control_value() == pytest.approx(0.0)

    def test_sun_up_keeps_the_old_no_further_opening(self):
        ctx = _ctx(vent_open_ceiling=True, clear_sky_now=300.0)
        c = _run([_p()], ctx, prev=5.0, dev=-0.5)[0]['v']
        assert c.reason == LC.REASON_NO_OUTDOOR_DATA
        assert c.control_value() == pytest.approx(5.0)

    def test_wider_openings_are_held_not_closed(self):
        ctx = _ctx(vent_open_ceiling=True, clear_sky_now=0.0)
        c = _run([_p()], ctx, prev=15.0, dev=-0.5)[0]['v']
        assert c.reason == LC.REASON_NO_OUTDOOR_DATA
        assert c.control_value() == pytest.approx(15.0)

    def test_the_hard_temperature_limit_still_lets_it_open(self):
        """`vent_open_ceiling_ids` 가 `_force_cool` 에서 비므로 닫기도 서지 않는다."""
        ctx = _ctx(vent_open_ceiling=True, clear_sky_now=0.0, internal={'_force_cool': True})
        c = _run([_p()], ctx, prev=5.0, dev=-0.5)[0]['v']
        assert c.reason != LC.REASON_OUTAGE_CLOSE

    def test_mpc_path_reads_the_same_rule(self):
        ctx = _ctx(vent_open_ceiling=True, clear_sky_now=0.0)
        pk = decide_parking([_p()], _Situation({'vpd': 0.0}, ctx), ctx, 600.0, {'v': 5.0}, log=False)
        assert pk.outage_zero_ids == {'v'}
        assert limit_vent_for_unknown_outdoor(ctx, _p(), 60.0, 5.0, pk) == (0.0, 58)
        assert limit_vent_for_unknown_outdoor(ctx, _p(), 60.0, 5.0) == (
            5.0, LC.REASON_NO_OUTDOOR_DATA)


class TestLastMeasuredRainAndWindCapsApplyDuringOutage:

    def test_a_numeric_cap_closes_a_held_vent(self):
        """마지막 실측이 비·강풍이었으면 상한까지 닫는다 — 제자리가 상한 위의 개도를 붙들면 안 된다."""
        ctx = _outage(vent_open_caps={'v': 30.0},
                      vent_open_cap_reasons={'v': LC.REASON_RAIN_RESTRICT})
        c = _run([_p()], ctx, prev=60.0, cycles=1)[0]['v']
        assert c.control_value() == pytest.approx(30.0)
        assert c.reason == LC.REASON_RAIN_RESTRICT

    def test_a_none_cap_only_holds(self):
        ctx = _outage(vent_open_caps={'v': None})
        c = _run([_p()], ctx, prev=60.0)[0]['v']
        assert c.control_value() == pytest.approx(60.0)


class TestMpcPathReadsTheSameRule:

    def _pk(self, ctx, prev):
        prof = [_p()]
        return decide_parking(prof, _Situation({'vpd': 0.0}, ctx), ctx, 600.0,
                              {'v': prev}, log=False)

    def test_night_parking_in_an_outage(self):
        ctx = _outage(night_vent_park=True, clear_sky_now=0.0)
        pk = self._pk(ctx, 25.0)
        assert pk.outage_park_ids == {'v'}
        val, why = limit_vent_for_unknown_outdoor(ctx, _p(), 60.0, 25.0, pk)
        assert why == LC.REASON_NIGHT_PARKED and val < 25.0

    def test_small_opening_after_sunset(self):
        ctx = _outage(clear_sky_now=0.0)
        pk = self._pk(ctx, 5.0)
        assert pk.outage_zero_ids == {'v'}
        assert limit_vent_for_unknown_outdoor(ctx, _p(), 60.0, 5.0, pk) == (0.0, 58)

    def test_without_the_decision_it_is_the_old_hold(self):
        ctx = _outage(clear_sky_now=0.0)
        assert limit_vent_for_unknown_outdoor(ctx, _p(), 60.0, 5.0) == (
            5.0, LC.REASON_NO_OUTDOOR_DATA)

    def test_the_command_never_exceeds_prev(self):
        ctx = _outage(night_vent_park=True, clear_sky_now=0.0)
        pk = self._pk(ctx, 25.0)
        val, _ = outage_close_command(pk, _p(), 25.0)
        assert val <= 25.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. 일사 하한 — 풀리면 바로 푼다 (내림 램프는 되돌렸다, 2026-10-12 최종 폐루프 회귀 R1·R5)
# ─────────────────────────────────────────────────────────────────────────────

def _sv(active, pct=0.0, why_off=None):
    return SV.SolarVentDecision(active=active, floor_pct=pct, solar_w=650.0, sun_on=True,
                                t_line=26.7, excess_c=2.0 if active else None,
                                why_off=why_off)


def _sctx(sv, **kw):
    T = 28.0
    svp = 0.6108 * math.exp(17.27 * T / (T + 237.3))
    ctx = {'cycle_sec': 600.0, 'T_ext': T, 'T_int': 28.7,
           'RH_ext': (1.0 - 2.2 / svp) * 100.0, 'vent_futility_gate': False,
           'internal': {}, 'external': {}, 'solar_vent': sv}
    ctx.update(kw)
    return ctx


class TestSolarFloorReleasesDirectly:
    """#161 의 내림 램프(사이클당 5 %p)는 PI 와 번갈아 창을 올렸다 내려 창 반전이 pre-#161 기준보다 나빠졌다
    (고친 뒤에도 normal 0.98 → 1.19 · fog 0.20 → 0.76 /h). 종전(#136)대로 판단이 풀리면 하한도 그 사이클에 풀린다 —
    짧은 켬/끔은 선 뒤 30 분 유지(`SV_MIN_ON_S`)가 맡는다."""

    def test_no_ramp_api_left(self):
        assert not hasattr(SV, 'release_floor')
        assert not hasattr(SV, 'SV_FLOOR_RELEASE_STEP_PCT')
        assert not hasattr(CoordinatorState(), 'solar_floor')

    def test_floor_holds_then_releases_in_one_cycle(self):
        st = CoordinatorState()
        st.prev_commands, st.integral = {'v': 0.0}, {'v': 0.0}
        on, off = _sv(True, 30.0), _sv(False, why_off='cool')
        cmds, st = coordinate(_Situation({'vpd': +0.5}, _sctx(on)), [_p()], st, unique_id='')
        assert cmds['v'].reason == LC.REASON_SOLAR_VENT_FLOOR
        assert cmds['v'].control_value() == pytest.approx(30.0)
        assert st.integral['v'] >= 30.0 - 1e-9                 # 적분도 하한에 묶인다(풀린 뒤 PI 가 그 자리에서)
        st.prev_commands = {'v': cmds['v'].control_value()}
        cmds, st = coordinate(_Situation({'vpd': +0.5}, _sctx(off)), [_p()], st, unique_id='')
        assert cmds['v'].reason != LC.REASON_SOLAR_VENT_FLOOR
