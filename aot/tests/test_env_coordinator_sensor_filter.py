# coding=utf-8
"""온도·습도도 거른다 — 그리고 안전 판단은 원값을 본다.

VPD 만 거르면 T/RH 를 직접 쓰는 곳(온도 상한 항, 분무 습도 잠금)에 습도 눈금 1 %
디더가 그대로 들어간다. VPD 가 T/RH 계산값이면 걸러진 T/RH 로 다시 계산한다.
"""
from unittest.mock import MagicMock

import pytest

import aot.aot_flask.geo.facility_sensors as fs
from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.utils.env_control.situation import compute_vpd


def _coord(monkeypatch, readings, vpd_measured=False):
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c._sensors_resolved = [{'x': 1}]
    it = iter(readings)

    def fake(_sr, max_age=None):
        T, RH = next(it)
        out = {'T': T, 'RH': RH, 'T_max': T, 'T_min': T,
               'VPD': round(compute_vpd(T, RH), 3), 'vpd_measured': vpd_measured}
        return out
    monkeypatch.setattr(fs, 'compute_spatial_internal', fake)
    return c


def test_humidity_dither_is_smoothed(monkeypatch):
    c = _coord(monkeypatch, [(20.0, 85.0), (20.0, 86.0), (20.0, 85.0), (20.0, 86.0)])
    rh = [c._collect_internal()['RH'] for _ in range(4)]
    assert max(rh) - min(rh) < 0.5, '1 % 눈금 디더가 그대로 통과한다'


def test_real_transitions_snap_through(monkeypatch):
    c = _coord(monkeypatch, [(20.0, 85.0), (20.0, 70.0)])
    c._collect_internal()
    assert c._collect_internal()['RH'] == 70.0


def test_derived_vpd_is_recomputed_from_filtered_values(monkeypatch):
    c = _coord(monkeypatch, [(20.0, 85.0), (20.0, 86.0)])
    c._collect_internal()
    r = c._collect_internal()
    assert r['VPD'] == pytest.approx(compute_vpd(r['T'], r['RH']), abs=1e-3)


def test_raw_values_are_kept_for_safety(monkeypatch):
    c = _coord(monkeypatch, [(20.0, 85.0), (20.0, 86.0)])
    c._collect_internal()
    r = c._collect_internal()
    assert r['RH_raw'] == 86.0 and r['T_raw'] == 20.0
    env = c._build_gate_env(r, {})
    assert env['internal']['RH'] == 86.0, '게이트가 걸러진 값을 본다'
