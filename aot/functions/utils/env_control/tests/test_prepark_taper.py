# coding=utf-8
"""야간 파킹 직전 완충 구간 — 곧 닫힐 창을 더 열지 않는다 (2026-10-09 김제 육묘장3).

## 실측

    16:48 12 % → 17:09 40 → 17:29 65 → 17:49 91 (근거 1 주작용)
    17:59 야간 파킹 시작(근거 19) → 18:42 0 %

해 질 무렵 실내 RH 가 오르고 실외가 더 건조해서 "환기하면 VPD 가 오른다" 가 창을 열었고,
10분 뒤 야간 파킹이 그 창을 닫았다.

## 구조

    판정(구간 안인가)   `_night_vent_clock`  — 파킹 시작과 같은 기준·같은 오프셋, 한 곳
    적용 대상           `decide_parking`     — ParkDecision.taper_ids
    명령·적분           `coordinate`         — 직전 개도에 묶고 적분은 그 자리를 넘지 않게

안전·한계 사유(온도 하드·습도 하드·극한 고온 보호·결로 탈출)는 구간을 풀고, 위치를 모르면
(태양시 없음) 구간이 없다.
"""
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.custom_functions.env_coordinator_impl import _helpers_mixin
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    NIGHT_VENT_TAPER_S,
)
from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate, decide_parking,
)
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 구간 판정 — 파킹 시작과 같은 기준이다
# ─────────────────────────────────────────────────────────────────────────────

_SUNSET = datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc)      # 18:00 KST
_SUNRISE = datetime(2026, 10, 8, 21, 20, tzinfo=timezone.utc)   # 06:20 KST


def _sun_coord(monkeypatch, now, offset=10.0, sunset=_SUNSET, sunrise=_SUNRISE,
               located=True):
    """일몰 기준 코디네이터. 태양시와 현재 시각만 갈아 끼운다."""
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.unique_id = 'fn'
    c.night_vent_park = True
    c.night_vent_basis = 'sun'
    c.night_vent_sunset_offset_min = offset
    st = SimpleNamespace(sunset=sunset, sunrise=sunrise) if located else None
    monkeypatch.setattr('aot.utils.solar.sun_times', lambda **kw: st)
    monkeypatch.setattr('aot.utils.timekit.utc_now', lambda: now)
    return c


def _clock_coord(now_local, start='18:00', end='06:00'):
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.unique_id = 'fn'
    c.night_vent_park = True
    c.night_vent_basis = 'clock'
    c.night_vent_start = start
    c.night_vent_end = end
    c._facility_local_now = lambda: now_local
    return c


class TestWindowBoundaries:
    """창은 `[파킹 시작 − 45분, 파킹 시작)` — 시작 포함, 끝 제외."""

    PARK_START = _SUNSET - timedelta(minutes=10)      # 17:50 KST

    def test_the_window_is_forty_five_minutes(self):
        assert NIGHT_VENT_TAPER_S == 45 * 60

    def test_it_ends_where_the_parking_starts(self, monkeypatch):
        c = _sun_coord(monkeypatch, self.PARK_START - timedelta(seconds=1))
        parked, until = c._night_vent_clock()
        assert parked is False and until == pytest.approx(1.0)
        # 시작 순간 — 파킹이 서고 구간은 끝난다(겹치지 않는다)
        c = _sun_coord(monkeypatch, self.PARK_START)
        assert c._night_vent_clock() == (True, None)

    def test_it_begins_exactly_forty_five_minutes_before(self, monkeypatch):
        c = _sun_coord(monkeypatch, self.PARK_START - timedelta(seconds=2700))
        assert c._night_vent_clock() == (False, 2700.0)
        c = _sun_coord(monkeypatch, self.PARK_START - timedelta(seconds=2701))
        assert c._night_vent_clock() == (False, None)

    def test_the_afternoon_has_no_window(self, monkeypatch):
        noon = datetime(2026, 10, 9, 3, 0, tzinfo=timezone.utc)
        c = _sun_coord(monkeypatch, noon)
        assert c._night_vent_clock() == (False, None)

    def test_before_sunrise_is_parked_not_a_window(self, monkeypatch):
        c = _sun_coord(monkeypatch, _SUNRISE - timedelta(minutes=30))
        assert c._night_vent_clock() == (True, None)

    def test_the_offset_moves_the_window_with_the_parking(self, monkeypatch):
        """오프셋 30분이면 파킹이 30분 일찍 시작하므로 창도 같이 당겨진다."""
        now = _SUNSET - timedelta(minutes=40)                 # 17:20 KST
        # 오프셋 0: 파킹 시작 18:00 → 40분 전 = 창 안(2400 s)
        assert _sun_coord(monkeypatch, now, offset=0.0)._night_vent_clock() == (
            False, 2400.0)
        # 오프셋 30: 파킹 시작 17:30 → 10분 전 = 창 안(600 s)
        assert _sun_coord(monkeypatch, now, offset=30.0)._night_vent_clock() == (
            False, 600.0)
        # 오프셋 60: 파킹 시작 17:00 → 이미 밤
        assert _sun_coord(monkeypatch, now, offset=60.0)._night_vent_clock() == (
            True, None)

    def test_a_negative_offset_is_discarded(self, monkeypatch):
        now = _SUNSET - timedelta(minutes=10)
        c = _sun_coord(monkeypatch, now, offset=-30.0)
        assert c._night_vent_clock() == (False, 600.0)       # 오프셋 0 으로 본다

    def test_clock_basis_uses_the_same_window(self):
        # 시설 현지 17:30, 시작 18:00 → 30분 전
        c = _clock_coord(datetime(2026, 10, 9, 17, 30, 0))
        assert c._night_vent_clock() == (False, 1800.0)
        assert _clock_coord(datetime(2026, 10, 9, 17, 15, 0))._night_vent_clock() == (
            False, 2700.0)
        assert _clock_coord(datetime(2026, 10, 9, 17, 14, 59))._night_vent_clock() == (
            False, None)
        assert _clock_coord(datetime(2026, 10, 9, 18, 0, 0))._night_vent_clock() == (
            True, None)

    def test_clock_basis_window_crosses_midnight(self):
        """시작이 00:10 인 짧은 밤도 자정을 넘어 센다."""
        c = _clock_coord(datetime(2026, 10, 9, 23, 50, 0), start='00:10', end='05:00')
        assert c._night_vent_clock() == (False, 1200.0)

    def test_a_malformed_clock_time_gives_no_window(self):
        c = _clock_coord(datetime(2026, 10, 9, 17, 30), start='soon')
        assert c._night_vent_clock() == (False, None)


class TestNoSunInfoMeansNoTaper:
    """위치를 모르면 파킹이 언제 시작할지도 모른다 — 그 앞을 셀 수 없다."""

    def test_no_coordinates(self, monkeypatch):
        now = _SUNSET - timedelta(minutes=20)
        c = _sun_coord(monkeypatch, now, located=False)
        assert c._night_vent_clock() == (False, None)
        assert c._night_vent_decide({}, {}) == (False, None)

    def test_no_sunset_today(self, monkeypatch):
        """백야 — 일몰이 없다."""
        c = _sun_coord(monkeypatch, _SUNSET, sunset=None)
        assert c._night_vent_clock() == (False, None)

    def test_the_lookup_blowing_up(self, monkeypatch):
        c = _sun_coord(monkeypatch, _SUNSET)

        def boom(**kw):
            raise RuntimeError('astral')
        monkeypatch.setattr('aot.utils.solar.sun_times', boom)
        assert c._night_vent_clock() == (False, None)

    def test_the_option_off_means_no_window(self, monkeypatch):
        now = _SUNSET - timedelta(minutes=20)
        c = _sun_coord(monkeypatch, now)
        c.night_vent_park = False
        assert c._night_vent_decide({}, {}) == (False, None)


class TestTheReasonsThatBreakParkingBreakTheWindow:
    """파킹을 푸는 사유가 서 있으면 미리 묶어 두지 않는다."""

    NOW = _SUNSET - timedelta(minutes=20)      # 파킹(오프셋 10) 10분 전

    def test_the_baseline_has_a_window(self, monkeypatch):
        c = _sun_coord(monkeypatch, self.NOW)
        assert c._night_vent_decide({'T': 24, 'RH': 70}, {'T': 18, 'RH': 50}) == (
            False, 600.0)

    @pytest.mark.parametrize('flag', ['_force_cool', '_force_dehumid'])
    def test_hard_limits(self, monkeypatch, flag):
        c = _sun_coord(monkeypatch, self.NOW)
        assert c._night_vent_decide({'T': 24, 'RH': 70, flag: True}, {}) == (False, None)

    def test_condensation_escape(self, monkeypatch):
        c = _sun_coord(monkeypatch, self.NOW)
        # 실내 15 °C·95 % 인데 실외 12 °C·60 % — 열면 결로가 덜어진다(야간 파킹 탈출 조건)
        assert c._night_vent_decide({'T': 15, 'RH': 95}, {'T': 12, 'RH': 60}) == (
            False, None)

    def test_the_escape_is_not_a_window_when_it_does_not_apply(self, monkeypatch):
        c = _sun_coord(monkeypatch, self.NOW)
        # 차고 습한 외기는 결로를 덜지 못한다 — 탈출 아님, 구간은 그대로 선다
        assert c._night_vent_decide({'T': 15, 'RH': 95}, {'T': 5, 'RH': 90}) == (
            False, 600.0)

    def test_parked_boolean_view_is_unchanged(self, monkeypatch):
        """`_night_vent_parked` 는 종전대로 bool — 구간은 파킹이 아니다."""
        c = _sun_coord(monkeypatch, self.NOW)
        assert c._night_vent_parked({'T': 24, 'RH': 70}, {'T': 18, 'RH': 50}) is False
        c = _sun_coord(monkeypatch, _SUNSET)
        assert c._night_vent_parked({'T': 24, 'RH': 70}, {'T': 18, 'RH': 50}) is True


# ─────────────────────────────────────────────────────────────────────────────
# 2. 적용 — decide_parking / coordinate
# ─────────────────────────────────────────────────────────────────────────────

def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, deviation, context, extra_target=None):
        self.target = {'vpd': TargetVar(value=1.0, tolerance=0.1,
                                        priority=1.2, unit='kPa')}
        self.target.update(extra_target or {})
        self.deviation_native = deviation
        self.context = context


def _p(aid, kind='opening', magnitude=0.4, temp=None, scale=1.0, safe_default=0.0):
    model = {'vpd': _effect('↑', magnitude)}
    if temp is not None:
        model['temperature'] = _effect('↓', temp)
    p = ActuatorProfile(
        actuator_id=aid, kind=kind, effect_model=model,
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=safe_default)
    p.cmd_scale = scale
    return p


def _ctx(taper_s=600.0, **kw):
    """실외가 더 건조(0.897 kPa) → 창을 열면 VPD 가 오른다. 실내 VPD 는 낮다(-0.33)."""
    T = 30.0
    svp = 0.6108 * math.exp(17.27 * T / (T + 237.3))
    ctx = {'cycle_sec': 600.0, 'T_ext': T,
           'RH_ext': (1.0 - 0.897 / svp) * 100.0,
           'vent_futility_gate': False, 'night_vent_taper_s': taper_s,
           'internal': {}, 'external': {}}
    ctx.update(kw)
    return ctx


def _run(profiles, ctx, prev=40.0, cycles=1, dev=-0.33, integral=None):
    st = CoordinatorState()
    st.prev_commands = {p.actuator_id: prev for p in profiles}
    st.integral = {p.actuator_id: (prev if integral is None else integral)
                   for p in profiles}
    cmds = None
    for _ in range(cycles):
        cmds, st = coordinate(_Situation({'vpd': dev}, ctx), profiles, st,
                              unique_id='')
    return cmds, st


class TestTheCap:

    def test_without_a_window_the_vent_opens_as_before(self):
        """창 밖에서는 아무것도 달라지지 않는다 — 종전 동작."""
        cmds, _ = _run([_p('v')], _ctx(taper_s=None))
        assert cmds['v'].reason == LC.REASON_PRIMARY
        assert cmds['v'].control_value() > 40.0

    def test_inside_the_window_it_stays_where_it_is(self):
        cmds, _ = _run([_p('v')], _ctx())
        assert cmds['v'].reason == LC.REASON_PREPARK_HOLD
        assert cmds['v'].control_value() == pytest.approx(40.0)

    def test_it_never_grows_over_the_whole_window(self):
        """한 번이 아니라 창 내내 — 4~5 사이클을 지나도 같은 자리."""
        cmds, st = _run([_p('v')], _ctx(), cycles=8)
        assert cmds['v'].control_value() == pytest.approx(40.0)
        assert st.integral['v'] <= 40.0 + 1e-9

    def test_the_integral_does_not_wind_up(self):
        """적분이 개도보다 낮게 시작해도 창 안에서 자라지 않는다(조건부 적분)."""
        _, st = _run([_p('v')], _ctx(), prev=40.0, integral=25.0, cycles=8)
        assert st.integral['v'] <= 25.0 + 1e-9

    def test_a_high_integral_is_pulled_down_to_the_opening(self):
        """개도 위에 쌓여 있던 적분이 창 끝에서 한꺼번에 밀지 않게 개도로 내린다."""
        _, st = _run([_p('v')], _ctx(), prev=40.0, integral=90.0)
        assert st.integral['v'] <= 40.0 + 1e-9

    def test_no_jump_when_the_window_ends(self):
        """묶는 동안 적분이 감기지 않았으면 창이 끝나도 계단이 없다 — 대조: 묶지 않고 감긴 적분."""
        prof = [_p('v')]
        _, held = _run(prof, _ctx(), cycles=6)

        def after(st):
            c, _ = coordinate(_Situation({'vpd': -0.33}, _ctx(taper_s=None)),
                              prof, st, unique_id='')
            return c['v'].control_value()
        # 같은 요구를 한 사이클 더 받았을 때 묶어 둔 쪽의 출발점이 훨씬 낮다
        _, unheld = _run(prof, _ctx(taper_s=None), cycles=6)
        assert after(held) < after(unheld)

    def test_closing_is_still_allowed(self):
        """닫는 쪽은 막지 않는다 — PI 가 줄이라 하면 줄인다(근거도 PRIMARY 그대로)."""
        cmds, _ = _run([_p('v')], _ctx(), dev=+0.33)
        assert cmds['v'].control_value() < 40.0
        assert cmds['v'].reason != LC.REASON_PREPARK_HOLD

    def test_an_exhaust_fan_is_held_too(self):
        cmds, _ = _run([_p('f', kind='exhaust_fan')], _ctx())
        assert cmds['f'].reason == LC.REASON_PREPARK_HOLD
        assert cmds['f'].control_value() == pytest.approx(40.0)

    def test_screens_and_hvac_are_not_vents(self):
        prof = [_p('h', kind='heater'), _p('c', kind='curtain', safe_default=100.0)]
        cmds, _ = _run(prof, _ctx())
        assert cmds['h'].reason != LC.REASON_PREPARK_HOLD
        assert cmds['c'].reason != LC.REASON_PREPARK_HOLD

    def test_a_delivery_ratio_below_one_does_not_decay_the_hold(self):
        """풍향 가중치 0.5 — 요구를 나눠 내야 실제 개도가 제자리에 선다."""
        cmds, _ = _run([_p('v', scale=0.5)], _ctx(), prev=20.0)
        assert cmds['v'].control_value() == pytest.approx(20.0)
        assert cmds['v'].reason == LC.REASON_PREPARK_HOLD

    def test_an_already_parked_vent_reads_as_parked_not_held(self):
        """파킹이 서면(구간 값은 비어 있다) 근거는 19 — 구간과 겹치지 않는다."""
        cmds, _ = _run([_p('v')], _ctx(taper_s=None, night_vent_park=True))
        assert cmds['v'].reason == LC.REASON_NIGHT_PARKED

    def test_the_hold_does_not_hide_a_parked_vent_even_if_both_are_set(self):
        cmds, _ = _run([_p('v')], _ctx(night_vent_park=True))
        assert cmds['v'].reason == LC.REASON_NIGHT_PARKED


class TestSafetyAndLimitReasonsWin:
    """안전·한계 사유는 창을 푼다 — 열 수 있다."""

    def test_hard_cooling_latch(self):
        ctx = _ctx(internal={'_force_cool': True})
        cmds, _ = _run([_p('v')], ctx)
        assert cmds['v'].reason != LC.REASON_PREPARK_HOLD
        assert cmds['v'].control_value() > 40.0

    def test_hard_dehumidify_latch(self):
        ctx = _ctx(internal={'_force_dehumid': True})
        cmds, _ = _run([_p('v')], ctx)
        assert cmds['v'].reason != LC.REASON_PREPARK_HOLD

    def test_the_hard_temperature_term_opens_the_vent(self):
        """온도 상한의 하드 항(투영 온도가 temp_max) — 래치가 서기 전에도 연다."""
        ctx = _ctx(T_int=35.5, T_trend=0.0, T_ceiling=32.0, temp_max=35.0)
        cmds, _ = _run([_p('v', temp=3.0)], ctx, prev=10.0, integral=10.0)
        assert cmds['v'].reason != LC.REASON_PREPARK_HOLD
        assert cmds['v'].control_value() > 10.0

    def test_a_soft_temperature_excess_does_not_break_the_window(self):
        """유도 상한을 막 넘은 정도(하드 아님)는 파킹도 풀지 않는다 — 같은 규칙."""
        ctx = _ctx(T_int=31.5, T_trend=0.0, T_ceiling=32.0, temp_max=35.0)
        cmds, _ = _run([_p('v', temp=3.0)], ctx, prev=10.0, integral=10.0)
        assert cmds['v'].reason == LC.REASON_PREPARK_HOLD
        assert cmds['v'].control_value() == pytest.approx(10.0)

    def test_extreme_heat_protection_opens_the_vent(self):
        hp = HeatProtectDecision(
            tier=1, threshold=30.0, vent_open_ok=True,
            vent_open_ids=frozenset({'v'}), vent_closed_ids=frozenset(),
            fog_allowed=True, fog_blocked_ids=frozenset(),
            floor_ids=frozenset(), floor_pct=0.0)
        ctx = _ctx(heat_protect=hp, T_int=31.0, T_trend=0.0, T_ceiling=32.0,
                   temp_max=35.0)
        pk = decide_parking([_p('v', temp=3.0)], _Situation({'vpd': -0.33}, ctx),
                            ctx, 600.0, {'v': 40.0}, log=False)
        assert pk.taper_ids == set()
        cmds, _ = _run([_p('v', temp=3.0)], ctx)
        assert cmds['v'].reason != LC.REASON_PREPARK_HOLD

    def test_extreme_heat_protection_closing_is_not_overridden(self):
        """바깥이 더 더워 닫는 중인 창은 닫히는 근거(28)가 이긴다."""
        hp = HeatProtectDecision(
            tier=1, threshold=30.0, vent_open_ok=False,
            vent_open_ids=frozenset(), vent_closed_ids=frozenset({'v'}),
            fog_allowed=True, fog_blocked_ids=frozenset(),
            floor_ids=frozenset(), floor_pct=0.0)
        ctx = _ctx(heat_protect=hp, T_int=31.0, T_trend=0.0, T_ceiling=32.0,
                   temp_max=35.0)
        cmds, _ = _run([_p('v', temp=3.0)], ctx)
        assert cmds['v'].reason == LC.REASON_HEAT_VENT_HOT_OUTSIDE

    def test_protection_that_is_enabled_but_idle_does_not_break_the_window(self):
        hp = HeatProtectDecision(
            tier=0, threshold=30.0, vent_open_ok=None,
            vent_open_ids=frozenset(), vent_closed_ids=frozenset(),
            fog_allowed=True, fog_blocked_ids=frozenset(),
            floor_ids=frozenset(), floor_pct=0.0)
        ctx = _ctx(heat_protect=hp)
        cmds, _ = _run([_p('v')], ctx)
        assert cmds['v'].reason == LC.REASON_PREPARK_HOLD


class TestOtherHoldsKeepTheirOwnReason:
    """이미 다른 근거로 서 있는 장치를 48 로 덮어쓰지 않는다."""

    def test_unknown_outdoor_stays_reason_16(self):
        ctx = _ctx(external={'_ext_synthetic': True})
        cmds, _ = _run([_p('v')], ctx)
        assert cmds['v'].reason == LC.REASON_NO_OUTDOOR_DATA

    def test_rain_or_wind_ceiling_stays_reason_16(self):
        ctx = _ctx(vent_open_ceiling=True)
        cmds, _ = _run([_p('v')], ctx)
        assert cmds['v'].reason == LC.REASON_NO_OUTDOOR_DATA

    def test_decide_parking_lists_only_the_free_vents(self):
        profs = [_p('v1'), _p('v2'), _p('h', kind='heater')]
        ctx = _ctx()
        pk = decide_parking(profs, _Situation({'vpd': -0.33}, ctx), ctx, 600.0,
                            {'v1': 40.0, 'v2': 40.0}, log=False)
        assert pk.taper_ids == {'v1', 'v2'}
        ctx = _ctx(taper_s=None)
        pk = decide_parking(profs, _Situation({'vpd': -0.33}, ctx), ctx, 600.0,
                            {'v1': 40.0, 'v2': 40.0}, log=False)
        assert pk.taper_ids == set()


# ─────────────────────────────────────────────────────────────────────────────
# 3. 배선 — 사이클이 구간을 싣고, 근거 코드가 모든 표에 있다
# ─────────────────────────────────────────────────────────────────────────────

class TestWiring:

    def test_the_cycle_carries_the_window_into_the_context(self):
        import inspect
        from aot.functions.custom_functions.env_coordinator_impl import (
            _cycle_mixin as m)
        src = inspect.getsource(m.CycleMixin._run_cycle)
        assert "situation.context['night_vent_taper_s']" in src

    def test_the_reason_code_is_new_and_unique(self):
        assert LC.REASON_PREPARK_HOLD == 48
        codes = [v for k, v in vars(LC).items()
                 if k.startswith('REASON_') and isinstance(v, int)]
        assert len(codes) == len(set(codes)), '근거코드가 겹친다'

    def test_the_health_check_names_it(self):
        from aot.scripts.check_env_coordinator_health import REASON_LABEL
        assert LC.REASON_PREPARK_HOLD in REASON_LABEL

    def test_the_window_constant_has_one_definition(self):
        """상수는 한 곳 — 문서가 45분이라 말하는 값이 이것이다."""
        import inspect
        src = inspect.getsource(_helpers_mixin)
        assert src.count('NIGHT_VENT_TAPER_S =') == 1
