# coding=utf-8
"""맞서는 짝(냉방↔난방)은 **온도 축의 요구가 한쪽만 고른다**.

PID 는 raise/lower 출력을 두고 오차 부호가 한쪽만 고르므로, 방향을 정하는 행위
자체가 곧 인터록이다. 코디네이터는 액추에이터마다 따로 PI 를 돌려서 그 성질이
공짜로 따라오지 않는다 — `coordinate()` 2.55절이 명시적으로 준다.

## 왜 뒤에서 끄는 것으로는 부족한가

디스패치 직전 인터록(`_cycle_mixin.apply_hvac_opposition_interlock`)은 마지막
방어선이지만, 그때까지 **진 쪽은 매 사이클 100% 를 원하며 적분을 쌓는다.**
후보에서 빼면 적분이 safe_default 로 풀린다.

## 2026-08-26 실측 — 이 검사가 없으면 나는 일

温室環境制御(Kumamoto): `temp_max=30` 인데 실내 32.7°C, 목표 온도는 31.97°C.
코디네이터는 난방기를 **VPD 때문에** 100% 로 켜 두고 있었고(`var='vpd'`,
편차 −0.07), 하드 임계는 냉방기를 100% 로 강제했다. 둘이 함께 돌았다.

⚠ 그때 **`deviation_native` 에 'temperature' 가 아예 없었다.** VPD 직접 제어
모드에서 `_decompose_vpd` 가 온도를 `_temperature_constraint` 로 강등하기
때문이다. 편차 부호만 보는 판정은 이 사고에서 **한 번도 서지 않는다** — 그래서
하드 임계를 먼저 본다.
"""

from aot.functions.utils.env_control.coordinator import (
    REASON_NO_GRADIENT, REASON_OPPOSING_PARKED, CoordinatorState, coordinate,
)
from aot.functions.utils.env_control.situation import assess
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar,
)


def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


def _pair():
    """난방기·냉방기 한 쌍. 둘 다 온도에만 효과를 선언한다."""
    return [
        ActuatorProfile(
            actuator_id='heat', kind='heater',
            effect_model={'temperature': _effect('↑', 2.0)},
            cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
            gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0),
        ActuatorProfile(
            actuator_id='cool', kind='cooler',
            effect_model={'temperature': _effect('↓', 2.5)},
            cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
            gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0),
    ]


def _cycle(profiles, state, T_int, T_target, internal_extra=None, tol=1.0):
    internal = {'T': T_int, 'RH': 65.0, 'CO2': 600.0}
    internal.update(internal_extra or {})
    target = {'temperature': TargetVar(value=T_target, tolerance=tol,
                                       priority=1.0)}
    report, _ = assess(
        target, internal,
        {'T': T_int, 'RH': 65.0, 'wind': 1.0, 'rain': 0.0, 'solar': 0.0},
        cycle_sec=60.0, now_ts=1767240000.0)
    return coordinate(report, profiles, state)


class TestTemperatureAxisPicksOneSide:

    def test_hot_parks_the_heater(self):
        profiles = _pair()
        # 난방기가 이전 사이클에 100% 로 돌고 있었고 적분도 거기 굳어 있다.
        st = CoordinatorState(prev_commands={'heat': 100.0, 'cool': 0.0},
                              integral={'heat': 100.0, 'cool': 0.0})
        cmds, new = _cycle(profiles, st, T_int=35.0, T_target=25.0)

        assert cmds['heat'].reason == REASON_OPPOSING_PARKED, '난방기가 안 파킹됐다'
        assert cmds['cool'].control_value() > 0.0, '냉방기가 일하지 않는다'
        # 후보에서 빠졌으므로 적분이 safe_default 쪽으로 **풀린다**.
        assert new.integral['heat'] < 100.0, (
            '진 쪽의 적분이 그대로 남았다 — 다음 사이클에도 100%% 를 원한다: %.1f'
            % new.integral['heat'])

    def test_cold_parks_the_cooler(self):
        profiles = _pair()
        st = CoordinatorState(prev_commands={'heat': 0.0, 'cool': 100.0},
                              integral={'heat': 0.0, 'cool': 100.0})
        cmds, new = _cycle(profiles, st, T_int=15.0, T_target=25.0)

        assert cmds['cool'].reason == REASON_OPPOSING_PARKED, '냉방기가 안 파킹됐다'
        assert cmds['heat'].control_value() > 0.0
        assert new.integral['cool'] < 100.0

    def test_inside_tolerance_parks_neither(self):
        """온도가 편안한 구간이면 제한하지 않는다.

        VPD 나 습도를 위해 가온·냉방하는 것은 정상이다. 여기서까지 막으면
        "온도가 목표면 다른 것은 못 고친다" 가 된다.
        """
        profiles = _pair()
        st = CoordinatorState()
        cmds, _ = _cycle(profiles, st, T_int=25.2, T_target=25.0, tol=1.0)

        assert cmds['heat'].reason != REASON_OPPOSING_PARKED
        assert cmds['cool'].reason != REASON_OPPOSING_PARKED


class TestHardThresholdIsCheckedFirst:
    """⚠ 이 계열이 이 파일의 존재 이유다.

    VPD 직접 제어 모드에서는 `deviation_native` 에 온도가 없어 편차 부호 판정이
    통째로 서지 않는다. 그때도 하드 임계는 서야 한다 — 2026-08-26 사고가
    정확히 그 조합이었다.
    """

    def test_force_cool_parks_the_heater_even_without_a_temperature_deviation(self):
        profiles = _pair()
        st = CoordinatorState(prev_commands={'heat': 100.0},
                              integral={'heat': 100.0})
        # 온도는 허용오차 안(편차 부호로는 아무 요구도 없다) + 하드 상한 위반.
        cmds, new = _cycle(profiles, st, T_int=25.2, T_target=25.0,
                           internal_extra={'_force_cool': True})

        assert cmds['heat'].reason == REASON_OPPOSING_PARKED, (
            '하드 임계가 후보 선택에 반영되지 않았다 — 편차가 0 이면 난방기가 '
            'VPD 때문에 계속 돈다(2026-08-26 사고의 모양)')
        assert new.integral['heat'] < 100.0

    def test_force_heat_parks_the_cooler(self):
        profiles = _pair()
        st = CoordinatorState(prev_commands={'cool': 100.0},
                              integral={'cool': 100.0})
        cmds, new = _cycle(profiles, st, T_int=24.8, T_target=25.0,
                           internal_extra={'_force_heat': True})

        assert cmds['cool'].reason == REASON_OPPOSING_PARKED
        assert new.integral['cool'] < 100.0

    def test_hard_threshold_beats_the_deviation_sign(self):
        """둘이 엇갈리면 사용자가 정한 문턱이 이긴다.

        목표가 하드 상한보다 높게 설정된 시설이 실제로 있다(温室環境制御:
        목표 31.97 · temp_max 30). 그러면 "목표까지 더 데워라" 와 "상한을
        넘지 마라" 가 매 사이클 맞선다.
        """
        profiles = _pair()
        st = CoordinatorState()
        # 편차만 보면 가온 요구(목표보다 5°C 낮다). 그런데 하드 상한 위반.
        cmds, _ = _cycle(profiles, st, T_int=20.0, T_target=25.0,
                         internal_extra={'_force_cool': True})

        assert cmds['heat'].reason == REASON_OPPOSING_PARKED, (
            '하드 임계가 편차 부호에 졌다')

    def test_parked_pair_is_not_reported_as_no_gradient(self):
        """0% 로 쉬는 난방기가 화면에서 "이 장치로 할 수 있는 만큼 하고
        있습니다"(무구배 문구)라고 말하면 정반대의 말이 된다."""
        profiles = _pair()
        cmds, _ = _cycle(profiles, CoordinatorState(),
                         T_int=35.0, T_target=25.0)
        assert cmds['heat'].reason != REASON_NO_GRADIENT
