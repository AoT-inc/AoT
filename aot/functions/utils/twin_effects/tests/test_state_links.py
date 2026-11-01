# coding=utf-8
import pytest

from aot.functions.utils.twin_effects import links as L, reader as R, state as S
from aot.functions.utils.twin_effects.tests.fixture_integ import _integ


# ── 상태 출처 ─────────────────────────────────────────────────────────────────────
def test_basis_priority_on_off_kinds():
    assert S.choose_basis("heater", True, True, True) == S.ACTUAL
    assert S.choose_basis("heater", False, True, True) == S.DUTY_LOG
    assert S.choose_basis("heater", False, False, True) == S.COMMAND
    assert S.choose_basis("heater", False, False, False) == S.NONE


def test_position_kinds_do_not_use_duty_log():
    """창·차광·커튼의 가동 이력은 움직인 시간이지 위치가 아니다."""
    for k in ("opening", "shade", "curtain", "window"):
        assert S.is_position_kind(k)
        assert S.choose_basis(k, False, True, False) == S.NONE
        assert S.choose_basis(k, False, True, True) == S.COMMAND
    assert not S.is_position_kind("exhaust_fan")


def test_command_is_estimated_and_left_out_of_sync():
    assert S.estimated(S.COMMAND) and not S.estimated(S.DUTY_LOG) and not S.estimated(S.ACTUAL)
    assert S.COMMAND not in S.SYNC_BASES and S.DUTY_LOG in S.SYNC_BASES and S.ACTUAL in S.SYNC_BASES


# ── 가동 이력 → 계단 ──────────────────────────────────────────────────────────────
def test_duty_step_basic():
    t, v = S.duty_step_series([(100.0, 50.0), (300.0, 100.0)], 0.0, 500.0)
    assert list(zip(t, v)) == [(0.0, 0.0), (100.0, 100.0), (150.0, 0.0), (300.0, 100.0), (400.0, 0.0), (500.0, 0.0)]


def test_duty_step_event_spanning_window_start_and_end():
    t, v = S.duty_step_series([(-50.0, 100.0), (450.0, 100.0)], 0.0, 500.0)
    assert (t[0], v[0]) == (0.0, 100.0)                      # 구간 앞에서 켜져 걸쳐 옴
    assert (t[-1], v[-1]) == (500.0, 100.0)                  # 구간 끝까지 켜져 있음


def test_duty_step_overlaps_merge_and_no_events_is_off():
    t, v = S.duty_step_series([(10.0, 100.0), (50.0, 100.0)], 0.0, 200.0)
    assert list(zip(t, v)) == [(0.0, 0.0), (10.0, 100.0), (150.0, 0.0), (200.0, 0.0)]
    assert S.duty_step_series([], 0.0, 100.0) == ([0.0, 100.0], [0.0, 0.0])


def test_duty_negative_duration_read_by_magnitude():
    t, v = S.duty_step_series([(10.0, -20.0)], 0.0, 100.0)
    assert (10.0, 100.0) in list(zip(t, v)) and (30.0, 0.0) in list(zip(t, v))


# ── 연결 줄 ───────────────────────────────────────────────────────────────────────
def _rows(extra=None, state=None, overrides=None):
    integ = _integ()
    integ["actuators_resolved"].extend(extra or [])
    read = R.devices_from_integration(integ)
    return {r["id"]: r for r in L.build_rows(read, state, overrides)}, read


def test_every_device_gets_a_line_with_channel_and_status():
    rows, read = _rows()
    assert rows["heat"]["channel"] == "heat" and rows["heat"]["status"] == "modeled"
    assert rows["fog"]["channel"] == "fog" and rows["fog"]["status"] == "partial"      # 잎 젖음 미반영
    assert rows["win-g1"]["channel"] == "vent"
    assert len(rows) == len(read.devices)


def test_unmodeled_kind_is_stated_not_dropped():
    extra = [{"output_uuid": "lamp", "output_name": "보광", "output_type": "x", "slot_key": None, "kind": "lighting",
              "capabilities": [], "fitting_ids": [], "vent_openings_area_m2": 0.0, "vent_openings_count": 0}]
    rows, _ = _rows(extra)
    assert rows["lamp"]["status"] == "unmodeled" and rows["lamp"]["channel"] is None
    assert "par" in rows["lamp"]["unmodeled_effects"]


def test_unknown_kind_asks_for_a_kind_and_override_makes_it_a_device():
    extra = [{"output_uuid": "x1", "output_name": "범용", "output_type": "x", "slot_key": None, "kind": None,
              "capabilities": [], "fitting_ids": [], "vent_openings_area_m2": 0.0, "vent_openings_count": 0,
              "fitting_kind": "mystery"}]
    rows, read = _rows(extra)
    assert rows["x1"]["status"] == "unknown" and rows["x1"]["needs_kind"] and rows["x1"]["channel"] is None
    ov = L.validate_overrides({"devices": {"x1": {"kind": "heater"}}})
    rows2, _ = _rows(extra, overrides=ov)
    assert rows2["x1"]["channel"] == "heat" and rows2["x1"]["kind_from"] == "override" and not rows2["x1"]["needs_kind"]
    assert "x1" in {d.actuator_id for d in L.effective_devices(read, ov)}


def test_override_never_changes_a_recognised_kind():
    ov = L.validate_overrides({"devices": {"heat": {"kind": "cooler"}}})
    rows, read = _rows(overrides=ov)
    assert rows["heat"]["kind"] == "heater" and rows["heat"]["kind_from"] == "location"
    assert {d.actuator_id: d.kind for d in L.effective_devices(read, ov)}["heat"] == "heater"


def test_exclude_removes_from_effects_and_summary():
    ov = L.validate_overrides({"devices": {"heat": {"exclude": True}}})
    rows, read = _rows(overrides=ov)
    assert rows["heat"]["excluded"]
    assert "heat" not in {d.actuator_id for d in L.effective_devices(read, ov)}
    s = L.summarize(list(rows.values()))
    assert s["excluded"] == 1 and s["total"] == len(rows) - 1


def test_validate_overrides_rejects_garbage():
    with pytest.raises(L.OverrideError):
        L.validate_overrides({"devices": {"a": {"kind": "no-such-kind"}}})
    with pytest.raises(L.OverrideError):
        L.validate_overrides({"devices": {"a": {"ratings": {}}}})
    with pytest.raises(L.OverrideError):
        L.validate_overrides({"rows": {}})
    assert L.validate_overrides(None) == {}
    assert L.validate_overrides({"devices": {"a": {}}}) == {}


def test_field_domain_uses_roles():
    assert "irrigation_drip" in L.C.all_kinds("field")
    assert L.validate_overrides({"devices": {"v1": {"kind": "irrigation_drip"}}}, "field") == \
        {"v1": {"kind": "irrigation_drip"}}
    with pytest.raises(L.OverrideError):
        L.validate_overrides({"devices": {"v1": {"kind": "heater"}}}, "field")


def test_summary_counts_no_state_and_estimated():
    state = {"heat": {"basis": "duty_log"}, "fan-r": {"basis": "command"}}
    rows, _ = _rows(state=state)
    s = L.summarize(list(rows.values()))
    assert s["estimated"] == 1
    assert s["no_state"] == len([r for r in rows.values() if r["channel"] and r["basis"] == "none"])
    assert rows["heat"]["estimated"] is False and rows["fan-r"]["estimated"] is True


def test_effects_options_shape_matches_what_the_model_part_reads():
    rows, read = _rows()
    devs = L.effective_devices(read, {})
    o = L.effects_options(devs, {"heat": "duty_log"})
    d = {x["id"]: x for x in o["devices"]}
    assert d["heat"]["basis"] == "duty_log" and d["heat"]["ratings"]["rated_kW_thermal"] == 30.0
    assert d["heat0"]["ratings"] == {} and d["heat0"]["basis"] == "none"
