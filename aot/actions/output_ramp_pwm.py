# coding=utf-8
import math
import time

from flask_babel import lazy_gettext

from aot.config_translations import TRANSLATIONS
from aot.databases.models import Actions
from aot.databases.models import Output
from aot.actions.base_action import AbstractFunctionAction, coerce_seconds
from aot.utils.constraints_pass import constraints_pass_positive_or_zero_value
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.execution_context import run_in_thread
from aot.utils.lazy_text import lazy_format, lazy_join

ACTION_INFORMATION = {
    'name_unique': 'output_ramp_pwm',
    'name': lazy_join(TRANSLATIONS['output']['title'], ': ', TRANSLATIONS['ramp']['title'], ' ', TRANSLATIONS['duty_cycle']['title']),
    'library': None,
    'manufacturer': 'AoT',
    'application': ['functions'],

    'url_manufacturer': None,
    'url_datasheet': None,
    'url_product_purchase': None,
    'url_additional': None,

    'message': lazy_gettext('Ramp a PWM Output from one duty cycle to another duty cycle over a period of time.'),

    'usage': 'Executing <strong>self.run_action("ACTION_ID")</strong> will ramp the PWM output duty cycle according to the settings. '
             'Executing <strong>self.run_action("ACTION_ID", value={"output_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "channel": 0, "start": 42, "end": 62, "increment": 1.0, "duration": 600})</strong> will ramp the duty cycle of the PWM output with the specified ID and channel. Don\'t forget to change the output_id value to an actual Output ID that exists in your system.',

    'custom_options': [
        {
            'id': 'output',
            'type': 'select_channel',
            'default_value': '',
            'required': True,
            'options_select': [
                'Output_Channels',
            ],
            'name': lazy_gettext('Output'),
            'phrase': 'Select an output to control'
        },
        {
            'id': 'start',
            'type': 'float',
            'default_value': 0.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_or_zero_value,
            'name': lazy_format("{}: {}", lazy_gettext('Duty Cycle'), lazy_gettext('Start')),
            'phrase': lazy_gettext('Duty cycle for the PWM (percent, 0.0 - 100.0)')
        },
        {
            'id': 'end',
            'type': 'float',
            'default_value': 50.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_or_zero_value,
            'name': lazy_format("{}: {}", lazy_gettext('Duty Cycle'), lazy_gettext('End')),
            'phrase': lazy_gettext('Duty cycle for the PWM (percent, 0.0 - 100.0)')
        },
        {
            'id': 'increment',
            'type': 'float',
            'default_value': 1.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_format("{} ({})", lazy_gettext('Increment'), lazy_gettext('Duty Cycle')),
            'phrase': 'How much to change the duty cycle every Duration'
        },
        {
            'id': 'duration',
            'type': 'float',
            'default_value': 0.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_or_zero_value,
            'name': lazy_format("{} ({})", lazy_gettext('Duration'), lazy_gettext('Seconds')),
            'phrase': 'How long to ramp from start to finish.'
        }
    ]
}


def ramp_plan(start, end, increment, duration):
    """램프 계획 `(start, [단계별 듀티...], 단계 간격 초)`. 만들 수 없으면 None.

    - 값이 문자열이어도 숫자로 읽는다(`value={...}` 로 넘어온 경우).
    - `increment <= 0` 은 끝에 닿지 못하므로 거부한다(예전엔 0 나눗셈/무한 루프).
    - `duration == 0` 이면 기다림 없이 끝값으로 바로 간다. `start == end` 면 시작값만 쓴다.
      예전엔 duration 0(설정 기본값이 0.0)이면 단계 간격 0 이라 `while timer <
      time.time()` 이 영원히 참인 **무한 루프**였다.
    - 마지막 단계는 항상 `end` 로 맞춘다(증분이 나누어떨어지지 않아도).
    """
    start = coerce_seconds(start, default=None)
    end = coerce_seconds(end, default=None)
    increment = coerce_seconds(increment, default=None)
    duration = coerce_seconds(duration, default=None)
    if None in (start, end, increment, duration):
        return None
    if increment <= 0 or duration < 0:
        return None
    if start == end:
        return start, [], 0.0
    if duration == 0:
        return start, [end], 0.0

    count = max(1, math.ceil(abs(end - start) / increment - 1e-9))
    direction = 1 if end > start else -1
    steps = [start + direction * increment * k for k in range(1, count)]
    steps.append(end)
    # 램프 전체가 정확히 duration 안에 끝나도록 단계 수로 나눈다.
    return start, steps, duration / count


class ActionModule(AbstractFunctionAction):
    """Ramp a PWM output duty cycle between two values over a duration.

    @phase active
    @stability stable
    @dependency AbstractFunctionAction
    """
    def __init__(self, action_dev, testing=False):
        super().__init__(action_dev, testing=testing, name=__name__)

        self.output_device_id = None
        self.output_channel_id = None
        self.start = None
        self.end = None
        self.increment = None
        self.duration = None

        action = db_retrieve_table_daemon(
            Actions, unique_id=self.unique_id)
        self.setup_custom_options(
            ACTION_INFORMATION['custom_options'], action)

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.action_setup = True

    def run_action(self, dict_vars):
        """Ramp the PWM duty cycle from start to end in timed increments."""
        try:
            output_id = dict_vars["value"]["output_id"]
        except:
            output_id = self.output_device_id

        try:
            channel = dict_vars["value"]["channel"]
        except:
            channel = self.get_output_channel_from_channel_id(
                self.output_channel_id)

        try:
            start = dict_vars["value"]["start"]
        except:
            start = self.start

        try:
            end = dict_vars["value"]["end"]
        except:
            end = self.end

        try:
            increment = dict_vars["value"]["increment"]
        except:
            increment = self.increment

        try:
            duration = dict_vars["value"]["duration"]
        except:
            duration = self.duration

        if 'message' not in dict_vars:
            dict_vars['message'] = ""

        output = db_retrieve_table_daemon(
            Output, unique_id=output_id, entry='first')

        if not output:
            msg = f" Error: Output with ID '{output_id}' not found."
            dict_vars['message'] += msg
            self.logger.error(msg)
            return dict_vars

        plan = ramp_plan(start, end, increment, duration)
        if plan is None:
            msg = (f" Error: Ramp of output {output_id} CH{channel} not run "
                   f"(invalid start={start!r}, end={end!r}, "
                   f"increment={increment!r}, duration={duration!r}).")
            dict_vars['message'] += msg
            self.logger.error(msg)
            return dict_vars
        start, steps, seconds_per_step = plan

        dict_vars['message'] += f" Ramp output {output_id} CH{channel} ({output.name}) " \
                                f"duty cycle from {start:g} % to {(steps[-1] if steps else start):g} % in increments " \
                                f"of {coerce_seconds(increment):g} over {coerce_seconds(duration):g} seconds."

        run_in_thread(
            self.control.output_on,
            args=(output_id,),
            kwargs={'output_type': 'pwm',
                    'amount': start,
                    'output_channel': channel})

        # 경과 시간은 벽시계(time.time)가 아니라 단조 시계로 잰다 — NTP·수동
        # 보정으로 시계가 뒤로 가면 램프가 그만큼 멈추고, 앞으로 가면 한꺼번에
        # 끝난다. 그리고 단계 사이에는 **잔다**: 예전에는 sleep 없이 시계만
        # 확인하는 바쁜 루프라 램프 시간 내내 CPU 한 코어를 먹었다.
        # (이 함수는 액션을 부른 스레드를 램프 시간만큼 붙잡는다 — 호출부 참조.)
        t0 = time.monotonic()
        for index, duty_cycle in enumerate(steps, start=1):
            remaining = t0 + index * seconds_per_step - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            run_in_thread(
                self.control.output_on,
                args=(output_id,),
                kwargs={'output_type': 'pwm',
                        'amount': duty_cycle,
                        'output_channel': channel})

        self.logger.debug(f"Message: {dict_vars['message']}")

        return dict_vars

    def is_setup(self):
        return self.action_setup
