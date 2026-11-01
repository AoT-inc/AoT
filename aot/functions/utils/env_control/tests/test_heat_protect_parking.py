# coding=utf-8
"""극한 고온 보호의 결론이 코디네이터(PI)·L2 에 바르게 들어가는가 — 설계 §5.

판정은 `heat_protect` 가 하고(`test_heat_protect.py`), 여기서는 그 결론을 읽는 자리를 본다:

  · 열어도 되는 창은 야간 파킹·냉난방 연동·환기 무익에서 빠진다. 환기 우선은 꺼진다.
  · 바깥이 더 더우면 닫는 쪽(근거 28), 분무를 못 쓰면 분무 파킹(근거 29), 하한은
    명령·적분 양쪽에.
  · 실외를 모르면(지어낸 실외) 여전히 제자리(근거 16)가 이긴다.
  · 온도 상한이 하드가 되어 냉각과 맞서는 VPD 항을 뺀다.
  · 온·습도 직접 모드에서는 L2 가 온도 우선순위를 올리고, 모드 목록 맨 앞에 보호 모드가 선다.
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, _temperature_ceiling, coordinate, decide_parking,
)
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.log_channels import (
    REASON_HEAT_FOG_BLOCKED, REASON_HEAT_VENT_HOT_OUTSIDE, REASON_NIGHT_PARKED,
    REASON_NO_OUTDOOR_DATA, REASON_OPPOSING_PARKED,
)
from aot.functions.utils.env_control.situation import assess
from aot.functions.utils.env_control.types import (
    MODE_EMERGENCY, MODE_HEAT_PROTECT, ActuatorProfile, CmdConstraints,
    EffectResult, TargetVar,
)

from .conftest import make_ctx, make_target


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, target, deviation, context):
        self.target = target
        self.deviation_native = deviation
        self.context = context


def _profile(aid, kind, temp_dir='↓', temp_mag=2.0, vpd_dir='↓', vpd_mag=0.1,
             cost=5.0, sd=0.0):
    return ActuatorProfile(
        actuator_id=aid, kind=kind,
        effect_model={'temperature': _effect(temp_dir, temp_mag),
                      'vpd': _effect(vpd_dir, vpd_mag)},
        cost_fn=lambda env, pct, _c=cost: _c,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2},
        safe_default=sd,
    )


# VPD 모드 — 온도는 deviation 에 없다. VPD 가 목표보다 **낮아**(습함) VPD 는 창을
# 닫자고 한다(창의 VPD 효과 ↓). 냉각과 맞서는 항이다.
_TARGET = {'vpd': TargetVar(value=1.0, tolerance=0.1, priority=1.2, unit='kPa')}
_DEV = {'vpd': -0.5}


def _hp(tier=1, open_ids=(), closed_ids=(), fog_blocked=(), floor_ids=(),
        floor_pct=0.0, thr=30.0):
    return HeatProtectDecision(
        tier=tier, threshold=thr,
        vent_open_ok=(True if open_ids else (False if closed_ids else None)),
        vent_open_ids=frozenset(open_ids), vent_closed_ids=frozenset(closed_ids),
        fog_allowed=not fog_blocked, fog_blocked_ids=frozenset(fog_blocked),
        floor_ids=frozenset(floor_ids), floor_pct=floor_pct)


def _ctx(hp=None, **kw):
    ctx = {'cycle_sec': 60.0, 'vent_futility_gate': False,
           'T_int': 31.0, 'T_trend': 0.0, 'T_ceiling': 32.0, 'temp_max': 35.0,
           'T_ext': 26.0, 'internal': {}, 'external': {}}
    if hp is not None:
        ctx['heat_protect'] = hp
    ctx.update(kw)
    return ctx


def _park(profiles, ctx, prev=None, dev=None):
    return decide_parking(profiles, _Situation(_TARGET, dict(dev or _DEV), ctx),
                          ctx, 60.0, prev or {}, log=False)


def _run(profiles, ctx, state=None, dev=None):
    return coordinate(_Situation(_TARGET, dict(dev or _DEV), ctx), profiles,
                      state or CoordinatorState(), unique_id='')


# ─────────────────────────────────────────────────────────────────────────────
# 파킹 판정
# ─────────────────────────────────────────────────────────────────────────────

class TestParking:
    def test_open_ok_vents_escape_night_parking(self):
        w = _profile('w', 'opening')
        base = _park([w], _ctx(night_vent_park=True))
        assert 'w' in base.park_ids and 'w' in base.night_parked
        pk = _park([w], _ctx(_hp(open_ids={'w'}), night_vent_park=True))
        assert 'w' not in pk.park_ids and 'w' not in pk.night_parked
        assert pk.heat_open_ids == {'w'}

    def test_open_ok_vents_escape_the_hvac_interlock(self):
        w = _profile('w', 'opening')
        pk = _park([w], _ctx(_hp(open_ids={'w'}), hvac_interlock=True,
                             hvac_running=True))
        assert 'w' not in pk.park_ids and not pk.interlock_ids

    def test_open_ok_vents_escape_the_futility_gate(self):
        w = _profile('w', 'opening')
        w.live_effect = {'vpd': EffectResult('↓', 0.1)}
        ctx = _ctx(_hp(open_ids={'w'}), vent_futility_gate=True,
                   T_ext=26.0, RH_ext=95.0)
        pk = _park([w], ctx)
        assert 'w' not in pk.park_ids and not pk.futile_ids

    def test_vent_first_is_off_during_protection(self):
        w = _profile('w', 'opening', vpd_dir='↑')
        c = _profile('c', 'cooler', cost=9.0)
        # 실외 VPD 가 목표 너머 — 보호가 없으면 냉방을 쉬게 할 조건이다
        ctx = _ctx(vent_first=True, T_ext=20.0, RH_ext=30.0)
        base = _park([w, c], ctx)
        assert 'c' in base.vent_first_ids
        pk = _park([w, c], dict(ctx, heat_protect=_hp(open_ids={'w'})))
        assert not pk.vent_first_ids and 'c' not in pk.park_ids

    def test_heater_is_parked_as_opposing(self):
        h = _profile('h', 'heater', temp_dir='↑')
        pk = _park([h], _ctx(_hp()))
        assert 'h' in pk.park_ids and 'h' in pk.opposing_ids

    def test_hot_outside_and_fog_blocked_are_parked(self):
        w = _profile('w', 'opening')
        f = _profile('f', 'fogger')
        pk = _park([w, f], _ctx(_hp(closed_ids={'w'}, fog_blocked={'f'})))
        assert {'w', 'f'} <= pk.park_ids
        assert pk.heat_closed_ids == {'w'} and pk.heat_fog_blocked_ids == {'f'}

    def test_unknown_outdoor_hold_wins(self):
        w = _profile('w', 'opening')
        ctx = _ctx(_hp(closed_ids={'w'}), external={'_ext_synthetic': True})
        pk = _park([w], ctx)
        assert 'w' in pk.hold_ids
        assert 'w' not in pk.park_ids and not pk.heat_closed_ids

    def test_inactive_decision_changes_nothing(self):
        w = _profile('w', 'opening')
        a = _park([w], _ctx(night_vent_park=True))
        b = _park([w], _ctx(HeatProtectDecision(), night_vent_park=True))
        assert a.park_ids == b.park_ids and not b.heat_open_ids


# ─────────────────────────────────────────────────────────────────────────────
# PI 안 — 근거·하한·온도 상한
# ─────────────────────────────────────────────────────────────────────────────

class TestCoordinate:
    def test_hot_outside_reason_is_28(self):
        cmds, _ = _run([_profile('w', 'opening')],
                       _ctx(_hp(closed_ids={'w'})))
        assert cmds['w'].reason == REASON_HEAT_VENT_HOT_OUTSIDE

    def test_hot_outside_beats_night_parking_in_the_reason(self):
        cmds, _ = _run([_profile('w', 'opening')],
                       _ctx(_hp(closed_ids={'w'}), night_vent_park=True))
        assert cmds['w'].reason == REASON_HEAT_VENT_HOT_OUTSIDE

    def test_fog_blocked_reason_is_29(self):
        cmds, _ = _run([_profile('f', 'fogger')], _ctx(_hp(fog_blocked={'f'})))
        assert cmds['f'].reason == REASON_HEAT_FOG_BLOCKED

    def test_unknown_outdoor_keeps_position(self):
        st = CoordinatorState(prev_commands={'w': 40.0})
        cmds, _ = _run([_profile('w', 'opening')],
                       _ctx(_hp(closed_ids={'w'}), external={'_ext_synthetic': True}),
                       state=st)
        assert cmds['w'].reason == REASON_NO_OUTDOOR_DATA
        assert cmds['w'].value == pytest.approx(40.0)

    def test_floor_holds_command_and_integral(self):
        st = CoordinatorState(prev_commands={'w': 0.0}, integral={'w': 0.0})
        cmds, new = _run([_profile('w', 'opening')],
                         _ctx(_hp(closed_ids={'w'}, floor_ids={'w'}, floor_pct=15.0)),
                         state=st)
        assert cmds['w'].value == pytest.approx(15.0)
        assert new.integral['w'] >= 15.0

    def test_heater_rests_during_protection(self):
        st = CoordinatorState(prev_commands={'h': 50.0}, integral={'h': 50.0})
        cmds, _ = _run([_profile('h', 'heater', temp_dir='↑', vpd_dir='↑')],
                       _ctx(_hp()), state=st)
        assert cmds['h'].reason == REASON_OPPOSING_PARKED
        assert cmds['h'].value < 50.0

    def test_ceiling_is_hard_and_capped_at_the_threshold(self):
        sit = _Situation(_TARGET, dict(_DEV), {})
        r = _temperature_ceiling(sit, _ctx(_hp(thr=30.0), T_ceiling=32.0), 60.0)
        assert r is not None and r[1] is True
        assert r[0] == pytest.approx(31.0 - (30.0 - 1.0))
        # 보호가 없으면 같은 실내(31 °C, 유도 상한 32)에서는 상한 항이 서지 않는다
        assert _temperature_ceiling(sit, _ctx(T_ceiling=32.0), 60.0) is None

    def test_opposing_vpd_term_is_dropped_so_the_window_opens(self):
        """VPD 는 닫자고 하고 실내는 31 °C · 실외 26 °C — 보호 중에는 창이 연다."""
        p = _profile('w', 'opening', vpd_mag=1.0)
        base, _ = _run([p], _ctx(T_ceiling=40.0, temp_max=40.0))
        assert base['w'].value == 0.0
        cmds, _ = _run([_profile('w', 'opening', vpd_mag=1.0)],
                       _ctx(_hp(open_ids={'w'}), T_ceiling=40.0, temp_max=40.0))
        assert cmds['w'].value > 0.0
        assert cmds['w'].var_source == 'temperature'

    def test_cooler_follows_the_hard_term_in_tier1(self):
        c = _profile('c', 'cooler')
        assert _run([c], _ctx(T_ceiling=40.0, temp_max=40.0))[0]['c'].value == 0.0
        cmds, _ = _run([_profile('c', 'cooler')],
                       _ctx(_hp(), T_ceiling=40.0, temp_max=40.0))
        assert cmds['c'].value > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# L2 — 모드·온도 우선순위
# ─────────────────────────────────────────────────────────────────────────────

class TestAssess:
    def _report(self, target, tier):
        ctx = make_ctx(T_int=31.0, T_ext=26.0, RH_int=60.0)
        report, _ = assess(target, ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'],
                           heat_protect_tier=tier)
        return report

    def test_mode_comes_first(self):
        assert self._report(make_target(vpd=1.2), 1).modes[0] == MODE_HEAT_PROTECT
        assert self._report(make_target(vpd=1.2), 2).modes[0] == MODE_EMERGENCY
        assert self._report(make_target(vpd=1.2), 0).modes[0] not in (
            MODE_HEAT_PROTECT, MODE_EMERGENCY)

    def test_direct_mode_raises_temperature_priority(self):
        # VPD 측정이 없으면(0) 온·습도 직접 모드로 돈다
        target = make_target(vpd=1.2, T=25.0, RH=70.0)
        ctx = make_ctx(T_int=31.0, T_ext=26.0, RH_int=60.0, VPD_int=0.0)
        internal = dict(ctx['internal'], VPD=0.0)
        rep, _ = assess(target, internal, ctx['external'], cycle_sec=60.0,
                        now_ts=ctx['now_ts'], heat_protect_tier=1)
        assert 'temperature' in rep.target
        assert rep.target['temperature'].priority >= 2.0
        assert target['temperature'].priority == 0.8      # 설정값은 그대로
        rep0, _ = assess(target, internal, ctx['external'], cycle_sec=60.0,
                         now_ts=ctx['now_ts'])
        assert rep0.target['temperature'].priority == 0.8
