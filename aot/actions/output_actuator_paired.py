# coding=utf-8
import threading

from flask_babel import lazy_gettext

from aot.databases.models import Actions
from aot.databases.models import Output
from aot.actions.base_action import AbstractFunctionAction
from aot.utils.constraints_pass import constraints_pass_positive_or_zero_value
from aot.utils.database import db_retrieve_table_daemon

ACTION_INFORMATION = {
    'name_unique': 'output_actuator_paired',
    'name': lazy_gettext('Output: Actuator Paired (Position / Stop)'),
    'library': None,
    'manufacturer': 'AoT',
    'application': ['functions'],

    'url_manufacturer': None,
    'url_datasheet': None,
    'url_product_purchase': None,
    'url_additional': None,

    'message': lazy_gettext(
        'Drive an Actuator Paired output to a target position (0–100 %) or send a Stop command.'
    ),

    'usage': (
        'Executing <strong>self.run_action("ACTION_ID")</strong> drives the actuator to the '
        'configured position. '
        'Executing <strong>self.run_action("ACTION_ID", value={"output_id": "UUID", '
        '"channel": 0, "command": "set_position", "position": 75})</strong> drives the '
        'Actuator Paired output with the given ID to 75 %. '
        'Use <strong>"command": "stop"</strong> to halt motion immediately.'
    ),

    'custom_options': [
        {
            'id': 'output',
            'type': 'select_channel',
            'default_value': '',
            'required': True,
            'options_select': ['Output_Channels'],
            'name': lazy_gettext('Actuator Paired Output'),
            'phrase': lazy_gettext('Select the Actuator Paired output channel to control.'),
        },
        {
            'id': 'command',
            'type': 'select',
            'default_value': 'set_position',
            'required': True,
            'options_select': [
                ('set_position', lazy_gettext('Set Position (%)')),
                ('stop',         lazy_gettext('Stop')),
            ],
            'name': lazy_gettext('Command'),
            'phrase': lazy_gettext(
                '"Set Position" drives the actuator to the target %. '
                '"Stop" halts motion immediately.'
            ),
        },
        {
            'id': 'position',
            'type': 'float',
            'default_value': 0.0,
            'required': False,
            'constraints_pass': constraints_pass_positive_or_zero_value,
            'name': lazy_gettext('Target Position (%)'),
            'phrase': lazy_gettext('0 = fully closed, 100 = fully open. Used only when Command is "Set Position".'),
        },
    ],
}


class ActionModule(AbstractFunctionAction):
    """Drive an Actuator Paired output to a target position or stop it.

    @phase active
    @stability stable
    @dependency AbstractFunctionAction
    """

    def __init__(self, action_dev, testing=False):
        super().__init__(action_dev, testing=testing, name=__name__)

        self.output_device_id = None
        self.output_channel_id = None
        self.command = 'set_position'
        self.position = 0.0

        action = db_retrieve_table_daemon(Actions, unique_id=self.unique_id)
        self.setup_custom_options(ACTION_INFORMATION['custom_options'], action)

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.action_setup = True

    def run_action(self, dict_vars):
        """Drive the Actuator Paired output to a position or stop it."""
        try:
            output_id = dict_vars["value"]["output_id"]
        except Exception:
            output_id = self.output_device_id

        try:
            channel = dict_vars["value"]["channel"]
        except Exception:
            channel = self.get_output_channel_from_channel_id(self.output_channel_id)

        try:
            command = dict_vars["value"]["command"]
        except Exception:
            command = self.command

        try:
            position = float(dict_vars["value"]["position"])
        except Exception:
            position = float(self.position or 0.0)

        position = max(0.0, min(100.0, position))

        output = db_retrieve_table_daemon(Output, unique_id=output_id, entry='first')

        if 'message' not in dict_vars:
            dict_vars['message'] = ''

        if not output:
            msg = f" Error: Output with ID '{output_id}' not found."
            dict_vars['message'] += msg
            self.logger.error(msg)
            return dict_vars

        if command == 'stop':
            dict_vars['message'] += (
                f" Actuator Paired output {output_id} CH{channel} ({output.name}): Stop."
            )
            t = threading.Thread(
                target=self.control.output_off,
                args=(output_id,),
                kwargs={'output_channel': channel},
            )
            t.start()
        else:
            dict_vars['message'] += (
                f" Actuator Paired output {output_id} CH{channel} ({output.name}): "
                f"set position to {position:.1f} %."
            )
            t = threading.Thread(
                target=self.control.output_on,
                args=(output_id,),
                kwargs={
                    'output_type': 'value',
                    'amount': position,
                    'output_channel': channel,
                },
            )
            t.start()

        self.logger.debug(f"Message: {dict_vars['message']}")
        return dict_vars

    def is_setup(self):
        return self.action_setup
