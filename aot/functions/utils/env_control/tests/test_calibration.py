# coding=utf-8
"""
P3-3: RLS 자동 캘리브레이션 단위 테스트.

대상:
  - RLSCalibrator: 수렴, 경계 클램프, 외란 스킵, 상태 직렬화
  - ActuatorCalibrator: enabled=False 시 갱신 없음, 다변수 독립 추정
  - is_disturbed: 강우/강풍 판단
"""

import pytest

from aot.functions.utils.env_control.calibration import (
    RLSCalibrator,
    ActuatorCalibrator,
    is_disturbed,
)


# ─────────────────────────────────────────────────────────────────────────────
# RLSCalibrator
# ─────────────────────────────────────────────────────────────────────────────

class TestRLSCalibrator:
    def _make(self, k=2.0):
        return RLSCalibrator(k_default=k, lambda_=0.95)

    def test_initial_k_hat_equals_default(self):
        rls = self._make(2.0)
        assert rls.k_hat == pytest.approx(2.0)

    def test_update_applied_when_delta_cmd_sufficient(self):
        rls = self._make(2.0)
        rls.update(0.0, 100.0, delta_obs=2.0)
        assert rls.n_updates == 1

    def test_update_skipped_when_delta_cmd_small(self):
        rls = self._make(2.0)
        rls.update(50.0, 54.0, delta_obs=1.0)  # Δcmd=4% < 5%
        assert rls.n_updates == 0

    def test_update_skipped_when_disturbed(self):
        rls = self._make(2.0)
        rls.update(0.0, 100.0, delta_obs=2.0, disturbed=True)
        assert rls.n_updates == 0

    def test_k_hat_converges_toward_true_k(self):
        """true_k=3.0 — 충분히 반복하면 추정값이 근접."""
        true_k = 3.0
        rls = RLSCalibrator(k_default=2.0, lambda_=0.9)
        for _ in range(200):
            cmd = 60.0
            delta_obs = true_k * (cmd / 100.0)
            rls.update(0.0, cmd, delta_obs)
        assert rls.k_hat == pytest.approx(true_k, abs=0.2)

    def test_k_hat_clamped_at_upper_bound(self):
        """아무리 큰 관측값이 들어와도 K_max 이상이 되지 않는다."""
        rls = self._make(2.0)  # k_max = 10.0
        for _ in range(500):
            rls.update(0.0, 100.0, delta_obs=9999.0)
        assert rls.k_hat <= rls.k_max + 1e-9

    def test_k_hat_clamped_at_lower_bound(self):
        rls = self._make(2.0)  # k_min = 0.2
        for _ in range(500):
            rls.update(0.0, 100.0, delta_obs=-9999.0)
        assert rls.k_hat >= rls.k_min - 1e-9

    def test_state_dict_round_trip(self):
        rls = self._make(2.0)
        rls.update(0.0, 100.0, delta_obs=2.5)
        state = rls.state_dict()
        rls2 = RLSCalibrator.from_state(state)
        assert rls2.k_hat   == pytest.approx(rls.k_hat)
        assert rls2._P      == pytest.approx(rls._P)
        assert rls2.n_updates == rls.n_updates

    def test_variance_decreases_with_updates(self):
        rls = self._make(2.0)
        p0 = rls.variance
        for _ in range(30):
            rls.update(0.0, 100.0, delta_obs=2.0)
        assert rls.variance < p0

    def test_is_converged_false_initially(self):
        rls = self._make(2.0)
        assert not rls.is_converged(threshold=0.01)

    def test_is_converged_true_after_many_updates(self):
        """망각 RLS 의 P 정상 하한 = (1-λ)/x² = 0.1/0.64 ≈ 0.156.
        따라서 threshold 는 0.2 수준으로 설정해야 수렴 판정 가능."""
        rls = RLSCalibrator(k_default=2.0, lambda_=0.9)
        for _ in range(500):
            rls.update(0.0, 80.0, delta_obs=2.0 * 0.8)
        assert rls.is_converged(threshold=0.2)


# ─────────────────────────────────────────────────────────────────────────────
# ActuatorCalibrator
# ─────────────────────────────────────────────────────────────────────────────

class TestActuatorCalibrator:
    def test_disabled_no_update(self):
        cal = ActuatorCalibrator('a1', 'heater', enabled=False)
        result = cal.update('temperature', 0.0, 100.0, delta_obs=2.0)
        assert not result

    def test_enabled_update_applied(self):
        cal = ActuatorCalibrator('a1', 'heater', enabled=True)
        result = cal.update('temperature', 0.0, 100.0, delta_obs=2.0)
        assert result

    def test_unknown_var_no_update(self):
        cal = ActuatorCalibrator('a1', 'heater', enabled=True)
        result = cal.update('light', 0.0, 100.0, delta_obs=100.0)
        assert not result

    def test_independent_variables(self):
        """temperature 와 humidity 추정이 독립적으로 진행."""
        cal = ActuatorCalibrator('a1', 'heater', enabled=True)
        for _ in range(50):
            cal.update('temperature', 0.0, 100.0, delta_obs=3.0)
        k_t = cal.k_hat('temperature')
        k_rh = cal.k_hat('humidity')
        # temperature 만 갱신했으므로 humidity 는 default 에 가까움
        assert k_rh == pytest.approx(1.5, abs=0.01)  # K_HEATER_RH default
        assert k_t != pytest.approx(2.0, abs=0.01)   # temperature 는 변경됨

    def test_state_round_trip(self):
        cal = ActuatorCalibrator('a1', 'fogger', enabled=True)
        cal.update('humidity', 0.0, 100.0, delta_obs=3.0)
        state = cal.state_dict()
        cal2 = ActuatorCalibrator.from_state(state)
        assert cal2.k_hat('humidity') == pytest.approx(cal.k_hat('humidity'))


# ─────────────────────────────────────────────────────────────────────────────
# is_disturbed
# ─────────────────────────────────────────────────────────────────────────────

class TestIsDisturbed:
    def test_normal_not_disturbed(self):
        assert not is_disturbed({'rain': 0.0, 'wind': 3.0})

    def test_rain_disturbed(self):
        assert is_disturbed({'rain': 1.0, 'wind': 0.0})

    def test_high_wind_disturbed(self):
        assert is_disturbed({'rain': 0.0, 'wind': 6.0})

    def test_custom_wind_threshold(self):
        assert not is_disturbed({'rain': 0.0, 'wind': 6.0}, wind_threshold=10.0)

    def test_missing_keys_not_disturbed(self):
        assert not is_disturbed({})
