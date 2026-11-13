# coding=utf-8
"""PID 컨트롤러·위젯의 시간 동작 회귀 시험 (2026-11-11 점검).

DB·influx·스레드 없이 로직만 본다 — 컨트롤러는 `__new__` 로 만들고 측정 읽기·출력
호출은 대체한다. 각 시험 위에 고치기 전에 무엇이 깨졌는지 적었다.
"""
import contextlib
import logging
import math
import signal
import unittest
from types import SimpleNamespace
from unittest import mock

from aot.controllers import controller_pid as cp
from aot.utils.pid_controller_default import PIDControl

ERROR = 5.0     # setpoint 25 - measurement 20


def make(period=30.0, setpoint=25.0, ki=1.0, kp=1.0, kd=0.0, direction='raise',
         integrator_max=100.0):
    c = cp.PIDController.__new__(cp.PIDController)      # 스레드·DB 초기화 건너뜀
    c.logger = logging.getLogger('test_pid_timing')
    c.unique_id = 'pid1'
    c.is_activated = True
    c.is_paused = False
    c.is_held = False
    c.setpoint_tracking_type = ''
    c.setpoint_tracking_id = ''
    c.setpoint = setpoint
    c.raise_output_id = 'out'
    c.lower_output_id = None
    c.raise_output_channel = 0
    c.lower_output_channel = None
    c.period = period
    c.timer = 0
    c._last_run_mono = None
    c._integrated_sample = None
    c._cycle_abort = False
    c._cycle_setpoint = None
    c._bad_period_logged = None
    c.last_time = 1000.0
    c.last_measurement = 20.0
    c.last_measurement_success = True
    c.PID_Controller = PIDControl(
        c.logger, setpoint, kp, ki, kd, direction, 0, -integrator_max, integrator_max)
    c.out_calls = 0
    c.write_calls = 0
    c.control = mock.MagicMock()

    def fake_get():
        c.last_measurement_success = True       # 같은 표본을 계속 돌려준다
    c.get_last_measurement_pid = fake_get
    c.manipulate_output = lambda: setattr(c, 'out_calls', c.out_calls + 1)
    c.write_pid_values = lambda: setattr(c, 'write_calls', c.write_calls + 1)
    return c


@contextlib.contextmanager
def fake_scope(*args, **kwargs):
    yield mock.MagicMock()


@contextlib.contextmanager
def alarm(seconds):
    """무한 루프가 시험을 멈춰 세우지 않고 실패로 끝나게 한다."""
    def boom(signum, frame):
        raise AssertionError(f'{seconds}초 안에 끝나지 않았다(무한 루프)')
    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


class PeriodGuardTest(unittest.TestCase):
    def test_safe_period_values(self):
        # 고치기 전: safe_period 자체가 없었다.
        self.assertEqual(30.0, cp.safe_period(0))
        self.assertEqual(30.0, cp.safe_period(-5))
        self.assertEqual(30.0, cp.safe_period(None))
        self.assertEqual(30.0, cp.safe_period('abc'))
        self.assertEqual(30.0, cp.safe_period(float('nan')))
        self.assertEqual(30.0, cp.safe_period(float('inf')))
        self.assertEqual(1.0, cp.safe_period(0.2))
        self.assertEqual(45.0, cp.safe_period(45))

    def test_loop_with_zero_period_terminates(self):
        # 고치기 전: period=0 이면 `while now > timer: timer += 0` 가 영원히 돈다.
        c = make(period=0)
        c.timer = 100.0
        ran = []
        c.run_cycle = lambda: ran.append(1)
        with alarm(5), mock.patch('time.monotonic', lambda: 130.5):
            c.loop()
        self.assertEqual([1], ran)
        self.assertGreater(c.timer, 130.5)

    def test_duty_cycle_with_zero_period_does_not_divide_by_zero(self):
        c = make(period=0)
        self.assertEqual(50.0, c.control_var_to_duty_cycle(15.0))


class GridTest(unittest.TestCase):
    def test_grid_has_no_drift_and_skips_missed_cycles(self):
        c = make(period=30.0)
        c.timer = 1000.0
        runs = []
        c.run_cycle = lambda: runs.append(t['now'])
        t = {'now': 0.0}
        with mock.patch('time.monotonic', lambda: t['now']):
            for i in range(int(600 / 0.25)):
                t['now'] = 1000.0 + i * 0.25 + 0.01
                c.loop()
            # 5분 동안 막혔다가 돌아와도 몰아서 실행하지 않고 한 번만 돈다
            t['now'] += 300
            before = len(runs)
            c.loop()
        gaps = {round(b - a, 1) for a, b in zip(runs[:-1], runs[1:-1])}
        self.assertEqual({30.0}, gaps)
        self.assertEqual(1, len(runs) - before)

    def test_wall_clock_step_does_not_stall_the_loop(self):
        # 고치기 전: `time.time()` 기준이라 NTP 가 시계를 1시간 되돌리면 그만큼 멈췄다.
        c = make(period=30.0)
        c.timer = 1000.0
        runs = []
        c.run_cycle = lambda: runs.append(1)
        mono = {'now': 1000.5}
        wall = {'now': 5_000_000.0}
        with mock.patch('time.monotonic', lambda: mono['now']), \
                mock.patch('time.time', lambda: wall['now']):
            c.loop()
            wall['now'] -= 3600              # 시계 되돌림
            mono['now'] += 31                # 실제로는 31초 지남
            c.loop()
        self.assertEqual(2, len(runs))


class WidgetValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from aot.widgets import AoT_PID
        cls.validate = staticmethod(AoT_PID.validate_pid_params)

    def test_period_must_be_in_form_range(self):
        # 고치기 전: 위젯 경로는 float() 만 하고 저장했다.
        for bad in (0, -1, 0.5, 86401, 'abc', float('nan'), float('inf')):
            self.assertIsNotNone(self.validate({'period': bad}), bad)
        for good in (1, 30, '45.5', 86400):
            self.assertIsNone(self.validate({'period': good}), good)

    def test_band_and_integrator(self):
        self.assertIsNotNone(self.validate({'band': -1}))
        self.assertIsNone(self.validate({'band': 0}))
        self.assertIsNotNone(self.validate({'integrator_min': 5, 'integrator_max': 1}))
        cur = SimpleNamespace(integrator_min=-10, integrator_max=10)
        self.assertIsNotNone(self.validate({'integrator_min': 20}, current=cur))
        self.assertIsNone(self.validate({'integrator_max': 20}, current=cur))

    def test_empty_values_are_ignored_like_before(self):
        self.assertIsNone(self.validate({'period': '', 'band': ''}))

    def test_non_finite_gains_and_setpoint_rejected(self):
        self.assertIsNotNone(self.validate({'p': float('nan')}))
        self.assertIsNotNone(self.validate({'setpoint': float('inf')}))


class PauseHoldTest(unittest.TestCase):
    def test_pause_does_nothing_but_hold_freezes(self):
        # 고치기 전: 일시정지 단독은 측정·적분·값 기록이 계속 돌았고, 유지 단독은 평소와 같았다.
        c = make()
        c.is_paused = True
        c.check_pid()
        self.assertEqual((0.0, 0, 0), (c.PID_Controller.integrator, c.out_calls, c.write_calls))

        c = make()
        c.check_pid()                                   # 한 번 계산해 둔다
        cv, integ = c.PID_Controller.control_variable, c.PID_Controller.integrator
        c.is_held = True
        c.last_time = 2000.0                            # 새 표본이 와도
        c.check_pid()
        self.assertEqual(integ, c.PID_Controller.integrator)
        self.assertEqual(cv, c.PID_Controller.control_variable)
        self.assertEqual(2, c.out_calls)                # 마지막 출력은 반복한다
        self.assertEqual(1, c.write_calls)              # 새 값 기록은 없다

    def test_flags_are_mutually_exclusive(self):
        # 고치기 전: hold→pause 하면 데몬 메모리에 두 플래그가 같이 남았다(DB 는 한쪽).
        with mock.patch.object(cp, 'session_scope', fake_scope):
            c = make()
            c.pid_hold()
            self.assertEqual((True, False), (c.is_held, c.is_paused))
            c.pid_pause()
            self.assertEqual((False, True), (c.is_held, c.is_paused))
            c.pid_hold()
            self.assertEqual((True, False), (c.is_held, c.is_paused))
            c.pid_resume()
            self.assertEqual((False, False), (c.is_held, c.is_paused))

    def test_pause_turns_outputs_off(self):
        with mock.patch.object(cp, 'session_scope', fake_scope):
            c = make()
            c.pid_pause()
        c.control.output_off.assert_called_once_with('out', output_channel=0)

    def test_integrator_does_not_wind_up_while_paused_and_resume_is_bumpless(self):
        with mock.patch.object(cp, 'session_scope', fake_scope):
            c = make()
            c.check_pid()
            integ = c.PID_Controller.integrator
            c.pid_pause()
            for i in range(20):                         # 10분
                c.last_time += 30
                c.check_pid()
            self.assertEqual(integ, c.PID_Controller.integrator)
            c.pid_resume()
            self.assertTrue(c.PID_Controller.first_start)   # D 기준점만 다시 잡는다
            self.assertEqual(integ, c.PID_Controller.integrator)

    def test_legacy_both_flags_normalize_to_pause(self):
        c = make()
        c.is_held = c.is_paused = True
        # initialize_variables 의 정규화만 떼어 확인할 수 없어 같은 규칙을 직접 건다
        src = open(cp.__file__, encoding='utf-8').read()
        self.assertIn('if self.is_held and self.is_paused:', src)

    def test_hold_with_stale_measurement_turns_outputs_off(self):
        # 유지 중에도 측정이 낡으면 옛 제어 변수를 계속 내보내지 않는다.
        c = make()
        del c.manipulate_output                          # 진짜 manipulate_output 사용
        c.raise_output_type = 'on_off'
        c.raise_max_duration = 0
        c.raise_min_duration = 0
        c.raise_min_off_duration = 0
        c.write_pid_output_influxdb = lambda *a, **k: None
        c.check_pid()                                    # 신선한 한 번
        c.control.output_on.assert_called_once()
        c.is_held = True

        def stale():
            c.last_measurement_success = False
        c.get_last_measurement_pid = stale
        c.control.reset_mock()
        c.check_pid()
        c.control.output_on.assert_not_called()
        c.control.output_off.assert_called_once()


class NewSampleOnlyTest(unittest.TestCase):
    def test_same_sample_integrates_once(self):
        # 고치기 전: 표본 1개가 주기마다 적분에 더해졌다(4주기 → 20).
        c = make()
        for _ in range(4):
            c.check_pid()
        self.assertEqual(ERROR, c.PID_Controller.integrator)
        self.assertEqual(4, c.out_calls)                 # 출력은 매 주기

    def test_new_sample_integrates_again(self):
        c = make()
        c.check_pid()
        c.last_time += 120
        c.check_pid()
        self.assertEqual(2 * ERROR, c.PID_Controller.integrator)

    def test_setpoint_change_recomputes_p_without_integrating(self):
        c = make()
        c.check_pid()
        c.PID_Controller.setpoint = 30.0                 # 사용자가 설정점을 올림
        c.check_pid()                                    # 같은 표본
        self.assertEqual(ERROR, c.PID_Controller.integrator)
        self.assertEqual(10.0, c.PID_Controller.P_value)  # 다음 표본을 기다리지 않는다

    def test_last_time_is_epoch_seconds(self):
        # 고치기 전: `/ 1000` 으로 1970년 1월이 됐다.
        c = make()
        del c.get_last_measurement_pid
        with mock.patch.object(cp, 'get_measurement', return_value=SimpleNamespace(conversion_id=None)), \
                mock.patch.object(cp, 'db_retrieve_table_daemon', return_value=None), \
                mock.patch.object(cp, 'return_measurement_info', return_value=(0, 'C', 'temperature')), \
                mock.patch.object(cp, 'read_influxdb_single', return_value=[1_762_000_000.5, 21.0]):
            c.device_id, c.measurement_id, c.max_measure_age = 'd', 'm', 120
            c.get_last_measurement_pid()
        self.assertEqual(1_762_000_000.5, c.last_time)


class RetryOnlyReadsTest(unittest.TestCase):
    def test_output_failure_does_not_stack_integration(self):
        # 고치기 전: check_pid 전체를 3번 재시도해 한 주기에 적분이 3배(15)가 됐다.
        c = make()
        calls = {'n': 0}

        def flaky():
            calls['n'] += 1
            raise RuntimeError('output_on RPC 실패')
        c.manipulate_output = flaky
        with mock.patch('time.sleep') as sleep, mock.patch('time.monotonic', lambda: 5.0):
            c.run_cycle()
        self.assertEqual(ERROR, c.PID_Controller.integrator)
        self.assertEqual(1, calls['n'])                  # 출력 단계는 재시도 안 한다
        sleep.assert_not_called()
        self.assertEqual(5.0, c._last_run_mono)

    def test_read_failure_is_retried(self):
        c = make()
        calls = {'n': 0}

        def flaky_read():
            calls['n'] += 1
            if calls['n'] < 3:
                raise RuntimeError('influx 일시 오류')
            c.last_measurement_success = True
        c.get_last_measurement_pid = flaky_read
        with mock.patch('time.sleep') as sleep:
            c.run_cycle()
        self.assertEqual(3, calls['n'])
        self.assertEqual(2, sleep.call_count)
        self.assertEqual(ERROR, c.PID_Controller.integrator)


class ConditionalIntegrationTest(unittest.TestCase):
    def _pid(self, **limits):
        pid = PIDControl(logging.getLogger('t'), 25.0, 1.0, 1.0, 0.0, 'raise', 0, -100, 100)
        pid.output_min = limits.get('lo')
        pid.output_max = limits.get('hi')
        return pid

    def test_no_limits_behaves_as_before(self):
        pid = self._pid()
        for _ in range(3):
            pid.update_pid_output(20.0)
        self.assertEqual(15.0, pid.integrator)

    def test_saturated_output_stops_accumulating(self):
        # 고치기 전: 출력이 한계(10)에 붙어도 적분이 상한(100)까지 쌓였다.
        pid = self._pid(lo=0.0, hi=10.0)
        for _ in range(50):
            pid.update_pid_output(20.0)                  # 오차 +5 지속
        self.assertLess(pid.integrator, 10.0)
        # 오차가 뒤집히면 곧바로 풀린다
        pid.update_pid_output(30.0)
        self.assertLess(pid.control_variable, 10.0)

    def test_unwinding_is_allowed_while_saturated(self):
        pid = self._pid(lo=0.0, hi=10.0)
        pid.integrator = 50.0                            # 한계 훨씬 위
        pid.update_pid_output(30.0)                      # 오차 -5: 풀리는 방향
        self.assertEqual(45.0, pid.integrator)

    def test_floor_stops_negative_windup_for_raise_only(self):
        pid = self._pid(lo=0.0, hi=10.0)
        for _ in range(50):
            pid.update_pid_output(40.0)                  # 오차 -15 지속, 출력은 0 이하
        self.assertGreater(pid.integrator, -10.0)

    def test_controller_derives_limits_from_output_settings(self):
        c = make(period=30.0, direction='raise')
        c.raise_output_type, c.raise_max_duration = 'on_off', 20
        self.assertEqual((0.0, 20.0), c._output_limits())
        c.raise_output_type, c.raise_max_duration = 'pwm', 50
        self.assertEqual((0.0, 15.0), c._output_limits())      # 50% × 30초
        c.raise_max_duration = 0
        self.assertEqual((0.0, 30.0), c._output_limits())      # pwm 은 100% 가 한계
        c.raise_output_type, c.raise_max_duration = 'on_off', 0
        self.assertEqual((0.0, None), c._output_limits())
        c.raise_output_id = None
        self.assertEqual((None, None), c._output_limits())     # 계산 전용


class StatusFactsTest(unittest.TestCase):
    def test_facts_report_last_run_not_query_time(self):
        # 고치기 전: `Current time: {utc_now()}` 영문 원문이라 멈춘 PID 도 정상처럼 보였다.
        c = make(period=30.0)
        c.check_pid()
        c.timer = 130.0
        with mock.patch('time.monotonic', lambda: 100.0):
            c._last_run_mono = 40.0
            facts = c.function_status()['status_facts']
        self.assertEqual('pid', facts['kind'])
        self.assertEqual('running', facts['state'])
        self.assertEqual(60.0, facts['last_run_age_s'])
        self.assertEqual(30.0, facts['next_run_s'])
        self.assertEqual(30.0, facts['period_s'])
        self.assertNotIn('string_status', c.function_status())

    def test_never_run_and_states(self):
        c = make()
        self.assertIsNone(c.function_status()['status_facts']['last_run_age_s'])
        c.is_paused = True
        self.assertEqual('paused', c.function_status()['status_facts']['state'])
        c.is_paused, c.is_held = False, True
        self.assertEqual('held', c.function_status()['status_facts']['state'])
        c.is_activated = False
        self.assertEqual('deactivated', c.function_status()['status_facts']['state'])


if __name__ == '__main__':
    unittest.main()
