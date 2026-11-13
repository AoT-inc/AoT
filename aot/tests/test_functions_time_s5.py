# coding=utf-8
"""Function 시간 점검 S5 — 사용자 Function 모듈의 시간 처리.

고친 것(각 시험 클래스 머리말에 근거):
- 루프 주기 0·음수·숫자 아님이면 `while timer_loop < now: timer_loop += 주기` 가 끝나지
  않는다(모듈 ≈35개) → 옵션을 읽은 직후 한 곳(`AbstractFunction`)에서 고친다.
- `controller_function` 의 같은 루프를 산술로(주기 0·시계 점프에도 안전).
- LCD·OLED 12종이 컨테이너 시계로 시각을 적던 것 → 장소 시계.
- 카메라 파일명·타임랩스 시각이 컨테이너 시계였고, 타임랩스 주기 0 이면 루프가 멈췄다.
- `sum_accumulate` 점 모드 스냅샷이 DST 날 한 시간 밀리고, 가을 25시간 날 미래 시각이 나왔다.
"""
import ast
import glob
import logging
import os
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
import pytz

from aot.functions.base_function import AbstractFunction

FUNCTIONS_DIR = os.path.join(os.path.dirname(__file__), '..', 'functions')
NY = pytz.timezone('America/New_York')
SEOUL = pytz.timezone('Asia/Seoul')


def _utc(y, mo, d, h=0, mi=0):
    return pytz.utc.localize(datetime(y, mo, d, h, mi)).timestamp()


# ---------------------------------------------------------------------------
# 루프 주기 점검 (AbstractFunction)
# ---------------------------------------------------------------------------
class _Fn(AbstractFunction):
    def __init__(self):  # DB 없이
        self.logger = logging.getLogger('test.fn_period')


OPTS = [{'id': 'period', 'type': 'text', 'default_value': 60},
        {'id': 'update_period', 'type': 'text', 'default_value': 5},
        {'id': 'other', 'type': 'text', 'default_value': 0}]


class TestLoopPeriodSanitized:

    @pytest.mark.parametrize('raw, expected', [
        (0, 60), (-5, 60), (None, 60), ('abc', 60), (float('nan'), 60),
        (float('inf'), 60), (0.0, 60),
        (30, 30), (2.5, 2.5), ('45', 45.0),
    ])
    def test_period(self, raw, expected):
        f = _Fn()
        f.period = raw
        f.update_period = 7
        f._ensure_positive_loop_periods(OPTS)
        assert f.period == expected
        assert f.update_period == 7

    def test_update_period_falls_back_to_its_own_default(self):
        f = _Fn()
        f.period = 10
        f.update_period = 0
        f._ensure_positive_loop_periods(OPTS)
        assert f.update_period == 5.0

    def test_other_options_untouched(self):
        f = _Fn()
        f.period, f.update_period, f.other = 10, 10, 0
        f._ensure_positive_loop_periods(OPTS)
        assert f.other == 0

    def test_module_without_period_attr_is_skipped(self):
        f = _Fn()
        f._ensure_positive_loop_periods(OPTS)  # 예외 없음

    def test_loop_terminates_after_fix(self):
        """고친 주기로는 모듈이 쓰는 while 이 끝난다(고치기 전엔 period=0 에서 영영 돌았다)."""
        f = _Fn()
        f.period = 0
        f._ensure_positive_loop_periods(OPTS)
        timer_loop = time.time() - 600
        n = 0
        while timer_loop < time.time():
            timer_loop += f.period
            n += 1
            assert n < 1000
        assert n == 10 or n == 11


# ---------------------------------------------------------------------------
# controller_function.loop_is_due
# ---------------------------------------------------------------------------
class TestControllerFunctionDue:

    def _ctl(self, rate, timer_loop):
        from aot.controllers.controller_function import FunctionController
        c = FunctionController.__new__(FunctionController)
        c.logger = logging.getLogger('test.fc')
        c.sample_rate = rate
        c.timer_loop = timer_loop
        c._bad_rate_logged = False
        return c

    @pytest.mark.parametrize('rate', [0, -3, None, 'x', float('inf')])
    def test_bad_rate_does_not_hang(self, rate):
        c = self._ctl(rate, 1000.0)
        assert c.loop_is_due(1010.5) is True      # 1초로 대신 — 끝난다
        assert c.timer_loop == pytest.approx(1011.0)

    def test_not_due_before_time(self):
        c = self._ctl(5, 2000.0)
        assert c.loop_is_due(1999.0) is False
        assert c.timer_loop == 2000.0

    def test_due_advances_past_now_without_loop(self):
        c = self._ctl(5, 0.0)
        now = 1.7e9
        assert c.loop_is_due(now) is True         # 3.4억 번 더하지 않는다
        assert now < c.timer_loop <= now + 5

    def test_clock_stepped_back_restarts_count(self):
        c = self._ctl(5, 5000.0)                  # 시계가 1시간 가까이 뒤로 감
        assert c.loop_is_due(1000.0) is True
        assert 1000.0 < c.timer_loop <= 1005.0

    def test_small_future_timer_is_just_waiting(self):
        c = self._ctl(5, 1003.0)
        assert c.loop_is_due(1000.0) is False
        assert c.timer_loop == 1003.0


# ---------------------------------------------------------------------------
# 표시 시각 — 장소 시계
# ---------------------------------------------------------------------------
class TestPlaceClock:

    def test_epoch_in_place_tz(self):
        from aot.functions.utils.place_clock import place_time_str
        t = _utc(2026, 11, 11, 15, 0)
        assert place_time_str(t, SEOUL) == '2026-11-12 00:00:00'
        assert place_time_str(t, NY) == '2026-11-11 10:00:00'

    def test_dst_offsets(self):
        from aot.functions.utils.place_clock import place_time_str
        assert place_time_str(_utc(2026, 7, 1, 12), NY) == '2026-07-01 08:00:00'
        assert place_time_str(_utc(2026, 1, 1, 12), NY) == '2026-01-01 07:00:00'

    def test_bad_value_is_empty_or_raises_value_error(self):
        from aot.functions.utils.place_clock import place_time_str
        assert place_time_str(None, SEOUL) == ''
        with pytest.raises(ValueError):
            place_time_str('not a time', SEOUL)

    def test_now_uses_place_clock(self, monkeypatch):
        import aot.functions.utils.place_clock as pc
        monkeypatch.setattr(pc, 'utc_now', lambda: pytz.utc.localize(datetime(2026, 11, 11, 15, 0)))
        assert pc.place_now_str(SEOUL) == '2026-11-12 00:00:00'


class TestNoContainerClockInFunctions:
    """check_time_rules 가 못 잡는 사각지대: tz 없는 fromtimestamp·time.strftime·time.localtime."""

    @staticmethod
    def _violations():
        out = []
        for path in sorted(glob.glob(os.path.join(FUNCTIONS_DIR, '**', '*.py'), recursive=True)):
            if os.sep + 'examples' + os.sep in path or os.path.basename(path).startswith('example_'):
                continue  # 사용자가 복사해 가는 견본 — 배포 코드 아님
            tree = ast.parse(open(path, encoding='utf-8').read())
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                name = node.func.attr
                owner = getattr(node.func.value, 'id', None) or getattr(node.func.value, 'attr', None)
                bad = False
                if name == 'fromtimestamp':
                    has_tz = len(node.args) >= 2 or any(k.arg == 'tz' for k in node.keywords)
                    bad = not has_tz
                elif owner == 'time' and name in ('strftime', 'localtime', 'ctime', 'asctime'):
                    bad = True
                if bad:
                    out.append('{}:{}'.format(os.path.relpath(path, FUNCTIONS_DIR), node.lineno))
        return out

    def test_none(self):
        assert self._violations() == []


# ---------------------------------------------------------------------------
# 카메라 — 파일명·타임랩스
# ---------------------------------------------------------------------------
class TestCamera:

    def _cam(self, monkeypatch):
        import aot.functions.camera_libcamera as cam
        monkeypatch.setattr(cam, 'to_tz', lambda v, where: pytz.utc.localize(
            datetime.utcfromtimestamp(v)).astimezone(SEOUL))
        c = cam.CustomModule.__new__(cam.CustomModule)
        c.logger = logging.getLogger('test.cam')
        c.unique_id = 'cam-1'
        c.tl_active = False
        c.tl_pause = False
        saved = {}
        c.set_custom_option = lambda k, v: saved.setdefault(k, v) if False else (saved.__setitem__(k, v) or v)
        c._saved = saved
        return cam, c

    def test_place_time_str_for_filename(self, monkeypatch):
        _cam_mod, c = self._cam(monkeypatch)
        assert c._place_time_str(_utc(2026, 11, 11, 15, 0), '%Y-%m-%d_%H-%M-%S') == '2026-11-12_00-00-00'

    @pytest.mark.parametrize('dur, per', [(0, 60), (3600, 0), (3600, -1), ('a', 60), (3600, None)])
    def test_timelapse_start_rejects_non_positive(self, monkeypatch, dur, per):
        _m, c = self._cam(monkeypatch)
        assert c.timelapse_start({'tl_duration_sec': dur, 'tl_period_sec': per}) is None
        assert c.tl_active is False
        assert 'tl_active' not in c._saved

    def test_timelapse_start_accepts_numeric_strings(self, monkeypatch):
        _m, c = self._cam(monkeypatch)
        assert c.timelapse_start({'tl_duration_sec': '3600', 'tl_period_sec': '60'}) == 'Timelapse started.'
        assert c.tl_period_sec == 60 and isinstance(c.tl_period_sec, int)
        assert c.tl_active is True
        assert c.tl_start_str.startswith('20')

    def test_loop_with_zero_period_stops_instead_of_hanging(self, monkeypatch):
        _m, c = self._cam(monkeypatch)
        c.tl_active, c.tl_pause = True, False
        c.timer_loop = time.time() - 10
        c.tl_period_sec = 0
        c.tl_start_epoch, c.tl_duration_sec = time.time(), 3600
        c.loop()
        assert c.tl_active is False


# ---------------------------------------------------------------------------
# sum_accumulate — 점 모드 스냅샷 격자
# ---------------------------------------------------------------------------
class TestSumAccumulateSnapshotGrid:

    def _fn(self, tz, snapshot_time='17:00', hours='24', point_count=3):
        import aot.functions.sum_accumulate as sa
        f = sa.CustomModule.__new__(sa.CustomModule)
        f.logger = logging.getLogger('test.sa')
        f.snapshot_time, f.snapshot_interval_hours = snapshot_time, hours
        f.point_count = point_count
        f._grid_tz = None
        f.last_processed_instant = None
        f._source_tz = lambda: tz
        f.set_custom_option = lambda k, v: v
        return f

    @staticmethod
    def _local(epoch, tz):
        return pytz.utc.localize(datetime.utcfromtimestamp(epoch)).astimezone(tz)

    def test_spring_forward_day_before_anchor(self):
        """3/8(봄, 02:00→03:00) 10:00 — 어제 17:00(EST)이어야 한다. 에폭 -86400 은 16:00."""
        f = self._fn(NY)
        now = _utc(2026, 3, 8, 14, 0)  # 10:00 EDT
        inst, interval = f._snapshot_geometry(now)
        loc = self._local(inst, NY)
        assert (loc.month, loc.day, loc.hour, loc.minute) == (3, 7, 17, 0)
        assert interval == 86400

    def test_spring_forward_day_after_anchor(self):
        f = self._fn(NY)
        inst, _ = f._snapshot_geometry(_utc(2026, 3, 8, 23, 0))  # 19:00 EDT
        loc = self._local(inst, NY)
        assert (loc.month, loc.day, loc.hour) == (3, 8, 17)

    def test_fall_back_25h_day_never_future(self):
        """11/1(가을, 25시간) 23:30 EST — 옛 코드는 k=1 로 내일 00:00 을 냈다."""
        f = self._fn(NY, snapshot_time='00:00')
        now = _utc(2026, 11, 2, 4, 30)  # 11/1 23:30 EST
        inst, _ = f._snapshot_geometry(now)
        assert inst <= now
        loc = self._local(inst, NY)
        assert (loc.month, loc.day, loc.hour) == (11, 1, 0)

    def test_previous_points_keep_wall_time_across_dst(self):
        f = self._fn(NY)
        inst, interval = f._snapshot_geometry(_utc(2026, 3, 9, 20, 0))  # 3/9 16:00 EDT
        seen = []
        f._read_point_value = lambda d, u, c, m, instant, iv: seen.append(instant) or 1.0
        f._store_at = lambda v, e: None
        f._process_instant(('d', 1, 'u', 'm'), inst, interval)
        hours = [(self._local(e, NY).day, self._local(e, NY).hour) for e in seen]
        assert hours == [(8, 17), (7, 17), (6, 17)]

    def test_backfill_instants_are_wall_aligned(self, monkeypatch):
        f = self._fn(NY)
        now = _utc(2026, 3, 10, 22, 0)  # 18:00 EDT
        # 3/6 17:00 EST 에 마지막으로 처리 — 3/7,3/8,3/9,3/10 이 밀렸다.
        f.last_processed_instant = NY.localize(datetime(2026, 3, 6, 17, 0)).timestamp()
        done = []
        f._source_info = lambda: ('d', 1, 'u', 'm')
        f._process_instant = lambda src, inst, iv: done.append(inst)
        f.timer_loop = 0
        import aot.functions.sum_accumulate as sa
        monkeypatch.setattr(sa, 'time', SimpleNamespace(time=lambda: now))
        f._loop_point()
        local = [self._local(e, NY) for e in done]
        assert [(d.day, d.hour) for d in local] == [(7, 17), (8, 17), (9, 17), (10, 17)]

    def test_backfill_realigns_stale_offset_instant(self, monkeypatch):
        """DST 전에 에폭 격자로 저장돼 한 시간 밀린 last_processed 도 현재 격자로 복구."""
        f = self._fn(NY)
        now = _utc(2026, 3, 9, 22, 0)  # 18:00 EDT
        f.last_processed_instant = NY.localize(datetime(2026, 3, 7, 17, 0)).timestamp() - 3600
        done = []
        f._source_info = lambda: ('d', 1, 'u', 'm')
        f._process_instant = lambda src, inst, iv: done.append(inst)
        f.timer_loop = 0
        import aot.functions.sum_accumulate as sa
        monkeypatch.setattr(sa, 'time', SimpleNamespace(time=lambda: now))
        f._loop_point()
        assert [self._local(e, NY).hour for e in done] == [17, 17]

    def test_seoul_unchanged(self):
        f = self._fn(SEOUL, snapshot_time='00:00')
        now = _utc(2026, 11, 11, 15, 0)  # 11/12 00:00 KST
        inst, _ = f._snapshot_geometry(now)
        assert inst == now

    def test_subdaily_grid_is_elapsed_time(self):
        f = self._fn(SEOUL, snapshot_time='00:00', hours='6')
        now = _utc(2026, 11, 11, 15, 0) + 7 * 3600  # 07:00 KST
        inst, interval = f._snapshot_geometry(now)
        assert interval == 6 * 3600
        assert inst == _utc(2026, 11, 11, 15, 0) + 6 * 3600

    def test_interval_mode_execute_now_does_not_spin(self):
        f = self._fn(SEOUL)
        f.period = 1.0
        f.last_sum_time = None
        f.timer_loop = 0
        f._source_info = lambda: None
        t0 = time.time()
        f._loop_period()
        assert time.time() - t0 < 1.0     # 1.7e9 번 더하지 않는다
        assert f.timer_loop > time.time() - 1


# ---------------------------------------------------------------------------
# lorawan_class_scheduler — 수동 창
# ---------------------------------------------------------------------------
class TestClassSchedulerManualWindow:

    def _sch(self, start='05:00', expire='17:00', tz=SEOUL, now=None):
        import aot.functions.lorawan_class_scheduler as cs
        s = cs.CustomModule.__new__(cs.CustomModule)
        s.logger = logging.getLogger('test.cs')
        s.unique_id = 'sch'
        s.manual_c_start, s.manual_c_expire = start, expire
        s._local_tz = lambda: tz
        s._local_now = lambda: pytz.utc.localize(datetime.utcfromtimestamp(now)).astimezone(tz)
        return s

    @staticmethod
    def _at(h, m=0, tz=SEOUL):
        return tz.localize(datetime(2026, 11, 11, h, m))

    @pytest.mark.parametrize('h, expected', [(4, False), (5, True), (12, True), (16, True), (17, False), (23, False)])
    def test_same_day_window(self, h, expected):
        s = self._sch()
        assert s._in_manual_window(self._at(h)) is expected

    @pytest.mark.parametrize('h, expected', [(21, False), (22, True), (23, True), (0, True), (5, True), (6, False), (12, False)])
    def test_overnight_window(self, h, expected):
        s = self._sch(start='22:00', expire='06:00')
        assert s._in_manual_window(self._at(h)) is expected

    def test_equal_start_end_is_empty(self):
        s = self._sch(start='08:00', expire='08:00')
        assert s._in_manual_window(self._at(8)) is False

    def test_expire_2400_is_next_midnight(self):
        now = SEOUL.localize(datetime(2026, 11, 11, 10, 0)).timestamp()
        s = self._sch(now=now)
        epoch = s._today_time_epoch('24:00')   # 예전엔 ValueError
        assert epoch == SEOUL.localize(datetime(2026, 11, 12, 0, 0)).timestamp()

    def test_expire_uses_place_tz_across_dst(self):
        now = NY.localize(datetime(2026, 3, 8, 10, 0)).timestamp()  # DST 시작 날
        s = self._sch(tz=NY, now=now)
        epoch = s._today_time_epoch('17:00')
        assert epoch == NY.localize(datetime(2026, 3, 8, 17, 0)).timestamp()
