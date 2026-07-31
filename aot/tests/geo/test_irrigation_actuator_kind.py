# coding=utf-8
"""
관수 액추에이터 → env_control ActuatorProfile.kind 해석 테스트.

2026-07-31 이전에는 관수 밸브가 무조건 env 등록 제외였다
(_ACTUATOR_UI_KIND_TO_KIND['irrigation_valve'] = None,
 _FITTING_KIND_TO_ACTUATOR_KIND['irrigation_*'] = 'irrigation' — 후자는
 ACTUATOR_KINDS 에 없는 이름이라 프로필이 만들어져도 effect 모델이 비었다).

그래서 통합환경제어에 VPD 를 낮출 액추에이터가 하나도 잡히지 않았고,
VPD 관리를 별도 PID Function 으로 분리해 운영할 수밖에 없었다.
이제는 노즐 구성으로 판정한다 — 분무 노즐이 달려 있으면 fogger, 드립
전용이면 여전히 제외.
"""

from aot.aot_flask.geo.facility_integration import (
    _fitting_actuator_kind, _irrigation_actuator_kind,
)
from aot.aot_flask.geo.irrigation_nozzles import nozzles_by_actuator


def _fittings(sub_type='sprinkler', flow_lph=40.0, radius_m=2.0):
    return [
        {'kind': 'irrigation_layer', 'id': 'L1', 'height_m': 2.0,
         'actuator_id': 'valve_01'},
        {'kind': 'irrigation_device', 'layer_id': 'L1', 'pipe_id': 'p1',
         'sub_type': sub_type, 'orientation': 'down',
         'flow_lph': flow_lph, 'radius_m': radius_m,
         'position': {'x': 0.0, 'y': 2.0, 'z': 0.0}},
    ]


class TestIrrigationActuatorKind:
    def test_sprinkler_layer_becomes_fogger(self):
        nozzle_map = nozzles_by_actuator(_fittings())
        assert _irrigation_actuator_kind(nozzle_map['valve_01']) == 'fogger'

    def test_drip_only_layer_stays_excluded(self):
        nozzle_map = nozzles_by_actuator(_fittings(sub_type='drip'))
        assert _irrigation_actuator_kind(nozzle_map['valve_01']) is None

    def test_missing_nozzle_info_excluded(self):
        assert _irrigation_actuator_kind(None) is None
        assert _irrigation_actuator_kind({}) is None


class TestFittingActuatorKind:
    def test_irrigation_layer_resolved_via_nozzle_map(self):
        fittings = _fittings()
        nozzle_map = nozzles_by_actuator(fittings)
        layer = fittings[0]
        assert _fitting_actuator_kind(layer, nozzle_map) == 'fogger'

    def test_irrigation_layer_without_map_is_none(self):
        """노즐 맵 없이 호출하면 등록하지 않는다 (과거의 잘못된 'irrigation' 대신)."""
        assert _fitting_actuator_kind(_fittings()[0]) is None

    def test_non_irrigation_kinds_unchanged(self):
        assert _fitting_actuator_kind({'kind': 'side_window'}) == 'opening'
        assert _fitting_actuator_kind({'kind': 'shade_curtain'}) == 'shade'
        assert _fitting_actuator_kind(
            {'kind': 'fan', 'fan_role': 'exhaust_fan'}) == 'exhaust_fan'
        assert _fitting_actuator_kind({'kind': 'bench'}) is None


class TestFixtureFittingKinds:
    """설비(Fixtures) 팔레트로 배치한 실내 장치가 등록되는지.

    디자이너는 가습기·난방기 등을 배치하고 Output 까지 물릴 수 있는데
    (geo_facility.html 의 배치 버튼과 인스펙터 종류 드롭다운), 매핑 표에
    없으면 통합환경제어가 조용히 버렸다. 사용자는 붙여 놨는데 등록이 안 되고,
    VPD 를 낮출 액추에이터가 하나도 없는 상태가 된다
    (2026-07-31 aot-005 육묘장에서 실제 발생).
    """

    def test_fogger_fitting_registers(self):
        assert _fitting_actuator_kind(
            {'kind': 'fogger', 'actuator_id': 'x'}) == 'fogger'

    def test_other_fixture_kinds_register(self):
        for fk, expect in (('heater', 'heater'), ('cooler', 'cooler'),
                           ('co2_injector', 'co2_injector'),
                           ('lighting', 'lighting')):
            assert _fitting_actuator_kind({'kind': fk}) == expect

    def test_registered_kinds_are_valid_actuator_kinds(self):
        """매핑 결과가 전부 ACTUATOR_KINDS 안에 있어야 한다.

        과거 'irrigation' 처럼 존재하지 않는 이름을 넣으면 프로필은 만들어지되
        효과 모델이 비어 조율 대상에서 조용히 빠진다.
        """
        from aot.aot_flask.geo.facility_integration import (
            _FITTING_KIND_TO_ACTUATOR_KIND,
        )
        from aot.functions.utils.env_control.types import ACTUATOR_KINDS
        for fk, kind in _FITTING_KIND_TO_ACTUATOR_KIND.items():
            assert kind in ACTUATOR_KINDS, (fk, kind)
