# coding=utf-8
"""
MPC 규칙 동등성(D 단계, 2026-09-22) — PI 가 지키는 파킹 판정을 MPC 도 지킨다.

판정은 `coordinator.decide_parking` 한 곳이다. PI 는 파킹된 장치를 safe_default 로
감쇠시키고, MPC 는 채널 상한(`optimize_channels(channel_upper=...)`)으로 받는다.
"""

import logging
import types as _types

from aot.functions.utils.env_control.greybox.params import GreyboxParams
from aot.functions.utils.env_control.greybox import mpc as gbmpc
from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate, decide_parking,
)
from aot.functions.utils.env_control.log_channels import (
    REASON_NIGHT_PARKED, REASON_OPPOSING_PARKED, REASON_NO_GRADIENT,
)
from aot.functions.utils.env_control.situation import assess

from .conftest import make_ctx, make_target, make_opening_profile, make_heater_profile


def _insulated():
    p = GreyboxParams()
    p.UA_eff = 120.0
    p.tau_T = 1200.0
    return p


def _coord(profiles, params=None):
    from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
    from aot.functions.utils.env_control.greybox.mpc import MPCConfig
    c = CycleMixin.__new__(CycleMixin)
    c._profiles = profiles
    c._coord_state = CoordinatorState()
    c._greybox_active = True
    c._mpc_enabled = True
    c._greybox_shadow_inst = _types.SimpleNamespace(params=params or _insulated())
    c._mpc_config = MPCConfig(horizon=8)
    c._actuator_idx = {}
    c.logger = logging.getLogger('test_mpc_parity')
    return c


def _hot_report(**flags):
    """더운 실내 + 찬 외기 — 막지 않으면 MPC 가 창을 연다."""
    ctx = make_ctx(T_int=32.0, T_ext=15.0, RH_ext=50.0)
    report, _ = assess(make_target(vpd=1.2, T=22.0), ctx['internal'], ctx['external'],
                       cycle_sec=60.0, now_ts=ctx['now_ts'])
    report.context.update(flags)
    return report


class TestChannelUpper:
    def test_상한이_경계다(self):
        """벌점이 아니라 경계 — 열면 이득이어도 상한을 넘지 않는다."""
        kw = dict(state=(32.0, 60.0, 600.0), targets={'temperature': (22.0, 1.0, 0.8)},
                  profiles=[make_opening_profile()],
                  ext_seq=[{'T_ext': 15.0, 'RH_ext': 50.0, 'CO2_ext': 400.0,
                            'solar': 0.0, 'wind': 2.0}] * 10,
                  params=_insulated(), prev_channel_cmds={'vent': 40.0})
        free = gbmpc.optimize_channels(**kw)
        capped = gbmpc.optimize_channels(**kw, channel_upper={'vent': 0.0})
        assert free.channel_cmds['vent'] > 10.0
        assert capped.channel_cmds['vent'] == 0.0

    def test_부분_상한(self):
        kw = dict(state=(32.0, 60.0, 600.0), targets={'temperature': (22.0, 1.0, 0.8)},
                  profiles=[make_opening_profile()],
                  ext_seq=[{'T_ext': 15.0, 'RH_ext': 50.0, 'CO2_ext': 400.0,
                            'solar': 0.0, 'wind': 2.0}] * 10,
                  params=_insulated(), prev_channel_cmds={'vent': 0.0})
        res = gbmpc.optimize_channels(**kw, channel_upper={'vent': 20.0})
        assert 0.0 <= res.channel_cmds['vent'] <= 20.0


class TestRunMpcParking:
    def test_막지_않으면_연다(self):
        """아래 테스트들의 전제 — 이 상황에서 MPC 는 창을 연다."""
        c = _coord([make_opening_profile()])
        cmds, _ = c._run_mpc(_hot_report(), 'u')
        assert cmds['vent_01'].control_value() > 0.0
        assert c._last_mpc_caps == {}

    def test_야간_파킹(self):
        c = _coord([make_opening_profile()])
        cmds, _ = c._run_mpc(_hot_report(night_vent_park=True), 'u')
        assert cmds['vent_01'].control_value() == 0.0
        assert cmds['vent_01'].reason == REASON_NIGHT_PARKED
        assert c._last_mpc_caps == {'vent': 0.0}

    def test_냉난방_연동(self):
        c = _coord([make_opening_profile()])
        cmds, _ = c._run_mpc(_hot_report(hvac_interlock=True, hvac_running=True), 'u')
        assert cmds['vent_01'].control_value() == 0.0
        assert cmds['vent_01'].reason == REASON_NO_GRADIENT

    def test_냉난방_연동은_가동_중일_때만(self):
        c = _coord([make_opening_profile()])
        cmds, _ = c._run_mpc(_hot_report(hvac_interlock=True, hvac_running=False), 'u')
        assert cmds['vent_01'].control_value() > 0.0

    def test_온도_축_반대편_난방기(self):
        """실내가 목표보다 덥다(32 vs 22) — 난방기는 VPD 가 원해도 켜지지 않는다."""
        c = _coord([make_opening_profile(), make_heater_profile()])
        cmds, _ = c._run_mpc(_hot_report(), 'u')
        assert cmds['heater_01'].control_value() == 0.0
        assert cmds['heater_01'].reason == REASON_OPPOSING_PARKED
        assert c._last_mpc_caps.get('heat') == 0.0

    def test_파킹이_열린_창을_닫는다(self):
        """이미 열린 창은 슬루 제한 안에서 닫힌다(PI 의 감쇠와 같은 방향)."""
        c = _coord([make_opening_profile()])
        c._coord_state = CoordinatorState(prev_commands={'vent_01': 60.0})
        cmds, _ = c._run_mpc(_hot_report(night_vent_park=True), 'u')
        assert cmds['vent_01'].control_value() < 60.0


def _cooler():
    from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints
    from aot.functions.utils.env_control.effect_functions import build_effect_model
    return ActuatorProfile(
        actuator_id='cooler_01', kind='cooler',
        effect_model=build_effect_model('cooler', {}),
        cmd_constraints=CmdConstraints(slew_per_cycle=20.0),
        gains={'kp': 1.0, 'ki': 0.05}, safe_default=0.0)


class TestVentFirst:
    def test_환기로_닿으면_냉방기를_쉬게_한다(self):
        c = _coord([make_opening_profile(), _cooler()])
        cmds, st = c._run_mpc(_hot_report(vent_first=True), 'u')
        assert cmds['cooler_01'].control_value() == 0.0
        assert c._last_mpc_caps.get('cool') == 0.0
        assert st.vent_first_held_s == 60.0

    def test_인내_시간이_사이클을_넘어_쌓인다(self):
        """예전 MPC 경로는 미모델 장치만 보는 coordinate() 의 값을 받아 매 사이클 0 으로
        풀렸다 — 냉난방에 넘기는 경로가 MPC 에서 죽어 있었다."""
        from aot.functions.utils.env_control.coordinator import VENT_FIRST_PATIENCE_S
        c = _coord([make_opening_profile(), _cooler()])
        c._coord_state = CoordinatorState(vent_first_held_s=VENT_FIRST_PATIENCE_S)
        _, st = c._run_mpc(_hot_report(vent_first=True), 'u')
        assert st.vent_first_held_s > VENT_FIRST_PATIENCE_S
        assert 'cool' not in c._last_mpc_caps      # 인내가 다 차면 냉방기에 넘긴다


class TestSameDecision:
    def test_PI_와_MPC_가_같은_장치를_파킹한다(self):
        """판정이 한 곳이라는 것을 결과로 확인한다 — 같은 상황, 같은 파킹 사유."""
        profiles = [make_opening_profile(), make_heater_profile()]
        report = _hot_report(night_vent_park=True)
        pk = decide_parking(profiles, report, report.context, 60.0, {}, 0.0)
        assert pk.park_ids == {'vent_01', 'heater_01'}

        pi_cmds, _ = coordinate(report, profiles, CoordinatorState())
        c = _coord(profiles)
        mpc_cmds, _ = c._run_mpc(_hot_report(night_vent_park=True), 'u')
        for aid in ('vent_01', 'heater_01'):
            assert pi_cmds[aid].reason == mpc_cmds[aid].reason
            assert mpc_cmds[aid].control_value() == 0.0

    def test_그림자는_인내_상태를_바꾸지_않는다(self):
        c = _coord([make_opening_profile()])
        c._coord_state = CoordinatorState(vent_first_held_s=123.0)
        _, st = c._run_mpc(_hot_report(), '', shadow=True)
        assert st.vent_first_held_s == 123.0
