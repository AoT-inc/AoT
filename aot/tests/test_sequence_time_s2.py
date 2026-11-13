# coding=utf-8
"""시퀀스 트리거의 시간 처리 — Function 시간 점검 S2.

본 것 (점검표 A~H):
- A 판정 시계: 요일·창 판정이 컨테이너 시계가 아니라 장소 시계(`device_tz`)다.
  같은 순간이 서울·뉴욕에서 다른 요일·다른 창 안팎이 된다.
- B/C DST·자정: 창 시작/끝 epoch 가 23시간·25시간짜리 날에도 벽시계에 붙고,
  밤샘(22:00~24:00 + 00:00~02:00) 창이 DST 를 지나도 끝이 벽시계 02:00 이다.
- E 재시작: 저장된 사이클을 복원할지 `주기 안인가` 로 정한다. 저장 시각이 지금보다
  미래(시계가 뒤로 갔다)면 믿지 않는다.
- G 간격: 사이클 격자는 단조 epoch 차이다 — DST 전환일에도 주기가 늘거나 줄지 않는다.
- H 표시: 상태 로그의 현지 시각에 어느 시계인지 붙는다.
"""
import datetime as dt
import logging
from unittest.mock import MagicMock

import pytest

import aot.controllers.controller_trigger_sequence as seq_mod
import aot.utils.timekit as tk
import aot.utils.weekly_schedule as ws

UTC = dt.timezone.utc
SEOUL = 'Asia/Seoul'
NY = 'America/New_York'
BERLIN = 'Europe/Berlin'
LORD_HOWE = 'Australia/Lord_Howe'   # 30분 DST


def at(tz, wall):
    """그 시계의 벽시각 → UTC aware."""
    return tk.wall_to_utc(dt.datetime.fromisoformat(wall), tz)


def wall(epoch, tz):
    return tk.to_tz(dt.datetime.fromtimestamp(epoch, UTC), tz).strftime('%Y-%m-%d %H:%M')


def _entry(start, end, period=3600, enabled=True):
    return {'enabled': enabled, 'start': start, 'end': end, 'period': period}


def _sched(days=None, default=None):
    """days: {요일: entry}. 나머지 요일은 default 항목(없으면 꺼짐)."""
    default = default or _entry('06:00', '07:00', enabled=False)
    return {'version': 1, 'mode': 'per_day', 'shared': {'start': '06:00', 'end': '07:00', 'period': 3600},
            'days': {str(i): dict((days or {}).get(i, default)) for i in range(7)}}


@pytest.fixture
def clock(monkeypatch):
    """`weekly_schedule.datetime.now(tz)` 를 고정한 순간으로 바꾼다 — 기존
    test_weekly_schedule.py 와 같은 자리(모듈의 `datetime`)를 갈아 끼우되
    `fromtimestamp` 등 나머지는 그대로 둔다."""
    real = dt.datetime
    state = {}

    class FakeDT(real):
        @classmethod
        def now(cls, tz=None):
            now = state['now']
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(ws, 'datetime', FakeDT)

    def set_now(value):
        state['now'] = value
    return set_now


# ---------------------------------------------------------------------------
# A. 판정 시계 — 장소 시계로 요일과 창을 판단한다
# ---------------------------------------------------------------------------

def test_same_instant_is_different_weekday_and_window_per_place(clock):
    """UTC 2026-06-01(월) 20:00 = 서울 화 05:00 = 뉴욕 월 16:00.
    월 15:00~17:00 창은 뉴욕에서만 안이다."""
    s = _sched({0: _entry('15:00', '17:00')})
    clock(dt.datetime(2026, 6, 1, 20, 0, tzinfo=UTC))
    assert ws.active_entry_now(s, SEOUL) is None
    got = ws.active_entry_now(s, NY)
    assert got is not None and got[0] == 0
    assert ws.get_today_idx(SEOUL) == 1       # 서울은 이미 화요일
    assert ws.get_today_idx(NY) == 0


@pytest.mark.parametrize('tz,now_wall,active', [
    # 창 [06:00, 07:00) — 끝 분은 닫힌다(07:00:00 에 닫힘).
    (SEOUL, '2026-06-01 06:00', True),
    (SEOUL, '2026-06-01 06:59', True),
    (SEOUL, '2026-06-01 07:00', False),
    (NY, '2026-06-01 05:59', False),
])
def test_window_edges(clock, tz, now_wall, active):
    s = _sched(default=_entry('06:00', '07:00'))
    clock(at(tz, now_wall))
    assert (ws.active_entry_now(s, tz) is not None) is active


def test_end_of_day_window_covers_last_minute_and_next_day_opens_at_midnight(clock):
    s = _sched({0: _entry('22:00', '24:00'), 1: _entry('00:00', '02:00')})
    clock(at(BERLIN, '2026-06-01 23:59'))
    assert ws.active_entry_now(s, BERLIN)[0] == 0
    clock(at(BERLIN, '2026-06-02 00:00'))
    assert ws.active_entry_now(s, BERLIN)[0] == 1


@pytest.mark.parametrize('tz,now_wall,idx', [
    # 뉴욕 DST 가 시작되는 날(일요일 2026-03-08)과 끝나는 날(2026-11-01)에도 요일이 맞다.
    (NY, '2026-03-08 03:30', 6),
    (NY, '2026-11-01 01:30', 6),
    (LORD_HOWE, '2026-10-04 02:45', 6),
])
def test_weekday_on_dst_days(clock, tz, now_wall, idx):
    clock(at(tz, now_wall))
    assert ws.get_today_idx(tz) == idx


# ---------------------------------------------------------------------------
# B/C. 창 경계 epoch — DST 와 자정
# ---------------------------------------------------------------------------

def test_window_bounds_on_spring_forward_day():
    """뉴욕 2026-03-08 은 23시간. 00:00~24:00 창의 길이가 23시간이다."""
    e = _entry('00:00', '24:00')
    now = at(NY, '2026-03-08 12:00').timestamp()
    start, end = ws.window_bounds_epoch(e, NY, now)
    assert wall(start, NY) == '2026-03-08 00:00'
    assert wall(end, NY) == '2026-03-09 00:00'
    assert end - start == 23 * 3600


def test_window_bounds_on_fall_back_day():
    """뉴욕 2026-11-01 은 25시간."""
    e = _entry('00:00', '24:00')
    now = at(NY, '2026-11-01 12:00').timestamp()
    start, end = ws.window_bounds_epoch(e, NY, now)
    assert end - start == 25 * 3600


def test_window_start_in_spring_gap_reads_as_standard_time():
    """없는 시각(02:30)에 시작하는 창은 표준시로 읽는다(03:30 EDT) — `wall_to_utc` 규약."""
    now = at(NY, '2026-03-08 12:00').timestamp()
    start = ws.window_start_epoch(_entry('02:30', '05:00'), NY, now)
    assert wall(start, NY) == '2026-03-08 03:30'


def test_lord_howe_half_hour_dst_window():
    """로드하우 2026-10-04 은 23.5시간(02:00 → 02:30)."""
    e = _entry('00:00', '24:00')
    now = at(LORD_HOWE, '2026-10-04 12:00').timestamp()
    start, end = ws.window_bounds_epoch(e, LORD_HOWE, now)
    assert end - start == 23.5 * 3600


def test_overnight_window_across_spring_forward():
    """토 22:00~24:00 + 일 00:00~06:00 (뉴욕, 일요일이 DST 시작일).
    끝은 일요일 벽시계 06:00 이고 UTC 로는 10:00(EDT)."""
    s = _sched({5: _entry('22:00', '24:00'), 6: _entry('00:00', '06:00')})
    sat_23 = at(NY, '2026-03-07 23:00').timestamp()
    end = ws.continuous_window_end_epoch(s, 5, NY, sat_23)
    assert wall(end, NY) == '2026-03-08 06:00'
    assert dt.datetime.fromtimestamp(end, UTC) == dt.datetime(2026, 3, 8, 10, 0, tzinfo=UTC)


def test_overnight_window_week_wrap():
    """일요일 → 월요일(주 경계)로 이어진다."""
    s = _sched({6: _entry('23:00', '24:00'), 0: _entry('00:00', '01:00')})
    sun_2330 = at(SEOUL, '2026-06-07 23:30').timestamp()
    end = ws.continuous_window_end_epoch(s, 6, SEOUL, sun_2330)
    assert wall(end, SEOUL) == '2026-06-08 01:00'


def test_month_end_rollover():
    """월말(5/31 → 6/1) 자정 이음도 날짜 계산에 의존하지 않는다."""
    s = _sched({6: _entry('23:00', '24:00'), 0: _entry('00:00', '01:00')})   # 2026-05-31 은 일요일
    t = at(BERLIN, '2026-05-31 23:10').timestamp()
    end = ws.continuous_window_end_epoch(s, 6, BERLIN, t)
    assert wall(end, BERLIN) == '2026-06-01 01:00'


# ---------------------------------------------------------------------------
# G. 사이클 격자 — 단조 epoch 간격
# ---------------------------------------------------------------------------

def make_controller(tz=SEOUL, period=3600.0):
    inst = object.__new__(seq_mod.SequenceTriggerController)
    inst.unique_id = 'seq-time-s2-0000'
    inst.logger = MagicMock()
    inst.cycle_start_time = None
    inst.device_tz = tz
    inst.sequence_cycle_duration = period
    inst.active_actions = set()
    inst._runt_logged_start = None
    inst._skip_logged_start = None
    inst.is_activated = True
    return inst


def test_cycle_grid_after_dst_jump_is_still_hourly_in_wall_clock():
    """뉴욕 DST 시작일 00:00~24:00, 1시간 주기: 03:00 EDT 이후에도 정시(:00)에 시작한다."""
    inst = make_controller(NY)
    e = _entry('00:00', '24:00')
    now = at(NY, '2026-03-08 04:20').timestamp()
    start = inst._next_cycle_start(e, now, 3600.0)
    assert wall(start, NY) == '2026-03-08 04:00'


def test_cycle_grid_first_cycle_per_place():
    """창 05:00~15:00, 1시간 주기에 각 장소의 벽시계 09:30 에 붙으면 09:00 격자에 선다."""
    for tz in (SEOUL, NY, BERLIN, LORD_HOWE):
        inst = make_controller(tz)
        e = _entry('05:00', '15:00')
        now = at(tz, '2026-06-01 09:30').timestamp()
        assert wall(inst._next_cycle_start(e, now, 3600.0), tz) == '2026-06-01 09:00'


# ---------------------------------------------------------------------------
# E. 재시작 복원 — 저장 시각이 지금보다 미래일 때
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_runtime_db(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from aot.databases.models import FunctionRuntimeState
    uri = f'sqlite:///{tmp_path / "rt.db"}'
    engine = create_engine(uri)
    FunctionRuntimeState.__table__.create(bind=engine)
    engine.dispose()
    monkeypatch.setattr(seq_mod, 'AOT_DB_PATH', uri)
    return uri


def _restore(monkeypatch, saved_ts, now_ts):
    inst = make_controller(period=3600.0)
    inst.active_weekday = None
    inst.build_cycle_schedule = MagicMock()
    inst._resync_after_resume = MagicMock()
    inst.cycle_start_time = saved_ts
    inst.active_actions = {'a'}
    inst._save_runtime_state()
    fresh = make_controller(period=3600.0)
    fresh.build_cycle_schedule = MagicMock()
    fresh._resync_after_resume = MagicMock()
    monkeypatch.setattr(seq_mod.time, 'time', lambda: now_ts)
    fresh._load_runtime_state()
    return fresh


def test_restore_within_period(temp_runtime_db, monkeypatch):
    got = _restore(monkeypatch, 1_800_000_000.0, 1_800_000_000.0 + 600)
    assert got.cycle_start_time == 1_800_000_000.0
    assert got.active_actions == {'a'}


def test_restore_stale_cycle_is_dropped(temp_runtime_db, monkeypatch):
    got = _restore(monkeypatch, 1_800_000_000.0, 1_800_000_000.0 + 3600)
    assert got.cycle_start_time is None
    assert got._had_persisted_cycle is True


def test_restore_ignores_cycle_saved_in_the_future(temp_runtime_db, monkeypatch):
    """시계가 뒤로 간 부팅(예: 시계 장치 없는 보드가 마지막 저장 시각으로 올라옴)에서는
    저장된 사이클이 '미래' 가 된다. elapsed 가 음수로 복원되면 그 사이클은 영영 안 끝난다."""
    got = _restore(monkeypatch, 1_800_000_000.0, 1_800_000_000.0 - 7200)
    assert got.cycle_start_time is None
    assert got.active_actions == set()


# ---------------------------------------------------------------------------
# H. 상태 로그의 현지 시각
# ---------------------------------------------------------------------------

def test_status_log_clock_is_labeled(monkeypatch):
    monkeypatch.setattr(seq_mod, 'utc_now', lambda: at(NY, '2026-03-08 03:30'))
    label = seq_mod.SequenceTriggerController._local_clock_label(NY)
    assert '2026-03-08 03:30' in label and 'America/New_York' in label and 'UTC-04:00' in label


def test_status_log_clock_falls_back_to_utc_for_unknown_zone(monkeypatch):
    monkeypatch.setattr(seq_mod, 'utc_now', lambda: dt.datetime(2026, 6, 1, 12, 0, tzinfo=UTC))
    assert '12:00' in seq_mod.SequenceTriggerController._local_clock_label('Nowhere/Land')
