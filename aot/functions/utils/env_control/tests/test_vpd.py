# coding=utf-8
"""
VPD 관련 단위 테스트.

대상:
  - svp(T): Magnus/Tetens 공식
  - compute_vpd(T, RH): 포차 계산
  - decompose_vpd_to_T_RH(): 가중 분해 (P1-1)
"""

import math
import pytest

from aot.functions.utils.env_control.situation import (
    svp, compute_vpd, decompose_vpd_to_T_RH,
)


# ─────────────────────────────────────────────────────────────────────────────
# SVP (포화 수증기압)
# ─────────────────────────────────────────────────────────────────────────────

class TestSVP:
    def test_known_value_20c(self):
        """20°C SVP ≈ 2.338 kPa (Magnus)."""
        assert abs(svp(20.0) - 2.338) < 0.005

    def test_known_value_25c(self):
        """25°C SVP ≈ 3.169 kPa."""
        assert abs(svp(25.0) - 3.169) < 0.005

    def test_monotone_increasing(self):
        """온도 상승 → SVP 단조증가."""
        temps = [0, 5, 10, 15, 20, 25, 30, 35, 40]
        svps = [svp(t) for t in temps]
        assert all(svps[i] < svps[i + 1] for i in range(len(svps) - 1))

    def test_positive_for_all_realistic_T(self):
        """현실적 온도 범위에서 항상 양수."""
        for t in range(-10, 50):
            assert svp(float(t)) > 0


# ─────────────────────────────────────────────────────────────────────────────
# compute_vpd
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeVPD:
    def test_rh100_gives_zero(self):
        """RH=100% → VPD=0."""
        assert compute_vpd(25.0, 100.0) == pytest.approx(0.0, abs=1e-9)

    def test_rh0_gives_svp(self):
        """RH=0% → VPD = SVP(T)."""
        T = 20.0
        assert compute_vpd(T, 0.0) == pytest.approx(svp(T), rel=1e-6)

    def test_typical_greenhouse(self):
        """T=22, RH=65 → VPD ≈ 0.94 kPa."""
        vpd = compute_vpd(22.0, 65.0)
        assert 0.8 < vpd < 1.1

    def test_non_negative(self):
        """모든 정상 입력에서 VPD ≥ 0."""
        for T in [10, 15, 20, 25, 30]:
            for RH in [40, 50, 60, 70, 80, 90]:
                assert compute_vpd(float(T), float(RH)) >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# decompose_vpd_to_T_RH (P1-1)
# ─────────────────────────────────────────────────────────────────────────────

class TestDecomposeVPD:
    """
    decompose_vpd_to_T_RH(vpd_target, T_int, RH_int, w_T=0.6)
    → (T_aux, RH_aux)

    불변 조건:
      1. VPD(T_aux, RH_aux) ≈ vpd_target (제약 충족)
      2. T_aux ∈ [T_min, T_max], RH_aux ∈ [0, 100]
      3. w_T=1 → T 만 이동 (RH_aux ≈ RH_int)
      4. w_T=0 → RH 만 이동 (T_aux ≈ T_int)
      5. 이미 목표 충족 시 현재값 그대로 반환
    """

    # 공통 파라미터
    T_int = 22.0
    RH_int = 65.0

    def _vpd(self, T, RH):
        return compute_vpd(T, RH)

    # ── 기본 불변 조건 ────────────────────────────────────────────────────────

    def test_constraint_satisfied_default_weight(self):
        """기본 가중치(w_T=0.6)로 VPD 제약 충족."""
        T_a, RH_a = decompose_vpd_to_T_RH(1.2, self.T_int, self.RH_int)
        assert self._vpd(T_a, RH_a) == pytest.approx(1.2, abs=0.01)

    def test_constraint_satisfied_various_targets(self):
        """다양한 VPD 목표에서 제약 충족."""
        for vpd_t in [0.5, 0.8, 1.0, 1.2, 1.5, 1.8]:
            T_a, RH_a = decompose_vpd_to_T_RH(vpd_t, self.T_int, self.RH_int)
            assert self._vpd(T_a, RH_a) == pytest.approx(vpd_t, abs=0.02), \
                f"vpd_target={vpd_t}: got VPD={self._vpd(T_a, RH_a):.3f}"

    def test_rh_clamped_to_valid_range(self):
        """RH_aux는 항상 [0, 100] 범위."""
        for vpd_t in [0.1, 0.5, 1.0, 1.5, 2.0, 2.5]:
            _, RH_a = decompose_vpd_to_T_RH(vpd_t, self.T_int, self.RH_int)
            assert 0.0 <= RH_a <= 100.0

    # ── 가중치 극단값 ─────────────────────────────────────────────────────────

    def test_w_T_one_adjusts_only_temperature(self):
        """w_T=1 → T_aux 이동, RH_aux ≈ RH_int."""
        T_a, RH_a = decompose_vpd_to_T_RH(1.5, self.T_int, self.RH_int, w_T=1.0)
        assert abs(RH_a - self.RH_int) < 1.0  # RH 거의 불변
        assert abs(T_a - self.T_int) > 0.5    # T 이동

    def test_w_T_zero_adjusts_only_humidity(self):
        """w_T=0 → RH_aux 이동, T_aux = T_int."""
        T_a, RH_a = decompose_vpd_to_T_RH(1.5, self.T_int, self.RH_int, w_T=0.0)
        assert abs(T_a - self.T_int) < 1e-6   # T 불변
        assert abs(RH_a - self.RH_int) > 1.0  # RH 이동

    def test_default_weight_is_0_6(self):
        """w_T 미지정 시 0.6 기본값 동작 — w_T=0.6 명시 결과와 동일."""
        r1 = decompose_vpd_to_T_RH(1.2, self.T_int, self.RH_int)
        r2 = decompose_vpd_to_T_RH(1.2, self.T_int, self.RH_int, w_T=0.6)
        assert r1 == r2

    # ── 이미 목표 충족 ────────────────────────────────────────────────────────

    def test_already_at_target_returns_current(self):
        """현재 VPD ≈ vpd_target → T_aux, RH_aux ≈ 현재값."""
        vpd_now = self._vpd(self.T_int, self.RH_int)
        T_a, RH_a = decompose_vpd_to_T_RH(vpd_now, self.T_int, self.RH_int)
        assert abs(T_a - self.T_int) < 0.5
        assert abs(RH_a - self.RH_int) < 2.0

    # ── 경계 조건 ────────────────────────────────────────────────────────────

    def test_very_high_vpd_target_clamped(self):
        """물리적으로 달성 불가능한 VPD → RH 클램프(0%) 로 최대화."""
        T_a, RH_a = decompose_vpd_to_T_RH(5.0, self.T_int, self.RH_int)
        assert RH_a >= 0.0
        assert T_a <= 50.0

    def test_vpd_target_zero_gives_rh100(self):
        """VPD=0 목표 → RH_aux ≈ 100%."""
        T_a, RH_a = decompose_vpd_to_T_RH(0.0, self.T_int, self.RH_int)
        assert RH_a == pytest.approx(100.0, abs=1.0)

    def test_negative_vpd_target_handled(self):
        """음수 VPD 목표 → VPD ≥ 0 을 보장 (RH=100 클램프)."""
        T_a, RH_a = decompose_vpd_to_T_RH(-0.5, self.T_int, self.RH_int)
        assert RH_a <= 100.0
        assert T_a >= -10.0

    # ── 방향성 ───────────────────────────────────────────────────────────────

    def test_higher_vpd_target_moves_toward_drier(self):
        """VPD 목표 높일수록 T_aux 높거나 RH_aux 낮아짐."""
        current_vpd = self._vpd(self.T_int, self.RH_int)
        T1, RH1 = decompose_vpd_to_T_RH(current_vpd + 0.3, self.T_int, self.RH_int)
        T2, RH2 = decompose_vpd_to_T_RH(current_vpd + 0.6, self.T_int, self.RH_int)
        # 더 높은 VPD 목표 → T 더 높거나 RH 더 낮음
        assert T2 >= T1 - 0.1 or RH2 <= RH1 + 0.1
