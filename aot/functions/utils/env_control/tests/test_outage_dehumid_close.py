# coding=utf-8
"""두절이 30 분 넘게 이어지면 **밤에 제습으로 열린 창**을 단계로 닫는다 (2026-10-12 김제, 근거 58).

## 실측

    김제 10/10 22:30 → 01:30   RH 91~95 % > humid_max 90 % → 하드 습도 상한이 야간 파킹을 풀어 창 25~30 % 로 제습.
                               이어서 기상청 값이 끊겼고(EXT_EXP / 실외 모름) 창은 3 시간 13~25 % 로 묶였다(근거 16).
    PR #161 은 하드 한계가 환기를 원하는 동안 '해 진 뒤 ≤ 10 % 닫기' 를 건너뛴다 — 그래서 이 경우는 그대로였다.

## 규칙 (사용자 결정 가)

    두절(실외 지어냄 `_ext_synthetic` 또는 강우·풍속 잃음) 시계 ≥ 30 분, 밤(맑은 하늘 일사 < 50 W/m² 또는 파킹 옵션이 켜진
    밤의 해제), 습도 때문에 열린 창(`_force_dehumid` / 파킹 해제) → 사이클당 5 %p 씩 0 까지, 근거 58, 적분 정렬.
    30 분 안은 종전. 온도 비상·극한 고온 보호·낮은 그대로. 값이 돌아오면 시계가 0 이라 보통의 제어. 시계는 재시작을 넘는다.
"""
import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.utils.env_control import cycle_memory
from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control import outage_clock as OC
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.coordinator import (
    OUTAGE_DEHUMID_STEP_PCT, CoordinatorState, coordinate, decide_parking,
    limit_vent_for_unknown_outdoor, outage_close_command,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)

LONG = OC.OUTAGE_DEHUMID_GRACE_S + 60.0      # 31 분째
SHORT = OC.OUTAGE_DEHUMID_GRACE_S - 60.0     # 29 분째
STEP = OUTAGE_DEHUMID_STEP_PCT


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, deviation, context):
        self.target = {'vpd': TargetVar(value=1.0, tolerance=0.1, priority=1.2, unit='kPa')}
        self.deviation_native = deviation
        self.context = context


def _p(aid='v', kind='opening', magnitude=0.4):
    p = ActuatorProfile(
        actuator_id=aid, kind=kind, effect_model={'vpd': _effect('↑', magnitude)},
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)
    p.cmd_scale = 1.0
    return p


def _ctx(**kw):
    T = 24.0
    svp = 0.6108 * math.exp(17.27 * T / (T + 237.3))
    ctx = {'cycle_sec': 600.0, 'T_ext': T, 'T_int': 24.0,
           'RH_ext': (1.0 - 1.0 / svp) * 100.0, 'vent_futility_gate': False,
           'internal': {'_force_dehumid': True}, 'external': {'_ext_synthetic': True},
           'clear_sky_now': 0.0, 'outdoor_outage_s': LONG}
    ctx.update(kw)
    return ctx


def _weather_lost(**kw):
    """실외 온습도는 있으나 강우·풍속을 잃음(게이트 EXT_EXP) — '더 열지 않음' 경로."""
    kw.setdefault('external', {})
    kw.setdefault('vent_open_ceiling', True)
    return _ctx(**kw)


def _series(ctx, prev=25.0, cycles=1, profiles=None, dev=-0.5, ctx_by_cycle=None):
    """사이클마다 나간 개도에서 이어서 — [(명령, 근거)] 와 마지막 상태."""
    profiles = profiles or [_p()]
    st = CoordinatorState()
    st.prev_commands = {p.actuator_id: prev for p in profiles}
    st.integral = {p.actuator_id: prev for p in profiles}
    out = []
    for i in range(cycles):
        c = (ctx_by_cycle[i] if ctx_by_cycle else ctx)
        cmds, st = coordinate(_Situation({'vpd': dev}, dict(c)), profiles, st, unique_id='')
        out.append((cmds['v'].control_value(), cmds['v'].reason))
        st.prev_commands = {p.actuator_id: cmds[p.actuator_id].control_value() for p in profiles}
    return out, st


# ─────────────────────────────────────────────────────────────────────────────
# 1. 규칙
# ─────────────────────────────────────────────────────────────────────────────

class TestShortOutageIsUnchanged:

    @pytest.mark.parametrize('make', [_ctx, _weather_lost])
    def test_under_thirty_minutes_the_vent_holds_with_reason_16(self, make):
        """30 분 안의 끊김은 종전대로 — 제습 중인 창을 흔들지 않는다."""
        (val, why), _ = _series(make(outdoor_outage_s=SHORT), prev=25.0)[0][0], None
        assert why == LC.REASON_NO_OUTDOOR_DATA
        assert val == pytest.approx(25.0)

    def test_exactly_at_the_grace_it_starts(self):
        (val, why), = _series(_ctx(outdoor_outage_s=OC.OUTAGE_DEHUMID_GRACE_S), prev=25.0)[0]
        assert why == LC.REASON_OUTAGE_CLOSE and val == pytest.approx(25.0 - STEP)

    def test_no_clock_means_no_outage_rule(self):
        (val, why), = _series(_ctx(outdoor_outage_s=None), prev=25.0)[0]
        assert why == LC.REASON_NO_OUTDOOR_DATA and val == pytest.approx(25.0)


class TestStepwiseClose:

    @pytest.mark.parametrize('make', [_ctx, _weather_lost])
    def test_closes_five_points_per_cycle_down_to_zero_with_reason_58(self, make):
        """김제 25~30 % 제습 창 — 두절 30 분 뒤 사이클당 5 %p 씩, 근거 58."""
        series, st = _series(make(), prev=28.0, cycles=7)
        vals = [v for v, _ in series]
        assert vals == pytest.approx([23.0, 18.0, 13.0, 8.0, 3.0, 0.0, 0.0])
        assert all(w == LC.REASON_OUTAGE_CLOSE for _, w in series[:6])
        assert st.integral['v'] == pytest.approx(0.0)

    @pytest.mark.parametrize('make', [_ctx, _weather_lost])
    def test_the_integral_follows_the_command(self, make):
        _, st = _series(make(), prev=25.0, cycles=1)
        assert st.integral['v'] == pytest.approx(20.0)

    def test_once_closed_it_holds_at_zero_and_never_reopens(self):
        """닫힌 뒤에는 제자리(16) — 두절 중에는 열지 않는다. 습도가 더 올라도(dev 큼)."""
        series, _ = _series(_ctx(), prev=5.0, cycles=4, dev=-2.0)
        assert [v for v, _ in series] == pytest.approx([0.0, 0.0, 0.0, 0.0])
        assert series[1][1] == LC.REASON_NO_OUTDOOR_DATA

    def test_never_exceeds_prev_and_is_monotonic(self):
        vals = [v for v, _ in _series(_ctx(), prev=30.0, cycles=8)[0]]
        assert vals == sorted(vals, reverse=True)
        assert all(a - b <= STEP + 1e-9 for a, b in zip([30.0] + vals, vals))

    def test_a_shorter_cycle_scales_the_step_by_time(self):
        """시간당 속도는 같다 — 300 초 사이클은 2.5 %p."""
        (val, _), = _series(_ctx(cycle_sec=300.0), prev=25.0)[0]
        assert val == pytest.approx(25.0 - STEP / 2)

    def test_a_longer_cycle_is_capped_at_five_points(self):
        (val, _), = _series(_ctx(cycle_sec=1200.0), prev=25.0)[0]
        assert val == pytest.approx(25.0 - STEP)

    def test_a_small_remainder_goes_straight_to_zero(self):
        (val, why), = _series(_ctx(), prev=3.0)[0]
        assert val == 0.0 and why == LC.REASON_OUTAGE_CLOSE

    def test_the_step_is_gentler_than_halving_for_large_openings(self):
        """결정의 근거 — ×0.5 는 30 % 에서 15 %p 를 한 번에 내린다."""
        (val, _), = _series(_ctx(), prev=30.0)[0]
        assert 30.0 - val < 30.0 * 0.5


class TestOnlyHumidityOpenedWindowsAtNight:

    def test_daytime_large_opening_is_not_touched(self):
        """낮에 크게 열린 창은 두절 시계가 길어도 그대로(PR #161 과 같다)."""
        for cs in (50.0, 300.0, 800.0):
            (val, why), = _series(_ctx(clear_sky_now=cs), prev=40.0)[0]
            assert why == LC.REASON_NO_OUTDOOR_DATA, cs
            assert val == pytest.approx(40.0)

    def test_unknown_sun_is_not_guessed(self):
        (val, why), = _series(_ctx(clear_sky_now=None), prev=25.0)[0]
        assert why == LC.REASON_NO_OUTDOOR_DATA and val == pytest.approx(25.0)

    def test_heat_hard_limit_wins(self):
        ctx = _ctx(internal={'_force_dehumid': True, '_force_cool': True})
        (val, why), = _series(ctx, prev=25.0)[0]
        assert why != LC.REASON_OUTAGE_CLOSE and val >= 25.0 - 1e-9

    def test_extreme_heat_protection_wins(self):
        hp = HeatProtectDecision(tier=2, vent_open_ids=frozenset({'v'}))
        (val, why), = _series(_ctx(heat_protect=hp), prev=25.0)[0]
        assert why != LC.REASON_OUTAGE_CLOSE and val >= 25.0 - 1e-9

    def test_without_the_humidity_reason_at_night_it_is_not_this_rule(self):
        """제습이 아닌 밤의 열림(하드 한계 없음·파킹 해제 아님)은 이 규칙의 대상이 아니다 — 종전 제자리."""
        ctx = _ctx(internal={})
        (val, why), = _series(ctx, prev=25.0)[0]
        assert why == LC.REASON_NO_OUTDOOR_DATA and val == pytest.approx(25.0)

    def test_night_release_without_the_hard_limit_counts(self):
        """야간 파킹 옵션이 켜진 밤인데 파킹이 풀려 있으면(습도·결로 탈출) 하드 한계 없이도."""
        ctx = _weather_lost(internal={}, night_vent_released=True, clear_sky_now=None)
        (val, why), = _series(ctx, prev=25.0)[0]
        assert why == LC.REASON_OUTAGE_CLOSE and val == pytest.approx(25.0 - STEP)

    def test_still_parked_windows_follow_the_parking(self):
        """파킹 중이면 야간 파킹(19)이 닫는다 — 이 규칙의 대상이 아니다."""
        ctx = _ctx(internal={}, night_vent_park=True)
        (val, why), = _series(ctx, prev=25.0)[0]
        assert why == LC.REASON_NIGHT_PARKED

    def test_fans_are_not_closed_by_this_rule(self):
        profiles = [_p('f', kind='exhaust_fan')]
        st = CoordinatorState()
        st.prev_commands, st.integral = {'f': 60.0}, {'f': 60.0}
        cmds, _ = coordinate(_Situation({'vpd': -0.5}, _ctx()), profiles, st, unique_id='')
        assert cmds['f'].reason != LC.REASON_OUTAGE_CLOSE

    def test_known_outdoor_is_untouched(self):
        """값이 돌아오면 시계가 None → 보통의 제어. (PI 가 정하므로 58 이 아니면 된다)"""
        ctx = _ctx(external={}, outdoor_outage_s=None, vent_open_ceiling=False)
        (val, why), = _series(ctx, prev=25.0, dev=-0.5)[0]
        assert why != LC.REASON_OUTAGE_CLOSE


class TestResumesWhenDataReturns:

    def test_closing_stops_and_the_pi_takes_over_in_the_next_cycle(self):
        out = _ctx()
        back = _ctx(external={}, outdoor_outage_s=None, vent_open_ceiling=False)
        series, _ = _series(None, prev=28.0, cycles=4,
                            ctx_by_cycle=[out, out, back, back], dev=-1.0)
        assert [w for _, w in series[:2]] == [LC.REASON_OUTAGE_CLOSE] * 2
        assert all(w != LC.REASON_OUTAGE_CLOSE for _, w in series[2:])

    def test_it_can_reopen_after_the_data_returns(self):
        """래치가 없다 — 값이 돌아온 뒤 습도가 높고 실외가 건조하면 PI 가 다시 연다."""
        out = _ctx(external={'_ext_synthetic': True})
        back = _ctx(external={}, outdoor_outage_s=None, vent_open_ceiling=False)
        series, _ = _series(None, prev=25.0, cycles=8,
                            ctx_by_cycle=[out] * 6 + [back] * 2, dev=-2.0)
        assert series[5][0] == pytest.approx(0.0)
        assert series[7][0] > 0.0


class TestMpcPathReadsTheSameRule:

    def _pk(self, ctx, prev):
        return decide_parking([_p()], _Situation({'vpd': 0.0}, ctx), ctx, 600.0,
                              {'v': prev}, log=False)

    def test_decision_carries_the_step(self):
        pk = self._pk(_ctx(), 25.0)
        assert pk.outage_dehumid_ids == {'v'} and pk.outage_dehumid_step_pct == pytest.approx(STEP)
        assert limit_vent_for_unknown_outdoor(_ctx(), _p(), 60.0, 25.0, pk) == (
            pytest.approx(25.0 - STEP), LC.REASON_OUTAGE_CLOSE)

    def test_short_outage_has_no_decision(self):
        pk = self._pk(_ctx(outdoor_outage_s=SHORT), 25.0)
        assert not pk.outage_dehumid_ids
        assert outage_close_command(pk, _p(), 25.0) is None

    def test_the_command_never_exceeds_prev(self):
        pk = self._pk(_ctx(), 25.0)
        val, _ = outage_close_command(pk, _p(), 25.0)
        assert val <= 25.0

    def test_a_small_opening_still_uses_the_one_shot_zero_when_the_hard_limit_is_off(self):
        """PR #161 의 '≤ 10 % → 0' 은 하드 한계 없이 밤 해제일 때 그대로 앞선다."""
        ctx = _weather_lost(internal={}, night_vent_released=True)
        pk = self._pk(ctx, 5.0)
        assert 'v' in pk.outage_zero_ids and 'v' in pk.outage_dehumid_ids
        assert outage_close_command(pk, _p(), 5.0) == (0.0, LC.REASON_OUTAGE_CLOSE)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 두절 시계
# ─────────────────────────────────────────────────────────────────────────────

class TestOutageClock:

    def test_counts_while_lost_and_resets_when_found(self):
        st = OC.OutageState()
        assert OC.update(st, False, 1000.0) is None
        assert OC.update(st, True, 1100.0) == 0.0
        assert OC.update(st, True, 1700.0) == pytest.approx(600.0)
        assert OC.update(st, True, 2300.0) == pytest.approx(1200.0)
        assert OC.update(st, False, 2900.0) is None and st.since is None
        assert OC.update(st, True, 3500.0) == 0.0            # 다시 처음부터 — 래치 없음

    def test_a_long_gap_between_cycles_restarts_the_clock(self):
        """제어가 멈춰 있던(시간창 밖·정지) 동안은 두절로 세지 않는다."""
        st = OC.OutageState()
        OC.update(st, True, 1000.0)
        OC.update(st, True, 1600.0)
        assert OC.update(st, True, 1600.0 + OC.MAX_GAP_S + 1.0) == 0.0

    def test_a_clock_that_goes_backwards_restarts(self):
        st = OC.OutageState()
        OC.update(st, True, 5000.0)
        assert OC.update(st, True, 4000.0) == 0.0


class _Clock:
    t = 1_800_000_000.0


class TestClockSurvivesARestart:

    def _coord(self, monkeypatch, clock):
        monkeypatch.setattr('time.time', lambda: clock.t)
        c = CustomModule.__new__(CustomModule)
        c.logger = MagicMock()
        c.night_vent_park = False
        return c

    def _eval(self, c, **ext):
        sit = SimpleNamespace(context={})
        c._evaluate_outdoor_outage(sit, ext, SimpleNamespace(vent_open_ceiling=False), False)
        return sit.context

    def test_restart_keeps_the_thirty_minute_clock(self, monkeypatch):
        clock = _Clock()
        a = self._coord(monkeypatch, clock)
        for _ in range(3):                                   # 20 분 두절
            ctx = self._eval(a, _ext_synthetic=True)
            clock.t += 600.0
        assert ctx['outdoor_outage_s'] == pytest.approx(1200.0)
        blob = cycle_memory.export_memory(a, clock.t)

        # 재시작 — 새 프로세스, 실외 캐시가 비어 곧바로 '지어낸 값'
        b = self._coord(monkeypatch, clock)
        clock.t += 60.0
        assert '_outage_state' in cycle_memory.restore_memory(b, blob, clock.t)
        ctx = self._eval(b, _ext_synthetic=True)
        assert ctx['outdoor_outage_s'] == pytest.approx(1860.0)   # 재시작이 시계를 0 으로 돌리지 않는다
        assert ctx['outdoor_outage_s'] >= OC.OUTAGE_DEHUMID_GRACE_S

    def test_without_the_memory_the_clock_starts_over(self, monkeypatch):
        clock = _Clock()
        b = self._coord(monkeypatch, clock)
        assert self._eval(b, _ext_synthetic=True)['outdoor_outage_s'] == 0.0

    def test_a_stale_memory_is_dropped(self, monkeypatch):
        clock = _Clock()
        a = self._coord(monkeypatch, clock)
        self._eval(a, _ext_synthetic=True)
        blob = cycle_memory.export_memory(a, clock.t)
        clock.t += cycle_memory.MEMORY_MAX_AGE_S + 60.0      # 반나절 멈춘 뒤
        b = self._coord(monkeypatch, clock)
        assert '_outage_state' not in cycle_memory.restore_memory(b, blob, clock.t)

    def test_data_back_resets_the_clock(self, monkeypatch):
        clock = _Clock()
        a = self._coord(monkeypatch, clock)
        self._eval(a, _ext_synthetic=True)
        clock.t += 900.0
        assert self._eval(a, T=10.0)['outdoor_outage_s'] is None


class TestMixinContext:

    def _coord(self, monkeypatch, clock, *, option, night):
        monkeypatch.setattr('time.time', lambda: clock.t)
        c = CustomModule.__new__(CustomModule)
        c.logger = MagicMock()
        c.night_vent_park = option
        c._night_vent_clock = lambda: (night, None)
        return c

    def test_weather_lost_alone_counts_as_an_outage(self, monkeypatch):
        clock = _Clock()
        c = self._coord(monkeypatch, clock, option=False, night=True)
        sit = SimpleNamespace(context={})
        c._evaluate_outdoor_outage(sit, {}, SimpleNamespace(vent_open_ceiling=True), False)
        assert sit.context['outdoor_outage_s'] == 0.0

    def test_night_released_needs_the_option_the_night_and_a_long_outage(self, monkeypatch):
        clock = _Clock()
        gate = SimpleNamespace(vent_open_ceiling=True)

        def run(option, night, parked, wait):
            c = self._coord(monkeypatch, clock, option=option, night=night)
            sit = SimpleNamespace(context={})
            c._evaluate_outdoor_outage(sit, {}, gate, parked)
            while wait > 0.0:                                  # 사이클은 10 분 간격으로 돈다
                clock.t += min(600.0, wait)
                wait -= 600.0
                c._evaluate_outdoor_outage(sit, {}, gate, parked)
            return sit.context['night_vent_released']

        assert run(True, True, False, LONG) is True
        assert run(True, True, False, SHORT) is False          # 30 분 전엔 계산하지 않는다
        assert run(False, True, False, LONG) is False          # 옵션이 없다
        assert run(True, False, False, LONG) is False          # 낮이다
        assert run(True, True, True, LONG) is False            # 파킹 중이다
