# coding=utf-8
#

#
#  Copyright (C) 2015-2020 Kyle T. Gabriel <mycodo@kylegabriel.com>
#
#  This file is part of Mycodo
#
#  Mycodo is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  Mycodo is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with Mycodo. If not, see <http://www.gnu.org/licenses/>.
#
#  Contact at kylegabriel.com
#
import copy
import time

from flask_babel import lazy_gettext

from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.inputs.sensorutils import calculate_vapor_pressure_deficit
from aot.inputs.sensorutils import convert_from_x_to_y_unit
from aot.aot_client import DaemonControl
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.system_pi import get_measurement
from aot.utils.system_pi import return_measurement_info

measurements_dict = {
    0: {
        'measurement': 'vapor_pressure_deficit',
        'unit': 'Pa'
    }
}

FUNCTION_INFORMATION = {
    'function_name_unique': 'AoT_VPD',
    'function_name': lazy_gettext('AoT VPD'),
    'measurements_dict': measurements_dict,
    'message': lazy_gettext('This function calculates the Vapor Pressure Deficit (VPD) based on leaf temperature and humidity. '
               'If leaf temperature is not provided, an offset is applied to the air temperature instead.'),

    'options_enabled': [
        'custom_options'
    ],

    # custom_options with a Leaf Temperature option added
    'custom_options': [
        {
            'id': 'period',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 60,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('Period'), lazy_gettext('seconds')),
            'phrase': lazy_gettext('The period between measurements or actions')
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Start Offset'), lazy_gettext('seconds')),
            'phrase': lazy_gettext('The wait time before the first action')
        },
        {
            'id': 'select_measurement_temperature_c',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': [
                'Input',
                'Function'
            ],
            'required': False,
            'name': lazy_gettext('Air Temperature'),
            'phrase': lazy_gettext('Air temperature measurement')
        },
        {
            'id': 'max_measure_age_temperature_c',
            'type': 'integer',
            'default_value': 360,
            'required': False,
            'name': "{}: {} ({})".format(lazy_gettext('Air Temperature'), lazy_gettext('Max Age'), lazy_gettext('seconds')),
            'phrase': lazy_gettext('The maximum age of the measurement to use')
        },
        {
            'id': 'select_measurement_humidity',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': [
                'Input',
                'Function'
            ],
            'required': False,
            'name': lazy_gettext('Humidity'),
            'phrase': lazy_gettext('Humidity measurement')
        },
        {
            'id': 'max_measure_age_humidity',
            'type': 'integer',
            'default_value': 360,
            'required': False,
            'name': "{}: {} ({})".format(lazy_gettext('Humidity'), lazy_gettext('Max Age'), lazy_gettext('seconds')),
            'phrase': lazy_gettext('The maximum age of the measurement to use')
        },
        {
            'id': 'select_measurement_leaf_temp',
            'type': 'select_measurement',
            'default_value': '',
            'options_select': [
                'Input',
                'Function'
            ],
            'required': False,
            'name': lazy_gettext('Leaf Temperature'),
            'phrase': lazy_gettext('Leaf temperature measurement')
        },
        {
            'id': 'max_measure_age_leaf_temp',
            'type': 'integer',
            'default_value': 360,
            'required': False,
            'name': "{}: {} ({})".format(lazy_gettext('Leaf Temperature'), lazy_gettext('Max Age'), lazy_gettext('seconds')),
            'phrase': lazy_gettext('The maximum age of the measurement to use')
        },
        {
            'id': 'leaf_temp_offset',
            'type': 'float',
            'default_value': -1.5,
            'required': True,
            'name': lazy_gettext('Leaf Temperature Offset (°C)'),
            'phrase': lazy_gettext('Offset (°C) to apply when leaf temperature is not provided')
        }
    ]
}


class CustomModule(AbstractFunction):
    """Calculate Vapor Pressure Deficit (VPD) from air temperature and humidity.

    Computes VPD in Pascals using leaf temperature (or air temperature with
    a configurable offset) and relative humidity. Outputs a single
    vapor_pressure_deficit measurement to InfluxDB.

    @phase core
    @stability stable
    @dependency AbstractFunction, DaemonControl, Conversion, InfluxDB
    """
    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)

        self.timer_loop = time.time()

        self.control = DaemonControl()

        # Initialize custom options
        self.period = None
        self.start_offset = None

        self.select_measurement_temperature_c_device_id = None
        self.select_measurement_temperature_c_measurement_id = None
        self.max_measure_age_temperature_c = None

        self.select_measurement_humidity_device_id = None
        self.select_measurement_humidity_measurement_id = None
        self.max_measure_age_humidity = None

        # Newly added Leaf Temp related options
        self.select_measurement_leaf_temp_device_id = None
        self.select_measurement_leaf_temp_measurement_id = None
        self.max_measure_age_leaf_temp = None
        self.leaf_temp_offset = None

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

        # Air temperature
        temp_c = None
        # Humidity
        hum_percent = None
        # Leaf temperature
        leaf_temp_c = None
        # Final VPD result
        vpd_pa = None

        # 1) Measure air temperature
        last_measurement_temp = self.get_last_measurement(
            self.select_measurement_temperature_c_device_id,
            self.select_measurement_temperature_c_measurement_id,
            max_age=self.max_measure_age_temperature_c
        )
        self.logger.debug("Temp: {}".format(last_measurement_temp))

        if last_measurement_temp:
            device_measurement = get_measurement(
                self.select_measurement_temperature_c_measurement_id
            )
            if device_measurement is not None and getattr(device_measurement, 'conversion_id', None) is not None:
                conversion = db_retrieve_table_daemon(
                    Conversion, unique_id=device_measurement.conversion_id
                )
                channel, unit, measurement = return_measurement_info(
                    device_measurement, conversion
                )
                temp_c = convert_from_x_to_y_unit(unit, 'C', last_measurement_temp[1])
            else:
                self.logger.debug("Temperature measurement device_measurement is None or missing conversion_id, skipping temperature measurement.")

        # 2) Measure humidity
        last_measurement_hum = self.get_last_measurement(
            self.select_measurement_humidity_device_id,
            self.select_measurement_humidity_measurement_id,
            max_age=self.max_measure_age_humidity
        )
        self.logger.debug("Hum: {}".format(last_measurement_hum))

        if last_measurement_hum:
            device_measurement = get_measurement(
                self.select_measurement_humidity_measurement_id
            )
            if device_measurement is not None and getattr(device_measurement, 'conversion_id', None) is not None:
                conversion = db_retrieve_table_daemon(
                    Conversion, unique_id=device_measurement.conversion_id
                )
                channel, unit, measurement = return_measurement_info(
                    device_measurement, conversion
                )
                hum_percent = convert_from_x_to_y_unit(unit, 'percent', last_measurement_hum[1])
            else:
                self.logger.debug("Humidity measurement device_measurement is None or missing conversion_id, skipping humidity measurement.")

        # 3) Measure leaf temperature (if missing, apply offset to air temperature)
        if temp_c is not None and hum_percent is not None:
            last_measurement_leaf = self.get_last_measurement(
                self.select_measurement_leaf_temp_device_id,
                self.select_measurement_leaf_temp_measurement_id,
                max_age=self.max_measure_age_leaf_temp
            )
            self.logger.debug("Leaf Temp: {}".format(last_measurement_leaf))

            # Check both that the list exists and the measurement value is not None
            if (last_measurement_leaf
                and last_measurement_leaf[1] is not None
                and self.select_measurement_leaf_temp_measurement_id):

                device_measurement = get_measurement(
                    self.select_measurement_leaf_temp_measurement_id
                )

                # Also check whether device_measurement is None or conversion_id is None
                if device_measurement is not None and getattr(device_measurement, 'conversion_id', None) is not None:
                    conversion = db_retrieve_table_daemon(
                        Conversion, unique_id=device_measurement.conversion_id
                    )
                    channel, unit, measurement = return_measurement_info(
                        device_measurement, conversion
                    )
                    leaf_temp_c = convert_from_x_to_y_unit(unit, 'C', last_measurement_leaf[1])
                else:
                    # If device_measurement could not be retrieved properly, use the offset
                    self.logger.debug("device_measurement is missing or invalid, applying offset")
                    leaf_temp_c = temp_c + self.leaf_temp_offset

            else:
                # If leaf temperature is not measured -> air temperature + offset
                # Default offset: -1.5 => (if air temperature is 25C, leaf temperature is assumed to be 23.5C)
                leaf_temp_c = temp_c + self.leaf_temp_offset

            # 4) Calculate VPD
            try:
                vpd_pa = calculate_vapor_pressure_deficit(leaf_temp_c, hum_percent)
            except TypeError as err:
                self.logger.error("Error while calculating VPD: {msg}".format(msg=err))

        # 5) Store measurement and send to InfluxDB
        if vpd_pa is not None:
            measurement_dict = copy.deepcopy(measurements_dict)

            # Reuse the existing measurements_dict[0] structure
            dev_measurement = self.channels_measurement[0]
            channel, unit, measurement = return_measurement_info(
                dev_measurement, self.channels_conversion[0]
            )

            # Convert from base unit (Pa) to the AoT storage unit (unit)
            vpd_store = convert_from_x_to_y_unit('Pa', unit, vpd_pa)

            measurement_dict[0] = {
                'measurement': measurement,
                'unit': unit,
                'value': vpd_store
            }

            self.logger.debug(
                "Adding measurement to InfluxDB (ID: {}): {}".format(
                    self.unique_id, measurement_dict
                )
            )
            add_measurements_influxdb(self.unique_id, measurement_dict)
        else:
            self.logger.debug("Temperature/humidity not sufficiently available, cannot calculate VPD.")