# coding=utf-8
"""Function 시간 점검 S3 — 조건문(conditional_conditional)의 시간 처리.

고친 것:
  H  발화 메시지 시각이 tz 없는 fromtimestamp 였다 → 장소 시계 + 라벨
  D  주기 0·음수·빈 값이면 `timer_period += period` 가 제자리/실패 → 오류 로그 후 실행 안 함,
     놓친 주기 따라잡기는 반복문 대신 산수로
  G  시계가 뒤로 밀리면(NTP 보정) 다음 실행·불응기가 그만큼 멈춤 → 되돌림
  max_age  0/빈 값이면 InfluxDB 질의가 전체 이력을 훑어 오래된 값이 현재 값으로 돌아옴
           과거 평균 창이 비면 ZeroDivisionError
  저장  폼이 주기 0 이하·빈 값을 그대로 저장

DB·데몬·InfluxDB 를 쓰지 않는다(스텁). 시간대 3곳(Asia/Seoul, America/New_York DST,
Australia/Lord_Howe 30분 DST).
"""
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import pytz

from aot.controllers import controller_conditional as cc
from aot.controllers.base_conditional import AbstractConditional
from aot.controllers.controller_conditional import ConditionalController
from aot.utils import actions as actions_module

UID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


# ---------------------------------------------------------------------------
# 컨트롤러 만들기
# ---------------------------------------------------------------------------

def _controller(period=60, start_offset=10, timer_period=None, activated=True):
    ctrl = ConditionalController.__new__(ConditionalController)
    ctrl.pause_loop = False
    ctrl.verify_pause_loop = True
    ctrl.is_activated = activated
    ctrl.period = period
    ctrl.start_offset = start_offset
    ctrl.timer_period = timer_period
    ctrl.unique_id = UID
    ctrl.logger = Mock()
    ctrl.message_include_code = False
    ctrl.conditional_run = Mock(action_fired=False)
    ctrl.check_conditionals = Mock()
    ctrl.attempt_execute = lambda fn: fn()
    return ctrl


@pytest.fixture
def no_signal():
    with patch.object(cc, 'conditional_fired'), \
            patch.object(cc, 'db_retrieve_table_daemon'):
        yield


# ---------------------------------------------------------------------------
# D — 주기 따라잡기
# ---------------------------------------------------------------------------

class TestPeriodCatchUp:
    def test_runs_once_and_stays_on_the_grid(self, no_signal):
        now = 1_800_000_000.0
        ctrl = _controller(period=60, timer_period=now - 1000)
        with patch.object(cc.time, 'time', return_value=now):
            ctrl.loop()
        assert ctrl.check_conditionals.call_count == 1
        # 격자 유지: 원래 타이머 + n*60 이고 지금보다 미래
        assert ctrl.timer_period > now
        assert ctrl.timer_period - (now - 1000) == pytest.approx(
            round((ctrl.timer_period - (now - 1000)) / 60) * 60)
        assert ctrl.timer_period - now <= 60

    def test_tiny_period_after_long_gap_does_not_hang(self, no_signal):
        """시계가 며칠 앞서 뛰어도(또는 주기가 아주 작아도) 반복문 때문에 멈추지 않는다."""
        now = 1_800_000_000.0
        ctrl = _controller(period=0.001, timer_period=now - 86400 * 3)
        t0 = time.monotonic()
        with patch.object(cc.time, 'time', return_value=now):
            ctrl.loop()
        assert time.monotonic() - t0 < 1.0
        assert ctrl.timer_period > now

    def test_not_due_does_not_run(self, no_signal):
        now = 1_800_000_000.0
        ctrl = _controller(period=60, timer_period=now + 30)
        with patch.object(cc.time, 'time', return_value=now):
            ctrl.loop()
        ctrl.check_conditionals.assert_not_called()
        assert ctrl.timer_period == now + 30


# ---------------------------------------------------------------------------
# G — 시계가 뒤로 밀림
# ---------------------------------------------------------------------------

class TestClockStepBack:
    def test_rebases_when_clock_went_back_hours(self, no_signal):
        now = 1_800_000_000.0
        # 시계가 3시간 뒤로 밀려 다음 실행이 3시간 뒤가 됐다
        ctrl = _controller(period=60, timer_period=now + 3 * 3600)
        with patch.object(cc.time, 'time', return_value=now):
            ctrl.loop()
        assert ctrl.timer_period == now + 60
        ctrl.logger.warning.assert_called()

    def test_first_run_start_offset_is_not_mistaken_for_step_back(self, no_signal):
        now = 1_800_000_000.0
        # 주기 60초, 시작 지연 300초 — 첫 실행까지 300초 남은 것은 정상
        ctrl = _controller(period=60, start_offset=300, timer_period=now + 300)
        with patch.object(cc.time, 'time', return_value=now):
            ctrl.loop()
        assert ctrl.timer_period == now + 300
        ctrl.logger.warning.assert_not_called()


# ---------------------------------------------------------------------------
# D — 주기 설정 값 검증 (initialize_variables)
# ---------------------------------------------------------------------------

def _init(tmp_path, monkeypatch, period, start_offset=10):
    monkeypatch.setattr(cc, 'PATH_PYTHON_CODE_USER', str(tmp_path))
    (tmp_path / f'conditional_{UID}.py').write_text(
        "class ConditionalRun:\n"
        "    def __init__(self, logger, uid, message):\n"
        "        self.action_fired = False\n")
    row = SimpleNamespace(
        is_activated=True, conditional_statement='', conditional_import='',
        conditional_initialize='', conditional_status='', period=period,
        start_offset=start_offset, pyro_timeout=30, log_level_debug=False,
        use_pylint=False, message_include_code=False)
    misc = SimpleNamespace(sample_rate_controller_conditional=0.25)

    def _db(model, *a, **k):
        return misc if model is cc.Misc else row

    monkeypatch.setattr(cc, 'db_retrieve_table_daemon', _db)
    ctrl = ConditionalController.__new__(ConditionalController)
    ctrl.unique_id = UID
    ctrl.logger = logging.getLogger('s3test')
    ctrl.logger.error = Mock()
    ctrl.ready = Mock()
    ctrl.initialize_variables()
    return ctrl


class TestPeriodValidation:
    @pytest.mark.parametrize('bad', [0, 0.0, -5, None, '', 'abc', float('nan'), float('inf')])
    def test_bad_period_logs_and_does_not_schedule(self, tmp_path, monkeypatch, bad):
        ctrl = _init(tmp_path, monkeypatch, period=bad)
        assert ctrl.timer_period is None
        assert ctrl.period is None
        ctrl.logger.error.assert_called()

    def test_bad_period_loop_is_inert(self, tmp_path, monkeypatch):
        ctrl = _init(tmp_path, monkeypatch, period=0)
        ctrl.pause_loop = False
        ctrl.check_conditionals = Mock()
        ctrl.loop()  # 무한 루프도 예외도 없어야 한다
        ctrl.check_conditionals.assert_not_called()

    def test_good_period_schedules_after_start_offset(self, tmp_path, monkeypatch):
        before = time.time()
        ctrl = _init(tmp_path, monkeypatch, period=60, start_offset=10)
        assert ctrl.period == 60.0
        assert before + 10 <= ctrl.timer_period <= time.time() + 10

    @pytest.mark.parametrize('bad_offset', [None, -3, 'x'])
    def test_bad_start_offset_falls_back_to_zero(self, tmp_path, monkeypatch, bad_offset):
        ctrl = _init(tmp_path, monkeypatch, period=60, start_offset=bad_offset)
        assert ctrl.start_offset == 0.0
        assert ctrl.timer_period is not None


# ---------------------------------------------------------------------------
# H — 메시지 시각
# ---------------------------------------------------------------------------

# (장소 시간대, 고정 UTC 순간, 기대 머리글)
_CASES = [
    ('Asia/Seoul', datetime(2026, 11, 11, 15, 30, tzinfo=timezone.utc),
     '2026-11-12 00:30:00 (Asia/Seoul, UTC+09:00)'),
    # 미국 봄 DST 당일: 07:00Z 에 02:00 → 03:00
    ('America/New_York', datetime(2026, 3, 8, 6, 59, tzinfo=timezone.utc),
     '2026-03-08 01:59:00 (America/New_York, UTC-05:00)'),
    ('America/New_York', datetime(2026, 3, 8, 7, 1, tzinfo=timezone.utc),
     '2026-03-08 03:01:00 (America/New_York, UTC-04:00)'),
    # 가을: 같은 01:30 이 두 번 — 오프셋 라벨로 구별된다
    ('America/New_York', datetime(2026, 11, 1, 5, 30, tzinfo=timezone.utc),
     '2026-11-01 01:30:00 (America/New_York, UTC-04:00)'),
    ('America/New_York', datetime(2026, 11, 1, 6, 30, tzinfo=timezone.utc),
     '2026-11-01 01:30:00 (America/New_York, UTC-05:00)'),
    # 30분 DST (남반구 가을 종료: 15:00Z 에 02:00 → 01:30, 01:45 가 두 번)
    ('Australia/Lord_Howe', datetime(2026, 4, 4, 14, 45, tzinfo=timezone.utc),
     '2026-04-05 01:45:00 (Australia/Lord_Howe, UTC+11:00)'),
    ('Australia/Lord_Howe', datetime(2026, 4, 4, 15, 15, tzinfo=timezone.utc),
     '2026-04-05 01:45:00 (Australia/Lord_Howe, UTC+10:30)'),
]


class TestMessageTimestamp:
    @pytest.mark.parametrize('tz_name, instant, expected', _CASES)
    def test_message_header_is_labeled_place_clock(self, tz_name, instant, expected):
        ctrl = _controller()
        ctrl.time_conditional = instant.timestamp()
        cond_row = SimpleNamespace(name='N', conditional_statement='x')
        with patch.object(cc, 'db_retrieve_table_daemon', return_value=cond_row), \
                patch.object(cc, 'tz_of', return_value=pytz.timezone(tz_name)), \
                patch.object(cc, 'utc_now', return_value=instant):
            ctrl.conditional_run = SimpleNamespace(
                action_fired=False, message='', conditional_code_run=lambda: None)
            ctrl.check_conditionals = ConditionalController.check_conditionals.__get__(ctrl)
            ctrl.check_conditionals()
        assert ctrl.conditional_run.message.startswith(expected + '\n[Name: N]')

    def test_container_clock_does_not_leak_into_message(self, monkeypatch):
        """컨테이너 OS 시간대가 무엇이든 메시지는 같다 (예전엔 fromtimestamp)."""
        instant = datetime(2026, 11, 11, 15, 30, tzinfo=timezone.utc)
        out = []
        for os_tz in ('UTC', 'Pacific/Auckland'):
            monkeypatch.setenv('TZ', os_tz)
            time.tzset()
            ctrl = _controller()
            ctrl.time_conditional = instant.timestamp()
            with patch.object(cc, 'db_retrieve_table_daemon',
                              return_value=SimpleNamespace(name='N', conditional_statement='')), \
                    patch.object(cc, 'tz_of', return_value=pytz.timezone('Asia/Seoul')), \
                    patch.object(cc, 'utc_now', return_value=instant):
                ctrl.conditional_run = SimpleNamespace(
                    action_fired=False, message='', conditional_code_run=lambda: None)
                ConditionalController.check_conditionals(ctrl)
            out.append(ctrl.conditional_run.message)
        monkeypatch.delenv('TZ')
        time.tzset()
        assert out[0] == out[1]

    def test_tz_resolution_failure_still_runs_user_code(self):
        ctrl = _controller()
        ctrl.time_conditional = time.time()
        ran = []
        ctrl.conditional_run = SimpleNamespace(
            action_fired=False, message='', conditional_code_run=lambda: ran.append(1))
        with patch.object(cc, 'db_retrieve_table_daemon',
                          return_value=SimpleNamespace(name='N', conditional_statement='')), \
                patch.object(cc, 'tz_of', side_effect=RuntimeError('boom')):
            ConditionalController.check_conditionals(ctrl)
        assert ran == [1]
        assert 'UTC' in ctrl.conditional_run.message


# ---------------------------------------------------------------------------
# G — 불응기와 시계 역행
# ---------------------------------------------------------------------------

class _Row(SimpleNamespace):
    pass


def _refractory_cond(last_fired, refractory=300):
    row = _Row(unique_id='cccccccc-0000-0000-0000-000000000000',
               refractory_period=refractory,
               custom_options=json.dumps(
                   {} if last_fired is None
                   else {'__aot_refractory_last_fired_ts__': last_fired}))

    class _Session:
        def query(self, _m): return self
        def filter(self, *a, **k): return self
        def first(self): return row
        def commit(self): pass

    from contextlib import contextmanager

    @contextmanager
    def _scope(*a, **k):
        yield _Session()

    cond = AbstractConditional(logger=Mock(), function_id=row.unique_id, message='')
    cond.control = Mock()
    cond.control.trigger_all_actions.return_value = ''
    return cond, row, _scope


class TestRefractoryClock:
    def _run(self, last_fired, now, monkeypatch, refractory=300):
        cond, row, scope = _refractory_cond(last_fired, refractory)
        monkeypatch.setattr(
            'aot.controllers.base_conditional.db_retrieve_table_daemon',
            lambda *a, **k: row)
        monkeypatch.setattr('aot.controllers.base_conditional.session_scope', scope)
        monkeypatch.setattr('aot.controllers.base_conditional.time.time', lambda: now)
        cond.run_all_actions()
        return cond, row

    def test_inside_window_is_suppressed(self, monkeypatch):
        cond, _ = self._run(last_fired=1_000_000.0, now=1_000_100.0, monkeypatch=monkeypatch)
        assert cond.action_fired is False

    def test_after_window_fires(self, monkeypatch):
        cond, _ = self._run(last_fired=1_000_000.0, now=1_000_301.0, monkeypatch=monkeypatch)
        assert cond.action_fired is True

    def test_last_fired_in_future_means_clock_went_back_so_fire(self, monkeypatch):
        cond, row = self._run(last_fired=1_000_000.0 + 3 * 3600, now=1_000_000.0,
                              monkeypatch=monkeypatch)
        assert cond.action_fired is True
        # 새 발동 시각이 기록되어 이후 불응기는 정상 계산된다
        assert json.loads(row.custom_options)['__aot_refractory_last_fired_ts__'] == 1_000_000.0

    @pytest.mark.parametrize('junk', ['abc', True, [1], {'a': 1}])
    def test_junk_last_fired_does_not_crash(self, junk, monkeypatch):
        cond, _ = self._run(last_fired=junk, now=1_000_000.0, monkeypatch=monkeypatch)
        assert cond.action_fired is True


# ---------------------------------------------------------------------------
# max_age — 데몬 쪽 조건값
# ---------------------------------------------------------------------------

def _stub_measurement_db(monkeypatch, condition):
    class _Query:
        def filter(self, *a, **k): return self
        def first(self): return condition

    def _db(model, *a, **k):
        if model is actions_module.ConditionalConditions and not k:
            return _Query()
        return SimpleNamespace(conversion_id=None)

    monkeypatch.setattr(actions_module, 'db_retrieve_table_daemon', _db)
    monkeypatch.setattr(actions_module, 'return_measurement_info',
                        lambda *a, **k: (0, 'C', 'temperature'))


def _meas(**kw):
    base = dict(unique_id='dddddddd-0000-0000-0000-000000000000',
                conditional_id='aaaaaaaa-0000-0000-0000-000000000000',
                condition_type='measurement', measurement='dev,meas', max_age=120)
    base.update(kw)
    return SimpleNamespace(**base)


class TestMaxAge:
    @pytest.mark.parametrize('ctype', ['measurement', 'measurement_and_ts',
                                       'measurement_past_average',
                                       'measurement_past_sum', 'measurement_dict'])
    @pytest.mark.parametrize('bad', [0, None, -1, ''])
    def test_bad_max_age_never_queries_unbounded_history(self, monkeypatch, ctype, bad):
        _stub_measurement_db(monkeypatch, _meas(condition_type=ctype, max_age=bad))
        spies = {n: Mock(return_value=[None, None]) for n in
                 ('get_last_measurement', 'get_past_measurements')}
        for n, m in spies.items():
            monkeypatch.setattr(actions_module, n, m)
        fn = (actions_module.get_condition_value_dict if ctype == 'measurement_dict'
              else actions_module.get_condition_value)
        result = fn('dddddddd-0000-0000-0000-000000000000')
        spies['get_last_measurement'].assert_not_called()
        spies['get_past_measurements'].assert_not_called()
        if ctype == 'measurement_and_ts':
            assert result == {'time': None, 'value': None}
        else:
            assert result is None

    def test_max_age_is_passed_as_positive_seconds(self, monkeypatch):
        _stub_measurement_db(monkeypatch, _meas(max_age=360))
        spy = Mock(return_value=[1_800_000_000.0, 21.5])
        monkeypatch.setattr(actions_module, 'get_last_measurement', spy)
        assert actions_module.get_condition_value('x') == 21.5
        assert spy.call_args.kwargs['max_age'] == 360

    def test_fractional_max_age_rounds_up_to_one_second(self, monkeypatch):
        _stub_measurement_db(monkeypatch, _meas(max_age=0.4))
        spy = Mock(return_value=[1.0, 2.0])
        monkeypatch.setattr(actions_module, 'get_last_measurement', spy)
        actions_module.get_condition_value('x')
        assert spy.call_args.kwargs['max_age'] == 1


class TestPastWindows:
    def test_average_of_empty_window_is_none_not_zero_division(self, monkeypatch):
        _stub_measurement_db(monkeypatch, _meas(condition_type='measurement_past_average'))
        monkeypatch.setattr(actions_module, 'get_past_measurements', lambda *a, **k: [])
        assert actions_module.get_condition_value('x') is None

    def test_average_when_query_failed_is_none(self, monkeypatch):
        _stub_measurement_db(monkeypatch, _meas(condition_type='measurement_past_average'))
        monkeypatch.setattr(actions_module, 'get_past_measurements', lambda *a, **k: None)
        assert actions_module.get_condition_value('x') is None

    def test_average_normal(self, monkeypatch):
        _stub_measurement_db(monkeypatch, _meas(condition_type='measurement_past_average'))
        monkeypatch.setattr(actions_module, 'get_past_measurements',
                            lambda *a, **k: [(1.0, 10), (2.0, 20)])
        assert actions_module.get_condition_value('x') == 15

    def test_sum_when_query_failed_is_none_but_empty_window_stays_zero(self, monkeypatch):
        _stub_measurement_db(monkeypatch, _meas(condition_type='measurement_past_sum'))
        monkeypatch.setattr(actions_module, 'get_past_measurements', lambda *a, **k: None)
        assert actions_module.get_condition_value('x') is None
        monkeypatch.setattr(actions_module, 'get_past_measurements', lambda *a, **k: [])
        assert actions_module.get_condition_value('x') == 0  # 기존 동작 유지


# ---------------------------------------------------------------------------
# sun_event_countdown / sun_state — 시간대·DST (실제 태양 계산, 좌표만 고정)
# ---------------------------------------------------------------------------

class TestSunConditionsAcrossZones:
    def _setup(self, monkeypatch, lat, lon, now):
        from aot.utils import solar
        solar.clear_cache()
        monkeypatch.setattr(solar, '_resolve_location', lambda *a, **k: (lat, lon))
        monkeypatch.setattr(solar, 'utc_now', lambda: now)
        monkeypatch.setattr('aot.utils.timekit.utc_now', lambda: now)
        cond = SimpleNamespace(
            unique_id='dddddddd-0000-0000-0000-000000000000',
            conditional_id='aaaaaaaa-0000-0000-0000-000000000000',
            condition_type='sun_event_countdown', sun_event='sunset',
            sun_offset_start_minutes=0, sun_offset_end_minutes=0)

        class _Query:
            def filter(self, *a, **k): return self
            def first(self): return cond
        monkeypatch.setattr(actions_module, 'db_retrieve_table_daemon',
                            lambda *a, **k: _Query())
        return cond

    @pytest.mark.parametrize('lat, lon, now', [
        (37.5, 127.0, datetime(2026, 6, 21, 3, 0, tzinfo=timezone.utc)),    # 서울
        (40.7, -74.0, datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)),    # 뉴욕 DST 당일
        (40.7, -74.0, datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)),   # 뉴욕 가을 DST 당일
        (-31.55, 159.08, datetime(2026, 4, 4, 18, 0, tzinfo=timezone.utc)), # 로드하우 30분 DST
    ])
    def test_countdown_is_positive_and_within_a_day(self, monkeypatch, lat, lon, now):
        self._setup(monkeypatch, lat, lon, now)
        left = actions_module.get_condition_value('x')
        assert left is not None
        assert 0 < left <= 24 * 3600 + 3600

    def test_countdown_matches_event_minus_now_on_dst_day(self, monkeypatch):
        now = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)   # 뉴욕 08:00 EDT
        self._setup(monkeypatch, 40.7, -74.0, now)
        from aot.utils.solar import next_sun_event
        event = next_sun_event('sunset', now=now, latitude=40.7, longitude=-74.0)
        # 뉴욕 3월 8일 일몰은 18:00 EDT(=22:00Z) 전후 — 시각 자체가 맞아야 한다
        assert event.astimezone(pytz.timezone('America/New_York')).hour in (17, 18)
        assert actions_module.get_condition_value('x') == pytest.approx(
            (event - now).total_seconds(), abs=2)

    def test_polar_no_event_gives_none_not_crash(self, monkeypatch):
        # 북극권 한여름: 일몰이 없다
        now = datetime(2026, 6, 21, 12, 0, tzinfo=timezone.utc)
        self._setup(monkeypatch, 78.2, 15.6, now)
        actions_module.get_condition_value('x')   # 예외 없이 돌아오면 된다

    def test_sun_state_each_zone(self, monkeypatch):
        from aot.utils.solar import is_daytime
        # 서울 한낮(03:00Z=12:00 KST)은 주간, 서울 자정 무렵(15:00Z=00:00 KST)은 야간
        assert is_daytime(at=datetime(2026, 6, 21, 3, 0, tzinfo=timezone.utc),
                          latitude=37.5, longitude=127.0) is True
        assert is_daytime(at=datetime(2026, 6, 21, 15, 0, tzinfo=timezone.utc),
                          latitude=37.5, longitude=127.0) is False


# ---------------------------------------------------------------------------
# 저장 — 주기 입력 검사
# ---------------------------------------------------------------------------

class TestTimingFormCheck:
    def test_valid(self):
        from decimal import Decimal
        from aot.aot_flask.utils.utils_conditional import check_conditional_timing
        assert check_conditional_timing(Decimal('60'), Decimal('10'), Decimal('0')) == []
        assert check_conditional_timing(0.5, 0, None) == []
        assert check_conditional_timing('60', '0', '') == []

    @pytest.mark.parametrize('period', [0, -1, None, '', 'abc', float('nan')])
    def test_bad_period(self, period):
        from aot.aot_flask.utils.utils_conditional import check_conditional_timing
        errs = check_conditional_timing(period, 10)
        assert any('주기' in e for e in errs)

    @pytest.mark.parametrize('offset', [-1, None, 'x'])
    def test_bad_start_offset(self, offset):
        from aot.aot_flask.utils.utils_conditional import check_conditional_timing
        assert any('시작 지연' in e for e in check_conditional_timing(60, offset))

    def test_bad_refractory(self):
        from aot.aot_flask.utils.utils_conditional import check_conditional_timing
        assert any('불응기' in e for e in check_conditional_timing(60, 10, -5))
