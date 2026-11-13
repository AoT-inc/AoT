"""S5b — 시간대 이름을 timekit 입구로 푼 경로의 DST·폴백 시험.

개발 로컬 장치는 전부 +09:00 이라 KST 로는 서머타임 버그가 가려진다 —
뉴욕(2026-03-08 서머타임 시작 · 11-01 종료)으로 확인한다.
"""
from datetime import datetime, timezone

import pytest

NY = 'America/New_York'


def _ep(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp()


def test_weekly_wall_minutes_across_dst_start():
    from aot.utils.weekly_schedule import _epoch_of_wall_minutes
    # 3/8 뉴욕: 자정 EST(-5) → 06:00 EDT(-4) = 10:00Z (고정 오프셋이면 11:00Z)
    now = _ep(2026, 3, 8, 12)
    assert _epoch_of_wall_minutes(6 * 60, NY, now) == _ep(2026, 3, 8, 10)


def test_weekly_today_idx_uses_name_not_naive_local():
    from aot.utils.weekly_schedule import get_today_idx
    # 호출 시점에 따라 달라지므로 이름과 tzinfo 가 같은 값을 내는지만 본다
    import pytz
    assert get_today_idx(NY) == get_today_idx(pytz.timezone(NY))


def test_forecast_epoch_dst_and_unknown_name():
    from aot.functions.utils.env_control.forecast_feedforward import forecast_epoch
    assert forecast_epoch('202603081200', NY) == _ep(2026, 3, 8, 16)   # EDT
    assert forecast_epoch('202611011200', NY) == _ep(2026, 11, 1, 17)  # EST
    assert forecast_epoch('202603081200', 'Not/AZone') is None         # 읽을 수 없으면 None
    assert forecast_epoch('202603081200') == _ep(2026, 3, 8, 3)        # 기본 KST


def test_epoch_of_next_time_unknown_zone_is_none():
    from aot.utils.system_pi import epoch_of_next_time
    assert epoch_of_next_time('08:00:00', 'Not/AZone') is None
    assert epoch_of_next_time('08:00:00', NY) is not None


def test_site_due_uses_site_clock():
    from aot.utils.fc_cal.job import site_due
    # 2026-03-08 07:30Z = 뉴욕 03:30 EDT(≥3시) / 07:30Z 는 EST 였다면 02:30(<3시)
    assert site_due(_ep(2026, 3, 8, 7, 30), NY, None) is True
    assert site_due(_ep(2026, 3, 8, 6, 30), NY, None) is False


def test_method_weeks_elapsed_ignores_invalid_name_like_before():
    from aot.utils.method import weeks_elapsed_at
    when = datetime(2026, 3, 15, 12, tzinfo=timezone.utc)
    ny = weeks_elapsed_at('2026-03-01', when, NY)
    bad = weeks_elapsed_at('2026-03-01', when, 'Not/AZone')   # UTC 로 계산(예전과 같다)
    utc = weeks_elapsed_at('2026-03-01', when, 'UTC')
    assert bad == utc
    assert ny != utc


def test_resolve_tz_validity_probe_used_for_user_settings():
    from aot.utils.timekit import resolve_tz, SOURCE_EXPLICIT
    assert resolve_tz(NY)[1] == SOURCE_EXPLICIT
    assert resolve_tz('Not/AZone')[1] != SOURCE_EXPLICIT


def test_forecast_series_offset_follows_dst():
    from aot.space.forecast_series import _tz_offset_s
    assert _tz_offset_s(NY, _ep(2026, 3, 8, 12)) == -4 * 3600
    assert _tz_offset_s(NY, _ep(2026, 3, 1, 12)) == -5 * 3600
