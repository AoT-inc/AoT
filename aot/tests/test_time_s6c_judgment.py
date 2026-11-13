"""S6c — 판단이 필요했던 시간 처리 정리의 시험.

로컬 장치는 전부 +09:00 이라 KST 로는 서머타임 버그가 가려진다 — 뉴욕
(2026-03-08 서머타임 시작 · 11-01 종료)으로 확인한다.
"""
import datetime as dt
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

NY = 'America/New_York'


def _z(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


# ── 결정 1: 오프셋 없는 문자열은 장소 현지 벽시계로 ────────────────────────────

def test_location_window_reads_naive_as_place_wall_clock_across_dst():
    from aot.utils.device_tz import location_window
    t0, t1, l0, l1 = location_window('2026-03-08T01:00', '2026-03-08T03:30', NY)
    assert t0 == _z(2026, 3, 8, 6)            # 01:00 EST
    assert t1 == _z(2026, 3, 8, 7, 30)        # 03:30 EDT (고정 -5 면 08:30)
    assert l0.endswith('-05:00') and l1.endswith('-04:00')


def test_location_window_date_only_end_includes_the_day_on_dst_day():
    from aot.utils.device_tz import location_window
    t0, t1, _l0, _l1 = location_window('2026-11-01', '2026-11-01', NY)
    assert t0 == _z(2026, 11, 1, 4)           # 00:00 EDT
    assert t1 == _z(2026, 11, 2, 5)           # 다음 날 00:00 EST — 하루가 25시간


def test_location_window_explicit_offset_is_that_instant():
    from aot.utils.device_tz import location_window
    t0, _t1, _l0, _l1 = location_window('2026-03-08T12:00:00Z', '2026-03-08T13:00:00+09:00', NY)
    assert t0 == _z(2026, 3, 8, 12)


def test_location_window_unreadable_text_raises():
    from aot.utils.device_tz import location_window
    with pytest.raises(ValueError):
        location_window('not-a-time', None, NY)


def test_forecast_start_naive_is_place_local_and_offset_converts():
    from aot.tools.aot_data_tool_service import AoTDataToolService as M
    now = _z(2026, 3, 8, 12)
    st, now_hour, _n = M._parse_forecast_start('2026-03-08T15:00', NY, now)
    assert st == datetime(2026, 3, 8, 15) and now_hour == datetime(2026, 3, 8, 8)   # 12Z = 08:00 EDT
    st, _nh, _n = M._parse_forecast_start('2026-03-08T20:00:00Z', NY, now)
    assert st == datetime(2026, 3, 8, 16)
    assert isinstance(M._parse_forecast_start('garbage', NY, now), str)


def test_forecast_start_today_tomorrow_follow_wall_to_utc_policy_in_ny():
    """today/tomorrow HH:MM 도 명시 시각과 같은 정책 — 간극은 한 시간 뒤 칸, 서울은 그대로."""
    from aot.tools.aot_data_tool_service import AoTDataToolService as M
    now = _z(2027, 3, 13, 15)                                   # 10:00 EST, 다음 날 간극
    st, _nh, _n = M._parse_forecast_start('tomorrow 02:30', NY, now)
    assert st == datetime(2027, 3, 14, 3)                       # 02:30 은 없는 시각 → 03:00 칸
    st, _nh, _n = M._parse_forecast_start('2027-03-14T02:30', NY, now)
    assert st == datetime(2027, 3, 14, 3)                       # 명시 경로와 동일
    st, _nh, _n = M._parse_forecast_start('tomorrow 03:00', NY, now)
    assert st == datetime(2027, 3, 14, 3)
    st, _nh, _n = M._parse_forecast_start('tomorrow 01:00', NY, now)
    assert st == datetime(2027, 3, 14, 1)


def test_forecast_start_today_tomorrow_ambiguous_hour_matches_explicit_in_ny():
    """중복 시각(11-01 01:30)은 두 번째 발생 — today/tomorrow 가 명시 경로와 같은 칸."""
    from aot.tools.aot_data_tool_service import AoTDataToolService as M
    now = _z(2026, 10, 31, 15)                                  # 11:00 EDT
    a, _nh, _n = M._parse_forecast_start('tomorrow 01:30', NY, now)
    b, _nh, _n = M._parse_forecast_start('2026-11-01T01:30', NY, now)
    assert a == b == datetime(2026, 11, 1, 1)
    st, _nh, _n = M._parse_forecast_start('tomorrow 02:00', NY, now)
    assert st == datetime(2026, 11, 1, 2)


def test_forecast_start_today_tomorrow_unchanged_in_seoul():
    from aot.tools.aot_data_tool_service import AoTDataToolService as M
    now = _z(2027, 3, 13, 15)                                   # 00:00 KST 3/14
    st, _nh, _n = M._parse_forecast_start('tomorrow 02:30', 'Asia/Seoul', now)
    assert st == datetime(2027, 3, 15, 2)
    st, _nh, _n = M._parse_forecast_start('today', 'Asia/Seoul', now)
    assert st == datetime(2027, 3, 14, 0)


def test_in_period_z_value_follows_the_place_not_utc():
    from aot.tools.domain import vocab
    rng = (dt.date(2026, 3, 7), dt.date(2026, 3, 7))
    # 2026-03-08T02:00Z 는 뉴욕에서는 3/7 21:00 이다
    assert vocab.in_period('2026-03-08T02:00:00Z', rng, NY) is True
    assert vocab.in_period('2026-03-08T02:00:00Z', rng, 'UTC') is False
    # 오프셋·벽시계는 값 자체의 날짜
    assert vocab.in_period('2026-03-07T23:30:00+09:00', rng, NY) is True
    assert vocab.in_period('2026-03-07T09:00:00', rng, NY) is True
    assert vocab.in_period('x', rng) is False


# ── 결정 2: _as_utc 제거 후에도 None·naive 동작이 그대로 ───────────────────────

def test_as_utc_helpers_are_gone():
    import aot.ai.services.safety_service as ss
    import aot.ai.services.tier_decision_engine as te
    assert not hasattr(ss, '_as_utc') and not hasattr(te, '_as_utc')


def test_tier_engine_skips_none_timestamps_and_reads_naive_as_utc():
    from aot.ai.services.tier_decision_engine import TierDecisionEngine as E
    doc = SimpleNamespace(last_accessed=None, date_time=datetime(2026, 11, 1, 3, 0))
    got = E._get_last_accessed(doc)
    assert got == _z(2026, 11, 1, 3)
    assert E._get_last_accessed(SimpleNamespace(last_accessed=None, date_time=None)) is None


# ── 결정 3: 통일한 ISO 파서는 예전과 같은 값을 낸다 ────────────────────────────

_OLD_T = ['2026-03-08T12:00:00Z', '2026-03-08T12:00:00z', '2026-03-08T12:00:00+09:00',
          '2026-03-08T12:00:00', '2026-03-08 12:00:00', '2026-03-08',
          '2026-03-08T12:00:00.123456Z']


def _old_weather_t(value):
    txt = value.strip()
    if txt.endswith(('Z', 'z')):
        txt = txt[:-1] + '+00:00'
    d = datetime.fromisoformat(txt)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


@pytest.mark.parametrize('value', _OLD_T)
def test_weather_state_time_parse_matches_old_hand_written(value):
    from aot.space import weather_state as ws
    now = _old_weather_t(value)
    assert ws.parse_time(value, now=now) == _old_weather_t(value)


def test_weather_state_rejects_unreadable_text():
    from aot.space import weather_state as ws
    with pytest.raises(ValueError):
        ws.parse_time('garbage', now=0.0)


def _old_twin_parse(value):
    if value is None or value == '':
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), timezone.utc)
        text = str(value).strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        d = datetime.fromisoformat(text)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


@pytest.mark.parametrize('value', _OLD_T[:1] + _OLD_T[2:] + ['', None, 0, 1.7e9, 'garbage', '2026-13-40'])
def test_twin_gate_parse_ts_matches_old(value):
    from aot.utils.twin_gate import _parse_ts
    assert _parse_ts(value) == _old_twin_parse(value)


# ── 결정 3: 바꾸지 않은 RFC3339 'Z' 출력은 iso_utc 와 다르다(예외 후보의 근거) ──────

def test_rfc3339_z_outputs_differ_from_iso_utc():
    from aot.utils.timekit import iso_utc
    from aot.ai.services.calendar_sync_service import _naive_utc_to_rfc3339
    from aot.utils.ai_screen_cards import iso_z
    from aot.utils.twin_gate import _iso
    naive = datetime(2026, 3, 8, 12, 0, 0)
    assert _naive_utc_to_rfc3339(naive) == '2026-03-08T12:00:00Z'
    assert iso_z(naive) == '2026-03-08T12:00:00Z'
    assert _iso(_z(2026, 3, 8, 12)) == '2026-03-08T12:00:00Z'
    assert iso_utc(naive) == '2026-03-08T12:00:00+00:00'          # 같지 않다 → 통일하지 않았다


# ── 결정 4: 현지 정시 + 1시간은 서머타임 전환에서도 맞다 ─────────────────────────

def test_next_local_hour_across_dst_start():
    from aot.utils.timekit import parse_utc, to_tz, tz_of
    tz = tz_of(NY)
    hour_start = _z(2026, 3, 8, 6, 20).astimezone(tz).replace(minute=0, second=0, microsecond=0)   # 01:00 EST
    nxt = to_tz(parse_utc(hour_start) + dt.timedelta(hours=1), tz)
    assert nxt.strftime('%H:%M') == '03:00'                       # 02:00 은 없다


def test_picker_start_six_hours_back_is_farm_wall_clock_across_dst():
    from aot.utils.timekit import to_tz
    now = to_tz(_z(2026, 3, 8, 10), NY)                           # 06:00 EDT
    back = to_tz(now - dt.timedelta(hours=6), NY)
    assert back.strftime('%m-%d %H:%M') == '03-07 23:00' and back.utcoffset() == dt.timedelta(hours=-5)


# ── localize → wall_to_utc 치환: 서머타임 경계 ───────────────────────────────

def test_solar_always_night_bands_use_wall_to_utc():
    from aot.utils.timekit import wall_to_utc
    assert wall_to_utc(datetime(2026, 3, 8), NY) == _z(2026, 3, 8, 5)
    assert wall_to_utc(datetime(2026, 3, 9), NY) == _z(2026, 3, 9, 4)


def test_method_local_noon_across_dst():
    from aot.utils.method import local_noon
    import pytz
    a = local_noon(dt.date(2026, 3, 8), pytz.timezone(NY))
    assert a.isoformat() == '2026-03-08T12:00:00-04:00'
    assert local_noon(dt.date(2026, 3, 7), pytz.timezone(NY)).isoformat() == '2026-03-07T12:00:00-05:00'


def test_docker_update_next_run_uses_wall_to_utc():
    from aot.utils import docker_update as du
    import inspect
    assert '_localize' not in inspect.getsource(du)
