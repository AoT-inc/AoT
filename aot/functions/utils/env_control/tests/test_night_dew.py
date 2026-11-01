# coding=utf-8
"""밤 이슬 순환팬 (근거 59, 2026-10-12) — 판정(`night_dew.wanted`)과 `_apply_mixing_actuators` 이음매.

닫힌 집의 열대야: 외기 이슬점이 실내보다 높아 창으로 습기가 안 빠진다 — 순환팬으로 잎이 젖어 있는 시간을 줄인다.
"""
import logging

import pytest

import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cycle_mod  # noqa: F401
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
from aot.functions.utils.env_control import humid_regime as HR
from aot.functions.utils.env_control import night_dew as ND
from aot.functions.utils.env_control.coordinator import ActuatorCommand, CoordinatorState
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.log_channels import (
    REASON_NIGHT_DEW_FAN, REASON_PRIMARY, reason_name)
from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints

# 25 °C · RH 97 % → 이슬점 여유 ≈ 0.6 °C(진입선 2.0 아래) / RH 85 % → ≈ 2.4 °C(해제선 3.0 아래, 진입선 위)
WET = (25.0, 97.0)
MID = (25.0, 85.0)
DRY = (25.0, 70.0)      # 여유 ≈ 5.7 °C


class TestThresholdsAreHumidRegimes:
    def test_same_constants_as_over_humid_zone(self):
        assert ND.ENTER_MARGIN_C == HR.ENTER_MARGIN_C
        assert ND.EXIT_MARGIN_C == HR.EXIT_MARGIN_C

    def test_margin(self):
        assert 0.0 < ND.margin_c(*WET) < ND.ENTER_MARGIN_C
        assert ND.ENTER_MARGIN_C < ND.margin_c(*MID) < ND.EXIT_MARGIN_C
        assert ND.margin_c(*DRY) > ND.EXIT_MARGIN_C
        assert ND.margin_c(None, 90.0) is None and ND.margin_c(20.0, None) is None

    def test_reason_code(self):
        assert REASON_NIGHT_DEW_FAN == 59
        assert reason_name(59) == 'night_dew_fan'


class TestWanted:
    def test_night_and_low_margin_turns_on(self):
        st = ND.NightDewState()
        assert ND.wanted(st, *WET, True, 0.0) is True
        assert st.on and st.since == 0.0

    def test_day_never(self):
        st = ND.NightDewState()
        assert ND.wanted(st, *WET, False, 0.0) is False

    def test_unknown_night_is_not_night(self):
        """좌표를 몰라 밤인지 모르면 팬을 세우지 않는다."""
        st = ND.NightDewState()
        assert ND.wanted(st, *WET, None, 0.0) is False

    def test_unknown_indoor_is_off(self):
        st = ND.NightDewState()
        assert ND.wanted(st, None, 97.0, True, 0.0) is False
        assert ND.wanted(st, 25.0, None, True, 0.0) is False

    def test_dry_night_stays_off(self):
        st = ND.NightDewState()
        assert ND.wanted(st, *DRY, True, 0.0) is False

    def test_hysteresis_band_holds_both_ways(self):
        st = ND.NightDewState()
        assert ND.wanted(st, *MID, True, 0.0) is False            # 켜지 못하는 자리(진입선 위)
        assert ND.wanted(st, *WET, True, 100.0) is True
        t = ND.MIN_ON_S + 100.0
        assert ND.wanted(st, *MID, True, t) is True               # 밴드 안 — 켜진 채
        assert ND.wanted(st, *DRY, True, t + 600.0) is False      # 해제선 위 — 꺼짐

    def test_min_on_holds_through_dry_reading(self):
        st = ND.NightDewState()
        ND.wanted(st, *WET, True, 0.0)
        assert ND.wanted(st, *DRY, True, 600.0) is True           # 센서 잡음 — 최소 가동 안
        assert ND.wanted(st, *DRY, True, ND.MIN_ON_S) is False

    def test_sunrise_stops_immediately(self):
        st = ND.NightDewState()
        ND.wanted(st, *WET, True, 0.0)
        assert ND.wanted(st, *WET, False, 60.0) is False
        assert not st.on and st.since is None


def _p(aid, kind):
    return ActuatorProfile(actuator_id=aid, kind=kind, effect_model={},
                           cmd_constraints=CmdConstraints(), gains={})


def _host(profiles=None, night=True, enabled=True):
    c = CycleMixin.__new__(CycleMixin)
    c.night_dew_fan = enabled          # 옵션(기본 꺼짐) — 규칙을 보는 시험은 켠다
    c._profiles = profiles if profiles is not None else [
        _p('win', 'opening'), _p('circ', 'circulation_fan')]
    c._coord_state = CoordinatorState()
    c.unique_id = 'fn-night-dew'
    c.logger = logging.getLogger('test_night_dew')
    c.lines = []
    c._status_log = lambda level, msg, *a: c.lines.append(msg % a)
    c._facility_night = lambda: night
    return c


def _cmds():
    return {'circ': ActuatorCommand(value=0.0, reason=0),
            'win': ActuatorCommand(value=0.0, reason=0)}


def _internal(th=WET, **extra):
    return {'T': th[0], 'RH': th[1], **extra}


class TestMixingSeam:
    def test_night_dew_runs_the_fan_with_reason_59(self):
        c = _host()
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal())
        assert cmds['circ'].value == 100.0
        assert cmds['circ'].reason == REASON_NIGHT_DEW_FAN
        assert cmds['circ'].var_source == 'night_dew'
        assert cmds['win'].value == 0.0                    # 다른 장치는 건드리지 않는다

    def test_no_circulation_fan_no_effect_and_no_state(self):
        c = _host(profiles=[_p('win', 'opening'), _p('fog', 'fogger')])
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal())
        assert cmds['circ'].value == 0.0 and cmds['circ'].reason == 0
        assert getattr(c, '_night_dew_state', None) is None   # 판정조차 돌리지 않는다
        assert c.lines == []

    def test_daytime_no_effect(self):
        c = _host(night=False)
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal())
        assert cmds['circ'].value == 0.0

    def test_unknown_night_no_effect(self):
        c = _host(night=None)
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal())
        assert cmds['circ'].value == 0.0

    def test_dry_night_no_effect(self):
        c = _host()
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal(DRY))
        assert cmds['circ'].value == 0.0

    def test_heat_protect_keeps_its_own_reason(self):
        c = _host()
        cmds = _cmds()
        c._apply_mixing_actuators(
            cmds, _internal(_heat_protect=HeatProtectDecision(tier=1)))
        assert cmds['circ'].value == 100.0
        assert cmds['circ'].reason == REASON_PRIMARY
        assert cmds['circ'].var_source == 'heat_protect'

    def test_hotspot_keeps_its_own_reason(self):
        c = _host()
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal(_spatial_hotspot_T=True))
        assert cmds['circ'].reason == REASON_PRIMARY
        assert cmds['circ'].var_source == 'mixing'

    def test_existing_hotspot_rule_unchanged_without_dew(self):
        c = _host()
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal(DRY, _spatial_hotspot_RH=True))
        assert cmds['circ'].value == 100.0 and cmds['circ'].var_source == 'mixing'
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal(DRY))
        assert cmds['circ'].value == 0.0

    def test_transition_logged_once_each_way(self):
        c = _host()
        for _ in range(3):
            c._apply_mixing_actuators(_cmds(), _internal())
        assert len(c.lines) == 1 and '가동' in c.lines[0]
        c._facility_night = lambda: False
        for _ in range(3):
            c._apply_mixing_actuators(_cmds(), _internal())
        assert len(c.lines) == 2 and '정지' in c.lines[1]

    def test_multiple_fans_all_run(self):
        c = _host(profiles=[_p('c1', 'circulation_fan'), _p('c2', 'circulation_fan')])
        cmds = {'c1': ActuatorCommand(value=0.0, reason=0),
                'c2': ActuatorCommand(value=0.0, reason=0)}
        c._apply_mixing_actuators(cmds, _internal())
        assert all(v.value == 100.0 and v.reason == 59 for v in cmds.values())


class TestOptionDefaultOff:
    """2026-10-12 최종 폐루프 회귀 R3 — 열대야 밤 젖음 918 분 그대로, 팬 전력 +17 %·결로 +80 분. 기본 꺼짐."""

    def test_option_off_leaves_the_fan_alone(self):
        c = _host(enabled=False)
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal())
        assert cmds['circ'].value == 0.0 and cmds['circ'].reason == 0
        assert getattr(c, '_night_dew_state', None) is None   # 판정조차 돌리지 않는다
        assert c.lines == []

    def test_option_missing_is_off(self):
        c = _host()
        del c.night_dew_fan
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal())
        assert cmds['circ'].value == 0.0

    def test_option_off_keeps_heat_protect_and_hotspot(self):
        c = _host(enabled=False)
        cmds = _cmds()
        c._apply_mixing_actuators(cmds, _internal(_spatial_hotspot_T=True))
        assert cmds['circ'].value == 100.0 and cmds['circ'].var_source == 'mixing'
        cmds = _cmds()
        c._apply_mixing_actuators(
            cmds, _internal(_heat_protect=HeatProtectDecision(tier=1)))
        assert cmds['circ'].value == 100.0 and cmds['circ'].var_source == 'heat_protect'

    def test_schema_declares_it_advanced_and_off(self):
        from aot.functions.custom_functions.env_coordinator_impl import _function_info as fi
        opt = next(o for o in fi.FUNCTION_INFORMATION['custom_options']
                   if o.get('id') == 'night_dew_fan')
        assert opt['type'] == 'bool'
        assert opt['default_value'] is False
        assert opt.get('advanced_only') is True


class TestFacilityNight:
    def test_inverts_is_daytime_and_keeps_unknown(self, monkeypatch):
        import aot.utils.solar as solar
        c = _host()
        del c._facility_night           # 인스턴스 람다를 걷어 진짜 메서드를 쓴다
        monkeypatch.setattr(solar, 'is_daytime', lambda **kw: False)
        assert c._facility_night() is True
        monkeypatch.setattr(solar, 'is_daytime', lambda **kw: True)
        assert c._facility_night() is False
        monkeypatch.setattr(solar, 'is_daytime', lambda **kw: None)
        assert c._facility_night() is None

    def test_exception_is_not_night(self, monkeypatch):
        import aot.utils.solar as solar
        c = _host()
        del c._facility_night

        def boom(**kw):
            raise RuntimeError('x')
        monkeypatch.setattr(solar, 'is_daytime', boom)
        assert c._facility_night() is None
