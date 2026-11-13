# coding=utf-8
"""구획 화면이 곡선에 넘기는 재배 시작 시각 — 그 구획 시계의 자정이라는 **순간**.

구획 모달(`coordinator_plot._resolve_curve_targets`)과 일지(`calc._curve_profile`)는
재배 시작일을 `method_start_time` 으로 넘긴다. 예전에는 naive 자정을 넘겼고, 메서드는
naive 시작을 UTC 로 읽으므로(저장 규약) 기간형(Duration) 곡선이 시간대만큼 늦게
시작했다 — 서울이면 9시간(현지 정오에 12 가 아니라 3).

시간대 3곳: 서울(DST 없음), 뉴욕의 DST 시작일(23시간)·종료일(25시간).
"""
import datetime
from types import SimpleNamespace as NS
from unittest import mock

import pytest
import pytz

from aot.utils import method as M
from aot.utils.method import local_midnight
from aot.utils.timekit import wall_to_utc

UTC = datetime.timezone.utc
SEOUL = pytz.timezone('Asia/Seoul')
NY = pytz.timezone('America/New_York')


class _Q:
    def __init__(self, rows):
        self._r = rows

    def filter(self, *_a, **_k):
        return self

    def all(self):
        return list(self._r)

    def first(self):
        return self._r[0] if self._r else None


def _duration(hours=48):
    """시작부터 시간당 1 씩 오르는 기간형 곡선 — 값이 곧 경과 시간."""
    row = NS(duration_sec=hours * 3600, setpoint_start=0.0,
             setpoint_end=float(hours), duration_end=None, output_id=None)
    return M.DurationMethod(NS(unique_id='d-1', method_type='Duration', name='d'),
                            _Q([row]))


# ── local_midnight ──────────────────────────────────────────────────────

@pytest.mark.parametrize('tz, day, utc_hour', [
    (SEOUL, datetime.date(2026, 11, 12), (2026, 11, 11, 15)),
    (NY, datetime.date(2026, 3, 8), (2026, 3, 8, 5)),      # DST 시작일 자정은 아직 EST
    (NY, datetime.date(2026, 11, 1), (2026, 11, 1, 4)),    # DST 종료일 자정은 아직 EDT
    (None, datetime.date(2026, 11, 12), (2026, 11, 12, 0)),
])
def test_local_midnight_is_that_clocks_midnight(tz, day, utc_hour):
    got = local_midnight(day, tz)
    assert got.tzinfo is not None
    assert got.astimezone(UTC) == datetime.datetime(*utc_hour, tzinfo=UTC)


# ── 일지: _curve_profile ────────────────────────────────────────────────

@pytest.mark.parametrize('tz, day', [
    (SEOUL, datetime.date(2026, 11, 12)),
    (NY, datetime.date(2026, 3, 8)),       # 23시간 날
    (NY, datetime.date(2026, 11, 1)),      # 25시간 날
])
def test_journal_duration_curve_counts_from_local_midnight(tz, day):
    from aot.aot_flask.geo.plot_journal import calc
    profile = calc._curve_profile(_duration(), None, tz, day,
                                  start_dt=local_midnight(day, tz))
    assert profile is not None
    start = local_midnight(day, tz)
    for i, value in enumerate(profile):
        wall = datetime.datetime.combine(day, datetime.time.min) + datetime.timedelta(
            seconds=i * calc.CURVE_SAMPLE_SEC + calc.CURVE_SAMPLE_SEC // 2)
        expected = (wall_to_utc(wall, tz) - start).total_seconds() / 3600
        assert value == pytest.approx(expected), (i, wall)


def test_journal_naive_start_is_read_as_the_plots_wallclock():
    """naive 시작이 와도 UTC 가 아니라 그 구획의 벽시계로 읽는다."""
    from aot.aot_flask.geo.plot_journal import calc
    day = datetime.date(2026, 11, 12)
    naive = calc._curve_profile(_duration(), None, SEOUL, day,
                                start_dt=datetime.datetime(2026, 11, 12))
    aware = calc._curve_profile(_duration(), None, SEOUL, day,
                                start_dt=local_midnight(day, SEOUL))
    assert naive == aware
    noon = (12 * 3600) // calc.CURVE_SAMPLE_SEC
    assert naive[noon] == pytest.approx(12 + calc.CURVE_SAMPLE_SEC / 2 / 3600)


# ── 구획 모달: _resolve_curve_targets ────────────────────────────────────

class _Spy:
    def __init__(self, real):
        self.real = real
        self.starts = []

    def calculate_setpoint(self, now, method_start_time=None):
        self.starts.append(method_start_time)
        return self.real.calculate_setpoint(now, method_start_time=method_start_time)


@pytest.mark.parametrize('tz', [SEOUL, NY])
def test_modal_duration_curve_counts_from_local_midnight(tz):
    from aot.space import coordinator_plot as CP
    started = datetime.date(2026, 11, 12)
    plot = NS(unique_id='plot-1', program_uuid='prog-1', facility_uuid=None,
              started_on=started)
    spy = _Spy(_duration())
    now = local_midnight(started, tz) + datetime.timedelta(hours=12)
    prog = mock.Mock(targets_methods={'vpd': 'curve-1'})
    with mock.patch('aot.databases.models.GeoProgram') as geo_program, \
            mock.patch('aot.utils.timekit.tz_of', return_value=tz), \
            mock.patch('aot.utils.method.load_method_handler', return_value=spy), \
            mock.patch('time.time', return_value=now.timestamp()):
        geo_program.query.filter_by.return_value.first.return_value = prog
        out = CP._resolve_curve_targets(plot, ['vpd'], on=started)
    start = spy.starts[-1]
    assert start.tzinfo is not None
    assert start == local_midnight(started, tz)
    assert out['vpd'] == pytest.approx(12.0)    # 예전: 서울 3.0
