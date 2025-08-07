# coding=utf-8
#
#  accumulated_temperature.py - Calculates daily GDD and cumulative accumulated temperature (GDD)
#
#  Copyright (C)
#
#  This file is part of AoT
#
#  AoT is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License.
#
#  Contact at aot-inc.com
#
import time
import datetime

from flask_babel import lazy_gettext

from aot.databases.models import Conversion
from aot.databases.models import CustomController
from aot.functions.base_function import AbstractFunction
from aot.aot_client import DaemonControl
from aot.utils.constraints_pass import constraints_pass_positive_value
from aot.utils.database import db_retrieve_table_daemon
from aot.utils.influx import add_measurements_influxdb
from aot.utils.system_pi import get_measurement
from aot.utils.system_pi import return_measurement_info

# 채널에 대한 기본 정보 (메시지와 단위 등)
measurements_dict = {
    0: {
        'measurement': '',
        'unit': '',
    }
}

# 함수 정보를 설정합니다.
FUNCTION_INFORMATION = {
    'function_name_unique': 'ACCUMULATED_TEMP',
    'function_name': '적산온도',
    'measurements_dict': measurements_dict,
    'enable_channel_unit_select': True,
    'message': (
        '이 함수는 지정된 센서 데이터를 기반으로 사용자가 선택한 기간 동안(시작 날짜 ~ 종료 날짜)의 '
        '하루 평균 온도를 계산하고, 기준 온도와의 차이를 이용하여 일일 GDD를 산출합니다. '
        '누적 GDD(적산온도)는 이전 일자의 누적값에 당일 GDD를 더하여 계산되며, 이 두 값을 데이터베이스에 저장합니다.'
    ),
    'options_enabled': [
        'measurements_select_measurement_unit',
        'custom_options'
    ],
    'custom_options': [
        {
            'id': 'measurement_start_time',
            'type': 'text',
            'default_value': '00:00',  # 측정 시작 시간 (예: 자정)
            'required': True,
            'name': lazy_gettext('Measurement Start Time'),
            'phrase': '측정 시작 시간을 입력하세요 (HH:MM 형식, 기본값 00:00)'
        },
        {
            'id': 'start_date',
            'type': 'text',
            'default_value': (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
            'required': True,
            'name': lazy_gettext('Start Date'),
            'phrase': '적산온도 계산 시작 날짜를 선택하세요 (YYYY-MM-DD). 기본값: 어제'
        },
        {
            'id': 'end_date',
            'type': 'text',
            'default_value': datetime.date.today().strftime('%Y-%m-%d'),
            'required': True,
            'name': lazy_gettext('End Date'),
            'phrase': '적산온도 계산 종료 날짜를 선택하세요 (YYYY-MM-DD). 기본값: 오늘'
        },
        {
            'id': 'base_temperature',
            'type': 'float',
            'default_value': 10.0,
            'required': True,
            'name': lazy_gettext('Base Temperature'),
            'phrase': '적산온도 계산을 위한 기준 온도를 입력하세요'
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
            'phrase': '적산온도 계산에 사용할 온도 측정값을 선택하세요'
        }
    ]
}


class CustomModule(AbstractFunction):
    """
    적산온도(GDD)를 계산하는 모듈입니다.
    
    - 사용자가 선택한 시작 날짜와 종료 날짜 동안, 지정한 측정 시작 시간부터 24시간의 센서 데이터를 조회하여
      해당 기간의 하루 평균 온도를 계산합니다.
    - 하루 평균 온도에서 기준 온도(base_temperature)를 뺀 값(음수이면 0 처리)이 그 날의 GDD가 됩니다.
    - 일일 GDD 값은 이전 누적값과 합산되어 누적 적산온도(누적 GDD)를 계산합니다.
    - 계산된 당일 GDD와 누적 GDD는 InfluxDB에 저장됩니다.
    """
    def __init__(self, function, testing=False):
        super().__init__(function, testing=testing, name=__name__)
        self.control = DaemonControl()

        # 센서 측정 채널 정보 (select_measurement 옵션을 통해 설정)
        self.select_measurement_device_id = None
        self.select_measurement_measurement_id = None

        # Custom options 설정
        custom_function = db_retrieve_table_daemon(CustomController, unique_id=self.unique_id)
        self.setup_custom_options(FUNCTION_INFORMATION['custom_options'], custom_function)

        self.measurement_start_time = self.custom_options.get('measurement_start_time', '00:00')
        self.start_date = self.custom_options.get('start_date', (datetime.date.today() - datetime.timedelta(days=1)).strftime('%Y-%m-%d'))
        self.end_date = self.custom_options.get('end_date', datetime.date.today().strftime('%Y-%m-%d'))
        self.base_temperature = float(self.custom_options.get('base_temperature', 10.0))

        if not testing:
            self.try_initialize()

    def query_daily_average(self, day, measurement_start_time):
        """
        주어진 날짜(day, datetime.date)와 측정 시작 시간(문자열, "HH:MM" 형식)을 기반으로
        24시간 동안의 센서 데이터를 조회하여 평균 온도를 계산합니다.
        반환 값: 산술 평균 온도 (float) 또는 데이터가 없으면 None
        """
        if self.select_measurement_device_id is None or self.select_measurement_measurement_id is None:
            self.logger.error("측정값 정보가 설정되지 않았습니다.")
            return None

        dt_start = datetime.datetime.combine(day, datetime.datetime.strptime(measurement_start_time, "%H:%M").time())
        dt_end = dt_start + datetime.timedelta(hours=24)

        from aot.databases.models import DeviceMeasurements, Conversion
        from aot.utils.influx import read_influxdb_list, return_measurement_info, db_retrieve_table_daemon

        device_measurement = db_retrieve_table_daemon(DeviceMeasurements).filter(
            DeviceMeasurements.unique_id == self.select_measurement_measurement_id).first()

        conversion = db_retrieve_table_daemon(Conversion, unique_id=device_measurement.conversion_id) if device_measurement else None

        channel, unit, measurement = return_measurement_info(device_measurement, conversion)

        start_str = dt_start.isoformat() + "Z"
        end_str = dt_end.isoformat() + "Z"

        measurements = read_influxdb_list(
            self.select_measurement_device_id,
            unit,
            channel,
            measure=measurement,
            start_str=start_str,
            end_str=end_str
        )
        if not measurements:
            return None

        # 모든 측정값 추출
        values = [value for (_, value) in measurements]
        if not values:
            return None

        # 산술 평균 계산
        average_temperature = sum(values) / len(values)
        return average_temperature

    def calculate_daily_gdd(self, average_temperature, base_temperature):
        """
        주어진 하루 평균 온도와 기준 온도를 사용하여 일일 GDD를 계산합니다.
        
        일일 GDD = max(average_temperature - base_temperature, 0)
        """
        daily_gdd = average_temperature - base_temperature
        if daily_gdd < 0:
            daily_gdd = 0
        return daily_gdd

    def loop(self):
        """
        지정한 날짜 범위(시작 날짜 ~ 종료 날짜)에 대해 각 날짜의 24시간 평균 온도, 일일 GDD, 누적 GDD를 계산한 후,
        오늘의 GDD와 누적 GDD를 InfluxDB에 저장합니다.
        """
        try:
            start_date_obj = datetime.datetime.strptime(self.start_date, '%Y-%m-%d').date()
            end_date_obj = datetime.datetime.strptime(self.end_date, '%Y-%m-%d').date()
        except Exception as e:
            self.logger.error(f"날짜 포맷 오류: {e}")
            return

        from aot.utils.influx import query_latest_value
        current_date = start_date_obj
        cumulative_gdd = query_latest_value(self.unique_id, 'cumulative') or 0.0
        daily_results = {}

        while current_date <= end_date_obj:
            avg_temp = self.query_daily_average(current_date, self.measurement_start_time)
            if avg_temp is None:
                self.logger.warning(f"{current_date}의 센서 데이터가 없습니다.")
                daily_gdd = 0.0
            else:
                daily_gdd = self.calculate_daily_gdd(avg_temp, self.base_temperature)
            cumulative_gdd += daily_gdd
            daily_results[current_date.strftime('%Y-%m-%d')] = {
                'daily_average': avg_temp if avg_temp is not None else 'No Data',
                'daily_gdd': daily_gdd,
                'cumulative_gdd': cumulative_gdd
            }
            current_date += datetime.timedelta(days=1)

        self.logger.debug("계산된 적산온도 결과: {}".format(daily_results))

        # 최신 날짜(종료 날짜) 데이터를 InfluxDB에 저장합니다.
        if daily_results:
            today_str = end_date_obj.strftime('%Y-%m-%d')
            today_data = daily_results[today_str]
            measurement_dict = {
                0: {
                    'measurement': self.channels_measurement[0].measurement,
                    'unit': self.channels_measurement[0].unit,
                    'fields': {
                        'daily_gdd': today_data['daily_gdd'],
                        'cumulative_gdd': today_data['cumulative_gdd']
                    }
                }
            }
            self.logger.debug(
                "InfluxDB에 저장할 적산온도 데이터 (ID {}): {}".format(
                    self.unique_id, measurement_dict))
            add_measurements_influxdb(self.unique_id, measurement_dict)
        else:
            self.logger.debug("저장할 적산온도 데이터가 없습니다.")