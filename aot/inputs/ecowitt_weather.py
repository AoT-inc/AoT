# coding=utf-8
#
#  This software is a derivative version based on the open-source Mycodo
#  project (© Kyle T. Gabriel), modified to suit the goals of the AoT project.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#
#  This file is distributed under the GNU GPLv3 license.
#  The original copyright and license terms are stated below.
#
#  2025-04-21

import copy
import requests

from flask_babel import lazy_gettext

from aot.inputs.base_input import AbstractInput
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.config_devices_units import MEASUREMENTS, UNITS, UNIT_CONVERSIONS
from aot.utils.safe_eval import safe_eval

measurements_dict = {
    1:  {'measurement': 'temperature',   'unit': 'C',      'name': lazy_gettext('Outdoor Temperature')},   # data['outdoor']['temperature'] (default unit Celsius)
    2:  {'measurement': 'humidity',      'unit': 'percent','name': lazy_gettext('Outdoor Humidity')},      # data['outdoor']['humidity']
    3:  {'measurement': 'dewpoint',      'unit': 'C',      'name': lazy_gettext('Outdoor Dew Point')},     # data['outdoor']['dew_point']
    4:  {'measurement': 'temperature',   'unit': 'C',      'name': lazy_gettext('Indoor Temperature')},    # data['indoor']['temperature']
    5:  {'measurement': 'humidity',      'unit': 'percent','name': lazy_gettext('Indoor Humidity')},       # data['indoor']['humidity']
    6:  {'measurement': 'pressure',      'unit': 'hPa',    'name': lazy_gettext('Pressure')},              # data['pressure']['absolute'] (typical agricultural pressure: hPa)
    7:  {'measurement': 'direction',     'unit': 'bearing','name': lazy_gettext('Wind Direction')},        # data['wind']['wind_direction']
    8:  {'measurement': 'speed',         'unit': 'm_s',    'name': lazy_gettext('Wind Speed')},            # data['wind']['wind_speed']
    9:  {'measurement': 'radiation',     'unit': 'W_m2',   'name': lazy_gettext('Solar Radiation')},       # data['solar_and_uvi']['solar']
    10: {'measurement': 'uvi',           'unit': 'index',  'name': lazy_gettext('UV Index')},              # data['solar_and_uvi']['uvi']
    11: {'measurement': 'precipitation', 'unit': 'mm_h',   'name': lazy_gettext('Precipitation')},         # data['rainfall']['rain_rate']
    12: {'measurement': 'battery',       'unit': 'bool',   'name': lazy_gettext('Outdoor Battery')},       # data['battery']['sensor_array']
    13: {'measurement': 'battery',       'unit': 'bool',   'name': lazy_gettext('Indoor Battery')},        # data['battery']['indoor_sensor']
}

INPUT_INFORMATION = {
    'input_name_unique': 'ecowitt_weather',
    'input_manufacturer': 'Ecowitt',
    'input_name': 'Ecowitt Cloud API Weather Data',
    'input_name_short': 'Ecowitt WS',
    'measurements_dict': measurements_dict,
    'message': lazy_gettext('To use the Ecowitt Cloud API, enter the Application Key, API Key, and device MAC address.'),

    'options_enabled': ['measurements_select'],

    'custom_options': [
        {
            'id': 'period',
            'type': 'float',
            'default_value': 60,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': lazy_gettext("Measurement Period (sec)"),
            'phrase': lazy_gettext("Enter the measurement interval in seconds.")
        },
        {
            'id': 'application_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext("Application Key"),
            'phrase': lazy_gettext("Enter the Application Key issued by the Ecowitt platform.")
        },
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext("API Key"),
            'phrase': lazy_gettext("Enter the API Key issued by the Ecowitt platform.")
        },
        {
            'id': 'mac',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': lazy_gettext("Device MAC"),
            'phrase': lazy_gettext("Enter the MAC address of the Ecowitt device.")
        },
        {
            'id': 'call_back',
            'type': 'text',
            'default_value': 'all',
            'required': False,
            'name': lazy_gettext("Call Back"),
            'phrase': lazy_gettext("Enter the type of data to request (e.g. all).")
        }
    ]
}


class InputModule(AbstractInput):
    """Sensor driver for Ecowitt weather station via Ecowitt Cloud API.

    Reads outdoor/indoor temperature, humidity, pressure, wind, solar radiation, UV index, rainfall, and battery status.

    @phase active
    @stability stable
    @dependency AbstractInput
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)
        if not hasattr(self.input_dev, 'options'):
            self.input_dev.options = {}
        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()

    def initialize(self):
        """Override initialize to satisfy AbstractInput requirements."""
        # No additional initialization required for this input module
        pass

    def match_idx(self, group, sensor):
        # Index-based mapping of (group, sensor) -> measurement key.
        # Uses fixed indices rather than display names so localized labels do not affect matching.
        if group == 'outdoor':
            return {'temperature': 1, 'humidity': 2, 'dew_point': 3}.get(sensor)
        if group == 'indoor':
            return {'temperature': 4, 'humidity': 5}.get(sensor)
        if group == 'pressure':
            return 6 if sensor == 'absolute' else None
        if group == 'wind':
            return {'wind_direction': 7, 'wind_speed': 8}.get(sensor)
        if group == 'solar_and_uvi':
            return {'solar': 9, 'uvi': 10}.get(sensor)
        if group == 'rainfall':
            return 11 if sensor == 'rain_rate' else None
        if group == 'battery':
            return {'sensor_array': 12, 'indoor_sensor': 13}.get(sensor)
        return None

    def convert_unit(self, value, from_unit, to_unit):
        if from_unit == to_unit or value is None:
            return value
        for src, dst, expr in UNIT_CONVERSIONS:
            if src == from_unit and dst == to_unit:
                try:
                    return safe_eval(expr, {'x': value})
                except Exception:
                    break
        return value

    def pre_fetch_data(self):
        try:
            response = requests.get(self.api_url, timeout=60)
            response.raise_for_status()
            result = response.json()
            data = result.get('data')
            if not data:
                return None
            self.raw_data_cache = data
            return data
        except Exception as e:
            return None

    def _extract_measurements(self, data):
        results = {}
        api_units = {
            'temperature': 'F',
            'humidity': 'percent',
            'dewpoint': 'F',
            'pressure': 'inHg',
            'direction': 'bearing',
            'speed': 'mph',
            'radiation': 'W_m2',
            'uvi': 'index',
            'precipitation': 'in_h',
            'battery': 'percent'
        }
        for idx, info in measurements_dict.items():
            desired_unit = info['unit']
            if idx == 1:
                source = data.get('outdoor', {}); api_field, api_unit = 'temperature', api_units['temperature']
            elif idx == 2:
                source = data.get('outdoor', {}); api_field, api_unit = 'humidity', api_units['humidity']
            elif idx == 3:
                source = data.get('outdoor', {}); api_field, api_unit = 'dew_point', api_units['dewpoint']
            elif idx == 4:
                source = data.get('indoor', {}); api_field, api_unit = 'temperature', api_units['temperature']
            elif idx == 5:
                source = data.get('indoor', {}); api_field, api_unit = 'humidity', api_units['humidity']
            elif idx == 6:
                source = data.get('pressure', {}); api_field, api_unit = 'absolute', api_units['pressure']
            elif idx == 7:
                source = data.get('wind', {}); api_field, api_unit = 'wind_direction', api_units['direction']
            elif idx == 8:
                source = data.get('wind', {}); api_field, api_unit = 'wind_speed', api_units['speed']
            elif idx == 9:
                source = data.get('solar_and_uvi', {}); api_field, api_unit = 'solar', api_units['radiation']
            elif idx == 10:
                source = data.get('solar_and_uvi', {}); api_field, api_unit = 'uvi', api_units['uvi']
            elif idx == 11:
                source = data.get('rainfall', {}); api_field, api_unit = 'rain_rate', api_units['precipitation']
            elif idx == 12:
                source = data.get('battery', {}); api_field, api_unit = 'sensor_array', api_units['battery']
            elif idx == 13:
                source = data.get('battery', {}); api_field, api_unit = 'indoor_sensor', api_units['battery']
            else:
                continue
            entry = source.get(api_field)
            value = None
            if isinstance(entry, dict):
                try:
                    raw_val = float(entry.get('value'))
                    if isinstance(raw_val, (int, float)):
                        value = self.convert_unit(raw_val, api_unit, desired_unit)
                except (TypeError, ValueError):
                    continue
            elif isinstance(entry, (int, float)):
                value = entry
            if isinstance(value, (int, float)):
                results[idx] = value
        return results

    def get_measurement(self):
        self.application_key = self.get_custom_option('application_key')
        self.api_key = self.get_custom_option('api_key')
        self.mac = self.get_custom_option('mac')
        self.api_url = (
            f"https://api.ecowitt.net/api/v3/device/real_time"
            f"?application_key={self.application_key}"
            f"&api_key={self.api_key}"
            f"&mac={self.mac}"
            f"&call_back=all"
        )
        if not (self.application_key and self.api_key and self.mac):
            return
        self.return_dict = copy.deepcopy(measurements_dict)
        data = self.pre_fetch_data()
        if data is None:
            return
        measurements = self._extract_measurements(data)
        for idx, val in measurements.items():
            if self.is_enabled(idx):
                self.value_set(idx, val)
        return self.return_dict