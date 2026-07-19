# coding=utf-8
#
# AoT Average (Last, Multiple)
#
# Input measurements to aggregate are registered in the Actions table with the 'avg_measurement_input' type.
# In the UI, measurements can be added/removed via "Add Action -> AoT Average: Input Measurement".
#

import json
import time

from flask_babel import lazy_gettext

from aot.databases.models import Actions
from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.influx import read_influxdb_single
from aot.utils.system_pi import get_measurement
from aot.utils.system_pi import return_measurement_info

measurements_dict = {
    0: {
        'measurement': '',
        'unit': '',
    }
}

FUNCTION_INFORMATION = {
    'function_name_unique': 'AoT_AVG_MULTI',
    'function_name': lazy_gettext('AoT Average (Last, Multiple)'),
    'measurements_dict': measurements_dict,
    'enable_channel_unit_select': True,

    'message': lazy_gettext(
        'Reads the latest data from the selected measurements, computes the arithmetic mean, '
        'and stores the result with the specified measurement/unit. '
        'Register the input measurements to aggregate by adding the '
        '"AoT Average: Input Measurement" action in the [Actions] list below. '
        'Only the average is stored; the original source values are not stored separately.'
    ),

    'options_enabled': [
        'measurements_select_measurement_unit',
        'custom_options',
        'enable_actions'
    ],

    # Restrict the actions that can be added to this function (other action types are not shown in the dropdown)
    'restrict_actions': [
        'measurement_input',
        'measurement_output',
        'measurement_function',
    ],

    'custom_options': [
        {
            'id': 'period',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 60,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('Period'), lazy_gettext('seconds')),
            'phrase': lazy_gettext('The period (in seconds) between measurements and calculations')
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Start Offset'), lazy_gettext('seconds')),
            'phrase': lazy_gettext('The wait time (in seconds) before the first measurement')
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': 360,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Max Age'), lazy_gettext('seconds')),
            'phrase': lazy_gettext(
                'Default maximum age (in seconds). '
                'If set separately in an individual input action, that value takes precedence.'
            )
        },
        {
            'id': 'debug_logging',
            'type': 'bool',
            'default_value': False,
            'required': False,
            'name': lazy_gettext('Enable Debug Logging'),
            'phrase': lazy_gettext('Log the computed average value each cycle. Leave off in production.')
        },
    ]
}


class CustomModule(AbstractFunction):
    """Compute the average of the last readings from multiple measurement channels.

    Input measurements are registered as Actions of type 'avg_measurement_input'
    linked to this function. The loop() queries those actions at runtime to
    build the channel list.

    Only the computed average is written to InfluxDB (channel 0).
    Source readings are never re-stored.

    @phase core
    @stability stable
    @dependency AbstractFunction, DaemonControl, Conversion, Actions, InfluxDB
    """

    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.timer_loop = time.time()
        self.control = DaemonControl()

        self.period = None
        self.start_offset = None
        self.max_measure_age = None

        custom_function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)

        self.setup_custom_options(
            FUNCTION_INFORMATION['custom_options'], custom_function)

        if not testing:
            self.try_initialize()

    def initialize(self):
        """Start the loop after start_offset on the first run."""
        self.timer_loop = time.time() + self.start_offset

    def loop(self):
        """Each period, read measurements from the registered actions and store the average to InfluxDB."""
        if self.timer_loop > time.time():
            return

        while self.timer_loop < time.time():
            self.timer_loop += self.period

        # ----------------------------------------------------------
        # 1) Query the 'avg_measurement_input' actions registered to this function
        # ----------------------------------------------------------
        input_actions = db_retrieve_table_daemon(Actions).filter(
            Actions.function_id == self.unique_id,
            Actions.action_type.in_([
                'measurement_input',
                'measurement_output',
                'measurement_function',
            ])
        ).all()

        if not input_actions:
            self.logger.warning(
                "No input measurement actions are registered. "
                "Add 'AoT Average: Input/Output/Function Measurement' in the actions list.")
            return

        # ----------------------------------------------------------
        # 2) Read the measurement from each action (source values are not stored)
        # ----------------------------------------------------------
        values = []
        for action in input_actions:
            try:
                opts = json.loads(action.custom_options) if action.custom_options else {}
            except Exception:
                self.logger.error(
                    "Failed to parse custom_options for action {}.".format(action.unique_id))
                continue

            meas_str = opts.get('select_measurement', '')
            if not meas_str or ',' not in meas_str:
                self.logger.debug(
                    "Action {}: measurement not set, skipping.".format(action.unique_id))
                continue

            device_id, measure_id = meas_str.split(',', 1)
            max_age = int(opts.get('max_measure_age', self.max_measure_age))

            device_measurement = get_measurement(measure_id)
            if not device_measurement:
                self.logger.error(
                    "Action {}: measurement channel (ID={}) info not found.".format(
                        action.unique_id, measure_id))
                continue

            conversion = db_retrieve_table_daemon(
                Conversion, unique_id=device_measurement.conversion_id)
            channel, unit, measurement = return_measurement_info(
                device_measurement, conversion)

            self.logger.debug(
                "Action {}: device={}, unit={}, channel={}, measurement={}, max_age={}s".format(
                    action.unique_id, device_id, unit, channel, measurement, max_age))

            last = read_influxdb_single(
                device_id,
                unit,
                channel,
                measure=measurement,
                duration_sec=max_age,
                value='LAST'
            )

            if not last:
                self.logger.warning(
                    "Action {}: no valid data within {} seconds, excluding.".format(
                        action.unique_id, max_age))
                continue

            # last = (timestamp, value) — skip None values
            if last[1] is None:
                continue
            values.append(last[1])

        # ----------------------------------------------------------
        # 3) Exit if there is no valid data
        # ----------------------------------------------------------
        if not values:
            self.logger.warning("No valid measurements, average not stored.")
            return

        # ----------------------------------------------------------
        # 4) Compute the average and store it to InfluxDB (average only)
        # ----------------------------------------------------------
        average = sum(values) / len(values)
        if getattr(self, 'debug_logging', False):
            self.logger.info(
                "Average of {} inputs: {:.6g}".format(len(values), average))

        add_measurements_influxdb(
            self.unique_id,
            {
                0: {
                    'measurement': self.channels_measurement[0].measurement,
                    'unit': self.channels_measurement[0].unit,
                    'value': average
                }
            }
        )
