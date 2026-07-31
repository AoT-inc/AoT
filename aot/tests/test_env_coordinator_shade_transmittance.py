# coding=utf-8
"""차광포 투과율 기반 실내 광량 추정(estimate_indoor_light) 테스트.

실내 광센서가 없으면 internal['light'] 에 실외 일사가 그대로 들어가는데, 그
값은 차광막을 닫아도 변하지 않는다. 즉 차광막이 스스로 만든 광부족을
light_min 이 원리적으로 감지할 수 없다(2026-07-29 aot-005 사건).
"""
import pytest

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    estimate_indoor_light,
)
from aot.functions.utils.env_control.types import ActuatorProfile


def _shade(aid='shade-1', tau=None):
    cap = {}
    if tau is not None:
        cap['shade_transmittance'] = tau
    return ActuatorProfile(actuator_id=aid, kind='shade', capacity_meta=cap)


# ── 기본 물리 ────────────────────────────────────────────────────────────────

def test_fully_open_passes_all_light():
    ps = [_shade(tau=0.30)]
    assert estimate_indoor_light(800.0, ps, {'shade-1': 100.0}) == pytest.approx(800.0)


def test_fully_closed_passes_only_transmittance():
    ps = [_shade(tau=0.30)]
    # 완전 폐쇄 → 투과율 30% 만 통과
    assert estimate_indoor_light(800.0, ps, {'shade-1': 0.0}) == pytest.approx(240.0)


def test_half_closed_is_linear_between():
    ps = [_shade(tau=0.30)]
    # 폐쇄율 0.5 → 통과율 1 - 0.5*(1-0.3) = 0.65
    assert estimate_indoor_light(800.0, ps, {'shade-1': 50.0}) == pytest.approx(520.0)


def test_opaque_cloth_blocks_almost_everything():
    ps = [_shade(tau=0.05)]
    assert estimate_indoor_light(800.0, ps, {'shade-1': 0.0}) == pytest.approx(40.0)


# ── opt-in 보장 (미설정 시 기존 동작 유지) ───────────────────────────────────

def test_no_transmittance_configured_returns_outdoor_unchanged():
    """투과율 미설정이면 추정하지 않는다 — 기존 설치의 동작이 바뀌면 안 된다."""
    ps = [_shade(tau=None)]
    assert estimate_indoor_light(800.0, ps, {'shade-1': 0.0}) == 800.0


def test_zero_transmittance_treated_as_disabled():
    ps = [_shade(tau=0.0)]
    assert estimate_indoor_light(800.0, ps, {'shade-1': 0.0}) == 800.0


def test_no_shade_actuator_returns_outdoor_unchanged():
    ps = [ActuatorProfile(actuator_id='op-1', kind='opening')]
    assert estimate_indoor_light(800.0, ps, {'op-1': 0.0}) == 800.0


def test_missing_aperture_is_skipped():
    """첫 사이클처럼 prev_commands 가 비어 있으면 추정하지 않는다."""
    ps = [_shade(tau=0.30)]
    assert estimate_indoor_light(800.0, ps, {}) == 800.0


def test_non_shade_kinds_are_ignored():
    """보온커튼은 차광 목적이 아니므로 광량 추정에 관여하면 안 된다."""
    curtain = ActuatorProfile(actuator_id='cur-1', kind='curtain',
                              capacity_meta={'shade_transmittance': 0.1})
    assert estimate_indoor_light(800.0, [curtain], {'cur-1': 0.0}) == 800.0


# ── 다중 차광막 ──────────────────────────────────────────────────────────────

def test_multiple_shades_uses_darkest():
    """여러 장이면 가장 어두운 쪽을 대표값으로 — 광부족을 놓치지 않기 위해."""
    ps = [_shade('shade-L', tau=0.30), _shade('shade-R', tau=0.30)]
    # 좌는 열림(통과 1.0), 우는 폐쇄(통과 0.3) → 최소값 0.3 채택
    got = estimate_indoor_light(800.0, ps, {'shade-L': 100.0, 'shade-R': 0.0})
    assert got == pytest.approx(240.0)


# ── 실제 사건 재현 ───────────────────────────────────────────────────────────

def test_reproduces_aot005_blind_spot():
    """2026-07-30 aot-005: 실외 335 W/m² 인데 차광막 완전폐쇄 상태였다.

    추정 전에는 335 > light_min(150) 이라 '광량 충분'으로 보였지만, 실제
    차광막 아래는 100 W/m² 로 light_min 미만이다.
    """
    ps = [_shade(tau=0.30)]
    outdoor = 335.0
    assert outdoor > 150.0                      # 추정 없이는 위반 아님
    est = estimate_indoor_light(outdoor, ps, {'shade-1': 0.0})
    assert est == pytest.approx(100.5)
    assert est < 150.0                          # 추정하면 광부족이 드러난다


# ── 경계값 방어 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('aperture,expected', [
    (-10.0, 240.0),    # 범위 밖 음수 → 0% 로 클램프
    (150.0, 800.0),    # 범위 밖 초과 → 100% 로 클램프
])
def test_aperture_out_of_range_is_clamped(aperture, expected):
    ps = [_shade(tau=0.30)]
    assert estimate_indoor_light(800.0, ps, {'shade-1': aperture}) == pytest.approx(expected)


def test_transmittance_above_one_is_rejected():
    """물리적으로 불가능한 값(>1)은 무시하고 원본을 돌려준다."""
    ps = [_shade(tau=1.5)]
    assert estimate_indoor_light(800.0, ps, {'shade-1': 0.0}) == 800.0


# ── 함수 레벨 기본 투과율 (자동발견 액추에이터용) ────────────────────────────
# 시설 도면에서 자동 발견된 차광막은 env_actuator 액션 행이 없어 액추에이터별
# 투과율을 넣을 자리가 없다(aot-005 가 그렇다). 함수 레벨 값이 유일한 입력구다.

def test_function_level_default_applies_when_actuator_has_none():
    ps = [_shade(tau=None)]
    got = estimate_indoor_light(800.0, ps, {'shade-1': 0.0}, default_tau=0.5)
    assert got == pytest.approx(400.0)


def test_per_actuator_value_overrides_function_level_default():
    ps = [_shade(tau=0.30)]
    got = estimate_indoor_light(800.0, ps, {'shade-1': 0.0}, default_tau=0.5)
    assert got == pytest.approx(240.0)      # 0.30 이 이김


def test_function_level_zero_keeps_opt_in_behaviour():
    ps = [_shade(tau=None)]
    assert estimate_indoor_light(800.0, ps, {'shade-1': 0.0}, default_tau=0.0) == 800.0


def test_function_level_default_with_tau_half_on_real_case():
    """aot-005 적용값 0.5 기준: 실외 335 → 차광막 완전폐쇄 시 167.5 W/m²."""
    ps = [_shade(tau=None)]
    got = estimate_indoor_light(335.0, ps, {'shade-1': 0.0}, default_tau=0.5)
    assert got == pytest.approx(167.5)
