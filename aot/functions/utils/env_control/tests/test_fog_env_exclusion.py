# coding=utf-8
"""
관수 겸용 분무기를 환경 제어에서 제외하는 스위치 테스트.

배경 (2026-08-03 aot-005 육묘장):
이 시설은 관수와 가습을 **한 장치**로 처리한다 — 노즐 312개, 총 12,480 L/h 의
미니스프링클러 하나가 관수 레이어의 액추에이터이자 코디네이터의 fogger 다.

그래서 코디네이터를 켜면 별도 관수 제어와 경합한다. 조율기는 명령을 받지 못한
프로필에 safe_default 를 채우는데 fogger 의 safe_default 는 0.0 이고, 습윤형
분무기는 펄스 도징 대상이라 디스패치 데드밴드까지 면제된다. 결과적으로 가습
수요가 없는 새벽에도 **매 사이클 output_off 가 나가** 새벽 관수를 10 분 안에
꺼버린다. 잠금이 걸렸을 때만이 아니라 수요가 없을수록 더 확실하게 0 이 나간다.

살수 깊이가 이 판단의 근거다. 펄스 1회(20초)는 약 0.07 mm 로 엽면 보유량
(~0.2 mm)에 못 미쳐 흘러내리지 못하고 잎에서 그대로 마른다 — 용존 성분이
전량 잎에 남는다. 반면 아침 관수 10분은 2.1 mm 라 대부분 흘러내리며 오히려
씻어낸다. 같은 물·같은 노즐인데 잎 위 잔류량이 자릿수로 갈린다.
"""

import pytest

from aot.functions.custom_functions.env_coordinator_impl._profile_loader_mixin import (
    _fog_excluded_from_env, _fog_pulse_constraints, _is_wetting_fog,
)


WETTING     = {'nozzle': {'wetting': True,  'sprinkler_count': 312}}
NON_WETTING = {'nozzle': {'wetting': False, 'sprinkler_count': 0}}
NO_NOZZLE   = {}


class _Coord:
    """옵션만 들고 있는 최소 코디네이터 스텁."""

    def __init__(self, use_fog=None, nursery=False):
        self.use_wetting_fog_for_humidity = use_fog
        self.nursery_mode = nursery
        self.nursery_max_on_sec = 20.0
        self.nursery_min_off_sec = 600.0


# ─────────────────────────────────────────────────────────────────────────────
# 습윤 판정 (safety_gates.is_wetting_fogger 와 기준이 같아야 한다)
# ─────────────────────────────────────────────────────────────────────────────

class TestIsWettingFog:
    def test_wetting_nozzle(self):
        assert _is_wetting_fog('fogger', WETTING) is True

    def test_high_pressure_fog_is_not_wetting(self):
        assert _is_wetting_fog('fogger', NON_WETTING) is False

    def test_missing_nozzle_info_is_conservative(self):
        """수동 등록이라 노즐을 모르면 습윤형으로 본다."""
        assert _is_wetting_fog('fogger', NO_NOZZLE) is True

    def test_other_kinds_are_never_wetting(self):
        for kind in ('opening', 'shade', 'curtain', 'heater', 'circulation_fan'):
            assert _is_wetting_fog(kind, WETTING) is False

    def test_matches_safety_gate_judgment(self):
        """게이트와 판정이 갈리면 제외 대상과 잠금 대상이 어긋난다."""
        from aot.functions.utils.env_control.safety_gates import is_wetting_fogger
        from aot.functions.utils.env_control.types import (
            ActuatorProfile, CmdConstraints, ManualLockState,
        )
        for meta in (WETTING, NON_WETTING, NO_NOZZLE):
            p = ActuatorProfile(
                actuator_id='fog_01', kind='fogger', capabilities=['humidify'],
                manual_lock=ManualLockState(), cmd_constraints=CmdConstraints(),
                capacity_meta=meta)
            assert _is_wetting_fog('fogger', meta) == is_wetting_fogger(p)


# ─────────────────────────────────────────────────────────────────────────────
# 제외 판정
# ─────────────────────────────────────────────────────────────────────────────

class TestFogExclusion:
    def test_excluded_when_option_off(self):
        assert _fog_excluded_from_env(_Coord(use_fog=False), 'fogger', WETTING) is True

    def test_kept_when_option_on(self):
        assert _fog_excluded_from_env(_Coord(use_fog=True), 'fogger', WETTING) is False

    def test_unset_keeps_previous_behaviour(self):
        """옵션 미설정(None) = 기본값 사용 — 기존 설치의 동작이 바뀌면 안 된다."""
        assert _fog_excluded_from_env(_Coord(use_fog=None), 'fogger', WETTING) is False

    def test_missing_attribute_keeps_previous_behaviour(self):
        """구버전 설정에서 올라온 인스턴스에 속성 자체가 없을 수도 있다."""
        class _Old:
            pass
        assert _fog_excluded_from_env(_Old(), 'fogger', WETTING) is False

    def test_high_pressure_fog_survives_the_switch(self):
        """고압 미세포그는 가습 전용 설비라 끄개의 대상이 아니다."""
        assert _fog_excluded_from_env(
            _Coord(use_fog=False), 'fogger', NON_WETTING) is False

    def test_manual_registration_without_nozzle_is_excluded(self):
        """노즐 정보가 없으면 습윤형으로 보고 함께 제외한다."""
        assert _fog_excluded_from_env(_Coord(use_fog=False), 'fogger', NO_NOZZLE) is True

    def test_other_actuators_untouched(self):
        """스크린·개구부·팬은 이 스위치와 무관하다 — 가습은 이들이 대신한다."""
        for kind in ('opening', 'shade', 'curtain', 'heater', 'circulation_fan'):
            assert _fog_excluded_from_env(_Coord(use_fog=False), kind, WETTING) is False


# ─────────────────────────────────────────────────────────────────────────────
# 펄스 도징과의 관계 — 두 기능이 같은 습윤 판정을 공유한다
# ─────────────────────────────────────────────────────────────────────────────

class TestPulseConstraintsUnaffected:
    def test_pulse_still_applies_when_fog_is_used(self):
        c = _Coord(use_fog=True, nursery=True)
        assert _fog_pulse_constraints(c, 'fogger', WETTING) == {
            'max_on_sec': 20.0, 'min_off_sec': 600.0}

    def test_pulse_not_applied_to_high_pressure_fog(self):
        c = _Coord(use_fog=True, nursery=True)
        assert _fog_pulse_constraints(c, 'fogger', NON_WETTING) == {}

    def test_refactor_kept_missing_nozzle_conservative(self):
        """_is_wetting_fog 추출 과정에서 보수적 기본값이 뒤집히지 않았는지."""
        c = _Coord(use_fog=True, nursery=False)
        assert _fog_pulse_constraints(c, 'fogger', NO_NOZZLE) == {
            'max_on_sec': 30.0, 'min_off_sec': 180.0}


# ─────────────────────────────────────────────────────────────────────────────
# 왜 '명령 0' 이 아니라 '프로필 없음' 이어야 하는가
# ─────────────────────────────────────────────────────────────────────────────

class TestExclusionMustRemoveTheProfile:
    """제외의 구현 방식을 행동으로 고정한다.

    조율기는 배분에서 빠진 프로필에도 `safe_default` 명령을 채운다
    (coordinator.py 의 "명령을 못 받은 프로필 → 안전 기본값" 루프).
    fogger 는 `_KIND_SAFE_DEFAULT` 에 없어 0.0 이다. 그리고 습윤형 분무기는
    펄스 도징 대상이라 디스패치 데드밴드가 면제돼 이 0 이 매 사이클 실제로
    전송된다 — 새벽처럼 가습 수요가 아예 없는 시간대에도 그렇다.

    그래서 "코디네이터가 안 쓰면 그만" 이 성립하지 않는다. 프로필을 남긴 채
    명령만 비우는 구현은 별도 관수 제어를 계속 꺼버린다.
    """

    @staticmethod
    def _profiles():
        from aot.functions.utils.env_control.types import (
            ActuatorProfile, CmdConstraints, ManualLockState,
        )
        from .conftest import make_opening_profile
        fog = ActuatorProfile(
            actuator_id='sprinkler_01', kind='fogger', capabilities=['humidify'],
            manual_lock=ManualLockState(), cmd_constraints=CmdConstraints(),
            capacity_meta=WETTING)
        return fog, make_opening_profile()

    @staticmethod
    def _run(profiles):
        """새벽 상황(가습 수요 없음)으로 한 사이클 조율."""
        from aot.functions.utils.env_control.coordinator import (
            CoordinatorState, coordinate,
        )
        from aot.functions.utils.env_control.situation import assess
        from .conftest import make_ctx, make_target
        # 실내가 이미 습해 VPD 가 목표보다 낮다 = 가습이 필요 없는 새벽
        ctx = make_ctx(T_int=20.0, RH_int=92.0)
        report, _ = assess(make_target(), ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'])
        cmds, _ = coordinate(report, list(profiles), CoordinatorState())
        return cmds

    def test_profile_present_gets_a_zero_command(self):
        """프로필이 남아 있으면 수요가 없어도 0 명령이 생성된다 = 관수와 경합."""
        fog, vent = self._profiles()
        cmds = self._run([fog, vent])
        assert fog.actuator_id in cmds
        assert cmds[fog.actuator_id].value == pytest.approx(0.0)

    def test_profile_absent_produces_no_command_at_all(self):
        """제외하면 명령 자체가 없다 — 관수 제어가 그대로 살아 있다."""
        fog, vent = self._profiles()
        cmds = self._run([vent])
        assert fog.actuator_id not in cmds

    def test_other_actuators_still_coordinated(self):
        """분무기를 빼도 개구부 등 나머지 조율은 정상이어야 한다."""
        _, vent = self._profiles()
        cmds = self._run([vent])
        assert vent.actuator_id in cmds
