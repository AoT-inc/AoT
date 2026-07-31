# coding=utf-8
"""하드 임계 히스테리시스(latch_threshold) 회귀 테스트.

2026-07-30 aot-005: 차광막이 17:50 개방 → 18:04 폐쇄로 왕복했다. 하드 임계
판정이 단순 비교(`t_val > temp_max`)라 값이 임계 근처에서 흔들리면 강제
오버라이드가 매 사이클 on/off 를 반복한다. 차광막은 편도 285초 full-stroke
주행이라 왕복 피해가 특히 크다.
"""
import pytest

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    latch_threshold, TEMP_HYST_C, RH_HYST_PCT, LIGHT_HYST_FRAC,
)


# ── mode='max' (상한) ────────────────────────────────────────────────────────

def test_max_enters_breach_above_threshold():
    assert latch_threshold(33.1, 33.0, 0.5, was_breached=False, mode='max') is True


def test_max_does_not_enter_at_or_below_threshold():
    assert latch_threshold(33.0, 33.0, 0.5, was_breached=False, mode='max') is False
    assert latch_threshold(32.9, 33.0, 0.5, was_breached=False, mode='max') is False


def test_max_holds_breach_inside_hysteresis_band():
    """핵심: 임계 아래로 내려와도 히스테리시스 폭 안이면 강제를 유지한다."""
    # 33.0 - 0.5 = 32.5 이 해제선. 32.7 은 아직 밴드 안 → 유지.
    assert latch_threshold(32.7, 33.0, 0.5, was_breached=True, mode='max') is True


def test_max_releases_below_hysteresis_band():
    # 32.4 < 32.5 → 해제
    assert latch_threshold(32.4, 33.0, 0.5, was_breached=True, mode='max') is False


# ── mode='min' (하한) ────────────────────────────────────────────────────────

def test_min_enters_breach_below_threshold():
    assert latch_threshold(3.9, 4.0, 0.5, was_breached=False, mode='min') is True


def test_min_holds_breach_inside_hysteresis_band():
    # 4.0 + 0.5 = 4.5 이 해제선. 4.3 은 밴드 안 → 유지.
    assert latch_threshold(4.3, 4.0, 0.5, was_breached=True, mode='min') is True


def test_min_releases_above_hysteresis_band():
    assert latch_threshold(4.6, 4.0, 0.5, was_breached=True, mode='min') is False


# ── 채터링 시나리오 재현 ─────────────────────────────────────────────────────

def test_oscillating_value_does_not_chatter():
    """임계를 사이에 두고 미세 진동하는 값이 강제를 왕복시키지 않아야 한다.

    히스테리시스가 없으면 아래 시퀀스는 True/False 를 6번 왕복한다
    (= 차광막 full-stroke 왕복 6회).
    """
    seq = [33.1, 32.9, 33.1, 32.8, 33.2, 32.9]   # 33.0 근처 진동
    state = False
    transitions = 0
    for v in seq:
        new = latch_threshold(v, 33.0, TEMP_HYST_C, state, 'max')
        if new != state:
            transitions += 1
        state = new
    # 진입 1회만 일어나고, 32.5 아래로 내려간 적이 없으므로 해제는 없어야 한다.
    assert transitions == 1, f'강제가 {transitions}회 왕복했다 — 히스테리시스 미작동'
    assert state is True


def test_sustained_drop_still_releases():
    """히스테리시스가 강제를 영구 고착시키면 안 된다 — 확실히 내려가면 해제."""
    state = True
    for v in [32.8, 32.6, 32.4]:
        state = latch_threshold(v, 33.0, TEMP_HYST_C, state, 'max')
    assert state is False


# ── 상수 타당성 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('hyst', [TEMP_HYST_C, RH_HYST_PCT, LIGHT_HYST_FRAC])
def test_hysteresis_constants_are_positive(hyst):
    assert hyst > 0


def test_light_hysteresis_scales_with_threshold():
    """광량은 절대폭이 넓어 비율 기반이어야 한다(150 과 800 의 밴드가 달라야)."""
    assert 150.0 * LIGHT_HYST_FRAC == pytest.approx(15.0)
    assert 800.0 * LIGHT_HYST_FRAC == pytest.approx(80.0)
