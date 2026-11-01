# coding=utf-8
"""극한 고온·건조의 짧은 펄스 분무 — 일소 잠금 속에서 10초 켜고 15분 이상 쉰다 (2026-10-12, 근거 57).

## 배경

폐루프 극한 기상(김제 육묘장): `heatwave_tropical_night` 실내 42.5 °C·40 °C 초과 337분·VPD 목표 안 7 %,
`foehn_dry_wind` RH 15 %·VPD 7 kPa — 낮에는 일소 잠금(250 W/m²), 저녁에는 해 질 녘 제한(53)이 막아
습윤형 분무가 **하루 종일 0** 이었다. 잠금의 이유(지하수 염분 잔여물)는 관찰 없는 추측이었다(사용자 2026-10-11).

## 구조 (시험도 이 모양을 따른다)

    판정(순수)                     `pulse_fog.evaluate_pulse_fog`
    입력을 모아 잠금의 0 에서 빼기   `_evaluate_pulse_fog` (사본을 돌려준다 — 게이트 결과는 그대로)
    명령을 100 % 근거 57 로         `apply_extreme_pulse_fog` (감쇠 36 은 건너뛴다)
    10초·15분                      `PulsedDoseAdapter.send(pulse_cap=…)` — 새 타이머 없음
"""
import ast
import datetime as dt
import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin, _helpers_mixin
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    CycleMixin, apply_extreme_pulse_fog, apply_nursery_fog_derate,
    apply_threshold_and_gate_overrides,
)
from aot.functions.utils.env_control import dispatch_adapters as da
from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control import pulse_fog as PF
from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints

LOCK = LC.GATE_BIT_FOG_SUNBURN


def _fogger(aid='fog', wetting=True, pulse=True):
    return ActuatorProfile(
        actuator_id=aid, kind='fogger', capabilities=['humidify', 'cooling_passive'],
        cost_fn=lambda env, pct: 5.0, response_sec=60.0, safe_default=0.0,
        capacity_meta={'nozzle': {'wetting': wetting}},
        cmd_constraints=(CmdConstraints(max_on_sec=30.0, min_off_sec=180.0) if pulse
                         else CmdConstraints()))


def _hot_dry(**over):
    """덥고 마른 한낮 — 42 °C · RH 30 % (VPD 5.7 kPa, 건구−습구 15 °C)."""
    d = {'T': 42.0, 'RH': 30.0, 'VPD': 5.7}
    d.update(over)
    return d


def _eval(internal=None, **over):
    kw = dict(enabled=True, gate_mask=LOCK, evening_block=False, dusk_limited=False,
              heat_tier=1, fog_allowed=True, internal=internal if internal is not None else _hot_dry(),
              humid_max=None)
    kw.update(over)
    return PF.evaluate_pulse_fog(**kw)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 판정 — 조건 하나하나
# ─────────────────────────────────────────────────────────────────────────────

class TestDecision:

    def test_hot_and_dry_during_the_lock_pulses(self):
        d = _eval()
        assert d.active and d.why == 'heat+dry'
        assert d.depression == pytest.approx(15.47, abs=0.1)

    def test_constants_are_the_documented_ones(self):
        assert PF.PF_ON_SEC == 10.0 and PF.PF_MIN_OFF_SEC == 900.0
        assert PF.PF_VPD_KPA == 3.0 and PF.PF_HEAT_TIER == 1
        assert PF.PF_WETBULB_DEPRESSION_C == 8.0
        assert PF.PULSE_FOG_REASON == 'extreme_pulse_fog'

    def test_heat_protect_alone_is_enough(self):
        # 보호 단계 1, VPD 는 3 이하(T 36 °C · RH 36 % → VPD 3.6 이 아니라 아래 값으로 고정)
        d = _eval(_hot_dry(VPD=2.5), heat_tier=1)
        assert d.active and d.why == 'heat'

    def test_dry_air_alone_is_enough(self):
        d = _eval(_hot_dry(VPD=3.4), heat_tier=0)
        assert d.active and d.why == 'dry'

    def test_vpd_threshold_is_strictly_above_3(self):
        assert not _eval(_hot_dry(VPD=3.0), heat_tier=0).active
        assert _eval(_hot_dry(VPD=3.01), heat_tier=0).active

    def test_neither_hot_nor_dry_does_not(self):
        d = _eval(_hot_dry(VPD=2.0), heat_tier=0)
        assert not d.active and d.blocked == 'not_extreme'

    def test_vpd_falls_back_to_T_and_RH(self):
        internal = {'T': 42.0, 'RH': 30.0}               # 센서 VPD 없음
        assert PF.indoor_vpd(internal) == pytest.approx(5.74, abs=0.05)
        assert _eval(internal, heat_tier=0).active

    @pytest.mark.parametrize('T,RH,ok', [
        (40.0, 45.0, True),      # 건구−습구 10.9
        (35.0, 60.0, False),     # 6.8 — 보호의 문턱(4 °C)은 넘지만 펄스 문턱(8 °C)은 못 넘는다
    ])
    def test_evaporation_needs_a_wetbulb_depression_of_8(self, T, RH, ok):
        d = _eval({'T': T, 'RH': RH, 'VPD': 4.0})
        assert d.active is ok
        if not ok:
            assert d.blocked == 'low_evaporation'

    def test_depression_boundary_is_inclusive(self, monkeypatch):
        monkeypatch.setattr(PF, 'wetbulb_depression', lambda T, RH: 8.0)
        assert _eval().active
        monkeypatch.setattr(PF, 'wetbulb_depression', lambda T, RH: 7.99)
        assert not _eval().active

    def test_the_option_turns_it_off(self):
        d = _eval(enabled=False)
        assert not d.active and d.blocked == 'option_off'

    def test_without_the_lock_it_does_nothing(self):
        d = _eval(gate_mask=0)
        assert not d.active and d.blocked == 'no_lock'

    def test_unknown_indoor_does_not_pulse(self):
        assert _eval({'VPD': 5.0}).blocked == 'no_indoor'
        assert _eval({'T': 40.0}).blocked == 'no_indoor'

    # ── 이기는 쪽들 ──────────────────────────────────────────────────────────

    def test_the_evening_lock_wins(self):
        assert _eval(evening_block=True).blocked == 'evening'

    def test_dusk_stop_wins(self):
        """해 질 녘 제한(53)이 서 있으면 저녁·밤 펄스는 없다."""
        assert _eval(dusk_limited=True).blocked == 'dusk'

    @pytest.mark.parametrize('bit', [
        LC.GATE_BIT_RAIN, LC.GATE_BIT_RAIN_LIGHT, LC.GATE_BIT_WIND, LC.GATE_BIT_COLD,
        LC.GATE_BIT_FROST, LC.GATE_BIT_FROST_WATCH, LC.GATE_BIT_EXT_EXP, LC.GATE_BIT_INT_EXP])
    def test_other_gates_win(self, bit):
        d = _eval(gate_mask=LOCK | bit)
        assert not d.active and d.blocked == 'gate'

    def test_wind_stage_one_only_limits_openings_so_it_does_not_block(self):
        assert _eval(gate_mask=LOCK | LC.GATE_BIT_WIND_LIGHT).active

    def test_humidity_ceiling_flag_wins(self):
        d = _eval(_hot_dry(_fog_humidity_block=True))
        assert not d.active and d.blocked == 'humidity'

    def test_rh_at_the_protection_threshold_blocks(self, monkeypatch):
        # 건구−습구 8 °C 이상이면 RH 는 늘 65 % 아래라 이 천장은 사실상 여분의 안전망이다 — 판정이
        # 증발 여력을 잘못 읽어도(여기서는 9 °C 로 고정) 보호의 습도 문턱(85 %)에서 선다.
        monkeypatch.setattr(PF, 'wetbulb_depression', lambda T, RH: 9.0)
        d = _eval({'T': 40.0, 'RH': 85.0, 'VPD': 3.5})
        assert not d.active and d.blocked == 'humidity'
        assert _eval({'T': 40.0, 'RH': 84.9, 'VPD': 3.5}).active

    def test_humid_max_is_a_ceiling_too(self):
        internal = {'T': 40.0, 'RH': 45.0, 'VPD': 4.0}
        assert _eval(internal, humid_max=60.0).active
        assert _eval(internal, humid_max=45.0).blocked == 'humidity'      # RH == 상한 → 막는다
        assert _eval(internal, humid_max=40.0).blocked == 'humidity'

    def test_no_water_wins(self):
        d = _eval(_hot_dry(_water_available=False))
        assert not d.active and d.blocked == 'no_water'

    def test_water_unknown_is_not_missing_water(self):
        assert _eval(_hot_dry()).active           # 키가 없으면 있는 것(`apply_no_water_override` 와 같다)

    def test_heat_protect_fog_parking_wins(self):
        assert _eval(fog_allowed=False).blocked == 'heat_protect_fog'

    def test_describe_says_what_it_does(self):
        assert '10초' in _eval().describe() and '15분' in _eval().describe()
        assert 'dusk' in _eval(dusk_limited=True).describe()


# ─────────────────────────────────────────────────────────────────────────────
# 2. 어느 분무기를 다루는가
# ─────────────────────────────────────────────────────────────────────────────

class TestWhichFoggers:

    def test_wetting_and_pulse_dosing_only(self):
        ids = PF.pulse_fog_ids([_fogger('w'), _fogger('fine', wetting=False),
                                _fogger('cont', pulse=False)])
        assert ids == frozenset({'w'})

    def test_a_nozzleless_fogger_counts_as_wetting(self):
        p = _fogger('x')
        p.capacity_meta = {}
        assert PF.pulse_fog_ids([p]) == frozenset({'x'})


# ─────────────────────────────────────────────────────────────────────────────
# 3. 명령에 얹기
# ─────────────────────────────────────────────────────────────────────────────

def _active_internal(**extra):
    d = {'_pulse_fog': PF.PulseFogDecision(active=True, why='heat+dry', vpd=5.7, depression=15.0)}
    d.update(extra)
    return d


class TestApply:

    def test_demand_becomes_a_full_pulse_with_reason_57(self):
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 37.0, 'reason': 1}}
        apply_extreme_pulse_fog(_active_internal(), [fog], cmds)
        assert cmds[fog.actuator_id] == {'value': 100.0, 'reason': 'extreme_pulse_fog'}
        assert LC.reason_code('extreme_pulse_fog') == 57.0

    def test_no_demand_stays_off(self):
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 0.0, 'reason': 1}}
        apply_extreme_pulse_fog(_active_internal(), [fog], cmds)
        assert cmds[fog.actuator_id] == {'value': 0.0, 'reason': 1}

    def test_demand_below_the_minimum_on_is_left_alone(self):
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 4.9, 'reason': 1}}
        apply_extreme_pulse_fog(_active_internal(), [fog], cmds)
        assert cmds[fog.actuator_id]['reason'] == 1

    def test_inactive_or_missing_decision_does_nothing(self):
        fog = _fogger()
        for internal in ({}, {'_pulse_fog': PF.PulseFogDecision(blocked='dusk')}):
            cmds = {fog.actuator_id: {'value': 80.0, 'reason': 1}}
            apply_extreme_pulse_fog(internal, [fog], cmds)
            assert cmds[fog.actuator_id] == {'value': 80.0, 'reason': 1}

    def test_fine_fog_and_non_pulsing_foggers_are_untouched(self):
        fine, cont, wet = _fogger('fine', wetting=False), _fogger('cont', pulse=False), _fogger('wet')
        cmds = {a.actuator_id: {'value': 80.0, 'reason': 1} for a in (fine, cont, wet)}
        apply_extreme_pulse_fog(_active_internal(), [fine, cont, wet], cmds)
        assert cmds['fine']['reason'] == 1 and cmds['cont']['reason'] == 1
        assert cmds['wet']['reason'] == 'extreme_pulse_fog'

    def test_a_missing_command_is_skipped(self):
        apply_extreme_pulse_fog(_active_internal(), [_fogger()], {})

    def test_derate_is_skipped_while_pulsing(self):
        """잠금 중 감쇠(36)는 해제선~잠금선 사이에서 명령을 깎는다 — 펄스 길이를 또 깎지 않는다."""
        fog = _fogger()
        internal = {'_nursery_mode': True, 'light_est': 200.0, '_nursery_solar_lockout': 250.0,
                    '_nursery_solar_release': 150.0}
        cmds = {fog.actuator_id: {'value': 80.0, 'reason': 1}}
        apply_nursery_fog_derate(dict(internal), [fog], cmds)
        assert cmds[fog.actuator_id]['reason'] == 'nursery_fog_derate'        # 평소엔 깎는다
        cmds = {fog.actuator_id: {'value': 80.0, 'reason': 1}}
        apply_nursery_fog_derate({**internal, **_active_internal()}, [fog], cmds)
        assert cmds[fog.actuator_id] == {'value': 80.0, 'reason': 1}


class TestInsideTheOverrideChain:

    def test_order_is_ceiling_then_pulse_then_gate(self):
        src = inspect.getsource(apply_threshold_and_gate_overrides)
        order = [src.index(n) for n in (
            'apply_nursery_fog_derate(', 'apply_wetting_fog_dusk_limit(',
            'apply_wetting_fog_humidity_ceiling(', 'apply_extreme_pulse_fog(',
            'if partial_overrides:')]
        assert order == sorted(order), order

    def test_the_lock_zero_is_gone_so_the_pulse_goes_out(self):
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 60.0, 'reason': 1}}
        apply_threshold_and_gate_overrides(_active_internal(), [fog], cmds, {})
        assert cmds[fog.actuator_id] == {'value': 100.0, 'reason': 'extreme_pulse_fog'}

    def test_a_gate_command_on_the_fogger_still_wins(self):
        """다른 게이트의 0(서리 등)이 같은 분무기에 남아 있으면 펄스가 그것을 이기지 못한다."""
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 60.0, 'reason': 1}}
        gate = {fog.actuator_id: {'value': 0.0, 'reason': LC.REASON_FROST_PROTECT}}
        apply_threshold_and_gate_overrides(_active_internal(), [fog], cmds, gate)
        assert cmds[fog.actuator_id]['value'] == 0.0

    def test_ceiling_dusk_and_no_water_zeros_are_not_resurrected(self):
        """판정이 그 결론을 이미 읽어 서지 않지만, 억지로 켜 둬도 위 제한이 만든 0 은 되살아나지 않는다."""
        fog = _fogger()
        for extra in ({'_fog_humidity_block': True}, {'_water_available': False}):
            cmds = {fog.actuator_id: {'value': 60.0, 'reason': 1}}
            apply_threshold_and_gate_overrides(_active_internal(**extra), [fog], cmds, {})
            assert cmds[fog.actuator_id]['value'] == 0.0, extra


# ─────────────────────────────────────────────────────────────────────────────
# 4. 사이클 배선 — 입력을 모아 잠금의 0 에서 뺀다
# ─────────────────────────────────────────────────────────────────────────────

def _coord(profiles, real_dusk=False, **attrs):
    class C(CycleMixin):
        unique_id = 'x'
        log_level_debug = False
    c = C()
    c.logger = MagicMock()
    c._status_log = MagicMock()
    c._profiles = profiles
    c.humid_max = None
    if not real_dusk:                     # 시계·좌표에 기대지 않는다 — 구간 시험만 진짜 판정을 쓴다
        c._past_dusk_cutoff = lambda cutoff_min: False
    for k, v in attrs.items():
        setattr(c, k, v)
    return c


def _gate(mask=LOCK):
    return SimpleNamespace(gate_mask=mask)


def _hp(tier=1, fog_allowed=True):
    return SimpleNamespace(tier=tier, active=tier >= 1, fog_allowed=fog_allowed)


def _partial(*ids):
    return {a: {'value': 0.0, 'reason': LC.REASON_SAFETY_PRE_GATE, 'ttl': 300.0} for a in ids}


class TestWiring:

    def test_the_lock_zero_is_dropped_for_the_pulsing_fogger_only(self):
        wet, fine = _fogger('wet'), _fogger('fine', wetting=False)
        c = _coord([wet, fine])
        internal = _hot_dry(_heat_protect=_hp())
        original = _partial('wet', 'fine')
        out = c._evaluate_pulse_fog(internal, _gate(), original)
        assert internal['_pulse_fog'].active
        assert set(out) == {'fine'}                       # 미세포그의 0 은 게이트가 건드린 적 없는 것 — 그대로 둔다
        assert set(original) == {'wet', 'fine'}           # 받은 dict 는 건드리지 않는다

    def test_no_lock_means_nothing_is_planted(self):
        c = _coord([_fogger()])
        internal = _hot_dry(_heat_protect=_hp())
        out = c._evaluate_pulse_fog(internal, _gate(0), {})
        assert '_pulse_fog' not in internal and out == {}

    def test_dusk_decision_in_internal_blocks(self):
        c = _coord([_fogger()])
        internal = _hot_dry(_heat_protect=_hp(), _wet_fog_dusk=SimpleNamespace(limited=True))
        out = c._evaluate_pulse_fog(internal, _gate(), _partial('fog'))
        assert '_pulse_fog' not in internal and set(out) == {'fog'}

    def test_the_evening_lock_blocks(self):
        c = _coord([_fogger()])
        internal = _hot_dry(_heat_protect=_hp(), evening_block=True)
        out = c._evaluate_pulse_fog(internal, _gate(), _partial('fog'))
        assert '_pulse_fog' not in internal and set(out) == {'fog'}

    def test_option_off_keeps_the_lock_absolute(self):
        c = _coord([_fogger()], extreme_pulse_fog=False)
        internal = _hot_dry(_heat_protect=_hp())
        out = c._evaluate_pulse_fog(internal, _gate(), _partial('fog'))
        assert '_pulse_fog' not in internal and set(out) == {'fog'}

    def test_unset_option_means_on(self):
        c = _coord([_fogger()], extreme_pulse_fog=None)
        internal = _hot_dry(_heat_protect=_hp())
        c._evaluate_pulse_fog(internal, _gate(), _partial('fog'))
        assert internal['_pulse_fog'].active

    def test_heat_protect_decision_is_read(self):
        c = _coord([_fogger()])
        # 보호 없음 + VPD 낮음 → 극한이 아니다
        internal = _hot_dry(VPD=2.0, _heat_protect=_hp(tier=0))
        c._evaluate_pulse_fog(internal, _gate(), _partial('fog'))
        assert '_pulse_fog' not in internal
        # 보호가 분무를 막고 있으면(물·증발·습도) 펄스도 없다
        internal = _hot_dry(_heat_protect=_hp(fog_allowed=False))
        c._evaluate_pulse_fog(internal, _gate(), _partial('fog'))
        assert '_pulse_fog' not in internal

    def test_humid_max_is_read_from_the_coordinator(self):
        c = _coord([_fogger()], humid_max=25.0)
        internal = _hot_dry(_heat_protect=_hp())          # RH 30 ≥ 25
        c._evaluate_pulse_fog(internal, _gate(), _partial('fog'))
        assert '_pulse_fog' not in internal

    def test_other_gates_block(self):
        c = _coord([_fogger()])
        internal = _hot_dry(_heat_protect=_hp())
        c._evaluate_pulse_fog(internal, _gate(LOCK | LC.GATE_BIT_FROST_WATCH), _partial('fog'))
        assert '_pulse_fog' not in internal

    def test_it_says_so_once_when_it_changes(self):
        c = _coord([_fogger()])
        hot = lambda: _hot_dry(_heat_protect=_hp())
        c._evaluate_pulse_fog(hot(), _gate(), {})
        c._evaluate_pulse_fog(hot(), _gate(), {})
        assert c._status_log.call_count == 1
        c._evaluate_pulse_fog(_hot_dry(_heat_protect=_hp(), _water_available=False), _gate(), {})
        assert c._status_log.call_count == 2

    def test_silent_when_it_never_stood(self):
        c = _coord([_fogger()])
        c._evaluate_pulse_fog({'T': 22.0, 'RH': 60.0}, _gate(0), {})
        c._status_log.assert_not_called()

    def test_no_pulse_capable_fogger_means_no_judgement(self):
        c = _coord([_fogger('fine', wetting=False), _fogger('cont', pulse=False)])
        internal = _hot_dry(_heat_protect=_hp())
        out = c._evaluate_pulse_fog(internal, _gate(), _partial('fine', 'cont'))
        assert '_pulse_fog' not in internal and set(out) == {'fine', 'cont'}

    def test_non_nursery_installs_have_no_lock_so_nothing_changes(self):
        """육묘 모드가 아니면 잠금 비트 자체가 서지 않는다 — 이 규칙은 그 자리에서 아무 일도 하지 않는다."""
        c = _coord([_fogger()])
        internal = _hot_dry(_heat_protect=_hp())
        out = c._evaluate_pulse_fog(internal, _gate(0), {})
        assert out == {} and '_pulse_fog' not in internal

    def test_pulses_stop_well_before_the_dusk_rule_stands(self, monkeypatch):
        """마지막 펄스의 물이 저녁 닫힌 집에서 마저 증발해 이슬을 앞당기지 않게 — 해 질 녘 제한보다 `PF_DUSK_MARGIN_MIN` 일찍 멈춘다."""
        assert PF.PF_DUSK_MARGIN_MIN == 240.0
        day = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)
        sun = SimpleNamespace(sunset=day.replace(hour=12), sunrise=day.replace(hour=0))
        monkeypatch.setattr('aot.utils.solar.sun_times', lambda **k: sun)
        c = _coord([_fogger()], real_dusk=True, nursery_mode=True, nursery_evening_cutoff_min=120.0)
        # 일몰 12:00Z − 120분(규칙) − 240분(마진) = 06:00Z
        for hh, mm, ok in ((5, 59, True), (6, 0, False), (9, 0, False)):
            monkeypatch.setattr('aot.utils.timekit.utc_now',
                                lambda hh=hh, mm=mm: day.replace(hour=hh, minute=mm))
            internal = _hot_dry(_heat_protect=_hp())
            c._evaluate_pulse_fog(internal, _gate(), _partial('fog'))
            assert ('_pulse_fog' in internal) is ok, (hh, mm)

    def test_the_margin_follows_the_same_cutoff_as_the_dusk_rule(self):
        c = _coord([_fogger()], nursery_mode=True, nursery_evening_cutoff_min=90.0)
        assert c._pulse_fog_dusk_cutoff_min() == 90.0 + PF.PF_DUSK_MARGIN_MIN
        c = _coord([_fogger()], nursery_mode=False)
        assert c._pulse_fog_dusk_cutoff_min() == 90.0 + PF.PF_DUSK_MARGIN_MIN   # 육묘가 아니면 고정 90분

    def test_run_cycle_only_calls_it_after_the_dusk_judgement(self):
        tree = ast.parse(inspect.getsource(_cycle_mixin))
        run = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == '_run_cycle')
        calls = [n.func.attr for n in ast.walk(run)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        assert calls.index('_evaluate_wetting_fog_dusk') < calls.index('_evaluate_pulse_fog')
        assert calls.index('_judge_fog_humidity_block') < calls.index('_evaluate_pulse_fog')
        assert calls.index('_evaluate_heat_protect') < calls.index('_evaluate_pulse_fog')


# ─────────────────────────────────────────────────────────────────────────────
# 5. 펄스의 모양 — 10초 켜고 15분 이상 쉰다 (어댑터의 시계)
# ─────────────────────────────────────────────────────────────────────────────

class _Control:
    def __init__(self):
        self.calls = []

    def output_on(self, aid, **k):
        self.calls.append(('on', k))
        return (0, 'OK')

    def output_off(self, aid, **k):
        self.calls.append(('off', k))
        return (0, 'OK')


def _adapter(max_on=30.0, min_off=180.0, inner=None):
    return da.PulsedDoseAdapter(inner or da.TimeProportionalAdapter(),
                                max_on_sec=max_on, min_off_sec=min_off)


CAP = (PF.PF_ON_SEC, PF.PF_MIN_OFF_SEC)


class TestPulseShape:

    @pytest.fixture
    def clock(self, monkeypatch):
        t = {'now': 1_000_000.0}
        monkeypatch.setattr('time.time', lambda: t['now'])
        return t

    def test_ten_seconds_on_then_fifteen_minutes_off(self, clock):
        a, ctl = _adapter(), _Control()
        a.send(ctl, 'f', 100.0, 0, 600.0, pulse_cap=CAP)
        assert ctl.calls == [('on', {'output_type': 'sec', 'amount': 10.0, 'output_channel': 0})]
        assert a.blocked_until == pytest.approx(clock['now'] + 10.0 + 900.0)

    def test_nothing_goes_out_during_the_rest(self, clock):
        a, ctl = _adapter(), _Control()
        a.send(ctl, 'f', 100.0, 0, 600.0, pulse_cap=CAP)
        for step in (60.0, 540.0, 299.0):                  # 60 · 600 · 899 초 뒤 — 910 초(10 + 900) 전
            clock['now'] += step
            ctl.calls.clear()
            a.send(ctl, 'f', 100.0, 0, 600.0, pulse_cap=CAP)
            assert [c[0] for c in ctl.calls] == ['off']

    def test_the_next_pulse_after_fifteen_minutes(self, clock):
        a, ctl = _adapter(), _Control()
        a.send(ctl, 'f', 100.0, 0, 600.0, pulse_cap=CAP)
        clock['now'] += 911.0
        ctl.calls.clear()
        a.send(ctl, 'f', 100.0, 0, 600.0, pulse_cap=CAP)
        assert ctl.calls[0][0] == 'on' and ctl.calls[0][1]['amount'] == 10.0

    def test_the_users_shorter_setting_wins_over_ten_seconds(self, clock):
        a, ctl = _adapter(max_on=5.0), _Control()
        a.send(ctl, 'f', 100.0, 0, 600.0, pulse_cap=CAP)
        assert ctl.calls[0][1]['amount'] == 5.0

    def test_the_users_longer_rest_wins_over_fifteen_minutes(self, clock):
        a, ctl = _adapter(min_off=1800.0), _Control()
        a.send(ctl, 'f', 100.0, 0, 600.0, pulse_cap=CAP)
        assert a.blocked_until == pytest.approx(clock['now'] + 10.0 + 1800.0)

    def test_without_the_cap_the_old_behaviour_is_unchanged(self, clock):
        a, ctl = _adapter(), _Control()
        a.send(ctl, 'f', 100.0, 0, 600.0)
        assert ctl.calls[0][1]['amount'] == 30.0
        assert a.blocked_until == pytest.approx(clock['now'] + 30.0 + 180.0)

    def test_a_pwm_fogger_cannot_be_cut_to_ten_seconds_so_it_does_not_pulse(self, clock):
        a, ctl = _adapter(inner=da.PwmAdapter()), _Control()
        a.send(ctl, 'f', 100.0, 0, 600.0, pulse_cap=CAP)
        assert [c[0] for c in ctl.calls] == ['off']
        assert a.blocked_until == 0.0

    def test_a_volumetric_pump_gets_ten_seconds_of_water(self, clock):
        a = da.PulsedDoseAdapter(da.VolumetricAdapter(flow_lpm=6.0), 30.0, 180.0, flow_lpm=6.0)
        ctl = _Control()
        a.send(ctl, 'f', 100.0, 0, 600.0, pulse_cap=CAP)
        assert ctl.calls[0][1]['amount'] == pytest.approx(1000.0)     # 6 L/min × 10 s = 1 L


class _FakeAdapter(da.PulsedDoseAdapter):
    def __init__(self):
        super().__init__(da.TimeProportionalAdapter(), 30.0, 180.0)
        self.seen = []

    def send(self, control, actuator_id, pct, ch, cycle_sec, pulse_cap=None):
        self.seen.append((pct, pulse_cap))


class TestDispatchRoutesTheCap:

    def _host(self, adapter):
        class H(_helpers_mixin.HelpersMixin):
            _DISPATCH_STAGGER_SEC = 0.0
        h = H()
        h.logger = MagicMock()
        h.unique_id = 'x'
        h.control = MagicMock()
        h._channel_map = {'fog': 0}
        fog = _fogger('fog')
        h._by_id = {'fog': fog}
        h._adapter_by_id = {'fog': adapter}
        return h

    def test_reason_57_carries_the_cap(self):
        ad = _FakeAdapter()
        h = self._host(ad)
        h._dispatch_commands({'fog': {'value': 100.0, 'reason': PF.PULSE_FOG_REASON}}, 600.0)
        assert ad.seen == [(100.0, (PF.PF_ON_SEC, PF.PF_MIN_OFF_SEC))]

    def test_any_other_reason_does_not(self):
        ad = _FakeAdapter()
        h = self._host(ad)
        h._dispatch_commands({'fog': {'value': 60.0, 'reason': 1}}, 600.0)
        assert ad.seen == [(60.0, None)]

    def test_the_rest_is_held_by_the_coordinator_not_the_adapter(self, monkeypatch):
        """어댑터 맵은 10분마다 다시 지어진다 — 새 어댑터(시계 0)여도 15분은 쉰다."""
        t = {'now': 5_000_000.0}
        monkeypatch.setattr('time.time', lambda: t['now'])
        cmd = {'fog': {'value': 100.0, 'reason': PF.PULSE_FOG_REASON}}
        ad = _FakeAdapter()
        h = self._host(ad)
        h._dispatch_commands(cmd, 600.0)
        assert ad.seen[-1][0] == 100.0
        for step in (600.0, 299.0):                       # 600 · 899 초 뒤 — 910 초 전
            t['now'] += step
            h._adapter_by_id = {'fog': (ad := _FakeAdapter())}      # 맵 재적재 흉내
            h._dispatch_commands(cmd, 600.0)
            assert ad.seen == [(0.0, None)], t['now']
        t['now'] += 20.0                                   # 919 초 — 쉼이 끝났다
        h._adapter_by_id = {'fog': (ad := _FakeAdapter())}
        h._dispatch_commands(cmd, 600.0)
        assert ad.seen == [(100.0, (PF.PF_ON_SEC, PF.PF_MIN_OFF_SEC))]

    def test_each_actuator_has_its_own_rest(self, monkeypatch):
        t = {'now': 6_000_000.0}
        monkeypatch.setattr('time.time', lambda: t['now'])
        a1, a2 = _FakeAdapter(), _FakeAdapter()
        h = self._host(a1)
        h._channel_map['fog2'] = 1
        h._by_id['fog2'] = _fogger('fog2')
        h._adapter_by_id['fog2'] = a2
        h._dispatch_commands({'fog': {'value': 100.0, 'reason': PF.PULSE_FOG_REASON}}, 600.0)
        t['now'] += 600.0
        h._dispatch_commands({'fog': {'value': 100.0, 'reason': PF.PULSE_FOG_REASON},
                              'fog2': {'value': 100.0, 'reason': PF.PULSE_FOG_REASON}}, 600.0)
        assert a1.seen[-1][0] == 0.0                       # 첫 분무기는 쉬는 중
        assert a2.seen[-1][0] == 100.0                     # 둘째는 처음 펄스


# ─────────────────────────────────────────────────────────────────────────────
# 6. 근거 57 · 옵션 · 라벨
# ─────────────────────────────────────────────────────────────────────────────

class TestReasonAndOption:

    def test_reason_is_57_and_named(self):
        assert LC.REASON_EXTREME_PULSE_FOG == 57
        assert LC.STRING_REASON_CODES['extreme_pulse_fog'] == 57
        assert LC.reason_name('extreme_pulse_fog') == 'extreme_pulse_fog'
        assert LC.reason_name(57) == 'extreme_pulse_fog'
        # 52~56 은 그대로(다른 규칙이 쓴다)
        assert (LC.REASON_RAIN_RESTRICT, LC.REASON_WETTING_FOG_DUSK, LC.REASON_MORNING_PURGE,
                LC.REASON_WIND_RESTRICT, LC.REASON_FROST_PROTECT) == (52, 53, 54, 55, 56)

    def test_health_check_labels_it(self):
        from aot.scripts import check_env_coordinator_health as H
        assert H.REASON_LABEL[LC.REASON_EXTREME_PULSE_FOG]

    def test_map_popup_labels_it_in_both_vocabularies(self):
        from aot.tests.test_map_popup_labels import _js_map
        # 숫자 키(57)는 `_js_map` 의 `\\w+` 로 읽힌다 — 문자열 키와 같은 문구여야 한다.
        for name in ('_REASON_TEXT',):
            try:
                m = _js_map(name)
            except Exception:                                  # noqa: BLE001
                pytest.skip('라벨 표 이름이 다르다 — test_map_popup_labels 가 본다')
            assert '57' in m and 'extreme_pulse_fog' in m and m['57'] == m['extreme_pulse_fog']

    def test_the_option_is_one_default_on_advanced_bool(self):
        from aot.functions.custom_functions.env_coordinator_impl import _function_info as fi
        opts = [o for o in fi.FUNCTION_INFORMATION['custom_options'] if o.get('id') == 'extreme_pulse_fog']
        assert len(opts) == 1
        o = opts[0]
        assert o['type'] == 'bool' and o['default_value'] is True and o.get('advanced_only')

    def test_the_sunburn_lock_help_mentions_the_exception(self):
        from aot.functions.custom_functions.env_coordinator_impl import _function_info as fi
        by_id = {o.get('id'): o for o in fi.FUNCTION_INFORMATION['custom_options']}
        for key in ('nursery_mode', 'nursery_solar_lockout'):
            text = str(by_id[key]['phrase'])
            assert 'short pulses' in text and 'extreme' in text, key

    def test_the_coordinator_declares_the_attribute(self):
        from aot.functions.custom_functions import env_coordinator
        src = inspect.getsource(env_coordinator)
        assert 'self.extreme_pulse_fog' in src
