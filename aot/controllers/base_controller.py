# coding=utf-8
"""Provide abstract controller with run loop lifecycle for all controllers.

Define the run-initialize-loop-stop lifecycle that concrete controller
subclasses must implement.

@phase active
@stability stable
@dependency AbstractBaseController
"""
import logging
import threading
import time
import timeit

import Pyro5

from aot.controllers.abstract_base_controller import AbstractBaseController
from aot.utils.execution_context import set_thread_default


def _controller_kind(class_name):
    """'PIDController' -> 'pid'. 출처 표기에 쓰는 짧은 종류 이름."""
    name = class_name[:-len('Controller')] if class_name.endswith('Controller') else class_name
    return name.lower() or 'controller'


class AbstractController(AbstractBaseController):
    """Manage controller run loop lifecycle with initialize, loop, and stop.

    @phase active
    @stability stable
    @dependency AbstractBaseController
    """
    def __init__(self, ready, unique_id=None, name=__name__):
        super().__init__(unique_id, name=__name__)

        self.thread_startup_timer = timeit.default_timer()
        self.running = False
        self.thread_shutdown_timer = 0
        self.sample_rate = 0.25
        self.unique_id = unique_id
        self.ready = ready
        # Set by stop_controller() to cut short the inter-loop wait. The loop
        # used to sit in an uninterruptible time.sleep(sample_rate), so a
        # controller noticed running=False up to one full period late and the
        # daemon's shutdown time tracked sample_rate rather than the work.
        #
        # sample_rate is user-configurable (Settings > General) and the defaults
        # are small (0.05-0.25 s), which is why this stayed invisible: it only
        # bites on installs that raised it. Measured 2026-08-12 on the local
        # install, where all six rates are 15 s -- of a 38.4 s shutdown, the
        # Output controller spent 8.3 s and the Widget controller 14.4 s purely
        # asleep, and every output's actual teardown took 15 ms in total.
        # Shutdown after this change: 1.84 s.
        self._stop_event = threading.Event()
        # 루프 사이 대기를 **끝내는** 신호. stop 도 이것을 세운다. 다른 스레드가
        # 새 일정을 만들었을 때(출력을 N초 켬 등) `wake()` 로 세워, 점검 주기
        # (sample_rate)를 다 기다리지 않고 다음 할 일 시각을 다시 계산하게 한다.
        self._wake_event = threading.Event()
        self._overdue_last_wait = False

        logger_name = f"{name}"
        if self.unique_id:
            logger_name += f"_{unique_id.split('-')[0]}"
            self.setup_device_measurement(unique_id)
        self.logger = logging.getLogger(logger_name)

    #
    # Begin functions the user is expected to overwrite
    #

    def initialize_variables(self):
        """Initialize controller-specific variables; must be overridden by subclasses."""
        self.logger.error(
            f"{type(self).__name__} did not overwrite the initialize_variables() method. "
            f"All subclasses of the AbstractController class are required to overwrite this method")
        raise NotImplementedError

    def loop(self):
        """Execute one iteration of the controller main loop; must be overridden."""
        self.logger.error(
            f"{type(self).__name__} did not overwrite the loop() method. "
            f"All subclasses of the AbstractController class are required to overwrite this method")
        raise NotImplementedError

    def run_finally(self):
        """Executed after loop() has finished."""
        pass

    def pre_stop(self):
        """Executed when the controller is instructed to stop."""
        pass

    #
    # End functions the user typically overwrites
    #

    def run(self):
        """Execute the controller lifecycle: initialize, loop, and finalize."""
        # 이 스레드가 대표하는 주체를 한 번 등록한다. 컨트롤러는 각자 자기
        # 스레드에서 돌고, 장치 명령은 그 스레드에서 DaemonControl 로 나가므로
        # 여기 한 줄이면 PID·Function·env_coordinator 등 44곳의 호출부를 건드리지
        # 않고도 "어느 자동화가 명령했나" 가 감사·InfluxDB 양쪽에 채워진다.
        try:
            set_thread_default(
                source_type=_controller_kind(type(self).__name__),
                source_id=self.unique_id)
        except Exception:
            pass  # 출처 표기 실패가 컨트롤러 기동을 막지 않는다

        try:
            try:
                self.initialize_variables()
            except Exception as except_msg:
                self.logger.exception(f"initialize_variables() Exception: {except_msg}")

            dur = (timeit.default_timer() - self.thread_startup_timer) * 1000
            self.logger.debug(f"Activated in {dur:.1f} ms")

            while self.running:
                try:
                    self.loop()
                except Pyro5.errors.TimeoutError:
                    self.logger.exception("Pyro5 TimeoutError")
                except Exception:
                    self.logger.exception("loop() Error")
                finally:
                    # Interruptible pacing: identical cadence while running,
                    # but a stop is acted on immediately instead of one
                    # sample_rate later. wait(None) would block forever, which
                    # is a worse failure than the TypeError sleep(None) raised,
                    # so fall back to the constructor default.
                    self._wake_event.wait(self._loop_wait())
                    self._wake_event.clear()

        except Exception:
            self.logger.exception("Run Error")
            self.thread_shutdown_timer = timeit.default_timer()
        finally:
            self.run_finally()
            self.running = False
            if self.thread_shutdown_timer:
                dur = (timeit.default_timer() - self.thread_shutdown_timer) * 1000
                self.logger.debug(f"Deactivated in {dur:.1f} ms")
            else:
                self.logger.error("Deactivated unexpectedly")

    def is_running(self):
        return self.running

    def stop_controller(self):
        """Signal the controller to stop running and begin shutdown."""
        self.thread_shutdown_timer = timeit.default_timer()
        self.pre_stop()
        self.running = False
        # Wake the loop out of its inter-iteration wait. Set after running=False
        # so the woken thread always re-reads the flag as already cleared.
        self._stop_event.set()
        self._wake_event.set()

    # 다음 할 일 시각에 맞춰 깨어날 때의 하한(초). 0 으로 기다리면 바쁜 대기가
    # 되므로 아주 작게 둔다 — 할 일 시각 바로 뒤에 깨어나 `< now` 비교가 참이 된다.
    MIN_LOOP_WAIT_S = 0.01

    def _base_wait(self):
        """점검 주기(sample_rate). 없거나 양수가 아니면 생성자 기본 0.25초."""
        try:
            rate = float(self.sample_rate)
        except (TypeError, ValueError):
            return 0.25
        return rate if rate > 0 and rate == rate else 0.25

    def seconds_until_due(self):
        """다음 할 일까지 남은 초. 없으면 None — 하위 클래스가 덮어쓴다.

        점검 주기는 "얼마나 자주 상태를 둘러보나" 이지 "약속한 시각을 얼마나
        어길 수 있나" 가 아니다. 예전에는 루프가 늘 sample_rate 만큼 잤으므로,
        점검 주기를 15초로 올린 설치(2026-11-12 맥북·맥미니 실측)에서는 시간
        트리거가 최대 15초 늦게 발화하고 출력의 '5초 켜짐' 이 15초가 됐다.
        """
        return None

    def _loop_wait(self):
        """이번 대기 길이: 점검 주기와 '다음 할 일까지' 중 짧은 쪽."""
        base = self._base_wait()
        try:
            due = self.seconds_until_due()
        except Exception:
            self.logger.exception("seconds_until_due() Error")
            due = None
        if due is None:
            return base
        try:
            due = float(due)
        except (TypeError, ValueError):
            return base
        if due != due:     # NaN
            return base
        if due <= 0:
            # 할 일 시각이 지났는데 직전 바퀴에서도 지나 있었다면 `loop()` 가 그
            # 시각을 앞으로 밀지 못하는 상태다(주기 0 으로 저장된 설정 등).
            # 바로 다시 깨우면 0.01초마다 도는 바쁜 대기가 되므로 예전처럼 점검
            # 주기로 물러선다.
            if getattr(self, '_overdue_last_wait', False):
                self._overdue_last_wait = False
                return base
            self._overdue_last_wait = True
            return self.MIN_LOOP_WAIT_S
        self._overdue_last_wait = False
        return max(self.MIN_LOOP_WAIT_S, min(base, due + self.MIN_LOOP_WAIT_S))

    def wake(self):
        """기다리는 루프를 바로 깨운다(다음 할 일 시각을 다시 계산하게)."""
        event = getattr(self, '_wake_event', None)    # __init__ 전(시험의 object.__new__)
        if event is not None:
            event.set()

    def set_log_level_debug(self, log_level_debug):
        if log_level_debug:
            self.logger.setLevel(logging.DEBUG)
        else:
            # 시스템 전역 로그 규칙: 장치 단위 INFO/WARNING 은 사용자가
            # log_level_debug 옵션을 켠 경우에만 기록. 기본은 ERROR 이상만 저장.
            self.logger.setLevel(logging.ERROR)

    def attempt_execute(self, func, times=3, delay_sec=10):
        """Attempt to execute a function several times with a delay between attempts."""
        for i in range(1, times + 1):
            try:
                func()
                break
            except Exception:
                if i < times:
                    self.logger.exception(
                        f"Exception executing {func.__name__}() on attempt {i} of {times}. "
                        f"Waiting {delay_sec} seconds and trying again.")
                    time.sleep(delay_sec)
                else:
                    self.logger.exception(
                        f"Exception executing {func.__name__}() on attempt {i} of {times}.")
