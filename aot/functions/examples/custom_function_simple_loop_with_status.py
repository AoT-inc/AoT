# coding=utf-8
#
#  custom_function_example.py - Custom function example file for importing into AoT
#
#  Copyright (C) 2015-2020 Kyle T. Gabriel <aot@aot-inc.com>
#
#  This file is part of AoT
#
#  AoT is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  AoT is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with AoT. If not, see <http://www.gnu.org/licenses/>.
#
#  Contact at aot-inc.com
#
import datetime
import time

from flask_babel import lazy_gettext

from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon

FUNCTION_INFORMATION = {
    'function_name_unique': 'example_function_loop_with_status',
    'function_name': 'Example: Simple Loop with Status',

    'message': 'This is an example function that will increment a stored variable once every 60 seconds. '
               'A status call will be made to the function from the web UI and the return string along '
               'with the current time will be displayed for the user every Status Period. The Status '
               'Widget will also display this status.',

    'options_enabled': [
        'custom_options',
        'function_status'
    ],
    'options_disabled': [
        'measurements_select',
        'measurements_configure'
    ],

    # These options will appear in the settings of the Function,
    # which the user can use to set different values and options for the Function.
    # These settings can only be changed when the Function is inactive.
    'custom_options': [
        {
            'id': 'period',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 60,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('Period'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The duration between measurements or actions')
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Start Offset'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The duration to wait before the first operation')
        },
        {
            'id': 'period_status',
            'type': 'integer',
            'default_value': 60,
            'required': True,
            'name': 'Status Period (Seconds)',
            'phrase': 'The duration to update the Function status on the UI'
        }
    ]
}


class CustomModule(AbstractFunction):
    """Example template function demonstrating loop() and function_status().

    This reference implementation shows how to create a periodic loop function
    that increments a counter and reports status to the web UI. Developers
    should copy this file as a starting point for simple timer-based functions.

    @phase prototype
    @stability experimental
    @dependency AbstractFunction, DaemonControl
    """
    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.timer_loop = None
        self.loop_count = 0

        #
        # Initialize what you defined in custom_options, above
        #

        self.period = None
        self.start_offset = None
        self.period_status = None

        #
        # Set custom options
        #
        custom_function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)
        self.setup_custom_options(
            FUNCTION_INFORMATION['custom_options'], custom_function)

        if not testing:
            self.try_initialize()

    def initialize(self):
        # import controller-specific modules here
        # You may import something you defined in dependencies_module
        self.timer_loop = time.time() + self.start_offset

    def loop(self):
        if self.timer_loop > time.time():
            return

        while self.timer_loop < time.time():
            self.timer_loop += self.period

        self.logger.info(
            "This text will appear in the Daemon Log as an INFO line")

        self.logger.debug(
            "This text will appear in the Daemon Log as an DEBUG line and "
            "will only appear if Log Level: Debug is enabled")

        self.loop_count += 1

        self.logger.info("Loop counter: {}".format(self.loop_count))

    def function_status(self):
        return_dict = {
            'string_status': "This info is being returned from the Function Module."
                             "\nCurrent time: {}"
                             "\nLoop count: {}".format(
                datetime.datetime.now(),
                self.loop_count),
            'error': []
        }
        return return_dict

    def button_one(self, args_dict):
        self.logger.error("Button One Pressed!: {}".format(int(args_dict['button_one_value'])))
        return "Here return message will be seen in the web UI. " \
               "This only works when 'wait_for_return' is set True."

    def button_two(self, args_dict):
        self.logger.error("Button Two Pressed!: {}".format(int(args_dict['button_two_value'])))
        return "This message will never be seen in the web UI because this process is threaded"
