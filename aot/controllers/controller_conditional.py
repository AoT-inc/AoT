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
import datetime
import importlib.util
import os
import threading
import time
import timeit

from aot.config import PATH_PYTHON_CODE_USER
from aot.controllers.base_controller import AbstractController
from aot.databases.models import Actions
from aot.databases.models import Conditional
from aot.databases.models import ConditionalConditions
from aot.databases.models import Misc
from aot.utils.conditional import save_conditional_code
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.signals import conditional_fired
from aot.utils.execution_context import set_execution_context, clear_execution_context
from aot.utils.time_utils import utc_now


class ConditionalController(AbstractController, threading.Thread):
    """Operate conditional controller with user-editable Python code execution.

    Execute user-defined Python code that queries measurement data and
    triggers function actions based on evaluated conditions.

    @phase active
    @stability stable
    @dependency AbstractController, Conditional, ConditionalConditions, Actions
    """
    def __init__(self, ready, unique_id):
        threading.Thread.__init__(self)
        super().__init__(ready, unique_id=unique_id, name=__name__)

        self.unique_id = unique_id
        self.pause_loop = False
        self.verify_pause_loop = True
        self.is_activated = None
        self.period = None
        self.start_offset = None
        self.pyro_timeout = None
        self.log_level_debug = None
        self.use_pylint = None
        self.message_include_code = None
        self.conditional_import = None
        self.conditional_initialize = None
        self.conditional_statement = None
        self.conditional_status = None
        self.timer_period = None
        self.file_run = None
        self.sample_rate = None
        self.time_conditional = None
        self.conditional_run = None
        self._last_run_ts = None

    def loop(self):
        """Check elapsed period and execute conditional code when due."""
        # Pause loop to modify conditional.
        # Prevents execution of conditional while variables are
        # being modified.
        if self.pause_loop:
            self.verify_pause_loop = True
            while self.pause_loop:
                time.sleep(0.1)

        self.time_conditional = time.time()
        # Check if the conditional period has elapsed
        if (self.is_activated and self.timer_period and
                self.timer_period < self.time_conditional):

            while self.timer_period < self.time_conditional:
                self.timer_period += self.period

            set_execution_context(source_type='conditional', source_id=self.unique_id)
            try:
                self.attempt_execute(self.check_conditionals)
            finally:
                clear_execution_context()

            # Emit signal for AISchedulerService to track — only when this
            # cycle's user code actually called run_action()/run_all_actions()
            # (AbstractConditional.action_fired). Every period tick used to
            # send this signal regardless of outcome, which turned every
            # active Conditional into a permanent once-a-period row in
            # scheduler_jobs_meta (41,000+ rows/month on a single box —
            # see project_scheduler_conditional_flood_incident memory).
            if getattr(self.conditional_run, 'action_fired', False):
                conditional_fired.send(
                    self,
                    conditional_id=self.unique_id,
                    name=db_retrieve_table_daemon(Conditional, unique_id=self.unique_id, entry='first').name,
                    next_run=self.timer_period
                )


    def initialize_variables(self):
        """Define all settings."""
        cond = db_retrieve_table_daemon(
            Conditional, unique_id=self.unique_id)
        if cond is None:
            # 조회 실패(락·디스크 I/O)든 행 삭제든, 자기 설정 없이 뜨면 잘못된
            # 상태로 동작한다. 원인을 남기고 기동을 중단한다.
            raise RuntimeError(
                f"Conditional {self.unique_id}: 설정을 읽지 못해 컨트롤러를 "
                f"시작할 수 없다 (DB 조회 실패 또는 행 삭제)")
        self.is_activated = cond.is_activated
        self.conditional_statement = cond.conditional_statement
        self.conditional_import = cond.conditional_import
        self.conditional_initialize = cond.conditional_initialize
        self.conditional_status = cond.conditional_status
        self.period = cond.period
        self.start_offset = cond.start_offset
        self.pyro_timeout = cond.pyro_timeout
        self.log_level_debug = cond.log_level_debug
        self.use_pylint = cond.use_pylint
        self.message_include_code = cond.message_include_code

        self.sample_rate = db_retrieve_table_daemon(
            Misc, entry='first').sample_rate_controller_conditional

        self.set_log_level_debug(self.log_level_debug)

        now = utc_now().timestamp()

        self.timer_period = now + self.start_offset

        self.file_run = f'{PATH_PYTHON_CODE_USER}/conditional_{self.unique_id}.py'

        # If the file to execute doesn't exist, generate it
        if not os.path.exists(self.file_run):
            save_conditional_code(
                [],
                self.conditional_import,
                self.conditional_initialize,
                self.conditional_statement,
                self.conditional_status,
                self.unique_id,
                db_retrieve_table_daemon(ConditionalConditions, entry='all'),
                db_retrieve_table_daemon(Actions, entry='all'),
                timeout=self.pyro_timeout)

        module_name = f"aot.conditional.{os.path.basename(self.file_run).split('.')[0]}"
        spec = importlib.util.spec_from_file_location(
            module_name, self.file_run)
        conditional_run = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conditional_run)
        self.conditional_run = conditional_run.ConditionalRun(
            self.logger, self.unique_id, '')

        self.logger.debug(
            f"Run Python Code (pre-replacement):\n{self.conditional_statement}")

        with open(self.file_run, 'r') as file:
            self.logger.debug(
                f"Run Python Code (post-replacement):\n{file.read()}")

        self.ready.set()
        self.running = True

    def refresh_settings(self):
        """Signal to pause the main loop and wait for verification, the refresh settings."""
        self.pause_loop = True
        while not self.verify_pause_loop:
            time.sleep(0.1)

        self.logger.info("Refreshing conditional settings")
        self.initialize_variables()

        self.pause_loop = False
        self.verify_pause_loop = False
        return "Conditional settings successfully refreshed"

    def check_conditionals(self):
        """Check if conditional is activated and execute its user-defined code."""
        # Reset before every cycle (not just on success) so a stale True from
        # a prior cycle can never leak into this one's conditional_fired
        # decision, including on the early-return/exception paths below.
        self.conditional_run.action_fired = False

        cond = db_retrieve_table_daemon(
            Conditional, unique_id=self.unique_id, entry='first')
        if cond is None:
            # 사용자 코드를 실행하는 자리다. 설정을 못 읽은 채 진행하면 무엇을
            # 실행하는지 모르는 상태가 되므로 이번 판정을 건너뛴다.
            self.logger.error(
                "Conditional 설정을 읽지 못해 이번 판정을 건너뛴다")
            return

        timestamp = datetime.datetime.fromtimestamp(
            self.time_conditional).strftime('%Y-%m-%d %H:%M:%S')
        message = f"{timestamp}\n[Conditional {self.unique_id}]\n[Name: {cond.name}]"

        if self.message_include_code:
            message += '\n[Run Python Code Code Executed]:' \
                       '\n--------------------' \
                       f'\n{cond.conditional_statement}' \
                       '\n--------------------\n'

        message += '\n[Messages]:\n'

        self.conditional_run.message = message
        try:
            self.conditional_run.conditional_code_run()
        except Exception:
            self.logger.exception("Exception executing Run Python Code")
        # `time_conditional` 은 loop() 가 **매 tick** 덮어쓰므로(주기가 아니라
        # sample_rate 마다) "마지막으로 판정한 때" 가 아니다. 상태 요약이 그
        # 값을 쓰면 주기가 1시간인 Conditional 도 "방금 실행" 으로 보인다.
        self._last_run_ts = time.time()

    def function_status(self):
        """Return the current status of the conditional function.

        정본은 사용자 코드다 — Conditional 설정의 "Status" 칸이 생성된
        `ConditionalRun.function_status()` 본문이 된다(`utils/conditional.py`).

        ⚠ **그 칸은 비어 있을 수 있고, 그때 생성된 메서드는 `pass` 라 `None` 을
          돌려준다.** 그러면 라우트가 `null` 을 내보내고 위젯 JS 는 `'error' in
          data` 에서 죽는다 — 응답은 200 이고 콘솔에만 남으므로 화면에서는
          **아무 일도 일어나지 않은 것처럼 보인다.** 사용자가 상태 코드를 안
          적었다는 것이 "이 Conditional 이 도는지 알 수 없다" 가 되어서는 안
          되므로, 그때는 컨트롤러가 아는 실행 상태로 대신 답한다.
        """
        status = None
        user_status = getattr(self.conditional_run, 'function_status', None)
        if callable(user_status):
            try:
                status = user_status()
            except Exception as err:
                # 사용자 코드의 실패는 감추지 않는다 — 여기서 조용히 아래
                # 기본 요약으로 넘어가면 "상태 코드를 고쳤는데 화면이 안
                # 바뀐다" 가 되고, 원인이 코드에 있다는 사실이 사라진다.
                self.logger.exception("Exception executing function_status")
                return {'error': [f"Status code error: {err}"]}

        # 사용자 코드가 실제로 할 말이 있을 때만 그것을 쓴다. 빈 문자열은
        # 위젯에서 "받은 것이 없음" 과 구별되지 않는다.
        if isinstance(status, dict) and (status.get('string_status')
                                         or status.get('error')):
            return status

        # ⚠ **문장을 여기서 만들지 말 것.** 데몬에는 요청 컨텍스트가 없어
        #   `gettext` 가 뷰어의 언어로 풀리지 않는다. 사실만 내보내고 문장은
        #   Flask 쪽(`aot_flask/utils/utils_function_status.py`)이 만든다.
        now = time.time()
        last_run = getattr(self, '_last_run_ts', None)
        return {
            'status_facts': {
                'kind': 'conditional',
                'is_activated': bool(self.is_activated),
                'period_s': self.period,
                'last_run_age_s': (now - last_run) if last_run else None,
                'action_fired': bool(
                    getattr(self.conditional_run, 'action_fired', False)),
                'next_check_s': (max(0.0, self.timer_period - now)
                                 if self.is_activated and self.timer_period else None),
            },
            'error': [],
        }

    def stop_controller(self):
        """Stop the conditional controller and its running code."""
        self.thread_shutdown_timer = timeit.default_timer()
        self.pre_stop()
        try:
            self.conditional_run.stop_conditional()
        except Exception:
            pass
        self.running = False
