# coding=utf-8
"""Unit tests for aot.utils.solar — 태양시 단일 커널.

DB 를 건드리지 않는다: 좌표를 전부 명시로 넘겨 순수 계산만 검증한다
(라이브 DB 대상 테스트 금지 규칙).
"""
from datetime import date, datetime, timedelta

import pytest
import pytz

from aot.utils import solar

# 전북 완주 인근 — 실제 농장 위도/경도대와 같은 대역.
LAT, LON = 35.8, 127.1
KST = pytz.timezone('Asia/Seoul')
# 스발바르 — 백야/극야 경계 밖.
POLAR_LAT, POLAR_LON = 78.2, 15.6


@pytest.fixture(autouse=True)
def _clear_cache():
    solar.clear_cache()
    yield
    solar.clear_cache()


# ---------------------------------------------------------------------------
# sun_times — 하루치 계산
# ---------------------------------------------------------------------------

def test_sun_times_uses_local_date_boundary():
    """일출·일몰이 **같은 현지 날짜**에 속해야 한다.

    UTC 날짜로 계산하면 한국(UTC+9)에서 일출은 전날 UTC 저녁, 일몰은 당일
    UTC 오전이 되어 서로 다른 날에 걸린다 — 예전 구현의 실패 지점.
    """
    st = solar.sun_times(latitude=LAT, longitude=LON, date=date(2026, 7, 31))
    assert st is not None
    assert st.status == solar.STATUS_NORMAL
    assert st.tz_name == 'Asia/Seoul'
    assert st.sunrise.astimezone(KST).date() == date(2026, 7, 31)
    assert st.sunset.astimezone(KST).date() == date(2026, 7, 31)
    assert st.sunrise < st.solar_noon < st.sunset


def test_sun_times_returns_utc_aware():
    st = solar.sun_times(latitude=LAT, longitude=LON, date=date(2026, 7, 31))
    for value in (st.sunrise, st.sunset, st.solar_noon, st.civil_dawn, st.civil_dusk):
        assert value.tzinfo is not None
        assert value.utcoffset() == timedelta(0)


def test_sun_times_civil_twilight_brackets_day():
    st = solar.sun_times(latitude=LAT, longitude=LON, date=date(2026, 7, 31))
    assert st.civil_dawn < st.sunrise
    assert st.sunset < st.civil_dusk


def test_day_length_summer_longer_than_winter():
    summer = solar.sun_times(latitude=LAT, longitude=LON, date=date(2026, 6, 21))
    winter = solar.sun_times(latitude=LAT, longitude=LON, date=date(2026, 12, 21))
    assert summer.day_length_seconds > winter.day_length_seconds
    assert summer.day_length_seconds / 3600 == pytest.approx(14.4, abs=0.3)
    assert winter.day_length_seconds / 3600 == pytest.approx(9.7, abs=0.3)


def test_sun_times_without_coords_returns_none(monkeypatch):
    monkeypatch.setattr(solar, 'resolve_coords', lambda *a, **k: (None, None, 'utc'))
    assert solar.sun_times(target_id='no-such-entity') is None


def test_cache_reuses_computation(monkeypatch):
    solar.sun_times(latitude=LAT, longitude=LON, date=date(2026, 7, 31))

    calls = []
    original = solar._compute
    monkeypatch.setattr(solar, '_compute',
                        lambda *a, **k: (calls.append(1), original(*a, **k))[1])
    solar.sun_times(latitude=LAT, longitude=LON, date=date(2026, 7, 31))
    assert calls == []  # 같은 위치·같은 날 → 재계산 없음


# ---------------------------------------------------------------------------
# next_sun_event — 타이머 예약
# ---------------------------------------------------------------------------

def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=pytz.utc)


def test_next_sun_event_is_strictly_future():
    now = _utc(2026, 7, 31, 9)  # 18:00 KST — 일몰 전
    nxt = solar.next_sun_event('sunset', latitude=LAT, longitude=LON, now=now)
    assert nxt > now
    assert nxt.astimezone(KST).date() == date(2026, 7, 31)


def test_next_sun_event_rolls_to_next_day_when_passed():
    now = _utc(2026, 7, 31, 9)  # 18:00 KST — 오늘 일출은 이미 지남
    nxt = solar.next_sun_event('sunrise', latitude=LAT, longitude=LON, now=now)
    assert nxt.astimezone(KST).date() == date(2026, 8, 1)


def test_next_sun_event_time_offset_applied():
    now = _utc(2026, 7, 31, 0)
    base = solar.next_sun_event('sunset', latitude=LAT, longitude=LON, now=now)
    shifted = solar.next_sun_event('sunset', latitude=LAT, longitude=LON, now=now,
                                   time_offset_minutes=-30)
    assert base - shifted == timedelta(minutes=30)


def test_next_sun_event_date_offset_shifts_search_start():
    now = _utc(2026, 7, 31, 0)  # 09:00 KST — 오늘 일몰은 아직 안 옴
    today = solar.next_sun_event('sunset', latitude=LAT, longitude=LON, now=now)
    tomorrow = solar.next_sun_event('sunset', latitude=LAT, longitude=LON, now=now,
                                    date_offset_days=1)
    assert today.astimezone(KST).date() == date(2026, 7, 31)
    assert tomorrow.astimezone(KST).date() == date(2026, 8, 1)


def test_next_sun_event_epoch_matches_datetime():
    now = _utc(2026, 7, 31, 0)
    dt = solar.next_sun_event('sunrise', latitude=LAT, longitude=LON, now=now)
    epoch = solar.next_sun_event_epoch('sunrise', latitude=LAT, longitude=LON, now=now)
    assert epoch == pytest.approx(dt.timestamp())


def test_next_sun_event_unknown_kind_returns_none():
    assert solar.next_sun_event('moonrise', latitude=LAT, longitude=LON) is None


# ---------------------------------------------------------------------------
# is_daytime — 주간/야간 판정 (Function·Output 전반의 공용 프리미티브)
# ---------------------------------------------------------------------------

def test_is_daytime_true_at_local_noon():
    assert solar.is_daytime(latitude=LAT, longitude=LON, at=_utc(2026, 7, 31, 3)) is True


def test_is_daytime_false_at_local_midnight():
    assert solar.is_daytime(latitude=LAT, longitude=LON, at=_utc(2026, 7, 31, 15)) is False


def test_is_daytime_offsets_narrow_the_window():
    st = solar.sun_times(latitude=LAT, longitude=LON, date=date(2026, 7, 31))
    just_after_sunrise = st.sunrise + timedelta(minutes=10)
    assert solar.is_daytime(latitude=LAT, longitude=LON, at=just_after_sunrise) is True
    # "일출 30분 후부터 주간" → 같은 시각이 아직 야간
    assert solar.is_daytime(latitude=LAT, longitude=LON, at=just_after_sunrise,
                            start_offset_minutes=30) is False


def test_is_daytime_none_without_coords(monkeypatch):
    monkeypatch.setattr(solar, 'resolve_coords', lambda *a, **k: (None, None, 'utc'))
    assert solar.is_daytime(target_id='no-such-entity') is None


# ---------------------------------------------------------------------------
# 극지 — 예외가 아니라 status 로 표현
# ---------------------------------------------------------------------------

def test_polar_midnight_sun_reports_always_day():
    st = solar.sun_times(latitude=POLAR_LAT, longitude=POLAR_LON, date=date(2026, 7, 1))
    assert st.status == solar.STATUS_ALWAYS_DAY
    assert st.day_length_seconds == 86400.0
    assert solar.is_daytime(latitude=POLAR_LAT, longitude=POLAR_LON,
                            at=_utc(2026, 7, 1, 2)) is True


def test_polar_night_reports_always_night():
    st = solar.sun_times(latitude=POLAR_LAT, longitude=POLAR_LON, date=date(2026, 12, 21))
    assert st.status == solar.STATUS_ALWAYS_NIGHT
    assert st.day_length_seconds == 0.0
    assert solar.is_daytime(latitude=POLAR_LAT, longitude=POLAR_LON,
                            at=_utc(2026, 12, 21, 12)) is False


# ---------------------------------------------------------------------------
# sun_position — 차광·일소 게이트용 태양고도
# ---------------------------------------------------------------------------

def test_sun_position_high_at_noon_negative_at_night():
    noon_elev, noon_azim = solar.sun_position(
        latitude=LAT, longitude=LON, at=_utc(2026, 7, 31, 3))   # 12:00 KST
    night_elev, _ = solar.sun_position(
        latitude=LAT, longitude=LON, at=_utc(2026, 7, 31, 15))  # 24:00 KST
    assert noon_elev > 60
    assert 0 <= noon_azim <= 360
    assert night_elev < 0


def test_sun_position_none_without_coords(monkeypatch):
    monkeypatch.setattr(solar, 'resolve_coords', lambda *a, **k: (None, None, 'utc'))
    assert solar.sun_position(target_id='no-such-entity') == (None, None)


# ---------------------------------------------------------------------------
# 하위 호환 shim
# ---------------------------------------------------------------------------

def test_legacy_shim_delegates_to_kernel():
    from aot.utils.sunriseset import suntime_calculate_next_sunrise_sunset_epoch

    epoch = suntime_calculate_next_sunrise_sunset_epoch(LAT, LON, 0, 0, 'sunrise')
    assert epoch is not None and epoch > 0

    dt = suntime_calculate_next_sunrise_sunset_epoch(
        LAT, LON, 0, 0, 'sunrise', return_dt=True)
    assert dt.tzinfo is not None
    assert dt.timestamp() == pytest.approx(epoch)


# ---------------------------------------------------------------------------
# night_bands — 그래프 야간 음영
# ---------------------------------------------------------------------------

def test_night_bands_span_sunset_to_sunrise():
    start = datetime(2026, 7, 30, 0, 0, tzinfo=pytz.utc)
    end = datetime(2026, 8, 1, 0, 0, tzinfo=pytz.utc)
    bands = solar.night_bands(start, end, latitude=LAT, longitude=LON)

    assert bands
    for lo, hi in bands:
        assert start <= lo < hi <= end
    # 어느 밴드든 일몰에서 시작해 다음 일출에 끝난다.
    day = solar.sun_times(latitude=LAT, longitude=LON, date=date(2026, 7, 30))
    nxt = solar.sun_times(latitude=LAT, longitude=LON, date=date(2026, 7, 31))
    assert any(lo == day.sunset and hi == nxt.sunrise for lo, hi in bands)


def test_night_bands_clipped_to_window():
    """창이 밤 한가운데서 시작·끝나도 창 밖으로 새지 않는다."""
    start = datetime(2026, 7, 30, 17, 0, tzinfo=pytz.utc)   # 02:00 KST — 한밤중
    end = datetime(2026, 7, 30, 19, 0, tzinfo=pytz.utc)     # 04:00 KST — 아직 밤
    bands = solar.night_bands(start, end, latitude=LAT, longitude=LON)
    assert bands == [(start, end)]


def test_night_bands_daytime_window_is_empty():
    start = datetime(2026, 7, 31, 2, 0, tzinfo=pytz.utc)    # 11:00 KST
    end = datetime(2026, 7, 31, 5, 0, tzinfo=pytz.utc)      # 14:00 KST
    assert solar.night_bands(start, end, latitude=LAT, longitude=LON) == []


def test_night_bands_polar_day_has_no_night():
    start = datetime(2026, 7, 1, 0, 0, tzinfo=pytz.utc)
    end = datetime(2026, 7, 3, 0, 0, tzinfo=pytz.utc)
    assert solar.night_bands(start, end,
                             latitude=POLAR_LAT, longitude=POLAR_LON) == []


def test_night_bands_polar_night_covers_window():
    start = datetime(2026, 12, 20, 0, 0, tzinfo=pytz.utc)
    end = datetime(2026, 12, 22, 0, 0, tzinfo=pytz.utc)
    bands = solar.night_bands(start, end,
                              latitude=POLAR_LAT, longitude=POLAR_LON)
    assert bands == [(start, end)]


def test_night_bands_empty_without_coords(monkeypatch):
    monkeypatch.setattr(solar, 'resolve_coords', lambda *a, **k: (None, None, 'utc'))
    start = datetime(2026, 7, 30, tzinfo=pytz.utc)
    assert solar.night_bands(start, start + timedelta(days=1),
                             target_id='no-such-entity') == []


def test_night_bands_rejects_inverted_window():
    start = datetime(2026, 7, 31, 12, 0, tzinfo=pytz.utc)
    assert solar.night_bands(start, start - timedelta(hours=1),
                             latitude=LAT, longitude=LON) == []


# ---------------------------------------------------------------------------
# clear_sky_irradiance — 센서 없는 시설의 광량 어림
# ---------------------------------------------------------------------------

def test_clear_sky_peaks_near_solar_noon():
    noon = solar.clear_sky_irradiance(latitude=LAT, longitude=LON,
                                      at=_utc(2026, 7, 31, 3))    # 12:00 KST
    morning = solar.clear_sky_irradiance(latitude=LAT, longitude=LON,
                                         at=_utc(2026, 7, 31, 0))  # 09:00 KST
    assert 850 < noon <= solar.CLEAR_SKY_PEAK_W_M2
    assert morning < noon


def test_clear_sky_is_zero_at_night():
    assert solar.clear_sky_irradiance(latitude=LAT, longitude=LON,
                                      at=_utc(2026, 7, 31, 15)) == 0.0


def test_clear_sky_none_without_coords(monkeypatch):
    monkeypatch.setattr(solar, 'resolve_coords', lambda *a, **k: (None, None, 'utc'))
    assert solar.clear_sky_irradiance(target_id='no-such-entity') is None


def test_clear_sky_winter_noon_lower_than_summer():
    summer = solar.clear_sky_irradiance(latitude=LAT, longitude=LON,
                                        at=_utc(2026, 6, 21, 3))
    winter = solar.clear_sky_irradiance(latitude=LAT, longitude=LON,
                                        at=_utc(2026, 12, 21, 3))
    assert winter < summer
