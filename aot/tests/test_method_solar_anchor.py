# coding=utf-8
"""Unit tests for solar-anchored daily setpoint curves (7단계).

- 하루 단위 메서드가 **위치의 벽시계**로 판정되는지 (기존 UTC 판정 버그)
- 구간의 양 끝을 태양 이벤트에 걸 수 있는지

DB 는 건드리지 않는다 — Method/MethodData 는 스텁으로 대체한다.
"""
import datetime
from types import SimpleNamespace

import pytest
import pytz

from aot.utils.method import DailyMethod

KST = pytz.timezone('Asia/Seoul')


class _DataQuery:
    """MethodData 쿼리 흉내 — filter(...).all()/.first() 만 쓰인다."""

    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_k):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


def _row(time_start='06:00:00', time_end='18:00:00',
         setpoint_start=18.0, setpoint_end=24.0, **anchors):
    base = dict(
        time_start=time_start, time_end=time_end,
        setpoint_start=setpoint_start, setpoint_end=setpoint_end,
        time_start_event=None, time_start_offset_min=0,
        time_end_event=None, time_end_offset_min=0,
        output_id=None, duration_sec=None,
    )
    base.update(anchors)
    return SimpleNamespace(**base)


def _handler(rows, target_id=None):
    method = SimpleNamespace(unique_id='m-1', method_type='Daily', name='m')
    return DailyMethod(method, _DataQuery(rows), None, target_id=target_id)


@pytest.fixture(autouse=True)
def _farm_tz(monkeypatch):
    """위치 해석은 항상 Asia/Seoul 로 — DB 없이 결정적으로."""
    monkeypatch.setattr('aot.utils.device_tz.resolve_location_tz',
                        lambda *_a, **_k: KST)


def _utc(hour_kst, minute=0):
    return KST.localize(
        datetime.datetime(2026, 7, 31, hour_kst, minute)).astimezone(pytz.utc)


# ---------------------------------------------------------------------------
# 벽시계 해석 — UTC 가 아니라 위치 현지시각
# ---------------------------------------------------------------------------

def test_daily_curve_uses_location_wallclock():
    """12:00 KST(=03:00 UTC)는 06–18 구간의 한가운데다.

    예전 구현은 UTC 시각(03:00)으로 판정해 구간 밖으로 떨어뜨렸다.
    """
    h = _handler([_row()])
    setpoint, ended = h.calculate_setpoint(_utc(12))
    assert ended is False
    assert setpoint == pytest.approx(21.0, abs=0.1)


def test_evening_is_outside_the_window():
    """19:00 KST(=10:00 UTC). UTC 로 읽으면 구간 안이라 값이 나와 버렸다."""
    h = _handler([_row()])
    assert h.calculate_setpoint(_utc(19)) == (None, False)


def test_early_morning_is_outside_the_window():
    h = _handler([_row()])
    assert h.calculate_setpoint(_utc(5)) == (None, False)


def test_naive_datetime_is_treated_as_wallclock():
    """플롯 경로가 넘기는 naive 시각은 변환하지 않는다."""
    h = _handler([_row()])
    setpoint, _ended = h.calculate_setpoint(datetime.datetime(1900, 1, 1, 12, 0))
    assert setpoint == pytest.approx(21.0, abs=0.1)


# ---------------------------------------------------------------------------
# 태양 앵커
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_sun(monkeypatch):
    """오늘 일출 05:39 / 일몰 19:38 (KST) 로 고정."""
    times = SimpleNamespace(
        sunrise=KST.localize(datetime.datetime(2026, 7, 31, 5, 39)).astimezone(pytz.utc),
        sunset=KST.localize(datetime.datetime(2026, 7, 31, 19, 38)).astimezone(pytz.utc),
        solar_noon=KST.localize(datetime.datetime(2026, 7, 31, 12, 38)).astimezone(pytz.utc),
        civil_dawn=None, civil_dusk=None,
    )
    times.event = lambda kind: getattr(times, kind, None)
    monkeypatch.setattr('aot.utils.solar.sun_times', lambda **_k: times)
    return times


def test_anchor_replaces_stored_clock(stub_sun):
    h = _handler([_row(time_start_event='sunrise', time_start_offset_min=30,
                       time_end_event='sunset', time_end_offset_min=-60)])
    row = h.method_data_all[0]
    assert h.resolve_daily_bound(row, 'start').strftime('%H:%M') == '06:09'
    assert h.resolve_daily_bound(row, 'end').strftime('%H:%M') == '18:38'


def test_anchor_widens_the_window(stub_sun):
    """일출~일몰 그대로 걸면 저장된 06–18 보다 넓어진다(여름)."""
    h = _handler([_row(time_start_event='sunrise', time_end_event='sunset')])
    # 05:50 KST — 고정 시각(06:00)으로는 구간 밖, 일출 기준으로는 안.
    setpoint, _ended = h.calculate_setpoint(_utc(5, 50))
    assert setpoint is not None


def test_only_one_end_anchored(stub_sun):
    """한쪽만 걸 수 있다 — 나머지는 저장된 벽시계 그대로."""
    h = _handler([_row(time_end_event='sunset')])
    row = h.method_data_all[0]
    assert h.resolve_daily_bound(row, 'start').strftime('%H:%M') == '06:00'
    assert h.resolve_daily_bound(row, 'end').strftime('%H:%M') == '19:38'


def test_unknown_event_falls_back_to_clock(stub_sun):
    h = _handler([_row(time_start_event='moonrise')])
    row = h.method_data_all[0]
    assert h.resolve_daily_bound(row, 'start').strftime('%H:%M') == '06:00'


def test_missing_event_falls_back_to_clock(stub_sun):
    """극지에서 그 이벤트가 없는 날 — 곡선을 잃지 않고 저장된 시각을 쓴다."""
    h = _handler([_row(time_start_event='civil_dawn')])   # 스텁에서 None
    row = h.method_data_all[0]
    assert h.resolve_daily_bound(row, 'start').strftime('%H:%M') == '06:00'


def test_no_anchor_keeps_previous_behaviour(stub_sun):
    h = _handler([_row()])
    row = h.method_data_all[0]
    assert h.resolve_daily_bound(row, 'start').strftime('%H:%M') == '06:00'
    assert h.resolve_daily_bound(row, 'end').strftime('%H:%M') == '18:00'


def test_plot_reflects_resolved_anchors(stub_sun):
    """그래프가 저장된 시각으로 그려지면 실제 동작과 어긋나 보인다."""
    h = _handler([_row(time_start_event='sunrise', time_start_offset_min=30,
                       time_end_event='sunset', time_end_offset_min=-60)])
    plot = h.get_plot()
    start_sec = plot[0][0] / 1000
    end_sec = plot[1][0] / 1000
    assert int(start_sec // 3600) == 6 and int(start_sec % 3600 // 60) == 9
    assert int(end_sec // 3600) == 18 and int(end_sec % 3600 // 60) == 38


def test_segment_without_times_is_skipped(stub_sun):
    h = _handler([_row(time_start=None, time_end=None)])
    assert h.calculate_setpoint(_utc(12)) == (None, False)


# ---------------------------------------------------------------------------
# 공식 곡선(sine/bezier) 위상 고정 · Cascade 전달
# ---------------------------------------------------------------------------

def _sine_handler(event=None, offset=0, target_id=None):
    from aot.utils.method import DailySineMethod
    row = SimpleNamespace(amplitude=1.0, frequency=1.0, shift_angle=0.0, shift_y=20.0,
                          time_start_event=event, time_start_offset_min=offset,
                          output_id=None, duration_sec=None)
    method = SimpleNamespace(unique_id='s-1', method_type='DailySine', name='s')
    return DailySineMethod(method, _DataQuery([row]), None, target_id=target_id)


@pytest.fixture
def stub_noon(monkeypatch):
    """남중 12:38 KST 로 고정 — 시계 정오보다 38분 늦다."""
    times = SimpleNamespace(
        solar_noon=KST.localize(datetime.datetime(2026, 7, 31, 12, 38)).astimezone(pytz.utc),
        sunrise=None, sunset=None, civil_dawn=None, civil_dusk=None)
    times.event = lambda kind: getattr(times, kind, None)
    monkeypatch.setattr('aot.utils.solar.sun_times', lambda **_k: times)
    return times


def _peak_minute(handler):
    """곡선이 최대가 되는 현지 시각(분)."""
    return max(range(0, 24 * 60, 5),
               key=lambda m: handler.calculate_setpoint(_utc(m // 60, m % 60))[0])


def test_sine_without_anchor_peaks_on_the_clock(stub_noon):
    assert _peak_minute(_sine_handler()) == 6 * 60


def test_sine_anchor_shifts_peak_by_solar_noon_offset(stub_noon):
    """남중이 12:38 이면 곡선 전체가 38분 뒤로 밀린다."""
    assert _peak_minute(_sine_handler(event='solar_noon')) == 6 * 60 + 40  # 5분 격자


def test_sine_anchor_offset_shifts_further(stub_noon):
    peak = _peak_minute(_sine_handler(event='solar_noon', offset=60))
    assert peak == 7 * 60 + 40


def test_sine_anchor_falls_back_when_event_missing(monkeypatch):
    """남중을 못 구하면 보정 없이 벽시계 그대로 — 곡선을 잃지 않는다."""
    times = SimpleNamespace(solar_noon=None)
    times.event = lambda kind: None
    monkeypatch.setattr('aot.utils.solar.sun_times', lambda **_k: times)
    assert _peak_minute(_sine_handler(event='solar_noon')) == 6 * 60


def test_bezier_uses_the_same_shift(stub_noon):
    from aot.utils.method import DailyBezierMethod
    row = SimpleNamespace(shift_angle=0.0, x0=86400, y0=20.0, x1=60000, y1=25.0,
                          x2=30000, y2=25.0, x3=0, y3=20.0,
                          time_start_event='solar_noon', time_start_offset_min=0,
                          output_id=None, duration_sec=None)
    method = SimpleNamespace(unique_id='b-1', method_type='DailyBezier', name='b')
    handler = DailyBezierMethod(method, _DataQuery([row]), None)
    # 보정이 걸리면 같은 시각이라도 다른 x 를 쓴다.
    assert handler.day_seconds(_utc(12)) == pytest.approx(12 * 3600 - 38 * 60, abs=1)


def test_cascade_passes_target_id_to_linked_methods(monkeypatch):
    """하위 메서드가 위치를 모르면 태양 앵커·현지시각이 농장 전역으로 떨어진다."""
    from aot.utils import method as method_module

    seen = {}

    def _fake_load(method_id, logger=None, target_id=None):
        seen['target_id'] = target_id
        return None

    monkeypatch.setattr(method_module, 'load_method_handler', _fake_load)

    row = SimpleNamespace(linked_method_id='inner', output_id=None, duration_sec=None)
    method = SimpleNamespace(unique_id='c-1', method_type='Cascade', name='c')
    handler = method_module.CascadeMethod(
        method, _DataQuery([row]), None, target_id='zone-42')
    handler.calculate_setpoint(_utc(12))
    assert seen['target_id'] == 'zone-42'
