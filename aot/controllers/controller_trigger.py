# coding=utf-8
#
# controller_trigger.py - Trigger controller that checks measurements
#                         and performs functions in response to events
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

from aot.config import AOT_DB_PATH
from aot.controllers.base_controller import AbstractController
from aot.databases.models import CustomController
from aot.databases.models import Input
from aot.databases.models import Misc
from aot.databases.models import Output
from aot.databases.models import OutputChannel
from aot.databases.models import PID
from aot.databases.models import SMTP
from aot.databases.models import Trigger
from aot.databases.utils import session_scope
from aot.aot_client import DaemonControl
from datetime import datetime, timezone
from aot.utils.time_utils import parse_flexible_time, utc_now
from aot.utils.actions import parse_action_information
from aot.utils.actions import trigger_controller_actions
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.method import load_method_handler, parse_db_time
from aot.utils.solar import next_sun_event_epoch
from aot.utils.system_pi import epoch_of_next_time
from aot.utils.system_pi import time_between_range
from aot.utils.signals import trigger_fired
from aot.utils.execution_context import set_execution_context, clear_execution_context
from aot.utils.device_tz import get_device_tz



class TriggerController(AbstractController, threading.Thread):
    """Operate trigger controller for event-driven action execution.

    Triggers are events that signal when a set of actions should be executed.
    The main loop continually checks if any timer triggers have elapsed. If so,
    trigger_all_actions() executes all actions associated with that trigger.
    Edge and output conditionals are triggered from input/output controllers.

    @phase active
    @stability stable
    @dependency AbstractController, Trigger, Actions, DaemonControl
    """
    def __init__(self, ready, unique_id):
        threading.Thread.__init__(self)
        super().__init__(ready, unique_id=unique_id, name=__name__)

        self.unique_id = unique_id
        self.sample_rate = None

        self.control = DaemonControl()

        self.pause_loop = False
        self.verify_pause_loop = True
        self.trigger = None
        self.trigger_type = None
        self.trigger_name = None
        self.is_activated = None
        self.log_level_debug = None
        self.smtp_max_count = None
        self.email_count = None
        self.allowed_to_send_notice = None
        self.smtp_wait_timer = None
        self.timer_period = None
        self.period = None
        self.smtp_wait_timer = None
        self.timer_start_time = None
        self.timer_end_time = None
        self.unique_id_1 = None
        self.unique_id_2 = None
        self.unique_id_3 = None
        self.trigger_actions_at_period = None
        self.trigger_actions_at_start = None
        self.method_start_time = None
        self.method_end_time = None
        self._facility_tz = None

    def loop(self):
        # Pause loop to modify trigger.
        # Prevents execution of trigger while variables are
        # being modified.
        if self.pause_loop:
            self.verify_pause_loop = True
            while self.pause_loop:
                time.sleep(0.1)

        elif (self.is_activated and self.timer_period and
                self.timer_period < time.time()):
            check_approved = False

            # Check if the trigger period has elapsed
            if self.trigger_type == 'trigger_sunrise_sunset':
                while self.running and self.timer_period < time.time():
                    next_epoch = self.next_sunrise_sunset_epoch()
                    if next_epoch is None:
                        # 좌표 미해석/극지 등으로 다음 시각을 못 구한 경우.
                        # None 을 그대로 두면 다음 loop 에서 비교가 터지므로
                        # 한 시간 뒤 재시도로 물러선다.
                        self.logger.error(
                            "Could not calculate the next sunrise/sunset time. "
                            "Check this Trigger's location (latitude/longitude). "
                            "Retrying in 1 hour.")
                        self.timer_period = time.time() + 3600
                        return
                    self.timer_period = next_epoch
                check_approved = True

            elif self.trigger_type == 'trigger_run_pwm_method':
                # Only execute trigger actions when started
                # Now only set PWM output
                pwm_duty_cycle, ended = self.get_method_output(
                    self.trigger.unique_id_1)

                self.timer_period += self.trigger.period
                if pwm_duty_cycle is None:
                    # 메서드가 값을 내지 못했다(시작 시각 미기록·곡선 밖 등).
                    # 예전에는 그대로 넘겨 `amount=None` 으로 출력 명령이 나갔다.
                    self.logger.error(
                        "메서드가 설정점을 내지 못해 PWM 출력을 건드리지 "
                        "않습니다. 이 트리거의 메서드 설정을 확인하십시오.")
                else:
                    self.set_output_duty_cycle(pwm_duty_cycle)

                actions = parse_action_information()

                if self.trigger_actions_at_period:
                    trigger_controller_actions(
                        actions,
                        self.unique_id,
                        debug=self.log_level_debug)
                check_approved = True

                if ended:
                    self.stop_method()

            elif self.trigger_type in [
                    'trigger_timer_daily_time_point',
                    'trigger_timer_duration']:
                if self.trigger_type == 'trigger_timer_daily_time_point':
                    self.timer_period = epoch_of_next_time(f'{self.timer_start_time}:00', tz=self.device_tz)
                elif self.trigger_type == 'trigger_timer_duration':
                    while self.running and self.timer_period < time.time():
                        self.timer_period += self.period
                check_approved = True

            elif self.trigger_type == 'trigger_timer_daily_time_span':
                if time_between_range(self.timer_start_time,
                                      self.timer_end_time,
                                      tz=self.device_tz):
                    check_approved = True
                self.set_next_daily_time_span_run(time.time())

            if check_approved:
                self.logger.debug("Executing Trigger Actions")
                set_execution_context(source_type='trigger', source_id=self.unique_id)
                try:
                    self.attempt_execute(self.check_triggers)
                finally:
                    clear_execution_context()

                # Emit signal for AISchedulerService to track
                trigger_fired.send(
                    self,
                    trigger_id=self.unique_id,
                    name=self.trigger_name,
                    next_run=self.timer_period
                )


    def run_finally(self):
        pass

    # 메인 루프가 "멈췄다" 고 답할 때까지 기다리는 상한.
    #
    # 무한 대기였다. 그런데 이 확인은 **오직 `loop()` 안에서만** 세워지므로,
    # 컨트롤러 스레드가 이미 끝났거나(정지 중 refresh) 예외로 죽었으면 영원히
    # 오지 않는다 — RPC 스레드가 통째로 새고, 더 나쁘게는 `pause_loop` 가 True
    # 로 남아 **그 트리거가 두 번 다시 발화하지 않는다.**
    #
    # 못 기다렸을 때는 그냥 진행한다. 잠깐의 어긋난 읽기보다 트리거가 죽는
    # 쪽이 훨씬 나쁘고, 시퀀스 컨트롤러는 애초에 이 멈춤 없이 돈다.
    PAUSE_ACK_TIMEOUT_S = 10.0

    def refresh_settings(self):
        """Signal to pause the main loop and wait for verification, the refresh settings."""
        self.pause_loop = True
        try:
            deadline = time.time() + self.PAUSE_ACK_TIMEOUT_S
            while not self.verify_pause_loop:
                if time.time() >= deadline:
                    self.logger.error(
                        f"메인 루프가 {self.PAUSE_ACK_TIMEOUT_S:.0f}초 안에 멈춤을 "
                        "확인하지 않았습니다 — 기다리지 않고 설정을 다시 읽습니다.")
                    break
                time.sleep(0.1)

            self.logger.info("Refreshing trigger settings")
            self.initialize_variables()
        finally:
            # **반드시 푼다.** 예전에는 `initialize_variables()` 가 예외를
            # 던지면 `pause_loop` 가 True 로 남아, 메인 루프가 그 자리에 park
            # 한 채 트리거가 조용히 죽었다(에러 로그 한 줄 말고는 흔적이 없다).
            self.pause_loop = False
            self.verify_pause_loop = False
        return "Trigger settings successfully refreshed"

    def initialize_variables(self):
        """Define all settings."""
        self.email_count = 0
        self.allowed_to_send_notice = True

        self.sample_rate = db_retrieve_table_daemon(
            Misc, entry='first').sample_rate_controller_conditional

        self.smtp_max_count = db_retrieve_table_daemon(
            SMTP, entry='first').hourly_max

        self.trigger = db_retrieve_table_daemon(
            Trigger, unique_id=self.unique_id)
        self.trigger_type = self.trigger.trigger_type
        self.trigger_name = self.trigger.name
        self.is_activated = self.trigger.is_activated
        self.log_level_debug = self.trigger.log_level_debug

        # Resolve device timezone for local-clock comparisons (HH:MM settings).
        _tz_obj = get_device_tz(self.trigger)
        self._facility_tz = _tz_obj
        self.device_tz = str(_tz_obj)

        self.set_log_level_debug(self.log_level_debug)

        now = time.time()
        self.smtp_wait_timer = now + 3600
        self.timer_period = None

        # Set up trigger timer (daily time point)
        if self.trigger_type == 'trigger_timer_daily_time_point':
            self.timer_start_time = self.trigger.timer_start_time
            self.timer_period = epoch_of_next_time(f'{self.trigger.timer_start_time}:00', tz=self.device_tz)

        # Set up trigger timer (daily time span)
        elif self.trigger_type == 'trigger_timer_daily_time_span':
            self.timer_start_time = self.trigger.timer_start_time
            self.timer_end_time = self.trigger.timer_end_time
            self.period = self.trigger.period
            self.set_next_daily_time_span_run(now)

        # Set up trigger timer (duration)
        elif self.trigger_type == 'trigger_timer_duration':
            self.period = self.trigger.period
            if self.trigger.timer_start_offset:
                self.timer_period = now + self.trigger.timer_start_offset
            else:
                self.timer_period = now

        # Set up trigger Run PWM Method
        elif self.trigger_type == 'trigger_run_pwm_method':
            self.unique_id_1 = self.trigger.unique_id_1
            self.unique_id_2 = self.trigger.unique_id_2
            self.unique_id_3 = self.trigger.unique_id_3
            self.period = self.trigger.period
            self.trigger_actions_at_period = self.trigger.trigger_actions_at_period
            self.trigger_actions_at_start = self.trigger.trigger_actions_at_start
            self.method_start_time = self.trigger.method_start_time
            self.method_end_time = self.trigger.method_end_time
            if self.is_activated:
                self.start_method(self.trigger.unique_id_1)
            if self.trigger_actions_at_start:
                # 기준점을 한 주기 뒤로 눕히면 **다음 loop() 에서 바로 발화한다**
                # (`timer_period < time.time()` 이 참). 그래서 여기서 직접
                # `self.loop()` 를 부를 필요가 없다.
                #
                # ⚠ **다시 부르지 말 것 — 교착이다.** `initialize_variables` 는
                # 기동 때만 도는 게 아니라 `refresh_settings()` 를 통해서도
                # 도는데, 그쪽은 `pause_loop=True` 를 걸어 둔 채 이 함수를
                # 부른다. 그 상태에서 재진입한 `loop()` 는 첫 분기
                # (`if self.pause_loop:`)에서 `while self.pause_loop` 로 park
                # 하고, 그 플래그를 풀 코드는 자기를 기다리는 `refresh_settings`
                # 하나뿐이라 서로 영원히 기다린다. 실증(2026-09-05): 3초 안에
                # 반환하지 않았다. 걸리면 RPC 가 끝나지 않고 `pause_loop` 가
                # True 로 남아 **그 트리거는 조용히 영영 발화하지 않는다.**
                #
                # 대가는 발화가 최대 sample_rate 만큼 늦어지는 것뿐이다.
                self.timer_period = now - self.trigger.period
            else:
                self.timer_period = now

        # Set up trigger sunrise/sunset
        elif self.trigger_type == 'trigger_sunrise_sunset':
            self.period = 60
            # Set the next trigger at the specified sunrise/sunset time (+-offsets)
            self.timer_period = self.next_sunrise_sunset_epoch()

        self.ready.set()
        self.running = True

    def next_sunrise_sunset_epoch(self, trigger=None):
        """이 트리거의 다음 일출/일몰 시각(epoch). 계산 불가 시 None.

        위치는 트리거 자신의 좌표가 있으면 그것을, 없으면 태양시 커널의 상속
        체인(소속 도형 → 농장 지도 중심)을 따른다.
        """
        trigger = trigger if trigger is not None else self.trigger
        return next_sun_event_epoch(
            trigger.rise_or_set,
            target_id=trigger.unique_id,
            latitude=trigger.latitude,
            longitude=trigger.longitude,
            date_offset_days=trigger.date_offset_days,
            time_offset_minutes=trigger.time_offset_minutes)

    def set_next_daily_time_span_run(self, now):
        if not time_between_range(self.timer_start_time, self.timer_end_time, tz=self.device_tz):
            # Set next execution at start time
            self.timer_period = epoch_of_next_time(f'{self.trigger.timer_start_time}:00', tz=self.device_tz)
        else:
            # Find the next execution within the run period
            test_time = epoch_of_next_time(f'{self.trigger.timer_start_time}:00', tz=self.device_tz) - 86400
            while test_time < now:
                test_time += self.period
            self.timer_period = test_time

    def start_method(self, method_id):
        """Instruct a method to start running."""
        if method_id:
            this_controller = db_retrieve_table_daemon(
                Trigger, unique_id=self.unique_id)

            method = load_method_handler(method_id, self.logger, target_id=self.unique_id)

            if parse_db_time(this_controller.method_start_time) is None:
                self.method_start_time = utc_now()
                self.method_end_time = method.determine_end_time(self.method_start_time)

                self.logger.info(f"Starting method {self.method_start_time} {self.method_end_time}")

                with session_scope(AOT_DB_PATH) as db_session:
                    this_controller = db_session.query(Trigger)
                    this_controller = this_controller.filter(Trigger.unique_id == self.unique_id).first()
                    this_controller.method_start_time = self.method_start_time
                    this_controller.method_end_time = self.method_end_time
                    db_session.commit()
            else:
                # already running, potentially the daemon has been restarted
                self.method_start_time = this_controller.method_start_time
                self.method_end_time = this_controller.method_end_time

    def stop_method(self):
        self.method_start_time = None
        self.method_end_time = None
        with session_scope(AOT_DB_PATH) as db_session:
            this_controller = db_session.query(Trigger)
            this_controller = this_controller.filter(Trigger.unique_id == self.unique_id).first()
            this_controller.is_activated = False
            this_controller.method_start_time = None
            this_controller.method_end_time = None
            db_session.commit()
        self.stop_controller()
        self.is_activated = False
        self.logger.warning(
            "Method has ended. "
            "Activate the Trigger controller to start it again.")

    def _get_weeks_elapsed(self, method_start_raw) -> float:
        """Return fractional weeks elapsed since method_start_time (week-0 reference)."""
        if not method_start_raw:
            return 0.0
        try:
            from datetime import datetime as _dt, timezone as _tz
            from aot.utils.method import parse_db_time
            start_dt = parse_db_time(str(method_start_raw))
            if start_dt is None:
                return 0.0
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=_tz.utc)
            elapsed_sec = (_dt.now(_tz.utc) - start_dt).total_seconds()
            return max(0.0, elapsed_sec / (7 * 86400))
        except Exception as exc:
            self.logger.warning(f'Trigger _get_weeks_elapsed: {exc}')
            return 0.0

    def get_method_output(self, method_id):
        """Get output variable from method."""
        this_controller = db_retrieve_table_daemon(
            Trigger, unique_id=self.unique_id)

        if this_controller.method_start_time is None:
            # **반드시 튜플로 돌려준다.** 예전에는 맨 `return`(=None) 이라
            # 호출부의 `pwm_duty_cycle, ended = ...` 가 TypeError 로 터졌고,
            # 그 예외가 `timer_period` 를 갱신하기 **전**이라 루프가 매 주기
            # 같은 예외를 되풀이했다(로그 폭주 + 헛도는 루프).
            return None, False

        now = utc_now()

        method = load_method_handler(method_id, self.logger, target_id=self.unique_id)
        if method.method_type == 'DailyMultiPoint':
            weeks_elapsed = self._get_weeks_elapsed(this_controller.method_start_time)
            setpoint, ended = method.calculate_setpoint(
                now, this_controller.method_start_time,
                weeks_elapsed=weeks_elapsed,
                facility_tz=self._facility_tz)
        else:
            setpoint, ended = method.calculate_setpoint(now, this_controller.method_start_time)

        if setpoint is not None:
            if setpoint > 100:
                setpoint = 100
            elif setpoint < 0:
                setpoint = 0

        return setpoint, ended

    def set_output_duty_cycle(self, duty_cycle):
        """Set PWM Output duty cycle. 실패하면 **크게 남긴다**.

        예전에는 반환값을 버렸다. `output_on` 은 예외가 아니라 `(1, msg)` 로
        실패를 알리므로(Pyro5 타임아웃·통신오류 포함), 버리면 명령이 못 나가도
        설정점 곡선만 조용히 진행한다 — 화면의 설정점과 실제 출력이 갈리는데
        아무 흔적이 없다.
        """
        output_channel = db_retrieve_table_daemon(OutputChannel).filter(
            OutputChannel.unique_id == self.trigger.unique_id_3).first()
        output_channel = output_channel.channel if output_channel else 0
        self.logger.debug(f"Set output duty cycle to {duty_cycle}")
        ret = self.control.output_on(
            self.trigger.unique_id_2, output_type='pwm', amount=duty_cycle, output_channel=output_channel)
        # (code, msg) 중 code 0 만 성공. 튜플이 아닌 반환은 성공으로 본다 —
        # 반환값이 없는 드라이버가 정상이고, 감사 계층
        # (`controller_output.output_on_off`)도 같은 규약을 쓴다.
        if isinstance(ret, (tuple, list)) and ret and ret[0]:
            self.logger.error(
                f"PWM 듀티 {duty_cycle} 전송이 거부되었습니다 — "
                f"{ret[1] if len(ret) > 1 else ret[0]}. "
                "설정점 곡선은 계속 진행하지만 출력은 바뀌지 않았습니다.")
            return False
        return True

    def check_triggers(self):
        """
        Check if any Triggers are activated and
        execute their actions if so.

        For example, if measured temperature is above 30C, notify me@gmail.com

        "if measured temperature is above 30C" is the Trigger to check.
        "notify me@gmail.com" is the Trigger Action to execute if the
        Trigger is True.
        """
        now = time.time()
        timestamp = datetime.fromtimestamp(now).strftime(
            '%Y-%m-%d %H:%M:%S')
        message = f"{timestamp}\n[Trigger {self.unique_id} ({self.trigger_name})]"

        trigger = db_retrieve_table_daemon(
            Trigger, unique_id=self.unique_id, entry='first')

        device_id = trigger.measurement.split(',')[0]

        device = None

        input_dev = db_retrieve_table_daemon(
            Input, unique_id=device_id, entry='first')
        if input_dev:
            device = input_dev

        function = db_retrieve_table_daemon(
            CustomController, unique_id=device_id, entry='first')
        if function:
            device = CustomController

        output = db_retrieve_table_daemon(
            Output, unique_id=device_id, entry='first')
        if output:
            device = output

        pid = db_retrieve_table_daemon(
            PID, unique_id=device_id, entry='first')
        if pid:
            device = pid

        if not device:
            message += " Error: Controller not Input, Function, Output, or PID"
            self.logger.error(message)
            return

        # Calculate the sunrise/sunset times and find the next time this trigger should trigger
        elif trigger.trigger_type == 'trigger_sunrise_sunset':
            # Since the check time is the trigger time, we will only calculate and set the next trigger time
            self.timer_period = self.next_sunrise_sunset_epoch(trigger)

        # If the code hasn't returned by now, action should be executed
        actions = parse_action_information()
        trigger_controller_actions(
            actions,
            self.unique_id,
            message=message,
            debug=self.log_level_debug)
