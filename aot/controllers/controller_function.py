# coding=utf-8
#
#
#  Copyright (C) 2015-2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <http://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com
#
import threading
import time

from aot.controllers.base_controller import AbstractController
from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.databases.models import DeviceMeasurements
from aot.databases.models import Misc
from aot.aot_client import DaemonControl
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.functions import parse_function_information
from aot.utils.modules import load_module_from_file


class FunctionController(AbstractController, threading.Thread):
    """Operate custom function controller with dynamic module loading.

    @phase active
    @stability stable
    @dependency AbstractController, CustomController, DaemonControl
    """
    def __init__(self, ready, unique_id):
        threading.Thread.__init__(self)
        super().__init__(ready, unique_id=unique_id, name=__name__)

        self.unique_id = unique_id
        self.run_function = None
        self.sample_rate = None

        self.control = DaemonControl()

        self.timer_loop = time.time()
        self.dict_function = None
        self.device_measurements = None
        self.conversions = None
        self.function = None
        self.function_name = None
        self.log_level_debug = None
        self.device = None
        self.period = None

        self.has_loop = False
        self.has_listener = False
        self._bad_rate_logged = False

    def __str__(self):
        return str(self.__class__)

    def loop(self):
        """Execute the loaded function module loop at each period interval."""
        if not self.run_function:
            self.logger.error("Function could not be initialized. Shutting controller down.")
            self.running = False
            return

        if not self.has_loop:
            return
        now = time.time()
        module_due = self._module_seconds_until_due()
        # 점검 주기 격자(예전 그대로)와 모듈이 알려 준 할 일 시각 중 먼저 오는 쪽.
        # 격자는 그대로 밀어 둔다 — 모듈이 시각을 모를 때 예전처럼 불리게.
        grid_due = self.loop_is_due(now)
        if grid_due or (module_due is not None and module_due <= 0):
            try:
                self.run_function.loop()
            except Exception:
                self.logger.exception("Exception while running loop()")

    def _module_seconds_until_due(self):
        """모듈이 알려 준 다음 할 일까지 남은 초. 모르면 None."""
        fn = getattr(self.run_function, 'seconds_until_due', None)
        if not callable(fn):
            return None
        try:
            due = fn()
            return None if due is None else float(due)
        except Exception:
            return None

    def seconds_until_due(self):
        """기반 루프가 점검 주기 대신 모듈의 다음 할 일 시각에 깨어나게 한다."""
        if not self.has_loop or not self.run_function:
            return None
        return self._module_seconds_until_due()

    def _run_then_wake(self, run_command, args_dict):
        """모듈 명령(예: '지금 실행' 이 timer_loop 를 0 으로)을 마친 뒤 루프를 깨운다."""
        try:
            return run_command(args_dict)
        finally:
            self.wake()

    def loop_is_due(self, now):
        """이번 틱에 module.loop() 를 부를 때인가. 부를 때면 다음 시각으로 민다.

        Mycodo 원형은 `while timer_loop < now: timer_loop += sample_rate` 였다.
        sample_rate 가 0·음수·None 이면 끝나지 않아 이 스레드가 영영 돌고, RTC 없는
        보드에서 NTP 가 시계를 수년 앞으로 맞추면 수천만 번을 돈다. 한 번의 산술로
        민다. 시계가 한 주기 넘게 뒤로 가면(timer_loop 가 미래로 남음) 그 시각까지
        멈춰 있지 않고 지금부터 다시 센다.
        """
        try:
            rate = float(self.sample_rate)
        except (TypeError, ValueError):
            rate = 0.0
        if not (0 < rate < float('inf')):
            if not self._bad_rate_logged:
                self._bad_rate_logged = True
                self.logger.error(
                    "Function 루프 주기(sample_rate) %r 이(가) 양수가 아니다 — "
                    "1초로 대신 쓴다. 설정의 Function 컨트롤러 주기를 확인하라.",
                    self.sample_rate)
            rate = 1.0
        if self.timer_loop > now + rate:
            self.logger.warning("시스템 시계가 뒤로 갔다 — 루프 시각을 지금부터 다시 센다")
            self.timer_loop = now - 1e-6
        if self.timer_loop >= now:
            return False
        self.timer_loop += (int((now - self.timer_loop) // rate) + 1) * rate
        return True

    def run_finally(self):
        """Stop the loaded function module on controller shutdown."""
        try:
            self.run_function.stop_function()
        except:
            pass

    def initialize_variables(self):
        """Load function module and start listener thread if available."""
        function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)
        if function is None:
            raise RuntimeError(
                f"Function {self.unique_id}: 설정을 읽지 못해 컨트롤러를 "
                f"시작할 수 없다 (DB 조회 실패 또는 행 삭제)")

        self.log_level_debug = function.log_level_debug
        self.set_log_level_debug(self.log_level_debug)

        self.dict_function = parse_function_information()

        self.sample_rate = db_retrieve_table_daemon(
            Misc, entry='first').sample_rate_controller_function

        self.device_measurements = db_retrieve_table_daemon(
            DeviceMeasurements).filter(
            DeviceMeasurements.device_id == self.unique_id)

        self.conversions = db_retrieve_table_daemon(Conversion)

        self.function = function
        self.unique_id = function.unique_id
        self.function_name = function.name
        self.device = function.device

        if self.device in self.dict_function:
            function_loaded, status = load_module_from_file(
                self.dict_function[self.device]['file_path'],
                'function')

            if function_loaded:
                self.run_function = function_loaded.CustomModule(self.function)

            self.ready.set()
            self.running = True
        else:
            self.ready.set()
            self.running = False
            self.logger.error(f"'{self.device}' is not a valid device type. Deactivating controller.")
            return

        # Check if loop() exists
        if hasattr(self.run_function, 'loop'):
            self.logger.debug("loop() found")
            self.has_loop = True
        else:
            self.logger.debug("loop() not found")

        # Check if listener() exists
        if hasattr(self.run_function, 'listener'):
            self.logger.debug("listener() found")
            self.has_listener = True
        else:
            self.logger.debug("listener() not found")

        # Set up listener() thread
        if self.has_listener:
            self.logger.debug("Starting listener() thread")
            function_listener = threading.Thread(
                target=self.run_function.listener)
            function_listener.daemon = True
            function_listener.start()

    def call_module_function(self, button_id, args_dict, thread=True, return_from_function=False):
        """Execute function from custom action button press."""
        try:
            try:
                run_command = getattr(self.run_function, button_id)
            except AttributeError:
                msg = f"{button_id}() not found in module. Module may currently be initializing or may be missing the function."
                self.logger.error(msg)
                return 1, msg
            if not thread or return_from_function:
                return_val = self._run_then_wake(run_command, args_dict)
                if return_from_function:
                    return 0, return_val
                else:
                    return 0, f"Command sent to Function Controller. Returned: {return_val}"
            else:
                thread_run_command = threading.Thread(
                    target=self._run_then_wake,
                    args=(run_command, args_dict))
                thread_run_command.start()
                return 0, "Command sent to Function Controller and is running in the background."
        except Exception as err:
            msg = f"Error executing function '{button_id}': {err}"
            self.logger.exception(msg)
            return 1, msg

    def function_action(self, action_string, args_dict=None, thread=True):
        """Execute a named function action optionally in a background thread."""
        if args_dict is None:
            args_dict = {}
        try:
            run_command = getattr(self.run_function, action_string)
            if thread:
                thread_run_command = threading.Thread(
                    target=self._run_then_wake,
                    args=(run_command, args_dict))
                thread_run_command.start()
                return 0, "Command sent to Function Controller and is running in the background."
            else:
                return_val = self._run_then_wake(run_command, args_dict)
                return 0, ["Command sent to Function Controller.", return_val]
        except:
            self.logger.exception(f"Error executing function action '{action_string}'")

    def function_status(self):
        """Return the current status dict from the loaded function module."""
        func_exists = getattr(self.run_function, "function_status", None)
        if callable(func_exists):
            return self.run_function.function_status()
        else:
            return {
                'error': ["function_status() missing from Function Class"]
            }
