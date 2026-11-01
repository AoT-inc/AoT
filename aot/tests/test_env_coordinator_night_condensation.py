# coding=utf-8
"""야간 파킹의 결로 탈출구 — 결로가 임박했고, 환기가 그것을 실제로 덜어 줄 때만 연다.

"결로 위험이면 닫는다" 는 거꾸로다 — 닫으면 수분이 갇힌다. 그러나 차가운 외기는
실내를 식혀 상대습도를 올릴 수도 있어서, "실외가 건조하다" 만으로 열지 않고
외기를 조금 섞었을 때 이슬점 여유가 벌어지는지 계산한다.
"""
from unittest.mock import MagicMock

from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    condensation_escape, dewpoint_margin)


def test_cold_humid_outside_air_does_not_help():
    """실내 15 °C·95 %, 실외 5 °C·90 % — 섞으면 포화에 더 가깝다."""
    assert not condensation_escape(15, 95, 5, 90)


def test_cool_dry_outside_air_helps():
    assert condensation_escape(15, 95, 12, 60)


def test_warm_humid_outside_air_does_not_help():
    assert not condensation_escape(20, 90, 25, 90)


def test_no_risk_no_escape():
    assert dewpoint_margin(18, 80) > 3.0
    assert not condensation_escape(18, 80, 10, 50)


def test_unknown_outdoor_keeps_the_parking():
    assert not condensation_escape(15, 95, None, None)


def test_exit_needs_more_margin_than_entry():
    """여유 2.5 °C: 새로 들어가지는 않지만, 이미 탈출 중이면 유지한다(히스테리시스)."""
    import math
    # 여유가 약 2.5 °C 인 습도를 찾는다
    rh = next(r for r in [x / 10 for x in range(990, 700, -1)]
              if dewpoint_margin(18, r) >= 2.5)
    assert not condensation_escape(18, rh, 10, 50, was_escaping=False)
    assert condensation_escape(18, rh, 10, 50, was_escaping=True)


def _coord():
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.unique_id = 'fn'
    c.night_vent_park = True
    c.night_vent_basis = 'clock'
    c.night_vent_start = '00:00'
    c.night_vent_end = '23:59'
    from datetime import datetime
    c._facility_local_now = lambda: datetime(2026, 9, 22, 2, 0)
    return c


def test_parking_holds_without_condensation_risk():
    c = _coord()
    assert c._night_vent_parked({'T': 18, 'RH': 70}, {'T': 10, 'RH': 50})


def test_parking_lifts_when_venting_relieves_condensation():
    c = _coord()
    assert not c._night_vent_parked({'T': 15, 'RH': 95}, {'T': 12, 'RH': 60})
    assert c.logger.error.called, '파킹을 푼 사실을 남긴다'


def test_parking_holds_when_outside_air_would_make_it_worse():
    c = _coord()
    assert c._night_vent_parked({'T': 15, 'RH': 95}, {'T': 5, 'RH': 90})


def test_recorded_night_values_2026_10_01():
    """실외 이슬점이 실내보다 **높거나 비슷한** 밤에는 열지 않는다(로컬 3포장·쿠마모토).

    VPD 로는 실외가 더 건조해 보였고(따뜻해서) 여유도 0.2~0.3 °C 늘어나 창이 열렸다 —
    실제로는 습기를 들이는 중이었다.
    """
    cases_closed = [
        (16.3, 88, 18.8, 72),     # 3포장 20:40 — 이슬점 차 0.7
        (15.3, 90, 19.7, 75),     # 22:00 — 실외 이슬점이 더 높다
        (14.8, 91, 20.1, 80),     # 23:00
        (14.3, 93, 20.8, 70),     # 01:00
        (14.8, 92, 20.2, 88),     # 쿠마모토 03:20
    ]
    for c in cases_closed:
        assert not condensation_escape(*c), c
    # 실외 이슬점이 훨씬 낮아진 새벽에는 열 수 있다
    assert condensation_escape(14.8, 94, 18.3, 49)
    assert condensation_escape(15.4, 95, 16.8, 48)


def test_outdoor_dewpoint_gap_is_required():
    # 여유가 늘더라도(따뜻한 외기) 이슬점이 더 높으면 열지 않는다
    assert not condensation_escape(15, 95, 25, 80)


def test_winter_heating_never_escapes_by_opening():
    """난방 중인 겨울 밤 — 온도차가 커서 열면 열을 버린다."""
    for c in [(20, 95, 0, 80), (20, 95, -5, 70), (18, 92, 5, 60)]:
        assert not condensation_escape(*c), c


def test_a_heat_demand_blocks_the_escape():
    c = _coord()
    c.night_vent_basis = 'clock'
    assert c._night_vent_parked({'T': 15, 'RH': 95, '_force_heat': True},
                                {'T': 12, 'RH': 60})


def test_warm_side_blocks_escape_into_colder_air():
    """보온 쪽(목표 근처 이하)에서는 실외가 1 °C 넘게 차가우면 결로 탈출로 열지 않는다."""
    case = (15, 95, 12, 60)
    assert condensation_escape(*case)                      # 보온 요구 없음 — 종전대로 연다
    assert not condensation_escape(*case, warm_side=True)  # 3 °C 더 찬 외기 — 열지 않는다


def test_warm_side_still_escapes_into_warmer_air():
    """외기가 더 따뜻하면 열어도 온도가 오르므로 보온 쪽이어도 막지 않는다."""
    assert condensation_escape(14.8, 94, 18.3, 49, warm_side=True)


def test_parking_holds_when_warm_side_even_if_condensation_relievable():
    c = _coord()
    assert c._night_vent_parked({'T': 15, 'RH': 95}, {'T': 12, 'RH': 60}, warm_side=True)
