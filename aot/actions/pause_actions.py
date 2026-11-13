# coding=utf-8
import time

from flask_babel import lazy_gettext

from aot.config_translations import TRANSLATIONS
from aot.databases.models import Actions
from aot.actions.base_action import AbstractFunctionAction, coerce_seconds
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.lazy_text import lazy_format, lazy_join

ACTION_INFORMATION = {
    'name_unique': 'pause_actions',
    'name': lazy_join(TRANSLATIONS['actions']['title'], ': ', TRANSLATIONS['pause']['title']),
    'library': None,
    'manufacturer': 'AoT',
    'application': ['functions'],

    'url_manufacturer': None,
    'url_datasheet': None,
    'url_product_purchase': None,
    'url_additional': None,

    'message': lazy_gettext('Set a delay between executing Actions when self.run_all_actions() is used.'),

    'usage': 'Executing <strong>self.run_action("ACTION_ID")</strong> will create a pause for the set duration. When <strong>self.run_all_actions()</strong> is executed, this will add a pause in the sequential execution of all actions.',

    'custom_options': [
        {
            'id': 'duration',
            'type': 'float',
            'default_value': 0.0,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_format("{} ({})", lazy_gettext('Duration'), lazy_gettext('Seconds')),
            'phrase': 'The duration to pause'
        }
    ]
}


class ActionModule(AbstractFunctionAction):
    """Pause execution for a configured duration between actions.

    @phase active
    @stability stable
    @dependency AbstractFunctionAction
    """
    def __init__(self, action_dev, testing=False):
        super().__init__(action_dev, testing=testing, name=__name__)

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
        """Sleep for the configured duration and update the message dict."""
        if 'message' not in dict_vars:
            dict_vars['message'] = ""

        # 코드가 value={"duration": ...} 로 넘기면 문자열·음수일 수 있다.
        # 음수 `time.sleep` 은 ValueError 로 뒤따르는 액션까지 끊는다.
        try:
            requested = dict_vars["value"]["duration"]
        except (KeyError, TypeError):
            requested = self.duration
        seconds = coerce_seconds(requested, default=0.0)
        if seconds < 0:
            self.logger.error(
                f"Pause duration {requested!r} is negative; not pausing.")
            seconds = 0.0

        dict_vars['message'] += f" Pause for {seconds:g} seconds."

        # 이 sleep 은 액션을 부른 스레드(트리거 컨트롤러 루프 또는 데몬의
        # RPC 스레드)를 그대로 붙잡는다 — run_all_actions() 의 순차 실행이
        # 곧 이 동작이다. 호출부가 이 시간을 감안해야 한다.
        if seconds > 0:
            time.sleep(seconds)

        self.logger.debug(f"Message: {dict_vars['message']}")

        return dict_vars

    def is_setup(self):
        return self.action_setup
