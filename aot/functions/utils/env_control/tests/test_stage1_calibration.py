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
    """명령이 한 번 바뀌고 lag 가 지나면, 예측이 있으면 갱신된다."""
    cal = ActuatorCalibrator('v1', 'opening', enabled=True)
    for cmd, T in _simulate(cal, rate=-0.2, theta=1.0, steps=[20, 60]):
        pass
    assert cal._rls['temperature'].n_updates > 0


def _simulate(cal, rate, theta, steps, drift=0.0, probe=False, steady=True,
              var='temperature', start=24.0, hold=None):
    """센서 = 이전 사이클 명령 × θ × 예측 속도 + 드리프트. 명령을 steps 순으로 번갈아 든다."""
    hold = hold or cal._lag + 2
    s, prev_cmd, out = start, steps[0], []
    for i in range(len(steps) * hold * 30):
        cmd = steps[(i // hold) % len(steps)]
        s += theta * (prev_cmd / 100.0) * rate + drift
        cal.push_cycle(cmd, {var: s}, True, 1.0, probe, {var: rate}, steady)
        prev_cmd = cmd
        out.append((cmd, s))
    return out


def test_scale_converges_for_a_lowering_device():
    """내리는 장치(예측 음수)도 θ 가 하한에 붙지 않고 실제 배율로 수렴한다."""
    cal = ActuatorCalibrator('c1', 'cooler', enabled=True)
    _simulate(cal, rate=-0.3, theta=0.5, steps=[10, 70])
    assert cal.k_hat('temperature') == pytest.approx(0.5, abs=0.05)


def test_drift_before_the_change_is_removed():
    """이미 진행 중이던 흐름(드리프트)은 장치 몫으로 치지 않는다."""
    cal = ActuatorCalibrator('h1', 'heater', enabled=True)
    _simulate(cal, rate=0.4, theta=1.5, steps=[10, 60], drift=0.05)
    assert cal.k_hat('temperature') == pytest.approx(1.5, abs=0.1)


def test_probe_weight_does_not_bias_the_estimate():
    """탐색 가중치는 갱신의 무게다 — 관측값을 2배로 만들지 않는다."""
    a = ActuatorCalibrator('a', 'heater', enabled=True)
    b = ActuatorCalibrator('b', 'heater', enabled=True)
    _simulate(a, rate=0.4, theta=0.8, steps=[10, 60], probe=False)
    _simulate(b, rate=0.4, theta=0.8, steps=[10, 60], probe=True)
    assert b.k_hat('temperature') == pytest.approx(0.8, abs=0.05)
    assert b.k_hat('temperature') == pytest.approx(a.k_hat('temperature'), abs=0.05)


def test_no_learning_while_other_devices_move():
    """다른 장치가 같이 움직이면 누구 몫인지 가를 수 없다 — 배우지 않는다."""
    cal = ActuatorCalibrator('h1', 'heater', enabled=True)
    _simulate(cal, rate=0.4, theta=3.0, steps=[10, 60], steady=False)
    assert cal._rls['temperature'].n_updates == 0


def test_no_learning_without_a_prediction():
    cal = ActuatorCalibrator('h1', 'heater', enabled=True)
    for i in range(30):
        cal.push_cycle(10 if (i // 7) % 2 else 60, {'temperature': 20 + i * 0.1}, True, 1.0)
    assert cal._rls['temperature'].n_updates == 0


def test_old_k_model_state_is_discarded():
    """옛 상태의 k_hat 은 단위가 다른 K 다 — θ 자리에 올리면 모델을 수십 배로 키운다."""
    old = {'actuator_id': 'h1', 'kind': 'heater', 'enabled': True,
           'rls': {'temperature': {'k_hat': 2.4, 'P': 0.01, 'n_updates': 40,
                                   'k_default': 2.0}}}
    cal = ActuatorCalibrator.from_state(old)
    assert cal.k_hat('temperature') == 1.0
    assert cal._rls['temperature'].n_updates == 0


def test_effect_function_multiplies_its_k_by_the_scale():
    from types import SimpleNamespace
    from aot.functions.utils.env_control.effect_functions import (
        heater_temp_effect, co2_injector_co2_effect)
    base = heater_temp_effect({}, 50.0, SimpleNamespace())
    scaled = heater_temp_effect({}, 50.0, SimpleNamespace(calibrated_K={'temperature': 2.0}))
    assert scaled.magnitude_native == pytest.approx(2 * base.magnitude_native)
    c0 = co2_injector_co2_effect({}, 50.0, SimpleNamespace())
    c1 = co2_injector_co2_effect({}, 50.0, SimpleNamespace(calibrated_K={'co2': 0.5}))
    assert c1.magnitude_native == pytest.approx(0.5 * c0.magnitude_native)


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
