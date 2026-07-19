# coding=utf-8
"""
P2-2: 외부 센서 만료 fallback 단위 테스트.

대상:
  - ExtContextCache: 갱신·age 계산·빈 캐시
  - build_fallback_context: 키 존재, 캐시 우선, 내부값 fallback, _stale 마커
  - 게이트: EXT_EXP 단독 시 partial=True, 개구부만 강제 폐쇄
  - 게이트: EXT_EXP + 다른 게이트 동시 시 triggered=True (보수적 전체 차단)
"""

import time

import pytest

from aot.functions.utils.env_control.ext_context_fallback import (
    ExtContextCache, build_fallback_context,
)
from aot.functions.utils.env_control.log_channels import GATE_BIT_EXT_EXP
from aot.functions.utils.env_control.safety_gates import (
    SafetyPreGate, PreGateConfig, GATE_BIT_RAIN,
)

from .conftest import make_ctx, make_opening_profile


# ─────────────────────────────────────────────────────────────────────────────
# ExtContextCache
# ─────────────────────────────────────────────────────────────────────────────

class TestExtContextCache:
    def test_update_sets_values(self):
        cache = ExtContextCache()
        now = time.time()
        cache.update({'T': 25.0, 'wind': 3.0}, now=now)
        assert cache.values['T'] == pytest.approx(25.0)
        assert cache.last_good_ts == pytest.approx(now)

    def test_age_after_update(self):
        cache = ExtContextCache()
        t0 = 1000.0
        cache.update({'T': 20.0}, now=t0)
        assert cache.age(now=t0 + 120) == pytest.approx(120.0)

    def test_age_empty_is_inf(self):
        cache = ExtContextCache()
        assert cache.age() == float('inf')

    def test_is_empty_initially(self):
        assert ExtContextCache().is_empty()

    def test_not_empty_after_update(self):
        cache = ExtContextCache()
        cache.update({'T': 20.0})
        assert not cache.is_empty()

    def test_update_overwrites(self):
        cache = ExtContextCache()
        cache.update({'T': 20.0})
        cache.update({'T': 30.0})
        assert cache.values['T'] == pytest.approx(30.0)


# ─────────────────────────────────────────────────────────────────────────────
# build_fallback_context
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildFallbackContext:
    def _cache_with(self, **kv):
        c = ExtContextCache()
        c.update(kv, now=1000.0)
        return c

    def test_stale_marker_set(self):
        fb = build_fallback_context(ExtContextCache(), {'T': 22.0}, now=1000.0)
        assert fb['_stale'] is True

    def test_stale_age_present(self):
        cache = self._cache_with(T=20.0)
        fb = build_fallback_context(cache, {'T': 22.0}, now=1600.0)
        assert fb['_stale_age'] == pytest.approx(600.0)

    def test_wind_always_zero(self):
        """외부 센서 만료 시 wind=0 (개구부 게이트가 이미 폐쇄)."""
        cache = self._cache_with(wind=15.0)
        fb = build_fallback_context(cache, {})
        assert fb['wind'] == pytest.approx(0.0)

    def test_rain_always_zero(self):
        cache = self._cache_with(rain=5.0)
        fb = build_fallback_context(cache, {})
        assert fb['rain'] == pytest.approx(0.0)

    def test_T_ext_from_cache(self):
        cache = self._cache_with(T_ext=30.0)
        fb = build_fallback_context(cache, {'T': 22.0})
        assert fb['T_ext'] == pytest.approx(30.0)

    def test_T_ext_fallback_to_internal(self):
        """캐시 없을 때 T_int를 외부 온도 추정으로 사용."""
        fb = build_fallback_context(ExtContextCache(), {'T': 22.0})
        assert fb['T_ext'] == pytest.approx(22.0)

    def test_RH_ext_fallback_to_internal(self):
        fb = build_fallback_context(ExtContextCache(), {'T': 22.0, 'RH': 65.0})
        assert fb['RH_ext'] == pytest.approx(65.0)

    def test_required_keys_present(self):
        """fallback dict 이 필수 키를 모두 포함한다."""
        fb = build_fallback_context(ExtContextCache(), {})
        required = {'wind', 'rain', 'T_ext', 'RH_ext', '_stale', '_stale_age'}
        assert required.issubset(fb.keys())


# ─────────────────────────────────────────────────────────────────────────────
# 게이트 동작 — EXT_EXP 단독 vs 복합
# ─────────────────────────────────────────────────────────────────────────────

def _run_gate(ctx, profiles=None, cfg=None):
    profiles = profiles or [make_opening_profile()]
    gate = SafetyPreGate(config=cfg or PreGateConfig())
    return gate.evaluate(ctx, profiles)


class TestGateExtExpBehaviour:
    def test_ext_exp_alone_is_partial(self):
        """EXT_EXP 단독 → partial=True, triggered=False."""
        now = time.time()
        ctx = make_ctx(rain=0.0, wind=2.0, now_ts=now)
        ctx['last_ext_ts'] = now - 400
        result = _run_gate(ctx)
        assert not result.triggered
        assert result.partial

    def test_ext_exp_only_closes_openings(self):
        """EXT_EXP 단독 → opening 강제 0%, 내부 전용 액추에이터 명령 없음."""
        from aot.functions.utils.env_control.tests.conftest import make_heater_profile
        now = time.time()
        ctx = make_ctx(rain=0.0, wind=2.0, now_ts=now)
        ctx['last_ext_ts'] = now - 400
        profiles = [make_opening_profile('v1'), make_heater_profile('h1')]
        result = _run_gate(ctx, profiles)
        assert 'v1' in result.forced_commands
        assert result.forced_commands['v1']['value'] == pytest.approx(0.0)
        assert 'h1' not in result.forced_commands  # 난방기는 강제 명령 없음

    def test_ext_exp_plus_rain_triggers_full(self):
        """EXT_EXP + 강우 동시 → triggered=True (보수적 전체 차단)."""
        now = time.time()
        ctx = make_ctx(rain=2.0, wind=2.0, now_ts=now)
        ctx['last_ext_ts'] = now - 400
        result = _run_gate(ctx)
        assert result.triggered
        assert not result.partial

    def test_ext_exp_plus_wind_triggers_full(self):
        """EXT_EXP + 강풍 동시 → triggered=True."""
        now = time.time()
        ctx = make_ctx(rain=0.0, wind=15.0, now_ts=now)
        ctx['last_ext_ts'] = now - 400
        result = _run_gate(ctx)
        assert result.triggered


# ─────────────────────────────────────────────────────────────────────────────
# INT_EXP — 내부 센서 만료는 전체 차단 유지
# ─────────────────────────────────────────────────────────────────────────────

class TestIntExpBehaviour:
    def test_int_exp_triggers_full(self):
        """내부 센서 만료 → triggered=True (내부 제어 불가)."""
        now = time.time()
        ctx = make_ctx(rain=0.0, wind=2.0, now_ts=now)
        ctx['last_int_ts'] = now - 300   # 내부 만료 (기본 임계 120s)
        result = _run_gate(ctx)
        assert result.triggered
