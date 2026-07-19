# coding=utf-8
"""Provide abstract base template for all conditional controllers.

Ensure that required methods and instance variables are present in every
conditional subclass.

@phase active
@stability stable
@dependency Conditional, ConditionalConditions, Actions, DaemonControl
"""
import json

from aot.config import AOT_DB_PATH
from aot.databases.models import Actions
from aot.databases.models import Conditional
from aot.databases.models import ConditionalConditions
from aot.databases.utils import session_scope
from aot.aot_client import DaemonControl
from aot.utils.database import db_retrieve_table_daemon


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

    def run_all_actions(self, message=None):
        """Trigger execution of all actions associated with this conditional."""
        if message is None:
            message = self.message
        self.message = self.control.trigger_all_actions(self.function_id, message=message)

    def run_action(self, action_id, value=None, message=None):
        """Trigger a single action by its full or partial unique ID."""
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

        if message is None:
            send_dict['message'] = self.message

        if value:
            send_dict['value'] = value

        return_dict = self.control.trigger_action(
            full_action_id, value=send_dict)

        if return_dict and 'message' in return_dict:
            self.message = return_dict['message']

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

        return self.control.get_condition_measurement(full_cond_id)

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

        list_times_values = self.control.get_condition_measurement_dict(full_cond_id)
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
