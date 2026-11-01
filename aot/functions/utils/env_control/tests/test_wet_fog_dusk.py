# coding=utf-8
"""습윤형 분무는 해 질 녘으로 달리지 않는다 — 약한 해 비례 감쇠 + 일몰 전~일출 0 (2026-10-10 영양).

## 실측

    영양 육묘장(개발서버 2026-10-10, 토마토 VPD 목표 1.0, nursery_mode 꺼짐)
    분무기 "육묘장-분무"(습윤형)가 12:00~17:00 내내 100 %(근거 1, VPD)
    일사 150 → 46 → 31 W/m², VPD 1.18(16:30) → 0.87(17:00), 일몰 17:54

기존 저녁 차단(`nursery_evening_fog`)과 일소 잠금은 육묘 모드에서만 선다.

## 육묘 모드도 받는다 (2026-10-10 김제, `heatwave_tropical_night`)

일소 잠금이 낮 내내 분무를 막다가 저녁에 풀리면 해 진 뒤에 습윤 분무가 돌아 잎이 밤마다 590분쯤 젖었다.
그래서 육묘 모드도 같은 규칙을 받는다(아래 `TestNursery`). 구간 시작만 `nursery_evening_cutoff_min`(기본 120분)을
따르고, 끄는 스위치는 `wetting_fog_dusk_stop` 하나다. `nursery_evening_fog` 는 그 스위치를 껐을 때만 읽힌다.

## 구조

    판정(일사 → 비율, 구간 → 0)     `wet_fog_dusk.evaluate_wetting_fog_dusk`
    구간(일몰 − 90분 ~ 일출)        `_past_dusk_cutoff` — 육묘 저녁 차단과 **같은 함수**
    입력을 모아 `internal` 에 심기   `_evaluate_wetting_fog_dusk`
    명령에 곱하기                    `apply_wetting_fog_dusk_limit` (근거 53)
"""
import ast
import datetime as dt
import inspect
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    CycleMixin, apply_nursery_fog_derate, apply_threshold_and_gate_overrides,
    apply_wetting_fog_dusk_limit,
)
from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control import wet_fog_dusk as WFD
from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints


def _fogger(aid='fog', wetting=True):
    return ActuatorProfile(
        actuator_id=aid, kind='fogger', capabilities=['humidify', 'cooling_passive'],
        cost_fn=lambda env, pct: 5.0, response_sec=60.0, safe_default=0.0,
        capacity_meta={'nozzle': {'wetting': wetting}},
        cmd_constraints=CmdConstraints(max_on_sec=30.0, min_off_sec=180.0))


def _opening(aid='vent'):
    return ActuatorProfile(
        actuator_id=aid, kind='opening', capabilities=['ventilation'],
        cost_fn=lambda env, pct: 5.0, response_sec=60.0, safe_default=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 판정
# ─────────────────────────────────────────────────────────────────────────────

class TestDecision:

    @pytest.mark.parametrize('solar,expected', [
        (800.0, 1.0), (150.0, 1.0), (125.0, 0.75), (100.0, 0.5), (75.0, 0.25),
        (50.0, 0.0), (46.0, 0.0), (31.0, 0.0), (0.0, 0.0),
    ])
    def test_the_cap_is_proportional_between_50_and_150(self, solar, expected):
        assert WFD.solar_scale(solar) == pytest.approx(expected)

    def test_unknown_light_does_not_limit(self):
        """일사를 모르면 막지 않는다 — 모른다고 정상 가습을 끊지 않는다."""
        assert WFD.solar_scale(None) == 1.0
        assert not WFD.evaluate_wetting_fog_dusk(None, False).limited

    def test_the_measured_afternoon_is_cut_to_zero(self):
        """영양 16:30 의 일사 46 W/m² — 100 % 로 돌던 분무가 0 이 된다."""
        d = WFD.evaluate_wetting_fog_dusk(46.0, False)
        assert d.limited and d.scale == 0.0 and d.why == 'low_sun'

    def test_the_cutoff_window_is_zero_whatever_the_light(self):
        for solar in (None, 0.0, 400.0, 900.0):
            d = WFD.evaluate_wetting_fog_dusk(solar, True)
            assert d.scale == 0.0 and d.why == 'dusk'

    def test_bright_daytime_is_untouched(self):
        d = WFD.evaluate_wetting_fog_dusk(650.0, False)
        assert not d.limited and d.why is None and d.scale == 1.0

    def test_constants_are_the_documented_ones(self):
        assert (WFD.WFD_SOLAR_FULL_W, WFD.WFD_SOLAR_ZERO_W, WFD.WFD_CUTOFF_MIN) == (
            150.0, 50.0, 90.0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. 명령에 곱하기 — 습윤형만, 줄이는 쪽으로만
# ─────────────────────────────────────────────────────────────────────────────

def _dec(solar=100.0, past=False):
    return WFD.evaluate_wetting_fog_dusk(solar, past)


class TestApply:

    def test_wetting_fog_is_scaled_with_reason_53(self):
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 80.0, 'reason': 1}}
        apply_wetting_fog_dusk_limit({'_wet_fog_dusk': _dec(100.0)}, [fog], cmds)
        assert cmds[fog.actuator_id]['value'] == pytest.approx(40.0)
        assert LC.reason_code(cmds[fog.actuator_id]['reason']) == LC.REASON_WETTING_FOG_DUSK == 53

    def test_dusk_cuts_it_to_zero(self):
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 100.0, 'reason': 1}}
        apply_wetting_fog_dusk_limit({'_wet_fog_dusk': _dec(900.0, past=True)}, [fog], cmds)
        assert cmds[fog.actuator_id] == {'value': 0.0, 'reason': 'wetting_fog_dusk'}

    def test_fine_fog_is_not_touched(self):
        """고압 미세포그는 잎을 적시지 않는다 — 습윤형만 대상이다."""
        fine = _fogger('fine', wetting=False)
        cmds = {'fine': {'value': 100.0, 'reason': 1}}
        apply_wetting_fog_dusk_limit({'_wet_fog_dusk': _dec(900.0, past=True)}, [fine], cmds)
        assert cmds['fine'] == {'value': 100.0, 'reason': 1}

    def test_mixed_site_cuts_only_the_wetting_one(self):
        wet, fine, vent = _fogger('wet'), _fogger('fine', wetting=False), _opening()
        cmds = {'wet': {'value': 100.0, 'reason': 1}, 'fine': {'value': 60.0, 'reason': 1},
                'vent': {'value': 30.0, 'reason': 1}}
        apply_wetting_fog_dusk_limit({'_wet_fog_dusk': _dec(0.0, past=True)}, [wet, fine, vent], cmds)
        assert cmds['wet']['value'] == 0.0
        assert cmds['fine']['value'] == 60.0 and cmds['vent']['value'] == 30.0

    def test_no_decision_or_no_limit_does_nothing(self):
        fog = _fogger()
        for internal in ({}, {'_wet_fog_dusk': _dec(650.0)}):
            cmds = {fog.actuator_id: {'value': 70.0, 'reason': 1}}
            apply_wetting_fog_dusk_limit(internal, [fog], cmds)
            assert cmds[fog.actuator_id] == {'value': 70.0, 'reason': 1}

    def test_it_never_turns_fog_on(self):
        """이미 0 인 명령의 근거를 가로채지도, 켜지도 않는다."""
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 0.0, 'reason': 'fog_humidity_ceiling'}}
        apply_wetting_fog_dusk_limit({'_wet_fog_dusk': _dec(100.0)}, [fog], cmds)
        assert cmds[fog.actuator_id] == {'value': 0.0, 'reason': 'fog_humidity_ceiling'}

    def test_a_missing_command_is_skipped(self):
        apply_wetting_fog_dusk_limit({'_wet_fog_dusk': _dec(100.0)}, [_fogger()], {})


class TestInsideTheOverrideChain:

    def test_humid_min_cannot_force_wetting_fog_into_the_dusk(self):
        """습도 하한이 분무를 100 % 로 강제해도 저녁에는 습윤형으로 채우지 않는다."""
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 5.0, 'reason': 1}}
        internal = {'RH': 30.0, '_force_humid': True,
                    '_wet_fog_dusk': _dec(20.0, past=True)}
        apply_threshold_and_gate_overrides(internal, [fog], cmds, {})
        assert cmds[fog.actuator_id]['value'] == 0.0
        assert cmds[fog.actuator_id]['reason'] == 'wetting_fog_dusk'

    def test_order_is_derate_then_dusk_then_ceiling_then_gate(self):
        src = inspect.getsource(apply_threshold_and_gate_overrides)
        order = [src.index(n) for n in (
            'apply_nursery_fog_derate(', 'apply_wetting_fog_dusk_limit(',
            'apply_wetting_fog_humidity_ceiling(', 'if partial_overrides:')]
        assert order == sorted(order), order

    def test_the_safety_gate_still_wins_over_it(self):
        fog = _fogger()
        cmds = {fog.actuator_id: {'value': 100.0, 'reason': 1}}
        apply_threshold_and_gate_overrides(
            {'_wet_fog_dusk': _dec(100.0)}, [fog], cmds,
            {fog.actuator_id: {'value': 0.0, 'reason': 12}})
        assert cmds[fog.actuator_id] == {'value': 0.0, 'reason': 12}


# ─────────────────────────────────────────────────────────────────────────────
# 3. 사이클 배선 — 입력을 모아 internal 에 심는다
# ─────────────────────────────────────────────────────────────────────────────

_DAY = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)


def _coord(profiles, nursery=False, option=None, **attrs):
    class C(CycleMixin):
        unique_id = 'x'
        log_level_debug = False
        nursery_evening_fog = True
        nursery_evening_cutoff_min = 120.0
    c = C()
    c.logger = MagicMock()
    c._status_log = MagicMock()
    c._profiles = profiles
    c.nursery_mode = nursery
    c.wetting_fog_dusk_stop = option
    for k, v in attrs.items():
        setattr(c, k, v)
    return c


def _run(monkeypatch, c, now_h, solar=650.0, sunset_h=9, sunrise_h=21, minute=0, sun=None):
    """UTC 기준 시각으로 한 사이클을 돌린다. 기본 일몰 09:00Z · 일출 21:00Z(= 오늘 일출이 밤 뒤에 오는 값 —
    낮 시험은 sunrise_h=0 으로 '일출이 이미 지났다' 를 만든다)."""
    day = _DAY
    sun = sun if sun is not None else SimpleNamespace(
        sunset=None if sunset_h is None else day.replace(hour=sunset_h),
        sunrise=None if sunrise_h is None else day.replace(hour=sunrise_h))
    monkeypatch.setattr('aot.utils.solar.sun_times', lambda **k: sun)
    monkeypatch.setattr('aot.utils.timekit.utc_now',
                        lambda: day.replace(hour=now_h, minute=minute))
    internal = {} if solar is None else {'_outdoor_solar': solar}
    sit = SimpleNamespace(context={'external': {}})
    c._evaluate_wetting_fog_dusk(internal, sit)
    return internal


class TestWiring:
    def test_bright_afternoon_plants_nothing(self, monkeypatch):
        c = _coord([_fogger()])
        internal = _run(monkeypatch, c, now_h=5, sunrise_h=0)
        assert '_wet_fog_dusk' not in internal

    def test_weak_light_before_the_cutoff_scales(self, monkeypatch):
        c = _coord([_fogger()])
        internal = _run(monkeypatch, c, now_h=5, sunrise_h=0, solar=100.0)
        d = internal['_wet_fog_dusk']
        assert d.why == 'low_sun' and d.scale == pytest.approx(0.5)

    def test_cutoff_is_90_minutes_before_sunset(self, monkeypatch):
        c = _coord([_fogger()])
        # 일몰 09:00Z → 07:30Z 부터. 07:29 는 아직, 07:30 은 쉰다. 일사는 밝아도 쉰다.
        assert '_wet_fog_dusk' not in _run(monkeypatch, c, now_h=7, minute=29, sunrise_h=0)
        d = _run(monkeypatch, c, now_h=7, minute=30, sunrise_h=0)['_wet_fog_dusk']
        assert d.why == 'dusk' and d.scale == 0.0

    def test_dusk_stands_even_without_a_light_reading(self, monkeypatch):
        c = _coord([_fogger()])
        d = _run(monkeypatch, c, now_h=8, sunrise_h=0, solar=None)['_wet_fog_dusk']
        assert d.why == 'dusk'

    def test_night_before_sunrise_is_zero(self, monkeypatch):
        c = _coord([_fogger()])
        d = _run(monkeypatch, c, now_h=3, sunrise_h=21)['_wet_fog_dusk']   # 일출 전
        assert d.why == 'dusk'

    def test_after_sunrise_the_light_decides(self, monkeypatch):
        c = _coord([_fogger()])
        assert '_wet_fog_dusk' not in _run(monkeypatch, c, now_h=3, sunrise_h=2)

    def test_no_location_and_no_light_does_not_limit(self, monkeypatch):
        c = _coord([_fogger()])
        internal = {}
        monkeypatch.setattr('aot.utils.solar.sun_times', lambda **k: None)
        monkeypatch.setattr('aot.utils.timekit.utc_now', lambda: _DAY.replace(hour=8))
        c._evaluate_wetting_fog_dusk(internal, SimpleNamespace(context={'external': {}}))
        assert '_wet_fog_dusk' not in internal

    def test_estimated_light_is_used_without_a_sensor(self, monkeypatch):
        """센서가 없으면 맑은 하늘 × 구름비(없으면 0.5)로 어림한다 — `solar_vent.solar_load`."""
        c = _coord([_fogger()], _clear_sky_now=180.0)    # × 0.5 = 90 W/m²
        internal = _run(monkeypatch, c, now_h=5, sunrise_h=0, solar=None)
        assert internal['_wet_fog_dusk'].scale == pytest.approx(0.4)

    def test_the_option_turns_it_off(self, monkeypatch):
        c = _coord([_fogger()], option=False)
        assert '_wet_fog_dusk' not in _run(monkeypatch, c, now_h=8, sunrise_h=0)

    def test_unset_option_means_on(self, monkeypatch):
        c = _coord([_fogger()], option=None)
        assert _run(monkeypatch, c, now_h=8, sunrise_h=0)['_wet_fog_dusk'].why == 'dusk'

    def test_fine_fog_only_site_is_not_judged(self, monkeypatch):
        c = _coord([_fogger('fine', wetting=False), _opening()])
        assert '_wet_fog_dusk' not in _run(monkeypatch, c, now_h=8, sunrise_h=0)

    def test_it_says_so_once_when_it_changes(self, monkeypatch):
        c = _coord([_fogger()])
        _run(monkeypatch, c, now_h=8, sunrise_h=0)
        _run(monkeypatch, c, now_h=8, minute=10, sunrise_h=0)
        assert c._status_log.call_count == 1
        _run(monkeypatch, c, now_h=5, sunrise_h=0)           # 풀림
        assert c._status_log.call_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# 4. 육묘 모드도 받는다 — 구간 시작만 육묘 옵션을 따른다
# ─────────────────────────────────────────────────────────────────────────────

class TestNursery:

    def test_cutoff_minutes_is_one_place(self):
        assert WFD.cutoff_minutes(False, 45.0) == 90.0          # 육묘가 아니면 옵션을 읽지 않는다
        assert WFD.cutoff_minutes(True, None) == 120.0           # 옵션이 비면 육묘 기본
        assert WFD.cutoff_minutes(True, 150) == 150.0
        assert WFD.cutoff_minutes(True, '75') == 75.0            # 폼 문자열
        assert WFD.cutoff_minutes(True, 0) == 0.0                # 일몰부터
        assert WFD.cutoff_minutes(True, -5) == 0.0
        assert WFD.cutoff_minutes(True, 'abc') == 120.0

    def test_nursery_dusk_window_is_zero_reason_53(self, monkeypatch):
        """육묘 모드 + 해 질 녘 구간 → 결론이 심기고 습윤 분무는 0(근거 53)."""
        c = _coord([_fogger()], nursery=True)
        internal = _run(monkeypatch, c, now_h=8, sunrise_h=0)     # 일몰 09:00Z − 120분 = 07:00Z 이후
        d = internal['_wet_fog_dusk']
        assert d.why == 'dusk' and d.scale == 0.0 and d.cutoff_min == 120.0
        fog = c._profiles[0]
        cmds = {fog.actuator_id: {'value': 60.0, 'reason': 1}}
        internal['_nursery_mode'] = True
        apply_threshold_and_gate_overrides(internal, [fog], cmds, {})
        assert cmds[fog.actuator_id] == {'value': 0.0, 'reason': 'wetting_fog_dusk'}
        assert LC.reason_code(cmds[fog.actuator_id]['reason']) == 53

    def test_nursery_cutoff_follows_the_nursery_option(self, monkeypatch):
        """일몰 09:00Z — 기본 120분이면 07:00Z, 옵션 60분이면 08:00Z 부터. 비육묘의 90분(07:30Z)이 아니다."""
        c = _coord([_fogger()], nursery=True)
        assert '_wet_fog_dusk' not in _run(monkeypatch, c, now_h=6, minute=59, sunrise_h=0)
        assert _run(monkeypatch, c, now_h=7, sunrise_h=0)['_wet_fog_dusk'].why == 'dusk'
        c60 = _coord([_fogger()], nursery=True, nursery_evening_cutoff_min=60.0)
        assert '_wet_fog_dusk' not in _run(monkeypatch, c60, now_h=7, minute=59, sunrise_h=0)
        assert _run(monkeypatch, c60, now_h=8, sunrise_h=0)['_wet_fog_dusk'].why == 'dusk'

    def test_non_nursery_ignores_the_nursery_cutoff(self, monkeypatch):
        c = _coord([_fogger()], nursery=False, nursery_evening_cutoff_min=30.0)
        assert _run(monkeypatch, c, now_h=7, minute=29, sunrise_h=0).get('_wet_fog_dusk') is None
        d = _run(monkeypatch, c, now_h=7, minute=30, sunrise_h=0)['_wet_fog_dusk']
        assert d.why == 'dusk' and d.cutoff_min == 90.0

    def test_nursery_taper_in_weak_light(self, monkeypatch):
        """구간 앞의 약한 해: 100 W/m² → 절반, 46 W/m² → 0(low_sun). 육묘 모드도 같다."""
        c = _coord([_fogger()], nursery=True)
        d = _run(monkeypatch, c, now_h=5, sunrise_h=0, solar=100.0)['_wet_fog_dusk']
        assert d.why == 'low_sun' and d.scale == pytest.approx(0.5)
        d = _run(monkeypatch, c, now_h=5, sunrise_h=0, solar=46.0)['_wet_fog_dusk']
        assert d.why == 'low_sun' and d.scale == 0.0

    def test_nursery_bright_day_is_untouched(self, monkeypatch):
        """강한 해(낮)는 이 규칙의 몫이 아니다 — 일소 잠금·감쇠(근거 36)가 그대로 맡는다."""
        c = _coord([_fogger()], nursery=True)
        assert '_wet_fog_dusk' not in _run(monkeypatch, c, now_h=3, sunrise_h=0, solar=700.0)

    def test_nursery_night_before_sunrise_is_zero(self, monkeypatch):
        c = _coord([_fogger()], nursery=True)
        assert _run(monkeypatch, c, now_h=3, sunrise_h=21)['_wet_fog_dusk'].why == 'dusk'

    def test_nursery_opt_out_by_the_switch(self, monkeypatch):
        """스위치를 끄면 육묘 모드도 종전대로(저녁 분무는 `nursery_evening_fog` 가 정한다)."""
        c = _coord([_fogger()], nursery=True, option=False)
        assert '_wet_fog_dusk' not in _run(monkeypatch, c, now_h=8, sunrise_h=0)

    def test_evening_fog_true_does_not_override_the_new_default(self, monkeypatch):
        """`nursery_evening_fog` 켜짐(기본)이어도 이 규칙은 선다 — 기본값이라 명시한 선택과 구분되지 않는다."""
        c = _coord([_fogger()], nursery=True, nursery_evening_fog=True)
        assert _run(monkeypatch, c, now_h=8, sunrise_h=0)['_wet_fog_dusk'].why == 'dusk'

    def test_evening_fog_is_only_read_when_the_switch_is_off(self, monkeypatch):
        """스위치 꺼짐 + `nursery_evening_fog` 꺼짐 → 종전 게이트 차단(`evening_block`)만 선다. 켜짐이면 둘 다 없다."""
        for fog_allowed, expect_block in ((False, True), (True, False)):
            c = _coord([_fogger()], nursery=True, option=False, nursery_evening_fog=fog_allowed)
            day = _DAY
            sun = SimpleNamespace(sunset=day.replace(hour=9), sunrise=day.replace(hour=0))
            monkeypatch.setattr('aot.utils.solar.sun_times', lambda **k: sun)
            monkeypatch.setattr('aot.utils.timekit.utc_now', lambda: day.replace(hour=8))
            assert c._evening_fog_blocked() is expect_block
            assert '_wet_fog_dusk' not in _run(monkeypatch, c, now_h=8, sunrise_h=0)

    def test_both_on_share_the_same_cutoff(self, monkeypatch):
        """두 규칙이 모두 켜져도 구간 시작은 하나(`nursery_evening_cutoff_min`) — 서로 다른 시각에 서지 않는다."""
        c = _coord([_fogger()], nursery=True, nursery_evening_fog=False,
                   nursery_evening_cutoff_min=100.0)
        day = _DAY
        sun = SimpleNamespace(sunset=day.replace(hour=9), sunrise=day.replace(hour=0))
        monkeypatch.setattr('aot.utils.solar.sun_times', lambda **k: sun)
        for h, m in ((7, 19), (7, 20)):                # 09:00Z − 100분 = 07:20Z
            monkeypatch.setattr('aot.utils.timekit.utc_now',
                                lambda h=h, m=m: day.replace(hour=h, minute=m))
            internal = _run(monkeypatch, c, now_h=h, minute=m, sunrise_h=0)
            assert c._evening_fog_blocked() is ('_wet_fog_dusk' in internal)

    def test_nursery_derate_is_untouched_and_composes(self):
        """강한 해 감쇠(근거 36)는 자기 일을 한다. 이 규칙의 결론이 함께 있어도 한쪽만 1 보다 작은 구간이 없다."""
        fog = _fogger()
        internal = {'_nursery_mode': True, 'light_est': 200.0,
                    '_nursery_solar_lockout': 250.0, '_nursery_solar_release': 150.0,
                    '_wet_fog_dusk': _dec(100.0)}
        cmds = {fog.actuator_id: {'value': 100.0, 'reason': 1}}
        apply_nursery_fog_derate(internal, [fog], cmds)
        assert cmds[fog.actuator_id]['reason'] == 'nursery_fog_derate'
        assert cmds[fog.actuator_id]['value'] == pytest.approx(50.0)

    def test_fine_fog_in_nursery_is_not_judged(self, monkeypatch):
        c = _coord([_fogger('fine', wetting=False), _opening()], nursery=True)
        assert '_wet_fog_dusk' not in _run(monkeypatch, c, now_h=8, sunrise_h=0)

    def test_the_zone_test_has_a_single_owner(self):
        """구간 판정을 두 벌 두지 않는다 — 둘 다 `_past_dusk_cutoff` 를 부른다."""
        a = inspect.getsource(CycleMixin._evening_fog_blocked)
        b = inspect.getsource(CycleMixin._evaluate_wetting_fog_dusk)
        assert '_past_dusk_cutoff' in a and '_past_dusk_cutoff' in b
        assert 'sun_times' not in a and 'sun_times' not in b


# ─────────────────────────────────────────────────────────────────────────────
# 5. 근거 53 · 옵션
# ─────────────────────────────────────────────────────────────────────────────

class TestReasonAndOption:

    def test_reason_is_53_and_named(self):
        assert LC.REASON_WETTING_FOG_DUSK == 53
        assert LC.STRING_REASON_CODES['wetting_fog_dusk'] == 53
        assert LC.reason_name('wetting_fog_dusk') == 'wetting_fog_dusk'
        assert LC.reason_name(53) == 'wetting_fog_dusk'
        # 51·52(강우 단계 제한)·54(아침 습기 빼기) 는 그대로, 50 은 비어 있다(다른 브랜치가 쓴다)
        codes = {v for k, v in vars(LC).items() if k.startswith('REASON_') and isinstance(v, int)}
        assert LC.REASON_SOLAR_VENT_FLOOR == 51 and LC.REASON_RAIN_RESTRICT == 52
        assert LC.REASON_MORNING_PURGE == 54
        assert 50 not in codes

    def test_health_check_labels_it_and_counts_it_as_a_guard(self):
        from aot.scripts import check_env_coordinator_health as H
        assert H.REASON_LABEL[LC.REASON_WETTING_FOG_DUSK]
        assert LC.REASON_WETTING_FOG_DUSK in H.GUARD_REASONS

    def test_the_option_is_one_default_on_bool_outside_nursery(self):
        from aot.functions.custom_functions.env_coordinator_impl import _function_info as fi
        opt = next(o for o in fi.FUNCTION_INFORMATION['custom_options']
                   if o.get('id') == 'wetting_fog_dusk_stop') \
            if hasattr(fi, 'FUNCTION_INFORMATION') else None
        if opt is None:
            pytest.skip('옵션 목록 이름이 다르다 — 레이아웃 시험이 본다')
        assert opt['type'] == 'bool' and opt['default_value'] is True
        assert not opt.get('depends_on')     # 육묘 모드 토글에 묶지 않는다

    def test_run_cycle_only_calls_it(self):
        """`_run_cycle` 은 부르기만 한다 — 줄 수 상한은 `test_env_coordinator_cycle_structure`."""
        tree = ast.parse(inspect.getsource(_cycle_mixin))
        run = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == '_run_cycle')
        calls = [n.func.attr for n in ast.walk(run)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
        assert '_evaluate_wetting_fog_dusk' in calls
        assert calls.index('_evaluate_solar_vent') < calls.index('_evaluate_wetting_fog_dusk')
