# coding=utf-8
#
#  이 소프트웨어는 오픈소스 Mycodo 프로젝트(© Kyle T. Gabriel)를 기반으로
#  AoT 프로젝트 목적에 맞게 수정된 파생 버전입니다.
#
#  Copyright (C) 2025 AoT (aot.inc.kr@gmail.com)
#
#  본 파일은 GNU GPLv3 라이선스에 따라 배포됩니다.
#  원본 저작권 및 라이선스 조건은 아래에 명시되어 있습니다.
#
#  2025-04-21

import copy
import requests

from aot.inputs.base_input import AbstractInput
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.config_devices_units import MEASUREMENTS, UNITS, UNIT_CONVERSIONS

measurements_dict = {
    1:  {'measurement': 'temperature',   'unit': 'C',      'name': '실외기온'},       # data['outdoor']['temperature'] (기본 단위 섭씨)
    2:  {'measurement': 'humidity',      'unit': 'percent','name': '실외습도'},       # data['outdoor']['humidity']
    3:  {'measurement': 'dewpoint',      'unit': 'C',      'name': '실외이슬점'},     # data['outdoor']['dew_point']
    4:  {'measurement': 'temperature',   'unit': 'C',      'name': '실내기온'},       # data['indoor']['temperature']
    5:  {'measurement': 'humidity',      'unit': 'percent','name': '실내습도'},       # data['indoor']['humidity']
    6:  {'measurement': 'pressure',      'unit': 'hPa',    'name': '기압'},           # data['pressure']['absolute'] (농업 일반 기압: hPa)
    7:  {'measurement': 'direction',     'unit': 'bearing','name': '풍향'},           # data['wind']['wind_direction']
    8:  {'measurement': 'speed',         'unit': 'm_s',    'name': '풍속'},           # data['wind']['wind_speed']
    9:  {'measurement': 'radiation',     'unit': 'W_m2',   'name': '일사량'},         # data['solar_and_uvi']['solar']
    10: {'measurement': 'uvi',           'unit': 'index',  'name': '자외선지수'},     # data['solar_and_uvi']['uvi']
    11: {'measurement': 'precipitation', 'unit': 'mm_h',   'name': '강수량'},         # data['rainfall']['rain_rate']
    12: {'measurement': 'battery',       'unit': 'bool','name': '실외배터리'},     # data['battery']['sensor_array']
    13: {'measurement': 'battery',       'unit': 'bool','name': '실내배터리'},     # data['battery']['indoor_sensor']
}

INPUT_INFORMATION = {
    'input_name_unique': 'ecowitt_weather',
    'input_manufacturer': 'Ecowitt',
    'input_name': 'Ecowitt Cloud API Weather Data',
    'input_name_short': 'Ecowitt WS',
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
            'id': 'call_back',
            'type': 'text',
            'default_value': 'all',
            'required': False,
            'name': "Call Back",
            'phrase': "호출할 데이터 종류를 입력하세요 (예: all)."
        }
    ]
}


class InputModule(AbstractInput):
    """Ecowitt WS 시리즈: 실시간+히스토리(7일/증분) 동시지원"""

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
        for k, info in measurements_dict.items():
            if group in ('outdoor', 'indoor'):
                if info['measurement'] == sensor and info['name'].startswith('실외' if group == 'outdoor' else '실내'):
                    return k
            elif group == 'pressure':
                if sensor == 'absolute' and info['measurement'] == 'pressure':
                    return k
            elif group == 'wind':
                if sensor == 'wind_direction' and info['measurement'] == 'direction':
                    return k
                elif sensor == 'wind_speed' and info['measurement'] == 'speed':
                    return k
            elif group == 'solar_and_uvi':
                if sensor == 'solar' and info['measurement'] == 'radiation':
                    return k
                elif sensor == 'uvi' and info['measurement'] == 'uvi':
                    return k
            elif group == 'rainfall':
                if sensor == 'rain_rate' and info['measurement'] == 'precipitation':
                    return k
            elif group == 'battery':
                if '배터리' in info['name']:
                    return k
        return None

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