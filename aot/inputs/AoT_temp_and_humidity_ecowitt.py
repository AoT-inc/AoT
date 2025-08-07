# coding=utf-8

import copy
import requests
import datetime

from aot.inputs.base_input import AbstractInput
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.config_devices_units import MEASUREMENTS, UNITS, UNIT_CONVERSIONS

measurements_dict = {
    1: {'measurement': 'temperature',   'unit': 'F',      'name': '온도'},       # 채널별 온도
    2: {'measurement': 'humidity',      'unit': 'percent','name': '습도'},       # 채널별 습도
    3: {'measurement': 'battery',       'unit': 'bool',       'name': '배터리'},     # 채널별 배터리
}

INPUT_INFORMATION = {
    'input_name_unique': 'AoT_temp_humidity_sensor_ecowitt',
    'input_manufacturer': 'AoT',
    'input_name': 'Ecowitt temp_humidity_sensor',
    'input_name_short': '온습도 ',
    'measurements_dict': measurements_dict,
    'message': 'Ecowitt Cloud API를 사용하려면 Application Key, API Key, 장치 MAC 주소를 입력하세요.',
    'options_enabled': ['measurements_select'],

    'custom_options': [
        {
            'id': 'period',
            'type': 'float',
            'default_value': 60,
            'required': False,
            'constraints_pass': constraints_pass_positive_value,
            'name': "측정 기간(초)",
            'phrase': "측정 주기를 초 단위로 입력하세요."
        },
        {
            'id': 'application_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': "Application Key",
            'phrase': "Ecowitt 플랫폼에서 발급받은 Application Key를 입력하세요."
        },
        {
            'id': 'api_key',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': "API Key",
            'phrase': "Ecowitt 플랫폼에서 발급받은 API Key를 입력하세요."
        },
        {
            'id': 'mac',
            'type': 'text',
            'default_value': '',
            'required': True,
            'name': "Device MAC",
            'phrase': "Ecowitt 장치의 MAC 주소를 입력하세요."
        },
        {
            'id': 'channels',
            'type': 'text',
            'default_value': '1',
            'required': False,
            'name': "채널 선택",
            'phrase': "측정할 채널을 선택하세요."
        }
    ]
}


class InputModule(AbstractInput):
    """Ecowitt WS 시리즈: 실시간+히스토리(7일/증분) 동시지원"""

    def __init__(self, input_dev, testing=False):
        super().__init__(input_dev, testing=testing, name=__name__)
        if not hasattr(self.input_dev, 'options'):
            self.input_dev.options = {}
        self.latest_datetime = None  # 증분 수집 시 마지막 저장 시간(UTC)
        self.first_run = True
        if not testing:
            self.setup_custom_options(INPUT_INFORMATION['custom_options'], input_dev)
            self.try_initialize()
            # 최초 실행: 과거 7일 히스토리 적재

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
        measurements = {}
        for ch in channels:
            entry = data.get(f'temp_and_humidity_ch{ch}')
            if isinstance(entry, dict):
                temp = entry.get('temperature', {}).get('value')
                hum = entry.get('humidity', {}).get('value')
                if temp is not None:
                    try:
                        temp_val = float(temp)
                        if isinstance(temp_val, (int, float)):
                            measurements[(1, ch)] = temp_val
                    except (TypeError, ValueError):
                        continue
                if hum is not None:
                    try:
                        hum_val = float(hum)
                        if isinstance(hum_val, (int, float)):
                            measurements[(2, ch)] = hum_val
                    except (TypeError, ValueError):
                        continue
            batt_entry = data.get('battery', {}).get(f'temp_humidity_sensor_ch{ch}')
            if isinstance(batt_entry, dict):
                batt = batt_entry.get('value')
                if batt is not None:
                    try:
                        batt_val = float(batt)
                        if isinstance(batt_val, (int, float)):
                            measurements[(3, ch)] = batt_val
                    except (TypeError, ValueError):
                        continue
        return measurements

    def get_measurement(self):
        self.return_dict = copy.deepcopy(measurements_dict)
        self.application_key = self.get_custom_option('application_key')
        self.api_key = self.get_custom_option('api_key')
        self.mac = self.get_custom_option('mac')
        chosen = self.get_custom_option('channels') or []
        channels = [int(c) for c in chosen if c.isdigit() and 1 <= int(c) <= 8]
        if not channels: channels = list(range(1,9))
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