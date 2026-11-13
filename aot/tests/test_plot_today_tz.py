"""구획의 '오늘' 은 서버 날짜가 아니라 그 구획 현지 날짜다 (S7).

로컬 장치가 전부 +09:00 이라 8084 값으로는 가릴 수 없다 — 뉴욕(DST)으로 시험한다.
"""
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest import mock

import pytz

from aot.space import plot_context
from aot.utils import timekit

NY = pytz.timezone('America/New_York')


def _row():
    return SimpleNamespace(started_on=date(2026, 3, 1), ended_on=None)


class PlotTodayTz(unittest.TestCase):
    def _days(self, utc_instant):
        with mock.patch.object(timekit, 'utc_now', return_value=utc_instant), \
                mock.patch.object(timekit, '_row_tz', return_value=(NY, 'device')):
            return plot_context.elapsed_days(_row())

    def test_dst_start_night_uses_edt_not_est(self):
        # 2026-03-09 04:30Z = 뉴욕 03-09 00:30 EDT (고정 -05:00 이면 03-08 23:30)
        self.assertEqual(self._days(datetime(2026, 3, 9, 4, 30, tzinfo=timezone.utc)), 9)

    def test_new_york_evening_is_still_previous_day(self):
        # 2026-03-09 03:30Z = 뉴욕 03-08 23:30 EDT (UTC 날짜는 03-09)
        self.assertEqual(self._days(datetime(2026, 3, 9, 3, 30, tzinfo=timezone.utc)), 8)

    def test_dst_end_boundary(self):
        # 2026-11-01 05:30Z = 뉴욕 01:30 EDT, 06:30Z = 01:30 EST — 같은 날
        for h in (5, 6):
            with mock.patch.object(timekit, 'utc_now',
                                   return_value=datetime(2026, 11, 1, h, 30, tzinfo=timezone.utc)), \
                    mock.patch.object(timekit, '_row_tz', return_value=(NY, 'device')):
                self.assertEqual(timekit.today_at(object()), date(2026, 11, 1))


if __name__ == '__main__':
    unittest.main()
