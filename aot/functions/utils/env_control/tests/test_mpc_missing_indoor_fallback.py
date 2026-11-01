# coding=utf-8
"""실내 측정이 없는 사이클은 MPC/greybox 대신 레거시로 (B4 회귀).

`_run_mpc` 는 없는 실내값을 20 °C · 60 % · 400 ppm 으로 메워 최적화했다. 레거시
PI 는 잴 수 없는 축의 장치를 제자리에 둔다(coordinator 2.8, 근거 21). 엔진 선택
이음매(`_run_control`)에서 MPC 가 쓸 실내값이 없으면 레거시로 보낸다.
"""
import logging
import types as _types

import pytest

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
from aot.functions.utils.env_control.coordinator import CoordinatorState
from aot.functions.utils.env_control.greybox.mpc import MPCConfig
from aot.functions.utils.env_control.greybox.params import GreyboxParams
from aot.functions.utils.env_control.situation import assess

from .conftest import make_ctx, make_opening_profile, make_target


def _coord(profiles):
    c = CycleMixin.__new__(CycleMixin)
    c._profiles = profiles
    c._coord_state = CoordinatorState()
    c._greybox_active = True
    c._mpc_enabled = True
    c._greybox_shadow_inst = _types.SimpleNamespace(params=GreyboxParams())
    c._mpc_config = MPCConfig(horizon=8)
    c._actuator_idx = {}
    c.logger = logging.getLogger('test_mpc_missing_indoor')
    return c


def _report(target, **internal_overrides):
    ctx = make_ctx(T_int=32.0, T_ext=15.0)
    internal = dict(ctx['internal'])
    internal.update(internal_overrides)
    report, _ = assess(target, internal, ctx['external'],
                       cycle_sec=60.0, now_ts=ctx['now_ts'])
    return report


def _spy_mpc(c, monkeypatch):
    calls = []
    real = c._run_mpc

    def spy(*a, **kw):
        calls.append(1)
        return real(*a, **kw)
    monkeypatch.setattr(c, '_run_mpc', spy)
    return calls


def test_baseline_with_full_indoor_runs_mpc(monkeypatch):
    c = _coord([make_opening_profile()])
    calls = _spy_mpc(c, monkeypatch)
    cmds, _ = c._run_control(_report(make_target(vpd=1.5, T=22.0)), '')
    assert calls and c._last_control_engine == 'mpc'
    assert c._last_control_fallback is None
    assert cmds['vent_01'].var_source == 'mpc'


@pytest.mark.parametrize('missing,reason', [
    ({'T': None, 'T_max': None, 'T_min': None}, 'indoor_missing:T'),
    ({'RH': None}, 'indoor_missing:RH'),
])
def test_missing_T_or_RH_skips_mpc_and_uses_legacy(monkeypatch, missing, reason):
    p = make_opening_profile()
    p._legacy_effect_model = p.effect_model
    p.effect_model = {'temperature': lambda *a, **k: None}      # greybox 어댑터 대역
    c = _coord([p])
    calls = _spy_mpc(c, monkeypatch)
    report = _report(make_target(vpd=1.5, T=22.0), **missing)
    cmds, _ = c._run_control(report, '')
    assert not calls, 'MPC 가 지어낸 실내 상태로 돌았다'
    assert c._last_control_engine == 'legacy'
    assert c._last_control_fallback.startswith(reason.split(',')[0])
    assert p.effect_model is p._legacy_effect_model            # 이 사이클은 레거시 효과 모델
    assert all(getattr(v, 'var_source', None) != 'mpc' for v in cmds.values())


def test_missing_both_records_both_axes():
    c = _coord([make_opening_profile()])
    report = _report(make_target(vpd=1.5, T=22.0),
                     T=None, T_max=None, T_min=None, RH=None)
    c._run_control(report, '')
    assert c._last_control_fallback == 'indoor_missing:T,RH'


def test_fallback_flag_clears_when_indoor_returns(monkeypatch):
    c = _coord([make_opening_profile()])
    c._run_control(_report(make_target(vpd=1.5, T=22.0), RH=None), '')
    assert c._last_control_fallback
    c._run_control(_report(make_target(vpd=1.5, T=22.0)), '')
    assert c._last_control_fallback is None and c._last_control_engine == 'mpc'


def test_co2_only_matters_when_there_is_a_co2_target(monkeypatch):
    """CO₂ 센서가 없는 대부분의 시설이 MPC 를 잃으면 안 된다."""
    c = _coord([make_opening_profile()])
    calls = _spy_mpc(c, monkeypatch)
    c._run_control(_report(make_target(vpd=1.5, T=22.0), CO2=None), '')
    assert calls and c._last_control_engine == 'mpc'

    calls.clear()
    c._run_control(_report(make_target(vpd=1.5, T=22.0, co2=800.0), CO2=None), '')
    assert not calls and c._last_control_engine == 'legacy'
    assert c._last_control_fallback == 'indoor_missing:CO2'


def test_fallback_is_logged_once_not_every_cycle(caplog):
    c = _coord([make_opening_profile()])
    report = _report(make_target(vpd=1.5, T=22.0), RH=None)
    with caplog.at_level(logging.WARNING, logger='test_mpc_missing_indoor'):
        for _ in range(5):
            c._run_control(report, '')
    assert sum('MPC/greybox' in r.getMessage() for r in caplog.records) == 1
