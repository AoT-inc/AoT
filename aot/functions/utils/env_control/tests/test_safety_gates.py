# coding=utf-8
"""
safety_gates.py 단위 테스트.

대상:
  - 강우(rain) 게이트 발동
  - 강풍(wind) 게이트 발동
  - 외부 센서 만료(ext_expired) 게이트 발동
  - 풍향 차등 폐쇄 (G4 — partial gate)
  - 정상 조건에서 게이트 미발동
"""

import time
import pytest

from aot.functions.utils.env_control.safety_gates import (
    SafetyPreGate, PreGateConfig,
    GATE_BIT_RAIN, GATE_BIT_WIND, GATE_BIT_EXT_EXP,
)
from aot.functions.utils.env_control.types import ManualLockState

from .conftest import make_ctx, make_opening_profile


# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _run_gate(ctx, profiles=None, cfg=None):
    profiles = profiles or [make_opening_profile()]
    gate = SafetyPreGate(config=cfg or PreGateConfig())
    return gate.evaluate(ctx, profiles)


# ─────────────────────────────────────────────────────────────────────────────
# 정상 조건 — 게이트 미발동
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalConditions:
    def test_normal_no_gate(self):
        """정상 조건에서 PreGate 미발동."""
        ctx = make_ctx(rain=0.0, wind=2.0)
        result = _run_gate(ctx)
        assert not result.triggered

    def test_normal_forced_commands_empty(self):
        """정상 조건에서 강제 명령 없음."""
        ctx = make_ctx(rain=0.0, wind=2.0)
        result = _run_gate(ctx)
        assert result.forced_commands == {}


# ─────────────────────────────────────────────────────────────────────────────
# 강우 게이트
# ─────────────────────────────────────────────────────────────────────────────

class TestRainGate:
    def test_rain_triggers_gate(self):
        """rain > threshold → 게이트 발동."""
        ctx = make_ctx(rain=1.0)
        result = _run_gate(ctx)
        assert result.triggered
        assert result.gate_mask & GATE_BIT_RAIN

    def test_rain_closes_all_openings(self):
        """강우 시 모든 개구부 0% 강제."""
        ctx = make_ctx(rain=2.0)
        profiles = [make_opening_profile('v1'), make_opening_profile('v2')]
        result = _run_gate(ctx, profiles)
        for aid in ['v1', 'v2']:
            assert result.forced_commands[aid]['value'] == pytest.approx(0.0)

    def test_below_rain_threshold_no_gate(self):
        """rain 임계값 미만 → 미발동."""
        ctx = make_ctx(rain=0.3)
        cfg = PreGateConfig(rain_threshold=0.5)
        result = _run_gate(ctx, cfg=cfg)
        assert not result.triggered


# ─────────────────────────────────────────────────────────────────────────────
# 강풍 게이트
# ─────────────────────────────────────────────────────────────────────────────

class TestWindGate:
    def test_high_wind_triggers_gate(self):
        """wind > threshold → 게이트 발동."""
        ctx = make_ctx(wind=15.0)
        result = _run_gate(ctx)
        assert result.triggered
        assert result.gate_mask & GATE_BIT_WIND

    def test_wind_closes_openings(self):
        """강풍 시 개구부 강제 폐쇄."""
        ctx = make_ctx(wind=20.0)
        p = make_opening_profile('v1')
        result = _run_gate(ctx, [p])
        assert result.forced_commands['v1']['value'] == pytest.approx(0.0)

    def test_moderate_wind_no_gate(self):
        """보통 바람 → 미발동."""
        ctx = make_ctx(wind=5.0)
        result = _run_gate(ctx)
        assert not result.triggered


# ─────────────────────────────────────────────────────────────────────────────
# 외부 센서 만료 게이트
# ─────────────────────────────────────────────────────────────────────────────

class TestExtExpiredGate:
    def test_stale_ext_partial_gate(self):
        """P2-2: 외부 센서 단독 만료 → partial=True/triggered=False (내부 제어 지속)."""
        now = time.time()
        ctx = make_ctx(now_ts=now)
        ctx['last_ext_ts'] = now - 400  # 400초 경과
        result = _run_gate(ctx)
        assert not result.triggered          # 전체 차단 아님
        assert result.partial                # partial 모드 (개구부만 강제)
        assert result.gate_mask & GATE_BIT_EXT_EXP

    def test_stale_ext_closes_openings(self):
        """외부 센서 만료 → 개구부(opening) 강제 폐쇄."""
        now = time.time()
        ctx = make_ctx(now_ts=now)
        ctx['last_ext_ts'] = now - 400
        profiles = [make_opening_profile('v1'), make_opening_profile('v2')]
        result = _run_gate(ctx, profiles)
        assert result.forced_commands['v1']['value'] == pytest.approx(0.0)
        assert result.forced_commands['v2']['value'] == pytest.approx(0.0)

    def test_fresh_ext_no_gate(self):
        """외부 센서 최신 → 미발동."""
        now = time.time()
        ctx = make_ctx(now_ts=now)
        ctx['last_ext_ts'] = now - 30  # 30초 전
        result = _run_gate(ctx)
        assert not result.triggered


# ─────────────────────────────────────────────────────────────────────────────
# 풍향 차등 폐쇄 (G4, partial gate)
# ─────────────────────────────────────────────────────────────────────────────

class TestWindwardDifferential:
    """풍향(wind_dir)에 따라 풍상측 개구부만 강제 폐쇄."""

    def test_windward_opening_closed(self):
        """동풍(90°) 시 동쪽 개구부(azimuth=90°)만 폐쇄."""
        ctx = make_ctx(wind=8.0)
        ctx['wind_dir'] = 90.0  # 동풍

        east_vent = make_opening_profile('east', azimuth_deg=90.0)
        west_vent = make_opening_profile('west', azimuth_deg=270.0)

        result = _run_gate(ctx, [east_vent, west_vent])
        # partial 또는 triggered
        if result.forced_commands:
            # 동쪽 폐쇄 강제, 서쪽은 없거나 정상
            if 'east' in result.forced_commands:
                assert result.forced_commands['east']['value'] == pytest.approx(0.0)
            # 서쪽은 강제 폐쇄 대상 아님
            assert 'west' not in result.forced_commands or \
                   result.forced_commands['west']['value'] != pytest.approx(0.0)

    def test_leeward_opening_not_forced(self):
        """풍하측(반대 방향) 개구부는 강제 폐쇄 안 됨."""
        ctx = make_ctx(wind=8.0)
        ctx['wind_dir'] = 0.0  # 북풍

        south_vent = make_opening_profile('south', azimuth_deg=180.0)

        result = _run_gate(ctx, [south_vent])
        # 풍하측이므로 강제 명령 없거나 폐쇄 아님
        if 'south' in result.forced_commands:
            assert result.forced_commands['south']['value'] != pytest.approx(0.0)
