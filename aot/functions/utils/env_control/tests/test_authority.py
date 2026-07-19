# coding=utf-8
"""
authority.py 단위 테스트.

대상:
  - derive_authority: kind → 방향별 권한 도출
  - needed_direction_authority: 편차 부호 → 방향 키 조회
    (변수명/방향 키 불일치로 [조치필요] 경보가 죽는 회귀 방지)
"""

from aot.functions.utils.env_control.authority import (
    LEVEL_ACTIVE, LEVEL_PASSIVE, LEVEL_NATURAL,
    derive_authority, needed_direction_authority,
)
from aot.functions.utils.env_control.types import ActuatorProfile


def _profile(kind, aid='a'):
    return ActuatorProfile(actuator_id=aid, kind=kind)


class TestDeriveAuthority:
    def test_heater_gives_active_t_up(self):
        auth = derive_authority([_profile('heater')])
        assert auth['T_up'] == LEVEL_ACTIVE
        assert auth['T_down'] == LEVEL_NATURAL

    def test_opening_is_passive_multidirection(self):
        auth = derive_authority([_profile('opening')])
        assert auth['T_down'] == LEVEL_PASSIVE
        assert auth['CO2_down'] == LEVEL_PASSIVE
        assert auth['CO2_up'] == LEVEL_NATURAL   # 환기로는 CO2 상승 불가

    def test_empty_profiles_all_natural(self):
        auth = derive_authority([])
        assert all(v == LEVEL_NATURAL for v in auth.values())


class TestNeededDirectionAuthority:
    """편차 부호 → 올바른 방향 권한 조회.

    핵심 회귀: authority 는 'T_up'/'CO2_down' 키인데 변수명('temperature'/'co2')
    으로 조회하면 항상 NATURAL → [조치필요] 경보가 영영 발동하지 않는다.
    """

    def setup_method(self):
        # 난방기(T 상승 ACTIVE) + 환기(T/RH/CO2 하강 PASSIVE) 보유 시설
        self.auth = derive_authority([_profile('heater', 'h'),
                                      _profile('opening', 'o')])

    def test_cold_with_heater_is_actionable(self):
        # 현재 < 목표 (dev<0) → 상승 필요 → T_up ACTIVE
        assert needed_direction_authority(
            self.auth, 'temperature', -3.0) == LEVEL_ACTIVE

    def test_hot_with_vent_is_passive_actionable(self):
        # 현재 > 목표 (dev>0) → 하강 필요 → T_down PASSIVE
        assert needed_direction_authority(
            self.auth, 'temperature', +3.0) == LEVEL_PASSIVE

    def test_co2_below_target_no_injector_is_natural(self):
        # CO2 상승 장치 없음 → 상승 필요 시 NATURAL (조치 불가)
        assert needed_direction_authority(
            self.auth, 'co2', -600.0) == LEVEL_NATURAL

    def test_co2_above_target_vent_can_lower(self):
        # 환기로 CO2 하강 가능 → PASSIVE
        assert needed_direction_authority(
            self.auth, 'co2', +200.0) == LEVEL_PASSIVE

    def test_bare_varname_lookup_would_miss(self):
        """방어: 변수명 그대로 조회하면 NATURAL (버그 재현) — 헬퍼는 이를 회피."""
        # 직접 변수명 조회는 미스
        assert self.auth.get('temperature', LEVEL_NATURAL) == LEVEL_NATURAL
        # 헬퍼는 방향 키로 변환해 ACTIVE 를 찾는다
        assert needed_direction_authority(
            self.auth, 'temperature', -3.0) == LEVEL_ACTIVE
