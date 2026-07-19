# coding=utf-8
"""
액추에이터 개도 규약 테스트 (P6).

장치 규약: 모든 액추에이터 cmd_pct = 개도 (100=완전 열림, 0=완전 닫힘).
  천창/측창 100%=열림=환기 최대
  보온커튼 100%=열림/걷힘=단열 없음, 0%=닫힘=보온
  차광막   100%=열림=빛 유입,        0%=닫힘=차광

과거 effect 모델/게이트/광량 오버라이드가 커튼·차광막을 "100%=최대 효과"로
가정해 거꾸로 동작하던 것을 규약(100%=열림)에 맞게 수정했다.
"""

import pytest

from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.safety_gates import (
    SafetyPreGate, PreGateConfig,
)
from aot.functions.utils.env_control.types import ActuatorProfile


# ─────────────────────────────────────────────────────────────────────────────
# effect 모델 방향 (개도 100%=열림 기준)
# ─────────────────────────────────────────────────────────────────────────────

class TestEffectDirectionByOpenness:
    def test_shade_open_warms(self):
        """차광막 열림(100%)=빛 유입 → 온도 상승(↑). 닫으면 차광 효과."""
        sh = build_effect_model('shade', {})
        e = sh['temperature']({'solar': 600.0, 'T_int': 25.0, 'RH_int': 60.0}, 100.0, None)
        assert e.direction == '↑'        # 열수록 일사 유입 → 가온
        assert e.magnitude_native > 0.0

    def test_shade_no_solar_no_effect(self):
        """일사 없으면(야간) 차광막 개도와 무관하게 온도 효과 0."""
        sh = build_effect_model('shade', {})
        e = sh['temperature']({'solar': 0.0, 'T_int': 25.0, 'RH_int': 60.0}, 100.0, None)
        assert e.magnitude_native == 0.0

    def test_curtain_open_loses_heat_when_cold_outside(self):
        """보온커튼 걷힘(100%)=단열 없음 → 추운 밤엔 열손실로 온도 하락(↓)."""
        cu = build_effect_model('curtain', {})
        e = cu['temperature']({'T_int': 22.0, 'T_ext': 5.0}, 100.0, None)
        assert e.direction == '↓'        # 걷으면 외기(추움)로 열 빠짐
        assert e.magnitude_native > 0.0

    def test_curtain_closed_no_effect(self):
        """보온커튼 닫힘(0%)=완전 단열 → 외피 열교환 0."""
        cu = build_effect_model('curtain', {})
        e = cu['temperature']({'T_int': 22.0, 'T_ext': 5.0}, 0.0, None)
        assert e.magnitude_native == 0.0

    def test_shade_vpd_derived_matches_temp(self):
        """차광막 VPD effect(유도)도 규약과 일치: 열림→온도↑→VPD↑."""
        sh = build_effect_model('shade', {})
        ev = sh['vpd']({'solar': 600.0, 'T_int': 25.0, 'RH_int': 60.0}, 100.0, None)
        assert ev.direction == '↑'


# ─────────────────────────────────────────────────────────────────────────────
# 안전 게이트 강제 명령 (개도 규약)
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyGateOpennessConvention:
    def _profiles(self):
        return [
            ActuatorProfile(actuator_id='vent', kind='opening', azimuth_deg=90.0),
            ActuatorProfile(actuator_id='shade', kind='shade'),
            ActuatorProfile(actuator_id='curt', kind='curtain'),
        ]

    def _gate_env(self, **ext):
        e = {'rain': 0.0, 'wind': 1.0, 'T': 20.0}
        e.update(ext)
        return {'external': e, 'internal': {'T': e['T']}, 'now_ts': 0,
                'last_ext_ts': 0, 'last_int_ts': 0}

    def test_heat_deploys_shade_closed(self):
        """폭염: 차광막을 닫아(0%) 햇빛 차단 (과거 100=열림은 반대였음)."""
        cfg = PreGateConfig(heat_ext_threshold=40.0, heat_int_threshold=35.0)
        gate = SafetyPreGate(cfg)
        env = self._gate_env(T=42.0)
        env['internal'] = {'T': 38.0, 'T_max': 38.0}
        res = gate.evaluate(env, self._profiles(), '')
        assert res.forced_commands['shade']['value'] == pytest.approx(0.0)   # 닫힘=차광
        assert res.forced_commands['vent']['value'] == pytest.approx(100.0)  # 열림=환기

    def test_cold_deploys_curtain_closed(self):
        """한파: 보온커튼을 닫아(0%) 단열 (과거 100=열림은 반대였음)."""
        cfg = PreGateConfig(cold_ext_threshold=-2.0, cold_int_threshold=5.0)
        gate = SafetyPreGate(cfg)
        env = self._gate_env(T=-5.0)
        env['internal'] = {'T': 3.0, 'T_min': 3.0}
        res = gate.evaluate(env, self._profiles(), '')
        assert res.forced_commands['curt']['value'] == pytest.approx(0.0)    # 닫힘=보온
        assert res.forced_commands['vent']['value'] == pytest.approx(0.0)    # 닫힘

    def test_wind_closes_external_vents_not_internal_screens(self):
        """강풍: 외부 개구부만 폐쇄. 내부 시설(차광막·보온커튼)은 비바람 미노출 →
        강제하지 않는다(직전 위치 유지)."""
        cfg = PreGateConfig(wind_threshold=12.0)
        gate = SafetyPreGate(cfg)
        res = gate.evaluate(self._gate_env(wind=20.0), self._profiles(), '')
        assert res.forced_commands['vent']['value'] == pytest.approx(0.0)    # 외부 폐쇄
        assert 'shade' not in res.forced_commands                            # 내부 미강제
        assert 'curt' not in res.forced_commands

    def test_rain_closes_external_vents_not_internal_screens(self):
        """강우: 외부 개구부만 폐쇄. 내부 스크린은 강제하지 않는다."""
        cfg = PreGateConfig(rain_threshold=0.5)
        gate = SafetyPreGate(cfg)
        res = gate.evaluate(self._gate_env(rain=1.0), self._profiles(), '')
        assert res.forced_commands['vent']['value'] == pytest.approx(0.0)
        assert 'shade' not in res.forced_commands
        assert 'curt' not in res.forced_commands


# ─────────────────────────────────────────────────────────────────────────────
# 장치 위치 ↔ 코디네이터 개도 역변환 (prev_commands desync 수정)
# ─────────────────────────────────────────────────────────────────────────────

class TestMotorApertureRoundTrip:
    """_sync_prev_from_devices 의 motor→aperture 역변환이 map_aperture_to_motor 와
    정확히 역관계여야 한다. (어긋나면 슬루 기준이 틀려 반대로 움직임)"""

    def _inverse(self, motor, s, e):
        return ((motor - s) / (e - s) * 100.0) if e > s else motor

    def test_roundtrip_shade(self):
        """차광막(작동범위 0–100): 개도=모터 항등."""
        from aot.functions.utils.env_control.types import CmdConstraints
        cc = CmdConstraints(effective_start_pct=0.0, effective_end_pct=100.0)
        for ap in (0.0, 25.0, 50.0, 80.0, 100.0):
            motor = cc.map_aperture_to_motor(ap)
            assert abs(self._inverse(motor, 0.0, 100.0) - ap) < 1e-6

    def test_roundtrip_opening_operating_range(self):
        """개구부(작동범위 15–100): 개도↔모터 선형 역변환 일치."""
        from aot.functions.utils.env_control.types import CmdConstraints
        s, e = 15.0, 100.0
        cc = CmdConstraints(effective_start_pct=s, effective_end_pct=e)
        for ap in (0.0, 20.0, 50.0, 100.0):
            motor = cc.map_aperture_to_motor(ap)        # 0→15, 100→100
            assert abs(self._inverse(motor, s, e) - ap) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# 스크린 idle 기본값: 게이트(무구배) 시 걷힘(100)으로 수렴
# ─────────────────────────────────────────────────────────────────────────────

class TestScreenIdleRetracts:
    """할 일 없는(게이트된) 보온커튼·차광막은 닫힘(0=단열/차광)이 아니라
    걷힘(100=열림)으로 수렴해야 한다. (닫으면 더운 낮에 열을 가두거나 빛 차단)"""

    def test_curtain_gated_retracts_to_open(self):
        from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
        from aot.functions.utils.env_control.situation import assess
        from aot.functions.utils.env_control.types import (
            ActuatorProfile, CmdConstraints, TargetVar)
        from aot.functions.utils.env_control.effect_functions import build_effect_model

        # 보온커튼: safe_default=100(걷힘). 무구배(내외 동일 온도) → 게이트
        cur = ActuatorProfile(
            actuator_id='cur', kind='curtain',
            effect_model=build_effect_model('curtain', {}),
            cmd_constraints=CmdConstraints(effective_start_pct=0.0, effective_end_pct=100.0),
            gains={'kp': 1.0, 'ki': 0.2}, safe_default=100.0)
        target = {'temperature': TargetVar(24.0, 0.5, 1.0)}
        st = CoordinatorState(integral={'cur': 20.0})   # 일부 배치된 상태에서 시작
        last = None
        for _ in range(12):
            internal = {'T': 25.0, 'RH': 60.0, 'CO2': 400.0}
            external = {'T': 25.0, 'RH': 60.0, 'wind': 1.0, 'solar': 50.0}  # ΔT=0 → 무구배
            report, _ = assess(target, internal, external,
                               cycle_sec=600.0, now_ts=1767240000.0)
            cmds, st = coordinate(report, [cur], st)
            last = cmds['cur']
        # 걷힘(100=열림) 쪽으로 수렴 (닫힘 0 이 아님)
        assert last.aperture > 90.0, f"게이트된 보온커튼이 걷히지 않음: {last.aperture}%"
