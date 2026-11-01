# coding=utf-8
"""가짜 시설의 통합 payload 고정 자료 — 읽기 모듈·연결 시험이 같이 쓴다."""

FAC = "fac-parity"


def _act(uid, kind, slot_key=None, **extra):
    d = {"output_uuid": uid, "output_name": uid, "output_type": "virtual_on_off_single", "slot_key": slot_key,
         "kind": kind, "capabilities": [], "fitting_ids": [], "vent_openings_area_m2": 0.0, "vent_openings_count": 0}
    d.update(extra)
    return d


def _integ(vent_source="envelope"):
    return {
        "facility_uuid": FAC, "name": "가짜 시설", "vent_openings": [], "bays": [],
        "capacity_meta": {"volume_m3": 900.0, "u_effective": 5.0, "envelope_m2": 1200.0, "vent_open_m2": 60.0,
                          "vent_open_source": vent_source, "transmittance": 0.8},
        "computed": {"roof_m2": 700.0},
        "irrigation_summary": {"totals": {"flow_lpm": 20.0}},
        "actuators_resolved": [
            _act("win-g1", "opening", "side_vent_a", vent_openings_area_m2=12.5, vent_form="side"),     # 개구부 면적(G1)
            _act("win-s1", "opening", "roof_vent_1", vent_form="ridge"),                               # 슬롯 균등 분할
            _act("win-s2", "opening", "roof_vent_2", vent_form="ridge"),
            _act("fan-r", "exhaust_fan", "exhaust_fan", rated_m3h=48000.0),                            # 적힌 풍량
            _act("fan-d", "intake_fan", "intake_fan"),                                                 # 기본값 3000
            _act("fan-c", "circulation_fan", "circulation_fan"),                                       # 기본값 1500
            _act("heat", "heater", "heater", rated_kW_thermal=30.0),
            _act("heat0", "heater", "heater_2"),                                                       # 정격 모름
            _act("tc", "curtain", "thermal_curtain"),                                                  # 외피 면적
            _act("sh", "shade", "shade_curtain"),                                                      # 지붕 면적
            _act("fog", "fogger", "fogger", nozzle={"sprinkler_flow_lph": 120.0}),                     # 노즐 유량
            _act("fog0", "fogger", "fogger_2"),                                                        # 노즐 없음 — 시설 합계로 메우지 않는다
        ],
    }
