# coding=utf-8
"""Function 시간 점검 S4 — PID 컨트롤러와 설정점 메서드(`aot/utils/method.py`)의 시간 처리.

DB 는 건드리지 않는다 — Method/MethodData 는 스텁, PID 행은 SimpleNamespace.
시간대 3곳: Asia/Seoul(DST 없음), America/New_York(1시간 DST), Australia/Lord_Howe(30분 DST).
"""
import datetime
import logging
from types import SimpleNamespace as NS

import pytest
import pytz

from aot.utils import method as M

UTC = datetime.timezone.utc
KST = pytz.timezone('Asia/Seoul')
NY = pytz.timezone('America/New_York')
LH = pytz.timezone('Australia/Lord_Howe')


class _Q:
    def __init__(self, rows):
        self._r = rows

    def filter(self, *_a, **_k):
        return self

    def all(self):
        return list(self._r)

    def first(self):
        return self._r[0] if self._r else None


def _row(**kw):
    base = dict(
        time_start='2026-11-11 00:00:00', time_end='2026-11-13 00:00:00',
        setpoint_start=10.0, setpoint_end=20.0,
        time_start_event=None, time_start_offset_min=0,
        time_end_event=None, time_end_offset_min=0,
        output_id=None, duration_sec=None, duration_end=None)
    base.update(kw)
    return NS(**base)


def _meth(kind):
    return NS(unique_id='m-1', method_type=kind, name='m')


@pytest.fixture
def tz_is(monkeypatch):
    def _set(tz):
        monkeypatch.setattr('aot.utils.method.tz_of', lambda *_a, **_k: tz)
    return _set


def _utc(*a):
    return datetime.datetime(*a, tzinfo=UTC)


# ── Date 메서드: aware now 로 불려도 죽지 않고, DST 날에도 순간으로 계산 ───────────

def test_date_method_accepts_aware_now_seoul(tz_is):
    tz_is(KST)
    h = M.DateMethod(_meth('Date'), _Q([_row()]))
    # 2026-11-12 03:00 UTC = 12:00 KST → 36h / 48h
    sp, ended = h.calculate_setpoint(_utc(2026, 11, 12, 3, 0))
    assert ended is False
    assert sp == pytest.approx(10 + 10 * 0.75)


def test_date_method_epoch_and_naive_wallclock(tz_is):
    tz_is(KST)
    h = M.DateMethod(_meth('Date'), _Q([_row()]))
    epoch = _utc(2026, 11, 12, 3, 0).timestamp()
    assert h.calculate_setpoint(epoch)[0] == pytest.approx(17.5)
    # naive 는 이미 벽시계(12:00 KST) 로 읽는다
    assert h.calculate_setpoint(datetime.datetime(2026, 11, 12, 12, 0))[0] == pytest.approx(17.5)


def test_date_method_new_york_spring_forward_day_is_23_hours(tz_is):
    """2026-03-08 은 뉴욕 DST 시작일 — 하루가 23시간. 낮 12:00 EDT 는 11h/23h."""
    tz_is(NY)
    row = _row(time_start='2026-03-08 00:00:00', time_end='2026-03-09 00:00:00',
               setpoint_start=0.0, setpoint_end=23.0)
    h = M.DateMethod(_meth('Date'), _Q([row]))
    noon_edt = NY.localize(datetime.datetime(2026, 3, 8, 12, 0)).astimezone(pytz.utc)
    sp, _ = h.calculate_setpoint(noon_edt)
    assert sp == pytest.approx(11.0)          # 벽시계로 비교했다면 12.0


def test_date_method_new_york_fall_back_day_is_25_hours(tz_is):
    tz_is(NY)
    row = _row(time_start='2026-11-01 00:00:00', time_end='2026-11-02 00:00:00',
               setpoint_start=0.0, setpoint_end=25.0)
    h = M.DateMethod(_meth('Date'), _Q([row]))
    noon_est = NY.localize(datetime.datetime(2026, 11, 1, 12, 0)).astimezone(pytz.utc)
    assert h.calculate_setpoint(noon_est)[0] == pytest.approx(13.0)   # 12h + 1h 겹침


def test_date_method_lord_howe_half_hour_dst(tz_is):
    """로드하우 DST 종료(2026-04-05 02:00 → 01:30): 하루 24.5시간."""
    tz_is(LH)
    row = _row(time_start='2026-04-05 00:00:00', time_end='2026-04-06 00:00:00',
               setpoint_start=0.0, setpoint_end=24.5)
    h = M.DateMethod(_meth('Date'), _Q([row]))
    noon = LH.localize(datetime.datetime(2026, 4, 5, 12, 0)).astimezone(pytz.utc)
    assert h.calculate_setpoint(noon)[0] == pytest.approx(12.5)


def test_date_method_outside_range_and_bad_row(tz_is):
    tz_is(KST)
    bad = _row(time_start='garbage')
    h = M.DateMethod(_meth('Date'), _Q([bad, _row()]))
    assert h.calculate_setpoint(_utc(2026, 12, 1))[0] is None
    assert h.calculate_setpoint(_utc(2026, 11, 12, 3))[0] == pytest.approx(17.5)


# ── Duration 메서드 ───────────────────────────────────────────────────────

def _duration(rows=None):
    rows = rows if rows is not None else [_row(duration_sec=3600, setpoint_start=10, setpoint_end=20)]
    return M.DurationMethod(_meth('Duration'), _Q(rows))


NOW = _utc(2026, 11, 12, 3, 0)


@pytest.mark.parametrize('start', [
    '2026-11-12 02:30:00+00:00',   # 지금 코드가 쓰는 형식
    '2026-11-12 02:30:00',         # 오프셋 없는 옛 값(UTC)
    '2026-11-12T02:30:00Z',
    _utc(2026, 11, 12, 2, 30),
    datetime.datetime(2026, 11, 12, 2, 30),
])
def test_duration_reads_every_stored_start_format(start):
    sp, ended = _duration().calculate_setpoint(NOW, start)
    assert ended is False and sp == pytest.approx(15.0)


def test_duration_unreadable_start_uses_default_setpoint_not_exception():
    for bad in (None, '', 'not-a-time'):
        assert _duration().calculate_setpoint(NOW, bad) == (None, False)


def test_duration_start_in_future_clamps_to_method_start():
    """시작 시각이 미래(시계 역행·잘못 저장)여도 전체 길이(3600)가 설정점으로 나가지 않는다."""
    sp, ended = _duration().calculate_setpoint(NOW, '2026-11-12 05:00:00+00:00')
    assert ended is False and sp == pytest.approx(10.0)


def test_duration_without_rows_does_not_divide_by_zero():
    h = _duration([_row(duration_sec=0, duration_end=0)])
    assert h.calculate_setpoint(NOW, '2026-11-12 02:00:00+00:00') == (None, False)


def test_duration_elapsed_is_instant_difference_across_dst():
    """간격은 순간 차 — 뉴욕 봄 DST 를 가로질러도 3600초는 3600초."""
    h = _duration([_row(duration_sec=7200, setpoint_start=0, setpoint_end=7200)])
    start = NY.localize(datetime.datetime(2026, 3, 8, 1, 30)).astimezone(pytz.utc)
    now = start + datetime.timedelta(seconds=3600)      # 벽시계로는 03:30 (2시간 뒤처럼 보임)
    assert h.calculate_setpoint(now, start.isoformat())[0] == pytest.approx(3600.0)


def test_duration_repeat_and_end():
    rows = [_row(duration_sec=3600, setpoint_start=0, setpoint_end=3600),
            _row(duration_sec=0, duration_end=10800)]
    h = _duration(rows)
    start = '2026-11-12 00:00:00+00:00'
    # 1.5 사이클째, 반복 제한 3시간 안
    assert h.calculate_setpoint(_utc(2026, 11, 12, 1, 30), start)[0] == pytest.approx(1800.0)
    assert h.calculate_setpoint(_utc(2026, 11, 12, 3, 0), start) == (None, True)


def test_duration_determine_end_time_formats():
    h = _duration()
    expect = _utc(2026, 11, 12, 3, 0)
    assert h.determine_end_time('2026-11-12 02:00:00') == expect
    assert h.determine_end_time('2026-11-12 02:00:00+00:00') == expect
    assert h.determine_end_time(_utc(2026, 11, 12, 2, 0)) == expect
    # 못 읽는 시작은 지금부터 — 서기 1년 같은 끝 시각이 나오지 않는다
    end = h.determine_end_time(None)
    assert end > _utc(2026, 1, 1)


# ── Daily·DailySine·DailyBezier·DailyMultiPoint: DST 날 벽시계로 판정 ─────────

def test_daily_uses_local_wallclock_on_dst_day(tz_is):
    tz_is(NY)
    h = M.DailyMethod(_meth('Daily'), _Q([_row(time_start='06:00:00', time_end='18:00:00')]))
    # DST 시작일 12:00 EDT(=16:00 UTC) 는 구간 한가운데
    noon = NY.localize(datetime.datetime(2026, 3, 8, 12, 0)).astimezone(pytz.utc)
    assert h.calculate_setpoint(noon)[0] == pytest.approx(15.0)
    # 같은 UTC 시각이 UTC 로 판정되면 16:00 → 5/6 지점이 된다
    assert h.calculate_setpoint(noon)[0] != pytest.approx(10 + 10 * 10 / 12)


def test_daily_sine_phase_follows_local_wallclock(tz_is):
    tz_is(KST)
    row = _row(amplitude=1.0, frequency=1.0, shift_angle=0.0, shift_y=0.0)
    h = M.DailySineMethod(_meth('DailySine'), _Q([row]))
    # 06:00 KST(=전날 21:00 UTC): 각도 90° → sin = 1
    t = KST.localize(datetime.datetime(2026, 11, 12, 6, 0)).astimezone(pytz.utc)
    assert h.calculate_setpoint(t)[0] == pytest.approx(1.0)


def test_daily_multipoint_t_sec_local_on_dst_day():
    pts = {
        'version': 3, 'weeks': [0],
        'points': [
            {'point_id': 0, 't_sec': 0, 'values': [0.0], 'smooth': False,
             'curve': 'linear', 'handle_dt': None, 'handle_dv': None, 'is_endpoint': True},
            {'point_id': 1, 't_sec': 86400, 'values': [24.0], 'smooth': False,
             'curve': 'linear', 'handle_dt': None, 'handle_dv': None, 'is_endpoint': True},
        ]}
    import json
    row = NS(points_json=json.dumps(pts), output_id=None, duration_sec=None)
    h = M.DailyMultiPointMethod(_meth('DailyMultiPoint'), _Q([row]))
    # DST 시작일 15:00 EDT → 벽시계 15시 → 15.0 (UTC 로 읽으면 19.0)
    t = NY.localize(datetime.datetime(2026, 3, 8, 15, 0)).astimezone(pytz.utc)
    v, _ = h.calculate_setpoint(t, weeks_elapsed=0.0, facility_tz=NY)
    assert v == pytest.approx(15.0, abs=1e-6)
    # 로드하우 30분 DST
    t = LH.localize(datetime.datetime(2026, 4, 5, 15, 30)).astimezone(pytz.utc)
    v, _ = h.calculate_setpoint(t, weeks_elapsed=0.0, facility_tz='Australia/Lord_Howe')
    assert v == pytest.approx(15.5, abs=1e-6)


# ── PIDController ────────────────────────────────────────────────────────

def _pid(monkeypatch, row, tz=None):
    from aot.controllers import controller_pid as cp
    c = cp.PIDController.__new__(cp.PIDController)
    c.logger = logging.getLogger('test_pid_s4')
    c.unique_id = 'pid-1'
    c._facility_tz = tz
    monkeypatch.setattr(cp, 'db_retrieve_table_daemon', lambda *_a, **_k: row)
    return c, cp


def _freeze(monkeypatch, cp, now):
    monkeypatch.setattr(cp, 'utc_now', lambda: now)


def test_weeks_elapsed_schedule_date_is_local_midnight(monkeypatch):
    row = NS(schedule_start_time='2026-03-01', schedule_week_offset=0.0)
    c, cp = _pid(monkeypatch, row, tz=NY)
    # 3/1 00:00 EST = 05:00 UTC 가 0주 — 날짜만 준 시작일은 시설 현지 자정으로 읽는다.
    _freeze(monkeypatch, cp, _utc(2026, 3, 8, 5, 0))
    assert c._get_weeks_elapsed(None) == pytest.approx(1.0)
    # 주차는 흐른 시간이다: DST 를 지난 "벽시계 2주" 는 순간으로 2주 − 1시간
    _freeze(monkeypatch, cp, _utc(2026, 3, 15, 4, 0))
    assert c._get_weeks_elapsed(None) == pytest.approx(2.0 - 1 / 168)


def test_weeks_elapsed_schedule_date_seoul_and_offset(monkeypatch):
    row = NS(schedule_start_time='2026-11-01', schedule_week_offset=1.5)
    c, cp = _pid(monkeypatch, row, tz=KST)
    _freeze(monkeypatch, cp, _utc(2026, 11, 7, 15, 0))     # 11/8 00:00 KST = 1주
    assert c._get_weeks_elapsed(None) == pytest.approx(2.5)


def test_weeks_elapsed_future_start_clamps_to_zero(monkeypatch):
    row = NS(schedule_start_time='2027-01-01', schedule_week_offset=0.0)
    c, cp = _pid(monkeypatch, row, tz=KST)
    _freeze(monkeypatch, cp, _utc(2026, 11, 7))
    assert c._get_weeks_elapsed(None) == 0.0


def test_weeks_elapsed_falls_back_to_method_start(monkeypatch):
    row = NS(schedule_start_time='', schedule_week_offset=0.0)
    c, cp = _pid(monkeypatch, row, tz=KST)
    _freeze(monkeypatch, cp, _utc(2026, 11, 15, 0, 0))
    # 오프셋 있는 값·없는 옛 값(UTC) 둘 다
    assert c._get_weeks_elapsed('2026-11-01 00:00:00+00:00') == pytest.approx(2.0)
    assert c._get_weeks_elapsed('2026-11-01 00:00:00') == pytest.approx(2.0)
    assert c._get_weeks_elapsed('garbage') == 0.0


@pytest.mark.parametrize('value,expected', [
    (0, 0.0), (None, 0.0), (10, 10.0), (-5, 0.0),
    (float('nan'), 0.0), (float('inf'), 0.0), ('abc', 0.0),
])
def test_start_offset_is_always_finite(monkeypatch, value, expected):
    c, _ = _pid(monkeypatch, NS())
    c.start_offset = value
    assert c._start_offset_s() == expected


def test_last_measurement_log_time_is_labeled_not_container_clock():
    """디버그 로그의 측정 시각은 컨테이너 OS 시계가 아니라 시설 시계 + 오프셋."""
    from aot.utils.timekit import iso_at
    ts = _utc(2026, 11, 12, 3, 0).timestamp()
    assert iso_at(ts, KST) == '2026-11-12T12:00:00+09:00'
    assert iso_at(ts, NY) == '2026-11-11T22:00:00-05:00'
