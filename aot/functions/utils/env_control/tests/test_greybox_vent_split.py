# coding=utf-8
"""
MPC 보강 E 단계(2026-09-22) — 환기 채널 세분과 보온커튼.

- vent 채널 = 시설 환기 능력 대비 풍량 비율(창 면적·팬 정격·팬 압력 유효도)
- 채널 → 장치 분배는 그 역: 형태 우선순위(더우면 천창부터), 창·팬 중 큰 쪽 하나
- 보온커튼 = 외피 열손실·일사 투과 배율(모델 입력)
"""

import pytest

from aot.functions.utils.env_control.greybox import channels as ch
from aot.functions.utils.env_control.greybox.channels import (
    aggregate_cmds_by_kind, distribute_vent, vent_capacities,
    vent_channel_value, vent_reachable_pct, vent_shares,
)
from aot.functions.utils.env_control.greybox.model import step
from aot.functions.utils.env_control.greybox.params import GreyboxParams
from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints


def _opening(aid, area, form=None):
    return ActuatorProfile(actuator_id=aid, kind='opening', effect_model={},
                           cmd_constraints=CmdConstraints(), gains={},
                           safe_default=0.0, area_m2=area, vent_form=form)


def _fan(aid, m3h):
    return ActuatorProfile(actuator_id=aid, kind='exhaust_fan', effect_model={},
                           cmd_constraints=CmdConstraints(), gains={},
                           safe_default=0.0, capacity_meta={'rated_m3h': m3h})


# 천창 4 m²(2 m³/s) + 측창 2개 각 2 m²(각 1 m³/s) = 창 4 m³/s
CAPS = vent_capacities([_opening('ridge', 4.0, 'ridge'),
                        _opening('side_a', 2.0, 'side'),
                        _opening('side_b', 2.0, 'side')])


class TestCapacities:
    def test_면적과_정격에서(self):
        caps = vent_capacities([_opening('o', 4.0), _fan('f', 7200.0)])
        assert caps['o'].m3s == pytest.approx(2.0) and not caps['o'].is_fan
        assert caps['f'].m3s == pytest.approx(2.0) and caps['f'].is_fan

    def test_모르면_기본값(self):
        caps = vent_capacities([_opening('o', None), _fan('f', None)])
        assert caps['o'].m3s == pytest.approx(ch.DEFAULT_OPENING_M2 * ch.VENT_M3S_PER_M2)
        assert caps['f'].m3s == pytest.approx(ch.DEFAULT_FAN_M3H / 3600.0)

    def test_환기_아닌_장치는_없다(self):
        heater = ActuatorProfile(actuator_id='h', kind='heater', effect_model={},
                                 cmd_constraints=CmdConstraints(), gains={})
        assert vent_capacities([heater]) == {}


class TestChannelValue:
    def test_전부_같은_개도면_그_개도(self):
        """예전(최댓값)과 같은 답 — PI 가 늘 쓰던 모양에서는 학습 입력이 그대로다."""
        v = vent_channel_value({'ridge': 60.0, 'side_a': 60.0, 'side_b': 60.0}, CAPS)
        assert v == pytest.approx(60.0)

    def test_천창만_다_열면_제_몫(self):
        v = vent_channel_value({'ridge': 100.0}, CAPS)
        assert v == pytest.approx(50.0)     # 2 / 4 m³/s

    def test_창이_열리면_팬은_무력(self):
        caps = vent_capacities([_opening('o', 4.0), _fan('f', 7200.0)])
        closed = vent_channel_value({'o': 0.0, 'f': 100.0}, caps)
        opened = vent_channel_value({'o': 50.0, 'f': 100.0}, caps)
        assert closed == pytest.approx(100.0)
        assert opened == pytest.approx(50.0)  # 창 몫만 — 팬 압력 0

    def test_집계는_caps_가_있을_때만_바뀐다(self):
        cmds = {'ridge': 100.0, 'side_a': 0.0}
        kinds = {'ridge': 'opening', 'side_a': 'opening'}
        assert aggregate_cmds_by_kind(cmds, kinds)['vent'] == 100.0
        assert aggregate_cmds_by_kind(cmds, kinds, CAPS)['vent'] == pytest.approx(50.0)

    def test_보온커튼은_입력으로_집계(self):
        out = aggregate_cmds_by_kind({'c1': 20.0, 'c2': 40.0},
                                     {'c1': 'curtain', 'c2': 'curtain'})
        assert out['curtain'] == pytest.approx(30.0)


class TestDistribute:
    @pytest.mark.parametrize('u', [0.0, 10.0, 35.0, 50.0, 80.0, 100.0])
    @pytest.mark.parametrize('hot', [True, False])
    def test_집계의_역이다(self, u, hot):
        a = distribute_vent(u, CAPS, indoor_hotter=hot)
        assert vent_channel_value(a, CAPS) == pytest.approx(u, abs=1e-6)
        assert all(0.0 <= v <= 100.0 for v in a.values())

    def test_실내가_더우면_천창부터(self):
        a = distribute_vent(40.0, CAPS, indoor_hotter=True)
        assert a['ridge'] == pytest.approx(80.0)
        assert a['side_a'] == 0.0 and a['side_b'] == 0.0

    def test_실외가_더_더우면_측창부터(self):
        a = distribute_vent(40.0, CAPS, indoor_hotter=False)
        assert a['ridge'] == 0.0
        assert a['side_a'] == pytest.approx(80.0) == a['side_b']

    def test_천창이_다_차면_측창이_이어받는다(self):
        a = distribute_vent(75.0, CAPS, indoor_hotter=True)
        assert a['ridge'] == 100.0
        assert a['side_a'] == pytest.approx(50.0) == a['side_b']

    def test_형태를_모르면_같은_개도(self):
        caps = vent_capacities([_opening('a', 2.0), _opening('b', 6.0)])
        a = distribute_vent(30.0, caps, indoor_hotter=True)
        assert a['a'] == pytest.approx(30.0) == a['b']

    def test_막힌_장치는_0_나머지가_대신(self):
        a = distribute_vent(40.0, CAPS, indoor_hotter=True, blocked={'ridge'})
        assert a['ridge'] == 0.0
        assert a['side_a'] == pytest.approx(80.0)
        assert vent_reachable_pct(CAPS, {'ridge'}) == pytest.approx(50.0)
        assert vent_reachable_pct(CAPS) == pytest.approx(100.0)

    def test_팬이_크면_팬으로_내고_창은_닫는다(self):
        caps = vent_capacities([_opening('o', 1.0), _fan('f1', 7200.0), _fan('f2', 7200.0)])
        a = distribute_vent(50.0, caps, indoor_hotter=True)
        assert a['o'] == 0.0
        assert a['f1'] == pytest.approx(50.0) == a['f2']
        assert vent_channel_value(a, caps) == pytest.approx(50.0)

    def test_창이_크면_팬은_쓰지_않는다(self):
        caps = vent_capacities([_opening('o', 10.0), _fan('f', 3600.0)])
        a = distribute_vent(50.0, caps, indoor_hotter=True)
        assert a['f'] == 0.0 and a['o'] == pytest.approx(50.0)

    def test_몫(self):
        s = vent_shares(CAPS)
        assert s['ridge'] == pytest.approx(0.5) and s['side_a'] == pytest.approx(0.25)


class TestCurtain:
    def _night(self, curtain):
        p = GreyboxParams()
        ext = {'T_ext': 0.0, 'RH_ext': 80.0, 'CO2_ext': 400.0, 'solar': 0.0, 'wind': 1.0}
        return step(15.0, 70.0, 500.0, ext, {'curtain': curtain}, p, 600.0)[0]

    def test_닫으면_밤에_덜_식는다(self):
        assert self._night(0.0) > self._night(100.0)

    def test_없으면_걷힌_것과_같다(self):
        p = GreyboxParams()
        ext = {'T_ext': 0.0, 'RH_ext': 80.0, 'CO2_ext': 400.0, 'solar': 0.0, 'wind': 1.0}
        assert step(15.0, 70.0, 500.0, ext, {}, p, 600.0) == \
            step(15.0, 70.0, 500.0, ext, {'curtain': 100.0}, p, 600.0)

    def test_닫으면_일사도_줄인다(self):
        p = GreyboxParams()
        p.curtain_ua_saving = 0.0   # 외피 효과를 빼고 일사 차이만 본다
        ext = {'T_ext': 20.0, 'RH_ext': 60.0, 'CO2_ext': 400.0, 'solar': 800.0, 'wind': 0.0}
        t_open = step(20.0, 60.0, 400.0, ext, {'curtain': 100.0}, p, 60.0)[0]
        t_shut = step(20.0, 60.0, 400.0, ext, {'curtain': 0.0}, p, 60.0)[0]
        assert t_open > t_shut

    def test_시설값을_읽는다(self):
        p = GreyboxParams.from_capacity_meta({'curtain_u_saving': 0.5,
                                              'curtain_transmittance': 0.6})
        assert p.curtain_ua_saving == 0.5 and p.tau_curtain == 0.6
        again = GreyboxParams.from_dict(p.to_dict())
        assert again.curtain_ua_saving == 0.5 and again.tau_curtain == 0.6


class TestAdapterShare:
    def test_창_하나는_제_몫만_주장한다(self):
        from aot.functions.utils.env_control.greybox.effect_adapter import greybox_effect_model
        p = GreyboxParams()
        fn = greybox_effect_model('opening', p)['temperature']
        env = {'T_int': 30.0, 'RH_int': 60.0, 'CO2_int': 500.0, 'T_ext': 15.0,
               'RH_ext': 50.0, 'CO2_ext': 400.0, 'solar': 0.0, 'wind': 1.0,
               'cycle_sec': 60.0}
        full = fn(env, 100.0, _opening('ridge', 4.0, 'ridge')).magnitude_native
        env['_gb_vent_share'] = vent_shares(CAPS)
        part = fn(env, 100.0, _opening('side_a', 2.0, 'side')).magnitude_native
        assert part == pytest.approx(full * 0.25)


class TestRunMpc:
    def _coord(self, profiles):
        import logging
        import types as _types
        from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
        from aot.functions.utils.env_control.coordinator import CoordinatorState
        from aot.functions.utils.env_control.greybox.mpc import MPCConfig
        p = GreyboxParams()
        p.UA_eff = 120.0
        p.tau_T = 1200.0
        c = CycleMixin.__new__(CycleMixin)
        c._profiles = profiles
        c._coord_state = CoordinatorState()
        c._greybox_active = True
        c._mpc_enabled = True
        c._greybox_shadow_inst = _types.SimpleNamespace(params=p)
        c._mpc_config = MPCConfig(horizon=8)
        c._actuator_idx = {}
        c.logger = logging.getLogger('test_vent_split')
        return c

    def _report(self, **flags):
        from aot.functions.utils.env_control.situation import assess
        from .conftest import make_ctx, make_target
        ctx = make_ctx(T_int=32.0, T_ext=15.0, RH_ext=50.0)
        r, _ = assess(make_target(vpd=1.2, T=22.0), ctx['internal'], ctx['external'],
                      cycle_sec=60.0, now_ts=ctx['now_ts'])
        r.context.update(flags)
        return r

    def test_더운_실내는_천창을_먼저_연다(self):
        from .conftest import make_opening_profile
        from aot.functions.utils.env_control.effect_functions import (
            opening_temp_effect, opening_humid_effect)
        profs = []
        for aid, form in (('ridge', 'ridge'), ('side', 'side')):
            p = make_opening_profile(actuator_id=aid)
            p.vent_form = form
            p.area_m2 = 4.0
            profs.append(p)
        assert opening_temp_effect and opening_humid_effect
        c = self._coord(profs)
        cmds, _ = c._run_mpc(self._report(), 'u')
        r, s = cmds['ridge'].control_value(), cmds['side'].control_value()
        assert r > 0.0 and r >= s
