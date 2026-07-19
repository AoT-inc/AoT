# coding=utf-8
import threading

from flask_babel import lazy_gettext

from aot.actions.base_action import AbstractFunctionAction
from aot.config import AOT_DB_PATH
from aot.config_translations import TRANSLATIONS
from aot.databases.models import Actions
from aot.databases.models import Method
from aot.databases.models import PID
from aot.databases.utils import session_scope
from aot.utils.database import db_retrieve_table_daemon


ACTION_INFORMATION = {
    'name_unique': 'method_pid',
    'name': "{}: {}".format(TRANSLATIONS['pid']['title'], lazy_gettext('Set Method')),
    'library': None,
    'manufacturer': 'AoT',
    'application': ['functions'],

    'url_manufacturer': None,
    'url_datasheet': None,
    'url_product_purchase': None,
    'url_additional': None,

    'message': lazy_gettext('Select a method to set the PID to use.'),

    'usage': 'Executing <strong>self.run_action("ACTION_ID")</strong> will pause the selected PID Controller. '
             'Executing <strong>self.run_action("ACTION_ID", value={"pid_id": "959019d1-c1fa-41fe-a554-7be3366a9c5b", "method_id": "fe8b8f41-131b-448d-ba7b-00a044d24075"})</strong> will set a method for the PID Controller with the specified IDs. Don\'t forget to change the pid_id value to an actual PID ID that exists in your system.',

    'custom_options': [
        {
            'id': 'controller',
            'type': 'select_device',
            'default_value': '',
            'options_select': [
                'PID'
            ],
            'name': lazy_gettext('Controller'),
            'phrase': 'Select the PID Controller to apply the method'
        },
        {
            'id': 'method',
            'type': 'select_device',
            'default_value': '',
            'options_select': [
                'Method'
            ],
            'name': lazy_gettext('Method'),
            'phrase': 'Select the Method to apply to the PID'
        }
    ]
}


class ActionModule(AbstractFunctionAction):
    """Assign a method to a PID controller.

    @phase active
    @stability stable
    @dependency AbstractFunctionAction
    """
    def __init__(self, action_dev, testing=False):
        super().__init__(action_dev, testing=testing, name=__name__)

        self.controller_id = None
        self.method_id = None

        action = db_retrieve_table_daemon(
            Actions, unique_id=self.unique_id)
        self.setup_custom_options(
            ACTION_INFORMATION['custom_options'], action)

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.action_setup = True

    def run_action(self, dict_vars):
        """Set the method for the specified PID controller."""
        try:
            controller_id = dict_vars["value"]["pid_id"]
        except:
            controller_id = self.controller_id

        try:
            method_id = dict_vars["value"]["method_id"]
        except:
            method_id = self.method_id

        pid = db_retrieve_table_daemon(
            PID, unique_id=controller_id, entry='first')

        if not pid:
            msg = f" Error: PID Controller with ID '{controller_id}' not found."
            dict_vars['message'] += msg
            self.logger.error(msg)
            return dict_vars

        method = db_retrieve_table_daemon(
            Method, unique_id=method_id, entry='first')

        if not method:
            msg = f" Error: Method with ID {method_id} not found."
            dict_vars['message'] += msg
            self.logger.error(msg)
            return dict_vars

        dict_vars['message'] += f" Set PID {controller_id} ({pid.name}) to Method {method_id} ({method.name})."

        if pid.is_activated:
            method_pid = threading.Thread(
                target=self.control.pid_set,
                args=(controller_id,
                      'method',
                      method_id,))
            method_pid.start()
        else:
            with session_scope(AOT_DB_PATH) as new_session:
                mod_pid = new_session.query(PID).filter(
                    PID.unique_id == controller_id).first()
                mod_pid.setpoint_tracking_type = 'method'
                mod_pid.setpoint_tracking_id = method_id
                mod_pid.method_start_time = None
                mod_pid.method_end_time = None
                new_session.commit()

        self.logger.debug(f"Message: {dict_vars['message']}")

        return dict_vars

    def is_setup(self):
        return self.action_setup
