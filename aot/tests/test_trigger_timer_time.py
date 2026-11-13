# coding=utf-8
"""시간 기반 트리거(`controller_trigger.py`)의 시간 처리 — Function 시간 점검 S1.

본 것:
- 다음 발화 시각이 장소 시계·DST(없는 시각, 두 번 있는 시각, 30분 DST)에서 한 번만 온다.
- 매일 구간 트리거의 주기 격자가 DST 가 바뀌는 날에도 설정 시작 시각에 붙는다
  (예전: `다음 시작 - 86400` 기준이라 한 시간 어긋남).
- 시각·주기를 못 읽으면 조용히 멈추거나(None) 끝없이 돌지(주기 0) 않는다.
- 발화하면 액션이 실제로 실행된다 — 측정 장치 칸이 빈 시간 트리거가 액션을
  하나도 실행하지 않던 결함. PWM 메서드는 loop() 가 이미 실행하므로 두 번 하지 않는다.
- 발화 메시지 시각에 어느 시계인지가 붙는다.
- 폼의 주기 칸(문자열)을 숫자로 읽는다 — '주기' 트리거 저장이 TypeError 로 막히던 결함.
"""
import datetime as dt
import logging
from types import SimpleNamespace
from unittest import mock

import pytest

import aot.controllers.controller_trigger as ct
import aot.utils.system_pi as sp
import aot.utils.timekit as tk
from aot.databases.models import Trigger

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


@pytest.fixture
def clock(monkeypatch):
    """timekit·system_pi 의 '지금' 을 고정한다."""
    state = {}

    def set_now(value):
        state['now'] = value
        monkeypatch.setattr(tk, 'utc_now', lambda: state['now'])
        monkeypatch.setattr(sp, 'utc_now', lambda: state['now'])
        monkeypatch.setattr(ct, 'utc_now', lambda: state['now'])
        monkeypatch.setattr(ct.time, 'time', lambda: state['now'].timestamp())
    return set_now


# ---------------------------------------------------------------------------
# 다음 발화 시각 / 가장 최근 시각
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('tz,now_wall,hm,expected', [
    (SEOUL, '2026-06-01 07:00', '08:00', '2026-06-01 08:00'),
    (SEOUL, '2026-06-01 08:00', '08:00', '2026-06-02 08:00'),   # 지금 그 시각이면 내일
    (SEOUL, '2026-06-01 23:59', '00:00', '2026-06-02 00:00'),
    # 봄: 02:30 이 없는 날 → 표준시로 읽어 03:30 에 한 번
    (NY, '2026-03-08 01:00', '02:30', '2026-03-08 03:30'),
    (NY, '2026-03-08 03:31', '02:30', '2026-03-09 02:30'),
    (BERLIN, '2026-03-29 01:00', '02:30', '2026-03-29 03:30'),
    # 30분 DST: 02:00→02:30 으로 건너뛰는 날의 02:15
    (LORD_HOWE, '2026-10-04 01:00', '02:15', '2026-10-04 02:45'),
])
def test_next_time_in_place_clock(tz, now_wall, hm, expected):
    e = sp.epoch_of_next_time(hm + ':00', tz=tz, now=at(tz, now_wall))
    assert wall(e, tz) == expected


def test_next_time_fall_back_fires_once():
    """가을 01:30 은 두 번 오지만 발화는 한 번(두 번째)."""
    first = sp.epoch_of_next_time('01:30:00', tz=NY, now=at(NY, '2026-11-01 00:30'))
    assert dt.datetime.fromtimestamp(first, UTC) == dt.datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    after = sp.epoch_of_next_time(
        '01:30:00', tz=NY, now=dt.datetime.fromtimestamp(first + 1, UTC))
    assert wall(after, NY) == '2026-11-02 01:30'


def test_next_time_uses_clock_not_os(clock):
    """now 를 안 넘기면 timekit 의 지금을 쓴다(컨테이너 OS 시계 아님)."""
    clock(at(SEOUL, '2026-06-01 07:00'))
    assert wall(sp.epoch_of_next_time('08:00:00', tz=SEOUL), SEOUL) == '2026-06-01 08:00'


@pytest.mark.parametrize('bad', ['', 'None', '25:00', 'ab:cd'])
def test_next_time_unreadable_is_none(bad):
    assert sp.epoch_of_next_time(f'{bad}:00', tz=SEOUL, now=at(SEOUL, '2026-06-01 07:00')) is None


@pytest.mark.parametrize('tz,now_wall,hm,expected', [
    (SEOUL, '2026-06-01 10:00', '08:00', '2026-06-01 08:00'),
    (SEOUL, '2026-06-01 07:00', '08:00', '2026-05-31 08:00'),
    (SEOUL, '2026-06-01 08:00', '08:00', '2026-06-01 08:00'),   # 지금 이하
    # DST 당일: 예전 `다음 - 86400` 은 각각 23:00·01:00 / 21:00 으로 어긋났다
    (NY, '2026-03-08 10:00', '00:00', '2026-03-08 00:00'),
    (NY, '2026-11-01 10:00', '00:00', '2026-11-01 00:00'),
    (NY, '2026-03-08 03:30', '22:00', '2026-03-07 22:00'),
    (NY, '2026-11-01 05:00', '22:00', '2026-10-31 22:00'),
    (BERLIN, '2026-10-25 12:00', '00:00', '2026-10-25 00:00'),
])
def test_last_time_is_local_start(tz, now_wall, hm, expected):
    e = sp.epoch_of_last_time(hm + ':00', tz=tz, now=at(tz, now_wall))
    assert wall(e, tz) == expected


# ---------------------------------------------------------------------------
# 트리거 컨트롤러 — 초기화·격자·실패 처리
# ---------------------------------------------------------------------------

def _controller(tz=SEOUL, **trig):
    c = object.__new__(ct.TriggerController)
    c.unique_id = 't1'
    c.trigger_name = 'probe'
    c.log_level_debug = False
    c.logger = logging.getLogger('test_trigger_timer_time')
    c.device_tz = tz
    c._facility_tz = tk.tz_of(tz)
    c.trigger = SimpleNamespace(unique_id='t1', **trig)
    return c


def _init(c, trigger, tz):
    """initialize_variables 를 DB 없이 돌린다."""
    def fake_db(table, unique_id=None, entry=None, **kw):
        if table is Trigger:
            return trigger
        return SimpleNamespace(sample_rate_controller_conditional=1, hourly_max=2)
    with mock.patch.object(ct, 'db_retrieve_table_daemon', side_effect=fake_db), \
            mock.patch.object(ct, 'tz_of', return_value=tk.tz_of(tz)), \
            mock.patch.object(c, 'set_log_level_debug', create=True), \
            mock.patch.object(c, 'ready', create=True):
        c.initialize_variables()


def _trigger_row(trigger_type, **kw):
    base = dict(unique_id='t1', name='probe', trigger_type=trigger_type,
                is_activated=True, log_level_debug=False, measurement='',
                timer_start_time='08:00', timer_end_time='18:00',
                period=3600.0, timer_start_offset=0)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize('tz,now_wall,start,end,period,expected', [
    (SEOUL, '2026-06-01 09:10', '08:00', '18:00', 1800, '2026-06-01 09:30'),
    (SEOUL, '2026-06-01 07:00', '08:00', '18:00', 1800, '2026-06-01 08:00'),  # 구간 밖 → 시작
    # DST 당일 자정 시작 2시간 격자: 시작 + 실제 경과 2·4시간.
    # 봄은 벽시계 03:00(예전 01:00), 가을은 03:00 EST(예전 02:00).
    (NY, '2026-03-08 00:30', '00:00', '23:00', 7200, '2026-03-08 03:00'),
    (NY, '2026-11-01 01:30', '00:00', '23:00', 7200, '2026-11-01 03:00'),
    # 자정을 넘는 구간
    (SEOUL, '2026-06-02 01:10', '22:00', '06:00', 3600, '2026-06-02 02:00'),
])
def test_daily_span_grid_anchored_to_local_start(clock, tz, now_wall, start, end, period, expected):
    """격자는 '그날 시작 시각 + n×주기' (경과 시간 기준)."""
    now = at(tz, now_wall)
    clock(now)
    c = _controller(tz)
    c.timer_start_time, c.timer_end_time, c.period = start, end, float(period)
    c.set_next_daily_time_span_run(now.timestamp())
    assert wall(c.timer_period, tz) == expected


def test_daily_span_grid_counts_elapsed_seconds_across_dst(clock):
    """NY 봄 DST 날 00:00 시작 2시간 격자: 실제 경과 2·4시간 = 벽시계 03:00·05:00."""
    tz = NY
    clock(at(tz, '2026-03-08 03:10'))
    c = _controller(tz)
    c.timer_start_time, c.timer_end_time, c.period = '00:00', '23:00', 7200.0
    c.set_next_daily_time_span_run(at(tz, '2026-03-08 03:10').timestamp())
    start = at(tz, '2026-03-08 00:00').timestamp()
    assert (c.timer_period - start) % 7200 == 0
    assert wall(c.timer_period, tz) == '2026-03-08 05:00'


@pytest.mark.parametrize('ttype', ['trigger_timer_daily_time_span', 'trigger_timer_duration'])
@pytest.mark.parametrize('period', [0, -5, None, ''])
def test_bad_period_does_not_hang_or_fire(clock, caplog, ttype, period):
    """주기 0 이면 예전엔 `+= period` while 이 끝나지 않았다."""
    clock(at(SEOUL, '2026-06-01 09:10'))
    c = _controller(SEOUL)
    with caplog.at_level(logging.ERROR):
        _init(c, _trigger_row(ttype, period=period), SEOUL)
    assert c.timer_period is None
    assert '주기' in caplog.text


def test_unreadable_start_time_is_logged_not_silent(clock, caplog):
    clock(at(SEOUL, '2026-06-01 07:00'))
    c = _controller(SEOUL)
    with caplog.at_level(logging.ERROR):
        _init(c, _trigger_row('trigger_timer_daily_time_point', timer_start_time=''), SEOUL)
    assert c.timer_period is None
    assert '발화하지 않습니다' in caplog.text


def test_daily_point_init_and_after_fire(clock):
    tz = NY
    clock(at(tz, '2026-03-07 23:00'))
    c = _controller(tz)
    _init(c, _trigger_row('trigger_timer_daily_time_point', timer_start_time='02:30'), tz)
    assert wall(c.timer_period, tz) == '2026-03-08 03:30'
    # 발화 직후 다음 계산
    clock(dt.datetime.fromtimestamp(c.timer_period + 1, UTC))
    assert wall(c._next_wall_epoch(c.timer_start_time), tz) == '2026-03-09 02:30'


def test_duration_string_period_from_db(clock):
    """SQLite 에 문자열로 남은 주기('60')도 숫자로 읽는다."""
    now = at(SEOUL, '2026-06-01 09:00')
    clock(now)
    c = _controller(SEOUL)
    _init(c, _trigger_row('trigger_timer_duration', period='60', timer_start_offset=30), SEOUL)
    assert c.period == 60.0
    assert c.timer_period == now.timestamp() + 30


# ---------------------------------------------------------------------------
# 발화 → 액션
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('ttype', [
    'trigger_timer_daily_time_point', 'trigger_timer_daily_time_span',
    'trigger_timer_duration', 'trigger_sunrise_sunset'])
def test_time_trigger_fire_runs_actions(clock, ttype):
    """측정 장치 칸이 빈(기본값 '') 시간 트리거도 액션을 실행한다."""
    clock(at(SEOUL, '2026-06-01 08:00'))
    c = _controller(SEOUL)
    row = _trigger_row(ttype)
    with mock.patch.object(ct, 'db_retrieve_table_daemon', return_value=row), \
            mock.patch.object(ct, 'parse_action_information', return_value={}), \
            mock.patch.object(ct, 'trigger_controller_actions') as run:
        c.check_triggers()
    assert run.call_count == 1
    message = run.call_args.kwargs['message']
    assert message.startswith('2026-06-01 08:00:00 (Asia/Seoul, UTC+09:00)')


def test_pwm_method_actions_not_run_twice(clock):
    """PWM 메서드는 loop() 가 주기 액션을 이미 실행했다."""
    clock(at(SEOUL, '2026-06-01 08:00'))
    c = _controller(SEOUL)
    with mock.patch.object(ct, 'db_retrieve_table_daemon',
                           return_value=_trigger_row('trigger_run_pwm_method')), \
            mock.patch.object(ct, 'parse_action_information', return_value={}), \
            mock.patch.object(ct, 'trigger_controller_actions') as run:
        c.check_triggers()
    run.assert_not_called()


def test_missing_trigger_row_skips(clock, caplog):
    clock(at(SEOUL, '2026-06-01 08:00'))
    c = _controller(SEOUL)
    with mock.patch.object(ct, 'db_retrieve_table_daemon', return_value=None), \
            mock.patch.object(ct, 'trigger_controller_actions') as run, \
            caplog.at_level(logging.ERROR):
        c.check_triggers()
    run.assert_not_called()


def test_loop_daily_point_fires_once_and_reschedules(clock):
    """loop() 한 바퀴: 시각이 지나면 액션 한 번, 다음 날로 넘어간다."""
    tz = SEOUL
    clock(at(tz, '2026-06-01 07:59'))
    c = _controller(tz)
    _init(c, _trigger_row('trigger_timer_daily_time_point', timer_start_time='08:00'), tz)
    c.pause_loop = False
    c.running = True
    clock(at(tz, '2026-06-01 08:00') + dt.timedelta(seconds=1))
    with mock.patch.object(ct, 'db_retrieve_table_daemon',
                           return_value=_trigger_row('trigger_timer_daily_time_point')), \
            mock.patch.object(ct, 'parse_action_information', return_value={}), \
            mock.patch.object(ct, 'trigger_controller_actions') as run, \
            mock.patch.object(ct, 'trigger_fired'), \
            mock.patch.object(c, 'attempt_execute', side_effect=lambda f: f(), create=True):
        c.loop()
        c.loop()    # 같은 순간 두 번째 바퀴는 발화하지 않는다
    assert run.call_count == 1
    assert wall(c.timer_period, tz) == '2026-06-02 08:00'


# ---------------------------------------------------------------------------
# 폼 — 주기 칸은 문자열
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('raw,expected', [
    ('60', 60.0), (' 1.5 ', 1.5), ('0', 0.0), ('-5', -5.0), (60, 60.0),
    ('', None), ('abc', None), (None, None), (True, None)])
def test_form_number(raw, expected):
    from aot.aot_flask.utils.utils_trigger import _number
    assert _number(raw) == expected
