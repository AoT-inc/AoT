# coding=utf-8
"""과습 구간·열어도 소용없는 창·최소 VPD 차이·실외 평균 (2026-10-01).

로컬 시뮬레이터에서 밤에 창이 열리고(3포장) 열렸다 닫혔다 하며 천천히 올라가던(쿠마모토)
동작을 고정한다. 공통 원인은 **공기가 포화에 가까울 때 VPD 로 환기를 판단한 것**이다 —
실외가 따뜻하면 수분이 더 많아도 VPD 가 높게 나와 "열면 건조해진다" 로 읽혔다.
"""
import math

from aot.functions.utils.env_control import coordinator as C
from aot.functions.utils.env_control import humid_regime as HR
from aot.functions.utils.env_control import situation as S
from aot.functions.utils.env_control.authority import derive_authority
from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.ext_smoothing import OutdoorSmoother
from aot.functions.utils.env_control.goal import build_env_target
from aot.functions.utils.env_control.log_channels import (
    REASON_HUMID_CAPPED, REASON_HUMID_COLD, REASON_HUMID_NO_RELIEF,
    REASON_NO_RESPONSE, REASON_PRIMARY,
)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)

# 2026-10-01 로컬에서 기록된 값 — (실내 T, RH, 실외 T, RH)
REC = {
    'k_0320': (14.8, 92, 20.2, 88),      # 쿠마모토: 실외가 **더 습하다**
    'g_2200': (15.3, 90, 19.7, 75),      # 3포장: 실외 이슬점이 더 높다
    'g_0000': (14.1, 91, 20.3, 79),
    'g_0200': (14.5, 93, 19.9, 61),      # 이슬점 차 1.2 °C — 문턱 미만
    'g_0300': (14.8, 94, 18.3, 49),      # 실외가 훨씬 건조하다 — 그리고 더 따뜻하다(상한이 풀린다, 2026-10-14)
    'cold_dry': (25.5, 95, 20.0, 60),    # 실외가 건조하지만 5.5 °C 차다 — 열되 30 % 까지만
}


def _between(T):
    """들어가지는 않지만(VPD ≥ 0.30 · 여유 ≥ 2) 이미 들어가 있으면 못 나오는 습도."""
    return next(r for r in range(99, 50, -1)
                if HR.vpd_kpa(T, r) >= HR.ENTER_VPD_KPA
                and (T - HR.dewpoint_c(T, r)) >= HR.ENTER_MARGIN_C
                and (HR.vpd_kpa(T, r) < HR.EXIT_VPD_KPA
                     or (T - HR.dewpoint_c(T, r)) < HR.EXIT_MARGIN_C))


class TestModule:

    def test_zone_entry_and_exit_have_hysteresis(self):
        # 14.8 °C · 92 % → VPD 0.14 — 과습
        assert HR.in_overhumid_zone(14.8, 92)
        # 들어갈 때는 0.30 미만이어야 하고 나올 때는 0.40 을 넘어야 한다
        T = 20.0
        rh_between = _between(T)
        assert not HR.in_overhumid_zone(T, rh_between, was_in=False)
        assert HR.in_overhumid_zone(T, rh_between, was_in=True)

    def test_unknown_indoor_is_not_a_zone(self):
        assert not HR.in_overhumid_zone(None, 92)
        assert not HR.in_overhumid_zone(14.8, None)

    def test_wetter_outside_air_is_not_relief_even_when_its_vpd_is_higher(self):
        T_in, R_in, T_out, R_out = REC['k_0320']
        assert HR.vpd_kpa(T_out, R_out) > HR.vpd_kpa(T_in, R_in), \
            'VPD 만 보면 실외가 더 건조해 보인다 — 이것이 오판의 원인이었다'
        assert HR.dew_gap_c(*REC['k_0320']) < 0
        assert HR.relief_allowed(*REC['k_0320']) is False

    def test_recorded_night_values(self):
        assert HR.relief_allowed(*REC['g_2200']) is False
        assert HR.relief_allowed(*REC['g_0000']) is False
        assert HR.relief_allowed(*REC['g_0200']) is False       # 1.2 < 1.5
        assert HR.relief_allowed(*REC['g_0300']) is True

    def test_already_open_keeps_with_half_the_gap(self):
        gap = HR.dew_gap_c(*REC['g_0200'])
        assert 0.75 <= gap < 1.5
        assert HR.relief_allowed(*REC['g_0200'], was_open=True) is True

    def test_unknown_outdoor_is_not_judged(self):
        assert HR.relief_allowed(14.8, 92, None, None) is None


def _vent(aid='v'):
    return ActuatorProfile(
        actuator_id=aid, kind='opening', safe_default=0.0,
        effect_model=build_effect_model('opening', {}),
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2})


def _cycle(state, rec, vpd_target=0.8, prev=None, profiles=None, extra=None,
           cycle_sec=60.0):
    T_in, R_in, T_out, R_out = rec
    profs = profiles or [_vent()]
    target = build_env_target(T_target=22.0, T_tol=1.0, T_pri=0.5,
                              RH_target=70.0, RH_tol=5.0, RH_pri=0.5,
                              VPD_target=vpd_target, VPD_tol=0.1, VPD_pri=1.2)
    target.pop('co2', None)
    ext = {'T': T_out, 'RH': R_out, 'T_ext': T_out, 'RH_ext': R_out,
           'wind': 1.0, 'solar': 0.0}
    rep, _ = S.assess(target, {'T': T_in, 'RH': R_in}, ext,
                      cycle_sec=cycle_sec, authority=derive_authority(profs))
    rep.context.update({'cycle_sec': cycle_sec, 'vent_futility_gate': False,
                        'vent_first': False})
    rep.context.update(extra or {})
    if prev is not None:
        state.prev_commands = {p.actuator_id: prev for p in profs}
        state.integral = {p.actuator_id: prev for p in profs}
    return C.coordinate(rep, profs, state, unique_id='t')


class TestCoordinate:

    def test_wetter_outside_parks_the_vent_with_its_own_reason(self):
        cmds, st = _cycle(C.CoordinatorState(), REC['k_0320'], prev=20.0)
        assert cmds['v'].reason == REASON_HUMID_NO_RELIEF
        assert cmds['v'].control_value() < 20.0, '닫는 쪽으로 가야 한다'
        assert st.humid_zone is True

    def test_drier_outside_opens_but_is_capped(self):
        """실외가 건조해도 **차가우면**(열 손실이 크면) 30 % 까지만 연다."""
        state = C.CoordinatorState()
        for i in range(30):
            cmds, state = _cycle(state, REC['cold_dry'], prev=None if i else 25.0)
        assert cmds['v'].control_value() <= HR.CAP_PCT + 1e-6
        assert cmds['v'].reason in (REASON_HUMID_CAPPED, REASON_PRIMARY)
        assert state.integral['v'] <= HR.CAP_PCT + 1e-6, \
            '적분이 상한을 넘어 쌓이면 구간을 나가는 순간 창이 튄다'

    def test_the_cap_is_lifted_at_the_hard_humidity_limit(self):
        state = C.CoordinatorState()
        for i in range(30):
            cmds, state = _cycle(state, REC['cold_dry'], prev=None if i else 25.0,
                                 extra={'internal': {'_force_dehumid': True}})
        assert cmds['v'].control_value() > HR.CAP_PCT, \
            '하드 습도 상한을 넘었으면 상한을 풀어 습기를 빼야 한다'

    def test_a_nearly_same_temperature_and_much_drier_outside_lifts_the_cap(self):
        """열 손실이 작고(실외가 더 따뜻함) 실외가 충분히 건조하면 상한을 푼다(`relief_cap_pct`)."""
        state = C.CoordinatorState()
        for i in range(30):
            cmds, state = _cycle(state, REC['g_0300'], prev=None if i else 25.0)
        assert cmds['v'].control_value() > HR.CAP_PCT

    def test_a_dry_room_is_untouched(self):
        cmds, st = _cycle(C.CoordinatorState(), (26.0, 50, 20.0, 60),
                          vpd_target=1.0, prev=20.0)
        assert st.humid_zone is False
        assert cmds['v'].reason not in (REASON_HUMID_NO_RELIEF, REASON_HUMID_CAPPED)

    def test_heat_emergency_wins_over_the_humid_rule(self):
        cmds, st = _cycle(C.CoordinatorState(), REC['k_0320'], prev=20.0,
                          extra={'internal': {'_force_cool': True}})
        assert st.humid_zone is False
        assert cmds['v'].reason != REASON_HUMID_NO_RELIEF

    def test_unknown_outdoor_is_left_to_the_hold_rule(self):
        cmds, st = _cycle(C.CoordinatorState(), (14.8, 92, None, None),
                          prev=20.0, extra={'T_ext': None, 'RH_ext': None})
        assert cmds['v'].reason != REASON_HUMID_NO_RELIEF

    def test_zone_state_is_carried_between_cycles(self):
        _, st = _cycle(C.CoordinatorState(), REC['k_0320'], prev=20.0)
        assert st.humid_zone is True
        # 경계(VPD 0.30~0.40)에서는 들어가 있던 구간이 유지된다
        T = 20.0
        rh = _between(T)
        _, st2 = _cycle(st, (T, rh, 15.0, 60))
        assert st2.humid_zone is True
        _, st3 = _cycle(C.CoordinatorState(), (T, rh, 15.0, 60))
        assert st3.humid_zone is False


def _weak_vent(g):
    def fn(env, cmd_pct, profile=None):
        return EffectResult('↑', g * 6.0 * (cmd_pct / 100.0))
    return ActuatorProfile(
        actuator_id='v', kind='opening', safe_default=0.0,
        effect_model={'temperature': fn}, cost_fn=lambda e, p: 5.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2})


class _Sit:
    def __init__(self):
        self.target = {'temperature': TargetVar(value=24.0, tolerance=1.0,
                                                priority=1.0, unit='C')}
        self.deviation_native = {'temperature': -4.0}
        self.context = {'cycle_sec': 60.0}


def _run_stall(g, cycles=70, dev=-4.0):
    state = C.CoordinatorState()
    state.prev_commands = {'v': 15.0}
    state.integral = {'v': 15.0}
    out = []
    for _ in range(cycles):
        sit = _Sit()
        sit.deviation_native = {'temperature': dev}
        cmds, state = C.coordinate(sit, [_weak_vent(g)], state, unique_id='t')
        out.append((cmds['v'].control_value(), cmds['v'].reason))
    return out, state


class TestNoResponse:

    def test_a_weak_vent_that_changes_nothing_stops_climbing(self):
        out, _ = _run_stall(0.04)
        assert out[-1][1] == REASON_NO_RESPONSE, out[-5:]
        tail = [v for v, _r in out[-8:]]
        assert max(tail) - min(tail) < 1e-6, '멈춘 뒤에는 더 올라가면 안 된다'

    def test_it_takes_the_full_wait_not_a_few_cycles(self):
        out, _ = _run_stall(0.04, cycles=40)          # 40분 < 45분
        assert all(r != REASON_NO_RESPONSE for _v, r in out)

    def test_a_strong_vent_is_never_frozen(self):
        """효과가 큰 창은 편차가 안 줄어도 더 열어야 한다 — 아직 모자란 것이다."""
        out, _ = _run_stall(0.3)
        assert all(r != REASON_NO_RESPONSE for _v, r in out)

    def test_improving_error_resets_the_clock(self):
        state = C.CoordinatorState()
        state.prev_commands = {'v': 15.0}
        state.integral = {'v': 15.0}
        dev = -4.0
        for i in range(120):
            sit = _Sit()
            # 40분마다 편차가 15 % 좁혀진다 — 반응이 있는 창이다
            sit.deviation_native = {'temperature': dev * (0.85 ** (i // 40))}
            cmds, state = C.coordinate(sit, [_weak_vent(0.04)], state,
                                       unique_id='t')
            assert cmds['v'].reason != REASON_NO_RESPONSE, i

    def test_state_is_not_persisted_fields_exist(self):
        st = C.CoordinatorState()
        assert st.stall_s == {} and st.stall_ref == {} and st.humid_zone is False


class TestFutilityMinimumGap:

    def _futile(self, avail, was_futile=False):
        """need = −0.7(VPD 를 내려야 한다), 실외가 avail 만큼 실내보다 낮다."""
        measured = 1.8
        target = TargetVar(value=measured - 0.7, tolerance=0.1, priority=1.0,
                           unit='kPa')

        class Sit:
            pass
        sit = Sit()
        sit.target = {'vpd': target}
        sit.deviation_native = {'vpd': 0.7}
        prof = ActuatorProfile(
            actuator_id='v', kind='opening', safe_default=0.0,
            effect_model={'vpd': lambda e, c, p=None: EffectResult('↓', 0.3)},
            cmd_constraints=CmdConstraints())
        prof.live_effect = {'vpd': EffectResult('↓', 0.3)}
        # 실외 VPD = measured − avail  →  T_ext=25, RH_ext 를 거꾸로 푼다
        T_e = 25.0
        svp = 0.6108 * math.exp(17.27 * T_e / (T_e + 237.3))
        RH_e = (1.0 - (measured - avail) / svp) * 100.0
        ctx = {'T_ext': T_e, 'RH_ext': RH_e,
               '_futile_prev': {'v'} if was_futile else set()}
        return C._ventilation_is_futile(prof, sit, ctx)

    def test_a_tiny_gap_does_not_move_the_windows(self):
        # 0.15 kPa — 종전(허용오차 0.1)에는 "열어도 된다" 였고 RH 1~2 %p 잡음 안이다.
        # 이력: 새로 무익이 되려면 문턱의 60 %(0.15) 아래, 무익에서 나오려면 문턱(0.25) 이상.
        assert self._futile(0.10) is True
        assert self._futile(0.22, was_futile=True) is True
        assert self._futile(0.30, was_futile=True) is False
        assert self._futile(0.30) is False

    def test_the_verdict_does_not_flip_inside_the_band(self):
        """문턱 0.25 근처 0.17~0.24 에서 흔들려도 판정이 뒤집히지 않는다 — 창이 톱니가 되지 않는다."""
        for g in (0.17, 0.20, 0.24):
            assert self._futile(g, was_futile=False) is False
            assert self._futile(g, was_futile=True) is True

    def test_the_minimum_gap_is_named(self):
        assert C.VENT_MIN_VPD_GAP >= 0.2

    def test_a_clear_gap_still_counts(self):
        # 실외가 0.5 kPa 더 건조하지 않게(= VPD 를 내릴 방향) — 열 수 있다
        assert self._futile(0.5) is False
        # 방향이 반대로 크게 틀리면 무익이다
        assert self._futile(-0.5) is True


class TestOutdoorSmoother:

    def test_a_step_is_followed_gradually(self):
        sm = OutdoorSmoother()
        sm.smooth({'T': 20.0, 'RH': 88.0}, 0.0)
        a = sm.smooth({'T': 20.0, 'RH': 94.0}, 60.0)['RH']
        b = sm.smooth({'T': 20.0, 'RH': 94.0}, 1800.0)['RH']
        assert 88.0 < a < 89.0
        assert 93.0 < b < 94.0     # τ=10분 — 30분 뒤면 거의 따라온다

    def test_the_input_is_not_modified_and_other_keys_pass_through(self):
        sm = OutdoorSmoother()
        src = {'T': 20.0, 'RH': 88.0, 'wind': 7.0, 'rain': 1.0}
        sm.smooth(src, 0.0)
        src2 = {'T': 21.0, 'RH': 70.0, 'wind': 9.0, 'rain': 2.0}
        out = sm.smooth(src2, 60.0)
        assert src2['RH'] == 70.0
        assert out['wind'] == 9.0 and out['rain'] == 2.0, \
            '안전 게이트가 읽는 값은 평균하지 않는다'

    def test_a_long_gap_restarts_from_the_raw_value(self):
        sm = OutdoorSmoother()
        sm.smooth({'T': 10.0, 'RH': 50.0}, 0.0)
        out = sm.smooth({'T': 25.0, 'RH': 90.0}, 10000.0)
        assert out['T'] == 25.0 and out['RH'] == 90.0

    def test_synthetic_context_is_not_smoothed(self):
        sm = OutdoorSmoother()
        src = {'T': 20.0, 'RH': 60.0, '_ext_synthetic': True}
        assert sm.smooth(src, 0.0) is src

    def test_missing_values_pass_through(self):
        sm = OutdoorSmoother()
        out = sm.smooth({'T': None, 'RH': 70.0}, 0.0)
        assert out['T'] is None


class TestWinterHeating:
    """겨울 난방 중 — 온도차가 큰데 열면 열을 버린다 (2026-10-01 사용자 지적).

    실외 이슬점은 훨씬 낮아 "습기를 뺀다" 로 읽히지만(WET 이 아니다), 온도를 안 보면 창이 열린다.
    """
    WINTER = [(20, 95, 0, 80), (20, 95, -5, 70), (18, 92, 5, 60), (22, 90, 10, 70)]

    def test_a_big_temperature_drop_is_cold_not_ok(self):
        for c in self.WINTER:
            assert HR.dew_gap_c(*c) > HR.RELIEF_DEW_GAP_C, '이슬점만 보면 열어도 된다'
            assert HR.relief_verdict(*c) == HR.COLD, c
            assert HR.relief_allowed(*c) is False

    def test_heat_demand_blocks_even_a_modest_drop(self):
        c = (20, 95, 16, 50)            # 4 °C 차 — 난방 요구가 없으면 OK
        assert HR.relief_verdict(*c) == HR.OK
        assert HR.relief_verdict(*c, heat_demand=True) == HR.COLD

    def test_heat_demand_does_not_block_warmer_outdoor_air(self):
        assert HR.relief_verdict(14.8, 94, 18.3, 49, heat_demand=True) == HR.OK

    def test_the_drop_threshold_has_hysteresis(self):
        edge = HR.MAX_COLD_DELTA_C + 1.0
        c = (20.0, 95, 20.0 - edge, 50)
        assert HR.relief_verdict(*c, was_open=False) == HR.COLD
        assert HR.relief_verdict(*c, was_open=True) == HR.OK

    def test_the_coordinator_closes_the_vent_with_its_own_reason(self):
        cmds, st = _cycle(C.CoordinatorState(), (20, 95, 0, 80), prev=25.0)
        assert cmds['v'].reason == REASON_HUMID_COLD
        assert cmds['v'].control_value() < 25.0

    def test_a_heat_demand_in_the_situation_blocks_relief(self):
        """난방 요구가 서 있으면 실외가 조금만 차도 닫는다. 요구가 없으면 열어도 된다."""
        # 목표 온도 22 ± 1 °C — 26 °C 는 목표 위(식혀도 된다), 17 °C 는 난방 요구
        ok_rec = (26.0, 99, 19.0, 40)
        cmds, _ = _cycle(C.CoordinatorState(), ok_rec, prev=20.0)
        assert cmds['v'].reason != REASON_HUMID_COLD
        cold_rec = (17.0, 94, 14.0, 40)
        cmds, _ = _cycle(C.CoordinatorState(), cold_rec, prev=20.0)
        assert cmds['v'].reason == REASON_HUMID_COLD
        # 하드 저온(`_force_heat`)도 같다
        cmds, _ = _cycle(C.CoordinatorState(), ok_rec, prev=20.0,
                         extra={'internal': {'_force_heat': True}})
        assert cmds['v'].reason == REASON_HUMID_COLD


class TestNearOrBelowTarget:
    """목표 온도 근처 이하에서는 이슬점 기준 환기를 빼고 온도가 이긴다(사용자 제안)."""

    def test_at_the_target_a_colder_outdoor_air_is_not_used(self):
        # 목표 22 ± 1 °C — 22 °C(목표)에서 실외가 3 °C 더 차다: 이슬점은 훨씬 낮아도 열지 않는다
        cmds, _ = _cycle(C.CoordinatorState(), (22.0, 97, 19.0, 40), prev=20.0)
        assert cmds['v'].reason == REASON_HUMID_COLD

    def test_within_tolerance_above_target_still_counts_as_near(self):
        cmds, _ = _cycle(C.CoordinatorState(), (22.9, 97, 19.0, 40), prev=20.0)
        assert cmds['v'].reason == REASON_HUMID_COLD

    def test_clearly_above_target_the_dewpoint_rule_applies(self):
        """목표보다 확실히 더우면(허용오차 밖) 식히는 것이 온도에도 이득이다."""
        cmds, _ = _cycle(C.CoordinatorState(), (26.0, 99, 19.0, 40), prev=20.0)
        assert cmds['v'].reason != REASON_HUMID_COLD

    def test_a_warmer_outdoor_air_is_not_blocked_below_target(self):
        """밤의 3포장 — 실내가 목표보다 훨씬 낮아도 외기가 더 따뜻하면 열어도 온도가 오른다."""
        state = C.CoordinatorState()
        for i in range(10):
            cmds, state = _cycle(state, REC['g_0300'], prev=None if i else 25.0)
        assert cmds['v'].reason != REASON_HUMID_COLD


def test_morning_drying_is_not_masked_by_the_average():
    """쿠마모토 10:11 — 외기가 빠르게 건조해지는 중에도 평균이 환기 판단을 40분 늦추지 않는다."""
    from aot.utils.psychro import svp
    sm = OutdoorSmoother()
    for i, (T, RH) in enumerate([(23.6, 82)] * 6 + [(25.2, 72)] * 4):   # 10분 간격 10건
        out = sm.smooth({'T_ext': T, 'RH_ext': RH}, i * 600.0)
    vpd_in = 0.48
    gap = svp(out['T_ext']) * (1 - out['RH_ext'] / 100.0) - vpd_in
    assert gap >= 0.25, '평균이 따라와 무익 문턱(0.25 kPa)을 넘는다'
