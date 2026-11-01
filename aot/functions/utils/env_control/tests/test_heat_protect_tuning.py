# coding=utf-8
"""극한 고온 보호 · 온도 상한 항의 폐루프 조정 (2026-10-09).

폐루프 시뮬레이터(`aot/scripts/env_closedloop`, 김제 육묘장3)에서 보호(e471bf60b)를
붙인 뒤 창 반전·긴급이 늘었다(normal 1.40 → 1.87 /h, humid_night 긴급 5 → 16).
기전과 고친 것:

1. 보호 중에는 초과 0 에서도 하드 항(오차 0 · 무게 최대)이 남아, 선 아래에서 맞서는 VPD
   항만 남은 P 위주 PI 가 창을 0 으로 떨어뜨렸다 → 선 위(초과 > 0)에서만 하드.
2. 평소 상한(가이드 32 °C)이 보호 문턱(30 °C)보다 높아, 문턱을 넘는 것이 평소 제어의
   운전점이었다 → 래치가 조절기 노릇(진입·해제 반복) → 보호가 켜져 있으면 평소 상한도
   문턱을 넘지 않는다.
3. 상한 항이 꺼지면 무구배 감쇠로 닫혀 다시 데워지는 이완 발진 → 꺼지는 선 아래
   `T_CEILING_HOLD_BAND` 는 유지 구간(창 제자리).
4. 습윤형 분무는 보호의 증발냉각기가 아니다 → 하드 항이 몰지 않는다.
"""
import pytest

from aot.functions.utils.env_control.coordinator import (
    T_CEILING_HOLD_BAND, T_CEILING_HYST, T_CEILING_TOL, CoordinatorState,
    _temperature_ceiling, coordinate,
)
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Situation:
    def __init__(self, target, deviation, context):
        self.target = target
        self.deviation_native = deviation
        self.context = context


def _profile(aid, kind, temp_mag=2.0, vpd_dir='↓', vpd_mag=0.1, wetting=None):
    p = ActuatorProfile(
        actuator_id=aid, kind=kind,
        effect_model={'temperature': _effect('↓', temp_mag),
                      'vpd': _effect(vpd_dir, vpd_mag)},
        cost_fn=lambda env, pct: 5.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2},
        safe_default=0.0,
    )
    if wetting is not None:
        p.capacity_meta = {'nozzle': {'wetting': bool(wetting)}}
    return p


# VPD 모드 — VPD 가 목표보다 낮아(습함) VPD 항은 창을 닫자고 한다.
_TARGET = {'vpd': TargetVar(value=1.0, tolerance=0.1, priority=1.2, unit='kPa')}
_DEV = {'vpd': -0.5}


def _hp(tier=1, thr=30.0, enabled=True, cooling=()):
    return HeatProtectDecision(tier=tier, threshold=thr, enabled=enabled,
                               cooling_fog_ids=frozenset(cooling))


def _ctx(hp=None, **kw):
    ctx = {'cycle_sec': 600.0, 'vent_futility_gate': False,
           'T_int': 31.0, 'T_trend': 0.0, 'T_ceiling': 32.0, 'temp_max': 40.0,
           'T_ext': 22.0, 'internal': {}, 'external': {}}
    if hp is not None:
        ctx['heat_protect'] = hp
    ctx.update(kw)
    return ctx


def _run(profiles, ctx, state=None):
    return coordinate(_Situation(_TARGET, dict(_DEV), ctx), profiles,
                      state or CoordinatorState(), unique_id='')


def _state(prev, ceiling_active=True):
    st = CoordinatorState()
    st.prev_commands = dict(prev)
    st.integral = dict(prev)
    st.t_ceiling_active = ceiling_active
    return st


# ─────────────────────────────────────────────────────────────────────────────
# 1·2. 상한 항 — 보호 중 하드는 선 위에서만, 평소 상한도 문턱 아래
# ─────────────────────────────────────────────────────────────────────────────

class TestCeiling:
    def test_protection_hard_term_drops_below_the_line(self):
        sit = _Situation(_TARGET, dict(_DEV), {})
        above = _temperature_ceiling(sit, _ctx(_hp(), T_int=30.5), 600.0)
        assert above is not None and above[1] is True
        # 선(문턱 − 허용오차) 아래로 한참 — 예전에는 (0, True) 가 남아 창을 0 으로 떨궜다
        below = _temperature_ceiling(sit, _ctx(_hp(), T_int=26.0), 600.0)
        assert below is None

    def test_enabled_protection_caps_the_ordinary_ceiling(self):
        """보호가 켜져 있으면(단계 0 이어도) 평소 상한도 문턱(30)을 넘지 않는다 — 부드럽게."""
        sit = _Situation(_TARGET, dict(_DEV), {})
        r = _temperature_ceiling(sit, _ctx(_hp(tier=0), T_int=29.5), 600.0)
        assert r is not None and r[1] is False
        assert r[0] == pytest.approx(29.5 - (30.0 - T_CEILING_TOL))
        # 꺼져 있으면 문턱은 아무 데도 쓰이지 않는다 — 가이드 상한 32 그대로
        off = _hp(tier=0, enabled=False)
        assert _temperature_ceiling(sit, _ctx(off, T_int=29.5), 600.0) is None
        assert _temperature_ceiling(sit, _ctx(None, T_int=29.5), 600.0) is None

    def test_protection_line_applies_in_direct_temperature_mode(self):
        """온도가 제어목표(온도 우선 기준, 또는 습도를 잃은 VPD 기준의 온·습도 폴백)여도
        보호 중에는 문턱의 선을 건다. 폴백 목표는 가이드 상한(32)으로 클램프된 값이라 그것만
        좇으면 창이 40~50 % 에 머물고 실내가 36 °C 까지 갔다(폐루프 sensor_indoor_oor)."""
        sit = _Situation({'temperature': TargetVar(value=32.0, tolerance=1.0,
                                                   priority=2.0, unit='°C')},
                         {'temperature': 2.5}, {})
        r = _temperature_ceiling(sit, _ctx(_hp(), T_int=34.5), 600.0)
        assert r is not None and r[1] is True
        assert r[0] == pytest.approx(34.5 - (30.0 - T_CEILING_TOL))
        # 보호 밖에서는 종전대로 — 온도가 스스로 끌리므로 이중계상하지 않는다
        assert _temperature_ceiling(sit, _ctx(_hp(tier=0), T_int=34.5), 600.0) is None

    def test_direct_mode_window_opens_wider_under_protection(self):
        w = _profile('w', 'opening', temp_mag=2.0)
        tgt = {'temperature': TargetVar(value=32.0, tolerance=1.0, priority=2.0, unit='°C')}
        dev = {'temperature': 2.5}
        base, _ = coordinate(_Situation(tgt, dict(dev), _ctx(_hp(tier=0), T_int=34.5)),
                             [w], CoordinatorState(), unique_id='')
        w2 = _profile('w', 'opening', temp_mag=2.0)
        hp, _ = coordinate(_Situation(tgt, dict(dev), _ctx(_hp(), T_int=34.5)),
                           [w2], CoordinatorState(), unique_id='')
        assert hp['w'].value > base['w'].value

    def test_hard_limit_stays_hard_at_zero_excess(self):
        """하드 임계(`_force_cool`)는 종전대로 초과 0 에서도 하드다 — 보호만 바뀐다."""
        sit = _Situation(_TARGET, dict(_DEV), {})
        r = _temperature_ceiling(
            sit, _ctx(_hp(tier=2), T_int=26.0, internal={'_force_cool': True}), 600.0)
        assert r == (0.0, True)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 유지 구간 — 상한으로 연 창은 선 아래 1.5 °C 까지 제자리
# ─────────────────────────────────────────────────────────────────────────────

class TestHoldBand:
    _CEIL = 30.0
    _OFF = _CEIL - T_CEILING_TOL - T_CEILING_HYST          # 켜진 항이 꺼지는 선 28.5

    def test_window_holds_inside_the_band(self):
        w = _profile('w', 'opening')
        ctx = _ctx(T_ceiling=self._CEIL, T_int=self._OFF - 0.5)
        cmds, st = _run([w], ctx, _state({'w': 20.0}))
        assert cmds['w'].value == pytest.approx(20.0)
        assert st.t_ceiling_active                     # 다음 사이클도 유지 구간 판정
        assert st.integral['w'] == pytest.approx(20.0)  # 다시 넘으면 여기서 더 연다

    def test_hold_keeps_the_actual_opening_under_a_transfer_ratio(self):
        """풍향 가중치(전달 비율 0.7)가 걸려도 유지는 **실제 개도** 그대로 — 직전 개도를 다시
        내면 비율이 곱해져 사이클마다 닫힌다(시뮬레이터: 20 → 13.6 → 10 → 7 %)."""
        w = _profile('w', 'opening')
        w.cmd_scale = 0.7
        ctx = _ctx(T_ceiling=self._CEIL, T_int=self._OFF - 0.5)
        cmds, _ = _run([w], ctx, _state({'w': 20.0}))
        assert cmds['w'].aperture == pytest.approx(20.0)

    def test_window_relaxes_below_the_band(self):
        w = _profile('w', 'opening')
        ctx = _ctx(T_ceiling=self._CEIL, T_int=self._OFF - T_CEILING_HOLD_BAND - 0.3)
        cmds, _ = _run([w], ctx, _state({'w': 20.0}))
        assert cmds['w'].value < 20.0

    def test_band_needs_the_term_to_have_been_on(self):
        """꺼져 있던 항은 유지 구간을 만들지 않는다 — 종전 경로(감쇠)."""
        w = _profile('w', 'opening')
        ctx = _ctx(T_ceiling=self._CEIL, T_int=self._OFF - 0.5)
        cmds, _ = _run([w], ctx, _state({'w': 20.0}, ceiling_active=False))
        assert cmds['w'].value < 20.0

    def test_band_can_still_open_further(self):
        """유지 구간은 닫는 쪽만 막는다 — VPD 가 더 열자고 하면 연다."""
        w = _profile('w', 'opening', vpd_dir='↑', vpd_mag=1.0)
        ctx = _ctx(T_ceiling=self._CEIL, T_int=self._OFF - 0.5)
        sit = _Situation(_TARGET, {'vpd': -0.5}, ctx)
        cmds, _ = coordinate(sit, [w], _state({'w': 20.0}), unique_id='')
        assert cmds['w'].value >= 20.0

    def test_parking_wins_over_the_band(self):
        w = _profile('w', 'opening')
        ctx = _ctx(T_ceiling=self._CEIL, T_int=self._OFF - 0.5, night_vent_park=True)
        cmds, _ = _run([w], ctx, _state({'w': 20.0}))
        assert cmds['w'].value < 20.0


# ─────────────────────────────────────────────────────────────────────────────
# 4. 습윤형 분무는 보호의 하드 항이 몰지 않는다
# ─────────────────────────────────────────────────────────────────────────────

class TestWettingMist:
    def test_hard_term_drives_only_cooling_foggers(self):
        mist = _profile('mist', 'fogger', vpd_dir='↓', vpd_mag=0.1, wetting=True)
        fog = _profile('fog', 'fogger', vpd_dir='↓', vpd_mag=0.1, wetting=False)
        ctx = _ctx(_hp(cooling={'fog'}), T_int=31.5)
        cmds, _ = _run([mist, fog], ctx)
        assert cmds['fog'].value > 0.0
        # 습윤형은 평소 제어 그대로 — VPD 가 목표보다 낮으니(습함) 뿌리지 않는다
        assert cmds['mist'].value == 0.0

    def test_hard_limit_still_drives_every_fogger(self):
        mist = _profile('mist', 'fogger', wetting=True)
        ctx = _ctx(_hp(tier=2), T_int=31.5, internal={'_force_cool': True})
        cmds, _ = _run([mist], ctx)
        assert cmds['mist'].value > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 5. VPD 를 잃은 폴백은 기록된다
# ─────────────────────────────────────────────────────────────────────────────

def test_vpd_fallback_is_marked_in_the_context():
    from aot.functions.utils.env_control.situation import _decompose_vpd
    tgt = {'vpd': TargetVar(value=1.0, tolerance=0.1, priority=1.2, unit='kPa'),
           'temperature': TargetVar(value=32.0, tolerance=1.0, priority=0.5, unit='°C')}
    ctx = {'VPD_int': None}
    t = _decompose_vpd(tgt, ctx)
    assert ctx['vpd_fallback'] is True and 'temperature' in t and 'vpd' not in t
    ctx = {'VPD_int': 1.2}
    t = _decompose_vpd(tgt, ctx)
    assert ctx['vpd_fallback'] is False and 'vpd' in t and 'temperature' not in t


def test_missing_measurement_log_names_the_vpd_fallback():
    import logging
    import types
    from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
    logs = []
    host = types.SimpleNamespace(
        _status_log=lambda lvl, msg, *a: logs.append(msg % a))
    sit = types.SimpleNamespace(context={'unmeasured': ['humidity'], 'vpd_fallback': True})
    CycleMixin._warn_missing_measurements(host, sit)
    assert 'humidity, vpd' in logs[-1] and '온도·습도 기준' in logs[-1]
    CycleMixin._warn_missing_measurements(host, sit)        # 바뀔 때만
    assert len(logs) == 1
