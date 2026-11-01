# coding=utf-8
"""의심 액추에이터 — 판정(레지스트리) · 제외(코디네이터) · 사이클 배선.

세 층이다.

  1. `actuator_feedback` — 전송 실패 연속 / 반응 없음 후보로 의심이 되고, 30분 뒤 자동으로 풀린다.
     평생 누적(`is_suspicious`)은 제어를 건드리지 않는다. 같은 도메인의 연쇄 제외는 쿨다운이 막는다.
  2. `coordinator` — 의심 장치는 **제자리**(근거 42)이고 부하 분담 장부에 아무것도 올리지 않아
     나머지가 몫을 이어받는다. '반응 없음' 후보는 세게·뚜렷·오래·혼자 한 일일 때만 선다.
  3. `CycleMixin` — 바뀔 때만 말하고, 의심 장치는 전송하지 않으며, MPC/greybox 는 레거시로 물러난다.
"""
import logging
import types as _types

import pytest

import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cycle_mod
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
from aot.functions.utils.env_control import actuator_feedback as FB
from aot.functions.utils.env_control import coordinator as C
from aot.functions.utils.env_control.log_channels import (
    REASON_ACTUATOR_SUSPECT, REASON_PRIMARY, reason_code)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 레지스트리
# ─────────────────────────────────────────────────────────────────────────────

def _fail_run(reg, aid, n, t0=1000.0, step=60.0):
    for i in range(n):
        reg.record_dispatch(aid, 50.0, success=False, ts=t0 + i * step)
    return t0 + (n - 1) * step


class TestDispatchPath:
    def test_repeated_failures_make_it_suspected(self):
        reg = FB.ActuatorFeedbackRegistry()
        _fail_run(reg, 'a', FB.SUSPECT_FAIL_CYCLES)         # 60초 간격 5회 = 4분
        assert reg.suspected_ids() == ['a']
        assert reg.suspect_reason('a') == FB.REASON_DISPATCH

    def test_four_failures_are_not_enough(self):
        reg = FB.ActuatorFeedbackRegistry()
        _fail_run(reg, 'a', FB.SUSPECT_FAIL_CYCLES - 1)
        assert reg.suspected_ids() == []

    def test_a_burst_inside_the_span_is_a_blip_not_a_fault(self):
        """5번이 몇 초 안에 몰렸다면 일시 두절이다 — 시간이 지나야 의심."""
        reg = FB.ActuatorFeedbackRegistry()
        _fail_run(reg, 'a', 8, step=5.0)                    # 35초에 8번
        assert reg.suspected_ids() == []
        reg.record_dispatch('a', 50.0, False, ts=1000.0 + FB.SUSPECT_FAIL_SPAN_S + 1)
        assert reg.suspected_ids() == ['a']

    def test_one_success_restarts_the_count(self):
        reg = FB.ActuatorFeedbackRegistry()
        _fail_run(reg, 'a', 4)
        reg.record_dispatch('a', 50.0, True, ts=1300.0)
        _fail_run(reg, 'a', 4, t0=1400.0)
        assert reg.suspected_ids() == []

    def test_failures_scattered_over_weeks_never_suspect_it(self):
        """누적 `mismatch_count > 5` 로는 의심이 된다(학습 가중치용) — 제어는 그걸 읽지 않는다."""
        reg = FB.ActuatorFeedbackRegistry()
        t = 1000.0
        for _ in range(8):
            reg.record_dispatch('a', 50.0, False, ts=t)
            reg.record_dispatch('a', 50.0, True, ts=t + 60)
            t += 86400.0
        assert reg.get('a').is_suspicious is True
        assert reg.suspected_ids() == []

    def test_state_dict_exposes_the_suspicion(self):
        reg = FB.ActuatorFeedbackRegistry()
        _fail_run(reg, 'a', FB.SUSPECT_FAIL_CYCLES)
        d = reg.state_dict()['a']
        assert d['suspected'] is True and d['suspect_reason'] == 'dispatch'
        assert 'actual_pct' in d


class TestRecovery:
    def _suspected(self):
        reg = FB.ActuatorFeedbackRegistry()
        t = _fail_run(reg, 'a', FB.SUSPECT_FAIL_CYCLES)
        return reg, t

    def test_it_is_held_until_the_hold_time_then_released(self):
        reg, t = self._suspected()
        assert reg.refresh(t + FB.SUSPECT_HOLD_S - 1) == []
        assert reg.suspected_ids() == ['a']
        assert reg.refresh(t + FB.SUSPECT_HOLD_S + 1) == ['a']
        assert reg.suspected_ids() == []

    def test_released_on_probation_two_failures_suspect_it_again(self):
        reg, t = self._suspected()
        t2 = t + FB.SUSPECT_HOLD_S + 1
        reg.refresh(t2)
        reg.record_dispatch('a', 50.0, False, ts=t2 + 60)
        assert reg.suspected_ids() == []
        reg.record_dispatch('a', 50.0, False, ts=t2 + 120)
        assert reg.suspected_ids() == ['a']

    def test_one_success_ends_probation(self):
        reg, t = self._suspected()
        t2 = t + FB.SUSPECT_HOLD_S + 1
        reg.refresh(t2)
        reg.record_dispatch('a', 50.0, True, ts=t2 + 60)
        assert reg.get('a').probation is False
        _fail_run(reg, 'a', 2, t0=t2 + 120)               # 이제 다시 5번이 필요하다
        assert reg.suspected_ids() == []

    def test_failures_before_the_hold_do_not_carry_into_probation(self):
        reg, t = self._suspected()
        reg.refresh(t + FB.SUSPECT_HOLD_S + 1)
        assert reg.get('a').fail_streak == 0


class TestNoEffectPath:
    def test_it_suspects_through_record_sensor_mismatch(self):
        reg = FB.ActuatorFeedbackRegistry()
        before = reg.get('w').mismatch_count
        assert reg.record_no_effect('w', 'vent', ts=5000.0) is True
        fb = reg.get('w')
        assert fb.suspected and fb.suspect_reason == FB.REASON_NO_EFFECT
        assert fb.mismatch_count == before + 1 and fb.trust_score < 1.0

    def test_repeat_calls_while_suspected_are_ignored(self):
        reg = FB.ActuatorFeedbackRegistry()
        reg.record_no_effect('w', 'vent', ts=5000.0)
        trust = reg.trust_score('w')
        assert reg.record_no_effect('w', 'vent', ts=5060.0) is False
        assert reg.trust_score('w') == trust                # 신뢰도를 사이클마다 깎지 않는다

    def test_a_second_actuator_of_the_same_domain_waits_for_the_cooldown(self):
        """열린 루프 시설에서 창이 차례로 전부 제외되는 연쇄를 막는다."""
        reg = FB.ActuatorFeedbackRegistry()
        assert reg.record_no_effect('w1', 'vent', ts=5000.0)
        assert reg.record_no_effect('w2', 'vent', ts=5000.0 + 3600.0) is False
        assert reg.suspected_ids() == ['w1']
        assert reg.record_no_effect(
            'w2', 'vent', ts=5000.0 + FB.NOFX_DOMAIN_COOLDOWN_S + 1) is True

    def test_other_domains_are_independent(self):
        reg = FB.ActuatorFeedbackRegistry()
        assert reg.record_no_effect('w1', 'vent', ts=5000.0)
        assert reg.record_no_effect('h1', 'hvac', ts=5001.0)

    def test_the_same_actuator_is_not_re_flagged_inside_the_cooldown(self):
        reg = FB.ActuatorFeedbackRegistry()
        reg.record_no_effect('w1', 'vent', ts=5000.0)
        reg.refresh(5000.0 + FB.SUSPECT_HOLD_S + 1)         # 풀림
        assert reg.record_no_effect('w1', 'vent', ts=5000.0 + 7200.0) is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. 코디네이터
# ─────────────────────────────────────────────────────────────────────────────

def _fn(direction, g):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, g * 6.0 * (cmd_pct / 100.0))
    return fn


def _vent(aid, g=0.3, cost=5.0, kind='opening'):
    return ActuatorProfile(
        actuator_id=aid, kind=kind, safe_default=0.0,
        effect_model={'temperature': _fn('↑', g)}, cost_fn=lambda e, p, _c=cost: _c,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2})


class _Sit:
    """온도가 목표보다 4 °C 낮다 → '↑' 효과 장치가 켜지고 싶다."""
    def __init__(self, dev=-4.0, **ctx):
        self.target = {'temperature': TargetVar(value=24.0, tolerance=1.0,
                                                priority=1.0, unit='C')}
        self.deviation_native = {'temperature': dev}
        self.context = {'cycle_sec': 60.0}
        self.context.update(ctx)


def _state(**prev):
    st = C.CoordinatorState()
    st.prev_commands = dict(prev)
    st.integral = dict(prev)
    return st


class TestHoldAndLoadSharing:
    def test_suspected_actuator_is_held_in_place_with_its_own_reason(self):
        profiles = [_vent('a'), _vent('b', cost=9.0)]
        cmds, st = C.coordinate(_Sit(suspected_ids={'a'}), profiles,
                                _state(a=60.0, b=0.0), unique_id='t')
        assert cmds['a'].reason == REASON_ACTUATOR_SUSPECT
        assert cmds['a'].control_value() == pytest.approx(60.0)
        assert st.prev_commands['a'] == pytest.approx(60.0)
        assert st.integral['a'] == pytest.approx(60.0)       # 적분도 그대로

    def test_it_is_not_moved_by_the_transfer_ratio_or_slew(self):
        a = _vent('a')
        a.cmd_scale = 0.2                                     # 풍향 가중치 같은 전달 비율
        a.cmd_constraints = CmdConstraints(slew_per_cycle=5.0, min_on_pct=30.0)
        cmds, _ = C.coordinate(_Sit(suspected_ids={'a'}), [a],
                               _state(a=10.0), unique_id='t')
        assert cmds['a'].control_value() == pytest.approx(10.0)

    def test_the_rest_of_the_domain_picks_up_the_demand(self):
        """같은 사이클 같은 편차 — a 가 일하고 있으면 b 는 나머지만, a 를 빼면 b 가 전부 맡는다."""
        def b_command(suspected):
            profiles = [_vent('a', g=0.15, cost=5.0), _vent('b', g=0.15, cost=9.0)]
            sit = _Sit(suspected_ids=set(suspected))
            cmds, _ = C.coordinate(sit, profiles, _state(a=80.0, b=0.0),
                                   unique_id='t')
            return cmds['b'].control_value()
        assert b_command({'a'}) > b_command(set()) + 1.0

    def test_it_adds_nothing_to_the_ledger(self):
        """장부에 올린 몫이 없으니 같은 비용 묶음의 다른 장치도 그만큼 더 한다."""
        def b_command(suspected):
            profiles = [_vent('a', g=0.15), _vent('b', g=0.15, cost=9.0)]
            cmds, _ = C.coordinate(_Sit(suspected_ids=set(suspected)), profiles,
                                   _state(a=100.0, b=0.0), unique_id='t')
            return cmds['b'].control_value()
        assert b_command({'a'}) > b_command(set())

    def test_unknown_ids_are_ignored(self):
        cmds, _ = C.coordinate(_Sit(suspected_ids={'ghost'}), [_vent('a')],
                               _state(a=20.0), unique_id='t')
        assert cmds['a'].reason != REASON_ACTUATOR_SUSPECT

    def test_no_suspects_changes_nothing(self):
        base, _ = C.coordinate(_Sit(), [_vent('a')], _state(a=20.0), unique_id='t')
        with_key, _ = C.coordinate(_Sit(suspected_ids=set()), [_vent('a')],
                                   _state(a=20.0), unique_id='t')
        assert base['a'].control_value() == with_key['a'].control_value()

    def test_reason_code_is_the_dedicated_one(self):
        assert REASON_ACTUATOR_SUSPECT == 42
        assert reason_code(REASON_ACTUATOR_SUSPECT) == 42.0


def _run_cycles(profiles, cycles, prev, *, dev=-4.0, ctx=None, hold_prev=None,
                improve=None):
    """같은 편차로 사이클을 반복한다. `hold_prev` 로 직전 명령을 고정(= 반응 없는 열린 루프 + 세게)."""
    st = _state(**prev)
    for i in range(cycles):
        d = dev if improve is None else dev * improve(i)
        if hold_prev:
            st.prev_commands.update(hold_prev)
        _cmds, st = C.coordinate(_Sit(dev=d, **(ctx or {})), profiles, st,
                                 unique_id='t')
    return st


_TWO_HOURS_CYCLES = int(C.NOFX_AFTER_S / 60.0) + 2


class TestNoEffectCandidates:
    def test_sole_strong_vent_with_no_response_is_flagged_after_two_hours(self):
        # b 는 효과가 0 이라(g=0) 환기 효과를 전혀 내지 못한다 — a 가 혼자 한 일이다.
        profiles = [_vent('a', g=0.3), _vent('b', g=0.0, cost=9.0)]
        st = _run_cycles(profiles, _TWO_HOURS_CYCLES, {'a': 100.0, 'b': 0.0})
        assert st.noeffect_ids == {'a'}

    def test_not_before_two_hours(self):
        profiles = [_vent('a', g=0.3), _vent('b', g=0.0, cost=9.0)]
        st = _run_cycles(profiles, int(C.NOFX_AFTER_S / 60.0) - 5,
                         {'a': 100.0, 'b': 0.0})
        assert st.noeffect_ids == set()

    def test_several_strong_vents_are_a_common_cause_not_a_fault(self):
        """창이 함께 세게 열렸는데 편차가 안 줄면 열린 루프·센서·용량 — 창 하나의 고장이 아니다."""
        # d 는 효과가 없는 창이라 '하나는 남긴다' 규칙(⑥)이 아니라 몫 규칙(⑤)이 가르는 경우다.
        profiles = [_vent('a', g=0.3), _vent('b', g=0.3), _vent('c', g=0.3),
                    _vent('d', g=0.0, cost=9.0)]
        st = _run_cycles(profiles, _TWO_HOURS_CYCLES * 2,
                         {'a': 100.0, 'b': 100.0, 'c': 100.0, 'd': 0.0})
        assert max(st.nofx_s.values()) >= C.NOFX_AFTER_S       # 시간은 찼는데도 후보가 아니다
        assert st.noeffect_ids == set()

    def test_the_share_rule_is_what_blocks_it_not_just_the_last_vent_rule(self, monkeypatch):
        monkeypatch.setattr(C, 'NOFX_SOLE_SHARE', 0.0)
        profiles = [_vent('a', g=0.3), _vent('b', g=0.3), _vent('c', g=0.3),
                    _vent('d', g=0.0, cost=9.0)]
        st = _run_cycles(profiles, _TWO_HOURS_CYCLES * 2,
                         {'a': 100.0, 'b': 100.0, 'c': 100.0, 'd': 0.0})
        assert st.noeffect_ids == {'a', 'b', 'c'}              # 규칙을 풀면 셋 다 서 버린다

    def test_the_last_vent_is_never_a_candidate(self):
        st = _run_cycles([_vent('a', g=0.3)], _TWO_HOURS_CYCLES, {'a': 100.0})
        assert st.noeffect_ids == set()

    def test_a_response_resets_the_clock(self):
        profiles = [_vent('a', g=0.3), _vent('b', g=0.0, cost=9.0)]
        # 50분마다 편차가 15 % 좁혀진다 — 반응이 있는 창이다.
        st = _run_cycles(profiles, _TWO_HOURS_CYCLES * 2, {'a': 100.0, 'b': 0.0},
                         improve=lambda i: 0.85 ** (i // 50))
        assert st.noeffect_ids == set()

    def test_a_command_below_the_strong_threshold_does_not_count(self):
        profiles = [_vent('a', g=0.3), _vent('b', g=0.0, cost=9.0)]
        st = _run_cycles(profiles, _TWO_HOURS_CYCLES, {'a': 100.0, 'b': 0.0},
                         hold_prev={'a': C.NOFX_MIN_CMD_PCT - 10.0})
        assert st.noeffect_ids == set() and 'a' not in st.nofx_s

    def test_a_weak_effect_vent_is_not_measured_by_this_path(self):
        """효과가 작은 창은 STALL(열어도 소용없음)의 몫이다 — 여기서는 후보가 못 된다."""
        profiles = [_vent('a', g=0.03), _vent('b', g=0.0, cost=9.0)]
        st = _run_cycles(profiles, _TWO_HOURS_CYCLES, {'a': 100.0, 'b': 0.0})
        assert st.noeffect_ids == set() and 'a' not in st.nofx_s

    def test_unknown_outdoor_never_counts(self):
        profiles = [_vent('a', g=0.3), _vent('b', g=0.0, cost=9.0)]
        st = _run_cycles(profiles, _TWO_HOURS_CYCLES, {'a': 100.0, 'b': 0.0},
                         ctx={'external': {'_ext_synthetic': True}})
        assert st.noeffect_ids == set() and 'a' not in st.nofx_s

    def test_non_ventilation_kinds_are_not_tracked(self):
        h = _vent('h', g=0.3, kind='heater')
        st = _run_cycles([h, _vent('b', g=0.0, cost=9.0)], _TWO_HOURS_CYCLES,
                         {'h': 100.0, 'b': 0.0})
        assert st.noeffect_ids == set() and 'h' not in st.nofx_s

    def test_a_suspected_vent_is_dropped_from_the_tracker(self):
        profiles = [_vent('a', g=0.3), _vent('b', g=0.0, cost=9.0)]
        st = _run_cycles(profiles, _TWO_HOURS_CYCLES, {'a': 100.0, 'b': 0.0},
                         ctx={'suspected_ids': {'a'}})
        assert st.noeffect_ids == set() and 'a' not in st.nofx_s

    def test_state_fields_start_empty(self):
        st = C.CoordinatorState()
        assert st.nofx_s == {} and st.nofx_ref == {} and st.noeffect_ids == set()


class TestStallStillWorksAfterTheRefactor:
    def test_weak_vent_still_freezes_at_45_minutes(self):
        weak = _vent('v', g=0.04)
        st = _state(v=15.0)
        reason = None
        for _ in range(70):
            cmds, st = C.coordinate(_Sit(), [weak], st, unique_id='t')
            reason = cmds['v'].reason
        assert reason == C.REASON_NO_RESPONSE


# ─────────────────────────────────────────────────────────────────────────────
# 3. 사이클 배선
# ─────────────────────────────────────────────────────────────────────────────

def _host(**opts):
    c = CycleMixin.__new__(CycleMixin)
    c._profiles = [_vent('a'), _vent('b', cost=9.0)]
    c.unique_id = 'fn-suspect'
    c.logger = logging.getLogger('test_actuator_suspect')
    c.status = []
    c._status_log = lambda level, msg, *a: c.status.append((level, msg % a if a else msg))
    for k, v in opts.items():
        setattr(c, k, v)
    return c


class TestCycleWiring:
    def test_a_new_suspect_is_announced_once_and_a_release_once(self):
        c = _host()
        reg = c._feedback_registry
        assert c._update_suspects(1000.0) == set()
        _fail_run(reg, 'a', FB.SUSPECT_FAIL_CYCLES, t0=1000.0)
        for _ in range(4):
            assert c._update_suspects(1300.0) == {'a'}
        assert [lvl for lvl, _ in c.status] == [logging.WARNING]
        assert 'a(opening' in c.status[0][1] or 'opening' in c.status[0][1]
        assert c._update_suspects(1300.0 + FB.SUSPECT_HOLD_S + 5) == set()
        assert [lvl for lvl, _ in c.status] == [logging.WARNING, logging.INFO]

    def test_no_effect_candidates_reach_the_registry_per_domain(self):
        c = _host()
        c._note_no_effect({'a'})
        assert c._feedback_registry.suspected_ids() == ['a']
        assert c._feedback_registry.suspect_reason('a') == FB.REASON_NO_EFFECT
        c._note_no_effect({'b'})                      # 같은 도메인 쿨다운
        assert c._feedback_registry.suspected_ids() == ['a']

    def test_empty_or_none_candidates_do_nothing(self):
        c = _host()
        c._note_no_effect(None)
        c._note_no_effect(set())
        assert c._feedback_registry.suspected_ids() == []

    def test_cmd_reason_reads_dicts_and_objects(self):
        assert CycleMixin._cmd_reason({'value': 1.0, 'reason': 42}) == 42
        assert CycleMixin._cmd_reason(
            _types.SimpleNamespace(value=1.0, reason=7)) == 7

    def test_run_cycle_dispatches_only_non_suspect_commands(self):
        """소스 확인 — 전송에서 근거 42 를 빼고, 피드백 기록도 보낸 것만 센다."""
        import inspect
        src = inspect.getsource(CycleMixin._run_cycle)
        assert 'REASON_ACTUATOR_SUSPECT' in src
        assert 'self._dispatch(dispatch_cmds' in src
        assert 'self._record_dispatch_feedback(dispatch_cmds, failed)' in src
        feedback = inspect.getsource(CycleMixin._record_dispatch_feedback)
        assert 'for aid, cmd in dispatch_cmds.items()' in feedback
        # 의심 판정은 제어 앞(ctx)과 뒤(후보 전달) 양쪽에 있다.
        assert src.index("_update_suspects(") < src.index('_run_control(')
        assert src.index('_note_no_effect(') > src.index('_run_control(')


class TestEngineSeam:
    def _mpc_host(self, suspected):
        from aot.functions.utils.env_control.greybox.mpc import MPCConfig
        from aot.functions.utils.env_control.greybox.params import GreyboxParams
        c = _host()
        c._coord_state = C.CoordinatorState()
        c._greybox_active = True
        c._mpc_enabled = True
        c._greybox_shadow_inst = _types.SimpleNamespace(params=GreyboxParams())
        c._mpc_config = MPCConfig(horizon=8)
        c._actuator_idx = {}
        calls = []
        c._run_mpc = lambda *a, **k: calls.append(1)
        sit = _Sit(suspected_ids=set(suspected))
        sit.context.update({'T_int': 22.0, 'RH_int': 60.0})
        return c, sit, calls

    def test_suspect_sends_the_cycle_to_the_legacy_controller(self):
        c, sit, calls = self._mpc_host({'a'})
        c._run_control(sit, '')
        assert not calls and c._last_control_engine == 'legacy'
        assert c._last_control_fallback == 'actuator_suspect'

    def test_without_suspects_mpc_runs(self):
        c, sit, calls = self._mpc_host(set())
        c._run_control(sit, '')
        assert calls and c._last_control_fallback is None

    def test_fallback_message_names_the_reason(self, caplog):
        c, sit, _ = self._mpc_host({'a'})
        with caplog.at_level(logging.WARNING, logger='test_actuator_suspect'):
            for _ in range(3):
                c._run_control(sit, '')
        msgs = [r.getMessage() for r in caplog.records if 'MPC/greybox' in r.getMessage()]
        assert len(msgs) == 1 and '의심 액추에이터' in msgs[0]


class TestChannelAndLabels:
    def test_channel_93_does_not_collide_with_known_ones(self):
        from aot.functions.utils.env_control import log_channels as LC
        taken = {LC.CH_SAFETY_GATE, LC.CH_DISPATCH_FAIL, LC.CH_RUNTIME_STATE_FAIL,
                 LC.CH_ACTUATOR_MISMATCH, LC.CH_CLEAN_FOR_LEARNING,
                 LC.CH_HEAT_PROTECT_TIER, LC.CH_HEAT_PROTECT_FLAGS,
                 LC.CH_WATER_SUPPLY, LC.CH_GREYBOX_KPI_PASSED}
        assert LC.CH_ACTUATOR_SUSPECT == 93 and LC.CH_ACTUATOR_SUSPECT not in taken
        # 센서 상태 브랜치가 쓰는 80~91 과도 겹치지 않는다.
        assert not 80 <= LC.CH_ACTUATOR_SUSPECT <= 91
        assert not 80 <= LC.CH_WATER_SUPPLY <= 91
