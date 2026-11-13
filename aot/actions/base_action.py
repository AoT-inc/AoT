# coding=utf-8
"""Provide the abstract base class template for all Function Actions.

All Actions should inherit from this class and overwrite methods that raise
NotImplementedErrors. It is not to be used directly.

@phase active
@stability stable
@dependency AbstractBaseController, DaemonControl
"""
import logging
import timeit

from aot.controllers.abstract_base_controller import AbstractBaseController
from aot.config import AOT_DB_PATH
from aot.databases.models import Conditional
from aot.databases.models import Function
from aot.databases.models import Input
from aot.databases.models import Trigger
from aot.databases.utils import session_scope
from aot.aot_client import DaemonControl


def coerce_seconds(value, default=0.0):
    """액션 입력(설정값 또는 `value={...}` 로 넘어온 값)을 초 단위 float 로 읽는다.

    설정 화면 값은 float 로 파싱되지만 `run_action("ID", value={"duration": "30"})`
    처럼 코드가 넘기는 값은 문자열·None 일 수 있다. 그대로 `time.sleep`·산술에
    넣으면 TypeError 로 액션 전체가 죽는다. 읽을 수 없거나 NaN/무한이면
    `default` 를 돌려준다. 부호는 그대로 둔다(음수 지속 시간은 출력 쪽에서
    역방향 구동을 뜻할 수 있다).
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float('inf'), float('-inf')):
        return default
    return number


class AbstractFunctionAction(AbstractBaseController):
    """Enforce required methods and instance variables for all Function Actions.

    @phase active
    @stability stable
    @dependency AbstractBaseController, DaemonControl
    """
    def __init__(self, action_dev, testing=False, name=__name__):
        if not testing:
            super().__init__(action_dev.unique_id, testing=testing, name=__name__)
        else:
            super().__init__(None, testing=testing, name=__name__)

        self.action = action_dev
        self.action_setup = False
        self.startup_timer = timeit.default_timer()
        self.control = DaemonControl()

        self.logger = None
        self.setup_logger(testing=testing, name=name, action=action_dev)

        self.running = True

        if not testing:
            self.unique_id = action_dev.unique_id

    def __iter__(self):
        """Support the iterator protocol."""
        return self

    def __repr__(self):
        """Representation of object."""
        return_str = f'<{type(self).__name__}>'
        return return_str

    def __str__(self):
        """Return measurement information."""
        return_str = ''
        return return_str

    def is_setup(self):
        """Return whether the action has been successfully set up."""
        self.logger.error(
            f"{type(self).__name__} did not overwrite the is_setup() method. All "
            "subclasses of the AbstractFunctionAction class are required to overwrite "
            "this method")
        raise NotImplementedError

    def initialize(self):
        """Initialize the action; subclasses must override this method."""
        self.logger.error(
            f"{type(self).__name__} did not overwrite the initialize() method. All "
            "subclasses of the AbstractFunctionAction class are required to overwrite "
            "this method")
        raise NotImplementedError

    def run_action(self, dict_vars):
        """Called when Action is executed."""
        pass

    #
    # Do not overwrite the function below
    #

    def setup_logger(self, testing=None, name=None, action=None):
        """Configure the logger instance with appropriate debug level."""
        name = name if name else __name__
        if not testing and action:
            log_name = f"{name}_{action.unique_id.split('-')[0]}"
        else:
            log_name = name
        self.logger = logging.getLogger(log_name)
        if not testing and action:
            with session_scope(AOT_DB_PATH) as new_session:
                # 시스템 전역 로그 규칙: 장치 단위 INFO/WARNING 은 사용자가
                # log_level_debug 옵션을 켠 경우에만 기록. 기본은 ERROR 이상만 저장.
                debug_level = logging.ERROR

                input_dev = new_session.query(Input).filter(
                    Input.unique_id == action.function_id).first()
                conditional = new_session.query(Conditional).filter(
                    Conditional.unique_id == action.function_id).first()
                function = new_session.query(Function).filter(
                    Function.unique_id == action.function_id).first()
                trigger = new_session.query(Trigger).filter(
                    Trigger.unique_id == action.function_id).first()

                if input_dev and input_dev.log_level_debug:
                    debug_level = logging.DEBUG
                elif conditional and conditional.log_level_debug:
                    debug_level = logging.DEBUG
                elif function and function.log_level_debug:
                    debug_level = logging.DEBUG
                elif trigger and trigger.log_level_debug:
                    debug_level = logging.DEBUG

                self.logger.setLevel(debug_level)
