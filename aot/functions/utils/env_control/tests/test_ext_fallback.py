# coding=utf-8
"""
P2-2: 외부 센서 만료 fallback 단위 테스트.

대상:
  - ExtContextCache: 갱신·age 계산·빈 캐시
  - build_fallback_context: 키 존재, 캐시 우선, 내부값 fallback, _stale 마커
  - 게이트: 강우·풍속을 잃으면(EXT_EXP) partial, 강제 명령 없이 "더 열지 않음"
  - 게이트: 잃은 마지막 값이 위험이면 그 값으로 계속 닫는다(래치)
"""

import time

import pytest

from aot.functions.utils.env_control.ext_context_fallback import (
    ExtContextCache, build_fallback_context,
)
from aot.functions.utils.env_control.log_channels import (
    GATE_BIT_EXT_EXP, GATE_BIT_HEAT, GATE_BIT_INT_EXP,
)
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
    """강우·풍속을 잃었을 때의 게이트 — 규칙 A(오래된 값은 안전한 방향으로만)."""

    @staticmethod
    def _lose(ctx, *keys):
        for k in keys:
            ctx['external'].pop(k, None)
        return ctx

    def test_ext_exp_alone_is_partial(self):
        """평온하던 값을 잃음 → partial, 강제 명령 없음, 더 열지 않음."""
        from aot.functions.utils.env_control.tests.conftest import make_heater_profile
        gate = SafetyPreGate()
        profiles = [make_opening_profile('v1'), make_heater_profile('h1')]
        gate.evaluate(make_ctx(rain=0.0, wind=2.0), profiles)
        result = gate.evaluate(self._lose(make_ctx(), 'rain', 'wind'), profiles)
        assert not result.triggered
        assert result.partial
        assert result.vent_open_ceiling
        assert result.forced_commands == {}

    def test_ext_exp_plus_rain_triggers_full(self):
        """비 오던 중 강우를 잃음 → 마지막 값으로 계속 닫는다(래치)."""
        gate = SafetyPreGate()
        gate.evaluate(make_ctx(rain=2.0, wind=2.0), [make_opening_profile()])
        gate._triggered_until = 0.0                      # gate_ttl 경과 가정
        result = gate.evaluate(self._lose(make_ctx(), 'rain'),
                               [make_opening_profile()])
        assert result.triggered and not result.partial
        assert result.gate_mask & GATE_BIT_RAIN
        assert result.forced_commands['vent_01']['value'] == pytest.approx(0.0)

    def test_ext_exp_plus_wind_triggers_full(self):
        """강풍 중 풍속을 잃음 → 풍향 차등 없이 전부 닫는다."""
        gate = SafetyPreGate()
        gate.evaluate(make_ctx(rain=0.0, wind=15.0), [make_opening_profile()])
        gate._triggered_until = 0.0
        result = gate.evaluate(self._lose(make_ctx(), 'wind'),
                               [make_opening_profile()])
        assert result.triggered


# ─────────────────────────────────────────────────────────────────────────────
# INT_EXP — 실내 값을 잃으면 **제자리** (2026-09-20 재정의)
# ─────────────────────────────────────────────────────────────────────────────
# 예전에는 `last_int_ts` 로 나이를 재서 모든 액추에이터를 safe_default 로
# 강제했다. 둘 다 틀렸다 — 호출자가 그 키에 매번 `time.time()` 을 실어 보내
# **한 번도 발동한 적이 없었고**, 되살리면 실내 노드가 끊기는 순간 한여름에
# 창이 닫힌다. EXT_EXP 가 2026-09-19 에 같은 이유로 그만둔 동작이다.
# ─────────────────────────────────────────────────────────────────────────────

class TestIntExpBehaviour:

    @staticmethod
    def _lost(ctx):
        """실내 값이 안 온 사이클 — 게이트는 나이가 아니라 이것을 본다."""
        ctx['internal']['T'] = None
        ctx['internal']['RH'] = None
        return ctx

    def test_실내_값을_잃으면_발동한다(self):
        result = _run_gate(self._lost(make_ctx(rain=0.0, wind=2.0)))
        assert result.gate_mask & GATE_BIT_INT_EXP
        assert 'int_sensor_expired' in result.description

    def test_나이로_재지_않는다(self):
        """값이 왔으면 `last_int_ts` 가 아무리 낡아도 발동하지 않는다.

        판정이 두 벌이 되면 느슨한 쪽이 실질이 된다 — 값이 쓸 만한가는
        `measurement_freshness` 가 센서마다 이미 정했다.
        """
        now = time.time()
        ctx = make_ctx(rain=0.0, wind=2.0, now_ts=now)
        ctx['last_int_ts'] = now - 86400
        assert not (_run_gate(ctx).gate_mask & GATE_BIT_INT_EXP)

    def test_강제_명령을_만들지_않는다(self):
        """근거가 없다는 이유로 장비를 움직이지 않는다.

        예전에는 개구부가 safe_default(0 = 닫힘), 스크린이 100(= 걷힘) 으로
        끌려갔다. 실내를 모르는 동안 할 일은 아무것도 하지 않는 것이다.
        """
        result = _run_gate(self._lost(make_ctx(rain=0.0, wind=2.0)))
        assert result.forced_commands == {}

    def test_L1_L3_를_멈추지_않는다(self):
        """잴 수 있는 축(CO₂·광량 임계)은 계속 제어해야 한다."""
        result = _run_gate(self._lost(make_ctx(rain=0.0, wind=2.0)))
        assert result.partial and not result.triggered

    def test_TTL_을_잡지_않는다(self):
        """값이 돌아오면 곧바로 재개한다 — 300초 더 멈추지 않는다."""
        gate = SafetyPreGate()
        gate.evaluate(self._lost(make_ctx(rain=0.0, wind=2.0)),
                      [make_opening_profile()])
        back = gate.evaluate(make_ctx(rain=0.0, wind=2.0),
                             [make_opening_profile()])
        assert not back.triggered and back.gate_mask == 0

    def test_비상_게이트가_함께_서면_그쪽이_이긴다(self):
        """강우는 실내를 몰라도 판단할 수 있다 — 창은 닫혀야 한다."""
        result = _run_gate(self._lost(make_ctx(rain=5.0, wind=2.0)))
        assert result.triggered and not result.partial
        assert result.forced_commands['vent_01']['value'] == pytest.approx(0.0)

    def test_실내를_모르면_폭염_한파를_판정하지_않는다(self):
        """비상 게이트는 전 장비를 한쪽으로 몬다 — 근거가 확실할 때만 선다."""
        ctx = self._lost(make_ctx(rain=0.0, wind=2.0))
        ctx['external']['T'] = 46.0          # 폭염 임계 밖
        result = _run_gate(ctx)
        assert not (result.gate_mask & GATE_BIT_HEAT)
