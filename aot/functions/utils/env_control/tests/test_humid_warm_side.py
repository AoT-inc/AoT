# coding=utf-8
"""과습 열림 — VPD 직접 모드에서 '실외가 너무 참'(근거 27)이 거짓으로 서던 문제와 열림 상한 풀기 (2026-10-14).

## 실측 (김제 육묘장3, 2026-10-13, 개발서버 influx 읽기 전용)

    시각   실내 T/RH   실외 T/RH   온도 차  이슬점 차   당시 판정
    12:48  20.8 / 92   18.8 / 81    2.0     3.9      27(COLD) — 측창 0·11 %
    13:58  23.2 / 86   21.5 / 70    1.7     4.8      27(COLD) — 측창 12·18 %
    14:49  20.2 / 84   21.7 / 64   -1.5     2.8      25(상한 30 %)

12:48~15:59 실내는 VPD 0.21~0.45 · RH 82~91 % 였고 실외는 기온이 거의 같으면서 이슬점이 3~4 °C 낮았다 — 열면 습기가
빠지는 조건. 그런데 측창은 6~30 % 였고 두 번 27 로 닫혔다.

## 원인

`decide_parking` 2.65 의 `_warm_side`('목표 근처 이하 · 난방 요구')가 VPD 직접 모드의 **유도 온도 목표**를 기준으로
삼았다. 그 목표는 실내 + 0.6 × (VPD 를 맞추는 데 필요한 만큼)이라 늘 실내보다 앞서 있어서 '실내 ≤ 목표 + 허용오차' 와
'유도 목표에서 나온 난방 요구'(`_demand == 'heat'`)가 늘 참이었다. `relief_verdict` 는 그러면 실외가 1 °C 만 차가워도
COLD 로 닫는다. 아침 습기 빼기(근거 54)는 같은 함정을 유도 범위의 아래 끝으로 피했으나, 과습 판정에는 그 처리가 없었다.
여기에 열림 상한 `CAP_PCT`(30 %)가 겹쳐, 열어도 되는 때에도 30 % 였다.
"""
import inspect

import pytest

from aot.functions.utils.env_control import coordinator as C
from aot.functions.utils.env_control import humid_regime as HR
from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate, decide_parking,
)
from aot.functions.utils.env_control.log_channels import (
    REASON_HUMID_CAPPED, REASON_HUMID_COLD,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)

# 김제 2026-10-13 — (실내 T, RH, 실외 T, RH)
K_1248 = (20.8, 92, 18.8, 81)
K_1358 = (23.2, 86, 21.5, 70)
K_1207 = (20.8, 91, 17.3, 88)       # 온도 차 3.5 — 열 손실이 작지 않다
K_1449 = (20.2, 84, 21.7, 64)       # 이슬점 차 2.8 — 충분히 건조하지 않다

GUIDE_LOW = 15.0                    # VPD 직접 모드의 유도 범위 아래 끝(하드 최저로 좁힌 뒤)


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


def _p(aid='v'):
    p = ActuatorProfile(
        actuator_id=aid, kind='opening', effect_model={'vpd': _effect('↑', 0.4)},
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)
    p.cmd_scale = 1.0
    return p


class _Sit:
    """VPD 직접 모드(`mode='vpd'`)면 온도 목표가 `_temperature_constraint` 로 강등돼 있고 값은 **실내보다 앞선다**
    (유도 목표). 온도 제어 모드(`mode='temp'`)면 'temperature' 가 제어 목표(22 ± 1)다."""

    def __init__(self, T_in, mode='vpd', deviation=-0.8, ctx=None):
        self.target = {'vpd': TargetVar(value=0.8, tolerance=0.1, priority=1.2, unit='kPa')}
        if mode == 'vpd':
            self.target['_temperature_constraint'] = TargetVar(
                value=T_in + 2.5, tolerance=1.0, priority=0.5, unit='°C')
        else:
            self.target['temperature'] = TargetVar(
                value=22.0, tolerance=1.0, priority=0.5, unit='°C')
        self.deviation_native = {'vpd': deviation}
        self.context = ctx if ctx is not None else {}


def _ctx(rec, internal=None, guide_low=GUIDE_LOW):
    T_in, RH_in, T_out, RH_out = rec
    ctx = {'cycle_sec': 600.0, 'T_int': T_in, 'RH_int': RH_in, 'T_ext': T_out, 'RH_ext': RH_out,
           'vent_futility_gate': False, 'internal': dict(internal or {}), 'external': {}}
    if guide_low is not None:
        ctx['T_guide_low'] = guide_low
    return ctx


def _pk(rec, mode='vpd', prev=0.0, internal=None, guide_low=GUIDE_LOW):
    ctx = _ctx(rec, internal, guide_low)
    sit = _Sit(rec[0], mode, ctx=ctx)
    return decide_parking([_p()], sit, ctx, 600.0, {'v': prev}, log=False, humid_prev=True)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 기준선 함수 — 정의는 한 곳
# ─────────────────────────────────────────────────────────────────────────────

class TestTempEdge:

    def _tv(self, v=22.0, tol=1.0):
        return TargetVar(value=v, tolerance=tol, priority=0.5, unit='°C')

    def test_a_temperature_control_target_gives_value_minus_or_plus_tolerance(self):
        assert HR.temp_edge_c(self._tv(), 15.0) == pytest.approx(21.0)
        assert HR.temp_edge_c(self._tv(), 15.0, upper=True) == pytest.approx(23.0)

    def test_without_a_temperature_target_it_is_the_guide_low_on_either_side(self):
        assert HR.temp_edge_c(None, 15.0) == 15.0
        assert HR.temp_edge_c(None, 15.0, upper=True) == 15.0

    def test_unknown_is_not_invented(self):
        assert HR.temp_edge_c(None, None) is None

    def test_both_call_sites_share_the_one_function(self):
        """과습 열림(2.65)과 아침 습기 빼기(2.95)가 같은 함수를 부른다 — 정의가 두 벌이면 한쪽만 바뀐다."""
        src = inspect.getsource(C.decide_parking)
        assert src.count('HR.temp_edge_c(') == 1       # 아침 습기 빼기의 아래 선
        assert src.count('HR.warm_side(') == 1         # 과습 열림 — 위 선은 `warm_side` 안에서 같은 함수를 부른다
        # 예전 인라인 정의(목표 ± 허용오차를 직접 계산)가 남아 있지 않다
        assert "_t_tv_w" not in src
        assert "_t_real.value" not in src


# ─────────────────────────────────────────────────────────────────────────────
# 2. COLD 판정 — 김제 10-13 은 더 이상 COLD 가 아니다
# ─────────────────────────────────────────────────────────────────────────────

class TestColdVerdictInVpdMode:

    @pytest.mark.parametrize('rec', [K_1248, K_1358, K_1207, K_1449])
    def test_gimje_1013_is_not_cold(self, rec):
        pk = _pk(rec)
        assert pk.humid_zone
        assert not pk.humid_cold, '유도 목표를 기준으로 삼으면 늘 COLD 였다'
        assert not pk.humid_parked

    def test_the_old_behaviour_would_have_closed_it(self):
        """대조 — 같은 값을 '유도 목표가 기준' 으로 읽으면 COLD 다(고치기 전의 판정)."""
        T_in, RH_in, T_out, RH_out = K_1248
        assert HR.relief_verdict(T_in, RH_in, T_out, RH_out, heat_demand=True) == HR.COLD
        assert HR.relief_verdict(T_in, RH_in, T_out, RH_out, heat_demand=False) == HR.OK

    def test_a_derived_heat_demand_is_not_a_heat_demand(self):
        """VPD 직접 모드의 유도 목표가 실내보다 2.5 °C 앞서(허용오차 1) `_demand == 'heat'` 가 서도 난방 요구가 아니다."""
        pk = _pk(K_1248)
        assert not pk.humid_cold

    def test_below_the_guide_low_with_a_colder_outdoor_it_still_closes(self):
        """진짜 난방 요구 — 실내가 유도 범위의 아래 끝 아래이고 실외가 1 °C 넘게 더 차다."""
        pk = _pk((14.0, 95, 11.0, 60))
        assert pk.humid_zone and pk.humid_cold == {'v'}

    def test_forced_heat_still_closes(self):
        pk = _pk(K_1248, internal={'_force_heat': True})
        assert pk.humid_cold == {'v'}

    def test_winter_heating_still_closes(self):
        """겨울 난방 중(외기가 훨씬 참) — 실내가 유도 범위 안이어도 MAX_COLD_DELTA_C 로 닫는다."""
        pk = _pk((19.0, 94, 3.0, 70))
        assert pk.humid_zone and pk.humid_cold == {'v'}
        # 실내가 하한 아래이기도 하면 말할 것도 없다
        pk = _pk((13.0, 94, 0.0, 70))
        assert pk.humid_cold == {'v'}

    def test_the_max_cold_delta_still_applies_above_the_guide_low(self):
        T_out = 20.8 - (HR.MAX_COLD_DELTA_C + 0.5)
        assert _pk((20.8, 92, T_out, 50)).humid_cold == {'v'}
        assert not _pk((20.8, 92, 20.8 - (HR.MAX_COLD_DELTA_C - 0.5), 50)).humid_cold

    def test_an_unknown_guide_low_is_not_judged_as_warm(self):
        """유도 범위 아래 끝을 모르면 기준선을 지어내지 않는다 — 난방 요구 아니다."""
        assert not _pk(K_1248, guide_low=None).humid_cold


class TestTemperatureModeIsUnchanged:
    """온도가 제어 목표인 모드 — 기준선은 종전처럼 목표 + 허용오차(22 + 1 = 23)."""

    def test_at_or_below_target_plus_tolerance_a_colder_outdoor_closes(self):
        for T_in in (21.0, 22.5, 22.9):
            T_out = T_in - 1.6
            pk = _pk((T_in, 94, T_out, 55), mode='temp')
            assert pk.humid_zone and pk.humid_cold == {'v'}, T_in

    def test_above_target_plus_tolerance_a_colder_outdoor_is_fine(self):
        pk = _pk((24.5, 94, 22.5, 55), mode='temp')
        assert not pk.humid_cold

    def test_even_with_a_guide_low_far_below_the_target_wins(self):
        pk = _pk((22.5, 94, 20.5, 55), mode='temp', guide_low=5.0)
        assert pk.humid_cold == {'v'}

    def test_a_nearly_same_temperature_outdoor_opens(self):
        pk = _pk((22.5, 94, 22.0, 55), mode='temp')
        assert not pk.humid_cold


# ─────────────────────────────────────────────────────────────────────────────
# 3. 열림 상한
# ─────────────────────────────────────────────────────────────────────────────

class TestCapLift:

    def test_the_unit_conditions(self):
        # 김제 12:48 — 온도 차 2.0 · 이슬점 차 3.9
        assert HR.relief_cap_pct(*K_1248) == HR.CAP_FREE_PCT
        assert HR.relief_cap_pct(*K_1358) == HR.CAP_FREE_PCT
        # 열 손실이 크다(온도 차 3.5) / 충분히 건조하지 않다(이슬점 차 2.8)
        assert HR.relief_cap_pct(*K_1207) == HR.CAP_PCT
        assert HR.relief_cap_pct(*K_1449) == HR.CAP_PCT

    def test_the_thresholds_are_the_documented_ones(self):
        assert HR.CAP_LIFT_MAX_COLD_C == 2.0 and HR.CAP_LIFT_DEW_GAP_C == 3.0
        assert HR.CAP_LIFT_DEW_GAP_C > HR.RELIEF_DEW_GAP_C, '상한을 푸는 문턱은 열어도 되는 문턱보다 엄격하다'

    def test_a_warmer_outdoor_that_is_much_drier_lifts_it(self):
        assert HR.relief_cap_pct(14.8, 94, 18.3, 49) == HR.CAP_FREE_PCT

    def test_a_cold_outdoor_keeps_the_cap(self):
        """실외가 차가우면 습기가 더 빠져도 열 손실이 크다 — 지금처럼 30 %."""
        assert HR.relief_cap_pct(25.5, 95, 20.0, 60) == HR.CAP_PCT

    def test_unknown_values_keep_the_cap(self):
        assert HR.relief_cap_pct(None, 90, 20.0, 60) == HR.CAP_PCT
        assert HR.relief_cap_pct(21.0, 90, 20.0, None) == HR.CAP_PCT

    def test_hysteresis_once_lifted_it_stays_lifted_a_bit_longer(self):
        # 온도 차 2.5 는 새로 풀기엔 크고, 이미 풀려 있었다면 괜찮다
        assert HR.relief_cap_pct(21.0, 92, 18.5, 80) == HR.CAP_PCT
        assert HR.relief_cap_pct(21.0, 92, 18.5, 80, was_lifted=True) == HR.CAP_FREE_PCT
        # 이슬점 차도 마찬가지(3 → 2)
        T_in, RH_in = 21.0, 92
        T_out = 20.5
        rh = next(r for r in range(95, 30, -1)
                  if 2.0 <= HR.dew_gap_c(T_in, RH_in, T_out, r) < 3.0)
        assert HR.relief_cap_pct(T_in, RH_in, T_out, rh) == HR.CAP_PCT
        assert HR.relief_cap_pct(T_in, RH_in, T_out, rh, was_lifted=True) == HR.CAP_FREE_PCT

    def test_the_decision_lifts_the_cap_in_gimje_1013(self):
        for rec in (K_1248, K_1358):
            assert not _pk(rec).humid_cap_ids

    def test_the_decision_keeps_the_cap_where_it_was(self):
        assert _pk(K_1207).humid_cap_ids == {'v'}        # 열 손실이 크다
        assert _pk(K_1449).humid_cap_ids == {'v'}        # 충분히 건조하지 않다

    def test_a_cold_outdoor_above_the_guide_low_is_capped_not_closed(self):
        """VPD 직접 모드에서 실내가 하한 위이고 실외가 5 °C 찬 경우 — 예전엔 COLD, 지금은 30 % 로 연다."""
        pk = _pk((25.5, 95, 20.5, 60))
        assert not pk.humid_cold and pk.humid_cap_ids == {'v'}

    def test_a_previous_wide_opening_relaxes_the_threshold(self):
        # 온도 차 2.5 — 닫혀 있었다면 상한 30 %, 직전 40 % 로 열려 있었다면 계속 푼다
        rec = (21.0, 92, 18.5, 80)
        assert _pk(rec, prev=0.0).humid_cap_ids == {'v'}
        assert not _pk(rec, prev=40.0).humid_cap_ids

    def test_the_hard_humidity_limit_still_lifts_it(self):
        assert not _pk(K_1207, internal={'_force_dehumid': True}).humid_cap_ids


# ─────────────────────────────────────────────────────────────────────────────
# 4. 명령까지 — coordinate
# ─────────────────────────────────────────────────────────────────────────────

def _run(rec, mode='vpd', prev=25.0, cycles=40, dev=-0.8, internal=None):
    st = CoordinatorState()
    st.humid_zone = True          # 구간 안에 있던 중(진입 문턱보다 이탈 문턱이 높다)
    st.prev_commands = {'v': prev}
    st.integral = {'v': prev}
    ctx = _ctx(rec, internal)
    cmds = None
    for _ in range(cycles):
        cmds, st = coordinate(_Sit(rec[0], mode, dev, ctx), [_p()], st, unique_id='')
    return cmds, st


class TestCommand:

    def test_gimje_1248_opens_beyond_thirty_without_reason_27(self):
        cmds, st = _run(K_1248)
        assert cmds['v'].reason not in (REASON_HUMID_COLD, REASON_HUMID_CAPPED)
        assert cmds['v'].control_value() > HR.CAP_PCT

    def test_gimje_1358_is_not_closed_with_27(self):
        cmds, st = _run(K_1358)
        assert cmds['v'].reason != REASON_HUMID_COLD
        assert cmds['v'].control_value() > HR.CAP_PCT

    def test_gimje_1449_is_still_capped_at_thirty(self):
        cmds, st = _run(K_1449)
        assert cmds['v'].control_value() <= HR.CAP_PCT + 1e-6
        assert cmds['v'].reason in (REASON_HUMID_CAPPED, 1)
        assert st.integral['v'] <= HR.CAP_PCT + 1e-6

    def test_winter_heating_is_still_closed_with_27(self):
        cmds, st = _run((19.0, 94, 3.0, 70), prev=20.0, cycles=3)
        assert cmds['v'].reason == REASON_HUMID_COLD
        assert cmds['v'].control_value() < 20.0

    def test_temperature_mode_at_the_target_is_still_closed_with_27(self):
        cmds, st = _run((22.5, 94, 20.5, 55), mode='temp', prev=20.0, cycles=3, dev=-0.8)
        assert cmds['v'].reason == REASON_HUMID_COLD
        assert cmds['v'].control_value() < 20.0


# ─────────────────────────────────────────────────────────────────────────────
# 야간 결로 탈출(`_night_vent_decide` 의 warm_side)도 같은 기준선 — 2026-10-14
# ─────────────────────────────────────────────────────────────────────────────
# `_cycle_mixin` 의 `_warm` 이 `target['temperature'] or target['_temperature_constraint']` 를 읽었다. VPD 직접 모드의
# `_temperature_constraint` 는 유도 온도 목표(실내 + 2.5 °C 앞)라 '실내 ≤ 목표 + 허용오차' 가 늘 참 → 실외가 1 °C 넘게
# 차가우면 결로 탈출이 늘 막혔다. 과습 열림(2.65)과 같은 `HR.warm_side` 를 부른다.

class _NightSit:
    """`_Sit` 의 야간 판. context['T_guide_low'] 는 `_run_cycle` 이 `_night_warm_side` 호출 전에 싣는다."""

    def __init__(self, T_in, mode='vpd', guide_low=GUIDE_LOW):
        self.target = {'vpd': TargetVar(value=0.8, tolerance=0.1, priority=1.2, unit='kPa')}
        if mode == 'vpd':
            self.target['_temperature_constraint'] = TargetVar(
                value=T_in + 2.5, tolerance=1.0, priority=0.5, unit='°C')
        else:
            self.target['temperature'] = TargetVar(
                value=22.0, tolerance=1.0, priority=0.5, unit='°C')
        self.context = {'T_guide_low': guide_low}


def _night_coord():
    from datetime import datetime
    from unittest.mock import MagicMock
    from aot.functions.custom_functions.env_coordinator import CustomModule
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.unique_id = 'fn'
    c.night_vent_park = True
    c.night_vent_basis = 'clock'
    c.night_vent_start = '00:00'
    c.night_vent_end = '23:59'
    c._facility_local_now = lambda: datetime(2026, 10, 13, 2, 0)
    return c


# 실내 20.8 °C·95 % / 실외 18.8 °C·60 % — 2 °C 더 차지만 훨씬 건조하다(결로 임박, 열면 덜어진다)
NIGHT_IN = {'T': 20.8, 'RH': 95}
NIGHT_OUT = {'T': 18.8, 'RH': 60}


class TestWarmSideFunction:

    def _tv(self):
        return TargetVar(value=22.0, tolerance=1.0, priority=0.5, unit='°C')

    def test_temperature_control_mode_is_target_plus_tolerance(self):
        assert HR.warm_side(23.0, self._tv(), 15.0) is True
        assert HR.warm_side(23.1, self._tv(), 15.0) is False

    def test_vpd_direct_mode_is_the_guide_low(self):
        assert HR.warm_side(14.9, None, 15.0) is True
        assert HR.warm_side(15.1, None, 15.0) is False

    def test_force_heat_is_always_warm_side(self):
        assert HR.warm_side(30.0, None, 15.0, force_heat=True) is True

    def test_unknown_is_not_warm(self):
        assert HR.warm_side(None, None, 15.0) is False
        assert HR.warm_side(20.0, None, None) is False

    def test_over_humid_and_night_paths_use_the_one_function(self):
        from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin, _helpers_mixin
        assert 'HR.warm_side(' in inspect.getsource(C.decide_parking)
        assert 'HR.warm_side(' in inspect.getsource(_helpers_mixin.HelpersMixin._night_warm_side)
        run_cycle = inspect.getsource(_cycle_mixin)
        assert '_night_warm_side(internal, situation)' in run_cycle
        # 유도 목표(`_temperature_constraint`)로 직접 '따뜻한 쪽' 을 계산하는 옛 인라인이 남아 있지 않다
        assert '_warm = (_t_now is not None' not in run_cycle


class TestNightWarmSide:

    def test_vpd_mode_with_a_leading_derived_target_is_not_warm(self):
        """유도 목표가 실내보다 2.5 °C 앞서 있어도 20.8 °C 는 유도 범위 아래 끝(15 °C) 위 — 보온 쪽이 아니다."""
        c = _night_coord()
        assert c._night_warm_side(NIGHT_IN, _NightSit(20.8, 'vpd')) is False

    def test_vpd_mode_below_the_guide_low_is_warm(self):
        c = _night_coord()
        assert c._night_warm_side({'T': 14.0, 'RH': 95}, _NightSit(14.0, 'vpd')) is True

    def test_vpd_mode_force_heat_is_warm(self):
        c = _night_coord()
        assert c._night_warm_side({'T': 20.8, '_force_heat': True}, _NightSit(20.8, 'vpd')) is True

    def test_temperature_mode_is_unchanged(self):
        """온도 제어 모드는 종전과 같다 — 실내 ≤ 목표 + 허용오차(23 °C)."""
        c = _night_coord()
        assert c._night_warm_side({'T': 22.9}, _NightSit(22.9, 'temp')) is True
        assert c._night_warm_side({'T': 23.1}, _NightSit(23.1, 'temp')) is False


class TestNightEscapeInVpdMode:

    def _decide(self, mode, internal=NIGHT_IN, external=NIGHT_OUT):
        c = _night_coord()
        warm = c._night_warm_side(internal, _NightSit(internal['T'], mode))
        return c._night_vent_decide(dict(internal), dict(external), warm_side=warm)[0], warm

    def test_vpd_mode_dry_cooler_night_air_relieves_condensation(self):
        """김제 꼴의 습한 밤 — 실외가 2 °C 차지만 훨씬 건조하다. 예전에는 늘 '보온 쪽' 이라 닫혀 있었다."""
        parked, warm = self._decide('vpd')
        assert warm is False
        assert parked is False

    def test_vpd_mode_cold_winter_air_still_holds_the_parking(self):
        """겨울 난방 중 — 온도차가 크면(MAX_COLD_DELTA_C 초과) 보온 쪽이 아니어도 열지 않는다(열 손실)."""
        parked, _ = self._decide('vpd', {'T': 20.8, 'RH': 95}, {'T': 3.0, 'RH': 50})
        assert parked is True

    def test_vpd_mode_below_guide_low_holds_the_parking(self):
        parked, warm = self._decide('vpd', {'T': 14.0, 'RH': 95}, {'T': 11.0, 'RH': 60})
        assert warm is True
        assert parked is True

    def test_temperature_mode_at_target_keeps_blocking_colder_air(self):
        """온도 제어 모드(22 ± 1): 22.5 °C 는 보온 쪽 — 2 °C 찬 외기로 탈출하지 않는다(종전 그대로)."""
        parked, warm = self._decide('temp', {'T': 22.5, 'RH': 96}, {'T': 20.5, 'RH': 55})
        assert warm is True
        assert parked is True
