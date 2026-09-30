# coding=utf-8
"""Provide abstract base template for all conditional controllers.

Ensure that required methods and instance variables are present in every
conditional subclass.

@phase active
@stability stable
@dependency Conditional, ConditionalConditions, Actions, DaemonControl
"""
import json
import time

import Pyro5.errors

from aot.config import AOT_DB_PATH
from aot.databases.models import Actions
from aot.databases.models import Conditional
from aot.databases.models import ConditionalConditions
from aot.databases.utils import session_scope
from aot.aot_client import DaemonControl
from aot.utils.database import db_retrieve_table_daemon

# custom_options 키 하나를 예약해 "마지막으로 액션을 발동시킨 시각"을 저장한다.
# 사용자 코드도 self.set_custom_option()/get_custom_option() 으로 같은
# custom_options JSON 을 쓰므로, 충돌을 피하기 위해 사용자가 고를 법하지 않은
# 이름을 쓴다. 데몬이 재시작돼도 이 값은 DB 에 남아있어 불응기가 끊기지 않는다.
_REFRACTORY_LAST_FIRED_KEY = '__aot_refractory_last_fired_ts__'


class AbstractConditional:
    """Provide base template for all conditional execution classes.

    @phase active
    @stability stable
    @dependency Conditional, ConditionalConditions, Actions, DaemonControl
    """
    def __init__(self, logger, function_id, message, timeout=30):
        self.logger = logger
        self.function_id = function_id
        self.variables = {}
        self.message = message
        self.running = True
        self.control = DaemonControl(pyro_timeout=timeout)
        # Set by run_action()/run_all_actions() when THIS check cycle actually
        # triggered an action — the only reliable "did it really fire" signal,
        # since conditional_statement is arbitrary user code with no other
        # structured way to report outcome. ConditionalController resets this
        # to False before each conditional_code_run() call and only emits
        # conditional_fired when it ends up True (see controller_conditional.py).
        self.action_fired = False
        # 이번 check_conditionals() 주기에 대해 불응기 판정을 이미 내렸는지
        # (None=아직) 캐시한다. ConditionalController 가 매 주기 시작 시
        # action_fired 와 함께 None 으로 되돌린다. 한 번 판정하면 같은 주기 안의
        # 나머지 run_action()/run_all_actions() 호출(예: 장치를 켜고 이메일도
        # 보내는 것처럼 한 알림 이벤트에 속한 여러 액션)은 서로를 억제하지
        # 않고, 다음 주기부터 다시 불응기를 적용한다.
        self._refractory_gate_result = None

    def _refractory_gate(self):
        """Decide whether Refractory Period allows dispatching an action now.

        Returns True (and records "now" as the last-fired time) when firing is
        allowed. Returns False when a Refractory Period is configured on this
        Conditional and hasn't elapsed since the last dispatch — the caller
        should then skip the action without setting action_fired.
        """
        if self._refractory_gate_result is not None:
            return self._refractory_gate_result

        allowed = True
        conditional = db_retrieve_table_daemon(Conditional, unique_id=self.function_id)
        refractory_period = getattr(conditional, 'refractory_period', None) if conditional else None

        if conditional and refractory_period:
            try:
                dict_custom_options = json.loads(conditional.custom_options) if conditional.custom_options else {}
            except Exception:
                dict_custom_options = {}

            now = time.time()
            last_fired = dict_custom_options.get(_REFRACTORY_LAST_FIRED_KEY)
            if last_fired is not None and (now - last_fired) < refractory_period:
                allowed = False
                self.logger.debug(
                    "Refractory Period ({}s) active for this Conditional — "
                    "suppressing action dispatch ({:.1f}s remaining)".format(
                        refractory_period, refractory_period - (now - last_fired)))
            else:
                self.set_custom_option(_REFRACTORY_LAST_FIRED_KEY, now)

        self._refractory_gate_result = allowed
        return allowed

    def run_all_actions(self, message=None):
        """Trigger execution of all actions associated with this conditional."""
        if not self._refractory_gate():
            return
        if message is None:
            message = self.message
        self.action_fired = True
        self.message = self.control.trigger_all_actions(self.function_id, message=message)

    def run_action(self, action_id, value=None, message=None):
        """Trigger a single action by its full or partial unique ID."""
        if not self._refractory_gate():
            return None
        action = None
        full_action_id = action_id
        if len(action_id) < 36:
            action_id = action_id.replace("{", "").replace("}", "")
            with session_scope(AOT_DB_PATH) as new_session:
                action = new_session.query(Actions).filter(
                    Actions.unique_id.startswith(action_id)).first()
                new_session.expunge_all()
        if action:
            full_action_id = action.unique_id

        send_dict = {}

        # message= 로 넘긴 문구가 액션에 그대로 전달돼야 한다(생략하면 self.message).
        send_dict['message'] = self.message if message is None else message

        if value:
            send_dict['value'] = value

        self.action_fired = True
        return_dict = self.control.trigger_action(
            full_action_id, value=send_dict)

        if return_dict and 'message' in return_dict:
            self.message = return_dict['message']

    def _daemon_read(self, call, condition_id):
        """Read a condition value from the daemon; None if it can't answer in time.

        The daemon reads InfluxDB (client timeout 60 s) while this proxy gives up
        after ``timeout`` (30 s). When InfluxDB stalls the RPC times out, and the
        exception used to abort the whole check cycle, so user code never got to
        act on "no value". One retry rides out a short stall; after that the
        caller gets None, the same answer as a stale measurement.
        """
        for attempt in (1, 2):
            try:
                return call(condition_id)
            except (Pyro5.errors.TimeoutError, Pyro5.errors.CommunicationError) as err:
                self.logger.warning(
                    f"condition {condition_id}: daemon did not answer "
                    f"(attempt {attempt}/2): {err}")
        return None

    def condition(self, condition_id):
        """Retrieve the current measurement value for a condition."""
        full_cond_id = condition_id
        cond = None
        if len(condition_id) < 36:
            condition_id = condition_id.replace("{", "").replace("}", "")
            with session_scope(AOT_DB_PATH) as new_session:
                cond = new_session.query(ConditionalConditions).filter(
                    ConditionalConditions.unique_id.startswith(condition_id)).first()
                new_session.expunge_all()
        if cond:
            full_cond_id = cond.unique_id

        return self._daemon_read(
            self.control.get_condition_measurement, full_cond_id)

    def condition_dict(self, condition_id):
        """Retrieve time-value pairs for a condition as a list of dicts."""
        full_cond_id = condition_id
        cond = None
        if len(condition_id) < 36:
            condition_id = condition_id.replace("{", "").replace("}", "")
            with session_scope(AOT_DB_PATH) as new_session:
                cond = new_session.query(ConditionalConditions).filter(
                    ConditionalConditions.unique_id.startswith(condition_id)).first()
                new_session.expunge_all()
        if cond:
            full_cond_id = cond.unique_id

        list_times_values = self._daemon_read(
            self.control.get_condition_measurement_dict, full_cond_id)
        if list_times_values:
            list_ts_values = []
            for time, value in list_times_values:
                list_ts_values.append({'time': time, 'value': float(value)})
            return list_ts_values
        return None

    def stop_conditional(self):
        """Signal the conditional to stop its execution loop."""
        self.running = False

    def set_custom_option(self, option, value):
        """Persist a custom option key-value pair to the database."""
        try:
            with session_scope(AOT_DB_PATH) as new_session:
                mod_cond = new_session.query(Conditional).filter(
                    Conditional.unique_id == self.function_id).first()
                try:
                    dict_custom_options = json.loads(mod_cond.custom_options)
                except:
                    dict_custom_options = {}
                dict_custom_options[option] = value
                mod_cond.custom_options = json.dumps(dict_custom_options)
                new_session.commit()
        except Exception:
            self.logger.exception("set_custom_option")

    def get_custom_option(self, option, default_return=None):
        """Retrieve a custom option value from the database."""
        conditional = db_retrieve_table_daemon(Conditional, unique_id=self.function_id)
        try:
            dict_custom_options = json.loads(conditional.custom_options)
        except:
            dict_custom_options = {}
        if option in dict_custom_options:
            return dict_custom_options[option]
        return default_return
