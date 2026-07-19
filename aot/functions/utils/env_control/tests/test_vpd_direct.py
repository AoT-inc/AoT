# coding=utf-8
"""
VPD 우선 직접제어 테스트 (P6).

정책: VPD 측정값+목표가 있으면 VPD 가 1차 제어변수(다른 값보다 우선)이고,
VPD 가 없으면 온/습도가 후순위 제어 기준이 된다.

배경(현장 aot-005): 기존엔 VPD 목표를 T/RH 로 분해해 제어 → ∂VPD/∂T 로 인해
작은 VPD 편차(0.116 kPa)가 큰 온도 오차(~2°C)로 증폭되어 창호가 급개방했다.
VPD 를 직접 제어하면 이 증폭이 사라지고 응답이 실제 VPD 편차에 비례한다.
"""

import math
import statistics

from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
from aot.functions.utils.env_control.situation import assess
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, TargetVar,
)
from aot.functions.utils.env_control.effect_functions import build_effect_model


def _svp(T):
    return 0.6108 * math.exp(17.27 * T / (T + 237.3))


def _vpd(T, RH):
    return max(0.0, (1 - RH / 100.0) * _svp(T))


def _opening(aid='v1'):
    return ActuatorProfile(
        actuator_id=aid, kind='opening',
        effect_model=build_effect_model('opening', {}),   # 유도 VPD effect 포함
        cmd_constraints=CmdConstraints(slew_per_cycle=20.0, min_on_pct=5.0),
        gains={'kp': 1.0, 'ki': 0.2}, area_m2=50.0, azimuth_deg=90.0)


def _target(vpd_target=0.8):
    return {
        'vpd':         TargetVar(vpd_target, 0.1, 1.2, 'kPa'),
        'temperature': TargetVar(24.0, 0.5, 0.8),
        'humidity':    TargetVar(60.0, 3.0, 0.8),
    }


class TestEffectivenessGate:
    """무구배(내외차 거의 없음)에서 환기 액추에이터가 헛돌지 않는다 (권한 게이트).

    배경: 결합 drive 의 e_norm 은 정규화되어 절대 유효도를 반영하지 못해, 무구배에도
    편차 비례로 명령 → 성과 없이 작동시간만 늘고 적분이 와인드업(현장 aot-005 환기팬).
    유효도(g=magnitude/pband) 하한 게이트로 차단한다.
    """
    def _fan(self):
        # area_m2 없음 → GIS af=1, 무구배 시 유효도 낮음(저권한)
        return ActuatorProfile(
            actuator_id='fan', kind='exhaust_fan',
            effect_model=build_effect_model('exhaust_fan', {}),
            cmd_constraints=CmdConstraints(slew_per_cycle=20.0, min_on_pct=5.0),
            gains={'kp': 1.0, 'ki': 0.2})

    def _assess(self, T, RH, Text, RHext, wind):
        internal = {'T': T, 'RH': RH, 'CO2': 400.0, 'VPD': _vpd(T, RH)}
        external = {'T': Text, 'RH': RHext, 'wind': wind, 'solar': 50.0}
        return assess(_target(0.98), internal, external,
                      cycle_sec=600.0, now_ts=1767240000.0)[0]

    def test_no_gradient_fan_winds_down(self):
        """무구배 지속 시 와인드업된 배기팬이 점차 꺼진다(NO_GRADIENT)."""
        from aot.functions.utils.env_control.log_channels import REASON_NO_GRADIENT
        fan = self._fan()
        st = CoordinatorState(integral={'fan': 100.0}, prev_commands={'fan': 100.0})
        last = None
        for _ in range(8):
            report = self._assess(25.3, 51.4, 24.7, 51.0, 0.5)   # VPD_ext≈VPD_int
            cmds, st = coordinate(report, [fan], st)
            last = cmds['fan']
        assert last.reason == REASON_NO_GRADIENT
        assert last.aperture == 0.0, f"무구배인데 팬이 계속 작동: {last.aperture}%"

    def test_real_gradient_fan_active(self):
        """실제 구배(ΔT≥약1°C)가 있으면 배기팬이 정상 작동한다 (창 닫힘 가정)."""
        from aot.functions.utils.env_control.log_channels import REASON_PRIMARY
        fan = self._fan()
        st = CoordinatorState()   # 개구부 없음 → vent_open_frac=0 (창 닫힘)
        report = self._assess(26.0, 60.0, 20.0, 78.0, 1.0)   # 저녁 냉각 구배
        cmds, _ = coordinate(report, [fan], st)
        assert cmds['fan'].reason == REASON_PRIMARY
        assert cmds['fan'].aperture > 0.0

    def test_fan_useless_when_vents_open(self):
        """창이 열려 있으면(압력차 없음) 구배가 있어도 배기팬은 무력 → idle.

        덕트 없는 벽면 배기팬은 개구부가 닫혀 압력차가 생겨야 작동한다. 측창·천창이
        열려 있으면 압력이 안 걸려 헛돈다(현장 aot-005). vent_open_frac 으로 차단.
        """
        from aot.functions.utils.env_control.log_channels import REASON_NO_GRADIENT
        fan = self._fan()
        op = ActuatorProfile(
            actuator_id='op', kind='opening',
            effect_model=build_effect_model('opening', {}),
            cmd_constraints=CmdConstraints(slew_per_cycle=20.0, min_on_pct=5.0),
            gains={'kp': 1.0, 'ki': 0.2}, area_m2=50.0, azimuth_deg=90.0)
        # 개구부가 이미 90% 열린 상태(직전 명령) → 압력차 없음
        st = CoordinatorState(prev_commands={'op': 90.0}, integral={'fan': 80.0})
        report = self._assess(26.0, 60.0, 20.0, 78.0, 1.0)   # 구배는 충분
        cmds, _ = coordinate(report, [fan, op], st)
        # 구배가 있어도 창이 열려 배기팬은 무력 → NO_GRADIENT(권한 없음)
        assert cmds['fan'].reason == REASON_NO_GRADIENT
        # 측창은 정상 작동
        assert cmds['op'].aperture > 0.0


class TestVpdPrimary:
    def test_vpd_present_controls_vpd_not_temperature(self):
        """VPD 측정 있으면 deviation 에 'vpd' 만(온/습도는 제어목표에서 제외)."""
        T, RH = 22.8, 67.0
        internal = {'T': T, 'RH': RH, 'CO2': 600.0, 'VPD': _vpd(T, RH)}
        external = {'T': 19.0, 'RH': 80.0, 'wind': 1.0, 'solar': 50.0}
        report, _ = assess(_target(), internal, external,
                           cycle_sec=600.0, now_ts=1767240000.0)
        assert 'vpd' in report.deviation_native
        assert 'temperature' not in report.deviation_native
        assert 'humidity' not in report.deviation_native

    def test_vpd_absent_falls_back_to_temperature(self):
        """VPD 측정 없으면(internal 에 VPD 없음) 온/습도가 제어 기준(폴백)."""
        internal = {'T': 26.0, 'RH': 60.0, 'CO2': 600.0}   # VPD 미측정
        external = {'T': 20.0, 'RH': 70.0, 'wind': 1.0, 'solar': 50.0}
        report, _ = assess(_target(), internal, external,
                           cycle_sec=600.0, now_ts=1767240000.0)
        assert 'vpd' not in report.deviation_native       # 측정 없음 → 제어 안 함
        assert 'temperature' in report.deviation_native    # 폴백
        assert 'humidity' in report.deviation_native

    def test_small_vpd_deviation_gentle_response(self):
        """작은 VPD 초과(목표+0.12)에 창호가 급개방하지 않는다(온도 증폭 제거).

        기존(분해)이라면 0.12 kPa 가 ~2°C 온도오차로 증폭→완전개방. VPD 직접제어는
        실제 VPD 편차에 비례한 완만한 개도로 평형 수렴해야 한다.
        """
        p = _opening()
        st = CoordinatorState()
        T, RH = 22.8, 67.0
        ap, Vs = [], []
        for _ in range(30):
            V = _vpd(T, RH)
            internal = {'T': T, 'RH': RH, 'CO2': 600.0, 'VPD': V}
            external = {'T': 19.0, 'RH': 80.0, 'wind': 1.0, 'solar': 50.0}
            report, _ = assess(_target(0.8), internal, external,
                               cycle_sec=600.0, now_ts=1767240000.0)
            cmds, st = coordinate(report, [p], st)
            a = cmds['v1'].aperture
            ap.append(a)
            Vs.append(V)
            T += (19.0 - T) * 0.06 * (a / 100.0) + 0.02
            RH += (80.0 - RH) * 0.05 * (a / 100.0)

        # 급개방 없음: 0.12 kPa 초과에 완전개방(100%)하지 않는다
        assert max(ap) < 40.0, f"작은 VPD 편차에 과대 개방: {max(ap):.0f}%"
        # VPD 가 목표(0.8) 쪽으로 수렴
        assert Vs[-1] < Vs[0], f"VPD 미수렴: {Vs[0]:.3f}→{Vs[-1]:.3f}"
        # 내부 평형으로 안정(끝에 0/100 고착 아님)
        settled = ap[-10:]
        assert max(settled) - min(settled) < 12.0, "정착 진동"
