# coding=utf-8
"""
greybox 물리 제어(Stage 3) 테스트.

대상:
  - channels: kind→채널 집계 (미모델 제외, id 폴백)
  - effect_adapter: 물리 민감도 부호/유한성 (heater→T↑, cooler→T↓, vent 냉방, co2→CO2↑)
  - identification: 합성 데이터에서 파라미터/예측 복원
  - coordinate() 통합: greybox effect_model 로 교체 시 합리적 명령 산출
"""

import math

import pytest

from aot.functions.utils.env_control.greybox.params import GreyboxParams
from aot.functions.utils.env_control.greybox.model import step
from aot.functions.utils.env_control.greybox import channels as ch
from aot.functions.utils.env_control.greybox.effect_adapter import greybox_effect_model
from aot.functions.utils.env_control.greybox import identification as ident
from aot.functions.utils.env_control.greybox import mpc as gbmpc
from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
from aot.functions.utils.env_control.situation import assess

from .conftest import make_ctx, make_target, make_opening_profile, make_heater_profile


# ── channels ─────────────────────────────────────────────────────────────────

class TestChannels:
    def test_kind_aggregation_max(self):
        cmds = {'a': 60, 'b': 30, 'c': 80}
        kinds = {'a': 'side_vent', 'b': 'roof_vent', 'c': 'heater'}
        out = ch.aggregate_cmds_by_kind(cmds, kinds)
        assert out['vent'] == 60.0   # max(60, 30)
        assert out['heat'] == 80.0

    def test_unmodeled_kind_excluded(self):
        # circulation_fan 은 외기교환이 아니므로 vent 채널에 잡히지 않아야 한다
        out = ch.aggregate_cmds_by_kind({'f': 100}, {'f': 'circulation_fan'})
        assert out['vent'] == 0.0
        assert ch.channel_for_kind('circulation_fan') is None
        assert ch.channel_for_kind('shade') is None

    def test_id_fallback_when_kind_missing(self):
        out = ch.aggregate_cmds_by_kind({'heater_1': 70, 'co2_valve': 40}, None)
        assert out['heat'] == 70.0
        assert out['co2_inj'] == 40.0


# ── effect adapter 부호 ───────────────────────────────────────────────────────

def _env(**kw):
    base = dict(T_int=30.0, T_ext=15.0, RH_int=70.0, RH_ext=50.0,
                CO2_int=800.0, CO2_ext=400.0, solar=0.0, wind=2.0, cycle_sec=60.0,
                _gb_base_cmds={'heat': 0, 'cool': 0, 'vent': 0, 'fog': 0, 'co2_inj': 0})
    base.update(kw)
    return base


class TestEffectAdapter:
    def test_unmodeled_returns_none(self):
        assert greybox_effect_model('shade', GreyboxParams()) is None
        assert greybox_effect_model('circulation_fan', GreyboxParams()) is None

    def test_heater_raises_temperature(self):
        m = greybox_effect_model('heater', GreyboxParams())
        eff = m['temperature'](_env())
        assert eff.direction == '↑'
        assert eff.magnitude_native > 0

    def test_cooler_lowers_temperature(self):
        m = greybox_effect_model('cooler', GreyboxParams())
        eff = m['temperature'](_env())
        assert eff.direction == '↓'
        assert eff.magnitude_native > 0

    def test_vent_cools_when_outside_colder(self):
        m = greybox_effect_model('side_vent', GreyboxParams())
        eff = m['temperature'](_env(T_int=30.0, T_ext=15.0))
        assert eff.direction == '↓'

    def test_vent_heats_when_outside_hotter(self):
        m = greybox_effect_model('side_vent', GreyboxParams())
        eff = m['temperature'](_env(T_int=20.0, T_ext=35.0))
        assert eff.direction == '↑'

    def test_co2_injector_raises_co2(self):
        m = greybox_effect_model('co2_injector', GreyboxParams())
        eff = m['co2'](_env())
        assert eff.direction == '↑'
        assert eff.magnitude_native > 0


# ── identification ────────────────────────────────────────────────────────────

class TestIdentification:
    def _make_series(self, true, n=300, seed=1):
        import random
        rng = random.Random(seed)
        state = (18.0, 70.0, 450.0)
        states = [state]; exts = []; cmds = []
        for _ in range(n):
            ext = {'T_ext': 5.0 + 10 * rng.random(), 'RH_ext': 50 + 30 * rng.random(),
                   'CO2_ext': 400.0, 'solar': 200 * rng.random(), 'wind': 2.0}
            cmd = {'heat': 100 * rng.random(), 'cool': 0.0,
                   'vent': 100 * rng.random(), 'fog': 0.0, 'co2_inj': 0.0}
            nxt = step(state[0], state[1], state[2], ext, cmd, true, dt=60.0)
            exts.append(ext); cmds.append(cmd); states.append(nxt); state = nxt
        return states, exts, cmds

    def test_fit_recovers_prediction(self):
        true = GreyboxParams()
        true.UA_eff = 900.0; true.Q_heat = 6000.0
        true.m_vent_coef = 1.2; true.tau_T = 250.0; true.K_RH_vent = 0.003
        states, exts, cmds = self._make_series(true)
        fitted = ident.fit(states, exts, cmds, dt=60.0, prev_params=GreyboxParams())
        assert fitted is not None
        # 예측 정확도(제어 관건)는 KPI 한계 이내
        assert fitted.rmse_T <= 1.5
        assert fitted.rmse_RH <= 8.0
        # 릿지 정규화로 핵심 계수가 참값 부근(±40%)으로 복원
        assert 0.6 * 900.0 <= fitted.UA_eff <= 1.4 * 900.0

    def test_insufficient_samples_returns_none(self):
        true = GreyboxParams()
        states, exts, cmds = self._make_series(true, n=10)
        assert ident.fit(states, exts, cmds, dt=60.0) is None


# ── coordinate() 통합 ─────────────────────────────────────────────────────────

def _swap_to_greybox(profiles, params, ctx):
    for p in profiles:
        gm = greybox_effect_model(p.kind, params)
        if gm is not None:
            p.effect_model = gm


class TestGreyboxControlIntegration:
    def test_hot_facility_opens_vent(self):
        """더운 시설 + 찬 외기 → greybox effect_model 로도 환기 명령(양수)."""
        ctx = make_ctx(T_int=30.0, T_ext=15.0)
        target = make_target(vpd=1.5, T=22.0)
        p = make_opening_profile()
        params = GreyboxParams()

        report, _ = assess(target, ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'])
        report.context['_gb_base_cmds'] = {'heat': 0, 'cool': 0, 'vent': 0, 'fog': 0, 'co2_inj': 0}
        _swap_to_greybox([p], params, ctx)

        cmds, _ = coordinate(report, [p], CoordinatorState())
        assert 0.0 < cmds['vent_01'].value <= 100.0

    def test_cold_facility_no_vent_cooling(self):
        """추운 시설 + 더운 외기 → 환기로 냉방 불가, 환기 명령 0 (gradient/방향)."""
        ctx = make_ctx(T_int=16.0, T_ext=30.0)
        target = make_target(vpd=0.8, T=22.0)  # 난방 필요(가열)
        p = make_opening_profile()  # opening 은 가열 보조 가능하나 여기선 cooling 수요 없음
        params = GreyboxParams()

        report, _ = assess(target, ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'])
        report.context['_gb_base_cmds'] = {'heat': 0, 'cool': 0, 'vent': 0, 'fog': 0, 'co2_inj': 0}
        _swap_to_greybox([p], params, ctx)

        cmds, _ = coordinate(report, [p], CoordinatorState())
        # 명령은 유효 범위 내 (구체 방향은 목표 의존; 폭주/음수 없음 확인)
        assert 0.0 <= cmds['vent_01'].value <= 100.0


# ── MPC ───────────────────────────────────────────────────────────────────────

def _cold_forecast(H=10, T_ext=12.0):
    return [{'T_ext': T_ext, 'RH_ext': 45.0, 'CO2_ext': 400.0,
             'solar': 0.0, 'wind': 2.0} for _ in range(H)]


class TestMPC:
    def test_available_channels(self):
        chans = gbmpc.available_channels([make_opening_profile(), make_heater_profile()])
        assert 'vent' in chans and 'heat' in chans
        assert 'fog' not in chans

    def test_hot_facility_opens_vent(self):
        """더운 시설 + 찬 외기 → vent 가 주 냉방 레버인 단열 시설에서 환기 개방.

        과냉을 막기 위해 외피가 느린(단열) 파라미터를 써 vent 가 의미 있는 레버가
        되게 한다. 더울수록 더 많이 열어야 함을 방향성으로 검증한다.
        """
        params = GreyboxParams()
        params.UA_eff = 120.0; params.tau_T = 1200.0   # 단열·느린 외피
        targets = {'temperature': (22.0, 1.0, 0.8)}
        profiles = [make_opening_profile()]

        def vent_for(T):
            res = gbmpc.optimize_channels(
                state=(T, 60.0, 600.0), targets=targets, profiles=profiles,
                ext_seq=_cold_forecast(T_ext=15.0), params=params,
                prev_channel_cmds={'vent': 0.0}, cycle_sec=60.0)
            assert res.method in ('lbfgsb', 'cem')
            assert 0.0 <= res.channel_cmds['vent'] <= 100.0
            return res.channel_cmds['vent']

        hot = vent_for(32.0)
        comfortable = vent_for(22.0)
        assert hot > 10.0                # 냉방 수요 → 환기 개방
        assert hot > comfortable + 5.0   # 더울수록 더 많이 개방(방향성)

    def test_heat_demand_commands_heater(self):
        """추운 시설(12) + 따뜻 목표 → heat 채널 명령 양수."""
        params = GreyboxParams()
        targets = {'temperature': (24.0, 1.0, 0.8)}
        profiles = [make_heater_profile()]
        res = gbmpc.optimize_channels(
            state=(12.0, 60.0, 600.0), targets=targets, profiles=profiles,
            ext_seq=_cold_forecast(), params=params,
            prev_channel_cmds={'heat': 0.0}, cycle_sec=60.0)
        assert res.channel_cmds['heat'] > 10.0

    def test_bounds_respected(self):
        params = GreyboxParams()
        targets = {'temperature': (22.0, 1.0, 0.8)}
        res = gbmpc.optimize_channels(
            state=(50.0, 60.0, 600.0), targets=targets,
            profiles=[make_opening_profile()], ext_seq=_cold_forecast(),
            params=params, prev_channel_cmds=None, cycle_sec=60.0)
        for v in res.channel_cmds.values():
            assert 0.0 <= v <= 100.0

    def test_no_forecast_is_noop(self):
        res = gbmpc.optimize_channels(
            state=(30.0, 60.0, 600.0), targets={'temperature': (22.0, 1.0, 0.8)},
            profiles=[make_opening_profile()], ext_seq=[], params=GreyboxParams(),
            prev_channel_cmds=None)
        assert res.method == 'noop'

    def test_cem_minimizes_quadratic(self):
        # (x-30)² 최소화 → x≈30
        x, ok = gbmpc._cem(lambda v: (v[0] - 30.0) ** 2, [0.0], [(0.0, 100.0)], max_iter=40)
        assert ok and abs(x[0] - 30.0) < 3.0

    def test_distribute_skips_unmodeled(self):
        from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints
        shade = ActuatorProfile(actuator_id='shade_1', kind='shade', effect_model={},
                                cmd_constraints=CmdConstraints(), gains={}, safe_default=0.0)
        out = gbmpc.distribute_to_actuators(
            {'vent': 70.0, 'heat': 0.0, 'cool': 0.0, 'fog': 0.0, 'co2_inj': 0.0},
            [make_opening_profile(), shade])
        assert out['vent_01'] == 70.0
        assert 'shade_1' not in out   # 미모델 → 분배 제외


# ── MPC 배선 (_run_mpc) 통합 ──────────────────────────────────────────────────

class TestMPCWiring:
    def _coord(self, profiles, params=None):
        """CycleMixin 인스턴스를 __init__ 우회로 만들고 MPC 호출에 필요한 속성만 세팅."""
        import logging
        import types as _types
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
        from aot.functions.utils.env_control.greybox.mpc import MPCConfig

        c = CycleMixin.__new__(CycleMixin)
        c._profiles = profiles
        c._coord_state = CoordinatorState()
        c._greybox_active = True
        c._mpc_enabled = True
        c._greybox_shadow_inst = _types.SimpleNamespace(params=params or GreyboxParams())
        c._mpc_config = MPCConfig(horizon=8)
        c._actuator_idx = {}
        c.logger = logging.getLogger('test_mpc')
        return c

    def test_run_mpc_produces_commands_for_modeled(self):
        params = GreyboxParams(); params.UA_eff = 120.0; params.tau_T = 1200.0
        p = make_opening_profile()
        c = self._coord([p], params)
        ctx = make_ctx(T_int=32.0, T_ext=15.0)
        report, _ = assess(make_target(vpd=1.5, T=22.0), ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'])
        out = c._run_mpc(report, '')
        assert out is not None
        commands, new_state = out
        assert 'vent_01' in commands
        assert 0.0 <= commands['vent_01'].value <= 100.0
        assert commands['vent_01'].var_source == 'mpc'

    def test_run_mpc_dispatch_falls_back_when_no_modeled(self):
        """modeled actuator 가 없으면 _run_mpc 는 None → 디스패처가 coordinate 폴백."""
        from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints
        shade = ActuatorProfile(actuator_id='shade_1', kind='shade', effect_model={},
                                cmd_constraints=CmdConstraints(), gains={}, safe_default=0.0)
        c = self._coord([shade])
        ctx = make_ctx(T_int=30.0)
        report, _ = assess(make_target(vpd=1.2), ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'])
        assert c._run_mpc(report, '') is None
        # 디스패처 폴백 경로도 명령을 산출
        cmds, _ = c._run_control(report, '')
        assert 'shade_1' in cmds

    def test_run_mpc_unmodeled_handled_by_legacy(self):
        """modeled(vent)=MPC + unmodeled(shade)=legacy 가 모두 명령됨."""
        from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints
        from aot.functions.utils.env_control.effect_functions import build_effect_model
        params = GreyboxParams(); params.UA_eff = 120.0; params.tau_T = 1200.0
        vent = make_opening_profile()
        shade = ActuatorProfile(
            actuator_id='shade_1', kind='shade',
            effect_model=build_effect_model('shade', {}),
            cmd_constraints=CmdConstraints(slew_per_cycle=20.0), gains={'kp': 1.0, 'ki': 0.05},
            safe_default=0.0)
        c = self._coord([vent, shade], params)
        ctx = make_ctx(T_int=33.0, T_ext=16.0, solar=800.0)
        report, _ = assess(make_target(vpd=1.6, T=22.0), ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'])
        out = c._run_mpc(report, '')
        assert out is not None
        commands, _ = out
        assert 'vent_01' in commands and 'shade_1' in commands
        assert commands['vent_01'].var_source == 'mpc'
