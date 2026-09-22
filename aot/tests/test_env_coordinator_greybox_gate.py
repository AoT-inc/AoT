# coding=utf-8
"""greybox 제어 게이트 — 같은 모델 판 · 같은 KPI 기준의 통과만 인정한다.

옛 기준(1스텝 오차)의 통과 기록은 "변화 없음" 수준의 모델도 받았고, 옛 모델 판의
기록은 새 물리식을 보증하지 않는다.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.custom_functions.env_coordinator_impl import _cycle_mixin as cm
from aot.functions.utils.env_control.greybox.params import GreyboxParams


def _coord(state, live_pass=False):
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c._read_calibration_state = lambda: state
    p = GreyboxParams(n_updates=3, rmse_T=0.5, rmse_RH=3.0)
    c._greybox_shadow_inst = SimpleNamespace(params=p, kpi_passed=lambda: live_pass)
    return c


def test_live_pass_is_enough():
    assert _coord({}, live_pass=True)._greybox_control_gate_ok()


def test_old_basis_record_is_rejected():
    st = {'greybox_kpi_passed': True, 'greybox_kpi_model_version': 2}
    assert not _coord(st)._greybox_control_gate_ok()


def test_old_model_record_is_rejected():
    st = {'greybox_kpi_passed': True, 'greybox_kpi_basis': cm._KPI_BASIS}
    assert not _coord(st)._greybox_control_gate_ok()


def test_matching_record_is_accepted():
    st = {'greybox_kpi_passed': True,
          'greybox_kpi_model_version': GreyboxParams().model_version,
          'greybox_kpi_basis': cm._KPI_BASIS}
    assert _coord(st)._greybox_control_gate_ok()


def test_old_model_params_never_pass():
    c = _coord({}, live_pass=True)
    c._greybox_shadow_inst.params.model_version = 1
    assert not c._greybox_control_gate_ok()
