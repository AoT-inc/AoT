# coding=utf-8
"""Stage 1 캘리브레이션·능동탐색 단위 테스트."""
import pytest
from aot.functions.utils.env_control.calibration import (
    RLSCalibrator, ActuatorCalibrator, CalibrationRegistry,
)
from aot.functions.utils.env_control.active_probe import ActiveProbeScheduler
from aot.functions.utils.env_control.data_hygiene import DataHygieneChecker


# ── RLS 수렴 테스트 ────────────────────────────────────────────────────────────

def test_rls_converges_to_known_k():
    """합성 데이터(known K=3.0)로 RLS 가 수렴하는지 검증."""
    rls = RLSCalibrator(k_default=2.0, lambda_=0.95)
    true_k = 3.0
    import random
    random.seed(42)
    for _ in range(100):
        x = random.uniform(20.0, 80.0) / 100.0
        noise = random.gauss(0, 0.05)
        delta = true_k * x + noise
        rls.update(0.0, x * 100, delta, disturbed=False)
    assert abs(rls.k_hat - true_k) < 0.5, f'expected ~{true_k}, got {rls.k_hat:.3f}'


def test_rls_state_roundtrip():
    rls = RLSCalibrator(k_default=1.0)
    rls.update(0.0, 50.0, 0.4, disturbed=False)
    s = rls.state_dict()
    rls2 = RLSCalibrator.from_state(s)
    assert abs(rls2.k_hat - rls.k_hat) < 1e-9


def test_rls_disturbed_skipped():
    rls = RLSCalibrator(k_default=1.0)
    k_before = rls.k_hat
    updated = rls.update(0.0, 50.0, 999.0, disturbed=True)
    assert not updated
    assert rls.k_hat == k_before


# ── ActuatorCalibrator lag 버퍼 테스트 ────────────────────────────────────────

def test_actuator_calibrator_lag_skip():
    """lag 사이클 미달 시 RLS 갱신 안 됨."""
    cal = ActuatorCalibrator('v1', 'heater', enabled=True)
    lag = cal._lag
    # lag 미만 사이클 push
    for i in range(lag - 1):
        cal.push_cycle(50.0, {'temperature': 22.0}, True, 1.0)
    rls = cal._rls.get('temperature')
    assert rls.n_updates == 0


def test_actuator_calibrator_push_updates():
    """충분한 사이클 push 후 n_updates 증가."""
    cal = ActuatorCalibrator('v1', 'opening', enabled=True)
    lag = cal._lag
    for i in range(lag + 3):
        cal.push_cycle(50.0 + i, {'temperature': 24.0 - i * 0.1,
                                   'humidity':    65.0}, True, 1.0)
    rls = cal._rls.get('temperature')
    assert rls.n_updates > 0


# ── CalibrationRegistry ───────────────────────────────────────────────────────

def test_registry_k_hat_none_before_convergence():
    reg = CalibrationRegistry(enabled=True)
    # n_updates < 5 이면 None 반환
    for _ in range(3):
        reg.push_cycle('h1', 'heater', 80.0, {'temperature': 22.0}, True, 1.0)
    assert reg.k_hat('h1', 'temperature') is None


def test_registry_disabled_skips():
    reg = CalibrationRegistry(enabled=False)
    for _ in range(20):
        reg.push_cycle('h1', 'heater', 80.0, {'temperature': 22.0}, True, 1.0)
    assert 'h1' not in reg._cals


def test_registry_state_roundtrip():
    reg = CalibrationRegistry(enabled=True)
    for i in range(10):
        reg.push_cycle('v1', 'opening', 40.0 + i,
                       {'temperature': 25.0 - i * 0.1}, True, 1.0)
    sd = reg.state_dict()
    reg2 = CalibrationRegistry.from_state(sd)
    assert reg2.enabled
    assert 'v1' in reg2._cals


# ── DataHygieneChecker ────────────────────────────────────────────────────────

def test_hygiene_wind_dirty():
    checker = DataHygieneChecker(wind_threshold=5.0)
    clean = checker.check({'wind': 8.0, 'rain': 0.0, 'solar': 300.0},
                          {'T': 24.0}, {})
    assert not clean


def test_hygiene_rain_dirty():
    checker = DataHygieneChecker()
    clean = checker.check({'wind': 2.0, 'rain': 1.0, 'solar': 300.0},
                          {'T': 24.0}, {})
    assert not clean


def test_hygiene_solar_jump_dirty():
    checker = DataHygieneChecker()
    checker.check({'wind': 1.0, 'rain': 0.0, 'solar': 400.0}, {'T': 24.0}, {})
    # 1 사이클 뒤 solar 급변 (클라우드 패스)
    clean = checker.check({'wind': 1.0, 'rain': 0.0, 'solar': 600.0}, {'T': 24.0}, {})
    assert not clean


def test_hygiene_normal_clean():
    checker = DataHygieneChecker()
    for _ in range(5):
        checker.check({'wind': 1.0, 'rain': 0.0, 'solar': 400.0}, {'T': 24.0}, {})
    clean = checker.check({'wind': 1.0, 'rain': 0.0, 'solar': 405.0}, {'T': 24.1}, {})
    assert clean


# ── ActiveProbeScheduler ──────────────────────────────────────────────────────

class _FakeSituation:
    deviation_native = {'temperature': 0.1}
    target = {}


def test_probe_disabled():
    sched = ActiveProbeScheduler(enabled=False)
    cmds, is_probe = sched.step({'v1': 50.0}, [], _FakeSituation())
    assert not is_probe
    assert cmds == {'v1': 50.0}


def test_probe_gate_blocked():
    sched = ActiveProbeScheduler(interval_sec=0, enabled=True)
    cmds, is_probe = sched.step({'v1': 50.0}, [], _FakeSituation(),
                                gate_triggered=True)
    assert not is_probe
