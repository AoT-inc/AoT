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
    'function_name_unique': 'AoT_VPD',  # 1. 고유 함수명 변경
    'function_name': 'AoT VPD',        # 1. 함수 이름 변경
    'measurements_dict': measurements_dict,
    'message': '이 함수는 잎 온도와 습도를 기반으로 증기압 부족분(VPD)을 계산합니다.'
               '잎의 온도가 입력되지 않은 경우, 잎의 온도 대신 잎 온도에 오프셋을 적용합니다.',

    'options_enabled': [
        'custom_options'
    ],

    # 2. custom_options 한글화 및 Leaf Temperature 옵션 추가
    'custom_options': [
        {
            'id': 'period',
            'type': 'text',
            'class': 'aot-time-input',
            'default_value': 60,
            'required': True,
            'constraints_pass': constraints_pass_positive_value,
            'name': "{} ({})".format(lazy_gettext('주기'), lazy_gettext('초')),
            'phrase': '측정 또는 동작 사이의 기간'
        },
        {
            'id': 'start_offset',
            'type': 'integer',
            'default_value': 10,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('시작 지연'), lazy_gettext('초')),
            'phrase': lazy_gettext('첫 번째 동작 전 대기 시간')
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
            'name': '대기 온도',
            'phrase': '대기 온도 측정'
        },
        {
            'id': 'max_measure_age_temperature_c',
            'type': 'integer',
            'default_value': 360,
            'required': False,
            'name': "{}: {} ({})".format(lazy_gettext('대기 온도'), lazy_gettext('최대 사용 연령'), lazy_gettext('초')),
            'phrase': lazy_gettext('사용할 측정값의 최대 연령')
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
            'name': '습도',
            'phrase': '습도 측정'
        },
        {
            'id': 'max_measure_age_humidity',
            'type': 'integer',
            'default_value': 360,
            'required': False,
            'name': "{}: {} ({})".format(lazy_gettext('습도'), lazy_gettext('최대 사용 연령'), lazy_gettext('초')),
            'phrase': lazy_gettext('사용할 측정값의 최대 연령')
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
            'name': '잎 온도',
            'phrase': '잎 온도 측정'
        },
        {
            'id': 'max_measure_age_leaf_temp',
            'type': 'integer',
            'default_value': 360,
            'required': False,
            'name': "{}: {} ({})".format(lazy_gettext('잎 온도'), lazy_gettext('최대 사용 시간'), lazy_gettext('초')),
            'phrase': lazy_gettext('사용할 측정값의 최대 시간')
        },
        {
            'id': 'leaf_temp_offset',
            'type': 'float',
            'default_value': -1.5,
            'required': True,
            'name': '잎 온도 오프셋(°C)',
            'phrase': '잎 온도가 입력되지 않았을 경우 적용할 오프셋(°C)'
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

        self.select_measurement_temperature_c_device_id = None
        self.select_measurement_temperature_c_measurement_id = None
        self.max_measure_age_temperature_c = None

        self.select_measurement_humidity_device_id = None
        self.select_measurement_humidity_measurement_id = None
        self.max_measure_age_humidity = None

        # 새로 추가된 Leaf Temp 관련 옵션
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

        # 기존 대기 온도
        temp_c = None
        # 습도
        hum_percent = None
        # 잎 온도
        leaf_temp_c = None
        # 최종 VPD 결과
        vpd_pa = None

        # 1) 대기 온도 측정
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

        # 2) 습도 측정
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

        # 3) 잎 온도 측정(없으면 대기 온도에서 오프셋 적용)
        if temp_c is not None and hum_percent is not None:
            last_measurement_leaf = self.get_last_measurement(
                self.select_measurement_leaf_temp_device_id,
                self.select_measurement_leaf_temp_measurement_id,
                max_age=self.max_measure_age_leaf_temp
            )
            self.logger.debug("Leaf Temp: {}".format(last_measurement_leaf))

            # ▼ 수정된 부분: 리스트 존재 여부 + 측정값(None 아님)을 모두 확인
            if (last_measurement_leaf
                and last_measurement_leaf[1] is not None
                and self.select_measurement_leaf_temp_measurement_id):

                device_measurement = get_measurement(
                    self.select_measurement_leaf_temp_measurement_id
                )

                # device_measurement가 None인지, 혹은 conversion_id가 None인지도 확인
                if device_measurement is not None and getattr(device_measurement, 'conversion_id', None) is not None:
                    conversion = db_retrieve_table_daemon(
                        Conversion, unique_id=device_measurement.conversion_id
                    )
                    channel, unit, measurement = return_measurement_info(
                        device_measurement, conversion
                    )
                    leaf_temp_c = convert_from_x_to_y_unit(unit, 'C', last_measurement_leaf[1])
                else:
                    # device_measurement를 제대로 가져오지 못했다면 오프셋 사용
                    self.logger.debug("device_measurement가 없거나 유효하지 않아, 오프셋 적용")
                    leaf_temp_c = temp_c + self.leaf_temp_offset

            else:
                # 잎 온도가 측정되지 않는 경우 -> 대기 온도 + 오프셋
                # 기본 오프셋: -1.5 => (대기 온도가 25도면, 잎 온도는 23.5도로 가정)
                leaf_temp_c = temp_c + self.leaf_temp_offset

            # 4) VPD 계산
            try:
                vpd_pa = calculate_vapor_pressure_deficit(leaf_temp_c, hum_percent)
            except TypeError as err:
                self.logger.error("VPD 계산 중 에러: {msg}".format(msg=err))

        # 5) 측정값 저장 및 InfluxDB 전송
        if vpd_pa is not None:
            measurement_dict = copy.deepcopy(measurements_dict)

            # 기존 measurements_dict[0] 구조 활용
            dev_measurement = self.channels_measurement[0]
            channel, unit, measurement = return_measurement_info(
                dev_measurement, self.channels_conversion[0]
            )

            # 기본 단위(Pa) -> AoT 내 저장 단위(unit)로 변환
            vpd_store = convert_from_x_to_y_unit('Pa', unit, vpd_pa)

            measurement_dict[0] = {
                'measurement': measurement,
                'unit': unit,
                'value': vpd_store
            }

            self.logger.debug(
                "InfluxDB에 측정값 추가(ID: {}): {}".format(
                    self.unique_id, measurement_dict
                )
            )
            add_measurements_influxdb(self.unique_id, measurement_dict)
        else:
            self.logger.debug("온도/습도가 충분히 확보되지 않아 VPD를 계산할 수 없습니다.")