# coding=utf-8
#

import time

from flask_babel import lazy_gettext

from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.influx import average_past_seconds
from aot.utils.system_pi import get_measurement
from aot.utils.system_pi import return_measurement_info

measurements_dict = {
    0: {
        'measurement': '',
        'unit': '',
    }
}

FUNCTION_INFORMATION = {
    'function_name_unique': 'AVG_PAST_SINGLE',
    'function_name': '평균 (Past, Single)',
    'measurements_dict': measurements_dict,
    'enable_channel_unit_select': True,

    'message': '이 함수는 선택된 측정값의 과거 측정값(Max Age 내)을 가져와 평균을 계산한 후, 결과값을 해당 측정값과 단위로 저장합니다.'
               '참고: InfluxDB 1.8.10에는 mean() 함수가 올바르게 작동하지 않는 버그가 있습니다.'
               '따라서 InfluxDB v1.x를 사용하는 경우 median() 함수가 대신 사용됩니다.'
               'InfluxDB 2.x에서는 이 문제가 발생하지 않으며, mean() 함수를 정상적으로 사용할 수 있습니다.'
               '정확한 평균값을 얻으려면 InfluxDB 2.x로 업그레이드하세요.',

    'options_enabled': [
        'measurements_select_measurement_unit',
        'custom_options'
    ],

    'custom_options': [
        {
            'id': 'period',
            'type': 'float',
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
            'id': 'select_measurement',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': [
                'Input',
                'Function'
            ],
            'name': lazy_gettext('Measurement'),
            'phrase': 'Measurement to replace "x" in the equation'
        },
        {
            'id': 'max_measure_age',
            'type': 'integer',
            'default_value': 360,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Max Age'), lazy_gettext('Seconds')),
            'phrase': lazy_gettext('The maximum age of the measurement to use')
        }
    ]
}


class CustomModule(AbstractFunction):
    """
    Class to operate custom controller
    """
    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.timer_loop = time.time()

        self.control = DaemonControl()

        # Initialize custom options
        self.period = None
        self.start_offset = None
        self.select_measurement_device_id = None
        self.select_measurement_measurement_id = None
        self.max_measure_age = None

        # Set custom options
        custom_function = db_retrieve_table_daemon(
            CustomController, unique_id=self.unique_id)
        self.setup_custom_options(
            FUNCTION_INFORMATION['custom_options'], custom_function)

        if not testing:
            self.try_initialize()

    def initialize(self):
        self.timer_loop = time.time() + self.start_offset

    def loop(self):
        if self.timer_loop > time.time():
            return

        while self.timer_loop < time.time():
            self.timer_loop += self.period

        device_measurement = get_measurement(self.select_measurement_measurement_id)

        if not device_measurement:
            self.logger.error("Could not find Device Measurement")
            return

        conversion = db_retrieve_table_daemon(
            Conversion, unique_id=device_measurement.conversion_id)
        channel, unit, measurement = return_measurement_info(
            device_measurement, conversion)

        average = average_past_seconds(
            self.select_measurement_device_id,
            unit,
            channel,
            self.max_measure_age,
            measure=measurement)

        if not average:
            self.logger.error("Could not find measurement within the set Max Age")
            return False

        measurement_dict = {
            0: {
                'measurement': self.channels_measurement[0].measurement,
                'unit': self.channels_measurement[0].unit,
                'value': average
            }
        }

        if measurement_dict:
            self.logger.debug(
                "Adding measurements to InfluxDB with ID {}: {}".format(
                    self.unique_id, measurement_dict))
            add_measurements_influxdb(self.unique_id, measurement_dict)
        else:
            self.logger.debug(
                "No measurements to add to InfluxDB with ID {}".format(
                    self.unique_id))
