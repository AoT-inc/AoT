# coding=utf-8

import copy
import requests
import datetime

from flask_babel import lazy_gettext

from aot.inputs.base_input import AbstractInput
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.config_devices_units import MEASUREMENTS, UNITS, UNIT_CONVERSIONS

measurements_dict = {
    1: {'measurement': 'moisture', 'unit': 'percent', 'name': lazy_gettext('Soil Moisture')},
    2: {'measurement': 'unitless', 'unit': 'none',    'name': 'AD'},
    3: {'measurement': 'battery',  'unit': 'bool',    'name': lazy_gettext('Battery')},
}

INPUT_INFORMATION = {
    'input_name_unique': 'ecowitt_soil_sensor',
    'input_manufacturer': 'Ecowitt',
    'input_name': 'Ecowitt soil_sensor',
    'input_name_short': 'Ecowitt Soil Sensor',
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
            'id': 'channels',
            'type': 'text',
            'default_value': '1',
            'required': False,
            'name': lazy_gettext("Channel Selection"),
            'phrase': lazy_gettext("Select the channel to measure.")
        }
    ]
}


class InputModule(AbstractInput):
    """Sensor driver for Ecowitt soil moisture sensor via Ecowitt Cloud API.

    Reads soil moisture, AD value, and battery status from Ecowitt soil sensor.

    @phase active
    @stability stable
    @dependency AbstractInput
    """

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)
        if not hasattr(self.input_dev, 'options'):
            self.input_dev.options = {}
        self.latest_datetime = None  # last stored time (UTC) for incremental collection
        self.first_run = True
        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()
            # First run: load the past 7 days of history

    def initialize(self):
        """Override AbstractInput.initialize to satisfy requirement."""
        return


    def convert_unit(self, value, from_unit, to_unit):
        if from_unit == to_unit or value is None:
            return value
        for src, dst, expr in UNIT_CONVERSIONS:
            if src == from_unit and dst == to_unit:
                x = value
                try:
                    return eval(expr)
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
                self.logger.error("No data field in Ecowitt response.")
                return None
            self.raw_data_cache = data
            return data
        except Exception as e:
            self.logger.error(f"Error fetching Ecowitt data: {e}")
            return None

    def _extract_measurements(self, data, channels):
        results = {}
        for ch in channels:
            entry = data.get(f'soil_ch{ch}', {})
            if isinstance(entry, dict):
                # Soil moisture percentage
                mo = entry.get('soilmoisture', {}).get('value')
                try:
                    mo_val = float(mo)
                    if isinstance(mo_val, (int, float)):
                        results[(1, ch)] = mo_val
                except (TypeError, ValueError):
                    continue
                # Raw AD channel value
                ad = entry.get('ad', {}).get('value')
                try:
                    ad_val = float(ad)
                    if isinstance(ad_val, (int, float)):
                        results[(2, ch)] = ad_val
                except (TypeError, ValueError):
                    continue
        return results

    def get_measurement(self):
        self.return_dict = copy.deepcopy(measurements_dict)
        self.application_key = self.get_custom_option('application_key')
        self.api_key = self.get_custom_option('api_key')
        self.mac = self.get_custom_option('mac')
        chosen = self.get_custom_option('channels') or []
        channels = [int(c) for c in chosen if c.isdigit() and 1 <= int(c) <= 16]
        if not channels: channels = list(range(1,17))
        self.api_url = (
            f"https://api.ecowitt.net/api/v3/device/real_time"
            f"?application_key={self.application_key}"
            f"&api_key={self.api_key}"
            f"&mac={self.mac}"
            f"&call_back=all"
        )
        data = self.pre_fetch_data()
        if not data:
            return
        measurements = self._extract_measurements(data, channels)
        for (idx, ch), val in measurements.items():
            if self.is_enabled(idx):
                self.value_set(idx, val)
        return self.return_dict