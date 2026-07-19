# coding=utf-8
"""Unit tests for aot.utils.weekly_schedule."""
import json
import pytest
import pytz
from unittest.mock import patch
from datetime import datetime

from aot.utils.weekly_schedule import (
    time_to_minutes, minutes_to_hhmm,
    from_legacy, parse_schedule, validate, _validate_entry,
    active_entry_now, is_continuity_boundary,
    get_today_idx, to_legacy, build_warnings,
    day_action_enabled,
)


# ---------------------------------------------------------------------------
# time_to_minutes / minutes_to_hhmm
# ---------------------------------------------------------------------------

def test_time_to_minutes_normal():
    assert time_to_minutes("16:30") == 990
    assert time_to_minutes("00:00") == 0
    assert time_to_minutes("23:59") == 1439
    assert time_to_minutes("24:00") == 1440

def test_time_to_minutes_invalid():
    with pytest.raises(ValueError): time_to_minutes("25:00")
    with pytest.raises(ValueError): time_to_minutes("abc")
    with pytest.raises(ValueError): time_to_minutes("")

def test_minutes_to_hhmm():
    assert minutes_to_hhmm(0)    == "00:00"
    assert minutes_to_hhmm(990)  == "16:30"
    assert minutes_to_hhmm(1440) == "24:00"

def test_minutes_roundtrip():
    for t in ["00:00", "09:15", "16:30", "23:59", "24:00"]:
        assert minutes_to_hhmm(time_to_minutes(t)) == t


# ---------------------------------------------------------------------------
# from_legacy
# ---------------------------------------------------------------------------

def test_from_legacy_all_days():
    s = from_legacy("16:30", "19:00", None, 3600)
    assert s["version"] == 1
    assert s["mode"] == "shared"
    assert s["shared"]["start"] == "16:30"
    assert s["shared"]["period"] == 3600
    for i in range(7):
        assert s["days"][str(i)]["enabled"] is True
        assert s["days"][str(i)]["start"] == "16:30"

def test_from_legacy_specific_days():
    s = from_legacy("08:00", "12:00", "1,3,5", 1800)
    for i in range(7):
        expected = i in {1, 3, 5}
        assert s["days"][str(i)]["enabled"] == expected

def test_from_legacy_midnight_crossing_clamped():
    s = from_legacy("22:00", "02:00", None, 3600)
    assert s["shared"]["start"] == "22:00"
    assert s["shared"]["end"] == "24:00"

def test_from_legacy_empty_weekday_string():
    s = from_legacy("16:30", "19:00", "", 3600)
    for i in range(7):
        assert s["days"][str(i)]["enabled"] is True


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def _make_valid_schedule():
    return from_legacy("16:30", "19:00", None, 3600)

def test_validate_valid():
    assert validate(_make_valid_schedule()) == []

def test_validate_wrong_version():
    s = _make_valid_schedule()
    s["version"] = 2
    assert len(validate(s)) > 0

def test_validate_invalid_mode():
    s = _make_valid_schedule()
    s["mode"] = "weekly"
    assert any("mode" in e for e in validate(s))

def test_validate_start_after_end():
    s = _make_valid_schedule()
    s["shared"]["start"] = "20:00"
    s["shared"]["end"] = "16:00"
    errors = validate(s)
    assert any("before" in e for e in errors)

def test_validate_end_at_midnight_ok():
    s = _make_valid_schedule()
    s["shared"]["end"] = "24:00"
    for i in range(7):
        s["days"][str(i)]["end"] = "24:00"
    assert validate(s) == []

def test_validate_end_zero_invalid():
    s = _make_valid_schedule()
    s["shared"]["end"] = "00:00"
    errors = validate(s)
    assert any("00:00" in e for e in errors)

def test_validate_bad_period():
    s = _make_valid_schedule()
    s["shared"]["period"] = -1
    errors = validate(s)
    assert any("period" in e for e in errors)

def test_validate_missing_day():
    s = _make_valid_schedule()
    del s["days"]["3"]
    errors = validate(s)
    assert any("3" in e for e in errors)


# ---------------------------------------------------------------------------
# parse_schedule
# ---------------------------------------------------------------------------

def test_parse_schedule_from_json_string():
    s = _make_valid_schedule()
    s2 = parse_schedule(json.dumps(s))
    assert s2 is not None
    assert s2["mode"] == "shared"

def test_parse_schedule_none():
    assert parse_schedule(None) is None

def test_parse_schedule_invalid_json():
    assert parse_schedule("not json") is None

def test_parse_schedule_invalid_schema():
    assert parse_schedule({"version": 99}) is None


# ---------------------------------------------------------------------------
# active_entry_now (Asia/Seoul = UTC+9)
# ---------------------------------------------------------------------------

KST = pytz.timezone("Asia/Seoul")
UTC = pytz.utc

def _mock_now(weekday, hour, minute, tz=KST):
    """Return a patched datetime.now() context for the given local time."""
    # Weekday 0=Mon ... 6=Sun
    # We fix a Monday base date (2026-01-05 = Mon)
    base_dates = {0: (2026,1,5), 1: (2026,1,6), 2: (2026,1,7),
                  3: (2026,1,8), 4: (2026,1,9), 5: (2026,1,10), 6: (2026,1,11)}
    y, mo, d = base_dates[weekday]
    dt = tz.localize(datetime(y, mo, d, hour, minute, 0))
    return dt

def test_active_entry_now_in_window():
    s = from_legacy("16:30", "19:00", "0,1,2,3,4,5,6", 3600)
    with patch("aot.utils.weekly_schedule.datetime") as mock_dt:
        mock_dt.now.return_value = _mock_now(0, 17, 0)  # Mon 17:00 KST
        result = active_entry_now(s, KST)
    assert result is not None
    day_idx, entry = result
    assert day_idx == 0

def test_active_entry_now_outside_window():
    s = from_legacy("16:30", "19:00", "0,1,2,3,4,5,6", 3600)
    with patch("aot.utils.weekly_schedule.datetime") as mock_dt:
        mock_dt.now.return_value = _mock_now(0, 20, 0)  # Mon 20:00 (past end)
        result = active_entry_now(s, KST)
    assert result is None

def test_active_entry_now_disabled_day():
    s = from_legacy("16:30", "19:00", "1,2,3,4,5,6", 3600)  # Mon disabled
    with patch("aot.utils.weekly_schedule.datetime") as mock_dt:
        mock_dt.now.return_value = _mock_now(0, 17, 0)  # Mon
        result = active_entry_now(s, KST)
    assert result is None

def test_active_entry_now_end_of_day():
    """Window ending at 24:00 should be active at 23:59."""
    s = from_legacy("16:30", "24:00", "0", 3600)
    with patch("aot.utils.weekly_schedule.datetime") as mock_dt:
        mock_dt.now.return_value = _mock_now(0, 23, 59)
        result = active_entry_now(s, KST)
    assert result is not None

def test_active_entry_now_midnight_utc_offset():
    """Server UTC midnight = KST 09:00 — day evaluation must use KST."""
    s = from_legacy("08:00", "10:00", "0,1,2,3,4,5,6", 3600)  # active 08-10 KST
    # UTC 00:30 = KST 09:30 (Mon) → should be active
    utc_dt = UTC.localize(datetime(2026, 1, 5, 0, 30, 0))
    kst_dt = utc_dt.astimezone(KST)
    with patch("aot.utils.weekly_schedule.datetime") as mock_dt:
        mock_dt.now.return_value = kst_dt
        result = active_entry_now(s, KST)
    assert result is not None

def test_active_entry_now_newyork():
    """America/New_York (UTC-5 in winter): check day boundary."""
    NY = pytz.timezone("America/New_York")
    s = from_legacy("09:00", "17:00", "0,1,2,3,4,5,6", 3600)
    ny_dt = NY.localize(datetime(2026, 1, 5, 12, 0, 0))  # Mon 12:00 NY
    with patch("aot.utils.weekly_schedule.datetime") as mock_dt:
        mock_dt.now.return_value = ny_dt
        result = active_entry_now(s, NY)
    assert result is not None
    assert result[0] == 0  # Monday in NY


# ---------------------------------------------------------------------------
# is_continuity_boundary
# ---------------------------------------------------------------------------

def _make_continuity_schedule():
    s = from_legacy("22:00", "24:00", "4,5", 3600)  # Fri-Sat, ends at 24:00
    # Give Sat start 00:00
    s["days"]["5"]["start"] = "00:00"
    s["days"]["5"]["end"]   = "06:00"
    return s

def test_continuity_boundary_true():
    s = _make_continuity_schedule()
    assert is_continuity_boundary(s, 4, 5) is True  # Fri → Sat

def test_continuity_boundary_false_no_24():
    s = _make_continuity_schedule()
    s["days"]["4"]["end"] = "23:59"  # Not 24:00
    assert is_continuity_boundary(s, 4, 5) is False

def test_continuity_boundary_false_no_00():
    s = _make_continuity_schedule()
    s["days"]["5"]["start"] = "00:30"  # Not 00:00
    assert is_continuity_boundary(s, 4, 5) is False

def test_continuity_boundary_false_disabled():
    s = _make_continuity_schedule()
    s["days"]["5"]["enabled"] = False
    assert is_continuity_boundary(s, 4, 5) is False

def test_continuity_boundary_wrap_sunday_monday():
    s = from_legacy("22:00", "24:00", "6", 3600)  # Sun ends 24:00
    s["days"]["0"]["start"] = "00:00"
    s["days"]["0"]["enabled"] = True
    assert is_continuity_boundary(s, 6, 0) is True  # Sun → Mon

def test_continuity_boundary_non_adjacent():
    s = from_legacy("22:00", "24:00", "0,1,2,3,4,5,6", 3600)
    s["days"]["1"]["start"] = "00:00"
    # Mon → Wed is not adjacent
    assert is_continuity_boundary(s, 0, 2) is False


# ---------------------------------------------------------------------------
# to_legacy
# ---------------------------------------------------------------------------

def test_to_legacy_shared():
    s = from_legacy("16:30", "19:00", "1,2,3", 3600)
    start, end, wd_str, period = to_legacy(s)
    assert start == "16:30"
    assert end == "19:00"
    assert period == 3600.0
    # Enabled days: 1,2,3
    assert set(wd_str.split(',')) == {'1', '2', '3'}

def test_to_legacy_per_day():
    s = from_legacy("16:30", "19:00", "0,1,2,3,4,5,6", 3600)
    s["mode"] = "per_day"
    s["days"]["0"]["start"] = "08:00"
    s["days"]["0"]["end"] = "10:00"
    s["days"]["0"]["period"] = 1800
    start, end, wd_str, period = to_legacy(s)
    # Should pick first enabled day (Mon=0)
    assert start == "08:00"
    assert period == 1800.0


# ---------------------------------------------------------------------------
# build_warnings
# ---------------------------------------------------------------------------

def test_build_warnings_period_too_long():
    s = from_legacy("16:30", "17:00", "0", 7200)  # 30-min window, 2h period
    warnings = build_warnings(s)
    assert len(warnings) > 0
    assert "cut short" in warnings[0]

def test_build_warnings_ok():
    s = from_legacy("16:30", "19:00", "0", 3600)  # 2.5h window, 1h period
    assert build_warnings(s) == []

# ---------------------------------------------------------------------------
# day_action_enabled (per-day action selection)
# ---------------------------------------------------------------------------

def test_day_action_enabled_no_actions_map_falls_back():
    s = _make_valid_schedule()
    assert day_action_enabled(s, 0, "uid-1", True) is True
    assert day_action_enabled(s, 0, "uid-1", False) is False

def test_day_action_enabled_override():
    s = _make_valid_schedule()
    s["days"]["0"]["actions"] = {"uid-1": False, "uid-2": True}
    assert day_action_enabled(s, 0, "uid-1", True) is False
    assert day_action_enabled(s, 0, "uid-2", False) is True
    # uid not in map → fall back to default
    assert day_action_enabled(s, 0, "uid-3", True) is True
    # Other day has no map → fall back
    assert day_action_enabled(s, 1, "uid-1", True) is True

def test_validate_actions_map_ok():
    s = _make_valid_schedule()
    s["days"]["2"]["actions"] = {"uid-1": True}
    assert validate(s) == []

def test_validate_actions_map_wrong_type():
    s = _make_valid_schedule()
    s["days"]["2"]["actions"] = ["uid-1"]
    errors = validate(s)
    assert any("actions" in e for e in errors)

def test_parse_schedule_preserves_actions():
    s = _make_valid_schedule()
    s["days"]["3"]["actions"] = {"uid-9": False}
    s2 = parse_schedule(json.dumps(s))
    assert s2 is not None
    assert s2["days"]["3"]["actions"] == {"uid-9": False}
