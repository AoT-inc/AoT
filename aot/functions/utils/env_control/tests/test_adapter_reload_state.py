# coding=utf-8
"""프로필 재적재가 분무 최소 쉼을 지우지 않는다 (2026-10-13).

## 배경

`_reload_profiles` 는 10분(`_PROFILE_RELOAD_INTERVAL_S`)마다, 그리고 `cmd_reload` 때 어댑터 맵을
새로 짓는다(`build_adapter_map`). 습윤형 분무기의 `PulsedDoseAdapter` 는 "1회 분무 뒤 min_off_sec
동안은 무슨 명령이 와도 끈다" 를 자기 시계(`_blocked_until`)로 지키는데, 새 어댑터의 시계는 0 이라
**방금 뿌린 분무기가 재적재 직후 사이클에 바로 다시 뿌렸다** — 사용자가 정한 최소 쉼이 10분에 한 번
풀린다(10/12 최종 회귀 보고의 알려진 과제).

## 고친 모양

설정은 새 어댑터의 것, "마지막 펄스가 언제 끝났나" 만 옛 어댑터에서 넘긴다
(`carry_adapter_state` → `PulsedDoseAdapter.adopt_runtime_state`). 같은 장치·같은 종류일 때만.
"""
import inspect
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator_impl import _helpers_mixin
from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin import (
    ProfileLoaderMixin,
)
from aot.functions.utils.env_control import dispatch_adapters as da
from aot.functions.utils.env_control import pulse_fog as PF
from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints

T0 = 7_000_000.0
CAP = (PF.PF_ON_SEC, PF.PF_MIN_OFF_SEC)


@pytest.fixture
def clock(monkeypatch):
    t = {'now': T0}
    monkeypatch.setattr('time.time', lambda: t['now'])
    return t


class _Control:
    def __init__(self):
        self.calls = []

    def output_on(self, aid, **k):
        self.calls.append(('on', aid, k.get('amount')))
        return (0, 'OK')

    def output_off(self, aid, **k):
        self.calls.append(('off', aid, None))
        return (0, 'OK')

    def kinds(self):
        return [c[0] for c in self.calls]


def _pulsed(max_on=30.0, min_off=180.0, inner=None):
    return da.PulsedDoseAdapter(inner or da.TimeProportionalAdapter(),
                                max_on_sec=max_on, min_off_sec=min_off)


def _fogger(aid='fog', max_on=30.0, min_off=180.0):
    return ActuatorProfile(
        actuator_id=aid, kind='fogger', capabilities=['humidify'],
        cost_fn=lambda env, pct: 5.0, response_sec=60.0, safe_default=0.0,
        capacity_meta={'nozzle': {'wetting': True}},
        cmd_constraints=CmdConstraints(max_on_sec=max_on, min_off_sec=min_off))


# ─────────────────────────────────────────────────────────────────────────────
# 1. 어댑터 — 이어받는 것과 안 이어받는 것
# ─────────────────────────────────────────────────────────────────────────────

class TestAdopt:

    def test_same_settings_keep_the_same_rest(self, clock):
        old = _pulsed()
        old.send(_Control(), 'fog', 100.0, 0, 60.0)
        assert old.blocked_until == pytest.approx(T0 + 30.0 + 180.0)
        new = _pulsed()
        assert da.carry_adapter_state({'fog': old}, {'fog': new}) == ['fog']
        assert new.blocked_until == pytest.approx(old.blocked_until)

    def test_the_rest_holds_after_the_swap(self, clock):
        old, ctl = _pulsed(), _Control()
        old.send(ctl, 'fog', 100.0, 0, 60.0)
        new = _pulsed()
        da.carry_adapter_state({'fog': old}, {'fog': new})
        for step in (60.0, 60.0, 60.0):                   # 60·120·180 초 — 210 초 전
            clock['now'] += step
            ctl.calls.clear()
            new.send(ctl, 'fog', 100.0, 0, 60.0)
            assert ctl.kinds() == ['off'], clock['now'] - T0
        clock['now'] += 60.0                               # 240 초 — 쉼이 끝났다
        ctl.calls.clear()
        new.send(ctl, 'fog', 100.0, 0, 60.0)
        assert ctl.kinds() == ['on']

    def test_a_longer_new_rest_wins(self, clock):
        old = _pulsed(min_off=180.0)
        old.send(_Control(), 'fog', 100.0, 0, 60.0)
        new = _pulsed(min_off=600.0)
        da.carry_adapter_state({'fog': old}, {'fog': new})
        assert new.blocked_until == pytest.approx(T0 + 30.0 + 600.0)

    def test_a_shorter_new_rest_also_wins(self, clock):
        """줄인 최소 쉼은 사용자의 새 판단이다 — 옛 값으로 한 번 더 붙잡지 않는다."""
        old = _pulsed(min_off=600.0)
        old.send(_Control(), 'fog', 100.0, 0, 60.0)
        new = _pulsed(min_off=120.0)
        da.carry_adapter_state({'fog': old}, {'fog': new})
        assert new.blocked_until == pytest.approx(T0 + 30.0 + 120.0)

    def test_the_pulse_fog_floor_is_not_shortened_by_the_new_setting(self, clock):
        """근거 57 펄스가 얹은 15분은 설정이 아니라 그 펄스의 성질이다."""
        old = _pulsed(min_off=180.0)
        old.send(_Control(), 'fog', 100.0, 0, 60.0, pulse_cap=CAP)
        assert old.blocked_until == pytest.approx(T0 + 10.0 + 900.0)
        new = _pulsed(min_off=60.0)
        da.carry_adapter_state({'fog': old}, {'fog': new})
        assert new.blocked_until == pytest.approx(T0 + 10.0 + 900.0)

    def test_an_old_adapter_without_the_end_time_keeps_its_blocked_time(self, clock):
        old = _pulsed()
        old._blocked_until = T0 + 500.0                    # 옛 판에서 만든 어댑터
        old._last_pulse_end = None
        new = _pulsed(min_off=60.0)
        da.carry_adapter_state({'fog': old}, {'fog': new})
        assert new.blocked_until == pytest.approx(T0 + 500.0)

    def test_a_never_pulsed_adapter_carries_nothing_harmful(self, clock):
        new = _pulsed()
        da.carry_adapter_state({'fog': _pulsed()}, {'fog': new})
        assert new.blocked_until == 0.0

    def test_a_changed_inner_device_is_not_carried(self, clock):
        old = _pulsed()
        old.send(_Control(), 'fog', 100.0, 0, 60.0)
        new = da.PulsedDoseAdapter(da.VolumetricAdapter(6.0), 30.0, 180.0, flow_lpm=6.0)
        assert da.carry_adapter_state({'fog': old}, {'fog': new}) == []
        assert new.blocked_until == 0.0

    def test_a_changed_adapter_kind_is_not_carried(self, clock):
        old = _pulsed()
        old.send(_Control(), 'fog', 100.0, 0, 60.0)
        new = da.TimeProportionalAdapter()
        assert da.carry_adapter_state({'fog': old}, {'fog': new}) == []

    def test_a_removed_device_is_simply_gone(self, clock):
        old = _pulsed()
        old.send(_Control(), 'fog', 100.0, 0, 60.0)
        assert da.carry_adapter_state({'fog': old}, {'other': _pulsed()}) == []

    def test_stateless_adapters_carry_nothing(self):
        assert da.carry_adapter_state(
            {'w': da.PairedAdapter(), 'r': da.TimeProportionalAdapter()},
            {'w': da.PairedAdapter(), 'r': da.TimeProportionalAdapter()}) == []

    def test_no_previous_map(self):
        assert da.carry_adapter_state(None, {'fog': _pulsed()}) == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. 코디네이터 — 재적재를 끼운 디스패치
# ─────────────────────────────────────────────────────────────────────────────

class _Host(_helpers_mixin.HelpersMixin, ProfileLoaderMixin):
    _DISPATCH_STAGGER_SEC = 0.0


def _host(min_off=180.0):
    h = _Host()
    h.logger = MagicMock()
    h.unique_id = 'x'
    h.control = _Control()
    h._channel_map = {'fog': 0}
    h._by_id = {'fog': _fogger(min_off=min_off)}
    return h


def _reload(h, monkeypatch, min_off=180.0, max_on=30.0):
    """`_reload_profiles` 의 어댑터 단계만 — 새 설정으로 새 어댑터를 짓는다."""
    h._by_id = {'fog': _fogger(max_on=max_on, min_off=min_off)}
    monkeypatch.setattr(da, 'build_adapter_map',
                        lambda by_id: {'fog': _pulsed(max_on=max_on, min_off=min_off)})
    h._rebuild_adapter_map(h._by_id)


class TestReloadInTheLoop:

    CMD = {'fog': {'value': 100.0, 'reason': 1}}

    def test_reload_right_after_a_spray_does_not_spray_again(self, clock, monkeypatch):
        h = _host()
        _reload(h, monkeypatch)                            # 기동 때의 첫 적재
        h._dispatch_commands(self.CMD, 60.0)
        assert h.control.kinds() == ['on']
        sent = []
        for i in range(1, 5):                              # 60·120·180·240 초
            clock['now'] += 60.0
            _reload(h, monkeypatch)                        # 매 사이클 재적재(최악)
            h.control.calls.clear()
            h._dispatch_commands(self.CMD, 60.0)
            sent.append(h.control.kinds()[0])
        assert sent == ['off', 'off', 'off', 'on']         # 쉼 210 초 — 240 초에 다시

    def test_a_shortened_rest_takes_effect_at_the_reload(self, clock, monkeypatch):
        h = _host(min_off=600.0)
        _reload(h, monkeypatch, min_off=600.0)
        h._dispatch_commands(self.CMD, 60.0)
        clock['now'] += 120.0
        _reload(h, monkeypatch, min_off=60.0)              # 사용자가 쉼을 1분으로 줄였다
        h.control.calls.clear()
        h._dispatch_commands(self.CMD, 60.0)
        assert h.control.kinds() == ['on']                 # 30 + 60 = 90 초 < 120 초

    def test_pulse_fog_rest_survives_a_reload(self, clock, monkeypatch):
        """근거 57 의 15분은 코디네이터 시계와 어댑터 쉼 **둘 다** 로 지켜진다."""
        h = _host()
        _reload(h, monkeypatch)
        pf = {'fog': {'value': 100.0, 'reason': PF.PULSE_FOG_REASON}}
        h._dispatch_commands(pf, 60.0)
        assert h.control.calls[0] == ('on', 'fog', 10.0)
        # 근거 57 이 풀린 뒤 평소 가습이 와도 15분 쉼은 이어진다 — 재적재를 지나서도.
        for step in (300.0, 300.0, 299.0):
            clock['now'] += step
            _reload(h, monkeypatch)
            h.control.calls.clear()
            h._dispatch_commands(self.CMD, 60.0)
            assert h.control.kinds() == ['off'], clock['now'] - T0
        clock['now'] += 20.0                               # 919 초
        _reload(h, monkeypatch)
        h.control.calls.clear()
        h._dispatch_commands(self.CMD, 60.0)
        assert h.control.kinds() == ['on']

    def test_build_failure_still_falls_back_to_an_empty_map(self, monkeypatch):
        h = _host()

        def boom(by_id):
            raise RuntimeError('x')
        monkeypatch.setattr(da, 'build_adapter_map', boom)
        h._rebuild_adapter_map(h._by_id)
        assert h._adapter_by_id == {}


def test_reload_profiles_goes_through_the_carrying_builder():
    src = inspect.getsource(ProfileLoaderMixin._reload_profiles)
    assert 'self._rebuild_adapter_map(by_id)' in src
    assert 'build_adapter_map(' not in src.replace('_rebuild_adapter_map(', '')


# ─────────────────────────────────────────────────────────────────────────────
# 3. 쉼의 사이클 양자화 — "펄스 시작 간격 ≥ min_off" (2026-10-13)
# ─────────────────────────────────────────────────────────────────────────────
# 쉼을 펄스 끝부터 재면 주기 600 · 쉼 600 · 켬 20 에서 막힌 시각(620 s)이 다음 사이클을
# 넘겨 20분마다 뿌린다. 남은 막힘이 켬 시간 + 흔들림 여유(5 s) 이하이면 허용한다(상한: 쉼의 10 %).

class TestRestQuantization:

    CMD = {'fog': {'value': 100.0, 'reason': 1}}

    def _run(self, h, clock, monkeypatch, offsets, min_off, max_on=20.0, period=600.0):
        """사이클마다(재적재 포함) 전송하고 켬/끔을 돌려준다. offsets = 사이클 시각 흔들림(s)."""
        out = []
        for i, jit in enumerate(offsets):
            clock['now'] = T0 + i * period + jit
            _reload(h, monkeypatch, min_off=min_off, max_on=max_on)
            h.control.calls.clear()
            h._dispatch_commands(self.CMD, period)
            out.append(h.control.kinds()[0])
        return out

    def test_600_600_20_sprays_every_cycle_even_with_jitter(self, clock, monkeypatch):
        h = _host(min_off=600.0)
        jit = [3.0, 1.0, 4.0, 0.0, 2.0, -1.0, 3.0, 0.5]       # 간격 598·603·596·602·597·604·597.5
        assert self._run(h, clock, monkeypatch, jit, 600.0) == ['on'] * len(jit)

    def test_the_allowance_is_bounded(self, clock, monkeypatch):
        """간격이 켬 + 5 s 보다 더 짧으면(이른 사이클) 여전히 막는다."""
        h = _host(min_off=600.0)
        assert self._run(h, clock, monkeypatch, [0.0, -10.0], 600.0) == ['on', 'off']

    def test_a_900_rest_still_skips_one_cycle(self, clock, monkeypatch):
        h = _host(min_off=900.0)
        jit = [3.0, 1.0, 4.0, 0.0, 2.0, -1.0]
        assert self._run(h, clock, monkeypatch, jit, 900.0) == ['on', 'off'] * 3

    def test_the_allowance_is_at_most_a_tenth_of_the_rest(self, clock):
        a, ctl = _pulsed(max_on=30.0, min_off=180.0), _Control()
        a.send(ctl, 'fog', 100.0, 0, 60.0)                  # 끝 30 s, 막힘 210 s, 허용 18 s
        clock['now'] = T0 + 210.0 - 18.5
        ctl.calls.clear()
        a.send(ctl, 'fog', 100.0, 0, 60.0)
        assert ctl.kinds() == ['off']
        clock['now'] = T0 + 210.0 - 18.0
        ctl.calls.clear()
        a.send(ctl, 'fog', 100.0, 0, 60.0)
        assert ctl.kinds() == ['on']

    def test_the_allowance_survives_a_reload(self, clock):
        old = _pulsed(max_on=20.0, min_off=600.0)
        old.send(_Control(), 'fog', 100.0, 0, 600.0)
        new = _pulsed(max_on=20.0, min_off=600.0)
        da.carry_adapter_state({'fog': old}, {'fog': new})
        clock['now'] = T0 + 597.0
        ctl = _Control()
        new.send(ctl, 'fog', 100.0, 0, 600.0)
        assert ctl.kinds() == ['on']

    def test_no_allowance_after_a_reason_57_pulse(self, clock, monkeypatch):
        """근거 57 의 15분 하한은 그대로 — 남은 막힘이 몇 초여도 평소 가습은 끈다."""
        h = _host(min_off=600.0)
        _reload(h, monkeypatch, min_off=600.0, max_on=20.0)
        h._dispatch_commands({'fog': {'value': 100.0, 'reason': PF.PULSE_FOG_REASON}}, 600.0)
        assert h.control.calls[0] == ('on', 'fog', 10.0)    # 끝 10 s, 막힘 910 s
        for at, want in ((905.0, 'off'), (909.0, 'off'), (910.0, 'on')):
            clock['now'] = T0 + at
            _reload(h, monkeypatch, min_off=600.0, max_on=20.0)
            h.control.calls.clear()
            h._dispatch_commands(self.CMD, 600.0)
            assert h.control.kinds() == [want], at

    def test_reason_57_cadence_is_unchanged(self, clock, monkeypatch):
        """근거 57 이 이어지면 코디네이터 시계로 1200 s(두 사이클)마다 — 예전과 같다."""
        h = _host(min_off=600.0)
        pf = {'fog': {'value': 100.0, 'reason': PF.PULSE_FOG_REASON}}
        got = []
        for i, jit in enumerate([2.0, 0.0, 3.0, 1.0, 0.0]):
            clock['now'] = T0 + i * 600.0 + jit
            _reload(h, monkeypatch, min_off=600.0, max_on=20.0)
            h.control.calls.clear()
            h._dispatch_commands(pf, 600.0)
            got.append(h.control.kinds()[0])
        assert got == ['on', 'off', 'on', 'off', 'on']
