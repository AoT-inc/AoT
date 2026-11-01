# coding=utf-8
"""스크린 판단(`screen_policy`) — 차광막의 광 상태와 그 결론을 PI 가 읽는 자리 (Phase 5b-2).

    PROTECT  DLI 예상 < 목표 · 다 쳤을 때 광량 < light_min   → 걷어 둔다(근거 44)
    FREE     다 쳐도 광포화 이상 · 습윤형 분무 일소 잠금     → 열·VPD 에 쓴다(근거 43)
    TRADE    그 사이 · DLI 목표·광량 미상                   → 창·분무를 다 쓴 뒤에만
"""
import types

import pytest

from aot.functions.utils.env_control import screen_policy as SP
from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
from aot.functions.utils.env_control.log_channels import (
    REASON_PRIMARY, REASON_SHADE_HEAT, REASON_SHADE_LIGHT_KEEP,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _p(aid, kind, **kw):
    return types.SimpleNamespace(actuator_id=aid, kind=kind, capacity_meta=kw.get('cm', {}))


def _cfg(**kw):
    c = dict(shade_heat_assist=True, light_min=None, light_sat=600.0,
             dli_target=None, cycle_sec=600.0)
    c.update(kw)
    return SP.ScreenConfig(**c)


def _internal(**kw):
    d = {'T': 30.0, 'RH': 50.0, '_outdoor_solar': 800.0, '_light_shaded_est': 300.0,
         'light_open_est': 620.0, 'light_est': 620.0}
    d.update(kw)
    return d


class TestClassifyTable:
    @pytest.mark.parametrize('shaded,lmin,target,proj,sunburn,want', [
        (None, None, None, None, False, SP.SHADE_TRADE),       # 광량 미상
        (150.0, 200.0, None, None, False, SP.SHADE_PROTECT),   # 다 치면 light_min 아래
        (300.0, None, 15.0, 12.0, False, SP.SHADE_PROTECT),    # DLI 모자람
        (300.0, None, 15.0, 12.0, True, SP.SHADE_PROTECT),     # DLI 가 일소보다 앞
        (300.0, None, None, None, True, SP.SHADE_FREE),        # 일소 잠금 = 넘치는 빛
        (300.0, None, None, 20.0, False, SP.SHADE_TRADE),      # DLI 목표 미상
        (700.0, None, 15.0, 20.0, False, SP.SHADE_FREE),       # 다 쳐도 광포화 이상
        (300.0, None, 15.0, 20.0, False, SP.SHADE_TRADE),      # 광포화 아래·DLI 충분
    ])
    def test_table(self, shaded, lmin, target, proj, sunburn, want):
        cfg = _cfg(light_min=lmin, dli_target=target)
        got = SP.classify_shade(cfg, {'_light_shaded_est': shaded}, proj, sunburn)
        assert got == want


class TestDliProjection:
    def test_accumulates_and_resets_each_day(self):
        st = SP.ScreenState()
        SP._update_light_memory(st, {'light_est': 500.0}, 1000.0, '2027-07-25', None, 600.0)
        SP._update_light_memory(st, {'light_est': 500.0}, 1600.0, '2027-07-25', None, 600.0)
        assert st.dli_mol == pytest.approx(2 * 500.0 * 2.02 * 600.0 * 1e-6, rel=0.02)
        SP._update_light_memory(st, {'light_est': 0.0}, 2200.0, '2027-07-26', None, 600.0)
        assert st.dli_mol == 0.0

    def test_projection_assumes_closed_for_the_rest(self):
        st = SP.ScreenState(dli_mol=5.0, cloud_ratio=0.5)
        rest = 10e6     # J/m² 맑은 하늘
        got = SP.project_dli(st, rest, cover_tau=0.8, shade_tau=0.5)
        assert got == pytest.approx(5.0 + 10e6 * 0.5 * 0.8 * 0.5 * 2.02e-6, rel=0.02)

    def test_unknown_sky_gives_none(self):
        assert SP.project_dli(SP.ScreenState(), None, 1.0, 0.5) is None

    def test_cloud_ratio_is_smoothed(self):
        st = SP.ScreenState()
        SP._update_light_memory(st, {'_outdoor_solar': 800.0}, 0.0, 'd', 800.0, 600.0)
        SP._update_light_memory(st, {'_outdoor_solar': 200.0}, 600.0, 'd', 800.0, 600.0)
        assert 0.25 < st.cloud_ratio < 1.0


class TestEvaluate:
    def _eval(self, cfg=None, internal=None, prev=None, hp=None, fog_blocked=False,
              profiles=None, ext=None, state=None):
        st = state or SP.ScreenState(sun_on=True)
        profiles = profiles or [_p('s', 'shade'), _p('w', 'opening'), _p('f', 'fogger')]
        return SP.evaluate_screens(
            cfg or _cfg(), st, internal or _internal(), ext or {'T': 25.0}, profiles,
            hp, 0.0, prev_commands=prev or {}, fog_blocked=fog_blocked)

    def test_no_sun_no_judgement(self):
        dec = self._eval(internal=_internal(_outdoor_solar=40.0),
                         state=SP.ScreenState(sun_on=False))
        assert dec.shade_mode is None
        assert not dec.shade_floor_ids and not dec.shade_heat_ok

    def test_trade_keeps_the_screen_open_while_vents_and_fog_are_left(self):
        dec = self._eval(prev={'w': 30.0, 'f': 10.0})
        assert dec.shade_mode == SP.SHADE_TRADE
        assert dec.shade_floor_ids == {'s'} and not dec.shade_heat_ok

    def test_trade_shades_once_vents_and_fog_are_spent(self):
        dec = self._eval(prev={'w': 100.0, 'f': 0.0}, fog_blocked=True)
        assert dec.shade_heat_ok and not dec.shade_floor_ids

    def test_vents_are_spent_when_outside_is_hotter(self):
        dec = self._eval(prev={'w': 0.0, 'f': 90.0}, ext={'T': 34.0})
        assert dec.shade_heat_ok

    def test_protect_keeps_open(self):
        dec = self._eval(cfg=_cfg(light_min=400.0))
        assert dec.shade_mode == SP.SHADE_PROTECT and dec.shade_floor_ids == {'s'}

    def test_option_off_means_no_judgement(self):
        dec = self._eval(cfg=_cfg(shade_heat_assist=False))
        assert dec.shade_mode is None and not dec.shade_floor_ids

    def test_heat_protect_deploying_owns_the_screen(self):
        hp = types.SimpleNamespace(active=True, shade_deploy=True, light_min_yield=False)
        dec = self._eval(cfg=_cfg(light_min=400.0), hp=hp)
        assert dec.hp_owns_shade and not dec.shade_floor_ids

    def test_sunburn_lock_makes_it_free(self):
        fog = types.SimpleNamespace(actuator_id='f', kind='fogger',
                                    capacity_meta={'nozzle': {'wetting': True}})
        profiles = [_p('s', 'shade'), _p('w', 'opening'), fog]
        import aot.functions.utils.env_control.safety_gates as sg
        orig = sg.is_wetting_fogger
        sg.is_wetting_fogger = lambda p: p.kind == 'fogger'
        try:
            dec = self._eval(profiles=profiles,
                             internal=_internal(_nursery_solar_lockout=250.0))
        finally:
            sg.is_wetting_fogger = orig
        assert dec.shade_mode == SP.SHADE_FREE and dec.shade_heat_ok


class TestHeatProtectAsksTheSamePlace:
    def test_light_min_yield_uses_screen_policy(self):
        import inspect
        from aot.functions.utils.env_control import heat_protect as HP
        src = inspect.getsource(HP.evaluate_heat_protect)
        assert 'shaded_below_light_min' in src
        assert "shaded < light_min" not in src

    def test_solar_hysteresis_is_one_value(self):
        from aot.functions.utils.env_control import heat_protect as HP
        assert HP.HP_SHADE_SOLAR_ON == SP.SHADE_SOLAR_ON
        assert HP.HP_SHADE_SOLAR_OFF == SP.SHADE_SOLAR_OFF


class TestAdjustPiCommand:
    def _dec(self, **kw):
        return SP.ScreenDecision(shade_ids=frozenset({'s'}), **kw)

    def test_floor_opens_and_aligns_the_integral(self):
        dec = self._dec(shade_floor_ids=frozenset({'s'}))
        assert SP.adjust_pi_command(dec, _p('s', 'shade'), 20.0, 20.0, REASON_PRIMARY,
                                    'vpd') == (100.0, 100.0, REASON_SHADE_LIGHT_KEEP)

    def test_heat_use_is_labelled(self):
        dec = self._dec(shade_heat_ok=True)
        assert SP.adjust_pi_command(dec, _p('s', 'shade'), 20.0, 18.0, REASON_PRIMARY,
                                    'temperature') == (20.0, 18.0, REASON_SHADE_HEAT)

    def test_other_devices_pass_through(self):
        dec = self._dec(shade_floor_ids=frozenset({'s'}))
        assert SP.adjust_pi_command(dec, _p('w', 'opening'), 20.0, 20.0, REASON_PRIMARY,
                                    'vpd') == (20.0, 20.0, REASON_PRIMARY)

    def test_no_decision_passes_through(self):
        assert SP.adjust_pi_command(None, _p('s', 'shade'), 20.0, 20.0, 1, 'vpd') == (
            20.0, 20.0, 1)


# ─────────────────────────────────────────────────────────────────────────────
# coordinate() 안에서 — 온도 상한 항과 바닥
# ─────────────────────────────────────────────────────────────────────────────

class _Situation:
    def __init__(self, target, deviation, context):
        self.target = target
        self.deviation_native = deviation
        self.context = context


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


def _shade():
    return ActuatorProfile(
        actuator_id='s', kind='shade',
        effect_model={'temperature': _effect('↑', 1.0), 'vpd': _effect('↑', 0.15)},
        cost_fn=lambda env, pct: 5.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=100.0)


def _run(screen, dev_vpd=0.0):
    ctx = {'cycle_sec': 600.0, 'vent_futility_gate': False, 'T_int': 31.0,
           'T_trend': 0.05, 'T_ceiling': 28.0, 'temp_max': 40.0, 'screen': screen}
    target = {'vpd': TargetVar(value=1.2, tolerance=0.1, priority=1.2, unit='kPa')}
    st = CoordinatorState(prev_commands={'s': 100.0}, integral={'s': 100.0})
    cmds, _ = coordinate(_Situation(target, {'vpd': dev_vpd}, ctx), [_shade()], st,
                         unique_id='test')
    return cmds['s']


class TestCoordinateReadsTheDecision:
    def test_without_permission_the_ceiling_does_not_draw_the_shade(self):
        assert _run(None).value == pytest.approx(100.0)

    def test_permitted_shade_answers_the_temperature_ceiling(self):
        cmd = _run(SP.ScreenDecision(shade_ids=frozenset({'s'}), shade_heat_ok=True))
        assert cmd.value < 100.0
        assert cmd.reason == REASON_SHADE_HEAT

    def test_light_keep_wins_over_vpd(self):
        """VPD 가 높아 닫자고 해도 빛을 지킬 때는 걷어 둔다."""
        dec = SP.ScreenDecision(shade_ids=frozenset({'s'}),
                                shade_floor_ids=frozenset({'s'}))
        cmd = _run(dec, dev_vpd=0.6)
        assert cmd.value == pytest.approx(100.0)
        assert cmd.reason == REASON_SHADE_LIGHT_KEEP


# ─────────────────────────────────────────────────────────────────────────────
# 왕복 방지 (5b-3)
# ─────────────────────────────────────────────────────────────────────────────

class TestHold:
    def _setup(self, pos=100.0, sun=True, moves=0, last=None):
        st = SP.ScreenState(sun_on=sun, screen_pos={'s': pos},
                            moves_today={'s': moves},
                            last_move=({} if last is None else {'s': last}))
        dec = SP.ScreenDecision(shade_ids=frozenset({'s'}), hold_enabled=True)
        prof = types.SimpleNamespace(actuator_id='s', kind='shade', capacity_meta={},
                                     cmd_constraints=types.SimpleNamespace(full_stroke_sec=0.0))
        return st, dec, [prof]

    def _apply(self, st, dec, profs, value, reason, now):
        cmds = {'s': {'value': value, 'reason': reason}}
        blocked = SP.apply_screen_hold(dec, st, cmds, profs, {}, now)
        SP.record_screen_positions(st, cmds, profs, now)
        return cmds['s'], blocked

    def test_a_request_must_last_before_the_screen_moves(self):
        st, dec, profs = self._setup()
        cmd, why = self._apply(st, dec, profs, 0.0, REASON_SHADE_HEAT, 10_000.0)
        assert cmd == {'value': 100.0, 'reason': SP.REASON_SCREEN_HOLD}
        assert why == {'s': 'dwell'}
        cmd, why = self._apply(st, dec, profs, 0.0, REASON_SHADE_HEAT, 10_600.0)
        assert cmd['value'] == 0.0 and not why
        assert st.moves_today['s'] == 1

    def test_min_hold_after_a_move(self):
        st, dec, profs = self._setup(pos=0.0, last=10_000.0)
        st.pending['s'] = (100.0, 9_000.0)
        cmd, why = self._apply(st, dec, profs, 100.0, REASON_PRIMARY, 10_600.0)
        assert why == {'s': 'min_hold'} and cmd['value'] == 0.0
        cmd, why = self._apply(st, dec, profs, 100.0, REASON_PRIMARY, 11_000.0)
        assert cmd['value'] == 100.0 and not why

    def test_long_stroke_lengthens_the_hold(self):
        p = types.SimpleNamespace(capacity_meta={'screen_stroke_s': 400.0},
                                  cmd_constraints=types.SimpleNamespace(full_stroke_sec=0.0))
        assert SP.hold_seconds(p) == 1200.0

    @pytest.mark.parametrize('reason', ['light_max', 'light_min', 'temp_max', 'heat_protect',
                                        REASON_SHADE_LIGHT_KEEP])
    def test_limits_and_protection_always_pass(self, reason):
        st, dec, profs = self._setup(pos=100.0, last=10_000.0, moves=8)
        value = 100.0 if reason in ('light_min', REASON_SHADE_LIGHT_KEEP) else 0.0
        st.screen_pos['s'] = 100.0 - value
        cmd, why = self._apply(st, dec, profs, value, reason, 10_010.0)
        assert cmd['value'] == value and not why

    def test_day_cap(self):
        st, dec, profs = self._setup(pos=100.0, moves=SP.SCREEN_MAX_MOVES_PER_DAY)
        st.pending['s'] = (0.0, 0.0)
        cmd, why = self._apply(st, dec, profs, 0.0, REASON_SHADE_HEAT, 10_000.0)
        assert why == {'s': 'day_cap'} and cmd['value'] == 100.0

    def test_opening_after_sunset_is_not_capped(self):
        st, dec, profs = self._setup(pos=0.0, sun=False, moves=SP.SCREEN_MAX_MOVES_PER_DAY)
        cmd, why = self._apply(st, dec, profs, 100.0, 15, 10_000.0)
        assert cmd['value'] == 100.0 and not why

    def test_no_closing_without_sun(self):
        st, dec, profs = self._setup(pos=100.0, sun=False)
        st.pending['s'] = (0.0, 0.0)
        _, why = self._apply(st, dec, profs, 0.0, REASON_PRIMARY, 10_000.0)
        assert why == {'s': 'no_sun'}

    def test_off_or_owned_means_no_hold(self):
        st, dec, profs = self._setup()
        dec.hold_enabled = False
        cmd, why = self._apply(st, dec, profs, 0.0, REASON_PRIMARY, 10_000.0)
        assert cmd['value'] == 0.0 and not why
        hp = types.SimpleNamespace(active=True, shade_deploy=True, light_min_yield=False)
        d2 = SP.evaluate_screens(_cfg(), SP.ScreenState(sun_on=True), _internal(),
                                 {'T': 25.0}, [_p('s', 'shade')], hp, 0.0)
        assert not d2.hold_enabled

    def test_moves_reset_each_day(self):
        st = SP.ScreenState(day_key='d1', moves_today={'s': 5})
        SP._update_light_memory(st, {}, 0.0, 'd2', None, 600.0)
        assert st.moves_today == {}


def test_run_cycle_finishes_screens_before_recording():
    """왕복 방지 → 0/100 → 기록 순서 — 기록값 = 전송값(29cd04b84 회귀)."""
    import inspect
    from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin as cm
    src = inspect.getsource(cm.CycleMixin._run_cycle)
    assert src.index('self._finish_screens(') < src.index('write_final_commands(')
    fin = inspect.getsource(cm.CycleMixin._finish_screens)
    assert (fin.index('apply_screen_hold(') < fin.index('snap_screen_commands(')
            < fin.index('record_screen_positions('))


def test_a_shade_with_nothing_to_do_goes_straight_back_open():
    """무구배 감쇠(0 → 40)가 0/100 결정(60)을 못 넘어 닫힌 채 굳던 것(폐루프 hot_dry)."""
    from aot.functions.utils.env_control.log_channels import REASON_NO_GRADIENT
    dec = SP.ScreenDecision(shade_ids=frozenset({'s'}), daylight=True)
    assert SP.adjust_pi_command(dec, _p('s', 'shade'), 40.0, 40.0, REASON_NO_GRADIENT,
                                None) == (100.0, 100.0, REASON_NO_GRADIENT)
    # 밤에는 제자리 — 닫힌 막이 작물을 하늘 복사냉각에서 가린다(폐루프 hot_humid 이슬)
    night = SP.ScreenDecision(shade_ids=frozenset({'s'}), daylight=False)
    assert SP.adjust_pi_command(night, _p('s', 'shade'), 40.0, 40.0, REASON_NO_GRADIENT,
                                None) == (40.0, 40.0, REASON_NO_GRADIENT)
    # 보온커튼은 제자리 규칙(29cd04b84) 그대로다.
    assert SP.adjust_pi_command(dec, _p('c', 'curtain'), 0.0, 0.0, REASON_NO_GRADIENT,
                                None) == (0.0, 0.0, REASON_NO_GRADIENT)


def test_heat_protect_yields_when_light_must_be_kept():
    """보호(단계 1)는 '빛 지킴'(DLI 모자람)이면 차광을 치지 않는다 — 심각하면 친다."""
    from aot.functions.utils.env_control import heat_protect as HP
    cfg = HP.HeatProtectConfig(threshold=30.0, cycle_sec=600.0)
    internal = {'T': 31.0, 'RH': 50.0, '_outdoor_solar': 700.0,
                '_light_shaded_est': 250.0, '_shade_light_keep': True}
    st = HP.HeatProtectState(latched=True, entered_at=0.0, sun_on=True)
    dec = HP.evaluate_heat_protect(cfg, st, internal, {'T': 28.0},
                                   [_p('s', 'shade')], 100.0)
    assert dec.active and not dec.shade_deploy and dec.light_min_yield
    internal['T'] = 34.0                          # 문턱 + 3 °C 이상 — 심각
    st2 = HP.HeatProtectState(latched=True, entered_at=0.0, sun_on=True)
    dec2 = HP.evaluate_heat_protect(cfg, st2, internal, {'T': 28.0},
                                    [_p('s', 'shade')], 100.0)
    assert dec2.shade_deploy


def test_daylight_comes_from_sun_or_the_clock():
    st = SP.ScreenState(sun_on=False)
    d = SP.evaluate_screens(_cfg(), st, {}, {}, [_p('s', 'shade')], None, 0.0, daytime=True)
    assert d.daylight                                   # 일사를 모르면 시계
    # 일사를 재면 그것만 — 해 지기 직전(시계상 낮, 일사 4 W/m²)에는 걷지 않는다
    d = SP.evaluate_screens(_cfg(), SP.ScreenState(), {'_outdoor_solar': 4.0}, {},
                            [_p('s', 'shade')], None, 0.0, daytime=True)
    assert not d.daylight
    d = SP.evaluate_screens(_cfg(), SP.ScreenState(), {}, {}, [_p('s', 'shade')], None, 0.0,
                            daytime=False)
    assert not d.daylight
