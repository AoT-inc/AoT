# coding=utf-8
"""Provide abstract controller with run loop lifecycle for all controllers.

Define the run-initialize-loop-stop lifecycle that concrete controller
subclasses must implement.

@phase active
@stability stable
@dependency AbstractBaseController
"""
import logging
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
                    time.sleep(self.sample_rate)

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
